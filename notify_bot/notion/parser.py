"""Parser: raw Notion page dict -> TaskState.

Contract (spec §9):
- Property names come from a config dict/object (no hardcoded names).
- Missing properties -> fallback + log.warning once per key.
- Unknown type -> log.error + fallback.
- Never raises.
"""

import logging
from typing import Any

from notify_bot.core.models import TaskState

log = logging.getLogger(__name__)

# Module-level set to track already-warned missing property keys (warn-once).
_warned_missing: set = set()


def parse(raw: dict, props_config: dict) -> TaskState:
    """Parse a raw Notion page dict into a TaskState.

    Args:
        raw: full Notion page response dict.
        props_config: mapping of logical name -> Notion property name, e.g.:
            {
                "title":    "Name",
                "assignee": "Assign_new",
                "reporter": "Заказчик_new",
                "status":   "Status",
                "project":  "Проект",
                "due":      "Дата",
            }
    """
    props = raw.get("properties", {})

    title = _parse_title(props, props_config.get("title", "Name"))
    assignees = _parse_multi_select(props, props_config.get("assignee", "Assign_new"))
    reporter = _parse_reporter(props, props_config.get("reporter", "Заказчик_new"))
    status = _parse_status(props, props_config.get("status", "Status"))
    project_ids = _parse_relation(props, props_config.get("project", "Проект"))
    due_start, due_end = _parse_due(props, props_config.get("due", "Дата"))

    return TaskState(
        page_id=raw.get("id", ""),
        title=title,
        status=status,
        assignees=frozenset(assignees),
        reporter=frozenset(reporter),
        project_ids=tuple(project_ids),
        due_start=due_start,
        due_end=due_end,
        url=raw.get("url", ""),
        last_edited_time=raw.get("last_edited_time", ""),
    )


def _warn_missing(key: str) -> None:
    if key not in _warned_missing:
        log.warning("notion_parser: missing property key=%r", key)
        _warned_missing.add(key)


def _get_prop(props: dict, key: str) -> Any | None:
    if key not in props:
        _warn_missing(key)
        return None
    return props[key]


def _parse_title(props: dict, key: str) -> str:
    prop = _get_prop(props, key)
    if prop is None:
        return ""
    rich_text = prop.get("title", [])
    return "".join(chunk.get("plain_text", "") for chunk in rich_text)


def _parse_multi_select(props: dict, key: str) -> list:
    prop = _get_prop(props, key)
    if prop is None:
        return []
    items = prop.get("multi_select", [])
    if not isinstance(items, list):
        log.error("notion_parser: unexpected type for multi_select key=%r", key)
        return []
    return [o["name"] for o in items if "name" in o]


def _parse_reporter(props: dict, key: str) -> list:
    """Support both multi_select and select for reporter field."""
    prop = _get_prop(props, key)
    if prop is None:
        return []

    if "multi_select" in prop:
        items = prop["multi_select"]
        if not isinstance(items, list):
            log.error("notion_parser: unexpected multi_select for reporter key=%r", key)
            return []
        return [o["name"] for o in items if "name" in o]

    if "select" in prop:
        sel = prop["select"]
        if sel is None:
            return []
        name = sel.get("name")
        return [name] if name else []

    log.error("notion_parser: unknown reporter property type key=%r prop=%r", key, prop)
    return []


def _parse_status(props: dict, key: str) -> str | None:
    """Support status type and select type."""
    prop = _get_prop(props, key)
    if prop is None:
        return None

    if "status" in prop:
        val = prop["status"]
        return val.get("name") if val else None

    if "select" in prop:
        val = prop["select"]
        return val.get("name") if val else None

    log.error("notion_parser: unknown status property type key=%r prop=%r", key, prop)
    return None


def _parse_relation(props: dict, key: str) -> list:
    prop = _get_prop(props, key)
    if prop is None:
        return []
    items = prop.get("relation", [])
    if not isinstance(items, list):
        log.error("notion_parser: unexpected type for relation key=%r", key)
        return []
    return [o["id"] for o in items if "id" in o]


def _parse_due(props: dict, key: str) -> tuple:
    """Return (due_start, due_end) or (None, None)."""
    prop = _get_prop(props, key)
    if prop is None:
        return (None, None)
    date_val = prop.get("date")
    if date_val is None:
        return (None, None)
    return (date_val.get("start"), date_val.get("end"))
