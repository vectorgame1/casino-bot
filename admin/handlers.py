# handlers.py
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

# Все импорты строго вверху файла!
from config import BOT_NAME, START_BONUS, STARS_RATE, ADMIN_ID
from keyboards import main_menu, games_menu
from database import (
    get_balance, get_rate, set_rate, ensure_user, 
    check_and_give_bonus, is_banned
)
from utils import send_clean


# ═══ ФУНКЦИЯ ДЛЯ ПОДКЛЮЧЕНИЯ ═══
def register(dp: Dispatcher):

    # ── СТАРТ ──
    @dp.message(Command("start"))
    async def start(message: Message):
        user_id = message.from_user.id
        username = message.from_user.username or ""
        
        # 1. Создаем юзера (если его нет)
        ensure_user(user_id, username)
        
        # 2. Проверяем бан
        if is_banned(user_id):
            await send_clean(message, "🚫 <b>Вы заблокированы</b>\nОбратитесь к @vctorw", parse_mode="HTML")
            return
            
        # 3. Выдаем бонус (только если новый)
        is_new = check_and_give_bonus(user_id, START_BONUS)
        
        # 4. Формируем текст
        bonus_text = f"🎁 Тебе подарок: <b>{START_BONUS:,} Tokens</b>\n\n" if is_new else ""
        
        await send_clean(
            message,
            f"🎰 <b>Добро пожаловать в {BOT_NAME}</b>\n\n"
            "Это игровой бот. Здесь только виртуальные Tokens, "
            "реальных ставок нет.\n"
            "Играй ответственно, 18+.\n"
            "Донат — добровольная поддержка проекта.\n\n"
            f"{bonus_text}"
            "Выбери, с чего начнём 👇",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    # ── ИГРЫ ──
    @dp.message(F.text == "🎰 Игры")
    async def games(message: Message):
        await send_clean(
            message,
            "🎰 <b>Игры</b>\n\nВыбери игру 👇",
            parse_mode="HTML",
            reply_markup=games_menu()
        )

    # ── БАЛАНС ──
    @dp.message(F.text == "💰 Баланс")
    async def balance(message: Message):
        bal = get_balance(message.from_user.id)
        await send_clean(
            message,
            f"💰 <b>Баланс</b>\n\n💎 Tokens: <b>{bal:,}</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    # ── НАЗАД ──
    @dp.message(F.text == "⬅️ Назад")
    async def back(message: Message):
        await send_clean(
            message,
            "Главное меню 👇",
            reply_markup=main_menu()
        )

    # ── КУРС (АДМИН) ──
    @dp.message(Command("курс"))
    async def change_rate(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        args = message.text.split()
        if len(args) == 1:
            rate = get_rate("stars_rate", STARS_RATE)
            await message.answer(f"💱 Текущий курс: 1 ⭐ = {rate:,} Tokens\n\nИзменить: <code>/курс 8000</code>", parse_mode="HTML")
            return
        try:
            new_rate = int(args[1])
            set_rate("stars_rate", new_rate)
            await message.answer(f"✅ Новый курс: 1 ⭐ = {new_rate:,} Tokens")
        except ValueError:
            await message.answer("❌ Формат: /курс 8000")