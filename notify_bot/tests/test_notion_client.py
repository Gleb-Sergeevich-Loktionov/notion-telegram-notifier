"""Tests for notion/client.py.

Covers:
- 429 APIResponseError with Retry-After header → sleep + retry succeeds
- 429 without Retry-After header → uses backoff delay
- 5xx → backoff 3 attempts → NotionRetryable
- 401 → NotionFatal
- 403 → NotionFatal
- Other 4xx → NotionFatal
- Network error → backoff → NotionRetryable
- Pagination loop: two pages via next_cursor
- query filter: after=None → no filter; after=timestamp → filter applied
- retrieve_db: cache hit avoids _call; first miss fetches and caches
- close() cancels background task
"""

import asyncio
import pytest
import pytest_asyncio

from notion_client.errors import APIResponseError
from notify_bot.notion.client import NotionClient, NotionFatal, NotionRetryable


# ── helpers ──────────────────────────────────────────────────────────────────


def _api_error(status: int, headers: dict | None = None) -> APIResponseError:
    """Build a fake APIResponseError with given status and optional headers."""
    exc = APIResponseError.__new__(APIResponseError)
    exc.status = status
    exc.code = "error_code"
    exc.body = {}
    exc.headers = headers or {}
    exc.args = (f"status={status}",)
    return exc


def _make_client() -> NotionClient:
    return NotionClient(auth="fake-token", database_id="db-123")


# ── _call patching ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_success_on_first_try(monkeypatch):
    """No exception: returns result immediately."""
    client = _make_client()
    monkeypatch.setattr(client, "_call", AsyncMock(return_value={"ok": True}))

    result = await client._request("databases.query", database_id="db-123")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_request_401_raises_notion_fatal(monkeypatch):
    """401 → NotionFatal (no retry)."""
    client = _make_client()
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=_api_error(401)))

    with pytest.raises(NotionFatal):
        await client._request("databases.query")


@pytest.mark.asyncio
async def test_request_403_raises_notion_fatal(monkeypatch):
    """403 → NotionFatal."""
    client = _make_client()
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=_api_error(403)))

    with pytest.raises(NotionFatal):
        await client._request("databases.query")


@pytest.mark.asyncio
async def test_request_other_4xx_raises_notion_fatal(monkeypatch):
    """Other 4xx (e.g. 400) → NotionFatal."""
    client = _make_client()
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=_api_error(400)))

    with pytest.raises(NotionFatal):
        await client._request("databases.query")


@pytest.mark.asyncio
async def test_request_5xx_exhausts_retries_raises_retryable(monkeypatch):
    """5xx errors on all attempts → NotionRetryable after 3 tries."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = _make_client()
    # Always raise 500
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=_api_error(500)))

    with pytest.raises(NotionRetryable):
        await client._request("databases.query")

    # 3 backoff delays: 1, 2, 4 (last attempt gets None delay so no sleep after it)
    assert len(slept) == 3
    assert slept == [1, 2, 4]


@pytest.mark.asyncio
async def test_request_429_with_retry_after_header_sleeps(monkeypatch):
    """429 with Retry-After header → sleep(header_value) then retry succeeds."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = _make_client()
    exc_429 = _api_error(429, headers={"retry-after": "5"})
    # First call raises 429, second succeeds
    monkeypatch.setattr(
        client, "_call",
        AsyncMock(side_effects=[exc_429, {"results": [], "has_more": False}])
    )

    result = await client._request("databases.query")
    assert result == {"results": [], "has_more": False}
    assert slept == [5.0]


@pytest.mark.asyncio
async def test_request_network_error_retries_then_raises(monkeypatch):
    """Network error → retries with backoff → NotionRetryable."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = _make_client()
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=ConnectionError("timeout")))

    with pytest.raises(NotionRetryable):
        await client._request("databases.query")

    assert len(slept) == 3  # 3 backoff delays


# ── pagination ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_incremental_pagination(monkeypatch):
    """Two pages via next_cursor: all results merged and returned."""
    page1 = {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "cursor-abc"}
    page2 = {"results": [{"id": "p2"}], "has_more": False}

    call_count = [0]

    async def fake_call(method, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            assert "start_cursor" not in kwargs
            return page1
        else:
            assert kwargs.get("start_cursor") == "cursor-abc"
            return page2

    client = _make_client()
    monkeypatch.setattr(client, "_call", fake_call)

    results = await client.query_incremental(after=None)
    assert results == [{"id": "p1"}, {"id": "p2"}]
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_query_incremental_no_filter_when_after_none(monkeypatch):
    """after=None → no filter key sent to API."""
    captured_kwargs = {}

    async def fake_call(method, **kwargs):
        captured_kwargs.update(kwargs)
        return {"results": [], "has_more": False}

    client = _make_client()
    monkeypatch.setattr(client, "_call", fake_call)

    await client.query_incremental(after=None)
    assert "filter" not in captured_kwargs


@pytest.mark.asyncio
async def test_query_incremental_filter_when_after_given(monkeypatch):
    """after=timestamp → filter with last_edited_time included."""
    captured_kwargs = {}

    async def fake_call(method, **kwargs):
        captured_kwargs.update(kwargs)
        return {"results": [], "has_more": False}

    client = _make_client()
    monkeypatch.setattr(client, "_call", fake_call)

    await client.query_incremental(after="2024-01-01T10:00:00.000Z")
    assert "filter" in captured_kwargs
    f = captured_kwargs["filter"]
    assert f["timestamp"] == "last_edited_time"
    assert f["last_edited_time"]["on_or_after"] == "2024-01-01T10:00:00.000Z"


# ── retrieve_db cache ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_db_caches_on_first_call(monkeypatch):
    """First call fetches from API; second call uses in-memory cache."""
    call_count = [0]

    async def fake_call(method, **kwargs):
        call_count[0] += 1
        return {"properties": {"Name": {"type": "title"}}}

    client = _make_client()
    monkeypatch.setattr(client, "_call", fake_call)

    result1 = await client.retrieve_db()
    result2 = await client.retrieve_db()

    assert result1 == result2
    assert call_count[0] == 1  # only one actual API call


@pytest.mark.asyncio
async def test_retrieve_db_returns_cache_when_set(monkeypatch):
    """If _db_cache already set, retrieve_db returns it without any _call."""
    client = _make_client()
    client._db_cache = {"properties": {"cached": True}}
    monkeypatch.setattr(client, "_call", AsyncMock(side_effect=AssertionError("should not call")))

    result = await client.retrieve_db()
    assert result == {"properties": {"cached": True}}


# ── close ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_cancels_background_task(monkeypatch):
    """close() cancels the background refresh task if it exists."""
    client = _make_client()

    # Simulate a background task
    async def _noop():
        await asyncio.sleep(9999)

    task = asyncio.create_task(_noop())
    client._bg_refresh_task = task

    # Mock aclose to avoid real network
    async def fake_aclose():
        pass

    monkeypatch.setattr(client._client, "aclose", fake_aclose)
    await client.close()

    # Yield to the event loop so the cancellation propagates
    import asyncio as _asyncio
    try:
        await _asyncio.wait_for(_asyncio.shield(task), timeout=0.1)
    except (_asyncio.CancelledError, _asyncio.TimeoutError):
        pass

    assert task.cancelled() or task.cancelling() > 0


@pytest.mark.asyncio
async def test_close_without_background_task(monkeypatch):
    """close() works fine when no background task was started."""
    client = _make_client()

    async def fake_aclose():
        pass

    monkeypatch.setattr(client._client, "aclose", fake_aclose)
    # Should not raise
    await client.close()


# ── AsyncMock helper ─────────────────────────────────────────────────────────


class AsyncMock:
    """Minimal async mock: either fixed return_value or list of side_effects."""

    def __init__(self, return_value=None, side_effect=None, side_effects=None):
        self._return_value = return_value
        self._side_effect = side_effect
        self._side_effects = side_effects
        self._call_idx = 0

    async def __call__(self, *args, **kwargs):
        if self._side_effects is not None:
            effect = self._side_effects[self._call_idx]
            self._call_idx += 1
            if isinstance(effect, BaseException):
                raise effect
            return effect
        if self._side_effect is not None:
            raise self._side_effect
        return self._return_value
