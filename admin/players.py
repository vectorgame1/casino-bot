# ═══════════════════════════════════════════════════════════════
# admin/players.py — ОБРАБОТЧИКИ РАЗДЕЛА "ИГРОКИ"
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.types import Message

from config import ADMIN_ID
from admin.menu import admin_players_kb, admin_main_kb


def register(dp: Dispatcher):

    # ═══ ГЛАВНОЕ МЕНЮ ═══

    @dp.message(lambda m: m.text == "👥 Игроки" and m.from_user.id == ADMIN_ID)
    async def players_menu(message: Message):
        await message.answer(
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👇 Выбери действие:",
            parse_mode="HTML",
            reply_markup=admin_players_kb()
        )

    # ═══ НАЗАД В АДМИН ═══

    @dp.message(lambda m: m.text == "🔙 Назад в админ" and m.from_user.id == ADMIN_ID)
    async def back_to_admin(message: Message):
        await message.answer(
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n👇 Выбери раздел:",
            parse_mode="HTML",
            reply_markup=admin_main_kb()
        )

    # ═══ ПРОБИВ ═══

    @dp.message(lambda m: m.text == "🔍 Пробив" and m.from_user.id == ADMIN_ID)
    async def scan_hint(message: Message):
        await message.answer(
            "🔍 <b>ПРОБИВ ИГРОКА</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "<b>Способы:</b>\n"
            "1️⃣ <code>/scan @username</code>\n"
            "2️⃣ <code>/scan 123456789</code>\n"
            "3️⃣ <code>/scan me</code> — свой профиль\n"
            "4️⃣ Ответь на сообщение и напиши <code>/scan</code>",
            parse_mode="HTML"
        )

    # ═══ БАН ═══

    @dp.message(lambda m: m.text == "🚫 Бан" and m.from_user.id == ADMIN_ID)
    async def ban_hint(message: Message):
        await message.answer(
            "🚫 <b>БАН</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/ban</code>\n\n"
            "Или: <code>/ban @username</code>",
            parse_mode="HTML"
        )

    # ═══ РАЗБАН ═══

    @dp.message(lambda m: m.text == "✅ Разбан" and m.from_user.id == ADMIN_ID)
    async def unban_hint(message: Message):
        await message.answer(
            "✅ <b>РАЗБАН</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/unban</code>\n\n"
            "Или: <code>/unban @username</code>",
            parse_mode="HTML"
        )

    # ═══ БОНУС ═══

    @dp.message(lambda m: m.text == "🎁 Бонус" and m.from_user.id == ADMIN_ID)
    async def bonus_hint(message: Message):
        await message.answer(
            "🎁 <b>БОНУС ИГРОКУ</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/bonus 10000</code>\n\n"
            "Или: <code>/bonus @username 10000</code>\n"
            "Всем: <code>/bonus all 5000</code>",
            parse_mode="HTML"
        )

    # ═══ СЛЕДИТЬ ═══

    @dp.message(lambda m: m.text == "🎬 Следить" and m.from_user.id == ADMIN_ID)
    async def watch_hint(message: Message):
        await message.answer(
            "🎬 <b>СЛЕДИТЬ ЗА ИГРОКОМ</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/watch</code>\n\n"
            "Или: <code>/watch @username</code>",
            parse_mode="HTML"
        )

    # ═══ УДАЛИТЬ ═══

    @dp.message(lambda m: m.text == "🗑 Удалить" and m.from_user.id == ADMIN_ID)
    async def delete_hint(message: Message):
        await message.answer(
            "🗑 <b>УДАЛИТЬ ИГРОКА</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/delete</code>\n\n"
            "⚠️ <b>ОПАСНО! Действие необратимо!</b>",
            parse_mode="HTML"
        )

    # ═══ СПИСОК ═══

    @dp.message(lambda m: m.text == "📋 Список" and m.from_user.id == ADMIN_ID)
    async def list_hint(message: Message):
        await message.answer(
            "📋 <b>СПИСОК ИГРОКОВ</b>\n\n"
            "Напиши:\n"
            "<code>/players</code>",
            parse_mode="HTML"
        )

    # ═══ БАЛАНС / XP / VIP / ТИТУЛ ═══

    @dp.message(lambda m: m.text == "💰 Баланс" and m.from_user.id == ADMIN_ID)
    async def balance_hint(message: Message):
        await message.answer(
            "💰 <b>ИЗМЕНИТЬ БАЛАНС</b>\n\n"
            "Ответь на сообщение игрока:\n"
            "<code>/give 10000</code>\n\n"
            "Или: <code>/give @username 10000</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "📊 XP" and m.from_user.id == ADMIN_ID)
    async def xp_hint(message: Message):
        await message.answer(
            "📊 <b>ИЗМЕНИТЬ XP</b>\n\n"
            "Напиши:\n"
            "<code>/setxp @username 1000</code>",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "👑 VIP" and m.from_user.id == ADMIN_ID)
    async def vip_hint(message: Message):
        await message.answer(
            "👑 <b>ВЫДАТЬ VIP</b>\n\n"
            "Напиши:\n"
            "<code>/vip @username 3 20</code>\n"
            "(уровень 1-5, дней)",
            parse_mode="HTML"
        )

    @dp.message(lambda m: m.text == "🏷️ Титул" and m.from_user.id == ADMIN_ID)
    async def title_hint(message: Message):
        await message.answer(
            "🏷️ <b>ВЫДАТЬ ТИТУЛ</b>\n\n"
            "Напиши:\n"
            "<code>/title @username Легенда</code>",
            parse_mode="HTML"
        )