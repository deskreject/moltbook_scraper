#!/usr/bin/env bash
# monthly_rescrape.sh — Monthly full re-scrape for Moltbook on Hetzner VM
# Cron: 0 2 1 * *  (1st of month, 02:00 UTC)
#
# Stages: posts(full, --detect-deletions) → comments(full, --detect-deletions)
#         → enrich(--only-missing) → snapshots
#
# Long-running (~5-7 days for comments). Uses same lock file as weekly to
# prevent overlap (monthly takes priority).

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
SCRAPER_DIR="$HOME/moltbook_scraper"
PYTHON="$SCRAPER_DIR/.venv/bin/python"
DB_PATH="$SCRAPER_DIR/data/raw/moltbook.db"
BACKUP_DIR="$SCRAPER_DIR/data/backups"
LOG_DIR="$SCRAPER_DIR/logs"
LOCK_FILE="/tmp/moltbook_scrape.lock"
# Dedicated sentinel so weekly can skip cleanly (exit 0) while monthly runs.
# See weekly_scrape.sh and CLAUDE.md "Weekly / monthly cron coordination".
MONTHLY_SENTINEL="$SCRAPER_DIR/.monthly_running"
DATE=$(date -u +%Y-%m-%d)
LOG_FILE="$LOG_DIR/monthly-${DATE}.log"
KEEP_MONTHLY_BACKUPS=1
DATA_VOLUME="/mnt/HC_Volume_104999576"

# ─── Helpers ─────────────────────────────────────────────────────────────────
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"
}

send_email() {
    local subject="$1"
    local body="$2"
    if [[ -n "$EMAIL_TO" ]] && command -v msmtp &>/dev/null; then
        printf "Subject: %s\nFrom: moltbook-scraper@hetzner\n\n%s" "$subject" "$body" \
            | msmtp "$EMAIL_TO" 2>/dev/null || true
    fi
}

cleanup() {
    rm -f "$LOCK_FILE"
    rm -f "$MONTHLY_SENTINEL"
}

check_disk() {
    local usage path label
    for path in "$SCRAPER_DIR" "$DATA_VOLUME"; do
        [[ -d "$path" ]] || continue
        label=$(df "$path" --output=target | tail -1 | tr -d ' ')
        usage=$(df "$path" --output=pcent | tail -1 | tr -d ' %')
        if [[ "$usage" -ge 80 ]]; then
            log "WARNING: Disk usage at ${usage}% on $label"
            send_email "[MOLTBOOK] DISK WARNING: ${usage}% on $label" \
                "Disk usage on $(hostname) $label is at ${usage}%. Consider pruning backups or expanding disk."
        fi
    done
}

stage_timer() {
    local stage="$1"; shift
    local start end elapsed
    start=$(date +%s)
    log "START: $stage"
    if "$@" >> "$LOG_FILE" 2>&1; then
        end=$(date +%s)
        elapsed=$(( end - start ))
        log "DONE: $stage (${elapsed}s / $(( elapsed / 3600 ))h $(( (elapsed % 3600) / 60 ))m)"
        return 0
    else
        end=$(date +%s)
        elapsed=$(( end - start ))
        log "FAILED: $stage after ${elapsed}s"
        return 1
    fi
}

# ─── Lock ────────────────────────────────────────────────────────────────────
if [[ -f "$LOCK_FILE" ]]; then
    pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        log "Another scrape is running (PID $pid). Attempting to wait..."
        # Monthly takes priority — wait up to 2 hours for weekly to finish
        for i in $(seq 1 24); do
            sleep 300
            if ! kill -0 "$pid" 2>/dev/null; then
                log "Previous scrape finished after waiting $((i * 5)) minutes"
                break
            fi
            if [[ "$i" -eq 24 ]]; then
                log "ERROR: Previous scrape still running after 2 hours. Exiting."
                send_email "[MOLTBOOK] Monthly BLOCKED" \
                    "Monthly re-scrape could not acquire lock after 2 hours. PID $pid still running."
                exit 1
            fi
        done
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
# Write dedicated monthly sentinel so any cron-overlapping weekly can skip cleanly.
date -Iseconds > "$MONTHLY_SENTINEL"
trap cleanup EXIT INT TERM

# ─── Setup ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$BACKUP_DIR"
cd "$SCRAPER_DIR"

[[ -f .env ]] && set -a && source .env && set +a
EMAIL_TO="${MOLTBOOK_ALERT_EMAIL:-}"

SCRIPT_START=$(date +%s)
log "=========================================="
log "MONTHLY FULL RE-SCRAPE — $DATE"
log "=========================================="

send_email "[MOLTBOOK] Monthly re-scrape STARTED" \
    "Monthly full re-scrape started on $(hostname) at $(date -u).\nExpected duration: 5-7 days."

# ─── Pre-scrape DB Backup ────────────────────────────────────────────────────
log "Backing up database (pre-scrape)..."
BACKUP_PRE="$BACKUP_DIR/moltbook-monthly-pre-${DATE}.db"
sqlite3 "$DB_PATH" ".backup '$BACKUP_PRE'"
log "Pre-scrape backup: $BACKUP_PRE ($(du -h "$BACKUP_PRE" | cut -f1))"

# ─── Stages ──────────────────────────────────────────────────────────────────
ERRORS=0
STAGES_RUN=0

run_stage() {
    local name="$1"; shift
    STAGES_RUN=$((STAGES_RUN + 1))
    if ! stage_timer "$name" "$@"; then
        ERRORS=$((ERRORS + 1))
        log "ERROR: Stage '$name' failed — continuing with remaining stages"
        send_email "[MOLTBOOK] MONTHLY FAILURE: $name" \
            "Stage '$name' failed during monthly re-scrape on $DATE.\nSee log: $LOG_FILE"
    fi
    # Check disk after each stage (long-running)
    check_disk
}

run_stage "posts-full"   "$PYTHON" -u -m src.cli posts    --db "$DB_PATH" --detect-deletions --log-file "$LOG_DIR/scrape-posts.log"
run_stage "comments-full" "$PYTHON" -u -m src.cli comments --db "$DB_PATH" --detect-deletions --log-file "$LOG_DIR/scrape-comments.log"
run_stage "enrich"       "$PYTHON" -u -m src.cli enrich   --db "$DB_PATH" --only-missing --log-file "$LOG_DIR/scrape-enrich.log"
run_stage "snapshots"    "$PYTHON" -m src.cli snapshots    --db "$DB_PATH"

# ─── Post-scrape DB Backup ───────────────────────────────────────────────────
BACKUP_POST="$BACKUP_DIR/moltbook-monthly-post-${DATE}.db"
sqlite3 "$DB_PATH" ".backup '$BACKUP_POST'"
log "Post-scrape backup: $BACKUP_POST ($(du -h "$BACKUP_POST" | cut -f1))"

# ─── DB Stats ────────────────────────────────────────────────────────────────
DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
DISK_FREE=$(df -h "$SCRAPER_DIR" --output=avail | tail -1 | tr -d ' ')
log "DB size: $DB_SIZE | Disk free: $DISK_FREE"

# ─── Prune old monthly backups ───────────────────────────────────────────────
log "Pruning old monthly backups (keeping last $KEEP_MONTHLY_BACKUPS pair)..."
for prefix in "moltbook-monthly-pre-" "moltbook-monthly-post-"; do
    ls -1t "$BACKUP_DIR"/${prefix}*.db 2>/dev/null | tail -n +$((KEEP_MONTHLY_BACKUPS + 1)) | while read -r old; do
        log "  Removing: $(basename "$old")"
        rm -f "$old"
    done
done

# ─── Summary ─────────────────────────────────────────────────────────────────
SCRIPT_END=$(date +%s)
TOTAL_TIME=$(( SCRIPT_END - SCRIPT_START ))
TOTAL_HOURS=$(( TOTAL_TIME / 3600 ))
TOTAL_MINS=$(( (TOTAL_TIME % 3600) / 60 ))

if [[ "$ERRORS" -eq 0 ]]; then
    STATUS="SUCCESS"
else
    STATUS="PARTIAL FAILURE ($ERRORS/$STAGES_RUN stages failed)"
fi

SUMMARY="$STATUS: Monthly re-scrape completed in ${TOTAL_HOURS}h ${TOTAL_MINS}m ($STAGES_RUN stages, $ERRORS errors)
DB size: $DB_SIZE | Disk free: $DISK_FREE"

log "$SUMMARY"
log "=========================================="

send_email "[MOLTBOOK] Monthly $DATE — $STATUS" "$SUMMARY

Log: $LOG_FILE
Host: $(hostname)"
