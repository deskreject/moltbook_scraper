# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-04-27, session 24.

> **Provenance convention.** Each claim below is tagged:
> - `[verified]` — checked against current code or VM state in the most recent session
> - `[design]` — describes intent, not yet confirmed against runtime
> - `[planned]` — agreed direction, no implementation yet
>
> When updating this file: re-verify or re-tag every claim. Do not copy a `[verified]` tag from a prior version without re-checking.

---

## Orientation: where things stand

[verified 2026-04-27]

- **Apr 27 weekly is currently running.** PID 920465, started 02:00 UTC, comments stage in progress (~80% through at session start). ETA SUCCESS: ~Apr 30 ~15:00 UTC, ~85 h total because the widened enrich predicate matched the full ~175K backlog from the never-committed Apr 20 enrich. **This is the last 80h+ weekly.** Subsequent weeklies revert to ~16h.
- **Phase 3a is fully deployed.** `src/scraper.py:create_snapshots()` writes only to narrow `*_metrics` / `*_events` tables. **There is no longer a "legacy writer running alongside"** — that statement in the prior handover was a misread of design intent vs. shipped code. The `*_snapshots` tables (11.2M post + 18.5M comment + 866K agent + 100K submolt + 92K moderator rows) stopped growing at the Apr 20 weekly snapshot stage (last write 2026-04-23 12:23 UTC).
- **Volume expanded 80 → 100 GB on 2026-04-27.** `resize2fs` applied online during the running scrape; no impact. Currently 84 % used / 16 GB free during the run.
- **Backup retention rewritten** (this session): pre-monthly backup dropped; only `latest weekly` + `latest monthly-post` retained.
- **Monthly cron rescheduled** (this session): now first Tuesday of month (`55 1 * * 2` + day ≤ 7 guard). May 2026 monthly will fire May 5, after May 4 weekly.
- **Local repo**: `main`, working tree clean except for this session's edits. 5 commits ahead of origin from session 23 (`311b0d1` → `40b47e9`); push when convenient.
- **VM `~/moltbook_scraper`** is not a git checkout — code ships via `scp` + `dos2unix`. Verify push state by reading file contents, not `git log`.

## Spot-check on return

Run this before trusting anything below; output tells you which Block applies.

```bash
date -u
ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'
ssh vm 'ls -1 ~/moltbook_scraper/logs/weekly-*.log | tail -3'
ssh vm 'ls -1 ~/moltbook_scraper/logs/monthly-*.log | tail -3'
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'df -h /mnt/HC_Volume_104999576'
ssh vm 'crontab -l | grep -E "weekly|monthly"'
```

**Match against**:
- `df` should show **100 GB** total (post-resize). If 80 GB, the resize was rolled back somehow — investigate.
- Crontab monthly line should be `55 1 * * 2 ...`. If still `55 1 1 * * ...`, the cron update didn't get applied — see Block C.
- Backup directory should contain at most: 1× `moltbook-weekly-*.db` and 1× `moltbook-monthly-post-*.db`. **There should be NO `moltbook-monthly-pre-*.db`** under the new policy.
- `weekly-2026-04-27.log` exists. Check for `SUCCESS` or `FAILED` to know which Block applies.

---

## Block A — Verify Apr 27 weekly outcome

**Precondition**: `grep -q SUCCESS ~/moltbook_scraper/logs/weekly-2026-04-27.log` returns a match (i.e., the weekly has finished). If still running or no SUCCESS marker, do not proceed.

This is the first weekly that exercises the Apr 24 push (Phase 3a writer + enrich commit fix + WAL + sentinel) end-to-end on production data. We need to confirm it actually did what it was supposed to before doing Phase 4.

### A.1 Enrich commit fix landed

```bash
ssh vm 'sqlite3 ~/moltbook_scraper/data/raw/moltbook.db "
  SELECT COUNT(*) FROM agents WHERE is_claimed=1 AND claimed_by IS NULL
"'
```

- **Expected**: ≤ 200 (residual transient errors)
- **Acceptable**: ≤ 2,000
- **Investigate**: > 2,000 (commit fix may not have applied as expected; do not run Phase 4 until resolved)

### A.2 Phase 3a narrow writer fired correctly

```bash
ssh vm 'for t in post_metrics agent_metrics submolt_metrics moderator_events post_events agent_events submolt_events; do
  echo "$t: $(sqlite3 ~/moltbook_scraper/data/raw/moltbook.db "SELECT COUNT(*) FROM $t")"
done'
```

- **Expected** (one-time first-run baseline, per dryrun on Apr 8 11 GB DB):
  - `post_metrics`: ~22,000 (only posts ≤ 4 weeks old)
  - `agent_metrics`: ~175,000 (one-time first-run for all agents)
  - `submolt_metrics`: ~20,000 (one-time first-run for all submolts)
  - `moderator_events`: ~19,655 (one-time baseline "added")
  - `post_events`, `agent_events`, `submolt_events`: 0 (initial state captured in `*_first` anchors, not events)
- **Investigate**: any value off by >2× from expected. Cross-check `tail logs/scrape-snapshots.log` for R1 monitoring lines (`entities_scanned=N, inserted_metrics=M, inserted_events=E`).

### A.3 Legacy `*_snapshots` did not grow

```bash
ssh vm 'sqlite3 ~/moltbook_scraper/data/raw/moltbook.db "
  SELECT MAX(scrape_run_id) FROM post_snapshots;
  SELECT MAX(scrape_run_id) FROM comment_snapshots;
"'
```

- **Expected**: both = 1 (the Apr 20 weekly's `scrape_run_id`). Apr 27 weekly should not have written any rows.
- **Investigate**: max = 2 → `create_snapshots()` somehow still writing legacy rows. Means the deployed code differs from local. Re-read VM `src/scraper.py:_snapshot_*` functions.

If A.1, A.2, A.3 all pass: proceed to Block B.

---

## Block B — Phase 4: reclaim ~30 GB from legacy `*_snapshots`

**Precondition**: Block A passed AND no scrape currently running (`ps -ef | grep -v grep | grep -E "weekly_scrape|monthly_rescrape"` returns nothing).

**Goal**: shrink live DB from ~29 GB to ~14 GB by removing the 30 M historical legacy snapshot rows. New code does not write to these tables; they are pure historical residue.

### Decision needed before executing

Three sub-options, decide first:

1. **Drop entirely** — easiest. Loses 30 GB of historical snapshot data. Justification: the Phase 2 mutability audit (`tables/snapshot_mutability_audit_2026-04-14.csv`) found 0.0000 % change on post/comment snapshots → repeated rows of the same content. agent/submolt/moderator snapshots have some signal but limited.
2. **Offload, then drop** — `sqlite3 .dump > legacy_snapshots_v1.sql.gz`, scp to local or storage box, drop tables in DB. Preserves data off-volume.
3. **Selective**: drop only `post_snapshots` and `comment_snapshots` (the ones with 0.0000 % change). Keep agent/submolt/moderator snapshots in the DB.

[planned] Default recommendation if user has no preference: option 3 (selective drop). Saves ~25 GB while preserving the agent/submolt/moderator history that has actual signal.

### Execution outline (assuming option 3)

Do NOT execute until decision confirmed and scrape is idle. Sketch only:

1. Disable cron temporarily: `ssh vm 'crontab -l > /tmp/cron.bak; crontab -r'`
2. Acquire DB lock: just verify no scrape running via PID check
3. `BEGIN; DROP TABLE post_snapshots; DROP TABLE comment_snapshots; COMMIT;`
4. `VACUUM` (may take several hours on a 29 GB DB; runs offline)
5. Verify: `du -h moltbook.db` should now show ~14 GB
6. Re-enable cron: `ssh vm 'crontab /tmp/cron.bak'`
7. Update `claude_methodology_log.md` with the actual date, sub-option chosen, and resulting DB size

### Risk register

- VACUUM rewrites the entire DB; needs ~live-DB-size of free space mid-run. With 16 GB free post-resize and DB at 29 GB, **VACUUM will fail unless we drop the tables FIRST and `pragma incremental_vacuum` afterwards** — or move the DB to a temporary location with more free space. Verify free-space math before pulling the trigger.
- Compatibility: any R analysis script that reads `post_snapshots` or `comment_snapshots` will break. Audit `analysis/R/` first; nothing in there should depend on these tables under the Phase 3 design (R should be reading `posts.content` directly, since posts are immutable).

---

## Block C — Verify cron + script changes from session 24 actually landed on VM

**Precondition**: this Block's edits may have been completed in session 24 (check session log) or may still be pending. Idempotent — safe to re-run.

Session 24 made local edits to `scripts/monthly_rescrape.sh` and (per plan) updated the VM crontab. Verify the VM matches.

### C.1 monthly_rescrape.sh on VM matches local

```bash
ssh vm 'grep -E "DAY_OF_MONTH|monthly-pre|first Tuesday" ~/moltbook_scraper/scripts/monthly_rescrape.sh | head -10'
```

Expected:
- One line referencing `DAY_OF_MONTH=$(date -u +%-d)` (the Tuesday guard)
- One line of comment about "first Tuesday"
- **No active line** creating `monthly-pre-*.db` (only a comment block explaining its absence)

If output is missing these markers: scp the local file:
```bash
scp scripts/monthly_rescrape.sh vm:~/moltbook_scraper/scripts/
ssh vm 'dos2unix ~/moltbook_scraper/scripts/monthly_rescrape.sh'
ssh vm 'bash -n ~/moltbook_scraper/scripts/monthly_rescrape.sh'   # syntax check
```

### C.2 Crontab line matches new schedule

```bash
ssh vm 'crontab -l | grep monthly'
```

Expected: `55 1 * * 2  cd /root/moltbook_scraper && bash scripts/monthly_rescrape.sh ...`

If still `55 1 1 * * ...`: update via:
```bash
ssh vm 'crontab -l > /tmp/cron.tmp; sed -i "s|55 1 1 \\* \\*|55 1 * * 2|" /tmp/cron.tmp; crontab /tmp/cron.tmp; crontab -l'
```

### C.3 No leftover monthly-pre backups on volume

```bash
ssh vm 'ls /mnt/HC_Volume_104999576/moltbook_data/backups/moltbook-monthly-pre-*.db 2>/dev/null'
```

Expected: empty output (file not found). If any exist (none should, per session 24 spot-check), they are safe to `rm` to free disk.

---

## Known issues / open threads

### Apr 1 monthly never completed

[verified 2026-04-27] `logs/monthly-2026-04-01.log` is 4 lines: header + "Backing up database (pre-scrape)..." then nothing. No SUCCESS, no FAILED, and no `monthly-pre-2026-04-01.db` exists in `backups/`. As far as available evidence, **no monthly run has ever completed in the project's history**. Cron fired Apr 1 02:00 UTC and the script died silently somewhere during `sqlite3 .backup`.

To diagnose: check `~/moltbook_scraper/logs/cron.log` around 2026-04-01, `dmesg | grep -i kill` for OOM, and `/var/log/syslog` if retained. Likely culprits: OOM during `.backup` (the live DB at the time was ~22 GB; `.backup` opens a transaction holding pages in memory), disk-write failure on the at-the-time-cramped root disk, or an interrupted SSH session that took the script with it.

This becomes immediately relevant if May 5 monthly also dies silently. Do not assume the monthly will run successfully just because the cron fires.

### Pytest hang

[verified 2026-04-21] `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.

---

## Resuming after absence

1. Run §Spot-check block at top.
2. Decide which Block applies based on output:
   - Apr 27 weekly still running → wait, do nothing operational
   - Apr 27 weekly SUCCESS → Block A
   - Block A passed → Block B
   - Crontab line is wrong / scripts mismatched → Block C (do this in parallel with anything else)
3. Read `CLAUDE/session_logs/2026_04_27_session_log.md` for the full debugging trace and decision rationale of session 24.
4. After completing any Block, update this handover and methodology log accordingly.

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
