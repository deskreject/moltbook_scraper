"""Pre-deployment verification for Phase 3a.

Runs verifications 1-4 and 7-8 from session 21 / handover Step A.
Does NOT modify the input DB unless --apply-migration is passed.

Usage:
    py scripts/verify_phase3a.py --db data/raw/moltbook_phase3a_test.db
    py scripts/verify_phase3a.py --db data/raw/moltbook_phase3a_test.db --apply-migration
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def blast_radius(conn: sqlite3.Connection) -> None:
    section("#1 BLAST RADIUS (first-run event inserts)")
    q = """
    SELECT
      (SELECT COUNT(*) FROM posts WHERE is_pinned=1)                   AS posts_pinned,
      (SELECT COUNT(*) FROM posts WHERE is_locked=1)                   AS posts_locked,
      (SELECT COUNT(*) FROM posts WHERE is_deleted=1)                  AS posts_deleted,
      (SELECT COUNT(*) FROM posts WHERE is_spam=1)                     AS posts_spam,
      (SELECT COUNT(*) FROM posts)                                     AS posts_total,
      (SELECT COUNT(*) FROM agents WHERE is_claimed=1)                 AS agents_claimed,
      (SELECT COUNT(*) FROM agents)                                    AS agents_total,
      (SELECT COUNT(*) FROM moderators)                                AS moderator_pairs
    """
    row = dict(zip([d[0] for d in conn.execute(q).description], conn.execute(q).fetchone()))
    for k, v in row.items():
        print(f"  {k:20s} = {v:>12,}")

    # verification_status — may have multiple values
    print("\n  verification_status distribution (posts):")
    for vs, c in conn.execute("SELECT verification_status, COUNT(*) FROM posts GROUP BY verification_status"):
        print(f"    {str(vs):20s} {c:>12,}")

    # Events emitted on first run = posts with non-None flag × (one per flag)
    # Policy: old_value is None (no prior event row), new_value is current → emit.
    # So every row with a flag set (or verification_status != default) is an insert.
    post_event_rows = (
        row["posts_pinned"] + row["posts_locked"] + row["posts_deleted"] + row["posts_spam"]
    )
    # verification_status: emit one per row that is NOT the "default" (usually NULL or 'unverified')
    vs_default_candidates = list(conn.execute(
        "SELECT verification_status, COUNT(*) FROM posts GROUP BY verification_status ORDER BY COUNT(*) DESC"
    ))
    # Assume the most-frequent is "default" for purposes of rough estimate
    if vs_default_candidates:
        default_vs, default_count = vs_default_candidates[0]
        vs_non_default = sum(c for v, c in vs_default_candidates if v != default_vs)
    else:
        vs_non_default = 0
    post_event_rows += vs_non_default
    agent_event_rows = row["agents_claimed"]
    moderator_event_rows = row["moderator_pairs"]

    print("\n  ESTIMATED first-run event rows (with current writer logic):")
    print(f"    post_events       ~ {post_event_rows:>12,}")
    print(f"    agent_events      ~ {agent_event_rows:>12,}")
    print(f"    moderator_events  ~ {moderator_event_rows:>12,}")
    total = post_event_rows + agent_event_rows + moderator_event_rows
    print(f"    TOTAL             ~ {total:>12,}")
    if total > 1000:
        print("\n  [ALERT] EXCEEDS Alert C (>1000/run). First snapshot will look like a broken writer.")
        print("          Fix: seed baseline on migration so only real transitions emit events.")


def created_at_nulls(conn: sqlite3.Connection) -> None:
    section("#2 NULL/empty created_at (breaks 4-week cutoff)")
    for tbl in ("posts", "comments", "agents", "submolts"):
        try:
            nulls = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE created_at IS NULL OR created_at=''"
            ).fetchone()[0]
            total = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            flag = "  [BLOCKING]" if (tbl == "posts" and nulls > 0) else ""
            print(f"  {tbl:10s}: {nulls:>8,} / {total:>10,} NULL/empty{flag}")
        except sqlite3.OperationalError as e:
            print(f"  {tbl}: {e}")


def apply_migration(db_path: str) -> None:
    section("#4 MIGRATION DRY-RUN (applies _migrate + _create_tables)")
    # Import project Database class to run the real migration
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.database import Database
    print(f"  Opening {db_path} with Database() — this triggers _migrate() and _create_tables()")
    db = Database(db_path)
    print("  [OK] Migration completed without error")
    # Report journal_mode (verification #7)
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  journal_mode = {mode!r}")
    if mode.lower() != "wal":
        print("  ⚠  journal_mode is not WAL — check Database.__init__ pragma ordering")
    db.close()


def schema_checks(conn: sqlite3.Connection) -> None:
    section("Post-migration schema verification")
    expected_tables = [
        "post_metrics", "post_events",
        "agent_metrics", "agent_events",
        "submolt_metrics", "submolt_events",
        "moderator_events",
    ]
    for t in expected_tables:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        print(f"  table {t:20s} {'present' if row else 'MISSING'}")

    expected_cols = {
        "posts": ["hot_score_first", "hot_score_first_observed_at", "score_first"],
        "agents": ["description_first", "karma_first", "follower_count_first", "following_count_first"],
        "submolts": ["description_first", "subscriber_count_first"],
    }
    for tbl, cols in expected_cols.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        for c in cols:
            print(f"  {tbl}.{c:40s} {'present' if c in existing else 'MISSING'}")


def index_plans(conn: sqlite3.Connection) -> None:
    section("#3 EXPLAIN QUERY PLAN — confirm composite indexes used")
    # These queries mirror get_latest_*_metrics / get_latest_*_event
    queries = [
        ("post_metrics latest-by-post",
         "SELECT * FROM post_metrics WHERE post_id='x' ORDER BY scraped_at DESC LIMIT 1"),
        ("post_events latest-per-field",
         "SELECT * FROM post_events WHERE post_id='x' AND event_type='is_pinned' ORDER BY scraped_at DESC LIMIT 1"),
        ("agent_metrics latest-by-agent",
         "SELECT * FROM agent_metrics WHERE agent_name='x' ORDER BY scraped_at DESC LIMIT 1"),
        ("agent_events latest-per-field",
         "SELECT * FROM agent_events WHERE agent_name='x' AND event_type='is_claimed' ORDER BY scraped_at DESC LIMIT 1"),
        ("submolt_metrics latest-by-submolt",
         "SELECT * FROM submolt_metrics WHERE submolt_name='x' ORDER BY scraped_at DESC LIMIT 1"),
        ("moderator_events latest-per-pair",
         "SELECT * FROM moderator_events WHERE submolt_name='x' AND agent_name='y' ORDER BY scraped_at DESC LIMIT 1"),
    ]
    for label, q in queries:
        print(f"\n  {label}")
        for row in conn.execute(f"EXPLAIN QUERY PLAN {q}"):
            print(f"    {row[-1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply-migration", action="store_true",
                    help="Apply Phase 3a migration to the DB (use only on a COPY).")
    args = ap.parse_args()

    db_path = args.db
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    try:
        blast_radius(conn)
        created_at_nulls(conn)
    finally:
        conn.close()

    if args.apply_migration:
        apply_migration(db_path)
        conn = sqlite3.connect(db_path)
        try:
            schema_checks(conn)
            index_plans(conn)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
