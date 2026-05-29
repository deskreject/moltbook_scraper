"""Moltbook API client."""

import threading
import time
from typing import Optional, Callable

import requests


class _TokenBucket:
    """Thread-safe token bucket for rate-limiting concurrent workers.

    Each call to acquire() blocks until a token is available. Workers share
    one bucket so total request rate stays at or below the configured limit.
    """

    def __init__(self, rate_per_min: float, capacity: float):
        self._rate = rate_per_min / 60.0  # tokens per second
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


class RateLimitError(Exception):
    """Raised when rate limit is exceeded and retries are exhausted."""
    pass


def _normalize_agent(agent: dict) -> dict:
    """Normalize agent dict from API responses to use consistent snake_case keys.

    Embedded author objects in posts/comments use camelCase (avatarUrl,
    followerCount, etc.) while the profile endpoint uses snake_case.
    This normalizes both to snake_case for consistent database storage.
    """
    key_map = {
        "avatarUrl": "avatar_url",
        "followerCount": "follower_count",
        "followingCount": "following_count",
        "isClaimed": "is_claimed",
        "isActive": "is_active",
        "createdAt": "created_at",
        "lastActive": "last_active",
        "displayName": "display_name",
        "postsCount": "posts_count",
        "commentsCount": "comments_count",
        "isVerified": "is_verified",
        "claimedBy": "claimed_by",
    }
    normalized = {}
    for k, v in agent.items():
        normalized[key_map.get(k, k)] = v
    return normalized


class MoltbookClient:
    """Client for interacting with the Moltbook API."""

    BASE_URL = "https://www.moltbook.com/api/v1"

    # Cap on how long a single 429 backoff will sleep. App-layer cooldowns are
    # short (<=60s); this bounds a pathological/large Retry-After (e.g. an
    # infra-layer cooldown) so one 429 cannot stall a stage for many minutes —
    # retries exhaust and RateLimitError surfaces instead.
    # [session 2026_05_29: rate-limit regime change — see readme_api_limit.md top
    #  block + CLAUDE/session_logs/2026_05_29_session_log.md §2 for why.]
    MAX_BACKOFF_SECONDS = 120.0

    def __init__(
        self,
        api_key: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        on_request: Optional[Callable[[str], None]] = None,
        rate_limit: Optional[float] = None,
    ):
        """
        Args:
            rate_limit: Optional requests-per-minute cap shared across all workers.
                        Set to ~90 when using concurrent workers to prevent thundering
                        herd 429s. None (default) disables proactive throttling.
        """
        self.api_key = api_key
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.on_request = on_request
        self.request_count = 0
        self._throttle = (
            _TokenBucket(rate_limit, capacity=1.0)
            if rate_limit else None
        )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request with retry logic for rate limiting and server errors."""
        # Set default timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = 30

        for attempt in range(self.max_retries + 1):
            # Acquire a token before EVERY attempt (including retries) so that
            # retries also count against the rate limit. Placing acquire() outside
            # the loop (previous behaviour) caused retries to bypass the bucket,
            # multiplying actual HTTP requests by up to (1 + max_retries) = 6x.
            if self._throttle:
                self._throttle.acquire()

            self.request_count += 1
            if self.on_request:
                self.on_request(url)

            try:
                response = self.session.request(method, url, **kwargs)
            except requests.exceptions.Timeout as e:
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                raise

            # Retry on rate limit (429)
            if response.status_code == 429:
                if attempt < self.max_retries:
                    # [session 2026_05_29] The API rate-limit regime changed
                    # (tiered limiter + CloudFront). On an app-layer 429 the
                    # server signals a precise cooldown via Retry-After; honor it
                    # (bounded) instead of a blind exponential sleep. Infra-layer
                    # (CloudFront) 429s carry no Retry-After -> fall back to
                    # exponential. See readme_api_limit.md / 2026_05_29 log §2.
                    delay = self._backoff_delay(attempt, response.headers.get("Retry-After"))
                    time.sleep(delay)
                    continue
                else:
                    raise RateLimitError(
                        f"Rate limited after {self.max_retries} retries (429)"
                    )

            # Retry on server errors (5xx)
            if response.status_code >= 500:
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                # On final attempt, return the response so raise_for_status can handle it
                return response

            return response

        # Should not reach here
        raise RateLimitError("Max retries exceeded")

    def _backoff_delay(self, attempt: int, retry_after: Optional[str]) -> float:
        """Seconds to sleep before retrying a 429.

        Honors the server's ``Retry-After`` (integer seconds) when present and
        sane — never shorter than exponential backoff, never longer than
        ``MAX_BACKOFF_SECONDS``. Falls back to pure exponential backoff when the
        header is absent or unparseable (infra-layer 429s, or the HTTP-date form
        of Retry-After, which we deliberately do not parse). Pure function of its
        inputs so it is unit-testable without sleeping.

        [session 2026_05_29: added for the rate-limit regime change — see
        readme_api_limit.md top block + 2026_05_29 session log §2.]
        """
        exp = self.base_delay * (2 ** attempt)
        if retry_after is not None:
            try:
                ra = float(retry_after)
                if ra > 0:
                    return min(max(ra, exp), self.MAX_BACKOFF_SECONDS)
            except (TypeError, ValueError):
                pass  # HTTP-date or garbage -> fall back to exponential
        return min(exp, self.MAX_BACKOFF_SECONDS)

    def fetch_submolts(
        self,
        on_page: Optional[Callable[[int, int], None]] = None,
    ) -> list[dict]:
        """Fetch all submolts using page-based pagination.

        Args:
            on_page: Optional callback called with (page_num, submolts_so_far)
        """
        all_submolts = []
        page = 1
        while True:
            params = {"page": page}
            response = self._request("GET", f"{self.BASE_URL}/submolts", params=params)
            response.raise_for_status()
            data = response.json()
            submolts = data.get("submolts", [])
            if not submolts:
                break
            all_submolts.extend(submolts)
            if on_page:
                on_page(page, len(all_submolts))
            page += 1
        return all_submolts

    def fetch_submolts_streaming(
        self,
        on_page: Callable[[int, list[dict]], None],
        target_count: int = 0,
        max_stale_pages: int = 20,
    ) -> int:
        """Fetch all submolts using page-based pagination, calling on_page with each batch.

        Args:
            on_page: Callback called with (page_num, submolts_list) for each page.
            target_count: Ignored (kept for caller compatibility).
            max_stale_pages: Ignored (kept for caller compatibility).

        Returns:
            Total number of submolts fetched.
        """
        total = 0
        page = 1
        consecutive_errors = 0
        max_consecutive_errors = 10

        while True:
            params = {"page": page}
            try:
                response = self._request("GET", f"{self.BASE_URL}/submolts", params=params)
                response.raise_for_status()
                data = response.json()
                submolts = data.get("submolts", [])
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break
                time.sleep(self.base_delay * consecutive_errors)
                continue

            if not submolts:
                break

            on_page(page, submolts)
            total += len(submolts)
            page += 1

        return total

    def fetch_posts(self, limit: int = 100, cursor: Optional[str] = None, sort: str = "new") -> dict:
        """Fetch a page of posts from the API using cursor-based pagination.

        Args:
            sort: Sort order. "new" (chronological, full archive) or "hot" (score+recency,
                  only returns recent high-engagement posts — caps at ~70K empirically).
                  Default is "new" to ensure full corpus coverage.

        Returns:
            Dict with keys: posts, has_more, next_cursor
        """
        params = {"limit": limit, "sort": sort}
        if cursor:
            params["cursor"] = cursor
        response = self._request("GET", f"{self.BASE_URL}/posts", params=params)
        response.raise_for_status()
        data = response.json()
        return {
            "posts": data.get("posts", []),
            "has_more": data.get("has_more", False),
            "next_cursor": data.get("next_cursor"),
        }

    def fetch_all_posts(
        self,
        on_page: Optional[Callable[[int, int], None]] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch all posts using cursor-based pagination.

        Args:
            on_page: Optional callback called with (page_num, posts_so_far)
            limit: Number of posts per page (default 100)
        """
        all_posts = []
        cursor = None
        page = 0
        while True:
            result = self.fetch_posts(limit=limit, cursor=cursor)
            posts = result["posts"]
            if not posts:
                break
            all_posts.extend(posts)
            page += 1
            if on_page:
                on_page(page, len(all_posts))
            if not result["has_more"]:
                break
            cursor = result["next_cursor"]
            if not cursor:
                break
        return all_posts

    def fetch_posts_streaming(
        self,
        on_page: Callable[[int, list[dict]], None],
        target_count: int = 0,
        max_stale_pages: int = 20,
        sort: str = "new",
    ) -> int:
        """Fetch all posts using cursor-based pagination, calling on_page with each batch.

        Args:
            on_page: Callback called with (page_num, posts_list) for each page.
            target_count: Ignored (kept for caller compatibility).
            max_stale_pages: Ignored (kept for caller compatibility).
            sort: Sort order passed to fetch_posts (default "new" for full archive).

        Returns:
            Total number of posts fetched.
        """
        total_posts = 0
        cursor = None
        page = 0
        consecutive_errors = 0
        max_consecutive_errors = 10

        while True:
            try:
                result = self.fetch_posts(limit=100, cursor=cursor, sort=sort)
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break
                time.sleep(self.base_delay * consecutive_errors)
                continue

            posts = result["posts"]
            if not posts:
                break

            page += 1
            on_page(page, posts)
            total_posts += len(posts)

            if not result["has_more"]:
                break
            cursor = result["next_cursor"]
            if not cursor:
                break

        return total_posts

    def fetch_agent_profile(self, name: str) -> Optional[dict]:
        """Fetch an agent's profile by name. Returns None if not found."""
        response = self._request(
            "GET",
            f"{self.BASE_URL}/agents/profile",
            params={"name": name}
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            return None
        return data["agent"]

    def fetch_platform_stats(self, max_retries: int = 10) -> dict:
        """Fetch platform-wide statistics from moltbook.

        Retries until all key values are non-zero (API is flaky).

        Args:
            max_retries: Maximum retries to get non-zero values.

        Returns:
            Dict with keys: agents, submolts, posts, comments
        """
        for attempt in range(max_retries):
            response = self._request("GET", f"{self.BASE_URL}/stats")
            response.raise_for_status()
            data = response.json()
            stats = {
                "agents": data.get("totalAgents", 0),
                "submolts": data.get("totalSubmolts", 0),
                "posts": data.get("totalPosts", 0),
                "comments": data.get("totalComments", 0),
            }
            # Check if all values are non-zero
            if all(v > 0 for v in stats.values()):
                return stats
            # Wait before retry
            if attempt < max_retries - 1:
                time.sleep(self.base_delay * (attempt + 1))

        # Return best effort if we couldn't get all non-zero
        return stats

    def fetch_submolt_detail(self, name: str) -> Optional[dict]:
        """Fetch a submolt's full details by name. Returns None if not found."""
        response = self._request(
            "GET",
            f"{self.BASE_URL}/submolts/{name}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            return None
        return data["submolt"]

    def fetch_submolt_moderators(self, submolt_name: str) -> list[dict]:
        """Fetch moderators for a submolt. Returns empty list if not found or error."""
        try:
            response = self._request(
                "GET",
                f"{self.BASE_URL}/submolts/{submolt_name}/moderators"
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            return data.get("moderators", [])
        except Exception:
            return []

    def fetch_comments_only(self, post_id: str) -> list[dict]:
        """Fetch comments for a post from the /posts/{id}/comments endpoint.

        Does NOT re-fetch the post itself (use when the post is already in the DB).
        Halves API requests vs fetch_post_with_comments() for the comments stage.
        Requests limit=500 (server hard cap) to maximise comment coverage per request.

        Args:
            post_id: ID of the post to fetch comments for.

        Returns:
            List of comment dicts, or empty list if not found or on error.
        """
        try:
            response = self._request(
                "GET",
                f"{self.BASE_URL}/posts/{post_id}/comments",
                params={"limit": 500},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            return data.get("comments", [])
        except Exception:
            return []

    def fetch_post_with_comments(self, post_id: str) -> Optional[dict]:
        """Fetch a post with its comments. Returns None if not found.

        Comments are fetched from the separate /posts/{id}/comments endpoint.
        """
        # Fetch post
        response = self._request(
            "GET",
            f"{self.BASE_URL}/posts/{post_id}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            return None

        # Fetch comments from separate endpoint
        comments = []
        try:
            comments_response = self._request(
                "GET",
                f"{self.BASE_URL}/posts/{post_id}/comments"
            )
            if comments_response.status_code == 200:
                comments_data = comments_response.json()
                comments = comments_data.get("comments", [])
        except Exception:
            pass  # Return post with empty comments if comments fetch fails

        return {
            "post": data.get("post"),
            "comments": comments,
        }
