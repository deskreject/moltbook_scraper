"""Watchdog for the VM scraper: runs alongside scraper in tmux.

Monitors:
1. Is the scraper process alive?
2. Is progress advancing?
3. Are there rate limit errors?
4. Periodic DB backup (every 6 hours)

Writes status to ~/moltbook_scraper/logs/watchdog.log
Can be checked via: ssh root@vm 'cat ~/moltbook_scraper/logs/watchdog.log | tail -20'
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(os.path.expanduser("~/moltbook_scraper/logs"))
DB_PATH = Path(os.path.expanduser("~/moltbook_scraper/data/raw/moltbook.db"))
SCRAPE_LOG = LOG_DIR / "scrape-stdout.log"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
BACKUP_DIR = Path(os.path.expanduser("~/moltbook_scraper/data/backups"))

CHECK_INTERVAL = 900  # 15 minutes
BACKUP_INTERVAL = 6 * 3600  # 6 hours


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_scraper_running() -> bool:
    """Check if the scraper process is alive."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "src.cli comments"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def get_progress() -> tuple:
    """Parse the scrape log for the latest progress line.
    Returns (done, total, comments, errors) or (None, None, None, None).
    """
    try:
        with open(SCRAPE_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in reversed(lines):
            m = re.search(
                r"Progress:\s+(\d+)/(\d+)\s+posts\s+\((\d+)\s+comments,\s+(\d+)\s+errors\)",
                line,
            )
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    except Exception:
        pass
    return None, None, None, None


def count_429s_in_log() -> int:
    """Count 429-related errors in the scrape log."""
    try:
        result = subprocess.run(
            ["grep", "-c", "429", str(SCRAPE_LOG)],
            capture_output=True, text=True
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except Exception:
        return 0


def get_db_comment_count() -> int:
    """Get total comment count from DB."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


def backup_db():
    """Create a timestamped backup of the database."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"moltbook_{ts}.db"
    try:
        # Use sqlite3 backup API for consistency (no partial writes)
        src_conn = sqlite3.connect(str(DB_PATH))
        dst_conn = sqlite3.connect(str(dest))
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        size_mb = dest.stat().st_size / 1024 / 1024
        log(f"BACKUP: {dest.name} ({size_mb:.0f} MB)")
        # Keep only last 3 backups to save disk
        backups = sorted(BACKUP_DIR.glob("moltbook_*.db"))
        while len(backups) > 3:
            oldest = backups.pop(0)
            oldest.unlink()
            log(f"BACKUP: removed old backup {oldest.name}")
    except Exception as e:
        log(f"BACKUP FAILED: {e}")


def main():
    log("Watchdog started")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    prev_done = None
    prev_time = None
    last_backup = 0
    stall_count = 0

    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.monotonic()

        # Check process
        alive = is_scraper_running()

        # Check progress
        done, total, comments, errors = get_progress()
        db_comments = get_db_comment_count()

        # Calculate rate
        rate_str = ""
        if done is not None and prev_done is not None and prev_time is not None:
            elapsed_min = (now - prev_time) / 60
            delta = done - prev_done
            if elapsed_min > 0:
                rate = delta / elapsed_min
                rate_str = f"rate={rate:.1f}/min"
                if delta == 0:
                    stall_count += 1
                else:
                    stall_count = 0

        # 429 count
        n429 = count_429s_in_log()

        # Build status line
        status = "RUNNING" if alive else "STOPPED"
        if not alive:
            status = "*** SCRAPER STOPPED ***"
        elif stall_count >= 3:
            status = "*** STALLED (no progress for 45+ min) ***"
        elif n429 > 10:
            status = f"WARNING: {n429} rate limit errors in log"

        if done is not None:
            remaining = total - done
            if rate_str and "rate=" in rate_str:
                rate_val = float(rate_str.split("=")[1].split("/")[0])
                if rate_val > 0:
                    eta_h = remaining / rate_val / 60
                    rate_str += f" ETA={eta_h:.1f}h"
            log(
                f"{status} | {done:,}/{total:,} posts | "
                f"{comments:,} comments (DB: {db_comments:,}) | "
                f"errors={errors} | 429s={n429} | {rate_str}"
            )
        else:
            log(f"{status} | no progress data yet | DB comments: {db_comments:,}")

        if done is not None:
            prev_done = done
            prev_time = now

        # Check if complete
        if done is not None and done >= total:
            log("COMPLETE: all posts processed")
            backup_db()
            break

        if not alive:
            log("Scraper process is not running. Will keep checking in case it restarts.")

        # Periodic backup
        if now - last_backup >= BACKUP_INTERVAL:
            backup_db()
            last_backup = now


if __name__ == "__main__":
    main()
