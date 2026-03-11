"""Sustained rate test: run sequential scraper for 10 minutes, log rate and errors."""
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.client import MoltbookClient
from src.database import Database

DURATION_MINUTES = 10

api_key = os.getenv("MOLTBOOK_API_KEY")
client = MoltbookClient(api_key=api_key, max_retries=5, base_delay=2.0)
db = Database("data/raw/moltbook.db")

# Get a batch of post IDs to test with (skip ones already done)
post_ids = db.get_post_ids_without_comments_with_activity()[:5000]
print(f"Testing with {len(post_ids)} post IDs for {DURATION_MINUTES} minutes")
print(f"Start: {datetime.now().strftime('%H:%M:%S')}")

start = time.monotonic()
deadline = start + DURATION_MINUTES * 60
requests_made = 0
errors_429 = 0
errors_other = 0
comments_fetched = 0
last_report = start
report_interval = 60  # report every minute

for post_id in post_ids:
    if time.monotonic() > deadline:
        break
    try:
        comments = client.fetch_comments_only(post_id)
        requests_made += 1
        comments_fetched += len(comments) if comments else 0
    except Exception as e:
        requests_made += 1
        if "429" in str(e) or "Rate" in str(e):
            errors_429 += 1
        else:
            errors_other += 1

    now = time.monotonic()
    if now - last_report >= report_interval:
        elapsed_min = (now - start) / 60
        rate = requests_made / elapsed_min
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"{elapsed_min:.1f}min | "
            f"{requests_made} reqs ({rate:.1f}/min) | "
            f"429s: {errors_429} | "
            f"other errors: {errors_other} | "
            f"comments: {comments_fetched}",
            flush=True,
        )
        last_report = now

elapsed_min = (time.monotonic() - start) / 60
rate = requests_made / elapsed_min if elapsed_min > 0 else 0
print(f"\n=== FINAL ===")
print(f"Duration: {elapsed_min:.1f} minutes")
print(f"Requests: {requests_made}")
print(f"Rate: {rate:.1f} req/min")
print(f"429 errors: {errors_429}")
print(f"Other errors: {errors_other}")
print(f"Comments fetched: {comments_fetched}")
print(f"Effective rate (excluding 429 retries): {(requests_made - errors_429) / elapsed_min:.1f} successful/min")

if errors_429 > 0:
    print(f"\nWARNING: Got {errors_429} rate limit errors.")
    print(f"Consider adding --rate-limit {int(rate * 0.8)} to stay under the limit.")
else:
    print(f"\nNo rate limit errors. Sequential rate of {rate:.1f}/min appears sustainable.")

db.close()
