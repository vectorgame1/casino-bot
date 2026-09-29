# ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 1/15 — ИМПОРТЫ, КОНСТАНТЫ, УТИЛИТЫ, КОНФИГ
# ═══════════════════════════════════════════════════════════════

import asyncio
import logging
import os
import threading
import random
import re
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2 import pool

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    BotCommand, BotCommandScopeDefault,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from flask import Flask, jsonify, request
from flask_cors import CORS


# ═══════════════════════════════════════════════════════════════
# КОНФИГ
# ═══════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 6403424348
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Ссылки
BOT_USERNAME = "gold1_casino_bot"
GROUP_URL = "https://t.me/+xrmEcGndccs5ZGFi"
EXCHANGE_CHAT_URL = "https://t.me/Tokenschange"
EXCHANGE_CHAT_ID = -1001234567890  # ← ЗАМЕНИ на реальный ID чата обмена
MINI_APP_URL = "https://thriving-lokum-1f7004.netlify.app"
TOURNAMENT_CHANNEL = "@TokenCasinoTournaments"

# Время по Минску (UTC+3)
TZ_MINSK = timezone(timedelta(hours=3))


# ═══════════════════════════════════════════════════════════════
# ЛИМИТЫ ЭКОНОМИКИ
# ═══════════════════════════════════════════════════════════════

MAX_BALANCE = 100_000_000           # 100M — макс. баланс
MAX_BANK = 100_000_000              # 100M — макс. банк
MAX_TOTAL = MAX_BALANCE + MAX_BANK  # 200M — макс. всего

MAX_BET = 100_000_000               # 100M — макс. ставка
MAX_WIN = 50_000_000                # 50M — лимит стола (макс. выигрыш)

MAX_BANK_INTEREST = 25_000_000      # 25M — лимит банка для процентов
BANK_INTEREST_RATE = 0.05           # 5% в день

MAX_BIGINT = 9_000_000_000_000_000_000  # Тех. лимит BIGINT


# ═══════════════════════════════════════════════════════════════
# ЛИМИТЫ СТАВОК ПО ИГРАМ
# ═══════════════════════════════════════════════════════════════

GAME_BET_LIMITS = {
    "roulette": 25_000_000,    # 25M
    "slots": 500_000,          # 500K
    "coin": 25_000_000,        # 25M
    "mines": 2_500_000,        # 2.5M
    "bj": 25_000_000,          # 25M
    "duel": 25_000_000,        # 25M
    "crash": 500_000,          # 500K
    "plinko": 500_000,         # 500K
}


# ═══════════════════════════════════════════════════════════════
# КРЕДИТЫ
# ═══════════════════════════════════════════════════════════════

CREDIT_MIN = 50_000                 # 50K
CREDIT_MAX = 500_000                # 500K
CREDIT_DAYS = 3                     # 3 дня
CREDIT_PERCENT = 0                  # 0%


# ═══════════════════════════════════════════════════════════════
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ═══════════════════════════════════════════════════════════════

REF_BONUS_REFERRER = 5_000          # Рефереру
REF_BONUS_REFERRED = 5_000          # Приглашённому
REF_COMMISSION_PERCENT = 5          # 5% с выигрышей реферала


# ═══════════════════════════════════════════════════════════════
# ЕЖЕДНЕВНЫЙ БОНУС
# ═══════════════════════════════════════════════════════════════

START_BONUS = 1_000
DAILY_BONUS = 5_000                

# ═══════════════════════════════════════════════════════════════
# РУЛЕТКА: ЧЕСТНЫЕ КОЭФФИЦИЕНТЫ (RTP ~95%)
# ═══════════════════════════════════════════════════════════════

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

ROULETTE_PAYOUTS = {
    # Простые (18 чисел)
    "red": 1.95,
    "black": 1.95,
    "even": 1.95,
    "odd": 1.95,
    "1-18": 1.95,
    "19-36": 1.95,
    # Средние (12 чисел)
    "dozen1": 2.9,
    "dozen2": 2.9,
    "dozen3": 2.9,
    "column1": 2.9,
    "column2": 2.9,
    "column3": 2.9,
    # Сложные
    "line": 5.8,      # 6 чисел
    "corner": 8.7,    # 4 числа
    "street": 11.7,   # 3 числа
    "split": 17.5,    # 2 числа
    "straight": 35.0, # 1 число
    # Зеро
    "zero": 35.0,
}


# ═══════════════════════════════════════════════════════════════
# СЛОТЫ: ЧЕСТНЫЕ КОЭФФИЦИЕНТЫ (RTP ~90%)
# ═══════════════════════════════════════════════════════════════

SLOT_SYMBOLS = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']

SLOT_PAYOUTS = {
    '🍒': 9.0,
    '🍋': 13.5,
    '🍊': 18.0,
    '🍇': 22.5,
    '💎': 45.0,
    '7️⃣': 90.0,
}

SLOT_TWO_MATCH = 1.8  # 2 совпадения


# ═══════════════════════════════════════════════════════════════
# МОНЕТКА
# ═══════════════════════════════════════════════════════════════

COIN_PAYOUT = 1.95


# ═══════════════════════════════════════════════════════════════
# МИНЫ (честная формула)
# ═══════════════════════════════════════════════════════════════

MINES_LEVELS = {
    "easy":   {"name": "🟢 Лёгкий",   "mines": 3,  "step": 0.15},
    "medium": {"name": "🟡 Средний",  "mines": 5,  "step": 0.25},
    "hard":   {"name": "🔴 Хардкор",  "mines": 10, "step": 0.50},
}

MINES_HOUSE_EDGE = 0.95  # RTP 95%


# ═══════════════════════════════════════════════════════════════
# НАЗВАНИЯ ИГР
# ═══════════════════════════════════════════════════════════════

GAME_NAMES = {
    "roulette": "🎡 Рулетка",
    "slots": "🎰 Слоты",
    "coin": "🪙 Монетка",
    "mines": "💣 Мины",
    "bj": "🃏 Блэкджек",
    "duel": "⚔️ Дуэль",
    "crash": "🚀 Crash",
    "plinko": "🎯 Plinko",
}


# ═══════════════════════════════════════════════════════════════
# VIP-ТИРЫ
# ═══════════════════════════════════════════════════════════════

DEFAULT_VIP_TIERS = [
    {"id": 1, "name": "Серебро",     "icon": "🥈", "stars": 25,  "cashback": 2,  "bonus": 5_000,   "duration_days": 20, "exclusive_games": 0},
    {"id": 2, "name": "Золото",      "icon": "🥇", "stars": 50,  "cashback": 4,  "bonus": 15_000,  "duration_days": 20, "exclusive_games": 1},
    {"id": 3, "name": "Платина",     "icon": "💎", "stars": 75,  "cashback": 6,  "bonus": 30_000,  "duration_days": 20, "exclusive_games": 3},
    {"id": 4, "name": "Бриллиант",   "icon": "💠", "stars": 100, "cashback": 8,  "bonus": 50_000,  "duration_days": 20, "exclusive_games": 99},
    {"id": 5, "name": "Чёрная карта", "icon": "🖤", "stars": 150, "cashback": 10, "bonus": 100_000, "duration_days": 20, "exclusive_games": 99},
]


# ═══════════════════════════════════════════════════════════════
# ТИТУЛЫ
# ═══════════════════════════════════════════════════════════════

DEFAULT_TITLES = [
    {"id": "newbie",     "name": "🥉 Новичок",    "condition": "games",       "value": 0},
    {"id": "player",     "name": "🥈 Игрок",      "condition": "games",       "value": 10},
    {"id": "pro",        "name": "🥇 Профи",      "condition": "games",       "value": 100},
    {"id": "highroller", "name": "💎 Хайроллер",  "condition": "max_bet",     "value": 1_000_000},
    {"id": "lucky",      "name": "🔥 Везунчик",   "condition": "win_streak",  "value": 10},
    {"id": "sniper",     "name": "⚡ Снайпер",     "condition": "wins",        "value": 100},
    {"id": "elite",      "name": "💠 Элита",      "condition": "max_win",     "value": 1_000_000},
    {"id": "legend",     "name": "👑 Легенда",    "condition": "max_win",     "value": 10_000_000},
    {"id": "shadow",     "name": "🖤 Тень",       "condition": "vip",         "value": 5},
    {"id": "whale",      "name": "🌟 Кит",        "condition": "top1",        "value": 1},
]


# ═══════════════════════════════════════════════════════════════
# XP-ПАКИ
# ═══════════════════════════════════════════════════════════════

DEFAULT_XP_PACKS = [
    {"id": "xp_100",  "xp": 100,  "stars": 5},
    {"id": "xp_500",  "xp": 500,  "stars": 20},
    {"id": "xp_1000", "xp": 1000, "stars": 35},
]


# ═══════════════════════════════════════════════════════════════
# ЕЖЕДНЕВНЫЕ ЗАДАНИЯ
# ═══════════════════════════════════════════════════════════════

DEFAULT_DAILY_QUESTS = [
    {"key": "daily_bets_5",  "name": "🎰 Сделать 5 ставок",  "target": 5, "reward": 100},
    {"key": "daily_win_1",   "name": "🎲 Выиграть 1 раз",    "target": 1, "reward": 200},
    {"key": "daily_ref_1",   "name": "👥 Пригласить друга",  "target": 1, "reward": 500},
    {"key": "daily_buy_vip", "name": "⭐ Купить VIP",         "target": 1, "reward": 1000},
]


# ═══════════════════════════════════════════════════════════════
# НАГРАДЫ ЗА УРОВНИ
# ═══════════════════════════════════════════════════════════════

DEFAULT_LEVEL_REWARDS = [
    {"level": 5,  "type": "tokens",    "value": 500},
    {"level": 10, "type": "cashback",  "value": 2},
    {"level": 20, "type": "vip_games", "value": 1},
    {"level": 30, "type": "tokens",    "value": 5000},
    {"level": 50, "type": "vip_tier",  "value": 1},
]


# ═══════════════════════════════════════════════════════════════
# АНИМАЦИИ
# ═══════════════════════════════════════════════════════════════

ANIM_ROULETTE = [
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴",
    "🔴",
]
ANIM_ROULETTE_DELAYS = [0.15, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

ANIM_COIN = ["🦅", "👑", "🦅", "👑", "🦅", "👑"]
ANIM_COIN_DELAYS = [0.20, 0.20, 0.25, 0.25, 0.30, 0.35]

ANIM_DUEL = ["⚔️", "🔴 ⚔️ 🔵", "🔴 💥 🔵", "🔵 💥 🔴", "🔴 ⚔️ 🔵", "💥 БАХ!"]
ANIM_DUEL_DELAYS = [0.25, 0.25, 0.30, 0.30, 0.35, 0.40]


# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ═══════════════════════════════════════════════════════════════

active_bets = {}          # {chat_id: {"bets": [...]}}
bj_games = {}             # {user_id: {...}}
duel_games = {}           # {chat_id: {...}}
mines_games = {}          # {user_id: {...}}
disabled_games = set()    # {"slots", "mines", ...}
giveaway_timers = {}

edit_state = {}
edit_case_state = {}
edit_shop_state = {}
edit_tokens_state = {}
edit_vip_state = {}
edit_xp_state = {}
edit_quest_state = {}
edit_level_state = {}
bank_input_state = {}
admin_action_state = {}
credit_input_state = {}    # ← НОВОЕ: ввод суммы кредита
rates_input_state = {}     # ← НОВОЕ: ввод курсов
birthday_input_state = {}
lang_state = {}

event_double = False
maintenance_on = False
jackpot_amount = 10_000


# ═══════════════════════════════════════════════════════════════
# КЭШ
# ═══════════════════════════════════════════════════════════════

_cache = {}


def cache_get(key: str, ttl: int = 30):
    if key in _cache:
        val, exp = _cache[key]
        if time.time() < exp:
            return val
    return None


def cache_set(key: str, value, ttl: int = 30):
    _cache[key] = (value, time.time() + ttl)


def cache_invalidate(prefix: str = None):
    if prefix is None:
        _cache.clear()
    else:
        keys = [k for k in _cache.keys() if k.startswith(prefix)]
        for k in keys:
            _cache.pop(k, None)


# ═══════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════

def clamp(x, min_val=-MAX_BIGINT, max_val=MAX_BIGINT):
    """Ограничивает число в пределах BIGINT."""
    try:
        return max(min_val, min(int(x), max_val))
    except Exception:
        return 0


def clamp_balance(amount: int) -> tuple:
    """Ограничивает баланс до MAX_BALANCE. Возвращает (сумма, излишек)."""
    amount = clamp(amount)
    if amount > MAX_BALANCE:
        return MAX_BALANCE, amount - MAX_BALANCE
    return amount, 0


def clamp_bank(amount: int) -> tuple:
    """Ограничивает банк до MAX_BANK. Возвращает (сумма, излишек)."""
    amount = clamp(amount)
    if amount > MAX_BANK:
        return MAX_BANK, amount - MAX_BANK
    return amount, 0


def cap_win(amount: int) -> int:
    """Лимит стола: макс. выигрыш за раунд = MAX_WIN (50M)."""
    return min(clamp(amount), MAX_WIN)


def get_event_mult() -> int:
    """Множитель ивента ×2 (если включён)."""
    return 2 if event_double else 1


def fmt_num(n) -> str:
    """Форматирует число с пробелами: 1 000 000."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def fmt_balance(user_id: int, balance: int) -> str:
    """Красивое отображение баланса (с учётом безлимита)."""
    if is_unlimited(user_id):
        return "♾️ БЕЗЛИМИТ"
    return f"{fmt_num(balance)} Tokens"


def get_roulette_color(number: int) -> str:
    """Возвращает цвет числа: 🔴/⚫/🟢."""
    if number == 0:
        return "🟢"
    if number in RED_NUMBERS:
        return "🔴"
    return "⚫"


def calc_roulette_win(bet_type: str, amount: int) -> int:
    """Считает выигрыш по типу ставки."""
    mult = ROULETTE_PAYOUTS.get(bet_type, 0)
    if mult == 0:
        return 0
    return clamp(int(amount * mult))


def calc_range_mult(a: int, z: int) -> float:
    """
    Множитель зависит от размера диапазона.
    Чем уже диапазон — тем выше икс.
    """
    count = z - a + 1
    if count >= 18: return 1.95
    if count >= 12: return 2.9
    if count >= 6:  return 5.8
    if count >= 4:  return 8.7
    if count >= 3:  return 11.7
    if count >= 2:  return 17.5
    return 35.0


def calc_best_range_mult(ranges: list, result: int) -> float:
    """
    Берёт САМЫЙ УЗКИЙ диапазон, в который попало число.
    Кап ×35. Абуз невозможен.
    """
    best_mult = 0
    best_size = 999
    for (a, z) in ranges:
        if a <= result <= z:
            size = z - a + 1
            if size < best_size:
                best_size = size
                best_mult = calc_range_mult(a, z)
    return best_mult


def calc_mines_mult(total_cells: int, mines: int, opened: int) -> float:
    """Честный множитель для мин."""
    if opened == 0:
        return 1.0
    safe = total_cells - mines
    opened_safe = opened
    if opened_safe >= safe:
        # Все безопасные открыты
        from math import comb
        # Полный множитель
        return round(0.95 * (comb(total_cells, opened_safe) / comb(safe, opened_safe)), 2) if comb(safe, opened_safe) else 1.0
    fair = safe / (total_cells - opened)
    return round(fair * MINES_HOUSE_EDGE, 2)


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


# ═══════════════════════════════════════════════════════════════
# СЛУЖЕБНЫЕ СООБЩЕНИЯ С АВТО-УДАЛЕНИЕМ (2 минуты)
# ═══════════════════════════════════════════════════════════════

async def _delete_later(msg: Message, delay: int):
    """Удаляет сообщение через N секунд."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def send_temp(chat_id: int, text: str, delay: int = 120, **kwargs) -> Message:
    """Отправляет сообщение с авто-удалением через N секунд (по умолчанию 2 мин)."""
    msg = await bot.send_message(chat_id, text, **kwargs)
    asyncio.create_task(_delete_later(msg, delay))
    return msg


def get_event_multiplier():
    return 2 if event_double else 1


# ═══════════════════════════════════════════════════════════════
# СПИСОК КОМАНД (для BotFather + кнопки «Все команды»)
# ═══════════════════════════════════════════════════════════════

ALL_BOT_COMMANDS = {
    "🎮 Игровые (группа)": [
        ("к [сумма]", "Ставка на красное"),
        ("ч [сумма]", "Ставка на чёрное"),
        ("з [сумма]", "Ставка на зеро"),
        ("го", "Запустить рулетку"),
        ("спин [сумма]", "Слоты"),
        ("орёл [сумма]", "Монетка — орёл"),
        ("решка [сумма]", "Монетка — решка"),
        ("бж [сумма]", "Блэкджек"),
        ("мины [сумма]", "Мины"),
        ("дуэль [сумма] @user", "Вызвать на дуэль"),
        ("принять", "Принять дуэль"),
        ("банк", "Открыть банк"),
        ("банк положить [сумма]", "Положить в банк"),
        ("банк снять [сумма]", "Снять из банка"),
        ("п [сумма]", "Перевести (reply)"),
        ("лог", "История рулетки"),
        ("отмена", "Отменить ставки"),
        ("б", "Баланс"),
        ("топ", "Топ игроков"),
        ("профиль", "Профиль"),
        ("задания", "Ежедневные задания"),
    ],
    "👤 Личные (ЛС)": [
        ("/start", "Запуск бота"),
        ("/profile", "Профиль"),
        ("/balance", "Баланс"),
        ("/top", "Топ"),
        ("/shop", "Магазин"),
        ("/market", "Рынок"),
        ("/vip", "VIP"),
        ("/xp", "Буст XP"),
        ("/quests", "Задания"),
        ("/ref", "Рефералка"),
        ("/lang", "Язык"),
    ],
    "👑 Админские": [
        ("/admin", "Админ-панель"),
        ("/give @user [сумма]", "Выдать"),
        ("/ban @user", "Забанить"),
        ("/unban @user", "Разбанить"),
        ("/reset_all", "Обнулить всех"),
        ("/edit_user @user", "Управление игроком"),
        ("/games on/off [игра]", "Управление играми"),
        ("/games_list", "Список игр"),
        ("/refs", "Мои рефералы"),
        ("/ref_top", "Топ рефереров"),
        ("/set_rates", "Обновить курсы"),
        ("/event double on/off", "Ивент ×2"),
        ("/maintenance on/off", "Тех. работы"),
    ],
}
# ═══════════════ HTML STRIP (для alert'ов) ═══════════════

def strip_html(text: str) -> str:
    """Убирает HTML-теги. Для alert'ов (Telegram не поддерживает HTML в alert)."""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', str(text))


def clean_alert(msg: str) -> str:
    """Очищает сообщение для alert."""
    return strip_html(msg).strip()


# ═══════════════════════════════════════════════════════════════
# ЛОГГЕР
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger(__name__)
# ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 2/15 — ПУЛ СОЕДИНЕНИЙ, INIT_DB, CRUD
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ПУЛ СОЕДИНЕНИЙ ═══════════════
_db_pool = None


def init_pool():
    """Создаёт пул соединений с Supabase."""
    global _db_pool
    try:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=DATABASE_URL,
            sslmode='require',
        )
        print("✅ Connection pool создан (2-20)")
    except Exception as e:
        print(f"⚠️ Пул не создан, fallback: {e}")
        _db_pool = None


def get_conn():
    """Берёт соединение из пула."""
    if _db_pool:
        return _db_pool.getconn()
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def release_conn(conn):
    """Возвращает соединение в пул."""
    if _db_pool:
        _db_pool.putconn(conn)
    else:
        conn.close()


def get_db():
    return get_conn()


# ═══════════════ ИНИЦИАЛИЗАЦИЯ БД ═══════════════
def init_db():
    """Создаёт все таблицы и индексы."""
    conn = get_conn()
    c = conn.cursor()

    # ═══════════════ ОСНОВНЫЕ ТАБЛИЦЫ ═══════════════

    # USERS
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        balance BIGINT DEFAULT 1000,
        bank BIGINT DEFAULT 0,
        banned BOOLEAN DEFAULT FALSE,
        unlimited BOOLEAN DEFAULT FALSE,
        got_start_bonus BOOLEAN DEFAULT FALSE,
        xp BIGINT DEFAULT 0,
        vip_level INT DEFAULT 0,
        total_lost BIGINT DEFAULT 0,
        total_won BIGINT DEFAULT 0
    )""")

    # GAME_LOG
    c.execute("""CREATE TABLE IF NOT EXISTS game_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        game TEXT,
        bet BIGINT,
        win BIGINT,
        detail TEXT,
        time TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    # QUESTS (старые)
    c.execute("""CREATE TABLE IF NOT EXISTS quests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        quest_key TEXT NOT NULL,
        progress BIGINT DEFAULT 0,
        target BIGINT DEFAULT 1,
        completed BOOLEAN DEFAULT FALSE,
        claimed BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, quest_key)
    )""")

    # ACHIEVEMENTS
    c.execute("""CREATE TABLE IF NOT EXISTS achievements (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        achievement_key TEXT NOT NULL,
        unlocked BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, achievement_key)
    )""")

    # SETTINGS
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # TITLES
    c.execute("""CREATE TABLE IF NOT EXISTS titles (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        granted_by BIGINT,
        granted_at TIMESTAMP DEFAULT NOW()
    )""")

    # GIVEAWAYS
    c.execute("""CREATE TABLE IF NOT EXISTS giveaways (
        id SERIAL PRIMARY KEY,
        amount BIGINT,
        ends_at TIMESTAMP,
        created_by BIGINT,
        status TEXT DEFAULT 'active',
        winner_id BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    # GROUP_MEMBERS
    c.execute("""CREATE TABLE IF NOT EXISTS group_members (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,
        user_id BIGINT,
        username TEXT,
        last_seen TIMESTAMP DEFAULT NOW(),
        UNIQUE(chat_id, user_id)
    )""")

    # BOOSTS
    c.execute("""CREATE TABLE IF NOT EXISTS boosts (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        mult INT,
        until TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    # ═══════════════ НОВЫЕ ТАБЛИЦЫ ═══════════════

    # PURCHASE_LOG
    c.execute("""CREATE TABLE IF NOT EXISTS purchase_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        purchase_type TEXT,
        item_name TEXT,
        price TEXT,
        source TEXT,
        extra TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    # DAILY_QUESTS (новые)
    c.execute("""CREATE TABLE IF NOT EXISTS daily_quests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        quest_key TEXT NOT NULL,
        progress BIGINT DEFAULT 0,
        claimed BOOLEAN DEFAULT FALSE,
        reset_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, quest_key)
    )""")

    # LEVEL_REWARDS_CLAIMED
    c.execute("""CREATE TABLE IF NOT EXISTS level_rewards_claimed (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        level INT NOT NULL,
        claimed_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, level)
    )""")

    # TOURNAMENTS
    c.execute("""CREATE TABLE IF NOT EXISTS tournaments (
        id SERIAL PRIMARY KEY,
        name TEXT,
        started_at TIMESTAMP DEFAULT NOW(),
        ends_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        prize_1 BIGINT DEFAULT 10000,
        prize_2 BIGINT DEFAULT 5000,
        prize_3 BIGINT DEFAULT 2000,
        winner_1 BIGINT,
        winner_2 BIGINT,
        winner_3 BIGINT
    )""")

    # TOURNAMENT_SCORES
    c.execute("""CREATE TABLE IF NOT EXISTS tournament_scores (
        id SERIAL PRIMARY KEY,
        tournament_id INT,
        user_id BIGINT,
        username TEXT,
        total_won BIGINT DEFAULT 0,
        UNIQUE(tournament_id, user_id)
    )""")

    # DAILY_CASHBACK
    c.execute("""CREATE TABLE IF NOT EXISTS daily_cashback (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount BIGINT,
        date DATE DEFAULT CURRENT_DATE,
        paid_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, date)
    )""")

    # ACTIVE_VIP
    c.execute("""CREATE TABLE IF NOT EXISTS active_vip (
        user_id BIGINT PRIMARY KEY,
        tier INT DEFAULT 0,
        expires_at TIMESTAMP,
        purchased_at TIMESTAMP DEFAULT NOW()
    )""")

    # ═══════════════ КРЕДИТЫ ═══════════════
    c.execute("""CREATE TABLE IF NOT EXISTS credits (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        amount BIGINT NOT NULL,
        issued_at TIMESTAMP DEFAULT NOW(),
        due_at TIMESTAMP NOT NULL,
        returned_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        reminded BOOLEAN DEFAULT FALSE
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credits_user ON credits(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credits_status ON credits(status, due_at)")

    # ═══════════════ CRASH ═══════════════
    c.execute("""CREATE TABLE IF NOT EXISTS crash_rounds (
        id SERIAL PRIMARY KEY,
        crash_point DECIMAL(10,2),
        started_at TIMESTAMP DEFAULT NOW(),
        crashed_at TIMESTAMP,
        status TEXT DEFAULT 'waiting'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS crash_bets (
        id SERIAL PRIMARY KEY,
        round_id INT,
        user_id BIGINT,
        username TEXT,
        bet BIGINT,
        auto_cashout DECIMAL(10,2),
        cashed_out_at DECIMAL(10,2),
        won BIGINT DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crash_bets_round ON crash_bets(round_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crash_bets_user ON crash_bets(user_id)")

    # ═══════════════ PLINKO ═══════════════
    c.execute("""CREATE TABLE IF NOT EXISTS plinko_history (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        bet BIGINT,
        risk TEXT,
        position INT,
        multiplier DECIMAL(10,2),
        won BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_plinko_user ON plinko_history(user_id)")

    # ═══════════════ ALTER users (доп. колонки) ═══════════════
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_last_claim TIMESTAMP")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS inventory JSONB DEFAULT '[]'::jsonb")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_earnings BIGINT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_count INT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday TEXT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'ru'")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date DATE")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS win_streak INT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_blocked BOOLEAN DEFAULT FALSE")

    # ═══════════════ ИНДЕКСЫ ═══════════════
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_game ON game_log(game)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_created ON game_log(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_boosts_user ON boosts(user_id, until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_group_members_chat ON group_members(chat_id, user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_log_created ON purchase_log(created_at DESC)")

    conn.commit()
    c.close()
    release_conn(conn)
    print("✅ БД инициализирована + все таблицы + индексы")


# ═══════════════════════════════════════════════════════════════
# CRUD: USERS
# ═══════════════════════════════════════════════════════════════

def get_user(user_id: int):
    """Возвращает (username, balance) или None."""
    cache_key = f"user_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    cache_set(cache_key, row, ttl=10)
    return row


def get_user_id_by_username(username: str):
    """Ищет ID по @username."""
    if username.startswith('@'):
        username = username[1:]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else None


def ensure_user(user_id: int, username: str):
    """Создаёт юзера, если его нет. Обновляет username."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, username) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET username = %s",
        (user_id, username, username)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")


def get_balance(user_id: int) -> int:
    """Баланс игрока."""
    user = get_user(user_id)
    return user[1] if user else 1000


def set_balance(user_id: int, amount: int) -> int:
    """Изменяет баланс на amount. Возвращает новый баланс."""
    amount = clamp(amount)

    # Безлимит: не списываем
    if is_unlimited(user_id) and amount < 0:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        return row[0] if row else 0

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, 1000) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_balance = row[0] if row else 0

    # Ограничение баланса
    if new_balance > MAX_BALANCE:
        overflow = new_balance - MAX_BALANCE
        c.execute(
            "UPDATE users SET balance = %s, bank = LEAST(bank + %s, %s) WHERE user_id = %s",
            (MAX_BALANCE, overflow, MAX_BANK, user_id)
        )
        new_balance = MAX_BALANCE
    elif new_balance < 0:
        c.execute("UPDATE users SET balance = 0 WHERE user_id = %s", (user_id,))
        new_balance = 0

    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return new_balance


def set_balance_exact(user_id: int, amount: int) -> int:
    """Устанавливает точный баланс."""
    amount, overflow = clamp_balance(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, balance) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET balance = %s",
        (user_id, amount, amount)
    )
    if overflow > 0:
        c.execute("UPDATE users SET bank = LEAST(bank + %s, %s) WHERE user_id = %s",
                  (overflow, MAX_BANK, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return amount


# ═══════════════ БАНК ═══════════════

def get_bank(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row and row[0] else 0


def set_bank(user_id: int, amount: int) -> int:
    """Изменяет банк. Возвращает новый банк."""
    amount = clamp(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, bank) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_bank = row[0] if row else 0

    if new_bank > MAX_BANK:
        c.execute("UPDATE users SET bank = %s WHERE user_id = %s", (MAX_BANK, user_id))
        new_bank = MAX_BANK
    elif new_bank < 0:
        c.execute("UPDATE users SET bank = 0 WHERE user_id = %s", (user_id,))
        new_bank = 0

    conn.commit()
    c.close()
    release_conn(conn)
    return new_bank


# ═══════════════ БАН / БЕЗЛИМИТ ═══════════════

def is_banned(user_id: int) -> bool:
    cache_key = f"banned_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = bool(row[0]) if row and row[0] else False
    cache_set(cache_key, val, ttl=15)
    return val


def set_banned(user_id: int, banned: bool = True):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, banned) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET banned = %s",
        (user_id, banned, banned)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"banned_{user_id}")


def is_unlimited(user_id: int) -> bool:
    cache_key = f"unl_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT unlimited FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = bool(row[0]) if row and row[0] else False
    cache_set(cache_key, val, ttl=15)
    return val


def set_unlimited(user_id: int, unlimited: bool = True):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, unlimited) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET unlimited = %s",
        (user_id, unlimited, unlimited)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"unl_{user_id}")


# ═══════════════ XP ═══════════════

def get_xp(user_id: int) -> int:
    cache_key = f"xp_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = row[0] if row else 0
    cache_set(cache_key, val, ttl=10)
    return val


def add_xp(user_id: int, amount: int) -> tuple:
    """Начисляет XP. Возвращает (new_xp, level_changed, new_level)."""
    if amount <= 0:
        return get_xp(user_id), False, 0
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    old_xp = c.fetchone()[0] or 0
    old_level = old_xp // 100
    c.execute("UPDATE users SET xp = xp + %s WHERE user_id = %s", (amount, user_id))
    new_xp = old_xp + amount
    new_level = new_xp // 100
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{user_id}")
    cache_invalidate(f"user_{user_id}")
    return new_xp, (new_level > old_level), new_level


# ═══════════════ СТАТИСТИКА ═══════════════

def get_user_stats(user_id: int) -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (user_id,))
    total_games = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (user_id,))
    total_wins = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(bet), 0) FROM game_log WHERE user_id = %s", (user_id,))
    total_bet = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(win), 0) FROM game_log WHERE user_id = %s", (user_id,))
    total_win = c.fetchone()[0]
    c.execute("SELECT COALESCE(MAX(win), 0) FROM game_log WHERE user_id = %s", (user_id,))
    best_win = c.fetchone()[0]
    c.execute("""SELECT game, COUNT(*) as cnt FROM game_log
                 WHERE user_id = %s GROUP BY game ORDER BY cnt DESC LIMIT 1""", (user_id,))
    fav = c.fetchone()
    c.close()
    release_conn(conn)
    return {
        "total_games": total_games,
        "total_wins": total_wins,
        "total_bet": total_bet,
        "total_win": total_win,
        "profit": total_win - total_bet,
        "best_win": best_win,
        "fav_game": fav[0] if fav else "—",
        "winrate": round(total_wins / total_games * 100) if total_games > 0 else 0,
    }


# ═══════════════ ЛОГИ ═══════════════

def log_game(user_id: int, username: str, game: str, bet: int, win: int, detail: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO game_log (user_id, username, game, bet, win, detail, time)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)""",
              (user_id, username, game, clamp(bet), clamp(win), detail,
               datetime.now(TZ_MINSK).strftime("%H:%M:%S")))
    if win > 0:
        c.execute("UPDATE users SET total_won = total_won + %s WHERE user_id = %s", (win, user_id))
    else:
        c.execute("UPDATE users SET total_lost = total_lost + %s WHERE user_id = %s", (bet, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("top_balance")
    cache_invalidate("top_xp")
    if win > 0:
        update_tournament_score(user_id, username, win)


def get_last_roulette_results(limit: int = 10, chat_id: int = None):
    """Последние N результатов рулетки."""
    conn = get_conn()
    c = conn.cursor()
    if chat_id is not None:
        c.execute("""
            SELECT g.detail FROM game_log g
            JOIN group_members gm ON gm.user_id = g.user_id
            WHERE g.game='рулетка' AND gm.chat_id = %s
            ORDER BY g.id DESC LIMIT %s
        """, (chat_id, limit))
    else:
        c.execute("SELECT detail FROM game_log WHERE game='рулетка' ORDER BY id DESC LIMIT %s",
                  (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_user_history(user_id: int, game: str = None, limit: int = 15):
    conn = get_conn()
    c = conn.cursor()
    if game:
        c.execute("""SELECT game, bet, win, detail, time FROM game_log
                     WHERE user_id = %s AND game = %s ORDER BY id DESC LIMIT %s""",
                  (user_id, game, limit))
    else:
        c.execute("""SELECT game, bet, win, detail, time FROM game_log
                     WHERE user_id = %s ORDER BY id DESC LIMIT %s""",
                  (user_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_big_wins(limit: int = 10, min_win: int = 100_000):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT username, game, win, time FROM game_log
                 WHERE win >= %s ORDER BY win DESC LIMIT %s""", (min_win, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_recent_users(minutes: int = 5, limit: int = 20):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT DISTINCT u.user_id, u.username, u.balance
                 FROM users u
                 JOIN game_log g ON u.user_id = g.user_id
                 WHERE g.created_at > NOW() - INTERVAL '%s minutes'
                 ORDER BY u.balance DESC LIMIT %s""", (minutes, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


# ═══════════════ ТОПЫ ═══════════════

def get_top(limit: int = 10):
    cached = cache_get("top_balance", ttl=30)
    if cached is not None:
        return cached[:limit]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY balance DESC LIMIT 50")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    cache_set("top_balance", rows, ttl=30)
    return rows[:limit]


def get_top_xp(limit: int = 10):
    cached = cache_get("top_xp", ttl=30)
    if cached is not None:
        return cached[:limit]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY xp DESC LIMIT 50")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    cache_set("top_xp", rows, ttl=30)
    return rows[:limit]


def get_top_games(limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.balance, u.xp, COUNT(g.id) as games
        FROM users u
        LEFT JOIN game_log g ON u.user_id = g.user_id
        GROUP BY u.user_id, u.username, u.balance, u.xp
        ORDER BY games DESC LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_top_wins(limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.balance, u.xp, COUNT(g.id) as wins
        FROM users u
        LEFT JOIN game_log g ON u.user_id = g.user_id AND g.win > 0
        GROUP BY u.user_id, u.username, u.balance, u.xp
        ORDER BY wins DESC LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned = FALSE")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return [r[0] for r in rows]


def get_total_players() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else 0


# ═══════════════ ГРУППЫ ═══════════════

def track_group_member(chat_id: int, user_id: int, username: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO group_members (chat_id, user_id, username, last_seen)
                 VALUES (%s, %s, %s, NOW())
                 ON CONFLICT (chat_id, user_id) DO UPDATE
                 SET username = %s, last_seen = NOW()""",
              (chat_id, user_id, username, username))
    conn.commit()
    c.close()
    release_conn(conn)


def get_group_members(chat_id: int, limit: int = 100):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username FROM group_members
                 WHERE chat_id = %s ORDER BY last_seen DESC LIMIT %s""",
              (chat_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


# ═══════════════ БУСТЫ ═══════════════

def get_active_boost(user_id: int):
    cache_key = f"boost_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached if cached != "none" else None
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT mult, until FROM boosts
                 WHERE user_id = %s AND until > NOW()
                 ORDER BY mult DESC LIMIT 1""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    cache_set(cache_key, row if row else "none", ttl=10)
    return row


def add_boost(user_id: int, mult: int, minutes: int):
    until = datetime.now(TZ_MINSK) + timedelta(minutes=minutes)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO boosts (user_id, mult, until) VALUES (%s, %s, %s)",
              (user_id, mult, until))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"boost_{user_id}")
    return until


def get_user_mult(user_id: int) -> int:
    boost = get_active_boost(user_id)
    return boost[0] if boost else 1


# ═══════════════ НАСТРОЙКИ (settings) ═══════════════

def get_setting(key: str, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else default


def set_setting(key: str, value: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO settings (key, value) VALUES (%s, %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""",
              (key, value, value))
    conn.commit()
    c.close()
    release_conn(conn)


# ═══════════════ DISABLED GAMES ═══════════════

def get_disabled_games() -> set:
    val = get_setting("disabled_games", "")
    return set(val.split(',')) if val else set()


def save_disabled_games():
    set_setting("disabled_games", ','.join(disabled_games))


def is_game_disabled(game: str) -> bool:
    return game in disabled_games


def load_settings():
    global disabled_games
    disabled_games = get_disabled_games()
    print(f"✅ Настройки: disabled_games = {disabled_games}")
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 3/15 — VIP, ТИТУЛЫ, РЕФЕРАЛКА, БОНУС, STREAK
# ═══════════════════════════════════════════════════════════════

# ═══════════════ VIP ═══════════════

def get_vip_tier(user_id: int) -> int:
    """Активный VIP-тир (0 если нет/истёк)."""
    cache_key = f"vip_tier_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT tier FROM active_vip WHERE user_id = %s AND expires_at > NOW()", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = row[0] if row else 0
    cache_set(cache_key, val, ttl=15)
    return val


def get_vip_expires(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM active_vip WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else None


def set_vip_tier(user_id: int, tier: int, days: int = 20):
    """Устанавливает VIP. tier=0 — убрать."""
    if tier == 0:
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM active_vip WHERE user_id = %s", (user_id,))
        conn.commit()
        c.close()
        release_conn(conn)
        cache_invalidate(f"vip_tier_{user_id}")
        return

    expires = datetime.now(TZ_MINSK) + timedelta(days=days)
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO active_vip (user_id, tier, expires_at, purchased_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            tier = EXCLUDED.tier,
            expires_at = EXCLUDED.expires_at,
            purchased_at = NOW()
    """, (user_id, tier, expires))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"vip_tier_{user_id}")


def get_vip_tier_info(tier_id: int):
    """Информация о тире по id."""
    if tier_id < 1 or tier_id > 5:
        return None
    tiers = get_vip_tiers()
    for t in tiers:
        if t["id"] == tier_id:
            return t
    return None


def get_vip_tiers() -> list:
    """Все VIP-тиры (из настроек или дефолтные)."""
    cached = cache_get("vip_tiers", ttl=30)
    if cached is not None:
        return cached
    val = get_setting("vip_tiers")
    if val:
        try:
            tiers = json.loads(val)
            if isinstance(tiers, list) and tiers:
                cache_set("vip_tiers", tiers, ttl=30)
                return tiers
        except Exception:
            pass
    default = [dict(t) for t in DEFAULT_VIP_TIERS]
    cache_set("vip_tiers", default, ttl=30)
    return default


def save_vip_tiers(tiers: list):
    set_setting("vip_tiers", json.dumps(tiers, ensure_ascii=False))
    cache_invalidate("vip_tiers")


def get_user_cashback_percent(user_id: int) -> int:
    """Кэшбэк % (базовый 5% + VIP)."""
    base = 5
    tier = get_vip_tier(user_id)
    if tier > 0:
        info = get_vip_tier_info(tier)
        if info:
            base += info.get("cashback", 0)
    return base


# ═══════════════ ТИТУЛЫ ═══════════════

def add_title(user_id: int, title: str, granted_by: int = 0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO titles (user_id, title, granted_by) VALUES (%s, %s, %s)",
              (user_id, title, granted_by))
    conn.commit()
    c.close()
    release_conn(conn)


def get_user_titles(user_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT title FROM titles WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return [r[0] for r in rows]


def get_main_title(user_id: int) -> str:
    titles = get_user_titles(user_id)
    return titles[0] if titles else ""


def clear_user_titles(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)


def check_titles(user_id: int, username: str) -> list:
    """Проверяет и выдаёт новые титулы по достижениям."""
    try:
        stats = get_user_stats(user_id)
        games = stats["total_games"]
        wins = stats["total_wins"]
        max_win = stats["best_win"]

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(bet), 0) FROM game_log WHERE user_id = %s", (user_id,))
        max_bet = c.fetchone()[0]
        c.close()
        release_conn(conn)

        vip_tier = get_vip_tier(user_id)
        earned = []
        user_titles = get_user_titles(user_id)

        for t in DEFAULT_TITLES:
            if t["name"] in user_titles:
                continue
            cond = t["condition"]
            val = t["value"]
            ok = False
            if cond == "games" and games >= val:
                ok = True
            elif cond == "wins" and wins >= val:
                ok = True
            elif cond == "max_bet" and max_bet >= val:
                ok = True
            elif cond == "max_win" and max_win >= val:
                ok = True
            elif cond == "vip" and vip_tier >= val:
                ok = True
            if ok:
                add_title(user_id, t["name"], 0)
                earned.append(t["name"])
        return earned
    except Exception as e:
        print(f"[check_titles] {e}")
        return []


# ═══════════════ РЕФЕРАЛКА ═══════════════

def set_referrer(user_id: int, referrer_id: int) -> bool:
    """Привязывает юзера к рефереру. Возвращает True если привязал."""
    if user_id == referrer_id:
        return False
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        c.close()
        release_conn(conn)
        return False
    c.execute("UPDATE users SET referrer_id = %s WHERE user_id = %s", (referrer_id, user_id))
    c.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = %s", (referrer_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    # Бонусы
    set_balance(user_id, REF_BONUS_REFERRED)
    set_balance(referrer_id, REF_BONUS_REFERRER)
    add_ref_earnings(referrer_id, REF_BONUS_REFERRER)
    return True


def get_referrals(user_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users WHERE referrer_id = %s", (user_id,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_ref_stats(user_id: int) -> tuple:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(ref_count, 0), COALESCE(ref_earnings, 0) FROM users WHERE user_id = %s",
              (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return (row[0], row[1]) if row else (0, 0)


def add_ref_earnings(user_id: int, amount: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET ref_earnings = ref_earnings + %s WHERE user_id = %s",
              (amount, user_id))
    conn.commit()
    c.close()
    release_conn(conn)


def get_ref_top(limit: int = 10) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, ref_count, ref_earnings
                 FROM users WHERE ref_count > 0
                 ORDER BY ref_count DESC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def pay_ref_commission(user_id: int, win_amount: int):
    """Начисляет % с выигрыша реферала его рефереру."""
    if win_amount <= 0:
        return
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        if not row or not row[0]:
            return
        ref = row[0]
        amt = int(win_amount * REF_COMMISSION_PERCENT / 100)
        if amt > 0:
            set_balance(ref, amt)
            add_ref_earnings(ref, amt)
    except Exception as e:
        print(f"[pay_ref_commission] {e}")


# ═══════════════ ЕЖЕДНЕВНЫЙ БОНУС ═══════════════

def get_daily_status(user_id: int) -> tuple:
    """Возвращает (можно_забрать, секунд_осталось)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT daily_last_claim FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if not row or not row[0]:
        return True, 0
    last = row[0]
    # Если last с naive timezone — приводим к TZ
    now = datetime.now(TZ_MINSK)
    if last.tzinfo is None:
        last = last.replace(tzinfo=TZ_MINSK)
    delta = now - last
    if delta >= timedelta(hours=24):
        return True, 0
    left = int((timedelta(hours=24) - delta).total_seconds())
    return False, left


def claim_daily(user_id: int) -> bool:
    can, _ = get_daily_status(user_id)
    if not can:
        return False
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET daily_last_claim = NOW() WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    set_balance(user_id, DAILY_BONUS)
    update_daily_quest(user_id, "daily_win_1", 0)  # просто триггерим
    return True


def fmt_time_left(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}ч {m}мин"


# ═══════════════ STREAK (ежедневный вход) ═══════════════

def check_daily_login(user_id: int) -> tuple:
    """
    Проверяет streak входа.
    Возвращает (streak, bonus_awarded).
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT login_streak, last_login_date FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    today = datetime.now(TZ_MINSK).date()

    if not row:
        c.execute("UPDATE users SET login_streak = 1, last_login_date = %s WHERE user_id = %s",
                  (today, user_id))
        conn.commit()
        c.close()
        release_conn(conn)
        return 1, 0

    streak, last_date = row
    streak = streak or 0

    if last_date == today:
        c.close()
        release_conn(conn)
        return streak, 0

    if last_date == today - timedelta(days=1):
        streak += 1
    else:
        streak = 1

    bonus = 0
    if streak >= 7:
        bonus = 50_000
        streak = 0

    c.execute("UPDATE users SET login_streak = %s, last_login_date = %s WHERE user_id = %s",
              (streak, today, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    if bonus > 0:
        set_balance(user_id, bonus)
    return streak, bonus


# ═══════════════ БАНК: ПРОЦЕНТЫ (с лимитом 25M) ═══════════════

def accrue_bank_interest() -> int:
    """
    Начисляет 5% на банк, но ТОЛЬКО на сумму до MAX_BANK_INTEREST (25M).
    Возвращает количество обновлённых юзеров.
    """
    conn = get_conn()
    c = conn.cursor()
    # Начисляем только на часть до 25M
    c.execute("""
        UPDATE users
        SET bank = bank + LEAST(bank, %s) * %s
        WHERE bank > 0
    """, (MAX_BANK_INTEREST, BANK_INTEREST_RATE))
    affected = c.rowcount
    conn.commit()
    c.close()
    release_conn(conn)
    return affected


# ═══════════════ ЕЖЕДНЕВНЫЙ КЭШБЭК ═══════════════

def calc_cashback_today(user_id: int) -> int:
    """5% от проигрышей за 24ч."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT COALESCE(SUM(bet - win), 0) FROM game_log
                 WHERE user_id = %s AND created_at > NOW() - INTERVAL '24 hours'
                 AND win < bet""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    lost = row[0] if row else 0
    if lost <= 0:
        return 0
    return int(lost * get_user_cashback_percent(user_id) / 100)


def pay_daily_cashback() -> int:
    """Начисляет кэшбэк всем за сутки."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, username, COALESCE(SUM(bet - win), 0) AS lost
        FROM game_log
        WHERE created_at > NOW() - INTERVAL '24 hours' AND win < bet
        GROUP BY user_id, username
        HAVING SUM(bet - win) > 0
    """)
    rows = c.fetchall()
    paid = 0
    for uid, uname, lost in rows:
        base = int(lost * 5 / 100)
        if base < 100:
            continue
        try:
            set_balance(uid, base)
            c.execute("""INSERT INTO daily_cashback (user_id, amount)
                         VALUES (%s, %s) ON CONFLICT (user_id, date) DO NOTHING""",
                      (uid, base))
            paid += 1
        except Exception as e:
            print(f"[cashback {uid}] {e}")
    conn.commit()
    c.close()
    release_conn(conn)
    return paid


# ═══════════════ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ═══════════════

def get_daily_quests() -> list:
    cached = cache_get("daily_quests", ttl=30)
    if cached is not None:
        return cached
    val = get_setting("daily_quests")
    if val:
        try:
            qs = json.loads(val)
            if isinstance(qs, list) and qs:
                cache_set("daily_quests", qs, ttl=30)
                return qs
        except Exception:
            pass
    default = [dict(q) for q in DEFAULT_DAILY_QUESTS]
    cache_set("daily_quests", default, ttl=30)
    return default


def save_daily_quests(quests: list):
    set_setting("daily_quests", json.dumps(quests, ensure_ascii=False))
    cache_invalidate("daily_quests")


def get_user_daily_quests(user_id: int) -> list:
    quests = get_daily_quests()
    result = []
    conn = get_conn()
    c = conn.cursor()
    for q in quests:
        c.execute("""SELECT progress, claimed, reset_at FROM daily_quests
                     WHERE user_id = %s AND quest_key = %s""",
                  (user_id, q["key"]))
        row = c.fetchone()
        if row and row[2] and row[2].date() == datetime.now(TZ_MINSK).date():
            progress, claimed = row[0], row[1]
        else:
            c.execute("""INSERT INTO daily_quests (user_id, quest_key, progress, claimed, reset_at)
                         VALUES (%s, %s, 0, FALSE, NOW())
                         ON CONFLICT (user_id, quest_key) DO UPDATE
                         SET progress = 0, claimed = FALSE, reset_at = NOW()""",
                      (user_id, q["key"]))
            progress, claimed = 0, False
        result.append({
            "key": q["key"], "name": q["name"], "reward": q["reward"],
            "target": q["target"], "progress": progress,
            "completed": progress >= q["target"],
            "claimed": claimed,
        })
    conn.commit()
    c.close()
    release_conn(conn)
    return result


def update_daily_quest(user_id: int, quest_key: str, amount: int = 1):
    if amount <= 0:
        return
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO daily_quests (user_id, quest_key, progress, reset_at)
                     VALUES (%s, %s, %s, NOW())
                     ON CONFLICT (user_id, quest_key) DO UPDATE
                     SET progress = daily_quests.progress + EXCLUDED.progress,
                         reset_at = NOW()""",
                  (user_id, quest_key, amount))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[update_daily_quest] {e}")


def claim_daily_quest(user_id: int, quest_key: str) -> int:
    quests = get_daily_quests()
    q = next((x for x in quests if x["key"] == quest_key), None)
    if not q:
        return 0
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT progress, claimed FROM daily_quests
                 WHERE user_id = %s AND quest_key = %s""", (user_id, quest_key))
    row = c.fetchone()
    if not row or row[1] or row[0] < q["target"]:
        c.close()
        release_conn(conn)
        return 0
    c.execute("""UPDATE daily_quests SET claimed = TRUE
                 WHERE user_id = %s AND quest_key = %s""", (user_id, quest_key))
    conn.commit()
    c.close()
    release_conn(conn)
    set_balance(user_id, q["reward"])
    return q["reward"]


# ═══════════════ НАГРАДЫ ЗА УРОВНИ ═══════════════

def get_level_rewards() -> list:
    cached = cache_get("level_rewards", ttl=30)
    if cached is not None:
        return cached
    val = get_setting("level_rewards")
    if val:
        try:
            rewards = json.loads(val)
            if isinstance(rewards, list) and rewards:
                cache_set("level_rewards", rewards, ttl=30)
                return rewards
        except Exception:
            pass
    default = [dict(r) for r in DEFAULT_LEVEL_REWARDS]
    cache_set("level_rewards", default, ttl=30)
    return default


def save_level_rewards(rewards: list):
    set_setting("level_rewards", json.dumps(rewards, ensure_ascii=False))
    cache_invalidate("level_rewards")


def check_level_rewards(user_id: int, new_level: int) -> list:
    rewards = get_level_rewards()
    given = []
    conn = get_conn()
    c = conn.cursor()
    for r in rewards:
        if r["level"] > new_level:
            continue
        c.execute("SELECT 1 FROM level_rewards_claimed WHERE user_id = %s AND level = %s",
                  (user_id, r["level"]))
        if c.fetchone():
            continue
        if r["type"] == "tokens":
            set_balance(user_id, r["value"])
            given.append(f"🏆 Уровень {r['level']} — +{fmt_num(r['value'])} Tokens")
        elif r["type"] == "cashback":
            given.append(f"🏆 Уровень {r['level']} — кэшбэк +{r['value']}%")
        elif r["type"] == "vip_games":
            given.append(f"🏆 Уровень {r['level']} — VIP-игры разблокированы")
        elif r["type"] == "vip_tier":
            set_vip_tier(user_id, r["value"], 20)
            given.append(f"🏆 Уровень {r['level']} — VIP {r['value']} бесплатно")
        c.execute("INSERT INTO level_rewards_claimed (user_id, level) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                  (user_id, r["level"]))
    conn.commit()
    c.close()
    release_conn(conn)
    return given


# ═══════════════ XP-ПАКИ ═══════════════

def get_xp_packs() -> list:
    cached = cache_get("xp_packs", ttl=30)
    if cached is not None:
        return cached
    val = get_setting("xp_packs")
    if val:
        try:
            packs = json.loads(val)
            if isinstance(packs, list) and packs:
                cache_set("xp_packs", packs, ttl=30)
                return packs
        except Exception:
            pass
    default = [dict(p) for p in DEFAULT_XP_PACKS]
    cache_set("xp_packs", default, ttl=30)
    return default


def save_xp_packs(packs: list):
    set_setting("xp_packs", json.dumps(packs, ensure_ascii=False))
    cache_invalidate("xp_packs")


# ═══════════════ ТУРНИРЫ ═══════════════

def get_active_tournament():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, name, started_at, ends_at, prize_1, prize_2, prize_3
                 FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1""")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row


def start_tournament(name: str, duration_hours: int = 168):
    ends_at = datetime.now(TZ_MINSK) + timedelta(hours=duration_hours)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE tournaments SET status = 'finished' WHERE status = 'active'")
    c.execute("""INSERT INTO tournaments (name, ends_at, status, prize_1, prize_2, prize_3)
                 VALUES (%s, %s, 'active', 10000, 5000, 2000) RETURNING id""",
              (name, ends_at))
    tid = c.fetchone()[0]
    conn.commit()
    c.close()
    release_conn(conn)
    return tid, ends_at


def update_tournament_score(user_id: int, username: str, win_amount: int):
    try:
        t = get_active_tournament()
        if not t:
            return
        tid = t[0]
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO tournament_scores (tournament_id, user_id, username, total_won)
                     VALUES (%s, %s, %s, %s)
                     ON CONFLICT (tournament_id, user_id) DO UPDATE
                     SET total_won = tournament_scores.total_won + EXCLUDED.total_won,
                         username = EXCLUDED.username""",
                  (tid, user_id, username, win_amount))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[update_tournament_score] {e}")


def get_tournament_top(tid: int, limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, total_won FROM tournament_scores
                 WHERE tournament_id = %s ORDER BY total_won DESC LIMIT %s""",
              (tid, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def finish_tournament(tid: int):
    t = get_active_tournament()
    if not t or t[0] != tid:
        return None
    top = get_tournament_top(tid, 3)
    prizes = [t[4], t[5], t[6]]
    winners = []
    for i, (uid, uname, total) in enumerate(top):
        if i < 3 and prizes[i] > 0:
            set_balance(uid, prizes[i])
            winners.append((uid, uname, prizes[i]))
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE tournaments SET status = 'finished',
                 winner_1 = %s, winner_2 = %s, winner_3 = %s WHERE id = %s""",
              (winners[0][0] if len(winners) > 0 else None,
               winners[1][0] if len(winners) > 1 else None,
               winners[2][0] if len(winners) > 2 else None,
               tid))
    conn.commit()
    c.close()
    release_conn(conn)
    return winners


# ═══════════════ СБРОС ЮЗЕРА ═══════════════

def reset_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET balance = 1000, bank = 0, xp = 0, vip_level = 0,
                 total_lost = 0, total_won = 0, inventory = '[]'::jsonb,
                 birthday = NULL, login_streak = 0, last_login_date = NULL,
                 credit_blocked = FALSE
                 WHERE user_id = %s""", (user_id,))
    c.execute("DELETE FROM quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM achievements WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM daily_quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM level_rewards_claimed WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM credits WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate()


# ═══════════════ ЯЗЫК ═══════════════

def get_lang(user_id: int) -> str:
    if user_id in lang_state:
        return lang_state[user_id]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(lang, 'ru') FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    lang = row[0] if row else 'ru'
    if lang not in ('ru', 'en'):
        lang = 'ru'
    lang_state[user_id] = lang
    return lang


def set_lang(user_id: int, lang: str):
    if lang not in ('ru', 'en'):
        return
    lang_state[user_id] = lang
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET lang = %s WHERE user_id = %s", (lang, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 4/15 — КРЕДИТЫ (50к–500к, 3 дня, 0%)
# ═══════════════════════════════════════════════════════════════

# ═══════════════ КРЕДИТЫ: ОСНОВНЫЕ ФУНКЦИИ ═══════════════

def get_active_credit(user_id: int):
    """
    Возвращает активный кредит игрока или None.
    Формат: (id, amount, issued_at, due_at, status)
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, amount, issued_at, due_at, status
                 FROM credits
                 WHERE user_id = %s AND status = 'active'
                 ORDER BY id DESC LIMIT 1""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row


def get_last_credit(user_id: int):
    """Последний кредит игрока (любой статус)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, amount, issued_at, due_at, returned_at, status
                 FROM credits
                 WHERE user_id = %s
                 ORDER BY id DESC LIMIT 1""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row


def get_credit_history(user_id: int, limit: int = 10) -> list:
    """История кредитов игрока."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, amount, issued_at, due_at, returned_at, status
                 FROM credits
                 WHERE user_id = %s
                 ORDER BY id DESC LIMIT %s""", (user_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def is_credit_blocked(user_id: int) -> bool:
    """Заблокирован ли игрок из-за кредита."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT credit_blocked FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return bool(row[0]) if row and row[0] else False


def can_take_credit(user_id: int) -> tuple:
    """
    Может ли игрок взять кредит?
    Возвращает (можно: bool, причина_отказа_или_None).
    """
    active = get_active_credit(user_id)
    if active:
        return False, "❌ У вас уже есть активный кредит. Сначала верните его."
    
    if is_credit_blocked(user_id):
        return False, "🚫 Вы заблокированы из-за непогашенного кредита."
    
    return True, None


def issue_credit(user_id: int, amount: int) -> tuple:
    """
    Выдаёт кредит.
    Возвращает (успех: bool, сообщение: str, due_at или None).
    """
    if amount < CREDIT_MIN:
        return False, f"❌ Минимум: <b>{fmt_num(CREDIT_MIN)}</b> Tokens", None
    if amount > CREDIT_MAX:
        return False, f"❌ Максимум: <b>{fmt_num(CREDIT_MAX)}</b> Tokens", None
    
    can, reason = can_take_credit(user_id)
    if not can:
        return False, reason, None
    
    issued_at = datetime.now(TZ_MINSK)
    due_at = issued_at + timedelta(days=CREDIT_DAYS)
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO credits (user_id, amount, issued_at, due_at, status)
                 VALUES (%s, %s, %s, %s, 'active') RETURNING id""",
              (user_id, amount, issued_at, due_at))
    credit_id = c.fetchone()[0]
    conn.commit()
    c.close()
    release_conn(conn)
    
    set_balance(user_id, amount)
    
    try:
        asyncio.create_task(notify_admin_credit(user_id, amount, due_at))
    except Exception:
        pass
    
    return True, "✅ Кредит выдан!", due_at


def return_credit(user_id: int) -> tuple:
    """
    Возврат кредита вручную полной суммой.
    Возвращает (успех: bool, сообщение: str).
    """
    active = get_active_credit(user_id)
    if not active:
        return False, "❌ У вас нет активного кредита."
    
    credit_id, amount, issued_at, due_at, status = active
    
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=TZ_MINSK)
    
    balance = get_balance(user_id)
    if balance < amount and not is_unlimited(user_id):
        return False, (
            f"❌ <b>Недостаточно средств!</b>\n\n"
            f"💰 Нужно: <b>{fmt_num(amount)}</b> Tokens\n"
            f"💎 У вас: <b>{fmt_num(balance)}</b> Tokens\n\n"
            f"⚠️ <b>ВНИМАНИЕ!</b>\n"
            f"Если не вернёшь до <b>{due_at.strftime('%d.%m %H:%M')}</b> —\n"
            f"аккаунт будет <b>заблокирован</b>."
        )
    
    set_balance(user_id, -amount)
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE credits SET status = 'returned', returned_at = NOW()
                 WHERE id = %s""", (credit_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    
    new_balance = get_balance(user_id)
    return True, (
        f"✅ <b>Кредит возвращён!</b>\n\n"
        f"💰 Списано: <b>{fmt_num(amount)}</b> Tokens\n"
        f"💎 Новый баланс: <b>{fmt_num(new_balance)}</b> Tokens"
    )


def check_overdue_credits() -> list:
    """
    Проверяет просроченные кредиты.
    Возвращает [(user_id, amount, days_overdue), ...]
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, amount, due_at
                 FROM credits
                 WHERE status = 'active' AND due_at < NOW()""")
    rows = c.fetchall()
    
    overdue = []
    for uid, amount, due_at in rows:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        days = (datetime.now(TZ_MINSK) - due_at).days
        overdue.append((uid, amount, max(days, 1)))
    
    c.close()
    release_conn(conn)
    return overdue


def block_for_credit(user_id: int, amount: int, days_overdue: int):
    """Блокирует игрока за просрочку + уведомляет."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET credit_blocked = TRUE, banned = TRUE
                 WHERE user_id = %s""", (user_id,))
    c.execute("""UPDATE credits SET status = 'overdue'
                 WHERE user_id = %s AND status = 'active'""", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"banned_{user_id}")
    
    asyncio.create_task(send_credit_ban_message(user_id, amount, days_overdue))


async def send_credit_ban_message(user_id: int, amount: int, days_overdue: int):
    """Сообщение о бане за кредит."""
    text = (
        f"🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"⚠️ Вы не погасили кредит вовремя.\n\n"
        f"💰 Сумма долга: <b>{fmt_num(amount)}</b> Tokens\n"
        f"⏱ Просрочка: <b>{days_overdue} дн.</b>\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🔓 Чтобы разблокироваться —\n"
        f"свяжитесь с администратором.\n\n"
        f"💬 @admin"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception:
        pass


async def notify_admin_credit(user_id: int, amount: int, due_at: datetime):
    """Уведомляет админа о выдаче кредита."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        uname = row[0] if row else f"user_{user_id}"
        
        text = (
            f"💳 <b>НОВЫЙ КРЕДИТ ВЫДАН</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 Игрок: @{uname}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💰 Сумма: <b>{fmt_num(amount)}</b> Tokens\n"
            f"📈 Процент: <b>0%</b>\n"
            f"⏱ Вернуть до: <b>{due_at.strftime('%d.%m %H:%M')}</b>"
        )
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print(f"[notify_admin_credit] {e}")


def remind_credits() -> list:
    """
    Возвращает список кредитов, истекающих в течение 24ч (ещё не напомненных).
    Формат: [(user_id, amount, hours_left), ...]
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, amount, due_at
                 FROM credits
                 WHERE status = 'active'
                 AND due_at > NOW()
                 AND due_at < NOW() + INTERVAL '24 hours'
                 AND reminded = FALSE""")
    rows = c.fetchall()
    reminded = []
    
    for uid, amount, due_at in rows:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        hours_left = int((due_at - datetime.now(TZ_MINSK)).total_seconds() / 3600)
        reminded.append((uid, amount, max(hours_left, 1)))
        c.execute("""UPDATE credits SET reminded = TRUE
                     WHERE user_id = %s AND status = 'active'""", (uid,))
    
    conn.commit()
    c.close()
    release_conn(conn)
    return reminded


async def send_credit_reminder(user_id: int, amount: int, hours_left: int):
    """Напоминание о кредите за 24ч."""
    text = (
        f"⏰ <b>НАПОМИНАНИЕ О КРЕДИТЕ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"💰 Сумма долга: <b>{fmt_num(amount)}</b> Tokens\n"
        f"⏱ Осталось: <b>{hours_left} ч.</b>\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🚫 Если не вернёшь вовремя —\n"
        f"аккаунт будет <b>заблокирован</b>!"
    )
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception:
        pass


def get_credit_amount_info(user_id: int) -> dict:
    """
    Информация о доступности кредита для игрока.
    Для отображения в Mini App.
    """
    active = get_active_credit(user_id)
    if active:
        _, amount, issued_at, due_at, _ = active
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        days_left = max((due_at - datetime.now(TZ_MINSK)).days, 0)
        return {
            "status": "active",
            "amount": amount,
            "due_at": due_at.isoformat(),
            "days_left": days_left,
        }
    
    if is_credit_blocked(user_id):
        return {
            "status": "blocked",
            "reason": "Вы заблокированы из-за непогашенного кредита.",
        }
    
    return {
        "status": "available",
        "min": CREDIT_MIN,
        "max": CREDIT_MAX,
        "days": CREDIT_DAYS,
        "percent": CREDIT_PERCENT,
    }


def unlock_credit_user(user_id: int):
    """Разблокировка игрока после возврата кредита (только для админа)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET credit_blocked = FALSE, banned = FALSE
                 WHERE user_id = %s""", (user_id,))
    c.execute("""UPDATE credits SET status = 'returned', returned_at = NOW()
                 WHERE user_id = %s AND status IN ('active', 'overdue')""",
              (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"banned_{user_id}")


def get_all_credits_stats() -> dict:
    """Статистика по всем кредитам (для админ-панели)."""
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""SELECT COUNT(*), COALESCE(SUM(amount), 0)
                 FROM credits WHERE status = 'active'""")
    active_count, active_sum = c.fetchone()
    
    c.execute("""SELECT COUNT(*), COALESCE(SUM(amount), 0)
                 FROM credits WHERE status = 'overdue'""")
    overdue_count, overdue_sum = c.fetchone()
    
    c.execute("""SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM credits""")
    total_count, total_sum = c.fetchone()
    
    c.close()
    release_conn(conn)
    
    return {
        "active_count": active_count or 0,
        "active_sum": active_sum or 0,
        "overdue_count": overdue_count or 0,
        "overdue_sum": overdue_sum or 0,
        "total_count": total_count or 0,
        "total_sum": total_sum or 0,
    }


def get_overdue_users(limit: int = 50) -> list:
    """
    Список игроков с просроченным кредитом (для админ-панели).
    Формат: [(user_id, username, amount, days_overdue), ...]
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT c.user_id, u.username, c.amount, c.due_at
                 FROM credits c
                 JOIN users u ON u.user_id = c.user_id
                 WHERE c.status = 'overdue'
                 ORDER BY c.due_at ASC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    
    result = []
    for uid, uname, amount, due_at in rows:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        days = (datetime.now(TZ_MINSK) - due_at).days
        result.append((uid, uname, amount, max(days, 1)))
    return result
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 5/15 — МАГАЗИН, КЕЙСЫ, ДЖЕКПОТ, РЫНОК
# ═══════════════════════════════════════════════════════════════

# ═══════════════ МАГАЗИН ═══════════════

DEFAULT_SHOP_ITEMS = [
    # ⚡ Бусты
    {"id": "boost_2_30", "type": "boost", "name": "⚡ ×2 на 30 мин",
     "desc": "Множитель ×2 на 30 мин", "mult": 2, "minutes": 30,
     "stars": 5, "tokens": None, "category": "boosts"},
    {"id": "boost_2_60", "type": "boost", "name": "⚡ ×2 на 1 час",
     "desc": "Множитель ×2 на 60 мин", "mult": 2, "minutes": 60,
     "stars": 8, "tokens": None, "category": "boosts"},
    {"id": "boost_3_30", "type": "boost", "name": "⚡ ×3 на 30 мин",
     "desc": "Множитель ×3 на 30 мин", "mult": 3, "minutes": 30,
     "stars": 12, "tokens": None, "category": "boosts"},
    {"id": "boost_3_60", "type": "boost", "name": "⚡ ×3 на 1 час",
     "desc": "Множитель ×3 на 60 мин", "mult": 3, "minutes": 60,
     "stars": 15, "tokens": 500_000, "category": "boosts"},
    # 🏷️ Титулы
    {"id": "title_ludoman", "type": "title", "name": "🏷️ Титул «Лудоман»",
     "desc": "Крутой титул", "title": "🎰 Лудоман",
     "stars": 25, "tokens": None, "category": "titles"},
    {"id": "title_legend", "type": "title", "name": "🏷️ Титул «Легенда»",
     "desc": "Для настоящих легенд", "title": "👑 Легенда",
     "stars": 50, "tokens": 5_000_000, "category": "titles"},
    {"id": "title_elite", "type": "title", "name": "🏷️ Титул «Элита»",
     "desc": "Только для избранных", "title": "💠 Элита",
     "stars": 75, "tokens": None, "category": "titles"},
    {"id": "title_whale", "type": "title", "name": "🏷️ Титул «Кит»",
     "desc": "Для самых богатых", "title": "🌟 Кит",
     "stars": 100, "tokens": None, "category": "titles"},
]

DEFAULT_SHOP_CATEGORIES = {
    "tokens": "💰 Tokens",
    "cases": "🎰 Кейсы",
    "boosts": "⚡ Бусты",
    "titles": "🏷️ Титулы",
    "vip": "👑 VIP",
    "xp": "⭐ Буст XP",
}


def get_shop_items() -> list:
    cached = cache_get("shop_items", ttl=20)
    if cached is not None:
        return cached
    val = get_setting("shop_items")
    if val:
        try:
            items = json.loads(val)
            if isinstance(items, list) and items:
                cache_set("shop_items", items, ttl=20)
                return items
        except Exception:
            pass
    default = [dict(it) for it in DEFAULT_SHOP_ITEMS]
    cache_set("shop_items", default, ttl=20)
    return default


def save_shop_items(items: list):
    set_setting("shop_items", json.dumps(items, ensure_ascii=False))
    cache_invalidate("shop_items")


def get_shop_by_category(category: str) -> list:
    return [it for it in get_shop_items() if it.get("category") == category]


def get_shop_item_by_id(item_id: str):
    for it in get_shop_items():
        if it.get("id") == item_id:
            return it
    return None


def grant_shop_item(user_id: int, it: dict) -> str:
    """Выдаёт предмет из магазина в инвентарь."""
    t = it.get("type", "boost")
    if t == "boost":
        add_to_inventory(user_id, {
            "type": "boost", "mult": int(it.get("mult", 2)),
            "minutes": int(it.get("minutes", 30))
        })
        return f"⚡ Буст ×{it.get('mult')} на {it.get('minutes')} мин"
    if t == "title":
        add_to_inventory(user_id, {"type": "title", "title": it.get("title", "🏷️ Титул")})
        return f"🏷️ Титул «{it.get('title')}»"
    if t == "vip":
        add_to_inventory(user_id, {"type": "vip", "vip_level": int(it.get("vip_level", 1))})
        return f"👑 VIP уровень {it.get('vip_level')}"
    if t == "tokens":
        amount = int(it.get("tokens_amount", 0))
        set_balance(user_id, amount)
        return f"💰 +{fmt_num(amount)} Tokens"
    return "🎁 Предмет"


# ═══════════════ ПРОДАЖА TOKENS ЗА STARS ═══════════════

DEFAULT_TOKENS_PACKS = [
    {"id": "tokens_10k",  "amount": 10_000,   "stars": 5,   "active": True},
    {"id": "tokens_50k",  "amount": 50_000,   "stars": 20,  "active": True},
    {"id": "tokens_100k", "amount": 100_000,  "stars": 35,  "active": True},
    {"id": "tokens_500k", "amount": 500_000,  "stars": 150, "active": True},
]


def get_tokens_packs() -> list:
    cached = cache_get("tokens_packs", ttl=20)
    if cached is not None:
        return cached
    val = get_setting("tokens_packs")
    if val:
        try:
            packs = json.loads(val)
            if isinstance(packs, list):
                cache_set("tokens_packs", packs, ttl=20)
                return packs
        except Exception:
            pass
    default = [dict(p) for p in DEFAULT_TOKENS_PACKS]
    cache_set("tokens_packs", default, ttl=20)
    return default


def save_tokens_packs(packs: list):
    set_setting("tokens_packs", json.dumps(packs, ensure_ascii=False))
    cache_invalidate("tokens_packs")


def get_tokens_pack_by_id(pack_id: str):
    for p in get_tokens_packs():
        if p.get("id") == pack_id:
            return p
    return None


# ═══════════════ КЕЙСЫ ═══════════════

DEFAULT_CASES = [
    {
        "id": "bronze", "name": "🥉 Бронзовый",
        "desc": "Простой кейс", "stars": 5, "active": True,
        "rewards": [
            {"type": "tokens", "amount": 5_000,   "chance": 40},
            {"type": "tokens", "amount": 10_000,  "chance": 30},
            {"type": "boost",  "mult": 2, "minutes": 30, "chance": 20},
            {"type": "tokens", "amount": 50_000,  "chance": 10},
        ]
    },
    {
        "id": "silver", "name": "🥈 Серебряный",
        "desc": "Средний кейс", "stars": 15, "active": True,
        "rewards": [
            {"type": "tokens", "amount": 25_000,  "chance": 35},
            {"type": "tokens", "amount": 50_000,  "chance": 30},
            {"type": "boost",  "mult": 3, "minutes": 30, "chance": 20},
            {"type": "tokens", "amount": 200_000, "chance": 14},
            {"type": "title",  "title": "🎰 Лудоман", "chance": 1},
        ]
    },
    {
        "id": "gold", "name": "🥇 Золотой",
        "desc": "Лучший кейс", "stars": 35, "active": True,
        "rewards": [
            {"type": "tokens", "amount": 100_000, "chance": 30},
            {"type": "tokens", "amount": 250_000, "chance": 25},
            {"type": "boost",  "mult": 3, "minutes": 60, "chance": 20},
            {"type": "title",  "title": "👑 Легенда", "chance": 15},
            {"type": "vip",    "vip_level": 1, "chance": 8},
            {"type": "tokens", "amount": 1_000_000, "chance": 2},
        ]
    },
]


def get_cases() -> list:
    cached = cache_get("cases", ttl=20)
    if cached is not None:
        return cached
    val = get_setting("cases")
    if val:
        try:
            cases = json.loads(val)
            if isinstance(cases, list) and cases:
                cache_set("cases", cases, ttl=20)
                return cases
        except Exception:
            pass
    default = [dict(c) for c in DEFAULT_CASES]
    cache_set("cases", default, ttl=20)
    return default


def save_cases(cases: list):
    set_setting("cases", json.dumps(cases, ensure_ascii=False))
    cache_invalidate("cases")


def get_case_by_id(case_id: str):
    for c in get_cases():
        if c["id"] == case_id:
            return c
    return None


def roll_case_reward(case: dict):
    """Выбирает случайную награду из кейса."""
    rewards = case.get("rewards", [])
    total = sum(r.get("chance", 0) for r in rewards)
    if total <= 0:
        return rewards[0] if rewards else None
    roll = random.uniform(0, total)
    acc = 0
    for r in rewards:
        acc += r.get("chance", 0)
        if roll <= acc:
            return r
    return rewards[-1]


def apply_case_reward(user_id: int, reward: dict) -> str:
    """
    Применяет награду из кейса.
    Возвращает текст описания.
    """
    t = reward.get("type")
    
    if t == "tokens":
        amount = int(reward.get("amount", 0))
        set_balance(user_id, amount)
        return f"💰 +{fmt_num(amount)} Tokens"
    
    if t == "boost":
        add_to_inventory(user_id, {
            "type": "boost",
            "mult": int(reward.get("mult", 2)),
            "minutes": int(reward.get("minutes", 30))
        })
        return f"⚡ Буст ×{reward['mult']} на {reward['minutes']} мин"
    
    if t == "title":
        add_to_inventory(user_id, {"type": "title", "title": reward.get("title", "🏷️")})
        return f"🏷️ Титул «{reward.get('title')}»"
    
    if t == "vip":
        add_to_inventory(user_id, {
            "type": "vip",
            "vip_level": int(reward.get("vip_level", 1))
        })
        return f"👑 VIP уровень {reward.get('vip_level')}"
    
    if t == "xp":
        amount = int(reward.get("amount", 0))
        new_xp, level_changed, new_level = add_xp(user_id, amount)
        return f"⭐ +{fmt_num(amount)} XP"
    
    return "🎁 Награда"


# ═══════════════ ДЖЕКПОТ ═══════════════

def get_jackpot() -> int:
    cached = cache_get("jackpot", ttl=10)
    if cached is not None:
        return cached
    val = get_setting("jackpot")
    if val:
        try:
            amount = int(val)
        except Exception:
            amount = 10_000
    else:
        amount = 10_000
        set_setting("jackpot", "10000")
    cache_set("jackpot", amount, ttl=10)
    return amount


def save_jackpot(amount: int):
    amount = clamp(amount)
    set_setting("jackpot", str(amount))
    cache_invalidate("jackpot")


def add_to_jackpot(amount: int) -> int:
    """Добавляет в джекпот. Возвращает новый размер."""
    current = get_jackpot()
    new_val = clamp(current + amount)
    save_jackpot(new_val)
    return new_val


def reset_jackpot() -> int:
    save_jackpot(10_000)
    return 10_000


# ═══════════════ ИНВЕНТАРЬ ═══════════════

def get_inventory(user_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT inventory FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if not row or not row[0]:
        return []
    inv = row[0]
    if isinstance(inv, str):
        try:
            inv = json.loads(inv)
        except Exception:
            return []
    return inv if isinstance(inv, list) else []


def save_inventory(user_id: int, inventory: list):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET inventory = %s::jsonb WHERE user_id = %s",
              (json.dumps(inventory, ensure_ascii=False), user_id))
    conn.commit()
    c.close()
    release_conn(conn)


def add_to_inventory(user_id: int, item: dict) -> str:
    inv = get_inventory(user_id)
    item["inv_id"] = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    item["obtained_at"] = datetime.now(TZ_MINSK).isoformat()
    inv.append(item)
    save_inventory(user_id, inv)
    return item["inv_id"]


def remove_from_inventory(user_id: int, inv_id: str) -> bool:
    inv = get_inventory(user_id)
    new_inv = [it for it in inv if it.get("inv_id") != inv_id]
    if len(new_inv) == len(inv):
        return False
    save_inventory(user_id, new_inv)
    return True


def find_inventory_item(user_id: int, inv_id: str):
    inv = get_inventory(user_id)
    for it in inv:
        if it.get("inv_id") == inv_id:
            return it
    return None


def use_inventory_item(user_id: int, inv_id: str) -> tuple:
    """Использует предмет из инвентаря."""
    item = find_inventory_item(user_id, inv_id)
    if not item:
        return False, "❌ Предмет не найден"
    t = item.get("type")
    if t == "boost":
        add_boost(user_id, item["mult"], item["minutes"])
        remove_from_inventory(user_id, inv_id)
        return True, f"⚡ Буст ×{item['mult']} на {item['minutes']} мин активирован!"
    if t == "title":
        add_title(user_id, item["title"], 0)
        remove_from_inventory(user_id, inv_id)
        return True, f"🏷️ Титул «{item['title']}» активирован!"
    if t == "vip":
        set_vip_tier(user_id, item["vip_level"], 20)
        remove_from_inventory(user_id, inv_id)
        return True, f"👑 VIP {item['vip_level']} активирован на 20 дней!"
    return False, "❌ Неизвестный тип"


# ═══════════════ РЫНОК ═══════════════

def get_market_lots() -> list:
    val = get_setting("market_lots")
    if val:
        try:
            return json.loads(val)
        except Exception:
            return []
    return []


def save_market_lots(lots: list):
    set_setting("market_lots", json.dumps(lots, ensure_ascii=False))


def add_market_lot(user_id: int, username: str, item: dict, price: int) -> str:
    lots = get_market_lots()
    lot = {
        "id": f"lot_{int(time.time()*1000)}_{random.randint(100, 999)}",
        "seller_id": user_id,
        "seller_name": username,
        "type": item.get("type"),
        "payload": {k: v for k, v in item.items() if k not in ("inv_id", "obtained_at", "type")},
        "price": price,
        "created_at": datetime.now(TZ_MINSK).isoformat(),
    }
    lots.append(lot)
    save_market_lots(lots)
    return lot["id"]


def buy_market_lot(buyer_id: int, lot_idx: int) -> tuple:
    lots = get_market_lots()
    if lot_idx < 0 or lot_idx >= len(lots):
        return False, "❌ Лот не найден"
    lot = lots[lot_idx]
    if lot["seller_id"] == buyer_id:
        return False, "❌ Нельзя купить свой лот"
    
    buyer_balance = get_balance(buyer_id)
    price = lot["price"]
    if buyer_balance < price and not is_unlimited(buyer_id):
        return False, f"❌ Недостаточно! Нужно {fmt_num(price)} Tokens"
    
    set_balance(buyer_id, -price)
    commission = int(price * 0.05)
    seller_gets = price - commission
    add_to_jackpot(commission)
    set_balance(lot["seller_id"], seller_gets)
    
    new_item = dict(lot["payload"])
    new_item["type"] = lot["type"]
    add_to_inventory(buyer_id, new_item)
    
    lots.pop(lot_idx)
    save_market_lots(lots)
    
    return True, (
        f"✅ Куплено!\n"
        f"💰 Цена: <b>{fmt_num(price)}</b> Tokens\n"
        f"💸 Продавцу: <b>{fmt_num(seller_gets)}</b> Tokens\n"
        f"🎰 Комиссия в джекпот: <b>{fmt_num(commission)}</b> Tokens"
    )


# ═══════════════ НАГРАДЫ ИЗ КЕЙСОВ (для Mini App) ═══════════════

def save_last_reward(user_id: int, reward: dict):
    try:
        key = f"last_reward_{user_id}"
        set_setting(key, json.dumps(reward, ensure_ascii=False))
    except Exception as e:
        print(f"save_last_reward error: {e}")


def get_last_reward(user_id: int):
    try:
        key = f"last_reward_{user_id}"
        val = get_setting(key)
        if val:
            return json.loads(val)
    except Exception as e:
        print(f"get_last_reward error: {e}")
    return None


# ═══════════════ LOG PURCHASE ═══════════════

def log_purchase(user_id: int, username: str, purchase_type: str,
                 item_name: str, price: str, source: str, extra: str = ""):
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO purchase_log
                     (user_id, username, purchase_type, item_name, price, source, extra)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                  (user_id, username, purchase_type, item_name, price, source, extra))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[log_purchase] {e}")


def get_purchases(limit: int = 20) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, purchase_type, item_name, price, source, created_at
                 FROM purchase_log ORDER BY id DESC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 6/15 — КЛАВИАТУРЫ (REPLY + INLINE)
# ═══════════════════════════════════════════════════════════════

# ═══════════════ REPLY-КЛАВИАТУРЫ ═══════════════

def private_kb() -> ReplyKeyboardMarkup:
    """Основное меню игрока (Reply)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Баланс")],
            [KeyboardButton(text="🏦 Банк"), KeyboardButton(text="💳 Кредиты")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус")],
            [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎒 Инвентарь")],
            [KeyboardButton(text="🏪 Рынок"), KeyboardButton(text="🎯 Задания")],
            [KeyboardButton(text="🏆 Турнир"), KeyboardButton(text="🔗 Рефералка")],
            [KeyboardButton(text="🌐 WebApp")],
            [KeyboardButton(text="🎮 ИГРАТЬ В ГРУППЕ")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_panel_kb() -> ReplyKeyboardMarkup:
    """Админ-панель (Reply)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🛒 Контент"), KeyboardButton(text="💰 Экономика")],
            [KeyboardButton(text="📢 Связь"), KeyboardButton(text="📊 Мониторинг")],
            [KeyboardButton(text="💳 Кредиты")],
            [KeyboardButton(text="📋 Все команды")],
            [KeyboardButton(text="🌐 WebApp")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ═══════════════ INLINE: ГЛАВНОЕ МЕНЮ ═══════════════

def main_menu_inline_kb() -> InlineKeyboardMarkup:
    """Главное inline-меню игрока."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu_bank"),
         InlineKeyboardButton(text="💳 Кредиты", callback_data="menu_credits")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
         InlineKeyboardButton(text="🎁 Бонус", callback_data="menu_daily")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop"),
         InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
        [InlineKeyboardButton(text="🏪 Рынок", callback_data="menu_market"),
         InlineKeyboardButton(text="🎯 Задания", callback_data="menu_quests")],
        [InlineKeyboardButton(text="🏆 Турнир", callback_data="menu_tournament"),
         InlineKeyboardButton(text="🔗 Рефералка", callback_data="menu_ref")],
        [InlineKeyboardButton(text="🌐 Язык", callback_data="menu_lang")],
        [InlineKeyboardButton(text="🚀 Открыть Mini App", web_app=WebAppInfo(url=MINI_APP_URL))],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")]
    ])


# ═══════════════ INLINE: ПРОФИЛЬ ═══════════════

def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История", callback_data="menu_history"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton(text="🎂 Дата рождения", callback_data="menu_birthday")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def history_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="hist_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="hist_slots")],
        [InlineKeyboardButton(text="💣 Мины", callback_data="hist_mines"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="hist_bj")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="hist_coin"),
         InlineKeyboardButton(text="⚔️ Дуэль", callback_data="hist_duel")],
        [InlineKeyboardButton(text="📋 Всё", callback_data="hist_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_profile")],
    ])


# ═══════════════ INLINE: ТОП ═══════════════

def top_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 По балансу", callback_data="top_balance"),
         InlineKeyboardButton(text="⭐ По XP", callback_data="top_xp")],
        [InlineKeyboardButton(text="🎮 По играм", callback_data="top_games"),
         InlineKeyboardButton(text="🏆 По победам", callback_data="top_wins")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


# ═══════════════ INLINE: БАНК ═══════════════

def bank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Положить", callback_data="bank_deposit"),
         InlineKeyboardButton(text="📤 Снять", callback_data="bank_withdraw")],
        [InlineKeyboardButton(text="💳 Кредиты", callback_data="menu_credits")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def bank_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_bank")]
    ])


# ═══════════════ INLINE: КРЕДИТЫ ═══════════════

def credits_kb(status: str = "available") -> InlineKeyboardMarkup:
    """Кнопки для раздела кредитов."""
    rows = []
    
    if status == "available":
        rows.append([InlineKeyboardButton(
            text="💳 Взять кредит",
            callback_data="credit_take"
        )])
    
    elif status == "active":
        rows.append([InlineKeyboardButton(
            text="💰 Вернуть кредит",
            callback_data="credit_return"
        )])
    
    rows.append([InlineKeyboardButton(text="📜 История кредитов", callback_data="credit_history")])
    rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def credits_amounts_kb() -> InlineKeyboardMarkup:
    """Быстрый выбор суммы кредита."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50 000", callback_data="credit_amount_50000"),
         InlineKeyboardButton(text="100 000", callback_data="credit_amount_100000")],
        [InlineKeyboardButton(text="250 000", callback_data="credit_amount_250000"),
         InlineKeyboardButton(text="500 000", callback_data="credit_amount_500000")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="credit_amount_custom")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_credits")],
    ])


def credit_confirm_kb(amount: int) -> InlineKeyboardMarkup:
    """Подтверждение взятия кредита."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, взять", callback_data=f"credit_confirm_{amount}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="menu_credits")],
    ])


def credit_return_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение возврата."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, вернуть", callback_data="credit_return_confirm"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="menu_credits")],
    ])


# ═══════════════ INLINE: МАГАЗИН ═══════════════

def shop_categories_kb() -> InlineKeyboardMarkup:
    """Категории магазина."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Tokens", callback_data="shop_cat_tokens"),
         InlineKeyboardButton(text="🎰 Кейсы", callback_data="shop_cat_cases")],
        [InlineKeyboardButton(text="⚡ Бусты", callback_data="shop_cat_boosts"),
         InlineKeyboardButton(text="🏷️ Титулы", callback_data="shop_cat_titles")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="shop_cat_vip"),
         InlineKeyboardButton(text="⭐ Буст XP", callback_data="shop_cat_xp")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def shop_items_kb(category: str) -> InlineKeyboardMarkup:
    """Товары в категории."""
    rows = []
    
    if category == "tokens":
        for p in get_tokens_packs():
            if not p.get("active", True):
                continue
            rows.append([InlineKeyboardButton(
                text=f"💰 {fmt_num(p['amount'])} Tokens — {p['stars']} ⭐",
                callback_data=f"shop_tokens_{p['id']}"
            )])
    
    elif category == "cases":
        for c in get_cases():
            if not c.get("active", True):
                continue
            rows.append([InlineKeyboardButton(
                text=f"{c['name']} — {c['stars']} ⭐",
                callback_data=f"shop_case_{c['id']}"
            )])
    
    elif category == "boosts":
        for it in get_shop_by_category("boosts"):
            price = f"{it['stars']} ⭐" if it.get("stars") else f"{fmt_num(it['tokens'])} Tokens"
            rows.append([InlineKeyboardButton(
                text=f"{it['name']} — {price}",
                callback_data=f"shop_item_{it['id']}"
            )])
    
    elif category == "titles":
        for it in get_shop_by_category("titles"):
            price = f"{it['stars']} ⭐" if it.get("stars") else f"{fmt_num(it['tokens'])} Tokens"
            rows.append([InlineKeyboardButton(
                text=f"{it['name']} — {price}",
                callback_data=f"shop_item_{it['id']}"
            )])
    
    elif category == "vip":
        for t in get_vip_tiers():
            rows.append([InlineKeyboardButton(
                text=f"{t['icon']} VIP {t['id']} — {t['name']} — {t['stars']} ⭐",
                callback_data=f"vip_buy_{t['id']}_{t['stars']}"
            )])
    
    elif category == "xp":
        for p in get_xp_packs():
            rows.append([InlineKeyboardButton(
                text=f"⭐ +{p['xp']} XP — {p['stars']} ⭐",
                callback_data=f"xp_buy_{p['id']}_{p['xp']}_{p['stars']}"
            )])
    
    rows.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="menu_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_item_kb(item_id: str) -> InlineKeyboardMarkup:
    """Кнопки покупки конкретного товара."""
    it = get_shop_item_by_id(item_id)
    if not it:
        return back_to_main_kb()
    rows = []
    if it.get("stars"):
        rows.append([InlineKeyboardButton(
            text=f"⭐ Купить за {it['stars']} Stars",
            callback_data=f"shop_buy_stars_{item_id}"
        )])
    if it.get("tokens"):
        rows.append([InlineKeyboardButton(
            text=f"💎 Купить за {fmt_num(it['tokens'])}",
            callback_data=f"shop_buy_tokens_{item_id}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"shop_cat_{it.get('category', 'boosts')}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ INLINE: КЕЙСЫ (в магазине) ═══════════════

def case_buy_kb(case_id: str, stars: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Купить за {stars} Stars",
            callback_data=f"case_buy_{case_id}_{stars}"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_cat_cases")],
    ])


def case_result_kb(last_inv_id: str = None) -> InlineKeyboardMarkup:
    """Кнопки после открытия кейса."""
    rows = []
    if last_inv_id:
        rows.append([InlineKeyboardButton(
            text="⚡ Использовать сейчас",
            callback_data=f"case_use_{last_inv_id}"
        )])
    rows.append([InlineKeyboardButton(text="📦 В инвентарь", callback_data="case_keep")])
    rows.append([InlineKeyboardButton(text="🎰 Ещё кейс", callback_data="shop_cat_cases")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ INLINE: VIP ═══════════════

def vip_buy_kb(tier_id: int, stars: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Купить VIP за {stars} Stars",
            callback_data=f"vip_buy_{tier_id}_{stars}"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_cat_vip")],
    ])


# ═══════════════ INLINE: XP ═══════════════

def xp_buy_kb(pack_id: str, xp: int, stars: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Купить +{xp} XP за {stars} Stars",
            callback_data=f"xp_buy_{pack_id}_{xp}_{stars}"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_cat_xp")],
    ])


# ═══════════════ INLINE: ЗАДАНИЯ ═══════════════

def daily_quests_kb(user_id: int) -> InlineKeyboardMarkup:
    quests = get_user_daily_quests(user_id)
    rows = []
    for q in quests:
        if q["claimed"]:
            rows.append([InlineKeyboardButton(
                text=f"✔️ {q['name']}",
                callback_data="quest_noop"
            )])
        elif q["completed"]:
            rows.append([InlineKeyboardButton(
                text=f"✅ Забрать: {q['name']} (+{fmt_num(q['reward'])})",
                callback_data=f"daily_quest_claim_{q['key']}"
            )])
        else:
            rows.append([InlineKeyboardButton(
                text=f"{q['name']} [{q['progress']}/{q['target']}]",
                callback_data="quest_noop"
            )])
    rows.append([InlineKeyboardButton(text="📋 Награды за уровни", callback_data="menu_level_rewards")])
    rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def level_rewards_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_quests")]
    ])


# ═══════════════ INLINE: ИГРЫ ═══════════════

def games_kb() -> InlineKeyboardMarkup:
    """Список игр."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="info_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="info_slots")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="info_coin"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="info_bj")],
        [InlineKeyboardButton(text="💣 Мины", callback_data="info_mines"),
         InlineKeyboardButton(text="⚔️ Дуэль", callback_data="info_duel")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def back_to_games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К играм", callback_data="menu_games")]
    ])


# ═══════════════ INLINE: РУЛЕТКА (ставим) ═══════════════

def roulette_bet_kb(bet: int = 1_000) -> InlineKeyboardMarkup:
    """Кнопки для ставок в рулетке (в группе)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное ×1.95", callback_data=f"bet_red_{bet}"),
         InlineKeyboardButton(text="⚫ Чёрное ×1.95", callback_data=f"bet_black_{bet}")],
        [InlineKeyboardButton(text="🟢 Зеро ×35", callback_data=f"bet_green_{bet}")],
        [InlineKeyboardButton(text="100", callback_data="setbet_100"),
         InlineKeyboardButton(text="1 000", callback_data="setbet_1000"),
         InlineKeyboardButton(text="10 000", callback_data="setbet_10000"),
         InlineKeyboardButton(text="MAX", callback_data="setbet_max")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


# ═══════════════ INLINE: БЛЭКДЖЕК ═══════════════

def bj_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="bj_hit"),
         InlineKeyboardButton(text="✋ Хватит", callback_data="bj_stand")],
    ])


# ═══════════════ INLINE: МИНЫ ═══════════════

def mines_level_kb(bet: int) -> InlineKeyboardMarkup:
    """Выбор уровня мин."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (3 💣)", callback_data=f"mines_start_easy_{bet}")],
        [InlineKeyboardButton(text="🟡 Средний (5 💣)", callback_data=f"mines_start_medium_{bet}")],
        [InlineKeyboardButton(text="🔴 Хардкор (10 💣)", callback_data=f"mines_start_hard_{bet}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_games")],
    ])


def mines_field_kb(user_id: int) -> InlineKeyboardMarkup:
    """Игровое поле мин."""
    game = mines_games.get(user_id)
    if not game:
        return None
    opened = game["opened"]
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened:
                if idx in game["mines_positions"]:
                    row.append(InlineKeyboardButton(text="💣", callback_data="mines_noop"))
                else:
                    row.append(InlineKeyboardButton(text="💎", callback_data="mines_noop"))
            else:
                row.append(InlineKeyboardButton(text="⬜", callback_data=f"mines_open_{idx}"))
        rows.append(row)
    
    if opened:
        mult = game["mult"]
        cashout = cap_win(int(game["bet"] * mult))
        rows.append([InlineKeyboardButton(
            text=f"💰 Забрать ×{mult:.2f} ({fmt_num(cashout)})",
            callback_data="mines_cashout"
        )])
    else:
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mines_cancel")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ INLINE: РЕФКА ═══════════════

def ref_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои рефералы", callback_data="ref_list")],
        [InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="ref_top")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


# ═══════════════ INLINE: РЫНОК ═══════════════

def market_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить", callback_data="market_browse"),
         InlineKeyboardButton(text="💰 Продать", callback_data="market_sell")],
        [InlineKeyboardButton(text="📦 Мои лоты", callback_data="market_mylots")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def market_lots_kb(lots: list, page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    rows = []
    start = page * per_page
    end = start + per_page
    for i, lot in enumerate(lots[start:end]):
        real_idx = start + i
        t = lot.get("type")
        if t == "boost":
            label = f"⚡ ×{lot['payload'].get('mult', '?')} / {lot['payload'].get('minutes', '?')}м"
        elif t == "title":
            label = f"🏷️ {lot['payload'].get('title', '?')}"
        elif t == "vip":
            label = f"👑 VIP {lot['payload'].get('vip_level', '?')}"
        else:
            label = "❓"
        price = f"{fmt_num(lot['price'])} Tokens"
        rows.append([InlineKeyboardButton(
            text=f"{label} — {price}",
            callback_data=f"market_buy_{real_idx}"
        )])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"market_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}", callback_data="market_noop"))
    if end < len(lots):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"market_page_{page+1}"))
    if nav:
        rows.append(nav)
    
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def market_sell_kb(user_id: int) -> InlineKeyboardMarkup:
    inv = get_inventory(user_id)
    rows = []
    for it in inv[:10]:
        t = it.get("type")
        if t == "boost":
            label = f"⚡ ×{it.get('mult', '?')} / {it.get('minutes', '?')}м"
        elif t == "title":
            label = f"🏷️ {it.get('title', '?')}"
        elif t == "vip":
            label = f"👑 VIP {it.get('vip_level', '?')}"
        else:
            label = "❓"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"market_sellitem_{it['inv_id']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ INLINE: ИНВЕНТАРЬ ═══════════════

def inventory_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷️ Титулы", callback_data="inv_titles"),
         InlineKeyboardButton(text="⚡ Бусты", callback_data="inv_boosts")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="inv_vip"),
         InlineKeyboardButton(text="📦 Всё", callback_data="inv_all")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


def inventory_list_kb(user_id: int, filter_type: str = None) -> InlineKeyboardMarkup:
    inv = get_inventory(user_id)
    if filter_type:
        inv = [it for it in inv if it.get("type") == filter_type]
    rows = []
    for it in inv[:10]:
        t = it.get("type")
        if t == "boost":
            label = f"⚡ ×{it.get('mult', '?')} / {it.get('minutes', '?')}м"
        elif t == "title":
            label = f"🏷️ {it.get('title', '?')}"
        elif t == "vip":
            label = f"👑 VIP {it.get('vip_level', '?')}"
        else:
            label = "❓ Предмет"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"inv_view_{it['inv_id']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_inventory")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_item_kb(inv_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Использовать", callback_data=f"inv_use_{inv_id}")],
        [InlineKeyboardButton(text="💰 Продать", callback_data=f"inv_sell_{inv_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_inventory")],
    ])


# ═══════════════ INLINE: ЯЗЫК ═══════════════

def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")],
    ])


# ═══════════════ INLINE: ГРУППА ═══════════════

def group_url_kb(text: str = "🎮 ИГРАТЬ В ГРУППЕ") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=GROUP_URL)]
    ])


def private_url_kb(text: str = "💬 ОТКРЫТЬ ЛС БОТА") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=f"https://t.me/{BOT_USERNAME}")]
    ])


# ═══════════════ INLINE: АДМИН-ПАНЕЛЬ ═══════════════

def admin_panel_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_cat_players"),
         InlineKeyboardButton(text="🎮 Игры", callback_data="admin_cat_games")],
        [InlineKeyboardButton(text="🛒 Контент", callback_data="admin_cat_content"),
         InlineKeyboardButton(text="💰 Экономика", callback_data="admin_cat_economy")],
        [InlineKeyboardButton(text="📢 Связь", callback_data="admin_cat_comm"),
         InlineKeyboardButton(text="📊 Мониторинг", callback_data="admin_cat_monitor")],
        [InlineKeyboardButton(text="💳 Кредиты", callback_data="admin_cat_credits")],
        [InlineKeyboardButton(text="📋 Все команды", callback_data="admin_all_commands")],
    ])


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_players_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="admin_pi_info")],
        [InlineKeyboardButton(text="🚫 Ban / Unban", callback_data="admin_ban_start")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="admin_vip_start"),
         InlineKeyboardButton(text="🏷️ Титул", callback_data="admin_title_start")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="admin_bal_start"),
         InlineKeyboardButton(text="📊 XP", callback_data="admin_xp_start")],
        [InlineKeyboardButton(text="🔄 Reset игрока", callback_data="admin_reset_start")],
        [InlineKeyboardButton(text="⚠️ ОБНУЛИТЬ ВСЕХ", callback_data="admin_reset_all_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def admin_games_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, name in GAME_NAMES.items():
        if key in ("crash", "plinko"):
            continue  # только для Mini App
        status = "❌" if key in disabled_games else "✅"
        rows.append([InlineKeyboardButton(
            text=f"{status} {name}",
            callback_data=f"admin_toggle_{key}"
        )])
    rows.append([InlineKeyboardButton(text="🎰 Event ×2", callback_data="admin_event"),
                 InlineKeyboardButton(text="🛠️ Тех.работы", callback_data="admin_maintenance")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_content_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Редактор магазина", callback_data="editshop_start")],
        [InlineKeyboardButton(text="🎰 Редактор кейсов", callback_data="editcases_start")],
        [InlineKeyboardButton(text="💰 Редактор Tokens-паков", callback_data="edittokens_start")],
        [InlineKeyboardButton(text="👑 Редактор VIP", callback_data="editvip_start")],
        [InlineKeyboardButton(text="⭐ Редактор XP", callback_data="editxp_start")],
        [InlineKeyboardButton(text="🎯 Редактор заданий", callback_data="editquest_start")],
        [InlineKeyboardButton(text="🏆 Редактор наград уровней", callback_data="editlevel_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def admin_economy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Бонус игроку", callback_data="admin_bonus_start")],
        [InlineKeyboardButton(text="💎 Джекпот", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="🎁 Розыгрыш", callback_data="admin_giveaway_start")],
        [InlineKeyboardButton(text="🏆 Турниры", callback_data="admin_tournament")],
        [InlineKeyboardButton(text="💱 Курсы обмена", callback_data="admin_set_rates")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def admin_comm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_show")],
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="📋 Все игроки", callback_data="admin_all_players")],
        [InlineKeyboardButton(text="📋 Покупки", callback_data="admin_purchases")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def admin_monitor_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="🏆 Big Wins", callback_data="admin_bigwins_show")],
        [InlineKeyboardButton(text="📜 Логи игрока", callback_data="admin_logs_start")],
        [InlineKeyboardButton(text="📋 Покупки", callback_data="admin_purchases")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def admin_credits_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_credits_stats")],
        [InlineKeyboardButton(text="🚫 Должники", callback_data="admin_credits_overdue")],
        [InlineKeyboardButton(text="🔓 Разбанить по кредиту", callback_data="admin_credits_unlock")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


# ═══════════════ INLINE: ВСЕ КОМАНДЫ ═══════════════

def all_commands_kb(page: int = 0) -> InlineKeyboardMarkup:
    """Кнопка «Все команды» — список всех команд."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать список", callback_data="admin_copy_commands")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 7/15 — ТЕКСТЫ (ФУНКЦИИ РЕНДЕРА)
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ПРОФИЛЬ ═══════════════

def profile_text(user_id: int, username: str) -> str:
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    level = xp // 100
    rank = get_rank_name(level)
    bar = make_xp_bar(xp)
    stats = get_user_stats(user_id)
    title = get_main_title(user_id)
    
    # VIP
    vip_tier = get_vip_tier(user_id)
    vip_line = ""
    if vip_tier > 0:
        info = get_vip_tier_info(vip_tier)
        expires = get_vip_expires(user_id)
        if info and expires:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=TZ_MINSK)
            days_left = max((expires - datetime.now(TZ_MINSK)).days, 0)
            vip_line = f"\n{info['icon']} <b>VIP {info['id']} — {info['name']}</b> ({days_left} дн.)"
    
    # Буст
    boost = get_active_boost(user_id)
    boost_line = ""
    if boost:
        until = boost[1]
        if until.tzinfo is None:
            until = until.replace(tzinfo=TZ_MINSK)
        mins_left = max(int((until - datetime.now(TZ_MINSK)).total_seconds() // 60), 0)
        boost_line = f"\n⚡ Буст: <b>×{boost[0]}</b> ({mins_left} мин)"
    
    # Баланс
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"<b>{fmt_num(balance)}</b> Tokens"
    
    # День рождения
    birthday_line = ""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT birthday FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        birthday_line = f"\n🎂 День рождения: <b>{row[0]}</b>"
    
    # Кредит
    active_credit = get_active_credit(user_id)
    credit_line = ""
    if active_credit:
        _, amount, _, due_at, _ = active_credit
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        days_left = max((due_at - datetime.now(TZ_MINSK)).days, 0)
        credit_line = f"\n💳 Кредит: <b>{fmt_num(amount)}</b> ({days_left} дн.)"
    
    title_line = f"🎩 Статус: <b>{title}</b>\n" if title else ""
    
    return (
        f"👤 <b>ПРОФИЛЬ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎭 <b>{username}</b>\n"
        f"{title_line}"
        f"🎖 Ранг: <b>{rank}</b>\n"
        f"📊 Опыт: <b>{xp} / {(level+1)*100} XP</b>\n"
        f"{bar}\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"💎 Баланс: {bal_line}\n"
        f"🏦 В банке: <b>{fmt_num(bank)}</b> Tokens\n"
        f"📊 Всего: <b>{fmt_num(balance + bank)}</b> Tokens"
        f"{vip_line}{boost_line}{credit_line}{birthday_line}\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎮 Игр: <b>{stats['total_games']}</b>\n"
        f"🏆 Побед: <b>{stats['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{stats['winrate']}%</b>"
    )


# ═══════════════ СТАТИСТИКА ═══════════════

def stats_text(user_id: int, username: str) -> str:
    s = get_user_stats(user_id)
    profit = s["profit"]
    profit_emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
    
    return (
        f"📊 <b>СТАТИСТИКА</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎭 <b>{username}</b>\n\n"
        f"🎮 Всего игр: <b>{s['total_games']}</b>\n"
        f"🏆 Побед: <b>{s['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{s['winrate']}%</b>\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"💰 Ставок: <b>{fmt_num(s['total_bet'])}</b>\n"
        f"💵 Выигрышей: <b>{fmt_num(s['total_win'])}</b>\n"
        f"{profit_emoji} Профит: <b>{'+' if profit >= 0 else ''}{fmt_num(profit)}</b>\n"
        f"🔥 Best: <b>{fmt_num(s['best_win'])}</b>\n\n"
        f"🎯 Любимая: <b>{s['fav_game']}</b>"
    )


# ═══════════════ ИСТОРИЯ ═══════════════

def history_text(user_id: int, username: str, game: str = None) -> str:
    logs = get_user_history(user_id, game=game, limit=15)
    title = f"📜 История: {game}" if game else "📜 История игр"
    
    if not logs:
        return f"{title}\n\nПока пусто..."
    
    txt = f"{title}\n━━━━━━━━━━━━━━\n\n"
    for i, (g, bet, win, detail, time_str) in enumerate(logs, 1):
        profit = win - bet
        emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
        txt += f"{i}. {emoji} <b>{g}</b> | {fmt_num(bet)} → {fmt_num(win)} | {time_str}\n"
    return txt


# ═══════════════ ТОП ═══════════════

def top_text(mode: str = "balance") -> str:
    if mode == "balance":
        rows = get_top(10)
        title = "💎 ТОП ПО БАЛАНСУ"
        def metric(r): return f"<b>{fmt_num(r[2])}</b> Tokens"
    elif mode == "xp":
        rows = get_top_xp(10)
        title = "⭐ ТОП ПО XP"
        def metric(r): return f"<b>{fmt_num(r[3] or 0)} XP</b>"
    elif mode == "games":
        rows = get_top_games(10)
        title = "🎮 ТОП ПО ИГРАМ"
        def metric(r): return f"<b>{r[4]} игр</b>"
    elif mode == "wins":
        rows = get_top_wins(10)
        title = "🏆 ТОП ПО ПОБЕДАМ"
        def metric(r): return f"<b>{r[4]} побед</b>"
    else:
        rows = get_top(10)
        title = "🏆 ТОП-10"
        def metric(r): return f"<b>{fmt_num(r[2])}</b> Tokens"
    
    if not rows:
        return f"🏆 <b>{title}</b>\n\nПока нет игроков!"
    
    txt = f"🏆 <b>{title}</b>\n━━━━━━━━━━━━━━\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        uid, uname = row[0], row[1]
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        t = get_main_title(uid)
        title_str = f" 🏷️{t}" if t else ""
        txt += f"{medal} <b>{uname or f'user_{uid}'}</b>{title_str} — {metric(row)}\n"
    return txt


# ═══════════════ БАНК ═══════════════

def bank_text(user_id: int, username: str) -> str:
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    total = clamp(balance + bank)
    
    # Проценты: только на 25M
    interest_base = min(bank, MAX_BANK_INTEREST)
    daily_interest = int(interest_base * BANK_INTEREST_RATE)
    
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"<b>{fmt_num(balance)}</b> Tokens"
    
    warning = ""
    if bank > MAX_BANK_INTEREST:
        warning = (
            f"\n⚠️ <b>ВНИМАНИЕ!</b>\n"
            f"Проценты начисляются только до <b>{fmt_num(MAX_BANK_INTEREST)}</b> Tokens.\n"
            f"Сверх лимита: <b>{fmt_num(bank - MAX_BANK_INTEREST)}</b> — без процентов."
        )
    
    return (
        f"🏦 <b>БАНК</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎭 <b>{username}</b>\n\n"
        f"💎 Баланс: {bal_line}\n"
        f"🏦 В банке: <b>{fmt_num(bank)}</b> Tokens\n"
        f"📊 Всего: <b>{fmt_num(total)}</b> Tokens\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📈 <b>Проценты:</b>\n"
        f"💵 Ставка: <b>5% в день</b>\n"
        f"🎁 За сутки: <b>+{fmt_num(daily_interest)}</b> Tokens"
        f"{warning}\n\n"
        f"👇 Выбери действие:"
    )


# ═══════════════ КРЕДИТЫ ═══════════════

def credits_text(user_id: int) -> str:
    info = get_credit_amount_info(user_id)
    balance = get_balance(user_id)
    
    txt = f"💳 <b>КРЕДИТЫ</b>\n━━━━━━━━━━━━━━\n\n"
    txt += f"💎 Твой баланс: <b>{fmt_num(balance)}</b> Tokens\n\n"
    
    status = info.get("status")
    
    if status == "available":
        txt += (
            f"✅ <b>Доступно для взятия</b>\n\n"
            f"📋 <b>Условия:</b>\n"
            f"• 💰 Сумма: <b>{fmt_num(info['min'])}</b> – <b>{fmt_num(info['max'])}</b>\n"
            f"• ⏱ Срок: <b>{info['days']} дня</b>\n"
            f"• 📈 Процент: <b>{info['percent']}%</b>\n"
            f"• ⚠️ При просрочке: <b>БАН</b>\n\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👇 Возьми кредит:"
        )
    
    elif status == "active":
        txt += (
            f"⚠️ <b>АКТИВНЫЙ КРЕДИТ</b>\n\n"
            f"💰 Сумма: <b>{fmt_num(info['amount'])}</b> Tokens\n"
            f"📅 Осталось: <b>{info['days_left']} дн.</b>\n\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👇 Верни кредит:"
        )
    
    elif status == "blocked":
        txt += (
            f"🚫 <b>ЗАБЛОКИРОВАНО</b>\n\n"
            f"{info.get('reason', 'Вы заблокированы.')}\n\n"
            f"💬 Свяжитесь с админом: @admin"
        )
    
    return txt


def credit_history_text(user_id: int) -> str:
    history = get_credit_history(user_id, limit=10)
    if not history:
        return "📜 <b>История кредитов</b>\n\nПока пусто."
    
    txt = "📜 <b>ИСТОРИЯ КРЕДИТОВ</b>\n━━━━━━━━━━━━━━\n\n"
    for cid, amount, issued_at, due_at, returned_at, status in history:
        if issued_at and issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=TZ_MINSK)
        date_str = issued_at.strftime("%d.%m %H:%M") if issued_at else "?"
        
        if status == "returned":
            emoji = "✅"
            status_str = "Возвращён"
        elif status == "active":
            emoji = "⏳"
            status_str = "Активный"
        elif status == "overdue":
            emoji = "🚫"
            status_str = "Просрочен"
        else:
            emoji = "❓"
            status_str = status
        
        txt += f"{emoji} <b>{fmt_num(amount)}</b> — {status_str} ({date_str})\n"
    
    return txt


# ═══════════════ МАГАЗИН ═══════════════

def shop_text() -> str:
    return (
        f"🛒 <b>МАГАЗИН</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"<i>Всё за Telegram Stars ⭐</i>\n\n"
        f"👇 Выбери категорию:"
    )


def shop_category_text(category: str) -> str:
    category_names = {
        "tokens": ("💰", "TOKENS"),
        "cases": ("🎰", "КЕЙСЫ"),
        "boosts": ("⚡", "БУСТЫ"),
        "titles": ("🏷️", "ТИТУЛЫ"),
        "vip": ("👑", "VIP"),
        "xp": ("⭐", "БУСТ XP"),
    }
    icon, name = category_names.get(category, ("🛒", "МАГАЗИН"))
    
    return (
        f"{icon} <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"👇 Выбери товар:"
    )


def shop_item_text(item_id: str) -> str:
    it = get_shop_item_by_id(item_id)
    if not it:
        return "❌ Товар не найден"
    
    price_parts = []
    if it.get("stars"):
        price_parts.append(f"{it['stars']} ⭐")
    if it.get("tokens"):
        price_parts.append(f"{fmt_num(it['tokens'])} Tokens")
    price = " / ".join(price_parts) if price_parts else "—"
    
    return (
        f"🛒 <b>{it['name']}</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📝 {it.get('desc', '')}\n\n"
        f"💰 Цена: <b>{price}</b>\n\n"
        f"👇 Выбери способ оплаты:"
    )


# ═══════════════ КЕЙСЫ (в магазине) ═══════════════

def case_text(case_id: str) -> str:
    case = get_case_by_id(case_id)
    if not case:
        return "❌ Кейс не найден"
    
    txt = (
        f"{case['name']}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📝 {case.get('desc', '')}\n\n"
        f"💰 Цена: <b>{case['stars']} ⭐</b>\n\n"
        f"🎁 <b>Что внутри:</b>\n"
    )
    
    for r in case.get("rewards", []):
        t = r.get("type")
        chance = r.get("chance", 0)
        if t == "tokens":
            txt += f"• 💰 {fmt_num(r['amount'])} Tokens — {chance}%\n"
        elif t == "boost":
            txt += f"• ⚡ Буст ×{r['mult']} на {r['minutes']} мин — {chance}%\n"
        elif t == "title":
            txt += f"• 🏷️ Титул «{r['title']}» — {chance}%\n"
        elif t == "vip":
            txt += f"• 👑 VIP {r['vip_level']} — {chance}%\n"
    
    txt += "\n👇 Купить:"
    return txt


def case_result_text(case_name: str, reward_text: str) -> str:
    return (
        f"🎉 <b>КЕЙС «{case_name}» ОТКРЫТ!</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎁 Тебе выпало:\n"
        f"<b>{reward_text}</b>\n\n"
        f"📦 Предмет добавлен в инвентарь"
    )


# ═══════════════ VIP ═══════════════

def vip_text(user_id: int) -> str:
    tiers = get_vip_tiers()
    current = get_vip_tier(user_id)
    expires = get_vip_expires(user_id)
    
    txt = "👑 <b>VIP КЛУБ</b>\n━━━━━━━━━━━━━━\n\n"
    
    if current > 0 and expires:
        info = get_vip_tier_info(current)
        if info:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=TZ_MINSK)
            days = max((expires - datetime.now(TZ_MINSK)).days, 0)
            txt += f"Твой статус: {info['icon']} <b>VIP {info['id']} — {info['name']}</b>\n"
            txt += f"⏱ Осталось: <b>{days}</b> дней\n\n"
    else:
        txt += "Твой статус: <b>Нет VIP</b>\n\n"
    
    txt += "━━━━━━━━━━━━━━\n\n<b>Доступные VIP:</b>\n\n"
    for t in tiers:
        txt += (
            f"{t['icon']} <b>VIP {t['id']} — {t['name']}</b> — {t['stars']} ⭐\n"
            f"   💸 Кэшбэк {t['cashback']}%\n"
            f"   🎁 Бонус +{fmt_num(t['bonus'])} Tokens\n"
            f"   ⏱ Срок {t['duration_days']} дней\n\n"
        )
    txt += "👇 Выбери VIP:"
    return txt


# ═══════════════ XP ═══════════════

def xp_text(user_id: int) -> str:
    packs = get_xp_packs()
    xp = get_xp(user_id)
    level = xp // 100
    bar = make_xp_bar(xp)
    
    txt = (
        f"⭐ <b>БУСТ XP</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📊 Твой XP: <b>{fmt_num(xp)}</b>\n"
        f"🎖 Уровень: <b>{level}</b>\n"
        f"{bar}\n\n"
        f"<b>Доступные пакеты:</b>\n\n"
    )
    for p in packs:
        txt += f"• +{p['xp']} XP — <b>{p['stars']} ⭐</b>\n"
    txt += "\n👇 Выбери пакет:"
    return txt


# ═══════════════ ЗАДАНИЯ ═══════════════

def quests_text(user_id: int) -> str:
    quests = get_user_daily_quests(user_id)
    txt = "🎯 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n━━━━━━━━━━━━━━\n\n"
    for q in quests:
        if q["claimed"]:
            txt += f"✔️ {q['name']}\n"
        elif q["completed"]:
            txt += f"✅ {q['name']} → Забрать!\n"
        else:
            txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
    txt += "\n💡 Задания обновляются раз в 24 часа"
    return txt


def level_rewards_text() -> str:
    rewards = get_level_rewards()
    txt = "🏆 <b>НАГРАДЫ ЗА УРОВНИ</b>\n━━━━━━━━━━━━━━\n\n"
    for r in rewards:
        if r["type"] == "tokens":
            v = f"+{fmt_num(r['value'])} Tokens"
        elif r["type"] == "cashback":
            v = f"кэшбэк +{r['value']}%"
        elif r["type"] == "vip_games":
            v = "VIP-игры"
        elif r["type"] == "vip_tier":
            v = f"VIP {r['value']} бесплатно"
        else:
            v = str(r["value"])
        txt += f"🏆 Уровень <b>{r['level']}</b> — {v}\n"
    return txt


# ═══════════════ ТУРНИР ═══════════════

def tournament_text() -> str:
    t = get_active_tournament()
    if not t:
        return (
            "🏆 <b>ТУРНИР</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "😴 Сейчас нет активного турнира\n\n"
            f"Следи за анонсами в канале:\n{TOURNAMENT_CHANNEL}"
        )
    
    tid, name, started, ends, p1, p2, p3 = t
    top = get_tournament_top(tid, 10)
    
    if ends and ends.tzinfo is None:
        ends = ends.replace(tzinfo=TZ_MINSK)
    ends_str = ends.strftime('%d.%m %H:%M') if ends else "?"
    
    txt = f"🏆 <b>{name}</b>\n━━━━━━━━━━━━━━\n\n"
    txt += f"⏱ До: <b>{ends_str}</b>\n\n"
    txt += f"🥇 1 место — <b>{fmt_num(p1)}</b> Tokens\n"
    txt += f"🥈 2 место — <b>{fmt_num(p2)}</b> Tokens\n"
    txt += f"🥉 3 место — <b>{fmt_num(p3)}</b> Tokens\n\n"
    txt += "📊 <b>Топ-10:</b>\n\n"
    
    if not top:
        txt += "Пока никто не играл"
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, total) in enumerate(top):
            m = medals[i] if i < 3 else f"{i+1}."
            txt += f"{m} {uname} — {fmt_num(total)} Tokens\n"
    return txt


# ═══════════════ РЕФКА ═══════════════

def ref_text(user_id: int, username: str) -> str:
    count, earnings = get_ref_stats(user_id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    return (
        f"🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{fmt_num(earnings)}</b> Tokens\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎁 За каждого друга: <b>+{fmt_num(REF_BONUS_REFERRER)}</b> тебе и ему\n"
        f"📈 +{REF_COMMISSION_PERCENT}% с его выигрышей\n\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{link}</code>"
    )


def ref_list_text(user_id: int) -> str:
    refs = get_referrals(user_id)
    if not refs:
        return "👥 <b>Мои рефералы</b>\n\nПока никого."
    
    txt = f"👥 <b>МОИ РЕФЕРАЛЫ ({len(refs)})</b>\n━━━━━━━━━━━━━━\n\n"
    for i, (uid, uname) in enumerate(refs[:30], 1):
        txt += f"{i}. <b>{uname or f'user_{uid}'}</b>\n"
    if len(refs) > 30:
        txt += f"\n...и ещё {len(refs) - 30}"
    return txt


def ref_top_text() -> str:
    rows = get_ref_top(10)
    if not rows:
        return "🏆 <b>Топ рефереров</b>\n\nПока пусто."
    
    txt = "🏆 <b>ТОП РЕФЕРЕРОВ</b>\n━━━━━━━━━━━━━━\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, uname, cnt, earn) in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        txt += f"{m} <b>{uname or f'user_{uid}'}</b> — {cnt} 👥 | {fmt_num(earn)} Tokens\n"
    return txt


# ═══════════════ РЫНОК ═══════════════

def market_text() -> str:
    lots = get_market_lots()
    return (
        f"🏪 <b>РЫНОК</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📊 Активных лотов: <b>{len(lots)}</b>\n\n"
        f"👇 Выбери раздел:"
    )


def market_lots_text(page: int = 0, per_page: int = 5) -> str:
    lots = get_market_lots()
    if not lots:
        return (
            "🏪 <b>РЫНОК</b>\n\n"
            "😢 Пока пусто...\n\n"
            "Будь первым!"
        )
    
    start = page * per_page
    end = start + per_page
    page_lots = lots[start:end]
    
    txt = f"🏪 <b>РЫНОК</b>\n━━━━━━━━━━━━━━\n\n"
    txt += f"Стр. {page+1} | Лотов: <b>{len(lots)}</b>\n\n"
    
    for i, lot in enumerate(page_lots):
        idx = start + i
        t = lot.get("type")
        if t == "boost":
            label = f"⚡ ×{lot['payload'].get('mult', '?')} / {lot['payload'].get('minutes', '?')}м"
        elif t == "title":
            label = f"🏷️ {lot['payload'].get('title', '?')}"
        elif t == "vip":
            label = f"👑 VIP {lot['payload'].get('vip_level', '?')}"
        else:
            label = "❓"
        txt += f"{idx+1}. {label} — <b>{fmt_num(lot['price'])}</b> Tokens\n"
        txt += f"   👤 @{lot.get('seller_name', '?')}\n\n"
    
    return txt


def market_mylots_text(user_id: int) -> str:
    lots = get_market_lots()
    my_lots = [l for l in lots if l["seller_id"] == user_id]
    
    if not my_lots:
        return "📦 <b>Мои лоты</b>\n\nУ вас нет лотов."
    
    txt = f"📦 <b>МОИ ЛОТЫ ({len(my_lots)})</b>\n━━━━━━━━━━━━━━\n\n"
    for i, lot in enumerate(my_lots, 1):
        t = lot.get("type")
        if t == "boost":
            label = f"⚡ ×{lot['payload'].get('mult', '?')} / {lot['payload'].get('minutes', '?')}м"
        elif t == "title":
            label = f"🏷️ {lot['payload'].get('title', '?')}"
        elif t == "vip":
            label = f"👑 VIP {lot['payload'].get('vip_level', '?')}"
        else:
            label = "❓"
        txt += f"{i}. {label} — <b>{fmt_num(lot['price'])}</b> Tokens\n"
    return txt


# ═══════════════ ИНВЕНТАРЬ ═══════════════

def inventory_text(user_id: int, filter_type: str = None) -> str:
    inv = get_inventory(user_id)
    if filter_type:
        inv = [it for it in inv if it.get("type") == filter_type]
    
    titles_map = {
        None: "🎒 ИНВЕНТАРЬ",
        "boost": "⚡ БУСТЫ",
        "title": "🏷️ ТИТУЛЫ",
        "vip": "👑 VIP",
    }
    title = titles_map.get(filter_type, "🎒 ИНВЕНТАРЬ")
    
    if not inv:
        return f"{title}\n━━━━━━━━━━━━━━\n\nПусто..."
    
    txt = f"{title}\n━━━━━━━━━━━━━━\n\n"
    txt += f"📦 Всего: <b>{len(inv)}</b>\n\n"
    
    for it in inv[:10]:
        t = it.get("type")
        if t == "boost":
            txt += f"⚡ ×{it.get('mult', '?')} / {it.get('minutes', '?')}м\n"
        elif t == "title":
            txt += f"🏷️ {it.get('title', '?')}\n"
        elif t == "vip":
            txt += f"👑 VIP {it.get('vip_level', '?')}\n"
    
    if len(inv) > 10:
        txt += f"\n...и ещё {len(inv) - 10}"
    return txt


def inventory_item_text(inv_id: str, user_id: int) -> str:
    item = find_inventory_item(user_id, inv_id)
    if not item:
        return "❌ Предмет не найден"
    
    t = item.get("type")
    if t == "boost":
        return (
            f"📦 <b>Буст</b>\n\n"
            f"⚡ Множитель: <b>×{item.get('mult')}</b>\n"
            f"⏱ Время: <b>{item.get('minutes')} мин</b>\n\n"
            f"👇 Что делаем?"
        )
    if t == "title":
        return (
            f"📦 <b>Титул</b>\n\n"
            f"🏷️ Название: <b>{item.get('title')}</b>\n\n"
            f"👇 Что делаем?"
        )
    if t == "vip":
        return (
            f"📦 <b>VIP</b>\n\n"
            f"👑 Уровень: <b>{item.get('vip_level')}</b>\n\n"
            f"👇 Что делаем?"
        )
    return "📦 <b>Предмет</b>"


# ═══════════════ ПОКУПКИ (админ) ═══════════════

def purchases_text(limit: int = 20) -> str:
    rows = get_purchases(limit)
    if not rows:
        return "📋 <b>Покупок пока нет</b>"
    
    txt = "📋 <b>ПОСЛЕДНИЕ ПОКУПКИ</b>\n━━━━━━━━━━━━━━\n\n"
    for uid, uname, ptype, iname, price, source, created in rows:
        time_str = created.strftime("%d.%m %H:%M") if created else "—"
        txt += (
            f"👤 @{uname or f'id{uid}'}\n"
            f"💎 {iname} — {price}\n"
            f"📍 {source} | 🕐 {time_str}\n\n"
        )
    return txt


# ═══════════════ ПРАВИЛА / HELP ═══════════════

def rules_text() -> str:
    return (
        f"📖 <b>ПРАВИЛА И ЛИМИТЫ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Экономика:</b>\n"
        f"• Макс. баланс: <b>{fmt_num(MAX_BALANCE)}</b> Tokens\n"
        f"• Макс. банк: <b>{fmt_num(MAX_BANK)}</b> Tokens\n"
        f"• Лимит стола: <b>{fmt_num(MAX_WIN)}</b> Tokens\n"
        f"• Макс. ставка: <b>{fmt_num(MAX_BET)}</b> Tokens\n\n"
        f"📈 <b>Банк:</b>\n"
        f"• Проценты: <b>5% в день</b>\n"
        f"• Начисляются только до <b>{fmt_num(MAX_BANK_INTEREST)}</b> Tokens\n\n"
        f"💳 <b>Кредиты:</b>\n"
        f"• Сумма: <b>{fmt_num(CREDIT_MIN)}</b> – <b>{fmt_num(CREDIT_MAX)}</b>\n"
        f"• Срок: <b>{CREDIT_DAYS} дня</b>\n"
        f"• Процент: <b>{CREDIT_PERCENT}%</b>\n"
        f"• При просрочке — <b>БАН</b>\n\n"
        f"🎮 <b>Игры:</b>\n"
        f"• Рулетка: ×1.95 – ×35\n"
        f"• Слоты: ×9 – ×90\n"
        f"• Монетка: ×1.95\n"
        f"• Мины: до ×20\n\n"
        f"🎁 <b>Бонусы:</b>\n"
        f"• Ежедневный: <b>+{fmt_num(DAILY_BONUS)}</b> Tokens\n"
        f"• Новичку: <b>+{fmt_num(START_BONUS)}</b> Tokens\n"
        f"• Реферал: <b>+{fmt_num(REF_BONUS_REFERRER)}</b> за друга\n"
    )


def all_commands_text() -> str:
    """Список всех команд бота."""
    txt = "📋 <b>ВСЕ КОМАНДЫ БОТА</b>\n━━━━━━━━━━━━━━\n\n"
    
    for category, commands in ALL_BOT_COMMANDS.items():
        txt += f"<b>{category}</b>\n"
        for cmd, desc in commands:
            txt += f"  <code>{cmd}</code> — {desc}\n"
        txt += "\n"
    
    return txt
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 8/15 — ХЕНДЛЕРЫ КОМАНД (БАЗОВЫЕ)
# ═══════════════════════════════════════════════════════════════

# Инициализация бота и диспетчера (в конце файла — обязательно)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ═══════════════ /start ═══════════════

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # 🔒 Проверка: новый ли игрок?
    existing_user = get_user(user_id)
    is_new_user = existing_user is None
    
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n\nОбратитесь к @admin", parse_mode="HTML")
        return
    
    # ─── Рефералка (только для новых) ───
    args = message.text.split()
    if is_new_user and len(args) >= 2 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                ok = set_referrer(user_id, referrer_id)
                if ok:
                    await message.answer(
                        f"🎉 <b>Ты пришёл по приглашению!</b>\n\n"
                        f"💰 Тебе начислено <b>+{fmt_num(REF_BONUS_REFERRED)}</b> Tokens\n"
                        f"👤 Пригласивший тоже получил бонус",
                        parse_mode="HTML"
                    )
                    # Уведомление рефереру в тот же чат
                    try:
                        ref_user = get_user(referrer_id)
                        ref_name = ref_user[0] if ref_user else f"user_{referrer_id}"
                        await message.answer(
                            f"🎉 <b>НОВЫЙ РЕФЕРАЛ!</b>\n"
                            f"━━━━━━━━━━━━━━\n\n"
                            f"👤 Игрок: <b>{username}</b>\n"
                            f"💰 Ты получил: <b>+{fmt_num(REF_BONUS_REFERRER)}</b> Tokens\n\n"
                            f"📊 Всего рефералов: <b>{get_ref_stats(referrer_id)[0]}</b>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[ref start] {e}")
    
    # ─── Уведомление админу о новом игроке ───
    if is_new_user:
        try:
            total_players = get_total_players()
            now = datetime.now(TZ_MINSK).strftime("%d.%m %H:%M")
            
            # Источник
            source = "Прямая ссылка"
            if len(args) >= 2 and args[1].startswith("ref_"):
                source = f"Реферал от {args[1].replace('ref_', '')}"
            elif message.chat.type != "private":
                source = f"Из группы «{message.chat.title}»"
            
            admin_text = (
                f"🎉 <b>НОВЫЙ ИГРОК!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 Имя: <b>{message.from_user.full_name}</b>\n"
                f"🔗 Username: @{message.from_user.username or 'нет'}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"🕐 Время: <b>{now}</b>\n\n"
                f"📍 Источник: <b>{source}</b>\n"
                f"💰 Стартовый бонус: <b>+{fmt_num(START_BONUS)} Tokens</b>\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"📊 Всего игроков: <b>{total_players}</b>"
            )
            await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"[notify admin new] {e}")
    
    # ─── Ежедневный вход (streak) ───
    streak, bonus = check_daily_login(user_id)
    if bonus > 0:
        await message.answer(
            f"🔥 <b>7 дней подряд!</b>\n\n"
            f"🎁 Жирный бонус: <b>+{fmt_num(bonus)}</b> Tokens",
            parse_mode="HTML"
        )
    
    # ─── Бонус новичка ───
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT got_start_bonus FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    got_bonus = row[0] if row and row[0] else False
    c.close()
    release_conn(conn)
    
    bonus_text = ""
    if not got_bonus:
        set_balance(user_id, START_BONUS)
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET got_start_bonus = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        c.close()
        release_conn(conn)
        bonus_text = f"\n\n🎁 <b>БОНУС НОВИЧКА: +{fmt_num(START_BONUS)} Tokens!</b>"
    
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    level = xp // 100
    rank = get_rank_name(level)
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""
    
    vip_tier = get_vip_tier(user_id)
    vip_line = ""
    if vip_tier > 0:
        info = get_vip_tier_info(vip_tier)
        if info:
            vip_line = f"\n{info['icon']} <b>VIP {info['id']} — {info['name']}</b>"
    
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"💎 <b>{fmt_num(balance)}</b> Tokens"
    
    is_private = message.chat.type == "private"
    
    # ─── Админ в ЛС ───
    if is_private and user_id == ADMIN_ID:
        txt = (
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>{username}</b>\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n\n"
            f"👇 Выбери раздел:"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
        return
    
    # ─── ЛС игрока ───
    if is_private:
        txt = (
            f"🎰 <b>Tokens</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👋 Привет, <b>{username}</b>!\n\n"
            f"🎖 {rank}{vip_line}{title_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b>{bonus_text}\n\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎮 Игры · 💳 Кредиты · 🎰 Кейсы\n"
            f"🛒 Магазин · 🎒 Инвентарь · 🏪 Рынок\n"
            f"👑 VIP · 🎯 Задания · 🔗 Рефералка\n\n"
            f"💡 Играй в группе или Mini App 👇"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=private_kb())
        
        # Inline-кнопка «Играть в группе»
        await message.answer(
            "👇 <b>Играть в группе:</b>",
            parse_mode="HTML",
            reply_markup=group_url_kb()
        )
    # ─── В группе ───
    else:
        await message.reply(
            f"🎰 <b>Tokens</b>\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"{bal_line}\n\n"
            f"💡 Играй командами:\n"
            f"<code>к 1000</code> — красное\n"
            f"<code>ч 1000</code> — чёрное\n"
            f"<code>спин 1000</code> — слоты\n"
            f"<code>мины 1000</code> — мины\n"
            f"<code>го</code> — запуск",
            parse_mode="HTML"
        )


# ═══════════════ /admin ═══════════════

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    
    txt = (
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{username}</b>\n"
        f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
        f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n\n"
        f"👇 Выбери раздел:"
    )
    await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())


# ═══════════════ /profile ═══════════════

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    await message.answer(
        profile_text(user_id, username),
        parse_mode="HTML",
        reply_markup=profile_kb()
    )


# ═══════════════ /balance ═══════════════

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    
    if is_unlimited(user_id):
        await message.answer(
            f"💰 <b>БАЛАНС</b>\n\n👤 {username}\n♾️ <b>БЕЗЛИМИТ</b>\n🏦 Банк: <b>{fmt_num(bank)}</b>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"💰 <b>БАЛАНС</b>\n\n👤 {username}\n💎 Баланс: <b>{fmt_num(balance)}</b>\n🏦 Банк: <b>{fmt_num(bank)}</b>",
            parse_mode="HTML"
        )


# ═══════════════ /top ═══════════════

@dp.message(Command("top"))
async def cmd_top(message: Message):
    await message.answer(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())


# ═══════════════ /shop ═══════════════

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    await message.answer(
        shop_text(),
        parse_mode="HTML",
        reply_markup=shop_categories_kb()
    )


# ═══════════════ /cases ═══════════════

@dp.message(Command("cases"))
async def cmd_cases(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    # Открываем категорию «Кейсы» в магазине
    await message.answer(
        shop_category_text("cases"),
        parse_mode="HTML",
        reply_markup=shop_items_kb("cases")
    )


# ═══════════════ /inventory ═══════════════

@dp.message(Command("inventory", "inv"))
async def cmd_inventory(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    await message.answer(
        inventory_text(user_id),
        parse_mode="HTML",
        reply_markup=inventory_main_kb()
    )


# ═══════════════ /ref ═══════════════

@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    await message.answer(
        ref_text(user_id, username),
        parse_mode="HTML",
        reply_markup=ref_kb()
    )


# ═══════════════ /refs (список рефералов) ═══════════════

@dp.message(Command("refs"))
async def cmd_refs(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    await message.answer(ref_list_text(user_id), parse_mode="HTML")


# ═══════════════ /ref_top (топ рефереров) ═══════════════

@dp.message(Command("ref_top"))
async def cmd_ref_top(message: Message):
    await message.answer(ref_top_text(), parse_mode="HTML")


# ═══════════════ /market ═══════════════

@dp.message(Command("market"))
async def cmd_market(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    await message.answer(
        market_text(),
        parse_mode="HTML",
        reply_markup=market_main_kb()
    )


# ═══════════════ /vip ═══════════════

@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        return
    
    await message.answer(
        vip_text(user_id),
        parse_mode="HTML",
        reply_markup=shop_items_kb("vip")
    )


# ═══════════════ /xp ═══════════════

@dp.message(Command("xp"))
async def cmd_xp(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        return
    
    await message.answer(
        xp_text(user_id),
        parse_mode="HTML",
        reply_markup=shop_items_kb("xp")
    )


# ═══════════════ /quests ═══════════════

@dp.message(Command("quests", "задания"))
async def cmd_quests(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        return
    
    await message.answer(
        quests_text(user_id),
        parse_mode="HTML",
        reply_markup=daily_quests_kb(user_id)
    )


# ═══════════════ /tournament ═══════════════

@dp.message(Command("tournament", "турнир"))
async def cmd_tournament(message: Message):
    await message.answer(tournament_text(), parse_mode="HTML")


# ═══════════════ /lang ═══════════════

@dp.message(Command("lang", "язык"))
async def cmd_lang(message: Message):
    await message.answer(
        "🌐 <b>Выбор языка</b>\n\n👇 Выбери язык:",
        parse_mode="HTML",
        reply_markup=lang_kb()
    )


# ═══════════════ /rules ═══════════════

@dp.message(Command("rules", "правила"))
async def cmd_rules(message: Message):
    await message.answer(rules_text(), parse_mode="HTML", reply_markup=back_to_main_kb())


# ═══════════════ /credits ═══════════════

@dp.message(Command("credits", "кредиты"))
async def cmd_credits(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    info = get_credit_amount_info(user_id)
    status = info.get("status")
    
    await message.answer(
        credits_text(user_id),
        parse_mode="HTML",
        reply_markup=credits_kb(status)
    )


# ═══════════════════════════════════════════════════════════════
# АДМИН-КОМАНДЫ
# ═══════════════════════════════════════════════════════════════

# ═══════════════ /give ═══════════════

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    
    # /give unlimited — безлимит себе
    if len(args) >= 2 and args[1].lower() in ["unlimited", "безлимит", "∞"]:
        set_unlimited(message.from_user.id, True)
        await message.answer("♾️ <b>БЕЗЛИМИТ АКТИВИРОВАН!</b>", parse_mode="HTML")
        return
    
    if len(args) >= 2 and args[1].lower() in ["off", "выкл"]:
        set_unlimited(message.from_user.id, False)
        await message.answer("✅ <b>БЕЗЛИМИТ ОТКЛЮЧЁН</b>", parse_mode="HTML")
        return
    
    # /give @username amount
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except Exception:
            return
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, amount)
        await message.answer(
            f"✅ <b>+{fmt_num(amount)}</b> → @{username}\n💎 {fmt_num(nb)}",
            parse_mode="HTML"
        )
        return
    
    # /give (reply) amount
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("❌ Ответь на сообщение или: <code>/give @user сумма</code>", parse_mode="HTML")
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except Exception:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, amount)
    await message.answer(
        f"✅ <b>+{fmt_num(amount)}</b> → {target.username or target.first_name}\n💎 {fmt_num(nb)}",
        parse_mode="HTML"
    )


# ═══════════════ /ban ═══════════════

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    elif len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        if uid:
            set_banned(uid, True)
            await message.answer(f"🚫 <b>@{username} забанен!</b>", parse_mode="HTML")
        else:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    
    if not target:
        await message.answer("❌ Ответь или <code>/ban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, True)
    await message.answer(f"🚫 <b>{target.username or target.first_name} забанен!</b>", parse_mode="HTML")


# ═══════════════ /unban ═══════════════

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    elif len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        if uid:
            set_banned(uid, False)
            await message.answer(f"✅ <b>@{username} разбанен!</b>", parse_mode="HTML")
        else:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    
    if not target:
        await message.answer("❌ Ответь или <code>/unban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, False)
    await message.answer(f"✅ <b>{target.username or target.first_name} разбанен!</b>", parse_mode="HTML")


# ═══════════════ /reset_all ═══════════════

@dp.message(Command("reset_all"))
async def cmd_reset_all(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, ОБНУЛИТЬ ВСЕХ", callback_data="confirm_reset_all")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")],
    ])
    await message.answer(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Это обнулит ВСЕХ игроков:\n"
        "• Балансы → 1000\n"
        "• Банк → 0\n"
        "• XP → 0\n"
        "• Рефералы → 0\n\n"
        "Это действие НЕОБРАТИМО. Продолжить?",
        parse_mode="HTML",
        reply_markup=kb
    )


# ═══════════════ /edit_user ═══════════════

@dp.message(Command("edit_user"))
async def cmd_edit_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: <code>/edit_user 6403424348</code> или <code>/edit_user @username</code>", parse_mode="HTML")
        return
    
    target = args[1]
    uid = None
    if target.startswith('@'):
        uid = get_user_id_by_username(target[1:])
    elif target.isdigit():
        uid = int(target)
    
    if not uid:
        await message.answer("❌ Игрок не найден", parse_mode="HTML")
        return
    
    user = get_user(uid)
    if not user:
        await message.answer("❌ Игрок не в базе", parse_mode="HTML")
        return
    
    uname = user[0] or f"user_{uid}"
    balance = get_balance(uid)
    bank = get_bank(uid)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 +1000", callback_data=f"adm_add_{uid}"),
         InlineKeyboardButton(text="💰 -1000", callback_data=f"adm_sub_{uid}")],
        [InlineKeyboardButton(text="🔄 Обнулить баланс", callback_data=f"adm_zero_{uid}")],
        [InlineKeyboardButton(text="📊 Обнулить статы", callback_data=f"adm_stats_{uid}")],
        [InlineKeyboardButton(text="👥 Обнулить рефералов", callback_data=f"adm_refs_{uid}")],
        [InlineKeyboardButton(text="🗑 Удалить игрока", callback_data=f"adm_del_{uid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])
    
    text = (
        f"👤 <b>УПРАВЛЕНИЕ ИГРОКОМ</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🎭 Имя: <b>{uname}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💎 Баланс: <b>{fmt_num(balance)}</b>\n"
        f"🏦 Банк: <b>{fmt_num(bank)}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ═══════════════ /games ═══════════════

@dp.message(Command("games"))
async def cmd_games_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    
    # /games_list
    if len(args) >= 2 and args[1].lower() == "list":
        txt = "🎮 <b>СТАТУС ИГР</b>\n━━━━━━━━━━━━━━\n\n"
        for key, name in GAME_NAMES.items():
            if key in ("crash", "plinko"):
                continue
            status = "❌ Выкл" if key in disabled_games else "✅ Вкл"
            txt += f"{status} {name}\n"
        await message.answer(txt, parse_mode="HTML")
        return
    
    # /games on slots / /games off slots
    if len(args) >= 3:
        action = args[1].lower()
        game = args[2].lower()
        
        if game not in GAME_NAMES:
            await message.answer(f"❌ Игра «{game}» не найдена", parse_mode="HTML")
            return
        
        if action == "off":
            disabled_games.add(game)
            save_disabled_games()
            await message.answer(f"❌ <b>{GAME_NAMES[game]}</b> выключена", parse_mode="HTML")
        elif action == "on":
            disabled_games.discard(game)
            save_disabled_games()
            await message.answer(f"✅ <b>{GAME_NAMES[game]}</b> включена", parse_mode="HTML")
        else:
            await message.answer("Использование: <code>/games on/off slots</code>", parse_mode="HTML")
        return
    
    await message.answer(
        "Использование:\n"
        "<code>/games on slots</code>\n"
        "<code>/games off slots</code>\n"
        "<code>/games list</code>",
        parse_mode="HTML"
    )


# ═══════════════ /event ═══════════════

@dp.message(Command("event"))
async def cmd_event(message: Message):
    global event_double
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
        await message.answer(
            f"🎰 <b>ИВЕНТ ×2</b>\n\nСтатус: <b>{status}</b>\n\n"
            f"<code>/event on</code> — включить\n"
            f"<code>/event off</code> — выключить",
            parse_mode="HTML"
        )
        return
    mode = args[1].lower()
    if mode == "on":
        event_double = True
        await message.answer("🎰 <b>ИВЕНТ ×2 ВКЛЮЧЁН!</b>", parse_mode="HTML")
    elif mode == "off":
        event_double = False
        await message.answer("🎰 <b>ИВЕНТ ×2 ВЫКЛЮЧЕН</b>", parse_mode="HTML")


# ═══════════════ /maintenance ═══════════════

@dp.message(Command("maintenance"))
async def cmd_maintenance(message: Message):
    global maintenance_on
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
        await message.answer(
            f"🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nСтатус: <b>{status}</b>",
            parse_mode="HTML"
        )
        return
    sub = args[1].lower()
    if sub == "on":
        maintenance_on = True
        await message.answer("🛠️ <b>ТЕХ.РАБОТЫ ВКЛЮЧЕНЫ</b>", parse_mode="HTML")
    elif sub == "off":
        maintenance_on = False
        await message.answer("✅ <b>ТЕХ.РАБОТЫ ВЫКЛЮЧЕНЫ</b>", parse_mode="HTML")


# ═══════════════ /set_rates ═══════════════

@dp.message(Command("set_rates"))
async def cmd_set_rates(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    
    # /set_rates on
    if len(args) >= 2 and args[1].lower() == "on":
        set_setting("auto_rates", "on")
        await message.answer(
            "✅ <b>АВТОРАССЫЛКА ВКЛЮЧЕНА</b>\n\n"
            "Бот будет напоминать каждый день в 10:00 МСК.",
            parse_mode="HTML"
        )
        return
    
    # /set_rates off
    if len(args) >= 2 and args[1].lower() == "off":
        set_setting("auto_rates", "off")
        await message.answer(
            "🔕 <b>АВТОРАССЫЛКА ВЫКЛЮЧЕНА</b>\n\n"
            "Ручной запуск: <code>/set_rates</code>",
            parse_mode="HTML"
        )
        return
    
    # /set_rates — ручной запуск ввода
    rates_input_state[message.from_user.id] = {"step": "gram"}
    await message.answer(
        "💱 <b>ОБНОВЛЕНИЕ КУРСОВ</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "💰 Сколько <b>Gram</b> за 10 000 Tokens?\n"
        "Пример: <code>1000</code>\n\n"
        "❌ Отмена: /admin",
        parse_mode="HTML"
    )



# ЧАСТЬ 9/15 — ХЕНДЛЕРЫ ИГР В ГРУППЕ (КРАСИВЫЕ)
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ВСПОМОГАТЕЛЬНЫЕ ═══════════════

def check_bet_limit(game: str, bet: int) -> tuple:
    """
    Проверяет лимит ставки для игры.
    Возвращает (ok: bool, сообщение_или_None).
    """
    max_bet = GAME_BET_LIMITS.get(game, MAX_BET)
    if bet > max_bet:
        return False, (
            f"⚠️ <b>ЛИМИТ СТАВКИ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎮 Игра: <b>{GAME_NAMES.get(game, game)}</b>\n"
            f"💰 Макс. ставка: <b>{fmt_num(max_bet)}</b> Tokens\n"
            f"📊 Твоя: <b>{fmt_num(bet)}</b>\n\n"
            f"💡 Уменьши сумму."
        )
    return True, None


def is_credit_locked(user_id: int) -> bool:
    """Заблокирован ли игрок по кредиту."""
    return is_credit_blocked(user_id)


# ═══════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ТЕКСТОВЫЙ ХЕНДЛЕР ДЛЯ ГРУПП
# ═══════════════════════════════════════════════════════════════

@dp.message(F.text, F.chat.type != "private")
async def text_handler_group(message: Message):
    logger.info(f"[GROUP] text={message.text!r} chat={message.chat.id}")
    if not message.text:
        return
    if not message.from_user or message.from_user.is_bot:
        return
    
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    
    ensure_user(user_id, username)
    
    if chat_id < 0:
        track_group_member(chat_id, user_id, username)
    
    if is_banned(user_id):
        await message.reply("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    
    if maintenance_on and user_id != ADMIN_ID:
        await send_temp(chat_id,
            "🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nБот временно недоступен. Попробуй позже!",
            parse_mode="HTML"
        )
        return
    
    # ─── Блокировка кредитом ───
    if is_credit_locked(user_id) and user_id != ADMIN_ID:
        await message.reply(
            "🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n\n"
            "⚠️ У вас непогашенный кредит.\n"
            "Верните его, чтобы играть.",
            parse_mode="HTML"
        )
        return
    
    # ─── Короткие команды ───
    if text in ["б", "баланс"]:
        bal = get_balance(user_id)
        bank = get_bank(user_id)
        xp = get_xp(user_id)
        level = xp // 100
        rank = get_rank_name(level)
        
        if is_unlimited(user_id):
            await message.reply(
                f"💰 <b>{username}</b>\n"
                f"🎖 {rank}\n"
                f"♾️ <b>БЕЗЛИМИТ</b>\n"
                f"🏦 Банк: <b>{fmt_num(bank)}</b>",
                parse_mode="HTML"
            )
        else:
            await message.reply(
                f"💰 <b>{username}</b>\n"
                f"🎖 {rank}\n"
                f"💎 <b>{fmt_num(bal)}</b> Tokens\n"
                f"🏦 Банк: <b>{fmt_num(bank)}</b>",
                parse_mode="HTML"
            )
        return
    
    if text in ["топ", "top"]:
        await message.reply(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())
        return
    
    if text in ["профиль", "я"]:
        await message.reply(profile_text(user_id, username), parse_mode="HTML")
        return
    
    if text in ["задания", "квесты", "quests"]:
        await message.reply(quests_text(user_id), parse_mode="HTML", reply_markup=daily_quests_kb(user_id))
        return
    
    if text in ["банк"]:
        await message.reply(bank_text(user_id, username), parse_mode="HTML", reply_markup=bank_kb())
        return
    
    if text in ["кредиты", "кредит"]:
        info = get_credit_amount_info(user_id)
        await message.reply(
            credits_text(user_id),
            parse_mode="HTML",
            reply_markup=credits_kb(info.get("status", "available"))
        )
        return
    
    if text in ["бонус", "bonus", "ежедневка"]:
        can, left = get_daily_status(user_id)
        if can:
            claim_daily(user_id)
            nb = get_balance(user_id)
            await message.reply(
                f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 +<b>{fmt_num(DAILY_BONUS)}</b> Tokens\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
                f"⏳ Следующий через 24ч",
                parse_mode="HTML"
            )
        else:
            await message.reply(f"⏳ Через <b>{fmt_time_left(left)}</b>", parse_mode="HTML")
        return
    
    if text in ["игры", "игра"]:
        await message.reply(
            f"🎮 <b>ИГРЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎡 <b>Рулетка:</b> <code>к 1000</code>, <code>ч 1000</code>, <code>з 1000</code>\n"
            f"🎰 <b>Слоты:</b> <code>спин 1000</code>\n"
            f"🪙 <b>Монетка:</b> <code>орёл 1000</code> / <code>решка 1000</code>\n"
            f"🃏 <b>Блэкджек:</b> <code>бж 1000</code>\n"
            f"💣 <b>Мины:</b> <code>мины 1000</code>\n"
            f"⚔️ <b>Дуэль:</b> <code>дуэль 1000 @user</code>\n\n"
            f"🕐 <code>го</code> — запуск рулетки",
            parse_mode="HTML"
        )
        return
    
    if text in ["лог", "log"]:
        rows = get_last_roulette_results(10, chat_id=chat_id)
        if not rows:
            await message.reply("📜 <b>История пуста</b>", parse_mode="HTML")
            return
        
        txt = "📜 <b>ИСТОРИЯ РУЛЕТКИ</b>\n━━━━━━━━━━━━━━\n\n"
        for row in rows:
            detail = row[0] if isinstance(row, (tuple, list)) else row
            parts_d = str(detail).split()
            if len(parts_d) >= 2:
                num, color = parts_d[0], parts_d[-1]
                txt += f"{color} {num}\n"
            else:
                txt += f"{detail}\n"
        txt += "\n━━━━━━━━━━━━━━\n📊 Последние 10 раундов"
        await message.reply(txt, parse_mode="HTML")
        return 
    # ─── БАНК: положить / снять ───
    if len(parts) == 3 and parts[0] == "банк" and parts[1] == "положить":
        try:
            amount = int(parts[2])
        except Exception:
            return
        if amount < 1:
            await message.reply("❌ Мин. 1 Tokens")
            return
        bal = get_balance(user_id)
        if bal < amount and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        set_balance(user_id, -amount)
        new_bank = set_bank(user_id, amount)
        new_bal = get_balance(user_id)
        await message.reply(
            f"🏦 <b>В БАНК</b>\n\n"
            f"💰 -<b>{fmt_num(amount)}</b>\n"
            f"💎 Баланс: <b>{fmt_num(new_bal)}</b>\n"
            f"🏦 Банк: <b>{fmt_num(new_bank)}</b>",
            parse_mode="HTML"
        )
        return
    
    if len(parts) == 3 and parts[0] == "банк" and parts[1] == "снять":
        try:
            amount = int(parts[2])
        except Exception:
            return
        bank = get_bank(user_id)
        if bank < amount:
            await message.reply(f"❌ В банке {fmt_num(bank)}")
            return
        set_bank(user_id, -amount)
        new_bal = set_balance(user_id, amount)
        new_bank = get_bank(user_id)
        await message.reply(
            f"🏦 <b>ИЗ БАНКА</b>\n\n"
            f"💰 +<b>{fmt_num(amount)}</b>\n"
            f"💎 Баланс: <b>{fmt_num(new_bal)}</b>\n"
            f"🏦 Банк: <b>{fmt_num(new_bank)}</b>",
            parse_mode="HTML"
        )
        return
    
    # ─── ПЕРЕВОД ───
    if parts and parts[0] == "п":
        if len(parts) < 2:
            await message.reply("💸 Ответь и напиши: <code>п 1000</code>", parse_mode="HTML")
            return
        if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
            await message.reply("❌ Ответь на сообщение!")
            return
        try:
            amount = int(parts[1])
        except Exception:
            return
        if amount < 1:
            await message.reply("❌ Мин. 1")
            return
        target = message.reply_to_message.from_user
        if target.id == user_id:
            await message.reply("❌ Себе нельзя")
            return
        bal = get_balance(user_id)
        if bal < amount and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        ensure_user(target.id, target.username or target.first_name)
        set_balance(user_id, -amount)
        set_balance(target.id, amount)
        nb = get_balance(user_id)
        nt = get_balance(target.id)
        await message.reply(
            f"💸 <b>ПЕРЕВОД</b>\n\n"
            f"💰 <b>{fmt_num(amount)}</b> → {target.username or target.first_name}\n"
            f"💎 Твой: <b>{fmt_num(nb)}</b> | Его: <b>{fmt_num(nt)}</b>",
            parse_mode="HTML"
        )
        return
    
    # ─── ОТМЕНА СТАВОК ───
    if text in ["отмена", "отменить"]:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            for b in active_bets[chat_id]["bets"]:
                set_balance(b["user_id"], b["bet_total"])
            del active_bets[chat_id]
            await send_temp(chat_id, f"❌ <b>Отменено ({count} ставок)</b>", parse_mode="HTML")
        return
    
    # ═══════════════ РУЛЕТКА: СТАВКИ ═══════════════
    
    if len(parts) == 2 and parts[0] in ["к", "ч", "з"]:
        if is_game_disabled("roulette") and user_id != ADMIN_ID:
            await send_temp(chat_id,
                "⚠️ <b>ИГРА ВЫКЛЮЧЕНА</b>\n\n"
                "🎡 Рулетка временно недоступна.\n"
                "🙏 Приносим извинения!",
                parse_mode="HTML"
            )
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        if bet < 10:
            await message.reply("❌ Мин. ставка: <b>10</b> Tokens", parse_mode="HTML")
            return
        
        ok, err = check_bet_limit("roulette", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply(
                f"❌ <b>Недостаточно!</b>\n\n"
                f"💎 Баланс: <b>{fmt_num(bal)}</b>\n"
                f"💰 Нужно: <b>{fmt_num(bet)}</b>",
                parse_mode="HTML"
            )
            return
        
        set_balance(user_id, -bet)
        bet_type = {"к": "red", "ч": "black", "з": "green"}[parts[0]]
        
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username,
            "type": bet_type, "bet": bet, "bet_total": bet
        })
        
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        icon = {"red": "🔴", "black": "⚫", "green": "🟢"}[bet_type]
        
        # Красивое сообщение со спойлером
        bets_list = ""
        for i, b in enumerate(bets, 1):
            bi = {"red": "🔴", "black": "⚫", "green": "🟢"}[b["type"]]
            bets_list += f"{i}. <b>@{b['username']}</b> — {fmt_num(b['bet'])} ({bi})\n"
        
        txt = (
            f"📊 <b>СТАВКИ ПРИНЯТЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>@{username}</b>\n"
            f"{icon} × <b>{fmt_num(bet)}</b>\n\n"
            f"<blockquote expandable>📋 <b>ВСЕ СТАВКИ ({len(bets)})</b>\n"
            f"{bets_list}\n"
            f"💰 <b>Банк:</b> {fmt_num(total_bank)} Tokens</blockquote>\n\n"
            f"🕐 Напиши «<code>го</code>» чтобы запустить"
        )
        
        # Удаляем предыдущие сообщения (если есть)
        await message.reply(txt, parse_mode="HTML")
        return
    
    # ═══════════════ МУЛЬТИ-СТАВКА (диапазоны) ═══════════════
    
    bet, ranges = parse_multi_bet(text)
    if bet and ranges:
        if is_game_disabled("roulette") and user_id != ADMIN_ID:
            await send_temp(chat_id, "⚠️ Рулетка выключена", parse_mode="HTML")
            return
        
        if bet < 10:
            await message.reply("❌ Мин. 10")
            return
        
        total_bet = bet * len(ranges)
        ok, err = check_bet_limit("roulette", total_bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < total_bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! Нужно {fmt_num(total_bet)}")
            return
        
        set_balance(user_id, -total_bet)
        
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username, "type": "ranges",
            "bet": bet, "bet_total": total_bet, "ranges": ranges
        })
        
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        ranges_str = " ".join([f"{a}-{z}" if a != z else str(a) for (a, z) in ranges])
        
        await message.reply(
            f"📊 <b>МУЛЬТИ-СТАВКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎯 Диапазоны: <b>{ranges_str}</b>\n"
            f"💰 <b>{fmt_num(bet)}</b> × {len(ranges)} = <b>{fmt_num(total_bet)}</b>\n"
            f"📈 Банк: <b>{fmt_num(total_bank)}</b>\n\n"
            f"🕐 <code>го</code>",
            parse_mode="HTML"
        )
        return
    
    # ═══════════════ ЗАПУСК РУЛЕТКИ: «го» ═══════════════
    
    if text == "го":
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет ставок")
            return
        
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        unlimited_in = any(is_unlimited(b["user_id"]) for b in bets)
        bank_line = "♾️" if unlimited_in else f"{fmt_num(total_bank)}"
        
        # Красивая анимация
        msg = await message.reply(
            f"🎡 <b>РУЛЕТКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎲 Крутится...\n\n"
            f"🔴 ⚫ 🔴 ⚫ 🔴",
            parse_mode="HTML"
        )
        
        for i, frame in enumerate(ANIM_ROULETTE):
            await asyncio.sleep(ANIM_ROULETTE_DELAYS[i] if i < len(ANIM_ROULETTE_DELAYS) else 0.3)
            try:
                await msg.edit_text(
                    f"🎡 <b>РУЛЕТКА</b>\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"🎲 Крутится...\n\n"
                    f"{frame}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        result = random.randint(0, 36)
        color_emoji = get_roulette_color(result)
        
        winners = []
        losers = []
        
        for b in bets:
            win_amount = 0
            
            if b["type"] == "red" and result in RED_NUMBERS:
                win_amount = int(b["bet_total"] * ROULETTE_PAYOUTS["red"])
            elif b["type"] == "black" and result in BLACK_NUMBERS:
                win_amount = int(b["bet_total"] * ROULETTE_PAYOUTS["black"])
            elif b["type"] == "green" and result == 0:
                win_amount = int(b["bet_total"] * ROULETTE_PAYOUTS["zero"])
            elif b["type"] == "ranges":
                mult = calc_best_range_mult(b["ranges"], result)
                if mult > 0:
                    win_amount = int(b["bet_total"] * mult)
            
            # Event ×2 + boost
            if win_amount > 0:
                win_amount = int(win_amount * get_event_mult() * get_user_mult(b["user_id"]))
                # Лимит стола
                win_amount = cap_win(win_amount)
                
                set_balance(b["user_id"], win_amount)
                pay_ref_commission(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], win_amount, f"{result} {color_emoji}")
                update_daily_quest(b["user_id"], "daily_win_1", 1)
                
                if is_unlimited(b["user_id"]):
                    winners.append(f"🏆 @{b['username']} — ♾️")
                else:
                    winners.append(f"🏆 @{b['username']} — <b>+{fmt_num(win_amount)}</b>")
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], 0, f"{result} {color_emoji}")
                losers.append(f"😢 @{b['username']}")
        
        # Красивый результат
        result_txt = (
            f"🎡 <b>РУЛЕТКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎯 Выпало: <b>{color_emoji} {result}</b>\n\n"
            f"━━━━━━━━━━━━━━\n\n"
        )
        
        if winners:
            result_txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n"
            result_txt += "\n".join(winners) + "\n\n"
        
        if losers:
            result_txt += "💔 <b>Проиграли:</b>\n"
            result_txt += "\n".join(losers) + "\n\n"
        
        # Джекпот при Зеро
        if result == 0:
            jackpot = get_jackpot()
            green_bettors = [b for b in bets if b["type"] == "green"]
            if green_bettors and jackpot > 0:
                share = jackpot // len(green_bettors)
                for b in green_bettors:
                    set_balance(b["user_id"], share)
                result_txt += (
                    f"━━━━━━━━━━━━━━\n\n"
                    f"💎 <b>ДЖЕКПОТ СОРВАН!</b>\n"
                    f"💰 {fmt_num(jackpot)} разделены\n"
                )
                reset_jackpot()
        
        # Комиссия в джекпот
        commission = int(total_bank * 0.01)
        if commission > 0:
            add_to_jackpot(commission)
        
        result_txt += f"\n━━━━━━━━━━━━━━\n💰 Банк: <b>{bank_line}</b>"
        
        del active_bets[chat_id]
        
        try:
            await msg.edit_text(result_txt, parse_mode="HTML")
        except Exception:
            await message.reply(result_txt, parse_mode="HTML")
        return
    
    # ═══════════════ СЛОТЫ ═══════════════
    
    if len(parts) == 2 and parts[0] in ["спин", "spin"]:
        if is_game_disabled("slots") and user_id != ADMIN_ID:
            await send_temp(chat_id,
                "⚠️ <b>ИГРА ВЫКЛЮЧЕНА</b>\n\n"
                "🎰 Слоты в разработке.\n"
                "🙏 Приносим извинения!",
                parse_mode="HTML"
            )
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        ok, err = check_bet_limit("slots", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        
        set_balance(user_id, -bet)
        
        # Анимация — стоп по одному
        msg = await message.reply(
            f"🎰 <b>СЛОТЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎲 Крутим...\n\n"
            f"┃ ❓ ┃ ❓ ┃ ❓ ┃",
            parse_mode="HTML"
        )
        
        r1 = random.choice(SLOT_SYMBOLS)
        r2 = random.choice(SLOT_SYMBOLS)
        r3 = random.choice(SLOT_SYMBOLS)
        
        # Крутим первый
        for _ in range(3):
            a = random.choice(SLOT_SYMBOLS)
            await asyncio.sleep(0.15)
            try:
                await msg.edit_text(
                    f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n\n"
                    f"🎲 Крутим...\n\n"
                    f"┃ {a} ┃ ❓ ┃ ❓ ┃",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        await asyncio.sleep(0.3)
        try:
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n\n"
                f"🎲 Крутим...\n\n"
                f"┃ {r1} ┃ ❓ ┃ ❓ ┃",
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        # Крутим второй
        for _ in range(3):
            b = random.choice(SLOT_SYMBOLS)
            await asyncio.sleep(0.15)
            try:
                await msg.edit_text(
                    f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n\n"
                    f"🎲 Крутим...\n\n"
                    f"┃ {r1} ┃ {b} ┃ ❓ ┃",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        await asyncio.sleep(0.3)
        try:
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n\n"
                f"🎲 Крутим...\n\n"
                f"┃ {r1} ┃ {r2} ┃ ❓ ┃",
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        # Крутим третий
        for _ in range(3):
            cc = random.choice(SLOT_SYMBOLS)
            await asyncio.sleep(0.15)
            try:
                await msg.edit_text(
                    f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n\n"
                    f"🎲 Крутим...\n\n"
                    f"┃ {r1} ┃ {r2} ┃ {cc} ┃",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        await asyncio.sleep(0.4)
        
        # Определяем выигрыш
        win = False
        mult = 0
        combo_text = ""
        
        if r1 == r2 == r3:
            win = True
            mult = SLOT_PAYOUTS.get(r1, 9)
            combo_text = f"🎉 <b>ТРИ В РЯД!</b>"
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True
            mult = SLOT_TWO_MATCH
            combo_text = f"✨ <b>ДВА СОВПАДЕНИЯ!</b>"
        
        add_xp(user_id, 1)
        update_daily_quest(user_id, "daily_bets_5", 1)
        
        if win:
            wa = cap_win(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "слоты", bet, wa, f"{r1}{r2}{r3}")
            update_daily_quest(user_id, "daily_win_1", 1)
            
            result_txt = (
                f"🎰 <b>СЛОТЫ</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n"
                f"{combo_text}\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Выигрыш: <b>+{fmt_num(wa)}</b> (×{mult})\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            
            result_txt = (
                f"🎰 <b>СЛОТЫ</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n"
                f"😢 Не повезло...\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💸 Потеряно: <b>-{fmt_num(bet)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>"
            )
        
        try:
            await msg.edit_text(result_txt, parse_mode="HTML")
        except Exception:
            await message.reply(result_txt, parse_mode="HTML")
        return
    
    # ═══════════════ МОНЕТКА ═══════════════
    
    if len(parts) == 2 and parts[0] in ["орёл", "орел", "решка"]:
        if is_game_disabled("coin") and user_id != ADMIN_ID:
            await send_temp(chat_id, "⚠️ Монетка выключена", parse_mode="HTML")
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        ok, err = check_bet_limit("coin", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        
        set_balance(user_id, -bet)
        
        msg = await message.reply(
            f"🪙 <b>МОНЕТКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎲 Бросаем...\n\n"
            f"🦅",
            parse_mode="HTML"
        )
        
        for i, frame in enumerate(ANIM_COIN):
            await asyncio.sleep(ANIM_COIN_DELAYS[i] if i < len(ANIM_COIN_DELAYS) else 0.3)
            try:
                await msg.edit_text(
                    f"🪙 <b>МОНЕТКА</b>\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"🎲 Бросаем...\n\n"
                    f"{frame}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        choice = "heads" if parts[0] in ["орёл", "орел"] else "tails"
        result = random.choice(["heads", "tails"])
        result_emoji = "🦅" if result == "heads" else "👑"
        choice_str = "🦅 Орёл" if choice == "heads" else "👑 Решка"
        
        add_xp(user_id, 1)
        update_daily_quest(user_id, "daily_bets_5", 1)
        
        if result == choice:
            wa = cap_win(int(bet * COIN_PAYOUT * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, result_emoji)
            update_daily_quest(user_id, "daily_win_1", 1)
            
            result_txt = (
                f"🪙 <b>МОНЕТКА</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"🎯 Выпало: <b>{result_emoji}</b>\n"
                f"📌 Твой выбор: <b>{choice_str}</b>\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"🎉 <b>ПОБЕДА!</b>\n"
                f"💰 +<b>{fmt_num(wa)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, result_emoji)
            
            result_txt = (
                f"🪙 <b>МОНЕТКА</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"🎯 Выпало: <b>{result_emoji}</b>\n"
                f"📌 Твой выбор: <b>{choice_str}</b>\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"😢 <b>Проигрыш</b>\n"
                f"💸 -<b>{fmt_num(bet)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>"
            )
        
        try:
            await msg.edit_text(result_txt, parse_mode="HTML")
        except Exception:
            await message.reply(result_txt, parse_mode="HTML")
        return
    
    # ═══════════════ БЛЭКДЖЕК ═══════════════
    
    if len(parts) == 2 and parts[0] in ["бж", "блэкджек"]:
        if is_game_disabled("bj") and user_id != ADMIN_ID:
            await send_temp(chat_id, "⚠️ БЖ выключен", parse_mode="HTML")
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        ok, err = check_bet_limit("bj", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        
        set_balance(user_id, -bet)
        
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        
        bj_games[user_id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}
        p_score = hand_score(player)
        
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Ты:</b> {fmt_hand(player)} = <b>{p_score}</b>\n"
            f"🤖 <b>Дилер:</b> {fmt_hand(dealer, hide_second=True)}\n\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n\n"
            f"👇 Что делаешь?",
            parse_mode="HTML",
            reply_markup=bj_kb()
        )
        return
    
    # ═══════════════ МИНЫ ═══════════════
    
    if len(parts) == 2 and parts[0] in ["мины", "мина", "mines"]:
        if is_game_disabled("mines") and user_id != ADMIN_ID:
            await send_temp(chat_id, "⚠️ Мины выключены", parse_mode="HTML")
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        ok, err = check_bet_limit("mines", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        
        await message.reply(
            f"💣 <b>МИНЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n\n"
            f"👇 Выбери уровень:",
            parse_mode="HTML",
            reply_markup=mines_level_kb(bet)
        )
        return
    
    # ═══════════════ ДУЭЛЬ ═══════════════
    
    if len(parts) >= 3 and parts[0] == "дуэль":
        if is_game_disabled("duel") and user_id != ADMIN_ID:
            await send_temp(chat_id, "⚠️ Дуэль выключена", parse_mode="HTML")
            return
        
        try:
            bet = int(parts[1])
        except Exception:
            return
        
        if bet < 10:
            await message.reply("❌ Мин. 10")
            return
        
        ok, err = check_bet_limit("duel", bet)
        if not ok:
            await send_temp(chat_id, err, parse_mode="HTML")
            return
        
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!")
            return
        
        target_username = parts[2][1:] if parts[2].startswith('@') else None
        if not target_username:
            await message.reply("❌ <code>дуэль 1000 @user</code>", parse_mode="HTML")
            return
        
        opponent_id = get_user_id_by_username(target_username)
        if not opponent_id:
            await message.reply(f"❌ @{target_username} не найден")
            return
        
        if opponent_id == user_id:
            await message.reply("❌ Себя нельзя")
            return
        
        if chat_id in duel_games:
            await message.reply("❌ Уже есть дуэль")
            return
        
        duel_games[chat_id] = {
            "challenger_id": user_id, "challenger_name": username, "challenger_bet": bet,
            "opponent_id": opponent_id, "opponent_name": target_username, "opponent_bet": bet,
            "active": False
        }
        
        await message.reply(
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>@{username}</b>\n"
            f"     ⚔️\n"
            f"👤 <b>@{target_username}</b>\n\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b> Tokens\n\n"
            f"@{target_username}, напиши <code>принять</code>!",
            parse_mode="HTML"
        )
        return
    
    if text == "принять":
        if chat_id not in duel_games or duel_games[chat_id].get("active"):
            return
        
        duel = duel_games[chat_id]
        if duel["opponent_id"] != user_id:
            return
        
        cb = get_balance(duel["challenger_id"])
        ob = get_balance(duel["opponent_id"])
        
        if cb < duel["challenger_bet"] and not is_unlimited(duel["challenger_id"]):
            await message.reply(f"❌ У {duel['challenger_name']} мало")
            del duel_games[chat_id]
            return
        
        if ob < duel["opponent_bet"] and not is_unlimited(duel["opponent_id"]):
            await message.reply("❌ У тебя мало")
            return
        
        set_balance(duel["challenger_id"], -duel["challenger_bet"])
        set_balance(duel["opponent_id"], -duel["opponent_bet"])
        duel["active"] = True
        total_bank = clamp(duel["challenger_bet"] + duel["opponent_bet"])
        
        msg = await message.reply(
            f"⚔️ <b>ДУЭЛЬ!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Банк: <b>{fmt_num(total_bank)}</b>",
            parse_mode="HTML"
        )
        
        for i, frame in enumerate(ANIM_DUEL):
            await asyncio.sleep(ANIM_DUEL_DELAYS[i] if i < len(ANIM_DUEL_DELAYS) else 0.3)
            try:
                await msg.edit_text(
                    f"⚔️ <b>ДУЭЛЬ</b>\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"{frame}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        winner_color = random.choice(["red", "blue"])
        if winner_color == "red":
            wid = duel["challenger_id"]
            wn = duel["challenger_name"]
            ln = duel["opponent_name"]
            ce = "🔴"
        else:
            wid = duel["opponent_id"]
            wn = duel["opponent_name"]
            ln = duel["challenger_name"]
            ce = "🔵"
        
        total_bank = cap_win(int(total_bank * get_user_mult(wid)))
        nb = set_balance(wid, total_bank)
        pay_ref_commission(wid, total_bank)
        add_xp(duel["challenger_id"], 3)
        add_xp(duel["opponent_id"], 3)
        log_game(wid, wn, "дуэль", total_bank // 2, total_bank, f"vs {ln}")
        update_daily_quest(wid, "daily_win_1", 1)
        
        try:
            await msg.edit_text(
                f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"{ce} <b>ПОБЕДИТЕЛЬ</b>\n\n"
                f"🏆 <b>@{wn}</b>\n"
                f"💰 +<b>{fmt_num(total_bank)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"😢 @{ln} проиграл",
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        del duel_games[chat_id]
        return
    
    if text == "отмена" and chat_id in duel_games and not duel_games[chat_id].get("active"):
        duel = duel_games[chat_id]
        if user_id in [duel["challenger_id"], duel["opponent_id"]]:
            del duel_games[chat_id]
            await send_temp(chat_id, "❌ Дуэль отменена", parse_mode="HTML")
        return
        # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 10/15 — ГЛАВНЫЙ CALLBACK-ХЕНДЛЕР
# ═══════════════════════════════════════════════════════════════

@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)

    
    # ⚠️ ДОБАВЬ: обёртка для alert
    original_answer = call.answer
    async def _safe_answer(text=None, **kwargs):
        if text and kwargs.get('show_alert'):
            text = clean_alert(text)
        return await original_answer(text, **kwargs)
    call.answer = _safe_answer
    
    # ... остальной код
    
    if call.message and call.message.chat and call.message.chat.id < 0:
        track_group_member(call.message.chat.id, user_id, username)
    
    if is_banned(user_id):
        await call.answer("🚫 ВЫ ЗАБЛОКИРОВАНЫ", show_alert=True)
        return
    
    if maintenance_on and user_id != ADMIN_ID:
        await call.answer("🛠️ Тех.работы. Попробуй позже!", show_alert=True)
        return
    
    # ═══════════════ ЗАЩИТА КНОПОК ═══════════════
    # Кнопки с префиксами, где важен user_id:
    PROTECTED_PREFIXES = ["bet_", "group_bet_", "mines_", "bj_", "setbet_"]
    for prefix in PROTECTED_PREFIXES:
        if data.startswith(prefix):
            # Формат: prefix_USERID_... — проверяем
            # Но у нас сейчас нет user_id в callback. Поэтому защита ниже.
            pass
    
    # ═══════════════ ЯЗЫК ═══════════════
    
    if data == "menu_lang":
        await safe_edit(call, "🌐 <b>Выбор языка</b>\n\n👇 Выбери язык:", reply_markup=lang_kb())
        await call.answer()
        return
    
    if data.startswith("set_lang_"):
        lang = data.replace("set_lang_", "")
        if lang in ("ru", "en"):
            set_lang(user_id, lang)
            flag = "🇷🇺" if lang == "ru" else "🇬🇧"
            await call.answer(f"{flag} Язык изменён!", show_alert=True)
            await safe_edit(call, f"{flag} <b>Язык: {lang.upper()}</b>\n\n✅ Сохранено", reply_markup=back_to_main_kb())
        return
    
    # ═══════════════ ГЛАВНОЕ МЕНЮ ═══════════════
    
    if data == "menu_main":
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        xp = get_xp(user_id)
        level = xp // 100
        rank = get_rank_name(level)
        
        vip_tier = get_vip_tier(user_id)
        vip_line = ""
        if vip_tier > 0:
            info = get_vip_tier_info(vip_tier)
            if info:
                vip_line = f"{info['icon']} VIP {info['id']} — {info['name']}\n"
        
        boost = get_active_boost(user_id)
        if boost:
            until = boost[1]
            if until.tzinfo is None:
                until = until.replace(tzinfo=TZ_MINSK)
            mins_left = max(int((until - datetime.now(TZ_MINSK)).total_seconds() // 60), 0)
            boost_line = f"⚡ ×{boost[0]} • {mins_left} мин"
        else:
            boost_line = "❌ нет"
        
        if is_unlimited(user_id):
            total_line = "♾️"
        else:
            total_line = f"<b>{fmt_num(clamp(balance + bank))}</b> Tokens"
        
        txt = (
            f"🎰 <b>Tokens</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>{username}</b>\n"
            f"🎖 {rank}\n"
            f"{vip_line}\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n"
            f"📊 Всего: {total_line}\n\n"
            f"⚡ Буст: {boost_line}\n\n"
            f"👇 Выбирай:"
        )
        await safe_edit(call, txt, reply_markup=main_menu_inline_kb())
        await call.answer()
        return
    
    # ═══════════════ ИГРЫ ═══════════════
    
    if data == "menu_games":
        await safe_edit(call, "🎮 <b>ИГРЫ</b>\n\nВыбери игру:", reply_markup=games_kb())
        await call.answer()
        return
    
    if data == "info_roulette":
        await safe_edit(call,
            "🎡 <b>РУЛЕТКА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🔴 <b>Красное</b> ×1.95\n"
            "⚫ <b>Чёрное</b> ×1.95\n"
            "🟢 <b>Зеро</b> ×35\n\n"
            "🎯 <b>Диапазоны:</b>\n"
            "• 1-18 / 19-36 — ×1.95\n"
            "• Дюжина (12) — ×2.9\n"
            "• Линия (6) — ×5.8\n"
            "• Угол (4) — ×8.7\n"
            "• Стрит (3) — ×11.7\n"
            "• Сплит (2) — ×17.5\n"
            "• 1 число — ×35\n\n"
            "💡 <b>Команды:</b>\n"
            "<code>к 1000</code> — красное\n"
            "<code>ч 1000</code> — чёрное\n"
            "<code>з 1000</code> — зеро\n"
            "<code>1000 1-8 11-18</code> — мульти\n"
            "<code>го</code> — запуск",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    if data == "info_slots":
        await safe_edit(call,
            "🎰 <b>СЛОТЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🍒 ×9 | 🍋 ×13.5 | 🍊 ×18\n"
            "🍇 ×22.5 | 💎 ×45 | 7️⃣ ×90\n\n"
            "2 совпадения — ×1.8\n\n"
            "💡 Команда: <code>спин 1000</code>",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    if data == "info_coin":
        await safe_edit(call,
            "🪙 <b>МОНЕТКА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🦅 Орёл ×1.95\n"
            "👑 Решка ×1.95\n\n"
            "💡 Команды:\n"
            "<code>орёл 1000</code>\n"
            "<code>решка 1000</code>",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    if data == "info_bj":
        await safe_edit(call,
            "🃏 <b>БЛЭКДЖЕК</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Цель: набрать 21 или меньше,\n"
            "но больше дилера.\n\n"
            "💡 Команда: <code>бж 1000</code>",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    if data == "info_mines":
        await safe_edit(call,
            "💣 <b>МИНЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🟢 Лёгкий — 3 мины\n"
            "🟡 Средний — 5 мин\n"
            "🔴 Хардкор — 10 мин\n\n"
            "💡 Команда: <code>мины 1000</code>",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    if data == "info_duel":
        await safe_edit(call,
            "⚔️ <b>ДУЭЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Вызови другого игрока на дуэль.\n"
            "Победитель забирает весь банк.\n\n"
            "💡 Команда:\n"
            "<code>дуэль 1000 @user</code>\n"
            "Затем: <code>принять</code>",
            reply_markup=back_to_games_kb()
        )
        await call.answer()
        return
    
    # ═══════════════ ПРОФИЛЬ ═══════════════
    
    if data == "menu_profile":
        await safe_edit(call, profile_text(user_id, username), reply_markup=profile_kb())
        await call.answer()
        return
    
    if data == "menu_stats":
        await safe_edit(call, stats_text(user_id, username), reply_markup=back_to_main_kb())
        await call.answer()
        return
    
    if data == "menu_history":
        await safe_edit(call, history_text(user_id, username), reply_markup=history_kb())
        await call.answer()
        return
    
    if data.startswith("hist_"):
        game_map = {
            "hist_roulette": "рулетка", "hist_slots": "слоты",
            "hist_mines": "мины", "hist_bj": "блэкджек",
            "hist_coin": "монетка", "hist_duel": "дуэль",
            "hist_all": None,
        }
        game = game_map.get(data)
        await safe_edit(call, history_text(user_id, username, game), reply_markup=history_kb())
        await call.answer()
        return
    
    if data == "menu_birthday":
        birthday_input_state[user_id] = True
        await safe_edit(call,
            "🎂 <b>ДАТА РОЖДЕНИЯ</b>\n\n"
            "Отправь дату в формате <code>ДД.ММ</code>\n"
            "Пример: <code>15.06</code>\n\n"
            "🎁 В день рождения — бонус!\n\n"
            "❌ Отмена: /profile"
        )
        await call.answer()
        return
    
    # ═══════════════ БАЛАНС ═══════════════
    
    if data == "menu_balance":
        bank = get_bank(user_id)
        if is_unlimited(user_id):
            await call.answer(f"♾️ БЕЗЛИМИТ\n🏦 {fmt_num(bank)}", show_alert=True)
        else:
            balance = get_balance(user_id)
            await call.answer(f"💎 {fmt_num(balance)}\n🏦 {fmt_num(bank)}", show_alert=True)
        return
    
    # ═══════════════ ТОП ═══════════════
    
    if data == "menu_top":
        await safe_edit(call, top_text("balance"), reply_markup=top_kb())
        await call.answer()
        return
    
    if data.startswith("top_"):
        mode = data.replace("top_", "")
        await safe_edit(call, top_text(mode), reply_markup=top_kb())
        await call.answer()
        return
    
    # ═══════════════ БАНК ═══════════════
    
    if data == "menu_bank":
        await safe_edit(call, bank_text(user_id, username), reply_markup=bank_kb())
        await call.answer()
        return
    
    if data == "bank_deposit":
        balance = get_balance(user_id)
        bank_input_state[user_id] = {"mode": "deposit"}
        await safe_edit(call,
            f"🏦 <b>ПОЛОЖИТЬ В БАНК</b>\n\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b>\n\n"
            f"Введи сумму:",
            reply_markup=bank_cancel_kb()
        )
        await call.answer()
        return
    
    if data == "bank_withdraw":
        bank = get_bank(user_id)
        bank_input_state[user_id] = {"mode": "withdraw"}
        await safe_edit(call,
            f"🏦 <b>СНЯТЬ ИЗ БАНКА</b>\n\n"
            f"🏦 В банке: <b>{fmt_num(bank)}</b>\n\n"
            f"Введи сумму:",
            reply_markup=bank_cancel_kb()
        )
        await call.answer()
        return
    
    # ═══════════════ КРЕДИТЫ ═══════════════
    
    if data == "menu_credits":
        info = get_credit_amount_info(user_id)
        status = info.get("status", "available")
        await safe_edit(call, credits_text(user_id), reply_markup=credits_kb(status))
        await call.answer()
        return
    
    if data == "credit_take":
        info = get_credit_amount_info(user_id)
        if info.get("status") != "available":
            await call.answer(info.get("reason", "Недоступно"), show_alert=True)
            return
        
        await safe_edit(call,
            f"💳 <b>ВЫБОР СУММЫ КРЕДИТА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Мин: <b>{fmt_num(CREDIT_MIN)}</b>\n"
            f"💰 Макс: <b>{fmt_num(CREDIT_MAX)}</b>\n"
            f"⏱ Срок: <b>{CREDIT_DAYS} дня</b>\n"
            f"📈 Процент: <b>0%</b>\n\n"
            f"👇 Выбери сумму:",
            reply_markup=credits_amounts_kb()
        )
        await call.answer()
        return
    
    if data.startswith("credit_amount_"):
        amount_str = data.replace("credit_amount_", "")
        
        if amount_str == "custom":
            credit_input_state[user_id] = {"mode": "custom_amount"}
            await safe_edit(call,
                f"✏️ <b>СВОЯ СУММА</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"Введи сумму от <b>{fmt_num(CREDIT_MIN)}</b>\n"
                f"до <b>{fmt_num(CREDIT_MAX)}</b>:\n\n"
                f"❌ Отмена: /credits"
            )
            await call.answer()
            return
        
        try:
            amount = int(amount_str)
        except Exception:
            await call.answer("❌ Ошибка", show_alert=True)
            return
        
        # Подтверждение
        await safe_edit(call,
            f"⚠️ <b>ПОДТВЕРЖДЕНИЕ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Сумма: <b>{fmt_num(amount)}</b> Tokens\n"
            f"⏱ Вернуть: <b>{CREDIT_DAYS} дня</b>\n"
            f"📈 Процент: <b>0%</b>\n\n"
            f"❗ Если не вернёшь вовремя —\n"
            f"аккаунт будет <b>заблокирован</b>\n\n"
            f"Согласен?",
            reply_markup=credit_confirm_kb(amount)
        )
        await call.answer()
        return
    
    if data.startswith("credit_confirm_"):
        try:
            amount = int(data.replace("credit_confirm_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        ok, msg, due_at = issue_credit(user_id, amount)
        if not ok:
            await call.answer(msg, show_alert=True)
            return
        
        await safe_edit(call,
            f"✅ <b>КРЕДИТ ВЫДАН!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Сумма: <b>{fmt_num(amount)}</b> Tokens\n"
            f"📈 Процент: <b>0%</b>\n"
            f"⏱ Вернуть до: <b>{due_at.strftime('%d.%m %H:%M')}</b>\n\n"
            f"💎 Новый баланс: <b>{fmt_num(get_balance(user_id))}</b>",
            reply_markup=back_to_main_kb()
        )
        await call.answer("✅ Кредит выдан!", show_alert=True)
        return
    
    if data == "credit_return":
        active = get_active_credit(user_id)
        if not active:
            await call.answer("❌ Нет активного кредита", show_alert=True)
            return
        
        _, amount, _, due_at, _ = active
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=TZ_MINSK)
        
        await safe_edit(call,
            f"⚠️ <b>ВОЗВРАТ КРЕДИТА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Сумма долга: <b>{fmt_num(amount)}</b> Tokens\n"
            f"⏱ Срок: <b>{due_at.strftime('%d.%m %H:%M')}</b>\n\n"
            f"Вернуть кредит?",
            reply_markup=credit_return_confirm_kb()
        )
        await call.answer()
        return
    
    if data == "credit_return_confirm":
        ok, msg = return_credit(user_id)
        if ok:
            await safe_edit(call, f"✅ <b>{msg}</b>", reply_markup=back_to_main_kb())
            await call.answer("✅ Возвращено!", show_alert=True)
        else:
            await call.answer("❌ " + msg[:190], show_alert=True)
        return
    
    if data == "credit_history":
        await safe_edit(call, credit_history_text(user_id), reply_markup=back_to_main_kb())
        await call.answer()
        return
    
    # ═══════════════ МАГАЗИН ═══════════════
    
    if data == "menu_shop":
        await safe_edit(call, shop_text(), reply_markup=shop_categories_kb())
        await call.answer()
        return
    
    if data.startswith("shop_cat_"):
        category = data.replace("shop_cat_", "")
        await safe_edit(call, shop_category_text(category), reply_markup=shop_items_kb(category))
        await call.answer()
        return
    
    # Покупка Tokens-пака
    if data.startswith("shop_tokens_"):
        pack_id = data.replace("shop_tokens_", "")
        pack = get_tokens_pack_by_id(pack_id)
        if not pack:
            await call.answer("❌ Не найден", show_alert=True)
            return
        
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"💰 {fmt_num(pack['amount'])} Tokens",
                description=f"Покупка {fmt_num(pack['amount'])} Tokens",
                payload=f"tokens_{pack_id}",
                currency="XTR",
                prices=[LabeledPrice(label=f"{fmt_num(pack['amount'])} Tokens", amount=pack["stars"])],
            )
        except Exception as e:
            logger.error(f"[shop tokens invoice] {e}")
        return
    
    # Покупка кейса (inline)
    if data.startswith("shop_case_"):
        case_id = data.replace("shop_case_", "")
        case = get_case_by_id(case_id)
        if not case:
            await call.answer("❌ Кейс не найден", show_alert=True)
            return
        
        await safe_edit(call, case_text(case_id), reply_markup=case_buy_kb(case_id, case["stars"]))
        await call.answer()
        return
    
    if data.startswith("case_buy_"):
        parts = data.split("_")
        if len(parts) < 4:
            await call.answer("❌", show_alert=True)
            return
        case_id = parts[2]
        try:
            stars = int(parts[3])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        case = get_case_by_id(case_id)
        if not case or case["stars"] != stars:
            await call.answer("❌ Кейс изменился", show_alert=True)
            return
        
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"Кейс «{case['name']}»",
                description=case.get("desc", "Кейс с наградами"),
                payload=f"case_{case_id}",
                currency="XTR",
                prices=[LabeledPrice(label=case["name"], amount=stars)],
            )
        except Exception as e:
            logger.error(f"[case invoice] {e}")
        return
    
    # Покупка предмета магазина
    if data.startswith("shop_item_"):
        item_id = data.replace("shop_item_", "")
        it = get_shop_item_by_id(item_id)
        if not it:
            await call.answer("❌ Товар не найден", show_alert=True)
            return
        await safe_edit(call, shop_item_text(item_id), reply_markup=shop_item_kb(item_id))
        await call.answer()
        return
    
    if data.startswith("shop_buy_stars_"):
        item_id = data.replace("shop_buy_stars_", "")
        it = get_shop_item_by_id(item_id)
        if not it or not it.get("stars"):
            await call.answer("❌", show_alert=True)
            return
        
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=it["name"],
                description=it.get("desc", ""),
                payload=f"shop_stars_{item_id}",
                currency="XTR",
                prices=[LabeledPrice(label=it["name"], amount=it["stars"])],
            )
        except Exception as e:
            logger.error(f"[shop stars invoice] {e}")
        return
    
    if data.startswith("shop_buy_tokens_"):
        item_id = data.replace("shop_buy_tokens_", "")
        it = get_shop_item_by_id(item_id)
        if not it or not it.get("tokens"):
            await call.answer("❌", show_alert=True)
            return
        
        price = it["tokens"]
        balance = get_balance(user_id)
        if balance < price and not is_unlimited(user_id):
            await call.answer(f"❌ Нужно {fmt_num(price)} Tokens", show_alert=True)
            return
        
        set_balance(user_id, -price)
        reward_text = grant_shop_item(user_id, it)
        nb = get_balance(user_id)
        
        await call.answer("✅ Куплено!", show_alert=True)
        await safe_edit(call,
            f"✅ <b>КУПЛЕНО!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎁 {reward_text}\n\n"
            f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
            f"📦 Предмет в инвентаре!",
            reply_markup=back_to_main_kb()
        )
        
        price_str = f"{fmt_num(price)} Tokens"
        log_purchase(user_id, username, "tokens", it["name"], price_str, "Бот")
        try:
            asyncio.create_task(notify_admin_purchase(user_id, username, "tokens", it["name"], price_str, "Бот"))
        except Exception:
            pass
        return
    
    # VIP покупка
    if data.startswith("vip_buy_"):
        parts = data.split("_")
        if len(parts) < 4:
            await call.answer("❌", show_alert=True)
            return
        try:
            tid = int(parts[2])
            stars = int(parts[3])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        info = get_vip_tier_info(tid)
        if not info or info["stars"] != stars:
            await call.answer("❌ VIP изменился", show_alert=True)
            return
        
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"{info['icon']} VIP {tid} — {info['name']}",
                description=f"Кэшбэк {info['cashback']}%, бонус +{fmt_num(info['bonus'])} Tokens",
                payload=f"vip_{tid}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label=f"VIP {tid} — {info['name']}", amount=stars)],
            )
        except Exception as e:
            logger.error(f"[vip invoice] {e}")
        return
    
    # XP покупка
    if data.startswith("xp_buy_"):
        parts = data.split("_")
        if len(parts) < 5:
            await call.answer("❌", show_alert=True)
            return
        try:
            pack_id = parts[2]
            xp_amount = int(parts[3])
            stars = int(parts[4])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"⭐ Буст XP +{xp_amount}",
                description=f"Мгновенно +{xp_amount} XP",
                payload=f"xp_{pack_id}_{xp_amount}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label=f"+{xp_amount} XP", amount=stars)],
            )
        except Exception as e:
            logger.error(f"[xp invoice] {e}")
        return
    
    # ═══════════════ ЗАДАНИЯ ═══════════════
    
    if data == "menu_quests":
        await safe_edit(call, quests_text(user_id), reply_markup=daily_quests_kb(user_id))
        await call.answer()
        return
    
    if data == "menu_level_rewards":
        await safe_edit(call, level_rewards_text(), reply_markup=level_rewards_kb())
        await call.answer()
        return
    
    if data.startswith("daily_quest_claim_"):
        qkey = data.replace("daily_quest_claim_", "")
        reward = claim_daily_quest(user_id, qkey)
        if reward:
            new_balance = get_balance(user_id)
            await call.answer(f"✅ +{fmt_num(reward)} Tokens", show_alert=True)
            await safe_edit(call,
                f"🎯 <b>ЗАДАНИЕ ВЫПОЛНЕНО!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Награда: <b>+{fmt_num(reward)}</b> Tokens\n"
                f"💎 Баланс: <b>{fmt_num(new_balance)}</b>",
                reply_markup=daily_quests_kb(user_id)
            )
        else:
            await call.answer("❌ Уже получено", show_alert=True)
        return
    
    if data == "quest_noop":
        await call.answer()
        return
    
    # ═══════════════ ТУРНИР ═══════════════
    
    if data == "menu_tournament":
        await safe_edit(call, tournament_text(), reply_markup=back_to_main_kb())
        await call.answer()
        return
    
    # ═══════════════ РЕФКА ═══════════════
    
    if data == "menu_ref":
        await safe_edit(call, ref_text(user_id, username), reply_markup=ref_kb())
        await call.answer()
        return
    
    if data == "ref_list":
        await safe_edit(call, ref_list_text(user_id), reply_markup=ref_kb())
        await call.answer()
        return
    
    if data == "ref_top":
        await safe_edit(call, ref_top_text(), reply_markup=ref_kb())
        await call.answer()
        return
    
    # ═══════════════ РЫНОК ═══════════════
    
    if data == "menu_market":
        await safe_edit(call, market_text(), reply_markup=market_main_kb())
        await call.answer()
        return
    
    if data == "market_browse":
        lots = get_market_lots()
        if not lots:
            await safe_edit(call,
                "🏪 <b>РЫНОК</b>\n\n😢 Пока пусто...\n\nБудь первым!",
                reply_markup=market_main_kb()
            )
        else:
            await safe_edit(call, market_lots_text(0), reply_markup=market_lots_kb(lots, 0))
        await call.answer()
        return
    
    if data.startswith("market_page_"):
        try:
            page = int(data.replace("market_page_", ""))
        except Exception:
            page = 0
        lots = get_market_lots()
        await safe_edit(call, market_lots_text(page), reply_markup=market_lots_kb(lots, page))
        await call.answer()
        return
    
    if data.startswith("market_buy_"):
        try:
            idx = int(data.replace("market_buy_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        lots = get_market_lots()
        lot_price = lots[idx]["price"] if 0 <= idx < len(lots) else 0
        lot_type = lots[idx].get("type", "?") if 0 <= idx < len(lots) else "?"
        
        ok, msg = buy_market_lot(user_id, idx)
        if ok:
            await call.answer("✅ Куплено!", show_alert=True)
            await safe_edit(call,
                f"✅ <b>ПОКУПКА УСПЕШНА</b>\n\n{msg}",
                reply_markup=market_main_kb()
            )
            price_str = f"{fmt_num(lot_price)} Tokens"
            log_purchase(user_id, username, "market", f"Лот: {lot_type}", price_str, "Бот")
        else:
            await call.answer(msg[:190], show_alert=True)
        return
    
    if data == "market_sell":
        inv = get_inventory(user_id)
        if not inv:
            await call.answer("🎒 У тебя пусто!", show_alert=True)
            return
        await safe_edit(call, "💰 <b>ВЫСТАВИТЬ НА РЫНОК</b>\n\nВыбери предмет:", reply_markup=market_sell_kb(user_id))
        await call.answer()
        return
    
    if data.startswith("market_sellitem_"):
        inv_id = data.replace("market_sellitem_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌ Не найдено", show_alert=True)
            return
        edit_shop_state[user_id] = {"mode": "sell_price", "inv_id": inv_id}
        await safe_edit(call,
            f"💰 <b>ЦЕНА ЛОТА</b>\n\n"
            f"📦 Предмет: <b>{item.get('type')}</b>\n\n"
            f"Введи цену в Tokens (мин. 10 000):\n\n"
            f"❌ Отмена: /market"
        )
        await call.answer()
        return
    
    if data == "market_mylots":
        lots = get_market_lots()
        my_lots = [l for l in lots if l["seller_id"] == user_id]
        if not my_lots:
            await call.answer("📦 У тебя нет лотов", show_alert=True)
            return
        
        rows = []
        for i, lot in enumerate(my_lots):
            rows.append([InlineKeyboardButton(
                text=f"❌ Снять лот {i+1}",
                callback_data=f"market_remove_{lot['id']}"
            )])
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
        await safe_edit(call, market_mylots_text(user_id), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("market_remove_"):
        lot_id = data.replace("market_remove_", "")
        lots = get_market_lots()
        removed = None
        new_lots = []
        for l in lots:
            if l["id"] == lot_id and l["seller_id"] == user_id:
                removed = l
            else:
                new_lots.append(l)
        if removed:
            save_market_lots(new_lots)
            item = dict(removed["payload"])
            item["type"] = removed["type"]
            add_to_inventory(user_id, item)
            await call.answer("✅ Лот снят", show_alert=True)
        else:
            await call.answer("❌ Не найден", show_alert=True)
        return
    
    if data == "market_noop":
        await call.answer()
        return
    
    # ═══════════════ ИНВЕНТАРЬ ═══════════════
    
    if data == "menu_inventory":
        await safe_edit(call, inventory_text(user_id), reply_markup=inventory_main_kb())
        await call.answer()
        return
    
    if data in ("inv_titles", "inv_boosts", "inv_vip", "inv_all"):
        filter_map = {"inv_titles": "title", "inv_boosts": "boost", "inv_vip": "vip", "inv_all": None}
        ft = filter_map[data]
        await safe_edit(call, inventory_text(user_id, ft), reply_markup=inventory_list_kb(user_id, ft))
        await call.answer()
        return
    
    if data.startswith("inv_view_"):
        inv_id = data.replace("inv_view_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌ Предмет не найден", show_alert=True)
            return
        await safe_edit(call, inventory_item_text(inv_id, user_id), reply_markup=inventory_item_kb(inv_id))
        await call.answer()
        return
    
    if data.startswith("inv_use_"):
        inv_id = data.replace("inv_use_", "")
        ok, msg = use_inventory_item(user_id, inv_id)
        if ok:
            await call.answer("✅ Активировано!", show_alert=True)
            await safe_edit(call, f"✅ <b>АКТИВИРОВАНО!</b>\n\n{msg}", reply_markup=back_to_main_kb())
        else:
            await call.answer(msg[:190], show_alert=True)
        return
    
    if data.startswith("inv_sell_"):
        inv_id = data.replace("inv_sell_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌", show_alert=True)
            return
        edit_shop_state[user_id] = {"mode": "sell_price", "inv_id": inv_id}
        await safe_edit(call,
            f"💰 <b>ЦЕНА ЛОТА</b>\n\n"
            f"Введи цену (мин. 10 000):\n\n"
            f"❌ Отмена: /inventory"
        )
        await call.answer()
        return
    
    # ═══════════════ ИГРЫ: CALLBACK ═══════════════
    
    if data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        balance = get_balance(user_id)
        bet = balance if val == "max" else int(val)
        # Ограничиваем лимитом рулетки
        bet = min(bet, GAME_BET_LIMITS["roulette"])
        await call.message.edit_reply_markup(reply_markup=roulette_bet_kb(bet))
        await call.answer(f"💎 {fmt_num(bet)}")
        return
    
    if data.startswith("mines_start_"):
        parts = data.split("_")
        level = parts[2]
        bet = int(parts[3])
        
        if level not in MINES_LEVELS:
            await call.answer("❌", show_alert=True)
            return
        
        ok, err = check_bet_limit("mines", bet)
        if not ok:
            await call.answer("❌ Лимит ставки", show_alert=True)
            return
        
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await call.answer("❌ Недостаточно!", show_alert=True)
            return
        
        set_balance(user_id, -bet)
        positions = list(range(25))
        random.shuffle(positions)
        mines_positions = set(positions[:MINES_LEVELS[level]["mines"]])
        
        mines_games[user_id] = {
            "bet": bet, "level": level,
            "mines_positions": mines_positions,
            "opened": set(), "mult": 1.0,
        }
        add_xp(user_id, 2)
        update_daily_quest(user_id, "daily_bets_5", 1)
        
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[level]['name']}</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
            f"💎 Множитель: <b>×1.00</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[level]['mines']}</b>\n\n"
            f"👇 Открывай клетки:",
            parse_mode="HTML",
            reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💣 Началось!")
        return
    
    if data.startswith("mines_open_"):
        if user_id not in mines_games:
            await call.answer("❌", show_alert=True)
            return
        idx = int(data.replace("mines_open_", ""))
        game = mines_games[user_id]
        
        if idx in game["opened"]:
            await call.answer("❌ Уже открыто", show_alert=True)
            return
        
        if idx in game["mines_positions"]:
            # БУМ
            game["opened"].add(idx)
            log_game(user_id, username, "мины", game["bet"], 0, f"{game['level']} бум")
            
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET win_streak = 0 WHERE user_id = %s", (user_id,))
            conn.commit()
            c.close()
            release_conn(conn)
            
            await call.message.edit_text(
                f"💥 <b>БУМ! МИНА!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"😢 Ты попал на мину\n"
                f"💸 Потеряно: <b>{fmt_num(game['bet'])}</b>",
                parse_mode="HTML",
                reply_markup=back_to_main_kb()
            )
            del mines_games[user_id]
            await call.answer("💥")
            return
        
        game["opened"].add(idx)
        game["mult"] = calc_mines_mult(25, MINES_LEVELS[game["level"]]["mines"], len(game["opened"]))
        safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]
        
        if len(game["opened"]) == safe_total:
            wa = cap_win(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
            set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} all")
            update_daily_quest(user_id, "daily_win_1", 1)
            
            await call.message.edit_text(
                f"🏆 <b>ПОЛЕ ОЧИЩЕНО!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Выигрыш: <b>+{fmt_num(wa)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(get_balance(user_id))}</b>",
                parse_mode="HTML",
                reply_markup=back_to_main_kb()
            )
            del mines_games[user_id]
            await call.answer("🎉")
            return
        
        cashout = cap_win(int(game["bet"] * game["mult"]))
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[game['level']]['name']}</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Ставка: <b>{fmt_num(game['bet'])}</b>\n"
            f"💎 Множитель: <b>×{game['mult']:.2f}</b>\n"
            f"🎁 Забрать: <b>{fmt_num(cashout)}</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[game['level']]['mines']}</b>",
            parse_mode="HTML",
            reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💎")
        return
    
    if data == "mines_cashout":
        if user_id not in mines_games:
            await call.answer("❌", show_alert=True)
            return
        game = mines_games[user_id]
        if not game["opened"]:
            await call.answer("❌ Открой 1 клетку", show_alert=True)
            return
        
        wa = cap_win(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, wa)
        pay_ref_commission(user_id, wa)
        log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} x{game['mult']}")
        update_daily_quest(user_id, "daily_win_1", 1)
        
        await call.message.edit_text(
            f"💰 <b>ЗАБРАЛ!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Открыто клеток: <b>{len(game['opened'])}</b>\n"
            f"💎 Множитель: <b>×{game['mult']:.2f}</b>\n"
            f"🎁 Выигрыш: <b>+{fmt_num(wa)}</b>\n"
            f"💎 Баланс: <b>{fmt_num(get_balance(user_id))}</b>",
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )
        del mines_games[user_id]
        await call.answer("💰")
        return
    
    if data == "mines_cancel":
        if user_id in mines_games:
            game = mines_games[user_id]
            if not game["opened"]:
                set_balance(user_id, game["bet"])
                del mines_games[user_id]
                await call.message.edit_text("❌ Отменено", reply_markup=back_to_main_kb())
                await call.answer("Возвращено")
                return
        await call.answer("❌")
        return
    
    if data == "mines_noop":
        await call.answer()
        return
    
    # ═══════════════ БЖ ═══════════════
    
    if data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌", show_alert=True)
            return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n"
                f"🤖 {fmt_hand(game['dealer'])}\n\n"
                f"💥 <b>ПЕРЕБОР!</b>\n"
                f"💸 -{fmt_num(game['bet'])}\n"
                f"💎 {fmt_num(nb)}",
                parse_mode="HTML",
                reply_markup=back_to_main_kb()
            )
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score}")
            del bj_games[user_id]
        else:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n"
                f"🤖 {fmt_hand(game['dealer'], hide_second=True)}\n\n"
                f"🎯 Ещё?",
                parse_mode="HTML",
                reply_markup=bj_kb()
            )
        await call.answer()
        return
    
    if data == "bj_stand":
        if user_id not in bj_games:
            await call.answer("❌", show_alert=True)
            return
        game = bj_games[user_id]
        while hand_score(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        
        p_score = hand_score(game["player"])
        d_score = hand_score(game["dealer"])
        add_xp(user_id, 2)
        update_daily_quest(user_id, "daily_bets_5", 1)
        
        if d_score > 21 or p_score > d_score:
            wa = cap_win(int(game["bet"] * 2 * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            res = f"🎉 <b>ПОБЕДА!</b>\n💰 +{fmt_num(wa - game['bet'])}"
            log_game(user_id, username, "блэкджек", game["bet"], wa, f"{p_score} vs {d_score}")
            update_daily_quest(user_id, "daily_win_1", 1)
        elif p_score == d_score:
            set_balance(user_id, game["bet"])
            nb = get_balance(user_id)
            res = "🤝 <b>Ничья</b>"
            log_game(user_id, username, "блэкджек", game["bet"], game["bet"], f"{p_score}")
        else:
            nb = get_balance(user_id)
            res = f"😢 <b>Проигрыш</b>\n💸 -{fmt_num(game['bet'])}"
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} vs {d_score}")
        
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n"
            f"🤖 {fmt_hand(game['dealer'])} = <b>{d_score}</b>\n\n"
            f"{res}\n\n"
            f"💎 {fmt_num(nb)}",
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )
        del bj_games[user_id]
        await call.answer()
        return
    
    # ═══════════════ КЕЙС: РЕЗУЛЬТАТ ═══════════════
    
    if data.startswith("case_use_"):
        inv_id = data.replace("case_use_", "")
        if not inv_id or inv_id == "None":
            await call.answer("❌", show_alert=True)
            return
        ok, msg = use_inventory_item(user_id, inv_id)
        if ok:
            await call.answer("✅ Активировано!", show_alert=True)
            await safe_edit(call, f"✅ <b>АКТИВИРОВАНО!</b>\n\n{msg}", reply_markup=back_to_main_kb())
        else:
            await call.answer(msg[:190], show_alert=True)
        return
    
    if data == "case_keep":
        await call.answer("📦 В инвентаре", show_alert=True)
        return
    
    # ═══════════════ АДМИН ═══════════════
    
    if data.startswith("admin_") or data.startswith("rates_"):
        await handle_admin_callback(call)
        return
    
    # ═══════════════ РЕДАКТОРЫ ═══════════════
    
    if data.startswith("editshop_") or data.startswith("editcases_") or data.startswith("edittokens_") or data.startswith("editvip_") or data.startswith("editxp_") or data.startswith("editquest_") or data.startswith("editlevel_"):
        await handle_editor_callback(call)
        return
    
    # Если ничего не совпало
    await call.answer()


# ═══════════════════════════════════════════════════════════════
# SAFE_EDIT — безопасное редактирование сообщения
# ═══════════════════════════════════════════════════════════════

async def safe_edit(call: CallbackQuery, text: str, reply_markup=None):
    """Редактирует сообщение. Если не получилось — НЕ отправляет новое."""
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        err = str(e).lower()
        # Игнорируем "message is not modified" — ничего не делаем
        if "message is not modified" in err:
            return
        # Игнорируем "message can't be edited" — ничего не делаем
        if "message can't be edited" in err:
            return
        # Остальные ошибки — логируем, НЕ отправляем новое
        logger.error(f"[safe_edit] {e}")
    except Exception as e:
        logger.error(f"[safe_edit] {e}")

# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ИГР
# ═══════════════════════════════════════════════════════════════

def hand_score(cards: list) -> int:
    score = 0
    aces = 0
    for c in cards:
        val = c[:-1]
        if val == 'A':
            score += 11
            aces += 1
        elif val in ['K', 'Q', 'J', '10']:
            score += 10
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score


def create_deck() -> list:
    suits = ['♠', '♥', '♦', '♣']
    values = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = [v + s for s in suits for v in values]
    random.shuffle(deck)
    return deck


def fmt_hand(cards: list, hide_second: bool = False) -> str:
    if hide_second and len(cards) >= 2:
        return f"{cards[0]} 🂠"
    return " ".join(cards)


def parse_multi_bet(text: str) -> tuple:
    """Парсит мульти-ставку: '1000 1-8 11-18'."""
    parts = text.split()
    if len(parts) < 2:
        return None, []
    try:
        bet = int(parts[0]) if parts[0].isdigit() else 0
    except ValueError:
        return None, []
    if bet == 0:
        return None, []
    
    ranges = []
    for part in parts[1:]:
        try:
            if '-' in part:
                a, z = map(int, part.split('-'))
                if 0 <= a <= z <= 36:
                    ranges.append((a, z))
            else:
                n = int(part)
                if 0 <= n <= 36:
                    ranges.append((n, n))
        except ValueError:
            continue
    return bet, ranges


# ═══════════════════════════════════════════════════════════════
# ADMIN CALLBACK (заглушка — будет в Части 11)
# ═══════════════════════════════════════════════════════════════

async def handle_admin_callback(call: CallbackQuery):
    """Обработка админ-callback. Реализация — в Части 11."""
    data = call.data
    if data == "confirm_reset_all":
        await call.answer("⏳ Обработка...", show_alert=False)
    elif data == "cancel_reset":
        await safe_edit(call, "❌ Отменено")
        await call.answer()
    else:
        await call.answer()


# ═══════════════════════════════════════════════════════════════
# EDITOR CALLBACK (заглушка — будет в Части 11)
# ═══════════════════════════════════════════════════════════════

async def handle_editor_callback(call: CallbackQuery):
    """Обработка callback редакторов. Реализация — в Части 11."""
    await call.answer()


# ═══════════════════════════════════════════════════════════════
# УВЕДОМЛЕНИЕ АДМИНУ О ПОКУПКЕ
# ═══════════════════════════════════════════════════════════════

async def notify_admin_purchase(user_id: int, username: str, purchase_type: str,
                                 item_name: str, price: str, source: str, extra: str = ""):
    """Отправляет карточку покупки админу."""
    try:
        should_notify = False
        if purchase_type in ("stars", "case", "jackpot"):
            should_notify = True
        elif purchase_type == "tokens":
            try:
                if int(str(price).split()[0].replace(" ", "")) > 1_000_000:
                    should_notify = True
            except Exception:
                pass
        
        if not should_notify:
            return
        
        time_str = datetime.now(TZ_MINSK).strftime("%d.%m.%Y %H:%M")
        text = (
            f"📋 <b>ПОКУПКА!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 Игрок: @{username or f'id{user_id}'}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💎 Товар: <b>{item_name}</b>\n"
            f"⭐ Сумма: <b>{price}</b>\n"
            f"📍 Источник: {source}\n"
            f"🕐 Время: {time_str}"
        )
        if extra:
            text += f"\n📝 {extra}"
        
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[notify_admin_purchase] {e}")
        # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 11/15 — АДМИН-CALLBACK И РЕДАКТОРЫ
# ═══════════════════════════════════════════════════════════════

async def handle_admin_callback(call: CallbackQuery):
    """Обработка всех админ-callback."""
    data = call.data
    user_id = call.from_user.id

    
    # ⚠️ ДОБАВЬ: обёртка для alert
    original_answer = call.answer
    async def _safe_answer(text=None, **kwargs):
        if text and kwargs.get('show_alert'):
            text = clean_alert(text)
        return await original_answer(text, **kwargs)
    call.answer = _safe_answer
    
    # ... остальной код
    
    if user_id != ADMIN_ID:
        await call.answer("❌ Только для админа", show_alert=True)
        return
    
    # ═══════════════ НАВИГАЦИЯ ═══════════════
    
    if data == "admin_back":
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        txt = (
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b>\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b>\n\n"
            f"👇 Выбери раздел:"
        )
        await safe_edit(call, txt, reply_markup=admin_panel_inline_kb())
        await call.answer()
        return
    
    # ═══════════════ КАТЕГОРИИ ═══════════════
    
    if data == "admin_cat_players":
        await safe_edit(call, "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n👇 Выбери действие:", reply_markup=admin_players_kb())
        await call.answer()
        return
    
    if data == "admin_cat_games":
        await safe_edit(call, "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай:", reply_markup=admin_games_kb())
        await call.answer()
        return
    
    if data == "admin_cat_content":
        await safe_edit(call, "🛒 <b>УПРАВЛЕНИЕ КОНТЕНТОМ</b>\n\n👇 Выбери:", reply_markup=admin_content_kb())
        await call.answer()
        return
    
    if data == "admin_cat_economy":
        await safe_edit(call, "💰 <b>ЭКОНОМИКА</b>\n\n👇 Выбери:", reply_markup=admin_economy_kb())
        await call.answer()
        return
    
    if data == "admin_cat_comm":
        await safe_edit(call, "📢 <b>СВЯЗЬ</b>\n\n👇 Выбери:", reply_markup=admin_comm_kb())
        await call.answer()
        return
    
    if data == "admin_cat_monitor":
        await safe_edit(call, "📊 <b>МОНИТОРИНГ</b>\n\n👇 Выбери:", reply_markup=admin_monitor_kb())
        await call.answer()
        return
    
    if data == "admin_cat_credits":
        stats = get_all_credits_stats()
        txt = (
            f"💳 <b>КРЕДИТЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Активных: <b>{stats['active_count']}</b> ({fmt_num(stats['active_sum'])})\n"
            f"🚫 Просрочено: <b>{stats['overdue_count']}</b> ({fmt_num(stats['overdue_sum'])})\n"
            f"📊 Всего выдано: <b>{stats['total_count']}</b> ({fmt_num(stats['total_sum'])})\n\n"
            f"👇 Управление:"
        )
        await safe_edit(call, txt, reply_markup=admin_credits_kb())
        await call.answer()
        return
    
    # ═══════════════ ВСЕ КОМАНДЫ ═══════════════
    
    if data == "admin_all_commands":
        await safe_edit(call, all_commands_text(), reply_markup=all_commands_kb())
        await call.answer()
        return
    
    if data == "admin_copy_commands":
        txt = "📋 <b>КОМАНДЫ</b>\n\n"
        for cat, cmds in ALL_BOT_COMMANDS.items():
            txt += f"<b>{cat}</b>\n"
            for cmd, desc in cmds:
                txt += f"{cmd} — {desc}\n"
            txt += "\n"
        await safe_edit(call, txt, reply_markup=all_commands_kb())
        await call.answer("📋 Скопировано!")
        return
    
    # ═══════════════ ИГРЫ: ТОГГЛЫ ═══════════════
    
    if data.startswith("admin_toggle_"):
        game = data.replace("admin_toggle_", "")
        if game not in GAME_NAMES:
            await call.answer("❌", show_alert=True)
            return
        
        if game in disabled_games:
            disabled_games.discard(game)
            save_disabled_games()
            await call.answer(f"✅ {GAME_NAMES[game]} включена")
        else:
            disabled_games.add(game)
            save_disabled_games()
            await call.answer(f"❌ {GAME_NAMES[game]} выключена")
        
        await safe_edit(call, "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай:", reply_markup=admin_games_kb())
        return
    
    if data == "admin_event":
        status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
        await safe_edit(call,
            f"🎰 <b>EVENT ×2</b>\n\n"
            f"Статус: <b>{status}</b>\n\n"
            f"<code>/event on</code> — включить\n"
            f"<code>/event off</code> — выключить",
            reply_markup=admin_back_kb()
        )
        await call.answer()
        return
    
    if data == "admin_maintenance":
        status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
        await safe_edit(call,
            f"🛠️ <b>ТЕХ.РАБОТЫ</b>\n\n"
            f"Статус: <b>{status}</b>\n\n"
            f"<code>/maintenance on</code>\n"
            f"<code>/maintenance off</code>",
            reply_markup=admin_back_kb()
        )
        await call.answer()
        return
    
    # ═══════════════ ОБНУЛЕНИЕ ═══════════════
    
    if data == "admin_reset_all_start":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ДА, ОБНУЛИТЬ ВСЕХ", callback_data="confirm_reset_all")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")],
        ])
        await safe_edit(call,
            "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
            "Это обнулит ВСЕХ игроков:\n"
            "• Балансы → 1000\n"
            "• Банк → 0\n"
            "• XP → 0\n"
            "• Рефералы → 0\n\n"
            "Это действие НЕОБРАТИМО. Продолжить?",
            reply_markup=kb
        )
        await call.answer()
        return
    
    if data == "confirm_reset_all":
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("""UPDATE users SET balance = 1000, bank = 0, xp = 0,
                         total_lost = 0, total_won = 0, ref_count = 0,
                         ref_earnings = 0, referrer_id = NULL, inventory = '[]'::jsonb""")
            c.execute("DELETE FROM credits")
            conn.commit()
            c.close()
            release_conn(conn)
            cache_invalidate()
            await safe_edit(call, "✅ <b>ВСЕ ИГРОКИ ОБНУЛЕНЫ!</b>", reply_markup=admin_back_kb())
            await call.answer("✅ Готово!")
        except Exception as e:
            await call.answer(f"❌ {e}", show_alert=True)
        return
    
    if data == "cancel_reset":
        await safe_edit(call, "❌ Отменено.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    # ═══════════════ УПРАВЛЕНИЕ ИГРОКОМ ═══════════════
    
    if data.startswith("adm_add_"):
        uid = int(data.replace("adm_add_", ""))
        set_balance(uid, 1000)
        await call.answer("✅ +1000", show_alert=True)
        return
    
    if data.startswith("adm_sub_"):
        uid = int(data.replace("adm_sub_", ""))
        set_balance(uid, -1000)
        await call.answer("✅ -1000", show_alert=True)
        return
    
    if data.startswith("adm_zero_"):
        uid = int(data.replace("adm_zero_", ""))
        set_balance_exact(uid, 0)
        await call.answer("✅ Баланс обнулён", show_alert=True)
        return
    
    if data.startswith("adm_stats_"):
        uid = int(data.replace("adm_stats_", ""))
        conn = get_conn()
        c = conn.cursor()
        c.execute("""UPDATE users SET total_lost = 0, total_won = 0, xp = 0 WHERE user_id = %s""", (uid,))
        c.execute("DELETE FROM game_log WHERE user_id = %s", (uid,))
        conn.commit()
        c.close()
        release_conn(conn)
        cache_invalidate(f"xp_{uid}")
        await call.answer("✅ Статистика обнулена", show_alert=True)
        return
    
    if data.startswith("adm_refs_"):
        uid = int(data.replace("adm_refs_", ""))
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET ref_count = 0, ref_earnings = 0 WHERE user_id = %s", (uid,))
        conn.commit()
        c.close()
        release_conn(conn)
        await call.answer("✅ Рефералы обнулены", show_alert=True)
        return
    
    if data.startswith("adm_del_"):
        uid = int(data.replace("adm_del_", ""))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ДА, УДАЛИТЬ", callback_data=f"adm_delok_{uid}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
        ])
        await safe_edit(call,
            f"⚠️ Удалить игрока <code>{uid}</code>?\n\nЭто необратимо!",
            reply_markup=kb
        )
        await call.answer()
        return
    
    if data.startswith("adm_delok_"):
        uid = int(data.replace("adm_delok_", ""))
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM game_log WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM titles WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM boosts WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM credits WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM active_vip WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM daily_quests WHERE user_id = %s", (uid,))
        c.execute("DELETE FROM level_rewards_claimed WHERE user_id = %s", (uid,))
        conn.commit()
        c.close()
        release_conn(conn)
        cache_invalidate()
        await safe_edit(call, f"🗑 Игрок <code>{uid}</code> удалён.", reply_markup=admin_back_kb())
        await call.answer("✅ Удалено")
        return
    
    # ═══════════════ КРЕДИТЫ ═══════════════
    
    if data == "admin_credits_stats":
        stats = get_all_credits_stats()
        txt = (
            f"💳 <b>СТАТИСТИКА КРЕДИТОВ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Активных: <b>{stats['active_count']}</b>\n"
            f"💰 Сумма: <b>{fmt_num(stats['active_sum'])}</b>\n\n"
            f"🚫 Просрочено: <b>{stats['overdue_count']}</b>\n"
            f"💰 Сумма: <b>{fmt_num(stats['overdue_sum'])}</b>\n\n"
            f"📊 Всего выдано: <b>{stats['total_count']}</b>\n"
            f"💰 Сумма: <b>{fmt_num(stats['total_sum'])}</b>"
        )
        await safe_edit(call, txt, reply_markup=admin_credits_kb())
        await call.answer()
        return
    
    if data == "admin_credits_overdue":
        users = get_overdue_users(30)
        if not users:
            await call.answer("✅ Нет должников", show_alert=True)
            return
        txt = "🚫 <b>ДОЛЖНИКИ</b>\n━━━━━━━━━━━━━━\n\n"
        for uid, uname, amount, days in users:
            txt += f"• @{uname or uid} — <b>{fmt_num(amount)}</b> ({days} дн.)\n"
        await safe_edit(call, txt, reply_markup=admin_credits_kb())
        await call.answer()
        return
    
    if data == "admin_credits_unlock":
        admin_action_state[user_id] = {"mode": "credit_unlock"}
        await safe_edit(call,
            "🔓 <b>РАЗБЛОКИРОВАТЬ ПО КРЕДИТУ</b>\n\n"
            "Введи @username или ID:\n\n"
            "❌ Отмена: /admin"
        )
        await call.answer()
        return
    
    # ═══════════════ ДЖЕКПОТ ═══════════════
    
    if data == "admin_jackpot":
        jp = get_jackpot()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сбросить", callback_data="admin_jackpot_reset")],
            [InlineKeyboardButton(text="💰 Установить", callback_data="admin_jackpot_set")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        await safe_edit(call,
            f"💎 <b>ДЖЕКПОТ</b>\n\nТекущий: <b>{fmt_num(jp)}</b>",
            reply_markup=kb
        )
        await call.answer()
        return
    
    if data == "admin_jackpot_reset":
        reset_jackpot()
        await call.answer("✅ Сброшен до 10 000", show_alert=True)
        return
    
    if data == "admin_jackpot_set":
        admin_action_state[user_id] = {"mode": "jackpot_set"}
        await safe_edit(call, "💰 Введи сумму джекпота:\n\n❌ /admin")
        await call.answer()
        return
    
    # ═══════════════ ТУРНИРЫ ═══════════════
    
    if data == "admin_tournament":
        t = get_active_tournament()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="admin_tournament_start")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="admin_tournament_finish")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        if t:
            txt = f"🏆 Активный: <b>{t[1]}</b>\n⏱ До: <b>{t[3].strftime('%d.%m %H:%M')}</b>"
        else:
            txt = "🏆 <b>ТУРНИРЫ</b>\n\n😴 Нет активного турнира"
        await safe_edit(call, txt, reply_markup=kb)
        await call.answer()
        return
    
    if data == "admin_tournament_start":
        tid, ends_at = start_tournament("🏆 Турнир недели", 168)
        await call.answer(f"✅ Турнир до {ends_at.strftime('%d.%m %H:%M')}", show_alert=True)
        try:
            await bot.send_message(
                TOURNAMENT_CHANNEL,
                f"🏆 <b>НОВЫЙ ТУРНИР!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"🥇 1 место — <b>10 000</b>\n"
                f"🥈 2 место — <b>5 000</b>\n"
                f"🥉 3 место — <b>2 000</b>\n\n"
                f"⏱ До: <b>{ends_at.strftime('%d.%m %H:%M')}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return
    
    if data == "admin_tournament_finish":
        t = get_active_tournament()
        if not t:
            await call.answer("❌ Нет активного турнира", show_alert=True)
            return
        winners = finish_tournament(t[0])
        if winners:
            txt = "🏆 <b>ТУРНИР ЗАВЕРШЁН!</b>\n\n"
            medals = ["🥇", "🥈", "🥉"]
            for i, (uid, uname, prize) in enumerate(winners):
                txt += f"{medals[i]} {uname} — {fmt_num(prize)}\n"
            await call.answer("✅ Готово", show_alert=True)
            await safe_edit(call, txt, reply_markup=admin_back_kb())
            try:
                await bot.send_message(TOURNAMENT_CHANNEL, txt, parse_mode="HTML")
            except Exception:
                pass
        else:
            await call.answer("❌ Ошибка", show_alert=True)
        return
    
    # ═══════════════ РОЗЫГРЫШ ═══════════════
    
    if data == "admin_giveaway_start":
        admin_action_state[user_id] = {"mode": "giveaway"}
        await safe_edit(call,
            "🎁 <b>РОЗЫГРЫШ</b>\n\n"
            "Формат: <code>сумма время</code>\n"
            "Пример: <code>10000 1h</code>\n\n"
            "❌ /admin"
        )
        await call.answer()
        return
    
    # ═══════════════ КУРСЫ ═══════════════
    
    if data == "admin_set_rates":
        auto_status = get_setting("auto_rates", "on")
        status_str = "✅ ВКЛ" if auto_status == "on" else "❌ ВЫКЛ"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ввести курсы сейчас", callback_data="rates_input_start")],
            [InlineKeyboardButton(
                text="🔕 Отключить авторассылку" if auto_status == "on" else "🔔 Включить авторассылку",
                callback_data="rates_toggle_auto"
            )],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        
        await safe_edit(call,
            f"💱 <b>КУРСЫ ОБМЕНА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"Авторассылка: <b>{status_str}</b>\n"
            f"🕐 Время: <b>каждый день в 10:00 МСК</b>\n\n"
            f"👇 Что делаем?",
            reply_markup=kb
        )
        await call.answer()
        return
    
    if data == "rates_input_start":
        rates_input_state[user_id] = {"step": "gram"}
        await safe_edit(call,
            "💱 <b>ОБНОВЛЕНИЕ КУРСОВ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "💰 Сколько <b>Gram</b> за 10 000 Tokens?\n"
            "Пример: <code>1000</code>\n\n"
            "❌ Отмена: /admin"
        )
        await call.answer()
        return
    
    if data == "rates_skip_today":
        await safe_edit(call,
            "⏭ <b>Пропущено на сегодня</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Следующая рассылка — завтра в 10:00 МСК.\n\n"
            "💡 Ручной запуск: <code>/set_rates</code>"
        )
        await call.answer("⏭ Пропущено")
        return
    
    if data == "rates_disable_auto":
        set_setting("auto_rates", "off")
        await safe_edit(call,
            "🔕 <b>АВТОРАССЫЛКА ОТКЛЮЧЕНА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Бот больше НЕ будет напоминать о курсах.\n\n"
            "💡 Ручной запуск: <code>/set_rates</code>\n"
            "💡 Включить обратно: <code>/set_rates on</code>"
        )
        await call.answer("🔕 Отключено")
        return
    
    if data == "rates_toggle_auto":
        current = get_setting("auto_rates", "on")
        new_val = "off" if current == "on" else "on"
        set_setting("auto_rates", new_val)
        
        if new_val == "on":
            await call.answer("🔔 Авторассылка включена", show_alert=True)
        else:
            await call.answer("🔕 Авторассылка отключена", show_alert=True)
        
        auto_status = new_val
        status_str = "✅ ВКЛ" if auto_status == "on" else "❌ ВЫКЛ"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ввести курсы сейчас", callback_data="rates_input_start")],
            [InlineKeyboardButton(
                text="🔕 Отключить авторассылку" if auto_status == "on" else "🔔 Включить авторассылку",
                callback_data="rates_toggle_auto"
            )],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        await safe_edit(call,
            f"💱 <b>КУРСЫ ОБМЕНА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"Авторассылка: <b>{status_str}</b>\n"
            f"🕐 Время: <b>каждый день в 10:00 МСК</b>\n\n"
            f"👇 Что делаем?",
            reply_markup=kb
        )
        return
    if data == "rates_input_start":
        rates_input_state[user_id] = {"step": "gram"}
        await safe_edit(call,
            "💱 <b>ОБНОВЛЕНИЕ КУРСОВ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "💰 Сколько <b>Gram</b> за 10 000 Tokens?\n"
            "Пример: <code>1000</code>\n\n"
            "❌ Отмена: /admin"
        )
        await call.answer()
        return
    
    if data == "rates_skip_today":
        await safe_edit(call,
            "⏭ <b>Пропущено на сегодня</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Следующая рассылка — завтра в 10:00 МСК.\n\n"
            "💡 Ручной запуск: <code>/set_rates</code>"
        )
        await call.answer("⏭ Пропущено")
        return
    
    if data == "rates_disable_auto":
        set_setting("auto_rates", "off")
        await safe_edit(call,
            "🔕 <b>АВТОРАССЫЛКА ОТКЛЮЧЕНА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Бот больше НЕ будет напоминать о курсах.\n\n"
            "💡 Ручной запуск: <code>/set_rates</code>\n"
            "💡 Включить обратно: <code>/set_rates on</code>"
        )
        await call.answer("🔕 Отключено")
        return
    
    # ═══════════════ МОНИТОРИНГ ═══════════════
    
    if data == "admin_active_show":
        users = get_recent_users(minutes=5, limit=20)
        if not users:
            txt = "📊 За последние 5 минут никто не играл"
        else:
            txt = "📊 <b>АКТИВНЫЕ (5 мин)</b>\n━━━━━━━━━━━━━━\n\n"
            for i, (uid, uname, bal) in enumerate(users, 1):
                txt += f"{i}. <b>{uname}</b> — 💎 {fmt_num(bal)}\n"
        await safe_edit(call, txt, reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "admin_all_players":
        conn = get_conn()
        c = conn.cursor()
        c.execute("""SELECT user_id, username, balance, banned
                     FROM users ORDER BY balance DESC LIMIT 30""")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0]
        c.close()
        release_conn(conn)
        
        medals = ["🥇", "🥈", "🥉"]
        txt = f"👥 <b>ВСЕ ИГРОКИ ({total})</b>\n━━━━━━━━━━━━━━\n\n"
        for i, (uid, uname, bal, is_b) in enumerate(rows):
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            ban = " 🚫" if is_b else ""
            txt += f"{medal} {uname or f'user_{uid}'} — <b>{fmt_num(bal)}</b>{ban}\n"
        if total > 30:
            txt += f"\n<i>...и ещё {total - 30}</i>"
        await safe_edit(call, txt, reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "admin_stats_show":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
        total_balance = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM game_log")
        total_games = c.fetchone()[0]
        c.close()
        release_conn(conn)
        
        txt = (
            f"📊 <b>СТАТИСТИКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👥 Игроков: <b>{total_users}</b>\n"
            f"💎 Общий баланс: <b>{fmt_num(total_balance)}</b>\n"
            f"🎮 Игр: <b>{total_games}</b>"
        )
        await safe_edit(call, txt, reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "admin_bigwins_show":
        wins = get_big_wins(limit=10, min_win=1_000_000)
        if not wins:
            txt = "📊 Крупных выигрышей нет"
        else:
            txt = "🏆 <b>BIG WINS</b>\n━━━━━━━━━━━━━━\n\n"
            for i, (uname, game, win, time_str) in enumerate(wins, 1):
                txt += f"{i}. <b>{uname}</b> — {game} +{fmt_num(win)} ({time_str})\n"
        await safe_edit(call, txt, reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "admin_purchases":
        await safe_edit(call, purchases_text(20), reply_markup=admin_back_kb())
        await call.answer()
        return
    
    # ═══════════════ ДЕЙСТВИЯ С ИГРОКАМИ ═══════════════
    
    if data == "admin_ban_start":
        admin_action_state[user_id] = {"mode": "ban"}
        await safe_edit(call, "🚫 <b>BAN</b>\n\nВведи @username:\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_vip_start":
        admin_action_state[user_id] = {"mode": "vip"}
        await safe_edit(call, "👑 <b>VIP</b>\n\nФормат: <code>@username уровень</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_title_start":
        admin_action_state[user_id] = {"mode": "title"}
        await safe_edit(call, "🏷 <b>ТИТУЛ</b>\n\nФормат: <code>@username Титул</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_bal_start":
        admin_action_state[user_id] = {"mode": "balance"}
        await safe_edit(call, "💰 <b>БАЛАНС</b>\n\nФормат: <code>@username сумма</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_xp_start":
        admin_action_state[user_id] = {"mode": "xp"}
        await safe_edit(call, "📊 <b>XP</b>\n\nФормат: <code>@username XP</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_reset_start":
        admin_action_state[user_id] = {"mode": "reset"}
        await safe_edit(call, "🔄 <b>RESET</b>\n\nФормат: <code>@username</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_bonus_start":
        admin_action_state[user_id] = {"mode": "bonus"}
        await safe_edit(call, "🎁 <b>БОНУС</b>\n\n<code>@username сумма</code>\nили <code>all сумма</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_logs_start":
        admin_action_state[user_id] = {"mode": "logs"}
        await safe_edit(call, "📜 <b>ЛОГИ</b>\n\nФормат: <code>@username</code>\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_broadcast_start":
        admin_action_state[user_id] = {"mode": "broadcast"}
        await safe_edit(call, "📢 <b>РАССЫЛКА</b>\n\nОтправь текст:\n\n❌ /admin")
        await call.answer()
        return
    
    if data == "admin_pi_info":
        await safe_edit(call, "👤 <code>/edit_user @user</code>\n\n❌ /admin")
        await call.answer()
        return
    
    await call.answer()


# ═══════════════════════════════════════════════════════════════
# РЕДАКТОРЫ CALLBACK
# ═══════════════════════════════════════════════════════════════

async def handle_editor_callback(call: CallbackQuery):
    """Обработка callback редакторов."""
    data = call.data
    user_id = call.from_user.id
    original_answer = call.answer
async def _safe_answer(text=None, **kwargs):
        if text and kwargs.get('show_alert'):
            text = clean_alert(text)
        return await original_answer(text, **kwargs)
        call.answer = _safe_answer
    
    if user_id != ADMIN_ID:
        await call.answer("❌ Только для админа", show_alert=True)
        return
    
    # ═══════════════ РЕДАКТОР МАГАЗИНА ═══════════════
    
    if data == "editshop_start":
        items = get_shop_items()
        txt = "🛒 <b>РЕДАКТОР МАГАЗИНА</b>\n━━━━━━━━━━━━━━\n\n"
        if not items:
            txt += "Пусто."
        else:
            for i, it in enumerate(items, 1):
                txt += f"{i}. {it['name']}\n"
        
        rows = []
        for i, it in enumerate(items):
            rows.append([InlineKeyboardButton(
                text=f"{i+1}. {it['name'][:30]}",
                callback_data=f"editshop_item_{i}"
            )])
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
        
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("editshop_item_"):
        idx = int(data.replace("editshop_item_", ""))
        items = get_shop_items()
        if idx < 0 or idx >= len(items):
            await call.answer("❌", show_alert=True)
            return
        it = items[idx]
        txt = (
            f"🛒 <b>{it['name']}</b>\n\n"
            f"📝 {it.get('desc', '—')}\n"
            f"⭐ Stars: {it.get('stars', '—')}\n"
            f"💎 Tokens: {it.get('tokens', '—')}\n"
            f"🎯 Тип: {it.get('type', '—')}\n"
            f"📂 Категория: {it.get('category', '—')}"
        )
        rows = [
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editshop_del_{idx}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="editshop_start")],
        ]
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("editshop_del_"):
        idx = int(data.replace("editshop_del_", ""))
        items = get_shop_items()
        if 0 <= idx < len(items):
            items.pop(idx)
            save_shop_items(items)
        await safe_edit(call, "✅ Удалено.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    # ═══════════════ РЕДАКТОР КЕЙСОВ ═══════════════
    
    if data == "editcases_start":
        cases = get_cases()
        txt = "🎰 <b>РЕДАКТОР КЕЙСОВ</b>\n━━━━━━━━━━━━━━\n\n"
        for i, c in enumerate(cases, 1):
            txt += f"{i}. {c['name']} — {c['stars']} ⭐ | 🎁 {len(c.get('rewards', []))}\n"
        
        rows = []
        for i, c in enumerate(cases):
            rows.append([InlineKeyboardButton(
                text=f"{i+1}. {c['name']}",
                callback_data=f"editcases_item_{i}"
            )])
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
        
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("editcases_item_"):
        idx = int(data.replace("editcases_item_", ""))
        cases = get_cases()
        if idx < 0 or idx >= len(cases):
            await call.answer("❌", show_alert=True)
            return
        c = cases[idx]
        
        txt = (
            f"🎰 <b>{c['name']}</b>\n\n"
            f"📝 {c.get('desc', '—')}\n"
            f"⭐ Цена: {c['stars']}\n\n"
            f"🎁 <b>Призы:</b>\n"
        )
        for i, r in enumerate(c.get("rewards", []), 1):
            t = r.get("type")
            if t == "tokens":
                txt += f"{i}. 💰 {fmt_num(r['amount'])} — {r['chance']}%\n"
            elif t == "boost":
                txt += f"{i}. ⚡ ×{r['mult']}/{r['minutes']}м — {r['chance']}%\n"
            elif t == "title":
                txt += f"{i}. 🏷 {r['title']} — {r['chance']}%\n"
            elif t == "vip":
                txt += f"{i}. 👑 VIP {r['vip_level']} — {r['chance']}%\n"
        
        rows = [
            [InlineKeyboardButton(text="➕ Награда", callback_data=f"editcases_add_{idx}")],
            [InlineKeyboardButton(text="🗑 Удалить кейс", callback_data=f"editcases_del_{idx}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="editcases_start")],
        ]
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("editcases_del_"):
        idx = int(data.replace("editcases_del_", ""))
        cases = get_cases()
        if 0 <= idx < len(cases):
            cases.pop(idx)
            save_cases(cases)
        await safe_edit(call, "✅ Удалено.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data.startswith("editcases_add_"):
        idx = int(data.replace("editcases_add_", ""))
        edit_case_state[user_id] = {"mode": "add_reward", "case_idx": idx, "step": "type"}
        rows = [
            [InlineKeyboardButton(text="💰 Tokens", callback_data="editcases_newtype_tokens"),
             InlineKeyboardButton(text="⚡ Буст", callback_data="editcases_newtype_boost")],
            [InlineKeyboardButton(text="🏷 Титул", callback_data="editcases_newtype_title"),
             InlineKeyboardButton(text="👑 VIP", callback_data="editcases_newtype_vip")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"editcases_item_{idx}")],
        ]
        await safe_edit(call, "➕ <b>НОВАЯ НАГРАДА</b>\n\n👇 Выбери тип:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return
    
    if data.startswith("editcases_newtype_"):
        new_type = data.replace("editcases_newtype_", "")
        st = edit_case_state.get(user_id)
        if not st:
            await call.answer("❌", show_alert=True)
            return
        st["new_type"] = new_type
        st["step"] = "amount" if new_type == "tokens" else "value"
        edit_case_state[user_id] = st
        
        if new_type == "tokens":
            await safe_edit(call, "💰 Введи сумму Tokens:\n\n❌ /editcases")
        elif new_type == "boost":
            await safe_edit(call, "⚡ Введи множитель:\n\n❌ /editcases")
        elif new_type == "title":
            await safe_edit(call, "🏷 Введи название титула:\n\n❌ /editcases")
        elif new_type == "vip":
            await safe_edit(call, "👑 Введи уровень VIP (1-5):\n\n❌ /editcases")
        await call.answer()
        return
    
        # ═══════════════ РЕДАКТОР TOKENS-ПАКОВ ═══════════════

    if data == "edittokens_start":
        packs = get_tokens_packs()
        txt = "TOKENS ПАКИ\n━━━━━━━━━━━━━━\n\n"
        if not packs:
            txt += "Пусто."
        else:
            for i, p in enumerate(packs, 1):
                status = "●" if p.get("active", True) else "○"
                txt += f"{status} {i}. {fmt_num(p['amount'])} Tokens — {p['stars']} ⭐\n"
        
        rows = []
        for i, p in enumerate(packs):
            rows.append([InlineKeyboardButton(
                text=f"{i+1}. {fmt_num(p['amount'])} — {p['stars']}⭐",
                callback_data=f"edittokens_item_{i}"
            )])
        rows.append([InlineKeyboardButton(text="➕ Добавить пакет", callback_data="edittokens_add")])
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
        
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return

    if data.startswith("edittokens_item_"):
        try:
            idx = int(data.replace("edittokens_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        packs = get_tokens_packs()
        if idx < 0 or idx >= len(packs):
            await call.answer("❌ Не найден", show_alert=True)
            return
        
        p = packs[idx]
        status = "● АКТИВЕН" if p.get("active", True) else "○ ВЫКЛЮЧЕН"
        txt = (
            f"TOKENS ПАК\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"№{idx+1}\n"
            f"СУММА: {fmt_num(p['amount'])} Tokens\n"
            f"ЦЕНА: {p['stars']} STARS\n"
            f"СТАТУС: {status}\n\n"
            f"Что меняем?"
        )
        
        rows = [
            [InlineKeyboardButton(text="Сумма", callback_data=f"edittokens_field_{idx}_amount"),
             InlineKeyboardButton(text="Цена", callback_data=f"edittokens_field_{idx}_stars")],
            [InlineKeyboardButton(
                text="ВЫКЛЮЧИТЬ" if p.get("active", True) else "ВКЛЮЧИТЬ",
                callback_data=f"edittokens_toggle_{idx}"
            )],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"edittokens_del_{idx}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="edittokens_start")],
        ]
        await safe_edit(call, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return

    if data.startswith("edittokens_field_"):
        parts = data.replace("edittokens_field_", "").split("_")
        try:
            idx = int(parts[0])
            field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        
        edit_tokens_state[user_id] = {"mode": "edit_tokens", "idx": idx, "field": field}
        
        prompts = {
            "amount": "Введи сумму Tokens (число):",
            "stars": "Введи цену в Stars (число):",
        }
        await safe_edit(
            call,
            f"РЕДАКТИРОВАНИЕ\n\n{prompts.get(field, 'Значение')}\n\n❌ Отмена: /admin"
        )
        await call.answer()
        return

    if data.startswith("edittokens_toggle_"):
        try:
            idx = int(data.replace("edittokens_toggle_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        packs = get_tokens_packs()
        if 0 <= idx < len(packs):
            packs[idx]["active"] = not packs[idx].get("active", True)
            save_tokens_packs(packs)
            await call.answer(f"✅ {'Включён' if packs[idx]['active'] else 'Выключен'}")
        # Вернуть в карточку
        call.data = f"edittokens_item_{idx}"
        await handle_editor_callback(call)
        return

    if data.startswith("edittokens_del_"):
        try:
            idx = int(data.replace("edittokens_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        packs = get_tokens_packs()
        if 0 <= idx < len(packs):
            packs.pop(idx)
            save_tokens_packs(packs)
        await safe_edit(call, "✅ Удалено.", reply_markup=admin_back_kb())
        await call.answer()
        return

    if data == "edittokens_add":
        edit_tokens_state[user_id] = {"mode": "new_tokens", "step": "amount"}
        await safe_edit(
            call,
            "НОВЫЙ ПАК\n\nВведи сумму Tokens (число):\n\n❌ Отмена: /admin"
        )
        await call.answer()
        return
     
        
    
    
    # ═══════════════ ОСТАЛЬНЫЕ РЕДАКТОРЫ (упрощённо) ═══════════════
    
    if data == "editvip_start":
        await safe_edit(call, "👑 <b>РЕДАКТОР VIP</b>\n\nВ разработке. Используй настройки по умолчанию.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "editxp_start":
        await safe_edit(call, "⭐ <b>РЕДАКТОР XP</b>\n\nВ разработке.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "editquest_start":
        await safe_edit(call, "🎯 <b>РЕДАКТОР ЗАДАНИЙ</b>\n\nВ разработке.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    if data == "editlevel_start":
        await safe_edit(call, "🏆 <b>РЕДАКТОР НАГРАД</b>\n\nВ разработке.", reply_markup=admin_back_kb())
        await call.answer()
        return
    
    await call.answer()
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 12/15 — ТЕКСТОВЫЕ ХЕНДЛЕРЫ В ЛС + REPLY-КНОПКИ
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ХЕНДЛЕР ТЕКСТА В ЛС (АДМИН-ДИАЛОГИ + РЕДАКТОРЫ)
# ═══════════════════════════════════════════════════════════════

@dp.message(F.text, F.chat.type == "private")
async def text_handler_private(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    text = message.text.strip()
    
    # ⚠️ СНАЧАЛА обрабатываем Reply-кнопки
    if await handle_reply_button(message, text, user_id, username):
        return
    
    # ═══════════════ BIRTHDAY (для обычных юзеров) ═══════════════
    if user_id != ADMIN_ID:
        if birthday_input_state.get(user_id):
            parts = text.split(".")
            if len(parts) == 2:
                try:
                    d, m = int(parts[0]), int(parts[1])
                    if 1 <= d <= 31 and 1 <= m <= 12:
                        conn = get_conn()
                        c = conn.cursor()
                        c.execute("UPDATE users SET birthday = %s WHERE user_id = %s", (text, user_id))
                        conn.commit()
                        c.close()
                        release_conn(conn)
                        birthday_input_state.pop(user_id, None)
                        await message.answer(
                            f"✅ <b>Дата сохранена: {text}</b>\n\n🎂 Поздравим в этот день!",
                            parse_mode="HTML",
                            reply_markup=private_kb()
                        )
                        return
                except Exception:
                    pass
            await message.answer(
                "❌ Формат: <code>ДД.ММ</code>\nПример: <code>15.06</code>\n\n/profile",
                parse_mode="HTML"
            )
            return
        
        # Для обычных юзеров — ничего дальше
        return
    
    # ═══════════════ БАНК: ВВОД СУММЫ ═══════════════
    if user_id in bank_input_state:
        st = bank_input_state[user_id]
        mode = st.get("mode")
        try:
            amount = int(text)
        except ValueError:
            await message.answer("❌ Введи число:", parse_mode="HTML")
            return
        
        if amount < 1:
            await message.answer("❌ Минимум 1", parse_mode="HTML")
            return
        
        if mode == "deposit":
            bal = get_balance(user_id)
            if bal < amount and not is_unlimited(user_id):
                bank_input_state.pop(user_id, None)
                await message.answer(
                    f"❌ Недостаточно! Баланс: {fmt_num(bal)}",
                    parse_mode="HTML",
                    reply_markup=private_kb()
                )
                return
            set_balance(user_id, -amount)
            new_bank = set_bank(user_id, amount)
            new_bal = get_balance(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>ПОЛОЖЕНО В БАНК</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 +<b>{fmt_num(amount)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(new_bal)}</b>\n"
                f"🏦 Банк: <b>{fmt_num(new_bank)}</b>",
                parse_mode="HTML",
                reply_markup=private_kb()
            )
            return
        
        if mode == "withdraw":
            bank = get_bank(user_id)
            if bank < amount:
                bank_input_state.pop(user_id, None)
                await message.answer(
                    f"❌ В банке {fmt_num(bank)}",
                    parse_mode="HTML",
                    reply_markup=private_kb()
                )
                return
            set_bank(user_id, -amount)
            new_bal = set_balance(user_id, amount)
            new_bank = get_bank(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>СНЯТО ИЗ БАНКА</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 +<b>{fmt_num(amount)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(new_bal)}</b>\n"
                f"🏦 Банк: <b>{fmt_num(new_bank)}</b>",
                parse_mode="HTML",
                reply_markup=private_kb()
            )
            return
        
        bank_input_state.pop(user_id, None)
        return
    
    # ═══════════════ КРЕДИТ: ВВОД СВОЕЙ СУММЫ ═══════════════
    if user_id in credit_input_state:
        st = credit_input_state[user_id]
        if st.get("mode") == "custom_amount":
            try:
                amount = int(text)
            except ValueError:
                await message.answer("❌ Введи число:", parse_mode="HTML")
                return
            
            if amount < CREDIT_MIN:
                await message.answer(f"❌ Минимум: <b>{fmt_num(CREDIT_MIN)}</b>", parse_mode="HTML")
                return
            if amount > CREDIT_MAX:
                await message.answer(f"❌ Максимум: <b>{fmt_num(CREDIT_MAX)}</b>", parse_mode="HTML")
                return
            
            credit_input_state.pop(user_id, None)
            await message.answer(
                f"⚠️ <b>ПОДТВЕРЖДЕНИЕ</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 Сумма: <b>{fmt_num(amount)}</b> Tokens\n"
                f"⏱ Вернуть: <b>{CREDIT_DAYS} дня</b>\n"
                f"📈 Процент: <b>0%</b>\n\n"
                f"❗ Если не вернёшь вовремя —\n"
                f"аккаунт будет <b>заблокирован</b>",
                parse_mode="HTML",
                reply_markup=credit_confirm_kb(amount)
            )
            return
        # ═══════════════ РЕДАКТОР TOKENS (ВВОД) ═══════════════
    
    if user_id in edit_tokens_state:
        st = edit_tokens_state[user_id]
        mode = st.get("mode")
        
        if mode == "edit_tokens":
            idx = st["idx"]
            field = st["field"]
            packs = get_tokens_packs()
            if idx < 0 or idx >= len(packs):
                edit_tokens_state.pop(user_id, None)
                await message.answer("❌ Пакет не найден", parse_mode="HTML")
                return
            try:
                num = int(text.strip())
            except ValueError:
                await message.answer("❌ Введи число:", parse_mode="HTML")
                return
            if num < 1:
                await message.answer("❌ Минимум 1", parse_mode="HTML")
                return
            packs[idx][field] = num
            save_tokens_packs(packs)
            edit_tokens_state.pop(user_id, None)
            await message.answer("✅ Обновлено! /admin", parse_mode="HTML")
            return
        
        if mode == "new_tokens":
            step = st.get("step")
            if step == "amount":
                try:
                    num = int(text.strip())
                except ValueError:
                    await message.answer("❌ Введи число:", parse_mode="HTML")
                    return
                if num < 1:
                    await message.answer("❌ Минимум 1", parse_mode="HTML")
                    return
                st["amount"] = num
                st["step"] = "stars"
                edit_tokens_state[user_id] = st
                await message.answer("Введи цену в Stars:", parse_mode="HTML")
                return
            
            if step == "stars":
                try:
                    num = int(text.strip())
                except ValueError:
                    await message.answer("❌ Введи число:", parse_mode="HTML")
                    return
                if num < 1:
                    await message.answer("❌ Минимум 1", parse_mode="HTML")
                    return
                
                packs = get_tokens_packs()
                packs.append({
                    "id": f"tokens_{st['amount']}_{int(time.time())}",
                    "amount": st["amount"],
                    "stars": num,
                    "active": True,
                })
                save_tokens_packs(packs)
                edit_tokens_state.pop(user_id, None)
                await message.answer("✅ Пакет добавлен! /admin", parse_mode="HTML")
                return
    
    # ═══════════════ РЕДАКТОР МАГАЗИНА: ЦЕНА ЛОТА ═══════════════
    if user_id in edit_shop_state:
        st = edit_shop_state[user_id]
        
        if st.get("mode") == "sell_price":
            inv_id = st.get("inv_id")
            item = find_inventory_item(user_id, inv_id)
            if not item:
                edit_shop_state.pop(user_id, None)
                await message.answer("❌ Предмет не найден", parse_mode="HTML")
                return
            try:
                price = int(text)
            except ValueError:
                await message.answer("❌ Введи число:", parse_mode="HTML")
                return
            if price < 10_000:
                await message.answer("❌ Минимум 10 000", parse_mode="HTML")
                return
            if price > MAX_BALANCE:
                await message.answer(f"❌ Максимум {fmt_num(MAX_BALANCE)}", parse_mode="HTML")
                return
            
            remove_from_inventory(user_id, inv_id)
            add_market_lot(user_id, username, item, price)
            edit_shop_state.pop(user_id, None)
            await message.answer(
                f"✅ <b>ЛОТ ВЫСТАВЛЕН!</b>\n\n"
                f"💰 Цена: <b>{fmt_num(price)}</b> Tokens\n\n"
                f"🏪 /market",
                parse_mode="HTML",
                reply_markup=private_kb()
            )
            return
        
        # Редактор товара магазина
        if st.get("mode") == "edit_shop":
            idx = st["idx"]
            field = st["field"]
            items = get_shop_items()
            if idx < 0 or idx >= len(items):
                edit_shop_state.pop(user_id, None)
                await message.answer("❌ Товар не найден", parse_mode="HTML")
                return
            
            if field == "name":
                items[idx]["name"] = text
            elif field == "desc":
                items[idx]["desc"] = text
            elif field in ("stars", "tokens"):
                try:
                    num = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                items[idx][field] = num if num > 0 else None
            elif field in ("mult", "minutes", "vip_level"):
                try:
                    num = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                items[idx][field] = num
            elif field == "title":
                items[idx]["title"] = text
            
            save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ Обновлено! /editshop", parse_mode="HTML")
            return
    
    # ═══════════════ РЕДАКТОР КЕЙСОВ ═══════════════
    if user_id in edit_case_state:
        st = edit_case_state[user_id]
        
        if st.get("mode") == "add_reward":
            step = st.get("step")
            case_idx = st.get("case_idx")
            new_type = st.get("new_type")
            cases = get_cases()
            
            if case_idx is None or case_idx < 0 or case_idx >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌ Кейс не найден", parse_mode="HTML")
                return
            
            if step == "amount" and new_type == "tokens":
                try:
                    amount = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                st["amount"] = amount
                st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Введи шанс % (0-100):", parse_mode="HTML")
                return
            
            if step == "value" and new_type == "boost":
                try:
                    val = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                st["mult"] = val
                st["step"] = "minutes"
                edit_case_state[user_id] = st
                await message.answer("⏱ Введи минуты:", parse_mode="HTML")
                return
            
            if step == "minutes":
                try:
                    val = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                st["minutes"] = val
                st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Введи шанс %:", parse_mode="HTML")
                return
            
            if step == "value" and new_type == "title":
                st["title"] = text
                st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Введи шанс %:", parse_mode="HTML")
                return
            
            if step == "value" and new_type == "vip":
                try:
                    val = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                st["vip_level"] = val
                st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Введи шанс %:", parse_mode="HTML")
                return
            
            if step == "chance":
                try:
                    chance = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
                
                reward = {"type": new_type, "chance": chance}
                if new_type == "tokens":
                    reward["amount"] = st["amount"]
                elif new_type == "boost":
                    reward["mult"] = st["mult"]
                    reward["minutes"] = st["minutes"]
                elif new_type == "title":
                    reward["title"] = st["title"]
                elif new_type == "vip":
                    reward["vip_level"] = st["vip_level"]
                
                cases[case_idx].setdefault("rewards", []).append(reward)
                save_cases(cases)
                edit_case_state.pop(user_id, None)
                await message.answer("✅ Награда добавлена! /editcases", parse_mode="HTML")
                return
        
        if st.get("mode") == "editcase":
            idx = st["idx"]
            field = st["field"]
            cases = get_cases()
            if idx < 0 or idx >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML")
                return
            
            if field == "name":
                cases[idx]["name"] = text
            elif field == "desc":
                cases[idx]["desc"] = text
            elif field == "stars":
                try:
                    cases[idx]["stars"] = int(text)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML")
                    return
            
            save_cases(cases)
            edit_case_state.pop(user_id, None)
            await message.answer("✅ /editcases", parse_mode="HTML")
            return
    
    # ═══════════════ КУРСЫ ═══════════════
    if user_id in rates_input_state:
        st = rates_input_state[user_id]
        step = st.get("step")
        
        if step == "gram":
            try:
                gram = int(text)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            st["gram"] = gram
            st["step"] = "star"
            rates_input_state[user_id] = st
            await message.answer(
                "⭐ Сколько <b>Star</b> за 150 000 Tokens?\n"
                "Пример: <code>15</code>\n\n"
                "❌ /admin",
                parse_mode="HTML"
            )
            return
        
        if step == "star":
            try:
                star = int(text)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            
            gram = st.get("gram", 1000)
            rates_input_state.pop(user_id, None)
            
            rates_msg = (
                f"💱 <b>ДЕЙСТВУЮЩИЕ ЦЕНЫ НА ОБМЕН:</b>\n"
                f"• {gram} Gram = 10 000 токенов\n"
                f"• {star} Star = 150k токенов\n\n"
                f"(цены обновляются — актуальные всегда в закрепе группы)"
            )
            
            try:
                await bot.send_message(EXCHANGE_CHAT_ID, rates_msg, parse_mode="HTML")
                await message.answer("✅ Курсы отправлены в чат обмена!", parse_mode="HTML")
            except Exception as e:
                await message.answer(f"❌ Ошибка: {e}", parse_mode="HTML")
            return
    
    # ═══════════════ АДМИН-ДЕЙСТВИЯ ═══════════════
    if user_id in admin_action_state:
        st = admin_action_state[user_id]
        mode = st.get("mode")
        admin_action_state.pop(user_id, None)
        
        if mode == "broadcast":
            uids = get_all_user_ids()
            sent, failed = 0, 0
            for uid in uids:
                try:
                    await bot.send_message(uid, f"📢 <b>РАССЫЛКА</b>\n\n{text}", parse_mode="HTML")
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
            await message.answer(f"📢 Готово: ✅ {sent} | ❌ {failed}", parse_mode="HTML")
            return
        
        if mode == "ban":
            uname = text.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            set_banned(uid, True)
            await message.answer(f"🚫 @{uname} забанен!", parse_mode="HTML")
            return
        
        if mode == "vip":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("❌ @user уровень", parse_mode="HTML")
                return
            uname = parts[0].replace("@", "")
            try:
                level = int(parts[1])
            except ValueError:
                await message.answer("❌ Уровень число", parse_mode="HTML")
                return
            if not 0 <= level <= 5:
                await message.answer("❌ 0-5", parse_mode="HTML")
                return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            set_vip_tier(uid, level, 20)
            await message.answer(f"✅ @{uname} → VIP {level}", parse_mode="HTML")
            return
        
        if mode == "title":
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("❌ @user Титул", parse_mode="HTML")
                return
            uname = parts[0].replace("@", "")
            title_text = parts[1]
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            add_title(uid, title_text, user_id)
            await message.answer(f"🏷️ @{uname} → {title_text}", parse_mode="HTML")
            return
        
        if mode == "balance":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма", parse_mode="HTML")
                return
            uname = parts[0].replace("@", "")
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ Сумма число", parse_mode="HTML")
                return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            set_balance_exact(uid, amount)
            await message.answer(f"✅ @{uname}: баланс = {fmt_num(amount)}", parse_mode="HTML")
            return
        
        if mode == "xp":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("❌ @user XP", parse_mode="HTML")
                return
            uname = parts[0].replace("@", "")
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ XP число", parse_mode="HTML")
                return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET xp = %s WHERE user_id = %s", (amount, uid))
            conn.commit()
            c.close()
            release_conn(conn)
            cache_invalidate(f"xp_{uid}")
            await message.answer(f"✅ @{uname} XP = {amount}", parse_mode="HTML")
            return
        
        if mode == "reset":
            uname = text.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            reset_user(uid)
            await message.answer(f"✅ @{uname} сброшен", parse_mode="HTML")
            return
        
        if mode == "bonus":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма / all сумма", parse_mode="HTML")
                return
            target = parts[0]
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML")
                return
            if target.lower() == "all":
                uids = get_all_user_ids()
                count = 0
                for uid in uids:
                    try:
                        set_balance(uid, amount)
                        count += 1
                    except Exception:
                        pass
                await message.answer(f"🎁 +{fmt_num(amount)} всем ({count})", parse_mode="HTML")
                return
            uname = target.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            nb = set_balance(uid, amount)
            await message.answer(f"🎁 +{fmt_num(amount)} → @{uname}\n💎 {fmt_num(nb)}", parse_mode="HTML")
            return
        
        if mode == "logs":
            uname = text.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
                return
            logs = get_user_history(uid, limit=10)
            if not logs:
                await message.answer("📜 Пусто", parse_mode="HTML")
                return
            txt = f"📜 <b>Последние 10 игр @{uname}</b>\n\n"
            for i, (game, bet, win, detail, t) in enumerate(logs, 1):
                profit = win - bet
                emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
                txt += f"{i}. {emoji} {game} | {fmt_num(bet)} → {fmt_num(win)} | {t}\n"
            await message.answer(txt, parse_mode="HTML")
            return
        
        if mode == "jackpot_set":
            try:
                amount = int(text)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML")
                return
            save_jackpot(amount)
            await message.answer(f"✅ Джекпот = {fmt_num(amount)}", parse_mode="HTML")
            return
        
        if mode == "credit_unlock":
            uname = text.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                try:
                    uid = int(text)
                except ValueError:
                    await message.answer("❌ Не найден", parse_mode="HTML")
                    return
            unlock_credit_user(uid)
            await message.answer(f"✅ Игрок {uid} разблокирован по кредиту", parse_mode="HTML")
            return
        
        if mode == "giveaway":
            parts = text.split()
            if len(parts) < 2:
                await message.answer("❌ сумма время", parse_mode="HTML")
                return
            try:
                amount = int(parts[0])
            except ValueError:
                await message.answer("❌ Сумма", parse_mode="HTML")
                return
            time_str = parts[1].lower()
            minutes = 0
            if time_str.endswith("h"):
                minutes = int(time_str[:-1]) * 60
            elif time_str.endswith("m"):
                minutes = int(time_str[:-1])
            if minutes == 0:
                await message.answer("❌ 30m / 1h", parse_mode="HTML")
                return
            ends_at = datetime.now(TZ_MINSK) + timedelta(minutes=minutes)
            conn = get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO giveaways (amount, ends_at, created_by, status)
                         VALUES (%s, %s, %s, 'active')""", (amount, ends_at, user_id))
            conn.commit()
            c.close()
            release_conn(conn)
            await message.answer(f"🎁 Розыгрыш на {fmt_num(amount)}!", parse_mode="HTML")
            return
    
    # ═══════════════ REPLY-КНОПКИ (ВСЕ) ═══════════════



# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА REPLY-КНОПОК
# ═══════════════════════════════════════════════════════════════

async def handle_reply_button(message: Message, text: str, user_id: int, username: str) -> bool:
    """Обработка всех Reply-кнопок в ЛС."""
    
    # ═══════════════ ИГРОК ═══════════════
    
    if text == "🎮 Игры":
        await message.answer(
            "🎮 <b>ИГРЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🎡 Рулетка · 🎰 Слоты · 🪙 Монетка\n"
            "🃏 Блэкджек · 💣 Мины · ⚔️ Дуэль\n\n"
            "💡 Играть можно в группе или Mini App",
            parse_mode="HTML",
            reply_markup=games_kb()
        )
        return True
    
    if text == "💰 Баланс":
        await cmd_balance(message)
        return True
    
    if text == "🏦 Банк":
        await message.answer(bank_text(user_id, username), parse_mode="HTML", reply_markup=bank_kb())
        return True
    
    if text == "💳 Кредиты":
        info = get_credit_amount_info(user_id)
        status = info.get("status", "available")
        await message.answer(credits_text(user_id), parse_mode="HTML", reply_markup=credits_kb(status))
        return True
    
    if text == "👤 Профиль":
        await cmd_profile(message)
        return True
    
    if text == "🎁 Бонус":
        can, left = get_daily_status(user_id)
        if can:
            claim_daily(user_id)
            nb = get_balance(user_id)
            await message.answer(
                f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 +<b>{fmt_num(DAILY_BONUS)}</b> Tokens\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
                f"⏳ Следующий через 24ч",
                parse_mode="HTML"
            )
        else:
            await message.answer(f"⏳ Приходи через <b>{fmt_time_left(left)}</b>", parse_mode="HTML")
        return True
    
    if text == "🛒 Магазин":
        await cmd_shop(message)
        return True
    
    if text == "🎒 Инвентарь":
        await cmd_inventory(message)
        return True
    
    if text == "🏪 Рынок":
        await cmd_market(message)
        return True
    
    if text == "🎯 Задания":
        await cmd_quests(message)
        return True
    
    if text == "🏆 Турнир":
        await message.answer(tournament_text(), parse_mode="HTML")
        return True
    
    if text == "🔗 Рефералка":
        await cmd_ref(message)
        return True
    
    if text == "🌐 WebApp":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Открыть Mini App", web_app=WebAppInfo(url=MINI_APP_URL))]
        ])
        await message.answer(
            "🌐 <b>Mini App</b>\n\n👇 Нажми кнопку:",
            parse_mode="HTML",
            reply_markup=kb
        )
        return True
    
    if text == "🎮 ИГРАТЬ В ГРУППЕ":
        await message.answer(
            "🎮 <b>ИГРАТЬ В ГРУППЕ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Переходи в группу:",
            parse_mode="HTML",
            reply_markup=group_url_kb("🎮 ПЕРЕЙТИ В ГРУППУ")
        )
        return True
    
    
    
        # ═══════════════ АДМИН ═══════════════
    
    if user_id != ADMIN_ID:
        return False
    
    if text == "👥 Игроки":
        await message.answer(
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=admin_players_kb()
        )
        return True
    
    if text == "🎮 Игры":
        await message.answer(
            "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай:",
            parse_mode="HTML",
            reply_markup=admin_games_kb()
        )
        return True
    
    if text == "🛒 Контент":
        await message.answer(
            "🛒 <b>КОНТЕНТ</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=admin_content_kb()
        )
        return True
    
    if text == "💰 Экономика":
        await message.answer(
            "💰 <b>ЭКОНОМИКА</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=admin_economy_kb()
        )
        return True
    
    if text == "📢 Связь":
        await message.answer(
            "📢 <b>СВЯЗЬ</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=admin_comm_kb()
        )
        return True
    
    if text == "📊 Мониторинг":
        await message.answer(
            "📊 <b>МОНИТОРИНГ</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=admin_monitor_kb()
        )
        return True
    
    if text == "💳 Кредиты":
        stats = get_all_credits_stats()
        txt = (
            f"💳 <b>КРЕДИТЫ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Активных: <b>{stats['active_count']}</b>\n"
            f"🚫 Просрочено: <b>{stats['overdue_count']}</b>\n"
            f"📊 Всего: <b>{stats['total_count']}</b>"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_credits_kb())
        return True
    
    if text == "📋 Все команды":
        await message.answer(
            all_commands_text(),
            parse_mode="HTML",
            reply_markup=all_commands_kb()
        )
        return True
    
    return False


# ═══════════════════════════════════════════════════════════════
# РЕДИРЕКТ КОМАНД ИЗ ГРУППЫ В ЛС
# ═══════════════════════════════════════════════════════════════

PRIVATE_ONLY_COMMANDS = [
    "start", "profile", "balance", "top", "shop",
    "market", "vip", "xp", "quests", "ref", "lang",
    "rules", "credits", "cases", "inventory", "inv", "задания",
    "кредиты", "правила", "язык", "турнир", "refs", "ref_top"
]


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def redirect_to_private(message: Message):
    if not message.text:
        return
    
    # Обрабатываем ТОЛЬКО команды с /
    if not message.text.startswith("/"):
        return
    
    text = message.text.strip().lower()
    cmd = text.split()[0].lstrip("/") if text else ""
    
    # Игровые команды — пропускаем
    IGNORE = ["к", "ч", "з", "го", "спин", "орёл", "решка", "бж",
              "мины", "дуэль", "принять", "отмена", "лог", "б",
              "баланс", "топ", "профиль", "задания", "банк", "кредиты", "бонус", "п"]
    if cmd in IGNORE:
        return
    
    if cmd in PRIVATE_ONLY_COMMANDS:
        try:
            await send_temp(
                chat_id=message.chat.id,
                text=(
                    f"⚠️ <b>ЛИЧНЫЕ СООБЩЕНИЯ</b>\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"Эти команды работают только в ЛС.\n\n"
                    f"👇 Напиши боту в личку:\n"
                    f"<b>@{BOT_USERNAME}</b>"
                ),
                delay=120,
                parse_mode="HTML",
                reply_markup=private_url_kb()
            )
        except Exception as e:
            logger.error(f"[redirect] {e}")
        # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 13/15 — FLASK API ДЛЯ MINI APP
# ═══════════════════════════════════════════════════════════════

import random as _random

# ═══════════════ FLASK APP ═══════════════

app = Flask(__name__)
CORS(app)


@app.route("/")
def home():
    return "Tokens Bot API is running!"


@app.route("/health")
def health():
    return "OK"


# ═══════════════ БАЛАНС / ПРОФИЛЬ ═══════════════

@app.route("/api/balance/<int:user_id>")
def api_balance(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned", "banned": True}), 403
    
    xp = get_xp(user_id)
    boost = get_active_boost(user_id)
    boost_data = None
    if boost:
        until = boost[1]
        if until.tzinfo is None:
            until = until.replace(tzinfo=TZ_MINSK)
        boost_data = {
            "mult": boost[0],
            "until": until.isoformat(),
        }
    
    return jsonify({
        "user_id": user_id,
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "unlimited": is_unlimited(user_id),
        "xp": xp,
        "level": xp // 100,
        "vip_tier": get_vip_tier(user_id),
        "vip_expires": get_vip_expires(user_id).isoformat() if get_vip_expires(user_id) else None,
        "boost": boost_data,
    })


@app.route("/api/profile/<int:user_id>")
def api_profile(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    
    u = get_user(user_id)
    username = u[0] if u else f"user_{user_id}"
    xp = get_xp(user_id)
    stats = get_user_stats(user_id)
    titles = get_user_titles(user_id)
    
    # Кредит
    credit_info = get_credit_amount_info(user_id)
    
    # VIP
    vip_tier = get_vip_tier(user_id)
    vip_expires = get_vip_expires(user_id)
    if vip_expires and vip_expires.tzinfo is None:
        vip_expires = vip_expires.replace(tzinfo=TZ_MINSK)
    
    return jsonify({
        "user_id": user_id,
        "username": username,
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "xp": xp,
        "level": xp // 100,
        "rank": get_rank_name(xp // 100),
        "vip_tier": vip_tier,
        "vip_expires": vip_expires.isoformat() if vip_expires else None,
        "cashback": get_user_cashback_percent(user_id),
        "titles": titles,
        "stats": stats,
        "unlimited": is_unlimited(user_id),
        "credit": credit_info,
    })


@app.route("/api/update", methods=["POST"])
def api_update():
    data = request.json
    uid = data.get("user_id")
    amt = data.get("amount")
    if uid is None or amt is None:
        return jsonify({"error": "Missing"}), 400
    if is_banned(uid):
        return jsonify({"error": "Banned"}), 403
    return jsonify({"user_id": uid, "balance": set_balance(uid, amt)})


# ═══════════════ МАГАЗИН ═══════════════

@app.route("/api/shop")
def api_shop():
    return jsonify(get_shop_items())


@app.route("/api/shop/categories")
def api_shop_categories():
    return jsonify(DEFAULT_SHOP_CATEGORIES)


@app.route("/api/shop/buy", methods=["POST"])
def api_shop_buy():
    import requests as _requests
    data = request.json
    user_id = data.get("user_id")
    item_id = data.get("item_id")
    if not user_id or not item_id:
        return jsonify({"error": "Missing"}), 400
    it = get_shop_item_by_id(item_id)
    if not it:
        return jsonify({"error": "Item not found"}), 404
    stars = it.get("stars", 0)
    if not stars or int(stars) < 1:
        return jsonify({"error": "Not available for Stars"}), 400
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": it["name"],
            "description": it.get("desc", ""),
            "payload": f"shop_stars_{item_id}",
            "currency": "XTR",
            "prices": json.dumps([{"label": it["name"], "amount": int(stars)}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════ TOKENS-ПАКИ ═══════════════

@app.route("/api/tokens-packs")
def api_tokens_packs():
    return jsonify(get_tokens_packs())


@app.route("/api/tokens-packs/buy", methods=["POST"])
def api_tokens_packs_buy():
    import requests as _requests
    data = request.json
    user_id = data.get("user_id")
    pack_id = data.get("pack_id")
    if not user_id or not pack_id:
        return jsonify({"error": "Missing"}), 400
    pack = get_tokens_pack_by_id(pack_id)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"💰 {fmt_num(pack['amount'])} Tokens",
            "description": f"Покупка {fmt_num(pack['amount'])} Tokens",
            "payload": f"tokens_{pack_id}",
            "currency": "XTR",
            "prices": json.dumps([{"label": f"{fmt_num(pack['amount'])} Tokens", "amount": int(pack["stars"])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════ КЕЙСЫ ═══════════════

@app.route("/api/cases")
def api_cases():
    return jsonify(get_cases())


@app.route("/api/cases/buy", methods=["POST"])
def api_cases_buy():
    import requests as _requests
    data = request.json
    user_id = data.get("user_id")
    case_id = data.get("case_id")
    if not user_id or not case_id:
        return jsonify({"error": "Missing"}), 400
    case = get_case_by_id(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"Кейс «{case['name']}»",
            "description": case.get("desc", "Кейс с наградами"),
            "payload": f"case_{case_id}",
            "currency": "XTR",
            "prices": json.dumps([{"label": case["name"], "amount": int(case["stars"])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cases/last_reward/<int:user_id>")
def api_last_reward(user_id):
    reward = get_last_reward(user_id)
    if reward:
        return jsonify(reward)
    return jsonify({})


# ═══════════════ VIP / XP ═══════════════

@app.route("/api/vip")
def api_vip():
    return jsonify(get_vip_tiers())


@app.route("/api/vip/buy", methods=["POST"])
def api_vip_buy():
    import requests as _requests
    data = request.json
    user_id = data.get("user_id")
    tier_id = data.get("tier_id")
    if not user_id or not tier_id:
        return jsonify({"error": "Missing"}), 400
    info = get_vip_tier_info(int(tier_id))
    if not info:
        return jsonify({"error": "VIP not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"{info['icon']} VIP {info['id']} — {info['name']}",
            "description": f"Кэшбэк {info['cashback']}%, бонус +{fmt_num(info['bonus'])} Tokens",
            "payload": f"vip_{info['id']}_{info['stars']}",
            "currency": "XTR",
            "prices": json.dumps([{"label": f"VIP {info['id']}", "amount": int(info["stars"])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/xp")
def api_xp():
    return jsonify(get_xp_packs())

    # ═══════════════ API: TOKENS-ПАКИ ═══════════════

@app.route("/api/tokens-packs")
def api_tokens_packs():
    """Список Tokens-паков (активных)."""
    packs = get_tokens_packs()
    return jsonify([p for p in packs if p.get("active", True)])


@app.route("/api/tokens-packs/buy", methods=["POST"])
def api_tokens_packs_buy():
    """Создаёт счёт на Stars для покупки Tokens-пака."""
    import requests as _requests
    
    data = request.json
    user_id = data.get("user_id")
    pack_id = data.get("pack_id")
    
    if not user_id or not pack_id:
        return jsonify({"error": "Missing"}), 400
    
    pack = get_tokens_pack_by_id(pack_id)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    
    stars = pack.get("stars", 0)
    if not stars or stars < 1:
        return jsonify({"error": "Not available"}), 400
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"{fmt_num(pack['amount'])} Tokens",
            "description": f"Покупка {fmt_num(pack['amount'])} Tokens",
            "payload": f"tokens_{pack_id}",
            "currency": "XTR",
            "prices": json.dumps([
                {"label": f"{fmt_num(pack['amount'])} Tokens", "amount": int(stars)}
            ]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/xp/buy", methods=["POST"])
def api_xp_buy():
    import requests as _requests
    data = request.json
    user_id = data.get("user_id")
    pack_id = data.get("pack_id")
    if not user_id or not pack_id:
        return jsonify({"error": "Missing"}), 400
    packs = get_xp_packs()
    pack = next((p for p in packs if p.get("id") == pack_id), None)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"⭐ Буст XP +{pack['xp']}",
            "description": f"Мгновенно +{pack['xp']} XP",
            "payload": f"xp_{pack['id']}_{pack['xp']}_{pack['stars']}",
            "currency": "XTR",
            "prices": json.dumps([{"label": f"+{pack['xp']} XP", "amount": int(pack["stars"])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════ ЗАДАНИЯ ═══════════════

@app.route("/api/quests/<int:user_id>")
def api_quests(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    return jsonify(get_user_daily_quests(user_id))


@app.route("/api/quests/claim", methods=["POST"])
def api_quests_claim():
    data = request.json
    user_id = data.get("user_id")
    quest_key = data.get("quest_key")
    if not user_id or not quest_key:
        return jsonify({"error": "Missing"}), 400
    reward = claim_daily_quest(user_id, quest_key)
    if reward:
        return jsonify({"success": True, "reward": reward, "balance": get_balance(user_id)})
    return jsonify({"success": False, "error": "Already claimed or not completed"})


# ═══════════════ ТОП ═══════════════

@app.route("/api/top")
def api_top():
    mode = request.args.get("mode", "balance")
    if mode == "balance":
        rows = get_top(30)
    elif mode == "xp":
        rows = get_top_xp(30)
    elif mode == "games":
        rows = get_top_games(30)
    elif mode == "wins":
        rows = get_top_wins(30)
    else:
        rows = get_top(30)
    
    result = []
    for r in rows:
        result.append({
            "user_id": r[0],
            "username": r[1],
            "balance": r[2],
            "xp": r[3],
        })
    return jsonify(result)


# ═══════════════ БАНК ═══════════════

@app.route("/api/bank/deposit", methods=["POST"])
def api_bank_deposit():
    data = request.json
    user_id = data.get("user_id")
    amount = data.get("amount")
    if not user_id or not amount:
        return jsonify({"error": "Missing"}), 400
    try:
        amount = int(amount)
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    if amount < 1:
        return jsonify({"error": "Min 1"}), 400
    
    bal = get_balance(user_id)
    if bal < amount and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -amount)
    new_bank = set_bank(user_id, amount)
    return jsonify({
        "success": True,
        "balance": get_balance(user_id),
        "bank": new_bank,
    })


@app.route("/api/bank/withdraw", methods=["POST"])
def api_bank_withdraw():
    data = request.json
    user_id = data.get("user_id")
    amount = data.get("amount")
    if not user_id or not amount:
        return jsonify({"error": "Missing"}), 400
    try:
        amount = int(amount)
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    
    bank = get_bank(user_id)
    if bank < amount:
        return jsonify({"error": f"Not enough in bank (you have {bank})"}), 400
    
    set_bank(user_id, -amount)
    new_bal = set_balance(user_id, amount)
    return jsonify({
        "success": True,
        "balance": new_bal,
        "bank": get_bank(user_id),
    })


# ═══════════════ КРЕДИТЫ ═══════════════

@app.route("/api/credits/<int:user_id>")
def api_credits(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    info = get_credit_amount_info(user_id)
    history = get_credit_history(user_id, 10)
    
    history_list = []
    for cid, amount, issued, due, returned, status in history:
        if issued and issued.tzinfo is None:
            issued = issued.replace(tzinfo=TZ_MINSK)
        if due and due.tzinfo is None:
            due = due.replace(tzinfo=TZ_MINSK)
        history_list.append({
            "id": cid,
            "amount": amount,
            "issued_at": issued.isoformat() if issued else None,
            "due_at": due.isoformat() if due else None,
            "returned_at": returned.isoformat() if returned else None,
            "status": status,
        })
    
    return jsonify({
        "info": info,
        "history": history_list,
    })


@app.route("/api/credits/take", methods=["POST"])
def api_credits_take():
    data = request.json
    user_id = data.get("user_id")
    amount = data.get("amount")
    if not user_id or not amount:
        return jsonify({"error": "Missing"}), 400
    try:
        amount = int(amount)
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    
    ok, msg, due_at = issue_credit(user_id, amount)
    if not ok:
        return jsonify({"error": msg}), 400
    
    return jsonify({
        "success": True,
        "amount": amount,
        "due_at": due_at.isoformat() if due_at else None,
        "balance": get_balance(user_id),
    })


@app.route("/api/credits/return", methods=["POST"])
def api_credits_return():
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing"}), 400
    
    ok, msg = return_credit(user_id)
    if not ok:
        return jsonify({"error": msg}), 400
    
    return jsonify({
        "success": True,
        "balance": get_balance(user_id),
    })


# ═══════════════ ИНВЕНТАРЬ ═══════════════

@app.route("/api/inventory/<int:user_id>")
def api_inventory(user_id):
    return jsonify(get_inventory(user_id))


@app.route("/api/inventory/use", methods=["POST"])
def api_inventory_use():
    data = request.json
    user_id = data.get("user_id")
    inv_id = data.get("inv_id")
    if not user_id or not inv_id:
        return jsonify({"error": "Missing"}), 400
    ok, msg = use_inventory_item(user_id, inv_id)
    if ok:
        return jsonify({"success": True, "message": msg})
    return jsonify({"error": msg}), 400


@app.route("/api/inventory/sell", methods=["POST"])
def api_inventory_sell():
    data = request.json
    user_id = data.get("user_id")
    inv_id = data.get("inv_id")
    price = data.get("price")
    if not user_id or not inv_id or not price:
        return jsonify({"error": "Missing"}), 400
    try:
        price = int(price)
    except Exception:
        return jsonify({"error": "Invalid price"}), 400
    if price < 10_000:
        return jsonify({"error": "Minimum 10 000"}), 400
    if price > MAX_BALANCE:
        return jsonify({"error": "Maximum exceeded"}), 400
    
    item = find_inventory_item(user_id, inv_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    
    u = get_user(user_id)
    uname = u[0] if u else f"user_{user_id}"
    remove_from_inventory(user_id, inv_id)
    lot_id = add_market_lot(user_id, uname, item, price)
    return jsonify({"success": True, "lot_id": lot_id, "price": price})


# ═══════════════ РЫНОК ═══════════════

@app.route("/api/market/lots")
def api_market_lots():
    return jsonify(get_market_lots())


@app.route("/api/market/buy", methods=["POST"])
def api_market_buy():
    data = request.json
    user_id = data.get("user_id")
    lot_id = data.get("lot_id")
    if not user_id or not lot_id:
        return jsonify({"error": "Missing"}), 400
    
    lots = get_market_lots()
    lot_idx = None
    for i, l in enumerate(lots):
        if l.get("id") == lot_id:
            lot_idx = i
            break
    if lot_idx is None:
        return jsonify({"error": "Lot not found"}), 404
    
    ok, msg = buy_market_lot(user_id, lot_idx)
    if ok:
        return jsonify({"success": True, "message": msg})
    return jsonify({"error": msg}), 400


@app.route("/api/market/remove", methods=["POST"])
def api_market_remove():
    data = request.json
    user_id = data.get("user_id")
    lot_id = data.get("lot_id")
    if not user_id or not lot_id:
        return jsonify({"error": "Missing"}), 400
    
    lots = get_market_lots()
    removed = None
    new_lots = []
    for l in lots:
        if l.get("id") == lot_id and l.get("seller_id") == user_id:
            removed = l
        else:
            new_lots.append(l)
    
    if not removed:
        return jsonify({"error": "Not found"}), 404
    
    save_market_lots(new_lots)
    item = dict(removed["payload"])
    item["type"] = removed["type"]
    add_to_inventory(user_id, item)
    return jsonify({"success": True, "message": "Лот снят"})


# ═══════════════ ЕЖЕДНЕВНЫЙ БОНУС ═══════════════

@app.route("/api/daily/status/<int:user_id>")
def api_daily_status(user_id):
    can, left = get_daily_status(user_id)
    return jsonify({"can_claim": can, "time_left": left, "amount": DAILY_BONUS})


@app.route("/api/daily/claim", methods=["POST"])
def api_daily_claim():
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing"}), 400
    if claim_daily(user_id):
        return jsonify({"success": True, "amount": DAILY_BONUS, "balance": get_balance(user_id)})
    return jsonify({"success": False, "error": "Already claimed"})


# ═══════════════ ДЖЕКПОТ ═══════════════

@app.route("/api/jackpot")
def api_jackpot():
    return jsonify({"jackpot": get_jackpot()})


# ═══════════════ ИГРА: РУЛЕТКА ═══════════════

@app.route("/api/game/roulette", methods=["POST"])
def api_game_roulette():
    data = request.json
    user_id = data.get("user_id")
    bet = int(data.get("bet", 0))
    choice = data.get("choice", "red")
    
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    
    ok, err = check_bet_limit("roulette", bet)
    if not ok:
        return jsonify({"error": "Bet exceeds limit"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    result = random.randint(0, 36)
    color = get_roulette_color(result)
    
    mult = 0
    win = False
    
    if choice == "red" and result in RED_NUMBERS:
        win, mult = True, ROULETTE_PAYOUTS["red"]
    elif choice == "black" and result in BLACK_NUMBERS:
        win, mult = True, ROULETTE_PAYOUTS["black"]
    elif choice == "green" and result == 0:
        win, mult = True, ROULETTE_PAYOUTS["zero"]
    
    amount = 0
    if win:
        amount = cap_win(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "рулетка", bet, amount, f"{result} {color}")
        pay_ref_commission(user_id, amount)
    
    add_xp(user_id, 1)
    update_daily_quest(user_id, "daily_bets_5", 1)
    
    return jsonify({
        "win": win,
        "result": result,
        "color": color,
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ ИГРА: СЛОТЫ ═══════════════

@app.route("/api/game/slots", methods=["POST"])
def api_game_slots():
    data = request.json
    user_id = data.get("user_id")
    bet = int(data.get("bet", 0))
    
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    
    ok, err = check_bet_limit("slots", bet)
    if not ok:
        return jsonify({"error": "Bet exceeds limit"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    
    r1 = random.choice(SLOT_SYMBOLS)
    r2 = random.choice(SLOT_SYMBOLS)
    r3 = random.choice(SLOT_SYMBOLS)
    
    win = False
    mult = 0
    if r1 == r2 == r3:
        win = True
        mult = SLOT_PAYOUTS.get(r1, 9)
    elif r1 == r2 or r2 == r3 or r1 == r3:
        win = True
        mult = SLOT_TWO_MATCH
    
    amount = 0
    if win:
        amount = cap_win(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "слоты", bet, amount, f"{r1}{r2}{r3}")
        pay_ref_commission(user_id, amount)
    
    add_xp(user_id, 1)
    update_daily_quest(user_id, "daily_bets_5", 1)
    
    return jsonify({
        "win": win,
        "reels": [r1, r2, r3],
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ ИГРА: МОНЕТКА ═══════════════

@app.route("/api/game/coin", methods=["POST"])
def api_game_coin():
    data = request.json
    user_id = data.get("user_id")
    bet = int(data.get("bet", 0))
    choice = data.get("choice", "heads")
    
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    
    ok, err = check_bet_limit("coin", bet)
    if not ok:
        return jsonify({"error": "Bet exceeds limit"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    result = random.choice(["heads", "tails"])
    win = result == choice
    
    amount = 0
    if win:
        amount = cap_win(int(bet * COIN_PAYOUT * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "монетка", bet, amount, "🦅" if result == "heads" else "👑")
        pay_ref_commission(user_id, amount)
    
    add_xp(user_id, 1)
    update_daily_quest(user_id, "daily_bets_5", 1)
    
    return jsonify({
        "win": win,
        "result": result,
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ ИГРА: МИНЫ ═══════════════

@app.route("/api/game/mines/start", methods=["POST"])
def api_mines_start():
    data = request.json
    user_id = data.get("user_id")
    bet = int(data.get("bet", 0))
    level = data.get("level", "easy")
    
    if not user_id or bet < 10 or level not in MINES_LEVELS:
        return jsonify({"error": "Invalid"}), 400
    
    ok, err = check_bet_limit("mines", bet)
    if not ok:
        return jsonify({"error": "Bet exceeds limit"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    positions = list(range(25))
    random.shuffle(positions)
    mines_positions = set(positions[:MINES_LEVELS[level]["mines"]])
    
    game_data = {
        "bet": bet,
        "level": level,
        "mines": list(mines_positions),
        "opened": []
    }
    
    key = f"mines_game_{user_id}"
    set_setting(key, json.dumps(game_data))
    
    return jsonify({
        "success": True,
        "level": level,
        "bet": bet,
        "mines_count": MINES_LEVELS[level]["mines"],
    })


@app.route("/api/game/mines/open", methods=["POST"])
def api_mines_open():
    data = request.json
    user_id = data.get("user_id")
    idx = int(data.get("idx", -1))
    
    if not user_id or idx < 0 or idx > 24:
        return jsonify({"error": "Invalid"}), 400
    
    key = f"mines_game_{user_id}"
    val = get_setting(key)
    if not val:
        return jsonify({"error": "No active game"}), 400
    
    game = json.loads(val)
    if idx in game["opened"]:
        return jsonify({"error": "Already opened"}), 400
    
    if idx in game["mines"]:
        # БУМ
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()
        c.close()
        release_conn(conn)
        
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "мины", game["bet"], 0, f"{game['level']} бум")
        
        return jsonify({
            "mine": True,
            "idx": idx,
            "win": False,
            "amount": 0,
            "mines": game["mines"],
            "balance": get_balance(user_id),
        })
    
    game["opened"].append(idx)
    opened_count = len(game["opened"])
    mult = calc_mines_mult(25, MINES_LEVELS[game["level"]]["mines"], opened_count)
    safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]
    
    set_setting(key, json.dumps(game))
    
    if opened_count == safe_total:
        wa = cap_win(int(game["bet"] * mult * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, wa)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "мины", game["bet"], wa, f"{game['level']} all")
        pay_ref_commission(user_id, wa)
        
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()
        c.close()
        release_conn(conn)
        
        return jsonify({
            "mine": False,
            "idx": idx,
            "win": True,
            "amount": wa,
            "balance": get_balance(user_id),
            "mult": mult,
            "cashout_auto": True,
            "mines": game["mines"],
        })
    
    return jsonify({
        "mine": False,
        "idx": idx,
        "win": False,
        "amount": 0,
        "mult": mult,
        "opened": game["opened"],
        "balance": get_balance(user_id),
    })


@app.route("/api/game/mines/cashout", methods=["POST"])
def api_mines_cashout():
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Invalid"}), 400
    
    key = f"mines_game_{user_id}"
    val = get_setting(key)
    if not val:
        return jsonify({"error": "No active game"}), 400
    
    game = json.loads(val)
    if not game["opened"]:
        return jsonify({"error": "Open at least 1 cell"}), 400
    
    opened_count = len(game["opened"])
    mult = calc_mines_mult(25, MINES_LEVELS[game["level"]]["mines"], opened_count)
    wa = cap_win(int(game["bet"] * mult * get_event_mult() * get_user_mult(user_id)))
    set_balance(user_id, wa)
    
    u = get_user(user_id)
    uname = u[0] if u else "user"
    log_game(user_id, uname, "мины", game["bet"], wa, f"{game['level']} x{mult}")
    pay_ref_commission(user_id, wa)
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key = %s", (key,))
    conn.commit()
    c.close()
    release_conn(conn)
    
    return jsonify({
        "win": True,
        "amount": wa,
        "mult": mult,
        "balance": get_balance(user_id),
    })


# ═══════════════ CRASH: STATE ═══════════════

crash_state = {
    "round_id": 0,
    "status": "waiting",
    "multiplier": 1.00,
    "crash_point": 0.0,
    "started_at": 0.0,
    "next_round_at": 0.0,
    "history": [],
    "bets": [],
}
crash_lock = asyncio.Lock()


def generate_crash_point():
    r = _random.random()
    if r < 0.02:
        return 1.00
    if r < 0.30:
        return round(_random.uniform(1.20, 2.00), 2)
    if r < 0.65:
        return round(_random.uniform(2.00, 5.00), 2)
    if r < 0.90:
        return round(_random.uniform(5.00, 15.00), 2)
    if r < 0.99:
        return round(_random.uniform(15.00, 50.00), 2)
    return round(_random.uniform(50.00, 200.00), 2)


async def crash_loop():
    global crash_state
    print("🚀 Crash loop запущен")
    
    while True:
        try:
            async with crash_lock:
                crash_state["status"] = "waiting"
                crash_state["multiplier"] = 1.00
                crash_state["crash_point"] = generate_crash_point()
                crash_state["bets"] = []
                crash_state["next_round_at"] = time.time() + 8
                crash_state["round_id"] += 1
            
            await asyncio.sleep(8)
            
            async with crash_lock:
                if crash_state["status"] != "waiting":
                    continue
                crash_state["status"] = "running"
                crash_state["started_at"] = time.time()
            
            start_time = time.time()
            while True:
                elapsed = time.time() - start_time
                multiplier = round(1.0 + elapsed * 0.15 + (elapsed ** 2) * 0.03, 2)
                
                if multiplier >= crash_state["crash_point"]:
                    multiplier = crash_state["crash_point"]
                    async with crash_lock:
                        crash_state["multiplier"] = multiplier
                        crash_state["status"] = "crashed"
                    break
                
                async with crash_lock:
                    crash_state["multiplier"] = multiplier
                
                await check_crash_auto_cashouts(multiplier)
                await asyncio.sleep(0.1)
            
            await finalize_crash_round()
            
            async with crash_lock:
                crash_state["history"].insert(0, crash_state["crash_point"])
                crash_state["history"] = crash_state["history"][:20]
            
            await asyncio.sleep(5)
        
        except Exception as e:
            print(f"[crash_loop] {e}")
            await asyncio.sleep(5)


async def check_crash_auto_cashouts(current_mult):
    async with crash_lock:
        for bet in crash_state["bets"]:
            if bet.get("cashed_out_at"):
                continue
            auto = bet.get("auto_cashout")
            if auto and current_mult >= auto:
                win = cap_win(int(bet["bet"] * auto))
                set_balance(bet["user_id"], win)
                bet["cashed_out_at"] = auto
                bet["won"] = win
                log_game(bet["user_id"], bet["username"], "краш", bet["bet"], win, f"x{auto}")


async def finalize_crash_round():
    async with crash_lock:
        crash_point = crash_state["crash_point"]
        for bet in crash_state["bets"]:
            if bet.get("cashed_out_at"):
                continue
            log_game(bet["user_id"], bet["username"], "краш", bet["bet"], 0, f"boom {crash_point}")


@app.route("/api/crash/state")
def api_crash_state():
    return jsonify({
        "round_id": crash_state["round_id"],
        "status": crash_state["status"],
        "multiplier": crash_state["multiplier"],
        "crash_point": crash_state["crash_point"] if crash_state["status"] == "crashed" else None,
        "next_round_at": crash_state["next_round_at"],
        "history": crash_state["history"][:20],
        "bets": crash_state["bets"],
        "time_to_next": max(0, crash_state["next_round_at"] - time.time()),
    })


@app.route("/api/crash/bet", methods=["POST"])
def api_crash_bet():
    data = request.json
    user_id = data.get("user_id")
    username = data.get("username") or f"user_{user_id}"
    bet = int(data.get("bet", 0))
    auto_cashout = data.get("auto_cashout")
    if auto_cashout:
        try:
            auto_cashout = float(auto_cashout)
        except Exception:
            auto_cashout = None
    
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    
    if crash_state["status"] != "waiting":
        return jsonify({"error": "Round already running"}), 400
    
    for b in crash_state["bets"]:
        if b["user_id"] == user_id:
            return jsonify({"error": "Already bet in this round"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    
    crash_state["bets"].append({
        "user_id": user_id,
        "username": username,
        "bet": bet,
        "auto_cashout": auto_cashout,
        "cashed_out_at": None,
        "won": 0,
    })
    
    return jsonify({"success": True, "balance": get_balance(user_id)})


@app.route("/api/crash/cashout", methods=["POST"])
def api_crash_cashout():
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing"}), 400
    
    if crash_state["status"] != "running":
        return jsonify({"error": "Round not running"}), 400
    
    current_mult = crash_state["multiplier"]
    
    for b in crash_state["bets"]:
        if b["user_id"] == user_id:
            if b["cashed_out_at"]:
                return jsonify({"error": "Already cashed out"}), 400
            win = cap_win(int(b["bet"] * current_mult))
            set_balance(user_id, win)
            b["cashed_out_at"] = current_mult
            b["won"] = win
            log_game(user_id, b["username"], "краш", b["bet"], win, f"x{current_mult}")
            return jsonify({
                "success": True,
                "mult": current_mult,
                "win": win,
                "balance": get_balance(user_id),
            })
    
    return jsonify({"error": "No bet found"}), 400


# ═══════════════ PLINKO ═══════════════

PLINKO_MULTIPLIERS = {
    "low":    [1.5, 1.2, 1.1, 1.0, 0.5, 1.0, 1.1, 1.2, 1.5],
    "medium": [5.0, 2.0, 1.0, 0.5, 0.3, 0.5, 1.0, 2.0, 5.0],
    "high":   [100.0, 10.0, 2.0, 0.5, 0.0, 0.5, 2.0, 10.0, 100.0],
}


def generate_plinko_drop():
    position = 0
    for _ in range(8):
        if _random.random() < 0.5:
            position += 1
    return min(position, 8)


@app.route("/api/plinko/play", methods=["POST"])
def api_plinko_play():
    data = request.json
    user_id = data.get("user_id")
    bet = int(data.get("bet", 0))
    risk = data.get("risk", "medium")
    
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    if risk not in PLINKO_MULTIPLIERS:
        return jsonify({"error": "Invalid risk"}), 400
    
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    
    set_balance(user_id, -bet)
    position = generate_plinko_drop()
    multiplier = PLINKO_MULTIPLIERS[risk][position]
    win = cap_win(int(bet * multiplier)) if multiplier > 0 else 0
    
    if win > 0:
        set_balance(user_id, win)
    
    u = get_user(user_id)
    uname = u[0] if u else f"user_{user_id}"
    log_game(user_id, uname, "плинко", bet, win, f"{risk} x{multiplier} pos{position}")
    
    return jsonify({
        "win": win > 0,
        "position": position,
        "multiplier": multiplier,
        "amount": win,
        "bet": bet,
        "balance": get_balance(user_id),
    })


@app.route("/api/plinko/history")
def api_plinko_history():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""SELECT username, bet, risk, multiplier, won
                     FROM plinko_history
                     WHERE created_at > NOW() - INTERVAL '1 hour'
                     ORDER BY id DESC LIMIT 20""")
        rows = c.fetchall()
        c.close()
        release_conn(conn)
        return jsonify([
            {"username": r[0], "bet": r[1], "risk": r[2], "multiplier": float(r[3]), "won": r[4]}
            for r in rows
        ])
    except Exception:
        return jsonify([])


# ═══════════════ ПЛЕЙЕРЫ (АДМИН) ═══════════════

@app.route("/api/players")
def api_players():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, balance, xp, banned, unlimited
                 FROM users ORDER BY balance DESC""")
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
    total_balance = c.fetchone()[0]
    c.close()
    release_conn(conn)
    
    players = []
    for r in rows:
        players.append({
            "user_id": r[0],
            "username": r[1] or f"user_{r[0]}",
            "balance": r[2] or 0,
            "xp": r[3] or 0,
            "banned": bool(r[4]),
            "unlimited": bool(r[5]),
        })
    return jsonify({
        "total": total,
        "banned": banned,
        "total_balance": total_balance,
        "players": players,
    })


# ═══════════════ ЗАПУСК FLASK В THREAD ═══════════════

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


web_thread = threading.Thread(target=run_web)
web_thread.daemon = True
web_thread.start()
# ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 14/15 — ФОНОВЫЕ ЦИКЛЫ
# ═══════════════════════════════════════════════════════════════

# ═══════════════ БАНК: ПРОЦЕНТЫ ═══════════════

async def bank_interest_loop():
    """
    Начисляет проценты банка раз в 24 часа.
    Проценты начисляются ТОЛЬКО на сумму до 25M.
    """
    while True:
        try:
            await asyncio.sleep(86400)  # 24 часа
            affected = accrue_bank_interest()
            logger.info(f"🏦 Проценты банка начислены: {affected} игроков")
        except Exception as e:
            logger.error(f"[bank_interest_loop] {e}")
            await asyncio.sleep(3600)


# ═══════════════ КЭШБЭК ═══════════════

async def cashback_loop():
    """
    Начисляет кэшбэк (5% + VIP) раз в сутки в 00:00 МСК.
    """
    while True:
        try:
            now = datetime.now(TZ_MINSK)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            wait_seconds = (next_midnight - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            paid = pay_daily_cashback()
            logger.info(f"💸 Кэшбэк начислен: {paid} игроков")
        except Exception as e:
            logger.error(f"[cashback_loop] {e}")
            await asyncio.sleep(3600)


# ═══════════════ ТУРНИРЫ ═══════════════

async def tournament_checker_loop():
    """
    Проверяет, не закончился ли турнир.
    Каждые 5 минут.
    """
    while True:
        await asyncio.sleep(300)
        try:
            t = get_active_tournament()
            if not t:
                continue
            
            ends_at = t[3]
            if ends_at and ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=TZ_MINSK)
            
            if ends_at and ends_at <= datetime.now(TZ_MINSK):
                winners = finish_tournament(t[0])
                if winners:
                    txt = "🏆 <b>ТУРНИР ЗАВЕРШЁН!</b>\n━━━━━━━━━━━━━━\n\n"
                    medals = ["🥇", "🥈", "🥉"]
                    for i, (uid, uname, prize) in enumerate(winners):
                        txt += f"{medals[i]} {uname} — {fmt_num(prize)} Tokens\n"
                    try:
                        await bot.send_message(TOURNAMENT_CHANNEL, txt, parse_mode="HTML")
                    except Exception:
                        pass
                    logger.info(f"🏆 Турнир завершён: {len(winners)} победителей")
        except Exception as e:
            logger.error(f"[tournament_checker_loop] {e}")


# ═══════════════ VIP: ОЧИСТКА ═══════════════

async def vip_expire_loop():
    """
    Удаляет истёкшие VIP раз в час.
    """
    while True:
        await asyncio.sleep(3600)
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM active_vip WHERE expires_at <= NOW()")
            deleted = c.rowcount
            conn.commit()
            c.close()
            release_conn(conn)
            
            if deleted > 0:
                cache_invalidate("vip_tier_")
                logger.info(f"👑 Истёкших VIP удалено: {deleted}")
        except Exception as e:
            logger.error(f"[vip_expire_loop] {e}")


# ═══════════════ КРЕДИТЫ: НАПОМИНАНИЯ ═══════════════

async def credit_reminder_loop():
    """
    Напоминает о кредитах за 24ч.
    Каждый час.
    """
    while True:
        await asyncio.sleep(3600)
        try:
            reminded = remind_credits()
            for uid, amount, hours_left in reminded:
                await send_credit_reminder(uid, amount, hours_left)
                await asyncio.sleep(0.1)
            
            if reminded:
                logger.info(f"⏰ Напоминания о кредитах: {len(reminded)}")
        except Exception as e:
            logger.error(f"[credit_reminder_loop] {e}")


# ═══════════════ КРЕДИТЫ: АВТО-БАН ═══════════════

async def credit_overdue_loop():
    """
    Проверяет просроченные кредиты и банит.
    Каждые 30 минут.
    """
    while True:
        await asyncio.sleep(1800)
        try:
            overdue = check_overdue_credits()
            for uid, amount, days in overdue:
                block_for_credit(uid, amount, days)
                await asyncio.sleep(0.1)
            
            if overdue:
                logger.warning(f"🚫 Просрочено кредитов: {len(overdue)}")
        except Exception as e:
            logger.error(f"[credit_overdue_loop] {e}")


# ═══════════════ РАССЫЛКА КУРСОВ (10:00 МСК) ═══════════════

async def daily_rates_loop():
    """
    Каждый день в 10:00 МСК отправляет админу запрос на курсы.
    
    Логика:
    - Если авторассылка выключена (`auto_rates=off`) — спит 1 час и проверяет снова.
    - Если включена — ждёт 10:00 МСК и отправляет запрос с кнопками.
    - Админ может: ввести курсы, пропустить сегодня или отключить авторассылку.
    """
    while True:
        try:
            # Проверяем статус авторассылки
            auto_rates = get_setting("auto_rates", "on")
            if auto_rates == "off":
                await asyncio.sleep(3600)
                continue
            
            # Считаем время до 10:00 МСК
            now = datetime.now(TZ_MINSK)
            target = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Проверяем ещё раз, не отключили ли авторассылку пока ждали
            if get_setting("auto_rates", "on") == "off":
                continue
            
            # Отправляем админу запрос с кнопками
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Ввести курсы", callback_data="rates_input_start")],
                [InlineKeyboardButton(text="⏭ Пропустить сегодня", callback_data="rates_skip_today")],
                [InlineKeyboardButton(text="🔕 Отключить авторассылку", callback_data="rates_disable_auto")],
            ])
            
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "💱 <b>ОБНОВЛЕНИЕ КУРСОВ</b>\n"
                    "━━━━━━━━━━━━━━\n\n"
                    "🕐 Время: <b>10:00 МСК</b>\n"
                    "📅 Сегодня\n\n"
                    "👇 Что делаем?",
                    parse_mode="HTML",
                    reply_markup=kb
                )
                logger.info("📢 Запрос курсов отправлен админу")
            except Exception as e:
                logger.error(f"[daily_rates] не отправилось админу: {e}")
        
        except Exception as e:
            logger.error(f"[daily_rates_loop] {e}")
            await asyncio.sleep(3600)


# ═══════════════ РОЗЫГРЫШИ ═══════════════

async def giveaway_checker_loop():
    """
    Проверяет розыгрыши. Каждую минуту.
    """
    while True:
        await asyncio.sleep(60)
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM giveaways WHERE status = 'active' AND ends_at <= NOW()")
            rows = c.fetchall()
            c.close()
            release_conn(conn)
            
            for (gid,) in rows:
                conn = get_conn()
                c = conn.cursor()
                c.execute("SELECT user_id, amount FROM giveaways WHERE id = %s AND status = 'active'", (gid,))
                row = c.fetchone()
                if not row:
                    c.close()
                    release_conn(conn)
                    continue
                uid, amount = row
                c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, uid))
                c.execute("UPDATE giveaways SET status = 'finished', winner_id = %s WHERE id = %s", (uid, gid))
                conn.commit()
                c.close()
                release_conn(conn)
                
                try:
                    await bot.send_message(
                        uid,
                        f"🎉 <b>ТЫ ВЫИГРАЛ РОЗЫГРЫШ!</b>\n\n"
                        f"💰 +{fmt_num(amount)} Tokens",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[giveaway_checker_loop] {e}")


# ═══════════════ ЗАПУСК ВСЕХ ЦИКЛОВ ═══════════════

def start_background_tasks():
    """Запускает все фоновые циклы."""
    tasks = [
        bank_interest_loop(),
        cashback_loop(),
        tournament_checker_loop(),
        vip_expire_loop(),
        credit_reminder_loop(),
        credit_overdue_loop(),
        daily_rates_loop(),
        giveaway_checker_loop(),
        crash_loop(),
    ]
    for t in tasks:
        asyncio.create_task(t)
    logger.info(f"✅ Запущено {len(tasks)} фоновых циклов")
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 15/15 — ON_STARTUP, MAIN, ЗАПУСК
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ON_STARTUP ═══════════════

async def on_startup(bot_instance: Bot):
    """
    Настройка команд бота при старте + уведомление админу.
    """
    logger.info("🚀 Бот запускается...")
    
    # Устанавливаем команды в меню Telegram
    commands = [
        BotCommand(command="start",       description="🏠 Запуск"),
        BotCommand(command="profile",     description="👤 Профиль"),
        BotCommand(command="balance",     description="💰 Баланс"),
        BotCommand(command="top",         description="🏆 Топ"),
        BotCommand(command="shop",        description="🛒 Магазин"),
        BotCommand(command="cases",       description="🎰 Кейсы"),
        BotCommand(command="inventory",   description="🎒 Инвентарь"),
        BotCommand(command="market",      description="🏪 Рынок"),
        BotCommand(command="vip",         description="👑 VIP"),
        BotCommand(command="xp",          description="⭐ Буст XP"),
        BotCommand(command="quests",      description="🎯 Задания"),
        BotCommand(command="tournament",  description="🏆 Турнир"),
        BotCommand(command="ref",         description="🔗 Рефералка"),
        BotCommand(command="credits",     description="💳 Кредиты"),
        BotCommand(command="rules",       description="📖 Правила"),
        BotCommand(command="lang",        description="🌐 Язык"),
    ]
    
    try:
        await bot_instance.set_my_commands(
            commands=commands,
            scope=BotCommandScopeDefault()
        )
        logger.info(f"✅ Установлено {len(commands)} команд в меню")
    except Exception as e:
        logger.error(f"[on_startup] set_my_commands: {e}")
    
    # Уведомление админу о запуске
    try:
        await bot_instance.send_message(
            ADMIN_ID,
            "🚀 <b>БОТ ЗАПУЩЕН</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🕐 Время: <b>{datetime.now(TZ_MINSK).strftime('%d.%m %Y %H:%M:%S')}</b>\n"
            f"👥 Игроков: <b>{get_total_players()}</b>\n"
            f"🎮 Игр отключено: <b>{len(disabled_games)}</b>\n"
            f"📊 Статус: <b>✅ Работает</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[on_startup] notify admin: {e}")


async def on_shutdown(bot_instance: Bot):
    """При остановке бота — уведомляем админа."""
    logger.info("🛑 Бот останавливается...")
    try:
        await bot_instance.send_message(
            ADMIN_ID,
            "🛑 <b>БОТ ОСТАНОВЛЕН</b>\n"
            f"🕐 <b>{datetime.now(TZ_MINSK).strftime('%d.%m %Y %H:%M:%S')}</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ═══════════════ MAIN ═══════════════

async def main():
    """
    Главная функция запуска:
    1. Пул соединений
    2. Инициализация БД
    3. Загрузка настроек
    4. Запуск фоновых циклов
    5. On startup
    6. Polling
    """
    # 1. Инициализация пула
    logger.info("📊 Инициализация пула соединений...")
    init_pool()
    
    # 2. Инициализация БД
    logger.info("🗄️ Инициализация БД...")
    init_db()
    
    # 3. Загрузка настроек
    logger.info("⚙️ Загрузка настроек...")
    load_settings()
    
    # 4. Запуск фоновых циклов
    logger.info("⏰ Запуск фоновых циклов...")
    start_background_tasks()
    
    # 5. On startup
    await on_startup(bot)
    
    # 6. Запуск polling
    logger.info("🎰 Запуск polling...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await on_shutdown(bot)


# ═══════════════ ТОЧКА ВХОДА ═══════════════

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот выключен вручную")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
