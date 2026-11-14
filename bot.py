import asyncio
import io
import os
import random
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite
from PIL import Image, ImageDraw, ImageFont

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    User,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "tokens.sqlite3")

ASSETS = Path("assets")
PROFILE_BG = ASSETS / "profile_bg.jpg"
FONT_PATH = ASSETS / "Montserrat-Bold.ttf"

AUTO_DELETE_PRIVATE = 30
AUTO_DELETE_GAME = 15
AUTO_DELETE_GROUP = 60

PARTICIPATION_REWARD = 5
BONUS_REWARD = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tokens-club")

router = Router()


# ============================================================
# TRANSLATIONS
# ============================================================

TEXTS = {
    "ru": {
        "games": "🎰 Игры",
        "bonus": "🎁 Бонус",
        "donate": "💎 Донат",
        "profile": "👤 Профиль",
        "top": "🏆 Топ",
        "chats": "💬 Чаты",
        "support": "🆘 Поддержка",
        "language": "🌐 Язык",
        "welcome": "Добро пожаловать в TOKENS | PRIVATE CLUB!",
        "captcha_start": "Для продолжения нажмите кнопку ниже.",
        "captcha_button": "Я не робот",
        "captcha_prompt": "Введите число с картинки:",
        "captcha_wrong": "Число не совпало. Попробуйте ещё раз.",
        "captcha_ok": "Проверка пройдена!",
        "choose_game": "Выберите бесплатную игру:",
        "game_result": "Результат игры: {result}\nНаграда за участие: +{reward} TOKENS",
        "bonus_done": "Бонус получен: +{reward} TOKENS",
        "bonus_wait": "Бонус уже получен сегодня. Загляните завтра!",
        "profile_title": "ПРОФИЛЬ",
        "name": "Имя",
        "user_id": "ID",
        "rank": "Ранг",
        "balance": "Баланс",
        "rank_new": "Новичок",
        "rank_member": "Участник",
        "rank_vip": "VIP",
        "rank_elite": "Элита",
        "top_title": "ТОП ИГРОКОВ",
        "top_empty": "Пока нет участников в рейтинге.",
        "refresh": "Обновить",
        "language_changed": "Язык переключён на русский.",
        "support_text": "Поддержка: напишите администратору клуба.",
        "chats_text": "Чаты клуба:\nИгровой чат: https://t.me/tokenplays",
        "donate_text": "Раздел доната информационный. Покупки и денежные ставки в боте не поддерживаются.",
        "group_balance": "БАЛАНС",
        "group_top": "ТОП",
        "group_log": "ПОСЛЕДНИЕ СОБЫТИЯ",
        "updates": "ОБНОВЛЕНИЯ",
        "no_log": "Событий пока нет.",
        "not_verified": "Сначала пройдите проверку через /start в личных сообщениях.",
        "admin_only": "Эта команда доступна только администратору.",
        "user_not_found": "Пользователь не найден.",
        "grant_ok": "Начислено {amount} TOKENS пользователю {user_id}.",
        "drop_ok": "Бесплатный клубный бонус начислен пользователю {user_id}.",
        "ban_ok": "Пользователь {user_id} заблокирован.",
        "stats": "Пользователей: {users}\nПроверено: {verified}\nВсего TOKENS: {balance}",
        "backup_ok": "Резервная копия базы данных создана.",
        "backup_error": "Не удалось создать резервную копию.",
        "error": "Произошла ошибка. Попробуйте позже.",
        "already_claimed": "Вы уже получали этот бонус сегодня.",
        "profile_error": "Не удалось создать изображение профиля.",
        "log_empty": "История пока пуста.",
    },
    "en": {
        "games": "🎰 Games",
        "bonus": "🎁 Bonus",
        "donate": "💎 Donate",
        "profile": "👤 Profile",
        "top": "🏆 Top",
        "chats": "💬 Chats",
        "support": "🆘 Support",
        "language": "🌐 Language",
        "welcome": "Welcome to TOKENS | PRIVATE CLUB!",
        "captcha_start": "Press the button below to continue.",
        "captcha_button": "I'm not a robot",
        "captcha_prompt": "Enter the number shown in the image:",
        "captcha_wrong": "The number doesn't match. Try again.",
        "captcha_ok": "Verification completed!",
        "choose_game": "Choose a free game:",
        "game_result": "Game result: {result}\nParticipation reward: +{reward} TOKENS",
        "bonus_done": "Bonus received: +{reward} TOKENS",
        "bonus_wait": "You have already claimed today's bonus. Come back tomorrow!",
        "profile_title": "PROFILE",
        "name": "Name",
        "user_id": "ID",
        "rank": "Rank",
        "balance": "Balance",
        "rank_new": "Newcomer",
        "rank_member": "Member",
        "rank_vip": "VIP",
        "rank_elite": "Elite",
        "top_title": "PLAYER LEADERBOARD",
        "top_empty": "There are no players in the leaderboard yet.",
        "refresh": "Refresh",
        "language_changed": "Language changed to English.",
        "support_text": "Support: contact the club administrator.",
        "chats_text": "Club chats:\nGame chat: https://t.me/tokenplays",
        "donate_text": "The donation section is informational. Purchases and monetary bets are not supported.",
        "group_balance": "BALANCE",
        "group_top": "TOP",
        "group_log": "RECENT ACTIVITY",
        "updates": "UPDATES",
        "no_log": "No activity yet.",
        "not_verified": "Complete verification via /start in a private chat first.",
        "admin_only": "This command is available to the administrator only.",
        "user_not_found": "User not found.",
        "grant_ok": "Added {amount} TOKENS to user {user_id}.",
        "drop_ok": "A free club bonus was added to user {user_id}.",
        "ban_ok": "User {user_id} has been blocked.",
        "stats": "Users: {users}\nVerified: {verified}\nTotal TOKENS: {balance}",
        "backup_ok": "Database backup created.",
        "backup_error": "Could not create database backup.",
        "error": "An error occurred. Please try again later.",
        "already_claimed": "You have already claimed this bonus today.",
        "profile_error": "Could not create the profile image.",
        "log_empty": "No activity yet.",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    language = lang if lang in TEXTS else "ru"
    template = TEXTS[language].get(key, TEXTS["ru"].get(key, key))
    return template.format(**kwargs)


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()

    async def connect(self):
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        return conn

    async def init(self):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT DEFAULT '',
                        first_name TEXT DEFAULT '',
                        language TEXT DEFAULT 'ru',
                        balance INTEGER NOT NULL DEFAULT 0,
                        is_verified INTEGER NOT NULL DEFAULT 0,
                        is_banned INTEGER NOT NULL DEFAULT 0,
                        last_bonus TEXT DEFAULT '',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        description TEXT NOT NULL,
                        amount INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                await conn.commit()

    async def close(self):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                await conn.commit()

    async def ensure_user(self, user: User):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute("""
                    INSERT INTO users(user_id, username, first_name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = excluded.username,
                        first_name = excluded.first_name
                """, (
                    user.id,
                    user.username or "",
                    user.first_name or "",
                ))
                await conn.commit()

    async def get_user(self, user_id: int):
        async with self.lock:
            async with await self.connect() as conn:
                async with conn.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cursor:
                    return await cursor.fetchone()

    async def set_verified(self, user_id: int):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute(
                    "UPDATE users SET is_verified = 1 WHERE user_id = ?",
                    (user_id,),
                )
                await conn.commit()

    async def is_verified(self, user_id: int) -> bool:
        row = await self.get_user(user_id)
        return bool(row and row["is_verified"] and not row["is_banned"])

    async def is_banned(self, user_id: int) -> bool:
        row = await self.get_user(user_id)
        return bool(row and row["is_banned"])

    async def set_language(self, user_id: int, language: str):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute(
                    "UPDATE users SET language = ? WHERE user_id = ?",
                    (language, user_id),
                )
                await conn.commit()

    async def get_language(self, user_id: int) -> str:
        row = await self.get_user(user_id)
        return row["language"] if row else "ru"

    async def change_balance(
        self,
        user_id: int,
        amount: int,
        description: str = "Изменение баланса",
    ) -> bool:
        """
        Атомарное изменение баланса.
        Отрицательный баланс запрещён.
        """
        async with self.lock:
            async with await self.connect() as conn:
                try:
                    await conn.execute("BEGIN IMMEDIATE")

                    async with conn.execute(
                        "SELECT balance FROM users WHERE user_id = ?",
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if row is None:
                        await conn.rollback()
                        return False

                    new_balance = int(row["balance"]) + int(amount)

                    if new_balance < 0:
                        await conn.rollback()
                        return False

                    await conn.execute(
                        "UPDATE users SET balance = ? WHERE user_id = ?",
                        (new_balance, user_id),
                    )

                    await conn.execute("""
                        INSERT INTO activity(user_id, description, amount)
                        VALUES (?, ?, ?)
                    """, (user_id, description, amount))

                    await conn.commit()
                    return True

                except Exception:
                    await conn.rollback()
                    logger.exception("Balance transaction failed")
                    return False

    async def claim_bonus(self, user_id: int, amount: int) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")

        async with self.lock:
            async with await self.connect() as conn:
                try:
                    await conn.execute("BEGIN IMMEDIATE")

                    async with conn.execute(
                        "SELECT last_bonus FROM users WHERE user_id = ?",
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    if row is None or row["last_bonus"] == today:
                        await conn.rollback()
                        return False

                    await conn.execute("""
                        UPDATE users
                        SET balance = balance + ?, last_bonus = ?
                        WHERE user_id = ?
                    """, (amount, today, user_id))

                    await conn.execute("""
                        INSERT INTO activity(user_id, description, amount)
                        VALUES (?, ?, ?)
                    """, (user_id, "Ежедневный бонус", amount))

                    await conn.commit()
                    return True

                except Exception:
                    await conn.rollback()
                    logger.exception("Bonus transaction failed")
                    return False

    async def get_top(self, limit: int = 10):
        async with self.lock:
            async with await self.connect() as conn:
                async with conn.execute("""
                    SELECT user_id, first_name, username, balance
                    FROM users
                    WHERE is_verified = 1 AND is_banned = 0
                    ORDER BY balance DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    return await cursor.fetchall()

    async def get_activity(self, user_id: int, limit: int = 10):
        async with self.lock:
            async with await self.connect() as conn:
                async with conn.execute("""
                    SELECT description, amount, created_at
                    FROM activity
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (user_id, limit)) as cursor:
                    return await cursor.fetchall()

    async def stats(self):
        async with self.lock:
            async with await self.connect() as conn:
                async with conn.execute("""
                    SELECT
                        COUNT(*) AS users,
                        SUM(is_verified) AS verified,
                        COALESCE(SUM(balance), 0) AS balance
                    FROM users
                """) as cursor:
                    return await cursor.fetchone()

    async def ban(self, user_id: int):
        async with self.lock:
            async with await self.connect() as conn:
                await conn.execute(
                    "UPDATE users SET is_banned = 1 WHERE user_id = ?",
                    (user_id,),
                )
                await conn.commit()

    async def get_random_verified_user(self):
        async with self.lock:
            async with await self.connect() as conn:
                async with conn.execute("""
                    SELECT user_id FROM users
                    WHERE is_verified = 1 AND is_banned = 0
                    ORDER BY RANDOM()
                    LIMIT 1
                """) as cursor:
                    return await cursor.fetchone()


db = Database(DB_PATH)


# ============================================================
# AUTO DELETE
# ============================================================

async def delete_later(message: Message, seconds: int):
    try:
        await asyncio.sleep(seconds)
        await message.delete()
    except (TelegramBadRequest, Exception):
        pass


def schedule_delete(message: Message, seconds: int):
    asyncio.create_task(delete_later(message, seconds))


async def send_temporary(
    message: Message,
    text: str,
    seconds: int = AUTO_DELETE_PRIVATE,
    **kwargs,
):
    sent = await message.answer(text, **kwargs)

    if message.chat.type == ChatType.PRIVATE:
        schedule_delete(sent, seconds)

    return sent


async def send_photo_temporary(
    message: Message,
    image: bytes,
    caption: Optional[str] = None,
    seconds: int = AUTO_DELETE_PRIVATE,
):
    sent = await message.answer_photo(
        BufferedInputFile(image, filename="club.png"),
        caption=caption,
    )

    if message.chat.type == ChatType.PRIVATE:
        schedule_delete(sent, seconds)

    return sent


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard(lang: str):
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=tr(lang, "games")),
                KeyboardButton(text=tr(lang, "bonus")),
                KeyboardButton(text=tr(lang, "donate")),
            ],
            [
                KeyboardButton(text=tr(lang, "profile")),
                KeyboardButton(text=tr(lang, "top")),
                KeyboardButton(text=tr(lang, "chats")),
            ],
            [
                KeyboardButton(text=tr(lang, "support")),
                KeyboardButton(text=tr(lang, "language")),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="TOKENS | PRIVATE CLUB",
    )


def captcha_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=tr(lang, "captcha_button"),
                callback_data="captcha_begin",
            )
        ]
    ])


def games_keyboard(lang: str):
    labels = {
        "ru": [
            ("🎲 Кости", "dice"),
            ("🎯 Дартс", "darts"),
            ("🏀 Баскет", "basketball"),
            ("⚽ Футбол", "football"),
            ("🎳 Боулинг", "bowling"),
        ],
        "en": [
            ("🎲 Dice", "dice"),
            ("🎯 Darts", "darts"),
            ("🏀 Basketball", "basketball"),
            ("⚽ Football", "football"),
            ("🎳 Bowling", "bowling"),
        ],
    }

    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"game:{code}")
        for label, code in labels[lang]
    ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [buttons[0], buttons[1]],
            [buttons[2], buttons[3]],
            [buttons[4]],
        ]
    )


def top_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=tr(lang, "refresh"),
                callback_data="top_refresh",
            )
        ]
    ])


def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        ]
    ])


# ============================================================
# IMAGE HELPERS
# ============================================================

def load_font(size: int):
    try:
        if FONT_PATH.exists():
            return ImageFont.truetype(str(FONT_PATH), size=size)
    except Exception:
        pass

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def image_to_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def create_card(
    title: str,
    lines: list[str],
    width: int = 1000,
    height: int = 600,
) -> bytes:
    image = Image.new("RGB", (width, height), (12, 15, 24))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (25, 25, width - 25, height - 25),
        radius=35,
        outline=(210, 170, 80),
        width=4,
    )

    draw.text(
        (65, 55),
        title,
        font=load_font(52),
        fill=(236, 195, 105),
        stroke_width=1,
        stroke_fill=(0, 0, 0),
    )

    y = 155
    for line in lines:
        draw.text(
            (70, y),
            line,
            font=load_font(31),
            fill=(245, 245, 245),
        )
        y += 62

    draw.line(
        (65, height - 85, width - 65, height - 85),
        fill=(140, 110, 60),
        width=2,
    )

    draw.text(
        (70, height - 65),
        "TOKENS | PRIVATE CLUB",
        font=load_font(22),
        fill=(180, 180, 180),
    )

    return image_to_bytes(image)


def generate_profile_image(
    name: str,
    user_id: int,
    rank: str,
    balance: int,
    avatar_bytes: Optional[bytes] = None,
) -> bytes:
    width, height = 1100, 900

    if PROFILE_BG.exists():
        try:
            background = Image.open(PROFILE_BG).convert("RGB")
            background = background.resize((width, height))
        except Exception:
            background = Image.new("RGB", (width, height), (0, 0, 0))
    else:
        background = Image.new("RGB", (width, height), (0, 0, 0))

    image = background.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 100))
    image = Image.alpha_composite(image, overlay)

    draw = ImageDraw.Draw(image)

    # Avatar
    avatar_size = 220
    avatar_x = (width - avatar_size) // 2
    avatar_y = 45

    if avatar_bytes:
        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))

            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse(
                (0, 0, avatar_size - 1, avatar_size - 1),
                fill=255,
            )

            image.paste(
                avatar,
                (avatar_x, avatar_y),
                mask,
            )
        except Exception:
            draw.ellipse(
                (
                    avatar_x,
                    avatar_y,
                    avatar_x + avatar_size,
                    avatar_y + avatar_size,
                ),
                fill=(35, 35, 35, 255),
            )
    else:
        draw.ellipse(
            (
                avatar_x,
                avatar_y,
                avatar_x + avatar_size,
                avatar_y + avatar_size,
            ),
            fill=(35, 35, 35, 255),
        )

    draw.ellipse(
        (
            avatar_x - 7,
            avatar_y - 7,
            avatar_x + avatar_size + 7,
            avatar_y + avatar_size + 7,
        ),
        outline=(235, 190, 85, 255),
        width=9,
    )

    gold = (238, 195, 105, 255)
    white = (255, 255, 255, 255)

    title_font = load_font(48)
    text_font = load_font(39)

    def centered_text(y: int, text: str, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2

        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )

    centered_text(300, "TOKENS | PRIVATE CLUB", title_font, gold)
    centered_text(410, f"{name[:25]}", text_font, white)
    centered_text(490, f"ID: {user_id}", text_font, gold)
    centered_text(570, f"RANK: {rank}", text_font, white)
    centered_text(650, f"BALANCE: {balance:,} TOKENS", text_font, gold)

    draw.rounded_rectangle(
        (45, 35, width - 45, height - 35),
        radius=30,
        outline=(235, 190, 85, 255),
        width=4,
    )

    return image_to_bytes(image)


async def get_avatar_bytes(bot: Bot, user_id: int):
    try:
        photos = await bot.get_user_profile_photos(
            user_id=user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]
        file = await bot.get_file(photo.file_id)

        buffer = io.BytesIO()
        await bot.download_file(file.file_path, buffer)

        return buffer.getvalue()

    except Exception:
        logger.exception("Could not get avatar")
        return None


# ============================================================
# USER HELPERS
# ============================================================

async def ensure_user(message: Message):
    await db.ensure_user(message.from_user)
    return await db.get_user(message.from_user.id)


async def user_language(user_id: int):
    return await db.get_language(user_id)


async def check_access(message: Message) -> bool:
    if message.chat.type != ChatType.PRIVATE:
        return True

    if not await db.is_verified(message.from_user.id):
        lang = await user_language(message.from_user.id)
        await send_temporary(
            message,
            tr(lang, "not_verified"),
        )
        return False

    return True


def get_rank(balance: int, lang: str):
    if balance >= 10000:
        return tr(lang, "rank_elite")
    if balance >= 5000:
        return tr(lang, "rank_vip")
    if balance >= 500:
        return tr(lang, "rank_member")
    return tr(lang, "rank_new")


# ============================================================
# CAPTCHA
# ============================================================

captcha_sessions: dict[int, int] = {}


def create_captcha_image(number: int) -> bytes:
    image = Image.new("RGB", (600, 260), (15, 18, 28))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (10, 10, 590, 250),
        radius=25,
        outline=(220, 180, 85),
        width=5,
    )

    for _ in range(30):
        x1 = random.randint(0, 600)
        y1 = random.randint(0, 260)
        x2 = random.randint(0, 600)
        y2 = random.randint(0, 260)

        draw.line(
            (x1, y1, x2, y2),
            fill=(random.randint(45, 100), 65, 85),
            width=2,
        )

    draw.text(
        (180, 65),
        str(number),
        font=load_font(105),
        fill=(255, 255, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0),
    )

    return image_to_bytes(image)


@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return

    await db.ensure_user(message.from_user)

    user = await db.get_user(message.from_user.id)
    lang = user["language"] if user else "ru"

    if user and user["is_banned"]:
        return

    if user and user["is_verified"]:
        await message.answer(
            tr(lang, "welcome"),
            reply_markup=main_keyboard(lang),
        )
        return

    await message.answer(
        tr(lang, "captcha_start"),
        reply_markup=captcha_keyboard(lang),
    )


@router.callback_query(F.data == "captcha_begin")
async def captcha_begin(callback: CallbackQuery):
    await db.ensure_user(callback.from_user)

    if await db.is_verified(callback.from_user.id):
        await callback.answer()
        return

    lang = await user_language(callback.from_user.id)
    number = random.randint(1000, 9999)
    captcha_sessions[callback.from_user.id] = number

    await callback.answer()

    image = create_captcha_image(number)

    try:
        await callback.message.answer_photo(
            BufferedInputFile(image, filename="captcha.png"),
            caption=tr(lang, "captcha_prompt"),
        )
    except Exception:
        logger.exception("Captcha send failed")


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"^\d{4}$"),
)
async def captcha_answer(message: Message):
    await db.ensure_user(message.from_user)

    user_id = message.from_user.id
    lang = await user_language(user_id)

    if await db.is_verified(user_id):
        return

    expected = captcha_sessions.get(user_id)

    if expected is None:
        return

    try:
        supplied = int(message.text.strip())
    except ValueError:
        return

    if supplied != expected:
        sent = await message.answer(tr(lang, "captcha_wrong"))
        schedule_delete(sent, AUTO_DELETE_PRIVATE)
        return

    captcha_sessions.pop(user_id, None)
    await db.set_verified(user_id)

    await message.answer(
        tr(lang, "captcha_ok"),
        reply_markup=main_keyboard(lang),
    )


# ============================================================
# PROFILE
# ============================================================

@router.message(F.text.in_({"👤 Профиль", "👤 Profile"}))
async def profile_handler(message: Message, bot: Bot):
    if not await check_access(message):
        return

    user = await db.get_user(message.from_user.id)
    lang = user["language"]
    balance = int(user["balance"])
    rank = get_rank(balance, lang)

    avatar = await get_avatar_bytes(bot, message.from_user.id)

    try:
        image = await asyncio.to_thread(
            generate_profile_image,
            message.from_user.full_name,
            message.from_user.id,
            rank,
            balance,
            avatar,
        )

        await message.answer_photo(
            BufferedInputFile(image, filename="profile.png"),
        )

    except Exception:
        logger.exception("Profile image failed")
        await send_temporary(
            message,
            tr(lang, "profile_error"),
        )


# ============================================================
# GAMES
# ============================================================

GAME_EMOJIS = {
    "dice": "🎲",
    "darts": "🎯",
    "basketball": "🏀",
    "football": "⚽",
    "bowling": "🎳",
}


@router.message(F.text.in_({"🎰 Игры", "🎰 Games"}))
async def games_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)

    sent = await message.answer(
        tr(lang, "choose_game"),
        reply_markup=games_keyboard(lang),
    )

    if message.chat.type == ChatType.PRIVATE:
        schedule_delete(sent, AUTO_DELETE_PRIVATE)


@router.callback_query(F.data.startswith("game:"))
async def play_game(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id

    if not await db.is_verified(user_id):
        await callback.answer("Сначала пройдите проверку.", show_alert=True)
        return

    if await db.is_banned(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    game = callback.data.split(":", 1)[1]

    if game not in GAME_EMOJIS:
        await callback.answer()
        return

    await callback.answer()

    emoji = GAME_EMOJIS[game]

    try:
        sent = await bot.send_dice(
            chat_id=callback.message.chat.id,
            emoji=emoji,
        )

        await asyncio.sleep(3)

        # Бесплатное участие: нет ставки, списания или выплаты x2.
        await db.change_balance(
            user_id,
            PARTICIPATION_REWARD,
            f"Бесплатная игра: {game}",
        )

        lang = await user_language(user_id)
        value = sent.dice.value if sent.dice else "—"

        result_text = tr(
            lang,
            "game_result",
            result=value,
            reward=PARTICIPATION_REWARD,
        )

        result_message = await bot.send_message(
            callback.message.chat.id,
            result_text,
        )

        if callback.message.chat.type == ChatType.PRIVATE:
            schedule_delete(sent, AUTO_DELETE_GAME)
            schedule_delete(result_message, AUTO_DELETE_GAME)

    except Exception:
        logger.exception("Game error")
        lang = await user_language(user_id)

        try:
            await bot.send_message(
                callback.message.chat.id,
                tr(lang, "error"),
            )
        except Exception:
            pass


# ============================================================
# BONUS
# ============================================================

@router.message(F.text.in_({"🎁 Бонус", "🎁 Bonus"}))
async def bonus_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)

    success = await db.claim_bonus(
        message.from_user.id,
        BONUS_REWARD,
    )

    if success:
        text = tr(lang, "bonus_done", reward=BONUS_REWARD)
    else:
        text = tr(lang, "bonus_wait")

    await send_temporary(message, text)


# ============================================================
# DONATE / SUPPORT / CHATS
# ============================================================

@router.message(F.text.in_({"💎 Донат", "💎 Donate"}))
async def donate_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)
    await send_temporary(message, tr(lang, "donate_text"))


@router.message(F.text.in_({"💬 Чаты", "💬 Chats"}))
async def chats_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)
    await send_temporary(message, tr(lang, "chats_text"))


@router.message(F.text.in_({"🆘 Поддержка", "🆘 Support"}))
async def support_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)
    await send_temporary(message, tr(lang, "support_text"))


# ============================================================
# LANGUAGE
# ============================================================

@router.message(F.text.in_({"🌐 Язык", "🌐 Language"}))
async def language_handler(message: Message):
    if not await check_access(message):
        return

    await send_temporary(
        message,
        "Выберите язык / Choose language:",
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def language_callback(callback: CallbackQuery):
    language = callback.data.split(":", 1)[1]

    if language not in ("ru", "en"):
        await callback.answer()
        return

    await db.set_language(callback.from_user.id, language)
    await callback.answer(tr(language, "language_changed"))

    try:
        await callback.message.answer(
            tr(language, "language_changed"),
            reply_markup=main_keyboard(language),
        )
    except Exception:
        pass


# ============================================================
# TOP
# ============================================================

async def build_top_image(lang: str):
    rows = await db.get_top(10)

    lines = []

    for index, row in enumerate(rows, start=1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        lines.append(
            f"{index}. {name[:22]} — {row['balance']:,} TOKENS"
        )

    if not lines:
        lines.append(tr(lang, "top_empty"))

    return create_card(
        tr(lang, "top_title"),
        lines,
        height=max(600, 200 + len(lines) * 65),
    )


@router.message(F.text.in_({"🏆 Топ", "🏆 Top"}))
async def top_handler(message: Message):
    if not await check_access(message):
        return

    lang = await user_language(message.from_user.id)
    image = await build_top_image(lang)

    sent = await message.answer_photo(
        BufferedInputFile(image, filename="top.png"),
        reply_markup=top_keyboard(lang),
    )

    if message.chat.type == ChatType.PRIVATE:
        schedule_delete(sent, AUTO_DELETE_PRIVATE)


@router.callback_query(F.data == "top_refresh")
async def top_refresh(callback: CallbackQuery):
    if not await db.is_verified(callback.from_user.id):
        await callback.answer()
        return

    lang = await user_language(callback.from_user.id)
    image = await build_top_image(lang)

    try:
        await callback.message.edit_media(
            media=__import__("aiogram").types.InputMediaPhoto(
                media=BufferedInputFile(image, filename="top.png"),
            ),
            reply_markup=top_keyboard(lang),
        )
    except Exception:
        await callback.answer()
        return

    await callback.answer()


# ============================================================
# GROUP CARDS
# ============================================================

async def group_send_card(
    message: Message,
    title: str,
    lines: list[str],
):
    image = create_card(title, lines)

    sent = await message.answer_photo(
        BufferedInputFile(image, filename="club-card.png"),
    )

    if message.chat.type != ChatType.PRIVATE:
        schedule_delete(sent, AUTO_DELETE_GROUP)

    return sent


@router.message(F.text.regexp(r"(?i)^б$"))
async def group_balance(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    await db.ensure_user(message.from_user)

    row = await db.get_user(message.from_user.id)
    lang = row["language"] if row else "ru"

    if not row or not row["is_verified"]:
        await group_send_card(
            message,
            "TOKENS",
            [tr(lang, "not_verified")],
        )
        return

    await group_send_card(
        message,
        tr(lang, "group_balance"),
        [
            f"{message.from_user.full_name}",
            f"ID: {message.from_user.id}",
            f"{row['balance']:,} TOKENS",
        ],
    )


@router.message(F.text.regexp(r"(?i)^топ$"))
async def group_top(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    await db.ensure_user(message.from_user)
    lang = await user_language(message.from_user.id)

    rows = await db.get_top(10)

    lines = []

    for index, row in enumerate(rows, start=1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        lines.append(
            f"{index}. {name[:22]} — {row['balance']:,}"
        )

    if not lines:
        lines.append(tr(lang, "top_empty"))

    await group_send_card(
        message,
        tr(lang, "group_top"),
        lines,
    )


@router.message(F.text.regexp(r"(?i)^лог$"))
async def group_log(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    await db.ensure_user(message.from_user)
    lang = await user_language(message.from_user.id)

    if not await db.is_verified(message.from_user.id):
        await group_send_card(
            message,
            tr(lang, "group_log"),
            [tr(lang, "not_verified")],
        )
        return

    rows = await db.get_activity(message.from_user.id, 7)

    lines = []

    for row in rows:
        sign = "+" if row["amount"] > 0 else ""
        lines.append(
            f"{row['description'][:30]}: {sign}{row['amount']}"
        )

    if not lines:
        lines.append(tr(lang, "log_empty"))

    await group_send_card(
        message,
        tr(lang, "group_log"),
        lines,
    )


@router.message(F.text.regexp(r"(?i)^что нового$"))
async def group_updates(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return

    await db.ensure_user(message.from_user)
    lang = await user_language(message.from_user.id)

    lines = [
        "• Бесплатные мини-игры",
        "• Ежедневный бонус",
        "• Профили и рейтинг",
        "• Поддержка двух языков",
    ]

    if lang == "en":
        lines = [
            "• Free mini-games",
            "• Daily bonus",
            "• Profiles and leaderboard",
            "• Two language options",
        ]

    await group_send_card(
        message,
        tr(lang, "updates"),
        lines,
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

def is_admin(user_id: int):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_check(message: Message) -> bool:
    if not is_admin(message.from_user.id):
        lang = await user_language(message.from_user.id)
        await send_temporary(message, tr(lang, "admin_only"))
        return False

    return True


@router.message(F.text.startswith("@выдать"))
async def admin_grant(message: Message):
    if not await admin_check(message):
        return

    parts = message.text.split()

    if len(parts) != 3:
        await send_temporary(
            message,
            "Использование: @выдать USER_ID КОЛИЧЕСТВО",
        )
        return

    try:
        user_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await send_temporary(message, "Неверные аргументы.")
        return

    if amount <= 0 or amount > 1_000_000:
        await send_temporary(message, "Количество должно быть от 1 до 1000000.")
        return

    row = await db.get_user(user_id)

    if not row:
        await send_temporary(
            message,
            tr("ru", "user_not_found"),
        )
        return

    await db.change_balance(
        user_id,
        amount,
        "Начисление администратором",
    )

    await send_temporary(
        message,
        tr(
            "ru",
            "grant_ok",
            amount=amount,
            user_id=user_id,
        ),
    )


@router.message(F.text.startswith("@дроп"))
async def admin_drop(message: Message):
    if not await admin_check(message):
        return

    # Бесплатное начисление случайному проверенному участнику.
    # Участники не платят за участие и ничего не теряют.
    row = await db.get_random_verified_user()

    if not row:
        await send_temporary(message, "Нет проверенных участников.")
        return

    user_id = int(row["user_id"])

    await db.change_balance(
        user_id,
        BONUS_REWARD,
        "Бесплатный клубный бонус",
    )

    await send_temporary(
        message,
        tr("ru", "drop_ok", user_id=user_id),
    )


@router.message(F.text.startswith("@бан"))
async def admin_ban(message: Message):
    if not await admin_check(message):
        return

    parts = message.text.split()

    if len(parts) != 2:
        await send_temporary(message, "Использование: @бан USER_ID")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await send_temporary(message, "Неверный ID.")
        return

    await db.ban(user_id)

    await send_temporary(
        message,
        tr("ru", "ban_ok", user_id=user_id),
    )


@router.message(F.text == "@стата")
async def admin_stats(message: Message):
    if not await admin_check(message):
        return

    stats = await db.stats()

    text = tr(
        "ru",
        "stats",
        users=stats["users"] or 0,
        verified=stats["verified"] or 0,
        balance=stats["balance"] or 0,
    )

    await send_temporary(message, text)


@router.message(F.text == "@бекап")
async def admin_backup(message: Message):
    if not await admin_check(message):
        return

    backup_name = (
        f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
    )

    try:
        async with db.lock:
            async with await db.connect() as source:
                async with aiosqlite.connect(backup_name) as target:
                    await source.backup(target)

        await message.answer_document(
            BufferedInputFile(
                Path(backup_name).read_bytes(),
                filename=backup_name,
            ),
            caption=tr("ru", "backup_ok"),
        )

        try:
            os.remove(backup_name)
        except OSError:
            pass

    except Exception:
        logger.exception("Backup failed")
        await send_temporary(
            message,
            tr("ru", "backup_error"),
        )


# ============================================================
# UNKNOWN PRIVATE MESSAGE
# ============================================================

@router.message(F.chat.type == ChatType.PRIVATE)
async def private_fallback(message: Message):
    if not message.text:
        return

    await db.ensure_user(message.from_user)

    if not await db.is_verified(message.from_user.id):
        return

    lang = await user_language(message.from_user.id)

    # Reply-клавиатура остаётся доступной.
    sent = await message.answer(
        tr(lang, "welcome"),
        reply_markup=main_keyboard(lang),
    )

    # Это сообщение одновременно является главным меню,
    # поэтому его не удаляем.


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Установите переменную окружения BOT_TOKEN."
        )

    await db.init()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )

    dp = Dispatcher()
    dp.include_router(router)

    try:
        logger.info("TOKENS | PRIVATE CLUB starting")
        await dp.start_polling(bot)

    finally:
        await db.close()
        await bot.session.close()
        logger.info("TOKENS | PRIVATE CLUB stopped")


if __name__ == "__main__":
    asyncio.run(main())