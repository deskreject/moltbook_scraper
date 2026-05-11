# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-08, session 26.

> Provenance: claims tagged `[verified]` were checked against current state in this session; `[planned]` is agreed direction without implementation. Re-tag rather than copy-forward.

---

## Current state

[verified 2026-05-08]

- **May 5 monthly killed mid-run with corrupted comment-deletion data.** The infra-layer per-IP rate limit fired ~13:00 UTC May 5 onward (3 days of continuous traffic). `fetch_comments_only`'s swallow-bug turned every 429 into `[]`; `_detect_deleted_comments` then tombstoned existing comments for those posts. Final tally at SIGTERM: **4,126 `comments` rows** with `deleted_detected_at >= '2026-05-05'` (2,620 firm + 1,506 `deletion_uncertain=1`) and **6,428 `posts` rows** marked deleted on 2026-05-05 (post-stage may be largely real — first deletion-detection scan since March, ~0.22 % of corpus). Full diagnosis + evidence chain in session 26 log.
- **Monthly cron DISABLED on VM.** Crontab line commented out 2026-05-08 08:57 UTC; backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`. **Weekly + disk monitor untouched and active.** Weekly is safe because (a) `incremental` doesn't run `--detect-deletions`, so the swallow-bug only loses comments rather than tombstoning them, and (b) ~16 h continuous traffic doesn't accumulate enough sustained load to trip the infra limit.
- **API still rate-limited** as of 2026-05-08 ~08:50 UTC (≥ 32 min after SIGTERM). Cooldown window is open — needs probing.
- **DB state**: live `moltbook.db` 7.4 GB on volume `/dev/sdb` (60 GB free / 99 GB after May 4 weekly's prune). Backups: `moltbook-weekly-2026-05-04.db` (6.2 GB, clean — predates monthly entirely) + `moltbook-monthly-post-2026-05-05.db` (7.4 GB, **captures the corrupted state**). No `*-wal` / `*-shm` files; no orphan processes; sentinel removed.
- **Local repo**: `main`, working tree clean, synced with origin (handover from session 25 was stale on this — already pushed as `9a7a23c`).

## Spot-check on return

```bash
date -u
ssh vm 'crontab -l | grep -E "weekly|monthly|disk"'
ssh vm 'bash ~/moltbook_scraper/scripts/status.sh'
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'curl -is "https://www.moltbook.com/api/v1/posts?limit=1" | head -8'   # is the rate limit cleared?
```

Expected:
- Crontab: weekly + disk-monitor lines active; the `55 1 * * 2 ... monthly_rescrape.sh` line is commented out (`#55 1 * * 2 ...`) with a header comment pointing at the session 26 log.
- DB ~7.4 GB; backups dir has the 2026-05-04 weekly + 2026-05-05 monthly-post.
- Either May 11 weekly already ran (if you're back after Mon 02:00 UTC) or hasn't yet. Either is fine — weekly is unaffected by the bug.
- Curl: ideally HTTP 200 (limit cleared). If still 429 with body `{"error":"rate_limited",...}`, do NOT keep probing — wait longer.

## Next actions (in priority order)

1. **Verify the API rate limit has cleared.** A single `curl -is "https://www.moltbook.com/api/v1/posts?limit=1"` is enough. Body `{"error":"rate_limited",...}` and no `X-RateLimit-*` headers = still in penalty box. If still active after the multi-day gap since May 8, that's important new data — log it in `readme_api_limit.md` open question #2.

2. **Spot-check the false-deletion hypothesis end-to-end.** Pick the saved sample: post `2312864c-d211-43e2-88b6-5e7cb1a2732b` had three comments tombstoned on 2026-05-08 (`ffe1a7cb-d0a7-4797-86f7-553a4a97004c`, `ff748e77-1376-4ef4-a642-4002d1cd4a6d`, `ff021d6d-c792-4f4f-b8e6-402a75bfc6dc`). One curl to `/api/v1/posts/{id}/comments?limit=500` will show whether they come back. If they do → false-positive hypothesis confirmed; proceed to step 3. If they don't → those particular comments may have been genuinely deleted (the bug still applies broadly, just not to this sample).

3. **Estimate false-positive rate.** Take a stratified sample (~50–100) of `comments` rows where `deleted_detected_at >= '2026-05-05'`; re-fetch their parent posts; record fraction that come back. This guides remediation strategy.

4. **Choose remediation:**
   - **Targeted re-fetch sweep (recommended)**: SQL → list of distinct `post_id`s with comments tombstoned in this run; iterate, fetch comments via API, for any returned comment ID clear `is_deleted = 0, deleted_detected_at = NULL, deletion_uncertain = 0`. Cheaper than rollback.
   - **Full rollback (fallback)**: restore from `moltbook-weekly-2026-05-04.db` (predates monthly entirely). Loses any legitimate work done by posts-stage / enrich-stage in this run. Acceptable if false-positive rate is very high.

5. **Fix the bugs before re-enabling monthly:**
   - `client.py:fetch_comments_only` — distinguish `RateLimitError` from "API returned `[]`". Easiest: re-raise `RateLimitError`, catch only `requests.HTTPError` etc. and return `[]`. Test: existing `tests/test_client.py` should cover this; add a regression test that a 429-storming server triggers a propagated exception, not `[]`.
   - `scraper.py:_detect_deleted_comments` — accept the result of `fetch_comments_only` only when the fetch succeeded; on rate-limit propagate the failure up to scraper-level `error_count` and skip the deletion comparison entirely.
   - Both fixes are < 20 lines combined. The expensive part is testing them well.

6. **Re-evaluate planned submolt-letter sharding.** The reason today happened is 3 days of continuous traffic. Sharding into 3 letter-groups (A-H / I-P / Q-Z) gives each shard ~1 day of runtime with idle gaps in between — well below the infra-limit trigger threshold. Do this *before* re-enabling monthly cron, even if the bug fixes land first.

7. **Re-enable monthly cron.** Uncomment the `55 1 * * 2 ...` line; verify with `crontab -l`.

## May 11 weekly — should fire normally

[planned for 2026-05-11]

Mon 02:00 UTC May 11. Weekly is unaffected by today's incident (see "Current state" rationale above). On return, sanity-check it ran: `ssh vm 'tail -20 ~/moltbook_scraper/logs/weekly-2026-05-11.log'`. If you returned before Mon 02:00 UTC, the run is upcoming.

If the weekly errors out with rate-limit symptoms similar to today's, that would be a new finding (would mean the cooldown is far longer than expected). Diagnose via session 26's "Recognition signature" checklist.

## Known issues / open threads

### Apr 1 monthly silent-death — diagnosis blocked by today's incident

[blocked 2026-05-08] The May 5 monthly DID get past the "Backing up database" line that ate the Apr 1 monthly silently, so the original hypothesis (OOM during sqlite3 .backup on the at-the-time 22 GB DB) is consistent with Phase 4 having resolved it. But because we killed the May 5 run, this isn't a fully clean confirmation. Will be re-tested when the next monthly fires (after fixes land + cron re-enabled).

### Pytest hang

[verified 2026-04-21] `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.

### Sharding by submolt first-letter

[planned, not implemented] Methodology log entry from 2026-04-20; promoted to **blocking re-enable of monthly cron** by today's incident.

### status.sh cosmetic bugs

Two pre-existing display bugs surface every session-startup:
- `DB size: 0` — `du` on a symlinked path. Real size from `ls -lh`.
- `N errors` — `grep -c "error"` matches `"0 errors)"` in progress lines. Real error count from `grep -cE "Exception|Traceback|ENOSPC|OperationalError"`.

Both are 2–5 line fixes to `scripts/status.sh`. Low priority but worth doing — cost cognitive overhead every session.

---

## Resuming after absence

1. Run §Spot-check above.
2. Check whether the API rate limit has cleared (single curl, don't probe repeatedly).
3. If cleared → start with §Next-actions step 2 (spot-check false-deletion hypothesis on the saved sample).
4. If still rate-limited → still readable; just don't fetch from the API yet. Read the session 26 log to fully reload context before deciding what to do.
5. Read `CLAUDE/session_logs/2026_05_08_session_log.md` for full diagnostic trace, kill order, damage quantification, and the recognition-signature checklist for "is a future similar-looking failure the same family or something new."

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
