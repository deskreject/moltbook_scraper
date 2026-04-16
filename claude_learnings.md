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

**Agent profile is fetched by NAME, not ID (session 19, 2026-04-14).**
- `/api/v1/agents/{id}` → 404. The working endpoint is `/api/v1/agents/profile?name=X` (see `client.py:fetch_agent_profile`).
- Wasted half an investigation probing id-based variants. Always check the actual scraper code path before re-deriving the API surface.

**`submolts.is_nsfw` and `is_private` appear constant-`false` across the dataset.**
- Verified API returns these fields populated, but every sampled submolt is `false`. Most likely Moltbook hosts no NSFW content, and private submolts are not enumerated by the public `/submolts` listing endpoint by design.
- **Resolution:** Treat both columns as effectively constant in this dataset; do not use as features in analysis. Confirm with one full pass across all submolts when convenient.

---

## Local Machine Safety

**Never run pytest against the full 11 GB production database multiple times (session 18).**
- Three concurrent pytest runs each loaded the DB into memory, consuming ~45 GB total and freezing the machine.
- Root cause: retrying a background-spawned pytest command instead of waiting for the first one.
- **Resolution:** Only run pytest once. If it goes to background, wait for the result. Tests that touch the DB should use `:memory:` or a small test fixture, not `data/raw/moltbook.db`.

---

## Schema / Migration Traps

**`enrich --only-missing` skips already-enriched agents forever, even after a migration adds new enrichment columns (session 19, 2026-04-14).**
- Session 18 migration added `agents.claimed_by`. After 2 weekly scrapes, only 1 of 175,891 rows was populated. Cause: weekly cron runs `enrich --only-missing`, which selects via `get_unenriched_agent_names()` (filters on missing `description`). The 174,275 already-enriched `is_claimed=1` agents predate the migration and never get re-fetched. Only the single newly-discovered agent since the migration got `claimed_by`.
- The upsert uses `COALESCE(excluded.claimed_by, agents.claimed_by)` so a re-fetch is safe (NULL never overwrites). But this also means a stale non-NULL `claimed_by` is never *cleared* if an owner re-binds — acceptable trade-off given how rare that is.
- **Resolution (planned, not yet executed):** extend the unenriched predicate to also include `is_claimed=1 AND claimed_by IS NULL`, then run a one-off backfill on the VM (~48 h at 60 req/min). Do NOT drop `--only-missing` globally — that re-enriches all 174k every weekly run.
- **General lesson:** any migration that adds an enrichment column requires a paired backfill plan; the `--only-missing` predicate must be reviewed.

**Snapshot rows have `scrape_run_id = NULL` for all 22M+ rows, but this is NOT data corruption (session 19, 2026-04-14).**
- `scrape_runs` table is empty; staged CLI commands (used by `weekly_scrape.sh`) never open a run row, so snapshots are written with NULL run_id. Only the `full` command path creates a run row.
- Critical: snapshot tables also have `scraped_at TEXT DEFAULT CURRENT_TIMESTAMP`. Per-row insert time is preserved, so weekly snapshots remain distinguishable as a time series.
- **Do NOT "dedupe" snapshots by entity_id** — would destroy historical state.
- Forward fix (low priority): make `cli.py snapshots` open/close a `scrape_runs` row and pass id through. Do not retro-assign run_ids — clustering by `scraped_at` date is sufficient if ever needed.

**Snapshot growth is structural, not a bug (session 19, 2026-04-14).**
- Each successful weekly snapshot adds ~5 GB (~6.6M rows: comments dominate). Comments are mostly immutable after a few hours, so re-snapshotting the entire `comments` table weekly is mostly wasted bytes.
- At current cadence: ~20 GB/month, fills 80 GB volume in ~2–3 months.
- **Resolution (approved 2026-04-14):** replaced with narrow change-driven `*_metrics` (4-week panel for comments/posts) + `*_events` log; agents track first+latest on live table. See methodology_log and session 19 log. Projected steady-state growth: ~10–15 MB/week.

## Snapshot monitoring (R1 — new design, added 2026-04-14)

**How to read `inserted_metrics` / `inserted_events` counts in weekly snapshot logs.**
Each snapshot run logs per-table: `entities_scanned`, `inserted_metrics`, `inserted_events`. Rules:

- **Normal**: `inserted_metrics` is a small fraction of `entities_scanned` (1–10 % for comments in the 4-week window; near-zero for mature entities). `inserted_events` is very small (transitions are rare).
- **Alert A — change detection broken (writes too much)**: `inserted_metrics > 0.5 × entities_scanned` on a mature table. Likely the diff comparison is failing and every row is being treated as changed. Storage will explode. Stop weekly cron; inspect `scraper.create_snapshots()`.
- **Alert B — change detection broken (writes nothing)**: `inserted_metrics == 0` on a table with ≥1000 entities scanned, where vote counts on the platform have clearly moved. Likely the write path is silently failing. Stop cron; inspect logs.
- **Alert C — event log exploding**: `inserted_events > 1000` per run. Should be dozens, not thousands. Likely boolean comparison is broken (e.g. `0` vs `False` mismatch). Inspect event writer.
- **Where to find**: tail of `logs/scrape-snapshots.log` after each weekly run. Monitoring alerts should also email on any of A/B/C.

---

## SQLite contention & index traps (session 19, 2026-04-14)

**Long-running read query blocks all writers.**
- Ran `audit_snapshot_mutability.py` (large `SELECT ... ORDER BY`) while starting `backfill_claimed_by.py` in parallel in tmux. Backfill's first `commit()` died with `sqlite3.OperationalError: database is locked`. Without WAL mode, a single long read holds a shared lock that blocks writers.
- **Resolution:** For this DB, run heavy read audits and writers sequentially. If true parallelism is needed: `PRAGMA journal_mode=WAL` on the DB (one-time; persistent). Verify current mode via `PRAGMA journal_mode;` before flipping — WAL changes checkpoint behavior and interacts with backups.

**Snapshot audits require composite (entity, scraped_at) indexes.**
- `ORDER BY entity_col, scraped_at` on `*_snapshots` triggers a full external sort without an index that covers both columns. First audit hung 2+ h on agent_snapshots alone. After adding `idx_{table}_snap_entity_time` indexes, same audit ran in 23 s.
- **Resolution:** The indexes now exist on the VM DB (created inline in session 19). If rebuilding from scratch, add these after any bulk snapshot load.

**`tmux new -d -s NAME "cmd"` closes the session when `cmd` exits.**
- If the command errors quickly, the tmux window vanishes and you lose the traceback. First `backfill_claimed_by` attempt looked like it "disappeared" — actually died on SQLite lock, but stderr was gone.
- **Resolution:** Wrap commands with `bash -c "... ; exec bash"` so the shell stays alive after the process exits, and tee stderr to a log file.

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
