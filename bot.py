import asyncio
import logging
import os
import threading
import random
import psycopg2
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask, jsonify, request
from flask_cors import CORS

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MINI_APP_URL = "https://vectorgame1.github.io/casino/"

RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]

MULT_COLOR = 2
MULT_ZERO = 36
MULT_NUMBER = 36
MULT_RANGE = 1.2

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
duel_games = {}

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
    if is_banned(user_id):
        return jsonify({"error": "Banned", "banned": True}), 403
    return jsonify({
        "user_id": user_id,
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "unlimited": is_unlimited(user_id)
    })

@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    uid = data.get('user_id')
    amt = data.get('amount')
    if uid is None or amt is None:
        return jsonify({"error": "Missing"}), 400
    if is_banned(uid):
        return jsonify({"error": "Banned"}), 403
    return jsonify({"user_id": uid, "balance": set_balance(uid, amt)})

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    data = request.json
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    amount = data.get('amount')
    if admin_id != ADMIN_ID:
        return jsonify({"error": "Access denied"}), 403
    if target_id is None or amount is None:
        return jsonify({"error": "Missing"}), 400
    ensure_user(target_id, f"user_{target_id}")
    new_balance = set_balance(target_id, amount)
    return jsonify({"user_id": target_id, "balance": new_balance})

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

web_thread = threading.Thread(target=run_web)
web_thread.daemon = False
web_thread.start()

# ========== БАЗА ==========
def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        balance BIGINT DEFAULT 1000,
        bank BIGINT DEFAULT 0,
        banned BOOLEAN DEFAULT FALSE,
        unlimited BOOLEAN DEFAULT FALSE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS game_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        game TEXT,
        bet BIGINT,
        win BIGINT,
        detail TEXT,
        time TEXT
    )""")
    conn.commit()
    c.close()
    conn.close()

def get_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row

def ensure_user(user_id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = %s",
              (user_id, username, username))
    conn.commit()
    c.close()
    conn.close()

def is_banned(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else False

def set_banned(user_id, banned=True):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, banned) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET banned = %s",
              (user_id, banned, banned))
    conn.commit()
    c.close()
    conn.close()

def is_unlimited(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT unlimited FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else False

def set_unlimited(user_id, unlimited=True):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, unlimited) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET unlimited = %s",
              (user_id, unlimited, unlimited))
    conn.commit()
    c.close()
    conn.close()

def set_balance(user_id, amount):
    amount = int(amount)
    if is_unlimited(user_id) and amount < 0:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row[0] if row else 0
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, 1000) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000

def set_bank(user_id, amount):
    amount = int(amount)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, bank) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0

def get_bank(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else 0

def get_top(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def log_game(user_id, username, game, bet, win, detail):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO game_log (user_id, username, game, bet, win, detail, time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
              (user_id, username, game, bet, int(win), detail, datetime.now().strftime("%H:%M:%S")))
    conn.commit()
    c.close()
    conn.close()

def get_last_roulette_results(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT detail FROM game_log WHERE game='рулетка' ORDER BY id DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
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
def private_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Открыть Casino", web_app={"url": MINI_APP_URL})],
        [InlineKeyboardButton(text="🏆 Топ игроков", callback_data="menu_top")]
    ])

def group_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu_bank"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top")],
        [InlineKeyboardButton(text="📜 Лог", callback_data="menu_log")]
    ])

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="info_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="info_slots")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="info_coin"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="info_bj")],
        [InlineKeyboardButton(text="🃏 HL (карты)", callback_data="info_hl"),
         InlineKeyboardButton(text="⚔️ Дуэль", callback_data="info_duel")],
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
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    is_private = message.chat.type == 'private'
    if is_private:
        if is_unlimited(user_id):
            bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
        else:
            bal_line = f"💎 <b>{balance:,}</b> фишек".replace(',', ' ')
        txt = f"🎰 <b>WORLD CASINO</b>\n\n👤 {username}\n{bal_line}\n🏦 Банк: <b>{bank:,}</b>\n\n🎮 <b>Играй в Mini App!</b>\nНажми кнопку ниже 👇".replace(',', ' ')
        await message.answer(txt, parse_mode="HTML", reply_markup=private_kb())
    else:
        if is_unlimited(user_id):
            bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
        else:
            bal_line = f"💎 <b>{balance:,}</b> фишек".replace(',', ' ')
        txt = f"🎰 <b>WORLD CASINO</b>\n\n👤 {username}\n{bal_line}\n🏦 Банк: <b>{bank:,}</b>\n\n🎮 Нажми <b>Игры</b>!\n\n<code>б</code> — баланс | <code>топ</code> — топ\n<code>банк</code> — банк | <code>дуэль 1000 @user</code>\n<code>хл 100</code> — HL | <code>бж 100</code> — блэкджек\n<code>спин 100</code> — слоты\n<code>орёл 100</code> / <code>решка 100</code> — монетка\n<code>к/ч/з 100</code> — рулетка | <code>го</code> — запуск".replace(',', ' ')
        await message.answer(txt, parse_mode="HTML", reply_markup=group_kb())

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    if is_unlimited(user_id):
        await message.answer(f"💰 <b>Баланс</b>\n\n👤 {username}\n♾️ <b>У тебя БЕЗЛИМИТ</b>\n🏦 В банке: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")
    else:
        await message.answer(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 Баланс: <b>{balance:,}</b>\n🏦 В банке: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")

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

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 2 and args[1].lower() in ['unlimited', 'безлимит', '∞']:
        set_unlimited(message.from_user.id, True)
        await message.answer(
            f"♾️ <b>БЕЗЛИМИТ АКТИВИРОВАН!</b>\n\n"
            f"👤 {message.from_user.username or message.from_user.first_name}\n"
            f"💰 Теперь у тебя бесконечные фишки!\n\n"
            f"❌ Чтобы снять — напиши <code>/give all</code>",
            parse_mode="HTML"
        )
        return
    if len(args) >= 2 and args[1].lower() in ['all', 'off', 'выкл']:
        set_unlimited(message.from_user.id, False)
        await message.answer(f"✅ <b>БЕЗЛИМИТ ОТКЛЮЧЁН</b>\n\nТеперь фишки тратятся как обычно.", parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        row = c.fetchone()
        c.close()
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
    if len(args) >= 2 and args[1].lower() == 'all':
        if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
            await message.answer("❌ Ответь на сообщение игрока: <code>/take all</code>", parse_mode="HTML")
            return
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        tb = get_balance(target.id)
        if tb <= 0:
            await message.answer(f"❌ Нет фишек!", parse_mode="HTML")
            return
        set_balance(target.id, -tb)
        await message.answer(f"✅ <b>Забрано всё!</b>\n\n👤 {target.username or target.first_name}\n💸 -{tb:,}\n💎 Баланс: <b>0</b>".replace(',', ' '), parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        row = c.fetchone()
        c.close()
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

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    target = None
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    else:
        args = message.text.split()
        if len(args) >= 2 and args[1].startswith('@'):
            username = args[1][1:]
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT user_id, username FROM users WHERE username = %s", (username,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                ensure_user(row[0], row[1])
                set_banned(row[0], True)
                await message.answer(f"🚫 <b>Игрок @{username} забанен!</b>", parse_mode="HTML")
            else:
                await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
    if not target:
        await message.answer("❌ Ответь на сообщение или напиши: <code>/ban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, True)
    await message.answer(f"🚫 <b>Игрок {target.username or target.first_name} забанен!</b>", parse_mode="HTML")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    target = None
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    else:
        args = message.text.split()
        if len(args) >= 2 and args[1].startswith('@'):
            username = args[1][1:]
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT user_id, username FROM users WHERE username = %s", (username,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                ensure_user(row[0], row[1])
                set_banned(row[0], False)
                await message.answer(f"✅ <b>Игрок @{username} разбанен!</b>", parse_mode="HTML")
            else:
                await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
    if not target:
        await message.answer("❌ Ответь на сообщение или напиши: <code>/unban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, False)
    await message.answer(f"✅ <b>Игрок {target.username or target.first_name} разбанен!</b>", parse_mode="HTML")

# ========== КНОПКИ ==========
@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await call.answer("🚫 ВЫ ЗАБЛОКИРОВАНЫ", show_alert=True)
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)

    if data == "menu_main":
        if is_unlimited(user_id):
            bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
        else:
            bal_line = f"💎 <b>{balance:,}</b>".replace(',', ' ')
        txt = f"🎰 <b>WORLD CASINO</b>\n\n👤 {username}\n{bal_line}\n🏦 <b>{bank:,}</b>".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_games":
        txt = "🎮 <b>ИГРЫ</b>\n\nВыбери игру:"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=games_kb())

    elif data == "menu_balance":
        if is_unlimited(user_id):
            await call.answer(f"♾️ У тебя БЕЗЛИМИТ\n🏦 Банк: {bank:,}".replace(',', ' '), show_alert=True)
        else:
            await call.answer(f"💎 Баланс: {balance:,}\n🏦 Банк: {bank:,}".replace(',', ' '), show_alert=True)

    elif data == "menu_bank":
        txt = f"🏦 <b>БАНК</b>\n\n👤 {username}\n💎 Баланс: <b>{balance:,}</b>\n🏦 В банке: <b>{bank:,}</b>\n\n<b>Команды в чате:</b>\n<code>банк положить 1000</code>\n<code>банк снять 1000</code>\n\n🔥 <b>+5% в день</b> за хранение!".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_top":
        rows = get_top(10)
        txt = "🏆 <b>ТОП-10</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            txt += f"{medal} {uname} — <b>{bal:,}</b>\n".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

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
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "info_roulette":
        txt = f"🎡 <b>РУЛЕТКА</b>\n\n<code>к 1000</code> — красное (×2)\n<code>ч 1000</code> — чёрное (×2)\n<code>з 1000</code> — зеро (×36)\n<code>1000 5</code> — число (×36)\n<code>1000 1-9 10-18</code> — диапазоны\n\n<code>го</code> — запуск"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_slots":
        txt = f"🎰 <b>СЛОТЫ</b>\n\nНапиши: <code>спин 1000</code>\n\n🍒×10 | 🍋×15 | 🍊×20 | 🍇×25 | 💎×50 | 7️⃣×100"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_coin":
        txt = f"🪙 <b>МОНЕТКА</b>\n\n<code>орёл 1000</code> / <code>решка 1000</code>\n\nУгадал — ×2"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_bj":
        txt = f"🃏 <b>БЛЭКДЖЕК</b>\n\nНапиши: <code>бж 1000</code>\n\n➕ Взять | ✋ Хватит\n\nВыигрыш — ×2"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_hl":
        txt = f"🃏 <b>HL (карты)</b>\n\nНапиши: <code>хл 1000</code>\n\nУгадай — выше или ниже\nКоэффициент от ×1.13 до ×12.48\n💰 Забрать — комиссия 10%"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_duel":
        txt = f"⚔️ <b>ДУЭЛЬ 1 на 1</b>\n\n<b>Как играть:</b>\n1. Напиши: <code>дуэль 1000 @username</code>\n2. Второй игрок пишет: <code>принять</code>\n3. Ставки списываются у обоих\n4. 🔴🔵 Шарик крутится\n5. На чём остановится — тот выиграл\n6. Победитель забирает банк (2 ставки)"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

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
            await call.answer("❌ Минимум 10!", show_alert=True)
            return
        if balance < bet and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно! {balance}", show_alert=True)
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
        rkb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=rkb)

    elif data.startswith("group_bet_"):
        parts = data.split("_")
        bet_type = parts[2]
        bet = int(parts[3])
        if bet < 10:
            await call.answer("❌ Минимум 10!", show_alert=True)
            return
        if balance < bet and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно! {balance}", show_alert=True)
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
        rkb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"group_bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"group_bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=rkb)

    elif data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])}\n\n💥 <b>Перебор!</b>\n💸 -{game['bet']:,}\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=group_kb())
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} перебор")
            del bj_games[user_id]
        else:
            await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])}\n\n🎯 <b>Ещё карту?</b>", parse_mode="HTML", reply_markup=bj_kb())

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
        await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {' '.join(game['player'])} = <b>{p_score}</b>\n🤖 {' '.join(game['dealer'])} = <b>{d_score}</b>\n\n{result_text}\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=group_kb())
        del bj_games[user_id]

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
            await call.message.edit_text(f"🃏 <b>HL — Карты</b>\n\n✅ Верно! <b>{current_card}</b> → <b>{next_card}</b>\n\n🃏 Карта: <b>{next_card}</b>\n📈 Множитель: <b>×{game['mult']:.2f}</b>\n💰 Выигрыш: <b>{game['win_amount']:,}</b>\n\n⬆️ ×{up_mult_new} | ⬇️ ×{down_mult_new}".replace(',', ' '), parse_mode="HTML", reply_markup=hl_kb(up_mult_new, down_mult_new, game["win_amount"]))
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "HL", game["bet"], 0, f"{current_card}→{next_card}")
            await call.message.edit_text(f"💥 <b>Неверно! Карта: {next_card}</b>\n\n📉 Проиграл <b>{game['bet']:,}</b>\n\n🏁 <b>Игра окончена</b>\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=group_kb())
            del hl_games[user_id]

    elif data == "hl_cashout":
        if user_id not in hl_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = hl_games[user_id]
        wa = int(game["win_amount"] * 0.9)
        nb = set_balance(user_id, wa)
        log_game(user_id, username, "HL", game["bet"], wa, f"забрал ×{game['mult']}")
        await call.message.edit_text(f"💰 <b>Забрал: {wa:,}</b>\n\n📉 Комиссия 10%: −{int(game['win_amount'] * 0.1):,}\n🔥 Серия: {game['streak']}\n\n💎 <b>{nb:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=group_kb())
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
    if message.chat.type == 'private':
        return
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    ensure_user(user_id, username)

    # БАН
    if is_banned(user_id):
        await message.reply("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return

    # ДУЭЛЬ
    if len(parts) >= 3 and parts[0] == 'дуэль':
        try:
            bet = int(parts[1])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        target_username = None
        if len(parts) >= 3 and parts[2].startswith('@'):
            target_username = parts[2][1:]
        if not target_username:
            await message.reply("❌ Напиши: <code>дуэль 1000 @username</code>", parse_mode="HTML")
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = %s", (target_username,))
        row = c.fetchone()
        c.close()
        conn.close()
        if not row:
            await message.reply(f"❌ @{target_username} не найден!")
            return
        opponent_id = row[0]
        if opponent_id == user_id:
            await message.reply("❌ Нельзя вызвать себя!")
            return
        if chat_id in duel_games:
            await message.reply("❌ Уже есть активная дуэль в этом чате!")
            return
        duel_games[chat_id] = {
            "challenger_id": user_id,
            "challenger_name": username,
            "challenger_bet": bet,
            "opponent_id": opponent_id,
            "opponent_name": target_username,
            "opponent_bet": bet,
            "active": False
        }
        await message.reply(f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n👤 {username} вызывает @{target_username}\n💰 Ставка: <b>{bet:,}</b> с каждого\n\n@{target_username}, напиши <code>принять</code>!".replace(',', ' '), parse_mode="HTML")
        return

    if text == 'принять':
        if chat_id not in duel_games or duel_games[chat_id].get("active"):
            return
        duel = duel_games[chat_id]
        if duel["opponent_id"] != user_id:
            return
        c_balance = get_balance(duel["challenger_id"])
        o_balance = get_balance(duel["opponent_id"])
        if c_balance < duel["challenger_bet"] and not is_unlimited(duel["challenger_id"]):
            await message.reply(f"❌ У {duel['challenger_name']} недостаточно фишек!")
            del duel_games[chat_id]
            return
        if o_balance < duel["opponent_bet"] and not is_unlimited(duel["opponent_id"]):
            await message.reply(f"❌ У тебя недостаточно! Нужно {duel['opponent_bet']:,}".replace(',', ' '))
            return
        set_balance(duel["challenger_id"], -duel["challenger_bet"])
        set_balance(duel["opponent_id"], -duel["opponent_bet"])
        duel["active"] = True
        total_bank = duel["challenger_bet"] + duel["opponent_bet"]
        await message.reply(f"⚔️ <b>ДУЭЛЬ НАЧАЛАСЬ!</b>\n\n👤 {duel['challenger_name']} vs {duel['opponent_name']}\n💰 Банк: <b>{total_bank:,}</b>\n\n🔴 🔵 Шарик крутится...".replace(',', ' '), parse_mode="HTML")
        await asyncio.sleep(2)
        winner_color = random.choice(['red', 'blue'])
        if winner_color == 'red':
            winner_id = duel["challenger_id"]
            winner_name = duel["challenger_name"]
            loser_name = duel["opponent_name"]
            color_emoji = "🔴"
        else:
            winner_id = duel["opponent_id"]
            winner_name = duel["opponent_name"]
            loser_name = duel["challenger_name"]
            color_emoji = "🔵"
        new_balance = set_balance(winner_id, total_bank)
        log_game(winner_id, winner_name, "дуэль", total_bank // 2, total_bank, f"vs {loser_name}")
        await message.reply(f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n{color_emoji} Шарик остановился на <b>{color_emoji}</b>\n\n🏆 Победитель: <b>{winner_name}</b>\n💰 +{total_bank:,}\n💎 Баланс: <b>{new_balance:,}</b>".replace(',', ' '), parse_mode="HTML")
        del duel_games[chat_id]
        return

    if text == 'отмена' and chat_id in duel_games and not duel_games[chat_id].get("active"):
        duel = duel_games[chat_id]
        if user_id in [duel["challenger_id"], duel["opponent_id"]]:
            del duel_games[chat_id]
            await message.reply("❌ <b>Дуэль отменена</b>", parse_mode="HTML")
        return

    # БАНК
    if text == 'банк':
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        total = balance + bank
        await message.reply(f"🏦 <b>БАНК</b>\n\n👤 {username}\n💰 Баланс: <b>{balance:,}</b>\n🏦 В банке: <b>{bank:,}</b>\n💎 Всего: <b>{total:,}</b>\n\n<code>банк положить 1000</code>\n<code>банк снять 1000</code>".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'положить':
        try:
            amount = int(parts[2])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        balance = get_balance(user_id)
        if balance < amount and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -amount)
        new_bank = set_bank(user_id, amount)
        new_balance = get_balance(user_id)
        await message.reply(f"🏦 <b>В банк</b>\n\n💰 -{amount:,}\n💎 Баланс: <b>{new_balance:,}</b>\n🏦 Банк: <b>{new_bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'снять':
        try:
            amount = int(parts[2])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        bank = get_bank(user_id)
        if bank < amount:
            await message.reply(f"❌ В банке только {bank:,}".replace(',', ' '))
            return
        set_bank(user_id, -amount)
        new_balance = set_balance(user_id, amount)
        new_bank = get_bank(user_id)
        await message.reply(f"🏦 <b>Из банка</b>\n\n💰 +{amount:,}\n💎 Баланс: <b>{new_balance:,}</b>\n🏦 Банк: <b>{new_bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

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
        if balance < amount and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        ensure_user(target.id, target.username or target.first_name)
        set_balance(user_id, -amount)
        set_balance(target.id, amount)
        nb = get_balance(user_id)
        nt = get_balance(target.id)
        await message.reply(f"💸 <b>Перевод!</b>\n\n👤 {username} → {target.username or target.first_name}\n💰 <b>{amount:,}</b>\n\n💎 Твой: <b>{nb:,}</b>\n💎 Получателя: <b>{nt:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # ОТМЕНА (ставки)
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
        bank = get_bank(user_id)
        if is_unlimited(user_id):
            await message.reply(f"💰 <b>Баланс</b>\n\n👤 {username}\n♾️ <b>У тебя БЕЗЛИМИТ</b>\n🏦 Банк: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        else:
            await message.reply(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 <b>{balance:,}</b>\n🏦 Банк: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    # ИГРЫ
    if text in ['игры', 'игра']:
        await message.reply("🎮 <b>ИГРЫ</b>\n\nВыбери игру:", parse_mode="HTML", reply_markup=games_kb())
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
        user_last_bet = None
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
            if b["user_id"] == user_id:
                user_last_bet = b
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
        if user_last_bet:
            rkb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"group_bet_{user_last_bet['type']}_{user_last_bet['bet']}"),
                 InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"group_bet_{user_last_bet['type']}_{user_last_bet['bet']*2}")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
            ])
            await message.reply(result_text, parse_mode="HTML", reply_markup=rkb)
        else:
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
        if balance < bet and not is_unlimited(user_id):
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
        if balance < bet and not is_unlimited(user_id):
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
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        card = get_random_card()
        hl_games[user_id] = {
            "card": card, "bet": bet, "mult": 1.0,
            "win_amount": bet, "streak": 0
        }
        up_mult, down_mult = get_hl_mults(card)
        await message.reply(
            f"🃏 <b>HL — Карты</b>\n\n"
            f"🃏 Карта: <b>{card}</b>\n"
            f"📈 Множитель: <b>×1.00</b>\n"
            f"💰 Выигрыш: <b>{bet:,}</b>\n\n"
            f"⬆️ ×{up_mult} | ⬇️ ×{down_mult}".replace(',', ' '),
            parse_mode="HTML", reply_markup=hl_kb(up_mult, down_mult, bet)
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
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно! {balance}")
            return
        set_balance(user_id, -bet)
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        bj_games[user_id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}
        p_score = hand_score(player)
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Ты: {' '.join(player)} = <b>{p_score}</b>\n🤖 Дилер: {' '.join(dealer)}\n\n🎯 <b>Ещё карту?</b>",
            parse_mode="HTML", reply_markup=bj_kb()
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
        if balance < bet and not is_unlimited(user_id):
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
        if balance < total_bet and not is_unlimited(user_id):
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
async def bank_interest_loop():
    while True:
        await asyncio.sleep(86400)
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE users SET bank = bank + (bank * 0.05)::BIGINT WHERE bank > 0")
            conn.commit()
            c.close()
            conn.close()
            print("🏦 Проценты начислены")
        except Exception as e:
            print(f"Ошибка процентов: {e}")

async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    asyncio.create_task(bank_interest_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
