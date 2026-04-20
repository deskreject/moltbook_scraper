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

**Hetzner Cloud "Add SSH Key" does not apply to existing servers (session 17, 2026-04-03).**
- The dashboard SSH key feature only injects keys at server creation time. Adding a key there does nothing for running VMs.
- The Hetzner web console requires VM-level credentials (root password), not Hetzner account credentials.
- Original root credentials for this VM are undocumented — access depends entirely on the home PC's SSH key.
- **Resolution:** Add keys via `ssh vm 'echo "KEY" >> ~/.ssh/authorized_keys'` from a machine that already has access. Document root credentials or set a password via `passwd` for emergency access.

**Disk monitoring must be independent of the scrape pipeline (lesson from session 18 outage).**
- If a scrape fails due to disk-full, the in-script `check_disk()` never runs; if disk is full, email sending also fails (msmtp can't create temp files) → no alert, silent 9-day outage is possible.
- **Resolution:** `scripts/disk_monitor.sh` runs as standalone daily cron (08:00 UTC), independent of scrape scripts, alerts on >80 % on either mount. Full outage narrative: `claude_archive.md` entry 2026-04-08.

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

**Do NOT dedupe historical `*_snapshots` by `entity_id` when `scrape_run_id IS NULL`.**
- Historical (pre-Phase-4) snapshot rows have `scrape_run_id = NULL` because staged CLI commands never opened a `scrape_runs` row. Looks like corruption; is not. `scraped_at TEXT DEFAULT CURRENT_TIMESTAMP` preserves per-row time identity.
- Deduping by entity_id would collapse the time series. Always cluster by `scraped_at` date instead.
- Post-Phase-4: this is moot for new writes (narrow tables always have run_id), but the archived `*_snapshots_v1_archive` retains the NULL rows.

**`_migrate()` as a dict keyed by table silently drops duplicate keys (session 21, 2026-04-20).**
- Migrations 2, 3, 7 (early per-table column additions) and Migration 9/10 (anchors) both keyed on `posts` / `agents` / `submolts`. Later entries overwrote earlier ones; only the anchor block actually ran on fresh DBs. Production DBs had the early columns applied by earlier code generations so the drop was invisible there — until the test harness created a fresh DB and hit `table submolts has no column named creator_id`.
- **Resolution:** convert `migrations` to a `list[(table, columns)]` so blocks with the same table name both execute.
- **General lesson:** never use a dict keyed by table-name to list migrations — migrations are append-only and may re-target the same table across generations.

**Deletion guards cannot rely on the API flipping `is_deleted` (session 21, 2026-04-20).**
- Live probes P1 (posts) and P2 (comments) against the Moltbook API returned tombstoned items as `content='[deleted]'`, `title='[deleted]'`, AND `is_deleted:false`. The API never sets the flag; it only stops listing the row in feed endpoints. So a flag-based guard (`CASE WHEN excluded.is_deleted = 1 THEN ... END`) simply never fires in the actual observed data path.
- **Resolution:** guard must be content-heuristic — check `excluded.content = '[deleted]'` AND preserve the stored content, AND auto-infer `is_deleted = 1` in the same UPSERT. Applied to both `upsert_post` and `upsert_comment`. The narrower flag-only guard we had at the start of session 21 would have been a no-op in production for the actual worst case.
- **General lesson:** never design deletion-preservation logic around flags until you have empirically confirmed, with a live API call against a known-deleted row, that the platform sets the flag. Reddit-like platforms often use string-sentinel tombstones instead.

**Change-driven event writer must fall back to the first-observation anchor when no prior event exists (session 21, 2026-04-20).**
- Phase 3a initial draft of `_snapshot_posts` / `_snapshot_agents` read the latest `*_events` row for each (entity, field) pair and skipped emission when `None`. Intent: avoid a ~718k-row baseline spike on first run. Unintended consequence: since first observation deliberately emits no event, the first *genuine* transition after anchoring also sees `old_str is None` — so it gets skipped too, the event table stays empty, every subsequent check finds `None` again, and the log is permanently empty.
- Caught by `tests/test_snapshot_change_detection.py::test_boolean_flip_inserts_one_event`, which failed in a way that made the design gap obvious.
- **Resolution:** extend the SELECT in `_snapshot_posts` / `_snapshot_agents` to pull `*_first` anchor columns; when `old_str is None`, substitute the anchor as the prior value. Keeps first-run bounded (current=anchor → no diff, no emission) while emitting first flips correctly. Dryrun on the 11 GB Apr 8 copy still shows post_events=0 and agent_events=0 after the fix, matching the pre-fix bounded-spike behavior.
- **General lesson:** when a writer defers to anchors for initial state, the change-detection code must *read* those anchors too — otherwise the anchor is a memory the writer cannot consult.

---

## SQLite contention & index traps (session 19, 2026-04-14)

**Long-running read query blocks all writers (pre-WAL).**
- Ran `audit_snapshot_mutability.py` in parallel with `backfill_claimed_by.py` in tmux. Backfill's first `commit()` died with `sqlite3.OperationalError: database is locked`. Without WAL, a single long read holds a shared lock that blocks writers.
- **Resolution (planned in Phase 3a):** `PRAGMA journal_mode=WAL` in `DatabaseManager.__init__`. Forward-safe, persistent. Until that lands: run heavy read audits and writers sequentially.

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

**Orphan `pytest` processes accumulate tens of GB of RAM when left hung.**
- Session 21: two background `python -m pytest` tasks (no path filter → hit pre-existing-failure `test_fetch_all_posts_paginates_until_no_more`) hung instead of failing; held 43 GB + 7.7 GB RAM until manually killed next session.
- Root cause: full-suite invocation on Windows where that test hangs; the background-task wrapper never reaps on hang.
- **Resolution:** Always scope pytest to the affected files when running in background — e.g. `pytest tests/test_database.py tests/test_snapshot_change_detection.py`. If a full-suite run is ever needed, use `pytest --deselect tests/test_scraper.py::test_fetch_all_posts_paginates_until_no_more` or run in foreground so a hang is immediately visible. Check `tasklist | grep python` at session start and kill orphans before they pile up.
