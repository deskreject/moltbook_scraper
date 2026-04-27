# Session 24 — 2026-04-27

Machine-switch startup. Triggered by a disk-full alert on the VM, became a deeper audit of forecasts vs. reality. Volume resized 80 → 100 GB online; backup retention rewritten; monthly cron rescheduled; multiple stale claims in `claude_handover.md` and methodology log corrected.

## Context at session start

Apr 27 weekly cron fired 02:00 UTC and is currently mid-run (comments stage ~80 % through at session start). User received a disk-full email alert (volume at 100 %).

## Disk-fill diagnosis and resolution

`df -h /mnt/HC_Volume_104999576` returned 79 G / 79 G / 0 B / 100 %. `tune2fs -l /dev/sdb` showed only 107 MB free even to root — the 5 % reserved buffer was nearly exhausted. Active scrape was surviving on UPDATE-in-place writes (comments stage upserts existing rows, no new block allocations) with WAL checkpointing aggressively, but the snapshots stage at end of run would have hit ENOSPC within seconds.

**False alarm investigated and dismissed**: `status.sh` reported "795 errors" in `weekly-2026-04-27.log`. This came from `grep -ic "error"` matching the literal `0 errors)` inside every comments-stage progress line. Real error count via grep on `Exception|Traceback|ENOSPC|OperationalError`: **0**. The running scrape is healthy.

**Resolution**: user resized Hetzner volume 80 → 100 GB in console. Online `resize2fs /dev/sdb` ran during the live scrape (kernel 6.8, ext4 with `resize_inode` + `64bit` → fully supported). New state: 99 G / 16 G free / 84 % used. Scrape unaffected (PID 920465, comments progressed across the resize boundary with 0 errors).

## Three significant corrections to prior understanding

### 1. Phase 3a is replacement, not parallel writes

The prior handover claimed "Legacy snapshot writer still running. Until Phase 4 drops the `*_snapshots` tables, every weekly still appends a full-dump layer (observed ~5–6 GB in session 22)." Reading `src/scraper.py:create_snapshots` (lines 525–546): it only calls `_snapshot_posts/_agents/_submolts/_moderators`, all of which write only to `*_metrics` / `*_events`. **No legacy writer code path exists.**

Empirical confirmation:
- VM DB row counts: `post_snapshots: 11.2M, comment_snapshots: 18.5M, ...` (frozen historical) vs. `post_metrics: 0, agent_metrics: 0, ...` (Apr 27 snapshot stage hasn't run yet).
- Apr 20 weekly log shows the OLD writer creating 7.2M snapshot rows (pre-Phase-3a code).
- Local `src/scraper.py` (matches VM per session 23 verification) has no `INSERT INTO *_snapshots` anywhere in the new helpers.

**Implication**: ongoing snapshot growth stopped Apr 24. The 30 M legacy rows are pure historical residue. All my forecasts about "5–6 GB/week ongoing legacy bloat" were wrong.

### 2. Disk math missed monthly retention

Backup retention scheme as deployed:
- Weekly: `KEEP_WEEKLY_BACKUPS=1`, prunes only `moltbook-weekly-*.db` at end of run
- Monthly: `KEEP_MONTHLY_BACKUPS=1` *each* for `moltbook-monthly-pre-*.db` and `moltbook-monthly-post-*.db`

Steady state once monthly has fired = 3 backups (1 weekly + 1 monthly-pre + 1 monthly-post). At ~29 GB each, that's 87 GB just in backups + 29 GB live DB = 116 GB. Cannot fit 100 GB volume.

I had been forecasting 2N peak (just live DB + previous weekly). Adding monthly's pre+post pushes peak to 4N during a monthly run end. This was never going to fit — independent of Phase 3a / Phase 4.

### 3. Apr 1 monthly never completed

`monthly-2026-04-01.log` is 4 lines: banner + "Backing up database (pre-scrape)..." and stops. No SUCCESS / FAILED markers. No `monthly-pre-2026-04-01.db` exists in `backups/`. **As far as evidence on disk, no monthly run has ever completed since project start.** Likely OOM or disk-write failure during `sqlite3 .backup` on the at-the-time cramped root disk. Logged as a Known Issue in handover; full diagnosis deferred.

## Decisions

- **Drop pre-monthly backup.** Latest weekly serves as ≤7-day-stale "before monthly" recovery point. Risk accepted.
- **Move monthly cron to first Tuesday of month** (`55 1 * * 2` + day-of-month ≤ 7 guard). First Tuesday always lands after that week's Monday weekly, avoiding the 1st-Monday collision class entirely. May 2026 monthly fires May 5, after May 4 weekly.
- **No gzip compression.** Math without compression: post-Phase-4 live DB ~14 GB + 2 retained backups (~14 GB each) = ~42 GB steady, ~56 GB peak in 100 GB volume. Plenty of headroom; gzip stays as future contingency only. Backups remain plain `.db` files openable by any sqlite3 client.

## Edits made (local)

- `scripts/monthly_rescrape.sh`: added first-Tuesday guard, removed pre-scrape backup section, prune loop limited to `monthly-post-` prefix, header comments updated.
- `CLAUDE.md`: monthly cron line, weekly/monthly coordination section, Legacy note (snapshots frozen, not still growing), new Backup retention policy section.
- `claude_methodology_log.md`: snapshot redesign Active (was "implementing"), enrich commit fix Active (was "pending VM push"), Parquet-zstd backup decision superseded, monthly schedule entry, backup retention entry, sharding marked Planned.
- `claude_learnings.md`: removed stale "Post-Phase-4 archive plan" claim; WAL "planned in Phase 3a" tag updated to "deployed 2026-04-24".
- `claude_handover.md`: full rewrite. State-conditional Block A/B/C structure (no date-driven steps); claim provenance convention (`[verified] / [design] / [planned]`); Apr 1 monthly added to Known Issues.

## VM-side changes still pending (Block C in handover)

1. `scp scripts/monthly_rescrape.sh vm:~/moltbook_scraper/scripts/`
2. `ssh vm 'dos2unix ~/moltbook_scraper/scripts/monthly_rescrape.sh; bash -n ~/moltbook_scraper/scripts/monthly_rescrape.sh'`
3. Update VM crontab line from `55 1 1 * *` → `55 1 * * 2`

These are safe with the weekly running (different script, crontab edits don't affect running cron jobs). Holding off until user confirms.

## Why the handover went stale despite the session-summary skill

Root cause: session 23 wrote the post-push handover by transcribing the original Phase 3 design intent (parallel writes + Phase 4 archive) instead of re-reading the deployed code. The session-summary skill captures session narrative, but it cannot detect divergence between what was written down and what is actually in the file system.

Mitigation in this rewrite: every claim in the handover is tagged `[verified <date>]`, `[design]`, or `[planned]`. Future updates re-tag rather than copy-forward. This makes stale claims visible by their tags rather than camouflaged in narrative prose.

## Next session (state-conditional, in handover)

- Apply Block C (scp + crontab) on VM. Independent of weekly status; can do anytime.
- Once Apr 27 weekly SUCCESS: run Block A verification (enrich pool, narrow tables, legacy tables didn't grow).
- After Block A passes: execute Block B (Phase 4 — drop legacy `*_snapshots`).

Apr 1 monthly silent-death investigation deferred until May 5 monthly either runs cleanly or fails the same way.
