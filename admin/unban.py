# ═══════════════════════════════════════════════════════════════
# admin/unban.py — РАЗБАН И РАЗМУТ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_ID
from database import get_user_id_by_username, set_banned, cache_invalidate, get_conn, release_conn


def register(dp: Dispatcher):

    @dp.message(Command("unban", "разбан"))
    async def cmd_unban(message: Message):
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()
        uid = None

        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                uid = target.id

        if not uid and len(args) >= 2:
            target = args[1]
            if target.startswith('@'):
                uid = get_user_id_by_username(target[1:])
            elif target.isdigit():
                uid = int(target)

        if not uid:
            await message.answer("❌ Игрок не найден")
            return

        set_banned(uid, False)
        cache_invalidate(f"banned_{uid}")

        try:
            await dp.bot.send_message(
                uid,
                "✅ <b>ВЫ РАЗБАНЕНЫ</b>\n\n💬 Не нарушайте правила!",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await message.answer(
            f"✅ <b>ИГРОК РАЗБАНЕН</b>\n\n🆔 ID: <code>{uid}</code>",
            parse_mode="HTML"
        )

    @dp.message(Command("unmute", "размут"))
    async def cmd_unmute(message: Message):
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()
        uid = None

        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                uid = target.id

        if not uid and len(args) >= 2:
            target = args[1]
            if target.startswith('@'):
                uid = get_user_id_by_username(target[1:])
            elif target.isdigit():
                uid = int(target)

        if not uid:
            await message.answer("❌ Игрок не найден")
            return

        # Убираем мут из БД
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM alerts WHERE user_id = %s AND alert_type = 'MUTE'", (uid,))
            conn.commit()
            c.close()
            release_conn(conn)
        except Exception as e:
            print(f"[unmute] {e}")

        try:
            await dp.bot.send_message(
                uid,
                "🔊 <b>ВЫ РАЗМУЧЕНЫ</b>\n\n💬 Не нарушайте правила!",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await message.answer(
            f"🔊 <b>ИГРОК РАЗМУЧЕН</b>\n\n🆔 ID: <code>{uid}</code>",
            parse_mode="HTML"
        )