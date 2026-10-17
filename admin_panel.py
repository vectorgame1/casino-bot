# admin_panel.py
from aiogram import Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from keyboards import admin_panel_kb
from database import get_user_id_by_username, set_balance, set_banned, get_balance
from utils import fmt_num

# Состояния для ввода данных
class AdminStates(StatesGroup):
    waiting_give = State()     # Ждем ввода для выдачи
    waiting_take = State()     # Ждем ввода для забирания
    waiting_ban = State()      # Ждем ввода для бана
    waiting_unban = State()    # Ждем ввода для разбана

def register(dp: Dispatcher):

    # ═══ ГЛАВНАЯ АДМИНКА ═══
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
    async def admin_players_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],
                [KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=kb
        )

    # ═══ ВЫДАТЬ БАЛАНС ═══
    @dp.message(F.text == "💰 Выдать баланс")
    async def give_balance_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(
            "💰 <b>ВЫДАЧА БАЛАНСА</b>\n\n"
            "Введи @username и сумму через пробел.\n"
            "Пример: <code>@vctorw 500000</code>",
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_give)

    @dp.message(AdminStates.waiting_give)
    async def give_balance_process(message: Message, state: FSMContext):
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Ошибка! Введи @username и сумму через пробел.")
            return
        
        target_username = args[0].replace("@", "")
        try:
            amount = int(args[1])
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            return
            
        uid = get_user_id_by_username(target_username)
        if not uid:
            await message.answer("❌ Игрок не найден в базе.")
            return
            
        set_balance(uid, amount)
        await message.answer(f"✅ <b>Выдано!</b>\n\n👤 @{target_username}\n💰 +{fmt_num(amount)} Tokens", parse_mode="HTML")
        await state.clear()

    # ═══ ЗАБРАТЬ БАЛАНС ═══
    @dp.message(F.text == "💸 Забрать баланс")
    async def take_balance_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(
            "💸 <b>СПИСАНИЕ БАЛАНСА</b>\n\n"
            "Введи @username и сумму через пробел.\n"
            "Пример: <code>@vctorw 1000</code>",
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_take)

    @dp.message(AdminStates.waiting_take)
    async def take_balance_process(message: Message, state: FSMContext):
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Ошибка! Введи @username и сумму через пробел.")
            return
        
        target_username = args[0].replace("@", "")
        try:
            amount = int(args[1])
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            return
            
        uid = get_user_id_by_username(target_username)
        if not uid:
            await message.answer("❌ Игрок не найден в базе.")
            return
            
        set_balance(uid, -amount)
        await message.answer(f"✅ <b>Списано!</b>\n\n👤 @{target_username}\n💰 -{fmt_num(amount)} Tokens", parse_mode="HTML")
        await state.clear()

    # ═══ ЗАБАНИТЬ ═══
    @dp.message(F.text == "🚫 Забанить")
    async def ban_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🚫 <b>ВВЕДИ @username</b> игрока, которого нужно забанить:", parse_mode="HTML")
        await state.set_state(AdminStates.waiting_ban)

    @dp.message(AdminStates.waiting_ban)
    async def ban_process(message: Message, state: FSMContext):
        target_username = message.text.replace("@", "")
        uid = get_user_id_by_username(target_username)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_banned(uid, True)
        await message.answer(f"🚫 <b>Игрок @{target_username} забанен!</b>", parse_mode="HTML")
        await state.clear()

    # ═══ РАЗБАНИТЬ ═══
    @dp.message(F.text == "✅ Разбанить")
    async def unban_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("✅ <b>ВВЕДИ @username</b> игрока, которого нужно разбанить:", parse_mode="HTML")
        await state.set_state(AdminStates.waiting_unban)

    @dp.message(AdminStates.waiting_unban)
    async def unban_process(message: Message, state: FSMContext):
        target_username = message.text.replace("@", "")
        uid = get_user_id_by_username(target_username)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_banned(uid, False)
        await message.answer(f"✅ <b>Игрок @{target_username} разбанен!</b>", parse_mode="HTML")
        await state.clear()

    # ═══ ОСТАЛЬНЫЕ РАЗДЕЛЫ ═══
    @dp.message(F.text == "🎮 Игры")
    async def admin_games_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🎮 <b>ИГРЫ</b>\n\n(в разработке)\n\nНапиши /admin для возврата.", parse_mode="HTML")

    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💰 <b>ЭКОНОМИКА</b>\n\n(в разработке)\n\nНапиши /admin для возврата.", parse_mode="HTML")
        
    @dp.message(F.text == "🛒 Контент")
    async def admin_content_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🛒 <b>КОНТЕНТ</b>\n\n(в разработке)\n\nНапиши /admin для возврата.", parse_mode="HTML")

    @dp.message(F.text == "📢 Связь")
    async def admin_comm_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📢 <b>СВЯЗЬ</b>\n\n(в разработке)\n\nНапиши /admin для возврата.", parse_mode="HTML")

    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📊 <b>МОНИТОРИНГ</b>\n\n(в разработке)\n\nНапиши /admin для возврата.", parse_mode="HTML")

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад в админку")
    async def back_to_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_panel_kb()
        )