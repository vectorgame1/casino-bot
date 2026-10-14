# ═══════════════════════════════════════════════════════════════
# admin/bans_list.py — СПИСКИ БАНОВ
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_ID
from database import get_conn, release_conn, get_user_id_by_username


def register(dp: Dispatcher):

    @dp.message(Command("bans", "баны"))
    async def cmd_bans(message: Message):
        if message.from_user.id != ADMIN_ID:
            return

        conn = get_conn()
        c = conn.cursor()
        c.execute("""SELECT user_id, username FROM users 
                     WHERE banned = TRUE LIMIT 50""")
        rows = c.fetchall()
        c.close()
        release_conn(conn)

        if not rows:
            await message.answer("✅ Забаненных нет")
            return

        txt = f"🚫 <b>СПИСОК БАНОВ ({len(rows)})</b>\n▬▬▬▬▬▬▬▬▬▬\n\n"
        for uid, uname in rows:
            txt += f"• <b>{uname or f'user_{uid}'}</b> — <code>{uid}</code>\n"

        await message.answer(txt, parse_mode="HTML")

    @dp.message(Command("banhistory", "историябанов"))
    async def cmd_banhistory(message: Message):
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

        conn = get_conn()
        c = conn.cursor()
        c.execute("""SELECT alert_type, text, created_at FROM alerts 
                     WHERE user_id = %s AND alert_type IN ('WARN', 'MUTE', 'BAN')
                     ORDER BY id DESC LIMIT 20""", (uid,))
        rows = c.fetchall()
        c.close()
        release_conn(conn)

        if not rows:
            await message.answer(f"📜 <b>История пуста</b> (ID: <code>{uid}</code>)", parse_mode="HTML")
            return

        txt = f"📜 <b>ИСТОРИЯ</b> (ID: <code>{uid}</code>)\n▬▬▬▬▬▬▬▬▬▬\n\n"
        for atype, text_, created in rows:
            date = created.strftime('%d.%m %H:%M') if created else '?'
            emoji = {'WARN': '⚠️', 'MUTE': '🔇', 'BAN': '🚫'}.get(atype, '❓')
            txt += f"{emoji} <b>{atype}</b> — {date}\n   {text_}\n\n"

        await message.answer(txt, parse_mode="HTML")