# Claude Handover - Moltbook Scraper

**Last updated**: 2026-02-28 (session 4)
**Git state**: Branch `affectionate-lamport`, 4 files modified, uncommitted (see below)
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Uncommitted changes (session 4)

All four files below are modified and staged-but-not-committed:

| File | What changed |
|------|-------------|
| `src/client.py` | Full rewrite aligning with upstream `787f2d9`: removed sliding-window throttle (cold-start burst bug), added `_normalize_agent()`, cursor-based posts pagination, separate comments endpoint, page-based submolts pagination, corrected stats field names (`totalAgents` etc.), new `fetch_submolt_detail` |
| `src/scraper.py` | Import `_normalize_agent`; apply to submolt `created_by` and post authors; upsert embedded submolt from post; updated comment cap note (~200, not 1,000) |
| `data/README.md` | Updated platform scale, pagination notes, enrich explanation, corrected comment cap, scrape time estimates |
| `claude_handover.md` | This file |

**Commit when ready:**
```powershell
git add src/client.py src/scraper.py data/README.md claude_handover.md
git commit -m "Align with upstream API changes: cursor pagination, separate comments endpoint, normalize agents"
```

---

## Next Immediate Steps

### 1. Commit session 4 changes (above)

### 2. Run posts scrape (~3-4 hours)
```powershell
.venv\Scripts\python -m src.cli posts --db data/raw/moltbook.db --log-file logs/scrape-posts.log
```
Monitor with: `tail -20 logs/scrape-posts.log` (filter throttle noise with `grep -v WARNING`)

### 3. Run moderators scrape (~3-4 hours, can run alongside posts if separate terminal)
```powershell
.venv\Scripts\python -m src.cli moderators --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
```

### 4. Run comments scrape (~10-14 days — must background or use HPC)
```powershell
.venv\Scripts\python -m src.cli comments --only-missing --db data/raw/moltbook.db --log-file logs/scrape-comments.log
```
See HPC note below. This is the primary bottleneck.

### 5. Run enrich scrape (days–weeks — must background or use HPC)
```powershell
.venv\Scripts\python -m src.cli enrich --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
```
Enriches full agent profiles for every unique author found in posts+comments. Count unknown until posts/comments are done; could be 500K–2M agents.

### 6. Run snapshots (seconds — required before R analysis)
```powershell
.venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
```

### Still TODO (pre-existing)
- **Fix test failure**: `test_fetch_all_posts_paginates_until_no_more` — stop condition mismatch, now more pressing since posts pagination has changed to cursor-based
- **Design daily/weekly scrape automation** — Windows Task Scheduler vs. manual for `scripts/daily_scrape.ps1`
- **Wire `--log-file` through `daily_scrape.ps1`** — currently tees stdout instead

---

## HPC note

Comments (~10-14 days) and enrich (weeks) are impractical to run on a local machine that may sleep or restart. `scripts/run_on_hpc.sh` exists from the original author but is tied to their cluster. To adapt it for a different HPC, Claude will need the following information from you:

- **Job scheduler**: Which system does the cluster use? (SLURM, PBS/Torque, SGE, LSF — ask IT or run `sinfo`/`qstat`)
- **Python/conda**: How is Python loaded? (e.g. `module load anaconda`, or path to conda init script)
- **Repo location**: Where on the cluster will the repo be cloned?
- **Scratch/data path**: Where should the DB be written? (home dir, `/scratch/`, `/data/` etc. — large files often can't live in `$HOME`)

Data written on the HPC stays on HPC storage. Transfer back with:
```bash
rsync -avz --progress username@hpc.edu:~/moltbook_scraper/data/raw/moltbook.db data/raw/moltbook.db
```
Use `rsync` not `scp` — the DB will be several GB and must be resumable.

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (5.1 MB now, will reach several GB after comments+enrich; gitignored via `data/` and `*.db`)
- **DB write behaviour**: UPSERT throughout — re-running any stage updates in place, never deletes. Safe to re-run after failure.
- **Schema**: `src/database.py:_create_tables()` is authoritative. Human-readable: `data/README.md`.
- **Rate limit**: 100 req/min (API); client uses reactive exponential backoff on 429 (no proactive throttle)
- **Upstream**: `daveholtz/moltbook_scraper` — run `git fetch upstream` before each session to catch API drift
- **Platform scale** (2026-02-28): 2.85M agents, 1.67M posts, 12.5M comments, 18,625 submolts
- **Completed work archive**: `claude_archive.md`

---
