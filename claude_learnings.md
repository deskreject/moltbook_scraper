# Learnings — Errors, Dead Ends & Solutions

Errors, failures, choke points, and dead ends encountered across sessions. Purpose: avoid re-pursuing failed directions.

---

## Rate Limiting & Concurrency

**Multi-worker scraping is slower than sequential for this API.**
- Tried `--workers 4`, 8, 16 with token bucket (sessions 6-8). Best sustained rate: ~10-43 req/min. Sequential: ~25-150 req/min with zero 429s.
- Root causes: token contention, retry-bypass bug, micro-burst clustering, infrastructure IP ban
- Full investigation: `readme_api_limit.md`
- **Resolution:** Always use `--workers 1` (default). Parallelize across machines/IPs, not threads.

**Proactive sliding-window throttle failed (session 3).**
- Cold-start burst caused cascading 429 storms. Removed in session 4.
- **Resolution:** Reactive exponential backoff only.

**Production rate limit differs from source code.**
- Source says 100/min, production is 60/min (confirmed via `X-RateLimit-Limit: 60` header).
- **Resolution:** Never trust source code for rate limits; check live headers.

---

## Infrastructure & Deployment

**Ubuntu 24.04 has no `python` binary.**
- Only `python3` exists. Scripts using bare `python` failed silently in cron for a full week (Mar 17-23).
- **Resolution:** Always use `.venv/bin/python` explicitly. Session 13 fix.

**Windows CRLF breaks bash scripts after `scp`.**
- `\r': command not found` on every line. Affects both `.sh` and `.py` files.
- **Resolution:** Always run `dos2unix src/*.py scripts/*.sh` on VM after every code push.

**`ls *.glob` under `set -e` kills script when no matches.**
- `ls -1 *.db` exits with code 2 if no files match, triggering `set -e`.
- **Resolution:** Use `find -name '*.db'` instead (returns empty without error).

**`grep -c` output has trailing whitespace on some systems.**
- Caused `[[ "$count" -gt 0 ]]` to fail with "integer expression expected".
- **Resolution:** Pipe through `tr -d '[:space:]'` and use `${count:-0}` default.

**Snapshot stage OOM-killed on 4GB VM (session 15, 2026-03-26).**
- The snapshot command loads all rows from each live table into Python memory, then bulk-inserts into `*_snapshots` tables. At 11 GB DB / ~5.5M total rows, the Python process hit ~3.5 GB RSS and was killed by the Linux OOM killer (PID 359955, `dmesg` confirmed).
- **Temporary fix:** Added 4 GB swap file on the VM (`/swapfile`, persistent via `/etc/fstab`). This gives ~7.7 GB total virtual memory. Disk dropped from 14 GB → 9.3 GB free (75% used), which is stable given backup pruning keeps only 2 weekly copies.
- **Runway estimate:** Swap buys several weeks to months. DB grows ~50-100K posts/week; the memory pressure comes from snapshot row count, not DB file size. Should hold until ~8-10M total rows before swap is also insufficient.
- **Proper fix needed:** Refactor `src/scraper.py` snapshot functions to batch/stream rows (e.g., `SELECT ... LIMIT 10000 OFFSET N` per table) instead of loading all into memory. This would cap memory at ~50 MB regardless of DB size. See handover.md for implementation notes.

**Hetzner Cloud "Add SSH Key" does not apply to existing servers (session 17, 2026-04-03).**
- The dashboard SSH key feature only injects keys at server creation time. Adding a key there does nothing for running VMs.
- The Hetzner web console requires VM-level credentials (root password), not Hetzner account credentials.
- Original root credentials for this VM are undocumented — access depends entirely on the home PC's SSH key.
- **Resolution:** Add keys via `ssh vm 'echo "KEY" >> ~/.ssh/authorized_keys'` from a machine that already has access. Document root credentials or set a password via `passwd` for emergency access.

**VM disk filled to 100%, silently broke all scrapes for 9 days (session 18, 2026-04-08).**
- Root cause: 38 GB root disk could not hold the live DB (~11 GB) + 2 weekly backups (~21 GB) + 4 GB swap + OS. The Mar 30 weekly backup pushed usage to 100%. Both the Apr 1 monthly and Apr 6 weekly failed immediately on `cp: No space left on device`. Email alerts also failed (msmtp can't create temp files on full disk), so no notification was received.
- **Resolution (session 18):**
  1. Deleted stale backups to free immediate space.
  2. Resized Hetzner volume to 80 GB; ran `resize2fs /dev/sdb`.
  3. Moved DB and backups to the volume (`/mnt/HC_Volume_104999576/moltbook_data/`), symlinked from original paths so all scripts and `scp` commands still work.
  4. Reduced weekly backup retention from 2 to 1. Switched backup method from `cp` to `sqlite3 .backup` (safer for live DBs).
  5. Added standalone `disk_monitor.sh` cron (daily 08:00 UTC) that emails if either root disk or data volume exceeds 80% — runs independently of scrape scripts.
- **Disk budget at 80 GB volume**: DB (~11 GB) + 1 weekly backup (~11 GB) + monthly pre/post (~22 GB during monthly window) = ~44 GB peak. 36 GB headroom for ~1 year of growth at ~1 GB/month.
- **Key lesson:** Disk monitoring must be independent of the scrape pipeline. If the scrape fails due to disk, the in-script `check_disk()` never runs, and if disk is full, email sending also fails. The standalone daily cron catches issues before they cascade.

**Cron email alerts silently failed since deployment (session 15, 2026-03-26).**
- Both `weekly_scrape.sh` and `monthly_rescrape.sh` assigned `EMAIL_TO="${MOLTBOOK_ALERT_EMAIL:-}"` in the Configuration block, *before* `.env` was sourced in the Setup block. Cron runs in a minimal environment with no inherited vars, so `EMAIL_TO` was always empty and `send_email()` short-circuited.
- The manual `echo | msmtp` test worked because it ran in an interactive shell where the var was already exported.
- **Resolution:** Moved `EMAIL_TO` assignment to immediately after `source .env`. Fixed and pushed to VM in session 15.

---

## API Quirks

**`sort=hot` caps at ~70K posts.**
- Default sort is algorithmically limited to ~3 days of high-engagement content.
- **Resolution:** Always use `sort=new` for full archive (session 5).

**Comment counts are stale for deleted comments.**
- 167 posts show `comment_count > 0` but API returns empty. These are deleted comments — not a scraper bug.
- **Resolution:** Accept as data limitation; document in analysis.

**Comments hard cap 500/post, no pagination.**
- Posts with >500 comments are truncated. Affects ~1,507 posts.
- **Resolution:** Accept; sufficient for research. Pass `limit=500` to maximize coverage.

---

## Local Machine Safety

**Never run pytest against the full 11 GB production database multiple times (session 18).**
- Three concurrent pytest runs each loaded the DB into memory, consuming ~45 GB total and freezing the machine.
- Root cause: retrying a background-spawned pytest command instead of waiting for the first one.
- **Resolution:** Only run pytest once. If it goes to background, wait for the result. Tests that touch the DB should use `:memory:` or a small test fixture, not `data/raw/moltbook.db`.

---

## Process & Workflow

**`head -N` pipe blocks background Python process.**
- Launched comments scrape with `| head -20` which blocked waiting for output lines.
- **Resolution:** Never pipe long-running processes through `head`. Use `disown` and monitor via DB queries.

**Disowned process loses stdout when shell exits.**
- Background Python process stdout goes nowhere after terminal closes.
- **Resolution:** Always use `--log-file` flag and monitor via log file or DB queries.

**status.sh error counter counts "0 errors" as errors.**
- `grep -c "error"` matches progress lines containing "0 errors".
- **Status:** Known cosmetic issue, not yet fixed.
