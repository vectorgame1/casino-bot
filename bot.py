# bot.py — ФИНАЛЬНЫЙ МОНОЛИТ (v24)
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

    # ================= ИГРОК =================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or message.from_user.first_name)
        if is_banned(user_id): return await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>")
        
        is_new = check_and_give_bonus(user_id, START_BONUS)
        
        if message.chat.type != "private":
            return await message.reply(f"👋 Привет! Твой профиль и игры доступны в ЛС: @{bot.username}")
            
        if user_id == ADMIN_ID:
            return await send_clean(message, "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n👇 Выбери раздел:", reply_markup=admin_panel_kb())
            
        bonus = f"🎁 Бонус: +{START_BONUS} Tokens\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n👋 Привет, {message.from_user.first_name}!\n{bonus}✨ Выбери действие 👇"
        try:
            await message.answer_photo(photo=FSInputFile("welcome.jpg"), caption=txt, reply_markup=main_menu())
        except Exception:
            await message.answer(txt, reply_markup=main_menu())

    # 📌 КОМАНДЫ В ГРУППАХ (ТОЛЬКО ТЕКСТ)
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        bal = get_balance(message.from_user.id)
        await message.reply(f"💰 <b>Баланс:</b> {fmt_num(bal)} Tokens")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().in_({"профиль", "я"}))
    async def group_prof(message: Message):
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = f"👤 <b>Профиль</b>\n🎖 {get_rank_name(lvl)}\n📊 XP: {xp}\n💎 {fmt_num(get_balance(uid))}"
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "топ")
    async def group_top(message: Message):
        rows = get_top(10); txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n\n"
        for i, r in enumerate(rows): txt += f"{['🥇','🥈','🥉'][i] if i<3 else i+1}. {r[1] or 'user'} — {fmt_num(r[2])}\n"
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "лог")
    async def group_log(message: Message):
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT detail FROM game_log WHERE game = 'рулетка' ORDER BY id DESC LIMIT 10")
        rows = c.fetchall(); c.close(); release_conn(conn)
        if not rows: return await message.reply("📜 История пуста.")
        txt = "📜 <b>ПОСЛЕДНИЕ 10 ЧИСЕЛ</b>\n\n" + " ".join([row[0] for row in rows])
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
    async def group_games_rules(message: Message):
        txt = (
            "🎮 <b>НАШИ ИГРЫ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🎡 <b>1. РУЛЕТКА</b>\n"
            "• <code>к 1000</code> — Красное (x1.95)\n"
            "• <code>ч 1000</code> — Чёрное (x1.95)\n"
            "• <code>з 1000</code> — Зеро (x35)\n"
            "• <code>1000 1-18 20-36</code> — Диапазоны (умный кэф)\n"
            "• <code>го</code> — Запустить\n\n"
            "🎲 <b>2. КОСТИ</b>\n"
            "• <code>кости 1000</code> — Ставка на кубик\n"
            "• Выигрыш, если выпадет <b>4, 5 или 6</b> (x1.95)\n\n"
            "🎰 <b>3. СЛОТЫ</b>\n"
            "• <code>спин 1000</code> — Крутить слоты\n"
            "• Три одинаковых символа — <b>ДЖЕКПОТ</b> (до x90)\n"
            "• Два одинаковых — <b>x1.8</b>\n\n"
            "━━━━━━━━━━━━━━\n"
            "📊 <b>Общие команды:</b>\n"
            "• <code>ставки</code> — Твои текущие ставки\n"
            "• <code>отмена</code> — Отменить ставки (возврат)\n"
            "• <code>лог</code> — История рулетки\n\n"
            "💸 <b>Баланс:</b> <code>б</code> или <code>баланс</code>"
        )
        await message.reply(txt)

    # 📌 КОМАНДЫ В ЛС (С КНОПКАМИ)
    @dp.message(F.chat.type == "private", F.text.lower().in_({"баланс", "б"}))
    @dp.message(F.text == "💰 Баланс")
    async def cmd_bal(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        await send_clean(message, f"💎 <b>Баланс:</b> {fmt_num(bal)}", reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"профиль", "я"}))
    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = f"👤 <b>Профиль</b>\n🎖 {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💎 {fmt_num(get_balance(uid))}"
        await send_clean(message, txt, reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"топ"}))
    @dp.message(F.text == "🏆 Топ")
    async def cmd_top(message: Message, state: FSMContext):
        await state.clear()
        rows = get_top(10); txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n\n"
        for i, r in enumerate(rows): txt += f"{['🥇','🥈','🥉'][i] if i<3 else i+1}. {r[1] or 'user'} — {fmt_num(r[2])}\n"
        await send_clean(message, txt, reply_markup=main_menu())

    @dp.message(F.chat.type == "private", F.text.lower().in_({"донат", "магазин"}))
    @dp.message(F.text == "🏪 Донат")
    async def cmd_don(message: Message, state: FSMContext):
        await state.clear()
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"💳 <b>ПОКУПКА TOKENS</b>\n\n💱 Курс: 1 ⭐ = {rate:,} Tokens\n\nВведи количество Stars от 1 до 10000:")
        await state.set_state(BotStates.waiting_custom_stars)

    @dp.message(BotStates.waiting_custom_stars)
    async def custom_sum_process(message: Message, state: FSMContext):
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000: return await send_clean(message, "❌ От 1 до 10000.")
            rate = get_rate("stars_rate", STARS_RATE)
            tokens = stars * rate
            await message.answer_invoice(title=f"{tokens:,} Tokens", description=f"Покупка {tokens:,} Tokens", payload=f"buy_{stars}_{tokens}", provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{tokens:,} Tokens", amount=stars)])
            await state.clear()
        except ValueError:
            await send_clean(message, "❌ Введи число.")

    @dp.message(F.chat.type == "private", F.text.lower().in_({"бонус"}))
    async def cmd_bonus(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,)); row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            await send_clean(message, "⏳ Бонус уже забран.", reply_markup=main_menu()); c.close(); release_conn(conn); return
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        await send_clean(message, "🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=main_menu())

    @dp.message(F.text == "🎰 Игры")
    async def btn_games(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type == "private":
            await send_clean(message, "🎰 Игры в группе 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 В ГРУППУ", url=GROUP_URL)]]))
        else: await send_clean(message, "🎰 Игры:", reply_markup=games_menu())

    @dp.message(F.text == "⬅️ Назад")
    async def btn_back(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "Главное меню 👇", reply_markup=main_menu())

    # ================= ИГРЫ =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("к ", "ч ", "з ", "чёт ", "нечет ")))
    async def place_bet(message: Message):
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split(); bet_type = {"к":"red","ч":"black","з":"green","чёт":"even","нечет":"odd"}.get(parts[0])
        if not bet_type: return
        try: bet = int(parts[1])
        except: return
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 10.")
        set_balance(uid, -bet)
        active_bets.setdefault(chat_id, {"bets": []})["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        await message.reply(f"✅ Ставка {fmt_num(bet)} принята!")

    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def place_range_bet(message: Message):
        if "-" not in message.text: return
        if message.text.lower().startswith(("кости ", "кубик ", "дайс ", "спин ", "слот ")): return
        uid = message.from_user.id; chat_id = message.chat.id
        parts = message.text.lower().split()
        if len(parts) < 2: return
        try: bet = int(parts[0])
        except ValueError: return
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 10.")
        ranges = []
        for p in parts[1:]:
            if "-" in p:
                try:
                    start, end = map(int, p.split("-"))
                    if 0 <= start <= end <= 36: ranges.append((start, end))
                except: pass
            else:
                try:
                    num = int(p)
                    if 0 <= num <= 36: ranges.append((num, num))
                except: pass
        if not ranges: return await message.reply("❌ Ошибка в формате.")
        set_balance(uid, -bet)
        active_bets.setdefault(chat_id, {"bets": []})["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": "range", "ranges": ranges, "bet": bet})
        await message.reply(f"✅ Ставка {fmt_num(bet)} на диапазоны принята!")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "ставки")
    async def show_bets(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("📊 Нет ставок.")
        txt = "📊 <b>СТАВКИ</b>\n\n" + "\n".join([f"@{b['username']}: {fmt_num(b['bet'])}" for b in active_bets[chat_id]["bets"]])
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок!")
        bets = active_bets[chat_id]["bets"]; total = sum(b["bet"] for b in bets)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_roulette")]])
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 Крутится... Банк: {fmt_num(total)}", reply_markup=cancel_kb)
        except: msg = await message.reply(f"🎡 Крутится... Банк: {fmt_num(total)}", reply_markup=cancel_kb)
        await asyncio.sleep(2.5)
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
            if w > 0: set_balance(b["user_id"], w); win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else: lose.append(f"😢 @{b['username']}")
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n\n" + ("🎉 <b>Победители:</b>\n"+"\n".join(win) if win else "") + ("\n\n💔 <b>Проиграли:</b>\n"+"\n".join(lose) if lose else "")
        try: await msg.edit_caption(caption=txt, reply_markup=None)
        except: await msg.edit_text(txt, reply_markup=None)
        await asyncio.sleep(30)
        try: await msg.delete()
        except: pass
        del active_bets[chat_id]

    @dp.callback_query(F.data == "cancel_roulette")
    async def cancel_roulette_callback(call: CallbackQuery):
        chat_id = call.message.chat.id; uid = call.from_user.id
        if chat_id in active_bets:
            my = [b for b in active_bets[chat_id]["bets"] if b["user_id"]==uid]
            if my:
                set_balance(uid, sum(b["bet"] for b in my))
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"]!=uid]
                await call.answer("❌ Ставки отменены, токены возвращены.")
                return
        await call.answer("❌ Нет ваших ставок.", show_alert=True)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message):
        uid = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except ValueError: return
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 10.")
        set_balance(uid, -bet)
        try: msg = await message.reply_animation(FSInputFile("dice.gif"), caption=f"🎲 <b>Кубик крутится...</b>\n💰 Ставка: {fmt_num(bet)}")
        except Exception: msg = await message.reply(f"🎲 <b>Кубик крутится...</b>\n💰 Ставка: {fmt_num(bet)}")
        await asyncio.sleep(2.5)
        result = random.randint(1, 6)
        if result >= 4:
            win_amount = int(bet * 1.95)
            set_balance(uid, win_amount)
            log_game(uid, username, "кости", bet, win_amount, str(result))
            txt = f"🎲 Выпало: <b>{result}</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 Выигрыш: <b>+{fmt_num(win_amount)}</b>"
        else:
            log_game(uid, username, "кости", bet, 0, str(result))
            txt = f"🎲 Выпало: <b>{result}</b>\n\n😢 <b>Проигрыш</b>\n💸 Потеряно: <b>-{fmt_num(bet)}</b>"
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        await asyncio.sleep(30)
        try: await msg.delete()
        except: pass

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("спин ", "слот ")))
    async def play_slots(message: Message):
        uid = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        parts = message.text.lower().split()
        if len(parts) != 2: return
        try: bet = int(parts[1])
        except ValueError: return
        if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Недостаточно или < 10.")
        set_balance(uid, -bet)
        try: msg = await message.reply_animation(FSInputFile("slots.gif"), caption=f"🎰 <b>Слоты крутятся...</b>\n💰 Ставка: {fmt_num(bet)}")
        except Exception: msg = await message.reply(f"🎰 <b>Слоты крутятся...</b>\n💰 Ставка: {fmt_num(bet)}")
        await asyncio.sleep(2.5)
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        if r1 == r2 == r3:
            multipliers = {"🍒": 9, "🍋": 13.5, "🍊": 18, "🍇": 22.5, "💎": 45, "7️⃣": 90}
            mult = multipliers.get(r1, 9)
            win_amount = int(bet * mult)
            set_balance(uid, win_amount)
            log_game(uid, username, "слоты", bet, win_amount, f"{r1}{r2}{r3}")
            txt = f"🎰 <b>{r1} | {r2} | {r3}</b>\n\n🔥 <b>ДЖЕКПОТ!</b>\n💰 Выигрыш: <b>+{fmt_num(win_amount)}</b> (x{mult})"
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win_amount = int(bet * 1.8)
            set_balance(uid, win_amount)
            log_game(uid, username, "слоты", bet, win_amount, f"{r1}{r2}{r3}")
            txt = f"🎰 <b>{r1} | {r2} | {r3}</b>\n\n✨ <b>Два совпадения!</b>\n💰 Выигрыш: <b>+{fmt_num(win_amount)}</b> (x1.8)"
        else:
            log_game(uid, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            txt = f"🎰 <b>{r1} | {r2} | {r3}</b>\n\n😢 <b>Проигрыш</b>\n💸 Потеряно: <b>-{fmt_num(bet)}</b>"
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        await asyncio.sleep(30)
        try: await msg.delete()
        except: pass

    # ================= ОПЛАТА =================
    @dp.pre_checkout_query()
    async def pre_check(query: PreCheckoutQuery): await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_"):
            _, stars, amount = payload.split("_"); set_balance(message.from_user.id, int(amount))
            await message.answer(f"✅ Зачислено {fmt_num(int(amount))} Tokens.")

    # ================= АДМИНКА =================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Скан игрока")],[KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],[KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "👥 УПРАВЛЕНИЕ", reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "🔍 Скан игрока")
    async def adm_scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🔍 Введи @username или ID игрока:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="scan")

    @dp.message(F.text == "💰 Выдать баланс")
    async def adm_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 @username (или ID) и сумму:")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать баланс")
    async def adm_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 @username (или ID) и сумму:")
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
        if not uid: return await send_clean(message, "❌ Не найден.")
        try: amount = int(parts[1])
        except: return await send_clean(message, "❌ Число.")
        set_balance(uid, amount if data["action"]=="give" else -amount)
        await send_clean(message, f"✅ {'Выдано' if data['action']=='give' else 'Списано'} {fmt_num(amount)}.")
        await state.clear()

    @dp.message(F.text == "🚫 Забанить")
    async def adm_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🚫 @username (или ID):")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="ban")

    @dp.message(F.text == "✅ Разбанить")
    async def adm_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "✅ @username (или ID):")
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
            return await send_clean(message, "❌ Не найден.")
            
        if data.get("action")=="ban": 
            set_banned(uid, True)
            await send_clean(message, "🚫 Забанен.")
        elif data.get("action")=="unban": 
            set_banned(uid, False)
            await send_clean(message, "✅ Разбанен.")
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
                txt = f"🕵️ <b>СКАН ИГРОКА</b>\n━━━━━━━━━━━━━━\n\n👤 @{uname}\n🆔 <code>{uid}</code>\n📊 Статус: {status}\n\n💎 Баланс: {fmt_num(bal)}\n🏦 Банк: {fmt_num(bank)}\n⭐ XP: {xp}\n\n🎮 <b>ПОСЛЕДНИЕ ИГРЫ:</b>\n"
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
        await send_clean(message, "📢 <b>РАССЫЛКА</b>\n\nКому отправить?", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📢 Напиши текст для всех:")
        await state.set_state(BotStates.waiting_broadcast_text)
        await state.update_data(target="all")

    @dp.message(F.text == "🎯 По @username")
    async def broadcast_user_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🎯 Введи @username игрока:")
        await state.set_state(BotStates.waiting_broadcast_target)
        await state.update_data(mode="user")

    @dp.message(F.text == "🆔 По ID")
    async def broadcast_id_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🆔 Введи ID игрока:")
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
                try: await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n\n{message.text}", parse_mode="HTML"); sent += 1; await asyncio.sleep(0.05)
                except: pass
            await send_clean(message, f"✅ Отправлено: {sent}")
        else:
            try:
                await message.bot.send_message(target, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n\n{message.text}", parse_mode="HTML")
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
        txt = f"🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n━━━━━━━━━━━━━━\n\n📊 Всего сыграно игр: <b>{total_games}</b>\n✅ Все игры включены."
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: ЭКОНОМИКА (АДМИН) ═══
    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
        total_users, total_balance = c.fetchone()
        c.close(); release_conn(conn)
        txt = f"💰 <b>ЭКОНОМИКА</b>\n━━━━━━━━━━━━━━\n\n👥 Всего игроков: <b>{total_users}</b>\n💎 Общий баланс: <b>{fmt_num(total_balance)}</b>\n\n💱 Курс Stars: <b>1 ⭐ = 7 500 Tokens</b>"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: КОНТЕНТ (АДМИН) ═══
    @dp.message(F.text == "🛒 Контент")
    async def admin_content_menu(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = f"🛒 <b>КОНТЕНТ</b>\n━━━━━━━━━━━━━━\n\n📦 Редактор магазина и кейсов появится в следующем обновлении."
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: МОНИТОРИНГ (АДМИН) ═══
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
        txt = f"📊 <b>МОНИТОРИНГ</b>\n━━━━━━━━━━━━━━\n\n✅ Активных: <b>{active}</b>\n🚫 Забаненных: <b>{banned}</b>\n\n👑 Админ: <b>@{message.from_user.username}</b>"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: ВСЕ КОМАНДЫ (АДМИН) ═══
    @dp.message(F.text == "📋 Все команды")
    async def admin_all_commands(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        txt = "📋 <b>КОМАНДЫ</b>\n━━━━━━━━━━━━━━\n\n/admin — меню\n/give @user сумма — выдать\n/ban @user — забанить\n/unban @user — разбанить"
        await send_clean(message, txt, reply_markup=admin_panel_kb())

    # ================= ПОДДЕРЖКА =================
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🆘 Поддержка доступна в ЛС: @{bot.username}")
        try: await message.answer_photo(FSInputFile("support.jpg"), caption="🆘 <b>ПОДДЕРЖКА</b>\n\nВыбери тему 👇", reply_markup=support_menu())
        except Exception: await message.answer("🆘 <b>ПОДДЕРЖКА</b>\n\nВыбери тему 👇", reply_markup=support_menu())

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💎 <b>Tokens не пришли</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Спокойно, сейчас разберёмся. Проблема решаема.\n\n"
            "1️⃣ <b>Проверь оплату.</b> Зайди в Telegram -> Настройки -> Мои подарки. Если платеж прошел, но токенов нет — читаем дальше.\n"
            "2️⃣ <b>Подожди 5–10 минут.</b> Telegram Stars иногда зачисляются с задержкой.\n"
            "3️⃣ <b>Перезапусти бота.</b> Напиши /start. Если баланс не обновился — идем в поддержку.\n\n"
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
            "🎮 <b>Что-то сломалось в игре</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Опиши проблему, и мы починим это как можно скорее!\n\n"
            "Пожалуйста, укажи:\n"
            "1️⃣ <b>В какой игре</b> произошла ошибка (Рулетка, Слоты, Мины и т.д.).\n"
            "2️⃣ <b>Что ты делал</b> (какую команду вводил, на какую кнопку жал).\n"
            "3️⃣ <b>Что пошло не так</b> (списалось дважды, не выдало выигрыш, бот завис).\n\n"
            "📸 <b>Пришли скриншот</b> — это ускорит починку в 2 раза!\n\n"
            f"📩 <b>Куда писать:</b> {SUPPORT_USERNAME}\n"
            "Мы всё проверим по логам."
        )
        await send_clean(message, txt, reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "💳 <b>Вопрос по оплате</b>\n"
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
            "🚫 <b>Бан или мут</b>\n"
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
            "🐞 <b>Нашёл баг</b>\n"
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
        txt = (
            "📜 <b>Правила Gold Casino</b>\n"
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

    # ================= ЗАПУСК =================
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")