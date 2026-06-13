"""Notion API client wrapper.

Enforces:
- API version 2022-06-28 (CR-2, locked)
- Retry logic: 429 honors Retry-After; 5xx/network backoff 1/2/4s x3 → NotionRetryable
- 401/403 → NotionFatal
- retrieve_db() schema cache refreshed hourly in background
"""

import asyncio
import logging
import time
from typing import Any

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

log = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"  # CR-2: locked


class NotionRetryable(Exception):
    """Raised after exhausting retries on 429/5xx/network errors."""


class NotionFatal(Exception):
    """Raised on auth failures (401/403) — no retry."""


class NotionClient:
    def __init__(
        self,
        auth: str,
        database_id: str,
        *,
        notion_version: str = NOTION_VERSION,
        base_url: str | None = None,
    ):
        client_kwargs: dict[str, Any] = {"auth": auth, "notion_version": notion_version}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = AsyncClient(**client_kwargs)
        self._database_id = database_id
        self._db_cache: dict | None = None
        self._db_cache_at: float = 0.0
        self._cache_ttl: float = 3600.0  # 1 hour

    async def query_incremental(self, after: str | None) -> list:
        """Query all pages modified at or after `after` (None = full scan).

        Returns list of raw page dicts, sorted by last_edited_time ascending.
        """
        filters: dict | None = None
        if after:
            filters = {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": after},
            }
        sorts = [{"timestamp": "last_edited_time", "direction": "ascending"}]

        pages = []
        cursor = None
        while True:
            params: dict[str, Any] = {
                "database_id": self._database_id,
                "sorts": sorts,
                "page_size": 100,
            }
            if filters:
                params["filter"] = filters
            if cursor:
                params["start_cursor"] = cursor

            resp = await self._request("databases.query", **params)
            pages.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        return pages

    async def retrieve_db(self) -> dict:
        """Return cached DB schema (options for assignee/reporter properties).

        Reads from in-memory cache only — no Notion call on cache hit.
        Background refresh happens every hour via start_background_refresh().
        """
        if self._db_cache is not None:
            return self._db_cache
        await self._refresh_db_cache()
        return self._db_cache or {}

    async def retrieve_page(self, page_id: str) -> dict:
        """Retrieve a single page by ID."""
        return await self._request("pages.retrieve", page_id=page_id)

    async def start_background_refresh(self) -> None:
        """Launch hourly background refresh of the DB schema cache."""
        self._bg_refresh_task = asyncio.create_task(self._bg_refresh_loop())

    async def _bg_refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cache_ttl)
            try:
                await self._refresh_db_cache()
            except Exception as exc:
                log.warning("notion: bg schema refresh failed: %s", exc)

    async def _refresh_db_cache(self) -> None:
        resp = await self._request("databases.retrieve", database_id=self._database_id)
        self._db_cache = resp
        self._db_cache_at = time.monotonic()
        log.info("notion: db schema cache refreshed")

    async def _request(self, method: str, **kwargs: Any) -> dict:
        """Execute a Notion API call with retry logic."""
        backoff_delays = [1, 2, 4]
        last_exc: Exception | None = None

        for attempt, delay in enumerate(backoff_delays + [None]):  # type: ignore[list-item]
            try:
                return await self._call(method, **kwargs)
            except APIResponseError as exc:
                status = exc.status
                if status in (401, 403):
                    raise NotionFatal(f"Notion auth error {status}: {exc}") from exc
                if status == 429:
                    retry_after = _parse_retry_after(exc) or delay or 4
                    log.warning("notion: rate-limited, sleeping %ss", retry_after)
                    await asyncio.sleep(retry_after)
                    last_exc = exc
                    continue
                if status is not None and 500 <= status < 600:
                    log.warning("notion: server error %s attempt=%s", status, attempt)
                    last_exc = exc
                    if delay is not None:
                        await asyncio.sleep(delay)
                    continue
                # Other API errors (4xx not 401/403/429) — not retryable
                raise NotionFatal(f"Notion API error {status}: {exc}") from exc
            except Exception as exc:  # network errors
                log.warning("notion: network error attempt=%s: %s", attempt, exc)
                last_exc = exc
                if delay is not None:
                    await asyncio.sleep(delay or 4)
                continue

        raise NotionRetryable(f"Notion request failed after retries: {last_exc}") from last_exc

    async def _call(self, method: str, **kwargs: Any) -> dict:
        """Dispatch via raw REST paths (CR-2).

        notion-client 2.7+ перегруппировал endpoint-классы под data-sources API
        (databases.query исчез); при notion_version=2022-06-28 классические
        пути ниже остаются валидными, поэтому ходим в request() напрямую —
        структура SDK-обёрток больше не влияет.
        """
        if method == "databases.query":
            database_id = kwargs.pop("database_id")
            return await self._client.request(
                path=f"databases/{database_id}/query", method="POST", body=kwargs
            )
        if method == "databases.retrieve":
            return await self._client.request(
                path=f"databases/{kwargs['database_id']}", method="GET"
            )
        if method == "pages.retrieve":
            return await self._client.request(
                path=f"pages/{kwargs['page_id']}", method="GET"
            )
        raise ValueError(f"unknown notion method: {method}")

    async def close(self) -> None:
        task = getattr(self, "_bg_refresh_task", None)
        if task is not None:
            task.cancel()
        await self._client.aclose()


def _parse_retry_after(exc: APIResponseError) -> float | None:
    """Try to extract Retry-After value from the exception headers."""
    try:
        headers = exc.headers  # type: ignore[attr-defined]
        if headers and "retry-after" in headers:
            return float(headers["retry-after"])
    except Exception:
        pass
    return None
