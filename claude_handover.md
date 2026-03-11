# Claude Handover - Moltbook Scraper

**Last updated**: 2026-03-11 (session 9)
**Git state**: Branch `main`, clean after this commit
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-03-11)

| Table | Count | Status |
|-------|-------|--------|
| posts | 1,742,447 | Complete (93.4% of platform's 2.01M) |
| submolts | 18,673 | Complete (97.0% of platform's 19,241) |
| moderators | 13,741 | Complete |
| comments | 2,725,187 | Complete (167 posts unreachable — stale comment_count, API returns empty) |
| agents | 166,998 | Complete. 7,160 have no description (genuinely unset on platform, not a scraping gap) |
| snapshots | 1,742,447 post / 2,725,187 comment / 166,998 agent / 18,673 submolt / 13,741 mod | Created 2026-03-11 |

**DB size**: 5.7 GB (3.0 GB live + 2.7 GB snapshots)
**DB path**: `data/raw/moltbook.db`

---

## Scraping Complete — All Stages Done

All scraping stages are finished. The data is ready for analysis.

### Comments scrape (Hetzner VM)
- **Ran**: 2026-03-06 14:27 → 2026-03-10 21:13 UTC (~4.7 days)
- **Result**: 433,850/433,855 posts processed, 2,066,042 comments, 8 errors, 63 rate-limits
- **Mop-up** (2026-03-11): 2,725 remaining posts → 29,918 additional comments, 0 errors
- **Unreachable**: 167 posts have `comment_count > 0` but API returns empty (stale counts, likely deleted comments)

### Agent enrichment
- 7,159/7,160 stubs enriched (1 likely-deleted agent). All stubs genuinely have no description (bio not set on platform).
- Added `--only-missing` flag to `enrich` command to avoid re-fetching all 166K agents (~111h) vs only stubs (~48 min).

---

## Hetzner VM — Ready to Delete

**VM**: Hetzner CX23, Nuremberg, IP `159.69.34.240`, Ubuntu 24.04
**Cost**: ~€0.43/day. Running since 2026-03-06 ≈ €2.15 total.
**Status**: Scraper stopped, watchdog still running. DB copied to local. Safe to delete.
**Backups on VM**: 3 rolling backups in `~/moltbook_scraper/data/backups/`

---

## Next Steps

### 1. Run R analysis pipeline
```bash
cd analysis/R
Rscript 01_load_data.R   # Creates analysis/data/*.rds from snapshots
Rscript 02_structural.R  # Power-law fits, Gini, growth plots
# ... etc.
```

### 2. Fix pre-existing test failure
`test_fetch_all_posts_paginates_until_no_more` — needs update for cursor-based pagination and `sort` parameter.

### 3. Delete Hetzner VM
From Hetzner Cloud console. Stop billing.

---

## Rate Limiting — Key Facts

Full investigation: `readme_api_limit.md`

| Layer | Identifier | Limit | Cooldown |
|-------|-----------|-------|----------|
| Application | API token | 60/min (header says 60, source says 100) | 1 min |
| Infrastructure | IP address | Unknown (>150/min from VM) | 15+ min |

**Proven approach**: Sequential (1 worker, no token bucket), reactive exponential backoff. Achieves ~25-150 req/min depending on endpoint weight. Zero sustained 429s. Multi-worker is slower (see `readme_api_limit.md`).

---

## Key Reference

- **DB path**: `data/raw/moltbook.db` (5.7 GB with snapshots)
- **DB write behaviour**: UPSERT throughout — re-running any stage is safe
- **Schema**: `src/database.py:_create_tables()`; human-readable: `data/README.md`
- **Rate limit docs**: `readme_api_limit.md`
- **Comment hard cap**: 500/post, no pagination (API limitation)
- **Upstream**: `daveholtz/moltbook_scraper` — sequential, no workers, no token bucket
- **Platform scale** (2026-03-11): ~2.86M agents, ~2.01M posts, ~13.21M comments, ~19.2K submolts
