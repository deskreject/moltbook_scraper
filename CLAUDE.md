# CLAUDE.md - Project Guide for Moltbook Scraper

Keep this file ≤ 150 lines (max 200). If it grows, move detail to its real home — `data/README.md` (data model), `claude_methodology_log.md` (decisions), `readme_api_limit.md` (rate limits), or a session log (rationale) — and leave a pointer here.

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
python -u -m src.cli comments --only-missing --skip-empty --db data/raw/moltbook.db --log-file logs/scrape-comments.log
python -u -m src.cli enrich --only-missing --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
python -u -m src.cli moderators --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
python -m src.cli snapshots --db data/raw/moltbook.db

# Database status / fetch platform docs
python -m src.cli status --db data/raw/moltbook.db
python -m src.cli docs

# Full re-scrape with deletion detection (monthly only)
python -u -m src.cli posts    --db data/raw/moltbook.db --detect-deletions --log-file logs/scrape-posts.log
python -u -m src.cli comments --db data/raw/moltbook.db --detect-deletions --log-file logs/scrape-comments.log
```

**Always run sequential** (`--workers 1`, the default). Multi-worker is slower for this API and trips the infra rate limit — see `readme_api_limit.md` / `claude_learnings.md`.

### VM Automation (Hetzner)

```bash
# Weekly cron (Mon 02:00 UTC): 6 stages — incremental, submolts, comments, moderators, enrich, snapshots.
# Steady-state ~20 h (NOT 8-10 h); moderators is the swing stage (~12 h, spikes to ~30 h under API back-pressure). See session-30 log §1.
0 2 * * 1  cd ~/moltbook_scraper && bash scripts/weekly_scrape.sh

# Monthly cron (every Tue 01:55 UTC; script exits on non-first-Tuesdays). CURRENTLY DISABLED — see handover.
55 1 * * 2  cd ~/moltbook_scraper && bash scripts/monthly_rescrape.sh

# Daily disk monitor (08:00 UTC): emails if >80% on either disk
0 8 * * *  cd ~/moltbook_scraper && bash scripts/disk_monitor.sh

# Status (from local) / pull DB / push code (then dos2unix!)
ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'
scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/
scp -r src/ scripts/ vm:~/moltbook_scraper/
ssh vm 'cd ~/moltbook_scraper && dos2unix src/*.py scripts/*.sh'
```

**VM storage layout**: DB and backups live on the Hetzner volume (`/mnt/HC_Volume_104999576/moltbook_data/`), symlinked from `data/raw/` and `data/backups/`. All paths in scripts and `scp` commands work unchanged.

### Testing

```bash
# Scope to specific files — a bare `pytest` HANGS on test_fetch_all_posts_paginates_until_no_more
# and orphans GBs of RAM (see claude_learnings.md "Process & Workflow").
pytest tests/test_client.py -v
```

## Configuration

- **Env**: `MOLTBOOK_API_KEY` required for scraping (set in `.env`).
- **DB**: SQLite at `data/raw/moltbook.db` (gitignored; ~8-9 GB). Live tables `agents`, `posts`, `comments`, `submolts`, `moderators`; change-driven history in `*_metrics` (counter trajectories) + `*_events` (state transitions). Legacy `*_snapshots` were dropped in Phase 4 (2026-05-03).
- **Schema**: `src/database.py:_create_tables()`; **canonical data dictionary: `data/README.md`**.

## Code Conventions

- refer to /CLAUDE/project_specific_rules/ for guides specific to the language used (python, R etc.)

## Output conventions

from the project directory
- **Tables**: Save all tables to /tables
- **Figures** save all figures to /figures
- **claude scripts** save all figures to code named "claude_xxx.r"
- **session logs** save all session logs to /CLAUDE/session_logs

## Process logs

- **session memory** save what you did and what was learned in brief, but parsimonious way to the session logs in the form of "yyyy_mm_dd_session_log".
- **handover document** outline next steps to the file handover.md in a way that can be complemented by the session logs. I.e. reference in which session log the relevant further information to understand the next steps can be
- **Claude.md** should contain only rules about how Claude should behave and any key, timeless information. No superfluous detail that could be contained in other .md files
- **claude_methodology_log** should contain any information on processes or decisions made that need to be documented for scientific reproducability. in a table format
- **learnings.md** should document errors, failures, choke points or dead ends that were encountered and how they were solved including things that were tried and didn't work or were refused by me with the associated reason. The purpose is to stop pursuing directions that were tried in the past.
- **achive file**  It should be a archive.md file with condensed entries by date of things that were removed from handover, Claude.md and learning.md that are no longer relevant for each session but that offer a very parsimonious bread crumb trail.

## Reference & invariants (details live in the linked docs — do not duplicate here)

- **Data model & schema** → `data/README.md` (canonical): live tables, the change-driven `*_metrics` / `*_events` layers, `*_first`/`*_latest` anchors, query patterns, deletion-content-preservation guard. Rationale: methodology log (2026-04-14, 2026-04-20) + session 21 log.
- **API quirks** → methodology log (2026-02-28 / 03-02 / 03-05): comments hard-capped 500/req (no pagination); posts cursor-paginated, MUST use `sort=new` for the full archive; submolts page-based (20/page); embedded author objects are camelCase → `_normalize_agent()`. Follower/following graph not exposed (counts only).
- **Rate limits** → `readme_api_limit.md` (top block) + session-30 log §2/§5: regime changed 2026-05-29 (tiered limiter + CloudFront; sequential ~25/min is safe; `_request` honors `Retry-After`). Dead ends — no `--workers > 1`, no proactive throttling (`claude_learnings.md`).
- **Snapshot health check** (after each weekly, tail `logs/scrape-snapshots.log`): alert if `inserted_metrics > 0.5×entities_scanned` (over-writing), `inserted_metrics == 0` on a table that clearly moved (silent fail), or `inserted_events > 1000` (likely boolean-compare bug). Full R1 spec: session 21 log.
- **Cron coordination & backups** → methodology log (2026-04-20, 2026-04-27): weekly Mon 02:00 / monthly first-Tuesday; `.monthly_running` sentinel lets an overlapping weekly skip cleanly; retention = latest weekly + latest monthly-post only.

## Research Ethics

- Scraper account: `moltbook_archiver` (read-only, no posting). Data describes AI agents, not human subjects. Public API access with a dedicated research account.

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
- **Code changes** [session 30]: identify new fail-states (test them, or state why none are plausible); leave a revert-trail — a comment at the change site + a pointer in a suitable `.md` to the session log explaining why.

## Context & Token Economy
- **Logs**: never `Read` a full scrape log (can be 100k+ lines). `tail`/`head` first, or read the last ~100 lines when diagnosing.
- **Large files / queries**: if > 5,000 lines, read only the relevant section. Never dump full DB results into chat — `LIMIT 10` to explore, `COUNT(*)` to size.
- **Error-loop breaker**: if the same call fails 3× in a row, or a fix→test cycle fails 3×, stop and summarize rather than retrying with minor variations.
- **Scrape cost**: state estimated duration + API call count before starting; background anything running > 10 min in the foreground.

## Data Hygiene
- Large databases (>100MB) live in `data/raw/` (gitignored). Only `.rds` summaries go in `data/processed/`.
- Always use `data/raw/moltbook.db`; do not store the DB in the project root.
- R scripts in `analysis/R/` expect the DB at `../../data/raw/moltbook.db`. Update `utils.R:connect_db()` if the path changes.
