# bot.py — FINAL v53 (Чистый, красивый, рабочий)
import asyncio, logging, os, random, re, time
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
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

active_bets = {} 
is_spinning = {} 
support_replies = {}
credit_requests = {}

RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED else "⚫"

async def delete_message_later(message: Message, delay: int = 150):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

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

    # ================= СТАРТ И ПРОФИЛЬ =================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or message.from_user.first_name)
        
        if is_banned(user_id): return await send_clean(message, "🚫 Вы заблокированы.")
        if message.chat.type != "private": return await message.reply(f"👋 ЛС: @{bot.username}")
        if user_id == ADMIN_ID: return await send_clean(message, "👑 АДМИНКА", reply_markup=admin_panel_kb())
        
        is_new = check_and_give_bonus(user_id, START_BONUS)
        bonus = f"🎁 Бонус: +{fmt_num(START_BONUS)}\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n👋 {message.from_user.first_name}!\n{bonus}👇 Выбери действие:"
        await send_clean(message, txt, reply_markup=main_menu())

    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid)
        xp = get_xp(uid)
        lvl = xp // 100
        txt = f"👤 <b>ПРОФИЛЬ</b>\n🎖 Ранг: {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💰 Баланс: <b>{fmt_num(bal)}</b>"
        await send_clean(message, txt, reply_markup=profile_menu_inline())

    @dp.callback_query(F.data == "profile_bonus")
    async def prof_bonus(call: CallbackQuery):
        await call.message.delete()
        await call.message.answer("🎁 Для бонуса напиши: <code>бонус</code>")
        await call.answer()

    @dp.callback_query(F.data == "profile_case")
    async def prof_case(call: CallbackQuery):
        await call.message.delete()
        await call.message.answer("📦 Для кейса напиши: <code>кейс</code>")
        await call.answer()

    @dp.callback_query(F.data == "profile_back")
    async def prof_back(call: CallbackQuery):
        await call.message.delete()
        await call.message.answer("🏠 Главное меню:", reply_markup=main_menu())
        await call.answer()

    # ================= БОНУС И КЕЙС =================
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
            return await send_clean(message, "⏳ Ты уже брал бонус сегодня.")
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        await send_clean(message, "🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=main_menu())

    @dp.message(F.text.lower() == "кейс")
    async def daily_case(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private":
            return await message.reply(f"🎁 <b>КЕЙС</b>\n👇 Напиши мне сюда: @{bot.username}")
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try: c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_case_date DATE"); conn.commit()
        except: conn.rollback()
        c.execute("SELECT last_case_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            c.close(); release_conn(conn)
            return await send_clean(message, "⏳ <b>КЕЙС УЖЕ ОТКРЫТ</b>\nПриходи завтра!")
        c.execute("UPDATE users SET last_case_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        try: await message.answer_animation(FSInputFile("case.gif"), caption="🎁 <b>ОТКРЫВАЕМ...</b>")
        except: await send_clean(message, "🎁 <b>ОТКРЫВАЕМ...</b>")
        await asyncio.sleep(2.5)
        amount = random.choice([5000, 10000, 25000])
        set_balance(uid, amount)
        await send_clean(message, f"🎉 <b>КЕЙС ОТКРЫТ!</b>\nТы выиграл: <b>{fmt_num(amount)} Tokens!</b>", reply_markup=main_menu())

    # ================= БАНК И КРЕДИТЫ =================
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
        try: await message.answer_photo(photo=FSInputFile("bank.jpg"), caption=txt, reply_markup=bank_menu())
        except: await send_clean(message, txt, reply_markup=bank_menu())

    @dp.message(F.text == "📥 Положить")
    async def bank_deposit_start(message: Message, state: FSMContext):
        await send_clean(message, "💰 Введи сумму для вклада:")
        await state.set_state(BotStates.waiting_bank_amount); await state.update_data(action="deposit")

    @dp.message(F.text == "📤 Снять")
    async def bank_withdraw_start(message: Message, state: FSMContext):
        await send_clean(message, "💸 Введи сумму для снятия:")
        await state.set_state(BotStates.waiting_bank_amount); await state.update_data(action="withdraw")

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        data = await state.get_data()
        if message.text == "⬅️ Назад": await state.clear(); return await bank_menu_handler(message, state)
        try: amount = int(message.text)
        except ValueError: return await send_clean(message, "❌ Введи число.")
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        if data.get("action") == "deposit":
            if get_balance(uid) < amount: c.close(); release_conn(conn); return await send_clean(message, "❌ Недостаточно.")
            set_balance(uid, -amount); c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid)); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Внесено <b>{fmt_num(amount)}</b>.")
        else:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,)); row = c.fetchone(); bank = row[0] if row else 0
            if bank < amount: c.close(); release_conn(conn); return await send_clean(message, "❌ Мало в банке.")
            c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid)); set_balance(uid, amount); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Снято <b>{fmt_num(amount)}</b>.")
        await state.clear(); await bank_menu_handler(message, state)

    # КРЕДИТ (Красивый текст)
    @dp.message(F.text == "💳 Кредит")
    async def credit_start(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>ЗАЯВКА НА КРЕДИТ</b>\n\n"
            "Условия: от 10 000 до 100 000 под 3% в день.\n"
            "Максимальный срок: 7 дней.\n\n"
            "1️⃣ Введи свое <b>Имя и Фамилию</b>:"
        )
        await send_clean(message, txt)
        await state.set_state(BotStates.waiting_credit_name)

    @dp.message(BotStates.waiting_credit_name)
    async def credit_name(message: Message, state: FSMContext):
        await state.update_data(credit_name=message.text)
        await send_clean(message, "2️⃣ Введи <b>желаемую сумму</b> (от 10 000 до 100 000):")
        await state.set_state(BotStates.waiting_credit_amount)

    @dp.message(BotStates.waiting_credit_amount)
    async def credit_amount(message: Message, state: FSMContext):
        try: amt = int(message.text)
        except: return await send_clean(message, "❌ Введи число.")
        if amt < 10000 or amt > 100000: return await send_clean(message, "❌ От 10 000 до 100 000.")
        await state.update_data(credit_amount=amt)
        await send_clean(message, "3️⃣ На какой <b>срок</b> (в днях, от 1 до 7)?")
        await state.set_state(BotStates.waiting_credit_term)

    @dp.message(BotStates.waiting_credit_term)
    async def credit_term(message: Message, state: FSMContext):
        try: days = int(message.text)
        except: return await send_clean(message, "❌ Введи число.")
        if days < 1 or days > 7: return await send_clean(message, "❌ От 1 до 7 дней.")
        await state.update_data(credit_term=days)
        await send_clean(message, "4️⃣ На какую <b>цель</b> берешь кредит?")
        await state.set_state(BotStates.waiting_credit_purpose)

    @dp.message(BotStates.waiting_credit_purpose)
    async def credit_purpose(message: Message, state: FSMContext):
        data = await state.get_data(); data["credit_purpose"] = message.text
        user = message.from_user; await state.clear()
        req_id = f"{user.id}_{int(time.time())}"
        credit_requests[req_id] = {"user_id": user.id, **data}
        admin_txt = f"💳 <b>НОВАЯ ЗАЯВКА</b>\n👤 @{user.username or 'user'}\n💰 {fmt_num(data['credit_amount'])}\n📅 {data['credit_term']} дней\n🎯 {data['credit_purpose']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"cr_acc_{req_id}")],[InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cr_dec_{req_id}")]])
        try: await message.bot.send_message(ADMIN_ID, admin_txt, reply_markup=kb); await send_clean(message, "✅ Заявка отправлена!", reply_markup=main_menu())
        except: await send_clean(message, "❌ Ошибка", reply_markup=main_menu())

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
        if debt <= 0: return await send_clean(message, "✅ У тебя нет долгов!", reply_markup=bank_menu())
        if get_balance(uid) < debt: return await send_clean(message, f"❌ Мало средств! Долг: {fmt_num(debt)}", reply_markup=bank_menu())
        set_balance(uid, -debt)
        conn = get_conn(); c = conn.cursor(); c.execute("UPDATE users SET credit_debt = 0 WHERE user_id = %s", (uid,)); conn.commit(); c.close(); release_conn(conn)
        await send_clean(message, f"✅ Кредит погашен! Списано: {fmt_num(debt)}", reply_markup=bank_menu())

    # ================= ГРУППА: БАЛАНС И ПЕРЕВОД =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        bal = get_balance(uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Открыть кейс", url=f"https://t.me/{bot.username}?start=case")]])
        txt = f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 {fmt_num(bal)} Tokens\n\n👇 <i>Нажми на кнопку, чтобы открыть кейс!</i>"
        msg = await message.reply(txt, reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
    async def transfer_by_id(message: Message):
        parts = message.text.split(); uid = message.from_user.id
        try: target_id = int(parts[1]); amount = int(parts[2])
        except: return
        if amount < 10: return await message.reply("❌ Мин. 10.")
        if get_balance(uid) < amount: return await message.reply("❌ Мало.")
        set_balance(uid, -amount); set_balance(target_id, amount)
        await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 {fmt_num(amount)}")

    # ================= ИГРЫ =================
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
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "баскетбол ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "фут ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")

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
        asyncio.create_task(delete_message_later(msg, 150))

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
        del active_bets[chat_id]; is_spinning[chat_id] = False

    # ================= ПОДДЕРЖКА (КРАСИВАЯ) =================
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🆘 @{bot.username}")
        txt = "🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n👇 Выбери тему:"
        try: await message.answer_photo(photo=FSInputFile("support.jpg"), caption=txt, reply_markup=support_menu())
        except: await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>ПРОБЛЕМА С TOKENS</b>\n\n"
            "1️⃣ <b>Проверь оплату.</b> Настройки -> Мои подарки.\n"
            "2️⃣ <b>Подожди 5–10 минут.</b> Stars идут с задержкой.\n"
            "3️⃣ <b>Перезапусти бота.</b> Напиши /start.\n\n"
            f"📩 <b>Если не помогло:</b> {SUPPORT_USERNAME}\n"
            "Пришли скриншот чека. Мы всё вернём! 🙏"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🎮 <b>ОШИБКА В ИГРЕ</b>\n\n"
            "Опиши проблему:\n"
            "1️⃣ В какой игре?\n"
            "2️⃣ Что вводил?\n"
            "3️⃣ Что случилось?\n\n"
            "📸 <b>Пришли скриншот!</b>\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>ВОПРОС ПО ОПЛАТЕ</b>\n\n"
            "Все покупки через <b>Telegram Stars ⭐</b>.\n"
            "• Выбираешь пакет -> счет -> оплата.\n"
            "• Токены приходят за 10 секунд.\n\n"
            f"📩 <b>Вопросы:</b> {SUPPORT_USERNAME} ✍️"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🚫 <b>БАН ИЛИ МУТ</b>\n\n"
            "Если считаешь наказание ошибкой:\n"
            "1️⃣ Твой @username и ID.\n"
            "2️⃣ Причина блокировки.\n"
            "3️⃣ Время инцидента.\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🐞 <b>НАШЁЛ БАГ?</b>\n\n"
            "За реальный баг — бонус Tokens!\n\n"
            "Опиши подробно:\n"
            "1️⃣ Что делал?\n"
            "2️⃣ Что ожидал?\n"
            "3️⃣ Что случилось?\n\n"
            f"📩 <b>Отправь сюда:</b> {SUPPORT_USERNAME}\n"
            "За подтверждённый баг — бонус! 🎁"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            f"📜 <b>ПРАВИЛА {BOT_NAME.upper()}</b>\n\n"
            "1️⃣ Бот создан в развлекательных целях.\n"
            "2️⃣ Tokens не выводятся на реальные деньги.\n"
            "3️⃣ Игра разрешена только 18+.\n"
            "4️⃣ Запрещены мультиаккаунты и багоюз.\n"
            "5️⃣ Донат — добровольная поддержка.\n\n"
            "⚠️ <b>Нарушение = бан без предупреждения.</b>"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "✍️ Свой вопрос")
    async def support_custom_q(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "✍️ <b>СВОЙ ВОПРОС</b>\nНапиши свой вопрос, и я передам его администрации.\n\n👇 Жду сообщения...")
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
            admin_text = f"📩 <b>ВХОДЯЩЕЕ</b>\nОт: @{user.username or user.first_name}\nID: <code>{user.id}</code>\n\n💬 {message.text}\n\n<i>⚡ Ответь на это сообщение.</i>"
            try:
                sent_msg = await message.bot.send_message(ADMIN_ID, admin_text)
                support_replies[sent_msg.message_id] = user.id
                if current_state == "waiting_custom_support": await send_clean(message, "✅ Отправлено!", reply_markup=main_menu())
                else: await message.reply("✅ Доставлено.")
            except: await send_clean(message, "❌ Ошибка.", reply_markup=main_menu())

    @dp.message(lambda msg: msg.from_user.id == ADMIN_ID and msg.reply_to_message)
    async def admin_reply_to_support(message: Message):
        replied_msg_id = message.reply_to_message.message_id
        if replied_msg_id in support_replies:
            user_id = support_replies[replied_msg_id]
            user_text = f"📢 <b>ОТВЕТ ОТ ПОДДЕРЖКИ</b>\n\n💬 {message.text}\n\n<i>💡 Ответь на это сообщение для продолжения.</i>"
            try:
                sent_msg = await message.bot.send_message(user_id, user_text)
                support_replies[sent_msg.message_id] = ADMIN_ID
                await message.reply("✅ Отправлено!")
            except Exception as e: await message.reply(f"❌ Ошибка: {e}")

    # ================= АДМИНКА =================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
            "Добро пожаловать, Создатель!\n"
            "👇 Выбери нужный раздел:"
        )
        await send_clean(message, txt, reply_markup=admin_panel_kb())

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
            "• 🔍 <b>Скан</b> — посмотреть досье\n"
            "• 💰 <b>Выдать</b> — добавить токены\n"
            "• 💸 <b>Забрать</b> — списать токены\n"
            "• 🚫 <b>Бан</b> — заблокировать\n"
            "• ✅ <b>Разбан</b> — разблокировать"
        )
        await send_clean(message, txt, reply_markup=kb)

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
            "💰 <b>ЭКОНОМИКА</b>\n\n"
            f"👥 Всего игроков: <b>{tu}</b>\n"
            f"💎 Общий баланс: <b>{fmt_num(tb)}</b> Tokens\n\n"
            f"💱 Курс Stars: <b>1 ⭐ = {STARS_RATE} Tokens</b>"
        )
        await send_clean(message, txt, reply_markup=admin_panel_kb())

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
            "📊 <b>МОНИТОРИНГ</b>\n\n"
            f"🟢 Активных: <b>{a}</b>\n"
            f"🔴 Забанено: <b>{b}</b>\n\n"
            f"👑 Админ: <b>@{message.from_user.username}</b>"
        )
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ================= БАЛАНС В ГРУППЕ (ЖЕСТКИЙ ФИКС) =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal_fix(message: Message):
        uid = message.from_user.id
        bal = get_balance(uid)
        
        # Инлайн-кнопка для кейса в ЛС
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Открыть кейс", url=f"https://t.me/{bot.username}?start=case")]
        ])
        
        txt = (
            f"💳 <b>БАЛАНС</b>\n"
            f"👤 @{message.from_user.username or 'user'}\n"
            f"💰 <b>{fmt_num(bal)}</b> Tokens\n\n"
            f"👇 <i>Нажми на кнопку, чтобы открыть кейс!</i>"
        )
        msg = await message.reply(txt, reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 120))

    # ================= ПЕРЕВОД ПО ID (ЖЕСТКИЙ ФИКС) =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
    async def transfer_by_id_fix(message: Message):
        parts = message.text.split()
        uid = message.from_user.id
        try: 
            target_id = int(parts[1])
            amount = int(parts[2])
        except: 
            return
        
        if amount < 10: return await message.reply("❌ Мин. 10 токенов.")
        if get_balance(uid) < amount: return await message.reply("❌ Недостаточно средств.")
        
        set_balance(uid, -amount)
        set_balance(target_id, amount)
        await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 {fmt_num(amount)}")

    # ================= ИГРЫ И ЧТО НОВОГО (ЖЕСТКИЙ ФИКС) =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
    async def group_games_fix(message: Message):
        txt = (
            "🎮 <b>НАШИ ИГРЫ</b>\n\n"
            "🎡 <b>РУЛЕТКА</b>\n"
            "• <code>к 100</code> / <code>ч 100</code> / <code>з 100</code>\n"
            "• <code>го</code> — Запуск\n\n"
            "🎲 <b>КОСТИ</b> / 🎰 <b>СЛОТЫ</b> / 🏀 <b>БАСКЕТ</b> / ⚽ <b>ФУТБОЛ</b>\n"
            "• <code>кости 100</code> и т.д.\n\n"
            "💣 <b>МИНЫ</b> | ⚔️ <b>ДУЭЛИ</b> | 🪙 <b>МОНЕТКА</b>\n\n"
            "🎁 <b>Бонус:</b> <code>бонус</code>"
        )
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"что нового", "обнова"}))
    async def cmd_whats_new_fix(message: Message):
        txt = "🚀 <b>ОБНОВЛЕНИЕ v53!</b>\n\n💣 Мины\n🪙 Монетка 3.0\n⚔️ Дуэли\n🎁 Кейс\n💸 Переводы\n⚡ Скорость\n\n🔥 <i>Тестируй!</i>"
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))
        
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e:
        import traceback; traceback.print_exc()