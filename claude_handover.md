# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-11, session 27.

> Provenance: claims tagged `[verified]` were checked against current state in this session; `[planned]` is agreed direction without implementation. Re-tag rather than copy-forward.

---

## Current state

[verified 2026-05-11]

- **May 11 weekly in progress and healthy.** Started 02:00 UTC, at 85,900/110,953 posts (~77 %) in the `comments --only-missing --skip-empty` stage at 19:24 UTC. Throughput ~50 posts / 15-20 s (≈ 90 posts/min). Expected to finish later tonight or early Tue 12.
- **API rate-limit cleared.** Direct VM curl returns HTTP 200 in 509 ms with `x-ratelimit-remaining: 199/200` headers present — per-token budget full, per-IP infra limit not tripped. The multi-day cooldown from the session-26 incident is over.
- **Session-26 outputs now on origin/main** as commit `5ead3d9` (handover, learnings, methodology, readme_api_limit, session-26 log). Working tree clean.
- **Monthly cron remains DISABLED on VM.** Crontab line still commented out from 2026-05-08; backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`. Weekly + disk monitor untouched and active. Do NOT re-enable until the `fetch_comments_only` swallow-bug + `_detect_deleted_comments` empty-vs-rate-limited distinction are fixed AND submolt-letter sharding is implemented.
- **Corrupted comment-deletions from May 5 monthly remain in DB.** 4,126 comment rows with `deleted_detected_at >= '2026-05-05'` (2,620 firm + 1,506 `deletion_uncertain=1`) and 6,428 posts marked deleted on 2026-05-05 still untouched. Backups available: `moltbook-weekly-2026-05-04.db` (6.2 GB, clean — predates monthly) and `moltbook-monthly-post-2026-05-05.db` (7.4 GB, captures corrupted state).
- **DB**: 7.9 GB working copy on 99 GB volume. Three backups on disk total ~21 GB (May 4 weekly + May 5 monthly-post + May 11 weekly — May 4 will be pruned at end of current weekly per retention policy).

## Spot-check on return

```bash
date -u
ssh vm 'crontab -l | grep -E "weekly|monthly|disk"'
ssh vm 'tail -10 /root/moltbook_scraper/logs/weekly-2026-05-11.log'   # weekly finished cleanly?
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'curl -is "https://www.moltbook.com/api/v1/posts?limit=1" | head -8'
```

Expected:
- Crontab: weekly + disk-monitor active; the `55 1 * * 2 ... monthly_rescrape.sh` line is commented out.
- Weekly log: should have a "Weekly scrape complete" / non-zero exit footer if it finished. If still progressing, the timestamp on the last line should be recent.
- Backups dir: May 11 weekly (7.4 GB+, kept) + May 5 monthly-post (7.4 GB, kept). May 4 weekly should have been pruned at the end of the May 11 run.
- Curl: HTTP 200 with `x-ratelimit-*` headers present. If 429 with no headers (and CloudFront `x-cache: Error from cloudfront`), the infra limit has been re-tripped — diagnose against session 26 recognition signature.

## Next actions (in priority order)

1. **Verify May 11 weekly finished cleanly.** Read tail of `weekly-2026-05-11.log` for the completion footer. Check whether the comments stage ended on its own (not killed by sentinel timeout / OOM). If it errored, the bug surface to look at is the same as session 26 — but no `--detect-deletions` flag was on, so worst case is missing comments, not false tombstones.

2. **Spot-check the false-deletion hypothesis end-to-end.** Pick the saved sample: post `2312864c-d211-43e2-88b6-5e7cb1a2732b` had three comments tombstoned on 2026-05-08 (`ffe1a7cb-d0a7-4797-86f7-553a4a97004c`, `ff748e77-1376-4ef4-a642-4002d1cd4a6d`, `ff021d6d-c792-4f4f-b8e6-402a75bfc6dc`). One curl to `/api/v1/posts/{id}/comments?limit=500` will show whether they come back. If they do → false-positive hypothesis confirmed; proceed to step 3. If they don't → those particular comments may have been genuinely deleted (the bug still applies broadly, just not to this sample).

3. **Estimate false-positive rate.** Take a stratified sample (~50–100) of `comments` rows where `deleted_detected_at >= '2026-05-05'`; re-fetch their parent posts; record fraction that come back. This guides remediation strategy.

4. **Choose remediation:**
   - **Targeted re-fetch sweep (recommended)**: SQL → list of distinct `post_id`s with comments tombstoned in this run; iterate, fetch comments via API, for any returned comment ID clear `is_deleted = 0, deleted_detected_at = NULL, deletion_uncertain = 0`. Cheaper than rollback.
   - **Full rollback (fallback)**: restore from `moltbook-weekly-2026-05-04.db` (predates monthly entirely). Loses any legitimate work done by posts-stage / enrich-stage in this run AND the entire May 11 weekly. Acceptable if false-positive rate is very high.

5. **Fix the bugs before re-enabling monthly:**
   - `client.py:fetch_comments_only` — distinguish `RateLimitError` from "API returned `[]`". Easiest: re-raise `RateLimitError`, catch only `requests.HTTPError` etc. and return `[]`. Test: existing `tests/test_client.py` should cover this; add a regression test that a 429-storming server triggers a propagated exception, not `[]`.
   - `scraper.py:_detect_deleted_comments` — accept the result of `fetch_comments_only` only when the fetch succeeded; on rate-limit propagate the failure up to scraper-level `error_count` and skip the deletion comparison entirely.
   - Both fixes are < 20 lines combined. The expensive part is testing them well.

6. **Implement submolt-letter sharding.** The reason May 5 happened is 3 days of continuous traffic. Sharding into 3 letter-groups (A-H / I-P / Q-Z) gives each shard ~1 day of runtime with idle gaps in between — well below the infra-limit trigger threshold. Methodology log entry from 2026-04-20. Do this *before* re-enabling monthly cron, even if the bug fixes land first.

7. **Re-enable monthly cron.** Uncomment the `55 1 * * 2 ...` line; verify with `crontab -l`.

## Known issues / open threads

### Slow-batch pauses in comments stage

[observed 2026-05-11, session 27] During the May 11 weekly, the progress log showed a ~20-25 min gap with no new lines while the python process was alive and in `hrtimer_nanosleep`. Investigation via `strace -c` showed the syscall mix was dominated by `pwrite64`/`fdatasync`/`pread64` (heavy SQLite I/O), NOT `clock_nanosleep`/`poll` (which is the session-26 rate-limit signature). The pause resolved without intervention and throughput returned to normal. Likely a single slow batch — large-comment post, WAL checkpoint, or fsync stall at the current 7.9 GB DB size. Not actionable on its own; noted here so the next observer doesn't mistake it for session-26 recurrence.

### Apr 1 monthly silent-death — diagnosis blocked

[blocked since 2026-05-08] The May 5 monthly DID get past the "Backing up database" line that ate the Apr 1 monthly silently, so the original hypothesis (OOM during sqlite3 .backup on the at-the-time 22 GB DB) is consistent with Phase 4 having resolved it. But because we killed the May 5 run, this isn't a fully clean confirmation. Will be re-tested when the next monthly fires (after fixes land + cron re-enabled).

### Pytest hang

[verified 2026-04-21] `pytest` without path filter hangs on `test_fetch_all_posts_paginates_until_no_more` and orphans ~50 GB RAM. Always scope to specific test files.

### Sharding by submolt first-letter

[planned, not implemented] Methodology log entry from 2026-04-20; promoted to **blocking re-enable of monthly cron** by the 2026-05-08 incident.

### status.sh cosmetic bugs

Two pre-existing display bugs surface every session-startup:
- `DB size: 0` — `du` on a symlinked path. Real size from `ls -lh`.
- `N errors` — `grep -c "error"` matches `"0 errors)"` in progress lines. Real error count from `grep -cE "Exception|Traceback|ENOSPC|OperationalError"`.

Both are 2–5 line fixes to `scripts/status.sh`. Low priority but worth doing — cost cognitive overhead every session.

---

## Resuming after absence

1. Run §Spot-check above.
2. If the May 11 weekly finished cleanly, proceed to §Next-actions step 2 (spot-check false-deletion hypothesis on post `2312864c-...`). API budget is clear.
3. If the weekly is still running, hold off on API-touching work (steps 2-4) to avoid competing for budget. Bug fixes (step 5) and sharding design (step 6) are pure code work and safe to do in parallel.
4. Read `CLAUDE/session_logs/2026_05_08_session_log.md` for the full diagnostic trace of the May 5 monthly incident if you need it. `CLAUDE/session_logs/2026_05_11_session_log.md` covers today's admin work and the transient-pause investigation.

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
