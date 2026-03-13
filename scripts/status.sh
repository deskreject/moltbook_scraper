#!/usr/bin/env bash
# status.sh — Show Moltbook scraper status on Hetzner VM
# Run manually via SSH to check scraper health.

set -euo pipefail

SCRAPER_DIR="$HOME/moltbook_scraper"
DB_PATH="$SCRAPER_DIR/data/raw/moltbook.db"
LOG_DIR="$SCRAPER_DIR/logs"
BACKUP_DIR="$SCRAPER_DIR/data/backups"

# ─── Header ──────────────────────────────────────────────────────────────────
echo "Moltbook Scraper Status — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Host: $(hostname)"
echo "=========================================="

# ─── Database ────────────────────────────────────────────────────────────────
if [[ -f "$DB_PATH" ]]; then
    DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
    echo "DB size:        $DB_SIZE"

    # Quick row counts via sqlite3
    if command -v sqlite3 &>/dev/null; then
        POSTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM posts;")
        COMMENTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM comments;")
        AGENTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM agents;")
        SUBMOLTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM submolts;")
        DELETED_POSTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM posts WHERE is_deleted = 1;" 2>/dev/null || echo "N/A")
        DELETED_COMMENTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM comments WHERE is_deleted = 1;" 2>/dev/null || echo "N/A")
        echo "Posts:          $POSTS (deleted: $DELETED_POSTS)"
        echo "Comments:       $COMMENTS (deleted: $DELETED_COMMENTS)"
        echo "Agents:         $AGENTS"
        echo "Submolts:       $SUBMOLTS"

        LATEST_POST=$(sqlite3 "$DB_PATH" "SELECT created_at FROM posts ORDER BY created_at DESC LIMIT 1;" 2>/dev/null || echo "N/A")
        echo "Latest post:    $LATEST_POST"
    else
        echo "  (sqlite3 not installed — cannot query DB)"
    fi
else
    echo "DB:             NOT FOUND at $DB_PATH"
fi
echo ""

# ─── Disk ────────────────────────────────────────────────────────────────────
DISK_TOTAL=$(df -h "$SCRAPER_DIR" --output=size  | tail -1 | tr -d ' ')
DISK_FREE=$(df -h "$SCRAPER_DIR" --output=avail | tail -1 | tr -d ' ')
DISK_PCT=$(df "$SCRAPER_DIR" --output=pcent | tail -1 | tr -d ' %')
echo "Disk:           $DISK_FREE free / $DISK_TOTAL total (${DISK_PCT}% used)"

# ─── Backups ─────────────────────────────────────────────────────────────────
if [[ -d "$BACKUP_DIR" ]]; then
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.db 2>/dev/null | wc -l)
    BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    echo "Backups:        $BACKUP_COUNT files ($BACKUP_SIZE total)"
    if [[ "$BACKUP_COUNT" -gt 0 ]]; then
        LATEST_BACKUP=$(ls -1t "$BACKUP_DIR"/*.db 2>/dev/null | head -1)
        echo "  Latest:       $(basename "$LATEST_BACKUP") ($(du -h "$LATEST_BACKUP" | cut -f1))"
    fi
else
    echo "Backups:        directory not found"
fi
echo ""

# ─── Last scrapes ────────────────────────────────────────────────────────────
echo "Recent scrapes:"
for pattern in weekly monthly; do
    LATEST_LOG=$(ls -1t "$LOG_DIR"/${pattern}-*.log 2>/dev/null | head -1 || true)
    if [[ -n "$LATEST_LOG" ]]; then
        LOG_DATE=$(basename "$LATEST_LOG" | sed "s/${pattern}-//; s/\.log//")
        # Check for SUCCESS/FAILURE in last 5 lines
        STATUS=$(tail -5 "$LATEST_LOG" 2>/dev/null | grep -oE '(SUCCESS|PARTIAL FAILURE|FAILURE)' | head -1 || echo "UNKNOWN")
        echo "  Last ${pattern}:    $LOG_DATE — $STATUS"
    else
        echo "  Last ${pattern}:    (no logs found)"
    fi
done
echo ""

# ─── Cron jobs ───────────────────────────────────────────────────────────────
echo "Cron jobs:"
CRON_COUNT=$(crontab -l 2>/dev/null | grep -c moltbook || echo "0")
if [[ "$CRON_COUNT" -gt 0 ]]; then
    crontab -l 2>/dev/null | grep moltbook | while read -r line; do
        echo "  $line"
    done
else
    echo "  (none found)"
fi
echo ""

# ─── Recent errors ───────────────────────────────────────────────────────────
echo "Recent errors (last 7 days):"
ERROR_COUNT=0
for logfile in "$LOG_DIR"/*.log; do
    [[ -f "$logfile" ]] || continue
    # Only check logs modified in last 7 days
    if find "$logfile" -mtime -7 -print -quit 2>/dev/null | grep -q .; then
        count=$(grep -c -i "ERROR\|FAILED\|FAILURE" "$logfile" 2>/dev/null || echo "0")
        if [[ "$count" -gt 0 ]]; then
            echo "  $(basename "$logfile"): $count error(s)"
            ERROR_COUNT=$((ERROR_COUNT + count))
        fi
    fi
done
if [[ "$ERROR_COUNT" -eq 0 ]]; then
    echo "  None"
fi
echo ""

# ─── Lock file ───────────────────────────────────────────────────────────────
if [[ -f "/tmp/moltbook_scrape.lock" ]]; then
    LOCK_PID=$(cat /tmp/moltbook_scrape.lock 2>/dev/null || echo "")
    if [[ -n "$LOCK_PID" ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "Active scrape:  PID $LOCK_PID (running)"
    else
        echo "Active scrape:  stale lock file (PID $LOCK_PID not running)"
    fi
else
    echo "Active scrape:  none"
fi

echo "=========================================="
