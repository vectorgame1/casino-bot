# bot.py — FINAL v57 (Часть 1)
import asyncio, logging, os, random, re, time
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatMemberUpdated
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL, SUPPORT_USERNAME
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb, support_menu, bank_menu, profile_menu_inline, bet_actions_inline
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game, get_rate
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_bank_amount = State()
    waiting_credit_name = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_credit_purpose = State()
    waiting_custom_support = State()
    waiting_broadcast_target = State()
    waiting_broadcast_text = State()
    mines_game = State()
    bj_game = State()

active_bets = {} 
is_spinning = {} 
support_replies = {}
credit_requests = {}
bj_games = {}
active_duels = {}
last_bot_message = {} 
user_warns = {} 
muted_users = {} 

RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

BAD_WORDS = [
    "хуй", "хуя", "хую", "хуе", "хуи", "хуйн", "хуес", "хуеп", "хуит",
    "пизд", "пизж", "пизда", "пизде", "пизду", "пиздо", "пиздюл", "пиздоб",
    "бля", "блят", "блядь", "бляди", "блядю", "блядо", "бляду",
    "сука", "суки", "суке", "суку", "сукой", "сучк", "сучон",
    "ебал", "ебат", "ебуч", "ебан", "еби", "ебуч", "ебук", "ебани",
    "мудак", "мудил", "мудень", "мудозвон",
    "долбоеб", "долбаеб", "долбоёб", "долбаёб",
    "гандон", "гондон", "залуп", "залупа", "залупу", "залупой", "залупок",
    "пидор", "пидар", "пидорас", "пидорасина", "хуесос", "хуесосина",
    "отъеб", "въеб", "съеб", "заеб", "уеб", "наеб", "поъеб", "приеб", "проеб", "разъеб",
    "жопа", "жопу", "жопой", "жопе", "срать", "срал", "сру", "хер", "хрен", "член", "шлюх", "проститут", "дроч"
]

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
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    asyncio.create_task(start_web_server())
    init_pool(); init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # --- ПРИВЕТСТВИЕ БОТА ---
    @dp.my_chat_member()
    async def on_bot_added(event: ChatMemberUpdated):
        if event.new_chat_member.status == "member" and event.old_chat_member.status in ["left", "kicked"]:
            chat_id = event.chat.id
            txt = f"👋 <b>СПАСИБО ЗА ДОБАВЛЕНИЕ!</b>\n\nЯ — <b>{BOT_NAME.upper()}</b>!\n\n🎮 Напиши <b>игры</b>, чтобы начать!"
            try: await event.bot.send_message(chat_id, txt)
            except: pass

    # --- ПРИВЕТСТВИЕ НОВЫХ ---
    @dp.message(F.new_chat_members)
    async def welcome_new_member(message: Message):
        for user in message.new_chat_members:
            if user.is_bot: continue
            txt = f"🎉 <b>ДОБРО ПОЖАЛОВАТЬ!</b>\n👋 Привет, <b>{user.first_name}</b>!\n\n🎮 Напиши <code>игры</code>.\n🎁 Напиши <code>бонус</code> (5000)."
            try: await message.answer(txt)
            except: pass

    # --- СТАРТ ---
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        ensure_user(uid, message.from_user.username or message.from_user.first_name)
        if is_banned(uid): return await send_clean(message, "🚫 Заблокирован.")
        if message.chat.type != "private": return await message.reply(f"👋 ЛС: @{bot.username}")
        if uid == ADMIN_ID: return await cmd_admin(message, state)
        is_new = check_and_give_bonus(uid, START_BONUS)
        bonus = f"🎁 Бонус: +{fmt_num(START_BONUS)}\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n👋 {message.from_user.first_name}!\n{bonus}👇 Выбери действие:"
        await send_clean_private(message, txt, reply_markup=main_menu())

    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid)
        xp = get_xp(uid)
        lvl = xp // 100
        txt = f"👤 <b>ПРОФИЛЬ</b>\n🎖 Ранг: {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💰 Баланс: <b>{fmt_num(bal)}</b>"
        await send_clean_private(message, txt, reply_markup=profile_menu_inline())

    @dp.callback_query(F.data == "profile_bonus")
    async def prof_bonus(call: CallbackQuery):
        await call.message.delete()
        await cmd_bonus(call.message, None)
        await call.answer()

    @dp.callback_query(F.data == "profile_case")
    async def prof_case(call: CallbackQuery):
        await call.message.delete()
        await daily_case(call.message, None)
        await call.answer()

    @dp.callback_query(F.data == "profile_back")
    async def prof_back(call: CallbackQuery):
        await call.message.delete()
        await call.message.answer("🏠 Главное меню:", reply_markup=main_menu())
        await call.answer()

    # --- БОНУС И КЕЙС ---
    @dp.message(F.text.lower() == "бонус")
    async def cmd_bonus(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            c.close(); release_conn(conn)
            return await send_clean_private(message, "⏳ Бонус уже взят.")
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        await send_clean_private(message, "🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=main_menu())

    @dp.message(F.text.lower() == "кейс")
    async def daily_case(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🎁 Кейс в ЛС: @{bot.username}")
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try: c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_case_date DATE"); conn.commit()
        except: conn.rollback()
        c.execute("SELECT last_case_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            c.close(); release_conn(conn)
            return await send_clean_private(message, "⏳ Кейс уже открыт!")
        c.execute("UPDATE users SET last_case_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        if uid in last_bot_message:
            try: await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message[uid])
            except: pass
        try: msg = await message.answer_animation(FSInputFile("case.gif"), caption="🎁 ОТКРЫВАЕМ...")
        except: msg = await message.answer("🎁 ОТКРЫВАЕМ...")
        await asyncio.sleep(2.5)
        try: await msg.delete()
        except: pass
        amount = random.choice([5000, 10000, 25000])
        set_balance(uid, amount)
        res_msg = await message.answer(f"🎉 <b>КЕЙС ОТКРЫТ!</b>\nТы выиграл: <b>{fmt_num(amount)} Tokens!</b>", reply_markup=main_menu())
        last_bot_message[uid] = res_msg.message_id

    # --- МОДЕРАТОР ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if message.from_user.id == ADMIN_ID or message.from_user.is_bot: return
        if message.text and (message.text.startswith("/") or message.text.lower() in ["б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го", "что нового", "отмена", "ставки"]): return
        if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: return
        
        uid = message.from_user.id
        now = datetime.now(TZ_MINSK)
        
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
                
        if is_bad or is_caps or is_spam:
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
                await message.answer(f"🚫 <b>МУТ</b>\n@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}.")
            else:
                msg = await message.reply(f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!")
                asyncio.create_task(delete_message_later(msg, 30))

    # --- БАНК И КРЕДИТЫ ---
    @dp.message(F.text == "🏦 Банк")
    async def bank_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (message.from_user.id,)); row = c.fetchone(); bank = row[0] if row and row[0] is not None else 0
        except: bank = 0
        finally: c.close(); release_conn(conn)
        txt = f"🏦 <b>БАНК</b>\n💎 На руках: <b>{fmt_num(bal)}</b>\n🏦 В сейфе: <b>{fmt_num(bank)}</b>\n\n👇 Действие:"
        await send_clean_private(message, txt, reply_markup=bank_menu())

    @dp.message(F.text == "📥 Положить")
    async def bank_deposit_start(message: Message, state: FSMContext):
        await send_clean_private(message, "💰 Введи сумму для вклада:")
        await state.set_state(BotStates.waiting_bank_amount); await state.update_data(action="deposit")

    @dp.message(F.text == "📤 Снять")
    async def bank_withdraw_start(message: Message, state: FSMContext):
        await send_clean_private(message, "💸 Введи сумму для снятия:")
        await state.set_state(BotStates.waiting_bank_amount); await state.update_data(action="withdraw")

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        data = await state.get_data()
        if message.text == "⬅️ Назад": await state.clear(); return await bank_menu_handler(message, state)
        try: amount = int(message.text)
        except ValueError: return await send_clean_private(message, "❌ Введи число.")
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        if data.get("action") == "deposit":
            if get_balance(uid) < amount: c.close(); release_conn(conn); return await send_clean_private(message, "❌ Недостаточно.")
            set_balance(uid, -amount); c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid)); conn.commit(); c.close(); release_conn(conn)
            await send_clean_private(message, f"✅ Внесено <b>{fmt_num(amount)}</b>.")
        else:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,)); row = c.fetchone(); bank = row[0] if row else 0
            if bank < amount: c.close(); release_conn(conn); return await send_clean_private(message, "❌ Мало в банке.")
            c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid)); set_balance(uid, amount); conn.commit(); c.close(); release_conn(conn)
            await send_clean_private(message, f"✅ Снято <b>{fmt_num(amount)}</b>.")
        await state.clear(); await bank_menu_handler(message, state)

    @dp.message(F.text == "💳 Кредит")
    async def credit_start(message: Message, state: FSMContext):
        await state.clear()
        await send_clean_private(message, "💳 <b>ЗАЯВКА НА КРЕДИТ</b>\n1️⃣ Введи имя:")
        await state.set_state(BotStates.waiting_credit_name)

    @dp.message(BotStates.waiting_credit_name)
    async def credit_name(message: Message, state: FSMContext):
        await state.update_data(credit_name=message.text)
        await send_clean_private(message, "2️⃣ Сумма (10к-100к):")
        await state.set_state(BotStates.waiting_credit_amount)

    @dp.message(BotStates.waiting_credit_amount)
    async def credit_amount(message: Message, state: FSMContext):
        try: amt = int(message.text)
        except: return await send_clean_private(message, "❌ Число.")
        if amt < 10000 or amt > 100000: return await send_clean_private(message, "❌ 10-100к.")
        await state.update_data(credit_amount=amt)
        await send_clean_private(message, "3️⃣ Срок (1-7 дней):")
        await state.set_state(BotStates.waiting_credit_term)

    @dp.message(BotStates.waiting_credit_term)
    async def credit_term(message: Message, state: FSMContext):
        try: days = int(message.text)
        except: return await send_clean_private(message, "❌ Число.")
        if days < 1 or days > 7: return await send_clean_private(message, "❌ От 1 до 7 дней.")
        await state.update_data(credit_term=days)
        await send_clean_private(message, "4️⃣ Цель кредита:")
        await state.set_state(BotStates.waiting_credit_purpose)

    @dp.message(BotStates.waiting_credit_purpose)
    async def credit_purpose(message: Message, state: FSMContext):
        data = await state.get_data(); data["credit_purpose"] = message.text
        user = message.from_user; await state.clear()
        req_id = f"{user.id}_{int(time.time())}"
        credit_requests[req_id] = {"user_id": user.id, **data}
        admin_txt = f"💳 <b>КРЕДИТ</b>\n👤 @{user.username or 'user'}\n💰 {fmt_num(data['credit_amount'])}\n📅 {data['credit_term']} дней\n🎯 {data['credit_purpose']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"cr_acc_{req_id}")],[InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cr_dec_{req_id}")]])
        try: await message.bot.send_message(ADMIN_ID, admin_txt, reply_markup=kb); await send_clean_private(message, "✅ Заявка отправлена!", reply_markup=main_menu())
        except: await send_clean_private(message, "❌ Ошибка", reply_markup=main_menu())

    @dp.callback_query(F.data.startswith("cr_acc_"))
    async def credit_accept(call: CallbackQuery):
        req_id = call.data.replace("cr_acc_", "")
        if req_id not in credit_requests: return await call.answer("Устарело", show_alert=True)
        req = credit_requests[req_id]; uid = req["user_id"]
        set_balance(uid, req["credit_amount"])
        conn = get_conn(); c = conn.cursor()
        try: c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_debt BIGINT DEFAULT 0"); c.execute("UPDATE users SET credit_debt = %s WHERE user_id = %s", (req["credit_amount"] * 1.03, uid)); conn.commit()
        except: pass
        finally: c.close(); release_conn(conn)
        await call.message.edit_text("✅ Выдано!")
        try: await call.bot.send_message(uid, "🎉 Кредит одобрен!")
        except: pass
        del credit_requests[req_id]; await call.answer("Ок")

    @dp.callback_query(F.data.startswith("cr_dec_"))
    async def credit_decline(call: CallbackQuery):
        req_id = call.data.replace("cr_dec_", "")
        if req_id not in credit_requests: return await call.answer("Устарело", show_alert=True)
        del credit_requests[req_id]
        await call.message.edit_text("❌ Отклонено.")
        await call.answer()

    @dp.message(F.text == "💸 Погасить кредит")
    async def credit_repay(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT credit_debt FROM users WHERE user_id = %s", (uid,)); row = c.fetchone(); debt = row[0] if row and row[0] else 0
        except: debt = 0
        finally: c.close(); release_conn(conn)
        if debt <= 0: return await send_clean_private(message, "✅ У тебя нет долгов!", reply_markup=bank_menu())
        if get_balance(uid) < debt: return await send_clean_private(message, f"❌ Мало средств! Долг: {fmt_num(debt)}", reply_markup=bank_menu())
        set_balance(uid, -debt)
        conn = get_conn(); c = conn.cursor(); c.execute("UPDATE users SET credit_debt = 0 WHERE user_id = %s", (uid,)); conn.commit(); c.close(); release_conn(conn)
        await send_clean_private(message, f"✅ Кредит погашен! Списано: {fmt_num(debt)}", reply_markup=bank_menu())

    # --- ГРУППА: БАЛАНС И ПЕРЕВОД ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        bal = get_balance(uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Открыть кейс", url=f"https://t.me/{bot.username}?start=case")]])
        txt = f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 {fmt_num(bal)} Tokens\n\n👇 <i>Кейс в ЛС!</i>"
        msg = await message.reply(txt, reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 60))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
    async def transfer_by_id(message: Message):
        parts = message.text.split(); uid = message.from_user.id
        try: target_id = int(parts[1]); amount = int(parts[2])
        except: return
        if amount < 10: return await message.reply("❌ Мин. 10.")
        if get_balance(uid) < amount: return await message.reply("❌ Мало.")
        set_balance(uid, -amount); set_balance(target_id, amount)
        await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 {fmt_num(amount)}")

    # --- ИГРЫ (МЕНЮ) ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
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
        msg = await message.reply("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку, чтобы узнать правила:", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.callback_query(F.data.startswith("game_info_"))
    async def game_info_handler(call: CallbackQuery):
        game = call.data.replace("game_info_", "")
        if game == "close": await call.message.delete(); return await call.answer("Меню закрыто.")
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
            await call.message.edit_text("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку, чтобы узнать правила:", reply_markup=kb)
            return await call.answer()

        info = {
            "roulette": "🎡 <b>РУЛЕТКА</b>\n• <code>к 100</code> / <code>ч 100</code>\n• <code>100 1-18</code>\n• <code>го</code> — Запуск",
            "mines": "💣 <b>МИНЫ</b>\n• <code>мины 100</code>\nОткрывай клетки, собирай кэш!",
            "bj": "🃏 <b>БЛЭКДЖЕК</b>\n• <code>бж 100</code>\nНабери 21 очко, чтобы победить!",
            "duel": "⚔️ <b>ДУЭЛИ</b>\nОтветь на сообщение игрока:\n• <code>дуэль 100</code>",
            "dice": "🎲 <b>КОСТИ</b>\n• <code>кости 100</code>\nВыигрыш 4, 5, 6 (x1.95)",
            "slots": "🎰 <b>СЛОТЫ</b>\n• <code>спин 100</code>\nШанс 50% (x1.8)",
            "basket": "🏀 <b>БАСКЕТ</b>\n• <code>баскет 100</code>\nПопал (x2)",
            "football": "⚽ <b>ФУТБОЛ</b>\n• <code>футбол 100</code>\nГол (x2)",
            "darts": "🎯 <b>ДАРТС</b>\n• <code>дартс 100</code>\nЯблочко (x5)",
            "bowling": "🎳 <b>БОУЛИНГ</b>\n• <code>боулинг 100</code>\nСтрайк (x3)",
            "coin": "🪙 <b>МОНЕТКА</b>\n• <code>монетка 100 орел</code>\nОрел/Решка x2, Ребро x10"
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="game_info_back"), InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]])
        await call.message.edit_text(info.get(game, "Информация не найдена."), reply_markup=kb)
        await call.answer()

    # --- МИНЫ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2: return await message.reply("❌ <code>мины 100</code>")
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
        
        msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n⏳ Время: 5 минут\n\nОткрывай клетки!", reply_markup=kb)
        
        async def auto_fail():
            await asyncio.sleep(300)
            data = await state.get_data()
            if data.get("bet"):
                await state.clear()
                await msg.edit_text(f"⏰ <b>ВРЕМЯ ВЫШЛО!</b>\n😢 Ставка <b>{fmt_num(data['bet'])}</b> сгорела.")
        asyncio.create_task(auto_fail())

    @dp.callback_query(F.data.startswith("mine_"))
    async def mines_handler(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if not data: return await call.answer("Игра устарела.")
        bet, mines, opened, mult = data["bet"], data["mines"], data["opened"], data["mult"]
        
        if call.data == "mine_cashout":
            win = int(bet * mult); set_balance(call.from_user.id, win); await state.clear()
            await call.message.edit_text(f"💰 <b>ЗАБРАЛ!</b>\n💎 Выигрыш: <b>+{fmt_num(win)}</b>\n📈 x{mult:.2f}"); return await call.answer("Зачислено!")
            
        idx = int(call.data.split("_")[1])
        if idx in opened: return await call.answer("Уже открыто!")
        if idx in mines:
            await state.clear()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣" if r*5+c in mines else ("💎" if r*5+c in opened else "⬜"), callback_data="none") for c in range(5)] for r in range(5)])
            await call.message.edit_text(f"💥 <b>БУМ!</b>\n😢 Ставка <b>{fmt_num(bet)}</b> сгорела.", reply_markup=kb); return await call.answer("БУМ!")
            
        opened.append(idx)
        mult = round(1.0 + (len(opened) * 0.15), 2)
        await state.update_data(opened=opened, mult=mult)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
        await call.message.edit_text(f"💣 <b>МИНЫ</b>\n💰 {fmt_num(bet)}\n📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\nОткрывай дальше!", reply_markup=kb); await call.answer("Безопасно!")

    # --- БЛЭКДЖЕК ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("бж "))
    async def play_bj(message: Message):
        parts = message.text.lower().split()
        if len(parts) != 2: return await message.reply("❌ <code>бж 100</code>")
        try: bet = int(parts[1])
        except: return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        
        set_balance(uid, -bet)
        
        p1, p2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        d1, d2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        
        player_sum = p1 + p2
        dealer_sum = d1 + d2
        
        bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"), InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")]
        ])
        
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n"
            f"💰 Ставка: {fmt_num(bet)}\n\n"
            f"👤 Твои карты: <b>{p1} + {p2} = {player_sum}</b>\n"
            f"🤖 Дилер: <b>{d1} + ?</b>",
            reply_markup=kb
        )

    @dp.callback_query(F.data.startswith("bj_hit_"))
    async def bj_hit(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        if uid not in bj_games: return await call.answer("Игра не найдена", show_alert=True)
        
        game = bj_games[uid]
        new_card = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        game["player"].append(new_card)
        player_sum = sum(game["player"])
        
        if player_sum > 21:
            set_balance(uid, -game["bet"])
            del bj_games[uid]
            return await call.message.edit_text(f"🃏 <b>ПЕРЕБОР!</b>\nТы набрал {player_sum}. Ставка {fmt_num(game['bet'])} сгорела.")
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"), InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")]
        ])
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n"
            f"💰 Ставка: {fmt_num(game['bet'])}\n\n"
            f"👤 Твои карты: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n"
            f"🤖 Дилер: <b>{game['dealer'][0]} + ?</b>",
            reply_markup=kb
        )
        await call.answer(f"Выпала карта: {new_card}")

    @dp.callback_query(F.data.startswith("bj_stand_"))
    async def bj_stand(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
        if uid not in bj_games: return await call.answer("Игра не найдена", show_alert=True)
        
        game = bj_games[uid]
        player_sum = sum(game["player"])
        dealer_sum = sum(game["dealer"])
        
        while dealer_sum < 17:
            game["dealer"].append(random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]))
            dealer_sum = sum(game["dealer"])
            
        if dealer_sum > 21 or player_sum > dealer_sum:
            win = int(game["bet"] * 1.8)
            set_balance(uid, win)
            result = f"🎉 <b>ТЫ ВЫИГРАЛ!</b>\nВыигрыш: <b>+{fmt_num(win)}</b>"
        elif player_sum == dealer_sum:
            set_balance(uid, game["bet"])
            result = f"🤝 <b>НИЧЬЯ!</b>\nСтавка возвращена."
        else:
            result = f"😢 <b>ТЫ ПРОИГРАЛ!</b>\nСтавка сгорела."
            
        del bj_games[uid]
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Твои карты: {player_sum}\n🤖 Дилер: {dealer_sum}\n\n{result}")
        await call.answer("Игра окончена!")

    # --- ДУЭЛИ ---
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
        
        set_balance(challenger.id, -bet)
        chat_id = message.chat.id; duel_id = f"{chat_id}_{challenger.id}_{opponent.id}"
        active_duels[duel_id] = {"challenger_id": challenger.id, "challenger_name": challenger.username or challenger.first_name, "opponent_id": opponent.id, "opponent_name": opponent.username or opponent.first_name, "bet": bet}
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}")],[InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}")]])
        await message.reply(f"⚔️ <b>ВЫЗОВ!</b>\n👤 @{challenger.username or challenger.first_name} VS @{opponent.username or opponent.first_name}\n💰 {fmt_num(bet)}\n\n@{opponent.username or opponent.first_name}, жми кнопку!", reply_markup=kb)

    @dp.callback_query(F.data.startswith("duel_accept_"))
    async def duel_accept_handler(call: CallbackQuery):
        duel_id = call.data.replace("duel_accept_", "")
        if duel_id not in active_duels: return await call.answer("❌ Устарело.", show_alert=True)
        duel = active_duels[duel_id]
        if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
        if get_balance(duel["opponent_id"]) < duel["bet"]: return await call.answer("❌ Мало средств.", show_alert=True)
        set_balance(duel["opponent_id"], -duel["bet"]); del active_duels[duel_id]
        await call.message.edit_text(f"⚔️ <b>ДУЭЛЬ!</b>\n🔵 @{duel['challenger_name']}\n🔴 @{duel['opponent_name']}\n💰 {fmt_num(duel['bet'] * 2)}\n\n🎲 Бросаем...")
        await call.answer("Принято!")
        await asyncio.sleep(1.5)
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
        duel_id = call.data.replace("duel_decline_", "")
        if duel_id not in active_duels: return await call.answer("❌ Устарело.", show_alert=True)
        duel = active_duels[duel_id]
        if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
        set_balance(duel["challenger_id"], duel["bet"]); del active_duels[duel_id]
        await call.message.edit_text(f"❌ <b>ОТКЛОНЕНО</b>\n@{call.from_user.username or call.from_user.first_name} отказался.\n💰 {fmt_num(duel['bet'])} возвращены.")
        await call.answer("Отклонено.")

    # --- ОСТАЛЬНЫЕ ИГРЫ ---
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
        uid = message.from_user.id; username = message.from_user.username or message.from_user.first_name
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
            win = int(bet * win_mult); set_balance(uid, win); log_game(uid, username, game_name, bet, win, str(res))
            txt = win_txt.format(result=res, win=fmt_num(win))
        else:
            log_game(uid, username, game_name, bet, 0, str(res))
            txt = lose_txt.format(result=res, bet=fmt_num(bet))
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "баскетбол ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "фут ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "спин ")))
    async def play_slots(message: Message): await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8, "🎰 {result}\n😢 -{bet}", "🎰 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "дарт ")))
    async def play_darts(message: Message):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet); sent = await message.answer_dice(emoji="🎯"); await asyncio.sleep(2.5); res = sent.dice.value
        if res == 6: win = int(bet * 5); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "дартс", bet, win, str(res)); txt = f"🎯 ЯБЛОЧКО! +{fmt_num(win)} (x5)"
        elif res >= 3: win = int(bet * 1.5); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "дартс", bet, win, str(res)); txt = f"🎯 Попал! +{fmt_num(win)} (x1.5)"
        else: log_game(uid, message.from_user.username or "user", "дартс", bet, 0, str(res)); txt = f"🎯 Мимо. -{fmt_num(bet)}"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("боулинг ", "боул ")))
    async def play_bowling(message: Message):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet); sent = await message.answer_dice(emoji="🎳"); await asyncio.sleep(2.5); res = sent.dice.value
        if res == 6: win = int(bet * 3); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "боулинг", bet, win, str(res)); txt = f"🎳 СТРАЙК! +{fmt_num(win)} (x3)"
        elif res >= 4: win = int(bet * 1.5); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "боулинг", bet, win, str(res)); txt = f"🎳 Сбил! +{fmt_num(win)} (x1.5)"
        else: log_game(uid, message.from_user.username or "user", "боулинг", bet, 0, str(res)); txt = f"🎳 Мимо. -{fmt_num(bet)}"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("монетка ", "монета ")))
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
        if res == "ребро" and choice == "ребро": win = int(bet * 10); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "монетка", bet, win, res); txt = f"🪙 РЕБРО! ДЖЕКПОТ +{fmt_num(win)} (x10)"
        elif res == choice: win = int(bet * 2); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "монетка", bet, win, res); txt = f"🪙 {res.upper()}! +{fmt_num(win)} (x2)"
        else: log_game(uid, message.from_user.username or "user", "монетка", bet, 0, res); txt = f"🪙 {res.upper()}. -{fmt_num(bet)}"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    # --- РУЛЕТКА ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт)\s+(\d+)$"))
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        word = None; num = None
        for p in parts:
            if p.isdigit(): num = p
            elif p in ["к","ч","з","чет","чёт","нечет","нечёт"]: word = p
        if not word or not num: return
        bet_type = {"к":"red","ч":"black","з":"green","чет":"even","чёт":"even","нечет":"odd","нечёт":"odd"}.get(word)
        try: bet = int(num)
        except: return
        if bet < 1: return await message.reply("❌ Мин. 1.")
        bal = get_balance(uid)
        if bal < bet: return await message.reply(f"❌ Мало. Баланс: {fmt_num(bal)}")
        set_balance(uid, -bet)
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!", reply_markup=bet_actions_inline())
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.callback_query(F.data.in_({"bet_repeat", "bet_double"}))
    async def bet_actions_handler(call: CallbackQuery):
        uid = call.from_user.id; chat_id = call.message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            return await call.answer("Ставка устарела", show_alert=True)
        my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == uid]
        if not my_bets: return await call.answer("Ты не делал ставку!", show_alert=True)
        for b in my_bets:
            if b.get("action") == call.data:
                return await call.answer("❌ Ты уже использовал это в раунде!", show_alert=True)
        last_bet = my_bets[-1]; amount = last_bet["bet"]
        if call.data == "bet_double": amount *= 2
        if get_balance(uid) < amount: return await call.answer("❌ Недостаточно!", show_alert=True)
        set_balance(uid, -amount)
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": call.from_user.username or "user", "type": last_bet["type"], "bet": amount, "action": call.data})
        try: await call.message.delete()
        except: pass
        await call.answer(f"✅ Ставка на {fmt_num(amount)} принята!")
        await call.message.reply(f"🎰 <b>{'УДВОЕНИЕ' if call.data == 'bet_double' else 'ПОВТОР'}</b>\n@{call.from_user.username or 'user'} | {fmt_num(amount)}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
        if is_spinning.get(chat_id, False): return await message.reply("⏳ УЖЕ КРУТИТСЯ!")
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок.")
        if not any(b["user_id"] == uid for b in active_bets[chat_id]["bets"]): return await message.reply("❌ ТОЛЬКО ИГРОКИ СО СТАВКОЙ!")
        is_spinning[chat_id] = True
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        except: msg = await message.reply(f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
        await asyncio.sleep(3)
        res = random.randint(0, 36); color = get_color(res); win, lose = [], []
        for b in bets:
            w = 0
            if b["type"]=="red" and res in RED: w=int(b["bet"]*1.95)
            elif b["type"]=="black" and res in BLACK: w=int(b["bet"]*1.95)
            elif b["type"]=="green" and res==0: w=int(b["bet"]*35)
            elif b["type"]=="even" and res!=0 and res%2==0: w=int(b["bet"]*1.95)
            elif b["type"]=="odd" and res%2!=0: w=int(b["bet"]*1.95)
            if w > 0: set_balance(b["user_id"], w); win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else: lose.append(f"💔 @{b['username']}")
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n"
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        conn = get_conn(); c = conn.cursor()
        try: c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, f"{color}{res}"))
        except: pass
        finally: conn.commit(); c.close(); release_conn(conn)
        del active_bets[chat_id]; is_spinning[chat_id] = False
        asyncio.create_task(delete_message_later(msg, 120))

    # --- ЛОГ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "лог")
    async def group_log(message: Message):
        chat_id = message.chat.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS group_logs (chat_id BIGINT, detail TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("SELECT detail FROM group_logs WHERE chat_id = %s ORDER BY time DESC LIMIT 10", (chat_id,))
            rows = c.fetchall()
        except Exception: rows = []
        finally: c.close(); release_conn(conn)
        if not rows: return await message.reply("📜 <b>ИСТОРИЯ ПУСТА</b>\nВ этой группе еще не было игр.")
        txt = "📜 <b>ПОСЛЕДНИЕ 10 ЧИСЕЛ</b>\n\n"
        for i, (detail,) in enumerate(rows, 1):
            if detail.startswith("🔴"): txt += f"{i}. 🔴 <b>{detail[1:]}</b>\n"
            elif detail.startswith("⚫"): txt += f"{i}. ⚫ <b>{detail[1:]}</b>\n"
            elif detail.startswith("🟢"): txt += f"{i}. 🟢 <b>{detail[1:]}</b>\n"
            else: txt += f"{i}. {detail}\n"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 120))

    # ================= ПОДДЕРЖКА (КРАСИВАЯ) =================
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": 
            return await message.reply(f"🆘 Поддержка доступна в личных сообщениях: @{bot.username}")
        
        txt = (
            "🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n\n"
            "👋 Привет! Если у тебя возникли проблемы, выбери тему обращения ниже.\n\n"
            "👇 <i>Нажми на нужную кнопку:</i>"
        )
        try: 
            await message.answer_photo(photo=FSInputFile("support.jpg"), caption=txt, reply_markup=support_menu())
        except Exception: 
            await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>ПРОБЛЕМА С TOKENS</b>\n\n"
            "Спокойно, сейчас разберёмся. Проблема решаема.\n\n"
            "1️⃣ <b>Проверь оплату.</b> Зайди в Telegram -> Настройки -> Мои подарки. Если платеж прошел, но токенов нет — читаем дальше.\n"
            "2️⃣ <b>Подожди 5–10 минут.</b> Telegram Stars иногда зачисляются с задержкой.\n"
            "3️⃣ <b>Перезапусти бота.</b> Напиши /start. Если баланс не обновился — пиши в поддержку.\n\n"
            "✍️ <b>Что написать оператору:</b>\n"
            "• Скриншот чека об оплате\n"
            "• Сколько Stars отправил\n"
            "• Примерное время\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы всё вернём! 🙏"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🎮 <b>ОШИБКА В ИГРЕ</b>\n\n"
            "Опиши проблему, и мы починим это как можно скорее!\n\n"
            "Пожалуйста, укажи:\n"
            "1️⃣ <b>В какой игре</b> произошла ошибка.\n"
            "2️⃣ <b>Что ты делал</b> (какую команду вводил).\n"
            "3️⃣ <b>Что пошло не так</b> (списалось дважды, не выдало выигрыш).\n\n"
            "📸 <b>Пришли скриншот</b> — это ускорит починку в 2 раза!\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы всё проверим по логам. 🤝"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>ВОПРОС ПО ОПЛАТЕ</b>\n\n"
            "Все покупки в боте проходят через <b>Telegram Stars ⭐</b> (внутренняя валюта Telegram).\n\n"
            "<b>Как это работает:</b>\n"
            "• Ты выбираешь пакет -> бот присылает счет -> ты подтверждаешь оплату.\n"
            "• Токены зачисляются автоматически в течение 10 секунд.\n\n"
            "<b>Если что-то пошло не так:</b>\n"
            "• Возврат средств возможен только через поддержку Telegram (в настройках платежей).\n"
            "• Если токены не пришли — см. пункт <b>«Tokens не пришли»</b>.\n\n"
            f"📩 <b>Если остались вопросы:</b> {SUPPORT_USERNAME} ✍️"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🚫 <b>БАН ИЛИ МУТ</b>\n\n"
            "Если ты считаешь, что наказание было ошибочным, мы разберёмся.\n\n"
            "Пришли нам:\n"
            "1️⃣ Твой <b>@username</b> (и ID, если знаешь).\n"
            "2️⃣ <b>Причину блокировки</b> (если она была указана).\n"
            "3️⃣ <b>Примерное время</b>, когда это случилось.\n\n"
            "⚠️ <b>Важно:</b> Если ты попал в бан из-за непогашенного кредита, сначала верни долг.\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы проверим логи и снимем бан, если он был выдан по ошибке. 🤝"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🐞 <b>НАШЁЛ БАГ?</b>\n\n"
            "Спасибо, что помогаешь делать бота лучше! За реальный баг мы даем бонус Tokens.\n\n"
            "Опиши баг максимально подробно:\n"
            "1️⃣ <b>Что ты делал</b> (по шагам).\n"
            "2️⃣ <b>Что ожидал увидеть</b>.\n"
            "3️⃣ <b>Что случилось на самом деле</b>.\n\n"
            "📸 <b>Скриншот или текст ошибки</b> — обязательно!\n\n"
            f"📩 <b>Отправь это сюда:</b> {SUPPORT_USERNAME}\n"
            "За подтверждённый баг — бонус! 🎁"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            f"📜 <b>ПРАВИЛА {BOT_NAME.upper()}</b>\n\n"
            "1️⃣ Бот создан исключительно в развлекательных целях. <b>Реальных ставок нет.</b>\n"
            "2️⃣ Виртуальные Tokens не подлежат выводу или обмену на реальные деньги.\n"
            "3️⃣ Игра разрешена только пользователям <b>18+</b>.\n"
            "4️⃣ <b>Запрещены:</b> мультиаккаунтинг, использование багов, мошенничество.\n"
            "5️⃣ Донат — это добровольная поддержка проекта, а не инвестиция.\n\n"
            "⚠️ <b>Нарушение правил ведет к бану без предупреждения.</b>\n\n"
            "Играй ответственно! 🎲"
        )
        await send_clean_private(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "✍️ Свой вопрос")
    async def support_custom_q(message: Message, state: FSMContext):
        await state.clear()
        await send_clean_private(message, "✍️ <b>СВОЙ ВОПРОС</b>\n\nНапиши свой вопрос одним сообщением, и я передам его администрации.\n\n👇 <i>Жду твоего сообщения...</i>")
        await state.set_state("waiting_custom_support")

    @dp.message(lambda msg: msg.from_user.id != ADMIN_ID)
    async def catch_custom_q(message: Message, state: FSMContext):
        current_state = await state.get_state()
        is_reply = message.reply_to_message and message.reply_to_message.message_id in support_replies
        ignore_texts = ["💎 Tokens не пришли", "🎮 Что-то сломалось в игре", "💳 Вопрос по оплате", "🚫 Бан или мут", "🐞 Нашёл баг", "📜 Правила бота", "✍️ Свой вопрос", "⬅️ Назад"]
        if message.text in ignore_texts: return
        if current_state == "waiting_custom_support" or is_reply:
            await state.clear()
            user = message.from_user
            admin_text = f"📩 <b>ВХОДЯЩЕЕ СООБЩЕНИЕ</b>\n👤 <b>От:</b> @{user.username or user.first_name}\n🆔 <b>ID:</b> <code>{user.id}</code>\n\n💬 <b>Текст:</b>\n{message.text}\n\n<i>⚡ Ответь на это сообщение, чтобы ответить.</i>"
            try:
                sent_msg = await message.bot.send_message(ADMIN_ID, admin_text)
                support_replies[sent_msg.message_id] = user.id
                if current_state == "waiting_custom_support": 
                    await send_clean_private(message, "✅ <b>ОТПРАВЛЕНО!</b>\n\nЖди ответа от администрации.", reply_markup=main_menu())
                else: 
                    await message.reply("✅ Доставлено администрации.")
            except: 
                await send_clean_private(message, "❌ Ошибка отправки.", reply_markup=main_menu())

    @dp.message(lambda msg: msg.from_user.id == ADMIN_ID and msg.reply_to_message)
    async def admin_reply_to_support(message: Message):
        replied_msg_id = message.reply_to_message.message_id
        if replied_msg_id in support_replies:
            user_id = support_replies[replied_msg_id]
            user_text = f"📢 <b>ОТВЕТ ОТ ПОДДЕРЖКИ</b>\n\n💬 <b>Сообщение:</b>\n{message.text}\n\n<i>💡 Если у тебя есть еще вопросы, просто ответь на это сообщение!</i>"
            try:
                sent_msg = await message.bot.send_message(user_id, user_text)
                support_replies[sent_msg.message_id] = ADMIN_ID
                await message.reply("✅ <b>ОТВЕТ ОТПРАВЛЕН!</b>")
            except Exception as e:
                await message.reply(f"❌ Ошибка: {e}")

    # ================= АДМИНКА (КРАСИВАЯ) =================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
            "Добро пожаловать, Создатель! 🫡\n"
            "Здесь ты управляешь своим казино.\n\n"
            "👇 <b>Выбери нужный раздел:</b>"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🔍 Скан")],
            [KeyboardButton(text="💰 Выдать"), KeyboardButton(text="💸 Забрать")],
            [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
            [KeyboardButton(text="⬅️ Назад в админку")]
        ], resize_keyboard=True)
        txt = (
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n"
            "Здесь ты можешь найти любого игрока, выдать ему токены или заблокировать.\n\n"
            "• 🔍 <b>Скан</b> — посмотреть полное досье игрока (баланс, банк, последние игры).\n"
            "• 💰 <b>Выдать</b> — добавить токены на баланс.\n"
            "• 💸 <b>Забрать</b> — списать токены с баланса.\n"
            "• 🚫 <b>Бан</b> — заблокировать доступ к боту.\n"
            "• ✅ <b>Разбан</b> — разблокировать игрока.\n\n"
            "👇 <i>Выбери действие:</i>"
        )
        await send_clean_private(message, txt, reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await cmd_admin(message, state)

    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
        tu, tb = c.fetchone()
        c.close(); release_conn(conn)
        txt = (
            "💰 <b>ЭКОНОМИКА БОТА</b>\n\n"
            f"👥 Всего игроков: <b>{tu}</b>\n"
            f"💎 Общий баланс: <b>{fmt_num(tb)}</b> Tokens\n\n"
            f"💱 <b>Курс Stars:</b> 1 ⭐ = {STARS_RATE} Tokens\n\n"
            "<i>Здесь показана общая статистика по всем игрокам.</i>"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE banned = FALSE")
        a = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
        b = c.fetchone()[0]
        c.close(); release_conn(conn)
        txt = (
            "📊 <b>МОНИТОРИНГ АКТИВНОСТИ</b>\n\n"
            f"🟢 <b>Активных игроков:</b> {a}\n"
            f"🔴 <b>Забанено:</b> {b}\n\n"
            f"👑 <b>Твой профиль:</b> @{message.from_user.username}\n\n"
            "<i>Следи за активностью и бань нарушителей.</i>"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📢 Всем")],
            [KeyboardButton(text="🎯 По @username"), KeyboardButton(text="🆔 По ID")],
            [KeyboardButton(text="⬅️ Назад в админку")]
        ], resize_keyboard=True)
        txt = (
            "📢 <b>РАССЫЛКА СООБЩЕНИЙ</b>\n\n"
            "Здесь ты можешь отправить сообщение всем игрокам или кому-то конкретному.\n\n"
            "• 📢 <b>Всем</b> — отправить всем пользователям бота.\n"
            "• 🎯 <b>По @username</b> — отправить одному игроку (по юзернейму).\n"
            "• 🆔 <b>По ID</b> — отправить одному игроку (по ID).\n\n"
            "👇 <i>Выбери, кому отправить:</i>"
        )
        await send_clean_private(message, txt, reply_markup=kb)

    @dp.message(F.text == "📢 Всем")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean_private(message, "📢 <b>РАССЫЛКА ВСЕМ</b>\n\nНапиши текст сообщения, которое получат все игроки:")
        await state.set_state(BotStates.waiting_broadcast_text)
        await state.update_data(target="all")

    @dp.message(F.text == "🎯 По @username")
    async def broadcast_user_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean_private(message, "🎯 <b>РАССЫЛКА ПО USERNAME</b>\n\nВведи @username игрока (например, @vctorw):")
        await state.set_state(BotStates.waiting_broadcast_target)
        await state.update_data(mode="user")

    @dp.message(F.text == "🆔 По ID")
    async def broadcast_id_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean_private(message, "🆔 <b>РАССЫЛКА ПО ID</b>\n\nВведи числовой ID игрока:")
        await state.set_state(BotStates.waiting_broadcast_target)
        await state.update_data(mode="id")

    @dp.message(BotStates.waiting_broadcast_target)
    async def broadcast_target_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = message.text.strip()
        uid = get_user_id_by_username(target.replace("@", "")) if data["mode"] == "user" else (int(target) if target.isdigit() else None)
        
        if not uid:
            await state.clear()
            return await send_clean_private(message, "❌ <b>ИГРОК НЕ НАЙДЕН</b>\n\nПроверь правильность ввода.")
            
        await state.update_data(target=uid)
        await send_clean_private(message, "✍️ <b>ТЕКСТ СООБЩЕНИЯ</b>\n\nТеперь напиши текст, который получит этот игрок:")
        await state.set_state(BotStates.waiting_broadcast_text)

    @dp.message(BotStates.waiting_broadcast_text)
    async def broadcast_text_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = data.get("target")
        
        if target == "all":
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT user_id FROM users")
            users = c.fetchall()
            c.close(); release_conn(conn)
            
            sent = 0
            await send_clean_private(message, f"⏳ <b>РАССЫЛКА НАЧАТА</b>\n\nОтправляю сообщение {len(users)} игрокам...")
            for (uid,) in users:
                try:
                    await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n\n{message.text}")
                    sent += 1
                    await asyncio.sleep(0.05)
                except: pass
            await send_clean_private(message, f"✅ <b>ГОТОВО!</b>\n\nСообщение успешно отправлено <b>{sent}</b> игрокам.")
        else:
            try:
                await message.bot.send_message(target, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n\n{message.text}")
                await send_clean_private(message, "✅ <b>ОТПРАВЛЕНО!</b>\n\nСообщение доставлено игроку.")
            except Exception as e:
                await send_clean_private(message, f"❌ <b>ОШИБКА ОТПРАВКИ</b>\n\n{e}")
        await state.clear()

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)