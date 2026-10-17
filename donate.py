# ═══════════════════════════════════════════════════════════════
# donate.py — ДОНАТ-МАГАЗИН (только Tokens)
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import STARS_RATE, STARS_MIN, STARS_MAX, TOKENS_PACKS
from keyboards import donate_menu, main_menu
from database import get_rate, set_balance, get_balance


class DonateStates(StatesGroup):
    custom_amount = State()


def register(dp: Dispatcher):

    @dp.message(F.text == "🏪 Донат")
    async def donate_main(message: Message):
        rate = get_rate("stars_rate", STARS_RATE)
        await message.answer(
            "🏪 <b>Донат-магазин</b>\n\n"
            f"💱 Курс: 1 ⭐ = {rate:,} Tokens\n\n"
            "Выбери пакет 👇",
            parse_mode="HTML",
            reply_markup=donate_menu()
        )

    # ── Пакеты ──

    for tokens, stars in TOKENS_PACKS:
        @dp.message(F.text == f"💎 {tokens:,} Tokens — {stars} ⭐".replace(",", " "))
        async def buy_pack(message: Message, _t=tokens, _s=stars):
            await dp.bot.send_invoice(
                chat_id=message.from_user.id,
                title=f"💎 {_t:,} Tokens",
                description=f"Покупка {_t:,} Tokens за {_s} Stars",
                payload=f"donate_{_s}_{_t}",
                currency="XTR",
                prices=[LabeledPrice(label=f"{_t:,} Tokens", amount=_s)],
            )

    # ── Своя сумма ──

    @dp.message(F.text == "💎 Своя сумма")
    async def custom_start(message: Message, state: FSMContext):
        rate = get_rate("stars_rate", STARS_RATE)
        await message.answer(
            "💳 <b>Своя сумма</b>\n\n"
            f"⭐ Введи количество Stars:\n"
            f"От <b>{STARS_MIN}</b> до <b>{STARS_MAX}</b>\n\n"
            f"💱 Курс: 1 ⭐ = {rate:,} Tokens\n\n"
            f"Пример: <b>10</b> ⭐ = <b>{10 * rate:,}</b> Tokens\n\n"
            "👇 Напиши число:",
            parse_mode="HTML"
        )
        await state.set_state(DonateStates.custom_amount)

    @dp.message(DonateStates.custom_amount)
    async def custom_amount(message: Message, state: FSMContext):
        try:
            stars = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Введи число:")
            return

        if stars < STARS_MIN or stars > STARS_MAX:
            await message.answer(f"❌ От {STARS_MIN} до {STARS_MAX}:")
            return

        rate = get_rate("stars_rate", STARS_RATE)
        tokens = stars * rate
        await state.clear()

        await dp.bot.send_invoice(
            chat_id=message.from_user.id,
            title=f"💎 {tokens:,} Tokens",
            description=f"Покупка {tokens:,} Tokens за {stars} Stars",
            payload=f"donate_{stars}_{tokens}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{tokens:,} Tokens", amount=stars)],
        )