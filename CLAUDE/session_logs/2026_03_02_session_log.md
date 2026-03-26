# Session 5 — 2026-03-02 — sort=new Fix & Posts Scrape Restart

**What was done:**
- Diagnosed posts scrape exiting at 69,974: `sort=hot` is algorithmically capped at ~70K posts (~3 days of high-engagement)
- Added `sort` parameter (default `"new"`) to `fetch_posts()` and `fetch_posts_streaming()`
- Re-launched posts scrape with `sort=new` (219K posts at session end, walking back to Jan 15 platform launch)
- Assessed HPC strategy: outbound HTTPS from compute nodes is the blocker; Hetzner/DO VM recommended

**Key decisions:**
- `sort=new` required for full archive traversal
- Platform launched ~Jan 15 2026
- DB portable via rsync; UPSERT design supports cross-machine workflow
