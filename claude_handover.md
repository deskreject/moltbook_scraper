# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-02 (session 5)
**Git state**: Branch `main`, 1 commit ahead of origin/main (not yet pushed), 1 untracked file
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Active process

**Posts scrape is currently running** (started ~20:38 on 2026-03-02):

```powershell
# Still running — do NOT restart
.venv\Scripts\python -m src.cli posts --db data/raw/moltbook.db --log-file logs/scrape-posts.log
```

Check progress with:
```powershell
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/raw/moltbook.db'); print(c.execute('SELECT COUNT(*), MIN(created_at) FROM posts').fetchone())"
```

Expected completion: scrape walks backward from Mar 2 to ~Jan 15 2026 (platform launch). At ~219K posts and Feb 21 oldest at session end; several more hours to reach Jan 15. Scraper exits cleanly when `has_more=False`.

---

## Uncommitted changes

| File | What / Why |
|------|-----------|
| `scripts/monitor_posts.sh` | Monitoring helper added this session — should be committed |

One commit not yet pushed to `origin/main`:
- `fc8a489` — "Switch posts scrape to sort=new for full archive coverage"

**Commit + push when posts scrape completes successfully:**
```powershell
git add scripts/monitor_posts.sh
git commit -m "Add posts scrape monitoring script"
git push origin main
```

---

## Next Immediate Steps

### 1. Wait for posts scrape to finish
Monitor with the DB count check above. Expect `has_more=False` exit and a final count near the platform total (~1.73M posts). If it exits with a ValidationError, check the count — if it reached ≥1.6M it likely just finished; if far short, re-run.

### 2. Run moderators scrape (~3-4 hours)
```powershell
.venv\Scripts\python -m src.cli moderators --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
```
Iterates over all 18,625 submolts (1 req each). Safe to run in a second terminal while posts finishes, but watch disk — DB will be growing rapidly while posts runs.

### 3. Run comments scrape (~10-14 days — needs background or cloud VM)
```powershell
.venv\Scripts\python -m src.cli comments --only-missing --db data/raw/moltbook.db --log-file logs/scrape-comments.log
```
1 req/post × ~1.73M posts ÷ 100 req/min = ~12 days. Recommended approach: rsync DB to a cheap cloud VM (Hetzner CX22 ~€5 total, or DigitalOcean ~$7) and run with `tmux`. See Cloud VM section below.

### 4. Run enrich scrape (weeks — cloud VM required)
```powershell
.venv\Scripts\python -m src.cli enrich --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
```
Fetches full agent profiles for every unique agent stub. Agent count after posts+comments will be 500K–2M. Impractical locally.

### 5. Run snapshots (seconds — required before R analysis)
```powershell
.venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
```

### 6. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination and `sort` parameter.

---

## Cloud VM option for long scrapes

The DB is a single SQLite file — the cross-machine workflow is:
1. rsync DB to VM after posts + moderators complete
2. Run comments + enrich on VM (days/weeks)
3. rsync DB back for R analysis

```bash
# Push DB to VM
rsync -avz --progress data/raw/moltbook.db user@vm-ip:~/moltbook_scraper/data/raw/moltbook.db

# Pull DB back
rsync -avz --progress user@vm-ip:~/moltbook_scraper/data/raw/moltbook.db data/raw/moltbook.db
```

UPSERT design means it is safe to re-run any stage after rsync — no duplicates, no data loss.

Recommended providers: **Hetzner CX22** (~€5/2 weeks, 40 GB disk) or **DigitalOcean Basic** (~$7/2 weeks). Use `tmux` to keep process alive after SSH disconnect.

**HPC alternative**: `scripts/run_on_hpc.sh` exists (original author's SGE cluster) but needs rewrite. Before adapting, get from university IT: (a) outbound HTTPS allowed from compute nodes? (b) job scheduler (SLURM/PBS/SGE/LSF)? (c) max walltime? (d) Python/conda setup? (e) scratch path + quota?

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (~281 MB mid-scrape; will reach several GB after comments+enrich)
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe, never deletes data
- **Schema**: `src/database.py:_create_tables()` is authoritative. Human-readable: `data/README.md`
- **Rate limit**: 100 req/min; client uses reactive exponential backoff on 429 (no proactive throttle)
- **Upstream**: `daveholtz/moltbook_scraper` — run `git fetch upstream` before each session
- **Platform scale** (2026-03-02): ~2.85M agents, ~1.73M posts, ~12.65M comments, ~18,703 submolts
- **Platform launched**: ~Jan 15 2026 (inferred via cursor injection; no posts exist before this date)
- **Completed work archive**: `claude_archive.md`
