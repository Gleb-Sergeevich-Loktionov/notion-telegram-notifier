"""Telegram bot bootstrap: Bot/Dispatcher, setMyCommands, long-polling runner.

MemoryStorage is locked (CR-3).
"""

import logging

import aiosqlite
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from notify_bot.config import Settings
from notify_bot.telegram import handlers_admin, handlers_employee
from notify_bot.telegram.middleware import AdminFilter

log = logging.getLogger(__name__)

_EMPLOYEE_COMMANDS = [
    BotCommand(command="start", description="Привязать аккаунт"),
    BotCommand(command="me", description="Показать мою привязку"),
]

_ADMIN_COMMANDS = [
    BotCommand(command="invite", description="Создать код приглашения"),
    BotCommand(command="list", description="Список сотрудников"),
    BotCommand(command="rename", description="Переименовать сотрудника"),
    BotCommand(command="unbind", description="Снять привязку"),
    BotCommand(command="pause", description="Поставить рассылку на паузу"),
    BotCommand(command="resume", description="Возобновить рассылку"),
]


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    conn: aiosqlite.Connection,
    settings: Settings,
    notion_client=None,
) -> Dispatcher:
    """Build and configure the Dispatcher."""
    storage = MemoryStorage()  # CR-3: locked
    dp = Dispatcher(storage=storage)

    emp_router = handlers_employee.make_router(conn, settings)
    admin_router = handlers_admin.make_router(conn, settings, notion_client)
    admin_router.message.middleware(AdminFilter(settings.admin_chat_ids))

    dp.include_router(emp_router)
    dp.include_router(admin_router)

    return dp


async def run_bot(
    bot: Bot,
    dp: Dispatcher,
    settings: Settings,
) -> None:
    """Set commands then start long-polling. Runs until cancelled."""
    await bot.set_my_commands(_EMPLOYEE_COMMANDS)
    log.info("bot: starting long-polling")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        log.info("bot: session closed")
