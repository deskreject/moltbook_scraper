"""Backfill `agents.claimed_by` for agents missed by session-18 migration.

Resumable: on each iteration re-queries agents where `is_claimed=1 AND claimed_by IS NULL`,
so restart after interruption is idempotent. Meant to run in tmux on the VM.

    tmux new -s backfill
    cd ~/moltbook_scraper
    .venv/bin/python -u scripts/backfill_claimed_by.py --db data/raw/moltbook.db \
        --log-file logs/backfill-claimed-by.log
    # detach: Ctrl-B then D.  reattach: tmux attach -t backfill

Expected runtime: ~48h at 60 req/min for ~174k agents. See session 19 log (2026-04-14).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.client import MoltbookClient  # noqa: E402
from src.database import Database  # noqa: E402


def _configure_logging(log_file: str | None) -> logging.Logger:
    logger = logging.getLogger("backfill_claimed_by")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def _targets(db: Database) -> list[str]:
    cur = db.conn.execute(
        "SELECT name FROM agents WHERE is_claimed = 1 AND claimed_by IS NULL"
    )
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/raw/moltbook.db")
    p.add_argument("--log-file", default=None)
    p.add_argument("--limit", type=int, default=0, help="Stop after N agents (0 = no limit)")
    args = p.parse_args()

    log = _configure_logging(args.log_file)
    load_dotenv()
    api_key = os.environ.get("MOLTBOOK_API_KEY")
    if not api_key:
        sys.exit("MOLTBOOK_API_KEY not set")

    db = Database(args.db)
    client = MoltbookClient(api_key)

    pending = _targets(db)
    total_start = len(pending)
    log.info(f"Backfill starting: {total_start} agents need claimed_by")
    if not pending:
        return

    success = 0
    not_found = 0
    errors = 0
    started = time.time()

    for i, name in enumerate(pending, 1):
        if args.limit and success >= args.limit:
            log.info(f"Reached --limit {args.limit}; stopping")
            break
        try:
            profile = client.fetch_agent_profile(name)
        except Exception as e:
            errors += 1
            log.warning(f"[{i}/{total_start}] {name}: fetch error: {e}")
            continue

        if profile is None:
            not_found += 1
            # Agent may be deleted; mark as such to avoid re-fetching next run.
            db.conn.execute(
                "UPDATE agents SET deleted_at = COALESCE(deleted_at, ?) WHERE name = ?",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), name),
            )
            db.conn.commit()
            continue

        # Upsert via existing path so COALESCE semantics apply consistently.
        db.upsert_agent(profile)
        db.conn.commit()
        success += 1

        if i % 500 == 0:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed else 0
            remaining = (total_start - i) / rate if rate else 0
            log.info(
                f"Progress {i}/{total_start}: ok={success} 404={not_found} err={errors} "
                f"rate={rate*60:.1f}/min eta={remaining/3600:.1f}h"
            )

    log.info(f"Done. ok={success} 404={not_found} err={errors}")
    db.close()


if __name__ == "__main__":
    main()
