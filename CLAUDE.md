# CLAUDE.md - Project Guide for Moltbook Scraper

## Project Overview

Academic research project for scraping and econometrically analyzing Moltbook, an AI-agent-only social network. The project produces a working paper analyzing the social graph structure, conversation dynamics, and content patterns of AI agent interactions.

**Research Question**: Is posting activity on Moltbook meaningfully social, or is it largely an as-if performance?

## Repository Structure

```
moltbook_scraper/
├── src/                     # Python scraper (core data collection)
│   ├── cli.py               # CLI entry point
│   ├── client.py            # Moltbook API client with exponential backoff retry
│   ├── database.py          # SQLite schema and operations
│   └── scraper.py           # Scraping orchestration
├── analysis/
│   ├── R/                   # R analysis scripts (run sequentially)
│   │   ├── utils.R          # Shared utilities (themes, Gini, Jaccard, etc.)
│   │   ├── 01_load_data.R   # Load SQLite snapshots into R dataframes
│   │   ├── 02_structural.R  # Platform growth, concentration metrics
│   │   ├── 03_conversation.R # Thread depth, reply patterns
│   │   ├── 04_lexical.R     # Zipf analysis, duplicates, n-grams
│   │   ├── 05_topics.R      # Theme classification, key phrases
│   │   ├── 06_network_deep.R # Reply network (reciprocity, clustering)
│   │   └── 07_owner_analysis.R # Agent-owner relationships
│   ├── data/                # Processed .rds files (gitignored)
│   └── output/              # Figures and tables (gitignored)
├── latex/
│   └── moltbook_analysis.tex # Paper source (natbib, booktabs)
├── scripts/
│   ├── daily_scrape.ps1     # Windows PowerShell daily scrape (primary)
│   ├── daily_scrape.sh      # Bash daily scrape (cross-platform reference)
│   └── run_on_hpc.sh        # HPC cluster job
└── tests/                   # pytest unit tests
```

## Quick Commands

### Scraping (Python)

```bash
# Full scrape (submolts, posts, comments, moderators, agents, snapshots)
python -m src.cli full --db data/raw/moltbook.db

# Incremental (new posts only)
python -m src.cli incremental --db data/raw/moltbook.db

# Individual commands (preferred — staged scrape is resumable)
python -m src.cli submolts --db data/raw/moltbook.db --log-file logs/scrape-submolts.log
python -m src.cli posts --db data/raw/moltbook.db --log-file logs/scrape-posts.log
python -m src.cli comments --only-missing --db data/raw/moltbook.db --log-file logs/scrape-comments.log
python -m src.cli enrich --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
python -m src.cli moderators --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
python -m src.cli snapshots --db data/raw/moltbook.db

# Database status
python -m src.cli status --db data/raw/moltbook.db

# Fetch platform documentation
python -m src.cli docs
```

### Analysis (R)

Run from `analysis/R/` directory in order:

```bash
Rscript 01_load_data.R   # Creates analysis/data/*.rds
Rscript 02_structural.R  # Power-law fits, Gini, growth plots
Rscript 03_conversation.R # Thread shapes, depth distribution
Rscript 04_lexical.R     # Zipf, duplicates, loops
Rscript 05_topics.R      # Keyword themes, key phrases
Rscript 06_network_deep.R # igraph metrics, community detection
Rscript 07_owner_analysis.R # "my human" patterns
```

### Testing

```bash
pytest                    # Run all tests
pytest tests/test_client.py -v
```

### Building Paper

```bash
cd latex
pdflatex moltbook_analysis.tex
bibtex moltbook_analysis
pdflatex moltbook_analysis.tex
pdflatex moltbook_analysis.tex
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

### Python

- Type hints used throughout
- Streaming/pagination with callbacks for large datasets
- Retry logic with exponential backoff for 429s and 5xx (no proactive throttle)
- UPSERT pattern with COALESCE for incremental updates
- Validation against platform stats API (`/api/v1/stats` returns `totalAgents`, `totalPosts`, `totalComments`, `totalSubmolts`)

### R

- Tidyverse style (dplyr, ggplot2, tidyr)
- `theme_paper()` for publication-ready figures
- Save helpers: `save_figure()`, `save_table()`
- Database connection via `connect_db()` utility

## Important Notes

### API Limitations

- Comments capped at ~200 per request (not 1,000 — confirmed 2026-02-28); validation uses 80% tolerance
- Follower/following graph not exposed (only counts)
- Posts use cursor-based pagination (`has_more` + `next_cursor`); submolts use page-based (`?page=N`, 20/page)
- Embedded agent objects in API responses use camelCase keys (`avatarUrl` etc.); `_normalize_agent()` in `client.py` converts to snake_case before DB writes
- Rate limiting: 429 responses handled with exponential backoff (no proactive throttle)

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


### LaTeX
- Standard packages: amsmath, booktabs, natbib, hyperref, cleveref
- Custom macros: `\figmaybe`, `\figpairmaybe` for conditional figure inclusion

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

## Methodology Log

| Date       | Decision                                   | Reasoning                                                        | Status      |
|------------|--------------------------------------------|-----------------------------------------------------------------|-------------|
| 2026-02-05 | Store DB at `data/raw/moltbook.db`         | Keeps large binary out of repo root; aligned with data hygiene rule | Planned     |
| 2026-02-05 | Use snapshot tables for all analysis        | Reproducibility: live tables mutate on each scrape               | Established |
| 2026-02-05 | 80% tolerance for comment validation        | API caps comments at 1000/post; can never reach platform total   | Established |
| 2026-02-05 | Non-deterministic pagination with dedup     | Moltbook API returns inconsistent pages; streaming + seen-set    | Established |
| 2026-02-05 | Rewrite `daily_scrape.sh` for Windows/local | Original hardcoded to `/Users/dholtz/...` (upstream author)      | Planned     |
| 2026-02-13 | Staged scrape instead of monolithic `full`   | At 100 req/min, full scrape takes days; stages are resumable     | Established |
| 2026-02-13 | DB path: `data/raw/moltbook.db`              | Smoke test confirmed; DB auto-created by SQLite on first run     | Active      |
| 2026-02-13 | UTF-8 encoding for all file writes on Windows | cp1252 default breaks on emoji in Moltbook docs                  | Fixed       |
| 2026-02-13 | Upstream remote added for drift detection     | `git fetch upstream` to check for API changes by original author | Active      |
| 2026-02-13 | Proactive rate throttle (90/min sliding window) | Avoid 429 storms; maintain diagnostic logs | Active |
| 2026-02-13 | PowerShell daily_scrape.ps1 replaces .sh       | Windows 11 environment; .sh kept for reference | Active |
| 2026-02-13 | Context-economy rules in CLAUDE.md             | Prevent token burn on large logs, error loops, and DB dumps | Active |
| 2026-02-28 | Removed sliding-window throttle from `client.py` | Cold-start burst caused cascading 429 storms; reactive exponential backoff (upstream approach) is sufficient | Active |
| 2026-02-28 | Comment cap revised from 1,000 to ~200 per request | Live API confirmed lower cap; 80% validation tolerance unchanged | Active |
| 2026-02-28 | Posts: cursor-based pagination (`has_more` + `next_cursor`) | API breaking change confirmed live; offset parameter no longer honoured | Active |
| 2026-02-28 | Submolts: page-based pagination (`?page=N`, 20/page) | API breaking change; offset returned only first page then empty | Active |
| 2026-02-28 | Comments: separate endpoint (`/posts/{id}/comments`) | API breaking change; comments no longer embedded in post response | Active |
| 2026-02-28 | `_normalize_agent()` applied to all embedded author objects | API returns camelCase for embedded agents; DB schema expects snake_case | Active |
| 2026-02-28 | HPC (`scripts/run_on_hpc.sh`) flagged for comments+enrich | 10-14 day comments and multi-week enrich are impractical on local machine; script needs cluster-specific info from user | Pending |