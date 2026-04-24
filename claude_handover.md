# Claude Handover — Moltbook Scraper

**Last updated**: 2026-04-24, session 23 (post-push).

## ⚠️ Before trusting anything below: spot-check the VM

This handover freezes a view of the world on **2026-04-24 after the Phase 3a + commit-fix push**. Crons fire autonomously; state changes without me editing this file. If today is later than Apr 24, run the block below first and compare against §Current-state.

```bash
date -u                                                                         # today's UTC date
ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'                              # last scrape completion
ssh vm 'ls -lht /mnt/HC_Volume_104999576/moltbook_data/backups/ | head -5'      # backups
ssh vm 'ls -1 ~/moltbook_scraper/logs/weekly-*.log | tail -3'
ssh vm 'ls -1 ~/moltbook_scraper/logs/monthly-*.log | tail -3'
ssh vm 'df -h /mnt/HC_Volume_104999576'
ssh vm 'sqlite3 ~/moltbook_scraper/data/raw/moltbook.db "PRAGMA journal_mode;"' # expect: wal
ssh vm 'crontab -l | grep -E "weekly|monthly"'                                   # monthly should be 55 1 1 * *
```

`~/moltbook_scraper` on the VM is not a git checkout — code ships via `scp`. Verify push state by reading file contents.

## Current state (frozen 2026-04-24, after push)

- **Apr 20 weekly completed** 2026-04-23 15:05 UTC (85.08h). Exit SUCCESS, 174,718 "enriched" log line — but those writes were ROLLED BACK (see §Enrich-never-committed-bug). Only 1 of 174,905 claimed agents has `claimed_by` populated pre-Apr-27.
- **Apr 13 backup pruned cleanly** at end of Apr 20 run; only `moltbook-weekly-2026-04-20.db` (22 GB) retained at `/mnt/HC_Volume_104999576/moltbook_data/backups/`.
- **Disk**: 67 % / 29 GB free on 80 GB volume.
- **Phase 3a + commit patch PUSHED TO VM on 2026-04-24** (this session). Bundle: `src/scraper.py`, `src/database.py`, `scripts/weekly_scrape.sh`, `scripts/monthly_rescrape.sh`. `dos2unix` applied. Monthly cron moved to `55 1 1 * *`. `PRAGMA journal_mode=wal` now active on VM DB. Rollback copies: `tmp/vm_backup_pre_23/`.
- **Verification passed**: commits present in `enrich_agents` at lines 326/349/353; `PRAGMA journal_mode=WAL` in `Database.__init__`; `MONTHLY_SENTINEL` check in weekly; trap+sentinel in monthly; `.venv/bin/python` imports clean.
- **Git**: `main`, HEAD = `fec38e5`. Unpushed commits since `86d543d`: `311b0d1` (commit fix), `70d1db7` (docs), `3a94acf` (README prune), `fec38e5` (learnings + methodology). Working tree clean except for `CLAUDE.md` (monthly cron line edit, pending commit).

## Enrich-never-committed bug (discovered session 23)

`src/scraper.py:enrich_agents` (lines 293–350) has **no `self.db.commit()` calls anywhere**. All 174,718 upserts from Apr 20's enrich stage sat in an uncommitted transaction and were rolled back by `cli.py:280 → db.close()` (Python sqlite3 default isolation_level rollbacks on close).

Evidence:

- `SELECT MAX(last_updated_at) FROM agents WHERE is_claimed=1` = `2026-04-20T10:40:37` — end of posts stage, not end of enrich (Apr 23 12:23).
- `SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL` = `174904` of `174905` claimed agents. Only 1 row was ever populated.
- Scratch-DB test confirmed `upsert_agent(profile)` + explicit `commit()` DOES write `claimed_by` correctly (UUID, snake_case, returned by the profile endpoint as documented).

Every other stage (submolts / posts / comments / moderators / snapshots) commits. `enrich_agents` is the sole outlier.

→ `CLAUDE/session_logs/2026_04_24_session_log.md` for full diagnostic trace.

## Next actions (in order)

### 1. Apr 27 weekly post-run checkpoint

First weekly after the Phase 3a + commit push. Expected: ~85 h again on this one run because widened predicate still matches the 175K backlog pre-run. After run completes (ETA Apr 30 ~15:00 UTC):

- `SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL;` should drop to ~200 (leftover transient errors). If >2K still NULL, investigate before next weekly.
- `tail logs/scrape-snapshots.log` should emit R1-format lines (`inserted_metrics`, `inserted_events`, `entities_scanned`). Expected one-time baseline on the FIRST snapshot run: ~19,655 `moderator_events`; 0 for post/agent/submolt events.
- DB delta: ~200–400 MB (dryrun on 11 GB Apr 8 copy was +178 MB; full DB is 11 GB → proportionally ~400 MB). Legacy `*_snapshots` tables may still grow because they live alongside the new narrow writer until Phase 4 archives them.
- Subsequent weeklies (May 4 onward): predicate should self-clear to the ~7K new-stub pool, ~6–10 h runtime.

### 2. Phase 4 — compress existing 15 GB of legacy snapshots (USER-SUPERVISED)

Mid-week only (not near Monday). Halt cron for several hours. Parquet backup of `*_snapshots` first (disk < 85 %). Originals renamed to `*_snapshots_v1_archive`; compatibility VIEWs bridge existing R code until R is migrated.

→ Full sub-steps: `2026_04_20_session_log.md` §Phase-4.

### 3. Deferred

- **Monthly sharding** (A-H / I-P / Q-Z by submolt first letter): after Phase 4 stable for 1 weekly cycle.
- **Decommission `*_v1_archive` + compat VIEWs**: once R analysis code is migrated to read narrow tables directly.
- **Audit other scrape functions for missing-commit risk** — enrich_agents was the outlier but deserves a second pass.

## Known risks

- **Weekly-vs-monthly overlap**. Apr 27 weekly ~85 h → finishes ≈ Apr 30 15:00 UTC, ~35 h before May 1 01:55 UTC monthly. With `.monthly_running` sentinel now on VM, a weekly still running at May 1 would be skipped cleanly by the next weekly's sentinel check; but the Apr 27 weekly itself could still *overrun into* May 1 if enrich is slower than expected. WAL mitigates concurrent-access corruption risk.
- **Pytest hang.** `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.
- **Legacy snapshot writer still running**. Until Phase 4 drops the `*_snapshots` tables, every weekly still appends a full-dump layer (observed ~5–6 GB in session 22). Disk will creep up week-over-week; monitor via `df -h /mnt/HC_Volume_104999576`.

## Return-after-delay interpretation

Use this table when returning after a gap. Match against the spot-check output at the top of this file. "X" = cron has already fired since Apr 24.

| Return date | What happened since Apr 24 | Read this | Then do |
|---|---|---|---|
| **Apr 25–26** | No cron yet | status.sh (sanity: `claimed_by NOT NULL` should still be ~1 pre-Apr-27) | Nothing operational. Work on Phase 4 prep if desired. |
| **Apr 27–30** | Apr 27 weekly **X** mid-run | `ls -lh logs/weekly-2026-04-27*.log`; active-scrape line in status.sh | Let it finish — ~85 h, ETA Apr 30 ~15:00 UTC. Do NOT scp code during an active run. |
| **Apr 30 – May 1** | Apr 27 weekly done | `grep SUCCESS logs/weekly-2026-04-27.log`; `SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL;` | Run §Next-actions-1 checkpoint. Expected NULL count ≈ 200. If > 2K, debug before May 4. |
| **May 1 afternoon onward** | May 1 monthly **X** fired at 01:55 UTC | `tail -50 logs/monthly-2026-05-01.log`; `df -h /mnt/HC_Volume_104999576` | Confirm monthly ran / is running without DB-lock errors. Disk usage < 85 %. |
| **May 4 onward** | May 4 weekly **X** fired | Weekly log; snapshot stage timing | Expected: enrich pool ~7 K, runtime ~6–10 h (predicate self-cleared). If still ~85 h, `claimed_by` is still NULL → commit fix silently broken on VM, investigate. |
| **Late May / June** | Multiple cycles | Disk trend | Phase 4 (legacy snapshot compression) should have been done by now. If disk > 85 %, halt cron until Phase 4 completes. |

## Resuming after absence

1. Run the §spot-check block at top.
2. Match output against §Return-after-delay-interpretation.
3. Read latest file in `CLAUDE/session_logs/`.
4. Resume from the earliest incomplete action that is still applicable.

## Work laptop

SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
