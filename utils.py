# ═══════════════════════════════════════════════════════════════
# utils.py — УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════

import random
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from aiogram.types import Message

from config import (
    MAX_BALANCE, MAX_BANK, MAX_BET, MAX_WIN, MAX_BIGINT,
    MAX_BANK_INTEREST, BANK_INTEREST_RATE,
    TZ_MINSK,
)

# ═══════════════ БАЗОВЫЕ УТИЛИТЫ ═══════════════

def clamp(x, min_val=-MAX_BIGINT, max_val=MAX_BIGINT):
    """Ограничивает число в пределах BIGINT."""
    try:
        return max(min_val, min(int(x), max_val))
    except Exception:
        return 0


def clamp_balance(amount: int) -> tuple:
    """Ограничивает баланс до MAX_BALANCE."""
    amount = clamp(amount)
    if amount > MAX_BALANCE:
        return MAX_BALANCE, amount - MAX_BALANCE
    return amount, 0


def clamp_bank(amount: int) -> tuple:
    """Ограничивает банк до MAX_BANK."""
    amount = clamp(amount)
    if amount > MAX_BANK:
        return MAX_BANK, amount - MAX_BANK
    return amount, 0


def cap_win(amount: int) -> int:
    """Лимит стола: макс. выигрыш = MAX_WIN."""
    return min(clamp(amount), MAX_WIN)


def fmt_num(n) -> str:
    """Форматирует число с пробелами: 1 000 000."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def make_xp_bar(xp: int) -> str:
    """Прогресс-бар XP: ▰▰▰▱▱▱▱▱▱▱"""
    progress = xp % 100
    fill = int(progress / 100 * 10)
    return "▰" * fill + "▱" * (10 - fill)


def get_rank_name(level: int) -> str:
    """Ранг по уровню."""
    if level < 5:   return f"🥉 Бронза {['I','II','III'][min(level, 2)]}"
    if level < 10:  return "🥈 Серебро III"
    if level < 15:  return "🥈 Серебро II"
    if level < 20:  return "🥈 Серебро I"
    if level < 25:  return "🥇 Золото III"
    if level < 30:  return "🥇 Золото II"
    if level < 35:  return "🥇 Золото I"
    if level < 45:  return "💎 Платина"
    if level < 55:  return "💠 Бриллиант"
    return "🖤 Чёрная карта"


def fmt_time_left(seconds: int) -> str:
    """Форматирует время: 5ч 30мин."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}ч {m}мин"


# ═══════════════ АВТО-УДАЛЕНИЕ ═══════════════

async def _delete_later(msg: Message, delay: int):
    """Удаляет сообщение через N секунд."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def send_temp(bot, chat_id: int, text: str, delay: int = 120, **kwargs) -> Message:
    """Отправляет сообщение с авто-удалением."""
    msg = await bot.send_message(chat_id, text, **kwargs)
    asyncio.create_task(_delete_later(msg, delay))
    return msg


# ═══════════════ HTML УТИЛИТЫ ═══════════════

def strip_html(text: str) -> str:
    """Убирает HTML-теги."""
    import re
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', str(text))


def clean_alert(msg: str) -> str:
    """Очищает сообщение для alert."""
    return strip_html(msg).strip()