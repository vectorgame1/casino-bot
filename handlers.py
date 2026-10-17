# handlers.py
from aiogram import Dispatcher, F
from aiogram.types import Message, LabeledPrice
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_NAME, START_BONUS, STARS_RATE, ADMIN_ID, GROUP_URL, SUPPORT_USERNAME
from keyboards import main_menu, games_menu, donate_menu, support_menu
from database import (
    get_balance, get_rate, set_rate, ensure_user, 
    check_and_give_bonus, is_banned, get_top, get_xp
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name

class SupportStates(StatesGroup):
    waiting_question = State()

admin_replies = {}

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

    # ═══ ПОДДЕРЖКА ═══
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def help_menu(message: Message):
        await send_clean(
            message,
            "🆘 <b>Поддержка</b>\n\nВыбери тему 👇",
            parse_mode="HTML",
            reply_markup=support_menu()
        )

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await send_clean(message, "Главное меню 👇", reply_markup=main_menu())

    # ═══ АДМИН: КУРС ═══
    @dp.message(Command("курс"))
    async def change_rate(message: Message):
        if message.from_user.id != ADMIN_ID: return
        args = message.text.split()
        if len(args) == 1:
            rate = get_rate("stars_rate", STARS_RATE)
            await message.answer(f"💱 Текущий курс: 1 ⭐ = {rate:,} Tokens\n\nИзменить: <code>/курс 8000</code>", parse_mode="HTML")
            return
        try:
            new_rate = int(args[1])
            set_rate("stars_rate", new_rate)
            await message.answer(f"✅ Новый курс: 1 ⭐ = {new_rate:,} Tokens")
        except ValueError:
            await message.answer("❌ Формат: /курс 8000")

    # ═══ ПОДДЕРЖКА: СВОЙ ВОПРОС ═══
    @dp.message(F.text == "✍️ Свой вопрос")
    async def own_question(message: Message, state: FSMContext):
        await message.answer("✍️ <b>Свой вопрос</b>\n\nНапиши свой вопрос одним сообщением.", parse_mode="HTML")
        await state.set_state(SupportStates.waiting_question)

    @dp.message(SupportStates.waiting_question)
    async def forward_to_admin(message: Message, state: FSMContext):
        username = f"@{message.from_user.username}" if message.from_user.username else "без username"
        admin_msg = await message.bot.send_message(
            ADMIN_ID,
            f"📩 <b>Новое сообщение в поддержку</b>\n\n"
            f"👤 {username} (ID: <code>{message.from_user.id}</code>)\n\n"
            f"💬 Сообщение:\n«{message.text}»\n\n"
            f"↩️ Ответить: reply на это сообщение.",
            parse_mode="HTML"
        )
        admin_replies[admin_msg.message_id] = message.from_user.id
        await message.answer("✅ Передал оператору. Ответ придёт сюда.", reply_markup=main_menu())
        await state.clear()

    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply(message: Message):
        reply_id = message.reply_to_message.message_id
        user_id = admin_replies.get(reply_id)
        if not user_id: return
        await message.bot.send_message(
            user_id,
            f"📩 <b>Ответ поддержки:</b>\n\n«{message.text}»\n\n— Команда {BOT_NAME}",
            parse_mode="HTML"
        )
        await message.answer("✅ Отправлено игроку.")