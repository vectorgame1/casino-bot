# handlers.py
import asyncio
from datetime import datetime
from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_NAME, START_BONUS, STARS_RATE, GROUP_URL, ADMIN_ID, TZ_MINSK
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb
from database import (
    get_balance, get_rate, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_balance,
    get_conn, release_conn
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

class DonateStates(StatesGroup):
    waiting_custom_stars = State()

def register(dp: Dispatcher):

    # ═══ СТАРТ ═══
    @dp.message(Command("start"))
    async def start(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        ensure_user(user_id, username)
        
        if is_banned(user_id):
            await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>\n\nОбратитесь в поддержку: @vctorw", parse_mode="HTML")
            return
            
        is_new = check_and_give_bonus(user_id, START_BONUS)
        
        # Админка
        if user_id == ADMIN_ID:
            await send_clean(message, "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n━━━━━━━━━━━━━━\n\nДобро пожаловать, Босс. 👇 Выбери раздел:", parse_mode="HTML", reply_markup=admin_panel_kb())
            return
            
        # Игрок
        if is_new:
            bonus_block = "🎁 <b>ТВОЙ СТАРТОВЫЙ БОНУС:</b>\n💰 <b>+5 000 Tokens</b>\n\n"
        else:
            bonus_block = ""
            
        txt = (
            f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            "Ты попал в элитный игровой клуб.\n\n"
            "💎 Здесь только виртуальные Tokens.\n"
            "🎰 Реальных ставок нет (18+).\n\n"
            f"{bonus_block}"
            "✨ <b>Выбери, с чего начнём:</b>\n"
            "👇 Жми на кнопки ниже!"
        )
        
        try:
            photo = FSInputFile("welcome.png") 
            await message.answer_photo(photo=photo, caption=txt, parse_mode="HTML", reply_markup=main_menu())
        except Exception:
            await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())

    # ═══ РУССКИЕ КОМАНДЫ (И ЛС, И ГРУППЫ) ═══
    
    @dp.message(F.text.lower().in_({"баланс", "б", "деньги"}))
    async def cmd_balance_ru(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(message, f"💎 <b>ТВОЙ БАЛАНС</b>\n━━━━━━━━━━━━━━\n\n💰 Tokens: <b>{fmt_num(bal)}</b>", parse_mode="HTML")

    @dp.message(F.text.lower().in_({"профиль", "я", "стата"}))
    async def cmd_profile_ru(message: Message):
        user_id = message.from_user.id
        bal, xp = get_balance(user_id), get_xp(user_id)
        level = xp // 100
        rank, bar = get_rank_name(level), make_xp_bar(xp)
        await send_clean(message, f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━\n\n🎖 <b>Ранг:</b> {rank}\n📊 <b>Опыт:</b> {xp} / {(level+1)*100} XP\n<code>{bar}</code>\n\n💎 <b>Баланс:</b> {fmt_num(bal)} Tokens", parse_mode="HTML")

    @dp.message(F.text.lower().in_({"топ", "топ 10"}))
    async def cmd_top_ru(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n━━━━━━━━━━━━━━\n\n"
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"<b>{i+1}.</b>"
            txt += f"{medal} <b>{uname or f'user_{uid}'}</b> — {fmt_num(bal)} Tokens\n"
        await send_clean(message, txt, parse_mode="HTML")

    @dp.message(F.text.lower().in_({"донат", "магазин", "купить"}))
    async def cmd_donate_ru(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"🏪 <b>ДОНАТ</b>\n━━━━━━━━━━━━━━\n\n💱 Курс: <b>1 ⭐ = {rate:,} Tokens</b>\n\n✨ Выбери пакет 👇", parse_mode="HTML", reply_markup=donate_menu())

    # ═══ БОНУС (РАБОТАЕТ ВЕЗДЕ) ═══
    @dp.message(F.text.lower().in_({"бонус", "забрать", "ежедневка"}))
    async def daily_bonus(message: Message):
        user_id = message.from_user.id
        ensure_user(user_id, message.from_user.username or "user")
        
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        
        today = datetime.now(TZ_MINSK).date()
        last_date = row[0] if row and row[0] else None
        
        if last_date == today:
            await send_clean(message, "⏳ Ты уже забирал бонус сегодня!\n\nВозвращайся завтра 👇", parse_mode="HTML")
            c.close()
            release_conn(conn)
            return
            
        bonus_amount = 5000
        c.execute("UPDATE users SET balance = balance + %s, last_login_date = %s WHERE user_id = %s", (bonus_amount, today, user_id))
        conn.commit()
        c.close()
        release_conn(conn)
        
        await send_clean(
            message,
            f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💰 Ты получил: <b>+{fmt_num(bonus_amount)} Tokens</b>\n\n"
            f"✨ Приходи завтра за новым бонусом!",
            parse_mode="HTML"
        )

    # ═══ ЧТО НОВОГО (С АВТОУДАЛЕНИЕМ) ═══
    @dp.message(F.text.lower().in_({"что нового", "новости", "апдейт"}))
    async def whats_new(message: Message):
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
        msg = await message.answer(txt, parse_mode="HTML")
        await asyncio.sleep(120)
        try: await msg.delete()
        except: pass

    # ═══ ОБЫЧНЫЕ КНОПКИ (ДЛЯ ЛС) ═══
    @dp.message(F.text == "💰 Баланс")
    async def balance_btn(message: Message):
        await cmd_balance_ru(message)

    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(message: Message):
        await cmd_profile_ru(message)

    @dp.message(F.text == "🏆 Топ")
    async def top_btn(message: Message):
        await cmd_top_ru(message)

    @dp.message(F.text == "🏪 Донат")
    async def donate_btn(message: Message):
        await cmd_donate_ru(message)

    @dp.message(F.text == "🎰 Игры")
    async def games(message: Message):
        if message.chat.type == "private":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 ПЕРЕЙТИ В ГРУППУ", url=GROUP_URL)]])
            await send_clean(message, f"🎰 <b>ИГРЫ В ГРУППЕ</b>\n\n👇 Переходи: {GROUP_URL}", parse_mode="HTML", reply_markup=kb)
        else:
            await send_clean(message, "🎰 <b>Выбирай:</b>", parse_mode="HTML", reply_markup=games_menu())

    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await send_clean(message, "✨ Главное меню 👇", reply_markup=main_menu())

    # ═══ ОПЛАТА ═══
    @dp.message(F.text == "💎 50 000 Tokens — 7 ⭐")
    async def buy_50k(message: Message):
        await message.answer_invoice(title="50 000 Tokens", description="Покупка Tokens", payload="donate_50k", provider_token="", currency="XTR", prices=[LabeledPrice(label="50 000 Tokens", amount=7)])

    @dp.message(F.text == "💎 150 000 Tokens — 20 ⭐")
    async def buy_150k(message: Message):
        await message.answer_invoice(title="150 000 Tokens", description="Покупка Tokens", payload="donate_150k", provider_token="", currency="XTR", prices=[LabeledPrice(label="150 000 Tokens", amount=20)])

    @dp.message(F.text == "💎 300 000 Tokens — 40 ⭐")
    async def buy_300k(message: Message):
        await message.answer_invoice(title="300 000 Tokens", description="Покупка Tokens", payload="donate_300k", provider_token="", currency="XTR", prices=[LabeledPrice(label="300 000 Tokens", amount=40)])

    @dp.message(F.text == "💎 1 000 000 Tokens — 125 ⭐")
    async def buy_1m(message: Message):
        await message.answer_invoice(title="1 000 000 Tokens", description="Покупка Tokens", payload="donate_1m", provider_token="", currency="XTR", prices=[LabeledPrice(label="1 000 000 Tokens", amount=125)])

    @dp.message(F.text == "💎 2 000 000 Tokens — 265 ⭐")
    async def buy_2m(message: Message):
        await message.answer_invoice(title="2 000 000 Tokens", description="Покупка Tokens", payload="donate_2m", provider_token="", currency="XTR", prices=[LabeledPrice(label="2 000 000 Tokens", amount=265)])

    @dp.message(F.text == "💎 Своя сумма")
    async def custom_sum_start(message: Message, state: FSMContext):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"💳 <b>СВОЯ СУММА</b>\n━━━━━━━━━━━━━━\n\nВведи количество Stars от 1 до 10000.\nКурс: <b>1 ⭐ = {rate:,} Tokens</b>.\n\nПример: <code>10</code> ⭐ = <b>75 000</b> Tokens.", parse_mode="HTML")
        await state.set_state(DonateStates.waiting_custom_stars)

    @dp.message(DonateStates.waiting_custom_stars)
    async def custom_sum_process(message: Message, state: FSMContext):
        try:
            stars = int(message.text)
            if stars < 1 or stars > 10000:
                await send_clean(message, "❌ Введи число от 1 до 10000.")
                return
            
            rate = get_rate("stars_rate", STARS_RATE)
            tokens = stars * rate
            
            await send_clean(
                message,
                f"💎 <b>ПОДТВЕРЖДЕНИЕ</b>\n━━━━━━━━━━━━━━\n\n"
                f"⭐ Stars: <b>{stars}</b>\n"
                f"💰 Tokens: <b>{fmt_num(tokens)}</b>\n\n"
                "👇 Нажми на кнопку ниже, чтобы оплатить:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⭐ Оплатить", callback_data=f"pay_custom_{stars}_{tokens}")]])
            )
            await state.clear()
        except ValueError:
            await send_clean(message, "❌ Введи число от 1 до 10000.")

    @dp.callback_query(F.data.startswith("pay_custom_"))
    async def pay_custom_callback(call: CallbackQuery):
        parts = call.data.split("_")
        stars = int(parts[2])
        tokens = int(parts[3])
        await call.message.answer_invoice(
            title=f"{fmt_num(tokens)} Tokens",
            description=f"Покупка {fmt_num(tokens)} Tokens за {stars} Stars",
            payload=f"custom_{stars}_{tokens}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{fmt_num(tokens)} Tokens", amount=stars)]
        )
        await call.answer()

    @dp.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("custom_"):
            amount = int(payload.split("_")[2])
        else:
            amount = {"donate_50k": 50000, "donate_150k": 150000, "donate_300k": 300000, "donate_1m": 1000000, "donate_2m": 2000000}.get(payload, 0)
            
        if amount > 0:
            set_balance(message.from_user.id, amount)
            await message.answer(f"✅ <b>ОПЛАТА УСПЕШНА!</b>\n━━━━━━━━━━━━━━\n\n💰 Зачислено: <b>+{fmt_num(amount)} Tokens</b>\n\n✨ Спасибо за поддержку! 🖤", parse_mode="HTML")