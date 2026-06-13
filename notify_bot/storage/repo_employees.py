"""Repository for the employees table."""

import aiosqlite


async def get_by_name(conn: aiosqlite.Connection, canonical_name: str) -> dict | None:
    async with conn.execute(
        "SELECT canonical_name, chat_id, bound_at, created_at FROM employees WHERE canonical_name = ?",
        (canonical_name,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_by_chat_id(conn: aiosqlite.Connection, chat_id: int) -> dict | None:
    async with conn.execute(
        "SELECT canonical_name, chat_id, bound_at, created_at FROM employees WHERE chat_id = ?",
        (chat_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def is_bound(conn: aiosqlite.Connection, chat_id: int) -> bool:
    row = await get_by_chat_id(conn, chat_id)
    return row is not None and row.get("chat_id") is not None


async def upsert_name(conn: aiosqlite.Connection, canonical_name: str) -> None:
    """Insert employee row if not exists (CR-7: FK invite->employees)."""
    await conn.execute(
        "INSERT OR IGNORE INTO employees (canonical_name) VALUES (?)",
        (canonical_name,),
    )


async def bind(conn: aiosqlite.Connection, canonical_name: str, chat_id: int) -> None:
    """Set chat_id and bound_at for an employee."""
    await conn.execute(
        """UPDATE employees
           SET chat_id = ?, bound_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
           WHERE canonical_name = ?""",
        (chat_id, canonical_name),
    )


async def unbind(conn: aiosqlite.Connection, canonical_name: str) -> None:
    await conn.execute(
        "UPDATE employees SET chat_id = NULL, bound_at = NULL WHERE canonical_name = ?",
        (canonical_name,),
    )


async def rename(conn: aiosqlite.Connection, old_name: str, new_name: str) -> None:
    await conn.execute(
        "UPDATE employees SET canonical_name = ? WHERE canonical_name = ?",
        (new_name, old_name),
    )


async def list_all(conn: aiosqlite.Connection) -> list:
    async with conn.execute(
        "SELECT canonical_name, chat_id, bound_at, created_at FROM employees ORDER BY canonical_name"
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_bindings_map(conn: aiosqlite.Connection) -> dict:
    """Return {canonical_name: chat_id} for all bound employees."""
    async with conn.execute(
        "SELECT canonical_name, chat_id FROM employees WHERE chat_id IS NOT NULL"
    ) as cursor:
        rows = await cursor.fetchall()
    return {r["canonical_name"]: r["chat_id"] for r in rows}
