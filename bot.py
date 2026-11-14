import asyncio
import logging
import os
import random
import io
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import suppress

import aiosqlite
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
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
    TelegramObject,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.middlewares.base import BaseMiddleware


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "tokens_club.sqlite3")
PORT = int(os.getenv("PORT", "10000"))

ASSETS_DIR = Path("assets")
PROFILE_BACKGROUND = ASSETS_DIR / "profile.jpg"
PROFILE_FONT = ASSETS_DIR / "Montserrat-Bold.ttf"
AVATARS_DIR = Path("avatars")
BACKUP_DIR = Path("backups")

AVATARS_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("tokens_club")

if not BOT_TOKEN:
    raise RuntimeError("Укажите BOT_TOKEN в переменных окружения.")


# ============================================================
# TEXTS
# ============================================================

TEXTS = {
    "ru": {
        "welcome": (
            "Добро пожаловать в <b>TOKENS | PRIVATE CLUB</b>.\n\n"
            "Пространство общения, событий и дружеских активностей."
        ),
        "captcha": "Для продолжения подтвердите, что Вы человек.",
        "captcha_button": "Я не робот 🤖",
        "captcha_question": "Сколько будет <b>{a} + {b}</b>?",
        "captcha_wrong": "Ответ неверный. Попробуйте ещё раз.",
        "verified": "Проверка пройдена. Добро пожаловать в клуб.",
        "menu_activities": "🎮 Активности",
        "menu_bonus": "🎁 Бонус",
        "menu_donate": "💎 Донат",
        "menu_profile": "👤 Профиль",
        "menu_partners": "🤝 Партнёры",
        "menu_tournament": "🏆 Турнир",
        "menu_top": "📊 Топ",
        "menu_chats": "💬 Чаты",
        "menu_support": "🆘 Поддержка",
        "activities": (
            "<b>Активности клуба</b>\n\n"
            "Выберите развлечение. Участие бесплатное, "
            "очки начисляются за активность."
        ),
        "bonus_success": "Ваш ежедневный бонус: <b>+{amount} TOKENS</b>.",
        "bonus_wait": "Следующий бонус будет доступен через {hours} ч. {minutes} мин.",
        "profile": "Ваш профиль клуба:",
        "profile_history": "История активности",
        "profile_achievements": "Достижения",
        "profile_settings": "Настройки",
        "donate": (
            "<b>Поддержка клуба</b>\n\n"
            "В этой версии доступны только бесплатные функции. "
            "Покупки и денежные переводы не предусмотрены."
        ),
        "partners": "Ваша пригласительная ссылка:\n{link}",
        "tournament_empty": "За последние 7 дней пока нет результатов.",
        "top_empty": "Список участников пока пуст.",
        "chats": "Ссылки на чаты клуба появятся здесь.",
        "support": "По вопросам работы клуба обратитесь к администратору.",
        "game_result": "Результат: <b>{result}</b>\n{message}",
        "game_reward": "Вам начислено <b>+{amount} TOKENS</b>.",
        "game_no_reward": "Спасибо за участие!",
        "game_unknown": "Неизвестная активность. Выберите игру в меню.",
        "not_verified": "Сначала пройдите проверку через /start.",
        "banned": "Доступ к клубу временно ограничен.",
        "admin_only": "Эта команда доступна только администратору.",
        "admin_help": (
            "<b>Команды администратора</b>\n\n"
            "<code>@выдать ID КОЛИЧЕСТВО</code> — начислить очки\n"
            "<code>@дроп КОЛИЧЕСТВО</code> — общий бонус\n"
            "<code>@бан ID</code> — ограничить доступ\n"
            "<code>@стата</code> — статистика\n"
            "<code>@бекап</code> — резервная копия\n"
            "<code>@помощь</code> — эта справка"
        ),
        "language": "Выберите язык:",
        "language_saved": "Язык изменён.",
        "history_empty": "История пока пуста.",
        "achievements_empty": "Достижения появятся по мере активности.",
        "settings": "Настройки профиля",
        "error": "Произошла ошибка. Попробуйте позже.",
    },
    "en": {
        "welcome": (
            "Welcome to <b>TOKENS | PRIVATE CLUB</b>.\n\n"
            "A community for conversations, events and friendly activities."
        ),
        "captcha": "Please confirm that you are human to continue.",
        "captcha_button": "I'm not a robot 🤖",
        "captcha_question": "What is <b>{a} + {b}</b>?",
        "captcha_wrong": "That answer is incorrect. Please try again.",
        "verified": "Verification complete. Welcome to the club.",
        "menu_activities": "🎮 Activities",
        "menu_bonus": "🎁 Bonus",
        "menu_donate": "💎 Support",
        "menu_profile": "👤 Profile",
        "menu_partners": "🤝 Partners",
        "menu_tournament": "🏆 Tournament",
        "menu_top": "📊 Top",
        "menu_chats": "💬 Chats",
        "menu_support": "🆘 Help",
        "activities": (
            "<b>Club activities</b>\n\n"
            "Choose an activity. Participation is free; "
            "points are awarded for participation."
        ),
        "bonus_success": "Your daily bonus: <b>+{amount} TOKENS</b>.",
        "bonus_wait": "Your next bonus is available in {hours}h {minutes}m.",
        "profile": "Your club profile:",
        "profile_history": "Activity history",
        "profile_achievements": "Achievements",
        "profile_settings": "Settings",
        "donate": (
            "<b>Support the club</b>\n\n"
            "Only free features are available in this version. "
            "Purchases and money transfers are not supported."
        ),
        "partners": "Your invitation link:\n{link}",
        "tournament_empty": "There are no results for the last 7 days yet.",
        "top_empty": "The member list is currently empty.",
        "chats": "Club chat links will appear here.",
        "support": "For help, please contact the club administrator.",
        "game_result": "Result: <b>{result}</b>\n{message}",
        "game_reward": "You received <b>+{amount} TOKENS</b>.",
        "game_no_reward": "Thank you for participating!",
        "game_unknown": "Unknown activity. Choose a game from the menu.",
        "not_verified": "Please complete verification using /start.",
        "banned": "Access to the club is currently restricted.",
        "admin_only": "This command is available to the administrator only.",
        "admin_help": (
            "<b>Administrator commands</b>\n\n"
            "<code>@выдать ID AMOUNT</code> — grant points\n"
            "<code>@дроп AMOUNT</code> — community reward\n"
            "<code>@бан ID</code> — restrict access\n"
            "<code>@стата</code> — statistics\n"
            "<code>@бекап</code> — create backup\n"
            "<code>@помощь</code> — this help"
        ),
        "language": "Choose your language:",
        "language_saved": "Language updated.",
        "history_empty": "No activity history yet.",
        "achievements_empty": "Achievements will appear as you participate.",
        "settings": "Profile settings",
        "error": "Something went wrong. Please try again later.",
    },
}


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    t = TEXTS[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t["menu_activities"]),
                KeyboardButton(text=t["menu_bonus"]),
            ],
            [
                KeyboardButton(text=t["menu_donate"]),
                KeyboardButton(text=t["menu_profile"]),
            ],
            [
                KeyboardButton(text=t["menu_partners"]),
                KeyboardButton(text=t["menu_tournament"]),
            ],
            [
                KeyboardButton(text=t["menu_top"]),
                KeyboardButton(text=t["menu_chats"]),
            ],
            [KeyboardButton(text=t["menu_support"])],
        ],
        resize_keyboard=True,
        input_field_placeholder="TOKENS | PRIVATE CLUB",
    )


def captcha_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=TEXTS[lang]["captcha_button"],
                    callback_data="captcha:start",
                )
            ]
        ]
    )


def profile_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t["profile_history"],
                    callback_data="profile:history",
                ),
                InlineKeyboardButton(
                    text=t["profile_achievements"],
                    callback_data="profile:achievements",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t["profile_settings"],
                    callback_data="profile:settings",
                )
            ],
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Русский 🇷🇺",
                    callback_data="language:ru",
                ),
                InlineKeyboardButton(
                    text="English 🇬🇧",
                    callback_data="language:en",
                ),
            ]
        ]
    )


def activities_keyboard() -> InlineKeyboardMarkup:
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


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.connection = None
        self.lock = asyncio.Lock()

    async def connect(self):
        self.connection = await aiosqlite.connect(
            self.path,
            timeout=30,
        )
        self.connection.row_factory = aiosqlite.Row

        async with self.lock:
            await self.connection.execute("PRAGMA journal_mode=WAL")
            await self.connection.execute("PRAGMA synchronous=NORMAL")
            await self.connection.execute("PRAGMA foreign_keys=ON")
            await self.connection.execute("PRAGMA busy_timeout=30000")

            await self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'ru',
                    balance INTEGER NOT NULL DEFAULT 0,
                    rank TEXT NOT NULL DEFAULT 'Участник',
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    referrer_id INTEGER,
                    created_at TEXT NOT NULL,
                    last_bonus TEXT,
                    avatar_path TEXT
                );

                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    activity TEXT NOT NULL,
                    result INTEGER NOT NULL DEFAULT 0,
                    reward INTEGER NOT NULL DEFAULT 0,
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

                CREATE INDEX IF NOT EXISTS idx_activity_user
                ON activity_log(user_id);

                CREATE INDEX IF NOT EXISTS idx_activity_created
                ON activity_log(created_at);

                CREATE INDEX IF NOT EXISTS idx_users_balance
                ON users(balance DESC);
                """
            )
            await self.connection.commit()

    async def close(self):
        if self.connection is not None:
            async with self.lock:
                await self.connection.close()
                self.connection = None

    async def execute(self, query, parameters=()):
        async with self.lock:
            cursor = await self.connection.execute(query, parameters)
            await self.connection.commit()
            return cursor

    async def fetchone(self, query, parameters=()):
        async with self.lock:
            cursor = await self.connection.execute(query, parameters)
            return await cursor.fetchone()

    async def fetchall(self, query, parameters=()):
        async with self.lock:
            cursor = await self.connection.execute(query, parameters)
            return await cursor.fetchall()

    async def register_user(
        self,
        user_id: int,
        username: str,
        full_name: str,
        referrer_id=None,
    ):
        now = datetime.now(timezone.utc).isoformat()

        async with self.lock:
            existing = await self.connection.execute_fetchone(
                "SELECT user_id FROM users WHERE user_id = ?",
                (user_id,),
            )

            if existing:
                await self.connection.execute(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                    """,
                    (username, full_name, user_id),
                )
            else:
                if referrer_id == user_id:
                    referrer_id = None

                await self.connection.execute(
                    """
                    INSERT INTO users (
                        user_id, username, full_name, referrer_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        full_name,
                        referrer_id,
                        now,
                    ),
                )

            await self.connection.commit()

    async def get_user(self, user_id: int):
        return await self.fetchone(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        )

    async def set_verified(self, user_id: int):
        await self.execute(
            "UPDATE users SET is_verified = 1 WHERE user_id = ?",
            (user_id,),
        )

    async def set_language(self, user_id: int, language: str):
        await self.execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (language, user_id),
        )

    async def set_banned(self, user_id: int, value: bool):
        await self.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (int(value), user_id),
        )

    async def change_balance(self, user_id: int, amount: int):
        """
        Изменение виртуальных очков.

        В игровых обработчиках предусмотрены только бесплатные активности
        и положительные начисления. Метод проверяет баланс и сохраняет
        транзакцию атомарно для административных корректировок.
        """
        async with self.lock:
            try:
                await self.connection.execute("BEGIN TRANSACTION")

                cursor = await self.connection.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (user_id,),
                )
                row = await cursor.fetchone()

                if row is None:
                    await self.connection.rollback()
                    return False

                balance = int(row["balance"])

                if balance + amount < 0:
                    await self.connection.rollback()
                    return False

                await self.connection.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (amount, user_id),
                )

                await self.connection.commit()
                return True

            except Exception:
                await self.connection.rollback()
                raise

    async def add_activity(
        self,
        user_id: int,
        activity: str,
        result: int,
        reward: int,
    ):
        await self.execute(
            """
            INSERT INTO activity_log (
                user_id, activity, result, reward, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                activity,
                result,
                reward,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    async def get_history(self, user_id: int, limit: int = 10):
        return await self.fetchall(
            """
            SELECT activity, result, reward, created_at
            FROM activity_log
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

    async def get_top(self, limit: int = 10):
        return await self.fetchall(
            """
            SELECT user_id, full_name, balance
            FROM users
            WHERE is_banned = 0
            ORDER BY balance DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def get_weekly_top(self, limit: int = 10):
        since = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).isoformat()

        return await self.fetchall(
            """
            SELECT
                u.user_id,
                u.full_name,
                COALESCE(SUM(a.reward), 0) AS points
            FROM users u
            LEFT JOIN activity_log a
                ON a.user_id = u.user_id
                AND a.created_at >= ?
            WHERE u.is_banned = 0
            GROUP BY u.user_id
            ORDER BY points DESC
            LIMIT ?
            """,
            (since, limit),
        )

    async def claim_daily_bonus(self, user_id: int, amount: int):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()

        async with self.lock:
            try:
                await self.connection.execute("BEGIN TRANSACTION")

                cursor = await self.connection.execute(
                    "SELECT last_bonus FROM users WHERE user_id = ?",
                    (user_id,),
                )
                row = await cursor.fetchone()

                if row is None:
                    await self.connection.rollback()
                    return False, None

                last_bonus = row["last_bonus"]

                if last_bonus:
                    previous = datetime.fromisoformat(last_bonus)
                    if now - previous < timedelta(hours=24):
                        await self.connection.rollback()
                        return False, previous + timedelta(hours=24)

                await self.connection.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?, last_bonus = ?
                    WHERE user_id = ?
                    """,
                    (amount, now_text, user_id),
                )

                await self.connection.execute(
                    """
                    INSERT INTO activity_log (
                        user_id, activity, result, reward, created_at
                    )
                    VALUES (?, 'daily_bonus', 0, ?, ?)
                    """,
                    (user_id, amount, now_text),
                )

                await self.connection.commit()
                return True, None

            except Exception:
                await self.connection.rollback()
                raise

    async def count_users(self):
        row = await self.fetchone("SELECT COUNT(*) AS total FROM users")
        return int(row["total"]) if row else 0

    async def count_verified(self):
        row = await self.fetchone(
            "SELECT COUNT(*) AS total FROM users WHERE is_verified = 1"
        )
        return int(row["total"]) if row else 0

    async def count_activities(self):
        row = await self.fetchone(
            "SELECT COUNT(*) AS total FROM activity_log"
        )
        return int(row["total"]) if row else 0

    async def all_user_ids(self):
        rows = await self.fetchall(
            "SELECT user_id FROM users WHERE is_banned = 0"
        )
        return [int(row["user_id"]) for row in rows]

    async def clean_old_activity(self, days: int = 180):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        await self.execute(
            "DELETE FROM activity_log WHERE created_at < ?",
            (cutoff,),
        )

    async def admin_log(
        self,
        admin_id: int,
        action: str,
        target_id=None,
        amount=None,
    ):
        await self.execute(
            """
            INSERT INTO admin_log (
                admin_id, action, target_id, amount, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                admin_id,
                action,
                target_id,
                amount,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    async def get_referrals_count(self, user_id: int):
        row = await self.fetchone(
            "SELECT COUNT(*) AS total FROM users WHERE referrer_id = ?",
            (user_id,),
        )
        return int(row["total"]) if row else 0


db = Database(DB_PATH)


# ============================================================
# FSM
# ============================================================

class CaptchaState(StatesGroup):
    waiting_answer = State()


# ============================================================
# HELPERS
# ============================================================

def user_language(user) -> str:
    if not user:
        return "ru"

    lang = user["language"]
    return lang if lang in TEXTS else "ru"


def tr(user, key: str, **kwargs) -> str:
    lang = user_language(user)
    return TEXTS[lang][key].format(**kwargs)


async def auto_delete(message: Message, delay: int = 15):
    await asyncio.sleep(delay)

    with suppress(Exception):
        await message.delete()


async def send_temporary(
    message: Message,
    text: str,
    delay: int = 15,
    **kwargs,
):
    sent = await message.answer(text, **kwargs)
    asyncio.create_task(auto_delete(sent, delay))
    return sent


async def get_or_register_user(
    telegram_user,
    referrer_id=None,
):
    full_name = telegram_user.full_name or "Участник"
    username = telegram_user.username or ""

    await db.register_user(
        user_id=telegram_user.id,
        username=username,
        full_name=full_name,
        referrer_id=referrer_id,
    )

    return await db.get_user(telegram_user.id)


async def ensure_access(message: Message):
    user = await db.get_user(message.from_user.id)

    if user is None or not user["is_verified"]:
        await message.answer(
            TEXTS["ru"]["not_verified"],
            reply_markup=captcha_keyboard(),
        )
        return None

    if user["is_banned"]:
        await message.answer(tr(user, "banned"))
        return None

    return user


# ============================================================
# PROFILE IMAGE
# ============================================================

def generate_profile_image(user):
    """
    Синхронная генерация карточки профиля.

    user должен содержать:
      full_name, user_id, balance, rank, avatar_path.
    """
    width, height = 1000, 520

    if PROFILE_BACKGROUND.exists():
        try:
            image = Image.open(PROFILE_BACKGROUND).convert("RGBA")
            image = image.resize(
                (width, height),
                Image.Resampling.LANCZOS,
            )
        except Exception:
            image = Image.new(
                "RGBA",
                (width, height),
                (8, 8, 12, 255),
            )
    else:
        image = Image.new(
            "RGBA",
            (width, height),
            (8, 8, 12, 255),
        )

    # Затемняющий слой.
    darkness = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 155),
    )
    image = Image.alpha_composite(image, darkness)

    gold = (212, 175, 55, 255)
    white = (255, 255, 255, 255)
    grey = (180, 180, 190, 255)
    dark = (0, 0, 0, 180)

    # Шрифты.
    try:
        font_path = str(PROFILE_FONT)
        font_name = ImageFont.truetype(font_path, 30)
        font_id = ImageFont.truetype(font_path, 20)
        font_rank = ImageFont.truetype(font_path, 24)
        font_balance = ImageFont.truetype(font_path, 28)
        font_caption = ImageFont.truetype(font_path, 17)
    except OSError:
        font_name = ImageFont.load_default()
        font_id = ImageFont.load_default()
        font_rank = ImageFont.load_default()
        font_balance = ImageFont.load_default()
        font_caption = ImageFont.load_default()

    # Подложка карточки.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    overlay_draw.rounded_rectangle(
        (24, 24, width - 24, height - 24),
        radius=36,
        fill=dark,
        outline=gold,
        width=3,
    )

    image = Image.alpha_composite(image, overlay)

    # Аватар.
    avatar_size = 200
    avatar_x = 100
    avatar_y = 160

    avatar_path = user.get("avatar_path")

    if avatar_path and os.path.exists(avatar_path):
        try:
            avatar = Image.open(avatar_path).convert("RGBA")
            avatar = avatar.resize(
                (avatar_size, avatar_size),
                Image.Resampling.LANCZOS,
            )
        except Exception:
            avatar = Image.new(
                "RGBA",
                (avatar_size, avatar_size),
                (55, 55, 65, 255),
            )
    else:
        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (55, 55, 65, 255),
        )

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse(
        (0, 0, avatar_size - 1, avatar_size - 1),
        fill=255,
    )

    # Неоновое свечение.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    glow_draw.ellipse(
        (
            avatar_x - 13,
            avatar_y - 13,
            avatar_x + avatar_size + 13,
            avatar_y + avatar_size + 13,
        ),
        outline=(212, 175, 55, 255),
        width=18,
    )

    glow = glow.filter(ImageFilter.GaussianBlur(18))
    image = Image.alpha_composite(image, glow)

    # Аватар поверх свечения.
    avatar_layer = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0),
    )
    avatar_layer.paste(
        avatar,
        (avatar_x, avatar_y),
        mask,
    )
    image = Image.alpha_composite(image, avatar_layer)

    draw = ImageDraw.Draw(image)

    # Золотая рамка.
    draw.ellipse(
        (
            avatar_x - 6,
            avatar_y - 6,
            avatar_x + avatar_size + 6,
            avatar_y + avatar_size + 6,
        ),
        outline=gold,
        width=7,
    )

    # Текстовые данные.
    full_name = str(user.get("full_name", "Участник"))
    user_id = str(user.get("user_id", "—"))
    rank = str(user.get("rank", "Участник"))
    balance = str(user.get("balance", 0))

    # Левая текстовая колонка.
    draw.text(
        (350, 180),
        full_name[:28],
        font=font_name,
        fill=white,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.text(
        (352, 235),
        f"ID: {user_id}",
        font=font_id,
        fill=grey,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )

    # Правая текстовая колонка.
    draw.text(
        (690, 170),
        "RANK",
        font=font_caption,
        fill=gold,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.text(
        (690, 200),
        rank[:18],
        font=font_rank,
        fill=gold,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.text(
        (690, 280),
        "TOKENS",
        font=font_caption,
        fill=gold,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )

    draw.text(
        (690, 310),
        balance,
        font=font_balance,
        fill=white,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    # Нижняя декоративная линия.
    draw.line(
        (90, 420, width - 90, 420),
        fill=(212, 175, 55, 160),
        width=2,
    )

    draw.text(
        (100, 445),
        "TOKENS | PRIVATE CLUB",
        font=font_caption,
        fill=gold,
    )

    output = io.BytesIO()
    image.convert("RGB").save(
        output,
        format="PNG",
        optimize=True,
    )

    output.seek(0)

    return BufferedInputFile(
        output.getvalue(),
        filename="profile.png",
    )


async def download_user_avatar(bot: Bot, user_id: int):
    try:
        photos = await bot.get_user_profile_photos(
            user_id=user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]
        destination = AVATARS_DIR / f"{user_id}.jpg"

        await bot.download(
            photo,
            destination=destination,
        )

        return str(destination)

    except Exception:
        logger.exception("Не удалось получить аватар пользователя %s", user_id)
        return None


# ============================================================
# BOT AND ROUTER
# ============================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ============================================================
# CAPTCHA
# ============================================================

@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    referrer_id = None
    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        payload = args[1].strip()

        if payload.startswith("ref_"):
            with suppress(ValueError):
                referrer_id = int(payload.replace("ref_", "", 1))

    user = await get_or_register_user(
        message.from_user,
        referrer_id,
    )

    if user["is_banned"]:
        await message.answer(tr(user, "banned"))
        return

    if user["is_verified"]:
        await message.answer(
            tr(user, "welcome"),
            reply_markup=main_keyboard(user_language(user)),
        )
        return

    await message.answer(
        tr(user, "captcha"),
        reply_markup=captcha_keyboard(user_language(user)),
    )


@router.callback_query(F.data == "captcha:start")
async def captcha_start_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    user = await db.get_user(callback.from_user.id)

    if user is None:
        await callback.answer()
        return

    a = random.randint(2, 9)
    b = random.randint(2, 9)

    await state.set_state(CaptchaState.waiting_answer)
    await state.update_data(captcha_answer=a + b)

    await callback.message.answer(
        tr(user, "captcha_question", a=a, b=b),
    )

    await callback.answer()


@router.message(CaptchaState.waiting_answer)
async def captcha_answer_handler(
    message: Message,
    state: FSMContext,
):
    data = await state.get_data()
    expected = data.get("captcha_answer")

    try:
        answer = int(message.text.strip())
    except (ValueError, AttributeError):
        answer = None

    user = await db.get_user(message.from_user.id)

    if answer != expected:
        await message.answer(tr(user, "captcha_wrong"))
        return

    await db.set_verified(message.from_user.id)
    await state.clear()

    user = await db.get_user(message.from_user.id)

    await message.answer(
        tr(user, "verified"),
        reply_markup=main_keyboard(user_language(user)),
    )


# ============================================================
# ACCESS MIDDLEWARE
# ============================================================

class VerificationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict,
    ):
        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            if event.from_user:
                user = await db.get_user(event.from_user.id)

                if user is None or not user["is_verified"]:
                    if event.text and event.text.startswith("/"):
                        await event.answer(
                            TEXTS["ru"]["not_verified"],
                            reply_markup=captcha_keyboard(),
                        )
                    return

                if user["is_banned"]:
                    await event.answer(tr(user, "banned"))
                    return

        return await handler(event, data)


router.message.middleware(VerificationMiddleware())


# ============================================================
# MAIN MENU
# ============================================================

@router.message(F.text.in_({"🎮 Активности", "🎮 Activities"}))
async def activities_menu_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    await message.answer(
        tr(user, "activities"),
        reply_markup=activities_keyboard(),
    )


@router.message(F.text.in_({"💎 Донат", "💎 Support"}))
async def donation_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    await message.answer(tr(user, "donate"))


@router.message(F.text.in_({"🆘 Поддержка", "🆘 Help"}))
async def support_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    await message.answer(tr(user, "support"))


@router.message(F.text.in_({"💬 Чаты", "💬 Chats"}))
async def chats_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    await message.answer(tr(user, "chats"))


@router.message(F.text.in_({"🤝 Партнёры", "🤝 Partners"}))
async def partners_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"

    referrals = await db.get_referrals_count(message.from_user.id)

    await message.answer(
        tr(user, "partners", link=link)
        + f"\n\nПриглашено участников: <b>{referrals}</b>"
    )


# ============================================================
# DAILY BONUS
# ============================================================

DAILY_BONUS_AMOUNT = 5000


@router.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def daily_bonus_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    success, next_available = await db.claim_daily_bonus(
        message.from_user.id,
        DAILY_BONUS_AMOUNT,
    )

    if success:
        await message.answer(
            tr(user, "bonus_success", amount=DAILY_BONUS_AMOUNT),
        )
        return

    now = datetime.now(timezone.utc)
    remaining = next_available - now

    seconds = max(0, int(remaining.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    await message.answer(
        tr(
            user,
            "bonus_wait",
            hours=hours,
            minutes=minutes,
        )
    )


# ============================================================
# PROFILE
# ============================================================

@router.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def profile_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    avatar_path = await download_user_avatar(
        bot,
        message.from_user.id,
    )

    profile_data = {
        "full_name": user["full_name"],
        "user_id": user["user_id"],
        "balance": user["balance"],
        "rank": user["rank"],
        "avatar_path": avatar_path,
    }

    photo = await asyncio.to_thread(
        generate_profile_image,
        profile_data,
    )

    await message.answer_photo(
        photo=photo,
        caption=tr(user, "profile"),
        reply_markup=profile_keyboard(user_language(user)),
    )


@router.callback_query(F.data == "profile:history")
async def profile_history_callback(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user or not user["is_verified"]:
        await callback.answer()
        return

    rows = await db.get_history(callback.from_user.id)

    if not rows:
        await callback.message.answer(tr(user, "history_empty"))
        await callback.answer()
        return

    lines = ["<b>История активности</b>", ""]

    for row in rows:
        created = row["created_at"][:16].replace("T", " ")
        lines.append(
            f"• {row['activity']} | результат: {row['result']} "
            f"| +{row['reward']} TOKENS | {created}"
        )

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "profile:achievements")
async def profile_achievements_callback(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user or not user["is_verified"]:
        await callback.answer()
        return

    total = await db.fetchone(
        """
        SELECT COUNT(*) AS total
        FROM activity_log
        WHERE user_id = ?
        """,
        (callback.from_user.id,),
    )

    count = int(total["total"]) if total else 0

    text = (
        "<b>Достижения</b>\n\n"
        f"Активностей выполнено: <b>{count}</b>\n"
        f"Приглашено участников: "
        f"<b>{await db.get_referrals_count(callback.from_user.id)}</b>"
    )

    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "profile:settings")
async def profile_settings_callback(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)

    if not user:
        await callback.answer()
        return

    await callback.message.answer(
        tr(user, "language"),
        reply_markup=language_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("language:"))
async def language_callback(callback: CallbackQuery):
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
# FREE ACTIVITIES
# ============================================================

ACTIVITIES = {
    "dice": {
        "emoji": "🎲",
        "name": "Кости",
    },
    "darts": {
        "emoji": "🎯",
        "name": "Дартс",
    },
    "basketball": {
        "emoji": "🏀",
        "name": "Баскетбол",
    },
    "football": {
        "emoji": "⚽",
        "name": "Футбол",
    },
    "bowling": {
        "emoji": "🎳",
        "name": "Боулинг",
    },
}

ACTIVITY_REWARD = 20


async def play_free_activity(
    message: Message,
    activity_key: str,
):
    user = await ensure_access(message)
    if not user:
        return

    activity = ACTIVITIES.get(activity_key)

    if activity is None:
        await message.answer(tr(user, "game_unknown"))
        return

    # В этих активностях нет взносов и списаний очков.
    result_message = await message.answer_dice(
        emoji=activity["emoji"],
    )

    # Telegram возвращает итоговое значение анимации.
    await asyncio.sleep(3)

    result = result_message.dice.value

    # Небольшое фиксированное начисление за участие.
    # Оно не зависит от суммы или предварительного платежа.
    reward = ACTIVITY_REWARD if result >= 4 else 0

    if reward:
        await db.change_balance(
            message.from_user.id,
            reward,
        )

    await db.add_activity(
        user_id=message.from_user.id,
        activity=activity_key,
        result=result,
        reward=reward,
    )

    if reward:
        result_text = tr(
            user,
            "game_reward",
            amount=reward,
        )
    else:
        result_text = tr(user, "game_no_reward")

    final_message = await message.answer(
        tr(
            user,
            "game_result",
            result=result,
            message=result_text,
        )
    )

    asyncio.create_task(auto_delete(result_message, 15))
    asyncio.create_task(auto_delete(final_message, 15))
    asyncio.create_task(auto_delete(message, 15))


@router.callback_query(F.data.startswith("activity:"))
async def activity_callback(callback: CallbackQuery):
    activity_key = callback.data.split(":", 1)[1]

    if activity_key not in ACTIVITIES:
        await callback.answer()
        return

    await callback.answer("Активность запущена.")

    await play_free_activity(
        callback.message,
        activity_key,
    )


@router.message(F.text.lower().in_({"кости", "🎲 кости"}))
async def dice_text_handler(message: Message):
    await play_free_activity(message, "dice")


@router.message(F.text.lower().in_({"дартс", "🎯 дартс"}))
async def darts_text_handler(message: Message):
    await play_free_activity(message, "darts")


@router.message(F.text.lower().in_({"баскет", "баскетбол", "🏀"}))
async def basketball_text_handler(message: Message):
    await play_free_activity(message, "basketball")


@router.message(F.text.lower().in_({"футбол", "⚽"}))
async def football_text_handler(message: Message):
    await play_free_activity(message, "football")


@router.message(F.text.lower().in_({"боулинг", "🎳"}))
async def bowling_text_handler(message: Message):
    await play_free_activity(message, "bowling")


# ============================================================
# LEADERBOARDS
# ============================================================

@router.message(F.text.in_({"📊 Топ", "📊 Top"}))
async def top_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    rows = await db.get_top(10)

    if not rows:
        await message.answer(tr(user, "top_empty"))
        return

    lines = ["<b>ТОП УЧАСТНИКОВ</b>", ""]

    for index, row in enumerate(rows, start=1):
        name = row["full_name"] or f"ID {row['user_id']}"
        lines.append(
            f"<b>{index}.</b> {name[:25]} — "
            f"<b>{row['balance']}</b> TOKENS"
        )

    await message.answer("\n".join(lines))


@router.message(F.text.in_({"🏆 Турнир", "🏆 Tournament"}))
async def tournament_handler(message: Message):
    user = await ensure_access(message)
    if not user:
        return

    rows = await db.get_weekly_top(10)

    if not rows or all(int(row["points"]) == 0 for row in rows):
        await message.answer(tr(user, "tournament_empty"))
        return

    lines = ["<b>АКТИВНОСТЬ ЗА 7 ДНЕЙ</b>", ""]

    for index, row in enumerate(rows, start=1):
        name = row["full_name"] or f"ID {row['user_id']}"
        lines.append(
            f"<b>{index}.</b> {name[:25]} — "
            f"<b>{row['points']}</b> очков"
        )

    await message.answer("\n".join(lines))


# ============================================================
# ADMIN TOOLS
# ============================================================

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_denied(message: Message):
    await message.answer(TEXTS["ru"]["admin_only"])


@router.message(F.text.startswith("@помощь"))
async def admin_help_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    await message.answer(TEXTS["ru"]["admin_help"])


@router.message(F.text.startswith("@выдать"))
async def admin_grant_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    parts = message.text.split()

    if len(parts) != 3:
        await message.answer(
            "Формат: <code>@выдать ID КОЛИЧЕСТВО</code>"
        )
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("ID и количество должны быть числами.")
        return

    if amount <= 0 or amount > 1_000_000:
        await message.answer("Укажите положительное количество до 1000000.")
        return

    target = await db.get_user(target_id)

    if not target:
        await message.answer("Участник не найден.")
        return

    success = await db.change_balance(target_id, amount)

    if not success:
        await message.answer("Не удалось выполнить начисление.")
        return

    await db.admin_log(
        message.from_user.id,
        "grant_points",
        target_id,
        amount,
    )

    await message.answer(
        f"Начислено <b>{amount}</b> TOKENS участнику "
        f"<code>{target_id}</code>."
    )

    with suppress(Exception):
        lang = user_language(target)
        await bot.send_message(
            target_id,
            (
                f"Администратор начислил Вам "
                f"<b>+{amount} TOKENS</b>."
            ),
        )


@router.message(F.text.startswith("@дроп"))
async def admin_drop_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "Формат: <code>@дроп КОЛИЧЕСТВО</code>"
        )
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("Количество должно быть числом.")
        return

    if amount <= 0 or amount > 100_000:
        await message.answer("Допустимое значение: от 1 до 100000.")
        return

    user_ids = await db.all_user_ids()
    successful = 0

    for user_id in user_ids:
        try:
            if await db.change_balance(user_id, amount):
                successful += 1
        except Exception:
            logger.exception("Ошибка начисления пользователю %s", user_id)

        await asyncio.sleep(0.02)

    await db.admin_log(
        message.from_user.id,
        "community_reward",
        None,
        amount,
    )

    await message.answer(
        f"Бонус начислен участникам: <b>{successful}</b>.\n"
        f"Размер начисления: <b>{amount} TOKENS</b>."
    )


@router.message(F.text.startswith("@бан"))
async def admin_ban_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer("Формат: <code>@бан ID</code>")
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

    await db.admin_log(
        message.from_user.id,
        "ban",
        target_id,
    )

    await message.answer(
        f"Доступ участника <code>{target_id}</code> ограничен."
    )


@router.message(F.text.startswith("@стата"))
async def admin_stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    total = await db.count_users()
    verified = await db.count_verified()
    activities = await db.count_activities()

    await message.answer(
        "<b>СТАТИСТИКА КЛУБА</b>\n\n"
        f"Участников: <b>{total}</b>\n"
        f"Прошли проверку: <b>{verified}</b>\n"
        f"Активностей: <b>{activities}</b>"
    )


@router.message(F.text.startswith("@бекап"))
async def admin_backup_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"club_{timestamp}.sqlite3"

    try:
        async with db.lock:
            backup_connection = await aiosqlite.connect(
                str(destination)
            )

            await db.connection.backup(backup_connection)
            await backup_connection.close()

        await db.admin_log(
            message.from_user.id,
            "backup",
        )

        await message.answer_document(
            BufferedInputFile(
                destination.read_bytes(),
                filename=destination.name,
            ),
            caption="Резервная копия базы данных.",
        )

    except Exception:
        logger.exception("Backup error")
        await message.answer("Не удалось создать резервную копию.")


@router.message(F.text.startswith("@рестарт"))
async def admin_restart_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    await message.answer(
        "Для безопасного перезапуска используйте панель "
        "управления хостингом."
    )


# ============================================================
# SCHEDULED EVENTS
# ============================================================

scheduler = AsyncIOScheduler(
    timezone="UTC",
)


async def scheduled_community_drop():
    """
    Периодическое бесплатное начисление очков.

    Никаких списаний или условий денежного участия.
    """
    try:
        user_ids = await db.all_user_ids()

        if not user_ids:
            return

        selected = random.sample(
            user_ids,
            k=min(5, len(user_ids)),
        )

        for user_id in selected:
            await db.change_balance(user_id, 100)
            await db.add_activity(
                user_id,
                "community_event",
                1,
                100,
            )

            with suppress(Exception):
                await bot.send_message(
                    user_id,
                    "🎁 Вам начислен бонус события клуба: "
                    "<b>+100 TOKENS</b>.",
                )

    except Exception:
        logger.exception("Ошибка события сообщества")


async def scheduled_database_cleanup():
    try:
        await db.clean_old_activity(days=180)
        logger.info("Очистка старой истории завершена.")
    except Exception:
        logger.exception("Ошибка очистки базы данных")


async def scheduled_community_announcement():
    """
    Небольшое информационное сообщение для участников.
    """
    try:
        user_ids = await db.all_user_ids()

        for user_id in user_ids:
            with suppress(Exception):
                await bot.send_message(
                    user_id,
                    "✨ В клубе продолжаются активности. "
                    "Загляните в меню «🎮 Активности».",
                )
            await asyncio.sleep(0.03)

    except Exception:
        logger.exception("Ошибка рассылки события")


def setup_scheduler():
    scheduler.add_job(
        scheduled_community_drop,
        trigger="interval",
        hours=6,
        id="community_drop",
        replace_existing=True,
    )

    scheduler.add_job(
        scheduled_database_cleanup,
        trigger="cron",
        hour=4,
        minute=30,
        id="database_cleanup",
        replace_existing=True,
    )

    scheduler.start()


# ============================================================
# HEALTH SERVER
# ============================================================

async def health_handler(request: web.Request):
    return web.json_response(
        {
            "status": "ok",
            "service": "TOKENS | PRIVATE CLUB",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info("Health endpoint started on port %s", PORT)
    return runner


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@dp.errors()
async def global_error_handler(event):
    exception = event.exception

    logger.exception(
        "Unhandled update exception",
        exc_info=exception,
    )

    if ADMIN_ID:
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                (
                    "<b>Ошибка бота</b>\n\n"
                    f"<code>{type(exception).__name__}</code>\n"
                    f"{str(exception)[:2500]}"
                ),
            )

    return True


# ============================================================
# STARTUP AND SHUTDOWN
# ============================================================

async def on_startup():
    await db.connect()
    setup_scheduler()

    logger.info("Database initialized.")
    logger.info("Scheduler started.")


async def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)

    await db.close()

    with suppress(Exception):
        await bot.session.close()

    logger.info("TOKENS | PRIVATE CLUB stopped.")


async def main():
    await on_startup()

    health_runner = await start_health_server()

    try:
        logger.info("Bot polling started.")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:
        with suppress(Exception):
            await health_runner.cleanup()

        await on_shutdown()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")