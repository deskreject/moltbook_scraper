# Session 4 — 2026-02-28 — API Drift Fixes & Client Overhaul

**What was done:**
- Connectivity test exposed 4 breaking API changes since fork:
  1. Stats fields renamed to `totalX`
  2. Submolts → page-based pagination (`?page=N`, 20/page)
  3. Posts → cursor-based pagination (`has_more` + `next_cursor`)
  4. Comments → separate endpoint (`/posts/{id}/comments`)
- Fixed all in `src/client.py` (aligned with upstream `787f2d9`) and `src/scraper.py`
- Added `_normalize_agent()` for camelCase → snake_case on embedded agent objects
- Removed sliding-window throttle (reactive exponential backoff is sufficient)
- Submolts scrape completed: 18,625 records across 932 pages

**Key learnings:**
- Always check live API responses before assuming schema from source code
