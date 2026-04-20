#!/usr/bin/env bash
# weekly_scrape.sh — Weekly incremental scrape for Moltbook on Hetzner VM
# Cron: 0 2 * * 1  (Monday 02:00 UTC)
#
# Stages: incremental → submolts → comments(--only-missing --skip-empty)
#         → moderators → enrich(--only-missing) → snapshots
#
# Duration: ~8-10 hours (moderators ~7h is the bottleneck — 19.6K submolts at ~47/min)
# Features: lock file, DB backup, per-stage timing, email summary, backup pruning

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
SCRAPER_DIR="$HOME/moltbook_scraper"
PYTHON="$SCRAPER_DIR/.venv/bin/python"
DB_PATH="$SCRAPER_DIR/data/raw/moltbook.db"
BACKUP_DIR="$SCRAPER_DIR/data/backups"
LOG_DIR="$SCRAPER_DIR/logs"
LOCK_FILE="/tmp/moltbook_scrape.lock"
# Dedicated sentinel written by monthly_rescrape.sh so weekly can skip cleanly
# (exit 0, no cron-failure alert) rather than treating monthly as a conflict.
MONTHLY_SENTINEL="$SCRAPER_DIR/.monthly_running"
DATE=$(date -u +%Y-%m-%d)
LOG_FILE="$LOG_DIR/weekly-${DATE}.log"
KEEP_WEEKLY_BACKUPS=1
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
    # Usage: stage_timer "stage_name" command args...
    local stage="$1"; shift
    local start end elapsed
    start=$(date +%s)
    log "START: $stage"
    if "$@" >> "$LOG_FILE" 2>&1; then
        end=$(date +%s)
        elapsed=$(( end - start ))
        log "DONE: $stage (${elapsed}s)"
        return 0
    else
        end=$(date +%s)
        elapsed=$(( end - start ))
        log "FAILED: $stage after ${elapsed}s"
        return 1
    fi
}

# ─── Monthly-in-progress check ──────────────────────────────────────────────
# If a monthly run is active, skip this weekly entirely (exit 0, no alert).
# Stale-sentinel recovery: >7 days old means monthly almost certainly crashed
# without cleanup; warn and proceed.
mkdir -p "$LOG_DIR"  # needed before log() can write
if [[ -f "$MONTHLY_SENTINEL" ]]; then
    now_s=$(date +%s)
    sentinel_s=$(stat -c %Y "$MONTHLY_SENTINEL" 2>/dev/null || echo "$now_s")
    age_min=$(( (now_s - sentinel_s) / 60 ))
    if [[ "$age_min" -gt 10080 ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARN: stale monthly sentinel (age ${age_min}m > 7d), removing and proceeding" | tee -a "$LOG_FILE"
        rm -f "$MONTHLY_SENTINEL"
    else
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Monthly in progress since $(cat "$MONTHLY_SENTINEL" 2>/dev/null). Skipping weekly." | tee -a "$LOG_FILE"
        exit 0
    fi
fi

# ─── Lock ────────────────────────────────────────────────────────────────────
if [[ -f "$LOCK_FILE" ]]; then
    pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Another scrape is running (PID $pid). Exiting."
        exit 1
    fi
    echo "Stale lock file found (PID $pid not running). Removing."
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap cleanup EXIT

# ─── Setup ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$BACKUP_DIR"
cd "$SCRAPER_DIR"

# Source .env if present (must come before EMAIL_TO assignment — cron has no env vars)
[[ -f .env ]] && set -a && source .env && set +a
EMAIL_TO="${MOLTBOOK_ALERT_EMAIL:-}"

SCRIPT_START=$(date +%s)
log "=========================================="
log "WEEKLY SCRAPE — $DATE"
log "=========================================="

# ─── DB Backup ───────────────────────────────────────────────────────────────
log "Backing up database..."
BACKUP_FILE="$BACKUP_DIR/moltbook-weekly-${DATE}.db"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

# ─── Stages ──────────────────────────────────────────────────────────────────
ERRORS=0
STAGES_RUN=0

run_stage() {
    local name="$1"; shift
    STAGES_RUN=$((STAGES_RUN + 1))
    if ! stage_timer "$name" "$@"; then
        ERRORS=$((ERRORS + 1))
        log "ERROR: Stage '$name' failed — continuing with remaining stages"
        send_email "[MOLTBOOK] WEEKLY FAILURE: $name" \
            "Stage '$name' failed during weekly scrape on $DATE.\nSee log: $LOG_FILE"
    fi
}

run_stage "incremental"  "$PYTHON" -u -m src.cli incremental --db "$DB_PATH" --log-file "$LOG_DIR/scrape-incremental.log"
run_stage "submolts"     "$PYTHON" -u -m src.cli submolts    --db "$DB_PATH" --log-file "$LOG_DIR/scrape-submolts.log"
run_stage "comments"     "$PYTHON" -u -m src.cli comments    --db "$DB_PATH" --only-missing --skip-empty --log-file "$LOG_DIR/scrape-comments.log"
run_stage "moderators"   "$PYTHON" -u -m src.cli moderators  --db "$DB_PATH" --log-file "$LOG_DIR/scrape-moderators.log"
run_stage "enrich"       "$PYTHON" -u -m src.cli enrich      --db "$DB_PATH" --only-missing --log-file "$LOG_DIR/scrape-enrich.log"
run_stage "snapshots"    "$PYTHON" -m src.cli snapshots       --db "$DB_PATH"

# ─── DB Stats ────────────────────────────────────────────────────────────────
DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
DISK_FREE=$(df -h "$SCRAPER_DIR" --output=avail | tail -1 | tr -d ' ')
log "DB size: $DB_SIZE | Disk free: $DISK_FREE"

# ─── Prune old backups (keep last N weekly) ──────────────────────────────────
log "Pruning old weekly backups (keeping last $KEEP_WEEKLY_BACKUPS)..."
ls -1t "$BACKUP_DIR"/moltbook-weekly-*.db 2>/dev/null | tail -n +$((KEEP_WEEKLY_BACKUPS + 1)) | while read -r old; do
    log "  Removing: $(basename "$old")"
    rm -f "$old"
done

# ─── Disk check ──────────────────────────────────────────────────────────────
check_disk

# ─── Summary ─────────────────────────────────────────────────────────────────
SCRIPT_END=$(date +%s)
TOTAL_TIME=$(( SCRIPT_END - SCRIPT_START ))

if [[ "$ERRORS" -eq 0 ]]; then
    STATUS="SUCCESS"
else
    STATUS="PARTIAL FAILURE ($ERRORS/$STAGES_RUN stages failed)"
fi

SUMMARY="$STATUS: Weekly scrape completed in ${TOTAL_TIME}s ($STAGES_RUN stages, $ERRORS errors)
DB size: $DB_SIZE | Disk free: $DISK_FREE | Backup: $BACKUP_SIZE"

log "$SUMMARY"
log "=========================================="

send_email "[MOLTBOOK] Weekly $DATE — $STATUS" "$SUMMARY

Log: $LOG_FILE
Host: $(hostname)"
