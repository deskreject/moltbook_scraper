# Session 7 — 2026-03-05 — Comments Throughput Diagnosis & API Audit

**What was done:**
- Moderators scrape completed (13,741 rows, 13,645 submolts with mods)
- Comments scrape launched with `--workers 4`: only 10.8 posts/min because heavy posts queued first (22s/req)
- Audited Moltbook API source: confirmed global 100 req/min per token (but production is 60 — discovered next session)
- Comment limit is 500 (not ~200); updated `fetch_comments_only()` to pass `limit=500`
- Added `--rate-limit RPM` CLI flag and `-u` unbuffered stdout for background runs
- Restarted with `--workers 16`: 19,646 posts done, 434,063 remaining (~3.3 days)

**Key decisions:**
- Do NOT auto-start enrich after comments — assess VM / second API token first
