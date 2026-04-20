"""Scraper orchestration for Moltbook."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

from src.client import MoltbookClient, _normalize_agent
from src.database import Database


class ValidationError(Exception):
    """Raised when scraped data fails validation against baseline."""
    pass


class Scraper:
    """Orchestrates scraping of Moltbook data."""

    def __init__(
        self,
        client: MoltbookClient,
        db: Database,
        on_progress: Optional[Callable[[str], None]] = None,
        max_workers: int = 1,
    ):
        self.client = client
        self.db = db
        self.on_progress = on_progress
        self.max_workers = max_workers
        self._baseline_counts = None

    def _log(self, message: str):
        """Log progress message."""
        if self.on_progress:
            self.on_progress(message)

    def _load_baseline(self):
        """Load baseline counts from platform stats API for validation."""
        if self._baseline_counts is None:
            try:
                self._baseline_counts = self.client.fetch_platform_stats()
                self._log(f"Platform stats: {self._baseline_counts}")
            except Exception as e:
                # Fall back to snapshot counts if stats API fails
                self._baseline_counts = self.db.get_latest_snapshot_counts()
                self._log(f"Platform stats unavailable, using snapshot baseline: {self._baseline_counts}")
        return self._baseline_counts

    def _validate_count(self, entity: str, scraped_count: int):
        """Validate scraped count against baseline. Raises ValidationError if lower.

        Also checks DB count - if DB already has enough entities, validation passes
        even if this particular run didn't fetch that many.
        """
        baseline = self._load_baseline()
        expected = baseline.get(entity, 0)
        # Skip validation if platform reports 0 (broken stat)
        if expected == 0:
            self._log(f"Skipping {entity} validation (platform reports 0)")
            return

        # Comments have a known ~200-comment-per-request cap in the API,
        # so we can never reach the platform's reported total.
        # Allow up to 20% gap for comments.
        if entity == "comments":
            tolerance = 0.80  # Accept 80% of expected
        else:
            tolerance = 1.0  # Require 100% for other entities

        minimum = int(expected * tolerance)

        # Check DB count - if we already have enough, we're good
        if entity == "submolts":
            db_count = len(self.db.get_all_submolt_names())
        elif entity == "posts":
            db_count = len(self.db.get_all_post_ids())
        elif entity == "comments":
            db_count = self.db.get_comment_count()
        elif entity == "agents":
            db_count = len(self.db.get_all_agent_names())
        else:
            db_count = scraped_count

        # Pass if either scraped count or DB count meets minimum
        if scraped_count >= minimum or db_count >= minimum:
            if scraped_count < minimum:
                self._log(f"  {entity}: scraped {scraped_count} this run, but DB has {db_count} (>= {minimum} required)")
            return

        raise ValidationError(
            f"{entity}: scraped {scraped_count}, DB has {db_count}, but expected at least {minimum} "
            f"({int(tolerance*100)}% of {expected} from platform stats). "
            f"API may be returning incomplete data."
        )

    def scrape_submolts(self):
        """Fetch and store all submolts (saves each page immediately)."""
        # Get target count from platform stats
        baseline = self._load_baseline()
        target = baseline.get("submolts", 0)
        self._log(f"Fetching submolts (target: {target} unique)...")

        total_saved = [0]  # Use list for closure

        def on_page(page_num, submolts):
            for submolt in submolts:
                # Normalize created_by agent if present
                if submolt.get("created_by") and isinstance(submolt["created_by"], dict):
                    agent = _normalize_agent(submolt["created_by"])
                    if agent.get("name"):
                        self.db.upsert_agent(agent)
                self.db.upsert_submolt(submolt)
            self.db.commit()
            total_saved[0] += len(submolts)
            self._log(f"  Page {page_num}: saved {len(submolts)} submolts ({total_saved[0]} unique total)")

        self.client.fetch_submolts_streaming(on_page=on_page, target_count=target)
        self._log(f"Stored {total_saved[0]} unique submolts")

        # Validate against baseline
        self._validate_count("submolts", total_saved[0])

    def scrape_posts(self, detect_deletions: bool = False):
        """Fetch and store all posts (saves each page immediately).

        Args:
            detect_deletions: If True, after full pagination, mark posts in DB
                            that were not seen as deleted.
        """
        # Get target count from platform stats
        baseline = self._load_baseline()
        target = baseline.get("posts", 0)
        self._log(f"Fetching all posts (target: {target} unique)...")
        if detect_deletions:
            self._log("  Deletion detection enabled — will mark unseen posts as deleted")

        total_saved = [0]  # Use list for closure
        seen_ids = set()

        def on_page(page_num, posts):
            for post in posts:
                self.db.upsert_post(post)
                seen_ids.add(post["id"])
                if post.get("author"):
                    self.db.upsert_agent(_normalize_agent(post["author"]))
                if post.get("submolt") and isinstance(post["submolt"], dict):
                    self.db.upsert_submolt(post["submolt"])
            self.db.commit()
            total_saved[0] += len(posts)
            self._log(f"  Page {page_num}: saved {len(posts)} posts ({total_saved[0]} unique total)")

        self.client.fetch_posts_streaming(on_page=on_page, target_count=target)
        self._log(f"Stored {total_saved[0]} unique posts")

        # Post deletion detection
        if detect_deletions and seen_ids:
            all_db_ids = set(self.db.get_all_post_ids())
            missing_ids = [pid for pid in all_db_ids if pid not in seen_ids]
            if missing_ids:
                self.db.mark_posts_deleted(missing_ids)
                self.db.commit()
                self._log(f"  Marked {len(missing_ids)} posts as deleted (not seen in full scrape)")
            else:
                self._log("  No deleted posts detected")

        # Validate against baseline
        self._validate_count("posts", total_saved[0])

    def scrape_posts_incremental(self) -> int:
        """Fetch new posts using cursor-based pagination with sort=new.

        Pages backward from newest. Stops after 3 consecutive pages where
        all posts are already in the DB. UPSERTs all posts encountered
        (updating vote counts and comment_count for known posts).

        Returns:
            Number of new posts found.
        """
        self._log("Fetching new posts (incremental, sort=new)...")

        # Load known post IDs into a set for O(1) lookup
        known_ids = set(self.db.get_all_post_ids())
        self._log(f"  {len(known_ids):,} posts already in DB")

        new_count = 0
        updated_count = 0
        cursor = None
        page = 0
        consecutive_known_pages = 0
        max_consecutive_known = 3

        try:
            while True:
                result = self.client.fetch_posts(limit=100, cursor=cursor, sort="new")
                posts = result["posts"]
                if not posts:
                    break

                page += 1
                page_new = 0

                for post in posts:
                    self.db.upsert_post(post)
                    if post.get("author"):
                        self.db.upsert_agent(_normalize_agent(post["author"]))
                    if post.get("submolt") and isinstance(post["submolt"], dict):
                        self.db.upsert_submolt(post["submolt"])

                    if post["id"] not in known_ids:
                        new_count += 1
                        page_new += 1
                        known_ids.add(post["id"])
                    else:
                        updated_count += 1

                self.db.commit()

                if page_new == 0:
                    consecutive_known_pages += 1
                    if consecutive_known_pages >= max_consecutive_known:
                        self._log(f"  Stopping: {max_consecutive_known} consecutive pages with no new posts")
                        break
                else:
                    consecutive_known_pages = 0

                if page % 10 == 0:
                    self._log(f"  Page {page}: {new_count:,} new, {updated_count:,} updated")

                if not result["has_more"]:
                    break
                cursor = result["next_cursor"]
                if not cursor:
                    break

            self._log(f"Incremental scrape: {new_count:,} new posts, {updated_count:,} updated across {page} pages")
            return new_count

        except KeyboardInterrupt:
            self._log(f"Interrupted! Saving {new_count:,} new posts found so far...")
            self.db.commit()
            raise
        except Exception as e:
            self._log(f"Error: {e}. Saving {new_count:,} new posts found so far...")
            self.db.commit()
            raise

    def scrape_moderators(self):
        """Fetch moderators for all submolts."""
        submolt_names = self.db.get_all_submolt_names()
        self._log(f"Fetching moderators for {len(submolt_names)} submolts...")

        total_mods = 0
        error_count = 0

        if self.max_workers <= 1:
            # Sequential path
            for i, name in enumerate(submolt_names):
                try:
                    moderators = self.client.fetch_submolt_moderators(name)
                    for mod in moderators:
                        agent_name = mod.get("agent", {}).get("name") or mod.get("name")
                        if agent_name:
                            self.db.upsert_moderator(name, agent_name, mod.get("role"))
                            total_mods += 1
                    self.db.commit()
                except Exception:
                    error_count += 1
                if (i + 1) % 100 == 0:
                    self._log(f"  Progress: {i + 1}/{len(submolt_names)} ({total_mods} moderators, {error_count} errors)")
        else:
            # Concurrent path: HTTP in worker threads, DB writes in main thread
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_name = {
                    executor.submit(self.client.fetch_submolt_moderators, name): name
                    for name in submolt_names
                }
                for i, future in enumerate(as_completed(future_to_name)):
                    name = future_to_name[future]
                    try:
                        moderators = future.result()
                        for mod in moderators:
                            agent_name = mod.get("agent", {}).get("name") or mod.get("name")
                            if agent_name:
                                self.db.upsert_moderator(name, agent_name, mod.get("role"))
                                total_mods += 1
                        self.db.commit()
                    except Exception:
                        error_count += 1
                    if (i + 1) % 100 == 0:
                        self._log(f"  Progress: {i + 1}/{len(submolt_names)} ({total_mods} moderators, {error_count} errors)")

        self._log(f"Stored {total_mods} moderator relationships ({error_count} errors)")

    def enrich_agents(self, only_missing: bool = False):
        """Fetch full profiles for agents.

        Args:
            only_missing: If True, only enrich agents without a description (stubs).
                         If False, enrich all agents (re-fetches already-enriched ones).
        """
        if only_missing:
            agents = self.db.get_unenriched_agent_names()
        else:
            agents = self.db.get_all_agent_names()
        self._log(f"Enriching {len(agents)} agent profiles...")

        success_count = 0
        error_count = 0

        deleted_count = 0

        if self.max_workers <= 1:
            # Sequential path
            for i, name in enumerate(agents):
                try:
                    profile = self.client.fetch_agent_profile(name)
                    if profile:
                        self.db.upsert_agent(profile)
                        success_count += 1
                    else:
                        # None means 404 / not found — agent likely deleted
                        self._mark_agent_deleted(name)
                        deleted_count += 1
                except Exception:
                    error_count += 1
                if (i + 1) % 100 == 0:
                    self._log(f"  Progress: {i + 1}/{len(agents)} ({success_count} enriched, {deleted_count} deleted, {error_count} errors)")
        else:
            # Concurrent path: HTTP in worker threads, DB writes in main thread
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_name = {
                    executor.submit(self.client.fetch_agent_profile, name): name
                    for name in agents
                }
                for i, future in enumerate(as_completed(future_to_name)):
                    name = future_to_name[future]
                    try:
                        profile = future.result()
                        if profile:
                            self.db.upsert_agent(profile)
                            success_count += 1
                        else:
                            self._mark_agent_deleted(name)
                            deleted_count += 1
                    except Exception:
                        error_count += 1
                    if (i + 1) % 100 == 0:
                        self._log(f"  Progress: {i + 1}/{len(agents)} ({success_count} enriched, {deleted_count} deleted, {error_count} errors)")

        del_msg = f", {deleted_count} marked deleted" if deleted_count else ""
        self._log(f"Enriched {success_count} agents ({error_count} errors{del_msg})")

    def _mark_agent_deleted(self, name: str):
        """Mark an agent as deleted (404 from profile endpoint)."""
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        self.db.conn.execute("""
            UPDATE agents SET deleted_at = ?
            WHERE name = ? AND deleted_at IS NULL
        """, (now, name))

    def scrape_comments(self, only_missing: bool = False, skip_empty: bool = False,
                        detect_deletions: bool = False):
        """Fetch comments for posts.

        Args:
            only_missing: If True, only fetch comments for posts without any comments.
                         If False, fetch for all posts (updates existing).
            skip_empty: If True, skip posts where comment_count == 0 (platform reports
                        no comments). Reduces API requests by ~74% on the current corpus.
            detect_deletions: If True, compare API response with DB and mark comments
                            that are no longer returned as deleted. Only meaningful when
                            not using only_missing (needs to re-fetch posts that already
                            have comments). Incompatible with only_missing.
        """
        if detect_deletions and only_missing:
            self._log("Warning: --detect-deletions is ignored with --only-missing (no existing comments to compare)")
            detect_deletions = False

        baseline = self._load_baseline()
        target = baseline.get("comments", 0)

        if only_missing and skip_empty:
            post_ids = self.db.get_post_ids_without_comments_with_activity()
            self._log(f"Fetching comments for {len(post_ids)} posts (missing only, skip empty)...")
        elif only_missing:
            post_ids = self.db.get_post_ids_without_comments()
            self._log(f"Fetching comments for {len(post_ids)} posts (missing only)...")
        elif skip_empty:
            post_ids = self.db.get_all_post_ids_with_activity()
            self._log(f"Fetching comments for {len(post_ids)} posts (skip empty)...")
        else:
            post_ids = self.db.get_all_post_ids()
            self._log(f"Fetching comments for {len(post_ids)} posts (target: ~{target} comments)...")

        if detect_deletions:
            self._log("  Deletion detection enabled — will mark comments missing from API")

        total_comments = 0
        error_count = 0
        deleted_count = 0

        if self.max_workers <= 1:
            # Sequential path
            for i, post_id in enumerate(post_ids):
                try:
                    comments = self.client.fetch_comments_only(post_id)
                    if comments:
                        self._store_comments_recursive(comments, post_id)
                        total_comments += self._count_comments_recursive(comments)

                    if detect_deletions:
                        api_ids = self._collect_comment_ids_recursive(comments) if comments else set()
                        deleted_count += self._detect_deleted_comments(post_id, api_ids)

                    self.db.commit()
                except Exception as e:
                    error_count += 1
                    if error_count <= 5:
                        self._log(f"  Error fetching comments for post {post_id}: {type(e).__name__}: {e}")
                if (i + 1) % 50 == 0:
                    del_msg = f", {deleted_count} deleted" if detect_deletions else ""
                    self._log(f"  Progress: {i + 1}/{len(post_ids)} posts ({total_comments} comments, {error_count} errors{del_msg})")
        else:
            # Concurrent path: HTTP in worker threads, DB writes in main thread
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_pid = {
                    executor.submit(self.client.fetch_comments_only, pid): pid
                    for pid in post_ids
                }
                for i, future in enumerate(as_completed(future_to_pid)):
                    post_id = future_to_pid[future]
                    try:
                        comments = future.result()
                        if comments:
                            self._store_comments_recursive(comments, post_id)
                            total_comments += self._count_comments_recursive(comments)

                        if detect_deletions:
                            api_ids = self._collect_comment_ids_recursive(comments) if comments else set()
                            deleted_count += self._detect_deleted_comments(post_id, api_ids)

                        self.db.commit()
                    except Exception as e:
                        error_count += 1
                        if error_count <= 5:
                            self._log(f"  Error fetching comments for post {post_id}: {type(e).__name__}: {e}")
                    if (i + 1) % 50 == 0:
                        del_msg = f", {deleted_count} deleted" if detect_deletions else ""
                        self._log(f"  Progress: {i + 1}/{len(post_ids)} posts ({total_comments} comments, {error_count} errors{del_msg})")

        del_msg = f", {deleted_count} marked deleted" if detect_deletions else ""
        self._log(f"Stored {total_comments} comments ({error_count} errors{del_msg})")

        # Validate against baseline (only if not in only_missing mode)
        if not only_missing:
            self._validate_count("comments", total_comments)

    def _store_comments_recursive(self, comments: list, post_id: str):
        """Store comments and their nested replies."""
        for comment in comments:
            self.db.upsert_comment(comment, post_id)
            if comment.get("author"):
                self.db.upsert_agent(comment["author"])
            if comment.get("replies"):
                self._store_comments_recursive(comment["replies"], post_id)

    def _count_comments_recursive(self, comments: list) -> int:
        """Count total comments including nested replies."""
        count = len(comments)
        for comment in comments:
            if comment.get("replies"):
                count += self._count_comments_recursive(comment["replies"])
        return count

    def _collect_comment_ids_recursive(self, comments: list) -> set:
        """Collect all comment IDs from a nested comment tree."""
        ids = set()
        for comment in comments:
            ids.add(comment["id"])
            if comment.get("replies"):
                ids.update(self._collect_comment_ids_recursive(comment["replies"]))
        return ids

    def _detect_deleted_comments(self, post_id: str, api_comment_ids: set) -> int:
        """Mark comments in DB that are no longer returned by the API as deleted.

        Handles the 500-comment API cap: if the post's comment_count exceeds 500,
        missing comments are flagged as deletion_uncertain since they may just be
        beyond the API's return window rather than truly deleted.

        Returns:
            Number of comments newly marked as deleted.
        """
        existing_ids = self.db.get_comment_ids_for_post(post_id)
        missing_ids = [cid for cid in existing_ids if cid not in api_comment_ids]

        if not missing_ids:
            return 0

        # Check if post has more comments than the 500 API cap
        post = self.db.get_post(post_id)
        comment_count = post.get("comment_count", 0) if post else 0
        uncertain = comment_count > 500

        self.db.mark_comments_deleted(missing_ids, uncertain=uncertain)
        return len(missing_ids)

    # Boolean / enum fields whose transitions we record in *_events.
    # Change-driven: we only insert when the value differs from the last
    # recorded event_type row for that entity (or the first time we see it).
    _POST_EVENT_FIELDS = (
        "is_pinned", "is_locked", "is_deleted", "is_spam", "verification_status"
    )
    _AGENT_EVENT_FIELDS = ("is_claimed",)
    # Metric fields are the small-integer counters that trickle-change.
    # Posts use a 4-week age cutoff (audit shows 0.003% change rate; vote
    # velocity that matters happens in the first few weeks).
    _POST_AGE_CUTOFF_DAYS = 28

    def create_snapshots(self, scrape_run_id: int = None):
        """Change-driven snapshot writer (Phase 3 design — see session 21 log).

        Writes to narrow *_metrics and *_events tables only when values
        differ from the previous snapshot for the same entity. Sets first-
        observation anchor columns on live tables if still NULL.

        Emits R1 monitoring lines per table:
            <table>: entities_scanned=N, inserted_metrics=M, inserted_events=E
        See CLAUDE.md "Snapshot monitoring" for alert thresholds.
        """
        self._log("Creating snapshots (change-driven)...")

        self._snapshot_posts(scrape_run_id)
        self._snapshot_agents(scrape_run_id)
        self._snapshot_submolts(scrape_run_id)
        self._snapshot_moderators(scrape_run_id)
        # Comments: intentionally no-op. Audit shows 0.0000% change across all
        # columns on 9.88M pairs; live table + first_seen_at suffices.

        self.db.commit()
        self._log("Snapshots complete")

    # ----- Phase 3 per-entity snapshot helpers -----

    def _snapshot_posts(self, scrape_run_id):
        scanned = inserted_metrics = inserted_events = anchors_set = 0
        # 4-week age cutoff for metrics; anchors are set for every post regardless
        # (only costs a no-op UPDATE after the first time).
        # *_first columns are fetched so the event writer can fall back to them
        # when no prior event row exists — see the event-emission block below.
        cursor = self.db.conn.execute(f"""
            SELECT id, upvotes, downvotes, comment_count,
                   is_pinned, is_locked, is_deleted, is_spam, verification_status,
                   is_pinned_first, is_locked_first, is_deleted_first,
                   is_spam_first, verification_status_first,
                   hot_score, score, created_at,
                   (julianday('now') - julianday(created_at)) AS age_days
            FROM posts
        """)
        for row in cursor.fetchall():
            scanned += 1
            post_id = row["id"]

            # Anchors (every post, once). Skips if already set.
            # Boolean/enum anchors added in Migration 10 — capture initial state
            # so the event-log writer can skip first-observation emissions.
            anchors_set += self.db.set_post_anchors_if_unset(
                post_id, row["hot_score"], row["score"],
                row["is_pinned"], row["is_locked"], row["is_deleted"],
                row["is_spam"], row["verification_status"]
            )

            # Metrics (only for posts ≤ 4 weeks old)
            age = row["age_days"]
            if age is not None and age <= self._POST_AGE_CUTOFF_DAYS:
                last = self.db.get_latest_post_metrics(post_id)
                current = {
                    "upvotes": row["upvotes"],
                    "downvotes": row["downvotes"],
                    "comment_count": row["comment_count"],
                }
                if last is None or any(last[k] != current[k] for k in current):
                    inserted_metrics += self.db.insert_post_metric(
                        post_id, current["upvotes"], current["downvotes"],
                        current["comment_count"], scrape_run_id
                    )

            # Events (booleans / enums, no age cutoff — flips are rare anywhere).
            # Comparison logic:
            #   - If a prior event row exists, compare current vs. that value.
            #   - Otherwise, fall back to the *_first anchor: the initial state
            #     captured on the post's first observation. This covers the
            #     first genuine transition after anchoring. Without this
            #     fallback, first flips are silently lost (anchor holds old
            #     state forever, no event ever written).
            #   - If the anchor itself is NULL (not yet set — race where
            #     set_post_anchors_if_unset hasn't run), skip.
            # Gating on anchor-when-no-event avoids the ~718k first-run
            # baseline spike (Alert C) while still capturing transitions.
            for field in self._POST_EVENT_FIELDS:
                new_val = row[field]
                new_str = None if new_val is None else str(new_val)
                old_str = self.db.get_latest_post_event(post_id, field)
                if old_str is None:
                    anchor_val = row[f"{field}_first"]
                    if anchor_val is None:
                        continue
                    old_str = str(anchor_val)
                if old_str != new_str:
                    inserted_events += self.db.insert_post_event(
                        post_id, field, old_str, new_str, scrape_run_id
                    )

        self._log(
            f"  posts: entities_scanned={scanned}, inserted_metrics={inserted_metrics}, "
            f"inserted_events={inserted_events}, anchors_set={anchors_set}"
        )

    def _snapshot_agents(self, scrape_run_id):
        scanned = inserted_metrics = inserted_events = anchors_set = 0
        cursor = self.db.conn.execute("""
            SELECT name, description, karma, is_claimed, is_claimed_first,
                   follower_count, following_count
            FROM agents
        """)
        for row in cursor.fetchall():
            scanned += 1
            name = row["name"]

            # is_claimed anchor added in Migration 10 — avoids ~172k first-run
            # events where every existing claimed agent would look like a flip.
            anchors_set += self.db.set_agent_anchors_if_unset(
                name, row["description"], row["karma"],
                row["follower_count"], row["following_count"],
                row["is_claimed"]
            )

            last = self.db.get_latest_agent_metrics(name)
            current = {
                "karma": row["karma"],
                "follower_count": row["follower_count"],
                "following_count": row["following_count"],
            }
            if last is None or any(last[k] != current[k] for k in current):
                inserted_metrics += self.db.insert_agent_metric(
                    name, current["karma"], current["follower_count"],
                    current["following_count"], scrape_run_id
                )

            # Events: compare against last event; fall back to *_first anchor
            # when no event row exists yet (otherwise first flips are lost —
            # same pattern as _snapshot_posts).
            for field in self._AGENT_EVENT_FIELDS:
                new_val = row[field]
                new_str = None if new_val is None else str(new_val)
                old_str = self.db.get_latest_agent_event(name, field)
                if old_str is None:
                    anchor_val = row[f"{field}_first"]
                    if anchor_val is None:
                        continue
                    old_str = str(anchor_val)
                if old_str != new_str:
                    inserted_events += self.db.insert_agent_event(
                        name, field, old_str, new_str, scrape_run_id
                    )

        self._log(
            f"  agents: entities_scanned={scanned}, inserted_metrics={inserted_metrics}, "
            f"inserted_events={inserted_events}, anchors_set={anchors_set}"
        )

    def _snapshot_submolts(self, scrape_run_id):
        scanned = inserted_metrics = anchors_set = 0
        cursor = self.db.conn.execute("""
            SELECT name, description, subscriber_count FROM submolts
        """)
        for row in cursor.fetchall():
            scanned += 1
            name = row["name"]

            anchors_set += self.db.set_submolt_anchors_if_unset(
                name, row["description"], row["subscriber_count"]
            )

            last = self.db.get_latest_submolt_metrics(name)
            current = {"subscriber_count": row["subscriber_count"]}
            if last is None or last["subscriber_count"] != current["subscriber_count"]:
                inserted_metrics += self.db.insert_submolt_metric(
                    name, current["subscriber_count"], scrape_run_id
                )

        self._log(
            f"  submolts: entities_scanned={scanned}, inserted_metrics={inserted_metrics}, "
            f"anchors_set={anchors_set}"
        )

    def _snapshot_moderators(self, scrape_run_id):
        """Diff live `moderators` against latest moderator_events state.

        Emits:
          - 'added' for pairs new since last snapshot
          - 'role_changed' for pairs whose role changed
          - 'removed' for pairs that were active but vanished from the live table
        """
        live_pairs = self.db.get_all_moderator_pairs()
        live_set = {(s, a) for s, a, _ in live_pairs}
        scanned = len(live_pairs)
        inserted_events = 0

        for submolt, agent, role in live_pairs:
            prev = self.db.get_latest_moderator_state(submolt, agent)
            if prev is None or prev["event_type"] == "removed":
                inserted_events += self.db.insert_moderator_event(
                    submolt, agent, "added", role, scrape_run_id
                )
            elif prev.get("role") != role:
                inserted_events += self.db.insert_moderator_event(
                    submolt, agent, "role_changed", role, scrape_run_id
                )

        # Detect removals: active-from-events minus live.
        active_from_events = self.db.get_active_moderator_pairs_from_events()
        for pair in active_from_events - live_set:
            inserted_events += self.db.insert_moderator_event(
                pair[0], pair[1], "removed", None, scrape_run_id
            )

        self._log(
            f"  moderators: entities_scanned={scanned}, inserted_events={inserted_events}"
        )

    def full_scrape(self):
        """Run a complete scrape of all data."""
        run_id = self.db.start_scrape_run()
        self._log(f"Starting full scrape (run_id={run_id})...")

        validation_failures = []

        try:
            # Scrape each entity type, continuing even if validation fails
            try:
                self.scrape_submolts()
            except ValidationError as e:
                self._log(f"Validation warning: {e}")
                validation_failures.append("submolts")

            try:
                self.scrape_posts()
            except ValidationError as e:
                self._log(f"Validation warning: {e}")
                validation_failures.append("posts")

            try:
                self.scrape_comments()
            except ValidationError as e:
                self._log(f"Validation warning: {e}")
                validation_failures.append("comments")

            self.scrape_moderators()
            self.enrich_agents()
            self.create_snapshots(scrape_run_id=run_id)

            # Get final counts
            posts_count = len(self.db.get_all_post_ids())
            agents_count = len(self.db.get_all_agent_names())
            comments_count = self.db.get_comment_count()
            submolts_count = len(self.db.get_all_submolt_names())

            # Determine final status
            if validation_failures:
                status = f'incomplete: validation failed for {", ".join(validation_failures)}'
                self._log(f"Scrape incomplete - validation failed for: {', '.join(validation_failures)}")
            else:
                status = 'completed'
                self._log("Full scrape complete")

            self.db.complete_scrape_run(run_id, posts_count, agents_count, comments_count, submolts_count, status)

        except KeyboardInterrupt:
            # Record interruption and snapshot current state
            self._log("Interrupted! Creating snapshot of current state...")
            self.create_snapshots(scrape_run_id=run_id)
            posts_count = len(self.db.get_all_post_ids())
            agents_count = len(self.db.get_all_agent_names())
            comments_count = self.db.get_comment_count()
            submolts_count = len(self.db.get_all_submolt_names())
            self.db.complete_scrape_run(run_id, posts_count, agents_count, comments_count, submolts_count, 'interrupted')
            self._log("Partial scrape recorded.")
            raise
        except Exception as e:
            # Record failure and snapshot current state
            self._log(f"Failed: {e}. Creating snapshot of current state...")
            try:
                self.create_snapshots(scrape_run_id=run_id)
            except Exception:
                pass  # Don't let snapshot failure mask original error
            posts_count = len(self.db.get_all_post_ids())
            agents_count = len(self.db.get_all_agent_names())
            comments_count = self.db.get_comment_count()
            submolts_count = len(self.db.get_all_submolt_names())
            self.db.complete_scrape_run(run_id, posts_count, agents_count, comments_count, submolts_count, f'failed: {e}')
            raise
