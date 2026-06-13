"""Poller: main loop fetching Notion pages and dispatching notifications.

Algorithm matches spec §8 exactly (locked).
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from notify_bot.config import Settings
from notify_bot.core import differ, renderer, router
from notify_bot.notion.client import NotionClient, NotionFatal, NotionRetryable
from notify_bot.notion import parser, projects as proj_module
from notify_bot.storage import (
    db as db_mod,
    repo_employees,
    repo_journal,
    repo_snapshots,
    repo_state,
)

log = logging.getLogger(__name__)

_BACKOFF_DELAYS = [5, 15, 30]  # seconds for NotionRetryable


async def run(
    conn: aiosqlite.Connection,
    client: NotionClient,
    settings: Settings,
    sender_fn,
    stop_event: asyncio.Event,
) -> None:
    """Main poller loop. Runs until stop_event is set."""
    backoff_idx = 0

    while not stop_event.is_set():
        checkpoint = await repo_state.get_checkpoint(conn)
        cold = checkpoint is None

        try:
            await _run_cycle(conn, client, settings, sender_fn, checkpoint, cold)
            backoff_idx = 0  # reset on success
        except NotionRetryable as exc:
            delay = _BACKOFF_DELAYS[min(backoff_idx, len(_BACKOFF_DELAYS) - 1)]
            log.warning("poller: notion retryable error, backoff=%ss: %s", delay, exc)
            backoff_idx += 1
            # checkpoint NOT moved — will retry same window
            await _interruptible_sleep(delay, stop_event)
            continue
        except NotionFatal as exc:
            log.critical("poller: notion fatal error (auth/config): %s", exc)
            # keep looping — admin may fix token without restart
        except asyncio.CancelledError:
            log.info("poller: cancelled, shutting down")
            return
        except Exception as exc:
            log.exception("poller: unexpected error: %s", exc)

        await _interruptible_sleep(settings.poll_interval, stop_event)


async def _run_cycle(
    conn: aiosqlite.Connection,
    client: NotionClient,
    settings: Settings,
    sender_fn,
    checkpoint: str | None,
    cold: bool,
) -> None:
    """Execute one full poll cycle."""
    after = _subtract_seconds(checkpoint, settings.overlap_seconds) if checkpoint else None
    pages = await client.query_incremental(after)

    bindings = await repo_employees.get_bindings_map(conn)
    max_let: str | None = checkpoint

    for raw in pages:
        new_state = parser.parse(raw, settings.props_config)
        old_state = await repo_snapshots.get(conn, new_state.page_id)
        events = differ.diff(old_state, new_state, cold_start=cold, done_status=settings.done_status)

        if cold:
            plan = []
        else:
            project_name = await proj_module.resolve_first(
                new_state.project_ids, conn, client, settings.project_cache_ttl
            )
            plan = router.route(
                events,
                new_state,
                bindings,
                renderer.render,
                project_name=project_name,
                display_tz=settings.display_tz,
            )

        paused = await repo_state.is_paused(conn)
        if paused:
            for item in plan:
                log.info(
                    "poller: suppressed chat_id=%s dedup_key=%s",
                    item.chat_id,
                    item.dedup_key,
                )
            plan = []

        async with db_mod.transaction(conn):
            for item in plan:
                if await repo_journal.exists(conn, item.dedup_key):
                    continue
                ok = await sender_fn(item.chat_id, item.text)
                if ok:
                    await repo_journal.insert(
                        conn,
                        item.dedup_key,
                        new_state.page_id,
                        _event_kind_for(item.dedup_key),
                        item.chat_id,
                    )
            await repo_snapshots.upsert(conn, new_state)

        if max_let is None or new_state.last_edited_time > max_let:
            max_let = new_state.last_edited_time

    if max_let:
        await repo_state.set_checkpoint(conn, max_let)
        await conn.commit()

    _touch_heartbeat(settings.heartbeat_path)
    log.info("poller: cycle done cold=%s pages=%s checkpoint=%s", cold, len(pages), max_let)


def _subtract_seconds(iso_ts: str, seconds: int) -> str:
    """Subtract `seconds` from an ISO datetime string, return ISO string."""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    from datetime import timedelta
    result = dt - timedelta(seconds=seconds)
    return result.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _event_kind_for(dedup_key: str) -> str:
    """Extract event kind from dedup key (format: page_id:kind:value:let:chat_id)."""
    parts = dedup_key.split(":")
    return parts[1] if len(parts) >= 2 else "unknown"


def _touch_heartbeat(path: str) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    except Exception as exc:
        log.warning("poller: could not touch heartbeat %s: %s", path, exc)


async def _interruptible_sleep(seconds: float, stop_event: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
