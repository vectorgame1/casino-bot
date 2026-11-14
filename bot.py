import asyncio
import io
import logging
import os
import random
import time
from pathlib import Path
from contextlib import suppress

import aiosqlite
import aiohttp
from aiohttp import web

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    BotCommand,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
PORT = int(os.getenv("PORT", "8080"))

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
AVATARS_DIR = BASE_DIR / "avatars"

ASSETS_DIR.mkdir(exist_ok=True)
AVATARS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("private-club")

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")


# ============================================================
# LINKS
# ============================================================

SUPPORT_URL = "https://t.me/vctorw"
GAME_CHAT_URL = "https://t.me/tokenplays"
EXCHANGE_CHAT_URL = "https://t.me/Tokenschange"
NEWS_CHAT_URL = "https://t.me/TokenCasinoTournaments"


# ============================================================
# TEXTS
# ============================================================

TEXTS = {
    "welcome": (
        "✨ Добро пожаловать в TOKENS | PRIVATE CLUB!\n\n"
        "Здесь доступны профиль, бонусы, активности и таблица лидеров."
    ),
    "captcha": (
        "🔐 Подтверди, что ты не робот.\n\n"
        "Введи число, изображённое на картинке."
    ),
    "captcha_wrong": "❌ Неверный код. Попробуй ещё раз.",
    "captcha_ok": "✅ Проверка пройдена! Добро пожаловать.",
    "profile": "👤 Твой профиль",
    "bonus": "🎁 Ежедневный бонус",
    "donate": (
        "💎 Поддержка проекта\n\n"
        "Платёжные операции в этой версии бота не поддерживаются."
    ),
    "top": "📊 Таблица лидеров",
    "activities": "🎮 Бесплатные активности",
    "partners": "🤝 Партнёрская программа",
    "tournament": "🏆 Турнир",
    "chats": "💬 Наши сообщества",
    "support": "🆘 Поддержка",
    "not_verified": "Сначала пройди проверку через /start.",
    "bonus_received": "🎁 Ты получил 5000 бесплатных баллов!",
    "bonus_wait": "⏳ Бонус уже получен. Возвращайся позже.",
}


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()

    async def connect(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA foreign_keys=ON")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        full_name TEXT,
                        balance INTEGER NOT NULL DEFAULT 0,
                        rank TEXT NOT NULL DEFAULT 'Новичок',
                        is_verified INTEGER NOT NULL DEFAULT 0,
                        is_banned INTEGER NOT NULL DEFAULT 0,
                        language TEXT NOT NULL DEFAULT 'ru',
                        created_at INTEGER NOT NULL,
                        last_bonus INTEGER NOT NULL DEFAULT 0
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        activity TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS referrals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        referrer_id INTEGER NOT NULL,
                        referred_id INTEGER NOT NULL UNIQUE,
                        created_at INTEGER NOT NULL
                    )
                """)

                await conn.commit()

    async def close(self):
        pass

    async def register_user(
        self,
        user_id: int,
        username: str,
        full_name: str,
    ):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    INSERT OR IGNORE INTO users (
                        user_id, username, full_name, created_at
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    user_id,
                    username,
                    full_name,
                    int(time.time()),
                ))

                await conn.execute("""
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                """, (username, full_name, user_id))

                await conn.commit()

    async def get_user(self, user_id: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT
                        user_id,
                        username,
                        full_name,
                        balance,
                        rank,
                        is_verified,
                        is_banned,
                        language,
                        created_at,
                        last_bonus
                    FROM users
                    WHERE user_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

        if row is None:
            return None

        keys = (
            "user_id",
            "username",
            "full_name",
            "balance",
            "rank",
            "is_verified",
            "is_banned",
            "language",
            "created_at",
            "last_bonus",
        )

        return dict(zip(keys, row))

    async def set_verified(self, user_id: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    UPDATE users
                    SET is_verified = 1
                    WHERE user_id = ?
                """, (user_id,))
                await conn.commit()

    async def set_banned(self, user_id: int, banned: bool):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    UPDATE users
                    SET is_banned = ?
                    WHERE user_id = ?
                """, (int(banned), user_id))
                await conn.commit()

    async def change_balance(self, user_id: int, amount: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN TRANSACTION")

                async with conn.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False

                new_balance = row[0] + amount

                if new_balance < 0:
                    await conn.rollback()
                    return False

                await conn.execute("""
                    UPDATE users
                    SET balance = ?
                    WHERE user_id = ?
                """, (new_balance, user_id))

                await conn.commit()
                return True

    async def claim_bonus(self, user_id: int):
        now = int(time.time())
        bonus_period = 24 * 60 * 60

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN TRANSACTION")

                async with conn.execute("""
                    SELECT last_bonus
                    FROM users
                    WHERE user_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False

                if now - row[0] < bonus_period:
                    await conn.rollback()
                    return False

                await conn.execute("""
                    UPDATE users
                    SET balance = balance + 5000,
                        last_bonus = ?
                    WHERE user_id = ?
                """, (now, user_id))

                await conn.commit()
                return True

    async def get_top(self, limit: int = 10):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id, full_name, balance
                    FROM users
                    WHERE is_banned = 0
                    ORDER BY balance DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    rows = await cursor.fetchall()

        return rows

    async def get_referrals_count(self, user_id: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT COUNT(*)
                    FROM referrals
                    WHERE referrer_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

        return row[0] if row else 0

    async def add_referral(self, referrer_id: int, referred_id: int):
        if referrer_id == referred_id:
            return False

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                try:
                    await conn.execute("""
                        INSERT INTO referrals (
                            referrer_id,
                            referred_id,
                            created_at
                        )
                        VALUES (?, ?, ?)
                    """, (
                        referrer_id,
                        referred_id,
                        int(time.time()),
                    ))
                    await conn.commit()
                    return True
                except aiosqlite.IntegrityError:
                    return False

    async def add_activity(self, user_id: int, activity: str):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    INSERT INTO activity_log (
                        user_id,
                        activity,
                        created_at
                    )
                    VALUES (?, ?, ?)
                """, (user_id, activity, int(time.time())))

                await conn.commit()

    async def stats(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT COUNT(*), COALESCE(SUM(balance), 0)
                    FROM users
                """) as cursor:
                    row = await cursor.fetchone()

        return row


db = Database(DB_PATH)


# ============================================================
# USER CACHE
# ============================================================

class UserCache:
    def __init__(self, ttl: int = 5):
        self.ttl = ttl
        self.data = {}

    async def get(self, user_id: int):
        now = time.monotonic()
        cached = self.data.get(user_id)

        if cached and now - cached["time"] < self.ttl:
            return cached["user"]

        user = await db.get_user(user_id)

        if user is not None:
            self.data[user_id] = {
                "time": now,
                "user": user,
            }

        return user

    def invalidate(self, user_id: int):
        self.data.pop(user_id, None)


user_cache = UserCache(ttl=5)


# ============================================================
# CAPTCHA
# ============================================================

class CaptchaState(StatesGroup):
    waiting_for_answer = State()


def generate_captcha_image(answer: str) -> BufferedInputFile:
    width, height = 360, 150

    image = Image.new("RGB", (width, height), (20, 20, 32))
    draw = ImageDraw.Draw(image)

    for _ in range(450):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = random.choice([
            (70, 70, 95),
            (100, 85, 65),
            (65, 85, 110),
        ])
        draw.point((x, y), fill=color)

    for _ in range(9):
        points = [
            (
                random.randint(0, width),
                random.randint(0, height),
            )
            for _ in range(2)
        ]

        draw.line(
            points,
            fill=(random.randint(70, 150), 110, 80),
            width=2,
        )

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 58)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), answer, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    position = (
        (width - text_width) // 2,
        (height - text_height) // 2 - 5,
    )

    draw.text(
        position,
        answer,
        font=font,
        fill=(255, 205, 90),
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)

    return BufferedInputFile(output.read(), filename="captcha.png")


async def send_captcha(message: Message, state: FSMContext):
    answer = str(random.randint(10000, 99999))

    await state.set_state(CaptchaState.waiting_for_answer)
    await state.update_data(captcha_answer=answer)

    photo = generate_captcha_image(answer)

    await message.answer_photo(
        photo=photo,
        caption=TEXTS["captcha"],
    )


# ============================================================
# PROFILE IMAGE
# ============================================================

def load_font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def generate_profile_image(user: dict, avatar_path: str | None):
    background_path = ASSETS_DIR / "profile.jpg"

    if background_path.exists():
        background = Image.open(background_path).convert("RGB")
        background = background.resize((900, 600))
    else:
        background = Image.new(
            "RGB",
            (900, 600),
            (18, 18, 30),
        )

    background = background.convert("RGBA")

    overlay = Image.new("RGBA", background.size, (0, 0, 0, 115))
    background.alpha_composite(overlay)

    draw = ImageDraw.Draw(background)

    gold = (255, 205, 95, 255)
    white = (245, 245, 250, 255)

    avatar_size = 220
    avatar_x = 85
    avatar_y = 120

    glow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    glow_draw.ellipse(
        (
            avatar_x - 15,
            avatar_y - 15,
            avatar_x + avatar_size + 15,
            avatar_y + avatar_size + 15,
        ),
        fill=(255, 190, 50, 140),
    )

    glow = glow.filter(ImageFilter.GaussianBlur(22))
    background.alpha_composite(glow)

    if avatar_path and Path(avatar_path).exists():
        avatar = Image.open(avatar_path).convert("RGBA")
    else:
        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (55, 55, 75, 255),
        )

    avatar = avatar.resize((avatar_size, avatar_size))

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse(
        (0, 0, avatar_size - 1, avatar_size - 1),
        fill=255,
    )

    background.paste(
        avatar,
        (avatar_x, avatar_y),
        mask,
    )

    draw = ImageDraw.Draw(background)

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

    title_font = load_font(42)
    text_font = load_font(29)
    small_font = load_font(23)

    name = user.get("full_name") or "Пользователь"

    draw.text(
        (370, 105),
        "PRIVATE CLUB",
        font=title_font,
        fill=gold,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    lines = [
        f"Имя: {name}",
        f"ID: {user['user_id']}",
        f"Ранг: {user.get('rank', 'Новичок')}",
        f"Баланс: {user.get('balance', 0):,}",
    ]

    y = 205

    for line in lines:
        draw.text(
            (370, y),
            line,
            font=text_font,
            fill=white,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )
        y += 65

    draw.text(
        (85, 440),
        "TOKENS | PRIVATE CLUB",
        font=small_font,
        fill=gold,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    output = io.BytesIO()
    background.convert("RGB").save(output, format="JPEG", quality=92)
    output.seek(0)

    return output.getvalue()


async def download_avatar(bot: Bot, user_id: int):
    path = AVATARS_DIR / f"{user_id}.jpg"

    try:
        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1,
        )

        if not photos.photos:
            return str(path) if path.exists() else None

        photo = photos.photos[0][-1]

        await bot.download(
            photo,
            destination=path,
        )

        return str(path)

    except Exception:
        logger.exception("Не удалось загрузить аватар %s", user_id)
        return str(path) if path.exists() else None


# ============================================================
# BOT SETUP
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

dp.include_router(router)


# ============================================================
# KEYBOARDS
# ============================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🎮 Активности"),
            KeyboardButton(text="🎁 Бонус"),
        ],
        [
            KeyboardButton(text="💎 Донат"),
            KeyboardButton(text="👤 Профиль"),
        ],
        [
            KeyboardButton(text="🤝 Партнёры"),
            KeyboardButton(text="🏆 Турнир"),
        ],
        [
            KeyboardButton(text="📊 Топ"),
            KeyboardButton(text="💬 Чаты"),
        ],
        [
            KeyboardButton(text="🆘 Поддержка"),
        ],
    ],
    resize_keyboard=True,
)


ACTIVITY_KEYBOARD = InlineKeyboardMarkup(
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
            ),
        ],
    ]
)


# ============================================================
# HELPERS
# ============================================================

async def get_verified_user(user_id: int):
    user = await user_cache.get(user_id)

    if user is None:
        return None

    if user["is_banned"]:
        return None

    return user


async def send_asset(
    message: Message,
    asset_name: str,
    caption: str,
    reply_markup=None,
):
    path = ASSETS_DIR / asset_name

    if path.exists():
        try:
            await message.answer_photo(
                photo=BufferedInputFile(
                    path.read_bytes(),
                    filename=asset_name,
                ),
                caption=caption,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.exception("Ошибка отправки изображения %s", asset_name)

    await message.answer(
        caption,
        reply_markup=reply_markup,
    )


async def auto_delete(message: Message, delay: int = 15):
    await asyncio.sleep(delay)

    with suppress(TelegramBadRequest):
        await message.delete()


async def ensure_user(message: Message):
    user = message.from_user

    if not user:
        return

    await db.register_user(
        user.id,
        user.username or "",
        user.full_name,
    )

    user_cache.invalidate(user.id)


# ============================================================
# VERIFICATION MIDDLEWARE
# ============================================================

class VerificationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event,
        data,
    ):
        state: FSMContext = data["state"]

        if isinstance(event, Message):
            if event.from_user is None:
                return

            user_id = event.from_user.id

            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            if await state.get_state() == CaptchaState.waiting_for_answer.state:
                return await handler(event, data)

            user = await user_cache.get(user_id)

            if user is None:
                await db.register_user(
                    user_id,
                    event.from_user.username or "",
                    event.from_user.full_name,
                )
                user_cache.invalidate(user_id)
                user = await user_cache.get(user_id)

            if user and user["is_banned"]:
                await event.answer("⛔ Доступ ограничен.")
                return

            if not user or not user["is_verified"]:
                await send_captcha(event, state)
                return

        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            user = await user_cache.get(user_id)

            if user is None:
                await db.register_user(
                    user_id,
                    event.from_user.username or "",
                    event.from_user.full_name,
                )
                user_cache.invalidate(user_id)
                user = await user_cache.get(user_id)

            if user and user["is_banned"]:
                await event.answer("⛔ Доступ ограничен.", show_alert=True)
                return

            if not user or not user["is_verified"]:
                await event.answer(
                    "Сначала пройди проверку через /start.",
                    show_alert=True,
                )

                if event.message:
                    await send_captcha(event.message, state)

                return

        return await handler(event, data)


router.message.middleware(VerificationMiddleware())
router.callback_query.middleware(VerificationMiddleware())


# ============================================================
# START AND CAPTCHA
# ============================================================

@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
):
    await ensure_user(message)

    user = await user_cache.get(message.from_user.id)

    if user and user["is_banned"]:
        await message.answer("⛔ Доступ ограничен.")
        return

    if user and user["is_verified"]:
        await send_asset(
            message,
            "start.jpg",
            TEXTS["welcome"],
            MAIN_KEYBOARD,
        )
        return

    # Проверка нужна только до первого успешного прохождения.
    await send_captcha(message, state)


@router.message(CaptchaState.waiting_for_answer)
async def captcha_answer_handler(
    message: Message,
    state: FSMContext,
):
    data = await state.get_data()
    expected = data.get("captcha_answer", "")

    supplied = (message.text or "").strip()

    if supplied != expected:
        await message.answer(TEXTS["captcha_wrong"])
        await send_captcha(message, state)
        return

    user_id = message.from_user.id

    await db.set_verified(user_id)
    user_cache.invalidate(user_id)

    await state.clear()

    await message.answer(TEXTS["captcha_ok"])

    await send_asset(
        message,
        "start.jpg",
        TEXTS["welcome"],
        MAIN_KEYBOARD,
    )


# ============================================================
# PROFILE
# ============================================================

@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):
    user = await get_verified_user(message.from_user.id)

    if not user:
        await message.answer(TEXTS["not_verified"])
        return

    avatar_path = await download_avatar(
        bot,
        message.from_user.id,
    )

    image_bytes = await asyncio.to_thread(
        generate_profile_image,
        user,
        avatar_path,
    )

    await message.answer_photo(
        photo=BufferedInputFile(
            image_bytes,
            filename="profile.jpg",
        ),
        caption=TEXTS["profile"],
    )


# ============================================================
# BONUS
# ============================================================

@router.message(F.text == "🎁 Бонус")
async def bonus_handler(message: Message):
    user = await get_verified_user(message.from_user.id)

    if not user:
        await message.answer(TEXTS["not_verified"])
        return

    received = await db.claim_bonus(message.from_user.id)

    user_cache.invalidate(message.from_user.id)

    if received:
        caption = TEXTS["bonus_received"]
    else:
        caption = TEXTS["bonus_wait"]

    await send_asset(
        message,
        "bonus.jpg",
        caption,
    )


# ============================================================
# DONATE
# ============================================================

@router.message(F.text == "💎 Донат")
async def donate_handler(message: Message):
    await send_asset(
        message,
        "donate.jpg",
        TEXTS["donate"],
    )


# ============================================================
# ACTIVITIES
# ============================================================

@router.message(F.text == "🎮 Активности")
async def activities_handler(message: Message):
    await send_asset(
        message,
        "how_to_play.jpg",
        TEXTS["activities"] + "\n\nВыбери бесплатную активность:",
        ACTIVITY_KEYBOARD,
    )


ACTIVITY_EMOJIS = {
    "dice": "🎲",
    "darts": "🎯",
    "basketball": "🏀",
    "football": "⚽",
    "bowling": "🎳",
}

ACTIVITY_NAMES = {
    "dice": "Кости",
    "darts": "Дартс",
    "basketball": "Баскетбол",
    "football": "Футбол",
    "bowling": "Боулинг",
}


@router.callback_query(F.data.startswith("activity:"))
async def activity_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]

    if key not in ACTIVITY_EMOJIS:
        await callback.answer("Неизвестная активность.", show_alert=True)
        return

    user = await get_verified_user(callback.from_user.id)

    if not user:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    await callback.answer("Запускаю активность!")

    if not callback.message:
        return

    # Бесплатная активность: без ставок, списаний и денежных призов.
    dice_message = await bot.send_dice(
        chat_id=callback.message.chat.id,
        emoji=ACTIVITY_EMOJIS[key],
    )

    await db.add_activity(
        callback.from_user.id,
        key,
    )

    result_message = await bot.send_message(
        callback.message.chat.id,
        (
            f"🎮 Активность: {ACTIVITY_NAMES[key]}\n"
            f"Игрок: {callback.from_user.full_name}\n"
            f"Результат: {dice_message.dice.value}\n\n"
            "Спасибо за участие!"
        ),
    )

    asyncio.create_task(auto_delete(dice_message, 15))
    asyncio.create_task(auto_delete(result_message, 15))


# ============================================================
# LEADERBOARD
# ============================================================

@router.message(F.text == "📊 Топ")
async def top_handler(message: Message):
    rows = await db.get_top(10)

    lines = ["🏆 ТОП-10 УЧАСТНИКОВ\n"]

    if not rows:
        lines.append("Пока здесь никого нет.")
    else:
        for index, row in enumerate(rows, start=1):
            user_id, full_name, balance = row
            name = full_name or f"Игрок {user_id}"

            lines.append(
                f"{index}. {name} — {balance:,} баллов"
            )

    await send_asset(
        message,
        "top.jpg",
        "\n".join(lines),
    )


# ============================================================
# PARTNERS
# ============================================================

@router.message(F.text == "🤝 Партнёры")
async def partners_handler(message: Message):
    username = (await bot.get_me()).username

    referral_link = (
        f"https://t.me/{username}?start={message.from_user.id}"
    )

    count = await db.get_referrals_count(message.from_user.id)

    await message.answer(
        "🤝 Партнёрская программа\n\n"
        f"Твоя ссылка:\n{referral_link}\n\n"
        f"Приглашено участников: {count}"
    )


# ============================================================
# TOURNAMENT
# ============================================================

@router.message(F.text == "🏆 Турнир")
async def tournament_handler(message: Message):
    rows = await db.get_top(10)

    lines = ["🏆 РЕЙТИНГ УЧАСТНИКОВ\n"]

    for index, row in enumerate(rows, start=1):
        _, full_name, balance = row
        lines.append(
            f"{index}. {full_name or 'Участник'} — {balance:,}"
        )

    await message.answer("\n".join(lines))


# ============================================================
# CHATS
# ============================================================

@router.message(F.text == "💬 Чаты")
async def chats_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Игровой чат",
                    url=GAME_CHAT_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Чат обмена",
                    url=EXCHANGE_CHAT_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📰 Новости",
                    url=NEWS_CHAT_URL,
                ),
            ],
        ]
    )

    await send_asset(
        message,
        "chats.jpg",
        TEXTS["chats"],
        keyboard,
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
                    text="Открыть поддержку",
                    url=SUPPORT_URL,
                ),
            ],
        ]
    )

    await send_asset(
        message,
        "support.jpg",
        TEXTS["support"],
        keyboard,
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

def is_admin(user_id: int):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


@router.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    users_count, total_balance = await db.stats()

    await message.answer(
        "📊 Статистика\n\n"
        f"Пользователей: {users_count}\n"
        f"Всего баллов: {total_balance:,}"
    )


@router.message(Command("give"))
async def admin_give(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 3:
        await message.answer(
            "Использование: /give USER_ID AMOUNT"
        )
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("ID и количество должны быть числами.")
        return

    if amount <= 0:
        await message.answer("Количество должно быть положительным.")
        return

    success = await db.change_balance(target_id, amount)

    if success:
        user_cache.invalidate(target_id)
        await message.answer("✅ Баллы начислены.")
    else:
        await message.answer("❌ Не удалось выполнить операцию.")


@router.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Использование: /ban USER_ID")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный ID.")
        return

    await db.set_banned(target_id, True)
    user_cache.invalidate(target_id)

    await message.answer("⛔ Пользователь заблокирован.")


@router.message(Command("unban"))
async def admin_unban(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.answer("Использование: /unban USER_ID")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный ID.")
        return

    await db.set_banned(target_id, False)
    user_cache.invalidate(target_id)

    await message.answer("✅ Пользователь разблокирован.")


# ============================================================
# ERROR HANDLER
# ============================================================

@router.errors()
async def global_error_handler(event):
    exception = event.exception

    logger.exception(
        "Необработанная ошибка",
        exc_info=exception,
    )

    if ADMIN_ID:
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                "⚠️ Ошибка в боте:\n"
                f"{type(exception).__name__}: {exception}",
            )

    return True


# ============================================================
# HEALTH SERVER
# ============================================================

async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "service": "TOKENS PRIVATE CLUB",
    })


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()

    logger.info("Health server started on port %s", PORT)

    return runner


# ============================================================
# SCHEDULER
# ============================================================

scheduler = AsyncIOScheduler()


async def scheduled_announcement():
    logger.info("Плановое событие выполнено.")


def setup_scheduler():
    scheduler.add_job(
        scheduled_announcement,
        "cron",
        hour=12,
        minute=0,
    )

    scheduler.start()


# ============================================================
# STARTUP
# ============================================================

async def on_startup():
    await db.connect()

    await bot.set_my_commands([
        BotCommand(
            command="start",
            description="Запустить бота",
        ),
        BotCommand(
            command="stats",
            description="Статистика администратора",
        ),
        BotCommand(
            command="give",
            description="Начислить баллы",
        ),
        BotCommand(
            command="ban",
            description="Заблокировать пользователя",
        ),
        BotCommand(
            command="unban",
            description="Разблокировать пользователя",
        ),
    ])

    setup_scheduler()

    logger.info("Bot started")


# ============================================================
# SHUTDOWN
# ============================================================

async def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)

    await db.close()
    await bot.session.close()

    logger.info("Bot stopped")


# ============================================================
# MAIN
# ============================================================

async def main():
    await on_startup()

    health_runner = await start_health_server()

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await health_runner.cleanup()
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())