# bot.py — ПОЛНЫЙ МОНОЛИТ (ИГРОК + АДМИНКА + ИГРЫ + ПОДДЕРЖКА)
import asyncio
import logging
import os
import random
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb, support_menu
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

class BotStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_broadcast = State()
    waiting_question = State()
    waiting_custom_stars = State()

active_bets = {}
admin_replies = {}
last_scanned = {}

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_color(num):
    if num == 0: return "🟢"
    if num in RED_NUMBERS: return "🔴"
    return "⚫"

async def start_web_server():
    async def health(request): return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    init_pool()
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ================= ИГРОК =================

    @dp.message(Command("start"))
    async def start(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        ensure_user(user_id, username)
        
        if is_banned(user_id):
            await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>")
            return
            
        is_new = check_and_give_bonus(user_id, START_BONUS)
        
        if user_id == ADMIN_ID:
            await send_clean(message, "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n👇 Выбери раздел:", reply_markup=admin_panel_kb())
            return
            
        bonus = f"🎁 Бонус: +{START_BONUS} Tokens\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n👋 Привет, {username}!\n{bonus}✨ Выбери действие 👇"
        
        try:
            photo = FSInputFile("welcome.png")
            await message.answer_photo(photo=photo, caption=txt, reply_markup=main_menu())
        except:
            await message.answer(txt, reply_markup=main_menu())

    @dp.message(F.text.lower().in_({"баланс", "б"}))
    async def cmd_bal(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(message, f"💎 <b>Баланс:</b> {fmt_num(bal)} Tokens")

    @dp.message(F.text.lower().in_({"профиль", "я"}))
    async def cmd_prof(message: Message):
        uid = message.from_user.id
        bal, xp = get_balance(uid), get_xp(uid)
        lvl = xp // 100
        rank, bar = get_rank_name(lvl), make_xp_bar(xp)
        await send_clean(message, f"👤 <b>Профиль</b>\n🎖 Ранг: {rank}\n📊 Опыт: {xp}/{(lvl+1)*100}\n{bar}\n💎 Баланс: {fmt_num(bal)}")

    @dp.message(F.text.lower().in_({"топ"}))
    async def cmd_top(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n\n"
        for i, r in enumerate(rows):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            txt += f"{medal} {r[1] or 'user'} — {fmt_num(r[2])}\n"
        await send_clean(message, txt)

    @dp.message(F.text.lower().in_({"донат", "магазин"}))
    async def cmd_don(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"🏪 <b>ДОНАТ</b>\n💱 Курс: 1 ⭐ = {rate:,} Tokens\n\n👇 Выбери пакет:", reply_markup=donate_menu())

    @dp.message(F.text.lower().in_({"бонус"}))
    async def cmd_bonus(message: Message):
        uid = message.from_user.id
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            await send_clean(message, "⏳ Бонус уже забран сегодня.")
            c.close(); release_conn(conn)
            return
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit()
        c.close(); release_conn(conn)
        await send_clean(message, "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС: +5 000 Tokens</b>")

    @dp.message(F.text == "🎰 Игры")
    async def btn_games(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 В ГРУППУ", url=GROUP_URL)]])
        await send_clean(message, "🎰 Игры доступны в группе 👇", reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад")
    async def btn_back(message: Message):
        await send_clean(message, "Главное меню 👇", reply_markup=main_menu())

    # ================= ИГРЫ (РУЛЕТКА) =================

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("к ", "ч ", "з ", "чёт ", "нечет ")))
    async def place_bet(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        chat_id = message.chat.id
        
        ensure_user(user_id, username)
        if is_banned(user_id): return

        parts = message.text.lower().split()
        if len(parts) != 2: return
        
        bet_type_str = parts[0]
        try: bet = int(parts[1])
        except ValueError: return
        
        if bet < 10:
            await message.reply("❌ Мин. ставка: 10")
            return

        bal = get_balance(user_id)
        if bal < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {fmt_num(bal)}")
            return

        bet_type = {"к": "red", "ч": "black", "з": "green", "чёт": "even", "нечет": "odd"}.get(bet_type_str)
        if not bet_type: return

        set_balance(user_id, -bet)
        
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username, "type": bet_type, "bet": bet
        })
        
        icon = {"red": "🔴", "black": "⚫", "green": "🟢", "even": "2️⃣", "odd": "1️⃣"}[bet_type]
        await message.reply(f"✅ <b>Ставка принята!</b>\n👤 {username}\n💰 {fmt_num(bet)} на {icon}\n🕐 Напиши «го»")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "ставки")
    async def show_bets(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("📊 Сейчас нет активных ставок.")
            return
        
        txt = "📊 <b>ТЕКУЩИЕ СТАВКИ</b>\n\n"
        icons = {"red": "🔴", "black": "⚫", "green": "🟢", "even": "2️⃣", "odd": "1️⃣"}
        for b in active_bets[chat_id]["bets"]:
            txt += f"👤 @{b['username']}: {icons[b['type']]} — {fmt_num(b['bet'])} Tokens\n"
        await message.reply(txt)

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет ставок! Сделай: к 1000")
            return
            
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet"] for b in bets)
        
        try:
            gif = FSInputFile("roulette.gif")
            msg = await message.reply_animation(animation=gif, caption=f"🎡 <b>РУЛЕТКА КРУТИТСЯ...</b>\n💰 Банк: {fmt_num(total_bank)}")
        except:
            msg = await message.reply(f"🎡 <b>РУЛЕТКА КРУТИТСЯ...</b>\n💰 Банк: {fmt_num(total_bank)}")
            
        await asyncio.sleep(2.5)
        result = random.randint(0, 36)
        color = get_color(result)
        
        winners, losers = [], []
        for b in bets:
            win_amount = 0
            if b["type"] == "red" and result in RED_NUMBERS: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "black" and result in BLACK_NUMBERS: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "green" and result == 0: win_amount = int(b["bet"] * 35)
            elif b["type"] == "even" and result != 0 and result % 2 == 0: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "odd" and result % 2 != 0: win_amount = int(b["bet"] * 1.95)
                
            if win_amount > 0:
                set_balance(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], win_amount, f"{result} {color}")
                winners.append(f"🏆 @{b['username']} — +{fmt_num(win_amount)}")
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], 0, f"{result} {color}")
                losers.append(f"😢 @{b['username']}")
                
        txt = f"🎡 <b>ВЫПАЛО: {color} {result}</b>\n\n"
        if winners: txt += "🎉 <b>Победители:</b>\n" + "\n".join(winners) + "\n\n"
        if losers: txt += "💔 <b>Проиграли:</b>\n" + "\n".join(losers)
            
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)

        del active_bets[chat_id]

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "отмена")
    async def cancel_bets(message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        if chat_id in active_bets:
            my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == user_id]
            if my_bets:
                refund = sum(b["bet"] for b in my_bets)
                set_balance(user_id, refund)
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"] != user_id]
                await message.reply(f"❌ Отменено. Возвращено {fmt_num(refund)}.")

    # ================= ОПЛАТА =================

    @dp.message(F.text.startswith("💎 ") & F.text.endswith("⭐"))
    async def handle_buy(message: Message):
        parts = message.text.split()
        try:
            amount = int("".join(parts[1:3])) * 1000
            stars = int(parts[-2])
        except: return
        await message.answer_invoice(
            title=f"{amount:,} Tokens", description="Покупка Tokens", payload=f"buy_{stars}_{amount}",
            provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{amount:,} Tokens", amount=stars)]
        )

    @dp.pre_checkout_query()
    async def pre_check(query: PreCheckoutQuery): await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_"):
            _, stars, amount = payload.split("_")
            set_balance(message.from_user.id, int(amount))
            await message.answer(f"✅ Зачислено {fmt_num(int(amount))} Tokens.")

    # ================= АДМИНКА =================

    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n👇 Выбери раздел:", reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Скан игрока")],[KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],[KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await send_clean(message, "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n👇 Выбери действие:", reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=admin_panel_kb())

    @dp.message(F.text == "💰 Выдать баланс")
    async def adm_give_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 Введи @username и сумму (например: @vctorw 5000):")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать баланс")
    async def adm_take_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 Введи @username и сумму (например: @vctorw 5000):")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="take")

    @dp.message(BotStates.waiting_amount)
    async def adm_amount_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        parts = message.text.split()
        if len(parts) != 2:
            await send_clean(message, "❌ Формат: @username сумма")
            return
        target = parts[0].replace("@", "")
        try: amount = int(parts[1])
        except: 
            await send_clean(message, "❌ Сумма должна быть числом.")
            return
        uid = get_user_id_by_username(target)
        if not uid:
            await send_clean(message, "❌ Игрок не найден.")
            return
        if data["action"] == "give":
            set_balance(uid, amount)
            await send_clean(message, f"✅ Выдано {fmt_num(amount)} @{target}")
        else:
            set_balance(uid, -amount)
            await send_clean(message, f"✅ Списано {fmt_num(amount)} @{target}")
        await state.clear()

    @dp.message(F.text == "🚫 Забанить")
    async def adm_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🚫 Введи @username для бана:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="ban")

    @dp.message(F.text == "✅ Разбанить")
    async def adm_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "✅ Введи @username для разбана:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="unban")

    @dp.message(BotStates.waiting_scan)
    async def adm_scan_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = message.text.replace("@", "")
        uid = get_user_id_by_username(target)
        if not uid:
            await send_clean(message, "❌ Игрок не найден.")
            await state.clear()
            return
        
        if data.get("action") == "ban":
            set_banned(uid, True)
            await send_clean(message, f"🚫 @{target} забанен.")
        elif data.get("action") == "unban":
            set_banned(uid, False)
            await send_clean(message, f"✅ @{target} разбанен.")
        else:
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT balance, xp, banned FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            c.close(); release_conn(conn)
            if row:
                bal, xp, banned = row
                status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
                await send_clean(message, f"🕵️ <b>СКАН</b>\n👤 @{target}\n🆔 {uid}\n📊 {status}\n💎 {fmt_num(bal)}\n⭐ {xp}")
        await state.clear()

    # ЗАГЛУШКИ ДЛЯ ОСТАЛЬНЫХ КНОПОК
    @dp.message(F.text.in_({"🎮 Игры", "🛒 Контент", "💰 Экономика", "📊 Мониторинг", "📋 Все команды"}))
    async def placeholders(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, f"🛠 {message.text} (в разработке)", reply_markup=admin_panel_kb())

    # ================= ЗАПУСК =================
    await dp.start_polling(bot)

async def main_wrapper():
    asyncio.create_task(start_web_server())
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(main_wrapper())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен")