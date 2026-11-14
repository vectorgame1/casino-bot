
import asyncio
import io
import logging
import os
import random
import time
from pathlib import Path
from contextlib import suppress

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.middleware.base import BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ErrorEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "tokens_club.db")
PORT = int(os.getenv("PORT", "8080"))

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

START_PHOTO = ASSETS_DIR / "start.jpg"
PROFILE_BG = ASSETS_DIR / "profile_bg.jpg"
PROFILE_FALLBACK = ASSETS_DIR / "profile.jpg"
BONUS_PHOTO = ASSETS_DIR / "bonus.jpg"
TOP_PHOTO = ASSETS_DIR / "top.jpg"
TOURNAMENT_PHOTO = ASSETS_DIR / "tournament.jpg"
HOW_TO_PLAY_PHOTO = ASSETS_DIR / "how_to_play.jpg"
SUPPORT_PHOTO = ASSETS_DIR / "support.jpg"
CHATS_PHOTO = ASSETS_DIR / "chats.jpg"

SUPPORT_URL = "https://t.me/vctorw"
GAME_CHAT_URL = "https://t.me/tokenplays"
EXCHANGE_URL = "https://t.me/Tokenschange"
NEWS_URL = "https://t.me/TokenCasinoTournaments"

ACTIVITY_REWARD = 10
ACTIVITY_COOLDOWN = 60
BONUS_AMOUNT = 25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens-club")


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()
        self.cache = {}

    async def init(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT DEFAULT '',
                        full_name TEXT DEFAULT '',
                        balance INTEGER DEFAULT 0,
                        is_verified INTEGER DEFAULT 0,
                        last_bonus INTEGER DEFAULT 0,
                        joined_at INTEGER DEFAULT 0
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity_cooldowns (
                        user_id INTEGER NOT NULL,
                        activity TEXT NOT NULL,
                        last_play INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, activity)
                    )
                """)

                await conn.commit()

    def invalidate_cache(self, user_id: int):
        self.cache.pop(user_id, None)

    async def ensure_user(self, user_id: int, username: str, full_name: str):
        now = int(time.time())

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    INSERT OR IGNORE INTO users
                    (user_id, username, full_name, balance, is_verified, joined_at)
                    VALUES (?, ?, ?, 0, 0, ?)
                """, (user_id, username or "", full_name or "", now))

                await conn.execute("""
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                """, (username or "", full_name or "", user_id))

                await conn.commit()

        self.invalidate_cache(user_id)

    async def get_user(self, user_id: int):
        now = time.time()
        cached = self.cache.get(user_id)

        if cached and now - cached["time"] < 5:
            return cached["data"]

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id, username, full_name, balance,
                           is_verified, last_bonus, joined_at
                    FROM users
                    WHERE user_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

        if row is None:
            return None

        data = {
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "balance": row[3],
            "is_verified": bool(row[4]),
            "last_bonus": row[5],
            "joined_at": row[6],
        }

        self.cache[user_id] = {
            "time": now,
            "data": data,
        }
        return data

    async def set_verified(self, user_id: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute(
                    "UPDATE users SET is_verified = 1 WHERE user_id = ?",
                    (user_id,),
                )
                await conn.commit()

        self.invalidate_cache(user_id)

    async def change_balance(self, user_id: int, amount: int):
        """
        Изменение баланса с защитой от отрицательного значения.
        В игровых обработчиках используются только положительные
        фиксированные награды. Списание за участие не используется.
        """
        if amount == 0:
            return False

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False

                new_balance = row[0] + amount

                if new_balance < 0:
                    await conn.rollback()
                    return False

                await conn.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (new_balance, user_id),
                )
                await conn.commit()

        self.invalidate_cache(user_id)
        return True

    async def claim_bonus(self, user_id: int):
        now = int(time.time())
        day = 24 * 60 * 60

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT last_bonus FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False, 0

                last_bonus = row[0]

                if now - last_bonus < day:
                    remaining = day - (now - last_bonus)
                    await conn.rollback()
                    return False, remaining

                await conn.execute("""
                    UPDATE users
                    SET balance = balance + ?, last_bonus = ?
                    WHERE user_id = ?
                """, (BONUS_AMOUNT, now, user_id))

                await conn.commit()

        self.invalidate_cache(user_id)
        return True, BONUS_AMOUNT

    async def claim_activity(self, user_id: int, activity: str):
        now = int(time.time())

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute("""
                    SELECT last_play
                    FROM activity_cooldowns
                    WHERE user_id = ? AND activity = ?
                """, (user_id, activity)) as cursor:
                    row = await cursor.fetchone()

                last_play = row[0] if row else 0
                elapsed = now - last_play

                if elapsed < ACTIVITY_COOLDOWN:
                    await conn.rollback()
                    return False, ACTIVITY_COOLDOWN - elapsed

                await conn.execute("""
                    INSERT INTO activity_cooldowns
                    (user_id, activity, last_play)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, activity)
                    DO UPDATE SET last_play = excluded.last_play
                """, (user_id, activity, now))

                await conn.execute("""
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ?
                """, (ACTIVITY_REWARD, user_id))

                await conn.commit()

        self.invalidate_cache(user_id)
        return True, ACTIVITY_REWARD

    async def get_top(self, limit: int = 10):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id, username, full_name, balance
                    FROM users
                    WHERE is_verified = 1
                    ORDER BY balance DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    return await cursor.fetchall()

    async def close(self):
        pass


db = Database(DB_PATH)


# ============================================================
# FSM
# ============================================================

class Captcha(StatesGroup):
    waiting = State()


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎮 Активности"),
                KeyboardButton(text="🎁 Бонус"),
                KeyboardButton(text="💎 Магазин"),
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
    )


def activities_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Кости",
                    callback_data="game:dice",
                ),
                InlineKeyboardButton(
                    text="🎯 Дартс",
                    callback_data="game:darts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏀 Баскетбол",
                    callback_data="game:basketball",
                ),
                InlineKeyboardButton(
                    text="⚽ Футбол",
                    callback_data="game:football",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎳 Боулинг",
                    callback_data="game:bowling",
                ),
            ],
        ]
    )


# ============================================================
# HELPERS
# ============================================================

async def auto_delete(message: Message, seconds: int):
    if message.chat.type != ChatType.PRIVATE:
        return

    await asyncio.sleep(seconds)

    with suppress(Exception):
        await message.delete()


async def temp_answer(message: Message, text: str, **kwargs):
    sent = await message.answer(text, **kwargs)

    if message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(sent, 30))

    return sent


async def temp_photo(
    message: Message,
    photo_path: Path,
    caption: str,
    **kwargs,
):
    if photo_path.exists():
        sent = await message.answer_photo(
            BufferedInputFile(
                photo_path.read_bytes(),
                filename=photo_path.name,
            ),
            caption=caption,
            **kwargs,
        )
    else:
        sent = await message.answer(caption, **kwargs)

    if message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(sent, 30))

    return sent


async def send_main_menu(message: Message, caption: str = ""):
    keyboard = main_keyboard()

    if START_PHOTO.exists():
        return await message.answer_photo(
            BufferedInputFile(
                START_PHOTO.read_bytes(),
                filename=START_PHOTO.name,
            ),
            caption=caption or "Добро пожаловать в TOKENS | PRIVATE CLUB!",
            reply_markup=keyboard,
        )

    return await message.answer(
        caption or "Добро пожаловать в TOKENS | PRIVATE CLUB!",
        reply_markup=keyboard,
    )


def load_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "arial.ttf",
    ]

    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fit_cover(image: Image.Image, width: int, height: int):
    image = image.convert("RGB")
    ratio = max(width / image.width, height / image.height)

    new_size = (
        int(image.width * ratio),
        int(image.height * ratio),
    )

    image = image.resize(new_size, Image.Resampling.LANCZOS)

    left = (image.width - width) // 2
    top = (image.height - height) // 2

    return image.crop((left, top, left + width, top + height))


async def get_avatar(bot: Bot, user_id: int):
    try:
        photos = await bot.get_user_profile_photos(
            user_id=user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]
        file_info = await bot.get_file(photo.file_id)

        buffer = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buffer)
        buffer.seek(0)

        return Image.open(buffer).convert("RGBA")

    except Exception:
        logger.exception("Не удалось получить аватар пользователя %s", user_id)
        return None


def generate_profile_image(
    background_path: Path,
    fallback_path: Path,
    avatar: Image.Image | None,
    name: str,
    user_id: int,
    balance: int,
):
    width, height = 1000, 600

    # Если есть profile_bg.jpg — это чистый фон.
    # Если его нет — profile.jpg считается готовым дизайном.
    if background_path.exists():
        background = Image.open(background_path).convert("RGB")
        canvas = fit_cover(background, width, height).convert("RGBA")

        if avatar is not None:
            avatar = avatar.convert("RGBA").resize(
                (230, 230),
                Image.Resampling.LANCZOS,
            )

            mask = Image.new("L", (230, 230), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 230, 230), fill=255)

            # Мягкое внешнее свечение.
            glow = Image.new("RGBA", (270, 270), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            glow_draw.ellipse(
                (10, 10, 260, 260),
                fill=(255, 190, 65, 100),
            )
            glow = glow.filter(ImageFilter.GaussianBlur(18))

            canvas.alpha_composite(glow, (55, 65))

            avatar_layer = Image.new("RGBA", (230, 230), (0, 0, 0, 0))
            avatar_layer.paste(avatar, (0, 0), mask)

            canvas.alpha_composite(avatar_layer, (75, 85))

            draw = ImageDraw.Draw(canvas)
            draw.ellipse(
                (75, 85, 305, 315),
                outline=(255, 205, 95, 255),
                width=9,
            )

    elif fallback_path.exists():
        # Это уже готовая карточка профиля.
        # Аватар поверх неё не накладываем, чтобы не получить
        # двойную рамку и наложение фотографии на фотографию.
        background = Image.open(fallback_path).convert("RGB")
        canvas = fit_cover(background, width, height).convert("RGBA")

    else:
        canvas = Image.new(
            "RGBA",
            (width, height),
            (24, 27, 38, 255),
        )

    draw = ImageDraw.Draw(canvas)

    title_font = load_font(44)
    text_font = load_font(31)

    text_x = 350 if background_path.exists() else 70
    text_y = 175 if background_path.exists() else 170

    draw.text(
        (text_x, text_y),
        name[:24],
        font=title_font,
        fill=(255, 220, 150),
        stroke_width=2,
        stroke_fill=(20, 20, 20),
    )

    draw.text(
        (text_x, text_y + 75),
        f"ID: {user_id}",
        font=text_font,
        fill=(255, 255, 255),
        stroke_width=1,
        stroke_fill=(20, 20, 20),
    )

    draw.text(
        (text_x, text_y + 130),
        f"TOKENS: {balance:,}".replace(",", " "),
        font=text_font,
        fill=(255, 215, 105),
        stroke_width=1,
        stroke_fill=(20, 20, 20),
    )

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="JPEG", quality=92)
    output.seek(0)

    return output.getvalue()


# ============================================================
# CAPTCHA
# ============================================================

def generate_captcha():
    answer = random.randint(1000, 9999)

    width, height = 420, 180
    image = Image.new("RGB", (width, height), (25, 29, 42))
    draw = ImageDraw.Draw(image)

    for _ in range(35):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)

        draw.line(
            (x1, y1, x2, y2),
            fill=(
                random.randint(50, 120),
                random.randint(50, 120),
                random.randint(50, 120),
            ),
            width=2,
        )

    font = load_font(70)
    text = str(answer)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    draw.text(
        (
            (width - text_width) // 2,
            (height - text_height) // 2 - 8,
        ),
        text,
        font=font,
        fill=(255, 220, 130),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return answer, buffer.getvalue()


async def send_captcha(message: Message, state: FSMContext):
    answer, image_bytes = generate_captcha()

    await state.set_state(Captcha.waiting)
    await state.update_data(captcha_answer=str(answer))

    await message.answer_photo(
        BufferedInputFile(image_bytes, filename="captcha.png"),
        caption="🔐 Подтвердите, что вы не бот.\nВведите цифры с картинки.",
    )


# ============================================================
# VERIFICATION MIDDLEWARE
# ============================================================

class VerificationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            user = event.from_user
            state = data.get("state")

            if user is None:
                return await handler(event, data)

            await db.ensure_user(
                user.id,
                user.username or "",
                user.full_name or "",
            )

            # /start всегда пропускаем: он показывает CAPTCHA
            # или главное меню, если пользователь уже проверен.
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            user_data = await db.get_user(user.id)

            if user_data and user_data["is_verified"]:
                return await handler(event, data)

            if state and await state.get_state() == Captcha.waiting.state:
                return await handler(event, data)

            if state:
                await send_captcha(event, state)

            return None

        if isinstance(event, CallbackQuery):
            user = event.from_user
            state = data.get("state")

            await db.ensure_user(
                user.id,
                user.username or "",
                user.full_name or "",
            )

            user_data = await db.get_user(user.id)

            if user_data and user_data["is_verified"]:
                return await handler(event, data)

            await event.answer(
                "Сначала пройдите проверку через /start.",
                show_alert=True,
            )
            return None

        return await handler(event, data)


# ============================================================
# BOT SETUP
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

router.message.middleware(VerificationMiddleware())
router.callback_query.middleware(VerificationMiddleware())

dp.include_router(router)


# ============================================================
# START / CAPTCHA HANDLERS
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = message.from_user

    await db.ensure_user(
        user.id,
        user.username or "",
        user.full_name or "",
    )

    user_data = await db.get_user(user.id)

    if user_data and user_data["is_verified"]:
        await state.clear()
        await send_main_menu(
            message,
            "👑 Добро пожаловать в TOKENS | PRIVATE CLUB!",
        )
        return

    await send_captcha(message, state)


@router.message(Captcha.waiting)
async def captcha_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    expected = str(data.get("captcha_answer", ""))

    if not message.text or message.text.strip() != expected:
        await temp_answer(
            message,
            "❌ Неверный ответ. Попробуйте ещё раз.",
        )
        await send_captcha(message, state)
        return

    await db.set_verified(message.from_user.id)
    await state.clear()

    await message.answer("✅ Проверка пройдена!")
    await send_main_menu(
        message,
        "Добро пожаловать в TOKENS | PRIVATE CLUB!",
    )


# ============================================================
# PROFILE
# ============================================================

@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):
    user = message.from_user
    user_data = await db.get_user(user.id)

    if not user_data:
        await temp_answer(message, "Не удалось загрузить профиль.")
        return

    avatar = await get_avatar(bot, user.id)

    image_bytes = await asyncio.to_thread(
        generate_profile_image,
        PROFILE_BG,
        PROFILE_FALLBACK,
        avatar,
        user.full_name or "Пользователь",
        user.id,
        user_data["balance"],
    )

    await message.answer_photo(
        BufferedInputFile(image_bytes, filename="profile.jpg"),
        caption="👤 Ваш профиль TOKENS | PRIVATE CLUB",
    )


# ============================================================
# ACTIVITIES
# ============================================================

@router.message(F.text == "🎮 Активности")
async def activities_handler(message: Message):
    await temp_answer(
        message,
        (
            "🎮 **АКТИВНОСТИ**\n\n"
            "Выберите игру.\n"
            f"За участие начисляется фиксированная награда: "
            f"+{ACTIVITY_REWARD} TOKENS.\n"
            f"Повторная награда за ту же игру доступна через "
            f"{ACTIVITY_COOLDOWN} секунд.\n\n"
            "Участие бесплатное: баланс не списывается."
        ),
        reply_markup=activities_keyboard(),
        parse_mode="Markdown",
    )


GAME_CONFIG = {
    "dice": ("🎲", "Кости"),
    "darts": ("🎯", "Дартс"),
    "basketball": ("🏀", "Баскетбол"),
    "football": ("⚽", "Футбол"),
    "bowling": ("🎳", "Боулинг"),
}


@router.callback_query(F.data.startswith("game:"))
async def game_handler(callback: CallbackQuery):
    game_key = callback.data.split(":", 1)[1]

    if game_key not in GAME_CONFIG:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return

    emoji, title = GAME_CONFIG[game_key]
    user_id = callback.from_user.id

    allowed, value = await db.claim_activity(user_id, game_key)

    if not allowed:
        await callback.answer(
            f"Подождите ещё {value} сек. перед следующей наградой.",
            show_alert=True,
        )
        return

    await callback.answer()

    dice_message = await callback.message.answer_dice(emoji=emoji)

    result_message = await callback.message.answer(
        f"🎮 {title}\n"
        f"Участие засчитано!\n"
        f"Начислено: +{ACTIVITY_REWARD} TOKENS.\n"
        "За участие TOKENS не списываются."
    )

    if callback.message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(dice_message, 15))
        asyncio.create_task(auto_delete(result_message, 15))


# ============================================================
# DAILY BONUS
# ============================================================

@router.message(F.text == "🎁 Бонус")
async def bonus_handler(message: Message):
    success, value = await db.claim_bonus(message.from_user.id)

    if success:
        await temp_photo(
            message,
            BONUS_PHOTO,
            f"🎁 Ежедневный бонус получен!\n\n+{BONUS_AMOUNT} TOKENS",
        )
    else:
        hours = value // 3600
        minutes = (value % 3600) // 60

        await temp_answer(
            message,
            "⏳ Вы уже забирали ежедневный бонус.\n"
            f"Следующий будет доступен через {hours} ч. {minutes} мин.",
        )


# ============================================================
# SHOP — INFORMATION ONLY
# ============================================================

@router.message(F.text == "💎 Магазин")
async def shop_handler(message: Message):
    await temp_answer(
        message,
        (
            "💎 **МАГАЗИН TOKENS**\n\n"
            "Пополнение баланса временно недоступно.\n\n"
            "Покупка TOKENS за реальные деньги и Telegram Stars "
            "не поддерживается.\n\n"
            "Получайте TOKENS за бесплатные активности "
            "и ежедневный бонус."
        ),
        parse_mode="Markdown",
    )


# ============================================================
# PARTNERS
# ============================================================

@router.message(F.text == "🤝 Партнёры")
async def partners_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💱 Обмен",
                    url=EXCHANGE_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Игровой чат",
                    url=GAME_CHAT_URL,
                ),
            ],
        ]
    )

    await temp_answer(
        message,
        "🤝 **ПАРТНЁРЫ**\n\nНаши партнёрские площадки:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ============================================================
# TOURNAMENT
# ============================================================

@router.message(F.text == "🏆 Турнир")
async def tournament_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Новости турниров",
                    url=NEWS_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Игровой чат",
                    url=GAME_CHAT_URL,
                ),
            ],
        ]
    )

    await temp_photo(
        message,
        TOURNAMENT_PHOTO,
        (
            "🏆 **ТУРНИРЫ TOKENS**\n\n"
            "Следите за новостями, расписанием и объявлениями "
            "в официальном канале турниров."
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ============================================================
# TOP
# ============================================================

@router.message(F.text == "📊 Топ")
async def top_handler(message: Message):
    rows = await db.get_top(10)

    if not rows:
        await temp_answer(message, "Пока рейтинг пуст.")
        return

    lines = ["📊 **ТОП-10 УЧАСТНИКОВ**", ""]

    for index, row in enumerate(rows, start=1):
        user_id, username, full_name, balance = row

        display_name = (
            f"@{username}"
            if username
            else (full_name or f"Игрок {user_id}")
        )

        lines.append(
            f"{index}. {display_name} — **{balance:,} TOKENS**".replace(",", " ")
        )

    await temp_photo(
        message,
        TOP_PHOTO,
        "\n".join(lines),
        parse_mode="Markdown",
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
                    text="💬 Игровой чат",
                    url=GAME_CHAT_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📢 Новости и турниры",
                    url=NEWS_URL,
                ),
            ],
        ]
    )

    await temp_photo(
        message,
        CHATS_PHOTO,
        "💬 **ЧАТЫ TOKENS | PRIVATE CLUB**",
        reply_markup=keyboard,
        parse_mode="Markdown",
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
                    text="🆘 Написать в поддержку",
                    url=SUPPORT_URL,
                ),
            ],
        ]
    )

    await temp_photo(
        message,
        SUPPORT_PHOTO,
        "🆘 **ПОДДЕРЖКА**\n\nНажмите кнопку ниже, чтобы связаться с поддержкой.",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ============================================================
# HOW TO PLAY COMMAND
# ============================================================

@router.message(Command("help"))
async def help_handler(message: Message):
    await temp_photo(
        message,
        HOW_TO_PLAY_PHOTO,
        (
            "📖 **КАК ИГРАТЬ**\n\n"
            "1. Пройдите проверку через /start.\n"
            "2. Откройте «🎮 Активности».\n"
            "3. Выберите игру.\n"
            f"4. Получите фиксированную награду +{ACTIVITY_REWARD} TOKENS.\n"
            "5. Забирайте ежедневный бонус.\n\n"
            "Участие бесплатное. Ставок и списаний TOKENS нет."
        ),
        parse_mode="Markdown",
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

@router.message(Command("addtokens"))
async def admin_add_tokens(message: Message):
    if message.from_user.id != ADMIN_ID:
        await temp_answer(message, "⛔ Нет доступа.")
        return

    parts = (message.text or "").split()

    if len(parts) != 3:
        await temp_answer(
            message,
            "Использование: /addtokens USER_ID AMOUNT",
        )
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await temp_answer(message, "ID и сумма должны быть числами.")
        return

    if amount <= 0:
        await temp_answer(message, "Можно начислить только положительное число.")
        return

    target = await db.get_user(target_id)

    if target is None:
        await temp_answer(message, "Пользователь не найден в базе.")
        return

    success = await db.change_balance(target_id, amount)

    if success:
        await temp_answer(
            message,
            f"✅ Начислено {amount} TOKENS пользователю {target_id}.",
        )
    else:
        await temp_answer(message, "Не удалось изменить баланс.")


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
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()
    logger.info("Health server started on port %s", PORT)

    return runner


# ============================================================
# SCHEDULER
# ============================================================

scheduler = AsyncIOScheduler(timezone="UTC")


async def scheduled_status():
    logger.info("TOKENS PRIVATE CLUB is running.")


# ============================================================
# ERROR HANDLER
# ============================================================

@router.error()
async def error_handler(event: ErrorEvent):
    logger.exception(
        "Ошибка при обработке обновления",
        exc_info=event.exception,
    )

    if ADMIN_ID:
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                "⚠️ В боте произошла ошибка. Подробности записаны в лог.",
            )

    return True


# ============================================================
# MAIN
# ============================================================

async def main():
    await db.init()

    health_runner = await start_health_server()

    scheduler.add_job(
        scheduled_status,
        trigger="interval",
        hours=6,
        id="scheduled_status",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("TOKENS PRIVATE CLUB started.")

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)

        await health_runner.cleanup()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
