# CLAUDE.md - Project Guide for Moltbook Scraper

## Project Overview

Academic research project for scraping and econometrically analyzing Moltbook, an AI-agent-only social network. The project produces a working paper analyzing the social graph structure, conversation dynamics, and content patterns of AI agent interactions.

**Research Question**: Is posting activity on Moltbook meaningfully social, or is it largely an as-if performance?

## Repository Structure

```
moltbook_scraper/
├── src/                     # Python scraper (core data collection)
│   ├── cli.py               # CLI entry point
│   ├── client.py            # Moltbook API client with retry logic
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
│   ├── daily_scrape.sh      # Cron-style scraping
│   └── run_on_hpc.sh        # HPC cluster job
└── tests/                   # pytest unit tests
```

## Quick Commands

### Scraping (Python)

```bash
# Full scrape (submolts, posts, comments, moderators, agents, snapshots)
python -m src.cli full --db moltbook.db

# Incremental (new posts only)
python -m src.cli incremental --db moltbook.db

# Individual commands
python -m src.cli submolts --db moltbook.db
python -m src.cli posts --db moltbook.db
python -m src.cli comments --db moltbook.db
python -m src.cli comments --db moltbook.db --only-missing  # Skip posts with comments
python -m src.cli enrich --db moltbook.db
python -m src.cli moderators --db moltbook.db
python -m src.cli snapshots --db moltbook.db

# Database status
python -m src.cli status --db moltbook.db

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

- SQLite database: `moltbook.db` (gitignored)
- Snapshot tables record point-in-time data for reproducibility
- Key tables: `agents`, `posts`, `comments`, `submolts`, `moderators`
- Snapshot tables: `*_snapshots` with `scrape_run_id` for tracking


## Code Conventions

### Python

- Type hints used throughout
- Streaming/pagination with callbacks for large datasets
- Retry logic with exponential backoff for flaky API
- UPSERT pattern with COALESCE for incremental updates
- Validation against platform stats API

### R

- Tidyverse style (dplyr, ggplot2, tidyr)
- `theme_paper()` for publication-ready figures
- Save helpers: `save_figure()`, `save_table()`
- Database connection via `connect_db()` utility

## Important Notes

### API Limitations

- Comments capped at 1,000 per post (impacts high-volume posts)
- Follower/following graph not exposed (only counts)
- Non-deterministic pagination requires streaming with deduplication
- Rate limiting: 429 responses handled with exponential backoff

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

## Data Hygiene

- Large databases (>100MB) should be stored in `data/raw/` which is added to `.gitignore`. Only `.rds` summaries go in `data/processed/`.
- The default `--db moltbook.db` stores in project root; move to `data/raw/moltbook.db` once scraping is operational.
- R scripts in `analysis/R/` expect the DB at `../../moltbook.db` (relative to their directory). Update `utils.R:connect_db()` if the DB path changes.

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