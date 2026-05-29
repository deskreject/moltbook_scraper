# Claude Archive — Moltbook Scraper

Completed or superseded work, organized by topic. Dates preserved inline as `YYYY-MM-DD:`. Entries are abbreviated; follow the session-log pointer if the full context still matters.

---

## Project foundation

- **2026-02-05:** Initial setup (session 1). Created `CLAUDE.md`, audited codebase, identified missing infrastructure (no venv, `.env`, or `data/`; Mac-hardcoded script paths).
- **2026-02-13:** Environment bootstrap (session 2). Created `.venv`, installed deps, `data/raw/` / `logs/` / `analysis/` directories, Windows UTF-8 fix in `src/cli.py`, added upstream remote. Platform scale at this point: ~2.4M agents, ~757K posts, ~12.1M comments, ~17.3K submolts.

## API quirks and drift

- **2026-02-28:** Breaking upstream API changes (session 4). Stats fields renamed to `totalX`; submolts switched to page-based; posts switched to cursor-based; comments moved to a separate endpoint. Fixed wholesale in `src/client.py`, aligned with upstream `787f2d9`.
- **2026-03-02:** `sort=new` fix (session 5). Default `sort=hot` was capped at ~3 days of high-engagement content (~70K posts). Switched to `sort=new` for full archive access. Platform launched ~Jan 15 2026.
- **2026-03-05:** API source audit (session 7). Confirmed comment cap is 500 (not ~200), no pagination. Production rate limit is 60/min (source says 100) — see also `readme_api_limit.md`.

## Rate limits and concurrency

See also `readme_api_limit.md` for the deep-dive.

- **2026-02-13:** Sliding-window throttle added then removed (sessions 3→4). Caused cold-start 429 storms.
- **2026-03-03:** Multi-worker optimization attempt (session 6). `--skip-empty`, `fetch_comments_only()`, `ThreadPoolExecutor + _TokenBucket`. DB writes kept in main thread for SQLite safety.
- **2026-03-06:** Multi-worker slowness root cause (session 8). Three compounding bugs: bucket capacity=9 (burst spikes), `acquire()` outside retry loop (6× actual HTTP rate), rate set to 90/min when prod limit is 60. Also triggered infrastructure-level IP ban (Cloudflare, 15+ min cooldown). Conclusion: sequential (1 worker) at ~25 req/min beats concurrent by ~2.5×. Parallelize across machines/IPs, not threads. Comments scrape moved to dedicated Hetzner VM.

## Phase 0: initial scraping completion

- **2026-03-11:** All scraping stages complete (session 9). Comments scrape finished after ~4.7 days on VM: 2,066,042 comments from 433,850 posts. Mop-up recovered 29,918 more. 167 posts unreachable (stale deleted-comment counts, not a bug). Enrich: 7,160 stubs via `--only-missing` in ~48 min. DB copied to local (3.0 GB). Snapshots created (5.7 GB). Coverage: 93.4% posts, 20.6% comments (API 500/post cap), 5.8% agents (only those who posted/commented/moderated), 97% submolts.

## Schema evolution

- **2026-03-13:** Schema migrations + deletion detection (sessions 10-11). Added missing API fields on posts (type, is_locked, is_spam, verification_status, score, hot_score), comments (is_spam, depth, reply_count, score), agents (display_name, posts_count, is_active, last_active, deleted_at). `mark_posts_deleted()` / `mark_comments_deleted()`, 404 → `deleted_at` on enrich, `--detect-deletions` CLI flag.
- **2026-04-08:** Session 13 schema gaps applied (session 18). `claimed_by` on agents; `creator_id`/`post_count`/`is_nsfw`/`is_private` on submolts; COALESCE on submolt upsert to preserve metadata. Identified in session 13 but not applied until session 18 alongside the disk recovery work.

## VM infrastructure

- **2026-03-13 → 16:** Hetzner VM deployment (session 12). 10-day catch-up scrape complete. Hetzner CX23 VM (Nuremberg, €4.35/mo), pushed 9.9 GB DB, installed sqlite3 + msmtp + dos2unix. Cron: weekly Mon 02:00 UTC, monthly 1st 02:00 UTC. SSH alias `vm` → `root@159.69.34.240`.
- **2026-03-20:** Silent cron failure (session 13). Ubuntu 24.04 has no `python` binary (only `python3`). All scraper stages exited for a full week. Fixed: explicit `$PYTHON=$SCRAPER_DIR/.venv/bin/python` in shell scripts.
- **2026-03-26:** Email alerts + 4 GB swap (session 15). Email alerts silently failed since deployment (`EMAIL_TO` assigned before `.env` sourced). Fixed. Added 4 GB persistent swap as temporary OOM fix (later superseded by Phase 3 snapshot redesign — memory pressure came from loading all snapshot rows).

## Disk recovery and backup policy

- **2026-04-08:** VM disk outage + storage migration (session 18). Root disk (38 GB) hit 100% on Mar 30: DB (11 GB) + 2 backups (21 GB) + swap (4 GB). Apr 1 monthly and Apr 6 weekly failed silently. Email alerts also failed (msmtp needs temp space). Resolution: deleted stale backups, resized Hetzner volume to 80 GB, migrated DB + backups to volume with symlinks, reduced backup retention from 2→1, switched `cp` to `sqlite3 .backup`, added standalone daily disk monitor cron. Work laptop SSH key added, root password set. Generalizable lesson retained in `claude_learnings.md`.
- **2026-04-14:** Pre-compression backup format briefly chosen as Parquet zstd (~21 GB → ~3–5 GB via pandas/pyarrow). **Superseded 2026-04-27** — disk math without compression fits 100 GB volume comfortably (~42 GB steady-state, ~56 GB peak post-Phase-4). Plain `.db` backups kept; compression remains a future contingency only. Full rationale in session 24 log.
- **2026-04-27:** Disk-fill incident + retention rewrite (session 24). Apr 27 weekly backup creation pushed 80 GB volume to 100 % at 02:03 UTC; running scrape survived on root-reserved 5 % slack, no errors. User resized Hetzner volume 80 → 100 GB; `resize2fs /dev/sdb` ran online while scrape was active (kernel 6.8, ext4 with `resize_inode` + `64bit`). Backup retention rewritten: pre-monthly backup dropped, only `latest weekly` + `latest monthly-post` retained. Monthly cron moved from `55 1 1 * *` to `55 1 * * 2` with first-Tuesday-of-month guard inside script. Also surfaced: the prior handover described Phase 3a as "parallel writes alongside legacy" when the deployed code is a full replacement (last legacy `*_snapshots` write was Apr 23 12:23 UTC end of Apr 20 weekly). Apr 1 monthly logged its banner + "Backing up database (pre-scrape)..." then died silently — no monthly run has ever completed in project history. Full diagnosis: session 24 log.
- **2026-05-03:** Phase 4 completed (session 25). Block A passed (Phase 3a writer empirically verified: post_metrics 334 K = posts ≤ 28 d, agent_metrics 177 K = all agents, submolt_metrics 21 K, moderator_events 20 K baseline, post/agent/submolt_events 0 — anchor design works; legacy `*_snapshots` `MAX(scrape_run_id)` all = 1 confirms no parallel writes; claimed_by gate 240 / 175,311 = 0.14 % NULL). Then dropped all 5 legacy `*_snapshots` tables; preserved 30,752,503 rows as compressed local cold-storage dump (`data/archive/legacy_snapshots_2026-04-27.sql.gz`, 6.2 GB, SHA256 `720c3994…`). DROP under WAL took 28 min and grew WAL to 17 GB (logged in learnings). VACUUM rewrote DB 29 GB → 6.2 GB in 5 min. PRAGMA integrity_check = ok. Volume free 38 GB → 60 GB; will jump to ~83 GB once Mon May 4 weekly prunes the Apr 27 pre-Phase-4 backup. `snapshot_mutability_evidence` (audit summary, 30 rows) preserved; no compatibility VIEWs created (R code did not depend on `*_snapshots`).

## Phase 2: snapshot mutability audit

- **2026-04-16:** Audit complete (session 20). Per-column change rates across all four `*_snapshots` tables. Results in `snapshot_mutability_evidence` DB table + `tables/snapshot_mutability_audit_2026-04-14.csv`. Headlines: comment_snapshots 0.0000% on all columns; post_snapshots ≤ 0.003%; agent_snapshots content <0.1%, numeric 0.4-2.2%; submolt_snapshots description 8.84% and subscriber_count 9.85%. Composite indexes `idx_{table}_snap_entity_time` added during audit (fixed a 2h hang). Motivated the Phase 3 redesign — see session 21 log.

## Snapshot writer OOM (superseded)

- **2026-03-26:** Snapshot OOM on 4 GB VM (session 15). `create_snapshots()` loaded all live-table rows into memory, hit 3.5 GB RSS, OOM-killed. Temporary fix: 4 GB swap. Superseded by Phase 3 redesign (change-driven writer inserts only deltas; memory becomes non-issue).

## Claimed_by backfill strategy

- **2026-04-14:** Original plan (session 19). Dedicated one-off `scripts/backfill_claimed_by.py` in tmux for ~48 h; weekly untouched.
- **Between 2026-04-14 and 2026-04-20:** Revised plan. `get_unenriched_agent_names()` predicate widened with `OR (is_claimed = 1 AND claimed_by IS NULL)`. Backfill absorbed into weekly cron, intended to spread over multiple weeks.
- **2026-04-20:** Observed outcome (session 22). Widened predicate landed on the VM at some point before Apr 20; the Apr 20 weekly picked up the entire 174,939-agent backlog in one go. Rate-limit bound; expected ~48 h to complete. Once this run finishes, the `OR` branch returns ~0 rows going forward — next weekly reverts to normal enrich size.
- **2026-04-24:** Session-22 prediction disproven (session 23). Apr 20 run took 85h, logged 174,718 enriched, but only 1 agent ended up with `claimed_by` populated. Root cause: `src/scraper.py:enrich_agents` had zero `self.db.commit()` calls — `cli.py` close() rolled back the entire transaction. All other scrape stages commit. Patch (commit every 500 + at end) committed locally as `311b0d1`; pending VM push. With the patch, one more marathon run on Apr 27 fills `claimed_by` end-to-end; subsequent weeklies revert to normal size.

## Work laptop setup

- **2026-04-02 → 2026-04-03:** SSH setup saga (sessions 16-17). Key generated, config issues, permissions, public-key blocked by Hetzner console. Resolved: key added from home PC, ACL fixed via PowerShell. Still missing on work laptop: `.env`, `.venv/`, local `moltbook.db` — see session 16 log.

## Methodology log entries retired

Entries moved out of the active methodology log because they are now facts baked into code (no longer decisions that could be revisited):

- DB path `data/raw/moltbook.db` (session 2); UTF-8 encoding for Windows I/O (session 2); upstream remote setup.
- Proactive rate throttle removed (session 4, caused 429 storms).
- Comment cap revisions settled at 500 (session 7).
- Token bucket capacity=1.0 requirement (session 8).
- HPC approach superseded by Hetzner VM (session 6).
- `--only-missing` for enrich (session 9); `--skip-empty`, `fetch_comments_only()`, `--workers N` (sessions 6-7).
- `find` vs `ls glob` under `set -e` (session 12, baked into `status.sh`).
- SSH config alias setup (session 12, one-time infrastructure).
- Platform launched ~Jan 15 2026 (historical fact, session 5).

## Handover format evolution

- **2026-04-20:** Handover restructured from day-of-week checklist to relative-order + verification-checkpoint format (session 21).
- **2026-04-21:** Handover trimmed to launchpad-only; documentation discipline formalized (see session 22 log). Archive restructured from chronological to topical.
- **2026-04-27:** Handover restructured into state-conditional Block A / B / C with provenance tagging (`[verified]` / `[design]` / `[planned]`) — see session 24 log. Solved the "stale claim camouflaged in narrative prose" failure mode of session 23.
- **2026-05-03:** Block A / B / C structure retired (session 25). All three blocks executed; structure no longer applies to current state. Handover reverted to plain launchpad. The provenance-tagging convention is worth keeping as a discipline; it stays implicit in the new launchpad style.
- **2026-05-29:** CLAUDE.md pruned ~224 → ~140 lines (session 30). Removed detail blocks that duplicated `data/README.md` (data model, deletion-preservation) and the methodology log (API quirks, cron coordination, backup retention), condensed the snapshot-monitoring spec, and fixed stale lines (`*_snapshots`, runtime, bare-`pytest` example) — replaced with a "Reference & invariants" pointer section. `data/README.md` Phase-4 staleness corrected (legacy `*_snapshots` marked dropped; `*_metrics`/`*_events` field lists fixed to actual schema). No content lost — canonical homes are data/README.md / methodology log / readme_api_limit.md. Also: weekly runtime-budget TODO resolved (steady-state ~20 h, not 8-10 h; the 40 h May-11/18 runs = post-incident comments backlog + a one-off moderators rate-limit stall; session-30 log §1).
