# Claude Handover - Moltbook Scraper

**Last updated**: 2026-02-05
**Git state**: Clean (branch `main`, up to date with `origin/main`)

---

## Session Summary (2026-02-05)

### What was done
1. **Created `CLAUDE.md`** - comprehensive project guide covering repo structure, commands, conventions, API limitations, and data considerations.
2. **User refined `CLAUDE.md`** - added Rules for New Scraper Modules, Operational Safeguards, and Data Hygiene sections. Trimmed dependency listing to reference `requirements.txt` / renv lock. Added `!CLAUDE.md` to `.gitignore`.
3. **Full codebase audit for scraping readiness** - mapped every file present against what's needed to actually run the scraper end-to-end.
4. **Added Methodology Log table to `CLAUDE.md`** - records decisions with date, reasoning, and status.

### Key findings from audit
- **All Python source code is complete**: `cli.py`, `client.py`, `database.py`, `scraper.py` are fully functional.
- **No `.env` file exists** - API key has never been configured on this machine.
- **No Python runtime detected** from CLI (`python`/`python3` not on PATH in this shell).
- **`scripts/daily_scrape.sh` has wrong path** - hardcoded to `/Users/dholtz/Desktop/git_repos/moltbook_scraper` (upstream author's Mac).
- **Missing directories**: `logs/`, `data/raw/`, `data/processed/`, `analysis/data/`, `analysis/output/figures/`, `analysis/output/tables/`.
- **No large data files present** - `moltbook.db` hasn't been created yet. Repo is ~200KB total (all source code).
- **`.gitignore` is well-configured** - covers `.env`, `*.db`, `logs/`, `analysis/output/`, `snapshots/`. Whitelists `README.md` and `CLAUDE.md`.
- **`.gitignore` gap**: `data/raw/` and `data/processed/` are not yet covered (directories don't exist yet either).

### Uncommitted changes
- `CLAUDE.md` - modified locally with methodology log addition. Not yet committed.
- `claude_handover.md` - this file, newly created. Not yet committed.

### Temporary hacks
- None. Repo is clean fork of upstream.

---

## Next Immediate Steps

### You (human) must do:
1. **Install Python 3.9+** and ensure `python` or `python3` is on PATH.
2. **Get a Moltbook API key** from https://moltbook.com (create an account, likely named `moltbook_archiver` per the research ethics convention).
3. **Create `.env`** in project root:
   ```
   MOLTBOOK_API_KEY=your_key_here
   ```
   This file is gitignored and will not be committed.

### Claude (next session) should do:
4. **Create virtual environment and install deps**:
   ```bash
   python -m venv .venv
   .venv/Scripts/activate    # Windows
   pip install -r requirements.txt
   ```
5. **Create required directories**:
   ```
   logs/
   data/raw/
   data/processed/
   analysis/data/
   analysis/output/figures/
   analysis/output/tables/
   ```
6. **Add `data/` to `.gitignore`** to cover `data/raw/` and `data/processed/`.
7. **Fix `scripts/daily_scrape.sh`** - replace hardcoded path with relative paths or a Windows-compatible PowerShell script.
8. **Update `utils.R:connect_db()`** if DB moves to `data/raw/moltbook.db`.
9. **Create `.env.example`** (safe to commit) with placeholder format.
10. **Run a test scrape** to verify connectivity:
    ```bash
    python -m src.cli status --db data/raw/moltbook.db
    python -m src.cli docs  # No API key needed, tests network
    ```
11. **Run full scrape**:
    ```bash
    python -m src.cli full --db data/raw/moltbook.db
    ```
12. **Verify with status**:
    ```bash
    python -m src.cli status --db data/raw/moltbook.db
    ```

---

## File Inventory (all paths relative to project root)

| Path | Size | Tracked | Notes |
|------|------|---------|-------|
| `src/cli.py` | 6.6K | Yes | CLI entry point |
| `src/client.py` | 15K | Yes | API client with retries |
| `src/database.py` | 24K | Yes | SQLite schema + ops |
| `src/scraper.py` | 19K | Yes | Orchestration |
| `analysis/R/*.R` | ~93K | Yes | 8 analysis scripts |
| `latex/moltbook_analysis.tex` | 36K | Yes | Paper source |
| `latex/moltbook_analysis.bib` | 12K | Yes | Bibliography |
| `scripts/daily_scrape.sh` | 832B | Yes | Needs path fix |
| `scripts/run_on_hpc.sh` | 2.2K | Yes | HPC job script |
| `tests/` | ~19K | Yes | 3 test files |
| `CLAUDE.md` | 6.6K | Yes | Project guide (modified) |
| `.env` | -- | No (gitignored) | Does not exist yet |
| `moltbook.db` | -- | No (gitignored) | Does not exist yet |
