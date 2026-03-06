# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-06 (end of session 8)
**Git state**: Branch `main`, 4 commits ahead of origin/main (not yet pushed); 6 files locally modified (uncommitted — see below)
**Machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Active process

**No scraper running.** All processes were stopped at end of session 8.

**IP is currently blocked** at the infrastructure level (Cloudflare/nginx). The block does NOT return `X-RateLimit-*` headers — it is not the application-level 60/min limit. Caused by ~10 hours of 540 req/min (token bucket bug). Cooldown is 15+ minutes; may already have cleared by next session.

**To test if block has cleared:**
```powershell
# Quick API test — if 200, block is cleared
.venv\Scripts\python -c "from src.client import MoltbookClient; import os; c = MoltbookClient(os.getenv('MOLTBOOK_API_KEY')); r = c._request('GET', c.BASE_URL + '/stats'); print(f'status={r.status_code}'); print({h: r.headers[h] for h in r.headers if 'ratelimit' in h.lower()})"
```

---

## Current DB state (2026-03-06)

| Table | Count |
|-------|-------|
| posts | 1,742,447 |
| agents (stubs) | 165,604 |
| submolts | 18,673 |
| comments | ~600K (done for ~19,646 / 453,670 posts) |
| moderators | 13,741 rows (13,645 submolts with mods) |

---

## Next Immediate Steps

### 1. Resume comments scrape (SEQUENTIAL — do not use workers)

Once IP block clears (or after switching VPN server):
```powershell
# Sequential mode — NO --workers flag, NO token bucket
# Achieves ~25 req/min, well under 60/min limit, zero 429s
.venv\Scripts\python -u -m src.cli comments --only-missing --skip-empty --db data/raw/moltbook.db --log-file logs/scrape-comments.log
```

**DO NOT use `--workers > 1`** — see `readme_api_limit.md` for full analysis. Sequential is 2.5x faster than concurrent for this API.

Remaining: ~434K posts × 25 req/min ≈ **12 days** on single machine.

### 2. When comments complete: STOP — do not auto-start enrich

User wants to evaluate parallelization options first:
- **Option A: Second API token + different IP** — each machine runs sequential with its own token from a different IP; UPSERT design handles merge
- **Option B: Cloud VM** — Hetzner CX22 (~€5/2 weeks) or DigitalOcean Basic (~$7/2 weeks); rsync DB to VM, run there, rsync back
- **Option C: University HPC** — outbound HTTPS from compute nodes is the key question for IT

**Critical**: Multiple tokens from the same IP do NOT help — infrastructure blocks by IP, not by token.

### 3. Snapshots (run locally after comments complete)
```powershell
.venv\Scripts\python -m src.cli snapshots --db data/raw/moltbook.db
```
Takes <1 min; required before R analysis.

### 4. Enrich agents (~165,604 stubs)
Run sequential (1 worker). At ~25 req/min: 165,604 / 25 ≈ 4.6 days.
Cloud VM or second IP recommended to parallelize.

### 5. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination and `sort` parameter.

### 6. Commit and push sessions 7–8 changes
```bash
git add src/cli.py src/client.py CLAUDE.md claude_handover.md claude_archive.md readme_api_limit.md
git commit -m "Sessions 7-8: rate limit fixes, limit=500, --rate-limit flag, API investigation docs"
git push origin main
```

---

## Rate Limit — Key Findings (session 8)

Full investigation documented in **`readme_api_limit.md`**.

### Two-layer rate limiting
| Layer | Identifier | Limit | Cooldown | Headers |
|-------|-----------|-------|----------|---------|
| Application (`rateLimit.js`) | API token | 60/min | 1 minute | Yes (`X-RateLimit-*`) |
| Infrastructure (Cloudflare/nginx) | IP address | Unknown | 15+ minutes | No |

### Why sequential beats concurrent
- Sequential (1 worker, no bucket): ~25 req/min, zero 429s, network latency bound
- Concurrent (16 workers, 55/min bucket): ~10 req/min, constant 429s, token contention
- **Correct parallelism**: multiple machines/IPs, each running sequential

### Bugs fixed this session
1. Token bucket `capacity=9` → `capacity=1.0` (no burst)
2. `acquire()` moved inside retry loop (retries were bypassing bucket — 6x actual HTTP rate)
3. Default rate corrected from 90 → 55/min (production limit is 60, not 100)

---

## Cloud VM / Second Token Strategy

### Key constraint: different IPs required
Multiple tokens from the same IP share the infrastructure-level block. Each parallel scraper needs:
- A **different IP address** (cloud VM, different VPN server, etc.)
- A **different API token**
- A **subset of post_ids** (split by rowid range)
- **Sequential mode** (1 worker, no token bucket)

### rsync workflow
```bash
# Push to VM
rsync -avz --progress data/raw/moltbook.db user@vm-ip:~/moltbook_scraper/data/raw/moltbook.db

# Pull back
rsync -avz --progress user@vm-ip:~/moltbook_scraper/data/raw/moltbook.db data/raw/moltbook.db
```
UPSERT design means merge is always safe.

---

## Uncommitted Changes (sessions 7–8)

| File | Change |
|------|--------|
| `src/cli.py` | Added `--rate-limit RPM` flag; default when workers>1 corrected from 90 → 55/min |
| `src/client.py` | `fetch_comments_only()` passes `limit=500`; `_TokenBucket` capacity=1.0 (no burst); `acquire()` moved inside retry loop |
| `CLAUDE.md` | Rate limit corrected to 60/min production; methodology log updated |
| `claude_handover.md` | This file |
| `claude_archive.md` | Sessions 7–8 entries |
| `readme_api_limit.md` | **NEW** — comprehensive rate limit investigation log |

---

## Key Reference

- **DB path**: `data/raw/moltbook.db`
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe
- **Schema**: `src/database.py:_create_tables()` authoritative; human-readable: `data/README.md`
- **Background scrapes**: always use `python -u` flag (unbuffered stdout)
- **Rate limit docs**: `readme_api_limit.md` — read before changing any rate limit settings
- **Upstream**: `daveholtz/moltbook_scraper` — run `git fetch upstream` before each session
- **Platform scale** (2026-03-06): ~2.85M agents, ~1.87M posts, ~12.9M comments
- **Platform launched**: ~Jan 15, 2026
- **Completed work archive**: `claude_archive.md`
- **Git commits not yet pushed**: 4 (fc8a489, 550ea29, 3542aa1, e448cf5)
