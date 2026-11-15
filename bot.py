import os
import re
import io
import time
import json
import math
import html
import random
import asyncio
import logging
import sqlite3
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    LabeledPrice,
    PreCheckoutQuery,
    FSInputFile,
)
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramAPIError,
)

# ============================================================
# TOKENS BOT — CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DATABASE = os.getenv("DATABASE", "tokens.sqlite3")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

# Telegram username канала, который проверяется перед выдачей бонуса.
# Это именно TokenCasinoTournaments, а не tokens_news.
BONUS_CHANNEL = "@TokenCasinoTournaments"
BONUS_CHANNEL_URL = "https://t.me/TokenCasinoTournaments"

START_BALANCE = 0
BONUS_COOLDOWN = 12 * 60 * 60
NORMAL_BONUS = 2500
GAME_DELETE_SECONDS = 15
PRIVATE_DELETE_SECONDS = 30
GROUP_DELETE_SECONDS = 60

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("TOKENS")

bot: Optional[Bot] = None
db_conn: Optional[aiosqlite.Connection] = None
db_lock = asyncio.Lock()
dp = Dispatcher(storage=MemoryStorage())

bot_username = "TOKENS"
bot_name = "TOKENS"

# Состояния хранятся в памяти. После перезапуска пользователь
# сможет начать капчу или ввод суммы заново.
class CaptchaState(StatesGroup):
    waiting = State()


class CustomStarsState(StatesGroup):
    waiting = State()


class BroadcastState(StatesGroup):
    waiting = State()


# ============================================================
# TEXTS — RU / EN
# ============================================================

TEXTS = {
    "ru": {
        "menu_how": "🎮 Как играть?",
        "menu_bonus": "🎁 Бонус",
        "menu_donate": "💎 Донат",
        "menu_profile": "👤 Профиль",
        "menu_top": "🏆 Топ",
        "menu_ref": "🔗 Рефералка",
        "captcha": "Введите цифры с картинки, чтобы продолжить.",
        "captcha_wrong": "Неверный код. Попробуйте ещё раз.",
        "captcha_ok": "Проверка пройдена! Добро пожаловать в TOKENS.",
        "how": "🎮 **Как играть в TOKENS**\n\nВыберите игру ниже. Для игры укажите ставку, например:\n`кости 1000`\n\nСтавка списывается с баланса перед началом игры.",
        "help": "ℹ️ **Помощь TOKENS**\n\nВыберите нужный раздел. Если возникла проблема с балансом или платежом, обратитесь к администрации.",
        "chats": "💬 Наши чаты и новости доступны по кнопкам ниже.",
        "language": "🌐 Выберите язык интерфейса:",
        "bonus_sub": "Чтобы получить бонус, подпишитесь на канал и нажмите «Проверить подписку».",
        "bonus_check_error": "Не удалось проверить подписку. Попробуйте ещё раз позже.",
        "bonus_not_sub": "Подписка пока не обнаружена. Подпишитесь на канал и повторите проверку.",
        "bonus_wait": "Бонус уже получен. Следующий будет доступен через {time}.",
        "bonus_received": "🎁 Вы получили **{amount:,} TOKENS**!",
        "profile_error": "Не удалось создать изображение профиля. Попробуйте позже.",
        "donate": "💎 **Покупка TOKENS**\n\nВыберите пакет Telegram Stars или укажите свою сумму.",
        "custom_stars": "Введите количество Stars от 1 до 10000.",
        "invalid_stars": "Введите целое число от 1 до 10000.",
        "payment_sent": "Счёт отправлен. Токены будут начислены только после подтверждения оплаты Telegram.",
        "top": "🏆 **Рейтинг игроков**\nВыберите категорию:",
        "ref": "🔗 **Реферальная программа**\n\nПриглашайте друзей по вашей ссылке и получайте 5000 TOKENS за каждого нового игрока.",
        "game_choose": "Выберите игру:",
        "game_instruction": "🎮 **{game}**\n\nУкажите ставку сообщением:\n`{command} 1000`\n\nПри выигрыше выплата поступает на баланс.",
        "game_bet": "Использование: `{command} сумма`",
        "game_amount": "Ставка должна быть положительным целым числом.",
        "game_funds": "Недостаточно TOKENS для этой ставки.",
        "game_result": "🎮 {game}\nСтавка: {bet:,}\nРезультат: {result}\n{outcome}\nБаланс: {balance:,} TOKENS",
        "top_empty": "Пока нет игроков в этой категории.",
        "settings": "⚙️ Настройки профиля",
        "language_changed": "Язык изменён.",
        "not_found": "Пользователь не найден.",
        "admin_only": "Эта команда доступна только администраторам.",
        "transfer_disabled": "Переводы для одного из пользователей отключены.",
        "roulette_started": "🎡 Приём ставок открыт! Ставки отправляйте сообщениями.\nПримеры: `к 1000`, `ч 1000`, `10-20 500`, `500 10-20 0 21`.\nДля завершения раунда администратор использует `@стоп`.",
        "roulette_closed": "Сейчас приём ставок закрыт. Напишите `старт`, чтобы открыть новый раунд.",
        "roulette_no_bets": "Ставок пока нет.",
        "roulette_result": "🎡 **Рулетка завершена!**\nВыпало: **{number} ({color})**\n\n{winners}",
        "roulette_lose": "Победителей нет.",
        "roulette_repeat": "🔄 Повторить",
        "roulette_double": "⏫ Удвоить",
        "updates": "🆕 **ОБНОВЛЕНИЯ TOKENS**\n\nСледите за новостями проекта в официальном канале.",
        "at_home": "На месте!",
    },
    "en": {
        "menu_how": "🎮 How to play?",
        "menu_bonus": "🎁 Bonus",
        "menu_donate": "💎 Donate",
        "menu_profile": "👤 Profile",
        "menu_top": "🏆 Top",
        "menu_ref": "🔗 Referrals",
        "captcha": "Enter the digits from the image to continue.",
        "captcha_wrong": "Incorrect code. Try again.",
        "captcha_ok": "Verification complete! Welcome to TOKENS.",
        "how": "🎮 **How to play TOKENS**\n\nChoose a game below. To play, send a bet, for example:\n`dice 1000`\n\nThe bet is deducted before the game starts.",
        "help": "ℹ️ **TOKENS Help**\n\nChoose a section below. Contact the administration if you have a balance or payment issue.",
        "chats": "💬 Our chats and news are available using the buttons below.",
        "language": "🌐 Choose your interface language:",
        "bonus_sub": "Subscribe to the channel and press “Check subscription” to receive your bonus.",
        "bonus_check_error": "Could not verify your subscription. Please try again later.",
        "bonus_not_sub": "Subscription not found. Subscribe to the channel and try again.",
        "bonus_wait": "You already claimed your bonus. Next bonus in {time}.",
        "bonus_received": "🎁 You received **{amount:,} TOKENS**!",
        "profile_error": "Could not create your profile image. Please try again.",
        "donate": "💎 **Buy TOKENS**\n\nChoose a Telegram Stars package or enter a custom amount.",
        "custom_stars": "Enter a number of Stars from 1 to 10000.",
        "invalid_stars": "Enter an integer from 1 to 10000.",
        "payment_sent": "Invoice sent. Tokens are credited only after Telegram confirms payment.",
        "top": "🏆 **Player rankings**\nChoose a category:",
        "ref": "🔗 **Referral program**\n\nInvite friends using your link and receive 5000 TOKENS for every new player.",
        "game_choose": "Choose a game:",
        "game_instruction": "🎮 **{game}**\n\nSend your bet:\n`{command} 1000`\n\nWinnings are credited to your balance.",
        "game_bet": "Usage: `{command} amount`",
        "game_amount": "Bet must be a positive integer.",
        "game_funds": "Insufficient TOKENS for this bet.",
        "game_result": "🎮 {game}\nBet: {bet:,}\nResult: {result}\n{outcome}\nBalance: {balance:,} TOKENS",
        "top_empty": "There are no players in this category yet.",
        "settings": "⚙️ Profile settings",
        "language_changed": "Language changed.",
        "not_found": "User not found.",
        "admin_only": "This command is for administrators only.",
        "transfer_disabled": "Transfers are disabled for one of the users.",
        "roulette_started": "🎡 Betting is open! Send bets as messages.\nExamples: `к 1000`, `ч 1000`, `10-20 500`, `500 10-20 0 21`.\nAn administrator can close the round using `@стоп`.",
        "roulette_closed": "Betting is currently closed. Send `старт` to open a new round.",
        "roulette_no_bets": "There are no bets yet.",
        "roulette_result": "🎡 **Roulette finished!**\nNumber: **{number} ({color})**\n\n{winners}",
        "roulette_lose": "No winners.",
        "roulette_repeat": "🔄 Repeat",
        "roulette_double": "⏫ Double",
        "updates": "🆕 **TOKENS UPDATES**\n\nFollow the official project channel for news.",
        "at_home": "I'm here!",
    },
}

def tr(key: str, lang: str = "ru", **kwargs) -> str:
    lang = lang if lang in TEXTS else "ru"
    value = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    try:
        return value.format(**kwargs)
    except Exception:
        return value


# ============================================================
# DATABASE
# ============================================================

async def init_db():
    global db_conn

    db_conn = await aiosqlite.connect(DATABASE)
    db_conn.row_factory = aiosqlite.Row

    await db_conn.execute("PRAGMA journal_mode=WAL")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await db_conn.execute("PRAGMA busy_timeout=5000")

    await db_conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        full_name TEXT DEFAULT '',
        language TEXT DEFAULT 'ru',
        balance INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        donated_stars INTEGER DEFAULT 0,
        donated_tokens INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referral_earned INTEGER DEFAULT 0,
        referred_by INTEGER,
        referral_paid INTEGER DEFAULT 0,
        vip_until INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT 0,
        last_seen INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS game_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game TEXT NOT NULL,
        bet INTEGER NOT NULL,
        win INTEGER DEFAULT 0,
        result TEXT DEFAULT '',
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        reason TEXT DEFAULT '',
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS bonus (
        user_id INTEGER PRIMARY KEY,
        last_claim INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS payments (
        payload TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        stars INTEGER NOT NULL,
        tokens INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS roulette_bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT DEFAULT '',
        stake INTEGER NOT NULL,
        selection TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER PRIMARY KEY,
        transfers_blocked INTEGER DEFAULT 0
    );
    """)

    await db_conn.commit()
    logger.info("Database initialized")


async def db_execute(query, params=()):
    async with db_lock:
        await db_conn.execute(query, params)
        await db_conn.commit()


async def db_fetchone(query, params=()):
    async with db_lock:
        cursor = await db_conn.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def db_fetchall(query, params=()):
    async with db_lock:
        cursor = await db_conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def ensure_user(user):
    now = int(time.time())
    full_name = (user.full_name or user.first_name or "Игрок")[:128]
    username = user.username or ""

    async with db_lock:
        await db_conn.execute("""
        INSERT INTO users(user_id, username, full_name, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            last_seen=excluded.last_seen
        """, (user.id, username, full_name, now, now))
        await db_conn.commit()


async def get_user(user_id):
    return await db_fetchone(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,),
    )


async def get_language(user_id):
    row = await get_user(user_id)
    return row["language"] if row else "ru"


async def is_banned(user_id):
    row = await get_user(user_id)
    return bool(row and row["banned"])


async def change_balance(user_id: int, amount: int, reason: str = "") -> bool:
    """
    Атомарно меняет баланс.
    Отрицательное значение amount означает списание.
    Нельзя уйти в отрицательный баланс.
    """
    async with db_lock:
        await db_conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db_conn.execute(
                "SELECT balance FROM users WHERE user_id=?",
                (user_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()

            if row is None:
                await db_conn.rollback()
                return False

            new_balance = int(row["balance"]) + int(amount)
            if new_balance < 0:
                await db_conn.rollback()
                return False

            await db_conn.execute(
                "UPDATE users SET balance=? WHERE user_id=?",
                (new_balance, user_id),
            )
            await db_conn.execute("""
                INSERT INTO transactions(user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, amount, reason, int(time.time())))

            await db_conn.commit()
            return True
        except Exception:
            await db_conn.rollback()
            logger.exception("change_balance failed")
            return False


async def transfer_tokens(sender_id, receiver_id, amount):
    if sender_id == receiver_id or amount <= 0:
        return False

    async with db_lock:
        await db_conn.execute("BEGIN IMMEDIATE")
        try:
            sender = await db_conn.execute_fetchone(
                "SELECT balance FROM users WHERE user_id=?",
                (sender_id,),
            )
            receiver = await db_conn.execute_fetchone(
                "SELECT balance FROM users WHERE user_id=?",
                (receiver_id,),
            )
            if not sender or not receiver:
                await db_conn.rollback()
                return False

            sender_settings = await db_conn.execute_fetchone(
                "SELECT transfers_blocked FROM settings WHERE user_id=?",
                (sender_id,),
            )
            receiver_settings = await db_conn.execute_fetchone(
                "SELECT transfers_blocked FROM settings WHERE user_id=?",
                (receiver_id,),
            )

            if (
                (sender_settings and sender_settings["transfers_blocked"])
                or (receiver_settings and receiver_settings["transfers_blocked"])
            ):
                await db_conn.rollback()
                return "blocked"

            if int(sender["balance"]) < amount:
                await db_conn.rollback()
                return False

            await db_conn.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=?",
                (amount, sender_id),
            )
            await db_conn.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (amount, receiver_id),
            )

            now = int(time.time())
            await db_conn.execute(
                "INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                (sender_id, -amount, f"Перевод пользователю {receiver_id}", now),
            )
            await db_conn.execute(
                "INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                (receiver_id, amount, f"Перевод от пользователя {sender_id}", now),
            )
            await db_conn.commit()
            return True
        except Exception:
            await db_conn.rollback()
            logger.exception("transfer failed")
            return False


async def add_game_log(user_id, game, bet, win, result):
    await db_execute("""
        INSERT INTO game_log(user_id, game, bet, win, result, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, game, bet, win, result, int(time.time())))


async def get_game_stats(user_id):
    row = await db_fetchone("""
        SELECT
            COUNT(*) AS games,
            COALESCE(SUM(bet),0) AS bets,
            COALESCE(SUM(win),0) AS wins,
            COALESCE(SUM(CASE WHEN win=0 THEN bet ELSE 0 END),0) AS losses
        FROM game_log WHERE user_id=?
    """, (user_id,))
    return row


async def get_bonus_last(user_id):
    row = await db_fetchone(
        "SELECT last_claim FROM bonus WHERE user_id=?",
        (user_id,),
    )
    return int(row["last_claim"]) if row else 0


async def set_bonus_last(user_id, timestamp):
    await db_execute("""
        INSERT INTO bonus(user_id,last_claim) VALUES(?,?)
        ON CONFLICT(user_id) DO UPDATE SET last_claim=excluded.last_claim
    """, (user_id, timestamp))


# ============================================================
# GENERAL HELPERS
# ============================================================

async def auto_delete(message: Message, seconds=PRIVATE_DELETE_SECONDS):
    async def _delete():
        await asyncio.sleep(seconds)
        try:
            await message.delete()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        except Exception:
            logger.debug("Could not auto-delete message", exc_info=True)

    asyncio.create_task(_delete())


async def answer_temporary(message: Message, text: str, seconds=PRIVATE_DELETE_SECONDS, **kwargs):
    sent = await message.answer(text, **kwargs)
    await auto_delete(sent, seconds)
    return sent


def money(value):
    return f"{int(value):,}".replace(",", " ")


def get_font(size=22, bold=False):
    candidates = []
    if bold:
        candidates += [
            ASSETS_DIR / "Montserrat-Bold.ttf",
            ASSETS_DIR / "arialbd.ttf",
        ]
    else:
        candidates += [
            ASSETS_DIR / "Montserrat-Regular.ttf",
            ASSETS_DIR / "arial.ttf",
        ]

    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                pass

    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def image_bytes(image: Image.Image, fmt="JPEG"):
    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=92)
    output.seek(0)
    return output.getvalue()


def load_background(filename, size):
    path = ASSETS_DIR / filename
    if path.exists():
        try:
            img = Image.open(path).convert("RGB")
            return img.resize(size, Image.Resampling.LANCZOS)
        except Exception:
            logger.exception("Background load error: %s", filename)

    return Image.new("RGB", size, (12, 14, 25))


def draw_centered(draw, xy, text, font, fill):
    x, y = xy
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text((x - width / 2, y), text, font=font, fill=fill)


# ============================================================
# CAPTCHA IMAGE
# ============================================================

def create_captcha():
    width, height = 300, 100
    code = "".join(random.choices("0123456789", k=4))

    img = Image.new("RGB", (width, height), (20, 25, 45))
    draw = ImageDraw.Draw(img)

    for _ in range(900):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = random.choice([
            (60, 75, 110),
            (90, 65, 100),
            (40, 110, 130),
            (120, 120, 145),
        ])
        draw.point((x, y), fill=color)

    for _ in range(13):
        draw.line(
            (
                random.randint(0, width),
                random.randint(0, height),
                random.randint(0, width),
                random.randint(0, height),
            ),
            fill=random.choice([
                (80, 110, 180),
                (150, 70, 130),
                (50, 150, 160),
            ]),
            width=random.randint(1, 3),
        )

    font = get_font(55, True)
    for index, digit in enumerate(code):
        x = 28 + index * 65 + random.randint(-4, 4)
        y = random.randint(12, 28)
        draw.text(
            (x, y),
            digit,
            font=font,
            fill=random.choice([
                (255, 255, 255),
                (255, 220, 100),
                (120, 230, 255),
            ]),
            stroke_width=2,
            stroke_fill=(10, 10, 25),
        )

    img = img.filter(ImageFilter.GaussianBlur(0.25))
    return code, image_bytes(img)


# ============================================================
# PROFILE / REFERRAL / GENERIC IMAGES
# ============================================================

async def download_avatar(user_id):
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos.photos:
            return None

        file_id = photos.photos[0][-1].file_id
        file = await bot.get_file(file_id)
        buffer = io.BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        buffer.seek(0)
        return Image.open(buffer).convert("RGBA")
    except Exception:
        return None


async def make_profile_image(user_id):
    user = await get_user(user_id)
    if not user:
        raise ValueError("User not found")

    img = load_background("profile_bg.jpg", (900, 560)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 110))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    title_font = get_font(34, True)
    name_font = get_font(28, True)
    text_font = get_font(25, False)

    draw.text((50, 35), bot_name, font=title_font, fill=(255, 220, 120))
    draw.text((50, 100), "ПРОФИЛЬ ИГРОКА", font=name_font, fill="white")

    avatar = await download_avatar(user_id)
    if avatar:
        avatar = avatar.resize((145, 145), Image.Resampling.LANCZOS)
        mask = Image.new("L", (145, 145), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 145, 145), fill=255)
        img.alpha_composite(
            Image.new("RGBA", (145, 145), (0, 0, 0, 0)),
            (0, 0),
        )
        img.paste(avatar, (700, 35), mask)
    else:
        draw.ellipse((700, 35, 845, 180), fill=(65, 75, 100), outline="white", width=4)
        draw_centered(draw, (772, 85), "TOK", get_font(34, True), "white")

    stats = await get_game_stats(user_id)
    display_name = (user["username"] or user["full_name"] or "Игрок").lstrip("@")

    lines = [
        f"Имя: {display_name}",
        f"Баланс: {money(user['balance'])} TOKENS",
        f"Ставки: {money(stats['bets'])}",
        f"Выигрыши: {money(stats['wins'])}",
        f"Проигрыши: {money(stats['losses'])}",
        f"Игр: {stats['games']}",
    ]

    y = 205
    for line in lines:
        draw.text((55, y), line, font=text_font, fill=(245, 245, 250))
        y += 48

    return image_bytes(img)


def create_text_image(title, subtitle="", filename=None):
    img = load_background(filename, (900, 480)) if filename else Image.new(
        "RGB", (900, 480), (15, 20, 38)
    )
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 100))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    draw_centered(draw, (450, 145), title, get_font(44, True), (255, 220, 120))
    if subtitle:
        draw_centered(draw, (450, 240), subtitle, get_font(25), "white")

    return image_bytes(img)


async def make_referral_image(user_id):
    user = await get_user(user_id)
    img = load_background("ref.jpg", (900, 480)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw_centered(draw, (450, 70), "РЕФЕРАЛЬНАЯ ПРОГРАММА", get_font(38, True), (255, 220, 120))
    draw_centered(draw, (450, 170), f"Приглашено: {user['referrals']}", get_font(30, True), "white")
    draw_centered(draw, (450, 235), f"Заработано: {money(user['referral_earned'])} TOKENS", get_font(27), "white")
    return image_bytes(img)


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard(lang="ru"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr("menu_how", lang)), KeyboardButton(text=tr("menu_bonus", lang))],
            [KeyboardButton(text=tr("menu_donate", lang)), KeyboardButton(text=tr("menu_profile", lang))],
            [KeyboardButton(text=tr("menu_top", lang)), KeyboardButton(text=tr("menu_ref", lang))],
        ],
        resize_keyboard=True,
    )


def hidden_url_button(text, url):
    return InlineKeyboardButton(text=text, url=url)


def help_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❔ Помощь", callback_data="help")],
        [InlineKeyboardButton(text="💬 Чаты", callback_data="chats")],
        [InlineKeyboardButton(text="🌐 Язык", callback_data="language")],
        [
            hidden_url_button("📢 Канал турниров", BONUS_CHANNEL_URL),
        ],
    ])


def game_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"),
            InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts"),
        ],
        [
            InlineKeyboardButton(text="🏀 Баскет", callback_data="game_basket"),
            InlineKeyboardButton(text="⚽ Футбол", callback_data="game_football"),
        ],
        [
            InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling"),
            InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette"),
        ],
        [
            InlineKeyboardButton(text="❔ Помощь", callback_data="help"),
            InlineKeyboardButton(text="💬 Чаты", callback_data="chats"),
        ],
        [
            InlineKeyboardButton(text="🌐 Язык", callback_data="language"),
        ],
    ])


def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            InlineKeyboardButton(text="⭐ VIP", callback_data="vip"),
        ],
    ])


def settings_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang_ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")],
    ])


def top_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 По донату", callback_data="top_donate"),
        ],
        [
            InlineKeyboardButton(text="👥 По рефералам", callback_data="top_ref"),
        ],
        [
            InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"),
        ],
    ])


def bonus_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [hidden_url_button("📢 Подписаться на канал", BONUS_CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="bonus_check")],
    ])


def donate_keyboard():
    amounts = [10, 50, 100, 200, 300, 400, 500]
    rows = []
    for i in range(0, len(amounts), 3):
        rows.append([
            InlineKeyboardButton(
                text=f"{amount}⭐",
                callback_data=f"buy_{amount}",
            )
            for amount in amounts[i:i + 3]
        ])
    rows.append([
        InlineKeyboardButton(text="✍️ Своя сумма", callback_data="custom_stars"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def roulette_result_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Повторить", callback_data="roulette_repeat"),
            InlineKeyboardButton(text="⏫ Удвоить", callback_data="roulette_double"),
        ],
    ])


# ============================================================
# START / CAPTCHA / REFERRALS
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.from_user is None:
        return

    await ensure_user(message.from_user)

    user = await get_user(message.from_user.id)
    if user and user["banned"]:
        await message.answer("⛔ Ваш аккаунт заблокирован.")
        return

    # Реферальный параметр ref_ID.
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1][4:])
            if referrer_id != message.from_user.id:
                await process_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass

    if user and user["verified"]:
        lang = await get_language(message.from_user.id)
        await message.answer(
            tr("captcha_ok", lang),
            reply_markup=main_keyboard(lang),
        )
        return

    code, picture = create_captcha()
    await state.update_data(captcha_code=code)
    await state.set_state(CaptchaState.waiting)

    photo = await message.answer_photo(
        BufferedInputFile(picture, filename="captcha.jpg"),
        caption="🔐 Введите четыре цифры с картинки.",
    )
    await state.update_data(captcha_message_id=photo.message_id)


async def process_referral(new_user_id, referrer_id):
    referrer = await get_user(referrer_id)
    if not referrer:
        return

    async with db_lock:
        await db_conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db_conn.execute(
                "SELECT referred_by, referral_paid FROM users WHERE user_id=?",
                (new_user_id,),
            )
            new_user = await cursor.fetchone()
            await cursor.close()

            if not new_user or new_user["referred_by"] or new_user["referral_paid"]:
                await db_conn.rollback()
                return

            await db_conn.execute("""
                UPDATE users SET referred_by=?, referral_paid=1
                WHERE user_id=?
            """, (referrer_id, new_user_id))

            await db_conn.execute("""
                UPDATE users
                SET balance=balance+5000,
                    referrals=referrals+1,
                    referral_earned=referral_earned+5000
                WHERE user_id=?
            """, (referrer_id,))

            await db_conn.execute("""
                INSERT INTO transactions(user_id,amount,reason,created_at)
                VALUES(?,?,?,?)
            """, (referrer_id, 5000, "Реферальная награда", int(time.time())))

            await db_conn.commit()
        except Exception:
            await db_conn.rollback()
            logger.exception("Referral processing failed")


@dp.message(CaptchaState.waiting)
async def captcha_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    expected = str(data.get("captcha_code", ""))

    if (message.text or "").strip() != expected:
        lang = await get_language(message.from_user.id)
        await answer_temporary(message, tr("captcha_wrong", lang), 5)
        return

    await db_execute(
        "UPDATE users SET verified=1 WHERE user_id=?",
        (message.from_user.id,),
    )

    captcha_message_id = data.get("captcha_message_id")
    if captcha_message_id:
        try:
            await bot.delete_message(message.chat.id, captcha_message_id)
        except TelegramAPIError:
            pass

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await state.clear()
    lang = await get_language(message.from_user.id)
    await message.answer(
        tr("captcha_ok", lang),
        reply_markup=main_keyboard(lang),
    )


# ============================================================
# HOW TO PLAY / HELP / CHAT LINKS
# ============================================================

GAME_INFO = {
    "dice": ("Кости", "кости", "🎲", "Значение кубика больше 3 — выигрыш x2."),
    "darts": ("Дартс", "дартс", "🎯", "Попадание в центр (6) — выигрыш x2."),
    "basket": ("Баскетбол", "баскет", "🏀", "Заброшенный мяч (значение 4 или 5) — выигрыш x2."),
    "football": ("Футбол", "футбол", "⚽", "Гол (значение 3 или 4) — выигрыш x2."),
    "bowling": ("Боулинг", "боулинг", "🎳", "Страйк (значение 6) — выигрыш x2."),
    "roulette": ("Рулетка", "рулетка", "🎡", "Ставки на цвет, число или диапазон. В группах используйте `старт`."),
}


@dp.message(F.text.in_({"🎮 Как играть?", "🎮 How to play?"}))
async def how_to_play(message: Message):
    lang = await get_language(message.from_user.id)
    path = ASSETS_DIR / "how_to_play.jpg"

    caption = tr("how", lang)
    if path.exists():
        sent = await message.answer_photo(
            FSInputFile(path),
            caption=caption,
            reply_markup=game_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        sent = await message.answer(
            caption,
            reply_markup=game_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    if message.chat.type == ChatType.PRIVATE:
        # Основное меню не удаляется, а раздел "Как играть" временный.
        await auto_delete(sent, PRIVATE_DELETE_SECONDS)


@dp.callback_query(F.data.startswith("game_"))
async def game_instruction_callback(callback: CallbackQuery):
    key = callback.data.replace("game_", "")
    lang = await get_language(callback.from_user.id)

    if key not in GAME_INFO:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    name, command, emoji, instruction = GAME_INFO[key]
    text = tr(
        "game_instruction",
        lang,
        game=f"{emoji} {name}",
        command=command,
    )
    text += f"\n\n{instruction}"

    await callback.message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


@dp.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    lang = await get_language(callback.from_user.id)
    await callback.message.answer(
        tr("help", lang),
        reply_markup=help_inline_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


@dp.callback_query(F.data == "chats")
async def chats_callback(callback: CallbackQuery):
    lang = await get_language(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [hidden_url_button("📢 Канал турниров", BONUS_CHANNEL_URL)],
    ])
    await callback.message.answer(
        tr("chats", lang),
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data == "language")
async def language_callback(callback: CallbackQuery):
    lang = await get_language(callback.from_user.id)
    await callback.message.answer(
        tr("language", lang),
        reply_markup=settings_keyboard(),
    )
    await callback.answer()


# ============================================================
# BONUS — SUBSCRIPTION CHECK ONLY HERE
# ============================================================

async def check_bonus_subscription(user_id):
    try:
        member = await bot.get_chat_member(BONUS_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator", "restricted")
    except TelegramBadRequest as exc:
        logger.warning("Cannot verify channel membership: %s", exc)
        return None
    except TelegramAPIError:
        logger.exception("Channel membership check failed")
        return None


@dp.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def bonus_menu(message: Message):
    lang = await get_language(message.from_user.id)
    path = ASSETS_DIR / "bonus.jpg"

    if path.exists():
        sent = await message.answer_photo(
            FSInputFile(path),
            caption=tr("bonus_sub", lang),
            reply_markup=bonus_keyboard(),
        )
    else:
        sent = await message.answer(
            tr("bonus_sub", lang),
            reply_markup=bonus_keyboard(),
        )

    if message.chat.type == ChatType.PRIVATE:
        await auto_delete(sent, PRIVATE_DELETE_SECONDS)


@dp.callback_query(F.data == "bonus_check")
async def bonus_check_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await get_language(user_id)

    subscribed = await check_bonus_subscription(user_id)

    if subscribed is None:
        await callback.answer(tr("bonus_check_error", lang), show_alert=True)
        return

    if not subscribed:
        await callback.answer(tr("bonus_not_sub", lang), show_alert=True)
        return

    last = await get_bonus_last(user_id)
    now = int(time.time())
    remaining = BONUS_COOLDOWN - (now - last)

    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await callback.answer(
            tr("bonus_wait", lang, time=f"{hours} ч. {minutes} мин."),
            show_alert=True,
        )
        return

    user = await get_user(user_id)
    if user and user["vip_until"] > now:
        amount = random.choice([5000, 7500, 10000])
    else:
        amount = NORMAL_BONUS

    if not await change_balance(user_id, amount, "Ежедневный бонус"):
        await callback.answer("Ошибка начисления. Попробуйте позже.", show_alert=True)
        return

    await set_bonus_last(user_id, now)
    await callback.message.answer(
        tr("bonus_received", lang, amount=amount),
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer("Бонус начислен!")


# ============================================================
# PROFILE / SETTINGS / LANGUAGE
# ============================================================

@dp.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def profile_handler(message: Message):
    try:
        picture = await make_profile_image(message.from_user.id)
        await message.answer_photo(
            BufferedInputFile(picture, filename="profile.jpg"),
            reply_markup=profile_keyboard(),
        )
    except Exception:
        logger.exception("Profile rendering failed")
        lang = await get_language(message.from_user.id)
        await message.answer(tr("profile_error", lang))


@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    try:
        picture = await make_profile_image(callback.from_user.id)
        await callback.message.answer_photo(
            BufferedInputFile(picture, filename="profile.jpg"),
            reply_markup=profile_keyboard(),
        )
    except Exception:
        logger.exception("Profile callback failed")
        await callback.message.answer("Не удалось создать профиль.")
    await callback.answer()


@dp.callback_query(F.data == "settings")
async def settings_callback(callback: CallbackQuery):
    lang = await get_language(callback.from_user.id)
    await callback.message.answer(
        tr("settings", lang),
        reply_markup=settings_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("setlang_"))
async def set_language_callback(callback: CallbackQuery):
    lang = callback.data.split("_", 1)[1]
    if lang not in ("ru", "en"):
        await callback.answer()
        return

    await db_execute(
        "UPDATE users SET language=? WHERE user_id=?",
        (lang, callback.from_user.id),
    )
    await callback.message.answer(
        tr("language_changed", lang),
        reply_markup=main_keyboard(lang),
    )
    await callback.answer()


# ============================================================
# DONATION / TELEGRAM STARS
# ============================================================

def tokens_for_stars(stars):
    """
    Фиксированные пакеты соответствуют ТЗ.
    Для пользовательской суммы от 500 Stars действует правило:
    10000 TOKENS за каждые 500 Stars пропорционально.
    Для 1–499 Stars применяется пропорция от пакета 10 Stars.
    """
    fixed = {
        10: 7500,
        50: 7500,
        100: 8000,
        200: 8500,
        300: 8500,
        400: 9000,
        500: 10000,
    }
    if stars in fixed:
        return fixed[stars]
    if stars >= 500:
        return (10000 * stars) // 500
    return max(1, (7500 * stars) // 10)


@dp.message(F.text.in_({"💎 Донат", "💎 Donate"}))
async def donate_menu(message: Message):
    lang = await get_language(message.from_user.id)
    path = ASSETS_DIR / "donate.jpg"

    if path.exists():
        sent = await message.answer_photo(
            FSInputFile(path),
            caption=tr("donate", lang),
            reply_markup=donate_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        sent = await message.answer(
            tr("donate", lang),
            reply_markup=donate_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    if message.chat.type == ChatType.PRIVATE:
        await auto_delete(sent, PRIVATE_DELETE_SECONDS)


@dp.callback_query(F.data.startswith("buy_"))
async def buy_stars_callback(callback: CallbackQuery):
    try:
        stars = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("Неверная сумма", show_alert=True)
        return

    await send_stars_invoice(callback.from_user.id, stars)
    await callback.answer()


@dp.callback_query(F.data == "custom_stars")
async def custom_stars_callback(callback: CallbackQuery, state: FSMContext):
    lang = await get_language(callback.from_user.id)
    await state.set_state(CustomStarsState.waiting)
    await callback.message.answer(tr("custom_stars", lang))
    await callback.answer()


@dp.message(CustomStarsState.waiting)
async def custom_stars_input(message: Message, state: FSMContext):
    lang = await get_language(message.from_user.id)

    if not (message.text or "").strip().isdigit():
        await message.answer(tr("invalid_stars", lang))
        return

    stars = int(message.text.strip())
    if not 1 <= stars <= 10000:
        await message.answer(tr("invalid_stars", lang))
        return

    await state.clear()
    await send_stars_invoice(message.from_user.id, stars)


async def send_stars_invoice(user_id, stars):
    tokens = tokens_for_stars(stars)
    payload = f"tokens:{user_id}:{stars}:{int(time.time())}"

    await db_execute("""
        INSERT INTO payments(payload,user_id,stars,tokens,status,created_at)
        VALUES(?,?,?,?,?,?)
    """, (payload, user_id, stars, tokens, "pending", int(time.time())))

    await bot.send_invoice(
        chat_id=user_id,
        title="TOKENS",
        description=f"Покупка {tokens:,} TOKENS",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{tokens:,} TOKENS", amount=stars)],
    )


@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    payment = await db_fetchone(
        "SELECT * FROM payments WHERE payload=? AND status='pending'",
        (query.invoice_payload,),
    )

    if (
        not payment
        or payment["user_id"] != query.from_user.id
        or payment["stars"] != query.total_amount
        or query.currency != "XTR"
    ):
        await query.answer(
            ok=False,
            error_message="Платёж не прошёл проверку. Создайте новый счёт.",
        )
        return

    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload

    async with db_lock:
        await db_conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db_conn.execute(
                "SELECT * FROM payments WHERE payload=? AND status='pending'",
                (payload,),
            )
            payment = await cursor.fetchone()
            await cursor.close()

            if (
                not payment
                or payment["user_id"] != message.from_user.id
                or payment["stars"] != payment_info.total_amount
                or payment_info.currency != "XTR"
            ):
                await db_conn.rollback()
                await message.answer("Платёж не прошёл проверку. Обратитесь в поддержку.")
                return

            tokens = int(payment["tokens"])
            await db_conn.execute(
                "UPDATE users SET balance=balance+?, donated_stars=donated_stars+?, donated_tokens=donated_tokens+? WHERE user_id=?",
                (tokens, payment["stars"], tokens, message.from_user.id),
            )
            await db_conn.execute(
                "UPDATE payments SET status='paid' WHERE payload=?",
                (payload,),
            )
            await db_conn.execute("""
                INSERT INTO transactions(user_id,amount,reason,created_at)
                VALUES(?,?,?,?)
            """, (
                message.from_user.id,
                tokens,
                f"Покупка за {payment['stars']} Stars",
                int(time.time()),
            ))
            await db_conn.commit()

            await message.answer(
                f"✅ Оплата прошла успешно!\nНачислено: **{money(tokens)} TOKENS**",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await db_conn.rollback()
            logger.exception("Payment processing failed")
            await message.answer("Ошибка обработки платежа. Обратитесь в поддержку.")


# ============================================================
# TOP
# ============================================================

@dp.message(F.text.in_({"🏆 Топ", "🏆 Top"}))
async def top_menu(message: Message):
    lang = await get_language(message.from_user.id)
    path = ASSETS_DIR / "top.jpg"

    if path.exists():
        sent = await message.answer_photo(
            FSInputFile(path),
            caption=tr("top", lang),
            reply_markup=top_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        sent = await message.answer(
            tr("top", lang),
            reply_markup=top_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    if message.chat.type == ChatType.PRIVATE:
        await auto_delete(sent, PRIVATE_DELETE_SECONDS)


@dp.callback_query(F.data.startswith("top_"))
async def top_callback(callback: CallbackQuery):
    category = callback.data.split("_", 1)[1]

    if category == "donate":
        query = """
            SELECT username,full_name,donated_stars AS score
            FROM users ORDER BY donated_stars DESC LIMIT 10
        """
        title = "💎 ТОП ПО ДОНАТУ"
    elif category == "ref":
        query = """
            SELECT username,full_name,referrals AS score
            FROM users ORDER BY referrals DESC LIMIT 10
        """
        title = "👥 ТОП ПО РЕФЕРАЛАМ"
    else:
        query = """
            SELECT username,full_name,balance AS score
            FROM users ORDER BY balance DESC LIMIT 10
        """
        title = "💰 ТОП ПО БАЛАНСУ"

    rows = await db_fetchall(query)
    if not rows:
        lang = await get_language(callback.from_user.id)
        await callback.answer(tr("top_empty", lang), show_alert=True)
        return

    lines = [f"🏆 **{title}**\n"]
    for index, row in enumerate(rows, 1):
        name = row["username"] or row["full_name"] or "Игрок"
        lines.append(f"{index}. {html.escape(name)} — {money(row['score'])}")

    await callback.message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


# ============================================================
# REFERRAL MENU
# ============================================================

@dp.message(F.text.in_({"🔗 Рефералка", "🔗 Referrals"}))
async def referral_handler(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    try:
        picture = await make_referral_image(user_id)
        await message.answer_photo(
            BufferedInputFile(picture, filename="referrals.jpg"),
        )
    except Exception:
        logger.exception("Referral image error")
        path = ASSETS_DIR / "ref.jpg"
        if path.exists():
            await message.answer_photo(FSInputFile(path))
        else:
            await message.answer("РЕФЕРАЛЬНАЯ ПРОГРАММА")

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [hidden_url_button("🔗 Пригласить друга", link)],
        [hidden_url_button("📢 Канал турниров", BONUS_CHANNEL_URL)],
    ])

    await message.answer(
        f"Приглашено: **{user['referrals']}**\n"
        f"Заработано: **{money(user['referral_earned'])} TOKENS**",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# VIP — SIMPLE TIME-BASED STATUS
# ============================================================

@dp.callback_query(F.data == "vip")
async def vip_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 день — 5⭐", callback_data="vipbuy_1"),
            InlineKeyboardButton(text="3 дня — 15⭐", callback_data="vipbuy_3"),
        ],
        [
            InlineKeyboardButton(text="7 дней — 35⭐", callback_data="vipbuy_7"),
            InlineKeyboardButton(text="30 дней — 150⭐", callback_data="vipbuy_30"),
        ],
    ])

    await callback.message.answer(
        "⭐ **TOKENS VIP**\n\n"
        "VIP даёт увеличенный бонус и специальный статус.\n"
        "Стоимость: 5 Stars за один день.",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("vipbuy_"))
async def vip_buy_callback(callback: CallbackQuery):
    try:
        days = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer()
        return

    if days not in (1, 3, 7, 30):
        await callback.answer("Неверный срок", show_alert=True)
        return

    stars = days * 5
    payload = f"vip:{callback.from_user.id}:{days}:{int(time.time())}"

    await db_execute("""
        INSERT INTO payments(payload,user_id,stars,tokens,status,created_at)
        VALUES(?,?,?,?,?,?)
    """, (payload, callback.from_user.id, stars, 0, "pending", int(time.time())))

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="TOKENS VIP",
        description=f"VIP на {days} дн.",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"VIP {days} days", amount=stars)],
    )
    await callback.answer()


# ============================================================
# GAME ENGINE
# ============================================================

DICE_GAMES = {
    "кости": {
        "emoji": "🎲",
        "name": "Кости",
        "win_values": {4, 5, 6},
        "all_values": {1, 2, 3, 4, 5, 6},
    },
    "дартс": {
        "emoji": "🎯",
        "name": "Дартс",
        "win_values": {6},
        "all_values": set(range(1, 7)),
    },
    "баскет": {
        "emoji": "🏀",
        "name": "Баскетбол",
        "win_values": {4, 5},
        "all_values": set(range(1, 6)),
    },
    "футбол": {
        "emoji": "⚽",
        "name": "Футбол",
        "win_values": {3, 4},
        "all_values": set(range(1, 6)),
    },
    "боулинг": {
        "emoji": "🎳",
        "name": "Боулинг",
        "win_values": {6},
        "all_values": set(range(1, 7)),
    },
}


async def play_dice_game(message: Message, game_key: str, bet: int):
    user_id = message.from_user.id
    game = DICE_GAMES[game_key]
    lang = await get_language(user_id)

    if bet <= 0:
        await answer_temporary(message, tr("game_amount", lang), GAME_DELETE_SECONDS)
        return

    if not await change_balance(user_id, -bet, f"Ставка: {game['name']}"):
        await answer_temporary(message, tr("game_funds", lang), GAME_DELETE_SECONDS)
        return

    try:
        dice_message = await message.answer_dice(emoji=game["emoji"])
        await asyncio.sleep(3)

        value = dice_message.dice.value
        won = value in game["win_values"]
        payout = bet * 2 if won else 0

        if payout:
            await change_balance(user_id, payout, f"Выигрыш: {game['name']}")

        await add_game_log(
            user_id,
            game["name"],
            bet,
            payout,
            f"Выпало {value}",
        )

        user = await get_user(user_id)
        outcome = (
            f"🎉 Выигрыш: +{money(payout)} TOKENS"
            if won else "😔 Вы проиграли."
        )

        result = await message.answer(
            tr(
                "game_result",
                lang,
                game=game["name"],
                bet=money(bet),
                result=f"{value}",
                outcome=outcome,
                balance=money(user["balance"]),
            ),
        )

        await auto_delete(dice_message, GAME_DELETE_SECONDS)
        await auto_delete(result, GAME_DELETE_SECONDS)

    except Exception:
        logger.exception("Game error")
        await change_balance(user_id, bet, "Возврат ставки: ошибка игры")
        await answer_temporary(
            message,
            "Произошла ошибка игры. Ставка возвращена.",
            GAME_DELETE_SECONDS,
        )


@dp.message(F.text)
async def game_commands(message: Message):
    if not message.from_user or not message.text:
        return

    text = message.text.strip().lower()
    parts = text.split()

    if not parts:
        return

    game_key = parts[0]
    if game_key not in DICE_GAMES:
        return

    lang = await get_language(message.from_user.id)

    if len(parts) != 2 or not parts[1].isdigit():
        await answer_temporary(
            message,
            tr("game_bet", lang, command=game_key),
            GAME_DELETE_SECONDS,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await play_dice_game(message, game_key, int(parts[1]))


# ============================================================
# GROUP BALANCE / LOG / TOP / UPDATES
# ============================================================

async def make_user_summary_image(user_id, title="ИНФОРМАЦИЯ"):
    user = await get_user(user_id)
    stats = await get_game_stats(user_id)

    img = Image.new("RGB", (900, 480), (15, 20, 38))
    draw = ImageDraw.Draw(img)
    draw.text((45, 35), title, font=get_font(38, True), fill=(255, 220, 120))

    lines = [
        f"Игрок: {user['full_name']}",
        f"Баланс: {money(user['balance'])} TOKENS",
        f"Ставки: {money(stats['bets'])}",
        f"Выигрыши: {money(stats['wins'])}",
        f"Проигрыши: {money(stats['losses'])}",
        f"Количество игр: {stats['games']}",
    ]

    y = 115
    for line in lines:
        draw.text((55, y), line, font=get_font(27), fill="white")
        y += 53

    return image_bytes(img)


async def group_image_reply(message, data, filename="info.jpg"):
    sent = await message.answer_photo(
        BufferedInputFile(data, filename=filename),
    )
    await auto_delete(sent, GROUP_DELETE_SECONDS)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_text_commands(message: Message):
    if not message.text or not message.from_user:
        return

    text = message.text.strip().lower()

    if text == "бот":
        sent = await message.answer("На месте!")
        await auto_delete(sent, GROUP_DELETE_SECONDS)
        return

    if text == "б":
        try:
            data = await make_user_summary_image(message.from_user.id, "ВАШ БАЛАНС")
            await group_image_reply(message, data, "balance.jpg")
        except Exception:
            logger.exception("Group balance image error")
        return

    if text == "лог":
        rows = await db_fetchall("""
            SELECT game,bet,win,result,created_at
            FROM game_log WHERE user_id=?
            ORDER BY id DESC LIMIT 8
        """, (message.from_user.id,))

        img = Image.new("RGB", (900, 520), (15, 20, 38))
        draw = ImageDraw.Draw(img)
        draw.text((40, 30), "ИСТОРИЯ ИГР", font=get_font(36, True), fill=(255, 220, 120))

        y = 105
        if not rows:
            draw.text((50, y), "История пока пуста", font=get_font(25), fill="white")
        else:
            for row in rows:
                line = f"{row['game']} | ставка {money(row['bet'])} | выплата {money(row['win'])}"
                draw.text((45, y), line, font=get_font(22), fill="white")
                y += 45

        await group_image_reply(message, image_bytes(img), "history.jpg")
        return

    if text == "топ":
        rows = await db_fetchall("""
            SELECT username,full_name,balance
            FROM users ORDER BY balance DESC LIMIT 10
        """)

        lines = ["🏆 ТОП TOKENS"]
        for i, row in enumerate(rows, 1):
            name = row["username"] or row["full_name"] or "Игрок"
            lines.append(f"{i}. {name} — {money(row['balance'])}")

        sent = await message.answer("\n".join(lines))
        await auto_delete(sent, GROUP_DELETE_SECONDS)
        return

    if text == "что нового":
        path = ASSETS_DIR / "updates.jpg"
        caption = TEXTS["ru"]["updates"]

        if path.exists():
            sent = await message.answer_photo(
                FSInputFile(path),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            data = create_text_image("ОБНОВЛЕНИЯ", "Новости проекта TOKENS")
            sent = await message.answer_photo(
                BufferedInputFile(data, filename="updates.jpg"),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )

        await auto_delete(sent, GROUP_DELETE_SECONDS)


# ============================================================
# ROULETTE — MULTI-PARSER
# ============================================================

roulette_open = set()
roulette_lock = asyncio.Lock()

# Цвета европейской рулетки.
RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
}
BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS


def roulette_color(number):
    if number == 0:
        return "Зеро"
    return "Красное" if number in RED_NUMBERS else "Чёрное"


def parse_roulette_selections(tokens):
    """
    Поддерживаемые формы:
      к 1000
      1000 к
      ч 1000
      1000 ч
      10-20 500
      500 10-20
      500 10-20 11-20 0 9-15 20 21

    Если первый токен — число, а дальше идут варианты,
    это общая сумма на каждый указанный вариант.
    """
    if not tokens:
        return None

    tokens = [x.lower().strip() for x in tokens if x.strip()]
    if not tokens:
        return None

    selections = []
    stake = None

    # Цветовая ставка: "к 1000" или "1000 к".
    if len(tokens) == 2:
        if tokens[0] in ("к", "красное", "ч", "черное", "чёрное"):
            if not tokens[1].isdigit():
                return None
            stake = int(tokens[1])
            selection = "red" if tokens[0] in ("к", "красное") else "black"
            return stake, [selection]

        if tokens[1] in ("к", "красное", "ч", "черное", "чёрное"):
            if not tokens[0].isdigit():
                return None
            stake = int(tokens[0])
            selection = "red" if tokens[1] in ("к", "красное") else "black"
            return stake, [selection]

    # Обычный формат: сумма первым токеном.
    if tokens[0].isdigit():
        stake = int(tokens[0])
        for token in tokens[1:]:
            if token in ("к", "красное"):
                selections.append("red")
            elif token in ("ч", "черное", "чёрное"):
                selections.append("black")
            elif token.isdigit():
                value = int(token)
                if 0 <= value <= 36:
                    selections.append(f"num:{value}")
            elif re.fullmatch(r"\d{1,2}-\d{1,2}", token):
                left, right = map(int, token.split("-", 1))
                if 0 <= left <= right <= 36:
                    selections.append(f"range:{left}:{right}")
        if stake > 0 and selections:
            return stake, selections
        return None

    # Формат варианта первым, сумма последним.
    if tokens[-1].isdigit():
        stake = int(tokens[-1])
        for token in tokens[:-1]:
            if token in ("к", "красное"):
                selections.append("red")
            elif token in ("ч", "черное", "чёрное"):
                selections.append("black")
            elif token.isdigit():
                value = int(token)
                if 0 <= value <= 36:
                    selections.append(f"num:{value}")
            elif re.fullmatch(r"\d{1,2}-\d{1,2}", token):
                left, right = map(int, token.split("-", 1))
                if 0 <= left <= right <= 36:
                    selections.append(f"range:{left}:{right}")

        if stake > 0 and selections:
            return stake, selections

    return None


def roulette_matches(selection, number):
    if selection == "red":
        return number in RED_NUMBERS, 2

    if selection == "black":
        return number in BLACK_NUMBERS, 2

    if selection.startswith("num:"):
        target = int(selection.split(":")[1])
        return number == target, 36

    if selection.startswith("range:"):
        _, left, right = selection.split(":")
        left = int(left)
        right = int(right)
        if left <= number <= right:
            multiplier = max(1, 36 // (right - left + 1))
            return True, multiplier

    return False, 0


async def roulette_add_bets(message):
    parsed = parse_roulette_selections(message.text.split())
    if not parsed:
        return False

    stake, selections = parsed
    if stake <= 0 or stake > 10_000_000:
        return False

    total_cost = stake * len(selections)
    if not await change_balance(
        message.from_user.id,
        -total_cost,
        "Ставка в рулетке",
    ):
        await message.reply("Недостаточно TOKENS для этих ставок.")
        return True

    async with db_lock:
        for selection in selections:
            await db_conn.execute("""
                INSERT INTO roulette_bets(chat_id,user_id,username,stake,selection,created_at)
                VALUES(?,?,?,?,?,?)
            """, (
                message.chat.id,
                message.from_user.id,
                message.from_user.username or message.from_user.full_name,
                stake,
                selection,
                int(time.time()),
            ))
        await db_conn.commit()

    labels = ", ".join(selections)
    sent = await message.reply(
        f"✅ Ставка принята: {money(stake)} TOKENS на каждый вариант.\n"
        f"Варианты: {labels}\n"
        f"Всего списано: {money(total_cost)} TOKENS"
    )
    await auto_delete(sent, GROUP_DELETE_SECONDS)
    return True


async def roulette_start(message):
    if message.chat.id in roulette_open:
        await message.reply("Раунд уже открыт.")
        return

    roulette_open.add(message.chat.id)
    async with db_lock:
        await db_conn.execute(
            "DELETE FROM roulette_bets WHERE chat_id=?",
            (message.chat.id,),
        )
        await db_conn.commit()

    await message.reply(TEXTS["ru"]["roulette_started"], parse_mode=ParseMode.MARKDOWN)


async def roulette_stop(message):
    chat_id = message.chat.id

    if chat_id not in roulette_open:
        await message.reply(TEXTS["ru"]["roulette_closed"])
        return

    roulette_open.discard(chat_id)
    bets = await db_fetchall(
        "SELECT * FROM roulette_bets WHERE chat_id=?",
        (chat_id,),
    )

    if not bets:
        await message.reply(TEXTS["ru"]["roulette_no_bets"])
        return

    # Telegram animation 🎰 не выдаёт европейское число 0–36.
    # Поэтому реальный результат рулетки выбирается отдельно случайно.
    # Эмодзи-слот используется только как визуальная анимация.
    try:
        await message.answer_dice(emoji="🎰")
    except TelegramAPIError:
        pass

    await asyncio.sleep(3)
    number = random.randint(0, 36)
    color = roulette_color(number)

    payouts_by_user = {}
    won_lines = []

    for bet in bets:
        matched, multiplier = roulette_matches(bet["selection"], number)
        if matched:
            payout = int(bet["stake"]) * multiplier
            user_id = bet["user_id"]
            payouts_by_user[user_id] = payouts_by_user.get(user_id, 0) + payout
            won_lines.append(
                f"• {bet['username']}: {bet['selection']} — +{money(payout)} TOKENS"
            )

    for user_id, payout in payouts_by_user.items():
        await change_balance(user_id, payout, "Выигрыш в рулетке")

    winners_text = "\n".join(won_lines) if won_lines else TEXTS["ru"]["roulette_lose"]

    result_message = await message.answer(
        TEXTS["ru"]["roulette_result"].format(
            number=number,
            color=color,
            winners=winners_text,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=roulette_result_keyboard(),
    )
    await auto_delete(result_message, GROUP_DELETE_SECONDS)

    await db_execute(
        "DELETE FROM roulette_bets WHERE chat_id=?",
        (chat_id,),
    )


@dp.callback_query(F.data.in_({"roulette_repeat", "roulette_double"}))
async def roulette_repeat_callback(callback: CallbackQuery):
    await callback.message.answer(
        "Чтобы повторить ставку, отправьте её ещё раз в чат.\n"
        "Пример: `500 10-20 0 21`",
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback.answer()


# ============================================================
# ADMIN HELPERS
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def resolve_target(message, token=None):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id

    if not token:
        return None

    token = token.strip()

    if token.startswith("@"):
        username = token[1:].lower()
        row = await db_fetchone(
            "SELECT user_id FROM users WHERE lower(username)=?",
            (username,),
        )
        return int(row["user_id"]) if row else None

    if token.isdigit():
        return int(token)

    return None


async def admin_target_and_amount(message, parts):
    """
    Поддерживает:
      @выдать 123456 1000
      @выдать @username 1000
      reply + @выдать 1000
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        if not parts:
            return message.reply_to_message.from_user.id, None
        if parts[0].isdigit():
            return message.reply_to_message.from_user.id, int(parts[0])

    if len(parts) >= 2:
        target = await resolve_target(message, parts[0])
        amount = int(parts[1]) if parts[1].isdigit() else None
        return target, amount

    if len(parts) == 1:
        target = await resolve_target(message, parts[0])
        return target, None

    return None, None


@dp.message(F.text.startswith("@помощь"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id):
        return

    text = (
        "🛠 **АДМИН-ПАНЕЛЬ**\n\n"
        "`@помощь` — список команд\n"
        "`@скан ID/@username` — информация об игроке\n"
        "`@выдать ID сумма` — начислить TOKENS\n"
        "`@дроп ID сумма` — списать TOKENS\n"
        "`@бан ID` — заблокировать/разблокировать\n"
        "`@стата` — статистика бота\n"
        "`@бекап` — резервная копия базы\n"
        "`@рассылка текст` — рассылка сообщения\n"
        "`@стоп` — остановить раунд рулетки"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(F.text.startswith("@скан"))
async def admin_scan(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()[1:]
    target = await resolve_target(message, parts[0] if parts else None)

    if not target:
        await message.reply("Использование: `@скан ID` или ответом на сообщение.")
        return

    user = await get_user(target)
    if not user:
        await message.reply("Пользователь не найден в базе.")
        return

    data = await make_user_summary_image(target, "СКАН ИГРОКА")
    await message.answer_photo(
        BufferedInputFile(data, filename="scan.jpg"),
        caption=(
            f"ID: `{target}`\n"
            f"Username: @{user['username']}\n"
            f"VIP до: `{user['vip_until']}`\n"
            f"Рефералов: `{user['referrals']}`\n"
            f"Донат Stars: `{user['donated_stars']}`"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.message(F.text.startswith("@выдать"))
async def admin_give(message: Message):
    if not is_admin(message.from_user.id):
        return

    target, amount = await admin_target_and_amount(
        message,
        message.text.split()[1:],
    )

    if not target or amount is None or amount <= 0:
        await message.reply("Использование: `@выдать ID сумма`")
        return

    await ensure_user(
        type("User", (), {
            "id": target,
            "username": "",
            "full_name": str(target),
            "first_name": str(target),
        })()
    )

    if not await change_balance(target, amount, f"Выдача администратором {message.from_user.id}"):
        await message.reply("Не удалось изменить баланс.")
        return

    await message.reply(f"✅ Пользователю `{target}` выдано {money(amount)} TOKENS.")


@dp.message(F.text.startswith("@дроп"))
async def admin_drop(message: Message):
    if not is_admin(message.from_user.id):
        return

    target, amount = await admin_target_and_amount(
        message,
        message.text.split()[1:],
    )

    if not target or amount is None or amount <= 0:
        await message.reply("Использование: `@дроп ID сумма`")
        return

    if not await change_balance(target, -amount, f"Списание администратором {message.from_user.id}"):
        await message.reply("Недостаточно средств или пользователь не найден.")
        return

    await message.reply(f"✅ Списано {money(amount)} TOKENS у `{target}`.")


@dp.message(F.text.startswith("@бан"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()[1:]
    target = await resolve_target(message, parts[0] if parts else None)

    if not target:
        await message.reply("Использование: `@бан ID`")
        return

    user = await get_user(target)
    if not user:
        await message.reply("Пользователь не найден.")
        return

    new_value = 0 if user["banned"] else 1
    await db_execute(
        "UPDATE users SET banned=? WHERE user_id=?",
        (new_value, target),
    )

    await message.reply(
        f"Пользователь `{target}` "
        f"{'заблокирован' if new_value else 'разблокирован'}."
    )


@dp.message(F.text.startswith("@стата"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    row = await db_fetchone("""
        SELECT
            COUNT(*) AS users,
            COALESCE(SUM(balance),0) AS balances,
            COALESCE(SUM(donated_stars),0) AS stars,
            COALESCE(SUM(referrals),0) AS referrals
        FROM users
    """)

    games = await db_fetchone("SELECT COUNT(*) AS total FROM game_log")
    payments = await db_fetchone(
        "SELECT COUNT(*) AS total FROM payments WHERE status='paid'"
    )

    await message.reply(
        "📊 **СТАТИСТИКА TOKENS**\n\n"
        f"Пользователей: {row['users']}\n"
        f"Балансовая сумма: {money(row['balances'])}\n"
        f"Куплено Stars: {row['stars']}\n"
        f"Рефералов: {row['referrals']}\n"
        f"Игр: {games['total']}\n"
        f"Оплаченных платежей: {payments['total']}",
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.message(F.text.startswith("@бекап"))
async def admin_backup(message: Message):
    if not is_admin(message.from_user.id):
        return

    try:
        await db_conn.execute("PRAGMA wal_checkpoint(FULL)")
        await db_conn.commit()

        temp_path = BASE_DIR / f"tokens_backup_{int(time.time())}.sqlite3"

        def make_backup():
            source = sqlite3.connect(DATABASE)
            destination = sqlite3.connect(temp_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

        await asyncio.to_thread(make_backup)

        await message.answer_document(
            FSInputFile(temp_path),
            caption="🗄 Резервная копия базы данных.",
        )

        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    except Exception:
        logger.exception("Backup failed")
        await message.reply("Не удалось создать резервную копию.")


@dp.message(F.text.startswith("@рассылка"))
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text.partition(" ")[2].strip()
    if not text:
        await state.set_state(BroadcastState.waiting)
        await message.answer("Отправьте текст рассылки следующим сообщением.")
        return

    await run_broadcast(message, text)


@dp.message(BroadcastState.waiting)
async def admin_broadcast_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await run_broadcast(message, message.text or "")


async def run_broadcast(message, text):
    users = await db_fetchall("SELECT user_id FROM users WHERE banned=0")
    success = 0
    failed = 0

    status = await message.answer("📨 Начинаю рассылку...")

    for row in users:
        try:
            await bot.send_message(row["user_id"], text)
            success += 1
            await asyncio.sleep(0.04)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.send_message(row["user_id"], text)
                success += 1
            except Exception:
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

    await status.edit_text(
        f"Рассылка завершена.\nУспешно: {success}\nОшибок: {failed}"
    )


# ============================================================
# ADMIN ROULETTE COMMANDS AND GENERAL MESSAGE ROUTER
# ============================================================

@dp.message(F.text.regexp(r"(?i)^старт$"))
async def roulette_start_command(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("Рулетка запускается в групповом чате.")
        return
    await roulette_start(message)


@dp.message(F.text.regexp(r"(?i)^@стоп$"))
async def roulette_stop_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    await roulette_stop(message)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def roulette_bets_router(message: Message):
    if not message.text or not message.from_user:
        return

    text = message.text.strip().lower()

    if text in {"старт", "топ", "б", "лог", "бот", "что нового"}:
        return

    if text.startswith("@"):
        return

    if message.chat.id not in roulette_open:
        return

    await roulette_add_bets(message)


# ============================================================
# BANNED USER MIDDLEWARE-LIKE CHECK
# ============================================================

@dp.message()
async def final_message_guard(message: Message):
    if not message.from_user:
        return

    user = await get_user(message.from_user.id)
    if user and user["banned"]:
        try:
            await message.delete()
        except TelegramAPIError:
            pass
        return


@dp.callback_query()
async def final_callback_guard(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if user and user["banned"]:
        await callback.answer("Ваш аккаунт заблокирован.", show_alert=True)
        return


# ============================================================
# HTTP HEALTH SERVER — RENDER
# ============================================================

async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "service": "TOKENS",
        "time": int(time.time()),
    })


async def start_http_server():
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
    logger.info("HTTP server started on port %s", PORT)

    return runner


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

async def main():
    global bot, bot_username, bot_name

    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавьте переменную окружения BOT_TOKEN."
        )

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    me = await bot.get_me()
    bot_username = me.username or "TOKENS"
    bot_name = me.first_name or "TOKENS"

    logger.info("Bot started: @%s", bot_username)

    http_runner = await start_http_server()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await http_runner.cleanup()

        if db_conn:
            await db_conn.close()

        if bot:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())