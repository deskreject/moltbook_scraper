# Session 28 — 2026-05-12

Continuation day after session 27. Two pieces of work: (1) the May 11 weekly finished successfully late afternoon and the post-run state is recorded below, (2) a substantial investigation into the `kelkalot/moltbook-observatory` repo to assess whether our archive duplicates theirs, or whether the value of our data justifies the meeting partner's interest. Several concrete follow-up probes emerged; those are forwarded to the handover as TODOs.

## May 11 weekly — completion summary

- **Final status**: `SUCCESS: Weekly scrape completed in 146186s (6 stages, 0 errors)` at 2026-05-12 18:36:27 UTC.
- **Total runtime**: 40 h 36 min — substantially longer than the 8-10 h documented in CLAUDE.md. Worth a runtime-budget reassessment (see TODOs in handover).
- **Stage order observed** (different from CLAUDE.md description): `incremental → comments → moderators → enrich → snapshots`. Enrich stage alone ran 7 h 03 min and reported 311 individual-agent errors (`enriched 8,847 agents, 311 errors`). These are individual API failures, not a stage-level failure; worth a sanity check on whether 3.5 % is a normal failure rate for enrich or a regression.
- **Snapshot writer output** (the change-driven Phase-3a writer):
  - posts: `entities_scanned=2939474, inserted_metrics=68593, inserted_events=1, anchors_set=70539`
  - agents: `entities_scanned=179364, inserted_metrics=2623, inserted_events=0, anchors_set=9436`
  - submolts: `entities_scanned=28302, inserted_metrics=4274, anchors_set=4587`
  - moderators: `entities_scanned=27467, inserted_events=4128`
  - All within the "Normal" ranges from CLAUDE.md's snapshot monitoring section. No Alert A/B/C triggered.
- **Backup pruning ran correctly**: May 4 weekly removed; May 11 weekly (7.4 GB) and May 5 monthly-post (7.4 GB) retained. Total backups dir 14.8 GB.
- **Disk-free reporting bug discovered**: the weekly footer logged `Disk free: 29G`, but `df -h /mnt/HC_Volume_104999576` shows 72 GB free / 99 GB total / 24 % used. The 29G figure appears to be reading the wrong mount (system disk, not the data volume). Same family as the existing `DB size: 0` cosmetic bug in `status.sh`.

## Post-weekly table state (2026-05-12 18:36 UTC)

| Table | Rows | Δ from yesterday |
|---|---|---|
| posts | 2,939,474 | 0 (no new incremental posts) |
| comments | 5,629,305 | +17,889 |
| agents | 179,364 | 0 |
| submolts | 28,302 | 0 |
| moderators | 27,467 | +1,110 |
| post_metrics | 521,725 | +68,593 |
| agent_metrics | 186,022 | +2,623 |
| submolt_metrics | 28,548 | +4,274 |
| post_events | 292,488 | +1 |
| agent_events | **0** | 0 |
| moderator_events | 27,467 | +4,128 |

`agent_events = 0` is sustained after the snapshot run wrote 9,436 new agent anchors. This is structurally curious — see TODOs.

## Observatory analysis — main findings

(This is the bulk of today's work and the reason a comprehensive write-up belongs here rather than in any other doc. The handover only needs the TODOs that follow from it.)

### What Observatory collects

**Endpoints used** (from `observatory/poller/client.py`):
- `GET /posts?sort=new&limit=50` (every 2 min)
- `GET /posts?sort=hot&limit=25` (every 2 min)
- `GET /posts/{id}/comments` (every 2 min, only for posts whose stored count < platform count; caps at ~900 stored)
- `GET /submolts` (every hour)
- `GET /agents/profile?name=X` (every 15 min, 20 least-recently-updated agents per cycle)
- `GET /search?q=...` (exposed in client; not called by scheduler I can see)
- `GET /agents/me` (auth health)

**Storage**: SQLite, schema in `observatory/database/migrations.py`. Seven tables: `agents`, `posts`, `comments`, `submolts`, `follows`, `snapshots`, `word_frequency`.

**Key schema property — latest-value overwrite**: every numeric field that changes over time (`posts.score`, `posts.comment_count`, `posts.is_pinned`, `agents.karma/follower_count/following_count`, `comments.score`, `submolts.subscriber_count/post_count`) is overwritten on every poll. No history is kept. The only time-series persistence is in the hourly `snapshots` table (platform-wide totals + avg sentiment + top 10 words) and `word_frequency` (per-word per-hour counts). They do not have entity-level panels.

### What Observatory exposes for download

From `observatory/web/routes.py` — four export endpoints:
- `GET /api/export/posts.csv` — `SELECT id, agent_name, submolt, title, content, score, comment_count, created_at FROM posts ORDER BY created_at DESC`
- `GET /api/export/agents.csv` — agents table flat, ordered by karma DESC
- `GET /api/export/comments.csv` — comments + post_url, ordered by created_at DESC
- `GET /api/export/database.db` — **the complete SQLite file as one HTTP GET**

So a researcher can in principle mirror their entire archive with a single curl. But the result is a frozen photograph of latest values plus the hourly platform aggregates — it does not contain vote trajectories, deletion timelines, or state transitions, because those were never persisted in their DB to begin with.

### Schema comparison vs. ours

| Dimension | Observatory | This project |
|---|---|---|
| Historical depth | Polls forward from deployment date (Jan 30 2026 commit, earliest possible) — no backfill | Cursor-paginated `sort=new` sweep walks platform backwards on first scrape; pre-deployment posts captured |
| Vote / engagement history | Latest only (`score` overwritten) | `post_metrics` change-driven panel + `hot_score_first` capture (within 4-week post-age cutoff) |
| State transitions | None | `*_events` log for pinned/locked/deleted/spam/verification/mod-role transitions |
| Mutable text | Latest only | First+latest anchor columns (`description_first`, `description_latest`) |
| Deletion detection | Not modeled | `is_deleted`, `deleted_detected_at`, `deletion_uncertain`; content preservation guard |
| Moderators | Not modeled | Full `moderators` table + role events |
| Comment cap per post | ~900 stored (their code comment says API ceiling is "~1000") | 500 (our `readme_api_limit.md` says hard cap 500, no pagination) — **discrepancy worth resolving; see TODOs** |
| Follow graph | `follows` table declared in `migrations.py`, **no writer in `processors.py`** — aspirational, never populated | Not modeled; our `readme_api_limit.md` says graph isn't exposed |
| Sentiment scoring | TextBlob polarity on title+content, stored only in hourly platform aggregate `snapshots.avg_sentiment` | None (can be added as post-hoc analysis) |
| Word trends | `word_frequency` per-hour panel + %-change ranking | None (post-hoc) |
| Posts collection mode | Top 50 of `sort=new` + top 25 of `sort=hot` every 2 min | Cursor sweep with `has_more`, no top-N truncation |

### Value proposition — where our data is unique

**Live-table uniqueness (numerically bounded):**
- Posts created before Observatory's first commit (2026-01-30 19:24 UTC): **5,155** of our 2,939,474 posts (0.18 %)
- Comments created before that timestamp: **27,453** of our 5,629,305 (0.49 %)
- Oldest post in our DB: 2026-01-27 18:01 UTC. Oldest comment: 2026-01-28 01:18 UTC.
- These are literally unrecoverable for Observatory — they predate their deployment.
- Plus: posts that fell through Observatory's 2-minute `sort=new` polling-window blindspot (any post buried by 50+ newer posts within 2 min that never made `sort=hot`). This count is unbounded — depends on Moltbook's burst rate. Quantifying it is a TODO.

**Change-driven-panel uniqueness (qualitatively complete):**
- Every column of `post_metrics`, `agent_metrics`, `submolt_metrics`, `*_events`, and the `*_first/_latest` anchor pairs is unique to us. Observatory's schema cannot encode any of this. No volume of download from their endpoint can reconstruct it.

### Why their data may be SMALLER than ours

The meeting partner reportedly has less data on hand than we do. Plausible explanations, in order of likelihood:
1. They have Observatory's `posts.csv` export (latest snapshot of content), not our full corpus. Observatory's `posts` table has fewer rows because of (a) post-deployment-only collection and (b) the 2-min `sort=new` polling blindspot.
2. Their comment archive is bounded by Observatory's per-post 900-cap (which may or may not be tighter than the real API ceiling — see TODO below).
3. No moderator data, no event log, no metric panels in Observatory at all.

Genuine concern raised by the user: could our DB instead have duplicates / redundancies that inflate counts artificially? Worth a spot check — `posts.id` is a PRIMARY KEY so true row duplication is impossible at the DB level, but a content-level check (e.g., same `(agent_id, title, content, created_at)` appearing under multiple ids) would catch any case where Moltbook re-issued IDs. Low prior but cheap to run.

### Reverse direction — what Observatory has that we don't

- Per-post sentiment polarity (TextBlob title+content). Cheap to compute post-hoc; not a structural gap.
- Hourly word-frequency panel for language-diffusion analysis. Derivable from our content store.
- Public-facing dashboard / observation web UI. Not in scope for this project.
- The `follows` table — confirmed aspirational; their code does not populate it. So this is NOT a capability they have, just a schema declaration. The probe to confirm whether `/agents/profile` exposes a follower list is still warranted (see handover TODOs).

## Files touched

- `CLAUDE/session_logs/2026_05_12_session_log.md` — this file
- `claude_handover.md` — added two TODO blocks (Observatory follow-up + weekly-runtime / status.sh reporting bugs), pointing here

## Open questions and next actions

All material questions forwarded to handover as TODOs. The key ones:

1. **500 vs 1000 comment cap** — backtrace why we settled on 500 (probably session 6-8 work in March 2026, see `readme_api_limit.md`); then test the API on a known-high-comment post. If the real cap is 1000, the weekly's `--workers 16 limit=500` config is missing the tail of every popular thread, and the comment-archive size implications are significant.
2. **2-min polling-window adequacy** — what fraction of historical 2-minute windows have ≥ 25 posts/min created? On any such window Observatory misses posts; this gives an upper-bound estimate of their structural gap relative to us.
3. **agent_events = 0** — even after this run wrote 9,436 new agent anchors and 2,623 metric inserts, no transitions ever observed for agents. Either no `is_claimed` or `verification_status` flip has happened in the entire observation history, or the agent-event writer has a bug specific to those fields.
4. **Posts content-deduplication probe** — verify the same content doesn't appear under multiple ids; rules out a hypothetical inflation in our corpus relative to Observatory's.

## Rollback

No risky changes. Handover edits and this log are documentation-only. Both files reside in the project repo and revert via `git checkout -- claude_handover.md CLAUDE/session_logs/2026_05_12_session_log.md` if needed.
