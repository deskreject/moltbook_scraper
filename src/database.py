"""Database operations for Moltbook scraper."""

import sqlite3
import json
from datetime import datetime
from typing import Optional


class Database:
    """SQLite database for storing scraped Moltbook data."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        # WAL: readers and writers don't block each other. Forward-safe, persistent.
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                id TEXT,
                description TEXT,
                karma INTEGER,
                is_claimed BOOLEAN,
                follower_count INTEGER,
                following_count INTEGER,
                avatar_url TEXT,
                owner_json TEXT,
                metadata_json TEXT,
                created_at TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                title TEXT,
                content TEXT,
                url TEXT,
                author_name TEXT,
                submolt_name TEXT,
                upvotes INTEGER,
                downvotes INTEGER,
                comment_count INTEGER,
                is_pinned BOOLEAN,
                created_at TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS submolts (
                name TEXT PRIMARY KEY,
                id TEXT,
                display_name TEXT,
                description TEXT,
                subscriber_count INTEGER,
                avatar_url TEXT,
                banner_url TEXT,
                created_by_name TEXT,
                metadata_json TEXT,
                created_at TEXT,
                last_activity_at TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                agent_id TEXT,
                description TEXT,
                karma INTEGER,
                is_claimed BOOLEAN,
                follower_count INTEGER,
                following_count INTEGER,
                avatar_url TEXT,
                owner_json TEXT,
                metadata_json TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS scrape_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                completed_at TEXT,
                agents_scraped INTEGER,
                posts_scraped INTEGER,
                comments_scraped INTEGER,
                submolts_scraped INTEGER,
                status TEXT
            );

            CREATE TABLE IF NOT EXISTS comments (
                id TEXT PRIMARY KEY,
                post_id TEXT,
                parent_id TEXT,
                content TEXT,
                author_name TEXT,
                upvotes INTEGER,
                downvotes INTEGER,
                created_at TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS post_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                title TEXT,
                content TEXT,
                url TEXT,
                author_name TEXT,
                submolt_name TEXT,
                upvotes INTEGER,
                downvotes INTEGER,
                comment_count INTEGER,
                is_pinned BOOLEAN,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS comment_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                post_id TEXT,
                parent_id TEXT,
                content TEXT,
                author_name TEXT,
                upvotes INTEGER,
                downvotes INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS submolt_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submolt_name TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                submolt_id TEXT,
                display_name TEXT,
                description TEXT,
                subscriber_count INTEGER,
                avatar_url TEXT,
                banner_url TEXT,
                created_by_name TEXT,
                created_at TEXT,
                last_activity_at TEXT
            );

            CREATE TABLE IF NOT EXISTS moderators (
                submolt_name TEXT,
                agent_name TEXT,
                role TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (submolt_name, agent_name)
            );

            CREATE TABLE IF NOT EXISTS moderator_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submolt_name TEXT,
                agent_name TEXT,
                role TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
            CREATE INDEX IF NOT EXISTS idx_comments_parent_id ON comments(parent_id);
            CREATE INDEX IF NOT EXISTS idx_posts_submolt_name ON posts(submolt_name);
            CREATE INDEX IF NOT EXISTS idx_posts_author_name ON posts(author_name);
            CREATE INDEX IF NOT EXISTS idx_post_snapshots_post_id ON post_snapshots(post_id);
            CREATE INDEX IF NOT EXISTS idx_agent_snapshots_agent_name ON agent_snapshots(agent_name);
            CREATE INDEX IF NOT EXISTS idx_comment_snapshots_comment_id ON comment_snapshots(comment_id);
            CREATE INDEX IF NOT EXISTS idx_submolt_snapshots_submolt_name ON submolt_snapshots(submolt_name);
            CREATE INDEX IF NOT EXISTS idx_moderator_snapshots_submolt ON moderator_snapshots(submolt_name);
            CREATE INDEX IF NOT EXISTS idx_moderator_snapshots_agent ON moderator_snapshots(agent_name);
            CREATE INDEX IF NOT EXISTS idx_moderator_snapshots_run_id ON moderator_snapshots(scrape_run_id);

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            );

            -- Phase 3 narrow snapshot tables (change-driven, minimal) --

            CREATE TABLE IF NOT EXISTS post_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                upvotes INTEGER,
                downvotes INTEGER,
                comment_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS post_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                karma INTEGER,
                follower_count INTEGER,
                following_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT
            );

            CREATE TABLE IF NOT EXISTS submolt_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submolt_name TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                subscriber_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS submolt_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submolt_name TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT
            );

            CREATE TABLE IF NOT EXISTS moderator_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submolt_name TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scrape_run_id INTEGER,
                event_type TEXT NOT NULL,
                role TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_post_metrics_entity_time ON post_metrics(post_id, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_post_events_entity_time ON post_events(post_id, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_agent_metrics_entity_time ON agent_metrics(agent_name, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_agent_events_entity_time ON agent_events(agent_name, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_submolt_metrics_entity_time ON submolt_metrics(submolt_name, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_submolt_events_entity_time ON submolt_events(submolt_name, scraped_at);
            CREATE INDEX IF NOT EXISTS idx_moderator_events_pair_time ON moderator_events(submolt_name, agent_name, scraped_at);
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Run schema migrations. Each migration is idempotent via try/except.

        Structured as a list of (table, columns) tuples rather than a dict so
        the same table can appear in multiple migration blocks without later
        entries overwriting earlier ones. A dict silently drops duplicate keys
        and was hiding Migrations 2/3/7 on fresh databases — production DBs
        still had those columns because the blocks were applied in earlier
        code generations, but new checkouts (and the test suite) did not.
        """
        migrations = [
            # Migration 1: Comment deletion tracking
            ("comments", [
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_detected_at", "TEXT"),
                ("deletion_uncertain", "INTEGER DEFAULT 0"),
                # New API fields not previously captured
                ("is_spam", "INTEGER DEFAULT 0"),
                ("depth", "INTEGER"),
                ("reply_count", "INTEGER"),
                ("verification_status", "TEXT"),
                ("updated_at", "TEXT"),
                ("score", "INTEGER"),
            ]),
            # Migration 2: Post fields not previously captured
            ("posts", [
                ("type", "TEXT"),
                ("is_locked", "INTEGER DEFAULT 0"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("is_spam", "INTEGER DEFAULT 0"),
                ("verification_status", "TEXT"),
                ("updated_at", "TEXT"),
                ("score", "INTEGER"),
                ("hot_score", "REAL"),
                ("deleted_detected_at", "TEXT"),
            ]),
            # Migration 3: Agent fields not previously captured
            ("agents", [
                ("display_name", "TEXT"),
                ("posts_count", "INTEGER"),
                ("comments_count", "INTEGER"),
                ("deleted_at", "TEXT"),
                ("is_active", "INTEGER"),
                ("is_verified", "INTEGER"),
                ("last_active", "TEXT"),
                ("claimed_by", "TEXT"),
            ]),
            # Migration 4: Post snapshot new columns
            ("post_snapshots", [
                ("type", "TEXT"),
                ("is_locked", "INTEGER DEFAULT 0"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("is_spam", "INTEGER DEFAULT 0"),
                ("verification_status", "TEXT"),
                ("updated_at", "TEXT"),
                ("score", "INTEGER"),
                ("hot_score", "REAL"),
            ]),
            # Migration 5: Comment snapshot new columns
            ("comment_snapshots", [
                ("is_spam", "INTEGER DEFAULT 0"),
                ("depth", "INTEGER"),
                ("reply_count", "INTEGER"),
                ("verification_status", "TEXT"),
                ("updated_at", "TEXT"),
                ("score", "INTEGER"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_detected_at", "TEXT"),
                ("deletion_uncertain", "INTEGER DEFAULT 0"),
            ]),
            # Migration 6: Agent snapshot new columns
            ("agent_snapshots", [
                ("display_name", "TEXT"),
                ("posts_count", "INTEGER"),
                ("comments_count", "INTEGER"),
                ("is_active", "INTEGER"),
                ("is_verified", "INTEGER"),
                ("last_active", "TEXT"),
                ("deleted_at", "TEXT"),
                ("claimed_by", "TEXT"),
            ]),
            # Migration 7: Submolt fields from upstream audit (session 13)
            ("submolts", [
                ("creator_id", "TEXT"),
                ("post_count", "INTEGER"),
                ("is_nsfw", "INTEGER DEFAULT 0"),
                ("is_private", "INTEGER DEFAULT 0"),
            ]),
            # Migration 8: Submolt snapshot new columns
            ("submolt_snapshots", [
                ("creator_id", "TEXT"),
                ("post_count", "INTEGER"),
                ("is_nsfw", "INTEGER DEFAULT 0"),
                ("is_private", "INTEGER DEFAULT 0"),
            ]),
            # Migration 9 (Phase 3): anchor columns on live tables
            # hot_score decays fast — only first-observed value is interpretable
            ("posts", [
                ("hot_score_first", "REAL"),
                ("hot_score_first_observed_at", "TEXT"),
                ("score_first", "INTEGER"),
                # Migration 10 (Phase 3a v2): boolean/enum anchors so first run
                # does not emit a baseline event per entity (see session 21 log
                # verification #1 — would trip Alert C with ~718k post events).
                ("is_pinned_first", "INTEGER"),
                ("is_locked_first", "INTEGER"),
                ("is_deleted_first", "INTEGER"),
                ("is_spam_first", "INTEGER"),
                ("verification_status_first", "TEXT"),
            ]),
            # description_first + live `description` gives first+latest anchor;
            # numeric *_first give zero-JOIN access to first-observed values
            ("agents", [
                ("description_first", "TEXT"),
                ("karma_first", "INTEGER"),
                ("follower_count_first", "INTEGER"),
                ("following_count_first", "INTEGER"),
                # Migration 10: boolean anchor — avoids ~172k first-run events.
                ("is_claimed_first", "INTEGER"),
            ]),
            ("submolts", [
                ("description_first", "TEXT"),
                ("subscriber_count_first", "INTEGER"),
            ]),
        ]
        for table, columns in migrations:
            for col, typedef in columns:
                try:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                except sqlite3.OperationalError:
                    pass  # Column already exists
        self.conn.commit()

    def get_comment_ids_for_post(self, post_id: str) -> list[str]:
        """Get all comment IDs we have stored for a given post."""
        cursor = self.conn.execute(
            "SELECT id FROM comments WHERE post_id = ? AND is_deleted = 0",
            (post_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def mark_comments_deleted(self, comment_ids: list[str], uncertain: bool = False):
        """Mark comments as deleted (no longer returned by API).

        Args:
            comment_ids: IDs of comments to mark deleted.
            uncertain: If True, the post has >500 comments so the comment
                      may just be pushed out of the 500-cap window, not truly deleted.
        """
        now = datetime.utcnow().isoformat()
        for cid in comment_ids:
            self.conn.execute("""
                UPDATE comments
                SET is_deleted = 1, deleted_detected_at = ?, deletion_uncertain = ?
                WHERE id = ?
            """, (now, 1 if uncertain else 0, cid))

    def mark_posts_deleted(self, post_ids: list[str]):
        """Mark posts as deleted (no longer returned by API during full scrape).

        Args:
            post_ids: IDs of posts to mark deleted.
        """
        now = datetime.utcnow().isoformat()
        for pid in post_ids:
            self.conn.execute("""
                UPDATE posts
                SET is_deleted = 1, deleted_detected_at = ?
                WHERE id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
            """, (now, pid))

    def upsert_agent(self, agent: dict):
        """Insert or update an agent.

        Uses COALESCE for enrichment-only fields (karma, is_claimed, follower_count,
        following_count, owner_json, metadata_json, display_name, posts_count,
        comments_count, is_active, is_verified, last_active) to avoid overwriting
        with NULL when partial updates come from posts/comments (which only have
        id and name).
        """
        now = datetime.utcnow().isoformat()
        owner_json = json.dumps(agent.get("owner")) if agent.get("owner") else None
        metadata_json = json.dumps(agent.get("metadata")) if agent.get("metadata") else None

        self.conn.execute("""
            INSERT INTO agents (name, id, description, karma, is_claimed,
                              follower_count, following_count, avatar_url,
                              owner_json, metadata_json, created_at, last_updated_at,
                              display_name, posts_count, comments_count,
                              is_active, is_verified, last_active, claimed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                id = COALESCE(excluded.id, agents.id),
                description = COALESCE(excluded.description, agents.description),
                karma = COALESCE(excluded.karma, agents.karma),
                is_claimed = COALESCE(excluded.is_claimed, agents.is_claimed),
                follower_count = COALESCE(excluded.follower_count, agents.follower_count),
                following_count = COALESCE(excluded.following_count, agents.following_count),
                avatar_url = COALESCE(excluded.avatar_url, agents.avatar_url),
                owner_json = COALESCE(excluded.owner_json, agents.owner_json),
                metadata_json = COALESCE(excluded.metadata_json, agents.metadata_json),
                display_name = COALESCE(excluded.display_name, agents.display_name),
                posts_count = COALESCE(excluded.posts_count, agents.posts_count),
                comments_count = COALESCE(excluded.comments_count, agents.comments_count),
                is_active = COALESCE(excluded.is_active, agents.is_active),
                is_verified = COALESCE(excluded.is_verified, agents.is_verified),
                last_active = COALESCE(excluded.last_active, agents.last_active),
                claimed_by = COALESCE(excluded.claimed_by, agents.claimed_by),
                last_updated_at = excluded.last_updated_at
        """, (
            agent["name"],
            agent.get("id"),
            agent.get("description"),
            agent.get("karma"),
            agent.get("is_claimed"),
            agent.get("follower_count"),
            agent.get("following_count"),
            agent.get("avatar_url"),
            owner_json,
            metadata_json,
            agent.get("created_at"),
            now,
            agent.get("display_name"),
            agent.get("posts_count"),
            agent.get("comments_count"),
            agent.get("is_active"),
            agent.get("is_verified"),
            agent.get("last_active"),
            agent.get("claimed_by"),
        ))
        # Don't commit here - let caller batch commits

    def get_agent(self, name: str) -> Optional[dict]:
        """Get an agent by name."""
        cursor = self.conn.execute(
            "SELECT * FROM agents WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def upsert_post(self, post: dict):
        """Insert or update a post."""
        now = datetime.utcnow().isoformat()
        author_name = post.get("author", {}).get("name") if post.get("author") else None
        submolt_name = post.get("submolt", {}).get("name") if post.get("submolt") else None

        self.conn.execute("""
            INSERT INTO posts (id, title, content, url, author_name, submolt_name,
                             upvotes, downvotes, comment_count, is_pinned,
                             created_at, last_updated_at,
                             type, is_locked, is_deleted, is_spam,
                             verification_status, updated_at, score, hot_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                -- Preserve title/content/url when:
                --   (a) post is already flagged deleted in DB, OR
                --   (b) incoming row is flagged deleted (legacy path), OR
                --   (c) incoming content equals '[deleted]' tombstone — the
                --       common case: Moltbook returns content='[deleted]' WITHOUT
                --       flipping is_deleted, so the flag-based guard misses it
                --       entirely. Verified live 2026-04-20 (probes P1/P2).
                -- In case (c) we also infer is_deleted=1 for analysis accuracy.
                title = CASE
                    WHEN posts.is_deleted = 1 OR excluded.is_deleted = 1 THEN posts.title
                    WHEN excluded.content = '[deleted]'
                         AND posts.content IS NOT NULL
                         AND posts.content != '[deleted]' THEN posts.title
                    ELSE excluded.title END,
                content = CASE
                    WHEN posts.is_deleted = 1 OR excluded.is_deleted = 1 THEN posts.content
                    WHEN excluded.content = '[deleted]'
                         AND posts.content IS NOT NULL
                         AND posts.content != '[deleted]' THEN posts.content
                    ELSE excluded.content END,
                url = CASE
                    WHEN posts.is_deleted = 1 OR excluded.is_deleted = 1 THEN posts.url
                    WHEN excluded.content = '[deleted]'
                         AND posts.content IS NOT NULL
                         AND posts.content != '[deleted]' THEN posts.url
                    ELSE excluded.url END,
                upvotes = excluded.upvotes,
                downvotes = excluded.downvotes,
                comment_count = excluded.comment_count,
                is_pinned = excluded.is_pinned,
                is_locked = excluded.is_locked,
                -- Infer is_deleted=1 from tombstone content (API bug workaround).
                is_deleted = CASE
                    WHEN posts.is_deleted = 1 THEN 1
                    WHEN excluded.is_deleted = 1 THEN 1
                    WHEN excluded.content = '[deleted]' THEN 1
                    ELSE excluded.is_deleted END,
                is_spam = excluded.is_spam,
                verification_status = excluded.verification_status,
                updated_at = excluded.updated_at,
                score = excluded.score,
                hot_score = excluded.hot_score,
                last_updated_at = excluded.last_updated_at
        """, (
            post["id"],
            post.get("title"),
            post.get("content"),
            post.get("url"),
            author_name,
            submolt_name,
            post.get("upvotes"),
            post.get("downvotes"),
            post.get("comment_count"),
            post.get("is_pinned"),
            post.get("created_at"),
            now,
            post.get("type"),
            post.get("is_locked"),
            post.get("is_deleted"),
            post.get("is_spam"),
            post.get("verification_status"),
            post.get("updated_at"),
            post.get("score"),
            post.get("hot_score"),
        ))
        # Don't commit here - let caller batch commits

    def get_post(self, post_id: str) -> Optional[dict]:
        """Get a post by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def upsert_submolt(self, submolt: dict):
        """Insert or update a submolt."""
        now = datetime.utcnow().isoformat()
        created_by_name = submolt.get("created_by", {}).get("name") if submolt.get("created_by") else None
        creator_id = submolt.get("created_by", {}).get("id") if submolt.get("created_by") else submolt.get("creator_id")
        metadata_json = json.dumps(submolt.get("metadata")) if submolt.get("metadata") else None

        self.conn.execute("""
            INSERT INTO submolts (name, id, display_name, description,
                                subscriber_count, avatar_url, banner_url,
                                created_by_name, metadata_json, created_at, last_activity_at,
                                last_updated_at,
                                creator_id, post_count, is_nsfw, is_private)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                id = COALESCE(excluded.id, submolts.id),
                display_name = COALESCE(excluded.display_name, submolts.display_name),
                description = COALESCE(excluded.description, submolts.description),
                subscriber_count = COALESCE(excluded.subscriber_count, submolts.subscriber_count),
                avatar_url = COALESCE(excluded.avatar_url, submolts.avatar_url),
                banner_url = COALESCE(excluded.banner_url, submolts.banner_url),
                created_by_name = COALESCE(excluded.created_by_name, submolts.created_by_name),
                metadata_json = COALESCE(excluded.metadata_json, submolts.metadata_json),
                last_activity_at = COALESCE(excluded.last_activity_at, submolts.last_activity_at),
                creator_id = COALESCE(excluded.creator_id, submolts.creator_id),
                post_count = COALESCE(excluded.post_count, submolts.post_count),
                is_nsfw = COALESCE(excluded.is_nsfw, submolts.is_nsfw),
                is_private = COALESCE(excluded.is_private, submolts.is_private),
                last_updated_at = excluded.last_updated_at
        """, (
            submolt["name"],
            submolt.get("id"),
            submolt.get("display_name"),
            submolt.get("description"),
            submolt.get("subscriber_count"),
            submolt.get("avatar_url"),
            submolt.get("banner_url"),
            created_by_name,
            metadata_json,
            submolt.get("created_at"),
            submolt.get("last_activity_at"),
            now,
            creator_id,
            submolt.get("post_count"),
            submolt.get("is_nsfw"),
            submolt.get("is_private"),
        ))
        # Don't commit here - let caller batch commits

    def get_submolt(self, name: str) -> Optional[dict]:
        """Get a submolt by name."""
        cursor = self.conn.execute(
            "SELECT * FROM submolts WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def get_all_agent_names(self) -> list[str]:
        """Get all agent names in the database."""
        cursor = self.conn.execute("SELECT name FROM agents")
        return [row[0] for row in cursor.fetchall()]

    def get_unenriched_agent_names(self) -> list[str]:
        """Get agent names needing enrichment.

        Returns stubs (no description) AND agents missing post-migration
        fields like `claimed_by` on claimed accounts. The latter catches
        the session-18 migration gap: `claimed_by` was added after most
        agents were already enriched, so `WHERE description IS NULL` alone
        would skip them forever. See session 19 log (2026-04-14).
        """
        cursor = self.conn.execute("""
            SELECT name FROM agents
            WHERE description IS NULL
               OR (is_claimed = 1 AND claimed_by IS NULL)
        """)
        return [row[0] for row in cursor.fetchall()]

    def get_all_post_ids(self) -> list[str]:
        """Get all post IDs in the database."""
        cursor = self.conn.execute("SELECT id FROM posts")
        return [row[0] for row in cursor.fetchall()]

    def get_all_post_ids_with_activity(self) -> list[str]:
        """Get IDs of all posts with comment_count > 0, ordered by comment_count DESC.

        Used with --skip-empty when re-fetching all posts. Skips posts the
        platform itself reports as having zero comments. Ordered so the
        most-discussed posts are processed first.
        """
        cursor = self.conn.execute(
            "SELECT id FROM posts WHERE comment_count > 0 ORDER BY comment_count DESC"
        )
        return [row[0] for row in cursor.fetchall()]

    def get_comment_count(self) -> int:
        """Get total number of comments in the database."""
        return self.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]

    def get_post_ids_without_comments(self) -> list[str]:
        """Get post IDs that don't have any comments fetched yet.

        Returns posts sorted by comment_count DESC to prioritize posts with comments.
        """
        cursor = self.conn.execute("""
            SELECT id FROM posts
            WHERE id NOT IN (SELECT DISTINCT post_id FROM comments)
            ORDER BY comment_count DESC
        """)
        return [row[0] for row in cursor.fetchall()]

    def get_post_ids_without_comments_with_activity(self) -> list[str]:
        """Get IDs of posts that have comment_count > 0 and no scraped comments yet.

        Used with --skip-empty to avoid issuing 1.29M requests for posts the
        platform itself reports as having zero comments. Ordered by comment_count
        DESC so the most-discussed posts are processed first.
        """
        cursor = self.conn.execute("""
            SELECT p.id FROM posts p
            LEFT JOIN comments c ON c.post_id = p.id
            WHERE p.comment_count > 0 AND c.id IS NULL
            ORDER BY p.comment_count DESC
        """)
        return [row[0] for row in cursor.fetchall()]

    def upsert_comment(self, comment: dict, post_id: str):
        """Insert or update a comment."""
        now = datetime.utcnow().isoformat()
        author_name = comment.get("author", {}).get("name") if comment.get("author") else None

        self.conn.execute("""
            INSERT INTO comments (id, post_id, parent_id, content, author_name,
                                upvotes, downvotes, created_at, last_updated_at,
                                is_spam, depth, reply_count,
                                verification_status, updated_at, score, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                -- Preserve content when:
                --   (a) already flagged deleted in DB, OR
                --   (b) incoming row flagged deleted (legacy path), OR
                --   (c) incoming content equals '[deleted]' tombstone — live
                --       probe P2 (2026-04-20) confirmed Moltbook returns
                --       tombstoned comments with content='[deleted]' and
                --       is_deleted:false, so flag-based guard alone misses it.
                -- In case (c) we also infer is_deleted=1 for analysis accuracy.
                content = CASE
                    WHEN comments.is_deleted = 1 OR excluded.is_deleted = 1 THEN comments.content
                    WHEN excluded.content = '[deleted]'
                         AND comments.content IS NOT NULL
                         AND comments.content != '[deleted]' THEN comments.content
                    ELSE excluded.content END,
                upvotes = excluded.upvotes,
                downvotes = excluded.downvotes,
                is_spam = COALESCE(excluded.is_spam, comments.is_spam),
                depth = COALESCE(excluded.depth, comments.depth),
                reply_count = COALESCE(excluded.reply_count, comments.reply_count),
                verification_status = COALESCE(excluded.verification_status, comments.verification_status),
                updated_at = COALESCE(excluded.updated_at, comments.updated_at),
                score = COALESCE(excluded.score, comments.score),
                -- Infer is_deleted=1 from tombstone content (API bug workaround).
                is_deleted = CASE
                    WHEN comments.is_deleted = 1 THEN 1
                    WHEN excluded.is_deleted = 1 THEN 1
                    WHEN excluded.content = '[deleted]' THEN 1
                    ELSE COALESCE(excluded.is_deleted, comments.is_deleted, 0) END,
                last_updated_at = excluded.last_updated_at
        """, (
            comment["id"],
            post_id,
            comment.get("parent_id"),
            comment.get("content"),
            author_name,
            comment.get("upvotes"),
            comment.get("downvotes"),
            comment.get("created_at"),
            now,
            comment.get("is_spam"),
            comment.get("depth"),
            comment.get("reply_count"),
            comment.get("verification_status"),
            comment.get("updated_at"),
            comment.get("score"),
            comment.get("is_deleted"),
        ))
        # Don't commit here - let caller batch commits

    def save_post_snapshot(self, post: dict, scrape_run_id: int = None):
        """Save a snapshot of all post data."""
        self.conn.execute("""
            INSERT INTO post_snapshots (
                post_id, scrape_run_id, title, content, url, author_name, submolt_name,
                upvotes, downvotes, comment_count, is_pinned, created_at,
                type, is_locked, is_deleted, is_spam,
                verification_status, updated_at, score, hot_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post["id"],
            scrape_run_id,
            post.get("title"),
            post.get("content"),
            post.get("url"),
            post.get("author_name"),
            post.get("submolt_name"),
            post.get("upvotes"),
            post.get("downvotes"),
            post.get("comment_count"),
            post.get("is_pinned"),
            post.get("created_at"),
            post.get("type"),
            post.get("is_locked"),
            post.get("is_deleted"),
            post.get("is_spam"),
            post.get("verification_status"),
            post.get("updated_at"),
            post.get("score"),
            post.get("hot_score"),
        ))

    def save_agent_snapshot(self, agent: dict, scrape_run_id: int = None):
        """Save a snapshot of all agent data."""
        self.conn.execute("""
            INSERT INTO agent_snapshots (
                agent_name, scrape_run_id, agent_id, description, karma, is_claimed,
                follower_count, following_count, avatar_url,
                owner_json, metadata_json, created_at,
                display_name, posts_count, comments_count,
                is_active, is_verified, last_active, deleted_at, claimed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent["name"],
            scrape_run_id,
            agent.get("id"),
            agent.get("description"),
            agent.get("karma"),
            agent.get("is_claimed"),
            agent.get("follower_count"),
            agent.get("following_count"),
            agent.get("avatar_url"),
            agent.get("owner_json"),
            agent.get("metadata_json"),
            agent.get("created_at"),
            agent.get("display_name"),
            agent.get("posts_count"),
            agent.get("comments_count"),
            agent.get("is_active"),
            agent.get("is_verified"),
            agent.get("last_active"),
            agent.get("deleted_at"),
            agent.get("claimed_by"),
        ))

    def save_comment_snapshot(self, comment: dict, scrape_run_id: int = None):
        """Save a snapshot of all comment data."""
        self.conn.execute("""
            INSERT INTO comment_snapshots (
                comment_id, scrape_run_id, post_id, parent_id, content,
                author_name, upvotes, downvotes, created_at,
                is_spam, depth, reply_count,
                verification_status, updated_at, score,
                is_deleted, deleted_detected_at, deletion_uncertain
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comment["id"],
            scrape_run_id,
            comment.get("post_id"),
            comment.get("parent_id"),
            comment.get("content"),
            comment.get("author_name"),
            comment.get("upvotes"),
            comment.get("downvotes"),
            comment.get("created_at"),
            comment.get("is_spam"),
            comment.get("depth"),
            comment.get("reply_count"),
            comment.get("verification_status"),
            comment.get("updated_at"),
            comment.get("score"),
            comment.get("is_deleted"),
            comment.get("deleted_detected_at"),
            comment.get("deletion_uncertain"),
        ))

    def save_submolt_snapshot(self, submolt: dict, scrape_run_id: int = None):
        """Save a snapshot of all submolt data."""
        self.conn.execute("""
            INSERT INTO submolt_snapshots (
                submolt_name, scrape_run_id, submolt_id, display_name, description,
                subscriber_count, avatar_url, banner_url,
                created_by_name, created_at, last_activity_at,
                creator_id, post_count, is_nsfw, is_private
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            submolt["name"],
            scrape_run_id,
            submolt.get("id"),
            submolt.get("display_name"),
            submolt.get("description"),
            submolt.get("subscriber_count"),
            submolt.get("avatar_url"),
            submolt.get("banner_url"),
            submolt.get("created_by_name"),
            submolt.get("created_at"),
            submolt.get("last_activity_at"),
            submolt.get("creator_id"),
            submolt.get("post_count"),
            submolt.get("is_nsfw"),
            submolt.get("is_private"),
        ))

    def upsert_moderator(self, submolt_name: str, agent_name: str, role: str = None):
        """Insert or update a moderator relationship."""
        now = datetime.utcnow().isoformat()
        self.conn.execute("""
            INSERT INTO moderators (submolt_name, agent_name, role, last_updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(submolt_name, agent_name) DO UPDATE SET
                role = COALESCE(excluded.role, moderators.role),
                last_updated_at = excluded.last_updated_at
        """, (submolt_name, agent_name, role, now))

    def save_moderator_snapshot(self, submolt_name: str, agent_name: str, role: str, scrape_run_id: int = None):
        """Save a snapshot of a moderator relationship (legacy, Phase 2). Retained until Phase 4 archives."""
        self.conn.execute("""
            INSERT INTO moderator_snapshots (submolt_name, agent_name, role, scrape_run_id)
            VALUES (?, ?, ?, ?)
        """, (submolt_name, agent_name, role, scrape_run_id))

    # ----- Phase 3 narrow-snapshot writers -----
    #
    # These write to the change-driven *_metrics and *_events tables introduced
    # in session 21. Each writer returns 1 if it inserted a row, 0 otherwise —
    # the caller aggregates these into the R1 monitoring counters
    # (entities_scanned, inserted_metrics, inserted_events) logged per weekly run.

    def get_latest_post_metrics(self, post_id: str) -> Optional[dict]:
        """Latest (upvotes, downvotes, comment_count) row for a post from post_metrics, or None."""
        row = self.conn.execute("""
            SELECT upvotes, downvotes, comment_count
            FROM post_metrics WHERE post_id = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (post_id,)).fetchone()
        return dict(row) if row else None

    def insert_post_metric(self, post_id: str, upvotes, downvotes, comment_count, scrape_run_id: Optional[int]) -> int:
        """Insert a post_metrics row. Returns 1 on insert."""
        self.conn.execute("""
            INSERT INTO post_metrics (post_id, scrape_run_id, upvotes, downvotes, comment_count)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, scrape_run_id, upvotes, downvotes, comment_count))
        return 1

    def get_latest_post_event(self, post_id: str, event_type: str) -> Optional[str]:
        """Latest recorded value for a given event_type on a post, or None."""
        row = self.conn.execute("""
            SELECT new_value FROM post_events
            WHERE post_id = ? AND event_type = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (post_id, event_type)).fetchone()
        return row[0] if row else None

    def insert_post_event(self, post_id: str, event_type: str, old_value, new_value, scrape_run_id: Optional[int]) -> int:
        """Insert a post_events row. Returns 1 on insert."""
        self.conn.execute("""
            INSERT INTO post_events (post_id, scrape_run_id, event_type, old_value, new_value)
            VALUES (?, ?, ?, ?, ?)
        """, (post_id, scrape_run_id, event_type,
              None if old_value is None else str(old_value),
              None if new_value is None else str(new_value)))
        return 1

    def get_latest_agent_metrics(self, agent_name: str) -> Optional[dict]:
        row = self.conn.execute("""
            SELECT karma, follower_count, following_count
            FROM agent_metrics WHERE agent_name = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (agent_name,)).fetchone()
        return dict(row) if row else None

    def insert_agent_metric(self, agent_name: str, karma, follower_count, following_count, scrape_run_id: Optional[int]) -> int:
        self.conn.execute("""
            INSERT INTO agent_metrics (agent_name, scrape_run_id, karma, follower_count, following_count)
            VALUES (?, ?, ?, ?, ?)
        """, (agent_name, scrape_run_id, karma, follower_count, following_count))
        return 1

    def get_latest_agent_event(self, agent_name: str, event_type: str) -> Optional[str]:
        row = self.conn.execute("""
            SELECT new_value FROM agent_events
            WHERE agent_name = ? AND event_type = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (agent_name, event_type)).fetchone()
        return row[0] if row else None

    def insert_agent_event(self, agent_name: str, event_type: str, old_value, new_value, scrape_run_id: Optional[int]) -> int:
        self.conn.execute("""
            INSERT INTO agent_events (agent_name, scrape_run_id, event_type, old_value, new_value)
            VALUES (?, ?, ?, ?, ?)
        """, (agent_name, scrape_run_id, event_type,
              None if old_value is None else str(old_value),
              None if new_value is None else str(new_value)))
        return 1

    def get_latest_submolt_metrics(self, submolt_name: str) -> Optional[dict]:
        row = self.conn.execute("""
            SELECT subscriber_count FROM submolt_metrics
            WHERE submolt_name = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (submolt_name,)).fetchone()
        return dict(row) if row else None

    def insert_submolt_metric(self, submolt_name: str, subscriber_count, scrape_run_id: Optional[int]) -> int:
        self.conn.execute("""
            INSERT INTO submolt_metrics (submolt_name, scrape_run_id, subscriber_count)
            VALUES (?, ?, ?)
        """, (submolt_name, scrape_run_id, subscriber_count))
        return 1

    def get_latest_moderator_state(self, submolt_name: str, agent_name: str) -> Optional[dict]:
        """Latest (event_type, role) for a moderator pair, or None if never recorded."""
        row = self.conn.execute("""
            SELECT event_type, role FROM moderator_events
            WHERE submolt_name = ? AND agent_name = ?
            ORDER BY scraped_at DESC LIMIT 1
        """, (submolt_name, agent_name)).fetchone()
        return dict(row) if row else None

    def insert_moderator_event(self, submolt_name: str, agent_name: str, event_type: str, role, scrape_run_id: Optional[int]) -> int:
        """event_type is one of 'added', 'removed', 'role_changed'."""
        self.conn.execute("""
            INSERT INTO moderator_events (submolt_name, agent_name, scrape_run_id, event_type, role)
            VALUES (?, ?, ?, ?, ?)
        """, (submolt_name, agent_name, scrape_run_id, event_type, role))
        return 1

    def get_all_moderator_pairs(self) -> list[tuple]:
        """All (submolt, agent, role) tuples currently in the live `moderators` table."""
        return [
            (r[0], r[1], r[2])
            for r in self.conn.execute(
                "SELECT submolt_name, agent_name, role FROM moderators"
            ).fetchall()
        ]

    def get_active_moderator_pairs_from_events(self) -> set:
        """Set of (submolt, agent) pairs whose latest event is not 'removed'.

        Used to detect moderators that vanished from the live table between
        snapshot runs — those get a 'removed' event.
        """
        rows = self.conn.execute("""
            SELECT submolt_name, agent_name FROM moderator_events me1
            WHERE (submolt_name, agent_name, scraped_at) IN (
                SELECT submolt_name, agent_name, MAX(scraped_at)
                FROM moderator_events
                GROUP BY submolt_name, agent_name
            )
            AND event_type != 'removed'
        """).fetchall()
        return {(r[0], r[1]) for r in rows}

    def set_post_anchors_if_unset(self, post_id: str, hot_score, score,
                                   is_pinned, is_locked, is_deleted, is_spam,
                                   verification_status) -> int:
        """Set first-observed anchors on a post, only where currently NULL.

        Includes numeric anchors (hot_score, score) and boolean/enum anchors
        (is_pinned, is_locked, is_deleted, is_spam, verification_status). The
        boolean anchors were added in Migration 10 so the event-log writer does
        not emit a baseline row per flagged entity on first run (see session 21
        verification: avoided ~718k post_events).

        Returns 1 if any anchor was set. No-op on subsequent runs.
        """
        cursor = self.conn.execute("""
            UPDATE posts SET
                hot_score_first = COALESCE(hot_score_first, ?),
                hot_score_first_observed_at = COALESCE(hot_score_first_observed_at,
                    CASE WHEN hot_score_first IS NULL AND ? IS NOT NULL
                         THEN CURRENT_TIMESTAMP ELSE NULL END),
                score_first = COALESCE(score_first, ?),
                is_pinned_first = COALESCE(is_pinned_first, ?),
                is_locked_first = COALESCE(is_locked_first, ?),
                is_deleted_first = COALESCE(is_deleted_first, ?),
                is_spam_first = COALESCE(is_spam_first, ?),
                verification_status_first = COALESCE(verification_status_first, ?)
            WHERE id = ?
              AND (hot_score_first IS NULL OR score_first IS NULL
                   OR is_pinned_first IS NULL OR is_locked_first IS NULL
                   OR is_deleted_first IS NULL OR is_spam_first IS NULL
                   OR verification_status_first IS NULL)
        """, (hot_score, hot_score, score,
              is_pinned, is_locked, is_deleted, is_spam, verification_status,
              post_id))
        return 1 if cursor.rowcount else 0

    def set_agent_anchors_if_unset(self, agent_name: str, description, karma,
                                    follower_count, following_count, is_claimed) -> int:
        cursor = self.conn.execute("""
            UPDATE agents SET
                description_first = COALESCE(description_first, ?),
                karma_first = COALESCE(karma_first, ?),
                follower_count_first = COALESCE(follower_count_first, ?),
                following_count_first = COALESCE(following_count_first, ?),
                is_claimed_first = COALESCE(is_claimed_first, ?)
            WHERE name = ?
              AND (description_first IS NULL OR karma_first IS NULL
                   OR follower_count_first IS NULL OR following_count_first IS NULL
                   OR is_claimed_first IS NULL)
        """, (description, karma, follower_count, following_count, is_claimed, agent_name))
        return 1 if cursor.rowcount else 0

    def set_submolt_anchors_if_unset(self, submolt_name: str, description, subscriber_count) -> int:
        cursor = self.conn.execute("""
            UPDATE submolts SET
                description_first = COALESCE(description_first, ?),
                subscriber_count_first = COALESCE(subscriber_count_first, ?)
            WHERE name = ?
              AND (description_first IS NULL OR subscriber_count_first IS NULL)
        """, (description, subscriber_count, submolt_name))
        return 1 if cursor.rowcount else 0

    def get_all_submolt_names(self) -> list[str]:
        """Get all submolt names in the database."""
        cursor = self.conn.execute("SELECT name FROM submolts")
        return [row[0] for row in cursor.fetchall()]

    def start_scrape_run(self) -> int:
        """Record the start of a scrape run. Returns the run ID."""
        now = datetime.utcnow().isoformat()
        cursor = self.conn.execute("""
            INSERT INTO scrape_runs (started_at, status)
            VALUES (?, 'running')
        """, (now,))
        self.conn.commit()
        return cursor.lastrowid

    def complete_scrape_run(self, run_id: int, posts: int, agents: int, comments: int, submolts: int, status: str = 'completed'):
        """Record the completion of a scrape run."""
        now = datetime.utcnow().isoformat()
        self.conn.execute("""
            UPDATE scrape_runs
            SET completed_at = ?, posts_scraped = ?, agents_scraped = ?, comments_scraped = ?, submolts_scraped = ?, status = ?
            WHERE id = ?
        """, (now, posts, agents, comments, submolts, status, run_id))
        self.conn.commit()

    def get_latest_snapshot_counts(self) -> dict:
        """Get entity counts from the most recent completed scrape for validation.

        Returns:
            Dict with keys: submolts, posts, comments, agents
            Each value is the count of entities in the latest completed scrape run.
        """
        counts = {"submolts": 0, "posts": 0, "comments": 0, "agents": 0}

        # Get the most recent completed scrape run
        result = self.conn.execute("""
            SELECT id FROM scrape_runs
            WHERE status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
        """).fetchone()

        if not result:
            return counts

        run_id = result[0]

        # Count entities from that specific run
        result = self.conn.execute(
            "SELECT COUNT(*) FROM submolt_snapshots WHERE scrape_run_id = ?", (run_id,)
        ).fetchone()
        counts["submolts"] = result[0] if result else 0

        result = self.conn.execute(
            "SELECT COUNT(*) FROM post_snapshots WHERE scrape_run_id = ?", (run_id,)
        ).fetchone()
        counts["posts"] = result[0] if result else 0

        result = self.conn.execute(
            "SELECT COUNT(*) FROM comment_snapshots WHERE scrape_run_id = ?", (run_id,)
        ).fetchone()
        counts["comments"] = result[0] if result else 0

        result = self.conn.execute(
            "SELECT COUNT(*) FROM agent_snapshots WHERE scrape_run_id = ?", (run_id,)
        ).fetchone()
        counts["agents"] = result[0] if result else 0

        return counts

    def commit(self):
        """Commit pending changes."""
        self.conn.commit()

    def close(self):
        """Close the database connection."""
        self.conn.close()
