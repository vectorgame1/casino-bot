# ═══════════════════════════════════════════════════════════════
# admin/bot_control.py — УПРАВЛЕНИЕ БОТОМ
# ═══════════════════════════════════════════════════════════════

import logging
from aiogram import Dispatcher
from aiogram.types import Message

from config import ADMIN_ID
from admin.menu import admin_bot_kb, admin_main_kb
from database import get_total_players

logger = logging.getLogger(__name__)

# Глобальный флаг тех.работ
maintenance_flag = {"on": False}


def register(dp: Dispatcher):

    @dp.message(lambda m: m.text == "⚙️ Бот" and m.from_user.id == ADMIN_ID)
    async def bot_menu(message: Message):
        status = "🛠️ ТЕХ.РАБОТЫ" if maintenance_flag["on"] else "✅ РАБОТАЕТ"
        await message.answer(
            f"⚙️ <b>УПРАВЛЕНИЕ БОТОМ</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📊 Статус: <b>{status}</b>\n"
            f"👥 Игроков: <b>{get_total_players()}</b>\n\n"
            f"👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )

    @dp.message(lambda m: m.text == "🔴 Выключить бота" and m.from_user.id == ADMIN_ID)
    async def bot_off(message: Message):
        maintenance_flag["on"] = True
        await message.answer(
            "🔴 <b>БОТ ВЫКЛЮЧЕН</b>\n\n"
            "Игры недоступны всем, кроме админа.",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )

    @dp.message(lambda m: m.text == "🟢 Включить бота" and m.from_user.id == ADMIN_ID)
    async def bot_on(message: Message):
        maintenance_flag["on"] = False
        await message.answer(
            "🟢 <b>БОТ ВКЛЮЧЁН</b>\n\nИгры доступны всем.",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )

    @dp.message(lambda m: m.text == "📊 Статус бота" and m.from_user.id == ADMIN_ID)
    async def bot_status(message: Message):
        status = "🛠️ ТЕХ.РАБОТЫ" if maintenance_flag["on"] else "✅ РАБОТАЕТ"
        await message.answer(
            f"📊 <b>СТАТУС БОТА</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"🤖 Статус: <b>{status}</b>\n"
            f"👥 Игроков: <b>{get_total_players()}</b>\n"
            f"⚙️ Версия: <b>2.0</b>",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )

    @dp.message(lambda m: m.text == "🔄 Перезапуск" and m.from_user.id == ADMIN_ID)
    async def bot_restart(message: Message):
        await message.answer(
            "🔄 <b>ПЕРЕЗАПУСК</b>\n\n"
            "Бот перезапустится через 5 секунд.\n"
            "Подожди 1-2 минуты.",
            parse_mode="HTML"
        )
        # Render сам перезапустит если упадёт

    @dp.message(lambda m: m.text == "📜 Логи" and m.from_user.id == ADMIN_ID)
    async def bot_logs(message: Message):
        await message.answer(
            "📜 <b>ЛОГИ</b>\n\n"
            "Смотри на Render:\n"
            "dashboard.render.com → casino-bot → Logs",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "⚠️ Ошибки" and m.from_user.id == ADMIN_ID)
    async def bot_errors(message: Message):
        await message.answer(
            "⚠️ <b>ОШИБКИ</b>\n\n"
            "Смотри на Render:\n"
            "dashboard.render.com → casino-bot → Logs\n"
            "Ищи строки с 'ERROR'.",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "🛠️ Тех.работы ВКЛ" and m.from_user.id == ADMIN_ID)
    async def maintenance_on(message: Message):
        maintenance_flag["on"] = True
        await message.answer(
            "🛠️ <b>ТЕХ.РАБОТЫ ВКЛЮЧЕНЫ</b>",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )

    @dp.message(lambda m: m.text == "✅ Тех.работы ВЫКЛ" and m.from_user.id == ADMIN_ID)
    async def maintenance_off(message: Message):
        maintenance_flag["on"] = False
        await message.answer(
            "✅ <b>ТЕХ.РАБОТЫ ВЫКЛЮЧЕНЫ</b>",
            parse_mode="HTML",
            reply_markup=admin_bot_kb()
        )