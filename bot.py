import asyncio
import hashlib
import hmac
import html
import io
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
from aiogram.enums import ChatType, DiceEmoji, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Dice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "").strip()
PORT = int(os.getenv("PORT", "10000") or 10000)
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support").strip().lstrip("@")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

BASE_DIR = Path(__file__).resolve().parent
WEBAPP_DIR = BASE_DIR / "webapp"
ASSETS_DIR = BASE_DIR / "assets"
DB_PATH = BASE_DIR / "tokens.db"

START_BONUS = 5000
REFERRAL_BONUS = 1000
TNC_RATE = 50000
TNC_STARS_RATE = 10
STAR_TOKENS_RATE = 7500
CAPTCHA_ATTEMPTS = 3
CAPTCHA_BAN_HOURS = 12
VIP_CASHBACK_RATE = 0.025

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("TOKENS")

if not BOT_TOKEN:
    logger.warning("BOT_TOKEN is not configured. Set it in environment variables.")

from aiogram.client.default import DefaultBotProperties

bot = Bot(
    token=BOT_TOKEN or "000000000:PLACEHOLDER",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())

http_app = web.Application()
http_runner = None


# ============================================================
# FSM
# ============================================================

class CaptchaState(StatesGroup):
    waiting = State()


class ExchangeState(StatesGroup):
    waiting_amount = State()


# ============================================================
# DATABASE
# ============================================================

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    balance REAL DEFAULT 0,
    balance_tnc REAL DEFAULT 0,
    referrer_id INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    ban_until INTEGER DEFAULT 0,
    vip INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0,
    last_bonus INTEGER DEFAULT 0,
    last_daily_loss REAL DEFAULT 0,
    captcha_passed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    bet REAL DEFAULT 0,
    payout REAL DEFAULT 0,
    result TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    operation TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bonus (
    user_id INTEGER PRIMARY KEY,
    last_claim INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    payload TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS roulette_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    bet REAL NOT NULL,
    bet_type TEXT NOT NULL,
    bet_value TEXT NOT NULL,
    created_at INTEGER NOT NULL
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
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS quests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    quest_key TEXT NOT NULL,
    progress INTEGER DEFAULT 0,
    completed INTEGER DEFAULT 0,
    claimed INTEGER DEFAULT 0,
    updated_at INTEGER NOT NULL,
    UNIQUE(user_id, quest_key)
);
"""


async def db_connect():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    global DB
    DB = await aiosqlite.connect(DB_PATH)
    DB.row_factory = aiosqlite.Row
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            balance_tnc REAL DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            banned_until INTEGER DEFAULT 0,
            vip INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            description TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    await DB.commit()
    logger.info("Database initialized successfully")

async def get_setting(key: str, default: str = "") -> str:
    async with await db_connect() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return str(row["value"]) if row else default


async def set_setting(key: str, value: str):
    async with await db_connect() as db:
        await db.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, str(value)),
        )
        await db.commit()


async def get_user(user_id: int):
    async with await db_connect() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def get_user_balance(user_id: int) -> float:
    user = await get_user(user_id)
    return float(user["balance"]) if user else 0.0


async def get_user_tnc(user_id: int) -> float:
    user = await get_user(user_id)
    return float(user["balance_tnc"]) if user else 0.0


async def ensure_user(
    user_id: int,
    username: str = "",
    first_name: str = "",
    referrer_id: int = 0,
):
    now = int(time.time())
    async with await db_connect() as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        exists = await cur.fetchone()

        if exists:
            await db.execute(
                "UPDATE users SET username=?, first_name=? WHERE user_id=?",
                (username or "", first_name or "", user_id),
            )
        else:
            if referrer_id == user_id:
                referrer_id = 0

            await db.execute(
                """
                INSERT INTO users(
                    user_id, username, first_name, referrer_id, created_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (user_id, username or "", first_name or "", referrer_id, now),
            )

            if referrer_id:
                cur = await db.execute(
                    "SELECT user_id FROM users WHERE user_id=?",
                    (referrer_id,),
                )
                referrer = await cur.fetchone()
                if referrer:
                    await db.execute(
                        "UPDATE users SET referrals=referrals+1 WHERE user_id=?",
                        (referrer_id,),
                    )
                    await db.execute(
                        "UPDATE users SET balance=balance+? WHERE user_id=?",
                        (REFERRAL_BONUS, referrer_id),
                    )
                    await add_transaction_db(
                        db,
                        referrer_id,
                        "TOKENS",
                        REFERRAL_BONUS,
                        "referral",
                        f"Реферал {user_id}",
                    )

        await db.commit()


async def add_transaction_db(
    db,
    user_id: int,
    currency: str,
    amount: float,
    operation: str,
    description: str = "",
):
    await db.execute(
        """
        INSERT INTO transactions(
            user_id, currency, amount, operation, description, created_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            currency,
            float(amount),
            operation,
            description,
            int(time.time()),
        ),
    )


async def change_balance(
    user_id: int,
    amount: float,
    currency: str = "TOKENS",
    operation: str = "change",
    description: str = "",
):
    column = "balance" if currency.upper() == "TOKENS" else "balance_tnc"

    async with await db_connect() as db:
        cur = await db.execute(
            f"SELECT {column} FROM users WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return False

        new_value = float(row[column]) + float(amount)
        if new_value < -0.0000001:
            return False

        await db.execute(
            f"UPDATE users SET {column}=? WHERE user_id=?",
            (round(new_value, 8), user_id),
        )
        await add_transaction_db(
            db,
            user_id,
            currency.upper(),
            amount,
            operation,
            description,
        )
        await db.commit()
        return True


async def set_balance(
    user_id: int,
    amount: float,
    currency: str = "TOKENS",
    operation: str = "admin_set",
    description: str = "",
):
    column = "balance" if currency.upper() == "TOKENS" else "balance_tnc"
    async with await db_connect() as db:
        await db.execute(
            f"UPDATE users SET {column}=? WHERE user_id=?",
            (max(0, float(amount)), user_id),
        )
        await add_transaction_db(
            db,
            user_id,
            currency.upper(),
            amount,
            operation,
            description,
        )
        await db.commit()


async def is_banned(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False

    if not user["is_banned"]:
        return False

    until = int(user["ban_until"] or 0)
    if until and until <= int(time.time()):
        async with await db_connect() as db:
            await db.execute(
                "UPDATE users SET is_banned=0, ban_until=0 WHERE user_id=?",
                (user_id,),
            )
            await db.commit()
        return False

    return True


async def ban_user(user_id: int, hours: float, reason: str = ""):
    until = int(time.time() + hours * 3600)
    async with await db_connect() as db:
        await db.execute(
            "UPDATE users SET is_banned=1, ban_until=? WHERE user_id=?",
            (until, user_id),
        )
        await db.commit()
    return until


async def unban_user(user_id: int):
    async with await db_connect() as db:
        await db.execute(
            "UPDATE users SET is_banned=0, ban_until=0 WHERE user_id=?",
            (user_id,),
        )
        await db.commit()


async def log_game(
    user_id: int,
    chat_id: int,
    game: str,
    bet: float,
    payout: float,
    result: str,
):
    async with await db_connect() as db:
        await db.execute(
            """
            INSERT INTO game_log(
                user_id, chat_id, game, bet, payout, result, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                chat_id,
                game,
                bet,
                payout,
                result,
                int(time.time()),
            ),
        )
        await db.commit()


# ============================================================
# KEYBOARDS
# ============================================================

def main_reply_keyboard():
    webapp_button = KeyboardButton(
        text="🚀 Открыть TOKENS App",
        web_app=WebAppInfo(url=WEBAPP_URL) if WEBAPP_URL.startswith("https://") else None,
    )

    return ReplyKeyboardMarkup(
        keyboard=[
            [webapp_button],
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
                KeyboardButton(text="🔄 Обменник"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def inline_back(callback_data: str = "main"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]
        ]
    )


def app_button_row():
    if WEBAPP_URL.startswith("https://"):
        return [
            InlineKeyboardButton(
                text="🚀 Открыть App",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    return [
        InlineKeyboardButton(
            text="🌐 Открыть App",
            url=WEBAPP_URL if WEBAPP_URL.startswith("http") else "https://telegram.org",
        )
    ]


def profile_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💼 Кошелек", callback_data="wallet"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="profile_settings"),
            ],
            [
                InlineKeyboardButton(text="💎 Крипта", callback_data="crypto"),
                InlineKeyboardButton(text="🔄 Обменник", callback_data="exchange"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def exchange_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10k → TNC", callback_data="swap:10000"),
                InlineKeyboardButton(text="50k → TNC", callback_data="swap:50000"),
            ],
            [
                InlineKeyboardButton(text="100k → TNC", callback_data="swap:100000"),
                InlineKeyboardButton(text="1 TNC → 50k", callback_data="swap:tnc:1"),
            ],
            [
                InlineKeyboardButton(text="✍️ Своя сумма", callback_data="swap:custom"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def wallet_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обменять", callback_data="exchange"),
                InlineKeyboardButton(text="🚀 Открыть App", url=WEBAPP_URL)
                if WEBAPP_URL.startswith("https://")
                else InlineKeyboardButton(text="🚀 Открыть App", callback_data="main"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")],
        ]
    )


def how_to_play_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Кости", callback_data="help_dice"),
                InlineKeyboardButton(text="🎯 Дартс", callback_data="help_darts"),
            ],
            [
                InlineKeyboardButton(text="🏀 Баскетбол", callback_data="help_basket"),
                InlineKeyboardButton(text="⚽ Футбол", callback_data="help_football"),
            ],
            [
                InlineKeyboardButton(text="🎳 Боулинг", callback_data="help_bowling"),
                InlineKeyboardButton(text="🎡 Рулетка", callback_data="help_roulette"),
            ],
            [
                InlineKeyboardButton(text="💬 Команды", callback_data="help_commands"),
                InlineKeyboardButton(text="👥 Чаты", callback_data="help_chats"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def crypto_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Купить TNC", callback_data="crypto_buy"),
                InlineKeyboardButton(text="💸 Продать TNC", callback_data="crypto_sell"),
            ],
            app_button_row(),
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def shop_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎁 Открыть кейсы", callback_data="shop_cases"),
                InlineKeyboardButton(text="💎 Купить VIP", callback_data="shop_vip"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def quests_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus"),
            ],
            [
                InlineKeyboardButton(text="📋 Мои задания", callback_data="quest_list"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )


def roulette_result_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data="roulette_repeat"),
                InlineKeyboardButton(text="✖️ Удвоить", callback_data="roulette_double"),
            ]
        ]
    )


# ============================================================
# IMAGE GENERATION
# ============================================================

def load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def draw_centered(
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    font,
    fill,
    anchor="mm",
):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def create_gradient_background(width=1100, height=650):
    image = Image.new("RGB", (width, height))
    pixels = image.load()

    for y in range(height):
        for x in range(width):
            ratio = (x + y) / max(1, width + height)
            r = int(8 + 10 * ratio)
            g = int(13 + 12 * ratio)
            b = int(32 + 40 * ratio)
            pixels[x, y] = (r, g, b)

    return image


def add_glow(image: Image.Image, center, radius=180, color=(40, 100, 220)):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x, y = center

    for r in range(radius, 0, -8):
        alpha = max(1, int(3 + (radius - r) / radius * 12))
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=(*color, alpha),
        )

    overlay = overlay.filter(ImageFilter.GaussianBlur(25))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def image_to_bytes(image: Image.Image, fmt="PNG"):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    buffer.seek(0)
    return buffer.getvalue()


def generate_swap_image(amount, from_currency, to_currency):
    width, height = 1100, 650
    image = create_gradient_background(width, height).convert("RGBA")
    image = add_glow(image, (width // 2, 280), 260, (32, 92, 190))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (45, 45, width - 45, height - 45),
        radius=42,
        outline=(220, 177, 75, 210),
        width=3,
        fill=(8, 13, 27, 90),
    )

    draw_centered(
        draw,
        (width // 2, 135),
        "TOKENS EXCHANGE",
        load_font(40, True),
        (231, 194, 105, 255),
    )

    display_amount = f"{amount:,.8f}".rstrip("0").rstrip(".")
    if not display_amount:
        display_amount = "0"

    draw_centered(
        draw,
        (width // 2, 290),
        f"+ {display_amount} {to_currency}",
        load_font(62, True),
        (245, 248, 255, 255),
    )

    draw_centered(
        draw,
        (width // 2, 435),
        f"Обмен {amount:,.8f}".rstrip("0").rstrip(".")
        + f" {from_currency} на {to_currency}",
        load_font(27),
        (180, 196, 222, 255),
    )

    draw_centered(
        draw,
        (width // 2, 530),
        "TOKENS • SECURE EXCHANGE",
        load_font(20, True),
        (220, 177, 75, 255),
    )

    image = Image.alpha_composite(image, overlay)
    return image_to_bytes(image)


def generate_wallet_image(tokens: float, tnc: float):
    width, height = 1100, 650
    image = create_gradient_background(width, height).convert("RGBA")
    image = add_glow(image, (250, 250), 240, (40, 95, 190))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (45, 45, width - 45, height - 45),
        radius=42,
        fill=(8, 14, 31, 205),
        outline=(225, 185, 93, 220),
        width=3,
    )

    draw.text(
        (95, 95),
        "TOKENS WALLET",
        font=load_font(42, True),
        fill=(235, 198, 109, 255),
    )
    draw.text(
        (95, 220),
        "TOKENS",
        font=load_font(25, True),
        fill=(150, 174, 213, 255),
    )
    draw.text(
        (95, 270),
        f"{tokens:,.2f}",
        font=load_font(56, True),
        fill=(248, 250, 255, 255),
    )
    draw.text(
        (95, 390),
        "TNC",
        font=load_font(25, True),
        fill=(150, 174, 213, 255),
    )
    draw.text(
        (95, 435),
        f"{tnc:,.8f}".rstrip("0").rstrip("."),
        font=load_font(48, True),
        fill=(82, 183, 255, 255),
    )

    draw.rounded_rectangle(
        (700, 185, 1000, 465),
        radius=30,
        fill=(17, 38, 72, 230),
        outline=(74, 139, 225, 230),
        width=3,
    )
    draw_centered(
        draw,
        (850, 265),
        "TNC",
        load_font(36, True),
        (230, 191, 100, 255),
    )
    draw_centered(
        draw,
        (850, 350),
        f"{tnc * TNC_STARS_RATE:,.2f} ⭐",
        load_font(32, True),
        (245, 248, 255, 255),
    )

    image = Image.alpha_composite(image, overlay)
    return image_to_bytes(image)


def generate_profile_image(user_id: int, tokens: float, tnc: float):
    width, height = 1000, 520
    image = create_gradient_background(width, height).convert("RGBA")
    image = add_glow(image, (500, 230), 250, (38, 100, 180))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (35, 35, 965, 485),
        radius=35,
        fill=(7, 15, 33, 210),
        outline=(224, 181, 91, 220),
        width=3,
    )
    draw_centered(
        draw,
        (500, 125),
        "TOKENS PROFILE",
        load_font(42, True),
        (235, 195, 102, 255),
    )
    draw_centered(
        draw,
        (500, 230),
        f"ID: {user_id}",
        load_font(30, True),
        (232, 238, 250, 255),
    )
    draw_centered(
        draw,
        (500, 320),
        f"{tokens:,.0f} TOKENS  •  {tnc:,.4f} TNC",
        load_font(31, True),
        (105, 190, 255, 255),
    )

    return image_to_bytes(Image.alpha_composite(image, overlay))


def generate_error_image(message: str = "Что-то пошло не так"):
    width, height = 900, 450
    image = create_gradient_background(width, height).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (35, 35, 865, 415),
        radius=35,
        fill=(28, 13, 24, 220),
        outline=(220, 75, 90, 220),
        width=3,
    )
    draw_centered(
        draw,
        (450, 170),
        "TOKENS",
        load_font(48, True),
        (255, 110, 120, 255),
    )
    draw_centered(
        draw,
        (450, 270),
        message[:60],
        load_font(27, True),
        (245, 235, 240, 255),
    )
    return image_to_bytes(Image.alpha_composite(image, overlay))


def generate_captcha_image(code: str):
    width, height = 650, 260
    image = Image.new("RGB", (width, height), (10, 17, 36))
    draw = ImageDraw.Draw(image)

    for _ in range(45):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = x1 + random.randint(-100, 100)
        y2 = y1 + random.randint(-50, 50)
        draw.line(
            (x1, y1, x2, y2),
            fill=(
                random.randint(25, 70),
                random.randint(45, 100),
                random.randint(90, 160),
            ),
            width=random.randint(1, 3),
        )

    font = load_font(112, True)
    x = 105

    for digit in code:
        y = random.randint(75, 130)
        draw.text(
            (x, y),
            digit,
            font=font,
            fill=(
                random.randint(200, 255),
                random.randint(185, 230),
                random.randint(100, 180),
            ),
        )
        x += 115

    draw.rounded_rectangle(
        (8, 8, width - 8, height - 8),
        radius=20,
        outline=(220, 180, 90),
        width=3,
    )

    return image_to_bytes(image)


# ============================================================
# SHARED HELPERS
# ============================================================

async def safe_edit_text(message: Message, text: str, reply_markup=None):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Edit text failed: %s", exc)


async def safe_edit_caption(message: Message, caption: str, reply_markup=None):
    try:
        await message.edit_caption(
            caption=caption,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        logger.warning("Edit caption failed: %s", exc)


async def safe_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def edit_or_send(
    callback: CallbackQuery,
    text: str,
    keyboard=None,
):
    if callback.message:
        await safe_edit_text(callback.message, text, keyboard)


async def send_main_menu(message: Message, text="Добро пожаловать в TOKENS!"):
    photo_path = ASSETS_DIR / "start.jpg"

    if photo_path.is_file():
        try:
            await message.answer_photo(
                BufferedInputFile(photo_path.read_bytes(), filename="start.jpg"),
                caption=text,
                reply_markup=main_reply_keyboard(),
            )
            return
        except Exception as exc:
            logger.warning("Cannot send start.jpg: %s", exc)

    await message.answer(text, reply_markup=main_reply_keyboard())


def format_number(value: float, decimals=2):
    return f"{float(value):,.{decimals}f}"


async def current_tnc_rate():
    try:
        return float(await get_setting("tnc_rate", str(TNC_RATE)))
    except (TypeError, ValueError):
        return float(TNC_RATE)


async def notify_admin(text: str):
    if not ADMIN_ID:
        return
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


# ============================================================
# CAPTCHA AND START
# ============================================================

def parse_referral_argument(text: str) -> int:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return 0

    argument = parts[1].strip()
    if argument.startswith("ref_"):
        argument = argument[4:]

    try:
        return int(argument)
    except ValueError:
        return 0


async def send_captcha(message: Message, state: FSMContext):
    code = "".join(str(random.randint(0, 9)) for _ in range(4))
    image = generate_captcha_image(code)

    await state.update_data(
        captcha_code=code,
        captcha_attempts=0,
    )
    await state.set_state(CaptchaState.waiting)

    sent = await message.answer_photo(
        BufferedInputFile(image, filename="captcha.png"),
        caption=(
            "🔐 <b>Проверка безопасности</b>\n\n"
            "Введи 4 цифры с картинки одним сообщением."
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.update_data(captcha_message_id=sent.message_id)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if not message.from_user:
        return

    user = message.from_user
    referrer_id = parse_referral_argument(message.text or "")

    await ensure_user(
        user.id,
        user.username or "",
        user.first_name or "",
        referrer_id,
    )

    if await is_banned(user.id):
        record = await get_user(user.id)
        until = datetime.fromtimestamp(
            int(record["ban_until"]),
            tz=timezone.utc,
        ).strftime("%d.%m.%Y %H:%M UTC")
        await message.answer(f"⛔ Доступ ограничен до {until}.")
        return

    record = await get_user(user.id)
    if record and record["captcha_passed"]:
        await send_main_menu(message)
        return

    await send_captcha(message, state)


@dp.message(CaptchaState.waiting, F.text)
async def captcha_input(message: Message, state: FSMContext):
    if not message.from_user:
        return

    user_id = message.from_user.id

    if await is_banned(user_id):
        await safe_delete(message)
        return

    data = await state.get_data()
    expected = str(data.get("captcha_code", ""))
    attempts = int(data.get("captcha_attempts", 0))
    old_message_id = data.get("captcha_message_id")

    entered = (message.text or "").strip()
    await safe_delete(message)

    if entered == expected and expected:
        if old_message_id:
            try:
                await bot.delete_message(message.chat.id, old_message_id)
            except Exception:
                pass

        await state.clear()

        async with await db_connect() as db:
            await db.execute(
                "UPDATE users SET captcha_passed=1, balance=balance+? WHERE user_id=?",
                (START_BONUS, user_id),
            )
            await add_transaction_db(
                db,
                user_id,
                "TOKENS",
                START_BONUS,
                "welcome_bonus",
                "Бонус за прохождение капчи",
            )
            await db.commit()

        await message.answer(
            f"✅ Проверка пройдена! Начислено <b>{START_BONUS:,} TOKENS</b>."
        )
        await send_main_menu(message, "🚀 Добро пожаловать в TOKENS!")
        return

    attempts += 1

    if old_message_id:
        try:
            await bot.delete_message(message.chat.id, old_message_id)
        except Exception:
            pass

    if attempts >= CAPTCHA_ATTEMPTS:
        await state.clear()
        await ban_user(user_id, CAPTCHA_BAN_HOURS, "captcha")
        await message.answer(
            "⛔ Три неверные попытки. Доступ заблокирован на 12 часов.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.update_data(captcha_attempts=attempts)
    await send_captcha(message, state)
    await state.update_data(captcha_attempts=attempts)


@dp.message(CaptchaState.waiting)
async def captcha_non_text(message: Message):
    await safe_delete(message)
    await message.answer("Введи именно четыре цифры текстовым сообщением.")


# ============================================================
# MAIN MENU MESSAGE HANDLERS
# ============================================================

@dp.message(F.text == "👤 Профиль")
async def profile_message(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала отправь /start.")
        return

    tokens = float(user["balance"])
    tnc = float(user["balance_tnc"])
    image = generate_profile_image(user_id, tokens, tnc)

    await message.answer_photo(
        BufferedInputFile(image, filename="profile.png"),
        caption=(
            f"👤 <b>Профиль TOKENS</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💰 TOKENS: <b>{format_number(tokens)}</b>\n"
            f"💎 TNC: <b>{format_number(tnc, 8)}</b>\n"
            f"👥 Рефералы: <b>{user['referrals']}</b>\n"
            f"💎 VIP: {'Да' if user['vip'] else 'Нет'}"
        ),
        reply_markup=profile_keyboard(),
    )


@dp.message(F.text == "🎁 Бонус")
async def bonus_message(message: Message):
    path = ASSETS_DIR / "bonus.jpg"
    caption = (
        "🎁 <b>Бонус TOKENS</b>\n\n"
        "Забирай ежедневную награду и выполняй задания."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать бонус", callback_data="daily_bonus")],
            [InlineKeyboardButton(text="📋 Задания", callback_data="quest_list")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
        ]
    )

    if path.is_file():
        await message.answer_photo(
            BufferedInputFile(path.read_bytes(), filename="bonus.jpg"),
            caption=caption,
            reply_markup=keyboard,
        )
    else:
        await message.answer(caption, reply_markup=keyboard)


@dp.message(F.text == "🏆 Топ")
async def top_message(message: Message):
    await show_top_message(message)


@dp.message(F.text == "🔗 Рефералка")
async def referral_message(message: Message):
    user_id = message.from_user.id
    me = await bot.get_me()
    username = me.username or "TOKENS_BOT"
    user = await get_user(user_id)
    referrals = int(user["referrals"]) if user else 0
    link = f"https://t.me/{username}?start=ref_{user_id}"

    await message.answer(
        "🔗 <b>Реферальная программа</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: <b>{referrals}</b>\n"
        f"Награда за приглашённого: <b>{REFERRAL_BONUS:,} TOKENS</b>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
            ]
        ),
    )


@dp.message(F.text == "🎮 Как играть?")
async def how_to_play_message(message: Message):
    path = ASSETS_DIR / "how_to_play.jpg"
    caption = (
        "🎮 <b>Как играть в TOKENS</b>\n\n"
        "Игры доступны в групповых чатах, где добавлен бот.\n"
        "Выбери игру ниже, чтобы посмотреть правила."
    )
    keyboard = how_to_play_keyboard()

    if path.is_file():
        await message.answer_photo(
            BufferedInputFile(path.read_bytes(), filename="how_to_play.jpg"),
            caption=caption,
            reply_markup=keyboard,
        )
    else:
        await message.answer(caption, reply_markup=keyboard)


@dp.message(F.text == "💎 Крипта")
async def crypto_message(message: Message):
    rate = await current_tnc_rate()
    await message.answer(
        "💎 <b>TOKENS Crypto</b>\n\n"
        f"Текущий курс: <b>1 TNC = {rate:,.0f} TOKENS</b>\n"
        "TNC — внутренняя расчётная валюта TOKENS.",
        reply_markup=crypto_keyboard(),
    )


@dp.message(F.text == "🔄 Обменник")
async def exchange_message(message: Message):
    rate = await current_tnc_rate()
    await message.answer(
        "🔄 <b>Обменник TOKENS</b>\n\n"
        f"Курс: <b>1 TNC = {rate:,.0f} TOKENS</b>\n\n"
        "Выбери сумму для обмена. Комиссия не взимается.",
        reply_markup=exchange_keyboard(),
    )


# ============================================================
# INLINE NAVIGATION
# ============================================================

@dp.callback_query(F.data == "main")
async def callback_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_or_send(
        callback,
        "🏠 <b>Главное меню TOKENS</b>\n\n"
        "Используй кнопки меню под полем ввода для перехода по разделам.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
                [InlineKeyboardButton(text="💎 Крипта", callback_data="crypto")],
                [InlineKeyboardButton(text="🔄 Обменник", callback_data="exchange")],
                [InlineKeyboardButton(text="🎮 Как играть?", callback_data="how_to_play")],
            ]
        ),
    )


@dp.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)

    if not user:
        await edit_or_send(callback, "Профиль не найден. Отправь /start.")
        return

    tokens = float(user["balance"])
    tnc = float(user["balance_tnc"])
    image = generate_profile_image(callback.from_user.id, tokens, tnc)

    try:
        await callback.message.edit_media(
            media=__import__("aiogram").types.InputMediaPhoto(
                media=BufferedInputFile(image, filename="profile.png"),
                caption=(
                    "👤 <b>Профиль TOKENS</b>\n\n"
                    f"🆔 ID: <code>{callback.from_user.id}</code>\n"
                    f"💰 TOKENS: <b>{format_number(tokens)}</b>\n"
                    f"💎 TNC: <b>{format_number(tnc, 8)}</b>\n"
                    f"👥 Рефералы: <b>{user['referrals']}</b>\n"
                    f"💎 VIP: {'Да' if user['vip'] else 'Нет'}"
                ),
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=profile_keyboard(),
        )
    except Exception:
        await edit_or_send(
            callback,
            (
                "👤 <b>Профиль TOKENS</b>\n\n"
                f"💰 TOKENS: <b>{format_number(tokens)}</b>\n"
                f"💎 TNC: <b>{format_number(tnc, 8)}</b>"
            ),
            profile_keyboard(),
        )


@dp.callback_query(F.data == "how_to_play")
async def callback_how_to_play(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "🎮 <b>Как играть в TOKENS</b>\n\n"
        "Игры доступны в группах. Выбери нужную игру:",
        how_to_play_keyboard(),
    )


@dp.callback_query(F.data.startswith("help_"))
async def callback_game_help(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split("_", 1)[1]

    descriptions = {
        "dice": "🎲 <b>Кости</b>\n\nСтавка списывается до броска. При победе выплата составляет x2 от ставки.",
        "darts": "🎯 <b>Дартс</b>\n\nПопадание в цель определяется результатом броска Telegram. Победа — x2.",
        "basket": "🏀 <b>Баскетбол</b>\n\nМножители зависят от результата броска: 0, 1, 1.5, 1.8 или 2.",
        "football": "⚽ <b>Футбол</b>\n\nМножители зависят от результата броска: 0, 1, 1.5, 1.8 или 2.",
        "bowling": "🎳 <b>Боулинг</b>\n\nПри успешном результате выплата составляет x2 от ставки.",
        "roulette": "🎡 <b>Рулетка</b>\n\nСтавки: <code>к 1000</code> на красное, <code>ч 1000</code> на чёрное, <code>10-20 500</code> на диапазон чисел. Запуск — <code>старт</code>.",
        "commands": "💬 <b>Команды игр</b>\n\nВ группе используй:\n<code>кости 100</code>\n<code>дартс 100</code>\n<code>баскет 100</code>\n<code>футбол 100</code>\n<code>боулинг 100</code>\n\nРулетка: <code>к 1000</code>, <code>10-20 500</code>, затем <code>старт</code>.",
        "chats": "👥 <b>Игровые чаты</b>\n\nДобавь бота в группу, выдай право отправлять сообщения и запускай игры командами.",
    }

    text = descriptions.get(key, "Информация пока недоступна.")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К правилам", callback_data="how_to_play")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main")],
        ]
    )
    await edit_or_send(callback, text, keyboard)


@dp.callback_query(F.data == "crypto")
async def callback_crypto(callback: CallbackQuery):
    await callback.answer()
    rate = await current_tnc_rate()
    await edit_or_send(
        callback,
        "💎 <b>TOKENS Crypto</b>\n\n"
        f"Текущий курс: <b>1 TNC = {rate:,.0f} TOKENS</b>\n"
        "Баланс TNC хранится отдельно от TOKENS.",
        crypto_keyboard(),
    )


@dp.callback_query(F.data == "exchange")
async def callback_exchange(callback: CallbackQuery):
    await callback.answer()
    rate = await current_tnc_rate()
    await edit_or_send(
        callback,
        "🔄 <b>Обменник TOKENS</b>\n\n"
        f"Курс: <b>1 TNC = {rate:,.0f} TOKENS</b>\n"
        "Выбери направление обмена:",
        exchange_keyboard(),
    )


@dp.callback_query(F.data == "shop")
async def callback_shop(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "🛍 <b>Магазин TOKENS</b>\n\n"
        "Выбери доступную покупку:",
        shop_keyboard(),
    )


@dp.callback_query(F.data == "quests")
async def callback_quests(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "📋 <b>Задания TOKENS</b>\n\n"
        "Выполняй ежедневные задания и получай награды.",
        quests_keyboard(),
    )


# ============================================================
# WALLET
# ============================================================

@dp.callback_query(F.data == "wallet")
async def callback_wallet(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)

    if not user:
        await edit_or_send(callback, "Пользователь не найден.")
        return

    tokens = float(user["balance"])
    tnc = float(user["balance_tnc"])
    stars = tnc * TNC_STARS_RATE + tokens / STAR_TOKENS_RATE

    caption = (
        f"💼 <b>Твой баланс:</b> {format_number(tokens)} TOKENS, "
        f"{format_number(tnc, 8)} TNC.\n\n"
        f"В Stars: <b>{format_number(stars)} ⭐</b>\n"
        "Курс: 1 TNC = 10 Stars, 1 Star = 7500 TOKENS."
    )

    image = generate_wallet_image(tokens, tnc)

    try:
        await callback.message.edit_media(
            media=__import__("aiogram").types.InputMediaPhoto(
                media=BufferedInputFile(image, filename="wallet.png"),
                caption=caption,
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=wallet_keyboard(),
        )
    except Exception:
        await edit_or_send(callback, caption, wallet_keyboard())


# ============================================================
# EXCHANGE
# ============================================================

async def execute_tokens_to_tnc(user_id: int, tokens_amount: float):
    if tokens_amount <= 0:
        return False, 0.0

    rate = await current_tnc_rate()
    tnc_amount = tokens_amount / rate

    async with await db_connect() as db:
        cur = await db.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (user_id,),
        )
        user = await cur.fetchone()

        if not user or float(user["balance"]) < tokens_amount:
            return False, 0.0

        await db.execute(
            "UPDATE users SET balance=balance-?, balance_tnc=balance_tnc+? WHERE user_id=?",
            (tokens_amount, tnc_amount, user_id),
        )
        await add_transaction_db(
            db,
            user_id,
            "TOKENS",
            -tokens_amount,
            "exchange_out",
            "Обмен TOKENS на TNC",
        )
        await add_transaction_db(
            db,
            user_id,
            "TNC",
            tnc_amount,
            "exchange_in",
            "Обмен TOKENS на TNC",
        )
        await db.commit()

    return True, tnc_amount


async def execute_tnc_to_tokens(user_id: int, tnc_amount: float):
    if tnc_amount <= 0:
        return False, 0.0

    rate = await current_tnc_rate()
    tokens_amount = tnc_amount * rate

    async with await db_connect() as db:
        cur = await db.execute(
            "SELECT balance_tnc FROM users WHERE user_id=?",
            (user_id,),
        )
        user = await cur.fetchone()

        if not user or float(user["balance_tnc"]) < tnc_amount:
            return False, 0.0

        await db.execute(
            "UPDATE users SET balance_tnc=balance_tnc-?, balance=balance+? WHERE user_id=?",
            (tnc_amount, tokens_amount, user_id),
        )
        await add_transaction_db(
            db,
            user_id,
            "TNC",
            -tnc_amount,
            "exchange_out",
            "Обмен TNC на TOKENS",
        )
        await add_transaction_db(
            db,
            user_id,
            "TOKENS",
            tokens_amount,
            "exchange_in",
            "Обмен TNC на TOKENS",
        )
        await db.commit()

    return True, tokens_amount


async def send_exchange_result(
    message: Message,
    input_amount: float,
    from_currency: str,
    output_amount: float,
    to_currency: str,
):
    image = generate_swap_image(output_amount, from_currency, to_currency)
    await message.answer_photo(
        BufferedInputFile(image, filename="exchange.png"),
        caption=(
            "✅ <b>Успешный обмен!</b>\n\n"
            f"Списано: <b>{format_number(input_amount, 8)} {from_currency}</b>\n"
            f"Получено: <b>{format_number(output_amount, 8)} {to_currency}</b>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Ещё обмен", callback_data="exchange")],
                [InlineKeyboardButton(text="💼 Кошелек", callback_data="wallet")],
            ]
        ),
    )


@dp.callback_query(F.data.startswith("swap:"))
async def callback_swap(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(":")

    if len(parts) == 2 and parts[1] == "custom":
        await state.set_state(ExchangeState.waiting_amount)
        await callback.message.answer(
            "Введи сумму TOKENS для обмена на TNC:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if len(parts) == 3 and parts[1] == "tnc":
        try:
            tnc_amount = float(parts[2])
        except ValueError:
            await callback.answer("Некорректная сумма", show_alert=True)
            return

        success, output = await execute_tnc_to_tokens(
            callback.from_user.id,
            tnc_amount,
        )

        if not success:
            await callback.answer("Недостаточно TNC на балансе", show_alert=True)
            return

        await callback.message.answer_photo(
            BufferedInputFile(
                generate_swap_image(output, "TNC", "TOKENS"),
                filename="exchange.png",
            ),
            caption=(
                "✅ <b>Успешный обмен!</b>\n\n"
                f"Списано: {tnc_amount:g} TNC\n"
                f"Получено: {format_number(output)} TOKENS"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Ещё обмен", callback_data="exchange")],
                    [InlineKeyboardButton(text="💼 Кошелек", callback_data="wallet")],
                ]
            ),
        )
        return

    if len(parts) == 2:
        try:
            amount = float(parts[1])
        except ValueError:
            await callback.answer("Некорректная сумма", show_alert=True)
            return

        success, output = await execute_tokens_to_tnc(
            callback.from_user.id,
            amount,
        )

        if not success:
            await callback.answer("Недостаточно TOKENS на балансе", show_alert=True)
            return

        await callback.message.answer_photo(
            BufferedInputFile(
                generate_swap_image(output, "TOKENS", "TNC"),
                filename="exchange.png",
            ),
            caption=(
                "✅ <b>Успешный обмен!</b>\n\n"
                f"Списано: {format_number(amount)} TOKENS\n"
                f"Получено: {format_number(output, 8)} TNC"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Ещё обмен", callback_data="exchange")],
                    [InlineKeyboardButton(text="💼 Кошелек", callback_data="wallet")],
                ]
            ),
        )


@dp.message(ExchangeState.waiting_amount, F.text)
async def custom_exchange_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer("Введи корректное число, например 25000.")
        return

    if amount <= 0 or amount > 10**12:
        await message.answer("Сумма должна быть положительным числом.")
        return

    success, output = await execute_tokens_to_tnc(message.from_user.id, amount)

    if not success:
        await message.answer("Недостаточно TOKENS на балансе.")
        return

    await state.clear()
    await send_exchange_result(
        message,
        amount,
        "TOKENS",
        output,
        "TNC",
    )
    await message.answer(
        "Обмен завершён.",
        reply_markup=main_reply_keyboard(),
    )


# ============================================================
# CRYPTO AND SHOP CALLBACKS
# ============================================================

@dp.callback_query(F.data == "crypto_buy")
async def crypto_buy(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "💰 <b>Покупка TNC</b>\n\n"
        "Покупка через платёжного провайдера пока не подключена. "
        "Обратись в поддержку для уточнения условий.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="💬 Поддержка",
                    url=f"https://t.me/{SUPPORT_USERNAME}",
                )],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="crypto")],
            ]
        ),
    )


@dp.callback_query(F.data == "crypto_sell")
async def crypto_sell(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "💸 <b>Продажа TNC</b>\n\n"
        "Для обмена TNC на TOKENS открой обменник.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обменник", callback_data="exchange")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="crypto")],
            ]
        ),
    )


@dp.callback_query(F.data == "profile_settings")
async def profile_settings(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "⚙️ <b>Настройки профиля</b>\n\n"
        "Настройки аккаунта TOKENS.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить профиль", callback_data="profile")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")],
            ]
        ),
    )


@dp.callback_query(F.data == "shop_cases")
async def shop_cases(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "🎁 <b>Кейсы</b>\n\n"
        "Кейсы временно недоступны.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="shop")],
            ]
        ),
    )


@dp.callback_query(F.data == "shop_vip")
async def shop_vip(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        "💎 <b>TOKENS VIP</b>\n\n"
        "VIP предоставляет ежедневный кэшбэк 2.5% от чистого игрового убытка.\n"
        "Активация VIP выполняется администратором.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="shop")],
            ]
        ),
    )


# ============================================================
# DAILY BONUS AND QUESTS
# ============================================================

async def claim_daily_bonus(user_id: int):
    now = int(time.time())
    day = 86400

    async with await db_connect() as db:
        cur = await db.execute(
            "SELECT last_claim, streak FROM bonus WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()

        if row and now - int(row["last_claim"]) < day:
            return False, day - (now - int(row["last_claim"]))

        streak = 1
        if row and now - int(row["last_claim"]) < day * 2:
            streak = int(row["streak"]) + 1

        reward = min(1000 + (streak - 1) * 100, 5000)

        await db.execute(
            """
            INSERT INTO bonus(user_id, last_claim, streak)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_claim=excluded.last_claim,
                streak=excluded.streak
            """,
            (user_id, now, streak),
        )
        await db.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (reward, user_id),
        )
        await add_transaction_db(
            db,
            user_id,
            "TOKENS",
            reward,
            "daily_bonus",
            f"Ежедневный бонус, серия {streak}",
        )
        await db.commit()

    return True, reward


@dp.callback_query(F.data == "daily_bonus")
async def callback_daily_bonus(callback: CallbackQuery):
    await callback.answer()
    success, value = await claim_daily_bonus(callback.from_user.id)

    if success:
        text = (
            "🎁 <b>Бонус получен!</b>\n\n"
            f"Начислено: <b>{value:,} TOKENS</b>."
        )
    else:
        hours = value // 3600
        minutes = (value % 3600) // 60
        text = (
            "⏳ <b>Бонус уже получен.</b>\n\n"
            f"Следующий бонус будет доступен через {hours} ч. {minutes} мин."
        )

    await edit_or_send(
        callback,
        text,
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Задания", callback_data="quest_list")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
            ]
        ),
    )


@dp.callback_query(F.data == "quest_list")
async def callback_quest_list(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    now = int(time.time())

    quests = [
        ("first_game", "Сыграть одну игру", 1, 500),
        ("three_games", "Сыграть три игры", 3, 1500),
        ("invite_friend", "Пригласить друга", 1, 1000),
    ]

    async with await db_connect() as db:
        for key, title, target, reward in quests:
            await db.execute(
                """
                INSERT OR IGNORE INTO quests(
                    user_id, quest_key, progress, completed, claimed, updated_at
                ) VALUES(?, ?, 0, 0, 0, ?)
                """,
                (user_id, key, now),
            )

        cur = await db.execute(
            "SELECT quest_key, progress, completed, claimed FROM quests WHERE user_id=?",
            (user_id,),
        )
        rows = await cur.fetchall()
        await db.commit()

    state_map = {row["quest_key"]: row for row in rows}
    lines = ["📋 <b>Твои задания</b>\n"]

    for key, title, target, reward in quests:
        row = state_map.get(key)
        progress = int(row["progress"]) if row else 0
        completed = bool(row["completed"]) if row else False
        claimed = bool(row["claimed"]) if row else False

        status = "✅ Получено" if claimed else (
            "🎁 Готово к получению" if completed else f"{progress}/{target}"
        )
        lines.append(f"• {title}: {status} — {reward:,} TOKENS")

    await edit_or_send(
        callback,
        "\n".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Забрать награды", callback_data="quest_claim")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
            ]
        ),
    )


@dp.callback_query(F.data == "quest_claim")
async def callback_quest_claim(callback: CallbackQuery):
    await callback.answer()
    rewards = {
        "first_game": 500,
        "three_games": 1500,
        "invite_friend": 1000,
    }

    total = 0

    async with await db_connect() as db:
        for key, reward in rewards.items():
            cur = await db.execute(
                """
                SELECT completed, claimed FROM quests
                WHERE user_id=? AND quest_key=?
                """,
                (callback.from_user.id, key),
            )
            row = await cur.fetchone()

            if row and row["completed"] and not row["claimed"]:
                await db.execute(
                    """
                    UPDATE quests SET claimed=1
                    WHERE user_id=? AND quest_key=?
                    """,
                    (callback.from_user.id, key),
                )
                total += reward

        if total:
            await db.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (total, callback.from_user.id),
            )
            await add_transaction_db(
                db,
                callback.from_user.id,
                "TOKENS",
                total,
                "quest_reward",
                "Награда за задания",
            )

        await db.commit()

    await edit_or_send(
        callback,
        f"🎁 Получено наград: <b>{total:,} TOKENS</b>.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 К заданиям", callback_data="quest_list")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
            ]
        ),
    )


async def update_quest_progress(user_id: int, quest_key: str, amount: int = 1):
    now = int(time.time())
    targets = {
        "first_game": 1,
        "three_games": 3,
        "invite_friend": 1,
    }

    target = targets.get(quest_key)
    if not target:
        return

    async with await db_connect() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO quests(
                user_id, quest_key, progress, completed, claimed, updated_at
            ) VALUES(?, ?, 0, 0, 0, ?)
            """,
            (user_id, quest_key, now),
        )

        await db.execute(
            """
            UPDATE quests
            SET progress=MIN(progress+?, ?),
                completed=CASE WHEN MIN(progress+?, ?) >= ? THEN 1 ELSE completed END,
                updated_at=?
            WHERE user_id=? AND quest_key=? AND claimed=0
            """,
            (
                amount,
                target,
                amount,
                target,
                target,
                now,
                user_id,
                quest_key,
            ),
        )
        await db.commit()


# ============================================================
# TOP LIST
# ============================================================

async def build_top_text():
    async with await db_connect() as db:
        cur = await db.execute(
            """
            SELECT user_id, username, first_name, balance
            FROM users
            ORDER BY balance DESC
            LIMIT 10
            """
        )
        tokens_rows = await cur.fetchall()

        cur = await db.execute(
            """
            SELECT user_id, username, first_name, balance_tnc
            FROM users
            ORDER BY balance_tnc DESC
            LIMIT 10
            """
        )
        tnc_rows = await cur.fetchall()

    lines = ["🏆 <b>ТОП TOKENS</b>\n", "💰 <b>По TOKENS</b>"]

    for index, row in enumerate(tokens_rows, 1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        name = html.escape(str(name))
        lines.append(
            f"{index}. {name} — <b>{float(row['balance']):,.0f}</b>"
        )

    lines.append("\n💎 <b>По TNC</b>")

    for index, row in enumerate(tnc_rows, 1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        name = html.escape(str(name))
        lines.append(
            f"{index}. {name} — <b>{float(row['balance_tnc']):,.6f}</b>"
        )

    return "\n".join(lines)


async def show_top_message(message: Message):
    await message.answer(
        await build_top_text(),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
            ]
        ),
    )


@dp.callback_query(F.data == "top")
async def callback_top(callback: CallbackQuery):
    await callback.answer()
    await edit_or_send(
        callback,
        await build_top_text(),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
            ]
        ),
    )


# ============================================================
# GROUP GAMES
# ============================================================

GAME_EMOJIS = {
    "dice": DiceEmoji.DICE,
    "darts": DiceEmoji.DART,
    "bowling": DiceEmoji.BOWLING,
    "basketball": DiceEmoji.BASKETBALL,
    "football": DiceEmoji.FOOTBALL,
}

GAME_NAMES = {
    "dice": "Кости",
    "darts": "Дартс",
    "bowling": "Боулинг",
    "basketball": "Баскетбол",
    "football": "Футбол",
}

GAME_ALIASES = {
    "кости": "dice",
    "кость": "dice",
    "кубик": "dice",
    "дартс": "darts",
    "баскет": "basketball",
    "баскетбол": "basketball",
    "футбол": "football",
    "боулинг": "bowling",
}


def parse_bet_from_text(text: str):
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None

    try:
        amount = float(parts[1].replace(",", "."))
    except ValueError:
        return None

    if amount <= 0 or amount > 10**12:
        return None

    return amount


def game_multiplier(game: str, value: int):
    if game in ("dice", "darts", "bowling"):
        if game == "dice":
            return 2.0 if value >= 4 else 0.0
        if game == "darts":
            return 2.0 if value >= 3 else 0.0
        if game == "bowling":
            return 2.0 if value >= 4 else 0.0

    if game == "basketball":
        mapping = {
            1: 0.0,
            2: 1.0,
            3: 1.5,
            4: 1.8,
            5: 2.0,
        }
        return mapping.get(value, 0.0)

    if game == "football":
        mapping = {
            1: 0.0,
            2: 1.0,
            3: 1.5,
            4: 1.8,
            5: 2.0,
        }
        return mapping.get(value, 0.0)

    return 0.0


async def play_group_game(message: Message, game: str, bet: float):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply("Игры доступны только в группах.")
        return

    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply("⛔ Твой аккаунт заблокирован.")
        return

    user = await get_user(user_id)
    if not user or not user["captcha_passed"]:
        await message.reply("Сначала пройди проверку в личном чате с ботом: /start")
        return

    if bet <= 0:
        await message.reply("Ставка должна быть больше нуля.")
        return

    if float(user["balance"]) < bet:
        await message.reply("Недостаточно TOKENS для ставки.")
        return

    success = await change_balance(
        user_id,
        -bet,
        "TOKENS",
        "game_bet",
        f"Ставка: {game}",
    )
    if not success:
        await message.reply("Не удалось списать ставку.")
        return

    dice_message = await message.answer_dice(emoji=GAME_EMOJIS[game])
    value = dice_message.dice.value
    multiplier = game_multiplier(game, value)
    payout = bet * multiplier

    if payout > 0:
        await change_balance(
            user_id,
            payout,
            "TOKENS",
            "game_payout",
            f"Выигрыш: {game}, x{multiplier}",
        )

    net = payout - bet
    result = (
        f"🎮 <b>{GAME_NAMES[game]}</b>\n\n"
        f"Игрок: {html.escape(message.from_user.full_name)}\n"
        f"Ставка: <b>{bet:,.2f} TOKENS</b>\n"
        f"Множитель: <b>x{multiplier:g}</b>\n"
        f"Выплата: <b>{payout:,.2f} TOKENS</b>\n"
        f"Итог: <b>{net:+,.2f} TOKENS</b>"
    )

    await message.answer(result)
    await log_game(
        user_id,
        message.chat.id,
        game,
        bet,
        payout,
        f"value={value};multiplier={multiplier}",
    )
    await update_quest_progress(user_id, "first_game", 1)
    await update_quest_progress(user_id, "three_games", 1)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def group_game_commands(message: Message):
    if not message.from_user or not message.text:
        return

    text = message.text.strip()
    lowered = text.lower()

    if lowered.startswith("@"):
        return

    parts = lowered.split()
    if len(parts) < 2:
        return

    game = GAME_ALIASES.get(parts[0])
    if not game:
        return

    bet = parse_bet_from_text(text)
    if bet is None:
        await message.reply("Формат: <code>кости 100</code>")
        return

    await play_group_game(message, game, bet)


# ============================================================
# ROULETTE
# ============================================================

ROULETTE_RED = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
}
ROULETTE_BLACK = set(range(1, 37)) - ROULETTE_RED


def roulette_color(number: int):
    if number == 0:
        return "green"
    return "red" if number in ROULETTE_RED else "black"


def parse_roulette_bet(text: str):
    text = (text or "").strip().lower()
    parts = text.split()

    if len(parts) != 2:
        return None

    bet_text = parts[-1]
    try:
        amount = float(bet_text.replace(",", "."))
    except ValueError:
        return None

    if amount <= 0 or amount > 10**12:
        return None

    selection = parts[0]

    if selection in ("к", "красное", "красный", "red"):
        return "color", "red", amount

    if selection in ("ч", "черное", "чёрное", "черный", "чёрный", "black"):
        return "color", "black", amount

    if selection in ("з", "зеленое", "зелёное", "green"):
        return "color", "green", amount

    match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", selection)
    if match:
        start = int(match.group(1))
        end = int(match.group(2))
        if 0 <= start <= end <= 36:
            return "range", f"{start}-{end}", amount
        return None

    if re.fullmatch(r"\d{1,2}", selection):
        number = int(selection)
        if 0 <= number <= 36:
            return "number", str(number), amount

    return None


@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text.regexp(r"(?i)^(к|ч|з|красное|черное|чёрное|red|black|green|\d{1,2}(?:-\d{1,2})?)\s+\d+(?:[.,]\d+)?$")
)
async def roulette_bet_handler(message: Message):
    if not message.from_user:
        return

    parsed = parse_roulette_bet(message.text)
    if not parsed:
        return

    user_id = message.from_user.id
    if await is_banned(user_id):
        await message.reply("⛔ Аккаунт заблокирован.")
        return

    kind, value, amount = parsed
    user = await get_user(user_id)

    if not user or float(user["balance"]) < amount:
        await message.reply("Недостаточно TOKENS для ставки.")
        return

    success = await change_balance(
        user_id,
        -amount,
        "TOKENS",
        "roulette_bet",
        f"Рулетка: {value}",
    )
    if not success:
        await message.reply("Не удалось списать ставку.")
        return

    async with await db_connect() as db:
        await db.execute(
            """
            INSERT INTO roulette_bets(
                user_id, chat_id, bet, bet_type, bet_value, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                message.chat.id,
                amount,
                kind,
                value,
                int(time.time()),
            ),
        )
        await db.commit()

    await message.reply(
        f"🎡 Ставка принята: <b>{amount:,.2f} TOKENS</b> на <b>{html.escape(value)}</b>.\n"
        "Для запуска рулетки напиши <code>старт</code>."
    )


async def get_roulette_bets(chat_id: int):
    async with await db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM roulette_bets
            WHERE chat_id=?
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        return await cur.fetchall()


async def clear_roulette_bets(chat_id: int):
    async with await db_connect() as db:
        await db.execute(
            "DELETE FROM roulette_bets WHERE chat_id=?",
            (chat_id,),
        )
        await db.commit()


async def save_roulette_history(chat_id: int, number: int, color: str):
    async with await db_connect() as db:
        await db.execute(
            """
            INSERT INTO roulette_history(chat_id, number, color, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (chat_id, number, color, int(time.time())),
        )
        await db.commit()


def roulette_bet_wins(bet, number: int, color: str):
    kind = bet["bet_type"]
    value = str(bet["bet_value"])

    if kind == "color":
        return color == value, 2.0

    if kind == "number":
        return number == int(value), 36.0

    if kind == "range":
        start, end = map(int, value.split("-"))
        if start <= number <= end:
            multiplier = 36.0 / (end - start + 1)
            return True, multiplier
        return False, 0.0

    return False, 0.0


async def spin_roulette(message: Message):
    bets = await get_roulette_bets(message.chat.id)

    if not bets:
        await message.reply("Нет ставок. Сначала сделай ставку, например: <code>к 1000</code>.")
        return

    number = random.randint(0, 36)
    color = roulette_color(number)

    await save_roulette_history(message.chat.id, number, color)

    gif_path = ASSETS_DIR / "roulette.gif"
    if gif_path.is_file():
        try:
            await message.answer_animation(
                BufferedInputFile(gif_path.read_bytes(), filename="roulette.gif")
            )
        except Exception:
            pass

    color_names = {
        "red": "🔴 Красное",
        "black": "⚫ Чёрное",
        "green": "🟢 Зелёное",
    }

    lines = [
        "🎡 <b>Рулетка остановилась!</b>\n",
        f"Результат: <b>{number}</b> — {color_names[color]}\n",
    ]

    total_paid = 0.0
    replay_bets = []

    for bet in bets:
        won, multiplier = roulette_bet_wins(bet, number, color)
        payout = float(bet["bet"]) * multiplier if won else 0.0

        if payout > 0:
            await change_balance(
                int(bet["user_id"]),
                payout,
                "TOKENS",
                "roulette_payout",
                f"Рулетка, результат {number}",
            )
            total_paid += payout

        replay_bets.append(
            {
                "user_id": int(bet["user_id"]),
                "bet": float(bet["bet"]),
                "bet_type": str(bet["bet_type"]),
                "bet_value": str(bet["bet_value"]),
            }
        )

        try:
            member = await bot.get_chat_member(
                message.chat.id,
                int(bet["user_id"]),
            )
            name = html.escape(member.user.full_name)
        except Exception:
            name = str(bet["user_id"])

        lines.append(
            f"• {name}: {float(bet['bet']):,.0f} TOKENS — "
            f"{'выигрыш ' + format_number(payout) if won else 'проигрыш'}"
        )

        await log_game(
            int(bet["user_id"]),
            message.chat.id,
            "roulette",
            float(bet["bet"]),
            payout,
            f"number={number};color={color};selection={bet['bet_value']}",
        )

    await clear_roulette_bets(message.chat.id)

    result_message = await message.answer(
        "\n".join(lines),
        reply_markup=roulette_result_keyboard(),
    )

    # Store the last completed round for repeat/double callbacks.
    roulette_last_round[result_message.message_id] = replay_bets
    roulette_last_round[message.message_id] = replay_bets


roulette_last_round = {}


@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text.casefold() == "старт",
)
async def roulette_start_handler(message: Message):
    await spin_roulette(message)


@dp.callback_query(F.data.in_({"roulette_repeat", "roulette_double"}))
async def roulette_repeat_callback(callback: CallbackQuery):
    await callback.answer()

    if not callback.message:
        return

    bets = roulette_last_round.get(callback.message.message_id)
    if not bets:
        await callback.answer("Данные прошлого раунда недоступны.", show_alert=True)
        return

    multiplier = 2 if callback.data == "roulette_double" else 1
    user_id = callback.from_user.id

    own_bets = [item for item in bets if item["user_id"] == user_id]
    if not own_bets:
        await callback.answer("В прошлом раунде у тебя не было ставок.", show_alert=True)
        return

    balance = await get_user_balance(user_id)
    total = sum(item["bet"] * multiplier for item in own_bets)

    if balance < total:
        await callback.answer("Недостаточно TOKENS.", show_alert=True)
        return

    async with await db_connect() as db:
        for item in own_bets:
            amount = item["bet"] * multiplier
            await db.execute(
                """
                INSERT INTO roulette_bets(
                    user_id, chat_id, bet, bet_type, bet_value, created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    callback.message.chat.id,
                    amount,
                    item["bet_type"],
                    item["bet_value"],
                    int(time.time()),
                ),
            )
        await db.commit()

    await change_balance(
        user_id,
        -total,
        "TOKENS",
        "roulette_bet",
        "Повторная ставка рулетки",
    )

    await callback.answer("Ставки повторены. Напиши «старт» в чате.")


# ============================================================
# VIP DAILY CASHBACK
# ============================================================

async def calculate_daily_vip_cashback():
    now = int(time.time())
    yesterday = now - 86400

    async with await db_connect() as db:
        cur = await db.execute(
            """
            SELECT user_id
            FROM users
            WHERE vip=1
            """
        )
        vip_users = await cur.fetchall()

        for item in vip_users:
            user_id = int(item["user_id"])

            cur = await db.execute(
                """
                SELECT
                    SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS losses,
                    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS wins
                FROM transactions
                WHERE user_id=?
                  AND currency='TOKENS'
                  AND operation IN ('game_bet', 'game_payout', 'roulette_bet', 'roulette_payout')
                  AND created_at>=?
                  AND created_at<?
                """,
                (user_id, yesterday, now),
            )
            totals = await cur.fetchone()

            losses = float(totals["losses"] or 0)
            wins = float(totals["wins"] or 0)
            net_loss = max(0.0, losses - wins)
            cashback = round(net_loss * VIP_CASHBACK_RATE, 2)

            if cashback <= 0:
                continue

            await db.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (cashback, user_id),
            )
            await add_transaction_db(
                db,
                user_id,
                "TOKENS",
                cashback,
                "vip_cashback",
                "Ежедневный VIP-кэшбэк 2.5%",
            )

            try:
                await bot.send_message(
                    user_id,
                    "💎 <b>VIP-кэшбэк начислен!</b>\n\n"
                    f"Твой возврат: <b>{cashback:,.2f} TOKENS</b>.",
                )
            except Exception:
                pass

        await db.commit()


async def vip_cashback_loop():
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=5,
            microsecond=0,
        )
        delay = max(10, (next_midnight - now).total_seconds())
        await asyncio.sleep(delay)

        try:
            await calculate_daily_vip_cashback()
        except Exception:
            logger.exception("VIP cashback job failed")


# ============================================================
# ADMIN COMMANDS
# ============================================================

ADMIN_HELP = (
    "🛠 <b>Админ-команды TOKENS</b>\n\n"
    "<code>@помощь</code> — список команд\n"
    "<code>@скан ID</code> — информация о пользователе\n"
    "<code>@выдать ID СУММА</code> — выдать TOKENS\n"
    "<code>@выдать_крипту ID СУММА</code> — выдать TNC\n"
    "<code>@дроп СУММА</code> — раздать TOKENS всем\n"
    "<code>@бан ID ЧАСЫ</code> — заблокировать\n"
    "<code>@стата</code> — статистика\n"
    "<code>@сет_курс СУММА</code> — установить курс TNC\n"
    "<code>@дождь СУММА</code> — раздать сумму активным пользователям"
)


def is_admin(user_id: int):
    return bool(ADMIN_ID and user_id == ADMIN_ID)


async def admin_scan(target_id: int):
    user = await get_user(target_id)
    if not user:
        return "Пользователь не найден."

    return (
        f"👤 <b>Пользователь {target_id}</b>\n\n"
        f"Username: @{html.escape(user['username'] or '-')}\n"
        f"Имя: {html.escape(user['first_name'] or '-')}\n"
        f"TOKENS: <b>{float(user['balance']):,.2f}</b>\n"
        f"TNC: <b>{float(user['balance_tnc']):,.8f}</b>\n"
        f"Рефералы: {user['referrals']}\n"
        f"VIP: {bool(user['vip'])}\n"
        f"Бан: {bool(user['is_banned'])}\n"
        f"Captcha: {bool(user['captcha_passed'])}"
    )


async def admin_stats():
    async with await db_connect() as db:
        cur = await db.execute(
            """
            SELECT
                COUNT(*) AS users,
                SUM(balance) AS tokens,
                SUM(balance_tnc) AS tnc,
                SUM(vip) AS vip,
                SUM(is_banned) AS banned
            FROM users
            """
        )
        row = await cur.fetchone()

        cur = await db.execute(
            "SELECT COUNT(*) AS count FROM game_log"
        )
        games = await cur.fetchone()

        cur = await db.execute(
            "SELECT COUNT(*) AS count FROM transactions"
        )
        transactions_count = await cur.fetchone()

    return (
        "📊 <b>Статистика TOKENS</b>\n\n"
        f"Пользователей: <b>{row['users'] or 0}</b>\n"
        f"Общий баланс TOKENS: <b>{float(row['tokens'] or 0):,.2f}</b>\n"
        f"Общий баланс TNC: <b>{float(row['tnc'] or 0):,.8f}</b>\n"
        f"VIP: <b>{row['vip'] or 0}</b>\n"
        f"Заблокировано: <b>{row['banned'] or 0}</b>\n"
        f"Игр: <b>{games['count']}</b>\n"
        f"Транзакций: <b>{transactions_count['count']}</b>"
    )


async def admin_drop(amount: float):
    async with await db_connect() as db:
        cur = await db.execute("SELECT user_id FROM users WHERE is_banned=0")
        users = await cur.fetchall()

        for row in users:
            user_id = int(row["user_id"])
            await db.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (amount, user_id),
            )
            await add_transaction_db(
                db,
                user_id,
                "TOKENS",
                amount,
                "admin_drop",
                "Общий дроп",
            )

        await db.commit()

    return len(users)


async def admin_rain(amount: float):
    return await admin_drop(amount)


@dp.message(F.text.startswith("@"))
async def admin_command_handler(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    parts = (message.text or "").strip().split()
    if not parts:
        return

    command = parts[0].lower()

    if command == "@помощь":
        await message.answer(ADMIN_HELP)
        return

    if command == "@стата":
        await message.answer(await admin_stats())
        return

    if command == "@скан":
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Формат: <code>@скан ID</code>")
            return
        await message.answer(await admin_scan(int(parts[1])))
        return

    if command == "@выдать":
        if len(parts) < 3:
            await message.answer("Формат: <code>@выдать ID СУММА</code>")
            return

        try:
            target_id = int(parts[1])
            amount = float(parts[2].replace(",", "."))
        except ValueError:
            await message.answer("Некорректные аргументы.")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.")
            return

        if not await get_user(target_id):
            await message.answer("Пользователь не найден.")
            return

        await change_balance(
            target_id,
            amount,
            "TOKENS",
            "admin_grant",
            "Начисление администратором",
        )
        await message.answer(
            f"✅ Начислено {amount:,.2f} TOKENS пользователю {target_id}."
        )
        try:
            await bot.send_message(
                target_id,
                f"🎁 Администратор начислил тебе {amount:,.2f} TOKENS.",
            )
        except Exception:
            pass
        return

    if command == "@выдать_крипту":
        if len(parts) < 3:
            await message.answer(
                "Формат: <code>@выдать_крипту ID СУММА</code>"
            )
            return

        try:
            target_id = int(parts[1])
            amount = float(parts[2].replace(",", "."))
        except ValueError:
            await message.answer("Некорректные аргументы.")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.")
            return

        if not await get_user(target_id):
            await message.answer("Пользователь не найден.")
            return

        await change_balance(
            target_id,
            amount,
            "TNC",
            "admin_crypto_grant",
            "Начисление TNC администратором",
        )
        await message.answer(
            f"✅ Начислено {amount:,.8f} TNC пользователю {target_id}."
        )
        try:
            await bot.send_message(
                target_id,
                f"💎 Администратор начислил тебе {amount:,.8f} TNC.",
            )
        except Exception:
            pass
        return

    if command == "@дроп":
        if len(parts) < 2:
            await message.answer("Формат: <code>@дроп СУММА</code>")
            return

        try:
            amount = float(parts[1].replace(",", "."))
        except ValueError:
            await message.answer("Некорректная сумма.")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.")
            return

        count = await admin_drop(amount)
        await message.answer(
            f"🎁 Дроп {amount:,.2f} TOKENS начислен {count} пользователям."
        )
        return

    if command == "@дождь":
        if len(parts) < 2:
            await message.answer("Формат: <code>@дождь СУММА</code>")
            return

        try:
            amount = float(parts[1].replace(",", "."))
        except ValueError:
            await message.answer("Некорректная сумма.")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.")
            return

        count = await admin_rain(amount)
        await message.answer(
            f"🌧 Дождь! {amount:,.2f} TOKENS получили {count} пользователей."
        )
        return

    if command == "@бан":
        if len(parts) < 3:
            await message.answer("Формат: <code>@бан ID ЧАСЫ</code>")
            return

        try:
            target_id = int(parts[1])
            hours = float(parts[2].replace(",", "."))
        except ValueError:
            await message.answer("Некорректные аргументы.")
            return

        if hours <= 0:
            await message.answer("Часы должны быть больше нуля.")
            return

        await ban_user(target_id, hours, "admin")
        await message.answer(
            f"⛔ Пользователь {target_id} заблокирован на {hours:g} ч."
        )
        try:
            await bot.send_message(
                target_id,
                f"⛔ Твой аккаунт заблокирован на {hours:g} часов.",
            )
        except Exception:
            pass
        return

    if command == "@разбан":
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Формат: <code>@разбан ID</code>")
            return
        target_id = int(parts[1])
        await unban_user(target_id)
        await message.answer(f"✅ Пользователь {target_id} разблокирован.")
        return

    if command == "@сет_курс":
        if len(parts) < 2:
            await message.answer("Формат: <code>@сет_курс СУММА</code>")
            return

        try:
            rate = float(parts[1].replace(",", "."))
        except ValueError:
            await message.answer("Некорректный курс.")
            return

        if rate <= 0:
            await message.answer("Курс должен быть больше нуля.")
            return

        await set_setting("tnc_rate", str(rate))
        await message.answer(f"✅ Новый курс: 1 TNC = {rate:,.2f} TOKENS.")
        return

    await message.answer("Неизвестная команда. Напиши @помощь.")


# ============================================================
# TELEGRAM WEB APP INIT DATA VALIDATION
# ============================================================

def validate_telegram_init_data(init_data: str, bot_token: str):
    if not init_data or not bot_token:
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
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400:
            return None

        user_data = json.loads(parsed.get("user", "{}"))
        if not isinstance(user_data, dict):
            return None

        return user_data

    except Exception:
        logger.exception("initData validation failed")
        return None


def request_init_data(request: web.Request):
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()

    return (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData")
        or ""
    )


async def api_user(request: web.Request):
    init_data = request_init_data(request)
    user_data = validate_telegram_init_data(init_data, BOT_TOKEN)

    if not user_data:
        return web.json_response(
            {"ok": False, "error": "invalid_init_data"},
            status=401,
        )

    try:
        user_id = int(user_data["id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response(
            {"ok": False, "error": "invalid_user"},
            status=400,
        )

    user = await get_user(user_id)
    if not user:
        await ensure_user(
            user_id,
            user_data.get("username", ""),
            user_data.get("first_name", ""),
        )
        user = await get_user(user_id)

    if await is_banned(user_id):
        return web.json_response(
            {"ok": False, "error": "banned"},
            status=403,
        )

    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": user_id,
                "username": user_data.get("username", ""),
                "first_name": user_data.get("first_name", ""),
                "balance": float(user["balance"]),
                "balance_tnc": float(user["balance_tnc"]),
                "vip": bool(user["vip"]),
                "referrals": int(user["referrals"]),
            },
            "tnc_rate": await current_tnc_rate(),
        }
    )


async def api_swap(request: web.Request):
    init_data = request_init_data(request)
    user_data = validate_telegram_init_data(init_data, BOT_TOKEN)

    if not user_data:
        return web.json_response(
            {"ok": False, "error": "invalid_init_data"},
            status=401,
        )

    try:
        user_id = int(user_data["id"])
        payload = await request.json()
        amount = float(payload.get("amount", 0))
        direction = str(payload.get("direction", "tokens_to_tnc"))
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_payload"},
            status=400,
        )

    if amount <= 0 or amount > 10**12:
        return web.json_response(
            {"ok": False, "error": "invalid_amount"},
            status=400,
        )

    if await is_banned(user_id):
        return web.json_response(
            {"ok": False, "error": "banned"},
            status=403,
        )

    if direction == "tokens_to_tnc":
        success, received = await execute_tokens_to_tnc(user_id, amount)
        source_currency = "TOKENS"
        target_currency = "TNC"
    elif direction == "tnc_to_tokens":
        success, received = await execute_tnc_to_tokens(user_id, amount)
        source_currency = "TNC"
        target_currency = "TOKENS"
    else:
        return web.json_response(
            {"ok": False, "error": "invalid_direction"},
            status=400,
        )

    if not success:
        return web.json_response(
            {"ok": False, "error": "insufficient_balance"},
            status=400,
        )

    return web.json_response(
        {
            "ok": True,
            "spent": amount,
            "spent_currency": source_currency,
            "received": received,
            "received_currency": target_currency,
            "balance": await get_user_balance(user_id),
            "balance_tnc": await get_user_tnc(user_id),
        }
    )


# ============================================================
# WEB APP STATIC SERVER
# ============================================================

async def serve_webapp(request: web.Request):
    index_path = BASE_DIR / "webapp" / "index.html"

    if index_path.is_file():
        return web.FileResponse(index_path)

    fallback = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TOKENS App</title>
<style>
body{margin:0;background:#0b1225;color:#fff;font:16px Arial,sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center}
main{max-width:520px;padding:36px;text-align:center}
h1{color:#e8c36e}
p{color:#b9c5dc;line-height:1.6}
</style>
</head>
<body><main>
<h1>TOKENS App</h1>
<p>Mini App пока не установлен.</p>
<p>Добавь файл <b>webapp/index.html</b> в каталог проекта.</p>
</main></body></html>"""

    return web.Response(text=fallback, content_type="text/html")


async def health_check(request: web.Request):
    return web.json_response({"ok": True, "service": "TOKENS"})


async def start_web_server():
    global http_runner

    http_app.router.add_get("/webapp/", serve_webapp)
    http_app.router.add_get("/webapp/index.html", serve_webapp)
    http_app.router.add_get("/api/user", api_user)
    http_app.router.add_post("/api/swap", api_swap)
    http_app.router.add_get("/health", health_check)

    if WEBAPP_DIR.is_dir():
        try:
            http_app.router.add_static(
                "/webapp/",
                str(WEBAPP_DIR),
                show_index=True,
            )
        except RuntimeError:
            logger.warning("Static webapp route was not added.")

    http_runner = web.AppRunner(http_app)
    await http_runner.setup()

    site = web.TCPSite(http_runner, "0.0.0.0", PORT)
    await site.start()

    logger.info("TOKENS web server started on port %s", PORT)


async def stop_web_server():
    global http_runner
    if http_runner:
        await http_runner.cleanup()
        http_runner = None


# ============================================================
# SUPPORT AND GENERAL COMMANDS
# ============================================================

@dp.message(Command("help"))
async def command_help(message: Message):
    await message.answer(
        "ℹ️ <b>Помощь TOKENS</b>\n\n"
        "Основные разделы находятся в меню под строкой ввода.\n"
        "Игровые команды работают в группах.\n\n"
        "Поддержка: "
        f"<a href='https://t.me/{SUPPORT_USERNAME}'>@{SUPPORT_USERNAME}</a>",
        reply_markup=main_reply_keyboard(),
    )


@dp.message(Command("balance"))
async def command_balance(message: Message):
    user_id = message.from_user.id
    tokens = await get_user_balance(user_id)
    tnc = await get_user_tnc(user_id)

    await message.answer(
        "💼 <b>Баланс</b>\n\n"
        f"TOKENS: <b>{format_number(tokens)}</b>\n"
        f"TNC: <b>{format_number(tnc, 8)}</b>"
    )


@dp.message(Command("id"))
async def command_id(message: Message):
    await message.answer(
        f"Твой Telegram ID: <code>{message.from_user.id}</code>"
    )


@dp.message(Command("support"))
async def command_support(message: Message):
    await message.answer(
        f"💬 Поддержка: https://t.me/{SUPPORT_USERNAME}"
    )


@dp.message(Command("shop"))
async def command_shop(message: Message):
    await message.answer(
        "🛍 <b>Магазин TOKENS</b>",
        reply_markup=shop_keyboard(),
    )


@dp.message(Command("quests"))
async def command_quests(message: Message):
    await message.answer(
        "📋 <b>Задания TOKENS</b>",
        reply_markup=quests_keyboard(),
    )


# ============================================================
# PAYMENT RECORDS / PLACEHOLDER PAYMENT FLOW
# ============================================================

async def create_payment(
    user_id: int,
    currency: str,
    amount: float,
    payload: str = "",
):
    async with await db_connect() as db:
        cur = await db.execute(
            """
            INSERT INTO payments(
                user_id, currency, amount, status, payload, created_at
            ) VALUES(?, ?, ?, 'pending', ?, ?)
            """,
            (
                user_id,
                currency,
                amount,
                payload,
                int(time.time()),
            ),
        )
        payment_id = cur.lastrowid
        await db.commit()

    return payment_id


async def update_payment_status(payment_id: int, status: str):
    allowed = {"pending", "paid", "cancelled", "failed"}
    if status not in allowed:
        return False

    async with await db_connect() as db:
        await db.execute(
            "UPDATE payments SET status=? WHERE id=?",
            (status, payment_id),
        )
        await db.commit()

    return True


# ============================================================
# USER SAFETY CHECKS
# ============================================================

@dp.message()
async def fallback_handler(message: Message):
    if not message.from_user:
        return

    if await is_banned(message.from_user.id):
        await message.answer("⛔ Доступ к TOKENS временно ограничен.")
        return

    if message.chat.type == ChatType.PRIVATE:
        if message.text:
            await message.answer(
                "Используй кнопки главного меню или отправь /start.",
                reply_markup=main_reply_keyboard(),
            )


# ============================================================
# ERROR HANDLING
# ============================================================

@dp.errors()
async def global_error_handler(event):
    exception = event.exception
    logger.exception("Unhandled update error: %s", exception)

    try:
        update = event.update
        if update and update.message:
            await update.message.answer(
                "⚠️ Произошла внутренняя ошибка. Попробуй ещё раз."
            )
    except Exception:
        pass

    return True


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

async def startup_checks():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Установи переменную окружения BOT_TOKEN."
        )

    await init_db()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    WEBAPP_DIR.mkdir(parents=True, exist_ok=True)

    me = await bot.get_me()
    logger.info("Bot started: @%s (%s)", me.username, me.id)

    if NEWS_CHANNEL:
        logger.info("NEWS_CHANNEL configured: %s", NEWS_CHANNEL)


async def main():
    cashback_task = None

    try:
        await startup_checks()
        await start_web_server()

        cashback_task = asyncio.create_task(vip_cashback_loop())

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=False,
        )

    except KeyboardInterrupt:
        logger.info("Shutdown requested.")

    finally:
        if cashback_task:
            cashback_task.cancel()
            try:
                await cashback_task
            except asyncio.CancelledError:
                pass

        await stop_web_server()

        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())