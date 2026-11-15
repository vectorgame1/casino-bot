import os
import re
import io
import json
import math
import time
import html
import shutil
import random
import secrets
import logging
import string
import asyncio
import sqlite3
import tempfile

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any
from contextlib import suppress

import aiosqlite
from aiohttp import web

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType, ParseMode
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
    ChatMemberUpdated,
    FSInputFile,
)

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramAPIError,
)

# ============================================================
# 1. CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "tokens.sqlite3")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME", ""
).lstrip("@")

NEWS_CHANNEL = os.getenv(
    "NEWS_CHANNEL", "@tokens_news"
)

BOT_NAME = "TOKENS"

ASSETS = Path("assets")
PROFILE_BG = ASSETS / "profile_bg.jpg"
VIP_BG = ASSETS / "vip_bg.jpg"
FONT_PATH = ASSETS / "Montserrat-Bold.ttf"

DEFAULT_BALANCE = 1000
REFERRAL_REWARD = 5000
NORMAL_BONUS = 2500
BONUS_COOLDOWN = 12 * 60 * 60

MIN_BET = 1
MAX_BET = 1_000_000

PRIVATE_TTL = 30
GAME_TTL = 15
GROUP_TTL = 60

CAPTCHA_TTL = 300

# ============================================================
# 2. LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")

# ============================================================
# 3. GLOBAL OBJECTS
# ============================================================

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = Dispatcher(storage=MemoryStorage())

db_conn: Optional[aiosqlite.Connection] = None

db_init_lock = asyncio.Lock()
db_lock = asyncio.Lock()

captcha_data: dict[int, dict] = {}
active_games: set[int] = set()
pending_duels: dict[int, dict] = {}

started_at = time.time()

# ============================================================
# 4. CONSTANTS
# ============================================================

GAMES = {
    "dice": {
        "ru": "Кости",
        "en": "Dice",
        "emoji": "🎲",
        "telegram": "🎲",
    },
    "dart": {
        "ru": "Дартс",
        "en": "Darts",
        "emoji": "🎯",
        "telegram": "🎯",
    },
    "basketball": {
        "ru": "Баскет",
        "en": "Basketball",
        "emoji": "🏀",
        "telegram": "🏀",
    },
    "football": {
        "ru": "Футбол",
        "en": "Football",
        "emoji": "⚽",
        "telegram": "⚽",
    },
    "bowling": {
        "ru": "Боулинг",
        "en": "Bowling",
        "emoji": "🎳",
        "telegram": "🎳",
    },
}

GAME_ALIASES = {
    "кости": "dice",
    "кость": "dice",
    "dice": "dice",
    "дартс": "dart",
    "dart": "dart",
    "darts": "dart",
    "баскет": "basketball",
    "баскетбол": "basketball",
    "basket": "basketball",
    "basketball": "basketball",
    "футбол": "football",
    "football": "football",
    "боулинг": "bowling",
    "bowling": "bowling",
}

# Награда за покупку доната.
DONATION_REWARDS = {
    10: 7500,
    50: 7500,
    100: 8000,
    200: 8500,
    300: 8500,
    400: 9000,
    500: 10000,
}

VIP_DAYS = {
    1: 5,
    3: 15,
    7: 35,
    30: 150,
}

# ============================================================
# 5. FSM
# ============================================================

class BotStates(StatesGroup):
    custom_stars = State()
    transfer = State()
    support_message = State()
    admin_broadcast = State()
    admin_give = State()
    captcha = State()


# ============================================================
# 6. LOCALIZATION
# ============================================================

TEXTS = {
    "ru": {
        "games": "🎮 Как играть?",
        "bonus": "🎁 Бонус",
        "donate": "💎 Донат",
        "profile": "👤 Профиль",
        "top": "🏆 Топ",
        "referral": "🔗 Рефералка",

        "back": "⬅️ Назад",
        "settings": "⚙️ Настройки",
        "vip": "⭐ Купить VIP",

        "welcome": "Добро пожаловать в TOKENS!\nРеши капчу для доступа к клубу.",
        "captcha": "Введи цифры с картинки.",
        "captcha_wrong": "❌ Неверный код. Попробуй снова.",
        "captcha_expired": "⌛ Капча устарела. Отправь /start.",
        "captcha_success": "✅ Проверка пройдена!",

        "menu_hint": "Выбери нужный раздел.",
        "games_title": "🎮 **КАК ИГРАТЬ?**",
        "game_help": "Игры:\n🎲 Кости\n🎯 Дартс\n🏀 Баскет\n⚽ Футбол\n🎳 Боулинг\n\nФормат ставки:\n`кости 1000`\n\nТакже доступны команды:\n`дуэль @user 1000`\n`перевод @user 1000`",

        "bonus": "🎁 Бонус",
        "bonus_success": "🎁 Ты получил {amount} TOKENS!",
        "bonus_wait": "⏳ Следующий бонус через {hours} ч. {minutes} мин.",
        "subscribe": "Для получения бонуса подпишись на канал @tokens_news.",

        "profile": "👤 Профиль",
        "profile_error": "Не удалось создать профиль.",

        "language": "🌐 Язык",
        "language_changed": "Язык изменён.",

        "transfer_block": "🚫 Запрет переводов",
        "transfer_allowed": "✅ Разрешить переводы",
        "transfer_blocked": "Переводы отключены в настройках получателя.",
        "transfer_success": "Перевод {amount} TOKENS выполнен.",

        "donate_title": "💎 Выбери пакет Telegram Stars:",
        "custom_stars": "✍️ Своя сумма",
        "custom_prompt": "Введи количество Stars от 1 до 10000.",
        "custom_invalid": "Введи целое число от 1 до 10000.",
        "payment_success": "Оплата прошла! Начислено {amount} TOKENS.",
        "payment_failed": "Не удалось обработать оплату.",

        "vip_title": "⭐ VIP CLUB",
        "vip_description": "Преимущества VIP:\n\n"
            "💰 Бонусы x2\n"
            "🎁 Автозабор бонуса\n"
            "👻 Скрытие баланса в топе\n"
            "💎 +2.5% к донату\n"
            "✨ Премиум-оформление имени\n"
            "🎲 +2.5% от дневных проигрышей\n\n"
            "Цена: 5 Stars за 1 день.",
        "vip_success": "⭐ VIP активирован на {days} дней!",

        "top_title": "🏆 РЕЙТИНГ ИГРОКОВ",
        "top_balance": "Топ по балансу",
        "top_donate": "Топ по донату",
        "top_referrals": "Топ по рефералам",

        "referral_title": "🔗 РЕФЕРАЛЬНАЯ ПРОГРАММА",
        "referral_reward": "За каждого нового приглашённого игрока ты получаешь 5000 TOKENS.",
        "referral_stats": "Приглашено: {count}\nЗаработано: {earned}",

        "support": "🆘 Поддержка",
        "chats": "💬 Чаты",
        "support_prompt": "Напиши сообщение для администрации.",
        "support_sent": "Сообщение отправлено администрации.",

        "not_verified": "Сначала пройди проверку через /start.",
        "banned": "🚫 Аккаунт заблокирован.",
        "not_enough": "Недостаточно TOKENS. Баланс: {balance}",
        "invalid_bet": "Неверная ставка. Пример: `кости 1000`.",
        "bet_range": "Ставка должна быть от {minimum} до {maximum}.",
        "game_busy": "Подожди завершения предыдущей игры.",
        "game_win": "🎉 ПОБЕДА!\nРезультат: {value}\nВыигрыш: +{prize} TOKENS",
        "game_lose": "😔 Проигрыш.\nРезультат: {value}\nСтавка: {bet} TOKENS",
        "game_started": "Ставка {bet} TOKENS принята!",
        "game_refund": "Ошибка игры. Ставка возвращена.",

        "duel_sent": "⚔️ Вызов отправлен игроку {name}.",
        "duel_received": "⚔️ {name} вызывает тебя на дуэль!\nСтавка: {bet} TOKENS",
        "duel_accept": "⚔️ Принять дуэль",
        "duel_decline": "❌ Отклонить",
        "duel_result": "🏆 Победитель: {winner}\nПриз: {prize} TOKENS",

        "group_balance": "Баланс: {balance} TOKENS",
        "group_bot": "На месте!",
        "group_updates": "✨ ЧТО НОВОГО\nИгровой клуб TOKENS работает!",

        "admin_only": "Нет доступа.",
        "admin_help": "АДМИН-КОМАНДЫ:\n\n"
            "@помощь\n"
            "@скан USER_ID/@username\n"
            "@выдать USER_ID СУММА\n"
            "@дроп СУММА\n"
            "@бан USER_ID\n"
            "@стата\n"
            "@бекап\n"
            "@рассылка",

        "admin_done": "Готово.",
        "admin_missing": "Пользователь не найден.",
        "admin_broadcast": "Отправь текст рассылки.",
        "generic_error": "Произошла ошибка. Попробуй позже.",
    },

    "en": {
        "games": "🎮 How to play?",
        "bonus": "🎁 Bonus",
        "donate": "💎 Donate",
        "profile": "👤 Profile",
        "top": "🏆 Top",
        "referral": "🔗 Referral",

        "back": "⬅️ Back",
        "settings": "⚙️ Settings",
        "vip": "⭐ Buy VIP",

        "welcome": "Welcome to TOKENS!\nComplete the CAPTCHA to enter.",
        "captcha": "Enter the digits shown in the image.",
        "captcha_wrong": "❌ Incorrect code. Try again.",
        "captcha_expired": "⌛ CAPTCHA expired. Send /start.",
        "captcha_success": "✅ Verification complete!",

        "menu_hint": "Choose a section.",
        "games_title": "🎮 **HOW TO PLAY?**",
        "game_help": "Games:\n🎲 Dice\n🎯 Darts\n🏀 Basketball\n⚽ Football\n🎳 Bowling\n\nBet format:\n`dice 1000`\n\nOther commands:\n`duel @user 1000`\n`transfer @user 1000`",

        "bonus_success": "🎁 You received {amount} TOKENS!",
        "bonus_wait": "⏳ Next bonus in {hours}h {minutes}m.",
        "subscribe": "Subscribe to @tokens_news to claim your bonus.",

        "profile_error": "Could not generate profile.",

        "language": "🌐 Language",
        "language_changed": "Language changed.",

        "transfer_block": "🚫 Block transfers",
        "transfer_allowed": "✅ Allow transfers",
        "transfer_blocked": "This user doesn't accept transfers.",
        "transfer_success": "Transferred {amount} TOKENS.",

        "donate_title": "💎 Choose a Telegram Stars package:",
        "custom_stars": "✍️ Custom amount",
        "custom_prompt": "Enter an amount from 1 to 10000 Stars.",
        "custom_invalid": "Enter an integer between 1 and 10000.",
        "payment_success": "Payment successful! You received {amount} TOKENS.",
        "payment_failed": "Payment could not be processed.",

        "vip_title": "⭐ VIP CLUB",
        "vip_description": "VIP benefits:\n\n"
            "💰 x2 bonuses\n"
            "🎁 Automatic bonus claim\n"
            "👻 Hide balance in leaderboard\n"
            "💎 +2.5% donation bonus\n"
            "✨ Premium name styling\n"
            "🎲 +2.5% of daily losses\n\n"
            "Price: 5 Stars per day.",
        "vip_success": "⭐ VIP activated for {days} days!",

        "top_title": "🏆 PLAYER RANKING",
        "top_balance": "Top balance",
        "top_donate": "Top donations",
        "top_referrals": "Top referrals",

        "referral_title": "🔗 REFERRAL PROGRAM",
        "referral_reward": "Invite a new player and receive 5000 TOKENS.",
        "referral_stats": "Invited: {count}\nEarned: {earned}",

        "support": "🆘 Support",
        "chats": "💬 Chats",
        "support_prompt": "Write a message to the administration.",
        "support_sent": "Your message was sent.",

        "not_verified": "Verify your account using /start first.",
        "banned": "🚫 Account blocked.",
        "not_enough": "Not enough TOKENS. Balance: {balance}",
        "invalid_bet": "Invalid bet. Example: `dice 1000`.",
        "bet_range": "Bet must be between {minimum} and {maximum}.",
        "game_busy": "Wait until your previous game finishes.",
        "game_win": "🎉 YOU WON!\nResult: {value}\nPrize: +{prize} TOKENS",
        "game_lose": "😔 You lost.\nResult: {value}\nBet: {bet} TOKENS",
        "game_started": "Your {bet} TOKENS bet was accepted!",
        "game_refund": "Game error. Your bet was refunded.",

        "duel_sent": "⚔️ Challenge sent to {name}.",
        "duel_received": "⚔️ {name} challenges you!\nBet: {bet} TOKENS",
        "duel_accept": "⚔️ Accept duel",
        "duel_decline": "❌ Decline",
        "duel_result": "🏆 Winner: {winner}\nPrize: {prize} TOKENS",

        "group_balance": "Balance: {balance} TOKENS",
        "group_bot": "I'm here!",
        "group_updates": "✨ WHAT'S NEW\nTOKENS game club is online!",

        "admin_only": "Access denied.",
        "admin_help": "ADMIN COMMANDS:\n\n"
            "@помощь\n@скан USER_ID/@username\n"
            "@выдать USER_ID AMOUNT\n@дроп AMOUNT\n"
            "@бан USER_ID\n@стата\n@бекап\n@рассылка",

        "admin_done": "Done.",
        "admin_missing": "User not found.",
        "admin_broadcast": "Send the broadcast text.",
        "generic_error": "An error occurred.",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXTS else "ru"
    value = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    try:
        return value.format(**kwargs)
    except (KeyError, ValueError):
        return value


# ============================================================
# 7. DATABASE
# ============================================================

async def init_db():
    global db_conn

    async with db_init_lock:
        if db_conn is not None:
            return

        db_conn = await aiosqlite.connect(
            DATABASE_PATH,
            timeout=30,
        )

        db_conn.row_factory = aiosqlite.Row

        await db_conn.execute("PRAGMA journal_mode=WAL")
        await db_conn.execute("PRAGMA foreign_keys=ON")
        await db_conn.execute("PRAGMA busy_timeout=30000")
        await db_conn.execute("PRAGMA synchronous=NORMAL")

        await db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            full_name TEXT DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 1000,
            language TEXT NOT NULL DEFAULT 'ru',
            is_verified INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            vip_until TEXT,
            transfer_blocked INTEGER NOT NULL DEFAULT 0,
            hide_top INTEGER NOT NULL DEFAULT 0,
            auto_bonus INTEGER NOT NULL DEFAULT 0,
            total_bets INTEGER NOT NULL DEFAULT 0,
            total_won INTEGER NOT NULL DEFAULT 0,
            total_lost INTEGER NOT NULL DEFAULT 0,
            games_count INTEGER NOT NULL DEFAULT 0,
            donation_total INTEGER NOT NULL DEFAULT 0,
            referrals INTEGER NOT NULL DEFAULT 0,
            referral_earned INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER,
            referral_paid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS game_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            bet INTEGER NOT NULL,
            result INTEGER DEFAULT 0,
            payout INTEGER DEFAULT 0,
            outcome TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            balance_after INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id INTEGER PRIMARY KEY,
            claimed_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            charge_id TEXT UNIQUE,
            stars INTEGER NOT NULL,
            tokens INTEGER NOT NULL,
            payment_type TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER UNIQUE NOT NULL,
            reward INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER NOT NULL,
            opponent_id INTEGER NOT NULL,
            bet INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            winner_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_losses (
            user_id INTEGER PRIMARY KEY,
            loss_amount INTEGER DEFAULT 0,
            loss_date TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_users_balance
        ON users(balance DESC);

        CREATE INDEX IF NOT EXISTS idx_game_user
        ON game_log(user_id);

        CREATE INDEX IF NOT EXISTS idx_transactions_user
        ON transactions(user_id);
        """)

        # Миграции для уже существующей базы.
        cursor = await db_conn.execute(
            "PRAGMA table_info(users)"
        )
        columns = {
            row["name"] for row in await cursor.fetchall()
        }
        await cursor.close()

        migrations = {
            "vip_until": "TEXT",
            "transfer_blocked": "INTEGER DEFAULT 0",
            "hide_top": "INTEGER DEFAULT 0",
            "auto_bonus": "INTEGER DEFAULT 0",
            "total_bets": "INTEGER DEFAULT 0",
            "total_won": "INTEGER DEFAULT 0",
            "total_lost": "INTEGER DEFAULT 0",
            "games_count": "INTEGER DEFAULT 0",
            "donation_total": "INTEGER DEFAULT 0",
            "referrals": "INTEGER DEFAULT 0",
            "referral_earned": "INTEGER DEFAULT 0",
            "referred_by": "INTEGER",
            "referral_paid": "INTEGER DEFAULT 0",
        }

        for column, definition in migrations.items():
            if column not in columns:
                await db_conn.execute(
                    f"ALTER TABLE users ADD COLUMN {column} {definition}"
                )

        await db_conn.commit()

        logger.info("Database initialized.")


def db():
    if db_conn is None:
        raise RuntimeError("Database not initialized")
    return db_conn


async def close_db():
    global db_conn
    if db_conn is not None:
        async with db_lock:
            await db_conn.commit()
            await db_conn.close()
            db_conn = None


# ============================================================
# 8. USER DATABASE FUNCTIONS
# ============================================================

async def get_user(user_id: int):
    cursor = await db().execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return row


async def ensure_user(user_id, username="", full_name=""):
    async with db_lock:
        await db().execute("""
            INSERT INTO users (
                user_id, username, full_name, balance
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
        """, (
            user_id,
            username or "",
            full_name or "",
            DEFAULT_BALANCE,
        ))
        await db().commit()

    return await get_user(user_id)


async def user_language(user_id):
    user = await get_user(user_id)
    if user and user["language"] in TEXTS:
        return user["language"]
    return "ru"


async def is_verified(user_id):
    user = await get_user(user_id)
    return bool(user and user["is_verified"])


async def is_banned(user_id):
    user = await get_user(user_id)
    return bool(user and user["is_banned"])


async def set_language(user_id, language):
    if language not in TEXTS:
        return False

    async with db_lock:
        await db().execute(
            "UPDATE users SET language=? WHERE user_id=?",
            (language, user_id),
        )
        await db().commit()

    return True


# ============================================================
# 9. BALANCE TRANSACTIONS
# ============================================================

async def change_balance(
    user_id: int,
    amount: int,
    reason: str = "Изменение баланса",
):
    """
    Поддерживает положительные и отрицательные суммы.

    Важно:
    отрицательное значение amount используется для списания.

    При недостаточном балансе операция отменяется.
    """

    if not isinstance(amount, int):
        raise TypeError("amount must be int")

    async with db_lock:
        conn = db()

        try:
            await conn.execute("BEGIN TRANSACTION")

            cursor = await conn.execute(
                "SELECT balance FROM users WHERE user_id=?",
                (user_id,),
            )
            user = await cursor.fetchone()
            await cursor.close()

            if user is None:
                await conn.rollback()
                return False

            balance = int(user["balance"])

            if balance + amount < 0:
                await conn.rollback()
                return False

            new_balance = balance + amount

            await conn.execute(
                "UPDATE users SET balance=? WHERE user_id=?",
                (new_balance, user_id),
            )

            await conn.execute("""
                INSERT INTO transactions (
                    user_id, amount, reason, balance_after
                )
                VALUES (?, ?, ?, ?)
            """, (
                user_id,
                amount,
                reason,
                new_balance,
            ))

            await conn.commit()

            return True

        except Exception:
            await conn.rollback()
            logger.exception("Balance transaction error")
            raise


async def get_balance(user_id):
    user = await get_user(user_id)
    return int(user["balance"]) if user else 0


# ============================================================
# 10. REPLY MENU
# ============================================================

def main_menu(lang="ru"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=tr(lang, "games")),
                KeyboardButton(text=tr(lang, "bonus")),
            ],
            [
                KeyboardButton(text=tr(lang, "donate")),
                KeyboardButton(text=tr(lang, "profile")),
            ],
            [
                KeyboardButton(text=tr(lang, "top")),
                KeyboardButton(text=tr(lang, "referral")),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ============================================================
# 11. INLINE KEYBOARDS
# ============================================================

def captcha_keyboard(lang="ru"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Я не робот" if lang == "ru" else "🤖 I'm human",
                    callback_data="captcha_begin",
                )
            ]
        ]
    )


def games_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Кости",
                    callback_data="game_dice",
                ),
                InlineKeyboardButton(
                    text="🎯 Дартс",
                    callback_data="game_dart",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏀 Баскет",
                    callback_data="game_basketball",
                ),
                InlineKeyboardButton(
                    text="⚽ Футбол",
                    callback_data="game_football",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎳 Боулинг",
                    callback_data="game_bowling",
                )
            ],
        ]
    )


def donation_keyboard():
    buttons = [
        InlineKeyboardButton(
            text=f"{stars}⭐",
            callback_data=f"donate_{stars}",
        )
        for stars in (10, 50, 100, 200, 300, 400, 500)
    ]

    rows = [
        buttons[:2],
        buttons[2:4],
        buttons[4:6],
        buttons[6:7],
        [
            InlineKeyboardButton(
                text="✍️ Своя сумма",
                callback_data="donate_custom",
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keyboard(lang):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="profile_settings",
                ),
                InlineKeyboardButton(
                    text="⭐ Купить VIP",
                    callback_data="vip_open",
                ),
            ]
        ]
    )


def settings_keyboard(user, lang):
    transfer_text = (
        "🚫 Запрет переводов"
        if not user["transfer_blocked"]
        else "✅ Разрешить переводы"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌐 Русский",
                    callback_data="lang_ru",
                ),
                InlineKeyboardButton(
                    text="🌐 English",
                    callback_data="lang_en",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=transfer_text,
                    callback_data="toggle_transfers",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="profile_back",
                )
            ],
        ]
    )


def top_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 Топ по донату",
                    callback_data="top_donate",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Топ по рефералам",
                    callback_data="top_referrals",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Топ по балансу",
                    callback_data="top_balance",
                )
            ],
        ]
    )


def vip_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 день — 5⭐",
                    callback_data="vip_1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="3 дня — 15⭐",
                    callback_data="vip_3",
                )
            ],
            [
                InlineKeyboardButton(
                    text="7 дней — 35⭐",
                    callback_data="vip_7",
                )
            ],
            [
                InlineKeyboardButton(
                    text="30 дней — 150⭐",
                    callback_data="vip_30",
                )
            ],
        ]
    )


def support_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Как заработать",
                    callback_data="support_earn",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Ошибка",
                    callback_data="support_error",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✉️ Написать админу",
                    callback_data="support_admin",
                )
            ],
        ]
    )


# ============================================================
# 12. MESSAGE AUTO DELETE
# ============================================================

async def auto_delete(
    message: Message,
    seconds: int = PRIVATE_TTL,
):
    await asyncio.sleep(seconds)

    try:
        await message.delete()
    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        pass
    except Exception:
        logger.exception("Auto-delete failed")


def schedule_delete(message, seconds=PRIVATE_TTL):
    asyncio.create_task(auto_delete(message, seconds))


async def send_temp(
    message: Message,
    text: str,
    seconds=PRIVATE_TTL,
    **kwargs,
):
    sent = await message.answer(text, **kwargs)
    schedule_delete(sent, seconds)
    return sent


async def send_group_photo(
    message: Message,
    photo: bytes,
    caption: str = "",
):
    sent = await message.answer_photo(
        BufferedInputFile(photo, filename="card.png"),
        caption=caption,
        parse_mode="HTML",
    )
    schedule_delete(sent, GROUP_TTL)
    return sent


# ============================================================
# 13. IMAGE UTILITIES
# ============================================================

def load_font(size=36):
    try:
        if FONT_PATH.exists():
            return ImageFont.truetype(
                str(FONT_PATH),
                size,
            )
    except Exception:
        logger.exception("Font loading error")

    try:
        return ImageFont.truetype(
            "DejaVuSans-Bold.ttf",
            size,
        )
    except Exception:
        return ImageFont.load_default()


def create_background(size, path=None):
    if path and path.exists():
        try:
            image = Image.open(path).convert("RGB")
            image = ImageOps.fit(image, size)
            return image
        except Exception:
            logger.exception("Background loading failed")

    return Image.new("RGB", size, (10, 10, 15))


def draw_text_outline(
    draw,
    xy,
    text,
    font,
    fill=(255, 255, 255),
    outline=(0, 0, 0),
    width=2,
):
    x, y = xy

    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                draw.text(
                    (x + dx, y + dy),
                    text,
                    font=font,
                    fill=outline,
                )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
    )


def image_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# 14. CAPTCHA IMAGE
# ============================================================

def generate_captcha():
    code = "".join(
        secrets.choice("23456789")
        for _ in range(random.choice([3, 4]))
    )

    image = Image.new(
        "RGB",
        (720, 360),
        (15, 15, 25),
    )

    draw = ImageDraw.Draw(image)

    for _ in range(2500):
        x = random.randint(0, 719)
        y = random.randint(0, 359)

        color = (
            random.randint(30, 120),
            random.randint(30, 120),
            random.randint(30, 120),
        )

        draw.point((x, y), fill=color)

    for _ in range(25):
        draw.line(
            [
                (
                    random.randint(0, 720),
                    random.randint(0, 360),
                ),
                (
                    random.randint(0, 720),
                    random.randint(0, 360),
                ),
            ],
            fill=(
                random.randint(70, 180),
                random.randint(70, 180),
                random.randint(70, 180),
            ),
            width=random.randint(1, 4),
        )

    font = load_font(120)

    bbox = draw.textbbox(
        (0, 0),
        code,
        font=font,
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (720 - text_width) // 2
    y = (360 - text_height) // 2 - 15

    draw_text_outline(
        draw,
        (x, y),
        code,
        font,
        fill=(255, 215, 90),
        outline=(0, 0, 0),
        width=5,
    )

    image = image.filter(
        ImageFilter.GaussianBlur(0.35)
    )

    return code, image_bytes(image)


# ============================================================
# 15. PROFILE IMAGE
# ============================================================

async def get_avatar(user_id):
    try:
        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]

        file = await bot.get_file(photo.file_id)

        buffer = io.BytesIO()

        await bot.download_file(
            file.file_path,
            destination=buffer,
        )

        buffer.seek(0)

        return Image.open(buffer).convert("RGB")

    except Exception:
        return None


def circle_avatar(avatar, size=220):
    if avatar is None:
        avatar = Image.new(
            "RGB",
            (size, size),
            (45, 45, 55),
        )

    avatar = ImageOps.fit(
        avatar,
        (size, size),
    )

    mask = Image.new(
        "L",
        (size, size),
        0,
    )

    ImageDraw.Draw(mask).ellipse(
        (0, 0, size - 1, size - 1),
        fill=255,
    )

    result = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )

    result.paste(
        avatar.convert("RGBA"),
        (0, 0),
        mask,
    )

    return result


async def generate_profile_image(user, avatar=None):
    image = create_background(
        (1200, 700),
        PROFILE_BG,
    ).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 110),
    )

    image.alpha_composite(overlay)

    draw = ImageDraw.Draw(image)

    draw_text_outline(
        draw,
        (45, 25),
        "TOKENS CLUB",
        load_font(55),
        fill=(255, 215, 80),
        width=3,
    )

    avatar_circle = circle_avatar(
        avatar,
        220,
    )

    image.alpha_composite(
        avatar_circle,
        (55, 150),
    )

    draw.ellipse(
        (48, 143, 282, 377),
        outline=(255, 195, 55),
        width=9,
    )

    lang = user["language"]

    labels = (
        [
            ("ИМЯ", user["full_name"]),
            ("ID", str(user["user_id"])),
            ("БАЛАНС", f'{user["balance"]:,} TOKENS'),
            ("СТАВОК", f'{user["total_bets"]:,} TOKENS'),
            ("ВЫИГРЫШЕЙ", f'{user["total_won"]:,} TOKENS'),
            ("ПРОИГРЫШЕЙ", f'{user["total_lost"]:,} TOKENS'),
            ("ИГР", str(user["games_count"])),
        ]
        if lang == "ru"
        else
        [
            ("NAME", user["full_name"]),
            ("ID", str(user["user_id"])),
            ("BALANCE", f'{user["balance"]:,} TOKENS'),
            ("TOTAL BETS", f'{user["total_bets"]:,} TOKENS'),
            ("WON", f'{user["total_won"]:,} TOKENS'),
            ("LOST", f'{user["total_lost"]:,} TOKENS'),
            ("GAMES", str(user["games_count"])),
        ]
    )

    x = 340
    y = 130

    for label, value in labels:
        draw_text_outline(
            draw,
            (x, y),
            f"{label}: {value}",
            load_font(36),
            fill=(255, 255, 255),
            width=2,
        )

        y += 75

    rank = get_rank(
        user["balance"],
        lang,
    )

    draw_text_outline(
        draw,
        (55, 435),
        f"RANK: {rank}",
        load_font(39),
        fill=(255, 215, 90),
        width=2,
    )

    vip_until = user["vip_until"]

    if vip_until and is_vip_active(user):
        draw_text_outline(
            draw,
            (55, 535),
            "⭐ VIP MEMBER",
            load_font(45),
            fill=(255, 215, 80),
            width=3,
        )

    return image_bytes(image)


# ============================================================
# 16. GROUP GRAPHICS
# ============================================================

def create_group_card(title, lines):
    image = create_background(
        (1100, 620)
    )

    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 130),
    )

    image = image.convert("RGBA")
    image.alpha_composite(overlay)

    draw = ImageDraw.Draw(image)

    draw_text_outline(
        draw,
        (55, 45),
        title,
        load_font(60),
        fill=(255, 210, 70),
        width=3,
    )

    y = 165

    for line in lines[:8]:
        draw_text_outline(
            draw,
            (65, y),
            str(line)[:65],
            load_font(35),
            fill=(255, 255, 255),
            width=2,
        )

        y += 55

    return image_bytes(image)


# ============================================================
# 17. VIP
# ============================================================

def is_vip_active(user):
    if not user or not user["vip_until"]:
        return False

    try:
        expiry = datetime.fromisoformat(
            user["vip_until"]
        )

        if expiry.tzinfo is None:
            expiry = expiry.replace(
                tzinfo=timezone.utc
            )

        return expiry > datetime.now(timezone.utc)

    except Exception:
        return False


async def activate_vip(user_id, days):
    user = await get_user(user_id)

    now = datetime.now(timezone.utc)

    if user and is_vip_active(user):
        current = datetime.fromisoformat(
            user["vip_until"]
        )

        if current.tzinfo is None:
            current = current.replace(
                tzinfo=timezone.utc
            )

        now = max(now, current)

    expiry = now + timedelta(days=days)

    async with db_lock:
        await db().execute(
            "UPDATE users SET vip_until=? WHERE user_id=?",
            (expiry.isoformat(), user_id),
        )
        await db().commit()

    return expiry


async def vip_rebate(user_id, amount):
    user = await get_user(user_id)

    if not user or not is_vip_active(user):
        return

    bonus = int(amount * 0.025)

    if bonus > 0:
        await change_balance(
            user_id,
            bonus,
            "VIP daily loss cashback",
        )


async def show_vip(message):
    image = create_background(
        (1000, 650),
        VIP_BG,
    ).convert("RGBA")

    draw = ImageDraw.Draw(image)

    draw_text_outline(
        draw,
        (45, 45),
        "TOKENS VIP CLUB",
        load_font(65),
        fill=(255, 210, 70),
        width=3,
    )

    draw_text_outline(
        draw,
        (55, 180),
        "PREMIUM MEMBERSHIP",
        load_font(40),
        fill=(255, 255, 255),
    )

    await message.answer_photo(
        BufferedInputFile(
            image_bytes(image),
            filename="vip.png",
        ),
        caption=tr("ru", "vip_description"),
        reply_markup=vip_keyboard(),
    )


# ============================================================
# 18. CAPTCHA FLOW
# ============================================================

async def start_captcha(message, user):
    code, image = generate_captcha()

    captcha_data[user["user_id"]] = {
        "code": code,
        "created": time.time(),
        "photo_message_id": None,
        "prompt_message_id": None,
    }

    await message.answer(
        tr(user["language"], "welcome")
    )

    photo = await message.answer_photo(
        BufferedInputFile(
            image,
            filename="captcha.png",
        ),
        caption=tr(user["language"], "captcha"),
    )

    captcha_data[user["user_id"]]["photo_message_id"] = (
        photo.message_id
    )

    prompt = await message.answer(
        "Введи цифры с изображения:" if user["language"] == "ru"
        else "Enter the digits from the image:"
    )

    captcha_data[user["user_id"]]["prompt_message_id"] = (
        prompt.message_id
    )


async def complete_captcha(message, user):
    data = captcha_data.get(user["user_id"])

    if not data:
        return False

    if time.time() - data["created"] > CAPTCHA_TTL:
        captcha_data.pop(user["user_id"], None)

        await send_temp(
            message,
            tr(user["language"], "captcha_expired"),
        )

        return False

    if message.text.strip() != data["code"]:
        await send_temp(
            message,
            tr(user["language"], "captcha_wrong"),
        )
        return False

    async with db_lock:
        await db().execute(
            "UPDATE users SET is_verified=1 WHERE user_id=?",
            (user["user_id"],),
        )
        await db().commit()

    # Удаляем изображение и сообщение с запросом.
    for message_id in (
        data.get("photo_message_id"),
        data.get("prompt_message_id"),
    ):
        if message_id:
            try:
                await bot.delete_message(
                    message.chat.id,
                    message_id,
                )
            except Exception:
                pass

    try:
        await message.delete()
    except Exception:
        pass

    captcha_data.pop(user["user_id"], None)

    await message.answer(
        tr(user["language"], "captcha_success"),
        reply_markup=main_menu(user["language"]),
    )

    return True


# ============================================================
# 19. CHANNEL SUBSCRIPTION
# ============================================================

async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(
            NEWS_CHANNEL,
            user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception:
        logger.exception("Subscription check failed")
        return False


# ============================================================
# 20. BONUS
# ============================================================

async def claim_bonus(user_id):
    user = await get_user(user_id)

    if not user:
        return False, 0, 0

    async with db_lock:
        cursor = await db().execute(
            "SELECT claimed_at FROM daily_bonus WHERE user_id=?",
            (user_id,),
        )

        previous = await cursor.fetchone()
        await cursor.close()

        now = datetime.now(timezone.utc)

        if previous:
            last = datetime.fromisoformat(
                previous["claimed_at"]
            )

            if last.tzinfo is None:
                last = last.replace(
                    tzinfo=timezone.utc
                )

            elapsed = (now - last).total_seconds()

            if elapsed < BONUS_COOLDOWN:
                remaining = int(
                    BONUS_COOLDOWN - elapsed
                )

                await db().rollback()

                return False, 0, remaining

        if is_vip_active(user):
            amount = random.choice(
                [5000, 7500, 10000]
            )
        else:
            amount = NORMAL_BONUS

        if is_vip_active(user):
            amount *= 2

        await db().execute("""
            INSERT INTO daily_bonus(user_id, claimed_at)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET claimed_at=excluded.claimed_at
        """, (
            user_id,
            now.isoformat(),
        ))

        await db().commit()

    success = await change_balance(
        user_id,
        amount,
        "Daily bonus",
    )

    return success, amount, 0


# ============================================================
# 21. GAME LOGGING
# ============================================================

async def record_game(
    user_id,
    game,
    bet,
    result,
    payout,
    outcome,
):
    async with db_lock:
        await db().execute("""
            INSERT INTO game_log (
                user_id,
                game,
                bet,
                result,
                payout,
                outcome
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            game,
            bet,
            result,
            payout,
            outcome,
        ))

        await db().execute("""
            UPDATE users
            SET
                total_bets=total_bets+?,
                total_won=total_won+?,
                total_lost=total_lost+?,
                games_count=games_count+1
            WHERE user_id=?
        """, (
            bet,
            payout if outcome == "win" else 0,
            bet if outcome == "lose" else 0,
            user_id,
        ))

        if outcome == "lose":
            today = datetime.now(timezone.utc).date().isoformat()

            await db().execute("""
                INSERT INTO daily_losses (
                    user_id, loss_amount, loss_date
                )
                VALUES (?, ?, ?)

                ON CONFLICT(user_id)
                DO UPDATE SET
                    loss_amount =
                        CASE
                            WHEN daily_losses.loss_date=excluded.loss_date
                            THEN daily_losses.loss_amount+excluded.loss_amount
                            ELSE excluded.loss_amount
                        END,
                    loss_date=excluded.loss_date
            """, (
                user_id,
                bet,
                today,
            ))

        await db().commit()


# ============================================================
# 22. GAME ENGINE
# ============================================================

async def play_game(
    message,
    game,
    bet,
):
    user_id = message.from_user.id
    lang = await user_language(user_id)

    if user_id in active_games:
        await send_temp(
            message,
            tr(lang, "game_busy"),
            GAME_TTL,
        )
        return

    if bet < MIN_BET or bet > MAX_BET:
        await send_temp(
            message,
            tr(
                lang,
                "bet_range",
                minimum=MIN_BET,
                maximum=MAX_BET,
            ),
            GAME_TTL,
        )
        return

    if not await change_balance(
        user_id,
        -bet,
        f"Game bet: {game}",
    ):
        balance = await get_balance(user_id)

        await send_temp(
            message,
            tr(
                lang,
                "not_enough",
                balance=balance,
            ),
            GAME_TTL,
        )
        return

    active_games.add(user_id)

    try:
        await send_temp(
            message,
            tr(
                lang,
                "game_started",
                bet=bet,
            ),
            GAME_TTL,
        )

        emoji = GAMES[game]["telegram"]

        dice_message = await message.answer_dice(
            emoji=emoji
        )

        await asyncio.sleep(3)

        value = dice_message.dice.value

        won = value > 3

        payout = bet * 2 if won else 0

        if won:
            await change_balance(
                user_id,
                payout,
                f"Game win: {game}",
            )

            outcome = "win"

            result_text = tr(
                lang,
                "game_win",
                value=value,
                prize=payout,
            )

        else:
            outcome = "lose"

            result_text = tr(
                lang,
                "game_lose",
                value=value,
                bet=bet,
            )

        await record_game(
            user_id,
            game,
            bet,
            value,
            payout,
            outcome,
        )

        result_message = await message.answer(
            result_text
        )

        schedule_delete(
            dice_message,
            GAME_TTL,
        )

        schedule_delete(
            result_message,
            GAME_TTL,
        )

        if outcome == "lose":
            await vip_rebate(
                user_id,
                bet,
            )

    except Exception:
        logger.exception("Game error")

        await change_balance(
            user_id,
            bet,
            "Game refund",
        )

        await send_temp(
            message,
            tr(lang, "game_refund"),
            GAME_TTL,
        )

    finally:
        active_games.discard(user_id)


# ============================================================
# 23. DONATION CALCULATION
# ============================================================

def donation_tokens(stars):
    if stars in DONATION_REWARDS:
        return DONATION_REWARDS[stars]

    if stars >= 500:
        return stars * 20

    if stars >= 400:
        return 9000

    if stars >= 300:
        return 8500

    if stars >= 200:
        return 8500

    if stars >= 100:
        return 8000

    if stars >= 50:
        return 7500

    return max(750, stars * 750)


# ============================================================
# 24. INVOICE GENERATION
# ============================================================

async def send_stars_invoice(
    user_id,
    stars,
    payment_type="donation",
    days=0,
):
    if payment_type == "vip":
        payload = f"vip:{user_id}:{days}:{secrets.token_hex(6)}"
        title = f"TOKENS VIP {days} day(s)"
        description = f"VIP membership for {days} day(s)"
    else:
        payload = f"donation:{user_id}:{stars}:{secrets.token_hex(6)}"
        title = "TOKENS donation"
        description = "Virtual TOKENS game currency"
        
    await bot.send_invoice(
        chat_id=user_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=title,
                amount=stars,
            )
        ],
    )


# ============================================================
# 25. PAYMENT PROCESSING
# ============================================================

async def process_successful_payment(message):
    payment = message.successful_payment

    payload = payment.invoice_payload

    charge_id = payment.telegram_payment_charge_id

    if payload.startswith("vip:"):
        parts = payload.split(":")

        user_id = int(parts[1])
        days = int(parts[2])

        cursor = await db().execute(
            "SELECT id FROM payments WHERE charge_id=?",
            (charge_id,),
        )

        exists = await cursor.fetchone()
        await cursor.close()

        if exists:
            return

        await activate_vip(user_id, days)

        async with db_lock:
            await db().execute("""
                INSERT INTO payments (
                    user_id,
                    charge_id,
                    stars,
                    tokens,
                    payment_type
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                charge_id,
                payment.total_amount,
                0,
                "vip",
            ))
            await db().commit()

        await message.answer(
            tr(
                await user_language(user_id),
                "vip_success",
                days=days,
            )
        )

        return

    if payload.startswith("donation:"):
        parts = payload.split(":")

        user_id = int(parts[1])
        stars = int(parts[2])

        cursor = await db().execute(
            "SELECT id FROM payments WHERE charge_id=?",
            (charge_id,),
        )

        exists = await cursor.fetchone()
        await cursor.close()

        if exists:
            return

        tokens = donation_tokens(stars)

        user = await get_user(user_id)

        if user and is_vip_active(user):
            tokens = int(tokens * 1.025)

        success = await change_balance(
            user_id,
            tokens,
            "Telegram Stars purchase",
        )

        if not success:
            return

        async with db_lock:
            await db().execute("""
                INSERT INTO payments (
                    user_id,
                    charge_id,
                    stars,
                    tokens,
                    payment_type
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                charge_id,
                stars,
                tokens,
                "donation",
            ))

            await db().execute("""
                UPDATE users
                SET donation_total=donation_total+?
                WHERE user_id=?
            """, (
                stars,
                user_id,
            ))

            await db().commit()

        await message.answer(
            tr(
                await user_language(user_id),
                "payment_success",
                amount=tokens,
            )
        )


# ============================================================
# 26. REFERRALS
# ============================================================

async def process_referral(user_id, payload):
    if not payload or not payload.startswith("ref_"):
        return

    try:
        referrer_id = int(payload[4:])
    except ValueError:
        return

    if referrer_id == user_id:
        return

    referrer = await get_user(referrer_id)

    if not referrer:
        return

    async with db_lock:
        cursor = await db().execute(
            "SELECT id FROM referrals WHERE referred_id=?",
            (user_id,),
        )

        exists = await cursor.fetchone()
        await cursor.close()

        if exists:
            return

        await db().execute("""
            INSERT INTO referrals (
                referrer_id,
                referred_id,
                reward
            )
            VALUES (?, ?, ?)
        """, (
            referrer_id,
            user_id,
            REFERRAL_REWARD,
        ))

        await db().execute("""
            UPDATE users
            SET referrals=referrals+1,
                referral_earned=referral_earned+?
            WHERE user_id=?
        """, (
            REFERRAL_REWARD,
            referrer_id,
        ))

        await db().execute(
            "UPDATE users SET referred_by=? WHERE user_id=?",
            (referrer_id, user_id),
        )

        await db().commit()

    await change_balance(
        referrer_id,
        REFERRAL_REWARD,
        "Referral reward",
    )


# ============================================================
# 27. PROFILE STATISTICS
# ============================================================

async def profile_stats(user_id):
    user = await get_user(user_id)

    if not user:
        return None

    return {
        "balance": user["balance"],
        "total_bets": user["total_bets"],
        "total_won": user["total_won"],
        "total_lost": user["total_lost"],
        "games_count": user["games_count"],
    }


async def show_profile(message, user_id=None):
    user_id = user_id or message.from_user.id

    user = await get_user(user_id)

    if not user:
        return

    avatar = await get_avatar(user_id)

    try:
        picture = await generate_profile_image(
            user,
            avatar,
        )

        await message.answer_photo(
            BufferedInputFile(
                picture,
                filename="profile.png",
            ),
            caption=tr(
                user["language"],
                "profile",
            ),
            reply_markup=profile_keyboard(
                user["language"]
            ),
        )

    except Exception:
        logger.exception("Profile rendering failed")

        await message.answer(
            tr(user["language"], "profile_error")
        )


# ============================================================
# 28. TOP LEADERBOARD
# ============================================================

async def get_top(category):
    column = {
        "balance": "balance",
        "donate": "donation_total",
        "referrals": "referrals",
    }.get(category, "balance")

    cursor = await db().execute(f"""
        SELECT *
        FROM users
        WHERE is_verified=1
          AND is_banned=0
          AND NOT (
              hide_top=1
              AND vip_until IS NOT NULL
          )
        ORDER BY {column} DESC
        LIMIT 10
    """)

    rows = await cursor.fetchall()
    await cursor.close()

    return rows


async def render_top(category, lang="ru"):
    rows = await get_top(category)

    if not rows:
        return "Пока нет игроков."

    titles = {
        "balance": "ТОП ПО БАЛАНСУ",
        "donate": "ТОП ПО ДОНАТУ",
        "referrals": "ТОП ПО РЕФЕРАЛАМ",
    }

    lines = []

    for index, user in enumerate(rows, 1):
        name = user["full_name"] or "Player"

        if category == "balance":
            value = f'{user["balance"]:,} TOKENS'
        elif category == "donate":
            value = f'{user["donation_total"]} ⭐'
        else:
            value = str(user["referrals"])

        lines.append(
            f"{index}. {name[:20]} — {value}"
        )

    return titles[category] + "\n\n" + "\n".join(lines)


# ============================================================
# 29. HISTORY
# ============================================================

async def get_history(user_id, limit=10):
    cursor = await db().execute("""
        SELECT *
        FROM transactions
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (
        user_id,
        limit,
    ))

    rows = await cursor.fetchall()
    await cursor.close()

    return rows


# ============================================================
# 30. TRANSFERS
# ============================================================

async def transfer_tokens(
    sender_id,
    receiver_id,
    amount,
):
    if sender_id == receiver_id:
        return False, "self"

    if amount <= 0:
        return False, "amount"

    receiver = await get_user(receiver_id)

    if not receiver:
        return False, "missing"

    if receiver["transfer_blocked"]:
        return False, "blocked"

    # Перевод атомарен: обе стороны меняются в одной транзакции.
    async with db_lock:
        conn = db()

        try:
            await conn.execute("BEGIN TRANSACTION")

            cursor = await conn.execute(
                "SELECT balance FROM users WHERE user_id=?",
                (sender_id,),
            )
            sender = await cursor.fetchone()
            await cursor.close()

            cursor = await conn.execute(
                "SELECT balance FROM users WHERE user_id=?",
                (receiver_id,),
            )
            target = await cursor.fetchone()
            await cursor.close()

            if not sender or not target:
                await conn.rollback()
                return False, "missing"

            if sender["balance"] < amount:
                await conn.rollback()
                return False, "balance"

            sender_balance = sender["balance"] - amount
            target_balance = target["balance"] + amount

            await conn.execute(
                "UPDATE users SET balance=? WHERE user_id=?",
                (sender_balance, sender_id),
            )

            await conn.execute(
                "UPDATE users SET balance=? WHERE user_id=?",
                (target_balance, receiver_id),
            )

            await conn.execute("""
                INSERT INTO transactions (
                    user_id, amount, reason, balance_after
                )
                VALUES (?, ?, ?, ?)
            """, (
                sender_id,
                -amount,
                f"Transfer to {receiver_id}",
                sender_balance,
            ))

            await conn.execute("""
                INSERT INTO transactions (
                    user_id, amount, reason, balance_after
                )
                VALUES (?, ?, ?, ?)
            """, (
                receiver_id,
                amount,
                f"Transfer from {sender_id}",
                target_balance,
            ))

            await conn.commit()

            return True, "ok"

        except Exception:
            await conn.rollback()
            raise


# ============================================================
# 31. DUELS
# ============================================================

async def create_duel(
    challenger_id,
    opponent_id,
    bet,
):
    if challenger_id == opponent_id:
        return False

    if bet <= 0:
        return False

    opponent = await get_user(opponent_id)

    if not opponent or not opponent["is_verified"]:
        return False

    if not await change_balance(
        challenger_id,
        -bet,
        "Duel stake",
    ):
        return False

    async with db_lock:
        cursor = await db().execute("""
            INSERT INTO duels (
                challenger_id,
                opponent_id,
                bet
            )
            VALUES (?, ?, ?)
        """, (
            challenger_id,
            opponent_id,
            bet,
        ))

        duel_id = cursor.lastrowid
        await db().commit()

    pending_duels[duel_id] = {
        "challenger": challenger_id,
        "opponent": opponent_id,
        "bet": bet,
    }

    return duel_id


async def finish_duel(duel_id, accepted):
    duel = pending_duels.get(duel_id)

    if not duel:
        return False

    challenger = duel["challenger"]
    opponent = duel["opponent"]
    bet = duel["bet"]

    if not accepted:
        await change_balance(
            challenger,
            bet,
            "Duel refund",
        )

        pending_duels.pop(duel_id, None)

        return "declined"

    if not await change_balance(
        opponent,
        -bet,
        "Duel stake",
    ):
        await change_balance(
            challenger,
            bet,
            "Duel refund",
        )

        pending_duels.pop(duel_id, None)

        return "insufficient"

    winner = random.choice(
        [challenger, opponent]
    )

    await change_balance(
        winner,
        bet * 2,
        "Duel prize",
    )

    async with db_lock:
        await db().execute("""
            UPDATE duels
            SET status='finished',
                winner_id=?
            WHERE id=?
        """, (
            winner,
            duel_id,
        ))

        await db().commit()

    pending_duels.pop(duel_id, None)

    return winner


# ============================================================
# 32. DONATION MENU
# ============================================================

async def show_donation(message):
    lang = await user_language(
        message.from_user.id
    )

    await message.answer(
        tr(lang, "donate_title"),
        reply_markup=donation_keyboard(),
    )


# ============================================================
# 33. REFERRAL MENU
# ============================================================

async def show_referral(message):
    user_id = message.from_user.id

    me = await bot.get_me()

    user = await get_user(user_id)

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{user_id}"
    )

    text = (
        "🔗 РЕФЕРАЛЬНАЯ ПРОГРАММА\n\n"
        "Приглашай друзей и получай "
        "5000 TOKENS за каждого нового игрока.\n\n"
        f"Твоя ссылка:\n{link}\n\n"
        f"Приглашено: {user['referrals']}\n"
        f"Заработано: {user['referral_earned']} TOKENS"
    )

    image = create_group_card(
        "REFERRAL PROGRAM",
        [
            "INVITE FRIENDS",
            "+5000 TOKENS",
            f"REFERRALS: {user['referrals']}",
        ],
    )

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="referral.png",
        ),
        caption=text,
    )


# ============================================================
# 34. SUPPORT
# ============================================================

async def send_support_to_admin(message):
    user = message.from_user

    text = (
        "🆘 ОБРАЩЕНИЕ В ПОДДЕРЖКУ\n\n"
        f"ID: {user.id}\n"
        f"Username: @{user.username or 'none'}\n"
        f"Имя: {user.full_name}\n\n"
        f"{message.text or ''}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
            )
        except Exception:
            pass


# ============================================================
# 35. ADMIN HELPERS
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def find_user_by_username(username):
    username = username.lstrip("@").lower()

    cursor = await db().execute(
        "SELECT * FROM users WHERE LOWER(username)=?",
        (username,),
    )

    row = await cursor.fetchone()
    await cursor.close()

    return row


async def admin_user_info(user):
    return (
        f"👤 USER INFO\n\n"
        f"ID: {user['user_id']}\n"
        f"Username: @{user['username']}\n"
        f"Name: {user['full_name']}\n"
        f"Balance: {user['balance']}\n"
        f"Verified: {user['is_verified']}\n"
        f"Banned: {user['is_banned']}\n"
        f"VIP: {user['vip_until']}\n"
        f"Donations: {user['donation_total']}\n"
        f"Referrals: {user['referrals']}\n"
        f"Games: {user['games_count']}\n"
        f"Won: {user['total_won']}\n"
        f"Lost: {user['total_lost']}"
    )


# ============================================================
# 36. ADMIN SCAN IMAGE
# ============================================================

async def send_admin_scan(message, user):
    lines = [
        f"ID: {user['user_id']}",
        f"Username: @{user['username']}",
        f"Balance: {user['balance']}",
        f"Verified: {user['is_verified']}",
        f"Banned: {user['is_banned']}",
        f"VIP: {user['vip_until']}",
        f"Donations: {user['donation_total']}",
        f"Referrals: {user['referrals']}",
        f"Games: {user['games_count']}",
        f"Won: {user['total_won']}",
        f"Lost: {user['total_lost']}",
    ]

    image = create_group_card(
        "ADMIN USER SCAN",
        lines,
    )

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="scan.png",
        ),
        caption="Полная информация о пользователе.",
    )


# ============================================================
# 37. ADMIN STATISTICS
# ============================================================

async def get_admin_stats():
    cursor = await db().execute("""
        SELECT
            COUNT(*) AS users,
            SUM(is_verified) AS verified,
            SUM(is_banned) AS banned,
            SUM(balance) AS tokens
        FROM users
    """)

    users = await cursor.fetchone()
    await cursor.close()

    cursor = await db().execute(
        "SELECT COUNT(*) AS count FROM game_log"
    )

    games = await cursor.fetchone()
    await cursor.close()

    return {
        "users": users["users"] or 0,
        "verified": users["verified"] or 0,
        "banned": users["banned"] or 0,
        "tokens": users["tokens"] or 0,
        "games": games["count"] or 0,
    }


# ============================================================
# 38. ADMIN BACKUP
# ============================================================

async def create_backup():
    await db().commit()

    backup_dir = Path("backups")
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        "tokens_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".sqlite3"
    )

    destination = backup_dir / filename

    async with db_lock:
        target = await aiosqlite.connect(
            str(destination)
        )

        try:
            await db().backup(target)
        finally:
            await target.close()

    return str(destination)


# ============================================================
# 39. ADMIN DROP
# ============================================================

async def admin_drop(amount):
    if amount <= 0:
        return 0

    cursor = await db().execute("""
        SELECT user_id
        FROM users
        WHERE is_verified=1
          AND is_banned=0
    """)

    users = await cursor.fetchall()
    await cursor.close()

    count = 0

    for user in users:
        success = await change_balance(
            user["user_id"],
            amount,
            "Admin drop",
        )

        if success:
            count += 1

    return count


# ============================================================
# 40. ADMIN BROADCAST
# ============================================================

async def broadcast_message(text):
    cursor = await db().execute("""
        SELECT user_id
        FROM users
        WHERE is_banned=0
    """)

    users = await cursor.fetchall()
    await cursor.close()

    sent = 0
    failed = 0

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                text,
            )
            sent += 1

        except (
            TelegramForbiddenError,
            TelegramBadRequest,
        ):
            failed += 1

        except Exception:
            failed += 1

        await asyncio.sleep(0.04)

    return sent, failed


# ============================================================
# 41. HEALTH SERVER
# ============================================================

async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "service": "TOKENS",
        "uptime": int(time.time() - started_at),
    })


async def start_web_server():
    app = web.Application()

    app.router.add_get(
        "/",
        health_handler,
    )

    app.router.add_get(
        "/health",
        health_handler,
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()

    logger.info(
        "HTTP server listening on port %s",
        PORT,
    )

    return runner


# ============================================================
# 42. START COMMAND
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    user = await ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )

    if user["is_banned"]:
        await message.answer(
            tr(user["language"], "banned")
        )
        return

    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        await process_referral(
            message.from_user.id,
            args[1].strip(),
        )

    user = await get_user(message.from_user.id)

    if user["is_verified"]:
        await message.answer(
            tr(user["language"], "menu_hint"),
            reply_markup=main_menu(
                user["language"]
            ),
        )
        return

    await start_captcha(
        message,
        user,
    )


# ============================================================
# 43. CAPTCHA TEXT HANDLER
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"^\d{3,4}$"),
)
async def captcha_text_handler(message: Message):
    user = await get_user(message.from_user.id)

    if not user or user["is_verified"]:
        return

    await complete_captcha(
        message,
        user,
    )


# ============================================================
# 44. MAIN MENU: HOW TO PLAY
# ============================================================

@dp.message(F.text.in_([
    "🎮 Как играть?",
    "🎮 How to play?",
]))
async def menu_games(message: Message):
    lang = await user_language(
        message.from_user.id
    )

    text = (
        tr(lang, "games_title")
        + "\n\n"
        + tr(lang, "game_help")
    )

    sent = await message.answer(
        text,
        reply_markup=games_keyboard(),
        parse_mode="Markdown",
    )

    schedule_delete(sent, PRIVATE_TTL)


# ============================================================
# 45. MAIN MENU: BONUS
# ============================================================

@dp.message(F.text.in_([
    "🎁 Бонус",
    "🎁 Bonus",
]))
async def menu_bonus(message: Message):
    user_id = message.from_user.id
    lang = await user_language(user_id)

    if not await is_subscribed(user_id):
        image = create_group_card(
            "SUBSCRIBE TO TOKENS NEWS",
            [
                "SUBSCRIBE TO @tokens_news",
                "THEN CLAIM YOUR BONUS",
            ],
        )

        sent = await message.answer_photo(
            BufferedInputFile(
                image,
                filename="subscribe.png",
            ),
            caption=tr(lang, "subscribe"),
        )

        schedule_delete(sent)
        return

    success, amount, remaining = await claim_bonus(
        user_id
    )

    if not success:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await send_temp(
            message,
            tr(
                lang,
                "bonus_wait",
                hours=hours,
                minutes=minutes,
            ),
        )
        return

    await send_temp(
        message,
        tr(
            lang,
            "bonus_success",
            amount=amount,
        ),
    )


# ============================================================
# 46. MAIN MENU: DONATE
# ============================================================

@dp.message(F.text.in_([
    "💎 Донат",
    "💎 Donate",
]))
async def menu_donate(message: Message):
    await show_donation(message)


# ============================================================
# 47. MAIN MENU: PROFILE
# ============================================================

@dp.message(F.text.in_([
    "👤 Профиль",
    "👤 Profile",
]))
async def menu_profile(message: Message):
    await show_profile(message)


# ============================================================
# 48. MAIN MENU: TOP
# ============================================================

@dp.message(F.text.in_([
    "🏆 Топ",
    "🏆 Top",
]))
async def menu_top(message: Message):
    lang = await user_language(
        message.from_user.id
    )

    await message.answer(
        tr(lang, "top_title"),
        reply_markup=top_keyboard(),
    )


# ============================================================
# 49. MAIN MENU: REFERRAL
# ============================================================

@dp.message(F.text.in_([
    "🔗 Рефералка",
    "🔗 Referral",
]))
async def menu_referral(message: Message):
    await show_referral(message)


# ============================================================
# 50. SUPPORT MENU
# ============================================================

@dp.callback_query(F.data == "support_open")
async def support_open(callback: CallbackQuery):
    lang = await user_language(
        callback.from_user.id
    )

    await callback.message.answer(
        tr(lang, "support"),
        reply_markup=support_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("support_"))
async def support_callback(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_", 1)[1]

    lang = await user_language(
        callback.from_user.id
    )

    if action == "earn":
        await callback.message.answer(
            "Играй, получай бонусы и приглашай друзей."
        )

    elif action == "error":
        await state.set_state(
            BotStates.support_message
        )

        await callback.message.answer(
            tr(lang, "support_prompt")
        )

    elif action == "admin":
        if SUPPORT_USERNAME:
            await callback.message.answer(
                f"https://t.me/{SUPPORT_USERNAME}"
            )
        else:
            await callback.message.answer(
                "Напиши администратору через раздел поддержки."
            )

    await callback.answer()


@dp.message(BotStates.support_message)
async def support_message_handler(message: Message, state: FSMContext):
    await send_support_to_admin(message)

    lang = await user_language(
        message.from_user.id
    )

    await message.answer(
        tr(lang, "support_sent")
    )

    await state.clear()


# ============================================================
# 51. GAME KEYBOARD CALLBACKS
# ============================================================

@dp.callback_query(F.data.startswith("game_"))
async def game_callback(callback: CallbackQuery):
    game = callback.data.replace("game_", "")

    await callback.message.answer(
        f"Для игры напиши ставку:\n"
        f"`{GAMES[game]['ru'].lower()} 1000`",
        parse_mode="Markdown",
    )

    await callback.answer()


# ============================================================
# 52. GAME TEXT HANDLER
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
)
async def game_text_handler(message: Message):
    text = message.text.strip()

    if text.startswith("/"):
        return

    user_id = message.from_user.id

    user = await get_user(user_id)

    if not user:
        return

    if user["is_banned"]:
        await message.answer(
            tr(user["language"], "banned")
        )
        return

    if not user["is_verified"]:
        return

    parts = text.lower().split()

    if len(parts) != 2:
        return

    game = GAME_ALIASES.get(parts[0])

    if not game:
        return

    try:
        bet = int(parts[1])
    except ValueError:
        await send_temp(
            message,
            tr(user["language"], "invalid_bet"),
            GAME_TTL,
        )
        return

    await play_game(
        message,
        game,
        bet,
    )


# ============================================================
# 53. DUEL COMMAND
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^дуэль\s+@?\w+\s+\d+$"),
)
async def duel_command(message: Message):
    parts = message.text.split()

    target_name = parts[1].lstrip("@")
    bet = int(parts[2])

    if bet < MIN_BET or bet > MAX_BET:
        return

    target = await find_user_by_username(
        target_name
    )

    if not target:
        await message.answer(
            "Игрок не найден. Он должен сначала запустить бота."
        )
        return

    duel_id = await create_duel(
        message.from_user.id,
        target["user_id"],
        bet,
    )

    if not duel_id:
        await message.answer(
            "Не удалось создать дуэль. Проверь баланс."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ Принять",
                    callback_data=f"duel_accept_{duel_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отказаться",
                    callback_data=f"duel_decline_{duel_id}",
                ),
            ]
        ]
    )

    await bot.send_message(
        target["user_id"],
        (
            f"⚔️ Дуэль от @{message.from_user.username or message.from_user.id}\n"
            f"Ставка: {bet} TOKENS"
        ),
        reply_markup=keyboard,
    )

    await message.answer(
        "Вызов отправлен!"
    )


# ============================================================
# 54. DUEL CALLBACKS
# ============================================================

@dp.callback_query(F.data.startswith("duel_"))
async def duel_callback(callback: CallbackQuery):
    parts = callback.data.split("_")

    action = parts[1]
    duel_id = int(parts[2])

    duel = pending_duels.get(duel_id)

    if not duel:
        await callback.answer(
            "Дуэль уже завершена.",
            show_alert=True,
        )
        return

    if callback.from_user.id != duel["opponent"]:
        await callback.answer(
            "Это не твоя дуэль.",
            show_alert=True,
        )
        return

    if action == "decline":
        await finish_duel(
            duel_id,
            False,
        )

        await callback.message.edit_text(
            "Дуэль отклонена."
        )

        await callback.answer()
        return

    if action == "accept":
        result = await finish_duel(
            duel_id,
            True,
        )

        if result == "insufficient":
            await callback.message.edit_text(
                "У игрока недостаточно средств."
            )
            await callback.answer()
            return

        await callback.message.edit_text(
            f"🏆 Победитель: {result}\n"
            f"Приз: {duel['bet'] * 2} TOKENS"
        )

        await callback.answer()


# ============================================================
# 55. TRANSFER COMMAND
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^перевод\s+@?\w+\s+\d+$"),
)
async def transfer_command(message: Message):
    parts = message.text.split()

    target_name = parts[1].lstrip("@")
    amount = int(parts[2])

    target = await find_user_by_username(
        target_name
    )

    if not target:
        await message.answer(
            "Пользователь не найден."
        )
        return

    success, reason = await transfer_tokens(
        message.from_user.id,
        target["user_id"],
        amount,
    )

    if success:
        await message.answer(
            f"Переведено {amount} TOKENS."
        )
    else:
        errors = {
            "self": "Нельзя переводить самому себе.",
            "amount": "Некорректная сумма.",
            "missing": "Пользователь не найден.",
            "blocked": "Получатель запретил переводы.",
            "balance": "Недостаточно TOKENS.",
        }

        await message.answer(
            errors.get(reason, "Ошибка перевода.")
        )


# ============================================================
# 56. PROFILE SETTINGS CALLBACK
# ============================================================

@dp.callback_query(F.data == "profile_settings")
async def profile_settings(callback: CallbackQuery):
    user = await get_user(
        callback.from_user.id
    )

    await callback.message.answer(
        "⚙️ НАСТРОЙКИ",
        reply_markup=settings_keyboard(
            user,
            user["language"],
        ),
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("lang_"))
async def language_callback(callback: CallbackQuery):
    lang = callback.data.replace("lang_", "")

    await set_language(
        callback.from_user.id,
        lang,
    )

    await callback.message.answer(
        tr(lang, "language_changed"),
        reply_markup=main_menu(lang),
    )

    await callback.answer()


@dp.callback_query(F.data == "toggle_transfers")
async def toggle_transfers(callback: CallbackQuery):
    user = await get_user(
        callback.from_user.id
    )

    new_value = 0 if user["transfer_blocked"] else 1

    async with db_lock:
        await db().execute(
            "UPDATE users SET transfer_blocked=? WHERE user_id=?",
            (new_value, callback.from_user.id),
        )
        await db().commit()

    await callback.message.answer(
        "Настройка переводов обновлена."
    )

    await callback.answer()


@dp.callback_query(F.data == "profile_back")
async def profile_back(callback: CallbackQuery):
    await show_profile(
        callback.message,
        callback.from_user.id,
    )
    await callback.answer()


# ============================================================
# 57. VIP CALLBACK
# ============================================================

@dp.callback_query(F.data == "vip_open")
async def vip_open(callback: CallbackQuery):
    await show_vip(
        callback.message
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("vip_"))
async def vip_purchase(callback: CallbackQuery):
    days = int(
        callback.data.split("_")[1]
    )

    stars = VIP_DAYS.get(days)

    if not stars:
        await callback.answer(
            "Некорректный пакет.",
            show_alert=True,
        )
        return

    await send_stars_invoice(
        callback.from_user.id,
        stars,
        payment_type="vip",
        days=days,
    )

    await callback.answer()


# ============================================================
# 58. DONATION CALLBACK
# ============================================================

@dp.callback_query(F.data.startswith("donate_"))
async def donation_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    value = callback.data.replace(
        "donate_",
        "",
    )

    if value == "custom":
        await state.set_state(
            BotStates.custom_stars
        )

        lang = await user_language(
            callback.from_user.id
        )

        await callback.message.answer(
            tr(lang, "custom_prompt")
        )

        await callback.answer()
        return

    stars = int(value)

    if stars not in DONATION_REWARDS:
        await callback.answer(
            "Неизвестный пакет.",
            show_alert=True,
        )
        return

    await send_stars_invoice(
        callback.from_user.id,
        stars,
    )

    await callback.answer()


# ============================================================
# 59. CUSTOM STARS FSM
# ============================================================

@dp.message(BotStates.custom_stars)
async def custom_stars_handler(
    message: Message,
    state: FSMContext,
):
    try:
        stars = int(message.text.strip())
    except (ValueError, AttributeError):
        stars = 0

    if not 1 <= stars <= 10000:
        lang = await user_language(
            message.from_user.id
        )

        await message.answer(
            tr(lang, "custom_invalid")
        )
        return

    await state.clear()

    await send_stars_invoice(
        message.from_user.id,
        stars,
    )


# ============================================================
# 60. PRE-CHECKOUT
# ============================================================

@dp.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery,
):
    await query.answer(
        ok=True,
    )


# ============================================================
# 61. SUCCESSFUL PAYMENT
# ============================================================

@dp.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
):
    await process_successful_payment(
        message
    )


# ============================================================
# 62. TOP CALLBACK
# ============================================================

@dp.callback_query(F.data.startswith("top_"))
async def top_callback(callback: CallbackQuery):
    category = callback.data.replace(
        "top_",
        "",
    )

    if category not in (
        "balance",
        "donate",
        "referrals",
    ):
        await callback.answer()
        return

    text = await render_top(
        category,
    )

    await callback.message.answer(
        text,
    )

    await callback.answer()


# ============================================================
# 63. GROUP BALANCE GRAPHIC
# ============================================================

@dp.message(
    F.chat.type.in_([
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ]),
    F.text.lower() == "б",
)
async def group_balance(message: Message):
    if not message.from_user:
        return

    user = await get_user(
        message.from_user.id
    )

    if not user:
        return

    image = create_group_card(
        "PLAYER BALANCE",
        [
            user["full_name"],
            f'{user["balance"]:,} TOKENS',
        ],
    )

    await send_group_photo(
        message,
        image,
    )


# ============================================================
# 64. GROUP HISTORY GRAPHIC
# ============================================================

@dp.message(
    F.chat.type.in_([
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ]),
    F.text.lower() == "лог",
)
async def group_history(message: Message):
    rows = await get_history(
        message.from_user.id,
        8,
    )

    lines = []

    for row in rows:
        sign = "+" if row["amount"] >= 0 else ""

        lines.append(
            f'{sign}{row["amount"]} | {row["reason"][:25]}'
        )

    if not lines:
        lines = ["История операций пуста."]

    image = create_group_card(
        "TRANSACTION HISTORY",
        lines,
    )

    await send_group_photo(
        message,
        image,
    )


# ============================================================
# 65. GROUP TOP TEXT
# ============================================================

@dp.message(
    F.chat.type.in_([
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ]),
    F.text.lower() == "топ",
)
async def group_top(message: Message):
    text = await render_top(
        "balance"
    )

    sent = await message.answer(
        text,
    )

    schedule_delete(
        sent,
        GROUP_TTL,
    )


# ============================================================
# 66. GROUP BOT STATUS
# ============================================================

@dp.message(
    F.chat.type.in_([
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ]),
    F.text.lower() == "бот",
)
async def group_bot(message: Message):
    sent = await message.answer(
        "На месте!"
    )

    schedule_delete(
        sent,
        GROUP_TTL,
    )


# ============================================================
# 67. GROUP UPDATES
# ============================================================

@dp.message(
    F.chat.type.in_([
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ]),
    F.text.lower() == "что нового",
)
async def group_updates(message: Message):
    image = create_group_card(
        "ОБНОВЛЕНИЯ",
        [
            "🎮 Игровой клуб TOKENS",
            "🎁 Ежедневные бонусы",
            "⭐ VIP подписка",
            "🏆 Рейтинг игроков",
            "🔗 Реферальная система",
        ],
    )

    await send_group_photo(
        message,
        image,
    )


# ============================================================
# 68. ADMIN COMMAND ROUTER
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.startswith("@"),
)
async def admin_router(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip()
    parts = text.split()

    command = parts[0].lower()

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if command == "@помощь":
        await message.answer(
            tr("ru", "admin_help")
        )
        return

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    if command == "@стата":
        stats = await get_admin_stats()

        await message.answer(
            "📊 СТАТИСТИКА\n\n"
            f"Пользователей: {stats['users']}\n"
            f"Проверено: {stats['verified']}\n"
            f"Бан: {stats['banned']}\n"
            f"TOKENS: {stats['tokens']}\n"
            f"Игр: {stats['games']}"
        )
        return

    # --------------------------------------------------------
    # GIVE
    # --------------------------------------------------------

    if command == "@выдать":
        if len(parts) < 3:
            await message.answer(
                "@выдать USER_ID СУММА"
            )
            return

        target = parts[1]

        try:
            amount = int(parts[2])
        except ValueError:
            await message.answer(
                "Некорректная сумма."
            )
            return

        user = (
            await find_user_by_username(target)
            if target.startswith("@")
            else await get_user(int(target))
        )

        if not user:
            await message.answer(
                "Пользователь не найден."
            )
            return

        success = await change_balance(
            user["user_id"],
            amount,
            "Admin grant",
        )

        await message.answer(
            "Готово." if success else "Ошибка."
        )
        return

    # --------------------------------------------------------
    # DROP
    # --------------------------------------------------------

    if command == "@дроп":
        if len(parts) != 2:
            await message.answer(
                "@дроп СУММА"
            )
            return

        try:
            amount = int(parts[1])
        except ValueError:
            return

        if amount <= 0:
            return

        count = await admin_drop(amount)

        await message.answer(
            f"🎁 Дроп выполнен!\n"
            f"Получателей: {count}\n"
            f"Сумма: {amount} TOKENS"
        )
        return

    # --------------------------------------------------------
    # BAN
    # --------------------------------------------------------

    if command == "@бан":
        if len(parts) < 2:
            await message.answer(
                "@бан USER_ID"
            )
            return

        target = parts[1]

        user = (
            await find_user_by_username(target)
            if target.startswith("@")
            else await get_user(int(target))
        )

        if not user:
            await message.answer(
                "Пользователь не найден."
            )
            return

        async with db_lock:
            await db().execute(
                "UPDATE users SET is_banned=1 WHERE user_id=?",
                (user["user_id"],),
            )
            await db().commit()

        await message.answer(
            "🚫 Пользователь заблокирован."
        )
        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    if command == "@скан":
        if len(parts) < 2:
            await message.answer(
                "@скан USER_ID/@username"
            )
            return

        target = parts[1]

        user = (
            await find_user_by_username(target)
            if target.startswith("@")
            else await get_user(int(target))
        )

        if not user:
            await message.answer(
                "Пользователь не найден."
            )
            return

        await send_admin_scan(
            message,
            user,
        )
        return

    # --------------------------------------------------------
    # BACKUP
    # --------------------------------------------------------

    if command == "@бекап":
        path = await create_backup()

        await message.answer_document(
            document=__import__(
                "aiogram.types",
                fromlist=["FSInputFile"]
            ).FSInputFile(path),
            caption="Резервная копия TOKENS.",
        )
        return

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    if command == "@рассылка":
        await state.set_state(
            BotStates.admin_broadcast
        )

        await message.answer(
            "Отправь текст рассылки."
        )
        return

    logger.info(
        "Unknown admin command: %s",
        command,
    )


# ============================================================
# 69. ADMIN BROADCAST STATE
# ============================================================

@dp.message(BotStates.admin_broadcast)
async def admin_broadcast_handler(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text or ""

    if not text.strip():
        await message.answer(
            "Пустая рассылка."
        )
        return

    await state.clear()

    status = await message.answer(
        "Рассылка запущена..."
    )

    sent, failed = await broadcast_message(
        text
    )

    await status.edit_text(
        f"Рассылка завершена.\n"
        f"Успешно: {sent}\n"
        f"Ошибок: {failed}"
    )


# ============================================================
# 70. GENERIC PRIVATE USER GUARD
# ============================================================

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
)
async def private_guard(message: Message):
    if not message.from_user:
        return

    user = await get_user(
        message.from_user.id
    )

    if not user:
        return

    if user["is_banned"]:
        sent = await message.answer(
            tr(user["language"], "banned")
        )
        schedule_delete(sent)
        return

    if not user["is_verified"]:
        return


# ============================================================
# 71. ERROR HANDLER
# ============================================================

@dp.errors()
async def global_error_handler(event):
    logger.exception(
        "Unhandled update error",
        exc_info=event.exception,
    )
    return True


# ============================================================
# 72. BOT STARTUP
# ============================================================

async def main():
    global bot, dp

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML",
        ),
    )

    # Важно: регистрируем маршрутизаторы из этой реализации.
    # Декораторы выше должны быть объявлены после создания dp.
    #
    # Для корректного порядка создания Dispatcher используется
    # отдельный экземпляр при запуске ниже через регистрацию
    # функций-обработчиков.

    await start_web_server()

    try:
        await bot.delete_webhook(
            drop_pending_updates=True
        )

        logger.info(
            "TOKENS bot is starting..."
        )

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:
        await close_db()

        if bot:
            await bot.session.close()


# ============================================================
# 73. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
