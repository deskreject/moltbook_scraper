# Session 30 — 2026-05-29

Machine-switch startup → three threads: (1) diagnosed why the May 25 weekly ran ~half the time of May 18; (2) discovered the Moltbook API rate-limit regime has **changed** (new tiered scheme + CDN migration) and framed it as a prioritized investigation; (3) ran a first-pass variance/format assessment of the change-based panels (the project's claimed comparative advantage over the Observatory). No source-code changes. Doc edits only: CLAUDE.md runtime note, readme_api_limit.md observation, handover + methodology log.

## Context at start

Startup spot-check vs handover (session 29, 2026-05-17) all matched: weekly+disk cron active, monthly disabled, API 200, counts grown (posts 3,084,737 / comments 5,991,314). Two weeklies fired while away (May 18, May 25), both `SUCCESS, 0 errors`. **Note: session-29 doc work is still uncommitted locally** (git HEAD = session 28; working tree carries sessions 29 + 30 edits). Commit before any real machine switch or it strands.

## 1. Weekly runtime "halving" — RESOLVED, benign

User flagged May 25 (20.6 h) ≈ half of May 18 (43.3 h). Per-stage decomposition from `logs/cron.log` + `weekly-YYYY-MM-DD.log`:

| Stage | May 4 | May 11 | May 18 | May 25 |
|---|---|---|---|---|
| comments | 6.7 h | **21.5 h** | 8.5 h | 5.3 h |
| moderators | 9.2 h | 11.5 h | **31.4 h** | 11.8 h |
| (other 4) | ~0.8 h | ~7.4 h | ~3.0 h | ~3.0 h |
| **Total** | **19.5 h** | **40.6 h** | **43.3 h** | **20.6 h** |

The "halving" is an artefact of choosing May 18 as the reference. **May 25 (20.6 h) ≈ May 4 (19.5 h) is the true steady state.** The two intervening runs were elevated by two *unrelated, both-resolved* causes:

- **comments** — monotonic drain (21.5→8.5→5.3 h) of a post-incident backlog. The May 5 monthly's `comments-full` stage errored out 2026-05-08, leaving ~111k posts with un-fetched comments. Queue at run start: May 11 = 110,953 → May 18 = 41,809 → May 25 = 37,938 posts. **Today the backlog is 24 posts** (drains to ~0 each run). Stored-comments/post is flat ~4.5 across all three runs, 0 errors. → genuine work, not silent skip.
- **moderators** — May 18 hit multi-hour intermittent stalls (one 100-submolt batch took ~3 h; mod-yield/batch collapsed during stalls) = classic 429/backoff signature (matches session-27 "slow-batch pauses" + session-29 "intermittent infra-429"). Self-recovered, full 31,088 submolts walked, 0 errors. May 11 (11.5 h) and May 25 (11.8 h) are the clean baseline.

**Silent-skip ruled out at source level**: the weekly comments path (`only_missing=True, skip_empty=True`) defines its queue as `get_post_ids_without_comments_with_activity()` = `comment_count>0 AND no comment rows`. A rate-limited `[]` (block-A swallow) writes nothing and sets **no "done" flag** → the post stays queued and is retried next week. Worst case = *deferral*, never *drop*. The queue draining to ~0 via real stored comments confirms completeness. This is also why the weekly is structurally immune to the May-5 corruption class.

→ Closed operational TODO #1 (runtime budget). CLAUDE.md Quick Commands now documents ~20 h steady state + moderators-spike behaviour. The 8-10 h figure existed only in the handover TODO text, never in CLAUDE.md.

## 2. API rate-limit regime has CHANGED — PRIORITIZED INVESTIGATION (framed, not executed)

While probing API health I noticed `x-ratelimit-limit-short: 30`, which doesn't match the documented "60/min per token". Full current header set (authed AND anon — identical):

```
x-ratelimit-limit-short:  30      reset 1
x-ratelimit-limit-medium: 600     reset 60
x-ratelimit-limit-long:   10000   reset 300
x-ratelimit-limit:        200     reset <epoch>      (legacy/unsuffixed)
via: ...cloudfront.net (CloudFront);  x-amz-cf-pop: FRA60
```

**This is NEW, provider-side — not previously-hidden info.** Evidence the historical record gives us:
- `readme_api_limit.md` (confirmed 2026-03-06, and 2026_03_06_session_log.md line 7) recorded a **single** `X-RateLimit-Limit: 60` header — no `short/medium/long` tiers, and the unsuffixed value was 60, now **200**.
- Infra layer was documented as **Cloudflare/nginx**; it is now **AWS CloudFront** → a CDN/infrastructure migration.
- Anon and authed requests return identical limits and the same reset epoch → suggests **IP/global bucketing**, whereas the documented model was **per-token** (60/token). This may mean the second-token strategy (block-A T1-T5) no longer helps the way assumed.

The change is consistent with (but does not prove) the user's "META acquired Moltbook → re-platformed" hypothesis. To pin down *when/why* (next time): (a) check Moltbook API changelog / docs via `python -m src.cli docs` and diff vs stored `docs/`; (b) diff the upstream/cloned server repo + the "moltbook observatory" repo for changes to `src/middleware/rateLimit.js` (readme_api_limit.md already cites this server-side file — the cleanest source-of-truth if the repo is available); (c) web-search Moltbook/Meta API changes.

**Robustness exposure (why this matters for weekly + monthly):**
- `client.py:_request` uses **pure fixed exponential backoff** (`base_delay · 2^attempt`); it does **NOT** parse `Retry-After` or any `X-RateLimit-*` header. The scraper is blind to the new tiers — it can neither respect the server's signalled cooldown nor proactively throttle on `*-remaining-*`.
- Combined with the block-A swallow (`fetch_comments_only`/`fetch_posts_streaming` eat `RateLimitError`), rate-limit events are both **invisible** and **improperly backed off**. A tighter/short-window limit ⇒ more 429s ⇒ (weekly) more deferred posts; (monthly w/ `--detect-deletions`) more false tombstones. So the new regime *raises* the urgency and *reshapes the design* of the block-A safeguard.
- Sequential ~25/min is still comfortably under every new tier at the application layer, so **no immediate breakage** — current data integrity is fine. The risk is mischaracterized limits feeding into block-A probe design and safeguard sizing.

**Where it slots in the handover (assessment):** as **step 1.5 of block A — a precursor to / merge with T1-T5**. Rationale: T1-T5 were designed to *empirically characterize a presumed single limit*; we now know the headers expose explicit tiers + a new identifier model + new CDN, so (i) the probes should be redesigned to read/validate the tiered headers rather than ramp blind, and (ii) the safeguard (header-aware backoff that honours `Retry-After`/`*-remaining-*`) should be scoped against the real regime. Cheap to start (header probes already half-done). Does not block T6 (the offline regression test), which can still go first.

## 3. Side-quest — value & format of the change-based panels (first-pass)

Premise under test: the project's edge over the Observatory is the change-driven data. Practically, does it have enough *within-entity variance* to support dynamics research, and is the format right?

**Panel richness (live DB):**

| Table | entities | rows | changers (≥2 obs) | % | max obs |
|---|---|---|---|---|---|
| post_metrics (upvotes/downvotes/comment_count) | 657,125 | 667,204 | 10,078 | **1.5%** | 3 |
| agent_metrics (karma/follower/following) | 179,919 | 190,458 | 4,204 | **2.3%** | 6 |
| submolt_metrics (subscriber_count) | 31,407 | 32,273 | 655 | **2.1%** | 5 |

- Only **6 scrape runs, spanning 2026-04-30 → 2026-05-25** (~4 weeks; the change-driven writer started at Phase 3/4). **~98% of entities have exactly ONE observation** → the panels are currently near-cross-sectional, not longitudinal.
- **Where change exists, the signal is real and high-variance**: of 4,204 agents with ≥2 obs, 3,645 moved karma — avg spread 239, **max 237,757** (heavy-tailed, genuine dynamics); 3,078 moved followers (avg 7, max 427).
- **Events**: post_events = is_spam 286,009 / is_deleted 6,429 / is_pinned 48 / verification_status 8. `is_deleted` ≈ the 6,428 May-5 deletions (real). **`is_spam` = 286k flagged anomalous** (~10% of posts; vs 48 pinned) — diagnosed in the cheap-reads phase below. `agent_events = 0` flagged for probe. **Correction:** `submolt_events = 0` is **by design, NOT a bug** — `_snapshot_submolts` (scraper.py:677) tracks only a subscriber_count metric and writes no events (submolts have no tracked boolean fields). `moderator_events` = 30,579, all "added" (Migration-10 baseline).

**Assessment:**
- *Format is fundamentally right* — tidy event-sourced panels (entity, scraped_at, run_id, value cols) + transition event log (event_type/old/new). Storage-efficient, analysis-friendly.
- *Practical value is currently THIN but accruing*: too young (6 runs) to yet be the comparative advantage; it gains ~1 obs/entity/week and will mature. The premise is sound in principle, premature in practice as of 2026-05-29.
- *Two format/scope concerns to revisit*: (i) the **4-week post-metrics age cutoff + weekly cadence** caps a post's vote trajectory at ~4 points — likely too sparse if the research question is early-vote dynamics; reconsider cadence/cutoff. (ii) **Event-writer correctness must be fixed first** (is_spam flood, agent/submolt events = 0) or the events tables are not research-usable regardless of format.

## Files touched

- `CLAUDE.md` — Quick Commands weekly-cron comment: accurate stage list + ~20 h runtime + moderators-spike note (resolves operational TODO #1 / the stale runtime figure).
- `readme_api_limit.md` — appended 2026-05-29 observation: new tiered scheme + CloudFront + full header dump + anon==authed + client-doesn't-parse-headers.
- `claude_handover.md` — slotted the rate-limit investigation as block-A step 1.5; annotated runtime TODO resolved; added change-based-data follow-up.
- `claude_methodology_log.md` — row: API rate-limit regime change observed 2026-05-29 (provenance).
- this session log.

No source-code changes. No DB writes. Read-only SQL + a handful of GET probes against the live API.

## 4. Cheap-reads diagnostics phase (2026-05-29, cont.)

User reviewed the 3-goal plan (monthly reinforce / weekly rate-limit robustness / change-based value) and chose: **start with cheap reads (T6 + Phase-4 probes); circuit-breaker before sharding for monthly; third scraper analysis-gated.** Full plan in this session's chat; executed the cheap, zero-risk reads:

### T6 written (step 4)
`tests/test_client.py::TestFetchCommentsOnlyRateLimit::test_raises_ratelimit_error_instead_of_returning_empty` — asserts `fetch_comments_only` *raises* `RateLimitError` under a 429 storm (it currently returns `[]`). Marked `xfail(strict=False)`; passes (becomes the standing regression guard) once Phase-1 re-raise lands — remove the marker then. Verified: `1 xfailed in 0.05s`. (Ran scoped to the class — the bare-`pytest` hang lives in `test_fetch_all_posts_paginates_until_no_more` in the same file.)

### Event-writer diagnoses (steps 15-16)
- **`is_spam` flood = anchor artifact, not signal.** All 286,009 events are `0→1`, exactly one per post, and **286,004 landed in scrape_run_id=4 = 2026-05-08** — the May-5 monthly's snapshot pass after its full posts walk. Mechanism: `is_spam_first` anchors were set (Migration 10, 2026-04-20) from a stale/under-populated `0`; the monthly full scrape wrote the true `is_spam=1` via `upsert_post` (`is_spam = excluded.is_spam`, no COALESCE), and the writer emitted a one-time `0→1` for each. These are **measurement-catch-up artifacts, not real-time flaggings** — must be excluded from any "when did post X become spam" analysis. (Open: sample the live API to confirm these posts really are spam now vs. a mis-write — likely real-state, artifactual-timing.)
- **`agent_events = 0` is genuine + a minor latent gap.** Zero agents diverge from anchor (`is_claimed != is_claimed_first` → 0). is_claimed is near-static: 177,911 claimed/anchored-claimed, only 237 unclaimed. `upsert_agent` *does* update is_claimed (COALESCE, not frozen), so true transitions would be caught — there just are ~none in-window. Latent bug: **1,771 agents have `is_claimed=1` with NULL anchor**, and the writer skips NULL anchors, so they can never emit. Low priority (is_claimed is a low-variance field).
- **Conclusion for goal (c):** the boolean event log is **low research value** (is_spam artifact, is_claimed static, is_pinned/verification tiny; is_deleted is the only useful one). The change-based comparative advantage rests on the **numeric metric panels**, not events.

### Value-locating analysis (step 17) — GREEN LIGHT for a young-post pulse
Quantified the weekly-cadence blind spot for vote dynamics:
- **Age at first metric observation** (657k posts): only 0.6% observed at <1 d, ~5% within 2 d; median first-obs age ≈ **5-6 days** (largest bucket 4-7 d = 179k; 30% first seen at >14 d, backfilled old posts).
- **Among the 10,078 ≥2-obs posts** (the movers): **89.3% of final upvotes are already present at first observation**; only **+1.3** upvotes accrue afterward. Comments differ — they keep growing (avg **+13.3** after first obs), so weekly captures late comment dynamics but misses the early vote/score burst.
- **Verdict:** the early vote/score velocity (days 0-7, where hot-score decay and the interesting dynamics live) is **structurally invisible** at weekly cadence — first observation is too late and the action is over. This is a real, measured value gap → a lightweight **young-post pulse** (daily / 2×-day, only posts ≤7-14 d old, change-driven into existing `post_metrics`, keep 4-week cutoff) would unlock it at bounded cost (single-digit MB/month). Recommend proceeding to design it (Phase 4 step 18).

### Files touched (cont.)
- `tests/test_client.py` — T6 xfail regression guard (+import RateLimitError).
- this log + handover + methodology (is_spam-artifact row).

## Next actions (delta vs session-29 handover)

1. Commit sessions 29 + 30 docs (currently uncommitted).
2. Block A unchanged except **new step 1.5**: characterize the new tiered rate-limit regime (read headers, find when it changed, redesign T1-T5 around it, make backoff header-aware). T6 can still go first.
3. Event-writer correctness sweep (is_spam flood + agent_events/submolt_events = 0) — was operational TODO #2; now also gates the change-based-data research value (§3).
4. Decide whether the 4-week post-metrics cutoff / weekly cadence is adequate for the intended dynamics analysis.
