"""Probe all submolts to confirm `is_nsfw` / `is_private` flag distribution.

Paginated via `/submolts?page=N` until exhausted. Counts raw API values and
compares to DB. Writes a small CSV under `tables/` for citability.
See session 19 log (2026-04-14).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.client import MoltbookClient  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=None, help="CSV output path (default: tables/submolt_flag_probe_YYYY-MM-DD.csv)")
    args = p.parse_args()

    load_dotenv()
    api_key = os.environ.get("MOLTBOOK_API_KEY")
    if not api_key:
        sys.exit("MOLTBOOK_API_KEY not set")

    c = MoltbookClient(api_key)
    nsfw_true = nsfw_false = nsfw_missing = 0
    priv_true = priv_false = priv_missing = 0
    total = 0
    page = 1
    while True:
        r = c.session.get(
            f"{c.BASE_URL}/submolts",
            params={"page": page},
            headers={"Authorization": f"Bearer {c.api_key}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("submolts") or data.get("data") or []
        if not items:
            break
        for sm in items:
            total += 1
            v = sm.get("is_nsfw")
            if v is True: nsfw_true += 1
            elif v is False: nsfw_false += 1
            else: nsfw_missing += 1
            v = sm.get("is_private")
            if v is True: priv_true += 1
            elif v is False: priv_false += 1
            else: priv_missing += 1
        page += 1
        time.sleep(1)  # courtesy pause; API cap is 60/min

    out = args.out or f"tables/submolt_flag_probe_{time.strftime('%Y-%m-%d')}.csv"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["flag", "true", "false", "missing", "total"])
        w.writerow(["is_nsfw", nsfw_true, nsfw_false, nsfw_missing, total])
        w.writerow(["is_private", priv_true, priv_false, priv_missing, total])

    print(f"Scanned {total} submolts")
    print(f"is_nsfw:    true={nsfw_true}  false={nsfw_false}  missing={nsfw_missing}")
    print(f"is_private: true={priv_true}  false={priv_false}  missing={priv_missing}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
