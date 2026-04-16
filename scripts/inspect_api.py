"""Inspect raw API payloads to find true field names."""
import json
import os
import sys
from src.client import MoltbookClient

c = MoltbookClient(os.environ["MOLTBOOK_API_KEY"])

print("=== SUBMOLT (page 1, first 2) ===")
data = c._get("/submolts", params={"page": 1}) if hasattr(c, "_get") else None
# fallback to public methods
if data is None:
    import requests
    r = c.session.get(f"{c.BASE_URL}/submolts", params={"page": 1},
                      headers={"Authorization": f"Bearer {c.api_key}"})
    data = r.json()
print("TOP-LEVEL KEYS:", list(data.keys()) if isinstance(data, dict) else type(data))
items = data
if isinstance(data, dict):
    for k in ("data", "submolts", "items", "results"):
        if k in data and isinstance(data[k], list):
            items = data[k]; break
for sm in items[:2]:
    print("KEYS:", sorted(sm.keys()))
    print(json.dumps(sm, indent=2)[:1200])
    print("---")

print("\n=== AGENT profile sample ===")
# pick an agent id from a submolt creator
agent_id = items[0].get("created_by", {}).get("id") if items else None
if agent_id:
    r = c.session.get(f"{c.BASE_URL}/agents/{agent_id}",
                      headers={"Authorization": f"Bearer {c.api_key}"})
    a = r.json()
    a = a.get("data", a) if isinstance(a, dict) else a
    print("KEYS:", sorted(a.keys()))
    print(json.dumps(a, indent=2)[:1500])
