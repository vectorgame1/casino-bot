# ==============================================================================
# ИМПЕРИЯ TOKENS — Премиальный Telegram-бот (aiogram 3.x + PostgreSQL)
# Кэш баланса • Гибридное меню (Reply+Inline) • Баннеры • VIP • Гарант • Дуэли
# ==============================================================================

import os
import asyncio
import random
import logging
import datetime
import re
from typing import Optional, Dict, Tuple

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from psycopg_pool import ConnectionPool

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    FSInputFile, LabeledPrice,
    ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ForceReply,
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/your_channel")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/")
LINK_TO_TERMS = os.getenv("LINK_TO_TERMS", "https://t.me/")

START_BONUS = 5000
CURRENCY = "Tokens"
MAX_BET = 10_000_000
DATABASE_URL = os.getenv("DATABASE_URL", "")
REF_BONUS = 5000  # строго пригласившему

# ==============================================================================
# 2. КЭШ БАЛАНСА (для скорости)
# ==============================================================================
_balance_cache: Dict[int, int] = {}
_vip_cache: Dict[int, Optional[datetime.datetime]] = {}


def cache_get_balance(uid: int) -> Optional[int]:
    return _balance_cache.get(uid)


def cache_set_balance(uid: int, val: int):
    _balance_cache[uid] = int(val)


def cache_add_balance(uid: int, amt: int):
    if uid in _balance_cache:
        _balance_cache[uid] += amt


def cache_invalidate(uid: int):
    _balance_cache.pop(uid, None)
    _vip_cache.pop(uid, None)


# ==============================================================================
# 3. БАЗА ДАННЫХ
# ==============================================================================
db_pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, timeout=10)


def db_execute(query: str, params=(), fetchone: bool = False, fetchall: bool = False):
    query = query.replace("?", "%s")
    try:
        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone() if fetchone else cur.fetchall() if fetchall else None
                conn.commit()
                return result
    except Exception as e:
        logger.error(f"DB error: {e} | query={query} | params={params}")
        return None


def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru',
        balance BIGINT DEFAULT 5000, role TEXT DEFAULT 'user', last_bonus TEXT,
        clan_id INTEGER DEFAULT NULL, clan_donated BIGINT DEFAULT 0,
        vip_until TEXT, streak INTEGER DEFAULT 1, last_streak_date TEXT,
        total_bets BIGINT DEFAULT 0, total_win BIGINT DEFAULT 0,
        total_lose BIGINT DEFAULT 0, games_played INTEGER DEFAULT 0,
        last_seen TEXT, referrer_id BIGINT DEFAULT NULL,
        total_donated BIGINT DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id SERIAL PRIMARY KEY, name TEXT, owner_id BIGINT,
        treasury BIGINT DEFAULT 0, join_fee BIGINT DEFAULT 5000,
        level INTEGER DEFAULT 1, shield_until TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS tickets (
        id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (
        id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet BIGINT, win BIGINT, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (
        id SERIAL PRIMARY KEY, user_id BIGINT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS promos (
        code TEXT PRIMARY KEY, reward BIGINT, limit_count INTEGER, used_count INTEGER DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS promo_uses (
        id SERIAL PRIMARY KEY, code TEXT, user_id BIGINT
    )""")

    cols = [
        ("vip_until", "TEXT"), ("streak", "INTEGER DEFAULT 1"), ("last_streak_date", "TEXT"),
        ("total_bets", "BIGINT DEFAULT 0"), ("total_win", "BIGINT DEFAULT 0"),
        ("total_lose", "BIGINT DEFAULT 0"), ("games_played", "INTEGER DEFAULT 0"),
        ("last_seen", "TEXT"), ("referrer_id", "BIGINT DEFAULT NULL"),
        ("total_donated", "BIGINT DEFAULT 0"),
    ]
    for col, ctype in cols:
        db_execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ctype}")
    db_execute("ALTER TABLE clans ADD COLUMN IF NOT EXISTS shield_until TEXT")
    logger.info("DB initialized.")


# ==============================================================================
# 4. РАБОТА С ПОЛЬЗОВАТЕЛЕМ + КЭШ
# ==============================================================================
def get_user(uid: int):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (uid,), True)
    if not user:
        db_execute(
            "INSERT INTO users (user_id, username, balance, last_seen) VALUES (?, 'Unknown', ?, ?) ON CONFLICT DO NOTHING",
            (uid, START_BONUS, datetime.datetime.now().isoformat()),
        )
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (uid,), True)
    if user:
        cache_set_balance(uid, user[3] or 0)
    return user


def get_balance(uid: int) -> int:
    cached = cache_get_balance(uid)
    if cached is not None:
        return cached
    user = get_user(uid)
    return user[3] if user else 0


def update_balance(uid: int, amt: int):
    # обновляем кэш и БД
    cache_add_balance(uid, amt)
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))


def set_username(uid: int, un: str):
    db_execute("UPDATE users SET username = ? WHERE user_id = ?", (un or "Unknown", uid))


def format_money(amt: int) -> str:
    try:
        return f"{int(amt):,}".replace(",", " ") + f" {CURRENCY}"
    except Exception:
        return f"{amt} {CURRENCY}"


def log_game(uid: int, game: str, bet: int, win: int):
    db_execute(
        "INSERT INTO games_log (user_id, game, bet, win, date) VALUES (?, ?, ?, ?, ?)",
        (uid, game, bet, win, datetime.datetime.now().isoformat()),
    )
    if win > 0:
        db_execute(
            "UPDATE users SET total_bets = total_bets + ?, total_win = total_win + ?, games_played = games_played + 1 WHERE user_id = ?",
            (bet, win, uid),
        )
    else:
        db_execute(
            "UPDATE users SET total_bets = total_bets + ?, total_lose = total_lose + ?, games_played = games_played + 1 WHERE user_id = ?",
            (bet, bet, uid),
        )


def parse_amt(txt: str) -> Optional[int]:
    try:
        txt = txt.lower().replace(" ", "")
        m = re.match(r"^(\d+)(кк|к)?$", txt)
        if not m:
            return None
        val = int(m.group(1))
        if m.group(2) == "к":
            val *= 1000
        elif m.group(2) == "кк":
            val *= 1000000
        return val if 0 < val <= MAX_BET else None
    except Exception:
        return None


def is_vip(user) -> bool:
    if not user or not user[9]:
        return False
    try:
        return datetime.datetime.fromisoformat(user[9]) > datetime.datetime.now()
    except Exception:
        return False


# ==============================================================================
# 5. ЛОКАЛИЗАЦИЯ
# ==============================================================================
TEXTS = {
    "ru": {
        "menu": "🏠 <b>Главное меню</b>",
        "btn_play": "🎮 Как играть?",
        "btn_bonus": "🎁 Бонус",
        "btn_donate": "💎 Донат",
        "btn_profile": "👤 Профиль",
        "btn_top": "🏆 Топ",
        "btn_ref": "🔗 Рефералка",
        "btn_back": "⬅️ Назад в меню",
        "not_enough": "❌ Мало средств.",
        "profile": "👑 <b>Профиль:</b> {name}\n💰 Баланс: {bal}\n💎 VIP: {vip}\n🆔 ID: <code>{id}</code>",
        "bonus_wait": "⏳ <b>Бонус уже забран.</b>\nСледующий через: <b>{h} ч. {m} мин.</b>",
        "ref_text": "🔗 <b>Твоя реферальная ссылка:</b>\n<code>{link}</code>\n\n🎁 За каждого друга ты получаешь <b>5 000 Tokens</b>!\n(Друг получает стандартный стартовый бонус)",
        "top_balance": "💰 <b>ТОП-10 по балансу</b>\n\n{lines}",
        "top_donated": "💎 <b>ТОП-10 по донатам</b>\n\n{lines}",
        "top_wins": "🏆 <b>ТОП-10 по выигрышам</b>\n\n{lines}",
    },
    "en": {
        "menu": "🏠 <b>Main menu</b>",
        "btn_play": "🎮 How to play?",
        "btn_bonus": "🎁 Bonus",
        "btn_donate": "💎 Donate",
        "btn_profile": "👤 Profile",
        "btn_top": "🏆 Top",
        "btn_ref": "🔗 Referral",
        "btn_back": "⬅️ Back to menu",
        "not_enough": "❌ Not enough funds.",
        "profile": "👑 <b>Profile:</b> {name}\n💰 Balance: {bal}\n💎 VIP: {vip}\n🆔 ID: <code>{id}</code>",
        "bonus_wait": "⏳ <b>Bonus already taken.</b>\nNext in: <b>{h}h {m}m</b>",
        "ref_text": "🔗 <b>Your referral link:</b>\n<code>{link}</code>\n\n🎁 Get <b>5 000 Tokens</b> for each friend!\n(Friend gets the standard start bonus)",
        "top_balance": "💰 <b>TOP-10 by balance</b>\n\n{lines}",
        "top_donated": "💎 <b>TOP-10 by donations</b>\n\n{lines}",
        "top_wins": "🏆 <b>TOP-10 by wins</b>\n\n{lines}",
    },
}

WIN_PHRASES = [
    "🔥 Ого, да ты везунчик!",
    "🎉 Невероятная удача!",
    "💰 Казна пополняется!",
    "🤩 Фортуна на твоей стороне!",
    "👑 Настоящий хайроллер!",
]
LOSE_PHRASES = [
    "😢 Не повезло, попробуй еще!",
    "💸 В этот раз не твоя игра.",
    "🙈 Обидно, но удача вернется!",
    "😔 Проигрыш — путь к победе.",
    "🤷‍♂️ Крупье сегодня не в духе.",
]


def _(user, key, **kwargs):
    lang = user[2] if user and len(user) > 2 and user[2] in TEXTS else "ru"
    return TEXTS[lang].get(key, "").format(**kwargs)


# ==============================================================================
# 6. ПОДПИСКА
# ==============================================================================
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return True


async def require_subscription(message: Message) -> bool:
    if await check_subscription(message.from_user.id):
        return False
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📢 Перейти в канал", url=CHANNEL_LINK))
    try:
        await message.answer_sticker(STICKER_CROSS)
    except Exception:
        pass
    await message.reply(
        "🔒 <b>Чтобы играть, подпишись на наш канал!</b>",
        reply_markup=kb.as_markup(),
    )
    return True


# ==============================================================================
# 7. СТИКЕРЫ
# ==============================================================================
STICKER_MONEY = "CAACAgIAAxkBAAEj985q4eL9Brj-YpyQvGjLXw3FCOZZjQACSKgAAjAhEUsk5lafkHLFYD0E"
STICKER_GIFT = "CAACAgIAAxkBAAEj98Bq4eLXEYu2vZI5kR8FAa-5At5VCwACLqwAAkDWEEu1vr_yoL997j0E"
STICKER_CHECK = "CAACAgIAAxkBAAEj97Jq4eKR30htSL0IqPlPzJVRVzFtJwACYqIAAmLKEEtbsW05dAABQME9BA"
STICKER_CROSS = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"
STICKER_TRANSFER = "CAACAgEAAxkBAAEj9-Bq4eVW4VZEtByB92myle5Upux2mgACzgIAAgZEGETPmJF48lyuaD0E"
STICKER_TICKET = "CAACAgIAAxkBAAEj975q4eLJDqoTYwmhP1WgPmG147qWZgACdKkAAlAcEEt7BK5iDF740T0E"
STICKER_WHEEL = "CAACAgIAAxkBAAEj98Jq4eLY_6DZL-z-pta0MkNblBDoIAACY6YAAopJCEulegpkQ4jAtj0E"
STICKER_CROWN = "CAACAgIAAxkBAAEj99Bq4eL-1vc-E-lWg0SnnmQOohX96wACxaQAAu96EUteo43HZ6JM4T0E"
STICKER_FIREWORK = "CAACAgIAAxkBAAEj98xq4eL9f_1pJgjxIaZqYyfRDkVuIwACX6UAAt7VEEtyBsfC0Eld5z0E"
STICKER_TICKET_REPLY = "CAACAgIAAxkBAAEj97xq4eLIV5K-h2PJATFWIiPa7RjmrQACU6kAAg9PCEvOBzdsgawr_z0E"
STICKER_CLOCK = "CAACAgIAAxkBAAEj97pq4eK_3AjVJQ0c8YUiUwIfWprFXQACPaEAAm2sEUtORD2DpdGqTz0E"
STICKER_SUPPORT = "CAACAgUAAxkBAAEj-UBq4gLgU_KpjvP5klaeVLVjTVPXhgACcRcAAgFvCVUL3BYqgFb__j0E"
STICKER_SKULL = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"  # fallback
STICKER_FIRE = "CAACAgIAAxkBAAEj98xq4eL9f_1pJgjxIaZqYyfRDkVuIwACX6UAAt7VEEtyBsfC0Eld5z0E"
STICKER_CARD = "CAACAgIAAxkBAAEj975q4eLJDqoTYwmhP1WgPmG147qWZgACdKkAAlAcEEt7BK5iDF740T0E"

VIP_STICKERS = [
    "CAACAgIAAxkBAAEj965q4eJ3NdOJTNZKOXjLl-EefvciHgACJaAAAuNkEEtMkr6KfsoC1j0E",
    "CAACAgIAAxkBAAEj96xq4eJXgVef7iLshpSS5HehGR9fvAACX7IAAgOYEEtkVuP2AAGD3tY9BA",
]

# ==============================================================================
# 8. БАННЕРЫ (assets/)
# ==============================================================================
BANNERS = {
    "how_to_play": "assets/how_to_play.jpg",
    "bonus": "assets/bonus.jpg",
    "donate": "assets/donate.jpg",
    "profile": "assets/profile.jpg",
    "top": "assets/top.jpg",
    "ref": "assets/ref.jpg",
}


async def send_banner(
    target: Message,
    banner_key: str,
    caption: str,
    reply_markup=None,
    sticker: Optional[str] = None,
    use_reply_keyboard=None,
):
    """Отправляет баннер с текстом. Если картинки нет — просто текст. Стикер — в фоне."""
    path = BANNERS.get(banner_key)
    msg = None
    if path and os.path.exists(path):
        try:
            msg = await target.answer_photo(
                FSInputFile(path), caption=caption, reply_markup=reply_markup
            )
        except Exception as e:
            logger.warning(f"banner error {e}")
    if msg is None:
        msg = await target.answer(caption, reply_markup=reply_markup)
    if sticker:
        asyncio.create_task(_safe_sticker(target, sticker))
    return msg


async def _safe_sticker(target: Message, sticker: str):
    try:
        await target.answer_sticker(sticker)
    except Exception:
        pass


# ==============================================================================
# 9. КЛАВИАТУРЫ
# ==============================================================================
def get_main_menu(u):
    """Reply-клавиатура в ЛС — 6 кнопок, 2x3."""
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text=_(u, "btn_play")), KeyboardButton(text=_(u, "btn_bonus")))
    b.row(KeyboardButton(text=_(u, "btn_donate")), KeyboardButton(text=_(u, "btn_profile")))
    b.row(KeyboardButton(text=_(u, "btn_top")), KeyboardButton(text=_(u, "btn_ref")))
    return b.as_markup(resize_keyboard=True)


def inline_back_menu(u):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=_(u, "btn_back"), callback_data="nav_menu"))
    return kb.as_markup()


# ==============================================================================
# 10. BOT / DISPATCHER
# ==============================================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

user_router = Router()
admin_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, group_router)

# ==============================================================================
# 11. FSM
# ==============================================================================
class SupportStates(StatesGroup):
    waiting_ticket = State()
    waiting_bug = State()


class StarStates(StatesGroup):
    waiting_amount = State()


class ClanStates(StatesGroup):
    waiting_name = State()
    waiting_deposit = State()
    waiting_kick = State()
    waiting_join = State()


class GameStates(StatesGroup):
    waiting_dice_bet = State()
    waiting_roulette_bet = State()
    waiting_mines_bet = State()
    waiting_bj_bet = State()


# ==============================================================================
# 12. АВТОУДАЛЕНИЕ
# ==============================================================================
async def auto_delete(message: Message, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def delete_old_messages(bot_instance: Bot, state: FSMContext, chat_id: int):
    data = await state.get_data()
    for mid in data.get("last_msgs", []):
        try:
            await bot_instance.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    await state.update_data(last_msgs=[])


# ==============================================================================
# 13. ЛС — СТАРТ И ГЛАВНОЕ МЕНЮ
# ==============================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)

    # обработка рефералки
    ref_arg = None
    parts = message.text.split()
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            ref_arg = int(parts[1].split("_")[1])
        except Exception:
            ref_arg = None

    user = await asyncio.to_thread(get_user, message.from_user.id)
    if message.from_user.username:
        await asyncio.to_thread(set_username, message.from_user.id, message.from_user.username)

    # обработка рефералки (только пригласившему 5000)
    if ref_arg and ref_arg != message.from_user.id:
        if not user[17]:  # referrer_id пуст
            referrer = await asyncio.to_thread(get_user, ref_arg)
            if referrer:
                await asyncio.to_thread(update_balance, ref_arg, REF_BONUS)
                await asyncio.to_thread(
                    db_execute,
                    "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                    (ref_arg, user[0]),
                )
                try:
                    await bot.send_message(
                        ref_arg,
                        f"🎉 По твоей ссылке пришёл друг! Начислено <b>+{format_money(REF_BONUS)}</b>",
                    )
                except Exception:
                    pass

    await asyncio.to_thread(
        db_execute,
        "UPDATE users SET last_seen = ? WHERE user_id = ?",
        (datetime.datetime.now().isoformat(), user[0]),
    )

    if user[4] == "banned":
        msg = await message.answer("🚫 <b>Твой аккаунт заблокирован.</b>")
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        await state.update_data(last_msgs=[msg.message_id])
        return

    text = (
        f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В ИМПЕРИЮ TOKENS, {message.from_user.first_name}!</b>\n\n"
        "💎 Испытай удачу в играх, прокачай клан или сорви джекпот в чате!\n\n"
        "⚖️ <i>Виртуальная экономика. Ставки — развлечение.</i>\n\n"
        "👇 Выбери раздел:"
    )
    try:
        msg = await message.answer_photo(
            FSInputFile("assets/start.jpg") if os.path.exists("assets/start.jpg") else None,
            caption=text,
            reply_markup=get_main_menu(user),
        ) if os.path.exists("assets/start.jpg") else None
    except Exception:
        msg = None
    if msg is None:
        msg = await message.answer(text, reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


@user_router.callback_query(F.data == "nav_menu")
async def nav_menu(callback: CallbackQuery, state: FSMContext):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await callback.message.answer(_(user, "menu"), reply_markup=get_main_menu(user))
    await callback.answer()


# ==============================================================================
# 14. РАЗДЕЛ «КАК ИГРАТЬ?»
# ==============================================================================
GAMES_INFO = {
    "dice": "🎲 <b>КОСТИ</b>\n\n"
            "Команда: <code>кости 1000</code>\n"
            "Условие: выпало 4, 5 или 6 — победа x2.\n"
            "Коэффициент: x2.\n\n"
            "Пример: <code>кости 5к</code>, <code>кости 1кк</code>",
    "roulette": "🎡 <b>РУЛЕТКА</b>\n\n"
                "Ставки в любом порядке:\n"
                "• <code>к 1000</code> — красное\n"
                "• <code>1000 к</code> — тоже красное\n"
                "• <code>ч 500</code> — черное\n"
                "• <code>10-23 500</code> — диапазон чисел\n"
                "• <code>500 10-23</code> — тоже диапазон\n"
                "• <code>13 100</code> — конкретное число\n"
                "• <code>чет 1000</code> / <code>нечет 1000</code>\n\n"
                "Коэффициенты: число x36, диапазон x2.5, цвет/чётность x2.\n"
                "Запуск раунда: кто-то пишет <code>го</code>.",
    "mines": "💣 <b>МИНЫ</b>\n\n"
             "Команда: <code>мины 1000</code>\n"
             "Открывай клетки, ищи алмазы и бойся бомб.\n"
             "Каждая открытая клетка увеличивает потенциал на 20%.\n"
             "Забрать: кнопка «💰 Забрать».",
    "bj": "🃏 <b>БЛЭКДЖЕК</b>\n\n"
          "Команда: <code>бж 1000</code>\n"
          "Набери 21 очко или ближе к 21, чем дилер.\n"
          "Перебор (больше 21) — проигрыш.",
    "guarant": "🤝 <b>ГАРАНТ (сделки)</b>\n\n"
               "Команда: <code>гарант @user 5000</code>\n"
               "Покупатель платит, продавец подтверждает «Товар передан», покупатель — «Подтвердить».\n"
               "Если покупатель молчит 15 минут — бот напоминает.\n"
               "Отмена после передачи товара = блокировка сделки («Подозрительная активность»).",
    "duel": "⚔️ <b>ДУЭЛИ</b>\n\n"
            "Команда: <code>дуэль @user 1000</code>\n"
            "Второй игрок нажимает «Принять». Бот кидает кубики — победитель забирает x2.",
    "gift": "🎁 <b>ПОДАРКИ</b>\n\n"
            "Команда: <code>подарить @user 1000</code>\n"
            "Перевод токенов с красивым стикером.",
}


@user_router.message(F.text.in_([TEXTS["ru"]["btn_play"], TEXTS["en"]["btn_play"]]))
async def how_to_play(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)

    text = (
        "🎮 <b>КАК ИГРАТЬ В ИМПЕРИИ TOKENS</b>\n\n"
        "Все игры проходят <b>в чате</b>! Выбери раздел ниже:"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Кости", callback_data="gameinfo_dice"),
           InlineKeyboardButton(text="🎡 Рулетка", callback_data="gameinfo_roulette"))
    kb.row(InlineKeyboardButton(text="💣 Мины", callback_data="gameinfo_mines"),
           InlineKeyboardButton(text="🃏 БЖ", callback_data="gameinfo_bj"))
    kb.row(InlineKeyboardButton(text="🤝 Гарант", callback_data="gameinfo_guarant"),
           InlineKeyboardButton(text="⚔️ Дуэли", callback_data="gameinfo_duel"))
    kb.row(InlineKeyboardButton(text="🎁 Подарки", callback_data="gameinfo_gift"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))

    msg = await send_banner(message, "how_to_play", text, kb.as_markup(), sticker=STICKER_CROWN)
    await state.update_data(last_msgs=[msg.message_id])


@user_router.callback_query(F.data.startswith("gameinfo_"))
async def gameinfo_callback(callback: CallbackQuery):
    key = callback.data.split("_", 1)[1]
    text = GAMES_INFO.get(key, "ℹ️ Информация отсутствует.")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="gameinfo_back"))
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
        else:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


@user_router.callback_query(F.data == "gameinfo_back")
async def gameinfo_back(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    text = (
        "🎮 <b>КАК ИГРАТЬ В ИМПЕРИИ TOKENS</b>\n\n"
        "Все игры проходят <b>в чате</b>! Выбери раздел ниже:"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Кости", callback_data="gameinfo_dice"),
           InlineKeyboardButton(text="🎡 Рулетка", callback_data="gameinfo_roulette"))
    kb.row(InlineKeyboardButton(text="💣 Мины", callback_data="gameinfo_mines"),
           InlineKeyboardButton(text="🃏 БЖ", callback_data="gameinfo_bj"))
    kb.row(InlineKeyboardButton(text="🤝 Гарант", callback_data="gameinfo_guarant"),
           InlineKeyboardButton(text="⚔️ Дуэли", callback_data="gameinfo_duel"))
    kb.row(InlineKeyboardButton(text="🎁 Подарки", callback_data="gameinfo_gift"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
        else:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer()


# ==============================================================================
# 15. БОНУС
# ==============================================================================
@user_router.message(F.text.in_([TEXTS["ru"]["btn_bonus"], TEXTS["en"]["btn_bonus"]]))
async def daily_bonus(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    now = datetime.datetime.now()

    if user[5]:
        try:
            last_dt = datetime.datetime.fromisoformat(user[5])
            if now - last_dt < datetime.timedelta(hours=24):
                delta = datetime.timedelta(hours=24) - (now - last_dt)
                msg = await message.answer
                msg = await message.answer(
                    _(user, "bonus_wait", h=delta.seconds // 3600, m=(delta.seconds % 3600) // 60),
                    reply_markup=get_main_menu(user),
                )
                await state.update_data(last_msgs=[msg.message_id])
                return
        except ValueError:
            pass

    streak = user[10] or 1
    if user[11]:
        try:
            last_s = datetime.datetime.fromisoformat(user[11]).date()
            if (now.date() - last_s).days == 1:
                streak += 1
            elif (now.date() - last_s).days > 1:
                streak = 1
        except ValueError:
            pass

    prize = random.randint(2500, 25000)
    text = f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n💰 Ты получил: <b>+{format_money(prize)}</b>\n🔥 Стрик: <b>{streak}</b> дн."
    if streak >= 7:
        prize *= 2
        text = (
            f"🔥 <b>СТРИК 7 ДНЕЙ!</b> Бонус x2!\n\n"
            f"💰 Ты получил: <b>+{format_money(prize)}</b>\n🔥 Стрик: <b>{streak}</b> дн."
        )

    await asyncio.to_thread(update_balance, user[0], prize)
    await asyncio.to_thread(
        db_execute,
        "UPDATE users SET last_bonus=?, streak=?, last_streak_date=? WHERE user_id=?",
        (now.isoformat(), streak, now.date().isoformat(), user[0]),
    )

    kb = inline_back_menu(user)
    msg = await send_banner(message, "bonus", text, kb, sticker=STICKER_WHEEL)
    await state.update_data(last_msgs=[msg.message_id])


# ==============================================================================
# 16. ДОНАТ-ЦЕНТР
# ==============================================================================
def current_rate() -> int:
    """Курс меняется раз в 3 часа, 5000..10000."""
    slot = int(datetime.datetime.now().timestamp()) // (3 * 3600)
    return random.Random(slot).randint(5000, 10000)


@user_router.message(F.text.in_([TEXTS["ru"]["btn_donate"], TEXTS["en"]["btn_donate"]]))
async def donate_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rate = current_rate()

    text = (
        "💎 <b>ДОНАТ-ЦЕНТР</b>\n\n"
        f"🔥 Курс дня: <b>1 ⭐ = {rate:,} Tokens</b>\n\n"
        "Выбери действие:"
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Купить Токены", callback_data="donate_tokens"))
    kb.row(InlineKeyboardButton(text="👑 Купить VIP", callback_data="donate_vip"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))

    msg = await send_banner(message, "donate", text, kb.as_markup(), sticker=STICKER_FIREWORK)
    await state.update_data(last_msgs=[msg.message_id])


@user_router.callback_query(F.data == "donate_tokens")
async def donate_tokens(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    rate = current_rate()
    text = (
        "⭐ <b>ПОКУПКА ТОКЕНОВ</b>\n\n"
        f"Курс: <b>1 ⭐ = {rate:,} Tokens</b>\n\n"
        "Выбери пакет:"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"⭐ 15 Stars (+{rate*15:,})", callback_data="buy_stars_15"))
    kb.row(InlineKeyboardButton(text=f"⭐ 50 Stars (+{rate*50:,})", callback_data="buy_stars_50"))
    kb.row(InlineKeyboardButton(text="✍️ Своя сумма", callback_data="buy_stars_custom"))
    kb.row(InlineKeyboardButton(text="🎟 Секретный промокод (10 ⭐)", callback_data="buy_secret_promo"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_donate_back"))
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


@user_router.callback_query(F.data == "nav_donate_back")
async def nav_donate_back(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    rate = current_rate()
    text = (
        "💎 <b>ДОНАТ-ЦЕНТР</b>\n\n"
        f"🔥 Курс дня: <b>1 ⭐ = {rate:,} Tokens</b>\n\n"
        "Выбери действие:"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Купить Токены", callback_data="donate_tokens"))
    kb.row(InlineKeyboardButton(text="👑 Купить VIP", callback_data="donate_vip"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


@user_router.callback_query(F.data == "donate_vip")
async def donate_vip(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    text = (
        "👑 <b>VIP-СТАТУС</b>\n\n"
        "Что даёт VIP:\n"
        "• 💰 Авто-бонус <b>30 000 Tokens</b> каждый день в 12:00\n"
        "• 🎡 Золотая рулетка <b>x3</b>\n"
        "• 🚫 Без комиссии при переводах\n"
        "• 👑 VIP-значок в чате\n\n"
        "Выбери срок:"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👑 VIP 1 день (5 ⭐)", callback_data="buy_vip_5_1"))
    kb.row(InlineKeyboardButton(text="👑 VIP 7 дней (30 ⭐)", callback_data="buy_vip_30_7"))
    kb.row(InlineKeyboardButton(text="👑 VIP 30 дней (100 ⭐)", callback_data="buy_vip_100_30"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_donate_back"))
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


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
    user = await asyncio.to_thread(get_user, message.from_user.id)
    await message.answer_invoice(
        title=f"Звезды ({amount})",
        description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=amount)],
        start_parameter="buy",
    )
    await state.clear()


@user_router.callback_query(F.data == "buy_secret_promo")
async def buy_secret_promo(callback: CallbackQuery):
    await callback.message.answer_invoice(
        title="Секретный промокод",
        description="Промокод с бонусом",
        payload="secret_promo",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Secret promo", amount=10)],
        start_parameter="buy",
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    if callback.data == "buy_stars_custom":
        return
    try:
        amount = int(callback.data.split("_")[2])
    except Exception:
        return await callback.answer()
    await callback.message.answer_invoice(
        title="Звезды",
        description=f"Обмен {amount} Stars",
        payload=f"stars_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=amount)],
        start_parameter="buy",
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("buy_vip_"))
async def process_buy_vip(callback: CallbackQuery):
    try:
        _, _, price, days = callback.data.split("_")
        price, days = int(price), int(days)
    except Exception:
        return await callback.answer()
    await callback.message.answer_invoice(
        title=f"VIP {days} дн.",
        description="Активация VIP",
        payload=f"vip_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="VIP", amount=price)],
        start_parameter="buy",
    )
    await callback.answer()


@user_router.message(F.successful_payment)
async def success_payment(message: Message, state: FSMContext):
    payment = message.successful_payment
    user = await asyncio.to_thread(get_user, message.from_user.id)
    try:
        await message.answer_sticker(STICKER_FIREWORK)
    except Exception:
        pass

    if payment.invoice_payload.startswith("vip_"):
        days = int(payment.invoice_payload.split("_")[1])
        now = datetime.datetime.now()
        base = now
        if user[9]:
            try:
                cur = datetime.datetime.fromisoformat(user[9])
                if cur > now:
                    base = cur
            except Exception:
                pass
        vip_until = (base + datetime.timedelta(days=days)).isoformat()
        await asyncio.to_thread(
            db_execute,
            "UPDATE users SET role='vip', vip_until=? WHERE user_id=?",
            (vip_until, user[0]),
        )
        cache_invalidate(user[0])
        msg = await message.answer(
            f"✅ <b>VIP АКТИВИРОВАН НА {days} ДН.!</b>", reply_markup=get_main_menu(user)
        )

    elif payment.invoice_payload.startswith("stars_"):
        amount = int(payment.invoice_payload.split("_")[1])
        rate = current_rate()
        total = amount * rate
        await asyncio.to_thread(update_balance, user[0], total)
        await asyncio.to_thread(
            db_execute,
            "UPDATE users SET total_donated = total_donated + ? WHERE user_id = ?",
            (total, user[0]),
        )
        msg = await message.answer(
            f"✅ <b>ОПЛАТА УСПЕШНА!</b>\nЗачислено: <b>{format_money(total)}</b>",
            reply_markup=get_main_menu(user),
        )

    elif payment.invoice_payload == "secret_promo":
        code = f"SECRET{random.randint(1000, 9999)}"
        reward = 50000
        await asyncio.to_thread(
            db_execute,
            "INSERT INTO promos (code, reward, limit_count) VALUES (?, ?, 1) ON CONFLICT DO NOTHING",
            (code, reward),
        )
        msg = await message.answer(
            f"🎟 <b>Твой секретный промокод:</b>\n<code>{code}</code>\n\n"
            f"Активируй: <code>промо {code}</code>\nНаграда: {format_money(reward)}",
            reply_markup=get_main_menu(user),
        )
    else:
        msg = await message.answer("✅ Оплата получена.")
    await state.update_data(last_msgs=[msg.message_id])


# ==============================================================================
# 17. ПРОФИЛЬ
# ==============================================================================
@user_router.message(F.text.in_([TEXTS["ru"]["btn_profile"], TEXTS["en"]["btn_profile"]]))
async def profile(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    vip = is_vip(user)
    vip_text = "👑 VIP" if vip else "❌ Нет"

    text = _(
        user, "profile",
        name=message.from_user.first_name,
        bal=format_money(user[3]),
        vip=vip_text,
        id=user[0],
    )

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📋 Скопировать ID", callback_data="profile_copy_id"))
    kb.row(InlineKeyboardButton(text="📜 История игр", callback_data="profile_history"))
    kb.row(InlineKeyboardButton(text="🌐 Язык", callback_data="profile_lang"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))

    sticker = random.choice(VIP_STICKERS) if vip else STICKER_MONEY
    msg = await send_banner(message, "profile", text, kb.as_markup(), sticker=sticker)
    await state.update_data(last_msgs=[msg.message_id])


@user_router.callback_query(F.data == "profile_copy_id")
async def profile_copy_id(callback: CallbackQuery):
    await callback.message.answer(f"<code>{callback.from_user.id}</code>")
    await callback.answer("ID скопирован!")


@user_router.callback_query(F.data == "profile_history")
async def profile_history(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    rows = await asyncio.to_thread(
        db_execute,
        "SELECT game, bet, win, date FROM games_log WHERE user_id = ? ORDER BY id DESC LIMIT 10",
        (user[0],), False, True,
    )
    if not rows:
        await callback.message.answer("📜 История пуста. Сыграй в чате!")
        return await callback.answer()
    lines = ["📜 <b>Последние 10 игр:</b>\n"]
    for game, bet, win, date in rows:
        lines.append(f"{'🟢' if win > 0 else '🔴'} <b>{game}</b> · ставка {format_money(bet)} · выигрыш {format_money(win)}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@user_router.callback_query(F.data == "profile_lang")
async def profile_lang(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
           InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"))
    await callback.message.answer("🌐 <b>Выбери язык:</b>", reply_markup=kb.as_markup())
    await callback.answer()


@user_router.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    if lang not in TEXTS:
        return await callback.answer("❌")
    await asyncio.to_thread(
        db_execute, "UPDATE users SET lang = ? WHERE user_id = ?", (lang, callback.from_user.id)
    )
    cache_invalidate(callback.from_user.id)
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await callback.message.answer(f"✅ Язык изменён на {lang.upper()}", reply_markup=get_main_menu(user))
    await callback.answer()


# ==============================================================================
# 18. ТОП (3 вида)
# ==============================================================================
@user_router.message(F.text.in_([TEXTS["ru"]["btn_top"], TEXTS["en"]["btn_top"]]))
async def top_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)

    text = "🏆 <b>ТОПЫ ИГРОКОВ</b>\n\nВыбери категорию:"
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"))
    kb.row(InlineKeyboardButton(text="💎 По донатам", callback_data="top_donated"))
    kb.row(InlineKeyboardButton(text="🏆 По выигрышам", callback_data="top_wins"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))

    msg = await send_banner(message, "top", text, kb.as_markup(), sticker=STICKER_CROWN)
    await state.update_data(last_msgs=[msg.message_id])


def _format_top_rows(rows) -> str:
    if not rows:
        return "Пусто."
    lines = []
    for i, row in enumerate(rows, 1):
        un = row[0] or "—"
        val = row[1] or 0
        icon = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{icon} @{un} — {format_money(val)}")
    return "\n".join(lines)


@user_router.callback_query(F.data.startswith("top_"))
async def top_callback(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    action = callback.data.split("_", 1)[1]
    if action == "balance":
        rows = await asyncio.to_thread(
            db_execute, "SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10", (), False, True
        )
        text = _(user, "top_balance", lines=_format_top_rows(rows))
    elif action == "donated":
        rows = await asyncio.to_thread(
            db_execute, "SELECT username, total_donated FROM users ORDER BY total_donated DESC LIMIT 10", (), False, True
        )
        text = _(user, "top_donated", lines=_format_top_rows(rows))
    elif action == "wins":
        rows = await asyncio.to_thread(
            db_execute, "SELECT username, total_win FROM users ORDER BY total_win DESC LIMIT 10", (), False, True
        )
        text = _(user, "top_wins", lines=_format_top_rows(rows))
    else:
        return await callback.answer()

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"))
    kb.row(InlineKeyboardButton(text="💎 По донатам", callback_data="top_donated"))
    kb.row(InlineKeyboardButton(text="🏆 По выигрышам", callback_data="top_wins"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup())
        else:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


# ==============================================================================
# 19. РЕФЕРАЛКА
# ==============================================================================
@user_router.message(F.text.in_([TEXTS["ru"]["btn_ref"], TEXTS["en"]["btn_ref"]]))
async def refka(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user[0]}"
    text = _(user, "ref_text", link=link)
    msg = await send_banner(message, "ref", text, inline_back_menu(user), sticker=STICKER_GIFT)
    await state.update_data(last_msgs=[msg.message_id])


# ==============================================================================
# 20. ПРОМОКОДЫ
# ==============================================================================
@user_router.message(F.text.regexp(r"(?i)^промо\s+(.+)$"))
async def use_promo(message: Message):
    code = message.text.split()[1].upper()
    promo = await asyncio.to_thread(
        db_execute, "SELECT reward, limit_count, used_count FROM promos WHERE code = ?", (code,), True
    )
    if not promo:
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return await message.answer("❌ Неверный промокод.")
    if promo[2] >= promo[1]:
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return await message.answer("❌ Лимит активаций исчерпан.")

    used = await asyncio.to_thread(
        db_execute, "SELECT id FROM promo_uses WHERE code = ? AND user_id = ?", (code, message.from_user.id), True
    )
    if used:
        try:
            await message.answer_sticker(STICKER_CROSS)
        except Exception:
            pass
        return await message.answer("❌ Ты уже использовал этот промокод.")

    await asyncio.to_thread(update_balance, message.from_user.id, promo[0])
    await asyncio.to_thread(db_execute, "UPDATE promos SET used_count = used_count + 1 WHERE code = ?", (code,))
    await asyncio.to_thread(db_execute, "INSERT INTO promo_uses (code, user_id) VALUES (?, ?)", (code, message.from_user.id))
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    await message.answer(f"✅ Промокод активирован! Ты получил {format_money(promo[0])}!")


# ==============================================================================
# 21. КЛАНЫ (упрощённый блок)
# ==============================================================================
@user_router.message(F.text == "🛡 Клан")
async def clan_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        msg = await message.answer("🛡 <b>КЛАНЫ</b>\n\nТы пока не в клане.", reply_markup=get_clan_menu_kb(False, False, user))
        await state.update_data(last_msgs=[msg.message_id])
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT name, owner_id, treasury, join_fee, level FROM clans WHERE id = ?", (user[6],), True
    )
    if not clan:
        await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
        cache_invalidate(user[0])
        msg = await message.answer("Клан не найден.", reply_markup=get_clan_menu_kb(False, False, user))
        await state.update_data(last_msgs=[msg.message_id])
        return
    is_owner = clan[1] == user[0]
    try:
        await message.answer_sticker(STICKER_CROWN)
    except Exception:
        pass
    msg = await message.answer(
        f"🛡 <b>Клан: {clan[0]}</b>\n👑 Владелец: {'Ты' if is_owner else clan[1]}\n💰 {format_money(clan[2])}",
        reply_markup=get_clan_menu_kb(True, is_owner, user),
    )
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "➕ Создать")
async def clan_create_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < 100_000:
        return await message.answer("❌ Нужно 100 000 Tokens.")
    if user[6]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана:", reply_markup=ReplyKeyboardRemove())
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
        cache_invalidate(user[0])
        try:
            await message.answer_sticker(STICKER_CHECK)
        except Exception:
            pass
        msg = await message.answer(f"✅ Клан <b>{name}</b> создан!", reply_markup=get_main_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
    else:
        await message.answer("❌ Ошибка создания.")
    await state.clear()


@user_router.message(F.text == "🏆 Топ")
async def clan_top(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    rows = await asyncio.to_thread(
        db_execute, "SELECT name, treasury, level FROM clans ORDER BY treasury DESC LIMIT 10", (), False, True
    )
    if not rows:
        msg = await message.answer("🏆 Пока нет кланов.", reply_markup=get_main_menu(user))
        await state.update_data(last_msgs=[msg.message_id])
        return
    lines = ["🏆 <b>ТОП-10 КЛАНОВ</b>\n"]
    for i, (name, treasury, level) in enumerate(rows, 1):
        lines.append(f"{i}. <b>{name}</b> · ур.{level} · {format_money(treasury)}")
    msg = await message.answer("\n".join(lines), reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "💰 Внести")
async def clan_deposit_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return await message.answer("❌ Ты не в клане.")
    await message.answer("💰 Введи сумму для внесения:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_deposit)


@user_router.message(ClanStates.waiting_deposit)
async def clan_deposit_finish(message: Message, state: FSMContext):
    amount = parse_amt(message.text)
    if not amount:
        await state.clear()
        return await message.answer("❌ Введи положительное число.")
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        await state.clear()
        return await message.answer("❌ Мало средств.")
    await asyncio.to_thread(update_balance, user[0], -amount)
    await asyncio.to_thread(
        db_execute, "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (amount, user[6])
    )
    await asyncio.to_thread(
        db_execute, "UPDATE users SET clan_donated = clan_donated + ? WHERE user_id = ?", (amount, user[0])
    )
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"✅ Внесено в казну: <b>{format_money(amount)}</b>", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()


@user_router.message(F.text == "📜 Мой клан")
async def clan_my(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return await message.answer("❌ Ты не в клане.")
    clan = await asyncio.to_thread(
        db_execute, "SELECT name, treasury, level, owner_id FROM clans WHERE id = ?", (user[6],), True
    )
    members = await asyncio.to_thread(
        db_execute, "SELECT COUNT(*) FROM users WHERE clan_id = ?", (user[6],), True
    )
    if not clan:
        return await message.answer("❌ Клан не найден.")
    name, treasury, level, owner_id = clan
    owner = await asyncio.to_thread(
        db_execute, "SELECT username FROM users WHERE user_id = ?", (owner_id,), True
    )
    msg = await message.answer(
        f"📜 <b>{name}</b>\n👑 Владелец: @{owner[0] if owner else '—'}\n📈 Уровень: {level}\n"
        f"👥 Участников: {members[0] if members else 0}\n💰 Казна: {format_money(treasury)}",
        reply_markup=get_main_menu(user),
    )
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "🛡 Щит")
async def clan_shield(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return
    if user[3] < 250_000:
        return await message.answer("❌ Нужно 250 000 Tokens.")
    await asyncio.to_thread(update_balance, user[0], -250_000)
    await asyncio.to_thread(
        db_execute,
        "UPDATE clans SET shield_until = ? WHERE id = ?",
        ((datetime.datetime.now() + datetime.timedelta(days=7)).isoformat(), user[6]),
    )
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer("🛡 Щит клана активирован на 7 дней!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "📈 Прокачать")
async def clan_upgrade(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id, level, treasury FROM clans WHERE id = ?", (user[6],), True
    )
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может качать клан.")
    if clan[1] >= 5:
        return await message.answer("✅ Максимальный уровень.")
    cost = 250_000 * clan[1]
    if user[3] < cost:
        return await message.answer(f"❌ Нужно {format_money(cost)} на балансе.")
    await asyncio.to_thread(update_balance, user[0], -cost)
    await asyncio.to_thread(db_execute, "UPDATE clans SET level = level + 1 WHERE id = ?", (user[6],))
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"📈 Клан прокачан до уровня {clan[1] + 1}!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "💵 Налог")
async def clan_tax(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id, treasury FROM clans WHERE id = ?", (user[6],), True
    )
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может собрать налог.")
    tax = int(clan[1] * 0.10)
    if tax <= 0:
        return await message.answer("❌ Казна пуста.")
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury - ? WHERE id = ?", (tax, user[6]))
    await asyncio.to_thread(update_balance, user[0], tax)
    try:
        await message.answer_sticker(STICKER_MONEY)
    except Exception:
        pass
    msg = await message.answer(f"💵 Собрано 10% налога: <b>{format_money(tax)}</b>", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


@user_router.message(F.text == "🥾 Кик")
async def clan_kick_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[6],), True
    )
    if not clan or clan[0] != user[0]:
        return await message.answer("❌ Только владелец может кикать.")
    await message.answer("🥾 Отправь @username или ID игрока:", reply_markup=ReplyKeyboardRemove())
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
        return await message.answer("❌ Игрок не найден.", reply_markup=get_main_menu(user))
    target = await asyncio.to_thread(get_user, target_id)
    if not target or target[6] != user[6]:
        await state.clear()
        return await message.answer("❌ Игрок не в твоём клане.", reply_markup=get_main_menu(user))
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (target_id,))
    cache_invalidate(target_id)
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer("✅ Игрок исключён из клана.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()


@user_router.message(F.text == "🤝 Вступить")
async def clan_join_start(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[6]:
        return await message.answer("❌ Ты уже в клане.")
    await message.answer("✍️ Введи название клана:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ClanStates.waiting_join)


@user_router.message(ClanStates.waiting_join)
async def clan_join_finish(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    clan = await asyncio.to_thread(
        db_execute, "SELECT id, join_fee FROM clans WHERE name = ?", (name,), True
    )
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not clan:
        await state.clear()
        return await message.answer("❌ Клан не найден.", reply_markup=get_main_menu(user))
    cid, fee = clan
    if user[3] < fee:
        await state.clear()
        return await message.answer(f"❌ Нужно {format_money(fee)} на вход.", reply_markup=get_main_menu(user))
    await asyncio.to_thread(update_balance, user[0], -fee)
    await asyncio.to_thread(db_execute, "UPDATE clans SET treasury = treasury + ? WHERE id = ?", (fee, cid))
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = ? WHERE user_id = ?", (cid, user[0]))
    cache_invalidate(user[0])
    try:
        await message.answer_sticker(STICKER_CHECK)
    except Exception:
        pass
    msg = await message.answer(f"✅ Ты вступил в клан <b>{name}</b>!", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()


@user_router.message(F.text == "🚪 Выйти")
async def clan_leave(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if not user[6]:
        return await message.answer("❌ Ты не в клане.")
    clan = await asyncio.to_thread(
        db_execute, "SELECT owner_id FROM clans WHERE id = ?", (user[6],), True
    )
    if clan and clan[0] == user[0]:
        return await message.answer("👑 Владелец не может выйти.")
    await asyncio.to_thread(db_execute, "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user[0],))
    cache_invalidate(user[0])
    msg = await message.answer("✅ Ты вышел из клана.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])


# ==============================================================================
# 22. ПОДДЕРЖКА
# ==============================================================================
@user_router.message(F.text.in_(["🆘 Поддержка", "🆘 Support"]))
async def support_menu(message: Message, state: FSMContext):
    await delete_old_messages(bot, state, message.chat.id)
    user = await asyncio.to_thread(get_user, message.from_user.id)
    try:
        await message.answer_sticker(STICKER_SUPPORT)
    except Exception:
        pass
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✍️ Написать Админу", callback_data="sup_admin"))
    kb.row(InlineKeyboardButton(text="⚠️ Сообщить об ошибке", callback_data="sup_bug"))
    kb.row(InlineKeyboardButton(text=_(user, "btn_back"), callback_data="nav_menu"))
    msg = await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>", reply_markup=kb.as_markup())
    await state.update_data(last_msgs=[msg.message_id])


@user_router.callback_query(F.data == "sup_admin")
async def sup_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Опиши проблему одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_ticket)
    await callback.answer()


@user_router.callback_query(F.data == "sup_bug")
async def sup_bug(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⚠️ Опиши ошибку одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_bug)
    await callback.answer()


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
            ADMIN_ID, f"🎫 <b>ТИКЕТ</b>\nОт: @{message.from_user.username or message.from_user.id}\n{message.text}"
        )
    except Exception:
        pass
    try:
        await message.answer_sticker(STICKER_TICKET)
    except Exception:
        pass
    msg = await message.answer("✅ Тикет отправлен.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()


@user_router.message(SupportStates.waiting_bug)
async def process_bug(message: Message, state: FSMContext):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    try:
        await bot.send_message(
            ADMIN_ID, f"⚠️ <b>БАГ-РЕПОРТ</b>\nОт: @{message.from_user.username or message.from_user.id}\n{message.text}"
        )
    except Exception:
        pass
    try:
        await message.answer_sticker(STICKER_TICKET)
    except Exception:
        pass
    msg = await message.answer("✅ Спасибо! Баг-репорт отправлен.", reply_markup=get_main_menu(user))
    await state.update_data(last_msgs=[msg.message_id])
    await state.clear()


# ==============================================================================
# 23. ГРУППА: БАЛАНС, ПЕРЕВОД, ГАРАНТ, ПОДАРКИ, ДУЭЛИ
# ==============================================================================
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    user = await asyncio.to_thread(get_user, message.from_user.id)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    vip = is_vip(user)
    if vip:
        name_display = f"👑 <b>{name}</b>"
        sticker = random.choice(VIP_STICKERS)
    else:
        name_display = name
        sticker = STICKER_MONEY

    text = _(user, "balance", name=name_display, bal=format_money(user[3]))
    asyncio.create_task(_safe_sticker(message, sticker))
    msg = await message.reply(text)
    asyncio.create_task(auto_delete(msg, 60))


@group_router.message(F.text.regexp(r"(?i)^перевод\s+(.+)$"))
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
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная сумма!")

    sender = await asyncio.to_thread(get_user, message.from_user.id)
    if sender[3] < amount:
        return await message.reply("❌ Мало средств!")
    await asyncio.to_thread(update_balance, sender[0], -amount)
    await asyncio.to_thread(get_user, target_id)
    await asyncio.to_thread(update_balance, target_id, amount)

    asyncio.create_task(_safe_sticker(message, STICKER_TRANSFER))
    msg = await message.reply(
        f"✅ <b>Перевод выполнен!</b>\n\n"
        f"👤 От: {message.from_user.first_name}\n"
        f"👤 Кому: {message.reply_to_message.from_user.first_name}\n"
        f"💰 Сумма: <b>{format_money(amount)}</b>"
    )
    asyncio.create_task(auto_delete(msg, 60))


# ---------- ПОДАРКИ ----------
@group_router.message(F.text.regexp(r"(?i)^подарить\s+@?(\w+)\s+(.+)$"))
async def cmd_gift(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    try:
        m = re.match(r"(?i)^подарить\s+@?(\w+)\s+(.+)$", message.text)
        target_username, amount_raw = m.group(1), m.group(2)
        amount = parse_amt(amount_raw)
        if not amount:
            return await message.reply("❌ Неверная сумма!")
        found = await asyncio.to_thread(
            db_execute, "SELECT user_id FROM users WHERE username = ?", (target_username,), True
        )
        if not found:
            return await message.reply("❌ Получатель не найден.")
        target_id = found[0]
        if target_id == message.from_user.id:
            return await message.reply("❌ Себе нельзя!")
        sender = await asyncio.to_thread(get_user, message.from_user.id)
        if sender[3] < amount:
            return await message.reply("❌ Мало средств.")
        await asyncio.to_thread(update_balance, sender[0], -amount)
        await asyncio.to_thread(get_user, target_id)
        await asyncio.to_thread(update_balance, target_id, amount)
        asyncio.create_task(_safe_sticker(message, STICKER_GIFT))
        msg = await message.reply(
            f"🎁 <b>ПОДАРОК!</b>\n\n"
            f"👤 {message.from_user.first_name} → @{target_username}\n"
            f"💰 <b>{format_money(amount)}</b>"
        )
        asyncio.create_task(auto_delete(msg, 120))
    except Exception as e:
        logger.error(f"gift error: {e}")


# ---------- ГАРАНТ ----------
active_deals: Dict[str, dict] = {}


@group_router.message(F.text.regexp(r"(?i)^гарант\s+@?(\w+)\s+(.+)$"))
async def cmd_guarant(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    try:
        m = re.match(r"(?i)^гарант\s+@?(\w+)\s+(.+)$", message.text)
        seller_username, amount_str = m.group(1), m.group(2)
        buyer = await asyncio.to_thread(get_user, message.from_user.id)
        seller = await asyncio.to_thread(
            db_execute, "SELECT user_id FROM users WHERE username = ?", (seller_username,), True
        )
        if not seller:
            return await message.reply("❌ Продавец не найден.")
        if seller[0] == buyer[0]:
            return await message.reply("❌ Нельзя делать сделку с собой.")
        amount = parse_amt(amount_str)
        if not amount:
            return await message.reply("❌ Неверная сумма (макс 10кк).")
        if buyer[3] < amount:
            return await message.reply("❌ Мало средств для сделки.")
        await asyncio.to_thread(update_balance, buyer[0], -amount)

        deal_id = str(int(datetime.datetime.now().timestamp()))
        active_deals[deal_id] = {
            "buyer": buyer[0],
            "seller": seller[0],
            "amount": amount,
            "status": "waiting",
            "chat": message.chat.id,
            "seller_username": seller_username,
        }

        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"deal_{deal_id}_ok"))
        kb.row(InlineKeyboardButton(text="📦 Товар передан", callback_data=f"deal_{deal_id}_item"))
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"deal_{deal_id}_cancel"))

        asyncio.create_task(_safe_sticker(message, STICKER_TRANSFER))
        text = (
            f"🤝 <b>СДЕЛКА СОЗДАНА</b>\n\n"
            f"👤 Покупатель: {message.from_user.first_name} (оплатил)\n"
            f"👤 Продавец: @{seller_username}\n"
            f"💰 Сумма: {format_money(amount)} (заморожена)\n\n"
            f"📦 Продавец, передайте товар и нажмите «Товар передан».\n"
            f"✅ Покупатель, нажмите «Подтвердить», когда получите товар."
        )
        msg = await message.reply(text, reply_markup=kb.as_markup())
        asyncio.create_task(auto_delete(msg, 600))
    except Exception as e:
        logger.error(f"cmd_guarant: {e}")


async def _deal_timeout_watcher(deal_id: str):
    """Если продавец передал товар, а покупатель молчит 15 минут — напоминаем."""
    await asyncio.sleep(15 * 60)
    deal = active_deals.get(deal_id)
    if not deal:
        return
    if deal["status"] == "item_transferred":
        try:
            await bot.send_message(
                deal["buyer"],
                f"⏰ <b>Напоминание по сделке</b>\n"
                f"Продавец @{deal['seller_username']} передал товар.\n"
                f"Нажми «Подтвердить» в чате, если всё получил.",
            )
        except Exception:
            pass


@group_router.callback_query(F.data.startswith("deal_"))
async def process_deal(callback: CallbackQuery):
    try:
        _, deal_id, action = callback.data.split("_")
        deal = active_deals.get(deal_id)
        if not deal:
            return await callback.answer("Сделка не найдена или уже завершена.", show_alert=True)
        if callback.from_user.id not in (deal["buyer"], deal["seller"]):
            return await callback.answer("Не твоя сделка.", show_alert=True)

        if action == "cancel":
            # если продавец уже передал товар — блокируем отмену
            if deal["status"] == "item_transferred":
                try:
                    await callback.message.edit_text(
                        "⚠️ <b>Подозрительная активность</b>\n\n"
                        "Отмена невозможна: продавец уже передал товар.\n"
                        "Сделка передана администрации."
                    )
                except Exception:
                    pass
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"⚠️ Подозрительная отмена сделки\n"
                        f"Buyer: {deal['buyer']}  Seller: {deal['seller']}\n"
                        f"Сумма: {deal['amount']}",
                    )
                except Exception:
                    pass
                return await callback.answer("Отмена заблокирована.", show_alert=True)

            await asyncio.to_thread(update_balance, deal["buyer"], deal["amount"])
            try:
                await callback.message.edit_text(
                    f"❌ <b>СДЕЛКА ОТМЕНЕНА</b>\nСредства ({format_money(deal['amount'])}) возвращены покупателю."
                )
            except Exception:
                pass
            del active_deals[deal_id]
            return await callback.answer("Сделка отменена")

        if action == "item":
            if callback.from_user.id != deal["seller"]:
                return await callback.answer("Только продавец может подтвердить передачу товара!", show_alert=True)
            deal["status"] = "item_transferred"
            try:
                await callback.message.edit_text(
                    "📦 <b>ТОВАР ПЕРЕДАН</b>\nПокупатель, подтвердите получение кнопкой ниже.",
                    reply_markup=callback.message.reply_markup,
                )
            except Exception:
                pass
            asyncio.create_task(_deal_timeout_watcher(deal_id))
            return await callback.answer("Товар передан. Ждём покупателя.")

        if action == "ok":
            if callback.from_user.id != deal["buyer"]:
                return await callback.answer("Только покупатель может подтвердить сделку!", show_alert=True)
            if deal["status"] != "item_transferred":
                return await callback.answer("❌ Продавец ещё не передал товар!", show_alert=True)
            await asyncio.to_thread(update_balance, deal["seller"], deal["amount"])
            try:
                await callback.message.edit_text(
                    f"✅ <b>СДЕЛКА ЗАВЕРШЕНА!</b>\n"
                    f"Средства ({format_money(deal['amount'])}) переведены продавцу."
                )
            except Exception:
                pass
            del active_deals[deal_id]
            return await callback.answer("Сделка завершена!")
    except Exception as e:
        logger.error(f"process_deal: {e}")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)


# ---------- ДУЭЛИ ----------
active_duels: Dict[str, dict] = {}


@group_router.message(F.text.regexp(r"(?i)^дуэль\s+@?(\w+)\s+(.+)$"))
async def cmd_duel(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    try:
        m = re.match(r"(?i)^дуэль\s+@?(\w+)\s+(.+)$", message.text)
        target_username, amount_raw = m.group(1), m.group(2)
        amount = parse_amt(amount_raw)
        if not amount:
            return await message.reply("❌ Неверная сумма!")
        target = await asyncio.to_thread(
            db_execute, "SELECT user_id FROM users WHERE username = ?", (target_username,), True
        )
        if not target:
            return await message.reply("❌ Игрок не найден.")
        if target[0] == message.from_user.id:
            return await message.reply("❌ С собой нельзя.")
        challenger = await asyncio.to_thread(get_user, message.from_user.id)
        if challenger[3] < amount:
            return await message.reply("❌ Мало средств.")

        duel_id = str(int(datetime.datetime.now().timestamp()))
        active_duels[duel_id] = {
            "challenger": challenger[0],
            "challenger_name": message.from_user.first_name,
            "target": target[0],
            "amount": amount,
            "chat": message.chat.id,
            "status": "pending",
        }
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="⚔️ Принять", callback_data=f"duel_{duel_id}_accept"))
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"duel_{duel_id}_decline"))
        asyncio.create_task(_safe_sticker(message, STICKER_FIRE))
        msg = await message.reply(
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ</b>\n\n"
            f"{message.from_user.first_name} → @{target_username}\n"
            f"💰 Ставка: {format_money(amount)}\n\n"
            f"@{target_username}, принимаешь?",
            reply_markup=kb.as_markup(),
        )
        asyncio.create_task(auto_delete(msg, 300))
    except Exception as e:
        logger.error(f"cmd_duel: {e}")


@group_router.callback_query(F.data.startswith("duel_"))
async def process_duel(callback: CallbackQuery):
    try:
        _, duel_id, action = callback.data.split("_")
        duel = active_duels.get(duel_id)
        if not duel:
            return await callback.answer("Дуэль уже завершена.", show_alert=True)
        if action == "decline":
            del active_duels[duel_id]
            try:
                await callback.message.edit_text("❌ Дуэль отклонена.")
            except Exception:
                pass
            return await callback.answer("Отклонено")
        if action != "accept":
            return await callback.answer()
        if callback.from_user.id != duel["target"]:
            return await callback.answer("Только приглашённый может принять!", show_alert=True)
        c = await asyncio.to_thread(get_user, duel["challenger"])
        t = await asyncio.to_thread(get_user, duel["target"])
        amount = duel["amount"]
        if c[3] < amount:
            del active_duels[duel_id]
            return await callback.answer("У вызывающего нет средств.", show_alert=True)
        if t[3] < amount:
            return await callback.answer("У тебя нет средств.", show_alert=True)
        await asyncio.to_thread(update_balance, c[0], -amount)
        await asyncio.to_thread(update_balance, t[0], -amount)

        # кидаем кубики
        dice1 = await callback.message.answer_dice(emoji="🎲")
        dice2 = await callback.message.answer_dice(emoji="🎲")
        await asyncio.sleep(4)

        v1, v2 = dice1.dice.value, dice2.dice.value
        winner_name = None
        if v1 == v2:
            # возврат
            await asyncio.to_thread(update_balance, c[0], amount)
            await asyncio.to_thread(update_balance, t[0], amount)
            text = f"🤝 <b>НИЧЬЯ!</b>\n{dice1.dice.value} : {dice2.dice.value}\nСтавки возвращены."
        else:
            if v1 > v2:
                winner_id, winner_name = c[0], duel["challenger_name"]
            else:
                winner_id, winner_name = t[0], f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
            prize = amount * 2
            await asyncio.to_thread(update_balance, winner_id, prize)
            await asyncio.to_thread(log_game, winner_id, "дуэль", amount, prize)
            await asyncio.to_thread(log_game, c[0] if winner_id != c[0] else t[0], "дуэль", amount, 0)
            text = f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n{dice1.dice.value} : {dice2.dice.value}\n\n🏆 Победитель: <b>{winner_name}</b>\n💰 Приз: {format_money(prize)}"

        try:
            await callback.message.edit_text(text)
        except Exception:
            pass
        del active_duels[duel_id]
        await callback.answer()
    except Exception as e:
        logger.error(f"process_duel: {e}")
        await callback.answer("Ошибка дуэли.", show_alert=True)


# ==============================================================================
# 24. ИГРЫ В ЧАТЕ
# ==============================================================================
active_roulette: Dict[int, dict] = {}
active_mines: Dict[str, dict] = {}
active_bj: Dict[str, dict] = {}

DICE_EMOJI = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳", "слот": "🎰"}
RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}


# ---- Игровой зал ----
@group_router.message(F.text.lower() == "игры")
async def games_hall_group(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice_кости"),
           InlineKeyboardButton(text="🎯 Дартс", callback_data="game_dice_дартс"))
    kb.row(InlineKeyboardButton(text="🏀 Баскет", callback_data="game_dice_баскет"),
           InlineKeyboardButton(text="⚽ Футбол", callback_data="game_dice_футбол"))
    kb.row(InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_dice_боулинг"),
           InlineKeyboardButton(text="🎰 Слот", callback_data="game_dice_слот"))
    kb.row(InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_roulette"),
           InlineKeyboardButton(text="💣 Мины", callback_data="game_mines"))
    kb.row(InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_bj"))
    msg = await message.reply("🎮 <b>ИГРОВОЙ ЗАЛ</b>\n\nВыбери игру:", reply_markup=kb.as_markup())
    asyncio.create_task(auto_delete(msg, 120))


@group_router.callback_query(F.data.startswith("game_dice_"))
async def game_dice_choice(callback: CallbackQuery, state: FSMContext):
    game = callback.data.split("_", 2)[2]
    await state.update_data(dice_game=game)
    msg = await callback.message.reply(
        f"🎲 Вы выбрали <b>{game}</b>.\nНапиши ставку (например: <code>1000</code> или <code>10к</code>):",
        reply_markup=ForceReply(selective=True),
    )
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_dice_bet)
    await callback.answer()


@group_router.callback_query(F.data == "game_roulette")
async def game_roulette_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply(
        "🎡 Напиши ставку (например: <code>к 1000</code> или <code>13 500</code>):",
        reply_markup=ForceReply(selective=True),
    )
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_roulette_bet)
    await callback.answer()


@group_router.callback_query(F.data == "game_mines")
async def game_mines_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply(
        "💣 Напиши сумму ставки (например: <code>1000</code>):",
        reply_markup=ForceReply(selective=True),
    )
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_mines_bet)
    await callback.answer()


@group_router.callback_query(F.data == "game_bj")
async def game_bj_choice(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.reply(
        "🃏 Напиши сумму ставки (например: <code>1000</code>):",
        reply_markup=ForceReply(selective=True),
    )
    asyncio.create_task(auto_delete(msg, 60))
    await state.set_state(GameStates.waiting_bj_bet)
    await callback.answer()


# ---- Обработка ставок из FSM ----
@group_router.message(GameStates.waiting_dice_bet)
async def process_dice_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text or "")
    if not amount:
        await state.clear()
        return await message.reply("❌ Неверная ставка (макс 10кк)!")
    data = await state.get_data()
    game = data.get("dice_game", "кости")
    await state.clear()
    await _run_dice(message, game, amount)


@group_router.message(GameStates.waiting_roulette_bet)
async def process_roulette_bet(message: Message, state: FSMContext):
    parsed = _parse_roulette_bet(message.text or "")
    if not parsed:
        await state.clear()
        return await message.reply("❌ Неверный формат. Пример: <code>к 1000</code>")
    kind, value, bet_raw, amount = parsed
    await state.clear()
    await _place_roulette_bet(message, kind, value, bet_raw, amount)


@group_router.message(GameStates.waiting_mines_bet)
async def process_mines_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text or "")
    if not amount:
        await state.clear()
        return await message.reply("❌ Неверная ставка.")
    await state.clear()
    await _start_mines(message, amount)


@group_router.message(GameStates.waiting_bj_bet)
async def process_bj_bet(message: Message, state: FSMContext):
    amount = parse_amt(message.text or "")
    if not amount:
        await state.clear()
        return await message.reply("❌ Неверная ставка.")
    await state.clear()
    await _start_bj(message, amount)


# ---- ТЕКСТОВЫЕ КОМАНДЫ ----
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг|слот)\s+(.+)$"))
async def play_dice_group_text(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    parts = message.text.lower().split()
    game, amount = parts[0], parse_amt(parts[1])
    if not amount:
        return await message.reply("❌ Неверная ставка (макс 10кк).")
    await _run_dice(message, game, amount)


async def _run_dice(message: Message, game: str, amount: int):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
    await asyncio.to_thread(update_balance, user[0], -amount)

    msg = await message.answer_dice(emoji=DICE_EMOJI.get(game, "🎲"))
    await asyncio.sleep(3.5)
    val = msg.dice.value
    if game in ("кости", "дартс", "футбол"):
        win = val >= 4
    elif game == "баскет":
        win = val >= 3
    elif game == "боулинг":
        win = val == 6
    else:  # слот
        win = val in (1, 22, 43, 64)

    if win:
        prize = amount * 2
        await asyncio.to_thread(update_balance, user[0], prize)
        await asyncio.to_thread(log_game, user[0], game, amount, prize)
        res = await message.reply(f"{random.choice(WIN_PHRASES)}\nВыпало: {val}\nВыигрыш: <b>{format_money(prize)}</b>")
    else:
        await asyncio.to_thread(log_game, user[0], game, amount, 0)
        res = await message.reply(f"{random.choice(LOSE_PHRASES)}\nВыпало: {val}")
    asyncio.create_task(auto_delete(msg, 60))
    asyncio.create
    asyncio.create_task(auto_delete(res, 60))


# ---- УМНЫЙ ПАРСЕР РУЛЕТКИ (любой порядок) ----
def _parse_roulette_value(raw: str):
    """Возвращает (kind, value) или None."""
    raw = raw.lower().strip()
    if raw in ("к", "красное", "red"):
        return ("color", "к")
    if raw in ("ч", "черное", "black"):
        return ("color", "ч")
    if raw in ("з", "зеро", "zero"):
        return ("color", "з")
    if raw in ("чет", "even"):
        return ("parity", "чет")
    if raw in ("нечет", "odd"):
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


def _parse_roulette_bet(text: str):
    """Принимает: 'к 1000', '1000 к', '10-23 500', '500 10-23', '13 100', '100 13'."""
    parts = text.lower().replace(" ", "").split()
    # сначала попробуем 2 токена: значение + сумма или сумма + значение
    if len(parts) != 2:
        return None
    a, b = parts[0], parts[1]
    # попытка: a = ставка, b = сумма
    v = _parse_roulette_value(a)
    amt = parse_amt(b)
    if v and amt:
        return v[0], v[1], a, amt
    # попытка: a = сумма, b = ставка
    amt = parse_amt(a)
    v = _parse_roulette_value(b)
    if v and amt:
        return v[0], v[1], b, amt
    return None


def _roulette_mult(kind: str) -> float:
    return {"number": 36, "range": 2.5, "color": 2, "parity": 2}[kind]


async def _place_roulette_bet(message: Message, kind, value, bet_raw: str, amount: int):
    chat_id = message.chat.id
    if chat_id not in active_roulette:
        active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting":
        return await message.reply("⏳ Идёт раунд, подожди.")
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
    await asyncio.to_thread(update_balance, user[0], -amount)
    active_roulette[chat_id]["bets"].append({
        "uid": user[0], "name": message.from_user.first_name,
        "kind": kind, "value": value, "raw": bet_raw, "amount": amount,
    })
    res = await message.reply(
        _(user, "bet_acc", name=message.from_user.first_name, bet=bet_raw.upper(), amt=format_money(amount))
    )
    asyncio.create_task(auto_delete(res, 60))


@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    state = active_roulette.get(chat_id)
    if not state or not state["bets"]:
        return
    state["status"] = "playing"

    gif_path = "assets/roulette.gif"
    if os.path.exists(gif_path):
        try:
            msg = await message.answer_animation(FSInputFile(gif_path), caption="🎡 <i>Рулетка крутится...</i>")
        except Exception:
            msg = await message.answer("🎡 <i>Рулетка крутится...</i>")
    else:
        msg = await message.answer("🎡 <i>Рулетка крутится...</i>")

    await asyncio.sleep(3)
    result = random.randint(0, 36)
    color = "з" if result == 0 else "к" if result in RED_NUMS else "ч"
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
            prize = int(b["amount"] * _roulette_mult(k))
            await asyncio.to_thread(update_balance, b["uid"], prize)
            await asyncio.to_thread(log_game, b["uid"], "рулетка", b["amount"], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")
        else:
            await asyncio.to_thread(log_game, b["uid"], "рулетка", b["amount"], 0)

    lines.append("\n".join(winners) if winners else random.choice(LOSE_PHRASES))
    text = "\n".join(lines)
    try:
        await msg.edit_caption(caption=text)
    except Exception:
        try:
            await msg.edit_text(text)
        except Exception:
            pass
    active_roulette[chat_id] = {"status": "waiting", "bets": []}
    asyncio.create_task(auto_delete(msg, 60))


# ---- МИНЫ ----
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


async def _start_mines(message: Message, amount: int):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
    await asyncio.to_thread(update_balance, user[0], -amount)
    game_key = f"{message.chat.id}_{user[0]}"
    active_mines[game_key] = {
        "uid": user[0], "bet": amount,
        "mines": set(random.sample(range(25), 5)), "opened": [],
    }
    msg = await message.reply(
        f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}",
        reply_markup=_mines_keyboard(game_key, [], 0),
    )
    asyncio.create_task(auto_delete(msg, 120))


@group_router.message(F.text.regexp(r"(?i)^мины\s+(.+)$"))
async def play_mines_text(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная ставка.")
    await _start_mines(message, amount)


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
        else:
            await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], 0)
        try:
            await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
        except Exception:
            pass
        del active_mines[game_key]
        return await callback.answer("Зачислено!")

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
        try:
            await callback.message.edit_text(
                f"💥 <b>БУМ!</b> {random.choice(LOSE_PHRASES)} Проигрыш {format_money(game['bet'])}.",
                reply_markup=kb,
            )
        except Exception:
            pass
        await asyncio.to_thread(log_game, game["uid"], "мины", game["bet"], 0)
        del active_mines[game_key]
        return await callback.answer("Мина!")
    game["opened"].append(cell)
    potential = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    kb = _mines_keyboard(game_key, game["opened"], potential)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer(f"Безопасно! Потенциал: {format_money(potential)}")


# ---- БЛЭКДЖЕК ----
BJ_SUITS = ["♠", "♥", "♦", "♣"]
BJ_RANKS = [("2",2),("3",3),("4",4),("5",5),("6",6),("7",7),("8",8),("9",9),("10",10),("J",10),("Q",10),("K",10),("A",11)]


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


def _bj_keyboard(game_key: str):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{game_key}"))
    kb.row(InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj_stop_{game_key}"))
    return kb.as_markup()


async def _start_bj(message: Message, amount: int):
    user = await asyncio.to_thread(get_user, message.from_user.id)
    if user[3] < amount:
        return await message.reply(_(user, "not_enough"))
    await asyncio.to_thread(update_balance, user[0], -amount)
    deck = _new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    game_key = f"{message.chat.id}_{user[0]}"
    active_bj[game_key] = {
        "uid": user[0], "bet": amount, "deck": deck,
        "p": player, "d": dealer, "chat": message.chat.id,
    }
    text = f"🃏 <b>БЖ</b>\nТы: {_format_hand(player)} ({_hand_value(player)})\nДилер: {_format_hand(dealer, True)}"
    msg = await message.reply(text, reply_markup=_bj_keyboard(game_key))
    asyncio.create_task(auto_delete(msg, 120))
    if _hand_value(player) == 21:
        await _bj_finish(msg, game_key, message.chat.id)


@group_router.message(F.text.regexp(r"(?i)^бж\s+(.+)$"))
async def play_bj_text(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    if await require_subscription(message):
        return
    amount = parse_amt(message.text.split()[1])
    if not amount:
        return await message.reply("❌ Неверная ставка.")
    await _start_bj(message, amount)


@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(callback: CallbackQuery):
    game_key = callback.data[len("bj_hit_"):]
    game = active_bj.get(game_key)
    if not game:
        return await callback.answer("Игра окончена.", show_alert=True)
    if callback.from_user.id != game["uid"]:
        return await callback.answer("Не твоя игра!", show_alert=True)
    game["p"].append(game["deck"].pop())
    val = _hand_value(game["p"])
    if val > 21:
        await callback.answer("Перебор!")
        return await _bj_finish(callback.message, game_key, game["chat"], bust=True)
    text = f"🃏 <b>БЖ</b>\nТы: {_format_hand(game['p'])} ({val})\nДилер: {_format_hand(game['d'], True)}"
    try:
        await callback.message.edit_text(text, reply_markup=_bj_keyboard(game_key))
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
    await _bj_finish(callback.message, game_key, game["chat"])


async def _bj_finish(message: Message, game_key: str, chat_id: int, bust: bool = False):
    game = active_bj.pop(game_key, None)
    if not game:
        return
    player_val = _hand_value(game["p"])
    dealer = game["d"]
    while _hand_value(dealer) < 17:
        dealer.append(game["deck"].pop())
    dealer_val = _hand_value(dealer)

    if bust or player_val > 21:
        result, prize = f"💥 Перебор! {random.choice(LOSE_PHRASES)}", 0
    elif dealer_val > 21 or player_val > dealer_val:
        prize = game["bet"] * 2
        result = f"{random.choice(WIN_PHRASES)} Выигрыш: {format_money(prize)}"
    elif player_val == dealer_val:
        prize = game["bet"]
        result = f"🤝 Ничья. Возврат: {format_money(prize)}"
    else:
        result, prize = f"😢 Дилер победил. {random.choice(LOSE_PHRASES)}", 0

    if prize:
        await asyncio.to_thread(update_balance, game["uid"], prize)
    await asyncio.to_thread(log_game, game["uid"], "блэкджек", game["bet"], prize)

    text = (
        f"🃏 <b>БЛЭКДЖЕК — ИТОГ</b>\n\n"
        f"👤 <b>Ты:</b> {_format_hand(game['p'])} ({player_val})\n"
        f"🤖 <b>Дилер:</b> {_format_hand(dealer)} ({dealer_val})\n\n{result}"
    )
    try:
        await message.edit_text(text)
    except Exception:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ==============================================================================
# 25. АДМИН-КОМАНДЫ
# ==============================================================================
def _find_user_id(token: str) -> Optional[int]:
    token = token.replace("@", "")
    if token.isdigit():
        res = db_execute("SELECT user_id FROM users WHERE user_id = ?", (int(token),), True)
        return res[0] if res else None
    res = db_execute("SELECT user_id FROM users WHERE username = ?", (token,), True)
    return res[0] if res else None


def _parse_amount(raw: str) -> Optional[int]:
    raw = raw.lower().strip().replace("кк", "000000").replace("к", "000")
    try:
        return int(raw)
    except Exception:
        return None


@admin_router.message(F.text.startswith("@"))
async def neuro_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    cmd = args[0].lower()

    if cmd == "@помощь":
        return await message.reply(
            "👑 <b>КОМАНДЫ</b>\n\n"
            "<code>@бан [ник]</code> / <code>@анбан [ник]</code>\n"
            "<code>@вип [ник]</code>\n"
            "<code>@выдать [ник] 10к</code>\n"
            "<code>@забрать [ник] 5к</code>\n"
            "<code>@очистить_баланс [ник]</code>\n"
            "<code>@дроп 50к</code>\n"
            "<code>@стата</code>\n"
            "<code>@рассылка [текст]</code>\n"
            "<code>@промо [код] [сумма] [лимит]</code>\n"
            "<code>@промо_список</code>\n"
            "<code>@промо_удалить [код]</code>"
        )

    if cmd == "@стата":
        users = db_execute("SELECT COUNT(*) FROM users", (), True)[0]
        total_bal = db_execute("SELECT SUM(balance) FROM users", (), True)[0] or 0
        return await message.reply(f"📊 Игроков: {users}\n💰 Баланс: {format_money(total_bal)}")

    if cmd == "@бан" and len(args) >= 2:
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role='banned' WHERE user_id=?", (uid,))
            cache_invalidate(uid)
            return await message.reply(f"🚫 {args[1]} забанен.")

    if cmd == "@анбан" and len(args) >= 2:
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET role='user' WHERE user_id=?", (uid,))
            cache_invalidate(uid)
            return await message.reply(f"✅ {args[1]} разбанен.")

    if cmd == "@вип" and len(args) >= 2:
        uid = _find_user_id(args[1])
        if uid:
            until = (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat()
            db_execute("UPDATE users SET role='vip', vip_until=? WHERE user_id=?", (until, uid))
            cache_invalidate(uid)
            return await message.reply(f"👑 {args[1]} теперь VIP.")

    if cmd == "@выдать" and len(args) >= 3:
        uid = _find_user_id(args[1]); amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, amount)
            return await message.reply(f"✅ +{format_money(amount)} → {args[1]}")

    if cmd == "@забрать" and len(args) >= 3:
        uid = _find_user_id(args[1]); amount = _parse_amount(args[2])
        if uid and amount:
            update_balance(uid, -amount)
            return await message.reply(f"✅ -{format_money(amount)} у {args[1]}")

    if cmd == "@очистить_баланс" and len(args) >= 2:
        uid = _find_user_id(args[1])
        if uid:
            db_execute("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
            cache_invalidate(uid)
            return await message.reply("🧹 Баланс обнулён.")

    if cmd == "@дроп" and len(args) >= 2:
        amount = _parse_amount(args[1])
        if amount:
            kb = InlineKeyboardBuilder().button(text="💰 СХВАТИТЬ", callback_data=f"drop_{amount}")
            msg = await bot.send_message(
                CHAT_ID,
                f"🚨 <b>ДРОП!</b> Кто первый нажмёт — заберёт {format_money(amount)}!",
                reply_markup=kb.as_markup(),
            )
            asyncio.create_task(auto_delete(msg, 60))
            return await message.reply("✅ Дроп запущен.")

    if cmd == "@рассылка" and len(args) >= 2:
        text = message.text[len("@рассылка "):]
        users = db_execute("SELECT user_id FROM users", (), False, True)
        count = 0
        for u in users or []:
            try:
                await bot.send_message(u[0], f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text}")
                count += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        return await message.reply(f"✅ Доставлено: {count}")

    if cmd == "@промо" and len(args) >= 4:
        code = args[1].upper()
        reward = _parse_amount(args[2])
        limit = _parse_amount(args[3])
        if reward and limit:
            db_execute(
                "INSERT INTO promos (code, reward, limit_count) VALUES (?, ?, ?) "
                "ON CONFLICT (code) DO UPDATE SET reward=?, limit_count=?",
                (code, reward, limit, reward, limit),
            )
            return await message.reply(f"✅ Промокод {code} создан.")

    if cmd == "@промо_список":
        rows = db_execute("SELECT code, reward, limit_count, used_count FROM promos", (), False, True)
        if not rows:
            return await message.reply("Промокодов нет.")
        text = "🎟 <b>ПРОМОКОДЫ</b>\n\n"
        for c, r, l, u in rows:
            text += f"<code>{c}</code> — {format_money(r)} (Исп: {u}/{l})\n"
        return await message.reply(text)

    if cmd == "@промо_удалить" and len(args) >= 2:
        code = args[1].upper()
        db_execute("DELETE FROM promos WHERE code=?", (code,))
        return await message.reply(f"🗑 {code} удалён.")


@group_router.callback_query(F.data.startswith("drop_"))
async def claim_drop(callback: CallbackQuery):
    try:
        amount = int(callback.data.split("_")[1])
    except Exception:
        return await callback.answer()
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    await asyncio.to_thread(update_balance, user[0], amount)
    asyncio.create_task(_safe_sticker(callback.message, STICKER_MONEY))
    try:
        await callback.message.edit_text(
            f"💰 Мешок забрал <b>{callback.from_user.first_name}</b>! Он получил {format_money(amount)}!"
        )
    except Exception:
        pass
    await callback.answer("Ты забрал куш!", show_alert=True)


# ==============================================================================
# 26. АВТО-ИВЕНТЫ
# ==============================================================================
async def auto_drop():
    amount = random.choice([10000, 25000, 50000, 100000])
    kb = InlineKeyboardBuilder().button(text="💰 СХВАТИТЬ", callback_data=f"drop_{amount}")
    try:
        msg = await bot.send_message(
            CHAT_ID,
            f"🚨 <b>АВТО-ДРОП!</b> Кто первый нажмёт — заберёт {format_money(amount)}!",
            reply_markup=kb.as_markup(),
        )
        await bot.send_sticker(CHAT_ID, STICKER_GIFT)
        asyncio.create_task(auto_delete(msg, 90))
    except Exception as e:
        logger.warning(f"auto_drop: {e}")


async def auto_promo_create():
    code = f"TOKENS{random.randint(1000, 9999)}"
    reward = 10000
    db_execute(
        "INSERT INTO promos (code, reward, limit_count) VALUES (?, ?, 5) ON CONFLICT DO NOTHING",
        (code, reward),
    )
    try:
        await bot.send_message(
            CHAT_ID,
            f"🎟 <b>АВТО-ПРОМОКОД!</b>\n\n"
            f"Код: <code>{code}</code>\n"
            f"Награда: {format_money(reward)}\n"
            f"Лимит: 5 активаций!\n\n"
            f"Активируй: <code>промо {code}</code>",
        )
    except Exception:
        pass


async def auto_lottery_start():
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="🎟 Купить билет (10к)", callback_data="buy_ticket"))
    try:
        msg = await bot.send_message(CHAT_ID, "🎟 <b>РОЗЫГРЫШ ЛОТЕРЕИ!</b>", reply_markup=kb.as_markup())
        await bot.send_sticker(CHAT_ID, STICKER_GIFT)
        asyncio.create_task(auto_delete(msg, 3600))
    except Exception:
        pass


@group_router.callback_query(F.data == "buy_ticket")
async def buy_ticket(callback: CallbackQuery):
    user = await asyncio.to_thread(get_user, callback.from_user.id)
    if user[3] < 10000:
        return await callback.answer("Мало средств!", show_alert=True)
    await asyncio.to_thread(update_balance, user[0], -10000)
    db_execute("INSERT INTO lottery (user_id) VALUES (?)", (user[0],))
    await callback.answer("Билет куплен!", show_alert=True)


async def auto_lottery_end():
    tickets = db_execute("SELECT user_id FROM lottery", (), False, True)
    if not tickets:
        try:
            await bot.send_message(CHAT_ID, "Лотерея не состоялась (нет билетов).")
        except Exception:
            pass
        return
    winner = random.choice(tickets)[0]
    db_execute("DELETE FROM lottery")
    await asyncio.to_thread(update_balance, winner, 500_000)
    try:
        await bot.send_sticker(CHAT_ID, STICKER_CROWN)
    except Exception:
        pass
    await bot.send_message(
        CHAT_ID,
        f"🏆 Победитель лотереи: <a href='tg://user?id={winner}'>Игрок</a>!\nВыигрыш: 500 000 Tokens!",
    )


async def vip_daily_bonus():
    """VIP-автобонус в 12:00: 30 000 Tokens каждому активному VIP."""
    now = datetime.datetime.now()
    rows = db_execute(
        "SELECT user_id FROM users WHERE role='vip' AND vip_until IS NOT NULL", (), False, True
    )
    for (uid,) in rows or []:
        u = get_user(uid)
        if not u or not is_vip(u):
            continue
        await asyncio.to_thread(update_balance, uid, 30000)
        try:
            await bot.send_message(uid, "👑 <b>VIP-БОНУС</b> начислен: +30 000 Tokens!")
            await bot.send_sticker(uid, STICKER_CROWN)
        except Exception:
            pass
    # сброс просроченных VIP
    db_execute(
        "UPDATE users SET role='user' WHERE role='vip' AND vip_until IS NOT NULL AND vip_until < ?",
        (now.isoformat(),),
    )


async def vip_renewal_reminder():
    """За 1 день до конца VIP — напоминаем."""
    now = datetime.datetime.now()
    tomorrow = (now + datetime.timedelta(days=1)).isoformat()
    rows = db_execute(
        "SELECT user_id, vip_until FROM users WHERE role='vip' AND vip_until IS NOT NULL "
        "AND vip_until > ? AND vip_until < ?",
        (now.isoformat(), tomorrow), False, True,
    )
    for uid, until in rows or []:
        try:
            kb = InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="👑 Продлить VIP", callback_data="donate_vip")
            )
            await bot.send_message(
                uid,
                "👑 <b>VIP скоро истекает!</b>\n\n"
                "Продлить VIP за 30 ⭐?",
                reply_markup=kb.as_markup(),
            )
        except Exception:
            pass


# ==============================================================================
# 27. ЗАПУСК
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

    # Авто-ивенты
    scheduler.add_job(auto_drop, "interval", hours=2)
    scheduler.add_job(auto_promo_create, "cron", hour=15, minute=0)
    scheduler.add_job(auto_lottery_start, "cron", hour=20, minute=0)
    scheduler.add_job(auto_lottery_end, "cron", hour=21, minute=0)
    scheduler.add_job(vip_daily_bonus, "cron", hour=12, minute=0)
    scheduler.add_job(vip_renewal_reminder, "cron", hour=11, minute=0)
    scheduler.start()

    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass