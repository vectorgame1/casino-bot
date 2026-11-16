import os
from dotenv import load_dotenv
load_dotenv()
import io
import random
import string
import asyncio
import logging
import time
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    BufferedInputFile,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from dotenv import load_dotenv

# ============================================================
# 1. CONFIGURATION
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
DB_PATH = os.getenv("DB_PATH", "tokens.db")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

CAPTCHA_BAN_HOURS = 12
CAPTCHA_MAX_ATTEMPTS = 3
CAPTCHA_REWARD = 5000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

dp.include_router(router)

# ============================================================
# 2. GLOBAL STATE
# ============================================================

captcha_sessions = {}
captcha_bans = {}

# ============================================================
# 3. DATABASE INITIALIZATION
# ============================================================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0,
                balance_tnc REAL DEFAULT 0,
                referral_id INTEGER DEFAULT NULL,
                referrals INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT,
                bet INTEGER DEFAULT 0,
                win INTEGER DEFAULT 0,
                result TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT DEFAULT 'TOKENS',
                transaction_type TEXT,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS bonus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER DEFAULT 0,
                claimed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'TNC',
                payment_id TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS roulette_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bet_amount INTEGER NOT NULL,
                bet_type TEXT NOT NULL,
                bet_value TEXT,
                result TEXT,
                win_amount INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS roulette_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER NOT NULL,
                color TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()

    logger.info("Database initialized successfully")


# ============================================================
# 4. DATABASE HELPERS
# ============================================================

async def db_execute(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.lastrowid


async def db_fetchone(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchone()


async def db_fetchall(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()


# ============================================================
# 5. CAPTCHA IMAGE GENERATOR
# ============================================================

def generate_captcha_image(code: str) -> bytes:
    """
    Generates a 300x100 CAPTCHA image:
    - Four digits
    - Random background noise
    - Distortion lines
    - Slight blur
    """

    width = 300
    height = 100

    image = Image.new(
        "RGB",
        (width, height),
        (245, 245, 245)
    )

    draw = ImageDraw.Draw(image)

    # Background noise
    for _ in range(350):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)

        color = (
            random.randint(150, 220),
            random.randint(150, 220),
            random.randint(150, 220),
        )

        draw.point((x, y), fill=color)

    # Font
    try:
        font = ImageFont.truetype("arial.ttf", 55)
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                55
            )
        except OSError:
            font = ImageFont.load_default()

    # Draw digits
    for index, digit in enumerate(code):
        x = 38 + index * 58
        y = random.randint(12, 30)

        digit_image = Image.new(
            "RGBA",
            (65, 75),
            (255, 255, 255, 0)
        )

        digit_draw = ImageDraw.Draw(digit_image)

        digit_draw.text(
            (5, 0),
            digit,
            font=font,
            fill=(
                random.randint(0, 80),
                random.randint(0, 80),
                random.randint(0, 80),
            )
        )

        angle = random.randint(-20, 20)

        digit_image = digit_image.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False
        )

        image.paste(
            digit_image,
            (x, y),
            digit_image
        )

    # Distortion lines
    for _ in range(12):
        start = (
            random.randint(0, width),
            random.randint(0, height)
        )

        end = (
            random.randint(0, width),
            random.randint(0, height)
        )

        draw.line(
            [start, end],
            fill=(
                random.randint(50, 180),
                random.randint(50, 180),
                random.randint(50, 180),
            ),
            width=random.randint(1, 2)
        )

    image = image.filter(
        ImageFilter.SMOOTH
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# 6. CAPTCHA MANAGEMENT
# ============================================================

def generate_captcha_code():
    return "".join(
        random.choices(string.digits, k=4)
    )


async def is_captcha_banned(user_id: int) -> bool:
    """
    Checks whether a user is temporarily banned
    from CAPTCHA verification.
    """

    ban_until = captcha_bans.get(user_id)

    if not ban_until:
        return False

    if time.time() >= ban_until:
        captcha_bans.pop(user_id, None)
        return False

    return True


async def send_captcha(message: Message, user_id: int):
    """
    Creates a new CAPTCHA and replaces the previous one.
    """

    session = captcha_sessions.get(user_id)

    if session and session.get("message_id"):
        try:
            await bot.delete_message(
                chat_id=user_id,
                message_id=session["message_id"]
            )
        except TelegramBadRequest:
            pass

    code = generate_captcha_code()

    image_bytes = generate_captcha_image(code)

    photo = BufferedInputFile(
        image_bytes,
        filename="captcha.png"
    )

    sent_message = await message.answer_photo(
        photo=photo,
        caption=(
            "🔐 <b>Проверка безопасности TOKENS</b>\n\n"
            "Введи 4 цифры с картинки.\n"
            "У тебя есть 3 попытки.\n\n"
            "🎁 За успешную проверку ты получишь "
            f"<b>{CAPTCHA_REWARD:,} TOKENS</b>."
        ),
        parse_mode="HTML"
    )

    captcha_sessions[user_id] = {
        "code": code,
        "attempts": 0,
        "message_id": sent_message.message_id,
        "verified": False,
    }


async def captcha_failed(message: Message, user_id: int):
    """
    Handles incorrect CAPTCHA attempts.
    """

    session = captcha_sessions.get(user_id)

    if not session:
        return

    session["attempts"] += 1

    attempts = session["attempts"]

    # Three incorrect attempts
    if attempts >= CAPTCHA_MAX_ATTEMPTS:

        captcha_bans[user_id] = (
            time.time() + CAPTCHA_BAN_HOURS * 3600
        )

        captcha_sessions.pop(user_id, None)

        # Generate failure image with red cross
        image = Image.new(
            "RGB",
            (300, 100),
            (245, 245, 245)
        )

        draw = ImageDraw.Draw(image)

        for _ in range(200):
            x = random.randint(0, 299)
            y = random.randint(0, 99)

            draw.point(
                (x, y),
                fill=(210, 210, 210)
            )

        draw.line(
            (115, 15, 185, 85),
            fill=(220, 0, 0),
            width=14
        )

        draw.line(
            (185, 15, 115, 85),
            fill=(220, 0, 0),
            width=14
        )

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)

        photo = BufferedInputFile(
            output.getvalue(),
            filename="captcha_failed.png"
        )

        await message.answer_photo(
            photo=photo,
            caption=(
                "❌ <b>Проверка не пройдена!</b>\n\n"
                "Ты использовал все 3 попытки.\n"
                f"⛔ Доступ заблокирован на {CAPTCHA_BAN_HOURS} часов."
            ),
            parse_mode="HTML"
        )

        return

    # Delete previous CAPTCHA and generate another
    await message.answer(
        f"❌ Неверный код!\n"
        f"Осталось попыток: "
        f"{CAPTCHA_MAX_ATTEMPTS - attempts}"
    )

    await send_captcha(message, user_id)


async def captcha_success(message: Message, user_id: int):
    """
    Successfully verifies the CAPTCHA and rewards the user.
    """

    session = captcha_sessions.pop(user_id, None)

    if not session:
        return

    # Delete CAPTCHA image
    try:
        await bot.delete_message(
            chat_id=user_id,
            message_id=session["message_id"]
        )
    except TelegramBadRequest:
        pass

    # Delete user's CAPTCHA answer
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Register user if necessary
    await db_execute(
        """
        INSERT OR IGNORE INTO users (
            user_id,
            username,
            first_name,
            balance
        )
        VALUES (?, ?, ?, 0)
        """,
        (
            user_id,
            message.from_user.username,
            message.from_user.first_name,
        )
    )

    # Prevent duplicate CAPTCHA rewards
    await db_execute(
        """
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
        """,
        (CAPTCHA_REWARD, user_id)
    )

    await db_execute(
        """
        INSERT INTO transactions (
            user_id,
            amount,
            currency,
            transaction_type,
            description
        )
        VALUES (?, ?, 'TOKENS', 'bonus', 'CAPTCHA verification reward')
        """,
        (user_id, CAPTCHA_REWARD)
    )

    await message.answer(
        "✅ <b>Проверка успешно пройдена!</b>\n\n"
        "🎁 Тебе начислено:\n"
        f"<b>+{CAPTCHA_REWARD:,} TOKENS</b>\n\n"
        "Добро пожаловать в TOKENS! 🚀",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# 7. MAIN REPLY MENU
# ============================================================

def main_menu():
    """
    Main TOKENS reply keyboard.
    Web App button occupies the full first row.
    """

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🚀 Открыть TOKENS App",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ],
            [
                KeyboardButton(text="🎮 Как играть?"),
                KeyboardButton(text="💎 Крипта"),
            ],
            [
                KeyboardButton(text="🎁 Бонус"),
                KeyboardButton(text="👤 Профиль"),
            ],
            [
                KeyboardButton(text="🏆 Топ"),
                KeyboardButton(text="🔗 Рефералка"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )

    return keyboard


# ============================================================
# 8. USER REGISTRATION
# ============================================================

async def register_user(message: Message):
    """
    Creates a user record if one does not already exist.
    """

    user = message.from_user

    await db_execute(
        """
        INSERT OR IGNORE INTO users (
            user_id,
            username,
            first_name,
            balance,
            balance_tnc
        )
        VALUES (?, ?, ?, 0, 0)
        """,
        (
            user.id,
            user.username,
            user.first_name,
        )
    )


# ============================================================
# 9. CAPTCHA CHECK HANDLER
# ============================================================

@router.message(
    F.text,
    lambda message: message.from_user.id in captcha_sessions
)
async def captcha_handler(message: Message):
    """
    Processes CAPTCHA answers.
    """

    user_id = message.from_user.id

    session = captcha_sessions.get(user_id)

    if not session:
        return

    if await is_captcha_banned(user_id):
        remaining = int(
            captcha_bans[user_id] - time.time()
        )

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await message.answer(
            "⛔ Ты временно заблокирован.\n"
            f"Осталось: {hours} ч. {minutes} мин."
        )
        return

    answer = message.text.strip()

    if answer == session["code"]:
        await captcha_success(message, user_id)
    else:
        await captcha_failed(message, user_id)


# ============================================================
# END OF PART 1
# ============================================================

# ============================================================
# TOKENS — PART 2
# API, MINI APP, GAMES, ROULETTE
# Продолжение файла bot.py
# ============================================================

import json
import hmac
import hashlib
import secrets
import re
import aiohttp
import aiohttp.web
from urllib.parse import parse_qsl
from pathlib import Path

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.enums import ChatType


# ============================================================
# 1. API CONFIGURATION
# ============================================================

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

# Количество TNC за один TOKENS
SWAP_RATE = float(os.getenv("SWAP_RATE", "0.001"))

# Максимальный возраст initData
INIT_DATA_MAX_AGE = 86400

# Ссылка на групповой чат
GROUP_CHAT_URL = os.getenv(
    "GROUP_CHAT_URL",
    "https://t.me/your_group"
)

ROULETTE_GIF = Path("assets/roulette.gif")

# Состояние рулетки
roulette_games = {}


# ============================================================
# 2. TELEGRAM MINI APP AUTHENTICATION
# ============================================================

def validate_init_data(init_data: str):
    """
    Проверяет Telegram WebApp initData.
    Возвращает данные пользователя или None.
    """

    if not init_data or not BOT_TOKEN:
        return None

    try:
        parsed = dict(parse_qsl(
            init_data,
            keep_blank_values=True
        ))

        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        # Формируем data-check-string
        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(parsed.items())
        )

        # Получаем секретный ключ Telegram
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем ожидаемую подпись
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        # Проверяем время авторизации
        auth_date = int(parsed.get("auth_date", 0))

        if (
            auth_date <= 0
            or auth_date > time.time() + 60
            or time.time() - auth_date > INIT_DATA_MAX_AGE
        ):
            return None

        user_data = json.loads(parsed["user"])

        if not user_data.get("id"):
            return None

        return user_data

    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError
    ):
        return None


async def authenticate_api_request(request):
    """
    Получает initData из JSON или заголовка.
    """

    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        ""
    )

    if not init_data:
        try:
            body = await request.json()
            init_data = body.get("initData", "")
        except (ValueError, TypeError):
            return None

    return validate_init_data(init_data)


# ============================================================
# 3. API RESPONSE HELPERS
# ============================================================

def api_error(message, status=400):
    return aiohttp.web.json_response(
        {
            "success": False,
            "error": message
        },
        status=status
    )


async def get_user_balances(user_id):
    user = await db_fetchone(
        """
        SELECT balance, balance_tnc
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user:
        return None

    return {
        "balance": int(user[0] or 0),
        "balance_tnc": float(user[1] or 0)
    }


# ============================================================
# 4. API: GET /api/user
# ============================================================

async def api_user(request):
    """
    Возвращает информацию о пользователе Mini App.
    """

    user_data = await authenticate_api_request(request)

    if not user_data:
        return api_error(
            "Invalid Telegram authorization",
            401
        )

    user_id = int(user_data["id"])

    balances = await get_user_balances(user_id)

    if balances is None:
        return api_error(
            "User not registered",
            404
        )

    return aiohttp.web.json_response({
        "success": True,
        "user": {
            "id": user_id,
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name")
        },
        "balance": balances["balance"],
        "balance_tnc": balances["balance_tnc"]
    })


# ============================================================
# 5. API: POST /api/swap
# ============================================================

async def api_swap(request):
    """
    Обменивает TOKENS на TNC.

    amount_tokens — количество TOKENS.
    Курс задается переменной SWAP_RATE.
    """

    user_data = await authenticate_api_request(request)

    if not user_data:
        return api_error(
            "Invalid Telegram authorization",
            401
        )

    user_id = int(user_data["id"])

    try:
        body = await request.json()

        amount_tokens = int(body.get("amount_tokens", 0))

    except (ValueError, TypeError):
        return api_error("Invalid amount")

    if amount_tokens <= 0:
        return api_error("Amount must be positive")

    if amount_tokens > 1_000_000_000:
        return api_error("Amount is too large")

    amount_tnc = round(
        amount_tokens * SWAP_RATE,
        8
    )

    if amount_tnc <= 0:
        return api_error("Invalid swap result")

    try:
        async with aiosqlite.connect(DB_PATH) as db:

            await db.execute("BEGIN IMMEDIATE")

            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance - ?,
                    balance_tnc = balance_tnc + ?
                WHERE user_id = ?
                  AND balance >= ?
                """,
                (
                    amount_tokens,
                    amount_tnc,
                    user_id,
                    amount_tokens
                )
            )

            if cursor.rowcount == 0:
                await db.rollback()
                return api_error(
                    "Insufficient balance or user not found",
                    400
                )

            await db.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    amount,
                    currency,
                    transaction_type,
                    description
                )
                VALUES (?, ?, 'TOKENS', 'swap_out', ?)
                """,
                (
                    user_id,
                    -amount_tokens,
                    f"Swap to TNC at rate {SWAP_RATE}"
                )
            )

            await db.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    amount,
                    currency,
                    transaction_type,
                    description
                )
                VALUES (?, ?, 'TNC', 'swap_in', ?)
                """,
                (
                    user_id,
                    amount_tnc,
                    f"Swap from TOKENS at rate {SWAP_RATE}"
                )
            )

            await db.commit()

    except aiosqlite.Error:
        logger.exception("Swap database error")
        return api_error(
            "Internal database error",
            500
        )

    balances = await get_user_balances(user_id)

    return aiohttp.web.json_response({
        "success": True,
        "message": "Swap completed",
        "swapped": {
            "tokens": amount_tokens,
            "tnc": amount_tnc,
            "rate": SWAP_RATE
        },
        "balance": balances["balance"],
        "balance_tnc": balances["balance_tnc"]
    })


# ============================================================
# 6. API INITIALIZATION
# ============================================================

def create_api_app():
    app = aiohttp.web.Application(
        client_max_size=1024 * 1024
    )

    app.router.add_post(
        "/api/user",
        api_user
    )

    app.router.add_post(
        "/api/swap",
        api_swap
    )

    app.router.add_get(
        "/health",
        lambda request: aiohttp.web.json_response({
            "status": "ok",
            "service": "TOKENS API"
        })
    )

    return app


async def start_api_server():
    """
    Запускает HTTP API.
    Вызывать из основного startup приложения.
    """

    app = create_api_app()

    runner = aiohttp.web.AppRunner(app)

    await runner.setup()

    site = aiohttp.web.TCPSite(
        runner,
        API_HOST,
        API_PORT
    )

    await site.start()

    logger.info(
        "TOKENS API started on %s:%s",
        API_HOST,
        API_PORT
    )

    return runner


# ============================================================
# 7. GROUP-ONLY GAMES CONFIGURATION
# ============================================================

GROUP_GAMES = {
    "кости": "🎲",
    "дартс": "🎯",
    "баскет": "🏀",
    "футбол": "⚽",
    "боулинг": "🎳"
}

GAME_ALIASES = {
    "кости": "🎲",
    "кости 🎲": "🎲",
    "дартс": "🎯",
    "дартс 🎯": "🎯",
    "баскет": "🏀",
    "баскет 🏀": "🏀",
    "футбол": "⚽",
    "футбол ⚽": "⚽",
    "боулинг": "🎳",
    "боулинг 🎳": "🎳"
}


# ============================================================
# 8. PRIVATE CHAT GAME ERROR
# ============================================================

async def send_group_only_error(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Перейти в игровой чат",
                    url=GROUP_CHAT_URL
                )
            ]
        ]
    )

    await message.answer(
        "⛔ <b>Игры доступны только в группах!</b>\n\n"
        "Чтобы играть в TOKENS, перейди в наш игровой чат.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# 9. GAME HANDLER
# ============================================================

@router.message(
    F.text.lower().in_([
        "кости", "кости 🎲",
        "дартс", "дартс 🎯",
        "баскет", "баскет 🏀",
        "футбол", "футбол ⚽",
        "боулинг", "боулинг 🎳"
    ])
)
async def games_handler(message: Message):

    game_text = message.text.lower().strip()

    emoji = GAME_ALIASES.get(game_text)

    if not emoji:
        return

    # Запрещаем игры в личных сообщениях
    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await send_group_only_error(message)
        return

    user_id = message.from_user.id

    await register_user(message)

    # Отправляем игровой бросок Telegram
    result_message = await message.answer_dice(
        emoji=emoji
    )

    # Ждем завершения анимации
    await asyncio.sleep(4)

    result = result_message.dice.value

    game_name = {
        "🎲": "dice",
        "🎯": "darts",
        "🏀": "basketball",
        "⚽": "football",
        "🎳": "bowling"
    }[emoji]

    await db_execute(
        """
        INSERT INTO game_log (
            user_id,
            game,
            bet,
            win,
            result
        )
        VALUES (?, ?, 0, 0, ?)
        """,
        (
            user_id,
            game_name,
            str(result)
        )
    )

    await message.answer(
        f"🎮 <b>{game_name.upper()}</b>\n\n"
        f"👤 Игрок: {message.from_user.full_name}\n"
        f"🎯 Результат: <b>{result}</b>",
        parse_mode="HTML"
    )


# ============================================================
# 10. ROULETTE CONFIGURATION
# ============================================================

ROULETTE_RED = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36
}

ROULETTE_BLACK = {
    2, 4, 6, 8, 10,
    11, 13, 15, 17,
    20, 22, 24, 26, 28,
    29, 31, 33, 35
}


def roulette_color(number):
    if number == 0:
        return "green"

    if number in ROULETTE_RED:
        return "red"

    return "black"


def roulette_color_ru(color):
    return {
        "red": "🔴 Красное",
        "black": "⚫ Черное",
        "green": "🟢 Зеленое"
    }.get(color, color)


# ============================================================
# 11. ROULETTE BET PARSER
# ============================================================

def parse_roulette_bet(text):
    """
    Поддерживаемые форматы:

    к 1000       — красное
    ч 1000       — черное
    з 1000       — зеленое
    17 500       — конкретное число
    10-20 500    — диапазон чисел

    Никакого eval().
    """

    text = text.lower().strip()

    # Красное, черное, зеленое
    color_match = re.fullmatch(
        r"(к|красное|ч|черное|чёрное|з|зеленое|зелёное)\s+(\d+)",
        text
    )

    if color_match:

        color_alias = color_match.group(1)

        amount = int(color_match.group(2))

        color = {
            "к": "red",
            "красное": "red",
            "ч": "black",
            "черное": "black",
            "чёрное": "black",
            "з": "green",
            "зеленое": "green",
            "зелёное": "green"
        }[color_alias]

        if amount <= 0:
            return None

        return {
            "type": "color",
            "value": color,
            "amount": amount
        }

    # Диапазон чисел
    range_match = re.fullmatch(
        r"(\d{1,2})\s*-\s*(\d{1,2})\s+(\d+)",
        text
    )

    if range_match:

        start = int(range_match.group(1))
        end = int(range_match.group(2))
        amount = int(range_match.group(3))

        if (
            start < 0
            or end > 36
            or start >= end
            or amount <= 0
        ):
            return None

        return {
            "type": "range",
            "value": [start, end],
            "amount": amount
        }

    # Конкретное число
    number_match = re.fullmatch(
        r"(\d{1,2})\s+(\d+)",
        text
    )

    if number_match:

        number = int(number_match.group(1))
        amount = int(number_match.group(2))

        if number < 0 or number > 36 or amount <= 0:
            return None

        return {
            "type": "number",
            "value": number,
            "amount": amount
        }

    return None


# ============================================================
# 12. ROULETTE JSON STORAGE
# ============================================================

async def save_roulette_state(chat_id, state):
    """
    Сохраняет ставки в таблице settings в JSON.
    """

    json_data = json.dumps(
        state,
        ensure_ascii=False
    )

    await db_execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (
            f"roulette_{chat_id}",
            json_data
        )
    )


async def load_roulette_state(chat_id):
    row = await db_fetchone(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (f"roulette_{chat_id}",)
    )

    if not row:
        return None

    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        logger.exception(
            "Invalid roulette JSON for chat %s",
            chat_id
        )
        return None


async def delete_roulette_state(chat_id):
    await db_execute(
        """
        DELETE FROM settings
        WHERE key = ?
        """,
        (f"roulette_{chat_id}",)
    )


# ============================================================
# 13. ROULETTE KEYBOARDS
# ============================================================

def roulette_result_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Повторить",
                    callback_data="roulette_repeat"
                ),
                InlineKeyboardButton(
                    text="⏫ Удвоить",
                    callback_data="roulette_double"
                )
            ]
        ]
    )


# ============================================================
# 14. ADD ROULETTE BET
# ============================================================

async def add_roulette_bet(message: Message, bet):
    """
    Добавляет ставку в JSON.
    TOKENS списываются сразу.
    """

    user_id = message.from_user.id
    chat_id = message.chat.id

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await send_group_only_error(message)
        return

    if bet["amount"] > 1_000_000_000:
        await message.reply("❌ Слишком большая ставка.")
        return

    if not roulette_games.get(chat_id):

        state = await load_roulette_state(chat_id)

        if state and state.get("status") == "open":
            roulette_games[chat_id] = state
        else:
            roulette_games[chat_id] = {
                "status": "open",
                "bets": [],
                "last_bets": {}
            }

    state = roulette_games[chat_id]

    if state["status"] != "open":
        await message.reply(
            "⛔ Прием ставок закрыт."
        )
        return

    await register_user(message)

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
              AND balance >= ?
            """,
            (
                bet["amount"],
                user_id,
                bet["amount"]
            )
        )

        if cursor.rowcount == 0:
            await db.rollback()

            await message.reply(
                "❌ Недостаточно TOKENS для ставки."
            )
            return

        await db.commit()

    bet_data = {
        "user_id": user_id,
        "username": message.from_user.full_name,
        "type": bet["type"],
        "value": bet["value"],
        "amount": bet["amount"]
    }

    state["bets"].append(bet_data)

    await save_roulette_state(
        chat_id,
        state
    )

    await message.reply(
        "🎰 <b>Ставка принята!</b>\n\n"
        f"👤 Игрок: {message.from_user.full_name}\n"
        f"💰 Ставка: <b>{bet['amount']:,} TOKENS</b>\n"
        f"🎯 Тип: <code>{bet['type']}</code>\n"
        f"🎲 Значение: <code>{bet['value']}</code>",
        parse_mode="HTML"
    )


# ============================================================
# 15. ROULETTE BET MESSAGE HANDLER
# ============================================================

@router.message(
    F.text.regexp(
        r"^(к|красное|ч|черное|чёрное|з|зеленое|зелёное|\d{1,2})(\s+|\s*-\s*)"
    )
)
async def roulette_bet_handler(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await send_group_only_error(message)
        return

    bet = parse_roulette_bet(
        message.text
    )

    if not bet:
        await message.reply(
            "❌ Неверный формат ставки.\n\n"
            "Примеры:\n"
            "<code>к 1000</code> — красное\n"
            "<code>ч 1000</code> — черное\n"
            "<code>з 1000</code> — зеленое\n"
            "<code>17 500</code> — число\n"
            "<code>10-20 500</code> — диапазон",
            parse_mode="HTML"
        )
        return

    await add_roulette_bet(
        message,
        bet
    )


# ============================================================
# 16. ROULETTE PAYOUT CALCULATION
# ============================================================

def calculate_roulette_win(bet, number, color):
    """
    Возвращает полный выигрыш с учетом первоначальной ставки.

    Красное/черное: 2x
    Зеленое: 36x
    Число: 36x
    Диапазон: 36 / количество чисел
    """

    bet_type = bet["type"]
    bet_value = bet["value"]
    amount = bet["amount"]

    if bet_type == "color":

        if bet_value == color and color != "green":
            return amount * 2

        if bet_value == "green" and number == 0:
            return amount * 36

        return 0

    if bet_type == "number":

        if number == bet_value:
            return amount * 36

        return 0

    if bet_type == "range":

        start, end = bet_value

        if start <= number <= end:

            count = end - start + 1

            return int(
                amount * 36 / count
            )

        return 0

    return 0


# ============================================================
# 17. ROULETTE SPIN
# ============================================================

async def spin_roulette(message: Message):
    """
    Запускает раунд рулетки.
    """

    chat_id = message.chat.id

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await send_group_only_error(message)
        return

    state = roulette_games.get(chat_id)

    if not state:
        state = await load_roulette_state(chat_id)

    if not state or not state.get("bets"):
        await message.reply(
            "🎰 Нет ставок для запуска рулетки."
        )
        return

    if state.get("status") != "open":
        await message.reply(
            "⏳ Рулетка уже запущена."
        )
        return

    # Закрываем прием ставок
    state["status"] = "spinning"

    roulette_games[chat_id] = state

    await save_roulette_state(
        chat_id,
        state
    )

    # Анимация
    if ROULETTE_GIF.exists():

        await message.answer_animation(
            FSInputFile(ROULETTE_GIF)
        )

    else:

        await message.answer(
            "🎰 <b>Рулетка запускается...</b>",
            parse_mode="HTML"
        )

    await asyncio.sleep(3)

    # Европейская рулетка: 0-36
    number = secrets.randbelow(37)

    color = roulette_color(number)

    total_bets = 0
    total_wins = 0

    results = []

    # Начисление выигрышей
    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        try:

            for bet in state["bets"]:

                user_id = bet["user_id"]

                amount = bet["amount"]

                win = calculate_roulette_win(
                    bet,
                    number,
                    color
                )

                total_bets += amount
                total_wins += win

                if win > 0:

                    await db.execute(
                        """
                        UPDATE users
                        SET balance = balance + ?
                        WHERE user_id = ?
                        """,
                        (win, user_id)
                    )

                    await db.execute(
                        """
                        INSERT INTO transactions (
                            user_id,
                            amount,
                            currency,
                            transaction_type,
                            description
                        )
                        VALUES (?, ?, 'TOKENS', 'roulette_win', ?)
                        """,
                        (
                            user_id,
                            win,
                            f"Roulette win: {number} {color}"
                        )
                    )

                await db.execute(
                    """
                    INSERT INTO roulette_bets (
                        user_id,
                        bet_amount,
                        bet_type,
                        bet_value,
                        result,
                        win_amount
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        amount,
                        bet["type"],
                        json.dumps(
                            bet["value"],
                            ensure_ascii=False
                        ),
                        f"{number}:{color}",
                        win
                    )
                )

                results.append({
                    "username": bet["username"],
                    "amount": amount,
                    "win": win
                })

            await db.execute(
                """
                INSERT INTO roulette_history (
                    number,
                    color
                )
                VALUES (?, ?)
                """,
                (number, color)
            )

            await db.commit()

        except Exception:

            await db.rollback()

            logger.exception(
                "Roulette settlement failed"
            )

            await message.answer(
                "❌ Ошибка обработки раунда. "
                "Обратись к администратору."
            )

            return

    # Запоминаем последние ставки игроков
    last_bets = {}

    for bet in state["bets"]:

        last_bets[str(bet["user_id"])] = bet

    result_text = (
        "🎰 <b>РУЛЕТКА — РЕЗУЛЬТАТ</b>\n\n"
        f"🎯 Выпало: <b>{number}</b>\n"
        f"🎨 Цвет: {roulette_color_ru(color)}\n\n"
        "━━━━━━━━━━━━━━\n"
    )

    for result in results:

        if result["win"] > 0:

            result_text += (
                f"🏆 <b>{result['username']}</b>\n"
                f"💰 Ставка: {result['amount']:,}\n"
                f"🎁 Выигрыш: +{result['win']:,} TOKENS\n\n"
            )

        else:

            result_text += (
                f"❌ <b>{result['username']}</b>\n"
                f"💸 Проигрыш: -{result['amount']:,} TOKENS\n\n"
            )

    result_text += (
        "━━━━━━━━━━━━━━\n"
        f"💰 Всего поставлено: {total_bets:,}\n"
        f"🏆 Всего выплачено: {total_wins:,} TOKENS"
    )

    await message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=roulette_result_keyboard()
    )

    # Сохраняем историю для кнопок повтора
    roulette_games[chat_id] = {
        "status": "finished",
        "bets": [],
        "last_bets": last_bets
    }

    await save_roulette_state(
        chat_id,
        roulette_games[chat_id]
    )


# ============================================================
# 18. ROULETTE START COMMAND
# ============================================================

@router.message(
    F.text.lower().in_([
        "старт",
        "🎰 старт",
        "/roulette",
        "/roulette@"
    ])
)
async def roulette_start_handler(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await send_group_only_error(message)
        return

    await spin_roulette(message)


# ============================================================
# 19. REPEAT LAST ROULETTE BETS
# ============================================================

@router.callback_query(
    F.data == "roulette_repeat"
)
async def roulette_repeat_handler(
    callback: CallbackQuery
):

    chat_id = callback.message.chat.id

    if callback.message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await callback.answer(
            "Игры доступны только в группах!",
            show_alert=True
        )
        return

    state = roulette_games.get(chat_id)

    if not state:
        state = await load_roulette_state(chat_id)

    if not state:
        await callback.answer(
            "История ставок не найдена.",
            show_alert=True
        )
        return

    user_id = callback.from_user.id

    last_bets = state.get(
        "last_bets",
        {}
    )

    previous_bet = last_bets.get(
        str(user_id)
    )

    if not previous_bet:
        await callback.answer(
            "У тебя нет предыдущей ставки.",
            show_alert=True
        )
        return

    new_bet = {
        "type": previous_bet["type"],
        "value": previous_bet["value"],
        "amount": previous_bet["amount"]
    }

    await callback.answer(
        "Повторяем ставку!"
    )

    fake_message = callback.message

    # Ставка принимается в текущем или новом раунде
    if roulette_games.get(chat_id, {}).get("status") != "open":

        roulette_games[chat_id] = {
            "status": "open",
            "bets": [],
            "last_bets": last_bets
        }

    await add_roulette_bet_from_callback(
        callback,
        new_bet
    )


# ============================================================
# 20. DOUBLE LAST ROULETTE BET
# ============================================================

@router.callback_query(
    F.data == "roulette_double"
)
async def roulette_double_handler(
    callback: CallbackQuery
):

    chat_id = callback.message.chat.id

    if callback.message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await callback.answer(
            "Игры доступны только в группах!",
            show_alert=True
        )
        return

    state = roulette_games.get(chat_id)

    if not state:
        state = await load_roulette_state(chat_id)

    if not state:
        await callback.answer(
            "История ставок не найдена.",
            show_alert=True
        )
        return

    user_id = callback.from_user.id

    last_bets = state.get(
        "last_bets",
        {}
    )

    previous_bet = last_bets.get(
        str(user_id)
    )

    if not previous_bet:
        await callback.answer(
            "У тебя нет предыдущей ставки.",
            show_alert=True
        )
        return

    new_amount = int(
        previous_bet["amount"]
    ) * 2

    if new_amount > 1_000_000_000:
        await callback.answer(
            "Ставка слишком большая.",
            show_alert=True
        )
        return

    new_bet = {
        "type": previous_bet["type"],
        "value": previous_bet["value"],
        "amount": new_amount
    }

    await callback.answer(
        "Удваиваем ставку!"
    )

    if roulette_games.get(chat_id, {}).get("status") != "open":

        roulette_games[chat_id] = {
            "status": "open",
            "bets": [],
            "last_bets": last_bets
        }

    await add_roulette_bet_from_callback(
        callback,
        new_bet
    )


# ============================================================
# 21. ADD BET FROM CALLBACK
# ============================================================

async def add_roulette_bet_from_callback(
    callback: CallbackQuery,
    bet
):
    """
    Безопасное добавление ставки через inline-кнопки.
    """

    user_id = callback.from_user.id

    chat_id = callback.message.chat.id

    state = roulette_games.get(chat_id)

    if not state or state.get("status") != "open":

        state = {
            "status": "open",
            "bets": [],
            "last_bets": state.get("last_bets", {})
            if state else {}
        }

        roulette_games[chat_id] = state

    amount = int(bet["amount"])

    if amount <= 0:
        return

    await db_execute(
        """
        INSERT OR IGNORE INTO users (
            user_id,
            username,
            first_name
        )
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            callback.from_user.username,
            callback.from_user.first_name
        )
    )

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
              AND balance >= ?
            """,
            (amount, user_id, amount)
        )

        if cursor.rowcount == 0:

            await db.rollback()

            await callback.message.answer(
                "❌ Недостаточно TOKENS для ставки."
            )

            return

        await db.commit()

    state["bets"].append({
        "user_id": user_id,
        "username": callback.from_user.full_name,
        "type": bet["type"],
        "value": bet["value"],
        "amount": amount
    })

    await save_roulette_state(
        chat_id,
        state
    )

    await callback.message.answer(
        "🎰 <b>Ставка принята!</b>\n\n"
        f"👤 {callback.from_user.full_name}\n"
        f"💰 {amount:,} TOKENS\n"
        f"🎯 {bet['type']}: {bet['value']}",
        parse_mode="HTML"
    )


# ============================================================
# END OF PART 2
# ============================================================

# ============================================================
# TOKENS — PART 3 (FINAL)
# PROFILE, CRYPTO, ADMIN PANEL, MAIN
# Продолжение bot.py
# ============================================================

import html
from PIL import Image, ImageDraw, ImageFont, ImageOps
from aiogram.types import InputMediaPhoto


# ============================================================
# 1. PROFILE CONFIGURATION
# ============================================================

BOT_NAME = os.getenv("BOT_NAME", "TOKENS")
VIP_PRICE = int(os.getenv("VIP_PRICE", "100000"))
TNC_RATE = float(os.getenv("SWAP_RATE", "0.001"))

PROFILE_WIDTH = 800
PROFILE_HEIGHT = 400


def get_profile_font(size=30, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf"
    ]

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    return ImageFont.load_default()


# ============================================================
# 2. PROFILE IMAGE GENERATOR
# ============================================================

async def generate_profile_image(user):
    """
    Создает изображение профиля:
    - Темный фон
    - Круглая аватарка
    - Имя пользователя
    - Название TOKENS
    """

    image = Image.new(
        "RGB",
        (PROFILE_WIDTH, PROFILE_HEIGHT),
        (15, 20, 35)
    )

    draw = ImageDraw.Draw(image)

    # Background decoration
    draw.rounded_rectangle(
        (15, 15, 785, 385),
        radius=30,
        fill=(24, 32, 55),
        outline=(70, 120, 220),
        width=3
    )

    draw.ellipse(
        (550, -150, 900, 200),
        fill=(35, 65, 115)
    )

    draw.ellipse(
        (-150, 280, 200, 630),
        fill=(30, 55, 95)
    )

    # Avatar
    avatar = None

    try:
        photos = await bot.get_user_profile_photos(
            user_id=user.id,
            limit=1
        )

        if photos.total_count > 0:
            photo = photos.photos[0][-1]

            file = await bot.get_file(photo.file_id)

            avatar_bytes = io.BytesIO()

            await bot.download_file(
                file.file_path,
                destination=avatar_bytes
            )

            avatar_bytes.seek(0)

            avatar = Image.open(
                avatar_bytes
            ).convert("RGBA")

    except Exception:
        logger.exception("Could not download user avatar")

    avatar_size = 190

    if avatar:
        avatar = ImageOps.fit(
            avatar,
            (avatar_size, avatar_size)
        )
    else:
        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (55, 90, 150, 255)
        )

        avatar_draw = ImageDraw.Draw(avatar)

        avatar_draw.text(
            (avatar_size // 2, avatar_size // 2),
            user.first_name[:1].upper(),
            font=get_profile_font(85, True),
            fill="white",
            anchor="mm"
        )

    # Circular mask
    mask = Image.new(
        "L",
        (avatar_size, avatar_size),
        0
    )

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.ellipse(
        (0, 0, avatar_size, avatar_size),
        fill=255
    )

    avatar.putalpha(mask)

    # Avatar border
    draw.ellipse(
        (65, 100, 265, 300),
        outline=(75, 160, 255),
        width=6
    )

    image.paste(
        avatar,
        (70, 105),
        avatar
    )

    # User information
    draw.text(
        (310, 115),
        BOT_NAME,
        font=get_profile_font(48, True),
        fill=(90, 180, 255)
    )

    draw.text(
        (310, 185),
        user.first_name[:30],
        font=get_profile_font(32, True),
        fill=(255, 255, 255)
    )

    username = (
        f"@{user.username}"
        if user.username
        else "Без username"
    )

    draw.text(
        (310, 240),
        username[:35],
        font=get_profile_font(23),
        fill=(170, 185, 210)
    )

    draw.text(
        (310, 310),
        "YOUR DIGITAL WORLD",
        font=get_profile_font(17),
        fill=(100, 130, 175)
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# 3. PROFILE KEYBOARD
# ============================================================

def profile_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="profile_settings"
                ),
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="buy_vip"
                )
            ]
        ]
    )


# ============================================================
# 4. PROFILE HANDLER
# ============================================================

@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):

    user = message.from_user

    await register_user(message)

    balances = await get_user_balances(user.id)

    if not balances:
        await message.answer(
            "❌ Не удалось загрузить профиль."
        )
        return

    image_bytes = await generate_profile_image(user)

    photo = BufferedInputFile(
        image_bytes,
        filename="profile.png"
    )

    caption = (
        f"👤 <b>ПРОФИЛЬ {BOT_NAME}</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Имя: {html.escape(user.full_name)}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪙 TOKENS: <b>{balances['balance']:,}</b>\n"
        f"💎 TNC: <b>{balances['balance_tnc']:.8f}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери действие:"
    )

    await message.answer_photo(
        photo=photo,
        caption=caption,
        parse_mode="HTML",
        reply_markup=profile_keyboard()
    )


# ============================================================
# 5. PROFILE SETTINGS
# ============================================================

@router.callback_query(
    F.data == "profile_settings"
)
async def profile_settings_handler(callback: CallbackQuery):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔔 Уведомления",
                    callback_data="settings_notifications"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="profile_back"
                )
            ]
        ]
    )

    await callback.message.edit_caption(
        caption=(
            "⚙️ <b>Настройки TOKENS</b>\n\n"
            "Управление настройками аккаунта."
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


@router.callback_query(
    F.data == "settings_notifications"
)
async def settings_notifications_handler(callback: CallbackQuery):

    await callback.answer(
        "Настройки уведомлений появятся в следующем обновлении.",
        show_alert=True
    )


@router.callback_query(
    F.data == "profile_back"
)
async def profile_back_handler(callback: CallbackQuery):

    await callback.message.delete()

    await callback.answer()


# ============================================================
# 6. VIP PURCHASE
# ============================================================

@router.callback_query(
    F.data == "buy_vip"
)
async def buy_vip_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    balances = await get_user_balances(user_id)

    if not balances:
        await callback.answer(
            "Пользователь не найден.",
            show_alert=True
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="confirm_vip"
                )
            ]
        ]
    )

    await callback.message.answer(
        "⭐ <b>TOKENS VIP</b>\n\n"
        f"Стоимость: <b>{VIP_PRICE:,} TOKENS</b>\n\n"
        "VIP открывает дополнительные возможности проекта.\n\n"
        "Подтвердить покупку?",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    await callback.answer()


@router.callback_query(
    F.data == "confirm_vip"
)
async def confirm_vip_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
              AND balance >= ?
            """,
            (
                VIP_PRICE,
                user_id,
                VIP_PRICE
            )
        )

        if cursor.rowcount == 0:

            await db.rollback()

            await callback.answer(
                "Недостаточно TOKENS!",
                show_alert=True
            )
            return

        await db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, '1')
            ON CONFLICT(key)
            DO UPDATE SET value = '1'
            """,
            (f"vip_{user_id}",)
        )

        await db.execute(
            """
            INSERT INTO transactions (
                user_id,
                amount,
                currency,
                transaction_type,
                description
            )
            VALUES (?, ?, 'TOKENS', 'vip_purchase', 'VIP purchase')
            """,
            (user_id, -VIP_PRICE)
        )

        await db.commit()

    await callback.message.answer(
        "⭐ <b>Поздравляем!</b>\n\n"
        "VIP успешно приобретен!",
        parse_mode="HTML"
    )

    await callback.answer(
        "VIP активирован!"
    )


# ============================================================
# 7. CRYPTO IMAGE GENERATOR
# ============================================================

def generate_crypto_image():
    """
    Генерирует картинку с актуальным внутренним курсом TNC.
    """

    image = Image.new(
        "RGB",
        (800, 400),
        (12, 20, 40)
    )

    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (20, 20, 780, 380),
        radius=35,
        fill=(25, 40, 75),
        outline=(65, 140, 230),
        width=4
    )

    draw.text(
        (65, 65),
        "TOKENS CRYPTO",
        font=get_profile_font(35, True),
        fill=(100, 180, 255)
    )

    draw.text(
        (65, 145),
        "TNC",
        font=get_profile_font(75, True),
        fill=(255, 255, 255)
    )

    draw.text(
        (65, 245),
        f"1 TOKENS = {TNC_RATE:.8f} TNC",
        font=get_profile_font(27, True),
        fill=(80, 230, 170)
    )

    draw.text(
        (65, 315),
        "DIGITAL ASSET EXCHANGE",
        font=get_profile_font(17),
        fill=(150, 175, 205)
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# 8. CRYPTO HANDLER
# ============================================================

@router.message(F.text == "💎 Крипта")
async def crypto_handler(message: Message):

    image_bytes = generate_crypto_image()

    photo = BufferedInputFile(
        image_bytes,
        filename="crypto.png"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть App",
                    web_app=WebAppInfo(
                        url=WEBAPP_URL
                    )
                )
            ]
        ]
    )

    await message.answer_photo(
        photo=photo,
        caption=(
            "💎 <b>TOKENS CRYPTO</b>\n\n"
            f"Курс обмена:\n"
            f"1 TOKENS = <b>{TNC_RATE:.8f} TNC</b>\n\n"
            "Обмен доступен в TOKENS App.\n\n"
            "🚀 Нажми кнопку ниже."
        ),
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# 9. ADMIN CONFIGURATION
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def admin_required(message: Message):
    if not is_admin(message.from_user.id):

        await message.answer(
            "⛔ У тебя нет доступа к админ-панели."
        )

        return False

    return True


def admin_help_text():
    return (
        "🛠 <b>TOKENS ADMIN PANEL</b>\n\n"
        "<code>@помощь</code> — список команд\n"
        "<code>@скан</code> — список пользователей\n"
        "<code>@выдать ID СУММА</code> — выдать TOKENS\n"
        "<code>@дроп СУММА</code> — раздать всем\n"
        "<code>@бан ID</code> — заблокировать пользователя\n"
        "<code>@стата</code> — статистика проекта\n"
        "<code>@рассылка ТЕКСТ</code> — рассылка\n"
        "<code>@сет_курс ЧИСЛО</code> — установить курс\n"
        "<code>@дождь СУММА</code> — случайный дроп\n"
    )


# ============================================================
# 10. ADMIN: HELP
# ============================================================

@router.message(F.text.startswith("@помощь"))
async def admin_help_handler(message: Message):

    if not await admin_required(message):
        return

    await message.answer(
        admin_help_text(),
        parse_mode="HTML"
    )


# ============================================================
# 11. ADMIN: SCAN USERS
# ============================================================

@router.message(F.text.startswith("@скан"))
async def admin_scan_handler(message: Message):

    if not await admin_required(message):
        return

    users = await db_fetchall(
        """
        SELECT user_id, username, balance, balance_tnc
        FROM users
        ORDER BY balance DESC
        LIMIT 50
        """
    )

    if not users:
        await message.answer(
            "Пользователей пока нет."
        )
        return

    text = "🔎 <b>СКАНИРОВАНИЕ БАЗЫ</b>\n\n"

    for user in users:

        user_id, username, balance, tnc = user

        username = username or "Без username"

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"👤 {html.escape(username)}\n"
            f"🪙 {balance:,} TOKENS\n"
            f"💎 {tnc:.8f} TNC\n\n"
        )

    for index in range(0, len(text), 4000):

        await message.answer(
            text[index:index + 4000],
            parse_mode="HTML"
        )


# ============================================================
# 12. ADMIN: GIVE TOKENS
# ============================================================

@router.message(F.text.startswith("@выдать"))
async def admin_give_handler(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Формат:\n<code>@выдать USER_ID СУММА</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])
        amount = int(parts[2])

    except ValueError:

        await message.answer(
            "❌ ID и сумма должны быть числами."
        )
        return

    if amount <= 0 or amount > 1_000_000_000:

        await message.answer(
            "❌ Недопустимая сумма."
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (amount, user_id)
        )

        if cursor.rowcount == 0:

            await db.rollback()

            await message.answer(
                "❌ Пользователь не найден."
            )
            return

        await db.execute(
            """
            INSERT INTO transactions (
                user_id,
                amount,
                currency,
                transaction_type,
                description
            )
            VALUES (?, ?, 'TOKENS', 'admin_gift', ?)
            """,
            (
                user_id,
                amount,
                f"Admin gift by {message.from_user.id}"
            )
        )

        await db.commit()

    await message.answer(
        "✅ <b>Начисление выполнено!</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Сумма: <b>+{amount:,} TOKENS</b>",
        parse_mode="HTML"
    )


# ============================================================
# 13. ADMIN: DROP TO EVERYONE
# ============================================================

@router.message(F.text.startswith("@дроп"))
async def admin_drop_handler(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Формат: <code>@дроп СУММА</code>",
            parse_mode="HTML"
        )
        return

    try:
        amount = int(parts[1])

    except ValueError:
        await message.answer("❌ Неверная сумма.")
        return

    if amount <= 0 or amount > 1_000_000:

        await message.answer(
            "❌ Сумма должна быть от 1 до 1 000 000."
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        await db.execute(
            """
            UPDATE users
            SET balance = balance + ?
            """,
            (amount,)
        )

        await db.execute(
            """
            INSERT INTO transactions (
                user_id,
                amount,
                currency,
                transaction_type,
                description
            )
            SELECT user_id, ?, 'TOKENS', 'admin_drop', 'Global drop'
            FROM users
            """,
            (amount,)
        )

        cursor = await db.execute(
            "SELECT COUNT(*) FROM users"
        )

        count = (await cursor.fetchone())[0]

        await db.commit()

    await message.answer(
        "🎁 <b>ГЛОБАЛЬНЫЙ ДРОП!</b>\n\n"
        f"👥 Получателей: {count}\n"
        f"💰 Каждый получил: +{amount:,} TOKENS",
        parse_mode="HTML"
    )


# ============================================================
# 14. ADMIN: BAN USER
# ============================================================

@router.message(F.text.startswith("@бан"))
async def admin_ban_handler(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Формат: <code>@бан USER_ID</code>",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(parts[1])

    except ValueError:
        await message.answer("❌ Неверный ID.")
        return

    if user_id in ADMIN_IDS:

        await message.answer(
            "⛔ Нельзя заблокировать администратора."
        )
        return

    await db_execute(
        """
        UPDATE users
        SET is_banned = 1
        WHERE user_id = ?
        """,
        (user_id,)
    )

    await message.answer(
        f"⛔ Пользователь <code>{user_id}</code> заблокирован.",
        parse_mode="HTML"
    )


# ============================================================
# 15. ADMIN: STATISTICS
# ============================================================

@router.message(F.text.startswith("@стата"))
async def admin_stats_handler(message: Message):

    if not await admin_required(message):
        return

    users_count = await db_fetchone(
        "SELECT COUNT(*) FROM users"
    )

    total_tokens = await db_fetchone(
        "SELECT COALESCE(SUM(balance), 0) FROM users"
    )

    total_tnc = await db_fetchone(
        "SELECT COALESCE(SUM(balance_tnc), 0) FROM users"
    )

    games_count = await db_fetchone(
        "SELECT COUNT(*) FROM game_log"
    )

    payments_count = await db_fetchone(
        "SELECT COUNT(*) FROM payments"
    )

    banned_count = await db_fetchone(
        "SELECT COUNT(*) FROM users WHERE is_banned = 1"
    )

    text = (
        "📊 <b>TOKENS STATISTICS</b>\n\n"
        f"👥 Пользователей: <b>{users_count[0]:,}</b>\n"
        f"⛔ Заблокировано: <b>{banned_count[0]:,}</b>\n"
        f"🪙 Всего TOKENS: <b>{total_tokens[0]:,}</b>\n"
        f"💎 Всего TNC: <b>{total_tnc[0]:.8f}</b>\n"
        f"🎮 Игр сыграно: <b>{games_count[0]:,}</b>\n"
        f"💳 Платежей: <b>{payments_count[0]:,}</b>\n"
    )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# 16. ADMIN: BROADCAST
# ============================================================

@router.message(F.text.startswith("@рассылка"))
async def admin_broadcast_handler(message: Message):

    if not await admin_required(message):
        return

    broadcast_text = message.text[
        len("@рассылка"):
    ].strip()

    if not broadcast_text:

        await message.answer(
            "Формат:\n<code>@рассылка Текст сообщения</code>",
            parse_mode="HTML"
        )
        return

    users = await db_fetchall(
        """
        SELECT user_id
        FROM users
        WHERE is_banned = 0
        """
    )

    success = 0
    failed = 0

    status = await message.answer(
        "📢 Начинаю рассылку..."
    )

    for (user_id,) in users:

        try:

            await bot.send_message(
                chat_id=user_id,
                text=broadcast_text
            )

            success += 1

        except (TelegramForbiddenError, TelegramBadRequest):

            failed += 1

        except Exception:

            failed += 1

            logger.exception(
                "Broadcast error for user %s",
                user_id
            )

        await asyncio.sleep(0.05)

    await status.edit_text(
        "📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Доставлено: {success}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML"
    )


# ============================================================
# 17. ADMIN: SET TNC RATE
# ============================================================

@router.message(F.text.startswith("@сет_курс"))
async def admin_set_rate_handler(message: Message):

    global SWAP_RATE, TNC_RATE

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Формат:\n<code>@сет_курс 0.001</code>",
            parse_mode="HTML"
        )
        return

    try:
        new_rate = float(parts[1])

    except ValueError:
        await message.answer("❌ Неверный курс.")
        return

    if not 0 < new_rate <= 1_000_000:

        await message.answer(
            "❌ Курс должен быть положительным."
        )
        return

    SWAP_RATE = new_rate
    TNC_RATE = new_rate

    await db_execute(
        """
        INSERT INTO settings (key, value)
        VALUES ('swap_rate', ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (str(new_rate),)
    )

    await message.answer(
        "✅ <b>Курс обновлен!</b>\n\n"
        f"1 TOKENS = {new_rate:.8f} TNC",
        parse_mode="HTML"
    )


# ============================================================
# 18. ADMIN: RANDOM RAIN
# ============================================================

@router.message(F.text.startswith("@дождь"))
async def admin_rain_handler(message: Message):

    if not await admin_required(message):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Формат:\n<code>@дождь ОБЩИЙ_БЮДЖЕТ</code>",
            parse_mode="HTML"
        )
        return

    try:
        budget = int(parts[1])

    except ValueError:
        await message.answer("❌ Неверный бюджет.")
        return

    if budget <= 0 or budget > 1_000_000_000:

        await message.answer(
            "❌ Недопустимый бюджет."
        )
        return

    users = await db_fetchall(
        """
        SELECT user_id
        FROM users
        WHERE is_banned = 0
        """
    )

    if not users:

        await message.answer(
            "Нет пользователей для участия."
        )
        return

    if budget < len(users):

        await message.answer(
            "❌ Бюджет меньше количества участников."
        )
        return

    # Каждому гарантируется минимум 1 TOKENS.
    # Остаток распределяется случайным образом.
    shares = [1] * len(users)

    remaining = budget - len(users)

    for _ in range(remaining):
        shares[secrets.randbelow(len(users))] += 1

    async with aiosqlite.connect(DB_PATH) as db:

        await db.execute("BEGIN IMMEDIATE")

        try:

            for (user_id,), amount in zip(users, shares):

                await db.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (amount, user_id)
                )

                await db.execute(
                    """
                    INSERT INTO transactions (
                        user_id,
                        amount,
                        currency,
                        transaction_type,
                        description
                    )
                    VALUES (?, ?, 'TOKENS', 'admin_rain', 'Random rain')
                    """,
                    (user_id, amount)
                )

            await db.commit()

        except Exception:

            await db.rollback()

            logger.exception("Rain distribution failed")

            await message.answer(
                "❌ Ошибка распределения."
            )

            return

    await message.answer(
        "🌧 <b>TOKENS RAIN!</b>\n\n"
        f"👥 Участников: {len(users)}\n"
        f"💰 Общий бюджет: {budget:,} TOKENS\n\n"
        "🎁 TOKENS распределены случайным образом!",
        parse_mode="HTML"
    )


# ============================================================
# 19. MAIN APPLICATION
# ============================================================

async def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing! Check your .env file."
        )

    logger.info("Starting TOKENS bot...")

    # Initialize database
    await init_db()

    # Restore saved exchange rate
    saved_rate = await db_fetchone(
        """
        SELECT value
        FROM settings
        WHERE key = 'swap_rate'
        """
    )

    global SWAP_RATE, TNC_RATE

    if saved_rate:

        try:

            SWAP_RATE = float(saved_rate[0])
            TNC_RATE = SWAP_RATE

        except (ValueError, TypeError):

            logger.warning(
                "Invalid saved exchange rate. Using default."
            )

    # Start API server
    api_runner = await start_api_server()

    logger.info("TOKENS API is running.")

    try:

        # Start Telegram bot
        logger.info("Starting Telegram polling...")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:

        logger.info("Stopping TOKENS services...")

        # Stop API server
        await api_runner.cleanup()

        # Close Telegram bot session
        await bot.session.close()

        logger.info("TOKENS stopped successfully.")


# ============================================================
# 20. START BOT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())