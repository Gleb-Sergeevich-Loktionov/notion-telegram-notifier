"""Repository for task_snapshots table.

TaskState assignees/reporter/project_ids are stored as JSON arrays.
"""

import json

import aiosqlite

from notify_bot.core.models import TaskState


async def get(conn: aiosqlite.Connection, page_id: str) -> TaskState | None:
    """Load a TaskState by page_id, or return None if not found."""
    async with conn.execute(
        """SELECT page_id, title, status, assignees, reporter, project_ids,
                  due_start, due_end, url, last_edited_time
           FROM task_snapshots WHERE page_id = ?""",
        (page_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_task_state(row)


async def upsert(conn: aiosqlite.Connection, state: TaskState) -> None:
    """Insert or replace a TaskState snapshot."""
    await conn.execute(
        """INSERT INTO task_snapshots
               (page_id, title, status, assignees, reporter, project_ids,
                due_start, due_end, url, last_edited_time, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(page_id) DO UPDATE SET
               title = excluded.title,
               status = excluded.status,
               assignees = excluded.assignees,
               reporter = excluded.reporter,
               project_ids = excluded.project_ids,
               due_start = excluded.due_start,
               due_end = excluded.due_end,
               url = excluded.url,
               last_edited_time = excluded.last_edited_time,
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (
            state.page_id,
            state.title,
            state.status,
            json.dumps(sorted(state.assignees), ensure_ascii=False),
            json.dumps(sorted(state.reporter), ensure_ascii=False),
            json.dumps(list(state.project_ids), ensure_ascii=False),
            state.due_start,
            state.due_end,
            state.url,
            state.last_edited_time,
        ),
    )


def _row_to_task_state(row: aiosqlite.Row) -> TaskState:
    return TaskState(
        page_id=row["page_id"],
        title=row["title"],
        status=row["status"],
        assignees=frozenset(json.loads(row["assignees"])),
        reporter=frozenset(json.loads(row["reporter"])),
        project_ids=tuple(json.loads(row["project_ids"])),
        due_start=row["due_start"],
        due_end=row["due_end"],
        url=row["url"],
        last_edited_time=row["last_edited_time"],
    )
