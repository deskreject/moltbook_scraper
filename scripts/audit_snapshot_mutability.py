"""Audit how often snapshot columns actually change across existing snapshots.

Gates the Phase 4 compression decision: columns that change rarely (<5%) on
mature entities can be stored as first+latest anchors on the live table
instead of replicated in every weekly snapshot.

For each snapshot table, for each entity, walks the chronological snapshot
sequence and counts columns that differ between consecutive snapshots.
Reports per-column change rate (share of consecutive-pair observations where
value flipped). Writes:
  - CSV: tables/snapshot_mutability_audit_YYYY-MM-DD.csv
  - DB:  snapshot_mutability_evidence (permanent, citable in paper)

Read-only on snapshot tables. See session 19 log (2026-04-14).
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import time
from pathlib import Path

SNAPSHOT_TABLES = {
    "agent_snapshots": {
        "entity_col": "agent_name",
        "cols": ["description", "karma", "is_claimed", "follower_count",
                 "following_count", "avatar_url", "owner_json", "metadata_json"],
    },
    "post_snapshots": {
        "entity_col": "post_id",
        "cols": ["title", "content", "url", "author_name", "submolt_name",
                 "upvotes", "downvotes", "comment_count", "is_pinned"],
    },
    "comment_snapshots": {
        "entity_col": "comment_id",
        "cols": ["post_id", "parent_id", "content", "author_name",
                 "upvotes", "downvotes"],
    },
    "submolt_snapshots": {
        "entity_col": "submolt_name",
        "cols": ["display_name", "description", "subscriber_count",
                 "avatar_url", "banner_url", "created_by_name", "last_activity_at"],
    },
}


def _ensure_evidence_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshot_mutability_evidence (
            audited_at TEXT DEFAULT CURRENT_TIMESTAMP,
            table_name TEXT,
            column_name TEXT,
            entities_with_ge2_snapshots INTEGER,
            consecutive_pairs INTEGER,
            pairs_changed INTEGER,
            change_rate REAL,
            PRIMARY KEY (audited_at, table_name, column_name)
        )
    """)
    conn.commit()


def audit_table(conn: sqlite3.Connection, table: str, entity_col: str,
                cols: list[str]) -> list[dict]:
    # Stream ordered snapshots; compare each row to the prior row for same entity.
    select_cols = ", ".join(cols)
    q = (
        f"SELECT {entity_col}, scraped_at, {select_cols} "
        f"FROM {table} ORDER BY {entity_col}, scraped_at"
    )
    prev_entity = None
    prev_vals: tuple | None = None
    entities_with_multi: set = set()
    pairs_total = 0
    pairs_changed = [0] * len(cols)

    for row in conn.execute(q):
        entity = row[0]
        vals = row[2:]
        if entity == prev_entity and prev_vals is not None:
            entities_with_multi.add(entity)
            pairs_total += 1
            for i, (a, b) in enumerate(zip(prev_vals, vals)):
                if a != b:
                    pairs_changed[i] += 1
        prev_entity = entity
        prev_vals = vals

    n_entities = len(entities_with_multi)
    rows = []
    for i, col in enumerate(cols):
        rate = pairs_changed[i] / pairs_total if pairs_total else 0.0
        rows.append({
            "table_name": table,
            "column_name": col,
            "entities_with_ge2_snapshots": n_entities,
            "consecutive_pairs": pairs_total,
            "pairs_changed": pairs_changed[i],
            "change_rate": rate,
        })
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/raw/moltbook.db")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    _ensure_evidence_table(conn)

    out = args.out or f"tables/snapshot_mutability_audit_{time.strftime('%Y-%m-%d')}.csv"
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    for table, spec in SNAPSHOT_TABLES.items():
        t0 = time.time()
        print(f"Auditing {table} ...", flush=True)
        rows = audit_table(conn, table, spec["entity_col"], spec["cols"])
        all_rows.extend(rows)
        for r in rows:
            print(f"  {r['column_name']:20s} "
                  f"pairs={r['consecutive_pairs']:>8d}  "
                  f"changed={r['pairs_changed']:>8d}  "
                  f"rate={r['change_rate']:.4f}", flush=True)
        print(f"  ({table} done in {time.time()-t0:.0f}s)", flush=True)

    fields = ["table_name", "column_name", "entities_with_ge2_snapshots",
              "consecutive_pairs", "pairs_changed", "change_rate"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    conn.executemany(
        "INSERT OR REPLACE INTO snapshot_mutability_evidence "
        "(table_name, column_name, entities_with_ge2_snapshots, "
        " consecutive_pairs, pairs_changed, change_rate) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(r["table_name"], r["column_name"], r["entities_with_ge2_snapshots"],
          r["consecutive_pairs"], r["pairs_changed"], r["change_rate"])
         for r in all_rows],
    )
    conn.commit()
    conn.close()
    print(f"Wrote {out} and populated snapshot_mutability_evidence.")


if __name__ == "__main__":
    main()
