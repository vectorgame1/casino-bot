# ==============================================================================
# ФИНАЛЬНЫЙ ФАЙЛ БОТА (ВСЁ В ОДНОМ МЕСТЕ)
# ==============================================================================

import asyncio
import logging
import random
import sqlite3
import datetime
import os
import sys
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    LabeledPrice, PreCheckoutQuery, SuccessfulPayment
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==============================================================================
# КОНФИГУРАЦИЯ
# ==============================================================================

BOT_TOKEN = "8636948865:AAHxwsvpuIHQGgsZzifIeWHMYTDWxbWbIyI"
ADMIN_ID = 6403424348
DB_PATH = "database.db"
GROUP_CHAT_LINK = "https://t.me/your_chat_link"

CURRENCY = "Tokens"
START_BONUS = 5000
LOTTERY_TICKET_PRICE = 5000
LOTTERY_PRIZE = 100000
WHEEL_COOLDOWN_HOURS = 12
MOD_SALARY = 50000
PR_SALARY = 50000

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
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
    conn.commit()
    conn.close()
    return result

def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru',
        balance INTEGER DEFAULT 5000, xp INTEGER DEFAULT 0, rank TEXT DEFAULT 'Новичок',
        vip_until TEXT DEFAULT NULL, last_bonus TEXT DEFAULT NULL, streak INTEGER DEFAULT 0,
        last_wheel TEXT DEFAULT NULL, role TEXT DEFAULT 'user', warns INTEGER DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, amount INTEGER, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (user_id INTEGER PRIMARY KEY)""")
    db_execute("""CREATE TABLE IF NOT EXISTS mod_limits (
        user_id INTEGER PRIMARY KEY, given_amount INTEGER DEFAULT 0, last_reset TEXT
    )""")
    logger.info("База данных инициализирована.")

# ==============================================================================
# УТИЛИТЫ
# ==============================================================================

def get_user(user_id):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        db_execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, "Unknown", START_BONUS))
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return user

def update_balance(user_id, amount):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, ?, ?)", 
               (user_id, "balance_change", amount, datetime.datetime.now().isoformat()))

def is_vip(user_id):
    user = get_user(user_id)
    if user[6]:
        return datetime.datetime.fromisoformat(user[6]) > datetime.datetime.now()
    return False

def format_money(amount):
    return f"{amount:,}".replace(",", " ") + " " + CURRENCY

# ==============================================================================
# ЛОКАЛИЗАЦИЯ
# ==============================================================================

TEXTS = {
    "ru": {
        "menu_games": "🎮 Игры", "menu_bal": "💰 Баланс", "menu_prof": "👤 Профиль",
        "menu_donate": "💎 Донат", "menu_help": "🆘 Помощь", "menu_lang": "🌐 Язык",
        "menu_back": "⬅️ Назад", "btn_bonus": "🎁 Бонус", "btn_case": "📦 Кейс",
        "btn_lottery": "🎟 Лотерея", "btn_wheel": "🎡 Колесо", "btn_quests": "📜 Квесты",
        "case_common": "🎁 Обычный кейс", "case_vip": "💎 VIP Кейс",
        "btn_buy_stars": "⭐ Купить Stars", "btn_buy_vip": "👑 Купить VIP", "btn_custom_sum": "✍️ Своя сумма",
        "btn_sup_game": "🎮 Проблема с игрой", "btn_sup_pay": "💳 Вопрос по оплате",
        "btn_sup_ban": "🚫 Бан или мут", "btn_sup_bug": "🐞 Нашёл баг", "btn_sup_own": "✍️ Свой вопрос",
        "btn_admin_players": "👥 Игроки", "btn_admin_stats": "📊 Статистика", "btn_admin_broadcast": "📢 Рассылка",
        "btn_admin_event": "🎁 Ивент", "btn_admin_manage": "🛠 Управление", "btn_admin_report": "📜 Отчет",
        "btn_mod_limit": "📊 Мои лимиты", "btn_mod_clean": "🧹 Очистить", "btn_mod_pin": "📌 Закреп",
        "btn_mod_unban": "🔓 Разбан", "btn_mod_sos": "🚨 SOS", "btn_mod_help": "📖 Хелп",
        "btn_pr_text": "📝 Получить текст", "btn_pr_stats": "📊 Статистика",
        "welcome": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В TOKENS</b>\n\n👋 Привет, {name}!\n👇 Выбери действие:",
        "choose_lang": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В TOKENS</b>\n\n👋 Привет!\nВыбери язык для продолжения 👇\n\n🇬🇧 Hello! Choose language to continue 👇",
        "lang_changed": "✅ Язык изменен на Русский!",
        "profile": "👤 <b>ПРОФИЛЬ</b>\n🎖 Ранг: {rank}\n📊 XP: {xp}\n💰 Баланс: <b>{bal}</b>\n💎 VIP: {vip}",
        "support_title": "🆘 <b>СЛУЖБА ПОДДЕРЖКИ</b>\nВыбери тему:",
        "support_own": "✍️ Напиши свой вопрос. Админ ответит в ЛС.",
        "support_sent": "✅ Отправлено Админу.",
        "sup_game": "🎮 Напишите в чат: @TokensChange", "sup_pay": "💳 Напишите в чат: @TokensChange",
        "sup_ban": "🚫 Напишите Админу: @vctorw", "sup_bug": "🐞 Опишите баг: @TokensChange",
        "vip_why": "👑 <b>VIP СТАТУС</b>\n\n✅ Кэшбэк 5%\n✅ VIP-Кейс (до 500к)\n✅ Значок 💎\n\nВыбери пакет:",
        "games_unavail": "Играй в нашем чате: {link}", "donate_text": "💎 <b>ДОНАТ</b>\nКурс: 1 ⭐ = 7 500 Tokens",
        "help_menu": "🆘 <b>ПОМОЩЬ</b>\nВыбери тему:", "admin_panel": "👑 <b>АДМИН-ПАНЕЛЬ</b>\nВыбери действие:",
        "mod_panel": "🛠 <b>ПАНЕЛЬ МОДЕРА</b>\nВыбери действие:", "pr_panel": "📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>\nВыбери действие:",
    },
    "en": {
        "menu_games": "🎮 Games", "menu_bal": "💰 Balance", "menu_prof": "👤 Profile",
        "menu_donate": "💎 Donate", "menu_help": "🆘 Help", "menu_lang": "🌐 Language",
        "menu_back": "⬅️ Back", "btn_bonus": "🎁 Bonus", "btn_case": "📦 Case",
        "btn_lottery": "🎟 Lottery", "btn_wheel": "🎡 Wheel", "btn_quests": "📜 Quests",
        "case_common": "🎁 Common Case", "case_vip": "💎 VIP Case",
        "btn_buy_stars": "⭐ Buy Stars", "btn_buy_vip": "👑 Buy VIP", "btn_custom_sum": "✍️ Custom amount",
        "btn_sup_game": "🎮 Game issue", "btn_sup_pay": "💳 Payment issue",
        "btn_sup_ban": "🚫 Ban or mute", "btn_sup_bug": "🐞 Found a bug", "btn_sup_own": "✍️ Own question",
        "btn_admin_players": "👥 Players", "btn_admin_stats": "📊 Stats", "btn_admin_broadcast": "📢 Broadcast",
        "btn_admin_event": "🎁 Event", "btn_admin_manage": "🛠 Manage", "btn_admin_report": "📜 Report",
        "btn_mod_limit": "📊 My limits", "btn_mod_clean": "🧹 Clean", "btn_mod_pin": "📌 Pin",
        "btn_mod_unban": "🔓 Unban", "btn_mod_sos": "🚨 SOS", "btn_mod_help": "📖 Help",
        "btn_pr_text": "📝 Get text", "btn_pr_stats": "📊 Stats",
        "welcome": "👑 <b>WELCOME TO TOKENS</b>\n\n👋 Hi, {name}!\n👇 Choose action:",
        "choose_lang": "👑 <b>WELCOME TO TOKENS</b>\n\n👋 Hi!\nChoose language 👇\n\n🇬🇧 Hello! Choose language to continue 👇",
        "lang_changed": "✅ Language changed to English!",
        "profile": "👤 <b>PROFILE</b>\n🎖 Rank: {rank}\n📊 XP: {xp}\n💰 Balance: <b>{bal}</b>\n💎 VIP: {vip}",
        "support_title": "🆘 <b>SUPPORT</b>\nChoose topic:",
        "support_own": "✍️ Write your question. Admin will reply in DM.",
        "support_sent": "✅ Sent to Admin.",
        "sup_game": "🎮 Write to chat: @TokensChange", "sup_pay": "💳 Write to chat: @TokensChange",
        "sup_ban": "🚫 Write to Admin: @vctorw", "sup_bug": "🐞 Describe bug: @TokensChange",
        "vip_why": "👑 <b>VIP STATUS</b>\n\n✅ 5% Cashback\n✅ VIP-Case (up to 500k)\n✅ Badge 💎\n\nChoose package:",
        "games_unavail": "Play in our chat: {link}", "donate_text": "💎 <b>DONATE</b>\nRate: 1 ⭐ = 7 500 Tokens",
        "help_menu": "🆘 <b>HELP</b>\nChoose topic:", "admin_panel": "👑 <b>ADMIN PANEL</b>\nChoose action:",
        "mod_panel": "🛠 <b>MOD PANEL</b>\nChoose action:", "pr_panel": "📢 <b>PROMOTER PANEL</b>\nChoose action:",
    }
}

def get_text(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, "Text not found")
    if kwargs:
        return text.format(**kwargs)
    return text

# ==============================================================================
# КЛАВИАТУРЫ
# ==============================================================================

def get_main_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "menu_games")), KeyboardButton(text=get_text(lang, "menu_bal")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_prof")), KeyboardButton(text=get_text(lang, "menu_donate")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_help")), KeyboardButton(text=get_text(lang, "menu_lang")))
    return builder.as_markup(resize_keyboard=True)

def get_profile_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "btn_bonus")), KeyboardButton(text=get_text(lang, "btn_case")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_lottery")), KeyboardButton(text=get_text(lang, "btn_wheel")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_back")))
    return builder.as_markup(resize_keyboard=True)

def get_donate_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "btn_buy_stars")), KeyboardButton(text=get_text(lang, "btn_buy_vip")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_custom_sum")), KeyboardButton(text=get_text(lang, "menu_back")))
    return builder.as_markup(resize_keyboard=True)

def get_help_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "btn_sup_game")), KeyboardButton(text=get_text(lang, "btn_sup_pay")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_sup_ban")), KeyboardButton(text=get_text(lang, "btn_sup_bug")))
    builder.row(KeyboardButton(text=get_text(lang, "btn_sup_own")), KeyboardButton(text=get_text(lang, "menu_back")))
    return builder.as_markup(resize_keyboard=True)

def get_games_inline(lang):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎡 Рулетка", callback_data="game_roulette")
    builder.button(text="💣 Мины", callback_data="game_mines")
    builder.button(text="🃏 Блэкджек", callback_data="game_blackjack")
    builder.button(text="🎲 Кости", callback_data="game_dice")
    builder.button(text="🏀 Баскет", callback_data="game_basket")
    builder.button(text="⚽ Футбол", callback_data="game_football")
    builder.button(text="🎯 Дартс", callback_data="game_darts")
    builder.button(text="🎳 Боулинг", callback_data="game_bowling")
    builder.button(text="⚔️ Дуэли", callback_data="game_duel")
    builder.button(text="🪙 Монетка", callback_data="game_coin")
    builder.button(text="❌ Закрыть", callback_data="close_games")
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()

# ==============================================================================
# FSM И ОЧИСТКА ЛС
# ==============================================================================

class UserStates(StatesGroup):
    waiting_for_custom_sum = State()
    waiting_for_support = State()

last_messages = {}

async def send_clean(message: Message, text: str, reply_markup=None):
    chat_id = message.chat.id
    if chat_id in last_messages:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_messages[chat_id])
        except Exception:
            pass
    msg = await message.answer(text, reply_markup=reply_markup)
    last_messages[chat_id] = msg.message_id
    return msg

# ==============================================================================
# СТАРТ И ВЫБОР ЯЗЫКА
# ==============================================================================

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    if not user[1] or user[1] == "Unknown":
        builder = InlineKeyboardBuilder()
        builder.button(text="🇷🇺 Русский", callback_data="set_lang_ru")
        builder.button(text="🇬🇧 English", callback_data="set_lang_en")
        await message.answer(get_text("ru", "choose_lang"), reply_markup=builder.as_markup())
        return
    lang = user[2]
    photo_path = "assets/welcome.jpg"
    if os.path.exists(photo_path):
        try:
            await bot.send_photo(chat_id=message.chat.id, photo=types.FSInputFile(photo_path), caption=get_text(lang, "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(lang))
            return
        except Exception:
            pass
    await send_clean(message, get_text(lang, "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(lang))

@user_router.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[-1]
    db_execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, callback.from_user.id))
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(get_text(lang, "welcome", name=callback.from_user.first_name), reply_markup=get_main_menu(lang))
    await callback.answer(get_text(lang, "lang_changed"))

# ==============================================================================
# ПРОФИЛЬ, БАЛАНС, НАЗАД
# ==============================================================================

@user_router.message(F.text.in_([TEXTS["ru"]["menu_lang"], TEXTS["en"]["menu_lang"]]))
async def change_lang_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="set_lang_ru")
    builder.button(text="🇬🇧 English", callback_data="set_lang_en")
    await send_clean(message, get_text(get_user(message.from_user.id)[2], "choose_lang"), reply_markup=builder.as_markup())

@user_router.message(F.text.in_([TEXTS["ru"]["menu_bal"], TEXTS["en"]["menu_bal"]]))
async def show_balance(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, f"💰 <b>{format_money(user[3])}</b>", reply_markup=get_main_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["menu_prof"], TEXTS["en"]["menu_prof"]]))
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    vip_status = "✅" if is_vip(user[0]) else "❌"
    text = get_text(lang, "profile", rank=user[5], xp=user[4], bal=format_money(user[3]), vip=vip_status)
    await send_clean(message, text, reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_([TEXTS["ru"]["menu_back"], TEXTS["en"]["menu_back"]]))
async def go_back(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["menu_games"], TEXTS["en"]["menu_games"]]))
async def games_unavail(message: Message):
    user = get_user(message.from_user.id)
    text = get_text(user[2], "games_unavail", link=GROUP_CHAT_LINK)
    await send_clean(message, text, reply_markup=get_main_menu(user[2]))

# ==============================================================================
# ДОНАТ И VIP
# ==============================================================================

@user_router.message(F.text.in_([TEXTS["ru"]["menu_donate"], TEXTS["en"]["menu_donate"]]))
async def show_donate(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "donate_text"), reply_markup=get_donate_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_buy_stars"], TEXTS["en"]["btn_buy_stars"]]))
async def buy_stars_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="50 ⭐ (375,000)", callback_data="pay_stars_50")
    builder.button(text="100 ⭐ (750,000)", callback_data="pay_stars_100")
    builder.button(text="250 ⭐ (1,875,000)", callback_data="pay_stars_250")
    builder.button(text="500 ⭐ (3,750,000)", callback_data="pay_stars_500")
    await send_clean(message, "Выберите пакет Stars:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("pay_stars_"))
async def process_stars(callback: CallbackQuery):
    stars_amount = int(callback.data.split("_")[-1])
    await callback.message.answer_invoice(title=f"Покупка {stars_amount} Stars", description=f"Пополнение на {format_money(stars_amount * 7500)}", payload=f"stars_{stars_amount}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Stars", amount=stars_amount)], start_parameter="buy_stars")
    await callback.answer()

@user_router.message(F.text.in_([TEXTS["ru"]["btn_buy_vip"], TEXTS["en"]["btn_buy_vip"]]))
async def buy_vip_menu(message: Message):
    user = get_user(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="1 день — 5 ⭐", callback_data="vip_1")
    builder.button(text="1 нед — 30 ⭐", callback_data="vip_7")
    builder.button(text="1 мес — 100 ⭐", callback_data="vip_30")
    builder.button(text="1 год — 1000 ⭐", callback_data="vip_365")
    builder.adjust(2, 2)
    await send_clean(message, get_text(user[2], "vip_why"), reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("vip_"))
async def process_vip(callback: CallbackQuery):
    days = int(callback.data.split("_")[-1])
    stars_price = {1: 5, 7: 30, 30: 100, 365: 1000}[days]
    await callback.message.answer_invoice(title=f"Покупка VIP на {days} дн.", description=f"Активация VIP на {days} дней", payload=f"vip_{days}", provider_token="", currency="XTR", prices=[LabeledPrice(label="VIP", amount=stars_price)], start_parameter="buy_vip")
    await callback.answer()

@user_router.message(F.text.in_([TEXTS["ru"]["btn_custom_sum"], TEXTS["en"]["btn_custom_sum"]]))
async def custom_sum_start(message: Message, state: FSMContext):
    await send_clean(message, "Введите сумму в ⭐:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserStates.waiting_for_custom_sum)

@user_router.message(UserStates.waiting_for_custom_sum)
async def custom_sum_process(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Введите целое число.")
    stars = int(message.text)
    if stars < 1 or stars > 10000: return await message.answer("❌ От 1 до 10000 ⭐.")
    await state.clear()
    await message.answer_invoice(title=f"Покупка {stars} Stars", description=f"Пополнение на {format_money(stars * 7500)}", payload=f"stars_{stars}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Stars", amount=stars)], start_parameter="buy_stars")

@user_router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@user_router.message(F.successful_payment)
async def success_payment(message: Message):
    payment = message.successful_payment
    user = get_user(message.from_user.id)
    lang = user[2]
    if payment.invoice_payload.startswith("vip_"):
        days = int(payment.invoice_payload.split("_")[-1])
        now = datetime.datetime.now()
        current_vip = datetime.datetime.fromisoformat(user[6]) if user[6] and datetime.datetime.fromisoformat(user[6]) > now else now
        new_vip = current_vip + datetime.timedelta(days=days)
        db_execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_vip.isoformat(), user[0]))
        await send_clean(message, f"👑 VIP активирован до {new_vip.strftime('%d.%m.%Y %H:%M')}.", reply_markup=get_main_menu(lang))
    else:
        stars_amount = payment.total_amount
        tokens = stars_amount * 7500
        if is_vip(user[0]):
            cashback = int(tokens * 0.05)
            tokens += cashback
            text = f"✅ Оплата успешна! Вы получили {format_money(tokens)} (включая VIP-кэшбэк 5%: +{format_money(cashback)})."
        else:
            text = f"✅ Оплата успешна! Вы получили {format_money(tokens)}."
        update_balance(user[0], tokens)
        await send_clean(message, text, reply_markup=get_main_menu(lang))

# ==============================================================================
# КЕЙСЫ, КОЛЕСО, ЛОТЕРЕЯ, ПОДДЕРЖКА
# ==============================================================================

@user_router.message(F.text.in_([TEXTS["ru"]["btn_case"], TEXTS["en"]["btn_case"]]))
async def show_cases(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "case_common")), KeyboardButton(text=get_text(lang, "case_vip")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_back")))
    await send_clean(message, "📦 Выберите кейс:", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text.in_([TEXTS["ru"]["case_common"], TEXTS["en"]["case_common"]]))
async def open_common_case(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    if user[3] < 5000: return await message.answer("❌ Недостаточно средств! Кейс стоит 5 000 Tokens.")
    update_balance(user[0], -5000)
    if os.path.exists("assets/case.gif"):
        try: await message.answer_animation(types.FSInputFile("assets/case.gif"))
        except Exception: pass
    prize = random.choice([5000, 10000, 25000])
    update_balance(user[0], prize)
    await send_clean(message, f"🎉 Вы открыли обычный кейс и выиграли {format_money(prize)}!", reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_([TEXTS["ru"]["case_vip"], TEXTS["en"]["case_vip"]]))
async def open_vip_case(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    if not is_vip(user[0]): return await send_clean(message, "❌ У тебя нет VIP, купи в донате!", reply_markup=get_profile_menu(lang))
    if user[3] < 15000: return await message.answer("❌ Недостаточно средств! VIP Кейс стоит 15 000 Tokens.")
    update_balance(user[0], -15000)
    if os.path.exists("assets/vip_case.gif"):
        try: await message.answer_animation(types.FSInputFile("assets/vip_case.gif"))
        except Exception: pass
    prize = random.choice([50000, 100000, 150000, 500000])
    update_balance(user[0], prize)
    await send_clean(message, f"💎 Вы открыли VIP Кейс и выиграли {format_money(prize)}!", reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_wheel"], TEXTS["en"]["btn_wheel"]]))
async def spin_wheel(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    now = datetime.datetime.now()
    if user[9] and now - datetime.datetime.fromisoformat(user[9]) < datetime.timedelta(hours=WHEEL_COOLDOWN_HOURS):
        time_left = datetime.timedelta(hours=WHEEL_COOLDOWN_HOURS) - (now - datetime.datetime.fromisoformat(user[9]))
        return await send_clean(message, f"⏳ Ждите {time_left.seconds//3600} ч.", reply_markup=get_profile_menu(lang))
    await send_clean(message, "🎡 Колесо крутится...", reply_markup=get_profile_menu(lang))
    await asyncio.sleep(2)
    prize = random.choice([0, 5000, 10000, 20000])
    if prize > 0: update_balance(user[0], prize)
    db_execute("UPDATE users SET last_wheel = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await send_clean(message, f"🎉 Выигрыш: {format_money(prize)}" if prize else "😢 Пусто.", reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_lottery"], TEXTS["en"]["btn_lottery"]]))
async def lottery_menu(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    if db_execute("SELECT user_id FROM lottery WHERE user_id = ?", (user[0],), fetchone=True):
        return await send_clean(message, "🎟 Вы уже участвуете. Ждите 20:00.", reply_markup=get_profile_menu(lang))
    if user[3] < LOTTERY_TICKET_PRICE:
        return await send_clean(message, "❌ Недостаточно средств.", reply_markup=get_profile_menu(lang))
    update_balance(user[0], -LOTTERY_TICKET_PRICE)
    db_execute("INSERT INTO lottery (user_id) VALUES (?)", (user[0],))
    await send_clean(message, "🎟 Билет куплен! Удачи в 20:00.", reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_([TEXTS["ru"]["menu_help"], TEXTS["en"]["menu_help"]]))
async def support_menu(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "support_title"), reply_markup=get_help_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_sup_game"], TEXTS["en"]["btn_sup_game"]]))
async def sup_game(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "sup_game"), reply_markup=get_help_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_sup_pay"], TEXTS["en"]["btn_sup_pay"]]))
async def sup_pay(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "sup_pay"), reply_markup=get_help_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_sup_ban"], TEXTS["en"]["btn_sup_ban"]]))
async def sup_ban(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "sup_ban"), reply_markup=get_help_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_sup_bug"], TEXTS["en"]["btn_sup_bug"]]))
async def sup_bug(message: Message):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "sup_bug"), reply_markup=get_help_menu(user[2]))

@user_router.message(F.text.in_([TEXTS["ru"]["btn_sup_own"], TEXTS["en"]["btn_sup_own"]]))
async def sup_own(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await send_clean(message, get_text(user[2], "support_own"), reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserStates.waiting_for_support)

@user_router.message(UserStates.waiting_for_support)
async def sup_own_process(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()
    admin_text = f"📩 <b>Тикет!</b>\nОт: @{message.from_user.username} (ID: <code>{user[0]}</code>)\n\nТекст: {message.text}\n\n<i>Ответьте Reply на это сообщение.</i>"
    try:
        admin_msg = await bot.send_message(ADMIN_ID, admin_text)
        db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, ?, ?)", (user[0], f"support_msg_{admin_msg.message_id}", 0, datetime.datetime.now().isoformat()))
        await send_clean(message, get_text(user[2], "support_sent"), reply_markup=get_main_menu(user[2]))
    except Exception:
        await message.answer("❌ Ошибка отправки.")

@admin_router.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):
    if not message.reply_to_message: return
    admin_msg_id = message.reply_to_message.message_id
    log_entry = db_execute("SELECT user_id FROM logs WHERE action = ?", (f"support_msg_{admin_msg_id}",), fetchone=True)
    if log_entry:
        try:
            await bot.send_message(log_entry[0], f"✉️ <b>Ответ от администрации:</b>\n\n{message.text}")
            await message.reply("✅ Ответ отправлен игроку.")
        except Exception:
            await message.reply("❌ Игрок закрыл ЛС.")
    else:
        await message.reply("❌ Не найден игрок.")

# ==============================================================================
# ИГРЫ В ГРУППАХ
# ==============================================================================

@group_router.callback_query(F.data == "close_games")
async def close_games(callback: CallbackQuery):
    try: await callback.message.delete()
    except Exception: pass
    await callback.answer()

@group_router.message(F.text.lower().in_(["игры", "games", "играть"]))
@group_router.message(Command("игры"))
async def cmd_games_text(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    await message.answer("🎮 <b>Выберите игру:</b>", reply_markup=get_games_inline("ru"))

active_roulette_bets = {}

@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет)\s+(\d+)$"))
async def place_bet_roulette(message: Message):
    text = message.text.lower().split()
    bet_type, amount = text[0], int(text[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Недостаточно средств.")
    chat_id = message.chat.id
    if chat_id not in active_roulette_bets: active_roulette_bets[chat_id] = {}
    active_roulette_bets[chat_id][message.from_user.id] = {"amount": amount, "type": bet_type}
    update_balance(message.from_user.id, -amount)
    await message.reply(f"✅ Ставка {amount} на {bet_type} принята. Жми 'го'!")

@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette_bets or not active_roulette_bets[chat_id]: return
    bets = active_roulette_bets.pop(chat_id)
    active_roulette_bets[chat_id] = {}
    gif_path = "assets/roulette.gif"
    if os.path.exists(gif_path):
        try: msg = await message.answer_animation(types.FSInputFile(gif_path))
        except Exception: msg = await message.answer("🎡 Рулетка крутится...")
    else: msg = await message.answer("🎡 Рулетка крутится...")
    await asyncio.sleep(4)
    result = random.choice(["к", "ч", "з"])
    res_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[result]
    text = f"🎯 Выпало: <b>{res_name}</b>\n\n"
    winners = []
    for u_id, bet in bets.items():
        mult = 0
        if result == bet["type"]: mult = 2
        elif result == "з" and bet["type"] == "з": mult = 14
        elif result == "з" and bet["type"] in ["к", "ч", "красное", "черное", "чет", "нечет"]: mult = 0
        if mult > 0:
            prize = bet["amount"] * mult
            update_balance(u_id, prize)
            winners.append(f"👤 <a href='tg://user?id={u_id}'>{u_id}</a> выиграл {format_money(prize)}")
    text += "\n".join(winners) if winners else "😢 Победителей нет."
    builder = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔄 Повторить", callback_data="r_rep"), InlineKeyboardButton(text="⏫ Удвоить", callback_data="r_dbl"))
    await msg.edit_text(text, reply_markup=builder.as_markup())

@group_router.callback_query(F.data.in_(["r_rep", "r_dbl"]))
async def roulette_repeat(callback: CallbackQuery):
    await callback.answer("Напишите вашу ставку и 'го'!", show_alert=True)

@group_router.message(F.text.regexp(r"(?i)^(кости|баскет|футбол|дартс|боулинг|слот)\s+(\d+)$"))
async def play_simple_games(message: Message):
    parts = message.text.lower().split()
    amount = int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(message.from_user.id, -amount)
    await message.answer(f"🎲 Играем в {parts[0].capitalize()}...")
    await asyncio.sleep(2)
    if random.random() < 0.45:
        update_balance(message.from_user.id, amount * 2)
        await message.reply(f"🎉 Победа! Выиграли {format_money(amount*2)}!")
    else:
        await message.reply("😢 Проиграли.")

@group_router.message(F.text.regexp(r"(?i)^монетка\s+(\d+)(?:\s+(орел|решка))?$"))
async def play_coin(message: Message):
    parts = message.text.lower().split()
    amount = int(parts[1])
    if len(parts) < 3: return await message.reply("❌ Укажи сторону: <code>монетка 100 орел</code>")
    side = parts[2]
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(message.from_user.id, -amount)
    await message.answer("🪙 Монетка...")
    await asyncio.sleep(2)
    res = random.choice(["орел", "решка"])
    if side == res:
        update_balance(message.from_user.id, amount * 2)
        await message.reply(f"🪙 {res}! Выиграли {format_money(amount*2)}!")
    else:
        await message.reply(f"🪙 {res}. Проиграли.")

active_mines = {}

@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(message.from_user.id, -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    mines = random.sample(range(25), 5)
    builder = InlineKeyboardBuilder()
    for i in range(25): builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    msg = await message.reply(f"💣 <b>Мины!</b>\nСтавка: {format_money(amount)}\nИщи 💎", reply_markup=builder.as_markup())
    active_mines[game_key] = {"uid": message.from_user.id, "bet": amount, "mines": mines, "opened": []}

@group_router.callback_query(F.data.startswith("m_"))
async def open_mine(callback: CallbackQuery):
    parts = callback.data.split("_")
    game_key, cell = f"{parts[1]}_{parts[2]}", int(parts[3])
    if game_key not in active_mines: return await callback.answer("Игра окончена.", show_alert=True)
    game = active_mines[game_key]
    if callback.from_user.id != game["uid"]: return await callback.answer("Не твоя игра!", show_alert=True)
    if cell in game["opened"]: return await callback.answer("Уже открыта.", show_alert=True)
    if cell in game["mines"]:
        builder = InlineKeyboardBuilder()
        for i in range(25): builder.button(text="💥" if i in game["mines"] else "💎", callback_data="m_ign")
        builder.adjust(5, 5, 5, 5, 5)
        await callback.message.edit_text(f"💥 <b>БУМ!</b> Вы проиграли {format_money(game['bet'])}.", reply_markup=builder.as_markup())
        del active_mines[game_key]
        return await callback.answer()
    game["opened"].append(cell)
    mult = 1 + (len(game["opened"]) * 0.2)
    win = int(game["bet"] * mult)
    builder = InlineKeyboardBuilder()
    for i in range(25):
        if i in game["opened"]: builder.button(text="💎", callback_data="m_ign")
        else: builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    builder.row(InlineKeyboardButton(text=f"💰 Забрать {format_money(win)}", callback_data=f"m_cash_{game_key}"))
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer(f"Безопасно! Выигрыш: {format_money(win)}")

@group_router.callback_query(F.data.startswith("m_cash_"))
async def cashout_mine(callback: CallbackQuery):
    game_key = callback.data.split("m_cash_")[1]
    if game_key not in active_mines: return
    game = active_mines[game_key]
    win = int(game["bet"] * (1 + (len(game["opened"]) * 0.2)))
    update_balance(game["uid"], win)
    builder = InlineKeyboardBuilder()
    for i in range(25): builder.button(text="💥" if i in game["mines"] else "💎", callback_data="m_ign")
    builder.adjust(5, 5, 5, 5, 5)
    await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}", reply_markup=builder.as_markup())
    del active_mines[game_key]
    await callback.answer("Зачислено!")

@group_router.callback_query(F.data == "m_ign")
async def ign_mine(callback: CallbackQuery):
    await callback.answer("Недоступно.")

active_bj = {}

@group_router.message(F.text.regexp(r"(?i)^бж\s+(\d+)$"))
async def play_bj(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(message.from_user.id, -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    p_cards = [random.randint(2, 11), random.randint(2, 11)]
    d_cards = [random.randint(2, 11), random.randint(2, 11)]
    active_bj[game_key] = {"uid": message.from_user.id, "bet": amount, "p": p_cards, "d": d_cards}
    text = f"🃏 <b>Блэкджек</b>\n\nВаши карты: {p_cards[0]} + {p_cards[1]} = <b>{sum(p_cards)}</b>\nДилер: {d_cards[0]} + ?\n"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Взять", callback_data=f"bj_hit_{game_key}"), InlineKeyboardButton(text="Хватит", callback_data=f"bj_stand_{game_key}"))
    await message.reply(text, reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(callback: CallbackQuery):
    game_key = callback.data.split("bj_hit_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    card = random.randint(2, 11)
    game["p"].append(card)
    score = sum(game["p"])
    if score > 21:
        await callback.message.edit_text(f"🃏 Перебор! Сумма: {score}. Вы проиграли {format_money(game['bet'])}.")
        del active_bj[game_key]
    else:
        text = f"🃏 <b>Блэкджек</b>\n\nВаши карты: {', '.join(map(str, game['p']))} = <b>{score}</b>\nДилер: {game['d'][0]} + ?"
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="Взять", callback_data=f"bj_hit_{game_key}"), InlineKeyboardButton(text="Хватит", callback_data=f"bj_stand_{game_key}"))
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@group_router.callback_query(F.data.startswith("bj_stand_"))
async def bj_stand(callback: CallbackQuery):
    game_key = callback.data.split("bj_stand_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    p_score = sum(game["p"])
    d_score = sum(game["d"])
    while d_score < 17:
        game["d"].append(random.randint(2, 11))
        d_score = sum(game["d"])
    text = f"🃏 <b>Блэкджек</b>\n\nВаши карты: {', '.join(map(str, game['p']))} = {p_score}\nКарты дилера: {', '.join(map(str, game['d']))} = {d_score}\n\n"
    if d_score > 21:
        update_balance(game["uid"], game["bet"] * 2)
        text += "🎉 У дилера перебор! Вы выиграли!"
    elif p_score > d_score:
        update_balance(game["uid"], game["bet"] * 2)
        text += "🎉 Вы выиграли!"
    elif p_score == d_score:
        update_balance(game["uid"], game["bet"])
        text += "🤝 Ничья. Возврат ставки."
    else:
        text += "😢 Дилер выиграл."
    await callback.message.edit_text(text)
    del active_bj[game_key]
    await callback.answer()

active_duels = {}

@group_router.message(F.text.regexp(r"(?i)^дуэль\s+(\d+)$"))
async def start_duel(message: Message):
    if not message.reply_to_message: return await message.reply("❌ Нужно ответить (Reply) на сообщение соперника.")
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id: return await message.reply("❌ Нельзя вызывать самого себя.")
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Недостаточно средств.")
    duel_id = f"{message.chat.id}_{message.from_user.id}_{target_id}"
    active_duels[duel_id] = {"challenger": message.from_user.id, "target": target_id, "amount": amount}
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}"), InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}"))
    await message.reply(f"⚔️ <a href='tg://user?id={message.from_user.id}'>Игрок</a> вызывает <a href='tg://user?id={target_id}'>соперника</a> на дуэль на {format_money(amount)}!", reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("duel_accept_"))
async def accept_duel(callback: CallbackQuery):
    duel_id = callback.data.split("duel_accept_")[1]
    if duel_id not in active_duels: return await callback.answer("Дуэль не найдена.", show_alert=True)
    duel = active_duels[duel_id]
    if callback.from_user.id != duel["target"]: return await callback.answer("Это не твой вызов!", show_alert=True)
    target = get_user(duel["target"])
    if target[3] < duel["amount"]:
        del active_duels[duel_id]
        return await callback.message.edit_text("❌ У соперника недостаточно средств.")
    update_balance(duel["challenger"], -duel["amount"])
    update_balance(duel["target"], -duel["amount"])
    c_roll = random.randint(1, 6)
    t_roll = random.randint(1, 6)
    text = f"⚔️ <b>Дуэль!</b>\n\n<a href='tg://user?id={duel['challenger']}'>Игрок 1</a>: 🎲 {c_roll}\n<a href='tg://user?id={duel['target']}'>Игрок 2</a>: 🎲 {t_roll}\n\n"
    if c_roll > t_roll:
        update_balance(duel["challenger"], duel["amount"] * 2)
        text += f"🏆 Победил Игрок 1! Выигрыш: {format_money(duel['amount']*2)}"
    elif t_roll > c_roll:
        update_balance(duel["target"], duel["amount"] * 2)
        text += f"🏆 Победил Игрок 2! Выигрыш: {format_money(duel['amount']*2)}"
    else:
        update_balance(duel["challenger"], duel["amount"])
        update_balance(duel["target"], duel["amount"])
        text += "🤝 Ничья! Ставки возвращены."
    await callback.message.edit_text(text)
    del active_duels[duel_id]
    await callback.answer()

@group_router.callback_query(F.data.startswith("duel_decline_"))
async def decline_duel(callback: CallbackQuery):
    duel_id = callback.data.split("duel_decline_")[1]
    if duel_id not in active_duels: return await callback.answer("Дуэль не найдена.", show_alert=True)
    duel = active_duels[duel_id]
    if callback.from_user.id != duel["target"]: return await callback.answer("Это не твой вызов!", show_alert=True)
    del active_duels[duel_id]
    await callback.message.edit_text("❌ Дуэль отклонена.")
    await callback.answer()

# ==============================================================================
# ПЛАНИРОВЩИК
# ==============================================================================

async def lottery_draw():
    players = db_execute("SELECT user_id FROM lottery", fetchall=True)
    if not players: return
    winner = random.choice(players)[0]
    update_balance(winner, LOTTERY_PRIZE)
    db_execute("DELETE FROM lottery")
    try: await bot.send_message(winner, f"🎉 Вы выиграли {format_money(LOTTERY_PRIZE)} в лотерее!")
    except Exception: pass

async def pay_salaries():
    workers = db_execute("SELECT user_id FROM users WHERE role IN ('moderator', 'promoter')", fetchall=True)
    for w in workers:
        update_balance(w[0], MOD_SALARY)
        try: await bot.send_message(w[0], f"💸 Зарплата: {format_money(MOD_SALARY)}!")
        except Exception: pass

# ==============================================================================
# АДМИНКА, МОДЕРАЦИЯ, ПИАРЩИКИ
# ==============================================================================

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

@admin_router.message(Command("broadcast"))
@admin_router.message(F.text.in_([TEXTS["ru"]["btn_admin_broadcast"], TEXTS["en"]["btn_admin_broadcast"]]))
async def start_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("📢 Введите текст для рассылки (или /cancel для отмены):")
    await state.set_state(AdminStates.waiting_for_broadcast)

@admin_router.message(Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.")

@admin_router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    users = db_execute("SELECT user_id FROM users", fetchall=True)
    success, fail = 0, 0
    status_msg = await message.answer("⏳ Начинаю рассылку...")
    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await status_msg.edit_text(f"✅ Рассылка завершена!\nУспешно: {success}\nОшибок (заблокировали бота): {fail}")

@admin_router.message(Command("give_all"))
async def cmd_give_all(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) != 2: return await message.reply("Формат: /give_all 1000")
    try: amount = int(args[1])
    except ValueError: return await message.reply("❌ Введите число.")
    db_execute("UPDATE users SET balance = balance + ?", (amount,))
    await message.reply(f"✅ Всем игрокам выдано по {format_money(amount)}.")

@admin_router.message(Command("sys_info"))
async def cmd_sys_info(message: Message):
    if message.from_user.id != ADMIN_ID: return
    import platform
    total_users = db_execute("SELECT COUNT(*) FROM users", fetchone=True)[0]
    bal = db_execute("SELECT SUM(balance) FROM users", fetchone=True)[0] or 0
    text = f"🖥 <b>Состояние сервера</b>\n\n🐍 Python: {platform.python_version()}\n📅 ОС: {platform.system()}\n👥 Игроков: {total_users}\n💰 Общий баланс: {format_money(bal)}\n"
    await message.reply(text)

@admin_router.message(Command("secret"))
async def cmd_secret(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) != 3: return await message.reply("Формат: /secret СУММА ВРЕМЯ_В_СЕКУНДАХ")
    try:
        amount = int(args[1])
        time_sec = int(args[2])
    except ValueError: return await message.reply("❌ Неверный формат.")
    builder = InlineKeyboardBuilder().button(text="🎁 ЗАБРАТЬ", callback_data=f"secret_{amount}")
    msg = await message.answer(f"🎁 <b>СЕКРЕТНЫЙ ДРОП!</b>\nКто первый нажмет кнопку, получит {format_money(amount)}!", reply_markup=builder.as_markup())
    await asyncio.sleep(time_sec)
    try: await msg.delete()
    except Exception: pass

@admin_router.callback_query(F.data.startswith("secret_"))
async def claim_secret(callback: CallbackQuery):
    amount = int(callback.data.split("_")[-1])
    try: await callback.message.delete()
    except Exception: pass
    update_balance(callback.from_user.id, amount)
    try: await bot.send_message(callback.from_user.id, f"🎉 Вы забрали секретный дроп: {format_money(amount)}!")
    except Exception: pass

@admin_router.message(Command("mod_add"))
async def add_mod(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit(): return await message.reply("Формат: /mod_add ID")
    target_id = int(args[1])
    db_execute("UPDATE users SET role = 'moderator' WHERE user_id = ?", (target_id,))
    builder = ReplyKeyboardBuilder().row(KeyboardButton(text="⬅️ В меню"))
    try:
        await bot.send_message(target_id, "🛠 <b>Вам выданы права модератора!</b>\nПишите команды для модерации.", reply_markup=builder.as_markup(resize_keyboard=True))
        await message.reply("✅ Модер назначен.")
    except Exception: await message.reply("❌ Ошибка (закрыты ЛС).")

@admin_router.message(Command("pr_add"))
async def add_pr(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit(): return await message.reply("Формат: /pr_add ID")
    target_id = int(args[1])
    db_execute("UPDATE users SET role = 'promoter' WHERE user_id = ?", (target_id,))
    builder = ReplyKeyboardBuilder().row(KeyboardButton(text="📝 Получить текст")).row(KeyboardButton(text="⬅️ В меню"))
    try:
        await bot.send_message(target_id, "📢 <b>Вам выданы права пиарщика!</b>", reply_markup=builder.as_markup(resize_keyboard=True))
        await message.reply("✅ Пиарщик назначен.")
    except Exception: await message.reply("❌ Ошибка (закрыты ЛС).")

@pr_router.message(F.text.in_([TEXTS["ru"]["btn_pr_text"], TEXTS["en"]["btn_pr_text"]]))
@pr_router.message(Command("pr_text"))
async def pr_get_text(message: Message):
    user = get_user(message.from_user.id)
    if user[10] != "promoter" and message.from_user.id != ADMIN_ID: return
    db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, ?, ?)", (user[0], "pr_text_taken", 0, datetime.datetime.now().isoformat()))
    texts = [
        "🔥 <b>Лучший бот для заработка!</b>\nЗаходи, получай стартовый бонус 5000 и играй в игры прямо в чате! @{bot}",
        "💎 <b>Хочешь стать богаче?</b>\nНаш бот дает крутые бонусы и игры. Забирай свои 5000 прямо сейчас! @{bot}",
        "🎮 <b>Играй и зарабатывай!</b>\nРулетка, кейсы, лотереи. Стартовый бонус уже ждет тебя! @{bot}"
    ]
    bot_info = await bot.get_me()
    text = random.choice(texts).format(bot=bot_info.username)
    await message.answer(f"📋 <b>Ваш текст для рассылки:</b>\n\n{text}")

@mod_router.message(Command("mod_give"))
async def mod_give(message: Message):
    user = get_user(message.from_user.id)
    if user[10] not in ["moderator", "admin"] and message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) != 3: return await message.reply("Формат: /mod_give ID СУММА")
    try:
        target_id = int(args[1].replace("@", ""))
        amount = int(args[2])
    except ValueError: return await message.reply("❌ Неверный формат ID или суммы.")
    if message.from_user.id != ADMIN_ID:
        limit_data = db_execute("SELECT given_amount, last_reset FROM mod_limits WHERE user_id = ?", (user[0],), fetchone=True)
        now = datetime.datetime.now()
        if not limit_data:
            db_execute("INSERT INTO mod_limits (user_id, given_amount, last_reset) VALUES (?, 0, ?)", (user[0], now.isoformat()))
            given = 0
        else:
            given, last_reset = limit_data
            if now - datetime.datetime.fromisoformat(last_reset) > datetime.timedelta(days=7):
                given = 0
                db_execute("UPDATE mod_limits SET given_amount = 0, last_reset = ? WHERE user_id = ?", (now.isoformat(), user[0]))
        if given + amount > 5000000:
            return await message.reply(f"❌ Лимит превышен! Вы выдали {format_money(given)} из 5 000 000. Осталось: {format_money(5000000 - given)}.")
        db_execute("UPDATE mod_limits SET given_amount = given_amount + ? WHERE user_id = ?", (amount, user[0]))
    update_balance(target_id, amount)
    await message.reply(f"✅ Вы выдали {format_money(amount)} игроку {target_id}.")

# ==============================================================================
# ПАТЧ 10: ФИКС БАЛАНСА И БОНУСА (ИНДЕКСЫ БАЗЫ ДАННЫХ)
# ==============================================================================

@user_router.message(F.text.in_(["🎁 Бонус", "🎁 Bonus"]))
async def claim_bonus_final(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    last_bonus = user[7]
    if last_bonus:
        last_bonus_dt = datetime.datetime.fromisoformat(last_bonus)
        if now - last_bonus_dt < datetime.timedelta(hours=24):
            time_left = datetime.timedelta(hours=24) - (now - last_bonus_dt)
            return await send_clean(message, f"⏳ Следующий бонус через {time_left.seconds//3600} ч. {(time_left.seconds%3600)//60} мин.", reply_markup=get_profile_menu(user[2]))
    streak = user[8] + 1 if last_bonus and (now - last_bonus_dt).days == 1 else 1
    bonus_amount = 5000 if streak < 7 else 10000
    db_execute("UPDATE users SET balance = balance + ?, last_bonus = ?, streak = ? WHERE user_id = ?", (bonus_amount, now.isoformat(), streak, user[0]))
    await send_clean(message, f"🎁 Бонус: {format_money(bonus_amount)}!\n🔥 Стрик: {streak} дн.", reply_markup=get_profile_menu(user[2]))

@user_router.message(F.text.in_(["💰 Баланс", "💰 Balance"]))
async def show_balance_fix(message: Message):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await send_clean(message, f"💰 <b>{format_money(user[3])}</b>", reply_markup=get_main_menu(user[2]))

@group_router.message(F.text.in_(["б", "баланс"]))
async def cmd_balance_group_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    user = get_user(message.from_user.id)
    await message.reply(f"💰 Твой баланс: <b>{format_money(user[3])}</b>")

@group_router.message(F.text.lower() == "топ")
async def cmd_top_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    top_users = db_execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
    text = "🏆 <b>Топ-10 игроков:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        text += f"{i}. ID {u[0]} — {format_money(u[1])}\n"
    await message.reply(text)

@group_router.message(F.text.lower() == "лог")
async def cmd_log_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    logs = db_execute("SELECT action, amount FROM logs ORDER BY id DESC LIMIT 5", fetchall=True)
    text = "📜 <b>Последние операции:</b>\n\n"
    for log in logs:
        text += f"{log[0]}: {log[1]}\n"
    await message.reply(text)

@group_router.message(F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
async def cmd_transfer_fix(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    parts = message.text.split()
    target_id = int(parts[1])
    amount = int(parts[2])
    if target_id == message.from_user.id: return await message.reply("❌ Нельзя переводить самому себе.")
    sender = get_user(message.from_user.id)
    if sender[3] < amount: return await message.reply("❌ Недостаточно средств.")
    update_balance(message.from_user.id, -amount)
    update_balance(target_id, amount)
    await message.reply(f"✅ Перевод {format_money(amount)} пользователю <a href='tg://user?id={target_id}'>{target_id}</a> выполнен.")

@group_router.message(F.text.regexp(r"(?i)^(кости|баскет|футбол|дартс|боулинг)\s+(\d+)$"))
async def play_dice_games(message: Message):
    parts = message.text.lower().split()
    game = parts[0]
    amount = int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(message.from_user.id, -amount)
    if game == "кости": msg = await message.answer_dice(emoji="🎲")
    elif game == "баскет": msg = await message.answer_dice(emoji="🏀")
    elif game == "футбол": msg = await message.answer_dice(emoji="⚽")
    elif game == "дартс": msg = await message.answer_dice(emoji="🎯")
    elif game == "боулинг": msg = await message.answer_dice(emoji="🎳")
    await asyncio.sleep(3)
    dice_value = msg.dice.value
    win = False
    if game == "кости" and dice_value >= 4: win = True
    elif game == "баскет" and dice_value >= 3: win = True
    elif game == "футбол" and dice_value >= 4: win = True
    elif game == "дартс" and dice_value >= 4: win = True
    elif game == "боулинг" and dice_value >= 4: win = True
    if win:
        update_balance(message.from_user.id, amount * 2)
        await message.reply(f"🎉 Победа! Выпало {dice_value}. Выиграли {format_money(amount*2)}!")
    else:
        await message.reply(f"😢 Проиграли. Выпало {dice_value}.")

@group_router.callback_query(F.data.startswith("game_"))
async def process_game_callback(message: Message):
    game = message.data.split("_")[-1]
    if game == "roulette": await message.message.edit_text("🎡 <b>Рулетка</b>\n\nНапиши в чат: <code>к 100</code> и затем <code>го</code>")
    elif game == "mines": await message.message.edit_text("💣 <b>Мины</b>\n\nНапиши в чат: <code>мины 100</code>")
    elif game == "blackjack": await message.message.edit_text("🃏 <b>Блэкджек</b>\n\nНапиши в чат: <code>бж 100</code>")
    elif game == "dice": await message.message.edit_text("🎲 <b>Кости</b>\n\nНапиши в чат: <code>кости 100</code> (или используй кнопку ниже!)")
    elif game == "basket": await message.message.edit_text("🏀 <b>Баскет</b>\n\nНапиши в чат: <code>баскет 100</code>")
    elif game == "football": await message.message.edit_text("⚽ <b>Футбол</b>\n\nНапиши в чат: <code>футбол 100</code>")
    elif game == "darts": await message.message.edit_text("🎯 <b>Дартс</b>\n\nНапиши в чат: <code>дартс 100</code>")
    elif game == "bowling": await message.message.edit_text("🎳 <b>Боулинг</b>\n\nНапиши в чат: <code>боулинг 100</code>")
    elif game == "duel": await message.message.edit_text("⚔️ <b>Дуэли</b>\n\nОтветь (Reply) на сообщение игрока и напиши: <code>дуэль 100</code>")
    elif game == "coin": await message.message.edit_text("🪙 <b>Монетка</b>\n\nНапиши в чат: <code>монетка 100 орел</code>")
    await message.answer()

# ==============================================================================
# ЗАПУСК И ПИНГ
# ==============================================================================

async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_ping_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("Web-сервер для пинга запущен на порту 8080")

async def main():
    init_db()
    scheduler.add_job(lottery_draw, "cron", hour=20, minute=0)
    scheduler.add_job(pay_salaries, "interval", days=3, next_run_time=datetime.datetime.now() + datetime.timedelta(days=3))
    scheduler.start()
    asyncio.create_task(start_ping_server())
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")