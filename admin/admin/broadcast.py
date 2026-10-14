# ═══════════════════════════════════════════════════════════════
# admin/broadcast.py — РАССЫЛКИ
# ═══════════════════════════════════════════════════════════════

import asyncio
from aiogram import Dispatcher
from aiogram.types import Message

from config import ADMIN_ID
from admin.menu import admin_comm_kb, admin_main_kb
from database import get_conn, release_conn

# Состояние ввода текста
broadcast_state = {}


def register(dp: Dispatcher):

    @dp.message(lambda m: m.text == "📢 Связь" and m.from_user.id == ADMIN_ID)
    async def comm_menu(message: Message):
        await message.answer(
            "📢 <b>РАССЫЛКИ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👇 Выбери кому отправить:",
            parse_mode="HTML",
            reply_markup=admin_comm_kb()
        )

    @dp.message(lambda m: m.text == "📨 Всем" and m.from_user.id == ADMIN_ID)
    async def bc_all(message: Message):
        broadcast_state[message.from_user.id] = "all"
        await message.answer(
            "📨 <b>РАССЫЛКА ВСЕМ</b>\n\n"
            "Отправь текст сообщения.\n\n"
            "❌ Отмена: /admin",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📨 По ID" and m.from_user.id == ADMIN_ID)
    async def bc_id(message: Message):
        await message.answer(
            "📨 <b>РАССЫЛКА ПО ID</b>\n\n"
            "Напиши: <code>/sendid 123456 Текст</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📨 В группу" and m.from_user.id == ADMIN_ID)
    async def bc_group(message: Message):
        await message.answer(
            "📨 <b>РАССЫЛКА В ГРУППУ</b>\n\n"
            "Напиши: <code>/sendgroup -100xxx Текст</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📨 Активным" and m.from_user.id == ADMIN_ID)
    async def bc_active(message: Message):
        broadcast_state[message.from_user.id] = "active"
        await message.answer(
            "📨 <b>РАССЫЛКА АКТИВНЫМ</b>\n\n"
            "Отправь текст сообщения.",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📨 VIP" and m.from_user.id == ADMIN_ID)
    async def bc_vip(message: Message):
        broadcast_state[message.from_user.id] = "vip"
        await message.answer(
            "📨 <b>РАССЫЛКА VIP</b>\n\n"
            "Отправь текст сообщения.",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📨 Топ-100" and m.from_user.id == ADMIN_ID)
    async def bc_top(message: Message):
        broadcast_state[message.from_user.id] = "top"
        await message.answer(
            "📨 <b>РАССЫЛКА ТОП-100</b>\n\n"
            "Отправь текст сообщения.",
            parse_mode="HTML"
        )