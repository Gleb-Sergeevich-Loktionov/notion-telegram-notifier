"""Resolve project page_ids to human-readable titles.

Uses repo_projects cache with TTL (PROJECT_CACHE_TTL seconds).
On miss: calls notion client retrieve_page().
On unavailable: returns None (renderer shows «—»).
"""

import logging
import time

import aiosqlite

from notify_bot.notion.client import NotionClient
from notify_bot.storage import repo_projects

log = logging.getLogger(__name__)

# In-memory TTL guard: {page_id: fetched_at_monotonic}
_fetched_at: dict[str, float] = {}


async def resolve(
    page_id: str,
    conn: aiosqlite.Connection,
    client: NotionClient,
    cache_ttl: int,
) -> str | None:
    """Return project title for page_id, or None if unavailable."""
    cached = await repo_projects.get(conn, page_id)
    if cached and _is_fresh(page_id, cache_ttl):
        return cached["title"]

    try:
        raw = await client.retrieve_page(page_id)
        title = _extract_title(raw)
        if title:
            await repo_projects.upsert(conn, page_id, title)
            await conn.commit()
            _fetched_at[page_id] = time.monotonic()
            return title
        log.warning("projects: empty title for page_id=%s", page_id)
        return None
    except Exception as exc:
        log.warning("projects: could not resolve page_id=%s: %s", page_id, exc)
        return None


async def resolve_first(
    project_ids: tuple,
    conn: aiosqlite.Connection,
    client: NotionClient,
    cache_ttl: int,
) -> str | None:
    """Resolve the first project_id in the tuple, or None."""
    if not project_ids:
        return None
    return await resolve(project_ids[0], conn, client, cache_ttl)


def _is_fresh(page_id: str, ttl: int) -> bool:
    fetched = _fetched_at.get(page_id)
    if fetched is None:
        return False
    return (time.monotonic() - fetched) < ttl


def _extract_title(raw: dict) -> str:
    """Extract plain-text title from a Notion page response."""
    props = raw.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            rich = prop.get("title", [])
            return "".join(chunk.get("plain_text", "") for chunk in rich)
    # fallback: check top-level title if page has it
    return ""
