# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-29, session 30.

> Tag claims `[verified]` (checked this session) vs `[planned]` (agreed, not implemented). Re-tag rather than copy-forward. Reasoning lives in session logs — this file is pointers + state only.

---

## Current state [verified 2026-05-29]

- **Weekly cron: healthy & structurally immune** to the May-5 corruption class (uses `comments --only-missing --skip-empty`, no `--detect-deletions`, so `_detect_deleted_comments` is never reached). Last two weeklies (May 18, May 25) both `SUCCESS, 0 errors`. Steady-state runtime ~20 h. Next fires **Mon 2026-06-01 02:00 UTC**.
- **Monthly cron: DISABLED on VM** (crontab line commented since 2026-05-08; backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`). Do NOT re-enable until: Phase-1 safeguard lands + the corruption circuit-breaker is in + T5 validates + the May-5 damage is refetched. (Sharding deprioritized — user wants circuit-breaker first.)
- **Phase-0 rate-limit fix DEPLOYED to VM** (`src/client.py` honors `Retry-After`, capped 120 s; smoke-tested in VM venv 2026-05-29). Applies to the Jun-1 weekly.
- **API regime changed** (2026-05-29): tiered limiter (`short` 30/1s, `medium` 600/60s, `long` 10000/300s) + binding unsuffixed `200/~60s`, behind AWS CloudFront. Sequential ~25/min has ~8× headroom. Full detail: `readme_api_limit.md` top block + session-30 log §2/§5.
- **DB**: ~8.6 GB working copy on the 99 GB volume; backups = `moltbook-weekly-2026-05-25` (8.3 GB) + `moltbook-monthly-post-2026-05-05` (7.4 GB). Counts: posts 3,084,737 / comments 5,991,314.
- **May-5 corruption** characterized + classifier (`tombstoned == in_db AND in_db > 0`): 324 false-positive posts (1,533 comments) + 197 genuine. Posts-stage has the same swallow-bug class. Detail: session-29 log.

## Spot-check on return

```bash
date -u
ssh vm 'crontab -l | grep -E "weekly|monthly|disk"'   # weekly+disk active; monthly line commented
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'curl -is "https://www.moltbook.com/api/v1/posts?limit=1" | grep -i ratelimit'  # tiered headers; 429-no-headers = infra trip
ssh vm "sqlite3 /root/moltbook_scraper/data/raw/moltbook.db 'SELECT COUNT(*) FROM posts; SELECT COUNT(*) FROM comments;'"
```
Expected after the Jun-1 weekly: counts grown from above; backups = latest weekly + the May-5 monthly-post; client.py on VM contains `_backoff_delay`.

## Next actions

**Block A — monthly reinforce + weekly rate-limit robustness** (full 4-phase plan + decisions in session-30 chat / log §4-5):

1. ✅ **T6** — xfail regression guard for `fetch_comments_only` (done; flips to passing when step 3 lands).
2. ✅ **Phase 0** — regime characterized + header-aware backoff, deployed to VM. *Open sub-task (low priority):* date *when* the regime changed — diff `upstream`(`daveholtz/moltbook_scraper`) + observatory `src/middleware/rateLimit.js` history / web-search (Meta acquisition?).
3. **Phase 1 — swallow-bug safeguard [NEXT, ~10 lines]:** re-raise `RateLimitError` in `client.py:fetch_comments_only` / `fetch_posts_streaming` / `fetch_submolts_streaming` (return `[]`/break only for genuine 404/empty); defensive guards in `scraper.py:_detect_deleted_comments` (don't tombstone when api_ids empty AND existing non-empty) and `scrape_posts` (don't tombstone the tail if the walk ended on a RateLimitError). Then **T5** live validation on a tripped endpoint (0 tombstones, N logged errors).
4. **Corruption circuit-breaker** (monthly, priority): before committing any tombstoning in a monthly run, abort if any `RateLimitError` occurred in that stage OR the would-delete set exceeds a sanity ceiling → makes monthly fail-safe.
5. **Refetch sweep** of the 521 comment-affected posts + 6,428 post IDs (wide refetch; nothing lost — per user).
6. **Re-enable monthly** (uncomment `55 1 * * 2`) after 3+4+5.
7. **Weekly robustness:** thread a rate-limit counter into stage logs + degraded-run email alert; fix reporting bugs (`weekly_scrape.sh`/`status.sh`: `DB size:0` from `du` on symlink → `du -hL`; disk-free reads `/` not `$DATA_VOLUME`).
8. **Sharding (A-H/I-P/Q-Z)** — deferred until after circuit-breaker; threshold informed by the real rate regime.

**Block C — change-based-data value** (session-30 log §4):

9. **Young-post pulse scraper — GREEN LIGHT, design pending.** Measured blind spot: posts first observed at median age ~5-6 d; 89.3% of final upvotes already present at first obs. Build a lightweight daily/2×-day pulse over young posts (≤7-14 d), change-driven into `post_metrics`, keep 4-week cutoff → bounded ~single-digit MB/month. Decide cadence + cutoff for the young subset.
10. **Event-writer follow-ups** (low): exclude run-4 `is_spam` from analysis (artifact — methodology 2026-05-29); harden boolean anchor-setting to only anchor from a complete observation; 1,771 NULL-anchor agents can't emit `is_claimed`.

**Older low-cost probes (independent of block A; from session 28):** 500-vs-1000 comment cap; 2-min polling-window adequacy; posts content-dedup sanity; `/agents/profile` follower-list. Enrich-stage 311-errors investigation (persistent vs transient). Context: session-28 log.

## Known issues / open threads

- **Slow-batch pauses in comments stage** [session 27]: `pwrite64`/`fdatasync`-dominated WAL-checkpoint stall at current DB size; not independently actionable.
- **Apr 1 monthly silent-death** [blocked since 2026-05-08]: OOM-during-`sqlite3 .backup` hypothesis; re-tested when next monthly fires.
- **Pytest hang** [verified 2026-04-21]: bare `pytest` hangs on `test_fetch_all_posts_paginates_until_no_more` + orphans RAM. Always scope to specific test files. (See also the `responses`-repeating-mock loop pitfall — learnings.md "Process & Workflow".)

## Resuming after absence

1. Run §Spot-check. Verify the Jun-1 weekly completed (VM logs).
2. Block A is paused before Phase 1. Next concrete move: implement the 3-piece safeguard (action #3), then T5.
3. Don't re-derive: the false-deletion classifier + posts-stage bug (session-29 log); the rate-limit characterization + backoff (session-30 log §5); the change-based-data diagnosis (session-30 log §4).

## Work laptop

[verified 2026-04-21] SSH configured. Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session-16 log if setting up.
