# bot.py — ЧАСТЬ 1
# TOKENS Casino Bot — aiogram 3.x

import os
import re
import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Optional, List, Dict

import aiosqlite
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.filters import CommandStart
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

STAR_RATE = 7500
DICE_AUTODELETE_SEC = 60
DUEL_COMMISSION = 0.05
MINES_MULT_STEP = 0.15
ROULETTE_BET_SECONDS = 30

CHAT_GAME = "https://t.me/tokenplays"
CHAT_EXCHANGE = "https://t.me/Tokenschange"
CHAT_NEWS = "https://t.me/TokenCasinoTournaments"

IMG_DIR = "images"
IMG_START = os.path.join(IMG_DIR, "start.jpg")
IMG_PROFILE = os.path.join(IMG_DIR, "profile.jpg")
IMG_DONATE = os.path.join(IMG_DIR, "donate.jpg")
IMG_BONUS = os.path.join(IMG_DIR, "bonus.jpg")
IMG_TOP = os.path.join(IMG_DIR, "top.jpg")
IMG_REF = os.path.join(IMG_DIR, "ref.jpg")
IMG_HOW = os.path.join(IMG_DIR, "how_to_play.jpg")
IMG_SUPPORT = os.path.join(IMG_DIR, "support.jpg")
IMG_CHATS = os.path.join(IMG_DIR, "chats.jpg")
IMG_COMMANDS = os.path.join(IMG_DIR, "commands.jpg")
IMG_ROULETTE_GIF = os.path.join(IMG_DIR, "roulette.gif")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tokens")

if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
    except Exception as e:
        log.warning("DB remove fail: %s", e)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler()

roulette_sessions: Dict[int, dict] = {}
mines_sessions: Dict[int, dict] = {}
duel_sessions: Dict[str, dict] = {}
_duel_seq = 0

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
            vip INTEGER DEFAULT 0, games INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            notifications INTEGER DEFAULT 1, lang TEXT DEFAULT 'RU', banned INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY, games_enabled INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS event_chats (
            chat_id INTEGER PRIMARY KEY, title TEXT, added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS roulette_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
            bet INTEGER, win INTEGER, numbers TEXT, color TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS games_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT,
            bet INTEGER, win INTEGER, result TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS bonus_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message_id INTEGER,
            amount INTEGER, claimed_by INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS roulette_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
            bet_type TEXT, bet_value TEXT, amount INTEGER, payout INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY, amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS promo_used (
            user_id INTEGER, code TEXT, used_at TEXT, PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, details TEXT, created_at TEXT
        );
        """)
        await db.commit()


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


async def try_withdraw(user_id: int, amount: int) -> bool:
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or row[0] < amount:
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
        await db.execute(
            "UPDATE users SET games = games + 1, wins = wins + ? WHERE user_id=?",
            (1 if win > 0 else 0, user_id),
        )
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


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")]
    ])


def fmt(v: int) -> str:
    return f"{v:,}".replace(",", " ")


async def send_pic_or_text(msg: Message, path: str, caption: str, markup=None):
    if os.path.exists(path):
        try:
            return await msg.answer_photo(FSInputFile(path), caption=caption, reply_markup=markup)
        except Exception as e:
            log.warning("send_photo fail %s: %s", path, e)
    return await msg.answer(caption, reply_markup=markup)


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------
class BuyStars(StatesGroup):
    custom = State()


# ---------------------------------------------------------------------------
# ТЕКСТЫ: «КАК ИГРАТЬ» — 11 ИГР ПОДРОБНО
# ---------------------------------------------------------------------------
HOW_TO_PLAY_TEXT = (
    "🎮 <b>ПОЛНЫЙ ГАЙД ПО ИГРАМ TOKENS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "<b>1️⃣ КУБИКИ (кости 🎲)</b>\n"
    "Команда: <code>кости 1000</code>\n"
    "Бот бросает кубик. Если выпало <b>4, 5 или 6</b> — ты выиграл <b>x2</b>. "
    "Если 1, 2 или 3 — ставка сгорает.\n"
    "Пример: поставил 1000 → выпало 5 → получил 2000.\n\n"

    "<b>2️⃣ ДАРТС (🎯)</b>\n"
    "Команда: <code>дартс 500</code>\n"
    "Бот бросает дротик в мишень. Результат больше 3 → <b>x2</b>.\n\n"

    "<b>3️⃣ БАСКЕТБОЛ (🏀)</b>\n"
    "Команда: <code>баскет 1000</code>\n"
    "Бот бросает мяч. Попал больше 3 → <b>x2</b>.\n\n"

    "<b>4️⃣ ФУТБОЛ (⚽)</b>\n"
    "Команда: <code>футбол 2000</code>\n"
    "Удар по воротам. Значение > 3 → <b>x2</b>.\n\n"

    "<b>5️⃣ БОУЛИНГ (🎳)</b>\n"
    "Команда: <code>боулинг 1000</code>\n"
    "Бросок шара. Сбил больше 3 кеглей → <b>x2</b>.\n\n"

    "<b>6️⃣ БЛЭКДЖЕК / БЖ (🎰)</b>\n"
    "Команда: <code>бж 1000</code>\n"
    "Крутится слот. Значение > 3 → <b>x2</b>.\n\n"

    "<b>7️⃣ СЛОТЫ (🎰)</b>\n"
    "Команда: <code>слоты 1500</code>\n"
    "Классические слоты. Выигрыш <b>x2</b> при значении > 3.\n\n"

    "<b>8️⃣ МИНЫ (💣)</b>\n"
    "Команда: <code>мины 1000</code>\n"
    "Поле 5×5. Спрятаны <b>3 мины</b>. Открываешь клетки — растёт множитель.\n"
    "Формула: <b>1.0 + (открытых × 0.15)</b>\n"
    "Кнопка «💰 Забрать» фиксирует выигрыш в любой момент.\n"
    "Попал на мину — ставка сгорает.\n"
    "Пример: открыл 4 клетки → x1.6 → забрал 1600 с 1000.\n\n"

    "<b>9️⃣ ДУЭЛИ (⚔️)</b>\n"
    "Команда: <code>дуэль @user 1000</code>\n"
    "Вызов игроку. Он жмёт «✅ Принять» или «❌ Отклонить».\n"
    "Оба бросают кубик — у кого больше, тот забирает банк.\n"
    "Комиссия бота: <b>5%</b> от банка.\n"
    "Пример: ставка 1000 у каждого → банк 2000 → победитель получает 1900.\n\n"

    "<b>🔟 РУЛЕТКА (🎡) — ГЛАВНАЯ ИГРА</b>\n"
    "Запуск: напиши <code>старт</code> в чате.\n"
    "Бот пишет: «🎰 Рулетка запущена! Принимаю ставки 30 секунд».\n\n"
    "📌 <b>Форматы ставок:</b>\n"
    "• <code>к 1000</code> — красное (x2)\n"
    "• <code>ч 500</code> — чёрное (x2)\n"
    "• <code>1000 чет</code> — чётное (x2)\n"
    "• <code>1000 нечет</code> — нечётное (x2)\n"
    "• <code>0 100</code> — зеро (x36)\n"
    "• <code>1000 1 2 3</code> — числа через пробел (x36)\n"
    "• <code>500 10-20</code> — диапазон (x3)\n\n"
    "Через 30 сек бот выводит <b>список всех ставок</b>, шлёт гифку 🎡, "
    "ждёт 3 сек и объявляет результат.\n"
    "После — кнопки <b>«🔄 Повторить»</b> и <b>«⏫ Удвоить»</b>.\n\n"

    "<b>1️⃣1️⃣ БОНУС-ДРОП (🎁)</b>\n"
    "Не игра, но часть экономики. Раз в 2 часа бот кидает бонус в чаты "
    "из списка event. Первый, кто нажмёт «🎁 Забрать» — получает сумму.\n"
    "Также админ может вручную запустить <code>@дроп 1000</code>.\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "💡 <b>Общие правила:</b>\n"
    "• Минимальная ставка: <b>10 TOKENS</b>\n"
    "• Все игры работают в ЛС и в чатах (если админ не отключил игры)\n"
    "• Игры в чате отключаются командой <code>@игры_выкл</code> (только админ)\n"
    "• Автоудаление результатов кубиков через 60 секунд\n\n"
    "Удачи и больших выигрышей! 🍀"
)


# ---------------------------------------------------------------------------
# ТЕКСТЫ: «КОМАНДЫ» — ЮЗЕРСКИЕ (БЕЗ ИГР И БЕЗ АДМИНКИ)
# ---------------------------------------------------------------------------
COMMANDS_TEXT = (
    "📖 <b>КОМАНДЫ БОТА TOKENS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "<b>💰 БАЛАНС</b>\n"
    "<code>б</code> — быстро узнать свой баланс.\n"
    "Показывает: сколько TOKENS на счету, VIP-статус, число игр и побед.\n\n"

    "<b>🏆 ТОП</b>\n"
    "<code>топ</code> — Топ-10 игроков по балансу в реальном времени.\n"
    "Медали: 🥇 🥈 🥉 — первые три места.\n\n"

    "<b>🆕 ЧТО НОВОГО</b>\n"
    "<code>что нового</code> — последние обновления бота.\n"
    "Показывает свежие фичи и нововведения.\n\n"

    "<b>💸 ПЕРЕВОД</b>\n"
    "<code>перевод @user 1000</code> — перевести TOKENS другому игроку.\n"
    "Условия:\n"
    "• Минимум 10 TOKENS\n"
    "• Получатель должен быть зарегистрирован (запускал /start)\n"
    "• Баланс должен хватать\n"
    "Зачисление мгновенное.\n\n"

    "<b>🎟 ПРОМО-КОД</b>\n"
    "<code>промо КОД</code> — активировать промо-код.\n"
    "Коды выдают админы и бот в рассылках.\n"
    "Каждый код можно активировать <b>1 раз на аккаунт</b>.\n"
    "Если код истёк или закончились использования — бот сообщит.\n\n"

    "<b>📜 ЛОГ ИГР</b>\n"
    "<code>лог</code> — последние 10 игр лично твоих.\n"
    "Показывает: игру, ставку, выигрыш, время.\n"
    "🟢 — победа, 🔴 — проигрыш.\n\n"

    "<b>👤 ПРОФИЛЬ</b>\n"
    "Кнопка <b>«👤 Профиль»</b> в меню:\n"
    "• ID, баланс, VIP-статус\n"
    "• Всего игр и побед\n"
    "• Настройки: вкл/выкл уведомления\n"
    "• История последних 10 игр\n"
    "• Переключение языка RU / EN\n\n"

    "<b>💎 ДОНАТ</b>\n"
    "Кнопка <b>«💎 Донат»</b> в меню:\n"
    "Покупка TOKENS за Telegram Stars.\n"
    f"Курс: <b>1⭐ = {fmt(STAR_RATE)} TOKENS</b>\n"
    "Быстрые суммы: 50⭐, 100⭐, 250⭐, 500⭐\n"
    "Кнопка <b>«✍️ Своя сумма»</b> — вводишь любое количество звёзд (1–10000).\n\n"

    "<b>🎁 БОНУС</b>\n"
    "Кнопка <b>«🎁 Бонус»</b> в меню:\n"
    "• Авто-дроп раз в 2 часа в игровых чатах\n"
    "• Первый нажавший «Забрать» — получает сумму\n"
    "• Следи за новостями в канале\n\n"

    "<b>💬 ЧАТЫ</b>\n"
    "Кнопка <b>«💬 Чаты»</b> в меню:\n"
    "• 🎰 Игровой чат — <code>@tokenplays</code>\n"
    "• 💱 Чат обмена — <code>@Tokenschange</code>\n"
    "• 📢 Новости — <code>@TokenCasinoTournaments</code>\n\n"

    "<b>🆘 ПОДДЕРЖКА</b>\n"
    "Кнопка <b>«🆘 Поддержка»</b> в меню:\n"
    "Связь с администрацией по любым вопросам.\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🎮 <b>Все игровые команды</b> (кости, мины, дуэли, рулетка и т.д.) "
    "описаны в разделе <b>«🎮 Как играть»</b>.\n\n"
    "🔒 Команды для админа — только у администрации.\n\n"
    "💡 Совет: добавь бота в игровой чат — там проходит всё веселье!"
)


# ---------------------------------------------------------------------------
# START + МЕНЮ
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message):
    if msg.chat.type != ChatType.PRIVATE:
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    u = await get_user(msg.from_user.id)
    caption = (
        f"👋 <b>Добро пожаловать в TOKENS Casino!</b>\n\n"
        f"💎 Твой баланс: <b>{fmt(u['balance'])} TOKENS</b>\n"
        f"⭐ Курс: <b>{fmt(STAR_RATE)}</b> TOKENS = 1⭐\n\n"
        f"Жми «🎮 Как играть» чтобы узнать про все 11 игр.\n"
        f"Жми «📖 Команды» чтобы увидеть все команды бота."
    )
    await send_pic_or_text(msg, IMG_START, caption, main_kb())


@router.message(F.text == "🎮 Как играть")
async def how_to_play(msg: Message):
    await send_pic_or_text(msg, IMG_HOW, HOW_TO_PLAY_TEXT, back_kb())
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "📖 Команды")
async def commands_list(msg: Message):
    await send_pic_or_text(msg, IMG_COMMANDS, COMMANDS_TEXT, back_kb())
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "💬 Чаты")
async def chats_menu(msg: Message):
    caption = "💬 <b>Наши чаты</b>\n\nВыбирай, где тебе интересно:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="💱 Чат обмена", url=CHAT_EXCHANGE)],
        [InlineKeyboardButton(text="📢 Новости", url=CHAT_NEWS)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await send_pic_or_text(msg, IMG_CHATS, caption, kb)
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "🆘 Поддержка")
async def support(msg: Message):
    caption = (
        "🆘 <b>Поддержка</b>\n\n"
        "По всем вопросам пиши: @ТВОЙ_ЮЗЕРНЕЙМ"
    )
    await send_pic_or_text(msg, IMG_SUPPORT, caption, back_kb())
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "🎁 Бонус")
async def bonus_menu(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    caption = (
        f"🎁 <b>Бонусы</b>\n\n"
        f"💎 Баланс: <b>{fmt(u['balance'])}</b>\n\n"
        f"Авто-дроп раз в 2 часа в игровых чатах!\n"
        f"Заходи в 🎰 Игровой чат и лови бонусы."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await send_pic_or_text(msg, IMG_BONUS, caption, kb)
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "💎 Донат")
async def donate_menu(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    caption = (
        f"💎 <b>Пополнение баланса</b>\n\n"
        f"⭐ Курс: <b>{fmt(STAR_RATE)}</b> TOKENS за 1⭐\n"
        f"💡 100⭐ = <b>{fmt(100 * STAR_RATE)}</b> TOKENS\n\n"
        f"💎 Твой баланс: <b>{fmt(u['balance'])}</b>\n\n"
        f"Выбери сумму:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50⭐", callback_data="buy_50"),
         InlineKeyboardButton(text="100⭐", callback_data="buy_100")],
        [InlineKeyboardButton(text="250⭐", callback_data="buy_250"),
         InlineKeyboardButton(text="500⭐", callback_data="buy_500")],
        [InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])
    await send_pic_or_text(msg, IMG_DONATE, caption, kb)
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username)
    vip = "⭐ VIP" if u["vip"] else "Обычный"
    caption = (
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
    await send_pic_or_text(msg, IMG_PROFILE, caption, kb)
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.message(F.text == "🏆 Топ")
async def top_menu(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()
    lines = ["🏆 <b>Топ-10 игроков</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (uname, bal) in enumerate(rows):
        name = f"@{uname}" if uname else "Игрок"
        lines.append(f"{medals[i]} {name} — <b>{fmt(bal)}</b> TOKENS")
    if not rows:
        lines.append("Пока пусто.")
    await send_pic_or_text(msg, IMG_TOP, "\n".join(lines), back_kb())
    await msg.answer("Главное меню 👇", reply_markup=main_kb())


@router.callback_query(F.data == "nav_menu")
async def nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 <b>Главное меню</b>\n\nВыбери действие в меню ниже.")
    await cb.answer()


# ---------------------------------------------------------------------------
# ЮЗЕРСКИЕ КОМАНДЫ: б, топ, что нового, перевод, промо, лог
# ---------------------------------------------------------------------------
@router.message(F.text.lower() == "б")
async def cmd_balance(msg: Message):
    await ensure_user(msg.from_user.id, msg.from_user.username)
    u = await get_user(msg.from_user.id)
    await msg.reply(
        f"💰 <b>Баланс:</b> <b>{fmt(u['balance'])}</b> TOKENS\n"
        f"🎮 Игр: {u['games']} | 🏆 Побед: {u['wins']}"
    )


@router.message(F.text.lower() == "топ")
async def cmd_top(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()
    lines = ["🏆 <b>ТОП-10:</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (uname, bal) in enumerate(rows):
        name = f"@{uname}" if uname else "Игрок"
        lines.append(f"{medals[i]} {name} — {fmt(bal)}")
    await msg.reply("\n".join(lines))


@router.message(F.text.lower() == "что нового")
async def cmd_whats_new(msg: Message):
    await msg.reply(
        "🆕 <b>Что нового в TOKENS</b>\n\n"
        "✅ 11 игр: кубики, дартс, баскет, футбол, боулинг, бж, слоты, мины, дуэли, рулетка, бонус-дроп\n"
        "✅ Рулетка с гифкой и кнопками Повторить/Удвоить\n"
        "✅ Промо-коды\n"
        "✅ Переводы между игроками\n"
        "✅ Мега-админка (30+ команд)\n"
        "✅ Авто-дроп раз в 2 часа\n"
        "✅ Профиль с историей игр и сменой языка\n\n"
        "Следи за обновлениями в @TokenCasinoTournaments"
    )


@router.message(F.text.regexp(r"^перевод\s+@\w+\s+\d+$"))
async def cmd_transfer(msg: Message):
    await ensure_user(msg.from_user.id, msg.from_user.username)
    parts = msg.text.split()
    target_username = parts[1].lstrip("@")
    try:
        amount = int(parts[2])
    except ValueError:
        return
    if amount < 10:
        await msg.reply("❌ Минимум 10 TOKENS")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (target_username,))
        row = await cur.fetchone()
    if not row:
        await msg.reply("❌ Получатель не найден. Пусть запустит /start в ЛС.")
        return
    target_id = row[0]
    if target_id == msg.from_user.id:
        await msg.reply("❌ Нельзя перевести самому себе.")
        return
    if not await try_withdraw(msg.from_user.id, amount):
        await msg.reply("❌ Недостаточно средств.")
        return
    await add_balance(target_id, amount)
    await msg.reply(f"✅ Переведено <b>{fmt(amount)}</b> TOKENS → @{target_username}")


@router.message(F.text.regexp(r"^промо\s+\S+$"))
async def cmd_promo(msg: Message):
    await ensure_user(msg.from_user.id, msg.from_user.username)
    code = msg.text.split(maxsplit=1)[1].strip().upper()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM promo_codes WHERE code=?", (code,))
        row = await cur.fetchone()
        if not row:
            await msg.reply("❌ Промо-код не найден.")
            return
        if row["used_count"] >= row["max_uses"]:
            await msg.reply("❌ Код больше не действителен (закончились активации).")
            return
        cur = await db.execute("SELECT 1 FROM promo_used WHERE user_id=? AND code=?",
                               (msg.from_user.id, code))
        if await cur.fetchone():
            await msg.reply("❌ Ты уже активировал этот код.")
            return
        await db.execute("INSERT INTO promo_used(user_id, code, used_at) VALUES(?,?,?)",
                         (msg.from_user.id, code, datetime.utcnow().isoformat()))
        await db.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code=?", (code,))
        await db.commit()
    await add_balance(msg.from_user.id, row["amount"])
    await msg.reply(f"🎟 Промо-код активирован! +<b>{fmt(row['amount'])}</b> TOKENS")


@router.message(F.text.lower() == "лог")
async def cmd_log(msg: Message):
    await ensure_user(msg.from_user.id, msg.from_user.username)
    rows = await get_history(msg.from_user.id, 10)
    if not rows:
        await msg.reply("📜 История пуста. Сыграй первую игру!")
        return
    lines = ["📜 <b>Твои последние 10 игр:</b>\n"]
    for r in rows:
        sign = "🟢" if r["win"] > 0 else "🔴"
        lines.append(f"{sign} {r['game']} | ставка {fmt(r['bet'])} | выигрыш {fmt(r['win'])}")
    await msg.reply("\n".join(lines))


# ---------------------------------------------------------------------------
# ПРОФИЛЬ CALLBACKS
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, cb.from_user.id))
        await db.commit()
    await cb.answer(f"Язык: {lang}")
    await profile_back(cb)


@router.callback_query(F.data == "profile_back")
async def profile_back(cb: CallbackQuery):
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
        text = "📜 <b>История пуста.</b>"
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
# ДОНАТ
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "buy_custom")
async def buy_custom_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BuyStars.custom)
    await cb.message.edit_text("✍️ Введи количество звёзд (1-10000):", reply_markup=back_kb())
    await cb.answer()


@router.message(BuyStars.custom)
async def buy_custom_stars(msg: Message, state: FSMContext):
    try:
        stars = int(msg.text.strip())
        if not (1 <= stars <= 10000):
            raise ValueError
    except Exception:
        await msg.answer("❌ Введи целое число от 1 до 10000.")
        return
    await state.clear()
    tokens = stars * STAR_RATE
    await add_balance(msg.from_user.id, tokens)
    await msg.answer(f"✅ Начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐",
                     reply_markup=main_kb())


@router.callback_query(F.data.startswith("buy_") & ~F.data.in_({"buy_custom"}))
async def buy_stars(cb: CallbackQuery):
    try:
        stars = int(cb.data.split("_")[1])
    except ValueError:
        await cb.answer("Ошибка", show_alert=True)
        return
    tokens = stars * STAR_RATE
    await add_balance(cb.from_user.id, tokens)
    await cb.message.edit_text(f"✅ Начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐")
    await cb.answer("Готово")

# bot.py — ЧАСТЬ 2 (Игры, Рулетка с автостартом, Мега-админка 30+, планировщик, main)

# ============================================================
# ИГРЫ: КУБИКИ (7 видов)
# ============================================================
DICE_EMOJI = {
    "кубик": "🎲", "кубики": "🎲", "кости": "🎲",
    "дартс": "🎯", "баскет": "🏀", "баскетбол": "🏀",
    "футбол": "⚽", "боулинг": "🎳", "бж": "🎰", "слоты": "🎰",
}


@router.message(F.text.regexp(r"^(кубик|кубики|кости|дартс|баскет|баскетбол|футбол|боулинг|бж|слоты)\s+\d+$"))
async def dice_game(msg: Message):
    if msg.chat.type != ChatType.PRIVATE and not await chat_games_enabled(msg.chat.id):
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
    if not await try_withdraw(msg.from_user.id, bet):
        await msg.reply("❌ Недостаточно средств.")
        return
    emoji = DICE_EMOJI.get(game, "🎲")
    sent = await msg.reply_dice(emoji=emoji)
    value = sent.dice.value
    win = bet * 2 if value > 3 else 0
    if win:
        await add_balance(msg.from_user.id, win)
    await log_game(msg.from_user.id, f"dice_{game}", bet, win, f"value={value}")
    u2 = await get_user(msg.from_user.id)
    await msg.reply(
        f"{'🎉 Победа!' if win else '😔 Проигрыш'}\n"
        f"Результат: <b>{value}</b>\n"
        f"Выигрыш: <b>{fmt(win)}</b>\n"
        f"Баланс: <b>{fmt(u2['balance'])}</b>"
    )

    async def auto_delete():
        await asyncio.sleep(DICE_AUTODELETE_SEC)
        try:
            await sent.delete()
        except Exception:
            pass
    asyncio.create_task(auto_delete())


# ============================================================
# ИГРЫ: МИНЫ (5x5, 3 мины)
# ============================================================
def build_mines_kb(session: dict) -> InlineKeyboardMarkup:
    opened = session["opened"]
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
    if msg.chat.type != ChatType.PRIVATE and not await chat_games_enabled(msg.chat.id):
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
        await msg.reply("❗ У тебя уже активна игра в мины.")
        return
    if not await try_withdraw(msg.from_user.id, bet):
        await msg.reply("❌ Недостаточно средств.")
        return
    mines = set(random.sample(range(25), 3))
    mines_sessions[msg.from_user.id] = {
        "chat_id": msg.chat.id, "bet": bet, "mines": mines,
        "opened": set(), "exploded": set(), "msg_id": None,
    }
    kb = build_mines_kb(mines_sessions[msg.from_user.id])
    sent = await msg.reply(
        f"💣 <b>Мины</b>\nСтавка: <b>{fmt(bet)}</b>\n\n"
        f"Открывай клетки, избегай 3 мин. Множитель: 1.0 + 0.15 за клетку.",
        reply_markup=kb,
    )
    mines_sessions[msg.from_user.id]["msg_id"] = sent.message_id


@router.callback_query(F.data.startswith("mine_open_"))
async def mines_open(cb: CallbackQuery):
    uid = cb.from_user.id
    s = mines_sessions.get(uid)
    if not s:
        await cb.answer("Игра не найдена", show_alert=True)
        return
    if cb.message.chat.id != s["chat_id"]:
        await cb.answer("Не твоя игра", show_alert=True)
        return
    idx = int(cb.data.split("_")[2])
    if idx in s["opened"]:
        await cb.answer()
        return
    if idx in s["mines"]:
        s["exploded"].add(idx)
        mines_sessions.pop(uid, None)
        kb = build_mines_kb(s)
        await cb.message.edit_text(
            f"💥 <b>БУМ!</b> Ставка <b>{fmt(s['bet'])}</b> потеряна.",
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
    await cb.answer(f"💎 x{mult:.2f} (забрать: {fmt(profit)})")


@router.callback_query(F.data == "mine_take")
async def mines_take(cb: CallbackQuery):
    uid = cb.from_user.id
    s = mines_sessions.get(uid)
    if not s:
        await cb.answer("Игра не найдена", show_alert=True)
        return
    if not s["opened"]:
        await cb.answer("Открой хотя бы одну клетку!", show_alert=True)
        return
    mines_sessions.pop(uid, None)
    mult = 1.0 + len(s["opened"]) * MINES_MULT_STEP
    win = int(s["bet"] * mult)
    await add_balance(uid, win)
    await log_game(uid, "mines", s["bet"], win, f"cells={len(s['opened'])}")
    for m in s["mines"]:
        s["exploded"].add(m)
    kb = build_mines_kb(s)
    try:
        await cb.message.edit_text(
            f"💰 <b>Выигрыш!</b>\n"
            f"Открыто: <b>{len(s['opened'])}</b> | x{mult:.2f}\n"
            f"Выигрыш: <b>{fmt(win)} TOKENS</b>",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        pass
    await cb.answer(f"💰 +{fmt(win)}")


@router.callback_query(F.data == "mine_noop")
async def mines_noop(cb: CallbackQuery):
    await cb.answer()


# ============================================================
# ИГРЫ: ДУЭЛИ
# ============================================================
@router.message(F.text.regexp(r"^дуэль\s+@\w+\s+\d+$"))
async def duel_start(msg: Message):
    global _duel_seq
    if msg.chat.type != ChatType.PRIVATE and not await chat_games_enabled(msg.chat.id):
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
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)",
                               (target_username,))
        row = await cur.fetchone()
    if not row:
        await msg.reply("❌ Игрок не найден. Пусть напишет /start в ЛС.")
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
        "challenger": msg.from_user.id, "target": target_id, "bet": bet,
        "chat_id": msg.chat.id,
        "challenger_name": msg.from_user.username or str(msg.from_user.id),
        "target_name": target_username, "resolved": False,
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"duel_accept_{did}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"duel_decline_{did}")],
    ])
    await msg.reply(
        f"⚔️ <b>Вызов на дуэль!</b>\n\n"
        f"@{msg.from_user.username or msg.from_user.id} → @{target_username}\n"
        f"Ставка: <b>{fmt(bet)} TOKENS</b> | комиссия 5%\n\n"
        f"@{target_username}, примешь вызов?",
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


# ============================================================
# РУЛЕТКА — ПАРСЕР, АВТОСТАРТ, ВЫПЛАТЫ
# ============================================================
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

ROULETTE_START_DELAY = 10  # секунд после первой ставки


def parse_roulette_bet(text: str) -> Optional[list]:
    """
    Возвращает СПИСОК ставок (может быть несколько диапазонов/чисел).
    Форматы:
      "к 1000"                             -> color red
      "ч 500"                              -> color black
      "0 100"                              -> zero
      "1000 чет" / "1000 нечет"            -> parity
      "1000 1 2 3"                         -> numbers
      "500 10-20"                          -> один range
      "2000 2-5 7-11 15-19 22-25 26-29"    -> МНОГО range (по 2000 на каждый)
      "1000 1-5 12 20-25"                  -> смесь ranges + numbers
    """
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)

    # Цвет
    m = re.match(r"^(к|красное|красн)\s+(\d+)$", t)
    if m:
        return [{"type": "color", "value": "red", "amount": int(m.group(2))}]
    m = re.match(r"^(ч|черное|черн)\s+(\d+)$", t)
    if m:
        return [{"type": "color", "value": "black", "amount": int(m.group(2))}]

    # Зеро
    m = re.match(r"^(0|зеро|zero)\s+(\d+)$", t)
    if m:
        return [{"type": "color", "value": "zero", "amount": int(m.group(2))}]

    # Чет/нечет (сумма ПЕРЕД)
    m = re.match(r"^(\d+)\s+(чет|чёт|even)$", t)
    if m:
        return [{"type": "parity", "value": "even", "amount": int(m.group(1))}]
    m = re.match(r"^(\d+)\s+(нечет|нечёт|odd)$", t)
    if m:
        return [{"type": "parity", "value": "odd", "amount": int(m.group(1))}]

    # Пакетная ставка: сумма + несколько токенов (ranges и/или числа)
    # "2000 2-5 7-11 15-19 22-25 26-29"  или  "1000 1 2 3"
    m = re.match(r"^(\d+)\s+(.+)$", t)
    if m:
        amount = int(m.group(1))
        rest = m.group(2).strip()
        tokens = re.split(r"[,\s]+", rest)
        bets = []
        nums_plain = []
        for tok in tokens:
            if not tok:
                continue
            rng = re.match(r"^(\d+)-(\d+)$", tok)
            if rng:
                a, b = int(rng.group(1)), int(rng.group(2))
                if a > b:
                    a, b = b, a
                if 0 <= a <= 36 and 0 <= b <= 36:
                    bets.append({"type": "range", "value": (a, b), "amount": amount})
                else:
                    return None
            else:
                try:
                    n = int(tok)
                except ValueError:
                    return None
                if not (0 <= n <= 36):
                    return None
                nums_plain.append(n)
        # Каждое отдельное число — ставка на число (x36)
        for n in nums_plain:
            bets.append({"type": "numbers", "value": [n], "amount": amount})
        return bets if bets else None

    return None


def format_bet_label(b: dict) -> str:
    t, v = b["type"], b["value"]
    if t == "color":
        return {"red": "🔴 красное", "black": "⚫ чёрное", "zero": "0️⃣ зеро"}[v]
    if t == "parity":
        return "🎯 чёт" if v == "even" else "🎯 нечет"
    if t == "numbers":
        return "🔢 " + ",".join(map(str, v))
    if t == "range":
        return f"📏 {v[0]}-{v[1]}"
    return "❔"


def calc_roulette_win(b: dict, number: int, color: str) -> int:
    t, v, amt = b["type"], b["value"], b["amount"]
    if t == "color":
        if v == color:
            return amt * 36 if color == "zero" else amt * 2
    elif t == "parity":
        if number != 0:
            is_even = number % 2 == 0
            if (v == "even" and is_even) or (v == "odd" and not is_even):
                return amt * 2
    elif t == "numbers":
        if number in v:
            return amt * 36
    elif t == "range":
        a, bnd = v
        if a <= number <= bnd:
            return amt * 3
    return 0


async def ensure_roulette_session(chat_id: int, starter_id: int) -> dict:
    """Создаёт или возвращает сессию. Запускает таймер на ROULETTE_START_DELAY."""
    s = roulette_sessions.get(chat_id)
    if s and not s["resolved"]:
        return s
    s = {
        "bets": {},
        "started_by": starter_id,
        "started_at": time.time(),
        "resolved": False,
        "timer_started": False,
    }
    roulette_sessions[chat_id] = s
    return s


async def roulette_spin(chat_id: int):
    await asyncio.sleep(ROULETTE_START_DELAY)
    s = roulette_sessions.get(chat_id)
    if not s or s["resolved"]:
        return
    s["resolved"] = True

    if not s["bets"]:
        roulette_sessions.pop(chat_id, None)
        return

    # Список всех ставок
    lines = ["📋 <b>Ставки приняты:</b>"]
    for uid, bets in s["bets"].items():
        for b in bets:
            lines.append(
                f"• <code>{uid}</code>: {format_bet_label(b)} — <b>{fmt(b['amount'])}</b>"
            )
    await bot.send_message(chat_id, "\n".join(lines))

    # Гифка или кубик
    if os.path.exists(IMG_ROULETTE_GIF):
        try:
            await bot.send_animation(chat_id, FSInputFile(IMG_ROULETTE_GIF))
        except Exception as e:
            log.warning("roulette gif: %s", e)
            await bot.send_dice(chat_id, emoji="🎰")
    else:
        await bot.send_dice(chat_id, emoji="🎰")

    await asyncio.sleep(3)

    number = random.randint(0, 36)
    if number == 0:
        color = "zero"
    elif number in RED_NUMBERS:
        color = "red"
    else:
        color = "black"

    payout_total = 0
    winners_lines = []
    for uid, bets in s["bets"].items():
        user_total = 0
        for b in bets:
            win = calc_roulette_win(b, number, color)
            user_total += win
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO roulette_logs(chat_id, user_id, bet, win, numbers, color, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (chat_id, uid, b["amount"], win, str(number), color,
                     datetime.utcnow().isoformat()),
                )
                await db.commit()
        if user_total > 0:
            await add_balance(uid, user_total)
            payout_total += user_total
            winners_lines.append(f"🆔 <code>{uid}</code> +{fmt(user_total)}")

    color_emoji = {"red": "🔴", "black": "⚫", "zero": "🟢"}[color]
    color_text = {"red": "красное", "black": "чёрное", "zero": "зеро"}[color]
    text = (
        f"🎡 <b>Результат рулетки!</b>\n\n"
        f"Выпало: {color_emoji} <b>{number}</b> ({color_text})\n\n"
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
    await bot.send_message(chat_id, text, reply_markup=kb)

    s["result"] = {"number": number, "color": color}

    async def cleanup():
        await asyncio.sleep(120)
        roulette_sessions.pop(chat_id, None)
    asyncio.create_task(cleanup())


@router.message(F.text.lower() == "старт")
async def roulette_start_cmd(msg: Message):
    if msg.chat.type == ChatType.PRIVATE:
        await msg.reply("🎡 Рулетка запускается только в игровом чате: " + CHAT_GAME)
        return
    if not await chat_games_enabled(msg.chat.id):
        return
    s = roulette_sessions.get(msg.chat.id)
    if s and not s["resolved"]:
        await msg.reply("❗ Рулетка уже идёт.")
        return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    s = await ensure_roulette_session(msg.chat.id, msg.from_user.id)
    await msg.reply(
        f"🎰 <b>Рулетка запущена!</b>\n"
        f"Принимаю ставки <b>{ROULETTE_START_DELAY} секунд</b>.\n\n"
        f"📌 Форматы:\n"
        f"🔴 <code>к 1000</code> | ⚫ <code>ч 500</code>\n"
        f"🎯 <code>1000 чет</code> | <code>1000 нечет</code>\n"
        f"0️⃣ <code>0 100</code>\n"
        f"🔢 <code>1000 1 2 3</code>\n"
        f"📏 <code>500 10-20</code>\n"
        f"📦 <code>2000 2-5 7-11 15-19</code> — пакет диапазонов"
    )
    if not s["timer_started"]:
        s["timer_started"] = True
        asyncio.create_task(roulette_spin(msg.chat.id))


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def roulette_bet_handler(msg: Message):
    """Любое сообщение в чате, похожее на ставку, принимается.
    Если сессии нет — создаётся АВТОМАТИЧЕСКИ и запускается таймер."""
    if not msg.text or msg.from_user.is_bot:
        return
    if not await chat_games_enabled(msg.chat.id):
        return

    parsed = parse_roulette_bet(msg.text)
    if not parsed:
        return

    total_bet = sum(b["amount"] for b in parsed)
    if total_bet < 10:
        await msg.reply("❌ Минимальная ставка — 10 TOKENS")
        return

    await ensure_user(msg.from_user.id, msg.from_user.username)
    if not await try_withdraw(msg.from_user.id, total_bet):
        await msg.reply("❌ Недостаточно средств.")
        return

    s = await ensure_roulette_session(msg.chat.id, msg.from_user.id)
    uid = msg.from_user.id
    s["bets"].setdefault(uid, []).extend(parsed)

    async with aiosqlite.connect(DB_PATH) as db:
        for b in parsed:
            await db.execute(
                "INSERT INTO roulette_participants(chat_id, user_id, bet_type, bet_value, amount, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (msg.chat.id, uid, b["type"], str(b["value"]), b["amount"],
                 datetime.utcnow().isoformat()),
            )
        await db.commit()

    labels = " + ".join(format_bet_label(b) for b in parsed)
    await msg.reply(
        f"✅ Ставка принята: {labels}\n"
        f"💰 Всего: <b>{fmt(total_bet)}</b> TOKENS"
    )

    # Автостарт таймера, если это первая ставка
    if not s["timer_started"]:
        s["timer_started"] = True
        await msg.answer(
            f"🎰 <b>Рулетка запущена автоматически!</b>\n"
            f"Принимаю ещё ставки <b>{ROULETTE_START_DELAY} секунд</b>."
        )
        asyncio.create_task(roulette_spin(msg.chat.id))


@router.callback_query(F.data == "roul_repeat")
async def roulette_repeat(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    s = roulette_sessions.get(chat_id)
    if not s or "result" not in s:
        await cb.answer("Сессия истекла", show_alert=True)
        return
    old_bets = s.get("bets", {})
    roulette_sessions[chat_id] = {
        "bets": {}, "started_by": cb.from_user.id,
        "started_at": time.time(), "resolved": False, "timer_started": True,
    }
    for uid, bets in old_bets.items():
        for b in bets:
            if await try_withdraw(uid, b["amount"]):
                roulette_sessions[chat_id]["bets"].setdefault(uid, []).append(b)
    await cb.answer("🔄 Повтор!")
    await bot.send_message(chat_id,
        f"🎰 Повтор прошлых ставок! Принимаю {ROULETTE_START_DELAY} секунд...")
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
        "bets": {}, "started_by": cb.from_user.id,
        "started_at": time.time(), "resolved": False, "timer_started": True,
    }
    for uid, bets in old_bets.items():
        for b in bets:
            nb = dict(b)
            nb["amount"] = b["amount"] * 2
            if await try_withdraw(uid, nb["amount"]):
                roulette_sessions[chat_id]["bets"].setdefault(uid, []).append(nb)
    await cb.answer("⏫ Удвоено!")
    await bot.send_message(chat_id,
        f"🎰 Ставки удвоены! Принимаю {ROULETTE_START_DELAY} секунд...")
    asyncio.create_task(roulette_spin(chat_id))


# ============================================================
# МЕГА-АДМИНКА ЧЕРЕЗ @ (30+ команд)
# ============================================================
def is_admin(msg: Message) -> bool:
    return ADMIN_ID and msg.from_user and msg.from_user.id == ADMIN_ID


async def find_user_by_username(username: str) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)",
                               (username,))
        row = await cur.fetchone()
        return row[0] if row else None


async def admin_log(admin_id: int, action: str, details: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO admin_logs(admin_id, action, details, created_at) VALUES(?,?,?,?)",
            (admin_id, action, details, datetime.utcnow().isoformat()),
        )
        await db.commit()


ADMIN_HELP_TEXT = (
    "🤖 <b>МЕГА-АДМИНКА TOKENS</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "<b>👤 УПРАВЛЕНИЕ ИГРОКАМИ</b>\n"
    "<code>@выдать @user 1000</code> — выдать TOKENS\n"
    "<code>@забрать @user 1000</code> — забрать TOKENS\n"
    "<code>@бан @user</code> — забанить\n"
    "<code>@разбан @user</code> — разбанить\n"
    "<code>@банкрот @user</code> — обнулить баланс\n"
    "<code>@юзер @user</code> — подробная инфа об игроке\n\n"

    "<b>🎁 БОНУСЫ И ДРОПЫ</b>\n"
    "<code>@дроп 1000</code> — дроп в текущий чат с кнопкой\n"
    "<code>@дроп_всем 1000</code> — дроп всем игрокам в ЛС\n"
    "<code>@забрать_всем 1000</code> — забрать 1000 у всех\n\n"

    "<b>📊 СТАТИСТИКА</b>\n"
    "<code>@стата</code> — общая статистика бота\n"
    "<code>@лог 20</code> — последние 20 действий админа\n\n"

    "<b>📣 РАССЫЛКИ И ПРОМО</b>\n"
    "<code>@рассылка текст</code> — рассылка всем игрокам\n"
    "<code>@промо КОД 5000 10</code> — создать промокод (5000, 10 активаций)\n"
    "<code>@апдейт текст</code> — сообщение «Что нового» всем\n\n"

    "<b>💾 БЕКАП</b>\n"
    "<code>@бекап</code> — экспорт всех данных в .json (в ЛС)\n\n"

    "<b>💱 КУРСЫ</b>\n"
    "<code>@курс_добавить Имя 7500</code> — кастомный курс\n"
    "<code>@сброс_курса</code> — сброс кастомных курсов\n\n"

    "<b>💬 УПРАВЛЕНИЕ ЧАТАМИ</b>\n"
    "<code>@игры_выкл</code> — выключить игры в текущем чате\n"
    "<code>@игры_вкл</code> — включить игры\n"
    "<code>@ивент_чат_добавить</code> — добавить чат в авто-дроп\n"
    "<code>@ивент_чат_удалить</code> — убрать из авто-дроп\n"
    "<code>@очистить_чат 50</code> — удалить последние 50 сообщений бота\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Все команды работают только для <b>ADMIN_ID</b>."
)


@router.message(F.text.regexp(r"^@"))
async def admin_at_commands(msg: Message):
    if not is_admin(msg):
        return
    low = msg.text.strip().lower()

    # @помощь
    if low.startswith("@помощь"):
        await msg.reply(ADMIN_HELP_TEXT)
        return

    # @выдать @user 1000
    m = re.match(r"^@выдать\s+@(\w+)\s+(\d+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Игрок не найден.")
            return
        amount = int(m.group(2))
        await add_balance(uid, amount)
        await admin_log(msg.from_user.id, "выдать", f"@{m.group(1)} +{amount}")
        await msg.reply(f"✅ Выдано <b>{fmt(amount)}</b> @{m.group(1)}")
        return

    # @забрать @user 1000
    m = re.match(r"^@забрать\s+@(\w+)\s+(\d+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Игрок не найден.")
            return
        amount = int(m.group(2))
        ok = await try_withdraw(uid, amount)
        if not ok:
            await msg.reply("❌ У игрока недостаточно средств.")
            return
        await admin_log(msg.from_user.id, "забрать", f"@{m.group(1)} -{amount}")
        await msg.reply(f"✅ Забрано <b>{fmt(amount)}</b> у @{m.group(1)}")
        return

    # @бан / @разбан
    m = re.match(r"^@бан\s+@(\w+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
            await db.commit()
        await admin_log(msg.from_user.id, "бан", f"@{m.group(1)}")
        await msg.reply(f"⛔ @{m.group(1)} забанен.")
        return

    m = re.match(r"^@разбан\s+@(\w+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
            await db.commit()
        await admin_log(msg.from_user.id, "разбан", f"@{m.group(1)}")
        await msg.reply(f"✅ @{m.group(1)} разбанен.")
        return

    # @банкрот
    m = re.match(r"^@банкрот\s+@(\w+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
            await db.commit()
        await admin_log(msg.from_user.id, "банкрот", f"@{m.group(1)}")
        await msg.reply(f"💀 @{m.group(1)} обнулён.")
        return

    # @юзер @user
    m = re.match(r"^@юзер\s+@(\w+)$", low)
    if m:
        uid = await find_user_by_username(m.group(1))
        if not uid:
            await msg.reply("❌ Не найден.")
            return
        u = await get_user(uid)
        await msg.reply(
            f"👤 <b>Инфо об игроке</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"📛 Username: @{u['username'] or '—'}\n"
            f"💎 Баланс: <b>{fmt(u['balance'])}</b>\n"
            f"🎖 VIP: {'да' if u['vip'] else 'нет'}\n"
            f"🎮 Игр: {u['games']} | 🏆 Побед: {u['wins']}\n"
            f"🚫 Бан: {'да' if u['banned'] else 'нет'}\n"
            f"📅 Регистрация: {u['created_at'][:10]}"
        )
        return

    # @дроп 1000
    m = re.match(r"^@дроп\s+(\d+)$", low)
    if m:
        amount = int(m.group(1))
        await send_bonus_drop(msg.chat.id, amount)
        await admin_log(msg.from_user.id, "дроп", f"{amount}")
        return

    # @дроп_всем 1000
    m = re.match(r"^@дроп_всем\s+(\d+)$", low)
    if m:
        amount = int(m.group(1))
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM users")
            uids = [r[0] for r in await cur.fetchall()]
        ok = 0
        for uid in uids:
            await add_balance(uid, amount)
            ok += 1
            await asyncio.sleep(0.01)
        await admin_log(msg.from_user.id, "дроп_всем", f"{amount} x {ok}")
        await msg.reply(f"✅ Дроп <b>{fmt(amount)}</b> выдан {ok} игрокам.")
        return

    # @забрать_всем 1000
    m = re.match(r"^@забрать_всем\s+(\d+)$", low)
    if m:
        amount = int(m.group(1))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET balance = MAX(0, balance - ?)", (amount,))
            await db.commit()
        await admin_log(msg.from_user.id, "забрать_всем", f"{amount}")
        await msg.reply(f"✅ Забрано <b>{fmt(amount)}</b> у всех.")
        return

    # @стата
    if low.startswith("@стата"):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT COUNT(*), SUM(balance), SUM(games) FROM users")
            users_count, total_bal, total_games = await cur.fetchone()
            cur = await db.execute("SELECT COUNT(*) FROM event_chats")
            ev = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(*) FROM roulette_logs")
            rl = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(*) FROM promo_codes")
            pc = (await cur.fetchone())[0]
        await msg.reply(
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Игроков: <b>{users_count}</b>\n"
            f"💎 Всего балансов: <b>{fmt(total_bal or 0)}</b>\n"
            f"🎮 Всего игр: <b>{fmt(total_games or 0)}</b>\n"
            f"📣 Event-чатов: <b>{ev}</b>\n"
            f"🎡 Ставок в рулетке: <b>{rl}</b>\n"
            f"🎟 Промокодов: <b>{pc}</b>"
        )
        return

    # @лог 20
    m = re.match(r"^@лог\s+(\d+)$", low)
    if m:
        limit = int(m.group(1))
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = await cur.fetchall()
        if not rows:
            await msg.reply("📜 Логов нет.")
            return
        lines = [f"📜 <b>Последние {limit} действий:</b>\n"]
        for r in rows:
            lines.append(f"• {r['action']}: {r['details']} ({r['created_at'][:16]})")
        await msg.reply("\n".join(lines))
        return

    # @рассылка текст
    m = re.match(r"^@рассылка\s+(.+)$", msg.text.strip(), re.IGNORECASE | re.DOTALL)
    if m:
        text = m.group(1)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE notifications=1")
            uids = [r[0] for r in await cur.fetchall()]
        ok = 0
        for uid in uids:
            try:
                await bot.send_message(uid, f"📣 <b>Рассылка</b>\n\n{text}")
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await msg.reply(f"✅ Отправлено: <b>{ok}</b> / {len(uids)}")
        return

    # @промо КОД 5000 10
    m = re.match(r"^@промо\s+(\S+)\s+(\d+)\s+(\d+)$", msg.text.strip(), re.IGNORECASE)
    if m:
        code = m.group(1).upper()
        amount = int(m.group(2))
        max_uses = int(m.group(3))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO promo_codes(code, amount, max_uses, used_count) VALUES(?,?,?,0)",
                (code, amount, max_uses),
            )
            await db.commit()
        await msg.reply(
            f"🎟 Промокод <b>{code}</b> создан\n"
            f"💰 Сумма: <b>{fmt(amount)}</b>\n"
            f"🔢 Активаций: <b>{max_uses}</b>"
        )
        return

    # @апдейт текст
    m = re.match(r"^@апдейт\s+(.+)$", msg.text.strip(), re.IGNORECASE | re.DOTALL)
    if m:
        text = m.group(1)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE notifications=1")
            uids = [r[0] for r in await cur.fetchall()]
        ok = 0
        for uid in uids:
            try:
                await bot.send_message(uid, f"🆕 <b>Обновление!</b>\n\n{text}")
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await msg.reply(f"✅ Апдейт отправлен: <b>{ok}</b>")
        return

    # @бекап
    if low.startswith("@бекап"):
        import json
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            data = {}
            for table in ["users", "chat_settings", "event_chats", "roulette_logs",
                          "games_log", "bonus_items", "promo_codes"]:
                cur = await db.execute(f"SELECT * FROM {table}")
                data[table] = [dict(r) for r in await cur.fetchall()]
        path = f"backup_{int(time.time())}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        await msg.reply_document(FSInputFile(path, filename="backup.json"))
        try:
            os.remove(path)
        except Exception:
            pass
        return

    # @курс_добавить Имя 7500
    m = re.match(r"^@курс_добавить\s+(\S+)\s+(\d+)$", msg.text.strip(), re.IGNORECASE)
    if m:
        name, rate = m.group(1), int(m.group(2))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO custom_rates(name, rate) VALUES(?,?)", (name, rate)
            )
            await db.commit()
        await msg.reply(f"✅ Курс «{name}» = {fmt(rate)} TOKENS")
        return

    # @сброс_курса
    if low.startswith("@сброс_курса"):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM custom_rates")
            await db.commit()
        await msg.reply("✅ Кастомные курсы сброшены.")
        return

    # @игры_выкл / вкл
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

    # @ивент_чат_добавить / удалить
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

    # @очистить_чат 50
    m = re.match(r"^@очистить_чат\s+(\d+)$", low)
    if m:
        n = int(m.group(1))
        deleted = 0
        for i in range(n):
            try:
                await bot.delete_message(msg.chat.id, msg.message_id - i - 1)
                deleted += 1
            except Exception:
                pass
        await msg.reply(f"🧹 Удалено сообщений: {deleted}")
        return

    # Неизвестная @-команда
    await msg.reply(
        "🤔 Неизвестная команда.\n"
        "Напиши <code>@помощь</code> чтобы увидеть список."
    )


# ============================================================
# БОНУСЫ И АВТО-ДРОП
# ============================================================
async def send_bonus_drop(chat_id: int, amount: int):
    caption = (
        f"🎁 <b>БОНУС!</b>\n\n"
        f"Кто первый — того и <b>{fmt(amount)} TOKENS</b>!\n"
        f"⬇️ Жми «Забрать»"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать", callback_data=f"claim_bonus_{amount}")]
    ])
    try:
        if os.path.exists(IMG_BONUS):
            sent = await bot.send_photo(chat_id, FSInputFile(IMG_BONUS), caption=caption, reply_markup=kb)
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
            "SELECT * FROM bonus_items WHERE chat_id=? AND message_id=?", (chat_id, msg_id)
        )
        row = await cur.fetchone()
        if not row:
            await cb.answer("Бонус не найден", show_alert=True)
            return
        if row["claimed_by"]:
            await cb.answer("Бонус уже забран!", show_alert=True)
            return
        await db.execute("UPDATE bonus_items SET claimed_by=? WHERE id=?",
                         (cb.from_user.id, row["id"]))
        await db.commit()
    await ensure_user(cb.from_user.id, cb.from_user.username)
    await add_balance(cb.from_user.id, amount)
    await cb.answer(f"🎉 +{fmt(amount)} TOKENS!", show_alert=True)
    try:
        await cb.message.edit_caption(
            caption=f"🎁 Забрал @{cb.from_user.username or cb.from_user.id} — <b>{fmt(amount)}</b> TOKENS"
        )
    except Exception:
        try:
            await cb.message.edit_text(
                f"🎁 Забрал @{cb.from_user.username or cb.from_user.id} — <b>{fmt(amount)}</b> TOKENS"
            )
        except Exception:
            pass


async def broadcast_event_drop():
    chats = await get_event_chats()
    if not chats:
        return
    amount = random.choice([500, 1000, 1500, 2000, 3000])
    for cid in chats:
        try:
            await send_bonus_drop(cid, amount)
            await asyncio.sleep(1)
        except Exception as e:
            log.warning("event drop to %s failed: %s", cid, e)


async def scheduled_drop():
    log.info("Scheduled event drop running")
    await broadcast_event_drop()


async def cleanup_old_records():
    limit_games = (datetime.utcnow() - timedelta(days=30)).isoformat()
    limit_bonus = (datetime.utcnow() - timedelta(days=7)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM games_log WHERE created_at < ?", (limit_games,))
        await db.execute("DELETE FROM bonus_items WHERE created_at < ?", (limit_bonus,))
        await db.commit()
    log.info("Old records cleaned")


# ============================================================
# ВЕБ-СЕРВЕР И MAIN
# ============================================================
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


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    await db_init()
    scheduler.add_job(scheduled_drop, "interval", hours=2, id="event_drop")
    scheduler.add_job(cleanup_old_records, "interval", hours=24, id="cleanup")
    scheduler.start()
    await start_web()
    log.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")