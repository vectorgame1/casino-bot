# bot.py — FINAL v35 (Красивый UI, фикс рулетки, банк с фото)
import asyncio, logging, os, random
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

active_bets, admin_replies = {}, {}
RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED else "⚫"

async def start_web_server():
    async def health(request): return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', health); app.router.add_get('/health', health)
    runner = web.AppRunner(app); await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")

async def main():
    asyncio.create_task(start_web_server())
    init_pool(); init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ================= КНОПКА НАЗАД =================
    @dp.message(F.text == "⬅️ Назад")
    async def btn_back(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "🏠 <b>ГЛАВНОЕ МЕНЮ</b>\n━━━━━━━━━━━━━━\nВыбери нужный раздел 👇", reply_markup=main_menu())

    # ================= ИГРОК (ЛС) =================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or message.from_user.first_name)
        if is_banned(user_id): return await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>\n━━━━━━━━━━━━━━\nТы забанен в этом боте.")
        
        is_new = check_and_give_bonus(user_id, START_BONUS)
        
        if message.chat.type != "private":
            return await message.reply(f"👋 Привет! Твой профиль и игры доступны в ЛС: @{bot.username}")
            
        if user_id == ADMIN_ID:
            return await send_clean(message, "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n━━━━━━━━━━━━━━\nДобро пожаловать, Создатель 👇", reply_markup=admin_panel_kb())
            
        bonus = f"🎁 <b>Бонус новичка:</b> +{fmt_num(START_BONUS)} Tokens\n\n" if is_new else ""
        txt = (
            f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n"
            f"{bonus}"
            f"✨ Здесь тебя ждут лучшие игры, ставки и джекпоты.\n\n"
            f"👇 Выбери действие:"
        )
        try:
            await message.answer_photo(photo=FSInputFile("welcome.jpg"), caption=txt, reply_markup=main_menu())
        except Exception:
            await message.answer(txt, reply_markup=main_menu())

    # ================= ГРУППА =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        bal = get_balance(message.from_user.id)
        await message.reply(
            f"💳 <b>БАЛАНС</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Игрок: @{message.from_user.username or 'user'}\n"
            f"💰 На счету: <b>{fmt_num(bal)}</b> Tokens"
        )

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "топ")
    async def group_top(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ЗАЛ СЛАВЫ (ТОП-10)</b>\n━━━━━━━━━━━━━━\n\n"
        for i, r in enumerate(rows): 
            medal = ['🥇','🥈','🥉'][i] if i<3 else f"<b>{i+1}.</b>"
            txt += f"{medal} {r[1] or 'user'} — <b>{fmt_num(r[2])}</b>\n"
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "лог")
    async def group_log(message: Message):
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT detail FROM game_log WHERE game = 'рулетка' ORDER BY id DESC LIMIT 10")
        rows = c.fetchall(); c.close(); release_conn(conn)
        if not rows: return await message.reply("📜 История пуста.")
        txt = "📜 <b>ИСТОРИЯ РУЛЕТКИ</b>\n━━━━━━━━━━━━━━\nПоследние числа:\n\n" + "  ".join([row[0] for row in rows])
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
    async def group_games_rules(message: Message):
        txt = (
            "🎮 <b>НАШИ ИГРЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🎡 <b>РУЛЕТКА</b>\n"
            "• <code>к 100</code> — Красное (x1.95)\n"
            "• <code>ч 100</code> — Чёрное (x1.95)\n"
            "• <code>з 100</code> — Зеро (x35)\n"
            "• <code>го</code> — Запустить\n\n"
            "🎲 <b>КОСТИ</b>\n"
            "• <code>кости 100</code> — Выигрыш 4, 5, 6 (x1.95)\n\n"
            "🎰 <b>СЛОТЫ</b>\n"
            "• <code>спин 100</code> — Шанс 50% (x1.8)\n\n"
            "🏀 <b>БАСКЕТ</b>\n"
            "• <code>баскет 100</code> — Попади в кольцо (x2)\n\n"
            "⚽ <b>ФУТБОЛ</b>\n"
            "• <code>футбол 100</code> — Забей гол (x2)\n\n"
            "🎯 <b>ДАРТС</b>\n"
            "• <code>дартс 100</code> — Яблочко (x5), Попадание (x1.5)\n\n"
            "🎳 <b>БОУЛИНГ</b>\n"
            "• <code>боулинг 100</code> — Страйк (x3), Сбил (x1.5)\n\n"
            "🪙 <b>МОНЕТКА</b>\n"
            "• <code>монетка 100</code> — Орел/Решка (x2)\n\n"
            "━━━━━━━━━━━━━━\n"
            "📊 <b>Общие:</b> <code>ставки</code>, <code>отмена</code>, <code>б</code>"
        )
        await message.reply(txt)

    # ================= КОМАНДЫ В ЛС =================
    @dp.message(F.chat.type == "private", F.text.lower().in_({"баланс", "б"}))
    @dp.message(F.text == "💰 Баланс")
    async def cmd_bal(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        await send_clean(message, 
            f"💳 <b>ТВОЙ БАЛАНС</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 В кошельке: <b>{fmt_num(bal)}</b> Tokens", 
            reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"профиль", "я"}))
    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = (
            f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Имя: <b>{message.from_user.first_name}</b>\n"
            f"🎖 Ранг: <b>{get_rank_name(lvl)}</b>\n"
            f"📊 Опыт: {xp} XP\n"
            f"{make_xp_bar(xp)}\n"
            f"💰 Баланс: <b>{fmt_num(get_balance(uid))}</b> Tokens"
        )
        await send_clean(message, txt, reply_markup=main_menu())

    # 🏦 БАНК
    @dp.message(F.chat.type == "private", F.text.lower().in_({"банк"}))
    @dp.message(F.text == "🏦 Банк")
    async def bank_menu(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (message.from_user.id,))
            row = c.fetchone()
            bank = row[0] if row and row[0] is not None else 0
        except Exception:
            bank = 0
        finally:
            c.close(); release_conn(conn)
        
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📥 Положить"), KeyboardButton(text="📤 Снять")],
            [KeyboardButton(text="⬅️ Назад")]
        ], resize_keyboard=True)
        
        txt = (
            f"🏦 <b>БАНКОВСКОЕ ХРАНИЛИЩЕ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💎 На руках: <b>{fmt_num(bal)}</b>\n"
            f"🏦 В сейфе: <b>{fmt_num(bank)}</b>\n\n"
            f"📈 <b>Процент:</b> 5% в день\n\n"
            f"👇 Выбери действие:"
        )
        try:
            await message.answer_photo(photo=FSInputFile("bank.jpg"), caption=txt, reply_markup=kb)
        except Exception:
            await send_clean(message, txt, reply_markup=kb)

    @dp.message(F.text == "📥 Положить")
    async def bank_deposit_start(message: Message, state: FSMContext):
        await send_clean(message, "💰 <b>ВКЛАД</b>\n━━━━━━━━━━━━━━\nВведи сумму Tokens для вклада:")
        await state.set_state(BotStates.waiting_bank_amount)
        await state.update_data(action="deposit")

    @dp.message(F.text == "📤 Снять")
    async def bank_withdraw_start(message: Message, state: FSMContext):
        await send_clean(message, "💸 <b>СНЯТИЕ</b>\n━━━━━━━━━━━━━━\nВведи сумму Tokens для снятия:")
        await state.set_state(BotStates.waiting_bank_amount)
        await state.update_data(action="withdraw")

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        if message.text == "⬅️ Назад":
            await state.clear()
            return await bank_menu(message, state)
            
        data = await state.get_data()
        try: amount = int(message.text)
        except ValueError: return await send_clean(message, "❌ Ошибка: Введи число.")
        
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        
        if data["action"] == "deposit":
            bal = get_balance(uid)
            if bal < amount: 
                c.close(); release_conn(conn)
                return await send_clean(message, "❌ Недостаточно средств на балансе.")
            set_balance(uid, -amount)
            c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid))
            conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ <b>УСПЕШНО</b>\n━━━━━━━━━━━━━━\nТы положил <b>{fmt_num(amount)}</b> в банк.")
        else:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            bank = row[0] if row else 0
            if bank < amount:
                c.close(); release_conn(conn)
                return await send_clean(message, "❌ Недостаточно средств в банке.")
            c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid))
            set_balance(uid, amount)
            conn.commit(); c.close(); release_conn(conn)
            await send_clean(message, f"✅ <b>УСПЕШНО</b>\n━━━━━━━━━━━━━━\nТы снял <b>{fmt_num(amount)}</b> из банка.")
            
        await state.clear()
        await bank_menu(message, state)

    @dp.message(F.chat.type == "private", F.text.lower().in_({"донат", "магазин"}))
    @dp.message(F.text == "🏪 Донат")
    async def cmd_don(message: Message, state: FSMContext):
        await state.clear()
        rate = get_rate("stars_rate", STARS_RATE)
        txt = f"💳 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n━━━━━━━━━━━━━━\n💱 Курс: 1 ⭐ = {fmt_num(rate)} Tokens\n\n👇 Введи количество Stars от 1 до 10000:"
        
        try:
            await message.answer_photo(photo=FSInputFile("powertext_ru_1792346951926.png"), caption=txt, reply_markup=donate_menu())
        except Exception:
            await send_clean(message, txt, reply_markup=donate_menu())
            
        await state.set_state(BotStates.waiting_custom_stars)

    @dp.message(BotStates.waiting_custom_stars)
    async def custom_sum_process(message: Message, state: FSMContext):
        if message.text == "⬅️ Назад":
            await state.clear()
            return await send_clean(message, "🏠 <b>ГЛАВНОЕ МЕНЮ</b>", reply_markup=main_menu())
            
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000: return await send_clean(message, "❌ От 1 до 10000.")
            rate = get_rate("stars_rate", STARS_RATE)
            tokens = stars * rate
            await message.answer_invoice(title=f"{tokens:,} Tokens", description=f"Покупка {tokens:,} Tokens", payload=f"buy_{stars}_{tokens}", provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{tokens:,} Tokens", amount=stars)])
            await state.clear()
        except ValueError:
            await send_clean(message, "❌ Введи число (например, 100).")

    @dp.message(F.text == "🎰 Игры")
    async def btn_games(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type == "private":
            await send_clean(message, "🎰 <b>ИГРЫ В ГРУППЕ</b>\n━━━━━━━━━━━━━━\nЖми кнопку ниже, чтобы перейти 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 В ГРУППУ", url=GROUP_URL)]]))
        else: await send_clean(message, "🎰 Игры:", reply_markup=games_menu())

    # ================= ИГРЫ =================
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_condition, win_mult, lose_text, win_text):
        uid = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except ValueError: return
        
        if bet < 1 or get_balance(uid) < bet: 
            return await message.reply(f"❌ <b>ОШИБКА</b>\n━━━━━━━━━━━━━━\nНедостаточно средств или ставка < 1.")
        
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji=emoji)
        await asyncio.sleep(2.5)
        result = sent.dice.value
        
        if win_condition(result):
            win_amount = int(bet * win_mult)
            set_balance(uid, win_amount)
            log_game(uid, username, game_name, bet, win_amount, str(result))
            txt = win_text.format(result=result, win=fmt_num(win_amount), bet=fmt_num(bet))
        else:
            log_game(uid, username, game_name, bet, 0, str(result))
            txt = lose_text.format(result=result, win=fmt_num(0), bet=fmt_num(bet))
            
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "баскетбол ")))
    async def play_basket(message: Message):
        await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, 
            "🏀 <b>БАСКЕТ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n😢 Мимо. Потеряно: <b>-{bet}</b>", 
            "🏀 <b>БАСКЕТ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n🎉 Попал! Выигрыш: <b>+{win}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "фут ")))
    async def play_football(message: Message):
        await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, 
            "⚽ <b>ФУТБОЛ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n😢 Мимо. Потеряно: <b>-{bet}</b>", 
            "⚽ <b>ФУТБОЛ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n🎉 Гол! Выигрыш: <b>+{win}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "дарт ")))
    async def play_darts(message: Message):
        uid = message.from_user.id; username = message.from_user.username or "user"
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji="🎯")
        await asyncio.sleep(2.5)
        res = sent.dice.value
        
        if res == 6:
            win = int(bet * 5); set_balance(uid, win); log_game(uid, username, "дартс", bet, win, str(res))
            await message.reply(f"🎯 <b>ДАРТС</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n🎉 В ЯБЛОЧКО! Выигрыш: <b>+{fmt_num(win)}</b> (x5)")
        elif res >= 3:
            win = int(bet * 1.5); set_balance(uid, win); log_game(uid, username, "дартс", bet, win, str(res))
            await message.reply(f"🎯 <b>ДАРТС</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n🎉 Попал! Выигрыш: <b>+{fmt_num(win)}</b> (x1.5)")
        else:
            log_game(uid, username, "дартс", bet, 0, str(res))
            await message.reply(f"🎯 <b>ДАРТС</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n😢 Мимо. Потеряно: <b>-{fmt_num(bet)}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("боулинг ", "боул ")))
    async def play_bowling(message: Message):
        uid = message.from_user.id; username = message.from_user.username or "user"
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji="🎳")
        await asyncio.sleep(2.5)
        res = sent.dice.value
        
        if res == 6:
            win = int(bet * 3); set_balance(uid, win); log_game(uid, username, "боулинг", bet, win, str(res))
            await message.reply(f"🎳 <b>БОУЛИНГ</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n🎉 СТРАЙК! Выигрыш: <b>+{fmt_num(win)}</b> (x3)")
        elif res >= 4:
            win = int(bet * 1.5); set_balance(uid, win); log_game(uid, username, "боулинг", bet, win, str(res))
            await message.reply(f"🎳 <b>БОУЛИНГ</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n🎉 Сбил! Выигрыш: <b>+{fmt_num(win)}</b> (x1.5)")
        else:
            log_game(uid, username, "боулинг", bet, 0, str(res))
            await message.reply(f"🎳 <b>БОУЛИНГ</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n😢 Мимо. Потеряно: <b>-{fmt_num(bet)}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message):
        await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, 
            "🎲 <b>КОСТИ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n😢 Проигрыш. Потеряно: <b>-{bet}</b>", 
            "🎲 <b>КОСТИ</b>\n━━━━━━━━━━━━━━\nВыпало: {result}\n🎉 ПОБЕДА! Выигрыш: <b>+{win}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("спин ", "слот ")))
    async def play_slots(message: Message):
        uid = message.from_user.id; username = message.from_user.username or "user"
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji="🎰")
        await asyncio.sleep(2.5)
        res = sent.dice.value
        
        if res >= 32:
            win = int(bet * 1.8); set_balance(uid, win); log_game(uid, username, "слоты", bet, win, str(res))
            await message.reply(f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n🎉 Выигрыш! <b>+{fmt_num(win)}</b> (x1.8)")
        elif res >= 10:
            win = int(bet * 1.2); set_balance(uid, win); log_game(uid, username, "слоты", bet, win, str(res))
            await message.reply(f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n🎉 Маленький выигрыш! <b>+{fmt_num(win)}</b> (x1.2)")
        else:
            log_game(uid, username, "слоты", bet, 0, str(res))
            await message.reply(f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━\n😢 Проигрыш. <b>-{fmt_num(bet)}</b>")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("монетка ", "монета ")))
    async def play_coin(message: Message):
        uid = message.from_user.id; username = message.from_user.username or "user"
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        set_balance(uid, -bet)
        res = random.choice(["Орел 🦅", "Решка 🪙"])
        await asyncio.sleep(1)
        
        if random.random() < 0.5:
            win = int(bet * 2)
            set_balance(uid, win); log_game(uid, username, "монетка", bet, win, res)
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n🎉 Победа! Выигрыш: <b>+{fmt_num(win)}</b> (x2)")
        else:
            log_game(uid, username, "монетка", bet, 0, res)
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n━━━━━━━━━━━━━━\nВыпало: {res}\n😢 Проигрыш. Потеряно: <b>-{fmt_num(bet)}</b>")

    # ================= РУЛЕТКА =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("к ", "ч ", "з ", "чёт ", "нечет ")))
    async def place_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        bet_type = {"к":"red","ч":"black","з":"green","чёт":"even","нечет":"odd"}.get(parts[0])
        if not bet_type: return
        try: bet = int(parts[1])
        except: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        set_balance(uid, -bet)
        active_bets.setdefault(chat_id, {"bets": []})["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        await message.reply(
            f"🎰 <b>СТАВКА ПРИНЯТА</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Игрок: <b>@{message.from_user.username or 'user'}</b>\n"
            f"🎯 Выбор: <b>{names[bet_type]}</b>\n"
            f"💰 Сумма: <b>{fmt_num(bet)}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"⚡️ Напиши <b>го</b> для запуска!"
        )

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"^\d+.*-.*"))
    async def place_range_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        try: bet = int(parts[0])
        except ValueError: return
        if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 1.")
        
        ranges = []
        for p in parts[1:]:
            if "-" in p:
                try:
                    start, end = map(int, p.split("-"))
                    if 0 <= start <= end <= 36: ranges.append((start, end))
                except: pass
        if not ranges: return
        
        set_balance(uid, -bet)
        active_bets.setdefault(chat_id, {"bets": []})["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": "range", "ranges": ranges, "bet": bet})
        
        rng_str = ", ".join([f"{s}-{e}" for s, e in ranges])
        await message.reply(
            f"🎰 <b>СТАВКА НА ДИАПАЗОН</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Игрок: <b>@{message.from_user.username or 'user'}</b>\n"
            f"🎯 Сектор: <b>{rng_str}</b>\n"
            f"💰 Сумма: <b>{fmt_num(bet)}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"⚡️ Напиши <b>го</b> для запуска!"
        )

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "ставки")
    async def show_bets(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("📊 Нет активных ставок.")
        
        txt = "📊 <b>АКТИВНЫЕ СТАВКИ</b>\n━━━━━━━━━━━━━━\n"
        total = 0
        for b in active_bets[chat_id]["bets"]:
            txt += f"• @{b['username']}: <b>{fmt_num(b['bet'])}</b>\n"
            total += b["bet"]
        txt += f"━━━━━━━━━━━━━━\n💰 <b>Общий банк: {fmt_num(total)}</b>"
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "отмена")
    async def cancel_bets(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
        if chat_id in active_bets:
            my = [b for b in active_bets[chat_id]["bets"] if b["user_id"]==uid]
            if my:
                set_balance(uid, sum(b["bet"] for b in my))
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"]!=uid]
                await message.reply(f"❌ <b>ОТМЕНЕНО</b>\n━━━━━━━━━━━━━━\nСтавки на <b>{fmt_num(sum(b['bet'] for b in my))}</b> возвращены на баланс.")
                return
        await message.reply("📊 У тебя нет активных ставок.")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: 
            return await message.reply("❌ Нет ставок для запуска! Сначала сделай ставку.")
        
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        
        try: 
            msg = await message.reply_animation(
                FSInputFile("roulette.gif"), 
                caption=f"🎡 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n━━━━━━━━━━━━━━\n💰 Банк: <b>{fmt_num(total)}</b> Tokens\n⏳ Крутится..."
            )
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
            elif b["type"]=="range":
                for (start, end) in b["ranges"]:
                    if start <= res <= end:
                        count = end - start + 1
                        mult = round(36 / count * 0.95, 2)
                        w = int(b["bet"] * mult)
                        break
            if w > 0: 
                set_balance(b["user_id"], w)
                win.append(f"🏆 @{b['username']} — <b>+{fmt_num(w)}</b>")
            else: 
                lose.append(f"💔 @{b['username']} — Проигрыш")
                
        txt = (
            f"🎡 <b>РЕЗУЛЬТАТ РУЛЕТКИ</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 Выпало число: <b>{color} {res}</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
        )
        if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
        
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        
        await asyncio.sleep(30)
        try: await msg.delete()
        except: pass
        
        del active_bets[chat_id]

    # ================= ОПЛАТА =================
    @dp.pre_checkout_query()
    async def pre_check(query: PreCheckoutQuery): await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_"):
            _, stars, amount = payload.split("_"); set_balance(message.from_user.id, int(amount))
            await message.answer(f"✅ <b>ОПЛАТА УСПЕШНА</b>\n━━━━━━━━━━━━━━\nЗачислено <b>{fmt_num(int(amount))}</b> Tokens.")

    # ================= АДМИНКА =================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━\nВыбери раздел 👇", reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Скан игрока")],[KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],[KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n━━━━━━━━━━━━━━", reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "🔍 Скан игрока")
    async def adm_scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🔍 <b>СКАН</b>\n━━━━━━━━━━━━━━\nВведи @username или ID игрока:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="scan")

    @dp.message(F.text == "💰 Выдать баланс")
    async def adm_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 <b>ВЫДАЧА</b>\n━━━━━━━━━━━━━━\nВведи @username (или ID) и сумму через пробел:")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать баланс")
    async def adm_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 <b>СПИСАНИЕ</b>\n━━━━━━━━━━━━━━\nВведи @username (или ID) и сумму через пробел:")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="take")

    @dp.message(BotStates.waiting_amount)
    async def adm_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); parts = message.text.split()
        if len(parts) != 2: return await send_clean(message, "❌ Формат: @user сумма")
        target = parts[0].replace("@", "")
        if target.isdigit(): uid = int(target)
        else: uid = get_user_id_by_username(target)
        if not uid: return await send_clean(message, "❌ Игрок не найден.")
        try: amount = int(parts[1])
        except: return await send_clean(message, "❌ Введи корректное число.")
        set_balance(uid, amount if data["action"]=="give" else -amount)
        await send_clean(message, f"✅ {'Выдано' if data['action']=='give' else 'Списано'} <b>{fmt_num(amount)}</b> Tokens.")
        await state.clear()

    @dp.message(F.text == "🚫 Забанить")
    async def adm_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🚫 <b>БАН</b>\n━━━━━━━━━━━━━━\nВведи @username (или ID):")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="ban")

    @dp.message(F.text == "✅ Разбанить")
    async def adm_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "✅ <b>РАЗБАН</b>\n━━━━━━━━━━━━━━\nВведи @username (или ID):")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="unban")

    @dp.message(BotStates.waiting_scan)
    async def adm_scan(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); target = message.text.replace("@", "").strip()
        if target.isdigit(): uid = int(target)
        else: uid = get_user_id_by_username(target)
        if not uid:
            await state.clear()
            return await send_clean(message, "❌ Игрок не найден.")
            
        if data.get("action")=="ban": 
            set_banned(uid, True)
            await send_clean(message, "🚫 Игрок забанен.")
        elif data.get("action")=="unban": 
            set_banned(uid, False)
            await send_clean(message, "✅ Игрок разбанен.")
        elif data.get("action")=="scan":
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT username, balance, bank, xp, banned FROM users WHERE user_id=%s",(uid,))
            row=c.fetchone()
            c.execute("SELECT game, bet, win, time FROM game_log WHERE user_id=%s ORDER BY id DESC LIMIT 5", (uid,))
            recent_games = c.fetchall()
            c.close(); release_conn(conn)
            if row:
                uname, bal, bank, xp, banned = row
                status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
                txt = f"🕵️ <b>ДОСЬЕ ИГРОКА</b>\n━━━━━━━━━━━━━━\n\n👤 @{uname}\n🆔 <code>{uid}</code>\n📊 Статус: {status}\n\n💎 Баланс: <b>{fmt_num(bal)}</b>\n🏦 Банк: <b>{fmt_num(bank)}</b>\n⭐ XP: {xp}\n\n🎮 <b>ПОСЛЕДНИЕ ИГРЫ:</b>\n"
                if recent_games:
                    for g, bet, win, time in recent_games:
                        txt += f"• {g} | Ставка: {fmt_num(bet)} | Выигрыш: {fmt_num(win)}\n"
                else:
                    txt += "Нет истории игр.\n"
                await send_clean(message, txt)
        await state.clear()

    # ═══ РАССЫЛКА ═══
    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📢 Всем игрокам")],[KeyboardButton(text="🎯 По @username")],[KeyboardButton(text="🆔 По ID")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "📢 <b>РАССЫЛКА</b>\n━━━━━━━━━━━━━━\nКому отправить?", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📢 <b>ВСЕМ</b>\n━━━━━━━━━━━━━━\nНапиши текст для всех:")
        await state.set_state(BotStates.waiting_broadcast_text)
        await state.update_data(target="all")

    @dp.message(F.text == "🎯 По @username")
    async def broadcast_user_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🎯 <b>ЛИЧНО</b>\n━━━━━━━━━━━━━━\nВведи @username игрока:")
        await state.set_state(BotStates.waiting_broadcast_target)
        await state.update_data(mode="user")

    @dp.message(F.text == "🆔 По ID")
    async def broadcast_id_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🆔 <b>ЛИЧНО ПО ID</b>\n━━━━━━━━━━━━━━\nВведи ID игрока:")
        await state.set_state(BotStates.waiting_broadcast_target)
        await state.update_data(mode="id")

    @dp.message(BotStates.waiting_broadcast_target)
    async def broadcast_target_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); target = message.text.strip()
        
        if data["mode"] == "user":
            uid = get_user_id_by_username(target.replace("@", ""))
        else:
            try: uid = int(target)
            except: uid = None

        if not uid:
            await state.clear()
            return await send_clean(message, "❌ Игрок не найден.")

        await state.update_data(target=uid)
        await send_clean(message, "✍️ Теперь напиши текст сообщения:")
        await state.set_state(BotStates.waiting_broadcast_text)

    @dp.message(BotStates.waiting_broadcast_text)
    async def broadcast_text_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = data.get("target")
        
        if target == "all":
            conn = get_conn(); c = conn.cursor(); c.execute("SELECT user_id FROM users"); users = c.fetchall(); c.close(); release_conn(conn)
            sent = 0
            await send_clean(message, f"⏳ Рассылка на {len(users)}...")
            for (uid,) in users:
                try: await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML"); sent += 1; await asyncio.sleep(0.05)
                except: pass
            await send_clean(message, f"✅ Отправлено: {sent}")
        else:
            try:
                await message.bot.send_message(target, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML")
                await send_clean(message, "✅ Отправлено игроку!")
            except Exception as e:
                await send_clean(message, f"❌ Ошибка: {e}")
        await state.clear()

    # ═══ РАЗДЕЛ: ИГРЫ (АДМИН) ═══
    @dp.message(F.text == "🎮 Игры")
    async def admin_games_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM game_log")
        total_games = c.fetchone()[0]
        c.close(); release_conn(conn)
        txt = f"🎮 <b>ИГРЫ</b>\n━━━━━━━━━━━━━━\n\n📊 Всего игр: <b>{total_games}</b>\n✅ Все системы работают."
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
        total_users, total_balance = c.fetchone()
        c.close(); release_conn(conn)
        txt = f"💰 <b>ЭКОНОМИКА</b>\n━━━━━━━━━━━━━━\n\n👥 Игроков: <b>{total_users}</b>\n💎 В обороте: <b>{fmt_num(total_balance)}</b> Tokens\n\n💱 Курс: 1 ⭐ = {STARS_RATE} Tokens"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "🛒 Контент")
    async def admin_content_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = f"🛒 <b>КОНТЕНТ</b>\n━━━━━━━━━━━━━━\n📦 Управление магазином в разработке."
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE banned = FALSE")
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
        banned = c.fetchone()[0]
        c.close(); release_conn(conn)
        txt = f"📊 <b>МОНИТОРИНГ</b>\n━━━━━━━━━━━━━━\n\n🟢 В сети: <b>{active}</b>\n🔴 Забанено: <b>{banned}</b>\n\n👑 Админ: @{message.from_user.username}"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    @dp.message(F.text == "📋 Все команды")
    async def admin_all_commands(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = "📋 <b>КОМАНДЫ</b>\n━━━━━━━━━━━━━━\n\n/admin — меню\n/give @user сумма\n/ban @user\n/unban @user"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ================= ПОДДЕРЖКА =================
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🆘 Поддержка: @{bot.username}")
        try: await message.answer_photo(FSInputFile("support.jpg"), caption="🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n━━━━━━━━━━━━━━\nВыбери тему обращения 👇", reply_markup=support_menu())
        except Exception: await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\n━━━━━━━━━━━━━━\nВыбери тему 👇", reply_markup=support_menu())

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>ПРОБЛЕМА С TOKENS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "1️⃣ <b>Проверь оплату.</b> Настройки -> Мои подарки.\n"
            "2️⃣ <b>Подожди 5–10 минут.</b> Иногда Stars идут с задержкой.\n"
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
            "📜 <b>ПРАВИЛА {BOT_NAME}</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "1️⃣ Бот создан в развлекательных целях. Реальных ставок нет.\n"
            "2️⃣ Tokens не выводятся на реальные деньги.\n"
            "3️⃣ Игра разрешена только 18+.\n"
            "4️⃣ Запрещены мультиаккаунты и багоюз.\n"
            "5️⃣ Донат — добровольная поддержка.\n\n"
            "⚠️ <b>Нарушение = бан без предупреждения.</b>"
        )
        await send_clean(message, txt, reply_markup=support_menu())

    # ================= ЗАПУСК =================
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")