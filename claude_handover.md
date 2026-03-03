# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-03 (session 6)
**Git state**: Branch `main`, 3 commits ahead of origin/main (not yet pushed)
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Active process

**Moderators scrape is currently running** (started ~16:30 on 2026-03-03):

```powershell
# Still running — do NOT restart
.venv\Scripts\python -m src.cli moderators --workers 4 --db data/raw/moltbook.db --log-file logs/scrape-moderators.log
```

Check progress with:
```powershell
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/raw/moltbook.db'); mods=c.execute('SELECT COUNT(*) FROM moderators').fetchone()[0]; done=c.execute('SELECT COUNT(DISTINCT submolt_name) FROM moderators').fetchone()[0]; print(f'mods: {mods:,}, submolts processed: {done:,}')"
```

Expected completion: all 18,673 submolts. ~3-7 hours from start (rate is ~43 req/min
with --workers 4 + token bucket at 90/min; moderators scrape is UPSERT-safe so
re-running is harmless if interrupted).

---

## Current DB state (2026-03-03)

| Table | Count |
|-------|-------|
| posts | 1,742,447 |
| agents (stubs) | 165,604 |
| submolts | 18,673 |
| comments | 35,525 (scraped for 1,313 / 453,670 posts) |
| moderators | 705 rows |

---

## Next Immediate Steps

### 1. Wait for moderators to finish, then run comments (~2-3 days)
```powershell
.venv\Scripts\python -m src.cli comments --only-missing --skip-empty --workers 4 --db data/raw/moltbook.db --log-file logs/scrape-comments.log
```
- `--skip-empty` skips the 74% of posts with comment_count=0 (1.29M posts) → 453,670 to process
- `--workers 4` with auto token bucket at 90 req/min → estimated ~3.6× faster than sequential
- Estimated duration: ~453,670 / 90 req/min = ~84 hours = ~3.5 days (vs. 19 days sequential)
- Already scraped 1,313 posts; resumable (UPSERT + only-missing skips done ones)

### 2. Run enrich (~weeks — cloud VM or second API key recommended)
```powershell
.venv\Scripts\python -m src.cli enrich --workers 4 --db data/raw/moltbook.db --log-file logs/scrape-enrich.log
```
165,604 agent stubs to enrich. With --workers 4: same rate as comments (~90 req/min vs. 25 req/min sequential).

### 3. Run snapshots (seconds — required before R analysis)
```powershell
.venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
```

### 4. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination and `sort` parameter.

---

## Speed Optimizations (implemented session 6)

Three-stage optimization implemented and tested (30+ min each):

| Step | Flag | Effect | Tested |
|------|------|--------|--------|
| 1 | `--skip-empty` | Skip 74% of posts (comment_count=0) → 3.7× fewer requests for comments | ✓ |
| 2 | `fetch_comments_only()` | 1 req/post instead of 2 → ~1.7× speedup on comments | ✓ |
| 3 | `--workers N` | Concurrent HTTP workers, DB writes in main thread; token bucket at 90/min auto-enabled when N>1 | ✓ |

**Combined flags for comments**: `--only-missing --skip-empty --workers 4`

**Throughput observations** (measured):
- Sequential (1 worker): ~25 req/min (network latency bottleneck, 2.4s/req)
- 4 workers without token bucket: ~16 req/min (thundering herd 429s)
- 4 workers WITH token bucket: ~43 req/min for moderators endpoint (fast responses); comments endpoint (slow responses, 2-4s) should see ~3-4× improvement

---

## Cloud VM option for long scrapes

The DB is a single SQLite file — the cross-machine workflow is:
1. rsync DB to VM after moderators complete
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

---

## Second API Key Option

If a second API key is obtained: run comments on two machines simultaneously by:
1. Split post_ids into two halves (e.g. by rowid)
2. Run comments scrape on machine A (first half) + machine B (second half) in parallel
3. rsync both DBs back and combine — UPSERT ensures no duplicates

No code changes needed; the DB's UPSERT design handles this naturally.

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (~1.3 GB; will reach several GB after comments+enrich)
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe, never deletes data
- **Schema**: `src/database.py:_create_tables()` is authoritative. Human-readable: `data/README.md`
- **Rate limit**: 100 req/min advertised; actual effective rate ~25-50 req/min; client uses reactive exponential backoff on 429 + optional proactive token bucket
- **Upstream**: `daveholtz/moltbook_scraper` — run `git fetch upstream` before each session
- **Platform scale** (2026-03-02): ~2.85M agents, ~1.73M posts, ~12.65M comments, ~18,703 submolts
- **Platform launched**: ~Jan 27, 2026 (confirmed via sort=new)
- **Completed work archive**: `claude_archive.md`
- **Git commits not yet pushed**: 3 (fc8a489, 550ea29, 3542aa1)
