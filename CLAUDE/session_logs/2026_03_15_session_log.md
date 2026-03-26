# Session 12 — 2026-03-13 to 03-16 — Catch-Up Scrape & VM Setup

**What was done:**
- 10-day catch-up scrape (Mar 3 → Mar 13) ran locally over ~26h, 0 errors across all 6 stages:
  - Posts incremental: +326,541 (~50 req/min, 39 min). DB now 2,068,988 posts
  - Submolts: 19,593 refreshed (~10 min)
  - Comments: +366,589 from 130,414 posts (~16h, ~130 posts/min). DB now 3,177,832
  - Moderators: 18,769 from 19,593 submolts (~7h, ~47/min)
  - Enrich: +4,005 agents (~2.5h). DB now 171,003
  - Snapshots: all tables (~2 min)
- Hetzner VM setup (Mar 16): pushed 9.9 GB DB + code, installed sqlite3 + msmtp + dos2unix
- Configured cron jobs, created SSH alias `vm`, fixed status.sh bugs

**Key findings:**
- Weekly scrape takes ~8-10h not ~1-2h (moderators ~7h is bottleneck at ~47/min for 19.6K submolts)
- Comments throughput ~130/min for lightweight posts (higher than session 9's ~25/min for heavy posts)
- `dos2unix` required after every `scp` from Windows (CRLF breaks bash scripts)
