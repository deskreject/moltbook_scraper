# Claude Archive - Moltbook Scraper

Synthesized records of completed work from previous sessions. See `claude_handover.md` for current state.

---

## 2026-02-13 (session 2) — Environment bootstrap & codebase analysis

- Created `.venv`, installed all deps from `requirements.txt`
- Created directory structure: `data/raw/`, `logs/`, `analysis/data/`, `analysis/output/figures/`, `analysis/output/tables/`
- Updated `.gitignore` (added `data/`, `analysis/data/`, whitelisted `data/README.md`)
- Created `data/README.md` with full documentation of all 11 database tables (6 live, 5 snapshot)
- Fixed Windows encoding bug in `src/cli.py` — `write_text()` now specifies `encoding="utf-8"` (cp1252 breaks on emoji)
- Added upstream remote (`git remote add upstream https://github.com/daveholtz/moltbook_scraper.git`)
- Smoke test passed — `status --db data/raw/moltbook.db` confirmed DB creation
- Docs fetch succeeded — `snapshots/docs/` contains skill, heartbeat, messaging docs
- Key findings: platform scale ~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts; rate limit 100 req/min; full comments scrape ~5 days, enrichment ~17 days

## 2026-02-13 (session 3) — Rate-limit throttling, daily_scrape.ps1, CLAUDE.md hardening

- Created `scripts/daily_scrape.ps1` — PowerShell replacement for Mac-hardcoded `daily_scrape.sh`. Uses `$PSScriptRoot`, activates `.venv`, runs staged pipeline, tees to `logs/`
- Added proactive sliding-window throttle to `src/client.py` — 90/100 threshold per 60s window, escalating cooldown on consecutive 429s (30s→300s cap), `RateLimitError` after 10 consecutive 429s
- Added `--log-file` arg and `_configure_logging()` to `src/cli.py` — routes `moltbook.*` loggers to stderr + optional file with timestamps
- Hardened `CLAUDE.md` with "Context & Token Economy" section (log handling, large files, error-loop circuit breaker, scraping cost awareness)
- Tests: 7/8 pass; 1 pre-existing failure (`test_fetch_all_posts_paginates_until_no_more` — pagination stop condition mismatch, not caused by throttle changes)

## 2026-02-05 — Initial Setup Session

Created `CLAUDE.md` project guide, performed full codebase audit confirming all Python source is complete (`cli.py`, `client.py`, `database.py`, `scraper.py`), identified missing infrastructure (no Python runtime, no `.env`, no `data/` directories, hardcoded Mac paths in `daily_scrape.sh`), added methodology log, and established `.gitignore` whitelist pattern for project docs.
