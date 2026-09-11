import asyncio
import logging
import sqlite3
import os
import threading
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from flask import Flask

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DB_PATH = "casino.db"

# ========== ЦВЕТА РУЛЕТКИ ==========
RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]

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

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000

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
    
    balance = get_balance(user_id)
    await message.answer(
        f"🎰 <b>Добро пожаловать в World Casino!</b>\n\n"
        f"👤 Ты: @{username}\n"
        f"💰 Баланс: <b>{balance}</b> монет\n\n"
        f"<b>Команды:</b>\n"
        f"/balance — баланс\n"
        f"/top — топ игроков\n"
        f"/help — помощь\n\n"
        f"<b>🎡 Рулетка в чате:</b>\n"
        f"<code>к 100</code> — ставка на красное\n"
        f"<code>ч 100</code> — ставка на чёрное\n"
        f"<code>з 100</code> — ставка на зеро\n"
        f"<code>100 7</code> — ставка на число 7",
        parse_mode="HTML"
    )

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    balance = get_balance(user_id)
    await message.answer(f"💰 <b>Баланс: {balance} монет</b>", parse_mode="HTML")

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ <b>У тебя нет прав!</b>", parse_mode="HTML")
        return
    
    if not message.reply_to_message:
        await message.answer("🎯 <b>Ответь на сообщение пользователя:</b>\n<code>/give 1000</code>", parse_mode="HTML")
        return
    
    # Проверяем, что replied сообщение — не от бота
    if message.reply_to_message.from_user.is_bot:
        await message.answer("❌ <b>Это сообщение от бота — нельзя дать ему монеты!</b>", parse_mode="HTML")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("🎯 <b>Укажи сумму:</b>\n<code>/give 1000</code>", parse_mode="HTML")
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
        await message.answer("🎯 <b>Ответь на сообщение пользователя:</b>\n<code>/take 1000</code>", parse_mode="HTML")
        return
    
    # Проверяем, что replied сообщение — не от бота
    if message.reply_to_message.from_user.is_bot:
        await message.answer("❌ <b>Это сообщение от бота — нельзя забрать у него монеты!</b>", parse_mode="HTML")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("🎯 <b>Укажи сумму:</b>\n<code>/take 1000</code>", parse_mode="HTML")
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
        "➖ /take (ответом на сообщение) — забрать монеты\n\n"
        "<b>🎡 Рулетка в чате:</b>\n"
        "<code>к 100</code> — ставка на красное\n"
        "<code>ч 100</code> — ставка на чёрное\n"
        "<code>з 100</code> — ставка на зеро\n"
        "<code>100 7</code> — ставка на число 7",
        parse_mode="HTML"
    )

# ========== 🎡 РУЛЕТКА В ЧАТЕ ==========
@dp.message()
async def roulette_handler(message: Message):
    # Игнорируем команды
    if not message.text or message.text.startswith('/'):
        return
    
    # Игнорируем сообщения от ботов
    if message.from_user.is_bot:
        return
    
    text = message.text.strip().lower()
    parts = text.split()
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    
    # ========== СТАВКА НА КРАСНОЕ / ЧЁРНОЕ / ЗЕРО ==========
    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        try:
            bet = int(parts[1])
        except ValueError:
            return
        
        if bet < 10:
            await message.reply("❌ <b>Минимальная ставка — 10 монет!</b>", parse_mode="HTML")
            return
        
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ <b>Недостаточно монет! Баланс: {balance}</b>", parse_mode="HTML")
            return
        
        # Списываем ставку
        set_balance(user_id, -bet)
        
        # Крутим рулетку
        result = random.randint(0, 36)
        if result == 0:
            color = "Зеро 🟢"
        elif result in RED_NUMBERS:
            color = "Красное 🔴"
        else:
            color = "Чёрное ⚫"
        
        # Проверяем выигрыш
        bet_type = parts[0]
        win = False
        multiplier = 0
        
        if bet_type == 'к' and result in RED_NUMBERS:
            win = True; multiplier = 2
        elif bet_type == 'ч' and result in BLACK_NUMBERS:
            win = True; multiplier = 2
        elif bet_type == 'з' and result == 0:
            win = True; multiplier = 36
        
        if win:
            win_amount = bet * multiplier
            new_balance = set_balance(user_id, win_amount)
            await message.reply(
                f"🎡 <b>Выпало: {result}</b> ({color})\n"
                f"🎉 <b>ВЫИГРЫШ +{win_amount}!</b> (x{multiplier})\n"
                f"💰 Баланс: <b>{new_balance}</b>",
                parse_mode="HTML"
            )
        else:
            new_balance = get_balance(user_id)
            await message.reply(
                f"🎡 <b>Выпало: {result}</b> ({color})\n"
                f"😢 <b>Проигрыш -{bet}</b>\n"
                f"💰 Баланс: <b>{new_balance}</b>",
                parse_mode="HTML"
            )
        return
    
    # ========== СТАВКА НА ЧИСЛО (например: "100 7") ==========
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        try:
            bet = int(parts[0])
            number = int(parts[1])
        except ValueError:
            return
        
        if number < 0 or number > 36:
            return
        
        if bet < 10:
            await message.reply("❌ <b>Минимальная ставка — 10 монет!</b>", parse_mode="HTML")
            return
        
        balance = get_balance(user_id)
        if balance < bet:
            await message.reply(f"❌ <b>Недостаточно монет! Баланс: {balance}</b>", parse_mode="HTML")
            return
        
        # Списываем ставку
        set_balance(user_id, -bet)
        
        # Крутим рулетку
        result = random.randint(0, 36)
        if result == 0:
            color = "Зеро 🟢"
        elif result in RED_NUMBERS:
            color = "Красное 🔴"
        else:
            color = "Чёрное ⚫"
        
        if result == number:
            win_amount = bet * 36
            new_balance = set_balance(user_id, win_amount)
            await message.reply(
                f"🎡 <b>Выпало: {result}</b> ({color})\n"
                f"🎉 <b>ДЖЕКПОТ! +{win_amount}!</b> (x36)\n"
                f"💰 Баланс: <b>{new_balance}</b>",
                parse_mode="HTML"
            )
        else:
            new_balance = get_balance(user_id)
            await message.reply(
                f"🎡 <b>Выпало: {result}</b> ({color})\n"
                f"😢 <b>Проигрыш -{bet}</b>\n"
                f"💰 Баланс: <b>{new_balance}</b>",
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
