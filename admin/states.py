# ═══════════════════════════════════════════════════════════════
# admin/states.py — СОСТОЯНИЯ ДИАЛОГОВ
# ═══════════════════════════════════════════════════════════════

from aiogram.fsm.state import State, StatesGroup


class MuteStates(StatesGroup):
    """Состояния диалога мута."""
    username = State()  # ждёт username
    duration = State()  # ждёт время
    reason = State()    # ждёт причину


class WarnStates(StatesGroup):
    """Состояния диалога варна."""
    username = State()
    reason = State()


class BanStates(StatesGroup):
    """Состояния диалога бана."""
    username = State()
    duration = State()
    reason = State()


class ScanStates(StatesGroup):
    """Состояния диалога пробива."""
    username = State()


class GiveStates(StatesGroup):
    """Состояния диалога выдачи баланса."""
    username = State()
    amount = State()


class VipStates(StatesGroup):
    """Состояния диалога выдачи VIP."""
    username = State()
    level = State()
    days = State()