"""Check whether new schema fields (session 18) are populated with real data.

Checks fields added in session 18 migration:
- agents.claimed_by
- submolts.creator_id, post_count, is_nsfw, is_private

For each field, reports: total rows, non-null count, distinct values,
and a small sample, so we can tell real data from NULL-only or static fills.
"""
import sqlite3
import sys
from pathlib import Path

DB = sys.argv[1] if len(sys.argv) > 1 else "data/raw/moltbook.db"

CHECKS = [
    ("agents", "claimed_by"),
    ("submolts", "creator_id"),
    ("submolts", "post_count"),
    ("submolts", "is_nsfw"),
    ("submolts", "is_private"),
]


def check(conn: sqlite3.Connection, table: str, col: str) -> None:
    cur = conn.cursor()
    total = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    non_null = cur.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL"
    ).fetchone()[0]
    distinct = cur.execute(
        f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE {col} IS NOT NULL"
    ).fetchone()[0]
    top = cur.execute(
        f"SELECT {col}, COUNT(*) c FROM {table} WHERE {col} IS NOT NULL "
        f"GROUP BY {col} ORDER BY c DESC LIMIT 5"
    ).fetchall()

    pct = (non_null / total * 100) if total else 0
    status = (
        "EMPTY" if non_null == 0
        else "STATIC" if distinct == 1
        else "OK"
    )
    print(f"\n[{status}] {table}.{col}")
    print(f"  rows: {total:,}  non-null: {non_null:,} ({pct:.1f}%)  distinct: {distinct:,}")
    print(f"  top values: {top}")


def main() -> None:
    path = Path(DB)
    if not path.exists():
        sys.exit(f"DB not found: {path}")
    print(f"Checking {path}  ({path.stat().st_size / 1e9:.2f} GB)")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        for table, col in CHECKS:
            check(conn, table, col)


if __name__ == "__main__":
    main()
