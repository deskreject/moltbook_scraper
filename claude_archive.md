# Claude Archive - Moltbook Scraper

Synthesized records of completed work from previous sessions. See `claude_handover.md` for current state.

---

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
