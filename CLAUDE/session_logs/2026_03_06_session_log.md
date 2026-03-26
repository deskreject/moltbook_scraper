# Session 8 — 2026-03-06 — Rate Limit Root Cause & VM Deployment

**What was done:**
- Diagnosed 3 compounding bugs in 16-worker comments scrape (zero data overnight):
  1. Token bucket capacity=9 allowed burst spikes
  2. `acquire()` outside retry loop — retries bypassed bucket (6x actual HTTP rate)
  3. Rate set to 90/min vs real production limit of 60/min (`X-RateLimit-Limit: 60`)
- Discovered infrastructure-level IP rate limiting (Cloudflare/nginx, 15+ min cooldown)
- Deployed Hetzner CX23 VM (Nuremberg, ~0.43/day): sequential mode, zero 429s
- ExtraE113/moltbook_data has only ~165K posts (9%) due to offset-based pagination

**Core insight:** Sequential (1 worker, no token bucket) at ~25 req/min is 2.5x faster than concurrent. Correct parallelism is across machines/IPs, not threads. Full details in `readme_api_limit.md`.
