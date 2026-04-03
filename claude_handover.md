# Claude Handover - Moltbook Scraper

**Last updated**: 2026-04-03 (session 17)
**Git state**: Branch `main`
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-03-23)

| Table | Count | Status |
|-------|-------|--------|
| posts | ~2,139K | VM ahead (weekly ran Mar 23) |
| submolts | 20,276 | Complete |
| moderators | 18,769+ | Complete (weekly refreshes) |
| comments | ~3,328K | Complete. 167 posts unreachable (stale API counts) |
| agents | 172,798 | Complete. Stubs genuinely have no bio |
| snapshots | From 2026-03-15 | **Stale** — Mar 23 snapshot failed (OOM, now fixed with swap) |

**DB size**: ~11 GB (with snapshots)
**VM DB is ahead** of local. Pull: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**VM disk**: 9.3 GB free / 38 GB (75% used, includes 4 GB swap file)

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
Mar 23 weekly: partial failure — snapshots OOM-killed. Fixed by adding 4 GB swap (session 15). Email alerts also fixed (session 15).

---

## Returning After Absence

1. `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
2. `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, push code + DB, set up cron (see [session 12 log](CLAUDE/session_logs/2026_03_15_session_log.md))
4. If >1 month gap: run catch-up (incremental → comments → enrich → snapshots)
5. Pull latest DB locally

---

## Work Laptop Setup (incomplete — skip if on home PC)

SSH to the Hetzner VM is not yet configured on the work laptop. Key and config are generated, but the public key has not been added to the VM yet.

**Completed (session 17, 2026-04-03):**
- SSH key generated: `~/.ssh/id_ed25519_hetzner` (fingerprint: `SHA256:HNT84AN8gyZgTTRew7gp+l58NI3i890Woy6M1T6WYCY`)
- SSH config file created: `~/.ssh/config` (alias `vm` → `root@159.69.34.240`)

**Blocked — cannot add public key to VM from work laptop:**
- The Hetzner Cloud dashboard "Add SSH Key" only applies to **new** servers, not existing ones.
- The Hetzner web console requires VM-level login (not Hetzner account credentials). Neither `root` with blank password, nor Hetzner account email/password worked. The original root credentials are not documented anywhere in this project.
- **Rescue mode** is an option (Hetzner provides a temporary root password) but was not attempted.

**Resume from home PC** — run this single command:
```bash
ssh vm 'echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJv/94DRn7cPQU9eZyRblraOOWDavcOhQiNc6bVyvGCP moltbook-work-laptop" >> ~/.ssh/authorized_keys'
```
Then test from work laptop: `ssh vm 'echo connected'`

**Investigate on home PC**: How was root access originally provisioned? Check `~/.ssh/` for the key used, and whether a root password was set. Document findings so future VM access isn't dependent on one machine. See session 12 log for original VM setup.

**Also missing on work laptop**: `.env` file, `.venv/`, local copy of `moltbook.db`. See session 16 log.

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

### 5. Refactor snapshots to batch/stream (near-term, before DB doubles)
The snapshot command currently loads all rows per table into Python memory, then bulk-inserts into `*_snapshots`. This caused an OOM kill on the 4 GB VM at 11 GB DB size (session 15). A 4 GB swap file is the temporary fix, but swap will be insufficient once the DB reaches ~8-10M total rows (estimated several months at current growth).

**What to implement:**
- Modify `src/scraper.py` snapshot functions (`save_post_snapshot`, `save_agent_snapshot`, etc.) to iterate in batches (e.g., `SELECT ... LIMIT 10000 OFFSET N`) rather than `SELECT *` into a list.
- Each batch: fetch rows → insert into snapshot table → commit → move to next batch.
- Memory stays flat at ~50 MB regardless of DB size.
- No schema changes needed — only the Python iteration logic changes.
- The swap file can be removed afterward to reclaim 4 GB disk, or kept as general headroom.

**Why not expand disk instead:** The swap/memory pressure comes from the Python process loading rows into memory for the copy, not from the DB file itself. Expanding disk would not prevent the OOM — only batching the reads fixes the root cause. Disk expansion would only be needed if the DB + backups outgrow the 38 GB volume.

Details: [session 15 log](CLAUDE/session_logs/2026_03_26_session_log.md), `claude_learnings.md` (Infrastructure section).

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
