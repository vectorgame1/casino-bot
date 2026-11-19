import asyncio
import io
import logging
import os
import random
from pathlib import Path

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
)
from aiogram.client.default import DefaultBotProperties
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# НАСТРОЙКИ
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = Path(__file__).resolve().parent / "tokens.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("TOKENS")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB = None

class CaptchaState(StatesGroup):
    waiting = State()

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
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
    logger.info("Database initialized")

# ==========================================
# КАПЧА (ИСПРАВЛЕНА)
# ==========================================
def make_captcha(code: str):
    img = Image.new("RGB", (400, 150), (15, 20, 35))
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 90)
    except IOError:
        font = ImageFont.load_default()

    # Центрируем текст по картинке
    bbox = draw.textbbox((0, 0), code, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (400 - text_width) // 2
    y = (150 - text_height) // 2 - 15
    
    draw.text((x, y), code, font=font, fill=(255, 255, 255))
    
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

async def send_captcha(message: Message, state: FSMContext):
    code = str(random.randint(1000, 9999))
    await state.update_data(code=code)
    await state.set_state(CaptchaState.waiting)
    
    await message.answer_photo(
        BufferedInputFile(make_captcha(code), "captcha.png"),
        caption="🔐 <b>Введи код с картинки:</b>"
    )

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await DB.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await DB.commit()
    
    cur = await DB.execute("SELECT captcha_passed FROM users WHERE user_id=?", (user_id,))
    user = await cur.fetchone()
    
    if user and user["captcha_passed"]:
        await show_main_menu(message)
    else:
        await send_captcha(message, state)

@dp.message(CaptchaState.waiting)
async def captcha_check(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    try:
        await message.delete()
    except:
        pass

    if message.text and message.text.strip() == data["code"]:
        await state.clear()
        await DB.execute("UPDATE users SET captcha_passed=1, balance=5000 WHERE user_id=?", (user_id,))
        await DB.commit()
        await message.answer("✅ <b>Успех!</b> Начислено 5000 TOKENS.")
        await show_main_menu(message)
    else:
        await message.answer("❌ Неверный код, попробуй снова.")
        await send_captcha(message, state)

# ==========================================
# МЕНЮ (ИСПРАВЛЕНО)
# ==========================================
async def show_main_menu(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Открыть App", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer("Добро пожаловать в TOKENS!", reply_markup=kb)

# ==========================================
# API ДЛЯ MINI APP
# ==========================================
async def api_user(request: web.Request):
    try:
        # Отдаем данные первого пользователя (для теста)
        cur = await DB.execute("SELECT * FROM users LIMIT 1")
        user = await cur.fetchone()
        
        if user:
            return web.json_response({
                "success": True,
                "user": {"balance": user["balance"], "balance_tnc": user["balance_tnc"]}
            })
        return web.json_response({"success": False, "error": "No users"})
    except Exception as e:
        logger.error(f"API error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

# ==========================================
# ЗАПУСК ВЕБ-СЕРВЕРА
# ==========================================
async def start_web():
    app = web.Application()
    app.router.add_post("/api/user", api_user)
    
    webapp_dir = Path(__file__).resolve().parent / "webapp"
    if webapp_dir.exists():
        app.router.add_static("/webapp/", webapp_dir, show_index=True)
    else:
        logger.warning("Папка webapp не найдена!")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# ==========================================
# ГЛАВНАЯ
# ==========================================
async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан!")
    
    await init_db()
    await start_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())