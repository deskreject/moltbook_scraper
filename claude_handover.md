# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-13 (session 11)
**Git state**: Branch `main`, uncommitted changes pending commit
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-03-11, pre-catch-up)

| Table | Count | Status |
|-------|-------|--------|
| posts | 1,742,447 | Complete (93.4% of platform's 2.01M) |
| submolts | 18,673 | Complete (97.0% of platform's 19,241) |
| moderators | 13,741 | Complete |
| comments | 2,725,187 | Complete (167 posts unreachable — stale comment_count, API returns empty) |
| agents | 166,998 | Complete. 7,160 have no description (genuinely unset on platform) |
| snapshots | 1,742,447 post / 2,725,187 comment / 166,998 agent / 18,673 submolt / 13,741 mod | Created 2026-03-11 |

**DB size**: 5.7 GB (3.0 GB live + 2.7 GB snapshots)
**DB path**: `data/raw/moltbook.db`

---

## Session 11 Changes (2026-03-13)

### Schema & upserts
- **Migrations**: New columns for posts (type, is_locked, is_spam, verification_status, updated_at, score, hot_score, deleted_detected_at), comments (is_spam, depth, reply_count, verification_status, updated_at, score), agents (display_name, posts_count, comments_count, is_active, is_verified, last_active, deleted_at)
- **Snapshot table migrations**: Same columns added to post_snapshots, comment_snapshots, agent_snapshots
- **`upsert_agent()`**: Now persists all new agent fields with COALESCE
- **`upsert_comment()`**: Now persists all new comment fields with COALESCE
- **`upsert_post()`**: Already updated in session 10

### Deletion detection
- **`mark_posts_deleted(post_ids)`**: New DB method, analogous to `mark_comments_deleted()`
- **Post deletion**: `scrape_posts(detect_deletions=True)` tracks seen IDs during full pagination, marks unseen as deleted
- **Agent deletion**: `enrich_agents()` catches 404 → sets `deleted_at`
- **`--detect-deletions` flag**: Now works for both `posts` and `comments` commands

### Automation scripts (Hetzner VM)
- **`scripts/weekly_scrape.sh`**: Lock file, DB backup, staged scrape, email alerts, backup pruning (keep 2)
- **`scripts/monthly_rescrape.sh`**: Full re-scrape with deletion detection, pre/post backups, email on start/fail/complete
- **`scripts/status.sh`**: Dashboard showing DB size, row counts, disk, backups, cron jobs, recent errors

---

## Scraping Cadence

| Schedule | Script | Stages | Duration |
|----------|--------|--------|----------|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | incremental → submolts → comments(--only-missing --skip-empty) → moderators → enrich(--only-missing) → snapshots | ~1-2 hours |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | posts(full, --detect-deletions) → comments(full, --detect-deletions) → enrich(--only-missing) → snapshots | ~5-7 days |

Cron entries:
```
0 2 * * 1  cd ~/moltbook_scraper && bash scripts/weekly_scrape.sh
0 2 1 * *  cd ~/moltbook_scraper && bash scripts/monthly_rescrape.sh
```

---

## VM Operations

**VM**: Hetzner CX23, Nuremberg (re-provision as needed)
**Email alerts**: Set `MOLTBOOK_ALERT_EMAIL` in `.env`, install `msmtp`
**Check status**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB locally**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code to VM**: `scp -r src/ scripts/ vm:~/moltbook_scraper/`

---

## Returning After Absence

1. Check VM status: `ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'`
2. Review logs: `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, clone repo, copy DB, set up cron
4. If >1 month gap: run catch-up manually (incremental → comments → enrich → snapshots)
5. Pull latest DB: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`

---

## Next Steps

### 1. Catch-up scrape on Hetzner VM
Run staged catch-up for the 2-day gap:
```bash
python -u -m src.cli incremental --db data/raw/moltbook.db
python -u -m src.cli submolts --db data/raw/moltbook.db
python -u -m src.cli comments --only-missing --skip-empty --db data/raw/moltbook.db
python -u -m src.cli moderators --db data/raw/moltbook.db
python -u -m src.cli enrich --only-missing --db data/raw/moltbook.db
python -m src.cli snapshots --db data/raw/moltbook.db
```

### 2. Set up cron on VM
Install cron entries and configure msmtp for email alerts.

### 3. Run R analysis pipeline

### 4. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination.

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (5.7 GB with snapshots)
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe
- **Schema**: `src/database.py:_create_tables()` + `_migrate()`
- **Rate limit docs**: `readme_api_limit.md`
- **Comment hard cap**: 500/post, no pagination (API limitation)
- **Platform scale** (2026-03-11): ~2.86M agents, ~2.01M posts, ~13.21M comments, ~19.2K submolts
