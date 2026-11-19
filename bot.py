import asyncio
import io
import json
import logging
import os
import random
import time
from pathlib import Path

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.client.default import DefaultBotProperties
from PIL import Image, ImageDraw, ImageFont

# --- КОНФИГ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = Path(__file__).resolve().parent / "tokens.db"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB = None

class CaptchaState(StatesGroup):
    waiting = State()

# --- БАЗА ---
async def init_db():
    global DB
    DB = await aiosqlite.connect(DB_PATH)
    DB.row_factory = aiosqlite.Row
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            balance_tnc REAL DEFAULT 0,
            captcha_passed INTEGER DEFAULT 0
        );
    """)
    await DB.commit()

# --- КАПЧА ---
def make_captcha(code):
    img = Image.new("RGB", (300, 100), (15, 20, 35))
    draw = ImageDraw.Draw(img)
    draw.text((100, 30), code, fill="white")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

async def send_captcha(message: Message, state: FSMContext):
    code = str(random.randint(1000, 9999))
    await state.update_data(code=code)
    await state.set_state(CaptchaState.waiting)
    await message.answer_photo(
        BufferedInputFile(make_captcha(code), "captcha.png"),
        caption="Введи код с картинки:"
    )

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await DB.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    await DB.commit()
    
    cur = await DB.execute("SELECT captcha_passed FROM users WHERE user_id=?", (message.from_user.id,))
    user = await cur.fetchone()
    
    if user and user["captcha_passed"]:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Открыть App", web_app=WebAppInfo(url=WEBAPP_URL))]],
            resize_keyboard=True
        )
        await message.answer("Добро пожаловать!", reply_markup=kb)
    else:
        await send_captcha(message, state)

@dp.message(CaptchaState.waiting)
async def captcha_check(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.strip() == data["code"]:
        await state.clear()
        await DB.execute("UPDATE users SET captcha_passed=1, balance=5000 WHERE user_id=?", (message.from_user.id,))
        await DB.commit()
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Открыть App", web_app=WebAppInfo(url=WEBAPP_URL))]],
            resize_keyboard=True
        )
        await message.answer("✅ Успех! Начислено 5000 TOKENS.", reply_markup=kb)
    else:
        await message.answer("❌ Неверный код, попробуй снова.")
        await send_captcha(message, state)

# --- API ДЛЯ MINI APP ---
async def api_user(request):
    # В реальном проекте тут нужно проверять initData, но для теста просто отдаем баланс
    try:
        data = await request.json()
        # Хак для теста: берем ID из initData (если есть) или просто первого юзера
        # Для простоты отдаем баланс первого попавшегося юзера
        cur = await DB.execute("SELECT * FROM users LIMIT 1")
        user = await cur.fetchone()
        if user:
            return web.json_response({
                "success": True,
                "user": {"balance": user["balance"], "balance_tnc": user["balance_tnc"]}
            })
        return web.json_response({"success": False, "error": "No users"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

# --- ЗАПУСК ---
async def start_web():
    app = web.Application()
    app.router.add_post("/api/user", api_user)
    
    # Раздача Mini App
    webapp_dir = Path(__file__).resolve().parent / "webapp"
    if webapp_dir.exists():
        app.router.add_static("/webapp/", webapp_dir, show_index=True)
        
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Web server on {PORT}")

async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан!")
    
    await init_db()
    await start_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())