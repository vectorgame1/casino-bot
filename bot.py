# -*- coding: utf-8 -*-
"""
TOKENS | PRIVATE CLUB
Telegram Bot — монолитный файл bot.py
Python 3.13 / aiogram 3.x / aiosqlite / Pillow
Готов к деплою на Render
"""

import os
import io
import re
import sys
import json
import time
import math
import asyncio
import random
import logging
import sqlite3
import textwrap
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, List, Dict, Any, Tuple

# ---------- Pillow ----------
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageFilter,
    ImageOps,
)

# ---------- aiogram 3.x ----------
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import (
    ParseMode,
    ChatAction,
    ChatType,
    ContentType,
)
from aiogram.filters import (
    Command,
    CommandStart,
    CommandObject,
    StateFilter,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputFile,
    BufferedInputFile,
    FSInputFile,
    PreCheckoutQuery,
    LabeledPrice,
    User,
    Chat,
    PhotoSize,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    WebAppInfo,
)
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode, hitalic, hlink, hunderline

# ---------- aiosqlite ----------
import aiosqlite

# ---------- aiohttp (веб-сервер для Render) ----------
from aiohttp import web

# ---------- APScheduler ----------
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_OK = True
except Exception:  # noqa: BLE001
    APSCHEDULER_OK = False
    AsyncIOScheduler = None  # type: ignore
    CronTrigger = None  # type: ignore
    IntervalTrigger = None  # type: ignore


# =============================================================
# 1. ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
PORT = int(os.getenv("PORT", "8080") or "8080")
DB_PATH = os.getenv("DB_PATH", "tokens.db")

# Производные настройки
BOT_USERNAME_CACHE: Optional[str] = None  # заполняется при старте
ASSETS_DIR = os.getenv("ASSETS_DIR", "assets")

PROFILE_BG_PATH = os.path.join(ASSETS_DIR, "profile_bg.jpg")
NO_AVATAR_PATH = os.path.join(ASSETS_DIR, "no_avatar.png")
FONT_BOLD_PATH = os.path.join(ASSETS_DIR, "Montserrat-Bold.ttf")
FONT_REG_PATH = os.path.join(ASSETS_DIR, "Montserrat-Regular.ttf")

# Экономика
STAR_TO_TOKENS = 5000               # 1 ⭐ = 5000 TOKENS
DAILY_BONUS_BASE = 5000             # базовый ежедневный бонус
DAILY_BONUS_DOUBLE = 10000          # бонус с ссылкой в профиле
REFERRAL_REWARD = 1000              # награда за друга
REFERRAL_PERCENT = 0                # % с пополнений реферала (0%)

# Антиспам / антифрод
COOLDOWN_SEC = 3                    # глобальный кулдаун на действия
DICE_AUTODELETE_SEC = 15            # автоудаление стикерных игр

# Ограничения
MIN_BET = 100
MAX_BET = 10_000_000
MINES_GRID = 5                      # 5x5
MINES_DEFAULT_MINES = 5
MINES_MAX_MINES = 24
DUEL_MIN = 100
DUEL_MAX = 5_000_000
ROULETTE_MIN = 100
ROULETTE_MAX = 2_000_000

# Временные зоны / сезон
TZ = timezone.utc
SEASON_DURATION_DAYS = 7

# VIP
VIP_TIERS = {
    "none":   {"name": "—",        "emoji": "⚪", "limit_mult": 1.0},
    "silver": {"name": "Silver",   "emoji": "🥈", "limit_mult": 1.5},
    "gold":   {"name": "Gold",     "emoji": "🥇", "limit_mult": 2.0},
    "platinum": {"name": "Platinum","emoji": "💎","limit_mult": 3.0},
    "black":  {"name": "Black",    "emoji": "🖤", "limit_mult": 5.0},
}

# Ранги профиля (по капиталу)
PROFILE_RANKS = [
    (0,            "Новичок",      "🌱"),
    (10_000,       "Ученик",       "📘"),
    (50_000,       "Практик",      "🎯"),
    (200_000,      "Трейдер",      "📈"),
    (500_000,      "Инвестор",     "💼"),
    (1_500_000,    "Капиталист",   "🏦"),
    (5_000_000,    "Магнат",       "👑"),
    (20_000_000,   "Олигарх",      "💎"),
    (100_000_000,  "Легенда",      "🔥"),
]

# Ранги альянса (по кол-ву приглашённых)
ALLY_RANKS = [
    (0,    "Старт",        "◽"),
    (3,    "Партнёр",      "◾"),
    (10,   "Агент",        "🔹"),
    (25,   "Лидер",        "🔷"),
    (50,   "Посол",        "🟦"),
    (100,  "Магнат Сети",  "💠"),
    (250,  "Империя",      "🌐"),
    (500,  "Легенда Сети", "👑"),
]

# Турнирные награды (топ-10)
SEASON_REWARDS = [
    500_000,
    450_000,
    400_000,
    350_000,
    300_000,
    250_000,
    200_000,
    150_000,
    100_000,
    50_000,
]


# =============================================================
# 2. ЛОГГИРОВАНИЕ
# =============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tokens")
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


def log_exc(prefix: str = "") -> None:
    """Логирование текущего исключения."""
    log.error("%s\n%s", prefix or "Exception:", traceback.format_exc())


# =============================================================
# 3. УТИЛИТЫ ФОРМАТИРОВАНИЯ
# =============================================================

def fmt_num(n: Union[int, float]) -> str:
    """1234567 -> '1 234 567'"""
    try:
        n = int(round(float(n)))
    except Exception:  # noqa: BLE001
        return "0"
    return f"{n:,}".replace(",", " ")


def fmt_tokens(n: Union[int, float]) -> str:
    """Формат токенов с иконкой."""
    return f"{fmt_num(n)} TOKENS"


def fmt_mono(n: Union[int, float]) -> str:
    """Моноширинный формат (backticks) для чисел."""
    return f"`{fmt_num(n)}`"


def fmt_stars(n: Union[int, float]) -> str:
    return f"{fmt_num(n)} ⭐"


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M")


def now_utc() -> datetime:
    return datetime.now(tz=TZ)


def now_ts() -> int:
    return int(time.time())


def safe_username(user: Optional[User]) -> str:
    if not user:
        return "—"
    if user.username:
        return "@" + user.username
    return user.full_name


def safe_full_name(user: Optional[User]) -> str:
    if not user:
        return "Игрок"
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return name.strip() or "Игрок"


def clip_text(s: str, max_len: int = 32) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def get_profile_rank(capital: int) -> Tuple[str, str]:
    """Вернуть (имя ранга, эмодзи) по капиталу."""
    name, emoji = PROFILE_RANKS[0][1], PROFILE_RANKS[0][2]
    for threshold, n, e in PROFILE_RANKS:
        if capital >= threshold:
            name, emoji = n, e
        else:
            break
    return name, emoji


def get_ally_rank(count: int) -> Tuple[str, str]:
    name, emoji = ALLY_RANKS[0][1], ALLY_RANKS[0][2]
    for threshold, n, e in ALLY_RANKS:
        if count >= threshold:
            name, emoji = n, e
        else:
            break
    return name, emoji


def vip_info(tier: str) -> Dict[str, Any]:
    return VIP_TIERS.get(tier or "none", VIP_TIERS["none"])


# =============================================================
# 4. ГЛОБАЛЬНЫЕ ОБЪЕКТЫ
# =============================================================

bot: Bot = None  # type: ignore  # инициализируется в main()
dp: Dispatcher = None  # type: ignore
router = Router(name="main")
admin_router = Router(name="admin")

scheduler: Optional[Any] = None

# Кэш состояний: cooldown'ы, активные игры
COOLDOWN: Dict[int, float] = {}                    # uid -> last_ts
MINES_GAMES: Dict[int, Dict[str, Any]] = {}        # uid -> game
DUELS: Dict[str, Dict[str, Any]] = {}              # duel_id -> game
ROULETTE_GAMES: Dict[int, Dict[str, Any]] = {}     # chat_id -> roulette state
GAMES_DISABLED: bool = False                       # глобальный тумблер игр
STAR_RATE: int = STAR_TO_TOKENS                    # курс ⭐ -> TOKENS (изменяемый)

# Список стикерных игр
DICE_GAMES: Dict[str, Dict[str, Any]] = {
    "dice":    {"emoji": "🎲", "name": "Кости",    "mult": {1: -1, 6: 5, 5: 2, 4: 1.5, 3: 0, 2: -0.5}},
    "dart":    {"emoji": "🎯", "name": "Дартс",    "mult": {1: -1, 6: 5, 5: 2, 4: 1.5, 3: 0.5, 2: -0.5}},
    "basket":  {"emoji": "🏀", "name": "Баскет",   "mult": {1: -1, 5: 3, 4: 1.5, 3: 0.5, 2: -0.5}},
    "football": {"emoji": "⚽", "name": "Футбол",  "mult": {1: -1, 5: 3, 4: 1.5, 3: 0.5, 2: -0.5}},
    "bowling": {"emoji": "🎳", "name": "Боулинг",  "mult": {1: -1, 6: 5, 5: 2, 4: 1.5, 3: 0.5, 2: -0.5}},
    "bj":      {"emoji": "🎰", "name": "БЖ",       "mult": {1: -1, 64: 10, 43: 5, 22: 2, 11: 1.5, 3: -1}},
    "slots":   {"emoji": "🎰", "name": "Слоты",    "mult": {1: -1, 64: 10, 43: 5, 22: 2, 11: 1.5, 3: -1}},
}


# =============================================================
# 5. БАЗА ДАННЫХ
# =============================================================

class DB:
    """Обёртка над aiosqlite с WAL-режимом."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path, timeout=30.0)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA synchronous=NORMAL;")
        await self.conn.execute("PRAGMA foreign_keys=ON;")
        await self.conn.execute("PRAGMA busy_timeout=30000;")
        await self.conn.commit()
        log.info("DB connected: %s (WAL)", self.path)

    async def close(self) -> None:
        if self.conn:
            try:
                await self.conn.commit()
            except Exception:  # noqa: BLE001
                pass
            await self.conn.close()
            log.info("DB closed")

    # ----- низкоуровневые операции -----

    async def execute(self, sql: str, params: Tuple = ()) -> None:
        assert self.conn is not None
        async with self._lock:
            await self.conn.execute(sql, params)
            await self.conn.commit()

    async def executemany(self, sql: str, seq: List[Tuple]) -> None:
        assert self.conn is not None
        async with self._lock:
            await self.conn.executemany(sql, seq)
            await self.conn.commit()

    async def fetchone(self, sql: str, params: Tuple = ()) -> Optional[aiosqlite.Row]:
        assert self.conn is not None
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Tuple = ()) -> List[aiosqlite.Row]:
        assert self.conn is not None
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def fetchval(self, sql: str, params: Tuple = (), default: Any = None) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return default
        return row[0]

    # ----- транзакция -----

    async def transaction(self):
        """Асинхронный контекстный менеджер транзакции."""
        db = self

        class _Txn:
            async def __aenter__(self_inner):  # noqa: N805
                assert db.conn is not None
                await db._lock.acquire()
                await db.conn.execute("BEGIN IMMEDIATE;")
                return db.conn

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: N805
                assert db.conn is not None
                try:
                    if exc_type is None:
                        await db.conn.commit()
                    else:
                        await db.conn.rollback()
                finally:
                    db._lock.release()

        return _Txn()


db = DB(DB_PATH)


# =============================================================
# 6. СОЗДАНИЕ ТАБЛИЦ
# =============================================================

SCHEMA_SQL: List[str] = [
    # ----- Пользователи -----
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id         INTEGER PRIMARY KEY,
        username        TEXT,
        full_name       TEXT,
        balance         INTEGER NOT NULL DEFAULT 0,
        frozen          INTEGER NOT NULL DEFAULT 0,
        referrer_id     INTEGER,
        vip_tier        TEXT NOT NULL DEFAULT 'none',
        vip_until       INTEGER,
        banned          INTEGER NOT NULL DEFAULT 0,
        ban_reason      TEXT,
        daily_last      INTEGER,
        daily_streak    INTEGER NOT NULL DEFAULT 0,
        games_disabled  INTEGER NOT NULL DEFAULT 0,
        total_wagered   INTEGER NOT NULL DEFAULT 0,
        total_won       INTEGER NOT NULL DEFAULT 0,
        total_lost      INTEGER NOT NULL DEFAULT 0,
        created_at      INTEGER NOT NULL DEFAULT 0,
        updated_at      INTEGER NOT NULL DEFAULT 0
    )
    """,
    # ----- Журнал игр -----
    """
    CREATE TABLE IF NOT EXISTS game_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        game_type   TEXT NOT NULL,
        bet         INTEGER NOT NULL,
        win         INTEGER NOT NULL,
        delta       INTEGER NOT NULL,
        meta        TEXT,
        ts          INTEGER NOT NULL
    )
    """,
    # ----- Партнёры -----
    """
    CREATE TABLE IF NOT EXISTS partners (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id  INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        reward       INTEGER NOT NULL DEFAULT 0,
        created_at   INTEGER NOT NULL,
        UNIQUE(user_id)
    )
    """,
    # ----- Турниры (сезон) -----
    """
    CREATE TABLE IF NOT EXISTS tournaments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id   INTEGER NOT NULL,
        user_id     INTEGER NOT NULL,
        net_win     INTEGER NOT NULL DEFAULT 0,
        games       INTEGER NOT NULL DEFAULT 0,
        updated_at  INTEGER NOT NULL,
        UNIQUE(season_id, user_id)
    )
    """,
    # ----- Транзакции (пополнения/выплаты) -----
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        kind        TEXT NOT NULL,
        amount      INTEGER NOT NULL,
        stars       INTEGER NOT NULL DEFAULT 0,
        meta        TEXT,
        ts          INTEGER NOT NULL
    )
    """,
    # ----- Сезоны -----
    """
    CREATE TABLE IF NOT EXISTS seasons (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at  INTEGER NOT NULL,
        ends_at     INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'active',
        paid_out    INTEGER NOT NULL DEFAULT 0
    )
    """,
    # ----- Индексы -----
    "CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_game_log_ts ON game_log(ts)",
    "CREATE INDEX IF NOT EXISTS idx_partners_ref ON partners(referrer_id)",
    "CREATE INDEX IF NOT EXISTS idx_tour_season ON tournaments(season_id, net_win)",
    "CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, ts)",
]


async def init_db() -> None:
    """Полная инициализация схемы и seed-данных."""
    await db.connect()
    for sql in SCHEMA_SQL:
        await db.execute(sql)
    log.info("DB schema ready.")

    # Активный сезон
    active = await db.fetchone(
        "SELECT id, started_at, ends_at FROM seasons WHERE status='active' ORDER BY id DESC LIMIT 1"
    )
    if not active:
        now = now_ts()
        ends = now + SEASON_DURATION_DAYS * 86400
        await db.execute(
            "INSERT INTO seasons (started_at, ends_at, status) VALUES (?, ?, 'active')",
            (now, ends),
        )
        log.info("Season created: ends at %s", fmt_dt(datetime.fromtimestamp(ends, TZ)))
    else:
        # если сезон истёк, но не закрыт — отложим закрытие на scheduler
        if active["ends_at"] <= now_ts():
            log.warning("Season %s expired — will be finalized by scheduler.", active["id"])


async def get_active_season() -> Optional[aiosqlite.Row]:
    return await db.fetchone(
        "SELECT id, started_at, ends_at FROM seasons WHERE status='active' ORDER BY id DESC LIMIT 1"
    )


# =============================================================
# 7. ФУНКЦИИ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ
# =============================================================

async def ensure_user(user: User, referrer_id: Optional[int] = None) -> aiosqlite.Row:
    """Создать/обновить пользователя; вернуть строку."""
    if user is None or user.is_bot:
        raise ValueError("Invalid user for ensure_user")
    uid = user.id
    now = now_ts()
    username = user.username
    full_name = safe_full_name(user)

    row = await db.fetchone("SELECT * FROM users WHERE user_id=?", (uid,))
    if row is None:
        # Реферал — только если юзер новый и не сам себя
        ref = None
        if referrer_id and referrer_id != uid:
            ref_row = await db.fetchone("SELECT user_id FROM users WHERE user_id=?", (referrer_id,))
            if ref_row:
                ref = referrer_id
        await db.execute(
            """
            INSERT INTO users (user_id, username, full_name, balance, referrer_id, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (uid, username, full_name, ref, now, now),
        )
        if ref:
            await db.execute(
                "INSERT OR IGNORE INTO partners (referrer_id, user_id, reward, created_at) VALUES (?, ?, 0, ?)",
                (ref, uid, now),
            )
            # Награда рефереру
            await add_balance(ref, REFERRAL_REWARD, kind="referral", meta={"from": uid})
            try:
                await bot.send_message(
                    ref,
                    f"🤝 <b>Новый партнёр в Альянсе!</b>\n\n"
                    f"Вам начислено {fmt_mono(REFERRAL_REWARD)} TOKENS за приглашённого игрока.",
                )
            except Exception:  # noqa: BLE001
                pass
        row = await db.fetchone("SELECT * FROM users WHERE user_id=?", (uid,))
    else:
        # Обновим профиль
        if row["username"] != username or row["full_name"] != full_name:
            await db.execute(
                "UPDATE users SET username=?, full_name=?, updated_at=? WHERE user_id=?",
                (username, full_name, now, uid),
            )
            row = await db.fetchone("SELECT * FROM users WHERE user_id=?", (uid,))
    return row


async def get_user(uid: int) -> Optional[aiosqlite.Row]:
    return await db.fetchone("SELECT * FROM users WHERE user_id=?", (uid,))


async def get_balance(uid: int) -> int:
    v = await db.fetchval("SELECT balance FROM users WHERE user_id=?", (uid,), 0)
    return int(v or 0)


async def add_balance(
    uid: int,
    amount: int,
    kind: str = "credit",
    meta: Optional[Dict[str, Any]] = None,
) -> int:
    """Атомарно изменить баланс. Возвращает новый баланс."""
    if amount == 0:
        return await get_balance(uid)
    await db.execute(
        "UPDATE users SET balance = balance + ?, updated_at=? WHERE user_id=?",
        (amount, now_ts(), uid),
    )
    await db.execute(
        "INSERT INTO transactions (user_id, kind, amount, meta, ts) VALUES (?, ?, ?, ?, ?)",
        (uid, kind, amount, json.dumps(meta or {}, ensure_ascii=False), now_ts()),
    )
    return await get_balance(uid)


async def try_debit(uid: int, amount: int, kind: str = "bet", meta: Optional[Dict[str, Any]] = None) -> bool:
    """
    Атомарное списание с защитой от double-spend.
    Возвращает True, если списание прошло.
    """
    if amount <= 0:
        return False
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT balance FROM users WHERE user_id=? AND banned=0", (uid,)
        )
        row = await cur.fetchone()
        await cur.close()
        if not row or row[0] < amount:
            return False
        await conn.execute(
            "UPDATE users SET balance = balance - ?, total_wagered = total_wagered + ?, updated_at=? WHERE user_id=?",
            (amount, amount, now_ts(), uid),
        )
        await conn.execute(
            "INSERT INTO transactions (user_id, kind, amount, meta, ts) VALUES (?, ?, ?, ?, ?)",
            (uid, kind, -amount, json.dumps(meta or {}, ensure_ascii=False), now_ts()),
        )
    return True


async def credit_win(uid: int, amount: int, game: str, meta: Optional[Dict[str, Any]] = None) -> None:
    """Начислить выигрыш и записать статистику."""
    if amount <= 0:
        return
    await add_balance(uid, amount, kind=f"win_{game}", meta=meta)
    await db.execute(
        "UPDATE users SET total_won = total_won + ?, updated_at=? WHERE user_id=?",
        (amount, now_ts(), uid),
    )


async def log_game(uid: int, game_type: str, bet: int, win: int, meta: Optional[Dict[str, Any]] = None) -> None:
    delta = int(win) - int(bet)
    await db.execute(
        "INSERT INTO game_log (user_id, game_type, bet, win, delta, meta, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid, game_type, bet, win, delta, json.dumps(meta or {}, ensure_ascii=False), now_ts()),
    )
    # Обновим турнирную таблицу
    season = await get_active_season()
    if season:
        await db.execute(
            """
            INSERT INTO tournaments (season_id, user_id, net_win, games, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(season_id, user_id) DO UPDATE SET
                net_win = net_win + excluded.net_win,
                games = games + 1,
                updated_at = excluded.updated_at
            """,
            (season["id"], uid, delta, now_ts()),
        )


async def is_banned(uid: int) -> bool:
    v = await db.fetchval("SELECT banned FROM users WHERE user_id=?", (uid,), 0)
    return bool(v)


async def set_ban(uid: int, banned: bool, reason: str = "") -> None:
    await db.execute(
        "UPDATE users SET banned=?, ban_reason=?, updated_at=? WHERE user_id=?",
        (1 if banned else 0, reason if banned else None, now_ts(), uid),
    )


async def set_vip(uid: int, tier: str, until_ts: Optional[int] = None) -> None:
    await db.execute(
        "UPDATE users SET vip_tier=?, vip_until=?, updated_at=? WHERE user_id=?",
        (tier, until_ts, now_ts(), uid),
    )


async def get_referrer(uid: int) -> Optional[int]:
    v = await db.fetchval("SELECT referrer_id FROM users WHERE user_id=?", (uid,))
    return int(v) if v else None


async def count_partners(uid: int) -> int:
    v = await db.fetchval("SELECT COUNT(*) FROM partners WHERE referrer_id=?", (uid,), 0)
    return int(v or 0)


# =============================================================
# 8. КУЛДАУНЫ
# =============================================================

def check_cooldown(uid: int, sec: int = COOLDOWN_SEC) -> Tuple[bool, int]:
    """Вернуть (ok, осталось_сек)."""
    now = time.monotonic()
    last = COOLDOWN.get(uid, 0.0)
    delta = now - last
    if delta < sec:
        return False, int(math.ceil(sec - delta))
    COOLDOWN[uid] = now
    return True, 0


def clear_cooldown(uid: int) -> None:
    COOLDOWN.pop(uid, None)


# =============================================================
# 9. ИНИЦИАЛИЗАЦИЯ БОТА
# =============================================================

def build_bot() -> Bot:
    global bot
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения!")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return bot


def build_dispatcher() -> Dispatcher:
    global dp
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(router)
    return dp


async def setup_bot_commands() -> None:
    """Устанавливаем команды меню."""
    user_cmds = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="profile", description="👤 Личный кабинет"),
        BotCommand(command="daily", description="🎁 Ежедневник"),
        BotCommand(command="alliance", description="🤝 Альянс"),
        BotCommand(command="season", description="🏆 Сезон"),
        BotCommand(command="cashier", description="💎 Касса"),
        BotCommand(command="help", description="🆘 Консьерж"),
    ]
    try:
        await bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
    except Exception:  # noqa: BLE001
        log_exc("set_my_commands user")

    if ADMIN_ID:
        admin_cmds = user_cmds + [
            BotCommand(command="admin", description="🔐 Админ-пульт"),
        ]
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except Exception:  # noqa: BLE001
            log_exc("set_my_commands admin")


# =============================================================
# 10. ВЕБ-СЕРВЕР (заглушка для Render)
# =============================================================

async def health_handler(request: web.Request) -> web.Response:
    """Простой healthcheck."""
    try:
        ok = db.conn is not None
        count = await db.fetchval("SELECT COUNT(*) FROM users", (), 0) if ok else 0
        return web.json_response(
            {
                "status": "ok" if ok else "db_down",
                "service": "TOKENS | PRIVATE CLUB",
                "time": now_utc().isoformat(),
                "users": count,
            }
        )
    except Exception as e:  # noqa: BLE001
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def root_handler(request: web.Request) -> web.Response:
    return web.Response(
        text="TOKENS | PRIVATE CLUB — bot is running.",
        content_type="text/plain",
    )


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", root_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/healthz", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    log.info("Web server started on 0.0.0.0:%s", PORT)
    return runner


# =============================================================
# 11. ЗАГЛУШКИ (будут реализованы в следующих частях)
# =============================================================

# Эти функции будут полностью реализованы в Частях 2-6.
# Здесь — безопасные заглушки, чтобы файл был импортируемым.

async def post_init_hook() -> None:  # pragma: no cover
    """Будет расширено в Части 6 (scheduler + warm-up)."""
    global BOT_USERNAME_CACHE
    try:
        me = await bot.get_me()
        BOT_USERNAME_CACHE = me.username
        log.info("Bot @%s (id=%s) ready.", me.username, me.id)
    except Exception:  # noqa: BLE001
        log_exc("post_init: get_me")


def setup_scheduler_stub() -> None:  # pragma: no cover
    """Полноценный scheduler будет в Части 6."""
    global scheduler
    if not APSCHEDULER_OK:
        log.warning("APScheduler недоступен — автообновление сезона отключено.")
        return
    scheduler = AsyncIOScheduler(timezone=TZ)
    log.info("Scheduler (stub) initialized.")


# =============================================================
# 12. MAIN
# =============================================================

async def main() -> None:
    """Точка входа. Полная версия будет дополнена в Части 6."""
    log.info("=== TOKENS | PRIVATE CLUB : BOOT ===")
    log.info("PORT=%s DB_PATH=%s ADMIN_ID=%s", PORT, DB_PATH, ADMIN_ID)

    # 1) База
    await init_db()

    # 2) Бот / Диспетчер
    build_bot()
    build_dispatcher()

    # 3) Веб-сервер (Render)
    web_runner = await start_web_server()

    # 4) Scheduler (заглушка, полноценно — в Части 6)
    setup_scheduler_stub()

    # 5) Хук инициализации
    await post_init_hook()

    # 6) Меню команд
    await setup_bot_commands()

    # 7) Polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:  # noqa: BLE001
        log_exc("delete_webhook")

    log.info("=== START POLLING ===")
    try:
        # Обработчики будут подключены в Частях 2-6.
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("=== STOP POLLING ===")
        if scheduler:
            try:
                scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        try:
            await web_runner.cleanup()
        except Exception:  # noqa: BLE001
            pass
        await db.close()
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            pass

# =============================================================
# ЧАСТЬ 2: КЛАВИАТУРЫ, ПРОФИЛЬ, START, МЕНЮ, КОНСЬЕРЖ, ЕЖЕДНЕВНИК
# =============================================================

# =============================================================
# 13. REPLY-КЛАВИАТУРЫ
# =============================================================

def kb_main(user_id: int = 0, is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню (Reply)."""
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="🎮 Игровой Зал"),
        KeyboardButton(text="💎 Касса"),
    )
    b.row(
        KeyboardButton(text="🎁 Ежедневник"),
        KeyboardButton(text="🤝 Альянс"),
    )
    b.row(
        KeyboardButton(text="🏆 Сезон"),
        KeyboardButton(text="👑 Элита"),
    )
    b.row(
        KeyboardButton(text="👤 Личный Кабинет"),
    )
    b.row(
        KeyboardButton(text="🆘 Консьерж"),
    )
    if is_admin:
        b.row(KeyboardButton(text="🔐 Админ-пульт"))
    return b.as_markup(resize_keyboard=True, input_field_placeholder="Выберите действие…")


def kb_games() -> ReplyKeyboardMarkup:
    """Меню игрового зала."""
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="🎲 Кости"),
        KeyboardButton(text="🎯 Дартс"),
        KeyboardButton(text="🏀 Баскет"),
    )
    b.row(
        KeyboardButton(text="⚽ Футбол"),
        KeyboardButton(text="🎳 Боулинг"),
        KeyboardButton(text="🃏 БЖ"),
    )
    b.row(
        KeyboardButton(text="🎰 Слоты"),
        KeyboardButton(text="💣 Мины"),
        KeyboardButton(text="⚔️ Дуэль"),
    )
    b.row(
        KeyboardButton(text="🎡 Рулетка"),
    )
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True, input_field_placeholder="Выберите игру…")


def kb_cashier() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text="⭐ Купить Stars-пакет"),
    )
    b.row(
        KeyboardButton(text="💳 Своя сумма"),
        KeyboardButton(text="📊 Курс"),
    )
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


def kb_back() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


def kb_cancel() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="❌ Отмена"))
    return b.as_markup(resize_keyboard=True)


# =============================================================
# 14. INLINE-КЛАВИАТУРЫ
# =============================================================

def ikb_profile(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⭐ Статус Премиум", callback_data="profile:premium")
    b.button(text="⚙️ Конфигурация", callback_data="profile:config")
    b.button(text="⬅️ Назад", callback_data="menu:back")
    b.adjust(1, 1, 1)
    return b.as_markup()


def ikb_profile_config() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎁 Ежедневник", callback_data="go:daily")
    b.button(text="🤝 Альянс", callback_data="go:alliance")
    b.button(text="🏆 Сезон", callback_data="go:season")
    b.button(text="💳 История транзакций", callback_data="profile:history")
    b.button(text="⬅️ Назад", callback_data="profile:back")
    b.adjust(1, 1, 1, 1, 1)
    return b.as_markup()


def ikb_premium() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key in ("silver", "gold", "platinum", "black"):
        info = VIP_TIERS[key]
        b.button(text=f"{info['emoji']} {info['name']}", callback_data=f"premium:buy:{key}")
    b.button(text="⬅️ Назад", callback_data="profile:back")
    b.adjust(2, 2, 1)
    return b.as_markup()


def ikb_back_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ В меню", callback_data="menu:back")
    return b.as_markup()


def ikb_cashier() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    packs = [
        (10, 0), (50, 2), (100, 5), (250, 10), (500, 15), (1000, 20), (2500, 25),
    ]
    for stars, bonus in packs:
        tokens = stars * STAR_RATE * (100 + bonus) // 100
        label = f"{stars} ⭐ → {fmt_num(tokens)}" if bonus else f"{stars} ⭐"
        b.button(text=label, callback_data=f"cash:{stars}")
    b.button(text="✏️ Своя сумма", callback_data="cash:custom")
    b.button(text="📊 Курс", callback_data="cash:rate")
    b.button(text="⬅️ Назад", callback_data="menu:back")
    b.adjust(2, 2, 2, 1, 1, 1)
    return b.as_markup()


def ikb_alliance(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📈 Ранги Альянса", callback_data="ally:ranks")
    b.button(text="🔗 Моя ссылка", callback_data="ally:link")
    b.button(text="⬅️ Назад", callback_data="menu:back")
    b.adjust(1, 1, 1)
    return b.as_markup()


def ikb_daily() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎁 Активировать", callback_data="daily:activate")
    b.button(text="❓ Как получить x2", callback_data="daily:how")
    b.button(text="⬅️ Назад", callback_data="menu:back")
    b.adjust(1, 1, 1)
    return b.as_markup()


def ikb_season() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить топ", callback_data="season:refresh")
    b.button(text="🎁 Мои награды", callback_data="season:my")
    b.button(text="⬅️ Назад", callback_data="menu:back")
    b.adjust(1, 1, 1)
    return b.as_markup()


def ikb_games() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎲 Кости", callback_data="game:dice")
    b.button(text="🎯 Дартс", callback_data="game:dart")
    b.button(text="🏀 Баскет", callback_data="game:basket")
    b.button(text="⚽ Футбол", callback_data="game:football")
    b.button(text="🎳 Боулинг", callback_data="game:bowling")
    b.button(text="🃏 БЖ", callback_data="game:bj")
    b.button(text="🎰 Слоты", callback_data="game:slots")
    b.button(text="💣 Мины", callback_data="game:mines")
    b.button(text="⚔️ Дуэль", callback_data="game:duel")
    b.button(text="🎡 Рулетка", callback_data="game:roulette")
    b.button(text="⬅️ В меню", callback_data="menu:back")
    b.adjust(3, 3, 3, 1, 1)
    return b.as_markup()


def ikb_bet_choice(game: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for amt in (100, 500, 1000, 5000, 10000):
        b.button(text=f"{fmt_num(amt)}", callback_data=f"bet:{game}:{amt}")
    b.button(text="✏️ Своя ставка", callback_data=f"bet:{game}:custom")
    b.button(text="⬅️ Назад", callback_data="go:games")
    b.adjust(5, 1, 1)
    return b.as_markup()


def ikb_duel_accept(duel_id: str, bet: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Принять ({fmt_num(bet)})", callback_data=f"duel:accept:{duel_id}")
    b.button(text="❌ Отклонить", callback_data=f"duel:decline:{duel_id}")
    b.adjust(1, 1)
    return b.as_markup()


def ikb_duel_choice(duel_id: str) -> InlineKeyboardMarkup:
    """Для автора дуэли — отменить."""
    b = InlineKeyboardBuilder()
    b.button(text="🚫 Отменить дуэль", callback_data=f"duel:cancel:{duel_id}")
    return b.as_markup()


def ikb_mines(mines: int, opened: set, cashout_value: int) -> InlineKeyboardMarkup:
    """Поле 5x5. mines — количество мин, opened — множество открытых индексов."""
    b = InlineKeyboardBuilder()
    for i in range(25):
        if i in opened:
            b.button(text="💎", callback_data="mines:noop")
        else:
            b.button(text="⬜", callback_data=f"mines:open:{i}")
    b.button(text=f"💰 Забрать {fmt_num(cashout_value)}", callback_data="mines:cashout")
    # 5x5 сетка + 1 широкая кнопка
    b.adjust(*([5] * 5), 1)
    return b.as_markup()


def ikb_mines_start() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💣 3 мины", callback_data="mines:start:3")
    b.button(text="💣 5 мин", callback_data="mines:start:5")
    b.button(text="💣 10 мин", callback_data="mines:start:10")
    b.button(text="⬅️ Назад", callback_data="go:games")
    b.adjust(3, 1)
    return b.as_markup()


def ikb_roulette_bet(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки рулетки для владельца ставки."""
    b = InlineKeyboardBuilder()
    b.button(text="💣 Старт", callback_data=f"rl:start:{chat_id}")
    b.button(text="🔄 Отменить", callback_data=f"rl:cancel:{chat_id}")
    b.adjust(2)
    return b.as_markup()


def ikb_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data="adm:stats")
    b.button(text="📢 Рассылка", callback_data="adm:broadcast")
    b.button(text="💾 Бекап", callback_data="adm:backup")
    b.button(text="🔄 Рестарт", callback_data="adm:restart")
    b.button(text="⚙️ Курс ⭐", callback_data="adm:rate")
    b.button(text="💥 Глобальный дроп", callback_data="adm:gdrop")
    b.button(text="🕹 Игры вкл/выкл", callback_data="adm:toggle_games")
    b.button(text="⬅️ В меню", callback_data="menu:back")
    b.adjust(2, 2, 2, 1, 1)
    return b.as_markup()


# =============================================================
# 15. ГЕНЕРАЦИЯ ПРОФИЛЯ (PILLOW)
# =============================================================

def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Пробует загрузить шрифт, иначе — дефолтный."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        try:
            # fallback — встроенный
            return ImageFont.load_default()
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()


def _make_circle_avatar(img: Image.Image, size: int) -> Image.Image:
    """Вырезает круг из картинки и возвращает RGBA-круг заданного размера."""
    img = img.convert("RGBA")
    # кроп до квадрата (по центру)
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


async def _download_avatar(user_id: int) -> Optional[bytes]:
    """Скачать аватар пользователя. None, если нет фото."""
    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
        if not photos or not photos.photos:
            return None
        best = photos.photos[0][-1]
        f = await bot.get_file(best.file_id)
        buf = io.BytesIO()
        await bot.download_file(f.file_path, destination=buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        log_exc("download avatar")
        return None


def _load_default_avatar() -> Image.Image:
    try:
        if os.path.exists(NO_AVATAR_PATH):
            return Image.open(NO_AVATAR_PATH).convert("RGBA")
    except Exception:  # noqa: BLE001
        log_exc("load no_avatar")
    # нарисуем простой кружок
    img = Image.new("RGBA", (200, 200), (30, 30, 40, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 200, 200), fill=(60, 60, 80, 255))
    d.ellipse((50, 40, 150, 140), fill=(200, 200, 220, 255))
    d.ellipse((50, 130, 150, 230), fill=(200, 200, 220, 255))
    return img


def _load_bg() -> Image.Image:
    """Фон профиля 1000x700. Если нет — градиент."""
    try:
        if os.path.exists(PROFILE_BG_PATH):
            bg = Image.open(PROFILE_BG_PATH).convert("RGB")
            return bg.resize((1000, 700), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        log_exc("load profile_bg")
    # красивый градиент
    bg = Image.new("RGB", (1000, 700), (10, 10, 25))
    d = ImageDraw.Draw(bg)
    for y in range(700):
        r = int(10 + (y / 700) * 40)
        g = int(10 + (y / 700) * 20)
        b = int(30 + (y / 700) * 80)
        d.line([(0, y), (1000, y)], fill=(r, g, b))
    # лёгкие "звёзды"
    for _ in range(200):
        x = random.randint(0, 999)
        y = random.randint(0, 699)
        v = random.randint(80, 200)
        d.point((x, y), fill=(v, v, v))
    return bg


async def generate_profile_card(user: User, row: aiosqlite.Row) -> bytes:
    """Сгенерировать PNG-карточку профиля и вернуть байты."""
    W, H = 1000, 700

    # 1) Фон
    bg = _load_bg()

    # 2) Аватар
    avatar_bytes = await _download_avatar(user.id)
    avatar_size = 150
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes))
            avatar = _make_circle_avatar(av, avatar_size)
        except Exception:  # noqa: BLE001
            log_exc("avatar decode")
            avatar = _make_circle_avatar(_load_default_avatar(), avatar_size)
    else:
        avatar = _make_circle_avatar(_load_default_avatar(), avatar_size)

    # Обводка аватара
    ring = Image.new("RGBA", (avatar_size + 8, avatar_size + 8), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, avatar_size + 8, avatar_size + 8), outline=(255, 215, 0, 255), width=5)
    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(ring, (50 - 4, 50 - 4))
    bg_rgba.alpha_composite(avatar, (50, 50))

    # 3) Текст
    draw = ImageDraw.Draw(bg_rgba)
    f_title = _get_font(FONT_BOLD_PATH, 34)
    f_name = _get_font(FONT_BOLD_PATH, 46)
    f_label = _get_font(FONT_REG_PATH, 24)
    f_value = _get_font(FONT_BOLD_PATH, 30)
    f_small = _get_font(FONT_REG_PATH, 20)

    # Имя + ранг
    name = clip_text(safe_full_name(user), 28)
    capital = int(row["balance"] or 0)
    rank_name, rank_emoji = get_profile_rank(capital)

    text_x = 230
    draw.text((text_x, 70), name, font=f_name, fill=(255, 255, 255, 255))
    draw.text((text_x, 130), f"ID: {user.id}", font=f_label, fill=(180, 180, 200, 255))
    draw.text((text_x, 165), f"{rank_emoji} {rank_name}", font=f_value, fill=(255, 215, 0, 255))

    # VIP
    vip = vip_info(row["vip_tier"])
    vip_until = row["vip_until"]
    vip_txt = f"{vip['emoji']} VIP: {vip['name']}"
    if vip_until and vip_until > now_ts():
        days_left = max(0, (vip_until - now_ts()) // 86400)
        vip_txt += f" ({days_left}д)"
    draw.text((text_x, 210), vip_txt, font=f_label, fill=(200, 220, 255, 255))

    # Капитал
    partners = await count_partners(user.id)
    draw.text((60, 270), "КАПИТАЛ", font=f_label, fill=(160, 160, 180, 255))
    draw.text((60, 305), f"{fmt_num(capital)} TOKENS", font=f_title, fill=(80, 255, 160, 255))

    # Партнёры
    draw.text((60, 380), "ПАРТНЁРОВ", font=f_label, fill=(160, 160, 180, 255))
    draw.text((60, 415), f"{fmt_num(partners)}", font=f_title, fill=(120, 200, 255, 255))

    # Статистика игр
    draw.text((60, 490), "СТАВОК", font=f_label, fill=(160, 160, 180, 255))
    draw.text((60, 525), f"{fmt_num(row['total_wagered'] or 0)}", font=f_value, fill=(255, 255, 255, 255))

    draw.text((400, 490), "ВЫИГРЫШ", font=f_label, fill=(160, 160, 180, 255))
    draw.text((400, 525), f"{fmt_num(row['total_won'] or 0)}", font=f_value, fill=(80, 255, 160, 255))

    draw.text((740, 490), "ПРОИГРЫШ", font=f_label, fill=(160, 160, 180, 255))
    draw.text((740, 525), f"{fmt_num(row['total_lost'] or 0)}", font=f_value, fill=(255, 120, 120, 255))

    # Нижняя подпись
    draw.text(
        (60, 640),
        "TOKENS | PRIVATE CLUB",
        font=f_small,
        fill=(120, 120, 140, 255),
    )
    draw.text(
        (W - 260, 640),
        now_utc().strftime("%d.%m.%Y"),
        font=f_small,
        fill=(120, 120, 140, 255),
    )

    # 4) Сохранить
    out = io.BytesIO()
    bg_rgba.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


# =============================================================
# 16. ХЕНДЛЕРЫ: /start, ГЛАВНОЕ МЕНЮ
# =============================================================

WELCOME_TEXT = (
    "💎 <b>TOKENS | PRIVATE CLUB</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Добро пожаловать в закрытый клуб.\n"
    "Здесь вращаются большие деньги — <b>TOKENS</b>.\n\n"
    "🎮 <b>Игровой зал</b> — 11 игр на выбор\n"
    "💎 <b>Касса</b> — пополнение через Stars\n"
    "🎁 <b>Ежедневник</b> — бонус каждый день\n"
    "🤝 <b>Альянс</b> — до <b>1 000 TOKENS</b> за друга\n"
    "🏆 <b>Сезон</b> — турнир с призовым фондом\n"
    "👑 <b>Элита</b> — VIP-статусы и лимиты\n\n"
    "Выберите раздел ниже 👇"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработка /start с deep-link рефералом."""
    await state.clear()
    user = message.from_user
    if not user:
        return

    # Deep-link: /start 123456
    args = message.text.split(maxsplit=1)
    referrer_id: Optional[int] = None
    if len(args) > 1 and args[1].strip().isdigit():
        rid = int(args[1].strip())
        if rid != user.id:
            referrer_id = rid

    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>\nВы заблокированы в клубе.")
        return

    row = await ensure_user(user, referrer_id=referrer_id)
    await message.answer(
        WELCOME_TEXT,
        reply_markup=kb_main(user.id, is_admin=(user.id == ADMIN_ID)),
    )

    if referrer_id:
        await message.answer(
            "🤝 <b>Вы пришли по приглашению.</b>\n"
            "Ваш партнёр уже получил награду.",
        )


@router.message(Command("help"))
@router.message(F.text == "🆘 Консьерж")
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = (
        "🆘 <b>Консьерж</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Если возникли вопросы — обратитесь в поддержку.\n\n"
        "📌 <b>Частые вопросы:</b>\n\n"
        "• <b>Как пополнить?</b> → 💎 Касса\n"
        "• <b>Как вывести?</b> → обратитесь к администратору\n"
        "• <b>Не пришёл бонус?</b> → 🎁 Ежедневник\n"
        "• <b>Как пригласить друга?</b> → 🤝 Альянс\n"
        "• <b>Как стать VIP?</b> → 👤 Личный Кабинет → Премиум\n\n"
        f"👤 <b>Поддержка:</b> @{(BOT_USERNAME_CACHE or 'support')}\n"
        "⏱ <i>Время ответа: до 24 часов</i>"
    )
    await message.answer(text, reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID))


@router.message(Command("profile"))
@router.message(F.text == "👤 Личный Кабинет")
async def cmd_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return

    row = await ensure_user(user)
    await message.answer_chat_action(ChatAction.UPLOAD_PHOTO)
    try:
        img_bytes = await generate_profile_card(user, row)
        photo = BufferedInputFile(img_bytes, filename=f"profile_{user.id}.png")
        await message.answer_photo(
            photo=photo,
            caption=(
                f"👤 <b>{hbold(safe_full_name(user))}</b>\n"
                f"🆔 <code>{user.id}</code>\n"
                f"💰 Баланс: {fmt_mono(row['balance'])}\n"
                f"🎖 Ранг: <b>{get_profile_rank(int(row['balance']))[0]}</b>"
            ),
            reply_markup=ikb_profile(user.id),
        )
    except Exception:  # noqa: BLE001
        log_exc("generate_profile_card")
        # Fallback: текстовый профиль
        await message.answer(
            f"👤 <b>{safe_full_name(user)}</b>\n"
            f"🆔 <code>{user.id}</code>\n"
            f"💰 Баланс: {fmt_mono(row['balance'])}\n"
            f"🎖 Ранг: <b>{get_profile_rank(int(row['balance']))[0]}</b>",
            reply_markup=ikb_profile(user.id),
        )


@router.callback_query(F.data == "menu:back")
async def cb_menu_back(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.clear()
    user = cb.from_user
    # Если пришли из фото — удалим
    try:
        if cb.message and cb.message.photo:
            await cb.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await bot.send_message(
        user.id,
        "🏠 <b>Главное меню</b>\nВыберите раздел:",
        reply_markup=kb_main(user.id, is_admin=(user.id == ADMIN_ID)),
    )


@router.callback_query(F.data == "profile:back")
async def cb_profile_back(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.clear()
    user = cb.from_user
    row = await ensure_user(user)
    try:
        img_bytes = await generate_profile_card(user, row)
        photo = BufferedInputFile(img_bytes, filename=f"profile_{user.id}.png")
        await cb.message.answer_photo(
            photo=photo,
            caption=f"👤 <b>{safe_full_name(user)}</b>\n🆔 <code>{user.id}</code>",
            reply_markup=ikb_profile(user.id),
        )
        try:
            await cb.message.delete()
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        log_exc("cb_profile_back")
        await cb.answer("Ошибка генерации профиля", show_alert=True)


@router.callback_query(F.data == "profile:config")
async def cb_profile_config(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    try:
        await cb.message.edit_caption(
            caption="⚙️ <b>Конфигурация профиля</b>\nВыберите раздел:",
            reply_markup=ikb_profile_config(),
        )
    except Exception:  # noqa: BLE001
        await cb.message.answer("⚙️ <b>Конфигурация</b>", reply_markup=ikb_profile_config())


@router.callback_query(F.data == "profile:history")
async def cb_profile_history(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    uid = cb.from_user.id
    rows = await db.fetchall(
        "SELECT kind, amount, ts FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (uid,),
    )
    if not rows:
        text = "📜 <b>История пуста.</b>\nСовершите первую операцию."
    else:
        lines = ["📜 <b>Последние 10 операций:</b>\n"]
        for r in rows:
            sign = "+" if r["amount"] > 0 else ""
            dt = datetime.fromtimestamp(r["ts"], TZ).strftime("%d.%m %H:%M")
            lines.append(f"• {dt} | {r['kind']} | <b>{sign}{fmt_num(r['amount'])}</b>")
        text = "\n".join(lines)
    try:
        await cb.message.edit_caption(caption=text, reply_markup=ikb_profile_config())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_profile_config())


@router.callback_query(F.data == "profile:premium")
async def cb_profile_premium(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    text = (
        "⭐ <b>Статус Премиум</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👑 VIP даёт повышенные лимиты ставок и приоритет.\n\n"
        "🥈 <b>Silver</b> — x1.5 лимит\n"
        "🥇 <b>Gold</b> — x2.0 лимит\n"
        "💎 <b>Platinum</b> — x3.0 лимит\n"
        "🖤 <b>Black</b> — x5.0 лимит\n\n"
        "<i>Оплата Stars. Срок — 30 дней.</i>"
    )
    try:
        await cb.message.edit_caption(caption=text, reply_markup=ikb_premium())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_premium())


@router.callback_query(F.data.startswith("premium:buy:"))
async def cb_premium_buy(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    tier = cb.data.split(":")[-1]
    if tier not in VIP_TIERS or tier == "none":
        await cb.answer("Недоступно", show_alert=True)
        return
    prices = {"silver": 100, "gold": 250, "platinum": 500, "black": 1000}
    stars = prices.get(tier, 100)
    info = VIP_TIERS[tier]
    title = f"{info['emoji']} VIP {info['name']} (30 дней)"
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title=title,
            description=f"Статус Премиум {info['name']} на 30 дней. Множитель лимита x{info['limit_mult']}",
            payload=f"vip:{tier}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars)],
        )
    except Exception:  # noqa: BLE001
        log_exc("premium invoice")
        await cb.answer("Ошибка выставления счёта", show_alert=True)


# =============================================================
# 17. ЕЖЕДНЕВНИК
# =============================================================

DAILY_TEXT = (
    "🎁 <b>Ежедневник</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Заходите каждый день и забирайте бонус.\n\n"
    "💵 Базовый бонус: <b>{base} TOKENS</b>\n"
    "🔥 Бонус с ссылкой в профиле: <b>{dbl} TOKENS</b>\n\n"
    "📌 <b>Как получить x2?</b>\n"
    "Откройте настройки профиля Telegram →\n"
    "в разделе «О себе» добавьте:\n\n"
    "👉 <code>@{bot} - Твой путь к успеху!</code>\n\n"
    "Сохраните — бонус x2.\n\n"
    "⏱ <i>Следующий бонус через 24 часа.</i>"
)


async def _check_profile_link(user_id: int) -> bool:
    """Проверяет, есть ли @bot в bio пользователя."""
    if not BOT_USERNAME_CACHE:
        return False
    try:
        chat = await bot.get_chat(user_id)
        bio = (chat.bio or "").lower()
        return ("@" + BOT_USERNAME_CACHE.lower()) in bio or BOT_USERNAME_CACHE.lower() in bio
    except Exception:  # noqa: BLE001
        log_exc("check_profile_link")
        return False


@router.message(Command("daily"))
@router.message(F.text == "🎁 Ежедневник")
async def cmd_daily(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    row = await ensure_user(user)
    last = row["daily_last"] or 0
    now = now_ts()
    can_claim = (now - last) >= 86400
    if can_claim:
        status = "✅ <b>Бонус доступен!</b>"
    else:
        left = 86400 - (now - last)
        h, m = left // 3600, (left % 3600) // 60
        status = f"⏳ <b>Доступен через {h}ч {m}м</b>"

    text = DAILY_TEXT.format(base=fmt_num(DAILY_BONUS_BASE), dbl=fmt_num(DAILY_BONUS_DOUBLE), bot=BOT_USERNAME_CACHE or "bot")
    text += f"\n\n{status}"
    await message.answer(text, reply_markup=ikb_daily())


@router.callback_query(F.data == "daily:how")
async def cb_daily_how(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    text = (
        "❓ <b>Как получить x2</b>\n\n"
        "1. Откройте профиль Telegram\n"
        "2. Перейдите в «О себе»\n"
        "3. Добавьте:\n\n"
        f"<code>@{BOT_USERNAME_CACHE or 'bot'} - Твой путь к успеху!</code>\n\n"
        "4. Сохраните изменения\n"
        "5. Вернитесь и нажмите «Активировать»"
    )
    try:
        await cb.message.edit_text(text, reply_markup=ikb_daily())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_daily())


@router.callback_query(F.data == "daily:activate")
async def cb_daily_activate(cb: CallbackQuery) -> None:
    user = cb.from_user
    ok, left = check_cooldown(user.id)
    if not ok:
        try:
            await cb.answer(f"⏳ Подождите {left} сек.", show_alert=False)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass

    row = await ensure_user(user)
    last = row["daily_last"] or 0
    now = now_ts()
    if (now - last) < 86400:
        left_sec = 86400 - (now - last)
        h, m = left_sec // 3600, (left_sec % 3600) // 60
        await cb.answer(f"⏳ Следующий бонус через {h}ч {m}м", show_alert=True)
        return

    await cb.message.answer("🔎 <i>Проверяем ваш профиль…</i>")
    has_link = await _check_profile_link(user.id)
    bonus = DAILY_BONUS_DOUBLE if has_link else DAILY_BONUS_BASE

    # Атомарно: проверяем last ещё раз, обновляем, начисляем
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT daily_last, daily_streak FROM users WHERE user_id=?", (user.id,))
        r = await cur.fetchone()
        await cur.close()
        if not r:
            await cb.answer("Ошибка", show_alert=True)
            return
        if (now - (r["daily_last"] or 0)) < 86400:
            await cb.answer("Уже получено", show_alert=True)
            return
        streak = (r["daily_streak"] or 0) + 1
        await conn.execute(
            "UPDATE users SET daily_last=?, daily_streak=?, balance=balance+?, updated_at=? WHERE user_id=?",
            (now, streak, bonus, now, user.id),
        )
        await conn.execute(
            "INSERT INTO transactions (user_id, kind, amount, meta, ts) VALUES (?, 'daily', ?, ?, ?)",
            (user.id, bonus, json.dumps({"x2": has_link, "streak": streak}), now),
        )

    if has_link:
        text = (
            f"🎉 <b>Бонус x2 получен!</b>\n\n"
            f"👏 Ссылка найдена в профиле.\n"
            f"💰 +{fmt_mono(bonus)} TOKENS\n"
            f"🔥 Стрик: <b>{streak}</b> дн."
        )
    else:
        text = (
            f"🎁 <b>Бонус получен!</b>\n\n"
            f"💰 +{fmt_mono(bonus)} TOKENS\n"
            f"🔥 Стрик: <b>{streak}</b> дн.\n\n"
            f"💡 Добавьте <code>@{BOT_USERNAME_CACHE or 'bot'} - Твой путь к успеху!</code>\n"
            f"в профиль — и получайте <b>в 2 раза больше</b>."
        )
    await cb.message.answer(text)
    await bot.send_message(
        user.id,
        "Хотите вернуться в меню?",
        reply_markup=kb_main(user.id, is_admin=(user.id == ADMIN_ID)),
    )


# =============================================================
# 18. УНИВЕРСАЛЬНЫЙ ПЕРЕХОД ПО "go:*"
# =============================================================

@router.callback_query(F.data.startswith("go:"))
async def cb_go(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.clear()
    target = cb.data.split(":", 1)[1]
    user = cb.from_user

    if target == "games":
        await bot.send_message(
            user.id,
            "🎮 <b>Игровой зал</b>\n"
            "Выберите игру кнопкой ниже или в reply-меню.",
            reply_markup=kb_games(),
        )
    elif target == "daily":
        await cmd_daily(cb.message, state)  # type: ignore[arg-type]
    elif target == "alliance":
        await _send_alliance(user.id)
    elif target == "season":
        await _send_season(user.id)
    elif target == "cashier":
        await _send_cashier(user.id)
    else:
        await bot.send_message(user.id, "🏠 В меню.", reply_markup=kb_main(user.id, user.id == ADMIN_ID))


# =============================================================
# 19. ЗАГЛУШКИ (реализуются в Частях 3-4)
# =============================================================

async def _send_alliance(uid: int) -> None:  # pragma: no cover
    """Будет расширено в Части 4."""
    await bot.send_message(uid, "🤝 <b>Альянс</b>\nЗагрузка…")


async def _send_season(uid: int) -> None:  # pragma: no cover
    """Будет реализовано в Части 5."""
    await bot.send_message(uid, "🏆 <b>Сезон</b>\nЗагрузка…")


async def _send_cashier(uid: int) -> None:  # pragma: no cover
    """Будет реализовано в Части 4."""
    await bot.send_message(uid, "💎 <b>Касса</b>\nЗагрузка…")

# =============================================================
# ЧАСТЬ 3: АЛЬЯНС, КАССА (STARS), ЭЛИТА (VIP)
# =============================================================

# =============================================================
# 20. FSM СОСТОЯНИЯ (КАССА)
# =============================================================

class CashierStates(StatesGroup):
    waiting_custom_stars = State()   # ввод своей суммы ⭐
    waiting_custom_amount = State()  # ввод суммы TOKENS (если захотим)


class AdminBroadcastStates(StatesGroup):
    waiting_text = State()


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()
    waiting_rate = State()
    waiting_reason = State()


# =============================================================
# 21. АЛЬЯНС (РЕФЕРАЛКА)
# =============================================================

def _ref_link(uid: int) -> str:
    return f"https://t.me/{BOT_USERNAME_CACHE or 'bot'}?start={uid}"


ALLY_TEXT_TEMPLATE = (
    "🤝 <b>Партнёрский Альянс</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Приглашайте друзей и получайте <b>{reward} TOKENS</b> за каждого.\n"
    "Процент с пополнений: <b>{percent}%</b>\n\n"
    "🔗 <b>Ваша ссылка:</b>\n"
    "<code>{link}</code>\n\n"
    "📊 <b>Статистика:</b>\n"
    "• Приглашено: <b>{count}</b>\n"
    "• Ранг: {rank_emoji} <b>{rank_name}</b>\n"
    "• Заработано: <b>{earned} TOKENS</b>\n\n"
    "💡 <i>Скопируйте ссылку и отправьте другу.</i>"
)


async def _send_alliance(uid: int) -> None:
    """Отправляет экран Альянса."""
    await ensure_user_by_id(uid)
    count = await count_partners(uid)
    rank_name, rank_emoji = get_ally_rank(count)
    earned = await db.fetchval(
        "SELECT COALESCE(SUM(reward),0) FROM partners WHERE referrer_id=?", (uid,), 0
    )
    text = ALLY_TEXT_TEMPLATE.format(
        reward=fmt_num(REFERRAL_REWARD),
        percent=REFERRAL_PERCENT,
        link=_ref_link(uid),
        count=fmt_num(count),
        rank_emoji=rank_emoji,
        rank_name=rank_name,
        earned=fmt_num(earned or 0),
    )
    await bot.send_message(uid, text, reply_markup=ikb_alliance(uid), disable_web_page_preview=True)


async def ensure_user_by_id(uid: int) -> None:
    """Если юзера нет в базе (например, старый id) — создать минимальную запись."""
    row = await db.fetchone("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if row is None:
        try:
            chat = await bot.get_chat(uid)
            username = chat.username
            full_name = chat.full_name or "Игрок"
        except Exception:  # noqa: BLE001
            username = None
            full_name = "Игрок"
        now = now_ts()
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (uid, username, full_name, now, now),
        )


@router.message(Command("alliance"))
@router.message(F.text == "🤝 Альянс")
async def cmd_alliance(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    await ensure_user(user)
    await _send_alliance(user.id)


@router.callback_query(F.data == "ally:ranks")
async def cb_ally_ranks(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    lines = ["📈 <b>Ранги Альянса</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
    for threshold, name, emoji in ALLY_RANKS:
        lines.append(f"{emoji} <b>{name}</b> — {fmt_num(threshold)} партнёров")
    lines.append("\n💡 <i>Чем выше ранг — тем больше бонусов.</i>")
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=ikb_alliance(cb.from_user.id), disable_web_page_preview=True)
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_alliance(cb.from_user.id), disable_web_page_preview=True)


@router.callback_query(F.data == "ally:link")
async def cb_ally_link(cb: CallbackQuery) -> None:
    try:
        await cb.answer("Ссылка скопирована в чат ниже", show_alert=False)
    except Exception:  # noqa: BLE001
        pass
    link = _ref_link(cb.from_user.id)
    await cb.message.answer(
        f"🔗 <b>Ваша партнёрская ссылка:</b>\n\n<code>{link}</code>\n\n"
        f"<i>Отправьте её другу — и получите {fmt_num(REFERRAL_REWARD)} TOKENS, "
        f"как только он запустит бота.</i>",
        disable_web_page_preview=True,
    )


# =============================================================
# 22. КАССА (STARS)
# =============================================================

# Пакеты Stars -> токены (коэффициенты из ТЗ)
CASH_PACKS: List[Tuple[int, int]] = [
    (10, 0),
    (50, 2),
    (100, 5),
    (250, 10),
    (500, 15),
    (1000, 20),
    (2500, 25),
]


def _pack_tokens(stars: int, bonus: int) -> int:
    base = stars * STAR_RATE
    return base + base * bonus // 100


CASHIER_TEXT = (
    "💎 <b>Касса</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Пополняйте баланс через Telegram Stars.\n"
    "Курс: <b>1 ⭐ = {rate} TOKENS</b>\n\n"
    "🎁 <b>Пакеты с бонусом:</b>\n"
    "• 50 ⭐ → +2%\n"
    "• 100 ⭐ → +5%\n"
    "• 250 ⭐ → +10%\n"
    "• 500 ⭐ → +15%\n"
    "• 1000 ⭐ → +20%\n"
    "• 2500 ⭐ → +25%\n\n"
    "👤 <b>Ваш баланс:</b> {balance} TOKENS"
)


async def _send_cashier(uid: int) -> None:
    balance = await get_balance(uid)
    text = CASHIER_TEXT.format(rate=fmt_num(STAR_RATE), balance=fmt_num(balance))
    await bot.send_message(uid, text, reply_markup=ikb_cashier())


@router.message(Command("cashier"))
@router.message(F.text == "💎 Касса")
async def cmd_cashier(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    await ensure_user(user)
    await _send_cashier(user.id)
    await message.answer("Выберите действие:", reply_markup=kb_cashier())


@router.message(F.text == "📊 Курс")
async def cmd_rate_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"📊 <b>Текущий курс</b>\n\n"
        f"1 ⭐ = <b>{fmt_num(STAR_RATE)} TOKENS</b>\n\n"
        f"<i>Курс фиксируется на момент пополнения.</i>",
        reply_markup=kb_cashier(),
    )


@router.callback_query(F.data == "cash:rate")
async def cb_cash_rate(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    try:
        await cb.message.edit_text(
            f"📊 <b>Курс</b>\n1 ⭐ = <b>{fmt_num(STAR_RATE)} TOKENS</b>",
            reply_markup=ikb_cashier(),
        )
    except Exception:  # noqa: BLE001
        await cb.message.answer(
            f"📊 <b>Курс</b>\n1 ⭐ = <b>{fmt_num(STAR_RATE)} TOKENS</b>",
            reply_markup=ikb_cashier(),
        )


@router.message(F.text == "⭐ Купить Stars-пакет")
async def cmd_cashier_packs(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        await _send_cashier(message.from_user.id)
    except Exception:  # noqa: BLE001
        log_exc("cashier packs")


async def _send_invoice_stars(uid: int, stars: int, payload: str) -> None:
    """Выставляет счёт в Stars."""
    if stars <= 0 or stars > 100000:
        raise ValueError("Некорректная сумма stars")
    await bot.send_invoice(
        chat_id=uid,
        title=f"Пополнение на {stars} ⭐",
        description=f"Пополнение баланса на {stars} ⭐ (= {fmt_num(stars * STAR_RATE)} TOKENS).",
        payload=payload,
        provider_token="",  # для Stars пустая строка
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)],
    )


@router.callback_query(F.data.startswith("cash:"))
async def cb_cash_choose(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    user = cb.from_user
    data = cb.data.split(":", 1)[1]
    if await is_banned(user.id):
        await cb.answer("🚫 Доступ закрыт.", show_alert=True)
        return

    if data == "custom":
        await state.set_state(CashierStates.waiting_custom_stars)
        await cb.message.answer(
            "✏️ <b>Своя сумма</b>\n\n"
            "Введите количество ⭐ (от 1 до 100 000).\n"
            f"1 ⭐ = {fmt_num(STAR_RATE)} TOKENS\n\n"
            "Отмена — /cancel",
            reply_markup=kb_cancel(),
        )
        return

    if data == "rate":
        await cb_cash_rate(cb)
        return

    if not data.isdigit():
        await cb.answer("Некорректный пакет", show_alert=True)
        return

    stars = int(data)
    # Найти пакет
    pack = next(((s, b) for s, b in CASH_PACKS if s == stars), None)
    if pack is None:
        await cb.answer("Пакет не найден", show_alert=True)
        return
    s, bonus = pack
    tokens = _pack_tokens(s, bonus)
    try:
        await _send_invoice_stars(
            user.id,
            stars,
            payload=f"cash:{stars}:{bonus}:{tokens}",
        )
        await cb.answer(f"Счёт на {s} ⭐ отправлен", show_alert=False)
    except Exception:  # noqa: BLE001
        log_exc("send invoice")
        await cb.answer("Не удалось выставить счёт. Попробуйте позже.", show_alert=True)


@router.message(CashierStates.waiting_custom_stars, F.text)
async def fsm_custom_stars(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID))
        return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("❗ Введите целое число ⭐ от 1 до 100 000.")
        return
    stars = int(txt)
    if stars < 1 or stars > 100_000:
        await message.answer("❗ Сумма должна быть от 1 до 100 000 ⭐.")
        return
    tokens = stars * STAR_RATE
    await state.clear()
    try:
        await _send_invoice_stars(message.from_user.id, stars, payload=f"cash:{stars}:0:{tokens}")
        await message.answer("Счёт выставлен выше ☝️", reply_markup=kb_cashier())
    except Exception:  # noqa: BLE001
        log_exc("custom stars invoice")
        await message.answer("⚠️ Не удалось выставить счёт. Попробуйте позже.", reply_markup=kb_cashier())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Отменено.",
        reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID),
    )


# =============================================================
# 23. PRE-CHECKOUT + SUCCESSFUL PAYMENT
# =============================================================

@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery) -> None:
    """Подтверждаем любой pre-checkout (Stars уже списаны платформой)."""
    try:
        await bot.answer_pre_checkout_query(pcq.id, ok=True)
    except Exception:  # noqa: BLE001
        log_exc("pre_checkout")


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if not sp:
        return
    user = message.from_user
    payload = sp.invoice_payload or ""

    # ----- VIP оплата -----
    if payload.startswith("vip:"):
        tier = payload.split(":", 1)[1]
        info = VIP_TIERS.get(tier)
        if not info:
            await message.answer("⚠️ Неизвестный VIP-тир.")
            return
        until = now_ts() + 30 * 86400
        await set_vip(user.id, tier, until)
        await message.answer(
            f"👑 <b>VIP {info['name']} активирован!</b>\n\n"
            f"Действует до: <b>{fmt_dt(datetime.fromtimestamp(until, TZ))}</b>\n"
            f"Множитель лимита ставок: <b>x{info['limit_mult']}</b>",
            reply_markup=kb_main(user.id, user.id == ADMIN_ID),
        )
        try:
            await bot.send_message(
                ADMIN_ID,
                f"👑 <b>VIP покупка</b>\n"
                f"👤 {safe_username(user)} (<code>{user.id}</code>)\n"
                f"🎖 Тир: <b>{info['name']}</b>\n"
                f"💰 Оплачено: {sp.total_amount} ⭐",
            )
        except Exception:  # noqa: BLE001
            pass
        return

    # ----- Касса -----
    if payload.startswith("cash:"):
        parts = payload.split(":")
        try:
            stars = int(parts[1])
            bonus = int(parts[2])
            tokens_expected = int(parts[3])
        except Exception:  # noqa: BLE001
            stars, bonus, tokens_expected = sp.total_amount, 0, sp.total_amount * STAR_RATE

        # Пересчитываем токены на актуальном курсе (анти-подмена payload)
        base = stars * STAR_RATE
        tokens = base + base * bonus // 100

        async with db.transaction() as conn:
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at=? WHERE user_id=?",
                (tokens, now_ts(), user.id),
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, kind, amount, stars, meta, ts) VALUES (?, 'deposit_stars', ?, ?, ?, ?)",
                (
                    user.id,
                    tokens,
                    stars,
                    json.dumps({"bonus": bonus, "charge_id": sp.telegram_payment_charge_id}, ensure_ascii=False),
                    now_ts(),
                ),
            )

        new_balance = await get_balance(user.id)
        await message.answer(
            f"✅ <b>Пополнение успешно!</b>\n\n"
            f"⭐ Оплачено: <b>{sp.total_amount}</b>\n"
            f"💰 Начислено: <b>{fmt_num(tokens)} TOKENS</b>\n"
            f"👛 Баланс: <b>{fmt_num(new_balance)} TOKENS</b>"
            + (f"\n🎁 Бонус: +{bonus}%" if bonus else ""),
            reply_markup=kb_main(user.id, user.id == ADMIN_ID),
        )
        try:
            await bot.send_message(
                ADMIN_ID,
                f"💳 <b>Пополнение Stars</b>\n"
                f"👤 {safe_username(user)} (<code>{user.id}</code>)\n"
                f"⭐ {sp.total_amount}\n"
                f"💰 +{fmt_num(tokens)} TOKENS"
                + (f" (+{bonus}%)" if bonus else ""),
            )
        except Exception:  # noqa: BLE001
            pass
        return

    # ----- Неизвестный payload -----
    await message.answer("⚠️ Оплата получена, но payload неизвестен. Обратитесь в поддержку.")
    try:
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ Неизвестный successful_payment\n"
            f"👤 {user.id}\n"
            f"payload={payload}\n"
            f"amount={sp.total_amount} {sp.currency}",
        )
    except Exception:  # noqa: BLE001
        pass


# =============================================================
# 24. ЭЛИТА (VIP-витрина)
# =============================================================

ELITE_TEXT = (
    "👑 <b>Элита</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "VIP-статусы клуба. Повышенные лимиты, приоритет, "
    "закрытые турниры.\n\n"
    "🥈 <b>Silver</b> — x1.5 лимит · 100 ⭐ / 30 дней\n"
    "🥇 <b>Gold</b> — x2.0 лимит · 250 ⭐ / 30 дней\n"
    "💎 <b>Platinum</b> — x3.0 лимит · 500 ⭐ / 30 дней\n"
    "🖤 <b>Black</b> — x5.0 лимит · 1000 ⭐ / 30 дней\n\n"
    "🎁 <b>Ваш текущий статус:</b> {current}"
)


def _current_vip_txt(row: aiosqlite.Row) -> str:
    tier = row["vip_tier"] or "none"
    until = row["vip_until"]
    if tier == "none" or not until or until <= now_ts():
        return "— (обычный игрок)"
    info = vip_info(tier)
    left_days = max(0, (until - now_ts()) // 86400)
    return f"{info['emoji']} {info['name']} · осталось {left_days} дн."


@router.message(Command("elite"))
@router.message(F.text == "👑 Элита")
async def cmd_elite(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    row = await ensure_user(user)
    await message.answer(
        ELITE_TEXT.format(current=_current_vip_txt(row)),
        reply_markup=ikb_premium(),
    )


# =============================================================
# 25. РАСШИРЕНИЕ CALLBACK-НАВИГАЦИИ
# =============================================================
# (обработчик go:* уже определён в Части 2; _send_alliance и _send_cashier
#  теперь имеют реальные реализации, поэтому "go:alliance" и "go:cashier"
#  автоматически работают.)


# =============================================================
# 26. ПЕРЕОПРЕДЕЛЕНИЕ ensure_user → теперь с наградой-партнёру
# =============================================================
# Награда рефереру уже учтена в оригинальном ensure_user (Часть 1).
# Здесь — никаких изменений.

# =============================================================
# ЧАСТЬ 4: СЕЗОН, СТИКЕРНЫЕ ИГРЫ, ДУЭЛИ
# =============================================================

# =============================================================
# 27. СЕЗОН (ТУРНИР)
# =============================================================

SEASON_TEXT_TEMPLATE = (
    "🏆 <b>Сезон</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Топ-10 игроков по <b>чистому выигрышу</b> за 7 дней.\n"
    "Сброс каждый понедельник.\n\n"
    "🎁 <b>Призовой фонд:</b>\n"
    "🥇 1 место — <b>{r1} TOKENS</b>\n"
    "🥈 2 место — <b>{r2} TOKENS</b>\n"
    "🥉 3 место — <b>{r3} TOKENS</b>\n"
    "4–10 место — от <b>{r10} до {r4} TOKENS</b>\n\n"
    "⏳ <b>До конца сезона:</b> {left}\n\n"
    "{top_block}"
)


async def _format_season_top(season_id: int, limit: int = 10) -> str:
    rows = await db.fetchall(
        """
        SELECT t.user_id, t.net_win, t.games, u.username, u.full_name
        FROM tournaments t
        LEFT JOIN users u ON u.user_id = t.user_id
        WHERE t.season_id=? AND t.net_win > 0
        ORDER BY t.net_win DESC, t.games ASC
        LIMIT ?
        """,
        (season_id, limit),
    )
    if not rows:
        return "📊 <i>Пока никто не сделал ставок. Будьте первым!</i>"
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = ["📊 <b>Топ-10 сезона:</b>\n"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < len(medals) else "▫️"
        uname = f"@{r['username']}" if r["username"] else (r["full_name"] or f"id{r['user_id']}")
        uname = clip_text(uname, 20)
        reward = SEASON_REWARDS[i] if i < len(SEASON_REWARDS) else 0
        lines.append(
            f"{medal} <b>{i+1}.</b> {uname} — "
            f"<b>+{fmt_num(r['net_win'])}</b> "
            f"<i>({fmt_num(r['games'])} игр, приз {fmt_num(reward)})</i>"
        )
    return "\n".join(lines)


def _fmt_left(ends_ts: int) -> str:
    left = max(0, ends_ts - now_ts())
    d = left // 86400
    h = (left % 86400) // 3600
    m = (left % 3600) // 60
    return f"{d}д {h}ч {m}м"


async def _send_season(uid: int) -> None:
    season = await get_active_season()
    if not season:
        await bot.send_message(uid, "🏆 Сезон временно недоступен.")
        return
    top_block = await _format_season_top(season["id"])
    text = SEASON_TEXT_TEMPLATE.format(
        r1=fmt_num(SEASON_REWARDS[0]),
        r2=fmt_num(SEASON_REWARDS[1]),
        r3=fmt_num(SEASON_REWARDS[2]),
        r4=fmt_num(SEASON_REWARDS[3]),
        r10=fmt_num(SEASON_REWARDS[9]),
        left=_fmt_left(season["ends_at"]),
        top_block=top_block,
    )
    await bot.send_message(uid, text, reply_markup=ikb_season())


@router.message(Command("season"))
@router.message(F.text == "🏆 Сезон")
async def cmd_season(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    await ensure_user(user)
    await _send_season(user.id)


@router.callback_query(F.data == "season:refresh")
async def cb_season_refresh(cb: CallbackQuery) -> None:
    try:
        await cb.answer("Обновлено")
    except Exception:  # noqa: BLE001
        pass
    season = await get_active_season()
    if not season:
        return
    top_block = await _format_season_top(season["id"])
    text = SEASON_TEXT_TEMPLATE.format(
        r1=fmt_num(SEASON_REWARDS[0]),
        r2=fmt_num(SEASON_REWARDS[1]),
        r3=fmt_num(SEASON_REWARDS[2]),
        r4=fmt_num(SEASON_REWARDS[3]),
        r10=fmt_num(SEASON_REWARDS[9]),
        left=_fmt_left(season["ends_at"]),
        top_block=top_block,
    )
    try:
        await cb.message.edit_text(text, reply_markup=ikb_season())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_season())


@router.callback_query(F.data == "season:my")
async def cb_season_my(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    uid = cb.from_user.id
    season = await get_active_season()
    if not season:
        return
    row = await db.fetchone(
        "SELECT net_win, games FROM tournaments WHERE season_id=? AND user_id=?",
        (season["id"], uid),
    )
    if not row:
        text = "📊 <b>Вы ещё не участвовали в этом сезоне.</b>\nСделайте первую ставку!"
    else:
        # позиция
        pos = await db.fetchval(
            "SELECT COUNT(*)+1 FROM tournaments WHERE season_id=? AND net_win > ?",
            (season["id"], row["net_win"]),
        )
        text = (
            f"📊 <b>Ваша статистика в сезоне:</b>\n\n"
            f"🎯 Позиция: <b>#{pos}</b>\n"
            f"💰 Чистый выигрыш: <b>{'+' if row['net_win']>=0 else ''}{fmt_num(row['net_win'])}</b>\n"
            f"🎮 Игр: <b>{fmt_num(row['games'])}</b>"
        )
    try:
        await cb.message.answer(text, reply_markup=ikb_season())
    except Exception:  # noqa: BLE001
        pass


async def finalize_season() -> None:
    """Закрыть истёкший сезон, выплатить награды, создать новый."""
    season = await get_active_season()
    if not season:
        return
    if season["ends_at"] > now_ts():
        return
    log.info("Finalizing season %s", season["id"])
    rows = await db.fetchall(
        "SELECT user_id, net_win FROM tournaments WHERE season_id=? AND net_win > 0 ORDER BY net_win DESC LIMIT 10",
        (season["id"],),
    )
    for i, r in enumerate(rows):
        if i >= len(SEASON_REWARDS):
            break
        reward = SEASON_REWARDS[i]
        await add_balance(r["user_id"], reward, kind="season_prize",
                          meta={"season": season["id"], "place": i + 1})
        try:
            await bot.send_message(
                r["user_id"],
                f"🏆 <b>Сезон завершён!</b>\n\n"
                f"Ваше место: <b>#{i+1}</b>\n"
                f"Чистый выигрыш: <b>+{fmt_num(r['net_win'])}</b>\n"
                f"🎁 Награда: <b>{fmt_num(reward)} TOKENS</b>",
                reply_markup=kb_main(r["user_id"], r["user_id"] == ADMIN_ID),
            )
        except Exception:  # noqa: BLE001
            pass
    await db.execute("UPDATE seasons SET status='closed', paid_out=1 WHERE id=?", (season["id"],))
    now = now_ts()
    ends = now + SEASON_DURATION_DAYS * 86400
    await db.execute(
        "INSERT INTO seasons (started_at, ends_at, status) VALUES (?, ?, 'active')",
        (now, ends),
    )
    log.info("New season started, ends at %s", fmt_dt(datetime.fromtimestamp(ends, TZ)))


# =============================================================
# 28. ИГРОВОЙ ЗАЛ — ГЛАВНОЕ МЕНЮ ИГР
# =============================================================

GAMES_MENU_TEXT = (
    "🎮 <b>Игровой Зал</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "11 игр на любой вкус.\n"
    "Выберите игру ниже или в reply-меню 👇\n\n"
    "🎲 Кости · 🎯 Дартс · 🏀 Баскет\n"
    "⚽ Футбол · 🎳 Боулинг · 🃏 БЖ\n"
    "🎰 Слоты · 💣 Мины · ⚔️ Дуэль · 🎡 Рулетка"
)


@router.message(F.text == "🎮 Игровой Зал")
async def cmd_games(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if not user:
        return
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    if GAMES_DISABLED and user.id != ADMIN_ID:
        await message.answer("🛠 <b>Игровой зал временно отключён администрацией.</b>")
        return
    await ensure_user(user)
    await message.answer(GAMES_MENU_TEXT, reply_markup=kb_games())
    await message.answer("Быстрый выбор 👇", reply_markup=ikb_games())


@router.callback_query(F.data == "go:games")
async def cb_go_games(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.clear()
    user = cb.from_user
    await bot.send_message(user.id, GAMES_MENU_TEXT, reply_markup=kb_games())
    await bot.send_message(user.id, "Быстрый выбор 👇", reply_markup=ikb_games())


# =============================================================
# 29. СТИКЕРНЫЕ ИГРЫ (DICE) — ОБЩИЙ МЕХАНИЗМ
# =============================================================

def _dice_multiplier(game_key: str, value: int) -> float:
    """Возвращает множитель для исхода стикерной игры."""
    cfg = DICE_GAMES.get(game_key)
    if not cfg:
        return -1.0
    return float(cfg["mult"].get(value, -1.0))


async def _run_dice_game(
    uid: int,
    game_key: str,
    bet: int,
    chat_id: int,
    thread_id: Optional[int] = None,
) -> None:
    """Запуск стикерной игры (dice)."""
    cfg = DICE_GAMES[game_key]
    emoji = cfg["emoji"]

    # Атомарное списание
    ok = await try_debit(uid, bet, kind=f"bet_{game_key}", meta={"game": game_key})
    if not ok:
        await bot.send_message(chat_id, f"❌ Недостаточно средств. Нужно: <b>{fmt_num(bet)}</b> TOKENS.")
        return

    # Отправляем dice
    try:
        dice_msg = await bot.send_dice(chat_id=chat_id, emoji=emoji)
    except Exception:  # noqa: BLE001
        log_exc("send_dice")
        # вернуть ставку
        await add_balance(uid, bet, kind="refund", meta={"game": game_key, "reason": "dice_fail"})
        await bot.send_message(chat_id, "⚠️ Не удалось бросить кубик. Ставка возвращена.")
        return

    value = int(dice_msg.dice.value) if dice_msg.dice else 0
    mult = _dice_multiplier(game_key, value)
    win = int(round(bet * mult)) if mult > 0 else 0

    # Зачисление / фиксация
    if win > 0:
        await credit_win(uid, win, game=game_key, meta={"value": value, "mult": mult, "bet": bet})
        delta = win - bet
        result_txt = (
            f"🎉 <b>Победа!</b>\n"
            f"{emoji} <b>{cfg['name']}</b> → {value}\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
            f"📈 Множитель: <b>x{mult:g}</b>\n"
            f"💵 Выигрыш: <b>+{fmt_num(win)} TOKENS</b>\n"
            f"📊 Итог: <b>{'+' if delta>=0 else ''}{fmt_num(delta)}</b>"
        )
    elif mult == 0:
        await add_balance(uid, bet, kind="refund", meta={"game": game_key, "value": value, "mult": 0})
        result_txt = (
            f"🤝 <b>Возврат</b>\n"
            f"{emoji} <b>{cfg['name']}</b> → {value}\n"
            f"💰 Ставка возвращена: <b>{fmt_num(bet)} TOKENS</b>"
        )
    else:
        await db.execute(
            "UPDATE users SET total_lost = total_lost + ?, updated_at=? WHERE user_id=?",
            (bet, now_ts(), uid),
        )
        result_txt = (
            f"💀 <b>Проигрыш</b>\n"
            f"{emoji} <b>{cfg['name']}</b> → {value}\n"
            f"💰 Потеряно: <b>-{fmt_num(bet)} TOKENS</b>"
        )

    await log_game(uid, game_key, bet, win, meta={"value": value, "mult": mult})

    try:
        info_msg = await bot.send_message(chat_id, result_txt)
    except Exception:  # noqa: BLE001
        info_msg = None

    # Автоудаление через DICE_AUTODELETE_SEC
    async def _cleanup() -> None:
        await asyncio.sleep(DICE_AUTODELETE_SEC)
        for m in (dice_msg, info_msg):
            if not m:
                continue
            try:
                await m.delete()
            except Exception:  # noqa: BLE001
                pass

    asyncio.create_task(_cleanup())


# ----- Универсальный хендлер выбора игры -----

@router.callback_query(F.data.startswith("game:"))
async def cb_game_choose(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    game_key = cb.data.split(":", 1)[1]
    await _open_bet_choice(cb.from_user.id, game_key, cb.message)


async def _open_bet_choice(uid: int, game_key: str, source_message: Optional[Message] = None) -> None:
    if GAMES_DISABLED and uid != ADMIN_ID:
        await bot.send_message(uid, "🛠 <b>Игровой зал отключён.</b>")
        return
    if game_key in DICE_GAMES:
        name = DICE_GAMES[game_key]["name"]
        text = (
            f"🎮 <b>{name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Мин. ставка: {fmt_num(MIN_BET)} TOKENS\n"
            f"💰 Макс. ставка: {fmt_num(MAX_BET)} TOKENS\n\n"
            f"Выберите размер ставки:"
        )
        await bot.send_message(uid, text, reply_markup=ikb_bet_choice(game_key))
    elif game_key == "mines":
        await _open_mines_menu(uid)
    elif game_key == "duel":
        await _open_duel_menu(uid)
    elif game_key == "roulette":
        await _open_roulette_menu(uid)
    else:
        await bot.send_message(uid, "⚠️ Игра не найдена.")


# ----- Reply-кнопки стикерных игр -----

@router.message(F.text == "🎲 Кости")
async def msg_dice(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "dice")


@router.message(F.text == "🎯 Дартс")
async def msg_dart(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "dart")


@router.message(F.text == "🏀 Баскет")
async def msg_basket(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "basket")


@router.message(F.text == "⚽ Футбол")
async def msg_football(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "football")


@router.message(F.text == "🎳 Боулинг")
async def msg_bowling(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "bowling")


@router.message(F.text == "🃏 БЖ")
async def msg_bj(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "bj")


@router.message(F.text == "🎰 Слоты")
async def msg_slots(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_bet_choice(message.from_user.id, "slots")


# ----- Выбор ставки из inline -----

@router.callback_query(F.data.startswith("bet:"))
async def cb_bet_choice(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    if len(parts) < 3:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass
        return
    game_key = parts[1]
    value = parts[2]
    uid = cb.from_user.id

    if await is_banned(uid):
        try:
            await cb.answer("🚫 Доступ закрыт", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return

    ok, left = check_cooldown(uid)
    if not ok:
        try:
            await cb.answer(f"⏳ Подождите {left} сек.", show_alert=False)
        except Exception:  # noqa: BLE001
            pass
        return

    if value == "custom":
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass
        await state.set_state(GameBetStates.waiting_custom_bet)
        await state.update_data(game=game_key)
        await bot.send_message(
            uid,
            f"✏️ Введите сумму ставки (от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}):\n\nОтмена — /cancel",
            reply_markup=kb_cancel(),
        )
        return

    if not value.isdigit():
        try:
            await cb.answer("Некорректная сумма", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    bet = int(value)
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await _execute_bet(uid, game_key, bet, cb.message.chat.id if cb.message else uid)


class GameBetStates(StatesGroup):
    waiting_custom_bet = State()


async def _execute_bet(uid: int, game_key: str, bet: int, chat_id: int) -> None:
    if bet < MIN_BET or bet > MAX_BET:
        await bot.send_message(chat_id, f"❗ Ставка должна быть от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}.")
        return
    if game_key in DICE_GAMES:
        await _run_dice_game(uid, game_key, bet, chat_id)


@router.message(GameBetStates.waiting_custom_bet, F.text)
async def fsm_custom_bet(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID))
        return
    data = await state.get_data()
    game_key = data.get("game")
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer(f"❗ Введите целое число от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}.")
        return
    bet = int(txt)
    if bet < MIN_BET or bet > MAX_BET:
        await message.answer(f"❗ Ставка от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}.")
        return
    await state.clear()
    if game_key in DICE_GAMES:
        await _run_dice_game(message.from_user.id, game_key, bet, message.chat.id)


# =============================================================
# 30. ДУЭЛИ
# =============================================================

DUEL_TEXT = (
    "⚔️ <b>Дуэли</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Вызовите соперника на дуэль.\n"
    "Ставка обоих игроков идёт в банк.\n"
    "Победитель забирает всё (минус 5% комиссия клуба).\n\n"
    "💰 Лимиты: {min} — {max} TOKENS"
)


def _duel_id() -> str:
    return f"d{int(time.time())}{random.randint(1000, 9999)}"


async def _open_duel_menu(uid: int) -> None:
    text = DUEL_TEXT.format(min=fmt_num(DUEL_MIN), max=fmt_num(DUEL_MAX))
    b = InlineKeyboardBuilder()
    for amt in (500, 1000, 5000, 10000, 50000):
        b.button(text=f"{fmt_num(amt)}", callback_data=f"duel:create:{amt}")
    b.button(text="✏️ Своя ставка", callback_data="duel:create:custom")
    b.button(text="⬅️ Назад", callback_data="go:games")
    b.adjust(5, 1, 1)
    await bot.send_message(uid, text, reply_markup=b.as_markup())


@router.message(F.text == "⚔️ Дуэль")
async def msg_duel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message.from_user)
    await _open_duel_menu(message.from_user.id)


@router.callback_query(F.data.startswith("duel:create:"))
async def cb_duel_create(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    value = cb.data.split(":")[-1]
    if value == "custom":
        await state.set_state(DuelStates.waiting_custom_bet)
        await bot.send_message(
            cb.from_user.id,
            f"✏️ Введите сумму дуэли (от {fmt_num(DUEL_MIN)} до {fmt_num(DUEL_MAX)}):\n\nОтмена — /cancel",
            reply_markup=kb_cancel(),
        )
        return
    if not value.isdigit():
        return
    bet = int(value)
    await _create_duel(cb.from_user.id, bet)


class DuelStates(StatesGroup):
    waiting_custom_bet = State()


@router.message(DuelStates.waiting_custom_bet, F.text)
async def fsm_duel_custom(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID))
        return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer(f"❗ Введите целое число от {fmt_num(DUEL_MIN)} до {fmt_num(DUEL_MAX)}.")
        return
    bet = int(txt)
    if bet < DUEL_MIN or bet > DUEL_MAX:
        await message.answer(f"❗ Ставка от {fmt_num(DUEL_MIN)} до {fmt_num(DUEL_MAX)}.")
        return
    await state.clear()
    await _create_duel(message.from_user.id, bet)


async def _create_duel(uid: int, bet: int) -> None:
    if bet < DUEL_MIN or bet > DUEL_MAX:
        await bot.send_message(uid, "❗ Некорректная сумма дуэли.")
        return
    # Списать с автора
    ok = await try_debit(uid, bet, kind="duel_freeze", meta={"game": "duel", "role": "creator"})
    if not ok:
        await bot.send_message(uid, f"❌ Недостаточно средств. Нужно: <b>{fmt_num(bet)}</b> TOKENS.")
        return
    did = _duel_id()
    DUELS[did] = {
        "creator": uid,
        "bet": bet,
        "created": now_ts(),
        "status": "waiting",
    }
    text = (
        f"⚔️ <b>Дуэль создана!</b>\n\n"
        f"👤 Автор: <code>{uid}</code>\n"
        f"💰 Ставка: <b>{fmt_num(bet)} TOKENS</b>\n\n"
        f"<i>Кнопка ниже — для соперника. Нажмите, чтобы принять вызов.</i>"
    )
    await bot.send_message(uid, text, reply_markup=ikb_duel_accept(did, bet))
    await bot.send_message(uid, "Ожидайте соперника…", reply_markup=ikb_duel_choice(did))


@router.callback_query(F.data.startswith("duel:accept:"))
async def cb_duel_accept(cb: CallbackQuery) -> None:
    did = cb.data.split(":", 2)[-1]
    duel = DUELS.get(did)
    if not duel or duel["status"] != "waiting":
        try:
            await cb.answer("Дуэль уже недоступна", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    if cb.from_user.id == duel["creator"]:
        try:
            await cb.answer("Нельзя принять свою дуэль", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    bet = duel["bet"]
    ok = await try_debit(cb.from_user.id, bet, kind="duel_freeze", meta={"game": "duel", "role": "opponent"})
    if not ok:
        try:
            await cb.answer("❌ Недостаточно средств", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return

    duel["status"] = "running"
    duel["opponent"] = cb.from_user.id
    try:
        await cb.answer("Вызов принят!")
    except Exception:  # noqa: BLE001
        pass

    creator = duel["creator"]
    opponent = cb.from_user.id
    chat_id = cb.message.chat.id
    pot = bet * 2

    # Отправляем «кубик» в чат где приняли
    try:
        dice_msg = await bot.send_dice(chat_id=chat_id, emoji="🎲")
        await asyncio.sleep(4)
        value = int(dice_msg.dice.value) if dice_msg.dice else 1
    except Exception:  # noqa: BLE001
        log_exc("duel dice")
        value = random.randint(1, 6)

    # Победитель: чёт → оппонент, нечёт → создатель (или по значению)
    winner = creator if value % 2 == 1 else opponent
    loser = opponent if winner == creator else creator
    # Комиссия клуба 5%
    fee = pot * 5 // 100
    payout = pot - fee

    await credit_win(winner, payout, game="duel", meta={"duel_id": did, "value": value})
    await log_game(winner, "duel", bet, payout, meta={"duel_id": did, "value": value, "role": "winner"})
    await log_game(loser, "duel", bet, 0, meta={"duel_id": did, "value": value, "role": "loser"})

    DUELS.pop(did, None)

    win_name = "автор" if winner == creator else "соперник"
    text = (
        f"⚔️ <b>Дуэль завершена!</b>\n\n"
        f"🎲 Кубик: <b>{value}</b>\n"
        f"🏆 Победитель: <b>{win_name}</b> (<code>{winner}</code>)\n"
        f"💰 Банк: <b>{fmt_num(pot)}</b>\n"
        f"💸 Комиссия: <b>{fmt_num(fee)}</b>\n"
        f"🎁 Выплата: <b>{fmt_num(payout)} TOKENS</b>"
    )
    try:
        await bot.send_message(chat_id, text)
        await bot.send_message(winner, f"🎉 <b>Вы победили в дуэли!</b>\n+{fmt_num(payout)} TOKENS")
        await bot.send_message(loser, f"💀 <b>Вы проиграли дуэль.</b>\n-{fmt_num(bet)} TOKENS")
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("duel:decline:"))
async def cb_duel_decline(cb: CallbackQuery) -> None:
    did = cb.data.split(":", 2)[-1]
    duel = DUELS.get(did)
    if not duel:
        try:
            await cb.answer("Уже отменена", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    if cb.from_user.id == duel["creator"]:
        try:
            await cb.answer("Это ваша дуэль", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        await cb.answer("Отклонено")
    except Exception:  # noqa: BLE001
        pass
    await bot.send_message(cb.from_user.id, "Вы отклонили дуэль.")
    try:
        await bot.send_message(duel["creator"], f"😔 Дуэль {did[:8]}… отклонена.")
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("duel:cancel:"))
async def cb_duel_cancel(cb: CallbackQuery) -> None:
    did = cb.data.split(":", 2)[-1]
    duel = DUELS.get(did)
    if not duel:
        try:
            await cb.answer("Уже недоступна", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    if cb.from_user.id != duel["creator"]:
        try:
            await cb.answer("Не ваша дуэль", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    bet = duel["bet"]
    await add_balance(duel["creator"], bet, kind="refund", meta={"game": "duel", "duel_id": did})
    DUELS.pop(did, None)
    try:
        await cb.answer("Дуэль отменена, ставка возвращена")
    except Exception:  # noqa: BLE001
        pass
    try:
        await bot.send_message(duel["creator"], f"🔄 Дуэль отменена. Возврат: <b>{fmt_num(bet)} TOKENS</b>")
    except Exception:  # noqa: BLE001
        pass


# =============================================================
# 31. ЗАГЛУШКИ (реализуются в Части 5)
# =============================================================

async def _open_mines_menu(uid: int) -> None:  # pragma: no cover
    await bot.send_message(uid, "💣 <b>Мины</b>\nЗагрузка…")


async def _open_roulette_menu(uid: int) -> None:  # pragma: no cover
    await bot.send_message(uid, "🎡 <b>Рулетка</b>\nЗагрузка…")

# =============================================================
# ЧАСТЬ 5: МИНЫ, РУЛЕТКА, АДМИН-ПУЛЬТ
# =============================================================

# =============================================================
# 32. МИНЫ (5x5, cashout)
# =============================================================

MINES_MULT_TABLE = {
    # mines: {opened: multiplier}
    3:  {1: 1.10, 2: 1.30, 3: 1.55, 4: 1.90, 5: 2.35, 6: 2.90, 7: 3.60, 8: 4.50,
         9: 5.65, 10: 7.10, 11: 9.00, 12: 11.40, 13: 14.50, 14: 18.50, 15: 23.70,
         16: 30.40, 17: 39.10, 18: 50.40, 19: 65.10, 20: 84.30, 21: 109.00, 22: 141.00},
    5:  {1: 1.18, 2: 1.45, 3: 1.80, 4: 2.25, 5: 2.85, 6: 3.60, 7: 4.60, 8: 5.90,
         9: 7.60, 10: 9.80, 11: 12.70, 12: 16.60, 13: 21.70, 14: 28.50, 15: 37.60,
         16: 49.80, 17: 66.20, 18: 88.50, 19: 119.00, 20: 162.00},
    10: {1: 1.40, 2: 2.00, 3: 2.90, 4: 4.30, 5: 6.40, 6: 9.70, 7: 14.80, 8: 22.80,
         9: 35.40, 10: 55.60, 11: 88.50, 12: 142.00, 13: 232.00, 14: 388.00, 15: 668.00},
}


def _mines_multiplier(mines: int, opened: int) -> float:
    table = MINES_MULT_TABLE.get(mines, MINES_MULT_TABLE[5])
    return float(table.get(opened, 0.0))


async def _open_mines_menu(uid: int) -> None:
    balance = await get_balance(uid)
    text = (
        "💣 <b>Мины</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Поле 5×5, спрятаны мины.\n"
        "Открывайте клетки, забирайте выигрыш в любой момент.\n\n"
        f"💰 Баланс: <b>{fmt_num(balance)} TOKENS</b>\n"
        f"🔻 Мин. ставка: {fmt_num(MIN_BET)}\n\n"
        "Выберите количество мин:"
    )
    await bot.send_message(uid, text, reply_markup=ikb_mines_start())


@router.message(F.text == "💣 Мины")
async def msg_mines(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    await ensure_user(user)
    await _open_mines_menu(user.id)


@router.callback_query(F.data.startswith("mines:start:"))
async def cb_mines_start(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    uid = cb.from_user.id
    if uid in MINES_GAMES:
        await cb.answer("У вас уже есть активная игра", show_alert=True)
        return
    try:
        mines = int(cb.data.split(":")[-1])
    except Exception:  # noqa: BLE001
        return
    if mines not in MINES_MULT_TABLE:
        await cb.answer("Некорректно", show_alert=True)
        return
    await state.set_state(MinesStates.waiting_bet)
    await state.update_data(mines=mines)
    await bot.send_message(
        uid,
        f"💣 <b>{mines} мин</b>\n\n"
        f"Введите сумму ставки (от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}):\n\n"
        f"Отмена — /cancel",
        reply_markup=kb_cancel(),
    )


class MinesStates(StatesGroup):
    waiting_bet = State()


@router.message(MinesStates.waiting_bet, F.text)
async def fsm_mines_bet(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_main(message.from_user.id, message.from_user.id == ADMIN_ID))
        return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer(f"❗ Введите целое число от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}.")
        return
    bet = int(txt)
    if bet < MIN_BET or bet > MAX_BET:
        await message.answer(f"❗ Ставка от {fmt_num(MIN_BET)} до {fmt_num(MAX_BET)}.")
        return
    data = await state.get_data()
    mines = data.get("mines", 5)
    await state.clear()
    await _start_mines(message.from_user.id, bet, mines, message.chat.id)


async def _start_mines(uid: int, bet: int, mines: int, chat_id: int) -> None:
    if uid in MINES_GAMES:
        await bot.send_message(chat_id, "⚠️ Активная игра уже существует.")
        return
    ok = await try_debit(uid, bet, kind="bet_mines", meta={"mines": mines, "bet": bet})
    if not ok:
        await bot.send_message(chat_id, f"❌ Недостаточно средств. Нужно: <b>{fmt_num(bet)}</b>.")
        return
    # Генерим позиции мин
    positions = random.sample(range(25), mines)
    MINES_GAMES[uid] = {
        "bet": bet,
        "mines": mines,
        "mine_positions": set(positions),
        "opened": set(),
        "chat_id": chat_id,
        "started": now_ts(),
    }
    cashout = bet  # пока не открыто — вернётся ставка
    await bot.send_message(
        chat_id,
        f"💣 <b>Игра началась!</b>\n\n"
        f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
        f"💣 Мин: <b>{mines}</b>\n"
        f"🎯 Открывайте клетки и забирайте выигрыш.",
        reply_markup=ikb_mines(mines, set(), cashout),
    )


@router.callback_query(F.data.startswith("mines:open:"))
async def cb_mines_open(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    uid = cb.from_user.id
    game = MINES_GAMES.get(uid)
    if not game:
        return
    try:
        idx = int(cb.data.split(":")[-1])
    except Exception:  # noqa: BLE001
        return
    if idx < 0 or idx >= 25 or idx in game["opened"]:
        return

    if idx in game["mine_positions"]:
        # Проигрыш
        bet = game["bet"]
        mine_idx = idx
        MINES_GAMES.pop(uid, None)
        await db.execute(
            "UPDATE users SET total_lost = total_lost + ?, updated_at=? WHERE user_id=?",
            (bet, now_ts(), uid),
        )
        await log_game(uid, "mines", bet, 0, meta={"mine_positions": sorted(game["mine_positions"]), "hit": mine_idx})
        # Показать поле с минами
        kb = InlineKeyboardBuilder()
        for i in range(25):
            if i in game["mine_positions"]:
                kb.button(text="💥", callback_data="mines:noop")
            elif i == mine_idx:
                kb.button(text="💣", callback_data="mines:noop")
            else:
                kb.button(text="⬜", callback_data="mines:noop")
        kb.adjust(*([5] * 5))
        text = (
            f"💥 <b>Взрыв!</b>\n\n"
            f"Вы наступили на мину в клетке <b>#{mine_idx+1}</b>.\n"
            f"💰 Потеряно: <b>-{fmt_num(bet)} TOKENS</b>"
        )
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup())
        except Exception:  # noqa: BLE001
            await bot.send_message(uid, text, reply_markup=kb.as_markup())
        return

    # Открыли безопасную
    game["opened"].add(idx)
    opened = len(game["opened"])
    max_safe = 25 - game["mines"]
    if opened >= max_safe:
        # Все клетки открыты — авто-выплата
        mult = _mines_multiplier(game["mines"], max_safe)
        win = int(game["bet"] * mult)
        MINES_GAMES.pop(uid, None)
        await credit_win(uid, win, game="mines", meta={"opened": opened, "mult": mult})
        await log_game(uid, "mines", game["bet"], win, meta={"opened": opened, "mult": mult})
        text = (
            f"🏆 <b>Всё поле открыто!</b>\n\n"
            f"🎯 Открыто: <b>{opened}/{max_safe}</b>\n"
            f"📈 Множитель: <b>x{mult:g}</b>\n"
            f"💵 Выигрыш: <b>+{fmt_num(win)} TOKENS</b>"
        )
        try:
            await cb.message.edit_text(text)
        except Exception:  # noqa: BLE001
            await bot.send_message(uid, text)
        return

    mult = _mines_multiplier(game["mines"], opened)
    cashout = int(game["bet"] * mult)
    try:
        await cb.message.edit_reply_markup(
            reply_markup=ikb_mines(game["mines"], game["opened"], cashout),
        )
    except Exception:  # noqa: BLE001
        pass
    # Обновим подпись
    try:
        await cb.message.edit_text(
            f"💣 <b>Мины</b>\n\n"
            f"💰 Ставка: <b>{fmt_num(game['bet'])}</b>\n"
            f"🔓 Открыто: <b>{opened}</b> / {max_safe}\n"
            f"📈 Множитель: <b>x{mult:g}</b>\n"
            f"💵 Забрать: <b>{fmt_num(cashout)}</b>",
            reply_markup=ikb_mines(game["mines"], game["opened"], cashout),
        )
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == "mines:cashout")
async def cb_mines_cashout(cb: CallbackQuery) -> None:
    uid = cb.from_user.id
    game = MINES_GAMES.get(uid)
    if not game:
        try:
            await cb.answer("Нет активной игры", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    opened = len(game["opened"])
    if opened == 0:
        try:
            await cb.answer("Откройте хотя бы одну клетку", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return
    mult = _mines_multiplier(game["mines"], opened)
    win = int(game["bet"] * mult)
    MINES_GAMES.pop(uid, None)
    await credit_win(uid, win, game="mines", meta={"opened": opened, "mult": mult, "cashout": True})
    await log_game(uid, "mines", game["bet"], win, meta={"opened": opened, "mult": mult, "cashout": True})
    try:
        await cb.answer(f"Забрано {fmt_num(win)}")
    except Exception:  # noqa: BLE001
        pass
    try:
        await cb.message.edit_text(
            f"💰 <b>Кэшаут</b>\n\n"
            f"🎯 Открыто: <b>{opened}</b>\n"
            f"📈 Множитель: <b>x{mult:g}</b>\n"
            f"💵 Выигрыш: <b>+{fmt_num(win)} TOKENS</b>"
        )
    except Exception:  # noqa: BLE001
        await bot.send_message(uid, f"💰 Забрано: <b>{fmt_num(win)} TOKENS</b>")


@router.callback_query(F.data == "mines:noop")
async def cb_mines_noop(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass


# =============================================================
# 33. РУЛЕТКА (парсер ставок в чате)
# =============================================================

ROULETTE_TEXT = (
    "🎡 <b>Рулетка</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Как играть:\n"
    "1. Напишите в чате ставку:\n"
    "   • <code>к 1000</code> — на красное\n"
    "   • <code>ч 1000</code> — на чёрное\n"
    "   • <code>10-20 500</code> — на диапазон чисел\n"
    "2. Напишите <code>старт</code> — крупье запустит рулетку.\n\n"
    f"💰 Лимиты: {fmt_num(ROULETTE_MIN)} — {fmt_num(ROULETTE_MAX)} TOKENS\n"
    "🎯 Выплаты: красное/чёрное x2, диапазон x2 (10 чисел)\n"
    "🟢 Зеро — все ставки забирает клуб."
)

ROULETTE_NUMBER_EMOJI = {0: "🟢"}
for _n in range(1, 37):
    ROULETTE_NUMBER_EMOJI[_n] = "🔴" if _n % 2 == 1 else "⚫"


async def _open_roulette_menu(uid: int) -> None:
    await bot.send_message(uid, ROULETTE_TEXT)


@router.message(F.text == "🎡 Рулетка")
async def msg_roulette(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if await is_banned(user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>")
        return
    await ensure_user(user)
    await _open_roulette_menu(user.id)


# Парсер ставок
ROULETTE_BET_RE = re.compile(r"^(к|ч|кр|чёрн|черн|red|black)\s+(\d+)$", re.IGNORECASE)
ROULETTE_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)\s+(\d+)$")


@router.message(F.text.func(lambda t: t and (ROULETTE_BET_RE.match(t.strip()) or ROULETTE_RANGE_RE.match(t.strip()) or t.strip().lower() == "старт")))
async def roulette_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    txt = message.text.strip().lower()
    uid = message.from_user.id
    chat = message.chat

    # ---- СТАРТ ----
    if txt == "старт":
        if chat.id not in ROULETTE_GAMES:
            return
        game = ROULETTE_GAMES[chat.id]
        if game["spinning"]:
            return
        if game["player"] != uid and uid != ADMIN_ID:
            return
        await _spin_roulette(chat.id, message)
        return

    # ---- СТАВКИ ----
    m1 = ROULETTE_BET_RE.match(txt)
    m2 = ROULETTE_RANGE_RE.match(txt)
    if not m1 and not m2:
        return

    if chat.id in ROULETTE_GAMES:
        return  # уже есть активная игра в чате

    if m1:
        side = "red" if m1.group(1).lower() in ("к", "кр", "red") else "black"
        try:
            bet = int(m1.group(2))
        except Exception:  # noqa: BLE001
            return
        bet_type = "color"
        payload = side
    else:
        try:
            lo = int(m2.group(1))
            hi = int(m2.group(2))
            bet = int(m2.group(3))
        except Exception:  # noqa: BLE001
            return
        if lo < 1 or hi > 36 or lo >= hi or hi - lo > 11:
            await message.reply("❗ Диапазон: 1-36, до 12 чисел, lo<hi.")
            return
        bet_type = "range"
        payload = (lo, hi)

    if bet < ROULETTE_MIN or bet > ROULETTE_MAX:
        await message.reply(f"❗ Ставка от {fmt_num(ROULETTE_MIN)} до {fmt_num(ROULETTE_MAX)}.")
        return
    if await is_banned(uid):
        return
    if chat.id in ROULETTE_GAMES:
        return

    ok = await try_debit(uid, bet, kind="bet_roulette", meta={"type": bet_type, "payload": str(payload)})
    if not ok:
        await message.reply(f"❌ Недостаточно средств. Нужно <b>{fmt_num(bet)}</b> TOKENS.")
        return

    ROULETTE_GAMES[chat.id] = {
        "player": uid,
        "bet": bet,
        "type": bet_type,
        "payload": payload,
        "spinning": False,
    }

    label = "🔴 красное" if (bet_type == "color" and payload == "red") else (
        "⚫ чёрное" if bet_type == "color" else f"диапазон {payload[0]}-{payload[1]}"
    )
    await message.reply(
        f"🎡 Ставка принята: <b>{label}</b> на <b>{fmt_num(bet)} TOKENS</b>.\n"
        f"Игрок: <a href='tg://user?id={uid}'>{safe_full_name(message.from_user)}</a>\n\n"
        f"Напишите <code>старт</code>, чтобы запустить.",
        reply_markup=ikb_roulette_bet(chat.id),
    )


@router.callback_query(F.data.startswith("rl:start:"))
async def cb_rl_start(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    chat_id = int(cb.data.split(":")[-1])
    game = ROULETTE_GAMES.get(chat_id)
    if not game:
        await cb.answer("Нет игры", show_alert=True)
        return
    if cb.from_user.id != game["player"] and cb.from_user.id != ADMIN_ID:
        await cb.answer("Только игрок может запустить", show_alert=True)
        return
    await _spin_roulette(chat_id, cb.message)


@router.callback_query(F.data.startswith("rl:cancel:"))
async def cb_rl_cancel(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    chat_id = int(cb.data.split(":")[-1])
    game = ROULETTE_GAMES.pop(chat_id, None)
    if not game:
        return
    if cb.from_user.id != game["player"] and cb.from_user.id != ADMIN_ID:
        ROULETTE_GAMES[chat_id] = game
        return
    await add_balance(game["player"], game["bet"], kind="refund", meta={"game": "roulette"})
    try:
        await cb.message.edit_text(f"🔄 Ставка отменена. Возврат: <b>{fmt_num(game['bet'])} TOKENS</b>")
    except Exception:  # noqa: BLE001
        await bot.send_message(game["player"], f"🔄 Возврат: <b>{fmt_num(game['bet'])} TOKENS</b>")


async def _spin_roulette(chat_id: int, message: Message) -> None:
    game = ROULETTE_GAMES.get(chat_id)
    if not game or game["spinning"]:
        return
    game["spinning"] = True
    player = game["player"]
    bet = game["bet"]
    bet_type = game["type"]
    payload = game["payload"]

    try:
        await message.reply("🎡 <i>Крутим рулетку…</i>")
        await asyncio.sleep(1.2)
        number = random.randint(0, 36)
        emoji = ROULETTE_NUMBER_EMOJI.get(number, "⚫")
        await message.reply(f"🎯 Выпало: {emoji} <b>{number}</b>")
        await asyncio.sleep(0.8)

        win = 0
        if number == 0:
            win = 0
            outcome = "🟢 Зеро — ставки забирает клуб."
        elif bet_type == "color":
            color = "red" if number % 2 == 1 else "black"
            if color == payload:
                win = bet * 2
                outcome = f"✅ {emoji} {payload} — победа!"
            else:
                win = 0
                outcome = f"❌ {emoji} {color} — проигрыш."
        elif bet_type == "range":
            lo, hi = payload
            if lo <= number <= hi:
                win = bet * 2
                outcome = f"✅ Попадание в {lo}-{hi} — победа!"
            else:
                win = 0
                outcome = f"❌ Не попали в {lo}-{hi}."
        else:
            win = 0
            outcome = "—"

        if win > 0:
            await credit_win(player, win, game="roulette", meta={"number": number, "bet_type": bet_type, "payload": str(payload)})
        else:
            await db.execute(
                "UPDATE users SET total_lost = total_lost + ?, updated_at=? WHERE user_id=?",
                (bet, now_ts(), player),
            )
        await log_game(player, "roulette", bet, win, meta={"number": number, "bet_type": bet_type, "payload": str(payload)})

        delta = win - bet
        final = (
            f"🎡 <b>Рулетка завершена</b>\n\n"
            f"🎯 Число: {emoji} <b>{number}</b>\n"
            f"{outcome}\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
            f"📊 Итог: <b>{'+' if delta>=0 else ''}{fmt_num(delta)}</b>"
        )
        await message.reply(final)
    except Exception:  # noqa: BLE001
        log_exc("spin_roulette")
    finally:
        ROULETTE_GAMES.pop(chat_id, None)


# =============================================================
# 34. АДМИН-ПУЛЬТ (20+ КОМАНД)
# =============================================================

def _is_admin(uid: int) -> bool:
    return uid == ADMIN_ID and ADMIN_ID != 0


def _admin_only(func):
    """Декоратор: только для админа."""
    async def wrapper(event: Union[Message, CallbackQuery], *args, **kwargs):
        if not event.from_user or not _is_admin(event.from_user.id):
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("🚫 Доступ запрещён", show_alert=True)
                except Exception:  # noqa: BLE001
                    pass
            else:
                await event.answer("🚫 <b>Доступ запрещён.</b>")
            return
        return await func(event, *args, **kwargs)
    return wrapper


ADMIN_HELP = (
    "🔐 <b>Админ-пульт</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>Балансы:</b>\n"
    "<code>@выдать ID СУММА</code>\n"
    "<code>@дроп ID СУММА</code> — со списанием у вас\n"
    "<code>@обнулить ID</code>\n"
    "<code>@баланс ID</code>\n"
    "<code>@юзер ID</code>\n\n"
    "<b>Модерация:</b>\n"
    "<code>@бан ID [причина]</code>\n"
    "<code>@разбан ID</code>\n"
    "<code>@отключить_игры ID</code>\n"
    "<code>@включить_игры ID</code>\n\n"
    "<b>VIP:</b>\n"
    "<code>@выдать_vip ID ТИР [дней]</code>\n"
    "<code>@снять_vip ID</code>\n\n"
    "<b>Экономика:</b>\n"
    "<code>@изменить_курс N</code>\n"
    "<code>@глобальный_дроп СУММА</code>\n"
    "<code>@отключить_игры_all</code> / <code>@включить_игры_all</code>\n\n"
    "<b>Сервис:</b>\n"
    "<code>@стата</code>\n"
    "<code>@рассылка ТЕКСТ</code>\n"
    "<code>@бекап</code>\n"
    "<code>@рестарт</code>"
)


@admin_router.message(Command("admin"))
@router.message(F.text == "🔐 Админ-пульт")
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(ADMIN_HELP, reply_markup=ikb_admin())


@admin_router.callback_query(F.data == "adm:stats")
async def cb_adm_stats(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    total = await db.fetchval("SELECT COUNT(*) FROM users", (), 0)
    active_24 = await db.fetchval(
        "SELECT COUNT(DISTINCT user_id) FROM game_log WHERE ts > ?",
        (now_ts() - 86400,), 0,
    )
    sum_balance = await db.fetchval("SELECT COALESCE(SUM(balance),0) FROM users", (), 0)
    sum_wagered = await db.fetchval("SELECT COALESCE(SUM(total_wagered),0) FROM users", (), 0)
    games = await db.fetchval("SELECT COUNT(*) FROM game_log", (), 0)
    vip_count = await db.fetchval(
        "SELECT COUNT(*) FROM users WHERE vip_tier != 'none' AND (vip_until IS NULL OR vip_until > ?)",
        (now_ts(),), 0,
    )
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего юзеров: <b>{fmt_num(total)}</b>\n"
        f"🟢 Активных 24ч: <b>{fmt_num(active_24)}</b>\n"
        f"👑 VIP: <b>{fmt_num(vip_count)}</b>\n\n"
        f"💰 Сумма балансов: <b>{fmt_num(sum_balance)}</b>\n"
        f"🎮 Оборот ставок: <b>{fmt_num(sum_wagered)}</b>\n"
        f"🎲 Игр сыграно: <b>{fmt_num(games)}</b>"
    )
    try:
        await cb.message.edit_text(text, reply_markup=ikb_admin())
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, reply_markup=ikb_admin())


@admin_router.callback_query(F.data == "adm:rate")
async def cb_adm_rate(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(AdminStates.waiting_rate)
    await bot.send_message(
        cb.from_user.id,
        f"⚙️ Текущий курс: <b>{fmt_num(STAR_RATE)}</b> TOKENS за 1 ⭐\n\n"
        f"Введите новый курс (число):",
    )


@admin_router.message(AdminStates.waiting_rate, F.text)
async def fsm_admin_rate(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    global STAR_RATE
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❗ Введите положительное число.")
        return
    STAR_RATE = int(txt)
    await state.clear()
    await message.answer(f"✅ Новый курс: <b>{fmt_num(STAR_RATE)}</b> TOKENS за 1 ⭐")


@admin_router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(AdminBroadcastStates.waiting_text)
    await bot.send_message(
        cb.from_user.id,
        "📢 <b>Рассылка</b>\n\nОтправьте текст сообщения (HTML разрешён).\n\nОтмена — /cancel",
    )


@admin_router.message(AdminBroadcastStates.waiting_text, F.text)
async def fsm_admin_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    text = message.text
    await state.clear()
    rows = await db.fetchall("SELECT user_id FROM users WHERE banned=0")
    sent = 0
    failed = 0
    status_msg = await message.answer(f"📢 Отправляю… 0/{len(rows)}")
    for i, r in enumerate(rows):
        try:
            await bot.send_message(r["user_id"], text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        if (i + 1) % 25 == 0:
            try:
                await status_msg.edit_text(f"📢 Отправляю… {i+1}/{len(rows)}")
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.03)
    try:
        await status_msg.edit_text(
            f"📢 <b>Рассылка завершена</b>\n✅ Доставлено: <b>{sent}</b>\n❌ Ошибок: <b>{failed}</b>"
        )
    except Exception:  # noqa: BLE001
        await message.answer(f"✅ Доставлено: {sent}, ❌ Ошибок: {failed}")


@admin_router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer("Создаю бекап…")
    except Exception:  # noqa: BLE001
        pass
    try:
        if db.conn:
            await db.conn.commit()
        if os.path.exists(DB_PATH):
            doc = FSInputFile(DB_PATH, filename=f"backup_{now_ts()}.db")
            await bot.send_document(cb.from_user.id, doc, caption=f"💾 Бекап БД {now_utc().strftime('%Y-%m-%d %H:%M')}")
        else:
            await bot.send_message(cb.from_user.id, "⚠️ Файл БД не найден.")
    except Exception:  # noqa: BLE001
        log_exc("backup")
        await bot.send_message(cb.from_user.id, "⚠️ Ошибка бекапа.")


@admin_router.callback_query(F.data == "adm:restart")
async def cb_adm_restart(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer("Перезапуск…", show_alert=True)
    except Exception:  # noqa: BLE001
        pass
    await bot.send_message(cb.from_user.id, "🔄 <b>Рестарт через 2 сек…</b>")
    await asyncio.sleep(2)
    try:
        await db.close()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


@admin_router.callback_query(F.data == "adm:gdrop")
async def cb_adm_gdrop(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        return
    try:
        await cb.answer()
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(AdminStates.waiting_amount)
    await state.update_data(action="gdrop")
    await bot.send_message(cb.from_user.id, "💥 Введите сумму глобального дропа (каждому юзеру):")


@admin_router.callback_query(F.data == "adm:toggle_games")
async def cb_adm_toggle_games(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        return
    global GAMES_DISABLED
    GAMES_DISABLED = not GAMES_DISABLED
    try:
        await cb.answer(f"Игры: {'OFF' if GAMES_DISABLED else 'ON'}")
    except Exception:  # noqa: BLE001
        pass
    await bot.send_message(
        cb.from_user.id,
        f"🕹 Игры: <b>{'ОТКЛЮЧЕНЫ' if GAMES_DISABLED else 'ВКЛЮЧЕНЫ'}</b>",
    )


@admin_router.message(AdminStates.waiting_amount, F.text)
async def fsm_admin_amount(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    action = data.get("action")
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("❗ Введите число.")
        return
    amount = int(txt)
    await state.clear()
    if action == "gdrop":
        rows = await db.fetchall("SELECT user_id FROM users WHERE banned=0")
        for r in rows:
            await add_balance(r["user_id"], amount, kind="gdrop", meta={"by": message.from_user.id})
            try:
                await bot.send_message(r["user_id"], f"💥 <b>Глобальный дроп!</b>\n+{fmt_mono(amount)} TOKENS")
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.03)
        await message.answer(f"✅ Дроп {fmt_num(amount)} выдан {len(rows)} юзерам.")


# =============================================================
# 35. ТЕКСТОВЫЕ АДМИН-КОМАНДЫ (@...)
# =============================================================

async def _parse_id_amount(args: List[str]) -> Optional[Tuple[int, int]]:
    if len(args) < 2:
        return None
    try:
        return int(args[0]), int(args[1])
    except Exception:  # noqa: BLE001
        return None


@admin_router.message(F.text.startswith("@выдать"))
async def adm_give(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()[1:]
    pair = await _parse_id_amount(parts)
    if not pair:
        await message.answer("❗ Формат: <code>@выдать ID СУММА</code>")
        return
    uid, amount = pair
    if amount <= 0:
        await message.answer("❗ Сумма > 0.")
        return
    await ensure_user_by_id(uid)
    await add_balance(uid, amount, kind="admin_give", meta={"by": message.from_user.id})
    await message.answer(f"✅ Выдано <b>{fmt_mono(amount)}</b> юзеру <code>{uid}</code>.")
    try:
        await bot.send_message(uid, f"🎁 Вам начислено <b>{fmt_mono(amount)} TOKENS</b>.")
    except Exception:  # noqa: BLE001
        pass


@admin_router.message(F.text.startswith("@дроп"))
async def adm_drop(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()[1:]
    pair = await _parse_id_amount(parts)
    if not pair:
        await message.answer("❗ Формат: <code>@дроп ID СУММА</code>")
        return
    uid, amount = pair
    if amount <= 0:
        await message.answer("❗ Сумма > 0.")
        return
    if not await try_debit(message.from_user.id, amount, kind="admin_drop"):
        await message.answer("❌ Недостаточно средств у вас.")
        return
    await ensure_user_by_id(uid)
    await add_balance(uid, amount, kind="admin_drop", meta={"by": message.from_user.id})
    await message.answer(f"✅ Дропнуто <b>{fmt_mono(amount)}</b> юзеру <code>{uid}</code>.")


@admin_router.message(F.text.startswith("@обнулить"))
async def adm_zero(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("❗ Формат: <code>@обнулить ID</code>")
        return
    uid = int(parts[0])
    await db.execute("UPDATE users SET balance=0, updated_at=? WHERE user_id=?", (now_ts(), uid))
    await message.answer(f"✅ Баланс <code>{uid}</code> обнулён.")


@admin_router.message(F.text.startswith("@баланс"))
async def adm_balance(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("❗ Формат: <code>@баланс ID</code>")
        return
    uid = int(parts[0])
    bal = await get_balance(uid)
    await message.answer(f"💰 Баланс <code>{uid}</code>: <b>{fmt_mono(bal)}</b> TOKENS")


@admin_router.message(F.text.startswith("@юзер"))
async def adm_user(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("❗ Формат: <code>@юзер ID</code>")
        return
    uid = int(parts[0])
    row = await get_user(uid)
    if not row:
        await message.answer("Юзер не найден.")
        return
    partners = await count_partners(uid)
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 <code>{row['user_id']}</code>\n"
        f"👤 {row['full_name']} (@{row['username'] or '—'})\n"
        f"💰 Баланс: <b>{fmt_mono(row['balance'])}</b>\n"
        f"🎖 VIP: <b>{row['vip_tier']}</b>\n"
        f"🚫 Бан: <b>{'да' if row['banned'] else 'нет'}</b>\n"
        f"🤝 Партнёров: <b>{partners}</b>\n"
        f"🎮 Ставок: <b>{fmt_num(row['total_wagered'] or 0)}</b>\n"
        f"✅ Выигрыш: <b>{fmt_num(row['total_won'] or 0)}</b>\n"
        f"❌ Проигрыш: <b>{fmt_num(row['total_lost'] or 0)}</b>"
    )
    await message.answer(text)


@admin_router.message(F.text.startswith("@бан"))
async def adm_ban(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@бан ID [причина]</code>")
        return
    uid = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts) > 2 else "Нарушение правил"
    await ensure_user_by_id(uid)
    await set_ban(uid, True, reason)
    await message.answer(f"🚫 Забанен <code>{uid}</code>: {reason}")
    try:
        await bot.send_message(uid, f"🚫 <b>Вы забанены.</b>\nПричина: {reason}")
    except Exception:  # noqa: BLE001
        pass


@admin_router.message(F.text.startswith("@разбан"))
async def adm_unban(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@разбан ID</code>")
        return
    uid = int(parts[1])
    await set_ban(uid, False)
    await message.answer(f"✅ Разбанен <code>{uid}</code>.")
    try:
        await bot.send_message(uid, "✅ <b>Вы разбанены.</b>\nДобро пожаловать!")
    except Exception:  # noqa: BLE001
        pass


@admin_router.message(F.text.startswith("@отключить_игры_all"))
async def adm_games_off_all(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    global GAMES_DISABLED
    GAMES_DISABLED = True
    await message.answer("🕹 <b>Игры отключены для всех.</b>")


@admin_router.message(F.text.startswith("@включить_игры_all"))
async def adm_games_on_all(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    global GAMES_DISABLED
    GAMES_DISABLED = False
    await message.answer("🕹 <b>Игры включены для всех.</b>")


@admin_router.message(F.text.startswith("@отключить_игры"))
async def adm_games_off_user(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@отключить_игры ID</code>")
        return
    uid = int(parts[1])
    await db.execute("UPDATE users SET games_disabled=1, updated_at=? WHERE user_id=?", (now_ts(), uid))
    await message.answer(f"🕹 Игры отключены для <code>{uid}</code>.")


@admin_router.message(F.text.startswith("@включить_игры"))
async def adm_games_on_user(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@включить_игры ID</code>")
        return
    uid = int(parts[1])
    await db.execute("UPDATE users SET games_disabled=0, updated_at=? WHERE user_id=?", (now_ts(), uid))
    await message.answer(f"🕹 Игры включены для <code>{uid}</code>.")


@admin_router.message(F.text.startswith("@выдать_vip"))
async def adm_give_vip(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@выдать_vip ID ТИР [дней]</code>\nТиры: silver, gold, platinum, black")
        return
    uid = int(parts[1])
    tier = parts[2].lower()
    days = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 30
    if tier not in VIP_TIERS or tier == "none":
        await message.answer("❗ Неверный тир.")
        return
    await ensure_user_by_id(uid)
    until = now_ts() + days * 86400
    await set_vip(uid, tier, until)
    await message.answer(f"👑 VIP <b>{tier}</b> выдан <code>{uid}</code> на {days} дн.")
    try:
        await bot.send_message(uid, f"👑 <b>Вам выдан VIP {tier}!</b>\nДо: {fmt_dt(datetime.fromtimestamp(until, TZ))}")
    except Exception:  # noqa: BLE001
        pass


@admin_router.message(F.text.startswith("@снять_vip"))
async def adm_remove_vip(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@снять_vip ID</code>")
        return
    uid = int(parts[1])
    await set_vip(uid, "none", None)
    await message.answer(f"✅ VIP снят с <code>{uid}</code>.")


@admin_router.message(F.text.startswith("@изменить_курс"))
async def adm_change_rate(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer("❗ Формат: <code>@изменить_курс N</code>")
        return
    global STAR_RATE
    STAR_RATE = int(parts[1])
    await message.answer(f"✅ Курс: <b>{fmt_num(STAR_RATE)}</b> TOKENS за 1 ⭐")


@admin_router.message(F.text.startswith("@глобальный_дроп"))
async def adm_global_drop(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("❗ Формат: <code>@глобальный_дроп СУММА</code>")
        return
    amount = int(parts[1])
    if amount <= 0:
        await message.answer("❗ Сумма > 0.")
        return
    rows = await db.fetchall("SELECT user_id FROM users WHERE banned=0")
    for r in rows:
        await add_balance(r["user_id"], amount, kind="gdrop", meta={"by": message.from_user.id})
        try:
            await bot.send_message(r["user_id"], f"💥 <b>Глобальный дроп!</b>\n+{fmt_mono(amount)} TOKENS")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.03)
    await message.answer(f"✅ Дроп {fmt_num(amount)} выдан {len(rows)} юзерам.")


@admin_router.message(F.text.startswith("@стата"))
async def adm_stats(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    total = await db.fetchval("SELECT COUNT(*) FROM users", (), 0)
    active_24 = await db.fetchval(
        "SELECT COUNT(DISTINCT user_id) FROM game_log WHERE ts > ?",
        (now_ts() - 86400,), 0,
    )
    sum_balance = await db.fetchval("SELECT COALESCE(SUM(balance),0) FROM users", (), 0)
    games = await db.fetchval("SELECT COUNT(*) FROM game_log", (), 0)
    text = (
        f"📊 <b>Статистика</b>\n"
        f"👥 Юзеров: <b>{fmt_num(total)}</b>\n"
        f"🟢 Активных 24ч: <b>{fmt_num(active_24)}</b>\n"
        f"💰 Сумма балансов: <b>{fmt_num(sum_balance)}</b>\n"
        f"🎲 Игр: <b>{fmt_num(games)}</b>\n"
        f"⚙️ Курс: <b>{fmt_num(STAR_RATE)}</b>"
    )
    await message.answer(text)


@admin_router.message(F.text.startswith("@рассылка"))
async def adm_broadcast_cmd(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = (message.text or "")[len("@рассылка"):].strip()
    if not text:
        await message.answer("❗ Формат: <code>@рассылка ТЕКСТ</code>")
        return
    rows = await db.fetchall("SELECT user_id FROM users WHERE banned=0")
    sent, failed = 0, 0
    for r in rows:
        try:
            await bot.send_message(r["user_id"], text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.03)
    await message.answer(f"📢 Доставлено: {sent}, ошибок: {failed}")


@admin_router.message(F.text.startswith("@бекап"))
async def adm_backup_cmd(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        if db.conn:
            await db.conn.commit()
        if os.path.exists(DB_PATH):
            doc = FSInputFile(DB_PATH, filename=f"backup_{now_ts()}.db")
            await bot.send_document(message.from_user.id, doc, caption="💾 Бекап БД")
        else:
            await message.answer("⚠️ Файл БД не найден.")
    except Exception:  # noqa: BLE001
        log_exc("backup_cmd")
        await message.answer("⚠️ Ошибка бекапа.")


@admin_router.message(F.text.startswith("@рестарт"))
async def adm_restart_cmd(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer("🔄 <b>Рестарт через 2 сек…</b>")
    await asyncio.sleep(2)
    try:
        await db.close()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)

# =============================================================
# ЧАСТЬ 6: ФИНАЛ — SCHEDULER, MAIN, ЗАПУСК
# =============================================================

# =============================================================
# 36. SCHEDULER-ЗАДАЧИ
# =============================================================

async def _job_finalize_season() -> None:
    """Каждую ночь проверяем: если сезон истёк — закрываем и создаём новый."""
    try:
        await finalize_season()
    except Exception:  # noqa: BLE001
        log_exc("job_finalize_season")


async def _job_cleanup_expired() -> None:
    """Очистка: просроченные VIP, старые дуэли, зависшие мины, старые логи."""
    now = now_ts()
    try:
        # 1) Просроченный VIP
        await db.execute(
            "UPDATE users SET vip_tier='none', vip_until=NULL, updated_at=? "
            "WHERE vip_tier != 'none' AND vip_until IS NOT NULL AND vip_until <= ?",
            (now, now),
        )
        # 2) Зависшие дуэли (старше 30 минут) — вернуть ставки
        for did in list(DUELS.keys()):
            d = DUELS.get(did)
            if not d:
                continue
            if d["status"] == "waiting" and (now - d["created"]) > 1800:
                try:
                    await add_balance(d["creator"], d["bet"], kind="refund",
                                      meta={"game": "duel", "duel_id": did, "reason": "timeout"})
                except Exception:  # noqa: BLE001
                    pass
                DUELS.pop(did, None)
        # 3) Зависшие мины (старше 60 минут) — вернуть ставку
        for uid in list(MINES_GAMES.keys()):
            g = MINES_GAMES.get(uid)
            if not g:
                continue
            if (now - g["started"]) > 3600 and not g["opened"]:
                try:
                    await add_balance(uid, g["bet"], kind="refund",
                                      meta={"game": "mines", "reason": "timeout"})
                except Exception:  # noqa: BLE001
                    pass
                MINES_GAMES.pop(uid, None)
        # 4) Старые рулетки (старше 10 минут) — вернуть
        for chat_id in list(ROULETTE_GAMES.keys()):
            g = ROULETTE_GAMES.get(chat_id)
            if not g or g.get("spinning"):
                continue
            try:
                await add_balance(g["player"], g["bet"], kind="refund",
                                  meta={"game": "roulette", "reason": "timeout"})
            except Exception:  # noqa: BLE001
                pass
            ROULETTE_GAMES.pop(chat_id, None)
        # 5) Логи старше 90 дней
        await db.execute("DELETE FROM game_log WHERE ts < ?", (now - 90 * 86400,))
        await db.execute("DELETE FROM transactions WHERE ts < ?", (now - 180 * 86400,))
    except Exception:  # noqa: BLE001
        log_exc("job_cleanup_expired")


async def _job_daily_ping() -> None:
    """Раз в сутки — обновление топ-сезона (кэш) + лог."""
    try:
        season = await get_active_season()
        if not season:
            return
        if season["ends_at"] <= now_ts():
            await finalize_season()
            return
        top = await db.fetchall(
            "SELECT user_id, net_win FROM tournaments WHERE season_id=? AND net_win>0 "
            "ORDER BY net_win DESC LIMIT 3",
            (season["id"],),
        )
        log.info("Scheduler: season top-3 refreshed (%d entries)", len(top))
    except Exception:  # noqa: BLE001
        log_exc("job_daily_ping")


def setup_scheduler() -> None:
    """Переопределяем заглушку из Части 1."""
    global scheduler
    if not APSCHEDULER_OK:
        log.warning("APScheduler недоступен — периодические задачи отключены.")
        return
    try:
        scheduler = AsyncIOScheduler(timezone=TZ)
        # Закрытие сезона — каждый час (быстрая реакция на истёкший срок)
        scheduler.add_job(_job_finalize_season, IntervalTrigger(hours=1),
                          id="finalize_season", replace_existing=True)
        # Очистка — каждые 15 минут
        scheduler.add_job(_job_cleanup_expired, IntervalTrigger(minutes=15),
                          id="cleanup_expired", replace_existing=True)
        # Ежедневный пинг/обновление топа — каждый день в 03:00 UTC
        scheduler.add_job(_job_daily_ping, CronTrigger(hour=3, minute=0),
                          id="daily_ping", replace_existing=True)
        scheduler.start()
        log.info("Scheduler started: finalize_season(1h), cleanup(15m), daily_ping(03:00 UTC)")
    except Exception:  # noqa: BLE001
        log_exc("setup_scheduler")


# Переопределение заглушки Части 1
def setup_scheduler_stub() -> None:
    setup_scheduler()


# =============================================================
# 37. POST_INIT (переопределение заглушки)
# =============================================================

async def post_init_hook() -> None:
    global BOT_USERNAME_CACHE
    try:
        me = await bot.get_me()
        BOT_USERNAME_CACHE = me.username
        log.info("Bot @%s (id=%s) ready.", me.username, me.id)
    except Exception:  # noqa: BLE001
        log_exc("post_init: get_me")
        BOT_USERNAME_CACHE = "bot"

    # Проверим наличие ассетов
    for path, label in (
        (PROFILE_BG_PATH, "profile_bg.jpg"),
        (NO_AVATAR_PATH, "no_avatar.png"),
        (FONT_BOLD_PATH, "Montserrat-Bold.ttf"),
        (FONT_REG_PATH, "Montserrat-Regular.ttf"),
    ):
        if os.path.exists(path):
            log.info("Assets OK: %s", label)
        else:
            log.warning("Assets MISSING: %s — будет использован fallback.", label)


# =============================================================
# 38. ФИНАЛЬНЫЙ main() (переопределяет заглушку Части 1)
# =============================================================

async def main() -> None:
    log.info("=== TOKENS | PRIVATE CLUB : BOOT ===")
    log.info("PORT=%s DB_PATH=%s ADMIN_ID=%s", PORT, DB_PATH, ADMIN_ID)

    # 1) База данных (WAL)
    await init_db()

    # 2) Бот и диспетчер
    build_bot()
    build_dispatcher()

    # 3) Веб-сервер (Render health-check)
    web_runner = await start_web_server()

    # 4) Хук инициализации (username, ассеты)
    await post_init_hook()

    # 5) Команды меню
    await setup_bot_commands()

    # 6) Scheduler (APScheduler задачи)
    setup_scheduler()

    # 7) Сброс webhook
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:  # noqa: BLE001
        log_exc("delete_webhook")

    # 8) Polling
    log.info("=== START POLLING ===")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=False,
        )
    except Exception:  # noqa: BLE001
        log_exc("polling FATAL")
    finally:
        log.info("=== STOP POLLING ===")
        if scheduler:
            try:
                scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        try:
            await web_runner.cleanup()
        except Exception:  # noqa: BLE001
            pass
        await db.close()
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            pass


# =============================================================
# 39. ENTRY POINT
# =============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutdown requested.")
    except Exception:  # noqa: BLE001
        log_exc("FATAL")
        sys.exit(1)