# Claude Handover - Moltbook Scraper

**Last updated**: 2026-04-08 (session 18)
**Git state**: Branch `main`
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-04-08)

| Table | Count | Status |
|-------|-------|--------|
| posts | 2,240K | Local matches VM (through Mar 30). Weekly catch-up running. |
| submolts | 20,483 | Complete. New fields: `creator_id`, `post_count`, `is_nsfw`, `is_private` (session 18) |
| moderators | 19,655 | Complete (weekly refreshes) |
| comments | 3,552K | Complete. 167 posts unreachable (stale API counts) |
| agents | 173,949 | Complete. New field: `claimed_by` (session 18) |
| snapshots | From 2026-03-15 | **Stale** — Mar 23 & Mar 30 snapshots both failed |

**DB size**: ~11 GB (with snapshots)
**Local DB synced** with VM as of session 18. Pull: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**VM disk**: 55 GB free / 79 GB volume (28% used) + 30 GB free / 38 GB root (19% used)

---

## VM Automation (active since 2026-03-16)

**SSH**: `ssh vm` (alias → `root@159.69.34.240`)

| Schedule | Script | Duration |
|----------|--------|----------|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | ~8-10h |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | ~5-7 days |
| Daily 08:00 UTC | `disk_monitor.sh` | <1s |

**Storage**: DB and backups live on 80 GB volume (`/mnt/HC_Volume_104999576/moltbook_data/`), symlinked from `data/raw/moltbook.db` and `data/backups/`. All scripts and `scp` commands work unchanged.

**Check**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code**: `scp -r src/ scripts/ vm:~/moltbook_scraper/` then `dos2unix` on VM

**History**:
- Mar 23 weekly: 5/6 stages OK, snapshots OOM-killed. Fixed with swap (session 15).
- Mar 30 weekly: 5/6 stages OK, snapshots failed (disk full). Data through Mar 30 is complete.
- Apr 1 monthly & Apr 6 weekly: failed immediately (disk full, no space for backup copy).
- Apr 8 (session 18): disk fixed (80 GB volume, data migrated), weekly catch-up started.

---

## Returning After Absence

1. `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
2. `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, push code + DB, set up cron (see [session 12 log](CLAUDE/session_logs/2026_03_15_session_log.md))
4. If >1 month gap: run catch-up (incremental → comments → enrich → snapshots)
5. Pull latest DB locally

---

## Work Laptop Setup

**SSH**: Configured and working (key added session 18). Test: `ssh vm 'echo connected'`
**Root password**: Set (session 18). Web console login: `root` + chosen password.
**Still missing on work laptop**: `.env` file, `.venv/`, local copy of `moltbook.db`. See session 16 log.

---

## Next Steps

### 1. Verify weekly scrape & new schema fields (immediate)
Weekly scrape started 2026-04-08 ~15:08 UTC. Check completion and verify new fields (`claimed_by`, `creator_id`, `post_count`, `is_nsfw`, `is_private`) are populated:
```sql
SELECT COUNT(*) FROM agents WHERE claimed_by IS NOT NULL;
SELECT COUNT(*) FROM submolts WHERE creator_id IS NOT NULL;
```
Then pull updated DB locally. See [session 18 log](CLAUDE/session_logs/2026_04_08_session_log.md).

### 2. Run monthly scrape (after weekly completes)
Monthly re-scrape with deletion detection. Will fully populate the new schema fields. Run manually or wait for next 1st-of-month cron.

### 3. Run R analysis pipeline
`analysis/R/01_load_data.R` through `07_owner_analysis.R` — requires fresh snapshots (which the weekly should produce if it succeeds this time).

### 4. Refactor snapshots to batch/stream (medium priority)
Snapshot command loads all rows into memory → OOM risk. Batch `SELECT ... LIMIT 10000 OFFSET N` per table. Details: [session 15](CLAUDE/session_logs/2026_03_26_session_log.md), [session 18 archive](claude_archive.md).

### 5. Fix pre-existing test failure (low priority)
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination.

### 6. Fix status.sh cosmetic error counter (low priority)
Matches "0 errors" progress lines as errors. Known issue.

---

## Key Reference

- **Schema**: `src/database.py:_create_tables()` + `_migrate()`
- **Rate limits**: `readme_api_limit.md`
- **API details**: see API Limitations in `CLAUDE.md`
- **Methodology**: `claude_methodology_log.md`
- **Learnings/dead-ends**: `claude_learnings.md`
- **Session logs**: `CLAUDE/session_logs/`
- **Archive**: `claude_archive.md`

---

## Email Alert Setup

See `CLAUDE/session_logs/2026_03_15_session_log.md` and the email guide preserved below.

<details>
<summary>Full email setup guide (Gmail app password + msmtp)</summary>

### Step 1: Create a Gmail App Password
1. Go to https://myaccount.google.com/security — ensure 2-Step Verification is ON
2. Go to https://myaccount.google.com/apppasswords
3. Create app named `moltbook-alerts`, copy the 16-char password (remove spaces)

### Step 2: Configure msmtp on VM
```bash
ssh vm
nano /root/.msmtprc
```
Set `from`, `user` to your Gmail, `password` to app password.

### Step 3: Set recipient in `.env`
```bash
nano ~/moltbook_scraper/.env
# Set MOLTBOOK_ALERT_EMAIL=your.email@example.com
```

### Step 4: Test
```bash
echo "Test" | msmtp your.email@example.com
```
</details>
