# Session 23 — 2026-04-24

Machine-switch startup on home PC. Verified Apr 20 weekly completed. Diagnosed claimed_by-backfill failure → traced to a missing commit in `enrich_agents`. No code changes this session; pausing before applying the fix.

## Context at session start

- Machine switched (home PC). Local repo clean on `main`; HEAD `86d543d` (Phase 3a local, unpushed).
- Uncommitted doc edits carried from session 22: `claude_archive.md`, `claude_handover.md`, `claude_learnings.md`, plus untracked `2026_04_21_session_log.md`.
- Apr 20 weekly cron started 2026-04-20 02:00 UTC, expected to finish Apr 23–24 per session-22 projection.

## Spot-check against Apr 21 handover (Return-after-delay: Apr 24–26 row)

All local artifacts present: `.env`, `.venv/`, Apr 8 DB (11 GB), `scripts/verify_phase3a.py`, `scripts/dryrun_snapshots.py`, `scripts/backfill_claimed_by.py`.

VM state via `ssh vm 'bash scripts/status.sh'`:
- Apr 20 weekly **SUCCESS**, finished 2026-04-23 15:05 UTC. 85.08h runtime (306,302 s). Enrich stage ran 65.9h on 174,939 agents; log reports 174,718 enriched, 221 errors, 0 deleted.
- `scrape_run_id` confirmed populated (MAX=1 on `post_snapshots`) — session-19 fix is on VM.
- Backup retention works: Apr 13 backup pruned at end of Apr 20 run; only `moltbook-weekly-2026-04-20.db` (22 GB) retained.
- Disk: 67 % / 29 GB free on the 80 GB volume (recovered from Apr 21's 80 % / 16 GB free).
- Old full-dump snapshot writer ran at end (2.5M post_snapshots + 4.5M comment_snapshots + etc. inserted) — Phase 3a not pushed, as expected.

## Handover errors discovered

1. **Backup path in §Spot-check block is wrong.** `/mnt/HC_Volume_104999576/backups/` does not exist; real path is `/mnt/HC_Volume_104999576/moltbook_data/backups/`. The `status.sh` and weekly-log prune lines use the correct path; only the handover docs the wrong one.
2. **VM `git log` spot-check is impossible.** VM `~/moltbook_scraper` is not a git working tree (no `.git/`). Code is pushed via `scp -r src/ scripts/ vm:…`, so version verification must be done by reading file contents or hash comparison, not `git log`.
3. **Cosmetic `DB size: 0` in status.sh / weekly-log** — `du` on a symlinked path bug; real DB is 29 GB. Harmless.

## claimed_by reality check — session 22 prediction was wrong

Session 22 predicted "Once this run completes, every re-enriched agent has `claimed_by` populated, so the `OR` branch returns ~0 rows thereafter. Next weekly's pool reverts to the ~7K new agents added during the week."

Actual state after Apr 20 weekly completion:

```
SELECT COUNT(*) FROM agents;                                      -> 176547
SELECT COUNT(*) FROM agents WHERE is_claimed=1;                   -> 174905
SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL;  -> 174904
SELECT COUNT(*) FROM agents WHERE description IS NOT NULL;        -> 169258
```

Only 1 claimed agent has `claimed_by` populated (the single row that the session-18 migration caught). The 174,718 enrich upserts did NOT persist `claimed_by`.

## Root cause — enrich_agents never commits

Diagnostic path:

1. **API probe** (`fetch_agent_profile` on RebelBot / chunfen2026 / msgoogletoggle) confirmed the profile endpoint returns `claimed_by` in snake_case with a UUID value. No normalization bug. `_normalize_agent` is not needed for this endpoint; original comment "the profile endpoint uses snake_case" is accurate.
2. **VM code read** — `src/client.py:fetch_agent_profile` and `src/database.py:upsert_agent` on VM are identical to local. `upsert_agent` SQL correctly binds `agent.get("claimed_by")` and uses `COALESCE(excluded.claimed_by, agents.claimed_by)`.
3. **Isolated write test** — on a fresh scratch DB, seed `(RebelBot, is_claimed=1, claimed_by=NULL)`, then fetch + `upsert_agent(profile)` + `db.conn.commit()`: `claimed_by` is correctly written to the UUID. Write path works when committed.
4. **Last-updated-at distribution on VM** — `MAX(last_updated_at) WHERE is_claimed=1` = `2026-04-20T10:40:37`, i.e. end of the posts stage, *before* enrich even got warm. The 174,718 enrich upserts logged as "success" never updated `last_updated_at`.
5. **Commit audit** — `grep` over `src/scraper.py` for `self.db.commit()`:
   - `scrape_submolts`, `scrape_posts`, `scrape_posts_incremental`, `scrape_moderators`, `scrape_comments`, `create_snapshots` — all commit
   - **`enrich_agents` (lines 293–350) — zero commits**
6. **CLI wrapper** — `cli.py:242` handles `enrich` by calling `scraper.enrich_agents()` with no following commit; `finally: db.close()` at line 280. Python `sqlite3` default `isolation_level=""` means `close()` implicitly rolls back any uncommitted transaction.

Net effect: every weekly's enrich stage is a no-op for the DB. The 169,258 descriptions currently present must have been written by another path (embedded author objects in `scrape_posts` may occasionally carry `description` — to verify later) or by a one-off manual run in session history. For Apr 20 specifically, 65h of enrich API calls produced zero persistent writes.

## Implication for Apr 27 weekly

Without a fix:

- Apr 27 pool again = ~175K (widened predicate keeps matching because `claimed_by` stays NULL).
- ~85h enrich again, still writing nothing to the DB.
- Finishes ≈ Apr 30 15:00 UTC, ~35h before May 1 02:00 UTC monthly. Monthly-overlap risk stays moderate.

With the commit fix pushed before Apr 27:

- Apr 27 enrich pool still ~175K for this one run (widened predicate still matches pre-run).
- This run's upserts persist; `claimed_by` + `description` populated for all 174,718 successful fetches.
- Subsequent weeklies: predicate matches only new stubs + the ~200 transient error agents → ~7K pool, normal runtime.

Fix is a single-file patch (`src/scraper.py:enrich_agents`): add `self.db.commit()` at end of loop and every 100 records (matching progress-log cadence). Roughly 3 lines.

`scripts/backfill_claimed_by.py` is safe independently — it does commit (line 103) per upsert. Not currently scheduled and probably unnecessary if the commit fix lands.

## Tests run this session — all green

### 1. Scratch-DB commit-fix verification (passed)

Applied patch to local `src/scraper.py:enrich_agents` — added `self.db.commit()` every 500 successful upserts and one final commit at end of function. Tested on a fresh scratch DB seeded with 12 real claimed-agent names (`Hazel_OC`, `ummon_core`, `luna_coded`, `stellaentry`, `gribmas_bot`, `denza`, `kendraoc`, `ultrathink`, `PREA`, `AngelaMolty`, `zode`, `Piki`). Ran `Scraper.enrich_agents(only_missing=True)` at `max_workers=4`, then called `db.close()` (which would roll back any uncommitted writes in the default sqlite3 isolation). Re-opened the DB read-only: 12/12 rows had `claimed_by` populated (UUID) AND `description` populated. Commit path works.

### 2. Scoped pytest (passed)

`pytest tests/test_database.py tests/test_snapshot_change_detection.py -v`: **15 passed, 102 warnings**. All warnings are pre-existing `datetime.utcnow()` deprecation noise — not Phase-3a-related. Covered tests include anchor-set-once behaviour, deleted-post content preservation, 4-week post_metrics cutoff, tombstone handling, and moderator event turnover.

### 3. Phase 3a dryrun on local Apr 8 DB (passed)

Copied `data/raw/moltbook.db` → `data/raw/moltbook_phase3a_test.db` (11 GB); ran `scripts/dryrun_snapshots.py --db data/raw/moltbook_phase3a_test.db`.

| Metric | Value | Expected (CLAUDE.md) | Status |
|---|---|---|---|
| Elapsed | 48.9 s | fast | ✓ |
| post_metrics | 22,184 | small fraction of 2.24M (4-week cutoff) | ✓ |
| agent_metrics | 173,949 | ~all agents, one-time first-run | ✓ |
| submolt_metrics | 20,483 | ~all submolts, one-time first-run | ✓ |
| moderator_events | 19,655 | ~19,655 one-time baseline | ✓ exact |
| post_events | 0 | 0 on first run (goes to _first anchor) | ✓ |
| agent_events | 0 | 0 on first run | ✓ |
| DB delta | +169 MB | ~200 MB range; session 21 got +178 MB | ✓ |

Alert thresholds from CLAUDE.md §Snapshot monitoring:
- Alert A (inserted_metrics > 0.5 × entities_scanned): post_metrics 22,184/2,240,473 = 1.0 %. PASS.
- Alert B (inserted_metrics == 0 with ≥1000 entities): none. PASS.
- Alert C (inserted_events > 1000 excluding first-run moderator baseline): all 0. PASS.

Anchor coverage:
- `posts.hot_score_first`: 498,385 / 2,240,473 (22 %). Expected gap — historical posts scraped before `hot_score` was captured. R code should expect `hot_score_first IS NULL` on the long tail.
- `agents.is_claimed_first`: 172,446 / 173,949 (99.1 %). 1,503 agents known only via embedded authors that lack `isClaimed`.
- `submolts.subscriber_count_first`: 20,483 / 20,483 (100 %).

### 4. Code diffs VM vs local (reviewed)

- `src/database.py`: +359 lines. Additive only — 7 new tables (`*_metrics` × 3, `*_events` × 4), 7 new indexes, ~15 new insert/get methods, `set_*_anchors_if_unset` helpers. No existing tables dropped or altered.
- `src/scraper.py`: +78 lines. New per-entity snapshot helpers (`_snapshot_posts`, `_snapshot_agents`, `_snapshot_submolts`, `_snapshot_moderators`) + the `enrich_agents` commit patch applied this session.
- `scripts/weekly_scrape.sh`: +21 lines. Adds `MONTHLY_SENTINEL` check at top (exit 0 with log line if `.monthly_running` present and <7 days old; warn and proceed if stale).
- `scripts/monthly_rescrape.sh`: +5 lines. Writes `.monthly_running` on start, cleans up via `trap EXIT INT TERM`.

Line-endings caveat: local files are CRLF (Windows), VM files are LF. `ssh vm 'dos2unix …'` after push is still required (per CLAUDE.md Quick Commands).

## Artifacts to clean up later

- `data/raw/moltbook_phase3a_test.db` — 11 GB copy used for dryrun. Safe to delete once push is done; pending user direction to remove.

## Readiness for Phase 3a + commit-fix push to VM

All gates passed:
- Commit fix works under close() rollback conditions.
- Existing test suite unbroken.
- Phase 3a writer behaves exactly per design spec on a realistic 11 GB DB.
- Diffs show additive-only schema changes; no surprise deletions.

Bundle-and-push is now low-risk. Waiting for user go-ahead before `scp`-ing to VM.

## Files written this session

- `CLAUDE/session_logs/2026_04_24_session_log.md` — this file.
- `claude_handover.md` — rewritten to incorporate the commit-bug finding and revised next-actions.
- `data/README.md` — updated to reflect Phase 3 layered architecture (live + `*_metrics` + `*_events` + legacy `*_snapshots`). No schema changes yet.

No changes to `CLAUDE.md`, `claude_methodology_log.md`, or `claude_learnings.md` yet — pending end-of-session review.

## Rollback

All writes this session are documentation only. `git checkout -- <path>` reverts before the next commit.

## Open questions to resolve before Apr 27 02:00 UTC

1. Apply the `enrich_agents` commit fix on local, test it, scp to VM?
2. Bundle with Phase 3a push or ship separately? (Bundled = one VM touch; separate = smaller blast radius if something breaks.)
3. Keep the widened predicate or revert it? With the commit fix, keeping it causes ONE more ~85h run Apr 27 that actually persists — after which the predicate self-clears. Reverting means Apr 27 is a normal ~7h run but `claimed_by` stays mostly NULL and needs `scripts/backfill_claimed_by.py` invoked manually (also ~48–85h at 60/min rate limit) to fill.

## Resolution (same session, post-pause)

User chose Option A (keep widened predicate, one marathon Apr 27 run with committed writes) plus bundled push.

### Push to VM — 2026-04-24 afternoon

1. **Backup archive.** `scp` of the four current VM files into local `tmp/vm_backup_pre_23/` (rollback insurance).
2. **Push.** `scp` of patched `src/scraper.py`, `src/database.py`, `scripts/weekly_scrape.sh`, `scripts/monthly_rescrape.sh` to VM.
3. **Line endings.** `ssh vm 'dos2unix …'` on all four (CRLF → LF).
4. **WAL flip.** `ssh vm 'sqlite3 …moltbook.db "PRAGMA journal_mode=WAL;"'` — confirmed `wal` (was `delete`). Persistent; all subsequent connections inherit it.
5. **Cron update.** Monthly moved from `0 2 1 * *` to `55 1 1 * *`; header comment updated accordingly.

### Verification (all green)

- `grep self.db.commit src/scraper.py` — commits present in `enrich_agents` at lines 326, 349, 353 (every-500 in sequential path, every-500 in concurrent path, final).
- `grep journal_mode src/database.py` — `PRAGMA journal_mode=WAL;` in `Database.__init__`.
- `grep MONTHLY_SENTINEL scripts/weekly_scrape.sh` — check block at line 84.
- `grep "trap" scripts/monthly_rescrape.sh` — `trap cleanup EXIT INT TERM` at line 104.
- `.venv/bin/python -c "from src.database import Database; from src.scraper import Scraper; from src.client import MoltbookClient"` — imports clean.
- `bash scripts/status.sh` — runs, shows new cron schedule, no active scrape, no anomalies. (Cosmetic `DB size: 0` persists — pre-existing `du`-on-symlink issue.)

### Post-push doc sync

- `CLAUDE.md`: monthly cron line updated to `55 1 1 * *`.
- `claude_handover.md`: frozen state rewritten for post-push reality; Next Actions collapsed to Apr 27 post-run checkpoint + Phase 4 + deferred; return-after-delay table revised for the common-case timeline.

### Net status

Phase 3a writer, WAL mode, `.monthly_running` sentinel, deletion-content guard, and `enrich_agents` commit fix are ALL live on VM as of 2026-04-24 ~17:45 UTC. Apr 27 02:00 UTC weekly is the first run that exercises all of them together. Expected outcome: ~85 h marathon with 174,718 actually-persisted enrich upserts; `claimed_by` populated for ~174,905 claimed agents; first snapshot run emits ~19,655 moderator-baseline events and 0 post/agent/submolt events.
