# Session 25 — 2026-05-03

Machine-switch startup. Block A verification (Phase 3a empirical confirmation) all passed. Phase 4 executed end-to-end: legacy `*_snapshots` dropped, live DB 29 GB → 6.2 GB, ~30 M rows preserved as compressed local cold-storage dump.

## Context at session start

- Apr 27 weekly had completed 2026-04-30 11:33 UTC (`SUCCESS`, 81.5 h, 0 real errors). status.sh's "2981 errors" was the same false-positive grep pattern documented in session 24.
- Block C from session 24 was already fully landed on VM (crontab `55 1 * * 2`, monthly_rescrape.sh has the day-of-month guard, no leftover monthly-pre backup).
- Volume: 99 GB / 38 GB free / 61 % used.
- Local repo: `main`, 5 commits ahead of origin, 2-line uncommitted edits to `claude_archive.md` + `claude_methodology_log.md` carried from session 24.
- Predicted next-action: Block A → Block B (Phase 4).

## Block A — Phase 3a writer empirical verification

Six probes against the VM DB; cross-checked the snapshot stage R1 monitoring lines from `weekly-2026-04-27.log`.

| Check | Expected | Got | Verdict |
|---|---|---|---|
| A.1 `claimed_by` NULL on claimed agents | ≤ 200 expected, ≤ 2000 acceptable | **240** (out of 175,311) | PASS — likely the 238 transient enrich errors |
| A.2 `post_metrics` rows | ~22 K (Apr 8 dryrun) | **334,421** | PASS — see A.4 |
| A.2 `agent_metrics` rows | ~175 K | **177,058** = all agents | PASS |
| A.2 `submolt_metrics` rows | ~20 K | **20,840** = all submolts | PASS |
| A.2 `moderator_events` rows | ~19,655 | **20,010** | PASS (~355 more pairs since Apr 8) |
| A.2 `post_events` / `agent_events` / `submolt_events` | 0 / 0 / 0 | **0 / 0 / 0** | PASS — anchor design works |
| A.3 legacy `*_snapshots` `MAX(scrape_run_id)` | all = 1 (Apr 20 weekly) | **all = 1** | PASS — Phase 3a is replacement, not parallel writes |
| Anchor coverage `agents.is_claimed_first` | 99.1 % (dryrun) | 175,502 / 177,058 = **99.1 %** | PASS |
| Anchor coverage `posts.is_pinned_first` | high | **2,631,836 / 2,631,836 = 100 %** | PASS |
| All `*_metrics`/`*_events` `scrape_run_id` | 2 (Apr 27 weekly) | **all = 2** | PASS |

### A.4 — added probe to explain post_metrics = 334 K vs 22 K dryrun

Direct count: posts in DB with `julianday('2026-04-30T11:31:34Z') - julianday(created_at) <= 28` = **334,382**. The writer reported 334,421 inserted. **Δ = 39 rows** = posts created during the snapshot stage's 3-min window. Match.

Conclusion: writer is exactly per spec (4-week age cutoff). The session-23 dryrun saw 22 K because the Apr 8 frozen DB only contained 12 days' worth of post creations between the dryrun's effective `now` (Apr 24) and the DB's most-recent `created_at` (Apr 8). The handover's "expected ~22 K" range was an apples-to-oranges artifact, not a real benchmark. Updated methodology log entry accordingly.

Net: **all of Block A passed**. Phase 3a writer behaves as designed; legacy writer is fully retired.

## Block B / Phase 4 — option choice

User chose **option 2-full**: drop all 5 legacy `*_snapshots` tables (not selective drop), preserve a compressed dump on local. Reasoning: even if there is some signal in agent/submolt/moderator snapshots, a single historical archive on local is sufficient — no reason to keep ~150 MB of agent_snapshots living on the VM "just in case". `snapshot_mutability_evidence` (the audit summary, 30 rows, methodology-logged as "preserved permanently") explicitly excluded from the drop.

## Phase 4a — dump + transfer + verify (reversible)

Source: `moltbook-weekly-2026-04-27.db` (29 GB) — frozen, consistent backup. Avoided live DB to eliminate any contention risk.

```
sqlite3 backup.db ".dump <5 tables>" | gzip -6 > /mnt/.../legacy_snapshots_2026-04-27.sql.gz
```

- Dump duration: 13 min 45 s (19:06:50 → 19:20:35 UTC)
- Output size: **6.2 GB compressed** (vs ~22 GB raw data + indexes)
- VM SHA256: `720c3994ea60603dae19342b37d7c0c2a576e5ceefcd9f90c4f2daa3625ed817`
- SCP to local `data/archive/legacy_snapshots_2026-04-27.sql.gz`: ~9 min at ~15 MB/s
- Local SHA256: **identical** byte-for-byte
- INSERT-line counts inside dump match the row counts in handover §Known State exactly:
  - post_snapshots: 11,192,074 (handover: 11.2 M ✓)
  - comment_snapshots: 18,502,164 (18.5 M ✓)
  - agent_snapshots: 865,825 (866 K ✓)
  - submolt_snapshots: 100,342 (100 K ✓)
  - moderator_snapshots: 92,098 (92 K ✓)
  - **Total preserved: 30,752,503 rows**

## Phase 4b — DROP + VACUUM (irreversible)

Single ssh wrapper, output captured in `tasks/bj2poc5d0.output`:

1. Pre-flight: no scrape running, no orphan sqlite3.
2. `crontab -l > /tmp/cron.bak.20260503T195958Z` (9 lines), then `crontab -r`.
3. Pre-DROP table list confirmed all 6 of-interest tables present (5 to drop + audit table).
4. `BEGIN; DROP TABLE post_snapshots; DROP TABLE comment_snapshots; DROP TABLE agent_snapshots; DROP TABLE submolt_snapshots; DROP TABLE moderator_snapshots; COMMIT;` — **took ~28 min**, NOT instant. WAL grew to **17 GB** during the transaction (page-frees being journaled); volume free hit a peak low of **15 GB**. Survived but was tight. After COMMIT, auto-checkpoint cleaned the WAL fully (no `*-wal` file remained even before my explicit `wal_checkpoint(TRUNCATE)`, which returned `0|0|0`). DB file still 29 GB at this point — pages marked free internally but not reclaimed.
5. Post-DROP table list: 5 dropped tables gone, `snapshot_mutability_evidence` still there with 30 rows.
6. `VACUUM`: 5 min 6 s (20:46:19 → 20:51:25 UTC). DB rewrote to **6.2 GB**. Volume free jumped 32 GB → **54 GB**.
7. `PRAGMA integrity_check` → `ok`.
8. Live data row counts unchanged: posts 2,631,836, comments 4,713,351, agents 177,058, submolts 20,840, moderators 20,010. Phase 3 tables also unchanged (post_metrics 334,421, etc.). `claimed_by` gate still 240.
9. Cron restored from backup; `crontab -l` confirms 3 active lines (weekly, monthly, disk monitor).
10. VM-side dump file deleted (`legacy_snapshots_2026-04-27.sql.gz`); only `moltbook-weekly-2026-04-27.db` (29 GB) remains in backups.
11. Final disk: **35 GB used, 60 GB free, 37 %**.

## Disk impact summary

|  | Pre-Phase-4 | Post-Phase-4 | After Mon May 4 weekly |
|---|---|---|---|
| Live DB | 29 GB | **6.2 GB** | ~6–7 GB |
| Latest weekly backup | 29 GB | 29 GB (Apr 27) | ~6–7 GB (May 4 backup, Apr 27 pruned) |
| Volume free | 38 GB | **60 GB** | **~83 GB** projected |

Steady-state going forward: live DB ~6–7 GB + 1 weekly backup ~6–7 GB + 1 monthly-post backup ~6–7 GB ≈ 21 GB used, ~78 GB free. The volume-resize anxiety is resolved for the foreseeable future.

## Predicted Mon May 4 weekly behaviour

- Enrich pool: **7,537 agents** (queried `WHERE description IS NULL OR (is_claimed=1 AND claimed_by IS NULL)`). Back to "new agents this week" baseline. Runtime ~16 h instead of 80+ h.
- Snapshot stage (second run after Phase 3a): `*_metrics` inserts only for entities whose values actually moved since the Apr 27 baseline. Expect ~5–10 % of entity counts (handful of MB), not the 334 K + 177 K + 20 K first-run baseline.
- `*_events`: only on actual flips. Probably single-digit to low-hundreds.
- Post-prune: latest weekly backup will be `moltbook-weekly-2026-05-04.db` (~6–7 GB), the 29 GB Apr 27 backup gone.

## Files touched (project repo)

- `.gitignore` — added `data/archive/` and `*.sql.gz`
- `CLAUDE/session_logs/2026_05_03_session_log.md` — this file
- `claude_methodology_log.md` — Phase 4 entry; Phase 3a + commit-fix entries updated with empirical results
- `claude_learnings.md` — WAL-during-DROP lesson; status.sh "DB size 0" cosmetic
- `claude_handover.md` — full rewrite as launchpad for post-Phase-4 state
- `claude_archive.md` — Phase 4 completion under "Disk recovery and backup policy"; Block A/B/C handover-structure superseded (under "Handover format evolution")
- `CLAUDE.md` — Legacy note section gutted (tables no longer exist); Backup retention projections updated to actuals
- `data/archive/legacy_snapshots_2026-04-27.sql.gz` — 6.2 GB cold-storage dump (gitignored)

Pre-existing uncommitted edits to `claude_archive.md` and `claude_methodology_log.md` from session 24 carried into this session and folded into today's update (the Phase 3a-superseded note + the Apr 27 incident archive entry).

## Files touched (memory)

- `reference_hetzner_vm.md` — DB size 6.2 GB; volume 100 GB / 60 GB free; cron schedule corrected (monthly is `55 1 * * 2`); SSH alias `vm` used in practice
- `project_automation_cadence.md` — DB size, monthly cron, post-Phase-4 expected weekly runtime

## Rollback

Phase 4 is irreversible at the VM. Recovery path if any dropped data is ever needed:

```bash
gunzip -c data/archive/legacy_snapshots_2026-04-27.sql.gz | sqlite3 restored.db
```

This produces a standalone DB containing only the 5 dropped tables + their indexes. Use for one-off historical queries; do NOT load back into the live DB.

Doc edits are revertible via `git checkout --` before the next commit.

## Open threads (forwarded to handover)

1. Apr 1 monthly silent-death — diagnose only if May 5 monthly also fails. Cron now fires `55 1 * * 2` with first-Tuesday guard, so May 5 = first attempt under the new schedule.
2. Pytest hang on full-suite run — still unresolved; always scope to specific test files (recorded in learnings).
3. Sharding by submolt first-letter — still **planned, not implemented**. Re-evaluate after first successful post-Phase-4 monthly.
4. status.sh "DB size: 0" cosmetic bug — `du` on a symlink path. Pre-existing since Apr 8. Low priority but visible every session-startup; worth a 5-line fix.

## Notable surprises

- **DROP TABLE on a large table in WAL mode is NOT instant.** SQLite has to journal every freed page into the WAL inside the transaction. Our 5-table DROP took 28 min and grew the WAL to 17 GB. Lesson logged.
- **post_metrics 334 K vs dryrun 22 K** was not a bug — the dryrun number was effectively meaningless because the Apr 8 DB didn't have posts more recent than itself. Future dryrun docs should compute "posts within N days of DB's MAX(created_at)" instead of "within N days of now" to be comparable across runs.
