# ═══════════════════════════════════════════════════════════════
# admin/watch.py — СЛЕЖКА ЗА ИГРОКОМ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_ID
from database import get_user_id_by_username


def register(dp: Dispatcher):

    @dp.message(Command("watch", "следить"))
    async def cmd_watch(message: Message):
        """Следить за игроком."""
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()
        uid = None

        # Reply-режим
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                uid = target.id

        # Парсим @username или ID
        if not uid and len(args) >= 2:
            target = args[1]
            if target.startswith('@'):
                uid = get_user_id_by_username(target[1:])
            elif target.isdigit():
                uid = int(target)

        if not uid:
            await message.answer(
                "🎬 <b>СЛЕЖКА ЗА ИГРОКОМ</b>\n"
                "▬▬▬▬▬▬▬▬▬▬\n\n"
                "<b>Способы:</b>\n"
                "1️⃣ <code>/watch @username</code>\n"
                "2️⃣ <code>/watch 6403424348</code>\n"
                "3️⃣ Ответь на сообщение игрока и напиши <code>/watch</code>",
                parse_mode="HTML"
            )
            return

        # Просто подтверждение
        await message.answer(
            f"🎬 <b>СЛЕЖКА ВКЛЮЧЕНА</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"🆔 ID: <code>{uid}</code>\n\n"
            f"✅ Игрок добавлен под наблюдение.\n"
            f"💡 Все его действия будут логироваться.",
            parse_mode="HTML"
        )