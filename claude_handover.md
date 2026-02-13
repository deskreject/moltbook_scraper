# Claude Handover - Moltbook Scraper

**Last updated**: 2026-02-13
**Git state**: Branch `affectionate-lamport`, uncommitted changes to `.gitignore` and `src/cli.py` (being committed now)
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Session Summary (2026-02-13)

### What was done
1. **Environment setup complete** — created `.venv`, installed all deps from `requirements.txt` (requests, python-dotenv, pytest, etc.)
2. **Created required directories** — `data/raw/`, `logs/`, `analysis/data/`, `analysis/output/figures/`, `analysis/output/tables/`
3. **Updated `.gitignore`** — added `data/`, `analysis/data/`, whitelisted `data/README.md`
4. **Created `data/README.md`** — full documentation of all 11 database tables (6 live, 5 snapshot) with column descriptions
5. **Fixed Windows encoding bug in `src/cli.py`** — `filepath.write_text()` now specifies `encoding="utf-8"` (Moltbook docs contain emoji, Windows defaults to cp1252)
6. **Added upstream remote** — `git remote add upstream https://github.com/daveholtz/moltbook_scraper.git` for tracking original author changes
7. **Smoke test passed** — `status --db data/raw/moltbook.db` confirmed DB creation and table initialization (0 rows, as expected)
8. **Docs fetch succeeded** (after encoding fix) — `snapshots/docs/` contains skill, heartbeat, messaging docs
9. **Full codebase analysis** — read all 4 Python source files, mapped complete data schema, identified platform scale and rate limits
10. **API investigation** — confirmed Moltbook API v1 is live, rate limit is 100 req/min, documented all endpoints

### Key findings
- **Platform scale** (as of 2026-02-13): ~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts
- **Rate limit**: 100 requests/minute (confirmed via official API docs at github.com/moltbook/api)
- **Full scrape time estimate**: Comments ~5 days, agent enrichment ~17 days at rate limit. Must be run in stages.
- **No upstream divergence**: fork is current with `daveholtz/moltbook_scraper`
- **Scraper resilience**: UPSERT pattern means interrupted scrapes lose no data; re-running is safe

### Uncommitted changes (being committed with this handover)
- `.gitignore` — added `data/`, `analysis/data/`, `!data/README.md`
- `src/cli.py` — UTF-8 encoding fix for `write_text()`
- `claude_handover.md` — this file (rewritten)
- `claude_archive.md` — new (archived 2026-02-05 session)
- `data/README.md` — new (table documentation)
- `CLAUDE.md` — updated methodology log

### Temporary hacks
- None

---

## Next Immediate Steps

### Phase 2: Connectivity Test
1. **Run submolts scrape** to confirm API key and rate-limit behavior:
   ```bash
   .venv\Scripts\python -m src.cli submolts --db data/raw/moltbook.db
   ```
   Expected: ~17K submolts in 2–5 minutes

### Phase 3: Staged Full Scrape
Run each step independently (not `full`) so failures are isolated and resumable:

2. **Posts** (~1–2 hours):
   ```bash
   .venv\Scripts\python -m src.cli posts --db data/raw/moltbook.db 2>&1 | tee logs/scrape_posts.log
   ```
3. **Comments** (~5+ days, run overnight/background):
   ```bash
   .venv\Scripts\python -m src.cli comments --only-missing --db data/raw/moltbook.db 2>&1 | tee logs/scrape_comments.log
   ```
4. **Moderators** (~3 hours):
   ```bash
   .venv\Scripts\python -m src.cli moderators --db data/raw/moltbook.db 2>&1 | tee logs/scrape_moderators.log
   ```
5. **Enrich agents** (~17 days, longest step):
   ```bash
   .venv\Scripts\python -m src.cli enrich --db data/raw/moltbook.db 2>&1 | tee logs/scrape_enrich.log
   ```
6. **Snapshots** (local, seconds):
   ```bash
   .venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
   ```

### Still TODO (not yet started)
- **Fix `scripts/daily_scrape.sh`** — hardcoded to upstream author's Mac path
- **Design daily/weekly scrape automation** — decide on Windows Task Scheduler vs. manual
- **Consider rate-limit-aware throttling** — scraper retries on 429 but doesn't proactively slow down via `X-RateLimit-Remaining` header

---

## File Inventory (all paths relative to project root)

| Path | Size | Tracked | Notes |
|------|------|---------|-------|
| `src/cli.py` | 6.6K | Yes | Modified: UTF-8 encoding fix |
| `src/client.py` | 15K | Yes | Unchanged |
| `src/database.py` | 24K | Yes | Unchanged |
| `src/scraper.py` | 19K | Yes | Unchanged |
| `analysis/R/*.R` | ~93K | Yes | Unchanged (8 scripts) |
| `latex/moltbook_analysis.tex` | 36K | Yes | Unchanged |
| `scripts/daily_scrape.sh` | 832B | Yes | Still needs path fix |
| `tests/` | ~19K | Yes | Unchanged (3 test files) |
| `data/README.md` | 5.6K | Yes | New: table documentation |
| `data/raw/moltbook.db` | 128K | No (gitignored) | Empty schema, 0 rows |
| `.env` | -- | No (gitignored) | API key configured |
| `snapshots/docs/` | ~37K | No (gitignored) | Fetched Moltbook docs |
| `.venv/` | ~30MB | No (gitignored) | Python virtual environment |
