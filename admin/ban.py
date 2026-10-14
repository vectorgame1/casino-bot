# ═══════════════════════════════════════════════════════════════
# admin/ban.py — БАН С ДИАЛОГОМ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from config import ADMIN_ID
from database import get_user_id_by_username, set_banned, cache_invalidate
from admin.states import BanStates


def register(dp: Dispatcher):

    @dp.message(Command("ban", "бан"))
    async def cmd_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()

        # Reply-режим
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                await state.update_data(uid=target.id, uname=target.username or target.first_name)
                await state.set_state(BanStates.reason)
                await message.answer(
                    f"🚫 <b>БАН</b>\n\n"
                    f"👤 Игрок: <b>{target.username or target.first_name}</b>\n\n"
                    f"📝 Введи причину:\n\n"
                    f"❌ Отмена: /cancel",
                    parse_mode="HTML"
                )
                return

        if len(args) >= 2:
            target = args[1]
            uid = None
            if target.startswith('@'):
                uid = get_user_id_by_username(target[1:])
            elif target.isdigit():
                uid = int(target)

            if not uid:
                await message.answer("❌ Игрок не найден")
                return

            await state.update_data(uid=uid, uname=target)
            await state.set_state(BanStates.reason)
            await message.answer(
                f"🚫 <b>БАН</b>\n\n"
                f"👤 Игрок: <b>{target}</b>\n\n"
                f"📝 Введи причину:\n\n"
                f"❌ Отмена: /cancel",
                parse_mode="HTML"
            )
            return

        await state.set_state(BanStates.username)
        await message.answer(
            "🚫 <b>БАН</b>\n\n"
            "👤 Введи @username или ID:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(BanStates.username)
    async def ban_username(message: Message, state: FSMContext):
        text = message.text.strip()
        uid = None

        if text.startswith('@'):
            uid = get_user_id_by_username(text[1:])
        elif text.isdigit():
            uid = int(text)

        if not uid:
            await message.answer("❌ Игрок не найден. Попробуй ещё:")
            return

        await state.update_data(uid=uid, uname=text)
        await state.set_state(BanStates.reason)
        await message.answer(
            f"👤 Игрок: <b>{text}</b>\n\n"
            f"📝 Введи причину:\n\n"
            f"❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(BanStates.reason)
    async def ban_reason(message: Message, state: FSMContext):
        reason = message.text.strip()
        data = await state.get_data()
        uid = data.get("uid")

        set_banned(uid, True)
        cache_invalidate(f"banned_{uid}")

        try:
            await dp.bot.send_message(
                uid,
                f"🚫 <b>ВЫ ЗАБАНЕНЫ</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬\n\n"
                f"📝 Причина: <b>{reason}</b>\n\n"
                f"💬 Обратитесь: @vctorw",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await message.answer(
            f"🚫 <b>ИГРОК ЗАБАНЕН</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"📝 Причина: <b>{reason}</b>",
            parse_mode="HTML"
        )
        await state.clear()