import asyncio
import logging
import os
import random
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ============================================================
# TOKENS BOT
# Python 3.10+
#
# Установка:
# pip install aiogram aiosqlite aiohttp pillow
#
# Переменные окружения:
# BOT_TOKEN       — токен Telegram-бота
# ADMIN_ID        — ID администратора
# NEWS_CHANNEL    — канал для проверки подписки
# PORT            — порт health-сервера (Render)
# SUPPORT_USERNAME — username поддержки
#
# Пример NEWS_CHANNEL:
# @TokenCasinoTournaments
#
# Важно:
# 1. Бот должен быть администратором канала или иметь возможность
#    получать информацию об участниках канала.
# 2. Для Telegram Stars используется валюта XTR.
# 3. Игры и рулетка работают только в группах.
# 4. Все ссылки пользователям выдаются через inline-кнопки.
# ============================================================


# ------------------------- CONFIG ----------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_IDS = set()

for item in ADMIN_ID_RAW.split(","):
    item = item.strip()
    if item.isdigit():
        ADMIN_IDS.add(int(item))

NEWS_CHANNEL = os.getenv(
    "NEWS_CHANNEL",
    "@TokenCasinoTournaments",
).strip()

PORT = int(os.getenv("PORT", "10000"))

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "@tokens_support",
).strip()

DATABASE_PATH = os.getenv("DATABASE_PATH", "tokens.sqlite3")

ASSETS_DIR = Path("assets")

PROFILE_BG = ASSETS_DIR / "profile_bg.jpg"
TOP_BG = ASSETS_DIR / "top.jpg"
REF_BG = ASSETS_DIR / "ref.jpg"
HOW_TO_PLAY_BG = ASSETS_DIR / "how_to_play.jpg"
ROULETTE_GIF = ASSETS_DIR / "roulette.gif"
WELCOME_BG = ASSETS_DIR / "welcome.jpg"
ERROR_SUB_BG = ASSETS_DIR / "error_sub.jpg"

FONT_BOLD_PATH = ASSETS_DIR / "Montserrat-Bold.ttf"
FONT_REGULAR_PATH = ASSETS_DIR / "Montserrat-Regular.ttf"

BONUS_COOLDOWN = 12 * 60 * 60
CAPTCHA_BAN_SECONDS = 12 * 60 * 60

PRIVATE_DELETE_SECONDS = 30
GAME_DELETE_SECONDS = 15
GROUP_DELETE_SECONDS = 60

START_BONUS = 5000
REFERRAL_REWARD = 5000
NORMAL_BONUS = 2500
BONUS_BALANCE_LIMIT = 100000

VIP_PRICE_PER_DAY = 5

MAX_ROULETTE_RANGES = 100
ROULETTE_BET_MAX_AGE = 5 * 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("TOKENS")


# ------------------------- GLOBALS ---------------------------

bot: Optional[Bot] = None
dp = Dispatcher()

db_conn: Optional[aiosqlite.Connection] = None

db_lock = asyncio.Lock()
roulette_lock = asyncio.Lock()

bot_username = "TOKENS_BOT"
bot_display_name = "TOKENS"

pending_captchas = {}
captcha_bans = {}

roulette_rounds = {}
roulette_history = {}

last_user_bets = {}

background_tasks = set()

http_runner = None


# ------------------------- TEXTS -----------------------------

TEXTS = {
    "ru": {
        "menu_play": "🎮 Как играть?",
        "menu_bonus": "🎁 Бонус",
        "menu_donate": "💎 Донат",
        "menu_profile": "👤 Профиль",
        "menu_top": "🏆 Топ",
        "menu_ref": "🔗 Рефералка",

        "welcome": "Добро пожаловать в TOKENS!",
        "captcha_prompt": "Введи цифры с картинки. У тебя 3 попытки.",
        "captcha_wrong": "Неверный код. Попробуй ещё раз.",
        "captcha_banned": "Слишком много ошибок. Доступ временно ограничен на 12 часов.",
        "captcha_success": "Капча пройдена! На твой баланс начислено 5000 TOKENS.",
        "captcha_expired": "Время проверки истекло. Нажми /start ещё раз.",

        "bonus_received": "🎁 Ты получил {amount} TOKENS!",
        "bonus_cooldown": "Бонус уже получен. Следующий будет доступен через {time}.",
        "bonus_balance_limit": "Бонус недоступен: баланс должен быть не больше 100 000 TOKENS.",
        "subscribe_required": "Чтобы получить бонус, подпишись на наш канал.",
        "subscribe_check_error": "Не удалось проверить подписку. Попробуй ещё раз позже.",

        "profile_title": "ПРОФИЛЬ TOKENS",
        "profile_name": "Имя",
        "profile_balance": "Баланс",
        "profile_bets": "Ставки",
        "profile_wins": "Выигрыши",
        "profile_losses": "Проигрыши",
        "profile_games": "Игры",

        "settings_title": "Настройки",
        "settings_language": "Язык",
        "settings_transfers": "Запретить переводы",
        "settings_on": "Включено",
        "settings_off": "Выключено",

        "vip_title": "VIP TOKENS",
        "vip_description": (
            "VIP даёт дополнительные возможности:\n\n"
            "• Бонусы увеличенного размера\n"
            "• Автоматический сбор бонуса\n"
            "• Скрытие баланса в топе\n"
            "• +2.5% к начислению доната\n"
            "• +2.5% возврата от дневных проигрышей\n"
            "• VIP-значок в профиле"
        ),
        "vip_active": "VIP активен до {date}.",
        "vip_payment": "Оплата VIP: {days} дн.",

        "donate_title": "💎 Покупка TOKENS",
        "donate_description": "Выбери количество Telegram Stars.",
        "donate_success": "Оплата прошла успешно! Начислено {amount} TOKENS. Спасибо!",
        "donate_failed": "Не удалось обработать платёж.",

        "top_title": "🏆 ТОП ИГРОКОВ",
        "ref_title": "РЕФЕРАЛЬНАЯ ПРОГРАММА",
        "ref_invited": "Приглашено",
        "ref_earned": "Заработано",

        "how_title": "🎮 Как играть?",
        "games_title": "Выбери игру",
        "commands_title": "Команды",
        "chats_title": "Наши чаты",

        "game_group_only": (
            "Вижу, ты хочешь поиграть? Заходи в наш игровой чат и играй сколько хочешь!"
        ),
        "game_usage": "Формат: кости 1000",
        "game_not_enough": "Недостаточно TOKENS для этой ставки.",
        "game_result_win": "🎉 Победа! Начислено {amount} TOKENS.",
        "game_result_loss": "😔 Не повезло. Ставка проиграна.",
        "game_invalid_bet": "Ставка должна быть положительным числом.",
        "game_unknown": "Неизвестная игра.",

        "roulette_started": "🎡 Приём ставок открыт!",
        "roulette_no_bets": "У вас нет ставок.",
        "roulette_running": "Рулетка уже крутится!",
        "roulette_accepted": "Ставка принята.",
        "roulette_result": "🎡 Выпало: {number} ({color})",
        "roulette_repeat": "🔄 Повторить",
        "roulette_double": "⏫ Удвоить",

        "transfer_success": "Перевод {amount} TOKENS выполнен.",
        "transfer_failed": "Не удалось выполнить перевод.",
        "transfer_blocked": "Один из пользователей запретил переводы.",
        "transfer_usage": "Использование: перевод @username 1000 или ответом: перевод 1000.",

        "admin_denied": "Недостаточно прав.",
        "admin_help": "Команды администратора",
        "admin_user_not_found": "Пользователь не найден.",
        "admin_success": "Готово.",
        "admin_usage": "Неверный формат команды.",

        "bot_here": "На месте!",
        "new_updates": "ОБНОВЛЕНИЯ\n\n• Обновлены игры\n• Улучшена рулетка\n• Добавлены настройки профиля",
    },

    "en": {
        "menu_play": "🎮 How to play?",
        "menu_bonus": "🎁 Bonus",
        "menu_donate": "💎 Donate",
        "menu_profile": "👤 Profile",
        "menu_top": "🏆 Top",
        "menu_ref": "🔗 Referral",

        "welcome": "Welcome to TOKENS!",
        "captcha_prompt": "Enter the digits from the image. You have 3 attempts.",
        "captcha_wrong": "Incorrect code. Try again.",
        "captcha_banned": "Too many attempts. Access is restricted for 12 hours.",
        "captcha_success": "Captcha passed! 5000 TOKENS have been credited.",
        "captcha_expired": "Captcha expired. Send /start again.",

        "profile_title": "TOKENS PROFILE",
        "profile_name": "Name",
        "profile_balance": "Balance",
        "profile_bets": "Bets",
        "profile_wins": "Wins",
        "profile_losses": "Losses",
        "profile_games": "Games",

        "settings_title": "Settings",
        "settings_language": "Language",
        "settings_transfers": "Block transfers",
        "settings_on": "Enabled",
        "settings_off": "Disabled",

        "vip_title": "TOKENS VIP",
        "vip_description": (
            "VIP benefits:\n\n"
            "• Increased bonuses\n"
            "• Automatic bonus collection\n"
            "• Hide balance in leaderboard\n"
            "• +2.5% donation reward\n"
            "• +2.5% daily loss cashback\n"
            "• VIP profile badge"
        ),

        "donate_title": "💎 Buy TOKENS",
        "donate_description": "Choose Telegram Stars amount.",
        "donate_success": "Payment successful! {amount} TOKENS credited. Thank you!",

        "top_title": "🏆 TOP PLAYERS",
        "ref_title": "REFERRAL PROGRAM",
        "ref_invited": "Invited",
        "ref_earned": "Earned",

        "how_title": "🎮 How to play?",
        "games_title": "Choose a game",
        "commands_title": "Commands",
        "chats_title": "Our chats",

        "game_group_only": "Join our gaming chat to play!",
        "game_usage": "Format: dice 1000",
        "game_not_enough": "Not enough TOKENS.",
        "game_result_win": "🎉 You won! {amount} TOKENS credited.",
        "game_result_loss": "😔 You lost your bet.",
        "game_invalid_bet": "Bet must be a positive number.",

        "roulette_started": "🎡 Betting is open!",
        "roulette_no_bets": "There are no bets.",
        "roulette_running": "Roulette is already running!",
        "roulette_accepted": "Bet accepted.",

        "transfer_success": "Transfer of {amount} TOKENS completed.",
        "transfer_failed": "Transfer failed.",
        "transfer_blocked": "Transfers are disabled for one of the users.",

        "admin_denied": "Permission denied.",
        "admin_help": "Administrator commands",
        "admin_user_not_found": "User not found.",
        "admin_success": "Done.",
        "admin_usage": "Invalid command.",

        "bot_here": "I'm here!",
        "new_updates": "UPDATES\n\n• Games updated\n• Roulette improved\n• Profile settings added",
    },
}


# ------------------------- HELPERS ---------------------------

def now_ts() -> int:
    return int(time.time())


def utc_datetime(timestamp: Optional[int] = None) -> datetime:
    if timestamp is None:
        timestamp = now_ts()

    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours} ч. {minutes} мин."

    if minutes:
        return f"{minutes} мин."

    return f"{seconds} сек."


def tr(language: str, key: str, **kwargs) -> str:
    language = language if language in TEXTS else "ru"

    value = TEXTS[language].get(
        key,
        TEXTS["ru"].get(key, key),
    )

    try:
        return value.format(**kwargs)
    except Exception:
        return value


def user_language(user_data: Optional[dict]) -> str:
    if not user_data:
        return "ru"

    language = user_data.get("language", "ru")

    if language not in ("ru", "en"):
        return "ru"

    return language


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_group(message: Message) -> bool:
    return message.chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    )


def clean_username(username: Optional[str]) -> str:
    if not username:
        return "Без username"

    return username.lstrip("@")


def safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def make_inline(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button[0],
                    callback_data=button[1],
                    url=button[2] if len(button) > 2 else None,
                )
                for button in row
            ]
            for row in rows
        ]
    )


def schedule_task(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


async def auto_delete_message(
    message: Optional[Message],
    seconds: int,
):
    if not message:
        return

    await asyncio.sleep(seconds)

    try:
        await message.delete()
    except Exception:
        pass


async def delete_after_send(
    message: Optional[Message],
    seconds: int,
):
    if message:
        schedule_task(auto_delete_message(message, seconds))


async def send_temporary(
    message: Message,
    text: str,
    seconds: Optional[int] = None,
    reply_markup=None,
):
    sent = await message.answer(
        text,
        reply_markup=reply_markup,
    )

    if seconds is None:
        seconds = (
            PRIVATE_DELETE_SECONDS
            if is_private(message)
            else GROUP_DELETE_SECONDS
        )

    await delete_after_send(sent, seconds)
    return sent


async def send_photo_or_text(
    message: Message,
    image_path: Path,
    caption: str,
    reply_markup=None,
    delete_seconds: Optional[int] = None,
):
    if image_path.exists():
        try:
            sent = await message.answer_photo(
                BufferedInputFile(
                    image_path.read_bytes(),
                    filename=image_path.name,
                ),
                caption=caption,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            logger.warning("Cannot send image %s: %s", image_path, exc)
            sent = await message.answer(
                caption,
                reply_markup=reply_markup,
            )
    else:
        sent = await message.answer(
            caption,
            reply_markup=reply_markup,
        )

    if delete_seconds is not None:
        await delete_after_send(sent, delete_seconds)

    return sent


# ------------------------- IMAGE HELPERS ---------------------

def load_font(size: int, bold: bool = True):
    candidates = []

    if bold:
        candidates.append(FONT_BOLD_PATH)
    else:
        candidates.append(FONT_REGULAR_PATH)

    candidates.extend([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("arial.ttf"),
    ])

    for candidate in candidates:
        try:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
        except Exception:
            continue

    return ImageFont.load_default()


def make_gradient(
    width: int,
    height: int,
    color_top=(13, 17, 35),
    color_bottom=(34, 12, 55),
):
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)

        color = tuple(
            int(
                color_top[i] * (1 - ratio)
                + color_bottom[i] * ratio
            )
            for i in range(3)
        )

        draw.line(
            (0, y, width, y),
            fill=color,
        )

    return image


def add_noise(image: Image.Image, amount: int = 500):
    draw = ImageDraw.Draw(image)

    width, height = image.size

    for _ in range(amount):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)

        shade = random.randint(50, 240)

        draw.point(
            (x, y),
            fill=(shade, shade, shade),
        )

    return image


def generate_captcha_image(code: str) -> bytes:
    width, height = 300, 100

    image = make_gradient(
        width,
        height,
        (16, 20, 42),
        (43, 14, 65),
    )

    draw = ImageDraw.Draw(image)

    for _ in range(18):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)

        color = (
            random.randint(70, 170),
            random.randint(50, 150),
            random.randint(100, 220),
        )

        draw.line(
            (x1, y1, x2, y2),
            fill=color,
            width=random.randint(1, 3),
        )

    font = load_font(58)

    x = 37

    for char in code:
        layer = Image.new("RGBA", (70, 90), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)

        layer_draw.text(
            (8, random.randint(0, 12)),
            char,
            font=font,
            fill=(
                random.randint(210, 255),
                random.randint(210, 255),
                random.randint(210, 255),
                255,
            ),
            stroke_width=1,
            stroke_fill=(10, 10, 20, 255),
        )

        layer = layer.rotate(
            random.randint(-18, 18),
            resample=Image.Resampling.BICUBIC,
        )

        image.paste(
            layer,
            (x, random.randint(2, 10)),
            layer,
        )

        x += 58

    add_noise(image, 600)

    image = image.filter(
        ImageFilter.GaussianBlur(0.25)
    )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def generate_error_image(title: str = "ОШИБКА") -> bytes:
    image = make_gradient(
        640,
        360,
        (18, 18, 30),
        (43, 10, 25),
    )

    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (240, 25, 400, 185),
        outline=(255, 65, 75),
        width=13,
    )

    draw.line(
        (275, 60, 365, 150),
        fill=(255, 65, 75),
        width=15,
    )

    draw.line(
        (365, 60, 275, 150),
        fill=(255, 65, 75),
        width=15,
    )

    font = load_font(30)

    bbox = draw.textbbox(
        (0, 0),
        title,
        font=font,
    )

    text_width = bbox[2] - bbox[0]

    draw.text(
        ((640 - text_width) / 2, 235),
        title,
        font=font,
        fill=(255, 235, 235),
    )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def generate_success_image(title: str = "УСПЕШНО") -> bytes:
    image = make_gradient(
        640,
        360,
        (8, 35, 31),
        (10, 60, 50),
    )

    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (240, 25, 400, 185),
        outline=(60, 240, 160),
        width=13,
    )

    draw.line(
        (275, 105, 315, 145),
        fill=(60, 240, 160),
        width=15,
    )

    draw.line(
        (315, 145, 370, 65),
        fill=(60, 240, 160),
        width=15,
    )

    font = load_font(30)

    bbox = draw.textbbox((0, 0), title, font=font)
    text_width = bbox[2] - bbox[0]

    draw.text(
        ((640 - text_width) / 2, 235),
        title,
        font=font,
        fill=(230, 255, 240),
    )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def generate_profile_image(
    name: str,
    username: str,
    balance: int,
    bets: int,
    wins: int,
    losses: int,
    games: int,
    avatar_bytes: Optional[bytes] = None,
) -> bytes:
    width, height = 900, 650

    if PROFILE_BG.exists():
        try:
            image = Image.open(PROFILE_BG).convert("RGB")
            image = image.resize((width, height))
        except Exception:
            image = make_gradient(width, height)
    else:
        image = make_gradient(width, height)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 120))
    image = Image.alpha_composite(
        image.convert("RGBA"),
        overlay,
    )

    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    name_font = load_font(30)
    text_font = load_font(26)

    draw.text(
        (40, 25),
        bot_display_name,
        font=title_font,
        fill=(255, 220, 90),
    )

    avatar_size = 150
    avatar_x = 40
    avatar_y = 105

    avatar = None

    if avatar_bytes:
        try:
            avatar = Image.open(
                BytesIO(avatar_bytes)
            ).convert("RGBA")

            avatar = avatar.resize(
                (avatar_size, avatar_size),
            )
        except Exception:
            avatar = None

    if avatar is None:
        avatar = Image.new(
            "RGBA",
            (avatar_size, avatar_size),
            (55, 65, 100, 255),
        )

        avatar_draw = ImageDraw.Draw(avatar)
        avatar_draw.ellipse(
            (10, 10, 140, 140),
            fill=(85, 110, 160, 255),
        )

    mask = Image.new(
        "L",
        (avatar_size, avatar_size),
        0,
    )

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

    draw = ImageDraw.Draw(image)

    draw.text(
        (225, 120),
        name[:35],
        font=name_font,
        fill=(255, 255, 255),
    )

    draw.text(
        (225, 165),
        username[:35],
        font=text_font,
        fill=(190, 200, 225),
    )

    lines = [
        f"Баланс: {balance:,} TOKENS",
        f"Ставки: {bets:,} TOKENS",
        f"Выигрыши: {wins:,} TOKENS",
        f"Проигрыши: {losses:,} TOKENS",
        f"Игры: {games:,}",
    ]

    y = 310

    for line in lines:
        draw.text(
            (50, y),
            line,
            font=text_font,
            fill=(245, 245, 255),
        )

        y += 60

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def generate_top_image(rows: list) -> bytes:
    width, height = 900, 900

    if TOP_BG.exists():
        try:
            image = Image.open(TOP_BG).convert("RGB")
            image = image.resize((width, height))
        except Exception:
            image = make_gradient(width, height)
    else:
        image = make_gradient(width, height)

    image = Image.alpha_composite(
        image.convert("RGBA"),
        Image.new("RGBA", (width, height), (0, 0, 0, 150)),
    )

    draw = ImageDraw.Draw(image)

    title_font = load_font(42)
    row_font = load_font(25)

    draw.text(
        (40, 25),
        "ТОП-10 TOKENS",
        font=title_font,
        fill=(255, 220, 90),
    )

    y = 110

    for index, row in enumerate(rows, 1):
        username = row["username"] or row["full_name"] or str(row["user_id"])

        if row["vip_hide_top"]:
            balance = "Скрыт"
        else:
            balance = f'{row["balance"]:,}'

        text = f"{index}. {username[:22]} — {balance} TOKENS"

        draw.text(
            (45, y),
            text,
            font=row_font,
            fill=(255, 255, 255),
        )

        y += 68

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def generate_ref_image(
    invited: int,
    earned: int,
    referral_link: str,
) -> bytes:
    width, height = 900, 550

    if REF_BG.exists():
        try:
            image = Image.open(REF_BG).convert("RGB")
            image = image.resize((width, height))
        except Exception:
            image = make_gradient(width, height)
    else:
        image = make_gradient(width, height)

    image = Image.alpha_composite(
        image.convert("RGBA"),
        Image.new("RGBA", (width, height), (0, 0, 0, 135)),
    )

    draw = ImageDraw.Draw(image)

    title_font = load_font(38)
    text_font = load_font(28)

    draw.text(
        (45, 45),
        "РЕФЕРАЛЬНАЯ ПРОГРАММА",
        font=title_font,
        fill=(255, 220, 90),
    )

    draw.text(
        (55, 180),
        f"Приглашено: {invited}",
        font=text_font,
        fill=(255, 255, 255),
    )

    draw.text(
        (55, 250),
        f"Заработано: {earned:,} TOKENS",
        font=text_font,
        fill=(255, 255, 255),
    )

    draw.text(
        (55, 350),
        "Приглашай друзей и получай награды!",
        font=text_font,
        fill=(180, 230, 255),
    )

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def generate_scanner_image(data: dict) -> bytes:
    image = make_gradient(
        900,
        650,
        (8, 20, 35),
        (18, 35, 55),
    )

    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    text_font = load_font(23)

    draw.text(
        (35, 25),
        "TOKENS USER SCANNER",
        font=title_font,
        fill=(90, 230, 255),
    )

    fields = [
        ("ID", data.get("user_id")),
        ("Username", data.get("username")),
        ("Имя", data.get("full_name")),
        ("Баланс", data.get("balance")),
        ("Донат", data.get("donated_stars")),
        ("Рефералы", data.get("referrals")),
        ("VIP до", data.get("vip_until")),
        ("Бан", data.get("is_banned")),
        ("Язык", data.get("language")),
        ("Создан", data.get("created_at")),
    ]

    y = 110

    for label, value in fields:
        draw.text(
            (45, y),
            f"{label}: {value}",
            font=text_font,
            fill=(235, 245, 255),
        )

        y += 48

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# ------------------------- DATABASE --------------------------

async def init_db():
    global db_conn

    db_conn = await aiosqlite.connect(DATABASE_PATH)
    db_conn.row_factory = aiosqlite.Row

    await db_conn.execute("PRAGMA journal_mode=WAL")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await db_conn.execute("PRAGMA synchronous=NORMAL")
    await db_conn.execute("PRAGMA busy_timeout=5000")

    await db_conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT NOT NULL DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 0,
            donated_stars INTEGER NOT NULL DEFAULT 0,
            referrals INTEGER NOT NULL DEFAULT 0,
            referral_earned INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER,
            referral_paid INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            ban_until INTEGER NOT NULL DEFAULT 0,
            vip_until INTEGER NOT NULL DEFAULT 0,
            language TEXT NOT NULL DEFAULT 'ru',
            transfers_blocked INTEGER NOT NULL DEFAULT 0,
            vip_hide_top INTEGER NOT NULL DEFAULT 0,
            vip_auto_bonus INTEGER NOT NULL DEFAULT 1,
            captcha_verified INTEGER NOT NULL DEFAULT 0,
            captcha_attempts INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0,
            last_seen INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS game_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER,
            game TEXT NOT NULL,
            bet INTEGER NOT NULL DEFAULT 0,
            win INTEGER NOT NULL DEFAULT 0,
            result TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bonus (
            user_id INTEGER PRIMARY KEY,
            last_claim INTEGER NOT NULL DEFAULT 0,
            subscription_checked INTEGER NOT NULL DEFAULT 0,
            subscription_checked_at INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payload TEXT NOT NULL UNIQUE,
            stars INTEGER NOT NULL,
            tokens INTEGER NOT NULL,
            payment_type TEXT NOT NULL DEFAULT 'donate',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            paid_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS roulette_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            stake INTEGER NOT NULL,
            selection TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            settled INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS roulette_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            number INTEGER NOT NULL,
            color TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS captcha_bans (
            user_id INTEGER PRIMARY KEY,
            until_ts INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_user
        ON transactions(user_id);

        CREATE INDEX IF NOT EXISTS idx_game_log_user
        ON game_log(user_id);

        CREATE INDEX IF NOT EXISTS idx_roulette_round
        ON roulette_bets(round_id);
        """
    )

    await db_conn.commit()

    logger.info("Database initialized")


async def close_db():
    global db_conn

    if db_conn is not None:
        await db_conn.close()
        db_conn = None


async def db_fetchone(query: str, params=()):
    async with db_lock:
        cursor = await db_conn.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def db_fetchall(query: str, params=()):
    async with db_lock:
        cursor = await db_conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def db_execute(query: str, params=()):
    async with db_lock:
        await db_conn.execute(query, params)
        await db_conn.commit()


async def get_user(user_id: int):
    row = await db_fetchone(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )

    return dict(row) if row else None


async def ensure_user(user):
    user_id = user.id
    username = user.username
    full_name = user.full_name or ""

    async with db_lock:
        await db_conn.execute(
            """
            INSERT INTO users (
                user_id, username, full_name, created_at, last_seen
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen
            """,
            (
                user_id,
                username,
                full_name,
                now_ts(),
                now_ts(),
            ),
        )

        await db_conn.commit()


async def change_balance(
    user_id: int,
    amount: int,
    reason: str,
) -> bool:
    """
    Безопасное изменение баланса.
    Отрицательная сумма означает списание.
    """

    amount = int(amount)

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            cursor = await db_conn.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

            if row is None:
                await db_conn.rollback()
                return False

            new_balance = int(row["balance"]) + amount

            if new_balance < 0:
                await db_conn.rollback()
                return False

            await db_conn.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?",
                (new_balance, user_id),
            )

            await db_conn.execute(
                """
                INSERT INTO transactions (
                    user_id, amount, reason, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    amount,
                    reason,
                    now_ts(),
                ),
            )

            await db_conn.commit()
            return True

        except Exception:
            await db_conn.rollback()
            logger.exception("change_balance failed")
            return False


async def transfer_tokens(
    sender_id: int,
    recipient_id: int,
    amount: int,
) -> bool:
    if amount <= 0 or sender_id == recipient_id:
        return False

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            cursor = await db_conn.execute(
                """
                SELECT user_id, balance, transfers_blocked
                FROM users
                WHERE user_id IN (?, ?)
                """,
                (sender_id, recipient_id),
            )

            rows = await cursor.fetchall()
            await cursor.close()

            users = {
                int(row["user_id"]): dict(row)
                for row in rows
            }

            if sender_id not in users or recipient_id not in users:
                await db_conn.rollback()
                return False

            sender = users[sender_id]
            recipient = users[recipient_id]

            if sender["transfers_blocked"] or recipient["transfers_blocked"]:
                await db_conn.rollback()
                return False

            if sender["balance"] < amount:
                await db_conn.rollback()
                return False

            await db_conn.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, sender_id),
            )

            await db_conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, recipient_id),
            )

            timestamp = now_ts()

            await db_conn.execute(
                """
                INSERT INTO transactions(user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (sender_id, -amount, f"Перевод пользователю {recipient_id}", timestamp),
            )

            await db_conn.execute(
                """
                INSERT INTO transactions(user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (recipient_id, amount, f"Перевод от пользователя {sender_id}", timestamp),
            )

            await db_conn.commit()
            return True

        except Exception:
            await db_conn.rollback()
            logger.exception("transfer_tokens failed")
            return False


async def add_game_log(
    user_id: int,
    chat_id: int,
    game: str,
    bet: int,
    win: int,
    result: str,
):
    await db_execute(
        """
        INSERT INTO game_log(
            user_id, chat_id, game, bet, win, result, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            chat_id,
            game,
            bet,
            win,
            result,
            now_ts(),
        ),
    )


async def get_game_stats(user_id: int):
    row = await db_fetchone(
        """
        SELECT
            COALESCE(SUM(bet), 0) AS bets,
            COALESCE(SUM(win), 0) AS wins,
            COALESCE(SUM(CASE WHEN win = 0 THEN bet ELSE 0 END), 0) AS losses,
            COUNT(*) AS games
        FROM game_log
        WHERE user_id = ?
        """,
        (user_id,),
    )

    return dict(row) if row else {
        "bets": 0,
        "wins": 0,
        "losses": 0,
        "games": 0,
    }


async def get_user_by_username(username: str):
    username = username.lstrip("@").lower()

    row = await db_fetchone(
        """
        SELECT *
        FROM users
        WHERE lower(username) = ?
        LIMIT 1
        """,
        (username,),
    )

    return dict(row) if row else None


async def get_top_users(limit: int = 10):
    return await db_fetchall(
        """
        SELECT *
        FROM users
        WHERE is_banned = 0
        ORDER BY balance DESC
        LIMIT ?
        """,
        (limit,),
    )


async def get_recent_transactions(user_id: int, limit: int = 10):
    return await db_fetchall(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )


async def get_global_stats():
    row = await db_fetchone(
        """
        SELECT
            COUNT(*) AS users,
            COALESCE(SUM(balance), 0) AS balance,
            COALESCE(SUM(donated_stars), 0) AS donated_stars,
            COALESCE(SUM(referrals), 0) AS referrals
        FROM users
        """
    )

    return dict(row) if row else {}


# ------------------------- REFERRALS -------------------------

async def process_referral(new_user_id: int, referrer_id: int):
    if new_user_id == referrer_id:
        return False

    referrer = await get_user(referrer_id)

    if not referrer:
        return False

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            cursor = await db_conn.execute(
                """
                SELECT referred_by, referral_paid
                FROM users
                WHERE user_id = ?
                """,
                (new_user_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

            if not row:
                await db_conn.rollback()
                return False

            if row["referred_by"] is not None or row["referral_paid"]:
                await db_conn.rollback()
                return False

            await db_conn.execute(
                """
                UPDATE users
                SET referred_by = ?, referral_paid = 1
                WHERE user_id = ?
                """,
                (referrer_id, new_user_id),
            )

            await db_conn.execute(
                """
                UPDATE users
                SET balance = balance + ?,
                    referrals = referrals + 1,
                    referral_earned = referral_earned + ?
                WHERE user_id = ?
                """,
                (
                    REFERRAL_REWARD,
                    REFERRAL_REWARD,
                    referrer_id,
                ),
            )

            await db_conn.execute(
                """
                INSERT INTO transactions(user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    referrer_id,
                    REFERRAL_REWARD,
                    f"Реферал {new_user_id}",
                    now_ts(),
                ),
            )

            await db_conn.commit()

        except Exception:
            await db_conn.rollback()
            logger.exception("Referral transaction failed")
            return False

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Новый реферал! Начислено {REFERRAL_REWARD:,} TOKENS.",
        )
    except Exception:
        pass

    return True


# ------------------------- KEYBOARDS -------------------------

def main_menu(language: str = "ru"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=tr(language, "menu_play"),
                ),
            ],
            [
                KeyboardButton(
                    text=tr(language, "menu_bonus"),
                ),
                KeyboardButton(
                    text=tr(language, "menu_donate"),
                ),
            ],
            [
                KeyboardButton(
                    text=tr(language, "menu_profile"),
                ),
                KeyboardButton(
                    text=tr(language, "menu_top"),
                ),
            ],
            [
                KeyboardButton(
                    text=tr(language, "menu_ref"),
                ),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def how_keyboard():
    return make_inline([
        [
            ("🎮 Игры", "how:games"),
            ("📖 Команды", "how:commands"),
        ],
        [
            ("💬 Чаты", "how:chats"),
            ("⬅️ Назад", "how:back"),
        ],
    ])


def games_keyboard():
    return make_inline([
        [
            ("🎲 Кости", "gameinfo:dice"),
            ("🎯 Дартс", "gameinfo:darts"),
        ],
        [
            ("🏀 Баскет", "gameinfo:basket"),
            ("⚽ Футбол", "gameinfo:football"),
        ],
        [
            ("🎳 Боулинг", "gameinfo:bowling"),
            ("🎡 Рулетка", "gameinfo:roulette"),
        ],
        [
            ("⬅️ Назад", "how:back"),
        ],
    ])


def chats_keyboard():
    support = SUPPORT_USERNAME
    if not support.startswith("@"):
        support = "@" + support

    channel = NEWS_CHANNEL

    if channel.startswith("@"):
        channel = channel[1:]

    return make_inline([
        [
            InlineKeyboardButton(
                text="@tokenplays",
                url="https://t.me/tokenplays",
            ),
        ],
        [
            InlineKeyboardButton(
                text="@Tokenschange",
                url="https://t.me/Tokenschange",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💬 Поддержка",
                url=f"https://t.me/{support.lstrip('@')}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📢 Новости",
                url=f"https://t.me/{channel}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="how:back",
            ),
        ],
    ])


def profile_keyboard():
    return make_inline([
        [
            ("⚙️ Настройки", "profile:settings"),
            ("⭐ Купить VIP", "vip:open"),
        ],
    ])


def settings_keyboard(data: dict):
    language = data.get("language", "ru")
    transfers = bool(data.get("transfers_blocked", 0))

    transfer_label = (
        "🚫 Переводы: ВКЛ"
        if transfers
        else "✅ Переводы: ВЫКЛ"
    )

    return make_inline([
        [
            ("🇷🇺 Русский", "settings:lang:ru"),
            ("🇬🇧 English", "settings:lang:en"),
        ],
        [
            (transfer_label, "settings:transfers"),
        ],
        [
            ("⬅️ Назад", "profile:back"),
        ],
    ])


def vip_keyboard():
    return make_inline([
        [
            ("1 день — 5⭐", "vip:buy:1"),
            ("3 дня — 15⭐", "vip:buy:3"),
        ],
        [
            ("7 дней — 35⭐", "vip:buy:7"),
            ("30 дней — 150⭐", "vip:buy:30"),
        ],
        [
            ("⬅️ Назад", "profile:back"),
        ],
    ])


def donate_keyboard():
    return make_inline([
        [
            ("10⭐", "donate:10"),
            ("50⭐", "donate:50"),
            ("100⭐", "donate:100"),
        ],
        [
            ("200⭐", "donate:200"),
            ("300⭐", "donate:300"),
            ("400⭐", "donate:400"),
        ],
        [
            ("500⭐", "donate:500"),
        ],
        [
            ("✍️ Своя сумма", "donate:custom"),
        ],
    ])


def top_keyboard():
    return make_inline([
        [
            ("По балансу", "top:balance"),
        ],
    ])


def subscription_keyboard():
    channel = NEWS_CHANNEL.lstrip("@")

    return make_inline([
        [
            InlineKeyboardButton(
                text="📢 Подписаться на канал",
                url=f"https://t.me/{channel}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔄 Проверить подписку",
                callback_data="bonus:check",
            ),
        ],
    ])


def game_group_keyboard():
    return make_inline([
        [
            InlineKeyboardButton(
                text="🎮 Игровой чат",
                url="https://t.me/tokenplays",
            ),
        ],
    ])


# ------------------------- FSM -------------------------------

class CaptchaState(StatesGroup):
    waiting = State()


class CustomDonateState(StatesGroup):
    waiting_amount = State()


# ------------------------- USER STATUS -----------------------

async def user_is_banned(user_id: int) -> bool:
    user = await get_user(user_id)

    if not user:
        return False

    if not user["is_banned"]:
        return False

    if user["ban_until"] and user["ban_until"] < now_ts():
        await db_execute(
            """
            UPDATE users
            SET is_banned = 0, ban_until = 0
            WHERE user_id = ?
            """,
            (user_id,),
        )

        return False

    return True


async def user_is_vip(user_id: int) -> bool:
    user = await get_user(user_id)

    if not user:
        return False

    return int(user["vip_until"]) > now_ts()


async def set_user_ban(user_id: int, duration: int):
    await db_execute(
        """
        UPDATE users
        SET is_banned = 1, ban_until = ?
        WHERE user_id = ?
        """,
        (
            now_ts() + duration if duration > 0 else 0,
            user_id,
        ),
    )


# ------------------------- CAPTCHA ---------------------------

async def send_captcha(message: Message, state: FSMContext):
    code = str(random.randint(1000, 9999))

    image_bytes = generate_captcha_image(code)

    sent = await message.answer_photo(
        BufferedInputFile(
            image_bytes,
            filename="captcha.png",
        ),
        caption=tr("ru", "captcha_prompt"),
    )

    pending_captchas[message.from_user.id] = {
        "code": code,
        "attempts": 0,
        "message_id": sent.message_id,
        "chat_id": message.chat.id,
    }

    await state.set_state(CaptchaState.waiting)


async def complete_captcha(message: Message, state: FSMContext):
    user_id = message.from_user.id

    captcha = pending_captchas.get(user_id)

    if not captcha:
        await state.clear()
        return

    try:
        await message.delete()
    except Exception:
        pass

    if message.text.strip() != captcha["code"]:
        captcha["attempts"] += 1

        try:
            await bot.delete_message(
                captcha["chat_id"],
                captcha["message_id"],
            )
        except Exception:
            pass

        if captcha["attempts"] >= 3:
            await set_user_ban(
                user_id,
                CAPTCHA_BAN_SECONDS,
            )

            pending_captchas.pop(user_id, None)
            await state.clear()

            image = generate_error_image("ДОСТУП ЗАКРЫТ")

            await bot.send_photo(
                message.chat.id,
                BufferedInputFile(
                    image,
                    filename="captcha_banned.png",
                ),
                caption=tr("ru", "captcha_banned"),
            )

            return

        code = str(random.randint(1000, 9999))
        image = generate_captcha_image(code)

        sent = await bot.send_photo(
            message.chat.id,
            BufferedInputFile(
                image,
                filename="captcha.png",
            ),
            caption=tr("ru", "captcha_wrong"),
        )

        captcha["code"] = code
        captcha["message_id"] = sent.message_id

        pending_captchas[user_id] = captcha
        return

    try:
        await bot.delete_message(
            captcha["chat_id"],
            captcha["message_id"],
        )
    except Exception:
        pass

    pending_captchas.pop(user_id, None)
    await state.clear()

    await db_execute(
        """
        UPDATE users
        SET captcha_verified = 1, captcha_attempts = 0
        WHERE user_id = ?
        """,
        (user_id,),
    )

    await change_balance(
        user_id,
        START_BONUS,
        "Приветственный бонус",
    )

    await bot.send_message(
        message.chat.id,
        tr("ru", "captcha_success"),
        reply_markup=main_menu("ru"),
    )


# ------------------------- START -----------------------------

@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
):
    user = message.from_user

    await ensure_user(user)

    if await user_is_banned(user.id):
        return

    user_data = await get_user(user.id)

    if user_data and user_data["captcha_verified"]:
        await message.answer(
            "Добро пожаловать в TOKENS!",
            reply_markup=main_menu(user_language(user_data)),
        )
        return

    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        payload = args[1].strip()

        if payload.startswith("ref_"):
            referrer_id = safe_int(payload[4:])

            if referrer_id:
                user_data = await get_user(user.id)

                if user_data and user_data["referred_by"] is None:
                    await db_execute(
                        """
                        UPDATE users
                        SET referred_by = ?
                        WHERE user_id = ?
                        """,
                        (referrer_id, user.id),
                    )

    if WELCOME_BG.exists():
        try:
            await message.answer_photo(
                BufferedInputFile(
                    WELCOME_BG.read_bytes(),
                    filename="welcome.jpg",
                ),
                caption=tr("ru", "welcome"),
            )
        except Exception:
            await message.answer(tr("ru", "welcome"))
    else:
        await message.answer(tr("ru", "welcome"))

    await send_captcha(message, state)


@dp.message(CaptchaState.waiting)
async def captcha_message_handler(
    message: Message,
    state: FSMContext,
):
    if not message.text:
        return

    await complete_captcha(message, state)


# ------------------------- REFERRAL AFTER CAPTCHA ------------

async def reward_referral_after_captcha(user_id: int):
    user = await get_user(user_id)

    if not user:
        return

    referrer_id = user.get("referred_by")

    if not referrer_id:
        return

    # Защита от повторной выдачи.
    if user.get("referral_paid"):
        return

    success = await process_referral(user_id, referrer_id)

    if success:
        await change_balance(
            user_id,
            REFERRAL_REWARD,
            "Бонус за регистрацию по рефералу",
        )


# ------------------------- PROFILE ---------------------------

async def get_avatar_bytes(user_id: int):
    try:
        photos = await bot.get_user_profile_photos(
            user_id,
            limit=1,
        )

        if not photos.photos:
            return None

        photo = photos.photos[0][-1]

        file = await bot.get_file(photo.file_id)

        buffer = BytesIO()

        await bot.download_file(
            file.file_path,
            destination=buffer,
        )

        return buffer.getvalue()

    except Exception as exc:
        logger.debug("Avatar download failed: %s", exc)
        return None


async def show_profile(
    message: Message,
    user_id: int,
    chat_id: Optional[int] = None,
):
    user = await get_user(user_id)

    if not user:
        return

    stats = await get_game_stats(user_id)

    avatar = await get_avatar_bytes(user_id)

    image = generate_profile_image(
        name=user["full_name"],
        username=clean_username(user["username"]),
        balance=user["balance"],
        bets=stats["bets"],
        wins=stats["wins"],
        losses=stats["losses"],
        games=stats["games"],
        avatar_bytes=avatar,
    )

    caption = (
        "👤 ПРОФИЛЬ TOKENS\n\n"
        f"Имя: {user['full_name']}\n"
        f"Баланс: {user['balance']:,} TOKENS\n"
        f"Ставки: {stats['bets']:,}\n"
        f"Выигрыши: {stats['wins']:,}\n"
        f"Проигрыши: {stats['losses']:,}\n"
        f"Игры: {stats['games']}"
    )

    target_chat = chat_id or message.chat.id

    await bot.send_photo(
        target_chat,
        BufferedInputFile(
            image,
            filename="profile.png",
        ),
        caption=caption,
        reply_markup=profile_keyboard(),
    )


@dp.message(F.text.in_({
    "👤 Профиль",
    "👤 Profile",
}))
async def profile_handler(message: Message):
    await ensure_user(message.from_user)
    await show_profile(
        message,
        message.from_user.id,
    )


@dp.callback_query(F.data == "profile:back")
async def profile_back_callback(callback: CallbackQuery):
    await callback.answer()

    await show_profile(
        callback.message,
        callback.from_user.id,
    )


@dp.callback_query(F.data == "profile:settings")
async def profile_settings_callback(callback: CallbackQuery):
    await callback.answer()

    user = await get_user(callback.from_user.id)

    if not user:
        return

    await callback.message.answer(
        tr(user_language(user), "settings_title"),
        reply_markup=settings_keyboard(user),
    )


@dp.callback_query(F.data.startswith("settings:lang:"))
async def settings_language_callback(callback: CallbackQuery):
    language = callback.data.split(":")[-1]

    if language not in ("ru", "en"):
        await callback.answer()
        return

    await db_execute(
        "UPDATE users SET language = ? WHERE user_id = ?",
        (language, callback.from_user.id),
    )

    await callback.answer("Language updated")

    user = await get_user(callback.from_user.id)

    await callback.message.edit_text(
        tr(language, "settings_title"),
        reply_markup=settings_keyboard(user),
    )


@dp.callback_query(F.data == "settings:transfers")
async def settings_transfers_callback(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)

    if not user:
        await callback.answer()
        return

    new_value = 0 if user["transfers_blocked"] else 1

    await db_execute(
        """
        UPDATE users
        SET transfers_blocked = ?
        WHERE user_id = ?
        """,
        (new_value, callback.from_user.id),
    )

    updated = await get_user(callback.from_user.id)

    await callback.answer("Настройки обновлены")

    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(updated),
    )


# ------------------------- HOW TO PLAY -----------------------

@dp.message(F.text.in_({
    "🎮 Как играть?",
    "🎮 How to play?",
}))
async def how_to_play_handler(message: Message):
    await ensure_user(message.from_user)

    user = await get_user(message.from_user.id)
    language = user_language(user)

    await send_photo_or_text(
        message,
        HOW_TO_PLAY_BG,
        tr(language, "how_title"),
        reply_markup=how_keyboard(),
    )


@dp.callback_query(F.data == "how:back")
async def how_back_callback(callback: CallbackQuery):
    await callback.answer()

    user = await get_user(callback.from_user.id)
    language = user_language(user)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        tr(language, "how_title"),
        reply_markup=how_keyboard(),
    )


@dp.callback_query(F.data == "how:games")
async def how_games_callback(callback: CallbackQuery):
    await callback.answer()

    user = await get_user(callback.from_user.id)
    language = user_language(user)

    await callback.message.answer(
        tr(language, "games_title"),
        reply_markup=games_keyboard(),
    )


@dp.callback_query(F.data == "how:commands")
async def how_commands_callback(callback: CallbackQuery):
    await callback.answer()

    text = (
        "📖 Команды:\n\n"
        "кости 1000 — игра в кости\n"
        "дартс 1000 — игра в дартс\n"
        "баскет 1000 — баскетбол\n"
        "футбол 1000 — футбол\n"
        "боулинг 1000 — боулинг\n\n"
        "старт — запустить рулетку\n"
        "к 1000 — ставка на красное\n"
        "ч 1000 — ставка на чёрное\n"
        "перевод 1000 — перевод ответом на сообщение\n"
        "б — баланс\n"
        "лог — история рулетки\n"
        "топ — таблица лидеров"
    )

    await callback.message.answer(text)


@dp.callback_query(F.data == "how:chats")
async def how_chats_callback(callback: CallbackQuery):
    await callback.answer()

    await callback.message.answer(
        "Наши чаты и каналы:",
        reply_markup=chats_keyboard(),
    )


GAME_INFO = {
    "dice": (
        "🎲 Кости\n\n"
        "Напиши в группе: кости 1000\n"
        "Бот бросит кубик. При результате больше 3 "
        "ты получишь x2 от ставки."
    ),
    "darts": (
        "🎯 Дартс\n\n"
        "Напиши: дартс 1000\n"
        "Попадание в нужную зону приносит x2."
    ),
    "basket": (
        "🏀 Баскетбол\n\n"
        "Напиши: баскет 1000\n"
        "Множитель зависит от результата броска."
    ),
    "football": (
        "⚽ Футбол\n\n"
        "Напиши: футбол 1000\n"
        "Множитель зависит от результата броска."
    ),
    "bowling": (
        "🎳 Боулинг\n\n"
        "Напиши: боулинг 1000\n"
        "При результате больше 3 — x2."
    ),
    "roulette": (
        "🎡 Рулетка\n\n"
        "Ставки:\n"
        "к 1000 — красное\n"
        "ч 1000 — чёрное\n"
        "10-20 500 — диапазон\n"
        "500 10-20 21 — несколько вариантов\n"
        "старт — запустить рулетку."
    ),
}


@dp.callback_query(F.data.startswith("gameinfo:"))
async def game_info_callback(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]

    await callback.answer()

    text = GAME_INFO.get(
        key,
        "Инструкция недоступна.",
    )

    await callback.message.answer(
        text,
        reply_markup=make_inline([
            [("⬅️ Назад", "how:games")],
        ]),
    )


# ------------------------- BONUS -----------------------------

async def check_subscription(user_id: int):
    try:
        member = await bot.get_chat_member(
            NEWS_CHANNEL,
            user_id,
        )

        return member.status in (
            "creator",
            "administrator",
            "member",
        )

    except Exception as exc:
        logger.warning(
            "Subscription check failed for %s: %s",
            user_id,
            exc,
        )

        return None


async def get_bonus_last_claim(user_id: int):
    row = await db_fetchone(
        "SELECT last_claim FROM bonus WHERE user_id = ?",
        (user_id,),
    )

    return int(row["last_claim"]) if row else 0


async def claim_bonus(user_id: int):
    user = await get_user(user_id)

    if not user:
        return False, "USER"

    if user["balance"] > BONUS_BALANCE_LIMIT:
        return False, "LIMIT"

    last_claim = await get_bonus_last_claim(user_id)

    remaining = BONUS_COOLDOWN - (now_ts() - last_claim)

    if remaining > 0:
        return False, remaining

    vip = await user_is_vip(user_id)

    if vip:
        amount = random.choice([5000, 7500, 10000])
    else:
        amount = NORMAL_BONUS

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            cursor = await db_conn.execute(
                "SELECT last_claim FROM bonus WHERE user_id = ?",
                (user_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

            if row and now_ts() - int(row["last_claim"]) < BONUS_COOLDOWN:
                await db_conn.rollback()
                return False, BONUS_COOLDOWN - (
                    now_ts() - int(row["last_claim"])
                )

            await db_conn.execute(
                """
                INSERT INTO bonus(user_id, last_claim)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET last_claim = excluded.last_claim
                """,
                (user_id, now_ts()),
            )

            await db_conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id),
            )

            await db_conn.execute(
                """
                INSERT INTO transactions(user_id, amount, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    amount,
                    "Ежедневный бонус",
                    now_ts(),
                ),
            )

            await db_conn.commit()

            return True, amount

        except Exception:
            await db_conn.rollback()
            logger.exception("Bonus claim failed")
            return False, "ERROR"


async def send_bonus_error(message: Message, caption: str):
    image = generate_error_image("БОНУС НЕДОСТУПЕН")

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="bonus_error.png",
        ),
        caption=caption,
    )


async def bonus_entry(message: Message):
    user_id = message.from_user.id

    await ensure_user(message.from_user)

    subscription = await check_subscription(user_id)

    if subscription is None:
        await send_bonus_error(
            message,
            "Не удалось проверить подписку. Попробуй позже.",
        )
        return

    if not subscription:
        await send_bonus_error(
            message,
            tr("ru", "subscribe_required"),
        )

        await message.answer(
            "После подписки нажми кнопку проверки.",
            reply_markup=subscription_keyboard(),
        )

        return

    success, result = await claim_bonus(user_id)

    if success:
        await message.answer(
            tr("ru", "bonus_received", amount=result),
        )
        return

    if result == "LIMIT":
        await send_bonus_error(
            message,
            "Баланс больше 100 000 TOKENS. Бонус недоступен.",
        )
        return

    if isinstance(result, int):
        await send_bonus_error(
            message,
            f"Бонус будет доступен через {format_duration(result)}.",
        )
        return

    await send_bonus_error(
        message,
        "Не удалось получить бонус.",
    )


@dp.message(F.text.in_({
    "🎁 Бонус",
    "🎁 Bonus",
}))
async def bonus_handler(message: Message):
    await bonus_entry(message)


@dp.callback_query(F.data == "bonus:check")
async def bonus_check_callback(callback: CallbackQuery):
    await callback.answer()

    subscription = await check_subscription(
        callback.from_user.id,
    )

    if subscription is None:
        await callback.message.answer(
            "Не удалось проверить подписку. Попробуй позже.",
        )
        return

    if not subscription:
        await callback.message.answer(
            "Ты ещё не подписан на канал.",
            reply_markup=subscription_keyboard(),
        )
        return

    await callback.message.answer(
        "Подписка подтверждена! Нажми 🎁 Бонус.",
    )


# ------------------------- VIP -------------------------------

async def create_payment(
    user_id: int,
    stars: int,
    tokens: int,
    payment_type: str,
):
    payload = f"{payment_type}:{user_id}:{uuid.uuid4().hex}"

    await db_execute(
        """
        INSERT INTO payments(
            user_id, payload, stars, tokens,
            payment_type, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            user_id,
            payload,
            stars,
            tokens,
            payment_type,
            now_ts(),
        ),
    )

    return payload


@dp.callback_query(F.data == "vip:open")
async def vip_open_callback(callback: CallbackQuery):
    await callback.answer()

    user = await get_user(callback.from_user.id)

    if not user:
        return

    until = int(user["vip_until"])

    if until > now_ts():
        active_text = (
            "\n\nVIP активен до "
            + utc_datetime(until).strftime("%d.%m.%Y %H:%M UTC")
        )
    else:
        active_text = "\n\nVIP не активен."

    await callback.message.answer(
        tr("ru", "vip_title")
        + "\n\n"
        + tr("ru", "vip_description")
        + active_text,
        reply_markup=vip_keyboard(),
    )


@dp.callback_query(F.data.startswith("vip:buy:"))
async def vip_buy_callback(callback: CallbackQuery):
    days = safe_int(callback.data.split(":")[-1])

    if days not in (1, 3, 7, 30):
        await callback.answer("Неверный срок", show_alert=True)
        return

    stars = days * VIP_PRICE_PER_DAY

    payload = await create_payment(
        callback.from_user.id,
        stars,
        0,
        f"vip_{days}",
    )

    await callback.answer()

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="TOKENS VIP",
        description=f"VIP-подписка на {days} дн.",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"VIP {days} days",
                amount=stars,
            ),
        ],
    )


# ------------------------- DONATE -----------------------------

DONATE_RATES = {
    10: 7500,
    50: 7500,
    100: 8000,
    200: 8500,
    300: 8500,
    400: 9000,
    500: 10000,
}


def tokens_for_stars(stars: int) -> int:
    stars = max(1, min(10000, int(stars)))

    if stars in DONATE_RATES:
        return DONATE_RATES[stars]

    if stars >= 500:
        return (10000 * stars) // 500

    # Для нестандартных сумм ниже 500 используем
    # линейную интерполяцию между фиксированными пакетами.
    points = sorted(DONATE_RATES.items())

    lower = points[0]
    upper = points[-1]

    for point in points:
        if point[0] <= stars:
            lower = point

        if point[0] >= stars:
            upper = point
            break

    if lower[0] == upper[0]:
        return lower[1]

    fraction = (
        (stars - lower[0])
        / (upper[0] - lower[0])
    )

    return int(
        lower[1]
        + fraction * (upper[1] - lower[1])
    )


@dp.message(F.text.in_({
    "💎 Донат",
    "💎 Donate",
}))
async def donate_handler(message: Message):
    await ensure_user(message.from_user)

    await message.answer(
        tr("ru", "donate_title")
        + "\n\n"
        + tr("ru", "donate_description"),
        reply_markup=donate_keyboard(),
    )


@dp.callback_query(F.data.startswith("donate:"))
async def donate_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    value = callback.data.split(":")[-1]

    if value == "custom":
        await callback.answer()

        await state.set_state(
            CustomDonateState.waiting_amount,
        )

        await callback.message.answer(
            "Введи количество Stars от 1 до 10000:"
        )

        return

    stars = safe_int(value)

    if stars not in DONATE_RATES:
        await callback.answer("Неверный пакет", show_alert=True)
        return

    tokens = tokens_for_stars(stars)

    payload = await create_payment(
        callback.from_user.id,
        stars,
        tokens,
        "donate",
    )

    await callback.answer()

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="TOKENS",
        description=f"Покупка {tokens:,} TOKENS",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{tokens:,} TOKENS",
                amount=stars,
            ),
        ],
    )


@dp.message(CustomDonateState.waiting_amount)
async def custom_donate_amount_handler(
    message: Message,
    state: FSMContext,
):
    if not message.text or not message.text.isdigit():
        await message.answer("Введи целое число от 1 до 10000.")
        return

    stars = int(message.text)

    if not 1 <= stars <= 10000:
        await message.answer("Допустимо от 1 до 10000 Stars.")
        return

    await state.clear()

    tokens = tokens_for_stars(stars)

    payload = await create_payment(
        message.from_user.id,
        stars,
        tokens,
        "donate",
    )

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="TOKENS",
        description=f"Покупка {tokens:,} TOKENS",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"{tokens:,} TOKENS",
                amount=stars,
            ),
        ],
    )


# ------------------------- PAYMENT ----------------------------

@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    row = await db_fetchone(
        """
        SELECT *
        FROM payments
        WHERE payload = ?
          AND user_id = ?
          AND status = 'pending'
        """,
        (
            query.invoice_payload,
            query.from_user.id,
        ),
    )

    if not row:
        await query.answer(
            ok=False,
            error_message="Платёж не найден или уже обработан.",
        )
        return

    if query.currency != "XTR":
        await query.answer(
            ok=False,
            error_message="Неверная валюта.",
        )
        return

    if int(query.total_amount) != int(row["stars"]):
        await query.answer(
            ok=False,
            error_message="Неверная сумма платежа.",
        )
        return

    await query.answer(ok=True)


async def activate_vip(user_id: int, days: int):
    current_user = await get_user(user_id)

    if not current_user:
        return False

    current_until = max(
        now_ts(),
        int(current_user["vip_until"]),
    )

    new_until = current_until + days * 86400

    await db_execute(
        """
        UPDATE users
        SET vip_until = ?, vip_auto_bonus = 1
        WHERE user_id = ?
        """,
        (new_until, user_id),
    )

    return True


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment = message.successful_payment

    payload = payment.invoice_payload

    row = await db_fetchone(
        """
        SELECT *
        FROM payments
        WHERE payload = ?
          AND user_id = ?
          AND status = 'pending'
        """,
        (
            payload,
            message.from_user.id,
        ),
    )

    if not row:
        await message.answer(
            "Платёж получен, но запись не найдена. Обратись в поддержку."
        )
        return

    if payment.currency != "XTR":
        await message.answer("Неверная валюта платежа.")
        return

    if int(payment.total_amount) != int(row["stars"]):
        await message.answer("Сумма платежа не совпадает.")
        return

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            cursor = await db_conn.execute(
                """
                SELECT status
                FROM payments
                WHERE payload = ?
                """,
                (payload,),
            )

            current = await cursor.fetchone()
            await cursor.close()

            if not current or current["status"] != "pending":
                await db_conn.rollback()
                return

            await db_conn.execute(
                """
                UPDATE payments
                SET status = 'paid', paid_at = ?
                WHERE payload = ?
                """,
                (now_ts(), payload),
            )

            await db_conn.commit()

        except Exception:
            await db_conn.rollback()
            logger.exception("Payment update failed")
            return

    payment_type = row["payment_type"]

    if payment_type.startswith("vip_"):
        days = safe_int(payment_type.replace("vip_", ""))

        await activate_vip(
            message.from_user.id,
            days,
        )

        await message.answer(
            f"⭐ VIP активирован на {days} дн. Спасибо за поддержку!"
        )

        return

    tokens = int(row["tokens"])

    if await user_is_vip(message.from_user.id):
        tokens = int(tokens * 1.025)

    await change_balance(
        message.from_user.id,
        tokens,
        f"Покупка TOKENS за {row['stars']} Stars",
    )

    await db_execute(
        """
        UPDATE users
        SET donated_stars = donated_stars + ?
        WHERE user_id = ?
        """,
        (
            row["stars"],
            message.from_user.id,
        ),
    )

    await message.answer(
        tr(
            "ru",
            "donate_success",
            amount=f"{tokens:,}",
        ),
    )


# ------------------------- TOP -------------------------------

async def build_top_text():
    rows = await get_top_users(10)

    if not rows:
        return "Пока нет игроков."

    lines = ["🏆 ТОП-10 TOKENS", ""]

    for index, row in enumerate(rows, 1):
        name = row["username"] or row["full_name"] or str(row["user_id"])

        balance = (
            "Скрыт"
            if row["vip_hide_top"] and row["vip_until"] > now_ts()
            else f'{row["balance"]:,} TOKENS'
        )

        lines.append(
            f"{index}. {name} — {balance}"
        )

    return "\n".join(lines)


async def show_top(message: Message):
    rows = await get_top_users(10)

    if not rows:
        await message.answer("Пока нет игроков.")
        return

    image = generate_top_image(
        [dict(row) for row in rows],
    )

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="top.png",
        ),
        caption="🏆 ТОП-10 TOKENS",
    )


@dp.message(F.text.in_({
    "🏆 Топ",
    "🏆 Top",
}))
async def top_handler(message: Message):
    await show_top(message)


@dp.callback_query(F.data == "top:balance")
async def top_balance_callback(callback: CallbackQuery):
    await callback.answer()

    rows = await get_top_users(10)

    image = generate_top_image(
        [dict(row) for row in rows],
    )

    await callback.message.answer_photo(
        BufferedInputFile(
            image,
            filename="top.png",
        ),
        caption="🏆 ТОП-10 TOKENS",
    )


# ------------------------- REFERRAL --------------------------

@dp.message(F.text.in_({
    "🔗 Рефералка",
    "🔗 Referral",
}))
async def referral_handler(message: Message):
    await ensure_user(message.from_user)

    user = await get_user(message.from_user.id)

    me = await bot.get_me()

    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"

    image = generate_ref_image(
        user["referrals"],
        user["referral_earned"],
        link,
    )

    keyboard = make_inline([
        [
            InlineKeyboardButton(
                text="🔗 Пригласить друга",
                url=link,
            ),
        ],
    ])

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="referral.png",
        ),
        caption=(
            f"Приглашено: {user['referrals']}\n"
            f"Заработано: {user['referral_earned']:,} TOKENS"
        ),
        reply_markup=keyboard,
    )


# ------------------------- GAME ENGINE -----------------------

GAME_CONFIG = {
    "кости": {
        "emoji": "🎲",
        "multiplier": "dice",
    },
    "дартс": {
        "emoji": "🎯",
        "multiplier": "darts",
    },
    "баскет": {
        "emoji": "🏀",
        "multiplier": "sport",
    },
    "футбол": {
        "emoji": "⚽",
        "multiplier": "sport",
    },
    "боулинг": {
        "emoji": "🎳",
        "multiplier": "bowling",
    },
}

GAME_ALIASES = {
    "кости": "кости",
    "кость": "кости",
    "dice": "кости",

    "дартс": "дартс",
    "dart": "дартс",

    "баскет": "баскет",
    "баскетбол": "баскет",
    "basket": "баскет",

    "футбол": "футбол",
    "football": "футбол",

    "боулинг": "боулинг",
    "bowling": "боулинг",
}


def calculate_game_multiplier(game: str, value: int) -> float:
    if game in ("кости", "дартс", "боулинг"):
        return 2.0 if value > 3 else 0.0

    if game in ("баскет", "футбол"):
        multipliers = {
            1: 0.0,
            2: 1.0,
            3: 1.5,
            4: 1.8,
            5: 2.0,
        }

        return multipliers.get(value, 0.0)

    return 0.0


async def play_game(
    message: Message,
    game: str,
    stake: int,
):
    if not is_group(message):
        image = generate_error_image("ИГРАЙ В ГРУППЕ")

        await message.answer_photo(
            BufferedInputFile(
                image,
                filename="game_group.png",
            ),
            caption=tr("ru", "game_group_only"),
            reply_markup=game_group_keyboard(),
        )

        return

    if stake <= 0:
        await send_temporary(
            message,
            tr("ru", "game_invalid_bet"),
            GAME_DELETE_SECONDS,
        )
        return

    await ensure_user(message.from_user)

    if await user_is_banned(message.from_user.id):
        return

    success = await change_balance(
        message.from_user.id,
        -stake,
        f"Ставка: {game}",
    )

    if not success:
        image = generate_error_image("НЕДОСТАТОЧНО СРЕДСТВ")

        sent = await message.answer_photo(
            BufferedInputFile(
                image,
                filename="not_enough.png",
            ),
            caption=tr("ru", "game_not_enough"),
        )

        await delete_after_send(
            sent,
            GAME_DELETE_SECONDS,
        )

        return

    emoji = GAME_CONFIG[game]["emoji"]

    try:
        dice_message = await message.answer_dice(
            emoji=emoji,
        )
    except Exception:
        await change_balance(
            message.from_user.id,
            stake,
            "Возврат ставки: ошибка игры",
        )
        return

    await asyncio.sleep(3)

    value = dice_message.dice.value

    multiplier = calculate_game_multiplier(
        game,
        value,
    )

    payout = int(stake * multiplier)

    if payout:
        await change_balance(
            message.from_user.id,
            payout,
            f"Выигрыш: {game}",
        )

    net_win = payout - stake

    await add_game_log(
        message.from_user.id,
        message.chat.id,
        game,
        stake,
        payout,
        f"Выпало {value}; множитель {multiplier}",
    )

    if payout > 0:
        result_text = (
            f"🎉 {message.from_user.full_name}\n"
            f"Выпало: {value}\n"
            f"Множитель: x{multiplier}\n"
            f"Выплата: {payout:,} TOKENS\n"
            f"Чистый результат: {net_win:+,}"
        )
    else:
        result_text = (
            f"😔 {message.from_user.full_name}\n"
            f"Выпало: {value}\n"
            f"Ставка {stake:,} TOKENS проиграна."
        )

    result_message = await message.answer(
        result_text,
    )

    await delete_after_send(
        message,
        GAME_DELETE_SECONDS,
    )

    await delete_after_send(
        dice_message,
        GAME_DELETE_SECONDS,
    )

    await delete_after_send(
        result_message,
        GAME_DELETE_SECONDS,
    )


@dp.message(F.text)
async def game_message_router(message: Message):
    if not message.text:
        return

    parts = message.text.strip().split()

    if len(parts) != 2:
        return

    game_key = GAME_ALIASES.get(parts[0].lower())

    if not game_key:
        return

    if not re.fullmatch(r"\d+", parts[1]):
        return

    stake = int(parts[1])

    await play_game(
        message,
        game_key,
        stake,
    )


# ------------------------- ROULETTE --------------------------

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18,
    19, 21, 23, 25, 27,
    30, 32, 34, 36,
}

BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS


def roulette_color(number: int) -> str:
    if number == 0:
        return "Зеро"

    if number in RED_NUMBERS:
        return "Красное"

    return "Чёрное"


def parse_roulette_selection(token: str):
    token = token.lower().strip()

    if token in ("к", "красное", "red"):
        return {
            "type": "color",
            "value": "red",
            "multiplier": 2,
        }

    if token in ("ч", "черное", "чёрное", "black"):
        return {
            "type": "color",
            "value": "black",
            "multiplier": 2,
        }

    if token == "0":
        return {
            "type": "number",
            "value": 0,
            "multiplier": 36,
        }

    if re.fullmatch(r"\d{1,2}-\d{1,2}", token):
        start, end = map(int, token.split("-"))

        if not (0 <= start <= end <= 36):
            return None

        return {
            "type": "range",
            "value": [start, end],
            "multiplier": max(2, int(36 / (end - start + 1))),
        }

    if token.isdigit():
        number = int(token)

        if 0 <= number <= 36:
            return {
                "type": "number",
                "value": number,
                "multiplier": 36,
            }

    return None


def parse_roulette_bet(text: str):
    """
    Поддерживаемые форматы:
      к 1000
      1000 к
      ч 1000
      10-20 500
      500 10-20
      500 10-20 11-20 0 9-15 20 21

    Если первое значение — сумма, остальные токены
    считаются отдельными вариантами на эту сумму.
    """

    tokens = text.lower().split()

    if len(tokens) < 2:
        return None

    stake = None
    selections = []

    if tokens[0].isdigit():
        stake = int(tokens[0])
        selection_tokens = tokens[1:]

    elif tokens[-1].isdigit():
        stake = int(tokens[-1])
        selection_tokens = tokens[:-1]

    else:
        return None

    if stake <= 0:
        return None

    if len(selection_tokens) > MAX_ROULETTE_RANGES:
        return None

    for token in selection_tokens:
        selection = parse_roulette_selection(token)

        if not selection:
            return None

        selections.append(selection)

    if not selections:
        return None

    return stake, selections


def roulette_selection_wins(selection: dict, number: int) -> bool:
    selection_type = selection["type"]
    value = selection["value"]

    if selection_type == "color":
        if value == "red":
            return number in RED_NUMBERS

        return number in BLACK_NUMBERS

    if selection_type == "number":
        return number == value

    if selection_type == "range":
        return value[0] <= number <= value[1]

    return False


async def get_or_create_roulette_round(chat_id: int):
    current = roulette_rounds.get(chat_id)

    if current:
        return current

    round_id = uuid.uuid4().hex

    current = {
        "id": round_id,
        "chat_id": chat_id,
        "created_at": now_ts(),
        "running": False,
    }

    roulette_rounds[chat_id] = current

    return current


async def roulette_add_bet(
    message: Message,
    stake: int,
    selections: list,
):
    if not is_group(message):
        return

    await ensure_user(message.from_user)

    round_data = await get_or_create_roulette_round(
        message.chat.id,
    )

    if round_data["running"]:
        await send_temporary(
            message,
            "Рулетка уже крутится!",
            GAME_DELETE_SECONDS,
        )
        return

    total_cost = stake * len(selections)

    success = await change_balance(
        message.from_user.id,
        -total_cost,
        "Ставка в рулетке",
    )

    if not success:
        await send_temporary(
            message,
            "Недостаточно TOKENS для ставки.",
            GAME_DELETE_SECONDS,
        )
        return

    async with db_lock:
        await db_conn.execute("BEGIN TRANSACTION")

        try:
            for selection in selections:
                await db_conn.execute(
                    """
                    INSERT INTO roulette_bets(
                        round_id, user_id, chat_id,
                        stake, selection, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        round_data["id"],
                        message.from_user.id,
                        message.chat.id,
                        stake,
                        str(selection),
                        now_ts(),
                    ),
                )

            await db_conn.commit()

        except Exception:
            await db_conn.rollback()

            await change_balance(
                message.from_user.id,
                total_cost,
                "Возврат ставки рулетки",
            )

            logger.exception("Roulette bet failed")
            return

    last_user_bets[
        (message.chat.id, message.from_user.id)
    ] = {
        "stake": stake,
        "selections": selections,
        "created_at": now_ts(),
    }

    sent = await message.answer(
        tr("ru", "roulette_accepted"),
    )

    await delete_after_send(
        sent,
        GAME_DELETE_SECONDS,
    )


@dp.message(F.text)
async def roulette_bet_router(message: Message):
    if not message.text or not is_group(message):
        return

    text = message.text.strip()

    if text.lower() == "старт":
        await start_roulette(message)
        return

    parsed = parse_roulette_bet(text)

    if not parsed:
        return

    stake, selections = parsed

    await roulette_add_bet(
        message,
        stake,
        selections,
    )


async def start_roulette(message: Message):
    chat_id = message.chat.id

    async with roulette_lock:
        round_data = roulette_rounds.get(chat_id)

        if not round_data:
            await message.answer(
                tr("ru", "roulette_no_bets"),
            )
            return

        if round_data["running"]:
            await message.answer(
                tr("ru", "roulette_running"),
            )
            return

        round_data["running"] = True

    rows = await db_fetchall(
        """
        SELECT *
        FROM roulette_bets
        WHERE round_id = ?
          AND settled = 0
        ORDER BY id
        """,
        (round_data["id"],),
    )

    if not rows:
        roulette_rounds.pop(chat_id, None)

        await message.answer(
            tr("ru", "roulette_no_bets"),
        )

        return

    animation_message = None

    if ROULETTE_GIF.exists():
        try:
            animation_message = await message.answer_animation(
                BufferedInputFile(
                    ROULETTE_GIF.read_bytes(),
                    filename="roulette.gif",
                ),
            )
        except Exception:
            animation_message = None

    if animation_message is None:
        try:
            animation_message = await message.answer_dice(
                emoji="🎰",
            )
        except Exception:
            pass

    await asyncio.sleep(3)

    number = random.randint(0, 36)
    color = roulette_color(number)

    winners = []
    losers = []

    for row in rows:
        selection = eval(
            row["selection"],
            {"__builtins__": {}},
            {},
        )

        won = roulette_selection_wins(
            selection,
            number,
        )

        if won:
            payout = int(
                row["stake"] * selection["multiplier"]
            )

            await change_balance(
                row["user_id"],
                payout,
                "Выигрыш в рулетке",
            )

            winners.append(
                (row["user_id"], payout, row["stake"])
            )

        else:
            losers.append(
                (row["user_id"], row["stake"])
            )

    await db_execute(
        """
        UPDATE roulette_bets
        SET settled = 1
        WHERE round_id = ?
        """,
        (round_data["id"],),
    )

    await db_execute(
        """
        INSERT INTO roulette_history(chat_id, number, color, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            chat_id,
            number,
            color,
            now_ts(),
        ),
    )

    roulette_history.setdefault(chat_id, []).append(
        (number, color),
    )

    roulette_history[chat_id] = roulette_history[chat_id][-10:]

    if animation_message:
        try:
            await animation_message.delete()
        except Exception:
            pass

    result_lines = [
        f"🎡 Выпало: {number} ({color})",
        "",
        "🏆 Победители:",
    ]

    if winners:
        for user_id, payout, stake in winners:
            result_lines.append(
                f"• {user_id}: +{payout:,} TOKENS"
            )
    else:
        result_lines.append("Победителей нет.")

    result_lines.extend([
        "",
        "😔 Проигравшие:",
    ])

    if losers:
        for user_id, stake in losers:
            result_lines.append(
                f"• {user_id}: -{stake:,} TOKENS"
            )
    else:
        result_lines.append("Нет.")

    keyboard = make_inline([
        [
            ("🔄 Повторить", f"roulette:repeat:{round_data['id']}"),
            ("⏫ Удвоить", f"roulette:double:{round_data['id']}"),
        ],
    ])

    await message.answer(
        "\n".join(result_lines),
        reply_markup=keyboard,
    )

    roulette_rounds.pop(chat_id, None)


# ------------------------- ROULETTE REPEAT --------------------

@dp.callback_query(F.data.startswith("roulette:"))
async def roulette_repeat_callback(callback: CallbackQuery):
    parts = callback.data.split(":")

    if len(parts) != 3:
        await callback.answer()
        return

    action = parts[1]

    last_bet = last_user_bets.get(
        (
            callback.message.chat.id,
            callback.from_user.id,
        )
    )

    if not last_bet:
        await callback.answer(
            "Нет предыдущей ставки.",
            show_alert=True,
        )
        return

    if now_ts() - last_bet["created_at"] > ROuLETTE_BET_MAX_AGE:
        await callback.answer(
            "Ставка устарела.",
            show_alert=True,
        )
        return

    if action not in ("repeat", "double"):
        await callback.answer()
        return

    stake = int(last_bet["stake"])

    if action == "double":
        stake *= 2

    await callback.answer("Ставка отправлена.")

    await roulette_add_bet(
        callback.message,
        stake,
        last_bet["selections"],
    )


# ------------------------- TRANSFERS -------------------------

async def resolve_target_user(
    message: Message,
    target: Optional[str],
):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id

    if not target:
        return None

    if target.startswith("@"):
        user = await get_user_by_username(target)
        return user["user_id"] if user else None

    if target.isdigit():
        return int(target)

    return None


@dp.message(F.text.regexp(r"(?i)^перевод\b"))
async def transfer_handler(message: Message):
    parts = message.text.split()

    if message.reply_to_message:
        if len(parts) < 2:
            await message.answer(
                tr("ru", "transfer_usage"),
            )
            return

        target_id = await resolve_target_user(
            message,
            None,
        )

        amount = safe_int(parts[1])

    else:
        if len(parts) != 3:
            await message.answer(
                tr("ru", "transfer_usage"),
            )
            return

        target_id = await resolve_target_user(
            message,
            parts[1],
        )

        amount = safe_int(parts[2])

    if not target_id or amount <= 0:
        await message.answer(
            tr("ru", "transfer_failed"),
        )
        return

    await ensure_user(message.from_user)

    target_user = await get_user(target_id)

    if not target_user:
        await message.answer(
            "Получатель ещё не запускал бота.",
        )
        return

    sender = await get_user(message.from_user.id)

    if sender["transfers_blocked"] or target_user["transfers_blocked"]:
        await message.answer(
            tr("ru", "transfer_blocked"),
        )
        return

    success = await transfer_tokens(
        message.from_user.id,
        target_id,
        amount,
    )

    if success:
        await message.answer(
            tr("ru", "transfer_success", amount=f"{amount:,}"),
        )
    else:
        await message.answer(
            tr("ru", "transfer_failed"),
        )


# ------------------------- GROUP COMMANDS --------------------

@dp.message(F.text.regexp(r"(?i)^б$"))
async def group_balance_handler(message: Message):
    await ensure_user(message.from_user)

    user = await get_user(message.from_user.id)

    sent = await message.answer(
        f"💰 {message.from_user.full_name}\n"
        f"Баланс: {user['balance']:,} TOKENS"
    )

    await delete_after_send(
        sent,
        GROUP_DELETE_SECONDS,
    )


@dp.message(F.text.regexp(r"(?i)^лог$"))
async def group_log_handler(message: Message):
    rows = await db_fetchall(
        """
        SELECT number, color
        FROM roulette_history
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (message.chat.id,),
    )

    if not rows:
        text = "История рулетки пока пуста."
    else:
        lines = ["🎡 Последние результаты:"]

        for row in rows:
            lines.append(
                f"{row['number']} — {row['color']}"
            )

        text = "\n".join(lines)

    sent = await message.answer(text)

    await delete_after_send(
        sent,
        GROUP_DELETE_SECONDS,
    )


@dp.message(F.text.regexp(r"(?i)^топ$"))
async def group_top_handler(message: Message):
    text = await build_top_text()

    sent = await message.answer(text)

    await delete_after_send(
        sent,
        GROUP_DELETE_SECONDS,
    )


@dp.message(F.text.regexp(r"(?i)^бот$"))
async def group_bot_handler(message: Message):
    sent = await message.answer(
        tr("ru", "bot_here"),
    )

    await delete_after_send(
        sent,
        GROUP_DELETE_SECONDS,
    )


@dp.message(F.text.regexp(r"(?i)^что нового$"))
async def group_updates_handler(message: Message):
    image = generate_success_image("ОБНОВЛЕНИЯ")

    sent = await message.answer_photo(
        BufferedInputFile(
            image,
            filename="updates.png",
        ),
        caption=tr("ru", "new_updates"),
    )

    await delete_after_send(
        sent,
        GROUP_DELETE_SECONDS,
    )


# ------------------------- ADMIN HELPERS ---------------------

async def admin_target_from_message(
    message: Message,
    args: list,
    amount_position: Optional[int] = None,
):
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id

        if amount_position is None:
            return target_id, args

        return target_id, args[amount_position:]

    if not args:
        return None, []

    target_token = args[0]

    if target_token.startswith("@"):
        user = await get_user_by_username(target_token)

        if not user:
            return None, args[1:]

        return user["user_id"], args[1:]

    if target_token.isdigit():
        return int(target_token), args[1:]

    return None, args[1:]


async def admin_send_error(message: Message, text: str):
    image = generate_error_image("НЕТ ДОСТУПА")

    sent = await message.answer_photo(
        BufferedInputFile(
            image,
            filename="admin_error.png",
        ),
        caption=text,
    )

    await delete_after_send(
        sent,
        PRIVATE_DELETE_SECONDS if is_private(message) else GROUP_DELETE_SECONDS,
    )


def parse_admin_command(text: str):
    parts = text.strip().split()

    if not parts:
        return None, []

    command = parts[0].lower()

    if not command.startswith("@"):
        return None, []

    return command, parts[1:]


# ------------------------- ADMIN HELP ------------------------

ADMIN_HELP_TEXT = """
🛡 TOKENS ADMIN

@помощь — список команд
@скан ID или @username — информация о пользователе
@выдать ID сумма — начислить TOKENS
@дроп ID сумма — списать TOKENS
@бан ID — заблокировать пользователя
@разбан ID — снять блокировку
@стата — общая статистика
@рассылка текст — рассылка
@очистить_лог ID — очистить историю пользователя
@топ — список лидеров
@баланс ID — баланс пользователя
@чек payload — проверить платёж
"""


@dp.message(F.text.regexp(r"(?i)^@помощь$"))
async def admin_help_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    await message.answer(ADMIN_HELP_TEXT)


@dp.message(F.text.regexp(r"(?i)^@скан\b"))
async def admin_scan_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, _ = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id:
        await message.answer(
            "Использование: @скан ID или ответом на сообщение."
        )
        return

    user = await get_user(target_id)

    if not user:
        await message.answer(
            tr("ru", "admin_user_not_found"),
        )
        return

    image = generate_scanner_image(user)

    await message.answer_photo(
        BufferedInputFile(
            image,
            filename="scanner.png",
        ),
        caption=f"Скан пользователя {target_id}",
    )


@dp.message(F.text.regexp(r"(?i)^@выдать\b"))
async def admin_give_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, remaining = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id or not remaining:
        await message.answer(
            "Использование: @выдать ID сумма или ответом @выдать сумма"
        )
        return

    amount = safe_int(remaining[0])

    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return

    if not await get_user(target_id):
        await message.answer(
            tr("ru", "admin_user_not_found"),
        )
        return

    success = await change_balance(
        target_id,
        amount,
        f"Выдача администратора {message.from_user.id}",
    )

    if success:
        await message.answer(
            f"Начислено {amount:,} TOKENS пользователю {target_id}."
        )
    else:
        await message.answer("Не удалось начислить TOKENS.")


@dp.message(F.text.regexp(r"(?i)^@дроп\b"))
async def admin_drop_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, remaining = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id or not remaining:
        await message.answer(
            "Использование: @дроп ID сумма или ответом @дроп сумма"
        )
        return

    amount = safe_int(remaining[0])

    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return

    success = await change_balance(
        target_id,
        -amount,
        f"Списание администратора {message.from_user.id}",
    )

    if success:
        await message.answer(
            f"Списано {amount:,} TOKENS у пользователя {target_id}."
        )
    else:
        await message.answer(
            "Не удалось списать средства. Возможно, недостаточно баланса."
        )


@dp.message(F.text.regexp(r"(?i)^@бан\b"))
async def admin_ban_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, _ = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id:
        await message.answer(
            "Использование: @бан ID или ответом."
        )
        return

    await set_user_ban(
        target_id,
        0,
    )

    await message.answer(
        f"Пользователь {target_id} заблокирован."
    )


@dp.message(F.text.regexp(r"(?i)^@разбан\b"))
async def admin_unban_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, _ = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id:
        await message.answer(
            "Использование: @разбан ID или ответом."
        )
        return

    await db_execute(
        """
        UPDATE users
        SET is_banned = 0, ban_until = 0
        WHERE user_id = ?
        """,
        (target_id,),
    )

    await message.answer(
        f"Пользователь {target_id} разблокирован."
    )


@dp.message(F.text.regexp(r"(?i)^@стата$"))
async def admin_stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    stats = await get_global_stats()

    await message.answer(
        "📊 TOKENS STATISTICS\n\n"
        f"Пользователей: {stats.get('users', 0):,}\n"
        f"Всего балансов: {stats.get('balance', 0):,}\n"
        f"Донатов Stars: {stats.get('donated_stars', 0):,}\n"
        f"Рефералов: {stats.get('referrals', 0):,}"
    )


@dp.message(F.text.regexp(r"(?i)^@топ$"))
async def admin_top_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    await message.answer(
        await build_top_text(),
    )


@dp.message(F.text.regexp(r"(?i)^@баланс\b"))
async def admin_balance_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, _ = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id:
        await message.answer(
            "Использование: @баланс ID или ответом."
        )
        return

    user = await get_user(target_id)

    if not user:
        await message.answer(
            tr("ru", "admin_user_not_found"),
        )
        return

    await message.answer(
        f"Баланс {target_id}: {user['balance']:,} TOKENS"
    )


@dp.message(F.text.regexp(r"(?i)^@чек\b"))
async def admin_check_payment_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Использование: @чек payload"
        )
        return

    row = await db_fetchone(
        "SELECT * FROM payments WHERE payload = ?",
        (parts[1].strip(),),
    )

    if not row:
        await message.answer("Платёж не найден.")
        return

    await message.answer(
        f"Платёж: {row['payload']}\n"
        f"Пользователь: {row['user_id']}\n"
        f"Stars: {row['stars']}\n"
        f"Tokens: {row['tokens']}\n"
        f"Тип: {row['payment_type']}\n"
        f"Статус: {row['status']}"
    )


@dp.message(F.text.regexp(r"(?i)^@очистить_лог\b"))
async def admin_clear_log_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split()[1:]

    target_id, _ = await admin_target_from_message(
        message,
        parts,
    )

    if not target_id:
        await message.answer(
            "Использование: @очистить_лог ID"
        )
        return

    await db_execute(
        "DELETE FROM game_log WHERE user_id = ?",
        (target_id,),
    )

    await db_execute(
        "DELETE FROM transactions WHERE user_id = ?",
        (target_id,),
    )

    await message.answer(
        f"Логи пользователя {target_id} очищены."
    )


@dp.message(F.text.regexp(r"(?i)^@рассылка\b"))
async def admin_broadcast_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Использование: @рассылка текст сообщения"
        )
        return

    text = parts[1]

    rows = await db_fetchall(
        "SELECT user_id FROM users WHERE is_banned = 0",
    )

    success_count = 0
    failed_count = 0

    status = await message.answer(
        f"Рассылка началась. Получателей: {len(rows)}"
    )

    for row in rows:
        user_id = row["user_id"]

        try:
            await bot.send_message(
                user_id,
                text,
            )

            success_count += 1

        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)

            try:
                await bot.send_message(user_id, text)
                success_count += 1
            except Exception:
                failed_count += 1

        except (TelegramForbiddenError, TelegramBadRequest):
            failed_count += 1

        except Exception:
            failed_count += 1

        await asyncio.sleep(0.05)

    await status.edit_text(
        "Рассылка завершена.\n"
        f"Успешно: {success_count}\n"
        f"Ошибок: {failed_count}"
    )


# ------------------------- ADMIN BACKUP ----------------------

@dp.message(F.text.regexp(r"(?i)^@бекап$"))
async def admin_backup_handler(message: Message):
    if not is_admin(message.from_user.id):
        await admin_send_error(
            message,
            tr("ru", "admin_denied"),
        )
        return

    backup_path = Path(
        tempfile.gettempdir()
    ) / f"tokens_backup_{now_ts()}.sqlite3"

    try:
        async with db_lock:
            await db_conn.execute("PRAGMA wal_checkpoint(FULL)")
            await db_conn.commit()

        def create_backup():
            source = sqlite3.connect(DATABASE_PATH)
            destination = sqlite3.connect(str(backup_path))

            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

        await asyncio.to_thread(create_backup)

        await message.answer_document(
            BufferedInputFile(
                backup_path.read_bytes(),
                filename=backup_path.name,
            ),
            caption="Резервная копия базы TOKENS.",
        )

    except Exception as exc:
        logger.exception("Backup failed")
        await message.answer(
            f"Ошибка резервного копирования: {exc}"
        )

    finally:
        try:
            backup_path.unlink(missing_ok=True)
        except Exception:
            pass


# ------------------------- VIP AUTO BONUS --------------------

async def vip_auto_bonus_worker():
    """
    Периодическая проверка VIP пользователей.
    Если прошло 12 часов, автоматически начисляет бонус.
    Для автоматического сбора пользователь должен быть VIP.
    """

    while True:
        try:
            rows = await db_fetchall(
                """
                SELECT u.user_id, u.balance, u.vip_until, u.vip_auto_bonus,
                       b.last_claim
                FROM users u
                LEFT JOIN bonus b ON b.user_id = u.user_id
                WHERE u.vip_until > ?
                  AND u.vip_auto_bonus = 1
                  AND u.is_banned = 0
                """,
                (now_ts(),),
            )

            for row in rows:
                user_id = row["user_id"]

                if row["balance"] > BONUS_BALANCE_LIMIT:
                    continue

                last_claim = row["last_claim"] or 0

                if now_ts() - last_claim < BONUS_COOLDOWN:
                    continue

                subscription = await check_subscription(user_id)

                if subscription is not True:
                    continue

                success, amount = await claim_bonus(user_id)

                if not success:
                    continue

                try:
                    await bot.send_message(
                        user_id,
                        f"⭐ VIP автоматически собрал бонус: +{amount:,} TOKENS!",
                    )
                except Exception:
                    pass

                await asyncio.sleep(0.2)

        except Exception:
            logger.exception("VIP auto bonus worker failed")

        await asyncio.sleep(60)


# ------------------------- PERIODIC MAINTENANCE ---------------

async def maintenance_worker():
    while True:
        try:
            expired_bans = await db_fetchall(
                """
                SELECT user_id
                FROM users
                WHERE is_banned = 1
                  AND ban_until > 0
                  AND ban_until <= ?
                """,
                (now_ts(),),
            )

            for row in expired_bans:
                await db_execute(
                    """
                    UPDATE users
                    SET is_banned = 0, ban_until = 0
                    WHERE user_id = ?
                    """,
                    (row["user_id"],),
                )

            await db_execute(
                """
                DELETE FROM payments
                WHERE status = 'pending'
                  AND created_at < ?
                """,
                (now_ts() - 7 * 86400,),
            )

        except Exception:
            logger.exception("Maintenance worker failed")

        await asyncio.sleep(300)


# ------------------------- ERROR HANDLING --------------------

@dp.errors()
async def global_error_handler(event):
    logger.exception(
        "Unhandled update error",
        exc_info=event.exception,
    )

    return True


# ------------------------- HEALTH SERVER ---------------------

async def health_handler(request: web.Request):
    return web.json_response({
        "status": "ok",
        "service": "TOKENS",
        "timestamp": now_ts(),
    })


async def root_handler(request: web.Request):
    return web.Response(
        text="TOKENS bot is running",
        content_type="text/plain",
    )


async def start_health_server():
    global http_runner

    app = web.Application()

    app.router.add_get("/", root_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/healthz", health_handler)

    http_runner = web.AppRunner(app)

    await http_runner.setup()

    site = web.TCPSite(
        http_runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info(
        "Health server started on port %s",
        PORT,
    )


async def stop_health_server():
    global http_runner

    if http_runner is not None:
        await http_runner.cleanup()
        http_runner = None


# ------------------------- STARTUP CHECKS --------------------

async def startup_checks():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Добавь переменную окружения BOT_TOKEN."
        )

    if not ADMIN_IDS:
        logger.warning(
            "ADMIN_ID не задан. Административные команды будут недоступны."
        )

    if not NEWS_CHANNEL:
        logger.warning(
            "NEWS_CHANNEL не задан."
        )

    ASSETS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


# ------------------------- DEFAULT MESSAGE -------------------

@dp.message()
async def fallback_handler(message: Message):
    if not message.text:
        return

    user = await get_user(message.from_user.id)

    if not user:
        return

    if await user_is_banned(message.from_user.id):
        return

    language = user_language(user)

    known_buttons = {
        tr(language, "menu_play"),
        tr(language, "menu_bonus"),
        tr(language, "menu_donate"),
        tr(language, "menu_profile"),
        tr(language, "menu_top"),
        tr(language, "menu_ref"),
    }

    if message.text in known_buttons:
        return

    if is_private(message):
        # Не удаляем произвольный пользовательский текст.
        return


# ------------------------- BOT STARTUP -----------------------

async def main():
    global bot
    global bot_username
    global bot_display_name

    await startup_checks()

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    me = await bot.get_me()

    bot_username = me.username or "TOKENS_BOT"
    bot_display_name = me.full_name or "TOKENS"

    logger.info(
        "Starting @%s (%s)",
        bot_username,
        me.id,
    )

    await start_health_server()

    schedule_task(vip_auto_bonus_worker())
    schedule_task(maintenance_worker())

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:
        for task in list(background_tasks):
            task.cancel()

        if background_tasks:
            await asyncio.gather(
                *background_tasks,
                return_exceptions=True,
            )

        await stop_health_server()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())