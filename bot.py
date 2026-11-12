import asyncio
import logging
import os
import random
import time
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Any
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, PreCheckoutQuery, LabeledPrice, ChatMemberUpdated
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendDice
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = "tokens.db"
IMAGES_DIR = "images"
CACHE_TTL = 5.0
GAME_COOLDOWN = 3.0
MIN_BET = 10
MAX_BET = 1_000_000
DEFAULT_BALANCE = 1000
DAILY_BONUS = 500
VIP_PRICE = 50_000
VIP_DAYS = 30
VIP_BONUS = 0.05
DUEL_COMMISSION = 0.05
HAPPY_HOUR_MULT = 2.0
ROULETTE_PAUSE = 3.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("TOKENS")

if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
        log.info("Database removed on startup")
    except Exception as e:
        log.error(f"Failed to remove DB: {e}")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler(timezone="UTC")

_user_cache: dict[int, tuple[float, dict]] = {}
_cache_lock = asyncio.Lock()
_game_locks: dict[int, asyncio.Lock] = {}
_last_game: dict[int, float] = {}
_double_spend: set[int] = set()
_roulette_lock = asyncio.Lock()
_duel_lock = asyncio.Lock()
_active_mines: dict[int, dict] = {}
_active_roulettes: dict[int, dict] = {}
_active_duels: dict[int, dict] = {}
_games_enabled = True
_current_rate = 1.0
_happy_hour = False
_jackpot_pool = 0

GAMES_MAP = {
    "кости": "🎲", "дартс": "🎯", "баскет": "🏀",
    "футбол": "⚽", "боулинг": "🎳", "бж": "🎰", "слоты": "🎰"
}

def fmt(num: int | float) -> str:
    try:
        return f"{int(num):,}".replace(",", " ")
    except Exception:
        return str(num)

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")

def today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

def get_game_lock(uid: int) -> asyncio.Lock:
    if uid not in _game_locks:
        _game_locks[uid] = asyncio.Lock()
    return _game_locks[uid]

def is_on_cooldown(uid: int) -> bool:
    last = _last_game.get(uid, 0)
    return (time.time() - last) < GAME_COOLDOWN

def set_cooldown(uid: int) -> None:
    _last_game[uid] = time.time()

async def safe_send(chat_id: int, text: str, markup: Optional[Any] = None, **kwargs) -> Optional[Message]:
    try:
        if len(text) <= 4000:
            return await bot.send_message(chat_id, text, reply_markup=markup, **kwargs)
        parts = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > 4000:
                parts.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            parts.append(current)
        sent = None
        for i, part in enumerate(parts):
            m = markup if i == len(parts) - 1 else None
            sent = await bot.send_message(chat_id, part, reply_markup=m, **kwargs)
        return sent
    except TelegramForbiddenError:
        log.warning(f"Bot blocked by {chat_id}")
    except TelegramBadRequest as e:
        log.warning(f"BadRequest send to {chat_id}: {e}")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await bot.send_message(chat_id, text[:4000], reply_markup=markup, **kwargs)
        except Exception as ex:
            log.error(f"Retry failed: {ex}")
    except Exception as e:
        log.error(f"safe_send error to {chat_id}: {e}")
    return None

async def safe_edit(cb: CallbackQuery, text: str, markup: Optional[Any] = None) -> bool:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return True
        log.warning(f"edit error: {e}")
    except Exception as e:
        log.error(f"safe_edit error: {e}")
    return False

async def safe_photo(chat_id: int, path: str, caption: str = "", markup: Optional[Any] = None) -> Optional[Message]:
    try:
        full = os.path.join(IMAGES_DIR, path)
        if not os.path.exists(full):
            return await safe_send(chat_id, caption or " ", markup)
        return await bot.send_photo(chat_id, FSInputFile(full), caption=caption[:1000] if caption else None, reply_markup=markup)
    except Exception as e:
        log.error(f"safe_photo error: {e}")
        try:
            return await safe_send(chat_id, caption or " ", markup)
        except Exception:
            return None

async def safe_dice(chat_id: int, emoji: str) -> Optional[Message]:
    try:
        return await bot.send_dice(chat_id, emoji=emoji)
    except Exception as e:
        log.error(f"safe_dice error: {e}")
        return None

async def safe_delete(chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def safe_reply(msg: Message, text: str, markup: Optional[Any] = None) -> Optional[Message]:
    try:
        return await msg.reply(text, reply_markup=markup)
    except Exception as e:
        log.error(f"safe_reply error: {e}")
        return None

def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="🎮 Игры"), KeyboardButton(text="🎁 Бонус"))
    kb.row(KeyboardButton(text="💎 Донат"), KeyboardButton(text="👤 Профиль"))
    kb.row(KeyboardButton(text="🛡 Клан"), KeyboardButton(text="🏆 Топ"))
    kb.row(KeyboardButton(text="💬 Чаты"), KeyboardButton(text="🆘 Поддержка"))
    return kb.as_markup(resize_keyboard=True)

def back_inline(cb_data: str = "back_main") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="◀ Назад", callback_data=cb_data)
    return kb.as_markup()

async def db_init() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance INTEGER DEFAULT 1000,
            games_played INTEGER DEFAULT 0,
            games_won INTEGER DEFAULT 0,
            total_won INTEGER DEFAULT 0,
            total_lost INTEGER DEFAULT 0,
            vip_until TEXT DEFAULT NULL,
            banned INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'ru',
            hide_balance INTEGER DEFAULT 0,
            block_transfers INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            clan_id INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            games_enabled INTEGER DEFAULT 1,
            roulette_enabled INTEGER DEFAULT 1,
            duels_enabled INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            bet TEXT,
            win INTEGER DEFAULT 0,
            amount INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS games_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game TEXT,
            bet INTEGER,
            result INTEGER,
            win_amount INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bonus_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item TEXT,
            amount INTEGER DEFAULT 0,
            claimed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id INTEGER PRIMARY KEY,
            last_claim TEXT DEFAULT NULL,
            streak INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            uses_left INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS promo_used (
            user_id INTEGER,
            code TEXT,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, code)
        );
        CREATE TABLE IF NOT EXISTS clans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            owner_id INTEGER,
            balance INTEGER DEFAULT 0,
            members INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger INTEGER,
            opponent INTEGER,
            bet INTEGER,
            status TEXT DEFAULT 'pending',
            winner INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bet INTEGER,
            field TEXT,
            opened TEXT,
            won INTEGER DEFAULT 0,
            payout INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance);
        CREATE INDEX IF NOT EXISTS idx_games_user ON games_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_games_created ON games_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_roulette_user ON roulette_logs(user_id);
        CREATE INDEX IF NOT EXISTS idx_roulette_chat ON roulette_logs(chat_id);
        CREATE INDEX IF NOT EXISTS idx_promo_used_user ON promo_used(user_id);
        CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
        CREATE INDEX IF NOT EXISTS idx_duels_status ON duels(status);
        CREATE INDEX IF NOT EXISTS idx_event_active ON event_chats(active);
        """)
        await db.commit()
    log.info("Database initialized")

async def get_user(user_id: int, use_cache: bool = True) -> dict:
    if use_cache:
        async with _cache_lock:
            cached = _user_cache.get(user_id)
            if cached and (time.time() - cached[0]) < CACHE_TTL:
                return dict(cached[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, balance) VALUES (?, ?)",
                (user_id, DEFAULT_BALANCE)
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
    data = dict(row) if row else {}
    async with _cache_lock:
        _user_cache[user_id] = (time.time(), dict(data))
    return data

def invalidate_user_cache(user_id: int) -> None:
    _user_cache.pop(user_id, None)

async def update_balance(user_id: int, delta: int) -> int:
    invalidate_user_cache(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = MAX(0, balance + ?), last_seen=? WHERE user_id=?",
            (delta, now_iso(), user_id)
        )
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0

async def set_user_field(user_id: int, field: str, value: Any) -> None:
    allowed = {"username", "first_name", "lang", "hide_balance", "block_transfers",
               "vip_until", "banned", "clan_id"}
    if field not in allowed:
        return
    invalidate_user_cache(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
        await db.commit()

async def log_game(user_id: int, game: str, bet: int, result: int, win_amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO games_log (user_id, game, bet, result, win_amount) VALUES (?,?,?,?,?)",
            (user_id, game, bet, result, win_amount)
        )
        await db.execute(
            "UPDATE users SET games_played = games_played + 1, "
            "games_won = games_won + ?, total_won = total_won + ?, "
            "total_lost = total_lost + ? WHERE user_id=?",
            (1 if result == 1 else 0,
             win_amount if win_amount > 0 else 0,
             bet if result == 0 else 0,
             user_id)
        )
        await db.commit()

async def admin_log(admin_id: int, action: str, target: int = 0, details: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO admin_logs (admin_id, action, target, details) VALUES (?,?,?,?)",
            (admin_id, action, target, details)
        )
        await db.commit()

async def get_chat_settings(chat_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chat_settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO chat_settings (chat_id) VALUES (?)", (chat_id,))
            await db.commit()
            return {"chat_id": chat_id, "games_enabled": 1, "roulette_enabled": 1, "duels_enabled": 1}
    return dict(row)

async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def check_banned(user_id: int) -> bool:
    u = await get_user(user_id)
    return bool(u.get("banned", 0))

async def is_vip(user_id: int) -> bool:
    u = await get_user(user_id)
    vu = u.get("vip_until")
    if not vu:
        return False
    try:
        return datetime.fromisoformat(vu) > datetime.utcnow()
    except Exception:
        return False

async def vip_multiplier(user_id: int) -> float:
    m = 1.0 + (VIP_BONUS if await is_vip(user_id) else 0.0)
    if _happy_hour:
        m *= HAPPY_HOUR_MULT
    return m

async def cooldown_guard(msg: Message) -> bool:
    uid = msg.from_user.id
    if is_on_cooldown(uid):
        await safe_reply(msg, "⏳ <b>Подождите 3 секунды между играми.</b>")
        return False
    return True

def bet_from_message(msg: Message) -> Optional[int]:
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return None
        bet = int(parts[1])
        if bet < MIN_BET or bet > MAX_BET:
            return None
        return bet
    except Exception:
        return None

async def resolve_bet(msg: Message, bet: int) -> bool:
    uid = msg.from_user.id
    if uid in _double_spend:
        await safe_reply(msg, "⚠️ <b>Транзакция уже выполняется.</b>")
        return False
    u = await get_user(uid)
    if u["balance"] < bet:
        await safe_reply(msg, f"❌ <b>Недостаточно средств.</b> Баланс: <code>{fmt(u['balance'])}</code>")
        return False
    return True

async def user_display(user_id: int) -> str:
    u = await get_user(user_id)
    name = u.get("first_name") or u.get("username") or f"ID{user_id}"
    return name

async def log_roulette(chat_id: int, user_id: int, bet: str, win: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO roulette_logs (chat_id, user_id, bet, win, amount) VALUES (?,?,?,?,?)",
            (chat_id, user_id, bet, win, amount)
        )
        await db.commit()

async def get_daily_bonus(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_bonus WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {"user_id": user_id, "last_claim": None, "streak": 0}

async def set_daily_bonus(user_id: int, last_claim: str, streak: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO daily_bonus (user_id, last_claim, streak) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_claim=excluded.last_claim, streak=excluded.streak",
            (user_id, last_claim, streak)
        )
        await db.commit()

async def get_event_chats() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM event_chats WHERE active=1") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def add_event_chat(chat_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO event_chats (chat_id, title, active) VALUES (?,?,1) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, active=1",
            (chat_id, title)
        )
        await db.commit()

async def get_top_balance(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, first_name, username, balance FROM users "
            "WHERE banned=0 ORDER BY balance DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": "TOKENS", "ts": now_iso()})

async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"Web server started on 0.0.0.0:{PORT}")
    return runner

async def on_startup() -> None:
    await db_init()
    if not scheduler.running:
        scheduler.start()
    log.info("Bot startup complete")

# ============================================================
# ЧАСТЬ 2 — ХЕЛПЕРЫ UI, ПРОФИЛЬ, БОНУС, ТОП, ЧАТЫ, КЛАН, ДОНАТ
# ============================================================

async def touch_user(user: Any) -> None:
    """Обновляет username/first_name/last_seen при любом взаимодействии."""
    try:
        if getattr(user, "is_bot", False):
            return
        uid = user.id
        await get_user(uid)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_seen=? WHERE user_id=?",
                (user.username or "", user.first_name or "", now_iso(), uid)
            )
            await db.commit()
        invalidate_user_cache(uid)
    except Exception as e:
        log.error(f"touch_user error: {e}")

async def guard_message(msg: Message) -> bool:
    """Базовая защита: бан + валидность пользователя."""
    try:
        if not msg.from_user or msg.from_user.is_bot:
            return False
        if await check_banned(msg.from_user.id):
            await safe_reply(msg, "🚫 <b>Доступ к клубу ограничен.</b>")
            return False
        await touch_user(msg.from_user)
        return True
    except Exception as e:
        log.error(f"guard_message error: {e}")
        return False

async def guard_callback(cb: CallbackQuery) -> bool:
    try:
        await cb.answer()
    except Exception:
        pass
    if not cb.from_user or cb.from_user.is_bot:
        return False
    if await check_banned(cb.from_user.id):
        await safe_edit(cb, "🚫 <b>Доступ к клубу ограничен.</b>")
        return False
    await touch_user(cb.from_user)
    return True

# ---------- /start ----------
async def cmd_start(msg: Message, command: Optional[CommandObject] = None) -> None:
    try:
        uid = msg.from_user.id
        await get_user(uid)
        await touch_user(msg.from_user)
        u = await get_user(uid)
        deep = (command.args if command and command.args else "").strip().lower()
        bonus_line = ""
        if deep.startswith("promo_"):
            code = deep[6:].upper()
            bonus_line = f"\n\n🎟 Обнаружен промокод: <code>{code}</code>\nОтправьте: <code>промо {code}</code>"
        text = (
            "💠 <b>ДОБРО ПОЖАЛОВАТЬ В TOKENS</b>\n\n"
            "Элитный игровой клуб. Ставки, дуэли, рулетка, кланы.\n"
            "Все операции строго в токенах клуба.\n\n"
            f"👤 Игрок: <b>{msg.from_user.first_name or 'Гость'}</b>\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"💰 Баланс: <code>{fmt(u['balance'])}</code> TOKENS\n"
            f"🎁 Стартовый бонус: <code>{fmt(DEFAULT_BALANCE)}</code> TOKENS зачислен"
            f"{bonus_line}\n\n"
            "Используйте меню ниже для навигации.\n"
            "Справка: /help · Профиль: /profile"
        )
        await safe_photo(msg.chat.id, "start.jpg", text, main_menu_kb())
    except Exception as e:
        log.error(f"cmd_start error: {e}")
        await safe_send(msg.chat.id, "⚠️ Ошибка запуска. Попробуйте /start ещё раз.", main_menu_kb())

# ---------- /help ----------
async def cmd_help(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        text = (
            "📖 <b>СПРАВКА TOKENS</b>\n\n"
            "<b>Стикерные игры (ставка, выигрыш x2 при > 3):</b>\n"
            "<code>кости 1000</code> · <code>дартс 500</code> · <code>баскет 500</code>\n"
            "<code>футбол 500</code> · <code>боулинг 500</code> · <code>бж 500</code> · <code>слоты 500</code>\n\n"
            "<b>Мины:</b> <code>мины 1000</code>\n"
            "<b>Дуэль:</b> <code>дуэль @user 1000</code>\n"
            "<b>Рулетка:</b> ставки → <code>старт</code>\n\n"
            "<b>Ставки рулетки:</b>\n"
            "<code>к 1000</code> — красное · <code>ч 500</code> — чёрное\n"
            "<code>1000 чет</code> / <code>1000 нечет</code>\n"
            "<code>0 100</code> — зеро · <code>1000 1 2 3</code> — числа\n"
            "<code>500 10-20</code> — диапазон\n\n"
            "<b>Экономика:</b> <code>бонус</code> · <code>профиль</code> · <code>топ</code> · <code>промо КОД</code>\n"
            "<b>Кланы:</b> <code>клан создать ИМЯ</code> · <code>клан вступить ID</code> · <code>клан выйти</code>\n\n"
            "<b>Лимиты:</b> ставка от <code>{}</code> до <code>{}</code>, кулдаун <code>{} сек</code>".format(
                fmt(MIN_BET), fmt(MAX_BET), int(GAME_COOLDOWN)
            )
        )
        await safe_send(msg.chat.id, text, back_inline("back_main"))
    except Exception as e:
        log.error(f"cmd_help error: {e}")

# ---------- /profile ----------
async def cmd_profile(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        uid = msg.from_user.id
        u = await get_user(uid)
        games = u.get("games_played", 0) or 0
        won = u.get("games_won", 0) or 0
        wr = (won / games * 100) if games else 0.0
        balance_display = "🔒 скрыт" if u.get("hide_balance") else fmt(u["balance"])
        vip = await is_vip(uid)
        vip_tag = "💎 VIP" if vip else "обычный"
        created = (u.get("created_at") or "")[:10]
        clan_id = u.get("clan_id", 0)
        clan_name = "—"
        if clan_id:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT name FROM clans WHERE id=?", (clan_id,)) as cur:
                    c = await cur.fetchone()
            if c:
                clan_name = c["name"]
        total_won = u.get("total_won", 0) or 0
        total_lost = u.get("total_lost", 0) or 0
        text = (
            "👤 <b>ПРОФИЛЬ ИГРОКА</b>\n\n"
            f"Имя: <b>{u.get('first_name') or 'Гость'}</b>\n"
            f"ID: <code>{uid}</code>\n"
            f"Баланс: <code>{balance_display}</code> TOKENS\n"
            f"Игр: <code>{games}</code> · Побед: <code>{won}</code>\n"
            f"Винрейт: <code>{wr:.1f}%</code>\n"
            f"Всего выиграно: <code>{fmt(total_won)}</code>\n"
            f"Всего проиграно: <code>{fmt(total_lost)}</code>\n"
            f"Клан: <b>{clan_name}</b>\n"
            f"Статус: <b>{vip_tag}</b>\n"
            f"Регистрация: <code>{created}</code>"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="⚙ Настройки", callback_data="prof_settings")
        kb.button(text="📜 История", callback_data="prof_history")
        kb.button(text="💎 VIP-статус", callback_data="prof_vip")
        kb.button(text="◀ Назад", callback_data="back_main")
        kb.adjust(1, 1, 1, 1)
        await safe_photo(msg.chat.id, "profile.jpg", text, kb.as_markup())
    except Exception as e:
        log.error(f"cmd_profile error: {e}")

# ---------- Настройки профиля ----------
async def cb_prof_settings(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        u = await get_user(uid)
        lang = (u.get("lang") or "ru").upper()
        hide = "✅" if u.get("hide_balance") else "❌"
        block = "✅" if u.get("block_transfers") else "❌"
        text = (
            "⚙ <b>НАСТРОЙКИ ПРОФИЛЯ</b>\n\n"
            f"🌐 Язык интерфейса: <b>{lang}</b>\n"
            f"🙈 Скрывать баланс: {hide}\n"
            f"🚫 Запретить переводы: {block}\n\n"
            "Настройки применяются мгновенно."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🌐 Язык: {lang}", callback_data="prof_lang")
        kb.button(text=f"🙈 Скрывать баланс: {hide}", callback_data="prof_toggle_hide")
        kb.button(text=f"🚫 Запретить переводы: {block}", callback_data="prof_toggle_block")
        kb.button(text="◀ Назад", callback_data="prof_back")
        kb.adjust(1)
        await safe_edit(cb, text, kb.as_markup())
    except Exception as e:
        log.error(f"cb_prof_settings error: {e}")

async def cb_prof_lang(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        u = await get_user(uid)
        new_lang = "en" if (u.get("lang") or "ru") == "ru" else "ru"
        await set_user_field(uid, "lang", new_lang)
        await cb.answer(f"Язык: {new_lang.upper()}")
        await cb_prof_settings(cb)
    except Exception as e:
        log.error(f"cb_prof_lang error: {e}")

async def cb_prof_toggle_hide(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        u = await get_user(uid)
        new_val = 0 if u.get("hide_balance") else 1
        await set_user_field(uid, "hide_balance", new_val)
        await cb.answer("Сохранено")
        await cb_prof_settings(cb)
    except Exception as e:
        log.error(f"cb_prof_toggle_hide error: {e}")

async def cb_prof_toggle_block(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        u = await get_user(uid)
        new_val = 0 if u.get("block_transfers") else 1
        await set_user_field(uid, "block_transfers", new_val)
        await cb.answer("Сохранено")
        await cb_prof_settings(cb)
    except Exception as e:
        log.error(f"cb_prof_toggle_block error: {e}")

async def cb_prof_back(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        # Перерисовываем профиль в том же сообщении
        uid = cb.from_user.id
        u = await get_user(uid)
        games = u.get("games_played", 0) or 0
        won = u.get("games_won", 0) or 0
        wr = (won / games * 100) if games else 0.0
        balance_display = "🔒 скрыт" if u.get("hide_balance") else fmt(u["balance"])
        vip = await is_vip(uid)
        vip_tag = "💎 VIP" if vip else "обычный"
        created = (u.get("created_at") or "")[:10]
        text = (
            "👤 <b>ПРОФИЛЬ ИГРОКА</b>\n\n"
            f"Имя: <b>{u.get('first_name') or 'Гость'}</b>\n"
            f"ID: <code>{uid}</code>\n"
            f"Баланс: <code>{balance_display}</code> TOKENS\n"
            f"Игр: <code>{games}</code> · Побед: <code>{won}</code>\n"
            f"Винрейт: <code>{wr:.1f}%</code>\n"
            f"Статус: <b>{vip_tag}</b>\n"
            f"Регистрация: <code>{created}</code>"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="⚙ Настройки", callback_data="prof_settings")
        kb.button(text="📜 История", callback_data="prof_history")
        kb.button(text="💎 VIP-статус", callback_data="prof_vip")
        kb.button(text="◀ Назад", callback_data="back_main")
        kb.adjust(1, 1, 1, 1)
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await cb.message.edit_caption(caption=text, reply_markup=kb.as_markup())
    except Exception as e:
        log.error(f"cb_prof_back error: {e}")

async def cb_prof_history(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT game, bet, result, win_amount, created_at FROM games_log "
                "WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            text = "📜 <b>ИСТОРИЯ ИГР</b>\n\nПока нет записей."
        else:
            lines = ["📜 <b>ИСТОРИЯ ИГР (последние 10)</b>\n"]
            for r in rows:
                mark = "✅" if r["result"] == 1 else "❌"
                ts = (r["created_at"] or "")[:16].replace("T", " ")
                lines.append(
                    f"{mark} <b>{r['game']}</b> · ставка <code>{fmt(r['bet'])}</code> · "
                    f"выигрыш <code>{fmt(r['win_amount'])}</code> · <code>{ts}</code>"
                )
            text = "\n".join(lines)
        kb = InlineKeyboardBuilder()
        kb.button(text="◀ Назад", callback_data="prof_back")
        await safe_edit(cb, text, kb.as_markup())
    except Exception as e:
        log.error(f"cb_prof_history error: {e}")

# ---------- VIP ----------
async def cb_prof_vip(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        vip = await is_vip(uid)
        u = await get_user(uid)
        if vip:
            until = (u.get("vip_until") or "")[:10]
            text = (
                "💎 <b>VIP-СТАТУС АКТИВЕН</b>\n\n"
                f"Действует до: <code>{until}</code>\n"
                f"Бонус к выигрышу: <code>+{int(VIP_BONUS*100)}%</code>\n"
                f"Ежедневный бонус: <code>+5%</code>"
            )
        else:
            text = (
                "💎 <b>VIP-СТАТУС</b>\n\n"
                f"Стоимость: <code>{fmt(VIP_PRICE)}</code> TOKENS\n"
                f"Срок: <code>{VIP_DAYS}</code> дней\n"
                f"Бонус к выигрышу: <code>+{int(VIP_BONUS*100)}%</code>\n"
                f"Ежедневный бонус: <code>+5%</code>"
            )
        kb = InlineKeyboardBuilder()
        if not vip:
            kb.button(text="💳 Купить VIP", callback_data="prof_buy_vip")
        kb.button(text="◀ Назад", callback_data="prof_back")
        kb.adjust(1)
        await safe_edit(cb, text, kb.as_markup())
    except Exception as e:
        log.error(f"cb_prof_vip error: {e}")

async def cb_buy_vip(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        u = await get_user(uid)
        if u["balance"] < VIP_PRICE:
            await cb.answer("Недостаточно средств", show_alert=True)
            return
        until = (datetime.utcnow() + timedelta(days=VIP_DAYS)).isoformat(timespec="seconds")
        await update_balance(uid, -VIP_PRICE)
        await set_user_field(uid, "vip_until", until)
        await cb.answer(f"VIP активирован до {until[:10]}", show_alert=True)
        await cb_prof_vip(cb)
    except Exception as e:
        log.error(f"cb_buy_vip error: {e}")

# ---------- Бонус ----------
def _bonus_status(daily: dict) -> tuple[bool, int]:
    """Возвращает (can_claim, remaining_seconds)."""
    last = daily.get("last_claim")
    if not last:
        return True, 0
    try:
        diff = (datetime.utcnow() - datetime.fromisoformat(last)).total_seconds()
        if diff < 86400:
            return False, int(86400 - diff)
    except Exception:
        return True, 0
    return True, 0

def _bonus_text(daily: dict) -> str:
    streak = daily.get("streak", 0) or 0
    can_claim, remaining = _bonus_status(daily)
    amount = DAILY_BONUS + streak * 50
    lines = [
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n",
        f"Награда: <code>{fmt(amount)}</code> TOKENS",
        f"Серия: <code>{streak}</code> дней",
        f"Стрик-бонус: <code>+{streak*50}</code> за день серии"
    ]
    if can_claim:
        lines.append("\n✅ Готово к получению.")
    else:
        h = remaining // 3600
        m = (remaining % 3600) // 60
        lines.append(f"\n⏳ Доступно через: <code>{h}ч {m}м</code>")
    return "\n".join(lines)

def _bonus_kb(daily: dict) -> InlineKeyboardMarkup:
    can_claim, _ = _bonus_status(daily)
    kb = InlineKeyboardBuilder()
    if can_claim:
        kb.button(text="🎁 Забрать", callback_data="bonus_claim")
    kb.button(text="🎟 Промокод", callback_data="bonus_promo")
    kb.button(text="◀ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

async def cmd_bonus(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        daily = await get_daily_bonus(msg.from_user.id)
        await safe_photo(msg.chat.id, "bonus.jpg", _bonus_text(daily), _bonus_kb(daily))
    except Exception as e:
        log.error(f"cmd_bonus error: {e}")

async def cb_bonus_claim(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        daily = await get_daily_bonus(uid)
        can_claim, _ = _bonus_status(daily)
        if not can_claim:
            await cb.answer("Бонус ещё не готов", show_alert=True)
            return
        streak = daily.get("streak", 0) or 0
        last = daily.get("last_claim")
        if last:
            try:
                diff = (datetime.utcnow() - datetime.fromisoformat(last)).total_seconds()
                streak = streak + 1 if diff < 172800 else 1
            except Exception:
                streak = 1
        else:
            streak = 1
        amount = DAILY_BONUS + (streak - 1) * 50
        if await is_vip(uid):
            amount = int(amount * 1.05)
        await update_balance(uid, amount)
        await set_daily_bonus(uid, now_iso(), streak)
        await cb.answer(f"✅ Получено {fmt(amount)} TOKENS", show_alert=True)
        # Обновляем сообщение
        new_daily = await get_daily_bonus(uid)
        try:
            await cb.message.edit_caption(caption=_bonus_text(new_daily), reply_markup=_bonus_kb(new_daily))
        except TelegramBadRequest:
            try:
                await cb.message.edit_text(_bonus_text(new_daily), reply_markup=_bonus_kb(new_daily))
            except Exception:
                pass
    except Exception as e:
        log.error(f"cb_bonus_claim error: {e}")

async def cb_bonus_promo(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        text = (
            "🎟 <b>ПРОМОКОД</b>\n\n"
            "Отправьте сообщение в формате:\n"
            "<code>промо КОД</code>\n\n"
            "Код не чувствителен к регистру."
        )
        await safe_edit(cb, text, back_inline("back_bonus"))
    except Exception as e:
        log.error(f"cb_bonus_promo error: {e}")

async def cmd_promo(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        uid = msg.from_user.id
        parts = (msg.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await safe_reply(msg, "❌ Укажите код: <code>промо КОД</code>")
            return
        code = parts[1].strip().upper()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM promo_codes WHERE code=?", (code,)) as cur:
                row = await cur.fetchone()
            if not row:
                await safe_reply(msg, "❌ Промокод не найден.")
                return
            promo = dict(row)
            async with db.execute("SELECT 1 FROM promo_used WHERE user_id=? AND code=?", (uid, code)) as cur:
                if await cur.fetchone():
                    await safe_reply(msg, "⚠️ Вы уже использовали этот промокод.")
                    return
            if promo["uses_left"] <= 0:
                await safe_reply(msg, "❌ Промокод исчерпан.")
                return
            if promo.get("expires_at"):
                try:
                    if datetime.fromisoformat(promo["expires_at"]) < datetime.utcnow():
                        await safe_reply(msg, "❌ Промокод истёк.")
                        return
                except Exception:
                    pass
            await db.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code=?", (code,))
            await db.execute("INSERT INTO promo_used (user_id, code) VALUES (?,?)", (uid, code))
            await db.commit()
        await update_balance(uid, promo["amount"])
        await safe_reply(msg, f"✅ Промокод активирован: <code>{fmt(promo['amount'])}</code> TOKENS")
    except Exception as e:
        log.error(f"cmd_promo error: {e}")

# ---------- Топ ----------
async def cmd_top(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        rows = await get_top_balance(10)
        lines = ["🏆 <b>ТОП-10 БАЛАНСОВ</b>\n"]
        medals = ["🥇", "🥈", "🥉"]
        if not rows:
            lines.append("Пока нет данных.")
        for i, r in enumerate(rows, 1):
            mark = medals[i-1] if i <= 3 else f"{i}."
            name = r["first_name"] or r["username"] or f"ID{r['user_id']}"
            lines.append(f"{mark} <b>{name}</b> — <code>{fmt(r['balance'])}</code>")
        await safe_photo(msg.chat.id, "top.jpg", "\n".join(lines), back_inline("back_main"))
    except Exception as e:
        log.error(f"cmd_top error: {e}")

# ---------- Поддержка ----------
async def cmd_support(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        text = (
            "🆘 <b>ПОДДЕРЖКА</b>\n\n"
            "По вопросам работы клуба, вывода средств, бана и прочего — "
            "обратитесь к администратору.\n\n"
            f"👤 Администратор: <code>{ADMIN_ID}</code>\n\n"
            "Среднее время ответа: до 24 часов.\n"
            "Опишите проблему и приложите ID из профиля."
        )
        await safe_photo(msg.chat.id, "support.jpg", text, back_inline("back_main"))
    except Exception as e:
        log.error(f"cmd_support error: {e}")

# ---------- Чаты ----------
async def cmd_chats(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        chats = await get_event_chats()
        lines = ["💬 <b>ЧАТЫ СОБЫТИЙ</b>\n"]
        if not chats:
            lines.append("Список пока пуст.\nАдминистратор добавит чаты через <code>@добавить_чат</code>.")
        else:
            for c in chats[:20]:
                lines.append(f"• <b>{c['title'] or 'Без названия'}</b> — <code>{c['chat_id']}</code>")
        await safe_photo(msg.chat.id, "chats.jpg", "\n".join(lines), back_inline("back_main"))
    except Exception as e:
        log.error(f"cmd_chats error: {e}")

# ---------- Клан ----------
async def cmd_clan(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        uid = msg.from_user.id
        u = await get_user(uid)
        clan_id = u.get("clan_id", 0)
        if clan_id:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM clans WHERE id=?", (clan_id,)) as cur:
                    clan = await cur.fetchone()
            if clan:
                text = (
                    f"🛡 <b>КЛАН: {clan['name']}</b>\n\n"
                    f"Владелец: <code>{clan['owner_id']}</code>\n"
                    f"Участников: <code>{clan['members']}</code>\n"
                    f"Баланс клана: <code>{fmt(clan['balance'])}</code>\n\n"
                    "Покинуть: <code>клан выйти</code>"
                )
                await safe_photo(msg.chat.id, "clans.jpg", text, back_inline("back_main"))
                return
        text = (
            "🛡 <b>КЛАНЫ</b>\n\n"
            "Вы не состоите в клане.\n\n"
            "<b>Команды:</b>\n"
            "<code>клан создать ИМЯ</code> — 50 000 TOKENS\n"
            "<code>клан вступить ID</code>\n"
            "<code>клан выйти</code>\n"
            "<code>клан инфо ID</code>"
        )
        await safe_photo(msg.chat.id, "clans.jpg", text, back_inline("back_main"))
    except Exception as e:
        log.error(f"cmd_clan error: {e}")

async def cmd_clan_action(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        uid = msg.from_user.id
        parts = (msg.text or "").split(maxsplit=2)
        if len(parts) < 2:
            await cmd_clan(msg)
            return
        action = parts[1].lower()
        if action == "создать":
            if len(parts) < 3 or len(parts[2].strip()) < 3:
                await safe_reply(msg, "❌ Укажите имя клана (от 3 символов).")
                return
            name = parts[2].strip()[:32]
            u = await get_user(uid)
            if u.get("clan_id", 0):
                await safe_reply(msg, "⚠️ Вы уже в клане.")
                return
            if u["balance"] < 50000:
                await safe_reply(msg, "❌ Нужно <code>50 000</code> TOKENS для создания клана.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                try:
                    cur = await db.execute(
                        "INSERT INTO clans (name, owner_id, balance, members) VALUES (?,?,?,1)",
                        (name, uid, 0)
                    )
                    clan_id = cur.lastrowid
                    await db.execute("UPDATE users SET clan_id=? WHERE user_id=?", (clan_id, uid))
                    await db.commit()
                except aiosqlite.IntegrityError:
                    await safe_reply(msg, "❌ Клан с таким именем уже существует.")
                    return
            await update_balance(uid, -50000)
            await safe_reply(msg, f"✅ Клан <b>{name}</b> создан. ID: <code>{clan_id}</code>")
        elif action == "вступить":
            if len(parts) < 3:
                await safe_reply(msg, "❌ Укажите ID клана: <code>клан вступить ID</code>")
                return
            try:
                cid = int(parts[2].strip())
            except Exception:
                await safe_reply(msg, "❌ Неверный ID.")
                return
            u = await get_user(uid)
            if u.get("clan_id", 0):
                await safe_reply(msg, "⚠️ Вы уже в клане.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM clans WHERE id=?", (cid,)) as cur:
                    clan = await cur.fetchone()
                if not clan:
                    await safe_reply(msg, "❌ Клан не найден.")
                    return
                await db.execute("UPDATE clans SET members = members + 1 WHERE id=?", (cid,))
                await db.execute("UPDATE users SET clan_id=? WHERE user_id=?", (cid, uid))
                await db.commit()
            await safe_reply(msg, f"✅ Вы вступили в клан <b>{clan['name']}</b>.")
        elif action == "выйти":
            u = await get_user(uid)
            cid = u.get("clan_id", 0)
            if not cid:
                await safe_reply(msg, "⚠️ Вы не в клане.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE clans SET members = MAX(0, members - 1) WHERE id=?", (cid,))
                await db.execute("UPDATE users SET clan_id=0 WHERE user_id=?", (uid,))
                await db.commit()
            await safe_reply(msg, "✅ Вы покинули клан.")
        elif action == "инфо":
            if len(parts) < 3:
                await safe_reply(msg, "❌ Укажите ID: <code>клан инфо ID</code>")
                return
            try:
                cid = int(parts[2].strip())
            except Exception:
                await safe_reply(msg, "❌ Неверный ID.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM clans WHERE id=?", (cid,)) as cur:
                    clan = await cur.fetchone()
            if not clan:
                await safe_reply(msg, "❌ Клан не найден.")
                return
            await safe_reply(msg,
                f"🛡 <b>{clan['name']}</b>\n"
                f"ID: <code>{clan['id']}</code>\n"
                f"Владелец: <code>{clan['owner_id']}</code>\n"
                f"Участников: <code>{clan['members']}</code>\n"
                f"Баланс: <code>{fmt(clan['balance'])}</code>"
            )
        else:
            await cmd_clan(msg)
    except Exception as e:
        log.error(f"cmd_clan_action error: {e}")

# ---------- Донат ----------
async def cmd_donate(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        text = (
            "💎 <b>ДОНАТ</b>\n\n"
            "Поддержите клуб и получите привилегии.\n\n"
            f"• VIP на {VIP_DAYS} дней — <code>{fmt(VIP_PRICE)}</code> TOKENS (+5% к выигрышу)\n"
            "• Telegram Stars — пополнение баланса\n\n"
            "Выберите пакет ниже."
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="⭐ 100 Stars → 10 000", callback_data="donate_pack:100")
        kb.button(text="⭐ 500 Stars → 60 000", callback_data="donate_pack:500")
        kb.button(text="⭐ 1000 Stars → 150 000", callback_data="donate_pack:1000")
        kb.button(text="💎 Купить VIP", callback_data="prof_buy_vip")
        kb.button(text="◀ Назад", callback_data="back_main")
        kb.adjust(1)
        await safe_photo(msg.chat.id, "donate.jpg", text, kb.as_markup())
    except Exception as e:
        log.error(f"cmd_donate error: {e}")

async def cb_donate_pack(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        stars = int(cb.data.split(":")[1])
    except Exception:
        await cb.answer("Ошибка", show_alert=True)
        return
    tokens = {100: 10_000, 500: 60_000, 1000: 150_000}.get(stars, stars * 100)
    prices = [LabeledPrice(label=f"{tokens} TOKENS", amount=stars)]
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title=f"Пакет {fmt(tokens)} TOKENS",
            description=f"Пополнение баланса на {fmt(tokens)} TOKENS",
            payload=f"donate:{tokens}:{cb.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
        await cb.answer("Счёт отправлен")
    except Exception as e:
        log.error(f"invoice error: {e}")
        await cb.answer("Ошибка оплаты", show_alert=True)

async def pre_checkout_handler(pcq: PreCheckoutQuery) -> None:
    try:
        await bot.answer_pre_checkout_query(pcq.id, ok=True)
    except Exception as e:
        log.error(f"pre_checkout error: {e}")

async def successful_payment_handler(msg: Message) -> None:
    try:
        payload = msg.successful_payment.invoice_payload
        parts = payload.split(":")
        if len(parts) < 3 or parts[0] != "donate":
            return
        tokens = int(parts[1])
        uid = int(parts[2])
        await update_balance(uid, tokens)
        await admin_log(ADMIN_ID, "donate_payment", uid, f"{tokens} TOKENS")
        await safe_send(uid, f"✅ Оплата получена. Зачислено <code>{fmt(tokens)}</code> TOKENS.")
    except Exception as e:
        log.error(f"successful_payment error: {e}")

# ---------- Навигация ----------
async def cb_back_main(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        text = "💠 <b>ГЛАВНОЕ МЕНЮ</b>\n\nВыберите раздел ниже или используйте клавиатуру."
        await safe_edit(cb, text, back_inline("back_main"))
    except Exception as e:
        log.error(f"cb_back_main error: {e}")

async def cb_back_bonus(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        daily = await get_daily_bonus(cb.from_user.id)
        try:
            await cb.message.edit_caption(caption=_bonus_text(daily), reply_markup=_bonus_kb(daily))
        except TelegramBadRequest:
            await cb.message.edit_text(_bonus_text(daily), reply_markup=_bonus_kb(daily))
    except Exception as e:
        log.error(f"cb_back_bonus error: {e}")

async def cb_games_menu(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        text = (
            "🎮 <b>ИГРЫ</b>\n\n"
            "Выберите игру или используйте команды:\n"
            "<code>кости 1000</code>, <code>мины 500</code>, <code>дуэль @user 1000</code>\n"
            f"Ставка: <code>{fmt(MIN_BET)}</code> – <code>{fmt(MAX_BET)}</code>"
        )
        kb = InlineKeyboardBuilder()
        games = [
            ("🎲 Кости", "game_info:кости"),
            ("🎯 Дартс", "game_info:дартс"),
            ("🏀 Баскет", "game_info:баскет"),
            ("⚽ Футбол", "game_info:футбол"),
            ("🎳 Боулинг", "game_info:боулинг"),
            ("🎰 БЖ", "game_info:бж"),
            ("🎰 Слоты", "game_info:слоты"),
            ("💣 Мины", "game_info:мины"),
            ("⚔ Дуэли", "game_info:дуэли"),
            ("🎡 Рулетка", "game_info:рулетка"),
            ("🎁 Бонусы", "back_bonus"),
            ("📖 Все команды", "game_info:commands"),
            ("❓ Что такое TOKENS?", "game_info:about"),
        ]
        for label, data in games:
            kb.button(text=label, callback_data=data)
        kb.button(text="◀ Назад", callback_data="back_main")
        kb.adjust(2, 2, 2, 2, 2, 2, 1)
        await safe_edit(cb, text, kb.as_markup())
    except Exception as e:
        log.error(f"cb_games_menu error: {e}")

async def cb_game_info(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        key = cb.data.split(":", 1)[1]
        texts = {
            "кости": "🎲 <b>КОСТИ</b>\n\nКоманда: <code>кости СТАВКА</code>\nВыигрыш x2 при результате > 3.\nКулдаун: 3 сек.",
            "дартс": "🎯 <b>ДАРТС</b>\n\nКоманда: <code>дартс СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "баскет": "🏀 <b>БАСКЕТ</b>\n\nКоманда: <code>баскет СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "футбол": "⚽ <b>ФУТБОЛ</b>\n\nКоманда: <code>футбол СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "боулинг": "🎳 <b>БОУЛИНГ</b>\n\nКоманда: <code>боулинг СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "бж": "🎰 <b>БЛЭКДЖЕК (БЖ)</b>\n\nКоманда: <code>бж СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "слоты": "🎰 <b>СЛОТЫ</b>\n\nКоманда: <code>слоты СТАВКА</code>\nВыигрыш x2 при результате > 3.",
            "мины": "💣 <b>МИНЫ</b>\n\nКоманда: <code>мины СТАВКА</code>\nПоле 5x5, 3 мины. Множитель <code>1.0 + открытых * 0.15</code>.\nКнопка «💰 Забрать» фиксирует выигрыш.",
            "дуэли": "⚔ <b>ДУЭЛИ</b>\n\nКоманда: <code>дуэль @user СТАВКА</code>\nКомиссия 5% от банка.\nInline-принятие в течение 60 сек.",
            "рулетка": "🎡 <b>РУЛЕТКА</b>\n\nСначала ставки:\n<code>к 1000</code> · <code>ч 500</code> · <code>1000 чет</code>\n<code>0 100</code> · <code>1000 1 2 3</code> · <code>500 10-20</code>\n\nЗатем <code>старт</code> запускает игру.",
            "commands": "📖 <b>ВСЕ КОМАНДЫ</b>\n\n<code>кости</code> <code>дартс</code> <code>баскет</code> <code>футбол</code> <code>боулинг</code> <code>бж</code> <code>слоты</code>\n<code>мины СТАВКА</code> · <code>дуэль @user СТАВКА</code> · <code>старт</code>\n<code>к СТАВКА</code> · <code>ч СТАВКА</code> · <code>1000 чет</code> · <code>0 100</code> · <code>1000 1 2 3</code> · <code>500 10-20</code>\n<code>бонус</code> · <code>профиль</code> · <code>топ</code> · <code>промо КОД</code>\n<code>клан создать ИМЯ</code> · <code>клан вступить ID</code> · <code>клан выйти</code>",
            "about": "❓ <b>ЧТО ТАКОЕ TOKENS?</b>\n\nTOKENS — внутренняя валюта клуба. Используется для ставок, дуэлей, покупки VIP и кланов.\nКурс стабилен, операции фиксируются в базе.\nБаланс не подлежит обратному обмену на фиат.",
        }
        txt = texts.get(key, "Информация недоступна.")
        await safe_edit(cb, txt, back_inline("games_menu"))
    except Exception as e:
        log.error(f"cb_game_info error: {e}")

# ============================================================
# ЧАСТЬ 3 — ИГРОВОЙ ДВИЖОК (детально)
# ============================================================

DICE_EMOJI = {
    "кости": "🎲",
    "дартс": "🎯",
    "баскет": "🏀",
    "футбол": "⚽",
    "боулинг": "🎳",
    "бж": "🎰",
    "слоты": "🎰"
}

async def _apply_win(msg: Message, bet: int, win: bool, game: str, win_value: int, dice_msg: Optional[Message] = None) -> None:
    """Начисляет/списывает средства, пишет лог, планирует автоудаление."""
    uid = msg.from_user.id
    try:
        if win:
            mult = await vip_multiplier(uid)
            payout = int(bet * 2 * mult)
            await update_balance(uid, payout - bet)
            await log_game(uid, game, bet, 1, payout)
            text = (
                f"✅ <b>ПОБЕДА</b>\n\n"
                f"🎮 Игра: <b>{game}</b>\n"
                f"🎯 Результат: <code>{win_value}</code>\n"
                f"💰 Выигрыш: <code>+{fmt(payout - bet)}</code> TOKENS\n"
                f"💼 Баланс: <code>{fmt((await get_user(uid))['balance'])}</code>"
            )
        else:
            await update_balance(uid, -bet)
            await log_game(uid, game, bet, 0, 0)
            text = (
                f"❌ <b>ПРОИГРЫШ</b>\n\n"
                f"🎮 Игра: <b>{game}</b>\n"
                f"🎯 Результат: <code>{win_value}</code>\n"
                f"💸 Потеряно: <code>-{fmt(bet)}</code> TOKENS\n"
                f"💼 Баланс: <code>{fmt((await get_user(uid))['balance'])}</code>"
            )
        sent = await safe_send(msg.chat.id, text, reply_to_message_id=msg.message_id)
        if sent:
            asyncio.create_task(_auto_delete(msg.chat.id, sent.message_id, 15))
        if dice_msg:
            asyncio.create_task(_auto_delete(msg.chat.id, dice_msg.message_id, 15))
        asyncio.create_task(_auto_delete(msg.chat.id, msg.message_id, 15))
    except Exception as e:
        log.error(f"_apply_win error: {e}")

async def _auto_delete(chat_id: int, message_id: int, delay: int) -> None:
    try:
        await asyncio.sleep(delay)
        await safe_delete(chat_id, message_id)
    except Exception:
        pass

async def _play_dice(msg: Message, game: str, bet: int) -> None:
    uid = msg.from_user.id
    lock = get_game_lock(uid)
    if lock.locked():
        await safe_reply(msg, "⚠️ <b>Игра уже выполняется.</b>")
        return
    async with lock:
        if uid in _double_spend:
            await safe_reply(msg, "⚠️ <b>Транзакция уже выполняется.</b>")
            return
        _double_spend.add(uid)
        try:
            if not await resolve_bet(msg, bet):
                return
            set_cooldown(uid)
            emoji = DICE_EMOJI.get(game, "🎲")
            await update_balance(uid, -bet)
            dice = await safe_dice(msg.chat.id, emoji)
            if not dice:
                await update_balance(uid, bet)
                await safe_reply(msg, "⚠️ Не удалось бросить кубик. Ставка возвращена.")
                return
            value = dice.dice.value if dice.dice else 0
            await asyncio.sleep(4)
            win = value > 3
            await _apply_win(msg, bet, win, game, value, dice_msg=dice)
        finally:
            _double_spend.discard(uid)

async def cmd_dice_game(msg: Message, game: str) -> None:
    try:
        if not await guard_message(msg):
            return
        if not _games_enabled:
            await safe_reply(msg, "🚫 <b>Игры временно отключены.</b>")
            return
        bet = bet_from_message(msg)
        if not bet:
            await safe_reply(msg, f"❌ Ставка: <code>{fmt(MIN_BET)}</code> – <code>{fmt(MAX_BET)}</code>")
            return
        if is_on_cooldown(msg.from_user.id):
            await safe_reply(msg, "⏳ <b>Подождите 3 секунды между играми.</b>")
            return
        await _play_dice(msg, game, bet)
    except Exception as e:
        log.error(f"cmd_dice_game error: {e}")
        await safe_reply(msg, "⚠️ Произошла ошибка.")

# ---------- МИНЫ ----------
def _mines_generate_field() -> tuple[str, list[int]]:
    cells = list(range(25))
    mines = set(random.sample(cells, 3))
    return ",".join(str(i) for i in sorted(mines)), sorted(mines)

def _mines_multiplier(opened: int) -> float:
    return 1.0 + opened * 0.15

def _mines_kb(state: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    opened = set(state["opened"])
    mines = set(state["mines"])
    lost = state.get("lost", False)
    for i in range(25):
        if i in opened:
            if i in mines:
                label = "💣"
            else:
                label = "💠"
        elif lost and i in mines:
            label = "💥"
        else:
            label = "⬜"
        cb_data = f"mine:{i}" if not lost else "mine_noop"
        kb.button(text=label, callback_data=cb_data)
    # Кнопка "Забрать"
    if not lost and opened:
        mult = _mines_multiplier(len(opened))
        payout = int(state["bet"] * mult)
        kb.button(text=f"💰 Забрать {fmt(payout)}", callback_data="mine_cashout")
    kb.adjust(5, 5, 5, 5, 5, 1)
    return kb.as_markup()

def _mines_text(state: dict) -> str:
    opened = len(state["opened"])
    mult = _mines_multiplier(opened)
    payout = int(state["bet"] * mult)
    if state.get("lost"):
        return (
            "💣 <b>МИНЫ — ВЗРЫВ</b>\n\n"
            f"Ставка: <code>{fmt(state['bet'])}</code>\n"
            f"Открыто: <code>{opened}</code>\n"
            f"❌ Вы наступили на мину. Потеряно: <code>-{fmt(state['bet'])}</code>"
        )
    return (
        "💣 <b>МИНЫ</b>\n\n"
        f"Ставка: <code>{fmt(state['bet'])}</code>\n"
        f"Открыто: <code>{opened}</code> / 25\n"
        f"Множитель: <code>x{mult:.2f}</code>\n"
        f"Текущий выигрыш: <code>{fmt(payout)}</code>\n\n"
        "Открывайте клетки. Заберите выигрыш до взрыва."
    )

async def cmd_mines(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        if not _games_enabled:
            await safe_reply(msg, "🚫 <b>Игры временно отключены.</b>")
            return
        uid = msg.from_user.id
        if uid in _active_mines:
            await safe_reply(msg, "⚠️ <b>У Вас уже активная игра в Мины.</b> Завершите её.")
            return
        bet = bet_from_message(msg)
        if not bet:
            await safe_reply(msg, f"❌ Ставка: <code>{fmt(MIN_BET)}</code> – <code>{fmt(MAX_BET)}</code>")
            return
        if is_on_cooldown(uid):
            await safe_reply(msg, "⏳ <b>Подождите 3 секунды между играми.</b>")
            return
        if not await resolve_bet(msg, bet):
            return
        mines_str, mines_list = _mines_generate_field()
        await update_balance(uid, -bet)
        state = {
            "bet": bet,
            "mines": mines_list,
            "opened": [],
            "lost": False,
            "finished": False,
            "msg_id": None,
            "chat_id": msg.chat.id,
            "uid": uid
        }
        _active_mines[uid] = state
        set_cooldown(uid)
        sent = await safe_send(msg.chat.id, _mines_text(state), _mines_kb(state))
        if sent:
            state["msg_id"] = sent.message_id
        # Логируем начало
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO mines (user_id, bet, field, opened, won, payout) VALUES (?,?,?,?,0,0)",
                (uid, bet, mines_str, "")
            )
            await db.commit()
    except Exception as e:
        log.error(f"cmd_mines error: {e}")

async def cb_mine_open(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        state = _active_mines.get(uid)
        if not state or state.get("finished"):
            await cb.answer("Игра завершена", show_alert=True)
            return
        cell = int(cb.data.split(":")[1])
        if cell in state["opened"]:
            await cb.answer("Клетка уже открыта", show_alert=True)
            return
        state["opened"].append(cell)
        if cell in state["mines"]:
            state["lost"] = True
            state["finished"] = True
            try:
                await cb.message.edit_text(_mines_text(state), reply_markup=_mines_kb(state))
            except Exception:
                pass
            await log_game(uid, "мины", state["bet"], 0, 0)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE mines SET opened=?, won=0, payout=0 WHERE user_id=? ORDER BY id DESC LIMIT 1",
                    (",".join(map(str, state["opened"])), uid)
                )
                await db.commit()
            _active_mines.pop(uid, None)
            await cb.answer("💥 Взрыв!")
            return
        if len(state["opened"]) == 22:
            await _mines_cashout_impl(cb, uid, state)
            return
        try:
            await cb.message.edit_text(_mines_text(state), reply_markup=_mines_kb(state))
        except Exception:
            pass
        await cb.answer(f"Открыто: {len(state['opened'])}")
    except Exception as e:
        log.error(f"cb_mine_open error: {e}")

async def _mines_cashout_impl(cb: CallbackQuery, uid: int, state: dict) -> None:
    try:
        opened = len(state["opened"])
        mult = _mines_multiplier(opened) * await vip_multiplier(uid)
        payout = int(state["bet"] * mult)
        await update_balance(uid, payout)
        await log_game(uid, "мины", state["bet"], 1, payout)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE mines SET opened=?, won=1, payout=? WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (",".join(map(str, state["opened"])), payout, uid)
            )
            await db.commit()
        state["finished"] = True
        text = (
            f"💰 <b>МИНЫ — ЗАБРАНО</b>\n\n"
            f"Ставка: <code>{fmt(state['bet'])}</code>\n"
            f"Открыто: <code>{opened}</code>\n"
            f"Множитель: <code>x{mult:.2f}</code>\n"
            f"✅ Выигрыш: <code>+{fmt(payout)}</code> TOKENS\n"
            f"💼 Баланс: <code>{fmt((await get_user(uid))['balance'])}</code>"
        )
        try:
            await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        except Exception:
            pass
        _active_mines.pop(uid, None)
        await cb.answer(f"Забрано {fmt(payout)}", show_alert=True)
    except Exception as e:
        log.error(f"_mines_cashout_impl error: {e}")

async def cb_mine_cashout(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        uid = cb.from_user.id
        state = _active_mines.get(uid)
        if not state or state.get("finished"):
            await cb.answer("Игра завершена", show_alert=True)
            return
        if not state["opened"]:
            await cb.answer("Сначала откройте клетку", show_alert=True)
            return
        await _mines_cashout_impl(cb, uid, state)
    except Exception as e:
        log.error(f"cb_mine_cashout error: {e}")

async def cb_mine_noop(cb: CallbackQuery) -> None:
    try:
        await cb.answer()
    except Exception:
        pass

# ---------- РУЛЕТКА ----------
ROULETTE_RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
ROULETTE_BLACK = set(range(1, 37)) - ROULETTE_RED

def _roulette_parse(text: str) -> Optional[dict]:
    """Парсит ставку. Возвращает dict или None."""
    t = text.lower().strip()
    parts = t.split()
    if len(parts) < 2:
        return None
    # к 1000 / ч 500
    if parts[0] in ("к", "ч", "красное", "черное", "чёрное"):
        try:
            amt = int(parts[1])
        except Exception:
            return None
        if amt < MIN_BET or amt > MAX_BET:
            return None
        bet_type = "red" if parts[0] in ("к", "красное") else "black"
        return {"type": bet_type, "amount": amt, "raw": text}
    # 1000 чет / 1000 нечет
    if len(parts) >= 2 and parts[1] in ("чет", "нечет", "чёт", "нечёт"):
        try:
            amt = int(parts[0])
        except Exception:
            return None
        if amt < MIN_BET or amt > MAX_BET:
            return None
        bet_type = "even" if parts[1] in ("чет", "чёт") else "odd"
        return {"type": bet_type, "amount": amt, "raw": text}
    # 0 100
    if parts[0] == "0":
        try:
            amt = int(parts[1])
        except Exception:
            return None
        if amt < MIN_BET or amt > MAX_BET:
            return None
        return {"type": "zero", "amount": amt, "raw": text}
    # 1000 1 2 3 (числа) или 500 10-20 (диапазон)
    try:
        amt = int(parts[0])
    except Exception:
        return None
    if amt < MIN_BET or amt > MAX_BET:
        return None
    if len(parts) == 2 and "-" in parts[1]:
        try:
            a, b = parts[1].split("-")
            a, b = int(a), int(b)
            if not (0 <= a <= 36 and 0 <= b <= 36 and a <= b):
                return None
        except Exception:
            return None
        return {"type": "range", "amount": amt, "range": (a, b), "raw": text}
    nums = []
    for p in parts[1:]:
        try:
            n = int(p)
            if 0 <= n <= 36:
                nums.append(n)
        except Exception:
            return None
    if not nums:
        return None
    return {"type": "numbers", "amount": amt, "numbers": nums, "raw": text}

def _roulette_eval(bet: dict, result: int) -> int:
    """Возвращает множитель выигрыша (0 = проигрыш)."""
    t = bet["type"]
    if t == "red":
        return 2 if result in ROULETTE_RED else 0
    if t == "black":
        return 2 if result in ROULETTE_BLACK else 0
    if t == "even":
        return 2 if result != 0 and result % 2 == 0 else 0
    if t == "odd":
        return 2 if result % 2 == 1 else 0
    if t == "zero":
        return 36 if result == 0 else 0
    if t == "range":
        a, b = bet["range"]
        return 2 if a <= result <= b else 0
    if t == "numbers":
        return 36 if result in bet["numbers"] else 0
    return 0

def _roulette_bets_text(bets: dict[int, dict]) -> str:
    if not bets:
        return "Ставок пока нет."
    lines = []
    for i, (uid, b) in enumerate(bets.items(), 1):
        lines.append(f"{i}. <code>{uid}</code> → <code>{b['raw']}</code>")
    return "\n".join(lines)

def _roulette_kb(active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if active:
        kb.button(text="🎡 Запустить", callback_data="roulette_start")
    kb.adjust(1)
    return kb.as_markup()

async def cmd_roulette_bet(msg: Message) -> None:
    """Обрабатывает ставку рулетки в чате: к 1000, ч 500, 1000 чет и т.д."""
    try:
        if not await guard_message(msg):
            return
        uid = msg.from_user.id
        chat_id = msg.chat.id
        bet = _roulette_parse(msg.text)
        if not bet:
            return
        state = _active_roulettes.get(chat_id)
        if not state:
            state = {"bets": {}, "started": False, "msg_id": None}
            _active_roulettes[chat_id] = state
        if state["started"]:
            await safe_reply(msg, "⚠️ <b>Рулетка уже запущена.</b> Дождитесь результата.")
            return
        if uid in state["bets"]:
            await safe_reply(msg, "⚠️ <b>Вы уже сделали ставку.</b> Одна ставка на раунд.")
            return
        u = await get_user(uid)
        if u["balance"] < bet["amount"]:
            await safe_reply(msg, "❌ <b>Недостаточно средств.</b>")
            return
        state["bets"][uid] = bet
        text = (
            "🎡 <b>РУЛЕТКА — СТАВКИ</b>\n\n"
            f"Игрок: <b>{msg.from_user.first_name or 'Гость'}</b>\n"
            f"Ставка: <code>{bet['raw']}</code>\n\n"
            f"<b>Список ставок:</b>\n{_roulette_bets_text(state['bets'])}"
        )
        sent = await safe_send(chat_id, text, _roulette_kb(True))
        if sent:
            state["msg_id"] = sent.message_id
    except Exception as e:
        log.error(f"cmd_roulette_bet error: {e}")

async def cb_roulette_start(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        chat_id = cb.message.chat.id
        uid = cb.from_user.id
        state = _active_roulettes.get(chat_id)
        if not state or not state["bets"]:
            await cb.answer("Ставок нет", show_alert=True)
            return
        if state["started"]:
            await cb.answer("Уже запущено", show_alert=True)
            return
        # Запускать может любой (по правилам — инициатор), но лучше сделать admin/owner
        async with _roulette_lock:
            state["started"] = True
            total = sum(b["amount"] for b in state["bets"].values())
            # Списание средств
            for p_uid, b in state["bets"].items():
                await update_balance(p_uid, -b["amount"])
            try:
                await cb.message.edit_text(
                    "🎡 <b>РУЛЕТКА — ИГРА</b>\n\n"
                    f"Игроков: <code>{len(state['bets'])}</code>\n"
                    f"Банк: <code>{fmt(total)}</code>\n\n"
                    "Бросок через 3 секунды...",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
                )
            except Exception:
                pass
            dice = await safe_dice(chat_id, "🎡")
            await asyncio.sleep(ROULETTE_PAUSE + 1)
            if dice and dice.dice:
                result = (dice.dice.value - 1) * 6 + random.randint(1, 6) - 1
                result = max(0, min(36, result))
            else:
                result = random.randint(0, 36)
            color = "🔴 красное" if result in ROULETTE_RED else ("⚫ чёрное" if result in ROULETTE_BLACK else "🟢 зеро")
            winners_lines = []
            for p_uid, b in state["bets"].items():
                mult = _roulette_eval(b, result)
                if mult > 0:
                    base = b["amount"] * mult
                    vip_m = await vip_multiplier(p_uid)
                    payout = int(base * vip_m)
                    await update_balance(p_uid, payout)
                    await log_roulette(chat_id, p_uid, b["raw"], 1, payout)
                    winners_lines.append(f"✅ <code>{p_uid}</code> → <code>+{fmt(payout)}</code>")
                else:
                    await log_roulette(chat_id, p_uid, b["raw"], 0, 0)
                    winners_lines.append(f"❌ <code>{p_uid}</code> → <code>-{fmt(b['amount'])}</code>")
            text = (
                f"🎡 <b>РЕЗУЛЬТАТ РУЛЕТКИ</b>\n\n"
                f"Выпало: <b>{result}</b> {color}\n\n"
                f"<b>Итоги:</b>\n" + "\n".join(winners_lines)
            )
            await safe_send(chat_id, text, InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Повторить", callback_data="roulette_repeat")],
                [InlineKeyboardButton(text="×2 Удвоить", callback_data="roulette_double")]
            ]))
            # Сохраняем последнюю ставку для повтора
            state["last_result"] = result
            state["last_bets"] = dict(state["bets"])
            state["bets"] = {}
            state["started"] = False
            try:
                await cb.answer()
            except Exception:
                pass
    except Exception as e:
        log.error(f"cb_roulette_start error: {e}")

async def cb_roulette_repeat(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        chat_id = cb.message.chat.id
        state = _active_roulettes.get(chat_id)
        if not state or "last_bets" not in state:
            await cb.answer("Нет предыдущей ставки", show_alert=True)
            return
        uid = cb.from_user.id
        if uid not in state["last_bets"]:
            await cb.answer("Вы не участвовали", show_alert=True)
            return
        prev = state["last_bets"][uid]
        u = await get_user(uid)
        if u["balance"] < prev["amount"]:
            await cb.answer("Недостаточно средств", show_alert=True)
            return
        state["bets"] = {uid: prev}
        state["started"] = False
        await safe_send(chat_id, f"🔁 <b>Повтор ставки</b>\n\n<code>{prev['raw']}</code>", _roulette_kb(True))
        await cb.answer()
    except Exception as e:
        log.error(f"cb_roulette_repeat error: {e}")

async def cb_roulette_double(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        chat_id = cb.message.chat.id
        state = _active_roulettes.get(chat_id)
        if not state or "last_bets" not in state:
            await cb.answer("Нет предыдущей ставки", show_alert=True)
            return
        uid = cb.from_user.id
        if uid not in state["last_bets"]:
            await cb.answer("Вы не участвовали", show_alert=True)
            return
        prev = state["last_bets"][uid]
        new_amount = prev["amount"] * 2
        if new_amount > MAX_BET:
            await cb.answer("Превышен максимум", show_alert=True)
            return
        u = await get_user(uid)
        if u["balance"] < new_amount:
            await cb.answer("Недостаточно средств", show_alert=True)
            return
        new_bet = dict(prev)
        new_bet["amount"] = new_amount
        new_bet["raw"] = f"{prev['raw']} ×2"
        state["bets"] = {uid: new_bet}
        state["started"] = False
        await safe_send(chat_id, f"×2 <b>Удвоено</b>\n\n<code>{new_bet['raw']}</code>", _roulette_kb(True))
        await cb.answer()
    except Exception as e:
        log.error(f"cb_roulette_double error: {e}")

async def cmd_roulette_start_text(msg: Message) -> None:
    """Команда 'старт' в чате — запускает рулетку."""
    try:
        if not await guard_message(msg):
            return
        chat_id = msg.chat.id
        state = _active_roulettes.get(chat_id)
        if not state or not state["bets"]:
            await safe_reply(msg, "❌ <b>Нет ставок для запуска.</b>")
            return
        if state["started"]:
            await safe_reply(msg, "⚠️ <b>Рулетка уже запущена.</b>")
            return
        # Создаём фейковый cb для единой логики
        class _FakeCB:
            def __init__(self, m: Message):
                self.message = m
                self.from_user = m.from_user
                self.data = "roulette_start"
            async def answer(self, *a, **k):
                return None
        fake = _FakeCB(msg)
        await cb_roulette_start(fake)
    except Exception as e:
        log.error(f"cmd_roulette_start_text error: {e}")

# ---------- ДУЭЛИ ----------
async def cmd_duel(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        if not _games_enabled:
            await safe_reply(msg, "🚫 <b>Игры временно отключены.</b>")
            return
        uid = msg.from_user.id
        parts = (msg.text or "").split()
        if len(parts) < 3:
            await safe_reply(msg, "❌ Формат: <code>дуэль @user СТАВКА</code>")
            return
        target = parts[1].lstrip("@")
        try:
            bet = int(parts[2])
        except Exception:
            await safe_reply(msg, "❌ Неверная ставка.")
            return
        if bet < MIN_BET or bet > MAX_BET:
            await safe_reply(msg, f"❌ Ставка: <code>{fmt(MIN_BET)}</code> – <code>{fmt(MAX_BET)}</code>")
            return
        # Определяем opponent_id
        opponent_id = None
        if target.isdigit():
            opponent_id = int(target)
        else:
            # ищем по username
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE username=?", (target,)) as cur:
                    row = await cur.fetchone()
                if row:
                    opponent_id = row["user_id"]
        if not opponent_id:
            await safe_reply(msg, "❌ Игрок не найден в базе.")
            return
        if opponent_id == uid:
            await safe_reply(msg, "❌ Нельзя дуэль с самим собой.")
            return
        u = await get_user(uid)
        o = await get_user(opponent_id)
        if u["balance"] < bet:
            await safe_reply(msg, "❌ <b>Недостаточно средств.</b>")
            return
        if o["balance"] < bet:
            await safe_reply(msg, "❌ <b>У соперника недостаточно средств.</b>")
            return
        async with _duel_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "INSERT INTO duels (challenger, opponent, bet, status) VALUES (?,?,?, 'pending')",
                    (uid, opponent_id, bet)
                )
                duel_id = cur.lastrowid
                await db.commit()
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Принять", callback_data=f"duel_accept:{duel_id}")
        kb.button(text="❌ Отклонить", callback_data=f"duel_decline:{duel_id}")
        kb.adjust(2)
        await safe_send(
            msg.chat.id,
            f"⚔ <b>ВЫЗОВ НА ДУЭЛЬ</b>\n\n"
            f"Вызывающий: <b>{u.get('first_name') or uid}</b>\n"
            f"Соперник: <b>{o.get('first_name') or opponent_id}</b>\n"
            f"Ставка: <code>{fmt(bet)}</code>\n"
            f"Комиссия: <code>{int(DUEL_COMMISSION*100)}%</code>\n\n"
            f"Соперник, подтвердите в течение 60 секунд.",
            kb.as_markup()
        )
        asyncio.create_task(_duel_timeout(duel_id, msg.chat.id, 60))
    except Exception as e:
        log.error(f"cmd_duel error: {e}")

async def _duel_timeout(duel_id: int, chat_id: int, seconds: int) -> None:
    try:
        await asyncio.sleep(seconds)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM duels WHERE id=?", (duel_id,)) as cur:
                row = await cur.fetchone()
            if row and row["status"] == "pending":
                await db.execute("UPDATE duels SET status='expired' WHERE id=?", (duel_id,))
                await db.commit()
                await safe_send(chat_id, f"⌛ <b>Дуэль #{duel_id} истекла.</b>")
    except Exception as e:
        log.error(f"_duel_timeout error: {e}")

async def cb_duel_accept(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        duel_id = int(cb.data.split(":")[1])
        uid = cb.from_user.id
        async with _duel_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE id=?", (duel_id,)) as cur:
                    duel = await cur.fetchone()
                if not duel:
                    await cb.answer("Дуэль не найдена", show_alert=True)
                    return
                if duel["status"] != "pending":
                    await cb.answer("Дуэль уже завершена", show_alert=True)
                    return
                if duel["opponent"] != uid:
                    await cb.answer("Это не Ваш вызов", show_alert=True)
                    return
                bet = duel["bet"]
                u = await get_user(duel["challenger"])
                o = await get_user(uid)
                if u["balance"] < bet or o["balance"] < bet:
                    await db.execute("UPDATE duels SET status='failed' WHERE id=?", (duel_id,))
                    await db.commit()
                    await cb.answer("Недостаточно средств у кого-то из игроков", show_alert=True)
                    return
                await update_balance(duel["challenger"], -bet)
                await update_balance(uid, -bet)
                # Бросок кубика
                d1 = await safe_dice(cb.message.chat.id, "🎲")
                await asyncio.sleep(2)
                d2 = await safe_dice(cb.message.chat.id, "🎲")
                await asyncio.sleep(2)
                v1 = d1.dice.value if d1 and d1.dice else random.randint(1, 6)
                v2 = d2.dice.value if d2 and d2.dice else random.randint(1, 6)
                if v1 == v2:
                    # ничья — возврат
                    await update_balance(duel["challenger"], bet)
                    await update_balance(uid, bet)
                    await db.execute("UPDATE duels SET status='draw' WHERE id=?", (duel_id,))
                    await db.commit()
                    await safe_send(cb.message.chat.id,
                        f"⚔ <b>ДУЭЛЬ #{duel_id} — НИЧЬЯ</b>\n\n"
                        f"<code>{v1}</code> : <code>{v2}</code>\nСтавки возвращены.")
                    await cb.answer()
                    return
                winner = duel["challenger"] if v1 > v2 else uid
                loser = uid if winner == duel["challenger"] else duel["challenger"]
                total_bank = bet * 2
                commission = int(total_bank * DUEL_COMMISSION)
                payout = total_bank - commission
                await update_balance(winner, payout)
                await db.execute(
                    "UPDATE duels SET status='finished', winner=? WHERE id=?",
                    (winner, duel_id)
                )
                await db.commit()
                await log_game(winner, "дуэль", bet, 1, payout)
                await log_game(loser, "дуэль", bet, 0, 0)
                await safe_send(cb.message.chat.id,
                    f"⚔ <b>ДУЭЛЬ #{duel_id} — ИТОГ</b>\n\n"
                    f"<code>{v1}</code> : <code>{v2}</code>\n"
                    f"🏆 Победитель: <code>{winner}</code>\n"
                    f"💰 Выигрыш: <code>+{fmt(payout)}</code>\n"
                    f"💸 Комиссия: <code>{fmt(commission)}</code>")
                await cb.answer()
    except Exception as e:
        log.error(f"cb_duel_accept error: {e}")

async def cb_duel_decline(cb: CallbackQuery) -> None:
    try:
        if not await guard_callback(cb):
            return
        duel_id = int(cb.data.split(":")[1])
        uid = cb.from_user.id
        async with _duel_lock:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE id=?", (duel_id,)) as cur:
                    duel = await cur.fetchone()
                if not duel or duel["status"] != "pending":
                    await cb.answer("Дуэль не активна", show_alert=True)
                    return
                if duel["opponent"] != uid:
                    await cb.answer("Это не Ваш вызов", show_alert=True)
                    return
                await db.execute("UPDATE duels SET status='declined' WHERE id=?", (duel_id,))
                await db.commit()
                await safe_send(cb.message.chat.id, f"❌ <b>Дуэль #{duel_id} отклонена.</b>")
        await cb.answer("Отклонено")
    except Exception as e:
        log.error(f"cb_duel_decline error: {e}")

# ============================================================
# ЧАСТЬ 4 — АДМИНКА, АВТО-ИВЕНТЫ, РОУТИНГ, ЗАПУСК
# ============================================================

ADMIN_COMMANDS = {
    "выдать", "дроп", "бан", "разбан", "обнулить", "баланс",
    "выдать_всем", "забрать_всем", "юзер", "стата", "топ_баланс",
    "лог", "рассылка", "бекап", "отключить_игры", "включить_игры",
    "изменить_курс", "глобальный_дроп", "добавить_чат", "убрать_чат",
    "создать_промо", "сбросить_бонус", "выдать_vip"
}

async def admin_guard(msg: Message) -> bool:
    if not msg.from_user:
        return False
    if msg.from_user.id != ADMIN_ID:
        await safe_reply(msg, "🚫 <b>Недостаточно прав.</b>")
        return False
    await touch_user(msg.from_user)
    return True

async def _resolve_target(msg: Message, arg: str) -> Optional[int]:
    if arg.isdigit():
        return int(arg)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users WHERE username=?", (arg.lstrip("@"),)) as cur:
            row = await cur.fetchone()
    return row["user_id"] if row else None

async def cmd_admin(msg: Message) -> None:
    try:
        if not await admin_guard(msg):
            return
        text = (msg.text or "").strip()
        parts = text.split()
        if len(parts) < 1:
            return
        cmd = parts[0].lstrip("@").lower()
        args = parts[1:]
        admin_id = msg.from_user.id
        if cmd == "выдать":
            if len(args) < 2:
                await safe_reply(msg, "❌ <code>@выдать ID СУММА</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            try:
                amount = int(args[1])
            except Exception:
                await safe_reply(msg, "❌ Неверная сумма.")
                return
            await get_user(target)
            await update_balance(target, amount)
            await admin_log(admin_id, "выдать", target, f"+{amount}")
            await safe_reply(msg, f"✅ Выдано <code>{fmt(amount)}</code> игроку <code>{target}</code>")
        elif cmd == "дроп":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@дроп СУММА</code>")
                return
            try:
                amount = int(args[0])
            except Exception:
                await safe_reply(msg, "❌ Неверная сумма.")
                return
            if not msg.reply_to_message:
                await safe_reply(msg, "❌ Ответьте на сообщение игрока.")
                return
            target = msg.reply_to_message.from_user.id
            await get_user(target)
            await update_balance(target, amount)
            await admin_log(admin_id, "дроп", target, f"+{amount}")
            await safe_reply(msg, f"✅ Дроп <code>{fmt(amount)}</code> → <code>{target}</code>")
        elif cmd == "бан":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@бан ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            await get_user(target)
            await set_user_field(target, "banned", 1)
            await admin_log(admin_id, "бан", target, "")
            await safe_reply(msg, f"🚫 Забанен: <code>{target}</code>")
        elif cmd == "разбан":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@разбан ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            await get_user(target)
            await set_user_field(target, "banned", 0)
            await admin_log(admin_id, "разбан", target, "")
            await safe_reply(msg, f"✅ Разбанен: <code>{target}</code>")
        elif cmd == "обнулить":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@обнулить ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            u = await get_user(target)
            await update_balance(target, -u["balance"])
            await admin_log(admin_id, "обнулить", target, "0")
            await safe_reply(msg, f"✅ Баланс <code>{target}</code> обнулён.")
        elif cmd == "баланс":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@баланс ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            u = await get_user(target)
            await safe_reply(msg, f"💰 <code>{target}</code> → <code>{fmt(u['balance'])}</code>")
        elif cmd == "выдать_всем":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@выдать_всем СУММА</code>")
                return
            try:
                amount = int(args[0])
            except Exception:
                await safe_reply(msg, "❌ Неверная сумма.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET balance = balance + ? WHERE banned=0", (amount,))
                await db.commit()
            _user_cache.clear()
            await admin_log(admin_id, "выдать_всем", 0, f"+{amount}")
            await safe_reply(msg, f"✅ Всем выдано по <code>{fmt(amount)}</code>")
        elif cmd == "забрать_всем":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@забрать_всем СУММА</code>")
                return
            try:
                amount = int(args[0])
            except Exception:
                await safe_reply(msg, "❌ Неверная сумма.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET balance = MAX(0, balance - ?) WHERE banned=0", (amount,))
                await db.commit()
            _user_cache.clear()
            await admin_log(admin_id, "забрать_всем", 0, f"-{amount}")
            await safe_reply(msg, f"✅ У всех списано по <code>{fmt(amount)}</code>")
        elif cmd == "юзер":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@юзер ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                await safe_reply(msg, "❌ Игрок не найден.")
                return
            u = await get_user(target)
            text = (
                f"👤 <b>ИНФО</b>\n\n"
                f"ID: <code>{target}</code>\n"
                f"Имя: <b>{u.get('first_name') or '—'}</b>\n"
                f"Username: <code>@{u.get('username') or '—'}</code>\n"
                f"Баланс: <code>{fmt(u['balance'])}</code>\n"
                f"Игр: <code>{u.get('games_played', 0)}</code>\n"
                f"Побед: <code>{u.get('games_won', 0)}</code>\n"
                f"VIP до: <code>{u.get('vip_until') or '—'}</code>\n"
                f"Бан: <code>{u.get('banned', 0)}</code>\n"
                f"Клан: <code>{u.get('clan_id', 0)}</code>\n"
                f"Регистрация: <code>{(u.get('created_at') or '')[:10]}</code>"
            )
            await safe_send(msg.chat.id, text)
        elif cmd == "стата":
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT COUNT(*) as c, SUM(balance) as s FROM users") as cur:
                    row = await cur.fetchone()
            await safe_reply(msg,
                f"📊 <b>СТАТИСТИКА</b>\n\n"
                f"Пользователей: <code>{row['c'] or 0}</code>\n"
                f"Сумма балансов: <code>{fmt(row['s'] or 0)}</code>\n"
                f"Игры: <code>{'вкл' if _games_enabled else 'выкл'}</code>\n"
                f"Курс: <code>{_current_rate}</code>\n"
                f"Happy Hour: <code>{'да' if _happy_hour else 'нет'}</code>\n"
                f"Джекпот: <code>{fmt(_jackpot_pool)}</code>")
        elif cmd == "топ_баланс":
            rows = await get_top_balance(20)
            lines = ["🏆 <b>ТОП-20 (админ)</b>\n"]
            for i, r in enumerate(rows, 1):
                name = r["first_name"] or r["username"] or r["user_id"]
                lines.append(f"{i}. <code>{r['user_id']}</code> <b>{name}</b> — <code>{fmt(r['balance'])}</code>")
            await safe_send(msg.chat.id, "\n".join(lines))
        elif cmd == "лог":
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 20") as cur:
                    rows = await cur.fetchall()
            lines = ["📜 <b>ЛОГ АДМИНА (20)</b>\n"]
            for r in rows:
                ts = (r["created_at"] or "")[:16].replace("T", " ")
                lines.append(f"<code>{ts}</code> · <b>{r['action']}</b> · {r['target']} · {r['details']}")
            await safe_send(msg.chat.id, "\n".join(lines) if len(rows) else "Лог пуст.")
        elif cmd == "рассылка":
            if not msg.reply_to_message:
                await safe_reply(msg, "❌ Ответьте на сообщение для рассылки.")
                return
            src = msg.reply_to_message
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as cur:
                    users = [r[0] for r in await cur.fetchall()]
            ok, fail = 0, 0
            for uid in users:
                try:
                    await bot.copy_message(uid, src.chat.id, src.message_id)
                    ok += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    fail += 1
            await safe_reply(msg, f"✅ Рассылка: <code>{ok}</code> успешно, <code>{fail}</code> ошибок")
        elif cmd == "бекап":
            try:
                from datetime import datetime as _dt
                backup_name = f"backup_{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(f"VACUUM INTO '{backup_name}'")
                    await db.commit()
                await bot.send_document(msg.chat.id, FSInputFile(backup_name))
                try:
                    os.remove(backup_name)
                except Exception:
                    pass
            except Exception as e:
                log.error(f"backup error: {e}")
                await safe_reply(msg, "❌ Ошибка бекапа.")
        elif cmd == "отключить_игры":
            global _games_enabled
            _games_enabled = False
            await admin_log(admin_id, "отключить_игры")
            await safe_reply(msg, "🚫 Игры отключены.")
        elif cmd == "включить_игры":
            _games_enabled = True
            await admin_log(admin_id, "включить_игры")
            await safe_reply(msg, "✅ Игры включены.")
        elif cmd == "изменить_курс":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@изменить_курс 1.5</code>")
                return
            try:
                _current_rate = float(args[0])
            except Exception:
                await safe_reply(msg, "❌ Неверный курс.")
                return
            await admin_log(admin_id, "изменить_курс", 0, str(_current_rate))
            await safe_reply(msg, f"✅ Курс: <code>{_current_rate}</code>")
        elif cmd == "глобальный_дроп":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@глобальный_дроп СУММА</code>")
                return
            try:
                amount = int(args[0])
            except Exception:
                await safe_reply(msg, "❌ Неверная сумма.")
                return
            chats = await get_event_chats()
            sent = 0
            for c in chats:
                try:
                    await safe_send(c["chat_id"],
                        f"🎁 <b>ГЛОБАЛЬНЫЙ ДРОП</b>\n\n"
                        f"Сумма: <code>{fmt(amount)}</code> TOKENS\n"
                        f"Первым <code>10</code> игрокам.\n"
                        f"Отправьте <code>забрать</code> в чат.")
                    sent += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
            await safe_reply(msg, f"✅ Разослано в <code>{sent}</code> чатов.")
        elif cmd == "добавить_чат":
            if msg.chat.type not in ("group", "supergroup"):
                await safe_reply(msg, "❌ Используйте в группе.")
                return
            await add_event_chat(msg.chat.id, msg.chat.title or "")
            await safe_reply(msg, "✅ Чат добавлен.")
        elif cmd == "убрать_чат":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE event_chats SET active=0 WHERE chat_id=?", (msg.chat.id,))
                await db.commit()
            await safe_reply(msg, "✅ Чат убран.")
        elif cmd == "создать_промо":
            if len(args) < 2:
                await safe_reply(msg, "❌ <code>@создать_промо КОД СУММА [ИСПОЛЬЗОВАНИЙ]</code>")
                return
            code = args[0].upper()
            try:
                amount = int(args[1])
                uses = int(args[2]) if len(args) > 2 else 1
            except Exception:
                await safe_reply(msg, "❌ Неверные параметры.")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                try:
                    await db.execute(
                        "INSERT INTO promo_codes (code, amount, uses_left) VALUES (?,?,?)",
                        (code, amount, uses)
                    )
                    await db.commit()
                except aiosqlite.IntegrityError:
                    await safe_reply(msg, "❌ Код уже существует.")
                    return
            await safe_reply(msg, f"✅ Промокод <code>{code}</code>: <code>{fmt(amount)}</code> × <code>{uses}</code>")
        elif cmd == "сбросить_бонус":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@сбросить_бонус ID</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM daily_bonus WHERE user_id=?", (target,))
                await db.commit()
            await safe_reply(msg, f"✅ Бонус сброшен: <code>{target}</code>")
        elif cmd == "выдать_vip":
            if len(args) < 1:
                await safe_reply(msg, "❌ <code>@выдать_vip ID [дней]</code>")
                return
            target = await _resolve_target(msg, args[0])
            if not target:
                return
            days = int(args[1]) if len(args) > 1 else VIP_DAYS
            until = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
            await get_user(target)
            await set_user_field(target, "vip_until", until)
            await safe_reply(msg, f"✅ VIP до <code>{until[:10]}</code> для <code>{target}</code>")
        elif cmd == "хелп":
            lines = ["🛠 <b>АДМИН-КОМАНДЫ</b>\n"]
            for c in sorted(ADMIN_COMMANDS):
                lines.append(f"<code>@{c}</code>")
            await safe_send(msg.chat.id, "\n".join(lines))
    except Exception as e:
        log.error(f"cmd_admin error: {e}")
        await safe_reply(msg, "❌ Ошибка выполнения.")

# ============================================================
# АВТО-ИВЕНТЫ (APScheduler)
# ============================================================
async def event_happy_hour_start() -> None:
    global _happy_hour
    _happy_hour = True
    log.info("Happy hour started")
    chats = await get_event_chats()
    for c in chats:
        try:
            await safe_send(c["chat_id"], "🔥 <b>СЧАСТЛИВЫЙ ЧАС!</b>\n\nВсе выигрыши удвоены в течение часа.")
        except Exception:
            pass

async def event_happy_hour_end() -> None:
    global _happy_hour
    _happy_hour = False
    log.info("Happy hour ended")

async def event_auto_drop() -> None:
    try:
        chats = await get_event_chats()
        if not chats:
            return
        amount = random.randint(100, 500)
        for c in chats:
            try:
                await safe_send(c["chat_id"],
                    f"🎁 <b>АВТО-ДРОП</b>\n\n"
                    f"Сумма: <code>{fmt(amount)}</code> TOKENS\n"
                    f"Первым <code>5</code> игрокам.\n"
                    f"Команда: <code>забрать</code>")
            except Exception:
                pass
        log.info(f"Auto drop {amount} in {len(chats)} chats")
    except Exception as e:
        log.error(f"event_auto_drop error: {e}")

async def event_jackpot() -> None:
    try:
        global _jackpot_pool
        chats = await get_event_chats()
        if not chats:
            return
        if _jackpot_pool < 1000:
            _jackpot_pool += 500
            return
        winners = []
        for c in chats[:5]:
            try:
                await safe_send(c["chat_id"],
                    f"💎 <b>ГЛОБАЛЬНЫЙ ДЖЕКПОТ</b>\n\n"
                    f"Сумма: <code>{fmt(_jackpot_pool)}</code> TOKENS\n"
                    f"Команда: <code>забрать</code>")
                winners.append(c["chat_id"])
            except Exception:
                pass
        if winners:
            _jackpot_pool = 0
    except Exception as e:
        log.error(f"event_jackpot error: {e}")

async def cmd_claim_drop(msg: Message) -> None:
    try:
        if not await guard_message(msg):
            return
        # Простая механика: первым 5 игрокам +100 случайно
        if random.random() < 0.4:
            amount = random.randint(50, 500)
            await update_balance(msg.from_user.id, amount)
            await safe_reply(msg, f"🎁 Вам досталось <code>{fmt(amount)}</code> TOKENS!")
    except Exception as e:
        log.error(f"cmd_claim_drop error: {e}")

# ============================================================
# ОБРАБОТЧИКИ CALLBACK НАВИГАЦИИ
# ============================================================
async def cb_back_main_handler(cb: CallbackQuery) -> None:
    await cb_back_main(cb)

# ============================================================
# РОУТИНГ
# ============================================================
async def _resolve_username_from_text(msg: Message, arg: str) -> Optional[int]:
    return await _resolve_target(msg, arg)

router.message.register(cmd_start, CommandStart())
router.message.register(cmd_help, Command("help"))
router.message.register(cmd_profile, Command("profile"))
router.message.register(cmd_top, Command("top"))
router.message.register(cmd_bonus, Command("bonus"))
router.message.register(cmd_donate, Command("donate"))
router.message.register(cmd_support, Command("support"))
router.message.register(cmd_chats, Command("chats"))
router.message.register(cmd_clan, Command("clan"))

router.message.register(cmd_dice_game, F.text.regexp(r"^(кости|дартс|баскет|футбол|боулинг|бж|слоты)\s+\d+"))
router.message.register(cmd_mines, F.text.regexp(r"^мины\s+\d+"))
router.message.register(cmd_duel, F.text.regexp(r"^дуэль\s+"))
router.message.register(cmd_roulette_start_text, F.text.lower() == "старт")
router.message.register(cmd_roulette_bet, F.text.regexp(r"^(к|ч|красное|черное|чёрное)\s+\d+|^\d+\s+(чет|нечет|чёт|нечёт)|^0\s+\d+|^\d+\s+[\d\s\-]+$"))
router.message.register(cmd_promo, F.text.regexp(r"^промо\s+"))
router.message.register(cmd_claim_drop, F.text.lower() == "забрать")

# Menu buttons (Reply)
router.message.register(lambda m: cmd_dice_game(m, "кости"), F.text == "🎮 Игры")
router.message.register(cmd_bonus, F.text == "🎁 Бонус")
router.message.register(cmd_donate, F.text == "💎 Донат")
router.message.register(cmd_profile, F.text == "👤 Профиль")
router.message.register(cmd_clan, F.text == "🛡 Клан")
router.message.register(cmd_top, F.text == "🏆 Топ")
router.message.register(cmd_chats, F.text == "💬 Чаты")
router.message.register(cmd_support, F.text == "🆘 Поддержка")

# Callbacks: menu
router.callback_query.register(cb_games_menu, F.data == "games_menu")
router.callback_query.register(cb_game_info, F.data.startswith("game_info:"))
router.callback_query.register(cb_back_main, F.data == "back_main")
router.callback_query.register(cb_back_bonus, F.data == "back_bonus")
# Profile
router.callback_query.register(cb_prof_settings, F.data == "prof_settings")
router.callback_query.register(cb_prof_lang, F.data == "prof_lang")
router.callback_query.register(cb_prof_toggle_hide, F.data == "prof_toggle_hide")
router.callback_query.register(cb_prof_toggle_block, F.data == "prof_toggle_block")
router.callback_query.register(cb_prof_history, F.data == "prof_history")
router.callback_query.register(cb_prof_vip, F.data == "prof_vip")
router.callback_query.register(cb_buy_vip, F.data == "prof_buy_vip")
router.callback_query.register(cb_prof_back, F.data == "prof_back")
# Bonus
router.callback_query.register(cb_bonus_claim, F.data == "bonus_claim")
router.callback_query.register(cb_bonus_promo, F.data == "bonus_promo")
# Donate
router.callback_query.register(cb_donate_pack, F.data.startswith("donate_pack:"))
# Mines
router.callback_query.register(cb_mine_open, F.data.startswith("mine:"))
router.callback_query.register(cb_mine_cashout, F.data == "mine_cashout")
router.callback_query.register(cb_mine_noop, F.data == "mine_noop")
# Roulette
router.callback_query.register(cb_roulette_start, F.data == "roulette_start")
router.callback_query.register(cb_roulette_repeat, F.data == "roulette_repeat")
router.callback_query.register(cb_roulette_double, F.data == "roulette_double")
# Duels
router.callback_query.register(cb_duel_accept, F.data.startswith("duel_accept:"))
router.callback_query.register(cb_duel_decline, F.data.startswith("duel_decline:"))

# Admin (all text messages starting with @)
@router.message(F.text.regexp(r"^@\w+"))
async def admin_router(msg: Message) -> None:
    try:
        if msg.from_user and msg.from_user.id == ADMIN_ID:
            await cmd_admin(msg)
    except Exception as e:
        log.error(f"admin_router error: {e}")

router.pre_checkout_query.register(pre_checkout_handler)
router.message.register(successful_payment_handler, F.successful_payment)

# Клан (команды с префиксом)
router.message.register(cmd_clan_action, F.text.regexp(r"^клан\s+"))

# ============================================================
# ПЛАНИРОВЩИК
# ============================================================
def setup_scheduler() -> None:
    scheduler.add_job(event_happy_hour_start, CronTrigger(day_of_week="sat", hour=18, minute=0))
    scheduler.add_job(event_happy_hour_end, CronTrigger(day_of_week="sat", hour=19, minute=0))
    scheduler.add_job(event_auto_drop, IntervalTrigger(minutes=30))
    scheduler.add_job(event_jackpot, IntervalTrigger(hours=6))

# ============================================================
# MAIN
# ============================================================
async def main() -> None:
    logging.info("Starting TOKENS bot...")
    runner = await start_web_server()
    await on_startup()
    setup_scheduler()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"delete_webhook: {e}")
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await runner.cleanup()
        except Exception:
            pass
        if scheduler.running:
            scheduler.shutdown(wait=False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
    except Exception as e:
        log.critical(f"Fatal error: {e}")