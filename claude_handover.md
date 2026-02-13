# Claude Handover - Moltbook Scraper

**Last updated**: 2026-02-13 (session 3)
**Git state**: Branch `affectionate-lamport`, uncommitted changes from session 3 (see below)
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Uncommitted changes (session 3)

- `scripts/daily_scrape.ps1` — **new** (PowerShell daily scrape)
- `src/client.py` — sliding-window throttle + escalating cooldown
- `src/cli.py` — `_configure_logging()` + `--log-file` arg
- `CLAUDE.md` — Context & Token Economy section, methodology log entries, repo structure update

These should be reviewed and committed.

---

## Next Immediate Steps

### Phase 2: Connectivity Test
1. **Run submolts scrape** to confirm API key and rate-limit behavior:
   ```powershell
   .venv\Scripts\python -m src.cli submolts --db data/raw/moltbook.db --log-file logs/scrape-submolts.log
   ```
   Expected: ~17K submolts in 2-5 minutes. Verify sliding-window throttle messages appear in log.

### Phase 3: Staged Full Scrape
Run each step independently so failures are isolated and resumable:

2. **Posts** (~1-2 hours):
   ```powershell
   .venv\Scripts\python -m src.cli posts --db data/raw/moltbook.db --log-file logs/scrape-posts.log
   ```
3. **Comments** (~5+ days, run overnight/background):
   ```powershell
   .venv\Scripts\python -m src.cli comments --only-missing --db data/raw/moltbook.db --log-file logs/scrape-comments.log
   ```
4. **Moderators** (~3 hours):
   ```powershell
   .venv\Scripts\python -m src.cli moderators --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
   ```
5. **Enrich agents** (~17 days, longest step):
   ```powershell
   .venv\Scripts\python -m src.cli enrich --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
   ```
6. **Snapshots** (local, seconds):
   ```powershell
   .venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
   ```

### Still TODO
- **Fix pre-existing test failure**: `test_fetch_all_posts_paginates_until_no_more` — test uses 1-item pages but `fetch_all_posts` stops when `len(posts) < limit` (100). The test or the method needs to be reconciled.
- **Design daily/weekly scrape automation** — decide on Windows Task Scheduler vs. manual for `daily_scrape.ps1`
- **Investigate `daily_scrape.ps1` log-file arg** — the ps1 script doesn't pass `--log-file` to cli.py yet (it tees stdout instead). Consider wiring through for diagnostic-level logging.

---

## Key Reference

- **DB path**: `data/raw/moltbook.db`
- **Rate limit**: 100 req/min (throttle at 90)
- **Platform scale**: ~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts
- **Completed work archive**: see `claude_archive.md`

---
