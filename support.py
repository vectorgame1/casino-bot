# support.py
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID, BOT_NAME, SUPPORT_USERNAME
from keyboards import support_menu, main_menu

# Стейт для ожидания вопроса от игрока
class SupportStates(StatesGroup):
    waiting_question = State()

# Словарь для связи сообщения админа и ID игрока
# {message_id_у_админа: user_id_игрока}
admin_replies = {}

def register(dp: Dispatcher):

    # ═══ ГЛАВНОЕ МЕНЮ ПОДДЕРЖКИ ═══
    @dp.message(F.text.in_({"🆘 Помощь", "🆘 Поддержка"}))
    async def support_main(message: Message):
        await message.answer(
            "🆘 <b>Поддержка</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Выбери тему — я сразу отвечу.\n"
            "Если не найдёшь ответ, напиши свой вопрос, и я передам его оператору.",
            parse_mode="HTML",
            reply_markup=support_menu()
        )

    # ═══ ТЕМЫ ПОДДЕРЖКИ ═══
    @dp.message(F.text == "💎 Tokens не пришли")
    async def tokens_lost(message: Message):
        txt = (
            "💎 <b>Tokens не пришли</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Спокойно, сейчас разберёмся.\n\n"
            "1️⃣ Проверь, прошла ли оплата (зайди в настройки Telegram -> Мои подарки).\n"
            "2️⃣ Подожди 5 минут (иногда бывает задержка).\n"
            "3️⃣ Перезапусти бота командой /start.\n\n"
            "Если токены всё равно не пришли — напиши в поддержку сюда:\n"
            "• Скриншот оплаты\n"
            "• Сколько звезд отправил\n"
            "• Примерное время\n\n"
            "Мы всё вернём! 🙏"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    @dp.message(F.text == "🎮 Что-то сломалось в игре")
    async def game_broken(message: Message):
        txt = (
            "🎮 <b>Что-то сломалось в игре</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Опиши проблему, и мы починим это как можно скорее!\n\n"
            "Пожалуйста, укажи:\n"
            "• В какой игре произошла ошибка\n"
            "• Что ты делал (какую команду вводил)\n"
            "• Что пошло не так\n\n"
            "Если есть скриншот — пришли его сюда. Это ускорит починку! 🛠️"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    @dp.message(F.text == "💳 Вопрос по оплате")
    async def payment_q(message: Message):
        txt = (
            "💳 <b>Вопрос по оплате</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Все покупки проходят через Telegram Stars ⭐.\n\n"
            "• Токены зачисляются автоматически.\n"
            "• Если что-то не пришло — см. пункт «Tokens не пришли».\n"
            "• Возврат средств возможен только через поддержку Telegram (в настройках платежей).\n\n"
            "Если что-то неясно — напиши свой вопрос ниже. ✍️"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    @dp.message(F.text == "🚫 Бан или мут")
    async def ban_mute(message: Message):
        txt = (
            "🚫 <b>Бан или мут</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Если ты считаешь, что наказание было ошибочным, мы разберёмся.\n\n"
            "Пришли нам:\n"
            "• Твой @username\n"
            "• Причину блокировки (если знаешь)\n"
            "• Примерное время, когда это случилось\n\n"
            "Мы проверим логи и снимем бан, если он был выдан по ошибке. 🤝"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    @dp.message(F.text == "🐞 Нашёл баг")
    async def bug_found(message: Message):
        txt = (
            "🐞 <b>Нашёл баг</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Спасибо, что помогаешь делать бота лучше!\n\n"
            "Опиши баг максимально подробно:\n"
            "1️⃣ Что ты делал (по шагам)\n"
            "2️⃣ Что ожидал увидеть\n"
            "3️⃣ Что случилось на самом деле\n\n"
            "Пришли скриншот или текст ошибки. За подтверждённый баг — бонус Tokens! 🎁"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    @dp.message(F.text == "📜 Правила бота")
    async def rules(message: Message):
        txt = (
            "📜 <b>Правила Gold Casino</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "1. Бот создан исключительно в развлекательных целях. Реальных ставок нет.\n"
            "2. Виртуальные Tokens не подлежат выводу или обмену на реальные деньги.\n"
            "3. Игра разрешена только пользователям 18+.\n"
            "4. Запрещены: мультиаккаунтинг, использование багов, мошенничество.\n"
            "5. Донат — это добровольная поддержка проекта, а не инвестиция.\n\n"
            "Нарушение правил ведет к бану без предупреждения. 🚫"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=support_menu())

    # ═══ СВОЙ ВОПРОС (ПЕРЕСЫЛКА АДМИНУ) ═══
    @dp.message(F.text == "✍️ Свой вопрос")
    async def own_question(message: Message, state: FSMContext):
        await message.answer(
            "✍️ <b>Свой вопрос</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Напиши свой вопрос одним сообщением.\n"
            "Оператор ответит тебе в течение 24 часов.",
            parse_mode="HTML"
        )
        await state.set_state(SupportStates.waiting_question)

    @dp.message(SupportStates.waiting_question)
    async def forward_to_admin(message: Message, state: FSMContext):
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
        
        # Отправляем сообщение тебе (Админу)
        admin_msg = await message.bot.send_message(
            ADMIN_ID,
            f"📩 <b>Новое сообщение в поддержку</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 От: {username}\n\n"
            f"💬 Текст:\n«{message.text}»\n\n"
            f"↩️ <i>Чтобы ответить, нажми Reply (Ответить) на это сообщение.</i>",
            parse_mode="HTML"
        )
        
        # Запоминаем, что этот message_id принадлежит этому игроку
        admin_replies[admin_msg.message_id] = message.from_user.id
        
        await message.answer(
            "✅ <b>Вопрос отправлен!</b>\n\nОператор ответит тебе сюда в ближайшее время.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        await state.clear()

    # ═══ ОТВЕТ ОТ АДМИНА ИГРОКУ ═══
    @dp.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
    async def admin_reply(message: Message):
        # Проверяем, есть ли ID сообщения в словаре
        reply_id = message.reply_to_message.message_id
        user_id = admin_replies.get(reply_id)
        
        if not user_id:
            return # Если это просто ответ на обычное сообщение, игнорируем
            
        try:
            await message.bot.send_message(
                user_id,
                f"📩 <b>Ответ поддержки:</b>\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"«{message.text}»\n\n"
                f"— Команда {BOT_NAME}",
                parse_mode="HTML"
            )
            await message.answer("✅ <b>Ответ успешно отправлен игроку!</b>")
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке: {e}")

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await message.answer("Главное меню 👇", reply_markup=main_menu())