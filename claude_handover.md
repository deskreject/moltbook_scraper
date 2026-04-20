# Claude Handover - Moltbook Scraper

**Last updated**: 2026-04-20 end-of-session (session 21 closed; all Phase 3a code + tests + probes complete locally).
**Git state**: Branch `main`, uncommitted Phase 3a changes in `src/database.py`, `src/scraper.py`, `scripts/weekly_scrape.sh`, `scripts/monthly_rescrape.sh`, `tests/test_snapshot_change_detection.py`, `tests/test_database.py`.
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`.

## Start here tomorrow (session 22)

1. Run machine_switch_startup to reload project context (CLAUDE.md, this handover, latest session log).
2. Jump to **Step B** below — no local work is pending. Nothing has been pushed to the VM yet.
3. **Do NOT run `pytest` without a path filter** — it hangs on the pre-existing `test_fetch_all_posts_paginates_until_no_more` failure and leaves orphan Python processes eating RAM (session 21 had to kill ~51 GB of orphans). Use `pytest tests/test_database.py tests/test_snapshot_change_detection.py -v` for the Phase 3a subset.
4. First check before doing anything on the VM: `tasklist | grep python` (local) and `ssh vm 'ps auxf | grep python'` (VM) to catch any runaway processes.

Full design rationale: [session 21 log](CLAUDE/session_logs/2026_04_20_session_log.md). Prior audit + decisions: [session 19](CLAUDE/session_logs/2026_04_14_session_log.md), [session 20](CLAUDE/session_logs/2026_04_16_session_log.md).

---

## Current DB state (VM, pre-Apr-20-weekly)

| Table | Count | Notes |
|---|---|---|
| posts | 2,449 K | |
| submolts | 20,673 | `is_nsfw`/`is_private` 100 % false (likely genuine) |
| moderators | 19,844 | |
| comments | 4,159 K | |
| agents | 175,891 | **`claimed_by` populated for 1 only — backfill pending (Step C)** |
| comment_snapshots | 14.04 M (8.32 GB) | Scheduled for removal in Phase 4 — per audit, 0.0000 % change across all columns |
| post_snapshots | 8.65 M (6.72 GB) | Scheduled for narrowing in Phase 4 |
| scrape_runs | 0 | Empty; Apr 20 weekly is first run with session-19 fix — verify post-run |

**VM volume**: 60 GB used / 79 GB (**80 %**, only 16 GB free). Backup (Apr 20): 22 GB.
**Local DB**: Apr 8, 11 GB, pre-migration. Pull after Phase 4 only.

---

## VM automation (active since 2026-03-16)

**SSH**: `ssh vm` (alias → `root@159.69.34.240`)

| Schedule | Script | Duration |
|---|---|---|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | ~17 h |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | ~5-7 days today; **will be sharded in Step F** |
| Daily 08:00 UTC | `disk_monitor.sh` | <1 s |

**Check**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code**: `scp -r src/ scripts/ vm:~/moltbook_scraper/` then `ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'`

---

## Resume plan — relative order with verification checkpoints

> **Why relative order?** Delays between sessions are expected. Each step lists what to verify *before* acting, so stale assumptions get caught rather than propagated. Do not skip the "Verify before continuing" boxes.

### Step A — Draft Phase 3a migration + code (LOCAL ONLY)

Status: **code complete + locally verified** at end of session 21. See `scripts/verify_phase3a.py` and `scripts/dryrun_snapshots.py` for the verification harness (kept in-repo, re-runnable).

**Local verification results (run on 11 GB Apr 8 DB copy)**:
- Migration 9+10 applies cleanly, additive only.
- First snapshot: 287k metric baselines (one-time, by design) + 19,655 moderator events. Total events = 19,655 (was 910k before Migration 10 — see session 21 log "blast radius" section).
- Second snapshot on unchanged data: 0 inserts across every table. Idempotent.
- All composite indexes used (`EXPLAIN QUERY PLAN` USING INDEX).
- WAL engaged on first open.
- DB delta after one snapshot run: +179 MB.

**Before pushing to VM, resolve probes in `verification_probes.md`** (P1 and P2 are blocking for monthly `--detect-deletions`; P3/P4 are monitoring-only).

**Scope**
- `src/database.py`: new tables (`post_metrics`, `post_events`, `agent_metrics`, `agent_events`, `submolt_metrics`, `submolt_events`, `moderator_events`); `ALTER` to add anchor columns on live tables:
  - Numeric anchors: `posts.hot_score_first`, `posts.hot_score_first_observed_at`, `posts.score_first`; `agents.karma_first`, `agents.follower_count_first`, `agents.following_count_first`; `submolts.subscriber_count_first`.
  - Text anchors: `agents.description_first`, `submolts.description_first`.
  - **Boolean/enum anchors (Migration 10 — added after session-21 blast-radius verification)**: `posts.is_pinned_first`, `posts.is_locked_first`, `posts.is_deleted_first`, `posts.is_spam_first`, `posts.verification_status_first`; `agents.is_claimed_first`. Without these, first snapshot run would emit ~890k baseline events (trips Alert C).
  - Composite indexes (`idx_*_entity_time`); `PRAGMA journal_mode=WAL` in `__init__`.
- `src/database.py`: **deletion-preservation guard** on `upsert_post` AND `upsert_comment`. Both now combine a flag branch AND a content-heuristic branch because live probes P1/P2 (2026-04-20) confirmed Moltbook returns tombstones with `content='[deleted]'` AND `is_deleted:false` — flag-based guard alone would miss the common case. Both also auto-infer `is_deleted=1` from tombstone content. `upsert_comment` now includes `is_deleted` in its INSERT column list so the same CASE WHEN pattern applies. Details in `verification_probes.md`.
- `src/scraper.py`: rewrite `create_snapshots()` as change-driven writer with insertion counts logged (R1 monitoring from session 19). Event writers compare current value against the latest event row, falling back to the `*_first` anchor when no prior event exists — this captures first genuine transitions post-anchor while keeping first-run spike to zero. (Initial draft skipped emission entirely when `old_str is None`, which silently lost every first flip; caught by test #3. Fix: read `*_first` columns from the SELECT and use them as the old-value fallback.)
- **`src/database.py` `_migrate()` structural fix**: migrations was a dict keyed by table name, so duplicate keys (`posts`, `agents`, `submolts` each appeared in both the pre-Phase-3 and Migration-9/10 blocks) silently dropped the earlier columns on fresh DBs. Converted to a `list[tuple[str, list]]` so all blocks execute. Production DBs already had the old columns applied from earlier code generations and are unaffected; this only fixes behavior on fresh checkouts and the test harness.
- `scripts/weekly_scrape.sh` + `scripts/monthly_rescrape.sh`: add lock file mechanism (see session 21 log).
- Cron edit plan: move monthly from `0 2 1 * *` to `55 1 1 * *` (5 min offset to win the lock race).
- `tests/test_snapshot_change_detection.py`: **8 cases, all passing** (`pytest tests/test_snapshot_change_detection.py -v`):
  1. `no_change_emits_nothing` — snapshot twice with identical state → 0 new rows anywhere on second call.
  2. `numeric_change_inserts_one_metric` — bump `posts.upvotes` between calls → exactly 1 row in `post_metrics`.
  3. `boolean_flip_inserts_one_event` — flip `posts.is_pinned` 0→1 after anchor → exactly 1 row in `post_events`. **This test originally failed and surfaced the anchor-fallback bug in the event writer.**
  4. `anchor_set_once` — `hot_score_first` / `is_pinned_first` populated on first call, unchanged by second even when live values move.
  5. `deleted_post_content_preserved_when_flag_set` — flag-based branch of the deletion guard (`posts.is_deleted=1`).
  6. `post_metrics_respects_4_week_cutoff` — post older than 4 weeks gets no metrics rows even when totals change; fresh post does.
  7. `tombstone_content_preserved_without_flag` — **P2 finding**: upsert with `content='[deleted]'` and `is_deleted=false` must preserve stored content AND auto-infer `is_deleted=1` on BOTH posts and comments.
  8. `moderator_turnover_emits_events` — added → role_changed → removed → re-added path; asserts all four `event_type` values.

**No VM push.** All code review happens locally first.

### Step B — Verify Apr 20 weekly outcome + refresh state

**Verify before continuing:**
- `ssh vm 'bash scripts/status.sh'` — confirm weekly finished cleanly.
- Query: `SELECT COUNT(*) FROM post_snapshots WHERE scrape_run_id IS NOT NULL;` — should be >0 (first run with session-19 `scrape_run_id` fix).
- `df -h /mnt/HC_Volume_104999576` — if >85 %, flag; Phase 4 gets tighter.
- `ls -lh ~/moltbook_scraper/data/backups/` — confirm prune to 1 backup worked.

If any check fails, diagnose before Step C. Do not push code to VM while weekly is still running.

### Step C — Run `claimed_by` backfill

**Verify before continuing:**
- No weekly, monthly, or audit script is running on VM (`ps auxf | grep python`).
- WAL mode: **decide here whether to enable WAL on VM DB BEFORE or AFTER backfill.** Recommended: enable WAL first (it's forward-safe), reduces collision risk if anything else needs to read.

```bash
ssh vm 'cd ~/moltbook_scraper && sqlite3 data/raw/moltbook.db "PRAGMA journal_mode=WAL;"'
ssh vm 'cd ~/moltbook_scraper && tmux new -d -s backfill "bash -c \"source .venv/bin/activate && python -u scripts/backfill_claimed_by.py --db data/raw/moltbook.db --log-file logs/backfill-claimed-by.log 2>&1 | tee -a logs/backfill-stdout.log; exec bash\""'
```

**Expected duration**: ~48 h at 60 req/min. Must complete before Step E (Phase 4 archives agents — cannot freeze stale state).

**Verify after:** `SELECT COUNT(*) FROM agents WHERE is_claimed = 1 AND claimed_by IS NOT NULL;` should be close to 174,275 (allowing for a small number of genuine NULLs where API still returns no owner).

### Step D — Push Phase 3a to VM

**Verify before continuing:**
- Backfill complete (Step C done, check log tail).
- No cron run due within next 6 h (weekly Monday; monthly 1st).
- Disk < 85 %.
- Local code changes reviewed — migration is additive (no drops of existing data).

```bash
scp src/database.py src/scraper.py scripts/weekly_scrape.sh scripts/monthly_rescrape.sh vm:~/moltbook_scraper/
ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'
# Update cron (monthly shift to 01:55)
ssh vm 'crontab -l | sed "s|^0 2 1 \* \*|55 1 1 \* \*|" | crontab -'
ssh vm 'crontab -l'  # verify
```

First migration run: start of next weekly cron will invoke `_migrate()` and `_create_tables()`, which are additive (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`). Safe.

**Verify after:** next weekly completes, then
- `SELECT COUNT(*) FROM post_metrics;` — non-zero if any posts mutated.
- `SELECT COUNT(*) FROM post_snapshots WHERE scraped_at > <weekly_start>;` — should be 0 (old writer retired).
- Check `logs/scrape-snapshots.log` for R1-format lines: `inserted_metrics`, `inserted_events`, `entities_scanned`.

### Step E — Phase 4 compression (⚠ USER-SUPERVISED)

**Verify before continuing:**
- Steps A-D complete and stable for at least 1 full weekly cycle.
- `claimed_by` backfill is complete (Step C).
- Volume has ≥ 15 GB free (Parquet temp backup needs room).
- User is available for the duration (stop-cron → migrate → verify → resume-cron window).
- Day of week: NOT Saturday/Sunday (weekly fires Monday 02:00 UTC).

Sub-steps:
1. Parquet backup of `*_snapshots` to `data/backups/pre-compression_YYYY-MM-DD/*.parquet` (zstd).
2. Halt cron: `crontab -l > /tmp/crontab.bak && crontab -r`. Log time + re-enable deadline.
3. Run migration script: reads existing `*_snapshots`, writes into new narrow/event tables, renames originals to `*_snapshots_v1_archive`.
4. Create compatibility VIEWs named `*_snapshots` (UNION archive + new) for R code.
5. `VACUUM` and sanity-check row counts + sample queries.
6. Restore cron: `crontab /tmp/crontab.bak && crontab -l`. **Log in session log that cron is back on.**
7. After 2 weeks stable operation: DROP `*_v1_archive`, DROP compat views (if R migrated), `VACUUM`.

### Step F — Monthly sharding implementation

**Verify before continuing:**
- Phase 4 has been stable for at least 2 weekly cycles (no unexpected snapshot bloat).
- Today's date is earlier than the 20th of the month (monthly fires on the 1st; shard logic must land before next monthly).

Scope:
- `src/cli.py` + relevant scraper methods: add `--submolt-shard {A,B,C}` filter to `posts` and `comments` commands.
- `scripts/monthly_rescrape.sh`: compute shard from current month — `SHARD=$(printf '%s' {A,B,C} | cut -c$((( ($(date +%m) - 1) % 3) + 1))); ... --submolt-shard "$SHARD" ...`.
- Full scan (agents, submolts, moderators) unchanged.
- Document in `CLAUDE.md` which shard runs in which month for audit-trail purposes.

**Verify after:** first sharded monthly completes in < 4 days and covers expected submolt range.

### Step G — Decommission temporary compat views / archive (optional)

Deferred until R analysis has been migrated to query the new narrow tables directly.

---

## Returning after absence (any length)

1. `ssh vm 'bash scripts/status.sh'` — must succeed; if DB locked, check `ps auxf | grep python` for running jobs.
2. `ssh vm 'tail -50 logs/weekly-*.log logs/monthly-*.log'` (latest only).
3. Read latest `CLAUDE/session_logs/YYYY_MM_DD_session_log.md` to see where we stopped.
4. Check `df -h /mnt/HC_Volume_104999576` — volume usage trend.
5. Work through the Resume plan from the earliest uncompleted step. **Always run the step's "Verify before continuing" block.**
6. If the gap exceeded 1 month: pull DB locally only if analysis is imminent (DB transfer is ~30 min on a fast link).

---

## Known gotchas that still apply

- Windows CRLF: always `dos2unix` on VM after any `scp`.
- SQLite pre-WAL: long reads block writers. Phase 3a enables WAL.
- `tmux new -d -s NAME "cmd"` loses stderr if cmd dies — always wrap with `bash -c "... ; exec bash"`.
- `status.sh` "N errors" line is a known false-match on "0 errors" progress lines (cosmetic).
- Test suite has a pre-existing failure `test_fetch_all_posts_paginates_until_no_more` (cursor pagination); not regression.

---

## Key reference

- **Schema**: `src/database.py:_create_tables()` + `_migrate()`
- **Rate limits**: `readme_api_limit.md`
- **Methodology**: `claude_methodology_log.md`
- **Learnings / dead ends**: `claude_learnings.md`
- **Session logs**: `CLAUDE/session_logs/`
- **Archive**: `claude_archive.md`

---

## Work laptop setup (unchanged since session 18)

**SSH**: configured. **Still missing on work laptop**: `.env`, `.venv/`, local `moltbook.db`. See session 16 log if ever setting up.

<details>
<summary>Email alert setup (collapsed)</summary>

### Gmail app password + msmtp on VM
1. Create Gmail app password at https://myaccount.google.com/apppasswords (name: `moltbook-alerts`).
2. Edit `/root/.msmtprc` on VM: set `from`, `user`, `password`.
3. Set `MOLTBOOK_ALERT_EMAIL` in VM `.env`.
4. Test: `echo "Test" | msmtp your.email@example.com`.

Full historical context: `CLAUDE/session_logs/2026_03_15_session_log.md`.
</details>
