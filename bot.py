import asyncio
import logging
import sqlite3
import os
import threading
import random
from datetime import datetime
from aiogram import Bot, Dispatcher
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

MULT_COLOR = 2
MULT_ZERO = 36
MULT_NUMBER = 36
MULT_RANGE = 1.2

# ========== HL КАРТЫ ==========
CARD_DECK = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
CARD_VALUES = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
    '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
}

def get_hl_mults(card):
    v = CARD_VALUES[card]
    total = 13
    up_chance = (total - v) / (total - 1) if v < total else 0
    down_chance = (v - 1) / (total - 1) if v > 1 else 0
    up_mult = round(0.95 / up_chance, 2) if up_chance > 0 else 0
    down_mult = round(0.95 / down_chance, 2) if down_chance > 0 else 0
    up_mult = min(up_mult, 12.48)
    down_mult = min(down_mult, 12.48)
    return up_mult, down_mult

def get_random_card():
    return random.choice(CARD_DECK)

# ========== СОСТОЯНИЕ ==========
active_bets = {}
hl_games = {}
bj_games = {}

# ========== ВЕБ-СЕРВЕР ==========
app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK"

@app.route('/api/balance/<int:user_id>')
def api_balance(user_id):
    return jsonify({"user_id": user_id, "balance": get_balance(user_id)})

@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    uid = data.get('user_id')
    amt = data.get('amount')
    if uid is None or amt is None:
        return jsonify({"error": "Missing"}), 400
    return jsonify({"user_id": uid, "balance": set_balance(uid, amt)})

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

web_thread = threading.Thread(target=run_web)
web_thread.daemon = False
web_thread.start()

# ========== БАЗА ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000)")
    c.execute("""CREATE TABLE IF NOT EXISTS game_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, game TEXT,
        bet INTEGER, win INTEGER, detail TEXT, time TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def ensure_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()

def set_balance(user_id, amount):
    amount = int(amount)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000

def get_top(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def log_game(user_id, username, game, bet, win, detail):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO game_log (user_id, username, game, bet, win, detail, time) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (user_id, username, game, bet, int(win), detail, datetime.now().strftime("%H:%M:%S")))
    conn.commit()
    conn.close()

def get_last_roulette_results(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT detail FROM game_log WHERE game='рулетка' ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ========== БЛЭКДЖЕК ==========
def hand_score(cards):
    score = 0
    aces = 0
    for c in cards:
        val = c[:-1]
        if val == 'A':
            score += 11
            aces += 1
        elif val in ['K','Q','J','10']:
            score += 10
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

def create_deck():
    suits = ['♠','♥','♦','♣']
    values = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    deck = [v+s for s in suits for v in values]
    random.shuffle(deck)
    return deck

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top"),
         InlineKeyboardButton(text="📜 Лог", callback_data="menu_log")]
    ])

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="info_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="info_slots")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="info_coin"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="info_bj")],
        [InlineKeyboardButton(text="🃏 HL (карты)", callback_data="info_hl")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
    ])

def back_to_games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К играм", callback_data="menu_games")]
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

def hl_kb(up_mult=0, down_mult=0, cashout=0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⬇️ Ниже ×{down_mult}", callback_data="hl_down"),
         InlineKeyboardButton(text=f"⬆️ Выше ×{up_mult}", callback_data="hl_up")],
        [InlineKeyboardButton(text=f"💰 Забрать (−10%)", callback_data="hl_cashout")]
    ])

def bj_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="bj_hit"),
         InlineKeyboardButton(text="✋ Хватит", callback_data="bj_stand")]
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
    txt = (
        f"🎰 <b>WORLD CASINO</b>\n\n"
        f"👤 {username}\n"
        f"💎 <b>{balance:,}</b> фишек\n\n"
        f"🎮 Нажми <b>Игры</b> — там все игры!\n\n"
        f"<b>Команды:</b>\n"
        f"<code>б</code> — баланс\n"
        f"<code>игры</code> — список игр\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — лог"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML", reply_markup=main_menu_kb())

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
        await message.answer("📊 <b>Пока нет игроков!</b>", parse_mode="HTML")
        return
    txt = "🏆 <b>ТОП-10</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, uname, bal) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        txt += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        f"❓ <b>Помощь</b>\n\n"
        f"<code>б</code> — баланс\n"
        f"<code>игры</code> — список игр\n"
        f"<code>топ</code> — топ\n"
        f"<code>лог</code> — лог\n\n"
        f"<code>п 1000</code> — перевод (ответом)\n"
        f"<code>к/ч/з 1000</code> — рулетка\n"
        f"<code>го</code> — запуск рулетки\n"
        f"<code>спин 100</code> — слоты\n"
        f"<code>орёл 100</code> / <code>решка 100</code> — монетка\n"
        f"<code>хл 100</code> — HL (карты)\n"
        f"<code>бж 100</code> — блэкджек",
        parse_mode="HTML"
    )

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if not row:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(row[0], amount)
        await message.answer(f"✅ <b>+{amount:,}</b> → @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, amount)
    await message.answer(f"✅ <b>+{amount:,}</b> → {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("take"))
async def cmd_take(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    
    # /take all — забрать весь баланс
    if len(args) >= 2 and args[1].lower() == 'all':
        if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
            await message.answer("❌ Ответь на сообщение игрока и напиши: <code>/take all</code>", parse_mode="HTML")
            return
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        target_balance = get_balance(target.id)
        if target_balance <= 0:
            await message.answer(f"❌ У {target.username or target.first_name} нет фишек!", parse_mode="HTML")
            return
        set_balance(target.id, -target_balance)
        await message.answer(
            f"✅ <b>Забрано всё!</b>\n\n"
            f"👤 {target.username or target.first_name}\n"
            f"💸 -{target_balance:,} фишек\n"
            f"💎 Баланс: <b>0</b>".replace(',', ' '),
            parse_mode="HTML"
        )
        return
    
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if not row:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(row[0], -amount)
        await message.answer(f"✅ <b>-{amount:,}</b> ← @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except:
        return
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
        txt = (
            f"🎰 <b>WORLD CASINO</b>\n\n"
            f"👤 {username}\n"
            f"💎 <b>{balance:,}</b> фишек\n\n"
            f"🎮 Нажми <b>Игры</b>!"
        ).replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_games":
        txt = "🎮 <b>ИГРЫ</b>\n\nВыбери игру, чтобы узнать правила:"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=games_kb())

    elif data == "menu_balance":
        await call.answer(f"💎 Баланс: {balance:,}".replace(',', ' '), show_alert=True)

    elif data == "menu_top":
        rows = get_top(10)
        txt = "🏆 <b>ТОП-10</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            txt += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_log":
        rows = get_last_roulette_results(10)
        if not rows:
            txt = "📜 <b>Последние результаты:</b>\n\nПока пусто..."
        else:
            txt = "📜 <b>Последние результаты:</b>\n\n"
            for i, (detail,) in enumerate(rows, 1):
                parts_d = detail.split()
                if len(parts_d) >= 2:
                    txt += f"{i}. {parts_d[1]} {parts_d[0]}\n"
                else:
                    txt += f"{i}. {detail}\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "info_roulette":
        txt = (
            f"🎡 <b>РУЛЕТКА</b>\n\n"
            f"<b>Как играть:</b>\n"
            f"<code>к 1000</code> — красное (×2)\n"
            f"<code>ч 1000</code> — чёрное (×2)\n"
            f"<code>з 1000</code> — зеро (×36)\n"
            f"<code>1000 5</code> — число 5 (×36)\n"
            f"<code>1000 1-9 10-18</code> — диапазоны\n\n"
            f"<code>го</code> — запуск\n"
            f"<code>отмена</code> — отмена\n\n"
            f"После игры — кнопки <b>Повторить</b> и <b>Удвоить</b>!"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_slots":
        txt = (
            f"🎰 <b>СЛОТЫ</b>\n\n"
            f"Напиши: <code>спин 1000</code>\n\n"
            f"🍒🍒🍒 ×10 | 🍋🍋🍋 ×15\n"
            f"🍊🍊🍊 ×20 | 🍇🍇🍇 ×25\n"
            f"💎💎💎 ×50 | 7️⃣7️⃣7️⃣ ×100\n"
            f"Два одинаковых — ×2"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_coin":
        txt = (
            f"🪙 <b>МОНЕТКА</b>\n\n"
            f"<code>орёл 1000</code> — на орла\n"
            f"<code>решка 1000</code> — на решку\n\n"
            f"Угадал — ×2"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_bj":
        txt = (
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
            f"Напиши: <code>бж 1000</code>\n\n"
            f"Цель — 21 или ближе к 21, чем дилер\n"
            f"A = 1 или 11, J/Q/K = 10\n\n"
            f"➕ Взять — ещё карту\n"
            f"✋ Хватит — остановиться\n\n"
            f"Выигрыш — ×2"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_hl":
        txt = (
            f"🃏 <b>HL (Higher/Lower) — на картах</b>\n\n"
            f"<b>Как играть:</b>\n"
            f"1. Напиши: <code>хл 1000</code>\n"
            f"2. Бот выдаёт карту (2-10, J, Q, K, A)\n"
            f"3. Угадай — следующая будет <b>Выше</b> или <b>Ниже</b>\n"
            f"4. Коэффициент зависит от карты:\n"
            f"   • 2 — выше шанс, ×1.13\n"
            f"   • A — ниже шанс, ×12.48\n"
            f"5. Угадал — множитель растёт\n"
            f"6. <b>💰 Забрать</b> — с комиссией 10%\n"
            f"7. Не угадал — всё сгорает"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    # ========== РУЛЕТКА ==========
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
            await call.answer("❌ Минимум 10 фишек!", show_alert=True)
            return
        if balance < bet:
            await call.answer(f"❌ Недостаточно! Баланс: {balance}", show_alert=True)
            return
        set_balance(user_id, -bet)
        result = random.randint(0, 36)
        if result == 0:
            color = "🟢"
        elif result in RED_NUMBERS:
            color = "🔴"
        else:
            color = "⚫"
        win = False
        mult = 0
        if bet_type == "red" and result in RED_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "black" and result in BLACK_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "green" and result == 0:
            win = True
            mult = MULT_ZERO
        if win:
            wa = int(bet * mult)
            nb = set_balance(user_id, wa)
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n\n🎉 <b>{username}</b>\n💰 <b>+{wa:,}</b> (×{mult})\n\n💎 <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
        else:
            nb = get_balance(user_id)
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n\n😢 <b>{username}</b>\n💸 <b>-{bet:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
        # Кнопки Повторить / Удвоить
        rkb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=rkb)

    # ========== БЛЭКДЖЕК ==========
    elif data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])}\n\n💥 <b>Перебор!</b>\n💸 -{game['bet']:,}\n\n💎 <b>{nb:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=main_menu_kb()
            )
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} перебор")
            del bj_games[user_id]
        else:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])}\n\n🎯 <b>Ещё карту?</b>",
                parse_mode="HTML",
                reply_markup=bj_kb()
            )

    elif data == "bj_stand":
        if user_id not in bj_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = bj_games[user_id]
        while hand_score(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        d_score = hand_score(game["dealer"])
        if d_score > 21 or p_score > d_score:
            wa = game["bet"] * 2
            nb = set_balance(user_id, wa)
            result_text = f"🎉 <b>ПОБЕДА!</b>\n💰 +{wa - game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], wa, f"{p_score} vs {d_score}")
        elif p_score == d_score:
            set_balance(user_id, game["bet"])
            nb = get_balance(user_id)
            result_text = "🤝 <b>Ничья</b>"
            log_game(user_id, username, "блэкджек", game["bet"], game["bet"], f"{p_score} vs {d_score}")
        else:
            nb = get_balance(user_id)
            result_text = f"😢 <b>Проигрыш</b>\n💸 -{game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} vs {d_score}")
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])} = <b>{d_score}</b>\n\n{result_text}\n\n💎 <b>{nb:,}</b>".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        del bj_games[user_id]

    # ========== HL ==========
    elif data in ["hl_up", "hl_down"]:
        if user_id not in hl_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = hl_games[user_id]
        current_card = game["card"]
        next_card = get_random_card()
        current_value = CARD_VALUES[current_card]
        next_value = CARD_VALUES[next_card]
        direction = "up" if data == "hl_up" else "down"
        win = False
        if direction == "up" and next_value > current_value:
            win = True
        elif direction == "down" and next_value < current_value:
            win = True
        if win:
            up_mult, down_mult = get_hl_mults(current_card)
            mult = up_mult if direction == "up" else down_mult
            game["mult"] = round(game["mult"] * mult, 2)
            game["win_amount"] = int(game["bet"] * game["mult"])
            game["card"] = next_card
            game["streak"] += 1
            up_mult_new, down_mult_new = get_hl_mults(next_card)
            await call.message.edit_text(
                f"🃏 <b>HL — Карты</b>\n\n"
                f"✅ Верно! Было: <b>{current_card}</b> → Стало: <b>{next_card}</b>\n\n"
                f"🃏 Текущая карта: <b>{next_card}</b>\n"
                f"📈 Множитель: <b>×{game['mult']:.2f}</b>\n"
                f"💰 При выводе: <b>{game['win_amount']:,}</b> фишек\n\n"
                f"⬆️ Выше → <b>×{up_mult_new}</b> за шаг\n"
                f"⬇️ Ниже → <b>×{down_mult_new}</b> за шаг\n\n"
                f"😉 Нажимай на кнопки ниже!".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=hl_kb(up_mult_new, down_mult_new, game["win_amount"])
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "HL", game["bet"], 0, f"{current_card}→{next_card}")
            await call.message.edit_text(
                f"💥 <b>Неверно! Карта: {next_card}</b>\n\n"
                f"📉 Ты проиграл <b>{game['bet']:,}</b> фишек\n\n"
                f"🏁 <b>Игра окончена</b>\n\n"
                f"💎 Баланс: <b>{nb:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=main_menu_kb()
            )
            del hl_games[user_id]

    elif data == "hl_cashout":
        if user_id not in hl_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = hl_games[user_id]
        wa = int(game["win_amount"] * 0.9)
        nb = set_balance(user_id, wa)
        log_game(user_id, username, "HL", game["bet"], wa, f"забрал ×{game['mult']}")
        await call.message.edit_text(
            f"💰 <b>Забрал: {wa:,} фишек</b>\n\n"
            f"📉 Комиссия 10%: −{int(game['win_amount'] * 0.1):,}\n"
            f"🔥 Серия: {game['streak']}\n"
            f"📈 Множитель: ×{game['mult']:.2f}\n\n"
            f"💎 Баланс: <b>{nb:,}</b>".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        del hl_games[user_id]

    await call.answer()

# ========== ПАРСИНГ ДИАПАЗОНОВ ==========
def parse_multi_bet(text):
    parts = text.split()
    if len(parts) < 2:
        return None, None
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

# ========== ОБРАБОТКА ТЕКСТА ==========
@dp.message()
async def text_handler(message: Message):
    if not message.text:
        return
    if message.from_user.is_bot:
        return
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    ensure_user(user_id, username)

    # ПЕРЕВОД
    if parts[0] == 'п':
        if len(parts) < 2:
            await message.reply("💸 Ответь на сообщение и напиши: <code>п 1000</code>", parse_mode="HTML")
            return
        if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
            await message.reply("❌ Ответь на сообщение игрока!")
            return
        try:
            amount = int(parts[1])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        target = message.reply_to_message.from_user
        if target.id == user_id:
            await message.reply("❌ Нельзя себе!")
            return
        balance = get_balance(user_id)
        if balance < amount:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        ensure_user(target.id, target.username or target.first_name)
        set_balance(user_id, -amount)
        set_balance(target.id, amount)
        nb = get_balance(user_id)
        nt = get_balance(target.id)
        await message.reply(f"💸 <b>Перевод!</b>\n\n👤 {username} → {target.username or target.first_name}\n💰 <b>{amount:,}</b>\n\n💎 Твой: <b>{nb:,}</b>\n💎 Получателя: <b>{nt:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # ОТМЕНА
    if text in ['отмена', 'отменить']:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            for b in active_bets[chat_id]["bets"]:
                set_balance(b["user_id"], b["bet_total"])
            del active_bets[chat_id]
            await message.reply(f"❌ <b>Ставки отменены!</b>\nВозвращено {count} ставок.", parse_mode="HTML")
        return

    # БАЛАНС
    if text in ['б', 'баланс']:
        balance = get_balance(user_id)
        await message.reply(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 <b>{balance:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # ИГРЫ
    if text in ['игры', 'игра']:
        await message.reply("🎮 <b>ИГРЫ</b>\n\nВыбери игру, чтобы узнать правила:", parse_mode="HTML", reply_markup=games_kb())
        return

    # ЛОГ
    if text in ['лог', 'log']:
        rows = get_last_roulette_results(10)
        if not rows:
            await message.reply("📜 <b>Последние результаты:</b>\n\nПока пусто...", parse_mode="HTML")
            return
        out = "📜 <b>Последние результаты:</b>\n\n"
        for i, (detail,) in enumerate(rows, 1):
            parts_d = detail.split()
            if len(parts_d) >= 2:
                out += f"{i}. {parts_d[1]} {parts_d[0]}\n"
            else:
                out += f"{i}. {detail}\n"
        await message.reply(out, parse_mode="HTML")
        return

    # ТОП
    if text in ['топ', 'top']:
        rows = get_top(10)
        if not rows:
            await message.reply("📊 <b>Пока нет игроков!</b>", parse_mode="HTML")
            return
        out = "🏆 <b>ТОП-10</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            out += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
        await message.reply(out, parse_mode="HTML")
        return

    # ГО
    if text == 'го':
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет активных ставок!")
            return
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet_total"] for b in bets)
        await message.reply(f"🎡 <b>РУЛЕТКА!</b>\n\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 Крутится...".replace(',', ' '), parse_mode="HTML")
        await asyncio.sleep(3)
        result = random.randint(0, 36)
        if result == 0:
            color = "🟢"
        elif result in RED_NUMBERS:
            color = "🔴"
        else:
            color = "⚫"
        result_text = f"🎰 <b>ВЫПАЛО: {color} {result}</b>\n\n"
        winners = []
        for b in bets:
            win_amount = 0
            if b["type"] == "red" and result in RED_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR)
            elif b["type"] == "black" and result in BLACK_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR)
            elif b["type"] == "green" and result == 0:
                win_amount = int(b["bet_total"] * MULT_ZERO)
            elif b["type"] == "number" and result == b["number"]:
                win_amount = int(b["bet_total"] * MULT_NUMBER)
            elif b["type"] == "ranges":
                win_mult = 0
                for (a, z) in b["ranges"]:
                    if a <= result <= z:
                        win_mult += MULT_RANGE
                if win_mult > 0:
                    win_amount = int(b["bet_total"] * win_mult)
            if win_amount > 0:
                set_balance(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], win_amount, f"{result} {color}")
                winners.append(f"🎉 {b['username']} — <b>+{win_amount:,}</b>".replace(',', ' '))
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], 0, f"{result} {color}")
        if winners:
            result_text += "<b>Победители:</b>\n" + "\n".join(winners)
        else:
            result_text += "😢 <b>Победителей нет</b>"
        del active_bets[chat_id]
        await message.reply(result_text, parse_mode="HTML")
        return

    # СПИН
    if len(parts) == 2 and parts[0] in ['спин', 'spin']:
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
        r1 = random.choice(symbols)
        r2 = random.choice(symbols)
        r3 = random.choice(symbols)
        win = False
        mult = 0
        if r1 == r2 == r3:
            win = True
            mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True
            mult = 2
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

    # ОРЁЛ / РЕШКА
    if len(parts) == 2 and parts[0] in ['орёл', 'орел', 'решка']:
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        choice = 'heads' if parts[0] in ['орёл', 'орел'] else 'tails'
        result = random.choice(['heads', 'tails'])
        if result == choice:
            wa = bet * 2
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, "🦅" if result == 'heads' else "👑")
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅 Орёл' if result == 'heads' else '👑 Решка'}\n\n🎉 <b>+{wa:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, "🦅" if result == 'heads' else "👑")
            await message.reply(f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅 Орёл' if result == 'heads' else '👑 Решка'}\n\n😢 <b>-{bet:,}</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # HL
    if len(parts) == 2 and parts[0] == 'хл':
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        card = get_random_card()
        hl_games[user_id] = {
            "card": card,
            "bet": bet,
            "mult": 1.0,
            "win_amount": bet,
            "streak": 0
        }
        up_mult, down_mult = get_hl_mults(card)
        await message.reply(
            f"🃏 <b>HL — Карты</b>\n\n"
            f"🃏 Текущая карта: <b>{card}</b>\n"
            f"📈 Множитель: <b>×1.00</b>\n"
            f"💰 При выводе: <b>{bet:,}</b> фишек\n\n"
            f"⬆️ Выше → <b>×{up_mult}</b> за шаг\n"
            f"⬇️ Ниже → <b>×{down_mult}</b> за шаг\n\n"
            f"😉 Нажимай на кнопки ниже!".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=hl_kb(up_mult, down_mult, bet)
        )
        return

    # БЛЭКДЖЕК
    if len(parts) == 2 and parts[0] in ['бж', 'блэкджек']:
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        bj_games[user_id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}
        p_score = hand_score(player)
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Ты: {' '.join(player)} = <b>{p_score}</b>\n🤖 Дилер: {' '.join(dealer)}\n\n🎯 <b>Ещё карту?</b>".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=bj_kb()
        )
        return

    # К/Ч/З
    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        bet_type = 'red' if parts[0] == 'к' else ('black' if parts[0] == 'ч' else 'green')
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({"user_id": user_id, "username": username, "type": bet_type, "bet": bet, "bet_total": bet})
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet_total"] for b in bets)
        icon = '🔴' if bet_type == 'red' else ('⚫' if bet_type == 'black' else '🟢')
        await message.reply(f"📊 <b>Ставка принята!</b>\n\n👤 {username}\n{icon} × <b>{bet:,}</b>\n\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 <code>го</code> — запуск\n❌ <code>отмена</code>".replace(',', ' '), parse_mode="HTML")
        return

    # ДИАПАЗОНЫ
    bet, ranges = parse_multi_bet(text)
    if bet and ranges:
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        total_bet = bet * len(ranges)
        balance = get_balance(user_id)
        if balance < total_bet:
            await message.reply(f"❌ Нужно {total_bet:,}, у тебя {balance:,}".replace(',', ' '))
            return
        set_balance(user_id, -total_bet)
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({"user_id": user_id, "username": username, "type": "ranges", "bet": bet, "bet_total": total_bet, "ranges": ranges})
        bets = active_bets[chat_id]["bets"]
        total_bank = sum(b["bet_total"] for b in bets)
        ranges_str = " ".join([f"{a}-{z}" if a != z else str(a) for (a, z) in ranges])
        await message.reply(f"📊 <b>Ставка принята!</b>\n\n👤 {username}\n🎯 <b>{ranges_str}</b>\n💰 <b>{bet:,}</b> × {len(ranges)} = <b>{total_bet:,}</b>\n\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 <code>го</code> — запуск\n❌ <code>отмена</code>".replace(',', ' '), parse_mode="HTML")
        return

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
