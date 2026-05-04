# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-04, session 25.

> Provenance: claims tagged `[verified]` were checked against current state in this session; `[planned]` is agreed direction without implementation. Re-tag rather than copy-forward.

---

## Current state

[verified 2026-05-04]

- **Phase 4 complete (2026-05-03, session 25).** Live DB shrunk 29 GB → **6.2 GB** after dropping 5 legacy `*_snapshots` tables. ~30.75 M rows preserved as compressed cold-storage dump on local at `data/archive/legacy_snapshots_2026-04-27.sql.gz` (6.2 GB, SHA256 `720c3994ea60603dae19342b37d7c0c2a576e5ceefcd9f90c4f2daa3625ed817`). `snapshot_mutability_evidence` (audit summary, 30 rows) preserved.
- **May 4 weekly is currently running.** Cron fired 02:00 UTC; comments stage in progress at session-end (~6 h in). First weekly under the new normal — small enrich pool (predicted 7,537 agents) and incremental snapshot writer (no first-run baseline). Expected runtime ~16 h, ETA SUCCESS ~2026-05-04 ~18:00 UTC.
- **Phase 3a writer empirically verified.** post_metrics 334,421 = posts ≤ 28 d (Δ=39 vs direct count); agent_metrics 177,058 = all agents; submolt_metrics 20,840; moderator_events 20,010 (one-time baseline); post/agent/submolt_events 0 (anchor design works).
- **`claimed_by` backfill complete.** 240 / 175,311 = 0.14 % NULL — within ≤ 2 K acceptable threshold; the 240 ≈ the 238 transient enrich errors.
- **Volume: 60 GB free (37 % used)** as of session-25 end. Will jump to ~83 GB once May 4 weekly prunes the Apr 27 backup (still 29 GB, pre-Phase-4 era). Steady-state from there: ~21 GB used / ~78 GB free.
- **Cron**: weekly Mon 02:00, monthly Tue 01:55 (with first-Tuesday-of-month guard inside script), disk monitor 08:00 — all confirmed in place.
- **Local repo**: `main`, working tree has session-25 documentation edits uncommitted (8 files); plus pre-existing 5 commits ahead of origin from sessions 23 + 24.

## Spot-check on return

```bash
date -u
ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'
ssh vm 'ls -1t ~/moltbook_scraper/logs/weekly-*.log | head -3'
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'df -h /mnt/HC_Volume_104999576'
ssh vm 'crontab -l | grep -E "weekly|monthly"'
```

Match against:
- DB file should be ~6–7 GB (post-Phase-4). If 29 GB, something is very wrong.
- Volume free should be ≥ 60 GB; ~83 GB after May 4 weekly completes its prune.
- Backups dir post-May-4-weekly: `moltbook-weekly-2026-05-04.db` (~6–7 GB), Apr 27 backup pruned. If both still present, the prune step failed.
- Crontab monthly = `55 1 * * 2`. Weekly = `0 2 * * 1`.
- status.sh "DB size: 0" is a known cosmetic bug (du-on-symlink); ignore.
- status.sh "N errors" line is a known cosmetic bug (`grep -c "error"` matches `0 errors)` in progress lines); diagnose only via `grep -cE "Exception|Traceback|ENOSPC|OperationalError"`.

---

## Next actions (state-conditional)

### If May 4 weekly is still running

Nothing operational. Wait. Re-run spot-check on next visit.

### If May 4 weekly has completed (SUCCESS)

This is the first weekly under the new steady-state, so it deserves a one-time post-mortem to confirm forecasts:

1. **Enrich runtime**: should be ~10–16 h total (was 81.5 h on Apr 27). `grep "DONE: enrich" logs/weekly-2026-05-04.log` and confirm the elapsed.
2. **Enrich pool size**: was 175 K backfill on Apr 27. Confirm pool was ~7,537 (matches the Sun May 3 prediction). `grep -E "Found .* unenriched" logs/scrape-enrich.log`.
3. **`claimed_by` gate**: should still be ~240–500 (some normal turnover from new-agent stubs that fail enrich). `sqlite3 .. "SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL"`.
4. **Snapshot stage growth**: should be MUCH smaller than Apr 27 baseline. `tail logs/scrape-snapshots.log` and check the R1 monitoring lines:
   - `post_metrics inserted_metrics`: expect ≤ 5 K (only entities whose vote/comment counts moved). Apr 27 was 334 K (first-run, every eligible post).
   - `agent_metrics inserted_metrics`: expect ≤ 10 K. Apr 27 was 177 K.
   - `submolt_metrics inserted_metrics`: expect ≤ 1 K. Apr 27 was 21 K.
   - `moderator_events inserted_events`: expect ≤ 50 (only role/membership flips). Apr 27 was 20 K (baseline).
   - `post/agent/submolt_events inserted_events`: expect single-digits to low-hundreds (only state flips).
5. **Backup prune**: confirm `moltbook-weekly-2026-04-27.db` is gone and only `moltbook-weekly-2026-05-04.db` (~6–7 GB) remains.
6. **Disk**: `df -h` should show ~83 GB free.

If all of those pass, update this handover to `[verified]` for the new steady state and move on.

### If May 4 weekly FAILED

Read `tail -200 logs/weekly-2026-05-04.log`. Likely culprits given the change set:
- `enrich_agents` commit logic regression (now-known-good code, but worth a sanity check)
- snapshot stage error if the writer hits unexpected data (e.g. NULL anchors that should never be NULL)
- ENOSPC: should not happen with 60 GB free; if it does, something else is wrong

---

## May 5 monthly — first attempt under rescheduled cron

[planned for 2026-05-05]

Monthly cron now `55 1 * * 2`; first-Tuesday guard inside script. **Tue May 5 is the first Tuesday of May → monthly fires.** It runs *after* whatever happens with the May 4 weekly.

Two things to verify when convenient after May 5:
1. `monthly-2026-05-05.log` exists and progresses past the "Backing up database" line — that's where Apr 1 monthly silently died (no monthly run has ever completed in project history; see Known issues).
2. If it completes: takes ~5–7 days; `monthly-post-2026-05-05.db` backup created; Mondays during the run skip cleanly via `.monthly_running` sentinel.

Schedule a follow-up agent for ~2026-05-12 to verify completion (or diagnose silent death if it recurs).

---

## Known issues / open threads

### Apr 1 monthly silent-death — recurrence test pending

[verified 2026-04-27] `monthly-2026-04-01.log` is 4 lines and stops at "Backing up database (pre-scrape)...". No SUCCESS, no FAILED. As far as evidence on disk, no monthly run has ever completed. Likely OOM during `sqlite3 .backup` on the at-the-time 22 GB live DB on the cramped root disk. With Phase 4's 6.2 GB DB and 60 GB free volume, this should not recur — but the May 5 monthly is the actual test.

If May 5 also dies silently: `~/moltbook_scraper/logs/cron.log` around 2026-05-05, `dmesg | grep -i kill`, `/var/log/syslog`.

### Pytest hang

[verified 2026-04-21] `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.

### Sharding by submolt first-letter

[planned, not implemented] Methodology log entry from 2026-04-20. Re-evaluate after first successful post-Phase-4 monthly to see if the un-sharded run still fits inside the 7-day window with the smaller live DB.

### status.sh cosmetic bugs

Two pre-existing display bugs surface every session-startup:
- `DB size: 0` — `du` on a symlinked path. Real size from `ls -lh`.
- `N errors` — `grep -c "error"` matches `"0 errors)"` in progress lines. Real error count from `grep -cE "Exception|Traceback|ENOSPC|OperationalError"`.

Both are 2–5 line fixes to `scripts/status.sh`. Low priority but worth doing — they cost cognitive overhead every session.

---

## Resuming after absence

1. Run §Spot-check above.
2. Decide which of the May 4 weekly state branches applies; act accordingly.
3. If returning after 2026-05-12 and no monthly post-mortem exists: check May 5 monthly status (see "May 5 monthly" section above).
4. Read `CLAUDE/session_logs/2026_05_03_session_log.md` for the full Phase 4 execution trace.

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
