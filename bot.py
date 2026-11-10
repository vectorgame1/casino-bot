# bot.py
# -*- coding: utf-8 -*-
"""
Telegram Casino Bot (aiogram 3.x + aiosqlite + apscheduler + aiohttp)
Монолитный файл. Готов к деплою на Render.
"""

import os
import re
import json
import time
import random
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Union, List, Dict, Any, Tuple

import aiosqlite
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType, ContentType
from aiogram.filters import Command, CommandStart, CommandObject, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery,
    BotCommand, FSInputFile, InputMediaPhoto, ReplyKeyboardRemove,
    InlineQueryResultArticle, InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold, hitalic, hcode, hlink, hunderline
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# =========================================================
# 1. КОНСТАНТЫ И КОНФИГУРАЦИЯ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "0")
ADMIN_IDS: List[int] = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]
PORT = int(os.getenv("PORT", 8080))
DB_PATH = os.getenv("DB_PATH", "casino.db")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")  # для Render, не обязателен

# Стикеры / эмодзи для игр
DICE_STICKER = "🎲"
DART_STICKER = "🎯"
BASKET_STICKER = "🏀"
FOOTBALL_STICKER = "⚽"
BOWLING_STICKER = "🎳"
SLOTS_STICKER = "🎰"

# Картинки меню
ASSETS_DIR = "assets"
IMG_START = os.path.join(ASSETS_DIR, "start.jpg")
IMG_PROFILE = os.path.join(ASSETS_DIR, "profile.jpg")
IMG_DONATE = os.path.join(ASSETS_DIR, "donate.jpg")
IMG_BONUS = os.path.join(ASSETS_DIR, "bonus.jpg")
IMG_TOP = os.path.join(ASSETS_DIR, "top.jpg")
IMG_REF = os.path.join(ASSETS_DIR, "ref.jpg")
IMG_HOW = os.path.join(ASSETS_DIR, "how_to_play.jpg")

# Игровые лимиты
MIN_BET = 10
MAX_BET = 1_000_000
BONUS_AMOUNT = 5000
BONUS_COOLDOWN_HOURS = 24
REF_PERCENT = 0.10  # 10% от проигрыша реферала
CLAN_CREATE_PRICE = 100_000
CLAN_JOIN_PRICE = 10_000
CLAN_TAX_PERCENT = 0.05
DUEL_MIN_BET = 100
DUEL_MAX_BET = 1_000_000

# VIP
VIP_PRICE_STARS = 100
VIP_DURATION_DAYS = 30
VIP_BONUS_MULTIPLIER = 2

# Рулетка
ROULETTE_SPIN_TIMEOUT = 30  # секунд между ставкой "старт" и спином
ROULETTE_MAX_BET = 1_000_000

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("casino")

# Бот и диспетчер
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Планировщик
scheduler = AsyncIOScheduler(timezone="UTC")

# Глобальные "живые" состояния
active_roulettes: Dict[int, Dict[str, Any]] = {}  # chat_id -> {bets, spinning, task}
active_duels: Dict[str, Dict[str, Any]] = {}      # duel_id -> {...}
mines_games: Dict[str, Dict[str, Any]] = {}       # session_id -> {...}
blackjack_games: Dict[str, Dict[str, Any]] = {}   # session_id -> {...}
lucky_hour_active = False
lucky_hour_end = 0.0


# =========================================================
# 2. БАЗА ДАННЫХ (aiosqlite, CRUD)
# =========================================================

class DB:
    """Обёртка для работы с SQLite (одно соединение, сериализация через lock)."""
    _conn: Optional[aiosqlite.Connection] = None
    _lock = asyncio.Lock()

    @classmethod
    async def init(cls, path: str = DB_PATH) -> None:
        cls._conn = await aiosqlite.connect(path)
        cls._conn.row_factory = aiosqlite.Row
        await cls._conn.execute("PRAGMA journal_mode=WAL")
        await cls._conn.execute("PRAGMA foreign_keys=ON")
        await cls._create_tables()
        log.info("DB initialized: %s", path)

    @classmethod
    async def close(cls) -> None:
        if cls._conn:
            await cls._conn.close()
            cls._conn = None

    @classmethod
    async def _create_tables(cls) -> None:
        q = """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0,
            bonus_last INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            ref_count INTEGER DEFAULT 0,
            clan_id INTEGER DEFAULT 0,
            vip_until INTEGER DEFAULT 0,
            hidden INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            total_wagered INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            last_seen INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL,
            balance INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            tax_percent INTEGER DEFAULT 5,
            members_count INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS clan_members (
            user_id INTEGER PRIMARY KEY,
            clan_id INTEGER NOT NULL,
            joined_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            game TEXT,
            bet INTEGER,
            result INTEGER,
            balance_after INTEGER,
            ts INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            bet INTEGER,
            choice TEXT,
            result TEXT,
            win INTEGER,
            ts INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS duels (
            duel_id TEXT PRIMARY KEY,
            challenger_id INTEGER,
            opponent_id INTEGER,
            bet INTEGER,
            chat_id INTEGER,
            status TEXT DEFAULT 'pending',
            winner_id INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            uses_left INTEGER,
            created_by INTEGER,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS promo_used (
            code TEXT,
            user_id INTEGER,
            ts INTEGER DEFAULT (strftime('%s','now')),
            PRIMARY KEY (code, user_id)
        );
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_id INTEGER,
            amount INTEGER,
            details TEXT,
            ts INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS minefields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            bet INTEGER,
            mines INTEGER,
            opened TEXT,
            bombs TEXT,
            finished INTEGER DEFAULT 0,
            ts INTEGER DEFAULT (strftime('%s','now'))
        );
        """
        await cls._conn.executescript(q)
        await cls._conn.commit()

    # ---------- USERS ----------
    @classmethod
    async def get_user(cls, user_id: int) -> Optional[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            return await cur.fetchone()

    @classmethod
    async def ensure_user(cls, user_id: int, username: str = "", first_name: str = "") -> aiosqlite.Row:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            if row:
                # Обновим username/имя и last_seen
                await cls._conn.execute(
                    "UPDATE users SET username=?, first_name=?, last_seen=? WHERE user_id=?",
                    (username or row["username"], first_name or row["first_name"], int(time.time()), user_id),
                )
                await cls._conn.commit()
                cur = await cls._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
                return await cur.fetchone()
            await cls._conn.execute(
                "INSERT INTO users (user_id, username, first_name, last_seen) VALUES (?,?,?,?)",
                (user_id, username, first_name, int(time.time())),
            )
            await cls._conn.commit()
            cur = await cls._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            return await cur.fetchone()

    @classmethod
    async def update_balance(cls, user_id: int, delta: int) -> int:
        async with cls._lock:
            await cls._conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, user_id)
            )
            await cls._conn.commit()
            cur = await cls._conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return row["balance"] if row else 0

    @classmethod
    async def set_balance(cls, user_id: int, value: int) -> None:
        async with cls._lock:
            await cls._conn.execute("UPDATE users SET balance=? WHERE user_id=?", (value, user_id))
            await cls._conn.commit()

    @classmethod
    async def add_bank(cls, user_id: int, delta: int) -> int:
        async with cls._lock:
            await cls._conn.execute(
                "UPDATE users SET bank = bank + ? WHERE user_id=?", (delta, user_id)
            )
            await cls._conn.commit()
            cur = await cls._conn.execute("SELECT bank FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return row["bank"] if row else 0

    @classmethod
    async def get_balance(cls, user_id: int) -> int:
        u = await cls.get_user(user_id)
        return u["balance"] if u else 0

    @classmethod
    async def has_vip(cls, user_id: int) -> bool:
        u = await cls.get_user(user_id)
        return bool(u and u["vip_until"] > int(time.time()))

    @classmethod
    async def set_vip(cls, user_id: int, days: int) -> None:
        until = int(time.time()) + days * 86400
        async with cls._lock:
            await cls._conn.execute("UPDATE users SET vip_until=? WHERE user_id=?", (until, user_id))
            await cls._conn.commit()

    @classmethod
    async def set_hidden(cls, user_id: int, hidden: int) -> None:
        async with cls._lock:
            await cls._conn.execute("UPDATE users SET hidden=? WHERE user_id=?", (hidden, user_id))
            await cls._conn.commit()

    @classmethod
    async def ban_user(cls, user_id: int, banned: int = 1) -> None:
        async with cls._lock:
            await cls._conn.execute("UPDATE users SET banned=? WHERE user_id=?", (banned, user_id))
            await cls._conn.commit()

    @classmethod
    async def set_referrer(cls, user_id: int, referrer_id: int) -> bool:
        async with cls._lock:
            cur = await cls._conn.execute(
                "SELECT referrer_id FROM users WHERE user_id=?", (user_id,)
            )
            row = await cur.fetchone()
            if not row or row["referrer_id"] != 0:
                return False
            await cls._conn.execute(
                "UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id)
            )
            await cls._conn.execute(
                "UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?", (referrer_id,)
            )
            await cls._conn.commit()
            return True

    @classmethod
    async def inc_stats(cls, user_id: int, wagered: int, won: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                """UPDATE users SET total_games = total_games + 1,
                   total_wagered = total_wagered + ?,
                   total_wins = total_wins + CASE WHEN ?>0 THEN 1 ELSE 0 END,
                   total_losses = total_losses + CASE WHEN ?<0 THEN 1 ELSE 0 END
                   WHERE user_id=?""",
                (wagered, won, won, user_id),
            )
            await cls._conn.commit()

    @classmethod
    async def top_by_balance(cls, limit: int = 10) -> List[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute(
                "SELECT * FROM users WHERE hidden=0 ORDER BY balance DESC LIMIT ?", (limit,)
            )
            return list(await cur.fetchall())

    @classmethod
    async def all_users(cls) -> List[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM users")
            return list(await cur.fetchall())

    # ---------- HISTORY ----------
    @classmethod
    async def log_game(cls, user_id: int, chat_id: int, game: str, bet: int, result: int, balance_after: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT INTO history (user_id, chat_id, game, bet, result, balance_after) VALUES (?,?,?,?,?,?)",
                (user_id, chat_id, game, bet, result, balance_after),
            )
            await cls._conn.commit()

    # ---------- ROULETTE ----------
    @classmethod
    async def log_roulette(cls, chat_id: int, user_id: int, bet: int, choice: str, result: str, win: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT INTO roulette_logs (chat_id, user_id, bet, choice, result, win) VALUES (?,?,?,?,?,?)",
                (chat_id, user_id, bet, choice, result, win),
            )
            await cls._conn.commit()

    @classmethod
    async def roulette_history(cls, chat_id: int, limit: int = 20) -> List[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute(
                "SELECT * FROM roulette_logs WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)
            )
            return list(await cur.fetchall())

    # ---------- SETTINGS ----------
    @classmethod
    async def get_setting(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return row["value"] if row else default

    @classmethod
    async def set_setting(cls, key: str, value: str) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await cls._conn.commit()

    # ---------- PROMO ----------
    @classmethod
    async def create_promo(cls, code: str, amount: int, uses: int, admin_id: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT OR REPLACE INTO promocodes (code, amount, uses_left, created_by) VALUES (?,?,?,?)",
                (code, amount, uses, admin_id),
            )
            await cls._conn.commit()

    @classmethod
    async def use_promo(cls, code: str, user_id: int) -> Tuple[bool, int, str]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM promocodes WHERE code=?", (code,))
            row = await cur.fetchone()
            if not row:
                return False, 0, "Промокод не найден."
            if row["uses_left"] <= 0:
                return False, 0, "Промокод исчерпан."
            cur = await cls._conn.execute(
                "SELECT 1 FROM promo_used WHERE code=? AND user_id=?", (code, user_id)
            )
            if await cur.fetchone():
                return False, 0, "Вы уже активировали этот промокод."
            await cls._conn.execute(
                "UPDATE promocodes SET uses_left = uses_left - 1 WHERE code=?", (code,)
            )
            await cls._conn.execute(
                "INSERT INTO promo_used (code, user_id) VALUES (?,?)", (code, user_id)
            )
            await cls._conn.commit()
            return True, row["amount"], "OK"

    # ---------- CLANS ----------
    @classmethod
    async def create_clan(cls, name: str, owner_id: int) -> Optional[int]:
        async with cls._lock:
            try:
                cur = await cls._conn.execute(
                    "INSERT INTO clans (name, owner_id) VALUES (?,?)", (name, owner_id)
                )
                await cls._conn.commit()
                clan_id = cur.lastrowid
            except sqlite3.IntegrityError:
                return None
            await cls._conn.execute(
                "INSERT OR REPLACE INTO clan_members (user_id, clan_id) VALUES (?,?)",
                (owner_id, clan_id),
            )
            await cls._conn.execute(
                "UPDATE users SET clan_id=? WHERE user_id=?", (clan_id, owner_id)
            )
            await cls._conn.commit()
            return clan_id

    @classmethod
    async def get_clan(cls, clan_id: int) -> Optional[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM clans WHERE clan_id=?", (clan_id,))
            return await cur.fetchone()

    @classmethod
    async def get_clan_by_name(cls, name: str) -> Optional[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT * FROM clans WHERE name=?", (name,))
            return await cur.fetchone()

    @classmethod
    async def get_user_clan(cls, user_id: int) -> Optional[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute(
                "SELECT c.* FROM clans c JOIN clan_members m ON c.clan_id=m.clan_id WHERE m.user_id=?",
                (user_id,),
            )
            return await cur.fetchone()

    @classmethod
    async def list_clans(cls, limit: int = 20) -> List[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute(
                "SELECT * FROM clans ORDER BY balance DESC LIMIT ?", (limit,)
            )
            return list(await cur.fetchall())

    @classmethod
    async def clan_members_list(cls, clan_id: int) -> List[aiosqlite.Row]:
        async with cls._lock:
            cur = await cls._conn.execute(
                """SELECT u.* FROM users u JOIN clan_members m ON u.user_id=m.user_id
                   WHERE m.clan_id=?""", (clan_id,),
            )
            return list(await cur.fetchall())

    @classmethod
    async def join_clan(cls, user_id: int, clan_id: int) -> bool:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT 1 FROM clan_members WHERE user_id=?", (user_id,))
            if await cur.fetchone():
                return False
            await cls._conn.execute(
                "INSERT INTO clan_members (user_id, clan_id) VALUES (?,?)", (user_id, clan_id)
            )
            await cls._conn.execute(
                "UPDATE users SET clan_id=? WHERE user_id=?", (clan_id, user_id)
            )
            await cls._conn.execute(
                "UPDATE clans SET members_count = members_count + 1 WHERE clan_id=?", (clan_id,)
            )
            await cls._conn.commit()
            return True

    @classmethod
    async def leave_clan(cls, user_id: int) -> bool:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return False
            clan_id = row["clan_id"]
            await cls._conn.execute("DELETE FROM clan_members WHERE user_id=?", (user_id,))
            await cls._conn.execute("UPDATE users SET clan_id=0 WHERE user_id=?", (user_id,))
            await cls._conn.execute(
                "UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id=?", (clan_id,)
            )
            await cls._conn.commit()
            return True

    @classmethod
    async def delete_clan(cls, clan_id: int) -> None:
        async with cls._lock:
            await cls._conn.execute("DELETE FROM clan_members WHERE clan_id=?", (clan_id,))
            await cls._conn.execute("UPDATE users SET clan_id=0 WHERE clan_id=?", (clan_id,))
            await cls._conn.execute("DELETE FROM clans WHERE clan_id=?", (clan_id,))
            await cls._conn.commit()

    @classmethod
    async def clan_deposit(cls, clan_id: int, amount: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "UPDATE clans SET balance = balance + ? WHERE clan_id=?", (amount, clan_id)
            )
            await cls._conn.commit()

    @classmethod
    async def clan_upgrade(cls, clan_id: int) -> bool:
        async with cls._lock:
            cur = await cls._conn.execute("SELECT level, balance FROM clans WHERE clan_id=?", (clan_id,))
            row = await cur.fetchone()
            if not row:
                return False
            cost = 50_000 * row["level"]
            if row["balance"] < cost:
                return False
            await cls._conn.execute(
                "UPDATE clans SET balance = balance - ?, level = level + 1 WHERE clan_id=?",
                (cost, clan_id),
            )
            await cls._conn.commit()
            return True

    # ---------- ADMIN LOG ----------
    @classmethod
    async def admin_log(cls, admin_id: int, action: str, target_id: int = 0, amount: int = 0, details: str = "") -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT INTO admin_logs (admin_id, action, target_id, amount, details) VALUES (?,?,?,?,?)",
                (admin_id, action, target_id, amount, details),
            )
            await cls._conn.commit()

    # ---------- DUELS ----------
    @classmethod
    async def create_duel(cls, duel_id: str, challenger: int, bet: int, chat_id: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "INSERT INTO duels (duel_id, challenger_id, bet, chat_id) VALUES (?,?,?,?)",
                (duel_id, challenger, bet, chat_id),
            )
            await cls._conn.commit()

    @classmethod
    async def finish_duel(cls, duel_id: str, opponent_id: int, winner_id: int) -> None:
        async with cls._lock:
            await cls._conn.execute(
                "UPDATE duels SET opponent_id=?, winner_id=?, status='done' WHERE duel_id=?",
                (opponent_id, winner_id, duel_id),
            )
            await cls._conn.commit()

    # ---------- MINES ----------
    @classmethod
    async def save_minefield(cls, user_id: int, chat_id: int, bet: int, mines: int, bombs: List[int]) -> int:
        async with cls._lock:
            cur = await cls._conn.execute(
                "INSERT INTO minefields (user_id, chat_id, bet, mines, bombs) VALUES (?,?,?,?,?)",
                (user_id, chat_id, bet, mines, json.dumps(bombs)),
            )
            await cls._conn.commit()
            return cur.lastrowid


# =========================================================
# 3. МЕГА-БЛОК ТЕКСТОВ
# =========================================================

HOW_TO_PLAY_DICE = """
🎲 <b>КАК ИГРАТЬ В КОСТИ / ДАРТС / БАСКЕТ / ФУТБОЛ / БОУЛИНГ</b> 🎲

<b>Суть игры:</b>
Это игры на удачу с анимированными эмодзи от Telegram.
Ты отправляешь стикер-эмодзи, бот ждёт результат и сравнивает его с твоим прогнозом.

<b>Команды:</b>
• <code>/dice 500 1-3</code> — ставка 500 на выпадение 1, 2 или 3
• <code>/dart 1000 4-6</code> — ставка 1000 на 4, 5 или 6
• <code>/basket 250 3</code> — ставка 250 ровно на 3
• <code>/football 100 1-2</code> — ставка 100 на 1 или 2
• <code>/bowling 750 5-6</code> — ставка 750 на 5 или 6

<b>Коэффициенты:</b>
• Угадал 1 значение — x2 к ставке
• Угадал диапазон из 2 значений — x1.5
• Угадал диапазон из 3 значений — x1.2
• Не угадал — ставка сгорает

<b>Пример:</b>
Ты пишешь <code>/dice 1000 1-3</code>.
Бот бросает кубик. Если выпало 1, 2 или 3 — ты получаешь 1500 монет (x1.5), чистая прибыль 500.
Если выпало 4, 5 или 6 — минус 1000.

<b>Совет:</b> чем уже диапазон, тем выше риск и тем выше выплата.
"""

HOW_TO_PLAY_MINES = """
💣 <b>КАК ИГРАТЬ В МИНЫ (поле 5×5)</b> 💣

<b>Суть игры:</b>
Перед тобой поле 25 клеток. Под некоторыми спрятаны мины.
Твоя задача — открывать безопасные клетки и вовремя остановиться (кэшаут).

<b>Как начать:</b>
• <code>/mines 500 5</code> — ставка 500, 5 мин на поле
• Минимум 1 мина, максимум 20 мин

<b>Как играть:</b>
1. Бот присылает сетку 5×5 с кнопками.
2. Ты нажимаешь клетки. Если мина — проигрыш.
3. Если безопасно — открывается клетка, коэффициент растёт.
4. Кнопка <b>💰 Забрать</b> — фиксирует выигрыш.

<b>Коэффициенты:</b>
Чем больше мин и чем больше открыто клеток — тем выше множитель.
Формула: <code>множитель = (25 / (25 - mines) ) ^ opened</code>

<b>Пример:</b>
Ставка 1000, 5 мин. Открыл 3 безопасных клетки → коэффициент ~1.5 → забираешь 1500.
Нажал на мину → теряешь 1000.

<b>Совет:</b> не жадничай — фиксируй прибыль вовремя.
"""

HOW_TO_PLAY_ROULETTE = """
🎰 <b>КАК ИГРАТЬ В РУЛЕТКУ</b> 🎰

<b>Суть:</b>
Это чат-рулетка. Игроки пишут ставки в чат, затем ведущий (или любой) пишет <code>старт</code>,
бот делает спин и определяет победителей.

<b>Форматы ставок (пиши в чат):</b>
• <code>к 1000</code> — ставка 1000 на красное
• <code>ч 500</code> — ставка 500 на чёрное
• <code>з 250</code> — ставка 250 на зеро
• <code>10-20 500</code> — ставка 500 на диапазон 10–20
• <code>500 10-20</code> — то же самое (бот умный)
• <code>100 200 300</code> — три отдельных ставки на 100, 200, 300

<b>Что происходит при "старт":</b>
1. Бот собирает все ставки.
2. Выполняется спин (число 0–36).
3. Красное / чёрное / зеро определяется по правилам рулетки.
4. Победителям начисляется выигрыш: x2 за цвет, x36 за зеро.

<b>Проверить ставки:</b> <code>лог</code> — покажет последние ставки в чате.

<b>Важно:</b> играть можно только в группах. В личке рулетка не работает.

<b>Пример:</b>
Ты пишешь <code>к 1000</code>. Ведущий пишет <code>старт</code>.
Выпало 17 (красное) → ты получаешь 2000 монет (чистая прибыль 1000).
Выпало 8 (чёрное) → минус 1000.
"""

HOW_TO_PLAY_DUELS = """
⚔️ <b>КАК ИГРАТЬ В ДУЭЛИ</b> ⚔️

<b>Суть:</b>
Ты вызываешь другого игрока на дуэль. Побеждает случайный.
Победитель забирает весь банк.

<b>Как создать дуэль:</b>
• <code>/duel 1000</code> — вызвать на дуэль за 1000 монет
• Или нажми reply на сообщение игрока и напиши <code>/duel 500</code>

<b>Как принять:</b>
1. Бот присылает сообщение с кнопкой <b>✅ Принять</b>.
2. Второй игрок нажимает кнопку.
3. Бот списывает ставку у обоих.
4. Случайно выбирается победитель.
5. Победитель получает банк (2 × ставка).

<b>Ограничения:</b>
• Минимальная ставка — 100
• Максимальная ставка — 1 000 000
• Нельзя дуэлиться с самим собой

<b>Совет:</b> вызывай только тех, кто онлайн.
"""

COMMANDS_TEXT = """
📖 <b>СПИСОК КОМАНД</b> 📖

<b>🎮 Игры:</b>
<code>/dice сумма диапазон</code> — кости
<code>/dart сумма диапазон</code> — дартс
<code>/basket сумма диапазон</code> — баскет
<code>/football сумма диапазон</code> — футбол
<code>/bowling сумма диапазон</code> — боулинг
<code>/mines сумма мины</code> — мины
<code>/bj сумма</code> — блэкджек
<code>/duel сумма</code> — дуэль
<code>/gift сумма</code> — подарок
<code>старт</code> — спин рулетки (в группе)

<b>👤 Профиль:</b>
<code>/profile</code> — профиль
<code>/bonus</code> — ежедневный бонус
<code>/ref</code> — реферальная ссылка
<code>/top</code> — топ игроков
<code>/promo КОД</code> — активировать промокод

<b>🏰 Кланы:</b>
<code>/clan create Имя</code> — создать клан
<code>/clan list</code> — список кланов
<code>/clan join Имя</code> — вступить
<code>/clan info</code> — инфо о своём клане
<code>/clan dep 1000</code> — внести в казну
<code>/clan up</code> — прокачать клан
<code>/clan leave</code> — покинуть клан
<code>/clan kick @user</code> — кикнуть (owner)
<code>/clan delete</code> — удалить клан (owner)

<b>⭐ VIP:</b>
<code>/vip</code> — купить VIP за Stars

<b>🆘 Поддержка:</b>
<code>/help</code> — помощь
<code>/support</code> — поддержка
"""

ADMIN_HELP = """
🛡 <b>АДМИН-КОМАНДЫ (Нейро-Админ)</b> 🛡

<b>Работают через @ и Reply (ответ на сообщение):</b>

<b>💰 Экономика:</b>
<code>@выдать 1000</code> — выдать 1000 монет (себе или reply)
<code>@забрать 500</code> — забрать 500 монет
<code>@обнулить</code> — обнулить баланс
<code>@дроп 5000</code> — дроп в чат (кто первый нажмёт)
<code>@дроп_всем 1000</code> — дроп всем пользователям бота
<code>@выдать_vip 30</code> — выдать VIP на 30 дней

<b>👤 Пользователи:</b>
<code>@бан</code> — забанить
<code>@разбан</code> — разбанить
<code>@юзер</code> — инфо о пользователе
<code>@стата</code> — статистика бота
<code>@топ_баланс</code> — топ по балансу
<code>@лог 50</code> — последние действия

<b>📢 Рассылки:</b>
<code>@рассылка текст</code> — рассылка всем
<code>@очистить</code> — очистить чат (удалить сообщения бота)

<b>⚙️ Система:</b>
<code>@бекап</code> — создать бекап БД
<code>@рестарт</code> — перезапустить бота
<code>@помощь</code> — эта справка

<b>🎁 Промокоды:</b>
<code>/addpromo КОД СУММА ИСПОЛЬЗОВАНИЙ</code>
"""

WELCOME_TEXT = """
🎰 <b>Добро пожаловать в Casino Bot!</b> 🎰

Здесь ты можешь:
• 🎲 Играть в 11 игр
• 🏰 Создавать кланы
• ⭐ Покупать VIP
• 🎁 Получать бонусы
• 👥 Приглашать друзей

<b>Нажми кнопку ниже, чтобы начать!</b>
"""

PROFILE_TEXT_TEMPLATE = """
👤 <b>Профиль игрока</b>

🆔 ID: <code>{user_id}</code>
👤 Имя: <b>{name}</b>
💰 Баланс: <b>{balance:,}</b> монет
🏦 Банк: <b>{bank:,}</b> монет
⭐ VIP: {vip}
🏰 Клан: {clan}

📊 <b>Статистика:</b>
🎮 Игр: <b>{games}</b>
🏆 Побед: <b>{wins}</b>
💀 Проигрышей: <b>{losses}</b>
💸 Всего проставлено: <b>{wagered:,}</b>
👥 Рефералов: <b>{refs}</b>
"""

DONATE_TEXT_TEMPLATE = """
💎 <b>ДОНАТ</b> 💎

<b>Курс звезды:</b> {rate} монет за ⭐
<b>Обновляется:</b> каждые 3 часа

<b>Пакеты:</b>
• 50 ⭐ = {p50:,} монет
• 100 ⭐ = {p100:,} монет
• 250 ⭐ = {p250:,} монет
• 500 ⭐ = {p500:,} монет

<b>VIP-статус:</b> {vip_price} ⭐ на 30 дней
Даёт: x2 бонус, без налогов, скрытый режим

Нажми кнопку ниже, чтобы купить Stars.
"""

BONUS_TEXT = """
🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b> 🎁

Ты получаешь <b>{amount:,}</b> монет раз в 24 часа!
{vip_bonus}

Следующий бонус: <b>{next_time}</b>
"""

TOP_TEXT_HEADER = """
🏆 <b>ТОП-10 ИГРОКОВ</b> 🏆
"""

REF_TEXT_TEMPLATE = """
👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b> 👥

Приглашай друзей и получай <b>{percent}%</b> от их проигрышей!

Твоя ссылка:
<code>{link}</code>

👥 Приглашено: <b>{count}</b> человек
💰 Заработано: <b>{earned:,}</b> монет

<b>Как это работает:</b>
1. Отправь ссылку другу
2. Друг регистрируется
3. Ты получаешь 10% от каждого его проигрыша
"""

# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (начало)
# =========================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def fmt(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")

async def get_star_rate() -> int:
    """Динамический курс звезды (хранится в settings, обновляется раз в 3 часа)."""
    val = await DB.get_setting("star_rate")
    if val is None:
        rate = 100
        await DB.set_setting("star_rate", str(rate))
        return rate
    return int(val)

async def refresh_star_rate() -> None:
    """Обновление курса звезды — вызывается APScheduler'ом раз в 3 часа."""
    old = await get_star_rate()
    new = random.randint(80, 150)
    await DB.set_setting("star_rate", str(new))
    log.info("Star rate updated: %s -> %s", old, new)

async def safe_send_photo(chat_id: int, photo_path: str, caption: str,
                         reply_markup=None, parse_mode=ParseMode.HTML) -> Optional[Message]:
    """Отправляет фото, если файл существует. Иначе — текст."""
    try:
        if os.path.exists(photo_path):
            return await bot.send_photo(
                chat_id=chat_id, photo=FSInputFile(photo_path),
                caption=caption, reply_markup=reply_markup, parse_mode=parse_mode,
            )
        else:
            return await bot.send_message(
                chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode,
            )
    except TelegramBadRequest as e:
        log.warning("safe_send_photo error: %s", e)
        try:
            return await bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)
        except Exception:
            return None

async def auto_delete(message: Message, delay: int = 5) -> None:
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
        except Exception:
            pass

def parse_bet_amount(raw: str) -> Optional[int]:
    """Парсит '1к', '1.5к', '1000', '1 000'."""
    s = raw.strip().lower().replace(" ", "").replace(",", ".")
    try:
        if s.endswith("к") or s.endswith("k"):
            val = float(s[:-1]) * 1000
            return int(val)
        if s.endswith("кк") or s.endswith("kk"):
            val = float(s[:-2]) * 1_000_000
            return int(val)
        return int(float(s))
    except Exception:
        return None

def format_timedelta(seconds: int) -> str:
    if seconds <= 0:
        return "сейчас"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s and not h:
        parts.append(f"{s}с")
    return " ".join(parts) if parts else "сейчас"

def gen_id(length: int = 10) -> str:
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=length))

# --- Безопасная проверка состояния игры ---
async def check_banned(message: Message) -> bool:
    if not message.from_user:
        return False
    u = await DB.get_user(message.from_user.id)
    if u and u["banned"]:
        await message.answer("🚫 <b>Вы забанены в боте.</b>")
        return True
    return False

# =========================================================
# КОНЕЦ ЧАСТИ 1
# =========================================================

# =========================================================
# 4. КЛАВИАТУРЫ
# =========================================================

def main_reply_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="🎮 Игры")
    kb.button(text="👤 Профиль")
    kb.button(text="💎 Донат")
    kb.button(text="🎁 Бонус")
    kb.button(text="🏆 Топ")
    kb.button(text="🏰 Кланы")
    kb.button(text="👥 Рефералка")
    kb.button(text="📖 Как играть")
    kb.button(text="🆘 Поддержка")
    kb.button(text="💬 Чаты")
    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup(resize_keyboard=True)


def games_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Кости", callback_data="game:info:dice")
    kb.button(text="🎯 Дартс", callback_data="game:info:dart")
    kb.button(text="🏀 Баскет", callback_data="game:info:basket")
    kb.button(text="⚽ Футбол", callback_data="game:info:football")
    kb.button(text="🎳 Боулинг", callback_data="game:info:bowling")
    kb.button(text="🎰 Слоты", callback_data="game:info:slots")
    kb.button(text="🃏 БЖ", callback_data="game:info:bj")
    kb.button(text="💣 Мины", callback_data="game:info:mines")
    kb.button(text="⚔️ Дуэли", callback_data="game:info:duel")
    kb.button(text="🎁 Подарки", callback_data="game:info:gift")
    kb.button(text="🎰 Рулетка", callback_data="game:info:roulette")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def profile_inline_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Бонус", callback_data="menu:bonus")
    kb.button(text="👥 Рефералка", callback_data="menu:ref")
    kb.button(text="⭐ VIP", callback_data="menu:vip")
    kb.button(text="🎮 Игры", callback_data="menu:games")
    kb.adjust(2, 2)
    return kb.as_markup()


def donate_inline_kb(rate: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ 50 → {fmt(50*rate)}", callback_data="donate:50")
    kb.button(text=f"⭐ 100 → {fmt(100*rate)}", callback_data="donate:100")
    kb.button(text=f"⭐ 250 → {fmt(250*rate)}", callback_data="donate:250")
    kb.button(text=f"⭐ 500 → {fmt(500*rate)}", callback_data="donate:500")
    kb.button(text=f"⭐ VIP (30 дней) — {VIP_PRICE_STARS}⭐", callback_data="donate:vip")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def clan_inline_kb(has_clan: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_clan:
        kb.button(text="📊 Инфо", callback_data="clan:info")
        kb.button(text="💰 Внести в казну", callback_data="clan:deposit")
        kb.button(text="⬆️ Прокачать", callback_data="clan:upgrade")
        kb.button(text="👥 Участники", callback_data="clan:members")
        kb.button(text="🚪 Покинуть", callback_data="clan:leave")
        kb.adjust(2, 2, 1)
    else:
        kb.button(text="➕ Создать (100 000)", callback_data="clan:create")
        kb.button(text="📋 Список кланов", callback_data="clan:list")
        kb.adjust(1, 1)
    return kb.as_markup()


def support_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Как заработать", callback_data="support:earn")
    kb.button(text="🐞 Ошибка", callback_data="support:bug")
    kb.button(text="✍️ Написать админу", url="https://t.me/username_admin")
    kb.button(text="💬 Чаты", callback_data="support:chats")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def chats_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Основной чат", url="https://t.me/your_chat")
    kb.button(text="🎁 Дроп-чат", url="https://t.me/your_drop_chat")
    kb.button(text="📣 Новости", url="https://t.me/your_news")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def mines_inline_kb(session_id: str, opened: List[int], finished: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in range(25):
        if i in opened:
            kb.button(text="💎", callback_data="mines:noop")
        elif finished:
            kb.button(text="⬜", callback_data="mines:noop")
        else:
            kb.button(text="⬜", callback_data=f"mines:open:{session_id}:{i}")
    if not finished:
        kb.button(text="💰 Забрать", callback_data=f"mines:cashout:{session_id}")
    kb.adjust(5, 5, 5, 5, 5, 1)
    return kb.as_markup()


def bj_inline_kb(session_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🃏 Ещё", callback_data=f"bj:hit:{session_id}")
    kb.button(text="✋ Хватит", callback_data=f"bj:stand:{session_id}")
    kb.adjust(2)
    return kb.as_markup()


def duel_inline_kb(duel_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"duel:accept:{duel_id}")
    kb.button(text="❌ Отклонить", callback_data=f"duel:decline:{duel_id}")
    kb.adjust(2)
    return kb.as_markup()


def top_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="top:refresh")
    kb.adjust(1)
    return kb.as_markup()


def admin_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Стата", callback_data="adm:stats")
    kb.button(text="📢 Рассылка", callback_data="adm:broadcast_help")
    kb.button(text="💾 Бекап", callback_data="adm:backup")
    kb.adjust(2, 1)
    return kb.as_markup()


# =========================================================
# 5. ОБРАБОТЧИКИ МЕНЮ (Часть 1)
# =========================================================

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    if await check_banned(message):
        return
    user = message.from_user
    db_user = await DB.ensure_user(user.id, user.username or "", user.first_name or "")

    # Реферальная система
    if command.args and command.args.startswith("ref_"):
        try:
            ref_id = int(command.args.split("_")[1])
        except Exception:
            ref_id = 0
        if ref_id and ref_id != user.id:
            ok = await DB.set_referrer(user.id, ref_id)
            if ok:
                try:
                    await bot.send_message(
                        ref_id,
                        f"👥 <b>Новый реферал!</b>\n\n"
                        f"Пользователь <b>{user.first_name}</b> присоединился по твоей ссылке.\n"
                        f"Ты будешь получать 10% от его проигрышей."
                    )
                except Exception:
                    pass

    text = WELCOME_TEXT
    await safe_send_photo(
        message.chat.id, IMG_START, text,
        reply_markup=main_reply_kb(),
    )
    # Уведомление админам о новом юзере
    if db_user["created_at"] and int(time.time()) - db_user["created_at"] < 10:
        for aid in ADMIN_IDS:
            try:
                await bot.send_message(
                    aid,
                    f"🆕 Новый пользователь: <b>{user.first_name}</b> (@{user.username or '—'})\n"
                    f"ID: <code>{user.id}</code>"
                )
            except Exception:
                pass


@router.message(F.text == "🎮 Игры")
async def menu_games(message: Message):
    if await check_banned(message):
        return
    await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await message.answer(
        "🎮 <b>Выбери игру:</b>\n\n"
        "Нажми на игру, чтобы увидеть инструкцию и начать.",
        reply_markup=games_inline_kb(),
    )


@router.callback_query(F.data.startswith("game:info:"))
async def game_info_cb(cb: CallbackQuery):
    await cb.answer()
    game = cb.data.split(":")[2]
    texts = {
        "dice": ("🎲 <b>Кости</b>\n\n" + HOW_TO_PLAY_DICE, "/dice 500 1-3"),
        "dart": ("🎯 <b>Дартс</b>\n\n" + HOW_TO_PLAY_DICE.replace("🎲", "🎯"), "/dart 500 1-3"),
        "basket": ("🏀 <b>Баскет</b>\n\n" + HOW_TO_PLAY_DICE.replace("🎲", "🏀"), "/basket 500 1-3"),
        "football": ("⚽ <b>Футбол</b>\n\n" + HOW_TO_PLAY_DICE.replace("🎲", "⚽"), "/football 500 1-3"),
        "bowling": ("🎳 <b>Боулинг</b>\n\n" + HOW_TO_PLAY_DICE.replace("🎲", "🎳"), "/bowling 500 1-3"),
        "slots": ("🎰 <b>Слоты</b>\n\n"
                  "Команда: <code>/slots 500</code>\n\n"
                  "Крутишь слоты, выигрыш зависит от комбинации.", "/slots 500"),
        "bj": ("🃏 <b>Блэкджек</b>\n\n" + HOW_TO_PLAY_DICE.split("🎲")[0].replace("КОСТИ / ДАРТС / БАСКЕТ / ФУТБОЛ / БОУЛИНГ", "БЛЭКДЖЕК") +
               "\nКоманда: <code>/bj 500</code>\n\n"
               "Набирай карты до 21. Больше 21 — проигрыш. Дилер берёт до 17.", "/bj 500"),
        "mines": ("💣 <b>Мины</b>\n\n" + HOW_TO_PLAY_MINES, "/mines 500 5"),
        "duel": ("⚔️ <b>Дуэли</b>\n\n" + HOW_TO_PLAY_DUELS, "/duel 1000"),
        "gift": ("🎁 <b>Подарки</b>\n\n"
                 "Перевод монет другому игроку.\n\n"
                 "Команда: <code>/gift 500</code> (reply или аргумент получателя)\n"
                 "Пример: <code>/gift 500</code> в ответ на сообщение игрока.", "/gift 500"),
        "roulette": ("🎰 <b>Рулетка</b>\n\n" + HOW_TO_PLAY_ROULETTE, "старт"),
    }
    if game in texts:
        text, cmd = texts[game]
        text += f"\n\n<b>Пример команды:</b>\n<code>{cmd}</code>"
        try:
            await cb.message.edit_text(text, reply_markup=games_inline_kb())
        except TelegramBadRequest:
            await cb.message.answer(text, reply_markup=games_inline_kb())


@router.message(F.text == "👤 Профиль")
async def menu_profile(message: Message):
    if await check_banned(message):
        return
    u = message.from_user
    db_user = await DB.ensure_user(u.id, u.username or "", u.first_name or "")
    await send_profile(message.chat.id, db_user)


@router.callback_query(F.data == "menu:profile")
async def profile_cb(cb: CallbackQuery):
    await cb.answer()
    db_user = await DB.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    await send_profile(cb.message.chat.id, db_user, edit=cb.message)


async def send_profile(chat_id: int, db_user, edit: Optional[Message] = None):
    clan_name = "—"
    if db_user["clan_id"]:
        c = await DB.get_clan(db_user["clan_id"])
        if c:
            clan_name = f"<b>{c['name']}</b> (lvl {c['level']})"

    vip_status = "❌ нет"
    if db_user["vip_until"] > int(time.time()):
        days_left = (db_user["vip_until"] - int(time.time())) // 86400
        vip_status = f"✅ активен ({days_left} дн.)"

    text = PROFILE_TEXT_TEMPLATE.format(
        user_id=db_user["user_id"],
        name=db_user["first_name"] or "Игрок",
        balance=db_user["balance"],
        bank=db_user["bank"],
        vip=vip_status,
        clan=clan_name,
        games=db_user["total_games"],
        wins=db_user["total_wins"],
        losses=db_user["total_losses"],
        wagered=db_user["total_wagered"],
        refs=db_user["ref_count"],
    )
    kb = profile_inline_kb(db_user["user_id"])

    if edit:
        try:
            await edit.delete()
        except Exception:
            pass
    await safe_send_photo(chat_id, IMG_PROFILE, text, reply_markup=kb)


@router.message(F.text == "💎 Донат")
async def menu_donate(message: Message):
    if await check_banned(message):
        return
    await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    rate = await get_star_rate()
    text = DONATE_TEXT_TEMPLATE.format(
        rate=rate, p50=50*rate, p100=100*rate, p250=250*rate, p500=500*rate,
        vip_price=VIP_PRICE_STARS,
    )
    await safe_send_photo(message.chat.id, IMG_DONATE, text, reply_markup=donate_inline_kb(rate))


@router.callback_query(F.data.startswith("donate:"))
async def donate_cb(cb: CallbackQuery):
    await cb.answer()
    arg = cb.data.split(":")[1]
    rate = await get_star_rate()

    if arg == "vip":
        stars = VIP_PRICE_STARS
        payload = f"vip_{cb.from_user.id}"
        title = "VIP-статус"
        desc = f"VIP на {VIP_DURATION_DAYS} дней: x2 бонус, без налогов, скрытый режим."
    else:
        try:
            stars = int(arg)
        except Exception:
            await cb.answer("Ошибка", show_alert=True)
            return
        coins = stars * rate
        payload = f"stars_{cb.from_user.id}_{stars}"
        title = f"{stars} звёзд"
        desc = f"Получишь {fmt(coins)} монет по курсу {rate} за звезду."

    try:
        await bot.send_invoice(
            chat_id=cb.message.chat.id,
            title=title,
            description=desc,
            payload=payload,
            provider_token="",  # для Stars не нужен
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars)],
        )
    except Exception as e:
        log.exception("send_invoice error: %s", e)
        await cb.message.answer("❌ Не удалось создать счёт. Попробуйте позже.")


@router.pre_checkout_query()
async def pre_checkout_handler(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    user_id = message.from_user.id
    if parts[0] == "vip":
        await DB.ensure_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
        await DB.set_vip(user_id, VIP_DURATION_DAYS)
        await message.answer(
            f"⭐ <b>VIP активирован!</b>\n\n"
            f"Срок: {VIP_DURATION_DAYS} дней.\n"
            f"Бонусы: x2 ежедневный бонус, без налогов в клане, скрытый режим в топе."
        )
    elif parts[0] == "stars":
        stars = int(parts[2]) if len(parts) > 2 else 0
        rate = await get_star_rate()
        coins = stars * rate
        await DB.ensure_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
        await DB.update_balance(user_id, coins)
        await message.answer(
            f"✅ <b>Платёж получен!</b>\n\n"
            f"⭐ Получено: {stars}\n"
            f"💰 Начислено: {fmt(coins)} монет\n"
            f"Курс: {rate} монет за звезду"
        )


@router.message(F.text == "🎁 Бонус")
async def menu_bonus(message: Message):
    if await check_banned(message):
        return
    await grant_bonus(message.chat.id, message.from_user)


@router.callback_query(F.data == "menu:bonus")
async def bonus_cb(cb: CallbackQuery):
    await cb.answer()
    await grant_bonus(cb.message.chat.id, cb.from_user)


async def grant_bonus(chat_id: int, user):
    u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")
    now = int(time.time())
    cooldown = BONUS_COOLDOWN_HOURS * 3600
    elapsed = now - u["bonus_last"]

    if elapsed < cooldown:
        remain = cooldown - elapsed
        text = (
            f"⏳ <b>Бонус ещё не готов!</b>\n\n"
            f"Следующий бонус через: <b>{format_timedelta(remain)}</b>"
        )
        await safe_send_photo(chat_id, IMG_BONUS, text)
        return

    amount = BONUS_AMOUNT
    vip_mult_text = ""
    if await DB.has_vip(user.id):
        amount *= VIP_BONUS_MULTIPLIER
        vip_mult_text = f"⭐ VIP-бонус x{VIP_BONUS_MULTIPLIER} применён!"

    await DB.update_balance(user.id, amount)
    # Обновляем bonus_last
    async with DB._lock:
        await DB._conn.execute("UPDATE users SET bonus_last=? WHERE user_id=?", (now, user.id))
        await DB._conn.commit()

    next_time = format_timedelta(cooldown)
    text = BONUS_TEXT.format(amount=amount, vip_bonus=vip_mult_text, next_time=next_time)
    await safe_send_photo(chat_id, IMG_BONUS, text)


@router.message(F.text == "👥 Рефералка")
async def menu_ref(message: Message):
    if await check_banned(message):
        return
    await send_ref(message.chat.id, message.from_user)


@router.callback_query(F.data == "menu:ref")
async def ref_cb(cb: CallbackQuery):
    await cb.answer()
    await send_ref(cb.message.chat.id, cb.from_user)


async def send_ref(chat_id: int, user):
    u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")
    try:
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"
    except Exception:
        link = f"https://t.me/bot?start=ref_{user.id}"

    # Считаем заработанное с рефералов
    earned = 0
    async with DB._lock:
        cur = await DB._conn.execute(
            "SELECT COALESCE(SUM(-result),0) as lost FROM history h "
            "JOIN users u ON u.user_id=h.user_id "
            "WHERE u.referrer_id=? AND h.result<0", (user.id,)
        )
        row = await cur.fetchone()
        if row:
            earned = int(row["lost"] * REF_PERCENT)

    text = REF_TEXT_TEMPLATE.format(
        percent=int(REF_PERCENT * 100),
        link=link,
        count=u["ref_count"],
        earned=earned,
    )
    await safe_send_photo(chat_id, IMG_REF, text)


@router.message(F.text == "🏆 Топ")
async def menu_top(message: Message):
    if await check_banned(message):
        return
    await send_top(message.chat.id)


@router.callback_query(F.data == "top:refresh")
async def top_refresh_cb(cb: CallbackQuery):
    await cb.answer("Обновлено")
    await send_top(cb.message.chat.id, edit=cb.message)


async def send_top(chat_id: int, edit: Optional[Message] = None):
    top = await DB.top_by_balance(10)
    lines = [TOP_TEXT_HEADER]
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = row["first_name"] or "Игрок"
        if row["username"]:
            name = f"@{row['username']}"
        vip = " ⭐" if row["vip_until"] > int(time.time()) else ""
        lines.append(f"{medal} <b>{name}</b>{vip} — {fmt(row['balance'])}")
    if not top:
        lines.append("<i>Пока пусто...</i>")
    text = "\n".join(lines)
    if edit:
        try:
            await edit.delete()
        except Exception:
            pass
    await safe_send_photo(chat_id, IMG_TOP, text, reply_markup=top_inline_kb())


@router.message(F.text == "📖 Как играть")
async def menu_how(message: Message):
    if await check_banned(message):
        return
    text = COMMANDS_TEXT
    await safe_send_photo(message.chat.id, IMG_HOW, text)


@router.message(F.text == "🆘 Поддержка")
async def menu_support(message: Message):
    if await check_banned(message):
        return
    await message.answer(
        "🆘 <b>ПОДДЕРЖКА</b>\n\n"
        "Выбери категорию обращения или напиши админу напрямую:",
        reply_markup=support_inline_kb(),
    )


@router.message(F.text == "💬 Чаты")
async def menu_chats(message: Message):
    if await check_banned(message):
        return
    await message.answer(
        "💬 <b>НАШИ ЧАТЫ</b>\n\n"
        "Присоединяйся к сообществу:",
        reply_markup=chats_inline_kb(),
    )


@router.callback_query(F.data.startswith("support:"))
async def support_cb(cb: CallbackQuery):
    action = cb.data.split(":")[1]
    if action == "earn":
        text = (
            "💰 <b>КАК ЗАРАБОТАТЬ МОНЕТЫ</b> 💰\n\n"
            "1️⃣ <b>Ежедневный бонус</b> — /bonus (раз в 24ч)\n"
            "2️⃣ <b>Рефералы</b> — 10% от проигрышей друзей\n"
            "3️⃣ <b>Игры</b> — /dice, /mines, /bj и другие\n"
            "4️⃣ <b>Дропы</b> — следи за чатом\n"
            "5️⃣ <b>Промокоды</b> — /promo КОД\n"
            "6️⃣ <b>Рулетка</b> — пиши ставки в чат\n\n"
            "⚠️ Не пытайся обмануть бота — бан навсегда."
        )
        await cb.message.answer(text)
    elif action == "bug":
        text = (
            "🐞 <b>НАШЁЛ ОШИБКУ?</b>\n\n"
            "Опиши проблему админу: @username_admin\n"
            "Укажи: что делал, что ожидал, что получил.\n"
            "Скриншот приветствуется!"
        )
        await cb.message.answer(text)
    elif action == "chats":
        await cb.message.answer(
            "💬 <b>НАШИ ЧАТЫ</b>",
            reply_markup=chats_inline_kb(),
        )
    await cb.answer()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(COMMANDS_TEXT, reply_markup=main_reply_kb())


@router.message(Command("support"))
async def cmd_support(message: Message):
    await message.answer(
        "🆘 <b>ПОДДЕРЖКА</b>\n\nВыбери категорию:",
        reply_markup=support_inline_kb(),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    u = message.from_user
    db_user = await DB.ensure_user(u.id, u.username or "", u.first_name or "")
    await send_profile(message.chat.id, db_user)


@router.message(Command("bonus"))
async def cmd_bonus(message: Message):
    await grant_bonus(message.chat.id, message.from_user)


@router.message(Command("ref"))
async def cmd_ref(message: Message):
    await send_ref(message.chat.id, message.from_user)


@router.message(Command("top"))
async def cmd_top(message: Message):
    await send_top(message.chat.id)


@router.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject):
    if await check_banned(message):
        return
    if not command.args:
        await message.answer("❌ Использование: <code>/promo КОД</code>")
        return
    code = command.args.strip().upper()
    await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    ok, amount, msg = await DB.use_promo(code, message.from_user.id)
    if ok:
        await DB.update_balance(message.from_user.id, amount)
        await message.answer(f"✅ <b>Промокод активирован!</b>\n\n💰 Начислено: <b>{fmt(amount)}</b> монет")
    else:
        await message.answer(f"❌ {msg}")


@router.callback_query(F.data == "menu:vip")
async def vip_cb(cb: CallbackQuery):
    await cb.answer()
    u = await DB.get_user(cb.from_user.id)
    if u and u["vip_until"] > int(time.time()):
        days_left = (u["vip_until"] - int(time.time())) // 86400
        await cb.message.answer(
            f"⭐ <b>VIP активен</b>\n\n"
            f"Осталось дней: <b>{days_left}</b>\n\n"
            f"<b>Возможности:</b>\n"
            f"• x2 ежедневный бонус\n"
            f"• Без налогов в клане\n"
            f"• Скрытый режим в топе"
        )
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"⭐ Купить VIP за {VIP_PRICE_STARS} Stars", callback_data="donate:vip")
        await cb.message.answer(
            f"⭐ <b>VIP-СТАТУС</b>\n\n"
            f"<b>Цена:</b> {VIP_PRICE_STARS} ⭐ на {VIP_DURATION_DAYS} дней\n\n"
            f"<b>Что даёт:</b>\n"
            f"• x2 ежедневный бонус\n"
            f"• Без налогов в клане\n"
            f"• Скрытый режим в топе\n\n"
            f"Нажми кнопку ниже для покупки:",
            reply_markup=kb.as_markup(),
        )


@router.message(Command("vip"))
async def cmd_vip(message: Message):
    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["vip_until"] > int(time.time()):
        days_left = (u["vip_until"] - int(time.time())) // 86400
        await message.answer(f"⭐ VIP активен. Осталось: {days_left} дн.")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ Купить VIP за {VIP_PRICE_STARS} Stars", callback_data="donate:vip")
    await message.answer(
        f"⭐ <b>VIP-СТАТУС</b>\n\n"
        f"Цена: {VIP_PRICE_STARS} ⭐ на {VIP_DURATION_DAYS} дней\n\n"
        f"Бонусы: x2 бонус, без налогов, скрытый режим.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "menu:games")
async def games_cb(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(
        "🎮 <b>Выбери игру:</b>",
        reply_markup=games_inline_kb(),
    )


# =========================================================
# КОНЕЦ ЧАСТИ 2
# =========================================================

# =========================================================
# 6. ИГРЫ (Часть 2)
# =========================================================

# --- Вспомогательная логика для Dice-игр ---
DICE_GAMES = {
    "dice": ("🎲", "Кости"),
    "dart": ("🎯", "Дартс"),
    "basket": ("🏀", "Баскет"),
    "football": ("⚽", "Футбол"),
    "bowling": ("🎳", "Боулинг"),
}

async def play_dice_game(message: Message, game_key: str, bet: int, target_range: str):
    if bet < MIN_BET:
        await message.answer(f"❌ Мин. ставка: {MIN_BET}")
        return
    if bet > MAX_BET:
        await message.answer(f"❌ Макс. ставка: {fmt(MAX_BET)}")
        return

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["balance"] < bet:
        await message.answer("❌ Недостаточно средств!")
        return

    # Парсинг диапазона
    targets = set()
    try:
        if "-" in target_range:
            a, b = map(int, target_range.split("-"))
            targets = set(range(a, b + 1))
        else:
            targets = {int(target_range)}
    except Exception:
        await message.answer("❌ Неверный формат. Пример: 1-3 или 4")
        return

    if not targets or min(targets) < 1 or max(targets) > 6:
        await message.answer("❌ Диапазон должен быть от 1 до 6.")
        return

    # Списываем ставку
    await DB.update_balance(message.from_user.id, -bet)
    emoji, name = DICE_GAMES[game_key]

    # Бросаем
    msg = await message.answer_dice(emoji=emoji, emoji_reply_markup=None)
    await asyncio.sleep(3.5)
    value = msg.dice.value if msg.dice else 0

    # Расчет
    win = 0
    if value in targets:
        if len(targets) == 1:
            win = int(bet * 2.0)  # x2
        elif len(targets) == 2:
            win = int(bet * 1.5)  # x1.5
        elif len(targets) == 3:
            win = int(bet * 1.2)  # x1.2
        else:
            win = int(bet * 1.1)

    new_balance = await DB.update_balance(message.from_user.id, win)
    await DB.inc_stats(message.from_user.id, bet, win - bet)
    await DB.log_game(message.from_user.id, message.chat.id, game_key, bet, win - bet, new_balance)

    # Вывод
    if win > 0:
        text = (
            f"🎮 <b>{name}</b>\n\n"
            f"🎯 Твой прогноз: {target_range}\n"
            f"🎲 Выпало: <b>{value}</b>\n\n"
            f"🏆 <b>ПОБЕДА!</b> Выигрыш: <b>{fmt(win)}</b>\n"
            f"💰 Баланс: <b>{fmt(new_balance)}</b>"
        )
    else:
        text = (
            f"🎮 <b>{name}</b>\n\n"
            f"🎯 Твой прогноз: {target_range}\n"
            f"🎲 Выпало: <b>{value}</b>\n\n"
            f"💀 <b>ПРОИГРЫШ!</b>\n"
            f"💰 Баланс: <b>{fmt(new_balance)}</b>"
        )
    
    out_msg = await message.answer(text)
    asyncio.create_task(auto_delete(msg, 5))
    asyncio.create_task(auto_delete(out_msg, 10))


@router.message(Command("dice"))
async def cmd_dice(message: Message, command: CommandObject):
    if not command.args: 
        return await message.answer("❌ Использование: <code>/dice 500 1-3</code>")
    parts = command.args.split()
    if len(parts) < 2:
        return await message.answer("❌ Использование: <code>/dice 500 1-3</code>")
    bet = parse_bet_amount(parts[0])
    if not bet: return await message.answer("❌ Неверная сумма.")
    await play_dice_game(message, "dice", bet, parts[1])

@router.message(Command("dart"))
async def cmd_dart(message: Message, command: CommandObject):
    if not command.args: 
        return await message.answer("❌ Использование: <code>/dart 500 1-3</code>")
    parts = command.args.split()
    bet = parse_bet_amount(parts[0])
    await play_dice_game(message, "dart", bet, parts[1])

@router.message(Command("basket"))
async def cmd_basket(message: Message, command: CommandObject):
    if not command.args: 
        return await message.answer("❌ Использование: <code>/basket 500 1-3</code>")
    parts = command.args.split()
    bet = parse_bet_amount(parts[0])
    await play_dice_game(message, "basket", bet, parts[1])

@router.message(Command("football"))
async def cmd_football(message: Message, command: CommandObject):
    if not command.args: 
        return await message.answer("❌ Использование: <code>/football 500 1-3</code>")
    parts = command.args.split()
    bet = parse_bet_amount(parts[0])
    await play_dice_game(message, "football", bet, parts[1])

@router.message(Command("bowling"))
async def cmd_bowling(message: Message, command: CommandObject):
    if not command.args: 
        return await message.answer("❌ Использование: <code>/bowling 500 1-3</code>")
    parts = command.args.split()
    bet = parse_bet_amount(parts[0])
    await play_dice_game(message, "bowling", bet, parts[1])


# --- СЛОТЫ ---
@router.message(Command("slots"))
async def cmd_slots(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("❌ Использование: <code>/slots 500</code>")
    bet = parse_bet_amount(command.args)
    if not bet or bet < MIN_BET:
        return await message.answer(f"❌ Мин. ставка: {MIN_BET}")

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["balance"] < bet:
        return await message.answer("❌ Недостаточно средств!")

    await DB.update_balance(message.from_user.id, -bet)

    # Отправляем слот стикер
    msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)
    value = msg.dice.value if msg.dice else 0

    # Значения слота от 1 до 64.
    # 1 = BAR (три бара), 22 = 777, 43 = три семерки (джекпот), 64 = три вишенки.
    # Мы сделаем выплаты за самые частые и редкие комбинации, чтобы было интересно.
    win_mult = 0
    if value == 64:  # джекпот (3 семерки / вишенки)
        win_mult = 50
    elif value in (1, 22, 43):  # BAR и другие редкие
        win_mult = 20
    elif value in (2, 3, 4, 5):  # частые тройки
        win_mult = 5
    elif value in (6, 7, 8, 9, 10): # двойки
        win_mult = 2

    win = int(bet * win_mult) if win_mult > 0 else 0
    new_balance = await DB.update_balance(message.from_user.id, win)
    await DB.inc_stats(message.from_user.id, bet, win - bet)
    await DB.log_game(message.from_user.id, message.chat.id, "slots", bet, win - bet, new_balance)

    if win > 0:
        text = (
            f"🎰 <b>СЛОТЫ</b>\n\n"
            f"🎲 Выпало: <b>{value}</b>\n"
            f"🏆 <b>ВЫИГРЫШ!</b> x{win_mult} = <b>{fmt(win)}</b>\n"
            f"💰 Баланс: <b>{fmt(new_balance)}</b>"
        )
    else:
        text = (
            f"🎰 <b>СЛОТЫ</b>\n\n"
            f"🎲 Выпало: <b>{value}</b>\n"
            f"💀 <b>ПРОИГРЫШ</b>\n"
            f"💰 Баланс: <b>{fmt(new_balance)}</b>"
        )
    out = await message.answer(text)
    asyncio.create_task(auto_delete(msg, 5))
    asyncio.create_task(auto_delete(out, 10))


# --- МИНЫ ---
@router.message(Command("mines"))
async def cmd_mines(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("❌ Использование: <code>/mines 500 5</code>")
    parts = command.args.split()
    if len(parts) < 2:
        return await message.answer("❌ Использование: <code>/mines 500 5</code>")
    
    bet = parse_bet_amount(parts[0])
    try:
        mines_count = int(parts[1])
    except Exception:
        return await message.answer("❌ Неверное количество мин.")

    if not bet or bet < MIN_BET:
        return await message.answer(f"❌ Мин. ставка: {MIN_BET}")
    if mines_count < 1 or mines_count > 20:
        return await message.answer("❌ Мин: 1, Макс: 20")

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["balance"] < bet:
        return await message.answer("❌ Недостаточно средств!")

    await DB.update_balance(message.from_user.id, -bet)
    
    # Генерируем поле
    bombs = random.sample(range(25), mines_count)
    session_id = gen_id()
    
    mines_games[session_id] = {
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bet": bet,
        "mines": mines_count,
        "bombs": set(bombs),
        "opened": set(),
        "finished": False
    }

    text = (
        f"💣 <b>МИНЫ</b> (поле 5х5)\n\n"
        f"💰 Ставка: <b>{fmt(bet)}</b>\n"
        f"💣 Мин на поле: <b>{mines_count}</b>\n\n"
        f"Открывай клетки и вовремя забирай выигрыш!"
    )
    await message.answer(text, reply_markup=mines_inline_kb(session_id, []))

@router.callback_query(F.data.startswith("mines:open:"))
async def mines_open_cb(cb: CallbackQuery):
    _, _, session_id, idx = cb.data.split(":")
    idx = int(idx)
    game = mines_games.get(session_id)
    if not game or game["finished"] or game["user_id"] != cb.from_user.id:
        return await cb.answer("Игра недоступна.", show_alert=True)

    if idx in game["opened"]:
        return await cb.answer("Уже открыто.", show_alert=True)

    if idx in game["bombs"]:
        # Проигрыш
        game["finished"] = True
        await cb.message.edit_text(
            f"💥 <b>БУМ! Ты наступил на мину.</b>\n\n"
            f"💰 Ставка <b>{fmt(game['bet'])}</b> сгорела.\n"
            f"Мина была в клетке {idx+1}.",
            reply_markup=mines_inline_kb(session_id, list(game["opened"]), finished=True)
        )
        await cb.answer("Проигрыш!")
        del mines_games[session_id]
        await DB.inc_stats(cb.from_user.id, game["bet"], -game["bet"])
        return

    game["opened"].add(idx)
    opened_count = len(game["opened"])
    
    # Коэфф: (25 / (25 - mines)) ^ opened
    multiplier = (25 / (25 - game["mines"])) ** opened_count
    current_win = int(game["bet"] * multiplier)

    await cb.message.edit_text(
        f"💣 <b>МИНЫ</b>\n\n"
        f"💰 Ставка: <b>{fmt(game['bet'])}</b>\n"
        f"💎 Открыто: <b>{opened_count}</b>\n"
        f"📈 Текущий выигрыш: <b>{fmt(current_win)}</b> (x{multiplier:.2f})\n\n"
        f"Продолжай или забирай!",
        reply_markup=mines_inline_kb(session_id, list(game["opened"]))
    )
    await cb.answer("Безопасно!")

@router.callback_query(F.data.startswith("mines:cashout:"))
async def mines_cashout_cb(cb: CallbackQuery):
    session_id = cb.data.split(":")[2]
    game = mines_games.get(session_id)
    if not game or game["finished"] or game["user_id"] != cb.from_user.id:
        return await cb.answer("Игра недоступна.", show_alert=True)

    game["finished"] = True
    opened_count = len(game["opened"])
    
    if opened_count == 0:
        await cb.answer("Открой хотя бы одну клетку!", show_alert=True)
        game["finished"] = False
        return

    multiplier = (25 / (25 - game["mines"])) ** opened_count
    win = int(game["bet"] * multiplier)
    
    new_bal = await DB.update_balance(cb.from_user.id, win)
    await DB.inc_stats(cb.from_user.id, game["bet"], win - game["bet"])
    await DB.log_game(cb.from_user.id, cb.message.chat.id, "mines", game["bet"], win - game["bet"], new_bal)

    await cb.message.edit_text(
        f"💰 <b>Ты забрал выигрыш!</b>\n\n"
        f"🏆 Выигрыш: <b>{fmt(win)}</b> (x{multiplier:.2f})\n"
        f"💰 Баланс: <b>{fmt(new_bal)}</b>",
        reply_markup=mines_inline_kb(session_id, list(game["opened"]), finished=True)
    )
    await cb.answer("Забрано!")
    del mines_games[session_id]


# --- БЛЭКДЖЕК (БЖ) ---
DECK = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
SUITS = ["♠","♥","♦","♣"]

def draw_card():
    return random.choice(DECK), random.choice(SUITS)

def card_value(card: Tuple[str, str]) -> int:
    rank = card[0]
    if rank in ("J", "Q", "K"): return 10
    if rank == "A": return 11
    return int(rank)

def hand_value(hand: List[Tuple[str, str]]) -> int:
    val = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[0] == "A")
    while val > 21 and aces > 0:
        val -= 10
        aces -= 1
    return val

def format_hand(hand):
    return " ".join(f"{r}{s}" for r, s in hand)

@router.message(Command("bj"))
async def cmd_bj(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("❌ Использование: <code>/bj 500</code>")
    bet = parse_bet_amount(command.args)
    if not bet or bet < MIN_BET:
        return await message.answer(f"❌ Мин. ставка: {MIN_BET}")

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["balance"] < bet:
        return await message.answer("❌ Недостаточно средств!")

    await DB.update_balance(message.from_user.id, -bet)
    
    player_hand = [draw_card(), draw_card()]
    dealer_hand = [draw_card(), draw_card()]
    session_id = gen_id()

    blackjack_games[session_id] = {
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bet": bet,
        "player": player_hand,
        "dealer": dealer_hand,
        "finished": False
    }

    p_val = hand_value(player_hand)
    if p_val == 21:
        # Блэкджек сразу!
        win = int(bet * 2.5)
        new_bal = await DB.update_balance(message.from_user.id, win)
        await DB.inc_stats(message.from_user.id, bet, win - bet)
        await DB.log_game(message.from_user.id, message.chat.id, "bj", bet, win - bet, new_bal)
        await message.answer(
            f"🃏 <b>БЛЭКДЖЕК!</b>\n\n"
            f"👤 Твои карты: {format_hand(player_hand)} ({p_val})\n"
            f"🤖 Дилер: {format_hand(dealer_hand)}\n\n"
            f"🏆 Выигрыш: <b>{fmt(win)}</b>\n"
            f"💰 Баланс: <b>{fmt(new_bal)}</b>"
        )
        del blackjack_games[session_id]
        return

    await message.answer(
        f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
        f"💰 Ставка: <b>{fmt(bet)}</b>\n\n"
        f"👤 Твои карты: <b>{format_hand(player_hand)}</b> ({p_val})\n"
        f"🤖 Дилер: <b>{dealer_hand[0][0]}{dealer_hand[0][1]}</b> + 🂠\n\n"
        f"Набирай карты или остановись.",
        reply_markup=bj_inline_kb(session_id)
    )

@router.callback_query(F.data.startswith("bj:hit:"))
async def bj_hit_cb(cb: CallbackQuery):
    session_id = cb.data.split(":")[2]
    game = blackjack_games.get(session_id)
    if not game or game["finished"] or game["user_id"] != cb.from_user.id:
        return await cb.answer("Игра недоступна.", show_alert=True)

    game["player"].append(draw_card())
    p_val = hand_value(game["player"])

    if p_val > 21:
        # Перебор
        game["finished"] = True
        await cb.message.edit_text(
            f"🃏 <b>ПЕРЕБОР!</b>\n\n"
            f"👤 Твои карты: {format_hand(game['player'])} ({p_val})\n"
            f"🤖 Дилер: {format_hand(game['dealer'])}\n\n"
            f"💀 Ты проиграл <b>{fmt(game['bet'])}</b>.",
            reply_markup=None
        )
        await cb.answer("Перебор!")
        await DB.inc_stats(cb.from_user.id, game["bet"], -game["bet"])
        del blackjack_games[session_id]
        return

    await cb.message.edit_text(
        f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
        f"💰 Ставка: <b>{fmt(game['bet'])}</b>\n\n"
        f"👤 Твои карты: <b>{format_hand(game['player'])}</b> ({p_val})\n"
        f"🤖 Дилер: <b>{game['dealer'][0][0]}{game['dealer'][0][1]}</b> + 🂠\n\n"
        f"Ещё или хватит?",
        reply_markup=bj_inline_kb(session_id)
    )
    await cb.answer()

@router.callback_query(F.data.startswith("bj:stand:"))
async def bj_stand_cb(cb: CallbackQuery):
    session_id = cb.data.split(":")[2]
    game = blackjack_games.get(session_id)
    if not game or game["finished"] or game["user_id"] != cb.from_user.id:
        return await cb.answer("Игра недоступна.", show_alert=True)

    game["finished"] = True
    p_val = hand_value(game["player"])
    d_val = hand_value(game["dealer"])

    # Дилер берет до 17
    while d_val < 17:
        game["dealer"].append(draw_card())
        d_val = hand_value(game["dealer"])

    win = 0
    if d_val > 21 or p_val > d_val:
        win = int(game["bet"] * 2)
        result_text = "🏆 <b>ТЫ ВЫИГРАЛ!</b>"
    elif p_val == d_val:
        win = game["bet"]
        result_text = "🤝 <b>НИЧЬЯ</b> (возврат ставки)"
    else:
        result_text = "💀 <b>ТЫ ПРОИГРАЛ</b>"

    new_bal = await DB.update_balance(cb.from_user.id, win)
    await DB.inc_stats(cb.from_user.id, game["bet"], win - game["bet"])
    await DB.log_game(cb.from_user.id, cb.message.chat.id, "bj", game["bet"], win - game["bet"], new_bal)

    await cb.message.edit_text(
        f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
        f"👤 Твои карты: {format_hand(game['player'])} ({p_val})\n"
        f"🤖 Дилер: {format_hand(game['dealer'])} ({d_val})\n\n"
        f"{result_text}\n"
        f"💰 Баланс: <b>{fmt(new_bal)}</b>",
        reply_markup=None
    )
    await cb.answer()
    del blackjack_games[session_id]


# --- ДУЭЛИ ---
@router.message(Command("duel"))
async def cmd_duel(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("❌ Использование: <code>/duel 1000</code> (в ответ на сообщение) или <code>/duel 1000 @user</code>")
    
    parts = command.args.split()
    bet = parse_bet_amount(parts[0])
    if not bet or bet < DUEL_MIN_BET:
        return await message.answer(f"❌ Мин. ставка: {DUEL_MIN_BET}")
    
    # Определяем оппонента
    opponent_id = None
    opponent_name = ""
    
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == message.from_user.id:
            return await message.answer("❌ Нельзя дуэлиться с собой!")
        opponent_id = message.reply_to_message.from_user.id
        opponent_name = message.reply_to_message.from_user.first_name
    elif len(parts) > 1 and parts[1].startswith("@"):
        uname = parts[1][1:]
        async with DB._lock:
            cur = await DB._conn.execute("SELECT user_id, first_name FROM users WHERE username=?", (uname,))
            row = await cur.fetchone()
            if row:
                opponent_id = row["user_id"]
                opponent_name = row["first_name"]
            else:
                return await message.answer("❌ Пользователь не найден в базе бота.")
    else:
        return await message.answer("❌ Ответь на сообщение игрока или укажи @username.")

    if opponent_id == message.from_user.id:
        return await message.answer("❌ Нельзя дуэлиться с собой!")

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    opp = await DB.get_user(opponent_id)
    if not opp:
        return await message.answer("❌ Оппонент не зарегистрирован.")
    
    if u["balance"] < bet:
        return await message.answer("❌ У тебя недостаточно средств!")
    if opp["balance"] < bet:
        return await message.answer("❌ У оппонента недостаточно средств!")

    duel_id = gen_id()
    active_duels[duel_id] = {
        "challenger": message.from_user.id,
        "challenger_name": message.from_user.first_name,
        "opponent": opponent_id,
        "opponent_name": opponent_name,
        "bet": bet,
        "chat_id": message.chat.id,
        "status": "pending"
    }
    await DB.create_duel(duel_id, message.from_user.id, bet, message.chat.id)

    await message.answer(
        f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
        f"👤 <b>{message.from_user.first_name}</b> вызывает <b>{opponent_name}</b>\n"
        f"💰 Ставка: <b>{fmt(bet)}</b> монет\n\n"
        f"{opponent_name}, принимаешь вызов?",
        reply_markup=duel_inline_kb(duel_id)
    )

@router.callback_query(F.data.startswith("duel:accept:"))
async def duel_accept_cb(cb: CallbackQuery):
    duel_id = cb.data.split(":")[2]
    game = active_duels.get(duel_id)
    if not game:
        return await cb.answer("Дуэль не найдена.", show_alert=True)
    if game["status"] != "pending":
        return await cb.answer("Дуэль уже завершена.", show_alert=True)
    if cb.from_user.id != game["opponent"]:
        return await cb.answer("Это не твоя дуэль!", show_alert=True)

    # Проверяем балансы ещё раз
    u1 = await DB.get_user(game["challenger"])
    u2 = await DB.get_user(game["opponent"])
    if not u1 or not u2 or u1["balance"] < game["bet"] or u2["balance"] < game["bet"]:
        game["status"] = "cancelled"
        await cb.message.edit_text("❌ Дуэль отменена: у кого-то не хватило средств.")
        del active_duels[duel_id]
        return

    # Списываем
    await DB.update_balance(game["challenger"], -game["bet"])
    await DB.update_balance(game["opponent"], -game["bet"])

    # Случайный победитель
    winner_id = random.choice([game["challenger"], game["opponent"]])
    winner_name = game["challenger_name"] if winner_id == game["challenger"] else game["opponent_name"]
    prize = game["bet"] * 2

    await DB.update_balance(winner_id, prize)
    await DB.finish_duel(duel_id, game["opponent"], winner_id)
    
    # Статы
    await DB.inc_stats(game["challenger"], game["bet"], prize if winner_id == game["challenger"] else -game["bet"])
    await DB.inc_stats(game["opponent"], game["bet"], prize if winner_id == game["opponent"] else -game["bet"])
    await DB.log_game(winner_id, game["chat_id"], "duel", game["bet"], game["bet"], await DB.get_balance(winner_id))

    await cb.message.edit_text(
        f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
        f"👤 {game['challenger_name']} vs {game['opponent_name']}\n"
        f"💰 Ставка: <b>{fmt(game['bet'])}</b>\n\n"
        f"🎲 Победитель: <b>{winner_name}</b>!\n"
        f"🏆 Выигрыш: <b>{fmt(prize)}</b> монет",
        reply_markup=None
    )
    game["status"] = "done"
    del active_duels[duel_id]
    await cb.answer("Победа!")

@router.callback_query(F.data.startswith("duel:decline:"))
async def duel_decline_cb(cb: CallbackQuery):
    duel_id = cb.data.split(":")[2]
    game = active_duels.get(duel_id)
    if not game:
        return await cb.answer("Дуэль не найдена.", show_alert=True)
    if cb.from_user.id != game["opponent"]:
        return await cb.answer("Это не твоя дуэль!", show_alert=True)

    game["status"] = "declined"
    await cb.message.edit_text(
        f"⚔️ <b>Дуэль отклонена</b>\n\n"
        f"{game['opponent_name']} отказался от вызова.",
        reply_markup=None
    )
    del active_duels[duel_id]
    await cb.answer("Отклонено")


# --- ПОДАРКИ ---
@router.message(Command("gift"))
async def cmd_gift(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("❌ Использование: <code>/gift 500</code> в ответ на сообщение игрока.")
    
    bet = parse_bet_amount(command.args)
    if not bet or bet < 1:
        return await message.answer("❌ Неверная сумма.")

    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer("❌ Ответь на сообщение игрока, которому хочешь подарить монеты.")
    
    recipient = message.reply_to_message.from_user
    if recipient.id == message.from_user.id:
        return await message.answer("❌ Нельзя подарить самому себе.")
    if recipient.is_bot:
        return await message.answer("❌ Нельзя подарить боту.")

    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if u["balance"] < bet:
        return await message.answer("❌ Недостаточно средств!")

    await DB.ensure_user(recipient.id, recipient.username or "", recipient.first_name or "")
    
    # Налог на подарок (если у отправителя нет VIP)
    tax = 0
    if not await DB.has_vip(message.from_user.id):
        tax = int(bet * CLAN_TAX_PERCENT)  # используем тот же налог 5%

    final_amount = bet - tax
    
    await DB.update_balance(message.from_user.id, -bet)
    await DB.update_balance(recipient.id, final_amount)

    text = (
        f"🎁 <b>ПОДАРОК!</b>\n\n"
        f"👤 <b>{message.from_user.first_name}</b> подарил <b>{fmt(final_amount)}</b> монет "
        f"пользователю <b>{recipient.first_name}</b>!\n"
    )
    if tax > 0:
        text += f"\n💸 Налог: {fmt(tax)} (5%). Купи VIP, чтобы не платить налог!"
    
    await message.answer(text)


# =========================================================
# КОНЕЦ ЧАСТИ 3
# =========================================================

# =========================================================
# 7. РУЛЕТКА (Часть 3)
# =========================================================

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMBERS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}


def parse_roulette_bet(text: str) -> Optional[Tuple[str, Union[str, int, Tuple[int, int]], int]]:
    """
    Умный парсер ставок:
      - "к 1000" / "ч 500" / "з 250"     -> (color, color, amount)
      - "10-20 500" / "500 10-20"        -> (range, (10,20), amount)
      - "100 200 300"                    -> list of numbers treated as bets: return only first? 
                                             здесь возвращаем (numbers, list, sum) как отдельный случай
      - "7 500"                          -> exact number
    Возвращает (тип, значение, сумма) или None.
    """
    if not text:
        return None
    s = text.strip().lower().replace(",", ".")
    # Убираем лишние пробелы, оставляем одиночные
    s = re.sub(r"\s+", " ", s)

    # 1) Цвет + сумма: "к 1000", "ч 500", "з 250"
    m = re.fullmatch(r"(к|ч|з|red|black|zero)\s+(\d+(?:\.\d+)?к?)", s)
    if m:
        color_key = m.group(1)
        amt = parse_bet_amount(m.group(2))
        if amt:
            mapping = {"к": "red", "ч": "black", "з": "zero",
                       "red": "red", "black": "black", "zero": "zero"}
            return ("color", mapping[color_key], amt)

    # 2) Диапазон + сумма: "10-20 500" или "500 10-20"
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)\s+(\d+(?:\.\d+)?к?)", s)
    if m:
        a, b, amt = int(m.group(1)), int(m.group(2)), parse_bet_amount(m.group(3))
        if amt and 0 <= a <= b <= 36:
            return ("range", (a, b), amt)
    m = re.fullmatch(r"(\d+(?:\.\d+)?к?)\s+(\d+)\s*-\s*(\d+)", s)
    if m:
        amt = parse_bet_amount(m.group(1))
        a, b = int(m.group(2)), int(m.group(3))
        if amt and 0 <= a <= b <= 36:
            return ("range", (a, b), amt)

    # 3) Просто число + сумма: "7 500"
    m = re.fullmatch(r"(\d+)\s+(\d+(?:\.\d+)?к?)", s)
    if m:
        num = int(m.group(1))
        amt = parse_bet_amount(m.group(2))
        if amt and 0 <= num <= 36:
            return ("number", num, amt)

    # 4) Множественные ставки числами: "100 200 300" — трактуем как 3 равные ставки
    # Возвращаем особый тип
    tokens = s.split()
    if len(tokens) >= 2 and all(t.isdigit() for t in tokens):
        nums = [int(t) for t in tokens]
        if all(0 <= n <= 36 for n in nums):
            # ставка = минимальная сумма? нет — сумма не указана. Трактуем как сумму ставки на каждое число.
            # Но пользователь пишет "100 200 300" — это значит ставка на 100, 200 и 300? Слишком дорого.
            # По ТЗ: "100 200 300" — три отдельных ставки на числа 100, 200, 300.
            # Сумма ставки = фиксированная? Без указания суммы — берём минимальную ставку на каждое.
            # Упрощаем: интерпретируем как список ставок по MIN_BET на каждое число. Это спорно, но безопасно.
            return ("multi_numbers", nums, MIN_BET)

    return None


@router.message(F.text.regexp(r"^(к|ч|з)\s+\d+|^\d+\s*-\s*\d+\s+\d+|^\d+\s+\d+\s*-\s*\d+|^\d+\s+\d+(к)?$|^\d+\s+\d+\s+\d+$"), F.chat.type.in_({"group", "supergroup"}))
async def roulette_bet_listener(message: Message):
    """Ловит ставки в чате (в группах)."""
    if not message.text:
        return
    parsed = parse_roulette_bet(message.text)
    if not parsed:
        return
    bet_type, bet_value, amount = parsed
    if amount < MIN_BET:
        return

    chat_id = message.chat.id
    user = message.from_user
    u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")

    if u["balance"] < amount:
        return  # молча игнорим — не спамим

    # Забираем в pending (списываем сразу при "старт" или здесь?)
    # Решено: списываем при "старт", чтобы не морозить баланс.
    # Но проверять баланс — здесь.

    if chat_id not in active_roulettes:
        active_roulettes[chat_id] = {"bets": [], "spinning": False}

    # Форматируем отображение ставки
    if bet_type == "color":
        display = {"red": "🔴 красное", "black": "⚫ чёрное", "zero": "🟢 зеро"}[bet_value]
    elif bet_type == "range":
        a, b = bet_value
        display = f"диапазон {a}–{b}"
    elif bet_type == "number":
        display = f"число {bet_value}"
    else:  # multi_numbers
        display = "числа " + ", ".join(map(str, bet_value))

    # Проверим, не дублирует ли он (просто добавляем ещё одну ставку)
    active_roulettes[chat_id]["bets"].append({
        "user_id": user.id,
        "name": user.first_name,
        "type": bet_type,
        "value": bet_value,
        "amount": amount,
        "display": display,
    })

    await message.reply(
        f"✅ Ставка принята: <b>{user.first_name}</b> — <b>{fmt(amount)}</b> на <b>{display}</b>\n"
        f"<i>(напиши «старт», чтобы запустить рулетку)</i>"
    )


@router.message(F.text.lower() == "старт", F.chat.type.in_({"group", "supergroup"}))
async def roulette_start(message: Message):
    chat_id = message.chat.id
    data = active_roulettes.get(chat_id)
    if not data or not data["bets"]:
        return
    if data.get("spinning"):
        return await message.reply("🎰 Рулетка уже крутится!")

    data["spinning"] = True
    bets = data["bets"][:]

    await message.answer(
        f"🎰 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n"
        f"Всего ставок: <b>{len(bets)}</b>\n"
        f"Крутим..."
    )
    await asyncio.sleep(2.0)

    # Списываем у всех
    for b in bets:
        bal = await DB.get_balance(b["user_id"])
        if bal < b["amount"]:
            b["skipped"] = True
        else:
            await DB.update_balance(b["user_id"], -b["amount"])

    # Спин
    result_num = random.randint(0, 36)
    if result_num == 0:
        result_color = "zero"
        color_emoji = "🟢"
    elif result_num in RED_NUMBERS:
        result_color = "red"
        color_emoji = "🔴"
    else:
        result_color = "black"
        color_emoji = "⚫"

    # Расчет
    total_win = 0
    winners_lines = []
    for b in bets:
        if b.get("skipped"):
            continue
        win = 0
        hit = False
        if b["type"] == "color" and b["value"] == result_color:
            win = b["amount"] * (36 if result_color == "zero" else 2)
            hit = True
        elif b["type"] == "number" and b["value"] == result_num:
            win = b["amount"] * 36
            hit = True
        elif b["type"] == "range":
            a, bnd = b["value"]
            if a <= result_num <= bnd:
                win = int(b["amount"] * (36 / (bnd - a + 1)))
                hit = True
        elif b["type"] == "multi_numbers":
            # если число в списке, x36 на каждую
            for n in b["value"]:
                if n == result_num:
                    win += b["amount"] * 36
                    hit = True

        if hit and win > 0:
            await DB.update_balance(b["user_id"], win)
            total_win += win
            winners_lines.append(f"• {b['name']} +{fmt(win)}")
            await DB.log_roulette(chat_id, b["user_id"], b["amount"], b["display"], str(result_num), win - b["amount"])
        else:
            await DB.log_roulette(chat_id, b["user_id"], b["amount"], b["display"], str(result_num), -b["amount"])

    text = (
        f"🎰 <b>РУЛЕТКА — РЕЗУЛЬТАТ</b> 🎰\n\n"
        f"Выпало: {color_emoji} <b>{result_num}</b> ({result_color})\n\n"
    )
    if winners_lines:
        text += f"🏆 <b>Победители:</b>\n" + "\n".join(winners_lines) + f"\n\n💰 Всего выплачено: <b>{fmt(total_win)}</b>"
    else:
        text += "😔 <b>Победителей нет. Все ставки проиграли.</b>"

    await message.answer(text)
    active_roulettes[chat_id] = {"bets": [], "spinning": False}


@router.message(F.text.lower() == "лог", F.chat.type.in_({"group", "supergroup"}))
async def roulette_log(message: Message):
    rows = await DB.roulette_history(message.chat.id, 20)
    if not rows:
        return await message.reply("📜 Лог пуст.")
    lines = ["📜 <b>ПОСЛЕДНИЕ СТАВКИ</b>\n"]
    for r in rows:
        # находим имя
        u = await DB.get_user(r["user_id"])
        name = u["first_name"] if u else str(r["user_id"])
        sign = "🏆" if r["win"] > 0 else "💀"
        lines.append(
            f"{sign} <b>{name}</b> — {fmt(r['bet'])} на {r['choice']} → {r['result']} ({fmt(r['win'])})"
        )
    await message.reply("\n".join(lines))


# =========================================================
# 8. КЛАНЫ И VIP (Часть 4)
# =========================================================

@router.message(F.text == "🏰 Кланы")
async def menu_clans(message: Message):
    if await check_banned(message):
        return
    u = await DB.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    has_clan = bool(u["clan_id"])
    text = "🏰 <b>КЛАНЫ</b>\n\n"
    if has_clan:
        clan = await DB.get_clan(u["clan_id"])
        if clan:
            text += (
                f"🏰 <b>{clan['name']}</b> (lvl {clan['level']})\n"
                f"💰 Казна: <b>{fmt(clan['balance'])}</b>\n"
                f"👥 Участников: <b>{clan['members_count']}</b>\n"
                f"💸 Налог: <b>{clan['tax_percent']}%</b>\n"
            )
    else:
        text += (
            "Ты пока не в клане.\n\n"
            f"Создание клана стоит <b>{fmt(CLAN_CREATE_PRICE)}</b> монет.\n"
            "Или вступи в существующий."
        )
    await message.answer(text, reply_markup=clan_inline_kb(has_clan))


@router.callback_query(F.data.startswith("clan:"))
async def clan_cb(cb: CallbackQuery):
    action = cb.data.split(":")[1]
    user = cb.from_user

    if action == "create":
        await cb.message.answer(
            f"➕ <b>Создание клана</b>\n\n"
            f"Стоимость: <b>{fmt(CLAN_CREATE_PRICE)}</b>\n\n"
            f"Напиши: <code>/clan create ИмяКлана</code>\n"
            f"Имя от 3 до 20 символов, без пробелов."
        )
    elif action == "list":
        clans = await DB.list_clans(20)
        if not clans:
            await cb.message.answer("📋 Пока нет ни одного клана.")
        else:
            lines = ["📋 <b>ТОП КЛАНОВ</b>\n"]
            for i, c in enumerate(clans, 1):
                lines.append(f"{i}. <b>{c['name']}</b> — lvl {c['level']}, 👥 {c['members_count']}, 💰 {fmt(c['balance'])}")
            lines.append("\nВступить: <code>/clan join ИмяКлана</code>")
            await cb.message.answer("\n".join(lines))
    elif action == "info":
        u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")
        clan = await DB.get_clan(u["clan_id"]) if u["clan_id"] else None
        if not clan:
            return await cb.answer("Ты не в клане", show_alert=True)
        text = (
            f"🏰 <b>{clan['name']}</b>\n\n"
            f"👑 Владелец: <code>{clan['owner_id']}</code>\n"
            f"📈 Уровень: <b>{clan['level']}</b>\n"
            f"💰 Казна: <b>{fmt(clan['balance'])}</b>\n"
            f"👥 Участников: <b>{clan['members_count']}</b>\n"
            f"💸 Налог: <b>{clan['tax_percent']}%</b>"
        )
        await cb.message.answer(text)
    elif action == "deposit":
        await cb.message.answer(
            "💰 <b>Пополнение казны</b>\n\n"
            "Напиши: <code>/clan dep 1000</code>\n"
            "Сумма будет списана с твоего баланса."
        )
    elif action == "upgrade":
        await cb.message.answer(
            "⬆️ <b>Прокачка клана</b>\n\n"
            "Стоимость: <code>50 000 × текущий уровень</code>\n"
            "Пиши: <code>/clan up</code>"
        )
    elif action == "members":
        u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")
        if not u["clan_id"]:
            return await cb.answer("Ты не в клане", show_alert=True)
        members = await DB.clan_members_list(u["clan_id"])
        lines = [f"👥 <b>Участники клана</b>\n"]
        for m in members[:30]:
            mark = "👑" if m["user_id"] == (await DB.get_clan(u["clan_id"]))["owner_id"] else "👤"
            lines.append(f"{mark} {m['first_name']} — {fmt(m['balance'])}")
        await cb.message.answer("\n".join(lines))
    elif action == "leave":
        ok = await DB.leave_clan(user.id)
        if ok:
            await cb.message.answer("🚪 Ты покинул клан.")
        else:
            await cb.message.answer("❌ Ты не в клане.")

    await cb.answer()


@router.message(Command("clan"))
async def cmd_clan(message: Message, command: CommandObject):
    if await check_banned(message):
        return
    if not command.args:
        return await menu_clans(message)

    args = command.args.split()
    sub = args[0].lower()
    user = message.from_user
    u = await DB.ensure_user(user.id, user.username or "", user.first_name or "")

    if sub == "create":
        if len(args) < 2:
            return await message.answer("❌ <code>/clan create ИмяКлана</code>")
        name = args[1]
        if len(name) < 3 or len(name) > 20 or " " in name:
            return await message.answer("❌ Имя: 3-20 символов, без пробелов.")
        if u["clan_id"]:
            return await message.answer("❌ Ты уже в клане.")
        if u["balance"] < CLAN_CREATE_PRICE:
            return await message.answer(f"❌ Нужно {fmt(CLAN_CREATE_PRICE)} монет.")
        clan_id = await DB.create_clan(name, user.id)
        if not clan_id:
            return await message.answer("❌ Клан с таким именем уже существует.")
        await DB.update_balance(user.id, -CLAN_CREATE_PRICE)
        await message.answer(f"🏰 <b>Клан «{name}» создан!</b>\n💰 Списано: {fmt(CLAN_CREATE_PRICE)}")

    elif sub == "join":
        if len(args) < 2:
            return await message.answer("❌ <code>/clan join ИмяКлана</code>")
        if u["clan_id"]:
            return await message.answer("❌ Ты уже в клане.")
        clan = await DB.get_clan_by_name(args[1])
        if not clan:
            return await message.answer("❌ Клан не найден.")
        if u["balance"] < CLAN_JOIN_PRICE:
            return await message.answer(f"❌ Нужно {fmt(CLAN_JOIN_PRICE)} монет.")
        ok = await DB.join_clan(user.id, clan["clan_id"])
        if not ok:
            return await message.answer("❌ Не удалось вступить.")
        await DB.update_balance(user.id, -CLAN_JOIN_PRICE)
        await DB.clan_deposit(clan["clan_id"], CLAN_JOIN_PRICE)
        await message.answer(f"✅ Ты вступил в клан <b>{clan['name']}</b>!")

    elif sub == "info":
        await menu_clans(message)

    elif sub == "list":
        clans = await DB.list_clans(20)
        lines = ["📋 <b>ТОП КЛАНОВ</b>\n"]
        for i, c in enumerate(clans, 1):
            lines.append(f"{i}. <b>{c['name']}</b> — lvl {c['level']}, 👥 {c['members_count']}")
        await message.answer("\n".join(lines) if clans else "Пока нет кланов.")

    elif sub == "dep":
        if not u["clan_id"]:
            return await message.answer("❌ Ты не в клане.")
        if len(args) < 2:
            return await message.answer("❌ <code>/clan dep 1000</code>")
        amount = parse_bet_amount(args[1])
        if not amount or amount <= 0:
            return await message.answer("❌ Неверная сумма.")
        if u["balance"] < amount:
            return await message.answer("❌ Недостаточно средств.")
        await DB.update_balance(user.id, -amount)
        await DB.clan_deposit(u["clan_id"], amount)
        await message.answer(f"💰 Внесено в казну: <b>{fmt(amount)}</b>")

    elif sub == "up":
        if not u["clan_id"]:
            return await message.answer("❌ Ты не в клане.")
        clan = await DB.get_clan(u["clan_id"])
        if clan["owner_id"] != user.id:
            return await message.answer("❌ Только владелец может прокачивать.")
        ok = await DB.clan_upgrade(u["clan_id"])
        if not ok:
            cost = 50_000 * clan["level"]
            return await message.answer(f"❌ Недостаточно в казне. Нужно {fmt(cost)}")
        await message.answer("⬆️ Клан прокачан!")

    elif sub == "leave":
        ok = await DB.leave_clan(user.id)
        await message.answer("🚪 Покинул клан." if ok else "❌ Ты не в клане.")

    elif sub == "kick":
        if not u["clan_id"]:
            return await message.answer("❌ Ты не в клане.")
        clan = await DB.get_clan(u["clan_id"])
        if clan["owner_id"] != user.id:
            return await message.answer("❌ Только владелец может кикать.")
        target_id = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
        elif len(args) >= 2 and args[1].startswith("@"):
            uname = args[1][1:]
            async with DB._lock:
                cur = await DB._conn.execute("SELECT user_id FROM users WHERE username=?", (uname,))
                row = await cur.fetchone()
                if row: target_id = row["user_id"]
        if not target_id:
            return await message.answer("❌ Укажи пользователя (reply или @username).")
        if target_id == user.id:
            return await message.answer("❌ Нельзя кикнуть себя.")
        ok = await DB.leave_clan(target_id)
        await message.answer("✅ Кикнут." if ok else "❌ Не удалось кикнуть.")

    elif sub == "delete":
        if not u["clan_id"]:
            return await message.answer("❌ Ты не в клане.")
        clan = await DB.get_clan(u["clan_id"])
        if clan["owner_id"] != user.id:
            return await message.answer("❌ Только владелец может удалить.")
        await DB.delete_clan(u["clan_id"])
        await message.answer("🗑 Клан удалён.")

    else:
        await message.answer("❌ Неизвестная подкоманда. /clan — меню.")


# ---------- VIP ----------
# уже реализовано в ЧАСТИ 2 (callback donate:vip, /vip)


# =========================================================
# 9. ПРОМОКОДЫ
# =========================================================

@router.message(Command("addpromo"))
async def cmd_addpromo(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    if not command.args:
        return await message.answer("❌ <code>/addpromo КОД СУММА ИСПОЛЬЗОВАНИЙ</code>")
    parts = command.args.split()
    if len(parts) < 3:
        return await message.answer("❌ <code>/addpromo КОД СУММА ИСПОЛЬЗОВАНИЙ</code>")
    code = parts[0].upper()
    try:
        amount = int(parts[1])
        uses = int(parts[2])
    except Exception:
        return await message.answer("❌ Неверные числа.")
    await DB.create_promo(code, amount, uses, message.from_user.id)
    await DB.admin_log(message.from_user.id, "create_promo", 0, amount, f"code={code}, uses={uses}")
    await message.answer(f"✅ Промокод <code>{code}</code> создан.\n💰 {fmt(amount)} × {uses}")


# /promo уже реализован в ЧАСТИ 2


# =========================================================
# КОНЕЦ ЧАСТИ 4
# =========================================================

# =========================================================
# 10. НЕЙРО-АДМИН (Часть 5)
# =========================================================

def _extract_target_and_amount(message: Message, args_text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Универсальный парсер для админ-команд:
    - Если reply — цель = автор reply
    - Иначе цель = админ (self)
    - Сумма — из args_text (первое число)
    Возвращает (target_id, amount).
    """
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        target_id = message.from_user.id

    amount = None
    if args_text:
        token = args_text.strip().split()[0] if args_text.strip() else ""
        amount = parse_bet_amount(token) if token else None
    return target_id, amount


async def _resolve_target(message: Message, args_text: str) -> Optional[int]:
    """Если @username — ищем; если reply — автор; иначе — сам админ."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if args_text and args_text.strip().startswith("@"):
        uname = args_text.strip().split()[0][1:]
        async with DB._lock:
            cur = await DB._conn.execute("SELECT user_id FROM users WHERE username=?", (uname,))
            row = await cur.fetchone()
            return row["user_id"] if row else None
    return message.from_user.id


@router.message(F.text.regexp(r"^@\w+"))
async def neuro_admin_router(message: Message):
    """
    Роутер нейро-админа: обрабатывает любые сообщения, начинающиеся с @команда.
    Если это @username (без команды) — игнорируем.
    """
    if not message.text or not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    cmd = parts[0][1:].lower()  # без @
    rest = parts[1] if len(parts) > 1 else ""

    KNOWN_COMMANDS = {
        "выдать", "забрать", "обнулить", "дроп", "дроп_всем",
        "бан", "разбан", "юзер", "стата", "топ_баланс",
        "лог", "рассылка", "очистить", "бекап", "рестарт",
        "помощь", "выдать_vip", "разбан_всех", "мут", "анмут",
        "баланс", "все_балансы", "сброс_бд", "добавить_админа",
        "убрать_админа", "время", "пинг", "версия", "нагрузка",
        "сет_курс", "стоп_ивент", "запуск_ивента", "лог_админа",
        "топ_рефов", "кол_во", "удалить_юзера", "создать_промо",
        "список_промо", "удалить_промо", "выдать_клан", "удалить_клан",
        "инфо_клан", "топ_клан", "налог_клан", "проверить_юзера",
        "взять_баланс", "анонс", "закрепить", "рассылка_юзерам",
        "казино_откл", "казино_вкл", "очистить_историю",
    }
    if cmd not in KNOWN_COMMANDS:
        return  # возможно, это просто @username в тексте

    # Экономика
    if cmd == "выдать":
        target_id, amount = _extract_target_and_amount(message, rest)
        if not amount or amount <= 0:
            return await message.reply("❌ <code>@выдать 1000</code> (reply или себе)")
        await DB.ensure_user(target_id)
        new_bal = await DB.update_balance(target_id, amount)
        await DB.admin_log(message.from_user.id, "выдать", target_id, amount)
        await message.reply(f"✅ Выдано <b>{fmt(amount)}</b> пользователю <code>{target_id}</code>\n💰 Баланс: {fmt(new_bal)}")

    elif cmd == "забрать":
        target_id, amount = _extract_target_and_amount(message, rest)
        if not amount or amount <= 0:
            return await message.reply("❌ <code>@забрать 500</code>")
        new_bal = await DB.update_balance(target_id, -amount)
        await DB.admin_log(message.from_user.id, "забрать", target_id, amount)
        await message.reply(f"✅ Забрано <b>{fmt(amount)}</b>. Баланс: {fmt(new_bal)}")

    elif cmd == "обнулить":
        target_id = await _resolve_target(message, rest)
        await DB.set_balance(target_id, 0)
        await DB.admin_log(message.from_user.id, "обнулить", target_id)
        await message.reply(f"✅ Баланс пользователя <code>{target_id}</code> обнулён.")

    elif cmd == "дроп":
        amount = parse_bet_amount(rest.strip().split()[0]) if rest.strip() else None
        if not amount or amount <= 0:
            return await message.reply("❌ <code>@дроп 5000</code>")
        # Дроп в чат
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🎁 Забрать {fmt(amount)}", callback_data=f"drop_claim:{message.chat.id}:{amount}:{gen_id(8)}")
        sent = await message.answer(
            f"🎁 <b>ДРОП!</b>\n\n"
            f"Кто первый нажмёт — получит <b>{fmt(amount)}</b> монет!",
            reply_markup=kb.as_markup()
        )
        await DB.admin_log(message.from_user.id, "дроп", 0, amount, f"chat={message.chat.id}")

    elif cmd == "дроп_всем":
        amount = parse_bet_amount(rest.strip().split()[0]) if rest.strip() else None
        if not amount or amount <= 0:
            return await message.reply("❌ <code>@дроп_всем 1000</code>")
        users = await DB.all_users()
        cnt = 0
        for u in users:
            try:
                await DB.update_balance(u["user_id"], amount)
                cnt += 1
            except Exception:
                pass
        await DB.admin_log(message.from_user.id, "дроп_всем", 0, amount, f"users={cnt}")
        await message.reply(f"✅ Дропнуто {fmt(amount)} × {cnt} пользователей")

    elif cmd == "выдать_vip":
        target_id = await _resolve_target(message, rest)
        days = 30
        if rest.strip():
            try:
                days = int(rest.strip().split()[0])
            except Exception:
                pass
        await DB.set_vip(target_id, days)
        await DB.admin_log(message.from_user.id, "выдать_vip", target_id, days)
        await message.reply(f"⭐ VIP выдан пользователю <code>{target_id}</code> на {days} дней.")

    # Юзеры
    elif cmd == "бан":
        target_id = await _resolve_target(message, rest)
        await DB.ban_user(target_id, 1)
        await DB.admin_log(message.from_user.id, "бан", target_id)
        await message.reply(f"🚫 Пользователь <code>{target_id}</code> забанен.")

    elif cmd == "разбан":
        target_id = await _resolve_target(message, rest)
        await DB.ban_user(target_id, 0)
        await DB.admin_log(message.from_user.id, "разбан", target_id)
        await message.reply(f"✅ Пользователь <code>{target_id}</code> разбанен.")

    elif cmd == "разбан_всех":
        async with DB._lock:
            await DB._conn.execute("UPDATE users SET banned=0")
            await DB._conn.commit()
        await message.reply("✅ Все разбанены.")

    elif cmd == "юзер":
        target_id = await _resolve_target(message, rest)
        u = await DB.get_user(target_id)
        if not u:
            return await message.reply("❌ Не найден.")
        await message.reply(
            f"👤 <b>Инфо</b>\n\n"
            f"ID: <code>{u['user_id']}</code>\n"
            f"Имя: {u['first_name']}\n"
            f"Username: @{u['username'] or '—'}\n"
            f"💰 Баланс: {fmt(u['balance'])}\n"
            f"⭐ VIP: {'да' if u['vip_until']>time.time() else 'нет'}\n"
            f"🚫 Бан: {'да' if u['banned'] else 'нет'}\n"
            f"🎮 Игр: {u['total_games']}"
        )

    elif cmd == "стата":
        users = await DB.all_users()
        total_balance = sum(u["balance"] for u in users)
        total_games = sum(u["total_games"] for u in users)
        total_wagered = sum(u["total_wagered"] for u in users)
        banned = sum(1 for u in users if u["banned"])
        vip = sum(1 for u in users if u["vip_until"] > time.time())
        await message.reply(
            f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Всего юзеров: <b>{len(users)}</b>\n"
            f"🚫 Забанено: <b>{banned}</b>\n"
            f"⭐ VIP: <b>{vip}</b>\n"
            f"💰 Сумма балансов: <b>{fmt(total_balance)}</b>\n"
            f"🎮 Всего игр: <b>{total_games}</b>\n"
            f"💸 Оборот: <b>{fmt(total_wagered)}</b>"
        )

    elif cmd == "топ_баланс":
        top = await DB.top_by_balance(10)
        lines = ["🏆 <b>ТОП-10 БАЛАНСОВ</b>\n"]
        for i, row in enumerate(top, 1):
            lines.append(f"{i}. {row['first_name']} — {fmt(row['balance'])}")
        await message.reply("\n".join(lines))

    elif cmd == "топ_рефов":
        async with DB._lock:
            cur = await DB._conn.execute("SELECT * FROM users ORDER BY ref_count DESC LIMIT 10")
            rows = list(await cur.fetchall())
        lines = ["👥 <b>ТОП РЕФЕРАЛОВ</b>\n"]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. {r['first_name']} — {r['ref_count']}")
        await message.reply("\n".join(lines))

    elif cmd == "кол_во":
        users = await DB.all_users()
        await message.reply(f"👥 Юзеров: <b>{len(users)}</b>")

    # Логи
    elif cmd == "лог":
        limit = 20
        if rest.strip():
            try: limit = int(rest.strip().split()[0])
            except Exception: pass
        async with DB._lock:
            cur = await DB._conn.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = list(await cur.fetchall())
        lines = ["📜 <b>ЛОГ АДМИНОВ</b>\n"]
        for r in rows:
            lines.append(f"• {r['admin_id']} → {r['action']} (target={r['target_id']}, amount={r['amount']})")
        await message.reply("\n".join(lines) if rows else "Лог пуст.")

    elif cmd == "лог_админа":
        target = await _resolve_target(message, rest)
        async with DB._lock:
            cur = await DB._conn.execute("SELECT * FROM admin_logs WHERE admin_id=? ORDER BY id DESC LIMIT 30", (target,))
            rows = list(await cur.fetchall())
        lines = [f"📜 Лог админа <code>{target}</code>\n"]
        for r in rows:
            lines.append(f"• {r['action']} target={r['target_id']} amount={r['amount']} ({time.strftime('%d.%m %H:%M', time.localtime(r['ts']))})")
        await message.reply("\n".join(lines) if rows else "Пусто.")

    # Рассылки
    elif cmd == "рассылка" or cmd == "рассылка_юзерам":
        if not rest:
            return await message.reply("❌ <code>@рассылка текст</code>")
        users = await DB.all_users()
        ok, fail = 0, 0
        for u in users:
            try:
                await bot.send_message(u["user_id"], f"📢 <b>РАССЫЛКА</b>\n\n{rest}")
                ok += 1
            except Exception:
                fail += 1
        await message.reply(f"✅ Доставлено: {ok}\n❌ Ошибок: {fail}")

    elif cmd == "очистить":
        # Удаляем последние N сообщений бота в чате
        try:
            for i in range(message.message_id, max(1, message.message_id - 100), -1):
                try:
                    await bot.delete_message(message.chat.id, i)
                except Exception:
                    pass
        except Exception:
            pass
        await message.answer("🧹 Очищено.")

    elif cmd == "очистить_историю":
        async with DB._lock:
            await DB._conn.execute("DELETE FROM history")
            await DB._conn.execute("DELETE FROM roulette_logs")
            await DB._conn.commit()
        await message.reply("🗑 История игр и рулетки очищена.")

    elif cmd == "анонс":
        if not rest:
            return await message.reply("❌ <code>@анонс текст</code>")
        users = await DB.all_users()
        cnt = 0
        for u in users:
            try:
                await bot.send_message(u["user_id"], f"📣 <b>АНОНС</b>\n\n{rest}")
                cnt += 1
            except Exception:
                pass
        await message.reply(f"✅ Анонс доставлен: {cnt}")

    # Система
    elif cmd == "бекап":
        try:
            with open(DB_PATH, "rb") as f:
                data = f.read()
            file = types.BufferedInputFile(data, filename=f"backup_{int(time.time())}.db")
            await message.reply_document(file, caption="💾 Бекап базы данных")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")

    elif cmd == "рестарт":
        await message.reply("🔄 Рестарт...")
        await asyncio.sleep(1)
        os._exit(0)

    elif cmd == "помощь":
        await message.reply(ADMIN_HELP)

    elif cmd == "пинг":
        t = time.time()
        m = await message.reply("⏱")
        await m.edit_text(f"🏓 Pong! <b>{int((time.time()-t)*1000)} ms</b>")

    elif cmd == "версия":
        await message.reply(f"⚙️ <b>Casino Bot v1.0.0</b>\naiogram 3.x | Python {os.sys.version.split()[0]}")

    elif cmd == "время":
        await message.reply(f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

    elif cmd == "нагрузка":
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            await message.reply(f"📈 CPU: {cpu}%\n💾 RAM: {mem}%")
        except Exception:
            await message.reply("psutil не установлен")

    elif cmd == "сет_курс":
        if not rest.strip():
            return await message.reply("❌ <code>@сет_курс 120</code>")
        try:
            rate = int(rest.strip().split()[0])
        except Exception:
            return await message.reply("❌ Неверное число.")
        await DB.set_setting("star_rate", str(rate))
        await message.reply(f"✅ Курс звезды установлен: {rate}")

    # Казино on/off (глобально)
    elif cmd == "казино_откл":
        await DB.set_setting("casino_off", "1")
        await message.reply("🚫 Казино отключено.")

    elif cmd == "казино_вкл":
        await DB.set_setting("casino_off", "0")
        await message.reply("✅ Казино включено.")

    # Мут/анмут (заглушки — по ТЗ без мутов, но команды можно оставить)
    elif cmd == "мут":
        await message.reply("ℹ️ Муты не поддерживаются. Используй @бан.")

    elif cmd == "анмут":
        await message.reply("ℹ️ Муты не поддерживаются.")

    # Промокоды
    elif cmd == "создать_промо":
        parts = rest.split()
        if len(parts) < 3:
            return await message.reply("❌ <code>@создать_промо КОД СУММА ИСПОЛЬЗОВАНИЙ</code>")
        code = parts[0].upper()
        try:
            amount = int(parts[1]); uses = int(parts[2])
        except Exception:
            return await message.reply("❌ Неверные числа.")
        await DB.create_promo(code, amount, uses, message.from_user.id)
        await message.reply(f"✅ Промокод <code>{code}</code> создан.")

    elif cmd == "список_промо":
        async with DB._lock:
            cur = await DB._conn.execute("SELECT * FROM promocodes ORDER BY created_at DESC LIMIT 30")
            rows = list(await cur.fetchall())
        lines = ["🎁 <b>Промокоды</b>\n"]
        for r in rows:
            lines.append(f"• <code>{r['code']}</code> — {fmt(r['amount'])} × {r['uses_left']}")
        await message.reply("\n".join(lines) if rows else "Пусто.")

    elif cmd == "удалить_промо":
        if not rest.strip():
            return await message.reply("❌ <code>@удалить_промо КОД</code>")
        code = rest.strip().split()[0].upper()
        async with DB._lock:
            await DB._conn.execute("DELETE FROM promocodes WHERE code=?", (code,))
            await DB._conn.commit()
        await message.reply(f"🗑 Промокод <code>{code}</code> удалён.")

    # Клан-админ
    elif cmd == "выдать_клан":
        # reply на юзера + имя клана
        if not rest.strip():
            return await message.reply("❌ <code>@выдать_клан ИмяКлана</code> (reply)")
        target = await _resolve_target(message, "")
        name = rest.strip().split()[0]
        clan_id = await DB.create_clan(name, target)
        if clan_id:
            await message.reply(f"✅ Клан <b>{name}</b> выдан <code>{target}</code>")
        else:
            await message.reply("❌ Не удалось (имя занято).")

    elif cmd == "удалить_клан":
        if not rest.strip():
            return await message.reply("❌ <code>@удалить_клан ИмяКлана</code>")
        clan = await DB.get_clan_by_name(rest.strip().split()[0])
        if not clan:
            return await message.reply("❌ Клан не найден.")
        await DB.delete_clan(clan["clan_id"])
        await message.reply(f"🗑 Клан {clan['name']} удалён.")

    elif cmd == "инфо_клан":
        if not rest.strip():
            return await message.reply("❌ <code>@инфо_клан ИмяКлана</code>")
        clan = await DB.get_clan_by_name(rest.strip().split()[0])
        if not clan:
            return await message.reply("❌ Не найден.")
        await message.reply(
            f"🏰 <b>{clan['name']}</b>\n"
            f"👑 Owner: {clan['owner_id']}\n"
            f"📈 lvl: {clan['level']}\n"
            f"💰 Казна: {fmt(clan['balance'])}\n"
            f"👥 Members: {clan['members_count']}"
        )

    elif cmd == "топ_клан":
        clans = await DB.list_clans(10)
        lines = ["🏆 <b>ТОП КЛАНОВ</b>\n"]
        for i, c in enumerate(clans, 1):
            lines.append(f"{i}. <b>{c['name']}</b> — lvl {c['level']}, 💰 {fmt(c['balance'])}")
        await message.reply("\n".join(lines))

    elif cmd == "налог_клан":
        if not rest.strip():
            return await message.reply("❌ <code>@налог_клан 5</code> (reply в клан владельцу? проще по имени)")
        parts = rest.strip().split()
        if len(parts) < 2:
            return await message.reply("❌ <code>@налог_клан Имя 5</code>")
        clan = await DB.get_clan_by_name(parts[0])
        if not clan:
            return await message.reply("❌ Клан не найден.")
        try:
            tax = int(parts[1])
        except Exception:
            return await message.reply("❌ Неверный налог.")
        async with DB._lock:
            await DB._conn.execute("UPDATE clans SET tax_percent=? WHERE clan_id=?", (tax, clan["clan_id"]))
            await DB._conn.commit()
        await message.reply(f"✅ Налог клана {clan['name']}: {tax}%")

    # Прочее
    elif cmd == "удалить_юзера":
        target = await _resolve_target(message, rest)
        async with DB._lock:
            await DB._conn.execute("DELETE FROM users WHERE user_id=?", (target,))
            await DB._conn.commit()
        await message.reply(f"🗑 Юзер <code>{target}</code> удалён.")

    elif cmd == "проверить_юзера":
        target = await _resolve_target(message, rest)
        u = await DB.get_user(target)
        await message.reply(f"👤 {'✅ существует' if u else '❌ не найден'}")

    elif cmd == "все_балансы":
        users = await DB.all_users()
        total = sum(u["balance"] for u in users)
        await message.reply(f"💰 Сумма всех балансов: <b>{fmt(total)}</b>\n👥 Юзеров: {len(users)}")

    elif cmd == "сброс_бд":
        await message.reply("⚠️ Используй /dev null, авто-сброс запрещён.")

    elif cmd == "добавить_админа":
        target = await _resolve_target(message, rest)
        if target and target not in ADMIN_IDS:
            ADMIN_IDS.append(target)
            await message.reply(f"✅ <code>{target}</code> добавлен в админы (runtime).")

    elif cmd == "убрать_админа":
        target = await _resolve_target(message, rest)
        if target in ADMIN_IDS:
            ADMIN_IDS.remove(target)
            await message.reply(f"✅ <code>{target}</code> убран из админов (runtime).")

    elif cmd == "стоп_ивент":
        await message.reply("⏹ Ивенты остановлены.")

    elif cmd == "запуск_ивента":
        await message.reply("▶️ Ивенты запущены.")

    elif cmd == "закрепить":
        if message.reply_to_message:
            try:
                await message.reply_to_message.pin()
                await message.reply("📌 Закреплено.")
            except Exception as e:
                await message.reply(f"❌ {e}")

    else:
        await message.reply("❓ Неизвестная команда. См. @помощь")


# ---------- Обработчик дропа ----------
@router.callback_query(F.data.startswith("drop_claim:"))
async def drop_claim_cb(cb: CallbackQuery):
    try:
        _, chat_id_str, amount_str, token = cb.data.split(":")
        amount = int(amount_str)
    except Exception:
        return await cb.answer("Ошибка дропа", show_alert=True)

    # Проверка: уже кто-то забрал?
    key = f"drop_{token}"
    claimed = await DB.get_setting(key)
    if claimed:
        return await cb.answer("😔 Уже кто-то забрал!", show_alert=True)

    await DB.set_setting(key, str(cb.from_user.id))
    await DB.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    new_bal = await DB.update_balance(cb.from_user.id, amount)
    await DB.admin_log(0, "drop_claim", cb.from_user.id, amount, f"token={token}")

    await cb.message.edit_text(
        f"🎁 <b>ДРОП ЗАБРАН!</b>\n\n"
        f"👤 {cb.from_user.first_name} получил <b>{fmt(amount)}</b> монет!\n"
        f"💰 Баланс: {fmt(new_bal)}"
    )
    await cb.answer("🎉 Ты забрал дроп!")


# ---------- Reply-обработчик для админов ----------
@router.message(F.reply_to_message, F.from_user.id.in_(ADMIN_IDS))
async def admin_reply_commands(message: Message):
    """Админ отвечает на сообщение игрока и пишет команду без @."""
    if not message.text:
        return
    text = message.text.strip().lower()
    aliases = {
        "выдать": "выдать", "забрать": "забрать", "обнулить": "обнулить",
        "бан": "бан", "разбан": "разбан", "юзер": "юзер",
    }
    if text not in aliases:
        return
    # Перенаправляем в нейро-админ
    fake = message.model_copy(update={"text": f"@{aliases[text]}"})
    await neuro_admin_router(fake)


# =========================================================
# КОНЕЦ ЧАСТИ 5
# =========================================================

# =========================================================
# 11. АВТО-ИВЕНТЫ (Часть 6)
# =========================================================

AUTO_DROP_CHATS: List[int] = []  # сюда можно добавлять chat_id для авто-дропа


async def lucky_hour_task():
    """Счастливый час: x2 к выигрышам (флаг), длится 30 минут."""
    global lucky_hour_active, lucky_hour_end
    if lucky_hour_active:
        return
    lucky_hour_active = True
    lucky_hour_end = time.time() + 30 * 60
    # Рассылка
    users = await DB.all_users()
    text = (
        "🍀 <b>СЧАСТЛИВЫЙ ЧАС!</b> 🍀\n\n"
        "В течение 30 минут выигрыши в играх <b>удваиваются</b>!\n"
        "Успей сыграть!"
    )
    for u in users:
        try:
            await bot.send_message(u["user_id"], text)
        except Exception:
            pass
    log.info("Lucky Hour started!")
    await asyncio.sleep(30 * 60)
    lucky_hour_active = False
    log.info("Lucky Hour ended.")


async def auto_drop_task():
    """Авто-дроп в чат каждые 2 часа."""
    for chat_id in AUTO_DROP_CHATS:
        try:
            amount = random.randint(500, 5000)
            token = gen_id(8)
            kb = InlineKeyboardBuilder()
            kb.button(text=f"🎁 Забрать {fmt(amount)}", callback_data=f"drop_claim:{chat_id}:{amount}:{token}")
            await bot.send_message(
                chat_id,
                f"🎁 <b>АВТО-ДРОП!</b>\n\n"
                f"Кто первый нажмёт — получит <b>{fmt(amount)}</b> монет!",
                reply_markup=kb.as_markup(),
            )
        except Exception as e:
            log.warning("auto_drop chat %s error: %s", chat_id, e)


async def auto_roulette_task():
    """Авто-рулетка: раз в час запускает рулетку во всех чатах, где есть ставки."""
    for chat_id, data in list(active_roulettes.items()):
        if data.get("spinning") or not data.get("bets"):
            continue
        data["spinning"] = True
        bets = data["bets"][:]
        try:
            await bot.send_message(chat_id, f"🎰 <b>АВТО-РУЛЕТКА</b>\nКрутим {len(bets)} ставок...")
            await asyncio.sleep(2)
            for b in bets:
                bal = await DB.get_balance(b["user_id"])
                if bal < b["amount"]:
                    b["skipped"] = True
                else:
                    await DB.update_balance(b["user_id"], -b["amount"])

            result_num = random.randint(0, 36)
            if result_num == 0:
                result_color, emoji = "zero", "🟢"
            elif result_num in RED_NUMBERS:
                result_color, emoji = "red", "🔴"
            else:
                result_color, emoji = "black", "⚫"

            total_win = 0
            lines = []
            for b in bets:
                if b.get("skipped"):
                    continue
                win = 0
                if b["type"] == "color" and b["value"] == result_color:
                    win = b["amount"] * (36 if result_color == "zero" else 2)
                elif b["type"] == "number" and b["value"] == result_num:
                    win = b["amount"] * 36
                elif b["type"] == "range":
                    a, bb = b["value"]
                    if a <= result_num <= bb:
                        win = int(b["amount"] * (36 / (bb - a + 1)))
                elif b["type"] == "multi_numbers" and result_num in b["value"]:
                    win = b["amount"] * 36

                if win > 0:
                    await DB.update_balance(b["user_id"], win)
                    total_win += win
                    lines.append(f"• {b['name']} +{fmt(win)}")

            text = f"🎰 <b>Результат:</b> {emoji} <b>{result_num}</b>\n\n"
            if lines:
                text += "🏆 <b>Победители:</b>\n" + "\n".join(lines)
            else:
                text += "😔 Победителей нет."
            await bot.send_message(chat_id, text)
        except Exception as e:
            log.warning("auto_roulette error: %s", e)
        finally:
            active_roulettes[chat_id] = {"bets": [], "spinning": False}


async def refresh_star_rate_task():
    await refresh_star_rate()


def setup_scheduler():
    scheduler.add_job(refresh_star_rate_task, IntervalTrigger(hours=3), id="star_rate")
    scheduler.add_job(lucky_hour_task, IntervalTrigger(hours=6), id="lucky_hour")
    scheduler.add_job(auto_drop_task, IntervalTrigger(hours=2), id="auto_drop")
    scheduler.add_job(auto_roulette_task, IntervalTrigger(hours=1), id="auto_roulette")


# =========================================================
# 12. ЗАПУСК (main)
# =========================================================

async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "time": int(time.time()),
        "users": len(await DB.all_users()) if DB._conn else 0,
    })


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Web server started on port %s", PORT)
    return runner


async def on_startup():
    await DB.init()
    setup_scheduler()
    scheduler.start()
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="profile", description="👤 Профиль"),
        BotCommand(command="bonus", description="🎁 Бонус"),
        BotCommand(command="top", description="🏆 Топ"),
        BotCommand(command="mines", description="💣 Мины"),
        BotCommand(command="bj", description="🃏 Блэкджек"),
        BotCommand(command="duel", description="⚔️ Дуэль"),
        BotCommand(command="clan", description="🏰 Кланы"),
        BotCommand(command="promo", description="🎟 Промокод"),
        BotCommand(command="help", description="📖 Помощь"),
    ])
    log.info("Bot started, admin_ids=%s", ADMIN_IDS)


async def on_shutdown():
    scheduler.shutdown(wait=False)
    await DB.close()
    await bot.session.close()


async def main():
    runner = await start_web_server()
    try:
        await on_startup()
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")