# Claude Handover — Moltbook Scraper

**Last verified against code + VM**: 2026-05-12, session 28.

> Provenance: claims tagged `[verified]` were checked against current state in this session; `[planned]` is agreed direction without implementation. Re-tag rather than copy-forward.

---

## Current state

[verified 2026-05-12]

- **May 11 weekly finished cleanly** at 2026-05-12 18:36:27 UTC. Total runtime **40 h 36 min** — substantially longer than the 8-10 h documented in CLAUDE.md (see session 28 log for stage breakdown + runtime-budget reassessment TODO).
- **API rate-limit cleared and stable** throughout the weekly's 40 h continuous run. Confirms the per-IP infra limit only trips on multi-day sustained traffic (3+ days), not on a single 40-h weekly.
- **Post-weekly counts**: posts 2,939,474 / comments 5,629,305 / agents 179,364 / submolts 28,302 / moderators 27,467. Panels: post_metrics 521,725 (+68,593) / agent_metrics 186,022 (+2,623) / submolt_metrics 28,548 (+4,274). Events: post_events 292,488 (+1) / agent_events **0** (unchanged — see TODOs) / moderator_events 27,467 (+4,128). All snapshot-writer counts within "Normal" ranges per CLAUDE.md monitoring section.
- **Monthly cron remains DISABLED on VM.** Crontab line still commented out from 2026-05-08; backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`. Weekly + disk monitor untouched and active. Do NOT re-enable until the `fetch_comments_only` swallow-bug + `_detect_deleted_comments` empty-vs-rate-limited distinction are fixed AND submolt-letter sharding is implemented.
- **Corrupted comment-deletions from May 5 monthly remain in DB.** 4,126 comment rows with `deleted_detected_at >= '2026-05-05'` (2,620 firm + 1,506 `deletion_uncertain=1`) and 6,428 posts marked deleted on 2026-05-05 still untouched. Recovery backup `moltbook-weekly-2026-05-04.db` was **pruned at end of the May 11 weekly** per retention policy. Remaining backups: `moltbook-weekly-2026-05-11.db` (7.4 GB, captures pre-monthly-fix state) and `moltbook-monthly-post-2026-05-05.db` (7.4 GB, captures the corrupted state). The clean-pre-corruption recovery point is no longer on disk; targeted re-fetch sweep is now the only option short of replaying from earliest cold backup.
- **DB**: 7.9 GB working copy on 99 GB volume. 72 GB free / 24 % used. Two backups on disk total 14.8 GB.

## Spot-check on return

```bash
date -u
ssh vm 'crontab -l | grep -E "weekly|monthly|disk"'
ssh vm 'ls -lh /mnt/HC_Volume_104999576/moltbook_data/moltbook.db /mnt/HC_Volume_104999576/moltbook_data/backups/'
ssh vm 'curl -is "https://www.moltbook.com/api/v1/posts?limit=1" | head -8'
ssh vm "sqlite3 /root/moltbook_scraper/data/raw/moltbook.db 'SELECT COUNT(*) FROM posts; SELECT COUNT(*) FROM comments;'"
```

Expected:
- Crontab: weekly + disk-monitor active; the `55 1 * * 2 ... monthly_rescrape.sh` line is commented out.
- Backups dir: May 11 weekly (7.4 GB) + May 5 monthly-post (7.4 GB), nothing else.
- Curl: HTTP 200 with `x-ratelimit-*` headers present. If 429 with no headers (and CloudFront `x-cache: Error from cloudfront`), the infra limit has been re-tripped — diagnose against session 26 recognition signature.
- Counts: posts ≥ 2,939,474 / comments ≥ 5,629,305 (may have grown if any incremental scrape ran).

## Next actions (in priority order)

1. **Spot-check the false-deletion hypothesis end-to-end.** Pick the saved sample: post `2312864c-d211-43e2-88b6-5e7cb1a2732b` had three comments tombstoned on 2026-05-08 (`ffe1a7cb-d0a7-4797-86f7-553a4a97004c`, `ff748e77-1376-4ef4-a642-4002d1cd4a6d`, `ff021d6d-c792-4f4f-b8e6-402a75bfc6dc`). One curl to `/api/v1/posts/{id}/comments?limit=500` will show whether they come back. If they do → false-positive hypothesis confirmed; proceed to step 2. If they don't → those particular comments may have been genuinely deleted (the bug still applies broadly, just not to this sample).

2. **Estimate false-positive rate.** Take a stratified sample (~50–100) of `comments` rows where `deleted_detected_at >= '2026-05-05'`; re-fetch their parent posts; record fraction that come back. This guides remediation strategy.

3. **Choose remediation:**
   - **Targeted re-fetch sweep (recommended)**: SQL → list of distinct `post_id`s with comments tombstoned in this run; iterate, fetch comments via API, for any returned comment ID clear `is_deleted = 0, deleted_detected_at = NULL, deletion_uncertain = 0`. Cheaper than rollback.
   - **Full rollback** is no longer cheaply available: the May 4 weekly backup (clean, pre-monthly) was pruned at the end of the May 11 weekly. Earliest clean restore now requires the offline cold-storage dump or accepting the May 11 weekly as the rollback point (which still contains the corrupted May 5 deletions).

4. **Fix the bugs before re-enabling monthly:**
   - `client.py:fetch_comments_only` — distinguish `RateLimitError` from "API returned `[]`". Easiest: re-raise `RateLimitError`, catch only `requests.HTTPError` etc. and return `[]`. Test: existing `tests/test_client.py` should cover this; add a regression test that a 429-storming server triggers a propagated exception, not `[]`.
   - `scraper.py:_detect_deleted_comments` — accept the result of `fetch_comments_only` only when the fetch succeeded; on rate-limit propagate the failure up to scraper-level `error_count` and skip the deletion comparison entirely.
   - Both fixes are < 20 lines combined. The expensive part is testing them well.

5. **Implement submolt-letter sharding.** The reason May 5 happened is 3 days of continuous traffic. Sharding into 3 letter-groups (A-H / I-P / Q-Z) gives each shard ~1 day of runtime with idle gaps in between — well below the infra-limit trigger threshold. Methodology log entry from 2026-04-20. Do this *before* re-enabling monthly cron, even if the bug fixes land first.

6. **Re-enable monthly cron.** Uncomment the `55 1 * * 2 ...` line; verify with `crontab -l`.

## Observatory comparison — follow-up TODOs

[from session 28, 2026-05-12] Context, reasoning, and concrete numbers in `CLAUDE/session_logs/2026_05_12_session_log.md`. The investigation was driven by a meeting partner using `kelkalot/moltbook-observatory` who reportedly has less data than we do; we want to confirm whether the difference reflects real coverage gaps on their side or possible inflation on ours.

1. **500 vs 1000 comment cap probe.** Observatory's poller comments cap stored comments at 900 per post citing "~1000 API ceiling"; our `readme_api_limit.md` says hard cap is 500, no pagination. Both can't be right. Action: (a) backtrace where the 500 figure came from in our docs (likely sessions 6-8, March 2026); (b) run a direct API probe against a known-high-comment post to count actual returned items at limit=500 and limit=1000. If 1000 is real:
   - Update `client.py` to request the full 1000 (and update `readme_api_limit.md`)
   - Reassess monthly backfill cost — additional rows per popular post × number of popular posts
   - Reassess weekly load — incremental comments stage will now pull more per post

2. **Sampling-window adequacy on the post creation side.** Observatory polls top-50 of `sort=new` every 2 min. For any 2-minute window where Moltbook produced > 50 new posts (i.e., > 25 posts/min), posts get buried before their next poll and are silently missed unless they reach `sort=hot`. Action: SQL over `posts.created_at` to count 2-min buckets with ≥ 50 posts; compute the resulting upper-bound on posts Observatory would have missed. Gives a quantified answer to "what fraction of platform activity is invisible to Observatory."

3. **Posts content-deduplication sanity check.** Confirm our higher row count is not inflated by accidental duplication. `posts.id` is a PK so true row dupes are impossible at the DB level, but `(agent_id, title, content, created_at)` collision under multiple ids would suggest Moltbook re-issues IDs. Low prior; cheap query.

4. **`/agents/profile` follower-list probe.** Originally from session 27. Observatory's `follows` table is declared in their `migrations.py` but their `processors.py` does not write to it (verified in session 28), so they have not actually demonstrated that the endpoint exposes a list. Action: one curl `-H "Authorization: Bearer $MOLTBOOK_API_KEY" "https://www.moltbook.com/api/v1/agents/profile?name=<known_agent>"` — inspect response body for `followers` / `following` arrays. If counts only, doc stands. If an array (even paginated), the social graph is a first-class capability gap; add a `follow_edges` table + writer and update `readme_api_limit.md`. Cost: 1 API request. Do not loop trying to find an exposed endpoint — if the standard profile endpoint doesn't return the list, accept the doc as correct.

## Operational TODOs from May 11 weekly run

[from session 28, 2026-05-12] Surfaced during the post-run debrief. See session 28 log for full numbers and stage breakdown.

1. **Weekly runtime 40 h 36 min vs documented 8-10 h.** Either CLAUDE.md's runtime estimate is stale post-Phase-4 (more likely — corpus has grown substantially) or the enrich stage's 7 h is anomalous. Worth one calibration pass: how long should each stage take at current corpus size? Update CLAUDE.md "Quick Commands" comments to reflect reality.

2. **`agent_events = 0` is structurally suspicious.** After this weekly, 9,436 new agent anchors were set and 2,623 metric inserts written. Yet `agent_events` remains at 0. CLAUDE.md says initial state is captured in anchors only — events emit only for subsequent transitions, which is correct design. But after months of operation across 179,364 agents, zero verification or claimed-status flips is implausible. Action: SQL probe — `SELECT COUNT(*) FROM agents WHERE is_claimed_first != is_claimed;` or `SELECT COUNT(*) FROM agents WHERE verification_status_first != verification_status;`. If non-zero, the event writer for agent boolean/enum fields has a bug; trace through `scraper.py`'s snapshot writer.

3. **Enrich stage 311 errors.** `Enriched 8847 agents (311 errors)` — 3.4 % failure rate. Probably individual agent profile fetches that 404'd or timed out. Worth a one-off check on whether these are persistent (same agents fail every weekly) or transient. Persistent failures would suggest stale agent records in our DB.

4. **`status.sh` / `weekly_scrape.sh` reporting bugs** (cosmetic but degrading our trust in log signals):
   - `Disk free: 29G` is wrong — real free space on the data volume is 72 GB. The script is querying the wrong mount or running `df` without a path argument and getting the root filesystem.
   - `DB size: 0` is the existing known `du`-on-symlink bug.
   - Together they make the weekly footer's resource summary unreliable. Fix both in one pass — likely 5-10 lines.

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
2. The May 11 weekly is finished and API is clear — proceed to §Next-actions step 1 (false-deletion spot-check) whenever ready. No active scrape is consuming API budget.
3. Several investigative TODOs (§Observatory comparison + §Operational TODOs) are low-cost probes that don't depend on each other and can be done in any order. The 500-vs-1000 comment cap test is the most consequential because it could trigger a config change to the weekly + monthly scripts.
4. Context for the long-tail issues:
   - `CLAUDE/session_logs/2026_05_08_session_log.md` — full diagnostic of the May 5 monthly incident.
   - `CLAUDE/session_logs/2026_05_11_session_log.md` — session-26 commit, transient-pause investigation, follow-graph probe rationale.
   - `CLAUDE/session_logs/2026_05_12_session_log.md` — Observatory analysis, weekly completion summary, all of the Observatory + operational TODOs above.

## Work laptop

[verified 2026-04-21] SSH configured (sessions 16-17). Still missing locally: `.env`, `.venv/`, `data/raw/moltbook.db`. See session 16 log if ever setting up.
