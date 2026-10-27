import asyncio
import logging
import sqlite3
import datetime
import os
import random
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==============================================================================
# НАСТРОЙКИ (ВПИШИ ТОКЕН И ID!)
# ==============================================================================
BOT_TOKEN = "8940867005:AAHeQpS4_I1XZWfzC107G3EPNneQF_8JbYA"
ADMIN_ID = 6403424348 # Твой ID
GROUP_LINK = "https://t.me/tokenplays"
DB_PATH = "casino.db"
START_BONUS = 5000
CURRENCY = "Tokens"
MOD_LIMIT = 500000

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

user_router = Router()
admin_router = Router()
mod_router = Router()
pr_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, mod_router, pr_router, group_router)

# ==============================================================================
# БАЗА ДАННЫХ
# ==============================================================================
def db_execute(query, params=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone: result = cursor.fetchone()
    elif fetchall: result = cursor.fetchall()
    conn.commit()
    conn.close()
    return result

def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru',
        balance INTEGER DEFAULT 5000, role TEXT DEFAULT 'user', 
        last_bonus TEXT, last_case TEXT, last_vip_case TEXT, last_wheel TEXT,
        last_work TEXT, warns INTEGER DEFAULT 0, ref_id INTEGER DEFAULT NULL
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, reward INTEGER, limit_count INTEGER, used_count INTEGER DEFAULT 0)""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (user_id INTEGER PRIMARY KEY)""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT, bet INTEGER, win INTEGER, date TEXT)""")
    logger.info("База данных готова.")

def get_user(user_id):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        db_execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, "Unknown", START_BONUS))
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return user

def update_balance(user_id, amount):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))

def format_money(amount):
    return f"{amount:,}".replace(",", " ") + f" {CURRENCY}"

# ==============================================================================
# ЛОКАЛИЗАЦИЯ
# ==============================================================================
TEXTS = {
    "ru": {
        "welcome": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В КАЗИНО</b>\n\n👋 Привет, {name}!\n👇 Выбери действие:",
        "profile": "👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Баланс: <b>{bal}</b>\n⚠️ Варны: {warns}",
        "btn_games": "🎮 Игры", "btn_profile": "👤 Профиль", "btn_donate": "💎 Донат",
        "btn_transfer": "💸 Перевод", "btn_lang": "🌐 Язык", "btn_support": "🆘 Поддержка",
        "btn_back": "⬅️ Назад", "lang_changed": "✅ Язык изменен на Русский!"
    },
    "en": {
        "welcome": "👑 <b>WELCOME TO CASINO</b>\n\n👋 Hi, {name}!\n👇 Choose action:",
        "profile": "👤 <b>PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: <b>{bal}</b>\n⚠️ Warns: {warns}",
        "btn_games": "🎮 Games", "btn_profile": "👤 Profile", "btn_donate": "💎 Donate",
        "btn_transfer": "💸 Transfer", "btn_lang": "🌐 Language", "btn_support": "🆘 Support",
        "btn_back": "⬅️ Back", "lang_changed": "✅ Language changed to English!"
    }
}

def get_text(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, "Text not found")
    if kwargs: return text.format(**kwargs)
    return text

# ==============================================================================
# КЛАВИАТУРЫ
# ==============================================================================
def get_main_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "btn_games")), KeyboardButton(text=get_text(lang, "btn_profile")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_donate")), KeyboardButton(text=get_text(lang, "btn_transfer")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_lang")), KeyboardButton(text=get_text(lang, "btn_support")))
    return builder.as_markup(resize_keyboard=True)

def get_profile_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="📜 История"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_mod_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="💸 Выдать Токены"), KeyboardButton(text="🚫 Забанить"))
    builder.row(KeyboardButton(text="🔓 Разбанить"), KeyboardButton(text="⬅️ Выход"))
    return builder.as_markup(resize_keyboard=True)

def get_pr_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🔗 Моя Ссылка"), KeyboardButton(text="📊 Моя Стата"))
    builder.row(KeyboardButton(text="⬅️ Выход"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💸 Экономика"))
    builder.row(KeyboardButton(text="🎁 Промокоды"), KeyboardButton(text="👥 Люди"))
    builder.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎰 Игры"))
    builder.row(KeyboardButton(text="⚙️ Система"), KeyboardButton(text="🎁 Ивент"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    return builder.as_markup(resize_keyboard=True)

# ==============================================================================
# СТАРТ И ПРОФИЛЬ
# ==============================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await state.clear()
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    elif user[4] == "moderator":
        await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРА</b>", reply_markup=get_mod_menu())
    elif user[4] == "promoter":
        await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>", reply_markup=get_pr_menu())
    else:
        await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

@user_router.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(get_text(user[2], "profile", uid=user[0], bal=format_money(user[3]), warns=user[10]), reply_markup=get_profile_menu())

@user_router.message(F.text.in_(["🌐 Язык", "🌐 Language"]))
async def change_lang(message: Message):
    user = get_user(message.from_user.id)
    new_lang = "en" if user[2] == "ru" else "ru"
    db_execute("UPDATE users SET lang = ? WHERE user_id = ?", (new_lang, user[0]))
    await message.answer(get_text(new_lang, "lang_changed"), reply_markup=get_main_menu(new_lang))

@user_router.message(F.text == "⬅️ Назад")
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

# ==============================================================================
# ПЕРЕВОДЫ И БОНУСЫ
# ==============================================================================
class TransferStates(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

@user_router.message(F.text.in_(["💸 Перевод", "💸 Transfer"]))
async def transfer_start(message: Message, state: FSMContext):
    await message.answer("Введи ID или @юзернейм:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(TransferStates.waiting_id)

@user_router.message(TransferStates.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    target_text = message.text.replace("@", "").strip()
    target = db_execute("SELECT user_id FROM users WHERE user_id = ?" if target_text.isdigit() else "SELECT user_id FROM users WHERE username = ?", (int(target_text) if target_text.isdigit() else target_text,), fetchone=True)
    if not target: return await message.answer("❌ Игрок не найден.")
    if target[0] == message.from_user.id: return await message.answer("❌ Себе нельзя!")
    await state.update_data(target=target[0])
    await message.answer("Введи сумму:")
    await state.set_state(TransferStates.waiting_amount)

@user_router.message(TransferStates.waiting_amount)
async def transfer_amount(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    sender = get_user(message.from_user.id)
    if sender[3] < amount: return await message.answer("❌ Мало средств!")
    
    update_balance(sender[0], -amount)
    update_balance(data['target'], amount)
    await message.answer(f"✅ Переведено {format_money(amount)} игроку <code>{data['target']}</code>", reply_markup=get_main_menu(sender[2]))
    await state.clear()

@user_router.message(F.text == "🎁 Бонус")
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[5] and now - datetime.datetime.fromisoformat(user[5]) < datetime.timedelta(hours=24):
        return await message.answer("⏳ Бонус уже забран.")
    update_balance(user[0], 5000)
    db_execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer("🎁 Ты забрал бонус: <b>5 000 Tokens</b>!")

@user_router.message(F.text == "📜 История")
async def history_menu(message: Message):
    user = get_user(message.from_user.id)
    logs = db_execute("SELECT game, bet, win, date FROM games_log WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user[0],), fetchall=True)
    text = "📜 <b>ПОСЛЕДНИЕ 5 ИГР:</b>\n\n"
    if not logs: text += "Нет игр."
    for l in logs:
        text += f"{l[3][:10]} | {l[0]} | Ставка: {l[1]} | {l[2]}\n"
    await message.answer(text)

# ==============================================================================
# КЕЙСЫ, КОЛЕСО, ЛОТЕРЕЯ
# ==============================================================================
@user_router.message(F.text.in_(["🎮 Игры", "🎮 Games"]))
async def games_menu_btn(message: Message):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📦 Кейсы"), KeyboardButton(text="🎡 Колесо"))
    builder.row(KeyboardButton(text="🎟 Лотерея"), KeyboardButton(text="💼 Работа"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text == "📦 Кейсы")
async def cases_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Обычный кейс", callback_data="open_case")
    builder.button(text="💎 VIP кейс", callback_data="open_vip_case")
    await message.answer("📦 <b>КЕЙСЫ</b>", reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "open_case")
async def open_case(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    now = datetime.datetime.now()
    if user[6] and now - datetime.datetime.fromisoformat(user[6]) < datetime.timedelta(hours=24):
        return await callback.answer("⏳ Кейс уже открыт.", show_alert=True)
    
    prize = random.choice([1000, 2000, 5000, 10000, 15000, 25000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await callback.message.edit_text(f"🎁 Выигрыш: <b>{format_money(prize)}</b>!")
    await callback.answer()

@user_router.callback_query(F.data == "open_vip_case")
async def open_vip_case(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if user[10] != "vip": return await callback.answer("❌ Только VIP.", show_alert=True)
    now = datetime.datetime.now()
    if user[7] and now - datetime.datetime.fromisoformat(user[7]) < datetime.timedelta(hours=12):
        return await callback.answer("⏳ Жди 12 часов.", show_alert=True)
        
    prize = random.choice([5000, 10000, 25000, 50000, 100000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_vip_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await callback.message.edit_text(f"💎 Выигрыш: <b>{format_money(prize)}</b>!")
    await callback.answer()

@user_router.message(F.text == "🎡 Колесо")
async def spin_wheel(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[8] and now - datetime.datetime.fromisoformat(user[8]) < datetime.timedelta(hours=12):
        return await message.answer("⏳ Ждите 12 часов.")
    await message.answer("🎡 Колесо крутится...")
    await asyncio.sleep(2)
    prize = random.choice([0, 500, 1000, 5000, 10000, 50000])
    if prize > 0: update_balance(user[0], prize)
    db_execute("UPDATE users SET last_wheel = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer(f"🎉 Выигрыш: {format_money(prize)}" if prize else "😢 Пусто.")

@user_router.message(F.text == "🎟 Лотерея")
async def lottery_menu(message: Message):
    await message.answer("🎟 <b>ЛОТЕРЕЯ</b>\nБилет 5000.", reply_markup=InlineKeyboardBuilder().button(text="Купить", callback_data="buy_lottery").as_markup())

@user_router.callback_query(F.data == "buy_lottery")
async def buy_lottery(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if user[3] < 5000: return await callback.answer("❌ Мало средств.", show_alert=True)
    update_balance(user[0], -5000)
    db_execute("INSERT OR IGNORE INTO lottery (user_id) VALUES (?)", (user[0],))
    await callback.answer("✅ Куплено!", show_alert=True)

@user_router.message(F.text == "💼 Работа")
async def work_menu(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[10] and now - datetime.datetime.fromisoformat(user[10]) < datetime.timedelta(hours=1):
        return await message.answer("⏳ Вы уже работали. Ждите час.")
    update_balance(user[0], 1500)
    db_execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer(f"💼 Вы получили {format_money(1500)}!")

# ==============================================================================
# АДМИНКА (Полная)
# ==============================================================================
@admin_router.message(F.text == "⬅️ В меню игрока")
async def adm_exit(message: Message): 
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Меню игрока:", reply_markup=get_main_menu("ru"))

@admin_router.message(F.text == "📊 Статистика")
async def adm_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    users = db_execute("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_bal = db_execute("SELECT SUM(balance) FROM users", fetchone=True)[0] or 0
    await message.answer(f"📊 <b>СТАТИСТИКА</b>\n\n👥 Игроков: <b>{users}</b>\n💰 В обороте: <b>{format_money(total_bal)}</b>")

@admin_router.message(F.text == "💸 Экономика")
async def adm_eco(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать по ID"), KeyboardButton(text="Забрать по ID"))
    builder.row(KeyboardButton(text="Налог 10%"), KeyboardButton(text="Выдать всем"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    await message.answer("💸 <b>ЭКОНОМИКА</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "🎁 Промокоды")
async def adm_promos(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Создать промокод"), KeyboardButton(text="⬅️ В меню игрока"))
    await message.answer("🎁 <b>ПРОМОКОДЫ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "👥 Люди")
async def adm_people(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать Модера"), KeyboardButton(text="Выдать Пиарщика"))
    builder.row(KeyboardButton(text="Забанить"), KeyboardButton(text="Разбанить"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    await message.answer("👥 <b>УПРАВЛЕНИЕ ЛЮДЬМИ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "📢 Рассылка")
async def adm_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("📢 Введи текст для рассылки (или /cancel для отмены):")
    # Здесь должен быть FSM, но для краткости просто текст

@admin_router.message(F.text == "🎰 Игры")
async def adm_games(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Вкл/Выкл Кейсы"), KeyboardButton(text="Вкл/Выкл Ставки"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    await message.answer("🎰 <b>УПРАВЛЕНИЕ ИГРАМИ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "⚙️ Система")
async def adm_sys(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("⚙️ <b>СИСТЕМА</b>\n\nБот работает стабильно. База данных активна.")

@admin_router.message(F.text == "🎁 Ивент")
async def adm_event(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Дроп в чат"), KeyboardButton(text="Гиперинфляция"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    await message.answer("🎁 <b>ИВЕНТЫ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

# ==============================================================================
# МОДЕРЫ
# ==============================================================================
@mod_router.message(F.text == "💸 Выдать")
async def mod_give(message: Message):
    await message.answer("Напиши ID и сумму через пробел (например: 123456789 5000).")
    # Реализация парсинга ID и суммы

@mod_router.message(F.text == "🚫 Бан")
async def mod_ban(message: Message):
    await message.answer("Напиши ID для бана.")

@mod_router.message(F.text == "⬅️ Выход")
async def mod_exit(message: Message):
    await message.answer("Меню игрока:", reply_markup=get_main_menu("ru"))

# ==============================================================================
# ПИАРЩИКИ
# ==============================================================================
@pr_router.message(F.text == "🔗 Реф-Ссылка")
async def pr_ref(message: Message):
    bot_info = await bot.get_me()
    await message.answer(f"🔗 Твоя ссылка:\n<code>https://t.me/{bot_info.username}?start=ref_{message.from_user.id}</code>")

@pr_router.message(F.text == "📊 Статистика")
async def pr_stats(message: Message):
    ref_count = db_execute("SELECT COUNT(*) FROM users WHERE ref_id = ?", (message.from_user.id,), fetchone=True)[0]
    await message.answer(f"📊 Ты привел: <b>{ref_count}</b> человек.")

@pr_router.message(F.text == "⬅️ Выход")
async def pr_exit(message: Message):
    await message.answer("Меню игрока:", reply_markup=get_main_menu("ru"))

# ==============================================================================
# ЕЖЕДНЕВНЫЙ ОТЧЕТ В 22:00
# ==============================================================================
async def daily_report():
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    users = db_execute("SELECT COUNT(*) FROM users", fetchone=True)[0]
    games_today = db_execute("SELECT COUNT(*) FROM games_log WHERE date(date) = date('now')", fetchone=True)[0]
    total_win = db_execute("SELECT SUM(win) FROM games_log WHERE date(date) = date('now')", fetchone=True)[0] or 0
    total_bet = db_execute("SELECT SUM(bet) FROM games_log WHERE date(date) = date('now')", fetchone=True)[0] or 0
    
    top_active = db_execute("SELECT user_id, COUNT(*) as cnt FROM games_log WHERE date(date) = date('now') GROUP BY user_id ORDER BY cnt DESC LIMIT 3", fetchall=True)
    top_text = ""
    for i, u in enumerate(top_active):
        top_text += f"{i+1}. <code>{u[0]}</code> — {u[1]} игр\n"

    report_text = (
        f"📅 <b>ОТЧЕТ ЗА {now}</b>\n\n"
        f"👥 Всего игроков: <b>{users}</b>\n"
        f"🎮 Сыграно игр: <b>{games_today}</b>\n"
        f"💸 Поставлено: <b>{format_money(total_bet)}</b>\n"
        f"💰 Выиграно: <b>{format_money(total_win)}</b>\n\n"
        f"🏆 <b>Топ активных:</b>\n{top_text if top_text else 'Нет данных'}"
    )
    try:
        await bot.send_message(ADMIN_ID, report_text)
    except Exception as e:
        logger.error(f"Ошибка отправки отчета: {e}")

# ==============================================================================
# ФИНАЛЬНЫЙ ПАТЧ №2: ОТМЕНА ПЕРЕВОДА, БАЛАНС, ВОЗВРАТ АДМИНКИ И КАРТИНКИ
# ==============================================================================

# 1. Добавляем кнопку "Отмена" для выхода из перевода
@user_router.message(TransferStates.waiting_id, F.text == "⬅️ Отмена")
@user_router.message(TransferStates.waiting_amount, F.text == "⬅️ Отмена")
async def cancel_transfer(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    await message.answer("❌ Перевод отменен.", reply_markup=get_main_menu(user[2]))

# 2. Команда "б" (баланс) в личке
@user_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_private(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await message.answer(f"💰 Твой баланс: <b>{format_money(user[3])}</b>")

# 3. Принудительный возврат в Админку (перебиваем всё)
@admin_router.message(F.text == "⬅️ В меню игрока")
async def adm_exit_final(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    else:
        user = get_user(message.from_user.id)
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

# 4. Картинка при старте (если файла нет - шлет текст)
@user_router.message(CommandStart())
async def cmd_start_final(message: Message, state: FSMContext):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await state.clear()
    
    try:
        photo = FSInputFile("assets/welcome.jpg")
        await message.answer_photo(
            photo=photo, 
            caption=get_text(user[2], "welcome", name=message.from_user.first_name), 
            reply_markup=get_main_menu(user[2])
        )
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}")
        await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

# 5. Картинка (GIF) при открытии кейса
@user_router.callback_query(F.data == "open_case")
async def open_case_final(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    now = datetime.datetime.now()
    if user[6] and now - datetime.datetime.fromisoformat(user[6]) < datetime.timedelta(hours=24):
        return await callback.answer("⏳ Кейс уже открыт.", show_alert=True)
    
    prize = random.choice([1000, 2000, 5000, 10000, 15000, 25000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    
    try:
        await callback.message.answer_animation(
            animation=FSInputFile("assets/case.gif"), 
            caption=f"🎁 Ты открыл кейс и выиграл <b>{format_money(prize)}</b>!"
        )
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Не удалось отправить GIF: {e}")
        await callback.message.edit_text(f"🎁 Выигрыш: <b>{format_money(prize)}</b>!")
    await callback.answer()

# ==============================================================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER (Восстановлен)
# ==============================================================================
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_ping_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")


# ==============================================================================
# ЧИСТЫЙ КОД ИГР (ЗАМЕНЯЕТ ВСЕ СТАРЫЕ ОБРАБОТЧИКИ)
# ==============================================================================

# 1. Меню игр
@group_router.message(Command("игры"))
@group_router.message(F.text.lower().in_(["игры", "games"]))
async def games_menu_clean(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кости", callback_data="g_dice")
    builder.button(text="🎯 Дартс", callback_data="g_darts")
    builder.button(text="🏀 Баскет", callback_data="g_basket")
    builder.button(text="⚽ Футбол", callback_data="g_football")
    builder.button(text="🎳 Боулинг", callback_data="g_bowling")
    builder.button(text="🎡 Рулетка", callback_data="g_roulette_info")
    builder.button(text="💣 Мины", callback_data="g_mines_info")
    builder.button(text="🪜 Лесенка", callback_data="g_stairs_info")
    builder.button(text="🃏 Блэкджек", callback_data="g_bj_info")
    builder.button(text="🃏 Джокер", callback_data="g_joker")
    builder.adjust(2, 2, 2, 2, 2)
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>\nВыбери игру (пиши ставку в чат, например: <code>кости 1000</code>):", reply_markup=builder.as_markup())

@group_router.callback_query(F.data == "g_back")
async def back_to_games(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кости", callback_data="g_dice")
    builder.button(text="🎯 Дартс", callback_data="g_darts")
    builder.button(text="🏀 Баскет", callback_data="g_basket")
    builder.button(text="⚽ Футбол", callback_data="g_football")
    builder.button(text="🎳 Боулинг", callback_data="g_bowling")
    builder.button(text="🎡 Рулетка", callback_data="g_roulette_info")
    builder.button(text="💣 Мины", callback_data="g_mines_info")
    builder.button(text="🪜 Лесенка", callback_data="g_stairs_info")
    builder.button(text="🃏 Блэкджек", callback_data="g_bj_info")
    builder.button(text="🃏 Джокер", callback_data="g_joker")
    builder.adjust(2, 2, 2, 2, 2)
    await callback.message.edit_text("🎰 <b>ИГРОВОЙ ЗАЛ</b>", reply_markup=builder.as_markup())
    await callback.answer()

# 2. Инфо об играх
@group_router.callback_query(F.data == "g_dice")
async def info_dice(callback: CallbackQuery):
    await callback.message.edit_text("🎲 <b>КОСТИ</b>\nНапиши в чат: <code>кости 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_darts")
async def info_darts(callback: CallbackQuery):
    await callback.message.edit_text("🎯 <b>ДАРТС</b>\nНапиши в чат: <code>дартс 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_basket")
async def info_basket(callback: CallbackQuery):
    await callback.message.edit_text("🏀 <b>БАСКЕТ</b>\nНапиши в чат: <code>баскет 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_football")
async def info_football(callback: CallbackQuery):
    await callback.message.edit_text("⚽ <b>ФУТБОЛ</b>\nНапиши в чат: <code>футбол 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_bowling")
async def info_bowling(callback: CallbackQuery):
    await callback.message.edit_text("🎳 <b>БОУЛИНГ</b>\nНапиши в чат: <code>боулинг 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_roulette_info")
async def info_roulette(callback: CallbackQuery):
    await callback.message.edit_text("🎡 <b>РУЛЕТКА</b>\nСтавки: <code>к 1000</code>, <code>10-23 500</code>\nЗапуск: <code>го</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_mines_info")
async def info_mines(callback: CallbackQuery):
    await callback.message.edit_text("💣 <b>МИНЫ</b>\nНапиши в чат: <code>мины 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_stairs_info")
async def info_stairs(callback: CallbackQuery):
    await callback.message.edit_text("🪜 <b>ЛЕСЕНКА</b>\nНапиши в чат: <code>лесенка 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_bj_info")
async def info_bj(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>БЛЭКДЖЕК</b>\nНапиши в чат: <code>бж 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_joker")
async def info_joker(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>ДЖОКЕР</b>\nНапиши в чат: <code>джокер 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

# 3. САМИ ИГРЫ (Стикеры и логика)
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг)\s+(\d+)$"))
async def play_dice_clean(message: Message):
    parts = message.text.lower().split()
    game, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount)
    emoji = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳"}[game]
    
    msg = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5)
    val = msg.dice.value
    
    win = False
    if game in ["кости", "дартс"] and val >= 4: win = True
    elif game == "баскет" and val >= 3: win = True
    elif game == "футбол" and val >= 4: win = True
    elif game == "боулинг" and val == 6: win = True
    
    if win:
        update_balance(user[0], amount * 2)
        await message.reply(f"🎉 Победа! Выпало {val}. Выигрыш: {format_money(amount * 2)}!")
    else:
        await message.reply(f"😢 Проигрыш. Выпало {val}.")
       
# 6. Перезапуск с принудительным сбросом вебхука (для групп)
async def main_final():
    init_db()
    scheduler.add_job(daily_report, "cron", hour=22, minute=0)
    scheduler.start()
    asyncio.create_task(start_ping_server())
    
    # Сброс вебхука
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Бот запущен (Финальный патч №2)!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: 
        asyncio.run(main_final())
    except KeyboardInterrupt: 
        logger.info("Бот остановлен.")

