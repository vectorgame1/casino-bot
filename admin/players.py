# ═══════════════════════════════════════════════════════════════
# admin/players.py — ОБРАБОТЧИКИ РАЗДЕЛА "ИГРОКИ"
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.types import Message

from config import ADMIN_ID
from admin.menu import admin_players_kb, admin_main_kb


def register(dp: Dispatcher):
    """Регистрирует обработчики Reply-кнопок раздела Игроки."""

    @dp.message(lambda m: m.text == "👥 Игроки" and m.from_user.id == ADMIN_ID)
    async def players_menu(message: Message):
        await message.answer(
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=admin_players_kb()
        )

    @dp.message(lambda m: m.text == "🔙 Назад в админ" and m.from_user.id == ADMIN_ID)
    async def back_to_admin(message: Message):
        await message.answer(
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_main_kb()
        )