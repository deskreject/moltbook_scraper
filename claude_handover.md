# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-23 (session 14)
**Git state**: Branch `main`
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-03-23)

| Table | Count | Status |
|-------|-------|--------|
| posts | ~2,139K | VM ahead (weekly ran Mar 23) |
| submolts | 19,593+ | Complete |
| moderators | 18,769+ | Complete (weekly refreshes) |
| comments | ~3,328K | Complete. 167 posts unreachable (stale API counts) |
| agents | 171,003+ | Complete. Stubs genuinely have no bio |
| snapshots | From 2026-03-15 | Needs refresh after weekly completes |

**DB size**: ~10 GB (with snapshots)
**VM DB is ahead** of local. Pull: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`

---

## VM Automation (active since 2026-03-16)

**SSH**: `ssh vm` (alias → `root@159.69.34.240`)

| Schedule | Script | Duration |
|----------|--------|----------|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | ~8-10h |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | ~5-7 days |

**Check**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code**: `scp -r src/ scripts/ vm:~/moltbook_scraper/` then `dos2unix` on VM

First successful weekly: Mar 23 02:00 UTC (verified — see [session 14 log](CLAUDE/session_logs/2026_03_23_session_log.md)).

---

## Returning After Absence

1. `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
2. `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, push code + DB, set up cron (see [session 12 log](CLAUDE/session_logs/2026_03_15_session_log.md))
4. If >1 month gap: run catch-up (incremental → comments → enrich → snapshots)
5. Pull latest DB locally

---

## Next Steps

### 1. Apply upstream schema gaps (low effort)
`claimed_by` (agents), `creator_id`/`post_count`/`is_nsfw`/`is_private` (submolts), COALESCE fix on submolt upsert, `enrich_submolts()`. Details: [session 13 log](CLAUDE/session_logs/2026_03_20_session_log.md).

### 2. Run R analysis pipeline
`analysis/R/01_load_data.R` through `07_owner_analysis.R` — requires fresh snapshots.

### 3. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination.

### 4. Fix status.sh cosmetic error counter
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
