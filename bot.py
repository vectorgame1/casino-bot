# bot.py — ТОЧКА ВХОДА (v2 + Web Server)
import asyncio
import logging
import os


from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import F

from config import BOT_TOKEN
from database import init_pool, init_db

# ═══ ИМПОРТЫ МОДУЛЕЙ ═══
import support
import admin_panel
import handlers

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════ ВЕБ-СЕРВЕР ДЛЯ RENDER ═══════════════
async def start_web_server():
    """Мини-сервер, чтобы Render видел открытый порт и не убивал бота."""
    async def health(request):
        return web.Response(text="OK")
    
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")

# ═══════════════ ЗАПУСК БОТА ═══════════════
async def main():
    logger.info("📊 Инициализация пула...")
    init_pool()
    
    logger.info("🗄️ Инициализация БД...")
    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # 🆕 ЭКСТРЕННЫЙ ПЕРЕХВАТ КНОПОК АДМИНКИ
    @dp.message(F.text == "👥 Игроки")
    async def bot_admin_players(message: Message):
        if message.from_user.id != ADMIN_ID: return
        from keyboards import admin_panel_kb
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔍 Скан игрока")],
                [KeyboardButton(text="💰 Выдать баланс"), KeyboardButton(text="💸 Забрать баланс")],
                [KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],
                [KeyboardButton(text="⬅️ Назад в админку")]
            ],
            resize_keyboard=True
        )
        await message.answer("👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n👇 Выбери действие:", parse_mode="HTML", reply_markup=kb)

    @dp.message(F.text == "🎮 Игры")
    async def bot_admin_games(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("🎮 <b>ИГРЫ</b>\n\nВ разработке.", parse_mode="HTML", reply_markup=admin_panel_kb())

    @dp.message(F.text == "💰 Экономика")
    async def bot_admin_economy(message: Message):
        if message.from_user.id != ADMIN_ID: return
        await message.answer("💰 <b>ЭКОНОМИКА</b>\n\nВ разработке.", parse_mode="HTML", reply_markup=admin_panel_kb())

    # ═══ РЕГИСТРАЦИЯ (ПОРЯДОК ВАЖЕН!) ═══
    # 1. Админка (перехватывает кнопки админа)
    admin_panel.register(dp)
    # 2. Поддержка (перехватывает кнопки поддержки)
    support.register(dp)
    # 3. Игрок (Старт, Баланс, Профиль и т.д.)
    handlers.register(dp)

    logger.info("🎰 Запуск polling...")
    await dp.start_polling(bot)

async def main_wrapper():
    # Запускаем веб-сервер в фоне (чтобы Render был счастлив)
    asyncio.create_task(start_web_server())
    # Запускаем самого бота
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(main_wrapper())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот выключен")