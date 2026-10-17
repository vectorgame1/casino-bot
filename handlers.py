# handlers.py
from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command

from config import BOT_NAME, START_BONUS, STARS_RATE, GROUP_URL, ADMIN_ID
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb
from database import (
    get_balance, get_rate, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp, set_balance
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

def register(dp: Dispatcher):

    # ═══ СТАРТ ═══
    @dp.message(Command("start"))
    async def start(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        ensure_user(user_id, username)
        
        if is_banned(user_id):
            await send_clean(message, "🚫 <b>Вы заблокированы</b>\nОбратитесь к @vctorw", parse_mode="HTML")
            return
            
        is_new = check_and_give_bonus(user_id, START_BONUS)
        bonus_text = f"🎁 Тебе подарок: <b>{START_BONUS:,} Tokens</b>\n\n" if is_new else ""
        
        await send_clean(
            message,
            f"🎰 <b>Добро пожаловать в {BOT_NAME}</b>\n\n"
            "Это игровой бот. Здесь только виртуальные Tokens, "
            "реальных ставок нет.\n"
            "Играй ответственно, 18+.\n"
            "Донат — добровольная поддержка проекта.\n\n"
            f"{bonus_text}"
            "Выбери, с чего начнём 👇",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    # ═══ БАЛАНС ═══
    @dp.message(F.text == "💰 Баланс")
    async def balance(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(
            message,
            f"💰 <b>Баланс</b>\n\n💎 Tokens: <b>{fmt_num(bal)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    # ═══ ПРОФИЛЬ ═══
    @dp.message(F.text == "👤 Профиль")
    async def profile(message: Message):
        user_id = message.from_user.id
        bal = get_balance(user_id)
        xp = get_xp(user_id)
        level = xp // 100
        rank = get_rank_name(level)
        bar = make_xp_bar(xp)
        
        await send_clean(
            message,
            f"👤 <b>Профиль</b>\n\n"
            f"🎖 Ранг: <b>{rank}</b>\n"
            f"📊 Опыт: <b>{xp} / {(level+1)*100} XP</b>\n"
            f"{bar}\n\n"
            f"💎 Баланс: <b>{fmt_num(bal)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    # ═══ ТОП ═══
    @dp.message(F.text == "🏆 Топ")
    async def top(message: Message):
        rows = get_top(10)
        txt = "🏆 <b>ТОП ИГРОКОВ</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            txt += f"{medal} <b>{uname or f'user_{uid}'}</b> — {fmt_num(bal)} Tokens\n"
        
        await send_clean(message, txt, parse_mode="HTML", reply_markup=main_menu())

    # ═══ ИГРЫ ═══
    @dp.message(F.text == "🎰 Игры")
    async def games(message: Message):
        if message.chat.type == "private":
            await send_clean(
                message,
                f"🎰 <b>Игры доступны только в группе!</b>\n\n👇 Переходи и играй: {GROUP_URL}",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
        else:
            await send_clean(
                message,
                "🎰 <b>Игры</b>\n\nВыбери игру 👇",
                parse_mode="HTML",
                reply_markup=games_menu()
            )

    # ═══ ДОНАТ ═══
    @dp.message(F.text == "🏪 Донат")
    async def donate_btn(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await send_clean(
            message,
            "🏪 <b>Донат-магазин</b>\n\n"
            f"💱 Курс: 1 ⭐ = {rate:,} Tokens\n\n"
            "Выбери пакет 👇",
            parse_mode="HTML",
            reply_markup=donate_menu()
        )

    # ═══ ПОКУПКА ПАКЕТОВ ═══
    @dp.message(F.text == "💎 50 000 Tokens — 7 ⭐")
    async def buy_50k(message: Message):
        await message.answer_invoice(
            title="💎 50 000 Tokens", description="Покупка 50 000 Tokens",
            payload="donate_50k", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="50 000 Tokens", amount=7)]
        )

    @dp.message(F.text == "💎 150 000 Tokens — 20 ⭐")
    async def buy_150k(message: Message):
        await message.answer_invoice(
            title="💎 150 000 Tokens", description="Покупка 150 000 Tokens",
            payload="donate_150k", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="150 000 Tokens", amount=20)]
        )

    @dp.message(F.text == "💎 300 000 Tokens — 40 ⭐")
    async def buy_300k(message: Message):
        await message.answer_invoice(
            title="💎 300 000 Tokens", description="Покупка 300 000 Tokens",
            payload="donate_300k", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="300 000 Tokens", amount=40)]
        )

    @dp.message(F.text == "💎 1 000 000 Tokens — 125 ⭐")
    async def buy_1m(message: Message):
        await message.answer_invoice(
            title="💎 1 000 000 Tokens", description="Покупка 1 000 000 Tokens",
            payload="donate_1m", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="1 000 000 Tokens", amount=125)]
        )

    @dp.message(F.text == "💎 2 000 000 Tokens — 265 ⭐")
    async def buy_2m(message: Message):
        await message.answer_invoice(
            title="💎 2 000 000 Tokens", description="Покупка 2 000 000 Tokens",
            payload="donate_2m", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="2 000 000 Tokens", amount=265)]
        )

    @dp.message(F.text == "💎 Своя сумма")
    async def custom_sum(message: Message):
        await send_clean(
            message,
            "💳 <b>Своя сумма</b>\n\nВведи количество Stars от 1 до 10000.\nКурс: 1 ⭐ = 7 500 Tokens.\n\nПример: <code>10</code> ⭐ = <b>75 000</b> Tokens.",
            parse_mode="HTML"
        )

    # ═══ АДМИН-ПАНЕЛЬ (Reply) ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean(
            message,
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_panel_kb()
        )

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await send_clean(message, "Главное меню 👇", reply_markup=main_menu())

    # ═══ ОПЛАТА (PRE-CHECKOUT И УСПЕШНАЯ ОПЛАТА) ═══
    @dp.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def successful_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        amount = 0
        if payload == "donate_50k": amount = 50_000
        elif payload == "donate_150k": amount = 150_000
        elif payload == "donate_300k": amount = 300_000
        elif payload == "donate_1m": amount = 1_000_000
        elif payload == "donate_2m": amount = 2_000_000
        
        if amount > 0:
            set_balance(message.from_user.id, amount)
            await message.answer(f"✅ <b>Оплата прошла!</b>\n\nЗачислено <b>{fmt_num(amount)}</b> Tokens.", parse_mode="HTML")