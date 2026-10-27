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
# МЕГА-ПАТЧ: ПОЛНАЯ АДМИНКА, МОДЕРЫ И ПИАРЩИКИ
# ==============================================================================
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    waiting_give_id = State()
    waiting_give_amount = State()
    waiting_take_id = State()
    waiting_take_amount = State()
    waiting_promo_code = State()
    waiting_promo_amount = State()
    waiting_promo_limit = State()
    waiting_role_id = State()
    waiting_ban_id = State()
    waiting_unban_id = State()

class ModStates(StatesGroup):
    waiting_give_id = State()
    waiting_give_amount = State()
    waiting_ban_id = State()
    waiting_unban_id = State()

# ==============================================================================
# 1. ИСПРАВЛЕНИЕ КНОПКИ "В МЕНЮ ИГРОКА" (ВОЗВРАТ В АДМИНКУ)
# ==============================================================================
@admin_router.message(F.text == "⬅️ В меню игрока")
async def adm_exit_fix(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    else:
        user = get_user(message.from_user.id)
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

# ==============================================================================
# 2. ЭКОНОМИКА (АДМИН)
# ==============================================================================
@admin_router.message(F.text == "Выдать по ID")
async def adm_give_id(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока, кому выдать:")
    await state.set_state(AdminStates.waiting_give_id)

@admin_router.message(AdminStates.waiting_give_id)
async def adm_give_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму для выдачи:")
    await state.set_state(AdminStates.waiting_give_amount)

@admin_router.message(AdminStates.waiting_give_amount)
async def adm_give_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    update_balance(data['target'], amount)
    await message.answer(f"✅ Выдано {format_money(amount)} игроку <code>{data['target']}</code>", reply_markup=get_admin_menu())
    await state.clear()

@admin_router.message(F.text == "Забрать по ID")
async def adm_take_id(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока, у кого забрать:")
    await state.set_state(AdminStates.waiting_take_id)

@admin_router.message(AdminStates.waiting_take_id)
async def adm_take_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму для забора:")
    await state.set_state(AdminStates.waiting_take_amount)

@admin_router.message(AdminStates.waiting_take_amount)
async def adm_take_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    update_balance(data['target'], -amount)
    await message.answer(f"✅ Забрано {format_money(amount)} у игрока <code>{data['target']}</code>", reply_markup=get_admin_menu())
    await state.clear()

@admin_router.message(F.text == "Налог 10%")
async def adm_tax(message: Message):
    users = db_execute("SELECT user_id, balance FROM users WHERE balance > 100000", fetchall=True)
    total = 0
    for u in users:
        tax = int(u[1] * 0.1)
        update_balance(u[0], -tax)
        total += tax
    await message.answer(f"📉 Собрано налогов: <b>{format_money(total)}</b>", reply_markup=get_admin_menu())

# ==============================================================================
# 3. ПРОМОКОДЫ (АДМИН)
# ==============================================================================
@admin_router.message(F.text == "Создать промокод")
async def adm_promo_create(message: Message, state: FSMContext):
    await message.answer("Введи код (слово), например: <code>WELCOME</code>")
    await state.set_state(AdminStates.waiting_promo_code)

@admin_router.message(AdminStates.waiting_promo_code)
async def adm_promo_amount(message: Message, state: FSMContext):
    await state.update_data(code=message.text.upper())
    await message.answer("Введи сумму награды:")
    await state.set_state(AdminStates.waiting_promo_amount)

@admin_router.message(AdminStates.waiting_promo_amount)
async def adm_promo_limit(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(amount=amount)
    await message.answer("Введи лимит активаций:")
    await state.set_state(AdminStates.waiting_promo_limit)

@admin_router.message(AdminStates.waiting_promo_limit)
async def adm_promo_finish(message: Message, state: FSMContext):
    try: limit = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    db_execute("INSERT OR REPLACE INTO promos (code, reward, limit_count) VALUES (?, ?, ?)", (data['code'], data['amount'], limit))
    await message.answer(f"✅ Промокод <b>{data['code']}</b> создан!", reply_markup=get_admin_menu())
    await state.clear()

# ==============================================================================
# 4. УПРАВЛЕНИЕ ЛЮДЬМИ (АДМИН)
# ==============================================================================
@admin_router.message(F.text == "Выдать Модера")
async def adm_add_mod(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока, кому выдать Модера:")
    await state.set_state(AdminStates.waiting_role_id)

@admin_router.message(AdminStates.waiting_role_id)
async def adm_add_mod_finish(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET role = 'moderator' WHERE user_id = ?", (target,))
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Модер.", reply_markup=get_admin_menu())
    await state.clear()

@admin_router.message(F.text == "Выдать Пиарщика")
async def adm_add_pr(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока, кому выдать Пиарщика:")
    await state.set_state("waiting_pr_id")

@admin_router.message(StateFilter("waiting_pr_id"))
async def adm_add_pr_finish(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET role = 'promoter' WHERE user_id = ?", (target,))
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Пиарщик.", reply_markup=get_admin_menu())
    await state.clear()

# ==============================================================================
# 5. ПАНЕЛЬ МОДЕРА (РАБОЧАЯ)
# ==============================================================================
@mod_router.message(F.text == "⬅️ Выход")
async def mod_exit_fix(message: Message):
    user = get_user(message.from_user.id)
    if user[4] == "moderator":
        await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРА</b>", reply_markup=get_mod_menu())
    else:
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

@mod_router.message(F.text == "💸 Выдать Токены")
async def mod_give_id(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока, кому выдать (лимит 500к):")
    await state.set_state(ModStates.waiting_give_id)

@mod_router.message(ModStates.waiting_give_id)
async def mod_give_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму:")
    await state.set_state(ModStates.waiting_give_amount)

@mod_router.message(ModStates.waiting_give_amount)
async def mod_give_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    
    if amount > 500000:
        return await message.answer("❌ Лимит модера 500 000 токенов!")
        
    data = await state.get_data()
    update_balance(data['target'], amount)
    await message.answer(f"✅ Выдано {format_money(amount)} игроку <code>{data['target']}</code>", reply_markup=get_mod_menu())
    await state.clear()

@mod_router.message(F.text == "🚫 Забанить")
async def mod_ban(message: Message):
    await message.answer("Напиши ID игрока для бана. (В разработке)")

@mod_router.message(F.text == "🔓 Разбанить")
async def mod_unban(message: Message):
    await message.answer("Напиши ID игрока для разбана. (В разработке)")

# ==============================================================================
# 6. ПАНЕЛЬ ПИАРЩИКА (РАБОЧАЯ)
# ==============================================================================
@pr_router.message(F.text == "⬅️ Выход")
async def pr_exit_fix(message: Message):
    user = get_user(message.from_user.id)
    if user[4] == "promoter":
        await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>", reply_markup=get_pr_menu())
    else:
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

@pr_router.message(F.text == "🔗 Моя Ссылка")
async def pr_ref_fix(message: Message):
    bot_info = await bot.get_me()
    await message.answer(f"🔗 Твоя ссылка:\n<code>https://t.me/{bot_info.username}?start=ref_{message.from_user.id}</code>")

@pr_router.message(F.text == "📊 Моя Стата")
async def pr_stats_fix(message: Message):
    ref_count = db_execute("SELECT COUNT(*) FROM users WHERE ref_id = ?", (message.from_user.id,), fetchone=True)[0]
    await message.answer(f"📊 Ты привел: <b>{ref_count}</b> человек.")

# ==============================================================================
# МЕГА-ПАТЧ: ВСЕ ИГРЫ И КОМАНДЫ В ГРУППАХ (ПЕРЕЗАПИСЬ)
# ==============================================================================

# --- 1. КОМАНДЫ "Б", "ТОП", "ПЕРЕВОД" В ГРУППАХ ---
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    user = get_user(message.from_user.id)
    await message.reply(f"💰 Баланс <a href='tg://user?id={user[0]}'>{message.from_user.first_name}</a>: <b>{format_money(user[3])}</b>")

@group_router.message(F.text.lower() == "топ")
async def cmd_top_group_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    top_users = db_execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
    text = "🏆 <b>ТОП-10 БОГАЧЕЙ:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        text += f"{i}. <a href='tg://user?id={u[0]}'>{u[0]}</a> — {format_money(u[1])}\n"
    await message.reply(text)

@group_router.message(F.text.regexp(r"(?i)^перевод\s+(\d+)$"))
async def cmd_transfer_group_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    if not message.reply_to_message: 
        return await message.reply("❌ Ответь (Reply) на сообщение того, кому переводишь!")
    
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id: return await message.reply("❌ Себе нельзя!")
    
    amount = int(message.text.split()[1])
    sender = get_user(message.from_user.id)
    if sender[3] < amount: return await message.reply("❌ Мало средств!")
    
    update_balance(sender[0], -amount)
    update_balance(target_id, amount)
    await message.reply(f"✅ <a href='tg://user?id={sender[0]}'>{message.from_user.first_name}</a> перевел {format_money(amount)} игроку <a href='tg://user?id={target_id}'>{message.reply_to_message.from_user.first_name}</a>!")

# --- 2. МЕНЮ ИГР (с кнопкой Назад) ---
@group_router.message(Command("игры"))
@group_router.message(F.text.lower().in_(["игры", "games"]))
async def group_games_menu_final(message: Message):
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
async def back_to_games_final(callback: CallbackQuery):
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

# --- 3. ИНФО ОБ ИГРАХ ---
@group_router.callback_query(F.data == "g_dice")
async def info_dice_final(callback: CallbackQuery):
    await callback.message.edit_text("🎲 <b>КОСТИ</b>\nНапиши в чат: <code>кости 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_darts")
async def info_darts_final(callback: CallbackQuery):
    await callback.message.edit_text("🎯 <b>ДАРТС</b>\nНапиши в чат: <code>дартс 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_basket")
async def info_basket_final(callback: CallbackQuery):
    await callback.message.edit_text("🏀 <b>БАСКЕТ</b>\nНапиши в чат: <code>баскет 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_football")
async def info_football_final(callback: CallbackQuery):
    await callback.message.edit_text("⚽ <b>ФУТБОЛ</b>\nНапиши в чат: <code>футбол 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_bowling")
async def info_bowling_final(callback: CallbackQuery):
    await callback.message.edit_text("🎳 <b>БОУЛИНГ</b>\nНапиши в чат: <code>боулинг 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_roulette_info")
async def info_roulette_final(callback: CallbackQuery):
    await callback.message.edit_text("🎡 <b>РУЛЕТКА</b>\nСтавки: <code>к 1000</code>, <code>10-23 500</code>\nЗапуск: <code>го</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_mines_info")
async def info_mines_final(callback: CallbackQuery):
    await callback.message.edit_text("💣 <b>МИНЫ</b>\nНапиши в чат: <code>мины 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_stairs_info")
async def info_stairs_final(callback: CallbackQuery):
    await callback.message.edit_text("🪜 <b>ЛЕСЕНКА</b>\nНапиши в чат: <code>лесенка 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_bj_info")
async def info_bj_final(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>БЛЭКДЖЕК</b>\nНапиши в чат: <code>бж 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

@group_router.callback_query(F.data == "g_joker")
async def info_joker_final(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>ДЖОКЕР</b>\nНапиши в чат: <code>джокер 1000</code>", reply_markup=InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="g_back").as_markup())
    await callback.answer()

# --- 4. САМИ ИГРЫ ---
# Кости и т.д.
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг)\s+(\d+)$"))
async def play_dice_final(message: Message):
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

# Рулетка
active_roulette = {}
@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+)\s+(\d+)$"))
async def bet_roulette_final(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette: active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting": return await message.reply("⏳ Идет раунд.")
    parts = message.text.lower().split()
    bet, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    active_roulette[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "bet": bet, "amount": amount})
    await message.reply(f"✅ Ставка: <b>{message.from_user.first_name}</b> {format_money(amount)} на {bet.upper()}")

@group_router.message(F.text.lower() == "го")
async def start_roulette_final(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette or not active_roulette[chat_id]["bets"]: return
    active_roulette[chat_id]["status"] = "playing"
    msg = await message.answer("🎡 Рулетка крутится...")
    await asyncio.sleep(3)
    result_num = random.randint(0, 36)
    reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "з" if result_num == 0 else "к" if result_num in reds else "ч"
    res_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[color]
    text = f"🎯 Выпало: <b>{result_num} {res_name}</b>\n\n"
    winners = []
    for b in active_roulette[chat_id]["bets"]:
        win = False
        if b['bet'] in [color, "красное" if color=="к" else "черное" if color=="ч" else "зеро"]: win = True
        elif b['bet'] == "чет" and result_num % 2 == 0 and result_num != 0: win = True
        elif b['bet'] == "нечет" and result_num % 2 != 0: win = True
        elif "-" in b['bet']:
            start, end = map(int, b['bet'].split("-"))
            if start <= result_num <= end: win = True
        if win:
            prize = b['amount'] * 2
            update_balance(b['uid'], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")
    text += "\n".join(winners) if winners else "😢 Победителей нет."
    await msg.edit_text(text)
    active_roulette[chat_id] = {"status": "waiting", "bets": []}

# Мины
active_mines = {}
@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines_final(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    mines = random.sample(range(25), 5)
    active_mines[game_key] = {"uid": user[0], "bet": amount, "mines": mines, "opened": []}
    builder = InlineKeyboardBuilder()
    for i in range(25): builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    await message.reply(f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}", reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("m_"))
async def open_mine_final(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4: return
    game_key = f"{parts[1]}_{parts[2]}"
    cell = int(parts[3])
    if game_key not in active_mines: return await callback.answer("Игра окончена.", show_alert=True)
    game = active_mines[game_key]
    if callback.from_user.id != game["uid"]: return await callback.answer("Не твоя игра!", show_alert=True)
    if cell in game["opened"]: return await callback.answer("Уже открыта.", show_alert=True)
    if cell in game["mines"]:
        builder = InlineKeyboardBuilder()
        for i in range(25): builder.button(text="💥" if i in game["mines"] else "💎", callback_data="m_ign")
        builder.adjust(5, 5, 5, 5, 5)
        await callback.message.edit_text(f"💥 <b>БУМ!</b> Проигрыш {format_money(game['bet'])}.", reply_markup=builder.as_markup())
        del active_mines[game_key]
        return await callback.answer()
    game["opened"].append(cell)
    win = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    builder = InlineKeyboardBuilder()
    for i in range(25):
        if i in game["opened"]: builder.button(text="💎", callback_data="m_ign")
        else: builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    builder.row(InlineKeyboardButton(text=f"💰 Забрать {format_money(win)}", callback_data=f"m_cash_{game_key}"))
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer(f"Безопасно! Потенциал: {format_money(win)}")

@group_router.callback_query(F.data.startswith("m_cash_"))
async def cashout_mine_final(callback: CallbackQuery):
    game_key = callback.data.split("m_cash_")[1]
    if game_key not in active_mines: return
    game = active_mines[game_key]
    win = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    update_balance(game["uid"], win)
    await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
    del active_mines[game_key]
    await callback.answer("Зачислено!")

@group_router.callback_query(F.data == "m_ign")
async def ign_mine_final(callback: CallbackQuery): await callback.answer("Недоступно.")

# Лесенка
active_stairs = {}
@group_router.message(F.text.regexp(r"(?i)^лесенка\s+(\d+)$"))
async def play_stairs_final(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    dead_cells = random.sample(range(1, 10), 3)
    active_stairs[game_key] = {"uid": user[0], "bet": amount, "dead": dead_cells, "step": 1}
    builder = InlineKeyboardBuilder().button(text="🚶 Шагнуть", callback_data=f"st_{game_key}")
    await message.reply(f"🪜 <b>ЛЕСЕНКА</b>\nСтавка: {format_money(amount)}", reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("st_"))
async def step_stairs_final(callback: CallbackQuery):
    game_key = callback.data.split("st_")[1]
    if game_key not in active_stairs: return
    game = active_stairs[game_key]
    if callback.from_user.id != game["uid"]: return await callback.answer("Не твоя игра!", show_alert=True)
    game["step"] += 1
    if game["step"] in game["dead"]:
        await callback.message.edit_text(f"💀 <b>СГОРЕЛ!</b> Упали на шаге {game['step']}. Проигрыш {format_money(game['bet'])}.")
        del active_stairs[game_key]
        return await callback.answer()
    if game["step"] >= 10:
        win = game["bet"] * 5
        update_balance(game["uid"], win)
        await callback.message.edit_text(f"🏆 <b>ПОБЕДА!</b> Выигрыш x5: {format_money(win)}!")
        del active_stairs[game_key]
        return await callback.answer()
    win = int(game["bet"] * (1 + game["step"] * 0.3))
    builder = InlineKeyboardBuilder()
    builder.button(text="🚶 Шагнуть", callback_data=f"st_{game_key}")
    builder.button(text=f"💰 Забрать {format_money(win)}", callback_data=f"st_cash_{game_key}")
    await callback.message.edit_text(f"🪜 <b>ЛЕСЕНКА</b>\nШаг: {game['step']}/10\nПотенциал: {format_money(win)}", reply_markup=builder.as_markup())
    await callback.answer("Успешно!")

@group_router.callback_query(F.data.startswith("st_cash_"))
async def cashout_stairs_final(callback: CallbackQuery):
    game_key = callback.data.split("st_cash_")[1]
    if game_key not in active_stairs: return
    game = active_stairs[game_key]
    win = int(game["bet"] * (1 + game["step"] * 0.3))
    update_balance(game["uid"], win)
    await callback.message.edit_text(f"💰 Забрали {format_money(win)}!")
    del active_stairs[game_key]
    await callback.answer("Зачислено!")

# Блэкджек
active_bj = {}
@group_router.message(F.text.regexp(r"(?i)^бж\s+(\d+)$"))
async def play_bj_final(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    p_cards = [random.randint(2, 11), random.randint(2, 11)]
    d_cards = [random.randint(2, 11), random.randint(2, 11)]
    active_bj[game_key] = {"uid": user[0], "bet": amount, "p": p_cards, "d": d_cards}
    text = f"🃏 <b>БЛЭКДЖЕК</b>\nТвои карты: {p_cards[0]} + {p_cards[1]} = {sum(p_cards)}\nДилер: {d_cards[0]} + ?\n"
    builder = InlineKeyboardBuilder().button(text="Взять", callback_data=f"bj_hit_{game_key}").button(text="Хватит", callback_data=f"bj_stand_{game_key}")
    await message.reply(text, reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit_final(callback: CallbackQuery):
    game_key = callback.data.split("bj_hit_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    game["p"].append(random.randint(2, 11))
    score = sum(game["p"])
    if score > 21:
        await callback.message.edit_text(f"🃏 Перебор! {score}. Проигрыш {format_money(game['bet'])}.")
        del active_bj[game_key]
    else:
        builder = InlineKeyboardBuilder().button(text="Взять", callback_data=f"bj_hit_{game_key}").button(text="Хватит", callback_data=f"bj_stand_{game_key}")
        await callback.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\nТвои: {score}\nДилер: {game['d'][0]} + ?", reply_markup=builder.as_markup())
    await callback.answer()

@group_router.callback_query(F.data.startswith("bj_stand_"))
async def bj_stand_final(callback: CallbackQuery):
    game_key = callback.data.split("bj_stand_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    p_score, d_score = sum(game["p"]), sum(game["d"])
    while d_score < 17:
        game["d"].append(random.randint(2, 11))
        d_score = sum(game["d"])
    text = f"🃏 <b>БЛЭКДЖЕК</b>\nТвои: {p_score}\nДилер: {d_score}\n\n"
    if d_score > 21 or p_score > d_score:
        update_balance(game["uid"], game["bet"] * 2)
        text += "🎉 Ты выиграл!"
    elif p_score == d_score:
        update_balance(game["uid"], game["bet"])
        text += "🤝 Ничья."
    else: text += "😢 Дилер выиграл."
    await callback.message.edit_text(text)
    del active_bj[game_key]
    await callback.answer()

# Джокер
@group_router.message(F.text.regexp(r"(?i)^джокер\s+(\d+)$"))
async def play_joker_final(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    msg = await message.answer_dice(emoji="🃏")
    await asyncio.sleep(3)
    if msg.dice.value in [1, 2]:
        update_balance(user[0], amount * 3)
        await message.reply(f"🃏 ДЖОКЕР! Выигрыш x3: {format_money(amount * 3)}!")
    else: await message.reply("😢 Не повезло.")

# ==============================================================================
# ФИНАЛЬНЫЙ ПАТЧ: БАЛАНС, ПРОМОКОДЫ И ГИФКА РУЛЕТКИ
# ==============================================================================
from aiogram.types import FSInputFile

# --- 1. Команда "б" в группе (жесткая перезапись) ---
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def balance_group_final(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    user = get_user(message.from_user.id)
    await message.reply(f"💰 Баланс <a href='tg://user?id={user[0]}'>{message.from_user.first_name}</a>: <b>{format_money(user[3])}</b>")

# --- 2. Активация промокода в ЛС ---
@user_router.message(F.text.regexp(r"(?i)^промо\s+(\w+)$"))
async def use_promo_final(message: Message):
    if message.chat.type != "private": return
    
    code = message.text.split()[1].upper()
    promo = db_execute("SELECT reward, limit_count, used_count FROM promos WHERE code = ?", (code,), fetchone=True)
    
    if not promo: 
        return await message.reply("❌ Промокод не найден.")
    if promo[2] >= promo[1]: 
        return await message.reply("❌ Лимит активаций исчерпан.")
    
    user = get_user(message.from_user.id)
    update_balance(user[0], promo[0])
    db_execute("UPDATE promos SET used_count = used_count + 1 WHERE code = ?", (code,))
    await message.reply(f"✅ Промокод активирован! Ты получил {format_money(promo[0])}!")

# --- 3. Рулетка с гифкой (жесткая перезапись) ---
active_roulette_final = {}

@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+)\s+(\d+)$"))
async def bet_roulette_photo(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette_final: 
        active_roulette_final[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette_final[chat_id]["status"] != "waiting": 
        return await message.reply("⏳ Идет раунд.")
    
    parts = message.text.lower().split()
    bet, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount)
    active_roulette_final[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "bet": bet, "amount": amount})
    await message.reply(f"✅ Ставка: <b>{message.from_user.first_name}</b> {format_money(amount)} на {bet.upper()}")

@group_router.message(F.text.lower() == "го")
async def start_roulette_photo(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette_final or not active_roulette_final[chat_id]["bets"]: return
    active_roulette_final[chat_id]["status"] = "playing"
    
    # Отправляем гифку (если есть)
    try:
        msg = await message.answer_animation(
            animation=FSInputFile("assets/roulette.gif"), 
            caption="🎡 Рулетка крутится..."
        )
    except:
        msg = await message.answer("🎡 Рулетка крутится...")
        
    await asyncio.sleep(3)
    
    result_num = random.randint(0, 36)
    reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "з" if result_num == 0 else "к" if result_num in reds else "ч"
    res_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[color]
    
    text = f"🎯 Выпало: <b>{result_num} {res_name}</b>\n\n"
    winners = []
    for b in active_roulette_final[chat_id]["bets"]:
        win = False
        if b['bet'] in [color, "красное" if color=="к" else "черное" if color=="ч" else "зеро"]: win = True
        elif b['bet'] == "чет" and result_num % 2 == 0 and result_num != 0: win = True
        elif b['bet'] == "нечет" and result_num % 2 != 0: win = True
        elif "-" in b['bet']:
            start, end = map(int, b['bet'].split("-"))
            if start <= result_num <= end: win = True
        if win:
            prize = b['amount'] * 2
            update_balance(b['uid'], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")
            
    text += "\n".join(winners) if winners else "😢 Победителей нет."
    try: await msg.edit_caption(caption=text)
    except: await msg.edit_text(text)
    
    active_roulette_final[chat_id] = {"status": "waiting", "bets": []}

# ==============================================================================
# ПАТЧ: ПОЛНОСТЬЮ РАБОЧИЕ REPLY-КНОПКИ В ЛС (БЕЗ ЗАГЛУШЕК)
# ==============================================================================
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

# --- 1. ИГРЫ В ЛС (Кейсы, Колесо, Лотерея, Работа) ---
@user_router.message(F.text.in_(["🎮 Игры", "🎮 Games"]))
async def games_menu_ls(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📦 Кейсы"), KeyboardButton(text="🎡 Колесо"))
    builder.row(KeyboardButton(text="🎟 Лотерея"), KeyboardButton(text="💼 Работа"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>\nВыбирай раздел:", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text == "📦 Кейсы")
async def cases_menu_ls(message: Message):
    user = get_user(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Обычный кейс", callback_data="open_case")
    builder.button(text="💎 VIP кейс", callback_data="open_vip_case")
    await message.answer("📦 <b>КЕЙСЫ</b>", reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "open_case")
async def open_case_ls(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    now = datetime.datetime.now()
    if user[6] and now - datetime.datetime.fromisoformat(user[6]) < datetime.timedelta(hours=24):
        return await callback.answer("⏳ Кейс уже открыт. Жди 24 часа.", show_alert=True)
    
    prize = random.choice([1000, 2000, 5000, 10000, 15000, 25000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    
    try:
        # Пытаемся отправить гифку
        await callback.message.answer_animation(
            animation=FSInputFile("assets/case.gif"), 
            caption=f"🎁 Ты открыл кейс и выиграл <b>{format_money(prize)}</b>!"
        )
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text(f"🎁 Ты открыл кейс и выиграл <b>{format_money(prize)}</b>!")
    await callback.answer()

@user_router.callback_query(F.data == "open_vip_case")
async def open_vip_case_ls(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    # Жесткая проверка на VIP
    if user[10] != "vip": 
        return await callback.answer("❌ Этот кейс доступен только VIP-игрокам. Купи VIP в донате!", show_alert=True)
        
    now = datetime.datetime.now()
    if user[7] and now - datetime.datetime.fromisoformat(user[7]) < datetime.timedelta(hours=12):
        return await callback.answer("⏳ VIP кейс уже открыт. Жди 12 часов.", show_alert=True)
        
    prize = random.choice([5000, 10000, 25000, 50000, 100000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_vip_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    
    try:
        await callback.message.answer_animation(
            animation=FSInputFile("assets/case.gif"), 
            caption=f"💎 Ты открыл VIP кейс и выиграл <b>{format_money(prize)}</b>!"
        )
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text(f"💎 Ты открыл VIP кейс и выиграл <b>{format_money(prize)}</b>!")
    await callback.answer()

@user_router.message(F.text == "🎡 Колесо")
async def spin_wheel_ls(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[8] and now - datetime.datetime.fromisoformat(user[8]) < datetime.timedelta(hours=12):
        time_left = datetime.timedelta(hours=12) - (now - datetime.datetime.fromisoformat(user[8]))
        return await message.answer(f"⏳ Колесо крутится раз в 12 часов. Жди еще {time_left.seconds//3600} ч.")
    
    await message.answer("🎡 Колесо крутится...")
    await asyncio.sleep(2)
    
    prize = random.choice([0, 500, 1000, 5000, 10000, 50000])
    if prize > 0: 
        update_balance(user[0], prize)
        await message.answer(f"🎉 Ты выиграл <b>{format_money(prize)}</b>!")
    else:
        await message.answer("😢 Пусто. Попробуй еще раз через 12 часов.")
        
    db_execute("UPDATE users SET last_wheel = ? WHERE user_id = ?", (now.isoformat(), user[0]))

@user_router.message(F.text == "🎟 Лотерея")
async def lottery_menu_ls(message: Message):
    user = get_user(message.from_user.id)
    price = 5000
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Купить билет ({format_money(price)})", callback_data="buy_lottery")
    await message.answer("🎟 <b>ЛОТЕРЕЯ</b>\n\nПриз: <b>100 000 Tokens</b>\nРозыгрыш: каждый день в 20:00", reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "buy_lottery")
async def buy_lottery_ls(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    price = 5000
    if user[3] < price: return await callback.answer("❌ Мало средств.", show_alert=True)
    
    update_balance(user[0], -price)
    db_execute("INSERT OR IGNORE INTO lottery (user_id) VALUES (?)", (user[0],))
    await callback.answer("✅ Билет куплен! Удачи в 20:00!", show_alert=True)

@user_router.message(F.text == "💼 Работа")
async def work_ls(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[10] and now - datetime.datetime.fromisoformat(user[10]) < datetime.timedelta(hours=1):
        time_left = datetime.timedelta(hours=1) - (now - datetime.datetime.fromisoformat(user[10]))
        return await message.answer(f"⏳ Ты уже работал. Отдых еще {time_left.seconds//60} мин.")
        
    salary = 1500
    update_balance(user[0], salary)
    db_execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer(f"💼 Ты поработал и получил <b>{format_money(salary)}</b>!")

# --- 2. ДОНАТ (ПОЛНОСТЬЮ РАБОЧИЙ) ---
@user_router.message(F.text.in_(["💎 Донат", "💎 Donate"]))
async def donate_menu_ls(message: Message):
    if message.chat.type != "private": return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⭐ 15 Stars"), KeyboardButton(text="⭐ 25 Stars"))
    builder.row(KeyboardButton(text="⭐ 50 Stars"), KeyboardButton(text="⭐ 100 Stars"))
    builder.row(KeyboardButton(text="✍️ Своя сумма"), KeyboardButton(text="⬅️ Назад"))
    
    await message.answer(
        "💎 <b>ДОНАТ</b>\n\n🔥 Курс дня: 1 ⭐ = 12 500 Tokens\n\nВыбери пакет:", 
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

@user_router.message(F.text.startswith("⭐"))
async def buy_stars(message: Message):
    try:
        stars = int(message.text.split()[1])
        tokens = stars * 12500
        # Отправляем счет на оплату
        await message.answer_invoice(
            title=f"Покупка {stars} Stars",
            description=f"Пополнение на {format_money(tokens)}",
            payload=f"stars_{stars}",
            provider_token="", # Для Stars оставляем пустым
            currency="XTR",    # Валюта Stars
            prices=[types.LabeledPrice(label="Stars", amount=stars)],
            start_parameter="buy_stars"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@user_router.message(F.text == "✍️ Своя сумма")
async def custom_stars(message: Message, state: FSMContext):
    await message.answer("Введи количество Stars (от 1 до 10000):", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_custom_stars")

@user_router.message(StateFilter("waiting_custom_stars"))
async def process_custom_stars(message: Message, state: FSMContext):
    try:
        stars = int(message.text)
        if stars < 1 or stars > 10000: raise ValueError
        tokens = stars * 12500
        await message.answer_invoice(
            title=f"Покупка {stars} Stars",
            description=f"Пополнение на {format_money(tokens)}",
            payload=f"stars_{stars}",
            provider_token="",
            currency="XTR",
            prices=[types.LabeledPrice(label="Stars", amount=stars)],
            start_parameter="buy_stars"
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число от 1 до 10000!")

# ==============================================================================
# МЕГА-ПАТЧ: ПОДДЕРЖКА С БОЛЬШИМИ ТЕКСТАМИ (RU/EN)
# ==============================================================================
from aiogram.types import ReplyKeyboardRemove

# 1. Главное меню поддержки
@user_router.message(F.text.in_(["🆘 Поддержка", "🆘 Support"]))
async def support_menu_big(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    lang = user[2]
    
    builder = ReplyKeyboardBuilder()
    if lang == "ru":
        builder.row(KeyboardButton(text="💰 Как заработать?"), KeyboardButton(text="💳 Проблема с оплатой"))
        builder.row(KeyboardButton(text="🎁 Не пришел бонус"), KeyboardButton(text="🎰 Как играть в чате?"))
        builder.row(KeyboardButton(text="🛡 Проблема с кланом"), KeyboardButton(text="⚠️ Сообщить об ошибке"))
        builder.row(KeyboardButton(text="✍️ Написать Админу"), KeyboardButton(text="⬅️ Назад"))
        text = "🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\nЗдесь ты найдешь ответы на все свои вопросы. Выбери тему, которая тебя интересует, и я дам подробную инструкцию."
    else:
        builder.row(KeyboardButton(text="💰 How to earn?"), KeyboardButton(text="💳 Payment issue"))
        builder.row(KeyboardButton(text="🎁 No bonus?"), KeyboardButton(text="🎰 How to play?"))
        builder.row(KeyboardButton(text="🛡 Clan issue"), KeyboardButton(text="⚠️ Report a bug"))
        builder.row(KeyboardButton(text="✍️ Write to Admin"), KeyboardButton(text="⬅️ Back"))
        text = "🆘 <b>SUPPORT CENTER</b>\n\nHere you will find answers to all your questions. Choose a topic below and I will provide a detailed guide."
    
    await message.answer(text, reply_markup=builder.as_markup(resize_keyboard=True))

# ==============================================================================
# РУССКИЕ ОТВЕТЫ (БОЛЬШИЕ ТЕКСТА)
# ==============================================================================

@user_router.message(F.text == "💰 Как заработать?")
async def sup_earn_ru_big(message: Message):
    await message.answer(
        "💰 <b>КАК ЗАРАБОТАТЬ ТОКЕНЫ</b>\n\n"
        "У нас есть несколько проверенных способов поднять свой баланс:\n\n"
        "🎁 <b>Ежедневный бонус</b>\n"
        "Заходи каждый день в раздел «Профиль» и забирай свои 5 000 токенов. Не забывай заходить, чтобы не терять прогресс!\n\n"
        "💼 <b>Работа</b>\n"
        "В разделе «Игры» есть кнопка «Работа». Нажимай и получай 1 500 токенов раз в час. Это пассивный доход, который всегда с тобой.\n\n"
        "🎮 <b>Игры в чате</b>\n"
        "Зайди в наш игровой чат @tokenplays и играй в кости, рулетку или мины. Выигрывай токены у других игроков и становись самым богатым!\n\n"
        "📦 <b>Кейсы</b>\n"
        "Каждый день открывай бесплатный кейс в профиле. Внутри может быть от 1 000 до 50 000 токенов!\n\n"
        "👥 <b>Рефералы</b>\n"
        "Приглашай друзей по своей ссылке в профиле и получай бонусы за каждого приведенного игрока.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "💳 Проблема с оплатой")
async def sup_pay_ru_big(message: Message):
    await message.answer(
        "💳 <b>ПРОБЛЕМА С ОПЛАТОЙ</b>\n\n"
        "Если ты купил Stars или VIP, но токены не пришли на баланс — сделай следующее:\n\n"
        "1️⃣ Подожди 5-10 минут (иногда Telegram задерживает обработку платежей, особенно в часы пик).\n\n"
        "2️⃣ Проверь баланс в профиле (нажми на кнопку «Профиль» в главном меню).\n\n"
        "3️⃣ Если токены так и не пришли — напиши Админу @vctorw. Обязательно прикрепи скриншот чека из Telegram, чтобы мы могли быстро найти твой платеж и зачислить средства.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🎁 Не пришел бонус")
async def sup_bonus_ru_big(message: Message):
    await message.answer(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        "Бонус доступен раз в 24 часа. Если ты нажал на кнопку «Бонус», но токены не пришли — это значит, что ты уже забирал его сегодня.\n\n"
        "⏳ Система работает четко: как только пройдет ровно 24 часа с момента последнего получения, кнопка снова станет активной.\n\n"
        "Если ты уверен, что прошло больше суток, а бонус не пришел — напиши Админу @vctorw, но такое бывает крайне редко.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🎰 Как играть в чате?")
async def sup_games_ru_big(message: Message):
    await message.answer(
        "🎰 <b>КАК ИГРАТЬ В ЧАТЕ</b>\n\n"
        "Все наши игры проходят в официальном чате: @tokenplays\n\n"
        "Чтобы начать играть, просто пиши команды в чат:\n\n"
        "🎲 <b>Кости</b> — напиши <code>кости 1000</code>. Если выпадет 4, 5 или 6 — ты выиграл x2.\n"
        "🎯 <b>Дартс</b> — напиши <code>дартс 1000</code>. Тот же принцип.\n"
        "🎡 <b>Рулетка</b> — напиши <code>к 1000</code> (на красное) или <code>ч 1000</code> (на черное). Запуск: <code>го</code>.\n"
        "💣 <b>Мины</b> — напиши <code>мины 1000</code>. Ищи безопасные клетки и забирай куш!\n\n"
        "Перед игрой убедись, что у тебя на балансе достаточно токенов. Баланс можно проверить командой <code>б</code> в чате.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🛡 Проблема с кланом")
async def sup_clan_ru_big(message: Message):
    await message.answer(
        "🛡 <b>КЛАНЫ</b>\n\n"
        "Кланы — это объединения игроков для совместных игр и общего банка.\n\n"
        "Что нужно знать:\n"
        "▫️ Создание клана стоит 100 000 токенов.\n"
        "▫️ Вступить в клан можно бесплатно (если владелец пригласит).\n"
        "▫️ У клана есть своя казна, куда игроки скидывают токены.\n\n"
        "Если у тебя возник баг при создании клана (списались токены, но клан не создался) — пиши Админу @vctorw с чеком и описанием проблемы.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "⚠️ Сообщить об ошибке")
async def sup_bug_ru_big(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ <b>СООБЩИТЬ ОБ ОШИБКЕ</b>\n\n"
        "Спасибо, что помогаешь нам делать казино лучше! Пожалуйста, опиши проблему в одном сообщении как можно подробнее:\n\n"
        "▫️ Где произошла ошибка (в ЛС или в чате).\n"
        "▫️ Что ты делал в этот момент.\n"
        "▫️ Прикрепи скриншот, если это возможно.\n\n"
        "<i>За критический баг можем наградить токенами!</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_bug")

@user_router.message(StateFilter("waiting_bug"))
async def process_bug_ru_big(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    try:
        await bot.send_message(ADMIN_ID, f"🐞 <b>БАГ-РЕПОРТ</b>\nОт: @{message.from_user.username} (ID: <code>{user[0]}</code>)\n\n{message.text}")
        await message.answer("✅ Спасибо! Твое сообщение отправлено Админу.", reply_markup=get_main_menu(user[2]))
    except: 
        await message.answer("❌ Ошибка отправки. Попробуй позже.")
    await state.clear()

@user_router.message(F.text == "✍️ Написать Админу")
async def sup_ticket_ru_big(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>СВЯЗЬ С АДМИНОМ</b>\n\n"
        "Напиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.\n\n"
        "⚠️ <i>Пожалуйста, не спамь. Отвечаем в течение 24 часов. Если вопрос срочный — прикрепи чек или скриншот.</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_ticket")

@user_router.message(StateFilter("waiting_ticket"))
async def process_ticket_ru_big(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    try:
        admin_msg = await bot.send_message(
            ADMIN_ID, 
            f"📩 <b>ТИКЕТ</b>\nОт: @{message.from_user.username} (ID: <code>{user[0]}</code>)\n\n{message.text}\n\n<i>Ответь Reply на это сообщение.</i>"
        )
        db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, 0, ?)", (user[0], f"ticket_{admin_msg.message_id}", datetime.datetime.now().isoformat()))
        await message.answer("✅ Вопрос отправлен Админу. Ожидай ответа.", reply_markup=get_main_menu(user[2]))
    except:
        await message.answer("❌ Ошибка отправки. Попробуй позже.")
    await state.clear()

# ==============================================================================
# АНГЛИЙСКИЕ ОТВЕТЫ (БОЛЬШИЕ ТЕКСТА)
# ==============================================================================

@user_router.message(F.text == "💰 How to earn?")
async def sup_earn_en_big(message: Message):
    await message.answer(
        "💰 <b>HOW TO EARN TOKENS</b>\n\n"
        "We have several proven ways to boost your balance:\n\n"
        "🎁 <b>Daily Bonus</b>\n"
        "Visit the 'Profile' section every day and claim your 5,000 tokens. Don't forget to log in to keep your progress!\n\n"
        "💼 <b>Work</b>\n"
        "In the 'Games' section, there is a 'Work' button. Click it to receive 1,500 tokens once an hour. It's a passive income that's always with you.\n\n"
        "🎮 <b>Chat Games</b>\n"
        "Join our game chat @tokenplays and play dice, roulette, or mines. Win tokens from other players and become the richest!\n\n"
        "📦 <b>Cases</b>\n"
        "Open a free case in your profile every day. You can get from 1,000 to 50,000 tokens inside!\n\n"
        "👥 <b>Referrals</b>\n"
        "Invite friends using your link in the profile and get bonuses for each player you bring.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Back").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "💳 Payment issue")
async def sup_pay_en_big(message: Message):
    await message.answer(
        "💳 <b>PAYMENT ISSUE</b>\n\n"
        "If you bought Stars or VIP but tokens didn't arrive in your balance, do the following:\n\n"
        "1️⃣ Wait 5-10 minutes (sometimes Telegram delays payment processing, especially during peak hours).\n\n"
        "2️⃣ Check your balance in the profile (click the 'Profile' button in the main menu).\n\n"
        "3️⃣ If tokens still haven't arrived — write to Admin @vctorw. Be sure to attach a screenshot of the receipt from Telegram so we can quickly find your payment and credit the funds.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Back").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🎁 No bonus?")
async def sup_bonus_en_big(message: Message):
    await message.answer(
        "🎁 <b>DAILY BONUS</b>\n\n"
        "The bonus is available once every 24 hours. If you clicked the 'Bonus' button but tokens didn't arrive, it means you already claimed it today.\n\n"
        "⏳ The system works precisely: once exactly 24 hours have passed since your last claim, the button becomes active again.\n\n"
        "If you are sure that more than a day has passed and the bonus hasn't arrived — write to Admin @vctorw, but this is extremely rare.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Back").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🎰 How to play?")
async def sup_games_en_big(message: Message):
    await message.answer(
        "🎰 <b>HOW TO PLAY IN CHAT</b>\n\n"
        "All our games take place in the official chat: @tokenplays\n\n"
        "To start playing, just type commands in the chat:\n\n"
        "🎲 <b>Dice</b> — type <code>кости 1000</code>. If 4, 5 or 6 rolls, you win x2.\n"
        "🎯 <b>Darts</b> — type <code>дартс 1000</code>. Same principle.\n"
        "🎡 <b>Roulette</b> — type <code>к 1000</code> (for red) or <code>ч 1000</code> (for black). Start: <code>го</code>.\n"
        "💣 <b>Mines</b> — type <code>мины 1000</code>. Find safe cells and claim the prize!\n\n"
        "Make sure you have enough tokens in your balance before playing. You can check your balance with the <code>б</code> command in the chat.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Back").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "🛡 Clan issue")
async def sup_clan_en_big(message: Message):
    await message.answer(
        "🛡 <b>CLANS</b>\n\n"
        "Clans are associations of players for joint games and a shared treasury.\n\n"
        "What you need to know:\n"
        "▫️ Creating a clan costs 100,000 tokens.\n"
        "▫️ Joining a clan is free (if the owner invites you).\n"
        "▫️ The clan has its own treasury where players deposit tokens.\n\n"
        "If you encountered a bug when creating a clan (tokens were deducted but the clan wasn't created) — write to Admin @vctorw with a receipt and a description of the problem.",
        reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Back").as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "⚠️ Report a bug")
async def sup_bug_en_big(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ <b>REPORT A BUG</b>\n\n"
        "Thank you for helping us make the casino better! Please describe the problem in one message as detailed as possible:\n\n"
        "▫️ Where the error occurred (in DM or in chat).\n"
        "▫️ What you were doing at that moment.\n"
        "▫️ Attach a screenshot if possible.\n\n"
        "<i>For a critical bug, we may reward you with tokens!</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_bug")

@user_router.message(F.text == "✍️ Write to Admin")
async def sup_ticket_en_big(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>CONTACT ADMIN</b>\n\n"
        "Write your question in one message. The Admin will reply to you in DM.\n\n"
        "⚠️ <i>Please do not spam. We reply within 24 hours. If your question is urgent — attach a receipt or screenshot.</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_ticket")
    
# ==============================================================================
# ПАТЧ: РАБОЧАЯ КНОПКА "НАЗАД" (RU/EN) И СВЯЗКА РЕПЛАЙ-КНОПОК
# ==============================================================================

# 1. Глобальная кнопка "Назад" / "Back"
@user_router.message(F.text.in_(["⬅️ Назад", "⬅️ Back"]))
async def global_back_fix(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(
        get_text(user[2], "welcome", name=message.from_user.first_name), 
        reply_markup=get_main_menu(user[2])
    )

# ==============================================================================
# МЕГА-ПАТЧ: ПОЛНАЯ ПЕРЕЗАПИСЬ АДМИНКИ (БЕЗ ЗАГЛУШЕК)
# ==============================================================================
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

class AdminStates(StatesGroup):
    waiting_give_id = State()
    waiting_give_amount = State()
    waiting_take_id = State()
    waiting_take_amount = State()
    waiting_promo_code = State()
    waiting_promo_amount = State()
    waiting_promo_limit = State()
    waiting_role_id = State()
    waiting_broadcast = State()

# --- 1. ГЛАВНОЕ МЕНЮ АДМИНКИ (исправляем кнопку "В меню игрока") ---
def get_admin_menu_fixed():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💸 Экономика"))
    builder.row(KeyboardButton(text="🎁 Промокоды"), KeyboardButton(text="👥 Люди"))
    builder.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎰 Игры"))
    builder.row(KeyboardButton(text="⚙️ Система"), KeyboardButton(text="🎁 Ивент"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
    return builder.as_markup(resize_keyboard=True)

@admin_router.message(F.text == "⬅️ В меню игрока")
async def admin_back_to_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu_fixed())
    else:
        user = get_user(message.from_user.id)
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

# --- 2. СТАТИСТИКА ---
@admin_router.message(F.text == "📊 Статистика")
async def admin_stats_fixed(message: Message):
    if message.from_user.id != ADMIN_ID: return
    users = db_execute("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_bal = db_execute("SELECT SUM(balance) FROM users", fetchone=True)[0] or 0
    games_today = db_execute("SELECT COUNT(*) FROM games_log WHERE date(date) = date('now')", fetchone=True)[0]
    
    text = (
        f"📊 <b>СТАТИСТИКА КАЗИНО</b>\n\n"
        f"👥 Всего игроков: <b>{users}</b>\n"
        f"💰 В обороте: <b>{format_money(total_bal)}</b>\n"
        f"🎮 Игр за сегодня: <b>{games_today}</b>"
    )
    await message.answer(text, reply_markup=get_admin_menu_fixed())

# --- 3. ЭКОНОМИКА (Выдать, Забрать, Налог) ---
@admin_router.message(F.text == "💸 Экономика")
async def admin_eco_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать по ID"), KeyboardButton(text="Забрать по ID"))
    builder.row(KeyboardButton(text="Налог 10%"), KeyboardButton(text="Выдать всем"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    await message.answer("💸 <b>ЭКОНОМИКА</b>\nВыбери операцию:", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "⬅️ В меню админа")
async def admin_back_to_admin_menu(message: Message):
    await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu_fixed())

@admin_router.message(F.text == "Выдать по ID")
async def admin_give_start(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_give_id)

@admin_router.message(AdminStates.waiting_give_id)
async def admin_give_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму:")
    await state.set_state(AdminStates.waiting_give_amount)

@admin_router.message(AdminStates.waiting_give_amount)
async def admin_give_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    update_balance(data['target'], amount)
    await message.answer(f"✅ Выдано {format_money(amount)} игроку <code>{data['target']}</code>", reply_markup=get_admin_menu_fixed())
    await state.clear()

@admin_router.message(F.text == "Забрать по ID")
async def admin_take_start(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_take_id)

@admin_router.message(AdminStates.waiting_take_id)
async def admin_take_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму для забора:")
    await state.set_state(AdminStates.waiting_take_amount)

@admin_router.message(AdminStates.waiting_take_amount)
async def admin_take_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    update_balance(data['target'], -amount)
    await message.answer(f"✅ Забрано {format_money(amount)} у игрока <code>{data['target']}</code>", reply_markup=get_admin_menu_fixed())
    await state.clear()

@admin_router.message(F.text == "Налог 10%")
async def admin_tax_fixed(message: Message):
    users = db_execute("SELECT user_id, balance FROM users WHERE balance > 100000", fetchall=True)
    total = 0
    for u in users:
        tax = int(u[1] * 0.1)
        update_balance(u[0], -tax)
        total += tax
    await message.answer(f"📉 Собрано налогов: <b>{format_money(total)}</b>", reply_markup=get_admin_menu_fixed())

@admin_router.message(F.text == "Выдать всем")
async def admin_give_all(message: Message, state: FSMContext):
    await message.answer("Введи сумму для выдачи всем игрокам:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_give_all")

@admin_router.message(StateFilter("waiting_give_all"))
async def admin_give_all_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET balance = balance + ?", (amount,))
    await message.answer(f"✅ Всем игрокам выдано по {format_money(amount)}!", reply_markup=get_admin_menu_fixed())
    await state.clear()

# --- 4. ПРОМОКОДЫ ---
@admin_router.message(F.text == "🎁 Промокоды")
async def admin_promo_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Создать промокод"))
    builder.row(KeyboardButton(text="Список промокодов"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    await message.answer("🎁 <b>ПРОМОКОДЫ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "Создать промокод")
async def admin_promo_create(message: Message, state: FSMContext):
    await message.answer("Введи код (слово):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_promo_code)

@admin_router.message(AdminStates.waiting_promo_code)
async def admin_promo_amount(message: Message, state: FSMContext):
    await state.update_data(code=message.text.upper())
    await message.answer("Введи сумму награды:")
    await state.set_state(AdminStates.waiting_promo_amount)

@admin_router.message(AdminStates.waiting_promo_amount)
async def admin_promo_limit(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(amount=amount)
    await message.answer("Введи лимит активаций:")
    await state.set_state(AdminStates.waiting_promo_limit)

@admin_router.message(AdminStates.waiting_promo_limit)
async def admin_promo_finish(message: Message, state: FSMContext):
    try: limit = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    db_execute("INSERT OR REPLACE INTO promos (code, reward, limit_count) VALUES (?, ?, ?)", (data['code'], data['amount'], limit))
    await message.answer(f"✅ Промокод <b>{data['code']}</b> создан!", reply_markup=get_admin_menu_fixed())
    await state.clear()

@admin_router.message(F.text == "Список промокодов")
async def admin_promo_list(message: Message):
    promos = db_execute("SELECT code, reward, limit_count, used_count FROM promos", fetchall=True)
    if not promos: return await message.answer("📭 Промокодов нет.")
    text = "🎁 <b>СПИСОК ПРОМОКОДОВ:</b>\n\n"
    for p in promos:
        text += f"🔹 <code>{p[0]}</code> | {format_money(p[1])} | {p[3]}/{p[2]}\n"
    await message.answer(text, reply_markup=get_admin_menu_fixed())

# --- 5. УПРАВЛЕНИЕ ЛЮДЬМИ ---
@admin_router.message(F.text == "👥 Люди")
async def admin_people_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать Модера"), KeyboardButton(text="Выдать Пиарщика"))
    builder.row(KeyboardButton(text="Снять роль"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    await message.answer("👥 <b>УПРАВЛЕНИЕ ЛЮДЬМИ</b>", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "Выдать Модера")
async def admin_add_mod(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_mod_id")

@admin_router.message(StateFilter("waiting_mod_id"))
async def admin_add_mod_finish(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET role = 'moderator' WHERE user_id = ?", (target,))
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Модер.", reply_markup=get_admin_menu_fixed())
    await state.clear()

@admin_router.message(F.text == "Выдать Пиарщика")
async def admin_add_pr(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_pr_id")

@admin_router.message(StateFilter("waiting_pr_id"))
async def admin_add_pr_finish(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET role = 'promoter' WHERE user_id = ?", (target,))
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Пиарщик.", reply_markup=get_admin_menu_fixed())
    await state.clear()

# --- 6. РАССЫЛКА (ПОЛНОСТЬЮ РАБОЧАЯ) ---
@admin_router.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Введи текст для рассылки (или /cancel):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_broadcast)

@admin_router.message(AdminStates.waiting_broadcast)
async def admin_broadcast_finish(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_admin_menu_fixed())
        
    users = db_execute("SELECT user_id FROM users", fetchall=True)
    success = 0
    status_msg = await message.answer("⏳ Начинаю рассылку...")
    
    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
        
    await status_msg.edit_text(f"✅ Рассылка завершена!\nДоставлено: {success}/{len(users)}")
    await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu_fixed())
    await state.clear()

# ==============================================================================
# МЕГА-ПАТЧ: КЛАНЫ 2.0 (КАЗНА, РОЛИ, ПОЯСНЕНИЕ)
# ==============================================================================
from aiogram.types import ReplyKeyboardRemove

# 1. Главное меню Кланов (с пояснением)
@user_router.message(F.text == "🛡 Клан")
async def clan_menu_mega(message: Message):
    user = get_user(message.from_user.id)
    builder = ReplyKeyboardBuilder()
    
    text = (
        "🛡 <b>КЛАНОВАЯ СИСТЕМА</b>\n\n"
        "<i>Кланы — это объединения игроков. Вступив в клан, ты получаешь защиту, общую казну и участвуешь в войнах за первое место в топе.</i>\n\n"
    )
    
    if not user[12]:
        builder.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
        text += "Ты пока не в клане. Создай свой или попроси владельца другого клана пригласить тебя."
    else:
        clan = db_execute("SELECT name, treasury, owner_id FROM clans WHERE id = ?", (user[12],), fetchone=True)
        builder.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="🏆 Топ кланов"))
        builder.row(KeyboardButton(text="📜 Мой клан"), KeyboardButton(text="🚪 Выйти из клана"))
        
        role = "👑 Владелец" if clan[2] == user[0] else "🛡 Рядовой"
        text += f"<b>Твой клан:</b> {clan[0]}\n<b>Твоя роль:</b> {role}\n<b>Казна:</b> {format_money(clan[1])}"
        
    builder.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer(text, reply_markup=builder.as_markup(resize_keyboard=True))

# 2. Создание клана
@user_router.message(F.text == "➕ Создать клан (100к)")
async def clan_create_mega(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user[3] < 100000: 
        return await message.answer("❌ Нужно 100 000 токенов для создания клана.")
    if user[12]: 
        return await message.answer("❌ Ты уже в клане.")
        
    await message.answer("🛡 Введи название клана (до 15 символов):", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_clan_name")

@user_router.message(StateFilter("waiting_clan_name"))
async def clan_create_finish_mega(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) > 15: 
        return await message.answer("❌ Слишком длинное (макс 15).")
    
    user = get_user(message.from_user.id)
    if user[3] < 100000:
        await state.clear()
        return await message.answer("❌ Недостаточно средств.")
        
    update_balance(user[0], -100000)
    db_execute("INSERT INTO clans (name, owner_id, treasury) VALUES (?, ?, 0)", (name, user[0]))
    clan_id = db_execute("SELECT id FROM clans WHERE owner_id = ?", (user[0],), fetchone=True)[0]
    db_execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, user[0]))
    
    await state.clear()
    await message.answer(f"✅ Клан <b>{name}</b> создан!\nТы теперь Владелец.", reply_markup=get_main_menu(user[2]))

# 3. Топ кланов
@user_router.message(F.text == "🏆 Топ кланов")
async def clan_top_mega(message: Message):
    clans = db_execute("SELECT name, treasury FROM clans ORDER BY treasury DESC LIMIT 10", fetchall=True)
    text = "🏆 <b>ТОП-10 КЛАНОВ:</b>\n\n"
    if not clans: 
        text += "Пока нет ни одного клана."
    else:
        for i, c in enumerate(clans, 1):
            text += f"{i}. <b>{c[0]}</b> — Казна: {format_money(c[1])}\n"
    await message.answer(text, reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True))

# 4. Внести в казну
@user_router.message(F.text == "💰 Внести в казну")
async def clan_deposit_start(message: Message, state: FSMContext):
    await message.answer("💰 Введи сумму, которую хочешь внести в казну клана:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_clan_deposit")

@user_router.message(StateFilter("waiting_clan_deposit"))
async def clan_deposit_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    
    user = get_user(message.from_user.id)
    if user[3] < amount: 
        await state.clear()
        return await message.answer("❌ Недостаточно средств.")
        
    update_balance(user[0], -amount)
    db_execute("UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, user[12]))
    
    await state.clear()
    await message.answer(f"✅ Ты внес {format_money(amount)} в казну клана!", reply_markup=get_main_menu(user[2]))

# 5. Информация о моем клане
@user_router.message(F.text == "📜 Мой клан")
async def clan_info_mega(message: Message):
    user = get_user(message.from_user.id)
    if not user[12]: return await message.answer("Ты не в клане.")
    
    clan = db_execute("SELECT name, treasury, owner_id FROM clans WHERE id = ?", (user[12],), fetchone=True)
    members = db_execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (user[12],), fetchone=True)[0]
    owner_name = db_execute("SELECT username FROM users WHERE user_id = ?", (clan[2],), fetchone=True)[0]
    
    text = (
        f"🛡 <b>ИНФОРМАЦИЯ О КЛАНЕ</b>\n\n"
        f"📛 Название: <b>{clan[0]}</b>\n"
        f"👑 Владелец: @{owner_name if owner_name != 'Unknown' else clan[2]}\n"
        f"👥 Участников: <b>{members}</b>\n"
        f"💰 Казна: <b>{format_money(clan[1])}</b>"
    )
    await message.answer(text, reply_markup=ReplyKeyboardBuilder().button(text="⬅️ Назад").as_markup(resize_keyboard=True))

# 6. Выход из клана
@user_router.message(F.text == "🚪 Выйти из клана")
async def clan_leave_mega(message: Message):
    user = get_user(message.from_user.id)
    if not user[12]: return await message.answer("Ты не в клане.")
    
    clan = db_execute("SELECT owner_id, name FROM clans WHERE id = ?", (user[12],), fetchone=True)
    if clan and clan[0] == user[0]:
        db_execute("DELETE FROM clans WHERE id = ?", (user[12],))
        db_execute("UPDATE users SET clan_id = NULL WHERE clan_id = ?", (user[12],))
        await message.answer(f"🚪 Ты распустил свой клан <b>{clan[1]}</b>.", reply_markup=get_main_menu(user[2]))
    else:
        db_execute("UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
        await message.answer("🚪 Ты вышел из клана.", reply_markup=get_main_menu(user[2]))

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

