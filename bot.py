import asyncio
import io
import logging
import os
import random
import shutil
import time
from pathlib import Path
from contextlib import suppress

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ErrorEvent,
)
from aiogram.exceptions import TelegramBadRequest
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "8940867005:AAEe0MexxwgCMc9YYk9dvUkGtmjoMj55D-E"
ADMIN_ID = int(os.getenv("ADMIN_ID", ""))
DB_PATH = os.getenv("DB_PATH", "tokens_club.db")

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

PROFILE_BG = ASSETS_DIR / "profile_bg.jpg"
PROFILE_FONT = ASSETS_DIR / "Montserrat-Bold.ttf"

START_PHOTO = ASSETS_DIR / "start.jpg"
BONUS_PHOTO = ASSETS_DIR / "bonus.jpg"
TOP_PHOTO = ASSETS_DIR / "top.jpg"
TOURNAMENT_PHOTO = ASSETS_DIR / "tournament.jpg"
HOW_TO_PLAY_PHOTO = ASSETS_DIR / "how_to_play.jpg"
SUPPORT_PHOTO = ASSETS_DIR / "support.jpg"
CHATS_PHOTO = ASSETS_DIR / "chats.jpg"

SUPPORT_URL = "https://t.me/vctorw"
GAME_CHAT_URL = "https://t.me/tokenplays"
EXCHANGE_URL = "https://t.me/Tokenschange"
NEWS_URL = "https://t.me/TokenCasinoTournaments"

BONUS_AMOUNT = 25
ACTIVITY_COOLDOWN = 60
ACTIVITY_WIN_REWARD = 15
ACTIVITY_LOSS_REWARD = 5

CAPTCHA_MIN = 1000
CAPTCHA_MAX = 9999

AUTO_DELETE_SECONDS = 30
GAME_DELETE_SECONDS = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens-club")


# ============================================================
# ТЕКСТЫ И ЛОКАЛИЗАЦИЯ
# ============================================================

TEXTS = {
    "ru": {
        "welcome": "👑 Добро пожаловать в TOKENS | PRIVATE CLUB!",
        "captcha": "🔐 Введите цифры с картинки, чтобы подтвердить, что вы не бот.",
        "captcha_wrong": "❌ Неверный код. Попробуйте ещё раз.",
        "captcha_ok": "✅ Проверка пройдена!",
        "profile": "👤 Ваш профиль",
        "balance": "💰 Ваш баланс: {balance} TOKENS",
        "bonus_ok": "🎁 Вы получили ежедневный бонус: +{amount} TOKENS!",
        "bonus_wait": "⏳ Следующий бонус через {hours} ч. {minutes} мин.",
        "activities": "🎮 Выберите активность. За успех начисляется {win}, за неудачу — {loss} TOKENS. Участие бесплатное.",
        "game_win": "🏆 Успех! Начислено +{amount} TOKENS.",
        "game_loss": "🙂 Попытка засчитана. Утешительная награда: +{amount} TOKENS.",
        "cooldown": "⏳ Следующая награда за эту игру через {seconds} сек.",
        "shop": "💎 Магазин\n\nПополнение баланса временно недоступно. Покупка TOKENS за реальные деньги или Telegram Stars не поддерживается.",
        "partners": "🤝 Партнёрские площадки:",
        "tournament": "🏆 Следите за новостями и объявлениями турниров в официальном канале.",
        "top": "📊 ТОП участников",
        "support": "🆘 Нажмите кнопку ниже, чтобы связаться с поддержкой.",
        "chats": "💬 Наши чаты и новости:",
        "language": "🌐 Выберите язык:",
        "language_saved": "✅ Язык изменён.",
        "not_found": "Пользователь не найден.",
        "no_permission": "⛔ Недостаточно прав.",
        "transfer_usage": "Использование: ответьте на сообщение пользователя командой «перевод 100».",
        "transfer_self": "Нельзя переводить TOKENS самому себе.",
        "transfer_amount": "Укажите корректную положительную сумму.",
        "transfer_success": "✅ Переведено {amount} TOKENS пользователю {name}.",
        "transfer_received": "💰 Вам перевели {amount} TOKENS.",
    },
    "en": {
        "welcome": "👑 Welcome to TOKENS | PRIVATE CLUB!",
        "captcha": "🔐 Enter the digits in the image to verify that you are human.",
        "captcha_wrong": "❌ Incorrect code. Try again.",
        "captcha_ok": "✅ Verification completed!",
        "profile": "👤 Your profile",
        "balance": "💰 Your balance: {balance} TOKENS",
        "bonus_ok": "🎁 Daily bonus received: +{amount} TOKENS!",
        "bonus_wait": "⏳ Next bonus in {hours}h {minutes}m.",
        "activities": "🎮 Choose an activity. Success reward: {win}; consolation reward: {loss} TOKENS. Free to play.",
        "game_win": "🏆 Success! +{amount} TOKENS credited.",
        "game_loss": "🙂 Attempt recorded. Consolation reward: +{amount} TOKENS.",
        "cooldown": "⏳ Next reward for this game in {seconds}s.",
        "shop": "💎 Shop\n\nBalance top-ups are temporarily unavailable. TOKENS purchases with real money or Telegram Stars are not supported.",
        "partners": "🤝 Partner platforms:",
        "tournament": "🏆 Follow tournament announcements in the official channel.",
        "top": "📊 TOP players",
        "support": "🆘 Press the button below to contact support.",
        "chats": "💬 Our chats and news:",
        "language": "🌐 Choose your language:",
        "language_saved": "✅ Language updated.",
        "not_found": "User not found.",
        "no_permission": "⛔ Permission denied.",
        "transfer_usage": "Usage: reply to a user's message with «transfer 100».",
        "transfer_self": "You cannot transfer TOKENS to yourself.",
        "transfer_amount": "Enter a valid positive amount.",
        "transfer_success": "✅ Transferred {amount} TOKENS to {name}.",
        "transfer_received": "💰 You received {amount} TOKENS.",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXTS else "ru"
    template = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    return template.format(**kwargs)


# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================

class CaptchaState(StatesGroup):
    waiting_answer = State()


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()
        self.cache = {}

    def invalidate(self, user_id: int):
        self.cache.pop(user_id, None)

    async def init(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA foreign_keys=ON")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT DEFAULT '',
                        full_name TEXT DEFAULT '',
                        balance INTEGER NOT NULL DEFAULT 0,
                        is_verified INTEGER NOT NULL DEFAULT 0,
                        language TEXT NOT NULL DEFAULT 'ru',
                        rank TEXT NOT NULL DEFAULT 'Новичок',
                        last_bonus INTEGER NOT NULL DEFAULT 0,
                        joined_at INTEGER NOT NULL DEFAULT 0,
                        is_banned INTEGER NOT NULL DEFAULT 0
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity_cooldowns (
                        user_id INTEGER NOT NULL,
                        activity TEXT NOT NULL,
                        last_play INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (user_id, activity)
                    )
                """)

                await conn.commit()

    async def ensure_user(
        self,
        user_id: int,
        username: str = "",
        full_name: str = "",
    ):
        now = int(time.time())

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("""
                    INSERT OR IGNORE INTO users
                    (user_id, username, full_name, balance, is_verified,
                     language, rank, last_bonus, joined_at, is_banned)
                    VALUES (?, ?, ?, 0, 0, 'ru', 'Новичок', 0, ?, 0)
                """, (user_id, username or "", full_name or "", now))

                await conn.execute("""
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                """, (username or "", full_name or "", user_id))

                await conn.commit()

        self.invalidate(user_id)

    async def get_user(self, user_id: int):
        now = time.time()
        cached = self.cache.get(user_id)

        if cached and now - cached["time"] < 5:
            return cached["data"]

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id, username, full_name, balance,
                           is_verified, language, rank, last_bonus,
                           joined_at, is_banned
                    FROM users
                    WHERE user_id = ?
                """, (user_id,)) as cursor:
                    row = await cursor.fetchone()

        if row is None:
            return None

        data = {
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "balance": row[3],
            "is_verified": bool(row[4]),
            "language": row[5],
            "rank": row[6],
            "last_bonus": row[7],
            "joined_at": row[8],
            "is_banned": bool(row[9]),
        }

        self.cache[user_id] = {"time": now, "data": data}
        return data

    async def set_verified(self, user_id: int):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute(
                    "UPDATE users SET is_verified = 1 WHERE user_id = ?",
                    (user_id,),
                )
                await conn.commit()

        self.invalidate(user_id)

    async def set_language(self, user_id: int, language: str):
        if language not in ("ru", "en"):
            return

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute(
                    "UPDATE users SET language = ? WHERE user_id = ?",
                    (language, user_id),
                )
                await conn.commit()

        self.invalidate(user_id)

    async def set_banned(self, user_id: int, banned: bool):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute(
                    "UPDATE users SET is_banned = ? WHERE user_id = ?",
                    (int(banned), user_id),
                )
                await conn.commit()

        self.invalidate(user_id)

    @staticmethod
    def rank_for_balance(balance: int) -> str:
        if balance >= 10000:
            return "Легенда"
        if balance >= 5000:
            return "Элита"
        if balance >= 2000:
            return "Мастер"
        if balance >= 500:
            return "Игрок"
        return "Новичок"

    async def change_balance(self, user_id: int, amount: int):
        if amount == 0:
            return False

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False

                new_balance = row[0] + amount

                if new_balance < 0:
                    await conn.rollback()
                    return False

                rank = self.rank_for_balance(new_balance)

                await conn.execute("""
                    UPDATE users
                    SET balance = ?, rank = ?
                    WHERE user_id = ?
                """, (new_balance, rank, user_id))

                await conn.commit()

        self.invalidate(user_id)
        return True

    async def transfer(self, sender_id: int, recipient_id: int, amount: int):
        if sender_id == recipient_id or amount <= 0:
            return False

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (sender_id,),
                ) as cursor:
                    sender = await cursor.fetchone()

                async with conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?",
                    (recipient_id,),
                ) as cursor:
                    recipient = await cursor.fetchone()

                if sender is None or recipient is None or sender[0] < amount:
                    await conn.rollback()
                    return False

                sender_balance = sender[0] - amount
                await conn.execute(
                    "UPDATE users SET balance = ?, rank = ? WHERE user_id = ?",
                    (
                        sender_balance,
                        self.rank_for_balance(sender_balance),
                        sender_id,
                    ),
                )

                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (recipient_id,),
                ) as cursor:
                    recipient_balance = await cursor.fetchone()

                new_recipient_balance = recipient_balance[0] + amount

                await conn.execute(
                    "UPDATE users SET balance = ?, rank = ? WHERE user_id = ?",
                    (
                        new_recipient_balance,
                        self.rank_for_balance(new_recipient_balance),
                        recipient_id,
                    ),
                )

                await conn.commit()

        self.invalidate(sender_id)
        self.invalidate(recipient_id)
        return True

    async def claim_bonus(self, user_id: int):
        now = int(time.time())
        day = 86400

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute(
                    "SELECT last_bonus, balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False, 0

                last_bonus, balance = row

                if now - last_bonus < day:
                    await conn.rollback()
                    return False, day - (now - last_bonus)

                new_balance = balance + BONUS_AMOUNT

                await conn.execute("""
                    UPDATE users
                    SET balance = ?, last_bonus = ?, rank = ?
                    WHERE user_id = ?
                """, (
                    new_balance,
                    now,
                    self.rank_for_balance(new_balance),
                    user_id,
                ))

                await conn.commit()

        self.invalidate(user_id)
        return True, BONUS_AMOUNT

    async def claim_activity(self, user_id: int, activity: str, won: bool):
        now = int(time.time())
        reward = ACTIVITY_WIN_REWARD if won else ACTIVITY_LOSS_REWARD

        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")

                async with conn.execute("""
                    SELECT last_play
                    FROM activity_cooldowns
                    WHERE user_id = ? AND activity = ?
                """, (user_id, activity)) as cursor:
                    row = await cursor.fetchone()

                last_play = row[0] if row else 0
                elapsed = now - last_play

                if elapsed < ACTIVITY_COOLDOWN:
                    await conn.rollback()
                    return False, ACTIVITY_COOLDOWN - elapsed

                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    user_row = await cursor.fetchone()

                if user_row is None:
                    await conn.rollback()
                    return False, 0

                new_balance = user_row[0] + reward

                await conn.execute("""
                    INSERT INTO activity_cooldowns
                    (user_id, activity, last_play)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, activity)
                    DO UPDATE SET last_play = excluded.last_play
                """, (user_id, activity, now))

                await conn.execute("""
                    UPDATE users
                    SET balance = ?, rank = ?
                    WHERE user_id = ?
                """, (
                    new_balance,
                    self.rank_for_balance(new_balance),
                    user_id,
                ))

                await conn.commit()

        self.invalidate(user_id)
        return True, reward

    async def get_top(self, limit: int = 10):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id, username, full_name, balance, rank
                    FROM users
                    WHERE is_verified = 1 AND is_banned = 0
                    ORDER BY balance DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    return await cursor.fetchall()

    async def get_all_verified_ids(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT user_id FROM users
                    WHERE is_verified = 1 AND is_banned = 0
                """) as cursor:
                    rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def get_stats(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                async with conn.execute("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN is_verified = 1 THEN 1 ELSE 0 END),
                           SUM(balance)
                    FROM users
                """) as cursor:
                    row = await cursor.fetchone()

        return row or (0, 0, 0)

    async def close(self):
        async with self.lock:
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                await conn.commit()


db = Database(DB_PATH)


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_keyboard(lang: str = "ru"):
    if lang == "en":
        labels = [
            ("🎮 Activities", "🎁 Bonus", "💎 Shop"),
            ("👤 Profile", "🤝 Partners", "🏆 Tournament"),
            ("📊 Top", "💬 Chats", "🆘 Support"),
            ("🌐 Language",),
        ]
    else:
        labels = [
            ("🎮 Активности", "🎁 Бонус", "💎 Магазин"),
            ("👤 Профиль", "🤝 Партнёры", "🏆 Турнир"),
            ("📊 Топ", "💬 Чаты", "🆘 Поддержка"),
            ("🌐 Язык",),
        ]

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=text) for text in row]
            for row in labels
        ],
        resize_keyboard=True,
    )


def activities_keyboard(lang: str = "ru"):
    names = (
        ["🎲 Dice", "🎯 Darts", "🏀 Basketball", "⚽ Football", "🎳 Bowling"]
        if lang == "en"
        else ["🎲 Кости", "🎯 Дартс", "🏀 Баскет", "⚽ Футбол", "🎳 Боулинг"]
    )

    keys = ["dice", "darts", "basketball", "football", "bowling"]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=names[index],
                    callback_data=f"game:{keys[index]}",
                )
            ]
            for index in range(len(keys))
        ]
    )


def language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def auto_delete(message: Message, seconds: int):
    if message.chat.type != ChatType.PRIVATE:
        return

    await asyncio.sleep(seconds)

    with suppress(Exception):
        await message.delete()


async def temp_answer(message: Message, text: str, **kwargs):
    sent = await message.answer(text, **kwargs)

    if message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(sent, AUTO_DELETE_SECONDS))

    return sent


async def temp_photo(message: Message, path: Path, caption: str, **kwargs):
    if path.exists():
        sent = await message.answer_photo(
            BufferedInputFile(path.read_bytes(), filename=path.name),
            caption=caption,
            **kwargs,
        )
    else:
        sent = await message.answer(caption, **kwargs)

    if message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(sent, AUTO_DELETE_SECONDS))

    return sent


async def send_main_menu(message: Message, lang: str):
    caption = tr(lang, "welcome")
    keyboard = main_keyboard(lang)

    if START_PHOTO.exists():
        return await message.answer_photo(
            BufferedInputFile(START_PHOTO.read_bytes(), filename=START_PHOTO.name),
            caption=caption,
            reply_markup=keyboard,
        )

    return await message.answer(caption, reply_markup=keyboard)


def get_font(size: int):
    if PROFILE_FONT.exists():
        try:
            return ImageFont.truetype(str(PROFILE_FONT), size=size)
        except Exception:
            logger.exception("Не удалось загрузить Montserrat-Bold.ttf")

    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def fit_avatar(avatar: Image.Image, size: int):
    avatar = avatar.convert("RGB")
    avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(avatar, (0, 0), mask)

    return result


async def get_avatar(bot: Bot, user_id: int):
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]
        file_info = await bot.get_file(photo.file_id)

        buffer = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buffer)
        buffer.seek(0)

        return Image.open(buffer).convert("RGBA")

    except Exception:
        logger.exception("Не удалось получить аватар пользователя %s", user_id)
        return None


# ============================================================
# ГЕНЕРАЦИЯ ПРОФИЛЯ
# ============================================================

def generate_profile_image(
    avatar: Image.Image | None,
    name: str,
    user_id: int,
    rank: str,
    balance: int,
):
    """
    Заготовка profile_bg.jpg: 1024x512.

    Аватар:
        круг, центр примерно x=140, y=180, размер 220x220.

    Правая часть:
        имя    x=550, y=180
        ID     x=550, y=260
        ранг   x=550, y=330
        баланс x=550, y=410
    """

    if not PROFILE_BG.exists():
        raise FileNotFoundError(
            f"Не найден файл заготовки профиля: {PROFILE_BG}"
        )

    background = Image.open(PROFILE_BG).convert("RGBA")
    background = background.resize((1024, 512), Image.Resampling.LANCZOS)

    # --------------------------------------------------------
    # АВАТАРКА: круг в левом квадрате
    # --------------------------------------------------------

    avatar_size = 220
    avatar_x = 140
    avatar_y = 180

    if avatar is not None:
        circular_avatar = fit_avatar(avatar, avatar_size)

        # Золотое внешнее свечение.
        glow_layer = Image.new("RGBA", background.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)

        glow_draw.ellipse(
            (
                avatar_x - 8,
                avatar_y - 8,
                avatar_x + avatar_size + 8,
                avatar_y + avatar_size + 8,
            ),
            fill=(212, 175, 55, 115),
        )

        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(12))
        background.alpha_composite(glow_layer)

        # Золотая рамка.
        frame_draw = ImageDraw.Draw(background)
        frame_draw.ellipse(
            (
                avatar_x - 5,
                avatar_y - 5,
                avatar_x + avatar_size + 5,
                avatar_y + avatar_size + 5,
            ),
            outline=(212, 175, 55, 255),
            width=8,
        )

        background.alpha_composite(
            circular_avatar,
            (avatar_x, avatar_y),
        )

    else:
        # Если аватар отсутствует, оставляем левый квадрат фона.
        pass

    # --------------------------------------------------------
    # ТЕКСТ: строго по правым плашкам
    # --------------------------------------------------------

    draw = ImageDraw.Draw(background)

    gold = (212, 175, 55, 255)
    white = (255, 255, 255, 255)
    outline = (15, 15, 18, 255)

    font_name = get_font(30)
    font_regular = get_font(27)

    # Координаты заданы относительно макета 1024x512.
    text_x = 550

    fields = [
        (name[:24], text_x, 180, font_name),
        (str(user_id), text_x, 260, font_regular),
        (rank[:24], text_x, 330, font_regular),
        (f"{balance:,} TOKENS".replace(",", " "), text_x, 410, font_regular),
    ]

    for text, x, y, font in fields:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=gold,
            stroke_width=2,
            stroke_fill=outline,
        )

    output = io.BytesIO()
    background.convert("RGB").save(output, format="JPEG", quality=94)
    output.seek(0)

    return output.getvalue()


# ============================================================
# CAPTCHA
# ============================================================

def generate_captcha():
    answer = random.randint(CAPTCHA_MIN, CAPTCHA_MAX)

    width, height = 420, 180
    image = Image.new("RGB", (width, height), (24, 28, 40))
    draw = ImageDraw.Draw(image)

    # Шумовые линии.
    for _ in range(30):
        draw.line(
            (
                random.randint(0, width),
                random.randint(0, height),
                random.randint(0, width),
                random.randint(0, height),
            ),
            fill=(
                random.randint(55, 125),
                random.randint(55, 125),
                random.randint(55, 125),
            ),
            width=random.randint(1, 3),
        )

    # Шумовые точки.
    for _ in range(500):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        draw.point(
            (x, y),
            fill=(
                random.randint(70, 180),
                random.randint(70, 180),
                random.randint(70, 180),
            ),
        )

    font = get_font(68)
    text = str(answer)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    draw.text(
        (
            (width - text_width) // 2,
            (height - text_height) // 2 - 8,
        ),
        text,
        font=font,
        fill=(255, 215, 110),
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return str(answer), buffer.getvalue()


async def send_captcha(message: Message, state: FSMContext, lang: str):
    answer, image_bytes = generate_captcha()

    await state.set_state(CaptchaState.waiting_answer)
    await state.update_data(captcha_answer=answer)

    await message.answer_photo(
        BufferedInputFile(image_bytes, filename="captcha.png"),
        caption=tr(lang, "captcha"),
    )


# ============================================================
# MIDDLEWARE: РЕГИСТРАЦИЯ, CAPTCHA, БАН
# ============================================================

class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return await handler(event, data)

        await db.ensure_user(
            user.id,
            user.username or "",
            user.full_name or "",
        )

        user_data = await db.get_user(user.id)
        state = data.get("state")

        if user_data and user_data["is_banned"]:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Вы заблокированы.", show_alert=True)
            else:
                await event.answer("⛔ Вы заблокированы.")
            return None

        # CAPTCHA используется только в личных сообщениях.
        if isinstance(event, Message) and event.chat.type == ChatType.PRIVATE:
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            if user_data and user_data["is_verified"]:
                return await handler(event, data)

            if state and await state.get_state() == CaptchaState.waiting_answer.state:
                return await handler(event, data)

            if state:
                await send_captcha(
                    event,
                    state,
                    user_data["language"] if user_data else "ru",
                )
            return None

        if isinstance(event, CallbackQuery):
            if user_data and user_data["is_verified"]:
                return await handler(event, data)

            await event.answer(
                "Сначала пройдите проверку через /start.",
                show_alert=True,
            )
            return None

        return await handler(event, data)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

router.message.middleware(UserMiddleware())
router.callback_query.middleware(UserMiddleware())

dp.include_router(router)


# ============================================================
# /START И CAPTCHA
# ============================================================

@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    user = message.from_user

    await db.ensure_user(
        user.id,
        user.username or "",
        user.full_name or "",
    )

    user_data = await db.get_user(user.id)
    lang = user_data["language"] if user_data else "ru"

    if user_data and user_data["is_verified"]:
        await state.clear()
        await send_main_menu(message, lang)
        return

    await send_captcha(message, state, lang)


@router.message(CaptchaState.waiting_answer)
async def captcha_answer_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    expected = str(data.get("captcha_answer", ""))

    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    if not message.text or message.text.strip() != expected:
        await temp_answer(message, tr(lang, "captcha_wrong"))
        await send_captcha(message, state, lang)
        return

    await db.set_verified(message.from_user.id)
    await state.clear()

    await message.answer(tr(lang, "captcha_ok"))
    await send_main_menu(message, lang)


# ============================================================
# ЯЗЫК
# ============================================================

@router.message(F.text.in_({"🌐 Язык", "🌐 Language"}))
async def language_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    await temp_answer(
        message,
        tr(lang, "language"),
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def language_callback(callback: CallbackQuery):
    language = callback.data.split(":", 1)[1]

    if language not in ("ru", "en"):
        await callback.answer("Unknown language", show_alert=True)
        return

    await db.set_language(callback.from_user.id, language)
    await callback.answer(tr(language, "language_saved"))

    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)

    await callback.message.answer(
        tr(language, "language_saved"),
        reply_markup=main_keyboard(language),
    )


# ============================================================
# ПРОФИЛЬ
# ============================================================

@router.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def profile_handler(message: Message):
    user = message.from_user
    user_data = await db.get_user(user.id)

    if not user_data:
        await temp_answer(message, "Не удалось загрузить профиль.")
        return

    avatar = await get_avatar(bot, user.id)

    image_bytes = await asyncio.to_thread(
        generate_profile_image,
        avatar,
        user.full_name or "User",
        user.id,
        user_data["rank"],
        user_data["balance"],
    )

    await message.answer_photo(
        BufferedInputFile(image_bytes, filename="profile.jpg"),
        caption=tr(user_data["language"], "profile"),
    )


# ============================================================
# БАЛАНС
# ============================================================

@router.message(F.text.in_({"б", "баланс", "balance", "/balance"}))
async def balance_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)

    if not user_data:
        return

    await temp_answer(
        message,
        tr(
            user_data["language"],
            "balance",
            balance=f"{user_data['balance']:,}".replace(",", " "),
        ),
    )


# ============================================================
# АКТИВНОСТИ
# ============================================================

@router.message(F.text.in_({"🎮 Активности", "🎮 Activities"}))
async def activities_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    await temp_answer(
        message,
        tr(
            lang,
            "activities",
            win=ACTIVITY_WIN_REWARD,
            loss=ACTIVITY_LOSS_REWARD,
        ),
        reply_markup=activities_keyboard(lang),
    )


GAME_CONFIG = {
    "dice": {
        "emoji": "🎲",
        "title": "Кости",
        "success": lambda value: value >= 4,
    },
    "darts": {
        "emoji": "🎯",
        "title": "Дартс",
        "success": lambda value: value >= 4,
    },
    "basketball": {
        "emoji": "🏀",
        "title": "Баскетбол",
        "success": lambda value: value >= 4,
    },
    "football": {
        "emoji": "⚽",
        "title": "Футбол",
        "success": lambda value: value >= 3,
    },
    "bowling": {
        "emoji": "🎳",
        "title": "Боулинг",
        "success": lambda value: value >= 4,
    },
}


@router.callback_query(F.data.startswith("game:"))
async def game_callback(callback: CallbackQuery):
    game_key = callback.data.split(":", 1)[1]
    config = GAME_CONFIG.get(game_key)

    if config is None:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return

    user_id = callback.from_user.id
    user_data = await db.get_user(user_id)
    lang = user_data["language"] if user_data else "ru"

    await callback.answer()

    dice_message = await callback.message.answer_dice(
        emoji=config["emoji"],
    )

    # Даём Telegram время завершить анимацию и вернуть значение.
    await asyncio.sleep(3)

    dice_value = dice_message.dice.value
    won = config["success"](dice_value)

    success, reward_or_remaining = await db.claim_activity(
        user_id,
        game_key,
        won,
    )

    if not success:
        result_message = await callback.message.answer(
            tr(lang, "cooldown", seconds=reward_or_remaining),
        )
    elif won:
        result_message = await callback.message.answer(
            tr(lang, "game_win", amount=reward_or_remaining),
        )
    else:
        result_message = await callback.message.answer(
            tr(lang, "game_loss", amount=reward_or_remaining),
        )

    if callback.message.chat.type == ChatType.PRIVATE:
        asyncio.create_task(auto_delete(dice_message, GAME_DELETE_SECONDS))
        asyncio.create_task(auto_delete(result_message, GAME_DELETE_SECONDS))


# ============================================================
# ЕЖЕДНЕВНЫЙ БОНУС
# ============================================================

@router.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def bonus_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    success, value = await db.claim_bonus(message.from_user.id)

    if success:
        await temp_photo(
            message,
            BONUS_PHOTO,
            tr(lang, "bonus_ok", amount=value),
        )
        return

    hours = value // 3600
    minutes = (value % 3600) // 60

    await temp_answer(
        message,
        tr(lang, "bonus_wait", hours=hours, minutes=minutes),
    )


# ============================================================
# МАГАЗИН: ИНФОРМАЦИЯ БЕЗ ОПЛАТЫ
# ============================================================

@router.message(F.text.in_({"💎 Магазин", "💎 Shop"}))
async def shop_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    await temp_answer(message, tr(lang, "shop"))


# ============================================================
# ПАРТНЁРЫ
# ============================================================

@router.message(F.text.in_({"🤝 Партнёры", "🤝 Partners"}))
async def partners_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💱 Обмен", url=EXCHANGE_URL)],
            [InlineKeyboardButton(text="💬 Игровой чат", url=GAME_CHAT_URL)],
        ]
    )

    await temp_answer(
        message,
        tr(lang, "partners"),
        reply_markup=keyboard,
    )


# ============================================================
# ТУРНИР
# ============================================================

@router.message(F.text.in_({"🏆 Турнир", "🏆 Tournament"}))
async def tournament_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Новости турниров", url=NEWS_URL)],
            [InlineKeyboardButton(text="💬 Игровой чат", url=GAME_CHAT_URL)],
        ]
    )

    await temp_photo(
        message,
        TOURNAMENT_PHOTO,
        tr(lang, "tournament"),
        reply_markup=keyboard,
    )


# ============================================================
# ТОП
# ============================================================

async def build_top_text(lang: str):
    rows = await db.get_top(10)

    if not rows:
        return "Рейтинг пока пуст."

    lines = [tr(lang, "top"), ""]

    for index, row in enumerate(rows, start=1):
        user_id, username, full_name, balance, rank = row
        name = f"@{username}" if username else (full_name or str(user_id))

        lines.append(
            f"{index}. {name} — {balance:,} TOKENS ({rank})".replace(",", " ")
        )

    return "\n".join(lines)


@router.message(F.text.in_({"📊 Топ", "📊 Top", "топ", "/top"}))
async def top_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    text = await build_top_text(lang)

    await temp_photo(
        message,
        TOP_PHOTO,
        text,
    )


# ============================================================
# ПЕРЕВОД TOKENS В ГРУППЕ
# ============================================================

@router.message(F.text.regexp(r"^(перевод|transfer)\s+\d+$"))
async def transfer_handler(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        user_data = await db.get_user(message.from_user.id)
        lang = user_data["language"] if user_data else "ru"
        await temp_answer(message, tr(lang, "transfer_usage"))
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply(
            "Ответьте на сообщение получателя командой: перевод 100"
        )
        return

    try:
        amount = int(message.text.split()[-1])
    except (ValueError, IndexError):
        await message.reply("Укажите корректную сумму.")
        return

    if amount <= 0:
        await message.reply("Сумма должна быть положительной.")
        return

    sender_id = message.from_user.id
    recipient = message.reply_to_message.from_user
    recipient_id = recipient.id

    if sender_id == recipient_id:
        await message.reply("Нельзя переводить TOKENS самому себе.")
        return

    await db.ensure_user(
        recipient_id,
        recipient.username or "",
        recipient.full_name or "",
    )

    sender_data = await db.get_user(sender_id)
    recipient_data = await db.get_user(recipient_id)

    if not sender_data or not recipient_data:
        await message.reply("Не удалось найти пользователя.")
        return

    if not recipient_data["is_verified"]:
        await message.reply("Получатель ещё не прошёл проверку в боте.")
        return

    success = await db.transfer(sender_id, recipient_id, amount)

    if not success:
        await message.reply(
            "Перевод не выполнен: проверьте баланс и сумму."
        )
        return

    lang = sender_data["language"]
    recipient_name = recipient.full_name or str(recipient_id)

    await message.reply(
        tr(
            lang,
            "transfer_success",
            amount=amount,
            name=recipient_name,
        )
    )

    with suppress(Exception):
        await bot.send_message(
            recipient_id,
            tr(
                recipient_data["language"],
                "transfer_received",
                amount=amount,
            ),
        )


# ============================================================
# ЧАТЫ
# ============================================================

@router.message(F.text.in_({"💬 Чаты", "💬 Chats"}))
async def chats_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Игровой чат", url=GAME_CHAT_URL)],
            [InlineKeyboardButton(text="📢 Новости", url=NEWS_URL)],
        ]
    )

    await temp_photo(
        message,
        CHATS_PHOTO,
        tr(lang, "chats"),
        reply_markup=keyboard,
    )


# ============================================================
# ПОДДЕРЖКА
# ============================================================

@router.message(F.text.in_({"🆘 Поддержка", "🆘 Support"}))
async def support_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆘 Написать", url=SUPPORT_URL)]
        ]
    )

    await temp_photo(
        message,
        SUPPORT_PHOTO,
        tr(lang, "support"),
        reply_markup=keyboard,
    )


# ============================================================
# ЧТО НОВОГО
# ============================================================

@router.message(F.text.lower().in_({"что нового", "новости", "/news"}))
async def news_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Новости клуба", url=NEWS_URL)],
            [InlineKeyboardButton(text="🏆 Турниры", url=NEWS_URL)],
        ]
    )

    await temp_answer(
        message,
        (
            "📰 **ЧТО НОВОГО**\n\n"
            "Следите за обновлениями, активностями и объявлениями "
            "в официальном канале клуба."
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# ============================================================
# /HELP
# ============================================================

@router.message(Command("help"))
async def help_handler(message: Message):
    user_data = await db.get_user(message.from_user.id)
    lang = user_data["language"] if user_data else "ru"

    await temp_photo(
        message,
        HOW_TO_PLAY_PHOTO,
        (
            "📖 **КАК ПОЛЬЗОВАТЬСЯ БОТОМ**\n\n"
            "• Пройдите CAPTCHA после /start.\n"
            "• Откройте профиль и проверьте баланс.\n"
            "• Выберите бесплатную активность.\n"
            "• Получайте ежедневный бонус.\n"
            "• Общайтесь и следите за новостями клуба.\n\n"
            "Игры не требуют взносов и не списывают TOKENS."
        ),
        parse_mode="Markdown",
    )


# ============================================================
# АДМИН-ПРОВЕРКА
# ============================================================

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_denied(message: Message):
    await message.reply("⛔ Недостаточно прав.")


# ============================================================
# @ВЫДАТЬ — ВЫДАТЬ TOKENS ОТВЕТОМ НА СООБЩЕНИЕ
# ============================================================

@router.message(F.text.regexp(r"^@выдать\s+\d+$"))
async def admin_give_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответьте на сообщение пользователя: @выдать 100")
        return

    try:
        amount = int(message.text.split()[-1])
    except (ValueError, IndexError):
        await message.reply("Укажите сумму.")
        return

    if amount <= 0:
        await message.reply("Сумма должна быть положительной.")
        return

    target = message.reply_to_message.from_user

    await db.ensure_user(
        target.id,
        target.username or "",
        target.full_name or "",
    )

    success = await db.change_balance(target.id, amount)

    if success:
        await message.reply(
            f"✅ Начислено {amount} TOKENS пользователю {target.full_name}."
        )
    else:
        await message.reply("Не удалось выполнить начисление.")


# ============================================================
# @ДРОП — БЕСПЛАТНЫЙ РАЗОВЫЙ ДРОП СЛУЧАЙНОМУ УЧАСТНИКУ
# ============================================================

@router.message(F.text.regexp(r"^@дроп(?:\s+\d+)?$"))
async def admin_drop_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    parts = message.text.split()
    amount = 50

    if len(parts) > 1:
        try:
            amount = int(parts[1])
        except ValueError:
            await message.reply("Укажите корректную сумму.")
            return

    if amount <= 0:
        await message.reply("Сумма должна быть положительной.")
        return

    users = await db.get_all_verified_ids()

    if not users:
        await message.reply("Нет проверенных пользователей для дропа.")
        return

    winner_id = random.choice(users)
    success = await db.change_balance(winner_id, amount)

    if not success:
        await message.reply("Не удалось начислить дроп.")
        return

    await message.reply(
        f"🎁 Бесплатный дроп!\n"
        f"Пользователь ID {winner_id} получил {amount} TOKENS."
    )

    with suppress(Exception):
        await bot.send_message(
            winner_id,
            f"🎁 Вы получили бесплатный дроп: +{amount} TOKENS!",
        )


# ============================================================
# @БАН — ЗАБЛОКИРОВАТЬ ОТВЕТОМ НА СООБЩЕНИЕ
# ============================================================

@router.message(F.text == "@бан")
async def admin_ban_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответьте на сообщение пользователя командой @бан.")
        return

    target = message.reply_to_message.from_user

    await db.ensure_user(
        target.id,
        target.username or "",
        target.full_name or "",
    )
    await db.set_banned(target.id, True)

    await message.reply(
        f"⛔ Пользователь {target.full_name} заблокирован в боте."
    )


# ============================================================
# @СТАТА — СТАТИСТИКА БОТА
# ============================================================

@router.message(F.text == "@стата")
async def admin_stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    total, verified, total_balance = await db.get_stats()

    await message.reply(
        "📊 СТАТИСТИКА TOKENS CLUB\n\n"
        f"Всего пользователей: {total or 0}\n"
        f"Прошли CAPTCHA: {verified or 0}\n"
        f"Всего TOKENS на счетах: {total_balance or 0}"
    )


# ============================================================
# @БЕКАП — ВЫГРУЗИТЬ SQLITE-ФАЙЛ
# ============================================================

@router.message(F.text == "@бекап")
async def admin_backup_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_denied(message)
        return

    try:
        async with db.lock:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute("PRAGMA wal_checkpoint(FULL)")
                await conn.commit()

        if not Path(DB_PATH).exists():
            await message.reply("Файл базы данных не найден.")
            return

        backup_bytes = await asyncio.to_thread(
            Path(DB_PATH).read_bytes
        )

        await message.answer_document(
            BufferedInputFile(
                backup_bytes,
                filename=f"backup_{int(time.time())}.db",
            ),
            caption="🗄 Резервная копия базы данных.",
        )

    except Exception:
        logger.exception("Ошибка создания резервной копии")
        await message.reply("Не удалось создать резервную копию.")


# ============================================================
# ОБРАБОТЧИК ОШИБОК
# ============================================================

@router.error()
async def global_error_handler(event: ErrorEvent):
    logger.exception(
        "Ошибка обработки Telegram update",
        exc_info=event.exception,
    )

    if ADMIN_ID:
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                "⚠️ В боте произошла ошибка. Подробности находятся в логах.",
            )

    return True


# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    await db.init()

    logger.info("TOKENS | PRIVATE CLUB запускается")

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()
        logger.info("TOKENS | PRIVATE CLUB остановлен")


if __name__ == "__main__":
    asyncio.run(main())