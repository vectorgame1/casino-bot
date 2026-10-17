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
    waiting_broadcast_all = State()

last_scanned_user = {}

def register(dp: Dispatcher):

    # ═══ ГЛОБАЛЬНЫЙ СБРОС СОСТОЯНИЙ ═══
    @dp.message(F.text.in_({"⬅️ Назад в админку", "⬅️ В меню игроков", "👥 Игроки", "🎮 Игры", "🛒 Контент", "💰 Экономика", "📢 Связь", "📊 Мониторинг", "📋 Все команды", "🔍 Скан игрока", "❌ Отмена"}))
    async def cancel_any_state(message: Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state is not None:
            await state.clear()

    # ═══ ГЛАВНАЯ АДМИНКА ═══
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(
            message,
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_panel_kb()
        )

    # ═══ КНОПКА ОТМЕНА ═══
    @dp.message(F.text == "❌ Отмена")
    async def cancel_action(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await send_clean(
            message,
            "❌ Действие отменено.\n\nВозврат в админ-меню 👇",
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
        await send_clean(
            message,
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
        await send_clean(message, "🔍 Введи @username или ID игрока для сканирования:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
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
            await send_clean(message, "❌ Игрок не найден.")
            await state.clear()
            return

        last_scanned_user[message.from_user.id] = uid

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT username, balance, bank, xp, banned, total_won, total_lost FROM users WHERE user_id = %s", (uid,))
        row = c.fetchone()
        c.close()
        release_conn(conn)

        if not row:
            await send_clean(message, "❌ Игрок не найден в базе.")
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
            f"⭐ <b>XP:</b> {xp} (Ур. {lvl})\n\n"
            f"🏆 <b>Выиграл:</b> {fmt_num(won)}\n"
            f"💸 <b>Проиграл:</b> {fmt_num(lost)}"
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
        uid = last_scanned_user.get(message.from_user.id)
        if not uid: return
        set_banned(uid, True)
        await send_clean(message, "🚫 <b>Игрок забанен!</b>", parse_mode="HTML")

    @dp.message(F.text == "✅ Разбанить его")
    async def q_unban(message: Message):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned_user.get(message.from_user.id)
        if not uid: return
        set_banned(uid, False)
        await send_clean(message, "✅ <b>Игрок разбанен!</b>", parse_mode="HTML")

    @dp.message(F.text == "💰 Выдать ему")
    async def q_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💰 Введи сумму для выдачи:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_amount)
        await state.update_data(action="give")

    @dp.message(F.text == "💸 Забрать у него")
    async def q_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, "💸 Введи сумму для списания:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_amount)
        await state.update_data(action="take")

    @dp.message(AdminStates.waiting_amount)
    async def q_amount(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        uid = last_scanned_user.get(message.from_user.id)
        data = await state.get_data()
        try:
            amount = int(message.text)
        except ValueError:
            await send_clean(message, "❌ Введи число.")
            return
            
        if data["action"] == "give":
            set_balance(uid, amount)
            await send_clean(message, f"✅ Выдано <b>{fmt_num(amount)}</b> Tokens.", parse_mode="HTML")
        else:
            set_balance(uid, -amount)
            await send_clean(message, f"✅ Списано <b>{fmt_num(amount)}</b> Tokens.", parse_mode="HTML")
        await state.clear()

    # ═══ РАЗДЕЛ: СВЯЗЬ (РАССЫЛКА) ═══
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
        await send_clean(message, "📢 Напиши текст для рассылки всем игрокам:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True))
        await state.set_state(AdminStates.waiting_broadcast_all)

    @dp.message(AdminStates.waiting_broadcast_all)
    async def broadcast_process(message: Message, state: FSMContext):
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
        await send_clean(message, f"⏳ Рассылка на {len(users)} игроков...")
        
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, f"📢 <b>СООБЩЕНИЕ ОТ АДМИНИСТРАЦИИ</b>\n━━━━━━━━━━━━━━\n\n{text}", parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
                
        await send_clean(message, f"✅ <b>Рассылка завершена!</b>\n\nУспешно: {sent}\nОшибок: {failed}", parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ ЗАГЛУШКИ ═══
    @dp.message(F.text.in_({"🎮 Игры", "🛒 Контент", "💰 Экономика", "📊 Мониторинг", "📋 Все команды"}))
    async def placeholders(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await send_clean(message, f"🛠 <b>Раздел «{message.text}»</b>\n\nВ разработке.", parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ НАЗАД В АДМИНКУ ═══
    @dp.message(F.text == "⬅️ Назад в админку")
    async def back_admin(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await send_clean(
            message,
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_panel_kb()
        )

    # ═══ НАЗАД В МЕНЮ ИГРОКОВ ═══
    @dp.message(F.text == "⬅️ В меню игроков")
    async def back_players(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        # Вызываем функцию меню игроков
        await admin_players_menu(message)