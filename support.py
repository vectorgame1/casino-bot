# ═══════════════════════════════════════════════════════════════
# support.py — ПОДДЕРЖКА
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, SUPPORT_USERNAME, BOT_NAME
from keyboards import support_menu, main_menu


class SupportStates(StatesGroup):
    waiting_question = State()


# message_id сообщения у админа → user_id игрока
admin_replies = {}


def register(dp: Dispatcher):

    @dp.message(F.text == "🆘 Поддержка")
    async def support_main(message: Message):
        await message.answer(
            "🆘 <b>Поддержка</b>\n\n"
            "Выбери тему — отвечу сразу.\n"
            "Если не найдёшь ответ — напиши вопрос, передам оператору.",
            parse_mode="HTML",
            reply_markup=support_menu()
        )

    # ── Готовые ответы ──

    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message):
        await message.answer(
            "💎 <b>Tokens не пришли</b>\n\n"
            "Спокойно, сейчас разберёмся.\n\n"
            "Проверь:\n"
            "1. Оплата точно прошла? (скрин из Telegram)\n"
            "2. Прошло больше 5 минут?\n"
            "3. Перезапусти бота командой /start\n\n"
            "Если Tokens всё равно нет — напиши:\n"
            "• Сколько Stars оплатил\n"
            "• Примерное время оплаты\n"
            "• Скрин чека\n\n"
            f"Оператор: {SUPPORT_USERNAME}",
            parse_mode="HTML"
        )

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message):
        await message.answer(
            "🎮 <b>Что-то сломалось в игре</b>\n\n"
            "Опиши:\n"
            "1. Какая игра\n"
            "2. Что делал\n"
            "3. Что пошло не так\n"
            "4. Скрин, если есть\n\n"
            "Передам разработчику. Обычно чиним за 1–2 дня.",
            parse_mode="HTML"
        )

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message):
        await message.answer(
            "💳 <b>Вопрос по оплате</b>\n\n"
            "• Оплата через Telegram Stars\n"
            "• Tokens зачисляются автоматически\n"
            "• Возврат — только через поддержку Telegram\n\n"
            f"Если что-то неясно — напиши: {SUPPORT_USERNAME}",
            parse_mode="HTML"
        )

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message):
        await message.answer(
            "🚫 <b>Бан или мут</b>\n\n"
            "Если считаешь наказание ошибкой:\n"
            "• @username\n"
            "• Причина (если знаешь)\n"
            "• Когда случилось\n\n"
            "Разберёмся в течение 24 часов.",
            parse_mode="HTML"
        )

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message):
        await message.answer(
            "🐞 <b>Нашёл баг</b>\n\n"
            "Спасибо, что сообщаешь!\n"
            "Опиши:\n"
            "1. Что делал\n"
            "2. Что ожидал\n"
            "3. Что случилось\n"
            "4. Скрин / текст ошибки\n\n"
            "За реальный баг — бонус Tokens.",
            parse_mode="HTML"
        )

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message):
        await message.answer(
            f"📜 <b>Правила {BOT_NAME}</b>\n\n"
            "1. Бот только игровой, реальных ставок нет\n"
            "2. Tokens — виртуальные, не выводятся\n"
            "3. 18+\n"
            "4. Запрещены: мультиаккаунты, читы, скам\n"
            "5. Донат — добровольный\n"
            "6. Админ всегда прав\n\n"
            "Нарушение → бан без предупреждения.",
            parse_mode="HTML"
        )

    # ── Свой вопрос → пересылка админу ──

    @dp.message(F.text == "✍️ Свой вопрос")
    async def own_question(message: Message, state: FSMContext):
        await message.answer(
            "✍️ <b>Свой вопрос</b>\n\n"
            "Напиши свой вопрос одним сообщением.\n"
            "Оператор ответит в течение 24 часов.\n\n"
            "Если срочно — напиши «СРОЧНО» в начале.",
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
        await message.answer(
            "✅ Передал оператору. Ответ придёт сюда.",
            reply_markup=main_menu()
        )
        await state.clear()

    # ── Ответ админа → игроку ──

    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply(message: Message):
        reply_id = message.reply_to_message.message_id
        user_id = admin_replies.get(reply_id)
        if not user_id:
            return
        await dp.bot.send_message(
            user_id,
            f"📩 <b>Ответ поддержки:</b>\n\n"
            f"«{message.text}»\n\n"
            f"— Команда {BOT_NAME}",
            parse_mode="HTML"
        )
        await message.answer("✅ Отправлено игроку.")

    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await message.answer("Главное меню 👇", reply_markup=main_menu())