# Session 6 — 2026-03-03 — Three-Stage Speed Optimization

**What was done:**
- `--skip-empty`: skips 1.29M zero-comment posts (74% of corpus), reducing comment requests 3.7x
- `fetch_comments_only()`: drops redundant `GET /posts/{id}`, only calls `/posts/{id}/comments` (~1.7x speedup)
- `--workers N`: `ThreadPoolExecutor` with shared `_TokenBucket` rate limiter (90 req/min when N>1), DB writes in main thread
- All changes backward-compatible (`max_workers=1` default)
- Posts scrape complete: 1,742,447 posts

**Key learnings:**
- Without token bucket, 4 workers caused thundering herd (16 req/min — worse than 1 worker)
- With bucket: ~43 req/min for fast endpoints (moderators)
- Moderators scrape launched with `--workers 4`
