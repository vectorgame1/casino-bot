# admin_panel.py
from aiogram import Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import ADMIN_ID, BOT_NAME
from keyboards import admin_panel_kb
from database import get_user_id_by_username, set_balance, set_banned, get_balance
from utils import fmt_num

def register(dp: Dispatcher):

    # ═══ КОМАНДА /admin ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        await message.answer(
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_panel_kb()
        )

    # ═══ РАЗДЕЛ: ИГРОКИ ═══
    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message):
        if message.from_user.id != ADMIN_ID: return
        # Здесь мы будем выводить инлайн-кнопки для управления
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Найти игрока", callback_data="admin_find_player")],
            [InlineKeyboardButton(text="🚫 Бан / Разбан", callback_data="admin_ban_start")],
            [InlineKeyboardButton(text="💰 Выдать баланс", callback_data="admin_give_start")],
        ])
        await message.answer(
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=kb
        )

    # ═══ РАЗДЕЛ: ИГРЫ ═══
    @dp.message(F.text == "🎮 Игры")
    async def admin_games(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(
            "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "✅ Все игры включены (в разработке)\n"
            "👇 Скоро здесь появятся кнопки отключения.",
            parse_mode="HTML"
        )

    # ═══ РАЗДЕЛ: ЭКОНОМИКА ═══
    @dp.message(F.text == "💰 Экономика")
    async def admin_economy(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(
            "💰 <b>ЭКОНОМИКА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "📊 Статистика:\n"
            "• Курс Stars: 1 ⭐ = 7 500 Tokens\n"
            "• Курс Gram: 1 Gram = 10 000 Tokens\n\n"
            "👇 Скоро здесь появятся кнопки изменения курса.",
            parse_mode="HTML"
        )

    # ═══ РАЗДЕЛ: КОНТЕНТ ═══
    @dp.message(F.text == "🛒 Контент")
    async def admin_content(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🛒 <b>УПРАВЛЕНИЕ КОНТЕНТОМ</b>\n\n(в разработке)", parse_mode="HTML")

    # ═══ РАЗДЕЛ: СВЯЗЬ ═══
    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📢 <b>РАССЫЛКА</b>\n\n(в разработке)", parse_mode="HTML")

    # ═══ РАЗДЕЛ: МОНИТОРИНГ ═══
    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📊 <b>МОНИТОРИНГ</b>\n\n(в разработке)", parse_mode="HTML")

    # ═══ РАЗДЕЛ: ВСЕ КОМАНДЫ ═══
    @dp.message(F.text == "📋 Все команды")
    async def admin_commands(message: Message):
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "📋 <b>ВСЕ КОМАНДЫ АДМИНА</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "<b>Основные:</b>\n"
            "/admin — это меню\n"
            "/give @user 1000 — выдать баланс\n"
            "/ban @user — забанить\n"
            "/unban @user — разбанить\n"
            "/курс 8000 — изменить курс Stars\n"
        )
        await message.answer(txt, parse_mode="HTML")