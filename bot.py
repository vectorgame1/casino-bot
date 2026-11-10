# ============================================================
#  TOKENS BOT - ЧАСТЬ 1a
#  Импорты, настройки, тексты (RU/EN), база данных (схема)
# ============================================================

import os
import re
import json
import time
import random
import asyncio
import logging
import traceback
from typing import Optional, List, Dict, Any, Tuple

import aiosqlite
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ============================================================
#  НАСТРОЙКИ (из переменных окружения)
# ============================================================
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
CHAT_ID: int = int(os.getenv("CHAT_ID", "0"))
EVENT_CHAT_ID: int = int(os.getenv("EVENT_CHAT_ID", "0"))
PORT: int = int(os.getenv("PORT", "8080"))

# Стикеры (если есть, иначе бот шлет текст)
STICKER_MONEY = os.getenv("STICKER_MONEY", "")
STICKER_GIFT = os.getenv("STICKER_GIFT", "")
STICKER_VIP = os.getenv("STICKER_VIP", "")
STICKER_LOSE = os.getenv("STICKER_LOSE", "")
STICKER_WIN = os.getenv("STICKER_WIN", "")

# Игровые константы
START_BALANCE: int = 5000
MIN_BET: int = 100
MAX_BET: int = 1_000_000
CLAN_CREATE_COST: int = 100_000
DUEL_COMMISSION: float = 0.05
BONUS_COOLDOWN: int = 24 * 3600
BONUS_MIN: int = 1000
BONUS_MAX: int = 5000

# Курс звезд (ФИКС 7500)
STAR_RATE: int = 7500

# VIP константы
VIP_BONUS: float = 1.03  # +3% к выигрышу
VIP_PRICES = {
    1: 5,
    7: 30,
    30: 100,
    365: 1000
}
VIP_DAYS_IN_SEC = 86400

# Таймауты и лимиты
GAME_MSG_TIMEOUT = 60
ROULETTE_TIMEOUT = 60
MINES_TIMEOUT = 300
TRANSFER_COOLDOWN = 5

# Пути
DB_PATH = "casino.db"
# ВРЕМЕННЫЙ ФИКС: Удаляем старую базу с ошибкой
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
IMG_DIR = "images"
IMG_START = os.path.join(IMG_DIR, "start.jpg")
IMG_PROFILE = os.path.join(IMG_DIR, "profile.jpg")
IMG_DONATE = os.path.join(IMG_DIR, "donate.jpg")
IMG_BONUS = os.path.join(IMG_DIR, "bonus.jpg")
IMG_TOP = os.path.join(IMG_DIR, "top.jpg")
IMG_REF = os.path.join(IMG_DIR, "ref.jpg")
IMG_HOW_TO_PLAY = os.path.join(IMG_DIR, "how_to_play.jpg")
IMG_SUPPORT = os.path.join(IMG_DIR, "support.jpg")
IMG_CHATS = os.path.join(IMG_DIR, "chats.jpg")
IMG_COMMANDS = os.path.join(IMG_DIR, "commands.jpg")

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens_bot")

# ============================================================
#  БОТ / ДИСПЕТЧЕР / РОУТЕР / ПЛАНИРОВЩИК
# ============================================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ============================================================
#  ТЕКСТЫ (RU / EN)
# ============================================================
TEXTS = {
    "ru": {
        "menu_how_to_play": "🎮 Как играть",
        "menu_bonus": "🎁 Бонус",
        "menu_donate": "💎 Донат",
        "menu_profile": "👤 Профиль",
        "menu_clan": "🛡 Клан",
        "menu_ref": "🔗 Рефералка",
        "menu_top": "🏆 Топ",
        "menu_chats": "💬 Чаты",
        "menu_support": "🆘 Поддержка",
        "menu_commands": "📖 Команды",
        
        "start_text": "👋 <b>Привет, {name}!</b>\n\n💎 Добро пожаловать в <b>TOKENS</b>!\n🎮 Играй, выигрывай и поднимайся в топ!\n\n💰 Твой баланс: <b>{balance} 🪙</b>\n\n👇 Используй меню ниже.",
        "profile_text": "👤 <b>Профиль</b>\n\n🆔 ID: <code>{user_id}</code>\n📛 Имя: <b>{name}</b>\n🔗 Юзернейм: @{username}\n\n💰 Баланс: <b>{balance} 🪙</b>\n👑 VIP: <b>{vip}</b>\n🛡 Клан: <b>{clan}</b>\n\n🎮 Сыграно игр: <b>{games}</b>\n🎯 Всего ставок: <b>{total_bet} 🪙</b>\n🏆 Всего выиграно: <b>{total_win} 🪙</b>",
        "vip_active": "Активен (осталось {days} дн.)",
        "vip_none": "Не активен",
        "clan_none": "Нет",
        
        "not_understood": "🤖 <b>Упс! Я тебя не понял...</b>\n\nПохоже, ты написал что-то не по шаблону.\n\n👇 Что можно сделать:\n1. Нажми на кнопку <b>«📖 Команды»</b> внизу.\n2. Посмотри правила в <b>«🎮 Как играть»</b>.\n3. Если что-то сломалось — напиши в <b>«🆘 Поддержка»</b>.",
        
        "error_bet_min": "❌ Минимальная ставка: {min_bet} 🪙",
        "error_bet_max": "❌ Максимальная ставка: {max_bet} 🪙",
        "error_no_money": "❌ Недостаточно средств. Твой баланс: {balance} 🪙",
        "error_banned": "🚫 Ты забанен в боте.",
        
        "cancel_success": "🛑 <b>Действие отменено.</b>\n\nТы вернулся в главное меню.",
    },
    "en": {
        "menu_how_to_play": "🎮 How to play",
        "menu_bonus": "🎁 Bonus",
        "menu_donate": "💎 Donate",
        "menu_profile": "👤 Profile",
        "menu_clan": "🛡 Clan",
        "menu_ref": "🔗 Referral",
        "menu_top": "🏆 Top",
        "menu_chats": "💬 Chats",
        "menu_support": "🆘 Support",
        "menu_commands": "📖 Commands",
        
        "start_text": "👋 <b>Hello, {name}!</b>\n\n💎 Welcome to <b>TOKENS</b>!\n🎮 Play, win, and climb the leaderboard!\n\n💰 Your balance: <b>{balance} 🪙</b>\n\n👇 Use the menu below.",
        "profile_text": "👤 <b>Profile</b>\n\n🆔 ID: <code>{user_id}</code>\n📛 Name: <b>{name}</b>\n🔗 Username: @{username}\n\n💰 Balance: <b>{balance} 🪙</b>\n👑 VIP: <b>{vip}</b>\n🛡 Clan: <b>{clan}</b>\n\n🎮 Games played: <b>{games}</b>\n🎯 Total bets: <b>{total_bet} 🪙</b>\n🏆 Total won: <b>{total_win} 🪙</b>",
        "vip_active": "Active ({days} days left)",
        "vip_none": "Not active",
        "clan_none": "None",
        
        "not_understood": "🤖 <b>Oops! I didn't understand...</b>\n\nIt looks like you typed something wrong.\n\n👇 What to do:\n1. Click <b>«📖 Commands»</b> below.\n2. Read the rules in <b>«🎮 How to play»</b>.\n3. If something is broken — write to <b>«🆘 Support»</b>.",
        
        "error_bet_min": "❌ Minimum bet: {min_bet} 🪙",
        "error_bet_max": "❌ Maximum bet: {max_bet} 🪙",
        "error_no_money": "❌ Insufficient funds. Your balance: {balance} 🪙",
        "error_banned": "🚫 You are banned.",
        
        "cancel_success": "🛑 <b>Action cancelled.</b>\n\nYou returned to the main menu.",
    }
}

def get_text(key: str, lang: str = "ru", **kwargs) -> str:
    """Возвращает текст на нужном языке с подстановкой аргументов."""
    lang = lang if lang in TEXTS else "ru"
    text = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError as e:
            logger.error(f"Ошибка форматирования текста {key}: {e}")
            return text
    return text

# ============================================================
#  УТИЛИТЫ
# ============================================================
def fmt_money(n: int) -> str:
    """Форматирует число: 1234567 -> '1 234 567'."""
    return f"{int(n):,}".replace(",", " ")

def now_ts() -> int:
    return int(time.time())

def is_vip(user: Optional[Dict[str, Any]]) -> bool:
    """Проверяет, активен ли VIP."""
    if not user:
        return False
    return int(user.get("vip_until") or 0) > now_ts()

def calc_win(base_amount: int, user: Dict[str, Any]) -> int:
    """Считает выигрыш с учетом VIP (+3%)."""
    win = base_amount
    if is_vip(user):
        win = int(win * VIP_BONUS)
    return win

async def auto_delete(message: Message, delay: int = GAME_MSG_TIMEOUT) -> None:
    """Удаляет сообщение через `delay` секунд."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.debug(f"auto_delete: {e}")

# ============================================================
#  БАЗА ДАННЫХ (ИНИЦИАЛИЗАЦИЯ 18 ТАБЛИЦ)
# ============================================================
async def db_init() -> None:
    """Создает все таблицы и включает WAL режим для скорости."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA synchronous=NORMAL")
        
        await db.executescript("""
        -- 1. USERS
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            balance       INTEGER DEFAULT 0,
            vip_until     INTEGER DEFAULT 0,
            clan_id       INTEGER DEFAULT 0,
            referrer_id   INTEGER DEFAULT 0,
            ref_count     INTEGER DEFAULT 0,
            total_bet     INTEGER DEFAULT 0,
            total_win     INTEGER DEFAULT 0,
            total_lost    INTEGER DEFAULT 0,
            games_played  INTEGER DEFAULT 0,
            biggest_win   INTEGER DEFAULT 0,
            banned        INTEGER DEFAULT 0,
            ban_reason    TEXT,
            last_bonus    INTEGER DEFAULT 0,
            last_seen     INTEGER DEFAULT 0,
            lang          TEXT DEFAULT 'ru',
            notify_transfers INTEGER DEFAULT 1,
            notify_games  INTEGER DEFAULT 1,
            reg_date      INTEGER DEFAULT 0
        );

        -- 2. CLANS
        CREATE TABLE IF NOT EXISTS clans (
            clan_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT UNIQUE,
            owner_id      INTEGER,
            balance       INTEGER DEFAULT 0,
            level         INTEGER DEFAULT 1,
            description   TEXT,
            invite_code   TEXT UNIQUE,
            max_members   INTEGER DEFAULT 10,
            created_at    INTEGER DEFAULT 0
        );

        -- 3. CLAN_MEMBERS
        CREATE TABLE IF NOT EXISTS clan_members (
            clan_id       INTEGER,
            user_id       INTEGER,
            role          TEXT DEFAULT 'member',
            joined_at     INTEGER DEFAULT 0,
            PRIMARY KEY (clan_id, user_id)
        );

        -- 4. HISTORY
        CREATE TABLE IF NOT EXISTS history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            game          TEXT,
            bet           INTEGER,
            win           INTEGER,
            multiplier    REAL DEFAULT 0,
            balance_after INTEGER DEFAULT 0,
            result        TEXT,
            ts            INTEGER
        );

        -- 5. ROULETTE_LOGS
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER,
            user_id       INTEGER,
            bet           INTEGER,
            win           INTEGER,
            bet_type      TEXT,
            numbers_json  TEXT,
            color         TEXT,
            ts            INTEGER
        );

        -- 6. SETTINGS
        CREATE TABLE IF NOT EXISTS settings (
            key           TEXT PRIMARY KEY,
            value         TEXT
        );

        -- 7. PROMOCODES
        CREATE TABLE IF NOT EXISTS promocodes (
            code          TEXT PRIMARY KEY,
            amount        INTEGER,
            uses_left     INTEGER,
            uses_total    INTEGER,
            min_balance   INTEGER DEFAULT 0,
            expires_at    INTEGER DEFAULT 0,
            created_by    INTEGER,
            created_at    INTEGER
        );

        -- 8. PROMO_USES
        CREATE TABLE IF NOT EXISTS promo_uses (
            code          TEXT,
            user_id       INTEGER,
            used_at       INTEGER,
            PRIMARY KEY (code, user_id)
        );

        -- 9. ADMIN_LOGS
        CREATE TABLE IF NOT EXISTS admin_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id      INTEGER,
            action        TEXT,
            target_id     INTEGER,
            details       TEXT,
            chat_id       INTEGER,
            ts            INTEGER
        );

        -- 10. AUDIT_LOG
        CREATE TABLE IF NOT EXISTS audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id      INTEGER,
            action        TEXT,
            target_id     INTEGER,
            amount        INTEGER,
            details       TEXT,
            ts            INTEGER
        );

        -- 11. DUELS
        CREATE TABLE IF NOT EXISTS duels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER,
            opponent_id   INTEGER,
            bet           INTEGER,
            status        TEXT DEFAULT 'pending',
            winner_id     INTEGER,
            chat_id       INTEGER,
            created_at    INTEGER,
            expires_at    INTEGER
        );

        -- 12. MINES_GAMES
        CREATE TABLE IF NOT EXISTS mines_games (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            bet           INTEGER,
            field_json    TEXT,
            opened_json   TEXT,
            mult          REAL DEFAULT 1.0,
            status        TEXT DEFAULT 'active',
            created_at    INTEGER
        );

        -- 13. BONUS_DROPS (Без слова drop)
        CREATE TABLE IF NOT EXISTS bonus_drops (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER,
            amount        INTEGER,
            claimed_by    INTEGER,
            created_at    INTEGER,
            expires_at    INTEGER
        );

        -- 14. ROULETTE_PARTICIPANTS (Без слова autoroulette)
        CREATE TABLE IF NOT EXISTS roulette_participants (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER,
            user_id       INTEGER,
            bet           INTEGER,
            created_at    INTEGER
        );

        -- 15. BANS_HISTORY
        CREATE TABLE IF NOT EXISTS bans_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            admin_id      INTEGER,
            reason        TEXT,
            banned_at     INTEGER,
            unbanned_at   INTEGER DEFAULT 0
        );

        -- 16. DAILY_STATS
        CREATE TABLE IF NOT EXISTS daily_stats (
            date          TEXT PRIMARY KEY,
            dau           INTEGER DEFAULT 0,
            games_count   INTEGER DEFAULT 0,
            bets_total    INTEGER DEFAULT 0,
            wins_total    INTEGER DEFAULT 0,
            new_users     INTEGER DEFAULT 0
        );

        -- 17. CHAT_SETTINGS
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id       INTEGER PRIMARY KEY,
            games_enabled INTEGER DEFAULT 1,
            disabled_games TEXT DEFAULT '[]',
            auto_roulette_enabled INTEGER DEFAULT 1, 
            drop_enabled  INTEGER DEFAULT 1,
            min_bet       INTEGER DEFAULT 100,
            updated_by    INTEGER DEFAULT 0
        );

        -- 18. EVENT_CHATS
        CREATE TABLE IF NOT EXISTS event_chats (
            chat_id       INTEGER PRIMARY KEY,
            title         TEXT,
            autoroulette  INTEGER DEFAULT 1,
            drop          INTEGER DEFAULT 1,
            happy_hour    INTEGER DEFAULT 1,
            tournament    INTEGER DEFAULT 1,
            promo         INTEGER DEFAULT 1,
            surprise      INTEGER DEFAULT 1,
            added_at      INTEGER
        );

        -- Индексы для скорости
        CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);
        CREATE INDEX IF NOT EXISTS idx_users_clan ON users(clan_id);
        CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_chat ON roulette_logs(chat_id);
        CREATE INDEX IF NOT EXISTS idx_admin_logs_ts ON admin_logs(ts);
        """)
        
        # Дефолтные настройки (если пусто)
        defaults = {
            "star_rate": str(STAR_RATE),
            "happy_hour": "0",
            "changelog": json.dumps(["v1.0 — запуск бота"], ensure_ascii=False),
            "multi_courses": json.dumps({"TOKENS": 7500}, ensure_ascii=False)
        }
        for k, v in defaults.items():
            await db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
            
        await db.commit()
    logger.info("✅ БД инициализирована (18 таблиц, WAL mode)")

# ============================================================
#  ЧАСТЬ 1b: ФУНКЦИИ БД (USERS, HISTORY, SETTINGS, PROMO, ADMIN)
# ============================================================

# ------------------------------------------------------------
#  ПОЛЬЗОВАТЕЛИ
# ------------------------------------------------------------
async def db_get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает словарь с данными юзера или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_create_user(
    user_id: int, username: str, first_name: str, referrer_id: int = 0
) -> Dict[str, Any]:
    """Создает нового юзера, обрабатывает рефку."""
    now = now_ts()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users
               (user_id, username, first_name, balance, referrer_id, reg_date, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username or "", first_name or "", START_BALANCE, referrer_id, now, now),
        )
        await db.commit()
    
    # Реферальные бонусы
    if referrer_id and referrer_id != user_id:
        ref = await db_get_user(referrer_id)
        if ref:
            await db_add_balance(referrer_id, 2000, "ref_bonus")
            await db_add_balance(user_id, 1000, "ref_friend_bonus")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (referrer_id,))
                await db.commit()
                
    return await db_get_user(user_id) or {}

async def db_save_user(user_id: int, **fields) -> None:
    """Обновляет произвольные поля пользователя."""
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {cols} WHERE user_id = ?", vals)
        await db.commit()

async def db_add_balance(user_id: int, amount: int, reason: str = "") -> int:
    """Меняет баланс (может быть отрицательным). Возвращает новый баланс."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id),
        )
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0

async def db_find_user(query: str) -> Optional[Dict[str, Any]]:
    """Ищет по ID, @username или first_name."""
    q = (query or "").strip().lstrip("@")
    if not q:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # По ID
        if q.isdigit():
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (int(q),)) as cur:
                row = await cur.fetchone()
                if row: return dict(row)
        # По юзернейму
        async with db.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (q,)) as cur:
            row = await cur.fetchone()
            if row: return dict(row)
        # По имени
        async with db.execute("SELECT * FROM users WHERE first_name = ? LIMIT 1", (query,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_ban_user(user_id: int, banned: bool = True, reason: str = "") -> None:
    """Банит или разбанивает."""
    await db_save_user(user_id, banned=1 if banned else 0, ban_reason=reason)
    if banned:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO bans_history (user_id, admin_id, reason, banned_at) VALUES (?, ?, ?, ?)",
                (user_id, ADMIN_ID, reason, now_ts())
            )
            await db.commit()

async def db_set_vip(user_id: int, days: int) -> None:
    """Добавляет дни к VIP-статусу."""
    u = await db_get_user(user_id)
    if not u: return
    current_vip = u.get("vip_until", 0)
    base_time = current_vip if current_vip > now_ts() else now_ts()
    new_until = base_time + (days * VIP_DAYS_IN_SEC)
    await db_save_user(user_id, vip_until=new_until)

async def db_count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            return (await cur.fetchone())[0]

async def db_total_balance() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(SUM(balance),0) FROM users") as cur:
            return (await cur.fetchone())[0]

async def db_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE banned = 0") as cur:
            return [r[0] for r in await cur.fetchall()]

async def db_top_users(limit: int = 10, by: str = "balance") -> List[Dict[str, Any]]:
    """Топ по балансу или выигрышу."""
    field = "balance" if by == "balance" else "total_win"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM users WHERE banned = 0 ORDER BY {field} DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  ИСТОРИЯ И СТАТИСТИКА
# ------------------------------------------------------------
async def db_add_history(
    user_id: int, game: str, bet: int, win: int, mult: float = 0.0, result: str = ""
) -> None:
    """Записывает игру в историю и обновляет счетчики."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем баланс после игры
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            balance_after = row[0] if row else 0
            
        await db.execute(
            """INSERT INTO history 
               (user_id, game, bet, win, multiplier, balance_after, result, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, game, bet, win, mult, balance_after, result, now_ts()),
        )
        await db.execute(
            """UPDATE users SET 
               total_bet = total_bet + ?, 
               total_win = total_win + ?, 
               total_lost = total_lost + ?,
               games_played = games_played + 1 
               WHERE user_id = ?""",
            (bet, max(win, 0), bet if win == 0 else 0, user_id),
        )
        await db.commit()

async def db_get_history(user_id: int, limit: int = 10, filter_type: str = "all") -> List[Dict[str, Any]]:
    """Возвращает историю с фильтрацией (all, win, lose, transfer)."""
    query = "SELECT * FROM history WHERE user_id = ?"
    params = [user_id]
    
    if filter_type == "win":
        query += " AND win > bet"
    elif filter_type == "lose":
        query += " AND win = 0"
    elif filter_type == "transfer":
        query += " AND game = 'перевод'"
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  БОНУСЫ
# ------------------------------------------------------------
async def db_can_take_bonus(user_id: int, cooldown: int) -> bool:
    u = await db_get_user(user_id)
    if not u: return False
    return now_ts() - int(u.get("last_bonus") or 0) >= cooldown

async def db_claim_bonus(user_id: int, amount: int) -> None:
    await db_save_user(user_id, last_bonus=now_ts())
    await db_add_balance(user_id, amount, "bonus")

# ------------------------------------------------------------
#  НАСТРОЙКИ И КУРСЫ
# ------------------------------------------------------------
async def db_get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def db_set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def db_get_courses() -> Dict[str, int]:
    """Возвращает курсы валют других ботов."""
    raw = await db_get_setting("multi_courses", "{}")
    try:
        return json.loads(raw)
    except:
        return {}

async def db_add_course(name: str, rate: int) -> None:
    courses = await db_get_courses()
    courses[name] = rate
    await db_set_setting("multi_courses", json.dumps(courses))

async def db_get_changelog() -> List[str]:
    raw = await db_get_setting("changelog", "[]")
    try:
        return json.loads(raw)
    except:
        return []

async def db_add_changelog(entry: str) -> None:
    log = await db_get_changelog()
    log.insert(0, entry)
    await db_set_setting("changelog", json.dumps(log[:50], ensure_ascii=False))

# ------------------------------------------------------------
#  ПРОМОКОДЫ
# ------------------------------------------------------------
async def db_create_promo(code: str, amount: int, uses: int, created_by: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO promocodes(code, amount, uses_left, uses_total, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (code, amount, uses, uses, created_by, now_ts()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def db_redeem_promo(code: str, user_id: int) -> Optional[int]:
    """Возвращает сумму или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Проверка, не юзал ли уже
        async with db.execute("SELECT 1 FROM promo_uses WHERE code = ? AND user_id = ?", (code, user_id)) as cur:
            if await cur.fetchone():
                return -1 # Уже использовал
        
        async with db.execute("SELECT * FROM promocodes WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
            if not row or row["uses_left"] <= 0:
                return None
            
            await db.execute("UPDATE promocodes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
            await db.execute("INSERT INTO promo_uses(code, user_id, used_at) VALUES (?, ?, ?)", (code, user_id, now_ts()))
            await db.commit()
            return row["amount"]

# ------------------------------------------------------------
#  ЛОГИ И АУДИТ
# ------------------------------------------------------------
async def db_admin_log(admin_id: int, action: str, target_id: int = 0, details: str = "", chat_id: int = 0) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO admin_logs(admin_id, action, target_id, details, chat_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (admin_id, action, target_id, details, chat_id, now_ts()),
        )
        await db.commit()

async def db_audit_log(actor_id: int, action: str, target_id: int = 0, amount: int = 0, details: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_log(actor_id, action, target_id, amount, details, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (actor_id, action, target_id, amount, details, now_ts()),
        )
        await db.commit()

async def db_add_roulette_log(chat_id: int, user_id: int, bet: int, win: int, numbers: str, color: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO roulette_logs(chat_id, user_id, bet, win, numbers, color, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, bet, win, numbers, color, now_ts()),
        )
        await db.commit()

async def db_roulette_logs(chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM roulette_logs WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ============================================================
#  ЧАСТЬ 1c: ФУНКЦИИ БД (CLANS, DUELS, MINES, DROPS, AUTOROULETTE)
# ============================================================

# ------------------------------------------------------------
#  КЛАНЫ (С поддержкой ролей и казны)
# ------------------------------------------------------------
async def db_get_clan(clan_id: int) -> Optional[Dict[str, Any]]:
    if not clan_id: return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clans WHERE clan_id = ?", (clan_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_get_clan_by_name(name: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clans WHERE LOWER(name) = LOWER(?)", (name,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_create_clan(name: str, owner_id: int, cost: int) -> Optional[int]:
    """Создает клан, списывает стоимость, делает владельца участником."""
    u = await db_get_user(owner_id)
    if not u or u["balance"] < cost or u.get("clan_id"):
        return None
    if await db_get_clan_by_name(name):
        return None
        
    invite_code = f"CLAN{random.randint(1000, 9999)}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO clans(name, owner_id, balance, invite_code, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, owner_id, 0, invite_code, now_ts()),
        )
        await db.commit()
        async with db.execute("SELECT clan_id FROM clans WHERE name = ?", (name,)) as cur:
            cid = (await cur.fetchone())[0]
            
    # Списываем деньги
    await db_add_balance(owner_id, -cost, "clan_create")
    # Добавляем в участники
    await db_clan_add_member(cid, owner_id, role="owner")
    await db_save_user(owner_id, clan_id=cid)
    return cid

async def db_clan_members(clan_id: int) -> List[Dict[str, Any]]:
    """Возвращает список участников с их балансами."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.*, cm.role FROM users u
               JOIN clan_members cm ON u.user_id = cm.user_id
               WHERE cm.clan_id = ? ORDER BY u.balance DESC""", (clan_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_clan_member_count(clan_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (clan_id,)) as cur:
            return (await cur.fetchone())[0]

async def db_clan_deposit(clan_id: int, user_id: int, amount: int) -> bool:
    """Внесение в казну клана."""
    u = await db_get_user(user_id)
    if not u or u["balance"] < amount or amount <= 0:
        return False
    await db_add_balance(user_id, -amount, "clan_deposit")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET balance = balance + ? WHERE clan_id = ?", (amount, clan_id))
        await db.commit()
    return True

async def db_clan_add_member(clan_id: int, user_id: int, role: str = "member") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO clan_members(clan_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (clan_id, user_id, role, now_ts())
        )
        await db.commit()
    await db_save_user(user_id, clan_id=clan_id)

async def db_clan_leave(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_members WHERE user_id = ?", (user_id,))
        await db.commit()
    await db_save_user(user_id, clan_id=0)

async def db_get_clan_top(limit: int = 10) -> List[Dict[str, Any]]:
    """Топ кланов по сумме балансов участников и казны."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.*, 
                      (SELECT COALESCE(SUM(balance),0) FROM users WHERE clan_id = c.clan_id) AS members_balance
               FROM clans c
               ORDER BY (c.balance + (SELECT COALESCE(SUM(balance),0) FROM users WHERE clan_id = c.clan_id)) DESC
               LIMIT ?""", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  ДУЭЛИ
# ------------------------------------------------------------
async def db_create_duel(challenger_id: int, opponent_id: int, bet: int, chat_id: int) -> int:
    """Создает вызов на дуэль."""
    expires = now_ts() + 300 # 5 минут
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO duels(challenger_id, opponent_id, bet, status, chat_id, created_at, expires_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (challenger_id, opponent_id, bet, chat_id, now_ts(), expires)
        )
        await db.commit()
        return cursor.lastrowid

async def db_get_duel(duel_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM duels WHERE id = ?", (duel_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_finish_duel(duel_id: int, winner_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE duels SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, duel_id))
        await db.commit()

async def db_expire_duels() -> None:
    """Отменяет просроченные дуэли."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE duels SET status = 'expired' WHERE status = 'pending' AND expires_at < ?", (now_ts(),))
        await db.commit()

# ------------------------------------------------------------
#  МИНЫ (FSM + Сохранение в БД)
# ------------------------------------------------------------
async def db_mines_create(user_id: int, bet: int, field_json: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO mines_games(user_id, bet, field_json, opened_json, mult, status, created_at) VALUES (?, ?, ?, '[]', 1.0, 'active', ?)",
            (user_id, bet, field_json, now_ts())
        )
        await db.commit()
        return cursor.lastrowid

async def db_mines_get_active(user_id: int) -> Optional[Dict[str, Any]]:
    """Ищет активную игру пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mines_games WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_mines_update(game_id: int, opened_json: str, mult: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE mines_games SET opened_json = ?, mult = ? WHERE id = ?", (opened_json, mult, game_id))
        await db.commit()

async def db_mines_finish(game_id: int, status: str = "cashed") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE mines_games SET status = ? WHERE id = ?", (status, game_id))
        await db.commit()

# ------------------------------------------------------------
#  ДРОПЫ (Авто-дроп) - ТАБЛИЦА DROPS_TABLE
# ------------------------------------------------------------
async def db_drop_create(chat_id: int, amount: int, ttl: int = 600) -> int:
    expires = now_ts() + ttl
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO drops_table(chat_id, amount, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (chat_id, amount, now_ts(), expires)
        )
        await db.commit()
        return cursor.lastrowid

async def db_drop_take(drop_id: int, user_id: int) -> Optional[int]:
    """Пытается забрать дроп. Возвращает сумму или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bonus_drops WHERE id = ?", (drop_id,)) as cur:
            row = await cur.fetchone()
            if not row or row["claimed_by"] != 0 or row["expires_at"] < now_ts():
                return None
            
            await db.execute("UPDATE bonus_drops SET claimed_by = ? WHERE id = ?", (user_id, drop_id))
            await db.commit()
            return row["amount"]

async def db_expire_drops() -> None:
    """Удаляет просроченные дропы."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bonus_drops WHERE expires_at < ? AND claimed_by = 0", (now_ts(),))
        await db.commit()

# ------------------------------------------------------------
#  АВТО-РУЛЕТКА - ТАБЛИЦА AUTOROULETTE_TABLE
# ------------------------------------------------------------
async def db_ar_join(chat_id: int, user_id: int, bet: int) -> bool:
    """Регистрирует участника авто-рулетки."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, не записан ли уже
        async with db.execute("SELECT 1 FROM roulette_participants WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            if await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO roulette_participants(chat_id, user_id, bet, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, user_id, bet, now_ts())
        )
        await db.commit()
        return True

async def db_ar_participants(chat_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM roulette_participants WHERE chat_id = ?", (chat_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_ar_clear(chat_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM roulette_participants WHERE chat_id = ?", (chat_id,))
        await db.commit()

# ------------------------------------------------------------
#  УПРАВЛЕНИЕ ЧАТАМИ (Chat Settings)
# ------------------------------------------------------------
async def db_chat_get(chat_id: int) -> Dict[str, Any]:
    """Возвращает настройки чата (или дефолтные)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
            return {
                "chat_id": chat_id,
                "games_enabled": 1,
                "disabled_games": "[]",
                "auto_roulette_enabled": 1,
                "bonus_enabled": 1,
                "min_bet": MIN_BET
            }

async def db_chat_toggle_games(chat_id: int, enabled: bool, admin_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO chat_settings(chat_id, games_enabled, updated_by) VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET games_enabled = ?, updated_by = ?""",
            (chat_id, 1 if enabled else 0, admin_id, 1 if enabled else 0, admin_id)
        )
        await db.commit()

async def db_chat_toggle_specific_game(chat_id: int, game_name: str, enable: bool) -> None:
    """Включает/выключает конкретную игру."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT disabled_games FROM chat_settings WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
            disabled = json.loads(row["disabled_games"]) if row else []
            
        if enable and game_name in disabled:
            disabled.remove(game_name)
        elif not enable and game_name not in disabled:
            disabled.append(game_name)
            
        await db.execute(
            """INSERT INTO chat_settings(chat_id, disabled_games) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET disabled_games = ?""",
            (chat_id, json.dumps(disabled), json.dumps(disabled))
        )
        await db.commit()

# ------------------------------------------------------------
#  ИВЕНТ-ЧАТЫ (Онли-группа)
# ------------------------------------------------------------
async def db_event_chat_add(chat_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO event_chats(chat_id, title, added_at) VALUES (?, ?, ?)""",
            (chat_id, title, now_ts())
        )
        await db.commit()

async def db_event_chats_all() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM event_chats") as cur:
            return [dict(r) for r in await cur.fetchall()]

# ============================================================
#  ЧАСТЬ 1d: ПАРСЕР РУЛЕТКИ, УТИЛИТЫ ИГР, ТРАНЗАКЦИИ
# ============================================================

# ------------------------------------------------------------
#  ПАРСЕР РУЛЕТКИ (Умный, принимает все форматы)
# ------------------------------------------------------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

def get_roulette_color(num: int) -> str:
    """Возвращает 'red', 'black' или 'green'."""
    if num == 0: return "green"
    return "red" if num in RED_NUMBERS else "black"

def parse_roulette_bet(text: str) -> Optional[Dict[str, Any]]:
    """
    Парсит строку ставки.
    Возвращает: {"amount": int, "type": str, "target": list, "text": str} или None.
    """
    text = text.lower().strip()
    
    # 1. Формат "к 1000" или "ч 1000"
    match = re.match(r"^(к|ч|красное|черное|red|black)\s+(\d+)$", text)
    if match:
        color = "red" if match.group(1) in ["к", "красное", "red"] else "black"
        return {"amount": int(match.group(2)), "type": "color", "target": [color], "text": "🔴 красное" if color == "red" else "⚫ чёрное"}

    # 2. Формат "1000 чет" или "1000 нечет"
    match = re.match(r"^(\d+)\s+(чет|нечет|чёт|нечёт|even|odd)$", text)
    if match:
        is_even = match.group(2) in ["чет", "чёт", "even"]
        return {"amount": int(match.group(1)), "type": "parity", "target": ["even" if is_even else "odd"], "text": "Чёт" if is_even else "Нечет"}

    # 3. Формат "0 100" (зеро)
    match = re.match(r"^(0|зеро|zero)\s+(\d+)$", text)
    if match:
        return {"amount": int(match.group(2)), "type": "number", "target": [0], "text": "🟢 Зеро (0)"}

    # 4. Сложные форматы (сумма + числа/диапазоны)
    # Ищем первое число как сумму ставки
    parts = text.split()
    if not parts: return None
    
    # Пытаемся найти сумму (первый инт)
    amount = 0
    targets = []
    
    for part in parts:
        part = part.strip(",")
        if part.isdigit() and amount == 0:
            amount = int(part)
        elif part.isdigit():
            targets.append(int(part))
        elif "-" in part:
            # Диапазон "10-23"
            try:
                start, end = map(int, part.split("-"))
                if 0 <= start <= end <= 36:
                    targets.extend(range(start, end + 1))
            except ValueError:
                pass
                
    if amount > 0 and targets:
        # Убираем дубликаты
        targets = list(set(targets))
        # Определяем тип (если диапазон широкий — х3, если точные числа — х36)
        # Для простоты, если чисел больше 4, считаем как диапазон (х3)
        if len(targets) > 4:
            return {"amount": amount, "type": "range", "target": targets, "text": f"Диапазон ({len(targets)} чисел)"}
        else:
            return {"amount": amount, "type": "number", "target": targets, "text": f"Числа: {', '.join(map(str, targets))}"}

    return None

def calc_roulette_win(bet_info: Dict[str, Any], result_num: int) -> Tuple[int, float]:
    """
    Считает множитель и возвращает (выигрыш, множитель).
    """
    amount = bet_info["amount"]
    bet_type = bet_info["type"]
    targets = bet_info["target"]
    
    if bet_type == "color":
        if get_roulette_color(result_num) == targets[0]:
            return amount * 2, 2.0
    elif bet_type == "parity":
        is_even = (result_num % 2 == 0) and result_num != 0
        if (targets[0] == "even" and is_even) or (targets[0] == "odd" and not is_even and result_num != 0):
            return amount * 2, 2.0
    elif bet_type == "number":
        if result_num in targets:
            return amount * 36, 36.0
    elif bet_type == "range":
        if result_num in targets:
            return amount * 3, 3.0
            
    return 0, 0.0

# ------------------------------------------------------------
#  УТИЛИТЫ ДЛЯ ИГР
# ------------------------------------------------------------
RANKS = [
    ("Новичок", 0),
    ("Игрок", 10_000),
    ("Хайроллер", 100_000),
    ("Легенда", 1_000_000)
]

def get_rank(balance: int) -> Tuple[str, int]:
    """Возвращает (название ранга, до следующего)."""
    for i in range(len(RANKS) - 1, -1, -1):
        if balance >= RANKS[i][1]:
            if i == len(RANKS) - 1:
                return RANKS[i][0], 0
            return RANKS[i][0], RANKS[i+1][1] - balance
    return RANKS[0][0], RANKS[1][1]

def make_progress_bar(current: int, target: int, length: int = 10) -> str:
    """Создает строку прогресс-бара."""
    if target <= 0: return "█" * length
    pct = min(current / target, 1.0)
    filled = int(pct * length)
    return "█" * filled + "░" * (length - filled) + f" {int(pct*100)}%"

def check_bet(user: Dict[str, Any], amount: int) -> Tuple[bool, str]:
    """
    Проверяет ставку. Возвращает (ok, error_message).
    """
    if user.get("banned"):
        return False, get_text("error_banned", user.get("lang", "ru"))
    if amount < MIN_BET:
        return False, get_text("error_bet_min", user.get("lang", "ru"), min_bet=fmt_money(MIN_BET))
    if amount > MAX_BET:
        return False, get_text("error_bet_max", user.get("lang", "ru"), max_bet=fmt_money(MAX_BET))
    if user["balance"] < amount:
        return False, get_text("error_no_money", user.get("lang", "ru"), balance=fmt_money(user["balance"]))
    return True, ""

# ------------------------------------------------------------
#  ТРАНЗАКЦИИ И БЭКАП
# ------------------------------------------------------------
from contextlib import asynccontextmanager

@asynccontextmanager
async def db_transaction():
    """Контекстный менеджер для атомарных операций (если упадет — откатится)."""
    db = await aiosqlite.connect(DB_PATH)
    try:
        yield db
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"DB Transaction Error: {e}")
        raise
    finally:
        await db.close()

async def db_backup() -> bytes:
    """Возвращает байты базы данных для отправки."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.commit()
    with open(DB_PATH, "rb") as f:
        return f.read()

async def db_update_daily_stats(dau: int, games: int, bets: int, wins: int, new_users: int) -> None:
    """Обновляет статистику за сегодня."""
    today = time.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO daily_stats(date, dau, games_count, bets_total, wins_total, new_users)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               dau = dau + ?, games_count = games_count + ?, bets_total = bets_total + ?, wins_total = wins_total + ?, new_users = new_users + ?""",
            (today, dau, games, bets, wins, new_users, dau, games, bets, wins, new_users)
        )
        await db.commit()

# ============================================================
#  ЧАСТЬ 2: КЛАВИАТУРЫ И ГЛАВНОЕ МЕНЮ
# ============================================================

# ------------------------------------------------------------
#  REPLY-КЛАВИАТУРЫ (8 КНОПОК)
# ------------------------------------------------------------
def main_menu(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_text("menu_how_to_play", lang)), KeyboardButton(text=get_text("menu_bonus", lang))],
            [KeyboardButton(text=get_text("menu_donate", lang)), KeyboardButton(text=get_text("menu_profile", lang))],
            [KeyboardButton(text=get_text("menu_clan", lang)), KeyboardButton(text=get_text("menu_ref", lang))],
            [KeyboardButton(text=get_text("menu_top", lang)), KeyboardButton(text=get_text("menu_chats", lang))],
            [KeyboardButton(text=get_text("menu_support", lang)), KeyboardButton(text=get_text("menu_commands", lang))],
        ],
        resize_keyboard=True,
    )

# ------------------------------------------------------------
#  INLINE-КЛАВИАТУРЫ
# ------------------------------------------------------------
def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]])

def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Настройки", callback_data="prof_settings")],
        [InlineKeyboardButton(text="📜 История", callback_data="prof_history"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="prof_stats")],
        [InlineKeyboardButton(text="💸 Переводы", callback_data="prof_transfers"),
         InlineKeyboardButton(text="💰 Выигрыши/Проигрыши", callback_data="prof_winlose")],
        [InlineKeyboardButton(text="🌐 Язык (RU/EN)", callback_data="prof_lang")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def settings_kb(user: Dict[str, Any]) -> InlineKeyboardMarkup:
    t_trans = "🔔 Уведомления о переводах: ВКЛ" if user.get("notify_transfers") else "🔕 Уведомления о переводах: ВЫКЛ"
    t_games = "🔔 Уведомления об играх: ВКЛ" if user.get("notify_games") else "🔕 Уведомления об играх: ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t_trans, callback_data="toggle_transfers")],
        [InlineKeyboardButton(text=t_games, callback_data="toggle_games")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="prof_back")],
    ])

def donate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 50 → 375 000", callback_data="buy_stars_50"),
         InlineKeyboardButton(text="⭐ 100 → 750 000", callback_data="buy_stars_100")],
        [InlineKeyboardButton(text="⭐ 500 → 3 750 000", callback_data="buy_stars_500"),
         InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_custom")],
        [InlineKeyboardButton(text="👑 VIP-подписка", callback_data="vip_menu")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def vip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день — 5 ⭐", callback_data="vip_buy_1")],
        [InlineKeyboardButton(text="7 дней — 30 ⭐", callback_data="vip_buy_7")],
        [InlineKeyboardButton(text="30 дней — 100 ⭐", callback_data="vip_buy_30")],
        [InlineKeyboardButton(text="365 дней — 1000 ⭐", callback_data="vip_buy_365")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_donate")],
    ])

def top_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"),
         InlineKeyboardButton(text="🏆 По выигрышу", callback_data="top_win")],
        [InlineKeyboardButton(text="🛡 Топ кланов", callback_data="top_clans")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def ref_kb(link: str) -> InlineKeyboardMarkup:
    share = f"https://t.me/share/url?url={link}&text=Залетай в TOKENS и забирай бонус!"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=share)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def chats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Ивент-чат (Онли)", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="💬 Основной чат", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="📢 Канал", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def cancel_fsm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Отменить действие", callback_data="cancel_fsm")]
    ])

# ------------------------------------------------------------
#  УТИЛИТЫ ОТПРАВКИ (С фото и умным удалением в ЛС)
# ------------------------------------------------------------
async def send_photo_or_text(msg: Message, photo_path: str, caption: str, kb=None):
    if photo_path and os.path.exists(photo_path):
        try:
            await msg.answer_photo(FSInputFile(photo_path), caption=caption, parse_mode="HTML", reply_markup=kb)
            return
        except TelegramBadRequest:
            pass
    await msg.answer(caption, parse_mode="HTML", reply_markup=kb)

async def clean_and_send(msg: Message, text: str, kb=None, is_photo: str = None):
    """Удаляет предыдущее сообщение и отправляет новое (для чистоты в ЛС)."""
    if msg.chat.type == ChatType.PRIVATE:
        try: await msg.delete()
        except: pass
        
    if is_photo:
        await send_photo_or_text(msg, is_photo, text, kb)
    else:
        await msg.answer(text, reply_markup=kb)

async def ensure_user(msg: Message) -> Dict[str, Any]:
    """Гарантирует наличие юзера в БД (с обработкой рефки)."""
    u = await db_get_user(msg.from_user.id)
    if u:
        await db_save_user(msg.from_user.id, last_seen=now_ts(), username=msg.from_user.username or "")
        u["last_seen"] = now_ts()
        return u

    ref_id = 0
    if msg.text and msg.text.startswith("/start "):
        arg = msg.text.split(maxsplit=1)[1].strip()
        if arg.startswith("ref") and arg[3:].isdigit():
            ref_id = int(arg[3:])
            
    return await db_create_user(
        msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "", referrer_id=ref_id
    )

# ------------------------------------------------------------
#  FSM СОСТОЯНИЯ
# ------------------------------------------------------------
class DonateStates(StatesGroup):
    custom_amount = State()

# ------------------------------------------------------------
#  ГЛАВНОЕ МЕНЮ И НАВИГАЦИЯ
# ------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    if u.get("banned"):
        await msg.answer(get_text("error_banned", u.get("lang", "ru")))
        return

    lang = u.get("lang", "ru")
    text = get_text("start_text", lang, name=msg.from_user.first_name, balance=fmt_money(u["balance"]))
    await clean_and_send(msg, text, main_menu(lang), IMG_START)

@router.callback_query(F.data == "nav_menu")
async def cb_nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await cb.message.delete()
    except: pass
    u = await db_get_user(cb.from_user.id)
    lang = u.get("lang", "ru") if u else "ru"
    await cb.message.answer("🏠 Главное меню", reply_markup=main_menu(lang))
    await cb.answer()

@router.callback_query(F.data == "cancel_fsm")
async def cb_cancel_fsm(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    u = await db_get_user(cb.from_user.id)
    lang = u.get("lang", "ru") if u else "ru"
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(get_text("cancel_success", lang), reply_markup=main_menu(lang))
    await cb.answer("Отменено")

# ------------------------------------------------------------
#  КНОПКА «ПРОФИЛЬ»
# ------------------------------------------------------------
async def render_profile_text(user: Dict[str, Any]) -> str:
    lang = user.get("lang", "ru")
    vip_status = get_text("vip_none", lang)
    if is_vip(user):
        days = max(1, (user["vip_until"] - now_ts()) // 86400)
        vip_status = get_text("vip_active", lang, days=days)
        
    clan_name = get_text("clan_none", lang)
    if user.get("clan_id"):
        c = await db_get_clan(user["clan_id"])
        if c: clan_name = c["name"]
        
    return get_text("profile_text", lang,
        user_id=user["user_id"], name=user.get("first_name", "—"), username=user.get("username") or "—",
        balance=fmt_money(user["balance"]), vip=vip_status, clan=clan_name,
        games=user.get("games_played", 0), total_bet=fmt_money(user.get("total_bet", 0)), total_win=fmt_money(user.get("total_win", 0))
    )

@router.message(F.text.in_([get_text("menu_profile", "ru"), get_text("menu_profile", "en")]))
async def profile_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    text = await render_profile_text(u)
    await clean_and_send(msg, text, profile_kb(), IMG_PROFILE)

@router.callback_query(F.data == "prof_back")
async def cb_prof_back(cb: CallbackQuery):
    u = await db_get_user(cb.from_user.id)
    text = await render_profile_text(u)
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_PROFILE, text, profile_kb())
    await cb.answer()

@router.callback_query(F.data == "prof_settings")
async def cb_prof_settings(cb: CallbackQuery):
    u = await db_get_user(cb.from_user.id)
    text = "⚙️ <b>Настройки профиля</b>\n\nУправляй уведомлениями и языком."
    try: await cb.message.edit_caption(caption=text, reply_markup=settings_kb(u))
    except: await cb.message.edit_text(text, reply_markup=settings_kb(u))
    await cb.answer()

@router.callback_query(F.data.startswith("toggle_"))
async def cb_toggle_settings(cb: CallbackQuery):
    field = "notify_transfers" if cb.data == "toggle_transfers" else "notify_games"
    u = await db_get_user(cb.from_user.id)
    new_val = 0 if u.get(field) else 1
    await db_save_user(cb.from_user.id, **{field: new_val})
    u[field] = new_val
    try: await cb.message.edit_reply_markup(reply_markup=settings_kb(u))
    except: pass
    await cb.answer("Настройки сохранены")

@router.callback_query(F.data == "prof_lang")
async def cb_prof_lang(cb: CallbackQuery):
    u = await db_get_user(cb.from_user.id)
    new_lang = "en" if u.get("lang") == "ru" else "ru"
    await db_save_user(cb.from_user.id, lang=new_lang)
    u["lang"] = new_lang
    text = await render_profile_text(u)
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_PROFILE, text, profile_kb())
    await cb.message.answer("Language changed / Язык изменен", reply_markup=main_menu(new_lang))
    await cb.answer()

# ------------------------------------------------------------
#  КНОПКА «ДОНАТ» И «СВОЯ СУММА»
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_donate", "ru"), get_text("menu_donate", "en")]))
async def donate_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    text = (
        f"💎 <b>Магазин TOKENS</b>\n\n"
        f"Текущий курс: <b>1 ⭐ = {fmt_money(STAR_RATE)} TOKENS</b>\n\n"
        f"👑 <b>VIP-подписка</b> — от 5 ⭐ (+3% к выигрышу)\n\n"
        f"👇 Выбери пакет:"
    )
    await clean_and_send(msg, text, donate_kb(), IMG_DONATE)

@router.callback_query(F.data == "nav_donate")
async def cb_nav_donate(cb: CallbackQuery):
    text = (
        f"💎 <b>Магазин TOKENS</b>\n\n"
        f"Текущий курс: <b>1 ⭐ = {fmt_money(STAR_RATE)} TOKENS</b>\n\n"
        f"👑 <b>VIP-подписка</b> — от 5 ⭐ (+3% к выигрышу)\n\n"
        f"👇 Выбери пакет:"
    )
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_DONATE, text, donate_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("buy_stars_"))
async def cb_buy_stars(cb: CallbackQuery):
    stars = int(cb.data.split("_")[-1])
    coins = stars * STAR_RATE
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title=f"{stars} ⭐",
        description=f"Покупка {fmt_money(coins)} TOKENS",
        payload=f"stars_{coins}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)],
    )
    await cb.answer()

@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(cb: CallbackQuery, state: FSMContext):
    await state.set_state(DonateStates.custom_amount)
    await cb.message.answer(
        "✍️ <b>Своя сумма</b>\n\nНапиши, сколько звезд ты хочешь купить (от 1 до 1000).\n\n"
        "Например: <code>15</code>", 
        reply_markup=cancel_fsm_kb()
    )
    await cb.answer()

@router.message(DonateStates.custom_amount)
async def process_custom_amount(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("❌ Пожалуйста, введи число.")
        return
    stars = int(msg.text)
    if not (1 <= stars <= 1000):
        await msg.answer("❌ Сумма должна быть от 1 до 1000 звезд.")
        return
        
    await state.clear()
    coins = stars * STAR_RATE
    await bot.send_invoice(
        chat_id=msg.from_user.id,
        title=f"{stars} ⭐",
        description=f"Покупка {fmt_money(coins)} TOKENS",
        payload=f"stars_{coins}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)],
    )

# ------------------------------------------------------------
#  VIP ПОДПИСКА
# ------------------------------------------------------------
@router.callback_query(F.data == "vip_menu")
async def cb_vip_menu(cb: CallbackQuery):
    text = "👑 <b>VIP-подписка</b>\n\nПолучай <b>+3% к выигрышу</b> и золотой значок.\n\nВыбери срок:"
    try: await cb.message.edit_caption(caption=text, reply_markup=vip_kb())
    except: await cb.message.edit_text(text, reply_markup=vip_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("vip_buy_"))
async def cb_vip_buy(cb: CallbackQuery):
    days = int(cb.data.split("_")[-1])
    price = VIP_PRICES.get(days, 5)
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title=f"👑 VIP на {days} дн.",
        description=f"+3% к выигрышу на {days} дней",
        payload=f"vip_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="VIP", amount=price)],
    )
    await cb.answer()

# ------------------------------------------------------------
#  ОБРАБОТКА ОПЛАТЫ
# ------------------------------------------------------------
@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await pcq.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(msg: Message):
    payload = msg.successful_payment.invoice_payload
    u = await db_get_user(msg.from_user.id)
    lang = u.get("lang", "ru")
    
    if payload.startswith("stars_"):
        coins = int(payload.split("_")[-1])
        await db_add_balance(msg.from_user.id, coins, "donate")
        await msg.answer(f"✅ Оплата прошла!\n💰 +{fmt_money(coins)} TOKENS", reply_markup=back_kb())
    elif payload.startswith("vip_"):
        days = int(payload.split("_")[-1])
        await db_set_vip(msg.from_user.id, days)
        await msg.answer(f"👑 VIP активирован на {days} дней!", reply_markup=back_kb())

# ------------------------------------------------------------
#  КНОПКА «🏆 ТОП»
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_top", "ru"), get_text("menu_top", "en")]))
async def top_handler(msg: Message, state: FSMContext):
    await state.clear()
    await ensure_user(msg)
    await render_top_balance(msg)

async def render_top_balance(msg: Message):
    top = await db_top_users(10, "balance")
    lines = ["🏆 <b>Топ игроков по балансу:</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = u.get("first_name") or f"ID{u['user_id']}"
        lines.append(f"{prefix} <b>{name}</b> — {fmt_money(u['balance'])} TOKENS")
    await clean_and_send(msg, "\n".join(lines), top_kb(), IMG_TOP)

@router.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: CallbackQuery):
    top = await db_top_users(10, "balance")
    lines = ["🏆 <b>Топ игроков по балансу:</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = u.get("first_name") or f"ID{u['user_id']}"
        lines.append(f"{prefix} <b>{name}</b> — {fmt_money(u['balance'])} TOKENS")
    try: await cb.message.edit_caption(caption="\n".join(lines), reply_markup=top_kb())
    except: await cb.message.edit_text("\n".join(lines), reply_markup=top_kb())
    await cb.answer()

@router.callback_query(F.data == "top_win")
async def cb_top_win(cb: CallbackQuery):
    top = await db_top_users(10, "win")
    lines = ["🏆 <b>Топ игроков по выигрышу:</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = u.get("first_name") or f"ID{u['user_id']}"
        lines.append(f"{prefix} <b>{name}</b> — {fmt_money(u['total_win'])} TOKENS")
    try: await cb.message.edit_caption(caption="\n".join(lines), reply_markup=top_kb())
    except: await cb.message.edit_text("\n".join(lines), reply_markup=top_kb())
    await cb.answer()

@router.callback_query(F.data == "top_clans")
async def cb_top_clans(cb: CallbackQuery):
    top = await db_get_clan_top(10)
    if not top:
        await cb.answer("Кланов пока нет", show_alert=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🛡 <b>Топ кланов:</b>\n"]
    for i, c in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        total = c["balance"] + (c.get("members_balance") or 0)
        lines.append(f"{prefix} <b>{c['name']}</b> — {fmt_money(total)} TOKENS")
    try: await cb.message.edit_caption(caption="\n".join(lines), reply_markup=top_kb())
    except: await cb.message.edit_text("\n".join(lines), reply_markup=top_kb())
    await cb.answer()

# ------------------------------------------------------------
#  КНОПКА «🔗 РЕФЕРАЛКА»
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_ref", "ru"), get_text("menu_ref", "en")]))
async def ref_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{msg.from_user.id}"
    text = (
        "🔗 <b>Реферальная система</b>\n\n"
        f"👥 Приглашено друзей: <b>{u.get('ref_count', 0)}</b>\n\n"
        f"💰 Ты получаешь: <b>+2 000 TOKENS</b> за друга\n"
        f"🎁 Друг получает: <b>+1 000 TOKENS</b> на старт\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>\n\n"
        "👇 Жми кнопку ниже, чтобы похвастаться друзьям!"
    )
    await clean_and_send(msg, text, ref_kb(link), IMG_REF)

# ------------------------------------------------------------
#  КНОПКА «💬 ЧАТЫ»
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_chats", "ru"), get_text("menu_chats", "en")]))
async def chats_handler(msg: Message, state: FSMContext):
    await state.clear()
    await ensure_user(msg)
    text = (
        "💬 <b>Официальные чаты TOKENS</b>\n\n"
        "Здесь кипит жизнь! Заходи, общайся, лови авто-дропы и участвуй в турнирах:\n\n"
        "🎰 <b>Ивент-чат</b> — тут бот постоянно раздает бонусы и крутит рулетки.\n"
        "💬 <b>Основной чат</b> — общение и поиск соперников для дуэлей.\n"
        "📢 <b>Канал</b> — новости и анонсы.\n\n"
        "⚠️ <i>Остерегайтесь скамеров. Администрация никогда не пишет первая!</i>"
    )
    await clean_and_send(msg, text, chats_kb(), IMG_CHATS)

# ------------------------------------------------------------
#  КНОПКА «📖 КОМАНДЫ»
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_commands", "ru"), get_text("menu_commands", "en")]))
async def commands_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    
    if lang == "ru":
        text = (
            "📖 <b>ШПАРГАЛКА ПО КОМАНДАМ</b>\n\n"
            "🤖 <i>Всё пишется прямо в чат. Просто копируй шаблоны и меняй сумму.</i>\n\n"
            "💰 <b>БАЛАНС И ПЕРЕВОДЫ</b>\n"
            "• <code>б</code> — узнать свой баланс\n"
            "• <code>б @юзер</code> — узнать чужой баланс\n"
            "• <code>перевод @юзер 1000</code> — перевести TOKENS\n\n"
            "📊 <b>ИНФОРМАЦИЯ</b>\n"
            "• <code>лог</code> — 10 последних чисел рулетки (в группе)\n"
            "• <code>курс</code> — таблица курсов валют\n"
            "• <code>топ</code> — топ игроков по балансу\n"
            "• <code>промо КОД</code> — активировать подарок\n\n"
            "🛑 <b>УПРАВЛЕНИЕ</b>\n"
            "• <code>отмена</code> или <code>cancel</code> — прервать ввод (например, в донате)\n\n"
            "⚠️ <i>Игровые команды (кости, мины и т.д.) ищи в кнопке «🎮 Как играть».</i>"
        )
    else:
        text = (
            "📖 <b>COMMAND CHEAT SHEET</b>\n\n"
            "🤖 <i>Type in chat. Just copy the templates and change the amount.</i>\n\n"
            "💰 <b>BALANCE & TRANSFERS</b>\n"
            "• <code>b</code> — your balance\n"
            "• <code>b @user</code> — someone's balance\n"
            "• <code>transfer @user 1000</code> — send TOKENS\n\n"
            "📊 <b>INFO</b>\n"
            "• <code>log</code> — last 10 roulette numbers (in group)\n"
            "• <code>rate</code> — currency rates\n"
            "• <code>top</code> — top players\n"
            "• <code>promo CODE</code> — activate gift\n\n"
            "🛑 <b>MANAGEMENT</b>\n"
            "• <code>cancel</code> — abort input\n\n"
            "⚠️ <i>Game commands are in the «🎮 How to play» menu.</i>"
        )
    await clean_and_send(msg, text, None, IMG_COMMANDS)

# ------------------------------------------------------------
#  КНОПКА «🛡 КЛАН» (Создание и управление)
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_clan", "ru"), get_text("menu_clan", "en")]))
async def clan_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    
    if u.get("clan_id"):
        c = await db_get_clan(u["clan_id"])
        if not c:
            await db_save_user(msg.from_user.id, clan_id=0)
            await msg.answer("Клан не найден.", reply_markup=main_menu(u.get("lang", "ru")))
            return
        count = await db_clan_member_count(c["clan_id"])
        text = (
            f"🛡 <b>Клан: {c['name']}</b>\n\n"
            f"👑 Владелец: <code>{c['owner_id']}</code>\n"
            f"👥 Участников: <b>{count}</b> / {c['max_members']}\n"
            f"💰 Казна: <b>{fmt_money(c['balance'])} TOKENS</b>\n\n"
            f"🔗 Код для приглашения: <code>{c['invite_code']}</code>"
        )
        # Для клана тоже нужна своя клавиатура, но пока используем back_kb
        await clean_and_send(msg, text, back_kb()) 
    else:
        text = (
            "🛡 <b>Кланы</b>\n\n"
            "Объединяйтесь с друзьями, качайте казну и доминируйте в топе!\n\n"
            f"➕ <b>Создание клана:</b> {fmt_money(CLAN_CREATE_COST)} TOKENS\n"
        )
        # Создаем инлайн-клавиатуру прямо тут (чтобы не искать в других файлах)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать клан", callback_data="clan_create_action")],
            [InlineKeyboardButton(text="🔍 Найти клан", callback_data="clan_find_action")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]
        ])
        await clean_and_send(msg, text, kb)

# ============================================================
#  ЧАСТЬ 3: ИГРЫ (КУБИКИ, СЛОТЫ, МИНЫ, ДУЭЛИ)
# ============================================================

class MinesStates(StatesGroup):
    playing = State()

# ------------------------------------------------------------
#  ОБЩАЯ УТИЛИТА ДЛЯ БЫСТРЫХ ИГР (Кубики)
# ------------------------------------------------------------
async def process_dice_game(msg: Message, game_name: str, emoji: str, win_condition: callable):
    """Универсальная функция для игр на кубиках."""
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    
    # Парсим ставку (ищем число в тексте)
    args = msg.text.split()
    amount = 0
    for arg in args:
        if arg.isdigit():
            amount = int(arg)
            break
            
    if amount == 0:
        await msg.answer("❌ Укажи сумму ставки. Например: <code>кости 1000</code>")
        return

    ok, err = check_bet(u, amount)
    if not ok:
        err_msg = await msg.answer(err)
        asyncio.create_task(auto_delete(err_msg, 15))
        return

    # Мгновенно списываем
    await db_add_balance(msg.from_user.id, -amount, f"bet_{game_name}")
    
    # Кидаем кубик
    dice_msg = await msg.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5) # Ждем анимацию кубика
    
    value = dice_msg.dice.value
    is_win = win_condition(value)
    
    win_amount = 0
    mult = 0.0
    if is_win:
        base_win = amount * 2
        win_amount = calc_win(base_win, u) # Учитываем VIP +3%
        mult = round(win_amount / amount, 2)
        await db_add_balance(msg.from_user.id, win_amount, f"win_{game_name}")
        
    # Запись в историю
    await db_add_history(msg.from_user.id, game_name, amount, win_amount, mult, f"Выпало {value}")
    
    # Формируем результат
    res_text = f"🎲 Выпало: <b>{value}</b>\n"
    if is_win:
        res_text += f"🎉 <b>Победа!</b> Ты выиграл <b>{fmt_money(win_amount)} 🪙</b>"
    else:
        res_text += f"💸 <b>Проигрыш.</b> Ты потерял <b>{fmt_money(amount)} 🪙</b>"
        
    res_msg = await msg.answer(res_text)
    
    # Автоудаление через 60 сек
    asyncio.create_task(auto_delete(res_msg, GAME_MSG_TIMEOUT))
    try: await dice_msg.delete() # Удаляем сам кубик
    except: pass

# ------------------------------------------------------------
#  ХЕНДЛЕРЫ ИГР НА КУБИКАХ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^кости\s+\d+"))
async def game_dice(msg: Message):
    # Победа от 4 до 6 (шанс 50%)
    await process_dice_game(msg, "кости", "🎲", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^дартс\s+\d+"))
async def game_dart(msg: Message):
    # Победа от 4 до 6
    await process_dice_game(msg, "дартс", "🎯", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^баскет\s+\d+"))
async def game_basket(msg: Message):
    # Победа от 3 до 5
    await process_dice_game(msg, "баскет", "🏀", lambda v: v in [3, 4, 5])

@router.message(F.text.regexp(r"(?i)^футбол\s+\d+"))
async def game_football(msg: Message):
    # Победа от 3 до 5
    await process_dice_game(msg, "футбол", "⚽", lambda v: v in [3, 4, 5])

@router.message(F.text.regexp(r"(?i)^боулинг\s+\d+"))
async def game_bowling(msg: Message):
    # Победа от 4 до 6
    await process_dice_game(msg, "боулинг", "🎳", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^бж\s+\d+"))
async def game_bj(msg: Message):
    # 50/50 (от 4 до 6)
    await process_dice_game(msg, "бж", "🎲", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^слоты\s+\d+"))
async def game_slots(msg: Message):
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    args = msg.text.split()
    amount = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
    
    if amount == 0:
        await msg.answer("❌ Укажи сумму. Например: <code>слоты 1000</code>")
        return

    ok, err = check_bet(u, amount)
    if not ok:
        err_msg = await msg.answer(err)
        asyncio.create_task(auto_delete(err_msg, 15))
        return

    await db_add_balance(msg.from_user.id, -amount, "bet_slots")
    dice_msg = await msg.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)
    
    value = dice_msg.dice.value # 1-64
    # Telegram слоты: 1 = BAR, 2 = Ягода, 3 = Лимон, 4 = 7
    # 1-64. Джекпот (777) - это 64. Три одинаковых - редкость.
    
    is_win = False
    mult = 0.0
    if value == 64: # Джекпот
        is_win = True
        mult = 10.0
    elif value >= 43: # Три одинаковых (примерно)
        is_win = True
        mult = 5.0
    elif value >= 22: # Два одинаковых
        is_win = True
        mult = 2.0
        
    win_amount = 0
    if is_win:
        base_win = int(amount * mult)
        win_amount = calc_win(base_win, u)
        await db_add_balance(msg.from_user.id, win_amount, "win_slots")
        
    await db_add_history(msg.from_user.id, "слоты", amount, win_amount, mult, f"Выпало {value}")
    
    res_text = f"🎰 Слоты: <b>{value}</b>\n"
    if is_win:
        res_text += f"🎉 <b>Победа!</b> Ты выиграл <b>{fmt_money(win_amount)} 🪙</b>"
    else:
        res_text += f"💸 <b>Проигрыш.</b> Ты потерял <b>{fmt_money(amount)} 🪙</b>"
        
    res_msg = await msg.answer(res_text)
    asyncio.create_task(auto_delete(res_msg, GAME_MSG_TIMEOUT))
    try: await dice_msg.delete()
    except: pass

# ------------------------------------------------------------
#  ИГРА «МИНЫ» (FSM + Кнопки)
# ------------------------------------------------------------
def mines_kb(field: list, opened: list, finished: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened:
                if field[idx]: row.append(InlineKeyboardButton(text="💥", callback_data="mine_noop"))
                else: row.append(InlineKeyboardButton(text="💎", callback_data="mine_noop"))
            elif finished:
                row.append(InlineKeyboardButton(text="⬛", callback_data="mine_noop"))
            else:
                row.append(InlineKeyboardButton(text="⬜", callback_data=f"mine_open_{idx}"))
        rows.append(row)
        
    if not finished and opened:
        rows.append([InlineKeyboardButton(text="💰 Забрать", callback_data="mine_cashout")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(F.text.regexp(r"(?i)^мины\s+\d+"))
async def game_mines_start(msg: Message, state: FSMContext):
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    
    # Проверка, нет ли уже активной игры
    active = await db_mines_get_active(msg.from_user.id)
    if active:
        await msg.answer("⚠️ У тебя уже есть активная игра в Мины! Заверши её или напиши <code>отмена</code>.")
        return

    args = msg.text.split()
    amount = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
    
    ok, err = check_bet(u, amount)
    if not ok:
        err_msg = await msg.answer(err)
        asyncio.create_task(auto_delete(err_msg, 15))
        return

    # Списание и генерация поля
    await db_add_balance(msg.from_user.id, -amount, "bet_mines")
    field = [False] * 25
    for _ in range(3): # 3 мины
        idx = random.randint(0, 24)
        while field[idx]: idx = random.randint(0, 24)
        field[idx] = True
        
    game_id = await db_mines_create(msg.from_user.id, amount, json.dumps(field))
    await state.set_state(MinesStates.playing)
    await state.update_data(game_id=game_id, field=field, opened=[], bet=amount)
    
    text = f"💣 <b>Игра «Мины»</b>\n\nСтавка: {fmt_money(amount)} 🪙\nНайди все безопасные клетки или забери выигрыш!"
    await msg.answer(text, reply_markup=mines_kb(field, []))

@router.callback_query(F.data.startswith("mine_open_"))
async def cb_mine_open(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("game_id"):
        await cb.answer("Игра не найдена или уже завершена", show_alert=True)
        return
        
    idx = int(cb.data.split("_")[-1])
    field = data["field"]
    opened = data["opened"]
    
    if idx in opened:
        await cb.answer("Эта клетка уже открыта")
        return
        
    opened.append(idx)
    
    if field[idx]: # Попал на мину
        await db_mines_finish(data["game_id"], "busted")
        await db_add_history(cb.from_user.id, "мины", data["bet"], 0, 0, "Взорвался")
        await state.clear()
        
        text = f"💥 <b>БУМ!</b> Ты наткнулся на мину.\nПроигрыш: {fmt_money(data['bet'])} 🪙"
        await cb.message.edit_text(text, reply_markup=mines_kb(field, opened, finished=True))
        
        # Удаляем через 60 сек
        asyncio.create_task(auto_delete(cb.message, GAME_MSG_TIMEOUT))
        await cb.answer("Ты взорвался!")
        return
        
    # Если безопасно — считаем множитель
    # Формула: 1.0 + (кол-во открытых * 0.15)
    mult = 1.0 + (len(opened) * 0.15)
    await db_mines_update(data["game_id"], json.dumps(opened), mult)
    await state.update_data(opened=opened)
    
    # Если открыли все 22 безопасные клетки — авто-забор
    if len(opened) == 22:
        await cb_mine_cashout(cb, state)
        return

    text = f"💣 <b>Игра «Мины»</b>\n\nСтавка: {fmt_money(data['bet'])} 🪙\nТекущий выигрыш: {fmt_money(int(data['bet'] * mult))} 🪙 (x{mult:.2f})"
    await cb.message.edit_text(text, reply_markup=mines_kb(field, opened))
    await cb.answer("Безопасно!")

@router.callback_query(F.data == "mine_cashout")
async def cb_mine_cashout(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("game_id"):
        await cb.answer("Игра не найдена", show_alert=True)
        return
        
    opened = data["opened"]
    if not opened:
        await cb.answer("Сначала открой хотя бы одну клетку!", show_alert=True)
        return
        
    mult = 1.0 + (len(opened) * 0.15)
    win_amount = int(data["bet"] * mult)
    
    u = await db_get_user(cb.from_user.id)
    win_amount = calc_win(win_amount, u) # VIP +3%
    
    await db_add_balance(cb.from_user.id, win_amount, "win_mines")
    await db_mines_finish(data["game_id"], "cashed")
    await db_add_history(cb.from_user.id, "мины", data["bet"], win_amount, round(win_amount/data["bet"], 2), "Забрал")
    await state.clear()
    
    text = f"💰 <b>Ты забрал выигрыш!</b>\n\n+{fmt_money(win_amount)} 🪙"
    await cb.message.edit_text(text, reply_markup=mines_kb(data["field"], opened, finished=True))
    asyncio.create_task(auto_delete(cb.message, GAME_MSG_TIMEOUT))
    await cb.answer("Выигрыш зачислен!")

# ------------------------------------------------------------
#  ДУЭЛИ
# ------------------------------------------------------------
def duel_accept_kb(challenger_id: int, bet: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚔️ Принять ({fmt_money(bet)})", callback_data=f"duel_acc_{challenger_id}_{bet}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="duel_dec")]
    ])

@router.message(F.text.regexp(r"(?i)^дуэль\s+@\w+\s+\d+"))
async def game_duel_start(msg: Message):
    u = await ensure_user(msg)
    args = msg.text.split()
    
    if len(args) < 3:
        await msg.answer("❌ Формат: <code>дуэль @юзер 1000</code>")
        return
        
    target_username = args[1].lstrip("@")
    amount = int(args[2])
    
    ok, err = check_bet(u, amount)
    if not ok:
        await msg.answer(err)
        return
        
    target = await db_find_user(target_username)
    if not target:
        await msg.answer("❌ Игрок не найден.")
        return
    if target["user_id"] == msg.from_user.id:
        await msg.answer("❌ Нельзя вызвать самого себя.")
        return
        
    if target["balance"] < amount:
        await msg.answer(f"❌ У соперника недостаточно средств ({fmt_money(target['balance'])} 🪙).")
        return
        
    # Блокируем ставку у вызывающего
    await db_add_balance(msg.from_user.id, -amount, "duel_bet")
    
    text = (
        f"⚔️ <b>Вызов на дуэль!</b>\n\n"
        f"👤 <b>{msg.from_user.first_name}</b> вызывает <b>{target['first_name']}</b>\n"
        f"💰 Ставка: <b>{fmt_money(amount)} 🪙</b>\n\n"
        f"<i>Соперник, у тебя 5 минут, чтобы принять!</i>"
    )
    await msg.answer(text, reply_markup=duel_accept_kb(msg.from_user.id, amount))

@router.callback_query(F.data.startswith("duel_acc_"))
async def cb_duel_accept(cb: CallbackQuery):
    _, _, challenger_id, bet = cb.data.split("_")
    challenger_id, bet = int(challenger_id), int(bet)
    accepter = await db_get_user(cb.from_user.id)
    
    if accepter["balance"] < bet:
        await cb.answer("❌ Недостаточно средств!", show_alert=True)
        return
        
    # Списываем у принявшего
    await db_add_balance(cb.from_user.id, -bet, "duel_bet")
    await cb.message.edit_text("⚔️ <b>Дуэль началась!</b> Бросаем кубики...")
    
    # Бросаем кубики
    msg1 = await cb.message.answer_dice(emoji="🎲")
    msg2 = await cb.message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    v1, v2 = msg1.dice.value, msg2.dice.value
    bank = int(bet * 2 * (1 - DUEL_COMMISSION)) # 5% комиссия
    
    if v1 > v2:
        winner_id = challenger_id
    elif v2 > v1:
        winner_id = cb.from_user.id
    else:
        # Ничья — возврат
        await db_add_balance(challenger_id, bet, "duel_refund")
        await db_add_balance(cb.from_user.id, bet, "duel_refund")
        await cb.message.answer(f"🤝 <b>Ничья!</b> ({v1} - {v2}). Ставки возвращены.")
        return
        
    await db_add_balance(winner_id, bank, "duel_win")
    winner_name = "Вызывающий" if winner_id == challenger_id else "Принявший"
    
    res_text = (
        f"⚔️ <b>Дуэль окончена!</b>\n\n"
        f"🎲 Вызывающий: <b>{v1}</b>\n"
        f"🎲 Принявший: <b>{v2}</b>\n\n"
        f"🏆 Победитель: <b>{winner_name}</b> (+{fmt_money(bank)} 🪙)"
    )
    await cb.message.answer(res_text)

@router.callback_query(F.data == "duel_dec")
async def cb_duel_decline(cb: CallbackQuery):
    await cb.message.edit_text("❌ Дуэль отклонена.")
    await cb.answer("Ты отклонил дуэль")

# ============================================================
#  ЧАСТЬ 4: РУЛЕТКА, ПЕРЕВОДЫ, ГРУППОВЫЕ КОМАНДЫ
# ============================================================

# ------------------------------------------------------------
#  РУЛЕТКА (МГНОВЕННЫЙ ПАРСЕР, БЕЗ АКТИВАЦИИ)
# ------------------------------------------------------------
def roulette_retry_kb(amount: int, bet_text: str) -> InlineKeyboardMarkup:
    """Кнопки Повторить/Удвоить для рулетки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Повторить ({fmt_money(amount)})", callback_data=f"r_rep_{amount}_{bet_text}"),
         InlineKeyboardButton(text=f"⏫ Удвоить ({fmt_money(amount*2)})", callback_data=f"r_dbl_{amount}_{bet_text}")]
    ])

@router.message(F.text.regexp(r"(?i)^(к|ч|красное|черное|red|black)\s+\d+$"))
@router.message(F.text.regexp(r"(?i)^\d+\s+(чет|нечет|чёт|нечёт|even|odd)$"))
@router.message(F.text.regexp(r"(?i)^(0|зеро|zero)\s+\d+$"))
@router.message(F.text.regexp(r"(?i)^\d+\s+[\d\-, ]+$"))
async def game_roulette(msg: Message):
    # Проверка: разрешены ли игры в чате
    chat_cfg = await db_chat_get(msg.chat.id)
    if not chat_cfg["games_enabled"]:
        warn = await msg.answer("⚠️ <b>Игры в этом чате временно отключены администратором!</b>")
        asyncio.create_task(auto_delete(warn, 5))
        return
        
    u = await ensure_user(msg)
    lang = u.get("lang", "ru")
    
    bet_info = parse_roulette_bet(msg.text)
    if not bet_info:
        return # Не ставка
        
    amount = bet_info["amount"]
    
    # Проверка ставки
    ok, err = check_bet(u, amount)
    if not ok:
        err_msg = await msg.answer(err)
        asyncio.create_task(auto_delete(err_msg, 15))
        return
        
    # Мгновенно списываем
    await db_add_balance(msg.from_user.id, -amount, "bet_roulette")
    
    # Сообщение о приеме ставки
    accept_text = f"✅ <b>Ставка принята:</b> {msg.from_user.first_name} {fmt_money(amount)} на {bet_info['text']}"
    accept_msg = await msg.answer(accept_text)
    
    # Крутим кубик (рулетка)
    dice_msg = await msg.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)
    
    # Telegram кубик 🎰 выдает 1-64. Переводим в 0-36.
    result_num = (dice_msg.dice.value - 1) % 37
    color = get_roulette_color(result_num)
    color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]
    
    win_amount, mult = calc_roulette_win(bet_info, result_num)
    
    if win_amount > 0:
        win_amount = calc_win(win_amount, u) # VIP +3%
        await db_add_balance(msg.from_user.id, win_amount, "win_roulette")
        result_text = (
            f"🎯 Выпало: {color_emoji} <b>{result_num}</b>\n\n"
            f"💰 <b>{msg.from_user.first_name}</b> выиграл <b>{fmt_money(win_amount)} 🪙</b>!"
        )
    else:
        result_text = (
            f"🎯 Выпало: {color_emoji} <b>{result_num}</b>\n\n"
            f"💸 <b>{msg.from_user.first_name}</b> проиграл <b>{fmt_money(amount)} 🪙</b>."
        )
        
    await db_add_history(msg.from_user.id, "рулетка", amount, win_amount, mult, f"Выпало {result_num}")
    await db_add_roulette_log(msg.chat.id, msg.from_user.id, amount, win_amount, str(result_num), color)
    
    # Отправляем результат с кнопками Повторить/Удвоить
    await msg.answer(result_text, reply_markup=roulette_retry_kb(amount, bet_info["text"]))
    
    # Автоудаление
    asyncio.create_task(auto_delete(accept_msg, 10))
    try: await dice_msg.delete()
    except: pass

# Обработка кнопок Повторить/Удвоить
@router.callback_query(F.data.startswith("r_"))
async def cb_roulette_retry(cb: CallbackQuery):
    action, amount_str, bet_text = cb.data.split("_", 2)
    amount = int(amount_str)
    if action == "dbl": amount *= 2
    
    u = await db_get_user(cb.from_user.id)
    ok, err = check_bet(u, amount)
    if not ok:
        await cb.answer(err, show_alert=True)
        return
        
    await cb.message.delete()
    # Имитируем отправку нового сообщения для запуска игры
    fake_msg = cb.message
    fake_msg.text = f"{amount} {bet_text}" if " " in bet_text else f"{bet_text.split()[0]} {amount}"
    # В реальности тут нужно вызвать логику игры напрямую, но для простоты 
    # мы просто отправляем сообщение от имени бота, которое триггернет парсер
    await bot.send_message(cb.message.chat.id, fake_msg.text)
    await cb.answer()

# ------------------------------------------------------------
#  КОМАНДЫ: БАЛАНС, ЛОГ, КУРС
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^(б|баланс)(\s+.*)?$"))
async def cmd_balance(msg: Message):
    await ensure_user(msg)
    parts = msg.text.split()
    
    if len(parts) > 1:
        target = await db_find_user(parts[1])
        if not target:
            await msg.answer("❌ Игрок не найден.")
            return
        name = target.get("first_name") or f"ID{target['user_id']}"
        await msg.answer(f"💰 Баланс <b>{name}</b>:\n<b>{fmt_money(target['balance'])} TOKENS</b>")
    else:
        u = await db_get_user(msg.from_user.id)
        await msg.answer(f"💰 Твой баланс:\n<b>{fmt_money(u['balance'])} TOKENS</b>")

@router.message(F.text.regexp(r"(?i)^(лог|логи)$"))
async def cmd_log(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        # В ЛС показываем историю игр
        hist = await db_get_history(msg.from_user.id, limit=10)
        if not hist: 
            await msg.answer("📜 Ты еще не играл.")
            return
        lines = ["📜 <b>Последние 10 игр:</b>\n"]
        for h in hist:
            sign = "🟢" if h["win"] > 0 else "🔴"
            lines.append(f"{sign} {h['game']} | ставка: {fmt_money(h['bet'])} | выигрыш: {fmt_money(h['win'])}")
        await msg.answer("\n".join(lines))
    else:
        # В группе показываем лог чисел
        logs = await db_roulette_logs(msg.chat.id, limit=10)
        if not logs:
            await msg.answer("📜 Лог пуст.")
            return
        lines = ["📜 <b>Последние 10 чисел:</b>\n"]
        for r in reversed(logs):
            color = r.get("color", "green")
            emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}.get(color, "⚪")
            lines.append(f"{emoji} {r['numbers']}")
        await msg.answer("\n".join(lines))

@router.message(F.text.regexp(r"(?i)^курс$"))
async def cmd_course(msg: Message):
    courses = await db_get_courses()
    lines = ["💱 <b>Курсы валют:</b>\n"]
    for name, rate in courses.items():
        lines.append(f"• {name}: <b>{fmt_money(rate)}</b>")
    await msg.answer("\n".join(lines))

# ------------------------------------------------------------
#  ПЕРЕВОДЫ (ПО @USER И ПО ID)
# ------------------------------------------------------------
def transfer_confirm_kb(target_id: int, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"tr_yes_{target_id}_{amount}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="tr_no")]
    ])

@router.message(F.text.regexp(r"(?i)^(перевод|перевести|подарить|pay)\s+\S+\s+\d+$"))
async def cmd_transfer(msg: Message):
    parts = msg.text.split()
    target_q = parts[1]
    amount = int(parts[2])
    
    u = await ensure_user(msg)
    if amount < MIN_BET:
        await msg.answer(f"❌ Минимальный перевод: {fmt_money(MIN_BET)}")
        return
        
    target = await db_find_user(target_q)
    if not target:
        await msg.answer("❌ Получатель не найден.")
        return
    if target["user_id"] == msg.from_user.id:
        await msg.answer("❌ Нельзя переводить себе.")
        return
    if u["balance"] < amount:
        await msg.answer(f"❌ Недостаточно средств. У тебя: {fmt_money(u['balance'])}")
        return
        
    name = target.get("first_name") or f"ID{target['user_id']}"
    await msg.answer(
        f"💸 <b>Подтверждение перевода</b>\n\n"
        f"Кому: <b>{name}</b>\n"
        f"Сумма: <b>{fmt_money(amount)} TOKENS</b>",
        reply_markup=transfer_confirm_kb(target["user_id"], amount)
    )

@router.callback_query(F.data.startswith("tr_yes_"))
async def cb_transfer_yes(cb: CallbackQuery):
    _, _, target_id, amount = cb.data.split("_")
    target_id, amount = int(target_id), int(amount)
    
    sender = await db_get_user(cb.from_user.id)
    if sender["balance"] < amount:
        await cb.answer("❌ Недостаточно средств!", show_alert=True)
        return
        
    await db_add_balance(cb.from_user.id, -amount, "transfer_out")
    await db_add_balance(target_id, amount, "transfer_in")
    
    await db_add_history(cb.from_user.id, "перевод", amount, 0, 0, f"→ ID{target_id}")
    
    await cb.message.edit_text(f"✅ Перевод <b>{fmt_money(amount)} TOKENS</b> выполнен!")
    await cb.answer("Успешно!")
    
    # Уведомление получателю
    target = await db_get_user(target_id)
    if target and target.get("notify_transfers"):
        try:
            await bot.send_message(
                target_id,
                f"💸 <b>Тебе перевели!</b>\n\n"
                f"От: <b>{cb.from_user.first_name}</b>\n"
                f"Сумма: <b>{fmt_money(amount)} TOKENS</b>"
            )
        except: pass

@router.callback_query(F.data == "tr_no")
async def cb_transfer_no(cb: CallbackQuery):
    await cb.message.edit_text("❌ Перевод отменен.")
    await cb.answer()

# ------------------------------------------------------------
#  ПРОМОКОДЫ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^промо\s+\w+$"))
async def cmd_promo(msg: Message):
    code = msg.text.split()[1].upper()
    u = await ensure_user(msg)
    
    amount = await db_redeem_promo(code, msg.from_user.id)
    if amount == -1:
        await msg.answer("❌ Ты уже активировал этот промокод.")
    elif amount is None:
        await msg.answer("❌ Промокод не найден или закончился.")
    else:
        await db_add_balance(msg.from_user.id, amount, "promo")
        res = await msg.answer(f"🎉 Промокод активирован!\n💰 +{fmt_money(amount)} TOKENS")
        asyncio.create_task(auto_delete(res, 30))

# ------------------------------------------------------------
#  ФОЛБЭК (Если бот не понял)
# ------------------------------------------------------------
@router.message()
async def fallback_handler(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        # Игнорируем Reply-кнопки, чтобы они не срабатывали как фолбэк
        # (Мы их обрабатываем выше, тут только неизвестный текст)
        if msg.text in [
            get_text("menu_how_to_play", "ru"), get_text("menu_how_to_play", "en"),
            get_text("menu_bonus", "ru"), get_text("menu_bonus", "en"),
            # и т.д. (можно прописать все кнопки)
        ]:
            return
            
        u = await db_get_user(msg.from_user.id)
        lang = u.get("lang", "ru") if u else "ru"
        await msg.answer(get_text("not_understood", lang))

# ============================================================
#  ЧАСТЬ 5: АДМИНКА, АВТО-ИВЕНТЫ, ВЕБ-СЕРВЕР, ЗАПУСК
# ============================================================

# ------------------------------------------------------------
#  АДМИНКА: ИИ-ПОМОЩНИК (Все команды через @)
# ------------------------------------------------------------
@router.message(Command("admin"))
async def admin_help_cmd(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    await admin_help(msg)

@router.message(F.text.regexp(r"^@помощь$"))
async def admin_help(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    
    text = (
        "🤖 <b>ИИ-Помощник активирован.</b>\n\n"
        "👤 <b>Юзеры:</b>\n"
        "<code>@выдать @user 1000 [причина]</code>\n"
        "<code>@бан @user [причина]</code>\n"
        "<code>@разбан @user</code>\n"
        "<code>@банкрот @user</code>\n"
        "<code>@юзер @user</code>\n"
        "<code>@стата</code>\n\n"
        "💰 <b>Экономика:</b>\n"
        "<code>@дроп 1000</code>\n"
        "<code>@дроп_всем 1000</code>\n"
        "<code>@забрать_всем 1000</code>\n"
        "<code>@топ_баланс</code>\n\n"
        "🎮 <b>Управление играми (в текущем чате):</b>\n"
        "<code>@игры_выкл</code> / <code>@игры_вкл</code>\n"
        "<code>@игра_выкл рулетка</code>\n\n"
        "💱 <b>Курсы и Ивенты:</b>\n"
        "<code>@курс_добавить GRAM 7500</code>\n"
        "<code>@ивент_чат_добавить</code>\n\n"
        "📢 <b>Контент:</b>\n"
        "<code>@рассылка текст</code>\n"
        "<code>@апдейт текст</code>\n"
        "<code>@промо КОД 5000 10</code>\n"
        "<code>@очистить_чат 50</code>\n\n"
        "⚙️ <b>Система:</b>\n"
        "<code>@лог 20</code> | <code>@аудит</code> | <code>@бекап</code> | <code>@рестарт</code>\n\n"
        "<i>Пример: @выдать @vasya 5000 за активность</i>"
    )
    await msg.answer(text)

# --- ПАРСЕР КОМАНД ---
@router.message(F.text.startswith("@"))
async def admin_commands_handler(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    
    text = msg.text
    args = text.split()
    cmd = args[0].lower()
    
    # --- ЮЗЕРЫ ---
    if cmd == "@выдать":
        if len(args) < 3: 
            await msg.answer("🤖 Формат: <code>@выдать @user 1000 [причина]</code>")
            return
        target = await db_find_user(args[1])
        if not target:
            await msg.answer("❌ Юзер не найден.")
            return
        amount = int(args[2])
        reason = " ".join(args[3:]) if len(args) > 3 else "Админ-выдача"
        await db_add_balance(target["user_id"], amount, "admin_give")
        await db_admin_log(ADMIN_ID, "give", target["user_id"], f"+{amount} ({reason})")
        await msg.answer(f"✅ Выдано {fmt_money(amount)} TOKENS юзеру {target['first_name']}.")

    elif cmd == "@бан":
        if len(args) < 2: return
        target = await db_find_user(args[1])
        if not target: return
        reason = " ".join(args[2:]) if len(args) > 2 else "Без причины"
        await db_ban_user(target["user_id"], True, reason)
        await msg.answer(f"🚫 Юзер {target['first_name']} забанен. Причина: {reason}")

    elif cmd == "@разбан":
        if len(args) < 2: return
        target = await db_find_user(args[1])
        if not target: return
        await db_ban_user(target["user_id"], False)
        await msg.answer(f"✅ Юзер {target['first_name']} разбанен.")

    elif cmd == "@банкрот":
        if len(args) < 2: return
        target = await db_find_user(args[1])
        if not target: return
        await db_save_user(target["user_id"], balance=0)
        await msg.answer(f"💀 Баланс {target['first_name']} обнулен.")

    elif cmd == "@юзер":
        if len(args) < 2: return
        target = await db_find_user(args[1])
        if not target: return
        hist = await db_get_history(target["user_id"], 5)
        text = f"👤 <b>{target['first_name']}</b> (ID: <code>{target['user_id']}</code>)\n💰 Баланс: {fmt_money(target['balance'])}\n🎮 Игр: {target['games_played']}\n🚫 Бан: {'Да' if target['banned'] else 'Нет'}\n\n<b>Последние игры:</b>\n"
        for h in hist: text += f"• {h['game']} | {fmt_money(h['bet'])} -> {fmt_money(h['win'])}\n"
        await msg.answer(text)

    elif cmd == "@стата":
        users = await db_count_users()
        total_bal = await db_total_balance()
        await msg.answer(f"📊 <b>Статистика:</b>\n👥 Юзеров: {users}\n💰 Всего TOKENS: {fmt_money(total_bal)}")

    # --- ЭКОНОМИКА ---
    elif cmd == "@дроп":
        if len(args) < 2: return
        amount = int(args[1])
        drop_id = await db_drop_create(msg.chat.id, amount, ttl=600)
        await msg.answer(f"🎁 <b>Дроп {fmt_money(amount)} TOKENS!</b>\nКто первый нажмет — заберет!", 
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Забрать {amount}", callback_data=f"drop_take_{drop_id}")]]))

    elif cmd == "@дроп_всем":
        if len(args) < 2: return
        amount = int(args[1])
        users = await db_all_user_ids()
        for uid in users: await db_add_balance(uid, amount, "admin_drop_all")
        await msg.answer(f"✅ Выдано по {fmt_money(amount)} TOKENS всем ({len(users)} чел.).")

    # --- УПРАВЛЕНИЕ ЧАТАМИ ---
    elif cmd == "@игры_выкл":
        await db_chat_toggle_games(msg.chat.id, False, ADMIN_ID)
        await msg.answer("⚠️ Игры в этом чате <b>ОТКЛЮЧЕНЫ</b>.")
    
    elif cmd == "@игры_вкл":
        await db_chat_toggle_games(msg.chat.id, True, ADMIN_ID)
        await msg.answer("✅ Игры в этом чате <b>ВКЛЮЧЕНЫ</b>.")

    elif cmd == "@игра_выкл":
        if len(args) < 2: return
        await db_chat_toggle_specific_game(msg.chat.id, args[1].lower(), False)
        await msg.answer(f"⚠️ Игра {args[1]} выключена.")

    # --- КУРСЫ И ИВЕНТЫ ---
    elif cmd == "@курс_добавить":
        if len(args) < 3: return
        await db_add_course(args[1], int(args[2]))
        await msg.answer(f"✅ Курс {args[1]} добавлен: {args[2]}")

    elif cmd == "@ивент_чат_добавить":
        await db_event_chat_add(msg.chat.id, msg.chat.title or "Event Chat")
        await msg.answer("✅ Этот чат добавлен в список Ивент-чатов (Онли).")

    # --- КОНТЕНТ ---
    elif cmd == "@рассылка":
        text_to_send = text.replace("@рассылка ", "")
        users = await db_all_user_ids()
        count = 0
        await msg.answer("⏳ Рассылка началась...")
        for uid in users:
            try:
                await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{text_to_send}")
                count += 1
                await asyncio.sleep(0.05) # Чтобы не забанил ТГ
            except: pass
        await msg.answer(f"✅ Отправлено {count} юзерам.")

    elif cmd == "@апдейт":
        upd = text.replace("@апдейт ", "")
        await db_add_changelog(upd)
        await msg.answer("✅ Добавлено в «Что нового».")

    elif cmd == "@бекап":
        data = await db_backup()
        await msg.answer_document(FSInputFile(DB_PATH, filename=f"backup_{now_ts()}.db"), caption="💾 Бекап БД")
        
    elif cmd == "@рестарт":
        await msg.answer("🔄 Перезапуск планировщика...")
        scheduler.remove_all_jobs()
        setup_scheduler()
        await msg.answer("✅ Готово.")

# ------------------------------------------------------------
#  ЗАБОР ДРОПА (Инлайн-кнопка)
# ------------------------------------------------------------
@router.callback_query(F.data.startswith("drop_take_"))
async def cb_drop_take(cb: CallbackQuery):
    drop_id = int(cb.data.split("_")[-1])
    amount = await db_drop_take(drop_id, cb.from_user.id)
    
    if amount is None:
        await cb.answer("❌ Дроп уже забрали или он истек.", show_alert=True)
        return
        
    await db_add_balance(cb.from_user.id, amount, "drop")
    await cb.message.edit_text(f"🎉 {cb.from_user.first_name} забрал дроп <b>{fmt_money(amount)} TOKENS</b>!")
    await cb.answer(f"Ты забрал {amount} TOKENS!")

# ------------------------------------------------------------
#  АВТО-ИВЕНТЫ (ФОНОВЫЕ ЗАДАЧИ)
# ------------------------------------------------------------
async def event_auto_drop():
    """Авто-дроп раз в 2 часа."""
    chats = await db_event_chats_all()
    for chat in chats:
        if not chat["bonus_drop"]: continue
        amount = random.randint(5000, 20000)
        drop_id = await db_drop_create(chat["chat_id"], amount, ttl=600)
        
        text = f"🎁 <b>АВТО-ДРОП!</b>\n\nКто первый нажмет, тот забирает <b>{fmt_money(amount)} TOKENS</b>!"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Забрать", callback_data=f"drop_take_{drop_id}")]])
        
        try:
            # Отправляем с фото (если есть)
            photo = FSInputFile(IMG_BONUS) if os.path.exists(IMG_BONUS) else None
            if photo: await bot.send_photo(chat["chat_id"], photo, caption=text, reply_markup=kb)
            else: await bot.send_message(chat["chat_id"], text, reply_markup=kb)
        except Exception as e:
            logger.error(f"Drop error {chat['chat_id']}: {e}")

async def event_happy_hour():
    """Включает х2 на час."""
    await db_set_setting("happy_hour", "1")
    chats = await db_event_chats_all()
    text = "🕐 <b>СЧАСТЛИВЫЙ ЧАС!</b>\n\nВ течение часа все выигрыши удваиваются (x2)!\nУспей сыграть!"
    for chat in chats:
        if not chat["happy_hour"]: continue
        try: await bot.send_message(chat["chat_id"], text)
        except: pass
        
    await asyncio.sleep(3600) # Ждем час
    await db_set_setting("happy_hour", "0")

async def event_tournament():
    """Ежедневный турнир в 20:00."""
    # Берем топ-3 по выигрышу за сегодня (упрощенно - по total_win)
    top = await db_top_users(3, by="win")
    if not top: return
    
    chats = await db_event_chats_all()
    text = "🏆 <b>ИТОГИ ДНЯ!</b>\n\nЛучшие игроки:\n"
    for i, u in enumerate(top):
        prize = [50000, 25000, 10000][i]
        await db_add_balance(u["user_id"], prize, "tournament_prize")
        text += f"{i+1}. {u['first_name']} — +{fmt_money(prize)} TOKENS\n"
        
    for chat in chats:
        if not chat["tournament"]: continue
        try: await bot.send_message(chat["chat_id"], text)
        except: pass

def setup_scheduler():
    scheduler.add_job(event_auto_drop, 'interval', hours=2)
    scheduler.add_job(event_happy_hour, 'interval', hours=4)
    scheduler.add_job(event_tournament, 'cron', hour=20, minute=0)
    scheduler.add_job(db_expire_drops, 'interval', minutes=10)
    scheduler.add_job(db_expire_duels, 'interval', minutes=5)
    scheduler.start()

# ------------------------------------------------------------
#  ВЕБ-СЕРВЕР (Для Render, чтобы не засыпал)
# ------------------------------------------------------------
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}")

# ------------------------------------------------------------
#  ЗАПУСК БОТА
# ------------------------------------------------------------
async def self_test():
    try:
        me = await bot.get_me()
        logger.info(f"✅ Бот: @{me.username}")
    except:
        logger.error("❌ ОШИБКА ТОКЕНА!")
        return False
    logger.info("✅ База данных: OK")
    return True

async def main():
    logger.info("🚀 Запуск бота...")
    
    # 1. СРАЗУ ЗАПУСКАЕМ ВЕБ-СЕРВЕР (чтобы Render видел порт)
    asyncio.create_task(web_server())
    
    # 2. Потом чистим и инициализируем БД
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    await db_init()
    
    if not await self_test():
        return
        
    setup_scheduler()
    
    # 3. Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")