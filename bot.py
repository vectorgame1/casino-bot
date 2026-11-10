# bot.py
# TOKENS Casino Bot - aiogram 3.x / aiosqlite / aiohttp / apscheduler
# Python 3.13 ready

import os
import re
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

import aiosqlite
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    ChatMemberUpdated, ChatPermissions,
)
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.default import DefaultBotProperties

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = "tokens_casino.db"

STAR_RATE = 7500           # 1⭐ = 7500 TOKENS
DICE_AUTODELETE_SEC = 60
DUEL_COMMISSION = 0.05
MINES_MULT_STEP = 0.15

CHAT_GAME = "https://t.me/tokenplays"
CHAT_EXCHANGE = "https://t.me/Tokenschange"
CHAT_NEWS = "https://t.me/TokenCasinoTournaments"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("tokens")

if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
        log.info("Old DB removed: %s", DB_PATH)
    except Exception as e:
        log.warning("Cannot remove old DB: %s", e)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler()

# Active roulette sessions: chat_id -> dict
roulette_sessions: Dict[int, dict] = {}
# Active mines: user_id -> dict
mines_sessions: Dict[int, dict] = {}
# Active duels: duel_id -> dict
duel_sessions: Dict[str, dict] = {}
_duel_seq = 0

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            vip INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            notifications INTEGER DEFAULT 1,
            lang TEXT DEFAULT 'RU',
            banned INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            games_enabled INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS event_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            bet INTEGER,
            win INTEGER,
            numbers TEXT,
            color TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS games_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game TEXT,
            bet INTEGER,
            win INTEGER,
            result TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS bonus_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            amount INTEGER,
            claimed_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS roulette_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            bet_type TEXT,
            bet_value TEXT,
            amount INTEGER,
            payout INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            created_at TEXT
        );
        """)
        await db.commit()
    log.info("DB initialized")


async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def ensure_user(user_id: int, username: Optional[str] = None) -> dict:
    u = await get_user(user_id)
    if u:
        if username and u["username"] != username:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
                await db.commit()
        return u
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, username, balance, created_at) VALUES(?,?,?,?)",
            (user_id, username or "", 0, datetime.utcnow().isoformat()),
        )
        await db.commit()
    return await get_user(user_id)


async def add_balance(user_id: int, amount: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        await db.commit()


async def set_balance(user_id: int, amount: int):
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (max(0, amount), user_id))
        await db.commit()


async def try_withdraw(user_id: int, amount: int) -> bool:
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        bal = row[0] if row else 0
        if bal < amount:
            return False
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        await db.commit()
        return True


async def log_game(user_id: int, game: str, bet: int, win: int, result: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO games_log(user_id, game, bet, win, result, created_at) VALUES(?,?,?,?,?,?)",
            (user_id, game, bet, win, result, datetime.utcnow().isoformat()),
        )
        await db.execute("UPDATE users SET games = games + 1, wins = wins + ? WHERE user_id=?",
                         (1 if win > 0 else 0, user_id))
        await db.commit()


async def get_history(user_id: int, limit: int = 10) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM games_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        )
        return [dict(r) for r in await cur.fetchall()]


async def chat_games_enabled(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT games_enabled FROM chat_settings WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return True if row is None else bool(row[0])


async def set_chat_games(chat_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_settings(chat_id, games_enabled) VALUES(?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET games_enabled=excluded.games_enabled",
            (chat_id, 1 if enabled else 0),
        )
        await db.commit()


async def add_event_chat(chat_id: int, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO event_chats(chat_id, title, added_at) VALUES(?,?,?)",
            (chat_id, title, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_event_chats() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id FROM event_chats")
        return [r[0] for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------------------------
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Как играть"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="💎 Донат"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="💬 Чаты"), KeyboardButton(text="🆘 Поддержка")],
        [KeyboardButton(text="📖 Команды"), KeyboardButton(text="🏆 Топ")],
    ], resize_keyboard=True)


def back_kb(target: str = "nav_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]
    ])


def fmt(v: int) -> str:
    return f"{v:,}".replace(",", " ")


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------
class BuyStars(StatesGroup):
    amount = State()
    custom = State()


class MinesFSM(StatesGroup):
    play = State()


class DuelFSM(StatesGroup):
    choose_bet = State()


# ---------------------------------------------------------------------------
# BASIC COMMANDS
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message):
    if msg.chat.type != ChatType.PRIVATE:
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    u = await get_user(msg.from_user.id)
    text = (
        f"👋 <b>Добро пожаловать в TOKENS Casino!</b>\n\n"
        f"💎 Баланс: <b>{fmt(u['balance'])} TOKENS</b>\n\n"
        f"Курс: <b>{fmt(STAR_RATE)} TOKENS</b> = 1⭐\n\n"
        f"Используй меню ниже, чтобы начать."
    )
    await msg.answer(text, reply_markup=main_kb())


@router.message(F.text == "🎮 Как играть")
async def how_to_play(msg: Message):
    text = (
        "🎮 <b>Как играть</b>\n\n"
        "1️⃣ Пополни баланс через 💎 <b>Донат</b> (звёздами).\n"
        "2️⃣ Зайди в 🎰 <b>Игровой чат</b> и играй в кубики, мины, рулетку и дуэли.\n\n"
        "🎲 <b>Кубики</b>: ставка + бросок. Больше 3 — выигрыш x2.\n"
        "💣 <b>Мины</b>: 5x5, 3 мины. Открывай клетки, забирай выигрыш.\n"
        "⚔️ <b>Дуэли</b>: вызови игрока и сразись в кубиках.\n"
        "🎡 <b>Рулетка</b>: напиши <code>старт</code> в чате.\n\n"
        "📌 Ставки: <code>к 1000</code> (красное), <code>ч 500</code> (чёрное), "
        "<code>1000 чет</code>, <code>1000 нечет</code>, <code>0 100</code>, "
        "<code>1000 1 2 3</code>, <code>500 10-20</code>."
    )
    await msg.answer(text, reply_markup=main_kb())


@router.message(F.text == "🎁 Бонус")
async def bonus_menu(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    text = (
        f"🎁 <b>Бонусы</b>\n\n"
        f"Твой баланс: <b>{fmt(u['balance'])} TOKENS</b>\n\n"
        "Следи за авто-дропами в наших чатах — раз в 2 часа!\n"
        "Также заходи в игровой чат за эксклюзивными бонусами."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await msg.answer(text, reply_markup=kb)


@router.message(F.text == "💎 Донат")
async def donate_menu(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    text = (
        f"💎 <b>Пополнение баланса</b>\n\n"
        f"Курс: <b>{fmt(STAR_RATE)} TOKENS</b> за 1⭐\n"
        f"Пример: 100⭐ = <b>{fmt(100 * STAR_RATE)} TOKENS</b>\n\n"
        f"Твой баланс: <b>{fmt(u['balance'])} TOKENS</b>\n\n"
        "Выбери сумму покупки:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50⭐", callback_data="buy_50"),
         InlineKeyboardButton(text="100⭐", callback_data="buy_100")],
        [InlineKeyboardButton(text="250⭐", callback_data="buy_250"),
         InlineKeyboardButton(text="500⭐", callback_data="buy_500")],
        [InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await msg.answer(text, reply_markup=kb)


@router.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    vip = "⭐ VIP" if u["vip"] else "Обычный"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n"
        f"💎 Баланс: <b>{fmt(u['balance'])} TOKENS</b>\n"
        f"🎖 Статус: {vip}\n"
        f"🎮 Игр: <b>{u['games']}</b> | 🏆 Побед: <b>{u['wins']}</b>\n"
        f"🔔 Уведомления: {'вкл' if u['notifications'] else 'выкл'}\n"
        f"🌐 Язык: {u['lang']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="prof_settings")],
        [InlineKeyboardButton(text="📜 История", callback_data="prof_history")],
        [InlineKeyboardButton(text="🌐 Язык", callback_data="prof_lang")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await msg.answer(text, reply_markup=kb)


@router.message(F.text == "💬 Чаты")
async def chats_menu(msg: Message):
    text = "💬 <b>Наши чаты</b>\n\nВыбирай, где тебе интересно:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="💱 Чат обмена", url=CHAT_EXCHANGE)],
        [InlineKeyboardButton(text="📢 Новости", url=CHAT_NEWS)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await msg.answer(text, reply_markup=kb)


@router.message(F.text == "🆘 Поддержка")
async def support(msg: Message):
    text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Возникли вопросы? Напиши нам:\n"
        "👤 @TokenSupport\n\n"
        "Отвечаем в течение 24 часов."
    )
    await msg.answer(text, reply_markup=back_kb())


@router.message(F.text == "📖 Команды")
async def commands_list(msg: Message):
    text = (
        "📖 <b>Команды бота</b>\n\n"
        "<b>В чате:</b>\n"
        "🎲 <code>кубик 1000</code> — игра в кубик\n"
        "💣 <code>мины 1000</code> — игра в мины\n"
        "⚔️ <code>дуэль @user 1000</code> — вызов на дуэль\n"
        "🎡 <code>старт</code> — запустить рулетку\n\n"
        "<b>Ставки в рулетке:</b>\n"
        "🔴 <code>к 1000</code> — красное (x2)\n"
        "⚫ <code>ч 500</code> — чёрное (x2)\n"
        "🎯 <code>1000 чет</code> / <code>1000 нечет</code> (x2)\n"
        "0️⃣ <code>0 100</code> — зеро (x36)\n"
        "🔢 <code>1000 1 2 3</code> — числа (x36)\n"
        "📏 <code>500 10-20</code> — диапазон (x3)"
    )
    await msg.answer(text, reply_markup=back_kb())


@router.message(F.text == "🏆 Топ")
async def top_menu(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10"
        )
        rows = await cur.fetchall()
    lines = ["🏆 <b>Топ-10 игроков</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (uname, bal) in enumerate(rows):
        name = f"@{uname}" if uname else "Игрок"
        lines.append(f"{medals[i]} {name} — <b>{fmt(bal)}</b> TOKENS")
    if not rows:
        lines.append("Пока пусто.")
    await msg.answer("\n".join(lines), reply_markup=back_kb())


# ---------------------------------------------------------------------------
# NAV CALLBACKS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "nav_menu")
async def nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "🏠 <b>Главное меню</b>\n\nВыбери действие в меню ниже.",
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# DONATE FLOW
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("buy_"))
async def buy_stars(cb: CallbackQuery, state: FSMContext):
    if cb.data == "buy_custom":
        await state.set_state(BuyStars.custom)
        await cb.message.edit_text(
            "✍️ Введи количество звёзд (целое число, от 1 до 10000):",
            reply_markup=back_kb(),
        )
        await cb.answer()
        return
    try:
        stars = int(cb.data.split("_")[1])
    except ValueError:
        await cb.answer("Ошибка", show_alert=True)
        return
    await process_stars(cb, state, stars)


@router.message(BuyStars.custom)
async def buy_custom_stars(msg: Message, state: FSMContext):
    try:
        stars = int(msg.text.strip())
        if not (1 <= stars <= 10000):
            raise ValueError
    except Exception:
        await msg.answer("❌ Некорректное число. Введи целое число от 1 до 10000.")
        return
    await state.clear()
    # direct grant (в реальном проекте — через Telegram Stars invoice)
    tokens = stars * STAR_RATE
    await add_balance(msg.from_user.id, tokens)
    await msg.answer(
        f"✅ Успешно начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐",
        reply_markup=main_kb(),
    )


async def process_stars(cb: CallbackQuery, state: FSMContext, stars: int):
    # В реальном проекте используем Telegram Stars invoice.
    # Здесь — прямое зачисление после подтверждения.
    tokens = stars * STAR_RATE
    await add_balance(cb.from_user.id, tokens)
    await state.clear()
    try:
        await cb.message.edit_text(
            f"✅ Оплата {stars}⭐ прошла успешно!\n"
            f"💎 Начислено: <b>{fmt(tokens)} TOKENS</b>",
            reply_markup=main_kb(),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"✅ Начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐"
        )
    await cb.answer("Оплачено")


# ---------------------------------------------------------------------------
# PROFILE CALLBACKS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "prof_settings")
async def prof_settings(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    notif = "вкл" if u["notifications"] else "выкл"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 Уведомления: {notif}", callback_data="toggle_notif")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")],
    ])
    await cb.message.edit_text("⚙️ <b>Настройки</b>", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "toggle_notif")
async def toggle_notif(cb: CallbackQuery):
    await ensure_user(cb.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id=?",
                         (cb.from_user.id,))
        await db.commit()
    u = await get_user(cb.from_user.id)
    notif = "вкл" if u["notifications"] else "выкл"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 Уведомления: {notif}", callback_data="toggle_notif")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")],
    ])
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer(f"Уведомления {notif}")


@router.callback_query(F.data == "prof_lang")
async def prof_lang(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_RU")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_EN")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")],
    ])
    await cb.message.edit_text("🌐 Выбери язык:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang(cb: CallbackQuery):
    lang = cb.data.split("_")[2]
    await ensure_user(cb.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, cb.from_user.id))
        await db.commit()
    await cb.answer(f"Язык: {lang}")
    await prof_back(cb)


@router.callback_query(F.data == "profile_back")
async def prof_back(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    vip = "⭐ VIP" if u["vip"] else "Обычный"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n"
        f"💎 Баланс: <b>{fmt(u['balance'])} TOKENS</b>\n"
        f"🎖 Статус: {vip}\n"
        f"🎮 Игр: <b>{u['games']}</b> | 🏆 Побед: <b>{u['wins']}</b>\n"
        f"🔔 Уведомления: {'вкл' if u['notifications'] else 'выкл'}\n"
        f"🌐 Язык: {u['lang']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="prof_settings")],
        [InlineKeyboardButton(text="📜 История", callback_data="prof_history")],
        [InlineKeyboardButton(text="🌐 Язык", callback_data="prof_lang")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "prof_history")
async def prof_history(cb: CallbackQuery):
    rows = await get_history(cb.from_user.id, 10)
    if not rows:
        text = "📜 <b>История пуста.</b>\nСыграй первую игру!"
    else:
        lines = ["📜 <b>Последние 10 игр:</b>\n"]
        for r in rows:
            sign = "🟢" if r["win"] > 0 else "🔴"
            lines.append(f"{sign} {r['game']} | ставка {fmt(r['bet'])} | выигрыш {fmt(r['win'])}")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


# ---------------------------------------------------------------------------
# DICE GAMES
# ---------------------------------------------------------------------------
DICE_EMOJI = {
    "кубик": "🎲", "кубики": "🎲", "кости": "🎲",
    "дартс": "🎯", "баскет": "🏀", "баскетбол": "🏀",
    "футбол": "⚽", "боулинг": "🎳", "бж": "🎰", "слоты": "🎰",
}


@router.message(F.text.regexp(r"^(кубик|кубики|кости|дартс|баскет|баскетбол|футбол|боулинг|бж|слоты)\s+\d+$"))
async def dice_game(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        await msg.reply("🎲 Играй в игровом чате: " + CHAT_GAME)
        return
    if not await chat_games_enabled(msg.chat.id):
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    parts = msg.text.lower().split()
    game = parts[0]
    try:
        bet = int(parts[1])
    except ValueError:
        return
    if bet < 10:
        await msg.reply("❌ Минимальная ставка — 10 TOKENS")
        return
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        await msg.reply("❌ Недостаточно средств на балансе.")
        return
    if not await try_withdraw(msg.from_user.id, bet):
        return
    emoji = DICE_EMOJI.get(game, "🎲")
    sent = await msg.reply_dice(emoji=emoji)
    value = sent.dice.value
    win = bet * 2 if value > 3 else 0
    if win:
        await add_balance(msg.from_user.id, win)
    await log_game(msg.from_user.id, f"dice_{game}", bet, win, f"value={value}")
    u2 = await get_user(msg.from_user.id)
    result_text = (
        f"{'🎉 Победа!' if win else '😔 Проигрыш'}\n"
        f"Результат: <b>{value}</b>\n"
        f"Выигрыш: <b>{fmt(win)}</b>\n"
        f"Баланс: <b>{fmt(u2['balance'])}</b>"
    )
    await msg.reply(result_text)

    async def auto_delete():
        await asyncio.sleep(DICE_AUTODELETE_SEC)
        try:
            await sent.delete()
        except Exception:
            pass
    asyncio.create_task(auto_delete())


# ---------------------------------------------------------------------------
# MINES GAME
# ---------------------------------------------------------------------------
def build_mines_kb(session: dict) -> InlineKeyboardMarkup:
    opened = session["opened"]
    mines = session["mines"]
    buttons = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened:
                row.append(InlineKeyboardButton(text="💎", callback_data=f"mine_open_{idx}"))
            elif idx in session.get("exploded", set()):
                row.append(InlineKeyboardButton(text="💥", callback_data="mine_noop"))
            else:
                row.append(InlineKeyboardButton(text="⬜", callback_data=f"mine_open_{idx}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="💰 Забрать", callback_data="mine_take")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text.regexp(r"^мины\s+\d+$"))
async def mines_start(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        await msg.reply("💣 Играй в игровом чате: " + CHAT_GAME)
        return
    if not await chat_games_enabled(msg.chat.id):
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    try:
        bet = int(msg.text.split()[1])
    except ValueError:
        return
    if bet < 10:
        await msg.reply("❌ Минимальная ставка — 10 TOKENS")
        return
    if msg.from_user.id in mines_sessions:
        await msg.reply("❗ У тебя уже активна игра в мины. Заверши её.")
        return
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        await msg.reply("❌ Недостаточно средств.")
        return
    if not await try_withdraw(msg.from_user.id, bet):
        return
    mines = set(random.sample(range(25), 3))
    mines_sessions[msg.from_user.id] = {
        "chat_id": msg.chat.id,
        "bet": bet,
        "mines": mines,
        "opened": set(),
        "exploded": set(),
        "msg_id": None,
    }
    kb = build_mines_kb(mines_sessions[msg.from_user.id])
    sent = await msg.reply(
        f"💣 <b>Мины</b>\nСтавка: <b>{fmt(bet)}</b>\n\n"
        f"Открывай клетки, избегай 3 мин. Множитель: 1.0 + 0.15 за клетку.\n"
        f"Забирай выигрыш в любой момент!",
        reply_markup=kb,
    )
    mines_sessions[msg.from_user.id]["msg_id"] = sent.message_id


@router.callback_query(F.data.startswith("mine_open_"))
async def mines_open(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_sessions:
        await cb.answer("Игра не найдена", show_alert=True)
        return
    s = mines_sessions[uid]
    if cb.message.chat.id != s["chat_id"]:
        await cb.answer("Не твоя игра", show_alert=True)
        return
    idx = int(cb.data.split("_")[2])
    if idx in s["opened"]:
        await cb.answer()
        return
    if idx in s["mines"]:
        s["exploded"].add(idx)
        # проигрыш
        mines_sessions.pop(uid, None)
        kb = build_mines_kb(s)
        await cb.message.edit_text(
            f"💥 <b>БУМ!</b> Ты попал на мину.\n"
            f"Ставка <b>{fmt(s['bet'])}</b> потеряна.",
            reply_markup=kb,
        )
        await log_game(uid, "mines", s["bet"], 0, "boom")
        await cb.answer("💥 Мина!")
        return
    s["opened"].add(idx)
    mult = 1.0 + len(s["opened"]) * MINES_MULT_STEP
    profit = int(s["bet"] * mult)
    kb = build_mines_kb(s)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer(f"💎 Множитель: x{mult:.2f} (забрать: {fmt(profit)})")


@router.callback_query(F.data == "mine_take")
async def mines_take(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_sessions:
        await cb.answer("Игра не найдена", show_alert=True)
        return
    s = mines_sessions.pop(uid)
    if not s["opened"]:
        await cb.answer("Открой хотя бы одну клетку!", show_alert=True)
        # вернуть игру
        mines_sessions[uid] = s
        return
    mult = 1.0 + len(s["opened"]) * MINES_MULT_STEP
    win = int(s["bet"] * mult)
    await add_balance(uid, win)
    await log_game(uid, "mines", s["bet"], win, f"cells={len(s['opened'])}")
    # показать мины
    for m in s["mines"]:
        s["exploded"].add(m)
    kb = build_mines_kb(s)
    try:
        await cb.message.edit_text(
            f"💰 <b>Ты забрал выигрыш!</b>\n"
            f"Открыто клеток: <b>{len(s['opened'])}</b>\n"
            f"Множитель: <b>x{mult:.2f}</b>\n"
            f"Выигрыш: <b>{fmt(win)} TOKENS</b>",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        pass
    await cb.answer(f"💰 +{fmt(win)}")


@router.callback_query(F.data == "mine_noop")
async def mines_noop(cb: CallbackQuery):
    await cb.answer()


# ---------------------------------------------------------------------------
# DUELS
# ---------------------------------------------------------------------------
@router.message(F.text.regexp(r"^дуэль\s+@\w+\s+\d+$"))
async def duel_start(msg: Message):
    global _duel_seq
    if msg.chat.type == ChatType.PRIVATE:
        await msg.reply("⚔️ Дуэли только в игровом чате: " + CHAT_GAME)
        return
    if not await chat_games_enabled(msg.chat.id):
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    parts = msg.text.split()
    target_username = parts[1].lstrip("@")
    try:
        bet = int(parts[2])
    except ValueError:
        return
    if bet < 10:
        await msg.reply("❌ Минимальная ставка — 10 TOKENS")
        return
    # find target
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (target_username,))
        row = await cur.fetchone()
    if not row:
        await msg.reply("❌ Игрок не найден в базе. Пусть напишет боту /start в ЛС.")
        return
    target_id = row[0]
    if target_id == msg.from_user.id:
        await msg.reply("❌ Нельзя вызвать самого себя.")
        return
    me = await get_user(msg.from_user.id)
    target = await get_user(target_id)
    if me["balance"] < bet:
        await msg.reply("❌ Недостаточно средств.")
        return
    if target["balance"] < bet:
        await msg.reply("❌ У соперника недостаточно средств.")
        return
    _duel_seq += 1
    did = f"d{_duel_seq}_{int(time.time())}"
    duel_sessions[did] = {
        "challenger": msg.from_user.id,
        "target": target_id,
        "bet": bet,
        "chat_id": msg.chat.id,
        "challenger_name": msg.from_user.username or str(msg.from_user.id),
        "target_name": target_username,
        "resolved": False,
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"duel_accept_{did}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"duel_decline_{did}")],
    ])
    await msg.reply(
        f"⚔️ <b>Вызов на дуэль!</b>\n\n"
        f"@{msg.from_user.username or msg.from_user.id} → @{target_username}\n"
        f"Ставка: <b>{fmt(bet)} TOKENS</b>\n"
        f"Комиссия: {int(DUEL_COMMISSION*100)}%\n\n"
        f"@ {target_username}, примешь вызов?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("duel_decline_"))
async def duel_decline(cb: CallbackQuery):
    did = cb.data[len("duel_decline_"):]
    s = duel_sessions.get(did)
    if not s:
        await cb.answer("Дуэль уже завершена", show_alert=True)
        return
    if cb.from_user.id != s["target"]:
        await cb.answer("Это не твой вызов", show_alert=True)
        return
    duel_sessions.pop(did, None)
    try:
        await cb.message.edit_text(f"❌ Дуэль отклонена @{s['target_name']}.")
    except TelegramBadRequest:
        pass
    await cb.answer("Отклонено")


@router.callback_query(F.data.startswith("duel_accept_"))
async def duel_accept(cb: CallbackQuery):
    did = cb.data[len("duel_accept_"):]
    s = duel_sessions.get(did)
    if not s:
        await cb.answer("Дуэль уже завершена", show_alert=True)
        return
    if cb.from_user.id != s["target"]:
        await cb.answer("Это не твой вызов", show_alert=True)
        return
    if s["resolved"]:
        await cb.answer("Уже обработано", show_alert=True)
        return
    s["resolved"] = True
    bet = s["bet"]
    if not await try_withdraw(s["challenger"], bet):
        await cb.answer("У вызывающего нет средств", show_alert=True)
        return
    if not await try_withdraw(s["target"], bet):
        await add_balance(s["challenger"], bet)
        await cb.answer("У тебя нет средств", show_alert=True)
        return
    pot = bet * 2
    commission = int(pot * DUEL_COMMISSION)
    prize = pot - commission
    # roll
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    while dice1 == dice2:
        dice2 = random.randint(1, 6)
    winner = s["challenger"] if dice1 > dice2 else s["target"]
    await add_balance(winner, prize)
    winner_name = s["challenger_name"] if winner == s["challenger"] else s["target_name"]
    text = (
        f"⚔️ <b>Дуэль завершена!</b>\n\n"
        f"@{s['challenger_name']} 🎲 <b>{dice1}</b>\n"
        f"@{s['target_name']} 🎲 <b>{dice2}</b>\n\n"
        f"🏆 Победитель: @{winner_name}\n"
        f"💰 Приз: <b>{fmt(prize)}</b> (комиссия {fmt(commission)})"
    )
    try:
        await cb.message.edit_text(text)
    except TelegramBadRequest:
        await cb.message.answer(text)
    await log_game(s["challenger"], "duel", bet, prize if winner == s["challenger"] else 0, f"{dice1}-{dice2}")
    await log_game(s["target"], "duel", bet, prize if winner == s["target"] else 0, f"{dice2}-{dice1}")
    duel_sessions.pop(did, None)
    await cb.answer("🏆")


# ---------------------------------------------------------------------------
# ROULETTE PARSER
# ---------------------------------------------------------------------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def parse_roulette_bet(text: str) -> Optional[dict]:
    """
    Возвращает dict:
      {"type": "color", "value": "red"/"black"/"zero", "amount": int}
      {"type": "parity", "value": "even"/"odd", "amount": int}
      {"type": "numbers", "value": [int,...], "amount": int}
      {"type": "range", "value": (start, end), "amount": int}
    """
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)

    # color forms: "к 1000", "ч 500", "красное 1000", "черное 1000"
    m = re.match(r"^(к|красное|красн)\s+(\d+)$", t)
    if m:
        return {"type": "color", "value": "red", "amount": int(m.group(2))}
    m = re.match(r"^(ч|черное|черн)\s+(\d+)$", t)
    if m:
        return {"type": "color", "value": "black", "amount": int(m.group(2))}

    # zero forms: "0 100" or "зеро 100"
    m = re.match(r"^(0|зеро|zero)\s+(\d+)$", t)
    if m:
        return {"type": "color", "value": "zero", "amount": int(m.group(2))}

    # parity after: "1000 чет", "1000 нечет"
    m = re.match(r"^(\d+)\s+(чет|чёт|even)$", t)
    if m:
        return {"type": "parity", "value": "even", "amount": int(m.group(1))}
    m = re.match(r"^(\d+)\s+(нечет|нечёт|odd)$", t)
    if m:
        return {"type": "parity", "value": "odd", "amount": int(m.group(1))}

    # range: "500 10-20"
    m = re.match(r"^(\d+)\s+(\d+)\s*-\s*(\d+)$", t)
    if m:
        amount = int(m.group(1))
        a, b = int(m.group(2)), int(m.group(3))
        if a > b:
            a, b = b, a
        if not (0 <= a <= 36 and 0 <= b <= 36):
            return None
        return {"type": "range", "value": (a, b), "amount": amount}

    # numbers list: "1000 1 2 3" or "1000 1,2,3"
    m = re.match(r"^(\d+)\s+(.+)$", t)
    if m:
        amount = int(m.group(1))
        rest = m.group(2)
        parts = re.split(r"[,\s]+", rest.strip())
        try:
            nums = [int(p) for p in parts if p]
        except ValueError:
            return None
        if not nums:
            return None
        if not all(0 <= n <= 36 for n in nums):
            return None
        return {"type": "numbers", "value": nums, "amount": amount}
    return None


# ---------------------------------------------------------------------------
# ROULETTE COMMANDS
# ---------------------------------------------------------------------------
@router.message(F.text.lower() == "старт")
async def roulette_start(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        await msg.reply("🎡 Рулетка запускается только в игровом чате: " + CHAT_GAME)
        return
    if not await chat_games_enabled(msg.chat.id):
        return
    if msg.chat.id in roulette_sessions:
        await msg.reply("❗ Рулетка уже идёт в этом чате. Подожди результата.")
        return
    # require admin or just anyone? Let anyone with permission
    await ensure_user(msg.from_user.id, msg.from_user.username)
    roulette_sessions[msg.chat.id] = {
        "bets": {},
        "started_by": msg.from_user.id,
        "started_at": time.time(),
        "message_id": None,
        "resolved": False,
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data="roul_repeat"),
         InlineKeyboardButton(text="⏫ Удвоить", callback_data="roul_double")],
    ])
    sent = await msg.reply(
        "🎡 <b>РУЛЕТКА — СТАВКИ ОТКРЫТЫ!</b>\n\n"
        "📌 Форматы ставок:\n"
        "🔴 <code>к 1000</code> — красное (x2)\n"
        "⚫ <code>ч 500</code> — чёрное (x2)\n"
        "🎯 <code>1000 чет</code> / <code>1000 нечет</code> (x2)\n"
        "0️⃣ <code>0 100</code> — зеро (x36)\n"
        "🔢 <code>1000 1 2 3</code> — числа (x36)\n"
        "📏 <code>500 10-20</code> — диапазон (x3)\n\n"
        "⏳ Крутим через 20 секунд...",
        reply_markup=kb,
    )
    roulette_sessions[msg.chat.id]["message_id"] = sent.message_id
    asyncio.create_task(roulette_spin(msg.chat.id))


@router.message(F.text.regexp(r"^(\d+.*)$") | F.text.regexp(r"^(к|ч|красное|черное|0|зеро|zero)\s+\d+$"))
async def roulette_bet_handler(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        return
    chat_id = msg.chat.id
    if chat_id not in roulette_sessions:
        return
    s = roulette_sessions[chat_id]
    if s["resolved"]:
        return
    parsed = parse_roulette_bet(msg.text or "")
    if not parsed:
        return
    amount = parsed["amount"]
    if amount < 10:
        await msg.reply("❌ Минимальная ставка — 10 TOKENS")
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    if not await try_withdraw(msg.from_user.id, amount):
        await msg.reply("❌ Недостаточно средств.")
        return
    uid = msg.from_user.id
    if uid not in s["bets"]:
        s["bets"][uid] = []
    s["bets"][uid].append(parsed)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO roulette_participants(chat_id, user_id, bet_type, bet_value, amount, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (chat_id, uid, parsed["type"], str(parsed["value"]), amount,
             datetime.utcnow().isoformat()),
        )
        await db.commit()
    emoji = {"red": "🔴", "black": "⚫", "zero": "0️⃣",
             "even": "🎯", "odd": "🎯", "numbers": "🔢", "range": "📏"}
    kind = parsed["type"]
    label = emoji.get(parsed["value"] if kind == "color" else kind, "🎯")
    await msg.reply(f"✅ Ставка принята: {label} <b>{fmt(amount)}</b> TOKENS")


async def roulette_spin(chat_id: int):
    await asyncio.sleep(20)
    s = roulette_sessions.get(chat_id)
    if not s or s["resolved"]:
        return
    s["resolved"] = True
    # отправка гифки
    gif_path = "images/roulette.gif"
    try:
        if os.path.exists(gif_path):
            from aiogram.types import FSInputFile
            await bot.send_animation(chat_id, FSInputFile(gif_path))
        else:
            await bot.send_message(chat_id, "🎡 Крутим рулетку...")
    except Exception as e:
        log.warning("gif send failed: %s", e)
        try:
            await bot.send_message(chat_id, "🎡 Крутим рулетку...")
        except Exception:
            pass
    await asyncio.sleep(3)
    number = random.randint(0, 36)
    if number == 0:
        color = "zero"
    elif number in RED_NUMBERS:
        color = "red"
    else:
        color = "black"
    color_emoji = {"red": "🔴", "black": "⚫", "zero": "🟢"}[color]
    payout_total = 0
    winners_lines = []
    for uid, bets in s["bets"].items():
        for b in bets:
            win = 0
            t = b["type"]
            v = b["value"]
            amt = b["amount"]
            if t == "color":
                if v == color:
                    win = amt * 36 if color == "zero" else amt * 2
            elif t == "parity":
                if number != 0:
                    is_even = number % 2 == 0
                    if (v == "even" and is_even) or (v == "odd" and not is_even):
                        win = amt * 2
            elif t == "numbers":
                if number in v:
                    win = amt * 36
            elif t == "range":
                a, b = v
                if a <= number <= b:
                    win = amt * 3
            if win > 0:
                await add_balance(uid, win)
                payout_total += win
                winners_lines.append(f"🆔 <code>{uid}</code> +{fmt(win)}")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO roulette_logs(chat_id, user_id, bet, win, numbers, color, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (chat_id, uid, amt, win, str(number), color, datetime.utcnow().isoformat()),
                )
                await db.commit()
    text = (
        f"🎡 <b>Результат рулетки!</b>\n\n"
        f"Выпало число: {color_emoji} <b>{number}</b>\n"
        f"Цвет: <b>{ {'red':'красное','black':'чёрное','zero':'зеро'}[color] }</b>\n\n"
    )
    if winners_lines:
        text += "🏆 <b>Победители:</b>\n" + "\n".join(winners_lines[:15])
        if len(winners_lines) > 15:
            text += f"\n... и ещё {len(winners_lines) - 15}"
        text += f"\n\n💰 Всего выплачено: <b>{fmt(payout_total)}</b> TOKENS"
    else:
        text += "😔 Победителей нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data="roul_repeat"),
         InlineKeyboardButton(text="⏫ Удвоить", callback_data="roul_double")],
    ])
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:
        log.warning("spin result send: %s", e)
    # store last for repeat/double
    s["result"] = {"number": number, "color": color}
    # keep session for 60 sec for repeat/double
    async def cleanup():
        await asyncio.sleep(120)
        roulette_sessions.pop(chat_id, None)
    asyncio.create_task(cleanup())


@router.callback_query(F.data == "roul_repeat")
async def roulette_repeat(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    s = roulette_sessions.get(chat_id)
    if not s or "result" not in s:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    # restart session with same bets
    old_bets = s.get("bets", {})
    roulette_sessions[chat_id] = {
        "bets": {},
        "started_by": cb.from_user.id,
        "started_at": time.time(),
        "message_id": None,
        "resolved": False,
    }
    for uid, bets in old_bets.items():
        for b in bets:
            amt = b["amount"]
            if await try_withdraw(uid, amt):
                roulette_sessions[chat_id]["bets"].setdefault(uid, []).append(b)
    await cb.answer("🔄 Повтор!")
    await bot.send_message(chat_id, "🎡 <b>РУЛЕТКА — СТАВКИ ОТКРЫТЫ!</b>\nПовтор прошлых ставок. Крутим через 20 сек...")
    asyncio.create_task(roulette_spin(chat_id))


@router.callback_query(F.data == "roul_double")
async def roulette_double(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    s = roulette_sessions.get(chat_id)
    if not s or "result" not in s:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    old_bets = s.get("bets", {})
    roulette_sessions[chat_id] = {
        "bets": {},
        "started_by": cb.from_user.id,
        "started_at": time.time(),
        "message_id": None,
        "resolved": False,
    }
    for uid, bets in old_bets.items():
        for b in bets:
            nb = dict(b)
            nb["amount"] = b["amount"] * 2
            if await try_withdraw(uid, nb["amount"]):
                roulette_sessions[chat_id]["bets"].setdefault(uid, []).append(nb)
    await cb.answer("⏫ Удвоено!")
    await bot.send_message(chat_id, "🎡 <b>РУЛЕТКА — СТАВКИ ОТКРЫТЫ!</b>\nСтавки удвоены. Крутим через 20 сек...")
    asyncio.create_task(roulette_spin(chat_id))


# ---------------------------------------------------------------------------
# ADMIN @ COMMANDS (AI helper)
# ---------------------------------------------------------------------------
def is_admin(msg: Message) -> bool:
    return ADMIN_ID and msg.from_user and msg.from_user.id == ADMIN_ID


def mention_to_id(text: str) -> Optional[int]:
    m = re.search(r"@(\w+)", text)
    return None


async def find_user_by_username(username: str) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (username,))
        row = await cur.fetchone()
        return row[0] if row else None


@router.message(F.text.regexp(r"^@"))
async def admin_at_commands(msg: Message):
    if not is_admin(msg):
        return
    text = msg.text.strip()
    low = text.lower()

    if low.startswith("@помощь"):
        await msg.reply(
            "🤖 <b>ИИ-помощник</b>\n\n"
            "<code>@выдать @user 1000</code> — выдать баланс\n"
            "<code>@дроп 1000</code> — создать бонус в чате\n"
            "<code>@бан @user</code> / <code>@разбан @user</code>\n"
            "<code>@стата</code> — статистика\n"
            "<code>@игры_выкл</code> / <code>@игры_вкл</code> — управление играми в чате\n"
            "<code>@ивент_чат_добавить</code> — добавить чат в авто-дроп\n"
            "<code>@ивент_чат_удалить</code> — убрать из авто-дроп\n"
            "<code>@рассылка</code> — авто-дроп в event-чаты"
        )
        return

    if low.startswith("@выдать"):
        m = re.match(r"^@выдать\s+@(\w+)\s+(\d+)$", low)
        if not m:
            await msg.reply("❌ Формат: @выдать @user 1000")
            return
        uname, amount = m.group(1), int(m.group(2))
        uid = await find_user_by_username(uname)
        if not uid:
            await msg.reply("❌ Пользователь не найден в базе.")
            return
        await add_balance(uid, amount)
        await msg.reply(f"✅ Выдано <b>{fmt(amount)}</b> TOKENS @{uname}")
        return

    if low.startswith("@дроп"):
        m = re.match(r"^@дроп\s+(\d+)$", low)
        if not m:
            await msg.reply("❌ Формат: @дроп 1000")
            return
        amount = int(m.group(1))
        await send_bonus_drop(msg.chat.id, amount)
        return

    if low.startswith("@бан"):
        m = re.match(r"^@бан\s+@(\w+)$", low)
        if not m:
            await msg.reply("❌ Формат: @бан @user")
            return
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
            await db.commit()
        await msg.reply(f"⛔ @{m.group(1)} забанен.")
        return

    if low.startswith("@разбан"):
        m = re.match(r"^@разбан\s+@(\w+)$", low)
        if not m:
            await msg.reply("❌ Формат: @разбан @user")
            return
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
            await db.commit()
        await msg.reply(f"✅ @{m.group(1)} разбанен.")
        return

    if low.startswith("@стата"):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT COUNT(*), SUM(balance) FROM users")
            users_count, total_bal = await cur.fetchone()
            cur = await db.execute("SELECT COUNT(*) FROM event_chats")
            ev = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(*) FROM roulette_logs")
            rl = (await cur.fetchone())[0]
        await msg.reply(
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{users_count}</b>\n"
            f"💎 Всего балансов: <b>{fmt(total_bal or 0)}</b>\n"
            f"📣 Event-чатов: <b>{ev}</b>\n"
            f"🎡 Ставок в рулетке: <b>{rl}</b>"
        )
        return

    if low.startswith("@игры_выкл"):
        if msg.chat.type == ChatType.PRIVATE:
            await msg.reply("Только в чате.")
            return
        await set_chat_games(msg.chat.id, False)
        await msg.reply("⛔ Игры в этом чате отключены.")
        return

    if low.startswith("@игры_вкл"):
        if msg.chat.type == ChatType.PRIVATE:
            await msg.reply("Только в чате.")
            return
        await set_chat_games(msg.chat.id, True)
        await msg.reply("✅ Игры включены.")
        return

    if low.startswith("@ивент_чат_добавить"):
        if msg.chat.type == ChatType.PRIVATE:
            await msg.reply("Только в чате.")
            return
        title = msg.chat.title or str(msg.chat.id)
        await add_event_chat(msg.chat.id, title)
        await msg.reply(f"✅ Чат «{title}» добавлен в авто-дроп.")
        return

    if low.startswith("@ивент_чат_удалить"):
        if msg.chat.type == ChatType.PRIVATE:
            await msg.reply("Только в чате.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM event_chats WHERE chat_id=?", (msg.chat.id,))
            await db.commit()
        await msg.reply("✅ Чат убран из авто-дроп.")
        return

    if low.startswith("@рассылка"):
        await broadcast_event_drop()
        await msg.reply("✅ Авто-дроп разослан.")
        return


# ---------------------------------------------------------------------------
# BONUS / EVENT DROPS
# ---------------------------------------------------------------------------
async def send_bonus_drop(chat_id: int, amount: int, photo: Optional[str] = None):
    caption = (
        f"🎁 <b>БОНУС!</b>\n\n"
        f"Кто первый — того и <b>{fmt(amount)} TOKENS</b>!\n"
        f"⬇️ Жми «Забрать»"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать", callback_data=f"claim_bonus_{amount}")]
    ])
    try:
        if photo and os.path.exists(photo):
            from aiogram.types import FSInputFile
            sent = await bot.send_photo(chat_id, FSInputFile(photo), caption=caption, reply_markup=kb)
        else:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb)
    except Exception as e:
        log.warning("send_bonus_drop: %s", e)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bonus_items(chat_id, message_id, amount, created_at) VALUES(?,?,?,?)",
            (chat_id, sent.message_id, amount, datetime.utcnow().isoformat()),
        )
        await db.commit()


@router.callback_query(F.data.startswith("claim_bonus_"))
async def claim_bonus(cb: CallbackQuery):
    amount = int(cb.data.split("_")[2])
    chat_id = cb.message.chat.id
    msg_id = cb.message.message_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM bonus_items WHERE chat_id=? AND message_id=?",
            (chat_id, msg_id),
        )
        row = await cur.fetchone()
        if not row:
            await cb.answer("Бонус не найден", show_alert=True)
            return
        if row["claimed_by"]:
            await cb.answer("Бонус уже забран!", show_alert=True)
            return
        await db.execute("UPDATE bonus_items SET claimed_by=? WHERE id=?", (cb.from_user.id, row["id"]))
        await db.commit()
    await ensure_user(cb.from_user.id, cb.from_user.username)
    await add_balance(cb.from_user.id, amount)
    await cb.answer(f"🎉 +{fmt(amount)} TOKENS!", show_alert=True)
    try:
        await cb.message.edit_caption(
            caption=f"🎁 Бонус забрал @{cb.from_user.username or cb.from_user.id}\n"
                    f"💰 Выигрыш: <b>{fmt(amount)}</b> TOKENS"
        )
    except Exception:
        try:
            await cb.message.edit_text(
                f"🎁 Бонус забрал @{cb.from_user.username or cb.from_user.id}\n"
                f"💰 Выигрыш: <b>{fmt(amount)}</b> TOKENS"
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AUTO DROP SCHEDULER
# ---------------------------------------------------------------------------
async def broadcast_event_drop():
    chats = await get_event_chats()
    if not chats:
        log.info("No event chats for drop")
        return
    amount = random.choice([500, 1000, 1500, 2000, 3000])
    for cid in chats:
        try:
            await send_bonus_drop(cid, amount, photo="images/bonus.jpg")
            await asyncio.sleep(1)
        except Exception as e:
            log.warning("event drop to %s failed: %s", cid, e)


async def scheduled_drop():
    log.info("Scheduled event drop running")
    await broadcast_event_drop()


# ---------------------------------------------------------------------------
# WEB SERVER (Render)
# ---------------------------------------------------------------------------
async def health(_):
    return web.Response(text="TOKENS Casino Bot is running")


async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Web server on port %s", PORT)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    await db_init()
    scheduler.add_job(scheduled_drop, "interval", hours=2, id="event_drop")
    scheduler.start()
    await start_web()
    log.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")