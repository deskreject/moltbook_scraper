# Sessions 2-3 — 2026-02-13 — Environment Bootstrap & Rate Limit Throttling

**What was done:**
- Created `.venv`, installed deps, set up `data/raw/`, `logs/`, `analysis/` directories
- Fixed Windows UTF-8 encoding bug in `src/cli.py` (cp1252 default breaks on emoji)
- Added upstream remote for drift detection
- Created `scripts/daily_scrape.ps1` (Windows replacement for Mac-only `.sh`)
- Added proactive sliding-window throttle + `--log-file` / `_configure_logging()` to CLI
- 7/8 tests pass; 1 pre-existing failure (`test_fetch_all_posts_paginates_until_no_more`)

**Platform scale at time:** ~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts

**Key learnings:**
- Sliding-window throttle caused cold-start burst cascading 429s (removed in session 4)
- Always specify UTF-8 encoding explicitly on Windows
