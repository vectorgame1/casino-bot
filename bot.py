# bot.py — FINAL v60 (Часть 1)
import asyncio, logging, os, random, time, json
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatMemberUpdated, ChatPermissions
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL, SUPPORT_USERNAME
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user,
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game, get_rate
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name
from state_manager import load_mods, save_mods, refresh_week

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_USERNAME = ""

# ============================================================
# БЛОК 1. ПЕРЕВОДЫ (RU / EN)
# ============================================================
TEXTS = {
    "ru": {
        "welcome": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В {name}</b>\n\n👋 {first_name}!\n{bonus}👇 Выбери действие:",
        "menu": ["🎮 Игры", "💰 Баланс", "🏦 Банк", "👤 Профиль", "💎 Донат", "🆘 Помощь", "🌐 Язык"],
        "back": "⬅️ Назад",
        "lang_changed": "✅ Язык изменен на Русский",
        "bonus": "🎁 Бонус: +{amount}",
        "btn_games": "🎮 Игры",
        "btn_balance": "💰 Баланс",
        "btn_bank": "🏦 Банк",
        "btn_profile": "👤 Профиль",
        "btn_donate": "💎 Донат",
        "btn_help": "🆘 Помощь",
        "btn_lang": "🌐 Язык",
        "bank_menu": "🏦 <b>БАНК</b>\n💎 На руках: {bal}\n🏦 В сейфе: {bank}\n\n👇 Действие:",
        "btn_deposit": "📥 Положить",
        "btn_withdraw": "📤 Снять",
        "btn_credit": "💳 Кредит",
        "btn_repay": "💸 Погасить кредит",
        # Поддержка
        "support_title": "🆘 <b>ПОДДЕРЖКА</b>\n\nВыбери проблему:",
        "btn_bug": "🐞 Нашёл баг",
        "btn_pay": "💳 Вопрос по оплате",
        "btn_game": "🎮 Проблема с игрой",
        "btn_ban": "🚫 Бан или мут",
        "btn_own_q": "✍️ Свой вопрос",
        "support_own_q": "✍️ <b>СВОЙ ВОПРОС</b>\n\nНапиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.",
        "support_sent": "✅ Твой вопрос отправлен Админу. Ожидай ответа.",
        "support_admin_msg": "🆘 <b>ВОПРОС ОТ ИГРОКА</b>\n👤 От: @{user} (ID: {uid})\n💬 Текст: {text}\n\n<i>Ответь Reply на это сообщение!</i>",
        "support_answer": "👑 <b>ОТВЕТ ОТ АДМИНА:</b>\n\n{text}\n\n<i>Можешь ответить Reply.</i>",
        # Стрик
        "streak_taken": "⏳ Бонус уже взят.",
        "streak_received": "🎁 <b>СТРИК: ДЕНЬ {day}</b>\nТы получил: <b>+{amount} Tokens!</b>",
    },
    "en": {
        "welcome": "👑 <b>WELCOME TO {name}</b>\n\n👋 {first_name}!\n{bonus}👇 Choose an action:",
        "menu": ["🎮 Games", "💰 Balance", "🏦 Bank", "👤 Profile", "💎 Donate", "🆘 Help", "🌐 Language"],
        "back": "⬅️ Back",
        "lang_changed": "✅ Language changed to English",
        "bonus": "🎁 Bonus: +{amount}",
        "btn_games": "🎮 Games",
        "btn_balance": "💰 Balance",
        "btn_bank": "🏦 Bank",
        "btn_profile": "👤 Profile",
        "btn_donate": "💎 Donate",
        "btn_help": "🆘 Help",
        "btn_lang": "🌐 Language",
        "bank_menu": "🏦 <b>BANK</b>\n💎 On hands: {bal}\n🏦 In vault: {bank}\n\n👇 Action:",
        "btn_deposit": "📥 Deposit",
        "btn_withdraw": "📤 Withdraw",
        "btn_credit": "💳 Credit",
        "btn_repay": "💸 Repay credit",
        # Поддержка
        "support_title": "🆘 <b>SUPPORT</b>\n\nChoose a problem:",
        "btn_bug": "🐞 Found a bug",
        "btn_pay": "💳 Payment issue",
        "btn_game": "🎮 Game problem",
        "btn_ban": "🚫 Ban or mute",
        "btn_own_q": "✍️ Own question",
        "support_own_q": "✍️ <b>OWN QUESTION</b>\n\nWrite your question in one message. Admin will answer in DM.",
        "support_sent": "✅ Your question is sent to Admin. Wait for reply.",
        "support_admin_msg": "🆘 <b>QUESTION FROM PLAYER</b>\n👤 From: @{user} (ID: {uid})\n💬 Text: {text}\n\n<i>Reply to this message!</i>",
        "support_answer": "👑 <b>ANSWER FROM ADMIN:</b>\n\n{text}\n\n<i>You can Reply.</i>",
        # Стрик
        "streak_taken": "⏳ Bonus already taken.",
        "streak_received": "🎁 <b>STREAK: DAY {day}</b>\nYou received: <b>+{amount} Tokens!</b>",
    }
}

# Глобальный словарь для хранения языков игроков (в реальном проекте лучше БД, но для простоты пока так)
USER_LANGS = {}

def get_text(uid, key, **kwargs):
    lang = USER_LANGS.get(uid, "ru")
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, f"Error: {key}")
    return text.format(**kwargs) if kwargs else text

def get_main_kb(uid):
    lang = USER_LANGS.get(uid, "ru")
    t = TEXTS[lang]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t["btn_games"]), KeyboardButton(text=t["btn_balance"])],
        [KeyboardButton(text=t["btn_bank"]), KeyboardButton(text=t["btn_profile"])],
        [KeyboardButton(text=t["btn_donate"]), KeyboardButton(text=t["btn_help"])],
        [KeyboardButton(text=t["btn_lang"])]
    ], resize_keyboard=True)

# ============================================================
# БЛОК 2. СОСТОЯНИЯ
# ============================================================
class BotStates(StatesGroup):
    waiting_support = State()
    waiting_bank_amount = State()
    waiting_credit_name = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_credit_purpose = State()
    waiting_donate_amount = State()
    waiting_admin_give = State()
    waiting_admin_take = State()
    waiting_admin_ban = State()
    waiting_admin_unban = State()
    waiting_quick_amount = State()
    mines_game = State()

active_bets = {}
is_spinning = {}
credit_requests = {}
last_bot_message = {}
user_warns = {}
muted_users = {}
bj_games = {}
active_duels = {}
MODS, MOD_LIMITS = load_mods()
MAX_MOD_GIVE = 5_000_000
GLOBAL_MUTE = False
GLOBAL_MUTE_TASK = None
PROMO_CODES = {}
RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
BAD_WORDS = ["хуй", "хуя", "хую", "хуе", "хуи", "хуйн", "хуес", "хуеп", "хуит", "пизд", "пизж", "пизда", "пизде", "пизду", "пиздо", "пиздюл", "пиздоб", "бля", "блят", "блядь", "бляди", "блядю", "блядо", "бляду", "сука", "суки", "суке", "суку", "сукой", "сучк", "сучон", "ебал", "ебат", "ебуч", "ебан", "еби", "ебуч", "ебук", "ебани", "мудак", "мудил", "мудень", "мудозвон", "долбоеб", "долбаеб", "долбоёб", "долбаёб", "гандон", "гондон", "залуп", "залупа", "залупу", "залупой", "залупок", "пидор", "пидар", "пидорас", "пидорасина", "хуесос", "хуесосина", "отъеб", "въеб", "съеб", "заеб", "уеб", "наеб", "поъеб", "приеб", "проеб", "разъеб", "жопа", "жопу", "жопой", "жопе", "срать", "срал", "сру", "хер", "хрен", "член", "шлюх", "проститут", "дроч"]

def admin_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👥 Игроки"), KeyboardButton(text="👑 Админ-панель")],[KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📢 Рассылка")],[KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)

def mod_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],[KeyboardButton(text="⚠️ Предупреждение"), KeyboardButton(text="📌 Закрепить")],[KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS Админу")],[KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)

def get_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED else "⚫"

# ============================================================
# БЛОК 3. УТИЛИТЫ
# ============================================================
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
    if len(last_bot_message) > 1000:
        for k in list(last_bot_message.keys())[:200]: last_bot_message.pop(k, None)
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

# ============================================================
# БЛОК 4. MAIN (Часть 1: Старт, Язык, Поддержка, Стрик)
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

    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        ensure_user(uid, message.from_user.username or message.from_user.first_name)
        
        if message.chat.type != "private":
            return await message.reply(f"👋 ЛС: @{BOT_USERNAME}")
            
        if is_banned(uid):
            return await message.answer("🚫 Вы заблокированы.")

        # Логика стрика (Упрощенная, для БД нужно добавить колонку streak)
        # Пока просто выдаем бонус, если это новый день.
        # is_new = check_and_give_bonus(uid, START_BONUS)
        
        welcome_txt = get_text(uid, "welcome", name=BOT_NAME.upper(), first_name=message.from_user.first_name, bonus="")
        
        try:
            await message.answer_photo(FSInputFile("welcome.jpg"), caption=welcome_txt, reply_markup=get_main_kb(uid))
        except:
            await message.answer(welcome_txt, reply_markup=get_main_kb(uid))

    # --- Смена языка ---
    @dp.message(F.text.in_({"🌐 Язык", "🌐 Language"}))
    async def change_lang_start(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]
        ])
        await message.answer("Выбери язык / Choose language:", reply_markup=kb)

    @dp.callback_query(F.data.startswith("set_lang_"))
    async def set_lang_cb(call: CallbackQuery):
        lang = call.data.replace("set_lang_", "")
        uid = call.from_user.id
        USER_LANGS[uid] = lang
        # В идеале тут надо сохранить в БД
        
        await call.message.delete()
        await call.message.answer(get_text(uid, "lang_changed"), reply_markup=get_main_kb(uid))
        await call.answer()

    # --- Поддержка ---
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Help"}))
    async def support_menu(message: Message):
        uid = message.from_user.id
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text(uid, "btn_game"), callback_data="supp_game")],
            [InlineKeyboardButton(text=get_text(uid, "btn_pay"), callback_data="supp_pay")],
            [InlineKeyboardButton(text=get_text(uid, "btn_ban"), callback_data="supp_ban")],
            [InlineKeyboardButton(text=get_text(uid, "btn_bug"), callback_data="supp_bug")],
            [InlineKeyboardButton(text=get_text(uid, "btn_own_q"), callback_data="supp_own")]
        ])
        try:
            await message.answer_photo(FSInputFile("support.jpg"), caption=get_text(uid, "support_title"), reply_markup=kb)
        except:
            await message.answer(get_text(uid, "support_title"), reply_markup=kb)

    @dp.callback_query(F.data == "supp_own")
    async def supp_own_q(call: CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        await call.message.delete()
        await send_clean_private(call.message, get_text(uid, "support_own_q"))
        await state.set_state(BotStates.waiting_support)
        await call.answer()

    @dp.message(BotStates.waiting_support)
    async def supp_send_admin(message: Message, state: FSMContext):
        uid = message.from_user.id
        username = message.from_user.username or "no_username"
        text = message.text
        
        await state.clear()
        
        # Отправляем Админу
        try:
            await message.bot.send_message(
                ADMIN_ID, 
                get_text(ADMIN_ID, "support_admin_msg", user=username, uid=uid, text=text)
            )
        except:
            pass
            
        await message.answer(get_text(uid, "support_sent"), reply_markup=get_main_kb(uid))

    # --- Ответ Админа на тикет (через Reply) ---
    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply_ticket(message: Message):
        reply_text = message.reply_to_message.text
        if not reply_text or "ID: " not in reply_text:
            return
            
        try:
            # Вытаскиваем ID игрока из текста (например, "ID: 123456")
            uid_str = reply_text.split("ID: ")[1].split(")")[0].strip()
            target_uid = int(uid_str)
            
            await message.bot.send_message(
                target_uid, 
                get_text(target_uid, "support_answer", text=message.text)
            )
            await message.reply("✅ Ответ отправлен игроку.")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")

    # ========================================================
    # БЛОК 5. БАНК И КРЕДИТЫ
    # ========================================================
    @dp.message(F.text.in_({"🏦 Банк", "🏦 Bank"}))
    async def bank_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            bank = row[0] if row and row[0] is not None else 0
        except:
            bank = 0
        finally:
            c.close(); release_conn(conn)
            
        txt = get_text(uid, "bank_menu", bal=fmt_num(bal), bank=fmt_num(bank))
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=get_text(uid, "btn_deposit")), KeyboardButton(text=get_text(uid, "btn_withdraw"))],
            [KeyboardButton(text=get_text(uid, "btn_credit")), KeyboardButton(text=get_text(uid, "btn_repay"))],
            [KeyboardButton(text=get_text(uid, "back"))]
        ], resize_keyboard=True)
        
        try:
            await message.answer_photo(FSInputFile("bank.jpg"), caption=txt, reply_markup=kb)
        except:
            await message.answer(txt, reply_markup=kb)

    @dp.message(F.text.in_({"📥 Положить", "📥 Deposit", "📤 Снять", "📤 Withdraw"}))
    async def bank_action_start(message: Message, state: FSMContext):
        uid = message.from_user.id
        action = "deposit" if message.text in ["📥 Положить", "📥 Deposit"] else "withdraw"
        
        await state.update_data(action=action)
        await state.set_state(BotStates.waiting_bank_amount)
        
        prompt = "💰 Введи сумму для вклада:" if action == "deposit" else "💸 Введи сумму для снятия:"
        if USER_LANGS.get(uid) == "en":
            prompt = "💰 Enter amount to deposit:" if action == "deposit" else "💸 Enter amount to withdraw:"
            
        await send_clean_private(message, prompt)

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        uid = message.from_user.id
        if message.text in ["⬅️ Назад", "⬅️ Back"]:
            await state.clear()
            return await bank_menu_handler(message, state)
            
        try:
            amount = int(message.text)
        except:
            return await message.reply("❌ Введи число / Enter a number.")
            
        if amount <= 0:
            return await message.reply("❌ Сумма должна быть > 0")
            
        data = await state.get_data()
        conn = get_conn(); c = conn.cursor()
        try:
            if data["action"] == "deposit":
                if get_balance(uid) < amount:
                    return await message.reply("❌ Недостаточно средств.")
                set_balance(uid, -amount)
                c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid))
                conn.commit()
                await message.reply(f"✅ Внесено <b>{fmt_num(amount)}</b>.")
            else:
                c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
                bank = c.fetchone()[0] or 0
                if bank < amount:
                    return await message.reply("❌ Мало в банке.")
                c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid))
                set_balance(uid, amount)
                conn.commit()
                await message.reply(f"✅ Снято <b>{fmt_num(amount)}</b>.")
        finally:
            c.close(); release_conn(conn)
        await state.clear()
        await bank_menu_handler(message, state)

    @dp.message(F.text.in_({"⬅️ Назад", "⬅️ Back"}))
    async def global_back(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        if uid == ADMIN_ID:
            return await send_clean_private(message, "👑 Админ-панель:", reply_markup=admin_reply_kb())
        elif uid in MODS:
            return await send_clean_private(message, "🛡 Панель модератора:", reply_markup=mod_reply_kb())
        else:
            return await send_clean_private(message, "🏠 Главное меню:", reply_markup=get_main_kb(uid))

    # ========================================================
    # БЛОК 6. ДОНАТ (TELEGRAM STARS)
    # ========================================================
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
        await message.answer("💎 <b>ДОНАТ / DONATE</b>\n\nВыбери пакет или введи свою сумму:", reply_markup=kb)

    @dp.callback_query(F.data.startswith("buy_"))
    async def process_buy(call: CallbackQuery, state: FSMContext):
        data = call.data.replace("buy_", "")
        if data == "custom":
            await call.message.delete()
            await send_clean_private(call.message, "⭐ Введи количество звёзд (1-10000):")
            await state.set_state(BotStates.waiting_donate_amount)
            await call.answer()
            return
            
        stars = int(data)
        tokens = stars * 1000
        if stars == 100: tokens = 120000
        if stars == 250: tokens = 350000
        if stars == 500: tokens = 800000
        
        await call.message.answer_invoice(
            title=f"Покупка {fmt_num(tokens)} Tokens",
            description="Начисление токенов на ваш баланс.",
            payload=f"donate_{stars}_{tokens}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=stars)],
        )
        await call.answer()

    @dp.message(BotStates.waiting_donate_amount)
    async def custom_donate(message: Message, state: FSMContext):
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000: raise ValueError
        except:
            return await message.reply("❌ Введи число от 1 до 10000.")
            
        await state.clear()
        tokens = stars * 1000
        await message.answer_invoice(
            title=f"Покупка {fmt_num(tokens)} Tokens",
            description="Начисление токенов на ваш баланс.",
            payload=f"donate_{stars}_{tokens}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=stars)],
        )

    @dp.pre_checkout_query()
    async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        parts = payload.split("_")
        if len(parts) == 3:
            tokens = int(parts[2])
            uid = message.from_user.id
            set_balance(uid, tokens)
            await message.answer(f"🎉 <b>ОПЛАТА УСПЕШНА!</b>\nНачислено: <b>{fmt_num(tokens)}</b>\nБаланс: <b>{fmt_num(get_balance(uid))}</b>")

    # ========================================================
    # БЛОК 7. ИГРЫ И РУЛЕТКА
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"б", "баланс", "b", "balance"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        try:
            bal = get_balance(uid)
            if isinstance(bal, (tuple, list)): bal = bal[0]
        except:
            bal = 0
        msg = await message.reply(f"💳 Баланс @{message.from_user.username or 'user'}: <b>{fmt_num(bal)}</b> Tokens")
        asyncio.create_task(delete_message_later(msg, 60))

    # --- Рулетка ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт|r|b|g)\s+(\d+)$"))
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт|r|b|g)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id
        chat_id = message.chat.id
        parts = message.text.lower().split()
        word, num = None, None
        for p in parts:
            if p.isdigit(): num = p
            elif p in ["к", "r", "ч", "b", "з", "g", "чет", "нечет", "чёт", "нечёт"]: word = p
        
        if not word or not num: return
        bet_type = {"к": "red", "r": "red", "ч": "black", "b": "black", "з": "green", "g": "green", "чет": "even", "нечет": "odd", "чёт": "even", "нечёт": "odd"}.get(word)
        try: bet = int(num)
        except: return
        
        if bet < 1: return await message.reply("❌ Мин. 1.")
        if get_balance(uid) < bet: return await message.reply("❌ Мало токенов.")
        
        set_balance(uid, -bet)
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Повторить", callback_data="bet_repeat"),
            InlineKeyboardButton(text="⬆️ Удвоить", callback_data="bet_double")
        ]])
        msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if is_spinning.get(chat_id, False): return
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return
        
        is_spinning[chat_id] = True
        bets = active_bets[chat_id]["bets"]
        total = sum(b["bet"] for b in bets)
        
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        except: msg = await message.reply(f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        
        await asyncio.sleep(3)
        res = random.randint(0, 36)
        color = get_color(res)
        win, lose = [], []
        for b in bets:
            w = 0
            if b["type"] == "red" and res in RED: w = int(b["bet"] * 1.95)
            elif b["type"] == "black" and res in BLACK: w = int(b["bet"] * 1.95)
            elif b["type"] == "green" and res == 0: w = int(b["bet"] * 35)
            elif b["type"] == "even" and res != 0 and res % 2 == 0: w = int(b["bet"] * 1.95)
            elif b["type"] == "odd" and res % 2 != 0: w = int(b["bet"] * 1.95)
            if w > 0:
                set_balance(b["user_id"], w)
                win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else:
                lose.append(f"💔 @{b['username']}")
                
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n"
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        
        if chat_id in active_bets: active_bets[chat_id]["bets"] = []
        is_spinning[chat_id] = False
        asyncio.create_task(delete_message_later(msg, 120))

    # --- Остальные игры (Кости, Мины, Бж, и тд) ---
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
        uid = message.from_user.id
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji=emoji)
        await asyncio.sleep(2.5)
        res = sent.dice.value
        
        if win_cond(res):
            win = int(bet * win_mult)
            set_balance(uid, win)
            try: log_game(uid, message.from_user.username or "user", game_name, bet, win, str(res))
            except: pass
            txt = win_txt.format(result=res, win=fmt_num(win))
        else:
            try: log_game(uid, message.from_user.username or "user", game_name, bet, 0, str(res))
            except: pass
            txt = lose_txt.format(result=res, bet=fmt_num(bet))
            
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "dice ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "basket ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "football ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "darts ")))
    async def play_darts(message: Message): await play_dice_game(message, "дартс", "🎯", lambda r: r >= 3, 1.5, "🎯 {result}\n😢 -{bet}", "🎯 {result}\n🎉 +{win}")
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "slots ")))
    async def play_slots(message: Message): await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8, "🎰 {result}\n😢 -{bet}", "🎰 {result}\n🎉 +{win}")

    # ========================================================
    # БЛОК 8. ТОПЫ (3 команды)
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip() == "топ")
    async def top_balance(message: Message):
        try:
            top = get_top(10) # Предполагаем, что get_top возвращает список кортежей (username, balance)
            if not top: return await message.reply("🏆 Топ пуст.")
            txt = "🏆 <b>ТОП-10 БОГАЧЕЙ</b>\n\n"
            for i, row in enumerate(top, 1):
                name = row[0] if isinstance(row, (list, tuple)) else row
                bal = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0
                txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
            msg = await message.reply(txt)
            asyncio.create_task(delete_message_later(msg, 120))
        except Exception as e:
            await message.reply(f"❌ Ошибка БД: {e}")

    # ========================================================
    # БЛОК 9. ОСТАВШИЕСЯ ИГРЫ (БЖ, МИНЫ, ДУЭЛИ)
    # ========================================================
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
        
        if d1 + d2 == 21 and p1 + p2 != 21:
            return await message.reply(f"🃏 <b>БЛЭКДЖЕК У ДИЛЕРА!</b>\nТвои: {p1+p2}, Дилер: 21\n😢 Ставка {fmt_num(bet)} сгорела.")
        if p1 + p2 == 21:
            win = int(bet * 2.5); set_balance(uid, win)
            return await message.reply(f"🃏 <b>БЛЭКДЖЕК!</b>\nТвои: 21\n🎉 Выигрыш: <b>+{fmt_num(win)}</b> (x2.5)")
            
        bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
            InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
        ]])
        await message.reply(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(bet)}\n\n👤 Твои карты: <b>{p1} + {p2} = {p1+p2}</b>\n🤖 Дилер: <b>{d1} + ?</b>", reply_markup=kb)

    @dp.callback_query(F.data.startswith("bj_hit_"))
    async def bj_hit(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game: return await call.answer("Игра не найдена", show_alert=True)
        
        new_card = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        game["player"].append(new_card)
        player_sum = sum(game["player"])
        
        if player_sum > 21:
            await call.message.edit_text(f"🃏 <b>ПЕРЕБОР!</b>\nТы набрал {player_sum}. Ставка {fmt_num(game['bet'])} сгорела.")
            return await call.answer("Перебор!")
            
        bj_games[uid] = game
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
            InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
        ]])
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(game['bet'])}\n\n👤 Твои карты: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n🤖 Дилер: <b>{game['dealer'][0]} + ?</b>", reply_markup=kb)
        await call.answer(f"Выпала карта: {new_card}")

    @dp.callback_query(F.data.startswith("bj_stand_"))
    async def bj_stand(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game: return await call.answer("Игра не найдена", show_alert=True)
        
        player_sum = sum(game["player"])
        dealer_sum = sum(game["dealer"])
        while dealer_sum < 17:
            game["dealer"].append(random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]))
            dealer_sum = sum(game["dealer"])
            
        if dealer_sum > 21 or player_sum > dealer_sum:
            win = int(game["bet"] * 1.8); set_balance(uid, win)
            result = f"🎉 <b>ТЫ ВЫИГРАЛ!</b>\nВыигрыш: <b>+{fmt_num(win)}</b>"
        elif player_sum == dealer_sum:
            set_balance(uid, game["bet"])
            result = f"🤝 <b>НИЧЬЯ!</b>\nСтавка возвращена."
        else:
            result = f"😢 <b>ТЫ ПРОИГРАЛ!</b>\nСтавка сгорела."
            
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Твои карты: {player_sum}\n🤖 Дилер: {dealer_sum}\n\n{result}")
        await call.answer("Игра окончена!")

    # --- МИНЫ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        
        set_balance(uid, -bet)
        mines = random.sample(list(range(25)), 3)
        await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0)
        await state.set_state(BotStates.mines_game)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
        
        msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n\nОткрывай клетки!", reply_markup=kb)
        
        async def auto_fail():
            await asyncio.sleep(300)
            data = await state.get_data()
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
            win = int(bet * mult); set_balance(call.from_user.id, win)
            await state.clear()
            await call.message.edit_text(f"💰 <b>ЗАБРАЛ!</b>\n💎 Выигрыш: <b>+{fmt_num(win)}</b>\n📈 x{mult:.2f}")
            return await call.answer("Зачислено!")
            
        idx = int(call.data.split("_")[1])
        if idx in opened: return await call.answer("Уже открыто!")
        
        if idx in mines:
            await state.clear()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣" if r*5+c in mines else ("💎" if r*5+c in opened else "⬜"), callback_data="none") for c in range(5)] for r in range(5)])
            await call.message.edit_text(f"💥 <b>БУМ!</b>\n😢 Ставка <b>{fmt_num(bet)}</b> сгорела.", reply_markup=kb)
            return await call.answer("БУМ!")
            
        opened.append(idx)
        mult = round(1.0 + (len(opened) * 0.15), 2)
        await state.update_data(opened=opened, mult=mult)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
        await call.message.edit_text(f"💣 <b>МИНЫ</b>\n💰 {fmt_num(bet)}\n📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\nОткрывай дальше!", reply_markup=kb)
        await call.answer("Безопасно!")

    # ========================================================
    # БЛОК 10. МОДЕРАЦИЯ И АДМИНКА (КОМАНДЫ)
    # ========================================================
    @dp.message(F.text.in_({"📖 Хелп", "📖 Help"}))
    async def help_btn(message: Message, state: FSMContext):
        uid = message.from_user.id
        if uid == ADMIN_ID:
            await cmd_admin_help(message)
        elif uid in MODS:
            await cmd_mod_help(message)
        else:
            # Если обычный юзер нажал хелп в ЛС (хотя у него такой кнопки нет)
            await cmd_help(message)

    @dp.message(Command("mod_help", "помощь_модеру"))
    async def cmd_mod_help(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        txt = (
            "🛠 <b>МОДЕРАТОР — RU / EN</b>\n\n"
            "• <code>/mute 10</code> (Reply) — Мут на 10 мин / Mute 10 min\n"
            "• <code>/unmute</code> (Reply) — Снять мут / Unmute\n"
            "• <code>/warn</code> (Reply) — Предупреждение / Warn\n"
            "• <code>/clean @user</code> — Очистить сообщения / Clean msgs\n"
            "• <code>/kick</code> (Reply) — Кик / Kick\n"
            "• <code>/stats @user</code> — Стата / Stats\n"
            "• <code>/rules</code> — Правила / Rules\n"
            "• <code>/mod_clean</code> — Очистить 100 сообщений\n"
            "• <code>/mod_my_limit</code> — Мои лимиты / Limits\n\n"
            "👇 <i>Используй Reply-кнопки для быстрого доступа.</i>"
        )
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=mod_reply_kb())
        except: await message.answer(txt, reply_markup=mod_reply_kb())

    @dp.message(Command("admin_help", "помощь_админу"))
    async def cmd_admin_help(message: Message):
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "👑 <b>АДМИН — RU / EN</b>\n\n"
            "• <code>/userinfo @user</code> — Досье / Info\n"
            "• <code>/msg @user text</code> — ЛС от админа / DM\n"
            "• <code>/spy @user</code> — Активность 24ч / Spy\n"
            "• <code>/freeze @user</code> — Заморозка / Freeze\n"
            "• <code>/promo_create CODE 5000 100</code> — Промокод\n"
            "• <code>/maintenance on/off</code> — Тех.работы\n"
            "• <code>/event 100000</code> — Ивент-дроп\n"
            "• <code>/broadcast_text</code> — Рассылка текстом\n"
            "• <code>/sys_info</code> — Инфо о боте\n\n"
            "👇 <i>Ответ на тикет игрока делается через Reply!</i>"
        )
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=admin_reply_kb())
        except: await message.answer(txt, reply_markup=admin_reply_kb())

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

    @dp.message(Command("warn"))
    async def mod_warn_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        if uid not in user_warns: user_warns[uid] = {"count": 0, "time": _now(), "last_msg": None, "spam_count": 0}
        user_warns[uid]["count"] += 1
        if user_warns[uid]["count"] >= 3:
            del user_warns[uid]
            muted_users[uid] = _now() + timedelta(hours=1)
            await message.reply(f"🚫 Игрок получил 3/3 варна и мут на 1 час.")
        else:
            await message.reply(f"⚠️ Предупреждение {user_warns[uid]['count']}/3.")

    @dp.message(Command("kick"))
    async def mod_kick_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.ban_chat_member(message.chat.id, uid)
            await message.bot.unban_chat_member(message.chat.id, uid)
            await message.reply("✅ Игрок кикнут.")
        except: await message.reply("❌ Не могу кикнуть.")

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
            info = await message.answer(f"🧹 Удалено: <b>{deleted}</b>")
            await asyncio.sleep(3); await info.delete()
        except: pass

    # ========================================================
    # БЛОК 11. АВТО-МОДЕРАТОР
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if not message.from_user or message.from_user.id == ADMIN_ID or message.from_user.is_bot: return
        if message.text and (message.text.startswith("/") or message.text.lower().strip() in ["б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го", "что нового", "отмена", "ставки", "п"]): return
        if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: return
        
        uid = message.from_user.id
        now = _now()
        
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
            
        user_warns[uid]["count"] += 1
        user_warns[uid]["time"] = now
        user_warns[uid]["last_msg"] = message.text
        count = user_warns[uid]["count"]
        reason = "мат" if is_bad else ("капс" if is_caps else "спам")
            
        if count >= 3 or is_spam:
            mute_time = 10 if is_spam else 24
            muted_users[uid] = now + timedelta(minutes=mute_time)
            del user_warns[uid]
            try: await message.answer(f"🚫 <b>МУТ</b>\n@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}.")
            except: pass
        else:
            try:
                msg = await message.reply(f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!")
                asyncio.create_task(delete_message_later(msg, 30))
            except: pass

    # ========================================================
    # ЗАПУСК БОТА
    # ========================================================
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
