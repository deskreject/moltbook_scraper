# Session 21 — 2026-04-20

## Context at session start
- Machine switched; pulled latest repo state; Apr 20 weekly cron running at 02:00 UTC as expected.
- Phase 1 done (session 19), Phase 2 audit done (session 20). Entering Phase 3 design.
- Local DB is still Apr 8 / pre-migration (11 GB); VM DB is 22 GB with new columns.

## State deltas since session 20 (2026-04-16)

| Metric | Session 20 | Today | Note |
|---|---|---|---|
| Volume usage | 48 % / 40 GB free | **80 % / 16 GB free** | Runway shrunk from ~8 wk to ~3 wk |
| Latest weekly backup | 16 GB (Apr 13) | **22 GB (Apr 20)** | +6 GB in 7 days (worse than prior ~5 GB/wk estimate) |
| `scrape_run_id` in snapshots | Untested | First run with session-19 fix is **today's weekly** — verify post-run |
| Backfill `claimed_by` | 1/174,275 | Unchanged — blocked by audit lock, now by weekly lock | |

Implication: Phase 3 (stops new bleeding) and Phase 4 (compresses existing 15 GB of snapshots) are now timing-critical in combination. Without Phase 4, Phase 3 only stops further growth — existing backlog alone will not fit in the 100 GB hard cap.

## Phase 3 design (approved in this session)

### Revised per-column policy

The session-19 uniform 5 % gate is superseded. Gate depends on column type, because storage cost per changed row differs by 2+ orders of magnitude between a text field and a boolean.

**Policy rules:**
- **Text / URL / JSON on an immutable entity** (posts.title/content, comments.content, etc.): live table only, never snapshotted.
- **Text / URL / JSON on a mutable entity** (agents.description, submolts.description): anchor-only (first + latest) on the live table.
- **Numeric counters** (karma, followers, votes, subscriber_count, comment_count): change-driven insert into `*_metrics` panel. No gate — numeric is cheap.
- **Booleans / enums** (is_pinned, is_locked, is_deleted, is_spam, is_claimed, verification_status): `*_events` log — one row per transition.
- **Cosmetic URLs** (avatar_url, banner_url): dropped from snapshots entirely; anchor on live table only.
- **Timestamps** (last_activity_at, updated_at): monotonically increase → live table's latest value is sufficient.

### Per-table outcome

| Table | Action |
|---|---|
| `comment_snapshots` | **Drop entirely.** Audit shows 0.0000 % change across 9.88 M pairs on every column. Live `comments` table + `comments.first_observed_at` is sufficient. |
| `post_snapshots` | Replace with `post_metrics` panel (upvotes/downvotes/comment_count) **with 4-week age cutoff**, and `post_events` log (is_pinned/is_locked/is_deleted/is_spam/verification_status). Add `posts.hot_score_first`, `hot_score_first_observed_at`, `score_first`. |
| `agent_snapshots` | Replace with `agent_metrics` (karma/follower_count/following_count) — no age cutoff, change-driven — and `agent_events` (is_claimed transitions). Anchor columns on live `agents`: `description_first`, `first_observed_at`. |
| `submolt_snapshots` | Replace with `submolt_metrics` (subscriber_count + description_hash for change-detection on text) and `submolt_events` (none at present; reserved). Anchor columns: `description_first`, `description_latest`, `first_observed_at`. |
| `moderator_snapshots` | Replace with `moderator_events` — one row per appointment/removal. |

Projected steady-state weekly growth post-Phase 3: ~10–15 MB/week (vs. current ~6 GB/week).

### Deletion-content preservation (NEW critical guard)

**Vulnerability discovered this session** in `src/database.py:414` and `:603`:

```sql
ON CONFLICT(id) DO UPDATE SET content = excluded.content  -- unconditional
```

Both `upsert_post` and `upsert_comment` overwrite `content` on any conflict. Currently masked by the fact that `mark_*_deleted` works by *absence from API response* (item no longer appears in listing → `upsert_*` never runs for deleted items). If Moltbook ever changes to returning tombstones (e.g. `content="[deleted]"`), preserved content would be silently overwritten.

**Fix (bundled in Phase 3a):**

```sql
content = CASE
    WHEN posts.is_deleted = 1 THEN posts.content
    ELSE excluded.content
END
```

Same for comments. No behavioral change until/unless API shifts; protects research value for free.

### Weekly/monthly lock mechanism

Minimal, file-based, with stale-lock recovery:

```bash
# monthly_rescrape.sh (top)
LOCK=~/moltbook_scraper/.monthly_running
trap 'rm -f "$LOCK"' EXIT INT TERM
date -Iseconds > "$LOCK"

# weekly_scrape.sh (top)
LOCK=~/moltbook_scraper/.monthly_running
if [ -f "$LOCK" ]; then
  AGE_MIN=$(( ($(date +%s) - $(stat -c %Y "$LOCK")) / 60 ))
  if [ "$AGE_MIN" -gt 10080 ]; then  # > 7 days
    echo "WARN: stale monthly lock, proceeding anyway" | tee -a logs/cron.log
    rm -f "$LOCK"
  else
    echo "Monthly in progress since $(cat $LOCK) — skipping weekly"
    exit 0
  fi
fi
```

**Cron offset:** shift monthly from `0 2 1 * *` to `55 1 1 * *` so if the 1st is a Monday, monthly writes its lock 5 min before weekly checks for it.

**Deliberately NOT handled** (lightweight-by-design choices):
- `flock`/`mutex` for simultaneous-write races — 5-min cron offset solves it.
- Monthly failing to write the lock (disk full) — script would fail loudly in cron.log anyway.
- Signal-handler race on `trap` — bash `trap` is sufficient for our cadence.

### Monthly redesign: 3-shard by submolt

**Monthly's unique job** (not covered by weekly): (a) detect deletions, (b) refresh numerics for items older than the weekly's 4-week panel window.

**Runtime constraint:** hard limit < 7 days per monthly run.

**Shard-3 design:**
- Shard A = submolts with first char A-H
- Shard B = I-P
- Shard C = Q-Z
- Shard picked by `(MONTH - 1) % 3`, so Jan→A, Feb→B, Mar→C, Apr→A, ...
- Full coverage of any given item every 3 months. Deletion-detection lag ≤ 3 months.
- Agents / submolts (metadata) / moderators / enrichment: **full scan every monthly** (small enough — 175 K, 20 K).
- Posts / comments deletion + numeric refresh: **sharded ⅓**.

**Expected runtime (rough, scaled from session 20 weekly durations):**
- Agents full: ~9-10 h
- Submolts + moderators full: ~2 h
- Posts shard ⅓: ~1.5-2 days
- Comments shard ⅓ (deletion only, no content re-fetch): ~1-1.5 days
- **Total: ~3-4 days/monthly**. Headroom to 7-day limit holds for ~24 months at current growth.

**Sustainability re-evaluation policy:** annually, read actual runtimes from `monthly-*.log`. If any shard crosses 4 days, move to 4 shards. Simple config change.

**Explicit tradeoff accepted:** no per-post numeric trajectory for posts older than 4 weeks at better-than-quarterly cadence. Audit shows vote change rate for posts is already 0.003 % — this is effectively lossless.

### WAL mode

Enable `PRAGMA journal_mode=WAL` as part of Phase 3a DB init, so concurrent read-heavy audits don't block writers. Pre-existing gap flagged in session 19 after the audit-vs-backfill collision.

### Composite indexes

Mirror session 19's `idx_*_snap_entity_time` pattern on the new narrow tables: `idx_post_metrics_entity_time`, `idx_agent_metrics_entity_time`, `idx_submolt_metrics_entity_time`, plus `idx_*_events_entity_time`.

## Phase 4 reminder

Phase 4 compresses the existing 15 GB of `*_snapshots` into the new narrow tables, then drops / archives originals. Requires **user supervision** (cron must be halted for hours to days). Disk is now tighter — Phase 4 must run early in the week, never right before a Monday, and temp Parquet backup must fit in <10 GB headroom.

## Files created / modified this session

- `CLAUDE/session_logs/2026_04_20_session_log.md` — this file.
- `claude_handover.md` — rewrote resume-steps as relative-order checklist with verification checkpoints.
- `claude_methodology_log.md` — added Phase 3 refined per-column policy, deletion-preservation guard, lock mechanism, 3-shard monthly design, WAL mode; superseded the uniform 5 % gate entry.
- `CLAUDE.md` — added Phase 3 reproducibility section.
- `claude_learnings.md` — minor addition on the deletion-preservation vulnerability discovery.
- `claude_archive.md` — archived stale handover / methodology entries superseded by Phase 3 design.
- `src/database.py`, `src/scraper.py` — Phase 3a code draft.
- `scripts/weekly_scrape.sh`, `scripts/monthly_rescrape.sh` — `.monthly_running` sentinel + lock.
- `scripts/verify_phase3a.py`, `scripts/dryrun_snapshots.py` — verification harness (kept in repo for re-running before future migrations).
- `verification_probes.md` — tracks live-API probes that couldn't be resolved locally.

## Phase 3a pre-deployment verification (late-session)

Before pushing to VM I ran local verifications against a copy of the 11 GB Apr 8 DB (see `scripts/verify_phase3a.py` + `scripts/dryrun_snapshots.py`).

### First-run blast-radius discovery (critical)

Initial draft of the event-log writer compared current DB state against latest event row. On first run, no prior event → every flagged post/agent looked like a transition:

| Table | First-run inserts (original draft) |
|---|---:|
| post_events | 718,793 (pinned + spam + verification_status non-default) |
| agent_events | 172,396 (all claimed agents) |
| moderator_events | 19,655 (all active pairs) |
| **Total events** | **910,844** |

Exceeds the Alert C threshold (>1000/run) by 3 orders of magnitude. Every subsequent weekly cron run would look like a broken writer on first deploy.

### Fix applied — Migration 10 + writer gating

Added boolean/enum anchor columns on live tables to capture initial state:
- `posts.is_pinned_first`, `is_locked_first`, `is_deleted_first`, `is_spam_first`, `verification_status_first`
- `agents.is_claimed_first`

Changed `_snapshot_posts` and `_snapshot_agents` to skip event emission when `old_str is None` (no prior event row) — initial state is recoverable from the anchor. Transitions are the only thing emitted as events.

### Post-fix measurements (on 11 GB Apr 8 DB copy)

| Table | First run | Second run (unchanged data) |
|---|---:|---:|
| post_metrics (≤4-week posts) | 93,021 | 0 |
| post_events | **0** | 0 |
| agent_metrics | 173,949 | 0 |
| agent_events | **0** | 0 |
| submolt_metrics | 20,483 | 0 |
| moderator_events | 19,655 | 0 |
| **Total events** | **19,655** (98 % reduction) | 0 |
| DB delta | +179 MB | 0 MB |

Metrics tables seed one anchor row per entity on first run (by design — these are the metric baseline, not events). Second run is idempotent — zero inserts across all six tables.

Moderator first-run 19,655 is above Alert C's 1000 threshold but is bounded, one-time, and semantically meaningful (pairs active at observation start). Documented in `CLAUDE.md`.

### Deletion-guard enhancement

Original Phase 3a guard checked only `posts.is_deleted = 1`, missing the tombstone-on-response case: API returns a previously-live post with `content='[deleted]'` and `is_deleted=True` in the same scrape where platform tombstones it. The upsert runs BEFORE `mark_posts_deleted` → content clobbered.

Extended `upsert_post` guard to `CASE WHEN posts.is_deleted = 1 OR excluded.is_deleted = 1 THEN posts.<col>`. Comments retain narrower guard because `is_deleted` isn't in the comments INSERT column list — probe P2 in `verification_probes.md` tracks the open question.

### Other verifications (all passing)

- `created_at` has zero NULLs on posts and comments (4-week cutoff safe).
- `EXPLAIN QUERY PLAN` confirms all six latest-row queries use the new composite indexes.
- `PRAGMA journal_mode` returns `wal` after `Database()` opens file.
- Full migration applies in <1 s on 11 GB DB; `create_snapshots()` completes in 42 s.

### Pending live-API probes

See `verification_probes.md`. Blocking for monthly `--detect-deletions`: P1 (post tombstone format) and P2 (comment tombstone format). Non-blocking monitoring: P3 (WAL on VM), P4 (first-run DB size), P5 (monthly-shard runtime).

## P1 / P2 resolution and follow-on fixes (late-session addendum)

### Live API probe outcome

Probed P1 and P2 directly against Moltbook with the single tombstoned post (`24fe0690-4f8d-4928-9ba1-97d8e1e9b86e`) and the two tombstoned comments (parent post `a6a8d342-…`) already present in the local DB. Worst case confirmed: API returns `HTTP 200` with `{"content": "[deleted]", "title": "[deleted]", "is_deleted": false}` on both endpoints. The platform never flips the `is_deleted` flag — it only removes the row from feed listings, which is why `mark_*_deleted` eventually catches it via absence-from-listing, but by then `upsert_*` has already clobbered content.

Flag-based guard alone (the state at the start of session 21) would silently miss every tombstone in practice. Guard rewritten to content-heuristic on title/content/url + is_deleted auto-inference. `upsert_comment` INSERT column list extended to include `is_deleted` so the same CASE pattern compiles. Details in `verification_probes.md` (both probes marked Resolved 2026-04-20) and `claude_learnings.md`.

### Two new code-quality bugs discovered while writing the unit tests

**Bug 1 — `_migrate()` dropped Migrations 2, 3, 7 on fresh DBs.** `migrations` was a dict keyed by table name. `posts`, `agents`, and `submolts` each appeared twice (early column additions + anchor columns); dict-literal semantics silently overwrote the first entry. Production DBs had those columns applied by earlier code generations so the drop was invisible there. Test harness hit it on the first fresh DB: `table submolts has no column named creator_id`. Converted to `list[(table, columns)]` so both blocks execute.

**Bug 2 — event writer would never emit transitions.** Initial `_snapshot_posts` / `_snapshot_agents` read the latest event row and skipped emission on `None`. Since first observation deliberately emits nothing (anchors carry initial state), every subsequent flip saw `old_str is None` too and was skipped. Events tables would have remained permanently empty in production. Fix: extend SELECT to pull `*_first` columns; when `old_str is None`, fall back to the anchor as the prior value. Caught by `test_boolean_flip_inserts_one_event`.

### Unit test harness

New file `tests/test_snapshot_change_detection.py` — 8 tests, all passing:

1. `no_change_emits_nothing` — second snapshot on unchanged data inserts zero rows anywhere
2. `numeric_change_inserts_one_metric` — upvote bump → exactly one `post_metrics` row
3. `boolean_flip_inserts_one_event` — first flip after anchor emits exactly one event (**this is the test that caught Bug 2**)
4. `anchor_set_once` — `*_first` columns are write-once; later live-value changes do not overwrite
5. `deleted_post_content_preserved_when_flag_set` — flag branch of the deletion guard
6. `post_metrics_respects_4_week_cutoff` — age cutoff excludes old posts from the metrics panel
7. `tombstone_content_preserved_without_flag` — P2 finding: content heuristic preserves posts AND comments, auto-infers `is_deleted=1`
8. `moderator_turnover_emits_events` — added → role_changed → removed → re-added path

Also added `db.close()` to 7 tests in `test_database.py` — Windows WAL cleanup regression caused by the session 21 `PRAGMA journal_mode=WAL` change; unrelated to test correctness but blocks CI on Windows.

### Dryrun re-verification after the two bug fixes

Re-ran `scripts/dryrun_snapshots.py` on a fresh copy of the 11 GB Apr 8 DB. First-run blast radius unchanged:

| Table | First run |
|---|---:|
| post_metrics | 85,561 |
| post_events | **0** |
| agent_metrics | 173,949 |
| agent_events | **0** |
| submolt_metrics | 20,483 |
| moderator_events | 19,655 |
| DB delta | +178 MB |

Anchor-fallback fix does not regress the bounded first-run property (current state equals anchor → no diff → no emission). Elapsed 156 s.

### Files touched this addendum

- `src/database.py` — upsert_comment content-heuristic guard + is_deleted column in INSERT list; `_migrate()` dict → list conversion.
- `src/scraper.py` — `_snapshot_posts` / `_snapshot_agents` read `*_first` anchors and use them as event-writer fallback.
- `tests/test_snapshot_change_detection.py` — new, 8 cases.
- `tests/test_database.py` — `db.close()` added at end of 7 existing tests.
- `verification_probes.md` — P1 / P2 marked Resolved 2026-04-20 with findings.
- `claude_learnings.md` — three new entries (dict-migration trap, tombstone-without-flag, event-writer anchor fallback).
- `claude_methodology_log.md` — tombstone entry rewritten to content-heuristic; two new entries for event-writer fix and migrations list.
- `claude_handover.md` — Step A test list revised from 6 placeholder cases to 8 passing cases.

## End-of-session cleanup (pre-handover to session 22)

- Killed 4 orphan `python -m pytest` processes left running from earlier in the session (PIDs 14580, 44800, 25660, 45788; ~51 GB RAM combined, dominated by 14580 at 43 GB). Root cause: background full-suite runs hung on the pre-existing `test_fetch_all_posts_paginates_until_no_more` failure; never reaped. Added a Process-&-Workflow entry to `claude_learnings.md`: scope pytest to the affected files when backgrounding, or run foreground so hangs are visible.
- Task #9 marked completed (was `in_progress`; all 8 tests passing was documented in the addendum above).
- All open work for session 21 closed. Next session begins at **Step B** in `claude_handover.md` (verify Apr 20 weekly VM outcome). No local code changes remain; nothing has been pushed to VM yet.
