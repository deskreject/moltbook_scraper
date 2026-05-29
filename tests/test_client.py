"""Tests for MoltbookClient API wrapper."""

import time
from unittest.mock import patch
import responses
import pytest
import src.client as client_mod
from src.client import MoltbookClient, RateLimitError


class TestMoltbookClientFetchSubmolts:
    """Tests for fetching submolts."""

    @responses.activate
    def test_fetch_submolts_returns_list_of_submolts(self):
        """Client should return list of submolt dicts from API."""
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/submolts",
            json={
                "success": True,
                "submolts": [
                    {
                        "id": "abc123",
                        "name": "general",
                        "display_name": "General",
                        "description": "The town square",
                        "subscriber_count": 100,
                        "created_at": "2026-01-27T18:01:09.076047+00:00",
                    }
                ],
                "count": 1,
            },
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        submolts = client.fetch_submolts()

        assert len(submolts) == 1
        assert submolts[0]["name"] == "general"
        assert submolts[0]["subscriber_count"] == 100


class TestMoltbookClientFetchPosts:
    """Tests for fetching posts."""

    @responses.activate
    def test_fetch_posts_returns_list_of_posts(self):
        """Client should return posts from the API."""
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/posts",
            json={
                "success": True,
                "posts": [
                    {
                        "id": "post123",
                        "title": "Test post",
                        "content": "Hello world",
                        "upvotes": 10,
                        "downvotes": 1,
                        "comment_count": 5,
                        "created_at": "2026-01-30T05:39:05.821605+00:00",
                        "author": {"id": "author1", "name": "testbot"},
                        "submolt": {"id": "sub1", "name": "general"},
                    }
                ],
                "count": 1,
                "has_more": False,
                "next_offset": 25,
            },
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        posts = client.fetch_posts()

        assert len(posts) == 1
        assert posts[0]["title"] == "Test post"
        assert posts[0]["author"]["name"] == "testbot"

    @responses.activate
    def test_fetch_all_posts_paginates_until_no_more(self):
        """Client should paginate through all posts when has_more is True."""
        # First page
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/posts",
            json={
                "success": True,
                "posts": [{"id": "post1", "title": "First"}],
                "has_more": True,
                "next_offset": 25,
            },
            status=200,
        )
        # Second page
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/posts",
            json={
                "success": True,
                "posts": [{"id": "post2", "title": "Second"}],
                "has_more": False,
                "next_offset": 50,
            },
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        posts = client.fetch_all_posts()

        assert len(posts) == 2
        assert posts[0]["title"] == "First"
        assert posts[1]["title"] == "Second"


class TestMoltbookClientFetchAgentProfile:
    """Tests for fetching agent profiles."""

    @responses.activate
    def test_fetch_agent_profile_returns_agent_with_owner(self):
        """Client should return agent profile including owner Twitter info."""
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/agents/profile",
            json={
                "success": True,
                "agent": {
                    "id": "agent123",
                    "name": "Clawd",
                    "description": "Personal assistant",
                    "karma": 42,
                    "is_claimed": True,
                    "follower_count": 10,
                    "following_count": 5,
                    "owner": {
                        "x_handle": "testuser",
                        "x_name": "Test User",
                    },
                },
                "recentPosts": [],
            },
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        agent = client.fetch_agent_profile("Clawd")

        assert agent["name"] == "Clawd"
        assert agent["karma"] == 42
        assert agent["owner"]["x_handle"] == "testuser"

    @responses.activate
    def test_fetch_agent_profile_returns_none_when_not_found(self):
        """Client should return None when agent not found."""
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/agents/profile",
            json={
                "success": False,
                "error": "Bot not found",
            },
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        agent = client.fetch_agent_profile("nonexistent")

        assert agent is None


class TestMoltbookClientRateLimiting:
    """Tests for rate limiting behavior."""

    @responses.activate
    def test_retries_on_429_with_backoff(self):
        """Client should retry with exponential backoff on 429."""
        # First request returns 429
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/submolts",
            json={"error": "Rate limited"},
            status=429,
        )
        # Second request succeeds
        responses.add(
            responses.GET,
            "https://www.moltbook.com/api/v1/submolts",
            json={"success": True, "submolts": [{"name": "test"}]},
            status=200,
        )

        client = MoltbookClient(api_key="test_key")
        submolts = client.fetch_submolts()

        assert len(submolts) == 1
        assert len(responses.calls) == 2  # Two requests made

    @responses.activate
    def test_gives_up_after_max_retries(self):
        """Client should give up after max retries on persistent 429."""
        # All requests return 429
        for _ in range(5):
            responses.add(
                responses.GET,
                "https://www.moltbook.com/api/v1/submolts",
                json={"error": "Rate limited"},
                status=429,
            )

        client = MoltbookClient(api_key="test_key", max_retries=3)

        with pytest.raises(Exception) as exc_info:
            client.fetch_submolts()

        assert "429" in str(exc_info.value) or "rate" in str(exc_info.value).lower()

    def test_tracks_request_count(self):
        """Client should track number of requests made."""
        client = MoltbookClient(api_key="test_key")
        assert client.request_count == 0


class TestFetchCommentsOnlyRateLimit:
    """T6 — regression guard for the May-5 false-deletion root cause.

    `fetch_comments_only` currently catches *all* exceptions and returns [],
    so a persistent 429 is indistinguishable from "this post has no comments".
    In a `--detect-deletions` run that empty list causes every existing comment
    on the post to be tombstoned (the May 5 monthly incident — sessions 26/29).

    Contract pinned here: under a 429 storm the method must *raise*
    RateLimitError, not silently return []. Marked xfail until the Phase 1
    safeguard lands (re-raise RateLimitError in fetch_comments_only); remove the
    marker then so this becomes the standing regression guard.
    """

    @responses.activate
    @pytest.mark.xfail(
        reason="fetch_comments_only still swallows RateLimitError -> []; "
               "fix is Phase 1 step 5 (re-raise). Remove this marker once fixed.",
        strict=False,
    )
    def test_raises_ratelimit_error_instead_of_returning_empty(self):
        post_id = "post-under-ratelimit"
        url = f"https://www.moltbook.com/api/v1/posts/{post_id}/comments"
        # Persistent 429 across every retry attempt (more than max_retries+1).
        for _ in range(5):
            responses.add(responses.GET, url, json={"error": "Rate limited"}, status=429)

        client = MoltbookClient(api_key="test_key", max_retries=2, base_delay=0)

        with pytest.raises(RateLimitError):
            client.fetch_comments_only(post_id)


class TestBackoffDelay:
    """Fail-state coverage for Retry-After-aware 429 backoff (added 2026-05-29).

    Motivated by the API rate-limit regime change (tiered limiter + CloudFront);
    see readme_api_limit.md top block + CLAUDE/session_logs/2026_05_29_session_log.md §2.
    `_backoff_delay` is a pure function, so the fail-states are tested without sleeping.
    """

    def _client(self, base_delay=1.0, max_retries=3):
        return MoltbookClient(api_key="k", base_delay=base_delay, max_retries=max_retries)

    def test_honors_integer_retry_after(self):
        # attempt 0 -> exp=1; Retry-After=5 is longer, so it is honored.
        assert self._client()._backoff_delay(0, "5") == 5.0

    def test_retry_after_never_below_exponential(self):
        # attempt 3 -> exp=8; Retry-After=2 is shorter, so exp wins.
        assert self._client()._backoff_delay(3, "2") == 8.0

    def test_large_retry_after_is_capped(self):
        # Fail-state 1: a huge (e.g. infra-cooldown) Retry-After must not stall a
        # stage for many minutes — capped so retries exhaust and the error surfaces.
        assert self._client()._backoff_delay(0, "9999") == MoltbookClient.MAX_BACKOFF_SECONDS

    def test_malformed_retry_after_falls_back(self):
        # Fail-state 2: HTTP-date form or garbage must not raise; fall back to exp.
        c = self._client()
        assert c._backoff_delay(0, "Wed, 21 Oct 2026 07:28:00 GMT") == 1.0
        assert c._backoff_delay(0, "soon") == 1.0

    def test_nonpositive_retry_after_falls_back(self):
        c = self._client()
        assert c._backoff_delay(1, "0") == 2.0    # exp at attempt 1 = 2
        assert c._backoff_delay(1, "-5") == 2.0

    def test_absent_retry_after_is_exponential(self):
        # Fail-state 3 (regression): no header => unchanged exponential backoff.
        assert self._client()._backoff_delay(2, None) == 4.0  # exp at attempt 2 = 4

    @responses.activate
    def test_429_with_retry_after_honored_end_to_end(self):
        # Drive _request directly (not fetch_submolts) so exactly the two mocked
        # responses are consumed — a paginating caller would loop forever because
        # `responses` repeats the last registered response.
        url = "https://www.moltbook.com/api/v1/posts"
        responses.add(responses.GET, url, json={"error": "rl"}, status=429,
                      headers={"Retry-After": "3"})
        responses.add(responses.GET, url, json={"success": True}, status=200)
        client = MoltbookClient(api_key="k", max_retries=3, base_delay=1.0)
        with patch.object(client_mod.time, "sleep") as mock_sleep:
            resp = client._request("GET", url)
        assert resp.status_code == 200
        # The single retry slept the honored Retry-After (3s), not attempt-0 exp (1s).
        assert mock_sleep.call_args_list[0].args[0] == 3.0
