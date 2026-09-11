import asyncio
import logging
import sqlite3
import os
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from flask import Flask

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DB_PATH = "casino.db"

# ========== ФИКТИВНЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 1000
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            group_name TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def ensure_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()

def set_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def get_top(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO groups (group_id, group_name) VALUES (?, ?)", 
                   (message.chat.id, message.chat.title or "Личка"))
    conn.commit()
    conn.close()
    
    balance = get_user(user_id)[1]
    await message.answer(
        f"🎰 <b>Добро пожаловать в World Casino!</b>\n\n"
        f"👤 Ты: @{username}\n"
        f"💰 Баланс: <b>{balance}</b> монет\n\n"
        f"<b>Команды:</b>\n"
        f"/balance — баланс\n"
        f"/top — топ игроков\n"
        f"/help — помощь",
        parse_mode="HTML"
    )

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    balance = get_user(user_id)[1]
    await message.answer(f"💰 <b>Баланс: {balance} монет</b>", parse_mode="HTML")

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ <b>У тебя нет прав!</b>", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.answer("🎯 <b>Ответь на сообщение пользователя:</b>\n/give 1000", parse_mode="HTML")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("🎯 <b>Укажи сумму:</b>\n/give 1000", parse_mode="HTML")
        return
    
    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Неверная сумма!</b>", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    target_id = target.id
    target_name = target.username or target.first_name
    ensure_user(target_id, target_name)
    
    new_balance = set_balance(target_id, amount)
    
    await message.answer(
        f"✅ <b>@{target_name}</b> получил <b>+{amount}</b> монет!\n"
        f"💰 Новый баланс: <b>{new_balance}</b>",
        parse_mode="HTML"
    )

@dp.message(Command("take"))
async def cmd_take(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ <b>У тебя нет прав!</b>", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.answer("🎯 <b>Ответь на сообщение пользователя:</b>\n/take 1000", parse_mode="HTML")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("🎯 <b>Укажи сумму:</b>\n/take 1000", parse_mode="HTML")
        return
    
    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Неверная сумма!</b>", parse_mode="HTML")
        return
    
    target = message.reply_to_message.from_user
    target_id = target.id
    target_name = target.username or target.first_name
    ensure_user(target_id, target_name)
    
    new_balance = set_balance(target_id, -amount)
    
    await message.answer(
        f"✅ <b>@{target_name}</b> потерял <b>-{amount}</b> монет!\n"
        f"💰 Новый баланс: <b>{new_balance}</b>",
        parse_mode="HTML"
    )

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = get_top(limit=10)
    if not rows:
        await message.answer("📊 <b>Пока нет игроков!</b>", parse_mode="HTML")
        return
    
    text = "🏆 <b>ТОП-10 игроков:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, username, balance) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} @{username} — <b>{balance}</b> монет\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🎰 <b>World Casino — команды:</b>\n\n"
        "💰 /balance — показать баланс\n"
        "🏆 /top — топ игроков\n\n"
        "<b>Только для админа:</b>\n"
        "➕ /give (ответом на сообщение) — дать монеты\n"
        "➖ /take (ответом на сообщение) — забрать монеты",
        parse_mode="HTML"
    )

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
