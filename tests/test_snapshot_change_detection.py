"""Regression tests for Phase 3a change-driven snapshot writer.

Covers the six write paths documented in `claude_methodology_log.md` plus two
follow-ups added in session 21:
    1. no_change_emits_nothing                      — idempotence on unchanged data
    2. numeric_change_inserts_one_metric            — post_metrics on vote change
    3. boolean_flip_inserts_one_event               — post_events on is_pinned flip
    4. anchor_set_once                              — *_first columns are write-once
    5. deleted_post_content_preserved_when_flag_set — is_deleted=1 tombstone guard
    6. post_metrics_respects_4_week_cutoff          — age cutoff (src/scraper.py:_POST_AGE_CUTOFF_DAYS)
    7. tombstone_content_preserved_without_flag     — P2 finding: API returns
       content='[deleted]' with is_deleted:false. Guard must be content-heuristic
       AND auto-infer is_deleted=1 on both posts and comments.
    8. moderator_turnover_emits_events              — added / removed / role_changed path

The scraper writer is exercised directly via a FakeClient (no network).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.database import Database
from src.scraper import Scraper


class _FakeClient:
    """No-op stand-in; create_snapshots does not hit the network."""
    pass


@pytest.fixture
def db():
    """Fresh DB per test, with full schema + Migration 10 applied."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "phase3a.db")
        d = Database(db_path)
        yield d
        d.close()


@pytest.fixture
def scraper(db):
    return Scraper(_FakeClient(), db, on_progress=None, max_workers=1)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_post(post_id="p1", *, created_at=None, upvotes=10, downvotes=1,
               comment_count=0, is_pinned=False, is_locked=False,
               is_deleted=False, is_spam=False,
               verification_status="unverified", hot_score=1.0, score=9,
               content="hello world", title="t"):
    """Minimal post dict matching upsert_post's expected shape."""
    return {
        "id": post_id,
        "title": title,
        "content": content,
        "url": None,
        "author": {"name": "author1"},
        "submolt": {"name": "sub1"},
        "upvotes": upvotes,
        "downvotes": downvotes,
        "comment_count": comment_count,
        "is_pinned": is_pinned,
        "created_at": _iso(created_at or datetime.utcnow()),
        "type": "text",
        "is_locked": is_locked,
        "is_deleted": is_deleted,
        "is_spam": is_spam,
        "verification_status": verification_status,
        "updated_at": _iso(datetime.utcnow()),
        "score": score,
        "hot_score": hot_score,
    }


def _make_comment(cid="c1", post_id="p1", *, content="a reply",
                  upvotes=0, downvotes=0, is_deleted=False,
                  created_at=None):
    return {
        "id": cid,
        "post_id": post_id,
        "parent_id": None,
        "content": content,
        "author": {"name": "author1"},
        "upvotes": upvotes,
        "downvotes": downvotes,
        "created_at": _iso(created_at or datetime.utcnow()),
        "is_spam": False,
        "depth": 0,
        "reply_count": 0,
        "verification_status": "unverified",
        "updated_at": _iso(datetime.utcnow()),
        "score": upvotes - downvotes,
        "is_deleted": is_deleted,
    }


def _snapshot_counts(db):
    """Return row counts for every narrow snapshot table."""
    tables = ("post_metrics", "post_events", "agent_metrics", "agent_events",
              "submolt_metrics", "moderator_events")
    return {
        t: db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in tables
    }


# ---------------------------------------------------------------------------
# Test 1: no-change emits nothing (idempotence)
# ---------------------------------------------------------------------------

def test_no_change_emits_nothing(db, scraper):
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_post(_make_post())
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")
    first = _snapshot_counts(db)

    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")
    second = _snapshot_counts(db)

    # Second run must insert zero rows anywhere — the whole point of
    # change-driven snapshots is that idle data pays zero storage.
    for t in first:
        assert second[t] == first[t], (
            f"{t}: second run inserted {second[t] - first[t]} rows on "
            f"unchanged data (expected 0)"
        )


# ---------------------------------------------------------------------------
# Test 2: numeric change inserts exactly one metric row
# ---------------------------------------------------------------------------

def test_numeric_change_inserts_one_metric(db, scraper):
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_post(_make_post(upvotes=10))
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")
    metrics_before = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'p1'"
    ).fetchone()[0]

    db.upsert_post(_make_post(upvotes=11))  # only upvotes changed
    db.commit()

    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")

    metrics_after = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'p1'"
    ).fetchone()[0]
    assert metrics_after == metrics_before + 1

    latest = db.get_latest_post_metrics("p1")
    assert latest["upvotes"] == 11


# ---------------------------------------------------------------------------
# Test 3: boolean flip inserts exactly one event
# ---------------------------------------------------------------------------

def test_boolean_flip_inserts_one_event(db, scraper):
    """
    Per session 21 design (CLAUDE.md § Snapshot policy):
    'events are ONLY emitted for subsequent transitions. First observation
    is NOT an event.' Initial state is captured in is_pinned_first. A
    later flip must emit a row.

    If this test fails with 0 events, the writer is skipping transitions
    entirely (old_str-None branch short-circuits even when value moved
    away from the anchor). That would be a design regression worth
    surfacing before deploying Phase 3a.
    """
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_post(_make_post(is_pinned=False))
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")

    # Anchor captured initial state; no event yet.
    anchor = db.conn.execute(
        "SELECT is_pinned_first FROM posts WHERE id = 'p1'"
    ).fetchone()[0]
    assert anchor in (0, False)
    events_after_run1 = db.conn.execute(
        "SELECT COUNT(*) FROM post_events "
        "WHERE post_id = 'p1' AND event_type = 'is_pinned'"
    ).fetchone()[0]
    assert events_after_run1 == 0

    # Flip the bit in the live table and re-snapshot.
    db.upsert_post(_make_post(is_pinned=True))
    db.commit()
    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")

    events_after_flip = db.conn.execute(
        "SELECT COUNT(*) FROM post_events "
        "WHERE post_id = 'p1' AND event_type = 'is_pinned'"
    ).fetchone()[0]
    assert events_after_flip == 1, (
        "Expected exactly 1 is_pinned event after the first genuine flip "
        "post-anchor; got {}. See test docstring.".format(events_after_flip)
    )


# ---------------------------------------------------------------------------
# Test 4: anchor set once, never overwritten
# ---------------------------------------------------------------------------

def test_anchor_set_once(db, scraper):
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})
    db.upsert_post(_make_post(hot_score=3.14, is_pinned=False))
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")

    row = db.conn.execute(
        "SELECT hot_score_first, is_pinned_first FROM posts WHERE id = 'p1'"
    ).fetchone()
    assert row[0] == 3.14
    assert row[1] in (0, False)

    # Mutate the live values and run again.
    db.upsert_post(_make_post(hot_score=9.99, is_pinned=True))
    db.commit()
    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")

    row = db.conn.execute(
        "SELECT hot_score_first, is_pinned_first FROM posts WHERE id = 'p1'"
    ).fetchone()
    # Anchor columns must be write-once.
    assert row[0] == 3.14, "hot_score_first was overwritten"
    assert row[1] in (0, False), "is_pinned_first was overwritten"


# ---------------------------------------------------------------------------
# Test 5: deleted-post content preserved when is_deleted flag is already set
# ---------------------------------------------------------------------------

def test_deleted_post_content_preserved_when_flag_set(db):
    """Once is_deleted=1 on a stored post, later upserts never overwrite its
    content/title/url, regardless of what the API returns. This is the
    flag-based half of the deletion guard (src/database.py:532)."""
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})
    db.upsert_post(_make_post(content="original body", title="original title",
                               is_deleted=False))
    db.commit()

    # Mark it deleted (simulates `mark_posts_deleted` running on missing-id detection).
    db.conn.execute(
        "UPDATE posts SET is_deleted = 1, deleted_detected_at = ? WHERE id = 'p1'",
        (datetime.utcnow().isoformat(),),
    )
    db.commit()

    # API later returns the row with blanked content — guard must hold.
    db.upsert_post(_make_post(content="ANYTHING", title="ANYTHING",
                               is_deleted=False))
    db.commit()

    row = db.conn.execute(
        "SELECT content, title, is_deleted FROM posts WHERE id = 'p1'"
    ).fetchone()
    assert row[0] == "original body"
    assert row[1] == "original title"
    assert row[2] == 1  # is_deleted must stay 1


# ---------------------------------------------------------------------------
# Test 6: 4-week age cutoff on post_metrics
# ---------------------------------------------------------------------------

def test_post_metrics_respects_4_week_cutoff(db, scraper):
    """_POST_AGE_CUTOFF_DAYS gates the metrics panel. A post created >4 weeks
    ago should NOT get metrics rows even when its vote totals change, because
    the audit (2026-04-14) showed late-life change rate is 0.003 %.
    """
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})

    old_created = datetime.utcnow() - timedelta(days=60)
    fresh_created = datetime.utcnow() - timedelta(days=7)
    db.upsert_post(_make_post(post_id="old", created_at=old_created, upvotes=5))
    db.upsert_post(_make_post(post_id="fresh", created_at=fresh_created, upvotes=5))
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")

    old_rows = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'old'"
    ).fetchone()[0]
    fresh_rows = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'fresh'"
    ).fetchone()[0]
    assert old_rows == 0, "Post older than cutoff should not get a metrics row"
    assert fresh_rows == 1, "Fresh post should get its baseline metrics row"

    # Change both: only the fresh one should gain a row.
    db.upsert_post(_make_post(post_id="old", created_at=old_created, upvotes=99))
    db.upsert_post(_make_post(post_id="fresh", created_at=fresh_created, upvotes=99))
    db.commit()
    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")

    old_rows = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'old'"
    ).fetchone()[0]
    fresh_rows = db.conn.execute(
        "SELECT COUNT(*) FROM post_metrics WHERE post_id = 'fresh'"
    ).fetchone()[0]
    assert old_rows == 0, "Old post metrics must stay gated off by the 4-week cutoff"
    assert fresh_rows == 2, "Fresh post should have gained a second metrics row"


# ---------------------------------------------------------------------------
# Test 7: tombstone content preserved WITHOUT is_deleted flag (P2 finding)
# ---------------------------------------------------------------------------

def test_tombstone_content_preserved_without_flag(db):
    """Live-API probes P1 and P2 (2026-04-20) confirmed Moltbook returns
    deleted items with `content='[deleted]'` AND `is_deleted=false`. The
    flag-based guard alone would miss this — content would be clobbered
    and the entity would stay marked live. Guard must therefore combine:

      1. content-heuristic preservation on title/content/url
      2. auto-inference of is_deleted=1 when content='[deleted]'

    Applied to both posts (src/database.py:532-560) and comments
    (src/database.py:742-767).
    """
    db.upsert_submolt({"name": "sub1", "description": "d", "subscriber_count": 1})
    db.upsert_agent({"name": "author1", "karma": 5, "is_claimed": True,
                     "follower_count": 1, "following_count": 1})

    # --- Posts side ---
    db.upsert_post(_make_post(post_id="tomb", content="real body",
                               title="real title", is_deleted=False))
    db.commit()

    # API returns tombstone with is_deleted:false — the worst case.
    db.upsert_post(_make_post(post_id="tomb", content="[deleted]",
                               title="[deleted]", is_deleted=False))
    db.commit()

    row = db.conn.execute(
        "SELECT content, title, is_deleted FROM posts WHERE id = 'tomb'"
    ).fetchone()
    assert row[0] == "real body", "Post content clobbered by tombstone-on-response"
    assert row[1] == "real title", "Post title clobbered by tombstone-on-response"
    assert row[2] == 1, "Post is_deleted must be auto-inferred from '[deleted]' content"

    # --- Comments side ---
    db.upsert_comment(_make_comment(cid="ctomb", content="real reply",
                                     is_deleted=False), post_id="tomb")
    db.commit()

    db.upsert_comment(_make_comment(cid="ctomb", content="[deleted]",
                                     is_deleted=False), post_id="tomb")
    db.commit()

    crow = db.conn.execute(
        "SELECT content, is_deleted FROM comments WHERE id = 'ctomb'"
    ).fetchone()
    assert crow[0] == "real reply", "Comment content clobbered by tombstone-on-response"
    assert crow[1] == 1, "Comment is_deleted must be auto-inferred from '[deleted]'"


# ---------------------------------------------------------------------------
# Test 8: moderator turnover emits added / removed / role_changed
# ---------------------------------------------------------------------------

def test_moderator_turnover_emits_events(db, scraper):
    """The moderator writer is different from post/agent events — it emits on
    first observation (pairs active at observation start) and on every
    state transition thereafter. Covers all three event_types.
    """
    db.upsert_submolt({"name": "subA", "description": "d", "subscriber_count": 1})
    db.upsert_agent({"name": "modX", "karma": 0, "is_claimed": False,
                     "follower_count": 0, "following_count": 0})
    db.upsert_moderator("subA", "modX", role="mod")
    db.commit()

    run1 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run1)
    db.complete_scrape_run(run1, 0, 0, 0, 0, "completed")

    events = db.conn.execute(
        "SELECT event_type, role FROM moderator_events "
        "WHERE submolt_name = 'subA' AND agent_name = 'modX' "
        "ORDER BY scraped_at ASC"
    ).fetchall()
    assert len(events) == 1 and events[0]["event_type"] == "added"
    assert events[0]["role"] == "mod"

    # Change role -> role_changed.
    db.upsert_moderator("subA", "modX", role="admin")
    # upsert_moderator uses COALESCE which won't overwrite; force the update
    # to simulate an actual role change.
    db.conn.execute(
        "UPDATE moderators SET role = 'admin' WHERE submolt_name = 'subA' AND agent_name = 'modX'"
    )
    db.commit()
    run2 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run2)
    db.complete_scrape_run(run2, 0, 0, 0, 0, "completed")

    events = db.conn.execute(
        "SELECT event_type, role FROM moderator_events "
        "WHERE submolt_name = 'subA' AND agent_name = 'modX' "
        "ORDER BY scraped_at ASC"
    ).fetchall()
    assert len(events) == 2
    assert events[-1]["event_type"] == "role_changed"
    assert events[-1]["role"] == "admin"

    # Remove from live table -> removed.
    db.conn.execute(
        "DELETE FROM moderators WHERE submolt_name = 'subA' AND agent_name = 'modX'"
    )
    db.commit()
    run3 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run3)
    db.complete_scrape_run(run3, 0, 0, 0, 0, "completed")

    events = db.conn.execute(
        "SELECT event_type, role FROM moderator_events "
        "WHERE submolt_name = 'subA' AND agent_name = 'modX' "
        "ORDER BY scraped_at ASC"
    ).fetchall()
    assert len(events) == 3
    assert events[-1]["event_type"] == "removed"

    # Re-add -> new 'added' event (re-appointment after removal).
    db.upsert_moderator("subA", "modX", role="mod")
    db.commit()
    run4 = db.start_scrape_run()
    scraper.create_snapshots(scrape_run_id=run4)
    db.complete_scrape_run(run4, 0, 0, 0, 0, "completed")

    events = db.conn.execute(
        "SELECT event_type, role FROM moderator_events "
        "WHERE submolt_name = 'subA' AND agent_name = 'modX' "
        "ORDER BY scraped_at ASC"
    ).fetchall()
    assert len(events) == 4
    assert events[-1]["event_type"] == "added"
    assert events[-1]["role"] == "mod"
