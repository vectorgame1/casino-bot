# bot.py — ФИНАЛЬНЫЙ МОНОЛИТ (v13)
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

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL
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
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()

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
        if user_id == ADMIN_ID:
            return await send_clean(message, "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n👇 Выбери раздел:", reply_markup=admin_panel_kb())
            
        bonus = f"🎁 Бонус: +{START_BONUS} Tokens\n\n" if is_new else ""
        txt = f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n👋 Привет, {message.from_user.first_name}!\n{bonus}✨ Выбери действие 👇"
        try:
            await message.answer_photo(photo=FSInputFile("welcome.jpg"), caption=txt, reply_markup=main_menu())
        except Exception:
            await message.answer(txt, reply_markup=main_menu())

    @dp.message(F.text.lower().in_({"баланс", "б"}))
    @dp.message(F.text == "💰 Баланс")
    async def cmd_bal(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        if message.chat.type == "private": await send_clean(message, f"💎 <b>Баланс:</b> {fmt_num(bal)}", reply_markup=main_menu())
        else: await message.reply(f"💰 Баланс: <b>{fmt_num(bal)}</b>")

    @dp.message(F.text.lower().in_({"профиль", "я"}))
    @dp.message(F.text == "👤 Профиль")
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id; xp = get_xp(uid); lvl = xp // 100
        txt = f"👤 <b>Профиль</b>\n🎖 {get_rank_name(lvl)}\n📊 XP: {xp}\n{make_xp_bar(xp)}\n💎 {fmt_num(get_balance(uid))}"
        if message.chat.type == "private": await send_clean(message, txt, reply_markup=main_menu())
        else: await message.reply(txt)

    @dp.message(F.text.lower().in_({"топ"}))
    @dp.message(F.text == "🏆 Топ")
    async def cmd_top(message: Message, state: FSMContext):
        await state.clear()
        rows = get_top(10); txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n\n"
        for i, r in enumerate(rows): txt += f"{['🥇','🥈','🥉'][i] if i<3 else i+1}. {r[1] or 'user'} — {fmt_num(r[2])}\n"
        if message.chat.type == "private": await send_clean(message, txt, reply_markup=main_menu())
        else: await message.reply(txt)

    @dp.message(F.text.lower().in_({"донат", "магазин"}))
    @dp.message(F.text == "🏪 Донат")
    async def cmd_don(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🏪 В ЛС: @{bot.username}")
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
            await message.answer_invoice(
                title=f"{tokens:,} Tokens",
                description=f"Покупка {tokens:,} Tokens за {stars} Stars",
                payload=f"buy_{stars}_{tokens}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=f"{tokens:,} Tokens", amount=stars)]
            )
            await state.clear()
        except ValueError:
            await send_clean(message, "❌ Введи число.")

    @dp.message(F.text.lower().in_({"бонус"}))
    async def cmd_bonus(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type != "private": return await message.reply(f"🎁 В ЛС: @{bot.username}")
        uid = message.from_user.id; conn = get_conn(); c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,)); row = c.fetchone()
        today = datetime.now(TZ_MINSK).date()
        if row and row[0] == today:
            await send_clean(message, "⏳ Бонус уже забран.", reply_markup=main_menu()); c.close(); release_conn(conn); return
        c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
        conn.commit(); c.close(); release_conn(conn)
        await send_clean(message, "🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=main_menu())

    @dp.message(F.text.lower().in_({"что нового", "новости", "апдейт"}))
    async def cmd_news(message: Message, state: FSMContext):
        await state.clear()
        txt = (
            "🆕 <b>ЧТО НОВОГО В БОТЕ?</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "🔥 <b>Глобальное обновление:</b>\n"
            "• 💎 Новый дизайн (золото/черный)\n"
            "• 🎁 Ежедневный бонус (команда <code>бонус</code>)\n"
            "• 🎰 Обновленная Рулетка (с гифкой и логом)\n"
            "• 🆘 Улучшенная поддержка\n"
            "• 👑 Полностью рабочая Админка\n\n"
            "⏳ <i>Это сообщение удалится через 2 минуты.</i>"
        )
        msg = await message.answer(txt)
        await asyncio.sleep(120)
        try: await msg.delete()
        except: pass

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

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("10-", "1-", "2-", "3-", "4-", "5-", "6-", "7-", "8-", "9-")))
    async def place_range_bet(message: Message):
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
        try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 Крутится... Банк: {fmt_num(total)}")
        except: msg = await message.reply(f"🎡 Крутится... Банк: {fmt_num(total)}")
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
        try: await msg.edit_caption(caption=txt)
        except: await msg.edit_text(txt)
        await asyncio.sleep(30)
        try: await msg.delete()
        except: pass
        del active_bets[chat_id]

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "отмена")
    async def cancel_bets(message: Message):
        chat_id = message.chat.id; uid = message.from_user.id
        if chat_id in active_bets:
            my = [b for b in active_bets[chat_id]["bets"] if b["user_id"]==uid]
            if my:
                set_balance(uid, sum(b["bet"] for b in my))
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"]!=uid]
                await message.reply("❌ Отменено.")

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

    @dp.message(F.text == "💰 Выдать баланс")
    async def adm_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 @username и сумму:")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать баланс")
    async def adm_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 @username и сумму:")
        await state.set_state(BotStates.waiting_amount)
        await state.update_data(action="take")

    @dp.message(BotStates.waiting_amount)
    async def adm_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data(); parts = message.text.split()
        if len(parts) != 2: return await send_clean(message, "❌ Формат: @user сумма")
        uid = get_user_id_by_username(parts[0].replace("@", ""))
        if not uid: return await send_clean(message, "❌ Не найден.")
        try: amount = int(parts[1])
        except: return await send_clean(message, "❌ Число.")
        set_balance(uid, amount if data["action"]=="give" else -amount)
        await send_clean(message, f"✅ {'Выдано' if data['action']=='give' else 'Списано'} {fmt_num(amount)}.")
        await state.clear()

    @dp.message(F.text == "🚫 Забанить")
    async def adm_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🚫 @username:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="ban")

    @dp.message(F.text == "✅ Разбанить")
    async def adm_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "✅ @username:")
        await state.set_state(BotStates.waiting_scan)
        await state.update_data(action="unban")

    @dp.message(BotStates.waiting_scan)
    async def adm_scan(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = message.text.replace("@", "").strip()
        uid = get_user_id_by_username(target)
        if not uid:
            await state.clear()
            return await send_clean(message, "❌ Не найден.")
        if data.get("action")=="ban": 
            set_banned(uid, True)
            await send_clean(message, "🚫 Забанен.")
        elif data.get("action")=="unban": 
            set_banned(uid, False)
            await send_clean(message, "✅ Разбанен.")
        else:
            conn = get_conn(); c = conn.cursor(); c.execute("SELECT balance, xp, banned FROM users WHERE user_id=%s",(uid,)); row=c.fetchone(); c.close(); release_conn(conn)
            if row: await send_clean(message, f"🕵️ @{target}\n💎 {fmt_num(row[0])}\n⭐ {row[1]}\n📊 {'🚫' if row[2] else '✅'}")
        await state.clear()

    # 🆕 ЗАГЛУШКИ ДЛЯ ОСТАЛЬНЫХ КНОПОК
    @dp.message(F.text.in_({"🎮 Игры", "🛒 Контент", "💰 Экономика", "📊 Мониторинг", "📋 Все команды"}))
    async def placeholders(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, f"🛠 {message.text} в разработке.", reply_markup=admin_panel_kb())

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
        await send_clean(message, "💎 <b>Tokens не пришли</b>\n\n1. Проверь оплату.\n2. Подожди 5 минут.\n3. Напиши @vctorw", reply_markup=support_menu())

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "🎮 <b>Что-то сломалось в игре</b>\n\nОпиши проблему: @vctorw", reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "💳 <b>Вопрос по оплате</b>\n\nВсе покупки через Stars. Если что-то неясно: @vctorw", reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "🚫 <b>Бан или мут</b>\n\nЕсли наказание ошибочно, напиши @username и причину сюда: @vctorw", reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "🐞 <b>Нашёл баг</b>\n\nОпиши баг и пришли скриншот сюда: @vctorw", reply_markup=support_menu())

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message, state: FSMContext):
        await state.clear()
        await send_clean(message, "📜 <b>Правила</b>\n\n1. 18+\n2. Виртуальные Tokens\n3. Без мультиаккаунтов\n4. Донат — добровольный", reply_markup=support_menu())

    @dp.message(F.text == "✍️ Свой вопрос")
    async def own_q(message: Message, state: FSMContext):
        await send_clean(message, "✍️ Напиши вопрос:")
        await state.set_state(BotStates.waiting_question)

    @dp.message(BotStates.waiting_question)
    async def fwd_admin(message: Message, state: FSMContext):
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
        msg = await message.bot.send_message(ADMIN_ID, f"📩 <b>Вопрос</b>\n👤 {username}\n\n«{message.text}»\n\n↩️ <i>Reply чтобы ответить.</i>")
        admin_replies[msg.message_id] = message.from_user.id
        await send_clean(message, "✅ Отправлено оператору.", reply_markup=main_menu())
        await state.clear()

    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply(message: Message):
        uid = admin_replies.get(message.reply_to_message.message_id)
        if not uid: return
        try:
            await message.bot.send_message(uid, f"📩 <b>Ответ поддержки:</b>\n\n«{message.text}»\n\n— {BOT_NAME}")
            await message.answer("✅ Отправлено!")
        except Exception as e: await message.answer(f"❌ {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())