"""Renderer: produce HTML notification text for Telegram.

All user-supplied strings are html.escaped before insertion.
Templates per spec §7 (locked).
"""

import html
from zoneinfo import ZoneInfo

from notify_bot.core.models import Event, EventKind, TaskState

_NO_VALUE = "—"
_NO_TITLE = "(без названия)"
_DB_LABEL = "All Tasks"


def render(
    event: Event,
    task: TaskState,
    project_name: str | None,
    display_tz: str,
) -> str:
    """Render HTML notification text for one event.

    Args:
        event: the Event being notified about.
        task: current TaskState.
        project_name: resolved project name, or None.
        display_tz: IANA timezone name for date display.
    """
    title = html.escape(task.title) if task.title else _NO_TITLE
    project = html.escape(project_name) if project_name else _NO_VALUE
    due = _format_due(task.due_start, task.due_end, display_tz)
    url = html.escape(task.url)

    if event.kind == EventKind.NEW_ASSIGNEE:
        return _render_new_assignee(title, project, due, url)
    return _render_status_changed(event, title, project, due, url)


def _render_new_assignee(title: str, project: str, due: str, url: str) -> str:
    return (
        f"🆕 Новая задача · {_DB_LABEL}\n"
        f"«{title}»\n"
        f"Проект: {project} · Дедлайн: {due}\n"
        f'<a href="{url}">Открыть в Notion</a>'
    )


def _render_status_changed(
    event: Event, title: str, project: str, due: str, url: str
) -> str:
    old = html.escape(event.old_status) if event.old_status else _NO_VALUE
    new = html.escape(event.new_status) if event.new_status else _NO_VALUE
    return (
        f"🔄 Статус изменён · {_DB_LABEL}\n"
        f"«{title}»\n"
        f"{old} → {new}\n"
        f"Проект: {project} · Дедлайн: {due}\n"
        f'<a href="{url}">Открыть в Notion</a>'
    )


def _format_due(due_start: str | None, due_end: str | None, display_tz: str) -> str:
    """Format due date(s) as DD.MM in display timezone."""
    if due_start is None:
        return _NO_VALUE
    tz = ZoneInfo(display_tz)
    start_str = _iso_to_ddmm(due_start, tz)
    if due_end:
        end_str = _iso_to_ddmm(due_end, tz)
        return f"{start_str} → {end_str}"
    return start_str


def _iso_to_ddmm(iso_date: str, tz: ZoneInfo) -> str:
    """Convert ISO date string (YYYY-MM-DD or ISO datetime) to DD.MM in tz."""
    from datetime import date, datetime, timezone

    # Notion dates can be "YYYY-MM-DD" or full ISO datetime; malformed -> "—" (HR-6)
    try:
        if "T" in iso_date:
            dt = datetime.fromisoformat(iso_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local_dt = dt.astimezone(tz)
            d = local_dt.date()
        else:
            d = date.fromisoformat(iso_date)
    except ValueError:
        return _NO_VALUE

    return d.strftime("%d.%m")
