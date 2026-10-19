# bot.py — MEGA UPDATE v37 (ПОЛНЫЙ КОД)
import asyncio, logging, os, random, re
from datetime import datetime
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
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb, support_menu
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

active_bets = {} 
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

    # ================= ПРИВЕТСТВИЕ В ГРУППЕ =================
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
        txt = f"👋 <b>СПАСИБО ЗА ДОБАВЛЕНИЕ!</b>\n━━━━━━━━━━━━━━\nМне очень приятно!\n\n🎮 Играй: рулетка, мины, кости.\n🎁 Бонус каждый день.\n⚔️ Дуэли с друзьями.\n\nНапиши <b>игры</b> для списка команд!\n<i>(История логов для этой группы создана)</i>"
        try: await bot.send_message(chat_id, txt)
        except: pass

    # ================= ОБЩИЕ КНОПКИ =================
    @dp.message(F.text == "⬅️ Назад")
    async def btn_back(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "🏠 <b>ГЛАВНОЕ МЕНЮ</b>\n━━━━━━━━━━━━━━\nВыбери раздел 👇", reply_markup=main_menu())

    # ================= СТАРТ =================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or message.from_user.first_name)
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
        if is_banned(user_id): return await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>")
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

    # ================= ЛС =================
    @dp.message(F.chat.type == "private", F.text.lower().in_({"баланс", "б"}))
    @dp.message(F.text == "💰 Баланс")
    async def cmd_bal(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, f"💳 <b>БАЛАНС</b>\n━━━━━━━━━━━━━━\n💰 {fmt_num(get_balance(message.from_user.id))} Tokens", reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"профиль", "я"}))
    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━\n🎖 {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💰 {fmt_num(get_balance(uid))}"
        await send_clean(message, txt, reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"банк"}))
    @dp.message(F.text == "🏦 Банк")
    async def bank_menu(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (message.from_user.id,)); row = c.fetchone(); bank = row[0] if row and row[0] is not None else 0
        except: bank = 0
        finally: c.close(); release_conn(conn)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📥 Положить"), KeyboardButton(text="📤 Снять")],[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
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
        if message.text == "⬅️ Назад": await state.clear(); return await bank_menu(message, state)
        data = await state.get_data()
        try: amount = int(message.text)
        except ValueError: return await send_clean(message, "❌ Введи число.")
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        if data["action"] == "deposit":
            if get_balance(uid) < amount: c.close(); release_conn(conn); return await send_clean(message, "❌ Недостаточно.")
            set_balance(uid, -amount); c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid)); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Внесено <b>{fmt_num(amount)}</b>.")
        else:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,)); row = c.fetchone(); bank = row[0] if row else 0
            if bank < amount: c.close(); release_conn(conn); return await send_clean(message, "❌ Мало в банке.")
            c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid)); set_balance(uid, amount); conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ Снято <b>{fmt_num(amount)}</b>.")
        await state.clear(); await bank_menu(message, state)

    @dp.message(F.chat.type == "private", F.text.lower().in_({"донат", "магазин"}))
    @dp.message(F.text == "🏪 Донат")
    async def cmd_don(message: Message, state: FSMContext):
        await state.clear()
        rate = get_rate("stars_rate", STARS_RATE)
        txt = f"💳 <b>ПОПОЛНЕНИЕ</b>\n━━━━━━━━━━━━━━\n1 ⭐ = {fmt_num(rate)} Tokens\n\n👇 Введи Stars (1-10000):"
        try: await message.answer_photo(photo=FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=donate_menu())
        except: await send_clean(message, txt, reply_markup=donate_menu())
        await state.set_state(BotStates.waiting_custom_stars)

    @dp.message(BotStates.waiting_custom_stars)
    async def custom_sum_process(message: Message, state: FSMContext):
        if message.text == "⬅️ Назад": await state.clear(); return await send_clean(message, "🏠 МЕНЮ", reply_markup=main_menu())
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000: return await send_clean(message, "❌ 1-10000.")
            tokens = stars * get_rate("stars_rate", STARS_RATE)
            await message.answer_invoice(title=f"{tokens:,} Tokens", description=f"Покупка {tokens:,} Tokens", payload=f"buy_{stars}_{tokens}", provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{tokens:,} Tokens", amount=stars)])
            await state.clear()
        except ValueError: await send_clean(message, "❌ Число.")

    @dp.message(F.text == "🎰 Игры")
    async def btn_games(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type == "private": await send_clean(message, "🎰 <b>ИГРЫ В ГРУППЕ</b>\n━━━━━━━━━━━━━━\n👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 В ГРУППУ", url=GROUP_URL)]]))
        else: await send_clean(message, "🎰 Игры:", reply_markup=games_menu())

    # ================= ГРУППА: ИНФО =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        msg = await message.reply(f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 <b>{fmt_num(get_balance(message.from_user.id))}</b>")
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "топ")
    async def group_top(message: Message):
        rows = get_top(10); txt = "🏆 <b>ТОП-10</b>\n━━━━━━━━━━━━━━\n\n"
        for i, r in enumerate(rows): txt += f"{['🥇','🥈','🥉'][i] if i<3 else f'<b>{i+1}.</b>'} {r[1] or 'user'} — <b>{fmt_num(r[2])}</b>\n"
        msg = await message.reply(txt); asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "лог")
    async def group_log(message: Message):
        chat_id = message.chat.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS group_logs (chat_id BIGINT, detail TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("SELECT detail FROM group_logs WHERE chat_id = %s ORDER BY time DESC LIMIT 10", (chat_id,))
            rows = c.fetchall()
        except: rows = []
        finally: c.close(); release_conn(conn)
        if not rows: msg = await message.reply("📜 <b>ИСТОРИЯ</b>\nВ этой группе еще не было игр.")
        else:
            nums = [row[0] for row in rows if row[0] != "Инициализация"]
            if not nums: msg = await message.reply("📜 <b>ИСТОРИЯ</b>\nПусто.")
            else: msg = await message.reply("📜 <b>ИСТОРИЯ ЧИСЕЛ</b>\n━━━━━━━━━━━━━━\n" + "  ".join(nums))
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
    async def group_games_rules(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        msg = await message.reply("🎮 <b>ВЫБЕРИ ИГРУ</b>\n━━━━━━━━━━━━━━\nНажми на кнопку ниже, чтобы узнать правила и команды 👇", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.callback_query(F.data.startswith("game_info_"))
    async def game_info_handler(call: CallbackQuery):
        game = call.data.replace("game_info_", "")
        
        # Обработка кнопки Закрыть
        if game == "close":
            await call.message.delete()
            return await call.answer("Меню закрыто.")
            
        info = {
            "roulette": "🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━\n• <code>к 100</code> / <code>ч 100</code> — Цвета (x1.95)\n• <code>з 100</code> — Зеро (x35)\n• <code>100 1-18</code> — Диапазон\n• <code>го</code> — Запустить",
            "mines": "💣 <b>МИНЫ</b>\n━━━━━━━━━━━━━━\n• <code>мины 100</code>\nОткрывай клетки, собирай кэш. Попадешь на мину — ставка сгорит!",
            "dice": "🎲 <b>КОСТИ</b>\n━━━━━━━━━━━━━━\n• <code>кости 100</code>\nВыигрыш, если выпадет 4, 5 или 6 (x1.95)",
            "slots": "🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n• <code>спин 100</code>\nШанс выигрыша 50% (x1.8)",
            "basket": "🏀 <b>БАСКЕТ</b>\n━━━━━━━━━━━━━━\n• <code>баскет 100</code>\nПопади в кольцо (x2)",
            "football": "⚽ <b>ФУТБОЛ</b>\n━━━━━━━━━━━━━━\n• <code>футбол 100</code>\nЗабей гол (x2)",
            "darts": "🎯 <b>ДАРТС</b>\n━━━━━━━━━━━━━━\n• <code>дартс 100</code>\nЯблочко (6) — x5. Попадание — x1.5",
            "bowling": "🎳 <b>БОУЛИНГ</b>\n━━━━━━━━━━━━━━\n• <code>боулинг 100</code>\nСтрайк (6) — x3. Сбил — x1.5",
            "coin": "🪙 <b>МОНЕТКА</b>\n━━━━━━━━━━━━━━\n• <code>монетка 100 орел</code>\nОрел/Решка x2. Ребро x10!",
            "duel": "⚔️ <b>ДУЭЛИ</b>\n━━━━━━━━━━━━━━\nОтветь на сообщение игрока:\n• <code>дуэль 100</code>"
        }
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="game_info_back"), InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        
        await call.message.edit_text(info.get(game, "Информация не найдена."), reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data == "game_info_back")
    async def game_info_back(call: CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        await call.message.edit_text("🎮 <b>ВЫБЕРИ ИГРУ</b>\n━━━━━━━━━━━━━━\nНажми на кнопку ниже, чтобы узнать правила и команды 👇", reply_markup=kb)
        await call.answer()

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"что нового", "обнова"}))
    async def cmd_whats_new(message: Message):
        msg = await message.reply("🚀 <b>ОБНОВЛЕНИЕ v37!</b>\n━━━━━━━━━━━━━━\n💣 Мины\n🪙 Монетка 3.0 (x10)\n⚔️ Дуэли\n🎁 Бонус\n🤝 Рефералка\n\n🔥 Тестируй!")
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "бонус")
    async def group_bonus(message: Message):
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,)); row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today: c.close(); release_conn(conn); return await message.reply("⏳ Ты уже брал сегодня.")
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        msg = await message.reply(f"🎁 <b>БОНУС</b>\n+5 000 Tokens!"); asyncio.create_task(delete_message_later(msg, 150))

    # ================= ДУЭЛИ 2.0 (С ПРИНЯТИЕМ) =================
    
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("дуэль "))
    async def play_duel(message: Message):
        if not message.reply_to_message: 
            return await message.reply("⚔️ <b>ДУЭЛЬ</b>\n━━━━━━━━━━━━━━\nЧтобы вызвать на дуэль, ответь на сообщение соперника и напиши <code>дуэль 100</code>.")
        
        challenger = message.from_user
        opponent = message.reply_to_message.from_user
        
        # Проверки
        if challenger.id == opponent.id: return await message.reply("❌ Нельзя вызвать самого себя!")
        if opponent.is_bot: return await message.reply("❌ С ботом нельзя!")
        
        parts = message.text.lower().split()
        if len(parts) != 2: return await message.reply("❌ Формат: <code>дуэль 100</code>")
        try: bet = int(parts[1])
        except: return
        
        if bet < 10: return await message.reply("❌ Мин. ставка 10.")
        if get_balance(challenger.id) < bet: return await message.reply("❌ У тебя недостаточно средств.")
        if get_balance(opponent.id) < bet: return await message.reply("❌ У соперника недостаточно средств.")
        
        # Списываем у вызывающего (замораживаем)
        set_balance(challenger.id, -bet)
        
        # Создаем кнопку для принятия
        # В callback_data передаем ID вызывающего, ID соперника и сумму
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ПРИНЯТЬ ДУЭЛЬ", callback_data=f"duel_accept_{challenger.id}_{opponent.id}_{bet}")],
            [InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{challenger.id}_{opponent.id}_{bet}")]
        ])
        
        txt = (
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Вызывающий: <b>@{challenger.username or challenger.first_name}</b>\n"
            f"🛡️ Соперник: <b>@{opponent.username or opponent.first_name}</b>\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b> Tokens\n"
            f"━━━━━━━━━━━━━━\n"
            f"<i>@{opponent.username or opponent.first_name}, жми на кнопку ниже, чтобы принять бой!</i>"
        )
        
        await message.reply(txt, reply_markup=kb)

    @dp.callback_query(F.data.startswith("duel_accept_"))
    async def duel_accept_handler(call: CallbackQuery):
        parts = call.data.split("_")
        challenger_id = int(parts[2])
        opponent_id = int(parts[3])
        bet = int(parts[4])
        
        # Проверяем, что на кнопку жмет именно тот, кого вызвали
        if call.from_user.id != opponent_id:
            return await call.answer("❌ Это не твой вызов! Жди своей очереди.", show_alert=True)
            
        if get_balance(opponent_id) < bet:
            return await call.answer("❌ У тебя недостаточно средств для принятия!", show_alert=True)
            
        # Списываем у соперника
        set_balance(opponent_id, -bet)
        
        # Удаляем кнопки, чтобы никто больше не нажал
        await call.message.edit_text(
            f"⚔️ <b>ДУЭЛЬ НАЧАЛАСЬ!</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔵 @{call.bot.get_chat(challenger_id).username or 'Игрок 1'}\n"
            f"🔴 @{call.from_user.username or 'Игрок 2'}\n"
            f"💰 Банк: <b>{fmt_num(bet * 2)}</b> Tokens\n\n"
            f"🎲 Бросаем кубики..."
        )
        await call.answer("Дуэль принята!")
        
        await asyncio.sleep(1.5)
        
        # Кидаем стикеры кубиков (настоящие)
        # Кидаем от лица бота
        dice1_msg = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
        await asyncio.sleep(0.5)
        dice2_msg = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
        
        # Ждем, пока кубики прокрутятся (примерно 3 секунды)
        await asyncio.sleep(3.5)
        
        val1 = dice1_msg.dice.value
        val2 = dice2_msg.dice.value
        
        # Если ничья, перебрасываем (упрощенно: победит тот, у кого больше, при равенстве переброс не делаем, просто возвращаем ставки)
        if val1 == val2:
            set_balance(challenger_id, bet)
            set_balance(opponent_id, bet)
            await call.message.reply(f"🤝 <b>НИЧЬЯ!</b>\nВыпало {val1} и {val2}.\nСтавки возвращены.")
            return
            
        if val1 > val2:
            winner_id, loser_id = challenger_id, opponent_id
            winner_name = call.bot.get_chat(challenger_id).username or "Игрок 1"
            w_dice, l_dice = val1, val2
        else:
            winner_id, loser_id = opponent_id, challenger_id
            winner_name = call.from_user.username or "Игрок 2"
            w_dice, l_dice = val2, val1
            
        # Выдаем выигрыш
        set_balance(winner_id, bet * 2)
        
        # Записываем в лог игры (если нужно)
        log_game(winner_id, winner_name, "дуэль", bet, bet * 2, str(w_dice))
        
        await call.message.reply(
            f"🏆 <b>ПОБЕДИТЕЛЬ ДУЭЛИ</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🥇 <b>@{winner_name}</b> (Выпало: {w_dice})\n"
            f"💔 Проигравший (Выпало: {l_dice})\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 Выигрыш: <b>+{fmt_num(bet * 2)}</b> Tokens"
        )

    @dp.callback_query(F.data.startswith("duel_decline_"))
    async def duel_decline_handler(call: CallbackQuery):
        parts = call.data.split("_")
        challenger_id = int(parts[2])
        opponent_id = int(parts[3])
        bet = int(parts[4])
        
        if call.from_user.id != opponent_id:
            return await call.answer("❌ Это не твой вызов!", show_alert=True)
            
        # Возвращаем деньги вызывающему
        set_balance(challenger_id, bet)
        
        await call.message.edit_text(
            f"❌ <b>ДУЭЛЬ ОТКЛОНЕНА</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Игрок @{call.from_user.username or call.from_user.first_name} отказался от боя.\n"
            f"💰 Ставка <b>{fmt_num(bet)}</b> возвращена вызывающему."
        )
        await call.answer("Ты отклонил дуэль.")

    # ================= РУЛЕТКА (УМНЫЙ ПАРСЕР) =================
    
    # 1. Ставки на цвет / чёт
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чёт|нечет)\s+\d+$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        bet_type = {"к":"red","ч":"black","з":"green","чёт":"even","нечет":"odd"}.get(parts[0])
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно средств или ставка < 1.")
        
        set_balance(uid, -bet)
        
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        
        async def auto_cancel():
            await asyncio.sleep(150) # 2.5 минуты
            if chat_id in active_bets and active_bets[chat_id]["bets"]:
                for b in active_bets[chat_id]["bets"]: set_balance(b["user_id"], b["bet"])
                m = await message.answer("⏰ <b>ВРЕМЯ ВЫШЛО!</b> Ставки отменены, токены возвращены.")
                asyncio.create_task(delete_message_later(m, 30))
                del active_bets[chat_id]
        active_bets[chat_id]["timer"] = asyncio.create_task(auto_cancel())
        
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(f"🎰 <b>СТАВКА ПРИНЯТА</b>\n👤 @{message.from_user.username or 'user'}\n🎯 {names[bet_type]}\n💰 {fmt_num(bet)}\n⚡️ Напиши <b>го</b> для запуска!")
        asyncio.create_task(delete_message_later(msg, 150))

    # 2. Умный парсер диапазонов (Собирает ВСЕ уникальные числа)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"^\d+\s+([0-9\-]+\s*)+$"))
    async def place_range_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        try: bet = int(parts[0])
        except ValueError: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно средств или ставка < 1.")
        
        # Собираем ВСЕ числа в один уникальный список
        bet_numbers = set()
        for p in parts[1:]:
            if "-" in p:
                try:
                    s, e = map(int, p.split("-"))
                    if 0 <= s <= e <= 36:
                        for num in range(s, e + 1):
                            bet_numbers.add(num)
                except: pass
            else:
                try:
                    n = int(p)
                    if 0 <= n <= 36:
                        bet_numbers.add(n)
                except: pass
                
        if not bet_numbers: return await message.reply("❌ Ошибка в формате диапазонов. Убедись, что числа от 0 до 36.")
        
        # Считаем коэффициент: (36 / кол-во чисел) * 0.95
        count = len(bet_numbers)
        mult = round((36 / count) * 0.95, 2)
        
        set_balance(uid, -bet)
        
        if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        
        # Сохраняем как список конкретных чисел
        active_bets[chat_id]["bets"].append({
            "user_id": uid, 
            "username": message.from_user.username or "user", 
            "type": "numbers", 
            "numbers": list(bet_numbers), 
            "bet": bet,
            "mult": mult
        })
        
        async def auto_cancel():
            await asyncio.sleep(150)
            if chat_id in active_bets and active_bets[chat_id]["bets"]:
                for b in active_bets[chat_id]["bets"]: set_balance(b["user_id"], b["bet"])
                m = await message.answer("⏰ <b>ВРЕМЯ ВЫШЛО!</b> Ставки отменены.")
                asyncio.create_task(delete_message_later(m, 30))
                del active_bets[chat_id]
        active_bets[chat_id]["timer"] = asyncio.create_task(auto_cancel())
        
        msg = await message.reply(
            f"🎰 <b>СТАВКА НА ЧИСЛА</b>\n"
            f"👤 @{message.from_user.username or 'user'}\n"
            f"🎯 Выбрано чисел: <b>{count}</b> (шанс ~{int((count/37)*100)}%)\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b> (x{mult})\n"
            f"⚡️ Напиши <b>го</b> для запуска!"
        )
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок для запуска! Сначала сделай ставку.")
        
        if active_bets[chat_id].get("timer"): active_bets[chat_id]["timer"].cancel()
        
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        
        try: 
            msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n━━━━━━━━━━━━━━\n💰 Банк: <b>{fmt_num(total)}</b> Tokens\n⏳ Крутится...")
        except: 
            msg = await message.reply(f"🎡 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n━━━━━━━━━━━━━━\n💰 Банк: <b>{fmt_num(total)}</b> Tokens\n⏳ Крутится...")
            
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
                if res in b["numbers"]:
                    w = int(b["bet"] * b["mult"])
            if w > 0: 
                set_balance(b["user_id"], w); win.append(f"🏆 @{b['username']} — <b>+{fmt_num(w)}</b>")
            else: 
                lose.append(f"💔 @{b['username']}")
                
        txt = f"🎡 <b>РЕЗУЛЬТАТ РУЛЕТКИ</b>\n━━━━━━━━━━━━━━\n🎯 Выпало число: <b>{color} {res}</b>\n━━━━━━━━━━━━━━\n\n"
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        
        # Логируем (проверка на существование таблицы)
        conn = get_conn(); c = conn.cursor()
        try: 
            c.execute("CREATE TABLE IF NOT EXISTS group_logs (chat_id BIGINT, detail TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, f"{color}{res}"))
        except: pass
        finally: conn.commit(); c.close(); release_conn(conn)
        
        del active_bets[chat_id]

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

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>ПРОБЛЕМА С TOKENS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
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
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🎮 <b>ОШИБКА В ИГРЕ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Опиши проблему, и мы починим это как можно скорее!\n\n"
            "Пожалуйста, укажи:\n"
            "1️⃣ <b>В какой игре</b> произошла ошибка.\n"
            "2️⃣ <b>Что ты делал</b> (какую команду вводил).\n"
            "3️⃣ <b>Что пошло не так</b> (списалось дважды, не выдало выигрыш).\n\n"
            "📸 <b>Пришли скриншот</b> — это ускорит починку в 2 раза!\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы всё проверим по логам. 🤝"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>ВОПРОС ПО ОПЛАТЕ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Все покупки в боте проходят через <b>Telegram Stars ⭐</b> (внутренняя валюта Telegram).\n\n"
            "<b>Как это работает:</b>\n"
            "• Ты выбираешь пакет -> бот присылает счет -> ты подтверждаешь оплату.\n"
            "• Токены зачисляются автоматически в течение 10 секунд.\n\n"
            "<b>Если что-то пошло не так:</b>\n"
            "• Возврат средств возможен только через поддержку Telegram (в настройках платежей).\n"
            "• Если токены не пришли — см. пункт <b>«Tokens не пришли»</b>.\n\n"
            f"📩 <b>Если остались вопросы:</b> {SUPPORT_USERNAME} ✍️"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🚫 <b>БАН ИЛИ МУТ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Если ты считаешь, что наказание было ошибочным, мы разберёмся.\n\n"
            "Пришли нам:\n"
            "1️⃣ Твой <b>@username</b> (и ID, если знаешь).\n"
            "2️⃣ <b>Причину блокировки</b> (если она была указана).\n"
            "3️⃣ <b>Примерное время</b>, когда это случилось.\n\n"
            "⚠️ <b>Важно:</b> Если ты попал в бан из-за непогашенного кредита, сначала верни долг.\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы проверим логи и снимем бан, если он был выдан по ошибке. 🤝"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🐞 <b>НАШЁЛ БАГ?</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Спасибо, что помогаешь делать бота лучше! За реальный баг мы даем бонус Tokens.\n\n"
            "Опиши баг максимально подробно:\n"
            "1️⃣ <b>Что ты делал</b> (по шагам).\n"
            "2️⃣ <b>Что ожидал увидеть</b>.\n"
            "3️⃣ <b>Что случилось на самом деле</b>.\n\n"
            "📸 <b>Скриншот или текст ошибки</b> — обязательно!\n\n"
            f"📩 <b>Отправь это сюда:</b> {SUPPORT_USERNAME}\n"
            "За подтверждённый баг — бонус Tokens! 🎁"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message, state: FSMContext):
        await state.clear()
        # ИСПРАВЛЕНА ОШИБКА: добавлена f-строка
        txt = (
            f"📜 <b>ПРАВИЛА {BOT_NAME.upper()}</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "1️⃣ Бот создан исключительно в развлекательных целях. <b>Реальных ставок нет.</b>\n"
            "2️⃣ Виртуальные Tokens не подлежат выводу или обмену на реальные деньги.\n"
            "3️⃣ Игра разрешена только пользователям <b>18+</b>.\n"
            "4️⃣ <b>Запрещены:</b> мультиаккаунтинг, использование багов, мошенничество, передача аккаунта.\n"
            "5️⃣ Донат — это добровольная поддержка проекта, а не инвестиция.\n\n"
            "⚠️ <b>Нарушение правил ведет к бану без предупреждения.</b>\n\n"
            "Играй ответственно! 🎲"
        )
        await send_clean(message, txt, reply_markup=support_menu())

        # ✍️ СВОЙ ВОПРОС (Обработчик кнопки)
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

    # Обработка самого вопроса (когда игрок его напишет)
    @dp.message(F.text == "⬅️ Назад") # Чтобы можно было отменить, если передумал
    async def cancel_custom_q(message: Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state == "waiting_custom_support":
            await state.clear()
            return await send_clean(message, "❌ Отменено.", reply_markup=main_menu())
        # Если это не отмена вопроса, пропускаем дальше (для других кнопок Назад)
        await state.clear()
        await send_clean(message, "🏠 <b>ГЛАВНОЕ МЕНЮ</b>", reply_markup=main_menu())

    @dp.message(F.text != "⬅️ Назад", lambda msg: msg.from_user.id != ADMIN_ID) # Ловим любой текст от игрока
    async def catch_custom_q(message: Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state == "waiting_custom_support":
            await state.clear()
            user = message.from_user
            
            # Отправляем сообщение тебе (Админу)
            admin_text = (
                f"📩 <b>НОВЫЙ ВОПРОС В ПОДДЕРЖКУ</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"👤 От: @{user.username or user.first_name}\n"
                f"🆔 ID: <code>{user.id}</code>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💬 <b>Текст:</b>\n{message.text}"
            )
            try:
                await message.bot.send_message(ADMIN_ID, admin_text)
                await send_clean(message, 
                    "✅ <b>ВОПРОС ОТПРАВЛЕН!</b>\n"
                    "━━━━━━━━━━━━━━\n"
                    "Администрация получила твое сообщение и скоро ответит.", 
                    reply_markup=main_menu()
                )
            except Exception:
                await send_clean(message, "❌ Ошибка отправки. Попробуй позже.", reply_markup=main_menu())

    # ================= ЗАПУСК =================
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")