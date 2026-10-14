# ═══════════════════════════════════════════════════════════════
# admin/moderation.py — МОДЕРАЦИЯ (ВСЁ ЧЕРЕЗ ДИАЛОГИ)
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from config import ADMIN_ID
from admin.menu import admin_moderation_kb, admin_main_kb
from admin.states import MuteStates, WarnStates, BanStates


def register(dp: Dispatcher):

    # ═══ ГЛАВНОЕ МЕНЮ МОДЕРАЦИИ ═══

    @dp.message(lambda m: m.text == "🛡️ Модерация" and m.from_user.id == ADMIN_ID)
    async def mod_menu(message: Message):
        await message.answer(
            "🛡️ <b>МОДЕРАЦИЯ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=admin_moderation_kb()
        )

    # ═══ НАЗАД В АДМИН ═══

    @dp.message(lambda m: m.text == "🔙 Назад в админ" and m.from_user.id == ADMIN_ID)
    async def back_to_admin(message: Message):
        await message.answer(
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_main_kb()
        )

    # ═══ БАН — ДИАЛОГ ═══

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

    # ═══ МУТ — ДИАЛОГ ═══

    @dp.message(lambda m: m.text == "🔇 Мут" and m.from_user.id == ADMIN_ID)
    async def mute_start(message: Message, state: FSMContext):
        await state.set_state(MuteStates.username)
        await message.answer(
            "🔇 <b>МУТ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👤 Введи @username или ID игрока:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    # ═══ ВАРН — ДИАЛОГ ═══

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

    # ═══ РАЗБАН — ПОДСКАЗКА ═══

    @dp.message(lambda m: m.text == "✅ Разбан" and m.from_user.id == ADMIN_ID)
    async def unban_hint(message: Message):
        await message.answer(
            "✅ <b>РАЗБАН</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/unban @username</code>\n"
            "Или ответь на сообщение игрока и напиши <code>/unban</code>",
            parse_mode="HTML"
        )

    # ═══ РАЗМУТ — ПОДСКАЗКА ═══

    @dp.message(lambda m: m.text == "🔊 Размут" and m.from_user.id == ADMIN_ID)
    async def unmute_hint(message: Message):
        await message.answer(
            "🔊 <b>РАЗМУТ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/unmute @username</code>\n"
            "Или ответь на сообщение игрока и напиши <code>/unmute</code>",
            parse_mode="HTML"
        )

    # ═══ ВАРНЫ — ПОДСКАЗКА ═══

    @dp.message(lambda m: m.text == "📋 Варны" and m.from_user.id == ADMIN_ID)
    async def warns_hint(message: Message):
        await message.answer(
            "📋 <b>ВАРНЫ ИГРОКА</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/warns @username</code>\n"
            "Или ответь на сообщение игрока и напиши <code>/warns</code>",
            parse_mode="HTML"
        )

    # ═══ СПИСОК БАНОВ ═══

    @dp.message(lambda m: m.text == "📋 Список банов" and m.from_user.id == ADMIN_ID)
    async def bans_hint(message: Message):
        await message.answer(
            "📋 <b>СПИСОК БАНОВ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/bans</code>",
            parse_mode="HTML"
        )

    # ═══ ИСТОРИЯ БАНОВ ═══

    @dp.message(lambda m: m.text == "📜 История банов" and m.from_user.id == ADMIN_ID)
    async def banhistory_hint(message: Message):
        await message.answer(
            "📜 <b>ИСТОРИЯ БАНОВ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "Напиши: <code>/banhistory @username</code>\n"
            "Или ответь на сообщение игрока и напиши <code>/banhistory</code>",
            parse_mode="HTML"
        )

    # ═══ ОТМЕНА ДИАЛОГА ═══

    @dp.message(lambda m: m.text == "/cancel" and m.from_user.id == ADMIN_ID)
    async def cancel_dialog(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(
            "❌ Отменено",
            reply_markup=admin_moderation_kb()
        )