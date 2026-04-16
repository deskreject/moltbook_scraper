## Methodology Log

Active decisions that guide current scraping, analysis, and infrastructure. Historical/resolved entries archived in `claude_archive.md`.

| Date       | Decision                                   | Reasoning                                                        | Status      |
|------------|--------------------------------------------|-----------------------------------------------------------------|-------------|
| 2026-02-05 | Use snapshot tables for all analysis        | Reproducibility: live tables mutate on each scrape               | Established |
| 2026-02-13 | Staged scrape instead of monolithic `full`   | At 60 req/min, full scrape takes days; stages are resumable     | Established |
| 2026-02-28 | Posts: cursor-based pagination (`has_more` + `next_cursor`) | API uses cursor, not offset | Active |
| 2026-02-28 | Submolts: page-based pagination (`?page=N`, 20/page) | Different from posts | Active |
| 2026-02-28 | Comments: separate endpoint (`/posts/{id}/comments`) | Not embedded in post response | Active |
| 2026-02-28 | `_normalize_agent()` applied to all embedded author objects | API camelCase → DB snake_case | Active |
| 2026-03-02 | Posts scrape must use `sort=new` | `sort=hot` caps at ~70K posts; `sort=new` gives full archive | Active |
| 2026-03-05 | Rate limit: 60/min (not 100); token bucket at 55/min | Production header `X-RateLimit-Limit: 60`; do NOT raise without re-checking | Active |
| 2026-03-05 | Comments fetch uses `limit=500` (server hard cap) | 500/post, no pagination; ~1,507 posts truncated | Active |
| 2026-03-05 | Sequential scraping only (1 worker) | Multi-worker is slower for this API; parallelize across machines/IPs | Active |
| 2026-03-05 | Use `python -u` for all background scrapes | Prevents silent error loss from buffered stdout | Active |
| 2026-03-13 | Schema migrations for new API fields | Posts: type, is_locked, is_spam, score, hot_score, etc. Comments: is_spam, depth, reply_count, score, etc. Agents: display_name, posts_count, is_active, last_active, etc. | Active |
| 2026-03-13 | Deletion detection via `--detect-deletions` | Posts: marks unseen after full pagination. Agents: 404 → `deleted_at`. Monthly only. | Active |
| 2026-03-13 | Weekly/monthly cron on Hetzner VM | Weekly Mon 02:00 UTC (incremental); Monthly 1st 02:00 UTC (full + deletions) | Active |
| 2026-03-16 | All scraping runs on VM, not locally | Lower latency, doesn't tie up local machine. Local only if <1h and user approves | Active |
| 2026-03-16 | Always `dos2unix` after `scp` to VM | Windows CRLF breaks bash and Python on Linux | Active |
| 2026-03-20 | VM scripts use `.venv/bin/python` explicitly | Ubuntu 24.04 has no `python` binary | Active |
| 2026-03-26 | 4 GB swap on VM as temporary OOM fix | Snapshot stage OOM-killed at 11 GB DB. Swap buys weeks/months; batch refactor is the proper fix | Temporary |
| 2026-04-08 | DB and backups on 80 GB Hetzner volume | Root disk (38 GB) too small for DB + backups. Symlinked from original paths. | Active |
| 2026-04-08 | Backup via `sqlite3 .backup` not `cp` | Safer for live DB (handles locking). Applied to both weekly and monthly scripts. | Active |
| 2026-04-08 | Weekly backup retention reduced to 1 | 2 backups + DB exceeded 38 GB root disk. With 80 GB volume, 1 backup is sufficient. | Active |
| 2026-04-08 | Daily disk monitor cron (independent) | In-script `check_disk()` doesn't fire if script fails before reaching it. Standalone cron catches issues early. | Active |
| 2026-04-08 | Schema: `claimed_by` (agents), `creator_id`/`post_count`/`is_nsfw`/`is_private` (submolts) | Upstream fields silently dropped. COALESCE on submolt upsert to preserve metadata. | Active |
| 2026-04-08 | Agent model/LLM info not available via API | No fields for model, provider, or version. Stylometric inference from text is the research path. | Established |
| 2026-04-14 | Snapshot redesign: narrow change-driven metrics + event log | Full-copy weekly snapshots cost ~5 GB/wk, would fill 100 GB cap in months. New design: `*_metrics` (upvotes/downvotes/score/hot_score/reply_count/comment_count, 4-week panel for comments/posts only); `*_events` (state flips: is_pinned/is_locked/is_deleted/is_spam/verification_status); first+latest hot_score on live `posts`; agents get first-observed anchors on live table only. Projected growth: ~10–15 MB/wk. See session 19 log. | Active (implementing) |
| 2026-04-14 | Snapshot age cutoff: 4 weeks for metrics panels | Comments/posts vote velocity matters in early life; after 4 weeks, live-table latest is sufficient for most research. Trade-off accepted: no trajectory for late-life engagement bursts. | Active |
| 2026-04-14 | State-transition tracking via event log not state-with-last-change | Preserves full flip history (e.g. pinned→unpinned→pinned); negligible storage cost because transitions are rare. | Active |
| 2026-04-14 | `claimed_by` backfill via extended `get_unenriched_agent_names()` predicate | Weekly `enrich --only-missing` filters on missing description, so post-migration columns stay NULL for already-enriched agents. Predicate now also catches `is_claimed=1 AND claimed_by IS NULL`. One-off 48h tmux run for historical backfill. | Active |
| 2026-04-14 | Pre-compression backup format: Parquet zstd, not SQLite .backup | ~21 GB → ~3–5 GB; retrievable via pandas/pyarrow if ever needed. Keeps volume below 100 GB cap during migration. | Active |
| 2026-04-14 | `snapshot_mutability_evidence` table + `tables/` CSV preserved | Research defensibility: if a publication claims content fields change linearly/rarely, this audit of the 4 historical full snapshots is citable evidence. Permanent. | Active |
| 2026-04-14 | Composite indexes `idx_{table}_snap_entity_time` on all `*_snapshots` | Required for chronological per-entity walks (audits, future migrations). Audit script hung 2h without them, ran in 23s with them. | Active |
| 2026-04-16 | Phase 3 schema scope expanded to include `submolts` | Audit shows `submolts.description` (8.84%) and `subscriber_count` (9.85%) exceed 5% compression gate — they need a metrics-panel or anchor-pair, not first-only. Comments at 0.0000% across all columns; posts ≤ 0.003%. See session 20 log + `tables/snapshot_mutability_audit_2026-04-14.csv`. | Active |
| 2026-04-16 | `comment_snapshots` use first+latest anchor only (no metrics panel) | Audit shows 0.0000% change rate across every column on 9.88M consecutive pairs. The 4-week metrics panel for comments is empirically unnecessary — eliminates a table from the Phase 3 design. | Active |
