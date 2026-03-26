# Sessions 10-11 — 2026-03-12/13 — Schema Migrations & Automation Scripts

Session 10 (Mar 12) interrupted mid-implementation; completed as session 11 (Mar 13).

**What was done:**
- Schema migrations for new API fields: posts (type, is_locked, is_spam, verification_status, updated_at, score, hot_score), comments (is_spam, depth, reply_count, verification_status, updated_at, score), agents (display_name, posts_count, comments_count, is_active, is_verified, last_active)
- Snapshot table migrations to capture new columns
- Updated `upsert_agent()` and `upsert_comment()` with COALESCE to protect enrichment-only fields from NULL overwrite
- Deletion detection: `mark_posts_deleted()`, `--detect-deletions` CLI flag for posts/comments, agent 404 → `deleted_at`
- Created automation scripts: `weekly_scrape.sh`, `monthly_rescrape.sh`, `status.sh`

**Key decisions:**
- Weekly Mon 02:00 UTC (incremental + comments + enrich + snapshots)
- Monthly 1st 02:00 UTC (full re-scrape + deletion detection)
- Lock file prevents overlap; email alerts via msmtp
