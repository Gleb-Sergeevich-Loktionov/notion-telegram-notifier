"""Repository for project_cache table."""

import aiosqlite


async def get(conn: aiosqlite.Connection, page_id: str) -> dict | None:
    async with conn.execute(
        "SELECT page_id, title, refreshed_at FROM project_cache WHERE page_id = ?",
        (page_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert(conn: aiosqlite.Connection, page_id: str, title: str) -> None:
    await conn.execute(
        """INSERT INTO project_cache (page_id, title, refreshed_at)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(page_id) DO UPDATE SET
               title = excluded.title,
               refreshed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (page_id, title),
    )


async def get_title(conn: aiosqlite.Connection, page_id: str) -> str | None:
    row = await get(conn, page_id)
    return row["title"] if row else None
