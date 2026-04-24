# Data Directory

Raw and processed data for the Moltbook scraper project. The SQLite database (`data/raw/moltbook.db`) is the primary data store and is created automatically on first scrape.

## Database Location

```
data/raw/moltbook.db
```

SQLite requires no installation or server — it is built into Python. The database file is created automatically when the scraper runs for the first time. All tables are created via `CREATE TABLE IF NOT EXISTS` in `src/database.py`.

**Write behaviour**: all writes use UPSERT (`ON CONFLICT DO UPDATE SET`). Re-running any scrape stage updates existing rows in place and never deletes data. Snapshot tables are append-only. It is safe to re-run any stage after a failure.

## Platform Scale (as of 2026-04-24, VM)

| Entity | Count |
|--------|-------|
| Agents | ~176,547 |
| Posts | ~2,539,294 |
| Comments | ~4,459,599 |
| Submolts | ~20,786 |

Run `ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'` for current VM counts, or `python -m src.cli status --db data/raw/moltbook.db` locally.

## Live Tables

These tables are updated in-place on every scrape using UPSERT logic.

### agents

AI agent profiles on Moltbook. Stub records (name + ID only) are created automatically from embedded `author` objects when scraping posts and comments. Full profiles (karma, followers, bio, owner info) are populated by the `enrich` scrape stage, which calls `GET /agents/profile?name=X` for each known agent.

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique agent username |
| id | TEXT | Platform-assigned UUID |
| description | TEXT | Agent bio (latest value) |
| karma | INTEGER | Reputation score (latest value; trajectory in `agent_metrics`) |
| is_claimed | BOOLEAN | Whether agent is claimed by a human |
| claimed_by | TEXT | UUID of the human operator (NULL for unclaimed agents; present on profile-endpoint responses only) |
| follower_count | INTEGER | Follower count (latest; trajectory in `agent_metrics`) |
| following_count | INTEGER | Following count (latest; trajectory in `agent_metrics`) |
| avatar_url | TEXT | Profile image URL |
| owner_json | TEXT | JSON — richer human-owner block (from profile endpoint, claimed agents only) |
| metadata_json | TEXT | Additional platform metadata as JSON |
| display_name | TEXT | Human-readable display name |
| posts_count | INTEGER | Platform-reported post count |
| comments_count | INTEGER | Platform-reported comment count |
| is_active | INTEGER | Activity flag |
| is_verified | INTEGER | Verification flag |
| last_active | TEXT | Platform-reported last-active timestamp |
| deleted_at | TEXT | Set when scraper receives 404 on profile endpoint |
| created_at | TEXT | Account creation timestamp (ISO 8601) |
| first_seen_at | TEXT | When scraper first encountered this agent |
| last_updated_at | TEXT | When scraper last upserted this record |

**Why `is_claimed` and `claimed_by` are both stored.** `is_claimed` tells you *whether* a human runs the agent; `claimed_by` tells you *which* human (a stable UUID shared across all agents that human controls). Useful for operator-concentration and sockpuppet-network analyses. Note that the `claimed_by` column was added after most agents were already enriched, so it is sparsely populated pending a full re-enrich (see §Enrichment commit bug in handover).

**Note on camelCase vs snake_case.** Embedded `author` objects inside `/posts` and `/comments` responses use camelCase (`avatarUrl`, `followerCount`, `isClaimed`, …). The standalone `/agents/profile` endpoint uses snake_case (`avatar_url`, `follower_count`, `is_claimed`, `claimed_by`, …). `src/client.py:_normalize_agent()` converts camelCase author objects to snake_case before writing; profile responses are used as-is. `claimed_by` is returned only by the profile endpoint — it is not present on embedded author objects.

### posts

All posts on Moltbook, fetched via cursor-based pagination (`GET /posts?cursor=TOKEN`).

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique post UUID |
| title | TEXT | Post title |
| content | TEXT | Full post body |
| url | TEXT | Post URL on platform |
| author_name | TEXT | Agent who posted (FK → agents.name) |
| submolt_name | TEXT | Community it was posted in (FK → submolts.name) |
| upvotes | INTEGER | Upvote count |
| downvotes | INTEGER | Downvote count |
| comment_count | INTEGER | Platform-reported comment count |
| is_pinned | BOOLEAN | Whether post is pinned |
| created_at | TEXT | Post creation timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### comments

All comments, including nested replies. Thread structure is reconstructable via `parent_id`. Fetched via a dedicated endpoint: `GET /posts/{id}/comments` (separate from the post fetch since Feb 2026).

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique comment UUID |
| post_id | TEXT | Parent post (FK → posts.id) |
| parent_id | TEXT | Parent comment (NULL = top-level reply to post) |
| content | TEXT | Comment body |
| author_name | TEXT | Agent who commented (FK → agents.name) |
| upvotes | INTEGER | Upvote count |
| downvotes | INTEGER | Downvote count |
| created_at | TEXT | Comment timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

**Note**: API caps replies at 500 per request with no pagination. The scraper passes `limit=500`. For posts with > 500 comments, only the first 500 are retrievable. Validation uses an 80 % tolerance threshold against the platform-reported comment total. Posts and comments are effectively immutable after creation (see §Snapshot policy below).

### submolts

Communities (analogous to subreddits), fetched via page-based pagination (`GET /submolts?page=N`, 20 per page).

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique community slug |
| id | TEXT | Platform UUID |
| display_name | TEXT | Human-readable display name |
| description | TEXT | Community description |
| subscriber_count | INTEGER | Number of subscribers |
| avatar_url | TEXT | Community avatar URL |
| banner_url | TEXT | Community banner URL |
| created_by_name | TEXT | Agent who created the community (FK → agents.name) |
| metadata_json | TEXT | Additional metadata as JSON |
| created_at | TEXT | Community creation date |
| last_activity_at | TEXT | Most recent activity timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### moderators

Which agents moderate which communities.

| Column | Type | Description |
|--------|------|-------------|
| submolt_name | TEXT (PK part 1) | Community name (FK → submolts.name) |
| agent_name | TEXT (PK part 2) | Agent name (FK → agents.name) |
| role | TEXT | Moderation role |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### scrape_runs

Metadata about each scraping session. Used by `get_latest_snapshot_counts()` to provide a validation baseline when the live stats API is unavailable.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER (PK) | Auto-incrementing run ID |
| started_at | TEXT | Run start timestamp |
| completed_at | TEXT | Run end timestamp |
| agents_scraped | INTEGER | Agent count at completion |
| posts_scraped | INTEGER | Post count at completion |
| comments_scraped | INTEGER | Comment count at completion |
| submolts_scraped | INTEGER | Submolt count at completion |
| status | TEXT | `completed` / `interrupted` / `failed` / `incomplete` |

## Snapshot policy (Phase 3 design)

The database has a **three-layer design**. Different column types go to different layers depending on how they change over time. This is the authoritative mental model — the legacy full-dump `*_snapshots` tables are a transitional fat layer scheduled for retirement.

### Layer 1 — Live tables (primary state)

Hold the **current** value of every field and are updated in-place on every scrape via UPSERT. Immutable columns (post title/content, comment content) are authoritative here; mutable columns hold the latest observed value.

For a handful of mutable columns where the origin value is analytically useful, the live table also stores `_first` and `_latest` anchors:

- `agents.description_first`, `agents.description_latest`, `agents.description_first_observed_at`
- `submolts.description_first`, `submolts.description_latest`, `submolts.description_first_observed_at`
- `posts.hot_score_first`, `posts.hot_score_first_observed_at` (hot-score decays too fast for a trajectory)

Boolean/enum initial states (`is_pinned`, `is_deleted`, moderator `role`) are captured as `_first` anchors on live tables; subsequent transitions go to the event log (Layer 3). Cosmetic URLs (`avatar_url`, `banner_url`) are live-only and never snapshotted.

### Layer 2 — `*_metrics` tables (counter trajectories)

**Change-driven inserts.** One row per entity-per-scrape-run, **only when the counter differs from the last stored value**. Sparse: the vast majority of mature entities produce zero rows per run. Tables:

| Table | Counters tracked | Cutoff |
|-------|------------------|--------|
| post_metrics | upvotes, downvotes, comment_count, hot_score | 4 weeks after `posts.created_at` (hot lifecycle ends) |
| agent_metrics | karma, follower_count, following_count, posts_count, comments_count | none |
| comment_metrics | upvotes, downvotes | none (comments effectively immutable; this table is usually empty) |
| submolt_metrics | subscriber_count | none |

Query pattern for "karma trajectory of agent X": `SELECT scraped_at, karma FROM agent_metrics WHERE agent_name = 'X' ORDER BY scraped_at`.

### Layer 3 — `*_events` tables (state-transition log)

**One row per transition** of a boolean or enum. Very sparse (moderator add/remove, post pin/lock, agent verification change, `is_deleted` flip). Initial state is captured in the `_first` anchor on the live table — events are emitted only for *subsequent* transitions.

| Table | Transitions logged |
|-------|--------------------|
| post_events | is_pinned, is_locked, is_deleted, is_spam |
| agent_events | is_claimed, is_verified, deleted_at → non-NULL |
| submolt_events | verification status, private/public |
| moderator_events | role added / role removed / role changed |

First snapshot run after Phase 3a migration emits a ~19,655-row moderator-events baseline (by design — one "added" event per existing moderator pair). Post/agent/submolt events should be 0 on first run.

### Layer 4 — Legacy `*_snapshots` tables (to be retired in Phase 4)

Holds historical full-dump rows (one per entity per weekly scrape) from 2026-03-11 through the Phase 4 migration date. Will be renamed to `*_snapshots_v1_archive`; compatibility VIEWs named `*_snapshots` will bridge existing R analysis code during the transition. Currently these tables contain ~15 GB of data that Phase 4 compresses to Parquet.

### Table summary

| Table family | Rows per entity per run | Purpose |
|---|---|---|
| Live (`agents`, `posts`, `comments`, `submolts`, `moderators`) | always 1 row per entity (UPSERT) | current state |
| `*_metrics` | 0–1 row per entity per run (sparse) | counter trajectories |
| `*_events` | typically 0 rows per entity per run | state transitions |
| Legacy `*_snapshots` | 1 row per entity per run (dense) | historical full dump; retire in Phase 4 |
| `scrape_runs` | 1 row per scrape run | metadata (row count, status) |

### Migration status

- Phase 3a (narrow change-driven writer + `_first`/`_latest` anchors) is committed locally as `86d543d`; **not yet pushed to VM**. Until pushed, the weekly cron still writes the legacy `*_snapshots` layer as full dumps. See `claude_handover.md` for push plan.
- Phase 4 (compress `*_snapshots` to Parquet, swap in compatibility VIEWs) is deferred until the Apr 20 weekly is stable post-push.

## Scrape Stages

Run stages independently so failures are isolated and resumable. All are safe to re-run.

| Stage | Command | Est. time | Notes |
|-------|---------|-----------|-------|
| submolts | `python -m src.cli submolts` | 60–90 min | 18,625 submolts at 20/page |
| posts | `python -m src.cli posts` | 3–4 hours | 1.67M posts, cursor pagination |
| comments | `python -m src.cli comments --only-missing` | 10–14 days | 1 req/post; run as background process |
| moderators | `python -m src.cli moderators` | 3–4 hours | 1 req/submolt |
| enrich | `python -m src.cli enrich` | days–weeks | 1 req/agent; run as background process |
| snapshots | `python -m src.cli snapshots` | seconds | Run last; required before R analysis |

## Known Limitations

- Comments API returns ~200 comments per request (not the full thread for high-volume posts); validation uses 80% tolerance against platform total
- Follower/following graph not exposed by API (only counts available)
- Posts API uses cursor-based pagination (not offset); cursors are opaque tokens
- Submolts API uses page-based pagination (20 per page); offset parameter no longer supported
- Platform stats API (`/api/v1/stats`) returns `totalAgents`, `totalPosts`, `totalComments`, `totalSubmolts` — note `total` prefix (changed Feb 2026)
- Platform stats API is occasionally flaky; client retries up to 10 times on zero values
