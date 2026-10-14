# ═══════════════════════════════════════════════════════════════
# admin/moderation.py — МОДЕРАЦИЯ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.types import Message

from config import ADMIN_ID
from admin.menu import admin_moderation_kb, admin_main_kb


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
        from admin.states import BanStates
        await state.set_state(BanStates.username)
        await message.answer(
            "🚫 <b>БАН</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👤 Введи @username или ID:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "✅ Разбан" and m.from_user.id == ADMIN_ID)
    async def unban_hint(message: Message):
        await message.answer(
            "✅ <b>РАЗБАН</b>\n\n"
            "Напиши: <code>/unban @username</code>",
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