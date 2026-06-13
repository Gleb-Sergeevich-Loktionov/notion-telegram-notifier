"""Repository for invite_codes table."""

import aiosqlite


async def find_valid_by_hash(conn: aiosqlite.Connection, code_hash: str) -> dict | None:
    """Return an active (not used, not expired) invite record by code hash."""
    async with conn.execute(
        """SELECT id, canonical_name, code_hash, expires_at, used_at, created_at
           FROM invite_codes
           WHERE code_hash = ?
             AND used_at IS NULL
             AND expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (code_hash,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def insert(
    conn: aiosqlite.Connection,
    canonical_name: str,
    code_hash: str,
    expires_at: str,
) -> int:
    async with conn.execute(
        "INSERT INTO invite_codes (canonical_name, code_hash, expires_at) VALUES (?, ?, ?)",
        (canonical_name, code_hash, expires_at),
    ) as cursor:
        return cursor.lastrowid


async def mark_used(conn: aiosqlite.Connection, invite_id: int) -> None:
    await conn.execute(
        "UPDATE invite_codes SET used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (invite_id,),
    )


async def invalidate_for_name(conn: aiosqlite.Connection, canonical_name: str) -> None:
    """Mark all unused codes for a name as used (invalidate on re-invite)."""
    await conn.execute(
        """UPDATE invite_codes
           SET used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
           WHERE canonical_name = ? AND used_at IS NULL""",
        (canonical_name,),
    )
