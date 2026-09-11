import asyncio
import logging
import sqlite3
import os
import threading
import random
import re
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

# ========== АКТИВНЫЕ СТАВКИ ==========
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
        f"<code>п</code> — перевод\n"
        f"<code>го</code> — рулетка\n"
        f"<code>с 100</code> — слоты\n"
        f"<code>м 100 о</code> — монетка\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — история\n\n"
        f"🎡 <b>Ставки:</b>\n"
        f"<code>к 1000</code> — красное\n"
        f"<code>ч 1000</code> — чёрное\n"
        f"<code>з 1000</code> — зеро\n"
        f"<code>1000 5</code> — число\n"
        f"<code>1000 1-9 10-18</code> — диапазоны"
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
        f"<code>п @user 1000</code> — перевод\n"
        f"<code>го</code> — рулетка\n"
        f"<code>с 100</code> — слоты\n"
        f"<code>м 100 о</code> — монетка\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — лог\n\n"
        f"🎡 <b>Ставки:</b>\n"
        f"<code>к/ч/з 100</code> — цвет\n"
        f"<code>100 7</code> — число\n"
        f"<code>100 1-9 10-18</code> — диапазоны\n\n"
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

# ========== КНОПКИ ==========
@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)
    balance = get_balance(user_id)

    if data == "menu_main":
        text = (
            f"🎰 <b>WORLD CASINO</b>\n\n"
            f"👤 {username}\n"
            f"💎 <b>{balance:,}</b> фишек\n\n"
            f"🎮 <b>Выбери игру:</b>"
        ).replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_roulette":
        text = (
            f"🎡 <b>Рулетка</b>\n\n"
            f"💎 Баланс: <b>{balance:,}</b>\n\n"
            f"🎯 <b>Выбери ставку:</b>"
        ).replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=roulette_kb(100))

    elif data == "menu_balance":
        await call.answer(f"💎 Баланс: {balance:,} фишек".replace(',', ' '), show_alert=True)

    elif data == "menu_top":
        rows = get_top(10)
        text = "🏆 <b>ТОП-10</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_log":
        rows = get_last_games(10)
        if not rows:
            text = "📜 <b>Лог</b>\n\nПока пусто..."
        else:
            text = "📜 <b>Лог игр</b>\n\n"
            for uname, game, bet, win, detail, time in rows:
                icon = "🎡" if game == "рулетка" else ("🎰" if game == "слоты" else "🪙")
                if win > 0:
                    text += f"{icon} {uname} — <b>+{win:,}</b> ({detail}) [{time}]\n".replace(',', ' ')
                else:
                    text += f"{icon} {uname} — <b>-{bet:,}</b> [{time}]\n".replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_help":
        await call.message.edit_text(
            f"❓ <b>Помощь</b>\n\n"
            f"<code>б</code> — баланс\n"
            f"<code>п @user 1000</code> — перевод\n"
            f"<code>го</code> — рулетка\n"
            f"<code>с 100</code> — слоты\n"
            f"<code>м 100 о</code> — монетка\n"
            f"<code>100 1-9 10-18</code> — диапазоны",
            parse_mode="HTML", reply_markup=main_menu_kb()
        )

    elif data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        bet = balance if val == "max" else int(val)
        await call.message.edit_reply_markup(reply_markup=roulette_kb(bet))
        await call.answer(f"💎 Ставка: {bet:,}".replace(',', ' '))

    elif data.startswith("bet_"):
        parts = data.split("_")
        bet_type = parts[1]
        bet = int(parts[2])
        if bet < 10:
            await call.answer("❌ Минимум 10 фишек!", show_alert=True); return
        if balance < bet:
            await call.answer(f"❌ Недостаточно! Баланс: {balance}", show_alert=True); return

        set_balance(user_id, -bet)
        result = random.randint(0, 36)
        if result == 0: color = "🟢 Зеро"
        elif result in RED_NUMBERS: color = "🔴 Красное"
        else: color = "⚫ Чёрное"

        win = False; mult = 0
        if bet_type == "red" and result in RED_NUMBERS: win = True; mult = 2
        elif bet_type == "black" and result in BLACK_NUMBERS: win = True; mult = 2
        elif bet_type == "green" and result == 0: win = True; mult = 36

        if win:
            wa = bet * mult
            nb = set_balance(user_id, wa)
            text = f"🎰 <b>Выпало: {color} {result}</b>\n\n🎉 <b>{username}</b>\n💰 <b>+{wa:,}</b> (×{mult})\n\n💎 <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, wa, f"{color} {result}")
        else:
            nb = get_balance(user_id)
            text = f"🎰 <b>Выпало: {color} {result}</b>\n\n😢 <b>{username}</b>\n💸 <b>-{bet:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, 0, f"{color} {result}")
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    await call.answer()

# ========== ПАРСИНГ СТАВОК С ДИАПАЗОНАМИ ==========
def parse_multi_bet(text):
    """
    Парсит ставки вида:
    25000 25-29 24-27 23-26 22-25 21-24 20-23 15-19 ...
    Возвращает: (bet_amount, [список диапазонов])
    """
    parts = text.split()
    if len(parts) < 2: return None, None
    
    # Первое слово — ставка
    try:
        bet = int(parts[0])
    except:
        return None, None
    
    ranges = []
    for p in parts[1:]:
        if '-' in p:
            try:
                a, b = p.split('-')
                a, b = int(a), int(b)
                if 0 <= a <= 36 and 0 <= b <= 36:
                    ranges.append((min(a,b), max(a,b)))
            except:
                pass
        elif p.isdigit():
            num = int(p)
            if 0 <= num <= 36:
                ranges.append((num, num))
    
    return bet, ranges

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

    # ========== ПЕРЕВОД (п) ==========
    if parts[0] == 'п':
        if len(parts) < 3 or not parts[1].startswith('@'):
            await message.reply(
                f"💸 <b>Перевод</b>\n\n"
                f"Использование: <code>п @username 1000</code>",
                parse_mode="HTML"
            ); return
        target_username = parts[1][1:]
        try: amount = int(parts[2])
        except:
            await message.reply("❌ Неверная сумма!"); return
        if amount < 1:
            await message.reply("❌ Минимум 1 фишка!"); return
        balance = get_balance(user_id)
        if balance < amount:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (target_username,))
        row = c.fetchone(); conn.close()
        if not row:
            await message.reply(f"❌ @{target_username} не найден!"); return
        target_id = row[0]
        if target_id == user_id:
            await message.reply("❌ Нельзя переводить себе!"); return
        set_balance(user_id, -amount)
        set_balance(target_id, amount)
        nb = get_balance(user_id)
        await message.reply(
            f"💸 <b>Перевод выполнен!</b>\n\n"
            f"👤 {username} → @{target_username}\n"
            f"💰 Сумма: <b>{amount:,}</b>\n\n"
            f"💎 Твой баланс: <b>{nb:,}</b>".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    # ========== ОТМЕНА ==========
    if text in ['отмена', 'отменить']:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            for b in active_bets[chat_id]["bets"]:
                set_balance(b["user_id"], b["bet_total"])
            del active_bets[chat_id]
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
        total_bank = sum(b["bet_total"] for b in bets)
        await message.reply(
            f"🎡 <b>РУЛЕТКА ЗАПУЩЕНА!</b>\n\n"
            f"💰 Банк: <b>{total_bank:,}</b>\n\n"
            f"🕐 <b>Крутится...</b>".replace(',', ' '),
            parse_mode="HTML"
        )
        
        await asyncio.sleep(3)
        
        result = random.randint(0, 36)
        if result == 0: color = "🟢 Зеро"
        elif result in RED_NUMBERS: color = "🔴 Красное"
        else: color = "⚫ Чёрное"
        
        result_text = f"🎰 <b>ВЫПАЛО: {color} {result}</b>\n\n"
        winners = []
        
        for b in bets:
            win_amount = 0
            if b["type"] == "red" and result in RED_NUMBERS: win_amount = b["bet_total"] * 2
            elif b["type"] == "black" and result in BLACK_NUMBERS: win_amount = b["bet_total"] * 2
            elif b["type"] == "green" and result == 0: win_amount = b["bet_total"] * 36
            elif b["type"] == "number" and result == b["number"]: win_amount = b["bet_total"] * 36
            elif b["type"] == "ranges":
                # Проверяем диапазоны
                win_mult = 0
                for (a, z) in b["ranges"]:
                    if a <= result <= z:
                        win_mult += 2  # ×2 за каждый диапазон
                if win_mult > 0:
                    win_amount = b["bet_total"] * win_mult
            
            if win_amount > 0:
                set_balance(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], win_amount, f"{color} {result}")
                winners.append(f"🎉 {b['username']} — <b>+{win_amount:,}</b>".replace(',', ' '))
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], 0, f"{color} {result}")
        
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
        if bet < 10:
            await message.reply("❌ Минимум 10 фишек!"); return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        set_balance(user_id, -bet)
        bet_type = 'red' if parts[0] == 'к' else ('black' if parts[0] == 'ч' else 'green')
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({"user_id": user_id, "username": username, "type": bet_type, "bet": bet, "bet_total": bet})
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet_total"] for b in bets)
        await message.reply(
            f"📊 <b>Ставки приняты!</b>\n\n"
            f"👤 {username}\n"
            f"{'🔴 Красное' if bet_type == 'red' else ('⚫ Чёрное' if bet_type == 'black' else '🟢 Зеро')} × <b>{bet:,}</b>\n\n"
            f"⚡ Всего ставок: {len(bets)}\n"
            f"💰 Банк: <b>{total_bank:,}</b>\n\n"
            f"🕐 Напиши <code>го</code> для запуска\n"
            f"❌ Или <code>отмена</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    # ========== СТАВКИ НА ДИАПАЗОНЫ ==========
    bet, ranges = parse_multi_bet(text)
    if bet and ranges:
        if bet < 10:
            await message.reply("❌ Минимум 10 фишек!"); return
        total_bet = bet * len(ranges)
        balance = get_balance(user_id)
        if balance < total_bet:
            await message.reply(f"❌ Недостаточно! Нужно {total_bet:,}, у тебя {balance:,}".replace(',', ' ')); return
        set_balance(user_id, -total_bet)
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username, "type": "ranges",
            "bet": bet, "bet_total": total_bet, "ranges": ranges
        })
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet_total"] for b in bets)
        ranges_str = " ".join([f"{a}-{z}" if a != z else str(a) for (a, z) in ranges])
        await message.reply(
            f"📊 <b>Ставки приняты!</b>\n\n"
            f"👤 {username}\n"
            f"🎯 Диапазоны: <b>{ranges_str}</b>\n"
            f"💰 Ставка: <b>{bet:,}</b> × {len(ranges)} = <b>{total_bet:,}</b>\n\n"
            f"⚡ Всего ставок: {len(bets)}\n"
            f"💰 Банк: <b>{total_bank:,}</b>\n\n"
            f"🕐 Напиши <code>го</code> для запуска\n"
            f"❌ Или <code>отмена</code>".replace(',', ' '),
            parse_mode="HTML"
        )
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
            log_game(user_id, username, "слоты", bet, wa, f
