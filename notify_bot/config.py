"""Settings loaded from environment variables.

Fail-fast: missing required vars → clear message to stderr + sys.exit(1).
Token values are never logged.
"""

import os
import sys
from dataclasses import dataclass, field


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: required env var {name!r} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def _opt(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _opt_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"ERROR: env var {name!r} must be an integer, got {raw!r}", file=sys.stderr)
        sys.exit(1)


def _admin_ids(name: str) -> list:
    raw = os.environ.get(name, "").strip()
    if not raw:
        print(f"ERROR: required env var {name!r} is not set", file=sys.stderr)
        sys.exit(1)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        print(f"ERROR: {name!r} must contain at least one chat_id", file=sys.stderr)
        sys.exit(1)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            print(f"ERROR: {name!r} contains non-integer value {p!r}", file=sys.stderr)
            sys.exit(1)
    return result


@dataclass(frozen=True)
class Settings:
    notion_token: str
    telegram_token: str
    notion_database_id: str
    admin_chat_ids: tuple  # tuple[int, ...]

    db_path: str = "/data/bot.db"
    poll_interval: int = 90
    overlap_seconds: int = 300
    display_tz: str = "Europe/Moscow"

    prop_title: str = "Name"
    prop_assignee: str = "Assign_new"
    prop_reporter: str = "Заказчик_new"
    prop_status: str = "Status"
    prop_project: str = "Проект"
    prop_due: str = "Дата"
    done_status: str = "Готово"

    project_cache_ttl: int = 86400
    invite_ttl: int = 86400
    invite_max_attempts: int = 3

    heartbeat_path: str = "/tmp/notify_bot_heartbeat"
    notion_base_url: str = ""  # пусто = дефолт SDK (https://api.notion.com); для тестов/демо

    @property
    def props_config(self) -> dict:
        return {
            "title": self.prop_title,
            "assignee": self.prop_assignee,
            "reporter": self.prop_reporter,
            "status": self.prop_status,
            "project": self.prop_project,
            "due": self.prop_due,
        }


def load() -> Settings:
    """Load and validate settings from environment. Exits on missing required vars."""
    notion_token = _require("NOTION_TOKEN")
    telegram_token = _require("TELEGRAM_TOKEN")
    notion_database_id = _require("NOTION_DATABASE_ID")
    admin_chat_ids = _admin_ids("ADMIN_CHAT_IDS")

    return Settings(
        notion_token=notion_token,
        telegram_token=telegram_token,
        notion_database_id=notion_database_id,
        admin_chat_ids=tuple(admin_chat_ids),
        db_path=_opt("DB_PATH", "/data/bot.db"),
        poll_interval=_opt_int("POLL_INTERVAL", 90),
        overlap_seconds=_opt_int("OVERLAP_SECONDS", 300),
        display_tz=_opt("DISPLAY_TZ", "Europe/Moscow"),
        prop_title=_opt("PROP_TITLE", "Name"),
        prop_assignee=_opt("PROP_ASSIGNEE", "Assign_new"),
        prop_reporter=_opt("PROP_REPORTER", "Заказчик_new"),
        prop_status=_opt("PROP_STATUS", "Status"),
        prop_project=_opt("PROP_PROJECT", "Проект"),
        prop_due=_opt("PROP_DUE", "Дата"),
        done_status=_opt("DONE_STATUS", "Готово"),
        project_cache_ttl=_opt_int("PROJECT_CACHE_TTL", 86400),
        invite_ttl=_opt_int("INVITE_TTL", 86400),
        invite_max_attempts=_opt_int("INVITE_MAX_ATTEMPTS", 3),
        heartbeat_path=_opt("HEARTBEAT_PATH", "/tmp/notify_bot_heartbeat"),
        notion_base_url=_opt("NOTION_BASE_URL", ""),
    )
