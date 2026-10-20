import asyncio, logging, os, random, time, json, platform
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatPermissions
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, TZ_MINSK
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user,
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name
from state_manager import load_mods, save_mods, refresh_week

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_USERNAME = ""
MODS, MOD_LIMITS = load_mods()
MAX_MOD_GIVE = 5_000_000
credit_requests = {}
PROMO_CODES = {}
ACTIVE_EVENT = {"amount": 0, "claimed_by": []}

# Словарь переводов
TEXTS = {
    "ru": {
        "menu_games": "🎮 Игры", "menu_bal": "💰 Баланс", "menu_bank": "🏦 Банк", "menu_prof": "👤 Профиль",
        "menu_donate": "💎 Донат", "menu_help": "🆘 Помощь", "menu_lang": "🌐 Язык",
        "back": "⬅️ Назад", "lang_changed": "✅ Язык изменен на Русский",
        "welcome": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В {name}</b>\n\n👋 {first_name}!\n{bonus}👇 Выбери действие:",
        "profile": "👤 <b>ПРОФИЛЬ</b>\n🎖 Ранг: {rank}\n📊 XP: {xp}\n{bar}\n💰 Баланс: <b>{bal}</b>",
        "bank": "🏦 <b>БАНК</b>\n💎 На руках: <b>{bal}</b>\n🏦 В сейфе: <b>{bank}</b>\n\n👇 Действие:",
        "donate": "💎 <b>ДОНАТ</b>\n\nВыбери пакет:",
        "support": "🆘 <b>ПОДДЕРЖКА</b>\n\nВыбери проблему:",
        "support_own": "✍️ <b>СВОЙ ВОПРОС</b>\n\nНапиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.",
        "support_sent": "✅ Твой вопрос отправлен Админу.",
        "streak": "🎁 <b>БОНУС: ДЕНЬ {day}</b>\nТы получил: <b>+{amount} Tokens!</b>",
        "case_opened": "🎉 <b>КЕЙС ОТКРЫТ!</b>\nТы выиграл: <b>{amount} Tokens!</b>\n💰 Новый баланс: <b>{bal}</b>",
        "event_claim": "🎁 <b>ЗАБРАТЬ ДРОП</b>",
        "event_success": "🎉 Ты забрал <b>{amount}</b> токенов!",
        "event_fail": "❌ Ты уже забрал или дроп закончился!",
        "btn_dep": "📥 Положить", "btn_wit": "📤 Снять", "btn_cred": "💳 Кредит", "btn_repay": "💸 Погасить кредит"
    },
    "en": {
        "menu_games": "🎮 Games", "menu_bal": "💰 Balance", "menu_bank": "🏦 Bank", "menu_prof": "👤 Profile",
        "menu_donate": "💎 Donate", "menu_help": "🆘 Help", "menu_lang": "🌐 Language",
        "back": "⬅️ Back", "lang_changed": "✅ Language changed to English",
        "welcome": "👑 <b>WELCOME TO {name}</b>\n\n👋 {first_name}!\n{bonus}👇 Choose action:",
        "profile": "👤 <b>PROFILE</b>\n🎖 Rank: {rank}\n📊 XP: {xp}\n{bar}\n💰 Balance: <b>{bal}</b>",
        "bank": "🏦 <b>BANK</b>\n💎 On hands: <b>{bal}</b>\n🏦 In vault: <b>{bank}</b>\n\n👇 Action:",
        "donate": "💎 <b>DONATE</b>\n\nChoose package:",
        "support": "🆘 <b>SUPPORT</b>\n\nChoose problem:",
        "support_own": "✍️ <b>OWN QUESTION</b>\n\nWrite your question in one message.",
        "support_sent": "✅ Your question sent to Admin.",
        "streak": "🎁 <b>STREAK: DAY {day}</b>\nYou got: <b>+{amount} Tokens!</b>",
        "case_opened": "🎉 <b>CASE OPENED!</b>\nYou won: <b>{amount} Tokens!</b>\n💰 New balance: <b>{bal}</b>",
        "event_claim": "🎁 <b>CLAIM DROP</b>",
        "event_success": "🎉 You claimed <b>{amount}</b> tokens!",
        "event_fail": "❌ Already claimed or drop ended!",
        "btn_dep": "📥 Deposit", "btn_wit": "📤 Withdraw", "btn_cred": "💳 Credit", "btn_repay": "💸 Repay credit"
    }
}

def get_text(uid, key, **kwargs):
    lang = USER_LANGS.get(uid, "ru")
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, f"Error: {key}")
    return text.format(**kwargs) if kwargs else text

USER_LANGS = {}

def get_main_kb(uid):
    lang = USER_LANGS.get(uid, "ru")
    t = TEXTS[lang]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["menu_games"]), KeyboardButton(text=t["menu_bal"])],
        [KeyboardButton(text=t["menu_bank"]), KeyboardButton(text=t["menu_prof"])],
        [KeyboardButton(text=t["menu_donate"]), KeyboardButton(text=t["menu_help"])],
        [KeyboardButton(text=t["menu_lang"])]
    ], resize_keyboard=True)

def get_bank_kb(uid):
    lang = USER_LANGS.get(uid, "ru")
    t = TEXTS[lang]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["btn_dep"]), KeyboardButton(text=t["btn_wit"])],
        [KeyboardButton(text=t["btn_cred"]), KeyboardButton(text=t["btn_repay"])],
        [KeyboardButton(text=t["back"])]
    ], resize_keyboard=True)

def profile_menu_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="profile_bonus"), InlineKeyboardButton(text="📦 Кейс", callback_data="profile_case")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")]
    ])

def bet_actions_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data="bet_repeat"), InlineKeyboardButton(text="⏫ Удвоить", callback_data="bet_double")]
    ])

def mod_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],
        [KeyboardButton(text="⚠️ Предупреждение"), KeyboardButton(text="📌 Закрепить")],
        [KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS Админу")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В главное меню")]
    ], resize_keyboard=True)

def admin_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="👑 Админ-панель")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В главное меню")]
    ], resize_keyboard=True)

def admin_players_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💰 Выдать"), KeyboardButton(text="💸 Забрать")],
        [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
        [KeyboardButton(text="⬅️ В главное меню")]
    ], resize_keyboard=True)

def get_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED else "⚫"

async def delete_message_later(message: Message, delay: int = 150):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

async def send_clean_private(message: Message, text: str, reply_markup=None):
    uid = message.from_user.id
    if uid in last_bot_message:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message[uid])
        except: pass
    msg = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    last_bot_message[uid] = msg.message_id
    return msg

async def start_web_server():
    async def health(request): return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()

def _now(): return datetime.now(TZ_MINSK)
def persist_mods(): save_mods(MODS, MOD_LIMITS)

class BotStates(StatesGroup):
    waiting_bank_amount = State()
    waiting_donate_amount = State()
    waiting_support = State()
    waiting_broadcast_text = State()
    waiting_broadcast_photo = State()
    waiting_admin_give = State()
    waiting_admin_take = State()
    waiting_admin_ban = State()
    waiting_admin_unban = State()
    waiting_credit_name = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_credit_purpose = State()
    mines_game = State()
    waiting_promo_code = State()

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

# ============================================================
# MAIN
# ============================================================
async def main():
    asyncio.create_task(start_web_server())
    init_pool()
    init_db()
    
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username

    # --- СТАРТ И ПЕРЕВОД ---
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        ensure_user(uid, message.from_user.username or message.from_user.first_name)
        
        if message.chat.type != "private": return await message.reply(f"👋 ЛС: @{BOT_USERNAME}")
        if is_banned(uid): return await message.answer("🚫 Вы заблокированы / You are banned.")
        
        # Сохраняем язык в БД (создаем колонку lang, если нет)
        try:
            conn = get_conn(); c = conn.cursor()
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lang VARCHAR(2) DEFAULT 'ru'")
            conn.commit()
            c.execute("SELECT lang FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            if row and row[0]: USER_LANGS[uid] = row[0]
            c.close(); release_conn(conn)
        except: pass

        if uid == ADMIN_ID:
            try: await message.answer_photo(FSInputFile("welcome.jpg"), caption="👑 <b>С ВОЗВРАЩЕНИЕМ, БОСС!</b>", reply_markup=admin_panel_kb())
            except: await message.answer("👑 <b>С ВОЗВРАЩЕНИЕМ, БОСС!</b>", reply_markup=admin_panel_kb())
            return

        is_new = check_and_give_bonus(uid, START_BONUS)
        bonus = get_text(uid, "bonus", amount=fmt_num(START_BONUS)) + "\n\n" if is_new else ""
        txt = get_text(uid, "welcome", name=BOT_NAME.upper(), first_name=message.from_user.first_name, bonus=bonus)
        
        try: await message.answer_photo(FSInputFile("welcome.jpg"), caption=txt, reply_markup=get_main_kb(uid))
        except: await message.answer(txt, reply_markup=get_main_kb(uid))

    @dp.message(F.text.in_({"🌐 Язык", "🌐 Language"}))
    async def change_lang(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],[InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]])
        await message.answer("Выбери язык / Choose language:", reply_markup=kb)

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
        await call.message.answer(get_text(uid, "lang_changed"), reply_markup=get_main_kb(uid))
        await call.answer()

    # --- ПРОФИЛЬ ---
    @dp.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid); xp = get_xp(uid); lvl = xp // 100
        txt = get_text(uid, "profile", rank=get_rank_name(lvl), xp=xp, bar=make_xp_bar(xp), bal=fmt_num(bal))
        await send_clean_private(message, txt, reply_markup=profile_menu_inline())

    @dp.callback_query(F.data == "profile_back")
    async def prof_back(call: CallbackQuery):
        await call.message.delete(); await call.message.answer("🏠 Главное меню / Main menu:", reply_markup=get_main_kb(call.from_user.id)); await call.answer()

    # --- БОНУС И КЕЙС ---
    @dp.message(F.text.lower().in_({"бонус", "bonus"}))
    async def cmd_bonus_streak(message: Message, state: FSMContext):
        await state.clear(); uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS streak INT DEFAULT 0")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date DATE")
            conn.commit()
            c.execute("SELECT last_login_date, streak FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone(); today = _now().date()
            streak = row[1] if row and row[1] else 0; last_date = row[0] if row else None
            
            if last_date == today: return await send_clean_private(message, "⏳ Бонус уже взят сегодня / Bonus taken.")
            if last_date and (today - last_date).days == 1: streak += 1
            else: streak = 1
                
            rewards = {1: 1000, 2: 1500, 3: 2500, 4: 3500, 5: 5000, 6: 7500, 7: 10000}
            amount = rewards.get(streak, 10000)
            c.execute("UPDATE users SET balance = balance + %s, last_login_date = %s, streak = %s WHERE user_id = %s", (amount, today, streak, uid))
            conn.commit()
            msg_text = get_text(uid, "streak", day=streak, amount=fmt_num(amount))
        except Exception as e: return await message.reply(f"❌ Error: {e}")
        finally: c.close(); release_conn(conn)
        await send_clean_private(message, msg_text, reply_markup=get_main_kb(uid))

    @dp.message(F.text.lower().in_({"кейс", "case"}))
    async def cmd_case(message: Message, state: FSMContext):
        await state.clear(); uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_case_date DATE")
            conn.commit()
            c.execute("SELECT last_case_date FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone(); today = _now().date()
            if row and row[0] == today: return await send_clean_private(message, "⏳ Кейс уже открыт / Case already opened.")
            c.execute("UPDATE users SET last_case_date = %s WHERE user_id = %s", (today, uid))
            conn.commit()
        finally: c.close(); release_conn(conn)
        try: msg = await message.answer_animation(FSInputFile("case.gif"), caption="🎁 ОТКРЫВАЕМ / OPENING...")
        except: msg = await message.answer("🎁 ОТКРЫВАЕМ / OPENING...")
        await asyncio.sleep(2.5)
        try: await msg.delete()
        except: pass
        amount = random.choice([5000, 20000, 45000])
        new_bal = get_balance(uid) + amount
        set_balance(uid, amount)
        txt = get_text(uid, "case_opened", amount=fmt_num(amount), bal=fmt_num(new_bal))
        await send_clean_private(message, txt, reply_markup=get_main_kb(uid))

    # --- БАНК ---
    @dp.message(F.text.in_({"🏦 Банк", "🏦 Bank"}))
    async def bank_menu_handler(message: Message, state: FSMContext):
        await state.clear(); uid = message.from_user.id; bal = get_balance(uid)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone(); bank = row[0] if row and row[0] is not None else 0
        except: bank = 0
        finally: c.close(); release_conn(conn)
        txt = get_text(uid, "bank", bal=fmt_num(bal), bank=fmt_num(bank))
        try: await message.answer_photo(FSInputFile("bank.jpg"), caption=txt, reply_markup=get_bank_kb(uid))
        except: await message.answer(txt, reply_markup=get_bank_kb(uid))

    @dp.message(F.text.in_({"📥 Положить", "📥 Deposit", "📤 Снять", "📤 Withdraw"}))
    async def bank_action_start(message: Message, state: FSMContext):
        action = "deposit" if message.text in ["📥 Положить", "📥 Deposit"] else "withdraw"
        await state.update_data(action=action); await state.set_state(BotStates.waiting_bank_amount)
        prompt = "💰 Введи сумму / Enter amount:" 
        await send_clean_private(message, prompt)

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        uid = message.from_user.id
        if message.text in ["⬅️ Назад", "⬅️ Back"]: await state.clear(); return await bank_menu_handler(message, state)
        try: amount = int(message.text)
        except: return await message.reply("❌ Введи число / Enter number.")
        if amount <= 0: return await message.reply("❌ Сумма > 0")
        
        data = await state.get_data(); conn = get_conn(); c = conn.cursor()
        try:
            if data["action"] == "deposit":
                if get_balance(uid) < amount: return await message.reply("❌ Недостаточно / Not enough.")
                set_balance(uid, -amount)
                c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid))
                conn.commit(); await message.reply(f"✅ Внесено / Deposited: <b>{fmt_num(amount)}</b>.")
            else:
                c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
                bank = c.fetchone()[0] or 0
                if bank < amount: return await message.reply("❌ Мало в банке / Not enough in bank.")
                c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid))
                set_balance(uid, amount); conn.commit()
                await message.reply(f"✅ Снято / Withdrawn: <b>{fmt_num(amount)}</b>.")
        finally: c.close(); release_conn(conn)
        await state.clear(); await bank_menu_handler(message, state)

    # --- ДОНАТ ---
    @dp.message(F.text.in_({"💎 Донат", "💎 Donate"}))
    async def donate_menu(message: Message):
        uid = message.from_user.id
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 50 Stars = 50,000 T", callback_data="buy_50")],
            [InlineKeyboardButton(text="⭐ 100 Stars = 120,000 T", callback_data="buy_100")],
            [InlineKeyboardButton(text="⭐ 250 Stars = 350,000 T", callback_data="buy_250")],
            [InlineKeyboardButton(text="⭐ 500 Stars = 800,000 T", callback_data="buy_500")],
            [InlineKeyboardButton(text="💎 Своя сумма / Custom", callback_data="buy_custom")]
        ])
        await message.answer(get_text(uid, "donate"), reply_markup=kb)

    @dp.callback_query(F.data.startswith("buy_"))
    async def process_buy(call: CallbackQuery, state: FSMContext):
        data = call.data.replace("buy_", "")
        if data == "custom":
            await call.message.delete(); await send_clean_private(call.message, "⭐ Введи количество звёзд (1-10000):")
            await state.set_state(BotStates.waiting_donate_amount); await call.answer(); return
        stars = int(data); tokens = stars * 1000
        if stars == 100: tokens = 120000
        if stars == 250: tokens = 350000
        if stars == 500: tokens = 800000
        await call.message.answer_invoice(title=f"Покупка {fmt_num(tokens)} Tokens", description="Начисление токенов.", payload=f"donate_{stars}_{tokens}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Telegram Stars", amount=stars)])
        await call.answer()

    @dp.message(BotStates.waiting_donate_amount)
    async def custom_donate(message: Message, state: FSMContext):
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000: raise ValueError
        except: return await message.reply("❌ Введи число от 1 до 10000.")
        await state.clear(); tokens = stars * 1000
        await message.answer_invoice(title=f"Покупка {fmt_num(tokens)} Tokens", description="Начисление токенов.", payload=f"donate_{stars}_{tokens}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Telegram Stars", amount=stars)])

    @dp.pre_checkout_query()
    async def pre_checkout(pre_checkout_query: PreCheckoutQuery): await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_payment(message: Message):
        payload = message.successful_payment.invoice_payload; parts = payload.split("_")
        if len(parts) == 3:
            tokens = int(parts[2]); uid = message.from_user.id; set_balance(uid, tokens)
            await message.answer(f"🎉 <b>ОПЛАТА УСПЕШНА!</b>\nНачислено: <b>{fmt_num(tokens)}</b>\nБаланс: <b>{fmt_num(get_balance(uid))}</b>")

    # --- ПОДДЕРЖКА ---
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Help"}))
    async def support_menu(message: Message):
        uid = message.from_user.id
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🎮 Проблема с игрой" if USER_LANGS.get(uid)=="ru" else "🎮 Game problem"), KeyboardButton(text="💳 Вопрос по оплате" if USER_LANGS.get(uid)=="ru" else "💳 Payment issue")],
            [KeyboardButton(text="🚫 Бан или мут" if USER_LANGS.get(uid)=="ru" else "🚫 Ban or mute"), KeyboardButton(text="🐞 Нашёл баг" if USER_LANGS.get(uid)=="ru" else "🐞 Found a bug")],
            [KeyboardButton(text="✍️ Свой вопрос" if USER_LANGS.get(uid)=="ru" else "✍️ Own question")],
            [KeyboardButton(text=get_text(uid, "back"))]
        ], resize_keyboard=True)
        try: await message.answer_photo(FSInputFile("support.jpg"), caption=get_text(uid, "support"), reply_markup=kb)
        except: await message.answer(get_text(uid, "support"), reply_markup=kb)

    @dp.message(F.text.in_({"✍️ Свой вопрос", "✍️ Own question"}))
    async def supp_own_q(message: Message, state: FSMContext):
        await send_clean_private(message, get_text(message.from_user.id, "support_own"))
        await state.set_state(BotStates.waiting_support)

    @dp.message(BotStates.waiting_support)
    async def supp_send_admin(message: Message, state: FSMContext):
        uid = message.from_user.id; username = message.from_user.username or "no_username"; text = message.text
        await state.clear()
        try: await message.bot.send_message(ADMIN_ID, f"🆘 <b>ВОПРОС ОТ ИГРОКА</b>\n👤 От: @{username} (ID: {uid})\n💬 Текст: {text}\n\n<i>Ответь Reply на это сообщение!</i>")
        except: pass
        await message.answer(get_text(uid, "support_sent"), reply_markup=get_main_kb(uid))

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

    @dp.message(F.text.in_({"⬅️ Назад", "⬅️ Back"}))
    async def support_back(message: Message, state: FSMContext):
        await state.clear(); await message.answer("🏠 Меню / Menu:", reply_markup=get_main_kb(message.from_user.id))

    # --- АДМИНКА ---
    @dp.message(F.text == "👥 Игроки")
    async def admin_players_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("👥 <b>УПРАВЛЕНИЕ</b>", reply_markup=admin_players_kb())

    @dp.message(F.text == "💰 Выдать")
    async def admin_give_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💰 Введи <b>@username</b> (или ID) и <b>сумму</b>:")
        await state.set_state(BotStates.waiting_admin_give)

    @dp.message(BotStates.waiting_admin_give)
    async def process_admin_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ Формат: @user 1000")
        target = parts[0].replace("@", ""); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        try: amount = int(parts[1])
        except: return await message.reply("❌ Введи число.")
        set_balance(uid, amount); await message.reply(f"✅ Выдано {fmt_num(amount)} пользователю {target}."); await state.clear()

    @dp.message(F.text == "💸 Забрать")
    async def admin_take_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💸 Введи <b>@username</b> (или ID) и <b>сумму</b>:")
        await state.set_state(BotStates.waiting_admin_take)

    @dp.message(BotStates.waiting_admin_take)
    async def process_admin_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ Формат: @user 1000")
        target = parts[0].replace("@", ""); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        try: amount = int(parts[1])
        except: return await message.reply("❌ Введи число.")
        set_balance(uid, -amount); await message.reply(f"✅ Списано {fmt_num(amount)} у {target}."); await state.clear()

    @dp.message(F.text == "🚫 Бан")
    async def admin_ban_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🚫 Введи <b>@username</b> (или ID) для бана:")
        await state.set_state(BotStates.waiting_admin_ban)

    @dp.message(BotStates.waiting_admin_ban)
    async def process_admin_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "").strip(); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        set_banned(uid, True); await message.reply(f"✅ Игрок {target} забанен."); await state.clear()

    @dp.message(F.text == "✅ Разбан")
    async def admin_unban_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("✅ Введи <b>@username</b> (или ID) для разбана:")
        await state.set_state(BotStates.waiting_admin_unban)

    @dp.message(BotStates.waiting_admin_unban)
    async def process_admin_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "").strip(); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        set_banned(uid, False); await message.reply(f"✅ Игрок {target} разбанен."); await state.clear()

    @dp.message(F.text == "📊 Статистика")
    async def admin_stats_btn(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users"); tu, tb = c.fetchone()
            c.execute("SELECT COUNT(*) FROM game_log"); tg = c.fetchone()[0]
            await message.answer(f"📊 <b>СТАТИСТИКА</b>\n\n👥 Игроков: <b>{tu}</b>\n💎 Общий баланс: <b>{fmt_num(tb)}</b>\n🎮 Игр: <b>{tg}</b>")
        finally: c.close(); release_conn(conn)

    @dp.message(F.text == "📢 Рассылка")
    async def admin_broadcast_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.reply("📢 Отправь текст для рассылки (или 'отмена'):")
        await state.set_state(BotStates.waiting_broadcast_text)

    @dp.message(BotStates.waiting_broadcast_text)
    async def process_broadcast_text(message: Message, state: FSMContext):
        if message.text.lower() == "отмена": await state.clear(); return await message.reply("❌ Отменено.")
        await state.clear(); conn = get_conn(); c = conn.cursor()
        try: c.execute("SELECT user_id FROM users"); users = c.fetchall()
        finally: c.close(); release_conn(conn)
        sent = 0; await message.reply("⏳ Рассылка...")
        for (uid,) in users:
            try: await message.bot.send_message(uid, message.text); sent += 1; await asyncio.sleep(0.05)
            except: pass
        await message.reply(f"✅ Отправлено: {sent}")

    @dp.message(F.text == "⬅️ В главное меню")
    async def admin_back_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear(); await start(message, state)

    @dp.message(F.text == "📖 Хелп")
    async def admin_help_btn(message: Message):
        if message.from_user.id == ADMIN_ID: return await cmd_admin_help(message)
        if message.from_user.id in MODS: return await cmd_mod_help(message)

    # --- МОДЕРАЦИЯ ---
    @dp.message(F.text == "📊 Мои лимиты")
    async def mod_my_limit(message: Message):
        uid = message.from_user.id
        if uid not in MODS: return
        lim = refresh_week(uid, MOD_LIMITS); persist_mods()
        await message.reply(f"📊 <b>ТВОИ ЛИМИТЫ</b>\n\nВыдано: <b>{fmt_num(lim['given'])}</b>\nОсталось: <b>{fmt_num(MAX_MOD_GIVE - lim['given'])}</b>")

    @dp.message(F.text == "🧹 Очистить")
    @dp.message(Command("mod_clean", "очистить_чат"))
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

    @dp.message(F.text == "⚠️ Предупреждение")
    @dp.message(Command("warn"))
    async def mod_warn_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        if uid not in user_warns: user_warns[uid] = {"count": 0, "time": _now(), "last_msg": None, "spam_count": 0}
        user_warns[uid]["count"] += 1
        if user_warns[uid]["count"] >= 3:
            del user_warns[uid]; muted_users[uid] = _now() + timedelta(hours=1)
            await message.reply(f"🚫 Игрок получил 3/3 варна и мут на 1 час.")
        else: await message.reply(f"⚠️ Предупреждение {user_warns[uid]['count']}/3.")

    @dp.message(F.text == "📌 Закрепить")
    @dp.message(Command("mod_pin"))
    async def mod_pin_btn(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        try:
            await message.bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
            await message.reply("✅ Закреплено!")
        except: await message.reply("❌ Не могу закрепить.")

    @dp.message(F.text == "🔓 Разбан")
    @dp.message(Command("mod_unban"))
    async def mod_unban_btn(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        set_banned(uid, False); await message.reply(f"✅ Игрок разбанен.")

    @dp.message(F.text == "🚨 SOS Админу")
    @dp.message(Command("mod_alert"))
    async def mod_sos_btn(message: Message):
        if message.from_user.id not in MODS: return
        await message.reply("🚨 Сигнал отправлен Админу!")
        try: await message.bot.send_message(ADMIN_ID, f"🚨 <b>SOS ОТ МОДЕРА</b>\n@{message.from_user.username} вызывает тебя в чат <b>{message.chat.title}</b>")
        except: pass

    # --- ИГРЫ (ГРУППА) ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip() == "игры")
    async def group_games_rules(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
            [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        msg = await message.reply("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку:", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.callback_query(F.data.startswith("game_info_"))
    async def game_info_handler(call: CallbackQuery):
        game = call.data.replace("game_info_", "")
        if game == "close":
            try: await call.message.delete()
            except: pass
            return await call.answer("Меню закрыто.")
        if game == "back":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
                [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
                [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
                [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
                [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
                [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
            ])
            try: await call.message.edit_text("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку:", reply_markup=kb)
            except: pass
            return await call.answer()

        info = {
            "roulette": "🎡 <b>РУЛЕТКА</b>\n• <code>к 100</code> / <code>ч 100</code>\n• <code>го</code> — Запуск",
            "mines": "💣 <b>МИНЫ</b>\n• <code>мины 100</code>\nОткрывай клетки, собирай кэш!",
            "bj": "🃏 <b>БЛЭКДЖЕК</b>\n• <code>бж 100</code>\nНабери 21 очко!",
            "duel": "⚔️ <b>ДУЭЛИ</b>\nОтветь на сообщение игрока:\n• <code>дуэль 100</code>",
            "dice": "🎲 <b>КОСТИ</b>\n• <code>кости 100</code>\nВыигрыш 4, 5, 6 (x1.95)",
            "slots": "🎰 <b>СЛОТЫ</b>\n• <code>спин 100</code>\nШанс 50% (x1.8)",
            "basket": "🏀 <b>БАСКЕТ</b>\n• <code>баскет 100</code>\nПопал (x2)",
            "football": "⚽ <b>ФУТБОЛ</b>\n• <code>футбол 100</code>\nГол (x2)",
            "darts": "🎯 <b>ДАРТС</b>\n• <code>дартс 100</code>\nЯблочко (x5)",
            "bowling": "🎳 <b>БОУЛИНГ</b>\n• <code>боулинг 100</code>\nСтрайк (x3)",
            "coin": "🪙 <b>МОНЕТКА</b>\n• <code>монетка 100 орел</code>\nОрел/Решка x2"
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="game_info_back"), InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]])
        try: await call.message.edit_text(info.get(game, "Информация не найдена."), reply_markup=kb)
        except: pass
        await call.answer()

    # --- БАЛАНС, ТОП, ПЕРЕВОД В ГРУППЕ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        try:
            bal = get_balance(uid)
            if isinstance(bal, (tuple, list)): bal = bal[0]
        except: bal = 0
        msg = await message.reply(f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 {fmt_num(bal)} Tokens")
        asyncio.create_task(delete_message_later(msg, 60))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip() == "топ")
    async def group_top(message: Message):
        try:
            top = get_top(10)
            if not top: return await message.reply("🏆 Топ пуст.")
            txt = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n\n"
            for i, row in enumerate(top, 1):
                name = row[0] if isinstance(row, (list, tuple)) else row
                bal = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0
                txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
            msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))
        except Exception as e: await message.reply(f"❌ Ошибка БД: {e}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
    async def transfer_by_id(message: Message):
        parts = message.text.split(); uid = message.from_user.id
        try:
            target_id = int(parts[1]); amount = int(parts[2])
        except: return
        if amount < 10: return await message.reply("❌ Мин. 10.")
        if get_balance(uid) < amount: return await message.reply("❌ Мало.")
        set_balance(uid, -amount); set_balance(target_id, amount)
        await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 {fmt_num(amount)}")

    # --- РУЛЕТКА И ИГРЫ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт)\s+(\d+)$"))
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split(); word, num = None, None
        for p in parts:
            if p.isdigit(): num = p
            elif p in ["к", "ч", "з", "чет", "чёт", "нечет", "нечёт"]: word = p
        if not word or not num: return
        bet_type = {"к": "red", "ч": "black", "з": "green", "чет": "even", "чёт": "even", "нечет": "odd", "нечёт": "odd"}.get(word)
        try: bet = int(num)
        except: return
        if bet < 1: return await message.reply("❌ Мин. 1.")
        if get_balance(uid) < bet: return await message.reply("❌ Мало токенов.")
        set_balance(uid, -bet)
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!", reply_markup=bet_actions_inline())
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
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

    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji=emoji); await asyncio.sleep(2.5); res = sent.dice.value
        if win_cond(res):
            win = int(bet * win_mult); set_balance(uid, win)
            try: log_game(uid, message.from_user.username or "user", game_name, bet, win, str(res))
            except: pass
            txt = win_txt.format(result=res, win=fmt_num(win))
        else:
            try: log_game(uid, message.from_user.username or "user", game_name, bet, 0, str(res))
            except: pass
            txt = lose_txt.format(result=res, bet=fmt_num(bet))
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "dice ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "basket ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "football ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "darts ")))
    async def play_darts(message: Message): await play_dice_game(message, "дартс", "🎯", lambda r: r >= 3, 1.5, "🎯 {result}\n😢 -{bet}", "🎯 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "slots ")))
    async def play_slots(message: Message): await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8, "🎰 {result}\n😢 -{bet}", "🎰 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("монетка ", "coin ")))
    async def play_coin(message: Message):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) < 3: return await message.reply("❌ <code>монетка 100 орел</code>")
        try: bet = int(parts[1])
        except: return
        choice = parts[2]
        if choice not in ["орел", "решка", "ребро"]: return await message.reply("❌ орел/решка/ребро.")
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet); await asyncio.sleep(1)
        res = random.choices(["орел", "решка", "ребро"], weights=[49.5, 49.5, 1])[0]
        if res == "ребро" and choice == "ребро": win = int(bet * 10); set_balance(uid, win); txt = f"🪙 РЕБРО! ДЖЕКПОТ +{fmt_num(win)} (x10)"
        elif res == choice: win = int(bet * 2); set_balance(uid, win); txt = f"🪙 {res.upper()}! +{fmt_num(win)} (x2)"
        else: txt = f"🪙 {res.upper()}. -{fmt_num(bet)}"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("бж ", "bj ")))
    async def play_bj(message: Message):
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet)
        p1, p2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        d1, d2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        if d1 + d2 == 21 and p1 + p2 != 21: return await message.reply(f"🃏 <b>БЛЭКДЖЕК У ДИЛЕРА!</b>\nТвои: {p1+p2}, Дилер: 21\n😢 Ставка {fmt_num(bet)} сгорела.")
        if p1 + p2 == 21:
            win = int(bet * 2.5); set_balance(uid, win)
            return await message.reply(f"🃏 <b>БЛЭКДЖЕК!</b>\nТвои: 21\n🎉 Выигрыш: <b>+{fmt_num(win)}</b> (x2.5)")
        bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"), InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")]])
        await message.reply(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(bet)}\n\n👤 Твои карты: <b>{p1} + {p2} = {p1+p2}</b>\n🤖 Дилер: <b>{d1} + ?</b>", reply_markup=kb)

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
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(game['bet'])}\n\n👤 Твои карты: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n🤖 Дилер: <b>{game['dealer'][0]} + ?</b>", reply_markup=kb)
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

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet); mines = random.sample(list(range(25)), 3)
        await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0); await state.set_state(BotStates.mines_game)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
        msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n\nОткрывай клетки!", reply_markup=kb)
        async def auto_fail():
            await asyncio.sleep(300); data = await state.get_data()
            if data.get("bet"):
                await state.clear()
                try: await msg.edit_text(f"⏰ <b>ВРЕМЯ ВЫШЛО!</b>\n😢 Ставка <b>{fmt_num(data['bet'])}</b> сгорела.")
                except: pass
        asyncio.create_task(auto_fail())

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
        if get_balance(challenger.id) < bet or get_balance(opponent.id) < bet: return await message.reply("❌ Мало средств.")
        set_balance(challenger.id, -bet); chat_id = message.chat.id; duel_id = f"{chat_id}_{challenger.id}_{opponent.id}_{int(time.time())}"
        active_duels[duel_id] = {"challenger_id": challenger.id, "challenger_name": challenger.username or challenger.first_name, "opponent_id": opponent.id, "opponent_name": opponent.username or opponent.first_name, "bet": bet, "chat_id": chat_id, "created": time.time()}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}")],[InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}")]])
        await message.reply(f"⚔️ <b>ВЫЗОВ!</b>\n👤 @{challenger.username or challenger.first_name} VS @{opponent.username or opponent.first_name}\n💰 {fmt_num(bet)}\n\n@{opponent.username or opponent.first_name}, жми кнопку!", reply_markup=kb)
        async def auto_expire():
            await asyncio.sleep(120); d = active_duels.pop(duel_id, None)
            if d:
                set_balance(d["challenger_id"], d["bet"])
                try: await message.reply(f"⏰ <b>ДУЭЛЬ ПРОТУХЛА</b>\n💰 {fmt_num(d['bet'])} возвращены @{d['challenger_name']}.")
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

    async def cmd_mod_help(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        txt = "🛠 <b>МОДЕРАТОР</b>\n\n• <code>/mute 10</code> (Reply)\n• <code>/unmute</code> (Reply)\n• <code>/warn</code> (Reply)\n• <code>/kick</code> (Reply)\n• <code>/mod_clean</code>\n• <code>/mod_my_limit</code>"
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=mod_panel_kb())
        except: await message.answer(txt, reply_markup=mod_panel_kb())

    @dp.message(Command("mod_help", "помощь_модеру"))
    async def mod_help_cmd(message: Message): await cmd_mod_help(message)

    @dp.message(Command("mute"))
    async def mod_mute_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        try: mins = int(message.text.split()[1])
        except: return await message.reply("❌ /mute 10")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.restrict_chat_member(message.chat.id, uid, ChatPermissions(can_send_messages=False), until_date=_now() + timedelta(minutes=mins))
            await message.reply(f"🚫 Игрок замучен на {mins} мин.")
        except: await message.reply("❌ Не могу замутить.")

    @dp.message(Command("kick"))
    async def mod_kick_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.ban_chat_member(message.chat.id, uid); await message.bot.unban_chat_member(message.chat.id, uid)
            await message.reply("✅ Игрок кикнут.")
        except: await message.reply("❌ Не могу кикнуть.")

    async def cmd_admin_help(message: Message):
        if message.from_user.id != ADMIN_ID: return
        txt = "👑 <b>АДМИН</b>\n\n• <code>/userinfo @user</code>\n• <code>/msg @user text</code>\n• <code>/spy @user</code>\n• <code>/freeze @user</code>\n• <code>/promo_create CODE 5000 100</code>\n• <code>/maintenance on/off</code>\n• <code>/event 100000</code>\n• <code>/broadcast_text</code>\n• <code>/sys_info</code>"
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=admin_panel_kb())
        except: await message.answer(txt, reply_markup=admin_panel_kb())

    @dp.message(Command("admin_help", "помощь_админу"))
    async def admin_help_cmd(message: Message): await cmd_admin_help(message)

    @dp.message(Command("sys_info"))
    async def admin_sys_info(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.reply(f"💻 Python: {platform.python_version()}\nИгр в памяти: {len(active_bets)}\nВ муте: {len(muted_users)}")

    @dp.message(Command("userinfo"))
    async def admin_userinfo(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id; conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT username, balance, bank, credit_debt, xp, banned FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            if row:
                status = "🚫 Бан" if row[5] else "✅ Активен"
                await message.reply(f"🕵️ <b>ДОСЬЕ</b>\n👤 @{row[0]}\n💰 {fmt_num(row[1])}\n🏦 {fmt_num(row[2] or 0)}\n💳 {fmt_num(row[3] or 0)}\n⭐ XP: {row[4]}\nСтатус: {status}")
        finally: c.close(); release_conn(conn)

    @dp.message(Command("spy"))
    async def admin_spy(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id; conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT game, bet, win FROM game_log WHERE user_id = %s ORDER BY id DESC LIMIT 5", (uid,)); rows = c.fetchall()
        finally: c.close(); release_conn(conn)
        if not rows: return await message.reply("🕵️ Игрок не играл.")
        txt = "🕵️ <b>ПОСЛЕДНИЕ 5 ИГР</b>\n\n"
        for g, b, w in rows: txt += f"• {g} | {fmt_num(b)} -> {fmt_num(w)}\n"
        await message.reply(txt)

    @dp.message(Command("msg"))
    async def admin_msg(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3: return await message.reply("❌ /msg @user Текст")
        target = parts[1].replace("@", ""); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        try: await message.bot.send_message(uid, f"👑 <b>СООБЩЕНИЕ ОТ АДМИНА:</b>\n\n{parts[2]}"); await message.reply("✅ Отправлено.")
        except: await message.reply("❌ Ошибка.")

    @dp.message(Command("freeze"))
    async def admin_freeze(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        await message.reply("🧊 Аккаунт заморожен (запрет на игры).")

    @dp.message(Command("maintenance"))
    async def admin_maintenance(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.reply("🛠 Режим тех. работ включен.")

    @dp.message(Command("event"))
    async def admin_event(message: Message):
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

    @dp.message(Command("promo_create"))
    async def admin_promo_create(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split()
        if len(parts) != 4: return await message.reply("❌ /promo_create CODE 5000 100")
        code = parts[1].upper()
        try: amount = int(parts[2]); uses = int(parts[3])
        except: return await message.reply("❌ Неверные числа.")
        PROMO_CODES[code] = {"amount": amount, "uses": uses, "used_by": []}
        await message.reply(f"✅ Промокод {code} на {fmt_num(amount)} токенов (лимит: {uses}) создан!")

    @dp.message(Command("promo", "промо"))
    async def cmd_promo(message: Message, state: FSMContext):
        parts = message.text.split()
        if len(parts) != 2: return await message.reply("❌ Формат: <code>/promo КОД</code>")
        code = parts[1].upper(); uid = message.from_user.id
        if code not in PROMO_CODES: return await send_clean_private(message, "❌ <b>НЕВЕРНЫЙ ПРОМОКОД</b>", reply_markup=get_main_kb(uid))
        promo = PROMO_CODES[code]
        if uid in promo["used_by"]: return await send_clean_private(message, "⏳ Ты уже использовал этот промокод.", reply_markup=get_main_kb(uid))
        if len(promo["used_by"]) >= promo["uses"]: return await send_clean_private(message, "❌ <b>ЛИМИТ ИСЧЕРПАН</b>", reply_markup=get_main_kb(uid))
        promo["used_by"].append(uid); set_balance(uid, promo["amount"])
        await send_clean_private(message, f"🎉 <b>ПРОМОКОД АКТИВИРОВАН!</b>\nТы получил: <b>{fmt_num(promo['amount'])} Tokens!</b>", reply_markup=get_main_kb(uid))

    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if not message.from_user or message.from_user.id == ADMIN_ID or message.from_user.is_bot: return
        if message.text and (message.text.startswith("/") or message.text.lower().strip() in ["б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го", "что нового", "отмена", "ставки", "п"]): return
        if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: return
        uid = message.from_user.id; now = _now()
        if GLOBAL_MUTE and uid != ADMIN_ID:
            try: await message.delete()
            except: pass
            return
        if uid in muted_users:
            if now < muted_users[uid]:
                try: await message.delete()
                except: pass
                return 
            else: del muted_users[uid]
        is_bad = False
        if message.text:
            text_lower = message.text.lower()
            if any(word in text_lower for word in BAD_WORDS): is_bad = True
        is_caps = False
        if message.text and len(message.text) > 5:
            caps_count = sum(1 for c in message.text if c.isupper())
            if caps_count / len(message.text) > 0.7: is_caps = True
        is_spam = False
        if uid in user_warns and user_warns[uid].get("last_msg") == message.text:
            user_warns[uid]["spam_count"] = user_warns[uid].get("spam_count", 0) + 1
            if user_warns[uid]["spam_count"] >= 5: is_spam = True
        else:
            if uid in user_warns: user_warns[uid]["spam_count"] = 0
        if not (is_bad or is_caps or is_spam): return
        try: await message.delete()
        except: pass
        if uid not in user_warns: user_warns[uid] = {"count": 0, "time": now, "last_msg": None, "spam_count": 0}
        if (now - user_warns[uid]["time"]).total_seconds() > 3600: user_warns[uid]["count"] = 0
        user_warns[uid]["count"] += 1; user_warns[uid]["time"] = now; user_warns[uid]["last_msg"] = message.text
        count = user_warns[uid]["count"]; reason = "мат" if is_bad else ("капс" if is_caps else "спам")
        if count >= 3 or is_spam:
            mute_time = 10 if is_spam else 24
            muted_users[uid] = now + timedelta(minutes=mute_time); del user_warns[uid]
            try: await message.answer(f"🚫 <b>МУТ</b>\n@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}.")
            except: pass
        else:
            try:
                msg = await message.reply(f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!")
                asyncio.create_task(delete_message_later(msg, 30))
            except: pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e: logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)