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

class AdminStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_broadcast = State()
    waiting_ban = State()

last_scanned = {}
broadcast_text = {}

def register(dp: Dispatcher):

    # ═══ ГЛАВНАЯ АДМИНКА ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "👑 <b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━\n\n👇 Выбери раздел:", parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: ИГРОКИ ═══
    @dp.message(F.text == "👥 Игроки")
    async def admin_players(message: Message):
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
        await send_clean(message, "🔍 Введи @username или ID:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
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

    # ═══ БЫСТРЫЕ ДЕЙСТВИЯ ═══
    @dp.message(F.text == "🚫 Забанить его")
    async def q_ban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned.get(message.from_user.id)
        if uid: set_banned(uid, True)
        await send_clean(message, "🚫 Игрок забанен!")

    @dp.message(F.text == "✅ Разбанить его")
    async def q_unban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned.get(message.from_user.id)
        if uid: set_banned(uid, False)
        await send_clean(message, "✅ Игрок разбанен!")

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

    # ═══ РАЗДЕЛ: РАССЫЛКА ═══
    @dp.message(F.text == "📢 Связь")
    async def admin_comm(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📢 Всем игрокам")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await send_clean(message, "📢 <b>РАССЫЛКА</b>\n\nКому отправить?", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "📢 Всем игрокам")
    async def broadcast_start(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "📢 Напиши текст для всех:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_broadcast)

    @dp.message(AdminStates.waiting_broadcast)
    async def broadcast_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        c.close()
        release_conn(conn)
        
        sent = 0
        await send_clean(message, f"⏳ Рассылка на {len(users)} игроков...")
        
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, f"📢 <b>ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{message.text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
                
        await send_clean(message, f"✅ Отправлено: {sent}", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: ИГРЫ ═══
    @dp.message(F.text == "🎮 Игры")
    async def admin_games(message: Message):
        if message.from_user.id != ADMIN_ID: return
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Включить все"), KeyboardButton(text="❌ Выключить все")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await send_clean(message, "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Выбери действие:", parse_mode="HTML", reply_markup=kb)

    # ═══ РАЗДЕЛ: ЭКОНОМИКА ═══
    @dp.message(F.text == "💰 Экономика")
    async def admin_economy(message: Message):
        if message.from_user.id != ADMIN_ID: return
        # Получаем количество игроков и общий баланс
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
    async def admin_monitoring(message: Message):
        if message.from_user.id != ADMIN_ID: return
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE banned = FALSE")
        active_users = c.fetchone()[0]
        c.close()
        release_conn(conn)
        
        txt = (
            f"📊 <b>МОНИТОРИНГ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"✅ Активных игроков: <b>{active_users}</b>\n"
            f"👑 Админ: <b>@{message.from_user.username}</b>"
        )
        await send_clean(message, txt, parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ РАЗДЕЛ: КОНТЕНТ ═══
    @dp.message(F.text == "🛒 Контент")
    async def admin_content(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "🛒 <b>КОНТЕНТ</b>\n\nВ разработке (магазин и кейсы).", parse_mode="HTML", reply_markup=admin_panel_kb())