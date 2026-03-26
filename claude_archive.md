# Claude Archive - Moltbook Scraper

Synthesized records of completed work from previous sessions. See `claude_handover.md` for current state.

---

## 2026-03-26 (session 15) — VM health check, email fix, swap fix

VM weekly Mar 23 ran as partial failure: stages 1-5 succeeded, snapshots OOM-killed (3.5 GB RSS on 3.7 GB VM). Fixed email alerts (EMAIL_TO assigned before .env sourced — cron has no env vars). Added 4 GB persistent swap as temporary OOM fix. Verified all 5 upstream schema gaps are real and not yet addressed. Updated gitignore to whitelist `claude_learnings.md`, `claude_methodology_log.md`, and `CLAUDE/**/*.md`.

## Methodology log entries archived 2026-03-26

Entries removed from active methodology log — now historical facts baked into code:
- DB path `data/raw/moltbook.db` (established session 2)
- UTF-8 encoding for Windows file I/O (fixed session 2)
- Upstream remote for drift detection (active but routine)
- Proactive rate throttle removed (caused 429 storms, session 4)
- PowerShell daily_scrape.ps1 (active but established)
- Comment cap revisions (settled at 500, session 7)
- HPC approach superseded by Hetzner VM (session 6)
- Platform launched ~Jan 15 2026 (historical fact)
- DB portable via rsync/UPSERT design (established)
- `--skip-empty`, `fetch_comments_only()`, `--workers N` optimizations (all baked into code, sessions 6-7)
- Token bucket capacity=1.0 requirement (baked into code)
- Sequential vs concurrent throughput analysis (settled)
- Hetzner VM selection, agent enrichment count, ExtraE113 comparison (historical)
- All scraping stages complete as of session 9
- `--only-missing` for enrich (baked into code)
- Weekly ~8-10h duration, comments throughput variance (operational facts)
- `find` vs `ls glob` under `set -e` (baked into status.sh)
- SSH config alias setup (infrastructure, one-time)

## 2026-03-20 (session 13) — Cron fix, upstream audit, health check

Discovered weekly cron silently failed since Mar 17: Ubuntu 24.04 has no `python` binary (only `python3`), so all scraper stages exited immediately. Fixed both `weekly_scrape.sh` and `monthly_rescrape.sh` to use `$PYTHON="$SCRAPER_DIR/.venv/bin/python"`. Pushed fix to VM and verified with manual incremental (+18,040 posts, 7-day gap). Audited upstream repo (`daveholtz/moltbook_scraper`): only 1 commit since fork (`787f2d9`). Most changes (cursor pagination, page-based submolts, `_normalize_agent`, schema migrations) already implemented independently. Actual gaps: `claimed_by` field on agents, 4 submolt fields (`creator_id`, `post_count`, `is_nsfw`, `is_private`), `enrich_submolts()` method, COALESCE fix on submolt upsert. Email alerts confirmed working by user. Next real weekly: Mon Mar 23 02:00 UTC.

## 2026-03-13→16 (session 12) — 10-day catch-up scrape + Hetzner VM setup

Catch-up scrape for 10-day gap (Mar 3 → Mar 13) ran locally (user approved since <1 day). All 6 stages completed with 0 errors across ~26 hours total. Incremental: +326,541 posts (39 min, ~50 req/min), DB now 2,068,988 posts (~100% of platform). Submolts: 19,593 refreshed (~10 min). Comments: +366,589 from 130,414 posts (~16h, ~130 posts/min), DB now 3,177,832 comments. Moderators: 18,769 total from 19,593 submolts (~7h, ~47/min). Enrich: +4,005 agents (~2.5h), DB now 171,003 agents. Snapshots: all tables snapshotted (2 min). Platform stats at start: 2,863,666 agents, 19,594 submolts, 2,070,859 posts, 13,336,777 comments. Key finding: weekly scrape takes ~8-10h not ~1-2h (moderators ~7h is bottleneck at ~47/min for 19.6K submolts). Hetzner VM setup (2026-03-16): pushed 9.9 GB DB + code, installed sqlite3 + msmtp + dos2unix, set up cron jobs (weekly Mon 02:00 UTC, monthly 1st 02:00 UTC), created SSH config alias `vm`, fixed status.sh bugs (glob expansion under `set -e`, grep -c whitespace). SSH: `ssh vm` → `root@159.69.34.240`. Remaining: user to fill Gmail app password in `/root/.msmtprc` and set `MOLTBOOK_ALERT_EMAIL` in `.env`.

## 2026-03-13 (sessions 10-11) — Schema migrations, deletion detection, automation cadence

Session 10 (2026-03-12) was interrupted mid-implementation and completed as session 11 (2026-03-13). Added schema migrations for new API fields not previously captured: posts (type, is_locked, is_spam, verification_status, updated_at, score, hot_score), comments (is_spam, depth, reply_count, verification_status, updated_at, score), agents (display_name, posts_count, comments_count, is_active, is_verified, last_active, deleted_at). Corresponding snapshot table migrations added so snapshots capture the new columns. Updated `upsert_agent()` and `upsert_comment()` to persist new fields using COALESCE to avoid overwriting enrichment-only data with NULL from partial updates. Added deletion detection: `mark_posts_deleted()` DB method + `scrape_posts(detect_deletions=True)` tracks all seen IDs during full pagination and marks unseen posts; `enrich_agents()` now catches 404 responses and sets `deleted_at`; `--detect-deletions` CLI flag wired for both `posts` and `comments` commands. Created three automation scripts for Hetzner VM: `weekly_scrape.sh` (incremental + comments + enrich + snapshots, Mon 02:00 UTC cron, lock file, DB backup, email alerts, keeps last 2 backups), `monthly_rescrape.sh` (full re-scrape with deletion detection, 1st of month 02:00 UTC, pre/post backups, email on start/fail/complete), `status.sh` (dashboard showing DB size, row counts, disk usage, backups, cron jobs, recent errors).

## 2026-03-11 (session 9) — Scraping complete, DB finalized, snapshots created

Comments scrape on Hetzner VM completed cleanly on 2026-03-10 21:13 UTC after ~4.7 days: 433,850/433,855 posts processed, 2,066,042 comments, 8 errors, 63 rate-limits. Mop-up pass recovered 29,918 additional comments from 2,725 posts missed in first run (0 errors); 167 posts remain unreachable (API returns empty despite `comment_count > 0` — stale counts from deleted comments, not a scraper bug). Agent enrichment: added `--only-missing` flag and `get_unenriched_agent_names()` DB method to avoid re-fetching all 166K agents (~111h) when only 7,160 stubs needed enrichment (~48 min). All stubs have `description IS NULL` because the agents genuinely never set a bio, not because enrichment failed. DB copied from VM to local (3.0 GB), snapshots created (5.7 GB total). All scraping stages complete — data ready for R analysis pipeline. Platform scale at scrape time: ~2.01M posts (we have 1.74M = 93.4%), ~13.21M comments (we have 2.73M = 20.6% — limited by 500/post API cap), ~2.86M agents (we have 167K = 5.8% — only those who authored posts/comments/moderated), ~19.2K submolts (we have 18.7K = 97%).

## 2026-03-06 (session 8) — Rate limit root cause analysis, VM deployment, comments scrape restarted

Diagnosed three compounding bugs causing the 16-worker comments scrape to collect zero data overnight: (1) token bucket capacity=9 allowed burst spikes, (2) `acquire()` outside retry loop let retries bypass the bucket (6× actual HTTP rate → 540 req/min against 60/min limit), (3) rate set to 90/min when production limit is 60 (confirmed via `X-RateLimit-Limit: 60` header; source code says 100 but production config differs). Also discovered infrastructure-level IP rate limiting (Cloudflare/nginx, per-IP not per-token, no headers, 15+ min cooldown) triggered by the overnight abuse. Key conclusion documented in `readme_api_limit.md`: sequential (1 worker, no token bucket) at ~25 req/min is 2.5× faster than concurrent and produces zero 429s; correct parallelism is across machines/IPs, not threads. Investigated ExtraE113/moltbook_data repo: their dataset has only ~165K posts (9% of platform) due to offset-based pagination hitting API depth cap — our 1.74M posts (93% coverage) via cursor-based pagination is irreplaceable. Deployed Hetzner CX23 VM (Nuremberg, €4.35/mo) for comments scrape: sequential mode achieves ~30-150 req/min (varies by post weight) with zero 429s. Set up tmux, watchdog (process health + progress + 6-hourly DB backups), logs. Agent enrichment revised from 166K stubs to only 7,188 (~5 hours). Comments API confirmed: hard cap 500/post, no pagination.

## 2026-03-05 (session 7) — Comments scrape throughput diagnosis and fixes; API source audit

Moderators scrape completed (13,741 rows, 13,645 submolts with mods). Comments scrape launched with `--only-missing --skip-empty --workers 4`; diagnosed as severely slow (10.8 posts/min → 28-day projected runtime) because posts are queued `ORDER BY comment_count DESC`, making heavy-post API latency (~22s/req) the bottleneck rather than the 90/min token bucket. Audited Moltbook API source (`routes/posts.js`, `routes/index.js`, `middleware/rateLimit.js`): confirmed global 100 req/min limit per API token applied to all routes; confirmed comment limit is 500 (not ~200 as previously believed), default 100. Fixed: restarted with `--workers 16` (token bucket now saturated at 90/min for the lighter remaining posts; avg 7.3 comments/post); patched `fetch_comments_only()` to pass `limit=500`; added `--rate-limit RPM` CLI flag for future tuning without code edits; added `-u` unbuffered Python flag to diagnose silent process crashes. At session end: 19,646 posts done, 434,063 remaining (~3.3 days at 90/min). User decision: do NOT auto-start enrich after comments — assess cloud VM / second API token strategy first.

## 2026-03-03 (session 6) — Three-stage speed optimization (Steps 1-3)

Implemented and 30+ min tested three optimizations to reduce comment/enrich/moderator scrape duration: Step 1 (`--skip-empty`) skips 1.29M zero-comment posts (74% of corpus) via LEFT JOIN DB query, reducing comments requests 3.7×; Step 2 (`fetch_comments_only()`) drops the redundant `GET /posts/{id}` re-fetch and only calls `/posts/{id}/comments`, halving requests per post (~1.7× measured); Step 3 (`--workers N`) adds `ThreadPoolExecutor` concurrent HTTP workers with all DB writes in main thread + a shared `_TokenBucket` rate limiter (auto-enabled at 90 req/min when N>1) to prevent thundering herd 429s — without the bucket, 4 workers caused 16 req/min (worse than 1 worker); with bucket, moderators ran at ~43 req/min. All changes backward-compatible (`max_workers=1` default). Posts scrape already complete (1,742,447 posts). Moderators scrape running as of session end with `--workers 4`.

## 2026-03-02 (session 5) — sort=new fix, posts scrape restarted, HPC/alternatives assessment

Removed stale `affectionate-lamport` worktree and branch (session 4 changes were already committed to main). Diagnosed why posts scrape exited at 69,974 posts: default `sort=hot` endpoint is algorithmically limited to the last ~3 days of high-engagement posts; confirmed via cursor injection that `sort=new` traverses the full chronological archive (platform launched ~Jan 15 2026); added `sort` parameter (default `"new"`) to `fetch_posts()` and `fetch_posts_streaming()` in `src/client.py`; re-launched posts scrape with `sort=new` (219K posts at session end, walking back to Jan 15). Also: assessed HPC strategy (key blocker is outbound HTTPS from compute nodes; DigitalOcean/Hetzner cheap VM recommended as alternative); documented that DB is portable via rsync and UPSERT design supports cross-machine workflow.

## 2026-02-28 (session 4) — Connectivity test, API drift fixes, client.py overhaul

Ran submolts connectivity test which exposed three breaking API changes (stats fields renamed to `totalX`, submolts switched to page-based pagination, posts switched to cursor-based pagination, comments moved to a separate endpoint); fixed all four in `src/client.py` (wholesale alignment with upstream `787f2d9`) and `src/scraper.py` (added `_normalize_agent`, submolt upsert from posts); removed the sliding-window throttle which caused cold-start burst→429 cycling; submolts scrape completed successfully with 18,625 / 18,625 records saved across 932 pages; updated `data/README.md` with current platform scale, corrected comment cap (~200/req not 1,000), and revised full-scrape time estimates.

## 2026-02-13 (session 3) — Rate-limit throttling, daily_scrape.ps1, CLAUDE.md hardening

Created `scripts/daily_scrape.ps1` (PowerShell replacement for Mac-hardcoded `daily_scrape.sh`), added proactive sliding-window throttle + escalating cooldown to `src/client.py`, added `--log-file` / `_configure_logging()` to `src/cli.py`, hardened `CLAUDE.md` with context-economy and scraping-cost rules; 7/8 tests pass, 1 pre-existing failure (`test_fetch_all_posts_paginates_until_no_more`).

## 2026-02-13 (session 2) — Environment bootstrap & codebase analysis

Created `.venv`, installed deps, created `data/raw/` / `logs/` / `analysis/` directory structure, updated `.gitignore`, created `data/README.md`, fixed Windows UTF-8 encoding bug in `src/cli.py`, added upstream remote, confirmed smoke test and docs fetch pass; identified platform scale (~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts).

## 2026-02-05 — Initial Setup Session

Created `CLAUDE.md`, performed full codebase audit confirming all Python source is complete, identified missing infrastructure (no Python runtime, no `.env`, no `data/` directories, hardcoded Mac paths in `daily_scrape.sh`), added methodology log, established `.gitignore` whitelist pattern for project docs.
