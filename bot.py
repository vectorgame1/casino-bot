import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

import aiosqlite
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import (
    ChatType,
    DiceEmoji,
    ParseMode,
)
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "tokenplays").lstrip("@")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")

DATABASE_PATH = os.getenv("DATABASE_PATH", "tokens.db")
WEBAPP_DIR = Path("webapp")
WEBAPP_INDEX = WEBAPP_DIR / "index.html"

TOKEN_TO_TNC_RATE = 50000.0
START_BONUS = 5000
BONUS_AMOUNT = 2500
BONUS_COOLDOWN_HOURS = 12

CAPTCHA_ATTEMPTS = 3
CAPTCHA_BAN_HOURS = 12

PRIVATE_DELETE_SECONDS = 30
GAME_DELETE_SECONDS = 15
GROUP_DELETE_SECONDS = 60

VIP_CASHBACK_RATE = 0.025

ROULETTE_GIF = Path("roulette.gif")
HOW_TO_PLAY_IMAGE = Path("how_to_play.jpg")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("TOKENS")

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())

DATABASE_LOCK = asyncio.Lock()
roulette_locks: dict[int, asyncio.Lock] = {}
roulette_running: set[int] = set()


# ============================================================
# FSM
# ============================================================

class CaptchaState(StatesGroup):
    waiting = State()


class ManualSwapState(StatesGroup):
    waiting_amount = State()


class AdminBroadcastState(StatesGroup):
    waiting_text = State()


# ============================================================
# DATABASE
# ============================================================

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL NOT NULL DEFAULT 0,
                balance_tnc REAL NOT NULL DEFAULT 0,
                referrals INTEGER NOT NULL DEFAULT 0,
                referral_id INTEGER,
                is_banned INTEGER NOT NULL DEFAULT 0,
                banned_until TEXT,
                is_vip INTEGER NOT NULL DEFAULT 0,
                last_bonus TEXT,
                last_activity TEXT,
                total_games INTEGER NOT NULL DEFAULT 0,
                total_won REAL NOT NULL DEFAULT 0,
                total_lost REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                bet REAL NOT NULL DEFAULT 0,
                win REAL NOT NULL DEFAULT 0,
                profit REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'TOKENS',
                transaction_type TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bonus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                bonus_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                payload TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS roulette_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                bet REAL NOT NULL,
                selections TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS roulette_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                color TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                quest_key TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(user_id, quest_key)
            );

            CREATE INDEX IF NOT EXISTS idx_game_log_user
                ON game_log(user_id);

            CREATE INDEX IF NOT EXISTS idx_game_log_date
                ON game_log(created_at);

            CREATE INDEX IF NOT EXISTS idx_transactions_user
                ON transactions(user_id);

            CREATE INDEX IF NOT EXISTS idx_roulette_chat
                ON roulette_bets(chat_id);
            """
        )

        await db.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('token_to_tnc_rate', ?)
            """,
            (str(TOKEN_TO_TNC_RATE),),
        )
        await db.commit()

    logger.info("Database initialized")


async def db_execute(query: str, params: tuple = ()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.lastrowid


async def db_fetchone(query: str, params: tuple = ()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchone()


async def db_fetchall(query: str, params: tuple = ()):
    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchall()


async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    row = await db_fetchone(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    )
    return row[0] if row else default


async def set_setting(key: str, value: str):
    await db_execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


async def get_exchange_rate() -> float:
    value = await get_setting(
        "token_to_tnc_rate",
        str(TOKEN_TO_TNC_RATE),
    )
    try:
        rate = float(value)
        return rate if rate > 0 else TOKEN_TO_TNC_RATE
    except (TypeError, ValueError):
        return TOKEN_TO_TNC_RATE


async def get_user_balance(user_id: int) -> float:
    row = await db_fetchone(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
    )
    return float(row[0]) if row else 0.0


async def get_user_tnc_balance(user_id: int) -> float:
    row = await db_fetchone(
        "SELECT balance_tnc FROM users WHERE user_id = ?",
        (user_id,),
    )
    return float(row[0]) if row else 0.0


async def get_user(user_id: int):
    return await db_fetchone(
        """
        SELECT user_id, username, first_name, balance, balance_tnc,
               referrals, referral_id, is_banned, banned_until,
               is_vip, last_bonus, last_activity, total_games,
               total_won, total_lost, created_at
        FROM users WHERE user_id = ?
        """,
        (user_id,),
    )


async def log_transaction(
    user_id: int,
    amount: float,
    currency: str,
    transaction_type: str,
    description: str = "",
):
    await db_execute(
        """
        INSERT INTO transactions(
            user_id, amount, currency, transaction_type, description
        ) VALUES(?, ?, ?, ?, ?)
        """,
        (user_id, amount, currency, transaction_type, description),
    )


async def register_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    referral_id: Optional[int] = None,
):
    existing = await get_user(user_id)

    now = datetime.now(timezone.utc).isoformat()

    if existing:
        await db_execute(
            """
            UPDATE users
            SET username = ?, first_name = ?, last_activity = ?
            WHERE user_id = ?
            """,
            (username, first_name, now, user_id),
        )
        return False

    if referral_id == user_id:
        referral_id = None

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO users(
                    user_id, username, first_name, balance,
                    balance_tnc, referral_id, last_activity
                ) VALUES(?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    user_id,
                    username,
                    first_name,
                    START_BONUS,
                    referral_id,
                    now,
                ),
            )

            await db.execute(
                """
                INSERT INTO transactions(
                    user_id, amount, currency, transaction_type, description
                ) VALUES(?, ?, 'TOKENS', 'start_bonus', 'Стартовый бонус')
                """,
                (user_id, START_BONUS),
            )

            await db.execute(
                """
                INSERT INTO bonus(user_id, amount, bonus_type)
                VALUES(?, ?, 'start')
                """,
                (user_id, START_BONUS),
            )

            if referral_id:
                await db.execute(
                    """
                    UPDATE users
                    SET balance = balance + 5000,
                        referrals = referrals + 1
                    WHERE user_id = ?
                    """,
                    (referral_id,),
                )
                await db.execute(
                    """
                    INSERT INTO transactions(
                        user_id, amount, currency, transaction_type, description
                    ) VALUES(?, 5000, 'TOKENS', 'referral', ?)
                    """,
                    (referral_id, f"Реферал {user_id}"),
                )

            await db.commit()

    return True


async def is_user_banned(user_id: int) -> bool:
    row = await db_fetchone(
        "SELECT is_banned, banned_until FROM users WHERE user_id = ?",
        (user_id,),
    )
    if not row or not row[0]:
        return False

    if row[1]:
        try:
            until = datetime.fromisoformat(row[1])
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)

            if datetime.now(timezone.utc) >= until:
                await db_execute(
                    """
                    UPDATE users
                    SET is_banned = 0, banned_until = NULL
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                return False
        except ValueError:
            pass

    return True


async def credit_user(
    user_id: int,
    amount: float,
    currency: str = "TOKENS",
    description: str = "Начисление",
):
    if amount <= 0:
        raise ValueError("Сумма должна быть положительной")

    column = "balance" if currency == "TOKENS" else "balance_tnc"

    await db_execute(
        f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?",
        (amount, user_id),
    )
    await log_transaction(
        user_id,
        amount,
        currency,
        "credit",
        description,
    )


async def debit_user(
    user_id: int,
    amount: float,
    currency: str = "TOKENS",
    description: str = "Списание",
) -> bool:
    if amount <= 0:
        return False

    column = "balance" if currency == "TOKENS" else "balance_tnc"

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                f"""
                UPDATE users
                SET {column} = {column} - ?
                WHERE user_id = ? AND {column} >= ?
                """,
                (amount, user_id, amount),
            )
            success = cursor.rowcount > 0

            if success:
                await db.execute(
                    """
                    INSERT INTO transactions(
                        user_id, amount, currency, transaction_type, description
                    ) VALUES(?, ?, ?, 'debit', ?)
                    """,
                    (user_id, -amount, currency, description),
                )

            await db.commit()
            return success


async def record_game(
    user_id: int,
    game: str,
    bet: float,
    win: float,
):
    profit = win - bet

    await db_execute(
        """
        INSERT INTO game_log(user_id, game, bet, win, profit)
        VALUES(?, ?, ?, ?, ?)
        """,
        (user_id, game, bet, win, profit),
    )

    await db_execute(
        """
        UPDATE users
        SET total_games = total_games + 1,
            total_won = total_won + ?,
            total_lost = total_lost + ?
        WHERE user_id = ?
        """,
        (
            max(profit, 0),
            max(-profit, 0),
            user_id,
        ),
    )


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    rows = [
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
            KeyboardButton(text="🎮 Как играть?"),
            KeyboardButton(text="💎 Крипта"),
        ],
        [
            KeyboardButton(text="🔄 Обменник"),
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def back_keyboard(callback_data: str = "menu:main"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callback_data,
                )
            ]
        ]
    )


def games_help_keyboard():
    builder = InlineKeyboardBuilder()
    buttons = [
        ("🎲 Кости", "help:dice"),
        ("🎯 Дартс", "help:darts"),
        ("🏀 Баскет", "help:basketball"),
        ("⚽ Футбол", "help:football"),
        ("🎳 Боулинг", "help:bowling"),
        ("🎡 Рулетка", "help:roulette"),
        ("📖 Команды", "help:commands"),
        ("💬 Чаты", "help:chats"),
    ]

    for text, data in buttons:
        builder.button(text=text, callback_data=data)

    builder.button(text="⬅️ Назад", callback_data="menu:main")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def crypto_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📈 Купить TNC",
                    callback_data="crypto:buy",
                ),
                InlineKeyboardButton(
                    text="📉 Продать TNC",
                    callback_data="crypto:sell",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚀 Открыть App",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def exchange_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 10 000 TOKENS → TNC",
                    callback_data="swap:tokens:10000",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 50 000 TOKENS → TNC",
                    callback_data="swap:tokens:50000",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 100 000 TOKENS → TNC",
                    callback_data="swap:tokens:100000",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 1 TNC → 50 000 TOKENS",
                    callback_data="swap:tnc:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Ввести сумму вручную",
                    callback_data="swap:manual",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def shop_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Кейсы",
                    callback_data="shop:cases",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="shop:vip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def quests_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Ежедневный бонус",
                    callback_data="bonus:claim",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Выполнить квесты",
                    callback_data="quests:list",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def profile_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="profile:settings",
                ),
                InlineKeyboardButton(
                    text="💼 Кошелек",
                    callback_data="profile:wallet",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def top_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="По балансу",
                    callback_data="top:tokens",
                ),
                InlineKeyboardButton(
                    text="По крипте",
                    callback_data="top:tnc",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu:main",
                )
            ],
        ]
    )


def roulette_result_keyboard(chat_id: int, bet: float, selections: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Повторить",
                    callback_data=f"roulette:repeat:{chat_id}:{bet}:{selections}",
                ),
                InlineKeyboardButton(
                    text="✖️ Удвоить",
                    callback_data=f"roulette:double:{chat_id}:{bet}:{selections}",
                ),
            ]
        ]
    )


# ============================================================
# GENERAL HELPERS
# ============================================================

async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup=None,
):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def safe_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def delete_later(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def send_temporary_message(
    chat_id: int,
    text: str,
    delay: int = GROUP_DELETE_SECONDS,
    **kwargs,
):
    message = await bot.send_message(chat_id, text, **kwargs)
    asyncio.create_task(
        delete_later(chat_id, message.message_id, delay)
    )
    return message


def parse_referral_parameter(text: Optional[str]) -> Optional[int]:
    if not text:
        return None

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None

    payload = parts[1].strip()
    match = re.fullmatch(r"(?:ref_)?(\d+)", payload)

    if not match:
        return None

    return int(match.group(1))


def format_amount(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def ensure_registered(message: Message):
    if not message.from_user:
        return False

    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(
            "Сначала выполни /start и пройди проверку.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return False

    return True


async def send_main_menu(message: Message, text: str = "Главное меню TOKENS"):
    await message.answer(
        text,
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
# CAPTCHA IMAGE
# ============================================================

def generate_captcha_image(code: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    import io

    width, height = 320, 120
    image = Image.new("RGB", (width, height), (20, 27, 43))
    draw = ImageDraw.Draw(image)

    for _ in range(18):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line(
            (x1, y1, x2, y2),
            fill=(random.randint(40, 100), 60, 120),
            width=2,
        )

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 58)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), code, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    draw.text(
        (
            (width - text_width) / 2,
            (height - text_height) / 2 - 8,
        ),
        code,
        font=font,
        fill=(255, 255, 255),
    )

    for _ in range(100):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(180, 180, 220))

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def send_new_captcha(
    message: Message,
    state: FSMContext,
    attempts: int,
):
    code = str(random.randint(1000, 9999))
    image_data = generate_captcha_image(code)

    await state.set_state(CaptchaState.waiting)
    await state.update_data(
        captcha_code=code,
        attempts=attempts,
    )

    sent = await message.answer_photo(
        BufferedInputFile(image_data, filename="captcha.png"),
        caption=(
            "🔐 <b>Проверка безопасности</b>\n\n"
            "Введи четыре цифры с картинки.\n"
            f"Осталось попыток: <b>{attempts}</b>"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )

    await state.update_data(captcha_message_id=sent.message_id)


# ============================================================
# START AND CAPTCHA HANDLERS
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not message.from_user:
        return

    user_id = message.from_user.id

    if await is_user_banned(user_id):
        await message.answer(
            "⛔ Доступ временно ограничен. Попробуй позже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    referral_id = parse_referral_parameter(message.text)

    await register_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        referral_id=referral_id,
    )

    user = await get_user(user_id)

    if user and user[7]:
        await message.answer(
            "⛔ Твой аккаунт заблокирован.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.clear()

    await message.answer(
        "Добро пожаловать в <b>TOKENS</b>!\n\n"
        "Для продолжения пройди короткую проверку.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await send_new_captcha(
        message,
        state,
        CAPTCHA_ATTEMPTS,
    )


@dp.message(CaptchaState.waiting, F.text)
async def captcha_input_handler(
    message: Message,
    state: FSMContext,
):
    if not message.from_user:
        return

    data = await state.get_data()
    expected = str(data.get("captcha_code", ""))
    attempts = int(data.get("attempts", CAPTCHA_ATTEMPTS))
    entered = (message.text or "").strip()

    await safe_delete(message)

    if entered == expected:
        captcha_message_id = data.get("captcha_message_id")

        if captcha_message_id:
            try:
                await bot.delete_message(
                    message.chat.id,
                    int(captcha_message_id),
                )
            except Exception:
                pass

        await state.clear()

        await credit_user(
            message.from_user.id,
            START_BONUS,
            "TOKENS",
            "Награда за прохождение капчи",
        )

        await message.answer(
            "✅ <b>Проверка пройдена!</b>\n"
            f"Тебе начислено <b>{format_amount(START_BONUS)} TOKENS</b>.\n\n"
            "Добро пожаловать!",
            reply_markup=main_menu_keyboard(),
        )
        return

    attempts -= 1

    old_message_id = data.get("captcha_message_id")
    if old_message_id:
        try:
            await bot.delete_message(
                message.chat.id,
                int(old_message_id),
            )
        except Exception:
            pass

    if attempts <= 0:
        banned_until = (
            datetime.now(timezone.utc)
            + timedelta(hours=CAPTCHA_BAN_HOURS)
        ).isoformat()

        await db_execute(
            """
            UPDATE users
            SET is_banned = 1, banned_until = ?
            WHERE user_id = ?
            """,
            (banned_until, message.from_user.id),
        )

        await state.clear()

        await message.answer(
            "⛔ <b>Попытки закончились.</b>\n"
            "Доступ заблокирован на 12 часов.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await send_new_captcha(
        message,
        state,
        attempts,
    )


@dp.message(CaptchaState.waiting)
async def captcha_non_text_handler(message: Message):
    await safe_delete(message)


# ============================================================
# MAIN MENU ROUTING
# ============================================================

@dp.message(F.text == "👤 Профиль")
async def profile_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_profile(message)


@dp.message(F.text == "🎁 Бонус")
async def bonus_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_bonus(message)


@dp.message(F.text == "🏆 Топ")
async def top_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await message.answer(
        "🏆 <b>Таблица лидеров</b>",
        reply_markup=top_keyboard(),
    )


@dp.message(F.text == "🔗 Рефералка")
async def referral_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_referral(message)


@dp.message(F.text == "🎮 Как играть?")
async def how_to_play_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_how_to_play(message)


@dp.message(F.text == "💎 Крипта")
async def crypto_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_crypto(message)


@dp.message(F.text == "🔄 Обменник")
async def exchange_menu_handler(message: Message):
    if not await ensure_registered(message):
        return
    await show_exchange(message)


# ============================================================
# PROFILE
# ============================================================

async def get_profile_statistics(user_id: int):
    row = await db_fetchone(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(bet), 0),
            COALESCE(SUM(win), 0),
            COALESCE(SUM(profit), 0)
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,),
    )

    return row or (0, 0, 0, 0)


async def show_profile(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Пользователь не найден.")
        return

    stats = await get_profile_statistics(user_id)

    text = (
        "👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {html.escape(user[2] or 'Игрок')}\n"
        f"💰 TOKENS: <b>{format_amount(user[3])}</b>\n"
        f"💎 TNC: <b>{format_amount(user[4])}</b>\n"
        f"👥 Рефералы: <b>{user[5]}</b>\n"
        f"⭐ VIP: <b>{'Да' if user[9] else 'Нет'}</b>\n\n"
        "📊 <b>Статистика игр</b>\n"
        f"🎮 Игр: {stats[0]}\n"
        f"📥 Выиграно: {format_amount(stats[2])}\n"
        f"📤 Ставки: {format_amount(stats[1])}\n"
        f"📈 Результат: {format_amount(stats[3])}"
    )

    await message.answer(
        text,
        reply_markup=profile_keyboard(),
    )


@dp.callback_query(F.data == "profile:settings")
async def profile_settings_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "⚙️ <b>Настройки профиля</b>\n\n"
        "Настройки уведомлений и приватности.",
        back_keyboard("menu:profile"),
    )


@dp.callback_query(F.data == "profile:wallet")
async def profile_wallet_callback(callback: CallbackQuery):
    await callback.answer()

    tokens = await get_user_balance(callback.from_user.id)
    tnc = await get_user_tnc_balance(callback.from_user.id)

    await safe_edit_text(
        callback.message,
        "💼 <b>ТВОЙ КОШЕЛЕК</b>\n\n"
        f"💰 TOKENS: <b>{format_amount(tokens)}</b>\n"
        f"💎 TNC: <b>{format_amount(tnc)}</b>",
        back_keyboard("menu:profile"),
    )


# ============================================================
# BONUS AND QUESTS
# ============================================================

async def show_bonus(message: Message):
    await message.answer(
        "🎁 <b>Бонусный центр</b>\n\n"
        f"Обычный бонус: <b>{BONUS_AMOUNT:,} TOKENS</b>\n"
        f"VIP-бонус: случайная награда.\n"
        f"Период ожидания: <b>{BONUS_COOLDOWN_HOURS} часов</b>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎁 Забрать бонус",
                        callback_data="bonus:claim",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📋 Задания",
                        callback_data="quests:list",
                    )
                ],
            ]
        ),
    )


@dp.callback_query(F.data == "bonus:claim")
async def claim_bonus_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        await callback.answer("Сначала выполни /start", show_alert=True)
        return

    last_bonus = user[10]

    if last_bonus:
        try:
            last = datetime.fromisoformat(last_bonus)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            available_at = last + timedelta(
                hours=BONUS_COOLDOWN_HOURS
            )

            now = datetime.now(timezone.utc)

            if now < available_at:
                remaining = available_at - now
                hours = int(remaining.total_seconds() // 3600)
                minutes = int(
                    (remaining.total_seconds() % 3600) // 60
                )

                await callback.answer(
                    f"Бонус будет доступен через {hours}ч {minutes}м",
                    show_alert=True,
                )
                return
        except ValueError:
            pass

    amount = (
        random.choice([5000, 7500, 10000])
        if user[9]
        else BONUS_AMOUNT
    )

    now = datetime.now(timezone.utc).isoformat()

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET balance = balance + ?, last_bonus = ?
                WHERE user_id = ?
                """,
                (amount, now, user_id),
            )

            await db.execute(
                """
                INSERT INTO bonus(user_id, amount, bonus_type)
                VALUES(?, ?, 'daily')
                """,
                (user_id, amount),
            )

            await db.execute(
                """
                INSERT INTO transactions(
                    user_id, amount, currency, transaction_type, description
                ) VALUES(?, ?, 'TOKENS', 'bonus', 'Бонус')
                """,
                (user_id, amount),
            )

            await db.commit()

    await safe_edit_text(
        callback.message,
        "🎉 <b>Бонус получен!</b>\n\n"
        f"Тебе начислено <b>{format_amount(amount)} TOKENS</b>.",
        back_keyboard("menu:main"),
    )


@dp.callback_query(F.data == "quests:list")
async def quests_list_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        return

    text = (
        "📋 <b>Задания TOKENS</b>\n\n"
        "1. 🎮 Сыграй одну игру в группе.\n"
        "2. 🔗 Пригласи друга по реферальной ссылке.\n"
        "3. 🎁 Забери ежедневный бонус.\n\n"
        "Награды за задания будут начисляться после проверки выполнения."
    )

    await safe_edit_text(
        callback.message,
        text,
        back_keyboard("menu:main"),
    )


# ============================================================
# REFERRALS
# ============================================================

async def show_referral(message: Message):
    user_id = message.from_user.id
    me = await bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{user_id}"

    row = await db_fetchone(
        "SELECT referrals FROM users WHERE user_id = ?",
        (user_id,),
    )
    referrals = row[0] if row else 0

    await message.answer(
        "🔗 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{referrals}</b>\n"
        "За каждого нового активного пользователя начисляется бонус.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Поделиться",
                        url=(
                            "https://t.me/share/url?"
                            f"url={link}"
                        ),
                    )
                ]
            ]
        ),
    )


# ============================================================
# TOP
# ============================================================

@dp.callback_query(F.data.in_({"top:tokens", "top:tnc"}))
async def top_callback(callback: CallbackQuery):
    await callback.answer()

    if callback.data == "top:tokens":
        rows = await db_fetchall(
            """
            SELECT user_id, first_name, balance
            FROM users
            ORDER BY balance DESC
            LIMIT 10
            """
        )
        title = "🏆 <b>ТОП ПО TOKENS</b>"
        field = 2
    else:
        rows = await db_fetchall(
            """
            SELECT user_id, first_name, balance_tnc
            FROM users
            ORDER BY balance_tnc DESC
            LIMIT 10
            """
        )
        title = "💎 <b>ТОП ПО TNC</b>"
        field = 2

    lines = [title, ""]

    if not rows:
        lines.append("Пока нет игроков.")
    else:
        for index, row in enumerate(rows, 1):
            name = html.escape(row[1] or f"Игрок {row[0]}")
            lines.append(
                f"{index}. {name} — <b>{format_amount(row[field])}</b>"
            )

    await safe_edit_text(
        callback.message,
        "\n".join(lines),
        top_keyboard(),
    )


# ============================================================
# HOW TO PLAY
# ============================================================

async def show_how_to_play(message: Message):
    caption = (
        "🎮 <b>КАК ИГРАТЬ В TOKENS</b>\n\n"
        "Игры доступны в групповых чатах, где добавлен бот.\n"
        "Ставки списываются перед игрой, выигрыш начисляется после результата.\n\n"
        "Выбери раздел:"
    )

    if HOW_TO_PLAY_IMAGE.exists():
        await message.answer_photo(
            FSInputFile(HOW_TO_PLAY_IMAGE),
            caption=caption,
            reply_markup=games_help_keyboard(),
        )
    else:
        await message.answer(
            caption,
            reply_markup=games_help_keyboard(),
        )


@dp.callback_query(F.data.startswith("help:"))
async def help_game_callback(callback: CallbackQuery):
    await callback.answer()

    key = callback.data.split(":", 1)[1]

    descriptions = {
        "dice": "🎲 Кости: отправь команду «кости СУММА». Победа выплачивается с коэффициентом x2.",
        "darts": "🎯 Дартс: команда «дартс СУММА». Коэффициент победы x2.",
        "basketball": "🏀 Баскетбол: команда «баскет СУММА». Множители зависят от результата броска.",
        "football": "⚽ Футбол: команда «футбол СУММА». Множители зависят от результата удара.",
        "bowling": "🎳 Боулинг: команда «боулинг СУММА». Коэффициент победы x2.",
        "roulette": "🎡 Рулетка: сделай ставку, затем администратор или игрок запускает «старт».",
        "commands": "📖 Команды: кости, дартс, баскет, футбол, боулинг, рулетка и старт.",
        "chats": "💬 Игры работают только в группах. Добавь бота в групповой чат.",
    }

    await safe_edit_text(
        callback.message,
        descriptions.get(key, "Информация не найдена."),
        back_keyboard("menu:howtoplay"),
    )


# ============================================================
# CRYPTO AND EXCHANGE
# ============================================================

async def show_crypto(message: Message):
    rate = await get_exchange_rate()
    tnc = await get_user_tnc_balance(message.from_user.id)
    tokens = await get_user_balance(message.from_user.id)

    await message.answer(
        "💎 <b>КРИПТОВАЛЮТА $TNC</b>\n\n"
        f"Курс: <b>1 TNC = {format_amount(rate)} TOKENS</b>\n\n"
        f"Твой баланс:\n"
        f"💰 TOKENS: <b>{format_amount(tokens)}</b>\n"
        f"💎 TNC: <b>{format_amount(tnc)}</b>",
        reply_markup=crypto_keyboard(),
    )


async def show_exchange(message: Message):
    rate = await get_exchange_rate()

    await message.answer(
        "🔄 <b>ОБМЕННИК TOKENS ↔ TNC</b>\n\n"
        f"Текущий курс: <b>1 TNC = {format_amount(rate)} TOKENS</b>\n\n"
        "Выбери сумму для обмена:",
        reply_markup=exchange_keyboard(),
    )


@dp.callback_query(F.data.startswith("swap:"))
async def swap_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    parts = callback.data.split(":")

    if len(parts) < 2:
        return

    direction = parts[1]

    if direction == "manual":
        await state.set_state(ManualSwapState.waiting_amount)
        await state.update_data(swap_message_id=callback.message.message_id)

        await safe_edit_text(
            callback.message,
            "✍️ <b>Ручной обмен</b>\n\n"
            "Отправь сумму TOKENS для обмена в TNC.\n"
            "Чтобы отменить, нажми /cancel.",
            back_keyboard("menu:exchange"),
        )
        return

    if len(parts) != 3:
        return

    try:
        amount = float(parts[2])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return

    if amount <= 0:
        await callback.answer("Некорректная сумма", show_alert=True)
        return

    user_id = callback.from_user.id
    rate = await get_exchange_rate()

    if direction == "tokens":
        tokens_amount = amount
        tnc_amount = tokens_amount / rate

        if not await debit_user(
            user_id,
            tokens_amount,
            "TOKENS",
            "Обмен TOKENS на TNC",
        ):
            await callback.answer(
                "Недостаточно TOKENS",
                show_alert=True,
            )
            return

        await credit_user(
            user_id,
            tnc_amount,
            "TNC",
            "Обмен TOKENS на TNC",
        )

        text = (
            "✅ <b>Обмен выполнен!</b>\n\n"
            f"Списано: <b>{format_amount(tokens_amount)} TOKENS</b>\n"
            f"Начислено: <b>{format_amount(tnc_amount)} TNC</b>"
        )

    elif direction == "tnc":
        tnc_amount = amount
        tokens_amount = tnc_amount * rate

        if not await debit_user(
            user_id,
            tnc_amount,
            "TNC",
            "Обмен TNC на TOKENS",
        ):
            await callback.answer(
                "Недостаточно TNC",
                show_alert=True,
            )
            return

        await credit_user(
            user_id,
            tokens_amount,
            "TOKENS",
            "Обмен TNC на TOKENS",
        )

        text = (
            "✅ <b>Обмен выполнен!</b>\n\n"
            f"Списано: <b>{format_amount(tnc_amount)} TNC</b>\n"
            f"Начислено: <b>{format_amount(tokens_amount)} TOKENS</b>"
        )
    else:
        return

    await safe_edit_text(
        callback.message,
        text,
        back_keyboard("menu:exchange"),
    )


@dp.message(ManualSwapState.waiting_amount, F.text)
async def manual_swap_handler(
    message: Message,
    state: FSMContext,
):
    if (message.text or "").strip().lower() == "/cancel":
        await state.clear()
        await message.answer(
            "Обмен отменен.",
            reply_markup=main_menu_keyboard(),
        )
        return

    try:
        tokens_amount = float(
            message.text.replace(",", ".").replace(" ", "")
        )
    except ValueError:
        await message.answer("Введи корректное число.")
        return

    if tokens_amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return

    user_id = message.from_user.id
    rate = await get_exchange_rate()
    tnc_amount = tokens_amount / rate

    if not await debit_user(
        user_id,
        tokens_amount,
        "TOKENS",
        "Ручной обмен TOKENS на TNC",
    ):
        await message.answer("Недостаточно TOKENS.")
        return

    await credit_user(
        user_id,
        tnc_amount,
        "TNC",
        "Ручной обмен TOKENS на TNC",
    )

    await state.clear()

    await message.answer(
        "✅ <b>Обмен выполнен!</b>\n\n"
        f"Списано: {format_amount(tokens_amount)} TOKENS\n"
        f"Получено: {format_amount(tnc_amount)} TNC",
        reply_markup=main_menu_keyboard(),
    )


@dp.callback_query(F.data.in_({"crypto:buy", "crypto:sell"}))
async def crypto_trade_callback(callback: CallbackQuery):
    await callback.answer(
        "Используй раздел «Обменник» для обмена TOKENS и TNC.",
        show_alert=True,
    )


# ============================================================
# SHOP
# ============================================================

@dp.callback_query(F.data == "shop:cases")
async def shop_cases_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🎁 <b>КЕЙСЫ</b>\n\n"
        "Магазин кейсов пока находится в разработке.",
        back_keyboard("menu:shop"),
    )


@dp.callback_query(F.data == "shop:vip")
async def shop_vip_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "⭐ <b>VIP-СТАТУС</b>\n\n"
        "VIP-пользователи получают повышенные бонусы "
        "и ежедневный кешбэк 2.5% от игровых проигрышей.\n\n"
        "Покупка VIP будет доступна после подключения платежного провайдера.",
        back_keyboard("menu:shop"),
    )


# ============================================================
# INLINE NAVIGATION
# ============================================================

@dp.callback_query(F.data == "menu:main")
async def menu_main_callback(callback: CallbackQuery):
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        await safe_edit_text(
            callback.message,
            "Главное меню находится в нижней клавиатуре.",
            None,
        )


@dp.callback_query(F.data == "menu:profile")
async def menu_profile_callback(callback: CallbackQuery):
    await callback.answer()

    user = await get_user(callback.from_user.id)
    if not user:
        await safe_edit_text(
            callback.message,
            "Пользователь не найден.",
            back_keyboard("menu:main"),
        )
        return

    stats = await get_profile_statistics(callback.from_user.id)

    await safe_edit_text(
        callback.message,
        "👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💰 TOKENS: <b>{format_amount(user[3])}</b>\n"
        f"💎 TNC: <b>{format_amount(user[4])}</b>\n"
        f"👥 Рефералы: <b>{user[5]}</b>\n"
        f"⭐ VIP: <b>{'Да' if user[9] else 'Нет'}</b>\n"
        f"🎮 Игр: <b>{stats[0]}</b>",
        profile_keyboard(),
    )


@dp.callback_query(F.data == "menu:exchange")
async def menu_exchange_callback(callback: CallbackQuery):
    await callback.answer()
    rate = await get_exchange_rate()

    await safe_edit_text(
        callback.message,
        "🔄 <b>ОБМЕННИК TOKENS ↔ TNC</b>\n\n"
        f"Текущий курс: <b>1 TNC = {format_amount(rate)} TOKENS</b>\n\n"
        "Выбери сумму для обмена:",
        exchange_keyboard(),
    )


@dp.callback_query(F.data == "menu:shop")
async def menu_shop_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🛒 <b>МАГАЗИН</b>\n\nВыбери раздел:",
        shop_keyboard(),
    )


@dp.callback_query(F.data == "menu:quests")
async def menu_quests_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🎯 <b>ЗАДАНИЯ</b>\n\nВыбери действие:",
        quests_keyboard(),
    )


@dp.callback_query(F.data == "menu:howtoplay")
async def menu_howtoplay_callback(callback: CallbackQuery):
    await callback.answer()
    await safe_edit_text(
        callback.message,
        "🎮 <b>КАК ИГРАТЬ?</b>\n\n"
        "Игры доступны только в группах.\n"
        "Выбери нужную игру:",
        games_help_keyboard(),
    )


# ============================================================
# GAME ENGINE
# ============================================================

GAME_CONFIG = {
    "кости": {
        "emoji": DiceEmoji.DICE,
        "multiplier": 2.0,
        "type": "fixed",
    },
    "дартс": {
        "emoji": DiceEmoji.DART,
        "multiplier": 2.0,
        "type": "fixed",
    },
    "боулинг": {
        "emoji": DiceEmoji.BOWLING,
        "multiplier": 2.0,
        "type": "fixed",
    },
    "баскет": {
        "emoji": DiceEmoji.BASKETBALL,
        "type": "variable",
        "multipliers": {
            1: 0.0,
            2: 1.0,
            3: 1.5,
            4: 1.8,
            5: 2.0,
        },
    },
    "футбол": {
        "emoji": DiceEmoji.FOOTBALL,
        "type": "variable",
        "multipliers": {
            1: 0.0,
            2: 1.0,
            3: 1.5,
            4: 1.8,
            5: 2.0,
        },
    },
}


def parse_game_bet(text: str, command: str) -> Optional[float]:
    parts = text.strip().split()

    if len(parts) < 2:
        return None

    try:
        amount = float(parts[1].replace(",", "."))
    except ValueError:
        return None

    if amount <= 0 or amount > 1_000_000_000:
        return None

    return amount


async def game_private_error(message: Message):
    await message.answer(
        "🎮 Игры доступны только в групповых чатах.\n\n"
        f"Добавь бота в группу или обратись к @{SUPPORT_USERNAME}.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💬 Поддержка",
                        url=f"https://t.me/{SUPPORT_USERNAME}",
                    )
                ]
            ]
        ),
    )


async def play_dice_game(
    message: Message,
    game_name: str,
    bet: float,
):
    user_id = message.from_user.id

    if await is_user_banned(user_id):
        await send_temporary_message(
            message.chat.id,
            "⛔ Твой аккаунт заблокирован.",
            GAME_DELETE_SECONDS,
        )
        return

    if not await debit_user(
        user_id,
        bet,
        "TOKENS",
        f"Ставка: {game_name}",
    ):
        await send_temporary_message(
            message.chat.id,
            "❌ Недостаточно TOKENS для ставки.",
            GAME_DELETE_SECONDS,
        )
        return

    config = GAME_CONFIG[game_name]

    dice_message = await bot.send_dice(
        chat_id=message.chat.id,
        emoji=config["emoji"],
    )

    await asyncio.sleep(3)

    value = dice_message.dice.value

    if config["type"] == "fixed":
        multiplier = (
            config["multiplier"]
            if value >= 4
            else 0.0
        )
    else:
        multiplier = config["multipliers"].get(value, 0.0)

    payout = bet * multiplier

    if payout > 0:
        await credit_user(
            user_id,
            payout,
            "TOKENS",
            f"Выигрыш: {game_name}",
        )

    await record_game(
        user_id,
        game_name,
        bet,
        payout,
    )

    if payout > bet:
        result_text = (
            f"🎉 <b>Победа!</b>\n"
            f"Ставка: {format_amount(bet)} TOKENS\n"
            f"Выигрыш: {format_amount(payout)} TOKENS\n"
            f"Прибыль: +{format_amount(payout - bet)} TOKENS"
        )
    elif payout == bet and payout > 0:
        result_text = (
            f"🤝 <b>Возврат ставки</b>\n"
            f"Выплата: {format_amount(payout)} TOKENS"
        )
    else:
        result_text = (
            f"😔 <b>Не повезло.</b>\n"
            f"Потеряно: {format_amount(bet)} TOKENS"
        )

    result_message = await bot.send_message(
        message.chat.id,
        result_text,
    )

    asyncio.create_task(
        delete_later(
            message.chat.id,
            dice_message.message_id,
            GAME_DELETE_SECONDS,
        )
    )
    asyncio.create_task(
        delete_later(
            message.chat.id,
            result_message.message_id,
            GAME_DELETE_SECONDS,
        )
    )


async def game_command_handler(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        await game_private_error(message)
        return

    if not message.from_user:
        return

    if not await get_user(message.from_user.id):
        await send_temporary_message(
            message.chat.id,
            "Сначала открой личные сообщения с ботом и выполни /start.",
            GAME_DELETE_SECONDS,
        )
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        await send_temporary_message(
            message.chat.id,
            "Укажи ставку. Например: кости 100",
            GAME_DELETE_SECONDS,
        )
        return

    command = parts[0].lower()
    amount = parse_game_bet(text, command)

    if amount is None:
        await send_temporary_message(
            message.chat.id,
            "Некорректная ставка. Пример: кости 100",
            GAME_DELETE_SECONDS,
        )
        return

    await play_dice_game(
        message,
        command,
        amount,
    )


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def group_game_dispatcher(message: Message):
    if not message.text:
        return

    parts = message.text.strip().lower().split(maxsplit=1)
    if not parts:
        return

    command = parts[0]

    if command in GAME_CONFIG:
        await game_command_handler(message)


# ============================================================
# ROULETTE PARSER
# ============================================================

def roulette_color(number: int) -> str:
    if number == 0:
        return "green"

    if number in {
        1, 3, 5, 7, 9, 12, 14, 16, 18,
        19, 21, 23, 25, 27, 30, 32, 34, 36,
    }:
        return "red"

    return "black"


def parse_roulette_bet(text: str):
    """
    Форматы:
      к 1000
      10-20 500
      500 10-20 30-34 23-24 24-35

    Возвращает:
      {"amount": float, "selections": [списки чисел]}
    """
    parts = text.strip().lower().split()

    if len(parts) < 2:
        return None

    if parts[0] == "к":
        try:
            amount = float(parts[1].replace(",", "."))
        except ValueError:
            return None

        if amount <= 0:
            return None

        return {
            "amount": amount,
            "selections": [[number] for number in range(37)],
            "kind": "color",
        }

    try:
        first_number = float(parts[0].replace(",", "."))
    except ValueError:
        first_number = None

    if first_number is not None:
        amount = first_number
        selection_tokens = parts[1:]
    else:
        try:
            amount = float(parts[-1].replace(",", "."))
        except ValueError:
            return None

        selection_tokens = parts[:-1]

    if amount <= 0 or amount > 1_000_000_000:
        return None

    selections = []

    for token in selection_tokens:
        token = token.strip()

        if re.fullmatch(r"\d+", token):
            number = int(token)

            if not 0 <= number <= 36:
                return None

            selections.append([number])
            continue

        match = re.fullmatch(r"(\d+)-(\d+)", token)

        if not match:
            return None

        start = int(match.group(1))
        end = int(match.group(2))

        if not (0 <= start <= 36 and 0 <= end <= 36):
            return None

        low = min(start, end)
        high = max(start, end)

        selections.append(list(range(low, high + 1)))

    if not selections:
        return None

    return {
        "amount": amount,
        "selections": selections,
        "kind": "number",
    }


def serialize_selections(selections) -> str:
    return json.dumps(
        selections,
        separators=(",", ":"),
    )


def deserialize_selections(value: str):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return []

    if not isinstance(parsed, list):
        return []

    result = []

    for group in parsed:
        if not isinstance(group, list):
            continue

        valid = [
            int(number)
            for number in group
            if isinstance(number, int) and 0 <= number <= 36
        ]

        if valid:
            result.append(valid)

    return result


async def place_roulette_bet(
    message: Message,
    parsed: dict,
):
    user_id = message.from_user.id
    amount = float(parsed["amount"])
    selections = parsed["selections"]

    if not await debit_user(
        user_id,
        amount,
        "TOKENS",
        "Ставка в рулетке",
    ):
        await send_temporary_message(
            message.chat.id,
            "❌ Недостаточно TOKENS для ставки.",
            GROUP_DELETE_SECONDS,
        )
        return

    serialized = serialize_selections(selections)

    await db_execute(
        """
        INSERT INTO roulette_bets(
            chat_id, user_id, bet, selections
        ) VALUES(?, ?, ?, ?)
        """,
        (
            message.chat.id,
            user_id,
            amount,
            serialized,
        ),
    )

    await send_temporary_message(
        message.chat.id,
        (
            f"🎡 Ставка принята от "
            f"<a href=\"tg://user?id={user_id}\">игрока</a>.\n"
            f"Сумма: <b>{format_amount(amount)} TOKENS</b>\n"
            "Для запуска напиши «старт»."
        ),
        GROUP_DELETE_SECONDS,
    )


async def run_roulette(chat_id: int):
    lock = roulette_locks.setdefault(chat_id, asyncio.Lock())

    if lock.locked() or chat_id in roulette_running:
        return None

    async with lock:
        roulette_running.add(chat_id)

        try:
            bets = await db_fetchall(
                """
                SELECT id, user_id, bet, selections
                FROM roulette_bets
                WHERE chat_id = ?
                ORDER BY id ASC
                """,
                (chat_id,),
            )

            if not bets:
                return None

            number = random.randint(0, 36)
            color = roulette_color(number)

            await db_execute(
                """
                INSERT INTO roulette_history(chat_id, number, color)
                VALUES(?, ?, ?)
                """,
                (chat_id, number, color),
            )

            results = []

            for bet_id, user_id, bet, raw_selections in bets:
                selections = deserialize_selections(raw_selections)

                won = any(number in group for group in selections)

                # Упрощенная выплата: одиночное число x36,
                # диапазон — пропорциональная выплата по числу чисел.
                payout = 0.0

                if won:
                    matching_group = next(
                        (
                            group for group in selections
                            if number in group
                        ),
                        [],
                    )

                    if len(matching_group) == 1:
                        multiplier = 36.0
                    else:
                        multiplier = 36.0 / len(matching_group)

                    payout = bet * multiplier

                    await credit_user(
                        user_id,
                        payout,
                        "TOKENS",
                        "Выигрыш в рулетке",
                    )

                await record_game(
                    user_id,
                    "roulette",
                    bet,
                    payout,
                )

                results.append(
                    {
                        "user_id": user_id,
                        "bet": bet,
                        "payout": payout,
                        "selections": raw_selections,
                    }
                )

            await db_execute(
                "DELETE FROM roulette_bets WHERE chat_id = ?",
                (chat_id,),
            )

            return number, color, results

        finally:
            roulette_running.discard(chat_id)


async def roulette_start_handler(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        await game_private_error(message)
        return

    if message.chat.id in roulette_running:
        await send_temporary_message(
            message.chat.id,
            "⏳ Рулетка уже крутится.",
            GROUP_DELETE_SECONDS,
        )
        return

    result = await run_roulette(message.chat.id)

    if result is None:
        await send_temporary_message(
            message.chat.id,
            "❌ Нет ставок для запуска рулетки.",
            GROUP_DELETE_SECONDS,
        )
        return

    number, color, results = result

    if ROULETTE_GIF.exists():
        try:
            animation_message = await bot.send_animation(
                message.chat.id,
                FSInputFile(ROULETTE_GIF),
            )
            await asyncio.sleep(4)
        except Exception:
            animation_message = None
    else:
        animation_message = None

    color_emoji = {
        "red": "🔴",
        "black": "⚫",
        "green": "🟢",
    }[color]

    lines = [
        "🎡 <b>РЕЗУЛЬТАТ РУЛЕТКИ</b>",
        "",
        f"Выпало: <b>{number}</b> {color_emoji}",
        "",
    ]

    for item in results:
        user_id = item["user_id"]
        bet = item["bet"]
        payout = item["payout"]

        if payout > 0:
            lines.append(
                f"👤 <code>{user_id}</code>: "
                f"+{format_amount(payout)} TOKENS"
            )
        else:
            lines.append(
                f"👤 <code>{user_id}</code>: "
                f"-{format_amount(bet)} TOKENS"
            )

    result_message = await bot.send_message(
        message.chat.id,
        "\n".join(lines),
    )

    if animation_message:
        asyncio.create_task(
            delete_later(
                message.chat.id,
                animation_message.message_id,
                GROUP_DELETE_SECONDS,
            )
        )

    asyncio.create_task(
        delete_later(
            message.chat.id,
            result_message.message_id,
            GROUP_DELETE_SECONDS,
        )
    )


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def roulette_dispatcher(message: Message):
    text = (message.text or "").strip()

    if text.lower() == "старт":
        await roulette_start_handler(message)
        return

    parsed = parse_roulette_bet(text)

    if parsed is None:
        return

    if not message.from_user:
        return

    if not await get_user(message.from_user.id):
        await send_temporary_message(
            message.chat.id,
            "Сначала открой личные сообщения с ботом и выполни /start.",
            GROUP_DELETE_SECONDS,
        )
        return

    await place_roulette_bet(message, parsed)


@dp.callback_query(F.data.startswith("roulette:"))
async def roulette_repeat_callback(callback: CallbackQuery):
    await callback.answer()

    parts = callback.data.split(":", 4)

    if len(parts) != 5:
        return

    action = parts[1]

    try:
        chat_id = int(parts[2])
        amount = float(parts[3])
        selections = parts[4]
    except ValueError:
        return

    if action == "double":
        amount *= 2

    parsed_selections = deserialize_selections(selections)

    if not parsed_selections:
        await callback.answer("Ставка больше недоступна.", show_alert=True)
        return

    user_id = callback.from_user.id

    if not await debit_user(
        user_id,
        amount,
        "TOKENS",
        "Повторная ставка в рулетке",
    ):
        await callback.answer("Недостаточно TOKENS.", show_alert=True)
        return

    await db_execute(
        """
        INSERT INTO roulette_bets(chat_id, user_id, bet, selections)
        VALUES(?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            amount,
            serialize_selections(parsed_selections),
        ),
    )

    await callback.answer("Ставка добавлена.")


# ============================================================
# ADMIN COMMANDS
# ============================================================

ADMIN_HELP_TEXT = (
    "🛡 <b>АДМИН-ПАНЕЛЬ TOKENS</b>\n\n"
    "<code>@помощь</code> — список команд\n"
    "<code>@скан ID</code> — информация о пользователе\n"
    "<code>@выдать ID СУММА</code> — начислить TOKENS\n"
    "<code>@выдать_крипту ID СУММА</code> — начислить TNC\n"
    "<code>@дроп СУММА</code> — начислить всем\n"
    "<code>@бан ID ЧАСЫ</code> — временный бан\n"
    "<code>@стата</code> — статистика бота\n"
    "<code>@рассылка ТЕКСТ</code> — рассылка\n"
    "<code>@сет_курс ЧИСЛО</code> — изменить курс TNC\n"
    "<code>@дождь СУММА</code> — раздать участникам чата"
)


async def admin_reply(message: Message, text: str):
    await message.answer(text)


async def admin_scan(message: Message, user_id: int):
    user = await get_user(user_id)

    if not user:
        await admin_reply(message, "Пользователь не найден.")
        return

    stats = await get_profile_statistics(user_id)

    transactions_count = await db_fetchone(
        "SELECT COUNT(*) FROM transactions WHERE user_id = ?",
        (user_id,),
    )

    username = f"@{user[1]}" if user[1] else "не указан"

    text = (
        "🔎 <b>ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ</b>\n\n"
        f"ID: <code>{user[0]}</code>\n"
        f"Username: {html.escape(username)}\n"
        f"Имя: {html.escape(user[2] or '—')}\n"
        f"TOKENS: <b>{format_amount(user[3])}</b>\n"
        f"TNC: <b>{format_amount(user[4])}</b>\n"
        f"Рефералы: <b>{user[5]}</b>\n"
        f"Реферер ID: <code>{user[6] or '—'}</code>\n"
        f"Бан: <b>{'Да' if user[7] else 'Нет'}</b>\n"
        f"До бана: <code>{html.escape(user[8] or '—')}</code>\n"
        f"VIP: <b>{'Да' if user[9] else 'Нет'}</b>\n"
        f"Создан: <code>{html.escape(user[15] or '—')}</code>\n\n"
        f"Игр: <b>{stats[0]}</b>\n"
        f"Ставки: <b>{format_amount(stats[1])}</b>\n"
        f"Выигрыши: <b>{format_amount(stats[2])}</b>\n"
        f"Результат: <b>{format_amount(stats[3])}</b>\n"
        f"Транзакций: <b>{transactions_count[0] if transactions_count else 0}</b>"
    )

    await admin_reply(message, text)


async def admin_stats(message: Message):
    row = await db_fetchone(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(balance), 0),
            COALESCE(SUM(balance_tnc), 0),
            COALESCE(SUM(is_vip), 0)
        FROM users
        """
    )

    games = await db_fetchone(
        "SELECT COUNT(*) FROM game_log"
    )

    transactions = await db_fetchone(
        "SELECT COUNT(*) FROM transactions"
    )

    await admin_reply(
        message,
        "📊 <b>СТАТИСТИКА TOKENS</b>\n\n"
        f"👥 Пользователей: <b>{row[0]}</b>\n"
        f"💰 Общий баланс TOKENS: <b>{format_amount(row[1])}</b>\n"
        f"💎 Общий баланс TNC: <b>{format_amount(row[2])}</b>\n"
        f"⭐ VIP-пользователей: <b>{row[3]}</b>\n"
        f"🎮 Всего игр: <b>{games[0] if games else 0}</b>\n"
        f"🧾 Транзакций: <b>{transactions[0] if transactions else 0}</b>"
    )


async def admin_drop(message: Message, amount: float):
    if amount <= 0:
        await admin_reply(message, "Сумма должна быть больше нуля.")
        return

    users = await db_fetchall(
        "SELECT user_id FROM users WHERE is_banned = 0"
    )

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET balance = balance + ?
                WHERE is_banned = 0
                """,
                (amount,),
            )

            await db.executemany(
                """
                INSERT INTO transactions(
                    user_id, amount, currency, transaction_type, description
                ) VALUES(?, ?, 'TOKENS', 'admin_drop', 'Общий дроп')
                """,
                [(row[0], amount) for row in users],
            )

            await db.commit()

    await admin_reply(
        message,
        f"🎁 Начислено по <b>{format_amount(amount)} TOKENS</b> "
        f"пользователям: <b>{len(users)}</b>.",
    )


async def admin_ban(message: Message, user_id: int, hours: float):
    if hours <= 0:
        await admin_reply(message, "Количество часов должно быть больше нуля.")
        return

    banned_until = (
        datetime.now(timezone.utc)
        + timedelta(hours=hours)
    ).isoformat()

    await db_execute(
        """
        UPDATE users
        SET is_banned = 1, banned_until = ?
        WHERE user_id = ?
        """,
        (banned_until, user_id),
    )

    await admin_reply(
        message,
        f"⛔ Пользователь <code>{user_id}</code> заблокирован "
        f"на {hours:g} ч.",
    )


async def admin_broadcast(message: Message, text: str):
    users = await db_fetchall(
        "SELECT user_id FROM users WHERE is_banned = 0"
    )

    sent = 0
    failed = 0

    status = await message.answer(
        f"📣 Начинаю рассылку для {len(users)} пользователей..."
    )

    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"📢 <b>Сообщение TOKENS</b>\n\n{html.escape(text)}",
            )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    await status.edit_text(
        "📣 <b>Рассылка завершена</b>\n\n"
        f"Успешно: {sent}\n"
        f"Не доставлено: {failed}"
    )


async def admin_rain(message: Message, amount: float):
    if message.chat.type == ChatType.PRIVATE:
        await admin_reply(
            message,
            "Команда @дождь работает только в группе.",
        )
        return

    if amount <= 0:
        await admin_reply(message, "Сумма должна быть больше нуля.")
        return

    rows = await db_fetchall(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN game_log g ON g.user_id = u.user_id
        WHERE g.created_at >= datetime('now', '-1 day')
          AND u.is_banned = 0
        """
    )

    participants = [row[0] for row in rows]

    if not participants:
        await admin_reply(
            message,
            "За последние 24 часа никто не играл.",
        )
        return

    share = amount / len(participants)

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.executemany(
                """
                UPDATE users
                SET balance = balance + ?
                WHERE user_id = ?
                """,
                [(share, user_id) for user_id in participants],
            )

            await db.executemany(
                """
                INSERT INTO transactions(
                    user_id, amount, currency, transaction_type, description
                ) VALUES(?, ?, 'TOKENS', 'rain', 'Групповой дождь')
                """,
                [(user_id, share) for user_id in participants],
            )

            await db.commit()

    await admin_reply(
        message,
        "🌧 <b>ДОЖДЬ TOKENS!</b>\n\n"
        f"Общая сумма: <b>{format_amount(amount)} TOKENS</b>\n"
        f"Участников: <b>{len(participants)}</b>\n"
        f"Каждому начислено: <b>{format_amount(share)} TOKENS</b>",
    )


@dp.message(F.text.startswith("@"))
async def admin_command_handler(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    command = parts[0].lower()

    if command == "@помощь":
        await admin_reply(message, ADMIN_HELP_TEXT)
        return

    if command == "@стата":
        await admin_stats(message)
        return

    if command == "@скан":
        if len(parts) < 2 or not parts[1].isdigit():
            await admin_reply(message, "Формат: @скан ID")
            return

        await admin_scan(message, int(parts[1]))
        return

    if command == "@выдать":
        if len(parts) < 3:
            await admin_reply(message, "Формат: @выдать ID СУММА")
            return

        try:
            user_id = int(parts[1])
            amount = float(parts[2].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректные параметры.")
            return

        if amount <= 0:
            await admin_reply(message, "Сумма должна быть положительной.")
            return

        if not await get_user(user_id):
            await admin_reply(message, "Пользователь не найден.")
            return

        await credit_user(
            user_id,
            amount,
            "TOKENS",
            "Начисление администратором",
        )

        await admin_reply(
            message,
            f"✅ Начислено {format_amount(amount)} TOKENS пользователю "
            f"<code>{user_id}</code>.",
        )
        return

    if command == "@выдать_крипту":
        if len(parts) < 3:
            await admin_reply(
                message,
                "Формат: @выдать_крипту ID СУММА",
            )
            return

        try:
            user_id = int(parts[1])
            amount = float(parts[2].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректные параметры.")
            return

        if amount <= 0:
            await admin_reply(message, "Сумма должна быть положительной.")
            return

        if not await get_user(user_id):
            await admin_reply(message, "Пользователь не найден.")
            return

        await credit_user(
            user_id,
            amount,
            "TNC",
            "Начисление TNC администратором",
        )

        await admin_reply(
            message,
            f"💎 Начислено {format_amount(amount)} TNC пользователю "
            f"<code>{user_id}</code>.",
        )
        return

    if command == "@дроп":
        if len(parts) < 2:
            await admin_reply(message, "Формат: @дроп СУММА")
            return

        try:
            amount = float(parts[1].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректная сумма.")
            return

        await admin_drop(message, amount)
        return

    if command == "@бан":
        if len(parts) < 3:
            await admin_reply(message, "Формат: @бан ID ЧАСЫ")
            return

        try:
            user_id = int(parts[1])
            hours = float(parts[2].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректные параметры.")
            return

        await admin_ban(message, user_id, hours)
        return

    if command == "@сет_курс":
        if len(parts) < 2:
            await admin_reply(message, "Формат: @сет_курс ЧИСЛО")
            return

        try:
            rate = float(parts[1].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректный курс.")
            return

        if rate <= 0:
            await admin_reply(message, "Курс должен быть больше нуля.")
            return

        await set_setting("token_to_tnc_rate", str(rate))

        await admin_reply(
            message,
            f"✅ Новый курс: <b>1 TNC = {format_amount(rate)} TOKENS</b>",
        )
        return

    if command == "@дождь":
        if len(parts) < 2:
            await admin_reply(message, "Формат: @дождь СУММА")
            return

        try:
            amount = float(parts[1].replace(",", "."))
        except ValueError:
            await admin_reply(message, "Некорректная сумма.")
            return

        await admin_rain(message, amount)
        return

    if command == "@рассылка":
        if len(parts) < 2:
            await admin_reply(message, "Формат: @рассылка ТЕКСТ")
            return

        await admin_broadcast(message, text.split(maxsplit=1)[1])
        return


# ============================================================
# VIP DAILY CASHBACK
# ============================================================

async def process_vip_cashback_for_date(day: str):
    """
    Начисляет VIP 2.5% от чистых проигрышей за указанную дату.
    Дата хранится в UTC. Повторное начисление предотвращается
    отдельной записью в settings.
    """
    marker = f"vip_cashback_{day}"
    already_done = await get_setting(marker)

    if already_done == "done":
        return

    rows = await db_fetchall(
        """
        SELECT
            u.user_id,
            COALESCE(SUM(
                CASE WHEN g.profit < 0 THEN -g.profit ELSE 0 END
            ), 0) AS losses
        FROM users u
        JOIN game_log g ON g.user_id = u.user_id
        WHERE u.is_vip = 1
          AND date(g.created_at) = date(?)
        GROUP BY u.user_id
        """,
        (day,),
    )

    async with DATABASE_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for user_id, losses in rows:
                cashback = round(
                    float(losses) * VIP_CASHBACK_RATE,
                    2,
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
                    INSERT INTO transactions(
                        user_id, amount, currency,
                        transaction_type, description
                    ) VALUES(?, ?, 'TOKENS', 'vip_cashback', ?)
                    """,
                    (
                        user_id,
                        cashback,
                        f"VIP-кешбэк за {day}",
                    ),
                )

                await db.execute(
                    """
                    INSERT INTO bonus(user_id, amount, bonus_type)
                    VALUES(?, ?, 'vip_cashback')
                    """,
                    (user_id, cashback),
                )

            await db.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, 'done')
                ON CONFLICT(key) DO UPDATE SET value = 'done'
                """,
                (marker,),
            )

            await db.commit()

    logger.info(
        "VIP cashback processed for %s; users=%s",
        day,
        len(rows),
    )


async def vip_cashback_scheduler():
    while True:
        now = datetime.now(timezone.utc)

        tomorrow = (
            now + timedelta(days=1)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        seconds = max(
            1,
            (tomorrow - now).total_seconds(),
        )

        await asyncio.sleep(seconds)

        yesterday = (
            datetime.now(timezone.utc).date()
            - timedelta(days=1)
        ).isoformat()

        try:
            await process_vip_cashback_for_date(yesterday)
        except Exception:
            logger.exception("VIP cashback error")


# ============================================================
# TELEGRAM MINI APP INIT DATA VALIDATION
# ============================================================

def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
):
    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = parsed.pop("hash", None)

    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash,
    ):
        return None

    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError:
        return None

    now = int(time.time())

    if auth_date <= 0 or now - auth_date > max_age_seconds:
        return None

    if auth_date > now + 60:
        return None

    try:
        user_data = json.loads(parsed.get("user", "{}"))
    except ValueError:
        return None

    if not isinstance(user_data, dict):
        return None

    try:
        user_id = int(user_data["id"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "user_id": user_id,
        "user": user_data,
        "auth_date": auth_date,
    }


def get_request_init_data(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")

    if header.lower().startswith("tma "):
        return header[4:].strip()

    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData")
        or ""
    )


async def authenticate_webapp_request(request: web.Request):
    init_data = get_request_init_data(request)

    validated = validate_telegram_init_data(
        init_data,
        BOT_TOKEN,
    )

    if not validated:
        raise web.HTTPUnauthorized(
            text=json.dumps(
                {"ok": False, "error": "invalid_init_data"},
            ),
            content_type="application/json",
        )

    return validated


# ============================================================
# WEB APP API
# ============================================================

async def api_user(request: web.Request):
    auth = await authenticate_webapp_request(request)
    user_id = auth["user_id"]

    user = await get_user(user_id)

    if not user:
        raise web.HTTPNotFound(
            text=json.dumps(
                {"ok": False, "error": "user_not_found"},
            ),
            content_type="application/json",
        )

    rate = await get_exchange_rate()

    return web.json_response(
        {
            "ok": True,
            "user_id": user_id,
            "username": user[1],
            "first_name": user[2],
            "balance": user[3],
            "balance_tnc": user[4],
            "referrals": user[5],
            "is_vip": bool(user[9]),
            "exchange_rate": rate,
        }
    )


async def api_swap(request: web.Request):
    auth = await authenticate_webapp_request(request)
    user_id = auth["user_id"]

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {"ok": False, "error": "invalid_json"},
            ),
            content_type="application/json",
        )

    direction = str(payload.get("direction", "")).lower()

    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    if amount <= 0 or amount > 1_000_000_000:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {"ok": False, "error": "invalid_amount"},
            ),
            content_type="application/json",
        )

    rate = await get_exchange_rate()

    if direction == "tokens_to_tnc":
        tnc_amount = amount / rate

        if not await debit_user(
            user_id,
            amount,
            "TOKENS",
            "Mini App: TOKENS to TNC",
        ):
            raise web.HTTPBadRequest(
                text=json.dumps(
                    {"ok": False, "error": "insufficient_tokens"},
                ),
                content_type="application/json",
            )

        await credit_user(
            user_id,
            tnc_amount,
            "TNC",
            "Mini App: TOKENS to TNC",
        )

        result = {
            "spent": amount,
            "received": tnc_amount,
            "spent_currency": "TOKENS",
            "received_currency": "TNC",
        }

    elif direction == "tnc_to_tokens":
        tokens_amount = amount * rate

        if not await debit_user(
            user_id,
            amount,
            "TNC",
            "Mini App: TNC to TOKENS",
        ):
            raise web.HTTPBadRequest(
                text=json.dumps(
                    {"ok": False, "error": "insufficient_tnc"},
                ),
                content_type="application/json",
            )

        await credit_user(
            user_id,
            tokens_amount,
            "TOKENS",
            "Mini App: TNC to TOKENS",
        )

        result = {
            "spent": amount,
            "received": tokens_amount,
            "spent_currency": "TNC",
            "received_currency": "TOKENS",
        }

    else:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {"ok": False, "error": "invalid_direction"},
            ),
            content_type="application/json",
        )

    result["ok"] = True
    result["balance"] = await get_user_balance(user_id)
    result["balance_tnc"] = await get_user_tnc_balance(user_id)

    return web.json_response(result)


# ============================================================
# WEB APP STATIC FILES
# ============================================================

async def serve_webapp(request: web.Request):
    """
    Обслуживает /webapp/ и /webapp/index.html.
    Файл ищется по пути ./webapp/index.html относительно корня проекта.
    """
    if not WEBAPP_INDEX.exists():
        raise web.HTTPNotFound(
            text="Файл webapp/index.html не найден"
        )

    return web.FileResponse(WEBAPP_INDEX)


async def serve_webapp_assets(request: web.Request):
    relative_path = request.match_info.get("path", "")

    requested = (WEBAPP_DIR / relative_path).resolve()
    root = WEBAPP_DIR.resolve()

    try:
        requested.relative_to(root)
    except ValueError:
        raise web.HTTPForbidden()

    if not requested.exists() or not requested.is_file():
        raise web.HTTPNotFound()

    return web.FileResponse(requested)


async def health_check(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "service": "TOKENS",
        }
    )


async def start_web_server():
    app = web.Application(
        client_max_size=1024 * 1024,
    )

    app.router.add_get("/health", health_check)
    app.router.add_get("/api/user", api_user)
    app.router.add_post("/api/swap", api_swap)

    app.router.add_get("/webapp/", serve_webapp)
    app.router.add_get("/webapp/index.html", serve_webapp)
    app.router.add_get(
        "/webapp/{path:.*}",
        serve_webapp_assets,
    )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info("Web server started on port %s", PORT)

    return runner


# ============================================================
# ADDITIONAL COMMANDS
# ============================================================

@dp.message(Command("balance"))
async def balance_command(message: Message):
    if not await ensure_registered(message):
        return

    tokens = await get_user_balance(message.from_user.id)
    tnc = await get_user_tnc_balance(message.from_user.id)

    await message.answer(
        "💼 <b>ТВОЙ БАЛАНС</b>\n\n"
        f"💰 TOKENS: <b>{format_amount(tokens)}</b>\n"
        f"💎 TNC: <b>{format_amount(tnc)}</b>"
    )


@dp.message(Command("cancel"))
async def cancel_command(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "Действие отменено.",
        reply_markup=main_menu_keyboard(),
    )


@dp.message(Command("help"))
async def user_help_command(message: Message):
    await message.answer(
        "📖 <b>КОМАНДЫ TOKENS</b>\n\n"
        "/start — начать работу\n"
        "/balance — баланс\n"
        "/help — помощь\n\n"
        "Игры доступны в группах:\n"
        "кости 100\n"
        "дартс 100\n"
        "баскет 100\n"
        "футбол 100\n"
        "боулинг 100\n"
        "рулетка: 10-20 500\n"
        "старт — запустить рулетку"
    )


# ============================================================
# MESSAGE CLEANUP / USER ACTIVITY
# ============================================================

@dp.message()
async def activity_fallback(message: Message):
    if not message.from_user:
        return

    if message.chat.type == ChatType.PRIVATE:
        await db_execute(
            """
            UPDATE users
            SET last_activity = ?
            WHERE user_id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                message.from_user.id,
            ),
        )


# ============================================================
# APPLICATION LIFECYCLE
# ============================================================

async def main():
    await init_db()

    web_runner = None
    cashback_task = None

    try:
        web_runner = await start_web_server()

        cashback_task = asyncio.create_task(
            vip_cashback_scheduler(),
            name="vip_cashback_scheduler",
        )

        logger.info("Starting TOKENS Telegram bot")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=False,
        )

    finally:
        logger.info("Stopping TOKENS application")

        if cashback_task:
            cashback_task.cancel()

            try:
                await cashback_task
            except asyncio.CancelledError:
                pass

        if web_runner:
            await web_runner.cleanup()

        await bot.session.close()

        logger.info("TOKENS application stopped")


if __name__ == "__main__":
    asyncio.run(main())