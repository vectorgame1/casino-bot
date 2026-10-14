# ═══════════════════════════════════════════════════════════════
# admin/warn.py — ВАРН С ДИАЛОГОМ (3 = БАН)
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from config import ADMIN_ID
from database import get_conn, release_conn, get_user_id_by_username, set_banned
from admin.states import WarnStates


def register(dp: Dispatcher):

    @dp.message(Command("warn", "варн"))
    async def cmd_warn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()

        # Reply-режим
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                await state.update_data(uid=target.id, uname=target.username or target.first_name)
                await state.set_state(WarnStates.reason)
                await message.answer(
                    f"⚠️ <b>ВАРН</b>\n\n"
                    f"👤 Игрок: <b>{target.username or target.first_name}</b>\n\n"
                    f"📝 Введи причину:\n\n"
                    f"❌ Отмена: /cancel",
                    parse_mode="HTML"
                )
                return

        # @username в команде
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
            await state.set_state(WarnStates.reason)
            await message.answer(
                f"⚠️ <b>ВАРН</b>\n\n"
                f"👤 Игрок: <b>{target}</b>\n\n"
                f"📝 Введи причину:\n\n"
                f"❌ Отмена: /cancel",
                parse_mode="HTML"
            )
            return

        # Диалог
        await state.set_state(WarnStates.username)
        await message.answer(
            "⚠️ <b>ВАРН</b>\n\n"
            "👤 Введи @username или ID:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(WarnStates.username)
    async def warn_username(message: Message, state: FSMContext):
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
        await state.set_state(WarnStates.reason)
        await message.answer(
            f"👤 Игрок: <b>{text}</b>\n\n"
            f"📝 Введи причину:\n\n"
            f"❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    @dp.message(WarnStates.reason)
    async def warn_reason(message: Message, state: FSMContext):
        reason = message.text.strip()
        data = await state.get_data()
        uid = data.get("uid")

        # Считаем варны
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO alerts (user_id, alert_type, priority, text, status)
                     VALUES (%s, 'WARN', 'medium', %s, 'active')""",
                  (uid, reason))
        conn.commit()

        # Считаем количество активных варнов
        c.execute("""SELECT COUNT(*) FROM alerts 
                     WHERE user_id = %s AND alert_type = 'WARN' AND status = 'active'""",
                  (uid,))
        warns = c.fetchone()[0]
        c.close()
        release_conn(conn)

        # Если 3 варна — БАН
        if warns >= 3:
            set_banned(uid, True)
            try:
                await dp.bot.send_message(
                    uid,
                    f"🚫 <b>ВЫ ЗАБАНЕНЫ</b>\n"
                    f"▬▬▬▬▬▬▬▬▬▬\n\n"
                    f"Причина: <b>3 варна</b>\n\n"
                    f"💬 Обратитесь: @vctorw",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await message.answer(
                f"🚫 <b>ИГРОК ЗАБАНЕН</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬\n\n"
                f"🆔 ID: <code>{uid}</code>\n"
                f"⚠️ Причина: <b>3 варна</b>\n"
                f"📝 Последний: <b>{reason}</b>",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"⚠️ <b>ВАРН ВЫДАН</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬\n\n"
                f"🆔 ID: <code>{uid}</code>\n"
                f"📊 Варнов: <b>{warns}/3</b>\n"
                f"📝 Причина: <b>{reason}</b>",
                parse_mode="HTML"
            )

        await state.clear()