# Session 20 — 2026-04-16

## Goals
1. Machine-switch startup; verify environment.
2. Confirm Apr 13 weekly cron ran cleanly and Apr 20 will fire.
3. Pick up Phase 2 audit results.

## Environment check
- Local DB still pre-migration (Apr 8 snapshot, 11 GB) — needs `scp` pull when convenient.
- `.env`, `.venv`, all session-19 scripts (backfill / probe / audit) present.
- `ssh vm` works.

## Apr 13 weekly: clean success (6/6 stages, 16.8 h)

| Stage | Duration |
|---|---|
| Backup | 2 min (16 GB) |
| Incremental | 7.5 min |
| Submolts | 11.5 min |
| Comments | 5.2 h |
| Moderators | 7.6 h |
| Enrich | 3.0 h (7,274/7,281, 7 normal API errors) |
| Snapshots | 41 min (6.81 M rows / 5 tables) |

Latest post `2026-04-13T02:01:52Z`. Apr 20 will run as a regular incremental — **no catch-up needed**. The 1,038 "errors" reported by `status.sh` are the known cosmetic false-match (`grep "error"` catches "0 errors" progress lines).

## Phase 2 audit — complete

Full results pulled: `tables/snapshot_mutability_audit_2026-04-14.csv` (also persisted in `snapshot_mutability_evidence` table on VM DB).

| Table | Pairs | Verdict |
|---|---|---|
| **agent_snapshots** | 513,387 | Content fields <0.1 %; numeric (karma, follower, following) 0.4–2.2 % — all pass 5 % gate |
| **post_snapshots** | 6,203,260 | Every column ≤ 0.003 % — strongest compression candidate |
| **comment_snapshots** | 9,883,470 | Every column **0.0000** — comments are immutable in practice |
| **submolt_snapshots** | 58,883 | `description` 8.84 % and `subscriber_count` 9.85 % **FAIL** the gate; rest pass |

**Implication for Phase 3:** submolt schema work was not in the original Phase 3 list — needs adding. `submolts.description` and `subscriber_count` need either a metrics-panel column or first+latest anchors. Everything else (comments especially) compresses aggressively.

## Cleanup actions
- Killed 2 stale tmux sessions on VM (`backfill` from 04-14 lock-death, `scrape` from session-8 era — both empty).
- Pulled audit CSV to local `tables/`.
- Backfill still pending: `claimed_by` populated for 1 / 174,275 agents. Audit lock no longer holds, safe to restart.

## Files touched
- `tables/snapshot_mutability_audit_2026-04-14.csv` — new (pulled from VM).
- `CLAUDE/session_logs/2026_04_16_session_log.md` — new.
- `claude_handover.md`, `claude_methodology_log.md`, `claude_learnings.md` — updated.

## Next session
1. Restart `backfill_claimed_by.py` on VM in tmux with `bash -c "... ; exec bash"` wrapper.
2. Run `probe_submolt_flags.py` on VM.
3. Design Phase 3 schema migration — incorporating submolt handling (new finding).
