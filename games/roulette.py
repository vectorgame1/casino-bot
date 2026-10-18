# games/roulette.py
import asyncio
import random
from aiogram import Dispatcher, F
from aiogram.types import Message, FSInputFile
from database import get_balance, set_balance, ensure_user, is_banned, log_game
from utils import fmt_num

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

active_bets = {}

def get_color(num):
    if num == 0: return "🟢"
    if num in RED_NUMBERS: return "🔴"
    return "⚫"

def register(dp: Dispatcher):

    # ═══ СТАВКИ (ВКЛЮЧАЯ ДИАПАЗОНЫ) ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("к ", "ч ", "з ", "чёт ", "нечет ")))
    async def place_bet(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        chat_id = message.chat.id
        
        ensure_user(user_id, username)
        if is_banned(user_id): return

        parts = message.text.lower().split()
        if len(parts) != 2: return
        
        bet_type_str = parts[0]
        try: bet = int(parts[1])
        except ValueError: return
        
        if bet < 10:
            await message.reply("❌ Мин. ставка: 10 Tokens")
            return

        bal = get_balance(user_id)
        if bal < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {fmt_num(bal)}")
            return

        if bet_type_str == "к": bet_type = "red"
        elif bet_type_str == "ч": bet_type = "black"
        elif bet_type_str == "з": bet_type = "green"
        elif bet_type_str == "чёт": bet_type = "even"
        elif bet_type_str == "нечет": bet_type = "odd"
        else: return

        set_balance(user_id, -bet)
        
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username,
            "type": bet_type, "bet": bet
        })
        
        icon = {"red": "🔴", "black": "⚫", "green": "🟢", "even": "2️⃣", "odd": "1️⃣"}[bet_type]
        
        txt = (
            f"✅ <b>Ставка принята!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>{username}</b>\n"
            f"💰 Поставил: <b>{fmt_num(bet)}</b> на {icon}\n\n"
            f"🕐 Напиши «<code>го</code>» чтобы запустить"
        )
        await message.reply(txt, parse_mode="HTML")

    # ═══ СТАВКИ НА ДИАПАЗОН (например, "1000 10-33") ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("10-33 ", "1-18 ", "19-36 ")))
    async def place_range_bet(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        chat_id = message.chat.id
        
        ensure_user(user_id, username)
        if is_banned(user_id): return

        parts = message.text.lower().split()
        if len(parts) != 2: return
        
        try:
            bet = int(parts[0])
            range_str = parts[1]
        except ValueError: return

        if bet < 10:
            await message.reply("❌ Мин. ставка: 10 Tokens")
            return

        # Парсим диапазон (например, 10-33)
        try:
            start, end = map(int, range_str.split("-"))
            if not (0 <= start <= end <= 36):
                raise ValueError
        except:
            return

        bal = get_balance(user_id)
        if bal < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {fmt_num(bal)}")
            return

        set_balance(user_id, -bet)
        
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username,
            "type": "range", "range": (start, end), "bet": bet
        })
        
        txt = (
            f"✅ <b>Ставка на диапазон принята!</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 <b>{username}</b>\n"
            f"💰 Поставил: <b>{fmt_num(bet)}</b> на числа <b>{start}-{end}</b>\n\n"
            f"🕐 Напиши «<code>го</code>» чтобы запустить"
        )
        await message.reply(txt, parse_mode="HTML")

    # ═══ ПРОСМОТР СТАВОК ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "ставки")
    async def show_bets(message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("📊 <b>Сейчас нет активных ставок.</b>", parse_mode="HTML")
            return
            
        txt = "📊 <b>ТЕКУЩИЕ СТАВКИ</b>\n━━━━━━━━━━━━━━\n\n"
        icons = {"red": "🔴", "black": "⚫", "green": "🟢", "even": "2️⃣", "odd": "1️⃣"}
        
        for b in active_bets[chat_id]["bets"]:
            if b["type"] == "range":
                txt += f"👤 @{b['username']}: 🎯 <b>{b['range'][0]}-{b['range'][1]}</b> — {fmt_num(b['bet'])} Tokens\n"
            else:
                icon = icons[b["type"]]
                txt += f"👤 @{b['username']}: {icon} — {fmt_num(b['bet'])} Tokens\n"
            
        await message.reply(txt, parse_mode="HTML")

    # ═══ ЛОГ ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "лог")
    async def show_log(message: Message):
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT detail FROM game_log WHERE game = 'рулетка' ORDER BY id DESC LIMIT 10")
        rows = c.fetchall()
        c.close()
        release_conn(conn)
        
        if not rows:
            await message.reply("📜 История пока пуста.")
            return
            
        txt = "📜 <b>ПОСЛЕДНИЕ 10 ЧИСЕЛ</b>\n━━━━━━━━━━━━━━\n\n"
        for row in rows:
            txt += f"{row[0]} "
            
        await message.reply(txt, parse_mode="HTML")

    # ═══ ЗАПУСК ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет ставок! Сделай: <code>к 1000</code>", parse_mode="HTML")
            return
            
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet"] for b in bets)
        
        # Отправляем гифку
        try:
            gif = FSInputFile("roulette.gif")
            msg = await message.reply_animation(animation=gif, caption=f"🎡 <b>РУЛЕТКА КРУТИТСЯ...</b>\n💰 Банк: <b>{fmt_num(total_bank)}</b>")
        except Exception:
            msg = await message.reply(f"🎡 <b>РУЛЕТКА КРУТИТСЯ...</b>\n💰 Банк: <b>{fmt_num(total_bank)}</b>")
            
        await asyncio.sleep(2.5)
        
        result = random.randint(0, 36)
        color = get_color(result)
        
        winners = []
        losers = []
        
        for b in bets:
            win_amount = 0
            
            if b["type"] == "red" and result in RED_NUMBERS: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "black" and result in BLACK_NUMBERS: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "green" and result == 0: win_amount = int(b["bet"] * 35)
            elif b["type"] == "even" and result != 0 and result % 2 == 0: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "odd" and result % 2 != 0: win_amount = int(b["bet"] * 1.95)
            elif b["type"] == "range":
                start, end = b["range"]
                if start <= result <= end:
                    # Коэффициент для диапазона зависит от количества чисел
                    count = end - start + 1
                    multiplier = round(36 / count * 0.95, 2)  # RTP ~95%
                    win_amount = int(b["bet"] * multiplier)
                
            if win_amount > 0:
                set_balance(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], win_amount, f"{result} {color}")
                winners.append(f"🏆 @{b['username']} — <b>+{fmt_num(win_amount)}</b>")
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], 0, f"{result} {color}")
                losers.append(f"😢 @{b['username']}")
                
        txt = f"🎡 <b>ВЫПАЛО: {color} {result}</b>\n━━━━━━━━━━━━━━\n\n"
        if winners: txt += "🎉 <b>Победители:</b>\n" + "\n".join(winners) + "\n\n"
        if losers: txt += "💔 <b>Проиграли:</b>\n" + "\n".join(losers)
            
        try:
            await msg.edit_caption(caption=txt)
        except:
            await msg.edit_text(txt)

        del active_bets[chat_id]

    # ═══ ОТМЕНА ═══
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "отмена")
    async def cancel_bets(message: Message):
        chat_id = message.chat.id
        user_id = message.from_user.id
        if chat_id in active_bets:
            my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == user_id]
            if my_bets:
                refund = sum(b["bet"] for b in my_bets)
                set_balance(user_id, refund)
                active_bets[chat_id]["bets"] = [b for b in active_bets[chat_id]["bets"] if b["user_id"] != user_id]
                await message.reply(f"❌ Отменено. Возвращено {fmt_num(refund)} Tokens.")