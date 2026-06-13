"""Database connection, schema init, and transaction helper."""

import pathlib
from contextlib import asynccontextmanager

import aiosqlite

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


async def connect(db_path: str) -> aiosqlite.Connection:
    """Open an aiosqlite connection with WAL mode and foreign keys."""
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    return conn


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Apply schema.sql idempotently (CREATE TABLE IF NOT EXISTS)."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    await conn.executescript(sql)
    await conn.commit()


@asynccontextmanager
async def transaction(conn: aiosqlite.Connection):
    """Async context manager that commits on exit or rolls back on exception."""
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
