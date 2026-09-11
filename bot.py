import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "ТВОЙ_ТОКЕН_ЗДЕСЬ"  # ← ВСТАВЬ СВОЙ ТОКЕН
ADMIN_ID = 123456789  # ← ВСТАВЬ СВОЙ TELEGRAM ID
DB_PATH = "casino.db"

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            username TEXT,
            balance INTEGER DEFAULT 1000,
            PRIMARY KEY (user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER,
            group_name TEXT,
            PRIMARY KEY (group_id)
        )
    """)
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_top(group_id=None, limit=10):
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
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"🎰 <b>Добро пожаловать в World Casino!</b>\n\n"
        f"👤 Ты: @{username}\n"
        f"💰 Баланс: <b>{get_balance(user_id)}</b> монет\n\n"
        f"<b>Команды:</b>\n"
        f"/balance — баланс\n"
        f"/top — топ игроков\n"
        f"/play — играть в Mini App",
        parse_mode="HTML"
    )

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    balance = get_balance(user_id)
    
    if balance is None:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, message.from_user.username or "unknown"))
        conn.commit()
        conn.close()
        balance = 1000
    
    await message.answer(
        f"💰 <b>Баланс: {balance} монет</b>",
        parse_mode="HTML"
    )

@dp.message(Command("give"))
async def cmd_give(message: Message):
    # Только админ!
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ <b>У тебя нет прав!</b>", parse_mode="HTML")
        return
    
    # Проверяем, что это ответ на сообщение
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
    
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name
    
    set_balance(target_id, amount)
    new_balance = get_balance(target_id)
    
    await message.answer(
        f"✅ <b>@{target_name}</b> получил <b>+{amount}</b> монет!\n"
        f"💰 Новый баланс: <b>{new_balance}</b>",
        parse_mode="HTML"
    )

@dp.message(Command("take"))
async def cmd_take(message: Message):
    # Только админ!
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
    
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name
    
    set_balance(target_id, -amount)
    new_balance = get_balance(target_id)
    
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
        "🏆 /top — топ игроков\n"
        "🎮 /play — играть в Mini App\n\n"
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