"""Tests for telegram/handlers_employee.py — direct handler invocation.

All aiogram handlers are plain async functions; we call them directly
with fake Message/CallbackQuery/FSMContext objects (no Dispatcher needed).

Covers:
- /start: already-bound user → /me hint
- /start: unbound, not muted → sets EnterCode state
- /start: muted user → silent ignore
- enter_code: muted user → silent ignore
- enter_code: invalid code → fail counter incremented, remaining shown
- enter_code: max attempts reached → clear + error message
- enter_code: valid code → confirm keyboard sent with employee name
- confirm_name: action=no → cancel message
- confirm_name: action=yes → bind + invite used + success message
- confirm_name: action=yes with rebind → admin notification sent
- /me: bound user → name shown
- /me: unbound user → prompt to /start
"""

import asyncio
import datetime
import hashlib
import pytest
import pytest_asyncio

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from notify_bot.config import Settings
from notify_bot.storage import db as db_mod, repo_employees, repo_invites
from notify_bot.telegram import handlers_employee as he
from notify_bot.telegram.fsm import EmployeeReg


# ── fixtures & helpers ───────────────────────────────────────


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _make_settings(**overrides):
    base = dict(
        notion_token="x",
        telegram_token="123:ABC",
        notion_database_id="db1",
        admin_chat_ids=(999,),
        db_path=":memory:",
        invite_max_attempts=3,
        invite_ttl=86400,
    )
    base.update(overrides)
    return Settings(**base)



@pytest_asyncio.fixture
async def conn():
    c = await db_mod.connect(":memory:")
    await db_mod.init_schema(c)
    yield c
    await c.close()


@pytest_asyncio.fixture
def settings():
    return _make_settings()


def _make_fsm_ctx(user_id: int) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=0, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


class FakeMessage:
    """Minimal fake for aiogram.types.Message."""

    def __init__(self, text: str, user_id: int):
        self.text = text

        class _User:
            id = user_id

        self.from_user = _User()
        self.replies: list[dict] = []

    async def answer(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeCallbackQuery:
    """Minimal fake for aiogram.types.CallbackQuery."""

    def __init__(self, data: str, user_id: int, message_text: str = ""):
        self.data = data

        class _User:
            id = user_id

        self.from_user = _User()
        self.message = FakeMessage(message_text, user_id)
        self.answered = False

    async def answer(self):
        self.answered = True


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.raises: Exception | None = None

    async def send_message(self, chat_id: int, text: str, **kwargs):
        if self.raises:
            raise self.raises
        self.sent.append((chat_id, text))


# ── /start tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_already_bound_replies_me_hint(conn, settings):
    """Bound user gets '/me' hint instead of entering code flow."""
    he._throttle.clear()

    await repo_employees.upsert_name(conn, "Иван")
    await repo_employees.bind(conn, "Иван", 42)
    await conn.commit()

    # Build router to capture handler
    r = he.make_router(conn, settings)
    # Extract cmd_start by calling through the registered handlers list
    # handlers_employee registers: cmd_start, enter_code, confirm_name, cmd_me
    # We call the closure directly via the router's observers
    msg = FakeMessage("/start", user_id=42)
    ctx = _make_fsm_ctx(42)

    # Get the first handler function registered under Command("start")
    # by finding it on the router observers
    cmd_start = _get_handler(r, "cmd_start")
    await cmd_start(msg, ctx)

    assert any("/me" in rep["text"] for rep in msg.replies)


@pytest.mark.asyncio
async def test_start_unbound_sets_enter_code_state(conn, settings):
    """Unbound user: state set to EnterCode, prompt shown."""
    he._throttle.clear()

    r = he.make_router(conn, settings)
    msg = FakeMessage("/start", user_id=101)
    ctx = _make_fsm_ctx(101)

    cmd_start = _get_handler(r, "cmd_start")
    await cmd_start(msg, ctx)

    state = await ctx.get_state()
    assert state == EmployeeReg.EnterCode
    assert msg.replies  # something replied


@pytest.mark.asyncio
async def test_start_muted_user_ignores_silently(conn, settings):
    """Muted user: /start ignored with no reply."""
    he._throttle.clear()

    uid = 202
    for _ in range(he._MAX_FAILS):
        he._register_fail(uid)
    assert he._is_muted(uid)

    r = he.make_router(conn, settings)
    msg = FakeMessage("/start", user_id=uid)
    ctx = _make_fsm_ctx(uid)

    cmd_start = _get_handler(r, "cmd_start")
    await cmd_start(msg, ctx)

    assert msg.replies == []


# ── enter_code tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_enter_code_muted_ignores(conn, settings):
    """Muted user in EnterCode state: message ignored."""
    he._throttle.clear()

    uid = 303
    for _ in range(he._MAX_FAILS):
        he._register_fail(uid)

    r = he.make_router(conn, settings)
    msg = FakeMessage("ANYCODE", user_id=uid)
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.EnterCode)

    enter_code = _get_handler(r, "enter_code")
    await enter_code(msg, ctx)

    assert msg.replies == []


@pytest.mark.asyncio
async def test_enter_code_wrong_code_shows_remaining(conn, settings):
    """Wrong code: reply shows remaining attempts count."""
    he._throttle.clear()

    uid = 404
    r = he.make_router(conn, settings)
    msg = FakeMessage("BADCODE1", user_id=uid)
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.EnterCode)
    await ctx.update_data(attempts=0)

    enter_code = _get_handler(r, "enter_code")
    await enter_code(msg, ctx)

    assert msg.replies
    # First wrong attempt: remaining = 3 - 1 = 2
    assert "2" in msg.replies[0]["text"]


@pytest.mark.asyncio
async def test_enter_code_max_attempts_clears_and_notifies(conn, settings):
    """After max_attempts wrong codes: state cleared, error message sent."""
    he._throttle.clear()

    uid = 505
    r = he.make_router(conn, settings)
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.EnterCode)
    # Already used max_attempts - 1 attempts
    await ctx.update_data(attempts=settings.invite_max_attempts - 1)

    msg = FakeMessage("WRONGFINAL", user_id=uid)
    enter_code = _get_handler(r, "enter_code")
    await enter_code(msg, ctx)

    state = await ctx.get_state()
    assert state is None  # cleared
    assert any("попыток" in rep["text"] for rep in msg.replies)


@pytest.mark.asyncio
async def test_enter_code_valid_code_shows_confirm_keyboard(conn, settings):
    """Valid invite code: confirm keyboard with employee name shown."""
    he._throttle.clear()

    await repo_employees.upsert_name(conn, "Мария")
    expires = "2099-01-01T00:00:00.000Z"
    code = "VALIDXXX"
    code_hash = _sha256(code)
    await repo_invites.insert(conn, "Мария", code_hash, expires)
    await conn.commit()

    uid = 606
    r = he.make_router(conn, settings)
    msg = FakeMessage(code, user_id=uid)
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.EnterCode)
    await ctx.update_data(attempts=0)

    enter_code = _get_handler(r, "enter_code")
    await enter_code(msg, ctx)

    state = await ctx.get_state()
    assert state == EmployeeReg.ConfirmName
    assert msg.replies
    assert "Мария" in msg.replies[0]["text"]


# ── confirm_name tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_name_cancel_action(conn, settings):
    """action=no: cancel message sent, state cleared."""
    he._throttle.clear()

    uid = 707
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.ConfirmName)
    await ctx.update_data(invite_id=1, canonical_name="Тест")

    cb = FakeCallbackQuery(data="confirm_bind:no", user_id=uid)
    bot = FakeBot()

    r = he.make_router(conn, settings)
    confirm_name = _get_handler(r, "confirm_name")
    await confirm_name(cb, ctx, bot)

    assert cb.answered
    state = await ctx.get_state()
    assert state is None
    assert cb.message.replies


@pytest.mark.asyncio
async def test_confirm_name_yes_binds_and_marks_invite_used(conn, settings):
    """action=yes: employee bound, invite marked used, success message."""
    he._throttle.clear()

    await repo_employees.upsert_name(conn, "Алексей")
    expires = "2099-01-01T00:00:00.000Z"
    invite_id = await repo_invites.insert(conn, "Алексей", "fakehash", expires)
    await conn.commit()

    uid = 808
    ctx = _make_fsm_ctx(uid)
    await ctx.set_state(EmployeeReg.ConfirmName)
    await ctx.update_data(invite_id=invite_id, canonical_name="Алексей")

    cb = FakeCallbackQuery(data="confirm_bind:yes", user_id=uid)
    bot = FakeBot()

    r = he.make_router(conn, settings)
    confirm_name = _get_handler(r, "confirm_name")
    await confirm_name(cb, ctx, bot)

    assert cb.answered
    emp = await repo_employees.get_by_chat_id(conn, uid)
    assert emp is not None
    assert emp["canonical_name"] == "Алексей"

    # Invite should be marked used
    rec = await repo_invites.find_valid_by_hash(conn, "fakehash")
    assert rec is None

    assert any("Привязка" in rep["text"] for rep in cb.message.replies)


@pytest.mark.asyncio
async def test_confirm_name_rebind_notifies_admins(conn, settings):
    """Rebind (name already bound to another chat): admin notification sent."""
    he._throttle.clear()

    await repo_employees.upsert_name(conn, "Светлана")
    await repo_employees.bind(conn, "Светлана", 111)  # old binding
    await conn.commit()

    expires = "2099-01-01T00:00:00.000Z"
    invite_id = await repo_invites.insert(conn, "Светлана", "rebindhash", expires)
    await conn.commit()

    new_uid = 999
    ctx = _make_fsm_ctx(new_uid)
    await ctx.set_state(EmployeeReg.ConfirmName)
    await ctx.update_data(invite_id=invite_id, canonical_name="Светлана")

    cb = FakeCallbackQuery(data="confirm_bind:yes", user_id=new_uid)
    bot = FakeBot()

    # settings has admin_chat_ids=(999,) — but new_uid=999 is also the admin
    # use a distinct admin id
    custom_settings = _make_settings(admin_chat_ids=(7777,))
    r = he.make_router(conn, custom_settings)
    confirm_name = _get_handler(r, "confirm_name")
    await confirm_name(cb, ctx, bot)

    # Admin should receive rebind notification
    admin_msgs = [c for c, _ in bot.sent if c == 7777]
    assert len(admin_msgs) == 1


# ── /me tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_bound_shows_name(conn, settings):
    """Bound user /me: shows canonical_name."""
    he._throttle.clear()

    await repo_employees.upsert_name(conn, "Пётр")
    await repo_employees.bind(conn, "Пётр", 1111)
    await conn.commit()

    r = he.make_router(conn, settings)
    msg = FakeMessage("/me", user_id=1111)
    cmd_me = _get_handler(r, "cmd_me")
    await cmd_me(msg)

    assert any("Пётр" in rep["text"] for rep in msg.replies)


@pytest.mark.asyncio
async def test_me_unbound_prompts_start(conn, settings):
    """Unbound user /me: prompt to use /start."""
    he._throttle.clear()

    r = he.make_router(conn, settings)
    msg = FakeMessage("/me", user_id=9999)
    cmd_me = _get_handler(r, "cmd_me")
    await cmd_me(msg)

    assert msg.replies
    assert any("/start" in rep["text"] for rep in msg.replies)


# ── helper ──────────────────────────────────────────────


def _get_handler(router, name: str):
    """Extract a named handler closure from the router observers."""
    # Walk through message and callback_query observers
    for obs_name in ("message", "callback_query"):
        obs = getattr(router, obs_name, None)
        if obs is None:
            continue
        for handler_obj in obs.handlers:
            fn = handler_obj.callback
            if fn.__name__ == name:
                return fn
    raise LookupError(f"Handler {name!r} not found in router")
