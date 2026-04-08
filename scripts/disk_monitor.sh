#!/usr/bin/env bash
# disk_monitor.sh — Standalone disk usage monitor with email alerts
# Cron: 0 8 * * *  (daily 08:00 UTC)
#
# Checks both root disk and data volume. Sends email if either exceeds 80%.
# Runs independently of scrape scripts so alerts fire even if scrapes are broken.

SCRAPER_DIR="$HOME/moltbook_scraper"
DATA_VOLUME="/mnt/HC_Volume_104999576"

cd "$SCRAPER_DIR" || exit 1
[[ -f .env ]] && set -a && source .env && set +a
EMAIL_TO="${MOLTBOOK_ALERT_EMAIL:-}"

if [[ -z "$EMAIL_TO" ]] || ! command -v msmtp &>/dev/null; then
    exit 0
fi

for path in "$SCRAPER_DIR" "$DATA_VOLUME"; do
    [[ -d "$path" ]] || continue
    label=$(df "$path" --output=target | tail -1 | tr -d ' ')
    usage=$(df "$path" --output=pcent | tail -1 | tr -d ' %')
    if [[ "$usage" -ge 80 ]]; then
        avail=$(df -h "$path" --output=avail | tail -1 | tr -d ' ')
        printf "Subject: [MOLTBOOK] DISK ALERT: %s at %s%%\nFrom: moltbook-scraper@hetzner\n\nDisk usage on %s %s is at %s%% (%s free).\n\nAction needed: prune backups, run VACUUM, or expand disk.\n\n%s" \
            "$label" "$usage" "$(hostname)" "$label" "$usage" "$avail" "$(df -h)" \
            | msmtp "$EMAIL_TO" 2>/dev/null || true
    fi
done
