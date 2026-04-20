"""Dry-run one full create_snapshots() call on a DB copy.

Measures first-run insert counts and byte cost. Does NOT touch live DB.
Usage: py scripts/dryrun_snapshots.py --db data/raw/moltbook_phase3a_test.db
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    from src.database import Database
    from src.scraper import Scraper

    before_size = os.path.getsize(args.db)
    print(f"DB size before: {before_size / 1e9:.2f} GB")

    db = Database(args.db)
    # No client needed — create_snapshots is DB-only.
    class _FakeClient:
        pass
    scraper = Scraper(_FakeClient(), db, on_progress=print, max_workers=1)

    run_id = db.start_scrape_run()
    print(f"\nStarting create_snapshots(scrape_run_id={run_id}) ...")
    t0 = time.time()
    scraper.create_snapshots(scrape_run_id=run_id)
    elapsed = time.time() - t0
    db.complete_scrape_run(run_id, 0, 0, 0, 0, 'completed')
    db.conn.commit()

    print(f"\nElapsed: {elapsed:.1f}s")

    print("\nFirst-run table row counts:")
    for tbl in ("post_metrics", "post_events", "agent_metrics",
                "agent_events", "submolt_metrics", "moderator_events"):
        c = db.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl:20s} = {c:>10,}")

    print("\nAnchor-set row counts (expect: all posts/agents/submolts):")
    for tbl, anchor_col in (("posts", "hot_score_first"),
                             ("agents", "is_claimed_first"),
                             ("submolts", "subscriber_count_first")):
        c = db.conn.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE {anchor_col} IS NOT NULL"
        ).fetchone()[0]
        total = db.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}.{anchor_col:30s} = {c:>10,} / {total:,}")

    db.close()

    after_size = os.path.getsize(args.db)
    print(f"\nDB size after:  {after_size / 1e9:.2f} GB "
          f"(delta: {(after_size - before_size) / 1e6:+.1f} MB)")


if __name__ == "__main__":
    main()
