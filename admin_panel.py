import asyncio
from aiogram import Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import ADMIN_ID
from keyboards import admin_panel_kb
from database import get_user_id_by_username, set_balance, set_banned, get_balance, get_conn, release_conn
from utils import fmt_num

class AdminStates(StatesGroup):
    waiting_scan = State(); waiting_give = State(); waiting_take = State()
    waiting_ban = State(); waiting_unban = State(); waiting_amount = State()
    waiting_broadcast_all = State()

last_scanned_user = {}

def register(dp: Dispatcher):
    # Сброс всех состояний при нажатии любых кнопок навигации
    @dp.message(F.text.in_({"⬅️ Назад в админку", "⬅️ В меню игроков", "👥 Игроки", "🎮 Игры", "🛒 Контент", "💰 Экономика", "📢 Связь", "📊 Мониторинг", "📋 Все команды", "🔍 Скан игрока", "❌ Отмена"}))
    async def cancel_any_state(message: Message, state: FSMContext):
        if await state.get_state() is not None:
            await state.clear()

    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━\n\n👇 Выбери раздел:", parse_mode="HTML", reply_markup=admin_panel_kb())

    @dp.message(F.text == "❌ Отмена")
    async def cancel_action(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=admin_panel_kb())

    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Скан игрока")],[KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],[KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await message.answer("👥 <b>УПРАВЛЕНИЕ</b>\n\n👇 Выбери действие:", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "🔍 Скан игрока")
    async def scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🔍 Введи @username или ID:")
        await state.set_state(AdminStates.waiting_scan)

    @dp.message(AdminStates.waiting_scan)
    async def scan_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: await message.answer("❌ Не найден."); await state.clear(); return
        last_scanned_user[message.from_user.id] = uid
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT username, balance, bank, xp, banned, total_won, total_lost FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        c.close(); release_conn(conn)
        uname, bal, bank, xp, banned, won, lost = row
        ban_status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
        txt = f"🕵️ <b>СКАН</b>\n━━━━━━━━━━━━━━\n\n👤 @{uname}\n🆔 <code>{uid}</code>\n📊 {ban_status}\n\n💎 Баланс: {fmt_num(bal)}\n🏦 Банк: {fmt_num(bank)}\n⭐ XP: {xp}\n\n🏆 Выиграл: {fmt_num(won)}\n💸 Проиграл: {fmt_num(lost)}"
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚫 Забанить его"), KeyboardButton(text="✅ Разбанить его")],[KeyboardButton(text="💰 Выдать ему"), KeyboardButton(text="💸 Забрать у него")],[KeyboardButton(text="⬅️ В меню игроков")]], resize_keyboard=True)
        await message.answer(txt, parse_mode="HTML", reply_markup=kb)
        await state.clear()

    @dp.message(F.text == "🚫 Забанить его")
    async def q_ban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        set_banned(last_scanned_user.get(message.from_user.id), True)
        await message.answer("🚫 Забанен!")

    @dp.message(F.text == "✅ Разбанить его")
    async def q_unban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        set_banned(last_scanned_user.get(message.from_user.id), False)
        await message.answer("✅ Разбанен!")

    @dp.message(F.text == "💰 Выдать ему")
    async def q_give_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💰 Введи сумму для выдачи:")
        await state.set_state(AdminStates.waiting_amount); await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать у него")
    async def q_take_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💸 Введи сумму для списания:")
        await state.set_state(AdminStates.waiting_amount); await state.update_data(action="take")

    @dp.message(AdminStates.waiting_amount)
    async def q_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        uid, data = last_scanned_user.get(message.from_user.id), await state.get_data()
        try: amount = int(message.text)
        except: await message.answer("❌ Введи число."); return
        set_balance(uid, amount if data["action"] == "give" else -amount)
        await message.answer(f"✅ {'Выдано' if data['action'] == 'give' else 'Забрано'} <b>{fmt_num(amount)}</b>.", parse_mode="HTML")
        await state.clear()

    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📢 Всем игрокам")],[KeyboardButton(text="⬅️ Назад в админку")]], resize_keyboard=True)
        await message.answer("📢 <b>РАССЫЛКА</b>\n\nКому отправить?", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("📢 Напиши текст для всех:")
        await state.set_state(AdminStates.waiting_broadcast_all)

    @dp.message(AdminStates.waiting_broadcast_all)
    async def broadcast_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        conn = get_conn(); c = conn.cursor(); c.execute("SELECT user_id FROM users"); users = c.fetchall(); c.close(); release_conn(conn)
        sent = 0
        await message.answer(f"⏳ Рассылка на {len(users)}...")
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML")
                sent += 1; await asyncio.sleep(0.05)
            except: pass
        await message.answer(f"✅ Отправлено: {sent}")

    @dp.message(F.text == "⬅️ Назад в админку")
    async def back_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>", parse_mode="HTML", reply_markup=admin_panel_kb())

    @dp.message(F.text == "⬅️ В меню игроков")
    async def back_players(message: Message):
        await admin_players(message)

    @dp.message(F.text.in_({"🎮 Игры", "🛒 Контент", "💰 Экономика", "📊 Мониторинг", "📋 Все команды"}))
    async def placeholders(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer(f"🛠 <b>«{message.text}»</b>\n\nВ разработке.", parse_mode="HTML")