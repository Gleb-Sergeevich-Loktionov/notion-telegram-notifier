"""Admin command handlers (spec §11).

Commands: /invite /list /rename /unbind /pause /resume
All guarded by AdminFilter middleware.
"""

import difflib
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from notify_bot.storage import (
    repo_employees,
    repo_invites,
    repo_snapshots,
    repo_state,
)

log = logging.getLogger(__name__)

_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LEN = 8

router = Router()


def _gen_code() -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(_INVITE_CODE_LEN))


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _expires_at(invite_ttl: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=invite_ttl)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def make_router(conn: aiosqlite.Connection, settings, notion_client=None) -> Router:
    """Create and return admin router with injected dependencies."""

    async def _get_schema_options() -> list[str]:
        """Get assignee option names from Notion DB schema cache."""
        if notion_client is None:
            return []
        try:
            db_schema = await notion_client.retrieve_db()
            props = db_schema.get("properties", {})
            prop = props.get(settings.prop_assignee, {})
            options = prop.get("multi_select", {}).get("options", [])
            return [o["name"] for o in options if "name" in o]
        except Exception as exc:
            log.warning("admin: could not fetch schema options: %s", exc)
            return []

    @router.message(Command("invite"))
    async def cmd_invite(message: Message) -> None:
        text = message.text or ""
        name = text[len("/invite"):].strip()
        if not name:
            await message.answer("Использование: /invite <Имя>")
            return

        options = await _get_schema_options()
        if options and name not in options:
            suggestions = difflib.get_close_matches(name, options, n=3, cutoff=0.4)
            if suggestions:
                hint = "\n".join(f"  • {s}" for s in suggestions)
                await message.answer(
                    f"Имя «{name}» не найдено в опциях.\nВозможно вы имели в виду:\n{hint}"
                )
            else:
                await message.answer(f"Имя «{name}» не найдено в опциях Notion.")
            return

        # CR-7: ensure employee row exists (FK for invite)
        await repo_employees.upsert_name(conn, name)
        await conn.commit()

        # Invalidate old codes for this name
        await repo_invites.invalidate_for_name(conn, name)

        code = _gen_code()
        code_hash = _sha256(code)
        expires = _expires_at(settings.invite_ttl)

        await repo_invites.insert(conn, name, code_hash, expires)
        await conn.commit()

        ttl_hours = settings.invite_ttl // 3600
        await message.answer(
            f"Код для {name}:\n<code>{code}</code>\n\n"
            f"Истекает через {ttl_hours} ч. Передайте сотруднику лично.",
            parse_mode="HTML",
        )

    @router.message(Command("list"))
    async def cmd_list(message: Message) -> None:
        employees = await repo_employees.list_all(conn)
        if not employees:
            await message.answer("Сотрудников нет.")
            return

        lines = ["<b>Сотрудники:</b>"]
        for emp in employees:
            chat_id_str = str(emp["chat_id"]) if emp["chat_id"] else "—"
            bound_str = emp.get("bound_at") or "—"
            lines.append(f"{emp['canonical_name']} · {chat_id_str} · {bound_str}")

        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("rename"))
    async def cmd_rename(message: Message) -> None:
        text = message.text or ""
        args = text[len("/rename"):].strip()
        sep = " -> "
        if sep not in args:
            await message.answer("Использование: /rename Старое Имя -> Новое Имя")
            return

        idx = args.index(sep)
        old_name = args[:idx].strip()
        new_name = args[idx + len(sep):].strip()

        if not old_name or not new_name:
            await message.answer("Использование: /rename Старое Имя -> Новое Имя")
            return

        emp = await repo_employees.get_by_name(conn, old_name)
        if emp is None:
            await message.answer(f"Сотрудник «{old_name}» не найден.")
            return

        # Update snapshots: Python-side JSON replacement (CR-5)
        await _rename_in_snapshots(conn, old_name, new_name)

        # Rename employee row
        await repo_employees.rename(conn, old_name, new_name)
        await conn.commit()

        await message.answer(
            f"✅ Переименовано: {old_name} → {new_name}\n"
            "⚠️ Переименуйте ярлык в Notion сейчас же."
        )

    @router.message(Command("unbind"))
    async def cmd_unbind(message: Message) -> None:
        text = message.text or ""
        name = text[len("/unbind"):].strip()
        if not name:
            await message.answer("Использование: /unbind <Имя>")
            return

        emp = await repo_employees.get_by_name(conn, name)
        if emp is None:
            await message.answer(f"Сотрудник «{name}» не найден.")
            return

        await repo_employees.unbind(conn, name)
        await conn.commit()
        await message.answer(f"✅ Привязка снята: {name}")

    @router.message(Command("pause"))
    async def cmd_pause(message: Message) -> None:
        await repo_state.set_paused(conn, True)
        await conn.commit()
        await message.answer(
            "⏸ Рассылка на паузе. События периода НЕ будут досланы после возобновления."
        )

    @router.message(Command("resume"))
    async def cmd_resume(message: Message) -> None:
        await repo_state.set_paused(conn, False)
        await conn.commit()
        await message.answer("▶️ Рассылка возобновлена.")

    return router


async def _rename_in_snapshots(
    conn: aiosqlite.Connection, old_name: str, new_name: str
) -> None:
    """CR-5: Replace old_name with new_name in snapshot JSON arrays.

    Uses LIKE '%"old_name"%' to find candidates, then does exact Python-level
    element replacement to avoid corrupting substring names.
    """
    pattern = f'%"{old_name}"%'
    async with conn.execute(
        "SELECT page_id, assignees, reporter FROM task_snapshots "
        "WHERE assignees LIKE ? OR reporter LIKE ?",
        (pattern, pattern),
    ) as cursor:
        rows = await cursor.fetchall()

    for row in rows:
        page_id = row["page_id"]
        new_assignees = _replace_in_json_list(row["assignees"], old_name, new_name)
        new_reporter = _replace_in_json_list(row["reporter"], old_name, new_name)
        await conn.execute(
            "UPDATE task_snapshots SET assignees = ?, reporter = ? WHERE page_id = ?",
            (new_assignees, new_reporter, page_id),
        )


def _replace_in_json_list(json_str: str, old: str, new: str) -> str:
    """Exact element replacement in a JSON array string."""
    try:
        items = json.loads(json_str)
        updated = [new if item == old else item for item in items]
        return json.dumps(updated, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return json_str
