import os
import re
import io
import json
import hmac
import html
import math
import time
import uuid
import asyncio
import hashlib
import logging
import secrets
import contextlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl
from typing import Optional

import aiosqlite
from aiohttp import web

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    WebAppInfo,
    InputMediaPhoto,
)

# ============================================================
# FSM: КАПЧА
# ============================================================

class CaptchaState(StatesGroup):
    waiting = State()


# ============================================================
# ОКРУЖЕНИЕ И НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "")
PORT = int(os.getenv("PORT", "10000"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "tokenplays").lstrip("@")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

DATABASE_PATH = os.getenv("DATABASE_PATH", "tokens.db")

TOKEN_TO_TNC_RATE = 50000.0
START_BONUS = 5000
CAPTCHA_ATTEMPTS = 3
CAPTCHA_BAN_HOURS = 12

BONUS_AMOUNT = 2500
BONUS_COOLDOWN_HOURS = 12

VIP_CASHBACK_PERCENT = 0.025

PRIVATE_ERROR_DELETE_SECONDS = 30
GAME_DELETE_SECONDS = 15
GROUP_REPLY_DELETE_SECONDS = 60

MAX_BALANCE = 10**15

ROULETTE_DURATION = 30
ROULETTE_GIF = "roulette.gif"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DATABASE_LOCK = asyncio.Lock()

roulette_locks = {}
roulette_rounds = {}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID and int(user_id) == ADMIN_ID)


def is_group(message: Message) -> bool:
    return message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_tokens(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


async def db_execute(query: str, params=()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.lastrowid


async def db_fetchone(query: str, params=()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchone()


async def db_fetchall(query: str, params=()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchall()


async def add_transaction(
    user_id: int,
    amount: int,
    transaction_type: str,
    description: str = "",
    currency: str = "TOKENS",
):
    await db_execute(
        """
        INSERT INTO transactions
        (user_id, amount, currency, transaction_type, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            amount,
            currency,
            transaction_type,
            description,
            now_iso(),
        ),
    )


async def change_balance(
    user_id: int,
    amount: int,
    transaction_type: str,
    description: str = "",
):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET balance = MAX(0, MIN(?, COALESCE(balance, 0) + ?))
                WHERE user_id = ?
                """,
                (MAX_BALANCE, amount, user_id),
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description, created_at)
                VALUES (?, ?, 'TOKENS', ?, ?, ?)
                """,
                (
                    user_id,
                    amount,
                    transaction_type,
                    description,
                    now_iso(),
                ),
            )
            await db.commit()


async def delete_later(message: Message, seconds: int):
    await asyncio.sleep(seconds)
    with contextlib.suppress(Exception):
        await message.delete()


async def send_temporary_message(
    chat_id: int,
    text: str,
    seconds: int = GROUP_REPLY_DELETE_SECONDS,
    **kwargs,
):
    try:
        sent = await bot.send_message(chat_id, text, **kwargs)
        asyncio.create_task(delete_later(sent, seconds))
        return sent
    except Exception:
        logger.exception("Не удалось отправить временное сообщение")
        return None


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

async def init_db():
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    balance INTEGER NOT NULL DEFAULT 0,
                    balance_tnc REAL NOT NULL DEFAULT 0,
                    referrals INTEGER NOT NULL DEFAULT 0,
                    referral_id INTEGER,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    ban_until TEXT,
                    is_vip INTEGER NOT NULL DEFAULT 0,
                    last_bonus TEXT,
                    last_activity TEXT,
                    total_bet INTEGER NOT NULL DEFAULT 0,
                    total_win INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS game_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    game TEXT,
                    bet INTEGER NOT NULL DEFAULT 0,
                    win INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'TOKENS',
                    transaction_type TEXT,
                    description TEXT,
                    created_at TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bonus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    bonus_type TEXT,
                    created_at TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS roulette_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    bet_type TEXT NOT NULL,
                    bet_value TEXT NOT NULL,
                    round_id TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS roulette_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    round_id TEXT,
                    number INTEGER,
                    color TEXT,
                    created_at TEXT
                )
                """
            )

            # Миграции для старых баз данных.
            migrations = {
                "users": {
                    "balance_tnc": "REAL NOT NULL DEFAULT 0",
                    "referrals": "INTEGER NOT NULL DEFAULT 0",
                    "referral_id": "INTEGER",
                    "is_banned": "INTEGER NOT NULL DEFAULT 0",
                    "ban_until": "TEXT",
                    "is_vip": "INTEGER NOT NULL DEFAULT 0",
                    "last_bonus": "TEXT",
                    "last_activity": "TEXT",
                    "total_bet": "INTEGER NOT NULL DEFAULT 0",
                    "total_win": "INTEGER NOT NULL DEFAULT 0",
                    "created_at": "TEXT",
                },
                "game_log": {
                    "game": "TEXT",
                    "bet": "INTEGER NOT NULL DEFAULT 0",
                    "win": "INTEGER NOT NULL DEFAULT 0",
                    "created_at": "TEXT",
                },
                "transactions": {
                    "currency": "TEXT NOT NULL DEFAULT 'TOKENS'",
                    "transaction_type": "TEXT",
                    "description": "TEXT",
                    "created_at": "TEXT",
                },
                "bonus": {
                    "bonus_type": "TEXT",
                    "created_at": "TEXT",
                },
                "roulette_bets": {
                    "chat_id": "INTEGER",
                    "round_id": "TEXT",
                    "bet_type": "TEXT",
                    "bet_value": "TEXT",
                    "created_at": "TEXT",
                },
            }

            for table, columns in migrations.items():
                cursor = await db.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in await cursor.fetchall()}

                for column, definition in columns.items():
                    if column not in existing:
                        await db.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )

            await db.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ('token_to_tnc_rate', ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (str(TOKEN_TO_TNC_RATE),),
            )

            await db.commit()

    logger.info("База данных инициализирована")


# ============================================================
# КАПЧА: ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ
# ============================================================

def get_font(size: int):
    candidates = [
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    return ImageFont.load_default()


def generate_captcha_image(code: str) -> bytes:
    width, height = 320, 130

    image = Image.new("RGB", (width, height), (17, 24, 39))
    draw = ImageDraw.Draw(image)

    for _ in range(20):
        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)

        draw.line(
            (x1, y1, x2, y2),
            fill=(35, 50, 75),
            width=2,
        )

    font = get_font(58)

    for index, digit in enumerate(code):
        x = 55 + index * 58
        y = 24 + secrets.randbelow(18)

        draw.text(
            (x, y),
            digit,
            font=font,
            fill=(
                secrets.randbelow(100) + 155,
                secrets.randbelow(100) + 155,
                secrets.randbelow(100) + 155,
            ),
        )

    for _ in range(50):
        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        draw.ellipse(
            (x, y, x + 2, y + 2),
            fill=(90, 110, 140),
        )

    image = image.filter(ImageFilter.GaussianBlur(0.25))

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def send_new_captcha(
    message: Message,
    state: FSMContext,
    attempts: int,
):
    code = "".join(str(secrets.randbelow(10)) for _ in range(4))

    await state.set_state(CaptchaState.waiting)
    await state.update_data(
        captcha_code=code,
        attempts=attempts,
        captcha_message_id=None,
    )

    image = generate_captcha_image(code)

    sent = await message.answer_photo(
        BufferedInputFile(image, filename="captcha.png"),
        caption=(
            "🔐 <b>Проверка безопасности</b>\n\n"
            "Введите 4 цифры с картинки обычным сообщением.\n"
            f"Осталось попыток: <b>{attempts}</b>"
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )

    await state.update_data(captcha_message_id=sent.message_id)


# ============================================================
# ПОЛЬЗОВАТЕЛИ И РЕФЕРАЛЬНАЯ СИСТЕМА
# ============================================================

def parse_referral_id(text: str) -> Optional[int]:
    if not text:
        return None

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None

    payload = parts[1].strip()

    if payload.startswith("ref_"):
        payload = payload[4:]

    if payload.isdigit():
        return int(payload)

    return None


async def get_user(user_id: int):
    return await db_fetchone(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )


async def register_user(user, referral_id: Optional[int] = None):
    existing = await get_user(user.id)

    if existing:
        await db_execute(
            """
            UPDATE users
            SET username = ?, first_name = ?, last_activity = ?
            WHERE user_id = ?
            """,
            (
                user.username,
                user.first_name,
                now_iso(),
                user.id,
            ),
        )
        return False

    valid_referral = None

    if referral_id and referral_id != user.id:
        inviter = await get_user(referral_id)
        if inviter:
            valid_referral = referral_id

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, balance,
                    balance_tnc, referrals, referral_id,
                    is_banned, is_vip, created_at, last_activity
                )
                VALUES (?, ?, ?, ?, 0, 0, ?, 0, 0, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.first_name,
                    START_BONUS,
                    valid_referral,
                    now_iso(),
                    now_iso(),
                ),
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description, created_at)
                VALUES (?, ?, 'TOKENS', 'start_bonus', 'Бонус за регистрацию', ?)
                """,
                (user.id, START_BONUS, now_iso()),
            )

            if valid_referral:
                await db.execute(
                    """
                    UPDATE users
                    SET referrals = referrals + 1,
                        balance = balance + 5000
                    WHERE user_id = ?
                    """,
                    (valid_referral,),
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, 5000, 'TOKENS', 'referral', 'Приглашение пользователя', ?)
                    """,
                    (valid_referral, now_iso()),
                )

            await db.commit()

    return True


async def check_ban(user_id: int) -> bool:
    row = await db_fetchone(
        "SELECT is_banned, ban_until FROM users WHERE user_id = ?",
        (user_id,),
    )

    if not row or not row[0]:
        return False

    ban_until = row[1]

    if ban_until:
        try:
            expiry = datetime.fromisoformat(ban_until)
            if datetime.now() >= expiry:
                await db_execute(
                    """
                    UPDATE users
                    SET is_banned = 0, ban_until = NULL
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                return False
        except ValueError:
            pass

    return True


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🚀 Открыть TOKENS App",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ],
            [
                KeyboardButton(text="🎁 Бонус"),
                KeyboardButton(text="👤 Профиль"),
            ],
            [
                KeyboardButton(text="🏆 Топ"),
                KeyboardButton(text="🔗 Рефералка"),
            ],
            [
                KeyboardButton(text="💎 Крипта"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def back_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:home",
                )
            ]
        ]
    )


def crypto_inline_keyboard():
    buttons = []

    if WEBAPP_URL:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🚀 Открыть App",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="menu:home",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================================================
# ПРОФИЛЬ И МЕНЮ
# ============================================================

async def profile_text(user_id: int) -> str:
    row = await db_fetchone(
        """
        SELECT username, first_name, balance, balance_tnc,
               referrals, is_vip
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    if not row:
        return "Профиль не найден."

    username, first_name, balance, tnc, referrals, vip = row

    stats = await db_fetchone(
        """
        SELECT COUNT(*), COALESCE(SUM(bet), 0), COALESCE(SUM(win), 0)
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,),
    )

    games, total_bet, total_win = stats or (0, 0, 0)

    return (
        "👤 <b>ВАШ ПРОФИЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Имя: <b>{html.escape(first_name or 'Игрок')}</b>\n"
        f"Username: @{html.escape(username or 'не указан')}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"💰 Баланс: <b>{format_tokens(balance or 0)} TOKENS</b>\n"
        f"💎 Баланс: <b>{float(tnc or 0):.8f} TNC</b>\n"
        f"👥 Рефералов: <b>{referrals or 0}</b>\n"
        f"⭐ VIP: <b>{'Да' if vip else 'Нет'}</b>\n\n"
        f"🎮 Игр: <b>{games}</b>\n"
        f"📉 Поставлено: <b>{format_tokens(total_bet or 0)}</b>\n"
        f"📈 Выиграно: <b>{format_tokens(total_win or 0)}</b>"
    )


async def show_home(callback: CallbackQuery):
    text = (
        "🚀 <b>TOKENS</b>\n\n"
        "Добро пожаловать в игровую экономику TOKENS!\n\n"
        "Выберите нужный раздел ниже."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="menu:games",
                ),
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="menu:profile",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💎 Крипта",
                    callback_data="menu:crypto",
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="menu:bonus",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Топ",
                    callback_data="menu:top",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    if await check_ban(message.from_user.id):
        await message.answer(
            "🚫 Ваш аккаунт временно заблокирован.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    is_new = await register_user(
        message.from_user,
        parse_referral_id(message.text),
    )

    if is_new:
        await send_new_captcha(
            message,
            state,
            CAPTCHA_ATTEMPTS,
        )
        return

    await message.answer(
        "🚀 <b>Добро пожаловать в TOKENS!</b>",
        reply_markup=main_reply_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# КАПЧА: ПРАВИЛЬНЫЙ ОБРАБОТЧИК ВВОДА
# ============================================================

@dp.message(CaptchaState.waiting, F.text)
async def captcha_input_handler(
    message: Message,
    state: FSMContext,
):
    data = await state.get_data()

    captcha_code = data.get("captcha_code")
    attempts = safe_int(data.get("attempts"), CAPTCHA_ATTEMPTS)
    captcha_message_id = data.get("captcha_message_id")

    if not captcha_code:
        await state.clear()
        await message.answer(
            "Сессия проверки истекла. Нажмите /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Удаляем введённый пользователем текст с цифрами.
    with contextlib.suppress(Exception):
        await message.delete()

    if message.text.strip() == str(captcha_code):
        if captcha_message_id:
            with contextlib.suppress(Exception):
                await bot.delete_message(
                    message.chat.id,
                    captcha_message_id,
                )

        await state.clear()

        await change_balance(
            message.from_user.id,
            START_BONUS,
            "captcha_reward",
            "Награда за успешное прохождение капчи",
        )

        await message.answer(
            "✅ <b>Капча пройдена!</b>\n\n"
            f"🎁 Вам начислено <b>{format_tokens(START_BONUS)} TOKENS</b>.\n"
            "Добро пожаловать!",
            reply_markup=main_reply_keyboard(),
            parse_mode="HTML",
        )
        return

    # Неправильный ответ: удаляем старую капчу.
    if captcha_message_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(
                message.chat.id,
                captcha_message_id,
            )

    attempts -= 1

    if attempts <= 0:
        ban_until = (
            datetime.now() + timedelta(hours=CAPTCHA_BAN_HOURS)
        ).isoformat(timespec="seconds")

        await db_execute(
            """
            UPDATE users
            SET is_banned = 1, ban_until = ?
            WHERE user_id = ?
            """,
            (ban_until, message.from_user.id),
        )

        await state.clear()

        await message.answer(
            "🚫 <b>Проверка не пройдена.</b>\n"
            f"Вы заблокированы на {CAPTCHA_BAN_HOURS} часов.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"❌ Неверный код. Осталось попыток: {attempts}.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await send_new_captcha(
        message,
        state,
        attempts,
    )


@dp.message(CaptchaState.waiting)
async def captcha_non_text_handler(message: Message):
    with contextlib.suppress(Exception):
        await message.delete()

    await message.answer(
        "Введите именно 4 цифры с изображения."
    )


# ============================================================
# ОБРАБОТЧИКИ REPLY-МЕНЮ
# ============================================================

@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):
    if await check_ban(message.from_user.id):
        return

    text = await profile_text(message.from_user.id)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )


@dp.message(F.text == "💎 Крипта")
async def crypto_handler(message: Message):
    if await check_ban(message.from_user.id):
        return

    await message.answer(
        "💎 <b>TOKENS CRYPTO</b>\n\n"
        f"Курс обмена:\n"
        f"<b>1 TNC = {TOKEN_TO_TNC_RATE:,.0f} TOKENS</b>\n\n"
        "Обмен доступен в TOKENS App.",
        reply_markup=crypto_inline_keyboard(),
        parse_mode="HTML",
    )


@dp.message(F.text == "🚀 Открыть TOKENS App")
async def open_app_handler(message: Message):
    if not WEBAPP_URL:
        await message.answer("Mini App пока не настроен.")
        return

    await message.answer(
        "🚀 Откройте TOKENS App:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть TOKENS App",
                        web_app=WebAppInfo(url=WEBAPP_URL),
                    )
                ]
            ]
        ),
    )


# ============================================================
# БОНУС
# ============================================================

@dp.message(F.text == "🎁 Бонус")
async def bonus_handler(message: Message):
    if await check_ban(message.from_user.id):
        return

    await message.answer(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        f"Стандартный бонус: <b>{BONUS_AMOUNT:,} TOKENS</b>\n"
        f"Перезарядка: <b>{BONUS_COOLDOWN_HOURS} часов</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎁 Забрать бонус",
                        callback_data="bonus:claim",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "bonus:claim")
async def bonus_claim_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if await check_ban(user_id):
        await callback.answer("Аккаунт заблокирован.", show_alert=True)
        return

    row = await db_fetchone(
        "SELECT last_bonus FROM users WHERE user_id = ?",
        (user_id,),
    )

    last_bonus = row[0] if row else None

    if last_bonus:
        try:
            last_time = datetime.fromisoformat(last_bonus)
            next_time = last_time + timedelta(hours=BONUS_COOLDOWN_HOURS)

            if datetime.now() < next_time:
                remaining = next_time - datetime.now()
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)

                await callback.answer(
                    f"Бонус будет доступен через {hours} ч. {minutes} мин.",
                    show_alert=True,
                )
                return
        except ValueError:
            pass

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance + ?, last_bonus = ?
                WHERE user_id = ?
                  AND (
                      last_bonus IS NULL
                      OR datetime(last_bonus, '+' || ? || ' hours') <= datetime('now', 'localtime')
                  )
                """,
                (
                    BONUS_AMOUNT,
                    now_iso(),
                    user_id,
                    BONUS_COOLDOWN_HOURS,
                ),
            )

            if cursor.rowcount == 0:
                await db.rollback()
                await callback.answer(
                    "Бонус уже получен. Попробуйте позже.",
                    show_alert=True,
                )
                return

            await db.execute(
                """
                INSERT INTO bonus (user_id, amount, bonus_type, created_at)
                VALUES (?, ?, 'daily', ?)
                """,
                (user_id, BONUS_AMOUNT, now_iso()),
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description, created_at)
                VALUES (?, ?, 'TOKENS', 'bonus', 'Получение бонуса', ?)
                """,
                (user_id, BONUS_AMOUNT, now_iso()),
            )

            await db.commit()

    await callback.answer("Бонус начислен!", show_alert=True)

    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            f"🎉 Вам начислено <b>{BONUS_AMOUNT:,} TOKENS</b>!",
            parse_mode="HTML",
            reply_markup=back_inline_keyboard(),
        )


# ============================================================
# ТОП ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

async def get_top_text():
    rows = await db_fetchall(
        """
        SELECT user_id, first_name, username, balance
        FROM users
        WHERE is_banned = 0
        ORDER BY balance DESC
        LIMIT 10
        """
    )

    if not rows:
        return "🏆 Пока нет пользователей в рейтинге."

    result = ["🏆 <b>ТОП-10 TOKENS</b>\n"]

    for index, row in enumerate(rows, start=1):
        user_id, first_name, username, balance = row
        name = first_name or username or str(user_id)

        result.append(
            f"{index}. {html.escape(name)} — "
            f"<b>{format_tokens(balance or 0)} TOKENS</b>"
        )

    return "\n".join(result)


@dp.message(F.text == "🏆 Топ")
async def top_handler(message: Message):
    await message.answer(
        await get_top_text(),
        parse_mode="HTML",
    )


@dp.message(F.text == "🔗 Рефералка")
async def referral_handler(message: Message):
    me = await bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"

    row = await db_fetchone(
        "SELECT referrals FROM users WHERE user_id = ?",
        (message.from_user.id,),
    )

    referrals = row[0] if row else 0

    await message.answer(
        "🔗 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено пользователей: <b>{referrals}</b>\n"
        "Награда за нового пользователя: <b>5000 TOKENS</b>.",
        parse_mode="HTML",
    )


# ============================================================
# INLINE-МЕНЮ: РЕДАКТИРОВАНИЕ ТЕКУЩЕГО СООБЩЕНИЯ
# ============================================================

@dp.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery):
    section = callback.data.split(":", 1)[1]

    if section == "home":
        await show_home(callback)

    elif section == "games":
        await callback.message.edit_text(
            "🎮 <b>ИГРЫ TOKENS</b>\n\n"
            "Игры доступны только в групповых чатах.\n"
            "Добавьте бота в группу и используйте команды:\n\n"
            "🎲 кости\n"
            "🎯 дартс\n"
            "🎳 боулинг\n"
            "🏀 баскет\n"
            "⚽ футбол",
            parse_mode="HTML",
            reply_markup=back_inline_keyboard(),
        )

    elif section == "profile":
        await callback.message.edit_text(
            await profile_text(callback.from_user.id),
            parse_mode="HTML",
            reply_markup=back_inline_keyboard(),
        )

    elif section == "crypto":
        await callback.message.edit_text(
            "💎 <b>TOKENS CRYPTO</b>\n\n"
            f"Курс: <b>1 TNC = {TOKEN_TO_TNC_RATE:,.0f} TOKENS</b>\n"
            "Обмен TOKENS и TNC доступен в Mini App.",
            parse_mode="HTML",
            reply_markup=crypto_inline_keyboard(),
        )

    elif section == "bonus":
        await callback.message.edit_text(
            "🎁 <b>БОНУС</b>\n\n"
            f"Доступно: <b>{BONUS_AMOUNT:,} TOKENS</b>\n"
            f"Перезарядка: {BONUS_COOLDOWN_HOURS} часов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🎁 Забрать",
                            callback_data="bonus:claim",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data="menu:home",
                        )
                    ],
                ]
            ),
        )

    elif section == "top":
        await callback.message.edit_text(
            await get_top_text(),
            parse_mode="HTML",
            reply_markup=back_inline_keyboard(),
        )

    await callback.answer()


# ============================================================
# ИГРЫ: ОБЩИЕ ФУНКЦИИ
# ============================================================

async def log_game(
    user_id: int,
    game: str,
    bet: int,
    win: int,
):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO game_log (user_id, game, bet, win, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, game, bet, win, now_iso()),
            )

            await db.execute(
                """
                UPDATE users
                SET total_bet = total_bet + ?,
                    total_win = total_win + ?,
                    last_activity = ?
                WHERE user_id = ?
                """,
                (bet, win, now_iso(), user_id),
            )

            await db.commit()


async def play_dice(
    message: Message,
    emoji: str,
    game_name: str,
):
    if not is_group(message):
        sent = await message.answer(
            f"🎮 Игры доступны только в группах.\n"
            f"Поддержка: @{SUPPORT_USERNAME}"
        )
        asyncio.create_task(
            delete_later(sent, PRIVATE_ERROR_DELETE_SECONDS)
        )
        return

    if await check_ban(message.from_user.id):
        return

    user_id = message.from_user.id
    balance = await db_fetchone(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
    )

    if not balance or int(balance[0] or 0) <= 0:
        sent = await message.reply("❌ Недостаточно TOKENS.")
        asyncio.create_task(delete_later(sent, GAME_DELETE_SECONDS))
        return

    bet = min(100, int(balance[0]))

    await change_balance(
        user_id,
        -bet,
        "game_bet",
        f"Ставка в игре {game_name}",
    )

    dice_message = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3)

    value = dice_message.dice.value

    if game_name in ("Кости", "Дартс", "Боулинг"):
        multiplier = 2 if value >= 4 else 0
    else:
        multipliers = {
            1: 0,
            2: 1,
            3: 1.5,
            4: 1.8,
            5: 2,
        }
        multiplier = multipliers.get(value, 0)

    winnings = int(bet * multiplier)

    if winnings:
        await change_balance(
            user_id,
            winnings,
            "game_win",
            f"Выигрыш в игре {game_name}",
        )

    await log_game(
        user_id,
        game_name,
        bet,
        winnings,
    )

    net = winnings - bet

    result = await message.answer(
        f"🎮 <b>{game_name}</b>\n\n"
        f"Игрок: {html.escape(message.from_user.full_name)}\n"
        f"Результат: <b>{value}</b>\n"
        f"Ставка: <b>{format_tokens(bet)} TOKENS</b>\n"
        f"Множитель: <b>x{multiplier}</b>\n"
        f"Выплата: <b>{format_tokens(winnings)} TOKENS</b>\n"
        f"Итог: <b>{'+' if net >= 0 else ''}{format_tokens(net)} TOKENS</b>",
        parse_mode="HTML",
    )

    asyncio.create_task(delete_later(result, GAME_DELETE_SECONDS))
    asyncio.create_task(delete_later(dice_message, GAME_DELETE_SECONDS))


# ============================================================
# ИГРОВЫЕ КОМАНДЫ
# ============================================================

@dp.message(F.text.regexp(r"(?i)^кости$"))
async def dice_game_handler(message: Message):
    await play_dice(message, "🎲", "Кости")


@dp.message(F.text.regexp(r"(?i)^дартс$"))
async def darts_game_handler(message: Message):
    await play_dice(message, "🎯", "Дартс")


@dp.message(F.text.regexp(r"(?i)^боулинг$"))
async def bowling_game_handler(message: Message):
    await play_dice(message, "🎳", "Боулинг")


@dp.message(F.text.regexp(r"(?i)^баскет$"))
async def basketball_game_handler(message: Message):
    await play_dice(message, "🏀", "Баскет")


@dp.message(F.text.regexp(r"(?i)^футбол$"))
async def football_game_handler(message: Message):
    await play_dice(message, "⚽", "Футбол")


# ============================================================
# РУЛЕТКА: ПАРСЕР СТАВОК БЕЗ EVAL
# ============================================================

ROULETTE_RED = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
}

ROULETTE_BLACK = {
    2, 4, 6, 8, 10, 11, 13, 15, 17,
    20, 22, 24, 26, 28, 29, 31, 33, 35,
}


def roulette_color(number: int) -> str:
    if number == 0:
        return "green"
    if number in ROULETTE_RED:
        return "red"
    return "black"


def parse_roulette_bets(text: str):
    """
    Форматы:
      к 1000
      10-20 500
      500 10-30 30-34 23-24 24-35

    Возвращает список словарей.
    """
    parts = text.lower().strip().split()

    if len(parts) < 2:
        raise ValueError("Недостаточно аргументов")

    bets = []

    if parts[0] in ("к", "красное", "черное", "чёрное", "зеленое", "зелёное"):
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError("Формат: к 1000")

        amount = int(parts[1])

        if amount <= 0:
            raise ValueError("Ставка должна быть положительной")

        color = {
            "к": "red",
            "красное": "red",
            "черное": "black",
            "чёрное": "black",
            "зеленое": "green",
            "зелёное": "green",
        }[parts[0]]

        return [
            {
                "type": "color",
                "value": color,
                "amount": amount,
            }
        ]

    if len(parts) == 2 and re.fullmatch(r"\d+-\d+", parts[0]):
        match = re.fullmatch(r"(\d+)-(\d+)", parts[0])

        start = int(match.group(1))
        end = int(match.group(2))
        amount = int(parts[1])

        if not (0 <= start <= 36 and 0 <= end <= 36):
            raise ValueError("Числа должны быть от 0 до 36")

        if start > end:
            raise ValueError("Начало диапазона больше конца")

        if amount <= 0:
            raise ValueError("Ставка должна быть положительной")

        return [
            {
                "type": "range",
                "value": [start, end],
                "amount": amount,
            }
        ]

    if len(parts) >= 3 and parts[0].isdigit():
        amount = int(parts[0])

        if amount <= 0:
            raise ValueError("Ставка должна быть положительной")

        for item in parts[1:]:
            match = re.fullmatch(r"(\d+)-(\d+)", item)

            if not match:
                raise ValueError(f"Некорректный диапазон: {item}")

            start = int(match.group(1))
            end = int(match.group(2))

            if not (0 <= start <= 36 and 0 <= end <= 36):
                raise ValueError("Числа должны быть от 0 до 36")

            if start > end:
                raise ValueError("Некорректный диапазон")

            bets.append(
                {
                    "type": "range",
                    "value": [start, end],
                    "amount": amount,
                }
            )

        return bets

    raise ValueError("Неизвестный формат ставки")


async def place_roulette_bets(
    message: Message,
    bets: list,
):
    user_id = message.from_user.id
    chat_id = message.chat.id

    total_amount = sum(item["amount"] for item in bets)

    balance_row = await db_fetchone(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
    )

    balance = int(balance_row[0] or 0) if balance_row else 0

    if balance < total_amount:
        await message.reply("❌ Недостаточно TOKENS для этой ставки.")
        return

    round_id = roulette_rounds.get(chat_id)

    if not round_id:
        round_id = "waiting"

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance - ?
                WHERE user_id = ? AND balance >= ?
                """,
                (total_amount, user_id, total_amount),
            )

            if cursor.rowcount == 0:
                await db.rollback()
                await message.reply("❌ Недостаточно TOKENS.")
                return

            for bet in bets:
                await db.execute(
                    """
                    INSERT INTO roulette_bets (
                        chat_id, user_id, amount, bet_type,
                        bet_value, round_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        user_id,
                        bet["amount"],
                        bet["type"],
                        json.dumps(bet["value"]),
                        round_id,
                        now_iso(),
                    ),
                )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description, created_at)
                VALUES (?, ?, 'TOKENS', 'roulette_bet', ?, ?)
                """,
                (
                    user_id,
                    -total_amount,
                    "Ставка в рулетке",
                    now_iso(),
                ),
            )

            await db.commit()

    await message.reply(
        f"🎰 Ставка принята: <b>{format_tokens(total_amount)} TOKENS</b>",
        parse_mode="HTML",
    )


@dp.message(F.text.regexp(r"(?i)^(?:к\s+\d+|\d+-\d+\s+\d+|\d+\s+\d+-\d+(?:\s+\d+-\d+)*)$"))
async def roulette_bet_handler(message: Message):
    if not is_group(message):
        sent = await message.answer(
            f"🎰 Рулетка доступна только в группах.\n"
            f"Поддержка: @{SUPPORT_USERNAME}"
        )
        asyncio.create_task(
            delete_later(sent, PRIVATE_ERROR_DELETE_SECONDS)
        )
        return

    if await check_ban(message.from_user.id):
        return

    try:
        bets = parse_roulette_bets(message.text)
        await place_roulette_bets(message, bets)
    except ValueError as error:
        await message.reply(f"❌ {html.escape(str(error))}")


# ============================================================
# РУЛЕТКА: ЗАПУСК И РЕЗУЛЬТАТ
# ============================================================

def roulette_bet_wins(bet: dict, number: int) -> bool:
    if bet["type"] == "color":
        return roulette_color(number) == bet["value"]

    if bet["type"] == "range":
        start, end = bet["value"]
        return start <= number <= end

    return False


async def settle_roulette(chat_id: int, round_id: str):
    rows = await db_fetchall(
        """
        SELECT id, user_id, amount, bet_type, bet_value
        FROM roulette_bets
        WHERE chat_id = ? AND round_id = ?
        """,
        (chat_id, round_id),
    )

    if not rows:
        return None

    number = secrets.randbelow(37)
    color = roulette_color(number)

    results = {}

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for bet_id, user_id, amount, bet_type, bet_value in rows:
                try:
                    value = json.loads(bet_value)
                except (TypeError, json.JSONDecodeError):
                    continue

                bet = {
                    "type": bet_type,
                    "value": value,
                }

                if roulette_bet_wins(bet, number):
                    if bet_type == "color":
                        multiplier = 2 if value != "green" else 14
                    else:
                        count = value[1] - value[0] + 1
                        multiplier = max(1, int(36 / count))

                    payout = int(amount * multiplier)

                    await db.execute(
                        """
                        UPDATE users
                        SET balance = balance + ?
                        WHERE user_id = ?
                        """,
                        (payout, user_id),
                    )

                    await db.execute(
                        """
                        INSERT INTO transactions
                        (user_id, amount, currency, transaction_type, description, created_at)
                        VALUES (?, ?, 'TOKENS', 'roulette_win', ?, ?)
                        """,
                        (
                            user_id,
                            payout,
                            f"Выигрыш рулетки: число {number}",
                            now_iso(),
                        ),
                    )

                    results[user_id] = results.get(user_id, 0) + payout

            await db.execute(
                """
                INSERT INTO roulette_history
                (chat_id, round_id, number, color, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, round_id, number, color, now_iso()),
            )

            await db.commit()

    return number, color, results


async def start_roulette(message: Message):
    chat_id = message.chat.id

    if not is_group(message):
        await message.answer(
            f"🎰 Рулетка доступна только в группах. @{SUPPORT_USERNAME}"
        )
        return

    lock = roulette_locks.setdefault(chat_id, asyncio.Lock())

    if lock.locked():
        await message.reply("⏳ Рулетка уже крутится. Дождитесь результата.")
        return

    async with lock:
        pending = await db_fetchone(
            """
            SELECT COUNT(*)
            FROM roulette_bets
            WHERE chat_id = ? AND round_id = 'waiting'
            """,
            (chat_id,),
        )

        if not pending or int(pending[0]) == 0:
            await message.reply("❌ Нет ставок. Рулетка отменена.")
            return

        round_id = uuid.uuid4().hex
        roulette_rounds[chat_id] = round_id

        async with DATABASE_LOCK:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    UPDATE roulette_bets
                    SET round_id = ?
                    WHERE chat_id = ? AND round_id = 'waiting'
                    """,
                    (round_id, chat_id),
                )
                await db.commit()

        await message.answer("🎰 <b>РУЛЕТКА ЗАПУЩЕНА!</b>", parse_mode="HTML")

        if os.path.exists(ROULETTE_GIF):
            with contextlib.suppress(Exception):
                animation = await message.answer_animation(
                    BufferedInputFile(
                        open(ROULETTE_GIF, "rb").read(),
                        filename="roulette.gif",
                    )
                )
                await asyncio.sleep(ROULETTE_DURATION)
                with contextlib.suppress(Exception):
                    await animation.delete()
        else:
            await asyncio.sleep(ROULETTE_DURATION)

        result = await settle_roulette(chat_id, round_id)

        if not result:
            await message.answer("❌ Ставок не найдено.")
            return

        number, color, winners = result

        color_name = {
            "red": "🔴 Красное",
            "black": "⚫ Чёрное",
            "green": "🟢 Зелёное",
        }[color]

        text = (
            "🎰 <b>РУЛЕТКА — РЕЗУЛЬТАТ</b>\n\n"
            f"Выпало: <b>{number}</b> — {color_name}\n\n"
        )

        if winners:
            text += "<b>Победители:</b>\n"

            for user_id, payout in winners.items():
                text += (
                    f"• <code>{user_id}</code> — "
                    f"<b>{format_tokens(payout)} TOKENS</b>\n"
                )
        else:
            text += "Победителей нет."

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔁 Повторить",
                        callback_data="roulette:repeat",
                    ),
                    InlineKeyboardButton(
                        text="✖️ Удвоить",
                        callback_data="roulette:double",
                    ),
                ]
            ]
        )

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


@dp.message(F.text.regexp(r"(?i)^старт$"))
async def roulette_start_handler(message: Message):
    await start_roulette(message)


@dp.callback_query(F.data.in_({"roulette:repeat", "roulette:double"}))
async def roulette_repeat_callback(callback: CallbackQuery):
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Доступно только в группах.", show_alert=True)
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    last_rows = await db_fetchall(
        """
        SELECT amount, bet_type, bet_value
        FROM roulette_bets
        WHERE chat_id = ? AND user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (chat_id, user_id),
    )

    if not last_rows:
        await callback.answer("У вас нет предыдущих ставок.", show_alert=True)
        return

    multiplier = 2 if callback.data == "roulette:double" else 1

    bets = []

    for amount, bet_type, bet_value in last_rows:
        bets.append(
            {
                "amount": int(amount) * multiplier,
                "type": bet_type,
                "value": json.loads(bet_value),
            }
        )

    total = sum(item["amount"] for item in bets)

    balance = await get_user_balance(user_id)

    if balance < total:
        await callback.answer("Недостаточно TOKENS.", show_alert=True)
        return

    synthetic_message = callback.message
    synthetic_message.from_user = callback.from_user

    await place_roulette_bets(synthetic_message, bets)
    await callback.answer("Ставки повторены.")


# ============================================================
# КРИПТО API: ПРОВЕРКА TELEGRAM INIT DATA
# ============================================================

def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = safe_int(parsed.get("auth_date"), 0)

        if not auth_date or time.time() - auth_date > 86400:
            return None

        user_data = json.loads(parsed.get("user", "{}"))

        if not user_data.get("id"):
            return None

        return user_data

    except Exception:
        logger.exception("Ошибка проверки Telegram initData")
        return None


async def read_init_data(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")

    if not init_data:
        try:
            body = await request.json()
            init_data = body.get("initData", "")
        except Exception:
            init_data = ""

    return validate_init_data(init_data)


# ============================================================
# КРИПТО API: /api/user
# ============================================================

async def api_user(request: web.Request):
    user_data = await read_init_data(request)

    if not user_data:
        return web.json_response(
            {"ok": False, "error": "invalid_init_data"},
            status=401,
        )

    user_id = int(user_data["id"])

    row = await db_fetchone(
        """
        SELECT user_id, username, first_name, balance,
               balance_tnc, is_vip, referrals
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    if not row:
        return web.json_response(
            {"ok": False, "error": "user_not_found"},
            status=404,
        )

    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": row[0],
                "username": row[1],
                "first_name": row[2],
                "balance": int(row[3] or 0),
                "balance_tnc": float(row[4] or 0),
                "is_vip": bool(row[5]),
                "referrals": int(row[6] or 0),
            },
            "rate": TOKEN_TO_TNC_RATE,
        }
    )


# ============================================================
# КРИПТО API: /api/swap
# ============================================================

async def api_swap(request: web.Request):
    user_data = await read_init_data(request)

    if not user_data:
        return web.json_response(
            {"ok": False, "error": "invalid_init_data"},
            status=401,
        )

    try:
        body = await request.json()
        direction = str(body.get("direction", "")).lower()
        amount = float(body.get("amount", 0))
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_request"},
            status=400,
        )

    if not math.isfinite(amount) or amount <= 0:
        return web.json_response(
            {"ok": False, "error": "invalid_amount"},
            status=400,
        )

    user_id = int(user_data["id"])

    if direction == "tokens_to_tnc":
        tokens = int(amount)

        if tokens <= 0:
            return web.json_response(
                {"ok": False, "error": "invalid_amount"},
                status=400,
            )

        tnc = tokens / TOKEN_TO_TNC_RATE

        async with DATABASE_LOCK:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    UPDATE users
                    SET balance = balance - ?,
                        balance_tnc = balance_tnc + ?
                    WHERE user_id = ? AND balance >= ?
                    """,
                    (tokens, tnc, user_id, tokens),
                )

                if cursor.rowcount == 0:
                    await db.rollback()
                    return web.json_response(
                        {"ok": False, "error": "insufficient_balance"},
                        status=400,
                    )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TOKENS', 'swap_out', 'Обмен TOKENS в TNC', ?)
                    """,
                    (user_id, -tokens, now_iso()),
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TNC', 'swap_in', 'Обмен TOKENS в TNC', ?)
                    """,
                    (user_id, tnc, now_iso()),
                )

                await db.commit()

    elif direction == "tnc_to_tokens":
        tnc = amount
        tokens = int(math.floor(tnc * TOKEN_TO_TNC_RATE))

        if tokens <= 0:
            return web.json_response(
                {"ok": False, "error": "amount_too_small"},
                status=400,
            )

        async with DATABASE_LOCK:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    """
                    UPDATE users
                    SET balance_tnc = balance_tnc - ?,
                        balance = balance + ?
                    WHERE user_id = ? AND balance_tnc >= ?
                    """,
                    (tnc, tokens, user_id, tnc),
                )

                if cursor.rowcount == 0:
                    await db.rollback()
                    return web.json_response(
                        {"ok": False, "error": "insufficient_balance"},
                        status=400,
                    )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TNC', 'swap_out', 'Обмен TNC в TOKENS', ?)
                    """,
                    (user_id, -tnc, now_iso()),
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TOKENS', 'swap_in', 'Обмен TNC в TOKENS', ?)
                    """,
                    (user_id, tokens, now_iso()),
                )

                await db.commit()

    else:
        return web.json_response(
            {"ok": False, "error": "invalid_direction"},
            status=400,
        )

    row = await db_fetchone(
        "SELECT balance, balance_tnc FROM users WHERE user_id = ?",
        (user_id,),
    )

    return web.json_response(
        {
            "ok": True,
            "balance": int(row[0] or 0),
            "balance_tnc": float(row[1] or 0),
            "rate": TOKEN_TO_TNC_RATE,
        }
    )


# ============================================================
# AIOHTTP: СТАТИКА И WEBAPP
# ============================================================

async def serve_webapp(request: web.Request):
    webapp_dir = os.path.abspath("webapp")
    index_path = os.path.join(webapp_dir, "index.html")

    if not os.path.isfile(index_path):
        return web.Response(
            text="TOKENS Mini App: index.html not found",
            status=404,
        )

    return web.FileResponse(index_path)


async def start_web_server():
    app = web.Application(client_max_size=1024 * 1024)

    app.router.add_get("/", serve_webapp)
    app.router.add_get("/webapp/", serve_webapp)
    app.router.add_get("/webapp/index.html", serve_webapp)

    webapp_dir = os.path.abspath("webapp")

    if os.path.isdir(webapp_dir):
        app.router.add_static(
            "/webapp/",
            webapp_dir,
            show_index=False,
            follow_symlinks=False,
        )

    app.router.add_get("/api/user", api_user)
    app.router.add_post("/api/user", api_user)
    app.router.add_post("/api/swap", api_swap)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info("aiohttp server started on port %s", PORT)

    return runner


# ============================================================
# АДМИН-ПАНЕЛЬ: @ПОМОЩЬ
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@помощь$"))
async def admin_help_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "👑 <b>АДМИН-ПАНЕЛЬ TOKENS</b>\n\n"
        "<code>@помощь</code> — список команд\n"
        "<code>@скан ID</code> — информация о пользователе\n"
        "<code>@выдать ID СУММА</code> — начислить TOKENS\n"
        "<code>@дроп СУММА</code> — начислить всем\n"
        "<code>@бан ID ЧАСЫ</code> — временный бан\n"
        "<code>@стата</code> — статистика бота\n"
        "<code>@рассылка ТЕКСТ</code> — рассылка\n"
        "<code>@сет_курс ЧИСЛО</code> — изменить курс TNC\n"
        "<code>@дождь СУММА</code> — раздать игрокам чата",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @СКАН ID
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@скан\s+\d+$"))
async def admin_scan_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = int(message.text.split()[1])

    row = await db_fetchone(
        """
        SELECT user_id, username, first_name, balance,
               balance_tnc, referrals, is_banned, ban_until,
               is_vip, created_at, last_activity
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    if not row:
        await message.answer("❌ Пользователь не найден.")
        return

    games = await db_fetchone(
        """
        SELECT COUNT(*), COALESCE(SUM(bet), 0), COALESCE(SUM(win), 0)
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,),
    )

    transactions = await db_fetchone(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ?",
        (user_id,),
    )

    (
        uid, username, first_name, balance, tnc,
        referrals, banned, ban_until, vip, created, activity
    ) = row

    await message.answer(
        "🔎 <b>ПОЛЬЗОВАТЕЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"ID: <code>{uid}</code>\n"
        f"Имя: {html.escape(first_name or '')}\n"
        f"Username: @{html.escape(username or 'нет')}\n"
        f"TOKENS: <b>{format_tokens(balance or 0)}</b>\n"
        f"TNC: <b>{float(tnc or 0):.8f}</b>\n"
        f"Рефералов: <b>{referrals or 0}</b>\n"
        f"VIP: <b>{'Да' if vip else 'Нет'}</b>\n"
        f"Бан: <b>{'Да' if banned else 'Нет'}</b>\n"
        f"Бан до: <code>{ban_until or '—'}</code>\n"
        f"Регистрация: <code>{created or '—'}</code>\n"
        f"Активность: <code>{activity or '—'}</code>\n\n"
        f"Игр: <b>{games[0] if games else 0}</b>\n"
        f"Ставки: <b>{format_tokens(games[1] if games else 0)}</b>\n"
        f"Выигрыши: <b>{format_tokens(games[2] if games else 0)}</b>\n"
        f"Транзакций: <b>{transactions[0] if transactions else 0}</b>",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @ВЫДАТЬ ID СУММА
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@выдать\s+\d+\s+\d+$"))
async def admin_give_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    _, user_id_raw, amount_raw = message.text.split()
    user_id = int(user_id_raw)
    amount = int(amount_raw)

    if amount <= 0:
        await message.answer("❌ Сумма должна быть положительной.")
        return

    user = await get_user(user_id)

    if not user:
        await message.answer("❌ Пользователь не найден.")
        return

    await change_balance(
        user_id,
        amount,
        "admin_give",
        f"Начисление администратором {message.from_user.id}",
    )

    await message.answer(
        f"✅ Начислено <b>{format_tokens(amount)} TOKENS</b> "
        f"пользователю <code>{user_id}</code>.",
        parse_mode="HTML",
    )

    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id,
            f"🎁 Администратор начислил вам {format_tokens(amount)} TOKENS.",
        )


# ============================================================
# АДМИН: @ДРОП СУММА
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@дроп\s+\d+$"))
async def admin_drop_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    amount = int(message.text.split()[1])

    if amount <= 0:
        await message.answer("❌ Сумма должна быть положительной.")
        return

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            count = (await cursor.fetchone())[0]

            await db.execute(
                """
                UPDATE users
                SET balance = MIN(?, balance + ?)
                """,
                (MAX_BALANCE, amount),
            )

            await db.execute(
                """
                INSERT INTO transactions
                (user_id, amount, currency, transaction_type, description, created_at)
                SELECT user_id, ?, 'TOKENS', 'admin_drop',
                       'Массовое начисление', ?
                FROM users
                """,
                (amount, now_iso()),
            )

            await db.commit()

    await message.answer(
        f"🎉 Начислено по <b>{format_tokens(amount)} TOKENS</b> "
        f"для <b>{count}</b> пользователей.",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @БАН ID ЧАСЫ
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@бан\s+\d+\s+\d+$"))
async def admin_ban_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    _, user_id_raw, hours_raw = message.text.split()

    user_id = int(user_id_raw)
    hours = int(hours_raw)

    if hours <= 0:
        await message.answer("❌ Часы должны быть положительными.")
        return

    ban_until = (
        datetime.now() + timedelta(hours=hours)
    ).isoformat(timespec="seconds")

    cursor = await db_execute(
        """
        UPDATE users
        SET is_banned = 1, ban_until = ?
        WHERE user_id = ?
        """,
        (ban_until, user_id),
    )

    await message.answer(
        f"🚫 Пользователь <code>{user_id}</code> заблокирован "
        f"на {hours} ч.",
        parse_mode="HTML",
    )

    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id,
            f"🚫 Ваш аккаунт заблокирован на {hours} часов.",
        )


# ============================================================
# АДМИН: @СТАТА
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@стата$"))
async def admin_stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    users = await db_fetchone("SELECT COUNT(*) FROM users")
    balance = await db_fetchone(
        "SELECT COALESCE(SUM(balance), 0) FROM users"
    )
    games = await db_fetchone("SELECT COUNT(*) FROM game_log")
    vip = await db_fetchone(
        "SELECT COUNT(*) FROM users WHERE is_vip = 1"
    )
    transactions = await db_fetchone(
        "SELECT COUNT(*) FROM transactions"
    )

    await message.answer(
        "📊 <b>СТАТИСТИКА TOKENS</b>\n\n"
        f"👥 Пользователей: <b>{users[0]}</b>\n"
        f"💰 Общий баланс: <b>{format_tokens(balance[0])}</b>\n"
        f"🎮 Игр: <b>{games[0]}</b>\n"
        f"⭐ VIP: <b>{vip[0]}</b>\n"
        f"💳 Транзакций: <b>{transactions[0]}</b>",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @РАССЫЛКА ТЕКСТ
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@рассылка\s+.+"))
async def admin_broadcast_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    text = message.text.split(maxsplit=1)[1].strip()

    if not text:
        await message.answer("Укажите текст рассылки.")
        return

    rows = await db_fetchall("SELECT user_id FROM users")

    sent = 0
    failed = 0

    await message.answer(
        f"📢 Начинаю рассылку для {len(rows)} пользователей."
    )

    for (user_id,) in rows:
        try:
            await bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    await message.answer(
        "📢 <b>Рассылка завершена</b>\n\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @СЕТ_КУРС
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@сет_курс\s+\d+(?:\.\d+)?$"))
async def admin_set_rate_handler(message: Message):
    global TOKEN_TO_TNC_RATE

    if not is_admin(message.from_user.id):
        return

    rate = float(message.text.split()[1])

    if not math.isfinite(rate) or rate <= 0:
        await message.answer("❌ Курс должен быть положительным.")
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
                (str(rate),),
            )
            await db.commit()

    TOKEN_TO_TNC_RATE = rate

    await message.answer(
        f"✅ Новый курс: <b>1 TNC = {rate:,.8f} TOKENS</b>",
        parse_mode="HTML",
    )


# ============================================================
# АДМИН: @ДОЖДЬ СУММА
# ============================================================

@dp.message(F.text.regexp(r"(?i)^@дождь\s+\d+$"))
async def admin_rain_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    if not is_group(message):
        await message.answer("❌ Команда работает только в группе.")
        return

    amount = int(message.text.split()[1])

    if amount <= 0:
        await message.answer("❌ Сумма должна быть положительной.")
        return

    cutoff = (
        datetime.now() - timedelta(hours=24)
    ).isoformat(timespec="seconds")

    rows = await db_fetchall(
        """
        SELECT DISTINCT g.user_id
        FROM game_log g
        INNER JOIN users u ON u.user_id = g.user_id
        WHERE g.created_at >= ?
          AND u.is_banned = 0
        """,
        (cutoff,),
    )

    participants = [int(row[0]) for row in rows]

    if not participants:
        await message.answer("🌧 За последние 24 часа никто не играл.")
        return

    if amount < len(participants):
        await message.answer(
            f"❌ Минимальная сумма дождя: {len(participants)} TOKENS."
        )
        return

    each, remainder = divmod(amount, len(participants))

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for index, user_id in enumerate(participants):
                reward = each + (1 if index < remainder else 0)

                await db.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (reward, user_id),
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TOKENS', 'rain', ?, ?)
                    """,
                    (
                        user_id,
                        reward,
                        f"Дождь в чате {message.chat.id}",
                        now_iso(),
                    ),
                )

            await db.commit()

    await message.answer(
        "🌧 <b>ДОЖДЬ ЗАВЕРШЁН!</b>\n\n"
        f"Участников: <b>{len(participants)}</b>\n"
        f"Всего: <b>{format_tokens(amount)} TOKENS</b>\n"
        f"Каждому: <b>{format_tokens(each)} TOKENS</b>",
        parse_mode="HTML",
    )


# ============================================================
# VIP-КЕШБЭК: 2.5% ОТ ПРОИГРЫШЕЙ ЗА СУТКИ
# ============================================================

async def process_vip_cashback(start_time: str, end_time: str):
    rows = await db_fetchall(
        """
        SELECT
            g.user_id,
            SUM(
                CASE
                    WHEN g.bet > g.win THEN g.bet - g.win
                    ELSE 0
                END
            )
        FROM game_log g
        INNER JOIN users u ON u.user_id = g.user_id
        WHERE u.is_vip = 1
          AND g.created_at >= ?
          AND g.created_at < ?
        GROUP BY g.user_id
        """,
        (start_time, end_time),
    )

    rewarded_users = 0
    total_cashback = 0

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for user_id, losses in rows:
                cashback = int(
                    math.floor((losses or 0) * VIP_CASHBACK_PERCENT)
                )

                if cashback <= 0:
                    continue

                await db.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ? AND is_vip = 1
                    """,
                    (cashback, user_id),
                )

                await db.execute(
                    """
                    INSERT INTO transactions
                    (user_id, amount, currency, transaction_type, description, created_at)
                    VALUES (?, ?, 'TOKENS', 'vip_cashback', ?, ?)
                    """,
                    (
                        user_id,
                        cashback,
                        "VIP-кешбэк 2.5%",
                        now_iso(),
                    ),
                )

                rewarded_users += 1
                total_cashback += cashback

            await db.commit()

    logger.info(
        "VIP cashback: users=%s amount=%s",
        rewarded_users,
        total_cashback,
    )

    return rewarded_users, total_cashback


async def vip_cashback_scheduler():
    while True:
        now = datetime.now()

        next_day = now.date() + timedelta(days=1)
        midnight = datetime.combine(
            next_day,
            datetime.min.time(),
        )

        await asyncio.sleep(
            max(1, (midnight - now).total_seconds())
        )

        current_day = datetime.now().date()
        previous_day = current_day - timedelta(days=1)

        start_time = datetime.combine(
            previous_day,
            datetime.min.time(),
        ).isoformat(timespec="seconds")

        end_time = datetime.combine(
            current_day,
            datetime.min.time(),
        ).isoformat(timespec="seconds")

        try:
            await process_vip_cashback(
                start_time,
                end_time,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка начисления VIP-кешбэка")


# ============================================================
# ЗАГРУЗКА КУРСА ИЗ БАЗЫ
# ============================================================

async def load_token_rate():
    global TOKEN_TO_TNC_RATE

    row = await db_fetchone(
        "SELECT value FROM settings WHERE key = 'token_to_tnc_rate'"
    )

    if row:
        try:
            rate = float(row[0])

            if math.isfinite(rate) and rate > 0:
                TOKEN_TO_TNC_RATE = rate
        except (ValueError, TypeError):
            logger.exception("Не удалось загрузить курс")


# ============================================================
# MAIN
# ============================================================

async def main():
    web_runner = None
    cashback_task = None

    try:
        logger.info("Запуск TOKENS...")

        await init_db()
        await load_token_rate()

        web_runner = await start_web_server()

        cashback_task = asyncio.create_task(
            vip_cashback_scheduler(),
            name="vip_cashback_scheduler",
        )

        logger.info("Запуск Telegram polling...")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")

    finally:
        if cashback_task:
            cashback_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await cashback_task

        if web_runner:
            with contextlib.suppress(Exception):
                await web_runner.cleanup()

        with contextlib.suppress(Exception):
            await dp.storage.close()

        with contextlib.suppress(Exception):
            await bot.session.close()

        logger.info("TOKENS остановлен")


if __name__ == "__main__":
    asyncio.run(main())