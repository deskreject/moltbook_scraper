# Claude Handover — Moltbook Scraper

**Last updated**: 2026-04-24, session 23.

## ⚠️ Before trusting anything below: spot-check the VM

This handover freezes a view of the world on **2026-04-24**. Crons fire autonomously; the state changes without me editing this file. If today is later than Apr 24, run the block below first and compare against §Current-state. **Do not skip this even if the "Last updated" date looks recent** — the user may have been away.

```bash
date -u                                                                         # today's UTC date
ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'                              # last scrape completion
ssh vm 'ls -lht /mnt/HC_Volume_104999576/moltbook_data/backups/ | head -5'      # backups (correct path)
ssh vm 'ls -1 ~/moltbook_scraper/logs/weekly-*.log | tail -3'                   # recent weekly log filenames
ssh vm 'ls -1 ~/moltbook_scraper/logs/monthly-*.log | tail -3'
ssh vm 'df -h /mnt/HC_Volume_104999576'
ssh vm 'grep -n "self.db.commit" ~/moltbook_scraper/src/scraper.py | head -20'  # is enrich_agents commit patch on VM?
```

Don't try `git log` on the VM — `~/moltbook_scraper` is not a git checkout. Code ships via `scp`. Verify push state by reading file contents.

## Current state (frozen 2026-04-24)

- **Apr 20 weekly completed** 2026-04-23 15:05 UTC (85.08h). Exit SUCCESS, 0-error on the SUCCESS line. Enrich stage logged 174,718 "enriched", BUT SEE §Enrich-never-committed-bug.
- **Apr 13 backup pruned cleanly** at end of Apr 20 run; only `moltbook-weekly-2026-04-20.db` (22 GB) retained at `/mnt/HC_Volume_104999576/moltbook_data/backups/` (the correct path; handover previously docs a wrong one).
- **Disk**: 67 % / 29 GB free on 80 GB volume. Safe headroom.
- **`scrape_run_id` fix confirmed** — MAX=1 on `post_snapshots`. Session-19 write path is on VM.
- **Phase 3a** (narrow snapshots, WAL, `.monthly_running`, deletion guard) committed locally as `86d543d`, **not pushed to VM**. Old full-dump snapshot writer ran at end of Apr 20 weekly.
- **Git**: `main`, uncommitted doc edits from sessions 22–23 (`claude_handover.md`, `claude_archive.md`, `claude_learnings.md`, `data/README.md`) + untracked session logs. HEAD = `86d543d`.

## Enrich-never-committed bug (discovered session 23)

`src/scraper.py:enrich_agents` (lines 293–350) has **no `self.db.commit()` calls anywhere**. All 174,718 upserts from Apr 20's enrich stage sat in an uncommitted transaction and were rolled back by `cli.py:280 → db.close()` (Python sqlite3 default isolation_level rollbacks on close).

Evidence:

- `SELECT MAX(last_updated_at) FROM agents WHERE is_claimed=1` = `2026-04-20T10:40:37` — end of posts stage, not end of enrich (Apr 23 12:23).
- `SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL` = `174904` of `174905` claimed agents. Only 1 row was ever populated.
- Scratch-DB test confirmed `upsert_agent(profile)` + explicit `commit()` DOES write `claimed_by` correctly (UUID, snake_case, returned by the profile endpoint as documented).

Every other stage (submolts / posts / comments / moderators / snapshots) commits. `enrich_agents` is the sole outlier.

→ `CLAUDE/session_logs/2026_04_24_session_log.md` for full diagnostic trace.

## Next actions (in order)

### 1. Patch `enrich_agents` to commit (BEFORE Apr 27 02:00 UTC)

Add `self.db.commit()` at end of the loop AND every 100 records (matching the existing progress-log cadence) in `src/scraper.py:enrich_agents`. Target: ~3-line change.

Test plan:
- Seed scratch DB with 10 claimed agents having `claimed_by IS NULL`.
- Run `enrich_agents(only_missing=True)` via the CLI or direct call.
- Verify all 10 have `claimed_by` populated and `description` set after the run.
- Run scoped pytest: `pytest tests/test_database.py tests/test_snapshot_change_detection.py` (do NOT run bare `pytest` — `test_fetch_all_posts_paginates_until_no_more` hangs, orphans ~50 GB RAM).

### 2. Push Phase 3a + commit patch to VM (BEFORE Apr 27 02:00 UTC)

Bundled push (one VM touch) is lower operational cost than separate. Files: `src/database.py`, `src/scraper.py` (patched), `scripts/weekly_scrape.sh`, `scripts/monthly_rescrape.sh`. Update monthly cron to `55 1 1 * *`.

Pre-push: `scp` old copies of the four VM files to `~/tmp/vm_backup_pre_23/` as a local rollback archive.

Post-push verification:
- `PRAGMA journal_mode` on VM DB = `wal`.
- Grep `self.db.commit` on VM `src/scraper.py` shows commits inside `enrich_agents`.
- First weekly after push: `logs/scrape-snapshots.log` emits R1-format lines (`inserted_metrics`, `inserted_events`, `entities_scanned`).
- Expected one-time baseline: ~19,655 moderator events on first post-migration snapshot run; 0 for post/agent/submolt events.
- DB delta: ~200–400 MB (dryrun on 11 GB Apr 8 copy was +178 MB).

### 3. Apr 27 weekly post-run checkpoint

If the commit fix + Phase 3a are on VM before Apr 27 02:00 UTC:

- Apr 27 enrich pool = ~175K (widened predicate still matches pre-run), ~85h runtime again for this one marathon.
- After run, verify:
  - `SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL;` → should drop to ~200 (leftover transient errors).
  - If >2K still NULL, don't wait; revert predicate now (one-line: drop the `OR (is_claimed=1 AND claimed_by IS NULL)` branch from `get_unenriched_agent_names` in `src/database.py`) and invoke `scripts/backfill_claimed_by.py` for the residue.
- Subsequent weeklies should revert to ~7K incremental pool (~6–10h).

### 4. Phase 4 — compress existing 15 GB of legacy snapshots (USER-SUPERVISED)

Mid-week only (not near Monday). Halt cron for several hours. Parquet backup of `*_snapshots` first (disk < 85%). Originals renamed to `*_snapshots_v1_archive`; compatibility VIEWs bridge existing R code until R is migrated.

→ Full sub-steps: `2026_04_20_session_log.md` §Phase-4.

### 5. Deferred

- **Monthly sharding** (A-H / I-P / Q-Z by submolt first letter): after Phase 4 stable for 1 weekly cycle.
- **Decommission `*_v1_archive` + compat VIEWs**: once R analysis code is migrated to read narrow tables directly.
- **Audit other scrape functions for missing-commit risk** — enrich_agents was the outlier but deserves a second pass.

## Minimum viable if time is tight before Apr 27

Priority order if you can only do some of the above:

1. **Commit fix on VM only** (scp patched `src/scraper.py`). Without this, Apr 27 enrich is another 65h of wasted API calls and `claimed_by` stays NULL forever.
2. **Predicate revert on VM** (one-line change to `src/database.py`) as a fallback if you can't verify the commit fix in time. This shortens Apr 27 to ~7h but leaves `claimed_by` unfilled.
3. Phase 3a can wait one week if necessary. Without it, Apr 27 adds one more full-dump snapshot layer (~500 MB) — survivable. By May 4 it MUST be on VM.

Do not skip both (1) and (2). One of them must land.

## Known risks

- **Weekly-vs-monthly overlap**. Apr 27 weekly + commit fix = ~85h → finishes ≈ Apr 30 15:00 UTC, ~35h before May 1 02:00 UTC monthly. If enrich runs slower this week (more rate-limit hits, more new agents), margin shrinks. Without Phase 3a's `.monthly_running` lock on VM, a weekly still running at May 1 02:00 UTC would run concurrently with monthly — SQLite serializes at DB level so no corruption, but one process will fail. Phase 3a + WAL eliminates this risk.
- **Pytest hang.** `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.
- **Commit-cadence choice**. Commit every 100 records vs commit at end: every-100 gives crash-resilience but adds 1.7K fsync calls over a 175K-agent run. Every-end is faster but loses everything on SIGTERM mid-run. Recommendation: commit every 500 + at end (350 fsync calls, <60s of work lost on crash).

## Return-after-delay interpretation

Use this table when returning after a gap. Match against the spot-check output at the top of this file. "X" = cron has already fired since Apr 24.

| Return date | What happened since Apr 24 | Read this | Then do |
|---|---|---|---|
| **Apr 25–26** | No cron yet | status.sh; verify Phase 3a + commit patch status on VM (`grep self.db.commit src/scraper.py`) | Proceed to §Next-actions-1 and 2 if not done. |
| **Apr 27 afternoon onward** | Apr 27 weekly **X** has fired | `ls logs/weekly-2026-04-27*.log`; on VM, grep for commit in `src/scraper.py`, check `claimed_by` count | **If patch was pushed pre-Apr-27:** Apr 27 ran ~85h with commits. Run post-run checkpoint (§Next-actions-3). **If patch NOT pushed:** Apr 27 was another no-op enrich. Push patch NOW so May 4 weekly is effective. |
| **May 1 afternoon onward** | Apr 27 weekly **X**, May 1 monthly **X** | `tail -50 logs/monthly-2026-05-01.log`; `df -h` | Monthly = comments rescrape + deletion detection, not snapshot stage. Check for weekly-vs-monthly overlap symptoms (failed stage, locked-DB errors). Verify disk isn't >85%. |
| **May 4 onward** | Apr 27 weekly **X**, May 1 monthly **X**, May 4 weekly **X** | Snapshot table sizes; `claimed_by NOT NULL` count | **Critical:** if `claimed_by NOT NULL` count is still ~1, the commit fix is NOT on VM — every weekly since Apr 27 was a no-op enrich. Push commit fix NOW. Also urgent: Phase 3a, or snapshot tables continue ballooning. |
| **Late May / June** | Multiple weeklies + monthlies | Disk 90%+ likely | Hard stop cron: `ssh vm 'crontab -r'`. Assess backup integrity, then commit fix + Phase 3a + Phase 4 back-to-back. |

## Resuming after absence

1. Run the §spot-check block at top.
2. Match output against §Return-after-delay-interpretation.
3. Read latest file in `CLAUDE/session_logs/`.
4. Resume from the earliest incomplete action that is still applicable.

## Work laptop

SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
