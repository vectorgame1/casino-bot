import asyncio
import logging
import sqlite3
import os
import threading
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask, jsonify, request
from flask_cors import CORS

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DB_PATH = "casino.db"

# ========== ГИФКА ПРИВЕТСТВИЯ ==========
WELCOME_GIF = "CgACAgIAAxkBAAEifPBqo_Vfzg4W5Hfc0OVtbiFMgN5L_wACUK0AA7YhScBYTPh8mwc9PQQ"

# ========== ЦВЕТА РУЛЕТКИ ==========
RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]

# ========== ВЕБ-СЕРВЕР + API ==========
app = Flask(__name__)
CORS(app)

@app.route('/')
def home(): return "Bot is running!"

@app.route('/health')
def health(): return "OK"

@app.route('/api/balance/<int:user_id>')
def api_balance(user_id):
    return jsonify({"user_id": user_id, "balance": get_balance(user_id)})

@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    user_id = data.get('user_id')
    amount = data.get('amount')
    if user_id is None or amount is None:
        return jsonify({"error": "Missing data"}), 400
    return jsonify({"user_id": user_id, "balance": set_balance(user_id, amount)})

@app.route('/api/top')
def api_top():
    return jsonify([{"user_id": r[0], "username": r[1], "balance": r[2]} for r in get_top(10)])

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000)")
    c.execute("CREATE TABLE IF NOT EXISTS groups (group_id INTEGER PRIMARY KEY, group_name TEXT)")
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_top(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="menu_roulette"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top"),
         InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
    ])

def roulette_kb(bet=100):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное x2", callback_data=f"bet_red_{bet}"),
         InlineKeyboardButton(text="⚫ Чёрное x2", callback_data=f"bet_black_{bet}")],
        [InlineKeyboardButton(text="🟢 Зеро x36", callback_data=f"bet_green_{bet}"),
         InlineKeyboardButton(text="🎯 Число x36", callback_data=f"bet_number_{bet}")],
        [InlineKeyboardButton(text="10", callback_data="setbet_10"),
         InlineKeyboardButton(text="100", callback_data="setbet_100"),
         InlineKeyboardButton(text="1000", callback_data="setbet_1000"),
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO groups (group_id, group_name) VALUES (?, ?)", (message.chat.id, message.chat.title or "Личка"))
    conn.commit()
    conn.close()
    balance = get_balance(user_id)
    
    caption = (
        f"╔══════════════════════╗\n"
        f"║   🎰 WORLD CASINO   ║\n"
        f"╚══════════════════════╝\n\n"
        f"👤 Игрок: @{username}\n"
        f"💰 Баланс: <b>{balance:,}</b> монет\n\n"
        f"🎮 <b>Выбери действие:</b>"
    ).replace(',', ' ')
    
    try:
        await bot.send_animation(
            chat_id=message.chat.id,
            animation=WELCOME_GIF,
            caption=caption,
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        print(f"Ошибка гифки: {e}")
        await message.answer(caption, parse_mode="HTML", reply_markup=main_menu_kb())

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    balance = get_balance(user_id)
    text = (
        f"💰 <b>БАЛАНС</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 @{username}\n"
        f"💎 {balance:,} монет\n"
        f"━━━━━━━━━━━━━━━━━━"
    ).replace(',', ' ')
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = get_top(10)
    if not rows:
        await message.answer("📊 <b>Пока нет игроков!</b>", parse_mode="HTML")
        return
    text = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, uname, bal) in enumerate(rows):
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        text += f"{medal} @{uname} — <b>{bal:,}</b>\n".replace(',', ' ')
    text += "━━━━━━━━━━━━━━━━━━"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        f"❓ <b>ПОМОЩЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 /balance — баланс\n"
        f"🏆 /top — топ игроков\n\n"
        f"🎡 <b>Рулетка в чате:</b>\n"
        f"<code>к 100</code> — красное\n"
        f"<code>ч 100</code> — чёрное\n"
        f"<code>з 100</code> — зеро\n"
        f"<code>100 7</code> — число 7\n\n"
        f"👑 <b>Только админ:</b>\n"
        f"<code>/give @user 1000</code>\n"
        f"<code>/take @user 1000</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode="HTML")

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
        new_bal = set_balance(row[0], amount)
        await message.answer(
            f"✅ <b>НАЧИСЛЕНО</b>\n━━━━━━━━━━━━━━━━━━\n👤 @{username}\n➕ +{amount:,}\n💰 {new_bal:,}\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
            parse_mode="HTML"
        ); return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot: return
    if len(args) < 2: return
    try: amount = int(args[1])
    except: return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    new_bal = set_balance(target.id, amount)
    await message.answer(
        f"✅ <b>НАЧИСЛЕНО</b>\n━━━━━━━━━━━━━━━━━━\n👤 @{target.username or target.first_name}\n➕ +{amount:,}\n💰 {new_bal:,}\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
        parse_mode="HTML"
    )

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
        new_bal = set_balance(row[0], -amount)
        await message.answer(
            f"✅ <b>СПИСАНО</b>\n━━━━━━━━━━━━━━━━━━\n👤 @{username}\n➖ -{amount:,}\n💰 {new_bal:,}\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
            parse_mode="HTML"
        ); return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot: return
    if len(args) < 2: return
    try: amount = int(args[1])
    except: return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    new_bal = set_balance(target.id, -amount)
    await message.answer(
        f"✅ <b>СПИСАНО</b>\n━━━━━━━━━━━━━━━━━━\n👤 @{target.username or target.first_name}\n➖ -{amount:,}\n💰 {new_bal:,}\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
        parse_mode="HTML"
    )

# ========== КНОПКИ ==========
@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)

    if data == "menu_main" or data == "menu_roulette":
        balance = get_balance(user_id)
        text = (
            f"╔══════════════════════╗\n"
            f"║   🎰 WORLD CASINO   ║\n"
            f"╚══════════════════════╝\n\n"
            f"💰 Баланс: <b>{balance:,}</b>\n\n"
            f"🎡 <b>Выбери ставку:</b>"
        ).replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=roulette_kb(100))

    elif data == "menu_balance":
        balance = get_balance(user_id)
        await call.answer(f"💰 Баланс: {balance:,}".replace(',', ' '), show_alert=True)

    elif data == "menu_top":
        rows = get_top(10)
        text = "🏆 <b>ТОП-10</b>\n━━━━━━━━━━━━━━━━━━\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, bal) in enumerate(rows):
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            text += f"{medal} @{uname} — {bal:,}\n".replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data == "menu_help":
        text = (
            f"❓ <b>ПОМОЩЬ</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🎡 <b>Рулетка в чате:</b>\n"
            f"<code>к 100</code> — красное\n"
            f"<code>ч 100</code> — чёрное\n"
            f"<code>з 100</code> — зеро\n"
            f"<code>100 7</code> — число\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

    elif data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        bet = get_balance(user_id) if val == "max" else int(val)
        await call.message.edit_reply_markup(reply_markup=roulette_kb(bet))
        await call.answer(f"Ставка: {bet:,}".replace(',', ' '))

    elif data.startswith("bet_"):
        parts = data.split("_")
        bet_type = parts[1]
        bet = int(parts[2])
        balance = get_balance(user_id)
        if bet < 10:
            await call.answer("❌ Минимум 10 монет!", show_alert=True); return
        if balance < bet:
            await call.answer(f"❌ Недостаточно! Баланс: {balance}", show_alert=True); return

        if bet_type == "number":
            await call.answer("🎯 Для числа — напиши в чат: 100 7", show_alert=True); return

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
            win_amount = bet * mult
            new_bal = set_balance(user_id, win_amount)
            text = (
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Выпало: <b>{result}</b> ({color})\n"
                f"🎉 <b>ВЫИГРЫШ +{win_amount:,}</b> (x{mult})\n"
                f"💰 Баланс: <b>{new_bal:,}</b>\n"
                f"━━━━━━━━━━━━━━━━━━"
            ).replace(',', ' ')
        else:
            new_bal = get_balance(user_id)
            text = (
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Выпало: <b>{result}</b> ({color})\n"
                f"😢 <b>Проигрыш -{bet:,}</b>\n"
                f"💰 Баланс: <b>{new_bal:,}</b>\n"
                f"━━━━━━━━━━━━━━━━━━"
            ).replace(',', ' ')
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=roulette_kb(bet))

    await call.answer()

# ========== РУЛЕТКА В ЧАТЕ ==========
@dp.message()
async def roulette_handler(message: Message):
    if not message.text or message.text.startswith('/'):
        return
    if message.from_user.is_bot:
        return
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)

    # к 100, ч 100, з 100
    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10:
            await message.reply("❌ Минимум 10 монет!"); return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        set_balance(user_id, -bet)
        result = random.randint(0, 36)
        if result == 0: color = "🟢 Зеро"
        elif result in RED_NUMBERS: color = "🔴 Красное"
        else: color = "⚫ Чёрное"
        win = False; mult = 0
        if parts[0] == 'к' and result in RED_NUMBERS: win = True; mult = 2
        elif parts[0] == 'ч' and result in BLACK_NUMBERS: win = True; mult = 2
        elif parts[0] == 'з' and result == 0: win = True; mult = 36
        if win:
            wa = bet * mult
            nb = set_balance(user_id, wa)
            await message.reply(
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n🎯 Выпало: <b>{result}</b> ({color})\n🎉 <b>ВЫИГРЫШ +{wa:,}</b> (x{mult})\n💰 Баланс: <b>{nb:,}</b>\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            await message.reply(
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n🎯 Выпало: <b>{result}</b> ({color})\n😢 <b>Проигрыш -{bet:,}</b>\n💰 Баланс: <b>{nb:,}</b>\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
                parse_mode="HTML"
            )
        return

    # 100 7 (ставка на число)
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        try:
            bet = int(parts[0]); number = int(parts[1])
        except:
            return
        if number < 0 or number > 36: return
        if bet < 10:
            await message.reply("❌ Минимум 10 монет!"); return
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ Недостаточно! Баланс: {balance}"); return
        set_balance(user_id, -bet)
        result = random.randint(0, 36)
        if result == 0: color = "🟢 Зеро"
        elif result in RED_NUMBERS: color = "🔴 Красное"
        else: color = "⚫ Чёрное"
        if result == number:
            wa = bet * 36
            nb = set_balance(user_id, wa)
            await message.reply(
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n🎯 Выпало: <b>{result}</b> ({color})\n🏆 <b>ДЖЕКПОТ! +{wa:,}</b> (x36)\n💰 Баланс: <b>{nb:,}</b>\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            await message.reply(
                f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n🎯 Выпало: <b>{result}</b> ({color})\n😢 <b>Проигрыш -{bet:,}</b>\n💰 Баланс: <b>{nb:,}</b>\n━━━━━━━━━━━━━━━━━━".replace(',', ' '),
                parse_mode="HTML"
            )
        return

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
