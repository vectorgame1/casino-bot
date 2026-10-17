# support.py
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, SUPPORT_USERNAME, BOT_NAME
from keyboards import support_menu, main_menu

class SupportStates(StatesGroup):
    waiting_question = State()

admin_replies = {}

def register(dp: Dispatcher):

    # Вызывается из handlers.py
    async def open_support(message: Message):
        await message.answer(
            "🆘 <b>Поддержка</b>\n\nВыбери тему 👇",
            parse_mode="HTML",
            reply_markup=support_menu()
        )

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message):
        await message.answer(
            "💎 <b>Tokens не пришли</b>\n\n"
            "Спокойно, сейчас разберёмся.\n\n"
            "Проверь:\n"
            "1. Оплата точно прошла?\n"
            "2. Прошло больше 5 минут?\n"
            "3. Перезапусти бота командой /start\n\n"
            f"Если нет — напиши оператору: {SUPPORT_USERNAME}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message):
        await message.answer(
            "🎮 <b>Что-то сломалось в игре</b>\n\n"
            "Опиши:\n1. Какая игра\n2. Что делал\n3. Что пошло не так\n\n"
            "Передам разработчику.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message):
        await message.answer(
            "💳 <b>Вопрос по оплате</b>\n\n"
            "• Оплата через Telegram Stars\n"
            "• Tokens зачисляются автоматически\n"
            "• Возврат — через поддержку Telegram\n\n"
            f"Вопросы: {SUPPORT_USERNAME}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message):
        await message.answer(
            "🚫 <b>Бан или мут</b>\n\n"
            "Если считаешь наказание ошибкой:\n"
            "• @username\n• Причина\n• Когда случилось",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message):
        await message.answer(
            "🐞 <b>Нашёл баг</b>\n\n"
            "Опиши:\n1. Что делал\n2. Что случилось\n3. Скрин",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message):
        await message.answer(
            f"📜 <b>Правила {BOT_NAME}</b>\n\n"
            "1. Бот только игровой\n"
            "2. Tokens не выводятся\n"
            "3. 18+\n"
            "4. Мультиаккаунты запрещены",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    @dp.message(F.text == "✍️ Свой вопрос")
    async def own_question(message: Message, state: FSMContext):
        await message.answer(
            "✍️ <b>Свой вопрос</b>\n\nНапиши свой вопрос одним сообщением.",
            parse_mode="HTML"
        )
        await state.set_state(SupportStates.waiting_question)

    @dp.message(SupportStates.waiting_question)
    async def forward_to_admin(message: Message, state: FSMContext):
        username = f"@{message.from_user.username}" if message.from_user.username else "без username"
        admin_msg = await dp.bot.send_message(
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
        if not user_id:
            return
        await dp.bot.send_message(
            user_id,
            f"📩 <b>Ответ поддержки:</b>\n\n«{message.text}»\n\n— Команда {BOT_NAME}",
            parse_mode="HTML"
        )
        await message.answer("✅ Отправлено игроку.")