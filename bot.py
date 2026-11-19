import os
import random
import string
import asyncio
import logging
import io
import time
import secrets
import hashlib
import aiohttp
import aiosqlite

from datetime import datetime, timedelta
from typing import Optional, Any

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    WebAppInfo,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

PORT = int(os.getenv("PORT", "10000"))

DATABASE_PATH = os.getenv("DATABASE_PATH", "tokens.db")

BOT_NAME = os.getenv("BOT_NAME", "TOKENS")

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")

PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY", "")

CRYPTO_API_URL = os.getenv(
    "CRYPTO_API_URL",
    "https://api.example.com"
)

MIN_WITHDRAWAL = int(os.getenv("MIN_WITHDRAWAL", "100"))

REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "10"))

START_BONUS = int(os.getenv("START_BONUS", "0"))

DAILY_BONUS = int(os.getenv("DAILY_BONUS", "5"))

CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").lower() == "true"

CAPTCHA_LENGTH = 4

CAPTCHA_WIDTH = 300

CAPTCHA_HEIGHT = 100

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")


# ============================================================
# BOT INITIALIZATION
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Укажите BOT_TOKEN в переменных окружения."
    )

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

router = Router()

dp.include_router(router)


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

DATABASE_LOCK = asyncio.Lock()


async def init_db():
    """
    Создание и инициализация базы данных TOKENS.
    """

    async with aiosqlite.connect(DATABASE_PATH) as db:

        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,

                balance REAL DEFAULT 0,
                balance_tnc REAL DEFAULT 0,

                referral_id INTEGER DEFAULT NULL,
                referrals INTEGER DEFAULT 0,

                is_banned INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,

                captcha_passed INTEGER DEFAULT 0,
                captcha_code TEXT DEFAULT NULL,

                registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_activity TEXT DEFAULT CURRENT_TIMESTAMP,

                last_bonus TEXT DEFAULT NULL,

                total_earned REAL DEFAULT 0,
                total_spent REAL DEFAULT 0,

                games_played INTEGER DEFAULT 0,

                FOREIGN KEY (referral_id)
                    REFERENCES users(user_id)
            )
        """)

        # ----------------------------------------------------
        # GAME LOG
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                game_type TEXT NOT NULL,

                bet REAL DEFAULT 0,

                win REAL DEFAULT 0,

                result TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # ----------------------------------------------------
        # TRANSACTIONS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                amount REAL NOT NULL,

                currency TEXT DEFAULT 'TOKENS',

                transaction_type TEXT NOT NULL,

                status TEXT DEFAULT 'completed',

                description TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # ----------------------------------------------------
        # BONUS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS bonus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                amount REAL NOT NULL,

                bonus_type TEXT DEFAULT 'daily',

                claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # ----------------------------------------------------
        # PAYMENTS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                payment_id TEXT UNIQUE,

                amount REAL NOT NULL,

                currency TEXT DEFAULT 'RUB',

                payment_method TEXT,

                status TEXT DEFAULT 'pending',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                completed_at TEXT,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # ----------------------------------------------------
        # ROULETTE BETS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS roulette_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                bet_amount REAL NOT NULL,

                bet_type TEXT NOT NULL,

                bet_value TEXT,

                result_number INTEGER,

                result_color TEXT,

                win_amount REAL DEFAULT 0,

                status TEXT DEFAULT 'pending',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # ----------------------------------------------------
        # SETTINGS
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,

                value TEXT NOT NULL
            )
        """)

        # ----------------------------------------------------
        # ROULETTE HISTORY
        # ----------------------------------------------------

        await db.execute("""
            CREATE TABLE IF NOT EXISTS roulette_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                number INTEGER NOT NULL,

                color TEXT NOT NULL,

                total_bets REAL DEFAULT 0,

                total_wins REAL DEFAULT 0,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_referral
            ON users(referral_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_game_log_user
            ON game_log(user_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_user
            ON transactions(user_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_user
            ON payments(user_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_roulette_user
            ON roulette_bets(user_id)
        """)

        # ----------------------------------------------------
        # DEFAULT SETTINGS
        # ----------------------------------------------------

        default_settings = {
            "maintenance": "0",
            "registration_enabled": "1",
            "games_enabled": "1",
            "bonus_enabled": "1",
            "roulette_enabled": "1",
            "referral_reward": str(REFERRAL_REWARD),
            "daily_bonus": str(DAILY_BONUS),
            "min_withdrawal": str(MIN_WITHDRAWAL),
            "start_bonus": str(START_BONUS),
        }

        for key, value in default_settings.items():

            await db.execute(
                """
                INSERT OR IGNORE INTO settings (key, value)
                VALUES (?, ?)
                """,
                (key, value)
            )

        await db.commit()

    logger.info("База данных TOKENS успешно инициализирована.")


# ============================================================
# DATABASE EXECUTE
# ============================================================

async def db_execute(
    query: str,
    params: tuple = (),
    fetch: bool = False
):
    """
    Выполнение SQL-запросов.

    Поддерживает INSERT, UPDATE, DELETE и другие запросы.
    """

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute("PRAGMA foreign_keys=ON")

            cursor = await db.execute(query, params)

            if fetch:
                result = await cursor.fetchall()
            else:
                result = cursor.lastrowid

            await db.commit()

            await cursor.close()

            return result


# ============================================================
# DATABASE FETCHONE
# ============================================================

async def db_fetchone(
    query: str,
    params: tuple = ()
):
    """
    Получение одной записи из базы данных.
    """

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute("PRAGMA foreign_keys=ON")

            cursor = await db.execute(query, params)

            result = await cursor.fetchone()

            await cursor.close()

            return result


# ============================================================
# DATABASE FETCHALL
# ============================================================

async def db_fetchall(
    query: str,
    params: tuple = ()
):
    """
    Получение всех записей из базы данных.
    """

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute("PRAGMA foreign_keys=ON")

            cursor = await db.execute(query, params)

            result = await cursor.fetchall()

            await cursor.close()

            return result


# ============================================================
# USER REGISTRATION
# ============================================================

async def register_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    referral_id: Optional[int] = None
):
    """
    Регистрация нового пользователя.
    """

    existing_user = await db_fetchone(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    if existing_user:
        await db_execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (username, first_name, user_id)
        )

        return False

    if referral_id == user_id:
        referral_id = None

    if referral_id is not None:

        referrer = await db_fetchone(
            "SELECT user_id FROM users WHERE user_id = ?",
            (referral_id,)
        )

        if not referrer:
            referral_id = None

    await db_execute(
        """
        INSERT INTO users (
            user_id,
            username,
            first_name,
            balance,
            balance_tnc,
            referral_id,
            referrals,
            is_banned,
            is_vip
        )
        VALUES (?, ?, ?, ?, 0, ?, 0, 0, 0)
        """,
        (
            user_id,
            username,
            first_name,
            START_BONUS,
            referral_id
        )
    )

    if START_BONUS > 0:

        await db_execute(
            """
            INSERT INTO transactions (
                user_id,
                amount,
                currency,
                transaction_type,
                description
            )
            VALUES (?, ?, 'TOKENS', 'start_bonus', ?)
            """,
            (
                user_id,
                START_BONUS,
                "Стартовый бонус"
            )
        )

    if referral_id is not None:

        await db_execute(
            """
            UPDATE users
            SET referrals = referrals + 1,
                balance = balance + ?
            WHERE user_id = ?
            """,
            (REFERRAL_REWARD, referral_id)
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
            VALUES (?, ?, 'TOKENS', 'referral_reward', ?)
            """,
            (
                referral_id,
                REFERRAL_REWARD,
                f"Реферальное вознаграждение за пользователя {user_id}"
            )
        )

    logger.info("Зарегистрирован пользователь %s", user_id)

    return True


# ============================================================
# CAPTCHA IMAGE GENERATOR
# ============================================================

def generate_captcha_image(
    code: Optional[str] = None
):
    """
    Генерирует CAPTCHA 300x100.

    Особенности:
    - 4 случайные цифры;
    - случайные линии;
    - шум;
    - случайные точки;
    - небольшое вращение символов.

    Возвращает:
        tuple[bytes, str]
    """

    if code is None:
        code = "".join(
            random.choices(string.digits, k=CAPTCHA_LENGTH)
        )

    width = CAPTCHA_WIDTH
    height = CAPTCHA_HEIGHT

    image = Image.new(
        "RGB",
        (width, height),
        color=(245, 245, 245)
    )

    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # FONT
    # --------------------------------------------------------

    font = None

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arial.ttf",
    ]

    for font_path in font_paths:

        try:
            font = ImageFont.truetype(
                font_path,
                55
            )
            break

        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()

    # --------------------------------------------------------
    # BACKGROUND NOISE
    # --------------------------------------------------------

    for _ in range(500):

        x = random.randint(0, width - 1)

        y = random.randint(0, height - 1)

        color = (
            random.randint(180, 230),
            random.randint(180, 230),
            random.randint(180, 230)
        )

        draw.point(
            (x, y),
            fill=color
        )

    # --------------------------------------------------------
    # RANDOM LINES
    # --------------------------------------------------------

    for _ in range(12):

        x1 = random.randint(0, width)

        y1 = random.randint(0, height)

        x2 = random.randint(0, width)

        y2 = random.randint(0, height)

        color = (
            random.randint(100, 190),
            random.randint(100, 190),
            random.randint(100, 190)
        )

        draw.line(
            (x1, y1, x2, y2),
            fill=color,
            width=random.randint(1, 3)
        )

    # --------------------------------------------------------
    # CAPTCHA DIGITS
    # --------------------------------------------------------

    digit_width = width // CAPTCHA_LENGTH

    for index, digit in enumerate(code):

        digit_image = Image.new(
            "RGBA",
            (75, 80),
            (255, 255, 255, 0)
        )

        digit_draw = ImageDraw.Draw(digit_image)

        digit_color = (
            random.randint(0, 70),
            random.randint(0, 70),
            random.randint(0, 70),
            255
        )

        digit_draw.text(
            (15, 5),
            digit,
            font=font,
            fill=digit_color
        )

        angle = random.randint(-20, 20)

        digit_image = digit_image.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False
        )

        x = index * digit_width + 5

        y = random.randint(5, 15)

        image.paste(
            digit_image,
            (x, y),
            digit_image
        )

    # --------------------------------------------------------
    # EXTRA NOISE
    # --------------------------------------------------------

    for _ in range(100):

        x = random.randint(0, width - 1)

        y = random.randint(0, height - 1)

        color = (
            random.randint(0, 150),
            random.randint(0, 150),
            random.randint(0, 150)
        )

        draw.ellipse(
            (x, y, x + 2, y + 2),
            fill=color
        )

    image = image.filter(
        ImageFilter.SMOOTH
    )

    # --------------------------------------------------------
    # EXPORT
    # --------------------------------------------------------

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output.getvalue(), code


# ============================================================
# ERROR IMAGE GENERATOR
# ============================================================

def generate_error_image(
    text: str = "ERROR"
):
    """
    Создает изображение ошибки с красным крестиком.
    """

    width = 300
    height = 200

    image = Image.new(
        "RGB",
        (width, height),
        color=(255, 255, 255)
    )

    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # FONT
    # --------------------------------------------------------

    font = None

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arial.ttf",
    ]

    for font_path in font_paths:

        try:
            font = ImageFont.truetype(
                font_path,
                24
            )
            break

        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()

    # --------------------------------------------------------
    # RED CROSS CIRCLE
    # --------------------------------------------------------

    circle_box = (
        100,
        15,
        200,
        115
    )

    draw.ellipse(
        circle_box,
        outline=(220, 40, 40),
        width=7
    )

    # --------------------------------------------------------
    # RED CROSS
    # --------------------------------------------------------

    draw.line(
        (125, 40, 175, 90),
        fill=(220, 40, 40),
        width=9
    )

    draw.line(
        (175, 40, 125, 90),
        fill=(220, 40, 40),
        width=9
    )

    # --------------------------------------------------------
    # ERROR TEXT
    # --------------------------------------------------------

    text_width = draw.textbbox(
        (0, 0),
        text,
        font=font
    )[2]

    text_x = (width - text_width) // 2

    draw.text(
        (text_x, 145),
        text,
        fill=(180, 30, 30),
        font=font
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG"
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# MAIN REPLY KEYBOARD
# ============================================================

def get_main_keyboard():
    """
    Главное меню TOKENS.
    """

    keyboard = ReplyKeyboardBuilder()

    # --------------------------------------------------------
    # WEB APP BUTTON - FULL WIDTH
    # --------------------------------------------------------

    keyboard.row(
        KeyboardButton(
            text="🚀 Открыть TOKENS App",
            web_app=WebAppInfo(
                url=WEBAPP_URL
            )
        ),
        width=1
    )

    # --------------------------------------------------------
    # BONUS AND PROFILE
    # --------------------------------------------------------

    keyboard.row(
        KeyboardButton(
            text="🎁 Бонус"
        ),
        KeyboardButton(
            text="👤 Профиль"
        ),
        width=2
    )

    # --------------------------------------------------------
    # TOP AND REFERRAL
    # --------------------------------------------------------

    keyboard.row(
        KeyboardButton(
            text="🏆 Топ"
        ),
        KeyboardButton(
            text="🔗 Рефералка"
        ),
        width=2
    )

    # --------------------------------------------------------
    # CRYPTO
    # --------------------------------------------------------

    keyboard.row(
        KeyboardButton(
            text="💎 Крипта"
        ),
        width=1
    )

    return keyboard.as_markup(
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие"
    )


# ============================================================
# CAPTCHA KEYBOARD
# ============================================================

def get_captcha_keyboard():
    """
    Клавиатура для ввода CAPTCHA.
    """

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🔄 Обновить капчу"
                )
            ],
            [
                KeyboardButton(
                    text="❌ Отмена"
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


# ============================================================
# CAPTCHA GENERATION AND STORAGE
# ============================================================

async def create_user_captcha(user_id: int):
    """
    Создает CAPTCHA и сохраняет ее в базе данных.
    """

    image_bytes, captcha_code = generate_captcha_image()

    await db_execute(
        """
        UPDATE users
        SET captcha_code = ?,
            captcha_passed = 0
        WHERE user_id = ?
        """,
        (captcha_code, user_id)
    )

    return image_bytes, captcha_code


# ============================================================
# START COMMAND - CAPTCHA
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработчик /start.

    Регистрирует пользователя,
    проверяет бан,
    запускает CAPTCHA.
    """

    user = message.from_user

    if not user:
        return

    user_id = user.id

    # --------------------------------------------------------
    # REFERRAL PARAMETER
    # --------------------------------------------------------

    referral_id = None

    command_parts = (message.text or "").split(maxsplit=1)

    if len(command_parts) > 1:

        referral_parameter = command_parts[1].strip()

        if referral_parameter.isdigit():

            referral_id = int(referral_parameter)

            if referral_id == user_id:
                referral_id = None

    # --------------------------------------------------------
    # REGISTRATION
    # --------------------------------------------------------

    await register_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name,
        referral_id=referral_id
    )

    # --------------------------------------------------------
    # BAN CHECK
    # --------------------------------------------------------

    user_data = await db_fetchone(
        """
        SELECT
            is_banned,
            captcha_passed,
            captcha_code,
            is_vip
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user_data:
        return

    is_banned = user_data[0]
    captcha_passed = user_data[1]

    if is_banned:

        error_image = generate_error_image(
            "ACCESS DENIED"
        )

        await message.answer_photo(
            BufferedInputFile(
                error_image,
                filename="error.png"
            ),
            caption=(
                "🚫 <b>Ваш аккаунт заблокирован.</b>\n\n"
                "Обратитесь в поддержку для получения информации."
            )
        )

        return

    # --------------------------------------------------------
    # CAPTCHA DISABLED
    # --------------------------------------------------------

    if not CAPTCHA_ENABLED:

        await db_execute(
            """
            UPDATE users
            SET captcha_passed = 1,
                captcha_code = NULL
            WHERE user_id = ?
            """,
            (user_id,)
        )

        await message.answer(
            (
                f"👋 Добро пожаловать в <b>{BOT_NAME}</b>!\n\n"
                "🚀 Используйте меню для управления своим аккаунтом."
            ),
            reply_markup=get_main_keyboard()
        )

        return

    # --------------------------------------------------------
    # ALREADY PASSED CAPTCHA
    # --------------------------------------------------------

    if captcha_passed:

        await message.answer(
            (
                f"👋 С возвращением в <b>{BOT_NAME}</b>!\n\n"
                "Выберите нужный раздел в меню."
            ),
            reply_markup=get_main_keyboard()
        )

        return

    # --------------------------------------------------------
    # GENERATE CAPTCHA
    # --------------------------------------------------------

    image_bytes, captcha_code = await create_user_captcha(
        user_id
    )

    await message.answer(
        (
            "🛡 <b>Проверка безопасности TOKENS</b>\n\n"
            "Для продолжения необходимо пройти проверку.\n\n"
            "🔢 Введите 4 цифры, изображенные на картинке.\n\n"
            "После успешной проверки откроется главное меню."
        ),
        reply_markup=get_captcha_keyboard()
    )

    await message.answer_photo(
        BufferedInputFile(
            image_bytes,
            filename="captcha.png"
        ),
        caption="🔐 <b>Введите код с изображения:</b>"
    )


# ============================================================
# END OF PART 1
# ============================================================

# Продолжение bot.py будет добавляться следующими частями.

# ============================================================
# PART 2 - WEBAPP, API, GAMES AND ROULETTE
# ============================================================

import json
import hmac
import hashlib
import urllib.parse
import os
from aiohttp import web
from aiogram.types import (
    Dice,
    FSInputFile,
)


# ============================================================
# ADDITIONAL CONFIGURATION
# ============================================================

WEBAPP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "webapp"
)

ROULETTE_GIF = os.getenv(
    "ROULETTE_GIF",
    "roulette.gif"
)

TOKEN_TO_TNC_RATE = 50000

MESSAGE_DELETE_DELAY = 15

MAX_ROULETTE_RANGES = 100

MAX_ROULETTE_NUMBER = 36

ROULETTE_BETS_CACHE = {}

ROULETTE_MULTIPLIERS = {
    "number": 36,
    "range": 36,
    "red": 2,
    "black": 2,
    "even": 2,
    "odd": 2,
}


# ============================================================
# MESSAGE AUTO DELETE
# ============================================================

async def delete_message_later(
    message: Message,
    delay: int = MESSAGE_DELETE_DELAY
):
    """
    Автоматическое удаление сообщения через заданное время.
    """

    await asyncio.sleep(delay)

    try:
        await message.delete()

    except Exception as error:
        logger.debug(
            "Не удалось удалить сообщение: %s",
            error
        )


async def send_temporary_message(
    message: Message,
    text: str,
    delay: int = MESSAGE_DELETE_DELAY,
    reply_markup=None
):
    """
    Отправка временного сообщения.
    """

    sent = await message.answer(
        text,
        reply_markup=reply_markup
    )

    asyncio.create_task(
        delete_message_later(sent, delay)
    )

    return sent


# ============================================================
# GROUP CHECK
# ============================================================

async def check_game_chat(
    message: Message
) -> bool:
    """
    Игры доступны только в группах.
    """

    if message.chat.type not in ("group", "supergroup"):

        await message.answer(
            (
                "❌ <b>Игры доступны только в группах!</b>\n\n"
                "Добавьте бота в группу или присоединитесь "
                "к игровому сообществу.\n\n"
                "🎮 Игровой бот: @tokenplays"
            )
        )

        return False

    return True


# ============================================================
# USER CHECK FOR GAMES
# ============================================================

async def get_game_user(
    user_id: int
):
    """
    Получение пользователя для игровых операций.
    """

    return await db_fetchone(
        """
        SELECT
            user_id,
            balance,
            balance_tnc,
            is_banned,
            is_vip
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )


# ============================================================
# GAME BALANCE OPERATIONS
# ============================================================

async def charge_game_bet(
    user_id: int,
    amount: float
) -> bool:
    """
    Списание ставки с баланса TOKENS.

    Используется атомарное UPDATE.
    """

    if amount <= 0:
        return False

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance - ?,
                    total_spent = total_spent + ?
                WHERE user_id = ?
                  AND balance >= ?
                  AND is_banned = 0
                """,
                (
                    amount,
                    amount,
                    user_id,
                    amount
                )
            )

            success = cursor.rowcount > 0

            await db.commit()

            await cursor.close()

            return success


async def credit_game_win(
    user_id: int,
    amount: float
):
    """
    Начисление выигрыша.
    """

    if amount <= 0:
        return

    await db_execute(
        """
        UPDATE users
        SET balance = balance + ?,
            total_earned = total_earned + ?
        WHERE user_id = ?
        """,
        (
            amount,
            amount,
            user_id
        )
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
        VALUES (?, ?, 'TOKENS', 'game_win', ?)
        """,
        (
            user_id,
            amount,
            "Выигрыш в игре"
        )
    )


async def log_game(
    user_id: int,
    game_type: str,
    bet: float,
    win: float,
    result: str
):
    """
    Сохранение игрового результата.
    """

    await db_execute(
        """
        INSERT INTO game_log (
            user_id,
            game_type,
            bet,
            win,
            result
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            game_type,
            bet,
            win,
            result
        )
    )

    await db_execute(
        """
        UPDATE users
        SET games_played = games_played + 1
        WHERE user_id = ?
        """,
        (user_id,)
    )


# ============================================================
# TELEGRAM DICE GAME
# ============================================================

async def play_telegram_dice_game(
    message: Message,
    emoji: str,
    game_name: str,
    bet: float
):
    """
    Игры Telegram Dice.

    Кости, Дартс, Боулинг:
    выигрыш x2 при максимальном результате.
    """

    if not await check_game_chat(message):
        return

    user = message.from_user

    if not user:
        return

    if bet <= 0:
        await send_temporary_message(
            message,
            "❌ Ставка должна быть больше нуля."
        )
        return

    user_data = await get_game_user(user.id)

    if not user_data:
        await send_temporary_message(
            message,
            "❌ Сначала зарегистрируйтесь через /start."
        )
        return

    if user_data[3]:
        await send_temporary_message(
            message,
            "🚫 Ваш аккаунт заблокирован."
        )
        return

    if user_data[1] < bet:
        await send_temporary_message(
            message,
            "❌ Недостаточно TOKENS для ставки."
        )
        return

    charged = await charge_game_bet(
        user.id,
        bet
    )

    if not charged:
        await send_temporary_message(
            message,
            "❌ Не удалось списать ставку."
        )
        return

    try:

        dice_message = await message.answer_dice(
            emoji=emoji
        )

        # Ждем завершения анимации Telegram.
        await asyncio.sleep(4)

        result = dice_message.dice.value

        won = result == 6

        win_amount = bet * 2 if won else 0

        if won:
            await credit_game_win(
                user.id,
                win_amount
            )

        await log_game(
            user.id,
            game_name,
            bet,
            win_amount,
            f"Результат: {result}"
        )

        balance_data = await db_fetchone(
            "SELECT balance FROM users WHERE user_id = ?",
            (user.id,)
        )

        balance = balance_data[0] if balance_data else 0

        result_text = (
            f"🎮 <b>{game_name}</b>\n\n"
            f"👤 Игрок: {user.full_name}\n"
            f"🎯 Результат: {result}\n"
            f"💰 Ставка: {bet:g} TOKENS\n\n"
        )

        if won:
            result_text += (
                f"🎉 <b>ПОБЕДА!</b>\n"
                f"💎 Выигрыш: {win_amount:g} TOKENS\n"
            )
        else:
            result_text += (
                "😔 <b>Вы проиграли.</b>\n"
            )

        result_text += (
            f"\n💳 Баланс: {balance:g} TOKENS"
        )

        sent = await message.answer(
            result_text
        )

        asyncio.create_task(
            delete_message_later(sent)
        )

    except Exception:

        logger.exception(
            "Ошибка игры %s",
            game_name
        )

        # Возвращаем ставку, если игра не состоялась.
        await credit_game_win(
            user.id,
            bet
        )

        await send_temporary_message(
            message,
            "❌ Ошибка запуска игры. Ставка возвращена."
        )


# ============================================================
# GAME: DICE
# ============================================================

@dp.message(Command("dice"))
async def game_dice(message: Message):
    """
    Пример:
    /dice 100
    """

    try:
        bet = float(
            message.text.split(maxsplit=1)[1]
        )
    except (ValueError, IndexError):
        await send_temporary_message(
            message,
            "Использование: <code>/dice 100</code>"
        )
        return

    await play_telegram_dice_game(
        message,
        "🎲",
        "Кости",
        bet
    )


# ============================================================
# GAME: DARTS
# ============================================================

@dp.message(Command("dart"))
async def game_darts(message: Message):
    """
    Пример:
    /dart 100
    """

    try:
        bet = float(
            message.text.split(maxsplit=1)[1]
        )
    except (ValueError, IndexError):
        await send_temporary_message(
            message,
            "Использование: <code>/dart 100</code>"
        )
        return

    await play_telegram_dice_game(
        message,
        "🎯",
        "Дартс",
        bet
    )


# ============================================================
# GAME: BOWLING
# ============================================================

@dp.message(Command("bowling"))
async def game_bowling(message: Message):
    """
    Пример:
    /bowling 100
    """

    try:
        bet = float(
            message.text.split(maxsplit=1)[1]
        )
    except (ValueError, IndexError):
        await send_temporary_message(
            message,
            "Использование: <code>/bowling 100</code>"
        )
        return

    await play_telegram_dice_game(
        message,
        "🎳",
        "Боулинг",
        bet
    )


# ============================================================
# BASKETBALL AND FOOTBALL GAMES
# ============================================================

async def play_sport_game(
    message: Message,
    emoji: str,
    game_name: str,
    bet: float
):
    """
    Спортивные игры.

    Множители:
    результат 1-2: проигрыш;
    результат 3: x1;
    результат 4: x1.5;
    результат 5: x1.8;
    результат 6: x2.

    Для Telegram Basketball и Football реальные значения
    находятся в диапазоне 1-5, поэтому x2 определяется
    отдельным случайным бонусным исходом.
    """

    if not await check_game_chat(message):
        return

    user = message.from_user

    if not user:
        return

    if bet <= 0:
        await send_temporary_message(
            message,
            "❌ Неверная ставка."
        )
        return

    user_data = await get_game_user(user.id)

    if not user_data:
        await send_temporary_message(
            message,
            "❌ Используйте /start для регистрации."
        )
        return

    if user_data[3]:
        await send_temporary_message(
            message,
            "🚫 Ваш аккаунт заблокирован."
        )
        return

    if user_data[1] < bet:
        await send_temporary_message(
            message,
            "❌ Недостаточно TOKENS."
        )
        return

    charged = await charge_game_bet(
        user.id,
        bet
    )

    if not charged:
        await send_temporary_message(
            message,
            "❌ Не удалось списать ставку."
        )
        return

    try:

        dice_message = await message.answer_dice(
            emoji=emoji
        )

        await asyncio.sleep(4)

        result = dice_message.dice.value

        # Множители для спортивных игр.
        multipliers = {
            1: 0,
            2: 0,
            3: 1,
            4: 1.5,
            5: 1.8,
        }

        multiplier = multipliers.get(
            result,
            0
        )

        # Дополнительный случайный бонус x2.
        # Бонус не зависит от результата Telegram Dice.
        if multiplier > 0 and random.random() < 0.05:
            multiplier = 2

        win_amount = bet * multiplier

        if win_amount > 0:
            await credit_game_win(
                user.id,
                win_amount
            )

        await log_game(
            user.id,
            game_name,
            bet,
            win_amount,
            f"Результат: {result}, множитель: x{multiplier}"
        )

        balance_data = await db_fetchone(
            "SELECT balance FROM users WHERE user_id = ?",
            (user.id,)
        )

        balance = balance_data[0] if balance_data else 0

        if multiplier == 0:
            outcome = "😔 Вы проиграли."
        else:
            outcome = (
                f"🎉 Выигрыш x{multiplier:g}!"
            )

        result_text = (
            f"🏅 <b>{game_name}</b>\n\n"
            f"👤 Игрок: {user.full_name}\n"
            f"🎯 Результат: {result}\n"
            f"💰 Ставка: {bet:g} TOKENS\n"
            f"📊 Множитель: x{multiplier:g}\n\n"
            f"{outcome}\n"
            f"💎 Выплата: {win_amount:g} TOKENS\n"
            f"💳 Баланс: {balance:g} TOKENS"
        )

        sent = await message.answer(
            result_text
        )

        asyncio.create_task(
            delete_message_later(sent)
        )

    except Exception:

        logger.exception(
            "Ошибка спортивной игры %s",
            game_name
        )

        await credit_game_win(
            user.id,
            bet
        )

        await send_temporary_message(
            message,
            "❌ Ошибка игры. Ставка возвращена."
        )


# ============================================================
# GAME: BASKETBALL
# ============================================================

@dp.message(Command("basket"))
async def game_basket(message: Message):
    """
    Пример:
    /basket 100
    """

    try:
        bet = float(
            message.text.split(maxsplit=1)[1]
        )
    except (ValueError, IndexError):
        await send_temporary_message(
            message,
            "Использование: <code>/basket 100</code>"
        )
        return

    await play_sport_game(
        message,
        "🏀",
        "Баскетбол",
        bet
    )


# ============================================================
# GAME: FOOTBALL
# ============================================================

@dp.message(Command("football"))
async def game_football(message: Message):
    """
    Пример:
    /football 100
    """

    try:
        bet = float(
            message.text.split(maxsplit=1)[1]
        )
    except (ValueError, IndexError):
        await send_temporary_message(
            message,
            "Использование: <code>/football 100</code>"
        )
        return

    await play_sport_game(
        message,
        "⚽",
        "Футбол",
        bet
    )


# ============================================================
# TELEGRAM WEBAPP HMAC VALIDATION
# ============================================================

def validate_webapp_init_data(
    init_data: str,
    bot_token: str = BOT_TOKEN
) -> Optional[dict]:
    """
    Проверка Telegram WebApp initData.

    Используется алгоритм Telegram:
    secret_key = HMAC_SHA256("WebAppData", bot_token)
    hash = HMAC_SHA256(secret_key, data_check_string)

    Возвращает словарь с данными пользователя
    либо None при ошибке подписи.
    """

    if not init_data or not bot_token:
        return None

    try:

        parsed_data = dict(
            urllib.parse.parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )

        received_hash = parsed_data.pop(
            "hash",
            None
        )

        if not received_hash:
            return None

        # ----------------------------------------------------
        # DATA CHECK STRING
        # ----------------------------------------------------

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(
                parsed_data.items()
            )
        )

        # ----------------------------------------------------
        # SECRET KEY
        # ----------------------------------------------------

        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()

        # ----------------------------------------------------
        # CALCULATE HASH
        # ----------------------------------------------------

        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        # ----------------------------------------------------
        # PARSE USER
        # ----------------------------------------------------

        if "user" not in parsed_data:
            return None

        user_data = json.loads(
            parsed_data["user"]
        )

        if not isinstance(user_data, dict):
            return None

        if "id" not in user_data:
            return None

        # ----------------------------------------------------
        # AUTH DATE VALIDATION
        # ----------------------------------------------------

        auth_date = parsed_data.get("auth_date")

        if not auth_date:
            return None

        auth_timestamp = int(auth_date)

        current_timestamp = int(time.time())

        # Не принимаем данные старше 24 часов
        # и данные из будущего.
        if current_timestamp - auth_timestamp > 86400:
            return None

        if auth_timestamp > current_timestamp + 60:
            return None

        return user_data

    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError
    ):

        logger.warning(
            "Ошибка проверки WebApp initData"
        )

        return None


# ============================================================
# WEBAPP REQUEST AUTHENTICATION
# ============================================================

async def get_webapp_user(
    request: web.Request
):
    """
    Получение авторизованного пользователя WebApp.
    """

    init_data = None

    # Поддержка заголовка Authorization.
    authorization = request.headers.get(
        "Authorization",
        ""
    )

    if authorization.startswith("Bearer "):
        init_data = authorization[7:].strip()

    # Поддержка JSON.
    if not init_data:

        try:
            body = await request.json()

            if isinstance(body, dict):
                init_data = body.get("initData")

        except Exception:
            pass

    # Поддержка GET-параметра.
    if not init_data:
        init_data = request.query.get("initData")

    if not init_data:
        return None

    return validate_webapp_init_data(
        init_data
    )


# ============================================================
# WEBAPP ERROR RESPONSE
# ============================================================

def api_error(
    message: str,
    status: int = 400
):
    return web.json_response(
        {
            "success": False,
            "error": message
        },
        status=status
    )


# ============================================================
# API: GET USER
# ============================================================

async def api_user(
    request: web.Request
):
    """
    GET /api/user

    Принимает initData.

    Возвращает:
    - Telegram ID;
    - username;
    - баланс TOKENS;
    - баланс TNC;
    - VIP статус.
    """

    user_data = await get_webapp_user(
        request
    )

    if not user_data:
        return api_error(
            "Unauthorized",
            401
        )

    user_id = int(user_data["id"])

    user = await db_fetchone(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance,
            balance_tnc,
            is_vip,
            is_banned,
            referrals
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user:
        return api_error(
            "User not found",
            404
        )

    if user[6]:
        return api_error(
            "Account banned",
            403
        )

    return web.json_response(
        {
            "success": True,
            "user": {
                "id": user[0],
                "username": user[1],
                "first_name": user[2],
                "balance": user[3],
                "balance_tnc": user[4],
                "is_vip": bool(user[5]),
                "referrals": user[7]
            },
            "currency": {
                "tokens": "TOKENS",
                "crypto": "TNC",
                "rate": TOKEN_TO_TNC_RATE
            }
        }
    )


# ============================================================
# API: SWAP TOKENS <-> TNC
# ============================================================

async def api_swap(
    request: web.Request
):
    """
    POST /api/swap

    JSON:
    {
        "initData": "...",
        "direction": "tokens_to_tnc",
        "amount": 50000
    }

    Курс:
    1 TNC = 50 000 TOKENS.

    Поддерживается обмен в обе стороны.
    """

    user_data = await get_webapp_user(
        request
    )

    if not user_data:
        return api_error(
            "Unauthorized",
            401
        )

    try:
        data = await request.json()

    except Exception:
        return api_error(
            "Invalid JSON"
        )

    if not isinstance(data, dict):
        return api_error(
            "Invalid request"
        )

    try:

        amount = float(
            data.get("amount", 0)
        )

    except (ValueError, TypeError):
        return api_error(
            "Invalid amount"
        )

    if not amount > 0:
        return api_error(
            "Amount must be positive"
        )

    if not amount < float("inf"):
        return api_error(
            "Invalid amount"
        )

    if amount != amount:
        return api_error(
            "Invalid amount"
        )

    direction = data.get("direction")

    user_id = int(
        user_data["id"]
    )

    if direction not in (
        "tokens_to_tnc",
        "tnc_to_tokens"
    ):
        return api_error(
            "Invalid swap direction"
        )

    # --------------------------------------------------------
    # TOKENS -> TNC
    # --------------------------------------------------------

    if direction == "tokens_to_tnc":

        tokens_amount = amount

        tnc_amount = tokens_amount / TOKEN_TO_TNC_RATE

        if tnc_amount <= 0:
            return api_error(
                "Amount too small"
            )

        async with DATABASE_LOCK:

            async with aiosqlite.connect(DATABASE_PATH) as db:

                await db.execute(
                    "BEGIN IMMEDIATE"
                )

                cursor = await db.execute(
                    """
                    SELECT balance, is_banned
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                user = await cursor.fetchone()

                if not user:
                    await db.rollback()
                    return api_error(
                        "User not found",
                        404
                    )

                if user[1]:
                    await db.rollback()
                    return api_error(
                        "Account banned",
                        403
                    )

                if user[0] < tokens_amount:
                    await db.rollback()
                    return api_error(
                        "Insufficient TOKENS balance"
                    )

                await db.execute(
                    """
                    UPDATE users
                    SET balance = balance - ?,
                        balance_tnc = balance_tnc + ?
                    WHERE user_id = ?
                    """,
                    (
                        tokens_amount,
                        tnc_amount,
                        user_id
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
                    VALUES (?, ?, 'TOKENS', 'swap_out', ?)
                    """,
                    (
                        user_id,
                        tokens_amount,
                        f"Обмен на {tnc_amount} TNC"
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
                        tnc_amount,
                        f"Обмен из {tokens_amount} TOKENS"
                    )
                )

                await db.commit()

                await cursor.close()

        return web.json_response(
            {
                "success": True,
                "direction": direction,
                "tokens_spent": tokens_amount,
                "tnc_received": tnc_amount,
                "rate": TOKEN_TO_TNC_RATE
            }
        )

    # --------------------------------------------------------
    # TNC -> TOKENS
    # --------------------------------------------------------

    if direction == "tnc_to_tokens":

        tnc_amount = amount

        tokens_amount = tnc_amount * TOKEN_TO_TNC_RATE

        async with DATABASE_LOCK:

            async with aiosqlite.connect(DATABASE_PATH) as db:

                await db.execute(
                    "BEGIN IMMEDIATE"
                )

                cursor = await db.execute(
                    """
                    SELECT balance_tnc, is_banned
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                user = await cursor.fetchone()

                if not user:
                    await db.rollback()
                    return api_error(
                        "User not found",
                        404
                    )

                if user[1]:
                    await db.rollback()
                    return api_error(
                        "Account banned",
                        403
                    )

                if user[0] < tnc_amount:
                    await db.rollback()
                    return api_error(
                        "Insufficient TNC balance"
                    )

                await db.execute(
                    """
                    UPDATE users
                    SET balance_tnc = balance_tnc - ?,
                        balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (
                        tnc_amount,
                        tokens_amount,
                        user_id
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
                    VALUES (?, ?, 'TNC', 'swap_out', ?)
                    """,
                    (
                        user_id,
                        tnc_amount,
                        f"Обмен на {tokens_amount} TOKENS"
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
                    VALUES (?, ?, 'TOKENS', 'swap_in', ?)
                    """,
                    (
                        user_id,
                        tokens_amount,
                        f"Обмен из {tnc_amount} TNC"
                    )
                )

                await db.commit()

                await cursor.close()

        return web.json_response(
            {
                "success": True,
                "direction": direction,
                "tnc_spent": tnc_amount,
                "tokens_received": tokens_amount,
                "rate": TOKEN_TO_TNC_RATE
            }
        )


# ============================================================
# WEBAPP INDEX PAGE
# ============================================================

async def serve_webapp(
    request: web.Request
):
    """
    Отдает webapp/index.html.

    Если файла нет, бот продолжает работать.
    """

    base_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    index_path = os.path.join(
        base_dir,
        "webapp",
        "index.html"
    )

    if not os.path.isfile(index_path):

        logger.warning(
            "WebApp index.html не найден: %s",
            index_path
        )

        return web.Response(
            text="Not Found",
            status=404,
            content_type="text/plain"
        )

    return web.FileResponse(
        index_path
    )


# ============================================================
# WEBAPP HEALTH CHECK
# ============================================================

async def webapp_health(
    request: web.Request
):
    return web.json_response(
        {
            "success": True,
            "service": "TOKENS",
            "status": "online"
        }
    )


# ============================================================
# CREATE WEB APPLICATION
# ============================================================

def create_web_app():
    """
    Создание aiohttp приложения.

    Маршруты:
    /webapp/
    /api/user
    /api/swap
    /health
    """

    app = web.Application(
        client_max_size=1024 * 1024
    )

    # --------------------------------------------------------
    # WEBAPP
    # --------------------------------------------------------

    app.router.add_get(
        "/webapp/",
        serve_webapp
    )

    # --------------------------------------------------------
    # STATIC FILES
    # --------------------------------------------------------

    if os.path.isdir(WEBAPP_DIR):

        app.router.add_static(
            "/webapp/",
            WEBAPP_DIR,
            show_index=True
        )

    else:

        logger.warning(
            "Папка webapp не найдена: %s",
            WEBAPP_DIR
        )

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    app.router.add_get(
        "/api/user",
        api_user
    )

    app.router.add_post(
        "/api/user",
        api_user
    )

    app.router.add_post(
        "/api/swap",
        api_swap
    )

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    app.router.add_get(
        "/health",
        webapp_health
    )

    return app


# ============================================================
# WEB SERVER STARTUP
# ============================================================

async def start_web_server():
    """
    Запуск HTTP-сервера aiohttp.
    """

    app = create_web_app()

    runner = web.AppRunner(
        app,
        access_log=logger
    )

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT
    )

    await site.start()

    logger.info(
        "TOKENS WebApp запущен на порту %s",
        PORT
    )

    return runner


# ============================================================
# ROULETTE RED NUMBERS
# ============================================================

ROULETTE_RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25,
    27, 30, 32, 34, 36
}

ROULETTE_BLACK_NUMBERS = {
    2, 4, 6, 8, 10,
    11, 13, 15, 17,
    20, 22, 24, 26,
    28, 29, 31, 33, 35
}


# ============================================================
# ROULETTE BET PARSER
# ============================================================

def parse_roulette_bet(
    text: str
) -> Optional[dict]:
    """
    Парсер рулеточных ставок.

    Поддерживаемые варианты:

    к 1000
        Красное, ставка 1000.

    ч 1000
        Черное, ставка 1000.

    10-20 500
        Диапазон 10-20, ставка 500.

    10 500
        Число 10, ставка 500.

    500 10-20 30-34 23-24 24-35
        Несколько диапазонов, ставка 500 на каждый.

    Максимум 100 диапазонов.

    Формат хранения:
    {
        "type": "range",
        "numbers": [[10, 20]],
        "amount": 500
    }
    """

    if not text:
        return None

    text = text.strip().lower()

    text = text.replace(",", ".")

    parts = text.split()

    if len(parts) < 2:
        return None

    # --------------------------------------------------------
    # COLOR BETS
    # --------------------------------------------------------

    color_aliases = {
        "к": "red",
        "красное": "red",
        "красный": "red",
        "ч": "black",
        "черное": "black",
        "чёрное": "black",
        "черный": "black",
        "чёрный": "black",
    }

    if parts[0] in color_aliases:

        try:
            amount = float(parts[1])
        except ValueError:
            return None

        if amount <= 0:
            return None

        if len(parts) != 2:
            return None

        return {
            "type": color_aliases[parts[0]],
            "numbers": [],
            "amount": amount
        }

    # --------------------------------------------------------
    # STAKE FIRST OR LAST
    # --------------------------------------------------------

    amount = None

    bet_parts = []

    # Сначала проверяем последний элемент.
    try:

        amount = float(parts[-1])

        bet_parts = parts[:-1]

    except ValueError:

        # Затем проверяем первый элемент.
        try:

            amount = float(parts[0])

            bet_parts = parts[1:]

        except ValueError:
            return None

    if amount is None or amount <= 0:
        return None

    if not amount < float("inf"):
        return None

    if amount != amount:
        return None

    if not bet_parts:
        return None

    if len(bet_parts) > MAX_ROULETTE_RANGES:
        return None

    # --------------------------------------------------------
    # PARSE NUMBERS AND RANGES
    # --------------------------------------------------------

    numbers = []

    for part in bet_parts:

        if "-" in part:

            range_parts = part.split("-")

            if len(range_parts) != 2:
                return None

            try:

                start = int(range_parts[0])

                end = int(range_parts[1])

            except ValueError:
                return None

            if not (
                0 <= start <= MAX_ROULETTE_NUMBER
                and
                0 <= end <= MAX_ROULETTE_NUMBER
            ):
                return None

            if start > end:
                return None

            numbers.append(
                [start, end]
            )

        else:

            try:
                number = int(part)

            except ValueError:
                return None

            if not 0 <= number <= MAX_ROULETTE_NUMBER:
                return None

            numbers.append(
                [number, number]
            )

    if len(numbers) > MAX_ROULETTE_RANGES:
        return None

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {
        "type": "range",
        "numbers": numbers,
        "amount": amount
    }


# ============================================================
# ROULETTE BET VALIDATION
# ============================================================

def validate_roulette_bet(
    bet: dict
) -> bool:
    """
    Проверка структуры ставки.
    """

    if not isinstance(bet, dict):
        return False

    bet_type = bet.get("type")

    amount = bet.get("amount")

    numbers = bet.get("numbers")

    if bet_type not in (
        "range",
        "red",
        "black"
    ):
        return False

    if not isinstance(amount, (int, float)):
        return False

    if amount <= 0 or not amount < float("inf"):
        return False

    if bet_type == "range":

        if not isinstance(numbers, list):
            return False

        if not 1 <= len(numbers) <= MAX_ROULETTE_RANGES:
            return False

        for item in numbers:

            if not isinstance(item, list):
                return False

            if len(item) != 2:
                return False

            start, end = item

            if not (
                isinstance(start, int)
                and isinstance(end, int)
            ):
                return False

            if not (
                0 <= start <= end <= MAX_ROULETTE_NUMBER
            ):
                return False

    return True


# ============================================================
# ROULETTE RESULT GENERATOR
# ============================================================

def generate_roulette_result():
    """
    Европейская рулетка: 0-36.
    """

    number = secrets.randbelow(37)

    if number == 0:
        color = "green"

    elif number in ROULETTE_RED_NUMBERS:
        color = "red"

    else:
        color = "black"

    return number, color


# ============================================================
# ROULETTE BET CHECK
# ============================================================

def calculate_roulette_win(
    bet: dict,
    number: int,
    color: str
) -> float:
    """
    Подсчет выигрыша.

    Для точного числа:
    x36.

    Для диапазона:
    36 / количество чисел в диапазоне.

    Для цвета:
    x2.
    """

    if not validate_roulette_bet(bet):
        return 0

    bet_type = bet["type"]

    amount = bet["amount"]

    if bet_type == "red":

        if color == "red":
            return amount * 2

        return 0

    if bet_type == "black":

        if color == "black":
            return amount * 2

        return 0

    if bet_type == "range":

        for start, end in bet["numbers"]:

            if start <= number <= end:

                range_size = end - start + 1

                multiplier = 36 / range_size

                return amount * multiplier

    return 0


# ============================================================
# ROULETTE BET SAVE
# ============================================================

async def save_roulette_bet(
    user_id: int,
    bet: dict
):
    """
    Сохранение ставки в SQLite.

    Данные ставки сохраняются в JSON.
    """

    if not validate_roulette_bet(bet):
        return False

    bet_json = json.dumps(
        bet,
        ensure_ascii=False
    )

    success = await charge_game_bet(
        user_id,
        bet["amount"]
    )

    if not success:
        return False

    try:

        await db_execute(
            """
            INSERT INTO roulette_bets (
                user_id,
                bet_amount,
                bet_type,
                bet_value,
                status
            )
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                user_id,
                bet["amount"],
                bet["type"],
                bet_json
            )
        )

        return True

    except Exception:

        logger.exception(
            "Ошибка сохранения ставки рулетки"
        )

        await credit_game_win(
            user_id,
            bet["amount"]
        )

        return False


# ============================================================
# ROULETTE BET HISTORY
# ============================================================

async def get_user_roulette_bets(
    user_id: int
):
    """
    Получение последних ставок пользователя.
    """

    return await db_fetchall(
        """
        SELECT
            id,
            bet_amount,
            bet_type,
            bet_value,
            status,
            win_amount
        FROM roulette_bets
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user_id,)
    )


# ============================================================
# ROULETTE INLINE KEYBOARD
# ============================================================

def get_roulette_keyboard():
    """
    Кнопки повторения и удвоения ставок.
    """

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
# ROULETTE RESULT HISTORY
# ============================================================

async def save_roulette_history(
    number: int,
    color: str,
    total_bets: float,
    total_wins: float
):
    """
    Сохранение результата рулетки.
    """

    await db_execute(
        """
        INSERT INTO roulette_history (
            number,
            color,
            total_bets,
            total_wins
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            number,
            color,
            total_bets,
            total_wins
        )
    )


# ============================================================
# ROULETTE START COMMAND
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "старт"
    )
)
async def roulette_start(message: Message):
    """
    Запускает рулетку по команде "старт".

    Все ожидающие ставки группы обрабатываются
    одним раундом.
    """

    if not await check_game_chat(message):
        return

    chat_id = message.chat.id

    # --------------------------------------------------------
    # GET PENDING BETS
    # --------------------------------------------------------

    pending_bets = await db_fetchall(
        """
        SELECT
            id,
            user_id,
            bet_amount,
            bet_type,
            bet_value
        FROM roulette_bets
        WHERE status = 'pending'
        ORDER BY id ASC
        """
    )

    if not pending_bets:

        await send_temporary_message(
            message,
            (
                "🎰 <b>Рулетка</b>\n\n"
                "Нет активных ставок.\n"
                "Сделайте ставку перед запуском."
            )
        )

        return

    # --------------------------------------------------------
    # FILTER GROUP BETS
    # --------------------------------------------------------

    # В этой версии ставки относятся к одному общему пулу.
    # Для изоляции ставок между группами потребуется отдельное
    # поле chat_id в roulette_bets.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # SEND ROULETTE GIF
    # --------------------------------------------------------

    if os.path.isfile(ROULETTE_GIF):

        try:

            roulette_message = await message.answer_animation(
                FSInputFile(ROULETTE_GIF),
                caption="🎰 <b>Рулетка запущена!</b>"
            )

        except Exception:

            logger.exception(
                "Не удалось отправить GIF рулетки"
            )

            roulette_message = await message.answer(
                "🎰 <b>Рулетка запущена!</b>"
            )

    else:

        roulette_message = await message.answer(
            "🎰 <b>Рулетка запущена!</b>"
        )

    await asyncio.sleep(3)

    # --------------------------------------------------------
    # GENERATE RESULT
    # --------------------------------------------------------

    number, color = generate_roulette_result()

    total_bets = 0

    total_wins = 0

    results = []

    # --------------------------------------------------------
    # PROCESS BETS
    # --------------------------------------------------------

    for row in pending_bets:

        bet_id = row[0]

        user_id = row[1]

        bet_amount = row[2]

        bet_json = row[4]

        try:

            bet = json.loads(bet_json)

        except (
            ValueError,
            TypeError,
            json.JSONDecodeError
        ):

            logger.error(
                "Некорректный JSON ставки %s",
                bet_id
            )

            await db_execute(
                """
                UPDATE roulette_bets
                SET status = 'invalid'
                WHERE id = ?
                """,
                (bet_id,)
            )

            continue

        if not validate_roulette_bet(bet):
            continue

        win_amount = calculate_roulette_win(
            bet,
            number,
            color
        )

        total_bets += bet_amount

        total_wins += win_amount

        if win_amount > 0:

            await credit_game_win(
                user_id,
                win_amount
            )

        await db_execute(
            """
            UPDATE roulette_bets
            SET result_number = ?,
                result_color = ?,
                win_amount = ?,
                status = 'completed'
            WHERE id = ?
            """,
            (
                number,
                color,
                win_amount,
                bet_id
            )
        )

        await log_game(
            user_id,
            "Рулетка",
            bet_amount,
            win_amount,
            f"Число: {number}, цвет: {color}"
        )

        results.append(
            {
                "user_id": user_id,
                "bet": bet_amount,
                "win": win_amount
            }
        )

    # --------------------------------------------------------
    # SAVE HISTORY
    # --------------------------------------------------------

    await save_roulette_history(
        number,
        color,
        total_bets,
        total_wins
    )

    # --------------------------------------------------------
    # COLOR EMOJI
    # --------------------------------------------------------

    color_emojis = {
        "red": "🔴",
        "black": "⚫",
        "green": "🟢"
    }

    color_emoji = color_emojis.get(
        color,
        "⚪"
    )

    # --------------------------------------------------------
    # RESULTS TEXT
    # --------------------------------------------------------

    result_text = (
        "🎰 <b>РУЛЕТКА — РЕЗУЛЬТАТ</b>\n\n"
        f"🎯 Выпало число: <b>{number}</b>\n"
        f"🎨 Цвет: {color_emoji}\n\n"
        f"💰 Всего ставок: {total_bets:g} TOKENS\n"
        f"🏆 Всего выплат: {total_wins:g} TOKENS\n\n"
    )

    winners = [
        item for item in results
        if item["win"] > 0
    ]

    if winners:

        result_text += "<b>🏆 Победители:</b>\n"

        for winner in winners[:15]:

            result_text += (
                f"👤 <code>{winner['user_id']}</code>\n"
                f"💎 Выигрыш: {winner['win']:g} TOKENS\n\n"
            )

    else:

        result_text += (
            "😔 В этом раунде победителей нет.\n"
        )

    # --------------------------------------------------------
    # SEND FINAL MESSAGE
    # --------------------------------------------------------

    result_message = await message.answer(
        result_text,
        reply_markup=get_roulette_keyboard()
    )

    asyncio.create_task(
        delete_message_later(result_message)
    )

    asyncio.create_task(
        delete_message_later(roulette_message)
    )


# ============================================================
# ROULETTE REPEAT BUTTON
# ============================================================

@dp.callback_query(
    F.data == "roulette_repeat"
)
async def roulette_repeat(
    callback: CallbackQuery
):
    """
    Повтор последней ставки пользователя.
    """

    user = callback.from_user

    last_bet = await db_fetchone(
        """
        SELECT bet_value
        FROM roulette_bets
        WHERE user_id = ?
          AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user.id,)
    )

    if not last_bet:

        await callback.answer(
            "Нет предыдущей ставки.",
            show_alert=True
        )

        return

    try:

        bet = json.loads(
            last_bet[0]
        )

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError
    ):

        await callback.answer(
            "Ошибка данных предыдущей ставки.",
            show_alert=True
        )

        return

    if not validate_roulette_bet(bet):

        await callback.answer(
            "Некорректная предыдущая ставка.",
            show_alert=True
        )

        return

    user_data = await get_game_user(
        user.id
    )

    if not user_data or user_data[3]:

        await callback.answer(
            "Аккаунт недоступен.",
            show_alert=True
        )

        return

    if user_data[1] < bet["amount"]:

        await callback.answer(
            "Недостаточно TOKENS.",
            show_alert=True
        )

        return

    success = await save_roulette_bet(
        user.id,
        bet
    )

    if not success:

        await callback.answer(
            "Не удалось создать ставку.",
            show_alert=True
        )

        return

    await callback.answer(
        "🔄 Ставка повторена!"
    )

    if callback.message:

        await callback.message.answer(
            (
                "🎰 <b>Ставка повторена!</b>\n\n"
                f"💰 Сумма: {bet['amount']:g} TOKENS\n"
                "Для запуска раунда напишите: <b>старт</b>"
            )
        )


# ============================================================
# ROULETTE DOUBLE BUTTON
# ============================================================

@dp.callback_query(
    F.data == "roulette_double"
)
async def roulette_double(
    callback: CallbackQuery
):
    """
    Удвоение последней ставки пользователя.
    """

    user = callback.from_user

    last_bet = await db_fetchone(
        """
        SELECT bet_value
        FROM roulette_bets
        WHERE user_id = ?
          AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user.id,)
    )

    if not last_bet:

        await callback.answer(
            "Нет предыдущей ставки.",
            show_alert=True
        )

        return

    try:

        bet = json.loads(
            last_bet[0]
        )

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError
    ):

        await callback.answer(
            "Ошибка данных ставки.",
            show_alert=True
        )

        return

    if not validate_roulette_bet(bet):

        await callback.answer(
            "Некорректная ставка.",
            show_alert=True
        )

        return

    doubled_bet = dict(bet)

    doubled_bet["amount"] = (
        bet["amount"] * 2
    )

    user_data = await get_game_user(
        user.id
    )

    if not user_data or user_data[3]:

        await callback.answer(
            "Аккаунт недоступен.",
            show_alert=True
        )

        return

    if user_data[1] < doubled_bet["amount"]:

        await callback.answer(
            "Недостаточно TOKENS для удвоения.",
            show_alert=True
        )

        return

    success = await save_roulette_bet(
        user.id,
        doubled_bet
    )

    if not success:

        await callback.answer(
            "Не удалось удвоить ставку.",
            show_alert=True
        )

        return

    await callback.answer(
        "⏫ Ставка удвоена!"
    )

    if callback.message:

        await callback.message.answer(
            (
                "⏫ <b>Ставка удвоена!</b>\n\n"
                f"💰 Новая ставка: "
                f"{doubled_bet['amount']:g} TOKENS\n\n"
                "Для запуска раунда напишите: <b>старт</b>"
            )
        )


# ============================================================
# ROULETTE TEXT BET HANDLER
# ============================================================

@dp.message(
    F.text.regexp(
        r"^(?:красное|красный|к|черное|чёрное|черный|чёрный|ч)\s+[\d.,]+$"
    )
)
async def roulette_color_bet(
    message: Message
):
    """
    Ставки на красное и черное.
    """

    if not await check_game_chat(message):
        return

    user = message.from_user

    if not user:
        return

    bet = parse_roulette_bet(
        message.text
    )

    if not bet:
        await send_temporary_message(
            message,
            "❌ Некорректная ставка."
        )
        return

    user_data = await get_game_user(
        user.id
    )

    if not user_data:
        await send_temporary_message(
            message,
            "Сначала используйте /start."
        )
        return

    if user_data[3]:
        await send_temporary_message(
            message,
            "🚫 Аккаунт заблокирован."
        )
        return

    success = await save_roulette_bet(
        user.id,
        bet
    )

    if not success:
        await send_temporary_message(
            message,
            "❌ Недостаточно TOKENS или ошибка ставки."
        )
        return

    color_name = (
        "🔴 Красное"
        if bet["type"] == "red"
        else "⚫ Черное"
    )

    await send_temporary_message(
        message,
        (
            "🎰 <b>Ставка принята!</b>\n\n"
            f"🎨 Ставка: {color_name}\n"
            f"💰 Сумма: {bet['amount']:g} TOKENS\n\n"
            "Для запуска напишите: <b>старт</b>"
        )
    )


# ============================================================
# ROULETTE NUMBER AND RANGE BET HANDLER
# ============================================================

@dp.message(
    F.text.regexp(
        r"^[\d.,]+(?:\s+\d+(?:-\d+)?)+$"
    )
)
async def roulette_number_bet(
    message: Message
):
    """
    Принимает числовые ставки и диапазоны.

    Примеры:

    10-20 500

    500 10-20 30-34 23-24

    10 500
    """

    if not await check_game_chat(message):
        return

    user = message.from_user

    if not user:
        return

    bet = parse_roulette_bet(
        message.text
    )

    if not bet:

        await send_temporary_message(
            message,
            (
                "❌ <b>Некорректная ставка.</b>\n\n"
                "Примеры:\n"
                "<code>10-20 500</code>\n"
                "<code>500 10-20 30-34</code>\n"
                "<code>10 500</code>"
            )
        )

        return

    user_data = await get_game_user(
        user.id
    )

    if not user_data:
        await send_temporary_message(
            message,
            "Сначала используйте /start."
        )
        return

    if user_data[3]:
        await send_temporary_message(
            message,
            "🚫 Аккаунт заблокирован."
        )
        return

    success = await save_roulette_bet(
        user.id,
        bet
    )

    if not success:

        await send_temporary_message(
            message,
            "❌ Недостаточно TOKENS или ошибка ставки."
        )

        return

    ranges_text = "\n".join(
        f"🎯 {start}-{end}"
        for start, end in bet["numbers"]
    )

    await send_temporary_message(
        message,
        (
            "🎰 <b>Ставка принята!</b>\n\n"
            f"{ranges_text}\n\n"
            f"💰 Ставка: {bet['amount']:g} TOKENS\n\n"
            "Для запуска рулетки напишите: <b>старт</b>"
        )
    )


# ============================================================
# END OF PART 2
# ============================================================

# Следующая часть может содержать:
# - профиль пользователя;
# - бонусы;
# - реферальную систему;
# - топ пользователей;
# - административную панель;
# - платежи;
# - запуск polling и aiohttp одновременно.

# ============================================================
# PART 3 - PROFILE, CRYPTO, BONUS, TOP, REFERRALS, TRANSFERS
# ============================================================

import math
from PIL import ImageOps, ImageDraw, ImageFont, ImageFilter


# ============================================================
# ADDITIONAL CONFIGURATION
# ============================================================

BONUS_COOLDOWN_HOURS = 12

NORMAL_BONUS = 2500

VIP_BONUSES = [5000, 7500, 10000]

REFERRAL_INVITER_REWARD = 5000

REFERRAL_NEW_USER_REWARD = 10000

MAX_BONUS_BALANCE = 100000

PRIVATE_MESSAGE_DELETE_DELAY = 30

GROUP_MESSAGE_DELETE_DELAY = 60

VIP_PRICE = int(os.getenv("VIP_PRICE", "0"))

VIP_CURRENCY = os.getenv("VIP_CURRENCY", "TOKENS")

BOT_USERNAME = None


# ============================================================
# FONT LOADER
# ============================================================

def load_font(size: int, bold: bool = False):
    """
    Загрузка шрифта для Pillow.
    """

    if bold:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "arialbd.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "arial.ttf",
        ]

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue

    return ImageFont.load_default()


# ============================================================
# AVATAR GENERATOR
# ============================================================

async def get_user_avatar(user_id: int):
    """
    Получение фотографии профиля Telegram.
    """

    try:
        photos = await bot.get_user_profile_photos(
            user_id=user_id,
            limit=1
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]

        file = await bot.get_file(
            photo.file_id
        )

        avatar_bytes = io.BytesIO()

        await bot.download_file(
            file.file_path,
            destination=avatar_bytes
        )

        avatar_bytes.seek(0)

        avatar = Image.open(
            avatar_bytes
        ).convert("RGBA")

        return avatar

    except Exception:

        logger.exception(
            "Не удалось получить аватар пользователя %s",
            user_id
        )

        return None


# ============================================================
# PROFILE IMAGE GENERATOR
# ============================================================

async def generate_profile_image(
    user_id: int,
    username: str,
    first_name: str,
    balance: float,
    balance_tnc: float,
    total_bets: float,
    total_wins: float,
    total_losses: float,
    games: int
):
    """
    Создание графической карточки профиля TOKENS.

    Содержит:
    - Круглую аватарку;
    - Имя пользователя;
    - Имя бота;
    - Баланс TOKENS;
    - Баланс TNC;
    - Ставки;
    - Выигрыши;
    - Проигрыши;
    - Количество игр.
    """

    width = 900
    height = 780

    image = Image.new(
        "RGB",
        (width, height),
        (15, 20, 38)
    )

    draw = ImageDraw.Draw(image)

    # --------------------------------------------------------
    # BACKGROUND
    # --------------------------------------------------------

    for y in range(height):

        factor = y / height

        color = (
            int(18 + factor * 8),
            int(23 + factor * 12),
            int(43 + factor * 20)
        )

        draw.line(
            (0, y, width, y),
            fill=color
        )

    # Decorative circles.
    draw.ellipse(
        (650, -180, 1050, 220),
        fill=(30, 42, 82)
    )

    draw.ellipse(
        (-180, 570, 230, 980),
        fill=(27, 39, 76)
    )

    # --------------------------------------------------------
    # FONTS
    # --------------------------------------------------------

    title_font = load_font(44, True)

    name_font = load_font(31, True)

    normal_font = load_font(23)

    value_font = load_font(29, True)

    small_font = load_font(19)

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    draw.text(
        (45, 35),
        "TOKENS",
        font=title_font,
        fill=(100, 190, 255)
    )

    draw.text(
        (47, 95),
        "USER PROFILE",
        font=small_font,
        fill=(150, 165, 195)
    )

    # --------------------------------------------------------
    # AVATAR
    # --------------------------------------------------------

    avatar = await get_user_avatar(
        user_id
    )

    avatar_size = 180

    if avatar is None:

        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (55, 85, 145, 255)
        )

        avatar_draw = ImageDraw.Draw(
            avatar
        )

        initials = (
            first_name[:1].upper()
            if first_name
            else "U"
        )

        avatar_draw.text(
            (avatar_size // 2 - 20, avatar_size // 2 - 35),
            initials,
            font=load_font(75, True),
            fill=(255, 255, 255)
        )

    avatar = ImageOps.fit(
        avatar,
        (avatar_size, avatar_size),
        method=Image.Resampling.LANCZOS
    )

    mask = Image.new(
        "L",
        (avatar_size, avatar_size),
        0
    )

    mask_draw = ImageDraw.Draw(mask)

    mask_draw.ellipse(
        (0, 0, avatar_size - 1, avatar_size - 1),
        fill=255
    )

    # Avatar border.
    draw.ellipse(
        (42, 145, 238, 341),
        outline=(90, 180, 255),
        width=7
    )

    image.paste(
        avatar,
        (50, 153),
        mask
    )

    # --------------------------------------------------------
    # USER NAME
    # --------------------------------------------------------

    display_name = first_name or "Пользователь"

    draw.text(
        (275, 170),
        display_name[:25],
        font=name_font,
        fill=(255, 255, 255)
    )

    display_username = (
        f"@{username}"
        if username
        else f"ID: {user_id}"
    )

    draw.text(
        (277, 220),
        display_username[:35],
        font=normal_font,
        fill=(155, 175, 205)
    )

    draw.text(
        (277, 275),
        "TOKENS MEMBER",
        font=small_font,
        fill=(100, 190, 255)
    )

    # --------------------------------------------------------
    # STAT CARDS
    # --------------------------------------------------------

    cards = [
        (
            "💰 TOKENS",
            f"{balance:,.2f}"
        ),
        (
            "💎 TNC",
            f"{balance_tnc:,.6f}"
        ),
        (
            "🎯 СТАВКИ",
            f"{total_bets:,.2f}"
        ),
        (
            "🏆 ВЫИГРЫШИ",
            f"{total_wins:,.2f}"
        ),
        (
            "❌ ПРОИГРЫШИ",
            f"{total_losses:,.2f}"
        ),
        (
            "🎮 ИГРЫ",
            str(games)
        )
    ]

    card_width = 390

    card_height = 115

    start_x = 45

    start_y = 375

    horizontal_gap = 25

    vertical_gap = 20

    for index, (label, value) in enumerate(cards):

        column = index % 2

        row = index // 2

        x = (
            start_x
            + column * (card_width + horizontal_gap)
        )

        y = (
            start_y
            + row * (card_height + vertical_gap)
        )

        draw.rounded_rectangle(
            (
                x,
                y,
                x + card_width,
                y + card_height
            ),
            radius=20,
            fill=(31, 42, 69),
            outline=(54, 76, 115),
            width=2
        )

        draw.text(
            (x + 22, y + 17),
            label,
            font=small_font,
            fill=(160, 185, 220)
        )

        draw.text(
            (x + 22, y + 55),
            value[:22],
            font=value_font,
            fill=(255, 255, 255)
        )

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    draw.line(
        (45, 765, 855, 765),
        fill=(65, 90, 135),
        width=2
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG",
        optimize=True
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# PROFILE INLINE KEYBOARD
# ============================================================

def get_profile_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="profile_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="profile_buy_vip"
                )
            ]
        ]
    )


# ============================================================
# GET PROFILE STATISTICS
# ============================================================

async def get_profile_statistics(
    user_id: int
):
    """
    Получение статистики пользователя.
    """

    result = await db_fetchone(
        """
        SELECT
            COALESCE(SUM(bet), 0),
            COALESCE(SUM(win), 0),
            COALESCE(SUM(
                CASE
                    WHEN win = 0 THEN bet
                    ELSE 0
                END
            ), 0),
            COUNT(*)
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not result:
        return 0, 0, 0, 0

    return (
        result[0],
        result[1],
        result[2],
        result[3]
    )


# ============================================================
# PROFILE HANDLER
# ============================================================

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):
    """
    Отображение профиля пользователя.
    """

    user = message.from_user

    if not user:
        return

    user_data = await db_fetchone(
        """
        SELECT
            balance,
            balance_tnc,
            is_banned,
            is_vip
        FROM users
        WHERE user_id = ?
        """,
        (user.id,)
    )

    if not user_data:

        await message.answer(
            "❌ Используйте /start для регистрации."
        )

        return

    if user_data[2]:

        await message.answer(
            "🚫 Ваш аккаунт заблокирован."
        )

        return

    total_bets, total_wins, total_losses, games = (
        await get_profile_statistics(user.id)
    )

    image_bytes = await generate_profile_image(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        balance=user_data[0],
        balance_tnc=user_data[1],
        total_bets=total_bets,
        total_wins=total_wins,
        total_losses=total_losses,
        games=games
    )

    vip_text = (
        "⭐ VIP"
        if user_data[3]
        else "Обычный пользователь"
    )

    caption = (
        f"👤 <b>Профиль TOKENS</b>\n\n"
        f"Имя: <b>{user.first_name}</b>\n"
        f"Статус: {vip_text}\n"
        f"ID: <code>{user.id}</code>"
    )

    await message.answer_photo(
        BufferedInputFile(
            image_bytes,
            filename="profile.png"
        ),
        caption=caption,
        reply_markup=get_profile_keyboard()
    )


# ============================================================
# PROFILE SETTINGS
# ============================================================

@dp.callback_query(
    F.data == "profile_settings"
)
async def profile_settings(
    callback: CallbackQuery
):
    """
    Настройки аккаунта.
    """

    user_id = callback.from_user.id

    user_data = await db_fetchone(
        """
        SELECT username, is_vip, is_banned
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user_data:

        await callback.answer(
            "Пользователь не найден.",
            show_alert=True
        )

        return

    if user_data[2]:

        await callback.answer(
            "Аккаунт заблокирован.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="profile_buy_vip"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="profile_settings_back"
                )
            ]
        ]
    )

    text = (
        "⚙️ <b>Настройки TOKENS</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"⭐ VIP: {'Активен' if user_data[1] else 'Не активен'}\n\n"
        "Ваш аккаунт защищен системой TOKENS."
    )

    await callback.message.answer(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(
    F.data == "profile_settings_back"
)
async def profile_settings_back(
    callback: CallbackQuery
):

    await callback.answer(
        "Откройте профиль через меню."
    )


# ============================================================
# VIP PURCHASE
# ============================================================

@dp.callback_query(
    F.data == "profile_buy_vip"
)
async def profile_buy_vip(
    callback: CallbackQuery
):
    """
    Покупка VIP.

    Для полноценной покупки необходимо настроить
    платежную систему и VIP_PRICE.
    """

    user_id = callback.from_user.id

    user_data = await db_fetchone(
        """
        SELECT is_vip, is_banned
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user_data:

        await callback.answer(
            "Пользователь не найден.",
            show_alert=True
        )

        return

    if user_data[1]:

        await callback.answer(
            "Аккаунт заблокирован.",
            show_alert=True
        )

        return

    if user_data[0]:

        await callback.answer(
            "⭐ У вас уже есть VIP!",
            show_alert=True
        )

        return

    if VIP_PRICE <= 0:

        await callback.answer(
            "Стоимость VIP пока не настроена. Обратитесь к администратору.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Оплатить VIP",
                    callback_data="vip_payment"
                )
            ]
        ]
    )

    await callback.message.answer(
        (
            "⭐ <b>Покупка TOKENS VIP</b>\n\n"
            f"💰 Стоимость: <b>{VIP_PRICE} {VIP_CURRENCY}</b>\n\n"
            "Преимущества VIP:\n"
            "🎁 Увеличенные бонусы\n"
            "⭐ VIP-статус\n"
            "💎 Дополнительные возможности"
        ),
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(
    F.data == "vip_payment"
)
async def vip_payment(
    callback: CallbackQuery
):

    await callback.answer(
        "Платежный модуль будет подключен отдельно.",
        show_alert=True
    )


# ============================================================
# CRYPTO IMAGE GENERATOR
# ============================================================

def generate_crypto_image(
    tokens_per_tnc: int = TOKEN_TO_TNC_RATE
):
    """
    Создание картинки с курсом TNC.
    """

    width = 900
    height = 500

    image = Image.new(
        "RGB",
        (width, height),
        (13, 20, 42)
    )

    draw = ImageDraw.Draw(image)

    # Background.
    for y in range(height):

        factor = y / height

        color = (
            int(15 + factor * 10),
            int(30 + factor * 20),
            int(60 + factor * 25)
        )

        draw.line(
            (0, y, width, y),
            fill=color
        )

    # Decorative circle.
    draw.ellipse(
        (610, -100, 1050, 350),
        fill=(25, 65, 105)
    )

    title_font = load_font(48, True)

    rate_font = load_font(55, True)

    normal_font = load_font(27)

    small_font = load_font(20)

    draw.text(
        (55, 45),
        "TOKENS CRYPTO",
        font=title_font,
        fill=(105, 195, 255)
    )

    draw.text(
        (60, 145),
        "💎 TNC EXCHANGE RATE",
        font=normal_font,
        fill=(220, 230, 250)
    )

    draw.rounded_rectangle(
        (45, 215, 855, 345),
        radius=25,
        fill=(30, 47, 78),
        outline=(75, 125, 190),
        width=3
    )

    draw.text(
        (80, 245),
        f"1 TNC = {tokens_per_tnc:,}",
        font=rate_font,
        fill=(255, 255, 255)
    )

    draw.text(
        (85, 365),
        "TOKENS",
        font=normal_font,
        fill=(105, 195, 255)
    )

    draw.text(
        (85, 415),
        "Exchange rate inside TOKENS App",
        font=small_font,
        fill=(165, 180, 210)
    )

    output = io.BytesIO()

    image.save(
        output,
        format="PNG",
        optimize=True
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# CRYPTO INLINE KEYBOARD
# ============================================================

def get_crypto_keyboard():

    return InlineKeyboardMarkup(
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


# ============================================================
# CRYPTO HANDLER
# ============================================================

@dp.message(
    F.text == "💎 Крипта"
)
async def crypto_handler(
    message: Message
):
    """
    Показывает курс TNC.
    """

    image_bytes = generate_crypto_image()

    await message.answer_photo(
        BufferedInputFile(
            image_bytes,
            filename="crypto.png"
        ),
        caption=(
            "💎 <b>TOKENS CRYPTO</b>\n\n"
            f"📈 Текущий внутренний курс:\n"
            f"<b>1 TNC = {TOKEN_TO_TNC_RATE:,} TOKENS</b>\n\n"
            "🚀 Откройте приложение для обмена."
        ),
        reply_markup=get_crypto_keyboard()
    )


# ============================================================
# BONUS INLINE KEYBOARD
# ============================================================

def get_bonus_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Забрать бонус",
                    callback_data="claim_bonus"
                )
            ]
        ]
    )


# ============================================================
# BONUS MENU HANDLER
# ============================================================

@dp.message(
    F.text == "🎁 Бонус"
)
async def bonus_menu(
    message: Message
):
    """
    Показывает информацию о бонусах.
    """

    user = message.from_user

    if not user:
        return

    user_data = await db_fetchone(
        """
        SELECT balance, is_vip, is_banned, last_bonus
        FROM users
        WHERE user_id = ?
        """,
        (user.id,)
    )

    if not user_data:
        await message.answer(
            "❌ Сначала используйте /start."
        )
        return

    if user_data[2]:
        await message.answer(
            "🚫 Ваш аккаунт заблокирован."
        )
        return

    balance = user_data[0]

    is_vip = user_data[1]

    if balance > MAX_BONUS_BALANCE:

        error_image = generate_error_image(
            "BONUS UNAVAILABLE"
        )

        await message.answer_photo(
            BufferedInputFile(
                error_image,
                filename="bonus_error.png"
            ),
            caption=(
                "❌ <b>Бонус недоступен!</b>\n\n"
                "Ваш баланс превышает 100 000 TOKENS."
            )
        )

        return

    bonus_amount = (
        random.choice(VIP_BONUSES)
        if is_vip
        else NORMAL_BONUS
    )

    await message.answer(
        (
            "🎁 <b>Ежедневный бонус TOKENS</b>\n\n"
            f"💰 Ваш баланс: {balance:,.2f} TOKENS\n"
            f"🎁 Ваш бонус: {bonus_amount:,} TOKENS\n\n"
            "⏳ Бонус доступен каждые 12 часов."
        ),
        reply_markup=get_bonus_keyboard()
    )


# ============================================================
# CLAIM BONUS
# ============================================================

@dp.callback_query(
    F.data == "claim_bonus"
)
async def claim_bonus(
    callback: CallbackQuery
):
    """
    Выдача бонуса с кулдауном 12 часов.
    """

    user_id = callback.from_user.id

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute(
                "BEGIN IMMEDIATE"
            )

            cursor = await db.execute(
                """
                SELECT
                    balance,
                    is_vip,
                    is_banned,
                    last_bonus
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            )

            user_data = await cursor.fetchone()

            if not user_data:

                await db.rollback()

                await callback.answer(
                    "Сначала зарегистрируйтесь через /start.",
                    show_alert=True
                )

                return

            balance, is_vip, is_banned, last_bonus = user_data

            if is_banned:

                await db.rollback()

                await callback.answer(
                    "Аккаунт заблокирован.",
                    show_alert=True
                )

                return

            if balance > MAX_BONUS_BALANCE:

                await db.rollback()

                await callback.answer(
                    "Бонус недоступен при балансе больше 100 000 TOKENS.",
                    show_alert=True
                )

                return

            now = datetime.utcnow()

            # ------------------------------------------------
            # COOLDOWN
            # ------------------------------------------------

            if last_bonus:

                try:

                    previous_bonus = datetime.fromisoformat(
                        last_bonus
                    )

                    elapsed = now - previous_bonus

                    cooldown = timedelta(
                        hours=BONUS_COOLDOWN_HOURS
                    )

                    if elapsed < cooldown:

                        remaining = cooldown - elapsed

                        total_seconds = int(
                            remaining.total_seconds()
                        )

                        hours = total_seconds // 3600

                        minutes = (
                            total_seconds % 3600
                        ) // 60

                        await db.rollback()

                        await callback.answer(
                            (
                                f"⏳ Следующий бонус через "
                                f"{hours} ч. {minutes} мин."
                            ),
                            show_alert=True
                        )

                        return

                except ValueError:

                    logger.warning(
                        "Некорректная дата бонуса пользователя %s",
                        user_id
                    )

            # ------------------------------------------------
            # BONUS AMOUNT
            # ------------------------------------------------

            bonus_amount = (
                random.choice(VIP_BONUSES)
                if is_vip
                else NORMAL_BONUS
            )

            bonus_type = (
                "vip"
                if is_vip
                else "normal"
            )

            # ------------------------------------------------
            # UPDATE BALANCE
            # ------------------------------------------------

            await db.execute(
                """
                UPDATE users
                SET balance = balance + ?,
                    last_bonus = ?
                WHERE user_id = ?
                """,
                (
                    bonus_amount,
                    now.isoformat(),
                    user_id
                )
            )

            # ------------------------------------------------
            # BONUS HISTORY
            # ------------------------------------------------

            await db.execute(
                """
                INSERT INTO bonus (
                    user_id,
                    amount,
                    bonus_type
                )
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    bonus_amount,
                    bonus_type
                )
            )

            # ------------------------------------------------
            # TRANSACTION HISTORY
            # ------------------------------------------------

            await db.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    amount,
                    currency,
                    transaction_type,
                    description
                )
                VALUES (?, ?, 'TOKENS', 'bonus', ?)
                """,
                (
                    user_id,
                    bonus_amount,
                    "Получение бонуса TOKENS"
                )
            )

            await db.commit()

            await cursor.close()

    await callback.answer(
        "🎁 Бонус успешно получен!"
    )

    if callback.message:

        await callback.message.answer(
            (
                "🎉 <b>БОНУС ПОЛУЧЕН!</b>\n\n"
                f"💰 Начислено: <b>+{bonus_amount:,} TOKENS</b>\n\n"
                "⏳ Следующий бонус через 12 часов."
            )
        )


# ============================================================
# TOP USERS
# ============================================================

async def get_top_users(limit: int = 10):
    """
    Получение топа пользователей.
    """

    return await db_fetchall(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance
        FROM users
        WHERE is_banned = 0
        ORDER BY balance DESC
        LIMIT ?
        """,
        (limit,)
    )


# ============================================================
# FORMAT TOP USERS
# ============================================================

async def format_top_users(
    limit: int = 10
):
    """
    Формирование текстового рейтинга.
    """

    users = await get_top_users(
        limit
    )

    if not users:
        return "🏆 Пока нет пользователей в рейтинге."

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    lines = [
        "🏆 <b>ТОП-10 TOKENS</b>",
        "",
    ]

    for index, user in enumerate(users):

        user_id = user[0]

        username = user[1]

        first_name = user[2]

        balance = user[3]

        if index < 3:
            prefix = medals[index]
        else:
            prefix = f"{index + 1}."

        display_name = (
            f"@{username}"
            if username
            else first_name or f"ID {user_id}"
        )

        lines.append(
            f"{prefix} <b>{display_name}</b>"
        )

        lines.append(
            f"   💰 {balance:,.2f} TOKENS"
        )

        lines.append("")

    return "\n".join(lines)


# ============================================================
# TOP PRIVATE MENU HANDLER
# ============================================================

@dp.message(
    F.text == "🏆 Топ"
)
async def top_handler(
    message: Message
):

    text = await format_top_users(10)

    await message.answer(
        text
    )


# ============================================================
# REFERRAL KEYBOARD
# ============================================================

def get_referral_keyboard(
    referral_link: str
):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Пригласить друга",
                    url=referral_link
                )
            ]
        ]
    )


# ============================================================
# REFERRAL HANDLER
# ============================================================

@dp.message(
    F.text == "🔗 Рефералка"
)
async def referral_handler(
    message: Message
):
    """
    Реферальная система.

    Пригласивший получает 5000 TOKENS.
    Новый пользователь получает 10000 TOKENS.

    Для корректной работы ниже переопределяется
    register_user().
    """

    user = message.from_user

    if not user:
        return

    global BOT_USERNAME

    if not BOT_USERNAME:

        me = await bot.get_me()

        BOT_USERNAME = me.username

    if not BOT_USERNAME:

        await message.answer(
            "❌ Не удалось получить ссылку бота."
        )

        return

    referral_link = (
        f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    )

    user_data = await db_fetchone(
        """
        SELECT referrals, balance
        FROM users
        WHERE user_id = ?
        """,
        (user.id,)
    )

    if not user_data:

        await message.answer(
            "Сначала используйте /start."
        )

        return

    referrals = user_data[0]

    balance = user_data[1]

    await message.answer(
        (
            "🔗 <b>Реферальная программа TOKENS</b>\n\n"
            "Приглашайте друзей и получайте награды!\n\n"
            "🎁 За каждого приглашенного:\n"
            f"👤 Вам: <b>+{REFERRAL_INVITER_REWARD:,} TOKENS</b>\n"
            f"🆕 Другу: <b>+{REFERRAL_NEW_USER_REWARD:,} TOKENS</b>\n\n"
            f"👥 Приглашено: <b>{referrals}</b>\n"
            f"💰 Ваш баланс: <b>{balance:,.2f} TOKENS</b>\n\n"
            "👇 Ваша персональная ссылка:"
        ),
        reply_markup=get_referral_keyboard(
            referral_link
        )
    )


# ============================================================
# REFERRAL REGISTRATION OVERRIDE
# ============================================================

async def register_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    referral_id: Optional[int] = None
):
    """
    Обновленная регистрация.

    ВАЖНО:
    Эта функция заменяет register_user из PART 1.

    Поддерживает:
    /start
    /start 123456
    /start ref_123456

    Награды:
    Пригласившему: 5000 TOKENS.
    Новому пользователю: 10000 TOKENS.
    """

    if referral_id is not None:
        if referral_id == user_id:
            referral_id = None

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute(
                "PRAGMA foreign_keys=ON"
            )

            await db.execute(
                "BEGIN IMMEDIATE"
            )

            cursor = await db.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            )

            existing = await cursor.fetchone()

            if existing:

                await db.execute(
                    """
                    UPDATE users
                    SET username = ?,
                        first_name = ?,
                        last_activity = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (
                        username,
                        first_name,
                        user_id
                    )
                )

                await db.commit()

                await cursor.close()

                return False

            # ------------------------------------------------
            # CHECK REFERRER
            # ------------------------------------------------

            valid_referral = None

            if referral_id is not None:

                cursor = await db.execute(
                    """
                    SELECT user_id
                    FROM users
                    WHERE user_id = ?
                      AND is_banned = 0
                    """,
                    (referral_id,)
                )

                referrer = await cursor.fetchone()

                if referrer:
                    valid_referral = referral_id

            # ------------------------------------------------
            # REGISTER USER
            # ------------------------------------------------

            start_balance = START_BONUS

            if valid_referral is not None:
                start_balance += REFERRAL_NEW_USER_REWARD

            await db.execute(
                """
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    balance,
                    balance_tnc,
                    referral_id,
                    referrals,
                    is_banned,
                    is_vip
                )
                VALUES (?, ?, ?, ?, 0, ?, 0, 0, 0)
                """,
                (
                    user_id,
                    username,
                    first_name,
                    start_balance,
                    valid_referral
                )
            )

            # ------------------------------------------------
            # START BONUS TRANSACTION
            # ------------------------------------------------

            if START_BONUS > 0:

                await db.execute(
                    """
                    INSERT INTO transactions (
                        user_id,
                        amount,
                        currency,
                        transaction_type,
                        description
                    )
                    VALUES (?, ?, 'TOKENS', 'start_bonus', ?)
                    """,
                    (
                        user_id,
                        START_BONUS,
                        "Стартовый бонус"
                    )
                )

            # ------------------------------------------------
            # REFERRAL REWARDS
            # ------------------------------------------------

            if valid_referral is not None:

                await db.execute(
                    """
                    UPDATE users
                    SET referrals = referrals + 1,
                        balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (
                        REFERRAL_INVITER_REWARD,
                        valid_referral
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
                    VALUES (?, ?, 'TOKENS', 'referral_reward', ?)
                    """,
                    (
                        valid_referral,
                        REFERRAL_INVITER_REWARD,
                        f"Приглашение пользователя {user_id}"
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
                    VALUES (?, ?, 'TOKENS', 'referral_welcome', ?)
                    """,
                    (
                        user_id,
                        REFERRAL_NEW_USER_REWARD,
                        "Бонус за регистрацию по реферальной ссылке"
                    )
                )

            await db.commit()

            await cursor.close()

    logger.info(
        "Пользователь %s зарегистрирован. Реферал: %s",
        user_id,
        valid_referral
    )

    return True


# ============================================================
# PARSE REFERRAL START PARAMETER
# ============================================================

def parse_referral_parameter(
    text: Optional[str]
) -> Optional[int]:
    """
    Извлекает referral ID из /start ref_ID.
    """

    if not text:
        return None

    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return None

    parameter = parts[1].strip()

    if parameter.startswith("ref_"):
        parameter = parameter[4:]

    if parameter.isdigit():
        return int(parameter)

    return None


# ============================================================
# REFERRAL START HANDLER COMPATIBILITY
# ============================================================

# В PART 1 обработчик /start разбирал только числовой ID.
# Поэтому для поддержки ref_ID замените в cmd_start PART 1:
#
# referral_parameter = command_parts[1].strip()
# if referral_parameter.isdigit():
#     referral_id = int(referral_parameter)
#
# на:
#
# referral_id = parse_referral_parameter(message.text)
#
# Обработчик /start уже вызывает register_user() по имени,
# поэтому переопределенная функция выше будет использоваться.


# ============================================================
# TRANSFER PARSER
# ============================================================

def parse_transfer_command(
    text: str
):
    """
    Форматы:

    перевод 1000
        Перевод пользователю из реплая.

    перевод @username 1000
        Перевод пользователю по username.
    """

    if not text:
        return None

    parts = text.strip().split()

    if len(parts) == 2:

        try:
            amount = float(parts[1])
        except ValueError:
            return None

        return {
            "username": None,
            "amount": amount
        }

    if len(parts) == 3:

        username = parts[1].lstrip("@")

        try:
            amount = float(parts[2])
        except ValueError:
            return None

        if not username:
            return None

        return {
            "username": username.lower(),
            "amount": amount
        }

    return None


# ============================================================
# TRANSFER EXECUTION
# ============================================================

async def execute_transfer(
    sender_id: int,
    recipient_id: int,
    amount: float
):
    """
    Безопасный атомарный перевод TOKENS.
    """

    if sender_id == recipient_id:
        return False, "Нельзя переводить самому себе."

    if amount <= 0 or not math.isfinite(amount):
        return False, "Некорректная сумма."

    async with DATABASE_LOCK:

        async with aiosqlite.connect(DATABASE_PATH) as db:

            await db.execute(
                "BEGIN IMMEDIATE"
            )

            cursor = await db.execute(
                """
                SELECT balance, is_banned
                FROM users
                WHERE user_id = ?
                """,
                (sender_id,)
            )

            sender = await cursor.fetchone()

            cursor = await db.execute(
                """
                SELECT balance, is_banned
                FROM users
                WHERE user_id = ?
                """,
                (recipient_id,)
            )

            recipient = await cursor.fetchone()

            if not sender or not recipient:

                await db.rollback()

                return False, "Один из пользователей не найден."

            if sender[1] or recipient[1]:

                await db.rollback()

                return False, "Перевод недоступен для заблокированного аккаунта."

            if sender[0] < amount:

                await db.rollback()

                return False, "Недостаточно TOKENS."

            # ------------------------------------------------
            # SENDER
            # ------------------------------------------------

            await db.execute(
                """
                UPDATE users
                SET balance = balance - ?,
                    total_spent = total_spent + ?
                WHERE user_id = ?
                """,
                (
                    amount,
                    amount,
                    sender_id
                )
            )

            # ------------------------------------------------
            # RECIPIENT
            # ------------------------------------------------

            await db.execute(
                """
                UPDATE users
                SET balance = balance + ?,
                    total_earned = total_earned + ?
                WHERE user_id = ?
                """,
                (
                    amount,
                    amount,
                    recipient_id
                )
            )

            # ------------------------------------------------
            # TRANSACTION HISTORY
            # ------------------------------------------------

            await db.execute(
                """
                INSERT INTO transactions (
                    user_id,
                    amount,
                    currency,
                    transaction_type,
                    description
                )
                VALUES (?, ?, 'TOKENS', 'transfer_out', ?)
                """,
                (
                    sender_id,
                    amount,
                    f"Перевод пользователю {recipient_id}"
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
                VALUES (?, ?, 'TOKENS', 'transfer_in', ?)
                """,
                (
                    recipient_id,
                    amount,
                    f"Получен перевод от пользователя {sender_id}"
                )
            )

            await db.commit()

    return True, "Перевод выполнен."


# ============================================================
# TRANSFER COMMAND
# ============================================================

@dp.message(
    F.text.regexp(r"^перевод\s+")
)
async def transfer_handler(
    message: Message
):
    """
    Переводы через reply или username.
    """

    sender = message.from_user

    if not sender:
        return

    parsed = parse_transfer_command(
        message.text
    )

    if not parsed:

        await send_temporary_message(
            message,
            (
                "❌ <b>Неверный формат.</b>\n\n"
                "Используйте:\n"
                "<code>перевод 1000</code> — ответом на сообщение.\n"
                "<code>перевод @username 1000</code>"
            )
        )

        return

    amount = parsed["amount"]

    recipient_id = None

    # --------------------------------------------------------
    # REPLY TARGET
    # --------------------------------------------------------

    if message.reply_to_message:

        reply_user = message.reply_to_message.from_user

        if reply_user:
            recipient_id = reply_user.id

    # --------------------------------------------------------
    # USERNAME TARGET
    # --------------------------------------------------------

    elif parsed["username"]:

        recipient = await db_fetchone(
            """
            SELECT user_id
            FROM users
            WHERE LOWER(username) = ?
            """,
            (parsed["username"],)
        )

        if recipient:
            recipient_id = recipient[0]

    else:

        await send_temporary_message(
            message,
            (
                "❌ Укажите получателя ответом на сообщение "
                "или через @username."
            )
        )

        return

    if recipient_id is None:

        await send_temporary_message(
            message,
            (
                "❌ Получатель не найден.\n\n"
                "Пользователь должен быть зарегистрирован в TOKENS."
            )
        )

        return

    if sender.id == recipient_id:

        await send_temporary_message(
            message,
            "❌ Нельзя переводить самому себе."
        )

        return

    success, result = await execute_transfer(
        sender.id,
        recipient_id,
        amount
    )

    if not success:

        await send_temporary_message(
            message,
            f"❌ {result}"
        )

        return

    await message.answer(
        (
            "💸 <b>ПЕРЕВОД ВЫПОЛНЕН!</b>\n\n"
            f"👤 Отправитель: {sender.full_name}\n"
            f"🆔 Получатель: <code>{recipient_id}</code>\n"
            f"💰 Сумма: <b>{amount:,.2f} TOKENS</b>"
        )
    )


# ============================================================
# GROUP COMMAND: BALANCE
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "б"
    )
)
async def group_balance(
    message: Message
):
    """
    Команда: б
    """

    if message.chat.type not in ("group", "supergroup"):
        return

    user = message.from_user

    if not user:
        return

    user_data = await db_fetchone(
        """
        SELECT balance, balance_tnc, is_banned
        FROM users
        WHERE user_id = ?
        """,
        (user.id,)
    )

    if not user_data:

        sent = await message.answer(
            "❌ Используйте /start для регистрации."
        )

    elif user_data[2]:

        sent = await message.answer(
            "🚫 Аккаунт заблокирован."
        )

    else:

        sent = await message.answer(
            (
                f"👤 <b>{user.full_name}</b>\n\n"
                f"💰 TOKENS: <b>{user_data[0]:,.2f}</b>\n"
                f"💎 TNC: <b>{user_data[1]:,.6f}</b>"
            )
        )

    asyncio.create_task(
        delete_message_later(
            message,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )

    asyncio.create_task(
        delete_message_later(
            sent,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# GROUP COMMAND: ROULETTE LOG
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "лог"
    )
)
async def group_roulette_log(
    message: Message
):
    """
    Команда: лог

    Последние 10 чисел рулетки.
    """

    if message.chat.type not in ("group", "supergroup"):
        return

    history = await db_fetchall(
        """
        SELECT number, color
        FROM roulette_history
        ORDER BY id DESC
        LIMIT 10
        """
    )

    if not history:

        text = (
            "🎰 <b>История рулетки</b>\n\n"
            "Пока результатов нет."
        )

    else:

        color_emojis = {
            "red": "🔴",
            "black": "⚫",
            "green": "🟢"
        }

        lines = [
            "🎰 <b>ПОСЛЕДНИЕ 10 РЕЗУЛЬТАТОВ</b>",
            ""
        ]

        for number, color in history:

            emoji = color_emojis.get(
                color,
                "⚪"
            )

            lines.append(
                f"{emoji} <b>{number}</b>"
            )

        text = "\n".join(lines)

    sent = await message.answer(
        text
    )

    asyncio.create_task(
        delete_message_later(
            message,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )

    asyncio.create_task(
        delete_message_later(
            sent,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# GROUP COMMAND: TOP
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "топ"
    )
)
async def group_top(
    message: Message
):
    """
    Команда: топ
    """

    if message.chat.type not in ("group", "supergroup"):
        return

    text = await format_top_users(10)

    sent = await message.answer(
        text
    )

    asyncio.create_task(
        delete_message_later(
            message,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )

    asyncio.create_task(
        delete_message_later(
            sent,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# GROUP COMMAND: BOT STATUS
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "бот"
    )
)
async def group_bot_status(
    message: Message
):
    """
    Команда: бот
    """

    if message.chat.type not in ("group", "supergroup"):
        return

    sent = await message.answer(
        "🤖 На месте!"
    )

    asyncio.create_task(
        delete_message_later(
            message,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )

    asyncio.create_task(
        delete_message_later(
            sent,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# GROUP COMMAND: WHAT'S NEW
# ============================================================

@dp.message(
    F.text.func(
        lambda text: text.strip().lower() == "что нового"
    )
)
async def group_whats_new(
    message: Message
):
    """
    Команда: что нового
    """

    if message.chat.type not in ("group", "supergroup"):
        return

    text = (
        "📰 <b>Что нового в TOKENS?</b>\n\n"
        "🚀 TOKENS App — управление балансом.\n"
        "🎁 Бонусы каждые 12 часов.\n"
        "💎 Обмен TOKENS и TNC.\n"
        "🎰 Рулетка и игровые режимы.\n"
        "🏆 Рейтинг игроков.\n"
        "🔗 Реферальная программа.\n\n"
        "Следите за обновлениями!"
    )

    sent = await message.answer(
        text
    )

    asyncio.create_task(
        delete_message_later(
            message,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )

    asyncio.create_task(
        delete_message_later(
            sent,
            GROUP_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# PRIVATE MESSAGE AUTO DELETE
# ============================================================

async def private_auto_delete(
    message: Message,
    response: Message
):
    """
    Удаление обычных сообщений в ЛС через 30 секунд.

    Не используется для главного меню и профиля.
    """

    if message.chat.type != "private":
        return

    asyncio.create_task(
        delete_message_later(
            response,
            PRIVATE_MESSAGE_DELETE_DELAY
        )
    )


# ============================================================
# END OF PART 3
# ============================================================

# ВАЖНО:
#
# 1. В PART 1 замените разбор referral_id внутри cmd_start:
#
#    referral_id = parse_referral_parameter(message.text)
#
# 2. В PART 2 функция register_user уже будет заменена
#    реализацией из PART 3 при вызове /start.
#
# 3. Для VIP необходимо отдельно подключить платежный модуль.
#
# 4. Для WebApp используйте:
#    GET  /api/user?initData=...
#    POST /api/swap
#
# 5. Для запуска бота и aiohttp используйте функцию
#    запуска из следующей части.

# ============================================================
# ЧАСТЬ 4. АДМИН-ПАНЕЛЬ, VIP-КЕШБЭК И ЗАПУСК БОТА
# ============================================================

import contextlib
import traceback


# ------------------------------------------------------------
# НАСТРОЙКИ АДМИНИСТРАТОРА
# ------------------------------------------------------------

VIP_CASHBACK_PERCENT = 0.025
VIP_CASHBACK_INTERVAL = 24 * 60 * 60
ADMIN_BROADCAST_DELAY = 0.05


def is_admin(user_id: int) -> bool:
    """Проверка прав администратора."""
    try:
        return int(user_id) == int(ADMIN_ID)
    except (TypeError, ValueError):
        return False


async def admin_reply(message: Message, text: str):
    """Отправка ответа администратору."""
    await message.answer(text, parse_mode="HTML")


async def get_all_user_ids():
    """Получение ID всех пользователей."""
    rows = await db_fetchall(
        "SELECT user_id FROM users"
    )
    return [int(row[0]) for row in rows]


async def get_user_balance(user_id: int) -> int:
    """Получение баланса пользователя."""
    row = await db_fetchone(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )
    return int(row[0]) if row and row[0] is not None else 0


# ------------------------------------------------------------
# АДМИН: @ПОМОЩЬ
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@помощь$"))
async def admin_help_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    text = (
        "👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА TOKENS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>Пользователи</b>\n"
        "<code>@скан ID</code> — информация о пользователе\n"
        "<code>@выдать ID СУММА</code> — начислить TOKENS\n"
        "<code>@бан ID ЧАСЫ</code> — временная блокировка\n\n"
        "💰 <b>Экономика</b>\n"
        "<code>@дроп СУММА</code> — начислить всем пользователям\n"
        "<code>@сет_курс ЧИСЛО</code> — изменить курс TNC\n"
        "<code>@дождь СУММА</code> — раздать TOKENS игрокам чата\n\n"
        "📊 <b>Статистика</b>\n"
        "<code>@стата</code> — статистика бота\n\n"
        "📢 <b>Рассылка</b>\n"
        "<code>@рассылка ТЕКСТ</code> — сообщение всем пользователям\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Команды доступны только администратору."
    )

    await admin_reply(message, text)


# ------------------------------------------------------------
# АДМИН: @СКАН ID
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@скан\s+\d+$"))
async def admin_scan_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        user_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await admin_reply(message, "❌ Использование: <code>@скан ID</code>")
        return

    user = await db_fetchone(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance,
            balance_tnc,
            referrals,
            is_banned,
            is_vip,
            last_activity
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not user:
        await admin_reply(message, "❌ Пользователь не найден.")
        return

    (
        uid,
        username,
        first_name,
        balance,
        balance_tnc,
        referrals,
        is_banned,
        is_vip,
        last_activity
    ) = user

    stats = await db_fetchone(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(bet), 0),
            COALESCE(SUM(win), 0)
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,)
    )

    games = int(stats[0]) if stats else 0
    total_bet = int(stats[1]) if stats else 0
    total_win = int(stats[2]) if stats else 0

    transactions_count = await db_fetchone(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE user_id = ?
        """,
        (user_id,)
    )

    transactions = (
        int(transactions_count[0])
        if transactions_count else 0
    )

    text = (
        "🔎 <b>ПОЛНАЯ ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Имя: {first_name or 'Не указано'}\n"
        f"📛 Username: @{username or 'отсутствует'}\n\n"
        f"💰 TOKENS: <b>{int(balance or 0):,}</b>\n"
        f"💎 TNC: <b>{float(balance_tnc or 0):.8f}</b>\n"
        f"👥 Рефералов: <b>{int(referrals or 0)}</b>\n"
        f"⭐ VIP: {'Да' if is_vip else 'Нет'}\n"
        f"🚫 Заблокирован: {'Да' if is_banned else 'Нет'}\n\n"
        f"🎮 Игр сыграно: <b>{games}</b>\n"
        f"📉 Всего поставлено: <b>{total_bet:,}</b>\n"
        f"📈 Всего выиграно: <b>{total_win:,}</b>\n"
        f"💳 Транзакций: <b>{transactions}</b>\n"
        f"🕒 Последняя активность: {last_activity or 'Нет данных'}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await admin_reply(message, text)


# ------------------------------------------------------------
# АДМИН: @ВЫДАТЬ ID СУММА
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@выдать\s+\d+\s+\d+$"))
async def admin_give_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        _, user_id_raw, amount_raw = message.text.split()
        user_id = int(user_id_raw)
        amount = int(amount_raw)
    except (ValueError, IndexError):
        await admin_reply(
            message,
            "❌ Использование: <code>@выдать ID СУММА</code>"
        )
        return

    if amount <= 0:
        await admin_reply(message, "❌ Сумма должна быть больше нуля.")
        return

    user = await db_fetchone(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    if not user:
        await admin_reply(message, "❌ Пользователь не найден.")
        return

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET balance = COALESCE(balance, 0) + ?
                WHERE user_id = ?
                """,
                (amount, user_id)
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description)
                VALUES (?, ?, 'TOKENS', 'admin_give', ?)
                """,
                (
                    user_id,
                    amount,
                    f"Начисление администратором {message.from_user.id}"
                )
            )

            await db.commit()

    await admin_reply(
        message,
        f"✅ Пользователю <code>{user_id}</code> начислено "
        f"<b>{amount:,} TOKENS</b>."
    )

    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id,
            f"🎁 Администратор начислил вам <b>{amount:,} TOKENS</b>!",
            parse_mode="HTML"
        )


# ------------------------------------------------------------
# АДМИН: @ДРОП СУММА
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@дроп\s+\d+$"))
async def admin_drop_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text.split()[1])
    except (IndexError, ValueError):
        await admin_reply(message, "❌ Использование: <code>@дроп СУММА</code>")
        return

    if amount <= 0:
        await admin_reply(message, "❌ Сумма должна быть больше нуля.")
        return

    user_ids = await get_all_user_ids()

    if not user_ids:
        await admin_reply(message, "❌ В базе пока нет пользователей.")
        return

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET balance = COALESCE(balance, 0) + ?
                """,
                (amount,)
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description)
                SELECT
                    user_id,
                    ?,
                    'TOKENS',
                    'admin_drop',
                    'Массовое начисление администратором'
                FROM users
                """,
                (amount,)
            )

            await db.commit()

    total = len(user_ids) * amount

    await admin_reply(
        message,
        "🎉 <b>МАССОВОЕ НАЧИСЛЕНИЕ ЗАВЕРШЕНО</b>\n\n"
        f"👥 Получателей: <b>{len(user_ids)}</b>\n"
        f"💰 На каждого: <b>{amount:,} TOKENS</b>\n"
        f"📦 Всего начислено: <b>{total:,} TOKENS</b>"
    )


# ------------------------------------------------------------
# АДМИН: @БАН ID ЧАСЫ
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@бан\s+\d+\s+\d+$"))
async def admin_ban_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        _, user_id_raw, hours_raw = message.text.split()
        user_id = int(user_id_raw)
        hours = int(hours_raw)
    except (ValueError, IndexError):
        await admin_reply(
            message,
            "❌ Использование: <code>@бан ID ЧАСЫ</code>"
        )
        return

    if hours <= 0:
        await admin_reply(message, "❌ Количество часов должно быть больше нуля.")
        return

    user = await db_fetchone(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    if not user:
        await admin_reply(message, "❌ Пользователь не найден.")
        return

    ban_until = (
        datetime.now() + timedelta(hours=hours)
    ).isoformat(timespec="seconds")

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET is_banned = 1,
                    ban_until = ?
                WHERE user_id = ?
                """,
                (ban_until, user_id)
            )
            await db.commit()

    await admin_reply(
        message,
        f"🚫 Пользователь <code>{user_id}</code> заблокирован "
        f"на <b>{hours}</b> ч.\n"
        f"До: <code>{ban_until}</code>"
    )

    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id,
            f"🚫 Ваш аккаунт временно заблокирован на {hours} ч."
        )


# ------------------------------------------------------------
# АДМИН: @СТАТА
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@стата$"))
async def admin_stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    users_count = await db_fetchone(
        "SELECT COUNT(*) FROM users"
    )

    total_balance = await db_fetchone(
        "SELECT COALESCE(SUM(balance), 0) FROM users"
    )

    games_count = await db_fetchone(
        "SELECT COUNT(*) FROM game_log"
    )

    vip_count = await db_fetchone(
        "SELECT COUNT(*) FROM users WHERE is_vip = 1"
    )

    banned_count = await db_fetchone(
        "SELECT COUNT(*) FROM users WHERE is_banned = 1"
    )

    referrals_count = await db_fetchone(
        "SELECT COALESCE(SUM(referrals), 0) FROM users"
    )

    transactions_count = await db_fetchone(
        "SELECT COUNT(*) FROM transactions"
    )

    text = (
        "📊 <b>ОБЩАЯ СТАТИСТИКА TOKENS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: <b>{int(users_count[0] or 0):,}</b>\n"
        f"💰 Общий баланс: <b>{int(total_balance[0] or 0):,} TOKENS</b>\n"
        f"🎮 Всего игр: <b>{int(games_count[0] or 0):,}</b>\n"
        f"⭐ VIP-пользователей: <b>{int(vip_count[0] or 0):,}</b>\n"
        f"🚫 Заблокировано: <b>{int(banned_count[0] or 0):,}</b>\n"
        f"👥 Всего рефералов: <b>{int(referrals_count[0] or 0):,}</b>\n"
        f"💳 Транзакций: <b>{int(transactions_count[0] or 0):,}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await admin_reply(message, text)


# ------------------------------------------------------------
# АДМИН: @РАССЫЛКА ТЕКСТ
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@рассылка\s+.+"))
async def admin_broadcast_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    broadcast_text = message.text.split(maxsplit=1)[1].strip()

    if not broadcast_text:
        await admin_reply(
            message,
            "❌ Использование: <code>@рассылка ТЕКСТ</code>"
        )
        return

    user_ids = await get_all_user_ids()

    sent = 0
    failed = 0
    blocked = 0

    await admin_reply(
        message,
        f"📢 Начинаю рассылку для <b>{len(user_ids)}</b> пользователей..."
    )

    for user_id in user_ids:
        try:
            await bot.send_message(
                user_id,
                broadcast_text,
                parse_mode="HTML"
            )
            sent += 1

        except Exception as error:
            failed += 1

            error_text = str(error).lower()

            if (
                "bot was blocked" in error_text
                or "user is deactivated" in error_text
                or "chat not found" in error_text
            ):
                blocked += 1

        await asyncio.sleep(ADMIN_BROADCAST_DELAY)

    await admin_reply(
        message,
        "📢 <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: <b>{len(user_ids)}</b>\n"
        f"✅ Доставлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"🚫 Недоступных аккаунтов: <b>{blocked}</b>"
    )


# ------------------------------------------------------------
# АДМИН: @СЕТ_КУРС ЧИСЛО
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@сет_курс\s+\d+(?:\.\d+)?$"))
async def admin_set_rate_handler(message: Message):
    global TOKEN_TO_TNC_RATE

    if not is_admin(message.from_user.id):
        return

    try:
        new_rate = float(message.text.split()[1])
    except (IndexError, ValueError):
        await admin_reply(
            message,
            "❌ Использование: <code>@сет_курс ЧИСЛО</code>"
        )
        return

    if not math.isfinite(new_rate) or new_rate <= 0:
        await admin_reply(message, "❌ Курс должен быть положительным числом.")
        return

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ('token_to_tnc_rate', ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value
                """,
                (str(new_rate),)
            )
            await db.commit()

    TOKEN_TO_TNC_RATE = new_rate

    await admin_reply(
        message,
        "✅ <b>КУРС ОБНОВЛЁН</b>\n\n"
        f"Новый курс: <b>1 TNC = {new_rate:,.8f} TOKENS</b>"
    )


# ------------------------------------------------------------
# АДМИН: @ДОЖДЬ СУММА
# ------------------------------------------------------------

@dp.message(F.text.regexp(r"(?i)^@дождь\s+\d+$"))
async def admin_rain_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    if message.chat.type not in ("group", "supergroup"):
        await admin_reply(
            message,
            "❌ Команда @дождь работает только в группах."
        )
        return

    try:
        amount = int(message.text.split()[1])
    except (IndexError, ValueError):
        await admin_reply(
            message,
            "❌ Использование: <code>@дождь СУММА</code>"
        )
        return

    if amount <= 0:
        await admin_reply(message, "❌ Сумма должна быть больше нуля.")
        return

    cutoff = (
        datetime.now() - timedelta(hours=24)
    ).isoformat(timespec="seconds")

    rows = await db_fetchall(
        """
        SELECT DISTINCT user_id
        FROM game_log
        WHERE created_at >= ?
          AND user_id IN (
              SELECT user_id FROM users
              WHERE is_banned = 0
          )
        """,
        (cutoff,)
    )

    participants = [int(row[0]) for row in rows]

    if not participants:
        await admin_reply(
            message,
            "🌧 За последние 24 часа в этом боте никто не играл."
        )
        return

    if amount < len(participants):
        await admin_reply(
            message,
            "❌ Суммы недостаточно, чтобы каждый участник получил "
            "хотя бы 1 TOKENS.\n"
            f"Участников: {len(participants)}"
        )
        return

    each = amount // len(participants)
    remainder = amount % len(participants)

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for index, user_id in enumerate(participants):
                reward = each + (1 if index < remainder else 0)

                await db.execute(
                    """
                    UPDATE users
                    SET balance = COALESCE(balance, 0) + ?
                    WHERE user_id = ?
                    """,
                    (reward, user_id)
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description)
                    VALUES (?, ?, 'TOKENS', 'admin_rain', ?)
                    """,
                    (
                        user_id,
                        reward,
                        f"Дождь в чате {message.chat.id}"
                    )
                )

            await db.commit()

    await message.answer(
        "🌧 <b>ДОЖДЬ TOKENS ЗАВЕРШЁН!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Участников: <b>{len(participants)}</b>\n"
        f"💰 Общая сумма: <b>{amount:,} TOKENS</b>\n"
        f"🎁 На каждого: <b>{each:,} TOKENS</b>\n"
        f"✨ Остаток распределён между первыми {remainder} участниками."
    )


# ------------------------------------------------------------
# VIP-КЕШБЭК
# ------------------------------------------------------------

async def get_daily_vip_losses(start_time: str, end_time: str):
    """
    Рассчитывает чистые проигрыши VIP-пользователей за период.

    Для каждой игры проигрыш считается как max(ставка - выигрыш, 0).
    """
    rows = await db_fetchall(
        """
        SELECT
            g.user_id,
            SUM(
                CASE
                    WHEN COALESCE(g.bet, 0) > COALESCE(g.win, 0)
                    THEN COALESCE(g.bet, 0) - COALESCE(g.win, 0)
                    ELSE 0
                END
            ) AS losses
        FROM game_log g
        INNER JOIN users u ON u.user_id = g.user_id
        WHERE u.is_vip = 1
          AND g.created_at >= ?
          AND g.created_at < ?
        GROUP BY g.user_id
        """,
        (start_time, end_time)
    )

    return rows


async def process_vip_cashback(start_time: str, end_time: str):
    """Начисление 2.5% от проигрышей VIP за указанный период."""
    rows = await get_daily_vip_losses(start_time, end_time)

    cashback_total = 0
    users_rewarded = 0

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for user_id, losses in rows:
                losses = int(losses or 0)

                cashback = int(
                    math.floor(losses * VIP_CASHBACK_PERCENT)
                )

                if cashback <= 0:
                    continue

                await db.execute(
                    """
                    UPDATE users
                    SET balance = COALESCE(balance, 0) + ?
                    WHERE user_id = ?
                      AND is_vip = 1
                    """,
                    (cashback, user_id)
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description)
                    VALUES (?, ?, 'TOKENS', 'vip_cashback', ?)
                    """,
                    (
                        user_id,
                        cashback,
                        f"VIP-кешбэк 2.5% за период {start_time} — {end_time}"
                    )
                )

                cashback_total += cashback
                users_rewarded += 1

            await db.commit()

    logger.info(
        "VIP cashback complete: users=%s total=%s",
        users_rewarded,
        cashback_total
    )

    return users_rewarded, cashback_total


async def vip_cashback_scheduler():
    """
    Фоновая задача:
    - ожидает ближайшие 00:00;
    - рассчитывает проигрыши за предыдущие сутки;
    - начисляет VIP-кешбэк;
    - повторяет цикл ежедневно.
    """
    while True:
        now = datetime.now()
        tomorrow = now.date() + timedelta(days=1)

        next_midnight = datetime.combine(
            tomorrow,
            datetime.min.time()
        )

        seconds_until_midnight = (
            next_midnight - now
        ).total_seconds()

        await asyncio.sleep(max(1, seconds_until_midnight))

        current_day = datetime.now().date()
        previous_day = current_day - timedelta(days=1)

        start_time = datetime.combine(
            previous_day,
            datetime.min.time()
        ).isoformat(timespec="seconds")

        end_time = datetime.combine(
            current_day,
            datetime.min.time()
        ).isoformat(timespec="seconds")

        try:
            rewarded, total = await process_vip_cashback(
                start_time,
                end_time
            )

            logger.info(
                "VIP cashback: %s users, %s TOKENS",
                rewarded,
                total
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception("Ошибка фонового VIP-кешбэка")


# ------------------------------------------------------------
# ЗАГРУЗКА КУРСА ИЗ БАЗЫ
# ------------------------------------------------------------

async def load_token_rate():
    global TOKEN_TO_TNC_RATE

    row = await db_fetchone(
        """
        SELECT value
        FROM settings
        WHERE key = 'token_to_tnc_rate'
        """
    )

    if row:
        try:
            rate = float(row[0])

            if math.isfinite(rate) and rate > 0:
                TOKEN_TO_TNC_RATE = rate

        except (TypeError, ValueError):
            logger.exception("Не удалось загрузить курс TOKENS/TNC")


# ------------------------------------------------------------
# КОРРЕКТНОЕ ЗАВЕРШЕНИЕ
# ------------------------------------------------------------

async def shutdown_application(cashback_task=None):
    """Останавливает фоновые задачи, бота и соединения."""

    if cashback_task is not None:
        cashback_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await cashback_task

    with contextlib.suppress(Exception):
        await bot.session.close()

    logger.info("TOKENS bot shutdown complete")


# ------------------------------------------------------------
# ГЛАВНАЯ ФУНКЦИЯ
# ------------------------------------------------------------

async def main():
    cashback_task = None

    try:
        logger.info("Запуск TOKENS bot...")

        # 1. Инициализация базы данных.
        await init_db()

        # 2. Загрузка сохранённого курса.
        await load_token_rate()

        # 3. Запуск aiohttp-сервера для API и Mini App.
        web_runner = await serve_webapp()

        logger.info(
            "Web server started on port %s",
            PORT
        )

        # 4. Запуск ежедневного VIP-кешбэка.
        cashback_task = asyncio.create_task(
            vip_cashback_scheduler(),
            name="vip_cashback_scheduler"
        )

        # 5. Запуск Telegram-бота.
        logger.info("Telegram polling started")

        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types()
            )

        finally:
            # Останавливаем HTTP-сервер.
            with contextlib.suppress(Exception):
                await web_runner.cleanup()

    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")

    except asyncio.CancelledError:
        logger.info("Главная задача отменена")
        raise

    except Exception:
        logger.exception("Критическая ошибка при запуске TOKENS bot")
        raise

    finally:
        await shutdown_application(cashback_task)


# ------------------------------------------------------------
# ЗАПУСК
# ------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())