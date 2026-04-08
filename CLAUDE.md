# CLAUDE.md - Project Guide for Moltbook Scraper

## Project Overview

Academic research project for scraping and econometrically analyzing Moltbook, an AI-agent-only social network. The project produces a working paper analyzing the social graph structure, conversation dynamics, and content patterns of AI agent interactions.

## Quick Commands

### Scraping (Python)

```bash
# Full scrape (submolts, posts, comments, moderators, agents, snapshots)
python -m src.cli full --db data/raw/moltbook.db

# Incremental (new posts only)
python -m src.cli incremental --db data/raw/moltbook.db

# Individual commands (preferred — staged scrape is resumable)
# IMPORTANT: always use -u (unbuffered stdout) for background runs so errors surface in log
python -u -m src.cli submolts --db data/raw/moltbook.db --log-file logs/scrape-submolts.log
python -u -m src.cli posts --db data/raw/moltbook.db --log-file logs/scrape-posts.log
python -u -m src.cli comments --only-missing --skip-empty --workers 16 --db data/raw/moltbook.db --log-file logs/scrape-comments.log
python -u -m src.cli enrich --workers 16 --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
python -u -m src.cli moderators --workers 4 --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
python -m src.cli snapshots --db data/raw/moltbook.db

# Database status
python -m src.cli status --db data/raw/moltbook.db

# Fetch platform documentation
python -m src.cli docs

# Full re-scrape with deletion detection (monthly)
python -u -m src.cli posts --db data/raw/moltbook.db --detect-deletions --log-file logs/scrape-posts.log
python -u -m src.cli comments --db data/raw/moltbook.db --detect-deletions --log-file logs/scrape-comments.log
```

### VM Automation (Hetzner)

```bash
# Weekly cron (Mon 02:00 UTC): incremental + comments + enrich + snapshots
0 2 * * 1  cd ~/moltbook_scraper && bash scripts/weekly_scrape.sh

# Monthly cron (1st 02:00 UTC): full re-scrape with deletion detection
0 2 1 * *  cd ~/moltbook_scraper && bash scripts/monthly_rescrape.sh

# Daily disk monitor (08:00 UTC): emails if >80% on either disk
0 8 * * *  cd ~/moltbook_scraper && bash scripts/disk_monitor.sh

# Check status manually (from local machine)
ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'

# Pull DB to local
scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/

# Push code to VM (then dos2unix!)
scp -r src/ scripts/ vm:~/moltbook_scraper/
ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'
```

**VM storage layout**: DB and backups live on 80 GB volume (`/mnt/HC_Volume_104999576/moltbook_data/`), symlinked from `data/raw/` and `data/backups/`. All paths in scripts and `scp` commands work unchanged.

### Testing

```bash
pytest                    # Run all tests
pytest tests/test_client.py -v
```

## Configuration

### Environment Variables

- `MOLTBOOK_API_KEY` - Required for scraping (set in `.env` file)

### Database

- SQLite database: `data/raw/moltbook.db` (gitignored; will reach several GB after full scrape)
- Snapshot tables record point-in-time data for reproducibility
- Key tables: `agents`, `posts`, `comments`, `submolts`, `moderators`
- Snapshot tables: `*_snapshots` with `scrape_run_id` for tracking
- Full schema: `src/database.py:_create_tables()`; human-readable: `data/README.md`


## Code Conventions

- refer to /CLAUDE/project_specific_rules/ for guides specific to the language used (python, R etc.)

## Important Notes

## Output conventions

from the project directory
- **Tables**: Save all tables to /tables
- **Figures** save all figures to /figures
- **claude scripts** save all figures to code named "claude_xxx.r"
- **session logs** save all session logs to /CLAUDE/session_logs 

## Process logs

- **session memory** save what you did and what was learned in brief, but parsimonious way to the session logs in the form of "yyyy_mm_dd_session_log".
- **handover document** outline next steps to the file handover.md in a way that can be complemented by the session logs. I.e. reference in which session log the relevant further information to understand the next steps can be
- **Claude.md** should be updated with any key decisions made about choice of methods, data processing and anything else of relevance for reproducibility
- **learnings.md** should document errors, failures, choke points or dead ends that were encountered and how they were solved including things that were tried and didn't work or were refused by me with the associated reason. The purpose is to stop pursuing directions that were tried in the past.
- **achive file**  It should be a archive.md file with condensed entries by date of things that were removed from handover, Claude.md and learning.md that are no longer relevant for each session but that offer a very parsimonious bread crumb trail. 

### API Limitations (quick reference; see `readme_api_limit.md` for rate limit deep dive)

- Comments: hard cap 500/request, no pagination; scraper passes `limit=500`
- Follower/following graph not exposed (only counts)
- Posts: cursor-based pagination (`has_more` + `next_cursor`) with `sort=new` (required for full archive)
- Submolts: page-based (`?page=N`, 20/page)
- Embedded agents use camelCase; `_normalize_agent()` converts to snake_case
- Rate limit: 60/min per token (production); exponential backoff on 429

### Data Considerations

- Snapshot data should be used for analysis (not live tables) for reproducibility
- R scripts expect snapshots to exist; run `python -m src.cli snapshots` first
- Analysis filters to snapshot timestamp via INNER JOIN

### Research Ethics

- Scraper account: `moltbook_archiver` (read-only, no posting)
- Data describes AI agents, not human subjects
- Public API access with dedicated research account

## Dependencies

from the requirements.txt or the renv lock file


## Rules for New Scraper Modules
- **File Location**: New scrapers go in `src/`.
- **CLI Integration**: Every new scraper must be registered as a command in `src/cli.py`.
- **Database**: Use the `DatabaseManager` class from `src/database.py`. Do not write raw SQL strings in the scraper files.
- **Documentation**: Every new function requires a Google-style docstring explaining the Moltbook API endpoint it hits.
- **Naming**: Use `fetch_` prefix for API calls and `process_` for data cleaning.

## Operational Safeguards
- **Scope**: Stay within the project root. Never move up the directory tree (`cd ..`).
- **Deletions**: Do not delete files without permission and a stated reason.
- **Git State**: Check for a 'clean' git state before performing major refactors.
- **Database**: Do not modify existing data in `moltbook.db` without a backup; never drop tables.
- **Safety**: Do not use `sudo`. Do not reveal `MOLTBOOK_API_KEY` in logs or chat outputs.
- **Costs**: If an automated task (like a loop) exceeds 5 iterations without success, stop and ask for guidance to avoid burning API tokens.

## Context & Token Economy

### Log file handling
- **Never** `Read` an entire scrape log file. Scrape logs can be hundreds of thousands of lines (multi-day processes). Always use `tail -50` or `head -50` via Bash first, or use `Read` with `offset`/`limit` to sample specific regions.
- When diagnosing scrape failures, read only the **last 100 lines** of the log unless explicitly asked for more.

### Large file guardrails
- Before reading any file, check its size. If > 5,000 lines, read only the relevant section (start, end, or grep for keywords).
- Never dump entire database query results into chat. Use `LIMIT 10` for exploratory queries; use `COUNT(*)` for sizing.

### Error-loop circuit breaker
- If the same tool call (Bash command, Read, etc.) fails **3 times in a row** with the same or similar error, **stop and ask the user** rather than retrying with minor variations. This prevents context-burning retry loops.
- If a code fix → test cycle fails **3 consecutive times**, pause and present a summary of what was tried and what failed.

### Scraping cost awareness
- Before starting any scrape command, state the estimated duration and API call count.
- If a scrape command has been running for > 10 minutes in a foreground Bash call, do not wait — inform the user it should be backgrounded or run in a separate terminal.

## Data Hygiene

- Large databases (>100MB) should be stored in `data/raw/` which is added to `.gitignore`. Only `.rds` summaries go in `data/processed/`.
- Always use `data/raw/moltbook.db` as the DB path — do not store the DB in the project root.
- R scripts in `analysis/R/` expect the DB at `../../data/raw/moltbook.db` (relative to their directory). Update `utils.R:connect_db()` if the DB path changes.

