"""Shared pytest configuration and fixtures.

Autouse fixture: reset module-level aiogram Router singletons before every
test so that handlers from one test cannot leak their `conn` closure into the
next test, and so that a Router is never re-attached to a second Dispatcher.
"""

import pytest
from aiogram import Router

from notify_bot.telegram import handlers_admin, handlers_employee


@pytest.fixture(autouse=True)
def _reset_module_routers():
    """Reset the module-level router in employee/admin handler modules."""
    handlers_employee.router = Router()
    handlers_admin.router = Router()
    yield
    handlers_employee.router = Router()
    handlers_admin.router = Router()
