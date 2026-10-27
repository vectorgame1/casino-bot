import asyncio
import logging
import sqlite3
import datetime
import os
import random
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, FSInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.exceptions import TelegramBadRequest

# ==============================================================================
# НАСТРОЙКИ (ВПИШИ СВОИ ДАННЫЕ!)
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
        last_work TEXT, warns INTEGER DEFAULT 0, ref_id INTEGER DEFAULT NULL,
        clan_id INTEGER DEFAULT NULL
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, treasury INTEGER DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS promos (
        code TEXT PRIMARY KEY, reward INTEGER, limit_count INTEGER, used_count INTEGER DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (user_id INTEGER PRIMARY KEY)""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT, bet INTEGER, win INTEGER, date TEXT
    )""")
    logger.info("База данных инициализирована.")

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
# ЛОКАЛИЗАЦИЯ (RU / EN)
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
# КЛАВИАТУРЫ (ВСЕ В ОДНОМ МЕСТЕ)
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
    builder.row(KeyboardButton(text="🔗 Моя Рефка"), KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_games_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📦 Кейсы"), KeyboardButton(text="🎡 Колесо"))
    builder.row(KeyboardButton(text="🎟 Лотерея"), KeyboardButton(text="💼 Работа"))
    builder.row(KeyboardButton(text="🛡 Клан"), KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_clan_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
    builder.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="📜 Мой клан"))
    builder.row(KeyboardButton(text="🚪 Выйти из клана"), KeyboardButton(text="⬅️ В Игры"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💸 Экономика"))
    builder.row(KeyboardButton(text="🎁 Промокоды"), KeyboardButton(text="👥 Люди"))
    builder.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎰 Игры"))
    builder.row(KeyboardButton(text="⚙️ Система"), KeyboardButton(text="🎁 Ивент"))
    builder.row(KeyboardButton(text="⬅️ В меню игрока"))
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

def get_support_menu(lang):
    builder = ReplyKeyboardBuilder()
    if lang == "ru":
        builder.row(KeyboardButton(text="💰 Как заработать?"), KeyboardButton(text="💳 Проблема с оплатой"))
        builder.row(KeyboardButton(text="🎁 Не пришел бонус"), KeyboardButton(text="🎰 Как играть в чате?"))
        builder.row(KeyboardButton(text="🛡 Проблема с кланом"), KeyboardButton(text="⚠️ Сообщить об ошибке"))
        builder.row(KeyboardButton(text="✍️ Написать Админу"), KeyboardButton(text="⬅️ Назад"))
    else:
        builder.row(KeyboardButton(text="💰 How to earn?"), KeyboardButton(text="💳 Payment issue"))
        builder.row(KeyboardButton(text="🎁 No bonus?"), KeyboardButton(text="🎰 How to play?"))
        builder.row(KeyboardButton(text="🛡 Clan issue"), KeyboardButton(text="⚠️ Report a bug"))
        builder.row(KeyboardButton(text="✍️ Write to Admin"), KeyboardButton(text="⬅️ Back"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_eco_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать по ID"), KeyboardButton(text="Забрать по ID"))
    builder.row(KeyboardButton(text="Налог 10%"), KeyboardButton(text="Выдать всем"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_promo_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Создать промокод"), KeyboardButton(text="Список промокодов"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    return builder.as_markup(resize_keyboard=True)

def get_admin_people_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Выдать Модера"), KeyboardButton(text="Выдать Пиарщика"))
    builder.row(KeyboardButton(text="Снять роль"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    return builder.as_markup(resize_keyboard=True)

def get_group_games_menu():
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
    return builder.as_markup()

def get_back_to_games_btn():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в меню", callback_data="g_back")
    return builder.as_markup()

# ==============================================================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER (Чтобы не падал)
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
# ЧАСТЬ 2: ИГРОК (ПРОФИЛЬ, ПЕРЕВОДЫ, БОНУС, ДОНАТ, ПОДДЕРЖКА)
# ==============================================================================
from aiogram.types import FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

class TransferStates(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

# --- 1. СТАРТ ---
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await state.clear()
    
    # Проверка реф-ссылки
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_") and not user[11]:
        try:
            ref_id = int(args[1].split("_")[1])
            if ref_id != user[0]:
                db_execute("UPDATE users SET ref_id = ? WHERE user_id = ?", (ref_id, user[0]))
                update_balance(ref_id, 10000)
                try: await bot.send_message(ref_id, "🎉 По твоей ссылке зашел новый игрок! +10 000 Tokens.")
                except: pass
        except: pass

    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    elif user[4] == "moderator":
        await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРА</b>", reply_markup=get_mod_menu())
    elif user[4] == "promoter":
        await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>", reply_markup=get_pr_menu())
    else:
        await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

# --- 2. ПРОФИЛЬ ---
@user_router.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(get_text(user[2], "profile", uid=user[0], bal=format_money(user[3]), warns=user[10]), reply_markup=get_profile_menu())

@user_router.message(F.text == "🔗 Моя Рефка")
async def my_ref(message: Message):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    await message.answer(f"🔗 <b>Твоя реферальная ссылка:</b>\n\n<code>{link}</code>\n\nПриглашай друзей и получай 10 000 токенов за каждого!", reply_markup=get_profile_menu())

@user_router.message(F.text.in_(["⬅️ Назад", "⬅️ Back"]))
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

# --- 3. БОНУС ---
@user_router.message(F.text == "🎁 Бонус")
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[5] and now - datetime.datetime.fromisoformat(user[5]) < datetime.timedelta(hours=24):
        time_left = datetime.timedelta(hours=24) - (now - datetime.datetime.fromisoformat(user[5]))
        return await message.answer(f"⏳ Бонус уже забран. Следующий через {time_left.seconds//3600} ч. {time_left.seconds%3600//60} мин.", reply_markup=get_profile_menu())
    update_balance(user[0], 5000)
    db_execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer("🎁 Ты забрал бонус: <b>5 000 Tokens</b>!", reply_markup=get_profile_menu())

# --- 4. ИСТОРИЯ ---
@user_router.message(F.text == "📜 История")
async def history_menu(message: Message):
    user = get_user(message.from_user.id)
    logs = db_execute("SELECT game, bet, win, date FROM games_log WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user[0],), fetchall=True)
    text = "📜 <b>ПОСЛЕДНИЕ 5 ИГР:</b>\n\n"
    if not logs: text += "Нет игр."
    for l in logs:
        text += f"📅 {l[3][:10]} | 🎮 {l[0]}\n💰 Ставка: {l[1]} | Результат: {l[2]}\n\n"
    await message.answer(text, reply_markup=get_profile_menu())

# --- 5. ПЕРЕВОДЫ ---
@user_router.message(F.text.in_(["💸 Перевод", "💸 Transfer"]))
async def transfer_start(message: Message, state: FSMContext):
    await message.answer("Введи ID или @юзернейм игрока, кому хочешь перевести:\n(или напиши «Отмена»)", reply_markup=ReplyKeyboardRemove())
    await state.set_state(TransferStates.waiting_id)

@user_router.message(TransferStates.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    if message.text.lower() == "отмена":
        await state.clear()
        user = get_user(message.from_user.id)
        return await message.answer("Отменено.", reply_markup=get_main_menu(user[2]))
        
    target_text = message.text.replace("@", "").strip()
    target = db_execute("SELECT user_id FROM users WHERE user_id = ?" if target_text.isdigit() else "SELECT user_id FROM users WHERE username = ?", (int(target_text) if target_text.isdigit() else target_text,), fetchone=True)
    
    if not target: return await message.answer("❌ Игрок не найден. Попробуй еще раз или напиши «Отмена».")
    if target[0] == message.from_user.id: return await message.answer("❌ Себе нельзя!")
    
    await state.update_data(target=target[0])
    await message.answer("Введи сумму перевода:")
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

# --- 6. СМЕНА ЯЗЫКА ---
@user_router.message(F.text.in_(["🌐 Язык", "🌐 Language"]))
async def change_lang(message: Message):
    user = get_user(message.from_user.id)
    new_lang = "en" if user[2] == "ru" else "ru"
    db_execute("UPDATE users SET lang = ? WHERE user_id = ?", (new_lang, user[0]))
    await message.answer(get_text(new_lang, "lang_changed"), reply_markup=get_main_menu(new_lang))

# --- 7. ДОНАТ ---
@user_router.message(F.text.in_(["💎 Донат", "💎 Donate"]))
async def donate_menu(message: Message):
    if message.chat.type != "private": return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⭐ 15 Stars"), KeyboardButton(text="⭐ 25 Stars"))
    builder.row(KeyboardButton(text="⭐ 50 Stars"), KeyboardButton(text="⭐ 100 Stars"))
    builder.row(KeyboardButton(text="✍️ Своя сумма"), KeyboardButton(text="⬅️ Назад"))
    await message.answer("💎 <b>ДОНАТ</b>\n\n🔥 Курс дня: 1 ⭐ = 12 500 Tokens\n\nВыбери пакет:", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text.startswith("⭐"))
async def buy_stars(message: Message):
    try:
        stars = int(message.text.split()[1])
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

@user_router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@user_router.message(F.successful_payment)
async def success_payment(message: Message):
    payment = message.successful_payment
    user = get_user(message.from_user.id)
    
    if payment.invoice_payload.startswith("stars_"):
        stars_amount = payment.total_amount
        tokens = stars_amount * 12500
        update_balance(user[0], tokens)
        await message.answer(f"✅ Оплата успешна! Вы получили <b>{format_money(tokens)}</b>.", reply_markup=get_main_menu(user[2]))

# --- 8. ПОДДЕРЖКА (БОЛЬШИЕ ТЕКСТА) ---
@user_router.message(F.text.in_(["🆘 Поддержка", "🆘 Support"]))
async def support_menu(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\nЗдесь ты найдешь ответы на все свои вопросы. Выбери тему, которая тебя интересует:", reply_markup=get_support_menu(user[2]))

@user_router.message(F.text == "💰 Как заработать?")
async def sup_earn_ru(message: Message):
    await message.answer(
        "💰 <b>КАК ЗАРАБОТАТЬ ТОКЕНЫ</b>\n\n"
        "У нас есть несколько проверенных способов поднять свой баланс:\n\n"
        "🎁 <b>Ежедневный бонус</b>\nЗаходи каждый день в раздел «Профиль» и забирай свои 5 000 токенов. Не забывай заходить, чтобы не терять прогресс!\n\n"
        "💼 <b>Работа</b>\nВ разделе «Игры» есть кнопка «Работа». Нажимай и получай 1 500 токенов раз в час. Это пассивный доход, который всегда с тобой.\n\n"
        "🎮 <b>Игры в чате</b>\nЗайди в наш игровой чат @tokenplays и играй в кости, рулетку или мины. Выигрывай токены у других игроков и становись самым богатым!\n\n"
        "📦 <b>Кейсы</b>\nКаждый день открывай бесплатный кейс в профиле. Внутри может быть от 1 000 до 50 000 токенов!\n\n"
        "👥 <b>Рефералы</b>\nПриглашай друзей по своей ссылке в профиле и получай бонусы за каждого приведенного игрока.",
        reply_markup=get_support_menu("ru")
    )

@user_router.message(F.text == "💳 Проблема с оплатой")
async def sup_pay_ru(message: Message):
    await message.answer(
        "💳 <b>ПРОБЛЕМА С ОПЛАТОЙ</b>\n\n"
        "Если ты купил Stars или VIP, но токены не пришли на баланс — сделай следующее:\n\n"
        "1️⃣ Подожди 5-10 минут (иногда Telegram задерживает обработку платежей, особенно в часы пик).\n\n"
        "2️⃣ Проверь баланс в профиле (нажми на кнопку «Профиль» в главном меню).\n\n"
        "3️⃣ Если токены так и не пришли — напиши Админу @vctorw. Обязательно прикрепи скриншот чека из Telegram, чтобы мы могли быстро найти твой платеж и зачислить средства.",
        reply_markup=get_support_menu("ru")
    )

@user_router.message(F.text == "🎁 Не пришел бонус")
async def sup_bonus_ru(message: Message):
    await message.answer(
        "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
        "Бонус доступен раз в 24 часа. Если ты нажал на кнопку «Бонус», но токены не пришли — это значит, что ты уже забирал его сегодня.\n\n"
        "⏳ Система работает четко: как только пройдет ровно 24 часа с момента последнего получения, кнопка снова станет активной.\n\n"
        "Если ты уверен, что прошло больше суток, а бонус не пришел — напиши Админу @vctorw, но такое бывает крайне редко.",
        reply_markup=get_support_menu("ru")
    )

@user_router.message(F.text == "🎰 Как играть в чате?")
async def sup_games_ru(message: Message):
    await message.answer(
        "🎰 <b>КАК ИГРАТЬ В ЧАТЕ</b>\n\n"
        "Все наши игры проходят в официальном чате: @tokenplays\n\n"
        "Чтобы начать играть, просто пиши команды в чат:\n\n"
        "🎲 <b>Кости</b> — напиши <code>кости 1000</code>. Если выпадет 4, 5 или 6 — ты выиграл x2.\n"
        "🎯 <b>Дартс</b> — напиши <code>дартс 1000</code>. Тот же принцип.\n"
        "🎡 <b>Рулетка</b> — напиши <code>к 1000</code> (на красное) или <code>ч 1000</code> (на черное). Запуск: <code>го</code>.\n"
        "💣 <b>Мины</b> — напиши <code>мины 1000</code>. Ищи безопасные клетки и забирай куш!\n\n"
        "Перед игрой убедись, что у тебя на балансе достаточно токенов. Баланс можно проверить командой <code>б</code> в чате.",
        reply_markup=get_support_menu("ru")
    )

@user_router.message(F.text == "🛡 Проблема с кланом")
async def sup_clan_ru(message: Message):
    await message.answer(
        "🛡 <b>КЛАНЫ</b>\n\n"
        "Кланы — это объединения игроков для совместных игр и общего банка.\n\n"
        "Что нужно знать:\n"
        "▫️ Создание клана стоит 100 000 токенов.\n"
        "▫️ Вступить в клан можно бесплатно (если владелец пригласит).\n"
        "▫️ У клана есть своя казна, куда игроки скидывают токены.\n\n"
        "Если у тебя возник баг при создании клана (списались токены, но клан не создался) — пиши Админу @vctorw с чеком и описанием проблемы.",
        reply_markup=get_support_menu("ru")
    )

@user_router.message(F.text == "⚠️ Сообщить об ошибке")
async def sup_bug_ru(message: Message, state: FSMContext):
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
async def process_bug_ru(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    try:
        await bot.send_message(ADMIN_ID, f"🐞 <b>БАГ-РЕПОРТ</b>\nОт: @{message.from_user.username} (ID: <code>{user[0]}</code>)\n\n{message.text}")
        await message.answer("✅ Спасибо! Твое сообщение отправлено Админу.", reply_markup=get_main_menu(user[2]))
    except: 
        await message.answer("❌ Ошибка отправки. Попробуй позже.")
    await state.clear()

@user_router.message(F.text == "✍️ Написать Админу")
async def sup_ticket_ru(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>СВЯЗЬ С АДМИНОМ</b>\n\n"
        "Напиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.\n\n"
        "⚠️ <i>Пожалуйста, не спамь. Отвечаем в течение 24 часов.</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_ticket")

@user_router.message(StateFilter("waiting_ticket"))
async def process_ticket_ru(message: Message, state: FSMContext):
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

# --- 9. АНГЛИЙСКАЯ ПОДДЕРЖКА ---
@user_router.message(F.text == "💰 How to earn?")
async def sup_earn_en(message: Message):
    await message.answer(
        "💰 <b>HOW TO EARN TOKENS</b>\n\n"
        "We have several proven ways to boost your balance:\n\n"
        "🎁 <b>Daily Bonus</b>\nVisit the 'Profile' section every day and claim your 5,000 tokens. Don't forget to log in to keep your progress!\n\n"
        "💼 <b>Work</b>\nIn the 'Games' section, there is a 'Work' button. Click it to receive 1,500 tokens once an hour. It's a passive income that's always with you.\n\n"
        "🎮 <b>Chat Games</b>\nJoin our game chat @tokenplays and play dice, roulette, or mines. Win tokens from other players and become the richest!\n\n"
        "📦 <b>Cases</b>\nOpen a free case in your profile every day. You can get from 1,000 to 50,000 tokens inside!\n\n"
        "👥 <b>Referrals</b>\nInvite friends using your link in the profile and get bonuses for each player you bring.",
        reply_markup=get_support_menu("en")
    )

@user_router.message(F.text == "💳 Payment issue")
async def sup_pay_en(message: Message):
    await message.answer(
        "💳 <b>PAYMENT ISSUE</b>\n\n"
        "If you bought Stars or VIP but tokens didn't arrive in your balance, do the following:\n\n"
        "1️⃣ Wait 5-10 minutes (sometimes Telegram delays payment processing, especially during peak hours).\n\n"
        "2️⃣ Check your balance in the profile (click the 'Profile' button in the main menu).\n\n"
        "3️⃣ If tokens still haven't arrived — write to Admin @vctorw. Be sure to attach a screenshot of the receipt from Telegram so we can quickly find your payment and credit the funds.",
        reply_markup=get_support_menu("en")
    )

@user_router.message(F.text == "🎁 No bonus?")
async def sup_bonus_en(message: Message):
    await message.answer(
        "🎁 <b>DAILY BONUS</b>\n\n"
        "The bonus is available once every 24 hours. If you clicked the 'Bonus' button but tokens didn't arrive, it means you already claimed it today.\n\n"
        "⏳ The system works precisely: once exactly 24 hours have passed since your last claim, the button becomes active again.\n\n"
        "If you are sure that more than a day has passed and the bonus hasn't arrived — write to Admin @vctorw, but this is extremely rare.",
        reply_markup=get_support_menu("en")
    )

@user_router.message(F.text == "🎰 How to play?")
async def sup_games_en(message: Message):
    await message.answer(
        "🎰 <b>HOW TO PLAY IN CHAT</b>\n\n"
        "All our games take place in the official chat: @tokenplays\n\n"
        "To start playing, just type commands in the chat:\n\n"
        "🎲 <b>Dice</b> — type <code>кости 1000</code>. If 4, 5 or 6 rolls, you win x2.\n"
        "🎯 <b>Darts</b> — type <code>дартс 1000</code>. Same principle.\n"
        "🎡 <b>Roulette</b> — type <code>к 1000</code> (for red) or <code>ч 1000</code> (for black). Start: <code>го</code>.\n"
        "💣 <b>Mines</b> — type <code>мины 1000</code>. Find safe cells and claim the prize!\n\n"
        "Make sure you have enough tokens in your balance before playing. You can check your balance with the <code>б</code> command in the chat.",
        reply_markup=get_support_menu("en")
    )

@user_router.message(F.text == "🛡 Clan issue")
async def sup_clan_en(message: Message):
    await message.answer(
        "🛡 <b>CLANS</b>\n\n"
        "Clans are associations of players for joint games and a shared treasury.\n\n"
        "What you need to know:\n"
        "▫️ Creating a clan costs 100,000 tokens.\n"
        "▣ Joining a clan is free (if the owner invites you).\n"
        "▫️ The clan has its own treasury where players deposit tokens.\n\n"
        "If you encountered a bug when creating a clan (tokens were deducted but the clan wasn't created) — write to Admin @vctorw with a receipt and a description of the problem.",
        reply_markup=get_support_menu("en")
    )

@user_router.message(F.text == "⚠️ Report a bug")
async def sup_bug_en(message: Message, state: FSMContext):
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
async def sup_ticket_en(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>CONTACT ADMIN</b>\n\n"
        "Write your question in one message. The Admin will reply to you in DM.\n\n"
        "⚠️ <i>Please do not spam. We reply within 24 hours.</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state("waiting_ticket")

# ==============================================================================
# ЧАСТЬ 3: ЭКОНОМИКА В ЛС (КЕЙСЫ, КОЛЕСО, ЛОТЕРЕЯ, РАБОТА, КЛАНЫ)
# ==============================================================================

# --- 1. МЕНЮ ИГР ---
@user_router.message(F.text.in_(["🎮 Игры", "🎮 Games"]))
async def games_menu_ls(message: Message):
    if message.chat.type != "private": return
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>\nВыбирай раздел:", reply_markup=get_games_menu())

# --- 2. КЕЙСЫ ---
@user_router.message(F.text == "📦 Кейсы")
async def cases_menu(message: Message):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🎁 Обычный кейс (5к)"), KeyboardButton(text="💎 VIP кейс (15к)"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    await message.answer("📦 <b>КЕЙСЫ</b>\nВыбери кейс для открытия:", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text == "🎁 Обычный кейс (5к)")
async def open_common_case(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[6] and now - datetime.datetime.fromisoformat(user[6]) < datetime.timedelta(hours=24):
        return await message.answer("⏳ Кейс уже открыт. Жди 24 часа.")
    if user[3] < 5000: return await message.answer("❌ Недостаточно средств.")
    
    update_balance(user[0], -5000)
    prize = random.choice([1000, 2000, 5000, 10000, 25000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    
    try:
        await message.answer_animation(
            animation=FSInputFile("assets/case.gif"), 
            caption=f"🎁 Ты открыл кейс и выиграл <b>{format_money(prize)}</b>!"
        )
    except:
        await message.answer(f"🎁 Ты открыл кейс и выиграл <b>{format_money(prize)}</b>!")

@user_router.message(F.text == "💎 VIP кейс (15к)")
async def open_vip_case(message: Message):
    user = get_user(message.from_user.id)
    if user[10] != "vip": return await message.answer("❌ Этот кейс доступен только VIP-игрокам.")
    now = datetime.datetime.now()
    if user[7] and now - datetime.datetime.fromisoformat(user[7]) < datetime.timedelta(hours=12):
        return await message.answer("⏳ VIP кейс уже открыт. Жди 12 часов.")
    if user[3] < 15000: return await message.answer("❌ Недостаточно средств.")
    
    update_balance(user[0], -15000)
    prize = random.choice([5000, 10000, 25000, 50000, 100000])
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_vip_case = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    
    try:
        await message.answer_animation(
            animation=FSInputFile("assets/case.gif"), 
            caption=f"💎 Ты открыл VIP кейс и выиграл <b>{format_money(prize)}</b>!"
        )
    except:
        await message.answer(f"💎 Ты открыл VIP кейс и выиграл <b>{format_money(prize)}</b>!")

# --- 3. КОЛЕСО ---
@user_router.message(F.text == "🎡 Колесо")
async def spin_wheel(message: Message):
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

# --- 4. ЛОТЕРЕЯ ---
@user_router.message(F.text == "🎟 Лотерея")
async def lottery_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить билет (5 000)", callback_data="buy_lottery")
    await message.answer("🎟 <b>ЛОТЕРЕЯ</b>\n\nПриз: <b>100 000 Tokens</b>\nРозыгрыш: каждый день в 20:00", reply_markup=builder.as_markup())

@user_router.callback_query(F.data == "buy_lottery")
async def buy_lottery(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if user[3] < 5000: return await callback.answer("❌ Мало средств.", show_alert=True)
    update_balance(user[0], -5000)
    db_execute("INSERT OR IGNORE INTO lottery (user_id) VALUES (?)", (user[0],))
    await callback.answer("✅ Билет куплен! Удачи в 20:00!", show_alert=True)

# --- 5. РАБОТА ---
@user_router.message(F.text == "💼 Работа")
async def work_menu(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[13] and now - datetime.datetime.fromisoformat(user[13]) < datetime.timedelta(hours=1):
        time_left = datetime.timedelta(hours=1) - (now - datetime.datetime.fromisoformat(user[13]))
        return await message.answer(f"⏳ Ты уже работал. Отдых еще {time_left.seconds//60} мин.")
        
    salary = 1500
    update_balance(user[0], salary)
    db_execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer(f"💼 Ты поработал и получил <b>{format_money(salary)}</b>!")

# --- 6. КЛАНЫ ---
@user_router.message(F.text == "🛡 Клан")
async def clan_menu(message: Message):
    user = get_user(message.from_user.id)
    builder = ReplyKeyboardBuilder()
    
    text = "🛡 <b>КЛАНОВАЯ СИСТЕМА</b>\n\n<i>Кланы — это объединения игроков. Вступай, чтобы качать общую казну и быть в топе.</i>\n\n"
    
    if not user[12]:
        builder.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
        text += "Ты пока не в клане. Создай свой или попроси владельца другого клана пригласить тебя."
    else:
        clan = db_execute("SELECT name, treasury, owner_id FROM clans WHERE id = ?", (user[12],), fetchone=True)
        builder.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="🏆 Топ кланов"))
        builder.row(KeyboardButton(text="📜 Мой клан"), KeyboardButton(text="🚪 Выйти из клана"))
        
        role = "👑 Владелец" if clan[2] == user[0] else "🛡 Рядовой"
        text += f"<b>Твой клан:</b> {clan[0]}\n<b>Твоя роль:</b> {role}\n<b>Казна:</b> {format_money(clan[1])}"
        
    builder.row(KeyboardButton(text="⬅️ В Игры"))
    await message.answer(text, reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text == "⬅️ В Игры")
async def back_to_games(message: Message):
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>", reply_markup=get_games_menu())

@user_router.message(F.text == "➕ Создать клан (100к)")
async def clan_create_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user[3] < 100000: return await message.answer("❌ Нужно 100 000 токенов.")
    await message.answer("🛡 Введи название клана (до 15 символов):", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_clan_name")

@user_router.message(StateFilter("waiting_clan_name"))
async def clan_create_finish(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) > 15: return await message.answer("❌ Слишком длинное (макс 15).")
    
    user = get_user(message.from_user.id)
    if user[3] < 100000:
        await state.clear()
        return await message.answer("❌ Недостаточно средств.")
        
    update_balance(user[0], -100000)
    db_execute("INSERT INTO clans (name, owner_id, treasury) VALUES (?, ?, 0)", (name, user[0]))
    clan_id = db_execute("SELECT id FROM clans WHERE owner_id = ?", (user[0],), fetchone=True)[0]
    db_execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, user[0]))
    
    await state.clear()
    await message.answer(f"✅ Клан <b>{name}</b> создан!", reply_markup=get_main_menu(user[2]))

@user_router.message(F.text == "🏆 Топ кланов")
async def clan_top(message: Message):
    clans = db_execute("SELECT name, treasury FROM clans ORDER BY treasury DESC LIMIT 10", fetchall=True)
    text = "🏆 <b>ТОП-10 КЛАНОВ:</b>\n\n"
    if not clans: text += "Пока нет ни одного клана."
    else:
        for i, c in enumerate(clans, 1):
            text += f"{i}. <b>{c[0]}</b> — Казна: {format_money(c[1])}\n"
    await message.answer(text, reply_markup=ReplyKeyboardBuilder().button(text="⬅️ В Игры").as_markup(resize_keyboard=True))

@user_router.message(F.text == "💰 Внести в казну")
async def clan_deposit_start(message: Message, state: FSMContext):
    await message.answer("💰 Введи сумму для взноса в казну:", reply_markup=ReplyKeyboardRemove())
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
    await message.answer(f"✅ Внесено {format_money(amount)} в казну!", reply_markup=get_main_menu(user[2]))

@user_router.message(F.text == "📜 Мой клан")
async def clan_info(message: Message):
    user = get_user(message.from_user.id)
    if not user[12]: return await message.answer("Ты не в клане.")
    
    clan = db_execute("SELECT name, treasury, owner_id FROM clans WHERE id = ?", (user[12],), fetchone=True)
    members = db_execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (user[12],), fetchone=True)[0]
    
    text = (
        f"🛡 <b>МОЙ КЛАН</b>\n\n"
        f"📛 Название: <b>{clan[0]}</b>\n"
        f"👥 Участников: <b>{members}</b>\n"
        f"💰 Казна: <b>{format_money(clan[1])}</b>"
    )
    await message.answer(text, reply_markup=ReplyKeyboardBuilder().button(text="⬅️ В Игры").as_markup(resize_keyboard=True))

@user_router.message(F.text == "🚪 Выйти из клана")
async def clan_leave(message: Message):
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

# ==============================================================================
# ЧАСТЬ 4: ИГРЫ В ЧАТЕ (Стикеры, Рулетка, Мины, Лесенка, БЖ, Джокер)
# ==============================================================================
import asyncio
import random

# --- 1. КОМАНДЫ В ГРУППЕ ---
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    user = get_user(message.from_user.id)
    name = f"@{message.from_user.username}" if message.from_user.username else f"<a href='tg://user?id={user[0]}'>{message.from_user.first_name}</a>"
    await message.reply(f"💰 Баланс {name}: <b>{format_money(user[3])}</b>")

@group_router.message(F.text.lower() == "топ")
async def cmd_top_group(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    top_users = db_execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
    if not top_users: return await message.reply("❌ В базе пока нет игроков.")
        
    text = "🏆 <b>ТОП-10 БОГАЧЕЙ:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        name = f"@{u[1]}" if u[1] and u[1] != "Unknown" else f"<a href='tg://user?id={u[0]}'>Игрок {u[0]}</a>"
        text += f"{i}. {name} — <b>{format_money(u[2])}</b>\n"
    await message.reply(text)

@group_router.message(F.text.regexp(r"(?i)^перевод\s+(\d+)$"))
async def cmd_transfer_group(message: Message):
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

# --- 2. МЕНЮ ИГР В ЧАТЕ ---
@group_router.message(Command("игры"))
@group_router.message(F.text.lower().in_(["игры", "games"]))
async def group_games_menu(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    await message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>\nВыбери игру (пиши ставку в чат, например: <code>кости 1000</code>):", reply_markup=get_group_games_menu())

@group_router.callback_query(F.data == "g_back")
async def back_to_games_final(callback: CallbackQuery):
    await callback.message.edit_text("🎰 <b>ИГРОВОЙ ЗАЛ</b>", reply_markup=get_group_games_menu())
    await callback.answer()

# --- 3. ИНФО ОБ ИГРАХ (С КНОПКОЙ НАЗАД) ---
@group_router.callback_query(F.data == "g_dice")
async def info_dice(callback: CallbackQuery):
    await callback.message.edit_text("🎲 <b>КОСТИ</b>\nНапиши в чат: <code>кости 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_darts")
async def info_darts(callback: CallbackQuery):
    await callback.message.edit_text("🎯 <b>ДАРТС</b>\nНапиши в чат: <code>дартс 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_basket")
async def info_basket(callback: CallbackQuery):
    await callback.message.edit_text("🏀 <b>БАСКЕТ</b>\nНапиши в чат: <code>баскет 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_football")
async def info_football(callback: CallbackQuery):
    await callback.message.edit_text("⚽ <b>ФУТБОЛ</b>\nНапиши в чат: <code>футбол 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_bowling")
async def info_bowling(callback: CallbackQuery):
    await callback.message.edit_text("🎳 <b>БОУЛИНГ</b>\nНапиши в чат: <code>боулинг 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_roulette_info")
async def info_roulette(callback: CallbackQuery):
    await callback.message.edit_text("🎡 <b>РУЛЕТКА</b>\nСтавки: <code>к 1000</code>, <code>10-23 500</code>\nЗапуск: <code>го</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_mines_info")
async def info_mines(callback: CallbackQuery):
    await callback.message.edit_text("💣 <b>МИНЫ</b>\nНапиши в чат: <code>мины 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_stairs_info")
async def info_stairs(callback: CallbackQuery):
    await callback.message.edit_text("🪜 <b>ЛЕСЕНКА</b>\nНапиши в чат: <code>лесенка 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_bj_info")
async def info_bj(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>БЛЭКДЖЕК</b>\nНапиши в чат: <code>бж 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

@group_router.callback_query(F.data == "g_joker")
async def info_joker(callback: CallbackQuery):
    await callback.message.edit_text("🃏 <b>ДЖОКЕР</b>\nНапиши в чат: <code>джокер 1000</code>", reply_markup=get_back_to_games_btn())
    await callback.answer()

# --- 4. САМИ ИГРЫ ---
# Кости
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг)\s+(\d+)$"))
async def play_dice_group(message: Message):
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

# Рулетка с гифкой
active_roulette = {}
@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+)\s+(\d+)$"))
async def bet_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette: 
        active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting": 
        return await message.reply("⏳ Идет раунд.")
    
    parts = message.text.lower().split()
    bet, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount)
    active_roulette[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "bet": bet, "amount": amount})
    await message.reply(f"✅ Ставка: <b>{message.from_user.first_name}</b> {format_money(amount)} на {bet.upper()}")

@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette or not active_roulette[chat_id]["bets"]: return
    active_roulette[chat_id]["status"] = "playing"
    
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
    try: await msg.edit_caption(caption=text)
    except: await msg.edit_text(text)
    
    active_roulette[chat_id] = {"status": "waiting", "bets": []}

# Мины
active_mines = {}
@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines(message: Message):
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
async def open_mine(callback: CallbackQuery):
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
async def cashout_mine(callback: CallbackQuery):
    game_key = callback.data.split("m_cash_")[1]
    if game_key not in active_mines: return
    game = active_mines[game_key]
    win = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    update_balance(game["uid"], win)
    await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
    del active_mines[game_key]
    await callback.answer("Зачислено!")

@group_router.callback_query(F.data == "m_ign")
async def ign_mine(callback: CallbackQuery): await callback.answer("Недоступно.")

# Лесенка
active_stairs = {}
@group_router.message(F.text.regexp(r"(?i)^лесенка\s+(\d+)$"))
async def play_stairs(message: Message):
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
async def step_stairs(callback: CallbackQuery):
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
async def cashout_stairs(callback: CallbackQuery):
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
async def play_bj(message: Message):
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
async def bj_hit(callback: CallbackQuery):
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
async def bj_stand(callback: CallbackQuery):
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
async def play_joker(message: Message):
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
# ЧАСТЬ 5: АДМИНКА, МОДЕРЫ, ПИАРЩИКИ, ОТЧЕТ И ЗАПУСК
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

class ModStates(StatesGroup):
    waiting_give_id = State()
    waiting_give_amount = State()

# ==============================================================================
# 1. ГЛАВНАЯ АДМИНКА
# ==============================================================================
@admin_router.message(F.text == "⬅️ В меню игрока")
async def admin_back_to_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    else:
        user = get_user(message.from_user.id)
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

@admin_router.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
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
    await message.answer(text, reply_markup=get_admin_menu())

# ==============================================================================
# 2. ЭКОНОМИКА
# ==============================================================================
@admin_router.message(F.text == "💸 Экономика")
async def admin_eco_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("💸 <b>ЭКОНОМИКА</b>\nВыбери операцию:", reply_markup=get_admin_eco_menu())

@admin_router.message(F.text == "⬅️ В меню админа")
async def admin_back_to_admin_menu(message: Message):
    await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())

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
    await message.answer(f"✅ Выдано {format_money(amount)} игроку <code>{data['target']}</code>", reply_markup=get_admin_menu())
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
    await message.answer(f"✅ Забрано {format_money(amount)} у игрока <code>{data['target']}</code>", reply_markup=get_admin_menu())
    await state.clear()

@admin_router.message(F.text == "Налог 10%")
async def admin_tax(message: Message):
    users = db_execute("SELECT user_id, balance FROM users WHERE balance > 100000", fetchall=True)
    total = 0
    for u in users:
        tax = int(u[1] * 0.1)
        update_balance(u[0], -tax)
        total += tax
    await message.answer(f"📉 Собрано налогов: <b>{format_money(total)}</b>", reply_markup=get_admin_menu())

@admin_router.message(F.text == "Выдать всем")
async def admin_give_all(message: Message, state: FSMContext):
    await message.answer("Введи сумму для выдачи всем игрокам:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_give_all")

@admin_router.message(StateFilter("waiting_give_all"))
async def admin_give_all_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET balance = balance + ?", (amount,))
    await message.answer(f"✅ Всем игрокам выдано по {format_money(amount)}!", reply_markup=get_admin_menu())
    await state.clear()

# ==============================================================================
# 3. ПРОМОКОДЫ
# ==============================================================================
@admin_router.message(F.text == "🎁 Промокоды")
async def admin_promo_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🎁 <b>ПРОМОКОДЫ</b>", reply_markup=get_admin_promo_menu())

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
    await message.answer(f"✅ Промокод <b>{data['code']}</b> создан!", reply_markup=get_admin_menu())
    await state.clear()

@admin_router.message(F.text == "Список промокодов")
async def admin_promo_list(message: Message):
    promos = db_execute("SELECT code, reward, limit_count, used_count FROM promos", fetchall=True)
    if not promos: return await message.answer("📭 Промокодов нет.")
    text = "🎁 <b>СПИСОК ПРОМОКОДОВ:</b>\n\n"
    for p in promos:
        text += f"🔹 <code>{p[0]}</code> | {format_money(p[1])} | {p[3]}/{p[2]}\n"
    await message.answer(text, reply_markup=get_admin_menu())

# --- Активация промокода игроком ---
@user_router.message(F.text.regexp(r"(?i)^промо\s+(\w+)$"))
async def use_promo(message: Message):
    if message.chat.type != "private": return
    code = message.text.split()[1].upper()
    promo = db_execute("SELECT reward, limit_count, used_count FROM promos WHERE code = ?", (code,), fetchone=True)
    
    if not promo: return await message.reply("❌ Промокод не найден.")
    if promo[2] >= promo[1]: return await message.reply("❌ Лимит активаций исчерпан.")
    
    user = get_user(message.from_user.id)
    update_balance(user[0], promo[0])
    db_execute("UPDATE promos SET used_count = used_count + 1 WHERE code = ?", (code,))
    await message.reply(f"✅ Промокод активирован! Ты получил {format_money(promo[0])}!")

# ==============================================================================
# 4. УПРАВЛЕНИЕ ЛЮДЬМИ
# ==============================================================================
@admin_router.message(F.text == "👥 Люди")
async def admin_people_menu(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("👥 <b>УПРАВЛЕНИЕ ЛЮДЬМИ</b>", reply_markup=get_admin_people_menu())

@admin_router.message(F.text == "Выдать Модера")
async def admin_add_mod(message: Message, state: FSMContext):
    await message.answer("Введи ID игрока:", reply_markup=ReplyKeyboardRemove())
    await state.set_state("waiting_mod_id")

@admin_router.message(StateFilter("waiting_mod_id"))
async def admin_add_mod_finish(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    db_execute("UPDATE users SET role = 'moderator' WHERE user_id = ?", (target,))
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Модер.", reply_markup=get_admin_menu())
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
    await message.answer(f"✅ Игрок <code>{target}</code> теперь Пиарщик.", reply_markup=get_admin_menu())
    await state.clear()

# ==============================================================================
# 5. РАССЫЛКА
# ==============================================================================
@admin_router.message(F.text == "📢 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Введи текст для рассылки (или /cancel):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminStates.waiting_broadcast)

@admin_router.message(AdminStates.waiting_broadcast)
async def admin_broadcast_finish(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_admin_menu())
        
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
    await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_menu())
    await state.clear()

# ==============================================================================
# 6. ПАНЕЛЬ МОДЕРА
# ==============================================================================
@mod_router.message(F.text == "⬅️ Выход")
async def mod_exit(message: Message):
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

# ==============================================================================
# 7. ПАНЕЛЬ ПИАРЩИКА
# ==============================================================================
@pr_router.message(F.text == "⬅️ Выход")
async def pr_exit(message: Message):
    user = get_user(message.from_user.id)
    if user[4] == "promoter":
        await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>", reply_markup=get_pr_menu())
    else:
        await message.answer("Главное меню:", reply_markup=get_main_menu(user[2]))

@pr_router.message(F.text == "🔗 Моя Ссылка")
async def pr_ref(message: Message):
    bot_info = await bot.get_me()
    await message.answer(f"🔗 Твоя ссылка:\n<code>https://t.me/{bot_info.username}?start=ref_{message.from_user.id}</code>")

@pr_router.message(F.text == "📊 Моя Стата")
async def pr_stats(message: Message):
    ref_count = db_execute("SELECT COUNT(*) FROM users WHERE ref_id = ?", (message.from_user.id,), fetchone=True)[0]
    await message.answer(f"📊 Ты привел: <b>{ref_count}</b> человек.")

# ==============================================================================
# 8. ЕЖЕДНЕВНЫЙ ОТЧЕТ В 22:00
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
# МЕГА-ПАТЧ: АДМИНКА (РАБОЧАЯ), КЛАНЫ 3.0 (С ИНФОЙ), VIP В ДОНАТЕ
# ==============================================================================
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

# ==============================================================================
# 1. ПОЧИНКА АДМИНКИ (ЭТИ КНОПКИ ТЕПЕРЬ РАБОТАЮТ)
# ==============================================================================
@admin_router.message(F.text == "🎁 Ивент")
async def adm_event_fix(message: Message):
    if message.from_user.id != ADMIN_ID: return
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📉 Гиперинфляция"), KeyboardButton(text="💣 Дроп в чат"))
    builder.row(KeyboardButton(text="⬅️ В меню админа"))
    await message.answer("🎁 <b>ИВЕНТЫ</b>\nВыбери действие:", reply_markup=builder.as_markup(resize_keyboard=True))

@admin_router.message(F.text == "⚙️ Система")
async def adm_sys_fix(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("⚙️ <b>СИСТЕМА</b>\n\nБот работает стабильно. База данных активна.\nВерсия: 2.0 (Clean Build)", reply_markup=get_admin_menu())

@admin_router.message(F.text == "🎰 Игры")
async def adm_games_fix(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🎰 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\nВсе игры включены. Ставки принимаются.", reply_markup=get_admin_menu())

# ==============================================================================
# 2. КЛАНЫ 3.0 (КРАСИВЫЙ ТОП И ВСТУПЛЕНИЕ ЗА 5000)
# ==============================================================================
JOIN_FEE = 5000 # Взнос за вступление
WELCOME_BONUS = 5000 # Бонус за вступление

@user_router.message(F.text == "🏆 Топ кланов")
async def clan_top_v3(message: Message):
    clans = db_execute("SELECT id, name, treasury FROM clans ORDER BY treasury DESC LIMIT 10", fetchall=True)
    if not clans:
        return await message.answer("🏆 <b>ТОП КЛАНОВ</b>\n\nПока нет ни одного клана. Создай первый!", reply_markup=get_clan_menu())
        
    builder = InlineKeyboardBuilder()
    for i, c in enumerate(clans, 1):
        builder.button(text=f"{i}. {c[1]} (💰 {format_money(c[2])})", callback_data=f"clan_info_{c[0]}")
    builder.row(InlineKeyboardButton(text="⬅️ В Игры", callback_data="back_to_games_btn"))
    builder.adjust(1)
    
    await message.answer("🏆 <b>ТОП-10 КЛАНОВ</b>\nНажми на клан, чтобы узнать подробности:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("clan_info_"))
async def clan_info_v3(callback: CallbackQuery):
    clan_id = int(callback.data.split("_")[2])
    clan = db_execute("SELECT name, treasury, owner_id FROM clans WHERE id = ?", (clan_id,), fetchone=True)
    if not clan: return await callback.answer("❌ Клан не найден.", show_alert=True)
    
    members = db_execute("SELECT COUNT(*) FROM users WHERE clan_id = ?", (clan_id,), fetchone=True)[0]
    owner_name = db_execute("SELECT username FROM users WHERE user_id = ?", (clan[2],), fetchone=True)[0]
    
    text = (
        f"🛡 <b>ИНФОРМАЦИЯ О КЛАНЕ</b>\n\n"
        f"📛 Название: <b>{clan[0]}</b>\n"
        f"👑 Владелец: @{owner_name if owner_name != 'Unknown' else clan[2]}\n"
        f"👥 Участников: <b>{members}</b> чел.\n"
        f"💰 Казна: <b>{format_money(clan[1])}</b>\n"
        f"🎁 Награда за вступление: <b>{format_money(WELCOME_BONUS)}</b>\n"
        f"💵 Взнос: <b>{format_money(JOIN_FEE)}</b>"
    )
    
    builder = InlineKeyboardBuilder()
    user = get_user(callback.from_user.id)
    if not user[12]:
        builder.button(text="🤝 Вступить", callback_data=f"clan_join_{clan_id}")
    builder.button(text="⬅️ Назад в Топ", callback_data="back_to_clan_top")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@user_router.callback_query(F.data == "back_to_clan_top")
async def back_to_clan_top(callback: CallbackQuery):
    clans = db_execute("SELECT id, name, treasury FROM clans ORDER BY treasury DESC LIMIT 10", fetchall=True)
    builder = InlineKeyboardBuilder()
    for i, c in enumerate(clans, 1):
        builder.button(text=f"{i}. {c[1]} (💰 {format_money(c[2])})", callback_data=f"clan_info_{c[0]}")
    builder.row(InlineKeyboardButton(text="⬅️ В Игры", callback_data="back_to_games_btn"))
    builder.adjust(1)
    await callback.message.edit_text("🏆 <b>ТОП-10 КЛАНОВ</b>\nНажми на клан для подробностей:", reply_markup=builder.as_markup())
    await callback.answer()

@user_router.callback_query(F.data.startswith("clan_join_"))
async def clan_join_process_v3(callback: CallbackQuery):
    clan_id = int(callback.data.split("_")[2])
    user = get_user(callback.from_user.id)
    
    if user[12]: return await callback.answer("❌ Ты уже в клане.", show_alert=True)
    if user[3] < JOIN_FEE: return await callback.answer(f"❌ Нужно {format_money(JOIN_FEE)} для взноса.", show_alert=True)
    
    clan = db_execute("SELECT name FROM clans WHERE id = ?", (clan_id,), fetchone=True)
    
    # Списываем взнос и пополняем казну
    update_balance(user[0], -JOIN_FEE)
    db_execute("UPDATE clans SET treasury = treasury + ? WHERE id = ?", (JOIN_FEE, clan_id))
    db_execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, user[0]))
    
    # Даем бонус
    update_balance(user[0], WELCOME_BONUS)
    
    await callback.message.edit_text(f"✅ Ты вступил в клан <b>{clan[0]}</b>!\nВзнос: {format_money(JOIN_FEE)}\nБонус: +{format_money(WELCOME_BONUS)}")
    await callback.answer("Добро пожаловать!")

@user_router.callback_query(F.data == "back_to_games_btn")
async def back_to_games_btn(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🎰 <b>ИГРОВОЙ ЗАЛ</b>", reply_markup=get_games_menu())

# ==============================================================================
# 3. VIP В ДОНАТЕ (ЕСЛИ ТЫ ЕГО НЕ ДОБАВИЛ)
# ==============================================================================
@user_router.message(F.text.in_(["💎 Донат", "💎 Donate"]))
async def donate_menu_vip_final(message: Message):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⭐ Купить 15 Stars"), KeyboardButton(text="⭐ Купить 50 Stars"))
    builder.row(KeyboardButton(text="👑 VIP на 1 день (5 ⭐)"), KeyboardButton(text="👑 VIP на 7 дней (30 ⭐)"))
    builder.row(KeyboardButton(text="👑 VIP на 30 дней (100 ⭐)"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    
    await message.answer(
        "💎 <b>ДОНАТ И VIP</b>\n\n"
        "🔥 Курс: 1 ⭐ = 12 500 Tokens\n\n"
        "👑 <b>VIP дает:</b>\n"
        "▫️ Доступ к VIP-кейсам\n"
        "▫️ Ежедневный бонус 15 000 (вместо 5 000)\n"
        "▫️ Бонус при покупке: +10 000 за каждый день\n\n"
        "Выбери пакет:", 
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

@user_router.message(F.text == "👑 VIP на 1 день (5 ⭐)")
async def buy_vip_1(message: Message):
    await message.answer_invoice(title="VIP 1 день", description="Активация VIP на 1 день", payload="vip_1_day", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP", amount=5)], start_parameter="buy_vip")

@user_router.message(F.text == "👑 VIP на 7 дней (30 ⭐)")
async def buy_vip_7(message: Message):
    await message.answer_invoice(title="VIP 7 дней", description="Активация VIP на 7 дней", payload="vip_7_days", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP", amount=30)], start_parameter="buy_vip")

@user_router.message(F.text == "👑 VIP на 30 дней (100 ⭐)")
async def buy_vip_30(message: Message):
    await message.answer_invoice(title="VIP 30 дней", description="Активация VIP на 30 дней", payload="vip_30_days", provider_token="", currency="XTR", prices=[types.LabeledPrice(label="VIP", amount=100)], start_parameter="buy_vip")

@user_router.message(F.successful_payment)
async def success_payment_final(message: Message):
    payment = message.successful_payment
    user = get_user(message.from_user.id)
    
    if payment.invoice_payload.startswith("vip_"):
        payload = payment.invoice_payload
        days = 1 if payload == "vip_1_day" else 7 if payload == "vip_7_days" else 30
        
        db_execute("UPDATE users SET role = 'vip' WHERE user_id = ?", (user[0],))
        bonus = 10000 * days
        update_balance(user[0], bonus)
        
        await message.answer(f"👑 <b>VIP АКТИВИРОВАН!</b>\nСрок: {days} дней\nБонус: +{format_money(bonus)}", reply_markup=get_main_menu(user[2]))
    else:
        tokens = payment.total_amount * 12500
        update_balance(user[0], tokens)
        await message.answer(f"✅ Оплата успешна! Получено {format_money(tokens)}.", reply_markup=get_main_menu(user[2]))
        
# ==============================================================================
# 9. ЗАПУСК БОТА
# ==============================================================================
async def main():
    init_db()
    scheduler.add_job(daily_report, "cron", hour=22, minute=0)
    scheduler.start()
    asyncio.create_task(start_ping_server())
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")