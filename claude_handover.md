# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-20 (session 13)
**Git state**: Branch `main`, committed at `bac2cb6` (uncommitted: venv python fix for weekly/monthly scripts)
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-03-20)

| Table | Count | Location | Status |
|-------|-------|----------|--------|
| posts | ~2,087,028 | VM (fresher) | VM incremental ran Mar 20, local is Mar 13 |
| submolts | 19,593 | Both | Complete |
| moderators | 18,769 | Both | Complete |
| comments | 3,177,832 | Both | Complete. 167 posts unreachable (stale API counts) |
| agents | 171,003 | Both | Complete. Stubs genuinely have no bio |
| snapshots | 2,068,988 post / 3,177,832 comment / 171,003 agent / 19,593 submolt / 18,769 mod | Both | From 2026-03-15, needs refresh after next weekly |

**DB size**: 9.9 GB (with snapshots)
**VM DB is ahead** of local by ~18K posts from Mar 20 incremental. Pull with `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/` when needed.

---

## VM Automation (active as of 2026-03-16)

**SSH**: `ssh vm` (alias configured in `~/.ssh/config` → `root@159.69.34.240`)

| Schedule | Script | Duration |
|----------|--------|----------|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | ~8-10h (moderators ~7h is bottleneck) |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | ~5-7 days |

**Check status**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB locally**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code to VM**: `scp -r src/ scripts/ vm:~/moltbook_scraper/` then `ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'`

**Issue detection**:
- Stage failure → email alert (if msmtp configured) + logged to `logs/weekly-*.log`
- Disk >80% → email alert
- Lock collision → weekly exits; monthly waits 2h then alerts
- **Silent failure gap**: VM crash / cron not firing produces no alert — check status manually

---

## Returning After Absence

1. `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
2. `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, push code + DB, set up cron (see archive session 12)
4. If >1 month gap: run catch-up on VM (incremental → comments → enrich → snapshots)
5. Pull latest DB: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`

---

## Next Immediate Steps

### 1. ~~Configure email alerts~~ DONE (user confirmed working 2026-03-20)

### 2. Commit venv python fix + verify next weekly cron
Scripts now use `$PYTHON` (`.venv/bin/python`) instead of bare `python` (which doesn't exist on Ubuntu 24.04). Fix already pushed to VM and tested. Weekly cron failed silently Mar 17 due to this bug — first real weekly will be **Mon Mar 23 02:00 UTC**.

### 3. Apply upstream schema gaps (low effort, improves data quality)
From upstream `787f2d9`: add `claimed_by` (agents), `creator_id`/`post_count`/`is_nsfw`/`is_private` (submolts), COALESCE fix on submolt upsert, `enrich_submolts()` method.

### 4. Run R analysis pipeline
`analysis/R/01_load_data.R` through `07_owner_analysis.R` — requires fresh snapshots (done)

### 5. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (9.9 GB with snapshots)
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe
- **Schema**: `src/database.py:_create_tables()` + `_migrate()`
- **Rate limit docs**: `readme_api_limit.md`
- **Comment hard cap**: 500/post, no pagination (API limitation)
- **Sequential > concurrent**: 1 worker at ~25-150 req/min beats 16 workers at ~10 req/min (see `readme_api_limit.md`)
- **Windows → VM gotcha**: Always `dos2unix` after `scp` from Windows

---

## Email Alert Setup Guide (step-by-step)

The VM scripts send email alerts on scrape completion, failure, and disk warnings.
This uses **msmtp** (a lightweight SMTP client already installed on the VM) to send
mail through your Gmail account to any recipient (e.g., your Outlook work email).

### Step 1: Create a Gmail App Password

You need this because Gmail blocks regular password login from scripts.

1. Go to https://myaccount.google.com/security
2. Make sure **2-Step Verification** is turned ON (required for app passwords)
3. Go to https://myaccount.google.com/apppasswords
   - If you don't see "App passwords", search for it in the Google Account search bar
4. Under "Select app", type a name like `moltbook-alerts`
5. Click **Create**
6. Google shows a 16-character password like `abcd efgh ijkl mnop` — **copy it now**, you can't see it again
   - Remove the spaces when you use it: `abcdefghijklmnop`

### Step 2: Configure msmtp on the VM

From your **Windows terminal** (Git Bash, PowerShell, or Windows Terminal):

```bash
# Connect to the VM
ssh vm

# Edit the msmtp config file (already created with a template)
nano /root/.msmtprc
```

Replace the placeholder values so the file looks like this:

```
defaults
auth           on
tls            on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile        /root/.msmtp.log

account gmail
host           smtp.gmail.com
port           587
from           YOUR_ACTUAL_GMAIL@gmail.com
user           YOUR_ACTUAL_GMAIL@gmail.com
password       abcdefghijklmnop

account default : gmail
```

- Replace `YOUR_ACTUAL_GMAIL@gmail.com` with your real Gmail address (both lines)
- Replace `abcdefghijklmnop` with the app password from Step 1 (no spaces)

Save and exit nano: `Ctrl+O` → `Enter` → `Ctrl+X`

Verify permissions (should already be 600):
```bash
ls -la /root/.msmtprc
# Should show: -rw------- 1 root root ...
```

### Step 3: Set the recipient email address

```bash
# Still on the VM — edit the scraper's .env file
nano ~/moltbook_scraper/.env
```

Change the last line from:
```
MOLTBOOK_ALERT_EMAIL=YOUR_WORK_EMAIL@outlook.com
```
to your actual work email:
```
MOLTBOOK_ALERT_EMAIL=your.actual.email@youruniversity.edu
```

Save and exit.

### Step 4: Test it

```bash
# Still on the VM
echo "Test alert from Moltbook scraper on $(hostname)" | msmtp your.actual.email@youruniversity.edu
```

Check your inbox (and spam folder). You should receive the test email within a minute.

If it fails, check the log:
```bash
cat /root/.msmtp.log
```

Common errors:
- `authentication failed` → wrong app password, or 2FA not enabled
- `connection refused` → firewall blocking port 587 (unlikely on Hetzner)
- `certificate verification failed` → run `apt-get install ca-certificates`

### Step 5: Verify with a real scrape alert

The next weekly scrape (Monday 02:00 UTC) will send an email summary automatically.
To test sooner, you can trigger a quick manual scrape:

```bash
# On the VM — this runs a tiny incremental (only new posts since last scrape)
cd ~/moltbook_scraper
source .env
python -u -m src.cli incremental --db data/raw/moltbook.db
```

Or test the email function directly from the weekly script:
```bash
cd ~/moltbook_scraper
source .env
echo "Manual test from weekly script" | msmtp "$MOLTBOOK_ALERT_EMAIL"
```

### Notes

- The **sender** is your Gmail. The **recipient** can be any email (Outlook, university, etc.)
- Gmail app passwords don't expire, but you can revoke them at https://myaccount.google.com/apppasswords
- If you ever re-provision the VM, you'll need to redo Steps 2-3 (install msmtp, create config, set .env)
- The `/root/.msmtprc` file is NOT in the git repo (it contains your password). It lives only on the VM
