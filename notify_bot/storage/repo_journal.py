"""Repository for sent_notifications (dedup journal)."""

import aiosqlite


async def exists(conn: aiosqlite.Connection, dedup_key: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM sent_notifications WHERE dedup_key = ?",
        (dedup_key,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def insert(
    conn: aiosqlite.Connection,
    dedup_key: str,
    page_id: str,
    event_kind: str,
    chat_id: int,
) -> None:
    """INSERT OR IGNORE — safe against race/retry duplicates."""
    await conn.execute(
        """INSERT OR IGNORE INTO sent_notifications (dedup_key, page_id, event_kind, chat_id)
           VALUES (?, ?, ?, ?)""",
        (dedup_key, page_id, event_kind, chat_id),
    )
