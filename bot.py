
# ============================================================
# TOKENS BOT — MONOLITHIC EDITION
# Python 3.11+
#
# Dependencies:
# pip install aiogram>=3.13 aiosqlite aiohttp Pillow
#
# Environment:
# BOT_TOKEN, ADMIN_ID, NEWS_CHANNEL, PORT,
# SUPPORT_USERNAME, WEBAPP_URL
#
# Assets:
# assets/how_to_play.jpg
# assets/bonus.jpg
# assets/crypto.jpg
# assets/roulette.gif
# assets/error.jpg (optional; generated if absent)
#
# ============================================================

# ======================== IMPORTS ============================

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
import string
import time

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

import aiosqlite
from aiohttp import web

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
    InputMediaPhoto,
    InputMediaAnimation,
    Dice,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ======================== CONFIG ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
NEWS_CHANNEL = os.getenv("NEWS_CHANNEL", "")
PORT = int(os.getenv("PORT", "10000"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

DB_PATH = os.getenv("DB_PATH", "tokens.db")
ASSETS_DIR = "assets"

START_BALANCE = 5000
REFERRAL_REWARD = 5000
NEW_REFERRAL_BALANCE = 10000

DEFAULT_TNC_RATE = 50000
CAPTCHA_ATTEMPTS = 3
CAPTCHA_BAN_HOURS = 12

PRIVATE_DELETE_SECONDS = 30
GAME_DELETE_SECONDS = 15
GROUP_DELETE_SECONDS = 60

VIP_CASHBACK_RATE = 0.025

MAX_ROULETTE_RANGES = 100
ROULETTE_MAX_AGE = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

bot = Bot(
    token=BOT_TOKEN,
    default=None,
)

dp = Dispatcher()

# ======================== GLOBAL STATE ========================

DB: Optional[aiosqlite.Connection] = None

captcha_sessions: dict[int, dict] = {}
roulette_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

navigation_history: dict[int, list[str]] = defaultdict(list)

roulette_rounds: dict[int, int] = defaultdict(int)
roulette_repeat_usage: set[tuple[int, int, str]] = set()

active_tasks: set[asyncio.Task] = set()

# ======================== DATABASE ============================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    balance INTEGER NOT NULL DEFAULT 0,
    balance_tnc REAL NOT NULL DEFAULT 0,
    referrer_id INTEGER DEFAULT NULL,
    referrals INTEGER NOT NULL DEFAULT 0,
    banned_until INTEGER NOT NULL DEFAULT 0,
    vip INTEGER NOT NULL DEFAULT 0,
    language TEXT DEFAULT 'ru',
    created_at INTEGER NOT NULL DEFAULT 0,
    last_cashback INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    bet INTEGER NOT NULL,
    multiplier REAL NOT NULL,
    profit INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bonus (
    user_id INTEGER PRIMARY KEY,
    last_claim INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS roulette_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    ranges_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    round_id INTEGER NOT NULL DEFAULT 0
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
    created_at INTEGER NOT NULL,
    round_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_game_user ON game_log(user_id);
CREATE INDEX IF NOT EXISTS idx_game_date ON game_log(created_at);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_roulette_chat ON roulette_bets(chat_id);
"""


async def init_db():
    global DB

    DB = await aiosqlite.connect(DB_PATH)
    DB.row_factory = aiosqlite.Row

    await DB.executescript(SCHEMA)

    await DB.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("tnc_rate", str(DEFAULT_TNC_RATE)),
    )

    await DB.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("maintenance", "0"),
    )

    await DB.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
        ("total_dropped", "0"),
    )

    await DB.commit()

    logger.info("Database initialized")


async def db_execute(query: str, params: tuple = ()):
    async with DB.execute(query, params) as cursor:
        return cursor


async def get_setting(key: str, default: str = "") -> str:
    async with DB.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ) as cursor:
        row = await cursor.fetchone()

    return row["value"] if row else default


async def set_setting(key: str, value: str):
    await DB.execute(
        """
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )
    await DB.commit()


async def get_user(user_id: int):
    async with DB.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,),
    ) as cursor:
        return await cursor.fetchone()


async def ensure_user(user_id: int, username="", first_name=""):
    await DB.execute(
        """
        INSERT OR IGNORE INTO users
        (user_id,username,first_name,created_at)
        VALUES(?,?,?,?)
        """,
        (user_id, username or "", first_name or "", int(time.time())),
    )

    await DB.execute(
        """
        UPDATE users
        SET username=?,first_name=?
        WHERE user_id=?
        """,
        (username or "", first_name or "", user_id),
    )

    await DB.commit()


async def update_balance(
    user_id: int,
    amount: int,
    description: str = "",
    transaction_type: str = "balance",
):
    async with DB.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return False

    new_balance = row["balance"] + amount

    if new_balance < 0:
        return False

    await DB.execute(
        "UPDATE users SET balance=? WHERE user_id=?",
        (new_balance, user_id),
    )

    await DB.execute(
        """
        INSERT INTO transactions
        (user_id,amount,transaction_type,description,created_at)
        VALUES(?,?,?,?,?)
        """,
        (
            user_id,
            amount,
            transaction_type,
            description,
            int(time.time()),
        ),
    )

    await DB.commit()
    return True


async def update_tnc(user_id: int, amount: float):
    async with DB.execute(
        "SELECT balance_tnc FROM users WHERE user_id=?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return False

    new_balance = round(row["balance_tnc"] + amount, 8)

    if new_balance < -0.00000001:
        return False

    await DB.execute(
        "UPDATE users SET balance_tnc=? WHERE user_id=?",
        (new_balance, user_id),
    )

    await DB.commit()
    return True


async def is_banned(user_id: int) -> bool:
    user = await get_user(user_id)

    if not user:
        return False

    return user["banned_until"] > int(time.time())


async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# ======================== UTILITIES ===========================

def safe_html(value: Any) -> str:
    return html.escape(str(value or ""))


def format_money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def format_tnc(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def now() -> int:
    return int(time.time())


def make_task(coro):
    task = asyncio.create_task(coro)
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)
    return task


async def delete_after(
    chat_id: int,
    message_id: int,
    seconds: int,
):
    await asyncio.sleep(seconds)

    try:
        await bot.delete_message(chat_id, message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def schedule_delete(message: Message, seconds: int):
    make_task(
        delete_after(
            message.chat.id,
            message.message_id,
            seconds,
        )
    )


async def safe_delete(message: Optional[Message]):
    if not message:
        return

    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return

        try:
            await message.delete()
        except Exception:
            pass

        await bot.send_message(
            message.chat.id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


async def safe_edit_media(
    message: Message,
    media,
    reply_markup=None,
):
    try:
        await message.edit_media(
            media=media,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        try:
            await message.delete()
        except Exception:
            pass

        await bot.send_photo(
            message.chat.id,
            media.media,
            caption=getattr(media, "caption", None),
            reply_markup=reply_markup,
        )


async def send_private(
    user_id: int,
    text: str,
    reply_markup=None,
    photo=None,
):
    try:
        if photo:
            return await bot.send_photo(
                user_id,
                photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )

        return await bot.send_message(
            user_id,
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )

    except TelegramForbiddenError:
        return None


def get_font(size: int):
    candidates = [
        "assets/font.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    return ImageFont.load_default()


def image_to_file(image: Image.Image, filename: str):
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return BufferedInputFile(output.getvalue(), filename=filename)


# ======================== IMAGE GENERATION ====================

def generate_captcha_image(code: str):
    image = Image.new("RGB", (300, 100), (24, 28, 43))
    draw = ImageDraw.Draw(image)

    for _ in range(100):
        x = random.randint(0, 299)
        y = random.randint(0, 99)
        color = (
            random.randint(50, 160),
            random.randint(50, 160),
            random.randint(50, 160),
        )
        draw.point((x, y), fill=color)

    for _ in range(12):
        draw.line(
            (
                random.randint(0, 300),
                random.randint(0, 100),
                random.randint(0, 300),
                random.randint(0, 100),
            ),
            fill=(65, 80, 110),
            width=2,
        )

    font = get_font(55)

    for index, digit in enumerate(code):
        x = 60 + index * 48
        y = random.randint(15, 28)

        draw.text(
            (x, y),
            digit,
            font=font,
            fill=(
                random.randint(180, 255),
                random.randint(180, 255),
                random.randint(180, 255),
            ),
        )

    image = image.filter(ImageFilter.GaussianBlur(0.25))

    return image_to_file(image, "captcha.png")


def generate_error_image():
    image = Image.new("RGB", (300, 180), (24, 28, 43))
    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (85, 15, 215, 145),
        outline=(235, 65, 75),
        width=8,
    )

    draw.line(
        (120, 50, 180, 110),
        fill=(255, 65, 75),
        width=13,
    )

    draw.line(
        (180, 50, 120, 110),
        fill=(255, 65, 75),
        width=13,
    )

    return image_to_file(image, "error.png")


def generate_profile_image(
    username: str,
    first_name: str,
):
    image = Image.new("RGB", (600, 400), (19, 23, 38))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (15, 15, 585, 385),
        radius=35,
        outline=(65, 100, 180),
        width=4,
    )

    avatar = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    avatar_draw = ImageDraw.Draw(avatar)

    avatar_draw.ellipse(
        (0, 0, 180, 180),
        fill=(60, 100, 180),
    )

    initials = (
        (first_name[:1] or "U").upper()
        + (username[:1] or "T").upper()
    )

    avatar_draw.text(
        (90, 90),
        initials,
        anchor="mm",
        font=get_font(60),
        fill="white",
    )

    image.paste(avatar, (210, 45), avatar)

    draw.text(
        (300, 260),
        "TOKENS",
        anchor="mm",
        font=get_font(46),
        fill=(255, 255, 255),
    )

    draw.text(
        (300, 320),
        first_name[:24],
        anchor="mm",
        font=get_font(23),
        fill=(170, 190, 220),
    )

    return image_to_file(image, "profile.png")


# ======================== KEYBOARDS ===========================

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
        input_field_placeholder="Выберите действие",
    )


def back_keyboard(target="menu"):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ Назад",
        callback_data=f"back:{target}",
    )

    return builder.as_markup()


def app_keyboard():
    builder = InlineKeyboardBuilder()

    if WEBAPP_URL:
        builder.button(
            text="🚀 Открыть App",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )

    builder.button(
        text="💬 Поддержка",
        url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}",
    )

    builder.adjust(1)
    return builder.as_markup()


def group_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎮 Игровой чат",
        url=NEWS_CHANNEL if NEWS_CHANNEL.startswith("https://") else (
            f"https://t.me/{NEWS_CHANNEL.lstrip('@')}"
        ),
    )

    builder.adjust(1)
    return builder.as_markup()


def menu_inline_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(text="🎮 Игры", callback_data="menu:games")
    builder.button(text="💎 Крипта", callback_data="menu:crypto")
    builder.button(text="🎁 Бонус", callback_data="menu:bonus")
    builder.button(text="👤 Профиль", callback_data="menu:profile")
    builder.button(text="🏆 Топ", callback_data="menu:top")
    builder.button(text="🔗 Рефералка", callback_data="menu:ref")

    builder.adjust(2, 2, 2)
    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📖 Правила",
        callback_data="games:rules",
    )

    builder.button(
        text="⬅️ Назад",
        callback_data="back:menu",
    )

    builder.adjust(1)
    return builder.as_markup()


# ======================== MESSAGE NAVIGATION ==================

async def show_menu(message: Message, edit=False):
    text = (
        "🚀 <b>TOKENS</b>\n\n"
        "Добро пожаловать в экономическую игровую систему!\n\n"
        "Выберите нужный раздел:"
    )

    if edit:
        await safe_edit_text(
            message,
            text,
            reply_markup=menu_inline_keyboard(),
        )
    else:
        await message.answer(
            text,
            reply_markup=main_reply_keyboard(),
        )


async def show_profile(message: Message, user_id: int, edit=False):
    user = await get_user(user_id)

    if not user:
        return

    username = user["username"] or "Не указан"

    caption = (
        "👤 <b>Профиль TOKENS</b>\n\n"
        f"Имя: <b>{safe_html(user['first_name'])}</b>\n"
        f"Username: @{safe_html(username)}\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"💰 TOKENS: <b>{format_money(user['balance'])}</b>\n"
        f"💎 TNC: <b>{format_tnc(user['balance_tnc'])}</b>\n"
        f"👥 Рефералы: <b>{user['referrals']}</b>\n"
        f"⭐ VIP: {'Да' if user['vip'] else 'Нет'}"
    )

    photo = generate_profile_image(
        username,
        user["first_name"],
    )

    keyboard = back_keyboard("menu")

    if edit:
        try:
            await message.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest:
            pass

    await message.answer_photo(
        photo,
        caption=caption,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def show_top(message: Message, edit=False):
    async with DB.execute(
        """
        SELECT user_id,username,first_name,balance
        FROM users
        WHERE banned_until < ?
        ORDER BY balance DESC
        LIMIT 10
        """,
        (now(),),
    ) as cursor:
        rows = await cursor.fetchall()

    medals = ["🥇", "🥈", "🥉"]

    lines = ["🏆 <b>ТОП-10 игроков TOKENS</b>\n"]

    for index, row in enumerate(rows):
        medal = medals[index] if index < 3 else f"{index + 1}."

        name = row["username"] or row["first_name"] or str(row["user_id"])

        lines.append(
            f"{medal} {safe_html(name)} — "
            f"<b>{format_money(row['balance'])}</b>"
        )

    text = "\n".join(lines)

    if edit:
        await safe_edit_text(
            message,
            text,
            reply_markup=back_keyboard("menu"),
        )
    else:
        await message.answer(
            text,
            reply_markup=back_keyboard("menu"),
        )


async def show_referral(message: Message, user_id: int, edit=False):
    user = await get_user(user_id)

    bot_info = await bot.get_me()

    link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    text = (
        "🔗 <b>Реферальная система</b>\n\n"
        f"Ваши приглашённые: <b>{user['referrals']}</b>\n\n"
        "За каждого нового приглашённого:\n"
        f"• Вам: <b>{REFERRAL_REWARD}</b> TOKENS\n"
        f"• Другу: <b>{NEW_REFERRAL_BALANCE}</b> TOKENS\n\n"
        "Приглашайте друзей по кнопке ниже."
    )

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📨 Пригласить",
        url=(
            "https://t.me/share/url?url="
            + link
        ),
    )

    builder.button(
        text="⬅️ Назад",
        callback_data="back:menu",
    )

    builder.adjust(1)

    if edit:
        await safe_edit_text(
            message,
            text,
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            text,
            reply_markup=builder.as_markup(),
        )


async def show_crypto(message: Message, edit=False):
    rate = int(await get_setting("tnc_rate", str(DEFAULT_TNC_RATE)))

    text = (
        "💎 <b>Криптовалюта $TNC</b>\n\n"
        f"Курс: <b>1 TNC = {format_money(rate)} TOKENS</b>\n\n"
        "Обмен доступен в TOKENS Mini App.\n"
        "Вы можете обменивать TOKENS на TNC "
        "и обратно."
    )

    keyboard = app_keyboard()

    if edit:
        await safe_edit_text(
            message,
            text,
            reply_markup=keyboard,
        )
    else:
        asset = os.path.join(ASSETS_DIR, "crypto.jpg")

        if os.path.exists(asset):
            await message.answer_photo(
                BufferedInputFile(
                    open(asset, "rb").read(),
                    filename="crypto.jpg",
                ),
                caption=text,
                reply_markup=keyboard,
            )
        else:
            await message.answer(
                text,
                reply_markup=keyboard,
            )


async def show_bonus(message: Message, user_id: int, edit=False):
    asset = os.path.join(ASSETS_DIR, "bonus.jpg")

    text = (
        "🎁 <b>Ежедневный бонус</b>\n\n"
        "Забирайте бесплатные TOKENS раз в 24 часа!"
    )

    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎁 Забрать бонус",
        callback_data="bonus:claim",
    )

    builder.button(
        text="⬅️ Назад",
        callback_data="back:menu",
    )

    builder.adjust(1)

    if edit:
        await safe_edit_text(
            message,
            text,
            reply_markup=builder.as_markup(),
        )
    elif os.path.exists(asset):
        with open(asset, "rb") as file:
            await message.answer_photo(
                BufferedInputFile(file.read(), filename="bonus.jpg"),
                caption=text,
                reply_markup=builder.as_markup(),
            )
    else:
        await message.answer(
            text,
            reply_markup=builder.as_markup(),
        )


# ======================== CAPTCHA =============================

async def start_captcha(message: Message, user_id: int):
    code = "".join(
        random.choices(string.digits, k=4)
    )

    captcha_sessions[user_id] = {
        "code": code,
        "attempts": 0,
        "message_id": None,
        "referrer": None,
    }

    photo = generate_captcha_image(code)

    sent = await message.answer_photo(
        photo,
        caption=(
            "🔐 <b>Проверка безопасности</b>\n\n"
            "Введите четыре цифры с картинки."
        ),
        parse_mode=ParseMode.HTML,
    )

    captcha_sessions[user_id]["message_id"] = sent.message_id


async def captcha_failed(message: Message, user_id: int):
    session = captcha_sessions.get(user_id)

    if not session:
        return

    old_message_id = session["message_id"]

    if old_message_id:
        try:
            await bot.delete_message(
                message.chat.id,
                old_message_id,
            )
        except TelegramBadRequest:
            pass

    session["attempts"] += 1

    if session["attempts"] >= CAPTCHA_ATTEMPTS:
        await DB.execute(
            """
            UPDATE users SET banned_until=?
            WHERE user_id=?
            """,
            (
                now() + CAPTCHA_BAN_HOURS * 3600,
                user_id,
            ),
        )

        await DB.commit()

        captcha_sessions.pop(user_id, None)

        error = generate_error_image()

        await message.answer_photo(
            error,
            caption=(
                "❌ <b>Доступ временно заблокирован.</b>\n\n"
                "Превышено количество попыток.\n"
                "Попробуйте через 12 часов."
            ),
        )
        return

    code = "".join(
        random.choices(string.digits, k=4)
    )

    session["code"] = code

    photo = generate_captcha_image(code)

    sent = await message.answer_photo(
        photo,
        caption=(
            "❌ Неверный код.\n\n"
            f"Осталось попыток: "
            f"{CAPTCHA_ATTEMPTS - session['attempts']}\n\n"
            "Введите код с картинки."
        ),
    )

    session["message_id"] = sent.message_id


async def captcha_success(message: Message, user_id: int):
    session = captcha_sessions.pop(user_id, None)

    if not session:
        return

    await safe_delete(message)

    if session["message_id"]:
        try:
            await bot.delete_message(
                message.chat.id,
                session["message_id"],
            )
        except TelegramBadRequest:
            pass

    referrer_id = session.get("referrer")

    if referrer_id and referrer_id != user_id:
        referrer = await get_user(referrer_id)

        if referrer:
            await update_balance(
                referrer_id,
                REFERRAL_REWARD,
                "Реферальная награда",
                "referral",
            )

            await DB.execute(
                """
                UPDATE users
                SET referrals=referrals+1
                WHERE user_id=?
                """,
                (referrer_id,),
            )

            await DB.commit()

            await update_balance(
                user_id,
                NEW_REFERRAL_BALANCE,
                "Регистрация по рефералу",
                "registration",
            )

            await send_private(
                referrer_id,
                f"🎉 Новый реферал! +{REFERRAL_REWARD} TOKENS",
            )

        else:
            await update_balance(
                user_id,
                START_BALANCE,
                "Стартовый бонус",
                "registration",
            )
    else:
        await update_balance(
            user_id,
            START_BALANCE,
            "Стартовый бонус",
            "registration",
        )

    await message.answer(
        "✅ <b>Проверка пройдена!</b>\n\n"
        "Ваш аккаунт активирован.\n"
        "Добро пожаловать в TOKENS!",
        reply_markup=main_reply_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# ======================== START HANDLER =======================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id

    await ensure_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if await is_banned(user_id):
        await message.answer(
            "⛔ Ваш аккаунт временно заблокирован."
        )
        return

    user = await get_user(user_id)

    if user["created_at"] < now() - 10:
        await show_menu(message)
        return

    args = message.text.split(maxsplit=1)

    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])

            if referrer_id != user_id:
                captcha_sessions.setdefault(
                    user_id,
                    {},
                )["referrer"] = referrer_id

        except ValueError:
            pass

    await start_captcha(message, user_id)


@dp.message(F.text.regexp(r"^\d{4}$"))
async def captcha_input(message: Message):
    user_id = message.from_user.id

    session = captcha_sessions.get(user_id)

    if not session:
        return

    if message.text == session["code"]:
        await captcha_success(message, user_id)
    else:
        await captcha_failed(message, user_id)


# ======================== MENU HANDLERS =======================

@dp.message(F.text == "👤 Профиль")
async def profile_button(message: Message):
    await show_profile(
        message,
        message.from_user.id,
    )


@dp.message(F.text == "🏆 Топ")
async def top_button(message: Message):
    await show_top(message)


@dp.message(F.text == "🔗 Рефералка")
async def referral_button(message: Message):
    await show_referral(
        message,
        message.from_user.id,
    )


@dp.message(F.text == "🎁 Бонус")
async def bonus_button(message: Message):
    await show_bonus(
        message,
        message.from_user.id,
    )


@dp.message(F.text == "💎 Крипта")
async def crypto_button(message: Message):
    await show_crypto(message)


@dp.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery):
    section = callback.data.split(":", 1)[1]

    if section == "profile":
        await show_profile(
            callback.message,
            callback.from_user.id,
            edit=True,
        )

    elif section == "top":
        await show_top(callback.message, edit=True)

    elif section == "ref":
        await show_referral(
            callback.message,
            callback.from_user.id,
            edit=True,
        )

    elif section == "bonus":
        await show_bonus(
            callback.message,
            callback.from_user.id,
            edit=True,
        )

    elif section == "crypto":
        await show_crypto(callback.message, edit=True)

    elif section == "games":
        text = (
            "🎮 <b>Игровой раздел</b>\n\n"
            "Игры доступны только в группах.\n"
            "Добавьте бота в игровой чат и используйте:\n\n"
            "<code>кости 1000</code>\n"
            "<code>дартс 500</code>\n"
            "<code>баскет 1000</code>\n\n"
            "Также доступна рулетка."
        )

        await safe_edit_text(
            callback.message,
            text,
            games_keyboard(),
        )

    await callback.answer()


@dp.callback_query(F.data.startswith("back:"))
async def back_callback(callback: CallbackQuery):
    target = callback.data.split(":", 1)[1]

    if target == "menu":
        await safe_edit_text(
            callback.message,
            "🚀 <b>TOKENS</b>\n\nВыберите раздел:",
            menu_inline_keyboard(),
        )

    elif target == "games":
        await safe_edit_text(
            callback.message,
            "🎮 <b>Игры</b>\n\nДоступны только в группах.",
            games_keyboard(),
        )

    await callback.answer()


# ======================== BONUS ===============================

BONUS_AMOUNT = 1000
BONUS_INTERVAL = 86400


@dp.callback_query(F.data == "bonus:claim")
async def claim_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with DB.execute(
        "SELECT last_claim FROM bonus WHERE user_id=?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    last_claim = row["last_claim"] if row else 0
    remaining = BONUS_INTERVAL - (now() - last_claim)

    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await callback.answer(
            f"Бонус будет доступен через {hours} ч. {minutes} мин.",
            show_alert=True,
        )
        return

    await DB.execute(
        """
        INSERT INTO bonus(user_id,last_claim)
        VALUES(?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET last_claim=excluded.last_claim
        """,
        (user_id, now()),
    )

    await DB.commit()

    await update_balance(
        user_id,
        BONUS_AMOUNT,
        "Ежедневный бонус",
        "bonus",
    )

    await safe_edit_text(
        callback.message,
        f"🎉 Вы получили <b>{BONUS_AMOUNT}</b> TOKENS!",
        back_keyboard("menu"),
    )

    await callback.answer("Бонус получен!")


# ======================== GAMES ===============================

GAME_MULTIPLIERS = {
    "dice": 2.0,
    "darts": 2.0,
    "bowling": 2.0,
    "basket": {
        1: 0,
        2: 1,
        3: 1.5,
        4: 1.8,
        5: 2,
    },
    "football": {
        1: 0,
        2: 1,
        3: 1.5,
        4: 1.8,
        5: 2,
    },
}

GAME_EMOJIS = {
    "dice": "🎲",
    "darts": "🎯",
    "bowling": "🎳",
    "basket": "🏀",
    "football": "⚽",
}

GAME_NAMES = {
    "dice": "Кости",
    "darts": "Дартс",
    "bowling": "Боулинг",
    "basket": "Баскетбол",
    "football": "Футбол",
}


def parse_game_command(text: str):
    parts = text.lower().strip().split()

    if len(parts) != 2:
        return None

    aliases = {
        "кости": "dice",
        "кость": "dice",
        "дартс": "darts",
        "боулинг": "bowling",
        "баскет": "basket",
        "баскетбол": "basket",
        "футбол": "football",
    }

    game = aliases.get(parts[0])

    if not game:
        return None

    if not parts[1].isdigit():
        return None

    bet = int(parts[1])

    if bet <= 0 or bet > 1_000_000_000:
        return None

    return game, bet


async def play_game(message: Message, game: str, bet: int):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if message.chat.type == ChatType.PRIVATE:
        error = generate_error_image()

        await message.answer_photo(
            error,
            caption="❌ Заходи в игровой чат!",
            reply_markup=group_keyboard(),
        )
        return

    if await is_banned(user_id):
        return

    user = await get_user(user_id)

    if not user or user["balance"] < bet:
        response = await message.answer(
            "❌ Недостаточно TOKENS."
        )
        await schedule_delete(response, GAME_DELETE_SECONDS)
        return

    if not await update_balance(
        user_id,
        -bet,
        f"Ставка: {game}",
        "game_bet",
    ):
        return

    dice = await bot.send_dice(
        chat_id,
        emoji=GAME_EMOJIS[game],
    )

    await asyncio.sleep(3.5)

    value = dice.dice.value

    if game in ("dice", "darts", "bowling"):
        multiplier = 2.0 if value >= 4 else 0.0
    else:
        multiplier = GAME_MULTIPLIERS[game].get(value, 0)

    payout = int(bet * multiplier)
    profit = payout - bet

    if payout > 0:
        await update_balance(
            user_id,
            payout,
            f"Выигрыш: {game}",
            "game_win",
        )

    await DB.execute(
        """
        INSERT INTO game_log
        (user_id,chat_id,game,bet,multiplier,profit,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            user_id,
            chat_id,
            game,
            bet,
            multiplier,
            profit,
            now(),
        ),
    )

    await DB.commit()

    result = (
        "🎉 <b>ПОБЕДА!</b>"
        if payout > bet
        else "😔 <b>Не повезло!</b>"
        if payout == 0
        else "🤝 <b>Возврат ставки!</b>"
    )

    response = await message.answer(
        f"{GAME_NAMES[game]}: {result}\n\n"
        f"Ставка: <b>{format_money(bet)}</b>\n"
        f"Множитель: <b>x{multiplier}</b>\n"
        f"Выплата: <b>{format_money(payout)}</b>\n"
        f"Изменение баланса: "
        f"<b>{profit:+,}</b>".replace(",", " "),
        parse_mode=ParseMode.HTML,
    )

    await schedule_delete(dice, GAME_DELETE_SECONDS)
    await schedule_delete(response, GAME_DELETE_SECONDS)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def game_handler(message: Message):
    if not message.text:
        return

    parsed = parse_game_command(message.text)

    if parsed:
        game, bet = parsed
        await play_game(message, game, bet)
        return

    if message.text.strip().lower() == "старт":
        await start_roulette(message)
        return


@dp.message(F.chat.type == ChatType.PRIVATE)
async def private_fallback(message: Message):
    if message.text and message.text.startswith("/"):
        return

    if message.from_user.id in captcha_sessions:
        return

    if await is_banned(message.from_user.id):
        return

    response = await message.answer(
        "Используйте кнопки меню TOKENS."
    )

    await schedule_delete(response, PRIVATE_DELETE_SECONDS)


# ======================== ROULETTE ============================

RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16,
    18, 19, 21, 23, 25, 27, 30,
    32, 34, 36,
}

BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS


def roulette_color(number: int) -> str:
    if number == 0:
        return "🟢 Зелёный"

    if number in RED_NUMBERS:
        return "🔴 Красный"

    return "⚫ Чёрный"


def parse_roulette_bet(text: str):
    """
    Поддерживаемые форматы:

    к 1000
    10-20 500
    500 10-30 30-34 23-24 24-35

    Результат:
    (amount, ranges)

    ranges — список пар [start, end].
    """

    parts = text.lower().strip().split()

    if len(parts) < 2:
        return None

    if parts[0] == "к":
        if len(parts) != 2 or not parts[1].isdigit():
            return None

        amount = int(parts[1])
        ranges = [[0, 36]]

    elif "-" in parts[0]:
        if len(parts) != 2 or not parts[1].isdigit():
            return None

        amount = int(parts[1])
        ranges = []

        for item in parts[0].split(","):
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", item)

            if not match:
                return None

            ranges.append([
                int(match.group(1)),
                int(match.group(2)),
            ])

    else:
        if not parts[0].isdigit():
            return None

        amount = int(parts[0])
        ranges = []

        for item in parts[1:]:
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", item)

            if not match:
                return None

            ranges.append([
                int(match.group(1)),
                int(match.group(2)),
            ])

    if amount <= 0 or amount > 1_000_000_000:
        return None

    if not ranges or len(ranges) > MAX_ROULETTE_RANGES:
        return None

    for start, end in ranges:
        if start < 0 or end > 36 or start > end:
            return None

    return amount, ranges


async def place_roulette_bet(message: Message):
    parsed = parse_roulette_bet(message.text or "")

    if not parsed:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    amount, ranges = parsed

    if await is_banned(user_id):
        return

    user = await get_user(user_id)

    if not user or user["balance"] < amount:
        response = await message.reply(
            "❌ Недостаточно TOKENS для ставки."
        )
        await schedule_delete(response, GAME_DELETE_SECONDS)
        return

    lock = roulette_locks[chat_id]

    if lock.locked():
        response = await message.reply(
            "⏳ Уже крутится!"
        )
        await schedule_delete(response, GAME_DELETE_SECONDS)
        return

    round_id = roulette_rounds[chat_id]

    if not await update_balance(
        user_id,
        -amount,
        "Ставка рулетка",
        "roulette_bet",
    ):
        return

    await DB.execute(
        """
        INSERT INTO roulette_bets
        (user_id,chat_id,amount,ranges_json,created_at,round_id)
        VALUES(?,?,?,?,?,?)
        """,
        (
            user_id,
            chat_id,
            amount,
            json.dumps(ranges),
            now(),
            round_id,
        ),
    )

    await DB.commit()

    response = await message.reply(
        f"🎰 Ставка принята: <b>{format_money(amount)}</b>\n"
        f"Диапазоны: <code>{safe_html(json.dumps(ranges))}</code>",
        parse_mode=ParseMode.HTML,
    )

    await schedule_delete(response, GAME_DELETE_SECONDS)


async def roulette_result_keyboard(user_id: int, round_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔄 Повторить",
        callback_data=f"roulette:repeat:{round_id}",
    )

    builder.button(
        text="⏫ Удвоить",
        callback_data=f"roulette:double:{round_id}",
    )

    return builder.as_markup()


async def start_roulette(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    lock = roulette_locks[chat_id]

    if lock.locked():
        response = await message.answer("⏳ Уже крутится!")
        await schedule_delete(response, GAME_DELETE_SECONDS)
        return

    async with lock:
        round_id = roulette_rounds[chat_id]

        async with DB.execute(
            """
            SELECT * FROM roulette_bets
            WHERE chat_id=? AND round_id=?
            ORDER BY created_at ASC
            """,
            (chat_id, round_id),
        ) as cursor:
            bets = await cursor.fetchall()

        if not bets:
            response = await message.answer("Нет ставок.")
            await schedule_delete(response, GAME_DELETE_SECONDS)
            return

        roulette_rounds[chat_id] += 1

        await DB.execute(
            """
            DELETE FROM roulette_bets
            WHERE chat_id=? AND round_id=?
            """,
            (chat_id, round_id),
        )

        await DB.commit()

        gif_path = os.path.join(
            ASSETS_DIR,
            "roulette.gif",
        )

        animation_message = None

        if os.path.exists(gif_path):
            with open(gif_path, "rb") as file:
                animation_message = await message.answer_animation(
                    BufferedInputFile(
                        file.read(),
                        filename="roulette.gif",
                    )
                )

        await asyncio.sleep(2)

        number = random.randint(0, 36)
        color = roulette_color(number)

        winners = []
        losers = []

        for bet in bets:
            try:
                ranges = json.loads(bet["ranges_json"])
            except (TypeError, json.JSONDecodeError):
                ranges = []

            won = any(
                start <= number <= end
                for start, end in ranges
            )

            name = str(bet["user_id"])

            if won:
                payout = bet["amount"] * 2

                await update_balance(
                    bet["user_id"],
                    payout,
                    "Выигрыш рулетки",
                    "roulette_win",
                )

                winners.append(
                    f"• <code>{name}</code> "
                    f"+{format_money(payout)}"
                )
            else:
                losers.append(
                    f"• <code>{name}</code> "
                    f"-{format_money(bet['amount'])}"
                )

        await DB.execute(
            """
            INSERT INTO roulette_history
            (chat_id,number,color,created_at,round_id)
            VALUES(?,?,?,?,?)
            """,
            (
                chat_id,
                number,
                color,
                now(),
                round_id,
            ),
        )

        await DB.commit()

        result = (
            f"🎰 <b>РУЛЕТКА</b>\n\n"
            f"Выпало: <b>{number}</b>\n"
            f"Цвет: {color}\n\n"
            f"🏆 <b>Победители:</b>\n"
            + ("\n".join(winners) if winners else "Нет")
            + "\n\n"
            + "💸 <b>Проигравшие:</b>\n"
            + ("\n".join(losers) if losers else "Нет")
        )

        result_message = await message.answer(
            result,
            parse_mode=ParseMode.HTML,
        )

        if animation_message:
            await schedule_delete(
                animation_message,
                GROUP_DELETE_SECONDS,
            )

        await schedule_delete(
            result_message,
            GROUP_DELETE_SECONDS,
        )


@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text.regexp(r"^(?:к\s+\d+|\d+\s+\d{1,2}-\d{1,2}(?:\s+\d{1,2}-\d{1,2})*)$"),
)
async def roulette_bet_handler(message: Message):
    await place_roulette_bet(message)


# ======================== ROULETTE CALLBACKS ==================

async def get_previous_bet(user_id: int, chat_id: int, round_id: int):
    async with DB.execute(
        """
        SELECT * FROM roulette_bets
        WHERE user_id=? AND chat_id=? AND round_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, chat_id, round_id),
    ) as cursor:
        return await cursor.fetchone()


@dp.callback_query(F.data.startswith("roulette:"))
async def roulette_callback(callback: CallbackQuery):
    parts = callback.data.split(":")

    if len(parts) != 3:
        await callback.answer()
        return

    action = parts[1]

    try:
        round_id = int(parts[2])
    except ValueError:
        await callback.answer("Ошибка раунда.", show_alert=True)
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    key = (user_id, chat_id, str(round_id))

    if key in roulette_repeat_usage:
        await callback.answer(
            "Повторная ставка уже использована.",
            show_alert=True,
        )
        return

    bet = await get_previous_bet(
        user_id,
        chat_id,
        round_id,
    )

    if not bet:
        await callback.answer(
            "Исходная ставка не найдена.",
            show_alert=True,
        )
        return

    if now() - bet["created_at"] > ROULETTE_MAX_AGE:
        await callback.answer(
            "Время для повтора истекло.",
            show_alert=True,
        )
        return

    amount = bet["amount"]

    if action == "double":
        amount *= 2
    elif action != "repeat":
        await callback.answer()
        return

    user = await get_user(user_id)

    if not user or user["balance"] < amount:
        await callback.answer(
            "Недостаточно TOKENS.",
            show_alert=True,
        )
        return

    try:
        ranges = json.loads(bet["ranges_json"])
    except json.JSONDecodeError:
        await callback.answer("Ошибка ставки.", show_alert=True)
        return

    async with roulette_locks[chat_id]:
        if not await update_balance(
            user_id,
            -amount,
            "Повтор ставки рулетки",
            "roulette_bet",
        ):
            await callback.answer("Недостаточно TOKENS.", show_alert=True)
            return

        await DB.execute(
            """
            INSERT INTO roulette_bets
            (user_id,chat_id,amount,ranges_json,created_at,round_id)
            VALUES(?,?,?,?,?,?)
            """,
            (
                user_id,
                chat_id,
                amount,
                json.dumps(ranges),
                now(),
                roulette_rounds[chat_id],
            ),
        )

        await DB.commit()

        roulette_repeat_usage.add(key)

    await callback.answer(
        f"Ставка {format_money(amount)} принята!"
    )


# ======================== CRYPTO / WEB APP ====================

def validate_webapp_init_data(init_data: str, bot_token: str):
    """
    Проверка подписи Telegram Mini App.

    Возвращает распарсенные данные или None.
    """

    from urllib.parse import parse_qsl

    if not init_data or len(init_data) > 10000:
        return None

    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True,
        )

        data = dict(pairs)

        received_hash = data.pop("hash", None)

        if not received_hash:
            return None

        auth_date = int(data.get("auth_date", "0"))

        if auth_date <= 0:
            return None

        if abs(now() - auth_date) > 86400:
            return None

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(data.items())
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

        user_data = json.loads(data.get("user", "{}"))

        if not isinstance(user_data, dict):
            return None

        if not user_data.get("id"):
            return None

        return user_data

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return None


async def authenticate_webapp(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        return None

    init_data = body.get("initData", "")

    return validate_webapp_init_data(
        init_data,
        BOT_TOKEN,
    )


async def api_user(request: web.Request):
    user_data = await authenticate_webapp(request)

    if not user_data:
        return web.json_response(
            {"error": "invalid_init_data"},
            status=401,
        )

    user_id = int(user_data["id"])

    user = await get_user(user_id)

    if not user:
        return web.json_response(
            {"error": "user_not_found"},
            status=404,
        )

    if await is_banned(user_id):
        return web.json_response(
            {"error": "banned"},
            status=403,
        )

    rate = int(
        await get_setting(
            "tnc_rate",
            str(DEFAULT_TNC_RATE),
        )
    )

    return web.json_response(
        {
            "success": True,
            "user": {
                "id": user_id,
                "username": user["username"],
                "balance": user["balance"],
                "balance_tnc": user["balance_tnc"],
                "vip": bool(user["vip"]),
                "referrals": user["referrals"],
            },
            "rate": rate,
        }
    )


async def api_swap(request: web.Request):
    user_data = await authenticate_webapp(request)

    if not user_data:
        return web.json_response(
            {"error": "invalid_init_data"},
            status=401,
        )

    user_id = int(user_data["id"])

    if await is_banned(user_id):
        return web.json_response(
            {"error": "banned"},
            status=403,
        )

    try:
        body = await request.json()
        amount = float(body.get("amount"))
        direction = body.get("direction", "to_tnc")

        if not amount or amount <= 0:
            raise ValueError

        if amount > 1_000_000_000_000:
            raise ValueError

    except (ValueError, TypeError):
        return web.json_response(
            {"error": "invalid_amount"},
            status=400,
        )

    rate = int(
        await get_setting(
            "tnc_rate",
            str(DEFAULT_TNC_RATE),
        )
    )

    if rate <= 0:
        return web.json_response(
            {"error": "invalid_rate"},
            status=500,
        )

    async with DB.execute(
        "SELECT balance,balance_tnc FROM users WHERE user_id=?",
        (user_id,),
    ) as cursor:
        user = await cursor.fetchone()

    if not user:
        return web.json_response(
            {"error": "user_not_found"},
            status=404,
        )

    # Обмен выполняется атомарно в рамках транзакции.
    try:
        await DB.execute("BEGIN IMMEDIATE")

        if direction == "to_tnc":
            tokens = int(amount)

            if tokens <= 0 or tokens > user["balance"]:
                raise ValueError("insufficient_balance")

            tnc = tokens / rate

            await DB.execute(
                """
                UPDATE users
                SET balance=balance-?,
                    balance_tnc=balance_tnc+?
                WHERE user_id=? AND balance>=?
                """,
                (tokens, tnc, user_id, tokens),
            )

            description = "TOKENS -> TNC"
            source_amount = -tokens

        elif direction == "to_tokens":
            tnc = round(amount, 8)

            if tnc <= 0 or tnc > user["balance_tnc"]:
                raise ValueError("insufficient_balance")

            tokens = int(tnc * rate)

            if tokens <= 0:
                raise ValueError("amount_too_small")

            await DB.execute(
                """
                UPDATE users
                SET balance=balance+?,
                    balance_tnc=balance_tnc-?
                WHERE user_id=? AND balance_tnc>=?
                """,
                (tokens, tnc, user_id, tnc),
            )

            description = "TNC -> TOKENS"
            source_amount = tokens

        else:
            raise ValueError("invalid_direction")

        await DB.execute(
            """
            INSERT INTO transactions
            (user_id,amount,transaction_type,description,created_at)
            VALUES(?,?,?,?,?)
            """,
            (
                user_id,
                source_amount,
                "swap",
                description,
                now(),
            ),
        )

        await DB.commit()

        return web.json_response(
            {
                "success": True,
                "direction": direction,
                "tokens": tokens,
                "tnc": round(tnc, 8),
                "rate": rate,
            }
        )

    except ValueError as exc:
        await DB.rollback()

        return web.json_response(
            {"error": str(exc)},
            status=400,
        )

    except Exception:
        await DB.rollback()
        logger.exception("Swap error")

        return web.json_response(
            {"error": "internal_error"},
            status=500,
        )


# ======================== HTTP SERVER =========================

async def health(request: web.Request):
    return web.json_response(
        {
            "status": "ok",
            "service": "TOKENS",
            "timestamp": now(),
        }
    )


async def index(request: web.Request):
    return web.json_response(
        {
            "name": "TOKENS API",
            "version": "1.0.0",
            "endpoints": [
                "/health",
                "/api/user",
                "/api/swap",
            ],
        }
    )


async def create_web_app():
    app = web.Application(
        client_max_size=1024 * 1024,
    )

    # Принудительная отдача index.html
    async def serve_index(request):
        with open("webapp/index.html", "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")

    app.router.add_get("/webapp/index.html", serve_index)
    
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/api/user", api_user)
    app.router.add_post("/api/swap", api_swap)

    # Раздача файлов Mini App
    app.router.add_static("/webapp/", "webapp", show_index=True) 
    return app


# ======================== ADMIN SECURITY ======================

def admin_command(text: str):
    if not text:
        return None

    if not text.startswith("@"):
        return None

    parts = text.strip().split()

    return parts[0].lower(), parts[1:]


async def admin_check(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Недостаточно прав.")
        return False

    return True


# ======================== ADMIN HELP ==========================

ADMIN_HELP = """
🛠 <b>TOKENS ADMIN PANEL</b>

<code>@помощь</code> — помощь
<code>@скан ID</code> — информация
<code>@выдать ID СУММА</code> — выдать TOKENS
<code>@дроп СУММА</code> — раздать всем
<code>@бан ID ЧАСЫ</code> — блокировка
<code>@стата</code> — статистика
<code>@рассылка ТЕКСТ</code> — рассылка
<code>@сет_курс ЧИСЛО</code> — курс TNC
<code>@дождь СУММА</code> — дождь
"""


@dp.message(F.text.startswith("@"))
async def admin_router(message: Message):
    if not await admin_check(message):
        return

    parsed = admin_command(message.text)

    if not parsed:
        return

    command, args = parsed

    # ------------------ HELP ------------------

    if command == "@помощь":
        await message.answer(
            ADMIN_HELP,
            parse_mode=ParseMode.HTML,
        )
        return

    # ------------------ SCAN ------------------

    if command == "@скан":
        if len(args) != 1 or not args[0].isdigit():
            await message.answer("Формат: @скан ID")
            return

        user = await get_user(int(args[0]))

        if not user:
            await message.answer("Пользователь не найден.")
            return

        text = (
            "🔎 <b>Информация о пользователе</b>\n\n"
            f"ID: <code>{user['user_id']}</code>\n"
            f"Username: @{safe_html(user['username'])}\n"
            f"Имя: {safe_html(user['first_name'])}\n"
            f"TOKENS: <b>{format_money(user['balance'])}</b>\n"
            f"TNC: <b>{format_tnc(user['balance_tnc'])}</b>\n"
            f"VIP: {user['vip']}\n"
            f"Рефералы: {user['referrals']}\n"
            f"Реферер: {user['referrer_id']}\n"
            f"Бан до: {user['banned_until']}\n"
            f"Язык: {safe_html(user['language'])}\n"
            f"Регистрация: {user['created_at']}"
        )

        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
        )
        return

    # ------------------ GIVE ------------------

    if command == "@выдать":
        if (
            len(args) != 2
            or not args[0].isdigit()
            or not args[1].isdigit()
        ):
            await message.answer(
                "Формат: @выдать ID СУММА"
            )
            return

        target = int(args[0])
        amount = int(args[1])

        if amount <= 0 or amount > 1_000_000_000:
            await message.answer("Некорректная сумма.")
            return

        if not await get_user(target):
            await message.answer("Пользователь не найден.")
            return

        await update_balance(
            target,
            amount,
            "Выдача администратором",
            "admin_give",
        )

        await message.answer(
            f"✅ Выдано {format_money(amount)} TOKENS."
        )

        await send_private(
            target,
            f"🎉 Администратор начислил вам {format_money(amount)} TOKENS.",
        )
        return

    # ------------------ DROP ------------------

    if command == "@дроп":
        if len(args) != 1 or not args[0].isdigit():
            await message.answer("Формат: @дроп СУММА")
            return

        amount = int(args[0])

        if amount <= 0 or amount > 1_000_000:
            await message.answer("Некорректная сумма.")
            return

        async with DB.execute(
            "SELECT user_id FROM users WHERE banned_until<?",
            (now(),),
        ) as cursor:
            users = await cursor.fetchall()

        await message.answer(
            f"Начинаю начисление {format_money(amount)} TOKENS "
            f"для {len(users)} пользователей."
        )

        async with DB.execute("BEGIN IMMEDIATE"):
            await DB.execute(
                """
                UPDATE users
                SET balance=balance+?
                WHERE banned_until<?
                """,
                (amount, now()),
            )

            await DB.execute(
                """
                INSERT INTO settings(key,value)
                VALUES('total_dropped',?)
                ON CONFLICT(key)
                DO UPDATE SET value=CAST(value AS INTEGER)+?
                """,
                (str(amount * len(users)), amount * len(users)),
            )

            await DB.commit()

        await message.answer("✅ Массовое начисление завершено.")
        return

    # ------------------ BAN ------------------

    if command == "@бан":
        if (
            len(args) != 2
            or not args[0].isdigit()
            or not args[1].isdigit()
        ):
            await message.answer(
                "Формат: @бан ID ЧАСЫ"
            )
            return

        target = int(args[0])
        hours = int(args[1])

        if hours < 1 or hours > 8760:
            await message.answer("Допустимо от 1 до 8760 часов.")
            return

        if target == ADMIN_ID:
            await message.answer("Нельзя заблокировать администратора.")
            return

        await DB.execute(
            """
            UPDATE users SET banned_until=?
            WHERE user_id=?
            """,
            (now() + hours * 3600, target),
        )

        await DB.commit()

        await message.answer(
            f"🔨 Пользователь {target} заблокирован на {hours} ч."
        )

        await send_private(
            target,
            f"⛔ Вы заблокированы на {hours} часов.",
        )
        return

    # ------------------ STATS ------------------

    if command == "@стата":
        async with DB.execute(
            """
            SELECT
                COUNT(*) AS users,
                SUM(balance) AS tokens,
                SUM(balance_tnc) AS tnc,
                SUM(vip) AS vip
            FROM users
            """
        ) as cursor:
            stats = await cursor.fetchone()

        async with DB.execute(
            "SELECT COUNT(*) AS total FROM game_log"
        ) as cursor:
            games = await cursor.fetchone()

        async with DB.execute(
            "SELECT COUNT(*) AS total FROM transactions"
        ) as cursor:
            transactions = await cursor.fetchone()

        text = (
            "📊 <b>Статистика TOKENS</b>\n\n"
            f"Пользователей: <b>{stats['users'] or 0}</b>\n"
            f"Общий баланс: <b>{format_money(stats['tokens'] or 0)}</b>\n"
            f"Общий TNC: <b>{format_tnc(stats['tnc'] or 0)}</b>\n"
            f"VIP: <b>{stats['vip'] or 0}</b>\n"
            f"Игр: <b>{games['total']}</b>\n"
            f"Транзакций: <b>{transactions['total']}</b>"
        )

        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
        )
        return

    # ------------------ BROADCAST ------------------

    if command == "@рассылка":
        text = message.text.partition(" ")[2].strip()

        if not text:
            await message.answer(
                "Формат: @рассылка ТЕКСТ"
            )
            return

        async with DB.execute(
            "SELECT user_id FROM users WHERE banned_until<?",
            (now(),),
        ) as cursor:
            users = await cursor.fetchall()

        await message.answer(
            f"📨 Рассылка запущена. Получателей: {len(users)}"
        )

        success = 0
        failed = 0

        for row in users:
            try:
                await bot.send_message(
                    row["user_id"],
                    text,
                    parse_mode=ParseMode.HTML,
                )
                success += 1

            except (
                TelegramForbiddenError,
                TelegramBadRequest,
            ):
                failed += 1

            except TelegramNetworkError:
                await asyncio.sleep(2)
                failed += 1

            await asyncio.sleep(0.05)

        await message.answer(
            f"Рассылка завершена.\n"
            f"Доставлено: {success}\n"
            f"Ошибок: {failed}"
        )
        return

    # ------------------ RATE ------------------

    if command == "@сет_курс":
        if len(args) != 1:
            await message.answer(
                "Формат: @сет_курс ЧИСЛО"
            )
            return

        try:
            rate = int(args[0])
        except ValueError:
            await message.answer("Некорректный курс.")
            return

        if rate <= 0 or rate > 1_000_000_000:
            await message.answer("Курс вне допустимого диапазона.")
            return

        await set_setting("tnc_rate", str(rate))

        await message.answer(
            f"✅ Новый курс: 1 TNC = {format_money(rate)} TOKENS"
        )
        return

    # ------------------ RAIN ------------------

    if command == "@дождь":
        if len(args) != 1 or not args[0].isdigit():
            await message.answer(
                "Формат: @дождь СУММА"
            )
            return

        amount = int(args[0])

        if amount <= 0 or amount > 1_000_000_000:
            await message.answer("Некорректная сумма.")
            return

        chat_id = message.chat.id

        async with DB.execute(
            """
            SELECT DISTINCT user_id
            FROM game_log
            WHERE chat_id=? AND created_at>?
            """,
            (chat_id, now() - 86400),
        ) as cursor:
            participants = await cursor.fetchall()

        if not participants:
            await message.answer(
                "За последние 24 часа игроков не было."
            )
            return

        eligible = []

        for row in participants:
            user = await get_user(row["user_id"])

            if user and user["banned_until"] < now():
                eligible.append(row["user_id"])

        if not eligible:
            await message.answer("Нет доступных участников.")
            return

        share = amount // len(eligible)

        if share <= 0:
            await message.answer(
                "Сумма слишком мала для количества участников."
            )
            return

        for target in eligible:
            await update_balance(
                target,
                share,
                "Дождь",
                "rain",
            )

        await message.answer(
            f"🌧 <b>ДОЖДЬ TOKENS!</b>\n\n"
            f"Участников: {len(eligible)}\n"
            f"Каждый получил: {format_money(share)} TOKENS",
            parse_mode=ParseMode.HTML,
        )
        return


# ======================== VIP CASHBACK =======================

async def vip_cashback_worker():
    """
    Ежедневный VIP-кешбэк:
    2.5% от чистых проигрышей за предыдущие сутки.

    Начисление выполняется не чаще одного раза в сутки.
    """

    while True:
        try:
            current = now()
            yesterday = current - 86400

            async with DB.execute(
                """
                SELECT user_id
                FROM users
                WHERE vip=1 AND last_cashback<?
                """,
                (current - 86400,),
            ) as cursor:
                users = await cursor.fetchall()

            for row in users:
                user_id = row["user_id"]

                async with DB.execute(
                    """
                    SELECT SUM(
                        CASE WHEN profit<0 THEN -profit ELSE 0 END
                    ) AS losses
                    FROM game_log
                    WHERE user_id=? AND created_at BETWEEN ? AND ?
                    """,
                    (user_id, yesterday, current),
                ) as cursor:
                    result = await cursor.fetchone()

                losses = result["losses"] or 0

                cashback = int(
                    losses * VIP_CASHBACK_RATE
                )

                if cashback > 0:
                    await update_balance(
                        user_id,
                        cashback,
                        "VIP ежедневный кешбэк",
                        "vip_cashback",
                    )

                    await send_private(
                        user_id,
                        f"⭐ VIP-кешбэк: +{format_money(cashback)} TOKENS",
                    )

                await DB.execute(
                    """
                    UPDATE users
                    SET last_cashback=?
                    WHERE user_id=?
                    """,
                    (current, user_id),
                )

                await DB.commit()

        except Exception:
            logger.exception("VIP cashback worker error")

        await asyncio.sleep(3600)


# ======================== GROUP AUTO CLEANUP =================

@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
)
async def group_cleanup_handler(message: Message):
    if message.from_user and message.from_user.is_bot:
        return

    await schedule_delete(
        message,
        GROUP_DELETE_SECONDS,
    )


# ======================== ERROR HANDLER ======================

@dp.errors()
async def global_error_handler(event):
    exception = event.exception

    logger.exception(
        "Unhandled update exception",
        exc_info=exception,
    )

    return True


# ======================== STARTUP / SHUTDOWN ==================

async def on_startup():
    logger.info("TOKENS bot starting")

    await init_db()

    await bot.delete_webhook(
        drop_pending_updates=False,
    )

    logger.info("Database ready")


async def on_shutdown():
    logger.info("TOKENS bot shutting down")

    for task in list(active_tasks):
        task.cancel()

    if DB:
        await DB.close()


# ======================== MAIN ================================

async def main():
    await init_db()

    app = await create_web_app()

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info(
        "HTTP server started on port %s",
        PORT,
    )

    await bot.delete_webhook(
        drop_pending_updates=False,
    )

    cashback_task = asyncio.create_task(
        vip_cashback_worker()
    )

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:
        cashback_task.cancel()

        try:
            await cashback_task
        except asyncio.CancelledError:
            pass

        await runner.cleanup()

        for task in list(active_tasks):
            task.cancel()

        if DB:
            await DB.close()

        await bot.session.close()

        logger.info("TOKENS stopped")


if __name__ == "__main__":
    asyncio.run(main())
