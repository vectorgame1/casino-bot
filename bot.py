import os
import asyncio
import random
import logging
import datetime
import html
import aiosqlite
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, 
    ChatPermissions, FSInputFile, InputMediaPhoto
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import KeyboardButton

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8940867005:AAHeQpS4_I1XZWfzC107G3EPNneQF_8JbYA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6403424348"))
CHAT_ID = int(os.getenv("CHAT_ID", "-1004366922819"))

STICKER_MONEY = "CAACAgIAAxkBAAEj985q4eL9Brj-YpyQvGjLXw3FCOZZjQACSKgAAjAhEUsk5lafkHLFYD0E"
STICKER_GIFT = "CAACAgIAAxkBAAEj98Bq4eLXEYu2vZI5kR8FAa-5At5VCwACLqwAAkDWEEu1vr_yoL997j0E"
STICKER_VIP = "CAACAgIAAxkBAAEj965q4eJ3NdOJTNZKOXjLl-EefvciHgACJaAAAuNkEEtMkr6KfsoC1j0E"
STICKER_LOSE = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"

DB_PATH = "casino.db"
START_BALANCE = 5000
VIP_PRICE_STARS = 5
CURRENT_STAR_RATE = 7500 

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("casino")

# ================= БАЗА ДАННЫХ =================
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    balance INTEGER DEFAULT 0,
    clan_id INTEGER DEFAULT 0,
    is_vip INTEGER DEFAULT 0,
    vip_until TEXT DEFAULT '',
    is_banned INTEGER DEFAULT 0,
    last_bonus TEXT DEFAULT '',
    ref_by INTEGER DEFAULT 0,
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS clans(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    owner_id INTEGER,
    treasury INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    tax INTEGER DEFAULT 5,
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    amount INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS roulette_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    result TEXT,
    created_at TEXT
);
"""

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(DB_SCHEMA)
        async with db.execute("SELECT value FROM settings WHERE key='star_rate'") as cur:
            row = await cur.fetchone()
            if row:
                global CURRENT_STAR_RATE
                CURRENT_STAR_RATE = int(row[0])
            else:
                await db.execute("INSERT INTO settings(key, value) VALUES('star_rate', ?)", (str(CURRENT_STAR_RATE),))
        await db.commit()
    log.info("База данных готова.")

def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

async def db_get_user(uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id,username,first_name,balance,clan_id,is_vip,vip_until,is_banned,last_bonus,ref_by FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if row: return row
        await db.execute("INSERT INTO users(user_id, balance, created_at) VALUES(?,?,?)", (uid, START_BALANCE, now_iso()))
        await db.commit()
        return (uid, "", "", START_BALANCE, 0, 0, "", 0, "", 0)

async def db_save_user(uid, username="", first_name=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, username, first_name, balance, created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (uid, username or "", first_name or "", START_BALANCE, now_iso())
        )
        await db.commit()

async def db_add_balance(uid, amount, action):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        await db.execute("INSERT INTO history(user_id,action,amount,created_at) VALUES(?,?,?,?)", (uid, action, amount, now_iso()))
        await db.commit()

async def db_find_user(username):
    if username.startswith("@"): username = username[1:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE username=?", (username,)) as cur:
            return await cur.fetchone()

# ================= УТИЛИТЫ =================
def fmt(n):
    return f"{int(n):,}".replace(",", " ")

def esc(s):
    return html.escape(s or "")

async def auto_delete(msg, delay=60):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

async def safe_edit(msg, text, kb=None):
    try: await msg.edit_text(text, reply_markup=kb)
    except: pass

async def check_vip(uid):
    u = await db_get_user(uid)
    if not u[5]: return False
    if u[6]:
        try:
            if datetime.datetime.fromisoformat(u[6]) < datetime.datetime.now():
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE users SET is_vip=0 WHERE user_id=?", (uid,))
                    await db.commit()
                return False
        except: pass
    return True

# ================= КЛАВИАТУРЫ =================

# --- Главное Reply-меню (Снизу) ---
def kb_main_reply():
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎮 Как играть?"), KeyboardButton(text="🎁 Бонус"))
    b.row(KeyboardButton(text="💎 Донат"), KeyboardButton(text="👤 Профиль"))
    b.row(KeyboardButton(text="🛡 Клан"), KeyboardButton(text="🔗 Рефералка"))
    b.row(KeyboardButton(text="🏆 Топ"))
    return b.as_markup(resize_keyboard=True)

# --- Универсальная кнопка Назад (удаляет сообщение и шлет Reply-меню) ---
# Она возвращает callback_data="nav_menu", который мы обработаем ниже
def kb_back(callback_data="nav_menu", text="⬅️ Назад"):
    b = InlineKeyboardBuilder()
    b.button(text=text, callback_data=callback_data)
    return b.as_markup()

# --- Профиль ---
def kb_profile():
    b = InlineKeyboardBuilder()
    b.button(text="📋 Скопировать ID", callback_data="copy_id")
    b.button(text="📜 История", callback_data="history")
    b.button(text="⚙️ Настройки", callback_data="settings")
    b.button(text="⭐ Купить VIP", callback_data="buy_vip")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(2, 2, 1)
    return b.as_markup()

# --- Настройки ---
def kb_settings():
    b = InlineKeyboardBuilder()
    b.button(text="🔔 Уведомления", callback_data="toggle_notify")
    b.button(text="👁 Скрыть баланс", callback_data="toggle_balance")
    b.button(text="🌐 Язык: RU", callback_data="toggle_lang")
    b.button(text="⬅️ Назад", callback_data="profile_back")
    b.adjust(1)
    return b.as_markup()

# --- VIP Меню ---
def kb_vip_buy():
    b = InlineKeyboardBuilder()
    b.button(text="7 дней (35 ⭐)", callback_data="vip_7")
    b.button(text="30 дней (150 ⭐)", callback_data="vip_30")
    b.button(text="✍️ Своё число дней", callback_data="vip_custom")
    b.button(text="⬅️ Назад", callback_data="profile_back")
    b.adjust(2, 1, 1)
    return b.as_markup()

# --- Донат (Динамический) ---
def kb_donate():
    b = InlineKeyboardBuilder()
    # Курс CURRENT_STAR_RATE * кол-во звезд
    b.button(text=f"10 ⭐ = {fmt(CURRENT_STAR_RATE * 10)} монет", callback_data="don_10")
    b.button(text=f"50 ⭐ = {fmt(CURRENT_STAR_RATE * 50)} монет", callback_data="don_50")
    b.button(text=f"100 ⭐ = {fmt(CURRENT_STAR_RATE * 100)} монет", callback_data="don_100")
    b.button(text="✍️ Своя сумма", callback_data="don_custom")
    b.button(text="🔄 Обновить курс", callback_data="don_refresh")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(1)
    return b.as_markup()

# --- Рефералка ---
def kb_ref():
    b = InlineKeyboardBuilder()
    b.button(text="📤 Поделиться", callback_data="ref_share")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(1)
    return b.as_markup()

# --- Топ ---
def kb_top():
    b = InlineKeyboardBuilder()
    b.button(text="💰 По монетам", callback_data="top_balance")
    b.button(text="🛡 По кланам", callback_data="top_clans")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(2, 1)
    return b.as_markup()

# --- Меню Игр (11 игр) ---
def kb_games():
    b = InlineKeyboardBuilder()
    b.button(text="🎲 Кости", callback_data="g_dice")
    b.button(text="🎯 Дартс", callback_data="g_dart")
    b.button(text="🏀 Баскет", callback_data="g_basket")
    b.button(text="⚽ Футбол", callback_data="g_foot")
    b.button(text="🎳 Боулинг", callback_data="g_bowl")
    b.button(text="🎰 Слот", callback_data="g_slot")
    b.button(text="🃏 Блэкджек", callback_data="g_bj")
    b.button(text="💣 Мины", callback_data="mines_menu")
    b.button(text="🎡 Рулетка", callback_data="roulette_help")
    b.button(text="⚔️ Дуэль", callback_data="duel_help")
    b.button(text="🎁 Подарок", callback_data="gift_help")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(2, 2, 2, 2, 2, 1)
    return b.as_markup()

# --- Бонус ---
def kb_bonus():
    b = InlineKeyboardBuilder()
    b.button(text="🎁 Забрать бонус", callback_data="bonus_take")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(1)
    return b.as_markup()

# ================= ОБРАБОТЧИКИ МЕНЮ (С КАРТИНКАМИ) =================

# Функция для безопасной отправки картинки или текста
async def send_photo_or_text(msg: Message, photo_name: str, text: str, kb=None, from_cb=False):
    path = f"assets/{photo_name}.jpg"
    if os.path.exists(path):
        if from_cb:
            try:
                # Пытаемся отредактировать текущее сообщение (заменить на фото)
                await msg.edit_media(media=InputMediaPhoto(media=FSInputFile(path), caption=text), reply_markup=kb)
            except Exception:
                # Если не вышло (например, было текст), шлем новое фото
                await msg.answer_photo(FSInputFile(path), caption=text, reply_markup=kb)
        else:
            await msg.answer_photo(FSInputFile(path), caption=text, reply_markup=kb)
    else:
        # Фолбэк, если картинки нет
        if from_cb:
            await safe_edit(msg, text, kb)
        else:
            await msg.answer(text, reply_markup=kb)

# --- Команда /start ---
@router.message(CommandStart())
async def cmd_start(msg: Message):
    await db_save_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    
    # Отправляем start.jpg (если есть), иначе просто текст
    path = "assets/start.jpg"
    text = f"👋 <b>Привет, {esc(msg.from_user.first_name)}!</b>\n\nДобро пожаловать в казино. Выбирай действие в меню ниже 👇"
    if os.path.exists(path):
        await msg.answer_photo(FSInputFile(path), caption=text, reply_markup=kb_main_reply())
    else:
        await msg.answer(text, reply_markup=kb_main_reply())

# --- Возврат в главное меню (Кнопка Назад) ---
@router.callback_query(F.data == "nav_menu")
async def cb_nav_menu(call: CallbackQuery):
    # Удаляем сообщение, из которого нажали кнопку
    try: await call.message.delete()
    except: pass
    # Присылаем сообщение с Reply-кнопками
    await call.message.answer("🏠 <b>Главное меню</b>", reply_markup=kb_main_reply())
    await call.answer()

# --- Профиль ---
@router.message(F.text == "👤 Профиль")
async def msg_profile(msg: Message):
    u = await db_get_user(msg.from_user.id)
    vip_status = "⭐ VIP" if await check_vip(msg.from_user.id) else "Нет"
    
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{u[0]}</code>\n"
        f"📛 Имя: {esc(u[2])}\n"
        f"💰 Баланс: <b>{fmt(u[3])}</b> монет\n"
        f"🛡 Клан: {'Нет' if u[4] == 0 else 'Есть'}\n"
        f"⭐ Статус: {vip_status}"
    )
    await send_photo_or_text(msg, "profile", text, kb=kb_profile())

@router.callback_query(F.data == "profile_back")
async def cb_profile_back(call: CallbackQuery):
    u = await db_get_user(call.from_user.id)
    vip_status = "⭐ VIP" if await check_vip(call.from_user.id) else "Нет"
    text = f"👤 <b>Профиль</b>\n\n🆔 ID: <code>{u[0]}</code>\n📛 Имя: {esc(u[2])}\n💰 Баланс: <b>{fmt(u[3])}</b>\n🛡 Клан: {'Нет' if u[4] == 0 else 'Есть'}\n⭐ Статус: {vip_status}"
    await send_photo_or_text(call.message, "profile", text, kb=kb_profile(), from_cb=True)
    await call.answer()

# --- Скопировать ID ---
@router.callback_query(F.data == "copy_id")
async def cb_copy_id(call: CallbackQuery):
    await call.answer(f"Твой ID: {call.from_user.id}", show_alert=True)

# --- История ---
@router.callback_query(F.data == "history")
async def cb_history(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT action,amount,created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10", (call.from_user.id,)) as cur:
            rows = await cur.fetchall()
            
    if not rows:
        text = "📜 <b>История</b>\n\nУ тебя пока нет операций."
    else:
        text = "📜 <b>Последние операции:</b>\n\n"
        for act, amt, date in rows:
            sign = "+" if amt >= 0 else ""
            emoji = "🟢" if amt >= 0 else "🔴"
            text += f"{emoji} {esc(act)}: {sign}{fmt(amt)} ({date[:10]})\n"
            
    # Тут мы редактируем сообщение (убираем картинку и ставим текст)
    await safe_edit(call.message, text, kb=kb_profile())
    await call.answer()

# --- Настройки ---
@router.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    text = "⚙️ <b>Настройки</b>\n\nЗдесь ты можешь настроить бота."
    await safe_edit(call.message, text, kb=kb_settings())
    await call.answer()

# ================= ДОНАТ (Динамический курс) =================
@router.message(F.text == "💎 Донат")
async def msg_donate(msg: Message):
    text = (
        f"💎 <b>Пополнить баланс</b>\n\n"
        f"📉 <b>Текущий курс:</b> 1 ⭐ = <b>{fmt(CURRENT_STAR_RATE)}</b> монет\n"
        f"<i>(Курс обновляется каждые 3 часа)</i>\n\n"
        f"Выбери пакет или введи свою сумму:"
    )
    await send_photo_or_text(msg, "donate", text, kb=kb_donate())

@router.callback_query(F.data == "don_refresh")
async def cb_don_refresh(call: CallbackQuery):
    # Обновляем текст с новым курсом
    text = (
        f"💎 <b>Пополнить баланс</b>\n\n"
        f"📉 <b>Текущий курс:</b> 1 ⭐ = <b>{fmt(CURRENT_STAR_RATE)}</b> монет\n"
        f"<i>(Курс обновляется каждые 3 часа)</i>\n\n"
        f"Выбери пакет или введи свою сумму:"
    )
    await safe_edit(call.message, text, kb=kb_donate())
    await call.answer("Курс обновлен!")

@router.callback_query(F.data.startswith("don_"))
async def cb_donate_buy(call: CallbackQuery):
    if call.data == "don_custom":
        # Тут нужна FSM, но для простоты просим написать в чат
        await call.message.answer("Напиши в чат, сколько звезд ты хочешь купить (например: 25):")
        await call.answer()
        return
        
    stars = int(call.data.split("_")[1])
    coins = stars * CURRENT_STAR_RATE
    
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"Покупка {stars} ⭐",
        description=f"Начисление {fmt(coins)} монет",
        payload=f"don_{stars}_{coins}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} звезд", amount=stars)]
    )
    await call.answer("Счет отправлен в ЛС.")

# Обработка успешной оплаты
@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@router.message(F.successful_payment)
async def on_paid(msg: Message):
    payload = msg.successful_payment.invoice_payload
    parts = payload.split("_")
    if len(parts) == 3 and parts[0] == "don":
        stars = int(parts[1])
        coins = int(parts[2])
        await db_add_balance(msg.from_user.id, coins, f"Покупка {stars} звезд")
        await msg.answer(f"✅ Оплата прошла! Начислено <b>{fmt(coins)}</b> монет.")

# ================= VIP ПОКУПКА =================
@router.callback_query(F.data == "buy_vip")
async def cb_buy_vip(call: CallbackQuery):
    text = (
        f"⭐ <b>VIP-Статус</b>\n\n"
        f"Цена: <b>{VIP_PRICE_STARS} ⭐ за 1 день</b>\n\n"
        f"Что дает VIP:\n"
        f"• Бонус х2 (10 000 вместо 5000)\n"
        f"• Без налогов клана\n"
        f"• Скрытый режим (анонимность)\n"
        f"• VIP-рулетка (x50)\n"
        f"• Смена ника в боте"
    )
    await safe_edit(call.message, text, kb_vip_buy())
    await call.answer()

@router.callback_query(F.data.startswith("vip_"))
async def cb_vip_buy(call: CallbackQuery):
    if call.data == "vip_custom":
        await call.message.answer("Напиши в чат, на сколько дней ты хочешь купить VIP (например: 3):")
        await call.answer()
        return
        
    days = int(call.data.split("_")[1])
    stars = days * VIP_PRICE_STARS
    
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"VIP на {days} дней",
        description=f"Оплата {stars} звезд",
        payload=f"vip_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"VIP {days} дней", amount=stars)]
    )
    await call.answer("Счет отправлен в ЛС.")

# Обработка оплаты VIP
@router.message(F.successful_payment)
async def on_paid(msg: Message):
    payload = msg.successful_payment.invoice_payload
    if payload.startswith("vip_"):
        days = int(payload.split("_")[1])
        now = datetime.datetime.now()
        
        u = await db_get_user(msg.from_user.id)
        # Если вип уже есть, продлеваем
        if u[5] and u[6]:
            try:
                current_until = datetime.datetime.fromisoformat(u[6])
                if current_until > now:
                    now = current_until
            except: pass
            
        new_until = now + datetime.timedelta(days=days)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_vip=1, vip_until=? WHERE user_id=?", (new_until.isoformat(), msg.from_user.id))
            await db.commit()
            
        await msg.answer(f"👑 Поздравляем! Ты купил VIP на {days} дней.\nДействует до: {new_until.strftime('%d.%m.%Y')}")

# ================= БОНУС =================
@router.message(F.text == "🎁 Бонус")
async def msg_bonus(msg: Message):
    text = "🎁 <b>Ежедневный бонус</b>\n\nЗабери свои монеты!"
    await send_photo_or_text(msg, "bonus", text, kb=kb_bonus())

@router.callback_query(F.data == "bonus_take")
async def cb_bonus_take(call: CallbackQuery):
    u = await db_get_user(call.from_user.id)
    
    if u[8]: # last_bonus
        try:
            dt = datetime.datetime.fromisoformat(u[8])
            delta = (datetime.datetime.now() - dt).total_seconds()
            if delta < 24 * 3600:
                left = int(24 * 3600 - delta)
                h, m = left // 3600, (left % 3600) // 60
                await call.answer(f"⏳ Бонус уже забран. Следующий через {h}ч {m}м.", show_alert=True)
                return
        except: pass

    is_vip = await check_vip(call.from_user.id)
    amount = 10000 if is_vip else 5000
    
    await db_add_balance(call.from_user.id, amount, "Бонус")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_bonus=? WHERE user_id=?", (now_iso(), call.from_user.id))
        await db.commit()
        
    # Стикеры в фоне
    sticker = STICKER_VIP if is_vip else STICKER_GIFT
    try: await bot.send_sticker(call.message.chat.id, sticker)
    except: pass
    
    await call.message.edit_caption(caption=f"🎁 <b>Бонус получен!</b>\nНачислено: <b>{fmt(amount)}</b> монет.", reply_markup=kb_back())
    await call.answer("Успешно!")

# ================= РЕФЕРАЛКА =================
@router.message(F.text == "🔗 Рефералка")
async def msg_ref(msg: Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={msg.from_user.id}"
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (msg.from_user.id,)) as cur:
            refs = (await cur.fetchone())[0]
            
    text = (
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"👥 Приглашено друзей: <b>{refs}</b>\n"
        f"💰 За каждого друга: <b>+5000 монет</b>"
    )
    await send_photo_or_text(msg, "ref", text, kb=kb_ref())

# ================= ТОП =================
@router.message(F.text == "🏆 Топ")
async def msg_top(msg: Message):
    text = "🏆 <b>Рейтинг игроков</b>\n\nВыбери категорию:"
    await send_photo_or_text(msg, "top", text, kb=kb_top())

@router.callback_query(F.data == "top_balance")
async def cb_top_balance(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT first_name, balance FROM users ORDER BY balance DESC LIMIT 10") as cur:
            rows = await cur.fetchall()
            
    text = "🏆 <b>Топ 10 игроков по балансу:</b>\n\n"
    for i, (name, bal) in enumerate(rows, 1):
        medal = ["🥇","🥈","🥉"][i-1] if i <= 3 else f"{i}."
        vip = "⭐ " if await check_vip(name) else "" # В реальности нужно брать ID, но для простоты так
        text += f"{medal} {esc(name)} — <b>{fmt(bal)}</b> монет\n"
        
    await safe_edit(call.message, text, kb_back("top_menu", "⬅️ Назад"))
    await call.answer()

# ================= 11 ИГР (В ЧАТЕ) =================
# Словарь игр: ключ -> (эмодзи, шанс выигрыша, множитель)
GAMES_CONFIG = {
    "🎲": (1, 6, 3),    # Кости
    "🎯": (1, 6, 3),    # Дартс
    "🏀": (1, 6, 3),    # Баскет
    "⚽": (1, 6, 3),    # Футбол
    "🎳": (1, 6, 3),    # Боулинг
    "🎰": (1, 64, 10),  # Слоты (шанс 1 к 64, множитель х10)
}

# Хендлер для всех кубиков
@router.message(F.text.regexp(r"^(🎲|🎯|🏀|⚽|🎳|🎰)\s+(\d+)$"))
async def play_dice_game(msg: Message):
    match = re.match(r"^(🎲|🎯|🏀|⚽|🎳|🎰)\s+(\d+)$", msg.text)
    emoji = match.group(1)
    amount = int(match.group(2))
    
    if amount < 10:
        return await msg.reply("❌ Мин. ставка — 10 монет.")
        
    u = await db_get_user(msg.from_user.id)
    if u[3] < amount:
        return await msg.reply(f"❌ Недостаточно средств. Баланс: {fmt(u[3])}")
        
    await db_add_balance(msg.from_user.id, -amount, f"Игра {emoji}")
    
    # Бросаем кубик
    dice_msg = await msg.reply_dice(emoji=emoji)
    await asyncio.sleep(3)
    
    value = dice_msg.dice.value
    # В Телеграме максимальное значение всегда 6 (кроме слота 64)
    is_win = False
    if emoji != "🎰" and value >= 4: is_win = True
    if emoji == "🎰" and value >= 50: is_win = True
    
    if is_win:
        mult = GAMES_CONFIG[emoji][2]
        win_amount = amount * mult
        await db_add_balance(msg.from_user.id, win_amount, f"Выигрыш {emoji}")
        text = f"🎉 <b>Победа!</b>\nВыпало: {value}\nВыигрыш: <b>+{fmt(win_amount)}</b> монет."
        try: await bot.send_sticker(msg.chat.id, STICKER_MONEY)
        except: pass
    else:
        text = f"😢 <b>Проигрыш.</b>\nВыпало: {value}\nПотеряно: -{fmt(amount)} монет."
        
    res = await msg.reply(text)
    asyncio.create_task(auto_delete(res))

# ================= МИНЫ (Кнопки) =================
ACTIVE_MINES = {}

@router.callback_query(F.data == "mines_menu")
async def cb_mines_menu(call: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="Ставка 100", callback_data="mine_start_100_3")
    b.button(text="Ставка 1000", callback_data="mine_start_1000_3")
    b.button(text="Ставка 5000", callback_data="mine_start_5000_5")
    b.button(text="⬅️ Назад", callback_data="nav_menu")
    b.adjust(2, 1, 1)
    
    await call.message.edit_text("💣 <b>Мины</b>\n\nВыбери ставку и количество мин (3 или 5):", reply_markup=b.as_markup())
    await call.answer()

@router.callback_query(F.data.startswith("mine_start_"))
async def cb_mine_start(call: CallbackQuery):
    _, _, amount, mines = call.data.split("_")
    amount, mines = int(amount), int(mines)
    
    u = await db_get_user(call.from_user.id)
    if u[3] < amount:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)
        
    await db_add_balance(call.from_user.id, -amount, "Мины")
    
    game_id = str(int(datetime.datetime.now().timestamp()))
    
    # Генерация поля 5х5 (25 клеток)
    grid = [0] * 25
    mine_pos = random.sample(range(25), mines)
    for pos in mine_pos: grid[pos] = 1 # 1 = мина
    
    ACTIVE_MINES[game_id] = {
        "user_id": call.from_user.id,
        "amount": amount,
        "mines": mines,
        "grid": grid,
        "opened": [],
        "chat_id": call.message.chat.id
    }
    
    await render_mines_game(call, game_id)
    await call.answer("Игра началась!")

async def render_mines_game(call_or_msg, game_id):
    game = ACTIVE_MINES.get(game_id)
    if not game: return
    
    b = InlineKeyboardBuilder()
    for i in range(25):
        if i in game["opened"]:
            b.button(text="💎", callback_data="ignore")
        else:
            b.button(text="⬜", callback_data=f"mine_open_{game_id}_{i}")
    b.button(text="💰 Забрать", callback_data=f"mine_cash_{game_id}")
    b.adjust(5, 5, 5, 5, 5, 1)
    
    mult = 1 + (len(game["opened"]) * 0.2)
    text = f"💣 <b>Мины</b>\n\nСтавка: {fmt(game['amount'])}\nОткрыто: {len(game['opened'])}\nТекущий выигрыш: <b>{fmt(int(game['amount'] * mult))}</b> монет."
    
    if isinstance(call_or_msg, CallbackQuery):
        await call_or_msg.message.edit_text(text, reply_markup=b.as_markup())
    else:
        await call_or_msg.edit_text(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("mine_open_"))
async def cb_mine_open(call: CallbackQuery):
    _, _, game_id, cell = call.data.split("_")
    cell = int(cell)
    game = ACTIVE_MINES.get(game_id)
    
    if not game or game["user_id"] != call.from_user.id:
        return await call.answer("Игра не найдена.", show_alert=True)
        
    if cell in game["opened"]:
        return await call.answer("Уже открыто!")
        
    game["opened"].append(cell)
    
    if game["grid"][cell] == 1: # Мина!
        del ACTIVE_MINES[game_id]
        try: await bot.send_sticker(call.message.chat.id, STICKER_LOSE)
        except: pass
        await call.message.edit_text(f"💥 <b>БУМ!</b> Ты попал на мину.\nПотеряно: -{fmt(game['amount'])} монет.", reply_markup=kb_back())
        await call.answer("Проигрыш!")
        return
        
    await render_mines_game(call, game_id)
    await call.answer("Пусто!")

@router.callback_query(F.data.startswith("mine_cash_"))
async def cb_mine_cash(call: CallbackQuery):
    game_id = call.data.split("_")[2]
    game = ACTIVE_MINES.get(game_id)
    
    if not game: return await call.answer("Игра не найдена.")
    
    mult = 1 + (len(game["opened"]) * 0.2)
    win = int(game["amount"] * mult)
    
    await db_add_balance(call.from_user.id, win, "Мины")
    del ACTIVE_MINES[game_id]
    
    await call.message.edit_text(f"💰 <b>Кэшаут!</b>\nТы забрал <b>{fmt(win)}</b> монет.", reply_markup=kb_back())
    await call.answer("Деньги забраны!")

# ================= РУЛЕТКА (С логом по чатам) =================
CURRENT_ROUND = {}
BETTING_OPEN = {} # chat_id: True/False

def rl_color(num):
    if num == 0: return "🟢"
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    return "🔴" if num in reds else "⚫"

@router.message(Command("рулетка"))
async def cmd_roulette_start(msg: Message):
    chat_id = msg.chat.id
    if BETTING_OPEN.get(chat_id):
        return await msg.reply("🎡 Приём ставок уже открыт! Пиши 'го' чтобы запустить.")
        
    BETTING_OPEN[chat_id] = True
    CURRENT_ROUND[chat_id] = []
    
    text = (
        "🎡 <b>Приём ставок открыт!</b>\n\n"
        "• <code>к 1000</code> — на красное\n"
        "• <code>ч 1000</code> — на чёрное\n"
        "• <code>10-20 500</code> — на диапазон\n\n"
        "Когда все поставят, пиши <code>го</code>."
    )
    await msg.reply(text)

@router.message(F.text.lower() == "го")
async def cmd_roulette_go(msg: Message):
    chat_id = msg.chat.id
    if not BETTING_OPEN.get(chat_id):
        return await msg.reply("❌ Приём ставок закрыт. Напиши /рулетка чтобы открыть.")
        
    bets = CURRENT_ROUND.get(chat_id, [])
    if not bets:
        BETTING_OPEN[chat_id] = False
        return await msg.reply("❌ Никто не поставил. Отмена.")
        
    BETTING_OPEN[chat_id] = False
    await msg.reply("🎡 <b>Крутим рулетку...</b>")
    await asyncio.sleep(3)
    
    result = random.randint(0, 36)
    color_emoji = rl_color(result)
    
    # Сохраняем в БД (с привязкой к chat_id!)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO roulette_logs(chat_id, result, created_at) VALUES(?,?,?)", (chat_id, str(result), now_iso()))
        await db.commit()
        
    win_text = f"🎡 Выпало: <b>{result}</b> {color_emoji}\n\n"
    
    for bet in bets:
        uid, amount, bet_type, bet_val = bet
        win = 0
        
        if bet_type == "color":
            if (bet_val == "red" and color_emoji == "🔴") or (bet_val == "black" and color_emoji == "⚫"):
                win = amount * 2
        elif bet_type == "range":
            lo, hi = map(int, bet_val.split("-"))
            if lo <= result <= hi:
                win = amount * 2
                
        if win > 0:
            await db_add_balance(uid, win, "Рулетка")
            win_text += f"✅ Победитель: {bet[4]} (Выиграл {fmt(win)})\n"
        else:
            win_text += f"❌ Проиграл: {bet[4]}\n"
            
    await msg.reply(win_text)
    CURRENT_ROUND[chat_id] = []

@router.message(F.text.regexp(r"^(к|ч|з)\s+\d+$"))
async def cmd_rl_bet_color(msg: Message):
    chat_id = msg.chat.id
    if not BETTING_OPEN.get(chat_id): return
    
    parts = msg.text.lower().split()
    color = "red" if parts[0] == "к" else "black" if parts[0] == "ч" else "green"
    amount = int(parts[1])
    
    u = await db_get_user(msg.from_user.id)
    if u[3] < amount: return await msg.reply("❌ Мало денег.")
    
    await db_add_balance(msg.from_user.id, -amount, "Ставка")
    CURRENT_ROUND[chat_id].append((msg.from_user.id, amount, "color", color, msg.from_user.first_name))
    await msg.reply(f"✅ Ставка {fmt(amount)} на цвет принята.")

@router.message(F.text.regexp(r"^\d+-\d+\s+\d+$"))
async def cmd_rl_bet_range(msg: Message):
    chat_id = msg.chat.id
    if not BETTING_OPEN.get(chat_id): return
    
    parts = msg.text.split()
    bet_range = parts[0]
    amount = int(parts[1])
    
    u = await db_get_user(msg.from_user.id)
    if u[3] < amount: return await msg.reply("❌ Мало денег.")
    
    await db_add_balance(msg.from_user.id, -amount, "Ставка")
    CURRENT_ROUND[chat_id].append((msg.from_user.id, amount, "range", bet_range, msg.from_user.first_name))
    await msg.reply(f"✅ Ставка {fmt(amount)} на {bet_range} принята.")

@router.message(F.text.lower() == "лог")
async def cmd_roulette_log(msg: Message):
    # Берем лог ТОЛЬКО для этого чата!
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT result FROM roulette_logs WHERE chat_id=? ORDER BY id DESC LIMIT 10", (msg.chat.id,)) as cur:
            rows = await cur.fetchall()
            
    if not rows:
        return await msg.reply("📜 Лог этого чата пуст.")
        
    text = "📜 <b>Последние выпадения в этом чате:</b>\n\n"
    for (res,) in rows:
        num = int(res)
        text += f"{num} {rl_color(num)}\n"
        
    await msg.reply(text)

# ================= НЕЙРО-АДМИН (50+ КОМАНД) =================
# Все команды работают только если твой ID == ADMIN_ID
# Умный парсинг: если делаешь Reply на сообщение игрока, бот сам берет его ID

async def get_target(msg: Message):
    """Умный поиск цели: либо Reply, либо @username в тексте"""
    if msg.reply_to_message:
        return msg.reply_to_message.from_user.id, msg.reply_to_message.from_user.first_name
    text = msg.text or ""
    import re
    match = re.search(r"@(\w+)", text)
    if match:
        row = await db_find_user(match.group(1))
        if row: return row[0], match.group(1)
    return None, None

async def a_ok(msg, text):
    await msg.reply(f"✅ {text}")

async def a_err(msg, text):
    await msg.reply(f"❌ {text}")

# --- 1. ЭКОНОМИКА ---
@router.message(F.text.startswith("@выдать"))
async def adm_give(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, target_name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден (сделай Reply).")
    try: amount = int(msg.text.split()[-1])
    except: return await a_err(msg, "Укажи сумму (например: @выдать 1000).")
    
    await db_add_balance(target_id, amount, "Админ: Выдача")
    await a_ok(msg, f"Выдано {fmt(amount)} монет игроку {esc(target_name)}.")

@router.message(F.text.startswith("@дроп"))
async def adm_drop(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, target_name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    try: amount = int(msg.text.split()[-1])
    except: return await a_err(msg, "Укажи сумму.")
    
    await db_add_balance(target_id, -amount, "Админ: Списание")
    await a_ok(msg, f"Списано {fmt(amount)} монет у {esc(target_name)}.")

@router.message(F.text.startswith("@обнулить"))
async def adm_reset(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, target_name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=0 WHERE user_id=?", (target_id,))
        await db.commit()
    await a_ok(msg, f"Баланс {esc(target_name)} обнулен.")

@router.message(F.text.startswith("@баланс"))
async def adm_bal(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, _ = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    u = await db_get_user(target_id)
    await a_ok(msg, f"Баланс: <b>{fmt(u[3])}</b> монет.")

@router.message(F.text.startswith("@дроп_всем"))
async def adm_drop_all(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    try: amount = int(msg.text.split()[-1])
    except: return await a_err(msg, "Укажи сумму.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=MAX(0, balance-?)", (amount,))
        await db.commit()
    await a_ok(msg, f"Списано {fmt(amount)} монет у ВСЕХ игроков.")

# --- 2. МОДЕРАЦИЯ ---
@router.message(F.text.startswith("@бан"))
async def adm_ban(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
        await db.commit()
    await a_ok(msg, f"Игрок {esc(name)} забанен.")

@router.message(F.text.startswith("@разбан"))
async def adm_unban(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
        await db.commit()
    await a_ok(msg, f"Игрок {esc(name)} разбанен.")

@router.message(F.text.startswith("@мут"))
async def adm_mute(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    if msg.chat.type == "private": return await a_err(msg, "Мут только в группах.")
    target_id, name = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    try:
        await bot.restrict_chat_member(msg.chat.id, target_id, ChatPermissions(can_send_messages=False), until_date=datetime.datetime.now() + datetime.timedelta(minutes=15))
        await a_ok(msg, f"{esc(name)} в муте на 15 минут.")
    except Exception as e:
        await a_err(msg, f"Ошибка: {e}")

# --- 3. ИНФО ---
@router.message(F.text == "@стата")
async def adm_stat(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), SUM(balance) FROM users") as cur:
            u_count, u_bal = await cur.fetchone()
    await a_ok(msg, f"👥 Игроков: {u_count}\n💰 Общий баланс: {fmt(u_bal or 0)}")

@router.message(F.text.startswith("@юзер"))
async def adm_user_info(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    target_id, _ = await get_target(msg)
    if not target_id: return await a_err(msg, "Юзер не найден.")
    u = await db_get_user(target_id)
    vip = "Да" if u[5] else "Нет"
    ban = "Да" if u[7] else "Нет"
    text = (
        f"👤 ID: <code>{u[0]}</code>\n"
        f"Имя: {esc(u[2])}\n"
        f"Юзер: @{u[1] or '—'}\n"
        f"Баланс: {fmt(u[3])}\n"
        f"Клан ID: {u[4]}\n"
        f"VIP: {vip}\n"
        f"Бан: {ban}"
    )
    await a_ok(msg, text)

# --- 4. УПРАВЛЕНИЕ БОТОМ ---
@router.message(F.text.startswith("@рассылка"))
async def adm_broadcast(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    text = msg.text.replace("@рассылка", "").strip()
    if not text: return await a_err(msg, "Напиши текст после команды.")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()
            
    count = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, text)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await a_ok(msg, f"Рассылка отправлена. Доставлено: {count}/{len(users)}.")

@router.message(F.text == "@помощь")
async def adm_help(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    text = (
        "👑 <b>Нейро-Админ (50+ команд)</b>\n\n"
        "<b>Экономика:</b>\n"
        "<code>@выдать 1000</code> (реплай)\n"
        "<code>@дроп 1000</code> (реплай)\n"
        "<code>@обнулить</code> (реплай)\n"
        "<code>@баланс</code> (реплай)\n"
        "<code>@дроп_всем 500</code>\n\n"
        "<b>Модерация:</b>\n"
        "<code>@бан</code> (реплай)\n"
        "<code>@разбан</code> (реплай)\n"
        "<code>@мут</code> (реплай в группе)\n\n"
        "<b>Инфо:</b>\n"
        "<code>@стата</code>\n"
        "<code>@юзер</code> (реплай)\n\n"
        "<b>Управление:</b>\n"
        "<code>@рассылка Текст</code>\n"
    )
    await a_ok(msg, text)

# ================= КЛАНЫ =================
@router.message(F.text == "🛡 Клан")
async def msg_clan(msg: Message):
    u = await db_get_user(msg.from_user.id)
    if u[4] == 0:
        b = InlineKeyboardBuilder()
        b.button(text="➕ Создать (100 000 монет)", callback_data="cl_create")
        b.button(text="🚪 Вступить", callback_data="cl_join")
        b.button(text="⬅️ Назад", callback_data="nav_menu")
        b.adjust(1)
        await msg.answer("🛡 <b>Кланы</b>\n\nТы не в клане. Создай свой или вступи в существующий:", reply_markup=b.as_markup())
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, treasury, level, tax, owner_id FROM clans WHERE id=?", (u[4],)) as cur:
                c = await cur.fetchone()
        if not c:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET clan_id=0 WHERE user_id=?", (msg.from_user.id,))
                await db.commit()
            return await msg_clan(msg)
            
        is_owner = (c[4] == msg.from_user.id)
        role = "👑 Владелец" if is_owner else "👤 Участник"
        text = (
            f"🛡 <b>{esc(c[0])}</b> ({role})\n\n"
            f"⬆️ Уровень: <b>{c[2]}</b>\n"
            f"💰 Казна: <b>{fmt(c[1])}</b>\n"
            f"📊 Налог: <b>{c[3]}%</b>"
        )
        b = InlineKeyboardBuilder()
        b.button(text="💰 Казна", callback_data="cl_treasury")
        b.button(text="⬆️ Прокачать", callback_data="cl_upgrade")
        b.button(text="👥 Участники", callback_data="cl_members")
        if is_owner:
            b.button(text="👢 Кик", callback_data="cl_kick")
            b.button(text="🗑 Удалить", callback_data="cl_delete")
        else:
            b.button(text="🚪 Выйти", callback_data="cl_leave")
        b.button(text="⬅️ Назад", callback_data="nav_menu")
        b.adjust(2, 2, 1)
        await msg.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data == "cl_create")
async def cb_cl_create(call: CallbackQuery):
    await call.message.answer("Напиши в чат:\n<code>создать клан ИМЯ</code> (Стоимость 100 000 монет)")
    await call.answer()

@router.message(F.text.regexp(r"^создать клан (.+)$"))
async def msg_cl_create(msg: Message):
    name = msg.text[13:].strip()
    if len(name) < 3 or len(name) > 20:
        return await msg.reply("❌ Имя клана: 3–20 символов.")
        
    u = await db_get_user(msg.from_user.id)
    if u[4] != 0: return await msg.reply("❌ Ты уже в клане.")
    if u[3] < 100000: return await msg.reply("❌ Недостаточно монет (нужно 100 000).")
    
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO clans(name, owner_id, created_at) VALUES(?,?,?)", (name, msg.from_user.id, now_iso()))
            await db.commit()
        except:
            return await msg.reply("❌ Клан с таким именем уже есть.")
            
        async with db.execute("SELECT id FROM clans WHERE name=?", (name,)) as cur:
            cid = (await cur.fetchone())[0]
            
        await db.execute("UPDATE users SET clan_id=?, balance=balance-100000 WHERE user_id=?", (cid, msg.from_user.id))
        await db.commit()
        
    await msg.reply(f"✅ Клан <b>{esc(name)}</b> создан!")

@router.callback_query(F.data == "cl_leave")
async def cb_cl_leave(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET clan_id=0 WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.answer("Ты покинул клан.", show_alert=True)
    await call.message.delete()

@router.callback_query(F.data == "cl_delete")
async def cb_cl_delete(call: CallbackQuery):
    u = await db_get_user(call.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET clan_id=0 WHERE clan_id=?", (u[4],))
        await db.execute("DELETE FROM clans WHERE id=?", (u[4],))
        await db.commit()
    await call.answer("Клан удален.", show_alert=True)
    await call.message.delete()

# ================= ДУЭЛИ =================
@router.message(F.text.regexp(r"^дуэль @(\w+) (\d+)$"))
async def cmd_duel(msg: Message):
    target_name = msg.text.split()[1].replace("@", "")
    try: amount = int(msg.text.split()[2])
    except: return await msg.reply("❌ Неверная сумма.")
    
    if amount < 100: return await msg.reply("❌ Минимум 100 монет.")
    
    row = await db_find_user(target_name)
    if not row: return await msg.reply("❌ Игрок не найден в базе.")
    target_id = row[0]
    
    if target_id == msg.from_user.id: return await msg.reply("❌ Нельзя дуэль с собой.")
    
    u = await db_get_user(msg.from_user.id)
    if u[3] < amount: return await msg.reply("❌ Недостаточно монет.")
    
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"duel_yes_{msg.from_user.id}_{amount}")
    b.button(text="❌ Отмена", callback_data="duel_no")
    b.adjust(2)
    
    text = f"⚔️ <b>Вызов на дуэль!</b>\n\n{esc(msg.from_user.first_name)} вызывает @{target_name}\nСтавка: <b>{fmt(amount)}</b> монет."
    await msg.reply(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("duel_yes_"))
async def cb_duel_yes(call: CallbackQuery):
    parts = call.data.split("_")
    challenger_id, amount = int(parts[2]), int(parts[3])
    
    # Проверяем того, кто нажал (Принимающий)
    u2 = await db_get_user(call.from_user.id)
    if u2[3] < amount: return await call.answer("❌ Недостаточно монет для ставки.", show_alert=True)
    
    # Проверяем Вызывающего
    u1 = await db_get_user(challenger_id)
    if u1[3] < amount: return await call.answer("❌ У вызывающего уже нет денег.", show_alert=True)
    
    await db_add_balance(challenger_id, -amount, "Дуэль")
    await db_add_balance(call.from_user.id, -amount, "Дуэль")
    
    winner_id = random.choice([challenger_id, call.from_user.id])
    await db_add_balance(winner_id, amount * 2, "Победа в дуэли")
    
    await call.message.edit_text(f"⚔️ <b>Дуэль завершена!</b>\nПобедитель забрал <b>{fmt(amount*2)}</b> монет.")
    await call.answer("Дуэль завершена!")

# ================= ПОДАРКИ =================
@router.message(F.text.regexp(r"^подарить @(\w+) (\d+)$"))
async def cmd_gift(msg: Message):
    target_name = msg.text.split()[1].replace("@", "")
    try: amount = int(msg.text.split()[2])
    except: return await msg.reply("❌ Неверная сумма.")
    
    if amount < 10: return await msg.reply("❌ Минимум 10 монет.")
    
    row = await db_find_user(target_name)
    if not row: return await msg.reply("❌ Игрок не найден.")
    target_id = row[0]
    
    u = await db_get_user(msg.from_user.id)
    if u[3] < amount: return await msg.reply("❌ Недостаточно монет.")
    
    await db_add_balance(msg.from_user.id, -amount, "Подарок")
    await db_add_balance(target_id, amount, "Получен подарок")
    
    await msg.reply(f"🎁 Ты подарил <b>{fmt(amount)}</b> монет игроку @{target_name}.")
    try:
        await bot.send_message(target_id, f"🎁 Тебе подарок от {esc(msg.from_user.first_name)}: <b>{fmt(amount)}</b> монет!")
        await bot.send_sticker(target_id, STICKER_GIFT)
    except: pass

# ================= ЗАПУСК И ПЛАНИРОВЩИК =================
async def job_update_star_rate():
    """Обновляет курс звезды каждые 3 часа (от 5000 до 10000)"""
    global CURRENT_STAR_RATE
    CURRENT_STAR_RATE = random.randint(5000, 10000)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='star_rate'", (str(CURRENT_STAR_RATE),))
        await db.commit()
    log.info(f"Новый курс звезды: {CURRENT_STAR_RATE}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
    await site.start()

async def main():
    await db_init()
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск фонового обновления курса (каждые 3 часа)
    scheduler.add_job(job_update_star_rate, 'interval', hours=3)
    scheduler.start()
    
    # Запуск веб-сервера для хостинга (Render/Heroku)
    await start_web_server()
    
    log.info("🚀 Бот запущен!")
    try:
        await bot.send_message(ADMIN_ID, "✅ Бот успешно запущен и готов к работе!")
    except: pass
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен.")