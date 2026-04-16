# Claude Handover - Moltbook Scraper

**Last updated**: 2026-04-16 (session 20, Phase 1 done, Phase 2 audit complete, ready for Phase 3 design)
**Git state**: Branch `main`
**Local machine**: Windows 11, Python 3.14.0, venv at `.venv/`

---

## Current DB State (2026-04-14, VM)

| Table | Count (VM) | Status |
|-------|------------|--------|
| posts | 2,449K | Two weeklies completed since Apr 8 |
| submolts | 20,673 | `creator_id`, `post_count` populated. `is_nsfw`/`is_private` 100% false (likely genuine — see learnings) |
| moderators | 19,844 | Complete |
| comments | 4,159K | Complete |
| agents | 175,891 | **`claimed_by` populated for only 1/175,891 — scraper bug, see Next Steps #2** |
| comment_snapshots | 14.04M (8.32 GB) | All `scrape_run_id = NULL` but `scraped_at` per row preserves time identity (NOT corruption) |
| post_snapshots | 8.65M (6.72 GB) | Same as above |
| scrape_runs | 0 | Empty — staged CLI commands never open a run row |

**DB size**: 21.0 GB (VM). Local DB (Apr 8, 11 GB) is **pre-migration** — none of the new columns exist locally.
Pull updated DB: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**VM disk**: 40 GB free / 79 GB volume (48% used). Backups: 16.6 GB (one weekly copy). Root disk 19% used.
**Volume runway at current snapshot growth (~5 GB/wk):** ~8 weeks before action required.

---

## VM Automation (active since 2026-03-16)

**SSH**: `ssh vm` (alias → `root@159.69.34.240`)

| Schedule | Script | Duration |
|----------|--------|----------|
| Weekly Mon 02:00 UTC | `weekly_scrape.sh` | ~8-10h |
| Monthly 1st 02:00 UTC | `monthly_rescrape.sh` | ~5-7 days |
| Daily 08:00 UTC | `disk_monitor.sh` | <1s |

**Storage**: DB and backups live on 80 GB volume (`/mnt/HC_Volume_104999576/moltbook_data/`), symlinked from `data/raw/moltbook.db` and `data/backups/`. All scripts and `scp` commands work unchanged.

**Check**: `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
**Pull DB**: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`
**Push code**: `scp -r src/ scripts/ vm:~/moltbook_scraper/` then `dos2unix` on VM

**History**:
- Mar 23 weekly: 5/6 stages OK, snapshots OOM-killed. Fixed with swap (session 15).
- Mar 30 weekly: 5/6 stages OK, snapshots failed (disk full). Data through Mar 30 is complete.
- Apr 1 monthly & Apr 6 weekly: failed immediately (disk full, no space for backup copy).
- Apr 8 (session 18): disk fixed (80 GB volume, data migrated), weekly catch-up started.

---

## Resume next session (immediate next steps)

See [session 20 log](CLAUDE/session_logs/2026_04_16_session_log.md) for verification of Apr 13 weekly + audit completion. Session 19 log retains the original phase rationale.

1. **Restart backfill in tmux** (audit lock now released — verified session 20):
   ```bash
   ssh vm 'cd ~/moltbook_scraper && tmux new -d -s backfill "bash -c \"source .venv/bin/activate && python -u scripts/backfill_claimed_by.py --db data/raw/moltbook.db --log-file logs/backfill-claimed-by.log 2>&1 | tee -a logs/backfill-stdout.log; exec bash\""'
   ```
   (`exec bash` keeps the session alive if the script dies, so we can inspect stderr.)
2. **Run submolt flag probe** (fast, one-shot):
   ```bash
   ssh vm 'cd ~/moltbook_scraper && .venv/bin/python scripts/probe_submolt_flags.py'
   ```
3. **Design Phase 3 schema migration** using `tables/snapshot_mutability_audit_2026-04-14.csv`. Headline:
   - Comments: anchor-only (every column 0.0000 — no metrics panel needed at all).
   - Posts: anchor-only + tiny `post_metrics` for the 3 columns that actually move (upvotes/downvotes/comment_count, all <0.003 %).
   - Agents: first+latest anchors on live table; numeric (karma/follower/following) optional small panel.
   - **Submolts (new — wasn't in original Phase 3 list):** `description` (8.84 %) and `subscriber_count` (9.85 %) **fail** the 5 % gate → need anchor-pair or panel. Add to migration.

**Known gotcha:** SQLite is not in WAL mode. Long-running read queries (like the audit) block all writers (like the backfill). Either run sequentially or `PRAGMA journal_mode=WAL` before parallel read+write jobs.

---

## Returning After Absence

1. `ssh vm 'cd ~/moltbook_scraper && bash scripts/status.sh'`
2. `ssh vm 'tail -50 ~/moltbook_scraper/logs/weekly-*.log'`
3. If VM deleted: re-provision, push code + DB, set up cron (see [session 12 log](CLAUDE/session_logs/2026_03_15_session_log.md))
4. If >1 month gap: run catch-up (incremental → comments → enrich → snapshots)
5. Pull latest DB locally

---

## Work Laptop Setup

**SSH**: Configured and working (key added session 18). Test: `ssh vm 'echo connected'`
**Root password**: Set (session 18). Web console login: `root` + chosen password.
**Still missing on work laptop**: `.env` file, `.venv/`, local copy of `moltbook.db`. See session 16 log.

---

## Plan Status (session 19, 2026-04-14 — **approved**)

Full design, risk table, and rationale in [session 19 log](CLAUDE/session_logs/2026_04_14_session_log.md). This checklist is a pointer — update as steps complete.

### Decisions locked
- **Trajectories**: 4-week panel for comments/posts (`*_metrics`); agents get first + latest anchors only.
- **Hot-score**: `hot_score_first` + `hot_score_first_observed_at` on live `posts` (~85 MB one-time).
- **State flips**: event log (`*_events`) — one row per transition.
- **Monthly scrape**: writes to same narrow tables as weekly.
- **Compression gate**: content/title/description change-rate <5 % across existing snapshots.
- **VM cap**: 100 GB. Projected forward growth under new design: ~10–15 MB/week (~800 MB/year).
- **`claimed_by` backfill**: Tue–Sun gap, tmux, resumable.

### Checklist

**Phase 1 — Non-policy fixes** ✅ code on VM
- [x] 1a. `get_unenriched_agent_names()` predicate extended.
- [x] 1b. `scripts/backfill_claimed_by.py` created; **started but died on SQLite lock** — see Resume below.
- [x] 1c. `scrape_run_id` wired into `cli.py` snapshots.
- [x] 1d. `scripts/probe_submolt_flags.py` created — **not yet run**.

**Phase 2 — Audit snapshot mutability** ✅ complete (2026-04-16)
- [x] 2a. `scripts/audit_snapshot_mutability.py` created, composite indexes added to VM DB.
- [x] 2b. All 4 snapshot tables audited. CSV at `tables/snapshot_mutability_audit_2026-04-14.csv`; permanent VM table `snapshot_mutability_evidence`.
- [x] 2c. Results reviewed — gate decisions in section below.

**Final audit results (5 % compression gate):**
- `comment_snapshots`: every column **0.0000** across 9.88M pairs → drop comments metrics panel entirely.
- `post_snapshots`: every column ≤ 0.003 % across 6.20M pairs → anchor + tiny metrics panel for vote/comment counts.
- `agent_snapshots`: content <0.1 %, numeric (karma/follower/following) 0.4–2.2 % — all pass gate.
- `submolt_snapshots`: `description` 8.84 %, `subscriber_count` 9.85 % — **fail** gate. Add submolt schema work to Phase 3.

**Phase 3 — New schema (additive, reversible)** — scope revised after audit
- [ ] 3a. Migration in `database.py`: new tables (`post_metrics`, `post_events`, `agent_events`, `submolt_metrics`, `submolt_events`); add columns (`posts.hot_score_first`, `posts.hot_score_first_observed_at`; `agents.karma_first`, `follower_count_first`, `following_count_first`, `first_observed_at`). **No `comment_metrics` or `comment_events`** — comments are immutable per audit; first+latest anchors on live `comments` table only.
- [ ] 3b. New `scraper.create_snapshots()` logic: change-driven metric inserts; event-log state transitions; 4-week age filter.
- [ ] 3c. Insert-count logging + anomaly alert (R1).
- [ ] 3d. `tests/test_snapshot_change_detection.py` — 6 cases per session-19 R9.

**Phase 4 — Compress existing snapshots (⚠ USER SUPERVISION REQUIRED)**
> Do not start this phase except in a session where the user will remain until cron is re-enabled.
- [ ] 4a. Parquet backup to `data/backups/pre-compression_YYYY-MM-DD/*.parquet` (zstd).
- [ ] 4b. `crontab -l > /tmp/crontab.bak && crontab -r` on VM. **Log re-enable deadline.**
- [ ] 4c. Migrate existing snapshot data into new narrow/event tables; rename originals to `*_snapshots_v1_archive`.
- [ ] 4d. Create compatibility VIEWs named `*_snapshots` (UNION archive + new) for R code.
- [ ] 4e. Verify row counts + sample queries.
- [ ] 4f. **Re-enable cron**: `crontab /tmp/crontab.bak && crontab -l`. Confirm in session log.
- [ ] 4g. After 2 weeks stable: DROP `*_v1_archive`, DROP compat views (if R migrated), `VACUUM`.

**Phase 5 — Script updates**
- [ ] 5a. `weekly_scrape.sh` / `monthly_rescrape.sh` invocations unchanged (Python absorbs the change).
- [ ] 5b. `disk_monitor.sh` threshold loosening.

**Phase 6 — Docs / tests / R compat**
- [ ] 6a. `CLAUDE.md` data-dictionary section updated.
- [ ] 6b. `data/README.md` schema docs updated.
- [ ] 6c. `claude_methodology_log.md` entry for new snapshot policy.
- [ ] 6d. `analysis/R/` — either migrate queries or keep compat views permanently; log any R changes in methodology_log.

### Deferred (low priority, unaffected)
- Fix pre-existing `test_fetch_all_posts_paginates_until_no_more` (cursor pagination).
- Fix `status.sh` "0 errors" false-match.
- ~~Refactor snapshots to batch/stream~~ — **superseded** by Phase 3.

### Downstream (after Phase 4 verified)
- Pull updated DB locally: `scp vm:~/moltbook_scraper/data/raw/moltbook.db data/raw/`.
- Run R analysis pipeline `analysis/R/01_load_data.R` → `07_*`.

### Monitoring (R1) — how to read new snapshot logs
Each weekly snapshot run logs per-table: `inserted_metrics`, `inserted_events`, `entities_scanned`. Alert fires if:
- `inserted_metrics == 0` on a table with ≥1000 entities scanned (change detection likely broken — nothing being written).
- `inserted_metrics > 0.5 × entities_scanned` on comments/posts (change detection likely broken — writing on every scan, defeating the purpose).
See `claude_learnings.md → Snapshot monitoring` for interpretation rules.

---

## Key Reference

- **Schema**: `src/database.py:_create_tables()` + `_migrate()`
- **Rate limits**: `readme_api_limit.md`
- **API details**: see API Limitations in `CLAUDE.md`
- **Methodology**: `claude_methodology_log.md`
- **Learnings/dead-ends**: `claude_learnings.md`
- **Session logs**: `CLAUDE/session_logs/`
- **Archive**: `claude_archive.md`

---

## Email Alert Setup

See `CLAUDE/session_logs/2026_03_15_session_log.md` and the email guide preserved below.

<details>
<summary>Full email setup guide (Gmail app password + msmtp)</summary>

### Step 1: Create a Gmail App Password
1. Go to https://myaccount.google.com/security — ensure 2-Step Verification is ON
2. Go to https://myaccount.google.com/apppasswords
3. Create app named `moltbook-alerts`, copy the 16-char password (remove spaces)

### Step 2: Configure msmtp on VM
```bash
ssh vm
nano /root/.msmtprc
```
Set `from`, `user` to your Gmail, `password` to app password.

### Step 3: Set recipient in `.env`
```bash
nano ~/moltbook_scraper/.env
# Set MOLTBOOK_ALERT_EMAIL=your.email@example.com
```

### Step 4: Test
```bash
echo "Test" | msmtp your.email@example.com
```
</details>
