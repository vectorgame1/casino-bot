# admin_panel.py
import asyncio
from aiogram import Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_ID
from keyboards import admin_panel_kb
from database import (
    get_user_id_by_username, set_balance, set_banned, 
    get_balance, get_conn, release_conn
)
from utils import fmt_num

class AdminStates(StatesGroup):
    waiting_give = State()
    waiting_take = State()
    waiting_ban = State()
    waiting_unban = State()
    waiting_scan = State()
    waiting_broadcast_all = State()
    waiting_broadcast_text = State()
    waiting_broadcast_target = State()

def register(dp: Dispatcher):

    # ═══ ГЛАВНАЯ АДМИНКА ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
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
                [KeyboardButton(text="🔍 Скан игрока")],
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

    # ═══ СКАН ИГРОКА ═══
    @dp.message(F.text == "🔍 Скан игрока")
    async def scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🔍 Введи @username или ID игрока для сканирования:")
        await state.set_state(AdminStates.waiting_scan)

    @dp.message(AdminStates.waiting_scan)
    async def scan_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "")
        
        uid = None
        if target.isdigit():
            uid = int(target)
        else:
            uid = get_user_id_by_username(target)
            
        if not uid:
            await message.answer("❌ Игрок не найден.")
            await state.clear()
            return

        # Собираем инфу
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT username, balance, bank, xp, banned, total_won, total_lost FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        c.close()
        release_conn(conn)

        if not row:
            await message.answer("❌ Игрок не найден в базе.")
            await state.clear()
            return

        uname, bal, bank, xp, banned, won, lost = row
        lvl = xp // 100
        ban_status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
        
        txt = (
            f"🕵️ <b>СКАН ИГРОКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Имя:</b> @{uname or 'нет'}\n"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n"
            f"📊 <b>Статус:</b> {ban_status}\n\n"
            f"💎 <b>Баланс:</b> {fmt_num(bal)}\n"
            f"🏦 <b>Банк:</b> {fmt_num(bank)}\n"
            f"⭐ <b>XP:</b> {xp} (Уровень {lvl})\n\n"
            f"🏆 <b>Выиграл:</b> {fmt_num(won)}\n"
            f"💸 <b>Проиграл:</b> {fmt_num(lost)}"
        )
        await message.answer(txt, parse_mode="HTML")
        await state.clear()

    # ═══ ВЫДАТЬ БАЛАНС ═══
    @dp.message(F.text == "💰 Выдать баланс")
    async def give_balance_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💰 Введи @username и сумму через пробел.\nПример: <code>@vctorw 50000</code>", parse_mode="HTML")
        await state.set_state(AdminStates.waiting_give)

    @dp.message(AdminStates.waiting_give)
    async def give_balance_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Ошибка! Введи @username и сумму через пробел.")
            return
        target, amount_str = args[0].replace("@", ""), args[1]
        try:
            amount = int(amount_str)
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            return
        uid = get_user_id_by_username(target)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_balance(uid, amount)
        await message.answer(f"✅ Выдано <b>{fmt_num(amount)}</b> игроку @{target}", parse_mode="HTML")
        await state.clear()

    # ═══ ЗАБРАТЬ БАЛАНС ═══
    @dp.message(F.text == "💸 Забрать баланс")
    async def take_balance_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💸 Введи @username и сумму через пробел.\nПример: <code>@vctorw 1000</code>", parse_mode="HTML")
        await state.set_state(AdminStates.waiting_take)

    @dp.message(AdminStates.waiting_take)
    async def take_balance_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        args = message.text.split()
        if len(args) != 2:
            await message.answer("❌ Ошибка! Введи @username и сумму через пробел.")
            return
        target, amount_str = args[0].replace("@", ""), args[1]
        try:
            amount = int(amount_str)
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            return
        uid = get_user_id_by_username(target)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_balance(uid, -amount)
        await message.answer(f"✅ Списано <b>{fmt_num(amount)}</b> у игрока @{target}", parse_mode="HTML")
        await state.clear()

    # ═══ БАН / РАЗБАН ═══
    @dp.message(F.text == "🚫 Забанить")
    async def ban_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🚫 Введи @username игрока для бана:")
        await state.set_state(AdminStates.waiting_ban)

    @dp.message(AdminStates.waiting_ban)
    async def ban_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "")
        uid = get_user_id_by_username(target)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_banned(uid, True)
        await message.answer(f"🚫 Игрок @{target} забанен.")
        await state.clear()

    @dp.message(F.text == "✅ Разбанить")
    async def unban_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("✅ Введи @username игрока для разбана:")
        await state.set_state(AdminStates.waiting_unban)

    @dp.message(AdminStates.waiting_unban)
    async def unban_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "")
        uid = get_user_id_by_username(target)
        if not uid:
            await message.answer("❌ Игрок не найден.")
            return
        set_banned(uid, False)
        await message.answer(f"✅ Игрок @{target} разбанен.")
        await state.clear()

    # ═══ РАЗДЕЛ: РАССЫЛКА ═══
    @dp.message(F.text == "📢 Связь")
    async def admin_comm_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📢 Всем игрокам")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await message.answer("📢 <b>РАССЫЛКА</b>\n\nКому отправить?", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📢 Напиши текст для рассылки всем игрокам:")
        await state.set_state(AdminStates.waiting_broadcast_all)

    @dp.message(AdminStates.waiting_broadcast_all)
    async def broadcast_all_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        text = message.text
        
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        c.close()
        release_conn(conn)
        
        sent = 0
        failed = 0
        await message.answer(f"⏳ Рассылка на {len(users)} игроков...")
        
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, f"📢 <b>СООБЩЕНИЕ ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
                
        await message.answer(f"✅ Рассылка завершена!\nУспешно: {sent}\nОшибок: {failed}", parse_mode="HTML")

    # ═══ ЗАГЛУШКИ ДЛЯ ОСТАЛЬНЫХ РАЗДЕЛОВ ═══
    @dp.message(F.text.in_({"🎮 Игры", "🛒 Контент", "💰 Экономика", "📊 Мониторинг", "📋 Все команды"}))
    async def placeholders(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(f"🛠 <b>Раздел «{message.text}»</b>\n\nВ разработке. Скоро здесь появятся команды.", parse_mode="HTML")

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад в админку")
    async def back_to_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n👇 Выбери раздел:", parse_mode="HTML", reply_markup=admin_panel_kb())