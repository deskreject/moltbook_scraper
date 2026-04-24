# Session 22 — 2026-04-21

Machine-switch startup, diagnosis of the Apr 20 weekly state, and overhaul of the project's documentation discipline. No VM changes this session.

## Context at session start

- Machine switched (home PC). Pulled latest repo state; working tree clean after session 21's local commit `86d543d`.
- Phase 3a code is committed locally but not pushed to VM.
- Apr 20 weekly cron fired at 02:00 UTC as expected.

## Machine-switch verification

All expected local artifacts present: `.env`, `.venv/`, Apr 8 DB (11 GB), `scripts/verify_phase3a.py`, `scripts/dryrun_snapshots.py`, `verification_probes.md`, `tests/test_snapshot_change_detection.py`. Git is clean on `main`.

One discrepancy: the handover's Git State line claimed Phase 3a changes were uncommitted. They were in fact committed as `86d543d` at end of session 21. Stale doc line, not a state problem.

## Step B investigation — Apr 20 weekly

The Apr 20 weekly is **still running** at 09:28 UTC Apr 21 (~31 h elapsed). Enrich stage is live, processing 40,300 of 174,939 agents at ~40/min (rate-limit bound). Remaining ~56 h, plus moderators (~7.6 h) and snapshots (~41 min). **Expected completion: Apr 23–24 UTC.**

### Root cause of the marathon run

`get_unenriched_agent_names()` in `src/database.py` was widened to include `OR (is_claimed = 1 AND claimed_by IS NULL)`. This catches the session-18 migration gap where `claimed_by` was added but only 1 of 174,275 claimed agents had been populated (because `enrich --only-missing` filters on missing description, so already-enriched agents were never re-fetched).

The widened predicate was pushed to the VM between Apr 13 and Apr 20. Apr 13 weekly saw only 7,281 agents (normal incremental). Apr 20 weekly sees 174,939 — the entire backfill pool in one go. Verified by direct read of `~/moltbook_scraper/src/database.py` on the VM: the `OR` branch is present.

**This is a one-time event.** Once this run completes, every re-enriched agent has `claimed_by` populated, so the `OR` branch returns ~0 rows thereafter. Next weekly's pool reverts to the ~7K new agents added during the week.

### Correction to the session 20 → 21 handover narrative

The handover (and session 20 log) claimed Step C (backfill) still required a separate tmux script. In reality the predicate extension had already absorbed the backfill into the weekly path — session 20 simply observed that enrich hadn't run yet due to the audit lock. By Apr 20 the absorption kicked in naturally. The dedicated tmux script was never needed.

### VM state checks

- Disk: 80% / 16 GB free on the volume. No immediate pressure.
- Backups: **both Apr 13 (16 GB) and Apr 20 (22 GB) present** — 38 GB total. Retention policy is 1 (2026-04-08 decision). Prune step is failing silently. Diagnosis deferred to next action, not this session.
- No orphan Python processes (local or VM) beyond the live enrich.
- `scrape_run_id` verification (session 19 fix) deferred — DB is locked by the live enrich.

## Documentation discipline overhaul

User raised a fundamental concern: pruning without breadcrumbs becomes forgetting. Across a long project, neither user memory nor session-scoped assistant memory is reliable. A returning user or fresh assistant must be able to reconstruct decision trails from the files alone — but without drowning in detail.

### Agreed discipline

| File | Role | Rule |
|---|---|---|
| `CLAUDE/session_logs/YYYY_MM_DD_session_log.md` | Diary, source of truth for each session | Full detail, decisions, rationale, rollback notes |
| `claude_handover.md` | Launchpad | Current state, next actions, open risks; no reasoning |
| `CLAUDE.md` | Project rules & reproducibility invariants | Rules only; cite source when non-obvious |
| `claude_methodology_log.md` | Append-only active decisions | Date / Decision / Reasoning / Status; source pointer for reopen-able decisions |
| `claude_archive.md` | Superseded / completed work | Topical, dates inline, abbreviated; link to session log only when full context still matters |
| `claude_learnings.md` | Failures and dead ends | Never pruned |

### Judgment calls (not hard rules)

- Not every archived item needs a pointer back. Completed one-shot tasks (integrity checks, etc.) don't. Superseded design decisions do.
- Not every methodology log row needs a source pointer. Routine decisions don't; debated ones do.
- Handover length can exceed typical size when a large in-flight process needs unusual detail. Don't sacrifice clarity for line count.

### Project-agnostic placement

The discipline overview lives in `~/.claude/commands/session-summary.md`, not in project `.md` files. Rationale: user is trialing the session-summary cadence and doesn't want to propagate discipline text across every project doc that would then need editing if the command changes or is dropped.

## Files written / modified

- `~/.claude/commands/session-summary.md` — rewritten with the documentation structure overview, judgment-call guidance, and explicit steps for handover trimming, ad-hoc file consolidation, and topical archive restructuring. Kept project-agnostic.
- `~/.claude/commands/machine_switch_startup.md` — revised to reference the documentation structure and require spot-checking current state (running processes, VM) before trusting handover.
- `claude_handover.md` — rewritten as launchpad (~75 lines). Next actions, known risks, resume instructions only. Pointers to session logs for all non-trivial context.
- `claude_archive.md` — restructured from chronological to topical (Project foundation / API quirks / Rate limits / Phase 0 / Schema evolution / VM infrastructure / Disk recovery / Phase 2 audit / Claimed_by backfill strategy / Methodology log retired / Handover format evolution). Dates preserved inline.
- `verification_probes.md` — deleted. P1/P2 resolution already in `2026_04_20_session_log.md`; P3 (WAL persistence) and P4 (first-run DB size) folded into the handover's Phase 3a post-push verification block; P5 (monthly sharding runtime) folded into the deferred-actions section.
- `CLAUDE/session_logs/2026_04_21_session_log.md` — this file.

No changes to `CLAUDE.md`, `claude_methodology_log.md`, or `claude_learnings.md` this session (no new project rules, no new decisions, no new failures).

## Phantom-fixes correction

Mid-session I drafted a two-part pre-push action (diagnose backup-prune "bug"; add weekly-vs-weekly lock). User pushed back — rightly — asking what the fixes actually changed. Careful re-read of local `scripts/weekly_scrape.sh` and direct `grep` on VM's copy of the same file showed:

- **Weekly-vs-weekly lock already exists.** `LOCK_FILE="/tmp/moltbook_scrape.lock"` at line 19, with PID + `kill -0 $pid` liveness check around lines 97–108. Present on both local and VM copies. Pre-existing since session 12.
- **Backup prune is not broken.** Retention = 1 (`KEEP_WEEKLY_BACKUPS=1`, line 22); prune step at the END of the weekly script (lines ~137–138 / 157–162 depending on version), inside the same run. The Apr 13 backup is still present only because the Apr 20 weekly that would have pruned it is still mid-enrich. No bug.

Neither fix was needed. Corrected handover accordingly (dropped action 1; re-numbered).

Lesson: before writing a "fix", read the target file end-to-end — not just the relevant-looking section. Added to `claude_learnings.md`.

## Time-sensitive handover mechanism

User flagged a real risk: they might not return until well into the next weekly cycle (or later). A future-me reading only the "Last updated 2026-04-21" line could misinterpret stale claims as current. Fix: handover now opens with a MUST-run VM spot-check block and a §Return-after-delay interpretation table keyed on return date × which crons fired × whether Phase 3a was pushed. Discipline: VM git log and `status.sh` are truth; handover text is a frozen snapshot.

## Pending actions

See `claude_handover.md` §Next-actions. Summary:

1. Wait for Apr 20 weekly to finish (~Apr 23–24 UTC).
2. Push Phase 3a to VM (target: before Apr 27 02:00 UTC).
3. Phase 4 (user-supervised compression of 15 GB legacy snapshots).

## Rollback

Documentation-only changes this session. `~/.claude/` is not under version control on this machine, so command-file changes are not trivially revertible — if either command needs to be restored, the previous versions are recoverable from this session log (full previous content is in the git history of this repo via the session-summary command mentions in session 21 log, but the commands themselves were not tracked). Project-repo changes are on `main`, uncommitted; `git checkout -- <path>` reverts any of them before the next commit.

## Open questions

- Should `~/.claude/commands/` be put under git (separate repo, not this project's)? Would make command-file revisions trackable. Not addressed this session.
- Should `CLAUDE.md` be trimmed in a future session? Current version is ~210 lines; a lot of the Phase 3 design text could be moved to session 21 log with a pointer. Defer until after Phase 4 lands (CLAUDE.md will need a pass then anyway).
