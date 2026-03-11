"""One-off sanity check for comment completeness and agent counts."""
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/moltbook.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# === COMMENT COMPLETENESS ===
print("=== COMMENT COMPLETENESS CHECK ===")
result = c.execute("""
    SELECT
        p.id,
        p.comment_count as platform_count,
        COUNT(cm.id) as our_count
    FROM posts p
    INNER JOIN comments cm ON cm.post_id = p.id
    GROUP BY p.id
    HAVING our_count > 0
    ORDER BY platform_count DESC
    LIMIT 20
""").fetchall()

print(f"{'post_id':<40} {'platform':>10} {'ours':>10} {'ratio':>10}")
for r in result:
    ratio = r[2] / r[1] if r[1] > 0 else 999
    print(f"{r[0]:<40} {r[1]:>10} {r[2]:>10} {ratio:>10.1%}")

stats = c.execute("""
    SELECT
        COUNT(*) as posts,
        SUM(p.comment_count) as platform_total,
        SUM(cnt) as our_total
    FROM posts p
    INNER JOIN (SELECT post_id, COUNT(*) as cnt FROM comments GROUP BY post_id) cm
        ON cm.post_id = p.id
""").fetchone()
print(f"\nOverall: {stats[0]:,} posts with comments")
print(f"Platform says: {stats[1]:,} comments for those posts")
print(f"We stored:     {stats[2]:,} comments")
print(f"Coverage:      {stats[2]/stats[1]:.1%}")

# Undershoot distribution
undershoot = c.execute("""
    SELECT
        CASE
            WHEN our_count >= platform_count THEN 'complete_or_over'
            WHEN our_count >= platform_count * 0.8 THEN '80-99%'
            WHEN our_count >= platform_count * 0.5 THEN '50-79%'
            ELSE 'under_50%'
        END as bucket,
        COUNT(*) as posts
    FROM (
        SELECT p.id, p.comment_count as platform_count, COUNT(cm.id) as our_count
        FROM posts p
        INNER JOIN comments cm ON cm.post_id = p.id
        GROUP BY p.id
    )
    GROUP BY bucket
    ORDER BY bucket
""").fetchall()
print("\nCompleteness distribution:")
for bucket, count in undershoot:
    print(f"  {bucket}: {count:,} posts")

# === AGENT COUNTS ===
print("\n=== AGENT COUNT ANALYSIS ===")
agents_total = c.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
print(f"Agents in our DB: {agents_total:,}")
print(f"Platform total:   2,855,581")
print(f"Our coverage:     {agents_total/2855581:.1%}")

unique_post_authors = c.execute(
    "SELECT COUNT(DISTINCT author_name) FROM posts WHERE author_name IS NOT NULL"
).fetchone()[0]
unique_comment_authors = c.execute(
    "SELECT COUNT(DISTINCT author_name) FROM comments WHERE author_name IS NOT NULL"
).fetchone()[0]
print(f"\nUnique post authors in posts table:    {unique_post_authors:,}")
print(f"Unique comment authors in comments:     {unique_comment_authors:,}")

# How many agents are ONLY known from comments (not from posts)?
comment_only = c.execute("""
    SELECT COUNT(DISTINCT cm.author_name)
    FROM comments cm
    WHERE cm.author_name IS NOT NULL
    AND cm.author_name NOT IN (SELECT DISTINCT author_name FROM posts WHERE author_name IS NOT NULL)
""").fetchone()[0]
print(f"Authors who commented but never posted: {comment_only:,}")

# Agent stub vs enriched
has_description = c.execute(
    "SELECT COUNT(*) FROM agents WHERE description IS NOT NULL AND description != ''"
).fetchone()[0]
print(f"\nAgents with description (enriched):    {has_description:,}")
print(f"Agents without description (stubs):     {agents_total - has_description:,}")

# Why more agents than posts?
total_posts = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
print(f"\n=== WHY MORE AGENTS THAN POSTERS? ===")
print(f"Total posts:          {total_posts:,}")
print(f"Unique post authors:  {unique_post_authors:,}")
print(f"Total agents in DB:   {agents_total:,}")
print(f"Difference:           {agents_total - unique_post_authors:,} agents never posted")
print("These extra agents come from: comment authors, moderators, embedded author objects")

# Enrich time estimate
print(f"\n=== ENRICH ESTIMATE ===")
stubs = agents_total - has_description
print(f"Agents needing enrichment: {stubs:,}")
print(f"At 25 req/min (sequential): {stubs/25/60:.1f} hours = {stubs/25/60/24:.1f} days")
print(f"At 136 req/min (VM speed):  {stubs/136/60:.1f} hours = {stubs/136/60/24:.1f} days")

conn.close()
