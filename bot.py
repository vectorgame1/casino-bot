# bot.py — ТОЧКА ВХОДА (v2 + Web Server)
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

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

    # ═══ РЕГИСТРАЦИЯ (ПОРЯДОК ВАЖЕН!) ═══
    support.register(dp)
    admin_panel.register(dp)
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