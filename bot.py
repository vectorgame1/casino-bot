# ==============================================================
# TOKENS | PRIVATE CLUB
# Monolithic Telegram Bot
# Python 3.11+ | aiogram 3.x | aiosqlite | Pillow
# APScheduler | aiohttp
#
# Install:
# pip install aiogram aiosqlite Pillow APScheduler aiohttp
#
# Environment:
# BOT_TOKEN=your_bot_token
# ADMIN_ID=123456789
# SUPPORT_URL=https://t.me/your_support
# CLUB_CHAT_URL=https://t.me/your_chat
#
# Run:
# python bot.py
# ==============================================================

# ============================ IMPORTS ==========================

import asyncio
import html
import io
import logging
import os
import random
import secrets
import shutil
import time

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
)

from aiogram import (
    Bot,
    Dispatcher,
    Router,
    F,
)

from aiogram.enums import ParseMode

from aiogram.client.default import DefaultBotProperties

from aiogram.filters import (
    Command,
    CommandStart,
)

from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiohttp import web


# ============================ CONFIG ===========================

BASE_DIR = Path(__file__).resolve().parent

ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"

for folder in (
    ASSETS_DIR,
    DATA_DIR,
    LOG_DIR,
    BACKUP_DIR,
):
    folder.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PORT = int(os.getenv("PORT", "8080"))

DB_PATH = os.getenv(
    "DB_PATH",
    str(DATA_DIR / "tokens_club.db")
)

SUPPORT_URL = os.getenv(
    "SUPPORT_URL",
    "https://t.me/"
)

CLUB_CHAT_URL = os.getenv(
    "CLUB_CHAT_URL",
    "https://t.me/"
)

BOT_NAME = "TOKENS | PRIVATE CLUB"

VERSION = "5.0.0"

DAILY_BONUS = 5000

DAILY_INTERVAL = 86400

MAX_REWARD = 10000

MAX_BALANCE = 10**12

UTC = timezone.utc

PROFILE_BACKGROUND = ASSETS_DIR / "profile.jpg"

PROFILE_FONT = ASSETS_DIR / "Montserrat-Bold.ttf"


# ============================ LOGGING ==========================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / "bot.log",
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger("TOKENS")


# ============================ TEXTS ============================

TEXTS = {
    "RU": {
        "welcome": (
            "<b>TOKENS | PRIVATE CLUB</b>\n\n"
            "Добро пожаловать, <b>{name}</b>.\n\n"
            "Ваше пространство для общения, "
            "интеллектуальных активностей и достижений.\n\n"
            "Баланс: <code>{balance}</code>\n"
            "Ранг: <b>{rank}</b>"
        ),
        "menu": "Выберите раздел клуба.",
        "profile": "ВАШ ПРОФИЛЬ",
        "bonus_success": (
            "Ежедневная награда получена: "
            "<code>+{amount}</code> очков."
        ),
        "bonus_wait": (
            "Следующая награда будет доступна через "
            "<b>{time}</b>."
        ),
        "not_registered": "Сначала зарегистрируйтесь через /start.",
        "banned": "Доступ к клубу ограничен.",
        "captcha": (
            "Для подтверждения регистрации нажмите кнопку ниже."
        ),
        "captcha_question": (
            "Введите число, которое показано ниже:\n\n"
            "<b>{number}</b>"
        ),
        "captcha_ok": (
            "Проверка пройдена. Добро пожаловать в клуб."
        ),
        "captcha_wrong": (
            "Ответ неверный. Попробуйте ещё раз."
        ),
        "games": (
            "<b>АКТИВНОСТИ</b>\n\n"
            "Выберите бесплатную активность:\n"
            "• Викторина\n"
            "• Развлекательный бросок кубика\n\n"
            "Активности не требуют взносов и не уменьшают баланс."
        ),
        "support": "Раздел поддержки клуба.",
        "chats": "Сообщество TOKENS | PRIVATE CLUB.",
        "donate": (
            "<b>ПОДДЕРЖКА КЛУБА</b>\n\n"
            "В этом разделе размещается информация о сообществе. "
            "Клубные очки выдаются бесплатно и не являются "
            "денежными средствами."
        ),
        "language": "Выберите язык интерфейса.",
        "language_changed": "Язык интерфейса изменён.",
        "unknown": "Неизвестная команда. Используйте меню или /help.",
    },
    "EN": {
        "welcome": (
            "<b>TOKENS | PRIVATE CLUB</b>\n\n"
            "Welcome, <b>{name}</b>.\n\n"
            "Your space for community, "
            "knowledge activities and achievements.\n\n"
            "Balance: <code>{balance}</code>\n"
            "Rank: <b>{rank}</b>"
        ),
        "menu": "Choose a club section.",
        "profile": "YOUR PROFILE",
        "bonus_success": (
            "Daily reward received: "
            "<code>+{amount}</code> points."
        ),
        "bonus_wait": (
            "Your next reward will be available in "
            "<b>{time}</b>."
        ),
        "not_registered": "Please register first using /start.",
        "banned": "Access to the club is restricted.",
        "captcha": "Press the button below to verify your registration.",
        "captcha_question": (
            "Enter the number shown below:\n\n"
            "<b>{number}</b>"
        ),
        "captcha_ok": "Verification completed. Welcome to the club.",
        "captcha_wrong": "Incorrect answer. Please try again.",
        "games": (
            "<b>ACTIVITIES</b>\n\n"
            "Choose a free activity:\n"
            "• Quiz\n"
            "• Entertainment dice roll\n\n"
            "Activities require no contributions and do not reduce balance."
        ),
        "support": "Club support.",
        "chats": "TOKENS | PRIVATE CLUB community.",
        "donate": (
            "<b>SUPPORT THE CLUB</b>\n\n"
            "This section contains community information. "
            "Club points are free and have no monetary value."
        ),
        "language": "Choose interface language.",
        "language_changed": "Interface language changed.",
        "unknown": "Unknown command. Use the menu or /help.",
    },
}


# ============================ CONSTANTS ========================

RANKS = [
    (0, "MEMBER"),
    (10000, "BRONZE"),
    (50000, "SILVER"),
    (150000, "GOLD"),
    (500000, "PLATINUM"),
    (1000000, "DIAMOND"),
    (5000000, "ELITE"),
]

REWARD_TYPES = {
    "DAILY_BONUS",
    "QUIZ_REWARD",
    "REFERRAL_REWARD",
    "ADMIN_REWARD",
    "EVENT_REWARD",
    "ACHIEVEMENT",
}

ASSETS = {
    "start": ASSETS_DIR / "start.jpg",
    "profile": PROFILE_BACKGROUND,
    "donate": ASSETS_DIR / "donate.jpg",
    "bonus": ASSETS_DIR / "bonus.jpg",
    "top": ASSETS_DIR / "top.jpg",
    "ref": ASSETS_DIR / "ref.jpg",
    "how_to_play": ASSETS_DIR / "how_to_play.jpg",
    "support": ASSETS_DIR / "support.jpg",
    "chats": ASSETS_DIR / "chats.jpg",
    "commands": ASSETS_DIR / "commands.jpg",
}

QUIZ_QUESTIONS = [
    {
        "q": "Сколько будет 12 × 8?",
        "a": ["86", "96", "108", "112"],
        "correct": 1,
    },
    {
        "q": "Какая планета ближе всего к Солнцу?",
        "a": ["Венера", "Земля", "Меркурий", "Марс"],
        "correct": 2,
    },
    {
        "q": "Сколько сторон у шестиугольника?",
        "a": ["5", "6", "7", "8"],
        "correct": 1,
    },
    {
        "q": "Какой язык используется для этого бота?",
        "a": ["Python", "Java", "C++", "PHP"],
        "correct": 0,
    },
    {
        "q": "Сколько минут в двух часах?",
        "a": ["100", "110", "120", "140"],
        "correct": 2,
    },
    {
        "q": "Столица Германии?",
        "a": ["Мюнхен", "Берлин", "Гамбург", "Бонн"],
        "correct": 1,
    },
    {
        "q": "Какое число простое?",
        "a": ["9", "15", "17", "21"],
        "correct": 2,
    },
    {
        "q": "Сколько дней в високосном году?",
        "a": ["364", "365", "366", "367"],
        "correct": 2,
    },
]


# ============================ HELPERS ==========================

def ts() -> int:
    return int(time.time())


def fmt(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def rank_for(balance: int) -> str:
    rank = "MEMBER"

    for threshold, name in RANKS:
        if balance >= threshold:
            rank = name

    return rank


def esc(value) -> str:
    return html.escape(str(value or ""))


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def human_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)

    if hours:
        return f"{hours} ч. {minutes} мин."

    if minutes:
        return f"{minutes} мин."

    return f"{seconds} сек."


def get_text(language: str, key: str, **kwargs) -> str:
    language = language if language in TEXTS else "RU"
    return TEXTS[language][key].format(**kwargs)


def admin(user_id: int) -> bool:
    return ADMIN_ID > 0 and user_id == ADMIN_ID


def parse_ref(payload: Optional[str]):
    if not payload or not payload.startswith("ref_"):
        return None

    value = safe_int(payload[4:], 0)

    return value if value > 0 else None


def user_lock(user_id: int):
    if user_id not in USER_ACTION_LOCKS:
        USER_ACTION_LOCKS[user_id] = asyncio.Lock()

    return USER_ACTION_LOCKS[user_id]


# ============================ DATABASE =========================

class Database:

    def __init__(self, path: str):
        self.path = str(path)
        self.lock = asyncio.Lock()
        self.cache = {}
        self.cache_at = {}

    async def connect(self):

        Path(self.path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        async with aiosqlite.connect(
            self.path,
            timeout=30,
        ) as conn:

            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=30000")

            await conn.executescript("""

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0,
                rank TEXT NOT NULL DEFAULT 'MEMBER',
                partner_id INTEGER,
                partners_count INTEGER NOT NULL DEFAULT 0,
                is_vip INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT 'RU',
                is_verified INTEGER NOT NULL DEFAULT 0,
                captcha_answer INTEGER,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                daily_bonus_at INTEGER NOT NULL DEFAULT 0,
                total_earned INTEGER NOT NULL DEFAULT 0,
                quiz_correct INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                result TEXT NOT NULL,
                points INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_bonus (
                user_id INTEGER PRIMARY KEY,
                last_claim INTEGER NOT NULL DEFAULT 0,
                total_claims INTEGER NOT NULL DEFAULT 0,
                total_received INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_id INTEGER,
                details TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_balance
            ON users(balance DESC);

            CREATE INDEX IF NOT EXISTS idx_game_user
            ON game_log(user_id);

            CREATE INDEX IF NOT EXISTS idx_game_time
            ON game_log(created_at);

            CREATE INDEX IF NOT EXISTS idx_transactions_user
            ON transactions(user_id);

            """)

            # Мягкая миграция старых версий БД.
            async with conn.execute(
                "PRAGMA table_info(users)"
            ) as cursor:
                columns = {
                    row[1] for row in await cursor.fetchall()
                }

            migrations = {
                "is_vip": "INTEGER NOT NULL DEFAULT 0",
                "language": "TEXT NOT NULL DEFAULT 'RU'",
                "is_verified": "INTEGER NOT NULL DEFAULT 0",
                "captcha_answer": "INTEGER",
                "quiz_correct": "INTEGER NOT NULL DEFAULT 0",
            }

            for column, definition in migrations.items():
                if column not in columns:
                    await conn.execute(
                        f"ALTER TABLE users ADD COLUMN {column} {definition}"
                    )

            defaults = {
                "maintenance": "0",
                "registration_enabled": "1",
                "happy_hour": "0",
                "auto_drop_enabled": "0",
                "auto_drop_amount": "1000",
            }

            for key, value in defaults.items():
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO settings
                    (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, ts()),
                )

            await conn.commit()

        logger.info("Database ready")

    def invalidate(self, user_id: int):
        self.cache.pop(user_id, None)
        self.cache_at.pop(user_id, None)

    async def get_user(self, user_id: int):

        cached = self.cache.get(user_id)

        if cached and time.monotonic() - self.cache_at.get(
            user_id, 0
        ) < 5:
            return cached.copy()

        async with aiosqlite.connect(self.path) as conn:

            conn.row_factory = aiosqlite.Row

            async with conn.execute(
                "SELECT * FROM users WHERE user_id=?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            return None

        result = dict(row)

        self.cache[user_id] = result.copy()
        self.cache_at[user_id] = time.monotonic()

        return result

    async def ensure_user(
        self,
        user_id: int,
        username: Optional[str],
        full_name: str,
        partner_id: Optional[int] = None,
    ):

        current = ts()

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30,
            ) as conn:

                await conn.execute("BEGIN TRANSACTION")

                try:

                    async with conn.execute(
                        "SELECT user_id FROM users WHERE user_id=?",
                        (user_id,),
                    ) as cursor:
                        existing = await cursor.fetchone()

                    if existing:

                        await conn.execute(
                            """
                            UPDATE users
                            SET username=?,
                                full_name=?,
                                last_seen=?
                            WHERE user_id=?
                            """,
                            (
                                username,
                                full_name[:128],
                                current,
                                user_id,
                            ),
                        )

                    else:

                        valid_partner = None

                        if partner_id and partner_id != user_id:

                            async with conn.execute(
                                """
                                SELECT user_id FROM users
                                WHERE user_id=? AND is_banned=0
                                """,
                                (partner_id,),
                            ) as cursor:
                                partner = await cursor.fetchone()

                            if partner:
                                valid_partner = partner_id

                        await conn.execute(
                            """
                            INSERT INTO users (
                                user_id, username, full_name,
                                partner_id, created_at, last_seen
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                username,
                                full_name[:128],
                                valid_partner,
                                current,
                                current,
                            ),
                        )

                        if valid_partner:
                            await conn.execute(
                                """
                                UPDATE users
                                SET partners_count=partners_count+1
                                WHERE user_id=?
                                """,
                                (valid_partner,),
                            )

                    await conn.commit()

                except Exception:
                    await conn.rollback()
                    raise

        self.invalidate(user_id)

        if partner_id:
            self.invalidate(partner_id)

        return await self.get_user(user_id)

    async def change_balance(
        self,
        user_id: int,
        amount: int,
        description: str,
        transaction_type: str = "EVENT_REWARD",
    ) -> bool:
        """
        Безопасное начисление бесплатных клубных очков.
        Отрицательные изменения и списания не поддерживаются.
        """

        if amount <= 0 or amount > MAX_REWARD:
            return False

        if transaction_type not in REWARD_TYPES:
            return False

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30,
            ) as conn:

                await conn.execute("BEGIN TRANSACTION")

                try:

                    async with conn.execute(
                        """
                        SELECT balance, is_banned
                        FROM users WHERE user_id=?
                        """,
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if not row or row[1]:
                        await conn.rollback()
                        return False

                    balance = row[0]

                    if balance + amount > MAX_BALANCE:
                        await conn.rollback()
                        return False

                    new_balance = balance + amount

                    await conn.execute(
                        """
                        UPDATE users
                        SET balance=?,
                            rank=?,
                            total_earned=total_earned+?
                        WHERE user_id=?
                        """,
                        (
                            new_balance,
                            rank_for(new_balance),
                            amount,
                            user_id,
                        ),
                    )

                    await conn.execute(
                        """
                        INSERT INTO transactions (
                            user_id, amount, transaction_type,
                            description, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            amount,
                            transaction_type,
                            description[:500],
                            ts(),
                        ),
                    )

                    await conn.commit()

                except Exception:
                    await conn.rollback()
                    raise

        self.invalidate(user_id)

        return True

    async def claim_daily(self, user_id: int):

        current = ts()

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30,
            ) as conn:

                await conn.execute("BEGIN TRANSACTION")

                try:

                    async with conn.execute(
                        """
                        SELECT u.balance, u.is_banned,
                               COALESCE(d.last_claim, 0)
                        FROM users u
                        LEFT JOIN daily_bonus d
                        ON d.user_id=u.user_id
                        WHERE u.user_id=?
                        """,
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if not row or row[1]:
                        await conn.rollback()
                        return False, 0

                    balance, _, last_claim = row

                    remaining = DAILY_INTERVAL - (
                        current - last_claim
                    )

                    if remaining > 0:
                        await conn.rollback()
                        return False, remaining

                    new_balance = balance + DAILY_BONUS

                    if new_balance > MAX_BALANCE:
                        await conn.rollback()
                        return False, 0

                    await conn.execute(
                        """
                        UPDATE users
                        SET balance=?,
                            rank=?,
                            total_earned=total_earned+?,
                            daily_bonus_at=?
                        WHERE user_id=?
                        """,
                        (
                            new_balance,
                            rank_for(new_balance),
                            DAILY_BONUS,
                            current,
                            user_id,
                        ),
                    )

                    await conn.execute(
                        """
                        INSERT INTO daily_bonus (
                            user_id, last_claim,
                            total_claims, total_received
                        )
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(user_id)
                        DO UPDATE SET
                            last_claim=excluded.last_claim,
                            total_claims=total_claims+1,
                            total_received=total_received+excluded.total_received
                        """,
                        (user_id, current, DAILY_BONUS),
                    )

                    await conn.execute(
                        """
                        INSERT INTO transactions (
                            user_id, amount, transaction_type,
                            description, created_at
                        )
                        VALUES (?, ?, 'DAILY_BONUS', ?, ?)
                        """,
                        (
                            user_id,
                            DAILY_BONUS,
                            "Daily club reward",
                            current,
                        ),
                    )

                    await conn.commit()

                except Exception:
                    await conn.rollback()
                    raise

        self.invalidate(user_id)

        return True, DAILY_BONUS

    async def log_game(
        self,
        user_id: int,
        name: str,
        result: str,
        points: int = 0,
    ):

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                """
                INSERT INTO game_log (
                    user_id, game_name, result, points, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name[:100],
                    result[:500],
                    points,
                    ts(),
                ),
            )

            await conn.commit()

    async def get_top(self, limit=10):

        async with aiosqlite.connect(self.path) as conn:

            conn.row_factory = aiosqlite.Row

            async with conn.execute(
                """
                SELECT user_id, username, full_name,
                       balance, rank
                FROM users
                WHERE is_banned=0
                ORDER BY balance DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_tournament(self, limit=10):

        cutoff = ts() - 7 * 86400

        async with aiosqlite.connect(self.path) as conn:

            conn.row_factory = aiosqlite.Row

            async with conn.execute(
                """
                SELECT
                    u.user_id,
                    u.full_name,
                    COALESCE(SUM(g.points), 0) AS points
                FROM users u
                LEFT JOIN game_log g
                    ON g.user_id=u.user_id
                    AND g.created_at>=?
                WHERE u.is_banned=0
                GROUP BY u.user_id
                ORDER BY points DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_history(self, user_id: int, limit=10):

        async with aiosqlite.connect(self.path) as conn:

            conn.row_factory = aiosqlite.Row

            async with conn.execute(
                """
                SELECT * FROM game_log
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_stats(self):

        async with aiosqlite.connect(self.path) as conn:

            async with conn.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(balance), 0),
                       COALESCE(SUM(quiz_correct), 0),
                       COALESCE(SUM(partners_count), 0)
                FROM users
                """
            ) as cursor:
                row = await cursor.fetchone()

        return {
            "users": row[0],
            "balance": row[1],
            "quiz": row[2],
            "partners": row[3],
        }

    async def get_setting(self, key, default=None):

        async with aiosqlite.connect(self.path) as conn:

            async with conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()

        return row[0] if row else default

    async def set_setting(self, key, value):

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, str(value), ts()),
            )

            await conn.commit()

    async def set_language(self, user_id: int, language: str):

        if language not in ("RU", "EN"):
            return False

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                "UPDATE users SET language=? WHERE user_id=?",
                (language, user_id),
            )

            await conn.commit()

        self.invalidate(user_id)

        return True

    async def set_verified(self, user_id: int):

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                """
                UPDATE users
                SET is_verified=1, captcha_answer=NULL
                WHERE user_id=?
                """,
                (user_id,),
            )

            await conn.commit()

        self.invalidate(user_id)

    async def get_all_ids(self):

        async with aiosqlite.connect(self.path) as conn:

            async with conn.execute(
                "SELECT user_id FROM users WHERE is_banned=0"
            ) as cursor:
                rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def set_banned(self, user_id: int, value: bool):

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                "UPDATE users SET is_banned=? WHERE user_id=?",
                (int(value), user_id),
            )

            await conn.commit()

        self.invalidate(user_id)

    async def admin_log(
        self,
        admin_id: int,
        action: str,
        target_id=None,
        details="",
    ):

        async with aiosqlite.connect(self.path) as conn:

            await conn.execute(
                """
                INSERT INTO admin_log (
                    admin_id, action, target_id, details, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    admin_id,
                    action[:100],
                    target_id,
                    details[:1000],
                    ts(),
                ),
            )

            await conn.commit()

    async def get_admin_logs(self, limit=20):

        async with aiosqlite.connect(self.path) as conn:

            conn.row_factory = aiosqlite.Row

            async with conn.execute(
                """
                SELECT * FROM admin_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def backup(self):

        destination = BACKUP_DIR / f"backup_{ts()}.db"

        async with self.lock:

            async with aiosqlite.connect(self.path) as source:

                async with aiosqlite.connect(
                    str(destination)
                ) as target:

                    await source.backup(target)

        return destination

    async def cleanup(self, days=90):

        cutoff = ts() - days * 86400

        async with aiosqlite.connect(self.path) as conn:

            cursor = await conn.execute(
                "DELETE FROM game_log WHERE created_at<?",
                (cutoff,),
            )

            count = cursor.rowcount

            await conn.commit()

        return count

    async def close(self):
        self.cache.clear()
        self.cache_at.clear()
        logger.info("Database closed")


# ============================ GLOBALS ==========================

db = Database(DB_PATH)

router = Router(name="tokens_private_club")

scheduler = AsyncIOScheduler(timezone="UTC")

quiz_sessions = {}

captcha_sessions = {}

user_locks = {}


# ============================ KEYBOARDS =======================

def main_keyboard(language="RU"):

    if language == "EN":

        labels = [
            ["🎮 Activities", "🎁 Bonus", "💎 Club"],
            ["👤 Profile", "🤝 Partners", "🏆 Tournament"],
            ["📊 Top", "💬 Chats", "🆘 Support"],
        ]

    else:

        labels = [
            ["🎮 Активности", "🎁 Бонус", "💎 Донат"],
            ["👤 Профиль", "🤝 Партнёры", "🏆 Турнир"],
            ["📊 Топ", "💬 Чаты", "🆘 Поддержка"],
        ]

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=value) for value in row]
            for row in labels
        ],
        resize_keyboard=True,
        input_field_placeholder=(
            "Выберите раздел клуба"
            if language == "RU"
            else "Choose a club section"
        ),
    )


def verification_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я не робот 🤖",
                    callback_data="captcha_begin",
                )
            ]
        ]
    )


def profile_keyboard(language="RU"):

    if language == "EN":
        labels = [
            ("Activity history", "profile_history"),
            ("Achievements", "profile_achievements"),
            ("Change language", "language_menu"),
        ]
    else:
        labels = [
            ("История активности", "profile_history"),
            ("Достижения", "profile_achievements"),
            ("Сменить язык", "language_menu"),
        ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=callback,
                )
            ]
            for label, callback in labels
        ]
    )


def activities_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Викторина",
                    callback_data="quiz_start",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Бросить кубик",
                    callback_data="dice_roll",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Правила",
                    callback_data="activity_rules",
                )
            ],
        ]
    )


def language_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Русский",
                    callback_data="language_RU",
                ),
                InlineKeyboardButton(
                    text="English",
                    callback_data="language_EN",
                ),
            ]
        ]
    )


# ============================ IMAGE HELPERS ====================

def load_font(size: int):

    try:

        if PROFILE_FONT.exists():

            return ImageFont.truetype(
                str(PROFILE_FONT),
                size,
            )

    except Exception:

        logger.exception("Font loading failed")

    return ImageFont.load_default()


def open_background(path: Path, size=(900, 600)):

    try:

        if path.exists():

            image = Image.open(path).convert("RGB")

            return ImageOps.fit(
                image,
                size,
                method=Image.Resampling.LANCZOS,
            )

    except Exception:

        logger.exception("Background loading failed")

    return Image.new(
        "RGB",
        size,
        (20, 24, 36),
    )


async def get_user_avatar(bot: Bot, user_id: int, size=160):

    try:

        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1,
        )

        if photos.total_count:

            photo = photos.photos[0][-1]

            file = await bot.get_file(photo.file_id)

            buffer = io.BytesIO()

            await bot.download_file(
                file.file_path,
                destination=buffer,
            )

            buffer.seek(0)

            avatar = Image.open(buffer).convert("RGBA")

            return ImageOps.fit(
                avatar,
                (size, size),
                method=Image.Resampling.LANCZOS,
            )

    except Exception:

        logger.exception(
            "Avatar loading failed: %s",
            user_id,
        )

    avatar = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(avatar)

    draw.ellipse(
        (2, 2, size - 2, size - 2),
        fill=(125, 130, 145, 255),
    )

    return avatar


def circular_avatar(avatar: Image.Image):

    avatar = avatar.convert("RGBA")

    mask = Image.new("L", avatar.size, 0)

    draw = ImageDraw.Draw(mask)

    draw.ellipse(
        (0, 0, avatar.width - 1, avatar.height - 1),
        fill=255,
    )

    avatar.putalpha(mask)

    return avatar


async def generate_profile_image(
    bot: Bot,
    user: dict,
):

    try:

        image = open_background(
            PROFILE_BACKGROUND,
            (900, 600),
        ).convert("RGBA")

        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle(
            (30, 30, 870, 570),
            radius=30,
            fill=(8, 12, 22, 190),
            outline=(130, 150, 190, 255),
            width=2,
        )

        avatar = await get_user_avatar(
            bot,
            user["user_id"],
            170,
        )

        avatar = circular_avatar(avatar)

        image.alpha_composite(
            avatar,
            (75, 95),
        )

        draw = ImageDraw.Draw(image)

        title_font = load_font(38)
        normal_font = load_font(27)
        small_font = load_font(21)

        draw.text(
            (285, 105),
            user["full_name"][:24],
            font=title_font,
            fill=(255, 255, 255, 255),
        )

        draw.text(
            (285, 175),
            f"ID: {user['user_id']}",
            font=normal_font,
            fill=(185, 200, 225, 255),
        )

        draw.text(
            (285, 235),
            f"RANK: {user['rank']}",
            font=normal_font,
            fill=(220, 220, 235, 255),
        )

        draw.text(
            (285, 295),
            f"BALANCE: {fmt(user['balance'])}",
            font=normal_font,
            fill=(255, 215, 110, 255),
        )

        draw.text(
            (75, 410),
            f"PARTNERS: {user['partners_count']}",
            font=small_font,
            fill=(210, 220, 235, 255),
        )

        draw.text(
            (75, 460),
            f"TOTAL EARNED: {fmt(user['total_earned'])}",
            font=small_font,
            fill=(210, 220, 235, 255),
        )

        draw.text(
            (75, 520),
            BOT_NAME,
            font=small_font,
            fill=(150, 170, 205, 255),
        )

        output = io.BytesIO()

        image.convert("RGB").save(
            output,
            format="JPEG",
            quality=92,
        )

        output.seek(0)

        return BufferedInputFile(
            output.getvalue(),
            filename="profile.jpg",
        )

    except Exception:

        logger.exception("Profile image generation failed")

        fallback = Image.new(
            "RGB",
            (900, 600),
            (20, 24, 36),
        )

        draw = ImageDraw.Draw(fallback)

        draw.text(
            (50, 80),
            user["full_name"][:30],
            font=load_font(32),
            fill="white",
        )

        draw.text(
            (50, 160),
            f"ID: {user['user_id']}",
            font=load_font(24),
            fill="white",
        )

        draw.text(
            (50, 220),
            f"RANK: {user['rank']}",
            font=load_font(24),
            fill="white",
        )

        draw.text(
            (50, 280),
            f"BALANCE: {fmt(user['balance'])}",
            font=load_font(24),
            fill="white",
        )

        output = io.BytesIO()

        fallback.save(output, format="JPEG")

        return BufferedInputFile(
            output.getvalue(),
            filename="profile.jpg",
        )


async def send_asset(
    message: Message,
    name: str,
    caption: str,
    reply_markup=None,
):

    path = ASSETS_DIR / f"{name}.jpg"

    if path.exists():

        try:

            await message.answer_photo(
                FSInputFile(path),
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )

            return

        except Exception:

            logger.exception(
                "Asset sending failed: %s",
                name,
            )

    await message.answer(
        caption,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
    )


# ============================ USER ACCESS ======================

async def require_user(message: Message):

    user = await db.get_user(
        message.from_user.id
    )

    if not user:

        await message.answer(
            get_text("RU", "not_registered")
        )

        return None

    if user["is_banned"]:

        await message.answer(
            get_text(user["language"], "banned")
        )

        return None

    if not user["is_verified"]:

        await message.answer(
            get_text(user["language"], "captcha"),
            reply_markup=verification_keyboard(),
        )

        return None

    maintenance = await db.get_setting(
        "maintenance",
        "0",
    )

    if maintenance == "1" and not admin(
        message.from_user.id
    ):

        await message.answer(
            "В клубе проводятся технические работы."
        )

        return None

    return user


async def require_callback(callback: CallbackQuery):

    user = await db.get_user(
        callback.from_user.id
    )

    if not user:
        await callback.answer(
            "Сначала используйте /start.",
            show_alert=True,
        )
        return None

    if user["is_banned"]:
        await callback.answer(
            "Доступ ограничен.",
            show_alert=True,
        )
        return None

    if not user["is_verified"]:
        await callback.answer(
            "Сначала пройдите проверку.",
            show_alert=True,
        )
        return None

    return user


# ============================ CAPTCHA ==========================

async def begin_captcha(
    callback: CallbackQuery,
):

    user = await db.get_user(
        callback.from_user.id
    )

    if not user:
        await callback.answer(
            "Сначала используйте /start.",
            show_alert=True,
        )
        return

    if user["is_verified"]:
        await callback.answer(
            "Проверка уже пройдена.",
            show_alert=True,
        )
        return

    number = random.randint(1000, 9999)

    captcha_sessions[callback.from_user.id] = number

    async with aiosqlite.connect(DB_PATH) as conn:

        await conn.execute(
            """
            UPDATE users
            SET captcha_answer=?
            WHERE user_id=?
            """,
            (number, callback.from_user.id),
        )

        await conn.commit()

    await callback.answer()

    await callback.message.answer(
        get_text(
            user["language"],
            "captcha_question",
            number=number,
        ),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "captcha_begin")
async def captcha_begin_handler(
    callback: CallbackQuery,
):

    await begin_captcha(callback)


@router.message(
    F.text.regexp(r"^\d{4}$")
)
async def captcha_text_handler(
    message: Message,
):

    user = await db.get_user(
        message.from_user.id
    )

    if not user or user["is_verified"]:
        return

    expected = captcha_sessions.get(
        message.from_user.id
    )

    if expected is None:
        expected = user["captcha_answer"]

    if safe_int(message.text, -1) == expected:

        captcha_sessions.pop(
            message.from_user.id,
            None,
        )

        await db.set_verified(
            message.from_user.id
        )

        updated = await db.get_user(
            message.from_user.id
        )

        language = updated["language"]

        await message.answer(
            get_text(language, "captcha_ok"),
            reply_markup=main_keyboard(language),
        )

    else:

        await message.answer(
            get_text(user["language"], "captcha_wrong")
        )


# ============================ START ============================

@router.message(CommandStart())
async def start_handler(
    message: Message,
    bot: Bot,
):

    payload = None

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) > 1:
        payload = parts[1].strip()

    existing = await db.get_user(
        message.from_user.id
    )

    registration_enabled = await db.get_setting(
        "registration_enabled",
        "1",
    )

    if not existing and registration_enabled != "1":

        await message.answer(
            "Регистрация временно закрыта."
        )

        return

    partner_id = None

    if not existing:
        partner_id = parse_ref(payload)

    user = await db.ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
        partner_id,
    )

    if user["is_banned"]:

        await message.answer(
            get_text(user["language"], "banned")
        )

        return

    if not user["is_verified"]:

        await message.answer(
            get_text(user["language"], "captcha"),
            reply_markup=verification_keyboard(),
        )

        return

    text = get_text(
        user["language"],
        "welcome",
        name=esc(user["full_name"]),
        balance=fmt(user["balance"]),
        rank=user["rank"],
    )

    await send_asset(
        message,
        "start",
        text,
    )

    await message.answer(
        get_text(user["language"], "menu"),
        reply_markup=main_keyboard(user["language"]),
    )


# ============================ PROFILE ==========================

async def show_profile(
    message: Message,
    bot: Bot,
    user_id: int,
):

    user = await db.get_user(user_id)

    if not user or user["is_banned"]:
        await message.answer("Профиль недоступен.")
        return

    if not user["is_verified"]:
        await message.answer(
            get_text(user["language"], "captcha"),
            reply_markup=verification_keyboard(),
        )
        return

    photo = await generate_profile_image(
        bot,
        user,
    )

    await message.answer_photo(
        photo,
        caption=(
            f"<b>{get_text(user['language'], 'profile')}</b>\n\n"
            f"Участник: <b>{esc(user['full_name'])}</b>\n"
            f"Баланс: <code>{fmt(user['balance'])}</code>\n"
            f"Ранг: <b>{user['rank']}</b>\n"
            f"Партнёры: <code>{user['partners_count']}</code>\n"
            f"Викторина: <code>{user['quiz_correct']}</code>"
        ),
        reply_markup=profile_keyboard(user["language"]),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("profile"))
async def profile_command(
    message: Message,
    bot: Bot,
):
    user = await require_user(message)
    if user:
        await show_profile(message, bot, message.from_user.id)


@router.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def profile_button(
    message: Message,
    bot: Bot,
):
    user = await require_user(message)
    if user:
        await show_profile(message, bot, message.from_user.id)


@router.callback_query(F.data == "profile_history")
async def profile_history(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    await callback.answer()

    rows = await db.get_history(
        callback.from_user.id,
        10,
    )

    if not rows:
        await callback.message.answer(
            "История активности пока пуста."
        )
        return

    lines = ["<b>ИСТОРИЯ АКТИВНОСТИ</b>\n"]

    for row in rows:
        lines.append(
            f"• {esc(row['game_name'])}: "
            f"{esc(row['result'])}\n"
            f"<code>{datetime.fromtimestamp(row['created_at'], UTC):%d.%m.%Y %H:%M}</code>"
        )

    await callback.message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "profile_achievements")
async def profile_achievements(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    await callback.answer()

    achievements = []

    if user["balance"] >= 10000:
        achievements.append("BRONZE MEMBER")

    if user["balance"] >= 50000:
        achievements.append("SILVER MEMBER")

    if user["balance"] >= 150000:
        achievements.append("GOLD MEMBER")

    if user["partners_count"] >= 1:
        achievements.append("FIRST PARTNER")

    if user["partners_count"] >= 5:
        achievements.append("NETWORK BUILDER")

    if user["quiz_correct"] >= 10:
        achievements.append("QUIZ EXPERT")

    text = (
        "\n".join(f"• {item}" for item in achievements)
        if achievements
        else "Пока нет открытых достижений."
    )

    await callback.message.answer(
        "<b>ДОСТИЖЕНИЯ</b>\n\n" + text,
        parse_mode=ParseMode.HTML,
    )


# ============================ LANGUAGE =========================

@router.callback_query(F.data == "language_menu")
async def language_menu(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    await callback.answer()

    await callback.message.answer(
        get_text(user["language"], "language"),
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("language_"))
async def language_set(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    language = callback.data.split("_", 1)[1]

    if language not in ("RU", "EN"):
        await callback.answer("Invalid language.")
        return

    await db.set_language(
        callback.from_user.id,
        language,
    )

    await callback.answer(
        get_text(language, "language_changed")
    )

    await callback.message.answer(
        get_text(language, "menu"),
        reply_markup=main_keyboard(language),
    )


# ============================ DAILY BONUS ======================

@router.message(Command("bonus"))
async def bonus_command(
    message: Message,
):
    await daily_bonus_handler(message)


@router.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def bonus_button(
    message: Message,
):
    await daily_bonus_handler(message)


async def daily_bonus_handler(message: Message):

    user = await require_user(message)

    if not user:
        return

    success, result = await db.claim_daily(
        message.from_user.id
    )

    if success:

        await send_asset(
            message,
            "bonus",
            get_text(
                user["language"],
                "bonus_success",
                amount=fmt(result),
            ),
        )

    else:

        await message.answer(
            get_text(
                user["language"],
                "bonus_wait",
                time=human_time(result),
            ),
            parse_mode=ParseMode.HTML,
        )


# ============================ PARTNERS =========================

@router.message(F.text.in_({"🤝 Партнёры", "🤝 Partners"}))
async def partners_handler(
    message: Message,
    bot: Bot,
):

    user = await require_user(message)

    if not user:
        return

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{message.from_user.id}"
    )

    await send_asset(
        message,
        "ref",
        (
            "<b>ПАРТНЁРСКАЯ ПРОГРАММА</b>\n\n"
            f"Приглашено участников: "
            f"<code>{user['partners_count']}</code>\n\n"
            "Ваша персональная ссылка:\n"
            f"<code>{esc(link)}</code>\n\n"
            "Приглашайте знакомых присоединиться к сообществу."
        ),
    )


# ============================ TOP ==============================

@router.message(Command("top"))
async def top_command(
    message: Message,
):
    await top_handler(message)


@router.message(F.text.in_({"📊 Топ", "📊 Top"}))
async def top_button(
    message: Message,
):
    await top_handler(message)


async def top_handler(message: Message):

    user = await require_user(message)

    if not user:
        return

    rows = await db.get_top(10)

    lines = ["<b>ТОП-10 УЧАСТНИКОВ</b>\n"]

    for index, row in enumerate(rows, 1):

        lines.append(
            f"<code>{index:02d}.</code> "
            f"<b>{esc(row['full_name'])}</b>\n"
            f"Баланс: <code>{fmt(row['balance'])}</code>\n"
            f"Ранг: <b>{row['rank']}</b>\n"
        )

    await send_asset(
        message,
        "top",
        "\n".join(lines),
    )


# ============================ TOURNAMENT =======================

@router.message(F.text.in_({"🏆 Турнир", "🏆 Tournament"}))
async def tournament_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    rows = await db.get_tournament(10)

    lines = [
        "<b>НЕДЕЛЬНЫЙ ТУРНИР</b>\n",
        "Рейтинг по результатам викторины за 7 дней.\n",
    ]

    for index, row in enumerate(rows, 1):

        lines.append(
            f"\n<code>{index:02d}.</code> "
            f"<b>{esc(row['full_name'])}</b>\n"
            f"Очки: <code>{fmt(row['points'])}</code>"
        )

    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ============================ ACTIVITIES =======================

@router.message(F.text.in_({"🎮 Активности", "🎮 Activities"}))
async def activities_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    await message.answer(
        get_text(user["language"], "games"),
        reply_markup=activities_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "activity_rules")
async def activity_rules(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    await callback.answer()

    await callback.message.answer(
        "<b>ПРАВИЛА АКТИВНОСТЕЙ</b>\n\n"
        "• Все активности бесплатны.\n"
        "• Баланс не уменьшается.\n"
        "• Клубные очки не продаются и не выводятся.\n"
        "• Результаты викторины могут учитываться в турнире.\n"
        "• Запрещены спам и автоматизация ответов.",
        parse_mode=ParseMode.HTML,
    )


# ============================ QUIZ =============================

@router.callback_query(F.data == "quiz_start")
async def quiz_start(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    user_id = callback.from_user.id

    if user_id in quiz_sessions:

        await callback.answer(
            "Сначала завершите текущий вопрос.",
            show_alert=True,
        )

        return

    question = random.choice(QUIZ_QUESTIONS)

    token = secrets.token_hex(4)

    quiz_sessions[user_id] = {
        "token": token,
        "question": question,
        "created_at": ts(),
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=answer,
                    callback_data=f"quiz_{token}_{index}",
                )
            ]
            for index, answer in enumerate(question["a"])
        ]
    )

    await callback.answer()

    await callback.message.answer(
        "<b>ВОПРОС ВИКТОРИНЫ</b>\n\n"
        + escape_text(question["q"]),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


def escape_text(value):
    return html.escape(str(value))


@router.callback_query(F.data.startswith("quiz_"))
async def quiz_answer(
    callback: CallbackQuery,
):

    user = await require_callback(callback)

    if not user:
        return

    parts = callback.data.split("_")

    if len(parts) != 3:
        await callback.answer("Некорректный ответ.")
        return

    token = parts[1]

    answer = safe_int(parts[2], -1)

    user_id = callback.from_user.id

    session = quiz_sessions.get(user_id)

    if not session or session["token"] != token:

        await callback.answer(
            "Этот вопрос уже завершён.",
            show_alert=True,
        )

        return

    quiz_sessions.pop(user_id, None)

    question = session["question"]

    correct = question["correct"]

    await callback.answer()

    if answer == correct:

        reward = 250

        await db.change_balance(
            user_id,
            reward,
            "Награда за правильный ответ",
            "QUIZ_REWARD",
        )

        async with aiosqlite.connect(DB_PATH) as conn:

            await conn.execute(
                """
                UPDATE users
                SET quiz_correct=quiz_correct+1
                WHERE user_id=?
                """,
                (user_id,),
            )

            await conn.commit()

        await db.log_game(
            user_id,
            "Викторина",
            "Правильный ответ",
            1,
        )

        text = (
            "<b>ВЕРНО!</b>\n\n"
            f"Начислено: <code>+{reward}</code> очков.\n"
            "В турнир добавлено `1` очко."
        )

    else:

        await db.log_game(
            user_id,
            "Викторина",
            "Неверный ответ",
            0,
        )

        text = (
            "<b>ОТВЕТ НЕВЕРНЫЙ</b>\n\n"
            "Правильный ответ: "
            f"<b>{escape_text(question['a'][correct])}</b>"
        )

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================ DICE =============================

@router.callback_query(F.data == "dice_roll")
async def dice_roll(
    callback: CallbackQuery,
    bot: Bot,
):

    user = await require_callback(callback)

    if not user:
        return

    await callback.answer()

    lock = user_lock(callback.from_user.id)

    if lock.locked():

        await callback.message.answer(
            "Предыдущая активность ещё выполняется."
        )

        return

    async with lock:

        await bot.send_dice(
            chat_id=callback.message.chat.id,
            emoji="🎲",
        )

        await db.log_game(
            callback.from_user.id,
            "Кубик",
            "Развлекательный бросок",
            0,
        )


# ============================ CLUB INFORMATION =================

@router.message(F.text.in_({"💎 Донат", "💎 Club"}))
async def donate_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    await send_asset(
        message,
        "donate",
        get_text(user["language"], "donate"),
    )


@router.message(F.text.in_({"💬 Чаты", "💬 Chats"}))
async def chats_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть чат клуба",
                    url=CLUB_CHAT_URL,
                )
            ]
        ]
    )

    await send_asset(
        message,
        "chats",
        get_text(user["language"], "chats"),
        keyboard,
    )


@router.message(F.text.in_({"🆘 Поддержка", "🆘 Support"}))
async def support_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Связаться с поддержкой",
                    url=SUPPORT_URL,
                )
            ]
        ]
    )

    await send_asset(
        message,
        "support",
        get_text(user["language"], "support"),
        keyboard,
    )


# ============================ HELP =============================

@router.message(Command("help"))
async def help_handler(
    message: Message,
):

    user = await require_user(message)

    if not user:
        return

    text = (
        "<b>TOKENS | PRIVATE CLUB</b>\n\n"
        "<b>Команды участника</b>\n"
        "/start — регистрация и меню\n"
        "/profile — профиль\n"
        "/bonus — ежедневная награда\n"
        "/top — рейтинг\n"
        "/help — помощь\n\n"
        "Остальные разделы доступны через меню."
    )

    if admin(message.from_user.id):

        text += (
            "\n\n<b>Администрирование</b>\n"
            "/admin — панель\n"
            "/stats — статистика\n"
            "/give ID AMOUNT — бесплатная награда\n"
            "/ban ID — ограничить доступ\n"
            "/unban ID — восстановить доступ\n"
            "/backup — резервная копия\n"
            "/broadcast — объявление\n"
            "/maintenance on/off — техрежим"
        )

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(user["language"]),
    )


# ============================ ADMIN ============================

def admin_only(message: Message) -> bool:
    return admin(message.from_user.id)


@router.message(Command("admin"))
async def admin_panel(
    message: Message,
):

    if not admin_only(message):
        await message.answer("Доступ запрещён.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="admin_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Резервная копия",
                    callback_data="admin_backup",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Журнал",
                    callback_data="admin_logs",
                )
            ],
        ]
    )

    await message.answer(
        "<b>ADMIN PANEL</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("stats"))
async def admin_stats(
    message: Message,
):

    if not admin_only(message):
        return

    stats = await db.get_stats()

    await message.answer(
        "<b>СТАТИСТИКА</b>\n\n"
        f"Участники: <code>{stats['users']}</code>\n"
        f"Баланс: <code>{fmt(stats['balance'])}</code>\n"
        f"Верных ответов: <code>{stats['quiz']}</code>\n"
        f"Партнёры: <code>{stats['partners']}</code>",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(
    callback: CallbackQuery,
):

    await callback.answer()

    if not admin(callback.from_user.id):
        return

    stats = await db.get_stats()

    await callback.message.answer(
        "<b>СТАТИСТИКА</b>\n\n"
        f"Участники: <code>{stats['users']}</code>\n"
        f"Баланс: <code>{fmt(stats['balance'])}</code>\n"
        f"Партнёры: <code>{stats['partners']}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================ ADMIN REWARD =====================

@router.message(Command("give"))
async def admin_give(
    message: Message,
):

    if not admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 3:

        await message.answer(
            "Использование: /give USER_ID AMOUNT\n"
            f"Максимальная награда: {MAX_REWARD}"
        )

        return

    target_id = safe_int(parts[1])

    amount = safe_int(parts[2])

    if target_id <= 0 or not 0 < amount <= MAX_REWARD:

        await message.answer(
            "Некорректный ID или размер награды."
        )

        return

    target = await db.get_user(target_id)

    if not target:

        await message.answer(
            "Пользователь не найден."
        )

        return

    success = await db.change_balance(
        target_id,
        amount,
        "Бесплатная награда администратора",
        "ADMIN_REWARD",
    )

    if not success:

        await message.answer(
            "Не удалось начислить награду."
        )

        return

    await db.admin_log(
        message.from_user.id,
        "GIVE_REWARD",
        target_id,
        str(amount),
    )

    await message.answer(
        "Награда начислена.\n"
        f"Пользователь: <code>{target_id}</code>\n"
        f"Количество: <code>+{amount}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================ ADMIN BAN ========================

@router.message(Command("ban"))
async def admin_ban(
    message: Message,
):

    if not admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Использование: /ban USER_ID")
        return

    target_id = safe_int(parts[1])

    if target_id <= 0 or target_id == ADMIN_ID:
        await message.answer("Недопустимый ID.")
        return

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Пользователь не найден.")
        return

    await db.set_banned(target_id, True)

    await db.admin_log(
        message.from_user.id,
        "BAN",
        target_id,
    )

    await message.answer(
        f"Доступ пользователя <code>{target_id}</code> ограничен.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("unban"))
async def admin_unban(
    message: Message,
):

    if not admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Использование: /unban USER_ID")
        return

    target_id = safe_int(parts[1])

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Пользователь не найден.")
        return

    await db.set_banned(target_id, False)

    await db.admin_log(
        message.from_user.id,
        "UNBAN",
        target_id,
    )

    await message.answer(
        f"Доступ пользователя <code>{target_id}</code> восстановлен.",
        parse_mode=ParseMode.HTML,
    )


# ============================ ADMIN BACKUP =====================

@router.message(Command("backup"))
async def admin_backup(
    message: Message,
):

    if not admin_only(message):
        return

    try:

        path = await db.backup()

        await db.admin_log(
            message.from_user.id,
            "BACKUP",
            details=str(path),
        )

        await message.answer_document(
            FSInputFile(path),
            caption="Резервная копия базы данных.",
        )

    except Exception:

        logger.exception("Backup error")

        await message.answer(
            "Не удалось создать резервную копию."
        )


@router.callback_query(F.data == "admin_backup")
async def admin_backup_callback(
    callback: CallbackQuery,
):

    await callback.answer()

    if not admin(callback.from_user.id):
        return

    try:

        path = await db.backup()

        await callback.message.answer_document(
            FSInputFile(path),
            caption="Резервная копия базы данных.",
        )

    except Exception:

        logger.exception("Backup error")

        await callback.message.answer(
            "Ошибка создания резервной копии."
        )


# ============================ ADMIN LOGS =======================

@router.callback_query(F.data == "admin_logs")
async def admin_logs(
    callback: CallbackQuery,
):

    await callback.answer()

    if not admin(callback.from_user.id):
        return

    rows = await db.get_admin_logs(15)

    if not rows:

        await callback.message.answer(
            "Журнал пуст."
        )

        return

    lines = ["<b>ЖУРНАЛ АДМИНИСТРАТОРА</b>\n"]

    for row in rows:

        lines.append(
            f"<code>{row['id']}</code> "
            f"<b>{esc(row['action'])}</b>\n"
            f"Admin: <code>{row['admin_id']}</code>\n"
            f"Target: <code>{row['target_id'] or '—'}</code>\n"
            f"Details: {esc(row['details'])}\n"
        )

    await callback.message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ============================ ADMIN MAINTENANCE ================

@router.message(Command("maintenance"))
async def admin_maintenance(
    message: Message,
):

    if not admin_only(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or parts[1] not in ("on", "off"):

        await message.answer(
            "Использование: /maintenance on или /maintenance off"
        )

        return

    value = "1" if parts[1] == "on" else "0"

    await db.set_setting(
        "maintenance",
        value,
    )

    await db.admin_log(
        message.from_user.id,
        "MAINTENANCE",
        details=value,
    )

    await message.answer(
        "Технический режим включён."
        if value == "1"
        else "Технический режим выключен."
    )


# ============================ ADMIN BROADCAST ==================

@router.message(Command("broadcast"))
async def broadcast_start(
    message: Message,
    state: FSMContext,
):

    if not admin_only(message):
        return

    await state.set_state(
        BroadcastState.waiting_text
    )

    await message.answer(
        "Отправьте текст объявления.\n"
        "Для отмены используйте /cancel."
    )


class BroadcastState(StatesGroup):
    waiting_text = State()


@router.message(
    BroadcastState.waiting_text,
    Command("cancel"),
)
async def broadcast_cancel(
    message: Message,
    state: FSMContext,
):

    await state.clear()

    await message.answer(
        "Рассылка отменена."
    )


@router.message(
    BroadcastState.waiting_text,
    F.text,
)
async def broadcast_send(
    message: Message,
    state: FSMContext,
    bot: Bot,
):

    if not admin_only(message):
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text or len(text) > 4000:

        await message.answer(
            "Текст должен содержать от 1 до 4000 символов."
        )

        return

    await state.clear()

    ids = await db.get_all_ids()

    sent = 0
    failed = 0

    status = await message.answer(
        "Рассылка выполняется."
    )

    for user_id in ids:

        try:

            await bot.send_message(
                user_id,
                text,
            )

            sent += 1

        except Exception:

            failed += 1

        await asyncio.sleep(0.04)

    await db.admin_log(
        message.from_user.id,
        "BROADCAST",
        details=f"sent={sent}; failed={failed}",
    )

    await status.edit_text(
        "Рассылка завершена.\n\n"
        f"Отправлено: <code>{sent}</code>\n"
        f"Ошибок: <code>{failed}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================ SCHEDULED TASKS ==================

async def scheduled_cleanup():

    try:

        deleted = await db.cleanup(90)

        logger.info(
            "Old activity rows deleted: %s",
            deleted,
        )

    except Exception:

        logger.exception("Scheduled cleanup failed")


async def scheduled_backup():

    try:

        path = await db.backup()

        logger.info(
            "Scheduled backup created: %s",
            path,
        )

        files = sorted(
            BACKUP_DIR.glob("backup_*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

        for old_file in files[10:]:

            try:
                old_file.unlink()
            except OSError:
                pass

    except Exception:

        logger.exception("Scheduled backup failed")


async def scheduled_auto_drop(bot: Bot):

    enabled = await db.get_setting(
        "auto_drop_enabled",
        "0",
    )

    if enabled != "1":
        return

    amount = safe_int(
        await db.get_setting(
            "auto_drop_amount",
            "1000",
        ),
        1000,
    )

    amount = max(
        1,
        min(amount, MAX_REWARD),
    )

    users = await db.get_all_ids()

    if not users:
        return

    target_id = random.choice(users)

    success = await db.change_balance(
        target_id,
        amount,
        "Автоматическая бесплатная награда",
        "EVENT_REWARD",
    )

    if not success:
        return

    try:

        await bot.send_message(
            target_id,
            "Вам начислена бесплатная клубная награда: "
            f"<code>+{amount}</code> очков.",
            parse_mode=ParseMode.HTML,
        )

    except Exception:

        logger.warning(
            "Could not notify user %s",
            target_id,
        )


async def scheduled_happy_hour():

    # Событие влияет только на информационный статус.
    # Никакие взносы, списания или выплаты не выполняются.

    current_hour = datetime.now(UTC).hour

    enabled = current_hour in (17, 18, 19)

    await db.set_setting(
        "happy_hour",
        "1" if enabled else "0",
    )


# ============================ HTTP SERVER ======================

async def health_handler(request):

    return web.json_response({
        "status": "ok",
        "service": BOT_NAME,
        "version": VERSION,
        "timestamp": ts(),
    })


async def start_http_server():

    app = web.Application()

    app.router.add_get("/", health_handler)

    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()

    logger.info(
        "Health server listening on %s",
        PORT,
    )

    return runner


# ============================ ERROR HANDLER ====================

async def global_error_handler(
    event,
    exception,
):

    logger.exception(
        "Unhandled update error",
        exc_info=exception,
    )

    try:

        bot = getattr(event, "bot", None)

        if bot and ADMIN_ID:

            await bot.send_message(
                ADMIN_ID,
                "В боте произошла ошибка:\n"
                f"<code>{esc(str(exception)[:1500])}</code>",
                parse_mode=ParseMode.HTML,
            )

    except Exception:

        logger.exception(
            "Could not notify administrator"
        )

    return True


# ============================ STARTUP ==========================

async def setup():

    if not BOT_TOKEN:

        raise RuntimeError(
            "Не задан BOT_TOKEN в переменных окружения."
        )

    await db.connect()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    dispatcher = Dispatcher(
        storage=MemoryStorage(),
    )

    dispatcher.include_router(router)

    dispatcher.errors.register(
        global_error_handler
    )

    scheduler.add_job(
        scheduled_cleanup,
        "cron",
        hour=4,
        minute=0,
        id="cleanup",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_backup,
        "cron",
        hour=3,
        minute=0,
        id="backup",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_happy_hour,
        "interval",
        minutes=5,
        id="happy_hour",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_auto_drop,
        "interval",
        minutes=60,
        args=[bot],
        id="auto_drop",
        replace_existing=True,
    )

    scheduler.start()

    http_runner = await start_http_server()

    logger.info(
        "%s v%s started",
        BOT_NAME,
        VERSION,
    )

    return bot, dispatcher, http_runner


# ============================ MAIN =============================

async def main():

    bot = None
    http_runner = None

    try:

        bot, dispatcher, http_runner = await setup()

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )

    except KeyboardInterrupt:

        logger.info("Shutdown requested")

    except Exception:

        logger.exception("Fatal application error")

        raise

    finally:

        logger.info("Stopping application")

        if scheduler.running:
            scheduler.shutdown(wait=False)

        if http_runner:
            await http_runner.cleanup()

        if bot:
            await bot.session.close()

        await db.close()

        logger.info("Application stopped")


if __name__ == "__main__":
    asyncio.run(main())