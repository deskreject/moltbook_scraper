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
