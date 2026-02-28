# Data Directory

Raw and processed data for the Moltbook scraper project. The SQLite database (`data/raw/moltbook.db`) is the primary data store and is created automatically on first scrape.

## Database Location

```
data/raw/moltbook.db
```

SQLite requires no installation or server — it is built into Python. The database file is created automatically when the scraper runs for the first time. All tables are created via `CREATE TABLE IF NOT EXISTS` in `src/database.py`.

**Write behaviour**: all writes use UPSERT (`ON CONFLICT DO UPDATE SET`). Re-running any scrape stage updates existing rows in place and never deletes data. Snapshot tables are append-only. It is safe to re-run any stage after a failure.

## Platform Scale (as of 2026-02-28)

| Entity | Count |
|--------|-------|
| Agents | ~2,849,285 |
| Posts | ~1,667,039 |
| Comments | ~12,530,042 |
| Submolts | ~18,625 |

These numbers grow daily. Run `python -m src.cli status --db data/raw/moltbook.db` to see current DB counts, and check the `/api/v1/stats` endpoint for live platform totals.

## Live Tables

These tables are updated in-place on every scrape using UPSERT logic.

### agents

AI agent profiles on Moltbook. Stub records (name + ID only) are created automatically from embedded `author` objects when scraping posts and comments. Full profiles (karma, followers, bio, owner info) are populated by the `enrich` scrape stage, which calls `GET /agents/profile?name=X` for each known agent.

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique agent username |
| id | TEXT | Platform-assigned UUID |
| description | TEXT | Agent bio/description |
| karma | INTEGER | Reputation score |
| is_claimed | BOOLEAN | Whether agent is claimed by a human owner |
| follower_count | INTEGER | Number of followers |
| following_count | INTEGER | Number following |
| avatar_url | TEXT | Profile image URL |
| owner_json | TEXT | JSON — human owner info (only present for claimed agents) |
| metadata_json | TEXT | Additional platform metadata as JSON |
| created_at | TEXT | Account creation timestamp (ISO 8601) |
| first_seen_at | TEXT | When scraper first encountered this agent |
| last_updated_at | TEXT | When scraper last updated this record |

**Note on camelCase**: embedded author objects in API responses use camelCase keys (`avatarUrl`, `followerCount`, etc.). The scraper normalises these to snake_case before writing, so all DB columns are snake_case regardless of source.

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

**Note**: API returns approximately 200 comments per request (not 1,000 as previously documented). The platform-reported comment total can never be fully collected due to this cap. Validation uses an 80% tolerance threshold.

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

## Snapshot Tables

Point-in-time copies of live tables, used for reproducible analysis. Each snapshot row includes `scraped_at` and `scrape_run_id` to link back to the scrape run that produced it. Created by running `python -m src.cli snapshots`.

R analysis scripts (`analysis/R/`) use snapshot tables exclusively (not the live tables), joined via `scrape_run_id` to ensure all analysis refers to a consistent point in time.

| Table | Mirrors |
|-------|---------|
| agent_snapshots | agents |
| post_snapshots | posts |
| comment_snapshots | comments |
| submolt_snapshots | submolts |
| moderator_snapshots | moderators |

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
