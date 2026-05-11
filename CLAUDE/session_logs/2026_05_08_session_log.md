# Session 26 — 2026-05-08

Machine-switch startup discovered the May 5 monthly was silently corrupting comment-deletion data. Diagnosed root cause (infra-layer per-IP rate limit + a 2-month-old known swallow-bug in `fetch_comments_only` + over-eager deletion writer), killed the run cleanly, quantified damage, mapped the rate-limit window, disabled monthly cron until fix lands.

## Context at session start

- May 4 weekly: SUCCESS in 19.5 h (first weekly under post-Phase-4 steady state — clean).
- May 5 monthly was running, ~3 days in, stuck at "comments-full --detect-deletions" stage.
- Local repo clean, synced with origin (handover's "5 commits ahead" claim was stale — already pushed as `9a7a23c` between sessions 25 and 26).
- Handover predicted "schedule a follow-up agent for ~2026-05-12 to verify monthly completion." That follow-up surfaced today instead.

## Diagnosis (the evidence chain)

Started from "throughput collapsed at 00:59 UTC May 8" hypothesis (post counter went from 50/15 s to 50/52 min). Then layered in:

1. **VM is healthy.** Load 0, mem 1 GB / 3.7 GB, 0 % iowait, sda quiet, sdb (DB volume) idle, no dmesg errors.
2. **`/proc/PID/stack`** = `hrtimer_nanosleep`, `wchan` = `hrtimer_nanosleep`. Process is sleeping, not blocked on network read.
3. **TCP socket alive**: `lastsnd` ~24 s, established to `2600:9000:*` (CloudFront/CloudFront-fronted Next.js origin). Recent activity, not abandoned.
4. **30 s strace summary**: 1× `clock_nanosleep`, 3× `poll`, ~15 syscalls total. 60 s strace: 5× `clock_nanosleep`, 18× `poll`, ~91 syscalls. Process is *deeply* idle — making roughly one HTTP request per minute.
5. **Direct curl from VM** to `/api/v1/posts/{id}/comments?limit=500` → **HTTP 429 in 41 ms**, body `{"error":"rate_limited","message":"Too many requests. Please slow down."}`. **No `X-RateLimit-*` headers, no `Retry-After`.** Even after waiting 30 s and 90 s, fresh requests still 429.
6. **Curl with no auth / bogus auth / no User-Agent** → all 429 immediately. Limit is **per-IP, not per-token**.
7. **`https://www.moltbook.com/`** (root site, not `/api/v1/`) → 200. Limit scoped to API paths.
8. Reading `client.py:_request` and `fetch_comments_only` revealed two compounding bugs (already documented in `readme_api_limit.md` line 85, never fixed):
   - `fetch_comments_only` wraps the call in `try / except Exception: return []` — every `RateLimitError` is silently swallowed.
   - `_detect_deleted_comments` then sees an empty API response, computes `existing_DB_ids \ {} = all existing ids`, and marks every one as `is_deleted = 1` via `mark_comments_deleted`.

So the script was structurally turning every 429 into "this post's comments are all deleted." Throughput dropped because each post burned the full retry budget (`_request` retries 1 s + 2 s + 4 s = 7 s of `time.sleep` + 4 round trips), all 429, before finally raising — and the server's per-minute limit then forced a longer wait before the next request could succeed (or also 429-ed). Average ~62 s/post.

The "0 errors" line in the progress log is a structural blind spot — exceptions never propagate up to scraper-level `error_count`.

## Kill + cleanup

1. SIGTERM python child (PID 1059544, the comments stage). Process exited; bash parent caught non-zero, logged `FAILED: comments-full after 240626 s`, and per `run_stage` semantics moved on to the next stage (`enrich`).
2. SIGTERM enrich python child (PID 1106964) → `FAILED: enrich after 35 s`.
3. SIGTERM bash parent. `trap` did NOT propagate to child immediately because bash was waiting on `run_stage`'s subprocess; instead the script continued to `snapshots`.
4. Snapshots stage runs entirely on the local DB (no API calls), so I let it complete naturally. 219 s. Final monthly status: `PARTIAL FAILURE (2/4 stages failed): Monthly re-scrape completed in 78h 51m`. Trap fired on EXIT, removed `.monthly_running` sentinel.
5. Post-scrape backup `moltbook-monthly-post-2026-05-05.db` (7.4 GB) was created at the end **— it captures the corrupted state**, which is useful for any rollback decision but should NOT be treated as a clean recovery point.

Final state: no orphan processes, no `*-wal`/`*-shm` files, sentinel gone, two backups present (May 4 weekly 6.2 GB + May 5 monthly-post 7.4 GB).

## Damage quantification

| Table | Marked deleted in this run | Notes |
|---|---|---|
| `comments` | **4,126** | 2,620 firm + 1,506 `deletion_uncertain=1` (post had > 500 comments, already-flagged) |
| `posts` | **6,428** (all on 2026-05-05) | First-ever post-stage `--detect-deletions` since March 2026; 0.22 % of corpus → likely largely real but unverified |

Comment-deletion timeline shows steady drip from 13:00 UTC May 5 onward (37/h to 217/h, mean ~65/h), with bursts up to 217/h on May 7 23:00 and 187/h on May 8 07:00. **The rate-limit-induced false positives are intermixed with real deletions throughout the run**, not concentrated at any one stall. Cannot disentangle without re-querying the API.

Sample for spot-checking when the limit clears: post `2312864c-d211-43e2-88b6-5e7cb1a2732b` had 3 comments tombstoned today (IDs `ffe1a7cb...`, `ff748e77...`, `ff021d6d...`). One API call to `/posts/{id}/comments?limit=500` will say whether they come back.

## Rate-limit investigation

Three angles, per user instruction:

1. **Server-side** — exhausted what the API tells us. No `X-RateLimit-*` headers, no `Retry-After`, only the JSON error body. CloudFront `x-cache: Error from cloudfront` confirms it's the origin's 429, not edge throttling. Per-IP, not per-token, not per-UA.
2. **Upstream `daveholtz/moltbook_scraper`** — dormant since 2026-02-28 (`787f2d9 Fix API pagination and add submolt enrichment`). No commits about rate limits. Useless for this question.
3. **`kelkalot/moltbook-observatory`** — 50+ commits inspected. Closest matches: `Fix comment collection bottleneck and API limit handling` (2026-02-02; their fix was a 900-comment `API_COMMENT_LIMIT` cap and switch to a 50-posts-per-2-min polling loop ≈ 25 req/min — they architecturally sit well below the limit) and `Remove User-Agent header from client request` (2026-04-06, suggests UA-discrimination existed at some point). No commits about a recent server-side rate-limit change.

**Conclusion: this is not a Moltbook/META update.** The infrastructure-layer per-IP limit was already documented in our own `readme_api_limit.md` (sessions 6–8, March 2026): "no `X-RateLimit-*` headers", "persists for 15+ minutes after abuse stops", "triggered by sustained high request rates", "multiple API tokens from the same IP share this limit". Open question #2 in that doc was already: "Does the infrastructure limit have a separate cooldown period? Evidence suggests a longer window (15+ minutes observed)."

What this monthly added: **3 days of continuous traffic** is the longest sustained load we've ever put on the API. The infra limit's cooldown evidently scales with abuse magnitude — at 32 min after our SIGTERM the API was still 429 to fresh probes, well past the 15 min documented previously.

## Monthly cron disabled

Crontab on VM edited (backup at `/tmp/cron.bak.before-monthly-disable.20260508T085734Z`). The line `55 1 * * 2 ... monthly_rescrape.sh` is now commented out with a pointer to this session log. Weekly (`0 2 * * 1`) and disk monitor (`0 8 * * *`) untouched and active.

The next "first Tuesday" the disabled monthly *would* have fired on is 2026-06-02. So the disable is belt-and-suspenders for the May 12, 19, 26 Tuesdays (where the day-of-month guard would have skipped anyway), and substantive coverage for June.

## Files touched

- `CLAUDE/session_logs/2026_05_08_session_log.md` — this file
- `claude_handover.md` — full rewrite for post-incident state and Monday-resume launchpad
- `claude_learnings.md` — new entry: "rate-limit-induced false comment-deletion incident (session 26)"; signature traits to recognize recurrence
- `claude_methodology_log.md` — appended: monthly-cron disabled status; deletion writer must distinguish empty-vs-rate-limited
- `readme_api_limit.md` — open-question #2 updated with today's data point (≥ 32 min cooldown after 3-day sustained run)
- VM crontab — monthly line commented out
- Memory: `project_automation_cadence.md`, `reference_hetzner_vm.md` — updated for monthly-disabled state

## Rollback

- **Crontab**: `ssh vm 'crontab /tmp/cron.bak.before-monthly-disable.20260508T085734Z'` restores the May 8 08:57 UTC state. Or just uncomment the `#55 1 * * 2 ...` line. Backup is on VM tmpfs and may be cleared on reboot — copy out if needed.
- **DB false deletions**: not yet rolled back. The May 4 weekly backup (`moltbook-weekly-2026-05-04.db`, 6.2 GB) predates the monthly entirely and is the cleanest recovery point if a full rollback is preferred over a targeted re-fetch fix. Targeted approach (re-query each affected post; clear `is_deleted=1, deleted_detected_at=...` for any comment ID that comes back) is far cheaper and is the recommended path.

## Open threads forwarded to handover

1. Test that the API rate-limit has cleared (probe at +1 h, +6 h, +24 h, mapping the actual long-window).
2. Spot-check the 3 comments on post `2312864c-...` to confirm the false-positive hypothesis end-to-end.
3. Quantify false-positive rate against a sample of the 4,126 comment-deletions; decide on full re-fetch sweep vs partial.
4. **Fix `fetch_comments_only`** — propagate `RateLimitError` distinctly from "API returned empty list".
5. **Fix `_detect_deleted_comments`** — refuse to mark anything when the fetch was rate-limited; only operate on confirmed-empty responses.
6. Re-evaluate the planned-but-not-implemented submolt-letter sharding for monthly. The 3-day continuous run is what tripped the infra limit; sharding into 3 ≈ 1-day chunks with idle gaps in between would not.
7. Re-enable monthly cron after fixes land.

## Recognition signature — does a future scrape stall match this incident?

Use this checklist if a comments / monthly stage looks rate-limit-shaped. Match all items → same family as today; miss one or more → probably something new (new server-side change, new bug, etc.) and should be diagnosed fresh.

1. Direct `curl` from VM to any `/api/v1/*` endpoint returns **HTTP 429 in < 100 ms** with body `{"error":"rate_limited","message":"Too many requests. Please slow down."}` and **no `X-RateLimit-*` headers, no `Retry-After`**.
2. Same 429 returned with no auth header / bogus auth / blank UA — confirms infra layer (per-IP), not application layer (per-token, which would set `X-RateLimit-*`).
3. `https://www.moltbook.com/` (root site) returns 200 — limit is API-path-scoped.
4. The python scraper process is **sleeping**, not blocked on network: `cat /proc/<PID>/stack` shows `hrtimer_nanosleep`, `wchan` = `hrtimer_nanosleep`, CPU 0 %, iowait 0 %.
5. The keepalive TCP socket to `2600:9000:*` (CloudFront) is **alive but mostly idle**: `ss -tnpoie` shows `lastsnd` < 60 s, low `bytes_sent` growth rate (~100 B/s).
6. Per-hour comment-deletion histogram is **sustained 30–200/h** for many hours: `sqlite3 ... "SELECT substr(deleted_detected_at,1,13) AS h, COUNT(*) FROM comments WHERE deleted_detected_at >= '<run_start_date>' GROUP BY h ORDER BY h"`.
7. Progress log shows **`0 errors`** despite the deletion-counter climb. This is the structural blind spot — `fetch_comments_only` swallows every exception.

If the signature matches: kill order is bash parent (PID from `pgrep -f monthly_rescrape`) first, then SIGTERM each python child as `run_stage` advances them. Don't expect the bash trap to clean up children; it doesn't propagate while bash is `wait`ing on a child.

If the signature does NOT match (e.g. headers ARE present → application limit, fast clear → transient, different error code → new failure mode): treat as a fresh incident. The fix-history in `readme_api_limit.md` and `claude_archive.md` may still be useful background.

## Notable surprises

- **The throughput "stall" at 00:59 UTC May 8 was a red herring** — visible in progress logs because that's when both the `total_comments` counter AND the post-throughput collapsed simultaneously, but rate-limit-induced false deletions had been happening throughout the run. The per-hour deletion histogram was the giveaway.
- **`run_stage` runs every stage even after one fails.** Not necessarily wrong — enrich is independent of comments — but it meant the SIGTERM on comments did not stop the run. Bash trap on TERM does not interrupt `wait` cleanly until the foreground child exits. Future similar interventions: SIGTERM the bash parent first, then SIGTERM each python child individually as they pop up.
- **Per-IP infra limit cooldown ≥ 32 min after a 3-day sustained load.** Previously documented as 15 min. Window evidently scales with magnitude/duration of the abuse.
