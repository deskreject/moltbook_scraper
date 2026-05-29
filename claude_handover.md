# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-29, session 30.

> **Session-30 deltas** (full detail in `CLAUDE/session_logs/2026_05_29_session_log.md`): (a) weekly runtime "halving" investigated → benign, May 25 (~20 h) is steady state; nothing skipped. (b) **API rate-limit regime changed** (tiered scheme + CloudFront) — new block-A step 1.5. (c) change-based panels assessed — currently thin (~98% single-obs), format sound. Spot-check below still valid; counts have grown.

> Provenance: claims tagged `[verified]` were checked against current state in this session; `[planned]` is agreed direction without implementation. Re-tag rather than copy-forward.

---

## Current state

[verified 2026-05-17]

- **Weekly cron is structurally immune** to the May 5 bug class. Weekly uses `comments --only-missing --skip-empty` (no `--detect-deletions`), so even if rate-limit trips during a weekly, no comments can be tombstoned — `_detect_deleted_comments` is never reached. Next weekly fires Mon 2026-05-18 02:00 UTC and is expected to succeed without intervention.
- **Monthly cron remains DISABLED on VM.** Crontab line still commented out (since 2026-05-08); backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`. Do NOT re-enable until: (a) the three code safeguards land, (b) T5 (live-rate-limit-validation) confirms the fix prevents corruption, (c) submolt-letter sharding is implemented.
- **DB**: 7.9 GB working copy / 99 GB volume / 24 % used / 72 GB free. Two backups: May 11 weekly (7.4 GB) + May 5 monthly-post (7.4 GB) = 14.8 GB.
- **API**: healthy (200/200 per-token at last probe, no infra-limit recurrence).
- **May 5 corruption empirically characterized.** 4,126 comment tombstones across 521 posts split bimodally into 324 false-positive posts (1,533 wiped comments, all alive in live API per n=30 sample) + 197 partial-deletion posts (2,593 tombstones, all genuine per same sample). The classifier `tombstoned == in_db AND in_db > 0` cleanly isolates the false-positive set. Details in `CLAUDE/session_logs/2026_05_17_session_log.md`.
- **Same bug class discovered in posts-stage path.** `fetch_posts_streaming` swallows `RateLimitError` into a consecutive-errors counter and silently breaks the loop after 10. The 6,428 May 5 post deletions may include false positives from pagination dying near end-of-walk. Severity bounded by the small total; remediation via wide refetch sweep, same approach as comments.

## Spot-check on return

```bash
date -u
ssh vm 'crontab -l | grep -E "weekly|monthly|disk"'
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'curl -is "https://www.moltbook.com/api/v1/posts?limit=1" | head -8'
ssh vm "sqlite3 /root/moltbook_scraper/data/raw/moltbook.db 'SELECT COUNT(*) FROM posts; SELECT COUNT(*) FROM comments;'"
```

Expected:
- Crontab: weekly + disk-monitor active; the `55 1 * * 2 ... monthly_rescrape.sh` line is commented out.
- Backups dir: May 18 weekly (7.4-7.6 GB, new) + May 5 monthly-post (7.4 GB). The May 11 weekly will have been pruned at the end of the May 18 weekly's run.
- Curl: HTTP 200 with `x-ratelimit-*` headers present. If 429 with no headers, infra limit re-tripped — diagnose against session 26 recognition signature.
- Counts: posts ≥ 2,939,474 / comments ≥ 5,629,305 (will have grown by one weekly's worth).

## Next actions (in priority order)

Sequencing per user signoff at end of session 29; **new step 1.5 added session 30** (rate-limit regime change).

1. **Decide whether to add the failing unit test (T6) for `fetch_comments_only` before T1-T5 probes, or run probes first.** T6 is offline, < 1 minute, requires no API budget — could be the cheap-and-fast first move. T1-T5 need a probe day with NordVPN running.

1.5. **[NEW — session 30] Characterize the changed API rate-limit regime BEFORE redesigning T1-T5.** As of 2026-05-29 the API returns a tiered `short/medium/long` limiter (30 / 600 / 10000) + unsuffixed 200, behind **AWS CloudFront** (was single `X-RateLimit-Limit:60` per-token behind Cloudflare on 2026-03-06). Anon==authed ⇒ likely IP/global bucketing, which may invalidate the "second token bypasses the app limit" premise underlying T1-T5. This reshapes block A: (a) redesign T1-T5 to read/validate the tiered headers rather than ramp blind; (b) make `client.py:_request` header-aware (honour `Retry-After` / `*-remaining-*` — currently pure fixed backoff, parses no headers) as part of the safeguard; (c) establish *when/why* it changed (Meta-acquisition?) via `cli docs` diff, upstream + observatory `src/middleware/rateLimit.js` diff, web search. Cheap to start. Full context + header dump: `readme_api_limit.md` top block + `CLAUDE/session_logs/2026_05_29_session_log.md` §2.

2. **T1-T5 verification probes using the second API token + NordVPN.** **Redesign per step 1.5 first.** Full (pre-regime-change) plan in `CLAUDE/session_logs/2026_05_17_session_log.md` §6:
   - T1: baseline ~25/min from NordVPN+token2 for 1h — confirms per-token behavior on clean IP.
   - T2: ramp rates 30/60/90/120/150 req/min, 10 min each — maps per-token ceiling.
   - T3: sustained ~25/min until first infra-429 — characterizes the volume/duration trigger. Run as overnight background probe.
   - T4: one curl from Hetzner IP once T3 trips — detects DC-IP-vs-residential reputation differential.
   - T5: **once T3 trips**, run the FIXED code locally against the live-tripped endpoint with `--detect-deletions` on a 100-post slice (using a copy of the prod DB or a small test DB). Expect: 0 tombstones written, N errors logged. **This is the decisive test that validates the fix on the exact failure mode.**

3. **Apply the three-piece safeguard.** ~10 lines total:
   - `client.py:fetch_comments_only`: re-raise `RateLimitError`, return `[]` only for non-rate-limit exceptions.
   - `client.py:fetch_posts_streaming` (+ `fetch_submolts` for symmetry): re-raise `RateLimitError` instead of swallowing.
   - `scraper.py:_detect_deleted_comments`: defensive guard — refuse to tombstone when `api_comment_ids` is empty AND `existing_ids` is non-empty.

4. **Refetch sweep over the 521 comment-affected posts + the 6,428 deleted post IDs.** Per user: no content is collected over time, so the simplest path is to just wide-refetch everything affected — no clever subset-targeting needed. The `tombstoned == in_db` discriminator is documented as the precision tool if needed; the wide approach is cheaper to implement.

5. **Implement submolt-letter sharding** (A-H / I-P / Q-Z). Methodology log entry from 2026-04-20. Threshold informed by T3's measured trigger value.

6. **Re-enable monthly cron.** Uncomment the `55 1 * * 2` line; verify with `crontab -l`.

## Observatory comparison — follow-up TODOs

[from session 28, 2026-05-12] Context in `CLAUDE/session_logs/2026_05_12_session_log.md`. Low-cost probes independent of block A.

0. **[session 30 — value-locating analysis DONE, log §4] Young-post pulse scraper: GREEN LIGHT.** The change-based edge is the **numeric metric panels** (events are low-value — see item #2). Measured weekly-cadence blind spot: posts are first observed at median age ~5-6 d, and among multi-obs posts **89.3% of final upvotes are already present at first observation** (only +1.3 accrue after) — so early vote/score velocity (days 0-7) is structurally invisible at weekly cadence. Comments differ (keep growing, +13.3 after first obs). **Recommended Phase-4 step 18:** a lightweight pulse (daily or 2×/day) sampling only young posts (≤7-14 d), change-driven into existing `post_metrics`, keeping the 4-week cutoff → bounded ~single-digit MB/month, trivial under the new rate-limit tiers. Decide cadence + whether to extend the cutoff for the young subset. Re-run the §3 richness queries periodically to track panel maturation.

1. **500 vs 1000 comment cap probe** — direct API test vs `readme_api_limit.md` claim. Backtrace why we settled on 500 first.
2. **2-min polling-window adequacy** — SQL over `posts.created_at` 2-min buckets ≥ 50 posts (Observatory miss-rate bound).
3. **Posts content-deduplication sanity check** — `(agent_id, title, content, created_at)` collision check.
4. **`/agents/profile` follower-list probe** — single curl to inspect for array vs counts.

## Operational TODOs from May 11 weekly run

[from session 28, 2026-05-12] Unchanged this session.

1. ~~**Weekly runtime budget reassessment**~~ **[RESOLVED session 30]** — steady state is ~20 h (May 4: 19.5 h, May 25: 20.6 h), not 8-10 h; the 40 h runs (May 11/18) were a post-incident comments backlog + a one-off moderators rate-limit stall. CLAUDE.md Quick Commands updated. See session-30 log §1.
2. **Event-writer findings [diagnosed session 30 — see log §4]** — mostly resolved, two small follow-ups remain:
   - `is_spam = 286,009`: **anchor artifact, not signal.** All `0→1`, one per post, 286,004 in run 4 (= the 2026-05-08 monthly snapshot pass); stale `is_spam_first=0` anchors met the monthly full scrape's true `is_spam=1`. **Action:** exclude run-4 is_spam events from analysis; harden anchor-setting so anchors are only taken from a trusted/complete observation (prevents recurrence on the next monthly). Optional: verify a sample against live API (real-state vs mis-write).
   - `agent_events = 0`: **genuine** (is_claimed near-static; `upsert_agent` does update it). Minor latent bug: **1,771 agents have `is_claimed=1` + NULL anchor** → writer skips NULL anchors so they can never emit. Low priority.
   - `submolt_events = 0`: **by design** (no submolt event writer) — not a bug; earlier note corrected.
   - Net: the boolean event log is low research value; the change-based edge is the **metric panels** (see item #0).
3. **Enrich-stage 311 errors investigation** — persistent (same agents fail every weekly = stale records) vs transient (network blips).
4. **`status.sh` + `weekly_scrape.sh` reporting bugs**:
   - Disk-free wrong-mount: confirmed in session 29 spot-check. `df -h /` returns 29 GB (system disk); script should `df -h /mnt/HC_Volume_104999576`.
   - `DB size: 0` from `du` on symlink.
   - ~5-10 lines, one pass.

## Known issues / open threads

### Slow-batch pauses in comments stage
[observed 2026-05-11, session 27] Distinct from session-26 rate-limit signature — `pwrite64`/`fdatasync` dominated, not `clock_nanosleep`/`poll`. Likely WAL-checkpoint stall at current DB size. Not actionable on its own.

### Apr 1 monthly silent-death
[blocked since 2026-05-08] OOM-during-`sqlite3 .backup` on 22 GB DB hypothesis is consistent with Phase 4 having resolved it (May 5 monthly got past the backup line before the comments-stage corruption began). Will be re-tested when next monthly fires.

### Pytest hang
[verified 2026-04-21] `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.

---

## Resuming after absence

1. Run §Spot-check above.
2. The May 18 weekly will already have completed (Mon 02:00 UTC + 1-2 days runtime). Verify success via VM logs.
3. Block A work is paused at "user signoff before further action." Next move depends on user's call: T6 first (cheap regression test) or T1-T5 (probe day with NordVPN).
4. The empirical false-deletion classifier and the posts-stage analogous bug are both documented in session 29 log; do not re-derive them.
5. Three follow-up TODO blocks (Observatory comparison, Operational, Known issues) are unchanged from session 28 and remain independent of block A — can be picked up in any order without blocking it.

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
