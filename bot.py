# ==============================================================================
# ИМПЕРИЯ TOKENS — Telegram-бот (aiogram 3.x + PostgreSQL)
# Полный рабочий код в одном файле.
# ==============================================================================

import os
import asyncio
import random
import logging
import datetime
from typing import Optional

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from psycopg_pool import ConnectionPool

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, LabeledPrice,
    ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# ==============================================================================
# 1. НАСТРОЙКИ
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens_bot")

BOT_TOKEN = "8940867005:AAHeQpS4_I1XZWfzC107G3EPNneQF_8JbYA"
ADMIN_ID = 6403424348
CHAT_ID = -1004366922819
GROUP_LINK = "https://t.me/tokenplays"
LINK_TO_TERMS = "https://telegra.ph/Pravila-01-01"
PORT = 8080

START_BONUS = 5000
CURRENCY    = "Tokens"

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ==============================================================================
# 2. БАЗА ДАННЫХ
# ==============================================================================
db_pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1, max_size=10, timeout=10,
)


def db_execute(query: str, params=(), fetchone: bool = False, fetchall: bool = False):
    """Синхронный запрос к БД. Вызывать через asyncio.to_thread."""
    query = query.replace("?", "%s")
    try:
        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = None
                if fetchone:
                    result = cur.fetchone()
                elif fetchall:
                    result = cur.fetchall()
                conn.commit()
                return result
    except Exception as e:
        logger.error(f"DB error: {e} | query={query} | params={params}")
        return None


def get_user(user_id: int):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        db_execute(
            "INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, "Unknown", START_BONUS),
        )
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return user


def update_balance(user_id: int, amount: int):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))


def set_username(user_id: int, username: str):
    db_execute("UPDATE users SET username = ? WHERE user_id = ?", (username or "Unknown", user_id))


def format_money(amount: int) -> str:
    try:
        return f"{int(amount):,}".replace(",", " ") + f" {CURRENCY}"
    except Exception:
        return f"{amount} {CURRENCY}"


def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        lang TEXT DEFAULT 'ru',
        balance BIGINT DEFAULT 5000,
        role TEXT DEFAULT 'user',
        last_bonus TEXT,
        clan_id INTEGER DEFAULT NULL,
        clan_donated BIGINT DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id SERIAL PRIMARY KEY,
        name TEXT,
        owner_id BIGINT,
        treasury BIGINT DEFAULT 0,
        join_fee BIGINT DEFAULT 5000,
        level INTEGER DEFAULT 1
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS tickets (
        id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (
        id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet BIGINT, win BIGINT, date TEXT
    )""")
    logger.info("DB initialized.")


def log_game(user_id: int, game: str, bet: int, win: int):
    db_execute(
        "INSERT INTO games_log (user_id, game, bet, win, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, game, bet, win, datetime.datetime.now().isoformat()),
    )


# ==============================================================================
# 3. СТИКЕРЫ
# ==============================================================================
STICKER_MONEY    = "CAACAgIAAxkBAAEj985q4eL9Brj-YpyQvGjLXw3FCOZZjQACSKgAAjAhEUsk5lafkHLFYD0E"
STICKER_GIFT     = "CAACAgIAAxkBAAEj98Bq4eLXEYu2vZI5kR8FAa-5At5VCwACLqwAAkDWEEu1vr_yoL997j0E"
STICKER_CHECK    = "CAACAgIAAxkBAAEj97Jq4eKR30htSL0IqPlPzJVRVzFtJwACYqIAAmLKEEtbsW05dAABQME9BA"
STICKER_CROSS    = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"
STICKER_VIP      = "CAACAgIAAxkBAAEj99Bq4eL-1vc-E-lWg0SnnmQOohX96wACxaQAAu96EUteo43HZ6JM4T0E"
STICKER_WAIT     = "CAACAgIAAxkBAAEj97hq4eKu4LVAQjvc8bvWLJsPGs4AAfcAAu6lAAIhCRFLfU-i5scDVp49BA"
STICKER_TRANSFER = "CAACAgEAAxkBAAEj9-Bq4eVW4VZEtByB92myle5Upux2mgACzgIAAgZEGETPmJF48lyuaD0E"
STICKER_TICKET   = "CAACAgIAAxkBAAEj975q4eLJDqoTYwmhP1WgPmG147qWZgACdKkAAlAcEEt7BK5iDF740T0E"
STICKER_WHEEL    = "CAACAgIAAxkBAAEj98Jq4eLY_6DZL-z-pta0MkNblBDoIAACY6YAAopJCEulegpkQ4jAtj0E"
VIP_STICKERS = [
    "CAACAgIAAxkBAAEj96xq4eJXgVef7iLshpSS5HehGR9fvAACX7IAAgOYEEtkVuP2AAGD3tY9BA",
    "CAACAgIAAxkBAAEj965q4eJ3NdOJTNZKOXjLl-EefvciHgACJaAAAuNkEEtMkr6KfsoC1j0E",
    "CAACAgIAAxkBAAEj97Bq4eJ6Nm0yg_NAkGH6X0a3pgmesAACXrgAAjPACUvbsySuV4_7ez0E",
]


# ==============================================================================
# 4. КЛАВИАТУРЫ
# ==============================================================================
def get_main_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус"))
    b.row(KeyboardButton(text="💎 Донат"), KeyboardButton(text="🛡 Клан"))
    b.row(KeyboardButton(text="🆘 Поддержка"))
    return b.as_markup(resize_keyboard=True)


def get_profile_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📜 История"), KeyboardButton(text="🔗 Моя Рефка"))
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


def get_support_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="💰 Как заработать?"), KeyboardButton(text="💳 Проблема с оплатой"))
    b.row(KeyboardButton(text="✍️ Написать Админу"), KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


def get_donate_menu() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="⭐ Купить Звезды"), KeyboardButton(text="👑 Купить VIP"))
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


# ==============================================================================
# 5. BOT / DISPATCHER / ROUTERS
# ==============================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

user_router  = Router()
admin_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, group_router)


# ==============================================================================
# 6. FSM-СОСТОЯНИЯ
# ==============================================================================
class SupportStates(StatesGroup):
    waiting_ticket = State()


class StarStates(StatesGroup):
    waiting_amount = State()


class ClanStates(StatesGroup):
    waiting_name = State()
    waiting_deposit = State()
    waiting_kick = State()
    waiting_join = State()
    waiting_fee = State()


# ==============================================================================
# 7. ОБЩИЕ ХЕНДЛЕРЫ (ЛС)
# ==============================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if message.from_user.username:
        await asyncio.to_thread(set_username, message.from_user.id, message.from_user.username)

    if user and user[4] == "banned":
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return await message.answer("🚫 <b>Твой аккаунт заблокирован.</b>")

    text = (
        f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В ИМПЕРИЮ TOKENS, {message.from_user.first_name}!</b>\n\n"
        f"💎 Здесь ты сам вершишь свою судьбу. Испытай удачу в играх, "
        f"прокачай свой клан или сорви джекпот в нашем чате!\n\n"
        f"⚖️ <i>Виртуальная экономика. Все ставки — развлечение. Играй с умом.</i>\n\n"
        f"📜 Нажимая кнопки ниже, ты соглашаешься с правилами нашего Дома."
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚀 Ворваться в игру (Чат)", url=GROUP_LINK))
    kb.row(InlineKeyboardButton(text="📜 Правила Дома", url=LINK_TO_TERMS))

    try:
        await message.answer_photo(FSInputFile("assets/start.jpg"), caption=text, reply_markup=kb.as_markup())
    except Exception:
        await message.answer(text, reply_markup=kb.as_markup())

    await message.answer("👇 <i>Твой личный кабинет:</i>", reply_markup=get_main_menu())


@user_router.message(F.text == "⬅️ Назад")
async def global_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню:", reply_markup=get_main_menu())


# ==============================================================================
# 8. ПРОФИЛЬ
# ==============================================================================
@user_router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    balance = user[3] or 0
    if balance > 1_000_000:
        rank = "💎 Легенда"
    elif balance > 500_000:
        rank = "🔥 Хайроллер"
    elif balance > 100_000:
        rank = "⭐ Профи"
    else:
        rank = "🟢 Новичок"

    vip = "👑 VIP" if user[4] == "vip" else "❌ Нет"
    text = (
        f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"🏆 Ранг: <b>{rank}</b>\n"
        f"💰 Баланс: <b>{format_money(balance)}</b>\n"
        f"💎 VIP: {vip}\n"
        f"🛡 Клан: {'Есть' if user[12] else 'Нет'}"
    )
    if user[4] == "vip":
        try:
            await message.answer_sticker(random.choice(VIP_STICKERS))
        except Exception:
            pass
    await message.answer(text, reply_markup=get_profile_menu())


@user_router.message(F.text == "📜 История")
async def history(message: Message):
    rows = await asyncio.to_thread(
        db_execute,
        "SELECT game, bet, win, date FROM games_log WHERE user_id = ? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,), False, True,
    )
    if not rows:
        return await message.answer("📜 История пуста. Сыграй в чате!", reply_markup=get_profile_menu())
    lines = ["📜 <b>Последние 10 игр:</b>\n"]
    for game, bet, win, date in rows:
        sign = "🟢" if win > 0 else "🔴"
        lines.append(f"{sign} <b>{game}</b> · ставка {format_money(bet)} · выигрыш {format_money(win)}")
    await message.answer("\n".join(lines), reply_markup=get_profile_menu())


@user_router.message(F.text == "🔗 Моя Рефка")
async def refka(message: Message):
    link = f"https://t.me/{(await bot.get_me()).username}?start=ref_{message.from_user.id}"
    await message.answer(f"🔗 <b>Твоя реферальная ссылка:</b>\n<code>{link}</code>\n\n"
                         f"Приглашай друзей и получай бонусы!", reply_markup=get_profile_menu())


# ==============================================================================
# 9. БОНУС
# ==============================================================================
@user_router.message(F.text == "🎁 Бонус")
async def daily_bonus(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    now = datetime.datetime.now()

    if user[5]:
        try:
            last_dt = datetime.datetime.fromisoformat(user[5])
            if now - last_dt < datetime.timedelta(hours=24):
                delta = datetime.timedelta(hours=24) - (now - last_dt)
                try:
                    await message.answer_sticker(STICKER_WAIT)
                except Exception:
                    pass
                return await message.answer(
                    f"⏳ <b>Бонус уже забран.</b>\n"
                    f"Следующий через: <b>{delta.seconds // 3600} ч. "
                    f"{(delta.seconds % 3600) // 60} мин.</b>",
                    reply_markup=get_main_menu(),
                )
        except ValueError:
            pass

    try:
        await message.answer_sticker(STICKER_WHEEL)
    except Exception:
        pass

    status = await message.answer("🎁 <i>Крутим колесо удачи...</i> 🎡")
    await asyncio.sleep(1.5)

    prizes = [
        (2500, 25), (3000, 20), (4000, 15), (5000, 15),
        (7500, 10), (10000, 7), (15000, 4), (20000, 2.5), (25000, 1.5),
    ]
    prize = random.choices([p[0] for p in prizes], weights=[p[1] for p in prizes], k=1)[0]

    await asyncio.to_thread(update_balance, user[0], prize)
    await asyncio.to_thread(
        db_execute,
        "UPDATE users SET last_bonus = ? WHERE user_id = ?",
        (now.isoformat(), user[0]),
    )
    await status.delete()
    await message.answer(
        f"🎉 <b>УДАЧА УЛЫБНУЛАСЬ ТЕБЕ!</b>\n\n"
        f"💰 Ты выиграл: <b>+{format_money(prize)}</b>\n\n"
        f"<i>Приходи завтра!</i>",
        reply_markup=get_main_menu(),
    )


# ==============================================================================
# 10. ДОНАТ
# ==============================================================================
def _get_rate() -> int:
    hour = datetime.datetime.now().hour
    rnd = random.Random(hour // 3)
    return rnd.randint(8000, 15000)


@user_router.message(F.text == "💎 Донат")
async def donate_menu(message: Message):
    rate = _get_rate()
    await message.answer(
        f"💎 <b>ДОНАТ И VIP</b>\n\n"
        f"🔥 Курс дня: 1 ⭐ = <b>{rate:,}</b> {CURRENCY}\n"
        f"<i>(Обновляется каждые 3 часа)</i>\n\n"
        f"👇 <i>Выбери:</i>",
        reply_markup=get_donate_menu(),
    )


@user_router.message(F.text == "⭐ Купить Звезды")
async def buy_stars_menu(message: Message):
    rate = _get_rate()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ 15 Stars", callback_data=f"buy_stars_15_{rate}"))
    kb.row(InlineKeyboardButton(text="⭐ 50 Stars", callback_data=f"buy_stars_50_{rate}"))
    kb.row(InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_stars_custom"))
    await message.answer(
        f"⭐ <b>ПОКУПКА ЗВЕЗД</b>\n\n🔥 Курс: 1 ⭐ = {rate} {CURRENCY}\n\nВыбери пакет:",
        reply_markup=kb.as_markup(),
    )


@user_router.callback_query(F.data == "buy_stars_custom")
async def stars_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введи количество звёзд (1–10000):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(StarStates.waiting_amount)
    await callback.answer()


@user_router.message(StarStates.waiting_amount)
async def stars_custom_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if not 1 <= amount <= 10000:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введи целое число от 1 до 10000.")
    rate = _get_rate()
    await message.answer_invoice(
        title=f"Звезды ({amount})",
        description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}_{rate}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=amount)],
        start_parameter="buy",
    )
    await state.clear()


@user_router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    data = callback.data
    if data == "buy_stars_custom":
        return  # обработан выше
    _, _, amount, rate = data.split("_")
    await callback.message.answer_invoice(
        title="Звезды", description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}_{rate}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=int(amount))],
        start_parameter="buy",
    )
    await callback.answer()


@user_router.message(F.text == "👑 Купить VIP")
async def buy_vip_menu(message: Message):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👑 VIP 1 день (5 ⭐)", callback_data="buy_vip_5_1"))
    kb.row(InlineKeyboardButton(text="👑 VIP 7 дней (30 ⭐)", callback_data="buy_vip_30_7"))
    kb.row(InlineKeyboardButton(text="👑 VIP 30 дней (100 ⭐)", callback_data="buy_vip_100_30"))
    await message.answer("👑 <b>ПОКУПКА VIP</b>\n\nВыбери срок:", reply_markup=kb.as_markup())


@user_router.callback_query(F.data.startswith("buy_vip_"))
async def process_buy_vip(callback: CallbackQuery):
    _, _, price, days = callback.data.split("_")
    await callback.message.answer_invoice(
        title=f"VIP {days} дн.", description="Активация VIP",
        payload=f"vip_{days}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label="VIP", amount=int(price))],
        start_parameter="buy",
    )
    await callback.answer()


@user_router.message(F.successful_payment)
async def success_payment(message: Message):
    payment = message.successful_payment
    user = await asyncio.to_thread(get_user, message.from_user.id)

    if payment.invoice_payload.startswith("vip_"):
        days = int(payment.invoice_payload.split("_")[1])
        await asyncio.to_thread(db_execute, "UPDATE users SET role = 'vip' WHERE user_id = ?", (user[0],))
        await asyncio.to_thread(update_balance, user[0], 10000 * days)
        try:
            await message.answer_sticker(random.choice(VIP_STICKERS))
        except Exception:
            pass
        await message.answer(f"✅ <b>VIP АКТИВИРОВАН!</b>\nСрок: {days} дней.", reply_markup=get_main_menu())

    elif payment.invoice_payload.startswith("stars_"):
        _, stars_amount, rate = payment.invoice_payload.split("_")
        total = int(stars_amount) * int(rate)
        await asyncio.to_thread(update_balance, user[0], total)
        try:
            await message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        await message.answer(
            f"✅ <b>ОПЛАТА УСПЕШНА!</b>\nЗачислено: <b>{format_money(total)}</b>",
            reply_markup=get_main_menu(),
        )


# ==============================================================================
# 11. ПОДДЕРЖКА (ТИКЕТЫ)
# ==============================================================================
@user_router.message(F.text == "🆘 Поддержка")
async def support_menu(message: Message):
    await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>", reply_markup=get_support_menu())


@user_router.message(F.text == "💰 Как заработать?")
async def sup_earn(message: Message):
    await message.answer(
        "💰 <b>Как заработать?</b>\n\n"
        "• 🎁 Бонус (раз в 24ч)\n"
        "• 🎲 Игры в чате\n"
        "• 🛡 Налог с клана\n"
        "• 🚨 Ловить дропы\n"
        "• 👑 VIP",
        reply_markup=get_support_menu(),
    )


@user_router.message(F.text == "💳 Проблема с оплатой")
async def sup_pay(message: Message, state: FSMContext):
    await message.answer("✍️ Опиши проблему одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_ticket)


@user_router.message(F.text == "✍️ Написать Админу")
async def sup_ticket(message: Message, state: FSMContext):
    await message.answer("✍️ Опиши проблему одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_ticket)


@user_router.message(SupportStates.waiting_ticket)
async def process_ticket(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    await asyncio.to_thread(
        db_execute,
        "INSERT INTO tickets (user_id, text, date) VALUES (?, ?, ?)",
        (user[0], message.text, datetime.datetime.now().isoformat()),
    )
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🎫 <b>ТИКЕТ</b>\nОт: @{message.from_user.username or message.from_user.id}\n{message.text}",
        )
    except Exception as e:
        logger.warning(f"Тикет не отправлен админу: {e}")
    try:
        await message.answer_sticker(STICKER_TICKET)
    except Exception:
        pass
    await message.answer("✅ Тикет отправлен.", reply_markup=get_main_menu())
    await state.clear()


# ==============================================================================
# 12. ГРУППОВЫЕ: БАЛАНС / ПЕРЕВОД
# ==============================================================================
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    user = await asyncio.to_thread(get_user, message.from_user.id)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    await message.reply(f"💰 <b>Баланс</b> {name}:\n💵 <b>{format_money(user[3])}</b>")


@group_router.message(F.text.regexp(r"(?i)^перевод\s+(\d+)$"))
async def cmd_transfer_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if not message.reply_to_message:
        return await message.reply("❌ Ответь (Reply) на сообщение получателя!")
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id:
        return await message.reply("❌ Себе нельзя!")
    if target_id == bot.id:
        return await message.reply("❌ Боту нельзя!")
    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except Exception:
        return await message.reply("❌ Введи положительное число!")

    sender = await asyncio.to_thread(get_user, message.from_user.id)
    if sender[3] < amount:
        return await message.reply("❌ Мало средств!")

    await asyncio.to_thread(update_balance, sender[0], -amount)
    await asyncio.to_thread(get_user, target_id)
    await asyncio.to_thread(update_balance, target_id, amount)

    try:
        await message.answer_sticker(STICKER_TRANSFER)
    except Exception:
        pass
    await message.reply(
        f"✅ <b>Перевод выполнен!</b>\n\n"
        f"👤 От: {message.from_user.first_name}\n"
        f"👤 Кому: {message.reply_to_message.from_user.first_name}\n"
        f"💰 Сумма: <b>{format_money(amount)}</b>"
    )


# ==============================================================================
# 13. ИГРЫ: СТИКЕРНЫЕ КУБИКИ
# ==============================================================================
DICE_EMOJI = {
    "кости": "🎲", "дартс": "🎯", "баскет": "🏀",
    "футбол": "⚽", "боулинг": "🎳", "слот": "🎰",
}


@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг|слот)\s+(\d+)$"))
async def play_dice_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    parts = message.text.lower().split()
    game, amount = parts[0], int(parts[1])
    if amount <= 0:
        return await message.reply("❌ Ставка должна быть положительной.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply("❌ Мало средств.")
    await asyncio.to_thread(update_balance, user[0], -amount)

    msg = await message.answer_dice(emoji=DICE_EMOJI[game])
    await asyncio.sleep(3.5)
    val = msg.dice.value

    win = False
    if game in ("кости", "дартс") and val >= 4:
        win = True
    elif game == "баскет" and val >= 3:
        win = True
    elif game == "футбол" and val >= 4:
        win = True
    elif game == "боулинг" and val == 6:
        win = True
    elif game == "слот" and val in (1, 22, 43, 64):
        win = True

    if win:
        prize = amount * 2
        await asyncio.to_thread(update_balance, user[0], prize)
        await asyncio.to_thread(log_game, user[0], game, amount, prize)
        try:
            await message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        await message.reply(f"🎉 <b>ПОБЕДА!</b>\nВыпало: {val}\nВыигрыш: <b>{format_money(prize)}</b>")
    else:
        await asyncio.to_thread(log_game, user[0], game, amount, 0)
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        await message.reply(f"😢 <b>Проигрыш.</b>\nВыпало: {val}")


# ==============================================================================
# 14. УМНАЯ РУЛЕТКА
# ==============================================================================
active_roulette: dict = {}
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


def _parse_roulette_bet(raw: str):
    """Возвращает (тип, значение) или None."""
    raw = raw.lower()
    if raw in ("к", "красное"):
        return ("color", "к")
    if raw in ("ч", "черное"):
        return ("color", "ч")
    if raw in ("з", "зеро"):
        return ("color", "з")
    if raw == "чет":
        return ("parity", "чет")
    if raw == "нечет":
        return ("parity", "нечет")
    if "-" in raw:
        try:
            a, b = raw.split("-")
            a, b = int(a), int(b)
            if 0 <= a < b <= 36:
                return ("range", (a, b))
        except Exception:
            return None
    if raw.isdigit():
        n = int(raw)
        if 0 <= n <= 36:
            return ("number", n)
    return None


def _roulette_multiplier(kind: str) -> float:
    return {"number": 36, "range": 2.5, "color": 2, "parity": 2}[kind]


@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+|\d+)\s+(\d+)$"))
async def bet_roulette(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    chat_id = message.chat.id
    if chat_id not in active_roulette:
        active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting":
        return await message.reply("⏳ Идёт раунд, подожди.")

    parts = message.text.lower().split()
    bet_raw, amount_raw = parts[0], parts[1]
    parsed = _parse_roulette_bet(bet_raw)
    if not parsed:
        return
    kind, value = parsed

    try:
        amount = int(amount_raw)
        if amount < 100:
            return await message.reply("❌ Минимальная ставка 100.")
    except Exception:
        return

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply("❌ Мало средств.")

    await asyncio.to_thread(update_balance, user[0], -amount)
    active_roulette[chat_id]["bets"].append({
        "uid": user[0],
        "name": message.from_user.first_name,
        "kind": kind,
        "value": value,
        "raw": bet_raw,
        "amount": amount,
    })
    await message.reply(
        f"✅ <b>Ставка принята:</b> {message.from_user.first_name}\n"
        f"🎯 На: {bet_raw.upper()}\n"
        f"💰 Сумма: {format_money(amount)}"
    )


@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    chat_id = message.chat.id
    state = active_roulette.get(chat_id)
    if not state or not state["bets"]:
        return
    state["status"] = "playing"

    try:
        msg = await message.answer_animation(
            animation=FSInputFile("assets/roulette.gif"),
            caption="🎡 <i>Рулетка крутится...</i>",
        )
    except Exception:
        msg = await message.answer("🎡 <i>Рулетка крутится...</i>")
    await asyncio.sleep(3)

    result = random.randint(0, 36)
    if result == 0:
        color = "з"
    elif result in RED_NUMS:
        color = "к"
    else:
        color = "ч"
    color_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[color]

    lines = [f"🎯 Выпало: <b>{result} {color_name}</b>\n"]
    winners = []
    for b in state["bets"]:
        win = False
        k, v = b["kind"], b["value"]
        if k == "color" and v == color:
            win = True
        elif k == "parity":
            if v == "чет" and result != 0 and result % 2 == 0:
                win = True
            if v == "нечет" and result % 2 != 0:
                win = True
        elif k == "range" and v[0] <= result <= v[1]:
            win = True
        elif k == "number" and v == result:
            win = True

        if win:
            prize = int(b["amount"] * _roulette_multiplier(k))
            await asyncio.to_thread(update_balance, b["uid"], prize)
            await asyncio.to_thread(log_game, b["uid"], "рулетка", b["amount"], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")

    lines.append("\n".join(winners) if winners else "😢 Победителей нет.")
    text = "\n".join(lines)
    try:
        await msg.edit_caption(caption=text)
    except Exception:
        try:
            await msg.edit_text(text)
        except Exception:
            pass

    active_roulette[chat_id] = {"status": "waiting", "bets": []}


# ==============================================================================
# 15. МИНЫ 5×5
# ==============================================================================
active_mines: dict = {}


def _mines_keyboard(game_key: str, opened: list, cash: Optional[int] = None, reveal_all=None):
    kb = InlineKeyboardBuilder()
    for i in range(25):
        if reveal_all is not None:
            text = "💥" if i in reveal_all else "💎"
            cb = "m_ign"
        elif i in opened:
            text = "💎"
            cb = "m_ign"
        else:
            text = "⬜"
            cb = f"m_{game_key}_{i}"
        kb.button(text=text, callback_data=cb)
    kb.adjust(5, 5, 5, 5, 5)
    if cash is not None:
        kb.row(InlineKeyboardButton(text=f"💰 Забрать {format_money(cash)}", callback_data=f"m_cash_{game_key}"))
    return kb.as_markup()


@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except Exception:
        return await message.reply("❌ Некорректная ставка.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply("❌ Мало средств.")
    await asyncio.to_thread(update_balance, user[0], -amount)

    game_key = f"{message.chat.id}_{message.from_user.id}"
    active_mines[game_key] = {
        "uid": user[0], "bet": amount,
        "mines": set(random.sample(range(25), 5)),
        "opened": [],
    }
    kb = _mines_keyboard(game_key, [], 0)
    await message.reply(
        f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}\n"
        f"Открывай клетки, забирай выигрыш — не попади на мину!",
        reply_markup=kb,
    )


@group_router.callback_query(F.data.startswith("m_"))
async def mines_callback(callback: CallbackQuery):
    data = callback.data
    if data == "m_ign":
        return await callback.answer("Недоступно.")

    if data.startswith("m_cash_"):
        game_key = data[len("m_cash_"):]
        game = active_mines.get(game_key)
        if not game:
            return await callback.answer("Игра окончена.", show_alert=True)
        if callback.from_user.id != game["uid"]:
            return await callback.answer("Не твоя игра!", show_alert=True)
        win = int(game["bet"] * (1 + len(game["opened"]) * 0.2)) if game["opened"] else 0
        if win:
            await asyncio.to_thread(update_balance, game["uid"], win)
            await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], win)
        await callback.message.edit_text(
            f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}"
        )
        del active_mines[game_key]
        try:
            await callback.message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        return await callback.answer("Зачислено!")

    # m_{chatid}_{userid}_{cell}
    parts = data.split("_")
    if len(parts) < 4:
        return await callback.answer()
    game_key = f"{parts[1]}_{parts[2]}"
    cell = int(parts[3])
    game = active_mines.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)
    if cell in game["opened"]:
        return await callback.answer("Уже открыта.")

    if cell in game["mines"]:
        kb = _mines_keyboard(game_key, [], None, reveal_all=game["mines"])
        await callback.message.edit_text(
            f"💥 <b>БУМ!</b> Проигрыш {format_money(game['bet'])}.",
            reply_markup=kb,
        )
        await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], 0)
        del active_mines[game_key]
        try:
            await callback.message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return await callback.answer("Мина!")

    game["opened"].append(cell)
    potential = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    kb = _mines_keyboard(game_key, game["opened"], potential)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"Безопасно! Потенциал: {format_money(potential)}")


# ==============================================================================
# 16. БЛЭКДЖЕК
# ==============================================================================
BJ_SUITS = ["♠", "♥", "♦", "♣"]
BJ_RANKS = [("2",2),("3",3),("4",4),("5",5),("6",6),("7",7),("8",8),("9",9),
            ("10",10),("J",10),("Q",10),("K",10),("A",11)]

active_bj: dict = {}


def _new_deck():
    deck = [(r, v, s) for (r, v) in BJ_RANKS for s in BJ_SUITS]
    random.shuffle(deck)
    return deck


def _hand_value(hand):
    total = sum(v for _, v, _ in hand)
    aces = sum(1 for r, _, _ in hand if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _format_hand(hand, hide=False):
    if hide:
        return f"{hand[0][0]}{hand[0][2]}  🂠"
    return "  ".join(f"{r}{s}" for r, _, s in hand)


def _bj_keyboard(game_key: str, can_take=True, can_stop=True):
    kb = InlineKeyboardBuilder()
    if can_take:
        kb.row(InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{game_key}"))
    if can_stop:
        kb.row(InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj_stop_{game_key}"))
    return kb.as_markup()


@group_router.message(F.text.regexp(r"(?i)^бж\s+(\d+)$"))
async def play_bj(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
    except Exception:
        return await message.reply("❌ Некорректная ставка.")

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply("❌ Мало средств.")
    await asyncio.to_thread(update_balance, user[0], -amount)

    deck = _new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    game_key = f"{message.chat.id}_{message.from_user.id}"
    active_bj[game_key] = {"uid": user[0], "bet": amount, "deck": deck,
                            "player": player, "dealer": dealer, "chat_id": message.chat.id}

    text = (
        f"🃏 <b>БЛЭКДЖЕК</b>\nСтавка: {format_money(amount)}\n\n"
        f"👤 <b>Ты:</b> {_format_hand(player)}  (сумма: {_hand_value(player)})\n"
        f"🤖 <b>Дилер:</b> {_format_hand(dealer, hide=True)}"
    )
    kb = _bj_keyboard(game_key)
    await message.reply(text, reply_markup=kb)

    # сразу блэкджек у игрока?
    if _hand_value(player) == 21:
        await _bj_finish(message, game_key, message.chat.id)


@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(callback: CallbackQuery):
    game_key = callback.data[len("bj_hit_"):]
    game = active_bj.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)

    game["player"].append(game["deck"].pop())
    val = _hand_value(game["player"])
    if val > 21:
        await callback.answer("Перебор!")
        return await _bj_finish(callback.message, game_key, game["chat_id"], bust=True)

    text = (
        f"🃏 <b>БЛЭКДЖЕК</b>\nСтавка: {format_money(game['bet'])}\n\n"
        f"👤 <b>Ты:</b> {_format_hand(game['player'])}  (сумма: {val})\n"
        f"🤖 <b>Дилер:</b> {_format_hand(game['dealer'], hide=True)}"
    )
    kb = _bj_keyboard(game_key)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@group_router.callback_query(F.data.startswith("bj_stop_"))
async def bj_stop(callback: CallbackQuery):
    game_key = callback.data[len("bj_stop_"):]
    game = active_bj.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)
    await callback.answer()
    await _bj_finish(callback.message, game_key, game["chat_id"])


async def _bj_finish(message: Message, game_key: str, chat_id: int, bust: bool = False):
    game = active_bj.pop(game_key, None)
    if not game:
        return
    player_val = _hand_value(game["player"])
    dealer = game["dealer"]
    while _hand_value(dealer) < 17:
        dealer.append(game["deck"].pop())
    dealer_val = _hand_value(dealer)

    # определить исход
    if bust or player_val > 21:
        result, prize = "💥 Перебор! Ты проиграл.", 0
    elif dealer_val > 21 or player_val > dealer_val:
        prize = game["bet"] * 2
        result = f"🎉 Ты победил! Выигрыш: {format_money(prize)}"
    elif player_val == dealer_val:
        prize = game["bet"]
        result = f"🤝 Ничья. Возврат: {format_money(prize)}"
    else:
        result, prize = "😢 Дилер победил.", 0

    if prize:
        await asyncio.to_thread(update_balance, game["uid"], prize)
    await asyncio.to_thread(log_game, game["uid"], "блэкджек", game["bet"], prize)

    text = (
        f"🃏 <b>БЛЭКДЖЕК — ИТОГ</b>\n\n"
        f"👤 <b>Ты:</b> {_format_hand(game['player'])}  (сумма: {player_val})\n"
        f"🤖 <b>Дилер:</b> {_format_hand(dealer)}  (сумма: {dealer_val})\n\n"
        f"{result}"
    )
    try:
        await message.edit_text(text)
    except Exception:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    try:
        if prize:
            await message.answer_sticker(STICKER_CHECK)
        else:
            await message.answer_sticker(STICKER_CROSS)
    except Exception:
        pass


# ==============================================================================
# 17. ИГРОВОЙ ЗАЛ
# ==============================================================================
@user_router.message(F.text == "🎮 Игры")
async def games_hall(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(
        "🎮 <b>ИГРОВОЙ ЗАЛ</b>\n\n"
        "Все игры доступны <b>только в чате</b>! Перейди по ссылке и пиши команды:\n\n"
        "🎲 <code>кости 1000</code> · <code>дартс 1000</code>\n"
        "🏀 <code>баскет 1000</code> · <code>футбол 1000</code>\n"
        "🎳 <code>боулинг 1000</code> · <code>слот 1000</code>\n\n"
        "🎡 <b>Рулетка:</b>\n"
        "<code>к 1000</code> — красное\n"
        "<code>ч 1000</code> — чёрное\n"
        "<code>10-23 500</code> — диапазон\n"
        "<code>13 100</code> — число\n"
        "Затем кто-то пишет <code>го</code> — запуск!\n\n"
        "💣 <code>мины 1000</code>\n"
        "🃏 <code>бж 1000</code>\n\n"
        "💡 Перевод: <code>перевод 1000</code> (ответом на сообщение)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚀 В чат", url=GROUP_LINK)
        ]])
    )


# ==============================================================================
# 18. КЛАНЫ
# ==============================================================================
def _clan_menu_kb(has_clan: bool, is_owner: bool):
    b = ReplyKeyboardBuilder()
    if not has_clan:
        b.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
        b.row(KeyboardButton(text="🤝 Вступить в клан"))
    else:
        b.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="🏆 Топ кланов"))
        b.row(KeyboardButton(text="📜 Мой клан"), KeyboardButton(text="🏅 Топ меценатов"))
        if is_owner:
            b.row(KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📈 Прокачать клан"))
            b.row(KeyboardButton(text="💵 Собрать налог"), KeyboardButton(text="🥾 Кикнуть игрока"))
        else:
            b.row(KeyboardButton(text="🚪 Выйти из клана"))
    b.row(KeyboardButton(text="⬅️ Назад"))
    return b.as_markup(resize_keyboard=True)


@user_router.message(F.text == "🛡 Клан")
async def clan_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await asyncio.to_thread(get_user, message.from_user.id)
    text = "🛡 <b>КЛАНОВАЯ СИСТЕМА</b>\n\n<i>Объединяйся, качай уровень, получай бонусы!</i>\n\n"

    if not user[12]:
        text += "Ты пока не в клане."
        await message.answer(text, reply_markup=_clan_menu_kb(False, False))
        return

    clan = await asyncio.to_thread(
        db_execute,
        "SELECT id, name, owner_id, treasury, COALESCE(join_fee, 5000), COALESCE(level, 1) "
        "FROM clans WHERE id = ?",
        (user[12],), True,
    )
    if not clan:
        await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
        return await message.answer("Клан не найден. Выбери действие:", reply_markup=_clan_menu_kb(False, False))

    cid, name, owner_id, treasury, join_fee, level = clan
    is_owner = owner_id == user[0]
    progress = min(int((treasury / 1_000_000) * 10), 10)
    bar = "🟩" * progress + "⬜️" * (10 - progress)

    text += (
        f"<b>Твой клан:</b> {name}\n"
        f"<b>Уровень:</b> {level} / 5\n"
        f"<b>Роль:</b> {'👑 Владелец' if is_owner else '🛡 Рядовой'}\n"
        f"<b>Казна:</b> {format_money(treasury)}\n"
        f"[{bar}]\n"
        f"<b>Награда за вход:</b> {format_money(join_fee)}"
    )
    await message.answer(text, reply_markup=_clan_menu_kb(True, is_owner))


@user_router.message(F.text == "➕ Создать клан (100к)")
async def clan_create_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < 100_000:
        return await message.answer("❌ Нужно 100 000 Tokens.")
    if user[12]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана (до 30 символов):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_name)


@user_router.message(ClanStates.waiting_name)
async def clan_create_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:30]
    if not name:
        return await message.answer("❌ Пустое имя.")
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < 100_000:
        await state.clear()
        return await message.answer("❌ Не хватает средств.")
    await asyncio.to_thread(update_balance, user[0], -100_000)
    clan = await asyncio.to_thread(
        db_execute,
        "INSERT INTO clans (name, owner_id, treasury, join_fee, level) VALUES (?, ?, 0, 5000, 1) RETURNING id",
        (name, user[0]), True,
    )
    if clan:
        await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = ? WHERE user_id = ?", (clan[0], user[0]))
        try:
            await message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        await message.answer(f"✅ Клан <b>{name}</b> создан!", reply_markup=get_main_menu())
    else:
        await message.answer("❌ Ошибка создания.")
    await state.clear()


@user_router.message(F.text == "🏆 Топ кланов")
async def clan_top(message: Message):
    rows = await asyncio.to_thread(
        db_execute,
        "SELECT name, treasury, level FROM clans ORDER BY treasury DESC LIMIT 10",
        (), False, True,
    )
    if not rows:
        return await message.answer("🏆 Пока нет кланов.")
    lines = ["🏆 <b>ТОП-10 КЛАНОВ</b>\n"]
    for i, (name, treasury, level) in enumerate(rows, 1):
        lines.append(f"{i}. <b>{name}</b> · ур.{level} · {format_money(treasury)}")
    await message.answer("\n".join(lines))


@user_router.message(F.text == "🏅 Топ меценатов")
async def donors_top(message: Message):
    rows = await asyncio.to_thread(
        db_execute,
        "SELECT u.username, u.clan_donated FROM users u WHERE u.clan_donated > 0 "
        "ORDER BY u.clan_donated DESC LIMIT 10",
        (), False, True,
    )
    if not rows:
        return await message.answer("🏅 Пока нет меценатов.")
    lines = ["🏅 <b>ТОП-10 МЕЦЕНАТОВ</b>\n"]
    for i, (username, amount) in enumerate(rows, 1):
        lines.append(f"{i}. @{username or '—'} — {format_money(amount)}")
    await message.answer("\n".join(lines))


@user_router.message(F.text == "💰 Внести в казну")
async def clan_deposit_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
    await message.answer("💰 Введи сумму для внесения в казну:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_deposit)


@user_router.message(ClanStates.waiting_deposit)
async def clan_deposit_finish(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except Exception:
        return await message.answer("❌ Введи положительное число.")
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        await state.clear()
        return await message.answer("❌ Мало средств.")
    await asyncio.to_thread(update_balance, user[0], -amount)
    await asyncio.to_thread(
        db_execute,
        "UPDATE clans SET treasury = treasury + ? WHERE id = ?",
        (amount, user[12]),
    )
    await asyncio.to_thread(
        db_execute,
        "UPDATE users SET clan_donated = clan_donated + ? WHERE user_id = ?",
        (amount, user[0]),
    )
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    await message.answer(f"✅ Внесено в казну: <b>{format_money(amount)}</b>", reply_markup=get_main_menu())
    await state.clear()


@user_router.message(F.text == "📜 Мой клан")
async def clan_my(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
    clan = await asyncio.to_thread(
        db_execute, "SELECT name, treasury, level, owner_id FROM clans WHERE id = ?", (user[12],), True
    )
    members = await asyncio.to_thread(
        db_execute, "SELECT COUNT(*) FROM users WHERE clan_id = ?", (user[12],), True
    )
    if not clan:
        return await message.answer("❌ Клан не найден.")
    name, treasury, level, owner_id = clan
    owner = await asyncio.to_thread(db_execute, "SELECT username FROM users WHERE user_id = ?", (owner_id,), True)
    await message.answer(
        f"📜 <b>{name}</b>\n"
        f"👑 Владелец: @{owner[0] if owner else '—'}\n"
        f"📈 Уровень: {level}\n"
        f"👥 Участников: {members[0] if members else 0}\n"
        f"💰 Казна: {format_money(treasury)}"
    )


@user_router.message(F.text == "⚙️ Настройки")
async def clan_settings(message: Message):
    await message.answer(
        "⚙️ <b>Настройки клана</b>\n\n"
        "• Изменить награду за вход — кнопка «Настройки» → введи сумму\n"
        "• Прокачать клан — до 5 уровня",
    )


@user_router.message(F.text == "📈 Прокачать клан")
async def clan_upgrade(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id, level, treasury FROM clans WHERE id = ?", (user[12],), True
    )
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может качать клан.")
    if clan[1] >= 5:
        return await message.answer("✅ Клан уже максимального уровня.")
    cost = 250_000 * clan[1]
    if user[3] < cost:
        return await message.answer(f"❌ Нужно {format_money(cost)} на балансе.")
    await asyncio.to_thread(update_balance, user[0], -cost)
    await asyncio.to_thread(db_execute, "UPDATE clans SET level = level + 1 WHERE id = ?", (user[12],))
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    await message.answer(f"📈 Клан прокачан до уровня {clan[1] + 1}!")


@user_router.message(F.text == "💵 Собрать налог")
async def clan_tax(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id, treasury FROM clans WHERE id = ?", (user[12],), True
    )
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может собрать налог.")
    tax = int(clan[1] * 0.10)
    if tax <= 0:
        return await message.answer("❌ Казна пуста.")
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury - ? WHERE id = ?", (tax, user[12]))
    await asyncio.to_thread(update_balance, user[0], tax)
    try:
        await message.answer_sticker(STICKER_MONEY)
    except Exception:
        pass
    await message.answer(f"💵 Собрано 10% налога: <b>{format_money(tax)}</b>")


@user_router.message(F.text == "🥾 Кикнуть игрока")
async def clan_kick_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return
    clan = await asyncio.to_thread(db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[12],), True)
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может кикать.")
    await message.answer(
        "🥾 Отправь @username или ID игрока (или ответом на его сообщение):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(ClanStates.waiting_kick)


@user_router.message(ClanStates.waiting_kick)
async def clan_kick_finish(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        raw = (message.text or "").strip().lstrip("@")
        if raw.isdigit():
            target_id = int(raw)
        else:
            found = await asyncio.to_thread(
                db_execute, "SELECT user_id FROM users WHERE username = ?", (raw,), True
            )
            if found:
                target_id = found[0]
    if not target_id:
        await state.clear()
        return await message.answer("❌ Игрок не найден.")
    target = await asyncio.to_thread(get_user, target_id)
    if not target or target[12] != user[12]:
        await state.clear()
        return await message.answer("❌ Игрок не в твоём клане.")
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (target_id,))
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    await message.answer("✅ Игрок исключён из клана.", reply_markup=get_main_menu())
    await state.clear()


@user_router.message(F.text == "🚪 Выйти из клана")
async def clan_leave(message: Message):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[12]:
        return await message.answer("❌ Ты не в клане.")
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[12],), True
    )
    if clan and clan[0] == user[0]:
        return await message.answer("👑 Владелец не может выйти. Передай клан или удали.")
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
    await message.answer("✅ Ты вышел из клана.", reply_markup=get_main_menu())


@user_router.message(F.text == "🤝 Вступить в клан")
async def clan_join_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[12]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана для вступления:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_join)


@user_router.message(ClanStates.waiting_join)
async def clan_join_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    clan = await asyncio.to_thread(
        db_execute,
        "SELECT id, join_fee FROM clans WHERE name = ?", (name,), True,
    )
    if not clan:
        await state.clear()
        return await message.answer("❌ Клан не найден.", reply_markup=get_main_menu())
    cid, fee = clan
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < fee:
        await state.clear()
        return await message.answer(f"❌ Нужно {format_money(fee)} на вход.", reply_markup=get_main_menu())

    await asyncio.to_thread(update_balance, user[0], -fee)
    await asyncio.to_thread(
        db_execute, "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (fee, cid)
    )
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = ? WHERE user_id = ?", (cid, user[0]))
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    await message.answer(f"✅ Ты вступил в клан <b>{name}</b>!", reply_markup=get_main_menu())
    await state.clear()


# ==============================================================================
# 19. НЕЙРО-АДМИН
# ==============================================================================
def _parse_amount(raw: str) -> Optional[int]:
    """'10к' → 10000, '1кк' → 1000000."""
    raw = raw.lower().strip().replace("к", "000").replace("кк", "000000")
    try:
        return int(raw)
    except Exception:
        return None


def _find_user_id(token: str) -> Optional[int]:
    token = token.replace("@", "")
    if token.isdigit():
        res = db_execute("SELECT user_id FROM users WHERE user_id = ?", (int(token),), True)
        return res[0] if res else None
    res = db_execute("SELECT user_id FROM users WHERE username = ?", (token,), True)
    return res[0] if res else None


@admin_router.message(F.text.startswith("@"))
async def neuro_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        return
    cmd = args[0].lower()

    if cmd == "@бан":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'banned' WHERE user_id = ?", (uid,))
            return await message.reply(f"🚫 Игрок {args[1]} забанен.")

    elif cmd == "@анбан":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'user' WHERE user_id = ?", (uid,))
            return await message.reply(f"✅ Игрок {args[1]} разбанен.")

    elif cmd == "@вип":
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role = 'vip' WHERE user_id = ?", (uid,))
            try:
                await message.reply_sticker(random.choice(VIP_STICKERS))
            except Exception:
                pass
            return await message.reply(f"👑 {args[1]} теперь VIP.")

    elif cmd == "@выдать" and len(args) >= 3:
        uid = _find_user_id(args[1])
        amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, amount)
            return await message.reply(f"✅ Выдано {format_money(amount)} → {args[1]}.")

    elif cmd == "@забрать" and len(args) >= 3:
        uid = _find_user_id(args[1])
        amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, -amount)
            return await message.reply(f"✅ Забрано {format_money(amount)} у {args[1]}.")

    elif cmd == "@дроп" and len(args) >= 2:
        amount = _parse_amount(args[1])
        if amount:
            kb = InlineKeyboardBuilder()
            kb.button(text="💰 СХВАТИТЬ", callback_data=f"drop_{amount}")
            await bot.send_message(
                CHAT_ID,
                f"🚨 <b>ДРОП!</b> Кто первый нажмёт — заберёт {format_money(amount)}!",
                reply_markup=kb.as_markup(),
            )
            await message.reply("✅ Дроп запущен.")


@group_router.callback_query(F.data.startswith("drop_"))
async def claim_drop(callback: CallbackQuery):
    try:
        amount = int(callback.data.split("_")[1])
    except Exception:
        return await callback.answer()
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await asyncio.to_thread(update_balance, user[0], amount)
    try:
        await callback.message.answer_sticker(STICKER_MONEY)
    except Exception:
        pass
    try:
        await callback.message.edit_text(
            f"💰 Мешок забрал <b>{callback.from_user.first_name}</b>! "
            f"Он получил {format_money(amount)}!"
        )
    except Exception:
        pass
    await callback.answer("Ты забрал куш!", show_alert=True)


# ==============================================================================
# 20. АВТО-ДРОП (каждые 2 часа)
# ==============================================================================
async def auto_drop():
    amount = random.choice([10000, 25000, 50000])
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 СХВАТИТЬ", callback_data=f"drop_{amount}")
    try:
        await bot.send_message(
            CHAT_ID,
            f"🚨 <b>ЗОЛОТАЯ ЛИХОРАДКА!</b> 🚨\n\n"
            f"Кто первый нажмёт — заберёт {format_money(amount)}!",
            reply_markup=kb.as_markup(),
        )
    except Exception as e:
        logger.warning(f"Авто-дроп не отправлен: {e}")


# ==============================================================================
# 21. ЗАПУСК + aiohttp health-check
# ==============================================================================
async def health(_):
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web-сервер на :{PORT}")


async def main():
    await asyncio.to_thread(init_db)
    scheduler.add_job(auto_drop, "interval", hours=2)
    scheduler.start()
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")