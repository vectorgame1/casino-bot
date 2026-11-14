import asyncio
import io
import logging
import os
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import suppress

import aiosqlite
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "tokens_club.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

ASSETS = Path("assets")
AVATARS = Path("avatars")
BACKUPS = Path("backups")

PROFILE_BG = ASSETS / "profile.jpg"
PROFILE_FONT = ASSETS / "Montserrat-Bold.ttf"

for directory in (ASSETS, AVATARS, BACKUPS):
    directory.mkdir(parents=True, exist_ok=True)

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN environment variable")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("tokens-club")


# ============================================================
# TRANSLATIONS
# ============================================================

TEXTS = {
    "ru": {
        "welcome": (
            "<b>TOKENS | PRIVATE CLUB</b>\n\n"
            "Добро пожаловать в пространство общения, "
            "событий и дружеских активностей."
        ),
        "captcha": "Подтвердите, что Вы человек.",
        "captcha_button": "Я не робот 🤖",
        "captcha_question": "Сколько будет <b>{a} + {b}</b>?",
        "captcha_wrong": "Ответ неверный. Попробуйте ещё раз.",
        "verified": "Проверка пройдена. Добро пожаловать!",
        "not_verified": "Сначала пройдите проверку через /start.",
        "banned": "Доступ к клубу ограничен.",
        "activities": (
            "<b>Активности клуба</b>\n\n"
            "Выберите бесплатную активность. "
            "Очки начисляются за участие."
        ),
        "bonus_ok": "Ваш ежедневный бонус: <b>+{amount} TOKENS</b>.",
        "bonus_wait": "Следующий бонус через {hours} ч. {minutes} мин.",
        "profile": "Ваш профиль клуба.",
        "history": "История активности",
        "achievements": "Достижения",
        "settings": "Настройки",
        "donate": (
            "<b>Поддержка клуба</b>\n\n"
            "В этой версии доступны бесплатные функции. "
            "Покупки и денежные переводы не предусмотрены."
        ),
        "partners": "Ваша ссылка-приглашение:\n{link}\n\nПриглашено: {count}",
        "top_empty": "Пока нет участников для рейтинга.",
        "tournament_empty": "За последние 7 дней результатов пока нет.",
        "support": "По вопросам работы клуба обратитесь к администратору.",
        "chats": "Ссылки на чаты клуба появятся здесь.",
        "language": "Выберите язык:",
        "language_saved": "Язык изменён.",
        "game_reward": "Результат: <b>{result}</b>\nНачислено: <b>+{reward} TOKENS</b>.",
        "game_no_reward": "Результат: <b>{result}</b>\nСпасибо за участие!",
        "admin_only": "Команда доступна только администратору.",
        "admin_help": (
            "<b>Команды администратора</b>\n\n"
            "<code>@выдать ID КОЛИЧЕСТВО</code> — начислить очки\n"
            "<code>@дроп КОЛИЧЕСТВО</code> — общий бонус\n"
            "<code>@бан ID</code> — ограничить доступ\n"
            "<code>@стата</code> — статистика\n"
            "<code>@бекап</code> — резервная копия\n"
            "<code>@рестарт</code> — инструкция по перезапуску\n"
            "<code>@помощь</code> — эта справка"
        ),
    },
    "en": {
        "welcome": (
            "<b>TOKENS | PRIVATE CLUB</b>\n\n"
            "Welcome to our community for conversations, "
            "events and friendly activities."
        ),
        "captcha": "Please confirm that you are human.",
        "captcha_button": "I'm not a robot 🤖",
        "captcha_question": "What is <b>{a} + {b}</b>?",
        "captcha_wrong": "Incorrect answer. Please try again.",
        "verified": "Verification complete. Welcome!",
        "not_verified": "Please complete verification using /start.",
        "banned": "Access to the club is restricted.",
        "activities": (
            "<b>Club activities</b>\n\n"
            "Choose a free activity. Points are awarded for participation."
        ),
        "bonus_ok": "Your daily bonus: <b>+{amount} TOKENS</b>.",
        "bonus_wait": "Next bonus in {hours}h {minutes}m.",
        "profile": "Your club profile.",
        "history": "Activity history",
        "achievements": "Achievements",
        "settings": "Settings",
        "donate": (
            "<b>Support the club</b>\n\n"
            "This version offers free features only. "
            "Purchases and money transfers are not supported."
        ),
        "partners": "Your invitation link:\n{link}\n\nInvited: {count}",
        "top_empty": "There are no members to rank yet.",
        "tournament_empty": "No results for the last seven days yet.",
        "support": "Please contact the club administrator for assistance.",
        "chats": "Club chat links will appear here.",
        "language": "Choose your language:",
        "language_saved": "Language updated.",
        "game_reward": "Result: <b>{result}</b>\nAwarded: <b>+{reward} TOKENS</b>.",
        "game_no_reward": "Result: <b>{result}</b>\nThanks for participating!",
        "admin_only": "This command is available to the administrator only.",
        "admin_help": (
            "<b>Administrator commands</b>\n\n"
            "<code>@выдать ID AMOUNT</code> — grant points\n"
            "<code>@дроп AMOUNT</code> — community reward\n"
            "<code>@бан ID</code> — restrict access\n"
            "<code>@стата</code> — statistics\n"
            "<code>@бекап</code> — database backup\n"
            "<code>@рестарт</code> — restart instructions\n"
            "<code>@помощь</code> — this help"
        ),
    },
}


# ============================================================
# DATABASE
# Each operation opens its own aiosqlite connection.
# No unsupported execute_fetchone helpers are used.
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()

    async def connect(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA busy_timeout=30000")
                await conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT DEFAULT '',
                        full_name TEXT DEFAULT '',
                        language TEXT DEFAULT 'ru',
                        balance INTEGER NOT NULL DEFAULT 0,
                        rank TEXT DEFAULT 'Участник',
                        verified INTEGER NOT NULL DEFAULT 0,
                        banned INTEGER NOT NULL DEFAULT 0,
                        referrer_id INTEGER,
                        created_at TEXT NOT NULL,
                        last_bonus TEXT,
                        avatar_path TEXT
                    );

                    CREATE TABLE IF NOT EXISTS activity_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        activity TEXT NOT NULL,
                        result INTEGER DEFAULT 0,
                        reward INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS admin_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        target_id INTEGER,
                        amount INTEGER,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_users_balance
                    ON users(balance DESC);

                    CREATE INDEX IF NOT EXISTS idx_activity_date
                    ON activity_log(created_at);

                    CREATE INDEX IF NOT EXISTS idx_activity_user
                    ON activity_log(user_id);
                    """
                )
                await conn.commit()

    async def close(self):
        pass

    async def register_user(self, tg_user, referrer_id=None):
        now = datetime.now(timezone.utc).isoformat()

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?",
                    (tg_user.id,),
                ) as cursor:
                    existing = await cursor.fetchone()

                if existing:
                    await conn.execute(
                        """
                        UPDATE users
                        SET username = ?, full_name = ?
                        WHERE user_id = ?
                        """,
                        (
                            tg_user.username or "",
                            tg_user.full_name or "",
                            tg_user.id,
                        ),
                    )
                else:
                    if referrer_id == tg_user.id:
                        referrer_id = None

                    await conn.execute(
                        """
                        INSERT INTO users (
                            user_id, username, full_name,
                            referrer_id, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            tg_user.id,
                            tg_user.username or "",
                            tg_user.full_name or "",
                            referrer_id,
                            now,
                        ),
                    )

                await conn.commit()

    async def get_user(self, user_id):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    return await cursor.fetchone()

    async def set_verified(self, user_id):
        await self._execute(
            "UPDATE users SET verified = 1 WHERE user_id = ?",
            (user_id,),
        )

    async def set_language(self, user_id, language):
        await self._execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (language, user_id),
        )

    async def set_banned(self, user_id, value):
        await self._execute(
            "UPDATE users SET banned = ? WHERE user_id = ?",
            (int(value), user_id),
        )

    async def _execute(self, query, params=()):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute(query, params)
                await conn.commit()

    async def change_balance(self, user_id, amount):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                try:
                    await conn.execute("BEGIN TRANSACTION")

                    async with conn.execute(
                        "SELECT balance FROM users WHERE user_id = ?",
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if row is None:
                        await conn.rollback()
                        return False

                    current_balance = int(row[0])

                    if current_balance + amount < 0:
                        await conn.rollback()
                        return False

                    await conn.execute(
                        """
                        UPDATE users
                        SET balance = balance + ?
                        WHERE user_id = ?
                        """,
                        (amount, user_id),
                    )

                    await conn.commit()
                    return True

                except Exception:
                    await conn.rollback()
                    raise

    async def add_activity(self, user_id, activity, result, reward):
        now = datetime.now(timezone.utc).isoformat()

        await self._execute(
            """
            INSERT INTO activity_log (
                user_id, activity, result, reward, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, activity, result, reward, now),
        )

    async def get_history(self, user_id, limit=10):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT activity, result, reward, created_at
                    FROM activity_log
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ) as cursor:
                    return await cursor.fetchall()

    async def get_top(self, limit=10):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT user_id, full_name, balance
                    FROM users
                    WHERE banned = 0
                    ORDER BY balance DESC
                    LIMIT ?
                    """,
                    (limit,),
                ) as cursor:
                    return await cursor.fetchall()

    async def get_weekly_top(self, limit=10):
        since = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).isoformat()

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT u.user_id, u.full_name,
                           COALESCE(SUM(a.reward), 0) AS points
                    FROM users u
                    LEFT JOIN activity_log a
                      ON a.user_id = u.user_id
                     AND a.created_at >= ?
                    WHERE u.banned = 0
                    GROUP BY u.user_id
                    ORDER BY points DESC
                    LIMIT ?
                    """,
                    (since, limit),
                ) as cursor:
                    return await cursor.fetchall()

    async def claim_bonus(self, user_id, amount):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                try:
                    await conn.execute("BEGIN TRANSACTION")

                    async with conn.execute(
                        "SELECT last_bonus FROM users WHERE user_id = ?",
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if row is None:
                        await conn.rollback()
                        return False, None

                    if row[0]:
                        previous = datetime.fromisoformat(row[0])
                        next_time = previous + timedelta(hours=24)

                        if now < next_time:
                            await conn.rollback()
                            return False, next_time

                    await conn.execute(
                        """
                        UPDATE users
                        SET balance = balance + ?, last_bonus = ?
                        WHERE user_id = ?
                        """,
                        (amount, now_text, user_id),
                    )

                    await conn.execute(
                        """
                        INSERT INTO activity_log (
                            user_id, activity, result, reward, created_at
                        )
                        VALUES (?, 'daily_bonus', 0, ?, ?)
                        """,
                        (user_id, amount, now_text),
                    )

                    await conn.commit()
                    return True, None

                except Exception:
                    await conn.rollback()
                    raise

    async def referrals_count(self, user_id):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute(
                    "SELECT COUNT(*) FROM users WHERE referrer_id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return int(row[0])

    async def all_user_ids(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute(
                    "SELECT user_id FROM users WHERE banned = 0"
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [int(row[0]) for row in rows]

    async def stats(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute(
                    "SELECT COUNT(*) FROM users"
                ) as cursor:
                    users = (await cursor.fetchone())[0]

                async with conn.execute(
                    "SELECT COUNT(*) FROM users WHERE verified = 1"
                ) as cursor:
                    verified = (await cursor.fetchone())[0]

                async with conn.execute(
                    "SELECT COUNT(*) FROM activity_log"
                ) as cursor:
                    activities = (await cursor.fetchone())[0]

                return users, verified, activities

    async def clean_old_rows(self, days=180):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        await self._execute(
            "DELETE FROM activity_log WHERE created_at < ?",
            (cutoff,),
        )

    async def write_admin_log(
        self, admin_id, action, target_id=None, amount=None
    ):
        now = datetime.now(timezone.utc).isoformat()

        await self._execute(
            """
            INSERT INTO admin_log (
                admin_id, action, target_id, amount, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (admin_id, action, target_id, amount, now),
        )


db = Database(DB_PATH)


# ============================================================
# BOT INITIALIZATION
# ============================================================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


class CaptchaState(StatesGroup):
    waiting_answer = State()


# ============================================================
# COMMON HELPERS
# ============================================================

def lang_of(user):
    if not user:
        return "ru"
    value = user["language"]
    return value if value in TEXTS else "ru"


def tr(user, key, **kwargs):
    return TEXTS[lang_of(user)][key].format(**kwargs)


def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def main_keyboard(lang="ru"):
    if lang == "en":
        labels = [
            ["🎮 Activities", "🎁 Bonus"],
            ["💎 Support", "👤 Profile"],
            ["🤝 Partners", "🏆 Tournament"],
            ["📊 Top", "💬 Chats"],
            ["🆘 Help"],
        ]
    else:
        labels = [
            ["🎮 Активности", "🎁 Бонус"],
            ["💎 Донат", "👤 Профиль"],
            ["🤝 Партнёры", "🏆 Турнир"],
            ["📊 Топ", "💬 Чаты"],
            ["🆘 Поддержка"],
        ]

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=item) for item in row]
            for row in labels
        ],
        resize_keyboard=True,
    )


def captcha_keyboard(lang="ru"):
    label = TEXTS[lang]["captcha_button"]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data="captcha:begin",
                )
            ]
        ]
    )


def profile_keyboard(lang="ru"):
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t["history"],
                    callback_data="profile:history",
                ),
                InlineKeyboardButton(
                    text=t["achievements"],
                    callback_data="profile:achievements",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t["settings"],
                    callback_data="profile:settings",
                )
            ],
        ]
    )


def language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Русский 🇷🇺",
                    callback_data="lang:ru",
                ),
                InlineKeyboardButton(
                    text="English 🇬🇧",
                    callback_data="lang:en",
                ),
            ]
        ]
    )


def activities_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Кости",
                    callback_data="activity:dice",
                ),
                InlineKeyboardButton(
                    text="🎯 Дартс",
                    callback_data="activity:darts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏀 Баскетбол",
                    callback_data="activity:basketball",
                ),
                InlineKeyboardButton(
                    text="⚽ Футбол",
                    callback_data="activity:football",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎳 Боулинг",
                    callback_data="activity:bowling",
                )
            ],
        ]
    )


async def auto_delete(message, delay=15):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def get_access(message):
    user = await db.get_user(message.from_user.id)

    if user is None or not user["verified"]:
        await message.answer(
            TEXTS["ru"]["not_verified"],
            reply_markup=captcha_keyboard(),
        )
        return None

    if user["banned"]:
        await message.answer(tr(user, "banned"))
        return None

    return user


# ============================================================
# PROFILE IMAGE
# ============================================================

def generate_profile_image(user):
    width, height = 1000, 520

    try:
        if PROFILE_BG.exists():
            image = Image.open(PROFILE_BG).convert("RGBA")
            image = image.resize(
                (width, height),
                Image.Resampling.LANCZOS,
            )
        else:
            image = Image.new(
                "RGBA", (width, height), (5, 5, 10, 255)
            )
    except Exception:
        image = Image.new(
            "RGBA", (width, height), (5, 5, 10, 255)
        )

    shade = Image.new(
        "RGBA", (width, height), (0, 0, 0, 155)
    )
    image = Image.alpha_composite(image, shade)

    gold = (212, 175, 55, 255)
    white = (255, 255, 255, 255)
    grey = (190, 190, 200, 255)

    try:
        font_name = ImageFont.truetype(str(PROFILE_FONT), 30)
        font_id = ImageFont.truetype(str(PROFILE_FONT), 20)
        font_rank = ImageFont.truetype(str(PROFILE_FONT), 24)
        font_balance = ImageFont.truetype(str(PROFILE_FONT), 28)
        font_small = ImageFont.truetype(str(PROFILE_FONT), 17)
    except Exception:
        font_name = ImageFont.load_default()
        font_id = ImageFont.load_default()
        font_rank = ImageFont.load_default()
        font_balance = ImageFont.load_default()
        font_small = ImageFont.load_default()

    panel = Image.new(
        "RGBA", (width, height), (0, 0, 0, 0)
    )
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle(
        (22, 22, width - 22, height - 22),
        radius=32,
        fill=(0, 0, 0, 115),
        outline=gold,
        width=3,
    )
    image = Image.alpha_composite(image, panel)

    avatar_size = 200
    avatar_x, avatar_y = 90, 155
    avatar_path = user.get("avatar_path")

    try:
        if avatar_path and os.path.isfile(avatar_path):
            avatar = Image.open(avatar_path).convert("RGBA")
            avatar = avatar.resize(
                (avatar_size, avatar_size),
                Image.Resampling.LANCZOS,
            )
        else:
            avatar = Image.new(
                "RGBA",
                (avatar_size, avatar_size),
                (65, 65, 75, 255),
            )
    except Exception:
        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (65, 65, 75, 255),
        )

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse(
        (0, 0, avatar_size - 1, avatar_size - 1),
        fill=255,
    )

    glow = Image.new(
        "RGBA", (width, height), (0, 0, 0, 0)
    )
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (
            avatar_x - 12,
            avatar_y - 12,
            avatar_x + avatar_size + 12,
            avatar_y + avatar_size + 12,
        ),
        outline=(255, 190, 30, 255),
        width=18,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(17))
    image = Image.alpha_composite(image, glow)

    avatar_layer = Image.new(
        "RGBA", (width, height), (0, 0, 0, 0)
    )
    avatar_layer.paste(
        avatar,
        (avatar_x, avatar_y),
        mask,
    )
    image = Image.alpha_composite(image, avatar_layer)

    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (
            avatar_x - 5,
            avatar_y - 5,
            avatar_x + avatar_size + 5,
            avatar_y + avatar_size + 5,
        ),
        outline=gold,
        width=7,
    )

    draw.text(
        (360, 165),
        str(user.get("full_name", "Участник"))[:28],
        font=font_name,
        fill=white,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )
    draw.text(
        (362, 220),
        f"ID: {user.get('user_id', '')}",
        font=font_id,
        fill=grey,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.text(
        (700, 165),
        "RANK",
        font=font_small,
        fill=gold,
    )
    draw.text(
        (700, 195),
        str(user.get("rank", "Участник"))[:18],
        font=font_rank,
        fill=gold,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )
    draw.text(
        (700, 275),
        "TOKENS",
        font=font_small,
        fill=gold,
    )
    draw.text(
        (700, 305),
        str(user.get("balance", 0)),
        font=font_balance,
        fill=white,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.line(
        (85, 420, 915, 420),
        fill=(212, 175, 55, 180),
        width=2,
    )
    draw.text(
        (90, 445),
        "TOKENS | PRIVATE CLUB",
        font=font_small,
        fill=gold,
    )

    output = io.BytesIO()
    image.convert("RGB").save(output, "PNG", optimize=True)
    output.seek(0)

    return BufferedInputFile(
        output.getvalue(),
        filename="profile.png",
    )


async def fetch_avatar(user_id):
    try:
        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]
        path = AVATARS / f"{user_id}.jpg"

        await bot.download(photo, destination=path)
        return str(path)
    except Exception:
        log.exception("Avatar download failed")
        return None


# ============================================================
# START AND CAPTCHA
# ============================================================

@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    referrer_id = None
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) > 1 and parts[1].startswith("ref_"):
        with suppress(ValueError):
            referrer_id = int(parts[1][4:])

    await db.register_user(message.from_user, referrer_id)
    user = await db.get_user(message.from_user.id)

    if user["banned"]:
        await message.answer(tr(user, "banned"))
        return

    if user["verified"]:
        await message.answer(
            tr(user, "welcome"),
            reply_markup=main_keyboard(lang_of(user)),
        )
        return

    await message.answer(
        tr(user, "captcha"),
        reply_markup=captcha_keyboard(lang_of(user)),
    )


@router.callback_query(F.data == "captcha:begin")
async def captcha_begin(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)

    if not user:
        await callback.answer()
        return

    a = random.randint(2, 9)
    b = random.randint(2, 9)

    await state.set_state(CaptchaState.waiting_answer)
    await state.update_data(answer=a + b)

    await callback.message.answer(
        tr(user, "captcha_question", a=a, b=b)
    )
    await callback.answer()


@router.message(CaptchaState.waiting_answer)
async def captcha_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    user = await db.get_user(message.from_user.id)

    try:
        answer = int(message.text.strip())
    except (ValueError, AttributeError):
        answer = None

    if answer != data.get("answer"):
        await message.answer(tr(user, "captcha_wrong"))
        return

    await db.set_verified(message.from_user.id)
    await state.clear()

    user = await db.get_user(message.from_user.id)

    await message.answer(
        tr(user, "verified"),
        reply_markup=main_keyboard(lang_of(user)),
    )


# ============================================================
# ACCESS MIDDLEWARE
# ============================================================

class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user:
            text = event.text or ""

            if text.startswith("/start"):
                return await handler(event, data)

            if isinstance(event, Message):
                current_state = data.get("state")
                if current_state:
                    state_name = await current_state.get_state()
                    if state_name == CaptchaState.waiting_answer.state:
                        return await handler(event, data)

            user = await db.get_user(event.from_user.id)

            if not user or not user["verified"]:
                await event.answer(
                    TEXTS["ru"]["not_verified"],
                    reply_markup=captcha_keyboard(),
                )
                return

            if user["banned"]:
                await event.answer(tr(user, "banned"))
                return

        return await handler(event, data)


router.message.middleware(AccessMiddleware())


# ============================================================
# MAIN MENU HANDLERS
# ============================================================

@router.message(F.text.in_({"🎮 Активности", "🎮 Activities"}))
async def menu_activities(message: Message):
    user = await get_access(message)
    if not user:
        return

    await message.answer(
        tr(user, "activities"),
        reply_markup=activities_keyboard(),
    )


@router.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def menu_bonus(message: Message):
    user = await get_access(message)
    if not user:
        return

    success, next_time = await db.claim_bonus(
        message.from_user.id,
        5000,
    )

    if success:
        await message.answer(tr(user, "bonus_ok", amount=5000))
        return

    remaining = next_time - datetime.now(timezone.utc)
    seconds = max(0, int(remaining.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60

    await message.answer(
        tr(user, "bonus_wait", hours=hours, minutes=minutes)
    )


@router.message(F.text.in_({"💎 Донат", "💎 Support"}))
async def menu_donate(message: Message):
    user = await get_access(message)
    if user:
        await message.answer(tr(user, "donate"))


@router.message(F.text.in_({"🆘 Поддержка", "🆘 Help"}))
async def menu_support(message: Message):
    user = await get_access(message)
    if user:
        await message.answer(tr(user, "support"))


@router.message(F.text.in_({"💬 Чаты", "💬 Chats"}))
async def menu_chats(message: Message):
    user = await get_access(message)
    if user:
        await message.answer(tr(user, "chats"))


@router.message(F.text.in_({"🤝 Партнёры", "🤝 Partners"}))
async def menu_partners(message: Message):
    user = await get_access(message)
    if not user:
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    count = await db.referrals_count(message.from_user.id)

    await message.answer(
        tr(user, "partners", link=link, count=count)
    )


# ============================================================
# PROFILE HANDLERS
# ============================================================

@router.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def menu_profile(message: Message):
    user = await get_access(message)
    if not user:
        return

    avatar_path = await fetch_avatar(message.from_user.id)

    profile = {
        "full_name": user["full_name"],
        "user_id": user["user_id"],
        "rank": user["rank"],
        "balance": user["balance"],
        "avatar_path": avatar_path,
    }

    photo = await asyncio.to_thread(
        generate_profile_image,
        profile,
    )

    await message.answer_photo(
        photo=photo,
        caption=tr(user, "profile"),
        reply_markup=profile_keyboard(lang_of(user)),
    )


@router.callback_query(F.data == "profile:history")
async def profile_history(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user or not user["verified"]:
        await callback.answer()
        return

    rows = await db.get_history(callback.from_user.id)

    if not rows:
        await callback.message.answer("История пока пуста.")
        await callback.answer()
        return

    lines = ["<b>История активности</b>", ""]

    for row in rows:
        date = row["created_at"][:16].replace("T", " ")
        lines.append(
            f"• {row['activity']} | {row['result']} | "
            f"+{row['reward']} TOKENS | {date}"
        )

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "profile:achievements")
async def profile_achievements(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user or not user["verified"]:
        await callback.answer()
        return

    rows = await db.get_history(callback.from_user.id, 1000)
    referrals = await db.referrals_count(callback.from_user.id)

    await callback.message.answer(
        "<b>Достижения</b>\n\n"
        f"Активностей: <b>{len(rows)}</b>\n"
        f"Приглашено участников: <b>{referrals}</b>"
    )
    await callback.answer()


@router.callback_query(F.data == "profile:settings")
async def profile_settings(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user:
        await callback.answer()
        return

    await callback.message.answer(
        tr(user, "language"),
        reply_markup=language_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lang:"))
async def language_change(callback: CallbackQuery):
    language = callback.data.split(":", 1)[1]

    if language not in TEXTS:
        await callback.answer()
        return

    await db.set_language(callback.from_user.id, language)

    await callback.message.answer(
        TEXTS[language]["language_saved"],
        reply_markup=main_keyboard(language),
    )
    await callback.answer()


# ============================================================
# FREE ACTIVITY ENGINE
# ============================================================

ACTIVITIES = {
    "dice": ("🎲", "dice"),
    "darts": ("🎯", "darts"),
    "basketball": ("🏀", "basketball"),
    "football": ("⚽", "football"),
    "bowling": ("🎳", "bowling"),
}

REWARD_FOR_PARTICIPATION = 20


async def run_activity(message: Message, key: str):
    user = await get_access(message)
    if not user:
        return

    activity = ACTIVITIES.get(key)

    if not activity:
        return

    emoji, label = activity

    result_message = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3)

    result = result_message.dice.value

    # Бесплатное начисление за участие.
    # Баланс участника не уменьшается.
    reward = REWARD_FOR_PARTICIPATION if result >= 4 else 0

    if reward:
        await db.change_balance(
            message.from_user.id,
            reward,
        )

    await db.add_activity(
        message.from_user.id,
        label,
        result,
        reward,
    )

    if reward:
        response = tr(
            user,
            "game_reward",
            result=result,
            reward=reward,
        )
    else:
        response = tr(
            user,
            "game_no_reward",
            result=result,
        )

    result_notice = await message.answer(response)

    asyncio.create_task(auto_delete(result_message, 15))
    asyncio.create_task(auto_delete(result_notice, 15))
    asyncio.create_task(auto_delete(message, 15))


@router.callback_query(F.data.startswith("activity:"))
async def activity_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]

    if key not in ACTIVITIES:
        await callback.answer()
        return

    await callback.answer("Активность запущена.")
    await run_activity(callback.message, key)


@router.message(F.text.lower().in_({"кости", "🎲 кости"}))
async def dice_text(message: Message):
    await run_activity(message, "dice")


@router.message(F.text.lower().in_({"дартс", "🎯 дартс"}))
async def darts_text(message: Message):
    await run_activity(message, "darts")


@router.message(F.text.lower().in_({"баскет", "баскетбол", "🏀"}))
async def basketball_text(message: Message):
    await run_activity(message, "basketball")


@router.message(F.text.lower().in_({"футбол", "⚽"}))
async def football_text(message: Message):
    await run_activity(message, "football")


@router.message(F.text.lower().in_({"боулинг", "🎳"}))
async def bowling_text(message: Message):
    await run_activity(message, "bowling")


# ============================================================
# TOP AND TOURNAMENT
# ============================================================

@router.message(F.text.in_({"📊 Топ", "📊 Top"}))
async def menu_top(message: Message):
    user = await get_access(message)
    if not user:
        return

    rows = await db.get_top(10)

    if not rows:
        await message.answer(tr(user, "top_empty"))
        return

    lines = ["<b>ТОП УЧАСТНИКОВ</b>", ""]

    for index, row in enumerate(rows, 1):
        name = row["full_name"] or str(row["user_id"])
        lines.append(
            f"<b>{index}.</b> {name[:25]} — "
            f"<b>{row['balance']}</b> TOKENS"
        )

    await message.answer("\n".join(lines))


@router.message(F.text.in_({"🏆 Турнир", "🏆 Tournament"}))
async def menu_tournament(message: Message):
    user = await get_access(message)
    if not user:
        return

    rows = await db.get_weekly_top(10)

    if not rows or all(int(row["points"]) == 0 for row in rows):
        await message.answer(tr(user, "tournament_empty"))
        return

    lines = ["<b>АКТИВНОСТЬ ЗА 7 ДНЕЙ</b>", ""]

    for index, row in enumerate(rows, 1):
        name = row["full_name"] or str(row["user_id"])
        lines.append(
            f"<b>{index}.</b> {name[:25]} — "
            f"<b>{row['points']}</b>"
        )

    await message.answer("\n".join(lines))


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def admin_check(message):
    if not is_admin(message.from_user.id):
        await message.answer(TEXTS["ru"]["admin_only"])
        return False
    return True


@router.message(F.text.startswith("@помощь"))
async def admin_help(message: Message):
    if not await admin_check(message):
        return
    await message.answer(TEXTS["ru"]["admin_help"])


@router.message(F.text.startswith("@выдать"))
async def admin_grant(message: Message):
    if not await admin_check(message):
        return

    parts = message.text.split()

    if len(parts) != 3:
        await message.answer("Формат: @выдать ID КОЛИЧЕСТВО")
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("ID и количество должны быть числами.")
        return

    if amount <= 0 or amount > 1_000_000:
        await message.answer("Количество должно быть от 1 до 1000000.")
        return

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Участник не найден.")
        return

    ok = await db.change_balance(target_id, amount)

    if not ok:
        await message.answer("Не удалось выполнить начисление.")
        return

    await db.write_admin_log(
        message.from_user.id,
        "grant",
        target_id,
        amount,
    )

    await message.answer(
        f"Начислено <b>{amount}</b> TOKENS участнику "
        f"<code>{target_id}</code>."
    )


@router.message(F.text.startswith("@дроп"))
async def admin_drop(message: Message):
    if not await admin_check(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Формат: @дроп КОЛИЧЕСТВО")
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("Количество должно быть числом.")
        return

    if not 1 <= amount <= 100_000:
        await message.answer("Укажите количество от 1 до 100000.")
        return

    user_ids = await db.all_user_ids()
    completed = 0

    for user_id in user_ids:
        if await db.change_balance(user_id, amount):
            completed += 1
        await asyncio.sleep(0.02)

    await db.write_admin_log(
        message.from_user.id,
        "community_drop",
        None,
        amount,
    )

    await message.answer(
        f"Бонус начислен участникам: <b>{completed}</b>."
    )


@router.message(F.text.startswith("@бан"))
async def admin_ban(message: Message):
    if not await admin_check(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Формат: @бан ID")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Участник не найден.")
        return

    await db.set_banned(target_id, True)
    await db.write_admin_log(
        message.from_user.id,
        "ban",
        target_id,
    )

    await message.answer(
        f"Доступ пользователя <code>{target_id}</code> ограничен."
    )


@router.message(F.text.startswith("@стата"))
async def admin_stats(message: Message):
    if not await admin_check(message):
        return

    users, verified, activities = await db.stats()

    await message.answer(
        "<b>СТАТИСТИКА</b>\n\n"
        f"Участников: <b>{users}</b>\n"
        f"Прошли проверку: <b>{verified}</b>\n"
        f"Активностей: <b>{activities}</b>"
    )


@router.message(F.text.startswith("@бекап"))
async def admin_backup(message: Message):
    if not await admin_check(message):
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUPS / f"club_{stamp}.sqlite3"

    try:
        async with db.lock:
            async with aiosqlite.connect(DB_PATH) as source:
                async with aiosqlite.connect(str(target)) as destination:
                    await source.backup(destination)

        await db.write_admin_log(
            message.from_user.id,
            "backup",
        )

        await message.answer_document(
            BufferedInputFile(
                target.read_bytes(),
                filename=target.name,
            ),
            caption="Резервная копия базы данных.",
        )

    except Exception:
        log.exception("Backup failed")
        await message.answer("Не удалось создать резервную копию.")


@router.message(F.text.startswith("@рестарт"))
async def admin_restart(message: Message):
    if not await admin_check(message):
        return

    await message.answer(
        "Для безопасного перезапуска используйте панель управления "
        "хостингом или выполните штатный redeploy."
    )


# ============================================================
# SCHEDULED TASKS
# ============================================================

scheduler = AsyncIOScheduler(timezone="UTC")


async def happy_hour_notice():
    """
    Информационное событие клуба.
    Оно не меняет стоимость участия: все активности бесплатны.
    """
    users = await db.all_user_ids()

    for user_id in users:
        with suppress(Exception):
            await bot.send_message(
                user_id,
                "✨ В клубе начался счастливый час! "
                "Загляните в раздел активностей.",
            )
        await asyncio.sleep(0.03)


async def scheduled_free_drop():
    users = await db.all_user_ids()

    if not users:
        return

    selected = random.sample(
        users,
        min(5, len(users)),
    )

    for user_id in selected:
        try:
            await db.change_balance(user_id, 100)
            await db.add_activity(
                user_id,
                "scheduled_community_bonus",
                1,
                100,
            )
            await bot.send_message(
                user_id,
                "🎁 Вам начислено <b>+100 TOKENS</b> "
                "за участие в жизни клуба.",
            )
        except Exception:
            log.exception("Scheduled reward failed for %s", user_id)


async def scheduled_cleanup():
    await db.clean_old_rows(days=180)
    log.info("Old activity rows cleaned")


def setup_scheduler():
    scheduler.add_job(
        happy_hour_notice,
        "cron",
        hour=18,
        minute=0,
        id="happy_hour",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_free_drop,
        "interval",
        hours=6,
        id="free_drop",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_cleanup,
        "cron",
        hour=4,
        minute=15,
        id="db_cleanup",
        replace_existing=True,
    )

    scheduler.start()


# ============================================================
# HEALTH ENDPOINT
# ============================================================

async def health(request):
    return web.json_response(
        {
            "status": "ok",
            "service": "TOKENS | PRIVATE CLUB",
            "time": datetime.now(timezone.utc).isoformat(),
        }
    )


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )
    await site.start()

    log.info("Health endpoint listening on %s", PORT)
    return runner


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@dp.errors()
async def global_error_handler(event):
    exception = event.exception

    log.exception(
        "Unhandled update error",
        exc_info=exception,
    )

    if ADMIN_ID:
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                "<b>Ошибка бота</b>\n\n"
                f"<code>{type(exception).__name__}</code>\n"
                f"{str(exception)[:2500]}",
            )

    return True


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

async def startup():
    await db.connect()
    setup_scheduler()
    log.info("Database and scheduler initialized")


async def shutdown(health_runner=None):
    if scheduler.running:
        scheduler.shutdown(wait=False)

    if health_runner:
        with suppress(Exception):
            await health_runner.cleanup()

    await db.close()

    with suppress(Exception):
        await bot.session.close()

    log.info("Bot shutdown complete")


async def main():
    await startup()
    health_runner = await start_health_server()

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await shutdown(health_runner)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user")