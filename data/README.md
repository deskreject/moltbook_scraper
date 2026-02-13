# Data Directory

Raw and processed data for the Moltbook scraper project. The SQLite database (`data/raw/moltbook.db`) is the primary data store and is created automatically on first scrape.

## Database Location

```
data/raw/moltbook.db
```

SQLite requires no installation or server -- it is built into Python. The database file is created automatically when the scraper runs for the first time. All tables are created via `CREATE TABLE IF NOT EXISTS` in `src/database.py`.

## Live Tables

These tables are updated in-place on every scrape using UPSERT logic.

### agents

AI agent profiles on Moltbook. Stub records are created from post/comment authors; full profiles are populated by `enrich_agents`.

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique agent username |
| id | TEXT | Platform-assigned ID |
| description | TEXT | Agent bio/description |
| karma | INTEGER | Reputation score |
| is_claimed | BOOLEAN | Whether agent is claimed by a human owner |
| follower_count | INTEGER | Number of followers |
| following_count | INTEGER | Number following |
| avatar_url | TEXT | Profile image URL |
| owner_json | TEXT | JSON -- human owner info |
| metadata_json | TEXT | Additional platform metadata as JSON |
| created_at | TEXT | Account creation timestamp (ISO 8601) |
| first_seen_at | TEXT | When scraper first encountered this agent |
| last_updated_at | TEXT | When scraper last updated this record |

### posts

All posts on Moltbook.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique post ID |
| title | TEXT | Post title |
| content | TEXT | Full post body |
| url | TEXT | Post URL on platform |
| author_name | TEXT | Agent who posted |
| submolt_name | TEXT | Community it was posted in |
| upvotes | INTEGER | Upvote count |
| downvotes | INTEGER | Downvote count |
| comment_count | INTEGER | Platform-reported comment count |
| is_pinned | BOOLEAN | Whether post is pinned |
| created_at | TEXT | Post creation timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### comments

All comments, including nested replies. Thread structure is reconstructable via parent_id.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (PK) | Unique comment ID |
| post_id | TEXT | Parent post |
| parent_id | TEXT | Parent comment (NULL = top-level reply) |
| content | TEXT | Comment body |
| author_name | TEXT | Agent who commented |
| upvotes | INTEGER | Upvote count |
| downvotes | INTEGER | Downvote count |
| created_at | TEXT | Comment timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

Note: API caps comments at 1,000 per post.

### submolts

Communities (analogous to subreddits).

| Column | Type | Description |
|--------|------|-------------|
| name | TEXT (PK) | Unique community name |
| id | TEXT | Platform ID |
| display_name | TEXT | Human-readable display name |
| description | TEXT | Community description |
| subscriber_count | INTEGER | Number of subscribers |
| avatar_url | TEXT | Community avatar URL |
| banner_url | TEXT | Community banner URL |
| created_by_name | TEXT | Agent who created the community |
| metadata_json | TEXT | Additional metadata as JSON |
| created_at | TEXT | Community creation date |
| last_activity_at | TEXT | Most recent activity timestamp |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### moderators

Which agents moderate which communities.

| Column | Type | Description |
|--------|------|-------------|
| submolt_name | TEXT (PK part 1) | Community name |
| agent_name | TEXT (PK part 2) | Agent name |
| role | TEXT | Moderation role |
| first_seen_at | TEXT | Scraper first-seen timestamp |
| last_updated_at | TEXT | Scraper last-update timestamp |

### scrape_runs

Metadata about each scraping session.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER (PK) | Auto-incrementing run ID |
| started_at | TEXT | Run start timestamp |
| completed_at | TEXT | Run end timestamp |
| agents_scraped | INTEGER | Agent count |
| posts_scraped | INTEGER | Post count |
| comments_scraped | INTEGER | Comment count |
| submolts_scraped | INTEGER | Submolt count |
| status | TEXT | completed / interrupted / failed / incomplete |

## Snapshot Tables

Point-in-time copies of live tables, used for reproducible analysis. Each snapshot row includes `scraped_at` and `scrape_run_id` to link back to the scrape run that produced it. Created by running `python -m src.cli snapshots`.

- **agent_snapshots** -- mirrors agents table
- **post_snapshots** -- mirrors posts table
- **comment_snapshots** -- mirrors comments table
- **submolt_snapshots** -- mirrors submolts table
- **moderator_snapshots** -- mirrors moderators table

## Scrape Modes

| Command | Purpose |
|---------|---------|
| `full` | Complete scrape: submolts, posts, comments, moderators, agent enrichment, snapshots, docs |
| `incremental` | New posts only (stops at first known post ID) |
| `snapshots` | Creates point-in-time copies of all live tables |

## Known Limitations

- Comment API caps at 1,000 comments per post (validation uses 80% tolerance)
- Follower/following graph not exposed by API (only counts available)
- API pagination is non-deterministic; scraper uses deduplication via seen-sets
- Platform stats API is flaky; may return zeros requiring retries
