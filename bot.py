
# ==============================================================
# TOKENS | PRIVATE CLUB
# Полный монолитный Telegram-бот
# Python 3.11+
#
# Установка:
# pip install aiogram aiosqlite Pillow apscheduler aiohttp
#
# Переменные окружения:
# BOT_TOKEN=токен_бота
# ADMIN_ID=telegram_id_администратора
# SUPPORT_URL=https://t.me/your_support
# CLUB_CHAT_URL=https://t.me/your_chat
# DB_PATH=data/tokens_club.db
#
# Запуск:
# python bot.py
# ==============================================================

import asyncio
import logging
import os
import random
import time
import io
import html
import shutil
import sqlite3

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

from aiogram.fsm.state import (
    State,
    StatesGroup,
)

from aiogram.fsm.context import FSMContext

from aiogram.fsm.storage.memory import MemoryStorage

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiohttp import web


# ==============================================================
# CONFIGURATION
# ==============================================================

BASE_DIR = Path(__file__).resolve().parent

ASSETS_DIR = BASE_DIR / "assets"

DATA_DIR = BASE_DIR / "data"

LOG_DIR = BASE_DIR / "logs"

BACKUP_DIR = BASE_DIR / "backups"

for directory in (
    ASSETS_DIR,
    DATA_DIR,
    LOG_DIR,
    BACKUP_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


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

VERSION = "4.0.0"

DAILY_BONUS = 5000

DAILY_INTERVAL = 86400

MAX_FREE_REWARD = 10000

MAX_BALANCE = 10**12

CACHE_TTL = 5

UTC = timezone.utc


# ==============================================================
# ASSETS
# ==============================================================

ASSETS = {
    "start": ASSETS_DIR / "start.jpg",
    "profile": ASSETS_DIR / "profile.jpg",
    "donate": ASSETS_DIR / "donate.jpg",
    "bonus": ASSETS_DIR / "bonus.jpg",
    "top": ASSETS_DIR / "top.jpg",
    "ref": ASSETS_DIR / "ref.jpg",
    "how_to_play": ASSETS_DIR / "how_to_play.jpg",
    "support": ASSETS_DIR / "support.jpg",
    "chats": ASSETS_DIR / "chats.jpg",
    "commands": ASSETS_DIR / "commands.jpg",
    "roulette": ASSETS_DIR / "roulette.gif",
}

FONT_PATH = ASSETS_DIR / "Montserrat-Bold.ttf"


# ==============================================================
# LOGGING
# ==============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / "tokens_club.log",
            encoding="utf-8"
        ),
    ],
)

logger = logging.getLogger("TOKENS")


# ==============================================================
# CONSTANTS
# ==============================================================

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

DEFAULT_SETTINGS = {
    "maintenance": "0",
    "registration_enabled": "1",
    "happy_hour": "0",
    "auto_drop_enabled": "0",
    "auto_drop_amount": "1000",
}

QUIZ_QUESTIONS = [
    {
        "question": "Сколько будет 12 × 8?",
        "answers": ["86", "96", "108", "112"],
        "correct": 1,
    },
    {
        "question": "Какая планета ближе всего к Солнцу?",
        "answers": ["Венера", "Земля", "Меркурий", "Марс"],
        "correct": 2,
    },
    {
        "question": "Сколько сторон у шестиугольника?",
        "answers": ["5", "6", "7", "8"],
        "correct": 1,
    },
    {
        "question": "Какой язык используется в этом боте?",
        "answers": ["Python", "Java", "C++", "PHP"],
        "correct": 0,
    },
    {
        "question": "Сколько минут в двух часах?",
        "answers": ["100", "110", "120", "140"],
        "correct": 2,
    },
    {
        "question": "Как называется столица Германии?",
        "answers": ["Мюнхен", "Берлин", "Гамбург", "Бонн"],
        "correct": 1,
    },
    {
        "question": "Какое число является простым?",
        "answers": ["9", "15", "17", "21"],
        "correct": 2,
    },
    {
        "question": "Сколько байт в одном килобайте по стандарту SI?",
        "answers": ["100", "512", "1000", "1024"],
        "correct": 2,
    },
]

# ==============================================================
# HELPERS
# ==============================================================

def current_time() -> int:
    return int(time.time())


def format_tokens(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def format_date(value: int) -> str:
    if not value:
        return "—"

    return datetime.fromtimestamp(
        value,
        UTC
    ).strftime("%d.%m.%Y %H:%M")


def escape(value) -> str:
    return html.escape(str(value or ""))


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def get_rank(balance: int) -> str:
    result = "MEMBER"

    for threshold, rank in RANKS:
        if balance >= threshold:
            result = rank

    return result


def human_time(seconds: int) -> str:
    seconds = max(0, int(seconds))

    hours, remainder = divmod(seconds, 3600)

    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours} ч. {minutes} мин."

    if minutes:
        return f"{minutes} мин."

    return f"{seconds} сек."


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def parse_referral(payload: Optional[str]):
    if not payload:
        return None

    if not payload.startswith("ref_"):
        return None

    try:
        user_id = int(payload[4:])

        return user_id if user_id > 0 else None

    except ValueError:
        return None


def normalize_name(value: Optional[str]) -> str:
    return (value or "Участник клуба").strip()[:128]


# ==============================================================
# DATABASE
# ==============================================================

class Database:

    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()
        self.cache = {}
        self.cache_time = {}

    async def connect(self):

        Path(self.path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        async with aiosqlite.connect(
            self.path,
            timeout=30
        ) as connection:

            await connection.execute(
                "PRAGMA journal_mode=WAL"
            )

            await connection.execute(
                "PRAGMA foreign_keys=ON"
            )

            await connection.execute(
                "PRAGMA busy_timeout=30000"
            )

            await connection.executescript("""

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0,
                rank TEXT NOT NULL DEFAULT 'MEMBER',
                partner_id INTEGER,
                partners_count INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                daily_bonus_at INTEGER NOT NULL DEFAULT 0,
                total_earned INTEGER NOT NULL DEFAULT 0,
                quiz_points INTEGER NOT NULL DEFAULT 0,
                quiz_correct INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                result TEXT NOT NULL,
                points INTEGER DEFAULT 0,
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

            CREATE INDEX IF NOT EXISTS idx_game_created
            ON game_log(created_at);

            CREATE INDEX IF NOT EXISTS idx_game_user
            ON game_log(user_id);

            CREATE INDEX IF NOT EXISTS idx_transactions_user
            ON transactions(user_id);

            """)

            for key, value in DEFAULT_SETTINGS.items():

                await connection.execute(
                    """
                    INSERT OR IGNORE INTO settings
                    (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, current_time())
                )

            await connection.commit()

        logger.info("Database initialized")

    def invalidate(self, user_id: int):
        self.cache.pop(user_id, None)
        self.cache_time.pop(user_id, None)

    def get_cached(self, user_id: int):
        data = self.cache.get(user_id)

        if data is None:
            return None

        if (
            time.monotonic()
            - self.cache_time.get(user_id, 0)
            > CACHE_TTL
        ):
            self.invalidate(user_id)
            return None

        return data.copy()

    def set_cached(self, user_id: int, data: dict):
        if len(self.cache) > 5000:
            self.cache.clear()
            self.cache_time.clear()

        self.cache[user_id] = data.copy()
        self.cache_time[user_id] = time.monotonic()

    async def get_user(self, user_id: int):

        cached = self.get_cached(user_id)

        if cached is not None:
            return cached

        async with aiosqlite.connect(self.path) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,)
            ) as cursor:

                row = await cursor.fetchone()

        if not row:
            return None

        result = dict(row)

        self.set_cached(user_id, result)

        return result

    async def ensure_user(
        self,
        user_id: int,
        username: Optional[str],
        full_name: str,
        partner_id: Optional[int] = None
    ):

        if user_id <= 0:
            raise ValueError("Invalid user ID")

        current = current_time()

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30
            ) as connection:

                await connection.execute(
                    "BEGIN IMMEDIATE"
                )

                try:

                    async with connection.execute(
                        "SELECT user_id FROM users WHERE user_id = ?",
                        (user_id,)
                    ) as cursor:

                        existing = await cursor.fetchone()

                    if existing:

                        await connection.execute(
                            """
                            UPDATE users
                            SET username = ?,
                                full_name = ?,
                                last_seen = ?
                            WHERE user_id = ?
                            """,
                            (
                                username,
                                normalize_name(full_name),
                                current,
                                user_id
                            )
                        )

                    else:

                        valid_partner = None

                        if partner_id and partner_id != user_id:

                            async with connection.execute(
                                """
                                SELECT user_id
                                FROM users
                                WHERE user_id = ?
                                AND is_banned = 0
                                """,
                                (partner_id,)
                            ) as cursor:

                                partner = await cursor.fetchone()

                            if partner:
                                valid_partner = partner_id

                        await connection.execute(
                            """
                            INSERT INTO users (
                                user_id,
                                username,
                                full_name,
                                partner_id,
                                created_at,
                                last_seen
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                username,
                                normalize_name(full_name),
                                valid_partner,
                                current,
                                current
                            )
                        )

                        if valid_partner:

                            await connection.execute(
                                """
                                UPDATE users
                                SET partners_count = partners_count + 1
                                WHERE user_id = ?
                                """,
                                (valid_partner,)
                            )

                    await connection.commit()

                except Exception:

                    await connection.rollback()

                    raise

        self.invalidate(user_id)

        if partner_id:
            self.invalidate(partner_id)

        return await self.get_user(user_id)

    async def add_reward(
        self,
        user_id: int,
        amount: int,
        description: str,
        reward_type: str = "EVENT_REWARD"
    ) -> bool:

        if amount <= 0 or amount > MAX_FREE_REWARD:
            return False

        if reward_type not in REWARD_TYPES:
            return False

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30
            ) as connection:

                await connection.execute(
                    "BEGIN IMMEDIATE"
                )

                try:

                    async with connection.execute(
                        """
                        SELECT balance, is_banned
                        FROM users
                        WHERE user_id = ?
                        """,
                        (user_id,)
                    ) as cursor:

                        row = await cursor.fetchone()

                    if not row or row[1]:
                        await connection.rollback()
                        return False

                    new_balance = row[0] + amount

                    if new_balance > MAX_BALANCE:
                        await connection.rollback()
                        return False

                    await connection.execute(
                        """
                        UPDATE users
                        SET balance = ?,
                            rank = ?,
                            total_earned = total_earned + ?
                        WHERE user_id = ?
                        """,
                        (
                            new_balance,
                            get_rank(new_balance),
                            amount,
                            user_id
                        )
                    )

                    await connection.execute(
                        """
                        INSERT INTO transactions (
                            user_id,
                            amount,
                            transaction_type,
                            description,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            amount,
                            reward_type,
                            description[:500],
                            current_time()
                        )
                    )

                    await connection.commit()

                except Exception:

                    await connection.rollback()

                    raise

        self.invalidate(user_id)

        return True

    async def claim_daily(self, user_id: int):

        current = current_time()

        async with self.lock:

            async with aiosqlite.connect(
                self.path,
                timeout=30
            ) as connection:

                await connection.execute(
                    "BEGIN IMMEDIATE"
                )

                try:

                    async with connection.execute(
                        """
                        SELECT
                            u.balance,
                            u.is_banned,
                            COALESCE(d.last_claim, 0)
                        FROM users u
                        LEFT JOIN daily_bonus d
                            ON d.user_id = u.user_id
                        WHERE u.user_id = ?
                        """,
                        (user_id,)
                    ) as cursor:

                        row = await cursor.fetchone()

                    if not row or row[1]:
                        await connection.rollback()
                        return False, 0

                    balance, _, last_claim = row

                    remaining = (
                        DAILY_INTERVAL
                        - (current - last_claim)
                    )

                    if remaining > 0:
                        await connection.rollback()
                        return False, remaining

                    new_balance = balance + DAILY_BONUS

                    if new_balance > MAX_BALANCE:
                        await connection.rollback()
                        return False, 0

                    await connection.execute(
                        """
                        UPDATE users
                        SET balance = ?,
                            rank = ?,
                            total_earned = total_earned + ?,
                            daily_bonus_at = ?
                        WHERE user_id = ?
                        """,
                        (
                            new_balance,
                            get_rank(new_balance),
                            DAILY_BONUS,
                            current,
                            user_id
                        )
                    )

                    await connection.execute(
                        """
                        INSERT INTO daily_bonus (
                            user_id,
                            last_claim,
                            total_claims,
                            total_received
                        )
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(user_id)
                        DO UPDATE SET
                            last_claim = excluded.last_claim,
                            total_claims = total_claims + 1,
                            total_received =
                                total_received + excluded.total_received
                        """,
                        (
                            user_id,
                            current,
                            DAILY_BONUS
                        )
                    )

                    await connection.execute(
                        """
                        INSERT INTO transactions (
                            user_id,
                            amount,
                            transaction_type,
                            description,
                            created_at
                        )
                        VALUES (?, ?, 'DAILY_BONUS', ?, ?)
                        """,
                        (
                            user_id,
                            DAILY_BONUS,
                            "Ежедневная награда",
                            current
                        )
                    )

                    await connection.commit()

                except Exception:

                    await connection.rollback()

                    raise

        self.invalidate(user_id)

        return True, DAILY_BONUS

    async def log_game(
        self,
        user_id: int,
        game_name: str,
        result: str,
        points: int = 0
    ):

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                INSERT INTO game_log (
                    user_id,
                    game_name,
                    result,
                    points,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    game_name[:100],
                    result[:500],
                    points,
                    current_time()
                )
            )

            await connection.commit()

    async def get_top_users(self, limit=10):

        async with aiosqlite.connect(self.path) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT user_id, username, full_name,
                       balance, rank
                FROM users
                WHERE is_banned = 0
                ORDER BY balance DESC
                LIMIT ?
                """,
                (limit,)
            ) as cursor:

                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_tournament_top(self, limit=10):

        cutoff = current_time() - 7 * 86400

        async with aiosqlite.connect(self.path) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT
                    u.user_id,
                    u.full_name,
                    u.username,
                    COALESCE(SUM(g.points), 0) AS points
                FROM users u
                LEFT JOIN game_log g
                    ON g.user_id = u.user_id
                    AND g.created_at >= ?
                WHERE u.is_banned = 0
                GROUP BY u.user_id
                ORDER BY points DESC
                LIMIT ?
                """,
                (cutoff, limit)
            ) as cursor:

                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_history(self, user_id: int, limit=10):

        async with aiosqlite.connect(self.path) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT *
                FROM game_log
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit)
            ) as cursor:

                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_setting(self, key, default=None):

        async with aiosqlite.connect(self.path) as connection:

            async with connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,)
            ) as cursor:

                row = await cursor.fetchone()

        return row[0] if row else default

    async def set_setting(self, key, value):

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value), current_time())
            )

            await connection.commit()

    async def get_stats(self):

        async with aiosqlite.connect(self.path) as connection:

            async with connection.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(balance), 0),
                    COALESCE(SUM(quiz_points), 0),
                    COALESCE(SUM(partners_count), 0)
                FROM users
                """
            ) as cursor:

                row = await cursor.fetchone()

        return {
            "users": row[0],
            "balance": row[1],
            "quiz_points": row[2],
            "partners": row[3],
        }

    async def get_admin_logs(self, limit=20):

        async with aiosqlite.connect(self.path) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT *
                FROM admin_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            ) as cursor:

                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def log_admin(
        self,
        admin_id,
        action,
        target_id=None,
        details=""
    ):

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                INSERT INTO admin_log (
                    admin_id, action, target_id,
                    details, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    admin_id,
                    action[:100],
                    target_id,
                    details[:1000],
                    current_time()
                )
            )

            await connection.commit()

    async def get_all_user_ids(self):

        async with aiosqlite.connect(self.path) as connection:

            async with connection.execute(
                "SELECT user_id FROM users WHERE is_banned = 0"
            ) as cursor:

                rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def set_banned(self, user_id: int, value: bool):

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                UPDATE users
                SET is_banned = ?
                WHERE user_id = ?
                """,
                (int(value), user_id)
            )

            await connection.commit()

        self.invalidate(user_id)

    async def backup(self):

        destination = (
            BACKUP_DIR /
            f"tokens_{current_time()}.db"
        )

        async with self.lock:

            async with aiosqlite.connect(self.path) as source:

                async with aiosqlite.connect(
                    str(destination)
                ) as target:

                    await source.backup(target)

        return destination

    async def cleanup(self, days=90):

        cutoff = current_time() - days * 86400

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                "DELETE FROM game_log WHERE created_at < ?",
                (cutoff,)
            )

            await connection.commit()

    async def close(self):
        self.cache.clear()
        self.cache_time.clear()


# ==============================================================
# GLOBAL OBJECTS
# ==============================================================

db = Database(DB_PATH)

router = Router(name="tokens_private_club")

scheduler = AsyncIOScheduler(timezone="UTC")

storage = MemoryStorage()

ACTIVE_QUIZZES = {}

USER_ACTION_LOCKS = {}


# ==============================================================
# FSM
# ==============================================================

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_reward = State()
    waiting_for_ban_id = State()


# ==============================================================
# KEYBOARDS
# ==============================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎮 Игры"),
                KeyboardButton(text="🎁 Бонус"),
                KeyboardButton(text="💎 Донат"),
            ],
            [
                KeyboardButton(text="👤 Профиль"),
                KeyboardButton(text="🤝 Партнёры"),
                KeyboardButton(text="🏆 Турнир"),
            ],
            [
                KeyboardButton(text="📊 Топ"),
                KeyboardButton(text="💬 Чаты"),
                KeyboardButton(text="🆘 Поддержка"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел клуба",
    )


def profile_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="История активности",
                    callback_data="profile_history"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Мои достижения",
                    callback_data="profile_achievements"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Обновить профиль",
                    callback_data="profile_refresh"
                ),
            ],
        ]
    )


def games_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Викторина",
                    callback_data="game_quiz"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Кубик",
                    callback_data="game_dice"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Правила игр",
                    callback_data="game_rules"
                ),
            ],
        ]
    )


def back_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="В меню",
                    callback_data="back_menu"
                )
            ]
        ]
    )


def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="admin_stats"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Резервная копия",
                    callback_data="admin_backup"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Журнал",
                    callback_data="admin_logs"
                ),
            ],
        ]
    )


# ==============================================================
# IMAGE HELPERS
# ==============================================================

def load_font(size: int):

    try:

        if FONT_PATH.exists():

            return ImageFont.truetype(
                str(FONT_PATH),
                size=size
            )

    except Exception:

        logger.warning("Cannot load custom font")

    return ImageFont.load_default()


def open_background(
    path: Path,
    size=(900, 600)
):

    if path.exists():

        try:

            image = Image.open(path).convert("RGB")

            return ImageOps.fit(
                image,
                size,
                method=Image.Resampling.LANCZOS
            )

        except Exception:

            logger.exception("Background image error")

    image = Image.new(
        "RGB",
        size,
        (19, 22, 32)
    )

    draw = ImageDraw.Draw(image)

    draw.rectangle(
        (0, 0, size[0], 100),
        fill=(29, 35, 52)
    )

    return image


async def get_user_avatar(
    bot: Bot,
    user_id: int,
    size=150
):

    try:

        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1
        )

        if photos.total_count > 0:

            photo = photos.photos[0][-1]

            file = await bot.get_file(photo.file_id)

            buffer = io.BytesIO()

            await bot.download_file(
                file.file_path,
                destination=buffer
            )

            buffer.seek(0)

            avatar = Image.open(buffer).convert("RGBA")

            avatar = ImageOps.fit(
                avatar,
                (size, size),
                method=Image.Resampling.LANCZOS
            )

            return avatar

    except Exception:

        logger.exception(
            "Avatar download failed for %s",
            user_id
        )

    avatar = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(avatar)

    draw.ellipse(
        (2, 2, size - 2, size - 2),
        fill=(125, 130, 145, 255)
    )

    return avatar


def make_round_avatar(avatar: Image.Image):

    avatar = avatar.convert("RGBA")

    mask = Image.new(
        "L",
        avatar.size,
        0
    )

    draw = ImageDraw.Draw(mask)

    draw.ellipse(
        (0, 0, avatar.width - 1, avatar.height - 1),
        fill=255
    )

    avatar.putalpha(mask)

    return avatar


async def generate_profile_image(
    bot: Bot,
    user: dict
):

    width = 900
    height = 600

    image = open_background(
        PROFILE_BACKGROUND,
        (width, height)
    ).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (35, 35, 865, 565),
        radius=30,
        fill=(8, 11, 20, 175),
        outline=(120, 150, 200, 180),
        width=2
    )

    image = Image.alpha_composite(
        image,
        overlay
    )

    avatar = await get_user_avatar(
        bot,
        user["user_id"],
        170
    )

    avatar = make_round_avatar(avatar)

    image.alpha_composite(
        avatar,
        (75, 95)
    )

    draw = ImageDraw.Draw(image)

    title_font = load_font(40)

    normal_font = load_font(27)

    small_font = load_font(21)

    name = user["full_name"][:24]

    draw.text(
        (285, 105),
        name,
        font=title_font,
        fill=(255, 255, 255, 255)
    )

    draw.text(
        (285, 175),
        f"ID: {user['user_id']}",
        font=normal_font,
        fill=(180, 195, 220, 255)
    )

    draw.text(
        (285, 235),
        f"RANK: {user['rank']}",
        font=normal_font,
        fill=(220, 220, 235, 255)
    )

    draw.text(
        (285, 295),
        f"BALANCE: {format_tokens(user['balance'])}",
        font=normal_font,
        fill=(255, 215, 110, 255)
    )

    draw.text(
        (75, 410),
        f"PARTNERS: {user['partners_count']}",
        font=small_font,
        fill=(210, 220, 235, 255)
    )

    draw.text(
        (75, 460),
        f"TOTAL EARNED: {format_tokens(user['total_earned'])}",
        font=small_font,
        fill=(210, 220, 235, 255)
    )

    draw.text(
        (75, 520),
        BOT_NAME,
        font=small_font,
        fill=(140, 160, 195, 255)
    )

    output = io.BytesIO()

    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=92
    )

    output.seek(0)

    return BufferedInputFile(
        output.getvalue(),
        filename="profile.jpg"
    )


async def send_asset(
    message: Message,
    asset_name: str,
    caption: str,
    reply_markup=None
):

    path = ASSETS.get(asset_name)

    if path and path.exists():

        await message.answer_photo(
            FSInputFile(path),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    else:

        await message.answer(
            caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )


# ==============================================================
# USER HELPERS
# ==============================================================

async def get_user_or_none(user_id: int):

    user = await db.get_user(user_id)

    if not user:
        return None

    if user["is_banned"]:
        return None

    return user


async def register_telegram_user(
    bot: Bot,
    telegram_user,
    referral_payload=None
):

    partner_id = parse_referral(referral_payload)

    user = await db.ensure_user(
        user_id=telegram_user.id,
        username=telegram_user.username,
        full_name=telegram_user.full_name,
        partner_id=partner_id
    )

    if (
        partner_id
        and partner_id != telegram_user.id
        and user["partner_id"] == partner_id
    ):

        # Награда начисляется только новому участнику.
        # Повторная регистрация не создаёт повторных наград.
        pass

    return user


async def create_referral_link(
    bot: Bot,
    user_id: int
):

    me = await bot.get_me()

    return (
        f"https://t.me/{me.username}"
        f"?start=ref_{user_id}"
    )


async def require_user(
    message: Message
):

    user = await get_user_or_none(
        message.from_user.id
    )

    if not user:

        await message.answer(
            "Доступ к клубу отсутствует. "
            "Используйте /start для регистрации."
        )

        return None

    return user


# ==============================================================
# START COMMAND
# ==============================================================

@router.message(CommandStart())
async def command_start(
    message: Message,
    bot: Bot
):

    payload = None

    if message.text:

        parts = message.text.split(maxsplit=1)

        if len(parts) > 1:
            payload = parts[1].strip()

    registration_enabled = await db.get_setting(
        "registration_enabled",
        "1"
    )

    existing = await db.get_user(
        message.from_user.id
    )

    if not existing and registration_enabled != "1":

        await message.answer(
            "Регистрация временно закрыта."
        )

        return

    user = await register_telegram_user(
        bot,
        message.from_user,
        payload
    )

    if user["is_banned"]:

        await message.answer(
            "Ваш доступ к клубу ограничен."
        )

        return

    text = (
        f"<b>{BOT_NAME}</b>\n\n"
        f"Добро пожаловать, "
        f"<b>{escape(user['full_name'])}</b>.\n\n"
        "Вы находитесь в закрытом клубном пространстве.\n"
        "Здесь доступны бесплатные мини-игры, "
        "викторины, достижения и рейтинги.\n\n"
        f"Ваш баланс: <code>{format_tokens(user['balance'])}</code>\n"
        f"Ваш статус: <b>{user['rank']}</b>\n\n"
        "Выберите нужный раздел в меню."
    )

    await send_asset(
        message,
        "start",
        text
    )

    await message.answer(
        "Главное меню",
        reply_markup=main_keyboard()
    )


# ==============================================================
# PROFILE
# ==============================================================

async def show_profile(
    message: Message,
    bot: Bot,
    user_id: int
):

    user = await get_user_or_none(user_id)

    if not user:

        await message.answer(
            "Профиль недоступен."
        )

        return

    photo = await generate_profile_image(
        bot,
        user
    )

    await message.answer_photo(
        photo,
        caption=(
            "<b>ВАШ ПРОФИЛЬ</b>\n\n"
            f"Участник: <b>{escape(user['full_name'])}</b>\n"
            f"Баланс: <code>{format_tokens(user['balance'])}</code>\n"
            f"Ранг: <b>{user['rank']}</b>\n"
            f"Партнёры: <code>{user['partners_count']}</code>\n"
            f"Викторина: <code>{user['quiz_correct']}</code> верных ответов"
        ),
        reply_markup=profile_keyboard(),
        parse_mode=ParseMode.HTML
    )


@router.message(F.text == "👤 Профиль")
async def profile_button(
    message: Message,
    bot: Bot
):

    await show_profile(
        message,
        bot,
        message.from_user.id
    )


@router.callback_query(F.data == "profile_refresh")
async def profile_refresh(
    callback: CallbackQuery,
    bot: Bot
):

    await callback.answer()

    user = await get_user_or_none(
        callback.from_user.id
    )

    if not user:
        await callback.message.answer(
            "Профиль недоступен."
        )
        return

    photo = await generate_profile_image(
        bot,
        user
    )

    await callback.message.answer_photo(
        photo,
        caption="Профиль обновлён.",
        reply_markup=profile_keyboard()
    )


@router.callback_query(F.data == "profile_history")
async def profile_history(
    callback: CallbackQuery
):

    await callback.answer()

    history = await db.get_history(
        callback.from_user.id,
        10
    )

    if not history:

        await callback.message.answer(
            "История пока пуста."
        )

        return

    lines = ["<b>ПОСЛЕДНЯЯ АКТИВНОСТЬ</b>\n"]

    for item in history:

        lines.append(
            f"• {escape(item['game_name'])}: "
            f"{escape(item['result'])}\n"
            f"  <code>{format_date(item['created_at'])}</code>"
        )

    await callback.message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "profile_achievements")
async def profile_achievements(
    callback: CallbackQuery
):

    await callback.answer()

    user = await get_user_or_none(
        callback.from_user.id
    )

    if not user:
        return

    achievements = []

    if user["balance"] >= 10000:
        achievements.append("BRONZE BALANCE")

    if user["balance"] >= 50000:
        achievements.append("SILVER BALANCE")

    if user["balance"] >= 150000:
        achievements.append("GOLD BALANCE")

    if user["partners_count"] >= 1:
        achievements.append("FIRST PARTNER")

    if user["partners_count"] >= 5:
        achievements.append("NETWORK BUILDER")

    if user["quiz_correct"] >= 10:
        achievements.append("QUIZ EXPERT")

    if not achievements:
        achievements.append(
            "Пока нет открытых достижений. "
            "Продолжайте участвовать в жизни клуба."
        )

    await callback.message.answer(
        "<b>ВАШИ ДОСТИЖЕНИЯ</b>\n\n"
        + "\n".join(
            f"• {escape(item)}"
            for item in achievements
        ),
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# DAILY BONUS
# ==============================================================

@router.message(F.text == "🎁 Бонус")
async def daily_bonus(
    message: Message
):

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
            (
                "<b>ЕЖЕДНЕВНАЯ НАГРАДА</b>\n\n"
                f"Вам начислено "
                f"<code>+{format_tokens(result)}</code> "
                "бесплатных клубных очков.\n\n"
                "Возвращайтесь через 24 часа."
            )
        )

    else:

        await message.answer(
            "Вы уже получали ежедневную награду.\n\n"
            f"Следующее получение через: "
            f"<b>{human_time(result)}</b>",
            parse_mode=ParseMode.HTML
        )


# ==============================================================
# REFERRALS
# ==============================================================

@router.message(F.text == "🤝 Партнёры")
async def referrals(
    message: Message,
    bot: Bot
):

    user = await require_user(message)

    if not user:
        return

    link = await create_referral_link(
        bot,
        message.from_user.id
    )

    text = (
        "<b>ПАРТНЁРСКАЯ ПРОГРАММА</b>\n\n"
        "Приглашайте знакомых в клуб.\n"
        "Количество приглашённых участников отображается "
        "в Вашем профиле.\n\n"
        f"Ваши партнёры: "
        f"<code>{user['partners_count']}</code>\n\n"
        "<b>Ваша ссылка:</b>\n"
        f"<code>{escape(link)}</code>\n\n"
        "Партнёрская ссылка предназначена "
        "для добровольного приглашения."
    )

    await send_asset(
        message,
        "ref",
        text
    )


# ==============================================================
# TOP
# ==============================================================

@router.message(F.text == "📊 Топ")
async def top_users(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    rows = await db.get_top_users(10)

    if not rows:

        await message.answer(
            "Рейтинг пока пуст."
        )

        return

    lines = [
        "<b>ТОП-10 УЧАСТНИКОВ</b>\n",
        "Рейтинг по количеству клубных очков:\n"
    ]

    for index, item in enumerate(rows, 1):

        lines.append(
            f"<code>{index:02d}.</code> "
            f"<b>{escape(item['full_name'])}</b>\n"
            f"Баланс: "
            f"<code>{format_tokens(item['balance'])}</code>\n"
            f"Ранг: <b>{item['rank']}</b>\n"
        )

    await send_asset(
        message,
        "top",
        "\n".join(lines)
    )


# ==============================================================
# TOURNAMENT
# ==============================================================

@router.message(F.text == "🏆 Турнир")
async def tournament(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    rows = await db.get_tournament_top(10)

    lines = [
        "<b>НЕДЕЛЬНЫЙ ТУРНИР</b>\n",
        "Рейтинг формируется по результатам "
        "интеллектуальной викторины за последние 7 дней.\n"
    ]

    if not rows:

        lines.append("Пока нет результатов.")

    else:

        for index, item in enumerate(rows, 1):

            lines.append(
                f"\n<code>{index:02d}.</code> "
                f"<b>{escape(item['full_name'])}</b>\n"
                f"Очки турнира: "
                f"<code>{format_tokens(item['points'])}</code>"
            )

    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# GAMES MENU
# ==============================================================

@router.message(F.text == "🎮 Игры")
async def games_menu(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    await message.answer(
        "<b>ИГРОВОЙ РАЗДЕЛ</b>\n\n"
        "В клубе доступны бесплатные активности:\n\n"
        "1. Викторина — проверка знаний.\n"
        "2. Кубик — анимация Telegram для развлечения.\n\n"
        "В играх нет ставок, покупки попыток "
        "или потери клубных очков.",
        reply_markup=games_keyboard(),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "game_rules")
async def game_rules(
    callback: CallbackQuery
):

    await callback.answer()

    await callback.message.answer(
        "<b>ПРАВИЛА ИГР</b>\n\n"
        "• Участие бесплатное.\n"
        "• Клубные очки нельзя купить или вывести.\n"
        "• Нельзя поставить баланс на кон.\n"
        "• Результаты викторины учитываются в турнире.\n"
        "• Запрещены автоматические ответы и спам.",
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# QUIZ
# ==============================================================

def quiz_keyboard(
    question_index: int,
    answers: list[str]
):

    buttons = []

    for index, answer in enumerate(answers):

        buttons.append([
            InlineKeyboardButton(
                text=answer,
                callback_data=(
                    f"quiz_{question_index}_{index}"
                )
            )
        ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


async def start_quiz(
    message: Message,
    user_id: int
):

    if user_id in ACTIVE_QUIZZES:

        await message.answer(
            "У Вас уже запущена викторина."
        )

        return

    question = random.choice(QUIZ_QUESTIONS)

    question_id = secrets.token_hex(4)

    ACTIVE_QUIZZES[user_id] = {
        "question": question,
        "question_id": question_id,
        "created_at": current_time(),
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=answer,
                    callback_data=(
                        f"quiz_{question_id}_{index}"
                    )
                )
            ]
            for index, answer in enumerate(
                question["answers"]
            )
        ]
    )

    await message.answer(
        "<b>ВОПРОС ВИКТОРИНЫ</b>\n\n"
        f"{escape(question['question'])}",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "game_quiz")
async def quiz_button(
    callback: CallbackQuery
):

    await callback.answer()

    user = await get_user_or_none(
        callback.from_user.id
    )

    if not user:
        return

    await start_quiz(
        callback.message,
        callback.from_user.id
    )


@router.callback_query(F.data.startswith("quiz_"))
async def quiz_answer(
    callback: CallbackQuery
):

    parts = callback.data.split("_")

    if len(parts) != 3:
        await callback.answer("Некорректный ответ.")
        return

    question_id = parts[1]

    answer_index = safe_int(parts[2], -1)

    user_id = callback.from_user.id

    active = ACTIVE_QUIZZES.get(user_id)

    if not active:

        await callback.answer(
            "Вопрос уже завершён.",
            show_alert=True
        )

        return

    if active["question_id"] != question_id:

        await callback.answer(
            "Этот вопрос уже неактуален.",
            show_alert=True
        )

        return

    ACTIVE_QUIZZES.pop(user_id, None)

    question = active["question"]

    correct = question["correct"]

    if answer_index == correct:

        reward = 250

        await db.add_reward(
            user_id,
            reward,
            "Награда за правильный ответ",
            "QUIZ_REWARD"
        )

        async with aiosqlite.connect(DB_PATH) as connection:

            await connection.execute(
                """
                UPDATE users
                SET quiz_points = quiz_points + 1,
                    quiz_correct = quiz_correct + 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            await connection.commit()

        await db.log_game(
            user_id,
            "Викторина",
            "Правильный ответ",
            1
        )

        text = (
            "<b>ВЕРНО!</b>\n\n"
            f"Начислено: <code>+{reward}</code> "
            "бесплатных клубных очков.\n"
            "В турнир добавлено 1 очко."
        )

    else:

        await db.log_game(
            user_id,
            "Викторина",
            "Неверный ответ",
            0
        )

        correct_text = question["answers"][correct]

        text = (
            "<b>ОТВЕТ НЕВЕРНЫЙ</b>\n\n"
            f"Правильный ответ: "
            f"<b>{escape(correct_text)}</b>\n\n"
            "Попробуйте следующий вопрос."
        )

    await callback.answer()

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# DICE - ENTERTAINMENT ONLY
# ==============================================================

@router.callback_query(F.data == "game_dice")
async def dice_button(
    callback: CallbackQuery,
    bot: Bot
):

    await callback.answer()

    user_id = callback.from_user.id

    user = await get_user_or_none(user_id)

    if not user:
        return

    lock = USER_ACTION_LOCKS.setdefault(
        user_id,
        asyncio.Lock()
    )

    if lock.locked():

        await callback.message.answer(
            "Дождитесь завершения предыдущей активности."
        )

        return

    async with lock:

        await bot.send_dice(
            chat_id=callback.message.chat.id,
            emoji="🎲"
        )

        await db.log_game(
            user_id,
            "Кубик",
            "Развлекательный бросок",
            0
        )


# ==============================================================
# DONATE / CLUB INFORMATION
# ==============================================================

@router.message(F.text == "💎 Донат")
async def donate_info(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    text = (
        "<b>ПОДДЕРЖКА TOKENS | PRIVATE CLUB</b>\n\n"
        "Этот раздел содержит информацию о клубе.\n\n"
        "Клубные очки выдаются бесплатно за активность "
        "и не являются деньгами, платёжным средством "
        "или финансовым активом.\n\n"
        "В этой версии бота нет покупки очков, "
        "платных игровых попыток или денежных переводов.\n\n"
        "Вы можете поддержать развитие сообщества "
        "участием в обсуждениях и приглашением знакомых."
    )

    await send_asset(
        message,
        "donate",
        text
    )


# ==============================================================
# CHATS
# ==============================================================

@router.message(F.text == "💬 Чаты")
async def chats(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть чат клуба",
                    url=CLUB_CHAT_URL
                )
            ]
        ]
    )

    await send_asset(
        message,
        "chats",
        (
            "<b>СООБЩЕСТВО</b>\n\n"
            "Присоединяйтесь к обсуждениям "
            "и знакомьтесь с участниками клуба."
        ),
        keyboard
    )


# ==============================================================
# SUPPORT
# ==============================================================

@router.message(F.text == "🆘 Поддержка")
async def support(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Связаться с поддержкой",
                    url=SUPPORT_URL
                )
            ]
        ]
    )

    await send_asset(
        message,
        "support",
        (
            "<b>СЛУЖБА ПОДДЕРЖКИ</b>\n\n"
            "Если у Вас возник вопрос по работе бота, "
            "обратитесь в службу поддержки."
        ),
        keyboard
    )


# ==============================================================
# HELP
# ==============================================================

@router.message(Command("help"))
async def help_command(
    message: Message
):

    text = (
        f"<b>{BOT_NAME}</b>\n\n"
        "<b>Пользовательские команды</b>\n"
        "/start — главное меню\n"
        "/profile — профиль\n"
        "/bonus — ежедневная награда\n"
        "/top — рейтинг\n"
        "/quiz — викторина\n"
        "/help — помощь\n\n"
        "Также используйте кнопки меню."
    )

    if is_admin(message.from_user.id):

        text += (
            "\n\n<b>Команды администратора</b>\n"
            "/admin — панель\n"
            "/stats — статистика\n"
            "/give ID AMOUNT — бесплатная награда\n"
            "/ban ID — ограничить доступ\n"
            "/unban ID — восстановить доступ\n"
            "/backup — резервная копия\n"
            "/broadcast — рассылка"
        )

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )


@router.message(Command("profile"))
async def profile_command(
    message: Message,
    bot: Bot
):

    await show_profile(
        message,
        bot,
        message.from_user.id
    )


@router.message(Command("bonus"))
async def bonus_command(
    message: Message
):

    await daily_bonus(message)


@router.message(Command("top"))
async def top_command(
    message: Message
):

    await top_users(message)


@router.message(Command("quiz"))
async def quiz_command(
    message: Message
):

    user = await require_user(message)

    if not user:
        return

    await start_quiz(
        message,
        message.from_user.id
    )


# ==============================================================
# ADMIN ACCESS
# ==============================================================

async def admin_required(
    message: Message
) -> bool:

    if not is_admin(message.from_user.id):

        await message.answer(
            "У Вас нет доступа к этой команде."
        )

        return False

    return True


@router.message(Command("admin"))
async def admin_panel(
    message: Message
):

    if not await admin_required(message):
        return

    await message.answer(
        "<b>ADMIN PANEL</b>\n\n"
        "Панель управления клубом.",
        reply_markup=admin_keyboard(),
        parse_mode=ParseMode.HTML
    )


@router.message(Command("stats"))
async def admin_stats_command(
    message: Message
):

    if not await admin_required(message):
        return

    stats = await db.get_stats()

    await message.answer(
        "<b>СТАТИСТИКА КЛУБА</b>\n\n"
        f"Участников: <code>{stats['users']}</code>\n"
        f"Всего очков: "
        f"<code>{format_tokens(stats['balance'])}</code>\n"
        f"Очков викторины: "
        f"<code>{format_tokens(stats['quiz_points'])}</code>\n"
        f"Партнёров: <code>{stats['partners']}</code>",
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(
    callback: CallbackQuery
):

    await callback.answer()

    if not is_admin(callback.from_user.id):
        return

    stats = await db.get_stats()

    await callback.message.answer(
        "<b>СТАТИСТИКА</b>\n\n"
        f"Участников: <code>{stats['users']}</code>\n"
        f"Баланс: <code>{format_tokens(stats['balance'])}</code>\n"
        f"Партнёров: <code>{stats['partners']}</code>",
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# ADMIN: GIVE FREE REWARD
# ==============================================================

@router.message(Command("give"))
async def admin_give(
    message: Message
):

    if not await admin_required(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 3:

        await message.answer(
            "Использование:\n"
            "<code>/give USER_ID AMOUNT</code>\n\n"
            "Лимит одной бесплатной награды: "
            f"<code>{MAX_FREE_REWARD}</code>",
            parse_mode=ParseMode.HTML
        )

        return

    target_id = safe_int(parts[1])

    amount = safe_int(parts[2])

    if target_id <= 0 or amount <= 0:

        await message.answer(
            "Некорректный ID или сумма."
        )

        return

    if amount > MAX_FREE_REWARD:

        await message.answer(
            f"Максимальная награда — "
            f"<code>{MAX_FREE_REWARD}</code>.",
            parse_mode=ParseMode.HTML
        )

        return

    target = await db.get_user(target_id)

    if not target:

        await message.answer(
            "Пользователь не найден."
        )

        return

    success = await db.add_reward(
        target_id,
        amount,
        "Бесплатная награда администратора",
        "ADMIN_REWARD"
    )

    if not success:

        await message.answer(
            "Не удалось начислить награду."
        )

        return

    await db.log_admin(
        message.from_user.id,
        "GIVE_REWARD",
        target_id,
        str(amount)
    )

    await message.answer(
        "Награда начислена.\n"
        f"Пользователь: <code>{target_id}</code>\n"
        f"Количество: <code>+{amount}</code>",
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# ADMIN: BAN / UNBAN
# ==============================================================

@router.message(Command("ban"))
async def admin_ban(
    message: Message
):

    if not await admin_required(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:

        await message.answer(
            "Использование: <code>/ban USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

        return

    target_id = safe_int(parts[1])

    if target_id <= 0 or target_id == ADMIN_ID:

        await message.answer(
            "Недопустимый ID."
        )

        return

    target = await db.get_user(target_id)

    if not target:

        await message.answer(
            "Пользователь не найден."
        )

        return

    await db.set_banned(target_id, True)

    await db.log_admin(
        message.from_user.id,
        "BAN",
        target_id
    )

    await message.answer(
        f"Доступ пользователя <code>{target_id}</code> ограничен.",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("unban"))
async def admin_unban(
    message: Message
):

    if not await admin_required(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:

        await message.answer(
            "Использование: <code>/unban USER_ID</code>",
            parse_mode=ParseMode.HTML
        )

        return

    target_id = safe_int(parts[1])

    if target_id <= 0:
        await message.answer("Некорректный ID.")
        return

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Пользователь не найден.")
        return

    await db.set_banned(target_id, False)

    await db.log_admin(
        message.from_user.id,
        "UNBAN",
        target_id
    )

    await message.answer(
        f"Доступ пользователя <code>{target_id}</code> восстановлен.",
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# ADMIN: BACKUP
# ==============================================================

@router.message(Command("backup"))
async def admin_backup(
    message: Message
):

    if not await admin_required(message):
        return

    try:

        path = await db.backup()

        await db.log_admin(
            message.from_user.id,
            "BACKUP",
            details=str(path)
        )

        await message.answer_document(
            FSInputFile(path),
            caption="Резервная копия базы данных."
        )

    except Exception:

        logger.exception("Backup failed")

        await message.answer(
            "Не удалось создать резервную копию."
        )


@router.callback_query(F.data == "admin_backup")
async def admin_backup_callback(
    callback: CallbackQuery
):

    await callback.answer()

    if not is_admin(callback.from_user.id):
        return

    try:

        path = await db.backup()

        await callback.message.answer_document(
            FSInputFile(path),
            caption="Резервная копия базы данных."
        )

    except Exception:

        logger.exception("Backup failed")

        await callback.message.answer(
            "Ошибка создания резервной копии."
        )


# ==============================================================
# ADMIN: LOGS
# ==============================================================

@router.callback_query(F.data == "admin_logs")
async def admin_logs(
    callback: CallbackQuery
):

    await callback.answer()

    if not is_admin(callback.from_user.id):
        return

    logs = await db.get_admin_logs(15)

    if not logs:

        await callback.message.answer(
            "Журнал администратора пуст."
        )

        return

    lines = ["<b>ЖУРНАЛ АДМИНИСТРАТОРА</b>\n"]

    for item in logs:

        lines.append(
            f"<code>{item['id']}</code> "
            f"<b>{escape(item['action'])}</b>\n"
            f"Администратор: "
            f"<code>{item['admin_id']}</code>\n"
            f"Цель: "
            f"<code>{item['target_id'] or '—'}</code>\n"
            f"Дата: "
            f"<code>{format_date(item['created_at'])}</code>\n"
        )

    await callback.message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# ADMIN: BROADCAST
# ==============================================================

@router.message(Command("broadcast"))
async def admin_broadcast_start(
    message: Message,
    state: FSMContext
):

    if not await admin_required(message):
        return

    await state.set_state(
        AdminStates.waiting_for_broadcast
    )

    await message.answer(
        "Отправьте текст объявления.\n"
        "Для отмены используйте /cancel."
    )


@router.message(
    AdminStates.waiting_for_broadcast,
    Command("cancel")
)
async def admin_broadcast_cancel(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "Рассылка отменена."
    )


@router.message(
    AdminStates.waiting_for_broadcast,
    F.text
)
async def admin_broadcast_send(
    message: Message,
    state: FSMContext,
    bot: Bot
):

    if not is_admin(message.from_user.id):

        await state.clear()

        return

    text = message.text.strip()

    if not text or len(text) > 4000:

        await message.answer(
            "Текст должен содержать от 1 до 4000 символов."
        )

        return

    await state.clear()

    user_ids = await db.get_all_user_ids()

    sent = 0
    failed = 0

    status = await message.answer(
        "Рассылка запущена."
    )

    for user_id in user_ids:

        try:

            await bot.send_message(
                user_id,
                text
            )

            sent += 1

        except Exception:

            failed += 1

        await asyncio.sleep(0.04)

    await db.log_admin(
        message.from_user.id,
        "BROADCAST",
        details=f"sent={sent}; failed={failed}"
    )

    await status.edit_text(
        "Рассылка завершена.\n\n"
        f"Отправлено: <code>{sent}</code>\n"
        f"Ошибок: <code>{failed}</code>",
        parse_mode=ParseMode.HTML
    )


# ==============================================================
# ADMIN: MAINTENANCE
# ==============================================================

@router.message(Command("maintenance"))
async def admin_maintenance(
    message: Message
):

    if not await admin_required(message):
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
        value
    )

    await db.log_admin(
        message.from_user.id,
        "MAINTENANCE",
        details=value
    )

    await message.answer(
        "Технический режим включён."
        if value == "1"
        else "Технический режим выключен."
    )


# ==============================================================
# MAINTENANCE MIDDLEWARE-LIKE CHECK
# ==============================================================

@router.message()
async def fallback_message(
    message: Message
):

    if not message.from_user:
        return

    maintenance = await db.get_setting(
        "maintenance",
        "0"
    )

    if maintenance == "1" and not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "В клубе проводятся технические работы. "
            "Попробуйте позже."
        )

        return

    await message.answer(
        "Не удалось распознать команду.\n"
        "Используйте кнопки меню или /help.",
        reply_markup=main_keyboard()
    )


# ==============================================================
# SCHEDULED TASKS
# ==============================================================

async def scheduled_cleanup():

    try:

        deleted = await db.cleanup(90)

        logger.info(
            "Cleanup completed. Deleted rows: %s",
            deleted
        )

    except Exception:

        logger.exception("Scheduled cleanup failed")


async def scheduled_backup():

    try:

        path = await db.backup()

        logger.info(
            "Scheduled backup created: %s",
            path
        )

        backups = sorted(
            BACKUP_DIR.glob("tokens_*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True
        )

        for old_backup in backups[10:]:

            try:
                old_backup.unlink()
            except OSError:
                pass

    except Exception:

        logger.exception("Scheduled backup failed")


async def scheduled_event_drop(bot: Bot):

    enabled = await db.get_setting(
        "auto_drop_enabled",
        "0"
    )

    if enabled != "1":
        return

    amount = safe_int(
        await db.get_setting(
            "auto_drop_amount",
            "1000"
        ),
        1000
    )

    amount = max(
        1,
        min(amount, MAX_FREE_REWARD)
    )

    user_ids = await db.get_all_user_ids()

    if not user_ids:
        return

    target_id = random.choice(user_ids)

    success = await db.add_reward(
        target_id,
        amount,
        "Автоматическая клубная награда",
        "EVENT_REWARD"
    )

    if not success:
        return

    try:

        await bot.send_message(
            target_id,
            "Вам начислена бесплатная награда "
            "за участие в жизни клуба: "
            f"<code>+{amount}</code> очков.",
            parse_mode=ParseMode.HTML
        )

    except Exception:

        logger.warning(
            "Could not notify drop recipient %s",
            target_id
        )


# ==============================================================
# HTTP HEALTH CHECK
# ==============================================================

async def health_handler(request):

    return web.json_response({
        "status": "ok",
        "service": BOT_NAME,
        "version": VERSION,
        "time": current_time(),
    })


async def start_http_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health_handler
    )

    app.router.add_get(
        "/health",
        health_handler
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logger.info(
        "HTTP server started on port %s",
        PORT
    )

    return runner


# ==============================================================
# ERROR HANDLER
# ==============================================================

async def global_error_handler(
    event,
    exception
):

    logger.exception(
        "Unhandled Telegram update error",
        exc_info=exception
    )

    try:

        if ADMIN_ID:

            bot = event.bot if hasattr(
                event,
                "bot"
            ) else None

            if bot:

                await bot.send_message(
                    ADMIN_ID,
                    "В боте произошла ошибка.\n"
                    f"<code>{escape(str(exception)[:1000])}</code>",
                    parse_mode=ParseMode.HTML
                )

    except Exception:

        logger.exception(
            "Could not notify administrator"
        )

    return True


# ==============================================================
# BOT INITIALIZATION
# ==============================================================

async def setup_bot():

    if not BOT_TOKEN:

        raise RuntimeError(
            "Не задан BOT_TOKEN. "
            "Добавьте токен в переменные окружения."
        )

    if ADMIN_ID <= 0:

        logger.warning(
            "ADMIN_ID is not configured. "
            "Admin commands will be unavailable."
        )

    await db.connect()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    dispatcher = Dispatcher(
        storage=storage
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
        id="database_cleanup",
        replace_existing=True
    )

    scheduler.add_job(
        scheduled_backup,
        "cron",
        hour=3,
        minute=0,
        id="database_backup",
        replace_existing=True
    )

    scheduler.start()

    http_runner = await start_http_server()

    logger.info(
        "%s v%s started",
        BOT_NAME,
        VERSION
    )

    return bot, dispatcher, http_runner


# ==============================================================
# MAIN
# ==============================================================

async def main():

    bot = None

    http_runner = None

    try:

        bot, dispatcher, http_runner = await setup_bot()

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False
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

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        pass

    except Exception:

        logger.exception("Application terminated")
