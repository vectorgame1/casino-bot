# admin.py — v61 (АДМИНКА И МОДЕРАЦИЯ)
import asyncio, time, random
from datetime import datetime, timedelta
from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ChatPermissions
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from config import ADMIN_ID, TZ_MINSK, BOT_NAME
from database import get_balance, set_balance, get_conn, release_conn, ensure_user, is_banned, set_banned, get_user_id_by_username
from utils import fmt_num, send_clean
from state_manager import load_mods, save_mods, refresh_week

admin_router = Router()
mod_router = Router()

MODS, MOD_LIMITS = load_mods()
MAX_MOD_GIVE = 5_000_000
user_warns = {}
muted_users = {}
GLOBAL_MUTE = False
GLOBAL_MUTE_TASK = None
BAD_WORDS = ["хуй", "хуя", "хую", "хуе", "хуи", "хуйн", "хуес", "хуеп", "хуит", "пизд", "пизж", "пизда", "пизде", "пизду", "пиздо", "пиздюл", "пиздоб", "бля", "блят", "блядь", "бляди", "блядю", "блядо", "бляду", "сука", "суки", "суке", "суку", "сукой", "сучк", "сучон", "ебал", "ебат", "ебуч", "ебан", "еби", "ебуч", "ебук", "ебани", "мудак", "мудил", "м��день", "мудозвон", "долбоеб", "долбаеб", "долбоёб", "долбаёб", "гандон", "гондон", "залуп", "залупа", "залупу", "залупой", "залупок", "пидор", "пидар", "пидорас", "пидорасина", "хуесос", "хуесосина", "отъеб", "въеб", "съеб", "заеб", "уеб", "наеб", "поъеб", "приеб", "проеб", "разъеб", "жопа", "жопу", "жопой", "жопе", "срать", "срал", "сру", "хер", "хрен", "член", "шлюх", "проститут", "дроч"]

async def delete_message_later(message: Message, delay: int = 150):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass


def _now(): return datetime.now(TZ_MINSK)

# ============================================================
# БЛОК 1. ФУНКЦИЯ СВЯЗЫВАНИЯ (Setup)
# ============================================================
def setup_admin_mod_handlers(dp: Dispatcher, bot: Bot, BotStates):
    """
    Эта функция вызывается из bot.py, чтобы передать нужные классы 
    и состояния в этот файл.
    """
    
    # ========================================================
    # БЛОК 2. МОДЕРАЦИЯ
    # ========================================================
    @mod_router.message(Command("mod_help", "помощь_модеру"))
    async def cmd_mod_help(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        txt = (
            "🛠 <b>МОДЕРАТОР — RU / EN</b>\n\n"
            "• <code>/mute 10</code> (Reply) — Мут на 10 мин\n"
            "• <code>/unmute</code> (Reply) — Снять мут\n"
            "• <code>/warn</code> (Reply) — Предупреждение\n"
            "• <code>/kick</code> (Reply) — Кик\n"
            "• <code>/clean</code> (Reply) — Удалить сообщения\n"
            "• <code>/mod_clean</code> — Очистить 100 сообщений\n"
            "• <code>/mod_my_limit</code> — Мои лимиты\n\n"
            "👇 <i>Используй Reply-кнопки.</i>"
        )
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt)
        except: await message.answer(txt)

    @mod_router.message(Command("mute"))
    async def mod_mute_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        try: mins = int(message.text.split()[1])
        except: return await message.reply("❌ /mute 10")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.restrict_chat_member(message.chat.id, uid, ChatPermissions(can_send_messages=False), until_date=_now() + timedelta(minutes=mins))
            await message.reply(f"🚫 Игрок замучен на {mins} мин.")
        except: await message.reply("❌ Не могу замутить.")

    @mod_router.message(Command("unmute"))
    async def mod_unmute_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.restrict_chat_member(message.chat.id, uid, ChatPermissions(can_send_messages=True))
            await message.reply("✅ Мут снят.")
        except: await message.reply("❌ Не могу снять мут.")

    @mod_router.message(Command("warn"))
    async def mod_warn_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        if uid not in user_warns: user_warns[uid] = {"count": 0, "time": _now(), "last_msg": None, "spam_count": 0}
        user_warns[uid]["count"] += 1
        if user_warns[uid]["count"] >= 3:
            del user_warns[uid]
            muted_users[uid] = _now() + timedelta(hours=1)
            await message.reply(f"🚫 Игрок получил 3/3 варна и мут на 1 час.")
        else:
            await message.reply(f"⚠️ Предупреждение {user_warns[uid]['count']}/3.")

    @mod_router.message(Command("kick"))
    async def mod_kick_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.ban_chat_member(message.chat.id, uid)
            await message.bot.unban_chat_member(message.chat.id, uid)
            await message.reply("✅ Игрок кикнут.")
        except: await message.reply("❌ Не могу кикнуть.")

    @mod_router.message(F.text == "🧹 Очистить")
    @mod_router.message(Command("mod_clean", "очистить_чат"))
    async def mod_clean_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID: return
        deleted = 0
        try:
            async for m in message.bot.get_chat_history(message.chat.id, limit=100):
                try: await m.delete(); deleted += 1
                except: pass
        except: pass
        try:
            info = await message.answer(f"🧹 Удалено: <b>{deleted}</b>")
            await asyncio.sleep(3); await info.delete()
        except: pass

    @mod_router.message(Command("mod_my_limit", "мои_лимиты"))
    @mod_router.message(F.text == "📊 Мои лимиты")
    async def mod_my_limit(message: Message):
        uid = message.from_user.id
        if uid not in MODS: return
        lim = refresh_week(uid, MOD_LIMITS)
        save_mods(MODS, MOD_LIMITS)
        given = lim["given"]
        left = MAX_MOD_GIVE - given
        await message.reply(f"📊 <b>ТВОИ ЛИМИТЫ</b>\n\nВыдано: <b>{fmt_num(given)}</b>\nОсталось: <b>{fmt_num(left)}</b>")

    # ========================================================
    # БЛОК 3. АДМИНКА
    # ========================================================
    @admin_router.message(Command("admin_help", "помощь_админу"))
    async def cmd_admin_help(message: Message):
        if message.from_user.id != ADMIN_ID: return
        txt = (
            "👑 <b>АДМИН — RU / EN</b>\n\n"
            "• <code>/userinfo @user</code> — Досье / Info\n"
            "• <code>/msg @user text</code> — ЛС от админа / DM\n"
            "• <code>/spy @user</code> — Активность 24ч / Spy\n"
            "• <code>/freeze @user</code> — Заморозка / Freeze\n"
            "• <code>/promo_create CODE 5000 100</code> — Промокод\n"
            "• <code>/maintenance on/off</code> — Тех.работы\n"
            "• <code>/event 100000</code> — Ивент-дроп\n"
            "• <code>/broadcast_text</code> — Рассылка текстом\n"
            "• <code>/sys_info</code> — Инфо о боте\n\n"
            "👇 <i>Ответ на тикет игрока делается через Reply!</i>"
        )
        try: await message.answer_photo(FSInputFile("powertext_ru_1792346951926.png"), caption=txt)
        except: await message.answer(txt)

    @admin_router.message(Command("userinfo"))
    async def admin_userinfo(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message and len(message.text.split()) != 2:
            return await message.reply("❌ /userinfo @user или Reply")
        
        if message.reply_to_message:
            uid = message.reply_to_message.from_user.id
        else:
            target = message.text.split()[1].replace("@", "")
            uid = int(target) if target.isdigit() else get_user_id_by_username(target)
            
        if not uid: return await message.reply("❌ Не найден.")
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT username, balance, bank, credit_debt, xp, banned FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            if not row: return await message.reply("❌ Нет в базе.")
            uname, bal, bank, debt, xp, banned = row
            status = "🚫 Бан" if banned else "✅ Активен"
            txt = f"🕵️ <b>ДОСЬЕ</b>\n👤 @{uname}\n🆔 <code>{uid}</code>\nСтатус: {status}\n💰 Баланс: {fmt_num(bal)}\n🏦 Банк: {fmt_num(bank or 0)}\n💳 Долг: {fmt_num(debt or 0)}\n⭐ XP: {xp}"
            await message.reply(txt)
        finally:
            c.close(); release_conn(conn)

    @admin_router.message(Command("spy"))
    async def admin_spy(message: Message):
        if message.from_user.id != ADMIN_ID: return
        if not message.reply_to_message: return await message.reply("❌ Ответь на сообщение игрока.")
        uid = message.reply_to_message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT game, bet, win FROM game_log WHERE user_id = %s ORDER BY id DESC LIMIT 5", (uid,))
            rows = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        if not rows: return await message.reply("🕵️ Игрок не играл.")
        txt = "🕵️ <b>ПОСЛЕДНИЕ 5 ИГР</b>\n\n"
        for g, b, w in rows:
            txt += f"• {g} | Ставка: {fmt_num(b)} | Выигрыш: {fmt_num(w)}\n"
        await message.reply(txt)

    @admin_router.message(Command("msg"))
    async def admin_msg(message: Message):
        if message.from_user.id != ADMIN_ID: return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3: return await message.reply("❌ /msg @user Текст")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid: return await message.reply("❌ Не найден.")
        try:
            await message.bot.send_message(uid, f"👑 <b>СООБЩЕНИЕ ОТ АДМИНА:</b>\n\n{parts[2]}")
            await message.reply("✅ Отправлено.")
        except: await message.reply("❌ Ошибка.")

    @admin_router.message(Command("sys_info"))
    async def admin_sys_info(message: Message):
        if message.from_user.id != ADMIN_ID: return
        import platform
        txt = f"💻 <b>СИСТЕМА</b>\nPython: {platform.python_version()}\nИгр в памяти: {len(active_bets) if 'active_bets' in globals() else 0}\nВ муте: {len(muted_users)}"
        await message.reply(txt)

    @admin_router.message(Command("broadcast_text"))
    async def admin_broadcast_text(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await message.reply("📢 Отправь текст для рассылки (или 'отмена'):")
        await state.set_state(BotStates.waiting_broadcast_text)

    @admin_router.message(BotStates.waiting_broadcast_text)
    async def process_broadcast_text(message: Message, state: FSMContext):
        if message.text.lower() == "отмена":
            await state.clear()
            return await message.reply("❌ Отменено.")
        await state.clear()
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT user_id FROM users")
            users = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        sent = 0
        await message.reply("⏳ Рассылка...")
        for (uid,) in users:
            try:
                await message.bot.send_message(uid, message.text)
                sent += 1
                await asyncio.sleep(0.05)
            except: pass
        await message.reply(f"✅ Отправлено: {sent}")

    # ========================================================
    # БЛОК 4. АВТО-МОДЕРАТОР
    # ========================================================
    @admin_router.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if not message.from_user or message.from_user.id == ADMIN_ID or message.from_user.is_bot: return
        if message.text and (message.text.startswith("/") or message.text.lower().strip() in ["б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го", "что нового", "отмена", "ставки", "п"]): return
        if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: return
        
        uid = message.from_user.id
        now = _now()
        
        if GLOBAL_MUTE and uid != ADMIN_ID:
            try: await message.delete()
            except: pass
            return
            
        if uid in muted_users:
            if now < muted_users[uid]:
                try: await message.delete()
                except: pass
                return 
            else: del muted_users[uid]
                
        is_bad = False
        if message.text:
            text_lower = message.text.lower()
            if any(word in text_lower for word in BAD_WORDS): is_bad = True
                
        is_caps = False
        if message.text and len(message.text) > 5:
            caps_count = sum(1 for c in message.text if c.isupper())
            if caps_count / len(message.text) > 0.7: is_caps = True
                
        is_spam = False
        if uid in user_warns and user_warns[uid].get("last_msg") == message.text:
            user_warns[uid]["spam_count"] = user_warns[uid].get("spam_count", 0) + 1
            if user_warns[uid]["spam_count"] >= 5: is_spam = True
        else:
            if uid in user_warns: user_warns[uid]["spam_count"] = 0
                
        if not (is_bad or is_caps or is_spam): return
            
        try: await message.delete()
        except: pass
            
        if uid not in user_warns: user_warns[uid] = {"count": 0, "time": now, "last_msg": None, "spam_count": 0}
        if (now - user_warns[uid]["time"]).total_seconds() > 3600: user_warns[uid]["count"] = 0
            
        user_warns[uid]["count"] += 1
        user_warns[uid]["time"] = now
        user_warns[uid]["last_msg"] = message.text
        count = user_warns[uid]["count"]
        reason = "мат" if is_bad else ("капс" if is_caps else "спам")
            
        if count >= 3 or is_spam:
            mute_time = 10 if is_spam else 24
            muted_users[uid] = now + timedelta(minutes=mute_time)
            del user_warns[uid]
            try: await message.answer(f"🚫 <b>МУТ</b>\n@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}.")
            except: pass
        else:
            try:
                msg = await message.reply(f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!")
                asyncio.create_task(delete_message_later(msg, 30))
            except: pass