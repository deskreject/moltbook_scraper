# Session 1 — 2026-02-05 — Initial Setup

**What was done:**
- Created `CLAUDE.md`, full codebase audit
- Identified missing infrastructure: no Python runtime, no `.env`, no `data/` dirs, hardcoded Mac paths in `daily_scrape.sh`
- Established `.gitignore` whitelist pattern for project docs

**Key decisions:**
- DB path: `data/raw/moltbook.db`
- Snapshot tables for all analysis (reproducibility)
- 80% tolerance for comment validation (API caps at 500/post)
