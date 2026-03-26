# Session 15 — 2026-03-26 — VM Health Check, Email Fix, Swap Fix

**What was done:**

1. **VM health check**: Weekly Mar 23 ran as PARTIAL FAILURE — stages 1-5 (incremental, submolts, comments, moderators, enrich) all succeeded; snapshot stage OOM-killed (PID 359955, 3.5 GB RSS on 3.7 GB VM, confirmed via `dmesg`). 2 minor enrich errors (2/7230 agents). No scrape running currently; data current through Mar 23.

2. **Email alert fix**: Diagnosed why no emails ever sent from cron despite manual test working. Root cause: `EMAIL_TO="${MOLTBOOK_ALERT_EMAIL:-}"` was assigned in Configuration block *before* `.env` was sourced in Setup block. Cron has minimal environment, so var was always empty. Fix: moved `EMAIL_TO` assignment to immediately after `source .env` in both `weekly_scrape.sh` and `monthly_rescrape.sh`. Pushed to VM, tested — email delivered to alexander.staub@esade.edu.

3. **Swap file (OOM temporary fix)**: Created 4 GB persistent swap on VM (`/swapfile`, in `/etc/fstab`). Total virtual memory now ~7.7 GB. Disk: 9.3 GB free / 38 GB (75% used). Estimated runway: several weeks to months before DB growth exhausts swap too.

4. **Schema gap verification**: Confirmed all 5 upstream gaps (`claimed_by`, `creator_id`, `post_count`, `is_nsfw`, `is_private`) are real — fields exist in API responses but are silently dropped by current upserts. `_normalize_agent()` already maps `claimedBy` → `claimed_by` but agents table has no column for it. COALESCE missing on submolt upsert (overwrites instead of preserving). None of these are in learnings.md as dead ends. Backfill: one enrich pass (~2-3 days) for agents, one submolt refresh (~10 min) for submolts. No full re-scrape of posts/comments needed.

5. **Documentation updates**: Updated `claude_learnings.md` (OOM + email entries), `claude_handover.md` (DB counts, swap status, batch snapshot refactor as next step #5 with implementation notes).

**What was learned:**
- Cron environment has no inherited vars — any var read before `source .env` is empty
- SQLite snapshot-by-full-copy pattern doesn't scale past ~5M rows on a 4 GB VM
- Swap is a valid temporary fix but batched reads are the proper solution
