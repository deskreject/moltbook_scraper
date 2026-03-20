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
│   ├── weekly_scrape.sh     # Weekly incremental (Hetzner VM cron, Mon 02:00 UTC)
│   ├── monthly_rescrape.sh  # Monthly full re-scrape (Hetzner VM cron, 1st 02:00 UTC)
│   ├── status.sh            # VM status dashboard (manual SSH)
│   ├── daily_scrape.ps1     # Windows PowerShell daily scrape (legacy)
│   ├── daily_scrape.sh      # Bash daily scrape (legacy reference)
│   └── run_on_hpc.sh        # HPC cluster job (unused)
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

# Check status manually (from local machine)
ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'

# Pull DB to local
scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/

# Push code to VM (then dos2unix!)
scp -r src/ scripts/ vm:~/moltbook_scraper/
ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'
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

- Comments: server default is 100/request, hard cap 500 (confirmed 2026-03-05 via API source); scraper passes `limit=500` to maximise coverage; validation uses 80% tolerance
- Follower/following graph not exposed (only counts)
- Posts use cursor-based pagination (`has_more` + `next_cursor`) with `sort=new` (required for full archive); `sort=hot` default caps at ~70K posts; submolts use page-based (`?page=N`, 20/page)
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
| 2026-02-05 | Rewrite `daily_scrape.sh` for Windows/local | Original hardcoded to `/Users/dholtz/...` (upstream author)      | Done (ps1)  |
| 2026-02-13 | Staged scrape instead of monolithic `full`   | At 100 req/min, full scrape takes days; stages are resumable     | Established |
| 2026-02-13 | DB path: `data/raw/moltbook.db`              | Smoke test confirmed; DB auto-created by SQLite on first run     | Active      |
| 2026-02-13 | UTF-8 encoding for all file writes on Windows | cp1252 default breaks on emoji in Moltbook docs                  | Fixed       |
| 2026-02-13 | Upstream remote added for drift detection     | `git fetch upstream` to check for API changes by original author | Active      |
| 2026-02-13 | Proactive rate throttle (90/min sliding window) | Avoid 429 storms; maintain diagnostic logs | REMOVED — caused cold-start burst cascading |
| 2026-02-13 | PowerShell daily_scrape.ps1 replaces .sh       | Windows 11 environment; .sh kept for reference | Active |
| 2026-02-13 | Context-economy rules in CLAUDE.md             | Prevent token burn on large logs, error loops, and DB dumps | Active |
| 2026-02-28 | Removed sliding-window throttle from `client.py` | Cold-start burst caused cascading 429 storms; reactive exponential backoff (upstream approach) is sufficient | Active |
| 2026-02-28 | Comment cap revised from 1,000 to ~200 per request | Live API confirmed lower cap; later corrected to 500 (see 2026-03-05) | Superseded |
| 2026-02-28 | Posts: cursor-based pagination (`has_more` + `next_cursor`) | API breaking change confirmed live; offset parameter no longer honoured | Active |
| 2026-02-28 | Submolts: page-based pagination (`?page=N`, 20/page) | API breaking change; offset returned only first page then empty | Active |
| 2026-02-28 | Comments: separate endpoint (`/posts/{id}/comments`) | API breaking change; comments no longer embedded in post response | Active |
| 2026-02-28 | `_normalize_agent()` applied to all embedded author objects | API returns camelCase for embedded agents; DB schema expects snake_case | Active |
| 2026-02-28 | HPC (`scripts/run_on_hpc.sh`) flagged for comments+enrich | 10-14 day comments and multi-week enrich are impractical on local machine; script needs cluster-specific info from user | Superseded by Hetzner VM |
| 2026-03-02 | Posts scrape must use `sort=new` not default `sort=hot` | `sort=hot` is algorithmically capped at ~70K posts (exhausts score-based tail after ~700 pages, covering only ~3 days); `sort=new` traverses full chronological archive back to platform launch | Active |
| 2026-03-02 | Platform launched ~Jan 15 2026 | Confirmed via cursor injection: no posts exist before Jan 15; platform is ~6 weeks old at time of scraping | Active |
| 2026-03-02 | Cloud VM (Hetzner/DigitalOcean) as HPC alternative | Comments (~10-14 days) and enrich (weeks) need persistent uptime; cheap VM (~€5-10 total) is lower-friction than HPC for a researcher without cluster experience | Active |
| 2026-03-02 | DB is portable via rsync; stages run on whichever machine holds the file | UPSERT design means cross-machine handoff is safe: copy file, continue scraping, copy back | Active |
| 2026-03-03 | `--skip-empty` flag skips 74% of posts with comment_count=0 | 1,288,777 of 1,742,447 posts have no comments; skipping them reduces comment-stage requests from 1.74M to 453K (3.7×) | Active |
| 2026-03-03 | `fetch_comments_only()` halves comment-stage requests | Posts are already in DB; only `/posts/{id}/comments` needed, not `/posts/{id}` — saves 1 req/post (~1.7× measured speedup) | Active |
| 2026-03-03 | `--workers N` adds ThreadPoolExecutor; DB writes stay in main thread | Workers do HTTP only to avoid SQLite check_same_thread; `--workers 4` auto-enables token bucket at 90 req/min; without bucket 4 workers caused thundering herd (16 req/min < 1 worker) | Active |
| 2026-03-03 | Token bucket required for concurrent workers; acquire() must be inside retry loop | Without bucket: thundering herd 429s; with bucket outside retry loop: retries bypass it, multiplying HTTP rate by up to 6×; acquire() must be called per HTTP attempt | Active |
| 2026-03-05 | Global rate limit: source code says 100/min, production is 60/min | `X-RateLimit-Limit: 60` observed in live response headers 2026-03-06; source code (`rateLimit.js`) said 100 but production config differs; token bucket default corrected to 55/min; do NOT raise without re-checking header | Active |
| 2026-03-05 | Comments fetch uses `limit=500` (server hard cap) | Default was 100; cap confirmed 500 via `src/routes/posts.js`; one request still per post | Active |
| 2026-03-05 | Use `python -u` for all background scrapes | Block-buffered stdout causes silent error loss when process dies; `-u` makes output appear immediately in task file | Active |
| 2026-03-05 | Comments scrape runs sequential (1 worker, no token bucket) | Multi-worker approach is slower than sequential for this API (see readme_api_limit.md); sequential achieves ~25-150 req/min depending on post weight, zero 429s | Active |
| 2026-03-05 | Do not auto-start enrich after comments | User evaluating second API token and cloud VM options first | Resolved — weekly script runs all stages sequentially |
| 2026-03-06 | Token bucket capacity must be 1.0 (no burst) | capacity=9 caused up to 9 simultaneous requests; combined with retries-bypassing-bucket bug, produced 540 HTTP req/min against 60/min limit; 10h of abuse triggered infrastructure block | Active |
| 2026-03-06 | Confirmed production rate limit is 60/min not 100/min | Live header `X-RateLimit-Limit: 60`; token bucket default corrected to 55/min; second API key = independent 60/min window | Active |
| 2026-03-06 | Sequential is faster than concurrent for this API | 1 worker ~25-150/min (zero 429s); 16 workers ~10/min (constant 429s); correct parallelism is across machines/IPs | Active |
| 2026-03-06 | Hetzner VM for long-running scrapes | CX23 Nuremberg, ~€0.43/day; lower latency → higher throughput; tmux + watchdog for resilience; DB copied back via scp | Active |
| 2026-03-06 | Comment API hard cap: 500/post, no pagination | Posts with >500 comments are truncated to top 500; affects 1,507 remaining posts; sufficient for research purposes | Active |
| 2026-03-06 | Agent enrichment: only 7,188 stubs (not 166K) | 158,880 agents already have descriptions from embedded API objects; enrich stage is ~50 min on VM | Active |
| 2026-03-06 | ExtraE113/moltbook_data has only ~165K posts (9%) | Uses offset-based pagination which hits API depth cap; our cursor-based scrape (1.74M posts, 93%) is irreplaceable | Active |
| 2026-03-11 | All scraping stages complete | Comments: 2,725,187 (167 unreachable posts); agents: 166,998 (7,160 genuinely have no description); snapshots created | Complete |
| 2026-03-11 | `--only-missing` flag for `enrich` command | Prevents re-fetching 166K agents (~111h) when only stubs need enrichment (~48 min); added `get_unenriched_agent_names()` to DB | Active |
| 2026-03-13 | Schema migrations for new API fields | Added type, is_locked, is_spam, verification_status, updated_at, score, hot_score (posts); is_spam, depth, reply_count, verification_status, updated_at, score (comments); display_name, posts_count, comments_count, is_active, is_verified, last_active (agents) | Active |
| 2026-03-13 | Deletion detection for posts and agents | `--detect-deletions` on posts marks unseen posts after full pagination; agent enrichment catches 404 → sets `deleted_at`; comment deletion already existed | Active |
| 2026-03-13 | Weekly/monthly automation cadence on Hetzner | Weekly (Mon 02:00 UTC): incremental + comments + enrich + snapshots; Monthly (1st 02:00 UTC): full re-scrape with deletion detection; lock file prevents overlap; email alerts via msmtp | Active |
| 2026-03-13 | Snapshot tables include new columns | Snapshot migrations add same columns as live tables; `create_snapshots()` SELECTs and saves all new fields | Active |
| 2026-03-16 | Weekly scrape takes ~8-10h, not ~1-2h | Moderators stage fetches all 19.6K submolts at ~47/min = ~7h; this is the bottleneck. Comments for weekly gap (~20K posts) takes ~1-2h. Total ~8-10h. | Active |
| 2026-03-16 | Comments throughput varies by post weight | Lightweight posts (few comments): ~130 posts/min; heavy posts (500+ comments): ~25/min. Session 12 catch-up averaged 130/min because new posts are light | Active |
| 2026-03-16 | Windows → Linux: always dos2unix after scp | Shell scripts and Python files from Windows have `\r\n` line endings that break bash `set -euo pipefail` and shebang lines. Run `dos2unix src/*.py scripts/*.sh` on VM after every code push | Active |
| 2026-03-16 | SSH config alias `vm` for Hetzner | `~/.ssh/config` maps `vm` → `root@159.69.34.240` with `hetzner_key`. Use `ssh vm`, `scp vm:...` instead of full commands | Active |
| 2026-03-16 | All scraping jobs run on VM, not locally | VM has lower latency to API, doesn't tie up local machine. Only run locally if job is short (<1h) and user explicitly approves | Active |
| 2026-03-16 | status.sh: use `find` not `ls glob` under `set -e` | `ls *.db` fails with exit 2 when no files match; `find -name '*.db'` returns empty without error. Glob expansion under `set -e` is a bash footgun | Active |