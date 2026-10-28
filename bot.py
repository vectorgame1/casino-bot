# ==============================================================================
# ИМПЕРИЯ TOKENS — Telegram-бот (aiogram 3.x + PostgreSQL)
# Полный рабочий код в одном файле (Максимально подробная версия)
# ==============================================================================

import os
import asyncio
import random
import logging
import datetime
import re
from typing import Optional

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from psycopg_pool import ConnectionPool

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, LabeledPrice,
    ReplyKeyboardRemove, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ForceReply
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# ==============================================================================
# 1. НАСТРОЙКИ
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/")
LINK_TO_TERMS = os.getenv("LINK_TO_TERMS", "https://t.me/")
PORT = int(os.getenv("PORT", "8080"))

START_BONUS = 5000
CURRENCY = "Tokens"
MAX_BET = 10_000_000
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ==============================================================================
# 2. БАЗА ДАННЫХ
# ==============================================================================
db_pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, timeout=10)

def db_execute(query: str, params=(), fetchone: bool = False, fetchall: bool = False):
    query = query.replace("?", "%s")
    try:
        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone() if fetchone else cur.fetchall() if fetchall else None
                conn.commit()
                return result
    except Exception as e:
        logger.error(f"DB error: {e} | query={query} | params={params}")
        return None

def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru',
        balance BIGINT DEFAULT 5000, role TEXT DEFAULT 'user', last_bonus TEXT,
        clan_id INTEGER DEFAULT NULL, clan_donated BIGINT DEFAULT 0,
        streak INTEGER DEFAULT 1, last_streak_date TEXT, last_seen TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id SERIAL PRIMARY KEY, name TEXT, owner_id BIGINT,
        treasury BIGINT DEFAULT 0, join_fee BIGINT DEFAULT 5000, level INTEGER DEFAULT 1, shield_until TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS tickets (
        id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (
        id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet BIGINT, win BIGINT, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (
        id SERIAL PRIMARY KEY, user_id BIGINT
    )""")
    
    # Безопасное добавление колонок, если база уже была создана ранее
    for col, q in [
        ("streak", "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak INTEGER DEFAULT 1"),
        ("last_streak_date", "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_streak_date TEXT"),
        ("last_seen", "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TEXT"),
        ("shield_until", "ALTER TABLE clans ADD COLUMN IF NOT EXISTS shield_until TEXT")
    ]:
        db_execute(q)
    logger.info("DB initialized.")

def get_user(uid: int):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (uid,), True)
    if not user:
        db_execute("INSERT INTO users (user_id, username, balance, last_seen) VALUES (?, 'Unknown', ?, ?) ON CONFLICT DO NOTHING", (uid, START_BONUS, datetime.datetime.now().isoformat()))
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (uid,), True)
    return user

def update_balance(uid: int, amt: int):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))

def set_username(uid: int, un: str):
    db_execute("UPDATE users SET username = ? WHERE user_id = ?", (un or "Unknown", uid))

def format_money(amt: int) -> str:
    try:
        return f"{int(amt):,}".replace(",", " ") + f" {CURRENCY}"
    except Exception:
        return f"{amt} {CURRENCY}"

def log_game(uid: int, game: str, bet: int, win: int):
    db_execute("INSERT INTO games_log (user_id, game, bet, win, date) VALUES (?, ?, ?, ?, ?)", (uid, game, bet, win, datetime.datetime.now().isoformat()))

def parse_amt(txt: str) -> Optional[int]:
    try:
        txt = txt.lower().replace(" ", "")
        m = re.match(r"^(\d+)(кк|к)?$", txt)
        if not m: return None
        val = int(m.group(1))
        if m.group(2) == "к": val *= 1000
        elif m.group(2) == "кк": val *= 1000000
        return val if 0 < val <= MAX_BET else None
    except Exception:
        return None

# ==============================================================================
# 3. ЛОКАЛИЗАЦИЯ
# ==============================================================================
TEXTS = {
    "ru": {
        "menu": "🏠 <b>Главное меню:</b>",
        "profile": "👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n🆔 ID: <code>{uid}</code>\n🏆 Ранг: <b>{rank}</b>\n💰 Баланс: <b>{bal}</b>\n💎 VIP: {vip}\n🛡 Клан: {clan}",
        "balance": "💰 <b>Баланс</b> {name}:\n💵 <b>{bal}</b>",
        "win": "🎉 <b>ПОБЕДА!</b>\nВыпало: {val}\nВыигрыш: <b>{prize}</b>",
        "lose": "😢 <b>Проигрыш.</b>\nВыпало: {val}",
        "not_enough": "❌ Мало средств.",
        "bet_acc": "✅ <b>Ставка принята:</b> {name}\n🎯 На: {bet}\n💰 Сумма: {amt}",
        "bonus_wait": "⏳ <b>Бонус уже забран.</b>\nСледующий через: <b>{h} ч. {m} мин.</b>",
        "btn_profile": "👤 Профиль", "btn_bonus": "🎁 Бонус", "btn_donate": "💎 Донат",
        "btn_clan": "🛡 Клан", "btn_shop": "🛒 Магазин", "btn_lang": "🌐 Язык",
        "btn_support": "🆘 Поддержка", "btn_back": "⬅️ Меню"
    },
    "en": {
        "menu": "🏠 <b>Main menu:</b>",
        "profile": "👤 <b>YOUR PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n🏆 Rank: <b>{rank}</b>\n💰 Balance: <b>{bal}</b>\n💎 VIP: {vip}\n🛡 Clan: {clan}",
        "balance": "💰 <b>Balance</b> {name}:\n💵 <b>{bal}</b>",
        "win": "🎉 <b>WIN!</b>\nRolled: {val}\nPrize: <b>{prize}</b>",
        "lose": "😢 <b>Lose.</b>\nRolled: {val}",
        "not_enough": "❌ Not enough funds.",
        "bet_acc": "✅ <b>Bet accepted:</b> {name}\n🎯 On: {bet}\n💰 Amount: {amt}",
        "bonus_wait": "⏳ <b>Bonus already taken.</b>\nNext in: <b>{h}h {m}m</b>",
        "btn_profile": "👤 Profile", "btn_bonus": "🎁 Bonus", "btn_donate": "💎 Donate",
        "btn_clan": "🛡 Clan", "btn_shop": "🛒 Shop", "btn_lang": "🌐 Language",
        "btn_support": "🆘 Support", "btn_back": "⬅️ Menu"
    }
}

def _(user, key, **kwargs):
    lang = user[2] if user and len(user) > 2 and user[2] in TEXTS else "ru"
    return TEXTS[lang].get(key, "").format(**kwargs)

# ==============================================================================
# 4. СТИКЕРЫ
# ==============================================================================
STICKER_MONEY = "CAACAgIAAxkBAAEj985q4eL9Brj-YpyQvGjLXw3FCOZZjQACSKgAAjAhEUsk5lafkHLFYD0E"
STICKER_GIFT = "CAACAgIAAxkBAAEj98Bq4eLXEYu2vZI5kR8FAa-5At5VCwACLqwAAkDWEEu1vr_yoL997j0E"
STICKER_CHECK = "CAACAgIAAxkBAAEj97Jq4eKR30htSL0IqPlPzJVRVzFtJwACYqIAAmLKEEtbsW05dAABQME9BA"
STICKER_CROSS = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"
STICKER_WAIT = "CAACAgIAAxkBAAEj97hq4eKu4LVAQjvc8bvWLJsPGs4AAfcAAu6lAAIhCRFLfU-i5scDVp49BA"
STICKER_TRANSFER = "CAACAgEAAxkBAAEj9-Bq4eVW4VZEtByB92myle5Upux2mgACzgIAAgZEGETPmJF48lyuaD0E"
STICKER_TICKET = "CAACAgIAAxkBAAEj975q4eLJDqoTYwmhP1WgPmG147qWZgACdKkAAlAcEEt7BK5iDF740T0E"
STICKER_WHEEL = "CAACAgIAAxkBAAEj98Jq4eLY_6DZL-z-pta0MkNblBDoIAACY6YAAopJCEulegpkQ4jAtj0E"
STICKER_REF = "CAACAgEAAxkBAAEj9-Bq4eVW4VZEtByB92myle5Upux2mgACzgIAAgZEGETPmJF48lyuaD0E"
STICKER_CROWN = "CAACAgIAAxkBAAEj99Bq4eL-1vc-E-lWg0SnnmQOohX96wACxaQAAu96EUteo43HZ6JM4T0E"
STICKER_FIREWORK = "CAACAgIAAxkBAAEj98xq4eL9f_1pJgjxIaZqYyfRDkVuIwACX6UAAt7VEEtyBsfC0Eld5z0E"
STICKER_TICKET_REPLY = "CAACAgIAAxkBAAEj97xq4eLIV5K-h2PJATFWIiPa7RjmrQACU6kAAg9PCEvOBzdsgawr_z0E"
STICKER_CLOCK = "CAACAgIAAxkBAAEj97pq4eK_3AjVJQ0c8YUiUwIfWprFXQACPaEAAm2sEUtORD2DpdGqTz0E"

VIP_STICKERS = [
    "CAACAgIAAxkBAAEj965q4eJ3NdOJTNZKOXjLl-EefvciHgACJaAAAuNkEEtMkr6KfsoC1j0E",
    "CAACAgIAAxkBAAEj96xq4eJXgVef7iLshpSS5HehGR9fvAACX7IAAgOYEEtkVuP2AAGD3tY9BA"
]

# ==============================================================================
# 5. КЛАВИАТУРЫ
# ==============================================================================
def get_main_menu(u):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text=_(u, "btn_profile")), KeyboardButton(text=_(u, "btn_bonus")))
    b.row(KeyboardButton(text=_(u, "btn_donate")), KeyboardButton(text=_(u, "btn_clan")))
    b.row(KeyboardButton(text=_(u, "btn_shop")), KeyboardButton(text=_(u, "btn_lang")))
    b.row(KeyboardButton(text=_(u, "btn_support")))
    return b.as_markup(resize_keyboard=True)

def get_profile_menu(u):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📜 История"), KeyboardButton(text="🔗 Рефка"))
    b.row(KeyboardButton(text=_(u, "btn_back")))
    return b.as_markup(resize_keyboard=True)

def get_donate_menu(u):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="⭐ Звезды"), KeyboardButton(text="👑 VIP"))
    b.row(KeyboardButton(text=_(u, "btn_back")))
    return b.as_markup(resize_keyboard=True)

def get_support_menu(u):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="✍️ Написать Админу"))
    b.row(KeyboardButton(text=_(u, "btn_back")))
    return b.as_markup(resize_keyboard=True)

def get_clan_menu_kb(has_clan, is_owner, u):
    b = ReplyKeyboardBuilder()
    if not has_clan:
        b.row(KeyboardButton(text="➕ Создать"), KeyboardButton(text="🏆 Топ"))
        b.row(KeyboardButton(text="🤝 Вступить"))
    else:
        b.row(KeyboardButton(text="💰 Внести"), KeyboardButton(text="🏆 Топ"))
        b.row(KeyboardButton(text="📜 Мой клан"), KeyboardButton(text="🛡 Щит"))
        if is_owner:
            b.row(KeyboardButton(text="📈 Прокачать"), KeyboardButton(text="💵 Налог"))
            b.row(KeyboardButton(text="🥾 Кик"))
        else:
            b.row(KeyboardButton(text="🚪 Выйти"))
    b.row(KeyboardButton(text=_(u, "btn_back")))
    return b.as_markup(resize_keyboard=True)

# ==============================================================================
# 6. BOT / DISPATCHER / ROUTERS
# ==============================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

user_router = Router()
admin_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, group_router)

# ==============================================================================
# 7. FSM-СОСТОЯНИЯ
# ==============================================================================
class SupportStates(StatesGroup):
    waiting_ticket = State()

class StarStates(StatesGroup):
    waiting_amount = State()

class ClanStates(StatesGroup):
    waiting_name = State()
    waiting_deposit = State()
    waiting_kick = State()
    waiting_join = State()

class GameStates(StatesGroup):
    waiting_dice_bet = State()
    waiting_roulette_bet = State()
    waiting_mines_bet = State()
    waiting_bj_bet = State()

# ==============================================================================
# 8. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ АВТОУДАЛЕНИЯ
# ==============================================================================
async def auto_delete(message: Message, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

async def delete_old_messages(bot_instance: Bot, state: FSMContext, chat_id: int):
    """Удаляет предыдущие сообщения бота, сохраненные в FSM"""
    data = await state.get_data()
    msg_ids = data.get("last_msgs", [])
    for mid in msg_ids:
        try:
            await bot_instance.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    await state.update_data(last_msgs=[])

# ==============================================================================
# 9. ХЕНДЛЕРЫ ЛС: СТАРТ И НАВИГАЦИЯ
# ==============================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if message.from_user.username:
        await asyncio.to_thread(set_username, message.from_user.id, message.from_user.username)
    await asyncio.to_thread(db_execute, "UPDATE users SET last_seen = ? WHERE user_id = ?", (datetime.datetime.now().isoformat(), user[0]))

    if user[4] == "banned":
        await message.answer("🚫 <b>Твой аккаунт заблокирован.</b>")
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return

    text = (
        f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В ИМПЕРИЮ TOKENS, {message.from_user.first_name}!</b>\n\n"
        f"💎 Здесь ты сам вершишь свою судьбу. Испытай удачу в играх, "
        f"прокачай свой клан или сорви джекпот в нашем чате!\n\n"
        f"⚖️ <i>Виртуальная экономика. Все ставки — развлечение. Играй с умом.</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚀 Ворваться в игру (Чат)", url=GROUP_LINK))
    kb.row(InlineKeyboardButton(text="📜 Правила Дома", url=LINK_TO_TERMS))

    try:
        msg = await message.answer_photo(FSInputFile("assets/start.jpg"), caption=text, reply_markup=kb.as_markup())
    except Exception:
        msg = await message.answer(text, reply_markup=kb.as_markup())

    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text.in_(["⬅️ Меню", "⬅️ Главное меню"]))
async def global_back(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    msg = await message.answer(_(user, "menu"), reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

# ==============================================================================
# 10. ПРОФИЛЬ
# ==============================================================================
@user_router.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def profile(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    bal = user[3]
    rank = "💎 Легенда" if bal > 1_000_000 else "🔥 Хайроллер" if bal > 500_000 else "⭐ Профи" if bal > 100_000 else "🟢 Новичок"
    vip = "👑 VIP" if user[4] == "vip" else "❌ Нет"
    clan = "Есть" if user[12] else "Нет"
    
    text = _(user, "profile", uid=user[0], rank=rank, bal=format_money(bal), vip=vip, clan=clan)
    
    new_ids = []
    if user[4] == "vip":
        try:
            st = await message.answer_sticker(random.choice(VIP_STICKERS))
            new_ids.append(st.message_id)
        except Exception:
            pass
            
    msg = await message.answer(text, reply_markup=get_profile_menu(user))
    new_ids.append(msg.message_id)
    await state.update_data(last_msgs=new_ids)

@user_router.message(F.text == "📜 История")
async def history(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rows = await asyncio.to_thread(db_execute, "SELECT game, bet, win, date FROM games_log WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user[0],), False, True)
    
    if not rows:
        msg = await message.answer("📜 История пуста. Сыграй в чате!", reply_markup=get_profile_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
        return
        
    lines = ["📜 <b>Последние 10 игр:</b>\n"]
    for game, bet, win, date in rows:
        sign = "🟢" if win > 0 else "🔴"
        lines.append(f"{sign} <b>{game}</b> · ставка {format_money(bet)} · выигрыш {format_money(win)}")
        
    msg = await message.answer("\n".join(lines), reply_markup=get_profile_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "🔗 Рефка")
async def refka(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user[0]}"
    
    new_ids = []
    try:
        st = await message.answer_sticker(STICKER_REF)
        new_ids.append(st.message_id)
    except Exception:
        pass
        
    msg = await message.answer(f"🔗 <b>Твоя реферальная ссылка:</b>\n<code>{link}</code>\n\nПриглашай друзей и получай бонусы!", reply_markup=get_profile_menu(user))
    new_ids.append(msg.message_id)
    await state.update_data(last_msgs=new_ids)

# ==============================================================================
# 11. БОНУС, СТРИК, ТОП
# ==============================================================================
@user_router.message(F.text.in_(["🎁 Бонус", "🎁 Bonus"]))
async def daily_bonus(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    now = datetime.datetime.now()

    if user[5]:
        try:
            last_dt = datetime.datetime.fromisoformat(user[5])
            if now - last_dt < datetime.timedelta(hours=24):
                delta = datetime.timedelta(hours=24) - (now - last_dt)
                hrs = delta.seconds // 3600
                mins = (delta.seconds % 3600) // 60
                bars = int((hrs / 24) * 10)
                bar = "🟩" * bars + "⬜️" * (10 - bars)
                
                new_ids = []
                try:
                    st = await message.answer_sticker(STICKER_CLOCK)
                    new_ids.append(st.message_id)
                except Exception:
                    pass
                    
                msg = await message.answer(_(user, "bonus_wait", h=hrs, m=mins) + f"\n[{bar}]", reply_markup=get_main_menu(user))
                new_ids.append(msg.message_id)
                await state.update_data(last_msgs=new_ids)
                return
        except ValueError:
            pass

    streak = user[13] or 1
    if user[14]:
        last_s = datetime.datetime.fromisoformat(user[14]).date()
        if (now.date() - last_s).days == 1:
            streak += 1
        elif (now.date() - last_s).days > 1:
            streak = 1

    prize = random.randint(2500, 25000)
    text = f"🎉 <b>УДАЧА УЛЫБНУЛАСЬ ТЕБЕ!</b>\n\n💰 Ты выиграл: <b>+{format_money(prize)}</b>"
    
    if streak >= 7:
        prize *= 2
        text = f"🔥 <b>СТРИК 7 ДНЕЙ!</b> Бонус x2!\n\n💰 Ты выиграл: <b>+{format_money(prize)}</b>"

    await asyncio.to_thread(update_balance, user[0], prize)
    await asyncio.to_thread(db_execute, "UPDATE users SET last_bonus=?, streak=?, last_streak_date=? WHERE user_id=?", (now.isoformat(), streak, now.date().isoformat(), user[0]))

    new_ids = []
    try:
        st = await message.answer_sticker(STICKER_WHEEL)
        new_ids.append(st.message_id)
    except Exception:
        pass
        
    msg = await message.answer(text, reply_markup=get_main_menu(user))
    new_ids.append(msg.message_id)
    await state.update_data(last_msgs=new_ids)

@user_router.message(Command("топ", "top"))
async def top_cmd(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rows = await asyncio.to_thread(db_execute, "SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10", (), False, True)
    
    if not rows:
        msg = await message.answer("Пусто.", reply_markup=get_main_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
        return
        
    text = "🏆 <b>ТОП-10 БОГАЧЕЙ:</b>\n\n"
    for i, (un, bal) in enumerate(rows, 1):
        icon = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{icon} @{un or '—'} — {format_money(bal)}\n"
        
    msg = await message.answer(text, reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

# ==============================================================================
# 12. ДОНАТ
# ==============================================================================
def _get_rate() -> int:
    hour = datetime.datetime.now().hour
    rnd = random.Random(hour // 3)
    return rnd.randint(8000, 15000)

@user_router.message(F.text.in_(["💎 Донат", "💎 Donate"]))
async def donate_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rate = _get_rate()
    text = f"💎 <b>ДОНАТ И VIP</b>\n\n🔥 Курс дня: 1 ⭐ = <b>{rate:,}</b> {CURRENCY}\n<i>(Обновляется каждые 3 часа)</i>"
    msg = await message.answer(text, reply_markup=get_donate_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "⭐ Звезды")
async def buy_stars_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rate = _get_rate()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ 15 Stars", callback_data=f"buy_stars_15_{rate}"))
    kb.row(InlineKeyboardButton(text="⭐ 50 Stars", callback_data=f"buy_stars_50_{rate}"))
    kb.row(InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_stars_custom"))
    msg = await message.answer(f"⭐ <b>ПОКУПКА ЗВЕЗД</b>\n\n🔥 Курс: 1 ⭐ = {rate} {CURRENCY}", reply_markup=kb.as_markup())
    await state.update_data(last_msgs=[msg.message_id])

@user_router.callback_query(F.data == "buy_stars_custom")
async def stars_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введи количество звёзд (1–10000):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(StarStates.waiting_amount)
    await callback.answer()

@user_router.message(StarStates.waiting_amount)
async def stars_custom_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if not 1 <= amount <= 10000:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введи целое число от 1 до 10000.")
    rate = _get_rate()
    await message.answer_invoice(
        title=f"Звезды ({amount})", description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}_{rate}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=amount)], start_parameter="buy"
    )
    await state.clear()

@user_router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    data = callback.data
    if data == "buy_stars_custom":
        return
    _, _, amount, rate = data.split("_")
    await callback.message.answer_invoice(
        title="Звезды", description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}_{rate}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=int(amount))], start_parameter="buy"
    )
    await callback.answer()

@user_router.message(F.text == "👑 VIP")
async def buy_vip_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👑 VIP 1 день (5 ⭐)", callback_data="buy_vip_5_1"))
    kb.row(InlineKeyboardButton(text="👑 VIP 7 дней (30 ⭐)", callback_data="buy_vip_30_7"))
    kb.row(InlineKeyboardButton(text="👑 VIP 30 дней (100 ⭐)", callback_data="buy_vip_100_30"))
    msg = await message.answer("👑 <b>ПОКУПКА VIP</b>\n\nВыбери срок:", reply_markup=kb.as_markup())
    await state.update_data(last_msgs=[msg.message_id])

@user_router.callback_query(F.data.startswith("buy_vip_"))
async def process_buy_vip(callback: CallbackQuery):
    _, _, price, days = callback.data.split("_")
    await callback.message.answer_invoice(
        title=f"VIP {days} дн.", description="Активация VIP",
        payload=f"vip_{days}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label="VIP", amount=int(price))], start_parameter="buy"
    )
    await callback.answer()

@user_router.message(F.successful_payment)
async def success_payment(message: Message, state: FSMContext):
    payment = message.successful_payment
    user = await asyncio.to_thread(get_user, message.from_user.id)
    
    new_ids = []
    try:
        st = await message.answer_sticker(STICKER_FIREWORK)
        new_ids.append(st.message_id)
    except Exception:
        pass

    if payment.invoice_payload.startswith("vip_"):
        days = int(payment.invoice_payload.split("_")[1])
        await asyncio.to_thread(db_execute, "UPDATE users SET role = 'vip' WHERE user_id = ?", (user[0],))
        await asyncio.to_thread(update_balance, user[0], 10000 * days)
        msg = await message.answer(f"✅ <b>VIP АКТИВИРОВАН!</b>\nСрок: {days} дней.", reply_markup=get_main_menu(user))
        new_ids.append(msg.message_id)

    elif payment.invoice_payload.startswith("stars_"):
        _, stars_amount, rate = payment.invoice_payload.split("_")
        total = int(stars_amount) * int(rate)
        await asyncio.to_thread(update_balance, user[0], total)
        msg = await message.answer(f"✅ <b>ОПЛАТА УСПЕШНА!</b>\nЗачислено: <b>{format_money(total)}</b>", reply_markup=get_main_menu(user))
        new_ids.append(msg.message_id)
        
    await state.update_data(last_msgs=new_ids)

# ==============================================================================
# 13. МАГАЗИН
# ==============================================================================
@user_router.message(F.text.in_(["🛒 Магазин", "🛒 Shop"]))
async def shop_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎟 Сброс Бонуса (100к)", callback_data="shop_bonus"))
    kb.row(InlineKeyboardButton(text="⚡ Сброс Рулетки (50к)", callback_data="shop_roulette"))
    kb.row(InlineKeyboardButton(text="🛡 Щит Клана (250к)", callback_data="shop_shield"))
    msg = await message.answer("🛒 <b>МАГАЗИН БУСТОВ</b>\n\nВыбери товар:", reply_markup=kb.as_markup())
    await state.update_data(last_msgs=[msg.message_id])

@user_router.callback_query(F.data == "shop_bonus")
async def shop_bonus(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    if user[3] < 100_000:
        return await callback.answer("❌ Мало средств!", show_alert=True)
    await asyncio.to_thread(update_balance, user[0], -100_000)
    await asyncio.to_thread(db_execute, "UPDATE users SET last_bonus = NULL WHERE user_id = ?", (user[0],))
    await callback.message.edit_text("✅ Кулдаун бонуса сброшен!")
    await callback.answer()

# ==============================================================================
# 14. ПОДДЕРЖКА (ТИКЕТЫ)
# ==============================================================================
@user_router.message(F.text.in_(["🆘 Поддержка", "🆘 Support"]))
async def support_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    msg = await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\nВыбери действие:", reply_markup=get_support_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "✍️ Написать Админу")
async def sup_ticket(message: Message, state: FSMContext):
    await message.answer("✍️ Опиши проблему одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_ticket)

@user_router.message(SupportStates.waiting_ticket)
async def process_ticket(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    await asyncio.to_thread(db_execute, "INSERT INTO tickets (user_id, text, date) VALUES (?, ?, ?)", (user[0], message.text, datetime.datetime.now().isoformat()))
    
    try:
        await bot.send_message(ADMIN_ID, f"🎫 <b>ТИКЕТ</b>\nОт: @{message.from_user.username or message.from_user.id}\n{message.text}")
    except Exception as e:
        logger.warning(f"Тикет не отправлен: {e}")
        
    try:
        await message.answer_sticker(STICKER_TICKET)
    except Exception:
        pass
        
    msg = await message.answer("✅ Тикет отправлен.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()

# ==============================================================================
# 15. ЯЗЫК
# ==============================================================================
@user_router.message(F.text.in_(["🌐 Язык", "🌐 Language"]))
async def lang_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"), InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"))
    msg = await message.answer("🌐 Выбери язык / Choose language:", reply_markup=kb.as_markup())
    await state.update_data(last_msgs=[msg.message_id])

@user_router.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await asyncio.to_thread(db_execute, "UPDATE users SET lang = ? WHERE user_id = ?", (lang, callback.from_user.id))
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await callback.answer("✅ Язык изменен / Language changed!")
    await callback.message.edit_text(_(user, "menu"), reply_markup=get_main_menu(user))

# ==============================================================================
# 16. КЛАНЫ
# ==============================================================================
@user_router.message(F.text == "🛡 Клан")
async def clan_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    
    if not user[12]:
        msg = await message.answer("🛡 <b>КЛАНОВАЯ СИСТЕМА</b>\n\nТы пока не в клане.", reply_markup=get_clan_menu_kb(False, False, user))
        await state.update_data(last_msgs=[msg.message_id])
        return
        
    clan = await asyncio.to_thread(db_execute, "SELECT name, owner_id, treasury, join_fee, level FROM clans WHERE id = ?", (user[12],), True)
    if not clan:
        await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
        msg = await message.answer("Клан не найден.", reply_markup=get_clan_menu_kb(False, False, user))
        await state.update_data(last_msgs=[msg.message_id])
        return
        
    is_owner = clan[1] == user[0]
    progress = min(int((clan[2] / 1_000_000) * 10), 10)
    bar = "🟩" * progress + "⬜️" * (10 - progress)
    text = f"🛡 <b>Клан: {clan[0]}</b>\n👑 Владелец: {'Ты' if is_owner else clan[1]}\n📈 Ур: {clan[4]}/5\n💰 {format_money(clan[2])}\n[{bar}]\nВход: {format_money(clan[3])}"
    
    new_ids = []
    try:
        st = await message.answer_sticker(STICKER_CROWN)
        new_ids.append(st.message_id)
    except Exception:
        pass
        
    msg = await message.answer(text, reply_markup=get_clan_menu_kb(True, is_owner, user))
    new_ids.append(msg.message_id)
    await state.update_data(last_msgs=new_ids)

@user_router.message(F.text == "➕ Создать")
async def clan_create_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < 100_000:
        return await message.answer("❌ Нужно 100 000 Tokens.")
    if user[12]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана (до 30 символов):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_name)

@user_router.message(ClanStates.waiting_name)
async def clan_create_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:30]
    if not name:
        return await message.answer("❌ Пустое имя.")
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < 100_000:
        await state.clear()
        return await message.answer("❌ Не хватает средств.")
        
    await asyncio.to_thread(update_balance, user[0], -100_000)
    clan = await asyncio.to_thread(db_execute, "INSERT INTO clans (name, owner_id, treasury, join_fee, level) VALUES (?, ?, 0, 5000, 1) RETURNING id", (name, user[0]), True)
    
    if clan:
        await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = ? WHERE user_id = ?", (clan[0], user[0]))
        try:
            await message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        msg = await message.answer(f"✅ Клан <b>{name}</b> создан!", reply_markup=get_main_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
    else:
        await message.answer("❌ Ошибка создания.")
    await state.clear()

@user_router.message(F.text == "🏆 Топ")
async def clan_top(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rows = await asyncio.to_thread(db_execute, "SELECT name, treasury, level FROM clans ORDER BY treasury DESC LIMIT 10", (), False, True)
    
    if not rows:
        msg = await message.answer("🏆 Пока нет кланов.", reply_markup=get_main_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
        return
        
    lines = ["🏆 <b>ТОП-10 КЛАНОВ</b>\n"]
    for i, (name, treasury, level) in enumerate(rows, 1):
        lines.append(f"{i}. <b>{name}</b> · ур.{level} · {format_money(treasury)}")
        
    msg = await message.answer("\n".join(lines), reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "💰 Внести")
async def clan_deposit_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
    await message.answer("💰 Введи сумму для внесения:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_deposit)

@user_router.message(ClanStates.waiting_deposit)
async def clan_deposit_finish(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except Exception:
        return await message.answer("❌ Введи положительное число.")
        
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        await state.clear()
        return await message.answer("❌ Мало средств.")
        
    await asyncio.to_thread(update_balance, user[0], -amount)
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, user[12]))
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_donated = clan_donated + ? WHERE user_id = ?", (amount, user[0]))
    
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"✅ Внесено в казну: <b>{format_money(amount)}</b>", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()

@user_router.message(F.text == "📜 Мой клан")
async def clan_my(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
        
    clan = await asyncio.to_thread(db_execute, "SELECT name, treasury, level, owner_id FROM clans WHERE id = ?", (user[12],), True)
    members = await asyncio.to_thread(db_execute, "SELECT COUNT(*) FROM users WHERE clan_id = ?", (user[12],), True)
    
    if not clan:
        return await message.answer("❌ Клан не найден.")
        
    name, treasury, level, owner_id = clan
    owner = await asyncio.to_thread(db_execute, "SELECT username FROM users WHERE user_id = ?", (owner_id,), True)
    text = f"📜 <b>{name}</b>\n👑 Владелец: @{owner[0] if owner else '—'}\n📈 Уровень: {level}\n👥 Участников: {members[0] if members else 0}\n💰 Казна: {format_money(treasury)}"
    
    msg = await message.answer(text, reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "🛡 Щит")
async def clan_shield(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
    if user[3] < 250_000:
        return await message.answer("❌ Нужно 250 000 Tokens.")
        
    await asyncio.to_thread(update_balance, user[0], -250_000)
    shield_until = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    await asyncio.to_thread(db_execute, "UPDATE clans SET shield_until = ? WHERE id = ?", (shield_until, user[12]))
    
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer("🛡 Щит клана активирован на 7 дней!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "📈 Прокачать")
async def clan_upgrade(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
        
    clan = await asyncio.to_thread(db_execute, "SELECT owner_id, level, treasury FROM clans WHERE id = ?", (user[12],), True)
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может качать клан.")
    if clan[1] >= 5:
        return await message.answer("✅ Максимальный уровень.")
        
    cost = 250_000 * clan[1]
    if user[3] < cost:
        return await message.answer(f"❌ Нужно {format_money(cost)} на балансе.")
        
    await asyncio.to_thread(update_balance, user[0], -cost)
    await asyncio.to_thread(db_execute, "UPDATE clans SET level = level + 1 WHERE id = ?", (user[12],))
    
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"📈 Клан прокачан до уровня {clan[1] + 1}!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "💵 Налог")
async def clan_tax(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
        
    clan = await asyncio.to_thread(db_execute, "SELECT owner_id, treasury FROM clans WHERE id = ?", (user[12],), True)
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может собрать налог.")
        
    tax = int(clan[1] * 0.10)
    if tax <= 0:
        return await message.answer("❌ Казна пуста.")
        
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury - ? WHERE id = ?", (tax, user[12]))
    await asyncio.to_thread(update_balance, user[0], tax)
    
    try:
        await message.answer_sticker(STICKER_MONEY)
    except Exception:
        pass
    msg = await message.answer(f"💵 Собрано 10% налога: <b>{format_money(tax)}</b>", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

@user_router.message(F.text == "🥾 Кик")
async def clan_kick_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
        
    clan = await asyncio.to_thread(db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[12],), True)
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может кикать.")
        
    await message.answer("🥾 Отправь @username или ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_kick)

@user_router.message(ClanStates.waiting_kick)
async def clan_kick_finish(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    target_id = None
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        raw = (message.text or "").strip().lstrip("@")
        if raw.isdigit():
            target_id = int(raw)
        else:
            found = await asyncio.to_thread(db_execute, "SELECT user_id FROM users WHERE username = ?", (raw,), True)
            if found:
                target_id = found[0]
                
    if not target_id:
        await state.clear()
        return await message.answer("❌ Игрок не найден.", reply_markup=get_main_menu(user))
        
    target = await asyncio.to_thread(get_user, target_id)
    if not target or target[12] != user[12]:
        await state.clear()
        return await message.answer("❌ Игрок не в твоём клане.", reply_markup=get_main_menu(user))
        
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (target_id,))
    
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer("✅ Игрок исключён из клана.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()

@user_router.message(F.text == "🤝 Вступить")
async def clan_join_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[12]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_join)

@user_router.message(ClanStates.waiting_join)
async def clan_join_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    clan = await asyncio.to_thread(db_execute, "SELECT id, join_fee FROM clans WHERE name = ?", (name,), True)
    
    if not clan:
        await state.clear()
        return await message.answer("❌ Клан не найден.", reply_markup=get_main_menu(await asyncio.to_thread(get_user, message.from_user.id)))
        
    cid, fee = clan
    user = await asyncio.to_thread(get_user, message.from_user.id)
    
    if user[3] < fee:
        await state.clear()
        return await message.answer(f"❌ Нужно {format_money(fee)} на вход.", reply_markup=get_main_menu(user))

    await asyncio.to_thread(update_balance, user[0], -fee)
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (fee, cid))
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = ? WHERE user_id = ?", (cid, user[0]))
    
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"✅ Ты вступил в клан <b>{name}</b>!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()

@user_router.message(F.text == "🚪 Выйти")
async def clan_leave(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
        
    clan = await asyncio.to_thread(db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[12],), True)
    if clan and clan[0] == user[0]:
        return await message.answer("👑 Владелец не может выйти.")
        
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
    msg = await message.answer("✅ Ты вышел из клана.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])

# ==============================================================================
# 17. ГРУППА: БАЛАНС, ПЕРЕВОД, ТОП
# ==============================================================================
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
        
    user = await asyncio.to_thread(get_user, message.from_user.id)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    text = _(user, "balance", name=name, bal=format_money(user[3]))
    
    msg = await message.reply(text)
    try:
        sticker = random.choice(VIP_STICKERS) if user[4] == "vip" else STICKER_MONEY
        await msg.reply_sticker(sticker)
    except Exception:
        pass
    asyncio.create_task(auto_delete(msg, 60))

@group_router.message(Command("топ", "top"))
async def cmd_top_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
        
    rows = await asyncio.to_thread(db_execute, "SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10", (), False, True)
    if not rows:
        return
        
    text = "🏆 <b>ТОП-10 БОГАЧЕЙ:</b>\n\n"
    for i, (un, bal) in enumerate(rows, 1):
        icon = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{icon} @{un or '—'} — {format_money(bal)}\n"
        
    msg = await message.reply(text)
    asyncio.create_task(auto_delete(msg, 60))

@group_router.message(F.text.regexp(r"(?i)^перевод\s+(.+)$"))
async def cmd_transfer_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if not message.reply_to_message:
        return await message.reply("❌ Ответь (Reply) на сообщение получателя!")
        
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id:
        return await message.reply("❌ Себе нельзя!")
    if target_id == bot.id:
        return await message.reply("❌ Боту нельзя!")
        
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная сумма!")

    sender = await asyncio.to_thread(get_user, message.from_user.id)
    if sender[3] < amount:
        return await message.reply("❌ Мало средств!")

    await asyncio.to_thread(update_balance, sender[0], -amount)
    await asyncio.to_thread(get_user, target_id)
    await asyncio.to_thread(update_balance, target_id, amount)

    msg = await message.reply(f"✅ <b>Перевод выполнен!</b>\n\n👤 От: {message.from_user.first_name}\n👤 Кому: {message.reply_to_message.from_user.first_name}\n💰 Сумма: <b>{format_money(amount)}</b>")
    try:
        await msg.reply_sticker(STICKER_TRANSFER)
    except Exception:
        pass
    asyncio.create_task(auto_delete(msg, 60))

# ==============================================================================
# 18. ИГРОВОЙ ЗАЛ (ИНЛАЙН)
# ==============================================================================
@group_router.message(F.text.lower() == "игры")
async def games_hall_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
        
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice_кости"), InlineKeyboardButton(text="🎯 Дартс", callback_data="game_dice_дартс"))
    kb.row(InlineKeyboardButton(text="🏀 Баскет", callback_data="game_dice_баскет"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_dice_футбол"))
    kb.row(InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_dice_боулинг"), InlineKeyboardButton(text="🎰 Слот", callback_data="game_dice_слот"))
    kb.row(InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_mines"))
    kb.row(InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_bj"))
    
    msg = await message.reply("🎮 <b>ИГРОВОЙ ЗАЛ</b>\n\nВыбери игру:", reply_markup=kb.as_markup())
    asyncio.create_task(auto_delete(msg, 120))

@group_router.callback_query(F.data.startswith("game_dice_"))
async def game_dice_choice(callback: CallbackQuery, state: FSMContext):
    game = callback.data.split("_")[2]
    await state.update_data(dice_game=game)
    msg = await callback.message.reply(f"🎲 Вы выбрали <b>{game}</b>.\nНапиши ставку (например: <code>1000</code> или <code>10к</code>):", reply_markup=ForceReply(selective=True))
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_dice_bet)
    await callback.answer()

@group_router.callback_query(F.data == "game_roulette")
async def game_roulette_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply("🎡 Напиши ставку (например: <code>к 1000</code> или <code>13 500</code>):", reply_markup=ForceReply(selective=True))
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_roulette_bet)
    await callback.answer()

@group_router.callback_query(F.data == "game_mines")
async def game_mines_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply("💣 Напиши сумму ставки (например: <code>1000</code>):", reply_markup=ForceReply(selective=True))
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_mines_bet)
    await callback.answer()

@group_router.callback_query(F.data == "game_bj")
async def game_bj_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply("🃏 Напиши сумму ставки (например: <code>1000</code>):", reply_markup=ForceReply(selective=True))
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_bj_bet)
    await callback.answer()

# ==============================================================================
# 19. ОБРАБОТКА СТАВОК ИЗ FSM
# ==============================================================================
@group_router.message(GameStates.waiting_dice_bet)
async def process_dice_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text)
    if not amount:
        return await message.reply("❌ Неверная ставка (макс 10кк)!")
        
    data = await state.get_data()
    game = data.get("dice_game", "кости")
    await state.clear()

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)

    emoji = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳", "слот": "🎰"}.get(game, "🎲")
    msg = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5)
    val = msg.dice.value

    win = False
    if game in ("кости", "дартс") and val >= 4: win = True
    elif game == "баскет" and val >= 3: win = True
    elif game == "футбол" and val >= 4: win = True
    elif game == "боулинг" and val == 6: win = True
    elif game == "слот" and val in (1, 22, 43, 64): win = True

    if win:
        prize = amount * 2
        await asyncio.to_thread(update_balance, user[0], prize)
        await asyncio.to_thread(log_game, user[0], game, amount, prize)
        res = await message.reply(_(user, "win", val=val, prize=format_money(prize)))
    else:
        await asyncio.to_thread(log_game, user[0], game, amount, 0)
        res = await message.reply(_(user, "lose", val=val))
        
    asyncio.create_task(auto_delete(msg, 60))
    asyncio.create_task(auto_delete(res, 60))

@group_router.message(GameStates.waiting_roulette_bet)
async def process_roulette_bet(message: Message, state: FSMContext):
    parts = message.text.lower().split()
    if len(parts) != 2:
        return await message.reply("❌ Формат: <code>к 1000</code>")
        
    bet, amt = parts[0], parse_amt(parts[1])
    if not amt or not _parse_roulette(bet):
        return await message.reply("❌ Неверная ставка.")
        
    await state.clear()
    chat_id = message.chat.id
    if chat_id not in active_roulette: active_roulette[chat_id] = {"status": "waiting", "bets": []}
    
    if active_roulette[chat_id]["status"] != "waiting":
        return await message.reply("⏳ Идёт раунд, подожди.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amt:
        return await message.reply(_(user, "not_enough"))

    await asyncio.to_thread(update_balance, user[0], -amt)
    active_roulette[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "bet": bet, "amt": amt})
    
    res = await message.reply(_(user, "bet_acc", name=message.from_user.first_name, bet=bet.upper(), amt=format_money(amt)))
    asyncio.create_task(auto_delete(res, 60))

@group_router.message(GameStates.waiting_mines_bet)
async def process_mines_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text)
    if not amount:
        return await message.reply("❌ Неверная ставка.")
        
    await state.clear()
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)

    game_key = f"{message.chat.id}_{user[0]}"
    active_mines[game_key] = {"uid": user[0], "bet": amount, "mines": set(random.sample(range(25), 5)), "opened": []}
    
    kb = _mines_keyboard(game_key, [], 0)
    msg = await message.reply(f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}", reply_markup=kb)
    asyncio.create_task(auto_delete(msg, 60))

@group_router.message(GameStates.waiting_bj_bet)
async def process_bj_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text)
    if not amount:
        return await message.reply("❌ Неверная ставка.")
        
    await state.clear()
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)

    deck = _new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    game_key = f"{message.chat.id}_{user[0]}"
    active_bj[game_key] = {"uid": user[0], "bet": amount, "deck": deck, "p": player, "d": dealer, "chat": message.chat.id}

    text = f"🃏 <b>БЖ</b>\nТы: {_format_hand(player)} ({_hand_value(player)})\nДилер: {_format_hand(dealer, True)}"
    msg = await message.reply(text, reply_markup=_bj_keyboard(game_key))
    asyncio.create_task(auto_delete(msg, 60))

    if _hand_value(player) == 21:
        await _bj_finish(message, game_key, message.chat.id)

# ==============================================================================
# 20. ТЕКСТОВЫЕ ИГРЫ (КОСТИ И БЖ И МИНЫ)
# ==============================================================================
DICE_EMOJI = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳", "слот": "🎰"}

@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг|слот)\s+(.+)$"))
async def play_dice_group_text(message: Message):
    parts = message.text.lower().split()
    game, amount = parts[0], parse_amt(parts[1])
    
    if not amount:
        return await message.reply("❌ Неверная ставка (макс 10кк).")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)

    msg = await message.answer_dice(emoji=DICE_EMOJI[game])
    await asyncio.sleep(3.5)
    val = msg.dice.value

    win = False
    if game in ("кости", "дартс") and val >= 4: win = True
    elif game == "баскет" and val >= 3: win = True
    elif game == "футбол" and val >= 4: win = True
    elif game == "боулинг" and val == 6: win = True
    elif game == "слот" and val in (1, 22, 43, 64): win = True

    if win:
        prize = amount * 2
        await asyncio.to_thread(update_balance, user[0], prize)
        await asyncio.to_thread(log_game, user[0], game, amount, prize)
        res = await message.reply(_(user, "win", val=val, prize=format_money(prize)))
    else:
        await asyncio.to_thread(log_game, user[0], game, amount, 0)
        res = await message.reply(_(user, "lose", val=val))
        
    asyncio.create_task(auto_delete(msg, 60))
    asyncio.create_task(auto_delete(res, 60))

@group_router.message(F.text.regexp(r"(?i)^мины\s+(.+)$"))
async def play_mines_text(message: Message):
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная ставка.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)
    game_key = f"{message.chat.id}_{user[0]}"
    active_mines[game_key] = {"uid": user[0], "bet": amount, "mines": set(random.sample(range(25), 5)), "opened": []}
    
    msg = await message.reply(f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}", reply_markup=_mines_keyboard(game_key, [], 0))
    asyncio.create_task(auto_delete(msg, 60))

@group_router.message(F.text.regexp(r"(?i)^бж\s+(.+)$"))
async def play_bj_text(message: Message):
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная ставка.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
        
    await asyncio.to_thread(update_balance, user[0], -amount)

    deck = _new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    game_key = f"{message.chat.id}_{user[0]}"
    active_bj[game_key] = {"uid": user[0], "bet": amount, "deck": deck, "p": player, "d": dealer, "chat": message.chat.id}

    text = f"🃏 <b>БЖ</b>\nТы: {_format_hand(player)} ({_hand_value(player)})\nДилер: {_format_hand(dealer, True)}"
    msg = await message.reply(text, reply_markup=_bj_keyboard(game_key))
    asyncio.create_task(auto_delete(msg, 60))
    if _hand_value(player) == 21:
        await _bj_finish(msg, game_key, message.chat.id)

# ==============================================================================
# 21. РУЛЕТКА
# ==============================================================================
active_roulette: dict = {}
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def _parse_roulette(raw: str):
    raw = raw.lower()
    if raw in ("к", "красное"): return ("color", "к")
    if raw in ("ч", "черное"): return ("color", "ч")
    if raw in ("з", "зеро"): return ("color", "з")
    if raw == "чет": return ("parity", "чет")
    if raw == "нечет": return ("parity", "нечет")
    if "-" in raw:
        try:
            a, b = raw.split("-")
            a, b = int(a), int(b)
            if 0 <= a < b <= 36: return ("range", (a, b))
        except Exception: return None
    if raw.isdigit():
        n = int(raw)
        if 0 <= n <= 36: return ("number", n)
    return None

def _roulette_mult(kind: str) -> float:
    return {"number": 36, "range": 2.5, "color": 2, "parity": 2}[kind]

@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+|\d+)\s+(.+)$"))
async def bet_roulette_text(message: Message):
    parts = message.text.lower().split()
    bet_raw, amount_raw = parts[0], parts[1]
    parsed = _parse_roulette(bet_raw)
    if not parsed:
        return
        
    kind, value = parsed
    amount = parse_amt(amount_raw)
    if not amount:
        return await message.reply("❌ Неверная сумма.")
        
    chat_id = message.chat.id
    if chat_id not in active_roulette:
        active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting":
        return await message.reply("⏳ Идёт раунд, подожди.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))

    await asyncio.to_thread(update_balance, user[0], -amount)
    active_roulette[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "kind": kind, "value": value, "raw": bet_raw, "amount": amount})
    
    res = await message.reply(_(user, "bet_acc", name=message.from_user.first_name, bet=bet_raw.upper(), amt=format_money(amount)))
    asyncio.create_task(auto_delete(res, 60))

@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    state = active_roulette.get(chat_id)
    if not state or not state["bets"]:
        return
        
    state["status"] = "playing"
    try:
        msg = await message.answer_animation(animation=FSInputFile("assets/roulette.gif"), caption="🎡 <i>Рулетка крутится...</i>")
    except Exception:
        msg = await message.answer("🎡 <i>Рулетка крутится...</i>")
        
    await asyncio.sleep(3)

    result = random.randint(0, 36)
    if result == 0: color = "з"
    elif result in RED_NUMS: color = "к"
    else: color = "ч"
    color_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[color]

    lines = [f"🎯 Выпало: <b>{result} {color_name}</b>\n"]
    winners = []
    
    for b in state["bets"]:
        win = False
        k, v = b["kind"], b["value"]
        if k == "color" and v == color: win = True
        elif k == "parity":
            if v == "чет" and result != 0 and result % 2 == 0: win = True
            if v == "нечет" and result % 2 != 0: win = True
        elif k == "range" and v[0] <= result <= v[1]: win = True
        elif k == "number" and v == result: win = True

        if win:
            prize = int(b["amount"] * _roulette_mult(k))
            await asyncio.to_thread(update_balance, b["uid"], prize)
            await asyncio.to_thread(log_game, b["uid"], "рулетка", b["amount"], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")

    lines.append("\n".join(winners) if winners else "😢 Победителей нет.")
    text = "\n".join(lines)
    
    try: await msg.edit_caption(caption=text)
    except Exception:
        try: await msg.edit_text(text)
        except Exception: pass

    active_roulette[chat_id] = {"status": "waiting", "bets": []}
    asyncio.create_task(auto_delete(msg, 60))

# ==============================================================================
# 22. МИНЫ
# ==============================================================================
active_mines: dict = {}

def _mines_keyboard(game_key: str, opened: list, cash: Optional[int] = None, reveal_all=None):
    kb = InlineKeyboardBuilder()
    for i in range(25):
        if reveal_all is not None:
            text = "💥" if i in reveal_all else "💎"
            cb = "m_ign"
        elif i in opened:
            text = "💎"
            cb = "m_ign"
        else:
            text = "⬜"
            cb = f"m_{game_key}_{i}"
        kb.button(text=text, callback_data=cb)
    kb.adjust(5, 5, 5, 5, 5)
    if cash is not None:
        kb.row(InlineKeyboardButton(text=f"💰 Забрать {format_money(cash)}", callback_data=f"m_cash_{game_key}"))
    return kb.as_markup()

@group_router.callback_query(F.data.startswith("m_"))
async def mines_callback(callback: CallbackQuery):
    data = callback.data
    if data == "m_ign":
        return await callback.answer("Недоступно.")

    if data.startswith("m_cash_"):
        game_key = data[len("m_cash_"):]
        game = active_mines.get(game_key)
        if not game:
            return await callback.answer("Игра окончена.", show_alert=True)
        if callback.from_user.id != game["uid"]:
            return await callback.answer("Не твоя игра!", show_alert=True)
            
        win = int(game["bet"] * (1 + len(game["opened"]) * 0.2)) if game["opened"] else 0
        if win:
            await asyncio.to_thread(update_balance, game["uid"], win)
            await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], win)
            
        try: await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
        except Exception: pass
        
        del active_mines[game_key]
        try: await callback.message.answer_sticker(STICKER_CHECK)
        except Exception: pass
        return await callback.answer("Зачислено!")

    parts = data.split("_")
    if len(parts) < 4:
        return await callback.answer()
        
    game_key = f"{parts[1]}_{parts[2]}"
    cell = int(parts[3])
    game = active_mines.get(game_key)
    
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)
    if cell in game["opened"]:
        return await callback.answer("Уже открыта.")

    if cell in game["mines"]:
        kb = _mines_keyboard(game_key, [], None, reveal_all=game["mines"])
        try: await callback.message.edit_text(f"💥 <b>БУМ!</b> Проигрыш {format_money(game['bet'])}.", reply_markup=kb)
        except Exception: pass
        
        await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], 0)
        del active_mines[game_key]
        
        try: await callback.message.answer_sticker(STICKER_CROSS)
        except Exception: pass
        return await callback.answer("Мина!")

    game["opened"].append(cell)
    potential = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    kb = _mines_keyboard(game_key, game["opened"], potential)
    
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception: pass
    await callback.answer(f"Безопасно! Потенциал: {format_money(potential)}")

# ==============================================================================
# 23. БЛЭКДЖЕК
# ==============================================================================
BJ_SUITS = ["♠", "♥", "♦", "♣"]
BJ_RANKS = [("2",2),("3",3),("4",4),("5",5),("6",6),("7",7),("8",8),("9",9),("10",10),("J",10),("Q",10),("K",10),("A",11)]
active_bj: dict = {}

def _new_deck():
    deck = [(r, v, s) for (r, v) in BJ_RANKS for s in BJ_SUITS]
    random.shuffle(deck)
    return deck

def _hand_value(hand):
    total = sum(v for _, v, _ in hand)
    aces = sum(1 for r, _, _ in hand if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def _format_hand(hand, hide=False):
    if hide: return f"{hand[0][0]}{hand[0][2]}  🂠"
    return "  ".join(f"{r}{s}" for r, _, s in hand)

def _bj_keyboard(game_key: str):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{game_key}"))
    kb.row(InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj_stop_{game_key}"))
    return kb.as_markup()

@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(callback: CallbackQuery):
    game_key = callback.data[len("bj_hit_"):]
    game = active_bj.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)

    game["p"].append(game["deck"].pop())
    val = _hand_value(game["p"])
    
    if val > 21:
        await callback.answer("Перебор!")
        return await _bj_finish(callback.message, game_key, game["chat"], bust=True)

    text = f"🃏 <b>БЖ</b>\nТы: {_format_hand(game['p'])} ({val})\nДилер: {_format_hand(game['d'], True)}"
    try: await callback.message.edit_text(text, reply_markup=_bj_keyboard(game_key))
    except Exception: pass
    await callback.answer()

@group_router.callback_query(F.data.startswith("bj_stop_"))
async def bj_stop(callback: CallbackQuery):
    game_key = callback.data[len("bj_stop_"):]
    game = active_bj.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)
        
    await callback.answer()
    await _bj_finish(callback.message, game_key, game["chat"])

async def _bj_finish(message: Message, game_key: str, chat_id: int, bust: bool = False):
    game = active_bj.pop(game_key, None)
    if not game:
        return
        
    player_val = _hand_value(game["p"])
    dealer = game["d"]
    while _hand_value(dealer) < 17:
        dealer.append(game["deck"].pop())
    dealer_val = _hand_value(dealer)

    if bust or player_val > 21:
        result, prize = "💥 Перебор! Ты проиграл.", 0
    elif dealer_val > 21 or player_val > dealer_val:
        prize = game["bet"] * 2
        result = f"🎉 Ты победил! Выигрыш: {format_money(prize)}"
    elif player_val == dealer_val:
        prize = game["bet"]
        result = f"🤝 Ничья. Возврат: {format_money(prize)}"
    else:
        result, prize = "😢 Дилер победил.", 0

    if prize:
        await asyncio.to_thread(update_balance, game["uid"], prize)
    await asyncio.to_thread(log_game, game["uid"], "блэкджек", game["bet"], prize)

    text = f"🃏 <b>БЛЭКДЖЕК — ИТОГ</b>\n\n👤 <b>Ты:</b> {_format_hand(game['p'])} ({player_val})\n🤖 <b>Дилер:</b> {_format_hand(dealer)} ({dealer_val})\n\n{result}"
    
    try: await message.edit_text(text)
    except Exception:
        try: await message.edit_reply_markup(reply_markup=None)
        except Exception: pass

    try:
        if prize: await message.answer_sticker(STICKER_CHECK)
        else: await message.answer_sticker(STICKER_CROSS)
    except Exception: pass

# ==============================================================================
# 24. НЕЙРО-АДМИН
# ==============================================================================
def _parse_amount(raw: str) -> Optional[int]:
    raw = raw.lower().strip().replace("к", "000").replace("кк", "000000")
    try: return int(raw)
    except Exception: return None

def _find_user_id(token: str) -> Optional[int]:
    token = token.replace("@", "")
    if token.isdigit():
        res = db_execute("SELECT user_id FROM users WHERE user_id = ?", (int(token),), True)
        return res[0] if res else None
    res = db_execute("SELECT user_id FROM users WHERE username = ?", (token,), True)
    return res[0] if res else None

@admin_router.message(F.text.startswith("@"))
async def neuro_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    args = message.text.split()
    if len(args) < 2:
        return
    cmd = args[0].lower()

    if cmd == "@бан":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'banned' WHERE user_id = ?", (uid,))
            return await message.reply(f"🚫 Игрок {args[1]} забанен.")
            
    elif cmd == "@анбан":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'user' WHERE user_id = ?", (uid,))
            return await message.reply(f"✅ Игрок {args[1]} разбанен.")
            
    elif cmd == "@вип":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'vip' WHERE user_id = ?", (uid,))
            try: await message.reply_sticker(random.choice(VIP_STICKERS))
            except Exception: pass
            return await message.reply(f"👑 {args[1]} теперь VIP.")
            
    elif cmd == "@выдать" and len(args) >= 3:
        uid = _find_user_id(args[1])
        amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, amount)
            return await message.reply(f"✅ Выдано {format_money(amount)} → {args[1]}.")
            
    elif cmd == "@забрать" and len(args) >= 3:
        uid = _find_user_id(args[1])
        amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, -amount)
            return await message.reply(f"✅ Забрано {format_money(amount)} у {args[1]}.")
            
    elif cmd == "@дроп" and len(args) >= 2:
        amount = _parse_amount(args[1])
        if amount:
            kb = InlineKeyboardBuilder()
            kb.button(text="💰 СХВАТИТЬ", callback_data=f"drop_{amount}")
            msg = await bot.send_message(CHAT_ID, f"🚨 <b>ДРОП!</b> Кто первый нажмёт — заберёт {format_money(amount)}!", reply_markup=kb.as_markup())
            asyncio.create_task(auto_delete(msg, 60))
            await message.reply("✅ Дроп запущен.")

@group_router.callback_query(F.data.startswith("drop_"))
async def claim_drop(callback: CallbackQuery):
    try:
        amount = int(callback.data.split("_")[1])
    except Exception:
        return await callback.answer()
        
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await asyncio.to_thread(update_balance, user[0], amount)
    
    try: await callback.message.answer_sticker(STICKER_MONEY)
    except Exception: pass
    try: await callback.message.edit_text(f"💰 Мешок забрал <b>{callback.from_user.first_name}</b>! Он получил {format_money(amount)}!")
    except Exception: pass
    
    await callback.answer("Ты забрал куш!", show_alert=True)

@admin_router.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply_ticket(message: Message):
    reply_text = message.reply_to_message.text or ""
    if not reply_text.startswith("🎫 ТИКЕТ"):
        return
        
    try:
        lines = reply_text.split("\n")
        user_info = lines[1].replace("От: ", "").strip()
        target_id = None
        
        if user_info.startswith("@"):
            username = user_info.lstrip("@")
            found = await asyncio.to_thread(db_execute, "SELECT user_id FROM users WHERE username = ?", (username,), True)
            if found: target_id = found[0]
        elif user_info.isdigit():
            target_id = int(user_info)
            
        if target_id:
            try: await bot.send_sticker(target_id, STICKER_TICKET_REPLY)
            except Exception: pass
            await bot.send_message(target_id, f"✉️ <b>Ответ от Администрации:</b>\n\n{message.text}")
            await message.reply("✅ Ответ успешно доставлен пользователю!")
    except Exception as e:
        logger.error(f"Ошибка при ответе на тикет: {e}")
        await message.reply("❌ Не удалось отправить ответ.")

# ==============================================================================
# 25. АВТО-ИВЕНТЫ (Лотерея, Пинг)
# ==============================================================================
async def auto_lottery_start():
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🎟 Купить билет (10к)", callback_data="buy_ticket"))
    msg = await bot.send_message(CHAT_ID, "🎟 <b>РОЗЫГРЫШ ЛОТЕРЕИ!</b>", reply_markup=kb.as_markup())
    try: await bot.send_sticker(CHAT_ID, STICKER_GIFT)
    except Exception: pass

@group_router.callback_query(F.data == "buy_ticket")
async def buy_ticket(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    if user[3] < 10000:
        return await callback.answer("Мало средств!", show_alert=True)
    await asyncio.to_thread(update_balance, user[0], -10000)
    db_execute("INSERT INTO lottery (user_id) VALUES (?)", (user[0],))
    await callback.answer("Билет куплен!", show_alert=True)

async def auto_lottery_end():
    tickets = db_execute("SELECT user_id FROM lottery", (), False, True)
    if not tickets:
        return await bot.send_message(CHAT_ID, "Лотерея не состоялась (нет билетов).")
        
    winner = random.choice(tickets)[0]
    db_execute("DELETE FROM lottery")
    await asyncio.to_thread(update_balance, winner, 500_000)
    
    try: await bot.send_sticker(CHAT_ID, STICKER_CROWN)
    except Exception: pass
    await bot.send_message(CHAT_ID, f"🏆 Победитель лотереи: <a href='tg://user?id={winner}'>Игрок</a>!\nВыигрыш: 500 000 Tokens!")

async def auto_ping_dead():
    three_days_ago = (datetime.datetime.now() - datetime.timedelta(days=3)).isoformat()
    users = db_execute("SELECT user_id FROM users WHERE last_seen < ? AND role != 'banned'", (three_days_ago,), False, True)
    
    for u in (users or []):
        try:
            await bot.send_sticker(u[0], STICKER_GIFT)
            await bot.send_message(u[0], "Скучаем! Лови 5 000 Tokens 💰")
            update_balance(u[0], 5000)
        except Exception:
            pass

# ==============================================================================
# 26. ЗАПУСК
# ==============================================================================
async def health(_):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web-сервер на :{PORT}")

async def main():
    await asyncio.to_thread(init_db)
    
    scheduler.add_job(auto_lottery_start, "cron", hour=20, minute=0)
    scheduler.add_job(auto_lottery_end, "cron", hour=21, minute=0)
    scheduler.add_job(auto_ping_dead, "cron", hour=12, minute=0)
    scheduler.start()

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")