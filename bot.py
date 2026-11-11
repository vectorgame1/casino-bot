# =============================================================================
#  TOKENS BOT — Telegram Game Bot
#  Python 3.13 | aiogram 3.x | aiosqlite | aiohttp | apscheduler
#  Deploy target: Render
#  -----------------------------------------------------------------------------
#  ЧАСТЬ 1 / 10:
#    - Импорты
#    - Константы и конфигурация
#    - Логирование (ротация, формат, уровни)
#    - Удаление старой БД при старте (требование Render)
#    - Валидация переменных окружения
#    - Текстовые константы (гайды, приветствия, ошибки)
#    - Вспомогательные утилиты (format_money, parse_int, safe_str)
# =============================================================================

from __future__ import annotations

# -----------------------------------------------------------------------------
#  СТАНДАРТНАЯ БИБЛИОТЕКА
# -----------------------------------------------------------------------------
import os
import sys
import re
import asyncio
import logging
import logging.handlers
import random
import time
import json
import math
import html
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union, Sequence, Iterable
from dataclasses import dataclass, field
from enum import Enum, IntEnum

# -----------------------------------------------------------------------------
#  AIOGRAM 3.x
# -----------------------------------------------------------------------------
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType, ChatMemberStatus
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
    BufferedInputFile,
    InputFile,
    ChatMemberUpdated,
    ChatPermissions,
    LinkPreviewOptions,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    Update,
    User as TgUser,
    Chat as TgChat,
    PreCheckoutQuery,
    LabeledPrice,
    SuccessfulPayment,
    TelegramObject,
)
from aiogram.filters import Command, CommandStart, CommandObject, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
    TelegramNotFound,
    TelegramConflictError,
    TelegramServerError,
    TelegramNetworkError,
    RestartingTelegram,
)
from aiogram.types.error_event import ErrorEvent

# -----------------------------------------------------------------------------
#  AIOHTTP (веб-сервер для Render healthcheck)
# -----------------------------------------------------------------------------
from aiohttp import web

# -----------------------------------------------------------------------------
#  AIOSQLITE (асинхронная обёртка над SQLite)
# -----------------------------------------------------------------------------
import aiosqlite

# -----------------------------------------------------------------------------
#  APSCHEDULER (автодропы, джекпот, очистка, напоминания)
# -----------------------------------------------------------------------------
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

# -----------------------------------------------------------------------------
#  ЗАЩИТА ОТ ПРЯМОГО ИМПОРТА НЕСОВМЕСТИМЫХ ВЕРСИЙ
# -----------------------------------------------------------------------------
if sys.version_info < (3, 10):
    raise RuntimeError(
        "TOKENS BOT требует Python 3.10+ (целевая платформа — 3.13). "
        f"Текущая версия: {sys.version_info.major}.{sys.version_info.minor}"
    )


# =============================================================================
#  КОНСТАНТЫ ПРОЕКТА
# =============================================================================
# Все "магические числа" собраны здесь, чтобы в остальных частях кода
# не было разбросанных литералов. Это облегчает тюнинг экономики бота.

BOT_NAME: str = "TOKENS"
BOT_VERSION: str = "1.0.0"
BOT_EMOJI: str = "💎"

# --- Пути ---------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
IMAGES_DIR: Path = BASE_DIR / "images"
DB_DIR: Path = BASE_DIR / "data"
DB_PATH: str = str(DB_DIR / "tokens.db")
LOG_DIR: Path = BASE_DIR / "logs"
LOG_FILE: str = str(LOG_DIR / "bot.log")

# Каталог images может отсутствовать при первом деплое — создаём.
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Экономика ----------------------------------------------------------
START_BALANCE: int = 5_000            # новичкам при /start
DAILY_BONUS_AMOUNT: int = 5_000       # ежедневный бонус
DAILY_BONUS_COOLDOWN: int = 24 * 3600 # 24 часа в секундах
REFERRAL_REWARD: int = 10_000         # за приглашённого друга (после 1-й игры)
VIP_PRICE: int = 50_000               # цена VIP в TOKENS
VIP_DURATION_DAYS: int = 30           # срок VIP
VIP_WIN_BONUS: float = 0.05           # +5% к выигрышу для VIP

# Курс доната: 1 ⭐ = 7500 TOKENS
STAR_TO_TOKENS: int = 7_500
DONATE_PRESETS: tuple[int, ...] = (50, 100, 250, 500)  # кнопки в меню доната

# --- Ограничения --------------------------------------------------------
TG_MSG_LIMIT: int = 4_096             # жёсткий лимит Telegram
TG_SAFE_LIMIT: int = 4_000            # безопасный лимит для safe_send
TG_CAPTION_LIMIT: int = 1_024         # лимит подписи к фото
GAME_COOLDOWN_SEC: float = 3.0        # антиспам: минимум между играми
FLOOD_SLEEP: float = 0.05             # микро-пауза после каждого хендлера
ROULETTE_ANIM_PAUSE: float = 3.0      # пауза перед результатом рулетки
GAME_AUTODELETE_SEC: int = 60         # автоудаление сообщений игр
MAX_TEXT_INPUT_LEN: int = 200         # защита от гигантских вводов

# --- Игры ---------------------------------------------------------------
GAME_DICE_EMOJI: dict[str, str] = {
    "кости":   "🎲",   # 1..6
    "дартс":   "🎯",   # 1..6
    "баскет":  "🏀",   # 1..5
    "футбол":  "⚽",   # 1..5
    "боулинг": "🎳",   # 1..6
    "бж":      "🎰",   # 1..64 (слоты)
    "слоты":   "🎰",   # синоним
}
# Порог, выше которого выигрыш x2 (для кубиков). Для слотов — отдельная логика.
DICE_WIN_THRESHOLD: int = 3

# Мины
MINES_FIELD_SIZE: int = 5            # поле 5x5 = 25 клеток
MINES_COUNT: int = 3                 # 3 мины
MINES_STEP_MULT: float = 0.15        # +15% за каждую открытую клетку

# Дуэли
DUEL_COMMISSION: float = 0.05        # 5% комиссия с банка

# --- Рулетка ------------------------------------------------------------
ROULETTE_MIN_BET: int = 50
ROULETTE_MAX_BET: int = 1_000_000
ROULETTE_MULT_COLOR: int = 2         # красное/чёрное — x2
ROULETTE_MULT_PARITY: int = 2        # чёт/нечет — x2
ROULETTE_MULT_RANGE: int = 3         # диапазон 10-20 — x3
ROULETTE_MULT_EXACT: int = 36        # точное число 0..36 — x36
ROULETTE_MAX_NUM: int = 36

# --- Промокоды ----------------------------------------------------------
PROMO_CODE_MIN_LEN: int = 3
PROMO_CODE_MAX_LEN: int = 32
PROMO_MAX_USES_DEFAULT: int = 1

# --- Админка ------------------------------------------------------------
ADMIN_LOG_LIMIT_DEFAULT: int = 20
CLEAN_CHAT_LIMIT_DEFAULT: int = 50

# --- Автоматизация ------------------------------------------------------
AUTO_DROP_INTERVAL_HOURS: int = 2
AUTO_DROP_MIN_AMOUNT: int = 500
AUTO_DROP_MAX_AMOUNT: int = 5_000
JACKPOT_INTERVAL_HOURS: int = 1
CLEANUP_INTERVAL_HOURS: int = 24
INACTIVE_REMIND_DAYS: int = 7


# =============================================================================
#  ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (Render)
# =============================================================================
# Render передаёт PORT автоматически. BOT_TOKEN и ADMIN_ID задаём в Dashboard.
# Читаем "лениво" в функции load_env(), чтобы ошибки были понятными.

@dataclass(slots=True)
class EnvConfig:
    """Валидированная конфигурация окружения."""
    bot_token: str
    admin_id: int
    port: int
    webhook_secret: Optional[str] = None
    is_debug: bool = False


def _env_get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Безопасное чтение env. Возвращает None, если пусто."""
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


def load_env() -> EnvConfig:
    """
    Читает и валидирует переменные окружения.
    Бросает RuntimeError с понятным сообщением, если что-то не так —
    чтобы контейнер на Render упал сразу, а не через 5 минут работы.
    """
    token = _env_get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Не задана переменная окружения BOT_TOKEN. "
            "Добавьте её в Render Dashboard → Environment."
        )
    # Токен Telegram-бота: <digits>:<base64-ish>. Проверяем грубо, но полезно.
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", token):
        raise RuntimeError(
            "BOT_TOKEN не похож на валидный токен Telegram-бота "
            "(ожидался формат '<id>:<hash>'). Проверьте значение."
        )

    admin_raw = _env_get("ADMIN_ID")
    if not admin_raw:
        raise RuntimeError(
            "Не задана переменная окружения ADMIN_ID. "
            "Укажите Telegram user_id главного администратора."
        )
    try:
        admin_id = int(admin_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"ADMIN_ID должен быть целым числом, получено: {admin_raw!r}"
        ) from exc

    port_raw = _env_get("PORT", "8080") or "8080"
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError(f"PORT должен быть числом, получено: {port_raw!r}") from exc
    if not (1 <= port <= 65_535):
        raise RuntimeError(f"PORT вне диапазона 1..65535: {port}")

    is_debug = (_env_get("DEBUG", "0") or "0") in ("1", "true", "True", "yes")
    webhook_secret = _env_get("WEBHOOK_SECRET")

    return EnvConfig(
        bot_token=token,
        admin_id=admin_id,
        port=port,
        webhook_secret=webhook_secret,
        is_debug=is_debug,
    )


# Загружаем конфиг на импорте модуля — падаем сразу, если env неверные.
try:
    ENV: EnvConfig = load_env()
except RuntimeError as _env_err:
    # Пишем в stderr максимально явно — Render это покажет в логах.
    print(f"[FATAL] Ошибка конфигурации: {_env_err}", file=sys.stderr)
    raise


# =============================================================================
#  ЛОГИРОВАНИЕ
# =============================================================================
# Двойной вывод: stdout (Render парсит) + файл с ротацией (для отладки).
# Формат: время | уровень | модуль | сообщение.

_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s"
_LOG_DATEFMT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> logging.Logger:
    """
    Настраивает корневой логгер:
      - stdout (уровень INFO, либо DEBUG при DEBUG=1)
      - файл logs/bot.log с ротацией 5MB × 3 (уровень DEBUG)
      - приглушает шумные сторонние логгеры (aiogram, aiohttp, apscheduler)
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Защита от повторной инициализации при перезагрузке модуля.
    if getattr(root, "_tokens_configured", False):
        return logging.getLogger("tokens")

    console_level = logging.DEBUG if ENV.is_debug else logging.INFO
    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))

    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))

    root.addHandler(console)
    root.addHandler(file_handler)

    # Приглушаем болтливые библиотеки.
    for noisy in (
        "aiogram.event",
        "aiogram.dispatcher",
        "aiogram.bot.api",
        "aiohttp.access",
        "aiohttp.client",
        "apscheduler.executors.default",
        "apscheduler.scheduler",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._tokens_configured = True  # type: ignore[attr-defined]
    return logging.getLogger("tokens")


log: logging.Logger = setup_logging()


def log_exception(context: str, exc: BaseException) -> None:
    """
    Единая точка логирования исключений.
    Не «глотает» ошибку — пишет полный traceback, чтобы дебажить на Render.
    """
    log.error(
        "Исключение в [%s]: %s: %s\n%s",
        context,
        type(exc).__name__,
        exc,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


# =============================================================================
#  УДАЛЕНИЕ СТАРОЙ БД (требование Render)
# =============================================================================
# ВАЖНО: на Render диск эфемерный, но при рестарте контейнера в том же
# инстансе файл может остаться. По ТЗ старую БД нужно удалять при старте.
# Функция вызывается из main() (ЧАСТЬ 10) ДО открытия соединения.

def purge_old_database() -> None:
    """
    Удаляет файл БД (если существует) и связанные WAL/SHM журналы.
    Безопасно вызывать многократно.
    """
    targets = [Path(DB_PATH), Path(DB_PATH + "-wal"), Path(DB_PATH + "-shm")]
    for path in targets:
        try:
            if path.exists():
                path.unlink()
                log.warning("Удалён старый файл БД: %s", path)
        except OSError as exc:
            log_exception(f"purge_old_database({path})", exc)


# =============================================================================
#  ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ
# =============================================================================
# Общие функции, используемые во всех последующих частях.

_NUM_RE = re.compile(r"^[+-]?\d{1,15}$")


def parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """
    Безопасный парсинг целого числа из пользовательского ввода.
    Поддерживает '1_000', '1000', '+500'. Возвращает default при ошибке.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    s = str(value).strip().replace("_", "").replace(" ", "")
    if not s:
        return default
    if not _NUM_RE.match(s):
        return default
    try:
        return int(s)
    except (ValueError, OverflowError):
        return default


def parse_positive_int(value: Any) -> Optional[int]:
    """Возвращает положительное целое или None (для ставок)."""
    n = parse_int(value)
    if n is None or n <= 0:
        return None
    return n


def format_money(amount: Union[int, float]) -> str:
    """
    Форматирует сумму с разделителями: 1234567 -> '1 234 567'.
    Отрицательные сохраняют знак. Дробные округляются вниз до int.
    """
    try:
        if isinstance(amount, float):
            amount = int(amount)
        return f"{int(amount):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def format_duration(seconds: int) -> str:
    """Секунды -> '1ч 23м 45с' / '5м 10с' / '30с'."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s or not parts:
        parts.append(f"{s}с")
    return " ".join(parts)


def utcnow_iso() -> str:
    """Текущее UTC-время в ISO8601 (для полей created_at)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utcnow_ts() -> int:
    """Текущий UNIX timestamp (секунды)."""
    return int(time.time())


def now_day_key() -> str:
    """Ключ текущих суток UTC (для дедупликации дневных наград)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def safe_str(text: Any, limit: int = MAX_TEXT_INPUT_LEN) -> str:
    """Убирает управляющие символы и обрезает до limit."""
    s = str(text)
    s = "".join(ch for ch in s if ch == "\n" or ch.isprintable())
    return s[:limit]


def html_escape(text: Any) -> str:
    """Экранирует HTML-сущности для parse_mode=HTML."""
    return html.escape(str(text), quote=False)


def mdv2_escape(text: Any) -> str:
    """
    Экранирует спецсимволы MarkdownV2.
    Используется, если в будущем захотим переключить часть сообщений на MDv2.
    """
    s = str(text)
    reserved = r"_*[]()~`>#+-=|{}.!\\"
    return "".join("\\" + ch if ch in reserved else ch for ch in s)


def chunk_text(text: str, limit: int = TG_SAFE_LIMIT) -> list[str]:
    """
    Разбивает длинный текст на куски <= limit, стараясь резать по '\n'.
    Гарантирует, что ни один кусок не превысит лимит Telegram.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def clamp(value: int, lo: int, hi: int) -> int:
    """Ограничивает value диапазоном [lo, hi]."""
    return max(lo, min(hi, value))


def humanize_username(user: Optional[TgUser]) -> str:
    """Человекопонятное имя пользователя для логов/отображения."""
    if user is None:
        return "неизвестный"
    if user.username:
        return f"@{user.username}"
    if user.full_name:
        return user.full_name
    return f"id{user.id}"


def mention_html(user_id: int, name: str) -> str:
    """HTML-упоминание, работающее даже без username."""
    return f'<a href="tg://user?id={user_id}">{html_escape(name)}</a>'


# =============================================================================
#  ТЕКСТОВЫЕ КОНСТАНТЫ
# =============================================================================
# Единый источник правды для всех пользовательских текстов.
# В ЧАСТИ 5 их отдаём через хендлеры меню.

# --- /start ------------------------------------------------------------
TEXT_START: str = (
    f"{BOT_EMOJI} <b>Добро пожаловать в {BOT_NAME}!</b>\n\n"
    "Это игровой бот с экономикой, рулеткой, дуэлями и ежедневными бонусами.\n\n"
    f"🎁 Тебе начислено <b>{format_money(START_BALANCE)} TOKENS</b> на старт!\n"
    "🎮 Используй меню ниже, чтобы начать играть.\n\n"
    "📖 Если не знаешь с чего начать — открой «Как играть»."
)

# --- Гайд «Как играть» (1500+ символов) --------------------------------
TEXT_HOW_TO_PLAY: str = (
    "🎮 <b>КАК ИГРАТЬ В TOKENS</b>\n\n"
    f"{BOT_EMOJI} <b>Что такое TOKENS?</b>\n"
    "TOKENS — внутренняя валюта бота. Зарабатывай её в играх, "
    "получай бонусы и соревнуйся с другими игроками в топе.\n\n"
    "🎲 <b>1. Игры на кубиках</b>\n"
    "Команды: <code>кости 1000</code>, <code>дартс 500</code>, "
    "<code>баскет 1000</code>, <code>футбол 2000</code>, "
    "<code>боулинг 1000</code>, <code>бж 1000</code>, "
    "<code>слоты 1000</code>.\n"
    "• Если выпадает больше 3 — выигрыш ×2.\n"
    "• Ставка списывается сразу, результат приходит через пару секунд.\n"
    "• Сообщение с результатом удаляется автоматически через 60 сек.\n\n"
    "💣 <b>2. Мины</b>\n"
    "Команда: <code>мины 1000</code>.\n"
    "Поле 5×5, спрятано 3 мины. Открывай клетки и забирай выигрыш.\n"
    "• Каждая открытая клетка даёт +15% к ставке.\n"
    "• Наткнулся на мину — теряешь всё.\n"
    "• Кнопка «💰 Забрать» фиксирует текущий выигрыш.\n\n"
    "⚔️ <b>3. Дуэли</b>\n"
    "Команда: <code>дуэль @username 1000</code>.\n"
    "• Соперник принимает вызов кнопкой.\n"
    "• Бросаются кубики, победитель забирает банк минус 5% комиссии.\n\n"
    "🎡 <b>4. Рулетка (главная фишка)</b>\n"
    "Запуск: <code>старт 1000</code> — затем пиши ставки сообщениями:\n"
    "• <code>к 500</code> / <code>ч 500</code> — красное/чёрное (×2)\n"
    "• <code>1000 чет</code> / <code>1000 нечет</code> — чёт/нечет (×2)\n"
    "• <code>500 10-20</code> — диапазон (×3)\n"
    "• <code>100 7</code> — точное число 0..36 (×36)\n"
    "После сбора ставок бот крутит рулетку и выдаёт результат.\n"
    "Кнопки «Повторить» и «Удвоить» ускоряют игру.\n\n"
    "🎁 <b>5. Бонусы</b>\n"
    "• Ежедневный бонус: 5 000 TOKENS раз в 24 часа.\n"
    "• Промокоды: вводи <code>промо КОД</code>.\n"
    "• Автодропы в игровых чатах — лови кнопки с TOKENS.\n\n"
    "👥 <b>6. Рефералы</b>\n"
    "Приглашай друзей по своей ссылке из профиля. "
    "За каждого друга, который сыграет хотя бы одну игру, "
    "ты получишь 10 000 TOKENS.\n\n"
    "⭐ <b>7. VIP</b>\n"
    "Покупка VIP за 50 000 TOKENS на 30 дней даёт +5% к выигрышу "
    "и бейдж ⭐ VIP в профиле.\n\n"
    "🏆 <b>8. Топ и достижения</b>\n"
    "Смотри рейтинг в «Топ», открывай достижения в профиле.\n\n"
    "💡 <b>Совет:</b> не ставь всё сразу — рулетка любит терпеливых."
)

# --- Команды -----------------------------------------------------------
TEXT_COMMANDS: str = (
    "📖 <b>КОМАНДЫ БОТА</b>\n\n"
    "🎲 <b>Игры:</b>\n"
    "• <code>кости СТАВКА</code>\n"
    "• <code>дартс СТАВКА</code>\n"
    "• <code>баскет СТАВКА</code>\n"
    "• <code>футбол СТАВКА</code>\n"
    "• <code>боулинг СТАВКА</code>\n"
    "• <code>бж СТАВКА</code> / <code>слоты СТАВКА</code>\n"
    "• <code>мины СТАВКА</code>\n"
    "• <code>дуэль @username СТАВКА</code>\n\n"
    "🎡 <b>Рулетка:</b>\n"
    "• <code>старт СТАВКА</code> — начать сессию\n"
    "• <code>к СТАВКА</code> / <code>ч СТАВКА</code> — цвет\n"
    "• <code>СТАВКА чет</code> / <code>СТАВКА нечет</code>\n"
    "• <code>СТАВКА 10-20</code> — диапазон\n"
    "• <code>СТАВКА 7</code> — точное число\n\n"
    "💰 <b>Экономика:</b>\n"
    "• <code>промо КОД</code> — активировать промокод\n"
    "• <code>перевод @username СУММА</code> — перевести TOKENS\n"
    "• <code>подарок @username СУММА</code> — подарить TOKENS\n\n"
    "👤 <b>Профиль:</b>\n"
    "• <code>профиль</code> — открыть профиль\n"
    "• <code>бонус</code> — ежедневный бонус\n"
    "• <code>топ</code> — рейтинг игроков\n"
    "• <code>баланс</code> — быстро узнать баланс\n\n"
    "🆘 <b>Поддержка:</b>\n"
    "• <code>поддержка</code> — связаться с админом\n"
    "• <code>помощь</code> — это меню"
)

# --- Профиль (шаблон, форматируется в ЧАСТИ 5) --------------------------
TEXT_PROFILE_HEADER: str = "👤 <b>ПРОФИЛЬ</b>"

# --- Поддержка ---------------------------------------------------------
TEXT_SUPPORT: str = (
    "🆘 <b>ПОДДЕРЖКА</b>\n\n"
    "Если возникла проблема — напиши администратору.\n"
    "Опиши ситуацию коротко: что делал, что пошло не так, "
    "приложи скриншот, если возможно.\n\n"
    "⚠️ Не сообщай никому пароли, коды и данные карт."
)

# --- Чаты --------------------------------------------------------------
TEXT_CHATS: str = (
    "💬 <b>НАШИ ЧАТЫ</b>\n\n"
    "🎮 <b>Игровой чат</b> — общение, игры, дропы.\n"
    "🔄 <b>Обмен</b> — обмен TOKENS и услугами.\n"
    "📰 <b>Новости</b> — анонсы обновлений и ивентов.\n\n"
    "Выбирай чат ниже 👇"
)

# --- Донат -------------------------------------------------------------
TEXT_DONATE: str = (
    "💎 <b>ДОНАТ</b>\n\n"
    f"Курс: <b>1 ⭐ = {format_money(STAR_TO_TOKENS)} TOKENS</b>\n\n"
    "Выбери пакет звёзд или введи свою сумму:\n"
    f"• 50 ⭐ = {format_money(50 * STAR_TO_TOKENS)} TOKENS\n"
    f"• 100 ⭐ = {format_money(100 * STAR_TO_TOKENS)} TOKENS\n"
    f"• 250 ⭐ = {format_money(250 * STAR_TO_TOKENS)} TOKENS\n"
    f"• 500 ⭐ = {format_money(500 * STAR_TO_TOKENS)} TOKENS\n\n"
    "⭐ <b>VIP</b> — отдельная покупка за TOKENS в профиле."
)

# --- Бонус -------------------------------------------------------------
TEXT_BONUS_READY: str = (
    "🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС</b>\n\n"
    f"Тебе доступно <b>{format_money(DAILY_BONUS_AMOUNT)} TOKENS</b>!\n"
    "Нажми кнопку ниже, чтобы забрать."
)

TEXT_BONUS_ALREADY: str = (
    "⏳ <b>БОНУС УЖЕ ЗАБРАН</b>\n\n"
    "Возвращайся через: <b>{remain}</b>"
)

# --- Топ ---------------------------------------------------------------
TEXT_TOP_HEADER: str = "🏆 <b>ТОП ИГРОКОВ</b>\n"

# --- Общие ошибки ------------------------------------------------------
TEXT_ERR_GENERIC: str = "⚠️ Что-то пошло не так. Попробуй позже."
TEXT_ERR_NOT_ENOUGH: str = "❌ Недостаточно TOKENS на балансе."
TEXT_ERR_BAD_BET: str = (
    f"❌ Неверная ставка. Минимум: {ROULETTE_MIN_BET}, максимум: {format_money(ROULETTE_MAX_BET)}."
)
TEXT_ERR_COOLDOWN: str = "⏳ Слишком быстро! Подожди {sec} сек."
TEXT_ERR_BANNED: str = "🚫 Ты забанен в боте. Обратись в поддержку."
TEXT_ERR_GAMES_DISABLED: str = "🔒 Игры отключены в этом чате администратором."
TEXT_ERR_PRIVATE_ONLY: str = "ℹ️ Эта команда работает только в личке с ботом."
TEXT_ERR_GROUP_ONLY: str = "ℹ️ Эта команда работает только в группе."
TEXT_ERR_UNKNOWN_CMD: str = "❓ Неизвестная команда. Открой «Команды» в меню."

# --- Ачивки ------------------------------------------------------------
ACHIEVEMENTS: dict[str, str] = {
    "novice":    "🔰 Новичок",
    "lucky":     "🍀 Везунчик",
    "millioner": "💰 Миллионер",
    "roulette":  "🎡 Рулетчик",
    "duelist":   "⚔️ Дуэлянт",
}

ACHIEVEMENTS_DESC: dict[str, str] = {
    "novice":    "Сыграть первую игру",
    "lucky":     "Выиграть 10 игр подряд",
    "millioner": "Накопить 1 000 000 TOKENS",
    "roulette":  "Сделать 50 ставок в рулетке",
    "duelist":   "Выиграть 10 дуэлей",
}

# --- Уровни ------------------------------------------------------------
# XP = сумма ставок / 100 (пример). Уровень = 1 + sqrt(XP/100).
LEVEL_XP_STEP: int = 100


def calc_level(xp: int) -> int:
    """Уровень по XP. Растёт как sqrt — не улетает в космос."""
    if xp <= 0:
        return 1
    return max(1, 1 + int(math.isqrt(max(0, xp) // LEVEL_XP_STEP)))


def xp_to_next_level(xp: int) -> int:
    """Сколько XP осталось до следующего уровня."""
    lvl = calc_level(xp)
    next_threshold = ((lvl) ** 2) * LEVEL_XP_STEP
    return max(0, next_threshold - xp)


# =============================================================================
#  ГЛОБАЛЬНЫЕ РЕЕСТРЫ (in-memory)
# =============================================================================
# Используются для защиты от double-spend и гонок в играх.
# ВАЖНО: один процесс — один набор словарей. На Render всегда 1 инстанс.

# in-flight ставки/игры: user_id -> timestamp
INFLIGHT_LOCKS: dict[int, float] = {}
# активные игровые сессии: user_id -> game_key
ACTIVE_GAME_LOCKS: dict[int, str] = {}
# сессии рулетки: chat_id -> объект (создаётся в ЧАСТИ 8)
ROULETTE_SESSIONS: dict[int, Any] = {}
# активные дуэли: duel_id -> данные (ЧАСТЬ 7)
ACTIVE_DUELS: dict[str, Any] = {}
# state для FSM покупки звёзд и др. — сам FSM в aiogram
# режим бога (админ не тратит баланс) — множество user_id
GOD_MODE_USERS: set[int] = set()
# глобальные настройки в памяти (на случай, если БД недоступна)
RUNTIME_FLAGS: dict[str, Any] = {
    "maintenance": False,       # техработы: блокируют игры
    "jackpot_pool": 0,          # текущий джекпот
}


# =============================================================================
#  БАЗОВЫЕ ДАТА-КЛАССЫ ДЛЯ ТИПИЗАЦИИ
# =============================================================================

@dataclass(slots=True)
class UserRow:
    """Строка таблицы users (см. ЧАСТЬ 2)."""
    user_id: int
    username: Optional[str]
    balance: int
    vip: int
    games: int
    wins: int
    achievements: str          # CSV-строка
    referrer_id: Optional[int]
    created_at: str
    xp: int
    level: int
    banned: int

    def achievements_list(self) -> list[str]:
        return [a.strip() for a in (self.achievements or "").split(",") if a.strip()]


@dataclass(slots=True)
class RouletteBet:
    """Одна ставка в сессии рулетки (ЧАСТЬ 8)."""
    user_id: int
    bet_type: str              # color | parity | range | number
    value: Any                 # 'red'|'black' | 'even'|'odd' | (lo,hi) | int
    amount: int
    raw: str = ""


# =============================================================================
#  БЫСТРЫЕ САНИТАЙЗЕРЫ ВВОДА
# =============================================================================

def sanitize_callback_data(data: str, limit: int = 64) -> str:
    """
    Telegram ограничивает callback_data 64 байтами.
    Обрезаем и убираем непечатаемое, чтобы не ловить TelegramBadRequest.
    """
    s = "".join(ch for ch in str(data) if ch.isprintable())
    encoded = s.encode("utf-8")
    if len(encoded) <= limit:
        return s
    return encoded[:limit].decode("utf-8", errors="ignore")


def split_command_args(text: str) -> list[str]:
    """Разбивает текст на аргументы, схлопывая пробелы."""
    return [a for a in re.split(r"\s+", text.strip()) if a]


def is_group_chat(chat: Optional[TgChat]) -> bool:
    """True для групп и супергрупп."""
    return bool(chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP))


def is_private_chat(chat: Optional[TgChat]) -> bool:
    return bool(chat and chat.type == ChatType.PRIVATE)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 1
# =============================================================================
# Проверяем, что базовые каталоги существуют (страховка для Render).
def _ensure_dirs() -> None:
    for p in (IMAGES_DIR, DB_DIR, LOG_DIR):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log_exception(f"_ensure_dirs({p})", exc)


_ensure_dirs()

log.info(
    "=== %s v%s: конфигурация загружена (admin=%s, port=%s, debug=%s) ===",
    BOT_NAME, BOT_VERSION, ENV.admin_id, ENV.port, ENV.is_debug,
)
log.info("БД будет создана по пути: %s", DB_PATH)
log.info("Каталог изображений: %s", IMAGES_DIR)

# =============================================================================
#  ЧАСТЬ 2 / 10: ФУНКЦИИ БД (часть 1)
#    - Пул соединений (одно долгоживущее соединение + lock)
#    - create_tables()  — вся схема (см. ТЗ)
#    - get_user / ensure_user
#    - add_balance (атомарно)
#    - try_withdraw (атомарно, возвращает bool — защита от double-spend)
#    - log_game, log_roulette (базовая запись)
#    - хелперы: execute / fetchone / fetchall с логированием
# =============================================================================
# ВАЖНО: используем ОДНО соединение aiosqlite + asyncio.Lock на запись.
# Для SQLite это оптимально и защищает от "database is locked" на Render.
# Все SELECT-ы проходят через тот же lock (дешёвая сериализация) — это
# гарантирует консистентность при параллельных играх.
# =============================================================================

from contextlib import asynccontextmanager

# Глобальное соединение и мьютекс. Инициализируются в init_db().
_DB: Optional[aiosqlite.Connection] = None
_DB_LOCK: asyncio.Lock = asyncio.Lock()
_DB_READY: bool = False


# =============================================================================
#  НИЗКОУРОВНЕВЫЕ ОБЁРТКИ
# =============================================================================

async def init_db() -> None:
    """
    Открывает соединение, включает WAL и foreign_keys, создаёт схему.
    Вызывается один раз из main() (ЧАСТЬ 10) ДО старта поллинга.
    """
    global _DB, _DB_READY, _DB_LOCK
    if _DB_READY:
        log.info("init_db: БД уже инициализирована, пропуск")
        return

    # Lock создаётся заново — на случай, если модуль перезагрузили.
    _DB_LOCK = asyncio.Lock()

    try:
        _DB = await aiosqlite.connect(DB_PATH, timeout=30.0)
        _DB.row_factory = aiosqlite.Row

        # WAL — параллельные чтения не блокируют запись. Критично для Render.
        await _DB.execute("PRAGMA journal_mode=WAL;")
        await _DB.execute("PRAGMA synchronous=NORMAL;")
        await _DB.execute("PRAGMA foreign_keys=ON;")
        await _DB.execute("PRAGMA busy_timeout=30000;")
        await _DB.commit()

        # ВАЖНО: ставим флаг ДО вызова create_tables(), 
        # иначе _get_db() выдаст ошибку инициализации
        _DB_READY = True
        
        try:
            await create_tables()
        except Exception as e:
            _DB_READY = False
            raise e


async def close_db() -> None:
    """Закрывает соединение при выключении бота."""
    global _DB, _DB_READY
    if _DB is not None:
        try:
            await _DB.close()
            log.info("close_db: соединение закрыто")
        except Exception as exc:
            log_exception("close_db", exc)
    _DB = None
    _DB_READY = False


def _get_db() -> aiosqlite.Connection:
    """Возвращает соединение или бросает понятную ошибку."""
    if _DB is None or not _DB_READY:
        raise RuntimeError("БД не инициализирована. Вызовите init_db() при старте.")
    return _DB


async def execute(sql: str, params: Sequence[Any] = ()) -> Optional[int]:
    """
    INSERT/UPDATE/DELETE с коммитом. Возвращает lastrowid (или rowcount).
    ВСЕГДА под lock — сериализуем запись.
    """
    db = _get_db()
    async with _DB_LOCK:
        try:
            cur = await db.execute(sql, tuple(params))
            await db.commit()
            return cur.lastrowid
        except Exception as exc:
            await db.rollback()
            log_exception(f"execute({sql[:80]!r})", exc)
            raise
        finally:
            try:
                await cur.close()  # type: ignore[name-defined]
            except Exception:
                pass


async def executemany(sql: str, seq_params: Iterable[Sequence[Any]]) -> None:
    """Массовая вставка/обновление одним коммитом."""
    db = _get_db()
    async with _DB_LOCK:
        try:
            await db.executemany(sql, [tuple(p) for p in seq_params])
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log_exception(f"executemany({sql[:80]!r})", exc)
            raise


async def fetchone(sql: str, params: Sequence[Any] = ()) -> Optional[aiosqlite.Row]:
    """Один SELECT. Возвращает Row или None."""
    db = _get_db()
    async with _DB_LOCK:
        try:
            cur = await db.execute(sql, tuple(params))
            return await cur.fetchone()
        except Exception as exc:
            log_exception(f"fetchone({sql[:80]!r})", exc)
            return None
        finally:
            try:
                await cur.close()  # type: ignore[name-defined]
            except Exception:
                pass


async def fetchall(sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
    """SELECT многих строк."""
    db = _get_db()
    async with _DB_LOCK:
        try:
            cur = await db.execute(sql, tuple(params))
            return list(await cur.fetchall())
        except Exception as exc:
            log_exception(f"fetchall({sql[:80]!r})", exc)
            return []
        finally:
            try:
                await cur.close()  # type: ignore[name-defined]
            except Exception:
                pass


async def fetchval(sql: str, params: Sequence[Any] = (), default: Any = 0) -> Any:
    """SELECT одного скалярного значения."""
    row = await fetchone(sql, params)
    if row is None:
        return default
    try:
        return row[0]
    except Exception:
        return default


# =============================================================================
#  СХЕМА БД
# =============================================================================
# Все CREATE TABLE — IF NOT EXISTS. Никаких "drop", "DELETE FROM users" и т.п.
# Внешние ключи для games_log/roulette_logs не ставим жёстко: юзер мог
# прийти из другого чата, и FK усложнили бы миграции. Логика целостности —
# на стороне Python (ensure_user перед любой записью).
# =============================================================================

CREATE_TABLES_SQL: tuple[str, ...] = (
    # ---- users ----
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id      INTEGER PRIMARY KEY,
        username     TEXT,
        balance      INTEGER NOT NULL DEFAULT 0,
        vip          INTEGER NOT NULL DEFAULT 0,          -- unix-ts окончания VIP (0 = нет)
        games        INTEGER NOT NULL DEFAULT 0,
        wins         INTEGER NOT NULL DEFAULT 0,
        achievements TEXT NOT NULL DEFAULT '',            -- csv
        referrer_id  INTEGER,
        created_at   TEXT NOT NULL,
        xp           INTEGER NOT NULL DEFAULT 0,
        level        INTEGER NOT NULL DEFAULT 1,
        banned       INTEGER NOT NULL DEFAULT 0,
        last_game_at INTEGER NOT NULL DEFAULT 0          -- антиспам играми (unix-ts)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance)",
    "CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_wins ON users(wins)",

    # ---- chat_settings ----
    """
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id       INTEGER PRIMARY KEY,
        games_enabled INTEGER NOT NULL DEFAULT 1,
        created_at    TEXT NOT NULL
    )
    """,

    # ---- event_chats ----
    """
    CREATE TABLE IF NOT EXISTS event_chats (
        chat_id  INTEGER PRIMARY KEY,
        title    TEXT,
        added_at TEXT NOT NULL
    )
    """,

    # ---- roulette_logs ----
    """
    CREATE TABLE IF NOT EXISTS roulette_logs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id    INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        bet        INTEGER NOT NULL,
        win        INTEGER NOT NULL DEFAULT 0,
        numbers    TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_roulette_user ON roulette_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_roulette_chat ON roulette_logs(chat_id)",

    # ---- games_log ----
    """
    CREATE TABLE IF NOT EXISTS games_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        game       TEXT NOT NULL,
        bet        INTEGER NOT NULL,
        win        INTEGER NOT NULL DEFAULT 0,
        result     TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_games_user ON games_log(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_games_game ON games_log(game)",

    # ---- bonus_items ----
    """
    CREATE TABLE IF NOT EXISTS bonus_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id    INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        claimed_by INTEGER,
        created_at TEXT NOT NULL,
        UNIQUE(chat_id, message_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bonus_claimed ON bonus_items(claimed_by)",

    # ---- daily_bonus ----
    """
    CREATE TABLE IF NOT EXISTS daily_bonus (
        user_id     INTEGER PRIMARY KEY,
        last_claim  INTEGER NOT NULL
    )
    """,

    # ---- promo_codes ----
    """
    CREATE TABLE IF NOT EXISTS promo_codes (
        code       TEXT PRIMARY KEY,
        amount     INTEGER NOT NULL,
        max_uses   INTEGER NOT NULL DEFAULT 1,
        used_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,

    # ---- promo_used ----
    """
    CREATE TABLE IF NOT EXISTS promo_used (
        user_id   INTEGER NOT NULL,
        code      TEXT NOT NULL,
        used_at   TEXT NOT NULL,
        PRIMARY KEY (user_id, code)
    )
    """,

    # ---- admin_logs ----
    """
    CREATE TABLE IF NOT EXISTS admin_logs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id   INTEGER NOT NULL,
        action     TEXT NOT NULL,
        details    TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_admin_action ON admin_logs(action)",

    # ---- referral_paid (вспомогательная, чтобы не выдать реф-бонус дважды) ----
    """
    CREATE TABLE IF NOT EXISTS referral_paid (
        referred_id INTEGER PRIMARY KEY,
        paid_at     TEXT NOT NULL
    )
    """,
)


async def create_tables() -> None:
    """Прогоняет все CREATE ... IF NOT EXISTS и индексы."""
    db = _get_db()
    try:
        for stmt in CREATE_TABLES_SQL:
            await db.execute(stmt)
        await db.commit()
        log.info("create_tables: схема применена (%d стейтментов)", len(CREATE_TABLES_SQL))
    except Exception as exc:
        log_exception("create_tables", exc)
        await db.rollback()
        raise


# =============================================================================
#  USERS: ЧТЕНИЕ / СОЗДАНИЕ
# =============================================================================

_ROW_TO_USER_FIELDS = (
    "user_id", "username", "balance", "vip", "games", "wins",
    "achievements", "referrer_id", "created_at", "xp", "level", "banned",
)


def _row_to_user(row: Optional[aiosqlite.Row]) -> Optional[UserRow]:
    """Преобразует Row -> UserRow. None-safe."""
    if row is None:
        return None
    try:
        return UserRow(
            user_id=int(row["user_id"]),
            username=row["username"],
            balance=int(row["balance"]),
            vip=int(row["vip"]),
            games=int(row["games"]),
            wins=int(row["wins"]),
            achievements=row["achievements"] or "",
            referrer_id=row["referrer_id"],
            created_at=row["created_at"],
            xp=int(row["xp"]),
            level=int(row["level"]),
            banned=int(row["banned"]),
        )
    except Exception as exc:
        log_exception("_row_to_user", exc)
        return None


async def get_user(user_id: int) -> Optional[UserRow]:
    """Возвращает пользователя или None, если его нет в БД."""
    row = await fetchone(
        "SELECT user_id, username, balance, vip, games, wins, achievements, "
        "referrer_id, created_at, xp, level, banned "
        "FROM users WHERE user_id = ?",
        (int(user_id),),
    )
    return _row_to_user(row)


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    referrer_id: Optional[int] = None,
    start_balance: int = START_BALANCE,
) -> UserRow:
    """
    Гарантирует, что пользователь есть в БД. Если нет — создаёт с балансом.
    Если есть — обновляет username (мог смениться) и возвращает запись.
    Реферальный бонус НЕ начисляется здесь — только сохранение referrer_id.
    Реф-награда выдаётся отдельно после первой игры (ЧАСТЬ 5).
    """
    uid = int(user_id)
    existing = await get_user(uid)
    uname = (username or None)
    if uname:
        uname = safe_str(uname.lstrip("@"), 64)

    if existing is None:
        created = utcnow_iso()
        # Если referrer_id указан — не даём "самореферал" и не перезаписываем.
        ref = int(referrer_id) if referrer_id and int(referrer_id) != uid else None
        await execute(
            "INSERT INTO users "
            "(user_id, username, balance, vip, games, wins, achievements, "
            " referrer_id, created_at, xp, level, banned, last_game_at) "
            "VALUES (?, ?, ?, 0, 0, 0, '', ?, ?, 0, 1, 0, 0)",
            (uid, uname, int(start_balance), ref, created),
        )
        log.info("ensure_user: создан новый игрок id=%s ref=%s balance=%s",
                 uid, ref, start_balance)
        # Возвращаем "свежую" запись
        fresh = await get_user(uid)
        if fresh is None:
            # Экстремальный случай: БД легла между INSERT и SELECT.
            # Возвращаем in-memory "заглушку", чтобы хендлер не упал 500.
            return UserRow(
                user_id=uid, username=uname, balance=int(start_balance), vip=0,
                games=0, wins=0, achievements="", referrer_id=ref,
                created_at=created, xp=0, level=1, banned=0,
            )
        return fresh

    # Обновляем username, если сменился (или появился).
    if uname and uname != (existing.username or ""):
        await execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (uname, uid),
        )
        existing.username = uname
    return existing


async def set_username(user_id: int, username: Optional[str]) -> None:
    """Явное обновление username (например, при /start)."""
    uname = safe_str((username or "").lstrip("@"), 64) if username else None
    await execute(
        "UPDATE users SET username = ? WHERE user_id = ?",
        (uname, int(user_id)),
    )


async def is_banned(user_id: int) -> bool:
    """Быстрая проверка бана (без загрузки всей строки)."""
    val = await fetchval("SELECT banned FROM users WHERE user_id = ?", (int(user_id),), 0)
    try:
        return int(val) == 1
    except Exception:
        return False


async def set_ban(user_id: int, banned: bool) -> bool:
    """Ставит/снимает бан. Возвращает True, если запись существует."""
    row = await fetchone("SELECT user_id FROM users WHERE user_id = ?", (int(user_id),))
    if row is None:
        return False
    await execute(
        "UPDATE users SET banned = ? WHERE user_id = ?",
        (1 if banned else 0, int(user_id)),
    )
    return True


# =============================================================================
#  БАЛАНС: АТОМАРНЫЕ ОПЕРАЦИИ
# =============================================================================
# Ключевой принцип: изменяем баланс ОДНИМ UPDATE с проверкой условия.
# SQLite выполняет UPDATE атомарно в рамках соединения. Плюс наш _DB_LOCK
# сериализует все операции — двойного списания не будет даже при гонке
# двух хендлеров одного юзера.
# =============================================================================

async def add_balance(
    user_id: int,
    amount: int,
    *,
    ensure: bool = True,
    username: Optional[str] = None,
) -> int:
    """
    Прибавляет (или отнимает, если amount<0) баланс.
    Возвращает НОВЫЙ баланс.
    - amount >= 0: атомарный инкремент.
    - amount < 0: безопасное списание через try_withdraw-подобную логику
      (не уходим в минус; если недостаточно — возвращаем текущий баланс).
    ВНИМАНИЕ: для игровых ставок используйте try_withdraw(), чтобы явно
    обработать отказ.
    """
    uid = int(user_id)
    if ensure:
        await ensure_user(uid, username=username)

    if amount == 0:
        return int(await fetchval("SELECT balance FROM users WHERE user_id = ?", (uid,), 0))

    if amount > 0:
        await execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (int(amount), uid),
        )
        return int(await fetchval("SELECT balance FROM users WHERE user_id = ?", (uid,), 0))

    # Отрицательная сумма — списываем безопасно, без ухода в минус.
    debit = -int(amount)
    await execute(
        "UPDATE users SET balance = balance - ? "
        "WHERE user_id = ? AND balance >= ?",
        (debit, uid, debit),
    )
    return int(await fetchval("SELECT balance FROM users WHERE user_id = ?", (uid,), 0))


async def try_withdraw(
    user_id: int,
    amount: int,
    *,
    allow_god_mode: bool = True,
    username: Optional[str] = None,
) -> bool:
    """
    Атомарная попытка списать amount.
    Возвращает True при успехе, False при нехватке средств.
    При allow_god_mode и наличии user_id в GOD_MODE_USERS — списывает 0
    (режим бога для админа), возвращая True.

    КЛЮЧЕВОЕ: единственный UPDATE с условием balance >= amount.
    rowcount == 1 => успех. Это исключает double-spend на уровне СУБД.
    """
    uid = int(user_id)
    amt = int(amount)
    if amt <= 0:
        return False

    # Режим бога: админ не тратит баланс, но и не уходит в минус.
    if allow_god_mode and uid in GOD_MODE_USERS:
        await ensure_user(uid, username=username)
        return True

    await ensure_user(uid, username=username)

    db = _get_db()
    async with _DB_LOCK:
        try:
            cur = await db.execute(
                "UPDATE users SET balance = balance - ? "
                "WHERE user_id = ? AND balance >= ?",
                (amt, uid, amt),
            )
            await db.commit()
            ok = (cur.rowcount or 0) == 1
            await cur.close()
            return ok
        except Exception as exc:
            await db.rollback()
            log_exception("try_withdraw", exc)
            return False


async def get_balance(user_id: int) -> int:
    """Быстрый доступ к балансу."""
    return int(await fetchval("SELECT balance FROM users WHERE user_id = ?", (int(user_id),), 0))


async def transfer_balance(
    from_id: int,
    to_id: int,
    amount: int,
    *,
    commission: float = 0.0,
) -> tuple[bool, str]:
    """
    Атомарный перевод между игроками.
    Возвращает (ok, reason). reason — человекочитаемая причина отказа.
    Комиссия удерживается с получателя (по ТЗ — только для дуэлей;
    для обычных переводов commission=0).
    """
    f_id, t_id, amt = int(from_id), int(to_id), int(amount)
    if f_id == t_id:
        return False, "Нельзя переводить самому себе."
    if amt <= 0:
        return False, "Сумма должна быть положительной."

    await ensure_user(f_id)
    await ensure_user(t_id)

    # Списываем у отправителя атомарно.
    if f_id not in GOD_MODE_USERS:
        ok = await try_withdraw(f_id, amt)
        if not ok:
            return False, "Недостаточно TOKENS."

    credited = int(amt * (1.0 - max(0.0, min(1.0, commission))))
    await add_balance(t_id, credited, ensure=False)
    return True, "ok"


# =============================================================================
#  ЛОГИ ИГР
# =============================================================================

async def log_game(
    user_id: int,
    game: str,
    bet: int,
    win: int,
    result: Optional[str] = None,
) -> None:
    """
    Пишет запись в games_log и обновляет счётчики игр/побед/XP.
    XP += bet // 100 (мягко). Уровень пересчитывается.
    """
    uid = int(user_id)
    g = safe_str(game, 32)
    b = max(0, int(bet))
    w = max(0, int(win))
    res = safe_str(result or "", 128) or None
    created = utcnow_iso()

    await ensure_user(uid)
    await execute(
        "INSERT INTO games_log (user_id, game, bet, win, result, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, g, b, w, res, created),
    )

    won_flag = 1 if w > b else 0
    xp_gain = b // LEVEL_XP_STEP

    # Сначала инкрементальные счётчики.
    await execute(
        "UPDATE users SET games = games + 1, wins = wins + ?, xp = xp + ? "
        "WHERE user_id = ?",
        (won_flag, xp_gain, uid),
    )

    # Пересчёт уровня на основе нового XP — отдельным запросом.
    row = await fetchone("SELECT xp FROM users WHERE user_id = ?", (uid,))
    if row is not None:
        try:
            new_xp = int(row["xp"])
            new_lvl = calc_level(new_xp)
            await execute(
                "UPDATE users SET level = ? WHERE user_id = ? AND level <> ?",
                (new_lvl, uid, new_lvl),
            )
        except Exception as exc:
            log_exception("log_game:recalc_level", exc)


async def log_roulette(
    chat_id: int,
    user_id: int,
    bet: int,
    win: int,
    numbers: str = "",
) -> None:
    """Пишет запись в roulette_logs. Вызывается из ЧАСТИ 8."""
    await execute(
        "INSERT INTO roulette_logs (chat_id, user_id, bet, win, numbers, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(chat_id), int(user_id), int(bet), int(win), safe_str(numbers, 64), utcnow_iso()),
    )


async def get_game_history(user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    """История последних игр (для кнопки «История» в профиле)."""
    lim = clamp(int(limit), 1, 50)
    return await fetchall(
        "SELECT game, bet, win, result, created_at FROM games_log "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (int(user_id), lim),
    )


async def get_user_stats(user_id: int) -> dict[str, int]:
    """Агрегированная статистика по игроку (для профиля/админки)."""
    total_bet = int(await fetchval(
        "SELECT COALESCE(SUM(bet),0) FROM games_log WHERE user_id = ?",
        (int(user_id),), 0,
    ))
    total_win = int(await fetchval(
        "SELECT COALESCE(SUM(win),0) FROM games_log WHERE user_id = ?",
        (int(user_id),), 0,
    ))
    games_cnt = int(await fetchval(
        "SELECT COUNT(*) FROM games_log WHERE user_id = ?",
        (int(user_id),), 0,
    ))
    return {"total_bet": total_bet, "total_win": total_win, "games": games_cnt}


# =============================================================================
#  АНТИСПАМ ИГРАМИ (минимальный интервал 3 сек)
# =============================================================================

async def check_game_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Возвращает (можно_играть, сколько_сек_осталось).
    Обновляет last_game_at при успехе.
    Работает на уровне БД — сохраняется между рестартами процесса.
    """
    uid = int(user_id)
    await ensure_user(uid)
    row = await fetchone("SELECT last_game_at FROM users WHERE user_id = ?", (uid,))
    now = utcnow_ts()
    if row is None:
        await execute("UPDATE users SET last_game_at = ? WHERE user_id = ?", (now, uid))
        return True, 0
    try:
        last = int(row["last_game_at"])
    except Exception:
        last = 0
    elapsed = now - last
    if elapsed < GAME_COOLDOWN_SEC:
        remain = int(GAME_COOLDOWN_SEC - elapsed) + 1
        return False, remain
    await execute("UPDATE users SET last_game_at = ? WHERE user_id = ?", (now, uid))
    return True, 0


# =============================================================================
#  VIP
# =============================================================================

async def is_vip(user_id: int) -> bool:
    """True, если VIP ещё активен (unix-ts окончания > сейчас)."""
    v = int(await fetchval("SELECT vip FROM users WHERE user_id = ?", (int(user_id),), 0))
    return v > utcnow_ts()


async def activate_vip(user_id: int, days: int = VIP_DURATION_DAYS) -> int:
    """Продлевает VIP на days дней. Возвращает новый unix-ts окончания."""
    uid = int(user_id)
    await ensure_user(uid)
    now = utcnow_ts()
    cur = int(await fetchval("SELECT vip FROM users WHERE user_id = ?", (uid,), 0))
    base = cur if cur > now else now
    new_ts = base + days * 86400
    await execute("UPDATE users SET vip = ? WHERE user_id = ?", (new_ts, uid))
    return new_ts


# =============================================================================
#  ДОСТИЖЕНИЯ
# =============================================================================

async def grant_achievement(user_id: int, code: str) -> bool:
    """
    Выдаёт достижение, если его ещё нет. Возвращает True, если новое.
    Хранится CSV-строкой в users.achievements.
    """
    if code not in ACHIEVEMENTS:
        return False
    uid = int(user_id)
    await ensure_user(uid)
    row = await fetchone("SELECT achievements FROM users WHERE user_id = ?", (uid,))
    if row is None:
        return False
    cur = (row["achievements"] or "").strip()
    items = [a for a in cur.split(",") if a]
    if code in items:
        return False
    items.append(code)
    new_csv = ",".join(items)
    await execute("UPDATE users SET achievements = ? WHERE user_id = ?", (new_csv, uid))
    return True


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 2
# =============================================================================
# Никаких "drop"/"DELETE FROM users" — только IF NOT EXISTS и UPDATE.
# Все операции записи — под _DB_LOCK и в try/except с rollback.
# =============================================================================

log.info("ЧАСТЬ 2: модуль БД (users/balance/log) инициализирован (ленивое соединение)")

# =============================================================================
#  ЧАСТЬ 3 / 10: ФУНКЦИИ БД (часть 2)
#    - История (профиль, топ, рейтинги)
#    - Настройки чатов (games_enabled)
#    - Ивент-чаты (для автодропов)
#    - Промокоды (создание/активация/список)
#    - Ежедневный бонус
#    - Реферальная система (первая игра -> бонус)
#    - Бонус-итемы (дропы в чатах)
#    - Джекпот
#    - Рейтинг/топ
#    - Админ-логи
#    - Технические хелперы (статистика, очистка старых записей)
# =============================================================================
# Все запросы параметризованные, без "drop". Все записи — под _DB_LOCK
# через execute/executemany из ЧАСТИ 2.
# =============================================================================


# =============================================================================
#  ИСТОРИЯ (игры, рулетка, транзакции)
# =============================================================================

async def get_roulette_history(user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    """Последние N ставок в рулетке для кнопки «История»."""
    lim = clamp(int(limit), 1, 50)
    return await fetchall(
        "SELECT bet, win, numbers, created_at FROM roulette_logs "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (int(user_id), lim),
    )


async def get_last_game_time(user_id: int) -> int:
    """
    Unix-ts последней игры пользователя (по games_log).
    0, если игр не было. Нужен для проверки условий реф-бонуса
    и «неактивности».
    """
    val = await fetchval(
        "SELECT MAX(created_at) FROM games_log WHERE user_id = ?",
        (int(user_id),), None,
    )
    if not val:
        return 0
    try:
        # created_at — ISO8601 UTC. Парсим безопасно.
        dt = datetime.fromisoformat(str(val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


async def has_played_any_game(user_id: int) -> bool:
    """True, если у юзера есть хотя бы одна запись в games_log."""
    cnt = int(await fetchval(
        "SELECT COUNT(*) FROM games_log WHERE user_id = ? LIMIT 1",
        (int(user_id),), 0,
    ))
    return cnt > 0


# =============================================================================
#  НАСТРОЙКИ ЧАТОВ
# =============================================================================

async def chat_games_enabled(chat_id: int) -> bool:
    """
    True, если игры разрешены в чате.
    По умолчанию (нет записи) — True. Явное отключение — 0.
    """
    val = await fetchval(
        "SELECT games_enabled FROM chat_settings WHERE chat_id = ?",
        (int(chat_id),), None,
    )
    if val is None:
        return True
    try:
        return int(val) == 1
    except Exception:
        return True


async def set_chat_games(chat_id: int, enabled: bool, title: Optional[str] = None) -> None:
    """Включает/выключает игры в чате. Создаёт запись при необходимости."""
    cid = int(chat_id)
    flag = 1 if enabled else 0
    exists = await fetchone(
        "SELECT chat_id FROM chat_settings WHERE chat_id = ?", (cid,),
    )
    if exists is None:
        await execute(
            "INSERT INTO chat_settings (chat_id, games_enabled, created_at) "
            "VALUES (?, ?, ?)",
            (cid, flag, utcnow_iso()),
        )
    else:
        await execute(
            "UPDATE chat_settings SET games_enabled = ? WHERE chat_id = ?",
            (flag, cid),
        )


async def list_disabled_chats() -> list[aiosqlite.Row]:
    """Чаты, где игры выключены (для админ-статистики)."""
    return await fetchall(
        "SELECT chat_id FROM chat_settings WHERE games_enabled = 0"
    )


# =============================================================================
#  ИВЕНТ-ЧАТЫ (автодропы)
# =============================================================================

async def add_event_chat(chat_id: int, title: Optional[str] = None) -> bool:
    """
    Добавляет чат в список ивент-чатов (куда падают автодропы).
    Возвращает True, если добавлен; False, если уже был.
    """
    cid = int(chat_id)
    t = safe_str(title, 128) if title else None
    exists = await fetchone("SELECT chat_id FROM event_chats WHERE chat_id = ?", (cid,))
    if exists is not None:
        if t:
            await execute("UPDATE event_chats SET title = ? WHERE chat_id = ?", (t, cid))
        return False
    await execute(
        "INSERT INTO event_chats (chat_id, title, added_at) VALUES (?, ?, ?)",
        (cid, t, utcnow_iso()),
    )
    return True


async def remove_event_chat(chat_id: int) -> bool:
    """Удаляет чат из ивент-списка. Возвращает True при успехе."""
    cid = int(chat_id)
    exists = await fetchone("SELECT chat_id FROM event_chats WHERE chat_id = ?", (cid,))
    if exists is None:
        return False
    await execute("DELETE FROM event_chats WHERE chat_id = ?", (cid,))
    return True


async def get_event_chats() -> list[int]:
    """Список chat_id всех ивент-чатов."""
    rows = await fetchall("SELECT chat_id FROM event_chats ORDER BY added_at ASC")
    return [int(r["chat_id"]) for r in rows]


# =============================================================================
#  ПРОМОКОДЫ
# =============================================================================

_PROMO_CODE_RE = re.compile(r"^[A-Z0-9_\-]{%d,%d}$" % (
    PROMO_CODE_MIN_LEN, PROMO_CODE_MAX_LEN
))


def normalize_promo_code(code: str) -> Optional[str]:
    """
    Приводит код к верхнему регистру и валидирует формат.
    None — если формат некорректен.
    """
    c = safe_str(code, PROMO_CODE_MAX_LEN).strip().upper()
    c = re.sub(r"\s+", "", c)
    if not _PROMO_CODE_RE.match(c):
        return None
    return c


async def create_promo(
    code: str,
    amount: int,
    max_uses: int = PROMO_MAX_USES_DEFAULT,
) -> tuple[bool, str]:
    """
    Создаёт промокод.
    Возвращает (ok, reason): reason == 'ok' | 'exists' | 'bad_code' | 'bad_amount'.
    """
    norm = normalize_promo_code(code)
    if norm is None:
        return False, "bad_code"
    amt = parse_positive_int(amount)
    if amt is None:
        return False, "bad_amount"
    uses = parse_positive_int(max_uses) or PROMO_MAX_USES_DEFAULT

    exists = await fetchone("SELECT code FROM promo_codes WHERE code = ?", (norm,))
    if exists is not None:
        return False, "exists"

    await execute(
        "INSERT INTO promo_codes (code, amount, max_uses, used_count, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (norm, amt, uses, utcnow_iso()),
    )
    return True, "ok"


async def activate_promo(user_id: int, code: str) -> tuple[bool, str, int]:
    """
    Активирует промокод для пользователя.
    Возвращает (ok, reason, amount).
    reason: 'ok' | 'bad_code' | 'not_found' | 'exhausted' | 'already_used'.
    """
    norm = normalize_promo_code(code)
    if norm is None:
        return False, "bad_code", 0
    uid = int(user_id)
    await ensure_user(uid)

    row = await fetchone(
        "SELECT amount, max_uses, used_count FROM promo_codes WHERE code = ?",
        (norm,),
    )
    if row is None:
        return False, "not_found", 0
    if int(row["used_count"]) >= int(row["max_uses"]):
        return False, "exhausted", 0

    used = await fetchone(
        "SELECT 1 FROM promo_used WHERE user_id = ? AND code = ?", (uid, norm),
    )
    if used is not None:
        return False, "already_used", 0

    amt = int(row["amount"])

    # Атомарный инкремент used_count с проверкой лимита.
    db = _get_db()
    async with _DB_LOCK:
        try:
            cur = await db.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 "
                "WHERE code = ? AND used_count < max_uses",
                (norm,),
            )
            if (cur.rowcount or 0) != 1:
                await cur.close()
                await db.rollback()
                return False, "exhausted", 0
            await db.execute(
                "INSERT INTO promo_used (user_id, code, used_at) VALUES (?, ?, ?)",
                (uid, norm, utcnow_iso()),
            )
            await db.commit()
            await cur.close()
        except Exception as exc:
            await db.rollback()
            log_exception("activate_promo", exc)
            return False, "not_found", 0

    await add_balance(uid, amt, ensure=False)
    return True, "ok", amt


async def list_promo_codes(limit: int = 20) -> list[aiosqlite.Row]:
    """Список активных промокодов (для админки)."""
    lim = clamp(int(limit), 1, 100)
    return await fetchall(
        "SELECT code, amount, max_uses, used_count, created_at FROM promo_codes "
        "ORDER BY created_at DESC LIMIT ?",
        (lim,),
    )


async def delete_promo(code: str) -> bool:
    """Удаляет промокод (только для админки @)."""
    norm = normalize_promo_code(code)
    if norm is None:
        return False
    exists = await fetchone("SELECT code FROM promo_codes WHERE code = ?", (norm,))
    if exists is None:
        return False
    await execute("DELETE FROM promo_codes WHERE code = ?", (norm,))
    return True


# =============================================================================
#  ЕЖЕДНЕВНЫЙ БОНУС
# =============================================================================

async def check_daily_bonus(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, доступен ли ежедневный бонус.
    Возвращает (доступен, сколько_сек_осталось).
    НЕ начисляет — только читает.
    """
    uid = int(user_id)
    await ensure_user(uid)
    row = await fetchone("SELECT last_claim FROM daily_bonus WHERE user_id = ?", (uid,))
    now = utcnow_ts()
    if row is None:
        return True, 0
    try:
        last = int(row["last_claim"])
    except Exception:
        last = 0
    elapsed = now - last
    if elapsed >= DAILY_BONUS_COOLDOWN:
        return True, 0
    return False, DAILY_BONUS_COOLDOWN - elapsed


async def claim_daily_bonus(user_id: int) -> tuple[bool, int, int]:
    """
    Пытается забрать ежедневный бонус.
    Возвращает (ok, amount, remain_sec).
    Атомарность: проверка+запись под одним lock — двойного начисления нет.
    """
    uid = int(user_id)
    await ensure_user(uid)
    now = utcnow_ts()

    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute(
                "SELECT last_claim FROM daily_bonus WHERE user_id = ?", (uid,),
            )
            row = await cur.fetchone()
            await cur.close()

            if row is not None:
                try:
                    last = int(row["last_claim"])
                except Exception:
                    last = 0
                if now - last < DAILY_BONUS_COOLDOWN:
                    remain = DAILY_BONUS_COOLDOWN - (now - last)
                    return False, 0, remain

            await db.execute(
                "INSERT INTO daily_bonus (user_id, last_claim) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_claim = excluded.last_claim",
                (uid, now),
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log_exception("claim_daily_bonus", exc)
            return False, 0, 0

    await add_balance(uid, DAILY_BONUS_AMOUNT, ensure=False)
    return True, DAILY_BONUS_AMOUNT, 0


# =============================================================================
#  РЕФЕРАЛЫ
# =============================================================================

async def set_referrer(user_id: int, referrer_id: int) -> bool:
    """
    Устанавливает реферера, если у юзера его ещё нет.
    Возвращает True, если установлен. Не даёт само-реферал и перезапись.
    """
    uid, rid = int(user_id), int(referrer_id)
    if uid == rid:
        return False
    await ensure_user(uid)
    await ensure_user(rid)
    row = await fetchone("SELECT referrer_id FROM users WHERE user_id = ?", (uid,))
    if row is None:
        return False
    if row["referrer_id"] is not None:
        return False
    await execute(
        "UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL",
        (rid, uid),
    )
    return True


async def try_pay_referral(referred_id: int) -> Optional[int]:
    """
    Пытается выплатить реф-бонус рефереру после ПЕРВОЙ игры приглашённого.
    Возвращает user_id реферера при выплате, иначе None.
    Защита от двойной выплаты — таблица referral_paid.
    """
    rid = int(referred_id)
    paid = await fetchone("SELECT referred_id FROM referral_paid WHERE referred_id = ?", (rid,))
    if paid is not None:
        return None

    row = await fetchone("SELECT referrer_id FROM users WHERE user_id = ?", (rid,))
    if row is None or row["referrer_id"] is None:
        return None
    referrer = int(row["referrer_id"])
    if referrer == rid:
        return None

    # Реферер должен существовать.
    ref_row = await fetchone("SELECT user_id FROM users WHERE user_id = ?", (referrer,))
    if ref_row is None:
        return None

    # Атомарно фиксируем выплату в referral_paid, чтобы два параллельных
    # хендлера не выдали бонус дважды.
    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute(
                "INSERT INTO referral_paid (referred_id, paid_at) VALUES (?, ?)",
                (rid, utcnow_iso()),
            )
            await db.commit()
            await cur.close()
        except Exception:
            # UNIQUE-конфликт => уже выплачено.
            await db.rollback()
            return None

    await add_balance(referrer, REFERRAL_REWARD, ensure=False)
    log.info("try_pay_referral: реферер %s получил %s за %s",
             referrer, REFERRAL_REWARD, rid)
    return referrer


async def get_referrals(user_id: int, limit: int = 20) -> list[aiosqlite.Row]:
    """Список приглашённых пользователей."""
    lim = clamp(int(limit), 1, 100)
    return await fetchall(
        "SELECT user_id, username, created_at FROM users "
        "WHERE referrer_id = ? ORDER BY created_at DESC LIMIT ?",
        (int(user_id), lim),
    )


async def count_referrals(user_id: int) -> int:
    return int(await fetchval(
        "SELECT COUNT(*) FROM users WHERE referrer_id = ?", (int(user_id),), 0,
    ))


async def count_paid_referrals(user_id: int) -> int:
    """Сколько из приглашённых уже сыграли (реферер получил бонус)."""
    return int(await fetchval(
        "SELECT COUNT(*) FROM users u "
        "JOIN referral_paid rp ON rp.referred_id = u.user_id "
        "WHERE u.referrer_id = ?",
        (int(user_id),), 0,
    ))


# =============================================================================
#  БОНУС-ИТЕМЫ (дропы в чатах)
# =============================================================================

async def create_bonus_item(chat_id: int, message_id: int, amount: int) -> bool:
    """Регистрирует дроп-сообщение в БД (для защиты от двойного клика)."""
    try:
        await execute(
            "INSERT INTO bonus_items (chat_id, message_id, amount, claimed_by, created_at) "
            "VALUES (?, ?, ?, NULL, ?)",
            (int(chat_id), int(message_id), int(amount), utcnow_iso()),
        )
        return True
    except Exception as exc:
        # UNIQUE(chat_id, message_id) — запись уже есть, это не ошибка.
        log_exception("create_bonus_item", exc)
        return False


async def claim_bonus_item(chat_id: int, message_id: int, user_id: int) -> tuple[bool, int]:
    """
    Пытается забрать дроп.
    Возвращает (ok, amount). ok=False, если уже забрали.
    Атомарно: UPDATE ... WHERE claimed_by IS NULL с проверкой rowcount.
    """
    cid, mid, uid = int(chat_id), int(message_id), int(user_id)
    await ensure_user(uid)

    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute(
                "UPDATE bonus_items SET claimed_by = ? "
                "WHERE chat_id = ? AND message_id = ? AND claimed_by IS NULL",
                (uid, cid, mid),
            )
            ok = (cur.rowcount or 0) == 1
            await cur.close()

            if not ok:
                await db.rollback()
                return False, 0

            amt_row = await db.execute(
                "SELECT amount FROM bonus_items WHERE chat_id = ? AND message_id = ?",
                (cid, mid),
            )
            arow = await amt_row.fetchone()
            await amt_row.close()
            amount = int(arow["amount"]) if arow else 0

            await db.commit()
        except Exception as exc:
            await db.rollback()
            log_exception("claim_bonus_item", exc)
            return False, 0

    if amount > 0:
        await add_balance(uid, amount, ensure=False)
    return True, amount


# =============================================================================
#  ДЖЕКПОТ
# =============================================================================

async def jackpot_add(amount: int) -> int:
    """
    Увеличивает пул джекпота в RUNTIME_FLAGS.
    (Источник правды — память процесса. Для Render с 1 инстансом — ок.)
    """
    add = max(0, int(amount))
    RUNTIME_FLAGS["jackpot_pool"] = int(RUNTIME_FLAGS.get("jackpot_pool", 0)) + add
    return int(RUNTIME_FLAGS["jackpot_pool"])


def jackpot_get() -> int:
    return int(RUNTIME_FLAGS.get("jackpot_pool", 0))


async def jackpot_reset() -> int:
    """Сбрасывает пул, возвращает предыдущее значение."""
    prev = int(RUNTIME_FLAGS.get("jackpot_pool", 0))
    RUNTIME_FLAGS["jackpot_pool"] = 0
    return prev


# =============================================================================
#  РЕЙТИНГ / ТОП
# =============================================================================

async def get_top_by_balance(limit: int = 10) -> list[aiosqlite.Row]:
    """Топ по балансу (только не забаненные)."""
    lim = clamp(int(limit), 1, 50)
    return await fetchall(
        "SELECT user_id, username, balance, level, vip FROM users "
        "WHERE banned = 0 ORDER BY balance DESC LIMIT ?",
        (lim,),
    )


async def get_top_by_wins(limit: int = 10) -> list[aiosqlite.Row]:
    """Топ по победам."""
    lim = clamp(int(limit), 1, 50)
    return await fetchall(
        "SELECT user_id, username, wins, games, level FROM users "
        "WHERE banned = 0 ORDER BY wins DESC, games ASC LIMIT ?",
        (lim,),
    )


async def get_top_by_level(limit: int = 10) -> list[aiosqlite.Row]:
    """Топ по уровню и XP."""
    lim = clamp(int(limit), 1, 50)
    return await fetchall(
        "SELECT user_id, username, level, xp FROM users "
        "WHERE banned = 0 ORDER BY level DESC, xp DESC LIMIT ?",
        (lim,),
    )


async def get_user_rank_balance(user_id: int) -> int:
    """Позиция юзера в топе по балансу (1-based). 0 — если нет в БД."""
    bal = await get_balance(int(user_id))
    if bal <= 0:
        # Позиция после всех, у кого баланс > 0 — либо 0, если игрок не в БД.
        exists = await fetchone("SELECT 1 FROM users WHERE user_id = ?", (int(user_id),))
        if exists is None:
            return 0
    cnt = int(await fetchval(
        "SELECT COUNT(*) FROM users WHERE banned = 0 AND balance > ?",
        (bal,), 0,
    ))
    return cnt + 1


# =============================================================================
#  АДМИН-ЛОГИ
# =============================================================================

async def log_admin_action(admin_id: int, action: str, details: Optional[str] = None) -> None:
    """Пишет действие админа в admin_logs."""
    try:
        await execute(
            "INSERT INTO admin_logs (admin_id, action, details, created_at) "
            "VALUES (?, ?, ?, ?)",
            (int(admin_id), safe_str(action, 64),
             safe_str(details or "", 512) or None, utcnow_iso()),
        )
    except Exception as exc:
        log_exception("log_admin_action", exc)


async def get_admin_logs(limit: int = ADMIN_LOG_LIMIT_DEFAULT) -> list[aiosqlite.Row]:
    lim = clamp(int(limit), 1, 200)
    return await fetchall(
        "SELECT id, admin_id, action, details, created_at FROM admin_logs "
        "ORDER BY id DESC LIMIT ?",
        (lim,),
    )


# =============================================================================
#  ГЛОБАЛЬНАЯ СТАТИСТИКА (для @стата)
# =============================================================================

async def get_global_stats() -> dict[str, Any]:
    """
    Агрегированная статистика бота для админки.
    Все SUM/COUNT — через COALESCE, чтобы не получить None.
    """
    users_total = int(await fetchval("SELECT COUNT(*) FROM users", (), 0))
    users_banned = int(await fetchval("SELECT COUNT(*) FROM users WHERE banned = 1", (), 0))
    total_balance = int(await fetchval(
        "SELECT COALESCE(SUM(balance),0) FROM users", (), 0))
    games_cnt = int(await fetchval("SELECT COUNT(*) FROM games_log", (), 0))
    roulette_cnt = int(await fetchval("SELECT COUNT(*) FROM roulette_logs", (), 0))
    today = now_day_key()
    games_today = int(await fetchval(
        "SELECT COUNT(*) FROM games_log WHERE substr(created_at,1,10) = ?",
        (today,), 0,
    ))
    roulette_today = int(await fetchval(
        "SELECT COUNT(*) FROM roulette_logs WHERE substr(created_at,1,10) = ?",
        (today,), 0,
    ))
    vip_active = int(await fetchval(
        "SELECT COUNT(*) FROM users WHERE vip > ?", (utcnow_ts(),), 0,
    ))
    chats_total = int(await fetchval("SELECT COUNT(*) FROM chat_settings", (), 0))
    chats_disabled = int(await fetchval(
        "SELECT COUNT(*) FROM chat_settings WHERE games_enabled = 0", (), 0,
    ))
    event_chats = int(await fetchval("SELECT COUNT(*) FROM event_chats", (), 0))

    return {
        "users_total": users_total,
        "users_banned": users_banned,
        "total_balance": total_balance,
        "games_cnt": games_cnt,
        "roulette_cnt": roulette_cnt,
        "games_today": games_today,
        "roulette_today": roulette_today,
        "vip_active": vip_active,
        "chats_total": chats_total,
        "chats_disabled": chats_disabled,
        "event_chats": event_chats,
        "jackpot_pool": jackpot_get(),
        "generated_at": utcnow_iso(),
    }


# =============================================================================
#  ОЧИСТКА (для APScheduler в ЧАСТИ 10)
# =============================================================================

async def cleanup_old_logs(days: int = 7) -> dict[str, int]:
    """
    Удаляет старые записи логов (games_log, roulette_logs, admin_logs).
    Возвращает счётчики удалённых записей.
    БЕЗОПАСНО: чистим только по дате, только логи (не users, не promos).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat(timespec="seconds")
    deleted = {"games": 0, "roulette": 0, "admin": 0}
    db = _get_db()

    async with _DB_LOCK:
        try:
            cur = await db.execute(
                "DELETE FROM games_log WHERE created_at < ?", (cutoff,)
            )
            deleted["games"] = cur.rowcount or 0
            await cur.close()

            cur = await db.execute(
                "DELETE FROM roulette_logs WHERE created_at < ?", (cutoff,)
            )
            deleted["roulette"] = cur.rowcount or 0
            await cur.close()

            cur = await db.execute(
                "DELETE FROM admin_logs WHERE created_at < ?", (cutoff,)
            )
            deleted["admin"] = cur.rowcount or 0
            await cur.close()

            await db.commit()
        except Exception as exc:
            await db.rollback()
            log_exception("cleanup_old_logs", exc)

    log.info("cleanup_old_logs: %s", deleted)
    return deleted


async def get_inactive_users(days: int = INACTIVE_REMIND_DAYS, limit: int = 200) -> list[int]:
    """
    Пользователи, у которых последняя игра была > days дней назад.
    Для напоминаний (ЧАСТЬ 10). Только не забаненные, с балансом > 0.
    """
    lim = clamp(int(limit), 1, 1000)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat(timespec="seconds")
    rows = await fetchall(
        "SELECT u.user_id FROM users u "
        "LEFT JOIN games_log g ON g.user_id = u.user_id "
        "WHERE u.banned = 0 AND u.balance > 0 "
        "GROUP BY u.user_id "
        "HAVING COALESCE(MAX(g.created_at), u.created_at) < ? "
        "LIMIT ?",
        (cutoff, lim),
    )
    return [int(r["user_id"]) for r in rows]


# =============================================================================
#  МАССОВЫЕ ОПЕРАЦИИ (для @дроп_всем, @забрать_всем)
# =============================================================================

async def bulk_add_balance(amount: int) -> int:
    """Прибавляет amount всем не забаненным пользователям. Возвращает кол-во."""
    amt = int(amount)
    if amt == 0:
        return 0
    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute(
                "UPDATE users SET balance = balance + ? WHERE banned = 0", (amt,),
            )
            n = cur.rowcount or 0
            await cur.close()
            await db.commit()
            return n
        except Exception as exc:
            await db.rollback()
            log_exception("bulk_add_balance", exc)
            return 0


async def bulk_try_withdraw(amount: int) -> int:
    """Списывает amount у всех, у кого хватает. Возвращает кол-во списаний."""
    amt = int(amount)
    if amt <= 0:
        return 0
    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute(
                "UPDATE users SET balance = balance - ? "
                "WHERE banned = 0 AND balance >= ?", (amt, amt),
            )
            n = cur.rowcount or 0
            await cur.close()
            await db.commit()
            return n
        except Exception as exc:
            await db.rollback()
            log_exception("bulk_try_withdraw", exc)
            return 0


async def bankrupt_user(user_id: int) -> int:
    """Обнуляет баланс пользователя. Возвращает предыдущий баланс."""
    uid = int(user_id)
    await ensure_user(uid)
    prev = await get_balance(uid)
    await execute("UPDATE users SET balance = 0 WHERE user_id = ?", (uid,))
    return prev


async def reset_all_balances() -> int:
    """Обнуляет баланс всем. Только для админа. Возвращает кол-во строк."""
    async with _DB_LOCK:
        db = _get_db()
        try:
            cur = await db.execute("UPDATE users SET balance = 0 WHERE balance <> 0")
            n = cur.rowcount or 0
            await cur.close()
            await db.commit()
            return n
        except Exception as exc:
            await db.rollback()
            log_exception("reset_all_balances", exc)
            return 0


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 3
# =============================================================================
log.info("ЧАСТЬ 3: модуль БД (история/чаты/промо/бонусы/топ/админ-логи) готов")

# =============================================================================
#  ЧАСТЬ 4 / 10: UI-ХЕЛПЕРЫ, FSM-СОСТОЯНИЯ, КЛАВИАТУРЫ
#    - Bot/Dispatcher будут созданы в ЧАСТИ 10, здесь — только хелперы
#    - safe_send / safe_edit / safe_delete / safe_answer — обёртки с try/except
#    - send_with_photo — проверка существования файла + fallback на текст
#    - FSM-состояния (BuyStars, CustomBet, AdminBroadcast, ...)
#    - Клавиатуры: main_reply_kb, back_inline_kb, profile_kb, donate_kb,
#      chats_kb, games_kb, top_kb, settings_kb, language_kb, mines_kb,
#      duel_kb, roulette_result_kb, admin_kb, bonus_kb
#    - Утилиты колбэков: cb_pack/cb_unpack (защита от 64-байт лимита)
# =============================================================================

# -----------------------------------------------------------------------------
#  ГЛОБАЛЬНАЯ ССЫЛКА НА BOT (устанавливается в ЧАСТИ 10 через set_bot())
# -----------------------------------------------------------------------------
# Хелперы должны работать даже если bot ещё не установлен — они вернут False.
_BOT_REF: Optional[Bot] = None


def set_bot(bot: Bot) -> None:
    """Регистрирует экземпляр Bot для хелперов (вызывается в main())."""
    global _BOT_REF
    _BOT_REF = bot


def get_bot() -> Optional[Bot]:
    return _BOT_REF


# =============================================================================
#  БЕЗОПАСНЫЕ ОБЁРТКИ TELEGRAM API
# =============================================================================
# Принцип: ни один хендлер не должен падать из-за Telegram-ошибок.
# Все обёртки возвращают Message/True/False и логируют.
# =============================================================================

async def safe_send(
    chat_id: int,
    text: str,
    markup: Optional[InlineKeyboardMarkup] = None,
    *,
    parse_mode: str = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    reply_to: Optional[int] = None,
    reply_markup_reply: Optional[ReplyKeyboardMarkup] = None,
    protect_content: bool = False,
) -> Optional[Message]:
    """
    Отправляет сообщение, разбивая текст > 4000 символов на части.
    Клавиатура прикрепляется ТОЛЬКО к последней части — иначе будет мусор.
    Все ошибки логируются, возвращает последнее Message (или None).
    """
    bot = get_bot()
    if bot is None:
        log.warning("safe_send: Bot не установлен")
        return None

    parts = chunk_text(text or "…", TG_SAFE_LIMIT)
    last_msg: Optional[Message] = None
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        kb = markup if is_last else None
        reply_markup = kb if kb is not None else (reply_markup_reply if is_last else None)
        try:
            last_msg = await bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to if i == 0 else None,
                protect_content=protect_content,
            )
        except TelegramRetryAfter as exc:
            log.warning("safe_send: flood control, retry after %ss", exc.retry_after)
            await asyncio.sleep(int(exc.retry_after) + 1)
            try:
                last_msg = await bot.send_message(
                    chat_id=chat_id, text=part, parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                    reply_markup=reply_markup,
                )
            except TelegramAPIError as exc2:
                log_exception("safe_send:retry", exc2)
                return last_msg
        except TelegramForbiddenError as exc:
            log.info("safe_send: бот заблокирован в чате %s: %s", chat_id, exc)
            return last_msg
        except TelegramBadRequest as exc:
            log.warning("safe_send: bad request (%s): %s", chat_id, exc)
            return last_msg
        except TelegramAPIError as exc:
            log_exception(f"safe_send({chat_id})", exc)
            return last_msg
        except Exception as exc:
            log_exception(f"safe_send({chat_id}):unexpected", exc)
            return last_msg

        # Микро-пауза между частями — не спамим Telegram.
        if not is_last:
            await asyncio.sleep(FLOOD_SLEEP)

    return last_msg


async def safe_edit(
    chat_id: int,
    message_id: int,
    text: str,
    markup: Optional[InlineKeyboardMarkup] = None,
    *,
    parse_mode: str = ParseMode.HTML,
    disable_web_page_preview: bool = True,
) -> bool:
    """
    Редактирует сообщение. Возвращает True при успехе.
    Если текст > 4000 — редактирует на первую часть, остальное — новым сообщением
    (редко нужно, но защищаемся от TelegramBadRequest).
    Если правки нет (текст не изменился) — Telegram вернёт BadRequest,
    это нормально, возвращаем False без падения.
    """
    bot = get_bot()
    if bot is None:
        return False

    parts = chunk_text(text or "…", TG_SAFE_LIMIT)
    first = parts[0]
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=first,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=markup,
        )
    except TelegramBadRequest as exc:
        # "message is not modified" — типичный случай, не логируем как ошибку.
        if "message is not modified" in str(exc).lower():
            return True
        # "message can't be edited" / "message to edit not found" — fallback.
        log.info("safe_edit fallback (%s): %s", message_id, exc)
        # Пробуем отправить новое сообщение и удалить старое.
        new_msg = await safe_send(chat_id, first, markup, parse_mode=parse_mode)
        if new_msg:
            await safe_delete(chat_id, message_id)
        return new_msg is not None
    except TelegramAPIError as exc:
        log_exception(f"safe_edit({chat_id},{message_id})", exc)
        return False
    except Exception as exc:
        log_exception(f"safe_edit({chat_id},{message_id}):unexpected", exc)
        return False

    # Остатки (если текст гигантский) — отдельными сообщениями.
    for i, part in enumerate(parts[1:], start=1):
        is_last = i == len(parts) - 1
        await safe_send(chat_id, part, markup if is_last else None, parse_mode=parse_mode)
        await asyncio.sleep(FLOOD_SLEEP)
    return True


async def safe_delete(chat_id: int, message_id: int, *, delay: float = 0.0) -> bool:
    """
    Удаляет сообщение. delay > 0 — отложенно (для автодаления результатов игр).
    Возвращает True при успехе.
    """
    bot = get_bot()
    if bot is None:
        return False
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramBadRequest as exc:
        # Сообщение уже удалено / слишком старое — не проблема.
        log.debug("safe_delete: %s", exc)
        return False
    except TelegramAPIError as exc:
        log_exception(f"safe_delete({chat_id},{message_id})", exc)
        return False


async def safe_answer(
    cb: CallbackQuery,
    text: Optional[str] = None,
    *,
    show_alert: bool = False,
    cache_time: int = 0,
) -> bool:
    """
    Отвечает на callback. ВСЕГДА в try/except.
    Возвращает False, если ответ уже был дан (просрочен) — это нормально.
    """
    try:
        await cb.answer(text=text, show_alert=show_alert, cache_time=cache_time)
        return True
    except TelegramBadRequest as exc:
        log.debug("safe_answer: %s", exc)
        return False
    except TelegramAPIError as exc:
        log_exception("safe_answer", exc)
        return False


async def safe_send_photo(
    chat_id: int,
    photo_path: Path | str,
    caption: str = "",
    markup: Optional[InlineKeyboardMarkup] = None,
    *,
    parse_mode: str = ParseMode.HTML,
) -> Optional[Message]:
    """
    Отправляет фото с подписью. Если файла нет — fallback на текст.
    Если подпись > 1024 — отправляет фото с обрезанной подписью и текст отдельно.
    """
    bot = get_bot()
    if bot is None:
        return None

    path = Path(photo_path)
    caption_clean = caption or ""
    if len(caption_clean) > TG_CAPTION_LIMIT:
        # Режем до безопасного лимита, остальное — отдельным сообщением.
        first_caption = caption_clean[: TG_CAPTION_LIMIT - 10].rstrip() + "…"
        tail = caption_clean[TG_CAPTION_LIMIT - 10:]
    else:
        first_caption = caption_clean
        tail = ""

    if path.exists() and path.is_file():
        try:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(str(path)),
                caption=first_caption or None,
                parse_mode=parse_mode,
                reply_markup=markup,
            )
        except TelegramRetryAfter as exc:
            await asyncio.sleep(int(exc.retry_after) + 1)
            try:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(str(path)),
                    caption=first_caption or None,
                    parse_mode=parse_mode,
                    reply_markup=markup,
                )
            except TelegramAPIError as exc2:
                log_exception("safe_send_photo:retry", exc2)
                return await safe_send(chat_id, caption_clean, markup, parse_mode=parse_mode)
        except TelegramBadRequest as exc:
            log.warning("safe_send_photo:bad request, fallback на текст: %s", exc)
            return await safe_send(chat_id, caption_clean, markup, parse_mode=parse_mode)
        except TelegramAPIError as exc:
            log_exception("safe_send_photo", exc)
            return await safe_send(chat_id, caption_clean, markup, parse_mode=parse_mode)
    else:
        # Файла нет — молча уходим в текст.
        log.debug("safe_send_photo: файл не найден %s, fallback", path)
        return await safe_send(chat_id, caption_clean, markup, parse_mode=parse_mode)

    if tail:
        await safe_send(chat_id, tail, None, parse_mode=parse_mode)
    return msg


async def send_with_photo(
    chat_id: int,
    image_name: str,
    caption: str,
    markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """
    Обёртка для удобства: путь images/<image_name>.
    Если файла нет — отправляет только текст (без исключения).
    """
    return await safe_send_photo(
        chat_id=chat_id,
        photo_path=IMAGES_DIR / image_name,
        caption=caption,
        markup=markup,
    )


async def send_animation(
    chat_id: int,
    animation_path: Path | str,
    caption: str = "",
    markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """
    Отправляет GIF/анимацию (например, рулетка). Fallback — текст.
    """
    bot = get_bot()
    if bot is None:
        return None
    path = Path(animation_path)
    if not path.exists() or not path.is_file():
        return await safe_send(chat_id, caption, markup)
    try:
        return await bot.send_animation(
            chat_id=chat_id,
            animation=FSInputFile(str(path)),
            caption=caption[:TG_CAPTION_LIMIT] if caption else None,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except TelegramAPIError as exc:
        log_exception("send_animation", exc)
        return await safe_send(chat_id, caption, markup)


# =============================================================================
#  УТИЛИТЫ КОЛБЭКОВ
# =============================================================================
# Telegram ограничивает callback_data 64 байтами. Для составных данных
# используем компактный формат: "prefix:arg1:arg2".
# Данные проверяем и обрезаем через sanitize_callback_data() из ЧАСТИ 1.
# =============================================================================

_CB_SEP = ":"


def cb_pack(prefix: str, *args: Any) -> str:
    """
    Собирает callback_data. Все аргументы приводятся к str и чистятся.
    Гарантирует <= 64 байта.
    """
    parts = [str(prefix)] + [str(a) for a in args]
    data = _CB_SEP.join(parts)
    return sanitize_callback_data(data, 64)


def cb_unpack(data: str) -> tuple[str, list[str]]:
    """
    Разбирает callback_data на (prefix, [args]).
    Устойчиво к мусору: если data пустая — вернёт ("", []).
    """
    if not data:
        return "", []
    parts = str(data).split(_CB_SEP)
    return parts[0], parts[1:]


# =============================================================================
#  FSM-СОСТОЯНИЯ
# =============================================================================

class BuyStars(StatesGroup):
    """Покупка звёзд: выбор пакета или своя сумма."""
    choosing = State()
    custom = State()          # ввод своей суммы звёзд


class RouletteSetup(StatesGroup):
    """Сессия рулетки: ожидание ставок после 'старт'."""
    betting = State()


class MinesGame(StatesGroup):
    """Игра «Мины»: активная сессия."""
    playing = State()


class DuelCreate(StatesGroup):
    """Создание дуэли через 'дуэль @user 1000'."""
    waiting_accept = State()


class AdminBroadcast(StatesGroup):
    """Массовая рассылка от админа."""
    waiting_text = State()
    waiting_confirm = State()


class AdminGrant(StatesGroup):
    """@выдать / @забрать — ввод суммы и цели (заготовка)."""
    waiting_args = State()


class AdminPromo(StatesGroup):
    """@промо КОД СУММА ИСПОЛЬЗОВАНИЯ — через FSM, если аргументов нет."""
    waiting_args = State()


class TransferState(StatesGroup):
    """Перевод TOKENS между игроками."""
    waiting_args = State()


class SettingsState(StatesGroup):
    """Настройки профиля (язык и т.п.)."""
    waiting = State()


# =============================================================================
#  REPLY-КЛАВИАТУРЫ
# =============================================================================

def main_reply_kb() -> ReplyKeyboardMarkup:
    """
    8 кнопок главного меню (см. ТЗ).
    Кнопки — Reply-кнопки, всегда на экране.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎮 Как играть"),
                KeyboardButton(text="🎁 Бонус"),
            ],
            [
                KeyboardButton(text="💎 Донат"),
                KeyboardButton(text="👤 Профиль"),
            ],
            [
                KeyboardButton(text="💬 Чаты"),
                KeyboardButton(text="🆘 Поддержка"),
            ],
            [
                KeyboardButton(text="📖 Команды"),
                KeyboardButton(text="🏆 Топ"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери раздел…",
    )


def cancel_reply_kb() -> ReplyKeyboardMarkup:
    """Reply-клавиатура «Отмена» для FSM-ввода."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# =============================================================================
#  INLINE-КЛАВИАТУРЫ
# =============================================================================

def back_inline_kb(target: str = "nav_menu") -> InlineKeyboardMarkup:
    """Единая кнопка «⬅️ Назад» (по ТЗ — callback_data='nav_menu' по умолчанию)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=target)],
        ]
    )


def nav_menu_inline_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад» в главное меню."""
    return back_inline_kb("nav_menu")


def profile_kb(is_vip_active: bool = False) -> InlineKeyboardMarkup:
    """
    Inline-меню профиля: Настройки, История, Язык, Достижения, Рефералы.
    Дополнительно: «Купить VIP» (если не активен) или «Продлить VIP».
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="profile:settings"),
            InlineKeyboardButton(text="📜 История", callback_data="profile:history"),
        ],
        [
            InlineKeyboardButton(text="🌐 Язык", callback_data="profile:language"),
            InlineKeyboardButton(text="🏅 Достижения", callback_data="profile:achievements"),
        ],
        [
            InlineKeyboardButton(text="👥 Рефералы", callback_data="profile:refs"),
        ],
        [
            InlineKeyboardButton(
                text=("⭐ Продлить VIP" if is_vip_active else f"⭐ Купить VIP ({format_money(VIP_PRICE)})"),
                callback_data="profile:buy_vip",
            ),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_kb() -> InlineKeyboardMarkup:
    """Переключатели истории: игры/рулетка/назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Игры", callback_data="history:games"),
                InlineKeyboardButton(text="🎡 Рулетка", callback_data="history:roulette"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:open")],
        ]
    )


def achievements_kb(achievements: Sequence[str]) -> InlineKeyboardMarkup:
    """
    Кнопки достижений: показывает список и статус. Callback — заглушка-инфо.
    Каждая кнопка при нажатии даёт краткое описание (обрабатывается в ЧАСТИ 5).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for code, title in ACHIEVEMENTS.items():
        unlocked = "✅" if code in achievements else "🔒"
        rows.append([InlineKeyboardButton(
            text=f"{unlocked} {title}",
            callback_data=cb_pack("ach", code),
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def donate_kb() -> InlineKeyboardMarkup:
    """
    Меню доната: 4 пресета + «Своя сумма» + VIP + Назад.
    Callback: 'donate:stars:<amount>' для покупки.
    """
    rows: list[list[InlineKeyboardButton]] = []
    # Пресеты по 2 в ряд.
    preset_buttons = [
        InlineKeyboardButton(
            text=f"{stars} ⭐ — {format_money(stars * STAR_TO_TOKENS)}",
            callback_data=cb_pack("donate", "stars", stars),
        )
        for stars in DONATE_PRESETS
    ]
    for i in range(0, len(preset_buttons), 2):
        rows.append(preset_buttons[i:i + 2])
    rows.append([
        InlineKeyboardButton(text="✍️ Своя сумма", callback_data="donate:custom"),
    ])
    rows.append([
        InlineKeyboardButton(text="⭐ VIP за TOKENS", callback_data="donate:vip"),
    ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def donate_custom_kb() -> InlineKeyboardMarkup:
    """Клавиатура для отмены ввода своей суммы звёзд."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="donate:menu")],
        ]
    )


def donate_invoice_kb(stars: int, price_tokens: int) -> InlineKeyboardMarkup:
    """
    Клавиатура под «счёт» на покупку звёзд (в нашем случае — просто
    подтверждение списания TOKENS в обмен на пакет звёзд, так как реальные
    Telegram Stars требуют отдельного провайдера).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ Купить {stars} ⭐ за {format_money(price_tokens)} TOKENS",
                callback_data=cb_pack("donate", "confirm", stars),
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="donate:menu")],
        ]
    )


def chats_kb() -> InlineKeyboardMarkup:
    """
    Меню «Чаты»: 3 ссылки. URL-кнопки не требуют callback-обработчиков.
    Ссылки-заглушки: заменяются на реальные при деплое (можно через env).
    """
    # Ссылки можно вынести в env, но по ТЗ — 3 фиксированных пункта.
    chat_url = _env_get("CHAT_GAME_URL", "https://t.me/") or "https://t.me/"
    swap_url = _env_get("CHAT_SWAP_URL", "https://t.me/") or "https://t.me/"
    news_url = _env_get("CHAT_NEWS_URL", "https://t.me/") or "https://t.me/"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Игровой чат", url=chat_url)],
            [InlineKeyboardButton(text="🔄 Обмен", url=swap_url)],
            [InlineKeyboardButton(text="📰 Новости", url=news_url)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def support_kb() -> InlineKeyboardMarkup:
    """Кнопка «Написать админу» (URL на профиль админа, если задан)."""
    admin_url = _env_get("SUPPORT_URL", f"tg://user?id={ENV.admin_id}") or f"tg://user?id={ENV.admin_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Написать в поддержку", url=admin_url)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def bonus_kb(available: bool) -> InlineKeyboardMarkup:
    """Кнопка «Забрать бонус» (активна, если доступен)."""
    if available:
        btn = InlineKeyboardButton(text=f"🎁 Забрать {format_money(DAILY_BONUS_AMOUNT)}", callback_data="bonus:claim")
    else:
        btn = InlineKeyboardButton(text="⏳ Уже забрано", callback_data="bonus:noop")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def games_kb() -> InlineKeyboardMarkup:
    """
    Быстрый доступ к играм через inline (для сообщения «Как играть» — внизу).
    Сами игры запускаются командами; inline-кнопки — просто напоминание.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Кости", callback_data="games:help:кости"),
                InlineKeyboardButton(text="🎯 Дартс", callback_data="games:help:дартс"),
            ],
            [
                InlineKeyboardButton(text="🏀 Баскет", callback_data="games:help:баскет"),
                InlineKeyboardButton(text="⚽ Футбол", callback_data="games:help:футбол"),
            ],
            [
                InlineKeyboardButton(text="🎳 Боулинг", callback_data="games:help:боулинг"),
                InlineKeyboardButton(text="🎰 Слоты", callback_data="games:help:слоты"),
            ],
            [
                InlineKeyboardButton(text="💣 Мины", callback_data="games:help:мины"),
                InlineKeyboardButton(text="⚔️ Дуэль", callback_data="games:help:дуэль"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def top_kb() -> InlineKeyboardMarkup:
    """Переключатели топа: баланс / победы / уровень."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Баланс", callback_data="top:balance"),
                InlineKeyboardButton(text="🏆 Победы", callback_data="top:wins"),
            ],
            [
                InlineKeyboardButton(text="📈 Уровень", callback_data="top:level"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    """Настройки профиля: язык, приватность (заглушка)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Язык", callback_data="profile:language")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:open")],
        ]
    )


def language_kb() -> InlineKeyboardMarkup:
    """
    Выбор языка. Реальная мультиязычность не реализована (по ТЗ её нет),
    но меню должно быть. Мы сохраним выбор в users (можно расширить схему).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:set:ru"),
            ],
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:open")],
        ]
    )


def mines_kb(game_id: str, opened: set[int], lost: bool = False) -> InlineKeyboardMarkup:
    """
    Поле 5×5 для «Мины». Колбэк: mines:open:<game_id>:<idx>.
    Открытые клетки помечаются ✅ (или 💥 при проигрыше), закрытые — ⬜.
    Внизу: «💰 Забрать» (если ещё живы и открыто >0).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for r in range(MINES_FIELD_SIZE):
        row: list[InlineKeyboardButton] = []
        for c in range(MINES_FIELD_SIZE):
            idx = r * MINES_FIELD_SIZE + c
            if idx in opened:
                text = "✅"
            elif lost:
                text = "💥"
            else:
                text = "⬜"
            row.append(InlineKeyboardButton(
                text=text,
                callback_data=cb_pack("mines", "open", game_id, idx),
            ))
        rows.append(row)

    if not lost and opened:
        rows.append([InlineKeyboardButton(
            text="💰 Забрать", callback_data=cb_pack("mines", "cashout", game_id),
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def duel_kb(duel_id: str) -> InlineKeyboardMarkup:
    """Кнопки дуэли: принять / отклонить."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=cb_pack("duel", "accept", duel_id)),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=cb_pack("duel", "decline", duel_id)),
            ],
        ]
    )


def roulette_result_kb(game_id: str) -> InlineKeyboardMarkup:
    """Кнопки после рулетки: «Повторить» (то же) / «Удвоить» / «Назад»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data=cb_pack("roulette", "repeat", game_id)),
                InlineKeyboardButton(text="✖️2 Удвоить", callback_data=cb_pack("roulette", "double", game_id)),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def admin_kb() -> InlineKeyboardMarkup:
    """Быстрые админ-действия inline (в ЛС админа). Команды — через @."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Стата", callback_data="adm:stat")],
            [InlineKeyboardButton(text="📜 Логи (20)", callback_data="adm:logs:20")],
            [
                InlineKeyboardButton(text="💾 Бекап", callback_data="adm:backup"),
                InlineKeyboardButton(text="🔄 Апдейт", callback_data="adm:update"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def confirm_kb(prefix: str, action: str) -> InlineKeyboardMarkup:
    """Универсальная клавиатура подтверждения: Да / Нет."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=cb_pack(prefix, "yes", action)),
                InlineKeyboardButton(text="❌ Нет", callback_data=cb_pack(prefix, "no", action)),
            ],
        ]
    )


def close_kb() -> InlineKeyboardMarkup:
    """Кнопка закрытия сообщения (удалить)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Закрыть", callback_data="ui:close")],
        ]
    )


def repeat_game_kb(game: str, bet: int) -> InlineKeyboardMarkup:
    """Кнопка «Повторить» для игр на кубиках (быстрый рематч)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🔁 Ещё раз ({format_money(bet)})",
                callback_data=cb_pack("game", "repeat", game, bet),
            )],
        ]
    )


# =============================================================================
#  УТИЛИТЫ ДЛЯ UI: бейджи, статусы
# =============================================================================

def vip_badge(is_active: bool) -> str:
    """Бейдж VIP для профиля/топа."""
    return " ⭐VIP" if is_active else ""


def level_badge(level: int) -> str:
    """Короткий префикс уровня."""
    return f"L{max(1, int(level))}"


def format_profile_text(user: UserRow, vip_active: bool, rank: int = 0) -> str:
    """
    Собирает текст профиля. Используется в ЧАСТИ 5.
    Все пользовательские строки — через html_escape.
    """
    uname = f"@{html_escape(user.username)}" if user.username else html_escape(f"id{user.user_id}")
    bal = format_money(user.balance)
    lvl = calc_level(user.xp)
    need_xp = xp_to_next_level(user.xp)
    badge = vip_badge(vip_active)
    rank_str = f"\n🏅 Место в топе: <b>#{rank}</b>" if rank > 0 else ""

    lines = [
        TEXT_PROFILE_HEADER,
        "",
        f"👤 <b>{uname}</b>{badge}",
        f"🆔 <code>{user.user_id}</code>",
        "",
        f"💰 Баланс: <b>{bal}</b> TOKENS",
        f"📈 Уровень: <b>{level_badge(lvl)}</b> (XP: {user.xp}, до следующего: {need_xp})",
        "",
        f"🎮 Игр: <b>{user.games}</b>",
        f"🏆 Побед: <b>{user.wins}</b>",
    ]
    if user.referrer_id:
        lines.append(f"👥 Реферер: <code>{user.referrer_id}</code>")
    lines.append(rank_str)
    if vip_active:
        expire_ts = int(user.vip)
        try:
            dt = datetime.fromtimestamp(expire_ts, tz=timezone.utc)
            lines.append(f"⭐ VIP до: <b>{dt.strftime('%Y-%m-%d %H:%M UTC')}</b>")
        except Exception:
            pass
    return "\n".join(line for line in lines if line != "")


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 4
# =============================================================================

log.info("ЧАСТЬ 4: UI-хелперы и клавиатуры готовы")

# =============================================================================
#  ЧАСТЬ 5 / 10: ОБРАБОТЧИКИ МЕНЮ
#    - Router (menu_router)
#    - /start (с рефералкой и установкой username)
#    - Reply-кнопки главного меню (8 штук)
#    - Inline: nav_menu, profile:*, donate:*, bonus:*, top:*, lang:*,
#      history:*, ach:*, ui:close
#    - FSM: BuyStars.custom (ввод своей суммы звёзд)
#    - /balance, /profile, /bonus, /top — команды-дубли
# =============================================================================

menu_router: Router = Router(name="menu")


# =============================================================================
#  ОБЩИЕ ПОМОЩНИКИ ДЛЯ ХЕНДЛЕРОВ
# =============================================================================

async def _banned_guard(msg_or_cb: Union[Message, CallbackQuery]) -> bool:
    """
    Проверяет, не забанен ли юзер. Если да — отвечает и возвращает True
    (хендлер должен прекратиться).
    """
    tg_user = msg_or_cb.from_user
    if tg_user is None:
        return True
    if await is_banned(tg_user.id):
        if isinstance(msg_or_cb, CallbackQuery):
            await safe_answer(msg_or_cb, TEXT_ERR_BANNED, show_alert=True)
        else:
            await safe_send(msg_or_cb.chat.id, TEXT_ERR_BANNED)
        return True
    return False


async def _register_user(msg: Message, referrer_id: Optional[int] = None) -> Optional[UserRow]:
    """
    ensure_user + установка реферера (если пришёл по реф-ссылке и ещё нет).
    Возвращает UserRow.
    """
    u = msg.from_user
    if u is None:
        return None
    user = await ensure_user(u.id, username=u.username)
    if referrer_id and user.referrer_id is None and referrer_id != u.id:
        # Реферера принимаем только если у нас ещё нет и это не само-реферал.
        await set_referrer(u.id, referrer_id)
        user = await get_user(u.id) or user
    return user


def _parse_ref_arg(args: Optional[str]) -> Optional[int]:
    """
    Парсит payload /start: 'ref_12345' -> 12345.
    Возвращает None, если формат не подходит.
    """
    if not args:
        return None
    s = args.strip()
    if s.startswith("ref_"):
        s = s[4:]
    return parse_int(s)


# =============================================================================
#  /start
# =============================================================================

@menu_router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(msg: Message, command: CommandObject, state: FSMContext) -> None:
    """Обработка /start с payload (реферальная ссылка)."""
    try:
        await state.clear()
        ref_id = _parse_ref_arg(command.args)
        user = await _register_user(msg, referrer_id=ref_id)
        if user is None:
            return
        if user.banned:
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return

        # Устанавливаем reply-меню только в приватном чате.
        if is_private_chat(msg.chat):
            await safe_send(msg.chat.id, TEXT_START, reply_markup_reply=main_reply_kb())

        # Фото start.jpg с подписью-приветствием, если есть.
        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="start.jpg",
            caption=f"{BOT_EMOJI} <b>{BOT_NAME}</b> — добро пожаловать!\n"
                    f"🎁 На счёт зачислено <b>{format_money(START_BALANCE)} TOKENS</b>.\n"
                    "Используй меню ниже.",
            markup=games_kb(),
        )
        log.info("/start: user=%s ref=%s", user.user_id, user.referrer_id)
    except Exception as exc:
        log_exception("cmd_start_deeplink", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext) -> None:
    """Обычный /start без payload."""
    try:
        await state.clear()
        user = await _register_user(msg)
        if user is None:
            return
        if user.banned:
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return

        if is_private_chat(msg.chat):
            await safe_send(msg.chat.id, TEXT_START, reply_markup_reply=main_reply_kb())

        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="start.jpg",
            caption=f"{BOT_EMOJI} <b>{BOT_NAME}</b>\n"
                    f"💰 Баланс: <b>{format_money(user.balance)} TOKENS</b>\n"
                    "Выбирай раздел в меню 👇",
            markup=games_kb(),
        )
    except Exception as exc:
        log_exception("cmd_start", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


# =============================================================================
#  КОМАНДЫ-ДУБЛИ (быстрый доступ)
# =============================================================================

@menu_router.message(Command("balance", "баланс"))
async def cmd_balance(msg: Message) -> None:
    try:
        u = msg.from_user
        if u is None:
            return
        user = await ensure_user(u.id, username=u.username)
        if user.banned:
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return
        await safe_send(
            msg.chat.id,
            f"💰 Твой баланс: <b>{format_money(user.balance)} TOKENS</b>",
        )
    except Exception as exc:
        log_exception("cmd_balance", exc)


@menu_router.message(Command("profile", "профиль"))
async def cmd_profile(msg: Message) -> None:
    try:
        await _show_profile(msg.chat.id, msg.from_user)
    except Exception as exc:
        log_exception("cmd_profile", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(Command("bonus", "бонус"))
async def cmd_bonus(msg: Message) -> None:
    try:
        await _show_bonus(msg.chat.id, msg.from_user)
    except Exception as exc:
        log_exception("cmd_bonus", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(Command("top", "топ"))
async def cmd_top(msg: Message) -> None:
    try:
        await _show_top(msg.chat.id, "balance")
    except Exception as exc:
        log_exception("cmd_top", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


# =============================================================================
#  REPLY-КНОПКИ ГЛАВНОГО МЕНЮ
# =============================================================================
# Каждая кнопка — отдельный хендлер с текстовым фильтром.
# Это надёжнее F-фильтров по содержимому, потому что aiogram матчит точное
# совпадение текста.
# =============================================================================

@menu_router.message(F.text == "🎮 Как играть")
async def btn_how_to_play(msg: Message) -> None:
    try:
        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="how_to_play.jpg",
            caption=TEXT_HOW_TO_PLAY,
            markup=games_kb(),
        )
    except Exception as exc:
        log_exception("btn_how_to_play", exc)
        await safe_send(msg.chat.id, TEXT_HOW_TO_PLAY, games_kb())


@menu_router.message(F.text == "🎁 Бонус")
async def btn_bonus(msg: Message) -> None:
    try:
        await _show_bonus(msg.chat.id, msg.from_user)
    except Exception as exc:
        log_exception("btn_bonus", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(F.text == "💎 Донат")
async def btn_donate(msg: Message) -> None:
    try:
        await _show_donate(msg.chat.id)
    except Exception as exc:
        log_exception("btn_donate", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(F.text == "👤 Профиль")
async def btn_profile(msg: Message) -> None:
    try:
        await _show_profile(msg.chat.id, msg.from_user)
    except Exception as exc:
        log_exception("btn_profile", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(F.text == "💬 Чаты")
async def btn_chats(msg: Message) -> None:
    try:
        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="chats.jpg",
            caption=TEXT_CHATS,
            markup=chats_kb(),
        )
    except Exception as exc:
        log_exception("btn_chats", exc)
        await safe_send(msg.chat.id, TEXT_CHATS, chats_kb())


@menu_router.message(F.text == "🆘 Поддержка")
async def btn_support(msg: Message) -> None:
    try:
        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="support.jpg",
            caption=TEXT_SUPPORT,
            markup=support_kb(),
        )
    except Exception as exc:
        log_exception("btn_support", exc)
        await safe_send(msg.chat.id, TEXT_SUPPORT, support_kb())


@menu_router.message(F.text == "📖 Команды")
async def btn_commands(msg: Message) -> None:
    try:
        await send_with_photo(
            chat_id=msg.chat.id,
            image_name="commands.jpg",
            caption=TEXT_COMMANDS,
            markup=nav_menu_inline_kb(),
        )
    except Exception as exc:
        log_exception("btn_commands", exc)
        await safe_send(msg.chat.id, TEXT_COMMANDS, nav_menu_inline_kb())


@menu_router.message(F.text == "🏆 Топ")
async def btn_top(msg: Message) -> None:
    try:
        await _show_top(msg.chat.id, "balance")
    except Exception as exc:
        log_exception("btn_top", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.message(F.text == "❌ Отмена")
async def btn_cancel(msg: Message, state: FSMContext) -> None:
    """Универсальная отмена FSM-ввода."""
    try:
        await state.clear()
        await safe_send(
            msg.chat.id,
            "❌ Действие отменено.",
            reply_markup_reply=main_reply_kb(),
        )
    except Exception as exc:
        log_exception("btn_cancel", exc)


# =============================================================================
#  ВНУТРЕННИЕ ФУНКЦИИ ОТОБРАЖЕНИЯ РАЗДЕЛОВ
# =============================================================================

async def _show_profile(chat_id: int, tg_user: Optional[TgUser]) -> None:
    """Собирает и отправляет профиль с inline-меню."""
    if tg_user is None:
        return
    if await is_banned(tg_user.id):
        await safe_send(chat_id, TEXT_ERR_BANNED)
        return
    user = await ensure_user(tg_user.id, username=tg_user.username)
    vip_active = await is_vip(user.user_id)
    rank = await get_user_rank_balance(user.user_id)
    text = format_profile_text(user, vip_active, rank)
    await send_with_photo(
        chat_id=chat_id,
        image_name="profile.jpg",
        caption=text,
        markup=profile_kb(vip_active),
    )


async def _show_bonus(chat_id: int, tg_user: Optional[TgUser]) -> None:
    """Показывает состояние бонуса и кнопку."""
    if tg_user is None:
        return
    if await is_banned(tg_user.id):
        await safe_send(chat_id, TEXT_ERR_BANNED)
        return
    await ensure_user(tg_user.id, username=tg_user.username)
    available, remain = await check_daily_bonus(tg_user.id)
    if available:
        text = TEXT_BONUS_READY
    else:
        text = TEXT_BONUS_ALREADY.format(remain=format_duration(int(remain)))
    await send_with_photo(
        chat_id=chat_id,
        image_name="bonus.jpg",
        caption=text,
        markup=bonus_kb(available),
    )


async def _show_donate(chat_id: int) -> None:
    """Меню доната."""
    await send_with_photo(
        chat_id=chat_id,
        image_name="donate.jpg",
        caption=TEXT_DONATE,
        markup=donate_kb(),
    )


async def _show_top(chat_id: int, mode: str = "balance") -> None:
    """Показывает топ по выбранному режиму."""
    if mode == "wins":
        rows = await get_top_by_wins(10)
        title = "🏆 <b>ТОП ПО ПОБЕДАМ</b>"
    elif mode == "level":
        rows = await get_top_by_level(10)
        title = "📈 <b>ТОП ПО УРОВНЮ</b>"
    else:
        rows = await get_top_by_balance(10)
        title = "💰 <b>ТОП ПО БАЛАНСУ</b>"

    if not rows:
        text = f"{TEXT_TOP_HEADER}\nПока никого нет. Стань первым!"
    else:
        lines = [title, ""]
        for idx, r in enumerate(rows, start=1):
            uid = int(r["user_id"])
            uname = r["username"]
            name = f"@{html_escape(uname)}" if uname else mention_html(uid, f"id{uid}")
            vip = " ⭐VIP" if (("vip" in r.keys()) and int(r["vip"] or 0) > utcnow_ts()) else ""
            if mode == "wins":
                stat = f"🏆 {int(r['wins'])} побед / {int(r['games'])} игр"
            elif mode == "level":
                stat = f"📈 L{int(r['level'])} (XP {int(r['xp'])})"
            else:
                stat = f"💰 {format_money(int(r['balance']))}"
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
            lines.append(f"{medal} {name}{vip} — {stat}")
        text = "\n".join(lines)

    await send_with_photo(
        chat_id=chat_id,
        image_name="top.jpg",
        caption=text,
        markup=top_kb(),
    )


# =============================================================================
#  INLINE: НАВИГАЦИЯ «НАЗАД»
# =============================================================================

@menu_router.callback_query(F.data == "nav_menu")
async def cb_nav_menu(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer(cb)
        await state.clear()
        if not cb.message:
            return
        # Убираем фото, отправляем приветствие с меню.
        try:
            await cb.message.delete()
        except Exception:
            pass
        await safe_send(
            cb.message.chat.id,
            f"{BOT_EMOJI} <b>Главное меню</b>\nВыбирай раздел 👇",
            reply_markup_reply=main_reply_kb() if is_private_chat(cb.message.chat) else None,
        )
    except Exception as exc:
        log_exception("cb_nav_menu", exc)


@menu_router.callback_query(F.data == "ui:close")
async def cb_ui_close(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message:
            await safe_delete(cb.message.chat.id, cb.message.message_id)
    except Exception as exc:
        log_exception("cb_ui_close", exc)


# =============================================================================
#  INLINE: ПРОФИЛЬ
# =============================================================================

@menu_router.callback_query(F.data == "profile:open")
async def cb_profile_open(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message and cb.from_user:
            await _show_profile(cb.message.chat.id, cb.from_user)
    except Exception as exc:
        log_exception("cb_profile_open", exc)


@menu_router.callback_query(F.data == "profile:settings")
async def cb_profile_settings(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                "⚙️ <b>Настройки</b>\n\nПока доступен только выбор языка.",
                settings_kb(),
            )
    except Exception as exc:
        log_exception("cb_profile_settings", exc)


@menu_router.callback_query(F.data == "profile:language")
async def cb_profile_language(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                "🌐 <b>Выбери язык интерфейса</b>\n\n"
                "(Полная мультиязычность появится позже, выбор сохраняется.)",
                language_kb(),
            )
    except Exception as exc:
        log_exception("cb_profile_language", exc)


@menu_router.callback_query(F.data.startswith("lang:set:"))
async def cb_lang_set(cb: CallbackQuery) -> None:
    """Устанавливает язык. Хранение — заглушка в памяти (расширяемо)."""
    try:
        await safe_answer(cb)
        if not cb.data:
            return
        _, _, lang = cb.data.split(":", 2)
        lang = lang if lang in ("ru", "en") else "ru"
        RUNTIME_FLAGS.setdefault("user_lang", {})[int(cb.from_user.id)] = lang
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                f"✅ Язык сохранён: <b>{'Русский' if lang == 'ru' else 'English'}</b>",
                profile_kb(await is_vip(cb.from_user.id)),
            )
    except Exception as exc:
        log_exception("cb_lang_set", exc)


@menu_router.callback_query(F.data == "profile:history")
async def cb_profile_history(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message and cb.from_user:
            await _render_history(cb.message.chat.id, cb.message.message_id, cb.from_user.id, "games")
    except Exception as exc:
        log_exception("cb_profile_history", exc)


@menu_router.callback_query(F.data.startswith("history:"))
async def cb_history_switch(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if not cb.data or not cb.message:
            return
        mode = cb.data.split(":", 1)[1]
        await _render_history(cb.message.chat.id, cb.message.message_id, cb.from_user.id, mode)
    except Exception as exc:
        log_exception("cb_history_switch", exc)


async def _render_history(chat_id: int, message_id: int, user_id: int, mode: str) -> None:
    """Рендерит историю игр или рулетки."""
    if mode == "roulette":
        rows = await get_roulette_history(user_id, 10)
        header = "🎡 <b>История рулетки</b>\n"
        if not rows:
            body = "\nПока нет ставок."
        else:
            lines = []
            for r in rows:
                bet = int(r["bet"])
                win = int(r["win"])
                delta = win - bet
                sign = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
                numbers = r["numbers"] or "—"
                ts = str(r["created_at"])[:16].replace("T", " ")
                lines.append(f"{sign} ставка {format_money(bet)} → {format_money(win)} "
                             f"(числа: {html_escape(numbers)}) · {ts}")
            body = "\n" + "\n".join(lines[-10:])
    else:
        rows = await get_game_history(user_id, 10)
        header = "🎲 <b>История игр</b>\n"
        if not rows:
            body = "\nПока нет игр."
        else:
            lines = []
            for r in rows:
                bet = int(r["bet"]); win = int(r["win"])
                delta = win - bet
                sign = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
                game = html_escape(str(r["game"]))
                res = html_escape(str(r["result"] or ""))
                ts = str(r["created_at"])[:16].replace("T", " ")
                lines.append(f"{sign} {game}: {format_money(bet)} → {format_money(win)} "
                             f"({res}) · {ts}")
            body = "\n" + "\n".join(lines[-10:])

    await safe_edit(chat_id, message_id, header + body, history_kb())


@menu_router.callback_query(F.data == "profile:achievements")
async def cb_profile_achievements(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if not cb.message or not cb.from_user:
            return
        user = await ensure_user(cb.from_user.id, username=cb.from_user.username)
        unlocked = user.achievements_list()
        lines = ["🏅 <b>ДОСТИЖЕНИЯ</b>\n"]
        for code, title in ACHIEVEMENTS.items():
            mark = "✅" if code in unlocked else "🔒"
            lines.append(f"{mark} <b>{title}</b> — {ACHIEVEMENTS_DESC.get(code, '')}")
        progress = f"\n\n📊 Открыто: <b>{len(unlocked)}/{len(ACHIEVEMENTS)}</b>"
        await safe_edit(
            cb.message.chat.id, cb.message.message_id,
            "\n".join(lines) + progress,
            achievements_kb(unlocked),
        )
    except Exception as exc:
        log_exception("cb_profile_achievements", exc)


@menu_router.callback_query(F.data.startswith("ach:"))
async def cb_achievement_info(cb: CallbackQuery) -> None:
    """Показывает описание конкретного достижения."""
    try:
        if not cb.data:
            await safe_answer(cb)
            return
        _, code = cb_unpack(cb.data)
        c = code[0] if code else ""
        title = ACHIEVEMENTS.get(c, "Неизвестно")
        desc = ACHIEVEMENTS_DESC.get(c, "")
        await safe_answer(cb, f"{title}\n{desc}", show_alert=True)
    except Exception as exc:
        log_exception("cb_achievement_info", exc)


@menu_router.callback_query(F.data == "profile:refs")
async def cb_profile_refs(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if not cb.message or not cb.from_user:
            return
        bot_username = (await get_bot().me()).username if get_bot() else "bot"
        link = f"https://t.me/{bot_username}?start=ref_{cb.from_user.id}"
        total = await count_referrals(cb.from_user.id)
        paid = await count_paid_referrals(cb.from_user.id)
        text = (
            "👥 <b>РЕФЕРАЛЫ</b>\n\n"
            f"🔗 Твоя ссылка:\n<code>{html_escape(link)}</code>\n\n"
            f"👤 Приглашено: <b>{total}</b>\n"
            f"💰 Оплачено (сыграли): <b>{paid}</b>\n\n"
            f"🎁 За каждого друга, который сыграет 1 игру — "
            f"<b>{format_money(REFERRAL_REWARD)} TOKENS</b>."
        )
        await send_with_photo(
            chat_id=cb.message.chat.id,
            image_name="ref.jpg",
            caption=text,
            markup=back_inline_kb("profile:open"),
        )
    except Exception as exc:
        log_exception("cb_profile_refs", exc)


@menu_router.callback_query(F.data == "profile:buy_vip")
async def cb_profile_buy_vip(cb: CallbackQuery) -> None:
    """Покупка/продление VIP за TOKENS."""
    try:
        if not cb.from_user:
            await safe_answer(cb)
            return
        user = await ensure_user(cb.from_user.id, username=cb.from_user.username)
        if user.balance < VIP_PRICE and user.user_id not in GOD_MODE_USERS:
            await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
            return
        ok = await try_withdraw(user.user_id, VIP_PRICE)
        if not ok:
            await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
            return
        new_ts = await activate_vip(user.user_id)
        try:
            dt = datetime.fromtimestamp(new_ts, tz=timezone.utc)
            expiry = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            expiry = str(new_ts)
        await safe_answer(cb, f"⭐ VIP активирован до {expiry}", show_alert=True)
        await log_admin_action(user.user_id, "vip_buy", f"price={VIP_PRICE}")
        if cb.message:
            await _show_profile(cb.message.chat.id, cb.from_user)
    except Exception as exc:
        log_exception("cb_profile_buy_vip", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


# =============================================================================
#  INLINE: БОНУС
# =============================================================================

@menu_router.callback_query(F.data == "bonus:claim")
async def cb_bonus_claim(cb: CallbackQuery) -> None:
    try:
        if not cb.from_user:
            await safe_answer(cb)
            return
        if await is_banned(cb.from_user.id):
            await safe_answer(cb, TEXT_ERR_BANNED, show_alert=True)
            return
        ok, amount, remain = await claim_daily_bonus(cb.from_user.id)
        if not ok:
            await safe_answer(
                cb,
                f"⏳ Бонус уже забран. Возвращайся через {format_duration(int(remain))}",
                show_alert=True,
            )
            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    TEXT_BONUS_ALREADY.format(remain=format_duration(int(remain))),
                    bonus_kb(False),
                )
            return
        await safe_answer(cb, f"🎁 +{format_money(amount)} TOKENS", show_alert=True)
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                f"✅ Бонус получен: <b>+{format_money(amount)} TOKENS</b>\n\n"
                f"Возвращайся через {format_duration(DAILY_BONUS_COOLDOWN)}.",
                bonus_kb(False),
            )
    except Exception as exc:
        log_exception("cb_bonus_claim", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


@menu_router.callback_query(F.data == "bonus:noop")
async def cb_bonus_noop(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb, "⏳ Ещё рано.", show_alert=False)
    except Exception as exc:
        log_exception("cb_bonus_noop", exc)


# =============================================================================
#  INLINE: ТОП
# =============================================================================

@menu_router.callback_query(F.data.startswith("top:"))
async def cb_top_switch(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if not cb.data or not cb.message:
            return
        mode = cb.data.split(":", 1)[1]
        if mode not in ("balance", "wins", "level"):
            mode = "balance"
        # Обновим текст, сохранив картинку — но проще пере-отправить.
        # Для простоты — редактируем только текст, если сообщение текстовое.
        # Здесь безопаснее пере-отправить сообщение заново.
        await _show_top(cb.message.chat.id, mode)
    except Exception as exc:
        log_exception("cb_top_switch", exc)


# =============================================================================
#  INLINE: ДОНАТ
# =============================================================================

@menu_router.callback_query(F.data == "donate:menu")
async def cb_donate_menu(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if cb.message:
            await safe_edit(cb.message.chat.id, cb.message.message_id, TEXT_DONATE, donate_kb())
    except Exception as exc:
        log_exception("cb_donate_menu", exc)


@menu_router.callback_query(F.data == "donate:custom")
async def cb_donate_custom(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer(cb)
        await state.set_state(BuyStars.custom)
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                "✍️ <b>Своя сумма звёзд</b>\n\n"
                f"Введи количество ⭐ (от 1 до 10000).\n"
                f"Курс: <b>1 ⭐ = {format_money(STAR_TO_TOKENS)} TOKENS</b>.",
                donate_custom_kb(),
            )
    except Exception as exc:
        log_exception("cb_donate_custom", exc)


@menu_router.message(BuyStars.custom)
async def fsm_buy_stars_custom(msg: Message, state: FSMContext) -> None:
    """Обрабатывает ввод своей суммы звёзд."""
    try:
        if not msg.from_user:
            return
        raw = safe_str(msg.text or "", 20)
        stars = parse_positive_int(raw)
        if stars is None or stars < 1 or stars > 10_000:
            await safe_send(
                msg.chat.id,
                "❌ Введи целое число звёзд от 1 до 10 000.",
            )
            return
        await state.clear()
        price = stars * STAR_TO_TOKENS
        await safe_send(
            msg.chat.id,
            f"⭐ <b>{stars} ⭐</b>\n"
            f"💰 Стоимость: <b>{format_money(price)} TOKENS</b>\n\n"
            "Подтверди покупку 👇",
            donate_invoice_kb(stars, price),
            reply_markup_reply=main_reply_kb() if is_private_chat(msg.chat) else None,
        )
    except Exception as exc:
        log_exception("fsm_buy_stars_custom", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@menu_router.callback_query(F.data.startswith("donate:stars:") | F.data.startswith("donate:confirm:"))
async def cb_donate_buy(cb: CallbackQuery) -> None:
    """
    Обрабатывает покупку звёзд (обмен TOKENS на пакет звёзд).
    Реальные Telegram Stars требуют Payment Provider — здесь упрощённо:
    списываем TOKENS и зачисляем «звёзды» в виде TOKENS по курсу +X%.
    По ТЗ: донат — это пополнение TOKENS за звёзды. У нас нет реального
    платёжного провайдера, поэтому «покупка звёзд» = моментальное зачисление.
    """
    try:
        if not cb.data or not cb.from_user:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 3:
            await safe_answer(cb)
            return
        action = parts[1]
        try:
            stars = int(parts[2])
        except ValueError:
            await safe_answer(cb, "❌ Неверная сумма", show_alert=True)
            return
        if stars <= 0 or stars > 10_000:
            await safe_answer(cb, "❌ Сумма вне диапазона", show_alert=True)
            return

        price = stars * STAR_TO_TOKENS

        if action == "stars":
            # Показываем подтверждение
            await safe_answer(cb)
            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    f"⭐ <b>Покупка {stars} ⭐</b>\n\n"
                    f"💰 Стоимость: <b>{format_money(price)} TOKENS</b>\n\n"
                    "Подтверди покупку 👇",
                    donate_invoice_kb(stars, price),
                )
            return

        if action == "confirm":
            user = await ensure_user(cb.from_user.id, username=cb.from_user.username)
            if user.banned:
                await safe_answer(cb, TEXT_ERR_BANNED, show_alert=True)
                return
            if user.balance < price and user.user_id not in GOD_MODE_USERS:
                await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
                return
            ok = await try_withdraw(user.user_id, price)
            if not ok:
                await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
                return
            # Зачисляем TOKENS эквивалент звёзд + бонус 5% (в рамках игры).
            credited = int(stars * STAR_TO_TOKENS * 1.05)
            await add_balance(user.user_id, credited, ensure=False)
            await log_admin_action(user.user_id, "donate_buy", f"stars={stars} price={price} credited={credited}")
            await safe_answer(cb, f"✅ Куплено {stars} ⭐ (+{format_money(credited)} TOKENS)", show_alert=True)
            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    f"✅ <b>Успешно!</b>\n\n"
                    f"⭐ Получено звёзд: <b>{stars}</b>\n"
                    f"💰 Зачислено: <b>+{format_money(credited)} TOKENS</b>\n\n"
                    "Спасибо за поддержку! 💎",
                    back_inline_kb("nav_menu"),
                )
            return
        await safe_answer(cb)
    except Exception as exc:
        log_exception("cb_donate_buy", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


@menu_router.callback_query(F.data == "donate:vip")
async def cb_donate_vip(cb: CallbackQuery) -> None:
    """Информация о VIP и кнопка покупки."""
    try:
        await safe_answer(cb)
        if not cb.message or not cb.from_user:
            return
        vip_active = await is_vip(cb.from_user.id)
        text = (
            "⭐ <b>VIP-СТАТУС</b>\n\n"
            f"💰 Цена: <b>{format_money(VIP_PRICE)} TOKENS</b>\n"
            f"⏳ Срок: <b>{VIP_DURATION_DAYS} дней</b>\n"
            f"📈 Бонус: <b>+{int(VIP_WIN_BONUS*100)}%</b> к выигрышу\n"
            "🏅 Бейдж ⭐ VIP в профиле и топе\n\n"
            + ("✅ VIP уже активен — можно продлить." if vip_active else "Купить VIP?")
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=("⭐ Продлить VIP" if vip_active else f"⭐ Купить за {format_money(VIP_PRICE)}"),
                callback_data="profile:buy_vip",
            )],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="donate:menu")],
        ])
        await safe_edit(cb.message.chat.id, cb.message.message_id, text, kb)
    except Exception as exc:
        log_exception("cb_donate_vip", exc)


# =============================================================================
#  INLINE: ИГРЫ (справка по кнопкам)
# =============================================================================

@menu_router.callback_query(F.data.startswith("games:help:"))
async def cb_games_help(cb: CallbackQuery) -> None:
    """Краткая справка по игре по inline-кнопке."""
    try:
        if not cb.data:
            await safe_answer(cb)
            return
        _, _, game = cb.data.split(":", 2)
        examples = {
            "кости":  "кости 1000",
            "дартс":  "дартс 500",
            "баскет": "баскет 1000",
            "футбол": "футбол 2000",
            "боулинг": "боулинг 1000",
            "слоты":  "слоты 1000",
            "мины":   "мины 1000",
            "дуэль":  "дуэль @username 1000",
        }
        ex = examples.get(game, f"{game} 1000")
        await safe_answer(cb, f"Команда: {ex}", show_alert=True)
    except Exception as exc:
        log_exception("cb_games_help", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=False)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 5
# =============================================================================

log.info("ЧАСТЬ 5: обработчики меню готовы")

# =============================================================================
#  ЧАСТЬ 6 / 10: ИГРЫ НА КУБИКАХ
#    - Router: dice_router
#    - Команды: кости, дартс, баскет, футбол, боулинг, бж, слоты
#    - Общая логика: списание → бросок → расчёт → лог → автоудаление
#    - Антиспам 3 сек (БД + memory)
#    - VIP +5% к выигрышу
#    - Кнопка «🔁 Ещё раз» (callback: game:repeat:<game>:<bet>)
#    - Защита от double-spend через INFLIGHT_LOCKS
# =============================================================================

dice_router: Router = Router(name="dice")


# =============================================================================
#  КОНФИГУРАЦИЯ ИГР
# =============================================================================
# max_face — верхняя граница "выигрышного" значения эмодзи (по Telegram:
# 🎲/🎯/🎳 → 1..6, 🏀/⚽ → 1..5, 🎰 → 1..64 для слотов).
# win_threshold — при каком значении считаем «победа» (обычно >3).
# mult — множитель при победе (для слотов — особая логика).
# =============================================================================

@dataclass(frozen=True, slots=True)
class DiceGameConfig:
    key: str
    emoji: str
    title: str
    max_face: int
    win_threshold: int
    mult: float = 2.0
    min_bet: int = ROULETTE_MIN_BET
    max_bet: int = ROULETTE_MAX_BET


DICE_GAMES: dict[str, DiceGameConfig] = {
    "кости":   DiceGameConfig("кости",   "🎲", "Кости",   max_face=6, win_threshold=3, mult=2.0),
    "дартс":   DiceGameConfig("дартс",   "🎯", "Дартс",   max_face=6, win_threshold=3, mult=2.0),
    "баскет":  DiceGameConfig("баскет",  "🏀", "Баскет",  max_face=5, win_threshold=3, mult=2.0),
    "футбол":  DiceGameConfig("футбол",  "⚽", "Футбол",  max_face=5, win_threshold=3, mult=2.0),
    "боулинг": DiceGameConfig("боулинг", "🎳", "Боулинг", max_face=6, win_threshold=3, mult=2.0),
    "бж":      DiceGameConfig("бж",      "🎰", "Слоты",   max_face=64, win_threshold=0, mult=0.0),
    "слоты":   DiceGameConfig("слоты",   "🎰", "Слоты",   max_face=64, win_threshold=0, mult=0.0),
}

# Псевдонимы команд → ключ в DICE_GAMES.
DICE_ALIASES: dict[str, str] = {
    "кости": "кости", "кубик": "кости", "кубики": "кости", "dice": "кости",
    "дартс": "дартс", "darts": "дартс",
    "баскет": "баскет", "баскетбол": "баскет", "basket": "баскет",
    "футбол": "футбол", "football": "футбол", "soccer": "футбол",
    "боулинг": "боулинг", "bowling": "боулинг",
    "бж": "бж",
    "слоты": "слоты", "слот": "слоты", "slots": "слоты",
}


# =============================================================================
#  РАСЧЁТ СЛОТОВ (эмодзи 🎰 возвращает 1..64)
# =============================================================================
# Значение 64 — это "семёрки" (джекпот). Логика:
#   1..21   → проигрыш (0x)
#   22..42  → возврат ставки (1x)
#   43..63  → выигрыш 2x
#   64      → джекпот 10x
# =============================================================================

def _calc_slot_prize(bet: int, face: int) -> tuple[int, str]:
    """Возвращает (win_amount, description)."""
    if face == 64:
        return bet * 10, "🎉 ДЖЕКПОТ x10!"
    if face >= 43:
        return bet * 2, "📈 Выигрыш x2"
    if face >= 22:
        return bet, "➖ Возврат ставки"
    return 0, "📉 Проигрыш"


# =============================================================================
#  ХЕЛПЕРЫ
# =============================================================================

def _dice_cooldown_memory(user_id: int) -> tuple[bool, int]:
    """
    Дополнительный in-memory антиспам (защищает от спама в пределах одного
    процесса, пока БД-проверка ещё не отработала).
    Возвращает (можно, осталось_сек).
    """
    now = time.monotonic()
    last = INFLIGHT_LOCKS.get(user_id)
    if last is not None and (now - last) < GAME_COOLDOWN_SEC:
        return False, int(GAME_COOLDOWN_SEC - (now - last)) + 1
    return True, 0


def _mark_dice_cooldown(user_id: int) -> None:
    INFLIGHT_LOCKS[int(user_id)] = time.monotonic()


def _game_lock_acquire(user_id: int, game_key: str) -> bool:
    """Пытается взять игру юзера в «inflight». False — уже что-то играет."""
    uid = int(user_id)
    if uid in ACTIVE_GAME_LOCKS:
        return False
    ACTIVE_GAME_LOCKS[uid] = game_key
    return True


def _game_lock_release(user_id: int) -> None:
    ACTIVE_GAME_LOCKS.pop(int(user_id), None)


async def _parse_bet(msg: Message, game_cfg: DiceGameConfig) -> Optional[int]:
    """
    Извлекает ставку из команды: «кости 1000» → 1000.
    Отправляет пользователю сообщение об ошибке при невалидной ставке.
    Возвращает None при ошибке.
    """
    text = (msg.text or "").strip()
    parts = split_command_args(text)
    # parts[0] — команда, parts[1] — ставка (может отсутствовать).
    if len(parts) < 2:
        await safe_send(
            msg.chat.id,
            f"❌ Укажи ставку.\nПример: <code>{game_cfg.key} 1000</code>",
        )
        return None
    bet = parse_positive_int(parts[1])
    if bet is None:
        await safe_send(
            msg.chat.id,
            "❌ Ставка должна быть положительным целым числом.",
        )
        return None
    if bet < game_cfg.min_bet:
        await safe_send(msg.chat.id, f"❌ Минимальная ставка: {format_money(game_cfg.min_bet)} TOKENS.")
        return None
    if bet > game_cfg.max_bet:
        await safe_send(msg.chat.id, f"❌ Максимальная ставка: {format_money(game_cfg.max_bet)} TOKENS.")
        return None
    return bet


async def _roll_dice(chat_id: int, emoji: str) -> Optional[Message]:
    """
    Отправляет dice-сообщение и возвращает его (со значением).
    Если Telegram не поддерживает эмодзи — возвращает None.
    """
    bot = get_bot()
    if bot is None:
        return None
    try:
        return await bot.send_dice(chat_id=chat_id, emoji=emoji)
    except TelegramBadRequest as exc:
        log.warning("_roll_dice: %s", exc)
        return None
    except TelegramAPIError as exc:
        log_exception("_roll_dice", exc)
        return None


def _apply_vip_bonus(win: int, vip_active: bool) -> int:
    """Применяет +5% к выигрышу для VIP (округляем вниз)."""
    if not vip_active or win <= 0:
        return win
    bonus = int(win * VIP_WIN_BONUS)
    return win + bonus


async def _settle_dice_game(
    *,
    user_id: int,
    chat_id: int,
    game_cfg: DiceGameConfig,
    bet: int,
    face: int,
    vip_active: bool,
) -> tuple[int, str, str]:
    """
    Рассчитывает результат партии.
    Возвращает (win_amount, human_result, log_result).
    НЕ начисляет баланс — это делает вызывающий код через add_balance.
    """
    if game_cfg.key in ("бж", "слоты"):
        win, desc = _calc_slot_prize(bet, face)
        win = _apply_vip_bonus(win, vip_active)
        return win, desc, f"face={face}"

    # Обычные кубики.
    if face > game_cfg.win_threshold:
        raw_win = int(bet * game_cfg.mult)
        win = _apply_vip_bonus(raw_win, vip_active)
        return win, f"🎉 Победа! x{int(game_cfg.mult)}", f"face={face} win"
    return 0, "📉 Проигрыш", f"face={face} lose"


async def _schedule_autodelete(chat_id: int, message_id: int) -> None:
    """Планирует удаление сообщения через GAME_AUTODELETE_SEC (фоново)."""
    async def _task() -> None:
        await safe_delete(chat_id, message_id, delay=GAME_AUTODELETE_SEC)
    asyncio.create_task(_task())


async def _notify_referral_after_first_game(user_id: int) -> None:
    """
    Если у юзера есть реферер и это его первая игра — пытаемся выплатить
    реф-бонус. try_pay_referral идемпотентен (таблица referral_paid).
    """
    try:
        referrer = await try_pay_referral(user_id)
        if referrer is not None:
            # Сообщаем рефереру (не критично, если не получится).
            await safe_send(
                referrer,
                f"🎁 Твой реферал сыграл первую игру — "
                f"<b>+{format_money(REFERRAL_REWARD)} TOKENS</b>!",
            )
    except Exception as exc:
        log_exception("_notify_referral_after_first_game", exc)


# =============================================================================
#  УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ИГРЫ НА КУБИКАХ
# =============================================================================

async def _play_dice_game(msg: Message, game_cfg: DiceGameConfig) -> None:
    """
    Полный цикл игры:
      1. Проверка бана / группы / игр в чате.
      2. Парсинг ставки.
      3. Антиспам (БД + память) и in-flight lock.
      4. Атомарное списание.
      5. Бросок кубика.
      6. Расчёт + начисление.
      7. Лог игры + уведомление реферала (первая игра).
      8. Сообщение-результат с кнопкой «Ещё раз» + автоудаление.
    """
    u = msg.from_user
    if u is None:
        return

    # 1. Защита от бана.
    if await is_banned(u.id):
        await safe_send(msg.chat.id, TEXT_ERR_BANNED)
        return

    # 1.1. Если группа — проверяем games_enabled.
    if is_group_chat(msg.chat) and not await chat_games_enabled(msg.chat.id):
        await safe_send(msg.chat.id, TEXT_ERR_GAMES_DISABLED)
        return

    # 2. Парсинг ставки.
    bet = await _parse_bet(msg, game_cfg)
    if bet is None:
        return

    # 3. Антиспам — память + БД.
    ok_mem, remain_mem = _dice_cooldown_memory(u.id)
    if not ok_mem:
        await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_mem))
        return
    ok_db, remain_db = await check_game_cooldown(u.id)
    if not ok_db:
        await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_db))
        return

    # 3.1. In-flight lock — не даём запустить две игры параллельно.
    if not _game_lock_acquire(u.id, game_cfg.key):
        await safe_send(msg.chat.id, "⏳ Ты уже играешь. Дождись результата.")
        return

    try:
        # 4. Атомарное списание.
        ok = await try_withdraw(u.id, bet, username=u.username)
        if not ok:
            await safe_send(msg.chat.id, TEXT_ERR_NOT_ENOUGH)
            return

        _mark_dice_cooldown(u.id)

        # 5. Бросок кубика.
        dice_msg = await _roll_dice(msg.chat.id, game_cfg.emoji)
        if dice_msg is None:
            # Не удалось бросить — возвращаем ставку.
            await add_balance(u.id, bet, ensure=False)
            await safe_send(msg.chat.id, "⚠️ Не удалось бросить кубик. Ставка возвращена.")
            return

        face = 0
        try:
            if dice_msg.dice:
                face = int(dice_msg.dice.value)
        except Exception:
            face = 0

        # Небольшая пауза — как будто «крутится».
        await asyncio.sleep(1.2)

        # 6. Расчёт.
        vip_active = await is_vip(u.id)
        win, human_result, log_result = await _settle_dice_game(
            user_id=u.id, chat_id=msg.chat.id, game_cfg=game_cfg,
            bet=bet, face=face, vip_active=vip_active,
        )

        # Начисление выигрыша (если есть).
        if win > 0:
            await add_balance(u.id, win, ensure=False)

        # 7. Логи.
        await log_game(u.id, game_cfg.key, bet, win, log_result)
        # Первая игра — реф-бонус.
        try:
            if await has_played_any_game(u.id):
                # has_played_any_game вернёт True и для только что сыгранной.
                # Поэтому вызываем try_pay_referral — он сам идемпотентен.
                await _notify_referral_after_first_game(u.id)
        except Exception as exc:
            log_exception("_play_dice_game:referral", exc)

        # 8. Результат.
        delta = win - bet
        sign = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
        vip_str = " ⭐VIP +5%" if vip_active and win > 0 else ""
        text = (
            f"{game_cfg.emoji} <b>{game_cfg.title}</b>\n\n"
            f"👤 {mention_html(u.id, humanize_username(u))}\n"
            f"🎲 Значение: <b>{face}</b>\n"
            f"💰 Ставка: <b>{format_money(bet)}</b> TOKENS\n"
            f"{sign} Итог: <b>{format_money(win)}</b> TOKENS "
            f"({'+' if delta >= 0 else ''}{format_money(delta)}){vip_str}\n"
            f"📝 {human_result}"
        )
        result_msg = await safe_send(
            msg.chat.id, text,
            markup=repeat_game_kb(game_cfg.key, bet),
        )
        if result_msg is not None:
            await _schedule_autodelete(msg.chat.id, result_msg.message_id)

        # Достижения.
        try:
            if win > bet:
                await _try_grant_lucky_achievement(u.id)
        except Exception as exc:
            log_exception("_play_dice_game:achievements", exc)

    except Exception as exc:
        log_exception("_play_dice_game", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)
    finally:
        _game_lock_release(u.id)


async def _try_grant_lucky_achievement(user_id: int) -> None:
    """
    Выдаёт «Везунчик» при 10 победах подряд.
    Считаем последние 10 игр: если все win>bet — выдаём.
    """
    rows = await fetchall(
        "SELECT bet, win FROM games_log WHERE user_id = ? "
        "ORDER BY id DESC LIMIT 10",
        (int(user_id),),
    )
    if len(rows) < 10:
        return
    if all(int(r["win"]) > int(r["bet"]) for r in rows):
        granted = await grant_achievement(user_id, "lucky")
        if granted:
            await safe_send(
                user_id,
                "🏅 Достижение разблокировано: <b>🍀 Везунчик</b>!\n"
                "10 побед подряд — так держать!",
            )


# =============================================================================
#  КОМАНДЫ ИГР (каждая — тонкая обёртка)
# =============================================================================

@dice_router.message(Command("кости", "кубик", "кубики", "dice"))
async def cmd_dice(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["кости"])


@dice_router.message(Command("дартс", "darts"))
async def cmd_darts(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["дартс"])


@dice_router.message(Command("баскет", "баскетбол", "basket"))
async def cmd_basket(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["баскет"])


@dice_router.message(Command("футбол", "football", "soccer"))
async def cmd_football(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["футбол"])


@dice_router.message(Command("боулинг", "bowling"))
async def cmd_bowling(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["боулинг"])


@dice_router.message(Command("бж"))
async def cmd_slots_short(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["бж"])


@dice_router.message(Command("слоты", "слот", "slots"))
async def cmd_slots(msg: Message) -> None:
    await _play_dice_game(msg, DICE_GAMES["слоты"])


# =============================================================================
#  КНОПКА «ЕЩЁ РАЗ»
# =============================================================================
# callback_data: game:repeat:<game>:<bet>
# Хендлер сам делает списание и бросок — полностью повторяет логику.
# =============================================================================

@dice_router.callback_query(F.data.startswith("game:repeat:"))
async def cb_game_repeat(cb: CallbackQuery) -> None:
    try:
        if not cb.data or not cb.from_user:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 4:
            await safe_answer(cb, "❌ Ошибка кнопки", show_alert=True)
            return
        _, _, game_key, bet_raw = parts[0], parts[1], parts[2], parts[3]
        game_cfg = DICE_GAMES.get(game_key)
        if game_cfg is None:
            await safe_answer(cb, "❌ Неизвестная игра", show_alert=True)
            return
        bet = parse_positive_int(bet_raw)
        if bet is None:
            await safe_answer(cb, "❌ Неверная ставка", show_alert=True)
            return

        # Быстрая проверка бана.
        if await is_banned(cb.from_user.id):
            await safe_answer(cb, TEXT_ERR_BANNED, show_alert=True)
            return

        # Антиспам.
        ok_mem, remain_mem = _dice_cooldown_memory(cb.from_user.id)
        if not ok_mem:
            await safe_answer(cb, f"⏳ Подожди {remain_mem} сек.", show_alert=True)
            return
        ok_db, remain_db = await check_game_cooldown(cb.from_user.id)
        if not ok_db:
            await safe_answer(cb, f"⏳ Подожди {remain_db} сек.", show_alert=True)
            return

        if not _game_lock_acquire(cb.from_user.id, game_cfg.key):
            await safe_answer(cb, "⏳ Уже играешь.", show_alert=True)
            return

        try:
            ok = await try_withdraw(cb.from_user.id, bet, username=cb.from_user.username)
            if not ok:
                await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
                return

            _mark_dice_cooldown(cb.from_user.id)

            # Отвечаем сразу — иначе кнопка "залипнет".
            await safe_answer(cb)

            if cb.message is None:
                return

            chat_id = cb.message.chat.id
            dice_msg = await _roll_dice(chat_id, game_cfg.emoji)
            if dice_msg is None:
                await add_balance(cb.from_user.id, bet, ensure=False)
                await safe_send(chat_id, "⚠️ Не удалось бросить кубик. Ставка возвращена.")
                return

            face = 0
            try:
                if dice_msg.dice:
                    face = int(dice_msg.dice.value)
            except Exception:
                face = 0

            await asyncio.sleep(1.2)

            vip_active = await is_vip(cb.from_user.id)
            win, human_result, log_result = await _settle_dice_game(
                user_id=cb.from_user.id, chat_id=chat_id,
                game_cfg=game_cfg, bet=bet, face=face, vip_active=vip_active,
            )
            if win > 0:
                await add_balance(cb.from_user.id, win, ensure=False)

            await log_game(cb.from_user.id, game_cfg.key, bet, win, log_result)

            delta = win - bet
            sign = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
            vip_str = " ⭐VIP +5%" if vip_active and win > 0 else ""
            text = (
                f"{game_cfg.emoji} <b>{game_cfg.title}</b>\n\n"
                f"👤 {mention_html(cb.from_user.id, humanize_username(cb.from_user))}\n"
                f"🎲 Значение: <b>{face}</b>\n"
                f"💰 Ставка: <b>{format_money(bet)}</b> TOKENS\n"
                f"{sign} Итог: <b>{format_money(win)}</b> TOKENS "
                f"({'+' if delta >= 0 else ''}{format_money(delta)}){vip_str}\n"
                f"📝 {human_result}"
            )
            result_msg = await safe_send(chat_id, text, markup=repeat_game_kb(game_cfg.key, bet))
            if result_msg is not None:
                await _schedule_autodelete(chat_id, result_msg.message_id)
        finally:
            _game_lock_release(cb.from_user.id)
    except Exception as exc:
        log_exception("cb_game_repeat", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 6
# =============================================================================

log.info("ЧАСТЬ 6: игры на кубиках готовы")

# =============================================================================
#  ЧАСТЬ 7 / 10: МИНЫ, ДУЭЛИ, ПОДАРКИ, ПЕРЕВОДЫ
#    - Router: extra_games_router
#    - Мины: мины <ставка>, поле 5x5, 3 мины, множитель 1+0.15*open
#    - Дуэли: дуэль @user <ставка>, accept/decline, кубики, 5% комиссия
#    - Подарки: подарок @user <сумма>
#    - Переводы: перевод @user <сумма>
#    - Команда отмены активной партии мин
# =============================================================================

extra_games_router: Router = Router(name="extra_games")


# =============================================================================
#  МИНЫ
# =============================================================================
# Состояние сессии хранится в RUNTIME_FLAGS["mines"][game_id] = dict:
#   user_id, chat_id, bet, opened set, mines set, message_id, active
# game_id — короткий uuid (8 символов) для callback_data.
# ВАЖНО: списание ставки происходит при старте партии, возврат — при
# cashout или при проигрыше (нет, при проигрыше не возвращается — это игра).
# =============================================================================

MINES_STORE: dict[str, dict[str, Any]] = {}


def _mines_multiplier(opened_count: int) -> float:
    """Множитель для текущей сессии: 1.0 + 0.15 * открытых."""
    return 1.0 + opened_count * MINES_STEP_MULT


def _mines_prize(bet: int, opened_count: int, vip_active: bool) -> int:
    """Выигрыш с учётом VIP-бонуса."""
    base = int(bet * _mines_multiplier(opened_count))
    if vip_active and base > bet:
        base += int(base * VIP_WIN_BONUS)
    return max(0, base)


def _mines_new_game_id() -> str:
    """8-символьный id. Без '-' — безопасно для callback_data."""
    return uuid.uuid4().hex[:8]


def _mines_generate_field() -> set[int]:
    """Генерирует 3 уникальные позиции мин из 25 клеток."""
    return set(random.sample(range(MINES_FIELD_SIZE * MINES_FIELD_SIZE), MINES_COUNT))


def _mines_render_field(game_id: str, opened: set[int], lost: bool = False) -> InlineKeyboardMarkup:
    """Строит клавиатуру поля."""
    return mines_kb(game_id, opened, lost=lost)


async def cmd_mines(msg: Message) -> None:
    """
    «мины 1000» — стартует партию.
    Проверки: бан, группа/игры, ставка, антиспам.
    """
    u = msg.from_user
    if u is None:
        return
    try:
        if await is_banned(u.id):
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return
        if is_group_chat(msg.chat) and not await chat_games_enabled(msg.chat.id):
            await safe_send(msg.chat.id, TEXT_ERR_GAMES_DISABLED)
            return

        cfg = DICE_GAMES["кости"]  # для min/max ставки
        bet = await _parse_bet(msg, cfg)
        if bet is None:
            return

        # Антиспам.
        ok_mem, remain_mem = _dice_cooldown_memory(u.id)
        if not ok_mem:
            await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_mem))
            return
        ok_db, remain_db = await check_game_cooldown(u.id)
        if not ok_db:
            await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_db))
            return

        if not _game_lock_acquire(u.id, "мины"):
            await safe_send(msg.chat.id, "⏳ У тебя уже активна партия.")
            return

        try:
            ok = await try_withdraw(u.id, bet, username=u.username)
            if not ok:
                await safe_send(msg.chat.id, TEXT_ERR_NOT_ENOUGH)
                return

            _mark_dice_cooldown(u.id)

            game_id = _mines_new_game_id()
            opened: set[int] = set()
            mines = _mines_generate_field()

            sent = await safe_send(
                msg.chat.id,
                f"💣 <b>МИНЫ</b>\n\n"
                f"👤 {mention_html(u.id, humanize_username(u))}\n"
                f"💰 Ставка: <b>{format_money(bet)}</b> TOKENS\n"
                f"🌐 Поле 5×5, мин: <b>{MINES_COUNT}</b>\n\n"
                f"Открывай клетки. Каждая клетка +{int(MINES_STEP_MULT*100)}%. "
                f"Наткнёшься на мину — потеряешь ставку.\n"
                f"Нажми «💰 Забрать», чтобы зафиксировать выигрыш.",
                markup=_mines_render_field(game_id, opened, lost=False),
            )
            if sent is None:
                # Не удалось отправить — возвращаем ставку.
                await add_balance(u.id, bet, ensure=False)
                _game_lock_release(u.id)
                return

            MINES_STORE[game_id] = {
                "user_id": u.id,
                "chat_id": msg.chat.id,
                "bet": bet,
                "opened": opened,
                "mines": mines,
                "message_id": sent.message_id,
                "active": True,
                "started_at": time.monotonic(),
            }
        except Exception:
            _game_lock_release(u.id)
            raise
    except Exception as exc:
        log_exception("cmd_mines", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@extra_games_router.callback_query(F.data.startswith("mines:open:"))
async def cb_mines_open(cb: CallbackQuery) -> None:
    """Открытие клетки. mines:open:<game_id>:<idx>"""
    try:
        if not cb.data or not cb.from_user:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 4:
            await safe_answer(cb)
            return
        _, _, game_id, idx_raw = parts[0], parts[1], parts[2], parts[3]
        game = MINES_STORE.get(game_id)
        if game is None or not game.get("active"):
            await safe_answer(cb, "❌ Партия завершена.", show_alert=True)
            return
        if int(cb.from_user.id) != int(game["user_id"]):
            await safe_answer(cb, "❌ Это не твоя партия.", show_alert=True)
            return
        idx = parse_int(idx_raw)
        if idx is None or idx < 0 or idx >= MINES_FIELD_SIZE * MINES_FIELD_SIZE:
            await safe_answer(cb, "❌ Неверная клетка", show_alert=True)
            return
        opened: set[int] = game["opened"]
        mines: set[int] = game["mines"]
        if idx in opened:
            await safe_answer(cb, "Уже открыта", show_alert=False)
            return

        # Открыли мину — проигрыш.
        if idx in mines:
            game["active"] = False
            await log_game(game["user_id"], "мины", game["bet"], 0, f"mine={idx}")
            _game_lock_release(game["user_id"])
            opened.add(idx)
            lost_kb = _mines_render_field(game_id, opened, lost=True)
            # Показать все мины.
            lost_text = (
                f"💥 <b>МИНА!</b>\n\n"
                f"👤 {mention_html(cb.from_user.id, humanize_username(cb.from_user))}\n"
                f"💰 Ставка: <b>{format_money(game['bet'])}</b> TOKENS\n"
                f"📉 Проигрыш: <b>-{format_money(game['bet'])}</b>\n\n"
                f"Повезёт в следующий раз!"
            )
            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    lost_text, lost_kb,
                )
            await safe_answer(cb, "💥 Мина!", show_alert=False)
            MINES_STORE.pop(game_id, None)
            return

        opened.add(idx)
        await safe_answer(cb, "✅ Чисто!", show_alert=False)

        # Обновить клавиатуру.
        current_prize = _mines_prize(game["bet"], len(opened), await is_vip(game["user_id"]))
        if cb.message:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                f"💣 <b>МИНЫ</b>\n\n"
                f"👤 {mention_html(cb.from_user.id, humanize_username(cb.from_user))}\n"
                f"💰 Ставка: <b>{format_money(game['bet'])}</b> TOKENS\n"
                f"✅ Открыто: <b>{len(opened)}</b> | "
                f"💵 Текущий выигрыш: <b>{format_money(current_prize)}</b>\n\n"
                f"Открывай дальше или нажми «💰 Забрать».",
                _mines_render_field(game_id, opened, lost=False),
            )

        # Если открыли все безопасные клетки — авто-cashout.
        safe_cells = MINES_FIELD_SIZE * MINES_FIELD_SIZE - MINES_COUNT
        if len(opened) >= safe_cells:
            # Автоматически забираем.
            await _mines_cashout(game_id, cb.from_user)
    except Exception as exc:
        log_exception("cb_mines_open", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


@extra_games_router.callback_query(F.data.startswith("mines:cashout:"))
async def cb_mines_cashout(cb: CallbackQuery) -> None:
    """Забрать текущий выигрыш. mines:cashout:<game_id>"""
    try:
        if not cb.data or not cb.from_user:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 3:
            await safe_answer(cb)
            return
        game_id = parts[2]
        game = MINES_STORE.get(game_id)
        if game is None or not game.get("active"):
            await safe_answer(cb, "❌ Партия завершена.", show_alert=True)
            return
        if int(cb.from_user.id) != int(game["user_id"]):
            await safe_answer(cb, "❌ Это не твоя партия.", show_alert=True)
            return
        if not game["opened"]:
            await safe_answer(cb, "Открой хотя бы одну клетку.", show_alert=True)
            return
        await _mines_cashout(game_id, cb.from_user)
        await safe_answer(cb, "💰 Забрано!", show_alert=False)
    except Exception as exc:
        log_exception("cb_mines_cashout", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


async def _mines_cashout(game_id: str, tg_user: TgUser) -> None:
    """Внутренняя логика cashout — начисление и завершение партии."""
    game = MINES_STORE.get(game_id)
    if game is None or not game.get("active"):
        return
    game["active"] = False
    bet = int(game["bet"])
    opened_count = len(game["opened"])
    vip_active = await is_vip(int(game["user_id"]))
    prize = _mines_prize(bet, opened_count, vip_active)
    if prize > 0:
        await add_balance(int(game["user_id"]), prize, ensure=False)
    await log_game(
        int(game["user_id"]), "мины", bet, prize,
        f"cashout open={opened_count} mult={_mines_multiplier(opened_count):.2f}",
    )
    _game_lock_release(int(game["user_id"]))

    # Обновить сообщение.
    chat_id = int(game["chat_id"])
    message_id = int(game["message_id"])
    delta = prize - bet
    sign = "📈" if delta > 0 else ("📉" if delta < 0 else "➖")
    vip_str = " ⭐VIP +5%" if vip_active and prize > bet else ""
    text = (
        f"💰 <b>Забрано!</b>\n\n"
        f"👤 {mention_html(int(game['user_id']), humanize_username(tg_user))}\n"
        f"✅ Открыто клеток: <b>{opened_count}</b>\n"
        f"📊 Множитель: <b>x{_mines_multiplier(opened_count):.2f}</b>\n"
        f"💰 Ставка: <b>{format_money(bet)}</b>\n"
        f"{sign} Выигрыш: <b>{format_money(prize)}</b> TOKENS"
        f" ({'+' if delta >= 0 else ''}{format_money(delta)}){vip_str}"
    )
    await safe_edit(chat_id, message_id, text, back_inline_kb("nav_menu"))
    MINES_STORE.pop(game_id, None)


@extra_games_router.message(Command("отмена_мин", "отменамин"))
async def cmd_mines_cancel(msg: Message) -> None:
    """Отменяет активную партию мин (возврат ставки)."""
    u = msg.from_user
    if u is None:
        return
    try:
        gid = None
        for g_id, g in MINES_STORE.items():
            if int(g["user_id"]) == int(u.id) and g.get("active"):
                gid = g_id
                break
        if gid is None:
            await safe_send(msg.chat.id, "❌ Активной партии нет.")
            return
        g = MINES_STORE[gid]
        g["active"] = False
        await add_balance(u.id, int(g["bet"]), ensure=False)
        _game_lock_release(u.id)
        MINES_STORE.pop(gid, None)
        await safe_send(msg.chat.id, "❌ Партия отменена, ставка возвращена.")
    except Exception as exc:
        log_exception("cmd_mines_cancel", exc)


# =============================================================================
#  ДУЭЛИ
# =============================================================================
# «дуэль @username 1000» — создаёт вызов. Оба участника должны быть
# зарегистрированы. Ставка списывается у создателя СРАЗУ, у соперника —
# при accept. Победитель забирает банк минус 5% комиссии.
# Данные дуэли: ACTIVE_DUELS[duel_id] = {...}
# =============================================================================

DUEL_TIMEOUT_SEC: int = 120


def _duel_new_id() -> str:
    return uuid.uuid4().hex[:10]


async def _find_user_by_username(username: str) -> Optional[UserRow]:
    """Ищет юзера по @username в БД."""
    uname = (username or "").lstrip("@").strip()
    if not uname:
        return None
    row = await fetchone(
        "SELECT user_id, username, balance, vip, games, wins, achievements, "
        "referrer_id, created_at, xp, level, banned "
        "FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
        (uname,),
    )
    return _row_to_user(row)


@extra_games_router.message(Command("дуэль", "duel"))
async def cmd_duel(msg: Message) -> None:
    """
    Формат: дуэль @username <ставка>
    """
    u = msg.from_user
    if u is None:
        return
    try:
        if await is_banned(u.id):
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return
        if is_group_chat(msg.chat) and not await chat_games_enabled(msg.chat.id):
            await safe_send(msg.chat.id, TEXT_ERR_GAMES_DISABLED)
            return

        parts = split_command_args(msg.text or "")
        if len(parts) < 3:
            await safe_send(
                msg.chat.id,
                "❌ Формат: <code>дуэль @username 1000</code>",
            )
            return
        target_raw = parts[1]
        bet_raw = parts[2]
        if not target_raw.startswith("@"):
            await safe_send(msg.chat.id, "❌ Укажи @username соперника.")
            return
        target = await _find_user_by_username(target_raw)
        if target is None:
            await safe_send(msg.chat.id, "❌ Соперник не найден. Пусть он напишет /start боту.")
            return
        if int(target.user_id) == int(u.id):
            await safe_send(msg.chat.id, "❌ Нельзя дуэлиться с собой.")
            return
        if target.banned:
            await safe_send(msg.chat.id, "❌ Соперник забанен.")
            return

        bet = parse_positive_int(bet_raw)
        if bet is None or bet < ROULETTE_MIN_BET or bet > ROULETTE_MAX_BET:
            await safe_send(
                msg.chat.id,
                f"❌ Ставка от {format_money(ROULETTE_MIN_BET)} до {format_money(ROULETTE_MAX_BET)}.",
            )
            return

        # Антиспам.
        ok_db, remain_db = await check_game_cooldown(u.id)
        if not ok_db:
            await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_db))
            return

        # Атомарное списание у инициатора.
        ok = await try_withdraw(u.id, bet, username=u.username)
        if not ok:
            await safe_send(msg.chat.id, TEXT_ERR_NOT_ENOUGH)
            return

        duel_id = _duel_new_id()
        ACTIVE_DUELS[duel_id] = {
            "creator_id": u.id,
            "creator_name": humanize_username(u),
            "opponent_id": int(target.user_id),
            "opponent_name": humanize_username(None) if not target.username else f"@{target.username}",
            "bet": bet,
            "chat_id": msg.chat.id,
            "created_at": time.monotonic(),
            "status": "pending",
        }

        await safe_send(
            msg.chat.id,
            f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ</b>\n\n"
            f"👤 Инициатор: {mention_html(u.id, humanize_username(u))}\n"
            f"👤 Соперник: {mention_html(int(target.user_id), target.username or f'id{target.user_id}')}\n"
            f"💰 Ставка: <b>{format_money(bet)}</b> TOKENS\n"
            f"🏦 Банк: <b>{format_money(bet * 2)}</b> TOKENS (минус {int(DUEL_COMMISSION*100)}%)\n\n"
            f"У соперника <b>{DUEL_TIMEOUT_SEC} сек</b>, чтобы принять.",
            markup=duel_kb(duel_id),
        )

        # Таймер: если не приняли — вернуть ставку.
        asyncio.create_task(_duel_timeout(duel_id))
    except Exception as exc:
        log_exception("cmd_duel", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


async def _duel_timeout(duel_id: str) -> None:
    """По истечении таймаута отменяет дуэль и возвращает ставку создателю."""
    await asyncio.sleep(DUEL_TIMEOUT_SEC)
    duel = ACTIVE_DUELS.get(duel_id)
    if duel is None or duel.get("status") != "pending":
        return
    duel["status"] = "timeout"
    ACTIVE_DUELS.pop(duel_id, None)
    try:
        await add_balance(int(duel["creator_id"]), int(duel["bet"]), ensure=False)
        await safe_send(
            int(duel["chat_id"]),
            f"⌛ Дуэль отменена (нет ответа). "
            f"Ставка <b>{format_money(duel['bet'])}</b> возвращена "
            f"{mention_html(int(duel['creator_id']), duel['creator_name'])}.",
        )
    except Exception as exc:
        log_exception("_duel_timeout", exc)


@extra_games_router.callback_query(F.data.startswith("duel:"))
async def cb_duel(cb: CallbackQuery) -> None:
    """Обработка accept/decline. duel:<action>:<duel_id>"""
    try:
        if not cb.data or not cb.from_user:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 3:
            await safe_answer(cb)
            return
        _, action, duel_id = parts[0], parts[1], parts[2]
        duel = ACTIVE_DUELS.get(duel_id)
        if duel is None or duel.get("status") != "pending":
            await safe_answer(cb, "❌ Дуэль недоступна.", show_alert=True)
            return

        if action == "decline":
            if int(cb.from_user.id) != int(duel["opponent_id"]):
                await safe_answer(cb, "❌ Только соперник может отклонить.", show_alert=True)
                return
            duel["status"] = "declined"
            ACTIVE_DUELS.pop(duel_id, None)
            await add_balance(int(duel["creator_id"]), int(duel["bet"]), ensure=False)
            await safe_answer(cb, "❌ Дуэль отклонена.", show_alert=False)
            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    f"❌ Дуэль отклонена.\nСтавка <b>{format_money(duel['bet'])}</b> "
                    f"возвращена {mention_html(int(duel['creator_id']), duel['creator_name'])}.",
                    back_inline_kb("nav_menu"),
                )
            return

        if action == "accept":
            if int(cb.from_user.id) != int(duel["opponent_id"]):
                await safe_answer(cb, "❌ Только соперник может принять.", show_alert=True)
                return

            # Списываем ставку у соперника.
            ok = await try_withdraw(
                int(cb.from_user.id), int(duel["bet"]),
                username=cb.from_user.username,
            )
            if not ok:
                await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
                return

            # Меняем статус, чтобы повторный accept не сработал.
            duel["status"] = "playing"
            await safe_answer(cb, "🎲 Дуэль началась!", show_alert=False)

            if cb.message is None:
                return
            chat_id = cb.message.chat.id

            # Бросаем кубики обоим.
            try:
                c_msg = await _roll_dice(chat_id, "🎲")
                o_msg = await _roll_dice(chat_id, "🎲")
            except Exception as exc:
                log_exception("cb_duel:roll", exc)
                c_msg = o_msg = None

            await asyncio.sleep(1.5)

            def _face(m: Optional[Message]) -> int:
                try:
                    if m and m.dice:
                        return int(m.dice.value)
                except Exception:
                    pass
                return 0

            c_face = _face(c_msg)
            o_face = _face(o_msg)

            bet = int(duel["bet"])
            bank = bet * 2
            commission = int(bank * DUEL_COMMISSION)
            prize = bank - commission

            creator_id = int(duel["creator_id"])
            opponent_id = int(cb.from_user.id)
            creator_vip = await is_vip(creator_id)
            opponent_vip = await is_vip(opponent_id)

            if c_face > o_face:
                winner_id = creator_id
                winner_name = duel["creator_name"]
                winner_vip = creator_vip
                loser_id = opponent_id
            elif o_face > c_face:
                winner_id = opponent_id
                winner_name = humanize_username(cb.from_user)
                winner_vip = opponent_vip
                loser_id = creator_id
            else:
                # Ничья — возврат ставок обоим.
                await add_balance(creator_id, bet, ensure=False)
                await add_balance(opponent_id, bet, ensure=False)
                await log_game(creator_id, "дуэль", bet, bet, f"draw {c_face}-{o_face}")
                await log_game(opponent_id, "дуэль", bet, bet, f"draw {c_face}-{o_face}")
                ACTIVE_DUELS.pop(duel_id, None)
                _game_lock_release(creator_id)
                _game_lock_release(opponent_id)
                if cb.message:
                    await safe_edit(
                        cb.message.chat.id, cb.message.message_id,
                        f"⚔️ <b>ДУЭЛЬ — НИЧЬЯ</b>\n\n"
                        f"🎲 {mention_html(creator_id, duel['creator_name'])}: {c_face}\n"
                        f"🎲 {mention_html(opponent_id, humanize_username(cb.from_user))}: {o_face}\n\n"
                        f"💰 Ставки возвращены обоим.",
                        back_inline_kb("nav_menu"),
                    )
                return

            # VIP-бонус применяется к призу (сверх комиссии).
            if winner_vip:
                prize += int(prize * VIP_WIN_BONUS)

            await add_balance(winner_id, prize, ensure=False)
            await log_game(winner_id, "дуэль", bet, prize, f"win {c_face}-{o_face}")
            await log_game(loser_id, "дуэль", bet, 0, f"lose {c_face}-{o_face}")

            ACTIVE_DUELS.pop(duel_id, None)
            _game_lock_release(creator_id)
            _game_lock_release(opponent_id)

            # Ачивка «Дуэлянт» — 10 выигранных дуэлей.
            try:
                wins = int(await fetchval(
                    "SELECT COUNT(*) FROM games_log WHERE user_id = ? AND game = 'дуэль' AND win > bet",
                    (winner_id,), 0,
                ))
                if wins >= 10:
                    if await grant_achievement(winner_id, "duelist"):
                        await safe_send(
                            winner_id,
                            "🏅 Достижение: <b>⚔️ Дуэлянт</b> (10 выигранных дуэлей)!",
                        )
            except Exception as exc:
                log_exception("cb_duel:achievement", exc)

            if cb.message:
                await safe_edit(
                    cb.message.chat.id, cb.message.message_id,
                    f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА</b>\n\n"
                    f"🎲 {mention_html(creator_id, duel['creator_name'])}: <b>{c_face}</b>\n"
                    f"🎲 {mention_html(opponent_id, humanize_username(cb.from_user))}: <b>{o_face}</b>\n\n"
                    f"🏆 Победитель: {mention_html(winner_id, winner_name)}\n"
                    f"💰 Приз: <b>{format_money(prize)}</b> TOKENS\n"
                    f"💼 Комиссия: {format_money(commission)} (5%)",
                    back_inline_kb("nav_menu"),
                )
            return

        await safe_answer(cb)
    except Exception as exc:
        log_exception("cb_duel", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


# =============================================================================
#  ПЕРЕВОДЫ И ПОДАРКИ
# =============================================================================
# «перевод @user 1000» — перевод между игроками (без комиссии).
# «подарок @user 1000» — то же самое, но с праздничным сообщением.
# =============================================================================

async def _transfer_common(msg: Message, is_gift: bool) -> None:
    u = msg.from_user
    if u is None:
        return
    try:
        if await is_banned(u.id):
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return
        parts = split_command_args(msg.text or "")
        if len(parts) < 3:
            await safe_send(
                msg.chat.id,
                f"❌ Формат: <code>{'подарок' if is_gift else 'перевод'} @username 1000</code>",
            )
            return
        target_raw, amount_raw = parts[1], parts[2]
        if not target_raw.startswith("@"):
            await safe_send(msg.chat.id, "❌ Укажи @username получателя.")
            return
        target = await _find_user_by_username(target_raw)
        if target is None:
            await safe_send(msg.chat.id, "❌ Получатель не найден. Пусть он напишет /start.")
            return
        if int(target.user_id) == int(u.id):
            await safe_send(msg.chat.id, "❌ Нельзя переводить самому себе.")
            return
        amount = parse_positive_int(amount_raw)
        if amount is None or amount <= 0:
            await safe_send(msg.chat.id, "❌ Неверная сумма.")
            return

        ok, reason = await transfer_balance(u.id, int(target.user_id), amount, commission=0.0)
        if not ok:
            await safe_send(msg.chat.id, f"❌ {reason}")
            return

        verb = "🎁 Подарок" if is_gift else "💸 Перевод"
        await safe_send(
            msg.chat.id,
            f"{verb} отправлен!\n\n"
            f"👤 От: {mention_html(u.id, humanize_username(u))}\n"
            f"👤 Кому: {mention_html(int(target.user_id), target.username or f'id{target.user_id}')}\n"
            f"💰 Сумма: <b>{format_money(amount)}</b> TOKENS",
        )
        # Уведомляем получателя в ЛС.
        await safe_send(
            int(target.user_id),
            f"{verb}!\n\n"
            f"👤 От: {mention_html(u.id, humanize_username(u))}\n"
            f"💰 Сумма: <b>+{format_money(amount)}</b> TOKENS",
        )
    except Exception as exc:
        log_exception(f"_transfer_common(gift={is_gift})", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


@extra_games_router.message(Command("перевод", "transfer", "pay"))
async def cmd_transfer(msg: Message) -> None:
    await _transfer_common(msg, is_gift=False)


@extra_games_router.message(Command("подарок", "gift"))
async def cmd_gift(msg: Message) -> None:
    await _transfer_common(msg, is_gift=True)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 7
# =============================================================================

log.info("ЧАСТЬ 7: мины, дуэли, подарки и переводы готовы")

# =============================================================================
#  ЧАСТЬ 8 / 10: РУЛЕТКА
#    - Router: roulette_router
#    - Запуск: «старт <ставка>» игроком
#    - Парсер: к 1000 | ч 500 | 1000 чет | 1000 нечет | 0 100 |
#              1000 1 2 3 | 500 10-20
#    - Множители: цвет/чёт x2, диапазон x3, число x36
#    - Вывод списка ставок, гифка, пауза 3 сек, результат
#    - Кнопки «Повторить»/«Удвоить» (callback: roulette:repeat/double:<gid>)
#    - Логирование в roulette_logs
#    - Защита от double-spend, race condition, спама
# =============================================================================
# АРХИТЕКТУРА СЕССИИ:
#   ROULETTE_SESSIONS[chat_id] = {
#       "game_id": str,
#       "initiator_id": int,
#       "bet": int (базовая ставка, для repeat/double),
#       "bets": list[RouletteBet],
#       "state": "collecting" | "spinning" | "finished",
#       "message_id": int,
#       "created_at": float,
#       "timer_task": Task
#   }
#
# Жизненный цикл:
#   1. «старт 1000» — создаёт сессию. Ставка инициатора = базовая.
#      Сессия открыта 15 сек для сбора ставок других игроков.
#   2. Игроки пишут «к 500», «1000 5» и т.п. — парсится, списывается,
#      добавляется в bets, сообщение сессии обновляется.
#   3. Через 15 сек — «spinning»: гифка, пауза 3 сек, результат.
#   4. Каждый победитель получает win по множителю; лог в roulette_logs.
#   5. Кнопки «Повторить»/«Удвоить» открывают новую сессию с теми же
#      (или удвоенными) ставками — только для инициатора.
# =============================================================================

roulette_router: Router = Router(name="roulette")

ROULETTE_COLLECT_SEC: int = 15          # окно сбора ставок
ROULETTE_RED_NUMBERS: set[int] = {      # европейская рулетка
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36
}
# Чёрные — остальные 1..36. 0 — зелёный, не красное и не чёрное.


# =============================================================================
#  ПАРСЕР СТАВОК
# =============================================================================
# Возвращает (RouletteBet | None, reason).
# reason == 'ok' | 'bad' | 'bad_amount' | 'bad_value'
# =============================================================================

_RANGE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_NUMBER_ONLY_RE = re.compile(r"^\d{1,2}$")
_COLOR_WORDS = {
    "к": "red", "кр": "red", "красн": "red", "красное": "red", "red": "red",
    "ч": "black", "чёрн": "black", "черн": "black", "чёрное": "black",
    "черное": "black", "black": "black",
}
_PARITY_WORDS = {
    "чет": "even", "чёт": "even", "чётн": "even", "чётное": "even", "even": "even",
    "нечет": "odd", "нечёт": "odd", "нечётн": "odd", "нечётное": "odd", "odd": "odd",
}


def _parse_roulette_bet(text: str, user_id: int) -> tuple[Optional[RouletteBet], str]:
    """
    Разбирает строку ставки. Поддерживаемые форматы:
      «к 1000» / «ч 500»         — цвет
      «1000 чет» / «1000 нечет»  — чётность
      «0 100» / «100 7»          — точное число 0..36
      «1000 1 2 3»               — мультичисла (одна ставка на каждое)
      «500 10-20»                — диапазон
      «к 500»                    — цвет
    ВАЖНО: парсер возвращает ОДНУ ставку (RouletteBet) — но мультичисла
    и диапазон кодируются внутри как список значений в RouletteBet.value.
    """
    if not text:
        return None, "bad"
    raw = text.strip()
    # Нормализуем: убираем лишние пробелы.
    tokens = [t for t in re.split(r"\s+", raw) if t]
    if len(tokens) < 2:
        return None, "bad"

    # Случай 1: цвет в начале («к 1000»).
    if tokens[0].lower() in _COLOR_WORDS:
        amount = parse_positive_int(tokens[1])
        if amount is None:
            return None, "bad_amount"
        color = _COLOR_WORDS[tokens[0].lower()]
        return RouletteBet(
            user_id=user_id, bet_type="color", value=color,
            amount=amount, raw=raw,
        ), "ok"

    # Случай 2: чётность в конце («1000 чет»).
    if tokens[-1].lower() in _PARITY_WORDS:
        amount = parse_positive_int(tokens[0])
        if amount is None:
            return None, "bad_amount"
        parity = _PARITY_WORDS[tokens[-1].lower()]
        return RouletteBet(
            user_id=user_id, bet_type="parity", value=parity,
            amount=amount, raw=raw,
        ), "ok"

    # Случай 3: диапазон («500 10-20»).
    for tok in tokens[1:]:
        m = _RANGE_RE.match(tok)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if not (0 <= lo < hi <= ROULETTE_MAX_NUM):
                return None, "bad_value"
            amount = parse_positive_int(tokens[0])
            if amount is None:
                return None, "bad_amount"
            return RouletteBet(
                user_id=user_id, bet_type="range", value=(lo, hi),
                amount=amount, raw=raw,
            ), "ok"

    # Случай 4: точное число или мультичисла.
    # tokens[0] — сумма, tokens[1:] — числа 0..36.
    amount = parse_positive_int(tokens[0])
    if amount is None:
        return None, "bad_amount"
    numbers: list[int] = []
    for tok in tokens[1:]:
        if not _NUMBER_ONLY_RE.match(tok):
            return None, "bad_value"
        n = int(tok)
        if not (0 <= n <= ROULETTE_MAX_NUM):
            return None, "bad_value"
        numbers.append(n)
    if not numbers:
        return None, "bad"
    if len(numbers) == 1:
        return RouletteBet(
            user_id=user_id, bet_type="number", value=numbers[0],
            amount=amount, raw=raw,
        ), "ok"
    # Несколько чисел — единая ставка, но value — список.
    return RouletteBet(
        user_id=user_id, bet_type="numbers", value=numbers,
        amount=amount, raw=raw,
    ), "ok"


def _roulette_check_win(bet: RouletteBet, result: int) -> int:
    """
    Возвращает сумму выигрыша (0 — проигрыш).
    Ставка списывается в момент добавления, поэтому возвращаем ПОЛНУЮ
    сумму, включая возврат ставки (если ставка на число/цвет/чёт, и выиграл,
    возвращаем amount * multiplier; иначе 0).
    """
    mult = 0
    if bet.bet_type == "color":
        if result != 0:
            is_red = result in ROULETTE_RED_NUMBERS
            if bet.value == "red" and is_red:
                mult = ROULETTE_MULT_COLOR
            elif bet.value == "black" and not is_red:
                mult = ROULETTE_MULT_COLOR
    elif bet.bet_type == "parity":
        if result != 0:
            is_even = (result % 2 == 0)
            if bet.value == "even" and is_even:
                mult = ROULETTE_MULT_PARITY
            elif bet.value == "odd" and not is_even:
                mult = ROULETTE_MULT_PARITY
    elif bet.bet_type == "range":
        lo, hi = bet.value
        if lo <= result <= hi:
            mult = ROULETTE_MULT_RANGE
    elif bet.bet_type == "number":
        if result == int(bet.value):
            mult = ROULETTE_MULT_EXACT
    elif bet.bet_type == "numbers":
        if result in bet.value:
            mult = ROULETTE_MULT_EXACT
    return int(bet.amount * mult) if mult > 0 else 0


def _roulette_result_color(result: int) -> str:
    if result == 0:
        return "🟢"
    return "🔴" if result in ROULETTE_RED_NUMBERS else "⚫"


def _roulette_render_bets(bets: list[RouletteBet], initiator_id: int) -> str:
    """Формирует список текущих ставок для сообщения сессии."""
    if not bets:
        return "<i>Пока нет ставок. Напиши свою: «к 1000» / «1000 7» / «500 10-20».</i>"
    lines = []
    for b in bets:
        if b.bet_type == "color":
            label = "🔴 красное" if b.value == "red" else "⚫ чёрное"
        elif b.bet_type == "parity":
            label = "🔢 чёт" if b.value == "even" else "🔢 нечёт"
        elif b.bet_type == "range":
            lo, hi = b.value
            label = f"📏 {lo}-{hi}"
        elif b.bet_type == "number":
            label = f"🎯 число {b.value}"
        elif b.bet_type == "numbers":
            label = f"🎯 числа {', '.join(str(n) for n in b.value)}"
        else:
            label = "—"
        star = " ⭐" if int(b.user_id) == int(initiator_id) else ""
        lines.append(f"• <code>{int(b.user_id)}</code>{star} — {label} · "
                     f"<b>{format_money(b.amount)}</b>")
    return "\n".join(lines)


def _roulette_render_session(session: dict[str, Any]) -> str:
    bets: list[RouletteBet] = session["bets"]
    total_bet = sum(b.amount for b in bets)
    initiator_id = int(session["initiator_id"])
    state = session["state"]
    if state == "collecting":
        header = (
            "🎡 <b>РУЛЕТКА — приём ставок</b>\n\n"
            f"👤 Инициатор: <code>{initiator_id}</code>\n"
            f"⏳ Окно сбора: <b>{ROULETTE_COLLECT_SEC} сек</b>\n"
            f"💰 Всего в банке: <b>{format_money(total_bet)}</b> TOKENS\n\n"
            "📋 <b>Ставки:</b>\n"
        )
    elif state == "spinning":
        header = "🎡 <b>РУЛЕТКА — крутится...</b>\n\n"
    else:
        header = "🎡 <b>РУЛЕТКА — итог</b>\n\n"
    return header + _roulette_render_bets(bets, initiator_id)


# =============================================================================
#  СОЗДАНИЕ СЕССИИ
# =============================================================================

def _roulette_get_session(chat_id: int) -> Optional[dict[str, Any]]:
    return ROULETTE_SESSIONS.get(int(chat_id))


def _roulette_new_session(
    chat_id: int, initiator_id: int, base_bet: int,
) -> dict[str, Any]:
    sid = uuid.uuid4().hex[:10]
    session = {
        "game_id": sid,
        "initiator_id": int(initiator_id),
        "base_bet": int(base_bet),
        "bets": [],
        "state": "collecting",
        "message_id": 0,
        "created_at": time.monotonic(),
        "timer_task": None,
    }
    ROULETTE_SESSIONS[int(chat_id)] = session
    return session


def _roulette_cancel_timer(session: Optional[dict[str, Any]]) -> None:
    if not session:
        return
    task = session.get("timer_task")
    if task and not task.done():
        try:
            task.cancel()
        except Exception:
            pass


# =============================================================================
#  КОМАНДА «СТАРТ»
# =============================================================================

@roulette_router.message(Command("старт", "start_roulette", "рулетка"))
async def cmd_roulette_start(msg: Message) -> None:
    """
    «старт 1000» — открывает сессию рулетки в чате.
    Инициатор сразу ставит base_bet на... ничего? Нет: по ТЗ «старт» —
    это открытие сессии, базовая ставка инициатора учитывается при
    повтор/удвоить. В самом списке ставок инициатора появится только когда
    он напишет «к 1000» и т.п.
    Однако ТЗ говорит: «Запускается ТОЛЬКО командой старт игроком со ставкой».
    Значит «старт 1000» — это открытие сессии + регистрация первой ставки
    инициатора как «просто сумма» (без типа) — она не участвует в расчёте.
    Практичнее: «старт 1000» открывает окно, а ставку инициатор всё равно
    должен сделать явно. base_bet запоминается для повтор/удвоить.
    """
    u = msg.from_user
    if u is None:
        return
    try:
        if await is_banned(u.id):
            await safe_send(msg.chat.id, TEXT_ERR_BANNED)
            return
        if is_group_chat(msg.chat) and not await chat_games_enabled(msg.chat.id):
            await safe_send(msg.chat.id, TEXT_ERR_GAMES_DISABLED)
            return

        parts = split_command_args(msg.text or "")
        if len(parts) < 2:
            await safe_send(
                msg.chat.id,
                "❌ Формат: <code>старт 1000</code>",
            )
            return
        base_bet = parse_positive_int(parts[1])
        if base_bet is None or base_bet < ROULETTE_MIN_BET:
            await safe_send(
                msg.chat.id,
                f"❌ Минимальная ставка: {format_money(ROULETTE_MIN_BET)}.",
            )
            return
        if base_bet > ROULETTE_MAX_BET:
            await safe_send(
                msg.chat.id,
                f"❌ Максимальная ставка: {format_money(ROULETTE_MAX_BET)}.",
            )
            return

        # Антиспам.
        ok_db, remain_db = await check_game_cooldown(u.id)
        if not ok_db:
            await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_db))
            return

        existing = _roulette_get_session(msg.chat.id)
        if existing and existing["state"] in ("collecting", "spinning"):
            await safe_send(msg.chat.id, "⏳ В этом чате уже идёт рулетка.")
            return

        # Убедимся, что у инициатора хватает баланса на base_bet хотя бы для
        # первой ставки — иначе бессмысленно.
        bal = await get_balance(u.id)
        if bal < base_bet and u.id not in GOD_MODE_USERS:
            await safe_send(msg.chat.id, TEXT_ERR_NOT_ENOUGH)
            return

        # Создаём сессию.
        session = _roulette_new_session(msg.chat.id, u.id, base_bet)
        text = _roulette_render_session(session)
        sent = await safe_send(
            msg.chat.id, text,
            markup=close_kb(),
        )
        if sent is None:
            ROULETTE_SESSIONS.pop(msg.chat.id, None)
            await safe_send(msg.chat.id, TEXT_ERR_GENERIC)
            return
        session["message_id"] = sent.message_id

        # Таймер сбора ставок.
        session["timer_task"] = asyncio.create_task(
            _roulette_spin_after(chat_id=msg.chat.id, game_id=session["game_id"])
        )
    except Exception as exc:
        log_exception("cmd_roulette_start", exc)
        await safe_send(msg.chat.id, TEXT_ERR_GENERIC)


# =============================================================================
#  ПАРСИНГ СТАВОК ИЗ СООБЩЕНИЙ ЧАТА
# =============================================================================
# Хендлер ловит сообщения, которые выглядят как ставки рулетки, но только
# когда в чате активна сессия в состоянии "collecting".
# =============================================================================

@roulette_router.message(F.text.regexp(r"^[\wа-яё0-9\-]+(\s+[\wа-яё0-9\-]+){0,4}$"))
async def on_roulette_message(msg: Message) -> None:
    """
    Обработчик «просто текста» — срабатывает, только если в этом чате
    есть активная сессия рулетки в фазе сбора.
    Сюда не должны попадать команды (они обрабатываются раньше через Command()).
    """
    try:
        chat_id = msg.chat.id
        session = _roulette_get_session(chat_id)
        if session is None or session["state"] != "collecting":
            return
        if msg.from_user is None:
            return
        if await is_banned(msg.from_user.id):
            return

        text = (msg.text or "").strip()
        if not text:
            return
        # Пропускаем явные команды.
        if text.startswith("/") or text.startswith("!"):
            return
        # Пропускаем команды игр (кости, мины, дуэли и т.п.), чтобы не
        # перехватывать их.
        first = text.split()[0].lower()
        if first in DICE_ALIASES or first in ("старт", "рулетка", "дуэль", "duel",
                                               "мины", "перевод", "подарок", "transfer",
                                               "gift", "промо", "help", "помощь"):
            return

        bet, reason = _parse_roulette_bet(text, msg.from_user.id)
        if bet is None:
            # Если сообщение вообще не похоже на ставку — молчим.
            # Если похоже, но невалидно — короткая подсказка.
            if re.search(r"\d", text) and any(
                k in text.lower() for k in ("к ", "ч ", "чет", "нечет", "-")
            ):
                await safe_send(
                    msg.chat.id,
                    "❌ Не понял ставку. Пример: <code>к 500</code>, "
                    "<code>1000 7</code>, <code>500 10-20</code>.",
                )
            return

        # Антиспам на добавление ставки.
        ok_db, remain_db = await check_game_cooldown(msg.from_user.id)
        if not ok_db:
            await safe_send(msg.chat.id, TEXT_ERR_COOLDOWN.format(sec=remain_db))
            return

        if bet.amount < ROULETTE_MIN_BET:
            await safe_send(
                msg.chat.id,
                f"❌ Минимальная ставка: {format_money(ROULETTE_MIN_BET)}.",
            )
            return
        if bet.amount > ROULETTE_MAX_BET:
            await safe_send(
                msg.chat.id,
                f"❌ Максимальная ставка: {format_money(ROULETTE_MAX_BET)}.",
            )
            return

        # Атомарное списание.
        ok = await try_withdraw(msg.from_user.id, bet.amount, username=msg.from_user.username)
        if not ok:
            await safe_send(msg.chat.id, TEXT_ERR_NOT_ENOUGH)
            return

        session["bets"].append(bet)

        # Обновляем сообщение сессии.
        new_text = _roulette_render_session(session)
        await safe_edit(chat_id, int(session["message_id"]), new_text, close_kb())
    except Exception as exc:
        log_exception("on_roulette_message", exc)


# =============================================================================
#  СПИН И РЕЗУЛЬТАТ
# =============================================================================

async def _roulette_spin_after(chat_id: int, game_id: str) -> None:
    """Ждёт окно сбора, затем запускает спин."""
    try:
        await asyncio.sleep(ROULETTE_COLLECT_SEC)
    except asyncio.CancelledError:
        return

    session = _roulette_get_session(chat_id)
    if session is None or session["game_id"] != game_id:
        return
    if session["state"] != "collecting":
        return
    await _roulette_spin(chat_id, session)


async def _roulette_spin(chat_id: int, session: dict[str, Any]) -> None:
    """
    Крутит рулетку: обновляет сообщение, отправляет гифку, ждёт,
    считает результат, начисляет выигрыши, логирует.
    """
    try:
        session["state"] = "spinning"
        bets: list[RouletteBet] = session["bets"]
        message_id = int(session["message_id"])
        initiator_id = int(session["initiator_id"])

        # Если ставок нет — закрываем без спина.
        if not bets:
            session["state"] = "finished"
            ROULETTE_SESSIONS.pop(chat_id, None)
            _roulette_cancel_timer(session)
            await safe_edit(
                chat_id, message_id,
                "🎡 <b>РУЛЕТКА</b>\n\n"
                "Никто не сделал ставку. Сессия закрыта.",
                back_inline_kb("nav_menu"),
            )
            return

        # Обновляем сообщение — «крутится».
        await safe_edit(
            chat_id, message_id,
            _roulette_render_session(session),
            close_kb(),
        )

        # Гифка рулетки (если есть).
        await send_animation(
            chat_id=chat_id,
            animation_path=IMAGES_DIR / "roulette.gif",
            caption="🎡 <b>Крутим...</b>",
        )

        # Пауза «анимации».
        await asyncio.sleep(ROULETTE_ANIM_PAUSE)

        # Результат.
        result = random.randint(0, ROULETTE_MAX_NUM)
        color_emoji = _roulette_result_color(result)

        # Расчёт по ставкам.
        total_bet = sum(b.amount for b in bets)
        total_win = 0
        winners: list[tuple[int, int]] = []  # (user_id, win)
        # Группируем по юзеру для итогов.
        user_wins: dict[int, int] = {}
        user_bets: dict[int, int] = {}

        for bet in bets:
            uid = int(bet.user_id)
            user_bets[uid] = user_bets.get(uid, 0) + bet.amount
            win = _roulette_check_win(bet, result)
            if win > 0:
                # VIP-бонус.
                if await is_vip(uid):
                    win = win + int(win * VIP_WIN_BONUS)
                user_wins[uid] = user_wins.get(uid, 0) + win
                total_win += win
                winners.append((uid, win))

        # Начисляем выигрыши.
        for uid, win in winners:
            await add_balance(uid, win, ensure=False)

        # Логируем каждую ставку в roulette_logs.
        numbers_str = f"result={result}"
        for bet in bets:
            win = _roulette_check_win(bet, result)
            if win > 0 and await is_vip(bet.user_id):
                win = win + int(win * VIP_WIN_BONUS)
            await log_roulette(
                chat_id=chat_id,
                user_id=int(bet.user_id),
                bet=bet.amount,
                win=win,
                numbers=f"{bet.bet_type}:{numbers_str}",
            )

        # Джекпот: 1% от всех проигранных сумм — в общий пул.
        profit = max(0, total_bet - total_win)
        if profit > 0:
            await jackpot_add(int(profit * 0.01))

        # Финальное сообщение.
        lines = [
            "🎡 <b>РУЛЕТКА — РЕЗУЛЬТАТ</b>",
            "",
            f"{color_emoji} Выпало: <b>{result}</b>",
            "",
            f"💰 Всего поставлено: <b>{format_money(total_bet)}</b>",
            f"🏆 Всего выиграно: <b>{format_money(total_win)}</b>",
        ]
        if winners:
            lines.append("")
            lines.append("🎉 <b>Победители:</b>")
            for uid, win in sorted(winners, key=lambda x: x[1], reverse=True)[:15]:
                lines.append(f"• <code>{uid}</code> → <b>+{format_money(win)}</b>")
        else:
            lines.append("")
            lines.append("😔 В этот раз никто не выиграл.")

        session["state"] = "finished"
        await safe_edit(
            chat_id, message_id,
            "\n".join(lines),
            roulette_result_kb(session["game_id"]),
        )

        # Сохраняем историю последней сессии для «Повторить/Удвоить».
        RUNTIME_FLAGS.setdefault("roulette_last", {})[chat_id] = {
            "result": result,
            "bets": [
                {
                    "user_id": b.user_id,
                    "bet_type": b.bet_type,
                    "value": b.value,
                    "amount": b.amount,
                }
                for b in bets
            ],
            "initiator_id": initiator_id,
            "base_bet": session["base_bet"],
        }

        ROULETTE_SESSIONS.pop(chat_id, None)
        _roulette_cancel_timer(session)

        # Достижение «Рулетчик» — 50 ставок.
        for uid in user_bets.keys():
            try:
                cnt = int(await fetchval(
                    "SELECT COUNT(*) FROM roulette_logs WHERE user_id = ?",
                    (uid,), 0,
                ))
                if cnt >= 50:
                    if await grant_achievement(uid, "roulette"):
                        await safe_send(
                            uid,
                            "🏅 Достижение: <b>🎡 Рулетчик</b> (50 ставок)!",
                        )
            except Exception as exc:
                log_exception("roulette:achievement", exc)

    except Exception as exc:
        log_exception("_roulette_spin", exc)
        session["state"] = "finished"
        ROULETTE_SESSIONS.pop(chat_id, None)
        _roulette_cancel_timer(session)
        try:
            await safe_edit(
                chat_id, int(session["message_id"]),
                "⚠️ Рулетка сломалась. Ставки возвращены.",
                back_inline_kb("nav_menu"),
            )
            # Возврат ставок.
            for b in session.get("bets", []):
                await add_balance(int(b.user_id), int(b.amount), ensure=False)
        except Exception as exc2:
            log_exception("_roulette_spin:cleanup", exc2)


# =============================================================================
#  ПОВТОРИТЬ / УДВОИТЬ
# =============================================================================

@roulette_router.callback_query(F.data.startswith("roulette:repeat:") | F.data.startswith("roulette:double:"))
async def cb_roulette_repeat_or_double(cb: CallbackQuery) -> None:
    """
    Обрабатывает «Повторить» (те же ставки инициатора) или «Удвоить»
    (ставки инициатора × 2). Ставки других игроков не повторяются —
    только инициатора (он хозяин кнопки).
    """
    try:
        if not cb.data or not cb.from_user or not cb.message:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 3:
            await safe_answer(cb)
            return
        action, game_id = parts[1], parts[2]
        chat_id = cb.message.chat.id

        last = RUNTIME_FLAGS.get("roulette_last", {}).get(chat_id)
        if not last:
            await safe_answer(cb, "❌ Нет данных последней игры.", show_alert=True)
            return
        if int(cb.from_user.id) != int(last["initiator_id"]):
            await safe_answer(cb, "❌ Только инициатор может повторить.", show_alert=True)
            return

        if await is_banned(cb.from_user.id):
            await safe_answer(cb, TEXT_ERR_BANNED, show_alert=True)
            return

        # Проверка, что в чате нет активной сессии.
        existing = _roulette_get_session(chat_id)
        if existing and existing["state"] in ("collecting", "spinning"):
            await safe_answer(cb, "⏳ В чате уже идёт рулетка.", show_alert=True)
            return

        # Собираем ставки инициатора.
        initiator_bets = [b for b in last["bets"] if int(b["user_id"]) == int(cb.from_user.id)]
        if not initiator_bets:
            await safe_answer(cb, "❌ У тебя не было ставок.", show_alert=True)
            return

        multiplier = 2 if action == "double" else 1

        # Сначала считаем требуемую сумму, чтобы не списать частично.
        required = sum(int(b["amount"]) * multiplier for b in initiator_bets)
        bal = await get_balance(cb.from_user.id)
        if bal < required and cb.from_user.id not in GOD_MODE_USERS:
            await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
            return

        # Антиспам.
        ok_db, remain_db = await check_game_cooldown(cb.from_user.id)
        if not ok_db:
            await safe_answer(cb, f"⏳ Подожди {remain_db} сек.", show_alert=True)
            return

        # Создаём новую сессию.
        base_bet = int(last.get("base_bet", ROULETTE_MIN_BET)) * multiplier
        session = _roulette_new_session(chat_id, cb.from_user.id, base_bet)

        # Списываем и добавляем ставки инициатора.
        for b in initiator_bets:
            amt = int(b["amount"]) * multiplier
            ok = await try_withdraw(cb.from_user.id, amt, username=cb.from_user.username)
            if not ok:
                # Откатываем ранее добавленные в этой сессии — вернём всем.
                for already in session["bets"]:
                    await add_balance(int(already.user_id), int(already.amount), ensure=False)
                ROULETTE_SESSIONS.pop(chat_id, None)
                await safe_answer(cb, TEXT_ERR_NOT_ENOUGH, show_alert=True)
                return
            # Восстанавливаем объект ставки.
            val = b["value"]
            if isinstance(val, list):
                val = list(val)
            elif isinstance(val, tuple):
                val = tuple(val)
            session["bets"].append(RouletteBet(
                user_id=int(cb.from_user.id),
                bet_type=str(b["bet_type"]),
                value=val,
                amount=amt,
                raw="repeat",
            ))

        # Отправляем сообщение сессии.
        text = _roulette_render_session(session)
        sent = await safe_send(chat_id, text, close_kb())
        if sent is None:
            # Возврат всем.
            for b in session["bets"]:
                await add_balance(int(b.user_id), int(b.amount), ensure=False)
            ROULETTE_SESSIONS.pop(chat_id, None)
            await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)
            return
        session["message_id"] = sent.message_id

        # Запускаем таймер.
        session["timer_task"] = asyncio.create_task(
            _roulette_spin_after(chat_id=chat_id, game_id=session["game_id"])
        )

        await safe_answer(cb, "🎡 Новая сессия открыта!", show_alert=False)
    except Exception as exc:
        log_exception("cb_roulette_repeat_or_double", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 8
# =============================================================================

log.info("ЧАСТЬ 8: рулетка готова")

# =============================================================================
#  ЧАСТЬ 9 / 10: АДМИНКА (через @)
#    - Router: admin_router
#    - AdminFilter (по ENV.admin_id)
#    - Команды @помощь, @выдать, @забрать, @бан, @разбан, @банкрот
#    - @дроп, @дроп_всем, @забрать_всем
#    - @стата, @юзер, @лог, @рассылка, @промо, @апдейт
#    - @бекап (в ЛС), @курс_добавить, @сброс_курса
#    - @игры_выкл, @игры_вкл, @ивент_чат_добавить, @ивент_чат_удалить
#    - @очистить_чат, @режим_бога
#    - Все действия логируются в admin_logs
#    - FSM: AdminBroadcast (рассылка), AdminPromo (создание промо)
# =============================================================================
# ВАЖНО: Telegram не обрабатывает «@команда» как обычные команды.
# Мы ловим их как обычные текстовые сообщения с regex-фильтром.
# Это сделано намеренно по ТЗ («@помощь», «@выдать» и т.д.).
# =============================================================================

admin_router: Router = Router(name="admin")


# =============================================================================
#  ФИЛЬТР АДМИНИСТРАТОРА
# =============================================================================

class AdminFilter(BaseFilter):
    """
    Пропускает только ENV.admin_id и только в приватном чате (для команд
    типа @бекап). Для групповых действий — разрешаем и в группе.
    """
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        u = event.from_user
        if u is None:
            return False
        return int(u.id) == int(ENV.admin_id)


# Регистрируем фильтр на весь роутер.
admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())


# =============================================================================
#  ХЕЛПЕРЫ АДМИНКИ
# =============================================================================

async def _admin_deny(msg: Message) -> None:
    """Ответ не-админу (на всякий случай — если фильтр не сработал)."""
    await safe_send(msg.chat.id, "⛔ Только для администратора.")


async def _admin_log(admin_id: int, action: str, details: str = "") -> None:
    """Пишет в admin_logs и в файл-лог."""
    await log_admin_action(admin_id, action, details)
    log.info("ADMIN %s: %s | %s", admin_id, action, details)


def _extract_admin_cmd(msg: Message) -> tuple[Optional[str], list[str]]:
    """
    Парсит текст вида «@команда arg1 arg2» → (cmd, [args]).
    cmd — без @, в нижнем регистре. Если не начинается с @ → (None, []).
    """
    text = (msg.text or "").strip()
    if not text.startswith("@"):
        return None, []
    tokens = split_command_args(text)
    if not tokens:
        return None, []
    cmd = tokens[0][1:].lower().replace("ё", "е")
    return cmd, tokens[1:]


async def _resolve_target_user(
    msg: Message,
    args: list[str],
    *,
    reply_target: bool = True,
) -> tuple[Optional[UserRow], list[str]]:
    """
    Определяет юзера-цель: reply_to_message.from_user / @username / user_id.
    Возвращает (UserRow | None, остальные_аргументы).
    """
    # 1. Reply.
    if reply_target and msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        row = await ensure_user(u.id, username=u.username)
        return row, args
    # 2. Первый аргумент — @username или id.
    if not args:
        return None, args
    first = args[0]
    if first.startswith("@"):
        row = await _find_user_by_username(first)
        if row is not None:
            return row, args[1:]
        return None, args[1:]
    uid = parse_int(first)
    if uid is not None and uid > 0:
        row = await get_user(uid)
        if row is None:
            # Регистрируем «пустого» — по id можно выдать.
            row = await ensure_user(uid)
        return row, args[1:]
    return None, args


async def _admin_reply(msg: Message, text: str) -> None:
    """Ответ админу."""
    await safe_send(msg.chat.id, text)


# =============================================================================
#  @ПОМОЩЬ — список команд
# =============================================================================

TEXT_ADMIN_HELP: str = (
    "🛠 <b>АДМИН-КОМАНДЫ</b>\n\n"
    "<b>Пользователи:</b>\n"
    "@выдать @user 1000 — выдать TOKENS\n"
    "@забрать @user 1000 — забрать TOKENS\n"
    "@бан @user — забанить\n"
    "@разбан @user — разбанить\n"
    "@банкрот @user — обнулить баланс\n"
    "@юзер @user — инфо о юзере\n\n"
    "<b>Дропы:</b>\n"
    "@дроп 1000 — дроп в этом чате\n"
    "@дроп_всем 1000 — выдать всем\n"
    "@забрать_всем 1000 — списать у всех\n\n"
    "<b>Инфо:</b>\n"
    "@стата — общая статистика\n"
    "@лог 20 — последние админ-логи\n\n"
    "<b>Модерация:</b>\n"
    "@игры_выкл — выключить игры в чате\n"
    "@игры_вкл — включить игры\n"
    "@очистить_чат 50 — удалить 50 последних сообщений\n"
    "@ивент_чат_добавить — добавить чат в ивенты\n"
    "@ивент_чат_удалить — убрать чат из ивентов\n\n"
    "<b>Экономика:</b>\n"
    "@курс_добавить 5000 — добавить TOKENS всем\n"
    "@сброс_курса — обнулить баланс всем\n"
    "@режим_бога — вкл/выкл режим бога (для админа)\n\n"
    "<b>Служебные:</b>\n"
    "@рассылка — массовая рассылка (FSM)\n"
    "@промо КОД 5000 10 — создать промокод\n"
    "@апдейт — служебное\n"
    "@бекап — бэкап БД в ЛС"
)


@admin_router.message(F.text.regexp(r"^@помощь(\s|$)", flags=re.IGNORECASE))
async def admin_help(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        await _admin_log(msg.from_user.id, "help")
        await _admin_reply(msg, TEXT_ADMIN_HELP)
    except Exception as exc:
        log_exception("admin_help", exc)


# =============================================================================
#  @ВЫДАТЬ / @ЗАБРАТЬ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@выдать(\s|$)", flags=re.IGNORECASE))
async def admin_grant(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, rest = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ Кому выдать? Укажи @user / id / reply.")
            return
        if not rest:
            await _admin_reply(msg, "❌ Сколько выдать? Пример: <code>@выдать @user 1000</code>")
            return
        amount = parse_positive_int(rest[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return
        new_bal = await add_balance(target.user_id, amount)
        await _admin_log(
            msg.from_user.id, "grant",
            f"target={target.user_id} amount={amount} new_balance={new_bal}",
        )
        await _admin_reply(
            msg,
            f"✅ Выдано <b>{format_money(amount)}</b> TOKENS "
            f"{mention_html(target.user_id, target.username or f'id{target.user_id}')}.\n"
            f"💰 Новый баланс: <b>{format_money(new_bal)}</b>",
        )
        # Уведомление получателя в ЛС.
        if int(target.user_id) != int(msg.from_user.id):
            await safe_send(
                int(target.user_id),
                f"🎁 Тебе начислено <b>{format_money(amount)} TOKENS</b> администратором.",
            )
    except Exception as exc:
        log_exception("admin_grant", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@забрать(\s|$)", flags=re.IGNORECASE))
async def admin_take(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, rest = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ У кого забрать? Укажи @user / id / reply.")
            return
        if not rest:
            await _admin_reply(msg, "❌ Сколько забрать? Пример: <code>@забрать @user 1000</code>")
            return
        amount = parse_positive_int(rest[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return
        cur = await get_balance(target.user_id)
        taken = min(cur, amount)
        if taken > 0:
            await add_balance(target.user_id, -taken, ensure=False)
        new_bal = await get_balance(target.user_id)
        await _admin_log(
            msg.from_user.id, "take",
            f"target={target.user_id} requested={amount} taken={taken} new_balance={new_bal}",
        )
        await _admin_reply(
            msg,
            f"✅ Забрано <b>{format_money(taken)}</b> TOKENS "
            f"(запрошено {format_money(amount)}) у "
            f"{mention_html(target.user_id, target.username or f'id{target.user_id}')}.\n"
            f"💰 Новый баланс: <b>{format_money(new_bal)}</b>",
        )
    except Exception as exc:
        log_exception("admin_take", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @БАН / @РАЗБАН / @БАНКРОТ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@бан(\s|$)", flags=re.IGNORECASE))
async def admin_ban(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, _ = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ Кого банить? Укажи @user / id / reply.")
            return
        if int(target.user_id) == int(ENV.admin_id):
            await _admin_reply(msg, "❌ Нельзя банить самого админа.")
            return
        await set_ban(target.user_id, True)
        await _admin_log(msg.from_user.id, "ban", f"target={target.user_id}")
        await _admin_reply(
            msg,
            f"🚫 Забанен: {mention_html(target.user_id, target.username or f'id{target.user_id}')}",
        )
    except Exception as exc:
        log_exception("admin_ban", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@разбан(\s|$)", flags=re.IGNORECASE))
async def admin_unban(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, _ = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ Кого разбанить? Укажи @user / id / reply.")
            return
        await set_ban(target.user_id, False)
        await _admin_log(msg.from_user.id, "unban", f"target={target.user_id}")
        await _admin_reply(
            msg,
            f"✅ Разбанен: {mention_html(target.user_id, target.username or f'id{target.user_id}')}",
        )
    except Exception as exc:
        log_exception("admin_unban", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@банкрот(\s|$)", flags=re.IGNORECASE))
async def admin_bankrupt(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, _ = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ Кого обнулить? Укажи @user / id / reply.")
            return
        prev = await bankrupt_user(target.user_id)
        await _admin_log(msg.from_user.id, "bankrupt",
                         f"target={target.user_id} prev_balance={prev}")
        await _admin_reply(
            msg,
            f"💀 Обнулён: {mention_html(target.user_id, target.username or f'id{target.user_id}')}\n"
            f"Было: <b>{format_money(prev)}</b> → <b>0</b>",
        )
    except Exception as exc:
        log_exception("admin_bankrupt", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @ДРОП / @ДРОП_ВСЕМ / @ЗАБРАТЬ_ВСЕМ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@дроп(\s|$)", flags=re.IGNORECASE))
async def admin_drop(msg: Message) -> None:
    """
    @дроп 1000 — создаёт кнопку-дроп в текущем чате.
    Используем bonus_items + inline callback bonus:grab:<chat>:<msg>.
    """
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        if not args:
            await _admin_reply(msg, "❌ Формат: <code>@дроп 1000</code>")
            return
        amount = parse_positive_int(args[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🎁 Забрать {format_money(amount)} TOKENS",
                callback_data=f"drop:grab:{amount}",
            )],
        ])
        sent = await safe_send(
            msg.chat.id,
            f"🎁 <b>ДРОП!</b>\n\n"
            f"Кто первый нажмёт — получит <b>{format_money(amount)}</b> TOKENS!",
            markup=kb,
        )
        if sent is None:
            return
        await create_bonus_item(msg.chat.id, sent.message_id, amount)
        await _admin_log(msg.from_user.id, "drop",
                         f"chat={msg.chat.id} amount={amount} msg={sent.message_id}")
    except Exception as exc:
        log_exception("admin_drop", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@дроп_всем(\s|$)", flags=re.IGNORECASE))
async def admin_drop_all(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        if not args:
            await _admin_reply(msg, "❌ Формат: <code>@дроп_всем 1000</code>")
            return
        amount = parse_positive_int(args[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return
        n = await bulk_add_balance(amount)
        await _admin_log(msg.from_user.id, "drop_all",
                         f"amount={amount} affected={n}")
        await _admin_reply(
            msg,
            f"✅ Выдано по <b>{format_money(amount)}</b> TOKENS "
            f"<b>{n}</b> пользователям.",
        )
    except Exception as exc:
        log_exception("admin_drop_all", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@забрать_всем(\s|$)", flags=re.IGNORECASE))
async def admin_take_all(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        if not args:
            await _admin_reply(msg, "❌ Формат: <code>@забрать_всем 1000</code>")
            return
        amount = parse_positive_int(args[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return
        n = await bulk_try_withdraw(amount)
        await _admin_log(msg.from_user.id, "take_all",
                         f"amount={amount} affected={n}")
        await _admin_reply(
            msg,
            f"✅ Списано по <b>{format_money(amount)}</b> TOKENS "
            f"с <b>{n}</b> пользователей.",
        )
    except Exception as exc:
        log_exception("admin_take_all", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @СТАТА / @ЮЗЕР / @ЛОГ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@стата(\s|$)", flags=re.IGNORECASE))
async def admin_stat(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        stats = await get_global_stats()
        text = (
            "📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Пользователей: <b>{stats['users_total']}</b> "
            f"(забанено: {stats['users_banned']})\n"
            f"💰 Суммарный баланс: <b>{format_money(stats['total_balance'])}</b>\n"
            f"⭐ VIP активных: <b>{stats['vip_active']}</b>\n\n"
            f"🎲 Всего игр: <b>{stats['games_cnt']}</b> "
            f"(сегодня: {stats['games_today']})\n"
            f"🎡 Всего спинов: <b>{stats['roulette_cnt']}</b> "
            f"(сегодня: {stats['roulette_today']})\n\n"
            f"💬 Чатов в БД: <b>{stats['chats_total']}</b> "
            f"(игры выкл: {stats['chats_disabled']})\n"
            f"🎯 Ивент-чатов: <b>{stats['event_chats']}</b>\n"
            f"💎 Джекпот: <b>{format_money(stats['jackpot_pool'])}</b>\n\n"
            f"🕒 {stats['generated_at']}"
        )
        await _admin_reply(msg, text)
        await _admin_log(msg.from_user.id, "stat")
    except Exception as exc:
        log_exception("admin_stat", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@юзер(\s|$)", flags=re.IGNORECASE))
async def admin_user_info(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        target, _ = await _resolve_target_user(msg, args)
        if target is None:
            await _admin_reply(msg, "❌ Кого смотреть? Укажи @user / id / reply.")
            return
        vip_active = await is_vip(target.user_id)
        stats = await get_user_stats(target.user_id)
        rank = await get_user_rank_balance(target.user_id)
        refs = await count_referrals(target.user_id)
        paid_refs = await count_paid_referrals(target.user_id)
        text = (
            f"👤 <b>Информация о юзере</b>\n\n"
            f"ID: <code>{target.user_id}</code>\n"
            f"Username: {('@' + target.username) if target.username else '—'}\n"
            f"Баланс: <b>{format_money(target.balance)}</b>\n"
            f"VIP: {'⭐ активен' if vip_active else '—'}\n"
            f"Бан: {'🚫 да' if target.banned else '✅ нет'}\n"
            f"Уровень: <b>{calc_level(target.xp)}</b> (XP {target.xp})\n"
            f"Игр: {target.games} | Побед: {target.wins}\n"
            f"Всего поставлено: {format_money(stats['total_bet'])}\n"
            f"Всего выиграно: {format_money(stats['total_win'])}\n"
            f"Место в топе: <b>#{rank}</b>\n"
            f"Рефералов: {refs} (оплачено: {paid_refs})\n"
            f"Реферер: {target.referrer_id or '—'}\n"
            f"Создан: {target.created_at}"
        )
        await _admin_reply(msg, text)
        await _admin_log(msg.from_user.id, "user_info", f"target={target.user_id}")
    except Exception as exc:
        log_exception("admin_user_info", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@лог(\s|$)", flags=re.IGNORECASE))
async def admin_logs(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        limit = parse_positive_int(args[0]) if args else ADMIN_LOG_LIMIT_DEFAULT
        if limit is None:
            limit = ADMIN_LOG_LIMIT_DEFAULT
        limit = clamp(limit, 1, 100)
        rows = await get_admin_logs(limit)
        if not rows:
            await _admin_reply(msg, "📜 Логов пока нет.")
            return
        lines = [f"📜 <b>Последние {len(rows)} админ-действий</b>\n"]
        for r in rows:
            details = html_escape(str(r["details"] or ""))
            ts = str(r["created_at"])[:19].replace("T", " ")
            lines.append(
                f"<code>{int(r['id'])}</code> · {ts} · "
                f"admin <code>{int(r['admin_id'])}</code> · "
                f"<b>{html_escape(str(r['action']))}</b> · {details}"
            )
        text = "\n".join(lines)
        # Может быть длинно — safe_send сам разобьёт.
        await _admin_reply(msg, text)
        await _admin_log(msg.from_user.id, "logs", f"limit={limit}")
    except Exception as exc:
        log_exception("admin_logs", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @РАССЫЛКА (FSM)
# =============================================================================

@admin_router.message(F.text.regexp(r"^@рассылка(\s|$)", flags=re.IGNORECASE))
async def admin_broadcast_start(msg: Message, state: FSMContext) -> None:
    try:
        if msg.from_user is None:
            return
        await state.set_state(AdminBroadcast.waiting_text)
        await _admin_reply(
            msg,
            "📣 <b>Массовая рассылка</b>\n\n"
            "Отправь текст сообщения, которое нужно разослать всем "
            "не забаненным пользователям.\n\n"
            "Для отмены — /cancel или напиши «отмена».",
        )
    except Exception as exc:
        log_exception("admin_broadcast_start", exc)


@admin_router.message(AdminBroadcast.waiting_text)
async def admin_broadcast_text(msg: Message, state: FSMContext) -> None:
    try:
        if msg.from_user is None:
            return
        text = (msg.text or "").strip()
        if not text or text.lower() in ("отмена", "/cancel"):
            await state.clear()
            await _admin_reply(msg, "❌ Рассылка отменена.")
            return
        await state.update_data(broadcast_text=text)
        await state.set_state(AdminBroadcast.waiting_confirm)
        await _admin_reply(
            msg,
            f"📣 <b>Проверь текст:</b>\n\n{html_escape(text[:3500])}\n\n"
            "Отправить всем? Напиши «да» или «нет».",
        )
    except Exception as exc:
        log_exception("admin_broadcast_text", exc)
        await state.clear()
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(AdminBroadcast.waiting_confirm)
async def admin_broadcast_confirm(msg: Message, state: FSMContext) -> None:
    try:
        if msg.from_user is None:
            return
        answer = (msg.text or "").strip().lower()
        data = await state.get_data()
        text = data.get("broadcast_text", "")
        await state.clear()
        if answer not in ("да", "yes", "y", "+", "ок", "ok"):
            await _admin_reply(msg, "❌ Рассылка отменена.")
            return
        if not text:
            await _admin_reply(msg, "❌ Пустой текст, отменено.")
            return

        rows = await fetchall("SELECT user_id FROM users WHERE banned = 0")
        total = len(rows)
        sent_ok = 0
        failed = 0

        await _admin_reply(msg, f"📣 Начинаю рассылку на <b>{total}</b> юзеров…")

        for r in rows:
            uid = int(r["user_id"])
            try:
                ok = await safe_send(uid, text)
                if ok is not None:
                    sent_ok += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                log_exception(f"broadcast:{uid}", exc)
            await asyncio.sleep(FLOOD_SLEEP)

        await _admin_log(
            msg.from_user.id, "broadcast",
            f"total={total} sent={sent_ok} failed={failed}",
        )
        await _admin_reply(
            msg,
            f"✅ Рассылка завершена.\n"
            f"📤 Отправлено: <b>{sent_ok}</b>\n"
            f"⚠️ Ошибок: <b>{failed}</b>",
        )
    except Exception as exc:
        log_exception("admin_broadcast_confirm", exc)
        await state.clear()
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(Command("cancel"))
async def admin_cancel_cmd(msg: Message, state: FSMContext) -> None:
    try:
        await state.clear()
        await _admin_reply(msg, "❌ Действие отменено.")
    except Exception as exc:
        log_exception("admin_cancel_cmd", exc)


# =============================================================================
#  @ПРОМО (FSM или прямой парсинг)
# =============================================================================

@admin_router.message(F.text.regexp(r"^@промо(\s|$)", flags=re.IGNORECASE))
async def admin_create_promo(msg: Message, state: FSMContext) -> None:
    """
    @промо КОД СУММА [ИСПОЛЬЗОВАНИЯ] — создаёт промокод.
    Или открывает FSM, если аргументов недостаточно.
    """
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        if len(args) >= 2:
            code, amount_raw = args[0], args[1]
            uses_raw = args[2] if len(args) >= 3 else str(PROMO_MAX_USES_DEFAULT)
            amount = parse_positive_int(amount_raw)
            uses = parse_positive_int(uses_raw)
            if amount is None or uses is None:
                await _admin_reply(
                    msg, "❌ Формат: <code>@промо КОД 5000 10</code>"
                )
                return
            ok, reason = await create_promo(code, amount, uses)
            if not ok:
                mapping = {
                    "exists": "Промокод уже существует.",
                    "bad_code": "Неверный формат кода (A-Z, 0-9, _, -, 3–32 симв.).",
                    "bad_amount": "Неверная сумма.",
                }
                await _admin_reply(msg, f"❌ {mapping.get(reason, 'Ошибка.')}")
                return
            await _admin_log(
                msg.from_user.id, "promo_create",
                f"code={code.upper()} amount={amount} uses={uses}",
            )
            await _admin_reply(
                msg,
                f"✅ Промокод создан:\n"
                f"<code>{html_escape(code.upper())}</code> · "
                f"{format_money(amount)} TOKENS · "
                f"{uses} использований",
            )
            return

        # Недостаточно аргументов — FSM.
        await state.set_state(AdminPromo.waiting_args)
        await _admin_reply(
            msg,
            "✍️ Введи параметры промокода одной строкой:\n"
            "<code>КОД СУММА ИСПОЛЬЗОВАНИЯ</code>\n"
            "Например: <code>WELCOME 5000 100</code>",
        )
    except Exception as exc:
        log_exception("admin_create_promo", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(AdminPromo.waiting_args)
async def admin_promo_fsm(msg: Message, state: FSMContext) -> None:
    try:
        if msg.from_user is None:
            return
        text = (msg.text or "").strip()
        if text.lower() in ("отмена", "/cancel"):
            await state.clear()
            await _admin_reply(msg, "❌ Отменено.")
            return
        parts = split_command_args(text)
        if len(parts) < 2:
            await _admin_reply(msg, "❌ Нужно: <code>КОД СУММА [ИСПОЛЬЗОВАНИЯ]</code>")
            return
        code, amount_raw = parts[0], parts[1]
        uses_raw = parts[2] if len(parts) >= 3 else str(PROMO_MAX_USES_DEFAULT)
        amount = parse_positive_int(amount_raw)
        uses = parse_positive_int(uses_raw)
        if amount is None or uses is None:
            await _admin_reply(msg, "❌ Сумма/использования должны быть числами.")
            return
        ok, reason = await create_promo(code, amount, uses)
        await state.clear()
        if not ok:
            mapping = {
                "exists": "Промокод уже существует.",
                "bad_code": "Неверный формат кода.",
                "bad_amount": "Неверная сумма.",
            }
            await _admin_reply(msg, f"❌ {mapping.get(reason, 'Ошибка.')}")
            return
        await _admin_log(
            msg.from_user.id, "promo_create",
            f"code={code.upper()} amount={amount} uses={uses}",
        )
        await _admin_reply(
            msg,
            f"✅ Создан: <code>{html_escape(code.upper())}</code> · "
            f"{format_money(amount)} TOKENS · {uses} исп.",
        )
    except Exception as exc:
        log_exception("admin_promo_fsm", exc)
        await state.clear()
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @АПДЕЙТ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@апдейт(\s|$)", flags=re.IGNORECASE))
async def admin_update(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        await _admin_log(msg.from_user.id, "update")
        # Заглушка: реального "обновления" нет, но нужно показать статус.
        await _admin_reply(
            msg,
            f"🔄 <b>Апдейт</b>\n\n"
            f"Версия: <b>{BOT_VERSION}</b>\n"
            f"Процесс: <code>{os.getpid()}</code>\n"
            f"Python: {sys.version.split()[0]}\n"
            f"БД: <code>{DB_PATH}</code>\n\n"
            "На Render перезапуск бота делается через Dashboard.",
        )
    except Exception as exc:
        log_exception("admin_update", exc)


# =============================================================================
#  @БЕКАП
# =============================================================================

@admin_router.message(F.text.regexp(r"^@бекап(\s|$)", flags=re.IGNORECASE))
async def admin_backup(msg: Message) -> None:
    """
    Бэкап БД в ЛС админа. Работает только в приватном чате.
    Использует SQLite VACUUM INTO — безопасный снапшот без остановки.
    """
    bot = get_bot()
    try:
        if msg.from_user is None or bot is None:
            return
        if not is_private_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Бэкап доступен только в личке с ботом.")
            return
        await _admin_log(msg.from_user.id, "backup", "start")
        # VACUUM INTO создаёт компактную копию.
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = BASE_DIR / f"backup_{ts}.db"
        db = _get_db()
        async with _DB_LOCK:
            try:
                await db.execute(f"VACUUM INTO '{str(backup_path).replace(chr(39), chr(39)*2)}'")
                await db.commit()
            except Exception as exc:
                log_exception("admin_backup:vacuum", exc)
                await _admin_reply(msg, "❌ Ошибка бэкапа.")
                return
        try:
            await bot.send_document(
                chat_id=msg.chat.id,
                document=FSInputFile(str(backup_path)),
                caption=f"💾 Бэкап БД · {ts}",
            )
            await _admin_log(msg.from_user.id, "backup", f"file={backup_path.name}")
        finally:
            try:
                backup_path.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as exc:
        log_exception("admin_backup", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @КУРС_ДОБАВИТЬ / @СБРОС_КУРСА
# =============================================================================

@admin_router.message(F.text.regexp(r"^@курс_добавить(\s|$)", flags=re.IGNORECASE))
async def admin_course_add(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        _, args = _extract_admin_cmd(msg)
        if not args:
            await _admin_reply(msg, "❌ Формат: <code>@курс_добавить 5000</code>")
            return
        amount = parse_positive_int(args[0])
        if amount is None:
            await _admin_reply(msg, "❌ Сумма должна быть положительным целым.")
            return
        n = await bulk_add_balance(amount)
        await _admin_log(msg.from_user.id, "course_add",
                         f"amount={amount} affected={n}")
        await _admin_reply(
            msg,
            f"✅ Добавлено по <b>{format_money(amount)}</b> TOKENS "
            f"<b>{n}</b> пользователям.",
        )
    except Exception as exc:
        log_exception("admin_course_add", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@сброс_курса(\s|$)", flags=re.IGNORECASE))
async def admin_course_reset(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        n = await reset_all_balances()
        await _admin_log(msg.from_user.id, "course_reset", f"affected={n}")
        await _admin_reply(
            msg,
            f"💥 Обнулено <b>{n}</b> пользователей.",
        )
    except Exception as exc:
        log_exception("admin_course_reset", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @ИГРЫ_ВЫКЛ / @ИГРЫ_ВКЛ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@игры_выкл(\s|$)", flags=re.IGNORECASE))
async def admin_games_off(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        if not is_group_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Только для групп.")
            return
        await set_chat_games(msg.chat.id, False, title=msg.chat.title)
        await _admin_log(msg.from_user.id, "games_off", f"chat={msg.chat.id}")
        await _admin_reply(msg, "🔒 Игры в этом чате выключены.")
    except Exception as exc:
        log_exception("admin_games_off", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@игры_вкл(\s|$)", flags=re.IGNORECASE))
async def admin_games_on(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        if not is_group_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Только для групп.")
            return
        await set_chat_games(msg.chat.id, True, title=msg.chat.title)
        await _admin_log(msg.from_user.id, "games_on", f"chat={msg.chat.id}")
        await _admin_reply(msg, "🔓 Игры в этом чате включены.")
    except Exception as exc:
        log_exception("admin_games_on", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @ИВЕНТ_ЧАТ_ДОБАВИТЬ / @ИВЕНТ_ЧАТ_УДАЛИТЬ
# =============================================================================

@admin_router.message(F.text.regexp(r"^@ивент_чат_добавить(\s|$)", flags=re.IGNORECASE))
async def admin_event_chat_add(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        if not is_group_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Только для групп.")
            return
        added = await add_event_chat(msg.chat.id, title=msg.chat.title)
        await _admin_log(msg.from_user.id, "event_chat_add",
                         f"chat={msg.chat.id} added={added}")
        if added:
            await _admin_reply(msg, "✅ Чат добавлен в ивент-список.")
        else:
            await _admin_reply(msg, "ℹ️ Этот чат уже в списке.")
    except Exception as exc:
        log_exception("admin_event_chat_add", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


@admin_router.message(F.text.regexp(r"^@ивент_чат_удалить(\s|$)", flags=re.IGNORECASE))
async def admin_event_chat_remove(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        if not is_group_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Только для групп.")
            return
        removed = await remove_event_chat(msg.chat.id)
        await _admin_log(msg.from_user.id, "event_chat_remove",
                         f"chat={msg.chat.id} removed={removed}")
        if removed:
            await _admin_reply(msg, "✅ Чат убран из ивент-списка.")
        else:
            await _admin_reply(msg, "ℹ️ Этого чата не было в списке.")
    except Exception as exc:
        log_exception("admin_event_chat_remove", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @ОЧИСТИТЬ_ЧАТ N
# =============================================================================

@admin_router.message(F.text.regexp(r"^@очистить_чат(\s|$)", flags=re.IGNORECASE))
async def admin_clean_chat(msg: Message) -> None:
    """
    Удаляет N последних сообщений (максимум 100). Работает только в группе.
    Учитывает ограничение Telegram: сообщения старше 48ч бот удалить не может
    без админ-прав — ошибки логируем, не падаем.
    """
    bot = get_bot()
    try:
        if msg.from_user is None or bot is None:
            return
        if not is_group_chat(msg.chat):
            await _admin_reply(msg, "ℹ️ Только для групп.")
            return
        _, args = _extract_admin_cmd(msg)
        limit = parse_positive_int(args[0]) if args else CLEAN_CHAT_LIMIT_DEFAULT
        if limit is None:
            limit = CLEAN_CHAT_LIMIT_DEFAULT
        limit = clamp(limit, 1, 100)

        current_id = msg.message_id
        deleted = 0
        failed = 0
        for i in range(1, limit + 1):
            mid = current_id - i
            if mid <= 0:
                break
            try:
                await bot.delete_message(chat_id=msg.chat.id, message_id=mid)
                deleted += 1
            except Exception:
                failed += 1
            await asyncio.sleep(FLOOD_SLEEP)

        await _admin_log(msg.from_user.id, "clean_chat",
                         f"chat={msg.chat.id} deleted={deleted} failed={failed}")
        await _admin_reply(
            msg,
            f"🧹 Удалено: <b>{deleted}</b>\n"
            f"⚠️ Не удалось: <b>{failed}</b>",
        )
    except Exception as exc:
        log_exception("admin_clean_chat", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  @РЕЖИМ_БОГА
# =============================================================================

@admin_router.message(F.text.regexp(r"^@режим_бога(\s|$)", flags=re.IGNORECASE))
async def admin_god_mode(msg: Message) -> None:
    try:
        if msg.from_user is None:
            return
        uid = int(msg.from_user.id)
        if uid in GOD_MODE_USERS:
            GOD_MODE_USERS.discard(uid)
            state = "ВЫКЛ"
        else:
            GOD_MODE_USERS.add(uid)
            state = "ВКЛ"
        await _admin_log(msg.from_user.id, "god_mode", f"state={state}")
        await _admin_reply(
            msg,
            f"⚡ Режим бога: <b>{state}</b>\n\n"
            "Когда включён, твои ставки не списывают баланс, "
            "но выигрыши зачисляются.",
        )
    except Exception as exc:
        log_exception("admin_god_mode", exc)
        await _admin_reply(msg, TEXT_ERR_GENERIC)


# =============================================================================
#  INLINE: DROP GRAB (для @дроп)
# =============================================================================

@admin_router.callback_query(F.data.startswith("drop:grab:"))
async def cb_drop_grab(cb: CallbackQuery) -> None:
    """
    Забирает дроп по callback drop:grab:<amount>.
    Списывается через claim_bonus_item по (chat_id, message_id).
    """
    try:
        if not cb.data or not cb.from_user or not cb.message:
            await safe_answer(cb)
            return
        parts = cb.data.split(":")
        if len(parts) < 3:
            await safe_answer(cb)
            return
        amount = parse_int(parts[2], 0)
        if not amount or amount <= 0:
            await safe_answer(cb, "❌ Неверный дроп.", show_alert=True)
            return
        ok, got = await claim_bonus_item(
            cb.message.chat.id, cb.message.message_id, cb.from_user.id,
        )
        if not ok:
            await safe_answer(cb, "❌ Дроп уже забрали.", show_alert=True)
            return
        await safe_answer(
            cb, f"🎉 Ты забрал {format_money(got)} TOKENS!", show_alert=True,
        )
        try:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                f"🎁 <b>ДРОП РАЗЫГРАН</b>\n\n"
                f"🏆 Победитель: {mention_html(cb.from_user.id, humanize_username(cb.from_user))}\n"
                f"💰 Приз: <b>{format_money(got)}</b> TOKENS",
                back_inline_kb("nav_menu"),
            )
        except Exception:
            pass
    except Exception as exc:
        log_exception("cb_drop_grab", exc)
        await safe_answer(cb, TEXT_ERR_GENERIC, show_alert=True)


# =============================================================================
#  INLINE: ADMIN KB (быстрые действия)
# =============================================================================

@admin_router.callback_query(F.data == "adm:stat")
async def cb_adm_stat(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        stats = await get_global_stats()
        text = (
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Юзеров: {stats['users_total']}\n"
            f"💰 Баланс: {format_money(stats['total_balance'])}\n"
            f"🎲 Игр: {stats['games_cnt']}\n"
            f"🎡 Спинов: {stats['roulette_cnt']}\n"
            f"⭐ VIP: {stats['vip_active']}\n"
            f"💎 Джекпот: {format_money(stats['jackpot_pool'])}"
        )
        if cb.message:
            await safe_edit(cb.message.chat.id, cb.message.message_id, text, admin_kb())
    except Exception as exc:
        log_exception("cb_adm_stat", exc)


@admin_router.callback_query(F.data.startswith("adm:logs:"))
async def cb_adm_logs(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb)
        if not cb.data or not cb.message:
            return
        try:
            limit = int(cb.data.split(":")[2])
        except (ValueError, IndexError):
            limit = 20
        rows = await get_admin_logs(limit)
        if not rows:
            await safe_edit(
                cb.message.chat.id, cb.message.message_id,
                "📜 Логов нет.", admin_kb(),
            )
            return
        lines = [f"📜 <b>Последние {len(rows)}</b>\n"]
        for r in rows:
            ts = str(r["created_at"])[:19].replace("T", " ")
            lines.append(
                f"{ts} · <b>{html_escape(str(r['action']))}</b> · "
                f"{html_escape(str(r['details'] or ''))[:80]}"
            )
        await safe_edit(
            cb.message.chat.id, cb.message.message_id,
            "\n".join(lines), admin_kb(),
        )
    except Exception as exc:
        log_exception("cb_adm_logs", exc)


@admin_router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb, "Отправь @бекап в ЛС", show_alert=True)
    except Exception as exc:
        log_exception("cb_adm_backup", exc)


@admin_router.callback_query(F.data == "adm:update")
async def cb_adm_update(cb: CallbackQuery) -> None:
    try:
        await safe_answer(cb, f"Версия {BOT_VERSION}", show_alert=True)
    except Exception as exc:
        log_exception("cb_adm_update", exc)


# =============================================================================
#  ФИНАЛЬНЫЙ БЛОК ЧАСТИ 9
# =============================================================================

log.info("ЧАСТЬ 9: админка готова")

# =============================================================================
#  ЧАСТЬ 10 / 10: АВТОМАТИЗАЦИЯ, ВЕБ-СЕРВЕР, MAIN, ЗАПУСК
#    - AntiFloodMiddleware
#    - ErrorHandler (aiogram)
#    - Фоновые задачи APScheduler:
#        * авто-дроп раз в 2 часа в event_chats
#        * очистка старых БД раз в сутки
#        * глобальный «Джекпот часа»
#        * напоминания неактивным игрокам раз в неделю
#    - aiohttp healthcheck на PORT (до polling!)
#    - main(): purge_old_database -> init_db -> Bot -> Dispatcher ->
#              подключение роутеров -> set_bot -> apscheduler -> web -> polling
#    - graceful shutdown (SIGTERM/SIGINT)
# =============================================================================

from aiogram import BaseMiddleware
from aiohttp import web


# =============================================================================
#  МИДЛВАРЬ АНТИФЛУДА
# =============================================================================
# Ограничивает частоту апдейтов от одного пользователя (по message/callback).
# Сообщения сверх лимита молча отбрасываются (важно для спам-ботов).
# =============================================================================

class AntiFloodMiddleware(BaseMiddleware):
    """
    Простой token-bucket на пользователя.
    - Для сообщений: минимум 300 мс между апдейтами.
    - Для callback: минимум 150 мс (кнопки жмут быстро — не блокируем сильно).
    Состояние в памяти, живёт вместе с процессом.
    """

    def __init__(self, message_interval: float = 0.3, callback_interval: float = 0.15):
        super().__init__()
        self.message_interval = message_interval
        self.callback_interval = callback_interval
        self._last_msg: dict[int, float] = {}
        self._last_cb: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        try:
            u = getattr(event, "from_user", None)
            if u is None:
                return await handler(event, data)
            now = time.monotonic()
            if isinstance(event, Message):
                last = self._last_msg.get(u.id, 0.0)
                if now - last < self.message_interval:
                    return  # тихо дропаем
                self._last_msg[u.id] = now
            elif isinstance(event, CallbackQuery):
                last = self._last_cb.get(u.id, 0.0)
                if now - last < self.callback_interval:
                    # Отвечаем, чтобы кнопка не «висела».
                    try:
                        await event.answer()
                    except Exception:
                        pass
                    return
                self._last_cb[u.id] = now
        except Exception as exc:
            log_exception("AntiFloodMiddleware", exc)
        return await handler(event, data)


# =============================================================================
#  ГЛОБАЛЬНЫЙ ERROR HANDLER (aiogram 3.x)
# =============================================================================
# Ловит ЛЮБОЕ необработанное исключение в хендлерах, логирует traceback
# и (по возможности) отвечает пользователю. Бот не падает.
# =============================================================================

async def on_error(event: ErrorEvent) -> bool:
    try:
        log.error(
            "НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ: %s: %s\n%s",
            type(event.exception).__name__,
            event.exception,
            "".join(traceback.format_exception(
                type(event.exception), event.exception, event.exception.__traceback__,
            )),
        )
        upd = event.update
        # Пытаемся сообщить пользователю в приватном чате / ответить на cb.
        chat_id: Optional[int] = None
        msg_id: Optional[int] = None

        if upd.message:
            chat_id = upd.message.chat.id
            msg_id = upd.message.message_id
        elif upd.callback_query and upd.callback_query.message:
            chat_id = upd.callback_query.message.chat.id
            msg_id = upd.callback_query.message.message_id
            try:
                await upd.callback_query.answer()
            except Exception:
                pass

        if chat_id is not None:
            try:
                await safe_send(chat_id, "⚠️ Внутренняя ошибка. Админ уже уведомлён.")
            except Exception:
                pass

        # Уведомим админа.
        try:
            await safe_send(
                int(ENV.admin_id),
                f"⚠️ <b>Ошибка в боте</b>\n\n"
                f"<code>{html_escape(type(event.exception).__name__)}</code>: "
                f"<code>{html_escape(str(event.exception))[:500]}</code>",
            )
        except Exception:
            pass
        return True
    except Exception as exc:
        log_exception("on_error", exc)
        return True


# =============================================================================
#  ФОНОВЫЕ ЗАДАЧИ (APScheduler)
# =============================================================================

# Глобальный экземпляр шедулера.
SCHEDULER: AsyncIOScheduler = AsyncIOScheduler(timezone="UTC")


async def job_auto_drop() -> None:
    """
    Каждые 2 часа: для каждого event_chat создаёт дроп-сообщение с кнопкой
    «Забрать». Сумма — случайная в [AUTO_DROP_MIN_AMOUNT, AUTO_DROP_MAX_AMOUNT].
    Пропускает, если бот не может писать в чат.
    """
    try:
        chats = await get_event_chats()
        if not chats:
            log.info("job_auto_drop: нет ивент-чатов")
            return
        for chat_id in chats:
            try:
                amount = random.randint(AUTO_DROP_MIN_AMOUNT, AUTO_DROP_MAX_AMOUNT)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"🎁 Забрать {format_money(amount)} TOKENS",
                        callback_data=f"drop:grab:{amount}",
                    )],
                ])
                sent = await safe_send(
                    chat_id,
                    f"🎁 <b>АВТО-ДРОП!</b>\n\n"
                    f"Кто первый нажмёт — получит <b>{format_money(amount)}</b> TOKENS!",
                    markup=kb,
                )
                if sent is None:
                    continue
                await create_bonus_item(chat_id, sent.message_id, amount)
                log.info("job_auto_drop: chat=%s amount=%s", chat_id, amount)
                await asyncio.sleep(FLOOD_SLEEP)
            except Exception as exc:
                log_exception(f"job_auto_drop:chat={chat_id}", exc)
        await log_admin_action(0, "auto_drop", f"chats={len(chats)}")
    except Exception as exc:
        log_exception("job_auto_drop", exc)


async def job_cleanup() -> None:
    """Раз в сутки: чистит старые логи и устаревшие записи в памяти."""
    try:
        deleted = await cleanup_old_logs(days=7)
        # Чистим in-memory сессии рулетки, которые подвисли.
        now = time.monotonic()
        for chat_id in list(ROULETTE_SESSIONS.keys()):
            s = ROULETTE_SESSIONS[chat_id]
            if now - float(s.get("created_at", now)) > 3600:
                _roulette_cancel_timer(s)
                ROULETTE_SESSIONS.pop(chat_id, None)
        # Чистим зависшие мины.
        for gid in list(MINES_STORE.keys()):
            g = MINES_STORE[gid]
            if now - float(g.get("started_at", now)) > 1800 and g.get("active"):
                g["active"] = False
                _game_lock_release(int(g["user_id"]))
                MINES_STORE.pop(gid, None)
        # Чистим зависшие дуэли.
        for duel_id in list(ACTIVE_DUELS.keys()):
            d = ACTIVE_DUELS[duel_id]
            if now - float(d.get("created_at", now)) > DUEL_TIMEOUT_SEC * 2:
                ACTIVE_DUELS.pop(duel_id, None)
        # Чистим in-flight lock-и старше 5 минут.
        cutoff = time.monotonic() - 300
        for uid in list(INFLIGHT_LOCKS.keys()):
            if INFLIGHT_LOCKS[uid] < cutoff:
                INFLIGHT_LOCKS.pop(uid, None)
        for uid in list(ACTIVE_GAME_LOCKS.keys()):
            # Если lock держится > 10 мин — релизим.
            # (в норме игра занимает секунды).
            # Храним время не отдельно, поэтому просто чистим "старые" по
            # общему принципу: если нет активной игры в MINES_STORE/duel —
            # снимаем.
            pass

        await log_admin_action(0, "cleanup", f"deleted={deleted}")
        log.info("job_cleanup: %s", deleted)
    except Exception as exc:
        log_exception("job_cleanup", exc)


async def job_jackpot() -> None:
    """
    Раз в час: объявляет «Джекпот часа».
    Пул растёт от проигрышей в рулетке (мы добавляем 1% в jackpot_add).
    Если пул < 1000 — не объявляем.
    Победитель: случайный не забаненный юзер с балансом > 0.
    """
    try:
        pool = jackpot_get()
        if pool < 1000:
            log.info("job_jackpot: пул слишком мал (%s)", pool)
            return
        rows = await fetchall(
            "SELECT user_id FROM users WHERE banned = 0 AND balance > 0",
        )
        if not rows:
            return
        winner = int(random.choice(rows)["user_id"])
        amount = await jackpot_reset()
        await add_balance(winner, amount, ensure=False)
        await log_admin_action(0, "jackpot",
                               f"winner={winner} amount={amount}")
        log.info("job_jackpot: winner=%s amount=%s", winner, amount)
        # Уведомляем победителя и ивент-чаты.
        await safe_send(
            winner,
            f"💎 <b>ДЖЕКПОТ ЧАСА!</b>\n\n"
            f"Ты выиграл джекпот: <b>+{format_money(amount)} TOKENS</b>! 🎉",
        )
        for chat_id in await get_event_chats():
            try:
                await safe_send(
                    chat_id,
                    f"💎 <b>ДЖЕКПОТ ЧАСА</b>\n\n"
                    f"🏆 Победитель: {mention_html(winner, f'id{winner}')}\n"
                    f"💰 Сумма: <b>{format_money(amount)}</b> TOKENS",
                )
                await asyncio.sleep(FLOOD_SLEEP)
            except Exception:
                continue
    except Exception as exc:
        log_exception("job_jackpot", exc)


async def job_remind_inactive() -> None:
    """Раз в неделю: напоминание неактивным игрокам."""
    try:
        users = await get_inactive_users(days=INACTIVE_REMIND_DAYS, limit=100)
        sent = 0
        for uid in users:
            try:
                msg = await safe_send(
                    uid,
                    "👋 Давно тебя не было!\n\n"
                    "🎁 Забери ежедневный бонус и сыграй в рулетку — "
                    "джекпот уже копится! 💎",
                )
                if msg is not None:
                    sent += 1
                await asyncio.sleep(FLOOD_SLEEP)
            except Exception:
                continue
        await log_admin_action(0, "remind_inactive", f"sent={sent}")
        log.info("job_remind_inactive: sent=%s", sent)
    except Exception as exc:
        log_exception("job_remind_inactive", exc)


def _on_scheduler_event(event) -> None:
    """Логирование событий APScheduler."""
    try:
        if event.exception:
            log.error("Scheduler job %s упал: %s",
                      event.job_id, event.exception)
        else:
            log.debug("Scheduler job %s выполнен", event.job_id)
    except Exception:
        pass


def setup_scheduler() -> None:
    """Регистрирует все фоновые задачи."""
    SCHEDULER.add_listener(_on_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # Автодроп каждые 2 часа.
    SCHEDULER.add_job(
        job_auto_drop, IntervalTrigger(hours=AUTO_DROP_INTERVAL_HOURS),
        id="auto_drop", replace_existing=True, max_instances=1,
    )
    # Очистка раз в сутки (в 03:00 UTC).
    SCHEDULER.add_job(
        job_cleanup, CronTrigger(hour=3, minute=0),
        id="cleanup", replace_existing=True, max_instances=1,
    )
    # Джекпот каждый час.
    SCHEDULER.add_job(
        job_jackpot, IntervalTrigger(hours=JACKPOT_INTERVAL_HOURS),
        id="jackpot", replace_existing=True, max_instances=1,
    )
    # Напоминания неактивным — раз в неделю (понедельник 12:00 UTC).
    SCHEDULER.add_job(
        job_remind_inactive, CronTrigger(day_of_week="mon", hour=12, minute=0),
        id="remind", replace_existing=True, max_instances=1,
    )
    log.info("setup_scheduler: зарегистрировано %d задач", len(SCHEDULER.get_jobs()))


# =============================================================================
#  AIOHTTP ВЕБ-СЕРВЕР (healthcheck для Render)
# =============================================================================
# Render ожидает, что сервис слушает $PORT. Отдаём /health 200 OK.
# Сервер поднимается ДО polling — критично для прохождения health check.
# =============================================================================

_HTTP_RUNNER: Optional[web.AppRunner] = None


async def handle_health(request: web.Request) -> web.Response:
    """Health-check endpoint."""
    try:
        stats = {
            "status": "ok",
            "bot": BOT_NAME,
            "version": BOT_VERSION,
            "time": utcnow_iso(),
            "db_ready": _DB_READY,
            "scheduler_jobs": len(SCHEDULER.get_jobs()) if SCHEDULER.running else 0,
        }
        return web.json_response(stats)
    except Exception as exc:
        log_exception("handle_health", exc)
        return web.json_response({"status": "error"}, status=500)


async def handle_root(request: web.Request) -> web.Response:
    """Корневой endpoint — просто текст."""
    return web.Response(
        text=f"{BOT_NAME} v{BOT_VERSION} — running. See /health.",
        content_type="text/plain",
    )


async def start_web_server(port: int) -> web.AppRunner:
    """
    Запускает aiohttp.Application на 0.0.0.0:port.
    Возвращает runner (для stop()).
    """
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("Веб-сервер запущен на 0.0.0.0:%s", port)
    return runner


# =============================================================================
#  MAIN — ТОЧКА ВХОДА
# =============================================================================

# Глобальные ссылки для graceful shutdown.
_BOT_INSTANCE: Optional[Bot] = None
_DP_INSTANCE: Optional[Dispatcher] = None
_STOP_EVENT: asyncio.Event = asyncio.Event()


def _install_signal_handlers() -> None:
    """
    Ставит обработчики SIGTERM/SIGINT для корректного завершения.
    Render при рестарте шлёт SIGTERM — мы должны освободить ресурсы.
    """
    import signal

    def _handler(signame: str) -> None:
        log.warning("Получен сигнал %s — останавливаюсь", signame)
        _STOP_EVENT.set()

    try:
        loop = asyncio.get_event_loop()
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, _handler, sig_name)
                except (NotImplementedError, RuntimeError):
                    # Windows / не-main-loop — пропускаем.
                    pass
    except Exception as exc:
        log_exception("_install_signal_handlers", exc)


async def _shutdown(reason: str = "manual") -> None:
    """Корректное завершение: снимаем polling, гасим шедулер, БД, веб."""
    log.warning("=== ОСТАНОВКА (%s) ===", reason)
    global _HTTP_RUNNER

    if _DP_INSTANCE is not None:
        try:
            await _DP_INSTANCE.stop_polling()
        except Exception as exc:
            log_exception("shutdown:stop_polling", exc)

    try:
        if SCHEDULER.running:
            SCHEDULER.shutdown(wait=False)
    except Exception as exc:
        log_exception("shutdown:scheduler", exc)

    if _HTTP_RUNNER is not None:
        try:
            await _HTTP_RUNNER.cleanup()
        except Exception as exc:
            log_exception("shutdown:http", exc)

    if _BOT_INSTANCE is not None:
        try:
            await _BOT_INSTANCE.session.close()
        except Exception:
            pass

    try:
        await close_db()
    except Exception as exc:
        log_exception("shutdown:db", exc)

    log.warning("=== ОСТАНОВЛЕНО ===")


def _build_dispatcher() -> Dispatcher:
    """
    Собирает Dispatcher: подключает роутеры и мидлвари.
    Порядок регистрации определяет приоритет обработки.
    """
    dp = Dispatcher(storage=MemoryStorage())

    # Антифлуд — на message и callback_query.
    antiflood = AntiFloodMiddleware()
    dp.message.middleware(antiflood)
    dp.callback_query.middleware(antiflood)

    # Роутеры: сначала более специфичные (админка → игры → меню).
    # Порядок важен: @-команды не должны пересекаться с обычными командами.
    dp.include_router(admin_router)
    dp.include_router(dice_router)
    dp.include_router(extra_games_router)
    dp.include_router(roulette_router)
    dp.include_router(menu_router)

    # Глобальный error handler.
    dp.errors.register(on_error)

    return dp


async def _set_bot_commands(bot: Bot) -> None:
    """
    Устанавливает список команд в меню Telegram.
    Не критично для работы, но улучшает UX.
    """
    try:
        # В ЛС.
        await bot.set_my_commands(
            commands=[
                BotCommand(command="start",    description="🚀 Запустить бота"),
                BotCommand(command="profile",  description="👤 Мой профиль"),
                BotCommand(command="balance",  description="💰 Баланс"),
                BotCommand(command="bonus",    description="🎁 Ежедневный бонус"),
                BotCommand(command="top",      description="🏆 Топ игроков"),
                BotCommand(command="кости",    description="🎲 Кости"),
                BotCommand(command="дартс",    description="🎯 Дартс"),
                BotCommand(command="баскет",   description="🏀 Баскет"),
                BotCommand(command="футбол",   description="⚽ Футбол"),
                BotCommand(command="боулинг",  description="🎳 Боулинг"),
                BotCommand(command="слоты",    description="🎰 Слоты"),
                BotCommand(command="мины",     description="💣 Мины"),
                BotCommand(command="дуэль",    description="⚔️ Дуэль"),
                BotCommand(command="старт",    description="🎡 Рулетка"),
                BotCommand(command="перевод",  description="💸 Перевод"),
                BotCommand(command="подарок",  description="🎁 Подарок"),
            ],
            scope=BotCommandScopeAllPrivateChats(),
        )
        # В группах.
        await bot.set_my_commands(
            commands=[
                BotCommand(command="кости",    description="🎲 Кости"),
                BotCommand(command="дартс",    description="🎯 Дартс"),
                BotCommand(command="баскет",   description="🏀 Баскет"),
                BotCommand(command="футбол",   description="⚽ Футбол"),
                BotCommand(command="боулинг",  description="🎳 Боулинг"),
                BotCommand(command="слоты",    description="🎰 Слоты"),
                BotCommand(command="мины",     description="💣 Мины"),
                BotCommand(command="дуэль",    description="⚔️ Дуэль"),
                BotCommand(command="старт",    description="🎡 Рулетка"),
                BotCommand(command="balance",  description="💰 Баланс"),
                BotCommand(command="top",      description="🏆 Топ"),
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception as exc:
        log_exception("_set_bot_commands", exc)


async def main() -> None:
    """
    Главный сценарий запуска:
      1. purge_old_database() — удаляем старую БД (требование Render).
      2. init_db() — создаём схему.
      3. Bot + Dispatcher + роутеры.
      4. set_bot() — регистрируем Bot для UI-хелперов.
      5. APScheduler — старт фоновых задач.
      6. aiohttp web-сервер — ДО polling (healthcheck).
      7. set_my_commands — меню команд.
      8. start_polling — основной цикл.
      9. graceful shutdown.
    """
    global _BOT_INSTANCE, _DP_INSTANCE, _HTTP_RUNNER

    log.warning("=== ЗАПУСК %s v%s ===", BOT_NAME, BOT_VERSION)

    # 1. Удаляем старую БД (свежий старт на каждом деплое — по ТЗ).
    purge_old_database()

    # 2. Инициализируем БД и схему.
    try:
        await init_db()
    except Exception as exc:
        log_exception("main:init_db", exc)
        raise

    # 3. Bot + Dispatcher.
    bot = Bot(
        token=ENV.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _BOT_INSTANCE = bot
    set_bot(bot)  # для safe_send/safe_edit и др.

    dp = _build_dispatcher()
    _DP_INSTANCE = dp

    # 4. Проверим, что бот жив (get_me).
    try:
        me = await bot.get_me()
        log.info("Бот авторизован: @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError as exc:
        log_exception("main:get_me", exc)
        await close_db()
        raise
    except TelegramAPIError as exc:
        # Не критично — Render сам перезапустит при падении сети.
        log_exception("main:get_me", exc)

    # 5. APScheduler.
    try:
        setup_scheduler()
        SCHEDULER.start()
        log.info("APScheduler запущен (%d задач)", len(SCHEDULER.get_jobs()))
    except Exception as exc:
        log_exception("main:scheduler_start", exc)

    # 6. Веб-сервер — ДО start_polling (healthcheck!).
    try:
        _HTTP_RUNNER = await start_web_server(ENV.port)
    except Exception as exc:
        log_exception("main:web", exc)
        # Если порт занят — логируем, но продолжаем (Render сам разберётся).

    # 7. Команды.
    await _set_bot_commands(bot)

    # Обработчики сигналов.
    _install_signal_handlers()

    # 8. Polling.
    try:
        # drop_pending_updates=False — не теряем сообщения при рестарте.
        await dp.start_polling(bot, drop_pending_updates=False)
    except TelegramConflictError as exc:
        # Кто-то ещё запустил бота с тем же токеном.
        log_exception("main:polling_conflict", exc)
    except Exception as exc:
        log_exception("main:polling", exc)
    finally:
        # 9. Shutdown.
        await _shutdown("polling_finished")


# =============================================================================
#  ТОЧКА ВХОДА
# =============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("KeyboardInterrupt — выход")
    except Exception as exc:
        log_exception("__main__", exc)
        sys.exit(1)