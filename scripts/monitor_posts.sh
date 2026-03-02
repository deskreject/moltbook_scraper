#!/bin/bash
# Monitor script for posts scrape.
# Phase 1 (arg: 1): 6 checks at 5-min intervals → exits after 30 min
# Phase 2 (arg: 2): single check after 15-min sleep → exits (restart each time)

cd "C:/Users/Usuario/Research/moltbook_scraper"

MONITOR_LOG="logs/monitor.log"
SCRAPE_LOG="logs/scrape-posts.log"
DB="data/raw/moltbook.db"
PYTHON=".venv/Scripts/python.exe"

do_check() {
    local label="$1"
    {
        echo "─── $label | $(date '+%H:%M:%S') ───────────────────────────"
        echo "SCRAPE LOG (last 2 lines):"
        tail -2 "$SCRAPE_LOG" 2>/dev/null || echo "  (no log yet)"
        echo "DB:"
        "$PYTHON" -c "
import sqlite3
c = sqlite3.connect('$DB')
posts  = c.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
agents = c.execute('SELECT COUNT(*) FROM agents').fetchone()[0]
print(f'  Posts: {posts:,}  |  Agent stubs: {agents:,}')
" 2>/dev/null || echo "  (db read error)"
        echo ""
    } | tee -a "$MONITOR_LOG"
}

PHASE="${1:-1}"

if [ "$PHASE" = "1" ]; then
    echo "=== MONITOR PHASE 1 START: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$MONITOR_LOG"
    echo "" | tee -a "$MONITOR_LOG"
    for i in 1 2 3 4 5 6; do
        sleep 300
        do_check "t+$((i*5)) min  [check $i/6]"
    done
    echo "=== PHASE 1 COMPLETE (30 min elapsed) ===" | tee -a "$MONITOR_LOG"
    echo "" | tee -a "$MONITOR_LOG"

elif [ "$PHASE" = "2" ]; then
    sleep 900
    do_check "t+15 min interval [phase 2]"
fi
