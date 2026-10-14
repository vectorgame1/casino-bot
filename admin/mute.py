# ═══════════════════════════════════════════════════════════════
# admin/mute.py — МУТ С ДИАЛОГОМ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta

from config import ADMIN_ID, TZ_MINSK
from database import (
    get_conn, release_conn, get_user_id_by_username,
    get_user, ensure_user,
)
from admin.states import MuteStates


# Хранилище мутов
muted_users = {}  # {user_id: until_datetime}


def is_muted(uid: int) -> bool:
    """Проверяет, замучен ли игрок."""
    if uid not in muted_users:
        return False
    until = muted_users[uid]
    if datetime.now(TZ_MINSK) > until:
        del muted_users[uid]
        return False
    return True


def register(dp: Dispatcher):

    # ═══ КОМАНДА /мут ═══

    @dp.message(Command("mute", "мут"))
    async def cmd_mute(message: Message, state: FSMContext):
        """Запуск диалога мута."""
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()

        # Reply-режим
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                await state.update_data(uid=target.id, uname=target.username or target.first_name)
                await state.set_state(MuteStates.duration)
                await message.answer(
                    f"🔇 <b>МУТ</b>\n"
                    f"▬▬▬▬▬▬▬▬▬▬\n\n"
                    f"👤 Игрок: <b>{target.username or target.first_name}</b>\n\n"
                    f"⏱ На сколько? (1m / 1h / 1d)\n\n"
                    f"❌ Отмена: /cancel",
                    parse_mode="HTML"
                )
                return

        # Если есть @username в команде
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
            await state.set_state(MuteStates.duration)
            await message.answer(
                f"🔇 <b>МУТ</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬\n\n"
                f"👤 Игрок: <b>{target}</b>\n\n"
                f"⏱ На сколько? (1m / 1h / 1d)\n\n"
                f"❌ Отмена: /cancel",
                parse_mode="HTML"
            )
            return

        # Иначе — запускаем диалог
        await state.set_state(MuteStates.username)
        await message.answer(
            "🔇 <b>МУТ</b>\n"
            "▬▬▬▬▬▬▬▬▬▬\n\n"
            "👤 Введи @username или ID игрока:\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    # ═══ ВВОД USERNAME ═══

    @dp.message(MuteStates.username)
    async def mute_username(message: Message, state: FSMContext):
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
        await state.set_state(MuteStates.duration)
        await message.answer(
            f"👤 Игрок: <b>{text}</b>\n\n"
            f"⏱ На сколько? (1m / 1h / 1d)\n\n"
            f"❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    # ═══ ВВОД ВРЕМЕНИ ═══

    @dp.message(MuteStates.duration)
    async def mute_duration(message: Message, state: FSMContext):
        text = message.text.strip().lower()
        seconds = 3600

        try:
            if text.endswith('m'):
                seconds = int(text[:-1]) * 60
            elif text.endswith('h'):
                seconds = int(text[:-1]) * 3600
            elif text.endswith('d'):
                seconds = int(text[:-1]) * 86400
            elif text.isdigit():
                seconds = int(text) * 60
            else:
                await message.answer("❌ Формат: 1m, 1h, 1d. Попробуй ещё:")
                return
        except Exception:
            await message.answer("❌ Формат: 1m, 1h, 1d. Попробуй ещё:")
            return

        await state.update_data(seconds=seconds)
        await state.set_state(MuteStates.reason)
        await message.answer(
            "📝 Причина?\n\n"
            "❌ Отмена: /cancel",
            parse_mode="HTML"
        )

    # ═══ ВВОД ПРИЧИНЫ ═══

    @dp.message(MuteStates.reason)
    async def mute_reason(message: Message, state: FSMContext):
        reason = message.text.strip()
        data = await state.get_data()
        uid = data.get("uid")
        seconds = data.get("seconds", 3600)

        until = datetime.now(TZ_MINSK) + timedelta(seconds=seconds)
        muted_users[uid] = until

        # Уведомляем игрока
        try:
            await dp.bot.send_message(
                uid,
                f"🔇 <b>ВЫ ЗАМУЧЕНЫ</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬\n\n"
                f"⏱ До: <b>{until.strftime('%d.%m %H:%M')}</b>\n"
                f"📝 Причина: <b>{reason}</b>\n\n"
                f"💬 Обратитесь: @vctorw",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await message.answer(
            f"✅ <b>ИГРОК ЗАМУЧЕН</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"⏱ До: <b>{until.strftime('%d.%m %H:%M')}</b>\n"
            f"📝 Причина: <b>{reason}</b>",
            parse_mode="HTML"
        )
        await state.clear()

    # ═══ ОТМЕНА ═══

    @dp.message(Command("cancel", "отмена"))
    async def cmd_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Отменено")