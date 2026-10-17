from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command
from config import BOT_NAME, START_BONUS, STARS_RATE, GROUP_URL, ADMIN_ID
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb
from database import get_balance, get_rate, ensure_user, check_and_give_bonus, is_banned, get_top, get_xp, set_balance
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

def register(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        ensure_user(user_id, username)
        if is_banned(user_id):
            await send_clean(message, "🚫 <b>ДОСТУП ЗАКРЫТ</b>\n\nОбратитесь в поддержку: @vctorw", parse_mode="HTML")
            return
        is_new = check_and_give_bonus(user_id, START_BONUS)
        bonus_text = f"🎁 Твой стартовый бонус: <b>+{START_BONUS:,} Tokens</b>\n\n" if is_new else ""
        await send_clean(message, f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n━━━━━━━━━━━━━━\n\n💎 Здесь только виртуальные Tokens.\n🎰 Реальных ставок нет (18+).\n\n{bonus_text}✨ Выбери, с чего начнём 👇", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(F.text == "💰 Баланс")
    async def balance(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(message, f"💎 <b>ТВОЙ БАЛАНС</b>\n━━━━━━━━━━━━━━\n\n💰 Tokens: <b>{fmt_num(bal)}</b>\n\n✨ Пополни в Донате!", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(F.text == "👤 Профиль")
    async def profile(message: Message):
        user_id = message.from_user.id
        bal, xp = get_balance(user_id), get_xp(user_id)
        level = xp // 100
        rank, bar = get_rank_name(level), make_xp_bar(xp)
        await send_clean(message, f"👤 <b>ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━\n\n🎖 <b>Ранг:</b> {rank}\n📊 <b>Опыт:</b> {xp} / {(level+1)*100} XP\n<code>{bar}</code>\n\n💎 <b>Баланс:</b> {fmt_num(bal)} Tokens", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(F.text == "🏆 Топ")
    async def top(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ЗАЛ СЛАВЫ</b>\n━━━━━━━━━━━━━━\n\n"
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"<b>{i+1}.</b>"
            txt += f"{medal} <b>{uname or f'user_{uid}'}</b> — {fmt_num(bal)} Tokens\n"
        await send_clean(message, txt, parse_mode="HTML", reply_markup=main_menu())

    @dp.message(F.text == "🎰 Игры")
    async def games(message: Message):
        if message.chat.type == "private":
            await send_clean(message, f"🎰 <b>ИГРЫ В ГРУППЕ</b>\n\n👇 Переходи: {GROUP_URL}", parse_mode="HTML", reply_markup=main_menu())
        else:
            await send_clean(message, "🎰 <b>Выбирай:</b>", parse_mode="HTML", reply_markup=games_menu())

    @dp.message(F.text == "🏪 Донат")
    async def donate_btn(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(message, f"🏪 <b>ДОНАТ</b>\n━━━━━━━━━━━━━━\n\n💱 Курс: <b>1 ⭐ = {rate:,} Tokens</b>\n\n✨ Выбери пакет 👇", parse_mode="HTML", reply_markup=donate_menu())

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

    @dp.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def success_pay(message: Message):
        payload = message.successful_payment.invoice_payload
        amount = {"donate_50k": 50000, "donate_150k": 150000, "donate_300k": 300000, "donate_1m": 1000000, "donate_2m": 2000000}.get(payload, 0)
        if amount > 0:
            set_balance(message.from_user.id, amount)
            await message.answer(f"✅ <b>ОПЛАТА УСПЕШНА!</b>\n\nЗачислено <b>+{fmt_num(amount)} Tokens</b>", parse_mode="HTML")