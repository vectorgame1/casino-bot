import asyncio
import logging
import sqlite3
import os
import threading
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask, jsonify, request
from flask_cors import CORS

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DB_PATH = "casino.db"

RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]

# ========== АКТИВНЫЕ СТАВКИ (в памяти) ==========
# {chat_id: {"bets": [{"user_id":.., "username":.., "type":.., "bet":.., "number":..}], "timer": None}}
active_bets = {}

# ========== ВЕБ-СЕРВЕР ==========
app = Flask(__name__)
CORS(app)

@app.route('/')
def home(): return "Bot is running!"
@app.route('/health')
def health(): return "OK"
@app.route('/api/balance/<int:user_id>')
def api_balance(user_id): return jsonify({"user_id": user_id, "balance": get_balance(user_id)})
@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    uid = data.get('user_id'); amt = data.get('amount')
    if uid is None or amt is None: return jsonify({"error": "Missing"}), 400
    return jsonify({"user_id": uid, "balance": set_balance(uid, amt)})

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_web, daemon=True).start()

# ========== БАЗА ==========
def init_db():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000)")
    c.execute("""CREATE TABLE IF NOT EXISTS game_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, game TEXT,
        bet INTEGER, win INTEGER, detail TEXT, time TEXT
    )""")
    conn.commit(); conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone(); conn.close(); return row

def ensure_user(user_id, username):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit(); conn.close()

def set_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone(); conn.close(); return row[0] if row else 0

def get_top(limit=10):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    rows = c.fetchall(); conn.close(); return rows

def get_balance(user_id):
    user = get_user(user_id); return user[1] if user else 1000

def log_game(user_id, username, game, bet, win, detail):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO game_log (user_id, username, game, bet, win, detail, time) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_id, username, game, bet, win, detail, datetime.now().strftime("%H:%M:%S")))
    conn.commit(); conn.close()

def get_last_games(limit=10):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT username, game, bet, win, detail, time FROM game_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall(); conn.close(); return rows

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="menu_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="menu_slots")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="menu_coin"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top"),
         InlineKeyboardButton(text="📜 Лог", callback_data="menu_log")]
    ])

def roulette_kb(bet=100):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное ×2", callback_data=f"bet_red_{bet}"),
         InlineKeyboardButton(text="⚫ Чёрное ×2", callback_data=f"bet_black_{bet}")],
        [InlineKeyboardButton(text="🟢 Зеро ×36", callback_data=f"bet_green_{bet}")],
        [InlineKeyboardButton(text="10", callback_data="setbet_10"),
         InlineKeyboardButton(text="100", callback_data="setbet_100"),
         InlineKeyboardButton(text="1K", callback_data="setbet_1000"),
         InlineKeyboardButton(text="MAX", callback_data="setbet_max")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
    ])

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    balance = get_balance(user_id)
    text = (
        f"🎰 <b>WORLD CASINO</b>\n\n"
        f"👤 {username}\n"
        f"💎 <b>{balance:,}</b> фишек\n\n"
        f"🎮 <b>Команды:</b>\n"
        f"<code>б</code> — баланс\n"
        f"<code>го</code> — рулетка\n"
        f"<code>с 100</code> — слоты\n"
        f"<code>м 100 о</code> — монетка\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — история\n\n"
        f"🎡 <b>Ставки в группе:</b>\n"
        f"<code>к 1000</code> — красное\n"
        f"<code>ч 1000</code> — чёрное\n"
        f"<code>з 1000</code> — зеро\n"
        f"<code>1000 5</code> — число\n"
        f"<code>го</code> — запуск\n"
        f"<code>отмена</code> — отменить"
    ).replace(',', ' ')
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    balance = get_balance(user_id)
    await message.answer(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 <b>{balance:,}</b> фишек".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = get_top(10)
    if not rows:
        await message.answer("📊 <b>Пока нет игроков!</b>", parse_mode="HTML"); return
    text = "🏆 <b>ТОП-10</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, uname, bal) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        f"❓ <b>Помощь</b>\n\n"
        f"💬 <b>Команды:</b>\n"
        f"<code>б</code> — баланс\n"
        f"<code>го</code> — рулетка\n"
        f"<code>с 100</code> — слоты\n"
        f"<code>м 100 о</code> — монетка\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — лог\n\n"
        f"🎡 <b>Ставки:</b>\n"
        f"<code>к/ч/з 100</code> — цвет\n"
        f"<code>100 7</code> — число\n\n"
        f"👑 <b>Админ:</b>\n"
        f"<code>/give @user 1000</code>\n"
        f"<code>/take @user 1000</code>",
        parse_mode="HTML"
    )

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try: amount = int(args[2])
        except: return
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        row = c.fetchone(); conn.close()
        if not row:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML"); return
        nb = set_balance(row[0], amount)
        await message.answer(f"✅ <b>+{amount:,}</b> → @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML"); return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot: return
    if len(args) < 2: return
    try: amount = int(args[1])
    except: return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, amount)
    await message.answer(f"✅ <b>+{amount:,}</b> → {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("take"))
async def cmd_take(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try: amount = int(args[2])
        except: return
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        row = c.fetchone(); conn.close()
        if not row:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML"); return
        nb = set_balance(row[0], -amount)
        await message.answer(f"✅ <b>-{amount:,}</b> ← @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML"); return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot: return
    if len(args) < 2: return
    try: amount = int(args[1])
    except: return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, -amount)
    await message.answer(f"✅ <b>-{amount:,}</b> ← {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")

# ========== ОТМЕНА СТАВОК ==========
async def cancel_bets(chat_id):
    if chat_id in active_bets:
        bets = active_bets[chat_id]["bets"]
        for b in bets:
            set_balance(b["user_id"], b["bet"])
        del active_bets[chat_id]

# ========== ЛОГИКА СТАВОК В ГРУППЕ ==========
async def add_bet(message, user_id, username, bet_type, bet, number=None):
    chat_id = message.chat.id
    if chat_id not in active_bets:
        active_bets[chat_id] = {"bets": []}
    
    balance = get_balance(user_id)
    if bet < 10:
        await message.reply("❌ Минимум 10 фишек!"); return
    if balance < bet:
        await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
    
    set_balance(user_id, -bet)
    
    bet_info = {"user_id": user_id, "username": username, "type": bet_type, "bet": bet, "number": number}
    active_bets[chat_id]["bets"].append(bet_info)
    
    bets = active_bets[chat_id]["bets"]
    bets_text = "📊 <b>Ваши ставки:</b>\n\n"
    for b in bets:
        if b["type"] == "red": desc = "🔴 Красное"
        elif b["type"] == "black": desc = "⚫ Чёрное"
        elif b["type"] == "green": desc = "🟢 Зеро"
        elif b["type"] == "number": desc = f"🎯 Число {b['number']}"
        else: desc = b["type"]
        bets_text += f"👤 {b['username']} — {desc} × <b>{b['bet']:,}</b>\n".replace(',', ' ')
    
    bets_text += f"\n⚡ <b>Всего ставок:</b> {len(bets)}\n"
    bets_text += f"💰 <b>Банк:</b> {sum(b['bet'] for b in bets):,}\n\n".replace(',', ' ')
    bets_text += f"🕐 Напиши <code>го</code> для запуска\n"
    bets_text += f"❌ Или <code>отмена</code> для отмены"
    
    await message.reply(bets_text, parse_mode="HTML")

# ========== ВСЕ КОМАНДЫ ==========
@dp.message()
async def text_handler(message: Message):
    if not message.text: return
    if message.from_user.is_bot: return
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    ensure_user(user_id, username)

    # ========== ОТМЕНА ==========
    if text in ['отмена', 'отменить']:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            await cancel_bets(chat_id)
            await message.reply(f"❌ <b>Ставки отменены!</b>\n\nВозвращено {count} ставок.", parse_mode="HTML")
        return

    # ========== БАЛАНС ==========
    if text in ['б', 'баланс']:
        balance = get_balance(user_id)
        await message.reply(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 <b>{balance:,}</b> фишек".replace(',', ' '), parse_mode="HTML")
        return

    # ========== ЛОГ ==========
    if text in ['лог', 'log']:
        rows = get_last_games(10)
        if not rows:
            await message.reply("📜 <b>Лог</b>\n\nПока пусто...", parse_mode="HTML"); return
        out = "📜 <b>Лог игр</b>\n\n"
        for uname, game, bet, win, detail, time in rows:
            icon = "🎡" if game == "рулетка" else ("🎰" if game == "слоты" else "🪙")
            if win > 0:
                out += f"{icon} {uname} — <b>+{win:,}</b> ({detail}) [{time}]\n".replace(',', ' ')
            else:
                out += f"{icon} {uname} — <b>-{bet:,}</b> [{time}]\n".replace(',', ' ')
        await message.reply(out, parse_mode="HTML")
        return

    # ========== ТОП ==========
    if text in ['топ', 'top']:
        rows = get_top(10)
        if not rows:
            await message.reply("📊 <b>Пока нет игроков!</b>", parse_mode="HTML"); return
        out = "🏆 <b>ТОП-10</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            out += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
        await message.reply(out, parse_mode="HTML")
        return

    # ========== ГО ==========
    if text == 'го':
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет активных ставок!"); return
        
        bets = active_bets[chat_id]["bets"]
        bets_text = "🎡 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n\n"
        bets_text += f"💰 Банк: <b>{sum(b['bet'] for b in bets):,}</b>\n\n".replace(',', ' ')
        bets_text += "🕐 <b>Крутится...</b>"
        await message.reply(bets_text, parse_mode="HTML")
        
        await asyncio.sleep(3)
        
        result = random.randint(0, 36)
        if result == 0: color = "🟢 Зеро"
        elif result in RED_NUMBERS: color = "🔴 Красное"
        else: color = "⚫ Чёрное"
        
        # Итог
        result_text = f"🎰 <b>ВЫПАЛО: {color} {result}</b>\n\n"
        
        total_bank = 0
        total_win = 0
        winners = []
        
        for b in bets:
            win = False
            mult = 0
            if b["type"] == "red" and result in RED_NUMBERS: win = True; mult = 2
            elif b["type"] == "black" and result in BLACK_NUMBERS: win = True; mult = 2
            elif b["type"] == "green" and result == 0: win = True; mult = 36
            elif b["type"] == "number" and result == b["number"]: win = True; mult = 36
            
            total_bank += b["bet"]
            if win:
                wa = b["bet"] * mult
                set_balance(b["user_id"], wa)
                total_win += wa
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], wa, f"{color} {result}")
                winners.append(f"🎉 {b['username']} — <b>+{wa:,}</b> (×{mult})".replace(',', ' '))
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet"], 0, f"{color} {result}")
        
        if winners:
            result_text += "<b>Победители:</b>\n" + "\n".join(winners)
        else:
            result_text += "😢 <b>Победителей нет</b>"
        
        del active_bets[chat_id]
        
        await message.reply(result_text, parse_mode="HTML")
        return

    # ========== СТАВКИ (к/ч/з) ==========
    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        try: bet = int(parts[1])
        except: return
        bet_type = 'red' if parts[0] == 'к' else ('black' if parts[0] == 'ч' else 'green')
        await add_bet(message, user_id, username, bet_type, bet)
        return

    # ========== СТАВКА НА ЧИСЛО (1000 5) ==========
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        try: bet = int(parts[0]); number = int(parts[1])
        except: return
        if number < 0 or number > 36: return
        await add_bet(message, user_id, username, "number", bet, number)
        return

    # ========== СЛОТЫ ==========
    if len(parts) == 2 and parts[0] in ['с', 'слоты']:
        try: bet = int(parts[1])
        except: return
        if bet < 10:
            await message.reply("❌ Минимум 10 фишек!"); return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        set_balance(user_id, -bet)
        symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
        r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        win = False; mult = 0
        if r1 == r2 == r3:
            win = True; mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True; mult = 2
        if win:
            wa = bet * mult
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "слоты", bet, wa, f"{r1}{r2}{r3}")
            await message.reply(f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n🎉 <b>+{wa:,}</b> (×{mult})\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            await message.reply(f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n😢 <b>-{bet:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # ========== МОНЕТКА ==========
    if len(parts) == 3 and parts[0] in ['м', 'монетка']:
        try: bet = int(parts[1])
        except: return
        choice = parts[2].lower()
        if choice in ['о', 'орёл', 'орел']: choice = 'heads'
        elif choice in ['р', 'решка']: choice = 'tails'
        else: return
        if bet < 10:
            await message.reply("❌ Минимум 10 фишек!"); return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        set_balance(user_id, -bet)
        result = random.choice(['heads', 'tails'])
        if result == choice:
            wa = bet * 2
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, "орёл" if result == 'heads' else "решка")
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅 Орёл' if result == 'heads' else '👑 Решка'}\n\n🎉 <b>+{wa:,}</b> (×2)\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, "орёл" if result == 'heads' else "решка")
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅 Орёл' if result == 'heads' else '👑 Решка'}\n\n😢 <b>-{bet:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
