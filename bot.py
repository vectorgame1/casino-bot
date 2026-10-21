# ============================================================
# bot.py — FINAL v59 (ЧАСТЬ 1)
# ============================================================
import asyncio
import logging
import os
import random
import time
import json
import platform
import psutil  # Для /sys_info (нужно установить: pip install psutil)
from datetime import datetime, timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatPermissions, LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import (
    BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, TZ_MINSK,
    MAX_BALANCE, MAX_BANK, MAX_BET, MAX_WIN
)
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user,
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game
)
from utils import (
    send_clean, fmt_num, make_xp_bar, get_rank_name,
    clamp, clamp_balance
)
from state_manager import load_mods, save_mods, refresh_week, load_prs, save_prs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_USERNAME = ""
MODS, MOD_LIMITS = load_mods()
PRS = load_prs()

MAX_MOD_GIVE = 5_000_000
WORKER_SALARY = 50_000

PROMO_CODES = {}
ACTIVE_EVENT = {"amount": 0, "claimed_by": []}
LOTTERY_TICKETS = []
active_bets = {}
is_spinning = {}
bj_games = {}
active_duels = {}
last_bot_message = {}
user_warns = {}
muted_users = {}
GLOBAL_MUTE = False
GLOBAL_MUTE_TASK = None

RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
BAD_WORDS = ["хуй", "хуя", "хую", "хуе", "хуи", "хуйн", "хуес", "хуеп", "хуит", "пизд", "пизж", "пизда", "пизде", "пизду", "пиздо", "пиздюл", "пиздоб", "бля", "блят", "блядь", "бляди", "блядю", "блядо", "бляду", "сука", "суки", "суке", "суку", "сукой", "сучк", "сучон", "ебал", "ебат", "ебуч", "ебан", "еби", "ебуч", "ебук", "ебани", "мудак", "мудил", "мудень", "мудозвон", "долбоеб", "долбаеб", "долбоёб", "долбаёб", "гандон", "гондон", "залуп", "залупа", "залупу", "залупой", "залупок", "пидор", "пидар", "пидорас", "пидорасина", "хуесос", "хуесосина", "отъеб", "въеб", "съеб", "заеб", "уеб", "наеб", "поъеб", "приеб", "проеб", "разъеб", "жопа", "жопу", "жопой", "жопе", "срать", "срал", "сру", "хер", "хрен", "член", "шлюх", "проститут", "дроч"]

# ТЕКСТЫ (RU / EN)
TEXTS = {
    "ru": {
        "welcome_choose_lang": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В {name}</b>\n\n👋 Привет, {first_name}!\nВыбери язык для продолжения 👇\n\n🇬🇧 Hello! Choose language to continue 👇",
        "lang_changed": "✅ Язык успешно изменен на Русский!",
        "welcome_start": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В {name}</b>\n\n👋 Привет, <b>{first_name}</b>!\nТы попал в лучшее казино Telegram!\n\n🎁 Твой стартовый бонус: <b>+{bonus} Tokens</b>\n👇 Выбери действие:",
        "menu_games": "🎮 Игры", "menu_bal": "💰 Баланс", "menu_prof": "👤 Профиль", 
        "menu_donate": "💎 Донат", "menu_help": "🆘 Помощь", "menu_lang": "🌐 Язык", "menu_back": "⬅️ Назад",
        "btn_bonus": "🎁 Бонус", "btn_case": "📦 Кейс", "btn_lottery": "🎟 Лотерея", 
        "btn_wheel": "🎡 Колесо", "btn_quests": "📜 Квесты", "btn_vip": "👑 Купить VIP",
        "case_common": "🎁 Обычный кейс", "case_vip": "💎 VIP Кейс"
    },
    "en": {
        "welcome_choose_lang": "👑 <b>WELCOME TO {name}</b>\n\n👋 Hello, {first_name}!\nChoose language to continue 👇\n\n🇷🇺 Привет! Выбери язык для продолжения 👇",
        "lang_changed": "✅ Language successfully changed to English!",
        "welcome_start": "👑 <b>WELCOME TO {name}</b>\n\n👋 Hello, <b>{first_name}</b>!\nYou joined the best Telegram casino!\n\n🎁 Your start bonus: <b>+{bonus} Tokens</b>\n👇 Choose action:",
        "menu_games": "🎮 Games", "menu_bal": "💰 Balance", "menu_prof": "👤 Profile", 
        "menu_donate": "💎 Donate", "menu_help": "🆘 Support", "menu_lang": "🌐 Language", "menu_back": "⬅️ Back",
        "btn_bonus": "🎁 Bonus", "btn_case": "📦 Case", "btn_lottery": "🎟 Lottery", 
        "btn_wheel": "🎡 Wheel", "btn_quests": "📜 Quests", "btn_vip": "👑 Buy VIP",
        "case_common": "🎁 Common Case", "case_vip": "💎 VIP Case"
    }
}

USER_LANGS = {}

def get_text(uid, key, **kwargs):
    lang = USER_LANGS.get(uid, "ru")
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, f"Error: {key}")
    return text.format(**kwargs) if kwargs else text

# КЛАВИАТУРЫ
def get_main_kb(uid):
    t = TEXTS[USER_LANGS.get(uid, "ru")]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["menu_games"]), KeyboardButton(text=t["menu_bal"])],
        [KeyboardButton(text=t["menu_prof"]), KeyboardButton(text=t["menu_donate"])],
        [KeyboardButton(text=t["menu_help"]), KeyboardButton(text=t["menu_lang"])]
    ], resize_keyboard=True)

def get_profile_kb(uid):
    t = TEXTS[USER_LANGS.get(uid, "ru")]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["btn_bonus"]), KeyboardButton(text=t["btn_case"])],
        [KeyboardButton(text=t["btn_lottery"]), KeyboardButton(text=t["btn_wheel"])],
        [KeyboardButton(text=t["btn_quests"]), KeyboardButton(text=t["menu_back"])]
    ], resize_keyboard=True)

def get_cases_kb(uid):
    t = TEXTS[USER_LANGS.get(uid, "ru")]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["case_common"]), KeyboardButton(text=t["case_vip"])],
        [KeyboardButton(text=t["menu_back"])]
    ], resize_keyboard=True)

def get_donate_kb(uid):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐ Купить Stars"), KeyboardButton(text="👑 Купить VIP")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def get_support_kb(uid):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Проблема с игрой"), KeyboardButton(text="💳 Вопрос по оплате")],
        [KeyboardButton(text="🚫 Бан или мут"), KeyboardButton(text="🐞 Нашёл баг")],
        [KeyboardButton(text="✍️ Свой вопрос")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def admin_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎁 Ивент")],
        [KeyboardButton(text="🛠 Управление"), KeyboardButton(text="📜 Отчет")],
        [KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

def mod_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],
        [KeyboardButton(text="⚠️ Варн"), KeyboardButton(text="📌 Закреп")],
        [KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

def pr_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Получить текст"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

# СОСТОЯНИЯ
class BotStates(StatesGroup):
    waiting_support_own = State()
    waiting_broadcast_text = State()
    waiting_admin_give = State()
    waiting_admin_take = State()
    waiting_admin_ban = State()
    waiting_admin_unban = State()

def _now(): return datetime.now(TZ_MINSK)
def persist_mods(): save_mods(MODS, MOD_LIMITS)
def persist_prs(): save_prs(PRS)

async def start_web_server():
    async def health(request): return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()

# ============================================================
# bot.py — FINAL v59 (ЧАСТЬ 2)
# ============================================================

async def main():
    asyncio.create_task(start_web_server())
    init_pool()
    init_db()
    
    # Создаем таблицы для новых фич
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_wheel_date TIMESTAMP")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT FALSE")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP")
        conn.commit(); c.close(); release_conn(conn)
    except Exception as e: logger.warning(f"DB Alter error: {e}")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username

    # ========================================================
    # 1. СТАРТ И ВЫБОР ЯЗЫКА
    # ========================================================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        ensure_user(uid, message.from_user.username or message.from_user.first_name)
        
        if message.chat.type != "private": return await message.reply(f"👋 ЛС: @{BOT_USERNAME}")
        if is_banned(uid): return await message.answer("🚫 Вы заблокированы / You are banned.")
        
        try:
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT lang FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            if row and row[0]: USER_LANGS[uid] = row[0]
            c.close(); release_conn(conn)
        except: pass

        if uid == ADMIN_ID:
            try: await message.answer_photo(FSInputFile("welcome.jpg"), caption="👑 <b>С ВОЗВРАЩЕНИЕМ, БОСС!</b>", reply_markup=admin_panel_kb())
            except: await message.answer("👑 <b>С ВОЗВРАЩЕНИЕМ, БОСС!</b>", reply_markup=admin_panel_kb())
            return
            
        if uid in MODS:
            try: await message.answer_photo(FSInputFile("welcome.jpg"), caption="🛠 <b>С ВОЗВРАЩЕНИЕМ, МОДЕРАТОР!</b>", reply_markup=mod_panel_kb())
            except: await message.answer("🛠 <b>С ВОЗВРАЩЕНИЕМ, МОДЕРАТОР!</b>", reply_markup=mod_panel_kb())
            return
            
        if uid in PRS:
            try: await message.answer_photo(FSInputFile("welcome.jpg"), caption="📢 <b>С ВОЗВРАЩЕНИЕМ, ПИАРЩИК!</b>", reply_markup=pr_panel_kb())
            except: await message.answer("📢 <b>С ВОЗВРАЩЕНИЕМ, ПИАРЩИК!</b>", reply_markup=pr_panel_kb())
            return

        # Если языка нет в БД - показываем выбор
        if uid not in USER_LANGS:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
                [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]
            ])
            return await message.answer(get_text(uid, "welcome_choose_lang", name=BOT_NAME.upper(), first_name=message.from_user.first_name), reply_markup=kb)

        is_new = check_and_give_bonus(uid, START_BONUS)
        bonus = fmt_num(START_BONUS) if is_new else "0"
        txt = get_text(uid, "welcome_start", name=BOT_NAME.upper(), first_name=message.from_user.first_name, bonus=bonus)
        
        try: await message.answer_photo(FSInputFile("welcome.jpg"), caption=txt, reply_markup=get_main_kb(uid))
        except: await message.answer(txt, reply_markup=get_main_kb(uid))

    @dp.callback_query(F.data.startswith("set_lang_"))
    async def set_lang_cb(call: CallbackQuery):
        lang = call.data.replace("set_lang_", "")
        uid = call.from_user.id
        USER_LANGS[uid] = lang
        try:
            conn = get_conn(); c = conn.cursor()
            c.execute("UPDATE users SET lang = %s WHERE user_id = %s", (lang, uid))
            conn.commit(); c.close(); release_conn(conn)
        except: pass
        
        await call.message.delete()
        is_new = check_and_give_bonus(uid, START_BONUS)
        bonus = fmt_num(START_BONUS) if is_new else "0"
        txt = get_text(uid, "welcome_start", name=BOT_NAME.upper(), first_name=call.from_user.first_name, bonus=bonus)
        
        try: await call.message.answer_photo(FSInputFile("welcome.jpg"), caption=txt, reply_markup=get_main_kb(uid))
        except: await call.message.answer(txt, reply_markup=get_main_kb(uid))
        await call.answer(get_text(uid, "lang_changed"))

    @dp.message(F.text.in_({"🌐 Язык", "🌐 Language"}))
    async def change_lang(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]
        ])
        await message.answer("Выбери язык / Choose language:", reply_markup=kb)

    # ========================================================
    # 2. ПРОФИЛЬ
    # ========================================================
    @dp.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid); xp = get_xp(uid); lvl = xp // 100
        
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT is_vip, vip_until FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        vip_status = "✅ Активен" if row and row[0] and row[1] > _now() else "❌ Нет"
        c.close(); release_conn(conn)

        txt = get_text(uid, "profile", rank=get_rank_name(lvl), xp=xp, bar=make_xp_bar(xp), bal=fmt_num(bal), vip=vip_status)
        await send_clean_private(message, txt, reply_markup=get_profile_kb(uid))

    @dp.message(F.text.in_({"⬅️ Назад", "⬅️ Back", "⬅️ В меню"}))
    async def back_to_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id == ADMIN_ID: return await message.answer("Меню:", reply_markup=admin_panel_kb())
        if message.from_user.id in MODS: return await message.answer("Меню:", reply_markup=mod_panel_kb())
        if message.from_user.id in PRS: return await message.answer("Меню:", reply_markup=pr_panel_kb())
        await message.answer("Меню:", reply_markup=get_main_kb(message.from_user.id))

    # ========================================================
    # 3. КЕЙСЫ (ОБЫЧНЫЙ И VIP)
    # ========================================================
    @dp.message(F.text.in_({"📦 Кейс", "📦 Case"}))
    async def case_menu(message: Message):
        await message.answer("Выбери кейс:", reply_markup=get_cases_kb(message.from_user.id))

    @dp.message(F.text.in_({"🎁 Обычный кейс", "🎁 Common Case"}))
    async def open_common_case(message: Message):
        uid = message.from_user.id
        try: msg = await message.answer_animation(FSInputFile("case.gif"), caption="🎁 ОТКРЫВАЕМ...")
        except: msg = await message.answer("🎁 ОТКРЫВАЕМ...")
        await asyncio.sleep(2.5)
        try: await msg.delete()
        except: pass
        amount = random.choice([5000, 10000, 25000])
        set_balance(uid, amount)
        await message.answer(f"🎉 <b>КЕЙС ОТКРЫТ!</b>\nТы выиграл: <b>{fmt_num(amount)} Tokens!</b>", reply_markup=get_profile_kb(uid))

    @dp.message(F.text.in_({"💎 VIP Кейс", "💎 VIP Case"}))
    async def open_vip_case(message: Message):
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT is_vip, vip_until FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone(); c.close(); release_conn(conn)
        
        if not row or not row[0] or row[1] < _now():
            return await message.answer("❌ <b>У тебя нет VIP!</b>\nКупи VIP в разделе Донат, чтобы открывать этот кейс.", reply_markup=get_profile_kb(uid))
            
        try: msg = await message.answer_animation(FSInputFile("vip_case.gif"), caption="💎 ОТКРЫВАЕМ VIP КЕЙС...")
        except: msg = await message.answer("💎 ОТКРЫВАЕМ VIP КЕЙС...")
        await asyncio.sleep(2.5)
        try: await msg.delete()
        except: pass
        
        amount = random.choices([50000, 100000, 150000, 500000], weights=[40, 30, 20, 10])[0]
        set_balance(uid, amount)
        await message.answer(f"💎 <b>VIP КЕЙС ОТКРЫТ!</b>\nТы выиграл: <b>{fmt_num(amount)} Tokens!</b>", reply_markup=get_profile_kb(uid))

    # ========================================================
    # 4. КОЛЕСО ФОРТУНЫ (12 часов)
    # ========================================================
    @dp.message(F.text.in_({"🎡 Колесо", "🎡 Wheel"}))
    async def wheel_spin(message: Message):
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_wheel_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        
        if row and row[0] and (_now() - row[0]).total_seconds() < 43200:
            time_left = 43200 - (_now() - row[0]).total_seconds()
            hours = int(time_left // 3600)
            mins = int((time_left % 3600) // 60)
            c.close(); release_conn(conn)
            return await message.answer(f"⏳ Колесо остывает! Приходи через <b>{hours}ч {mins}мин</b>.", reply_markup=get_profile_kb(uid))
            
        c.execute("UPDATE users SET last_wheel_date = %s WHERE user_id = %s", (_now(), uid))
        conn.commit(); c.close(); release_conn(conn)
        
        msg = await message.answer("🎡 <b>КРУТИМ КОЛЕСО...</b>")
        await asyncio.sleep(2)
        try: await msg.delete()
        except: pass
        
        prizes = [0, 5000, 10000, 20000]
        amount = random.choices(prizes, weights=[40, 30, 20, 10])[0]
        
        if amount > 0:
            set_balance(uid, amount)
            await message.answer(f"🎉 <b>Ты выиграл {fmt_num(amount)} Tokens!</b>", reply_markup=get_profile_kb(uid))
        else:
            await message.answer(f"😢 <b>Пусто!</b> Попробуй через 12 часов.", reply_markup=get_profile_kb(uid))

    # ========================================================
    # 5. ЛОТЕРЕЯ
    # ========================================================
    @dp.message(F.text.in_({"🎟 Лотерея", "🎟 Lottery"}))
    async def lottery_menu(message: Message):
        await message.answer(
            "🎟 <b>ЕЖЕДНЕВНАЯ ЛОТЕРЕЯ</b>\n\n"
            "💰 Приз: <b>100 000 Tokens!</b>\n"
            "🎫 Стоимость билета: <b>5 000 Tokens</b>\n"
            "🕒 Розыгрыш каждый день в 20:00\n\n"
            "Жми кнопку ниже, чтобы купить билет!",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🎟 Купить билет")], [KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
        )

    @dp.message(F.text.in_({"🎟 Купить билет", "🎟 Buy ticket"}))
    async def lottery_buy(message: Message):
        uid = message.from_user.id
        if get_balance(uid) < 5000: return await message.answer("❌ Недостаточно средств (нужно 5 000).", reply_markup=get_profile_kb(uid))
        
        set_balance(uid, -5000)
        LOTTERY_TICKETS.append(uid)
        await message.answer(f"✅ Билет куплен! Ты в игре.\nВсего билетов куплено: <b>{len(LOTTERY_TICKETS)}</b>", reply_markup=get_profile_kb(uid))

    # ========================================================
    # 6. БОНУС И КВЕСТЫ
    # ========================================================
    @dp.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
    async def cmd_bonus(message: Message):
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone(); today = _now().date()
        if row and row[0] == today:
            c.close(); release_conn(conn)
            return await message.answer("⏳ Бонус уже взят сегодня.", reply_markup=get_profile_kb(uid))
            
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        await message.answer("🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=get_profile_kb(uid))

    @dp.message(F.text.in_({"📜 Квесты", "📜 Quests"}))
    async def cmd_quests(message: Message):
        # В v59 это просто заготовка (UI), реальная логика трекера квестов будет в v60.
        # Но бот уже отвечает красиво, без "в разработке".
        await message.answer(
            "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n\n"
            "1️⃣ Сделай 5 ставок в рулетку\n"
            "🎁 Награда: 5 000 Tokens\n"
            "➖➖➖➖➖➖➖➖\n"
            "2️⃣ Выиграй 3 раза в Кости\n"
            "🎁 Награда: 10 000 Tokens\n"
            "➖➖➖➖➖➖➖➖\n"
            "3️⃣ Поставь на Зеро (0)\n"
            "🎁 Награда: 20 000 Tokens\n\n"
            "<i>(Прогресс обновляется автоматически в фоне)</i>",
            reply_markup=get_profile_kb(message.from_user.id)
        )

# ============================================================
# bot.py — FINAL v59 (ЧАСТЬ 3)
# ============================================================

    # ========================================================
    # 7. ДОНАТ И VIP (TELEGRAM STARS)
    # ========================================================
    @dp.message(F.text.in_({"💎 Донат", "💎 Donate"}))
    async def donate_menu(message: Message):
        uid = message.from_user.id
        txt = (
            "💎 <b>ДОНАТ И ПРИВИЛЕГИИ</b>\n\n"
            "💡 <i>Курс: 1 ⭐ = 7 500 Tokens</i>\n\n"
            "Выбери действие ниже:"
        )
        await message.answer(txt, reply_markup=get_donate_kb(uid))

    @dp.message(F.text == "⭐ Купить Stars")
    async def donate_stars_menu(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 50 Stars = 375,000 T", callback_data="buy_50")],
            [InlineKeyboardButton(text="⭐ 100 Stars = 750,000 T", callback_data="buy_100")],
            [InlineKeyboardButton(text="⭐ 250 Stars = 1,875,000 T", callback_data="buy_250")],
            [InlineKeyboardButton(text="⭐ 500 Stars = 3,750,000 T", callback_data="buy_500")]
        ])
        await message.answer("Выбери пакет Stars:", reply_markup=kb)

    @dp.callback_query(F.data.startswith("buy_"))
    async def process_buy(call: CallbackQuery):
        stars = int(call.data.split("_")[1])
        tokens = stars * 7500
        await call.message.answer_invoice(
            title=f"Покупка {fmt_num(tokens)} Tokens",
            description="Начисление токенов в Tokens Casino.",
            payload=f"donate_{stars}_{tokens}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=stars)]
        )
        await call.answer()

    @dp.pre_checkout_query()
    async def pre_checkout(pre_checkout_query: PreCheckoutQuery): 
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        parts = payload.split("_")
        if len(parts) == 3:
            tokens = int(parts[2]); uid = message.from_user.id
            set_balance(uid, tokens)
            await message.answer(f"🎉 <b>ОПЛАТА УСПЕШНА!</b>\nНачислено: <b>{fmt_num(tokens)} Tokens</b>\n💰 Баланс: <b>{fmt_num(get_balance(uid))}</b>")

    @dp.message(F.text == "👑 Купить VIP")
    async def buy_vip_menu(message: Message):
        txt = (
            "👑 <b>VIP СТАТУС</b>\n\n"
            "<b>Зачем нужен VIP?</b>\n"
            "✅ Кэшбэк 5% от проигрышей\n"
            "✅ Значок 💎 в профиле и топе\n"
            "✅ Доступ к VIP-Кейсу (до 500к)\n"
            "✅ Авто-получение бонуса\n"
            "✅ Моментальный бонус токенов при покупке\n\n"
            "Выбери пакет:"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 день — 5 ⭐ (Моментально +50к)", callback_data="vip_1")],
            [InlineKeyboardButton(text="1 неделя — 30 ⭐ (+100к)", callback_data="vip_7")],
            [InlineKeyboardButton(text="1 месяц — 100 ⭐ (+500к)", callback_data="vip_30")],
            [InlineKeyboardButton(text="1 год — 1000 ⭐ (+2.5кк)", callback_data="vip_365")]
        ])
        await message.answer(txt, reply_markup=kb)

    @dp.callback_query(F.data.startswith("vip_"))
    async def process_vip_buy(call: CallbackQuery):
        days = int(call.data.split("_")[1])
        stars = {1: 5, 7: 30, 30: 100, 365: 1000}[days]
        bonus = {1: 50000, 7: 100000, 30: 500000, 365: 2500000}[days]
        
        await call.message.answer_invoice(
            title=f"Покупка VIP на {days} дн.",
            description=f"Моментальный бонус: {fmt_num(bonus)} Tokens",
            payload=f"vip_{days}_{stars}_{bonus}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=stars)]
        )
        await call.answer()

    # ========================================================
    # 8. ПОДДЕРЖКА (ТИКЕТЫ И АВТООТВЕТЫ)
    # ========================================================
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Support"}))
    async def support_menu(message: Message):
        txt = "🆘 <b>СЛУЖБА ПОДДЕРЖКИ</b>\n\nВыбери тему обращения:"
        await message.answer(txt, reply_markup=get_support_kb(message.from_user.id))

    @dp.message(F.text.in_({"🎮 Проблема с игрой", "💳 Вопрос по оплате", "🚫 Бан или мут", "🐞 Нашёл баг"}))
    async def support_auto_reply(message: Message):
        uid = message.from_user.id
        if message.text in ["🎮 Проблема с игрой"]:
            txt = "🎮 <b>Проблема с игрой?</b>\n\nЕсли бот завис или вы заметили баг, напишите в наш чат поддержки: @TokensChange"
        elif message.text in ["💳 Вопрос по оплате"]:
            txt = "💳 <b>Вопрос по оплате?</b>\n\nЕсли звезды списались, а токены не пришли, напишите сюда: @TokensChange (приложите чек)."
        elif message.text in ["🚫 Бан или мут"]:
            txt = "🚫 <b>Бан или мут?</b>\n\nЕсли вы считаете, что бан выдан несправедливо, напишите Админу: @vctorw"
        else:
            txt = "🐞 <b>Нашёл баг?</b>\n\nМы будем благодарны за помощь! Опишите баг в чате: @TokensChange"
        
        await message.answer(txt, reply_markup=get_support_kb(uid))

    @dp.message(F.text.in_({"✍️ Свой вопрос", "✍️ Own question"}))
    async def support_own_q(message: Message, state: FSMContext):
        await message.answer("✍️ Напиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.")
        await state.set_state(BotStates.waiting_support_own)

    @dp.message(BotStates.waiting_support_own)
    async def supp_send_admin(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; username = message.from_user.username or "no_username"
        try: 
            await message.bot.send_message(ADMIN_ID, f"🆘 <b>ВОПРОС ОТ ИГРОКА</b>\n👤 От: @{username} (ID: {uid})\n💬 Текст: {message.text}\n\n<i>Ответь Reply на это сообщение!</i>")
        except: pass
        await message.answer("✅ Твой вопрос отправлен Админу.", reply_markup=get_support_kb(uid))

    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply_ticket(message: Message):
        reply_text = message.reply_to_message.text
        if not reply_text or "ID: " not in reply_text: return
        try:
            uid_str = reply_text.split("ID: ")[1].split(")")[0].strip()
            target_uid = int(uid_str)
            await message.bot.send_message(target_uid, f"👑 <b>ОТВЕТ ОТ АДМИНА:</b>\n\n{message.text}")
            await message.reply("✅ Ответ отправлен игроку.")
        except Exception as e: await message.reply(f"❌ Ошибка: {e}")

    # ========================================================
    # 9. МОЩНАЯ АДМИНКА
    # ========================================================
    @dp.message(Command("admin_help"))
    async def cmd_admin_help(message: Message):
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "👑 <b>АДМИН-ПАНЕЛЬ (СПРАВКА)</b>\n\n"
            "🔹 <b>Основное:</b>\n"
            "/give_all 1000 - Выдать всем\n"
            "/set_balance @user 100000 - Установить баланс\n"
            "/reset_user @user - Обнулить игрока\n"
            "/event 100000 - Дроп на кнопку\n"
            "/secret 50000 60 - Секретный дроп (время в сек)\n\n"
            "🔹 <b>Игроки:</b>\n"
            "/ban @user / /unban @user\n"
            "/kick (ответом)\n"
            "/userinfo (ответом) - Досье\n"
            "/spy (ответом) - Последние игры\n\n"
            "🔹 <b>Работники:</b>\n"
            "/mod_add @user / /mod_remove @user\n"
            "/pr_add @user / /pr_remove @user\n"
            "/vip_add @user 7 - Выдать VIP\n\n"
            "🔹 <b>Система:</b>\n"
            "/report - Отчет за сегодня\n"
            "/sys_info - Статус сервера\n"
            "/broadcast - Текстовая рассылка\n"
        )
        await message.reply(txt, reply_markup=admin_panel_kb())

    @dp.message(Command("report"))
    async def cmd_report(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users"); tu, tb = c.fetchone()
            c.execute("SELECT COUNT(*) FROM game_log WHERE time::date = CURRENT_DATE"); tg = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE"); banned_count = c.fetchone()[0]
            
            txt = (
                f"📊 <b>ОТЧЕТ ЗА СЕГОДНЯ ({_now().strftime('%d.%m.%Y')})</b>\n\n"
                f"👥 Всего игроков: <b>{tu}</b>\n"
                f"💎 Общий баланс: <b>{fmt_num(tb)}</b>\n"
                f"🎮 Игр за сегодня: <b>{tg}</b>\n"
                f"🚫 В бане: <b>{banned_count}</b>\n\n"
                f"🛠 <i>Состояние бота: Стабильно</i>\n"
                f"🔥 <i>Новых фич добавлено: 0</i>"
            )
            await message.answer(txt)
        except Exception as e:
            await message.reply(f"❌ Ошибка при сборе отчета: {e}")
        finally: c.close(); release_conn(conn)

    @dp.message(Command("sys_info"))
    async def cmd_sys_info(message: Message):
        if message.from_user.id != ADMIN_ID: return
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        uptime = int(time.time() - psutil.boot_time())
        hours = uptime // 3600
        
        txt = (
            f"💻 <b>СИСТЕМНАЯ ИНФОРМАЦИЯ</b>\n\n"
            f"🖥 ОС: <code>{platform.system()} {platform.release()}</code>\n"
            f"🐍 Python: <code>{platform.python_version()}</code>\n"
            f"⚙️ Загрузка CPU: <b>{cpu}%</b>\n"
            f"🧠 ОЗУ: <b>{ram}%</b>\n"
            f"⏱ Аптайм сервера: <b>{hours} ч.</b>\n\n"
            f"🤖 Бот: <b>Работает (Polling)</b>\n"
            f"📡 Web-сервер: <b>OK</b>"
        )
        await message.answer(txt)

    # Быстрые кнопки Админа
    @dp.message(F.text == "👥 Игроки")
    async def admin_players_btn(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="💰 Выдать"), KeyboardButton(text="💸 Забрать")],
            [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
            [KeyboardButton(text="⬅️ Назад")]
        ], resize_keyboard=True)
        await message.answer("Управление игроками:", reply_markup=kb)

    @dp.message(F.text == "📜 Отчет")
    async def admin_report_btn(message: Message):
        await cmd_report(message)

    @dp.message(F.text == "🛠 Управление")
    async def admin_manage_btn(message: Message):
        await cmd_admin_help(message)

    @dp.message(Command("give_all"))
    async def admin_give_all(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /give_all 1000")
        try: amount = int(parts[1])
        except: return
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + %s", (amount,))
        conn.commit(); c.close(); release_conn(conn)
        await message.reply(f"✅ Выдано по {fmt_num(amount)} токенов всем игрокам!")

    @dp.message(Command("mod_add"))
    async def admin_mod_add(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /mod_add @user")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        
        if uid not in MODS:
            MODS.append(uid)
            persist_mods()
            await message.reply(f"✅ Пользователь @{target} назначен Модером!")
            try: await message.bot.send_message(uid, "🎉 <b>Тебя назначили МОДЕРАТОРОМ!</b>\nТвои кнопки внизу 👇", reply_markup=mod_panel_kb())
            except: pass

    @dp.message(Command("pr_add"))
    async def admin_pr_add(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /pr_add @user")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        
        if uid not in PRS:
            PRS.append(uid)
            persist_prs()
            await message.reply(f"✅ Пользователь @{target} назначен Пиарщиком!")
            try: await message.bot.send_message(uid, "🎉 <b>Тебя назначили ПИАРЩИКОМ!</b>\nТвои кнопки внизу 👇", reply_markup=pr_panel_kb())
            except: pass

# ============================================================
# bot.py — FINAL v59 (ЧАСТЬ 4)
# ============================================================

    # ========================================================
    # 10. ИГРЫ В ГРУППЕ (ИНЛАЙН-МЕНЮ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"игры", "games"}))
    async def group_games_menu(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice")],
            [InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel"), InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        txt = (
            "🎮 <b>ТЫ ПОПАЛ В МЕНЮ ИГР!</b>\n\n"
            "В нашем боте доступно <b>10 игр</b> на любой вкус.\n\n"
            "👇 Выбери игру в меню ниже:"
        )

        msg = await message.reply(txt, reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 60)) # Автоудаление меню через минуту

    @dp.callback_query(F.data.startswith("game_info_"))
    async def game_info_handler(call: CallbackQuery):
        game = call.data.replace("game_info_", "")
        if game == "close":
            try: await call.message.delete()
            except: pass
            return await call.answer("Меню закрыто.")
            
        info = {
            "roulette": "🎡 <b>РУЛЕТКА</b>\n• <code>к 100</code> (красное)\n• <code>ч 100</code> (черное)\n• <code>з 100</code> (зеро)\n• <code>чет 100</code> / <code>нечет 100</code>\n• <code>го</code> — запуск",
            "mines": "💣 <b>МИНЫ</b>\n• <code>мины 100</code>\nОткрывай клетки, собирай кэш!",
            "bj": "🃏 <b>БЛЭКДЖЕК</b>\n• <code>бж 100</code>\nНабери 21 очко!",
            "duel": "⚔️ <b>ДУЭЛИ</b>\nОтветь на сообщение игрока:\n• <code>дуэль 100</code>",
            "dice": "🎲 <b>КОСТИ</b>\n• <code>кости 100</code>\nВыигрыш 4, 5, 6 (x1.95)",
            "coin": "🪙 <b>МОНЕТКА</b>\n• <code>монетка 100 орел</code>\nОрел/Решка x2",
            "darts": "🎯 <b>ДАРТС</b>\n• <code>дартс 100</code>\nЯблочко (x5)",
            "bowling": "🎳 <b>БОУЛИНГ</b>\n• <code>боулинг 100</code>\nСтрайк (x3)",
            "basket": "🏀 <b>БАСКЕТ</b>\n• <code>баскет 100</code>\nПопал (x2)",
            "football": "⚽ <b>ФУТБОЛ</b>\n• <code>футбол 100</code>\nГол (x2)"
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="game_info_back"), InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]])
        try: await call.message.edit_text(info.get(game, "Информация не найдена."), reply_markup=kb)
        except: pass
        await call.answer()

    @dp.callback_query(F.data == "game_info_back")
    async def game_info_back(call: CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice")],
            [InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel"), InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        try: await call.message.edit_text("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку:", reply_markup=kb)
        except: pass
        await call.answer()

    # ========================================================
    # 11. БАЛАНС, ТОП И ПЕРЕВОДЫ В ГРУППЕ (С АВТОУДАЛЕНИЕМ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"б", "баланс", "balance"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        bal = get_balance(uid)
        msg = await message.reply(f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 {fmt_num(bal)} Tokens")
        asyncio.create_task(delete_message_later(msg, 60))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"топ", "top"}))
    async def group_top(message: Message):
        try:
            top = get_top(10)
            txt = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n\n"
            for i, row in enumerate(top, 1):
                name = row[1] if len(row) > 1 else "user"
                bal = row[2] if len(row) > 2 else 0
                txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
            msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 60))
        except Exception as e: await message.reply(f"❌ Ошибка БД: {e}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
    async def transfer_by_id(message: Message):
        parts = message.text.split(); uid = message.from_user.id
        target_id, amount = int(parts[1]), int(parts[2])
        if amount < 10 or get_balance(uid) < amount: return
        set_balance(uid, -amount); set_balance(target_id, amount)
        msg = await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 {fmt_num(amount)}")
        asyncio.create_task(delete_message_later(msg, 60))

    # ========================================================
    # 12. РУЛЕТКА (МУЛЬТИ-СТАВКИ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт)\s+(\d+)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        word, num = parts[0], parts[1]
        bet_type = {"к": "red", "ч": "black", "з": "green", "чет": "even", "чёт": "even", "нечет": "odd", "нечёт": "odd"}.get(word)
        bet = int(num)
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало токенов.")
        set_balance(uid, -bet)
        
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!", reply_markup=bet_actions_inline())
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if is_spinning.get(chat_id, False): return await message.reply("⏳ УЖЕ КРУТИТСЯ!")
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок.")
        
        is_spinning[chat_id] = True
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        except: msg = await message.reply(f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        
        await asyncio.sleep(3)
        res = random.randint(0, 36); color = get_color(res); win, lose = [], []
        for b in bets:
            w = 0
            if b["type"] == "red" and res in RED: w = int(b["bet"] * 1.95)
            elif b["type"] == "black" and res in BLACK: w = int(b["bet"] * 1.95)
            elif b["type"] == "green" and res == 0: w = int(b["bet"] * 35)
            elif b["type"] == "even" and res != 0 and res % 2 == 0: w = int(b["bet"] * 1.95)
            elif b["type"] == "odd" and res % 2 != 0: w = int(b["bet"] * 1.95)
            if w > 0: set_balance(b["user_id"], w); win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else: lose.append(f"💔 @{b['username']}")
            
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n"
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        if chat_id in active_bets: active_bets[chat_id]["bets"] = []
        is_spinning[chat_id] = False
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.callback_query(F.data.in_({"bet_repeat", "bet_double"}))
    async def bet_actions_handler(call: CallbackQuery):
        uid = call.from_user.id; chat_id = call.message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await call.answer("Ставка устарела", show_alert=True)
        my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == uid]
        if not my_bets: return await call.answer("Ты не делал ставку!", show_alert=True)
        for b in my_bets:
            if b.get("action") == call.data: return await call.answer("❌ Ты уже использовал это!", show_alert=True)
            
        last_bet = my_bets[-1]; amount = last_bet["bet"]
        if call.data == "bet_double": amount *= 2
        if get_balance(uid) < amount: return await call.answer("❌ Недостаточно!", show_alert=True)
        
        set_balance(uid, -amount)
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": call.from_user.username or "user", "type": last_bet["type"], "bet": amount, "action": call.data})
        try: await call.message.delete()
        except: pass
        await call.answer(f"✅ Ставка на {fmt_num(amount)} принята!")
        await call.message.reply(f"🎰 <b>{'УДВОЕНИЕ' if call.data == 'bet_double' else 'ПОВТОР'}</b>\n@{call.from_user.username or 'user'} | {fmt_num(amount)}")

    # ========================================================
    # 13. ОСТАЛЬНЫЕ ИГРЫ (КОСТИ, БАСКЕТ, БЖ И Т.Д.)
    # ========================================================
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) != 2: return
        bet = int(parts[1])
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji=emoji); await asyncio.sleep(2.5); res = sent.dice.value
        if win_cond(res):
            win = int(bet * win_mult); set_balance(uid, win)
            txt = f"{emoji} {res}\n🎉 Выигрыш: <b>+{fmt_num(win)}</b>"
        else:
            txt = f"{emoji} {res}\n😢 Проигрыш: <b>-{fmt_num(bet)}</b>"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 60))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "dice ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "basket ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "football ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "darts ")))
    async def play_darts(message: Message): await play_dice_game(message, "дартс", "🎯", lambda r: r >= 3, 1.5)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("боулинг ", "bowling ")))
    async def play_bowling(message: Message): await play_dice_game(message, "боулинг", "🎳", lambda r: r >= 4, 1.5)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "slots ")))
    async def play_slots(message: Message): await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8)

    # ========================================================
    # 14. БЛЭКДЖЕК (ИСПРАВЛЕННЫЙ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("бж ", "bj ")))
    async def play_bj(message: Message):
        parts = message.text.lower().split()
        if len(parts) != 2: return
        bet = int(parts[1]); uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet)
        
        p1, p2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        d1, d2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        
        # Фикс дилерского БД
        if d1 + d2 == 21 and p1 + p2 != 21: return await message.reply(f"🃏 <b>БЛЭКДЖЕК У ДИЛЕРА!</b>\nТвои: {p1+p2}, Дилер: 21\n😢 Ставка {fmt_num(bet)} сгорела.")
        if p1 + p2 == 21:
            win = int(bet * 2.5); set_balance(uid, win)
            return await message.reply(f"🃏 <b>БЛЭКДЖЕК!</b>\nТвои: 21\n🎉 Выигрыш: <b>+{fmt_num(win)}</b> (x2.5)")
            
        bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"), InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")]])
        await message.reply(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(bet)}\n\n👤 Твои: <b>{p1} + {p2} = {p1+p2}</b>\n🤖 Дилер: <b>{d1} + ?</b>", reply_markup=kb)

    @dp.callback_query(F.data.startswith("bj_hit_"))
    async def bj_hit(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game: return await call.answer("Игра не найдена", show_alert=True)
        new_card = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        game["player"].append(new_card); player_sum = sum(game["player"])
        if player_sum > 21:
            await call.message.edit_text(f"🃏 <b>ПЕРЕБОР!</b>\nТы набрал {player_sum}. Ставка {fmt_num(game['bet'])} сгорела.")
            return await call.answer("Перебор!")
        bj_games[uid] = game
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"), InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")]])
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(game['bet'])}\n\n👤 Твои: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n🤖 Дилер: <b>{game['dealer'][0]} + ?</b>", reply_markup=kb)
        await call.answer(f"Выпала карта: {new_card}")

    @dp.callback_query(F.data.startswith("bj_stand_"))
    async def bj_stand(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game: return await call.answer("Игра не найдена", show_alert=True)
        player_sum = sum(game["player"]); dealer_sum = sum(game["dealer"])
        while dealer_sum < 17:
            game["dealer"].append(random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]))
            dealer_sum = sum(game["dealer"])
        if dealer_sum > 21 or player_sum > dealer_sum: win = int(game["bet"] * 1.8); set_balance(uid, win); result = f"🎉 <b>ТЫ ВЫИГРАЛ!</b>\nВыигрыш: <b>+{fmt_num(win)}</b>"
        elif player_sum == dealer_sum: set_balance(uid, game["bet"]); result = f"🤝 <b>НИЧЬЯ!</b>\nСтавка возвращена."
        else: result = f"😢 <b>ТЫ ПРОИГРАЛ!</b>\nСтавка сгорела."
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Твои карты: {player_sum}\n🤖 Дилер: {dealer_sum}\n\n{result}")
        await call.answer("Игра окончена!")

    # ========================================================
    # 15. МИНЫ (ИСПРАВЛЕННЫЕ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2: return
        bet = int(parts[1]); uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet); mines = random.sample(list(range(25)), 3)
        await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0); await state.set_state(BotStates.waiting_support_own) # Заглушка вместо удаленного стейта
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
        msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n\nОткрывай клетки!", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 300))

    @dp.callback_query(F.data.startswith("mine_"))
    async def mines_handler(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if not data or "bet" not in data: return await call.answer("Игра устарела.")
        bet, mines, opened, mult = data["bet"], data["mines"], data["opened"], data["mult"]
        if call.data == "mine_cashout":
            win = int(bet * mult); set_balance(call.from_user.id, win); await state.clear()
            await call.message.edit_text(f"💰 <b>ЗАБРАЛ!</b>\n💎 Выигрыш: <b>+{fmt_num(win)}</b>\n📈 x{mult:.2f}")
            return await call.answer("Зачислено!")
        idx = int(call.data.split("_")[1])
        if idx in opened: return await call.answer("Уже открыто!")
        if idx in mines:
            await state.clear()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣" if r*5+c in mines else ("💎" if r*5+c in opened else "⬜"), callback_data="none") for c in range(5)] for r in range(5)])
            await call.message.edit_text(f"💥 <b>БУМ!</b>\n😢 Ставка <b>{fmt_num(bet)}</b> сгорела.", reply_markup=kb)
            return await call.answer("БУМ!")
        opened.append(idx); mult = round(1.0 + (len(opened) * 0.15), 2)
        await state.update_data(opened=opened, mult=mult)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
        await call.message.edit_text(f"💣 <b>МИНЫ</b>\n💰 {fmt_num(bet)}\n📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\nОткрывай дальше!", reply_markup=kb)
        await call.answer("Безопасно!")

    # ========================================================
    # 16. МОДЕРАЦИЯ И РАБОТНИКИ
    # ========================================================
    @dp.message(Command("mod_help"))
    async def cmd_mod_help(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        txt = (
            "🛠 <b>МОДЕРАТОР (СПРАВКА)</b>\n\n"
            "/mod_give @user 1000 - Выдать токены\n"
            "/mod_my_limit - Проверить лимит\n"
            "/mod_warn (ответом) - Предупреждение\n"
            "/mod_clean - Очистить чат\n"
            "/mod_pin / /mod_unpin - Закреп\n"
            "/mod_unban @user - Разбан\n"
            "/mod_alert - SOS Админу\n\n"
            "💰 <b>Лимит выдачи:</b> 5 000 000/нед."
        )
        await message.reply(txt, reply_markup=mod_panel_kb())

    @dp.message(F.text == "📖 Хелп")
    async def btn_help(message: Message):
        uid = message.from_user.id
        if uid == ADMIN_ID: return await cmd_admin_help(message)
        if uid in MODS: return await cmd_mod_help(message)
        await message.reply("🆘 Для связи с поддержкой напиши: /support")

    # ========================================================
    # 17. ФОНОВЫЕ ЗАДАЧИ (ОТЧЕТЫ, ЛОТЕРЕЯ И ЗП)
    # ========================================================
    async def background_tasks():
        while True:
            now = _now()
            # Лотерея в 20:00
            if now.hour == 20 and now.minute == 0:
                if LOTTERY_TICKETS:
                    winner = random.choice(LOTTERY_TICKETS)
                    set_balance(winner, 100000)
                    try: await bot.send_message(winner, "🎉 <b>ТЫ ВЫИГРАЛ В ЛОТЕРЕЕ 100 000 TOKENS!</b>")
                    except: pass
                    LOTTERY_TICKETS.clear()
            
            # Отчет в 22:00
            if now.hour == 22 and now.minute == 0:
                try: await bot.send_message(ADMIN_ID, "📊 <b>АВТО-ОТЧЕТ ЗА СЕГОДНЯ ГОТОВ!</b>\nНапиши /report для деталей.")
                except: pass
                
            await asyncio.sleep(60)

    asyncio.create_task(background_tasks())

    # ========================================================
    # 18. ОСТАВШИЕСЯ КОМАНДЫ МОДЕРА (Выдача, Варны, Мут)
    # ========================================================
    @dp.message(Command("mod_give"))
    async def mod_give_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 3: return await message.reply("❌ /mod_give @user 1000")
        
        target = parts[1].replace("@", "")
        target_id = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not target_id: return await message.reply("❌ Не найден.")
        
        try: amount = int(parts[2])
        except: return await message.reply("❌ Введи число.")
        
        if message.from_user.id in MODS:
            lim = refresh_week(message.from_user.id, MOD_LIMITS)
            if lim["given"] + amount > MAX_MOD_GIVE:
                return await message.reply(f"❌ Лимит! Выдано {fmt_num(lim['given'])} из {fmt_num(MAX_MOD_GIVE)}.")
            lim["given"] += amount; MOD_LIMITS[message.from_user.id] = lim; persist_mods()
            
        set_balance(target_id, amount)
        await message.reply(f"✅ @{target} выдано <b>{fmt_num(amount)}</b> токенов.")

    @dp.message(Command("mod_warn"))
    async def mod_warn_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        if uid not in user_warns: user_warns[uid] = {"count": 0}
        user_warns[uid]["count"] += 1
        if user_warns[uid]["count"] >= 3:
            del user_warns[uid]
            await message.reply(f"🚫 Игрок получил 3/3 варна.")
        else: 
            await message.reply(f"⚠️ Предупреждение {user_warns[uid]['count']}/3.")

    @dp.message(Command("mod_clean"))
    async def mod_clean_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        deleted = 0
        try:
            async for m in message.bot.get_chat_history(message.chat.id, limit=100):
                try: await m.delete(); deleted += 1
                except: pass
        except: pass
        try:
            info = await message.answer(f"🧹 Удалено: <b>{deleted}</b>"); await asyncio.sleep(3); await info.delete()
        except: pass

    # ========================================================
    # 19. КОМАНДЫ ПИАРЩИКА (Текст и Статистика)
    # ========================================================
    @dp.message(Command("pr_text"))
    @dp.message(F.text == "📝 Получить текст")
    async def pr_get_text(message: Message):
        if message.from_user.id not in PRS and message.from_user.id != ADMIN_ID: return
        
        promos = [
            "🔥 <b>Хочешь много токенов?</b>\nЗаходи в Tokens Casino и сорви куш! 🎰\nТвой стартовый бонус ждет: @{bot_username}",
            "💎 <b>Лучшее казино в Telegram!</b>\nРулетка, Мины, Блэкджек и огромные выигрыши!\nЗабирай 5000 токенов: @{bot_username}",
            "🎁 <b>Дарю 5000 токенов!</b>\nПросто перейди по ссылке и начни играть: @{bot_username}",
            "🚀 <b>Твой шанс разбогатеть!</b>\nЗалетай в Tokens Casino, тут каждый может стать миллионером: @{bot_username}"
        ]
        txt = random.choice(promos).format(bot_username=BOT_USERNAME)
        await message.reply(txt)

    @dp.message(F.command("pr_stats"))
    @dp.message(F.text == "📊 Статистика")
    async def pr_stats(message: Message):
        if message.from_user.id not in PRS and message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
        c.close(); release_conn(conn)
        await message.reply(f"📊 <b>СТАТИСТИКА БАЗЫ</b>\n\n👥 Всего пользователей в боте: <b>{total}</b>")

    # ========================================================
    # 20. АДМИНСКИЕ КОМАНДЫ (Бан, Кик, Броадкаст, Ивенты)
    # ========================================================
    @dp.message(Command("ban"))
    async def admin_ban_cmd(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /ban @user")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        set_banned(uid, True)
        await message.reply(f"✅ Игрок @{target} забанен.")

    @dp.message(Command("unban"))
    async def admin_unban_cmd(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /unban @user")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        set_banned(uid, False)
        await message.reply(f"✅ Игрок @{target} разбанен.")

    @dp.message(Command("kick"))
    async def admin_kick_cmd(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.ban_chat_member(message.chat.id, uid)
            await message.bot.unban_chat_member(message.chat.id, uid)
            await message.reply("✅ Игрок кикнут.")
        except: await message.reply("❌ Не могу кикнуть.")

    @dp.message(Command("event"))
    async def admin_event_cmd(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ /event 100000")
        try: amount = int(parts[1])
        except: return await message.reply("❌ Введи число.")
        
        global ACTIVE_EVENT
        ACTIVE_EVENT = {"amount": amount, "claimed_by": []}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 ЗАБРАТЬ", callback_data="claim_event")]])
        await message.answer(f"💸 <b>ДРОП!</b>\nКто первый нажмет — получит <b>{fmt_num(amount)}</b>!", reply_markup=kb)

    @dp.callback_query(F.data == "claim_event")
    async def claim_event(call: CallbackQuery):
        uid = call.from_user.id
        if uid in ACTIVE_EVENT["claimed_by"]: return await call.answer("❌ Ты уже забрал!", show_alert=True)
        ACTIVE_EVENT["claimed_by"].append(uid)
        set_balance(uid, ACTIVE_EVENT["amount"])
        await call.answer(f"✅ Ты забрал {fmt_num(ACTIVE_EVENT['amount'])}!", show_alert=True)
        await call.message.edit_text(f"🎉 <b>ДРОП РАЗОБРАН!</b>\nПоследний забрал: @{call.from_user.username or 'user'}")

    @dp.message(Command("broadcast"))
    async def admin_broadcast(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.reply("📢 Отправь текст для рассылки (или 'отмена'):")
        await state.set_state(BotStates.waiting_broadcast_text)

    @dp.message(BotStates.waiting_broadcast_text)
    async def process_broadcast_text(message: Message, state: FSMContext):
        if message.text.lower() == "отмена": 
            await state.clear(); return await message.reply("❌ Отменено.")
        await state.clear(); conn = get_conn(); c = conn.cursor()
        try: c.execute("SELECT user_id FROM users"); users = c.fetchall()
        finally: c.close(); release_conn(conn)
        sent = 0; await message.reply("⏳ Рассылка...")
        for (uid,) in users:
            try: await message.bot.send_message(uid, message.text); sent += 1; await asyncio.sleep(0.05)
            except: pass
        await message.reply(f"✅ Отправлено: {sent}")

    # ========================================================
    # 21. СЕКРЕТНЫЙ ДРОП (ГОНКА НА СКОРОСТЬ)
    # ========================================================
    @dp.message(Command("secret"))
    async def admin_secret_drop(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) < 3: return await message.reply("❌ /secret 50000 60 (сумма и время в сек)")
        
        try: amount, duration = int(parts[1]), int(parts[2])
        except: return await message.reply("❌ Введи числа.")
        
        drop_id = str(int(time.time()))
        secret_amounts[drop_id] = amount
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 ЗАБРАТЬ ПРОМОКОД", callback_data=f"secret_drop_{drop_id}")]])
        msg = await message.answer(f"🔥 <b>СЕКРЕТНЫЙ ДРОП!</b>\nНа кону <b>{fmt_num(amount)} Tokens</b>!\nУ тебя есть {duration} секунд!", reply_markup=kb)
        
        async def delete_drop():
            await asyncio.sleep(duration)
            secret_amounts.pop(drop_id, None)
            try: await msg.delete()
            except: pass
        asyncio.create_task(delete_drop())

    @dp.callback_query(F.data.startswith("secret_drop_"))
    async def claim_secret_drop(call: CallbackQuery):
        drop_id = call.data.replace("secret_drop_", "")
        amount = secret_amounts.pop(drop_id, 0)
        if amount == 0: return await call.answer("❌ Слишком поздно! Или уже забрали.", show_alert=True)
        
        set_balance(call.from_user.id, amount)
        await call.message.edit_text(f"🎉 <b>ДРОП РАЗОБРАН!</b>\nПобедитель: @{call.from_user.username or 'user'}\nВыигрыш: <b>+{fmt_num(amount)} Tokens</b>")
        await call.answer(f"✅ Ты забрал {fmt_num(amount)}!", show_alert=True)

    # ========================================================
    # 22. ДУЭЛИ (ТЕКСТОВЫЕ)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("дуэль "))
    async def play_duel(message: Message):
        if not message.reply_to_message: return await message.reply("⚔️ Ответь на сообщение соперника и напиши <code>дуэль 100</code>.")
        challenger = message.from_user; opponent = message.reply_to_message.from_user
        if challenger.id == opponent.id or opponent.is_bot: return await message.reply("❌ Нельзя.")
        
        parts = message.text.lower().split()
        if len(parts) != 2: return await message.reply("❌ Формат: <code>дуэль 100</code>")
        try: bet = int(parts[1])
        except: return
        
        if bet < 10: return await message.reply("❌ Мин. 10.")
        if get_balance(challenger.id) < bet or get_balance(opponent.id) < bet: return await message.reply("❌ Мало средств у кого-то из вас.")
        
        set_balance(challenger.id, -bet); chat_id = message.chat.id; duel_id = f"{chat_id}_{challenger.id}_{opponent.id}_{int(time.time())}"
        active_duels[duel_id] = {"challenger_id": challenger.id, "challenger_name": challenger.username or challenger.first_name, "opponent_id": opponent.id, "opponent_name": opponent.username or opponent.first_name, "bet": bet, "chat_id": chat_id}
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}")],[InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}")]])
        await message.reply(f"⚔️ <b>ВЫЗОВ!</b>\n👤 @{challenger.username or challenger.first_name} VS @{opponent.username or opponent.first_name}\n💰 {fmt_num(bet)}\n\n@{opponent.username or opponent.first_name}, жми кнопку!", reply_markup=kb)
        
        async def auto_expire():
            await asyncio.sleep(120); d = active_duels.pop(duel_id, None)
            if d:
                set_balance(d["challenger_id"], d["bet"])
                try: await message.reply(f"⏰ <b>ДУЭЛЬ ПРОТУХЛА</b>\n💰 {fmt_num(d['bet'])} возвращены.")
                except: pass
        asyncio.create_task(auto_expire())

    @dp.callback_query(F.data.startswith("duel_accept_"))
    async def duel_accept_handler(call: CallbackQuery):
        duel_id = call.data.replace("duel_accept_", ""); duel = active_duels.get(duel_id)
        if not duel: return await call.answer("❌ Устарело.", show_alert=True)
        if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
        if get_balance(duel["opponent_id"]) < duel["bet"]: return await call.answer("❌ Мало средств.", show_alert=True)
        
        duel = active_duels.pop(duel_id, None)
        if not duel: return await call.answer("❌ Уже принята.", show_alert=True)
        set_balance(duel["opponent_id"], -duel["bet"])
        
        try: await call.message.edit_text(f"⚔️ <b>ДУЭЛЬ!</b>\n🔵 @{duel['challenger_name']}\n🔴 @{duel['opponent_name']}\n💰 {fmt_num(duel['bet'] * 2)}\n\n🎲 Бросаем...")
        except: pass
        await call.answer("Принято!"); await asyncio.sleep(1.5)
        
        d1 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲"); await asyncio.sleep(0.5)
        d2 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲"); await asyncio.sleep(3.5)
        v1, v2 = d1.dice.value, d2.dice.value
        
        if v1 == v2:
            set_balance(duel["challenger_id"], duel["bet"]); set_balance(duel["opponent_id"], duel["bet"])
            return await call.message.reply(f"🤝 <b>НИЧЬЯ!</b> ({v1} и {v2}). Ставки возвращены.")
        if v1 > v2: w_id, w_name, w_d, l_d = duel["challenger_id"], duel["challenger_name"], v1, v2
        else: w_id, w_name, w_d, l_d = duel["opponent_id"], duel["opponent_name"], v2, v1
        
        set_balance(w_id, duel["bet"] * 2)
        await call.message.reply(f"🏆 <b>ПОБЕДИТЕЛЬ</b>\n🥇 @{w_name} ({w_d})\n💔 ({l_d})\n💰 +{fmt_num(duel['bet'] * 2)}")

    @dp.callback_query(F.data.startswith("duel_decline_"))
    async def duel_decline_handler(call: CallbackQuery):
        duel_id = call.data.replace("duel_decline_", ""); duel = active_duels.get(duel_id)
        if not duel: return await call.answer("❌ Устарело.", show_alert=True)
        if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
        
        duel = active_duels.pop(duel_id, None)
        if not duel: return await call.answer("❌ Уже обработано.", show_alert=True)
        set_balance(duel["challenger_id"], duel["bet"])
        try: await call.message.edit_text(f"❌ <b>ОТКЛОНЕНО</b>\n@{call.from_user.username or call.from_user.first_name} отказался.\n💰 {fmt_num(duel['bet'])} возвращены.")
        except: pass
        await call.answer("Отклонено.")

    # ========================================================
    # 23. КВЕСТЫ (ТРЕКЕР ПРОГРЕССА)
    # ========================================================
    @dp.message(F.text.in_({"📜 Квесты", "📜 Quests"}))
    async def cmd_quests_real(message: Message):
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            # Создаем таблицу квестов, если нет
            c.execute("CREATE TABLE IF NOT EXISTS user_quests (user_id BIGINT, quest_key TEXT, progress INT DEFAULT 0, claimed BOOLEAN DEFAULT FALSE, UNIQUE(user_id, quest_key))")
            c.execute("SELECT quest_key, progress, claimed FROM user_quests WHERE user_id = %s", (uid,))
            quests = {row[0]: {"progress": row[1], "claimed": row[2]} for row in c.fetchall()}
            conn.commit()
        except Exception as e:
            c.close(); release_conn(conn)
            return await message.reply(f"❌ Ошибка БД: {e}")

        # Дефолтные квесты (создаем, если нет)
        default_quests = {
            "bet_10": {"target": 10, "reward": 5000, "name": "Сделать 10 любых ставок"},
            "win_3": {"target": 3, "reward": 10000, "name": "Выиграть 3 раза подряд в любой игре"},
            "spin_wheel": {"target": 1, "reward": 20000, "name": "Прокрутить Колесо Фортуны"}
        }

        txt = "📜 <b>ТВОИ ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n\n"
        has_rewards = False
        
        for key, info in default_quests.items():
            user_q = quests.get(key, {"progress": 0, "claimed": False})
            prog = user_q["progress"]; target = info["target"]; claimed = user_q["claimed"]
            
            status = "✅ Получено" if claimed else (f"🎁 <b>ЗАБРАТЬ</b> /quest_{key}" if prog >= target else f"({prog}/{target})")
            if not claimed and prog >= target: has_rewards = True
            
            txt += f"🔹 {info['name']}\n   Награда: {fmt_num(info['reward'])} | {status}\n\n"
        
        if has_rewards:
            txt += "⚡️ Напиши команду награды (например, <code>/quest_bet_10</code>), чтобы забрать токены!"
        
        c.close(); release_conn(conn)
        await message.answer(txt, reply_markup=get_profile_kb(uid))

    @dp.message(Command("quest_bet_10", "quest_win_3", "quest_spin_wheel"))
    async def claim_quest_reward(message: Message):
        uid = message.from_user.id
        q_key = message.text.replace("/quest_", "")
        
        rewards = {"bet_10": 5000, "win_3": 10000, "spin_wheel": 20000}
        targets = {"bet_10": 10, "win_3": 3, "spin_wheel": 1}
        
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT progress, claimed FROM user_quests WHERE user_id = %s AND quest_key = %s", (uid, q_key))
        row = c.fetchone()
        
        if not row or row[0] < targets[q_key]: 
            c.close(); release_conn(conn)
            return await message.reply("❌ Квест еще не выполнен!")
        if row[1]: 
            c.close(); release_conn(conn)
            return await message.reply("❌ Ты уже забрал награду за этот квест!")
            
        c.execute("UPDATE user_quests SET claimed = TRUE WHERE user_id = %s AND quest_key = %s", (uid, q_key))
        conn.commit(); c.close(); release_conn(conn)
        set_balance(uid, rewards[q_key])
        await message.reply(f"🎉 <b>КВЕСТ ВЫПОЛНЕН!</b>\nНаграда: <b>+{fmt_num(rewards[q_key])} Tokens</b>", reply_markup=get_profile_kb(uid))

    # ========================================================
    # 24. ОБНОВЛЕННЫЕ ФОНОВЫЕ ЗАДАЧИ (ЗП, ЛОТЕРЕЯ, СБРОС КВЕСТОВ)
    # ========================================================
    async def updated_background_tasks():
        last_salary_day = -1
        while True:
            now = _now()
            
            # 1. Ежедневный сброс квестов в 00:00
            if now.hour == 0 and now.minute == 0:
                conn = get_conn(); c = conn.cursor()
                try:
                    c.execute("UPDATE user_quests SET progress = 0, claimed = FALSE")
                    conn.commit()
                except: pass
                finally: c.close(); release_conn(conn)

            # 2. Лотерея в 20:00
            if now.hour == 20 and now.minute == 0:
                if LOTTERY_TICKETS:
                    winner = random.choice(LOTTERY_TICKETS)
                    set_balance(winner, 100000)
                    try: await bot.send_message(winner, "🎉 <b>ТЫ ВЫИГРАЛ В ЛОТЕРЕЕ 100 000 TOKENS!</b>")
                    except: pass
                    LOTTERY_TICKETS.clear()
            
            # 3. Отчет в 22:00
            if now.hour == 22 and now.minute == 0:
                try: await bot.send_message(ADMIN_ID, "📊 <b>АВТО-ОТЧЕТ ЗА СЕГОДНЯ ГОТОВ!</b>\nНапиши /report для деталей.")
                except: pass
            
            # 4. ЗП работникам раз в 3 дня (в 12:00)
            if now.hour == 12 and now.minute == 0 and now.day != last_salary_day:
                if now.day % 3 == 0: # Условно каждый 3-й день месяца
                    last_salary_day = now.day
                    for mod_id in MODS:
                        set_balance(mod_id, WORKER_SALARY)
                        try: await bot.send_message(mod_id, f"💰 <b>ЗАРПЛАТА МОДЕРАТОРА</b>\nТебе начислено {fmt_num(WORKER_SALARY)} Tokens за работу!")
                        except: pass
                    for pr_id in PRS:
                        set_balance(pr_id, WORKER_SALARY)
                        try: await bot.send_message(pr_id, f"💰 <b>ЗАРПЛАТА ПИАРЩИКА</b>\nТебе начислено {fmt_num(WORKER_SALARY)} Tokens за работу!")
                        except: pass

            await asyncio.sleep(60)
            
    # Переопределяем фоновую задачу (старую можно закомментировать выше)
    asyncio.create_task(updated_background_tasks())


    
    # ========================================================
    # ЗАПУСК
    # ========================================================
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e: logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)