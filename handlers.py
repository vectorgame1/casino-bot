from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_NAME, START_BONUS, STARS_RATE, GROUP_URL, ADMIN_ID
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb
from database import (
    get_balance, get_rate, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_balance
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

class DonateStates(StatesGroup):
    waiting_custom_stars = State()

def register(dp: Dispatcher):
    # 🆕 ПРОПУСКАЕМ ВСЕ КНОПКИ АДМИНКИ, ЧТОБЫ ОНИ ДОШЛИ ДО admin_panel.py
    @dp.message(F.text.in_({"👥 Игроки", "🎮 Игры", "🛒 Контент", "💰 Экономика", "📢 Связь", "📊 Мониторинг", "📋 Все команды", "❌ Отмена", "⬅️ Назад в админку", "⬅️ В меню игроков", "🔍 Скан игрока", "🚫 Забанить его", "✅ Разбанить его", "💰 Выдать ему", "💸 Забрать у него", "🚫 Забанить", "✅ Разбанить", "💰 Выдать баланс", "💸 Забрать баланс", "📢 Всем игрокам"}))
    async def skip_admin_buttons(message: Message):
        pass



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
        
        # 🆕 АДМИН ВИДИТ СРАЗУ АДМИНКУ
        if user_id == ADMIN_ID:
            await send_clean(
                message,
                "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                "Добро пожаловать, Босс. 👇 Выбери раздел:",
                parse_mode="HTML",
                reply_markup=admin_panel_kb()
            )
            return
            
        # 🆕 КРАСИВЫЙ СТАРТ ДЛЯ ИГРОКОВ
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
        
        # Отправка с картинкой (если файла нет - отправит текст)
        try:
            photo = FSInputFile("welcome.jpg") 
            await message.answer_photo(photo=photo, caption=txt, parse_mode="HTML", reply_markup=main_menu())
        except Exception:
            await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())

    # ═══ БАЛАНС ═══
    @dp.message(F.text == "💰 Баланс")
    async def balance(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(message, f"💎 <b>ТВОЙ БАЛАНС</b>\n━━━━━━━━━━━━━━\n\n💰 Tokens: <b>{fmt_num(bal)}</b>\n\n✨ Пополни в Донате!", parse_mode="HTML", reply_markup=main_menu())

    # ═══ ПРОФИЛЬ ═══
    @dp.message(F.text == "👤 Профиль")
    async def profile(message: Message):
        user_id = message.from_user.id
        bal, xp = get_balance(user_id), get_xp(user_id)
        level = xp // 100
        rank, bar = get_rank_name(level), make_xp_bar(xp)
        await send_clean(message, f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━\n\n🎖 <b>Ранг:</b> {rank}\n📊 <b>Опыт:</b> {xp} / {(level+1)*100} XP\n<code>{bar}</code>\n\n💎 <b>Баланс:</b> {fmt_num(bal)} Tokens", parse_mode="HTML", reply_markup=main_menu())

    # ═══ ТОП ═══
    @dp.message(F.text == "🏆 Топ")
    async def top(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n━━━━━━━━━━━━━━\n\n"
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"<b>{i+1}.</b>"
            txt += f"{medal} <b>{uname or f'user_{uid}'}</b> — {fmt_num(bal)} Tokens\n"
        await send_clean(message, txt, parse_mode="HTML", reply_markup=main_menu())

    # ═══ ИГРЫ ═══
    @dp.message(F.text == "🎰 Игры")
    async def games(message: Message):
        if message.chat.type == "private":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 ПЕРЕЙТИ В ГРУППУ", url=GROUP_URL)]
            ])
            await send_clean(
                message,
                "🎰 <b>ИГРОВОЙ ЗАЛ</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                "Игры доступны только в нашей группе!\n"
                "👇 Нажми на кнопку ниже:",
                parse_mode="HTML",
                reply_markup=kb
            )
        else:
            await send_clean(message, "🎰 <b>Выбирай:</b>", parse_mode="HTML", reply_markup=games_menu())

    # ═══ ДОНАТ ═══
    @dp.message(F.text == "🏪 Донат")
    async def donate_btn(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"🏪 <b>ДОНАТ</b>\n━━━━━━━━━━━━━━\n\n💱 Курс: <b>1 ⭐ = {rate:,} Tokens</b>\n\n✨ Выбери пакет 👇", parse_mode="HTML", reply_markup=donate_menu())

    # ═══ ПОКУПКА ПАКЕТОВ ═══
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

    # ═══ СВОЯ СУММА ═══
    @dp.message(F.text == "💎 Своя сумма")
    async def custom_sum_start(message: Message, state: FSMContext):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(
            message,
            "💳 <b>СВОЯ СУММА</b>\n━━━━━━━━━━━━━━\n\n"
            "Введи количество Stars от 1 до 10000.\n"
            f"Курс: <b>1 ⭐ = {rate:,} Tokens</b>.\n\n"
            "Пример: <code>10</code> ⭐ = <b>75 000</b> Tokens.",
            parse_mode="HTML"
        )
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
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐ Оплатить", callback_data=f"pay_custom_{stars}_{tokens}")]
                ])
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

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await send_clean(message, "✨ Главное меню 👇", reply_markup=main_menu())

    # ═══ ОПЛАТА ═══
    @dp.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        
        if payload.startswith("custom_"):
            parts = payload.split("_")
            amount = int(parts[2])
        else:
            amount = {
                "donate_50k": 50000, 
                "donate_150k": 150000, 
                "donate_300k": 300000, 
                "donate_1m": 1000000, 
                "donate_2m": 2000000
            }.get(payload, 0)
            
        if amount > 0:
            set_balance(message.from_user.id, amount)
            await message.answer(
                f"✅ <b>ОПЛАТА УСПЕШНА!</b>\n━━━━━━━━━━━━━━\n\n"
                f"💰 Зачислено: <b>+{fmt_num(amount)} Tokens</b>\n\n"
                "✨ Спасибо за поддержку! 🖤",
                parse_mode="HTML"
            )