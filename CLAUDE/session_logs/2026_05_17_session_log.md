# Session 29 — 2026-05-15 → 2026-05-17

Multi-day session, machine-switch startup → block-A investigation of the May 5 monthly-incident corruption. No code changes. Output is: (a) empirically-verified classifier separating false-positive comment tombstones from genuine deletions, (b) discovery that the analogous bug also exists in the posts-stage path, (c) a proposed minimal safeguard set + verification plan using a second API token and NordVPN before any code lands. User signoff requested before further work; weekly cron fires Mon 2026-05-18 02:00 UTC and is structurally immune to this bug class (no `--detect-deletions`).

## Context at session start

- Machine-switch startup. Spot-check vs handover (2026-05-12, session 28) all matched: weekly + disk-monitor cron active, monthly commented out, DB 7.9 GB, two backups (May 11 weekly + May 5 monthly-post) totalling 14.8 GB, API healthy (200/200 per-token, no infra-limit recurrence). Local `.env`, `.venv/`, `data/raw/moltbook.db` all present.
- Block A goal from handover: investigate and remediate the May 5 monthly false-deletion corruption — but per user direction, validate session-26 claims empirically rather than just assume them, and characterise the rate-limit trigger mechanism before redesigning the monthly script.

## What was done

### 1. Verified the session-26 bug description against the actual code

`client.py:fetch_comments_only` (lines 417-429) catches `except Exception` and returns `[]`. `_request` (line 105+) does raise `RateLimitError` on retry exhaustion, so the swallow is the proximate cause. `scraper.py:_detect_deleted_comments` (lines 489-511) computes `existing_db_ids - api_comment_ids` and calls `mark_comments_deleted` unconditionally if the diff is non-empty. The "uncertain" flag at line 508 is set only when `comment_count > 500` (the API hard-cap heuristic), not based on whether the fetch succeeded. **Exactly the bug session 26 described.**

### 2. Probed the May 5 deletion distribution in the DB

Window: `deleted_detected_at >= '2026-05-05' AND < '2026-05-09'`.

- 4,126 comment tombstones (2,620 firm + 1,506 `deletion_uncertain=1`) across **521 distinct posts**.
- 6,428 post tombstones — all on 2026-05-05 (single posts-full stage pass).
- Hourly histogram of comment deletions: steady drip 9-217/h across all 72 h, mean ~57/h. No sharp onset visible. Inconsistent with "rate limit tripped once at hour ~60 and stayed on"; more consistent with **intermittent** trips through the run.

### 3. Stratified empirical false-deletion probe (n=30 posts, 574 tombstoned comments)

Computed per-affected-post the fraction `tombstoned / in_db_total`. Distribution is **bimodal** — 324 posts have frac == 1.0 (whole-post wipe), 197 posts have frac < 0.5, **zero posts in the 0.6-0.8 borderline**. The classifier is exact:

| Stratum | n_posts | tombstoned | in_db_total | sampled posts | tombstoned comments back from live API |
|---|---|---|---|---|---|
| **hi** (frac ≥ 0.8) | 324 | 1,533 | 1,533 | 10 | **28 / 28 = 100%** |
| **mid** (0.2 < frac < 0.8) | 30 | 1,518 | 4,951 | 10 | 0 / 479 = 0% |
| **lo** (frac ≤ 0.2) | 167 | 1,075 | 22,884 | 10 | 0 / 67 = 0% |

The hi-stratum posts are uniformly small (104 had 1 comment, 134 had 2-4, 73 had 5-19, 13 had 20-99, **0 had 100+**). This is mechanistically explained: when the API returns `[]` after rate-limit retries exhaust, the post's *entire* comment set gets marked deleted. Big-thread posts that had partial real responses ended up in mid/lo with only the genuinely-missing comments tombstoned. The saved sample from session 26 (post `2312864c-...`, 3 tombstoned out of 3 in DB) is in the hi stratum — all 3 alive in API now, as session 26 predicted.

**Remediation rule is exact**: `tombstoned == in_db AND in_db > 0` → false-positive candidate. Per user, simpler approach is to skip the targeted clever logic and just re-fetch comments for all 521 affected posts + posts for all 6,428 deleted post IDs. Nothing is lost by refetching since we don't accumulate content over time.

### 4. Found the same bug class in the posts-stage path

`client.py:fetch_posts_streaming` (lines 280-329) catches every Exception including `RateLimitError`, increments `consecutive_errors`, and after 10 consecutive errors **silently breaks the loop and returns**. `scraper.py:scrape_posts` (lines 122-166) then runs `all_db_ids - seen_ids` against an incomplete `seen_ids` and marks the difference as deleted via `mark_posts_deleted`. If cursor pagination dies near the end of the walk, you get a small false-positive set that's indistinguishable from a real deletion run. The 6,428 posts on 2026-05-05 could partly be that. `fetch_submolts` (lines 195-225) has the identical `except Exception` consecutive-errors swallow pattern but no current downstream `--detect-deletions` consumer for submolts, so it's not corrupting data — just structurally fragile.

### 5. Drafted minimal safeguard set (NOT applied — for review)

Three small changes, ~10 lines total:

1. **`client.py:fetch_comments_only`**: re-raise `RateLimitError`, return `[]` only for non-rate-limit exceptions (404, JSON decode).
2. **`client.py:fetch_posts_streaming`** (and `fetch_submolts` for symmetry): re-raise `RateLimitError` instead of swallowing it into `consecutive_errors`.
3. **`scraper.py:_detect_deleted_comments`** defensive guard: if `len(api_comment_ids) == 0 AND existing_ids non-empty`, treat as ambiguous and skip / write `deletion_uncertain=1` rather than tombstoning. Catches the failure mode even if a future bug somehow lets an empty response through.

Existing `tests/test_client.py` uses `responses` mock library and already has `test_gives_up_after_max_retries` style for submolts — easy to add an analogous failing test for `fetch_comments_only` before the fix lands.

### 6. Designed verification tests using second API token + NordVPN

User has a second API key (unused — pristine reputation) and NordVPN. Plan:

| # | Test | What it answers | Cost |
|---|---|---|---|
| T1 | Sequential ~25/min from NordVPN+token2 for 1h; observe `X-RateLimit-*` headers | Baseline per-token behavior on a clean IP | ~1500 reqs / 1h |
| T2 | Ramp rates 30/60/90/120/150 req/min, 10 min each | Per-token rate ceiling + whether infra trips at moderate rates | ~5000 reqs / 1h |
| T3 | Sustained ~25/min until first infra-429; log total-reqs and elapsed-time | Whether trigger is volume- or duration-based | up to 6-12h |
| T4 | One curl from Hetzner IP after T3 starts | Whether DC IP faces tighter threshold than residential NordVPN | ~5 reqs |
| T5 | **Once T3 trips**, run FIXED code locally against the live-tripped endpoint with `--detect-deletions` on a 100-post slice. Expect: 0 tombstones, N errors logged. | Whether the proposed fix actually prevents the corruption mode | ~100 reqs after limit hot |
| T6 | Unit test mocking 429-storm; assert `fetch_comments_only` raises | Regression test | offline, <1s |

T1-T5 don't touch the Hetzner IP or production token. T5 is the most decisive because it validates the fix on the exact failure mode (live infra-tripped endpoint).

### 7. Considered but skipped

- Probing all 324 hi-stratum posts. The signature is exact (frac == 1.0, no borderline) and the n=30 sample showed 100% recovery. Going from n=30 to n=324 doesn't change the remediation decision and burns API budget for no incremental certainty.

## Decisions and why

| Decision | Reasoning |
|---|---|
| Skip the "prove the 324 hi posts are all false-positive" probe; just refetch wide on remediation. | User: "I'm not collecting the content over time so there is nothing lost by just refetching them." Targeted clever logic costs design effort for no recoverability benefit. |
| Do not apply any code changes this session. | User: review the safeguards before writing them; verification tests (esp. T5) come first. |
| `tombstoned == in_db` is the exact rate-limit-corruption discriminator. | Bimodal frac distribution with zero posts in [0.6, 0.8) confirms the regime split is sharp; the empirical false-positive rate is 100% on the hi side and 0% on the lo+mid side. |
| Defer rate-limit mechanism characterization to T1-T4 with second token + NordVPN. | Session 26's "3 days of continuous traffic" hypothesis is one observation. Hourly histogram of tombstoning is inconsistent with it (intermittent, not single onset). Volume-based threshold is at least equally plausible. Sharding design will be informed by whichever threshold actually triggers in T3. |

## Files touched

- `CLAUDE/session_logs/2026_05_17_session_log.md` — this file
- `claude_handover.md` — rewritten as launchpad for session 30
- `claude_learnings.md` — enriched the session-26 entry with empirical findings; added note about posts-stage and submolts-stage analogous bug
- `claude_methodology_log.md` — appended row for the empirical false-deletion classifier (active discriminator for remediation)

No source code changes. No DB writes. Two probes on the VM (read-only SQL + 30 GET requests against the live API at <1 req/sec) and one re-fetch on the saved sample post — all within budget.

## Cleanup performed

- VM `/tmp/probe.py`, `/tmp/sample.sql`, `/tmp/strata_totals.py` — removed.
- Local `/tmp/probe.py`, `/tmp/sample.sql`, `/tmp/strata_totals.py`, `/tmp/affected_posts.tsv`, `/tmp/stratified_sample.tsv` — removed.
- No orphan python/sqlite processes on the VM.

## Rollback

No risky changes. All edits are documentation only and revert via `git checkout --` if needed.

## Open questions and next actions

All carried forward in the handover. Top-of-stack:

1. Decide whether to add the failing unit test for `fetch_comments_only` (T6) before doing T1-T5, or run probes first.
2. T1-T5 sequencing — once user is available with NordVPN running and willing to dedicate a probe day.
3. Apply the 3-piece safeguard once T5 validates the fix.
4. Then refetch sweep over 521 comment-affected posts + 6,428 deleted post IDs.
5. Sharding design informed by T3's threshold.
6. Then re-enable monthly cron.

The weekly cron fires Mon 2026-05-18 02:00 UTC and is structurally immune to the false-deletion bug (no `--detect-deletions` in its pipeline). No action needed before then; just observe completion as a sanity check.
