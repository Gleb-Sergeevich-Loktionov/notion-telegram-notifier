"""Tests for notion/projects.py.

Covers:
- Cache hit (in-memory TTL fresh) → returns title without fetch
- Cache miss → retrieve_page + upsert + return title
- DB cached but TTL expired → re-fetches from Notion
- retrieve_page raises → returns None (no propagation)
- Empty title from API → returns None
- resolve_first with empty tuple → None
- resolve_first calls resolve on first element
"""

import time
import pytest
import pytest_asyncio

from notify_bot.storage import db as db_mod
from notify_bot.notion import projects as proj_mod


# ── helpers ───────────────────────────────────────────────


def _make_page_response(title_text: str) -> dict:
    return {
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title_text}],
            }
        }
    }


class FakeClient:
    def __init__(self, pages: dict | None = None, raises=None):
        self._pages = pages or {}
        self._raises = raises
        self.calls: list[str] = []

    async def retrieve_page(self, page_id: str) -> dict:
        self.calls.append(page_id)
        if self._raises is not None:
            raise self._raises
        return self._pages.get(page_id, {})


@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


# ── tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_miss_fetches_and_caches(conn):
    """Cache miss: retrieve_page is called, result stored in DB."""
    # Clear in-memory TTL guard for test isolation
    proj_mod._fetched_at.clear()

    client = FakeClient(pages={"page-1": _make_page_response("My Project")})

    result = await proj_mod.resolve("page-1", conn, client, cache_ttl=3600)

    assert result == "My Project"
    assert client.calls == ["page-1"]

    # DB should now have the title cached
    from notify_bot.storage import repo_projects
    row = await repo_projects.get(conn, "page-1")
    assert row is not None
    assert row["title"] == "My Project"


@pytest.mark.asyncio
async def test_resolve_cache_hit_no_fetch(conn):
    """Cache hit (in-memory TTL fresh): no retrieve_page call."""
    proj_mod._fetched_at.clear()

    # Pre-populate DB and in-memory TTL
    from notify_bot.storage import repo_projects
    await repo_projects.upsert(conn, "page-2", "Cached Project")
    await conn.commit()
    proj_mod._fetched_at["page-2"] = time.monotonic()

    client = FakeClient()

    result = await proj_mod.resolve("page-2", conn, client, cache_ttl=3600)

    assert result == "Cached Project"
    assert client.calls == []  # no fetch


@pytest.mark.asyncio
async def test_resolve_ttl_expired_refetches(conn):
    """TTL expired: even if DB row exists, re-fetches from Notion."""
    proj_mod._fetched_at.clear()

    from notify_bot.storage import repo_projects
    await repo_projects.upsert(conn, "page-3", "Old Title")
    await conn.commit()
    # Mark as fetched far in the past (expired)
    proj_mod._fetched_at["page-3"] = time.monotonic() - 99999

    client = FakeClient(pages={"page-3": _make_page_response("New Title")})

    result = await proj_mod.resolve("page-3", conn, client, cache_ttl=3600)

    assert result == "New Title"
    assert client.calls == ["page-3"]


@pytest.mark.asyncio
async def test_resolve_retrieve_failure_returns_none(conn):
    """retrieve_page raises → resolve returns None, no propagation."""
    proj_mod._fetched_at.clear()

    client = FakeClient(raises=RuntimeError("network error"))

    result = await proj_mod.resolve("page-err", conn, client, cache_ttl=3600)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_empty_title_returns_none(conn):
    """API returns page with no title property → None returned."""
    proj_mod._fetched_at.clear()

    client = FakeClient(pages={"page-notitle": {}})

    result = await proj_mod.resolve("page-notitle", conn, client, cache_ttl=3600)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_first_empty_tuple_returns_none(conn):
    """resolve_first with empty tuple → None immediately."""
    proj_mod._fetched_at.clear()
    client = FakeClient()

    result = await proj_mod.resolve_first((), conn, client, cache_ttl=3600)
    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_resolve_first_uses_first_id(conn):
    """resolve_first resolves first element of tuple only."""
    proj_mod._fetched_at.clear()

    client = FakeClient(pages={
        "first": _make_page_response("First Project"),
        "second": _make_page_response("Second Project"),
    })

    result = await proj_mod.resolve_first(("first", "second"), conn, client, cache_ttl=3600)

    assert result == "First Project"
    assert client.calls == ["first"]  # only first resolved
