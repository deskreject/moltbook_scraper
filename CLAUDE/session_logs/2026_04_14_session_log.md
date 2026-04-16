# Session 19 — 2026-04-14

## Goals
1. Diagnose session-18 follow-up: new fields unpopulated + 11→22 GB DB doubling.
2. Approve + begin executing the snapshot-redesign plan.

## Diagnosis (pre-outage phase)

**`claimed_by` bug (scraper, not API):** weekly `enrich --only-missing` selects via `get_unenriched_agent_names()` which filters on missing `description`. The 174,275 already-enriched `is_claimed=1` agents predate the migration and are skipped forever. Only 1 of 175,891 populated.

**`is_nsfw`/`is_private`:** API returns them, but 100 % false. Likely genuine — Moltbook hosts no NSFW, and private submolts aren't enumerated by the public listing endpoint. Needs one-shot confirmation.

**DB doubling is structural, not corruption.** All 14 M `comment_snapshots` and 8.65 M `post_snapshots` rows have `scrape_run_id = NULL` because staged CLI commands never open a `scrape_runs` row. But `scraped_at TEXT DEFAULT CURRENT_TIMESTAMP` preserves per-row time identity — *do not dedupe by entity_id*. Only 4 snapshot runs exist in DB (2026-03-11, 03-15, 04-09, 04-13). Apr 9 + Apr 13 added ~13 M rows ≈ ~10 GB, matching the doubling.

## Plan approved

Full rationale + decisions in this log's predecessor (preserved in git). Headline:
- 4-week panel for comment/post `*_metrics` (change-driven inserts).
- Agent first+latest anchors on live table.
- `hot_score_first` + `hot_score_first_observed_at` on live `posts` (one-time ~85 MB).
- Event log (`*_events`) for boolean flips.
- Compression gate: content columns must show <5 % change rate across existing snapshots.
- VM hard cap: 100 GB. Projected forward growth: ~10–15 MB/week.

## Phase 1 — executed

| File | Change |
|---|---|
| `src/database.py` | Extended `get_unenriched_agent_names()` — also returns `is_claimed=1 AND claimed_by IS NULL`. |
| `src/cli.py` | Wired `scrape_run_id` into `snapshots` command (forward-only). |
| `scripts/backfill_claimed_by.py` | New. Resumable, tmux, ~48 h ETA at 60 req/min. |
| `scripts/probe_submolt_flags.py` | New. One-shot pagination probe → `tables/submolt_flag_probe_*.csv`. |

All 4 files pushed to VM + `dos2unix`.

## Phase 2 — executed (partial)

Created `scripts/audit_snapshot_mutability.py`. Counts per-column change rates across consecutive snapshot pairs per entity. Writes CSV + persists into permanent `snapshot_mutability_evidence` DB table (citable in paper).

**First run hung 2 h** on agent_snapshots due to missing composite index — `ORDER BY entity, scraped_at` triggered full sort on each table. Killed.

**Fix:** created composite indexes `idx_{table}_entity_time` on all four snapshot tables (seconds to build via `CREATE INDEX`). Re-ran with `print(..., flush=True)` and logged to `logs/audit-snapshot.log`.

### Results so far

**agent_snapshots** (23 s, 513,387 pairs):

| Column | Change rate |
|---|---|
| description | 0.0006 |
| is_claimed | 0.0006 |
| avatar_url | 0.00005 |
| owner_json | 0.0000 |
| metadata_json | 0.0000 |
| following_count | 0.0041 |
| karma | 0.0215 |
| follower_count | 0.0219 |

**post_snapshots** (4,076 s, 6,203,260 pairs):

| Column | Change rate |
|---|---|
| title / content / url / author_name / submolt_name / is_pinned | 0.0000 |
| upvotes | 0.00002 (134 / 6.2 M) |
| downvotes | 0.0000005 |
| comment_count | 0.00003 |

**Interpretation (preliminary, before comments finish):**
- Agent content fields (description, avatar, owner_json, metadata_json) clear the <5 % gate by 3 orders of magnitude → safe to store as first+latest anchor.
- Post **everything** is near-zero change. Posts mature in hours; the 4-week panel cutoff is well-justified. Even numeric metrics change on fewer than 0.003 % of pair-observations, meaning change-driven metric inserts will be vanishingly small.
- `comment_snapshots` still running on VM at session close.

## Phase 2 problem encountered: SQLite read/write contention

Backfill was started in tmux in parallel with audit. First commit failed with `sqlite3.OperationalError: database is locked` and the script died silently (tmux `-d` session closes when its command exits with exit code 0 and only one window). Root cause: audit holds a long read transaction; DB is not in WAL mode, so readers block writers. Resolution: wait for audit to finish before restarting backfill. For future parallel reader/writer scripts, enable WAL mode (`PRAGMA journal_mode=WAL`) on DB init.

## VM state at session close

- Audit running: `~/moltbook_scraper/logs/audit-snapshot.log` (comment_snapshots pending).
- Backfill: **not running** — blocked on audit; restart after audit finishes.
- Volume `/mnt/HC_Volume_104999576`: 36 GB used / 79 GB. Root disk 19 %.
- Weekly cron still active (next run Mon 2026-04-20 02:00 UTC).

## Files touched
- `src/database.py`, `src/cli.py` — extended.
- `scripts/backfill_claimed_by.py`, `scripts/probe_submolt_flags.py`, `scripts/audit_snapshot_mutability.py` — new.
- VM DB: 4 composite indexes `idx_{agent,post,comment,submolt}_snap_entity_time`; new table `snapshot_mutability_evidence`.

## Immediate next session
1. Check audit log — wait for `comment_snapshots` section to complete.
2. Restart backfill in tmux (use a wrapper that doesn't exit the session on error).
3. Run `probe_submolt_flags.py` on VM.
4. Review full audit results → decide which columns pass the 5 % compression gate → design Phase 3 schema migration.
