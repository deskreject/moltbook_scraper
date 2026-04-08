# Session 18 — 2026-04-08

## Goal
Post-absence recovery: diagnose and fix VM issues, catch up on missed scrapes, apply schema gaps.

## What was done

### VM Recovery
1. **Diagnosed disk exhaustion**: VM disk (38 GB) was 100% full. Root cause: DB (11 GB) + 2 weekly backups (21 GB) + swap (4 GB) + OS exceeded capacity. Apr 1 monthly and Apr 6 weekly both failed immediately on `cp: No space left on device`. Email alerts also failed (msmtp can't write temp files on full disk).
2. **Freed immediate space**: Deleted stale backups (Mar 23 weekly + 2 truncated Apr backups), freeing ~10 GB.
3. **Resized Hetzner volume**: User expanded volume to 80 GB. Ran `resize2fs /dev/sdb` to make filesystem match.
4. **Migrated data to volume**: Moved `moltbook.db` and `data/backups/` to `/mnt/HC_Volume_104999576/moltbook_data/`, created symlinks from original paths. All scripts, `scp`, and CLI commands continue to work unchanged.
5. **SQLite journal cleanup**: 183 MB journal from failed snapshot write was rolled back cleanly by SQLite on next access. No data loss.
6. **Disk state after**: root disk 19% (6.6 GB / 38 GB), volume 28% (21 GB / 79 GB), 55 GB free.

### Email & Monitoring
7. **Tested email alerts**: Confirmed msmtp works now that disk has space. Test email sent to `alexander.staub@esade.edu`.
8. **Standalone disk monitor**: Created `scripts/disk_monitor.sh` — daily cron (08:00 UTC) checks both root disk and data volume, emails if either exceeds 80%. Independent of scrape scripts.

### Script Optimizations
9. **Backup method**: Changed `cp` → `sqlite3 .backup` in both weekly and monthly scripts (safer for live DBs).
10. **Weekly backup retention**: Reduced from 2 → 1 (saves ~11 GB).
11. **`check_disk()` updated**: Both scripts now check both root disk and data volume (not just `$SCRAPER_DIR`).

### SSH & Access
12. **Fixed SSH config permissions** on home PC: Removed CodexSandboxUsers inherited permissions via PowerShell ACL.
13. **Added work laptop SSH key** to VM `authorized_keys`.
14. **Root password**: Not yet set — user to run `ssh vm passwd` from a terminal.

### Schema Upgrades (session 13 backlog)
15. **Agents**: Added `claimed_by TEXT` column via migration. Updated `upsert_agent()` and `save_agent_snapshot()`.
16. **Submolts**: Added `creator_id TEXT`, `post_count INTEGER`, `is_nsfw INTEGER`, `is_private INTEGER` via migration. Updated `upsert_submolt()` with COALESCE for all fields (previously overwrote metadata). Updated `save_submolt_snapshot()`.
17. **Pushed to VM**: Migration ran successfully, all 5 new columns confirmed.

### Scrape & Local DB
18. **Weekly scrape started**: Running on VM since ~15:08 UTC. Incremental stage pulling new posts (9 days of missed data).
19. **Local DB replaced**: 11 GB download from VM completed. Row counts verified matching (2.24M posts, 3.55M comments, 174K agents, 20.5K submolts, 19.7K moderators).

## Outcome
VM is operational again with 55 GB free space. Weekly scrape is running. Local DB is current through Mar 30. Schema upgrades deployed — new fields will be populated by the running weekly scrape.

## Late-session issues
- Accidentally launched pytest 3 times against the 11 GB production DB, consuming ~45 GB RAM. Killed via PowerShell. Added to learnings.md.
- Root password set by user via `ssh vm passwd`.
- Weekly scrape at session end: comments stage 29% (26.4K/91.7K posts, 304K comments, 0 errors). Expected to complete overnight.

## Pending
- Monthly scrape — defer until weekly completes and schema fields are verified populated
- Snapshot batch refactor (handover item 5) — lower priority now with 80 GB volume
- Verify new schema fields populated after weekly completes (check `claimed_by`, `creator_id`, etc.)
- Run tests locally (single invocation) to confirm no regressions
