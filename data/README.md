# Database Structure

Reference for the SQLite database at `data/raw/moltbook.db`. All tables are created via `CREATE TABLE IF NOT EXISTS` in `src/database.py`. This file documents structure only — see `CLAUDE.md` for scrape commands, rate limits, and operational notes.

**Write behaviour**: all writes use UPSERT (`ON CONFLICT DO UPDATE SET`). Re-running any stage updates existing rows in place and never deletes data. `*_metrics`, `*_events`, and legacy `*_snapshots` are append-only. Re-running after a failure is safe.

## Live tables

Updated in place on every scrape. Hold the current value of every field. Immutable columns (post title/content, comment content) are authoritative here.

### agents

AI agent profiles. Stub records (name + ID only) are created from embedded `author` objects when scraping posts and comments. Full profiles are populated by the `enrich` stage, which calls `GET /agents/profile?name=X`.

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique agent username |
| id | TEXT | Platform-assigned UUID |
| description | TEXT | Agent bio (latest value; first/latest in `description_first` / `description_latest`) |
| karma | INTEGER | Reputation score (latest; trajectory in `agent_metrics`) |
| is_claimed | BOOLEAN | Whether agent is claimed by a human |
| claimed_by | TEXT | UUID of the human operator (NULL for unclaimed agents; populated only by profile endpoint) |
| follower_count | INTEGER | Follower count (latest; trajectory in `agent_metrics`) |
| following_count | INTEGER | Following count (latest; trajectory in `agent_metrics`) |
| avatar_url | TEXT | Profile image URL |
| owner_json | TEXT | JSON — human-owner block (profile endpoint, claimed agents only) |
| metadata_json | TEXT | Additional platform metadata as JSON |
| display_name | TEXT | Human-readable display name |
| posts_count | INTEGER | Platform-reported post count |
| comments_count | INTEGER | Platform-reported comment count |
| is_active | INTEGER | Activity flag |
| is_verified | INTEGER | Verification flag |
| last_active | TEXT | Platform-reported last-active timestamp |
| deleted_at | TEXT | Set when scraper receives 404 on profile endpoint |
| created_at | TEXT | Account creation timestamp |
| first_seen_at | TEXT | When scraper first encountered this agent |
| last_updated_at | TEXT | When scraper last upserted this record |

**Why both `is_claimed` and `claimed_by`.** `is_claimed` answers *whether* a human runs the agent; `claimed_by` answers *which* human (a stable UUID shared across all agents that human controls). The pair enables operator-concentration and sockpuppet-network analyses.

**camelCase vs snake_case.** Embedded `author` objects inside `/posts` and `/comments` responses use camelCase (`avatarUrl`, `followerCount`, `isClaimed`, …). The standalone `/agents/profile` endpoint uses snake_case (`avatar_url`, `follower_count`, `is_claimed`, `claimed_by`, …). `src/client.py:_normalize_agent()` converts camelCase author objects to snake_case before writing; profile responses are used as-is. `claimed_by` is returned only by the profile endpoint.

### posts

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique post UUID |
| title | TEXT | Post title (immutable) |
| content | TEXT | Full post body (immutable; preserved across deletion) |
| url | TEXT | Post URL on platform |
| author_name | TEXT | FK → agents.name |
| submolt_name | TEXT | FK → submolts.name |
| upvotes | INTEGER | Upvote count (latest; trajectory in `post_metrics` within 4-week cutoff) |
| downvotes | INTEGER | Downvote count (latest; trajectory in `post_metrics`) |
| comment_count | INTEGER | Platform-reported comment count (latest; trajectory in `post_metrics`) |
| is_pinned | BOOLEAN | Whether post is pinned (transitions in `post_events`) |
| hot_score_first | REAL | First observed hot-score (decays too fast for a trajectory) |
| hot_score_first_observed_at | TEXT | When `hot_score_first` was captured |
| created_at | TEXT | Post creation timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### comments

Includes nested replies; thread structure via `parent_id`. Fetched via `GET /posts/{id}/comments`.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique comment UUID |
| post_id | TEXT | FK → posts.id |
| parent_id | TEXT | Parent comment (NULL = top-level reply) |
| content | TEXT | Comment body (immutable; preserved across deletion) |
| author_name | TEXT | FK → agents.name |
| upvotes | INTEGER | Upvote count (latest; `comment_metrics` usually empty) |
| downvotes | INTEGER | Downvote count (latest) |
| created_at | TEXT | Comment timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### submolts

Communities (analogous to subreddits).

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique community slug |
| id | TEXT | Platform UUID |
| display_name | TEXT | Human-readable display name |
| description | TEXT | Community description (latest; first/latest in `description_first` / `description_latest`) |
| subscriber_count | INTEGER | Subscriber count (latest; trajectory in `submolt_metrics`) |
| avatar_url | TEXT | Avatar URL |
| banner_url | TEXT | Banner URL |
| created_by_name | TEXT | FK → agents.name |
| metadata_json | TEXT | Additional metadata as JSON |
| created_at | TEXT | Community creation date |
| last_activity_at | TEXT | Most recent activity timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### moderators

Which agents moderate which communities.

| Column | Type | Description |
|--------|------|-------------|
| submolt_name | TEXT (PK part 1) | FK → submolts.name |
| agent_name | TEXT (PK part 2) | FK → agents.name |
| role | TEXT | Moderation role (transitions in `moderator_events`) |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### scrape_runs

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

## Layered design (Phase 3)

Columns go to different layers based on how they change over time.

### Layer 1 — Live tables (current state)

UPSERT-in-place on every scrape. Immutable columns (post title/content, comment content) are authoritative here.

Mutable columns where the origin value is analytically useful get `_first` / `_latest` anchors on the live table:

- `agents.description_first`, `agents.description_latest`, `agents.description_first_observed_at`
- `submolts.description_first`, `submolts.description_latest`, `submolts.description_first_observed_at`
- `posts.hot_score_first`, `posts.hot_score_first_observed_at`

Boolean/enum initial states (`is_pinned`, `is_deleted`, moderator `role`) are captured as `_first` anchors; subsequent transitions go to Layer 3. Cosmetic URLs (`avatar_url`, `banner_url`) are live-only.

### Layer 2 — `*_metrics` tables (counter trajectories)

Change-driven inserts. One row per entity per scrape run, **only when the counter differs from the last stored value**. Sparse.

| Table | Counters | Cutoff |
|-------|----------|--------|
| post_metrics | upvotes, downvotes, comment_count, hot_score | 4 weeks after `posts.created_at` |
| agent_metrics | karma, follower_count, following_count, posts_count, comments_count | none |
| comment_metrics | upvotes, downvotes | none (usually empty) |
| submolt_metrics | subscriber_count | none |

Query pattern for "karma trajectory of agent X":
`SELECT scraped_at, karma FROM agent_metrics WHERE agent_name = 'X' ORDER BY scraped_at`.

### Layer 3 — `*_events` tables (state-transition log)

One row per transition of a boolean or enum. Very sparse. First observation is captured in the Layer-1 `_first` anchor — events are only emitted for *subsequent* transitions.

| Table | Transitions |
|-------|-------------|
| post_events | is_pinned, is_locked, is_deleted, is_spam |
| agent_events | is_claimed, is_verified, deleted_at → non-NULL |
| submolt_events | verification status, private/public |
| moderator_events | role added / removed / changed |

First post-migration snapshot emits a ~19,655-row moderator-events baseline (one "added" per existing pair). Post/agent/submolt events are 0 on first run.

### Layer 4 — Legacy `*_snapshots` (retiring in Phase 4)

Historical full-dump rows (one per entity per weekly run) from 2026-03-11 through the Phase 4 migration date. Will be renamed to `*_snapshots_v1_archive`; compatibility VIEWs named `*_snapshots` bridge existing R code during transition.

### Row-shape summary

| Layer | Rows per entity per run | Purpose |
|-------|------------------------|---------|
| Live (`agents`, `posts`, `comments`, `submolts`, `moderators`) | 1 (UPSERT) | current state |
| `*_metrics` | 0–1 (sparse) | counter trajectories |
| `*_events` | typically 0 | state transitions |
| Legacy `*_snapshots` | 1 (dense) | historical full dump; retire in Phase 4 |
| `scrape_runs` | 1 per run | run metadata |

## Deletion-content preservation

`upsert_post` and `upsert_comment` use `content = CASE WHEN is_deleted = 1 THEN <table>.content ELSE excluded.content END`. Once a row is marked deleted, its content is never overwritten, even if the API later returns a tombstone.
