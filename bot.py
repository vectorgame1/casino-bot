# ============================================================
#  TOKENS BOT - ЧАСТЬ 1: ФУНДАМЕНТ И БАЗА
# ============================================================

import os
import re
import json
import time
import random
import asyncio
import logging
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
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- НАСТРОЙКИ ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
CHAT_ID: int = int(os.getenv("CHAT_ID", "0"))
EVENT_CHAT_ID: int = int(os.getenv("EVENT_CHAT_ID", "0"))
PORT: int = int(os.getenv("PORT", "8080"))

START_BALANCE = 5000
MIN_BET = 100
MAX_BET = 1_000_000
CLAN_CREATE_COST = 100_000
DUEL_COMMISSION = 0.05
BONUS_COOLDOWN = 24 * 3600
BONUS_MIN = 1000
BONUS_MAX = 5000
STAR_RATE = 7500
VIP_BONUS = 1.03
VIP_PRICES = {1: 5, 7: 30, 30: 100, 365: 1000}
VIP_DAYS_IN_SEC = 86400
GAME_MSG_TIMEOUT = 60
DB_PATH = "casino.db"

# ЖЕЛЕЗНЫЙ ФИКС: УДАЛЯЕМ СТАРУЮ БАЗУ, ЧТОБЫ RENDER НЕ ПАДАЛ
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("tokens_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- ТЕКСТЫ (RU / EN) ---
TEXTS = {
    "ru": {
        "menu_how_to_play": "🎮 Как играть", "menu_bonus": "🎁 Бонус", "menu_donate": "💎 Донат",
        "menu_profile": "👤 Профиль", "menu_clan": "🛡 Клан", "menu_ref": "🔗 Рефералка",
        "menu_top": "🏆 Топ", "menu_chats": "💬 Чаты", "menu_support": "🆘 Поддержка", "menu_commands": "📖 Команды",
        "start_text": "👋 <b>Привет, {name}!</b>\n\n💎 Добро пожаловать в <b>TOKENS</b>!\n🎮 Играй, выигрывай и поднимайся в топ!\n\n💰 Твой баланс: <b>{balance} 🪙</b>\n\n👇 Используй меню ниже.",
        "profile_text": "👤 <b>Профиль</b>\n\n🆔 ID: <code>{user_id}</code>\n📛 Имя: <b>{name}</b>\n\n💰 Баланс: <b>{balance} 🪙</b>\n👑 VIP: <b>{vip}</b>\n🛡 Клан: <b>{clan}</b>\n\n🎮 Сыграно игр: <b>{games}</b>\n🎯 Ставок: <b>{total_bet} 🪙</b>\n🏆 Выиграно: <b>{total_win} 🪙</b>",
        "vip_active": "Активен ({days} дн.)", "vip_none": "Не активен", "clan_none": "Нет",
        "not_understood": "🤖 <b>Я тебя не понял...</b>\n\n👇 Нажми <b>«📖 Команды»</b> или <b>«🆘 Поддержка»</b>.",
        "error_bet_min": "❌ Мин. ставка: {min_bet} 🪙", "error_bet_max": "❌ Макс. ставка: {max_bet} 🪙",
        "error_no_money": "❌ Мало средств: {balance} 🪙", "error_banned": "🚫 Ты забанен.",
        "cancel_success": "🛑 <b>Действие отменено.</b>",
    },
    "en": {
        "menu_how_to_play": "🎮 How to play", "menu_bonus": "🎁 Bonus", "menu_donate": "💎 Donate",
        "menu_profile": "👤 Profile", "menu_clan": "🛡 Clan", "menu_ref": "🔗 Referral",
        "menu_top": "🏆 Top", "menu_chats": "💬 Chats", "menu_support": "🆘 Support", "menu_commands": "📖 Commands",
        "start_text": "👋 <b>Hello, {name}!</b>\n\n💎 Welcome to <b>TOKENS</b>!\n\n💰 Balance: <b>{balance} 🪙</b>\n\n👇 Use menu.",
        "profile_text": "👤 <b>Profile</b>\n\n🆔 ID: <code>{user_id}</code>\n📛 Name: <b>{name}</b>\n\n💰 Balance: <b>{balance} 🪙</b>\n👑 VIP: <b>{vip}</b>\n🛡 Clan: <b>{clan}</b>\n\n🎮 Games: <b>{games}</b>\n🎯 Bets: <b>{total_bet} 🪙</b>\n🏆 Won: <b>{total_win} 🪙</b>",
        "vip_active": "Active ({days} days)", "vip_none": "Not active", "clan_none": "None",
        "not_understood": "🤖 <b>I didn't understand...</b>\n\n👇 Click <b>«📖 Commands»</b> or <b>«🆘 Support»</b>.",
        "error_bet_min": "❌ Min bet: {min_bet} 🪙", "error_bet_max": "❌ Max bet: {max_bet} 🪙",
        "error_no_money": "❌ Insufficient funds: {balance} 🪙", "error_banned": "🚫 Banned.",
        "cancel_success": "🛑 <b>Cancelled.</b>",
    }
}

def get_text(key: str, lang: str = "ru", **kwargs) -> str:
    lang = lang if lang in TEXTS else "ru"
    text = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    if kwargs:
        try: return text.format(**kwargs)
        except: return text
    return text

# --- УТИЛИТЫ ---
def fmt_money(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")

def now_ts() -> int:
    return int(time.time())

def is_vip(user: Optional[Dict[str, Any]]) -> bool:
    if not user: return False
    return int(user.get("vip_until") or 0) > now_ts()

def calc_win(base_amount: int, user: Dict[str, Any]) -> int:
    return int(base_amount * VIP_BONUS) if is_vip(user) else base_amount

async def auto_delete(message: Message, delay: int = GAME_MSG_TIMEOUT) -> None:
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

# --- БАЗА ДАННЫХ (ИНИЦИАЛИЗАЦИЯ) ---
async def db_init() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, balance INTEGER DEFAULT 0,
            vip_until INTEGER DEFAULT 0, clan_id INTEGER DEFAULT 0, referrer_id INTEGER DEFAULT 0,
            ref_count INTEGER DEFAULT 0, total_bet INTEGER DEFAULT 0, total_win INTEGER DEFAULT 0,
            total_lost INTEGER DEFAULT 0, games_played INTEGER DEFAULT 0, banned INTEGER DEFAULT 0,
            ban_reason TEXT, last_bonus INTEGER DEFAULT 0, last_seen INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'ru', notify_transfers INTEGER DEFAULT 1, notify_games INTEGER DEFAULT 1, reg_date INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, owner_id INTEGER,
            balance INTEGER DEFAULT 0, level INTEGER DEFAULT 1, invite_code TEXT UNIQUE, created_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS clan_members (
            clan_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', joined_at INTEGER DEFAULT 0, PRIMARY KEY (clan_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT, bet INTEGER, win INTEGER,
            multiplier REAL DEFAULT 0, balance_after INTEGER DEFAULT 0, result TEXT, ts INTEGER
        );
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, bet INTEGER, win INTEGER,
            numbers TEXT, color TEXT, ts INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY, amount INTEGER, uses_left INTEGER, created_by INTEGER, created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS promo_uses (code TEXT, user_id INTEGER, used_at INTEGER, PRIMARY KEY (code, user_id));
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, target_id INTEGER, details TEXT, chat_id INTEGER, ts INTEGER
        );
        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, bet INTEGER, status TEXT DEFAULT 'pending',
            winner_id INTEGER, chat_id INTEGER, created_at INTEGER, expires_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS mines_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bet INTEGER, field_json TEXT, opened_json TEXT,
            mult REAL DEFAULT 1.0, status TEXT DEFAULT 'active', created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bonus_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, amount INTEGER, claimed_by INTEGER, created_at INTEGER, expires_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS roulette_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, bet INTEGER, created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bans_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, admin_id INTEGER, reason TEXT, banned_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY, games_enabled INTEGER DEFAULT 1, disabled_games TEXT DEFAULT '[]', updated_by INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_chats (
            chat_id INTEGER PRIMARY KEY, title TEXT, auto_roulette INTEGER DEFAULT 1, bonus_item INTEGER DEFAULT 1, added_at INTEGER
        );
        """)
        defaults = {"star_rate": str(STAR_RATE), "happy_hour": "0", "changelog": "[]", "multi_courses": json.dumps({"TOKENS": 7500})}
        for k, v in defaults.items():
            await db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        await db.commit()
    logger.info("✅ БД инициализирована")

# ============================================================
#  ЧАСТЬ 2: ФУНКЦИИ БАЗЫ ДАННЫХ
# ============================================================

# ------------------------------------------------------------
#  ПОЛЬЗОВАТЕЛИ
# ------------------------------------------------------------
async def db_get_user(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_create_user(user_id: int, username: str, first_name: str, referrer_id: int = 0) -> Dict[str, Any]:
    now = now_ts()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT OR IGNORE INTO users (user_id, username, first_name, balance, referrer_id, reg_date, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username or "", first_name or "", START_BALANCE, referrer_id, now, now))
        await db.commit()
    if referrer_id and referrer_id != user_id:
        if await db_get_user(referrer_id):
            await db_add_balance(referrer_id, 2000, "ref")
            await db_add_balance(user_id, 1000, "ref_friend")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (referrer_id,))
                await db.commit()
    return await db_get_user(user_id) or {}

async def db_save_user(user_id: int, **fields) -> None:
    if not fields: return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {cols} WHERE user_id = ?", vals)
        await db.commit()

async def db_add_balance(user_id: int, amount: int, reason: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0

async def db_find_user(query: str) -> Optional[Dict[str, Any]]:
    q = (query or "").strip().lstrip("@")
    if not q: return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if q.isdigit():
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (int(q),)) as cur:
                row = await cur.fetchone()
                if row: return dict(row)
        async with db.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (q,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def db_ban_user(user_id: int, banned: bool = True, reason: str = "") -> None:
    await db_save_user(user_id, banned=1 if banned else 0, ban_reason=reason)
    if banned:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO bans_history (user_id, admin_id, reason, banned_at) VALUES (?, ?, ?, ?)", (user_id, ADMIN_ID, reason, now_ts()))
            await db.commit()

async def db_set_vip(user_id: int, days: int) -> None:
    u = await db_get_user(user_id)
    if not u: return
    base_time = u.get("vip_until", 0) if u.get("vip_until", 0) > now_ts() else now_ts()
    await db_save_user(user_id, vip_until=base_time + (days * VIP_DAYS_IN_SEC))

async def db_count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur: return (await cur.fetchone())[0]

async def db_total_balance() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(SUM(balance),0) FROM users") as cur: return (await cur.fetchone())[0]

async def db_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE banned = 0") as cur: return [r[0] for r in await cur.fetchall()]

async def db_top_users(limit: int = 10, by: str = "balance") -> List[Dict[str, Any]]:
    field = "balance" if by == "balance" else "total_win"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT * FROM users WHERE banned = 0 ORDER BY {field} DESC LIMIT ?", (limit,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  ИСТОРИЯ И СТАТИСТИКА
# ------------------------------------------------------------
async def db_add_history(user_id: int, game: str, bet: int, win: int, mult: float = 0.0, result: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            bal = row[0] if row else 0
        await db.execute("""INSERT INTO history (user_id, game, bet, win, multiplier, balance_after, result, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, game, bet, win, mult, bal, result, now_ts()))
        await db.execute("""UPDATE users SET total_bet = total_bet + ?, total_win = total_win + ?, total_lost = total_lost + ?, games_played = games_played + 1 WHERE user_id = ?""",
            (bet, max(win, 0), bet if win == 0 else 0, user_id))
        await db.commit()

async def db_get_history(user_id: int, limit: int = 10, filter_type: str = "all") -> List[Dict[str, Any]]:
    q = "SELECT * FROM history WHERE user_id = ?"
    p = [user_id]
    if filter_type == "win": q += " AND win > bet"
    elif filter_type == "lose": q += " AND win = 0"
    elif filter_type == "transfer": q += " AND game = 'перевод'"
    q += " ORDER BY id DESC LIMIT ?"
    p.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, p) as cur: return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  БОНУСЫ И НАСТРОЙКИ
# ------------------------------------------------------------
async def db_can_take_bonus(user_id: int, cooldown: int) -> bool:
    u = await db_get_user(user_id)
    if not u: return False
    return now_ts() - int(u.get("last_bonus") or 0) >= cooldown

async def db_claim_bonus(user_id: int, amount: int) -> None:
    await db_save_user(user_id, last_bonus=now_ts())
    await db_add_balance(user_id, amount, "bonus")

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
    raw = await db_get_setting("multi_courses", "{}")
    try: return json.loads(raw)
    except: return {}

async def db_add_course(name: str, rate: int) -> None:
    c = await db_get_courses()
    c[name] = rate
    await db_set_setting("multi_courses", json.dumps(c))

async def db_get_changelog() -> List[str]:
    raw = await db_get_setting("changelog", "[]")
    try: return json.loads(raw)
    except: return []

async def db_add_changelog(entry: str) -> None:
    log = await db_get_changelog()
    log.insert(0, entry)
    await db_set_setting("changelog", json.dumps(log[:50], ensure_ascii=False))

# ------------------------------------------------------------
#  ПРОМОКОДЫ И ЛОГИ
# ------------------------------------------------------------
async def db_create_promo(code: str, amount: int, uses: int, created_by: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO promocodes(code, amount, uses_left, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (code, amount, uses, created_by, now_ts()))
            await db.commit()
            return True
        except: return False

async def db_redeem_promo(code: str, user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT 1 FROM promo_uses WHERE code = ? AND user_id = ?", (code, user_id)) as cur:
            if await cur.fetchone(): return -1
        async with db.execute("SELECT * FROM promocodes WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
            if not row or row["uses_left"] <= 0: return None
            await db.execute("UPDATE promocodes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
            await db.execute("INSERT INTO promo_uses(code, user_id, used_at) VALUES (?, ?, ?)", (code, user_id, now_ts()))
            await db.commit()
            return row["amount"]

async def db_admin_log(admin_id: int, action: str, target_id: int = 0, details: str = "", chat_id: int = 0) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO admin_logs(admin_id, action, target_id, details, chat_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (admin_id, action, target_id, details, chat_id, now_ts()))
        await db.commit()

async def db_add_roulette_log(chat_id: int, user_id: int, bet: int, win: int, numbers: str, color: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO roulette_logs(chat_id, user_id, bet, win, numbers, color, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, bet, win, numbers, color, now_ts()))
        await db.commit()

async def db_roulette_logs(chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM roulette_logs WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  КЛАНЫ
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
    u = await db_get_user(owner_id)
    if not u or u["balance"] < cost or u.get("clan_id"): return None
    if await db_get_clan_by_name(name): return None
    invite = f"CLAN{random.randint(1000, 9999)}"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO clans(name, owner_id, balance, invite_code, created_at) VALUES (?, ?, ?, ?, ?)", (name, owner_id, 0, invite, now_ts()))
        await db.commit()
        cid = cursor.lastrowid
    await db_add_balance(owner_id, -cost, "clan_create")
    await db_save_user(owner_id, clan_id=cid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO clan_members(clan_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)", (cid, owner_id, now_ts()))
        await db.commit()
    return cid

async def db_clan_member_count(clan_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (clan_id,)) as cur: return (await cur.fetchone())[0]

async def db_clan_deposit(clan_id: int, user_id: int, amount: int) -> bool:
    u = await db_get_user(user_id)
    if not u or u["balance"] < amount or amount <= 0: return False
    await db_add_balance(user_id, -amount, "clan_deposit")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET balance = balance + ? WHERE clan_id = ?", (amount, clan_id))
        await db.commit()
    return True

async def db_clan_leave(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_members WHERE user_id = ?", (user_id,))
        await db.commit()
    await db_save_user(user_id, clan_id=0)

async def db_get_clan_top(limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT c.*, (SELECT COALESCE(SUM(balance),0) FROM users WHERE clan_id = c.clan_id) AS members_balance
            FROM clans c ORDER BY (c.balance + (SELECT COALESCE(SUM(balance),0) FROM users WHERE clan_id = c.clan_id)) DESC LIMIT ?""", (limit,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

# ------------------------------------------------------------
#  ДУЭЛИ, МИНЫ, БОНУСЫ
# ------------------------------------------------------------
async def db_create_duel(c_id: int, o_id: int, bet: int, chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO duels(challenger_id, opponent_id, bet, status, chat_id, created_at, expires_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (c_id, o_id, bet, chat_id, now_ts(), now_ts()+300))
        await db.commit()
        return cursor.lastrowid

async def db_finish_duel(duel_id: int, winner_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE duels SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, duel_id))
        await db.commit()

async def db_expire_duels() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE duels SET status = 'expired' WHERE status = 'pending' AND expires_at < ?", (now_ts(),))
        await db.commit()

async def db_mines_create(user_id: int, bet: int, field_json: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO mines_games(user_id, bet, field_json, opened_json, mult, status, created_at) VALUES (?, ?, ?, '[]', 1.0, 'active', ?)",
            (user_id, bet, field_json, now_ts()))
        await db.commit()
        return cursor.lastrowid

async def db_mines_get_active(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mines_games WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1", (user_id,)) as cur:
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

async def db_bonus_item_create(chat_id: int, amount: int, ttl: int = 600) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO bonus_items(chat_id, amount, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (chat_id, amount, now_ts(), now_ts()+ttl))
        await db.commit()
        return cursor.lastrowid

async def db_bonus_item_take(item_id: int, user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bonus_items WHERE id = ?", (item_id,)) as cur:
            row = await cur.fetchone()
            if not row or row["claimed_by"] != 0 or row["expires_at"] < now_ts(): return None
            await db.execute("UPDATE bonus_items SET claimed_by = ? WHERE id = ?", (user_id, item_id))
            await db.commit()
            return row["amount"]

async def db_expire_bonus_items() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bonus_items WHERE expires_at < ? AND claimed_by = 0", (now_ts(),))
        await db.commit()

# ------------------------------------------------------------
#  ЧАТЫ И АВТО-РУЛЕТКА
# ------------------------------------------------------------
async def db_chat_get(chat_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if row: return dict(row)
            return {"chat_id": chat_id, "games_enabled": 1, "disabled_games": "[]", "updated_by": 0}

async def db_chat_toggle_games(chat_id: int, enabled: bool, admin_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO chat_settings(chat_id, games_enabled, updated_by) VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET games_enabled = ?, updated_by = ?""",
            (chat_id, 1 if enabled else 0, admin_id, 1 if enabled else 0, admin_id))
        await db.commit()

async def db_event_chat_add(chat_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO event_chats(chat_id, title, added_at) VALUES (?, ?, ?)", (chat_id, title, now_ts()))
        await db.commit()

async def db_event_chats_all() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM event_chats") as cur:
            return [dict(r) for r in await cur.fetchall()]

async def db_ar_join(chat_id: int, user_id: int, bet: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM roulette_participants WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            if await cur.fetchone(): return False
        await db.execute("INSERT INTO roulette_participants(chat_id, user_id, bet, created_at) VALUES (?, ?, ?, ?)", (chat_id, user_id, bet, now_ts()))
        await db.commit()
        return True

# ============================================================
#  ЧАСТЬ 3: КЛАВИАТУРЫ, ПАРСЕР РУЛЕТКИ, УТИЛИТЫ
# ============================================================

# ------------------------------------------------------------
#  УТИЛИТЫ ИГР И РУЛЕТКИ
# ------------------------------------------------------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

def get_roulette_color(num: int) -> str:
    if num == 0: return "green"
    return "red" if num in RED_NUMBERS else "black"

def parse_roulette_bet(text: str) -> Optional[Dict[str, Any]]:
    text = text.lower().strip()
    m = re.match(r"^(к|ч|красное|черное|red|black)\s+(\d+)$", text)
    if m:
        color = "red" if m.group(1) in ["к", "красное", "red"] else "black"
        return {"amount": int(m.group(2)), "type": "color", "target": [color], "text": "🔴 красное" if color == "red" else "⚫ чёрное"}
    m = re.match(r"^(\d+)\s+(чет|нечет|чёт|нечёт|even|odd)$", text)
    if m:
        is_even = m.group(2) in ["чет", "чёт", "even"]
        return {"amount": int(m.group(1)), "type": "parity", "target": ["even" if is_even else "odd"], "text": "Чёт" if is_even else "Нечет"}
    m = re.match(r"^(0|зеро|zero)\s+(\d+)$", text)
    if m: return {"amount": int(m.group(2)), "type": "number", "target": [0], "text": "🟢 Зеро (0)"}
    
    parts = text.split()
    if not parts: return None
    amount = 0
    targets = []
    for part in parts:
        part = part.strip(",")
        if part.isdigit() and amount == 0: amount = int(part)
        elif part.isdigit(): targets.append(int(part))
        elif "-" in part:
            try:
                s, e = map(int, part.split("-"))
                if 0 <= s <= e <= 36: targets.extend(range(s, e+1))
            except: pass
    if amount > 0 and targets:
        targets = list(set(targets))
        if len(targets) > 4: return {"amount": amount, "type": "range", "target": targets, "text": f"Диапазон ({len(targets)})"}
        else: return {"amount": amount, "type": "number", "target": targets, "text": f"Числа: {', '.join(map(str, targets))}"}
    return None

def calc_roulette_win(bet_info: Dict[str, Any], result_num: int) -> Tuple[int, float]:
    amount, t_type, targets = bet_info["amount"], bet_info["type"], bet_info["target"]
    if t_type == "color" and get_roulette_color(result_num) == targets[0]: return amount * 2, 2.0
    elif t_type == "parity":
        is_even = (result_num % 2 == 0) and result_num != 0
        if (targets[0] == "even" and is_even) or (targets[0] == "odd" and not is_even and result_num != 0): return amount * 2, 2.0
    elif t_type == "number" and result_num in targets: return amount * 36, 36.0
    elif t_type == "range" and result_num in targets: return amount * 3, 3.0
    return 0, 0.0

def check_bet(user: Dict[str, Any], amount: int) -> Tuple[bool, str]:
    if user.get("banned"): return False, get_text("error_banned", user.get("lang", "ru"))
    if amount < MIN_BET: return False, get_text("error_bet_min", user.get("lang", "ru"), min_bet=fmt_money(MIN_BET))
    if amount > MAX_BET: return False, get_text("error_bet_max", user.get("lang", "ru"), max_bet=fmt_money(MAX_BET))
    if user["balance"] < amount: return False, get_text("error_no_money", user.get("lang", "ru"), balance=fmt_money(user["balance"]))
    return True, ""

# ------------------------------------------------------------
#  ОТПРАВКА СООБЩЕНИЙ И ЮЗЕРЫ
# ------------------------------------------------------------
async def send_photo_or_text(msg: Message, photo_path: str, caption: str, kb=None):
    if photo_path and os.path.exists(photo_path):
        try: await msg.answer_photo(FSInputFile(photo_path), caption=caption, reply_markup=kb); return
        except: pass
    await msg.answer(caption, reply_markup=kb)

async def clean_and_send(msg: Message, text: str, kb=None, is_photo: str = None):
    if msg.chat.type == ChatType.PRIVATE:
        try: await msg.delete()
        except: pass
    if is_photo: await send_photo_or_text(msg, is_photo, text, kb)
    else: await msg.answer(text, reply_markup=kb)

async def ensure_user(msg: Message) -> Dict[str, Any]:
    u = await db_get_user(msg.from_user.id)
    if u:
        await db_save_user(msg.from_user.id, last_seen=now_ts(), username=msg.from_user.username or "")
        return u
    ref_id = 0
    if msg.text and msg.text.startswith("/start "):
        arg = msg.text.split(maxsplit=1)[1].strip()
        if arg.startswith("ref") and arg[3:].isdigit(): ref_id = int(arg[3:])
    return await db_create_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "", ref_id)

class DonateStates(StatesGroup):
    custom_amount = State()

class MinesStates(StatesGroup):
    playing = State()

# ------------------------------------------------------------
#  КЛАВИАТУРЫ
# ------------------------------------------------------------
def main_menu(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=get_text("menu_how_to_play", lang)), KeyboardButton(text=get_text("menu_bonus", lang))],
        [KeyboardButton(text=get_text("menu_donate", lang)), KeyboardButton(text=get_text("menu_profile", lang))],
        [KeyboardButton(text=get_text("menu_clan", lang)), KeyboardButton(text=get_text("menu_ref", lang))],
        [KeyboardButton(text=get_text("menu_top", lang)), KeyboardButton(text=get_text("menu_chats", lang))],
        [KeyboardButton(text=get_text("menu_support", lang)), KeyboardButton(text=get_text("menu_commands", lang))],
    ], resize_keyboard=True)

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]])

def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Настройки", callback_data="prof_settings")],
        [InlineKeyboardButton(text="📜 История", callback_data="prof_history"), InlineKeyboardButton(text="📊 Статистика", callback_data="prof_stats")],
        [InlineKeyboardButton(text="💸 Переводы", callback_data="prof_transfers"), InlineKeyboardButton(text="💰 Выигрыши/Проигрыши", callback_data="prof_winlose")],
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
        [InlineKeyboardButton(text="⭐ 50 → 375 000", callback_data="buy_stars_50"), InlineKeyboardButton(text="⭐ 100 → 750 000", callback_data="buy_stars_100")],
        [InlineKeyboardButton(text="⭐ 500 → 3 750 000", callback_data="buy_stars_500"), InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_custom")],
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
        [InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"), InlineKeyboardButton(text="🏆 По выигрышу", callback_data="top_win")],
        [InlineKeyboardButton(text="🛡 Топ кланов", callback_data="top_clans")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def ref_kb(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={link}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]])

def chats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Ивент-чат (Онли)", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="💬 Основной чат", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="📢 Канал", url="https://t.me/+ВАША_ССЫЛКА")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])

def cancel_fsm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Отменить", callback_data="cancel_fsm")]])

def mines_kb(field: list, opened: list, finished: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened: row.append(InlineKeyboardButton(text="💥" if field[idx] else "💎", callback_data="noop"))
            elif finished: row.append(InlineKeyboardButton(text="⬛", callback_data="noop"))
            else: row.append(InlineKeyboardButton(text="⬜", callback_data=f"mine_open_{idx}"))
        rows.append(row)
    if not finished and opened: rows.append([InlineKeyboardButton(text="💰 Забрать", callback_data="mine_cashout")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def duel_accept_kb(c_id: int, bet: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚔️ Принять ({fmt_money(bet)})", callback_data=f"duel_acc_{c_id}_{bet}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="duel_dec")]
    ])

def roulette_retry_kb(amount: int, bet_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Повторить ({fmt_money(amount)})", callback_data=f"r_rep_{amount}_{bet_text}"),
         InlineKeyboardButton(text=f"⏫ Удвоить ({fmt_money(amount*2)})", callback_data=f"r_dbl_{amount}_{bet_text}")]
    ])

# ============================================================
#  ЧАСТЬ 4: ВСЕ ИГРЫ (КУБИКИ, СЛОТЫ, МИНЫ, ДУЭЛИ, РУЛЕТКА)
# ============================================================

# ------------------------------------------------------------
#  ОБЩАЯ УТИЛИТА ДЛЯ КУБИКОВ
# ------------------------------------------------------------
async def process_dice_game(msg: Message, game_name: str, emoji: str, win_condition: callable):
    u = await ensure_user(msg)
    args = msg.text.split()
    amount = next((int(a) for a in args if a.isdigit()), 0)
    
    if amount == 0: 
        return await msg.answer("❌ Укажи сумму. Например: <code>кости 1000</code>")
        
    ok, err = check_bet(u, amount)
    if not ok: 
        return await msg.answer(err)
        
    await db_add_balance(msg.from_user.id, -amount, f"bet_{game_name}")
    
    dice_msg = await msg.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5) # Ждем анимацию
    
    value = dice_msg.dice.value
    is_win = win_condition(value)
    win = calc_win(amount * 2, u) if is_win else 0
    
    if is_win: 
        await db_add_balance(msg.from_user.id, win, f"win_{game_name}")
        
    await db_add_history(msg.from_user.id, game_name, amount, win, round(win/amount, 2) if win else 0, f"Выпало {value}")
    
    res_text = f"🎲 Выпало: <b>{value}</b>\n" + (f"🎉 <b>Победа!</b> Ты выиграл <b>{fmt_money(win)} 🪙</b>" if is_win else f"💸 <b>Проигрыш.</b> Ты потерял <b>{fmt_money(amount)} 🪙</b>")
    
    res_msg = await msg.answer(res_text)
    asyncio.create_task(auto_delete(res_msg, GAME_MSG_TIMEOUT))
    try: await dice_msg.delete()
    except: pass

# ------------------------------------------------------------
#  ИГРЫ НА КУБИКАХ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^кости\s+\d+"))
async def game_dice(msg: Message): 
    await process_dice_game(msg, "кости", "🎲", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^дартс\s+\d+"))
async def game_dart(msg: Message): 
    await process_dice_game(msg, "дартс", "🎯", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^баскет\s+\d+"))
async def game_basket(msg: Message): 
    await process_dice_game(msg, "баскет", "🏀", lambda v: v in [3, 4, 5])

@router.message(F.text.regexp(r"(?i)^футбол\s+\d+"))
async def game_football(msg: Message): 
    await process_dice_game(msg, "футбол", "⚽", lambda v: v in [3, 4, 5])

@router.message(F.text.regexp(r"(?i)^боулинг\s+\d+"))
async def game_bowling(msg: Message): 
    await process_dice_game(msg, "боулинг", "🎳", lambda v: v >= 4)

@router.message(F.text.regexp(r"(?i)^бж\s+\d+"))
async def game_bj(msg: Message): 
    await process_dice_game(msg, "бж", "🎲", lambda v: v >= 4)

# ------------------------------------------------------------
#  СЛОТЫ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^слоты\s+\d+"))
async def game_slots(msg: Message):
    u = await ensure_user(msg)
    args = msg.text.split()
    amount = int(args[1])
    
    ok, err = check_bet(u, amount)
    if not ok: return await msg.answer(err)
    
    await db_add_balance(msg.from_user.id, -amount, "bet_slots")
    dice_msg = await msg.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)
    
    value = dice_msg.dice.value
    is_win, mult = False, 0.0
    
    if value == 64: is_win, mult = True, 10.0 # Джекпот
    elif value >= 43: is_win, mult = True, 5.0 # Три одинаковых
    elif value >= 22: is_win, mult = True, 2.0 # Два одинаковых
    
    win = calc_win(int(amount * mult), u) if is_win else 0
    if is_win: await db_add_balance(msg.from_user.id, win, "win_slots")
        
    await db_add_history(msg.from_user.id, "слоты", amount, win, mult, f"Выпало {value}")
    
    res_text = f"🎰 Слоты: <b>{value}</b>\n" + (f"🎉 <b>Победа!</b> Ты выиграл <b>{fmt_money(win)} 🪙</b>" if is_win else f"💸 <b>Проигрыш.</b> Ты потерял <b>{fmt_money(amount)} 🪙</b>")
    
    res_msg = await msg.answer(res_text)
    asyncio.create_task(auto_delete(res_msg, GAME_MSG_TIMEOUT))
    try: await dice_msg.delete()
    except: pass

# ------------------------------------------------------------
#  ИГРА «МИНЫ»
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^мины\s+\d+"))
async def game_mines_start(msg: Message, state: FSMContext):
    u = await ensure_user(msg)
    if await db_mines_get_active(msg.from_user.id): 
        return await msg.answer("⚠️ У тебя уже есть активная игра!")
        
    amount = int(msg.text.split()[1])
    ok, err = check_bet(u, amount)
    if not ok: return await msg.answer(err)
    
    await db_add_balance(msg.from_user.id, -amount, "bet_mines")
    
    field = [False] * 25
    for _ in range(3):
        i = random.randint(0, 24)
        while field[i]: i = random.randint(0, 24)
        field[i] = True
        
    gid = await db_mines_create(msg.from_user.id, amount, json.dumps(field))
    await state.set_state(MinesStates.playing)
    await state.update_data(gid=gid, field=field, opened=[], bet=amount)
    
    await msg.answer(f"💣 <b>Мины</b>\nСтавка: {fmt_money(amount)} 🪙\nНайди безопасные клетки и забери выигрыш!", reply_markup=mines_kb(field, []))

@router.callback_query(F.data.startswith("mine_open_"))
async def cb_mine_open(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("gid"): return await cb.answer("Игра не найдена", show_alert=True)
    
    idx = int(cb.data.split("_")[-1])
    field, opened = data["field"], data["opened"]
    
    if idx in opened: return await cb.answer("Уже открыто")
    opened.append(idx)
    
    if field[idx]: # Попал на мину
        await db_mines_finish(data["gid"], "busted")
        await db_add_history(cb.from_user.id, "мины", data["bet"], 0, 0, "Взорвался")
        await state.clear()
        await cb.message.edit_text(f"💥 <b>БУМ!</b> Ты наткнулся на мину.\nПроигрыш: {fmt_money(data['bet'])} 🪙", reply_markup=mines_kb(field, opened, True))
        await cb.answer("Ты взорвался!")
        return
        
    mult = 1.0 + (len(opened) * 0.15)
    await db_mines_update(data["gid"], json.dumps(opened), mult)
    await state.update_data(opened=opened)
    
    if len(opened) == 22: 
        return await cb_mine_cashout(cb, state)
        
    await cb.message.edit_text(f"💣 <b>Мины</b>\nСтавка: {fmt_money(data['bet'])} 🪙\nВыигрыш: {fmt_money(int(data['bet'] * mult))} 🪙 (x{mult:.2f})", reply_markup=mines_kb(field, opened))
    await cb.answer("Безопасно!")

@router.callback_query(F.data == "mine_cashout")
async def cb_mine_cashout(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("opened"): 
        return await cb.answer("Открой хотя бы одну клетку!", show_alert=True)
        
    mult = 1.0 + (len(data["opened"]) * 0.15)
    win = calc_win(int(data["bet"] * mult), await db_get_user(cb.from_user.id))
    
    await db_add_balance(cb.from_user.id, win, "win_mines")
    await db_mines_finish(data["gid"], "cashed")
    await db_add_history(cb.from_user.id, "мины", data["bet"], win, round(win/data["bet"], 2), "Забрал")
    await state.clear()
    
    await cb.message.edit_text(f"💰 <b>Ты забрал выигрыш!</b>\n\n+{fmt_money(win)} 🪙", reply_markup=mines_kb(data["field"], data["opened"], True))
    await cb.answer("Выигрыш зачислен!")

# ------------------------------------------------------------
#  ДУЭЛИ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^дуэль\s+@\w+\s+\d+"))
async def game_duel_start(msg: Message):
    u = await ensure_user(msg)
    args = msg.text.split()
    amount = int(args[2])
    
    ok, err = check_bet(u, amount)
    if not ok: return await msg.answer(err)
    
    target = await db_find_user(args[1].lstrip("@"))
    if not target or target["user_id"] == msg.from_user.id or target["balance"] < amount: 
        return await msg.answer("❌ Ошибка вызова (мало средств или себя вызвал).")
        
    await db_add_balance(msg.from_user.id, -amount, "duel_bet")
    await msg.answer(f"⚔️ <b>Вызов на дуэль!</b>\n\n👤 <b>{msg.from_user.first_name}</b> вызывает <b>{target['first_name']}</b>\n💰 Ставка: <b>{fmt_money(amount)} 🪙</b>", reply_markup=duel_accept_kb(msg.from_user.id, amount))

@router.callback_query(F.data.startswith("duel_acc_"))
async def cb_duel_accept(cb: CallbackQuery):
    _, _, c_id, bet = cb.data.split("_")
    c_id, bet = int(c_id), int(bet)
    
    if (await db_get_user(cb.from_user.id))["balance"] < bet: 
        return await cb.answer("❌ Недостаточно средств!", show_alert=True)
        
    await db_add_balance(cb.from_user.id, -bet, "duel_bet")
    await cb.message.edit_text("⚔️ <b>Дуэль началась!</b> Бросаем кубики...")
    
    m1 = await cb.message.answer_dice(emoji="🎲")
    m2 = await cb.message.answer_dice(emoji="🎲")
    await asyncio.sleep(3.5)
    
    v1, v2 = m1.dice.value, m2.dice.value
    bank = int(bet * 2 * (1 - DUEL_COMMISSION))
    
    if v1 == v2:
        await db_add_balance(c_id, bet, "duel_refund")
        await db_add_balance(cb.from_user.id, bet, "duel_refund")
        return await cb.message.answer(f"🤝 <b>Ничья!</b> ({v1} - {v2}). Ставки возвращены.")
        
    winner = c_id if v1 > v2 else cb.from_user.id
    await db_add_balance(winner, bank, "duel_win")
    await cb.message.answer(f"⚔️ <b>Дуэль окончена!</b>\n🎲 Вызывающий: <b>{v1}</b>\n🎲 Принявший: <b>{v2}</b>\n\n🏆 Победитель забрал <b>{fmt_money(bank)} 🪙</b>")

@router.callback_query(F.data == "duel_dec")
async def cb_duel_decline(cb: CallbackQuery):
    await cb.message.edit_text("❌ Дуэль отклонена.")

# ------------------------------------------------------------
#  РУЛЕТКА (МГНОВЕННЫЙ ПАРСЕР)
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^(к|ч|красное|черное|red|black)\s+\d+$"))
@router.message(F.text.regexp(r"(?i)^\d+\s+(чет|нечет|чёт|нечёт|even|odd)$"))
@router.message(F.text.regexp(r"(?i)^(0|зеро|zero)\s+\d+$"))
@router.message(F.text.regexp(r"(?i)^\d+\s+[\d\-, ]+$"))
async def game_roulette(msg: Message):
    chat_cfg = await db_chat_get(msg.chat.id)
    if not chat_cfg["games_enabled"]:
        warn = await msg.answer("⚠️ <b>Игры в этом чате временно отключены администратором!</b>")
        asyncio.create_task(auto_delete(warn, 5))
        return
        
    u = await ensure_user(msg)
    bet = parse_roulette_bet(msg.text)
    if not bet: return
    
    ok, err = check_bet(u, bet["amount"])
    if not ok: return await msg.answer(err)
    
    await db_add_balance(msg.from_user.id, -bet["amount"], "bet_roulette")
    acc = await msg.answer(f"✅ <b>Ставка принята:</b> {msg.from_user.first_name} {fmt_money(bet['amount'])} на {bet['text']}")
    
    dice = await msg.answer_dice(emoji="🎰")
    await asyncio.sleep(3.5)
    
    num = (dice.dice.value - 1) % 37
    color = get_roulette_color(num)
    c_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]
    
    win, mult = calc_roulette_win(bet, num)
    if win > 0:
        win = calc_win(win, u)
        await db_add_balance(msg.from_user.id, win, "win_roulette")
        res = f"🎯 Выпало: {c_emoji} <b>{num}</b>\n\n💰 <b>{msg.from_user.first_name}</b> выиграл <b>{fmt_money(win)} 🪙</b>!"
    else:
        res = f"🎯 Выпало: {c_emoji} <b>{num}</b>\n\n💸 <b>{msg.from_user.first_name}</b> проиграл <b>{fmt_money(bet['amount'])} 🪙</b>."
        
    await db_add_history(msg.from_user.id, "рулетка", bet["amount"], win, mult, f"Выпало {num}")
    await db_add_roulette_log(msg.chat.id, msg.from_user.id, bet["amount"], win, str(num), color)
    
    await msg.answer(res, reply_markup=roulette_retry_kb(bet["amount"], bet["text"]))
    asyncio.create_task(auto_delete(acc, 10))
    try: await dice.delete()
    except: pass

@router.callback_query(F.data.startswith("r_"))
async def cb_roulette_retry(cb: CallbackQuery):
    action, amt, txt = cb.data.split("_", 2)
    amt = int(amt) * (2 if action == "dbl" else 1)
    await cb.message.delete()
    await bot.send_message(cb.message.chat.id, f"{txt.split()[0]} {amt}" if " " in txt else f"{amt} {txt}")

# ============================================================
#  ЧАСТЬ 5: КОМАНДЫ, МЕНЮ И ПРОФИЛЬ
# ============================================================

# ------------------------------------------------------------
#  ГЛАВНОЕ МЕНЮ И НАВИГАЦИЯ
# ------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    if u.get("banned"): return await msg.answer(get_text("error_banned", u.get("lang", "ru")))
    lang = u.get("lang", "ru")
    text = get_text("start_text", lang, name=msg.from_user.first_name, balance=fmt_money(u["balance"]))
    await clean_and_send(msg, text, main_menu(lang), IMG_START)

@router.callback_query(F.data == "nav_menu")
async def cb_nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await cb.message.delete()
    except: pass
    u = await db_get_user(cb.from_user.id)
    await cb.message.answer("🏠 Главное меню", reply_markup=main_menu(u.get("lang", "ru") if u else "ru"))
    await cb.answer()

@router.callback_query(F.data == "cancel_fsm")
async def cb_cancel_fsm(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    u = await db_get_user(cb.from_user.id)
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(get_text("cancel_success", u.get("lang", "ru") if u else "ru"), reply_markup=main_menu(u.get("lang", "ru") if u else "ru"))
    await cb.answer("Отменено")

# ------------------------------------------------------------
#  ПРОФИЛЬ
# ------------------------------------------------------------
async def render_profile_text(user: Dict[str, Any]) -> str:
    lang = user.get("lang", "ru")
    vip = get_text("vip_none", lang)
    if is_vip(user): vip = get_text("vip_active", lang, days=max(1, (user["vip_until"] - now_ts()) // 86400))
    clan = get_text("clan_none", lang)
    if user.get("clan_id"):
        c = await db_get_clan(user["clan_id"])
        if c: clan = c["name"]
    return get_text("profile_text", lang, user_id=user["user_id"], name=user.get("first_name", "—"),
        balance=fmt_money(user["balance"]), vip=vip, clan=clan, games=user.get("games_played", 0), 
        total_bet=fmt_money(user.get("total_bet", 0)), total_win=fmt_money(user.get("total_win", 0)))

@router.message(F.text.in_([get_text("menu_profile", "ru"), get_text("menu_profile", "en")]))
async def profile_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    await clean_and_send(msg, await render_profile_text(u), profile_kb(), IMG_PROFILE)

@router.callback_query(F.data == "prof_back")
async def cb_prof_back(cb: CallbackQuery):
    u = await db_get_user(cb.from_user.id)
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_PROFILE, await render_profile_text(u), profile_kb())
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
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_PROFILE, await render_profile_text(u), profile_kb())
    await cb.message.answer("Language changed / Язык изменен", reply_markup=main_menu(new_lang))
    await cb.answer()

@router.callback_query(F.data == "prof_history")
async def cb_prof_history(cb: CallbackQuery):
    hist = await db_get_history(cb.from_user.id, 10)
    lines = ["📜 <b>Последние игры:</b>\n"]
    for h in hist: lines.append(f"{'🟢' if h['win']>0 else '🔴'} {h['game']} | {fmt_money(h['bet'])} -> {fmt_money(h['win'])}")
    await cb.message.answer("\n".join(lines) if hist else "История пуста", reply_markup=back_kb())
    await cb.answer()

# ------------------------------------------------------------
#  ДОНАТ И VIP
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_donate", "ru"), get_text("menu_donate", "en")]))
async def donate_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    text = f"💎 <b>Магазин TOKENS</b>\n\nТекущий курс: <b>1 ⭐ = {fmt_money(STAR_RATE)} TOKENS</b>\n\n👑 <b>VIP-подписка</b> — от 5 ⭐ (+3% к выигрышу)\n\n👇 Выбери пакет:"
    await clean_and_send(msg, text, donate_kb(), IMG_DONATE)

@router.callback_query(F.data == "nav_donate")
async def cb_nav_donate(cb: CallbackQuery):
    text = f"💎 <b>Магазин TOKENS</b>\n\nТекущий курс: <b>1 ⭐ = {fmt_money(STAR_RATE)} TOKENS</b>\n\n👇 Выбери пакет:"
    try: await cb.message.delete()
    except: pass
    await send_photo_or_text(cb.message, IMG_DONATE, text, donate_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("buy_stars_"))
async def cb_buy_stars(cb: CallbackQuery):
    stars = int(cb.data.split("_")[-1])
    await bot.send_invoice(cb.from_user.id, title=f"{stars} ⭐", description=f"Покупка {fmt_money(stars*STAR_RATE)} TOKENS",
        payload=f"stars_{stars*STAR_RATE}", provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)])
    await cb.answer()

@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(cb: CallbackQuery, state: FSMContext):
    await state.set_state(DonateStates.custom_amount)
    await cb.message.answer("✍️ Напиши, сколько звезд купить (1-1000):", reply_markup=cancel_fsm_kb())
    await cb.answer()

@router.message(DonateStates.custom_amount)
async def process_custom_amount(msg: Message, state: FSMContext):
    if not msg.text.isdigit() or not (1 <= int(msg.text) <= 1000):
        return await msg.answer("❌ Введи число от 1 до 1000.")
    await state.clear()
    stars = int(msg.text)
    await bot.send_invoice(msg.from_user.id, title=f"{stars} ⭐", description=f"Покупка {fmt_money(stars*STAR_RATE)} TOKENS",
        payload=f"stars_{stars*STAR_RATE}", provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{stars} ⭐", amount=stars)])

@router.callback_query(F.data == "vip_menu")
async def cb_vip_menu(cb: CallbackQuery):
    try: await cb.message.edit_caption(caption="👑 <b>VIP-подписка</b>\n\n+3% к выигрышу. Выбери срок:", reply_markup=vip_kb())
    except: await cb.message.edit_text("👑 <b>VIP-подписка</b>\n\n+3% к выигрышу. Выбери срок:", reply_markup=vip_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("vip_buy_"))
async def cb_vip_buy(cb: CallbackQuery):
    days = int(cb.data.split("_")[-1])
    await bot.send_invoice(cb.from_user.id, title=f"👑 VIP на {days} дн.", description="+3% к выигрышу",
        payload=f"vip_{days}", provider_token="", currency="XTR", prices=[LabeledPrice(label="VIP", amount=VIP_PRICES.get(days, 5))])
    await cb.answer()

@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await pcq.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(msg: Message):
    payload = msg.successful_payment.invoice_payload
    if payload.startswith("stars_"):
        coins = int(payload.split("_")[-1])
        await db_add_balance(msg.from_user.id, coins, "donate")
        await msg.answer(f"✅ Оплата прошла!\n💰 +{fmt_money(coins)} TOKENS", reply_markup=back_kb())
    elif payload.startswith("vip_"):
        days = int(payload.split("_")[-1])
        await db_set_vip(msg.from_user.id, days)
        await msg.answer(f"👑 VIP активирован на {days} дней!", reply_markup=back_kb())

# ------------------------------------------------------------
#  ТОП, РЕФЕРАЛКА, ЧАТЫ, КОМАНДЫ
# ------------------------------------------------------------
@router.message(F.text.in_([get_text("menu_top", "ru"), get_text("menu_top", "en")]))
@router.message(F.text.regexp(r"(?i)^топ$"))
async def top_handler(msg: Message, state: FSMContext):
    await state.clear()
    await ensure_user(msg)
    top = await db_top_users(10, "balance")
    lines = ["🏆 <b>Топ по балансу:</b>\n"] + [f"{'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else str(i+1)+'.'} <b>{u.get('first_name') or 'ID'+str(u['user_id'])}</b> — {fmt_money(u['balance'])}" for i, u in enumerate(top)]
    await clean_and_send(msg, "\n".join(lines), top_kb(), IMG_TOP)

@router.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: CallbackQuery):
    top = await db_top_users(10, "balance")
    lines = ["🏆 <b>Топ по балансу:</b>\n"] + [f"{i+1}. <b>{u.get('first_name')}</b> — {fmt_money(u['balance'])}" for i, u in enumerate(top)]
    try: await cb.message.edit_caption(caption="\n".join(lines), reply_markup=top_kb())
    except: await cb.message.edit_text("\n".join(lines), reply_markup=top_kb())
    await cb.answer()

@router.message(F.text.in_([get_text("menu_ref", "ru"), get_text("menu_ref", "en")]))
async def ref_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{msg.from_user.id}"
    text = f"🔗 <b>Реферальная система</b>\n\n👥 Приглашено: <b>{u.get('ref_count', 0)}</b>\n\n🔗 Твоя ссылка:\n<code>{link}</code>"
    await clean_and_send(msg, text, ref_kb(link), IMG_REF)

@router.message(F.text.in_([get_text("menu_chats", "ru"), get_text("menu_chats", "en")]))
async def chats_handler(msg: Message, state: FSMContext):
    await state.clear()
    await ensure_user(msg)
    await clean_and_send(msg, "💬 <b>Официальные чаты TOKENS</b>\n\nЗаходи и общайся!", chats_kb(), IMG_CHATS)

@router.message(F.text.in_([get_text("menu_commands", "ru"), get_text("menu_commands", "en")]))
async def commands_handler(msg: Message, state: FSMContext):
    await state.clear()
    await ensure_user(msg)
    text = "📖 <b>ШПАРГАЛКА</b>\n\n• <code>б</code> — баланс\n• <code>перевод @user 1000</code>\n• <code>топ</code> — топ\n• <code>лог</code> — лог рулетки\n• <code>курс</code> — курсы\n• <code>промо КОД</code>\n• <code>отмена</code> — сброс"
    await clean_and_send(msg, text, None, IMG_COMMANDS)

@router.message(F.text.in_([get_text("menu_clan", "ru"), get_text("menu_clan", "en")]))
async def clan_handler(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg)
    if u.get("clan_id"):
        c = await db_get_clan(u["clan_id"])
        if c:
            count = await db_clan_member_count(c["clan_id"])
            text = f"🛡 <b>Клан: {c['name']}</b>\n\n👥 Участников: <b>{count}</b>\n💰 Казна: <b>{fmt_money(c['balance'])}</b>\n\nКод: <code>{c['invite_code']}</code>"
            return await clean_and_send(msg, text, back_kb())
    text = f"🛡 <b>Кланы</b>\n\nСоздание: <b>{fmt_money(CLAN_CREATE_COST)}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Создать", callback_data="clan_create")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]])
    await clean_and_send(msg, text, kb)

# ------------------------------------------------------------
#  КОМАНДЫ И ПЕРЕВОДЫ
# ------------------------------------------------------------
@router.message(F.text.regexp(r"(?i)^(б|баланс)(\s+.*)?$"))
async def cmd_balance(msg: Message):
    await ensure_user(msg)
    parts = msg.text.split()
    target = await db_find_user(parts[1]) if len(parts) > 1 else await db_get_user(msg.from_user.id)
    if not target: return await msg.answer("❌ Не найден")
    await msg.answer(f"💰 <b>{target.get('first_name')}</b>: {fmt_money(target['balance'])} TOKENS")

@router.message(F.text.regexp(r"(?i)^(лог|логи)$"))
async def cmd_log(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        hist = await db_get_history(msg.from_user.id)
        lines = [f"{'🟢' if h['win']>0 else '🔴'} {h['game']} | {fmt_money(h['bet'])} -> {fmt_money(h['win'])}" for h in hist]
        return await msg.answer("📜 <b>История:</b>\n" + "\n".join(lines) if lines else "Пусто")
    logs = await db_roulette_logs(msg.chat.id)
    lines = [f"{ {'red':'🔴','black':'⚫','green':'🟢'}.get(r.get('color'),'⚪') } {r['numbers']}" for r in reversed(logs)]
    await msg.answer("📜 <b>Последние числа:</b>\n" + "\n".join(lines) if lines else "Пусто")

@router.message(F.text.regexp(r"(?i)^курс$"))
async def cmd_course(msg: Message):
    c = await db_get_courses()
    await msg.answer("💱 <b>Курсы:</b>\n" + "\n".join([f"• {k}: {fmt_money(v)}" for k, v in c.items()]))

@router.message(F.text.regexp(r"(?i)^(перевод|перевести|подарить|pay)\s+\S+\s+\d+$"))
async def cmd_transfer(msg: Message):
    parts = msg.text.split()
    amount = int(parts[2])
    u = await ensure_user(msg)
    if amount < MIN_BET: return await msg.answer(f"❌ Мин: {fmt_money(MIN_BET)}")
    target = await db_find_user(parts[1])
    if not target or target["user_id"] == msg.from_user.id or u["balance"] < amount: 
        return await msg.answer("❌ Ошибка перевода (мало средств или себя выбрал)")
    await msg.answer(f"💸 Перевод <b>{fmt_money(amount)}</b> для <b>{target['first_name']}</b>?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"tr_yes_{target['user_id']}_{amount}"),
        InlineKeyboardButton(text="❌ Нет", callback_data="tr_no")]]))

@router.callback_query(F.data.startswith("tr_yes_"))
async def cb_transfer_yes(cb: CallbackQuery):
    _, _, t_id, amt = cb.data.split("_")
    t_id, amt = int(t_id), int(amt)
    if (await db_get_user(cb.from_user.id))["balance"] < amt: return await cb.answer("Мало средств", show_alert=True)
    await db_add_balance(cb.from_user.id, -amt, "tr_out")
    await db_add_balance(t_id, amt, "tr_in")
    await cb.message.edit_text(f"✅ Переведено {fmt_money(amt)}")
    try: await bot.send_message(t_id, f"💸 Тебе перевели {fmt_money(amt)} TOKENS!")
    except: pass

@router.callback_query(F.data == "tr_no")
async def cb_transfer_no(cb: CallbackQuery):
    await cb.message.edit_text("❌ Отменено")

@router.message(F.text.regexp(r"(?i)^промо\s+\w+$"))
async def cmd_promo(msg: Message):
    amt = await db_redeem_promo(msg.text.split()[1].upper(), msg.from_user.id)
    if amt == -1: return await msg.answer("❌ Уже активирован")
    if amt is None: return await msg.answer("❌ Неверный код")
    await db_add_balance(msg.from_user.id, amt, "promo")
    await msg.answer(f"🎉 +{fmt_money(amt)} TOKENS")

# ------------------------------------------------------------
#  ФОЛБЭК (ЕСЛИ БОТ НЕ ПОНЯЛ)
# ------------------------------------------------------------
@router.message()
async def fallback(msg: Message):
    if msg.chat.type == ChatType.PRIVATE and msg.text and not msg.text.startswith("/"):
        u = await db_get_user(msg.from_user.id)
        if u: await msg.answer(get_text("not_understood", u.get("lang", "ru")))