"""FSM states for employee self-registration flow (code-first, ADR-7).

MemoryStorage is locked (CR-3) — restart clears dialog state.
"""

from aiogram.fsm.state import State, StatesGroup


class EmployeeReg(StatesGroup):
    EnterCode = State()
    ConfirmName = State()
