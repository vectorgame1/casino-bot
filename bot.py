
# ============================================================
# TOKENS | PRIVATE CLUB
# Complete Telegram Bot
# Python 3.11+ | aiogram 3.x
# ============================================================

import asyncio
import logging
import os
import time
import io
import json
import random
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

from aiogram.enums import (
    ParseMode,
)

from aiogram.client.default import (
    DefaultBotProperties,
)

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
    InputMediaPhoto,
)

from aiogram.fsm.state import (
    State,
    StatesGroup,
)

from aiogram.fsm.context import FSMContext

from aiogram.fsm.storage.memory import (
    MemoryStorage,
)

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)

from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PORT = int(os.getenv("PORT", "8080"))

DB_PATH = os.getenv(
    "DB_PATH",
    "data/tokens_club.db"
)

CLUB_NAME = "TOKENS | PRIVATE CLUB"

DAILY_BONUS = 5000

CACHE_TTL = 5

MAX_BALANCE = 10**12

UTC = timezone.utc

BASE_DIR = Path(__file__).resolve().parent

ASSETS_DIR = BASE_DIR / "assets"

PROFILE_BG = ASSETS_DIR / "profile_bg.jpg"

PROFILE_FONT = ASSETS_DIR / "Montserrat-Bold.ttf"

NO_AVATAR = ASSETS_DIR / "no_avatar.png"

SUPPORT_URL = os.getenv(
    "SUPPORT_URL",
    "https://t.me/"
)

CLUB_CHAT_URL = os.getenv(
    "CLUB_CHAT_URL",
    "https://t.me/"
)

logger = logging.getLogger("TOKENS")

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    )
)


# ============================================================
# CONSTANTS
# ============================================================

RANKS = [
    (0, "MEMBER"),
    (10000, "BRONZE"),
    (50000, "SILVER"),
    (150000, "GOLD"),
    (500000, "PLATINUM"),
    (1000000, "DIAMOND"),
]

GAMES = {
    "кости": "Кости",
    "дартс": "Дартс",
    "баскет": "Баскетбол",
    "футбол": "Футбол",
    "боулинг": "Боулинг",
    "слоты": "Слоты",
}

GAME_REWARDS = {
    "dice": 500,
    "dart": 700,
    "basketball": 800,
    "football": 600,
    "bowling": 700,
    "slots": 1000,
}

DAILY_BONUS_SECONDS = 86400

MAX_GAME_REWARD = 10000

PROFILE_SIZE = (900, 500)


# ============================================================
# HELPERS
# ============================================================

def now() -> int:
    return int(time.time())


def format_tokens(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def get_rank(balance: int) -> str:
    result = "MEMBER"

    for threshold, rank in RANKS:
        if balance >= threshold:
            result = rank

    return result


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID and ADMIN_ID != 0


def parse_referral(value: Optional[str]) -> Optional[int]:
    if not value:
        return None

    if not value.startswith("ref_"):
        return None

    try:
        result = int(value[4:])
        return result if result > 0 else None
    except ValueError:
        return None


def human_time(seconds: int) -> str:
    seconds = max(0, seconds)

    hours, remainder = divmod(seconds, 3600)

    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours} ч. {minutes} мин."

    if minutes:
        return f"{minutes} мин. {secs} сек."

    return f"{secs} сек."


def escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ============================================================
# DATABASE
# ============================================================

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

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as connection:

                await connection.execute(
                    "PRAGMA journal_mode=WAL"
                )

                await connection.execute(
                    "PRAGMA foreign_keys=ON"
                )

                await connection.execute(
                    "PRAGMA busy_timeout=5000"
                )

                await connection.execute(
                    "PRAGMA synchronous=NORMAL"
                )

                await self.create_tables(connection)

                await connection.commit()

        logger.info("Database initialized.")

    async def create_tables(self, connection):

        await connection.executescript("""

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

            created_at INTEGER NOT NULL,

            last_seen INTEGER NOT NULL,

            daily_bonus_at INTEGER NOT NULL DEFAULT 0,

            total_earned INTEGER NOT NULL DEFAULT 0,

            games_played INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS game_log (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            game_name TEXT NOT NULL,

            result TEXT NOT NULL,

            points INTEGER NOT NULL DEFAULT 0,

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

        CREATE INDEX IF NOT EXISTS idx_game_created
        ON game_log(created_at);

        CREATE INDEX IF NOT EXISTS idx_game_user
        ON game_log(user_id);

        CREATE INDEX IF NOT EXISTS idx_transactions_user
        ON transactions(user_id);

        CREATE INDEX IF NOT EXISTS idx_users_partner
        ON users(partner_id);

        """)

        defaults = {
            "maintenance": "0",
            "happy_hour": "0",
            "club_name": CLUB_NAME,
            "daily_bonus": str(DAILY_BONUS),
        }

        for key, value in defaults.items():

            await connection.execute(
                """
                INSERT OR IGNORE INTO settings
                (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, now())
            )

    def invalidate(self, user_id: int):

        self.cache.pop(user_id, None)

        self.cache_time.pop(user_id, None)

    async def get_user(
        self,
        user_id: int
    ) -> Optional[dict]:

        cached = self.cache.get(user_id)

        if cached:

            if time.monotonic() - self.cache_time.get(
                user_id,
                0
            ) < CACHE_TTL:

                return cached.copy()

        async with aiosqlite.connect(
            self.path
        ) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT *
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            ) as cursor:

                row = await cursor.fetchone()

        if not row:
            return None

        result = dict(row)

        self.cache[user_id] = result

        self.cache_time[user_id] = time.monotonic()

        return result.copy()

    async def ensure_user(
        self,
        user_id: int,
        username: Optional[str],
        full_name: str,
        partner_id: Optional[int] = None
    ) -> dict:

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as connection:

                connection.row_factory = aiosqlite.Row

                try:

                    async with connection.execute(
                        "BEGIN TRANSACTION;"
                    ):

                        async with connection.execute(
                            """
                            SELECT user_id
                            FROM users
                            WHERE user_id = ?
                            """,
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
                                    full_name,
                                    now(),
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
                                    balance,
                                    rank,
                                    partner_id,
                                    created_at,
                                    last_seen
                                )
                                VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                                """,
                                (
                                    user_id,
                                    username,
                                    full_name,
                                    "MEMBER",
                                    valid_partner,
                                    now(),
                                    now()
                                )
                            )

                            if valid_partner:

                                await connection.execute(
                                    """
                                    UPDATE users
                                    SET partners_count =
                                        partners_count + 1
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

        result = await self.get_user(user_id)

        if result is None:
            raise RuntimeError("User registration failed.")

        return result

    async def change_balance(
        self,
        user_id: int,
        amount: int,
        description: str = "Награда клуба",
        transaction_type: str = "REWARD"
    ) -> bool:

        """
        Безопасное начисление бесплатных TOKENS.

        Отрицательные изменения запрещены.
        Это исключает использование метода
        для денежных ставок и игровых взносов.
        """

        if amount <= 0:
            raise ValueError("Некорректный размер награды.")

        if amount > MAX_GAME_REWARD:
            raise ValueError("Превышен лимит одной награды.")

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as connection:

                try:

                    async with connection.execute(
                        "BEGIN TRANSACTION;"
                    ):

                        async with connection.execute(
                            """
                            SELECT is_banned, balance
                            FROM users
                            WHERE user_id = ?
                            """,
                            (user_id,)
                        ) as cursor:

                            user = await cursor.fetchone()

                        if not user or user[0]:

                            await connection.rollback()

                            return False

                        if user[1] + amount > MAX_BALANCE:

                            await connection.rollback()

                            return False

                        await connection.execute(
                            """
                            UPDATE users
                            SET balance = balance + ?,
                                total_earned = total_earned + ?
                            WHERE user_id = ?
                            """,
                            (amount, amount, user_id)
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
                                transaction_type,
                                description,
                                now()
                            )
                        )

                        await connection.commit()

                except Exception:

                    await connection.rollback()

                    raise

        self.invalidate(user_id)

        return True

    async def log_game(
        self,
        user_id: int,
        game_name: str,
        result: str,
        points: int = 0
    ):

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as connection:

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
                        game_name,
                        result,
                        points,
                        now()
                    )
                )

                await connection.execute(
                    """
                    UPDATE users
                    SET games_played = games_played + 1
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await connection.commit()

        self.invalidate(user_id)

    async def log_admin(
        self,
        admin_id: int,
        action: str,
        target_id: Optional[int] = None,
        details: str = ""
    ):

        async with aiosqlite.connect(
            self.path
        ) as connection:

            await connection.execute(
                """
                INSERT INTO admin_log (
                    admin_id,
                    action,
                    target_id,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    admin_id,
                    action,
                    target_id,
                    details,
                    now()
                )
            )

            await connection.commit()

    async def claim_daily(
        self,
        user_id: int
    ) -> tuple[bool, int]:

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as connection:

                try:

                    async with connection.execute(
                        "BEGIN TRANSACTION;"
                    ):

                        async with connection.execute(
                            """
                            SELECT last_claim
                            FROM daily_bonus
                            WHERE user_id = ?
                            """,
                            (user_id,)
                        ) as cursor:

                            row = await cursor.fetchone()

                        last = row[0] if row else 0

                        remaining = 86400 - (now() - last)

                        if remaining > 0:

                            await connection.rollback()

                            return False, remaining

                        async with connection.execute(
                            """
                            SELECT is_banned
                            FROM users
                            WHERE user_id = ?
                            """,
                            (user_id,)
                        ) as cursor:

                            user = await cursor.fetchone()

                        if not user or user[0]:

                            await connection.rollback()

                            return False, 0

                        await connection.execute(
                            """
                            UPDATE users
                            SET balance = balance + ?,
                                total_earned = total_earned + ?
                            WHERE user_id = ?
                            """,
                            (
                                DAILY_BONUS,
                                DAILY_BONUS,
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
                                now(),
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
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                DAILY_BONUS,
                                "DAILY_BONUS",
                                "Ежедневная награда",
                                now()
                            )
                        )

                        await connection.commit()

                except Exception:

                    await connection.rollback()

                    raise

        self.invalidate(user_id)

        return True, DAILY_BONUS

    async def get_setting(
        self,
        key: str,
        default: str = ""
    ) -> str:

        async with aiosqlite.connect(
            self.path
        ) as connection:

            async with connection.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                """,
                (key,)
            ) as cursor:

                row = await cursor.fetchone()

        return row[0] if row else default

    async def set_setting(
        self,
        key: str,
        value: str
    ):

        async with aiosqlite.connect(
            self.path
        ) as connection:

            await connection.execute(
                """
                INSERT INTO settings (
                    key,
                    value,
                    updated_at
                )
                VALUES (?, ?, ?)

                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now())
            )

            await connection.commit()

    async def get_top(
        self,
        limit: int = 10
    ) -> list[dict]:

        async with aiosqlite.connect(
            self.path
        ) as connection:

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

    async def get_tournament_top(
        self,
        limit: int = 10
    ) -> list[dict]:

        week_ago = now() - 7 * 86400

        async with aiosqlite.connect(
            self.path
        ) as connection:

            connection.row_factory = aiosqlite.Row

            async with connection.execute(
                """
                SELECT
                    u.user_id,
                    u.username,
                    u.full_name,
                    COALESCE(SUM(
                        CASE WHEN g.points > 0
                        THEN g.points ELSE 0 END
                    ), 0) AS points
                FROM users u
                LEFT JOIN game_log g
                    ON g.user_id = u.user_id
                    AND g.created_at >= ?
                WHERE u.is_banned = 0
                GROUP BY u.user_id
                ORDER BY points DESC
                LIMIT ?
                """,
                (week_ago, limit)
            ) as cursor:

                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_stats(self) -> dict:

        async with aiosqlite.connect(
            self.path
        ) as connection:

            async with connection.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(balance), 0),
                    COALESCE(SUM(games_played), 0)
                FROM users
                """
            ) as cursor:

                row = await cursor.fetchone()

        return {
            "users": row[0],
            "balance": row[1],
            "games": row[2]
        }

    async def backup(self) -> str:

        filename = (
            f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )

        async with self.lock:

            async with aiosqlite.connect(
                self.path
            ) as source:

                async with aiosqlite.connect(
                    filename
                ) as target:

                    await source.backup(target)

        return filename


db = Database(DB_PATH)


# ============================================================
# FSM
# ============================================================

class ClubStates(StatesGroup):

    waiting_for_amount = State()

    waiting_for_broadcast = State()

    waiting_for_username = State()


# ============================================================
# TELEGRAM INITIALIZATION
# ============================================================

router = Router(name="private_club")

storage = MemoryStorage()

dp = Dispatcher(storage=storage)

dp.include_router(router)

bot = None

scheduler = AsyncIOScheduler(timezone="UTC")


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎮 Игры"),
                KeyboardButton(text="🎁 Бонус")
            ],
            [
                KeyboardButton(text="💎 Донат"),
                KeyboardButton(text="👤 Профиль")
            ],
            [
                KeyboardButton(text="🤝 Партнёры"),
                KeyboardButton(text="🏆 Турнир")
            ],
            [
                KeyboardButton(text="📊 Топ"),
                KeyboardButton(text="💬 Чаты")
            ],
            [
                KeyboardButton(text="🆘 Поддержка")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="TOKENS | PRIVATE CLUB"
    )


def profile_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="История активности",
                    callback_data="profile_history"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мои достижения",
                    callback_data="profile_achievements"
                )
            ]
        ]
    )


def games_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Кости",
                    callback_data="game_dice"
                ),
                InlineKeyboardButton(
                    text="Дартс",
                    callback_data="game_dart"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Баскетбол",
                    callback_data="game_basket"
                ),
                InlineKeyboardButton(
                    text="Футбол",
                    callback_data="game_football"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Боулинг",
                    callback_data="game_bowling"
                ),
                InlineKeyboardButton(
                    text="Викторина",
                    callback_data="game_quiz"
                )
            ]
        ]
    )


# ============================================================
# PROFILE IMAGE
# ============================================================

async def get_user_avatar(
    user_id: int
) -> Image.Image:

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

            return Image.open(buffer).convert("RGBA")

    except Exception as error:

        logger.warning(
            "Avatar download failed: %s",
            error
        )

    try:

        if NO_AVATAR.exists():

            return Image.open(
                NO_AVATAR
            ).convert("RGBA")

    except Exception:
        pass

    return Image.new(
        "RGBA",
        (300, 300),
        (55, 60, 75, 255)
    )


def load_font(size: int):

    try:

        if PROFILE_FONT.exists():

            return ImageFont.truetype(
                str(PROFILE_FONT),
                size
            )

    except Exception:
        pass

    return ImageFont.load_default()


async def generate_profile_image(
    user: dict
) -> BufferedInputFile:

    width, height = PROFILE_SIZE

    try:

        if PROFILE_BG.exists():

            background = Image.open(
                PROFILE_BG
            ).convert("RGBA")

            background = ImageOps.fit(
                background,
                PROFILE_SIZE
            )

        else:

            background = Image.new(
                "RGBA",
                PROFILE_SIZE,
                (18, 21, 31, 255)
            )

    except Exception:

        background = Image.new(
            "RGBA",
            PROFILE_SIZE,
            (18, 21, 31, 255)
        )

    overlay = Image.new(
        "RGBA",
        PROFILE_SIZE,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (25, 25, width - 25, height - 25),
        radius=28,
        fill=(10, 13, 23, 190),
        outline=(190, 160, 90, 255),
        width=3
    )

    background.alpha_composite(overlay)

    avatar = await get_user_avatar(
        user["user_id"]
    )

    avatar = ImageOps.fit(
        avatar,
        (220, 220)
    )

    mask = Image.new(
        "L",
        (220, 220),
        0
    )

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.ellipse(
        (0, 0, 219, 219),
        fill=255
    )

    background.paste(
        avatar,
        (65, 140),
        mask
    )

    draw = ImageDraw.Draw(background)

    title_font = load_font(34)

    name_font = load_font(28)

    info_font = load_font(22)

    small_font = load_font(18)

    draw.text(
        (330, 65),
        "TOKENS PRIVATE CLUB",
        font=title_font,
        fill=(220, 190, 120)
    )

    draw.text(
        (330, 145),
        str(user["full_name"])[:24],
        font=name_font,
        fill=(255, 255, 255)
    )

    draw.text(
        (330, 205),
        f"ID: {user['user_id']}",
        font=small_font,
        fill=(170, 180, 195)
    )

    draw.text(
        (330, 265),
        f"BALANCE: {format_tokens(user['balance'])}",
        font=info_font,
        fill=(230, 205, 140)
    )

    draw.text(
        (330, 325),
        f"RANK: {user['rank']}",
        font=info_font,
        fill=(255, 255, 255)
    )

    draw.text(
        (330, 380),
        f"PARTNERS: {user['partners_count']}",
        font=small_font,
        fill=(170, 180, 195)
    )

    output = io.BytesIO()

    background.convert("RGB").save(
        output,
        format="JPEG",
        quality=92
    )

    output.seek(0)

    return BufferedInputFile(
        output.read(),
        filename="club_profile.jpg"
    )


# ============================================================
# REGISTRATION
# ============================================================

async def register_message(
    message: Message,
    referral: Optional[int] = None
):

    user = message.from_user

    if user is None:
        return None

    return await db.ensure_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        partner_id=referral
    )


# ============================================================
# START
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message):

    args = message.text.split(maxsplit=1)

    referral = None

    if len(args) > 1:

        referral = parse_referral(
            args[1].strip()
        )

    user = await register_message(
        message,
        referral
    )

    if not user:
        return

    if user["is_banned"]:

        await message.answer(
            "Доступ к клубу ограничен."
        )

        return

    greeting = (
        "TOKENS | PRIVATE CLUB\n\n"
        f"Добро пожаловать, "
        f"{escape_html(user['full_name'])}.\n\n"
        "Ваш профиль клуба успешно активирован.\n\n"
        f"Баланс: `{format_tokens(user['balance'])} TOKENS`\n"
        f"Статус: `{user['rank']}`\n\n"
        "Выберите интересующий Вас раздел."
    )

    await message.answer(
        greeting,
        reply_markup=main_keyboard()
    )


# ============================================================
# ACCESS CHECK
# ============================================================

async def check_access(
    message: Message
) -> bool:

    if not message.from_user:
        return False

    user = await db.get_user(
        message.from_user.id
    )

    if not user:
        return False

    if user["is_banned"]:

        await message.answer(
            "Доступ к клубу ограничен."
        )

        return False

    return True


# ============================================================
# PROFILE
# ============================================================

@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):

    if not await check_access(message):
        return

    user = await db.get_user(
        message.from_user.id
    )

    photo = await generate_profile_image(
        user
    )

    caption = (
        "<b>ЛИЧНЫЙ ПРОФИЛЬ</b>\n\n"
        f"Участник: {escape_html(user['full_name'])}\n"
        f"ID: `{user['user_id']}`\n"
        f"Баланс: `{format_tokens(user['balance'])}` TOKENS\n"
        f"Ранг: `{user['rank']}`\n"
        f"Партнёры: `{user['partners_count']}`\n"
        f"Игры: `{user['games_played']}`"
    )

    await message.answer_photo(
        photo,
        caption=caption,
        reply_markup=profile_keyboard()
    )


@router.callback_query(F.data == "profile_history")
async def profile_history(
    callback: CallbackQuery
):

    async with aiosqlite.connect(
        DB_PATH
    ) as connection:

        connection.row_factory = aiosqlite.Row

        async with connection.execute(
            """
            SELECT game_name, result, points, created_at
            FROM game_log
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (callback.from_user.id,)
        ) as cursor:

            rows = await cursor.fetchall()

    if not rows:

        text = "История активности пока пуста."

    else:

        lines = ["<b>ПОСЛЕДНЯЯ АКТИВНОСТЬ</b>", ""]

        for row in rows:

            date = datetime.fromtimestamp(
                row["created_at"],
                UTC
            ).strftime("%d.%m.%Y %H:%M")

            lines.append(
                f"• {escape_html(row['game_name'])}: "
                f"{escape_html(row['result'])} "
                f"(`{row['points']}` TOKENS)\n"
                f"<code>{date}</code>"
            )

        text = "\n".join(lines)

    await callback.answer()

    await callback.message.answer(text)


@router.callback_query(F.data == "profile_achievements")
async def profile_achievements(
    callback: CallbackQuery
):

    user = await db.get_user(
        callback.from_user.id
    )

    achievements = []

    if user["games_played"] >= 1:
        achievements.append("Первый шаг")

    if user["games_played"] >= 10:
        achievements.append("Активный участник")

    if user["partners_count"] >= 1:
        achievements.append("Партнёр клуба")

    if user["balance"] >= 50000:
        achievements.append("Коллекционер")

    text = (
        "<b>ДОСТИЖЕНИЯ</b>\n\n"
        + (
            "\n".join(
                f"• {item}"
                for item in achievements
            )
            if achievements
            else "Пока нет открытых достижений."
        )
    )

    await callback.answer()

    await callback.message.answer(text)


# ============================================================
# DAILY BONUS
# ============================================================

@router.message(F.text == "🎁 Бонус")
async def bonus_handler(message: Message):

    if not await check_access(message):
        return

    success, result = await db.claim_daily(
        message.from_user.id
    )

    if success:

        await message.answer(
            "<b>ЕЖЕДНЕВНАЯ НАГРАДА</b>\n\n"
            f"На Ваш баланс начислено "
            f"`{format_tokens(result)}` TOKENS.\n\n"
            "Следующая награда будет доступна "
            "через `24 часа`."
        )

    elif result > 0:

        await message.answer(
            "Вы уже получили сегодняшнюю награду.\n\n"
            f"До следующего получения: "
            f"`{human_time(result)}`."
        )

    else:

        await message.answer(
            "Не удалось получить награду. "
            "Проверьте доступ к профилю."
        )


# ============================================================
# PARTNERS
# ============================================================

@router.message(F.text == "🤝 Партнёры")
async def partners_handler(message: Message):

    if not await check_access(message):
        return

    user = await db.get_user(
        message.from_user.id
    )

    me = await bot.get_me()

    referral_link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{message.from_user.id}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Уровни",
                    callback_data="partner_levels"
                )
            ]
        ]
    )

    await message.answer(
        "<b>ПАРТНЁРСКАЯ ПРОГРАММА</b>\n\n"
        f"Ваших партнёров: `{user['partners_count']}`\n\n"
        "Персональная ссылка:\n"
        f"<code>{referral_link}</code>\n\n"
        "Приглашайте новых участников "
        "и открывайте достижения клуба.",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "partner_levels")
async def partner_levels(
    callback: CallbackQuery
):

    await callback.answer()

    await callback.message.answer(
        "<b>УРОВНИ ПАРТНЁРСТВА</b>\n\n"
        "`1` партнёр — Начальный уровень\n"
        "`5` партнёров — Бронзовый уровень\n"
        "`10` партнёров — Серебряный уровень\n"
        "`25` партнёров — Золотой уровень\n"
        "`50` партнёров — Платиновый уровень"
    )


# ============================================================
# GAMES MENU
# ============================================================

@router.message(F.text == "🎮 Игры")
async def games_handler(message: Message):

    if not await check_access(message):
        return

    await message.answer(
        "<b>ИГРОВОЙ ЗАЛ</b>\n\n"
        "Выберите игру.\n\n"
        "За активность можно получать "
        "бесплатные баллы TOKENS.",
        reply_markup=games_keyboard()
    )


# ============================================================
# GAME CALLBACKS
# ============================================================

GAME_CALLBACKS = {
    "game_dice": ("dice", "Кости", "🎲"),
    "game_dart": ("dart", "Дартс", "🎯"),
    "game_basket": ("basketball", "Баскетбол", "🏀"),
    "game_football": ("football", "Футбол", "⚽"),
    "game_bowling": ("bowling", "Боулинг", "🎳"),
}


async def play_free_game(
    callback: CallbackQuery,
    game_key: str,
    game_name: str,
    emoji: str
):

    user = await db.get_user(
        callback.from_user.id
    )

    if not user or user["is_banned"]:

        await callback.answer(
            "Доступ ограничен.",
            show_alert=True
        )

        return

    await callback.answer()

    dice_message = await callback.message.answer_dice(
        emoji=emoji
    )

    await asyncio.sleep(3)

    value = dice_message.dice.value

    points = GAME_REWARDS.get(
        game_key,
        500
    )

    # Награда за участие, а не за игровой взнос.

    if value >= 4:
        points = min(points + 200, MAX_GAME_REWARD)

    awarded = await db.change_balance(
        callback.from_user.id,
        points,
        f"Активность: {game_name}",
        "GAME_REWARD"
    )

    result = (
        f"Результат: {value}. "
        f"Награда: {format_tokens(points)} TOKENS."
        if awarded
        else "Награда не начислена."
    )

    await db.log_game(
        callback.from_user.id,
        game_name,
        result,
        points if awarded else 0
    )

    result_message = await callback.message.answer(
        "<b>РЕЗУЛЬТАТ ИГРЫ</b>\n\n"
        f"{game_name}\n"
        f"Значение: `{value}`\n"
        f"Награда: `{format_tokens(points if awarded else 0)}` TOKENS"
    )

    await asyncio.sleep(15)

    try:
        await dice_message.delete()
        await result_message.delete()
    except Exception:
        pass


for callback_name, data in GAME_CALLBACKS.items():

    game_key, game_name, emoji = data

    async def game_callback(
        callback: CallbackQuery,
        key=game_key,
        name=game_name,
        icon=emoji
    ):

        await play_free_game(
            callback,
            key,
            name,
            icon
        )

    router.callback_query.register(
        game_callback,
        F.data == callback_name
    )


# ============================================================
# QUIZ GAME
# ============================================================

QUIZ = [
    (
        "Сколько дней в високосном году?",
        ["365", "366", "367"],
        1
    ),
    (
        "Сколько сторон у шестиугольника?",
        ["5", "6", "8"],
        1
    ),
    (
        "Как называется столица Франции?",
        ["Париж", "Рим", "Мадрид"],
        0
    ),
    (
        "Сколько минут в одном часе?",
        ["30", "60", "90"],
        1
    ),
]


@router.callback_query(F.data == "game_quiz")
async def quiz_handler(
    callback: CallbackQuery
):

    question, options, answer = random.choice(QUIZ)

    buttons = []

    for index, option in enumerate(options):

        buttons.append([
            InlineKeyboardButton(
                text=option,
                callback_data=f"quiz_{answer}_{index}"
            )
        ])

    await callback.answer()

    await callback.message.answer(
        f"<b>ВИКТОРИНА</b>\n\n{question}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


@router.callback_query(F.data.startswith("quiz_"))
async def quiz_answer(
    callback: CallbackQuery
):

    try:

        _, correct, selected = callback.data.split("_")

        is_correct = int(correct) == int(selected)

    except (ValueError, AttributeError):

        await callback.answer(
            "Некорректный ответ.",
            show_alert=True
        )

        return

    if is_correct:

        points = 1000

        success = await db.change_balance(
            callback.from_user.id,
            points,
            "Награда за викторину",
            "QUIZ_REWARD"
        )

        result = (
            f"Верно! Начислено `{points}` TOKENS."
            if success
            else "Не удалось начислить награду."
        )

    else:

        result = "Ответ неверный. Попробуйте ещё раз."

    await callback.answer(
        result,
        show_alert=True
    )

    try:
        await callback.message.edit_reply_markup(
            reply_markup=None
        )
    except Exception:
        pass


# ============================================================
# DONATION SECTION
# ============================================================

@router.message(F.text == "💎 Донат")
async def donation_handler(message: Message):

    if not await check_access(message):
        return

    await message.answer(
        "<b>ПОДДЕРЖКА КЛУБА</b>\n\n"
        "Раздел финансовых операций не подключён.\n\n"
        "Все TOKENS в текущей версии "
        "начисляются исключительно бесплатно."
    )


# ============================================================
# TOURNAMENT
# ============================================================

@router.message(F.text == "🏆 Турнир")
async def tournament_handler(
    message: Message
):

    if not await check_access(message):
        return

    rows = await db.get_tournament_top(10)

    lines = [
        "<b>НЕДЕЛЬНЫЙ ТУРНИР</b>",
        "",
        "Рейтинг активности за последние `7 дней`.",
        ""
    ]

    if not rows:

        lines.append("Участников пока нет.")

    else:

        for index, row in enumerate(rows, start=1):

            name = escape_html(
                row["username"] or row["full_name"]
            )

            lines.append(
                f"`{index}.` {name} — "
                f"`{format_tokens(row['points'])}` TOKENS"
            )

    lines.extend([
        "",
        "Награды:",
        "`1` место — 500 000 TOKENS",
        "`2` место — 250 000 TOKENS",
        "`3` место — 100 000 TOKENS"
    ])

    await message.answer(
        "\n".join(lines)
    )


# ============================================================
# TOP
# ============================================================

@router.message(F.text == "📊 Топ")
async def top_handler(message: Message):

    if not await check_access(message):
        return

    rows = await db.get_top(10)

    lines = [
        "<b>ТОП УЧАСТНИКОВ КЛУБА</b>",
        ""
    ]

    if not rows:

        lines.append("Рейтинг пока пуст.")

    else:

        for index, row in enumerate(rows, start=1):

            name = escape_html(
                row["username"] or row["full_name"]
            )

            lines.append(
                f"`{index}.` {name}\n"
                f"Баланс: `{format_tokens(row['balance'])}` TOKENS\n"
            )

    await message.answer(
        "\n".join(lines)
    )


# ============================================================
# CHATS
# ============================================================

@router.message(F.text == "💬 Чаты")
async def chats_handler(message: Message):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть клубный чат",
                    url=CLUB_CHAT_URL
                )
            ]
        ]
    )

    await message.answer(
        "<b>СООБЩЕСТВО КЛУБА</b>\n\n"
        "Присоединяйтесь к обсуждениям "
        "и общайтесь с участниками.",
        reply_markup=keyboard
    )


# ============================================================
# SUPPORT
# ============================================================

@router.message(F.text == "🆘 Поддержка")
async def support_handler(message: Message):

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

    await message.answer(
        "<b>СЛУЖБА ПОДДЕРЖКИ</b>\n\n"
        "Если у Вас возник вопрос, "
        "обратитесь к администрации клуба.",
        reply_markup=keyboard
    )


# ============================================================
# ADMIN DECORATOR HELPER
# ============================================================

async def admin_required(
    message: Message
) -> bool:

    if not message.from_user:
        return False

    if not is_admin(message.from_user.id):

        await message.answer(
            "У Вас нет доступа к этому разделу."
        )

        return False

    return True


# ============================================================
# ADMIN HELP
# ============================================================

@router.message(Command("admin"))
async def admin_help(message: Message):

    if not await admin_required(message):
        return

    await message.answer(
        "<b>АДМИНИСТРАТИВНЫЙ ЦЕНТР</b>\n\n"
        "`/give ID AMOUNT` — начислить бесплатные баллы\n"
        "`/balance ID` — баланс участника\n"
        "`/user ID` — профиль участника\n"
        "`/ban ID` — ограничить доступ\n"
        "`/unban ID` — восстановить доступ\n"
        "`/stats` — статистика\n"
        "`/backup` — резервная копия\n"
        "`/broadcast` — информационная рассылка\n"
        "`/maintenance` — режим обслуживания\n"
    )


# ============================================================
# ADMIN GIVE
# ============================================================

@router.message(Command("give"))
async def admin_give(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Формат: `/give ID AMOUNT`"
        )

        return

    target_id = safe_int(parts[1])

    amount = safe_int(parts[2])

    if target_id <= 0 or amount <= 0:

        await message.answer(
            "Проверьте ID и размер награды."
        )

        return

    if amount > MAX_GAME_REWARD:

        await message.answer(
            f"Лимит одной операции: `{MAX_GAME_REWARD}` TOKENS."
        )

        return

    success = await db.change_balance(
        target_id,
        amount,
        "Административная награда",
        "ADMIN_REWARD"
    )

    if not success:

        await message.answer(
            "Операция не выполнена. "
            "Проверьте существование профиля."
        )

        return

    await db.log_admin(
        message.from_user.id,
        "GIVE",
        target_id,
        str(amount)
    )

    await message.answer(
        f"Начислено `{format_tokens(amount)}` TOKENS "
        f"участнику `{target_id}`."
    )


# ============================================================
# ADMIN BALANCE
# ============================================================

@router.message(Command("balance"))
async def admin_balance(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Формат: `/balance ID`")
        return

    target_id = safe_int(parts[1])

    user = await db.get_user(target_id)

    if not user:
        await message.answer("Участник не найден.")
        return

    await message.answer(
        f"ID: `{target_id}`\n"
        f"Баланс: `{format_tokens(user['balance'])}` TOKENS"
    )


# ============================================================
# ADMIN USER
# ============================================================

@router.message(Command("user"))
async def admin_user(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Формат: `/user ID`")
        return

    user = await db.get_user(
        safe_int(parts[1])
    )

    if not user:
        await message.answer("Профиль не найден.")
        return

    await message.answer(
        "<b>ПРОФИЛЬ УЧАСТНИКА</b>\n\n"
        f"ID: `{user['user_id']}`\n"
        f"Имя: {escape_html(user['full_name'])}\n"
        f"Username: {escape_html(user['username'] or '-')}\n"
        f"Баланс: `{format_tokens(user['balance'])}`\n"
        f"Ранг: `{user['rank']}`\n"
        f"Партнёры: `{user['partners_count']}`\n"
        f"VIP: `{user['is_vip']}`\n"
        f"Бан: `{user['is_banned']}`"
    )


# ============================================================
# ADMIN BAN
# ============================================================

async def set_ban(
    message: Message,
    banned: bool
):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Укажите ID участника.")
        return

    target_id = safe_int(parts[1])

    if target_id <= 0:
        await message.answer("Некорректный ID.")
        return

    if target_id == ADMIN_ID:
        await message.answer("Нельзя изменить собственный доступ.")
        return

    async with db.lock:

        async with aiosqlite.connect(DB_PATH) as connection:

            cursor = await connection.execute(
                """
                UPDATE users
                SET is_banned = ?
                WHERE user_id = ?
                """,
                (int(banned), target_id)
            )

            await connection.commit()

            if cursor.rowcount == 0:
                await message.answer("Участник не найден.")
                return

    db.invalidate(target_id)

    await db.log_admin(
        message.from_user.id,
        "BAN" if banned else "UNBAN",
        target_id
    )

    await message.answer(
        f"Доступ участника `{target_id}` "
        f"{'ограничен' if banned else 'восстановлен'}."
    )


@router.message(Command("ban"))
async def admin_ban(message: Message):
    await set_ban(message, True)


@router.message(Command("unban"))
async def admin_unban(message: Message):
    await set_ban(message, False)


# ============================================================
# ADMIN STATS
# ============================================================

@router.message(Command("stats"))
async def admin_stats(message: Message):

    if not await admin_required(message):
        return

    stats = await db.get_stats()

    await message.answer(
        "<b>СТАТИСТИКА КЛУБА</b>\n\n"
        f"Участников: `{stats['users']}`\n"
        f"Игровых баллов: `{format_tokens(stats['balance'])}`\n"
        f"Сыграно игр: `{stats['games']}`"
    )


# ============================================================
# ADMIN BACKUP
# ============================================================

@router.message(Command("backup"))
async def admin_backup(message: Message):

    if not await admin_required(message):
        return

    try:

        filename = await db.backup()

        document = BufferedInputFile.from_file(
            filename
        )

        await message.answer_document(
            document,
            caption="Резервная копия базы данных."
        )

        os.remove(filename)

    except Exception:

        logger.exception("Backup failed")

        await message.answer(
            "Не удалось создать резервную копию."
        )


# ============================================================
# ADMIN BROADCAST
# ============================================================

@router.message(Command("broadcast"))
async def admin_broadcast_start(
    message: Message,
    state: FSMContext
):

    if not await admin_required(message):
        return

    await state.set_state(
        ClubStates.waiting_for_broadcast
    )

    await message.answer(
        "Отправьте текст информационного сообщения."
    )


@router.message(
    ClubStates.waiting_for_broadcast,
    F.text
)
async def admin_broadcast_send(
    message: Message,
    state: FSMContext
):

    if not await admin_required(message):
        await state.clear()
        return

    text = message.text

    await state.clear()

    async with aiosqlite.connect(
        DB_PATH
    ) as connection:

        async with connection.execute(
            """
            SELECT user_id
            FROM users
            WHERE is_banned = 0
            """
        ) as cursor:

            users = await cursor.fetchall()

    sent = 0

    failed = 0

    for row in users:

        try:

            await bot.send_message(
                row[0],
                escape_html(text)
            )

            sent += 1

        except Exception:

            failed += 1

        await asyncio.sleep(0.05)

    await db.log_admin(
        message.from_user.id,
        "BROADCAST",
        details=f"sent={sent};failed={failed}"
    )

    await message.answer(
        "<b>РАССЫЛКА ЗАВЕРШЕНА</b>\n\n"
        f"Доставлено: `{sent}`\n"
        f"Ошибок: `{failed}`"
    )


# ============================================================
# MAINTENANCE
# ============================================================

@router.message(Command("maintenance"))
async def admin_maintenance(message: Message):

    if not await admin_required(message):
        return

    current = await db.get_setting(
        "maintenance",
        "0"
    )

    new_value = "0" if current == "1" else "1"

    await db.set_setting(
        "maintenance",
        new_value
    )

    await db.log_admin(
        message.from_user.id,
        "MAINTENANCE",
        details=new_value
    )

    await message.answer(
        "Режим обслуживания: "
        f"`{'ВКЛЮЧЁН' if new_value == '1' else 'ВЫКЛЮЧЕН'}`"
    )


# ============================================================
# MIDDLEWARE-LIKE MAINTENANCE CHECK
# ============================================================

@router.message()
async def maintenance_and_unknown(
    message: Message
):

    if not message.from_user:
        return

    if is_admin(message.from_user.id):
        return

    maintenance = await db.get_setting(
        "maintenance",
        "0"
    )

    if maintenance == "1":

        await message.answer(
            "Клуб временно находится на техническом обслуживании."
        )

        return

    await message.answer(
        "Команда не распознана.\n"
        "Пожалуйста, используйте меню клуба.",
        reply_markup=main_keyboard()
    )


# ============================================================
# SCHEDULER EVENTS
# ============================================================

async def cleanup_cache():

    current = time.monotonic()

    expired = []

    for user_id, timestamp in db.cache_time.items():

        if current - timestamp > CACHE_TTL * 10:

            expired.append(user_id)

    for user_id in expired:

        db.invalidate(user_id)


async def happy_hour_event():

    try:

        await db.set_setting(
            "happy_hour",
            "1"
        )

        logger.info("Happy hour enabled.")

    except Exception:

        logger.exception("Happy hour event failed")


async def happy_hour_reset():

    try:

        await db.set_setting(
            "happy_hour",
            "0"
        )

        logger.info("Happy hour disabled.")

    except Exception:

        logger.exception("Happy hour reset failed")


async def cleanup_old_logs():

    cutoff = now() - 90 * 86400

    try:

        async with db.lock:

            async with aiosqlite.connect(
                DB_PATH
            ) as connection:

                await connection.execute(
                    """
                    DELETE FROM game_log
                    WHERE created_at < ?
                    """,
                    (cutoff,)
                )

                await connection.execute(
                    """
                    PRAGMA wal_checkpoint(PASSIVE)
                    """
                )

                await connection.commit()

        logger.info("Old game logs cleaned.")

    except Exception:

        logger.exception("Database cleanup failed")


# ============================================================
# ERROR HANDLER
# ============================================================

@dp.errors()
async def global_error_handler(event):

    exception = event.exception

    logger.exception(
        "Unhandled Telegram exception",
        exc_info=exception
    )

    if ADMIN_ID and bot:

        try:

            await bot.send_message(
                ADMIN_ID,
                "<b>ОШИБКА БОТА</b>\n\n"
                f"<code>{escape_html(str(exception)[:3000])}</code>"
            )

        except Exception:

            logger.exception(
                "Could not notify administrator"
            )

    return True


# ============================================================
# BOT STARTUP
# ============================================================

async def startup():

    await db.connect()

    scheduler.add_job(
        cleanup_cache,
        "interval",
        minutes=1,
        id="cleanup_cache",
        replace_existing=True
    )

    scheduler.add_job(
        cleanup_old_logs,
        "cron",
        hour=4,
        minute=0,
        id="cleanup_logs",
        replace_existing=True
    )

    scheduler.add_job(
        happy_hour_event,
        "cron",
        hour=18,
        minute=0,
        id="happy_hour",
        replace_existing=True
    )

    scheduler.add_job(
        happy_hour_reset,
        "cron",
        hour=19,
        minute=0,
        id="happy_hour_reset",
        replace_existing=True
    )

    scheduler.start()

    logger.info("Scheduler started.")


async def shutdown():

    if scheduler.running:
        scheduler.shutdown(wait=False)

    await db.close()

    logger.info("Bot shutdown completed.")


# ============================================================
# MAIN
# ============================================================

async def main():

    global bot

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не установлен в ENV."
        )

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    await startup()

    try:

        logger.info(
            "%s starting...",
            CLUB_NAME
        )

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:

        await shutdown()

        await bot.session.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "TOKENS PRIVATE CLUB stopped by operator."
        )

    except Exception:

        logger.exception(
            "Fatal application error."
        )

        raise
