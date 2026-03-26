### Python

- Type hints used throughout
- Streaming/pagination with callbacks for large datasets
- Retry logic with exponential backoff for 429s and 5xx (no proactive throttle)
- UPSERT pattern with COALESCE for incremental updates
- Validation against platform stats API (`/api/v1/stats` returns `totalAgents`, `totalPosts`, `totalComments`, `totalSubmolts`)