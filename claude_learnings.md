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
