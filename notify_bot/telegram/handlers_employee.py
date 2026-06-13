"""Employee self-registration handlers.

FSM flow (code-first, spec §10):
  /start → EnterCode → ConfirmName → done
Throttle: 10 failures per chat_id → mute 1 hour (in-memory).
"""

import hashlib
import logging
import time
from datetime import datetime, timezone

import aiosqlite
from aiogram import F, Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from notify_bot.storage import repo_employees, repo_invites
from notify_bot.telegram.fsm import EmployeeReg

log = logging.getLogger(__name__)

router = Router()

# In-memory throttle: {chat_id: {"count": int, "muted_until": float}}
_throttle: dict[int, dict] = {}

_MAX_FAILS = 10
_MUTE_SECONDS = 3600


def _is_muted(chat_id: int) -> bool:
    entry = _throttle.get(chat_id)
    if entry is None:
        return False
    muted_until = entry.get("muted_until", 0.0)
    if muted_until and time.monotonic() < muted_until:
        return True
    return False


def _register_fail(chat_id: int) -> None:
    entry = _throttle.setdefault(chat_id, {"count": 0, "muted_until": 0.0})
    entry["count"] += 1
    if entry["count"] >= _MAX_FAILS:
        entry["muted_until"] = time.monotonic() + _MUTE_SECONDS
        log.info("throttle: muting chat_id=%s for %ss", chat_id, _MUTE_SECONDS)


def make_router(conn: aiosqlite.Connection, settings) -> Router:
    """Create and return the employee router with injected dependencies."""

    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext) -> None:
        chat_id = message.from_user.id

        if await repo_employees.is_bound(conn, chat_id):
            emp = await repo_employees.get_by_chat_id(conn, chat_id)
            name = emp["canonical_name"] if emp else "?"
            await message.answer(f"Вы уже привязаны как {name}. /me")
            return

        if _is_muted(chat_id):
            return  # ignore silently

        await state.set_state(EmployeeReg.EnterCode)
        await state.update_data(attempts=0)
        await message.answer("Введите код приглашения от админа:")

    @router.message(EmployeeReg.EnterCode, F.text, ~F.text.startswith("/"))
    async def enter_code(message: Message, state: FSMContext) -> None:
        chat_id = message.from_user.id

        if _is_muted(chat_id):
            return

        code = (message.text or "").strip().upper()
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        rec = await repo_invites.find_valid_by_hash(conn, code_hash)

        if rec is None:
            _register_fail(chat_id)
            data = await state.get_data()
            attempts = data.get("attempts", 0) + 1
            await state.update_data(attempts=attempts)
            max_attempts = settings.invite_max_attempts

            if attempts >= max_attempts:
                await state.clear()
                await message.answer("Превышено число попыток. Обратитесь к админу.")
                return

            remaining = max_attempts - attempts
            await message.answer(f"Неверный код. Осталось попыток: {remaining}")
            return

        name = rec["canonical_name"]
        await state.update_data(invite_id=rec["id"], canonical_name=name)
        await state.set_state(EmployeeReg.ConfirmName)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data="confirm_bind:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_bind:no"),
            ]
        ])
        await message.answer(f"Привязать вас как {name}?", reply_markup=kb)

    @router.callback_query(EmployeeReg.ConfirmName)
    async def confirm_name(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        action = (callback.data or "").split(":")[-1]
        await state.clear()

        if action != "yes":
            await callback.message.answer(
                "Если код не ваш — обратитесь к админу."
            )
            await callback.answer()
            return

        invite_id = data["invite_id"]
        name = data["canonical_name"]
        chat_id = callback.from_user.id

        # Check for existing binding (rebind case, HR-5)
        existing = await repo_employees.get_by_name(conn, name)
        old_chat_id = existing["chat_id"] if existing else None

        await repo_employees.bind(conn, name, chat_id)
        await repo_invites.mark_used(conn, invite_id)
        await conn.commit()

        if old_chat_id and old_chat_id != chat_id:
            log.info(
                "rebind: name=%s old_chat_id=%s new_chat_id=%s",
                name, old_chat_id, chat_id,
            )
            for admin_id in settings.admin_chat_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ Перепривязка: {name}\nСтарый: {old_chat_id} → Новый: {chat_id}",
                    )
                except Exception as exc:
                    log.warning("rebind notify admin failed: %s", exc)

        await callback.message.answer(f"✅ Привязка сохранена: {name}")
        await callback.answer()

    @router.message(Command("me"))
    async def cmd_me(message: Message) -> None:
        chat_id = message.from_user.id
        emp = await repo_employees.get_by_chat_id(conn, chat_id)
        if emp:
            bound_at = emp.get("bound_at") or "—"
            await message.answer(f"Вы привязаны как: {emp['canonical_name']}\nС: {bound_at}")
        else:
            await message.answer("Вы не привязаны. Используйте /start чтобы привязаться.")

    return router
