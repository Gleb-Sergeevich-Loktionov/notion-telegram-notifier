"""Repository for bot_state kv-singleton (checkpoint, paused)."""

import aiosqlite

_KEY_CHECKPOINT = "checkpoint"
_KEY_PAUSED = "paused"
_PAUSED_TRUE = "true"
_PAUSED_FALSE = "false"


async def get_checkpoint(conn: aiosqlite.Connection) -> str | None:
    async with conn.execute(
        "SELECT value FROM bot_state WHERE key = ?", (_KEY_CHECKPOINT,)
    ) as cursor:
        row = await cursor.fetchone()
    return row["value"] if row else None


async def set_checkpoint(conn: aiosqlite.Connection, value: str) -> None:
    await conn.execute(
        "INSERT INTO bot_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_KEY_CHECKPOINT, value),
    )


async def is_paused(conn: aiosqlite.Connection) -> bool:
    async with conn.execute(
        "SELECT value FROM bot_state WHERE key = ?", (_KEY_PAUSED,)
    ) as cursor:
        row = await cursor.fetchone()
    return row["value"] == _PAUSED_TRUE if row else False


async def set_paused(conn: aiosqlite.Connection, paused: bool) -> None:
    value = _PAUSED_TRUE if paused else _PAUSED_FALSE
    await conn.execute(
        "INSERT INTO bot_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_KEY_PAUSED, value),
    )
