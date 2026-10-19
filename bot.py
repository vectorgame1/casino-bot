# bot.py — MEGA UPDATE v44 (Финальный фикс)
import asyncio, logging, os, random, re, time
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatMemberUpdated
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL, SUPPORT_USERNAME
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb, support_menu, bank_menu
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game, get_rate
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

class BotStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_question = State()
    waiting_custom_stars = State()
    waiting_bank_amount = State()
    waiting_broadcast_target = State()
    waiting_broadcast_text = State()
    mines_game = State()
    waiting_credit_name = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_credit_purpose = State()

active_bets = {} 
active_duels = {}
is_spinning = {} 
support_replies = {}
cache_balance = {} 
cache_admin_stats = {"time": 0, "users": 0, "balance": 0, "banned": 0}
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
    app.router.add_get('/', health); app.router.add_get('/health', health)
    runner = web.AppRunner(app); await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    asyncio.create_task(start_web_server())
    init_pool(); init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ================= ПРИВЕТСТВИЕ =================
    @dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
    async def on_bot_added(event: ChatMemberUpdated):
        chat_id = event.chat.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS group_logs (chat_id BIGINT, detail TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, "Инициализация"))
            conn.commit()
        except: pass
        finally: c.close(); release_conn(conn)
        txt = f"👋 <b>СПАСИБО ЗА ДОБАВЛЕНИЕ!</b>\n━━━━━━━━━━━━━━\nМне очень приятно!\n\n🎮 Играй: рулетка, мины, кости.\n🎁 Кейс и бонус каждый день.\n⚔️ Дуэли с друзьями.\n\nНапиши <b>команды</b> для списка команд!"
        try: await bot.send_message(chat_id, txt)
        except: pass

    # ================= ОБЩИЕ =================
    @dp.message(F.text == "⬅️ Назад")
    async def btn_back(message: Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state in [BotStates.waiting_credit_name, BotStates.waiting_credit_amount, BotStates.waiting_credit_term, BotStates.waiting_credit_purpose]:
            await state.clear()
            return await send_clean(message, "❌ Заявка на кредит отменена.", reply_markup=main_menu())
        await state.clear()
        await send_clean(message, "🏠 <b>ГЛАВНОЕ МЕНЮ</b>\n━━━━━━━━━━━━━━\nВыбери раздел 👇", reply_markup=main_menu())

    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or message.from_user.first_name)
        
        # Проверка на бан
        if is_banned(user_id): 
            return await send_clean(message, "🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>\n━━━━━━━━━━━━━━\nВы были забанены в этом боте. Если это ошибка, напишите в поддержку.")
            
        args = message.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            try: ref_id = int(args[1].replace("ref_", ""))
            except: ref_id = 0
            if ref_id and ref_id != user_id:
                conn = get_conn(); c = conn.cursor()
                c.execute("SELECT balance FROM users WHERE user_id = %s", (ref_id,))
                if c.fetchone():
                    set_balance(ref_id, 10000)
                    try: await bot.send_message(ref_id, "🎉 <b>ДРУГ ЗАШЕЛ!</b>\n+10 000 Tokens!")
                    except: pass
                c.close(); release_conn(conn)
                
        is_new = check_and_give_bonus(user_id, START_BONUS)
        if message.chat.type != "private": return await message.reply(f"👋 ЛС: @{bot.username}")
        if user_id == ADMIN_ID: return await send_clean(message, "👑 <b>АДМИНКА</b>", reply_markup=admin_panel_kb())
        bonus = f"🎁 Бонус: +{fmt_num(START_BONUS)}\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n━━━━━━━━━━━━━━\n\n👋 {message.from_user.first_name}!\n{bonus}👇 Выбери действие:"
        try: await message.answer_photo(photo=FSInputFile("welcome.jpg"), caption=txt, reply_markup=main_menu())
        except: await message.answer(txt, reply_markup=main_menu())

    @dp.message(Command("ref"))
    async def cmd_ref(message: Message):
        if message.chat.type != "private": return await message.reply(f"🤝 ЛС: @{bot.username}")
        ref_link = f"https://t.me/{bot.username}?start=ref_{message.from_user.id}"
        await message.reply(f"🤝 <b>РЕФЕРАЛКА</b>\n━━━━━━━━━━━━━━\nЗа друга <b>10 000 Tokens</b>!\n\n🔗 <code>{ref_link}</code>")

    # ================= ЛС: БАЛАНС, ПРОФИЛЬ, КЕЙС =================
    @dp.message(F.chat.type == "private", F.text.lower().in_({"баланс", "б"}))
    @dp.message(F.text == "💰 Баланс")
    async def cmd_bal(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        if uid in cache_balance: bal = cache_balance[uid]
        else: bal = get_balance(uid); cache_balance[uid] = bal
        await send_clean(message, f"💳 <b>БАЛАНС</b>\n━━━━━━━━━━━━━━\n💰 {fmt_num(bal)} Tokens", reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"профиль", "я"}))
    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━\n🎖 {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💰 {fmt_num(get_balance(uid))}\n\n🎁 Ежедневный кейс: <code>кейс</code>"
        await send_clean(message, txt, reply_markup=main_menu())

    # 🎁 ЕЖЕДНЕВНЫЙ КЕЙС
    @dp.message(F.chat.type == "private", F.text.lower().in_({"кейс", "ежедневный кейс"}))
    async def daily_case(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_case_date DATE")
            conn.commit()
        except: conn.rollback()
        
        c.execute("SELECT last_case_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        
        if row and row[0] == today:
            c.close(); release_conn(conn)
            return await send_clean(message, "⏳ <b>КЕЙС УЖЕ ОТКРЫТ</b>\n━━━━━━━━━━━━━━\nТы уже открывал кейс сегодня. Приходи завтра!")
            
        c.execute("UPDATE users SET last_case_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        
        try:
            await message.answer_animation(FSInputFile("case.gif"), caption="🎁 <b>ОТКРЫВАЕМ КЕЙС...</b>")
        except Exception:
            await send_clean(message, "🎁 <b>ОТКРЫВАЕМ КЕЙС...</b>")
            
        await asyncio.sleep(2.5)
        
        prizes = [
            (5000, "💰 <b>Ты выиграл 5 000 Tokens!</b>"),
            (10000, "💰 <b>Ты выиграл 10 000 Tokens!</b>"),
            (25000, "💎 <b>ДЖЕКПОТ! 25 000 Tokens!</b>")
        ]
        amount, text = random.choice(prizes)
        set_balance(uid, amount)
        
        await send_clean(message, f"🎉 <b>КЕЙС ОТКРЫТ!</b>\n━━━━━━━━━━━━━━\n{text}\n━━━━━━━━━━━━━━\nПриходи завтра за новым кейсом!", reply_markup=main_menu())

    # ================= БАНК И КРЕДИТЫ =================
    @dp.message(F.chat.type == "private", F.text.lower().in_({"банк"}))
    @dp.message(F.text == "🏦 Банк")
    async def bank_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (message.from_user.id,)); row = c.fetchone(); bank = row[0] if row and row[0] is not None else 0
        except: bank = 0
        finally: c.close(); release_conn(conn)
        
        kb = bank_menu() # Используем функцию из keyboards.py
        
        txt = f"🏦 <b>БАНК</b>\n━━━━━━━━━━━━━━\n\n💎 На руках: <b>{fmt_num(bal)}</b>\n🏦 В сейфе: <b>{fmt_num(bank)}</b>\n\n📈 <b>Процент:</b> 5% в день\n\n👇 Действие:"
        try: await message.answer_photo(photo=FSInputFile("bank.jpg"), caption=txt, reply_markup=kb)
        except: await send_clean(message, txt, reply_markup=kb)

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
        if data.get("action") in ["credit_name", "credit_amount", "credit_term"]:
            return
            
        if message.text == "⬅️ Назад": 
            await state.clear(); return await bank_menu_handler(message, state)
            
        try: amount = int(message.text)
        except ValueError: return await send_clean(message, "❌ Введи число.")
        
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        if data.get("action") == "deposit":
            if get_balance(uid) < amount: 
                c.close(); release_conn(conn); return await send_clean(message, "❌ Недостаточно.")
            set_balance(uid, -amount); c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid)); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Внесено <b>{fmt_num(amount)}</b>.")
        else:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,)); row = c.fetchone(); bank = row[0] if row else 0
            if bank < amount: 
                c.close(); release_conn(conn); return await send_clean(message, "❌ Мало в банке.")
            c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid)); set_balance(uid, amount); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Снято <b>{fmt_num(amount)}</b>.")
        await state.clear(); await bank_menu_handler(message, state)

    @dp.message(F.text == "💳 Кредит")
    async def credit_start(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "💳 <b>ЗАЯВКА НА КРЕДИТ</b>\n━━━━━━━━━━━━━━\nУсловия: от 10 000 до 100 000 под 3% в день.\n\n1️⃣ Введи свое <b>Имя и Фамилию</b>:")
        await state.set_state(BotStates.waiting_credit_name)

    @dp.message(BotStates.waiting_credit_name)
    async def credit_get_name(message: Message, state: FSMContext):
        await state.update_data(credit_name=message.text)
        await send_clean(message, "2️⃣ Введи <b>желаемую сумму</b> (от 10 000 до 100 000):")
        await state.set_state(BotStates.waiting_credit_amount)

    @dp.message(BotStates.waiting_credit_amount)
    async def credit_get_amount(message: Message, state: FSMContext):
        try: amount = int(message.text)
        except ValueError: return await send_clean(message, "❌ Введи число.")
        if amount < 10000 or amount > 100000: return await send_clean(message, "❌ От 10 000 до 100 000.")
        await state.update_data(credit_amount=amount)
        await send_clean(message, "3️⃣ На какой <b>срок</b> (в днях) берешь кредит?")
        await state.set_state(BotStates.waiting_credit_term)

    @dp.message(BotStates.waiting_credit_term)
    async def credit_get_term(message: Message, state: FSMContext):
        try: term = int(message.text)
        except ValueError: return await send_clean(message, "❌ Введи число дней.")
        await state.update_data(credit_term=term)
        await send_clean(message, "4️⃣ На какую <b>цель</b> берешь кредит?")
        await state.set_state(BotStates.waiting_credit_purpose)

    @dp.message(BotStates.waiting_credit_purpose)
    async def credit_get_purpose(message: Message, state: FSMContext):
        data = await state.get_data()
        data["credit_purpose"] = message.text
        user = message.from_user
        await state.clear()
        
        req_id = f"{user.id}_{int(time.time())}"
        credit_requests[req_id] = {"user_id": user.id, **data}
        
        admin_txt = (
            f"💳 <b>НОВАЯ ЗАЯВКА НА КРЕДИТ</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 <b>От:</b> @{user.username or user.first_name} (ID: <code>{user.id}</code>)\n"
            f"📝 <b>Имя:</b> {data['credit_name']}\n"
            f"💰 <b>Сумма:</b> {fmt_num(data['credit_amount'])} Tokens\n"
            f"📅 <b>Срок:</b> {data['credit_term']} дней\n"
            f"🎯 <b>Цель:</b> {data['credit_purpose']}\n"
            f"━━━━━━━━━━━━━━\n"
            f"<i>Одобрить или отклонить?</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ОДОБРИТЬ", callback_data=f"credit_accept_{req_id}")],
            [InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"credit_decline_{req_id}")]
        ])
        
        try:
            await message.bot.send_message(ADMIN_ID, admin_txt, reply_markup=kb)
            await send_clean(message, "✅ <b>ЗАЯВКА ОТПРАВЛЕНА!</b>\n━━━━━━━━━━━━━━\nЖди решения администрации.", reply_markup=main_menu())
        except Exception:
            await send_clean(message, "❌ Ошибка отправки.", reply_markup=main_menu())

    @dp.callback_query(F.data.startswith("credit_accept_"))
    async def credit_accept_handler(call: CallbackQuery):
        req_id = call.data.replace("credit_accept_", "")
        if req_id not in credit_requests: return await call.answer("❌ Заявка устарела.", show_alert=True)
        req = credit_requests[req_id]
        uid = req["user_id"]; amount = req["credit_amount"]
        set_balance(uid, amount)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_debt BIGINT DEFAULT 0")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_days_left INT DEFAULT 0")
            c.execute("UPDATE users SET credit_debt = %s, credit_days_left = %s WHERE user_id = %s", (amount * 1.03, req["credit_term"], uid))
            conn.commit()
        except: pass
        finally: c.close(); release_conn(conn)
        await call.message.edit_text(f"✅ <b>КРЕДИТ ОДОБРЕН</b>\nИгроку @{req.get('credit_name')} выдано {fmt_num(amount)} Tokens.\nК возврату: {fmt_num(int(amount*1.03))} за {req['credit_term']} дней.")
        try: await call.bot.send_message(uid, f"🎉 <b>КРЕДИТ ОДОБРЕН!</b>\n━━━━━━━━━━━━━━\nТебе выдано: <b>{fmt_num(amount)} Tokens</b>\nК возврату: <b>{fmt_num(int(amount*1.03))}</b> (3% в день) за {req['credit_term']} дней.\nНе забудь вернуть долг!")
        except: pass
        del credit_requests[req_id]
        await call.answer("Кредит выдан!")

    @dp.callback_query(F.data.startswith("credit_decline_"))
    async def credit_decline_handler(call: CallbackQuery):
        req_id = call.data.replace("credit_decline_", "")
        if req_id not in credit_requests: return await call.answer("❌ Устарело.", show_alert=True)
        req = credit_requests[req_id]
        await call.message.edit_text(f"❌ <b>КРЕДИТ ОТКЛОНЕН</b>\nЗаявка от @{req.get('credit_name')} отклонена.")
        try: await call.bot.send_message(req["user_id"], "❌ <b>ЗАЯВКА НА КРЕДИТ ОТКЛОНЕНА</b>\n━━━━━━━━━━━━━━\nАдминистрация отклонила твою заявку.")
        except: pass
        del credit_requests[req_id]
        await call.answer("Отклонено.")

    # 💸 ПОГАШЕНИЕ КРЕДИТА
    @dp.message(F.text == "💸 Погасить кредит")
    async def credit_repay(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT credit_debt FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            debt = row[0] if row and row[0] else 0
        except Exception:
            debt = 0
        finally:
            c.close(); release_conn(conn)
            
        if debt <= 0:
            return await send_clean(message, "✅ <b>У ТЕБЯ НЕТ ДОЛГОВ!</b>\n━━━━━━━━━━━━━━\nТы чист перед банком.", reply_markup=bank_menu())
            
        bal = get_balance(uid)
        if bal < debt:
            return await send_clean(message, f"❌ <b>НЕДОСТАТОЧНО СРЕДСТВ</b>\n━━━━━━━━━━━━━━\n💰 Твой баланс: <b>{fmt_num(bal)}</b>\n💳 Твой долг: <b>{fmt_num(debt)}</b>\n━━━━━━━━━━━━━━\nНе хватает: <b>{fmt_num(debt - bal)}</b> Tokens.", reply_markup=bank_menu())
            
        set_balance(uid, -debt)
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE users SET credit_debt = 0, credit_days_left = 0 WHERE user_id = %s", (uid,))
        conn.commit(); c.close(); release_conn(conn)
        
        await send_clean(message, f"✅ <b>КРЕДИТ ПОГАШЕН!</b>\n━━━━━━━━━━━━━━\n💸 Списано: <b>{fmt_num(debt)}</b> Tokens\n💎 Остаток на балансе: <b>{fmt_num(get_balance(uid))}</b>\n━━━━━━━━━━━━━━\nТвоя кредитная история чиста! 🤝", reply_markup=bank_menu())

    # ================= ИГРЫ =================
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
        uid = message.from_user.id; username = message.from_user.username or message.from_user.first_name
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet); sent = await message.answer_dice(emoji=emoji); await asyncio.sleep(2.5); res = sent.dice.value
        if win_cond(res):
            win = int(bet * win_mult); set_balance(uid, win); log_game(uid, username, game_name, bet, win, str(res))
            txt = win_txt.format(result=res, win=fmt_num(win))
        else:
            log_game(uid, username, game_name, bet, 0, str(res)); txt = lose_txt.format(result=res, bet=fmt_num(bet))
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "баскетбол ")))
    async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "фут ")))
    async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("спин ", "слот ")))
    async def play_slots(message: Message):
        uid = message.from_user.id; parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        set_balance(uid, -bet); sent = await message.answer_dice(emoji="🎰"); await asyncio.sleep(2.5); res = sent.dice.value
        if res >= 32: win = int(bet * 1.8); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "слоты", bet, win, str(res)); txt = f"🎰 🎉 +{fmt_num(win)}"
        elif res >= 10: win = int(bet * 1.2); set_balance(uid, win); log_game(uid, message.from_user.username or "user", "слоты", bet, win, str(res)); txt = f"🎰 🎉 +{fmt_num(win)}"
        else: log_game(uid, message.from_user.username or "user", "слоты", bet, 0, str(res)); txt = f"🎰 😢 -{fmt_num(bet)}"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

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
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

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
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

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
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

    # 💣 МИНЫ
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2: return await message.reply("❌ <code>мины 100</code>")
        try: bet = int(parts[1])
        except: return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet); mines = random.sample(list(range(25)), 3)
        await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0); await state.set_state(BotStates.mines_game)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
        msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n\nОткрывай клетки!", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 300))

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
        opened.append(idx); mult = round(1.0 + (len(opened) * 0.25), 2); await state.update_data(opened=opened, mult=mult)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
        await call.message.edit_text(f"💣 <b>МИНЫ</b>\n💰 {fmt_num(bet)}\n📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\nОткрывай дальше!", reply_markup=kb); await call.answer("Безопасно!")

    # ================= РУЛЕТКА =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт)\s+(\d+)$"))
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        word_part = None; num_part = None
        for p in parts:
            if p.isdigit(): num_part = p
            elif p in ["к", "ч", "з", "чет", "чёт", "нечет", "нечёт"]: word_part = p
        if not word_part or not num_part: return
        bet_type = {"к":"red", "ч":"black", "з":"green", "чет":"even", "чёт":"even", "нечет":"odd", "нечёт":"odd"}.get(word_part)
        try: bet = int(num_part)
        except: return
        if bet < 1: return await message.reply("❌ Мин. 1.")
        bal = get_balance(uid)
        if bal < bet: return await message.reply(f"❌ Мало. Баланс: {fmt_num(bal)}")
        set_balance(uid, -bet)
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        async def auto_cancel():
            await asyncio.sleep(150)
            if chat_id in active_bets and active_bets[chat_id]["bets"]:
                for b in active_bets[chat_id]["bets"]: set_balance(b["user_id"], b["bet"])
                m = await message.answer("⏰ <b>ВРЕМЯ ВЫШЛО!</b> Ставки отменены."); asyncio.create_task(delete_message_later(m, 30))
                del active_bets[chat_id]
        active_bets[chat_id]["timer"] = asyncio.create_task(auto_cancel())
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!")
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"^\d+\s+([0-9\-]+\s*)+$"))
    async def place_range_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        try: bet = int(parts[0])
        except ValueError: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
        bet_numbers = set()
        for p in parts[1:]:
            if "-" in p:
                try:
                    s, e = map(int, p.split("-"))
                    if 0 <= s <= e <= 36: [bet_numbers.add(num) for num in range(s, e + 1)]
                except: pass
            else:
                try:
                    n = int(p)
                    if 0 <= n <= 36: bet_numbers.add(n)
                except: pass
        if not bet_numbers: return await message.reply("❌ Ошибка диапазона.")
        count = len(bet_numbers); mult = round((36 / count) * 0.95, 2)
        set_balance(uid, -bet)
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": "numbers", "numbers": list(bet_numbers), "bet": bet, "mult": mult})
        async def auto_cancel():
            await asyncio.sleep(150)
            if chat_id in active_bets and active_bets[chat_id]["bets"]:
                for b in active_bets[chat_id]["bets"]: set_balance(b["user_id"], b["bet"])
                m = await message.answer("⏰ <b>ВРЕМЯ ВЫШЛО!</b> Ставки отменены."); asyncio.create_task(delete_message_later(m, 30))
                del active_bets[chat_id]
        active_bets[chat_id]["timer"] = asyncio.create_task(auto_cancel())
        msg = await message.reply(f"🎰 <b>СТАВКА НА ЧИСЛА</b>\n@{message.from_user.username or 'user'} | Чисел: {count} | {fmt_num(bet)} (x{mult})\n⚡️ <b>го</b>!")
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "ставки")
    async def show_bets(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("📊 Нет ставок.")
        txt = "📊 <b>СТАВКИ</b>\n"; total = 0
        for b in active_bets[chat_id]["bets"]:
            txt += f"• @{b['username']}: <b>{fmt_num(b['bet'])}</b>\n"; total += b["bet"]
        txt += f"━━━━━━━━━━━━━━\n💰 <b>Банк: {fmt_num(total)}</b>"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "отмена")
    async def cancel_bets(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
        if chat_id in active_bets:
            my = [b for b in active_bets[chat_id]["bets"] if b["user_id"]==uid]
            if my:
                set_balance(uid, sum(b["bet"] for b in my))
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"]!=uid]
                if not active_bets[chat_id]["bets"]:
                    if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
                    del active_bets[chat_id]
                msg = await message.reply(f"❌ Отменено на <b>{fmt_num(sum(b['bet'] for b in my))}</b>."); asyncio.create_task(delete_message_later(msg, 150)); return
        await message.reply("📊 У тебя нет ставок.")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
        if is_spinning.get(chat_id, False): return await message.reply("⏳ <b>РУЛЕТКА УЖЕ ЗАПУЩЕНА!</b>\nПодожди.")
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок.")
        user_has_bet = any(b["user_id"] == uid for b in active_bets[chat_id]["bets"])
        if not user_has_bet: return await message.reply("❌ <b>ТОЛЬКО ИГРОКИ СО СТАВКОЙ МОГУТ ЗАПУСКАТЬ РУЛЕТКУ!</b>")
        is_spinning[chat_id] = True
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 <b>КРУТИТСЯ...</b>\n💰 {fmt_num(total)}")
        except: msg = await message.reply(f"🎡 <b>КРУТИТСЯ...</b>\n💰 {fmt_num(total)}")
        await asyncio.sleep(3)
        res = random.randint(0, 36); color = get_color(res); win, lose = [], []
        for b in bets:
            w = 0
            if b["type"]=="red" and res in RED: w=int(b["bet"]*1.95)
            elif b["type"]=="black" and res in BLACK: w=int(b["bet"]*1.95)
            elif b["type"]=="green" and res==0: w=int(b["bet"]*35)
            elif b["type"]=="even" and res!=0 and res%2==0: w=int(b["bet"]*1.95)
            elif b["type"]=="odd" and res%2!=0: w=int(b["bet"]*1.95)
            elif b["type"]=="numbers":
                if res in b["numbers"]: w = int(b["bet"] * b["mult"])
            if w > 0: set_balance(b["user_id"], w); win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else: lose.append(f"💔 @{b['username']}")
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n━━━━━━━━━━━━━━\n"
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        conn = get_conn(); c = conn.cursor()
        try: c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, f"{color}{res}"))
        except: pass
        finally: conn.commit(); c.close(); release_conn(conn)
        del active_bets[chat_id]
        is_spinning[chat_id] = False

    # ================= ДУЭЛИ =================
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

    # ================= ОПЛАТА =================
    @dp.pre_checkout_query()
    async def pre_check(query: PreCheckoutQuery): await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_"):
            _, stars, amount = payload.split("_"); set_balance(message.from_user.id, int(amount))
            await message.answer(f"✅ Зачислено <b>{fmt_num(int(amount))}</b> Tokens.")

    # ================= АДМИНКА =================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИНКА</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Скан")],[KeyboardButton(text="💰 Выдать"), KeyboardButton(text="💸 Забрать")],[KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "👥 <b>УПРАВЛЕНИЕ</b>", reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИНКА</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "🔍 Скан")
    async def adm_scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🔍 Введи @username или ID:"); await state.set_state(BotStates.waiting_scan); await state.update_data(action="scan")

    @dp.message(F.text == "💰 Выдать")
    async def adm_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 @username и сумма:"); await state.set_state(BotStates.waiting_amount); await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать")
    async def adm_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 @username и сумма:"); await state.set_state(BotStates.waiting_amount); await state.update_data(action="take")

    @dp.message(BotStates.waiting_amount)
    async def adm_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); parts = message.text.split()
        if len(parts) != 2: return await send_clean(message, "❌ @user сумма")
        target = parts[0].replace("@", ""); uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await send_clean(message, "❌ Не найден.")
        try: amount = int(parts[1])
        except: return await send_clean(message, "❌ Число.")
        set_balance(uid, amount if data["action"]=="give" else -amount)
        await send_clean(message, f"✅ {'Выдано' if data['action']=='give' else 'Списано'} {fmt_num(amount)}."); await state.clear()

    @dp.message(F.text == "🚫 Бан")
    async def adm_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🚫 @username:"); await state.set_state(BotStates.waiting_scan); await state.update_data(action="ban")

    @dp.message(F.text == "✅ Разбан")
    async def adm_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "✅ @username:"); await state.set_state(BotStates.waiting_scan); await state.update_data(action="unban")

    @dp.message(BotStates.waiting_scan)
    async def adm_scan(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); target = message.text.replace("@", "").strip()
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: await state.clear(); return await send_clean(message, "❌ Не найден.")
        if data.get("action")=="ban": set_banned(uid, True); await send_clean(message, "🚫 Забанен.")
        elif data.get("action")=="unban": set_banned(uid, False); await send_clean(message, "✅ Разбанен.")
        elif data.get("action")=="scan":
            conn = get_conn(); c = conn.cursor(); c.execute("SELECT username, balance, bank, xp, banned FROM users WHERE user_id=%s",(uid,)); row=c.fetchone()
            c.execute("SELECT game, bet, win FROM game_log WHERE user_id=%s ORDER BY id DESC LIMIT 5", (uid,)); recent = c.fetchall()
            c.close(); release_conn(conn)
            if row:
                uname, bal, bank, xp, banned = row; status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
                txt = f"🕵️ <b>ДОСЬЕ</b>\n👤 @{uname}\n🆔 <code>{uid}</code>\n📊 {status}\n💎 {fmt_num(bal)}\n🏦 {fmt_num(bank)}\n⭐ XP: {xp}\n\n🎮 <b>Игры:</b>\n"
                txt += "\n".join([f"• {g} | {fmt_num(b)} | {fmt_num(w)}" for g, b, w in recent]) if recent else "Нет."
                await send_clean(message, txt)
        await state.clear()

    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📢 Всем")],[KeyboardButton(text="🎯 По @username")],[KeyboardButton(text="🆔 По ID")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "📢 <b>РАССЫЛКА</b>", reply_markup=kb)

    @dp.message(F.text == "📢 Всем")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📢 Текст для всех:"); await state.set_state(BotStates.waiting_broadcast_text); await state.update_data(target="all")

    @dp.message(F.text == "🎯 По @username")
    async def broadcast_user_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🎯 @username:"); await state.set_state(BotStates.waiting_broadcast_target); await state.update_data(mode="user")

    @dp.message(F.text == "🆔 По ID")
    async def broadcast_id_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🆔 ID:"); await state.set_state(BotStates.waiting_broadcast_target); await state.update_data(mode="id")

    @dp.message(BotStates.waiting_broadcast_target)
    async def broadcast_target_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); target = message.text.strip()
        uid = get_user_id_by_username(target.replace("@", "")) if data["mode"] == "user" else (int(target) if target.isdigit() else None)
        if not uid: await state.clear(); return await send_clean(message, "❌ Не найден.")
        await state.update_data(target=uid); await send_clean(message, "✍️ Текст:"); await state.set_state(BotStates.waiting_broadcast_text)

    @dp.message(BotStates.waiting_broadcast_text)
    async def broadcast_text_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); target = data.get("target")
        if target == "all":
            conn = get_conn(); c = conn.cursor(); c.execute("SELECT user_id FROM users"); users = c.fetchall(); c.close(); release_conn(conn)
            sent = 0; await send_clean(message, f"⏳ Рассылка на {len(users)}...")
            for (uid,) in users:
                try: await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}"); sent += 1; await asyncio.sleep(0.05)
                except: pass
            await send_clean(message, f"✅ Отправлено: {sent}")
        else:
            try: await message.bot.send_message(target, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}"); await send_clean(message, "✅ Отправлено!")
            except Exception as e: await send_clean(message, f"❌ Ошибка: {e}")
        await state.clear()

    @dp.message(F.text == "🎮 Игры")
    async def admin_games_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor(); c.execute("SELECT COUNT(*) FROM game_log"); tg = c.fetchone()[0]; c.close(); release_conn(conn)
        await send_clean(message, f"🎮 <b>ИГРЫ</b>\n📊 Всего: <b>{tg}</b>\n✅ Работают.", reply_markup=admin_panel_kb())

    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor(); c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users"); tu, tb = c.fetchone(); c.close(); release_conn(conn)
        await send_clean(message, f"💰 <b>ЭКОНОМИКА</b>\n👥 {tu}\n💎 {fmt_num(tb)}\n💱 1 ⭐ = {STARS_RATE}", reply_markup=admin_panel_kb())

    @dp.message(F.text == "🛒 Контент")
    async def admin_content_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, f"🛒 <b>КОНТЕНТ</b>\nВ разработке.", reply_markup=admin_panel_kb())

    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor(); c.execute("SELECT COUNT(*) FROM users WHERE banned = FALSE"); a = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE"); b = c.fetchone()[0]; c.close(); release_conn(conn)
        await send_clean(message, f"📊 <b>МОНИТОРИНГ</b>\n🟢 {a}\n🔴 {b}\n👑 @{message.from_user.username}", reply_markup=admin_panel_kb())

    @dp.message(F.text == "📋 Все команды")
    async def admin_all_commands(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📋 /admin\n/give @user сумма\n/ban @user\n/unban @user", reply_markup=admin_panel_kb())

    # ================= ПОДДЕРЖКА =================
    support_replies = {}

    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": 
            return await message.reply(f"🆘 Поддержка доступна только в личных сообщениях: @{bot.username}")
        
        txt = (
            "🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👋 Привет! Если у тебя возникли проблемы, выбери тему обращения ниже.\n\n"
            "👇 <i>Нажми на нужную кнопку:</i>"
        )
        try: 
            await message.answer_photo(photo=FSInputFile("support.jpg"), caption=txt, reply_markup=support_menu())
        except Exception: 
            await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "✍️ Свой вопрос")
    async def support_custom_q(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, 
            "✍️ <b>СВОЙ ВОПРОС</b>\n"
            "━━━━━━━━━━━━━━\n"
            "Напиши свой вопрос одним сообщением, и я передам его администрации.\n\n"
            "👇 <i>Жду твоего сообщения...</i>"
        )
        await state.set_state("waiting_custom_support")

    @dp.message(lambda msg: msg.from_user.id != ADMIN_ID) 
    async def catch_custom_q(message: Message, state: FSMContext):
        current_state = await state.get_state()
        is_reply = message.reply_to_message and message.reply_to_message.message_id in support_replies
        
        ignore_texts = ["💎 Tokens не пришли", "🎮 Что-то сломалось в игре", "💳 Вопрос по оплате", 
                        "🚫 Бан или мут", "🐞 Нашёл баг", "📜 Правила бота", "✍️ Свой вопрос", "⬅️ Назад"]
        if message.text in ignore_texts:
            return

        if current_state == "waiting_custom_support" or is_reply:
            await state.clear()
            user = message.from_user
            
            admin_text = (
                f"📩 <b>ВХОДЯЩЕЕ СООБЩЕНИЕ</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"👤 <b>От:</b> @{user.username or user.first_name}\n"
                f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💬 <b>Текст:</b>\n"
                f"{message.text}\n\n"
                f"<i>⚡ Чтобы ответить, зажми это сообщение и нажми «Ответить».</i>"
            )
            try:
                sent_msg = await message.bot.send_message(ADMIN_ID, admin_text)
                support_replies[sent_msg.message_id] = user.id
                if current_state == "waiting_custom_support":
                    await send_clean(message, "✅ <b>ОТПРАВЛЕНО!</b>\n━━━━━━━━━━━━━━\nЖди ответа от администрации.", reply_markup=main_menu())
                else:
                    await message.reply("✅ Доставлено администрации.")
            except Exception:
                await send_clean(message, "❌ Ошибка отправки.", reply_markup=main_menu())

    @dp.message(lambda msg: msg.from_user.id == ADMIN_ID and msg.reply_to_message)
    async def admin_reply_to_support(message: Message):
        replied_msg_id = message.reply_to_message.message_id
        if replied_msg_id in support_replies:
            user_id = support_replies[replied_msg_id]
            
            user_text = (
                f"📢 <b>ОТВЕТ ОТ ПОДДЕРЖКИ</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"👑 <b>Администрация на связи</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💬 <b>Сообщение:</b>\n"
                f"{message.text}\n\n"
                f"<i>💡 Если у тебя есть еще вопросы, просто ответь на это сообщение!</i>"
            )
            try:
                sent_msg = await message.bot.send_message(user_id, user_text)
                support_replies[sent_msg.message_id] = ADMIN_ID
                await message.reply("✅ <b>ОТВЕТ ОТПРАВЛЕН!</b>")
            except Exception as e:
                await message.reply(f"❌ Ошибка: {e}")

    # ТЕКСТЫ ДЛЯ ОСТАЛЬНЫХ КНОПОК
    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>ПРОБЛЕМА С TOKENS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
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
            "🎮 <b>ОШИБКА В ИГРЕ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Опиши проблему, чтобы мы починили:\n"
            "1️⃣ В какой игре?\n"
            "2️⃣ Что вводил?\n"
            "3️⃣ Что пошло не так?\n\n"
            "📸 <b>Пришли скриншот</b> — это ускорит починку!\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>ВОПРОС ПО ОПЛАТЕ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Все покупки идут через <b>Telegram Stars ⭐</b>.\n\n"
            "<b>Как работает:</b>\n"
            "• Выбираешь пакет -> счет -> оплата.\n"
            "• Токены приходят за 10 секунд.\n\n"
            f"📩 <b>Вопросы:</b> {SUPPORT_USERNAME} ✍️"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🚫 <b>БАН ИЛИ МУТ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Если считаешь наказание ошибкой:\n"
            "1️⃣ Твой @username и ID.\n"
            "2️⃣ Причина блокировки.\n"
            "3️⃣ Время инцидента.\n\n"
            "⚠️ <b>Важно:</b> Если есть долг — сначала верни его.\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🐞 <b>НАШЁЛ БАГ?</b>\n"
            "━━━━━━━━━━━━━━\n\n"
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
            f"📜 <b>ПРАВИЛА {BOT_NAME.upper()}</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "1️⃣ Бот создан в развлекательных целях.\n"
            "2️⃣ Tokens не выводятся на реальные деньги.\n"
            "3️⃣ Игра разрешена только 18+.\n"
            "4️⃣ Запрещены мультиаккаунты и багоюз.\n"
            "5️⃣ Донат — добровольная поддержка.\n\n"
            "⚠️ <b>Нарушение = бан без предупреждения.</b>"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    # ================= БАЛАНС (ОГРОМНЫЙ) =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        bal = get_balance(uid)
        cache_balance[uid] = bal
        
        txt = (
            f"💳 <b>БАЛАНС ИГРОКА</b>\n"
            f"╔══════════════════════╗\n"
            f"║ 👤 <b>Игрок:</b> @{message.from_user.username or 'user'}\n"
            f"║ 💎 <b>На счету:</b> {fmt_num(bal)} Tokens\n"
            f"╚══════════════════════╝\n\n"
            f"<i>Чтобы пополнить, зайди в ЛС бота.</i>"
        )
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 150))

    # ================= ЗАПУСК =================
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ ОШИБКА: {e}")