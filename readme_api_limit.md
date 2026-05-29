# API Rate Limit Investigation Log

**Purpose**: Document everything tried regarding rate limiting, what worked, what failed, and what was learned. Prevents re-trying failed approaches.

---

## ⚠️ REGIME CHANGE observed 2026-05-29 (session 30) — facts below are pre-change, see this block first

The live API now returns a **tiered, multi-window** rate-limit scheme behind **AWS CloudFront**, not the single-header `X-RateLimit-Limit: 60` per-token model documented below (confirmed 2026-03-06). This is a provider-side change (likely a re-platform). Full header set captured 2026-05-29 — **identical for authed and anon requests**:

```
x-ratelimit-limit-short:  30      reset 1        x-ratelimit-remaining-short
x-ratelimit-limit-medium: 600     reset 60       x-ratelimit-remaining-medium
x-ratelimit-limit-long:   10000   reset 300      x-ratelimit-remaining-long
x-ratelimit-limit:        200     reset <epoch>  (legacy/unsuffixed; was 60 on 2026-03-06)
via: 1.1 ...cloudfront.net (CloudFront);  x-amz-cf-pop: FRA60-P12
```

What changed vs the 2026-03 baseline: (a) single `X-RateLimit-Limit:60` → tiered `short/medium/long` + unsuffixed `200`; (b) infra layer Cloudflare/nginx → **CloudFront**; (c) anon==authed limits + shared reset epoch ⇒ likely **IP/global bucketing, not per-token** — so a second token may no longer bypass the app-layer limit (revisit block-A T1-T5 assumptions). Sequential ~25/min is still well under every tier, so **no immediate breakage**.

**Phase-0 characterization (2026-05-29, VM/prod IP — see 2026_05_29 log §5):** an 8-request spaced probe showed `short` (30/1s), `medium` (600/60s) and `long` (10000/300s) barely move at our rate; the binding app-layer limiter is the unsuffixed **`x-ratelimit-limit: 200` per ~60s window** (decrements 1/req, fixed-epoch reset, observed 10s-to-reset mid-window) — still ~8× our sequential ~25/min, so app-layer 429s are rare. 200-status responses carry **no `Retry-After`**. The real exposure remains the **headerless CloudFront/infra layer** (sustained-rate trips). **Mitigation applied:** `client.py:_request` now honors `Retry-After` on 429 (bounded by `MAX_BACKOFF_SECONDS=120`), falling back to exponential for headerless infra 429s; **no proactive throttling** (a documented dead-end — see §2/§3 above). **Still open:** *when* the regime changed (diff upstream/observatory `src/middleware/rateLimit.js`; possibly Meta-acquisition-related). Full detail: `CLAUDE/session_logs/2026_05_29_session_log.md` §2 + §5.

---

## Confirmed Facts (verified against live API) — PRE-2026-05-29 REGIME

### Application-level rate limit
- **60 req/min per API token** (confirmed via `X-RateLimit-Limit: 60` header on 2026-03-06)
- Source code (`src/middleware/rateLimit.js`) says 100/min, but **production config is 60/min**
- Identifier: `req.token || req.ip || 'anonymous'` — per-token for authenticated requests
- 1-minute sliding window; in-memory Map storage; cleanup every 5 minutes
- Response includes: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`

### Infrastructure-level rate limit (Cloudflare/nginx)
- Exists **in addition to** the application-level limit
- Rate-limits **by IP address**, not by API token
- **Does NOT return** `X-RateLimit-*` headers (this is how you distinguish it from the application limit)
- **Longer cooldown window**: persists for 15+ minutes after abuse stops (observed up to 3 min, confirmed cleared after 15 min)
- Triggered by sustained high request rates (observed after 540 req/min for 10+ hours)
- **Multiple API tokens from the same IP share this limit** — a second token does NOT bypass it
- **Changing IP (VPN, different machine) bypasses it** — confirmed by user with NordVPN

### Comment endpoint specifics
- `GET /posts/:id/comments?limit=500` — server hard cap is 500, default is 100
- `sort` parameter available (default: "top")
- No rate limiter on GET (reads); only POST (writes) have endpoint-specific limits
- Response time varies: 0.3-2s for light posts, potentially 20-60s for heavy posts (1000+ comments)

---

## What Was Tried (chronological)

### 1. Sequential scraping, no throttle (sessions 2-4, confirmed session 9)
- **Approach**: 1 worker, reactive exponential backoff on 429
- **Result**: ~25 req/min (limited by 2.4s network latency). Well under 60/min limit. No 429s.
- **Production validation (session 9)**: Full 4.7-day VM comments scrape completed 433,850 posts with only 8 errors and 63 rate-limits. Mop-up of 2,725 posts completed with 0 errors, 0 rate-limits. Agent enrichment of 7,160 profiles completed with 0 rate-limits at ~47/min. Sequential is the proven production approach.
- **Session 12 catch-up (local, 2026-03-13→15)**: Confirmed again at scale. Posts incremental: ~50 req/min (3,269 pages, 39 min, 0 errors). Comments (130K posts): ~130 posts/min over 16h, 0 errors, 0 rate-limits. Moderators (19.6K submolts): ~47/min, 7h, 0 errors. Enrich (7.2K agents): ~47/min, 2.5h, 0 errors. Comments throughput was notably higher (~130/min) than the VM session 9 run because the new posts have fewer comments on average (lightweight requests).
- **Status**: WORKED. This is the reliable baseline. Confirmed at scale across 3 separate multi-day runs.

### 2. Proactive sliding-window throttle (session 3)
- **Approach**: Added to `client.py` as middleware
- **Result**: Cold-start burst caused cascading 429 storms
- **Status**: REMOVED in session 4. Failed.

### 3. ThreadPoolExecutor + TokenBucket at 90/min (session 6)
- **Approach**: `--workers 4`, shared `_TokenBucket` at 90/min, capacity=9, `acquire()` called once per `_request()` (outside retry loop)
- **Result**: Initial burst (565 posts/min) was misleading; sustained rate dropped to 10.8/min for heavy posts. Thundering herd without bucket was worse (16 req/min). With bucket: ~43/min for fast endpoints (moderators).
- **Status**: PARTIALLY WORKED for fast endpoints. Failed for slow endpoints (comments).
- **Hidden bug**: 90/min exceeded the real 60/min production limit. We didn't know the production limit was 60/min until session 8.
- **Hidden bug**: `acquire()` outside retry loop meant retries bypassed the bucket; actual HTTP rate was up to 6x the bucket rate.

### 4. Increase workers to 16 (session 7-8)
- **Approach**: `--workers 16` to saturate the token bucket
- **Result**: Same or worse throughput (~10-15 posts/min). More workers = more contention for tokens = more clustered requests = more 429s.
- **Status**: FAILED. More workers does not help when the bottleneck is the rate limit, not response latency.

### 5. Token bucket capacity=1 (session 8)
- **Approach**: Reduce burst capacity from 9 to 1
- **Result**: No improvement. The burst wasn't the primary issue (it was the retry bypass).
- **Status**: Applied but insufficient alone. Correct in principle but didn't fix the core problem.

### 6. `acquire()` inside retry loop (session 8)
- **Approach**: Each HTTP attempt (including retries) consumes a token
- **Result**: Rate correctly limited, but with 16 workers competing for 55 tokens/min, each worker gets a token every ~17s. Combined with 429 retries consuming additional tokens, effective post rate dropped to ~10/min — **slower than sequential**.
- **Status**: Correct fix for the retry-bypass bug, but exposed the fundamental problem: concurrent workers competing for a limited token pool is slower than sequential when the rate limit is the bottleneck.

### 7. Rate limit reduced from 90/min to 55/min (session 8)
- **Approach**: Corrected default after discovering production limit is 60/min not 100/min
- **Result**: Still getting 429s. 10/min effective rate. Likely because the infrastructure-level IP limit was already triggered from previous abuse, and/or 16 workers with jitter still occasionally burst above 60/min.
- **Status**: Correct in principle but didn't solve the operational problem.

---

## Why Multi-Worker Is Slower Than Sequential (the core insight)

The sequential approach (1 worker, no token bucket) achieves ~25 req/min, limited by network latency (~2.4s per request). This is comfortably under the 60/min API limit, so no 429s occur. Every request succeeds on the first attempt.

The multi-worker approach with a token bucket aims for 55 req/min but in practice achieves ~10 req/min because:

1. **Token contention**: 16 workers compete for 55 tokens/min. Each worker waits ~17s between tokens.
2. **Clustering**: Despite the bucket, threads wake up in bursts (all sleeping the same duration), causing micro-bursts that trigger 429s.
3. **Retry cost**: Each 429 consumes an additional token (with the fix) or a free retry (without the fix). Either way, effective throughput drops.
4. **Silent failure**: `fetch_comments_only()` catches all exceptions and returns `[]`. 429s are invisible in the output — they look like posts with no comments.
5. **Infrastructure ban**: Sustained high request rates (even if application-level acceptable) trigger the infrastructure-level IP block, which persists for 15+ minutes.

**Bottom line**: For this API with a 60/min limit and 2.4s network latency, sequential is faster AND simpler than concurrent.

---

## Recommended Approach

### Single machine
Run sequential (1 worker, no token bucket). Default `--workers 1` already does this. Rate: ~25-130/min depending on comment density. Lightweight posts (few comments): ~130/min; heavy posts (500+ comments): ~25/min. Full corpus (~580K posts with comments): ~5-7 days on VM.

```powershell
.venv\Scripts\python -u -m src.cli comments --only-missing --skip-empty --db data/raw/moltbook.db --log-file logs/scrape-comments.log
```

### Parallel across machines/IPs (the correct way to parallelize)
Each machine gets:
- A **different IP address** (cloud VM, different VPN server, etc.)
- A **different API token**
- A **subset of post_ids** (split by rowid range)
- Runs **sequential** (1 worker)

This gives N × 25 req/min with no contention, no 429s, and no complexity. Two machines = 50 req/min = ~6 days. Three machines = 75 req/min = ~4 days.

The DB's UPSERT design means results can be rsync'd together safely.

### What NOT to do
- Do NOT use `--workers > 1` — it is slower, not faster, for this API
- Do NOT raise `--rate-limit` above 55 — production limit is 60/min
- Do NOT run multiple scrapers from the same IP — infrastructure blocks by IP
- Do NOT run multiple scrapers with different tokens from the same IP — same result

---

## IP vs Token Rate Limiting Summary

| Layer | Identifier | Limit | Cooldown | Headers |
|-------|-----------|-------|----------|---------|
| Application (`rateLimit.js`) | API token | 60/min | 1 minute | Yes (`X-RateLimit-*`) |
| Infrastructure (Cloudflare/nginx) | IP address | Unknown | 15+ minutes | No |

**How to tell which one blocked you**: If the 429 response includes `X-RateLimit-Limit` header → application layer. If no rate limit headers → infrastructure layer.

---

## Open Questions

1. What is the exact infrastructure-level rate limit (requests/min per IP)? We know it's above 25/min (sequential works) and below 540/min (triggered the block). Likely in the 60-200/min range.
2. Does the infrastructure limit have a separate cooldown period, or is it the same 1-minute window? Evidence suggests a longer window AND that the window scales with abuse magnitude. **2026-03 (session 8): ~10 h of 540 req/min bursts → ≥ 15 min cooldown.** **2026-05-08 (session 26): 3 days of continuous sustained traffic → ≥ 32 min cooldown still active when re-probed after SIGTERM.** Mapping the actual long-window after a multi-day run is an open task — see `CLAUDE/session_logs/2026_05_08_session_log.md` "Open threads".
3. Is there a per-IP daily/hourly quota in addition to the per-minute limit?
