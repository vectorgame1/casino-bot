# ═══════════════════════════════════════════════════════════════
# admin/moderation.py — МОДЕРАЦИЯ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.types import Message
from aiogram.fsm.context import FSMContext  

from config import ADMIN_ID
from admin.menu import admin_moderation_kb, admin_main_kb
from admin.states import MuteStates, WarnStates, BanStates


def register(dp: Dispatcher):

    @dp.message(lambda m: m.text == "🛡️ Модерация" and m.from_user.id == ADMIN_ID)
    async def mod_menu(message: Message):
        await message.answer(
            "🛡️ <b>МОДЕРАЦИЯ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=admin_moderation_kb()
        )

    @dp.message(lambda m: m.text == "🚫 Бан" and m.from_user.id == ADMIN_ID)
    async def ban_start(message: Message, state: FSMContext):
        await state.set_state(BanStates.username)
        await message.answer(
            "🚫 <b>БАН</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👤 Введи @username или ID игрока:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "✅ Разбан" and m.from_user.id == ADMIN_ID)
    async def unban_start(message: Message, state: FSMContext):
        await message.answer(
            "✅ <b>РАЗБАН</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/unban @username</code>\n"
            "Или ответь на сообщение игрока.",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "🔇 Мут" and m.from_user.id == ADMIN_ID)
    async def mute_hint(message: Message):
        await message.answer(
            "🔇 <b>МУТ</b>\n\n"
            "Напиши: <code>/mute @username 1h причина</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📋 Список банов" and m.from_user.id == ADMIN_ID)
    async def bans_list(message: Message):
        await message.answer(
            "📋 <b>СПИСОК БАНОВ</b>\n\n"
            "Напиши: <code>/bans</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📜 История банов" and m.from_user.id == ADMIN_ID)
    async def ban_history(message: Message):
        await message.answer(
            "📜 <b>ИСТОРИЯ БАНОВ</b>\n\n"
            "Напиши: <code>/banhistory @username</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "⚠️ Варн" and m.from_user.id == ADMIN_ID)
    async def warn_start(message: Message, state: FSMContext):
        await state.set_state(WarnStates.username)
        await message.answer(
            "⚠️ <b>ВАРН</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👤 Введи @username или ID игрока:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "🔊 Размут" and m.from_user.id == ADMIN_ID)
    async def unmute_start(message: Message, state: FSMContext):
        await message.answer(
            "🔊 <b>РАЗМУТ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/unmute @username</code>\n"
            "Или ответь на сообщение игрока.",
            parse_mode="HTML"
        )
    @dp.message(lambda m: m.text == "📋 Варны" and m.from_user.id == ADMIN_ID)
    async def warns_start(message: Message):
        await message.answer(
            "📋 <b>ВАРНЫ ИГРОКА</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/warns @username</code>\n"
            "Или ответь на сообщение игрока.",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📋 Список банов" and m.from_user.id == ADMIN_ID)
    async def bans_start(message: Message):
        await message.answer(
            "📋 <b>СПИСОК БАНОВ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/bans</code>",
            parse_mode="HTML"
        )
    @dp.message(lambda m: m.text == "📜 История банов" and m.from_user.id == ADMIN_ID)
    async def banhistory_start(message: Message):
        await message.answer(
            "📜 <b>ИСТОРИЯ БАНОВ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/banhistory @username</code>",
            parse_mode="HTML"
        )