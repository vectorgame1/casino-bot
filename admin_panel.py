# admin_panel.py
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

from config import ADMIN_ID, BOT_NAME
from database import set_balance, get_user_id_by_username, get_balance, set_banned
from utils import send_clean, fmt_num

def register(dp: Dispatcher):

    @dp.message(Command("admin"))
    async def cmd_admin(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        await message.answer(
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"💎 Бот: <b>{BOT_NAME}</b>\n"
            f"👇 Доступные команды:\n\n"
            f"<code>/give @user 1000</code> — выдать токены\n"
            f"<code>/ban @user</code> — забанить\n"
            f"<code>/unban @user</code> — разбанить\n"
            f"<code>/курс 8000</code> — изменить курс доната\n",
            parse_mode="HTML"
        )

    @dp.message(Command("give"))
    async def cmd_give(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        
        args = message.text.split()
        if len(args) < 3:
            await message.answer("❌ Использование: <code>/give @username 1000</code>", parse_mode="HTML")
            return

        target_username = args[1].replace("@", "")
        try:
            amount = int(args[2])
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            return

        target_uid = get_user_id_by_username(target_username)
        if not target_uid:
            await message.answer(f"❌ Игрок @{target_username} не найден в базе.")
            return

        new_bal = set_balance(target_uid, amount)
        await message.answer(
            f"✅ <b>Выдано!</b>\n\n"
            f"👤 Игрок: @{target_username}\n"
            f"💰 Сумма: <b>+{fmt_num(amount)}</b> Tokens\n"
            f"💎 Новый баланс: <b>{fmt_num(new_bal)}</b>",
            parse_mode="HTML"
        )

    @dp.message(Command("ban"))
    async def cmd_ban(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: <code>/ban @username</code>", parse_mode="HTML")
            return

        target_username = args[1].replace("@", "")
        target_uid = get_user_id_by_username(target_username)
        
        if not target_uid:
            await message.answer(f"❌ Игрок @{target_username} не найден.")
            return

        set_banned(target_uid, True)
        await message.answer(f"🚫 Игрок @{target_username} забанен.", parse_mode="HTML")

    @dp.message(Command("unban"))
    async def cmd_unban(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("❌ Использование: <code>/unban @username</code>", parse_mode="HTML")
            return

        target_username = args[1].replace("@", "")
        target_uid = get_user_id_by_username(target_username)
        
        if not target_uid:
            await message.answer(f"❌ Игрок @{target_username} не найден.")
            return

        set_banned(target_uid, False)
        await message.answer(f"✅ Игрок @{target_username} разбанен.", parse_mode="HTML")