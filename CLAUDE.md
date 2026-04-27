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

# Monthly cron (every Tue 01:55 UTC; script exits on non-first-Tuesdays)
# First Tuesday lands after the Monday weekly, avoiding the 1st-Monday collision
# class entirely. Subsequent Mondays during the monthly run skip via sentinel.
55 1 * * 2  cd ~/moltbook_scraper && bash scripts/monthly_rescrape.sh

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

### Snapshot policy (Phase 3 design — see session 21 log for rationale)

After the Phase 3 redesign, the snapshot layer is **change-driven and narrow**, not a weekly full dump. Policy by column type:

- **Text / URL / JSON on an immutable entity** (posts.title, posts.content, comments.content, author_name, submolt_name, post url): stored on the **live table only, never snapshotted**. Posts and comments are immutable after creation per the 2026-04-14 audit (0.0000 % change across 6.2 M post-pairs and 9.88 M comment-pairs).
- **Text on a mutable entity** (agents.description, submolts.description): **first + latest anchor** on the live table via `*_first` and `*_latest` columns.
- **Numeric counters** (karma, follower_count, following_count, upvotes, downvotes, comment_count, subscriber_count): **change-driven inserts** into `*_metrics` panels. Posts use a 4-week age cutoff; other entities have no cutoff.
- **Booleans / enum state** (is_pinned, is_locked, is_deleted, is_spam, is_claimed, verification_status, moderator role): **event log** in `*_events` tables, one row per transition. Initial state is captured in the `*_first` anchor columns on live tables (Migration 10) — events are ONLY emitted for subsequent transitions. First observation is NOT an event.
- **Cosmetic URLs** (avatar_url, banner_url): live table only; dropped from snapshots entirely.
- **Hot-score**: `posts.hot_score_first` + `posts.hot_score_first_observed_at` on live table. Decay is fast enough that first-observed is the only interpretable value.

**Consequences for analysis (R code):**
- Queries that joined `post_snapshots` / `comment_snapshots` for content must now read content from `posts` / `comments` directly. Content is preserved across the lifetime of the entity.
- Queries that need vote trajectory read from `post_metrics` (only for posts seen within 4 weeks of creation) or use `upvotes` / `downvotes` on the live table for a single latest value.
- Queries that need state transitions (was this post pinned in week X?) read from `post_events` / `agent_events` / etc.
- Compatibility VIEWs named `*_snapshots` will be provided during Phase 4 to ease R migration; they will be retired after R code is updated.

### Deletion-content preservation

`upsert_post` and `upsert_comment` use a guard clause: `content = CASE WHEN is_deleted = 1 THEN <table>.content ELSE excluded.content END`. Once a post or comment is marked deleted, its content is never overwritten, even if the API later returns a tombstone form.

### Weekly / monthly cron coordination

- Monthly cron fires every Tuesday 01:55 UTC; `monthly_rescrape.sh` exits cleanly when day-of-month > 7. Net effect: monthly runs on the first Tuesday of each month, always after that week's Monday weekly. The `.monthly_running` sentinel is written at start and removed via `trap EXIT INT TERM`.
- Weekly checks the sentinel at start; skips with a log line if present and <7 days old, proceeds with a warning otherwise (stale-lock recovery). The Mondays that fall during a 5–7 day monthly run skip cleanly because monthly is a superset.
- Sharding by submolt first-letter (A-H, I-P, Q-Z) is a planned future change to keep each monthly run inside the 7-day window — see methodology log entry. **Not yet implemented as of 2026-04-27.**

### Legacy note

`*_snapshots` tables contain the historical full-dump state from 2026-03-11 through the Apr 20 weekly snapshot stage (last write 2026-04-23 12:23 UTC). They have **stopped growing** as of the Apr 24 Phase 3a deployment — `create_snapshots()` no longer writes to them. Phase 4 (planned this week, post-Apr-27-weekly) will archive or drop them to reclaim ~30 GB inside the live DB.

Row counts as of 2026-04-27: post_snapshots 11.2M, comment_snapshots 18.5M, agent_snapshots 866K, submolt_snapshots 100K, moderator_snapshots 92K.

### Backup retention policy

Disk budget on the 100 GB Hetzner volume:

- **Live DB**: working copy. Post-Phase-4 target: ~14 GB.
- **Latest weekly backup** (`moltbook-weekly-YYYY-MM-DD.db`): one retained, pruned at end of next weekly run. Defends against any single week's corruption / accidental delete.
- **Latest monthly-post backup** (`moltbook-monthly-post-YYYY-MM-DD.db`): one retained, pruned at end of next monthly run. Long-term archival snapshot.
- **No pre-monthly backup** — the latest weekly already provides a "before monthly" recovery point (≤ 7 days stale). Dropped 2026-04-27 (session 24) for disk-budget reasons; risk accepted.

Steady state: live DB + 2 backups ≈ 3 × ~14 GB = ~42 GB. Peak during overlap window: ~56 GB.

### Snapshot monitoring (R1 — for new change-driven writer)

Each snapshot run logs per-table: `entities_scanned`, `inserted_metrics`, `inserted_events`. Expected ranges and alerts:

- **Normal**: `inserted_metrics` is a small fraction of `entities_scanned` (1–10 % for active entities; near-zero for mature ones). `inserted_events` very small (state transitions are rare).
- **Alert A — change detection broken, writing too much**: `inserted_metrics > 0.5 × entities_scanned` on a mature table. Diff comparison is failing; storage will explode. Stop cron, inspect `scraper.create_snapshots()`.
- **Alert B — change detection broken, writing nothing**: `inserted_metrics == 0` on a table with ≥1000 entities scanned where platform values have clearly moved. Write path is silently failing. Stop cron, inspect logs.
- **Alert C — event log exploding**: `inserted_events > 1000` per run (excluding moderators on the very first post-migration run — see below). Should be dozens otherwise. Likely boolean comparison bug (e.g. `0` vs `False`). Inspect event writer.
- **One-time exception**: the first snapshot after Migration 10 is expected to emit ~20k moderator events (baseline "added" for all pairs active at observation start). `post_events` and `agent_events` should be 0 on first run (initial state captured in `*_first` anchors).
- **Where**: tail of `logs/scrape-snapshots.log` after each weekly run.

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

