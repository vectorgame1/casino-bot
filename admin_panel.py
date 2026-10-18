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
from utils import send_clean, fmt_num

# ... дальше класс AdminStates ...
# Стейты
class AdminStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_ban_user = State()
    waiting_unban_user = State()
    waiting_broadcast_all = State()
    waiting_broadcast_target = State()
    waiting_broadcast_text = State()

last_scanned = {}
broadcast_target = {}

def register(dp: Dispatcher):

    # ═══ СБРОС СОСТОЯНИЙ ПРИ НАЖАТИИ НАВИГАЦИИ ═══
    @dp.message(F.text.in_({"⬅️ Назад в админку", "⬅️ В меню игроков", "👥 Игроки", "🎮 Игры", "🛒 Контент", "💰 Экономика", "📢 Связь", "📊 Мониторинг", "📋 Все команды", "🔍 Скан игрока", "❌ Отмена", "🎮 Управление играми"}))
    async def cancel_any_state(message: Message, state: FSMContext):
        if await state.get_state() is not None:
            await state.clear()

    # ═══ ГЛАВНАЯ АДМИНКА ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━\n\n👇 Выбери раздел:", parse_mode="HTML", reply_markup=admin_panel_kb())

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
        await send_clean(message, "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n━━━━━━━━━━━━━━\n\n👇 Выбери действие:", parse_mode="HTML", reply_markup=kb)

    # ═══ СКАН ИГРОКА ═══
    @dp.message(F.text == "🔍 Скан игрока")
    async def scan_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🔍 Введи @username или ID игрока:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_scan)

    @dp.message(AdminStates.waiting_scan)
    async def scan_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        target = message.text.replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        
        if not uid:
            await send_clean(message, "❌ Игрок не найден.")
            await state.clear()
            return

        last_scanned[message.from_user.id] = uid

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT username, balance, xp, banned FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        c.close()
        release_conn(conn)

        uname, bal, xp, banned = row
        status = "🚫 ЗАБАНЕН" if banned else "✅ Активен"
        
        txt = (
            f"🕵️ <b>СКАН ИГРОКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 @{uname}\n"
            f"🆔 <code>{uid}</code>\n"
            f"📊 Статус: {status}\n\n"
            f"💎 Баланс: <b>{fmt_num(bal)}</b>\n"
            f"⭐ XP: {xp}"
        )

        quick_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚫 Забанить его"), KeyboardButton(text="✅ Разбанить его")],
                [KeyboardButton(text="💰 Выдать ему"), KeyboardButton(text="💸 Забрать у него")],
                [KeyboardButton(text="⬅️ В меню игроков")]
            ],
            resize_keyboard=True
        )
        await send_clean(message, txt, parse_mode="HTML", reply_markup=quick_kb)
        await state.clear()

    # ═══ БЫСТРЫЕ ДЕЙСТВИЯ С ИГРОКОМ ═══
    @dp.message(F.text == "🚫 Забанить его")
    async def q_ban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned.get(message.from_user.id)
        if uid:
            set_banned(uid, True)
            await send_clean(message, "🚫 Игрок забанен!")
        else:
            await send_clean(message, "❌ Сначала просканируй игрока.")

    @dp.message(F.text == "✅ Разбанить его")
    async def q_unban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned.get(message.from_user.id)
        if uid:
            set_banned(uid, False)
            await send_clean(message, "✅ Игрок разбанен!")
        else:
            await send_clean(message, "❌ Сначала просканируй игрока.")

    @dp.message(F.text == "💰 Выдать ему")
    async def q_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 Введи сумму:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать у него")
    async def q_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 Введи сумму:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_amount)
        await state.update_data(action="take")

    @dp.message(AdminStates.waiting_amount)
    async def q_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned.get(message.from_user.id)
        data = await state.get_data()
        try:
            amount = int(message.text)
        except ValueError:
            await send_clean(message, "❌ Введи число.")
            return
            
        if data["action"] == "give":
            set_balance(uid, amount)
            await send_clean(message, f"✅ Выдано <b>{fmt_num(amount)}</b>.", parse_mode="HTML")
        else:
            set_balance(uid, -amount)
            await send_clean(message, f"✅ Списано <b>{fmt_num(amount)}</b>.", parse_mode="HTML")
        await state.clear()

    # ═══ РАЗДЕЛ: ИГРЫ (ВКЛ/ВЫКЛ) ═══
    @dp.message(F.text == "🎮 Игры")
    async def admin_games_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Включить все"), KeyboardButton(text="❌ Выключить все")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await send_clean(message, "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Выбери действие:", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "✅ Включить все")
    async def games_on(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE settings SET value = 'on' WHERE key = 'games_enabled'")
        conn.commit()
        c.close()
        release_conn(conn)
        await send_clean(message, "✅ Все игры включены!", reply_markup=admin_panel_kb())

    @dp.message(F.text == "❌ Выключить все")
    async def games_off(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE settings SET value = 'off' WHERE key = 'games_enabled'")
        conn.commit()
        c.close()
        release_conn(conn)
        await send_clean(message, "❌ Все игры выключены!", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: ЭКОНОМИКА ═══
    @dp.message(F.text == "💰 Экономика")
    async def admin_economy_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
        total_users, total_balance = c.fetchone()
        c.close()
        release_conn(conn)
        
        txt = (
            f"💰 <b>ЭКОНОМИКА</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👥 Всего игроков: <b>{total_users}</b>\n"
            f"💎 Общий баланс: <b>{fmt_num(total_balance)}</b>\n\n"
            f"💱 Курс Stars: <b>1 ⭐ = 7 500 Tokens</b>"
        )
        await send_clean(message, txt, parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: МОНИТОРИНГ ═══
    @dp.message(F.text == "📊 Мониторинг")
    async def admin_monitoring_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE banned = FALSE")
        active_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
        banned_users = c.fetchone()[0]
        c.close()
        release_conn(conn)
        
        txt = (
            f"📊 <b>МОНИТОРИНГ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Активных: <b>{active_users}</b>\n"
            f"🚫 Забаненных: <b>{banned_users}</b>\n\n"
            f"👑 Админ: <b>@{message.from_user.username}</b>"
        )
        await send_clean(message, txt, parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: СВЯЗЬ (РАССЫЛКА) ═══
    @dp.message(F.text == "📢 Связь")
    async def admin_comm_menu(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📢 Всем игрокам")],
                [KeyboardButton(text="🎯 По @username")],
                [KeyboardButton(text="🆔 По ID")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await send_clean(message, "📢 <b>РАССЫЛКА</b>\n\nКому отправить?", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_all_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📢 Напиши текст для всех:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_broadcast_all)

    @dp.message(AdminStates.waiting_broadcast_all)
    async def broadcast_all_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        c.close()
        release_conn(conn)
        sent = 0
        await send_clean(message, f"⏳ Рассылка на {len(users)}...")
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except: pass
        await send_clean(message, f"✅ Отправлено: {sent}", reply_markup=admin_panel_kb())

    @dp.message(F.text == "🎯 По @username")
    async def broadcast_user_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🎯 Введи @username игрока:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_broadcast_target)
        await state.update_data(mode="user")

    @dp.message(F.text == "🆔 По ID")
    async def broadcast_id_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🆔 Введи ID игрока:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_broadcast_target)
        await state.update_data(mode="id")

    @dp.message(AdminStates.waiting_broadcast_target)
    async def broadcast_target_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        data = await state.get_data()
        target = message.text.replace("@", "")
        
        if data["mode"] == "user":
            uid = get_user_id_by_username(target)
        else:
            try: uid = int(target)
            except: uid = None

        if not uid:
            await send_clean(message, "❌ Игрок не найден.")
            await state.clear()
            return

        broadcast_target[message.from_user.id] = uid
        await send_clean(message, "✍️ Теперь напиши текст сообщения:")
        await state.set_state(AdminStates.waiting_broadcast_text)

    @dp.message(AdminStates.waiting_broadcast_text)
    async def broadcast_text_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        uid = broadcast_target.get(message.from_user.id)
        if not uid:
            await send_clean(message, "❌ Ошибка.")
            await state.clear()
            return
        
        try:
            await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML")
            await send_clean(message, "✅ Сообщение отправлено!", reply_markup=admin_panel_kb())
        except Exception as e:
            await send_clean(message, f"❌ Ошибка: {e}", reply_markup=admin_panel_kb())
        await state.clear()

    # ═══ НАЗАД ═══
    @dp.message(F.text == "⬅️ Назад в админку")
    async def back_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>", parse_mode="HTML", reply_markup=admin_panel_kb())

    @dp.message(F.text == "⬅️ В меню игроков")
    async def back_players(message: Message):
        await admin_players_menu(message)

    @dp.message(F.text == "📋 Все команды")
    async def admin_commands(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📋 <b>КОМАНДЫ</b>\n\n/admin\n/give @user сумма\n/ban @user\n/unban @user", parse_mode="HTML", reply_markup=admin_panel_kb())