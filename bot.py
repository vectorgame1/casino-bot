import os
import re
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
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
# КОНФИГУРАЦИЯ
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = "tokens_bot.db"

STAR_RATE = 7500
DICE_AUTODELETE_SEC = 60
DUEL_COMMISSION = 0.05
MINES_MULT_STEP = 0.15

CHAT_GAME = "https://t.me/tokenplays"
CHAT_EXCHANGE = "https://t.me/Tokenschange"
CHAT_NEWS = "https://t.me/TokenCasinoTournaments"

IMG_DIR = "images"
IMG_START = os.path.join(IMG_DIR, "start.jpg")
IMG_PROFILE = os.path.join(IMG_DIR, "profile.jpg")
IMG_DONATE = os.path.join(IMG_DIR, "donate.jpg")
IMG_BONUS = os.path.join(IMG_DIR, "bonus.jpg")
IMG_TOP = os.path.join(IMG_DIR, "top.jpg")
IMG_HOW = os.path.join(IMG_DIR, "how_to_play.jpg")
IMG_SUPPORT = os.path.join(IMG_DIR, "support.jpg")
IMG_CHATS = os.path.join(IMG_DIR, "chats.jpg")
IMG_COMMANDS = os.path.join(IMG_DIR, "commands.jpg")
IMG_ROULETTE_GIF = os.path.join(IMG_DIR, "roulette.gif")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tokens")

if os.path.exists(DB_PATH):
    try: os.remove(DB_PATH)
    except Exception: pass

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
# БАЗА ДАННЫХ
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
        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id INTEGER PRIMARY KEY, last_claim TEXT
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY, amount INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS promo_used (
            user_id INTEGER, code TEXT, used_at TEXT, PRIMARY KEY (user_id, code)
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
        await db.execute("INSERT INTO users(user_id, username, balance, created_at) VALUES(?,?,?,?)",
                         (user_id, username or "", 0, datetime.utcnow().isoformat()))
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
        if not row or row[0] < amount: return False
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        await db.commit()
        return True

async def log_game(user_id: int, game: str, bet: int, win: int, result: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO games_log(user_id, game, bet, win, result, created_at) VALUES(?,?,?,?,?,?)",
                         (user_id, game, bet, win, result, datetime.utcnow().isoformat()))
        await db.execute("UPDATE users SET games = games + 1, wins = wins + ? WHERE user_id=?",
                         (1 if win > 0 else 0, user_id))
        await db.commit()

async def get_history(user_id: int, limit: int = 10) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM games_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return [dict(r) for r in await cur.fetchall()]

async def chat_games_enabled(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT games_enabled FROM chat_settings WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return True if row is None else bool(row[0])

async def set_chat_games(chat_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO chat_settings(chat_id, games_enabled) VALUES(?,?) "
                         "ON CONFLICT(chat_id) DO UPDATE SET games_enabled=excluded.games_enabled",
                         (chat_id, 1 if enabled else 0))
        await db.commit()

# ---------------------------------------------------------------------------
# ХЕЛПЕРЫ И КЛАВИАТУРЫ
# ---------------------------------------------------------------------------
def main_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Как играть", callback_data="menu_how"), 
         InlineKeyboardButton(text="🎁 Бонус", callback_data="menu_bonus")],
        [InlineKeyboardButton(text="💎 Донат", callback_data="menu_donate"), 
         InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="💬 Чаты", callback_data="menu_chats"), 
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="📖 Команды", callback_data="menu_commands"), 
         InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top")],
    ])

def back_kb(target="menu_start") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]
    ])

def fmt(v: int) -> str:
    return f"{v:,}".replace(",", " ")

async def auto_delete(msg: Message, delay: int = 30):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

async def safe_send(chat_id: int, text: str, reply_markup=None):
    if not text: return
    if len(text) <= 4000:
        try: return await bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as e: log.warning(f"safe_send: {e}")
    else:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, chunk in enumerate(chunks):
            markup = reply_markup if i == len(chunks) - 1 else None
            try: await bot.send_message(chat_id, chunk, reply_markup=markup)
            except Exception as e: log.warning(f"safe_send chunk: {e}")

# ---------------------------------------------------------------------------
# ГИГАНТСКИЕ ТЕКСТЫ (Гайды для игроков и Админа)
# ---------------------------------------------------------------------------
HOW_TO_PLAY_DICE = (
    "🎲 <b>КУБИКИ И СПОРТ</b>\n\n"
    "Это игры на удачу с мгновенным результатом. Твоя задача — выбросить больше 3.\n\n"
    "<b>Доступные команды:</b>\n"
    "• <code>кости 1000</code> — бросок классического кубика\n"
    "• <code>дартс 500</code> — бросок дротика в мишень\n"
    "• <code>баскет 1000</code> — бросок мяча в кольцо\n"
    "• <code>футбол 2000</code> — удар по воротам\n"
    "• <code>боулинг 1000</code> — бросок шара\n"
    "• <code>бж 1000</code> — блэкджек (слот)\n"
    "• <code>слоты 1000</code> — игровые автоматы\n\n"
    "🏆 <b>Правила выигрыша:</b>\n"
    "Если выпадает <b>4, 5 или 6</b> — ты получаешь <b>x2</b> к ставке.\n"
    "Если выпадает <b>1, 2 или 3</b> — ставка сгорает.\n\n"
    "💡 <i>Минимальная ставка: 10 TOKENS.</i>"
)

HOW_TO_PLAY_MINES = (
    "💣 <b>ИГРА В МИНЫ</b>\n\n"
    "Это игра на внимательность и риск.\n\n"
    "<b>Как начать:</b>\n"
    "Напиши <code>мины 1000</code> (где 1000 — твоя ставка).\n\n"
    "🎰 <b>Правила:</b>\n"
    "• Появляется поле 5×5 (всего 25 клеток).\n"
    "• Внутри спрятано ровно <b>3 мины</b>.\n"
    "• Ты открываешь клетки, нажимая на кнопки ⬜.\n"
    "• За каждую открытую безопасную клетку твой множитель растет на <b>+0.15</b>.\n"
    "• Если ты попадаешь на мину 💥 — игра заканчивается, ставка сгорает.\n\n"
    "💰 <b>Как забрать выигрыш:</b>\n"
    "В любой момент нажми кнопку <b>«💰 Забрать»</b>. Бот начислит твой баланс, умноженный на текущий множитель.\n"
    "Пример: открыл 4 клетки (x1.6). Забрал = получил 1600 со ставки 1000."
)

HOW_TO_PLAY_DUEL = (
    "⚔️ <b>ДУЭЛИ С ИГРОКАМИ</b>\n\n"
    "Сразись один на один с другим участником чата!\n\n"
    "<b>Как начать:</b>\n"
    "Напиши <code>дуэль @username 1000</code> (где @username — ник соперника, 1000 — ставка).\n\n"
    "🎲 <b>Правила:</b>\n"
    "• Бот отправляет вызов. Соперник должен нажать «✅ Принять».\n"
    "• У обоих списывается ставка и формируется общий банк.\n"
    "• Бот бросает кубики за тебя и за соперника.\n"
    "• У кого число больше — тот забирает весь банк.\n\n"
    "💸 <b>Комиссия:</b> Бот забирает 5% от общего банка за организацию дуэли.\n"
    "Если соперник отклонил вызов или у него нет денег — твоя ставка возвращается."
)

HOW_TO_PLAY_ROULETTE = (
    "🎡 <b>РУЛЕТКА</b>\n\n"
    "Главная игра нашего бота! Здесь можно сорвать крупный куш.\n\n"
    "<b>1. Как поставить?</b>\n"
    "Просто напиши в чат ставку. Форматы:\n"
    "• <code>к 1000</code> — на красное (x2)\n"
    "• <code>ч 500</code> — на чёрное (x2)\n"
    "• <code>1000 чет</code> — на чётное (x2)\n"
    "• <code>1000 нечет</code> — на нечётное (x2)\n"
    "• <code>0 100</code> — на Зеро (x36)\n"
    "• <code>1000 1 2 3</code> — на конкретные числа (x36)\n"
    "• <code>500 10-20</code> — на диапазон (x3)\n"
    "• <code>2000 2-5 7-11</code> — пакетная ставка на несколько диапазонов\n\n"
    "<b>2. Как запустить?</b>\n"
    "Когда сделаешь ставку (и другие игроки тоже), напиши в чат команду <code>старт</code>.\n"
    "❗ <i>Запустить рулетку может только тот, у кого есть активная ставка!</i>\n\n"
    "<b>3. Результат:</b>\n"
    "Бот покажет гифку, выпавшее число и выплатит выигрыши победителям."
)

COMMANDS_TEXT = (
    "📖 <b>СПИСОК КОМАНД БОТА</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🟢 <b>ДЛЯ ИГРОКОВ (В ЛЮБОМ ЧАТЕ И ЛС):</b>\n"
    "• <code>б</code> — Быстро узнать свой баланс\n"
    "• <code>топ</code> — Топ-10 самых богатых игроков\n"
    "• <code>перевод @user 1000</code> — Перевести токены другу\n"
    "• <code>промо КОД</code> — Активировать бонус-код\n"
    "• <code>лог</code> — Твоя история последних 10 игр\n"
    "• <code>что нового</code> — Список обновлений бота\n\n"
    "🎮 <b>ИГРОВЫЕ КОМАНДЫ:</b>\n"
    "• <code>кости 1000</code> — Игра в кубик (и другие: дартс, баскет, футбол, боулинг, бж, слоты)\n"
    "• <code>мины 1000</code> — Игра в Мины\n"
    "• <code>дуэль @user 1000</code> — Вызвать игрока на дуэль\n"
    "• <code>старт</code> — Запустить рулетку (если есть ставки)\n"
    "• <code>к 1000</code>, <code>ч 500</code> — Ставки в рулетке\n\n"
    "💎 <b>ДОНАТ И ПОДДЕРЖКА:</b>\n"
    "• Меню покупки токенов за Telegram Stars\n"
    "• Связь с админом: @ТВОЙ_ЮЗЕРНЕЙМ\n\n"
    "🛡 <i>Команды администратора скрыты от обычных игроков.</i>"
)

ADMIN_HELP = (
    "👑 <b>МЕГА-АДМИНКА БОТА</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "⚠️ <i>Все команды работают только для твоего ID и начинаются с @.</i>\n\n"
    "👤 <b>УПРАВЛЕНИЕ ИГРОКАМИ:</b>\n"
    "• <code>@выдать @user 1000</code> — начислить баланс\n"
    "• <code>@забрать @user 1000</code> — списать баланс\n"
    "• <code>@бан @user</code> — заблокировать игрока\n"
    "• <code>@разбан @user</code> — разблокировать\n"
    "• <code>@банкрот @user</code> — обнулить баланс\n"
    "• <code>@юзер @user</code> — подробная инфа (ID, игры, победы)\n\n"
    "🎁 <b>БОНУСЫ И РАЗДАЧИ:</b>\n"
    "• <code>@дроп 1000</code> — кинуть дроп в текущий чат\n"
    "• <code>@дроп_всем 1000</code> — начислить всем игрокам\n"
    "• <code>@забрать_всем 1000</code> — списать у всех\n"
    "• <code>@промо КОД 5000 10</code> — создать промокод (сумма, кол-во активаций)\n\n"
    "📣 <b>РАССЫЛКИ:</b>\n"
    "• <code>@рассылка Текст</code> — отправить сообщение всем в ЛС\n"
    "• <code>@апдейт Текст</code> — сообщение «Что нового»\n\n"
    "🛠 <b>УПРАВЛЕНИЕ ЧАТАМИ:</b>\n"
    "• <code>@игры_выкл</code> — отключить игры в текущем чате\n"
    "• <code>@игры_вкл</code> — включить игры\n"
    "• <code>@ивент_чат_добавить</code> — добавить чат в авто-дроп\n"
    "• <code>@очистить_чат 50</code> — удалить последние N сообщений\n\n"
    "🤫 <b>СКРЫТЫЕ ПРИКОЛЮХИ:</b>\n"
    "• <code>@режим_бога</code> — выдает тебе +1 000 000 TOKENS\n"
    "• <code>@стата</code> — глобальная статистика бота\n"
    "• <code>@бекап</code> — выгрузка всей БД в .json"
)

# ---------------------------------------------------------------------------
# СТАРТ И ГЛАВНОЕ МЕНЮ
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(msg: Message):
    if msg.chat.type != ChatType.PRIVATE: return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    u = await get_user(msg.from_user.id)
    
    welcome = ""
    if u['balance'] == 0 and u['games'] == 0:
        await add_balance(msg.from_user.id, 5000)
        welcome = "\n🎁 <b>Стартовый бонус: +5000 TOKENS!</b>"

    caption = (
        "👋 <b>Добро пожаловать в TOKENS Game!</b>\n\n"
        "🎮 Наш бот полностью обновлён. Мы убрали скучные текстовые меню и сделали всё в удобных кнопках.\n\n"
        f"💎 Твой баланс: <b>{fmt(u['balance'] + (5000 if welcome else 0))}</b>\n"
        f"⭐ Курс: <b>{fmt(STAR_RATE)}</b> = 1⭐\n{welcome}\n\n"
        "👇 <i>Выбирай нужный раздел ниже:</i>"
    )
    
    if os.path.exists(IMG_START):
        await msg.answer_photo(FSInputFile(IMG_START), caption=caption, reply_markup=main_inline_kb())
    else:
        await msg.answer(caption, reply_markup=main_inline_kb())

@router.callback_query(F.data == "menu_start")
async def cb_menu_start(cb: CallbackQuery):
    await ensure_user(cb.from_user.id, cb.from_user.username)
    caption = "🏠 <b>Главное меню</b>\n\nВыбирай раздел, который тебя интересует:"
    try:
        if os.path.exists(IMG_START):
            await cb.message.delete()
            await cb.message.answer_photo(FSInputFile(IMG_START), caption=caption, reply_markup=main_inline_kb())
        else:
            await cb.message.edit_text(caption, reply_markup=main_inline_kb())
    except TelegramBadRequest: pass
    await cb.answer()

# ---------------------------------------------------------------------------
# ГАЙД (Как играть) - С ПОДМЕНЮ
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu_how")
async def cb_menu_how(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кубики и Спорт", callback_data="guide_dice"),
         InlineKeyboardButton(text="💣 Мины", callback_data="guide_mines")],
        [InlineKeyboardButton(text="⚔️ Дуэли", callback_data="guide_duel"),
         InlineKeyboardButton(text="🎡 Рулетка", callback_data="guide_roulette")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]
    ])
    if os.path.exists(IMG_HOW):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_HOW), caption="🎮 <b>Выбери раздел гайда:</b>", reply_markup=kb)
    else:
        await cb.message.edit_text("🎮 <b>Выбери раздел гайда:</b>", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "guide_dice")
async def guide_dice(cb: CallbackQuery):
    await cb.message.edit_text(HOW_TO_PLAY_DICE, reply_markup=back_kb("menu_how"))
    await cb.answer()

@router.callback_query(F.data == "guide_mines")
async def guide_mines(cb: CallbackQuery):
    await cb.message.edit_text(HOW_TO_PLAY_MINES, reply_markup=back_kb("menu_how"))
    await cb.answer()

@router.callback_query(F.data == "guide_duel")
async def guide_duel(cb: CallbackQuery):
    await cb.message.edit_text(HOW_TO_PLAY_DUEL, reply_markup=back_kb("menu_how"))
    await cb.answer()

@router.callback_query(F.data == "guide_roulette")
async def guide_roulette(cb: CallbackQuery):
    await cb.message.edit_text(HOW_TO_PLAY_ROULETTE, reply_markup=back_kb("menu_how"))
    await cb.answer()

# ---------------------------------------------------------------------------
# КОМАНДЫ
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu_commands")
async def cb_menu_commands(cb: CallbackQuery):
    if os.path.exists(IMG_COMMANDS):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_COMMANDS), caption=COMMANDS_TEXT, reply_markup=back_kb())
    else:
        await cb.message.edit_text(COMMANDS_TEXT, reply_markup=back_kb())
    await cb.answer()

# ---------------------------------------------------------------------------
# ПРОФИЛЬ
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu_profile")
async def cb_menu_profile(cb: CallbackQuery):
    u = await ensure_user(cb.from_user.id, cb.from_user.username)
    vip = "⭐ VIP" if u["vip"] else "Обычный"
    text = (
        f"👤 <b>Твой Профиль</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n"
        f"💎 Баланс: <b>{fmt(u['balance'])} TOKENS</b>\n"
        f"🎖 Статус: {vip}\n"
        f"🎮 Игр сыграно: <b>{u['games']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b>\n"
        f"🔔 Уведомления: {'вкл' if u['notifications'] else 'выкл'}\n"
        f"🌐 Язык: {u['lang']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История игр", callback_data="prof_history"),
         InlineKeyboardButton(text="⚙️ Настройки", callback_data="prof_settings")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]
    ])
    if os.path.exists(IMG_PROFILE):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_PROFILE), caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "prof_history")
async def cb_prof_history(cb: CallbackQuery):
    rows = await get_history(cb.from_user.id, 10)
    if not rows:
        text = "📜 <b>История пуста.</b>\nСыграй свою первую игру!"
    else:
        lines = ["📜 <b>Последние 10 игр:</b>\n"]
        for r in rows:
            sign = "🟢" if r["win"] > 0 else "🔴"
            lines.append(f"{sign} {r['game']} | ставка {fmt(r['bet'])} | выигрыш {fmt(r['win'])}")
        text = "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=back_kb("menu_profile"))
    await cb.answer()

@router.callback_query(F.data == "prof_settings")
async def cb_prof_settings(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    notif = "вкл" if u["notifications"] else "выкл"
    text = "⚙️ <b>Настройки профиля</b>\n\nЗдесь ты можешь настроить бота под себя."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 Уведомления: {notif}", callback_data="toggle_notif")],
        [InlineKeyboardButton(text="🌐 Сменить язык", callback_data="prof_lang")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_profile")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "toggle_notif")
async def cb_toggle_notif(cb: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id=?", (cb.from_user.id,))
        await db.commit()
    await cb.answer("Настройки сохранены")
    await cb_prof_settings(cb)

@router.callback_query(F.data == "prof_lang")
async def cb_prof_lang(cb: CallbackQuery):
    text = "🌐 <b>Выбери язык интерфейса:</b>\n(Пока доступен только RU)"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_RU")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="prof_settings")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data.startswith("set_lang_"))
async def cb_set_lang(cb: CallbackQuery):
    lang = cb.data.split("_")[2]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, cb.from_user.id))
        await db.commit()
    await cb.answer("Язык изменён")
    await cb_prof_settings(cb)

# ---------------------------------------------------------------------------
# ЕЖЕДНЕВНЫЙ БОНУС
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu_bonus")
async def cb_menu_bonus(cb: CallbackQuery):
    u = await ensure_user(cb.from_user.id, cb.from_user.username)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT last_claim FROM daily_bonus WHERE user_id=?", (cb.from_user.id,))
        row = await cur.fetchone()
    
    now = datetime.utcnow()
    can_claim = True
    time_left = ""
    
    if row and row[0]:
        diff = now - datetime.fromisoformat(row[0])
        if diff < timedelta(days=1):
            can_claim = False
            rem = timedelta(days=1) - diff
            time_left = f"{rem.seconds // 3600}ч {(rem.seconds % 3600) // 60}м"

    if can_claim:
        amount = 5000
        await add_balance(cb.from_user.id, amount)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO daily_bonus(user_id, last_claim) VALUES(?,?)", (cb.from_user.id, now.isoformat()))
            await db.commit()
        text = (
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"💰 Тебе начислено: <b>+{fmt(amount)} TOKENS</b>\n"
            f"💎 Твой баланс: <b>{fmt(u['balance'] + amount)}</b>\n\n"
            f"Возвращайся ровно через 24 часа за новой порцией!"
        )
    else:
        text = f"🎁 <b>Бонус уже получен!</b>\n\n⏳ Следующий через: <b>{time_left}</b>\n\n<i>Заходи в игровой чат, там тоже бывают дропы!</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 В игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]
    ])
    if os.path.exists(IMG_BONUS):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_BONUS), caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# ---------------------------------------------------------------------------
# ДОНАТ И ПРОЧЕЕ
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu_donate")
async def cb_menu_donate(cb: CallbackQuery):
    u = await ensure_user(cb.from_user.id, cb.from_user.username)
    text = (
        f"💎 <b>Пополнение баланса</b>\n\n"
        f"💱 Курс: <b>1⭐ = {fmt(STAR_RATE)} TOKENS</b>\n"
        f"💡 Пример: 100⭐ = <b>{fmt(100 * STAR_RATE)}</b> TOKENS\n\n"
        f"Твой баланс: <b>{fmt(u['balance'])}</b>\n\n"
        f"<i>Выбери сумму для покупки:</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50⭐", callback_data="buy_50"), InlineKeyboardButton(text="100⭐", callback_data="buy_100")],
        [InlineKeyboardButton(text="250⭐", callback_data="buy_250"), InlineKeyboardButton(text="500⭐", callback_data="buy_500")],
        [InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_custom")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]
    ])
    if os.path.exists(IMG_DONATE):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_DONATE), caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "buy_custom")
async def buy_custom_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BuyStars.custom)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="menu_start")]])
    await cb.message.edit_text("✍️ <b>Введи количество звёзд (1-10000):</b>", reply_markup=kb)
    await cb.answer()

@router.message(BuyStars.custom)
async def buy_custom_stars(msg: Message, state: FSMContext):
    try:
        stars = int(msg.text.strip())
        if not (1 <= stars <= 10000): raise ValueError
    except:
        await msg.answer("❌ Введи целое число от 1 до 10000.")
        return
    await state.clear()
    tokens = stars * STAR_RATE
    await add_balance(msg.from_user.id, tokens)
    await msg.answer(f"✅ Начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐", reply_markup=main_inline_kb())

@router.callback_query(F.data.startswith("buy_") & ~F.data.in_({"buy_custom"}))
async def buy_stars(cb: CallbackQuery):
    try: stars = int(cb.data.split("_")[1])
    except: return
    tokens = stars * STAR_RATE
    await add_balance(cb.from_user.id, tokens)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]])
    await cb.message.edit_text(f"✅ Начислено <b>{fmt(tokens)} TOKENS</b> за {stars}⭐", reply_markup=kb)
    await cb.answer("Готово")

@router.callback_query(F.data == "menu_top")
async def cb_menu_top(cb: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = await cur.fetchall()
    lines = ["🏆 <b>ТОП-10 ИГРОКОВ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    for i, (uname, bal) in enumerate(rows):
        lines.append(f"{medals[i]} @{uname or 'Игрок'} — <b>{fmt(bal)}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]])
    if os.path.exists(IMG_TOP):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_TOP), caption="\n".join(lines), reply_markup=kb)
    else:
        await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "menu_chats")
async def cb_menu_chats(cb: CallbackQuery):
    text = "💬 <b>Наши сообщества</b>\n\nВыбирай, куда хочешь попасть:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Игровой чат", url=CHAT_GAME)],
        [InlineKeyboardButton(text="💱 Обмен валют", url=CHAT_EXCHANGE)],
        [InlineKeyboardButton(text="📢 Новости", url=CHAT_NEWS)],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]
    ])
    if os.path.exists(IMG_CHATS):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_CHATS), caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "menu_support")
async def cb_menu_support(cb: CallbackQuery):
    text = "🆘 <b>Служба поддержки</b>\n\nЕсли у тебя возникли проблемы или вопросы — напиши нашему администратору:\n\n👤 @ТВОЙ_ЮЗЕРНЕЙМ"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu_start")]])
    if os.path.exists(IMG_SUPPORT):
        await cb.message.delete()
        await cb.message.answer_photo(FSInputFile(IMG_SUPPORT), caption=text, reply_markup=kb)
    else:
        await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# ---------------------------------------------------------------------------
# ИГРА: КУБИКИ
# ---------------------------------------------------------------------------
DICE_EMOJI = {"кубик": "🎲", "кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳", "бж": "🎰", "слоты": "🎰"}

@router.message(F.text.regexp(r"^(кубик|кубики|кости|дартс|баскет|баскетбол|футбол|боулинг|бж|слоты)\s+\d+$"))
async def dice_game(msg: Message):
    if msg.chat.type != ChatType.PRIVATE and not await chat_games_enabled(msg.chat.id): return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    parts = msg.text.lower().split()
    game, bet = parts[0], int(parts[1])
    if bet < 10: return await msg.reply("❌ Мин. ставка 10 TOKENS")
    if not await try_withdraw(msg.from_user.id, bet): return await msg.reply("❌ Недостаточно средств.")
    
    sent = await msg.reply_dice(emoji=DICE_EMOJI.get(game, "🎲"))
    val = sent.dice.value
    win = bet * 2 if val > 3 else 0
    if win: await add_balance(msg.from_user.id, win)
    await log_game(msg.from_user.id, f"dice_{game}", bet, win, f"val={val}")
    
    result_msg = await msg.reply(f"{'🎉 Победа!' if win else '😔 Проигрыш'}\nРезультат: <b>{val}</b>\nВыигрыш: <b>{fmt(win)}</b>")
    if msg.chat.type != ChatType.PRIVATE:
        asyncio.create_task(auto_delete(sent, DICE_AUTODELETE_SEC))
        asyncio.create_task(auto_delete(result_msg, DICE_AUTODELETE_SEC))

# ---------------------------------------------------------------------------
# ИГРА: МИНЫ
# ---------------------------------------------------------------------------
mines_sessions = {}
def build_mines_kb(session):
    btns = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5+c
            if idx in session["opened"]: row.append(InlineKeyboardButton(text="💎", callback_data=f"mine_{idx}"))
            elif idx in session.get("exploded", set()): row.append(InlineKeyboardButton(text="💥", callback_data="mine_noop"))
            else: row.append(InlineKeyboardButton(text="⬜", callback_data=f"mine_{idx}"))
        btns.append(row)
    btns.append([InlineKeyboardButton(text="💰 Забрать", callback_data="mine_take")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

@router.message(F.text.regexp(r"^мины\s+\d+$"))
async def mines_start(msg: Message):
    if msg.chat.type != ChatType.PRIVATE and not await chat_games_enabled(msg.chat.id): return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    bet = int(msg.text.split()[1])
    if bet < 10: return await msg.reply("❌ Мин. ставка 10")
    if not await try_withdraw(msg.from_user.id, bet): return await msg.reply("❌ Мало средств.")
    
    mines_sessions[msg.from_user.id] = {"chat_id": msg.chat.id, "bet": bet, "mines": set(random.sample(range(25), 3)), "opened": set(), "exploded": set()}
    await msg.reply(f"💣 <b>Мины</b>\nСтавка: {fmt(bet)}", reply_markup=build_mines_kb(mines_sessions[msg.from_user.id]))

@router.callback_query(F.data.startswith("mine_"))
async def mines_cb(cb: CallbackQuery):
    if cb.data == "mine_noop": return await cb.answer()
    if cb.data == "mine_take":
        s = mines_sessions.get(cb.from_user.id)
        if not s or not s["opened"]: return await cb.answer("Открой хотя бы одну!", show_alert=True)
        mines_sessions.pop(cb.from_user.id)
        win = int(s["bet"] * (1.0 + len(s["opened"])*0.15))
        await add_balance(cb.from_user.id, win)
        return await cb.message.edit_text(f"💰 Забрано: <b>{fmt(win)}</b>", reply_markup=None)
        
    idx = int(cb.data.split("_")[1])
    s = mines_sessions.get(cb.from_user.id)
    if not s: return await cb.answer("Игра окончена")
    if idx in s["mines"]:
        s["exploded"].add(idx)
        mines_sessions.pop(cb.from_user.id)
        return await cb.message.edit_text(f"💥 БУМ! Ставка {fmt(s['bet'])} сгорела.", reply_markup=build_mines_kb(s))
    
    s["opened"].add(idx)
    await cb.message.edit_reply_markup(reply_markup=build_mines_kb(s))
    await cb.answer(f"Множитель: x{1.0 + len(s['opened'])*0.15:.2f}")

# ---------------------------------------------------------------------------
# ИГРА: ДУЭЛИ
# ---------------------------------------------------------------------------
@router.message(F.text.regexp(r"^дуэль\s+@\w+\s+\d+$"))
async def duel_start(msg: Message):
    global _duel_seq
    if not await chat_games_enabled(msg.chat.id): return
    await ensure_user(msg.from_user.id, msg.from_user.username)
    target = msg.text.split()[1].lstrip("@")
    bet = int(msg.text.split()[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (target,))
        row = await cur.fetchone()
    if not row: return await msg.reply("❌ Игрок не найден.")
    if not await try_withdraw(msg.from_user.id, bet): return await msg.reply("❌ Мало средств.")
    
    _duel_seq += 1
    did = f"d{_duel_seq}"
    duel_sessions[did] = {"challenger": msg.from_user.id, "target": row[0], "bet": bet}
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"duel_yes_{did}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"duel_no_{did}")
    ]])
    await msg.reply(f"⚔️ <b>Дуэль!</b>\n@{msg.from_user.username} вызывает @{target}\nСтавка: {fmt(bet)}", reply_markup=kb)

@router.callback_query(F.data.startswith("duel_yes_"))
async def duel_accept(cb: CallbackQuery):
    did = cb.data.split("_")[2]
    s = duel_sessions.get(did)
    if not s or cb.from_user.id != s["target"]: return await cb.answer("Это не тебе.", show_alert=True)
    if not await try_withdraw(s["target"], s["bet"]):
        return await cb.answer("У тебя нет средств!", show_alert=True)
        
    d1, d2 = random.randint(1,6), random.randint(1,6)
    while d1 == d2: d2 = random.randint(1,6)
    winner = s["challenger"] if d1 > d2 else s["target"]
    
    await add_balance(winner, int(s["bet"]*2*0.95))
    duel_sessions.pop(did)
    await cb.message.edit_text(f"⚔️ Дуэль окончена!\n🎲 {d1} vs {d2}\n🏆 Победил: <code>{winner}</code>")

@router.callback_query(F.data.startswith("duel_no_"))
async def duel_decline(cb: CallbackQuery):
    did = cb.data.split("_")[2]
    s = duel_sessions.get(did)
    if not s or cb.from_user.id != s["target"]: return await cb.answer("Не тебе.")
    duel_sessions.pop(did)
    await cb.message.edit_text("❌ Дуэль отклонена.")

# ---------------------------------------------------------------------------
# РУЛЕТКА 2.0 (Жёсткая и без багов)
# ---------------------------------------------------------------------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

def parse_roulette_bet(text: str) -> Optional[dict]:
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    m = re.match(r"^(к|красное)\s+(\d+)$", t)
    if m: return {"type": "color", "value": "red", "amount": int(m.group(2))}
    m = re.match(r"^(ч|черное)\s+(\d+)$", t)
    if m: return {"type": "color", "value": "black", "amount": int(m.group(2))}
    m = re.match(r"^(0|зеро)\s+(\d+)$", t)
    if m: return {"type": "color", "value": "zero", "amount": int(m.group(2))}
    m = re.match(r"^(\d+)\s+(чет|чёт)$", t)
    if m: return {"type": "parity", "value": "even", "amount": int(m.group(1))}
    m = re.match(r"^(\d+)\s+(нечет|нечёт)$", t)
    if m: return {"type": "parity", "value": "odd", "amount": int(m.group(1))}
    m = re.match(r"^(\d+)\s+(.+)$", t)
    if m:
        amount = int(m.group(1))
        rest = m.group(2).strip()
        tokens = re.split(r"[,\s]+", rest)
        ranges, nums = [], []
        for tok in tokens:
            if not tok: continue
            rng = re.match(r"^(\d+)-(\d+)$", tok)
            if rng:
                a, b = int(rng.group(1)), int(rng.group(2))
                if a > b: a, b = b, a
                if 0 <= a <= 36 and 0 <= b <= 36: ranges.append((a, b))
                else: return None
            else:
                try:
                    n = int(tok)
                    if 0 <= n <= 36: nums.append(n)
                except: return None
        if ranges or nums: return {"type": "pack", "value": {"ranges": ranges, "nums": nums}, "amount": amount}
    return None

def format_bet_label(b: dict) -> str:
    t, v = b["type"], b["value"]
    if t == "color": return {"red": "🔴", "black": "⚫", "zero": "0️⃣"}[v]
    if t == "parity": return "🎯 Ч" if v == "even" else "🎯 Н"
    if t == "pack":
        parts = []
        if v["ranges"]: parts.append("📏 " + ", ".join(f"{a}-{b}" for a, b in v["ranges"]))
        if v["nums"]: parts.append("🔢 " + ", ".join(str(n) for n in v["nums"]))
        return " + ".join(parts)
    return "❔"

def calc_roulette_win(b: dict, number: int, color: str) -> int:
    t, v, amt = b["type"], b["value"], b["amount"]
    if t == "color":
        if v == color: return amt * 36 if color == "zero" else amt * 2
    elif t == "parity":
        if number != 0 and ((v == "even" and number % 2 == 0) or (v == "odd" and number % 2 != 0)): return amt * 2
    elif t == "pack":
        win = 0
        for a, bnd in v["ranges"]:
            if a <= number <= bnd: win += amt * 3
        if number in v["nums"]: win += amt * 36
        return win
    return 0

@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def roulette_handler(msg: Message):
    if not msg.text or msg.from_user.is_bot: return
    if not await chat_games_enabled(msg.chat.id): return
    
    text = msg.text.strip().lower()
    chat_id = msg.chat.id
    s = roulette_sessions.get(chat_id)

    if text == "старт":
        if s and s.get("running"): return await msg.reply("❗ Рулетка уже крутится!")
        if not s or not s.get("bets"): return await msg.reply("❌ Нет ставок! Сначала поставь.")
        if msg.from_user.id not in s["bets"]: return await msg.reply("❌ Ты не делал ставку, не можешь запустить.")
        
        s["running"] = True
        await msg.reply(f"🎰 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\nСобрано игроков: {len(s['bets'])}\nКрутим...")
        asyncio.create_task(roulette_spin(chat_id))
        return

    if s and s.get("running"): return

    parsed = parse_roulette_bet(text)
    if not parsed: return
    if parsed["amount"] < 10: return await msg.reply("❌ Мин. ставка 10 TOKENS")
    
    await ensure_user(msg.from_user.id, msg.from_user.username)
    if s and msg.from_user.id in s["bets"]: return await msg.reply("❗ Ты уже поставил.")
    if not await try_withdraw(msg.from_user.id, parsed["amount"]): return await msg.reply("❌ Мало средств.")

    if not s:
        s = {"bets": {}, "running": False}
        roulette_sessions[chat_id] = s
    s["bets"][msg.from_user.id] = [parsed]
    await msg.reply(f"✅ Ставка принята: {format_bet_label(parsed)} — <b>{fmt(parsed['amount'])}</b>\n👉 Напиши <code>старт</code>, чтобы запустить!")

async def roulette_spin(chat_id: int):
    s = roulette_sessions.get(chat_id)
    if not s: return
    
    lines = ["📋 <b>Все ставки:</b>"]
    for uid, bets in s["bets"].items():
        for b in bets:
            lines.append(f"• <code>{uid}</code>: {format_bet_label(b)} — <b>{fmt(b['amount'])}</b>")
    await safe_send(chat_id, "\n".join(lines))

    try:
        if os.path.exists(IMG_ROULETTE_GIF): await bot.send_animation(chat_id, FSInputFile(IMG_ROULETTE_GIF))
        else: await bot.send_dice(chat_id, emoji="🎰")
    except: pass
    
    await asyncio.sleep(3)
    number = random.randint(0, 36)
    color = "zero" if number == 0 else ("red" if number in RED_NUMBERS else "black")
    
    payout = 0
    winners = []
    for uid, bets in s["bets"].items():
        u_win = sum(calc_roulette_win(b, number, color) for b in bets)
        if u_win > 0:
            await add_balance(uid, u_win)
            payout += u_win
            winners.append(f"🆔 <code>{uid}</code> +{fmt(u_win)}")
            
    color_emoji = {"red": "🔴", "black": "⚫", "zero": "🟢"}[color]
    text = f"🎡 <b>Результат:</b> {color_emoji} <b>{number}</b>\n\n"
    if winners: text += "🏆 <b>Победители:</b>\n" + "\n".join(winners[:15]) + f"\n\n💰 Выплачено: <b>{fmt(payout)}</b>"
    else: text += "😔 Победителей нет."
        
    await safe_send(chat_id, text)
    roulette_sessions.pop(chat_id, None)

# ---------------------------------------------------------------------------
# ЖЁСТКАЯ АДМИНКА (@)
# ---------------------------------------------------------------------------
def is_admin(msg: Message) -> bool:
    return ADMIN_ID and msg.from_user and msg.from_user.id == ADMIN_ID

@router.message(F.text.regexp(r"^@"))
async def admin_cmds(msg: Message):
    if not is_admin(msg): return
    low = msg.text.strip().lower()

    if low == "@помощь": return await msg.reply(ADMIN_HELP)
    if low == "@режим_бога":
        await add_balance(msg.from_user.id, 1000000)
        return await msg.reply("👑 Режим бога активирован! +1 000 000 TOKENS")
    if low.startswith("@игры_выкл"):
        await set_chat_games(msg.chat.id, False)
        return await msg.reply("⛔ Игры отключены.")
    if low.startswith("@игры_вкл"):
        await set_chat_games(msg.chat.id, True)
        return await msg.reply("✅ Игры включены.")

    m = re.match(r"^@выдать\s+@(\w+)\s+(\d+)$", low)
    if m:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (m.group(1),))
            row = await cur.fetchone()
        if row:
            await add_balance(row[0], int(m.group(2)))
            await msg.reply(f"✅ Выдано @{m.group(1)}")
        return

    m = re.match(r"^@дроп\s+(\d+)$", low)
    if m:
        await send_bonus_drop(msg.chat.id, int(m.group(1)))
        return

    await msg.reply("🤔 Неизвестная команда. Напиши @помощь")

# ---------------------------------------------------------------------------
# БОНУСЫ И ЗАПУСК
# ---------------------------------------------------------------------------
async def send_bonus_drop(chat_id: int, amount: int):
    caption = f"🎁 <b>БОНУС!</b>\n\nКто первый — того и <b>{fmt(amount)} TOKENS</b>!"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Забрать", callback_data=f"claim_{amount}")]])
    try:
        if os.path.exists(IMG_BONUS):
            sent = await bot.send_photo(chat_id, FSInputFile(IMG_BONUS), caption=caption, reply_markup=kb)
        else:
            sent = await bot.send_message(chat_id, caption, reply_markup=kb)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO bonus_items(chat_id, message_id, amount, created_at) VALUES(?,?,?,?)",
                             (chat_id, sent.message_id, amount, datetime.utcnow().isoformat()))
            await db.commit()
    except: pass

@router.callback_query(F.data.startswith("claim_"))
async def claim_bonus(cb: CallbackQuery):
    amount = int(cb.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bonus_items WHERE chat_id=? AND message_id=?", (cb.message.chat.id, cb.message.message_id))
        row = await cur.fetchone()
        if not row or row["claimed_by"]: return await cb.answer("Уже забрали!", show_alert=True)
        await db.execute("UPDATE bonus_items SET claimed_by=? WHERE id=?", (cb.from_user.id, row["id"]))
        await db.commit()
    await ensure_user(cb.from_user.id, cb.from_user.username)
    await add_balance(cb.from_user.id, amount)
    await cb.answer(f"🎉 +{fmt(amount)}!", show_alert=True)
    try: await cb.message.edit_caption(caption=f"🎁 Забрал @{cb.from_user.username} — {fmt(amount)}")
    except: pass

async def health(_): return web.Response(text="Bot running")
async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    if not BOT_TOKEN: raise RuntimeError("No Token")
    await db_init()
    scheduler.start()
    await start_web()
    log.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): log.info("Bot stopped")