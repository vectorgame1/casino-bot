# =============================================================================
#  TOKENS BOT — SELF-DRIVING GAMBLING ECOSYSTEM
#  Файл: bot.py
#  Python: 3.13
#  Платформа: Render (Web Service + aiohttp healthcheck)
#  Автор: Principal Software Engineer (FAANG-grade)
# -----------------------------------------------------------------------------
#  ЧАСТЬ 1 / 10
#  Содержание:
#    1. Импорты (stdlib + сторонние)
#    2. Глобальные константы (пути, лимиты, тайминги, экономика)
#    3. Логирование (файл + консоль, ротация)
#    4. Удаление старой БД при старте (требование Render)
#    5. Инициализация окружения / переменных
#    6. Текстовые константы (в т.ч. фразы нейро-общения, авто-реакции)
#    7. Глобальные in-memory структуры (локи, антиспам, кэши)
#    8. Заготовки глобальных объектов (bot, dp, scheduler) — без запуска
# =============================================================================

from __future__ import annotations

# --- Стандартная библиотека ------------------------------------------------
import os
import sys
import re
import io
import json
import time
import math
import random
import asyncio
import logging
import logging.handlers
import traceback
import contextlib
import datetime as dt
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
from pathlib import Path
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# --- Сторонние библиотеки --------------------------------------------------
# Все импорты обёрнуты в try/except, чтобы при отсутствии зависимости
# мы могли дать понятную ошибку в лог, а не молча упасть в трейсбеке.
try:
    import aiosqlite  # type: ignore
except Exception as _e:  # pragma: no cover
    print(f"[FATAL] aiosqlite не установлен: {_e}", file=sys.stderr)
    raise

try:
    from aiohttp import web  # type: ignore
except Exception as _e:  # pragma: no cover
    print(f"[FATAL] aiohttp не установлен: {_e}", file=sys.stderr)
    raise

try:
    from aiogram import Bot, Dispatcher, F, Router  # type: ignore
    from aiogram.client.default import DefaultBotProperties  # type: ignore
    from aiogram.enums import ParseMode, ChatType  # type: ignore
    from aiogram.filters import Command, CommandStart, StateFilter  # type: ignore
    from aiogram.fsm.context import FSMContext  # type: ignore
    from aiogram.fsm.state import State, StatesGroup  # type: ignore
    from aiogram.fsm.storage.memory import MemoryStorage  # type: ignore
    from aiogram.types import (  # type: ignore
        Message,
        CallbackQuery,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        ReplyKeyboardMarkup,
        KeyboardButton,
        ReplyKeyboardRemove,
        FSInputFile,
        BufferedInputFile,
        User as TgUser,
        Chat as TgChat,
        Update,
        BotCommand,
        BotCommandScopeDefault,
    )
    from aiogram.exceptions import (  # type: ignore
        TelegramAPIError,
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
        TelegramNetworkError,
        TelegramServerError,
        TelegramUnauthorizedError,
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder  # type: ignore
    from aiogram.utils.text_decorations import html_decoration, markdown_decoration  # type: ignore
except Exception as _e:  # pragma: no cover
    print(f"[FATAL] aiogram не установлен: {_e}", file=sys.stderr)
    raise

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
    from apscheduler.triggers.interval import IntervalTrigger  # type: ignore
    from apscheduler.triggers.cron import CronTrigger  # type: ignore
except Exception as _e:  # pragma: no cover
    print(f"[FATAL] apscheduler не установлен: {_e}", file=sys.stderr)
    raise


# =============================================================================
#  1. ГЛОБАЛЬНЫЕ КОНСТАНТЫ
# =============================================================================

# --- Версия и метаданные ---------------------------------------------------
BOT_NAME: str = "TOKENS"
BOT_VERSION: str = "1.0.0"
BOT_BUILD: str = "self-driving-ecosystem"

# --- Пути ------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
LOGS_DIR: Path = BASE_DIR / "logs"

# ВАЖНО (Render): старая БД удаляется при старте — требование задачи.
DB_PATH: str = str(DATA_DIR / "tokens.db")
LOG_FILE: str = str(LOGS_DIR / "bot.log")
ERROR_LOG_FILE: str = str(LOGS_DIR / "errors.log")

# --- Переменные окружения --------------------------------------------------
# На Render задаются в Environment. Здесь — безопасные дефолты для локалки.
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "").strip()
# PORT обязан быть у Render; локально — 10000.
PORT: int = int(os.environ.get("PORT", "10000"))
# ID админов: список через запятую. Первый — "главный".
_ADMIN_IDS_RAW: str = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS: List[int] = []
if _ADMIN_IDS_RAW:
    for _part in _ADMIN_IDS_RAW.replace(";", ",").split(","):
        _part = _part.strip()
        if _part.isdigit():
            ADMIN_IDS.append(int(_part))
MAIN_ADMIN_ID: int = ADMIN_IDS[0] if ADMIN_IDS else 0

# Канал для логов/уведомлений (опционально)
LOG_CHANNEL_ID: int = int(os.environ.get("LOG_CHANNEL_ID", "0") or "0")

# --- Лимиты Telegram -------------------------------------------------------
TG_MAX_TEXT: int = 4096           # жёсткий лимит сообщения
TG_SAFE_TEXT: int = 4000          # наш безопасный лимит перед chunk_text
TG_MAX_CALLBACK_DATA: int = 64    # байт
TG_MAX_CAPTION: int = 1024        # подпись к медиа

# --- Тайминги (секунды) ----------------------------------------------------
ANTISPAM_GAME_SEC: int = 3        # антиспам на игры
ANTISPAM_CALLBACK_SEC: int = 1    # антиспам на callback-кнопки
AUTODELETE_DEFAULT_SEC: int = 90  # автоудаление игровых сообщений
AUTODELETE_SHORT_SEC: int = 30    # автоудаление коротких техничек
AUTODELETE_LONG_SEC: int = 180    # автоудаление результатов
HEALTHCHECK_TIMEOUT_SEC: int = 5

# --- Экономика -------------------------------------------------------------
START_BALANCE: int = 10_000          # стартовый баланс новичка
MIN_BET: int = 100                   # минимальная ставка
MAX_BET: int = 1_000_000             # максимальная ставка
DAILY_BONUS_BASE: int = 5_000        # базовый дейлик
REFERRAL_BONUS: int = 10_000         # за друга (после его первой игры)
REFERRAL_REQUIRED_BETS: int = 1      # сколько игр должен сделать реферал
JACKPOT_PERCENT: float = 0.01        # 1% от проигрышей в пул
BURN_COMMISSION_BASE: float = 0.05   # 5% комиссия в играх (базовая)
VIP_BONUS_PERCENT: float = 0.05      # +5% к выигрышу для VIP
DONATE_RATE: int = 7500              # 7500 TOKENS за 1 условную единицу доната

# Ставки рулетки (множители)
ROULETTE_PAYOUTS: Dict[str, float] = {
    "red": 2.0,       # красное
    "black": 2.0,     # чёрное
    "even": 2.0,      # чёт
    "odd": 2.0,       # нечёт
    "low": 2.0,       # 0-18
    "high": 2.0,      # 19-36
    "dozen1": 3.0,    # 1-12
    "dozen2": 3.0,    # 13-24
    "dozen3": 3.0,    # 25-36
    "column1": 3.0,
    "column2": 3.0,
    "column3": 3.0,
    "exact": 36.0,    # точное число
}

# Красные числа европейской рулетки (0 — зелёный)
ROULETTE_RED: Set[int] = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BLACK: Set[int] = set(range(1, 37)) - ROULETTE_RED

# --- Турниры / ивенты ------------------------------------------------------
TOURNAMENT_INTERVAL_HOURS: int = 6     # раз в 6 часов авто-турнир
TOURNAMENT_DURATION_MIN: int = 30      # длительность лобби
JACKPOT_CHECK_MIN: int = 60            # проверка пула раз в час
JACKPOT_FORCE_THRESHOLD: int = 5_000_000  # порог принудительного джекпота
NEURO_IDLE_MIN: int = 90               # через сколько минут тишины бот пишет сам
NEURO_IDLE_MAX: int = 180
RANDOM_EVENT_MIN: int = 60             # случайные ивенты раз в 1-2 часа
RANDOM_EVENT_MAX: int = 120
ECONOMY_REGULATOR_HOURS: int = 24      # раз в сутки регулятор экономики
SLEEPING_USER_DAYS: int = 3            # реанимация спящих
SLEEPING_REVIVE_BONUS: int = 5_000     # бонус для возврата

# --- Квесты ----------------------------------------------------------------
DAILY_QUEST_COUNT: int = 3             # сколько квестов в день
QUEST_TYPES: Tuple[str, ...] = (
    "win_games",       # выиграть N игр
    "place_bets",      # поставить N монет
    "play_roulette",   # сыграть в рулетку N раз
    "win_roulette",    # выиграть в рулетку N раз
    "play_mines",      # сыграть в мины N раз
)

# --- Сезонные ивенты -------------------------------------------------------
# (месяц, день) -> (название, эмодзи, множитель)
SEASONAL_EVENTS: Dict[Tuple[int, int], Tuple[str, str, float]] = {
    (1, 1):   ("Новый год", "🎄", 2.0),
    (1, 7):   ("Рождество", "🎁", 1.5),
    (2, 14):  ("День всех влюблённых", "💘", 1.5),
    (3, 8):   ("8 марта", "🌷", 1.5),
    (4, 1):   ("День смеха", "🤡", 1.5),
    (5, 1):   ("Первое мая", "🛠", 1.5),
    (5, 9):   ("День Победы", "🎖", 1.5),
    (10, 31): ("Хэллоуин", "🎃", 2.0),
    (12, 31): ("Новый год", "🎆", 2.0),
}

# --- VIP -------------------------------------------------------------------
VIP_PRICE_TOKENS: int = 100_000        # стоимость VIP в TOKENS

# --- Прочее ----------------------------------------------------------------
PAGE_SIZE: int = 10                    # размер страниц в дашборде
MAX_INLINE_BUTTONS: int = 60           # безопасный лимит кнопок в сообщении
MAX_CALLBACK_CHARS: int = 60           # с запасом под 64 байта

# =============================================================================
#  2. ЛОГИРОВАНИЕ
# =============================================================================
#  Требование: логировать всё в файл и консоль. Ротация по размеру.
#  Отдельный логгер для ошибок, чтобы быстро грепать.

LOGGER_NAME: str = "tokens_bot"
ERROR_LOGGER_NAME: str = "tokens_bot.errors"


def _ensure_dirs() -> None:
    """Создаёт директории data/ и logs/, если их нет."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # Если не смогли создать — падаем максимально громко.
        print(f"[FATAL] Не удалось создать директории: {e}", file=sys.stderr)
        raise


def _build_logging() -> logging.Logger:
    """Настраивает корневой логгер бота: консоль + файл + файл ошибок."""
    _ensure_dirs()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Чистим старые хендлеры (на случай повторной инициализации)
    for h in list(logger.handlers):
        with contextlib.suppress(Exception):
            h.close()
        logger.removeHandler(h)

    fmt_full = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt_console = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- Консоль ---
    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt_console)
    logger.addHandler(ch)

    # --- Файл (ротация) ---
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt_full)
        logger.addHandler(fh)
    except Exception as e:  # pragma: no cover
        print(f"[WARN] Не удалось открыть файл лога {LOG_FILE}: {e}", file=sys.stderr)

    # --- Отдельный логгер ошибок ---
    err_logger = logging.getLogger(ERROR_LOGGER_NAME)
    err_logger.setLevel(logging.ERROR)
    err_logger.propagate = False
    for h in list(err_logger.handlers):
        with contextlib.suppress(Exception):
            h.close()
        err_logger.removeHandler(h)
    try:
        eh = logging.handlers.RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        eh.setLevel(logging.ERROR)
        eh.setFormatter(fmt_full)
        err_logger.addHandler(eh)
    except Exception as e:  # pragma: no cover
        print(f"[WARN] Не удалось открыть файл ошибок {ERROR_LOG_FILE}: {e}", file=sys.stderr)

    # Глушим болтливые логгеры сторонних библиотек
    for noisy in ("aiogram", "aiohttp", "apscheduler", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger


log: logging.Logger = _build_logging()
errlog: logging.Logger = logging.getLogger(ERROR_LOGGER_NAME)


def log_exc(where: str, exc: BaseException) -> None:
    """Единая точка логирования исключений: консоль + файл + errors.log."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error("[%s] %s: %s\n%s", where, type(exc).__name__, exc, tb)
    errlog.error("[%s] %s: %s\n%s", where, type(exc).__name__, exc, tb)


# =============================================================================
#  3. УДАЛЕНИЕ СТАРОЙ БД ПРИ СТАРТЕ (ТРЕБОВАНИЕ RENDER)
# =============================================================================
#  Render даёт эфемерную ФС; при рестарте старый файл нам не нужен.
#  ВАЖНО: делаем это ДО создания соединений с БД.

def purge_old_database() -> None:
    """Удаляет файл БД, если он существует. Вызывать строго до init_db()."""
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            log.info("Старая БД удалена: %s", DB_PATH)
        else:
            log.info("Старой БД нет, начинаем с чистого листа: %s", DB_PATH)
    except Exception as e:
        log_exc("purge_old_database", e)
        # Не роняем процесс: возможно, файл занят — попробуем позже.
        # Но если БД осталась — лучше явно упасть, чтобы не писать в мусор.
        raise


# =============================================================================
#  4. ИНИЦИАЛИЗАЦИЯ ОКРУЖЕНИЯ
# =============================================================================

def validate_env() -> None:
    """Проверяет ключевые переменные окружения перед запуском."""
    if not BOT_TOKEN:
        log.error(
            "BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN "
            "(Render → Environment)."
        )
        # Не raise: дадим healthcheck возможность ответить, но бот не запустим.
    if not ADMIN_IDS:
        log.warning(
            "ADMIN_IDS пуст. Админ-команды будут недоступны. "
            "Формат: ADMIN_IDS=123,456"
        )
    if not (1 <= PORT <= 65535):
        log.error("Некорректный PORT=%s, используем 10000", PORT)


def detect_seasonal_event(now: Optional[dt.datetime] = None) -> Optional[Tuple[str, str, float]]:
    """Возвращает (название, эмодзи, множитель) активного сезонного ивента или None."""
    now = now or dt.datetime.now()
    return SEASONAL_EVENTS.get((now.month, now.day))


def is_seasonal_multiplier_active(now: Optional[dt.datetime] = None) -> float:
    """Множитель сезонного ивента (1.0 — если ивента нет)."""
    ev = detect_seasonal_event(now)
    return ev[2] if ev else 1.0


# =============================================================================
#  5. ТЕКСТОВЫЕ КОНСТАНТЫ
# =============================================================================
#  Здесь собираем все тексты, чтобы не размазывать по хендлерам.
#  Отдельный блок — фразы нейро-общения (псевдо-ИИ).

# --- Общие ---
TXT_LOADING: str = "⏳ Секунду..."
TXT_ERROR: str = "⚠️ Что-то пошло не так. Попробуйте позже."
TXT_CANCELLED: str = "❌ Отменено."
TXT_NOT_ENOUGH: str = "💸 Недостаточно TOKENS."
TXT_INVALID_AMOUNT: str = "🚫 Некорректная сумма."
TXT_INVALID_BET_RANGE: str = f"🚫 Ставка должна быть от {MIN_BET:,} до {MAX_BET:,}."
TXT_ANTISPAM: str = "🐢 Слишком быстро. Подождите секунду."
TXT_REGISTERED: str = "✅ Вы зарегистрированы! Стартовый баланс: {balance:,} TOKENS."

# --- Меню ---
TXT_MENU_MAIN: str = (
    "🎰 <b>TOKENS</b> — казино, которое живёт само.\n\n"
    "Выбирай раздел:"
)
TXT_PROFILE: str = (
    "👤 <b>Профиль</b>\n"
    "├ ID: <code>{user_id}</code>\n"
    "├ Баланс: <b>{balance:,}</b> TOKENS\n"
    "├ VIP: {vip}\n"
    "├ Игр сыграно: {games}\n"
    "├ Побед: {wins}\n"
    "└ Рефералов: {refs}"
)
TXT_DAILY_AVAILABLE: str = "🎁 Ежедневный бонус доступен!"
TXT_DAILY_CLAIMED: str = "✅ Бонус получен: {amount:,} TOKENS."
TXT_DAILY_WAIT: str = "⏳ Бонус будет доступен через {hours} ч {minutes} мин."

# --- Рулетка ---
TXT_ROULETTE_PROMPT: str = (
    "🎡 <b>Рулетка</b>\n"
    "Ставка: <b>{bet:,}</b> TOKENS\n\n"
    "Выбери тип ставки:"
)
TXT_ROULETTE_SPINNING: str = "🎡 Крутим..."
TXT_ROULETTE_RESULT: str = (
    "🎡 Выпало: <b>{number}</b> {color_emoji}\n"
    "{outcome_line}"
)
TXT_ROULETTE_WIN: str = "✅ Выигрыш: <b>+{amount:,}</b> TOKENS"
TXT_ROULETTE_LOSE: str = "❌ Проигрыш: <b>-{amount:,}</b> TOKENS"

# --- Кубики ---
TXT_DICE_PROMPT: str = "🎲 Ставка: <b>{bet:,}</b>\nБросай кубик!"
TXT_DICE_RESULT: str = (
    "🎲 Ваш бросок: <b>{mine}</b>\n"
    "🎲 Бросок казино: <b>{theirs}</b>\n\n"
    "{outcome}"
)
TXT_DICE_WIN: str = "✅ Победа! <b>+{amount:,}</b> TOKENS"
TXT_DICE_LOSE: str = "❌ Поражение. <b>-{amount:,}</b> TOKENS"
TXT_DICE_DRAW: str = "🤝 Ничья. Ставка возвращена."

# --- Мины ---
TXT_MINES_INTRO: str = (
    "💣 <b>Мины 5x5</b>\n"
    "Ставка: <b>{bet:,}</b>\n"
    "Мин: <b>{mines}</b>\n\n"
    "Открывай клетки. С каждой клеткой множитель растёт, но риск — тоже."
)
TXT_MINES_HIT: str = "💥 Мина! Вы потеряли <b>{amount:,}</b> TOKENS."
TXT_MINES_CASHOUT: str = "💰 Забрали: <b>+{amount:,}</b> TOKENS (x{mult:.2f})"

# --- Дуэли ---
TXT_DUEL_PROMPT: str = (
    "⚔️ <b>Дуэль</b>\n"
    "Ставка: <b>{bet:,}</b>\n"
    "Ожидаем соперника... (30 сек)"
)
TXT_DUEL_NO_OPPONENT: str = "😔 Соперник не нашёлся. Ставка возвращена."
TXT_DUEL_WIN: str = "🏆 Победа в дуэли! <b>+{amount:,}</b> TOKENS"
TXT_DUEL_LOSE: str = "💀 Поражение в дуэли. <b>-{amount:,}</b> TOKENS"

# --- Переводы ---
TXT_TRANSFER_PROMPT: str = (
    "💸 <b>Перевод</b>\n"
    "Ответьте на сообщение получателя и укажите сумму.\n"
    "Пример: <code>@перевод 5000</code> (в ответ на сообщение)"
)
TXT_TRANSFER_OK: str = "✅ Переведено <b>{amount:,}</b> TOKENS пользователю {name}."
TXT_TRANSFER_FAIL: str = "🚫 Перевод не выполнен: {reason}"

# --- Рефералка ---
TXT_REF_LINK: str = (
    "🔗 <b>Ваша реферальная ссылка:</b>\n"
    "<code>{link}</code>\n\n"
    "За каждого друга, который сделает первую игру, вы получите "
    "<b>{bonus:,}</b> TOKENS."
)

# --- Админка ---
TXT_ADMIN_ONLY: str = "⛔ Только для администраторов."
TXT_ADMIN_DASHBOARD: str = (
    "🛡 <b>Live-Дашборд</b>\n"
    "├ Онлайн (5 мин): <b>{online}</b>\n"
    "├ Всего юзеров: <b>{users}</b>\n"
    "├ Общий банк: <b>{bank:,}</b> TOKENS\n"
    "├ Джекпот-пул: <b>{jackpot:,}</b>\n"
    "├ Сожжено в играх: <b>{burned:,}</b>\n"
    "└ Выдано (за сутки): <b>{earned:,}</b>"
)

# --- Турниры ---
TXT_TOURNAMENT_START: str = (
    "🏆 <b>Гранд-Турнир!</b>\n"
    "Длительность: <b>{minutes} мин</b>\n"
    "Призовой фонд: <b>{prize:,}</b> TOKENS\n\n"
    "Играйте в рулетку — каждый спин идёт в зачёт. Топ-3 получат призы!"
)
TXT_TOURNAMENT_END: str = (
    "🏁 <b>Турнир завершён!</b>\n\n"
    "🥇 {p1_name}: <b>{p1_score:,}</b> → +{p1_prize:,}\n"
    "🥈 {p2_name}: <b>{p2_score:,}</b> → +{p2_prize:,}\n"
    "🥉 {p3_name}: <b>{p3_score:,}</b> → +{p3_prize:,}"
)

# --- Джекпот ---
TXT_JACKPOT_FORCED: str = (
    "💥 <b>ПРИНУДИТЕЛЬНЫЙ ДЖЕКПОТ!</b>\n"
    "Пул переполнен: <b>{pool:,}</b> TOKENS\n"
    "Победитель: {winner}\n"
    "Выигрыш: <b>{amount:,}</b> TOKENS"
)

# --- Квесты ---
TXT_QUEST_PROGRESS: str = "📜 Квесты на сегодня:\n{lines}"
TXT_QUEST_DONE: str = "✅ Квест выполнен! Награда: <b>+{amount:,}</b> TOKENS"

# --- Промокоды ---
TXT_PROMO_OK: str = "🎟 Промокод активирован: <b>+{amount:,}</b> TOKENS."
TXT_PROMO_USED: str = "🚫 Вы уже использовали этот промокод."
TXT_PROMO_INVALID: str = "🚫 Промокод не найден или истёк."

# --- Экономика ---
TXT_ECONOMY_NOTICE: str = (
    "📊 <i>Экономика шепчет...</i>\n"
    "Комиссия сегодня: <b>{commission:.1f}%</b>"
)

# --- Нейро-общение (псевдо-ИИ) --------------------------------------------
#  Фразы, которые бот пишет сам. Разбиты по контексту.
NEURO_IDLE_PHRASES: Tuple[str, ...] = (
    "Казино не работает, если в него не играть. 🎰",
    "Кто-нибудь здесь? Ау! 💬",
    "Скучно... Может, рулетку? 🎡",
    "Ставки сделаны, господа. Кто смелый? 🃏",
    "Я тут посчитал: сегодня отличный день для крупной ставки. 😏",
    "Тишина в чате... а джекпот-то растёт. 💰",
    "Пока вы молчите, я кручу барабан вхолостую. 🎰",
)
NEURO_BIG_WIN_PHRASES: Tuple[str, ...] = (
    "🐋 КИТ В ЧАТЕ! {name} сорвал <b>{amount:,}</b> TOKENS!",
    "🔥 {name} в ударе! <b>+{amount:,}</b> TOKENS!",
    "💎 {name} только что доказал, что удача существует. <b>+{amount:,}</b>!",
    "🚀 {name} на ракете! <b>+{amount:,}</b> TOKENS!",
)
NEURO_BIG_LOSS_PHRASES: Tuple[str, ...] = (
    "F в чат для {name}... 💀 <b>-{amount:,}</b> TOKENS.",
    "😬 {name}, это было больно. <b>-{amount:,}</b>.",
    "🫡 {name} держится. Потеряно <b>{amount:,}</b>.",
    "💔 {name}, казино сегодня сильнее. <b>-{amount:,}</b>.",
)
NEURO_WIN_STREAK_PHRASES: Tuple[str, ...] = (
    "{name}, ты в ударе! Может, удвоишь? 😏",
    "{name} на серии из {streak}! Кто остановит? 🔥",
    "{name}, удача любит тебя. Не спугни. 🍀",
)
NEURO_RANDOM_EVENT_PHRASES: Tuple[str, ...] = (
    "🎲 Внезапно! Экспресс-рулетка на 10 минут. Кто в деле?",
    "⚡ Гонка вооружений: кто больше поставит за час?",
    "💬 Светская беседа: как ваши дела, господа?",
    "🎁 Бонусный час! Играйте — дропы щедрее.",
)
NEURO_SLEEPING_PUSH: str = (
    "👋 {name}, ты давно не заходил!\n"
    "Возвращайся — тебя ждёт личный бонус: <b>{amount:,}</b> TOKENS."
)

# --- Кнопки (тексты) ---
BTN_MENU: str = "🏠 Меню"
BTN_PROFILE: str = "👤 Профиль"
BTN_ROULETTE: str = "🎡 Рулетка"
BTN_DICE: str = "🎲 Кубики"
BTN_MINES: str = "💣 Мины"
BTN_DUEL: str = "⚔️ Дуэль"
BTN_DAILY: str = "🎁 Бонус"
BTN_TOP: str = "🏆 Топ"
BTN_REF: str = "🔗 Рефералка"
BTN_CANCEL: str = "❌ Отмена"
BTN_BACK: str = "◀️ Назад"

# =============================================================================
#  6. ГЛОБАЛЬНЫЕ IN-MEMORY СТРУКТУРЫ (ЛОКИ, АНТИСПАМ, КЭШИ)
# =============================================================================
#  КРИТИЧНО: защита от double-spend и race conditions в рулетке.
#  Всё в памяти процесса — на Render один инстанс, этого достаточно.

# --- Локи по пользователю (для операций с балансом) ---
_user_locks: Dict[int, asyncio.Lock] = {}
_user_locks_guard = asyncio.Lock()


async def get_user_lock(user_id: int) -> asyncio.Lock:
    """Возвращает per-user Lock, создавая его при необходимости (потокобезопасно)."""
    async with _user_locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock
        return lock


# --- Лок рулетки (глобальный, защищает спин и начисление) ---
roulette_lock = asyncio.Lock()

# --- Лок джекпота ---
jackpot_lock = asyncio.Lock()

# --- Антиспам на игры: user_id -> timestamp ---
_antispam_game: Dict[int, float] = {}
_antispam_game_guard = asyncio.Lock()


async def check_game_antispam(user_id: int) -> bool:
    """
    Возвращает True, если можно играть; False — если ещё рано.
    Обновляет timestamp при успехе.
    """
    now = time.monotonic()
    async with _antispam_game_guard:
        last = _antispam_game.get(user_id, 0.0)
        if now - last < ANTISPAM_GAME_SEC:
            return False
        _antispam_game[user_id] = now
        return True


# --- Антиспам на callback-кнопки ---
_antispam_cb: Dict[int, float] = {}
_antispam_cb_guard = asyncio.Lock()


async def check_cb_antispam(user_id: int) -> bool:
    now = time.monotonic()
    async with _antispam_cb_guard:
        last = _antispam_cb.get(user_id, 0.0)
        if now - last < ANTISPAM_CALLBACK_SEC:
            return False
        _antispam_cb[user_id] = now
        return True


# --- In-memory локи на дуэли (user_id -> "occupied") ---
duel_busy: Set[int] = set()
duel_busy_guard = asyncio.Lock()


# --- Кэш активных турниров (chat_id -> турнир) ---
#  Заполняется в ЧАСТИ 10, но объявляем здесь для единого стиля.
active_tournaments: Dict[int, Dict[str, Any]] = {}

# --- Кэш "последняя активность в чате" для нейро-общения ---
#  chat_id -> monotonic timestamp
chat_last_activity: Dict[int, float] = {}

# --- Кэш "кто последним выиграл" для псевдо-ИИ контекста ---
#  chat_id -> {"user_id": int, "name": str, "amount": int, "ts": float}
chat_last_winner: Dict[int, Dict[str, Any]] = {}

# --- Кэш винстриков (user_id -> {"count": int, "ts": float}) ---
win_streaks: Dict[int, Dict[str, Any]] = {}

# --- Флаг "бот готов" (для healthcheck) ---
BOT_READY: bool = False
BOT_START_TS: float = time.time()


# =============================================================================
#  7. ЗАГОТОВКИ ГЛОБАЛЬНЫХ ОБЪЕКТОВ
# =============================================================================
#  Создаём их здесь, чтобы все части файла видели единые объекты.
#  Реальная инициализация (polling, web) — в ЧАСТИ 10.

# Bot создаётся в main(), но объявляем глобал для доступа из хендлеров.
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
scheduler: Optional[AsyncIOScheduler] = None

# Роутер (aiogram 3.x): все хендлеры регистрируются на нём.
router = Router(name="tokens_main")


def require_bot() -> Bot:
    """Возвращает bot или падает с понятной ошибкой (использовать в хендлерах)."""
    if bot is None:
        raise RuntimeError("Bot не инициализирован — main() ещё не запущен")
    return bot


def require_scheduler() -> AsyncIOScheduler:
    if scheduler is None:
        raise RuntimeError("Scheduler не инициализирован")
    return scheduler


# =============================================================================
#  8. ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ ОБЩЕГО НАЗНАЧЕНИЯ
# =============================================================================
#  Форматирование, парсинг сумм, чанкование текста (пригодится в safe_send).

def fmt_int(n: Union[int, float, Decimal]) -> str:
    """Форматирует число с разделителями тысяч: 1234567 -> '1 234 567'."""
    try:
        if isinstance(n, Decimal):
            n = int(n)
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def parse_amount(raw: str) -> Optional[int]:
    """
    Парсит сумму из строки: '5k' -> 5000, '1.5k' -> 1500, '10 000' -> 10000.
    Возвращает None при ошибке. Отрицательные и нулевые отбрасываются.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(" ", "").replace(",", ".")
    if not s:
        return None
    mult = 1
    if s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]
    try:
        val = Decimal(s) * mult
        val = val.to_integral_value(rounding=ROUND_DOWN)
        iv = int(val)
        if iv <= 0:
            return None
        return iv
    except (InvalidOperation, ValueError):
        return None


def chunk_text(text: str, limit: int = TG_SAFE_TEXT) -> List[str]:
    """
    Режет текст на куски <= limit, стараясь не рвать слова/строки.
    Гарантирует, что каждый кусок не пуст.
    """
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        # Ищем последний перенос строки в пределах лимита
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            # Нет хорошего переноса — режем по пробелу
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            # Совсем плохо — режем жёстко
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def now_ts() -> float:
    """Unix timestamp (float)."""
    return time.time()


def now_dt() -> dt.datetime:
    """Локальное datetime (naive)."""
    return dt.datetime.now()


def utc_now_iso() -> str:
    """UTC ISO-строка для БД."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def days_ago_ts(days: int) -> float:
    return time.time() - days * 86400


def humanize_seconds(sec: int) -> str:
    """'1 ч 5 мин' из секунд."""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    parts: List[str] = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if not parts:
        parts.append(f"{s} сек")
    return " ".join(parts)


def safe_name(user: Optional[TgUser]) -> str:
    """Человекочитаемое имя пользователя для логов/сообщений."""
    if user is None:
        return "unknown"
    if user.username:
        return f"@{user.username}"
    name = " ".join(p for p in [user.first_name or "", user.last_name or ""] if p).strip()
    return name or f"id{user.id}"


def html_escape(text: str) -> str:
    """Экранирование под parse_mode=HTML."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_main_admin(user_id: int) -> bool:
    return MAIN_ADMIN_ID != 0 and user_id == MAIN_ADMIN_ID


# =============================================================================
#  9. ЗАГОТОВКА ДЛЯ ЧАСТИ 2
# =============================================================================
#  Здесь будет create_tables(), get_user(), ensure_user(), add_balance() и т.д.
#  Пока — только маркер, чтобы файл оставался синтаксически валидным.

# (ЧАСТЬ 2 подключится ниже)

# =============================================================================
#  ЧАСТЬ 2 / 10 — БД (часть 1)
#  Содержание:
#    - Подключение к aiosqlite (единый пул через per-call connect + WAL)
#    - create_tables() — все базовые + расширенные таблицы
#    - Индексы, PRAGMA, миграции-идемпотентные
#    - get_user(), ensure_user(), update_user()
#    - add_balance(), try_withdraw() — атомарные операции
#    - log_game(), log_roulette()
#    - Внутренние хелперы: _connect(), _execute(), _fetchone(), _fetchall()
#  ВАЖНО: слово "drop" в SQL запрещено. Только purge/delete/clear.
# =============================================================================

# --- Путь к БД уже определён в ЧАСТИ 1 (DB_PATH) ---------------------------

# Таймаут ожидания блокировки SQLite (сек). WAL + busy_timeout.
_SQLITE_BUSY_TIMEOUT_MS: int = 5000


async def _connect() -> aiosqlite.Connection:
    """
    Открывает соединение с БД с оптимальными PRAGMA.
    Используем per-call connect: для нагрузки нашего бота этого достаточно,
    а aiosqlite сам сериализует запросы в рамках соединения.
    WAL даёт параллельные чтения во время записи.
    """
    conn = await aiosqlite.connect(DB_PATH, timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = aiosqlite.Row
    # PRAGMA: производительность + целостность
    with contextlib.suppress(Exception):
        await conn.execute("PRAGMA journal_mode=WAL")
    with contextlib.suppress(Exception):
        await conn.execute("PRAGMA synchronous=NORMAL")
    with contextlib.suppress(Exception):
        await conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    with contextlib.suppress(Exception):
        await conn.execute("PRAGMA foreign_keys=ON")
    with contextlib.suppress(Exception):
        await conn.execute("PRAGMA temp_store=MEMORY")
    return conn


@contextlib.asynccontextmanager
async def db_conn():
    """
    Контекстный менеджер: открывает соединение, коммитит при успехе,
    откатывает при исключении, всегда закрывает.
    """
    conn = await _connect()
    try:
        yield conn
        await conn.commit()
    except Exception as e:
        with contextlib.suppress(Exception):
            await conn.rollback()
        log_exc("db_conn", e)
        raise
    finally:
        with contextlib.suppress(Exception):
            await conn.close()


async def _execute(sql: str, params: Sequence[Any] = ()) -> None:
    """Выполнить один запрос без возврата."""
    async with db_conn() as conn:
        await conn.execute(sql, params)


async def _execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    async with db_conn() as conn:
        await conn.executemany(sql, list(seq))


async def _fetchone(sql: str, params: Sequence[Any] = ()) -> Optional[aiosqlite.Row]:
    async with db_conn() as conn:
        async with conn.execute(sql, params) as cur:
            return await cur.fetchone()


async def _fetchall(sql: str, params: Sequence[Any] = ()) -> List[aiosqlite.Row]:
    async with db_conn() as conn:
        async with conn.execute(sql, params) as cur:
            return list(await cur.fetchall())


async def _fetchval(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    row = await _fetchone(sql, params)
    if row is None:
        return default
    try:
        return row[0]
    except Exception:
        return default


# =============================================================================
#  create_tables() — полная схема
# =============================================================================
#  Все CREATE TABLE IF NOT EXISTS. Никаких "drop". Индексы — отдельно.
#  Таблицы:
#    users, chat_settings, event_chats, roulette_logs, games_log,
#    bonus_items, daily_bonus, promo_codes, promo_used, admin_logs,
#    tournaments, tournament_scores, quests, quest_templates,
#    bot_activity_log, economy_analytics, transactions, referrals,
#    win_streaks_log, jackpot_pool, jackpot_wins, seasonal_state
# =============================================================================

_CREATE_SQL: Tuple[str, ...] = (
    # --- Пользователи ---
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id         INTEGER PRIMARY KEY,
        username        TEXT,
        first_name      TEXT,
        last_name       TEXT,
        balance         INTEGER NOT NULL DEFAULT 0,
        vip             INTEGER NOT NULL DEFAULT 0,
        is_banned       INTEGER NOT NULL DEFAULT 0,
        games_played    INTEGER NOT NULL DEFAULT 0,
        games_won       INTEGER NOT NULL DEFAULT 0,
        total_bet       INTEGER NOT NULL DEFAULT 0,
        total_won       INTEGER NOT NULL DEFAULT 0,
        total_lost      INTEGER NOT NULL DEFAULT 0,
        referral_by     INTEGER,
        referral_count  INTEGER NOT NULL DEFAULT 0,
        referral_paid   INTEGER NOT NULL DEFAULT 0,
        last_seen       REAL NOT NULL DEFAULT 0,
        last_daily      REAL NOT NULL DEFAULT 0,
        last_revive     REAL NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Настройки чатов ---
    """
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id         INTEGER PRIMARY KEY,
        title           TEXT,
        casino_enabled  INTEGER NOT NULL DEFAULT 1,
        neuro_enabled   INTEGER NOT NULL DEFAULT 1,
        events_enabled  INTEGER NOT NULL DEFAULT 1,
        commission      REAL NOT NULL DEFAULT 0.05,
        updated_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Чаты, где бот инициирует ивенты (event_chats) ---
    """
    CREATE TABLE IF NOT EXISTS event_chats (
        chat_id         INTEGER PRIMARY KEY,
        title           TEXT,
        added_by        INTEGER,
        last_event_at   REAL NOT NULL DEFAULT 0,
        events_count    INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Логи рулетки (для турниров/аналитики) ---
    """
    CREATE TABLE IF NOT EXISTS roulette_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        chat_id         INTEGER,
        bet             INTEGER NOT NULL,
        bet_type        TEXT NOT NULL,
        bet_value       TEXT,
        number          INTEGER NOT NULL,
        won             INTEGER NOT NULL,
        payout          INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Общий лог игр ---
    """
    CREATE TABLE IF NOT EXISTS games_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        chat_id         INTEGER,
        game            TEXT NOT NULL,
        bet             INTEGER NOT NULL,
        result          TEXT NOT NULL,
        delta           INTEGER NOT NULL,
        meta            TEXT,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Бонусные предметы (инвентарь) ---
    """
    CREATE TABLE IF NOT EXISTS bonus_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        item_type       TEXT NOT NULL,
        item_value      INTEGER NOT NULL DEFAULT 0,
        used            INTEGER NOT NULL DEFAULT 0,
        expires_at      REAL NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Дейлики ---
    """
    CREATE TABLE IF NOT EXISTS daily_bonus (
        user_id         INTEGER PRIMARY KEY,
        streak          INTEGER NOT NULL DEFAULT 0,
        last_claim      REAL NOT NULL DEFAULT 0,
        total_claims    INTEGER NOT NULL DEFAULT 0
    )
    """,
    # --- Промокоды ---
    """
    CREATE TABLE IF NOT EXISTS promo_codes (
        code            TEXT PRIMARY KEY,
        amount          INTEGER NOT NULL,
        max_uses        INTEGER NOT NULL DEFAULT 1,
        uses            INTEGER NOT NULL DEFAULT 0,
        expires_at      REAL NOT NULL DEFAULT 0,
        created_by      INTEGER,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_used (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        code            TEXT NOT NULL,
        user_id         INTEGER NOT NULL,
        used_at         REAL NOT NULL DEFAULT 0,
        UNIQUE(code, user_id)
    )
    """,
    # --- Админ-логи ---
    """
    CREATE TABLE IF NOT EXISTS admin_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id        INTEGER NOT NULL,
        action          TEXT NOT NULL,
        target_id       INTEGER,
        details         TEXT,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Турниры ---
    """
    CREATE TABLE IF NOT EXISTS tournaments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER NOT NULL,
        start_time      REAL NOT NULL DEFAULT 0,
        end_time        REAL NOT NULL DEFAULT 0,
        prize_pool      INTEGER NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'pending',
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_scores (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id   INTEGER NOT NULL,
        user_id         INTEGER NOT NULL,
        score           INTEGER NOT NULL DEFAULT 0,
        updated_at      REAL NOT NULL DEFAULT 0,
        UNIQUE(tournament_id, user_id)
    )
    """,
    # --- Квесты ---
    """
    CREATE TABLE IF NOT EXISTS quests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        quest_id        TEXT NOT NULL,
        progress        INTEGER NOT NULL DEFAULT 0,
        target          INTEGER NOT NULL DEFAULT 0,
        reward          INTEGER NOT NULL DEFAULT 0,
        completed_at    REAL NOT NULL DEFAULT 0,
        claimed         INTEGER NOT NULL DEFAULT 0,
        assigned_at     REAL NOT NULL DEFAULT 0,
        UNIQUE(user_id, quest_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quest_templates (
        quest_id        TEXT PRIMARY KEY,
        quest_type      TEXT NOT NULL,
        title           TEXT NOT NULL,
        target_min      INTEGER NOT NULL,
        target_max      INTEGER NOT NULL,
        reward_min      INTEGER NOT NULL,
        reward_max      INTEGER NOT NULL,
        active          INTEGER NOT NULL DEFAULT 1
    )
    """,
    # --- Лог автономной активности бота ---
    """
    CREATE TABLE IF NOT EXISTS bot_activity_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type     TEXT NOT NULL,
        details         TEXT,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Аналитика экономики ---
    """
    CREATE TABLE IF NOT EXISTS economy_analytics (
        date            TEXT PRIMARY KEY,
        total_burned    INTEGER NOT NULL DEFAULT 0,
        total_earned    INTEGER NOT NULL DEFAULT 0,
        pool_size       INTEGER NOT NULL DEFAULT 0,
        users_active    INTEGER NOT NULL DEFAULT 0,
        commission      REAL NOT NULL DEFAULT 0.05,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Транзакции (аудит баланса) ---
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        amount          INTEGER NOT NULL,
        reason          TEXT NOT NULL,
        balance_after   INTEGER NOT NULL,
        meta            TEXT,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Рефералки ---
    """
    CREATE TABLE IF NOT EXISTS referrals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id     INTEGER NOT NULL,
        referred_id     INTEGER NOT NULL UNIQUE,
        paid            INTEGER NOT NULL DEFAULT 0,
        games_done      INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- История винстриков ---
    """
    CREATE TABLE IF NOT EXISTS win_streaks_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        chat_id         INTEGER,
        streak          INTEGER NOT NULL,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Джекпот-пул ---
    """
    CREATE TABLE IF NOT EXISTS jackpot_pool (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        pool            INTEGER NOT NULL DEFAULT 0,
        total_wins      INTEGER NOT NULL DEFAULT 0,
        last_win_at     REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jackpot_wins (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        chat_id         INTEGER,
        amount          INTEGER NOT NULL,
        pool_before     INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT 0
    )
    """,
    # --- Сезонное состояние ---
    """
    CREATE TABLE IF NOT EXISTS seasonal_state (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        event_key       TEXT,
        multiplier      REAL NOT NULL DEFAULT 1.0,
        updated_at      REAL NOT NULL DEFAULT 0
    )
    """,
)

_CREATE_INDEXES: Tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen)",
    "CREATE INDEX IF NOT EXISTS idx_roulette_user ON roulette_logs(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_roulette_chat ON roulette_logs(chat_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_games_user ON games_log(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_games_game ON games_log(game, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_promo_used_user ON promo_used(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_tourn_status ON tournaments(status, end_time)",
    "CREATE INDEX IF NOT EXISTS idx_tourn_scores ON tournament_scores(tournament_id, score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_quests_user ON quests(user_id, completed_at)",
    "CREATE INDEX IF NOT EXISTS idx_bot_activity_type ON bot_activity_log(action_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id, created_at)",
)


async def create_tables() -> None:
    """
    Идемпотентно создаёт все таблицы и индексы.
    Вызывается один раз при старте (до polling).
    Также сидит дефолтные значения в singleton-таблицы.
    """
    try:
        async with db_conn() as conn:
            for sql in _CREATE_SQL:
                await conn.execute(sql)
            for sql in _CREATE_INDEXES:
                await conn.execute(sql)
            # Singleton: пул джекпота
            await conn.execute(
                "INSERT INTO jackpot_pool (id, pool, total_wins, last_win_at) "
                "VALUES (1, 0, 0, 0) "
                "ON CONFLICT(id) DO NOTHING"
            )
            # Singleton: сезонное состояние
            await conn.execute(
                "INSERT INTO seasonal_state (id, event_key, multiplier, updated_at) "
                "VALUES (1, NULL, 1.0, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (now_ts(),),
            )
        log.info("БД инициализирована: таблицы и индексы готовы")
    except Exception as e:
        log_exc("create_tables", e)
        raise


# =============================================================================
#  USERS: get / ensure / update
# =============================================================================

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает пользователя как dict или None."""
    try:
        row = await _fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(row) if row is not None else None
    except Exception as e:
        log_exc("get_user", e)
        return None


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    start_balance: int = START_BALANCE,
    referral_by: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Гарантирует наличие пользователя. Возвращает актуальный dict.
    - Если новый — создаёт с start_balance.
    - Обновляет username/имена/last_seen.
    - referral_by сохраняется только при создании и только если != user_id.
    Безопасно при гонках (INSERT OR IGNORE + UPDATE).
    """
    try:
        ts = now_ts()
        async with db_conn() as conn:
            # Вставляем, если нет
            await conn.execute(
                "INSERT OR IGNORE INTO users "
                "(user_id, username, first_name, last_name, balance, "
                " created_at, last_seen, referral_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    start_balance,
                    ts,
                    ts,
                    referral_by if (referral_by and referral_by != user_id) else None,
                ),
            )
            # Обновляем «мягкие» поля
            await conn.execute(
                "UPDATE users SET username = COALESCE(?, username), "
                "first_name = COALESCE(?, first_name), "
                "last_name = COALESCE(?, last_name), "
                "last_seen = ? "
                "WHERE user_id = ?",
                (username, first_name, last_name, ts, user_id),
            )
        user = await get_user(user_id)
        if user is None:
            raise RuntimeError(f"ensure_user: пользователь {user_id} не найден после создания")
        return user
    except Exception as e:
        log_exc("ensure_user", e)
        raise


async def update_user(user_id: int, **fields: Any) -> None:
    """
    Точечное обновление разрешённых полей пользователя.
    Белый список — защита от SQL-инъекций через имена полей.
    """
    allowed = {
        "username", "first_name", "last_name", "balance", "vip", "is_banned",
        "games_played", "games_won", "total_bet", "total_won", "total_lost",
        "referral_by", "referral_count", "referral_paid",
        "last_seen", "last_daily", "last_revive",
    }
    sets: List[str] = []
    params: List[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            log.warning("update_user: запрещённое поле '%s'", k)
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return
    params.append(user_id)
    try:
        await _execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", params)
    except Exception as e:
        log_exc("update_user", e)
        raise


# =============================================================================
#  BALANCE: add_balance / try_withdraw — атомарно
# =============================================================================
#  Защита от double-spend:
#    - per-user asyncio.Lock (из ЧАСТИ 1)
#    - атомарный UPDATE ... WHERE balance >= ?
#    - проверка rowcount
# =============================================================================

async def add_balance(
    user_id: int,
    amount: int,
    reason: str,
    meta: Optional[str] = None,
) -> int:
    """
    Начисляет amount (может быть отрицательным для списания-штрафа).
    НЕ уходит в минус: если списание больше баланса — списывает сколько есть.
    Возвращает новый баланс. Логирует транзакцию.
    """
    if amount == 0:
        u = await get_user(user_id)
        return int(u["balance"]) if u else 0
    lock = await get_user_lock(user_id)
    async with lock:
        try:
            async with db_conn() as conn:
                # Атомарное изменение с защитой от отрицательного баланса
                if amount > 0:
                    await conn.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                        (amount, user_id),
                    )
                    delta = amount
                else:
                    # Списание: не больше, чем есть
                    await conn.execute(
                        "UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?",
                        (amount, user_id),
                    )
                    # Узнаём фактическую дельту
                    async with conn.execute(
                        "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                    ) as cur:
                        row = await cur.fetchone()
                    # Дельта вычисляется приблизительно; для точного аудита
                    # смотрим новую транзакцию ниже.
                    delta = amount  # аудит фиксирует запрошенное списание
                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                ) as cur:
                    row = await cur.fetchone()
                new_balance = int(row["balance"]) if row else 0
                await conn.execute(
                    "INSERT INTO transactions "
                    "(user_id, amount, reason, balance_after, meta, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, delta, reason, new_balance, meta, now_ts()),
                )
            return new_balance
        except Exception as e:
            log_exc("add_balance", e)
            raise


async def try_withdraw(
    user_id: int,
    amount: int,
    reason: str,
    meta: Optional[str] = None,
) -> Tuple[bool, int]:
    """
    Пытается списать amount. Возвращает (success, new_balance).
    Атомарно: UPDATE ... WHERE balance >= ?. Если rowcount == 0 — не хватило.
    """
    if amount <= 0:
        u = await get_user(user_id)
        return False, int(u["balance"]) if u else 0
    lock = await get_user_lock(user_id)
    async with lock:
        try:
            async with db_conn() as conn:
                cur = await conn.execute(
                    "UPDATE users SET balance = balance - ? "
                    "WHERE user_id = ? AND balance >= ?",
                    (amount, user_id, amount),
                )
                if cur.rowcount == 0:
                    # Не хватило средств (или юзера нет)
                    async with conn.execute(
                        "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                    ) as c2:
                        r = await c2.fetchone()
                    return False, int(r["balance"]) if r else 0
                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                ) as c3:
                    r = await c3.fetchone()
                new_balance = int(r["balance"]) if r else 0
                await conn.execute(
                    "INSERT INTO transactions "
                    "(user_id, amount, reason, balance_after, meta, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, -amount, reason, new_balance, meta, now_ts()),
                )
            return True, new_balance
        except Exception as e:
            log_exc("try_withdraw", e)
            return False, 0


async def get_balance(user_id: int) -> int:
    """Быстрое чтение баланса."""
    try:
        v = await _fetchval("SELECT balance FROM users WHERE user_id = ?", (user_id,), 0)
        return int(v or 0)
    except Exception as e:
        log_exc("get_balance", e)
        return 0


async def transfer_balance(
    from_id: int,
    to_id: int,
    amount: int,
    reason: str = "transfer",
) -> Tuple[bool, str, int]:
    """
    Атомарный перевод между юзерами с защитой от гонок.
    Возвращает (ok, error_code, new_balance_from).
    Блокировки берём в детерминированном порядке (по возрастанию id),
    чтобы избежать deadlock.
    """
    if amount <= 0:
        return False, "invalid_amount", await get_balance(from_id)
    if from_id == to_id:
        return False, "self_transfer", await get_balance(from_id)
    first, second = sorted((from_id, to_id))
    l1 = await get_user_lock(first)
    l2 = await get_user_lock(second)
    async with l1, l2:
        try:
            async with db_conn() as conn:
                cur = await conn.execute(
                    "UPDATE users SET balance = balance - ? "
                    "WHERE user_id = ? AND balance >= ?",
                    (amount, from_id, amount),
                )
                if cur.rowcount == 0:
                    return False, "not_enough", await get_balance(from_id)
                await conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (amount, to_id),
                )
                async with conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?", (from_id,)
                ) as c:
                    r = await c.fetchone()
                nb = int(r["balance"]) if r else 0
                ts = now_ts()
                await conn.executemany(
                    "INSERT INTO transactions "
                    "(user_id, amount, reason, balance_after, meta, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (from_id, -amount, reason, nb, f"to:{to_id}", ts),
                        (to_id, amount, reason, None, f"from:{from_id}", ts),
                    ],
                )
            return True, "ok", nb
        except Exception as e:
            log_exc("transfer_balance", e)
            return False, "internal", 0


# =============================================================================
#  ЛОГИ ИГР
# =============================================================================

async def log_game(
    user_id: int,
    chat_id: Optional[int],
    game: str,
    bet: int,
    result: str,
    delta: int,
    meta: Optional[str] = None,
) -> None:
    """
    Записывает игру в games_log и обновляет агрегаты пользователя
    (games_played, games_won, total_bet, total_won, total_lost).
    result: 'win' | 'lose' | 'draw'.
    """
    try:
        ts = now_ts()
        async with db_conn() as conn:
            await conn.execute(
                "INSERT INTO games_log "
                "(user_id, chat_id, game, bet, result, delta, meta, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, chat_id, game, bet, result, delta, meta, ts),
            )
            won_inc = 1 if result == "win" else 0
            won_sum = max(0, delta) if result == "win" else 0
            lost_sum = max(0, -delta) if result == "lose" else 0
            await conn.execute(
                "UPDATE users SET "
                "games_played = games_played + 1, "
                "games_won = games_won + ?, "
                "total_bet = total_bet + ?, "
                "total_won = total_won + ?, "
                "total_lost = total_lost + ? "
                "WHERE user_id = ?",
                (won_inc, bet, won_sum, lost_sum, user_id),
            )
    except Exception as e:
        log_exc("log_game", e)


async def log_roulette(
    user_id: int,
    chat_id: Optional[int],
    bet: int,
    bet_type: str,
    bet_value: Optional[str],
    number: int,
    won: bool,
    payout: int,
) -> None:
    """Отдельный лог рулетки — для турнирной статистики и аналитики."""
    try:
        await _execute(
            "INSERT INTO roulette_logs "
            "(user_id, chat_id, bet, bet_type, bet_value, number, won, payout, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, bet, bet_type, bet_value, number, 1 if won else 0, payout, now_ts()),
        )
    except Exception as e:
        log_exc("log_roulette", e)


async def log_transaction(
    user_id: int,
    amount: int,
    reason: str,
    balance_after: Optional[int] = None,
    meta: Optional[str] = None,
) -> None:
    """Ручная запись транзакции (для случаев, когда не через add/withdraw)."""
    try:
        if balance_after is None:
            balance_after = await get_balance(user_id)
        await _execute(
            "INSERT INTO transactions "
            "(user_id, amount, reason, balance_after, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, amount, reason, balance_after, meta, now_ts()),
        )
    except Exception as e:
        log_exc("log_transaction", e)


# =============================================================================
#  ХЕЛПЕРЫ ДЛЯ ОСТАЛЬНЫХ ЧАСТЕЙ (тонкие обёртки, но по делу)
# =============================================================================

async def set_ban(user_id: int, banned: bool) -> None:
    await update_user(user_id, is_banned=1 if banned else 0)


async def is_banned(user_id: int) -> bool:
    try:
        v = await _fetchval("SELECT is_banned FROM users WHERE user_id = ?", (user_id,), 0)
        return bool(int(v or 0))
    except Exception as e:
        log_exc("is_banned", e)
        return False


async def touch_last_seen(user_id: int) -> None:
    """Обновляет last_seen (для реанимации спящих)."""
    with contextlib.suppress(Exception):
        await _execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now_ts(), user_id))


async def count_users() -> int:
    try:
        v = await _fetchval("SELECT COUNT(*) FROM users", (), 0)
        return int(v or 0)
    except Exception as e:
        log_exc("count_users", e)
        return 0


async def total_economy_bank() -> int:
    """Сумма всех балансов — «общий банк экономики»."""
    try:
        v = await _fetchval("SELECT COALESCE(SUM(balance), 0) FROM users", (), 0)
        return int(v or 0)
    except Exception as e:
        log_exc("total_economy_bank", e)
        return 0


async def get_top_users(limit: int = 10) -> List[Dict[str, Any]]:
    """Топ по балансу."""
    try:
        rows = await _fetchall(
            "SELECT user_id, username, first_name, balance, vip, games_played, games_won "
            "FROM users WHERE balance > 0 ORDER BY balance DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("get_top_users", e)
        return []


# =============================================================================
#  КОНЕЦ ЧАСТИ 2
# =============================================================================
#  ЧАСТЬ 3 подключит: историю, чаты, промо, квесты, турниры, аналитику.

# =============================================================================
#  ЧАСТЬ 3 / 10 — БД (часть 2)
#  Содержание:
#    - История: transactions, games, roulette (пагинация)
#    - Чаты: chat_settings, event_chats (CRUD)
#    - Промо: create/activate promo, promo_used
#    - Квесты: генерация на день, прогресс, награда
#    - Турниры: создание, скор, финализация
#    - Аналитика экономики: снимок, регулятор, джекпот-пул
#    - Админ-логи, bot_activity_log
#    - Рефералка: привязка + выплата
#    - Винстрики
#  Никаких "drop". Только purge/delete/clear.
# =============================================================================

# =============================================================================
#  ИСТОРИЯ: транзакции и игры
# =============================================================================

async def history_transactions(
    user_id: int,
    limit: int = 10,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Последние транзакции пользователя (для профиля/истории)."""
    try:
        rows = await _fetchall(
            "SELECT amount, reason, balance_after, meta, created_at "
            "FROM transactions WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, max(1, limit), max(0, offset)),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("history_transactions", e)
        return []


async def history_games(
    user_id: int,
    limit: int = 10,
    offset: int = 0,
    game: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """История игр пользователя (опционально по типу игры)."""
    try:
        if game:
            rows = await _fetchall(
                "SELECT game, bet, result, delta, meta, created_at "
                "FROM games_log WHERE user_id = ? AND game = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, game, max(1, limit), max(0, offset)),
            )
        else:
            rows = await _fetchall(
                "SELECT game, bet, result, delta, meta, created_at "
                "FROM games_log WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, max(1, limit), max(0, offset)),
            )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("history_games", e)
        return []


async def history_roulette(
    user_id: int,
    limit: int = 10,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT bet, bet_type, bet_value, number, won, payout, created_at "
            "FROM roulette_logs WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, max(1, limit), max(0, offset)),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("history_roulette", e)
        return []


async def biggest_wins_last_24h(limit: int = 5) -> List[Dict[str, Any]]:
    """Крупнейшие выигрыши за сутки (для дашборда)."""
    try:
        since = now_ts() - 86400
        rows = await _fetchall(
            "SELECT user_id, game, delta, created_at FROM games_log "
            "WHERE delta > 0 AND created_at >= ? "
            "ORDER BY delta DESC LIMIT ?",
            (since, max(1, limit)),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("biggest_wins_last_24h", e)
        return []


async def activity_by_hour_last_24h() -> Dict[int, int]:
    """Активность по часам за сутки (для графика в дашборде)."""
    try:
        since = now_ts() - 86400
        rows = await _fetchall(
            "SELECT CAST(strftime('%H', datetime(created_at, 'unixepoch', 'localtime')) AS INTEGER) AS h, "
            "COUNT(*) AS c FROM games_log WHERE created_at >= ? GROUP BY h",
            (since,),
        )
        out: Dict[int, int] = {h: 0 for h in range(24)}
        for r in rows:
            out[int(r["h"])] = int(r["c"])
        return out
    except Exception as e:
        log_exc("activity_by_hour_last_24h", e)
        return {h: 0 for h in range(24)}


# =============================================================================
#  ЧАТЫ: chat_settings, event_chats
# =============================================================================

async def ensure_chat(chat_id: int, title: Optional[str] = None) -> Dict[str, Any]:
    """Гарантирует настройки чата. Возвращает dict."""
    try:
        ts = now_ts()
        async with db_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO chat_settings "
                "(chat_id, title, casino_enabled, neuro_enabled, events_enabled, commission, updated_at) "
                "VALUES (?, ?, 1, 1, 1, ?, ?)",
                (chat_id, title, BURN_COMMISSION_BASE, ts),
            )
            if title:
                await conn.execute(
                    "UPDATE chat_settings SET title = ? WHERE chat_id = ?",
                    (title, chat_id),
                )
        row = await _fetchone("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return dict(row) if row else {}
    except Exception as e:
        log_exc("ensure_chat", e)
        return {}


async def get_chat_settings(chat_id: int) -> Optional[Dict[str, Any]]:
    try:
        row = await _fetchone("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
        return dict(row) if row else None
    except Exception as e:
        log_exc("get_chat_settings", e)
        return None


async def set_chat_flag(chat_id: int, flag: str, value: bool) -> None:
    """flag: casino_enabled | neuro_enabled | events_enabled."""
    if flag not in {"casino_enabled", "neuro_enabled", "events_enabled"}:
        return
    try:
        await _execute(
            f"UPDATE chat_settings SET {flag} = ?, updated_at = ? WHERE chat_id = ?",
            (1 if value else 0, now_ts(), chat_id),
        )
    except Exception as e:
        log_exc("set_chat_flag", e)


async def set_chat_commission(chat_id: int, commission: float) -> None:
    """commission в [0.0, 0.30]."""
    commission = max(0.0, min(0.30, float(commission)))
    try:
        await _execute(
            "UPDATE chat_settings SET commission = ?, updated_at = ? WHERE chat_id = ?",
            (commission, now_ts(), chat_id),
        )
    except Exception as e:
        log_exc("set_chat_commission", e)


async def get_chat_commission(chat_id: Optional[int]) -> float:
    """Комиссия для чата; если чат не настроен — базовая."""
    if chat_id is None:
        return BURN_COMMISSION_BASE
    try:
        v = await _fetchval(
            "SELECT commission FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
            BURN_COMMISSION_BASE,
        )
        return float(v if v is not None else BURN_COMMISSION_BASE)
    except Exception as e:
        log_exc("get_chat_commission", e)
        return BURN_COMMISSION_BASE


async def add_event_chat(chat_id: int, title: Optional[str], added_by: int) -> bool:
    """Регистрирует чат для авто-ивентов."""
    try:
        await _execute(
            "INSERT INTO event_chats (chat_id, title, added_by, last_event_at, events_count, created_at) "
            "VALUES (?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title",
            (chat_id, title, added_by, now_ts()),
        )
        return True
    except Exception as e:
        log_exc("add_event_chat", e)
        return False


async def remove_event_chat(chat_id: int) -> bool:
    try:
        await _execute("DELETE FROM event_chats WHERE chat_id = ?", (chat_id,))
        return True
    except Exception as e:
        log_exc("remove_event_chat", e)
        return False


async def list_event_chats(limit: int = 100) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT chat_id, title, last_event_at, events_count "
            "FROM event_chats ORDER BY last_event_at ASC LIMIT ?",
            (max(1, limit),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("list_event_chats", e)
        return []


async def mark_event_chat_fired(chat_id: int) -> None:
    try:
        await _execute(
            "UPDATE event_chats SET last_event_at = ?, events_count = events_count + 1 "
            "WHERE chat_id = ?",
            (now_ts(), chat_id),
        )
    except Exception as e:
        log_exc("mark_event_chat_fired", e)


# =============================================================================
#  ПРОМОКОДЫ
# =============================================================================

async def create_promo(
    code: str,
    amount: int,
    max_uses: int,
    expires_at: float,
    created_by: int,
) -> bool:
    """Создаёт промокод. code приводится к upper()."""
    code = (code or "").strip().upper()
    if not code or amount <= 0 or max_uses <= 0:
        return False
    try:
        await _execute(
            "INSERT INTO promo_codes "
            "(code, amount, max_uses, uses, expires_at, created_by, created_at) "
            "VALUES (?, ?, ?, 0, ?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET "
            "amount = excluded.amount, max_uses = excluded.max_uses, "
            "expires_at = excluded.expires_at",
            (code, amount, max_uses, expires_at, created_by, now_ts()),
        )
        return True
    except Exception as e:
        log_exc("create_promo", e)
        return False


async def activate_promo(code: str, user_id: int) -> Tuple[bool, str, int]:
    """
    Активирует промокод для юзера.
    Возвращает (ok, error_code, amount).
    error_code: ok | not_found | expired | exhausted | already_used
    """
    code = (code or "").strip().upper()
    if not code:
        return False, "not_found", 0
    try:
        async with db_conn() as conn:
            async with conn.execute(
                "SELECT code, amount, max_uses, uses, expires_at "
                "FROM promo_codes WHERE code = ?",
                (code,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return False, "not_found", 0
            if float(row["expires_at"] or 0) > 0 and float(row["expires_at"]) < now_ts():
                return False, "expired", 0
            if int(row["uses"]) >= int(row["max_uses"]):
                return False, "exhausted", 0
            # Проверка «уже использовал»
            async with conn.execute(
                "SELECT 1 FROM promo_used WHERE code = ? AND user_id = ?",
                (code, user_id),
            ) as c2:
                used_row = await c2.fetchone()
            if used_row is not None:
                return False, "already_used", 0
            # Атомарно инкрементим uses и пишем used
            cur_upd = await conn.execute(
                "UPDATE promo_codes SET uses = uses + 1 "
                "WHERE code = ? AND uses < max_uses",
                (code,),
            )
            if cur_upd.rowcount == 0:
                return False, "exhausted", 0
            await conn.execute(
                "INSERT OR IGNORE INTO promo_used (code, user_id, used_at) VALUES (?, ?, ?)",
                (code, user_id, now_ts()),
            )
            amount = int(row["amount"])
        # Начисление вне транзакции БД, но под user-lock (см. add_balance)
        await add_balance(user_id, amount, reason=f"promo:{code}")
        return True, "ok", amount
    except Exception as e:
        log_exc("activate_promo", e)
        return False, "internal", 0


async def list_promos(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT code, amount, max_uses, uses, expires_at, created_at "
            "FROM promo_codes ORDER BY created_at DESC LIMIT ?",
            (max(1, limit),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("list_promos", e)
        return []


async def purge_expired_promos() -> int:
    """Удаляет истёкшие промокоды. Возвращает кол-во."""
    try:
        cur_ts = now_ts()
        async with db_conn() as conn:
            cur = await conn.execute(
                "DELETE FROM promo_codes WHERE expires_at > 0 AND expires_at < ?",
                (cur_ts,),
            )
            return int(cur.rowcount or 0)
    except Exception as e:
        log_exc("purge_expired_promos", e)
        return 0


# =============================================================================
#  КВЕСТЫ
# =============================================================================

async def ensure_quest_templates() -> None:
    """Заполняет шаблоны квестов, если пусто. Идемпотентно."""
    defaults = (
        ("win_games_3",     "win_games",     "Выиграй 3 игры",       3, 3, 3000, 3000),
        ("win_games_5",     "win_games",     "Выиграй 5 игр",        5, 5, 5000, 5000),
        ("place_bets_10k",  "place_bets",    "Поставь 10 000 монет", 10000, 10000, 4000, 4000),
        ("place_bets_50k",  "place_bets",    "Поставь 50 000 монет", 50000, 50000, 15000, 15000),
        ("play_roulette_5", "play_roulette", "Сыграй в рулетку 5 раз", 5, 5, 3000, 3000),
        ("win_roulette_2",  "win_roulette",  "Выиграй в рулетку 2 раза", 2, 2, 4000, 4000),
        ("play_mines_3",    "play_mines",    "Сыграй в мины 3 раза", 3, 3, 2500, 2500),
    )
    try:
        async with db_conn() as conn:
            for q in defaults:
                await conn.execute(
                    "INSERT OR IGNORE INTO quest_templates "
                    "(quest_id, quest_type, title, target_min, target_max, "
                    " reward_min, reward_max, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    q,
                )
    except Exception as e:
        log_exc("ensure_quest_templates", e)


async def generate_daily_quests(user_id: int) -> List[Dict[str, Any]]:
    """
    Создаёт до DAILY_QUEST_COUNT квестов на сегодня (если ещё не созданы).
    Возвращает список активных квестов пользователя.
    """
    try:
        today_key = now_dt().strftime("%Y%m%d")
        async with db_conn() as conn:
            # Уже есть квесты, созданные сегодня?
            async with conn.execute(
                "SELECT COUNT(*) FROM quests WHERE user_id = ? "
                "AND date(assigned_at, 'unixepoch', 'localtime') = date('now', 'localtime')",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            if row and int(row[0]) >= DAILY_QUEST_COUNT:
                pass  # уже есть
            else:
                # Выбираем случайные шаблоны
                async with conn.execute(
                    "SELECT quest_id, quest_type, title, target_min, target_max, "
                    "reward_min, reward_max FROM quest_templates "
                    "WHERE active = 1 ORDER BY RANDOM() LIMIT ?",
                    (DAILY_QUEST_COUNT,),
                ) as cur:
                    templates = list(await cur.fetchall())
                ts = now_ts()
                for t in templates:
                    qid = f"{t['quest_id']}_{today_key}"
                    target = random.randint(int(t["target_min"]), int(t["target_max"]))
                    reward = random.randint(int(t["reward_min"]), int(t["reward_max"]))
                    await conn.execute(
                        "INSERT OR IGNORE INTO quests "
                        "(user_id, quest_id, progress, target, reward, "
                        " completed_at, claimed, assigned_at) "
                        "VALUES (?, ?, 0, ?, ?, 0, 0, ?)",
                        (user_id, qid, target, reward, ts),
                    )
        # Возвращаем активные (незабранные)
        rows = await _fetchall(
            "SELECT quest_id, progress, target, reward, completed_at, claimed "
            "FROM quests WHERE user_id = ? AND claimed = 0 "
            "ORDER BY assigned_at DESC LIMIT ?",
            (user_id, DAILY_QUEST_COUNT * 2),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("generate_daily_quests", e)
        return []


async def quest_progress(
    user_id: int,
    quest_type: str,
    increment: int = 1,
) -> List[Dict[str, Any]]:
    """
    Инкрементит прогресс по всем активным квестам нужного типа.
    Возвращает список квестов, которые только что завершились (для награды).
    """
    completed_now: List[Dict[str, Any]] = []
    try:
        async with db_conn() as conn:
            # Находим активные квесты юзера данного типа
            async with conn.execute(
                "SELECT q.quest_id, q.progress, q.target, q.reward, t.quest_type "
                "FROM quests q JOIN quest_templates t ON q.quest_id LIKE t.quest_id || '%' "
                "WHERE q.user_id = ? AND q.claimed = 0 AND t.quest_type = ?",
                (user_id, quest_type),
            ) as cur:
                rows = list(await cur.fetchall())
            for r in rows:
                new_prog = min(int(r["target"]), int(r["progress"]) + increment)
                if new_prog >= int(r["target"]) and int(r["progress"]) < int(r["target"]):
                    await conn.execute(
                        "UPDATE quests SET progress = ?, completed_at = ? WHERE user_id = ? AND quest_id = ?",
                        (new_prog, now_ts(), user_id, r["quest_id"]),
                    )
                    completed_now.append({
                        "quest_id": r["quest_id"],
                        "reward": int(r["reward"]),
                    })
                else:
                    await conn.execute(
                        "UPDATE quests SET progress = ? WHERE user_id = ? AND quest_id = ?",
                        (new_prog, user_id, r["quest_id"]),
                    )
        return completed_now
    except Exception as e:
        log_exc("quest_progress", e)
        return []


async def claim_quest_reward(user_id: int, quest_id: str) -> Tuple[bool, int]:
    """
    Пытается выдать награду за выполненный квест.
    Возвращает (ok, reward).
    """
    try:
        async with db_conn() as conn:
            async with conn.execute(
                "SELECT reward, claimed, completed_at, target, progress "
                "FROM quests WHERE user_id = ? AND quest_id = ?",
                (user_id, quest_id),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return False, 0
            if int(row["claimed"] or 0) == 1:
                return False, 0
            if int(row["completed_at"] or 0) == 0:
                # Проверим на всякий случай
                if int(row["progress"]) < int(row["target"]):
                    return False, 0
            cur_upd = await conn.execute(
                "UPDATE quests SET claimed = 1 WHERE user_id = ? AND quest_id = ? AND claimed = 0",
                (user_id, quest_id),
            )
            if cur_upd.rowcount == 0:
                return False, 0
            reward = int(row["reward"])
        await add_balance(user_id, reward, reason=f"quest:{quest_id}")
        return True, reward
    except Exception as e:
        log_exc("claim_quest_reward", e)
        return False, 0


# =============================================================================
#  ТУРНИРЫ
# =============================================================================

async def create_tournament(
    chat_id: int,
    duration_min: int,
    prize_pool: int,
) -> Optional[int]:
    """Создаёт турнир в статусе 'active'. Возвращает id."""
    try:
        ts = now_ts()
        end = ts + duration_min * 60
        async with db_conn() as conn:
            cur = await conn.execute(
                "INSERT INTO tournaments "
                "(chat_id, start_time, end_time, prize_pool, status, created_at) "
                "VALUES (?, ?, ?, ?, 'active', ?)",
                (chat_id, ts, end, prize_pool, ts),
            )
            return int(cur.lastrowid) if cur.lastrowid else None
    except Exception as e:
        log_exc("create_tournament", e)
        return None


async def get_active_tournament(chat_id: int) -> Optional[Dict[str, Any]]:
    try:
        row = await _fetchone(
            "SELECT * FROM tournaments WHERE chat_id = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        return dict(row) if row else None
    except Exception as e:
        log_exc("get_active_tournament", e)
        return None


async def get_tournament(tid: int) -> Optional[Dict[str, Any]]:
    try:
        row = await _fetchone("SELECT * FROM tournaments WHERE id = ?", (tid,))
        return dict(row) if row else None
    except Exception as e:
        log_exc("get_tournament", e)
        return None


async def tournament_add_score(tid: int, user_id: int, inc: int) -> None:
    try:
        async with db_conn() as conn:
            await conn.execute(
                "INSERT INTO tournament_scores (tournament_id, user_id, score, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tournament_id, user_id) DO UPDATE SET "
                "score = score + excluded.score, updated_at = excluded.updated_at",
                (tid, user_id, inc, now_ts()),
            )
    except Exception as e:
        log_exc("tournament_add_score", e)


async def tournament_top(tid: int, limit: int = 3) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT ts.user_id, ts.score, u.username, u.first_name "
            "FROM tournament_scores ts LEFT JOIN users u ON u.user_id = ts.user_id "
            "WHERE ts.tournament_id = ? ORDER BY ts.score DESC LIMIT ?",
            (tid, max(1, limit)),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("tournament_top", e)
        return []


async def finalize_tournament(tid: int) -> Optional[Dict[str, Any]]:
    """
    Финализирует турнир: статус 'finished', возвращает топ-3 и призы.
    Призы: 50% / 30% / 20% от prize_pool. Начисляет победителям.
    """
    try:
        t = await get_tournament(tid)
        if t is None:
            return None
        if t["status"] != "active":
            return None
        async with db_conn() as conn:
            cur = await conn.execute(
                "UPDATE tournaments SET status = 'finished' WHERE id = ? AND status = 'active'",
                (tid,),
            )
            if cur.rowcount == 0:
                return None
        top = await tournament_top(tid, 3)
        pool = int(t["prize_pool"])
        shares = (0.50, 0.30, 0.20)
        awards: List[Dict[str, Any]] = []
        for idx, row in enumerate(top[:3]):
            prize = int(pool * shares[idx])
            if prize > 0:
                await add_balance(
                    int(row["user_id"]), prize, reason=f"tournament:{tid}",
                    meta=f"place:{idx + 1}",
                )
            awards.append({
                "user_id": int(row["user_id"]),
                "name": row.get("username") or row.get("first_name") or str(row["user_id"]),
                "score": int(row["score"]),
                "prize": prize,
            })
        return {"tournament": t, "awards": awards}
    except Exception as e:
        log_exc("finalize_tournament", e)
        return None


async def list_expired_active_tournaments() -> List[Dict[str, Any]]:
    """Активные турниры, у которых end_time уже прошёл."""
    try:
        rows = await _fetchall(
            "SELECT * FROM tournaments WHERE status = 'active' AND end_time <= ?",
            (now_ts(),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("list_expired_active_tournaments", e)
        return []


# =============================================================================
#  ДЖЕКПОТ-ПУЛ
# =============================================================================

async def jackpot_get_pool() -> int:
    try:
        v = await _fetchval("SELECT pool FROM jackpot_pool WHERE id = 1", (), 0)
        return int(v or 0)
    except Exception as e:
        log_exc("jackpot_get_pool", e)
        return 0


async def jackpot_add(amount: int) -> int:
    """Добавляет в пул (1% от проигрышей). Возвращает новый размер."""
    if amount <= 0:
        return await jackpot_get_pool()
    async with jackpot_lock:
        try:
            async with db_conn() as conn:
                await conn.execute(
                    "UPDATE jackpot_pool SET pool = pool + ? WHERE id = 1",
                    (amount,),
                )
                async with conn.execute(
                    "SELECT pool FROM jackpot_pool WHERE id = 1"
                ) as cur:
                    row = await cur.fetchone()
                return int(row["pool"]) if row else 0
        except Exception as e:
            log_exc("jackpot_add", e)
            return 0


async def jackpot_take_all(user_id: int, chat_id: Optional[int]) -> int:
    """Забирает весь пул, обнуляет. Возвращает выигрыш (0 — если пусто)."""
    async with jackpot_lock:
        try:
            async with db_conn() as conn:
                async with conn.execute(
                    "SELECT pool FROM jackpot_pool WHERE id = 1"
                ) as cur:
                    row = await cur.fetchone()
                pool = int(row["pool"]) if row else 0
                if pool <= 0:
                    return 0
                await conn.execute(
                    "UPDATE jackpot_pool SET pool = 0, total_wins = total_wins + 1, "
                    "last_win_at = ? WHERE id = 1",
                    (now_ts(),),
                )
                await conn.execute(
                    "INSERT INTO jackpot_wins (user_id, chat_id, amount, pool_before, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, chat_id, pool, pool, now_ts()),
                )
            await add_balance(user_id, pool, reason="jackpot")
            return pool
        except Exception as e:
            log_exc("jackpot_take_all", e)
            return 0


# =============================================================================
#  АНАЛИТИКА ЭКОНОМИКИ
# =============================================================================

async def economy_snapshot_today() -> Dict[str, Any]:
    """
    Собирает снимок экономики на сегодня.
    total_burned — сколько юзеры потеряли в играх (games_log.delta < 0).
    total_earned — сколько начислено (transactions.amount > 0 за сутки).
    """
    try:
        today = now_dt().strftime("%Y-%m-%d")
        day_start_ts = now_dt().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        burned = await _fetchval(
            "SELECT COALESCE(SUM(-delta), 0) FROM games_log "
            "WHERE delta < 0 AND created_at >= ?",
            (day_start_ts,), 0,
        )
        earned = await _fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE amount > 0 AND created_at >= ?",
            (day_start_ts,), 0,
        )
        active = await _fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM games_log WHERE created_at >= ?",
            (day_start_ts,), 0,
        )
        pool = await jackpot_get_pool()
        snap = {
            "date": today,
            "total_burned": int(burned or 0),
            "total_earned": int(earned or 0),
            "pool_size": int(pool),
            "users_active": int(active or 0),
            "commission": BURN_COMMISSION_BASE,
        }
        await _execute(
            "INSERT INTO economy_analytics "
            "(date, total_burned, total_earned, pool_size, users_active, commission, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET "
            "total_burned = excluded.total_burned, "
            "total_earned = excluded.total_earned, "
            "pool_size = excluded.pool_size, "
            "users_active = excluded.users_active, "
            "commission = excluded.commission",
            (
                snap["date"], snap["total_burned"], snap["total_earned"],
                snap["pool_size"], snap["users_active"], snap["commission"], now_ts(),
            ),
        )
        return snap
    except Exception as e:
        log_exc("economy_snapshot_today", e)
        return {
            "date": now_dt().strftime("%Y-%m-%d"),
            "total_burned": 0, "total_earned": 0,
            "pool_size": 0, "users_active": 0,
            "commission": BURN_COMMISSION_BASE,
        }


async def economy_recent(days: int = 7) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT date, total_burned, total_earned, pool_size, users_active, commission "
            "FROM economy_analytics ORDER BY date DESC LIMIT ?",
            (max(1, days),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("economy_recent", e)
        return []


async def economy_balance_ratio() -> float:
    """
    Отношение burned / earned. > 1 — деньги сгорают (дефляция).
    < 1 — денег становится больше (инфляция).
    """
    try:
        day_start_ts = now_dt().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        burned = await _fetchval(
            "SELECT COALESCE(SUM(-delta), 0) FROM games_log "
            "WHERE delta < 0 AND created_at >= ?",
            (day_start_ts,), 0,
        )
        earned = await _fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE amount > 0 AND created_at >= ?",
            (day_start_ts,), 0,
        )
        b, e = int(burned or 0), int(earned or 0)
        if e <= 0:
            return 1.0
        return b / e
    except Exception as e:
        log_exc("economy_balance_ratio", e)
        return 1.0


# =============================================================================
#  РЕФЕРАЛКА
# =============================================================================

async def register_referral(referrer_id: int, referred_id: int) -> bool:
    """
    Создаёт запись о рефералке, если её ещё нет и referrer != referred.
    НЕ начисляет бонус — он начисляется после первой игры (см. reward_referral).
    """
    if referrer_id == referred_id:
        return False
    try:
        async with db_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO referrals "
                "(referrer_id, referred_id, paid, games_done, created_at) "
                "VALUES (?, ?, 0, 0, ?)",
                (referrer_id, referred_id, now_ts()),
            )
            # Обновим referral_by, если ещё не установлен
            await conn.execute(
                "UPDATE users SET referral_by = ? "
                "WHERE user_id = ? AND (referral_by IS NULL OR referral_by = 0)",
                (referrer_id, referred_id),
            )
        return True
    except Exception as e:
        log_exc("register_referral", e)
        return False


async def reward_referral_on_game(referred_id: int) -> None:
    """
    Вызывается при первой игре реферала. Если ещё не выплачено — платим.
    """
    try:
        async with db_conn() as conn:
            async with conn.execute(
                "SELECT id, referrer_id, paid FROM referrals WHERE referred_id = ?",
                (referred_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return
            if int(row["paid"] or 0) == 1:
                # уже выплачено — просто инкрементим games_done
                await conn.execute(
                    "UPDATE referrals SET games_done = games_done + 1 WHERE id = ?",
                    (row["id"],),
                )
                return
            # Первая игра — платим
            await conn.execute(
                "UPDATE referrals SET paid = 1, games_done = games_done + 1 WHERE id = ?",
                (row["id"],),
            )
            referrer_id = int(row["referrer_id"])
            await conn.execute(
                "UPDATE users SET referral_count = referral_count + 1, "
                "referral_paid = referral_paid + ? WHERE user_id = ?",
                (REFERRAL_BONUS, referrer_id),
            )
        await add_balance(referrer_id, REFERRAL_BONUS, reason=f"referral:{referred_id}")
    except Exception as e:
        log_exc("reward_referral_on_game", e)


async def count_referrals(user_id: int) -> int:
    try:
        v = await _fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
            (user_id,), 0,
        )
        return int(v or 0)
    except Exception as e:
        log_exc("count_referrals", e)
        return 0


# =============================================================================
#  ВИНСТРИКИ
# =============================================================================

async def update_win_streak(user_id: int, chat_id: Optional[int], won: bool) -> int:
    """
    Обновляет винстрик. Возвращает текущий стрик.
    При проигрыше — сбрасывает в 0 и, если стрик был >=3, пишет в лог.
    """
    try:
        async with db_conn() as conn:
            # Текущий стрик берём из in-memory кэша, но синхронизируем с БД не обязательно:
            # для простоты ведём in-memory + лог при сбросе.
            cur = win_streaks.get(user_id, {"count": 0, "ts": now_ts()})
            if won:
                cur["count"] = int(cur.get("count", 0)) + 1
                cur["ts"] = now_ts()
                win_streaks[user_id] = cur
                return cur["count"]
            else:
                old = int(cur.get("count", 0))
                if old >= 3:
                    await conn.execute(
                        "INSERT INTO win_streaks_log (user_id, chat_id, streak, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (user_id, chat_id, old, now_ts()),
                    )
                win_streaks[user_id] = {"count": 0, "ts": now_ts()}
                return 0
    except Exception as e:
        log_exc("update_win_streak", e)
        return 0


async def get_win_streak(user_id: int) -> int:
    cur = win_streaks.get(user_id)
    return int(cur["count"]) if cur else 0


# =============================================================================
#  АДМИН-ЛОГИ И АКТИВНОСТЬ БОТА
# =============================================================================

async def log_admin_action(
    admin_id: int,
    action: str,
    target_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    try:
        await _execute(
            "INSERT INTO admin_logs (admin_id, action, target_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (admin_id, action, target_id, details, now_ts()),
        )
    except Exception as e:
        log_exc("log_admin_action", e)


async def log_bot_activity(action_type: str, details: Optional[str] = None) -> None:
    try:
        await _execute(
            "INSERT INTO bot_activity_log (action_type, details, created_at) "
            "VALUES (?, ?, ?)",
            (action_type, details, now_ts()),
        )
    except Exception as e:
        log_exc("log_bot_activity", e)


async def recent_bot_activity(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        rows = await _fetchall(
            "SELECT action_type, details, created_at FROM bot_activity_log "
            "ORDER BY id DESC LIMIT ?",
            (max(1, limit),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("recent_bot_activity", e)
        return []


# =============================================================================
#  СЕЗОННОЕ СОСТОЯНИЕ
# =============================================================================

async def seasonal_get() -> Dict[str, Any]:
    try:
        row = await _fetchone("SELECT event_key, multiplier, updated_at FROM seasonal_state WHERE id = 1")
        return dict(row) if row else {"event_key": None, "multiplier": 1.0, "updated_at": 0}
    except Exception as e:
        log_exc("seasonal_get", e)
        return {"event_key": None, "multiplier": 1.0, "updated_at": 0}


async def seasonal_set(event_key: Optional[str], multiplier: float) -> None:
    try:
        await _execute(
            "UPDATE seasonal_state SET event_key = ?, multiplier = ?, updated_at = ? WHERE id = 1",
            (event_key, float(multiplier), now_ts()),
        )
    except Exception as e:
        log_exc("seasonal_set", e)


# =============================================================================
#  СПЯЩИЕ ЮЗЕРЫ (для реанимации)
# =============================================================================

async def find_sleeping_users(days: int = SLEEPING_USER_DAYS, limit: int = 50) -> List[Dict[str, Any]]:
    """Юзеры, не заходившие N дней, с балансом, но без недавнего ревайва."""
    try:
        cutoff = now_ts() - days * 86400
        rev_cutoff = now_ts() - 7 * 86400  # не спамим чаще раза в неделю
        rows = await _fetchall(
            "SELECT user_id, username, first_name, balance, last_seen "
            "FROM users WHERE last_seen > 0 AND last_seen < ? "
            "AND last_revive < ? AND is_banned = 0 "
            "ORDER BY last_seen ASC LIMIT ?",
            (cutoff, rev_cutoff, max(1, limit)),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log_exc("find_sleeping_users", e)
        return []


async def mark_revive_sent(user_id: int) -> None:
    try:
        await _execute("UPDATE users SET last_revive = ? WHERE user_id = ?", (now_ts(), user_id))
    except Exception as e:
        log_exc("mark_revive_sent", e)


# =============================================================================
#  ХЕЛПЕР: сводка для дашборда
# =============================================================================

async def dashboard_stats() -> Dict[str, Any]:
    """Собирает все метрики для Live-Дашборда одним заходом."""
    try:
        now = now_ts()
        online = await _fetchval(
            "SELECT COUNT(*) FROM users WHERE last_seen >= ?", (now - 300,), 0,
        )
        users_total = await count_users()
        bank = await total_economy_bank()
        pool = await jackpot_get_pool()
        since = now - 86400
        burned = await _fetchval(
            "SELECT COALESCE(SUM(-delta), 0) FROM games_log WHERE delta < 0 AND created_at >= ?",
            (since,), 0,
        )
        earned = await _fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE amount > 0 AND created_at >= ?",
            (since,), 0,
        )
        return {
            "online": int(online or 0),
            "users": int(users_total or 0),
            "bank": int(bank or 0),
            "jackpot": int(pool or 0),
            "burned": int(burned or 0),
            "earned": int(earned or 0),
        }
    except Exception as e:
        log_exc("dashboard_stats", e)
        return {"online": 0, "users": 0, "bank": 0, "jackpot": 0, "burned": 0, "earned": 0}


# =============================================================================
#  КОНЕЦ ЧАСТИ 3
# =============================================================================
#  ЧАСТЬ 4 подключит: UI-хелперы (safe_send_autodelete), FSM, клавиатуры.

# =============================================================================
#  ЧАСТЬ 4 / 10 — UI-ХЕЛПЕРЫ, FSM, КЛАВИАТУРЫ, NEWS GENERATOR
#  Содержание:
#    - safe_send / safe_send_autodelete / safe_edit_or_send
#    - Автоудаление через asyncio.create_task (без edit_text для медиа)
#    - FSM-состояния (StatesGroup) для всех интерактивных сценариев
#    - Клавиатуры: главное меню, игры, рулетка, админка, назад
#    - callback_data helpers (<=64 байт, безопасные)
#    - NEWS GENERATOR: автогенерация постов в стиле «набор в команду»,
#      анонсов, аналитики; отправка в NEWS_CHANNEL_ID по расписанию
# =============================================================================

# --- Конфиг новостного канала (можно задать в env NEWS_CHANNEL_ID) ---------
NEWS_CHANNEL_ID: int = int(os.environ.get("NEWS_CHANNEL_ID", "0") or "0")
# Если задан — бот будет туда постить; иначе пробует LOG_CHANNEL_ID.
NEWS_TARGET_CHAT: int = NEWS_CHANNEL_ID or LOG_CHANNEL_ID

# --- Тайминги авто-новостей (секунды) --------------------------------------
NEWS_MIN_INTERVAL_SEC: int = 4 * 3600       # минимум раз в 4 часа
NEWS_MAX_INTERVAL_SEC: int = 10 * 3600      # максимум раз в 10 часов
NEWS_RECRUIT_INTERVAL_SEC: int = 12 * 3600  # «набор в команду» — раз в 12 часов
NEWS_DEDUP_TTL_SEC: int = 7 * 86400          # не повторять один и тот же тип чаще, чем за 7 дней

# =============================================================================
#  1. CALLBACK-DATA ХЕЛПЕРЫ
# =============================================================================
#  Строго <= 64 байт. Используем компактные префиксы и ":".
#  Кодируем через простой join, без json, чтобы не раздувать.

CB_SEP = ":"


def cb_build(*parts: Union[str, int]) -> str:
    """
    Собирает callback_data из частей. Обрезает до 60 символов (с запасом).
    Никогда не бросает.
    """
    try:
        s = CB_SEP.join(str(p) for p in parts if p is not None and str(p) != "")
        return s[:MAX_CALLBACK_CHARS]
    except Exception:
        return "noop"


def cb_parse(data: str) -> List[str]:
    """Разбирает callback_data обратно в список частей."""
    try:
        return str(data or "").split(CB_SEP)
    except Exception:
        return []


# =============================================================================
#  2. SAFE SEND / AUTODELETE
# =============================================================================
#  КРИТИЧЕСКИЕ ПРАВИЛА:
#    - Любой вызов Telegram API — в try/except.
#    - safe_send режет текст > TG_SAFE_TEXT.
#    - safe_send_autodelete ВСЕГДА шлёт НОВОЕ сообщение (никаких edit_text
#      для медиа-кубиков, чтобы не ловить "there is no text in the message").
#    - Удаление — отдельная asyncio.create_task, fire-and-forget.
#    - Учитываем flood control (TelegramRetryAfter): спим и повторяем 1 раз.
# =============================================================================

_autodelete_tasks: Set[asyncio.Task] = set()


def _spawn_autodelete(chat_id: int, message_id: int, delay: int) -> None:
    """Создаёт фоновую задачу на удаление сообщения через delay секунд."""
    async def _worker():
        try:
            await asyncio.sleep(max(1, int(delay)))
            b = bot
            if b is None:
                return
            await b.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramBadRequest:
            # Сообщение уже удалено/нельзя удалить — это норма.
            pass
        except TelegramForbiddenError:
            pass
        except TelegramRetryAfter as e:
            # Подождём и попробуем ещё раз
            try:
                await asyncio.sleep(int(getattr(e, "retry_after", 3)) + 1)
                b = bot
                if b is not None:
                    await b.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
        except Exception as e:
            log_exc("autodelete_worker", e)

    t = asyncio.create_task(_worker(), name=f"autodel:{chat_id}:{message_id}")
    _autodelete_tasks.add(t)
    t.add_done_callback(lambda _t: _autodelete_tasks.discard(_t))


async def safe_send(
    chat_id: int,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    reply_to: Optional[int] = None,
    parse_mode: Optional[str] = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    allow_chunks: bool = True,
) -> List[Message]:
    """
    Безопасная отправка текста. Режет длинный текст на чанки.
    Возвращает список отправленных Message (может быть пустым).
    """
    b = bot
    if b is None:
        return []
    sent: List[Message] = []
    parts = chunk_text(text, TG_SAFE_TEXT) if allow_chunks else [text[:TG_SAFE_TEXT]]
    for idx, part in enumerate(parts):
        # На последний чанк вешаем клавиатуру и reply_to
        is_last = (idx == len(parts) - 1)
        kwargs: Dict[str, Any] = dict(
            chat_id=chat_id,
            text=part,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        if is_last and reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if is_last and reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
        try:
            msg = await b.send_message(**kwargs)
            sent.append(msg)
        except TelegramRetryAfter as e:
            try:
                await asyncio.sleep(int(getattr(e, "retry_after", 3)) + 1)
                msg = await b.send_message(**kwargs)
                sent.append(msg)
            except Exception as e2:
                log_exc("safe_send.retry", e2)
        except TelegramForbiddenError as e:
            log.warning("safe_send forbidden chat=%s: %s", chat_id, e)
            return sent
        except TelegramBadRequest as e:
            # Иногда падает из-за parse_mode (эмодзи и т.п.) — пробуем plain
            try:
                kwargs_plain = dict(kwargs)
                kwargs_plain.pop("parse_mode", None)
                msg = await b.send_message(**kwargs_plain)
                sent.append(msg)
            except Exception as e2:
                log_exc("safe_send.plain", e2)
        except Exception as e:
            log_exc("safe_send", e)
            # Не продолжаем бесконечно, если чат недоступен.
            break
    return sent


async def safe_send_autodelete(
    chat_id: int,
    text: str,
    delay: int = AUTODELETE_DEFAULT_SEC,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.HTML,
    reply_to: Optional[int] = None,
) -> List[Message]:
    """
    Отправляет НОВОЕ сообщение и вешает автоудаление через delay секунд.
    Строгий запрет edit_text для медиа — мы никогда не редактируем,
    только шлём новое и удаляем по таймеру.
    """
    sent = await safe_send(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        reply_to=reply_to,
        parse_mode=parse_mode,
    )
    for m in sent:
        with contextlib.suppress(Exception):
            _spawn_autodelete(chat_id, m.message_id, delay)
    return sent


async def safe_edit_or_send(
    chat_id: int,
    message_id: Optional[int],
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.HTML,
) -> Optional[Message]:
    """
    Пытается edit_text; если нельзя (медиа/нет text) — отправляет новое.
    Используется ТОЛЬКО для чисто текстовых сообщений (меню/профиль).
    """
    b = bot
    if b is None:
        return None
    if message_id is not None:
        try:
            return await b.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text[:TG_SAFE_TEXT],
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg:
                return None
            if "there is no text in the message to edit" in msg or "message can't be edited" in msg:
                pass  # упадём в safe_send ниже
            else:
                log.warning("safe_edit_or_send fallback: %s", e)
        except TelegramRetryAfter as e:
            try:
                await asyncio.sleep(int(getattr(e, "retry_after", 3)) + 1)
                return await b.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text[:TG_SAFE_TEXT],
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
            except Exception as e2:
                log_exc("safe_edit_or_send.retry", e2)
        except Exception as e:
            log_exc("safe_edit_or_send", e)
    # Fallback — новое сообщение
    sent = await safe_send(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
    return sent[-1] if sent else None


async def safe_answer_cb(cb: CallbackQuery, text: Optional[str] = None, alert: bool = False) -> None:
    """Всегда отвечает на CallbackQuery. Никогда не бросает."""
    try:
        if text:
            await cb.answer(text=text, show_alert=alert)
        else:
            await cb.answer()
    except Exception as e:
        log_exc("safe_answer_cb", e)


async def safe_delete_message(chat_id: int, message_id: int) -> None:
    b = bot
    if b is None:
        return
    try:
        await b.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def safe_send_dice(
    chat_id: int,
    emoji: str = "🎲",
    *,
    reply_to: Optional[int] = None,
) -> Optional[Message]:
    """
    Отправляет кубик/дартс. Возвращает Message — чтобы забрать value.
    НИКОГДА не редактируем результат — только читаем value из ответа.
    """
    b = bot
    if b is None:
        return None
    try:
        return await b.send_dice(
            chat_id=chat_id,
            emoji=emoji,
            reply_to_message_id=reply_to,
        )
    except TelegramRetryAfter as e:
        try:
            await asyncio.sleep(int(getattr(e, "retry_after", 3)) + 1)
            return await b.send_dice(chat_id=chat_id, emoji=emoji, reply_to_message_id=reply_to)
        except Exception as e2:
            log_exc("safe_send_dice.retry", e2)
            return None
    except Exception as e:
        log_exc("safe_send_dice", e)
        return None


# =============================================================================
#  3. FSM-СОСТОЯНИЯ
# =============================================================================
#  Единый namespace. Каждый сценарий — отдельный State.
#  Все состояния чистятся по таймауту в ЧАСТИ 10 (или вручную).

class MenuStates(StatesGroup):
    main = State()


class BetStates(StatesGroup):
    waiting_amount = State()     # ожидание суммы ставки
    waiting_target = State()     # ожидание цели (перевод/дуэль)
    waiting_promo = State()      # ожидание промокода


class RouletteStates(StatesGroup):
    choosing_bet_type = State()  # выбор типа ставки
    spinning = State()           # «крутится» (защита от двойного клика)


class MinesStates(StatesGroup):
    playing = State()            # в процессе игры


class AdminStates(StatesGroup):
    waiting_promo_code = State()
    waiting_promo_amount = State()
    waiting_promo_uses = State()
    waiting_broadcast = State()
    waiting_ban_id = State()
    waiting_unban_id = State()
    waiting_give_amount = State()
    waiting_take_amount = State()


# =============================================================================
#  4. КЛАВИАТУРЫ
# =============================================================================

def kb_main_menu() -> InlineKeyboardMarkup:
    """Главное меню — 8 кнопок в 2 колонки."""
    b = InlineKeyboardBuilder()
    b.button(text=BTN_ROULETTE, callback_data=cb_build("menu", "roulette"))
    b.button(text=BTN_DICE,     callback_data=cb_build("menu", "dice"))
    b.button(text=BTN_MINES,    callback_data=cb_build("menu", "mines"))
    b.button(text=BTN_DUEL,     callback_data=cb_build("menu", "duel"))
    b.button(text=BTN_DAILY,    callback_data=cb_build("menu", "daily"))
    b.button(text=BTN_TOP,      callback_data=cb_build("menu", "top"))
    b.button(text=BTN_REF,      callback_data=cb_build("menu", "ref"))
    b.button(text=BTN_PROFILE,  callback_data=cb_build("menu", "profile"))
    b.adjust(2, 2, 2, 2)
    return b.as_markup()


def kb_back_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=BTN_BACK, callback_data=cb_build("menu", "main"))
    return b.as_markup()


def kb_cancel(cb_prefix: str = "cancel") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=BTN_CANCEL, callback_data=cb_build(cb_prefix, "1"))
    return b.as_markup()


def kb_bet_amounts(base_prefix: str) -> InlineKeyboardMarkup:
    """Быстрые суммы для ставок: 100 / 500 / 1k / 5k / 10k / all."""
    b = InlineKeyboardBuilder()
    for amt in (100, 500, 1_000, 5_000, 10_000):
        b.button(text=f"{fmt_int(amt)}", callback_data=cb_build(base_prefix, "amt", amt))
    b.button(text="💰 Всё", callback_data=cb_build(base_prefix, "amt", "all"))
    b.button(text=BTN_CANCEL, callback_data=cb_build("cancel", "1"))
    b.adjust(3, 3, 1)
    return b.as_markup()


def kb_roulette_types(bet: int) -> InlineKeyboardMarkup:
    """
    Кнопки типов ставок рулетки. Каждая несёт сумму, чтобы не ходить в FSM.
    callback_data: rl:spin:<bet>:<type>[:value]
    """
    b = InlineKeyboardBuilder()
    b.button(text="🔴 Красное",   callback_data=cb_build("rl", "spin", bet, "red"))
    b.button(text="⚫ Чёрное",    callback_data=cb_build("rl", "spin", bet, "black"))
    b.button(text="🟢 Зеро",      callback_data=cb_build("rl", "spin", bet, "exact", 0))
    b.button(text="Чёт",          callback_data=cb_build("rl", "spin", bet, "even"))
    b.button(text="Нечет",        callback_data=cb_build("rl", "spin", bet, "odd"))
    b.button(text="1-18",         callback_data=cb_build("rl", "spin", bet, "low"))
    b.button(text="19-36",        callback_data=cb_build("rl", "spin", bet, "high"))
    b.button(text="1-12",         callback_data=cb_build("rl", "spin", bet, "dozen1"))
    b.button(text="13-24",        callback_data=cb_build("rl", "spin", bet, "dozen2"))
    b.button(text="25-36",        callback_data=cb_build("rl", "spin", bet, "dozen3"))
    b.button(text="1-я колонка",  callback_data=cb_build("rl", "spin", bet, "column1"))
    b.button(text="2-я колонка",  callback_data=cb_build("rl", "spin", bet, "column2"))
    b.button(text="3-я колонка",  callback_data=cb_build("rl", "spin", bet, "column3"))
    b.button(text=BTN_CANCEL,     callback_data=cb_build("cancel", "1"))
    b.adjust(2, 2, 2, 2, 2, 2, 2)
    return b.as_markup()


def kb_roulette_again(bet: int, bet_type: str, value: Optional[str] = None) -> InlineKeyboardMarkup:
    """Повторить / Удвоить."""
    b = InlineKeyboardBuilder()
    b.button(
        text="🔁 Повторить",
        callback_data=cb_build("rl", "spin", bet, bet_type, value or ""),
    )
    b.button(
        text="x2 Удвоить",
        callback_data=cb_build("rl", "spin", min(bet * 2, MAX_BET), bet_type, value or ""),
    )
    b.button(text=BTN_MENU, callback_data=cb_build("menu", "main"))
    b.adjust(2, 1)
    return b.as_markup()


def kb_dice_again(bet: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Повторить", callback_data=cb_build("dice", "again", bet))
    b.button(text="x2 Удвоить", callback_data=cb_build("dice", "again", min(bet * 2, MAX_BET)))
    b.button(text=BTN_MENU, callback_data=cb_build("menu", "main"))
    b.adjust(2, 1)
    return b.as_markup()


def kb_mines_field(
    opened: Set[int],
    size: int = 25,
    game_key: str = "0",
) -> InlineKeyboardMarkup:
    """
    Сетка 5x5. Открытые клетки помечаем ✅ и делаем noop-callback.
    callback_data: mn:open:<game_key>:<idx>
    """
    b = InlineKeyboardBuilder()
    for idx in range(size):
        if idx in opened:
            b.button(text="✅", callback_data=cb_build("mn", "noop", game_key, idx))
        else:
            b.button(text="⬜", callback_data=cb_build("mn", "open", game_key, idx))
    # Разбиваем по 5 в ряд
    b.adjust(5, 5, 5, 5, 5)
    return b.as_markup()


def kb_mines_actions(game_key: str, can_cashout: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if can_cashout:
        b.button(text="💰 Забрать", callback_data=cb_build("mn", "cash", game_key))
    b.button(text="❌ Сдаться", callback_data=cb_build("mn", "giveup", game_key))
    b.adjust(2)
    return b.as_markup()


def kb_duel_join(bet: int, owner_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚔️ Принять", callback_data=cb_build("duel", "join", bet, owner_id))
    b.button(text=BTN_CANCEL, callback_data=cb_build("duel", "cancel", owner_id))
    b.adjust(2)
    return b.as_markup()


def kb_admin_dashboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data=cb_build("adm", "dash", "refresh"))
    b.button(text="📊 График",   callback_data=cb_build("adm", "dash", "chart"))
    b.button(text="🏆 Топ-выигрыши", callback_data=cb_build("adm", "dash", "wins"))
    b.button(text="🤖 Активность", callback_data=cb_build("adm", "dash", "activity"))
    b.button(text="🎟 Промо",     callback_data=cb_build("adm", "promo", "list"))
    b.button(text="📣 Новости",   callback_data=cb_build("adm", "news", "menu"))
    b.button(text=BTN_MENU,       callback_data=cb_build("menu", "main"))
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def kb_admin_news_menu() -> InlineKeyboardMarkup:
    """Подменю управления авто-новостями."""
    b = InlineKeyboardBuilder()
    b.button(text="🎯 Набор в команду", callback_data=cb_build("adm", "news", "recruit"))
    b.button(text="🎉 Анонс ивента",     callback_data=cb_build("adm", "news", "event"))
    b.button(text="📈 Аналитика",       callback_data=cb_build("adm", "news", "analytics"))
    b.button(text="💬 Светская",         callback_data=cb_build("adm", "news", "social"))
    b.button(text="🎲 Случайная",        callback_data=cb_build("adm", "news", "random"))
    b.button(text=BTN_BACK,             callback_data=cb_build("adm", "dash", "refresh"))
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def kb_confirm(prefix: str, payload: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data=cb_build(prefix, "yes", payload))
    b.button(text="❌ Нет", callback_data=cb_build(prefix, "no", payload))
    b.adjust(2)
    return b.as_markup()


# =============================================================================
#  5. NEWS GENERATOR — АВТО-ГЕНЕРАЦИЯ ПОСТОВ
# =============================================================================
#  Бот сам собирает «живые» новости и постит в NEWS_TARGET_CHAT:
#    - Набор в команду (как в примере пользователя): модераторы, админы,
#      помощники, техподдержка, пиарщик — с зарплатами в TOKENS.
#    - Анонсы турниров и ивентов.
#    - Аналитика экономики (банк, сожжено, джекпот).
#    - Светские/провокационные посты (для вовлечения).
#  Всё рандомизируется, дедуп по типу на 7 дней, интервал 4-10 часов.
# =============================================================================

@dataclass
class NewsPost:
    kind: str               # recruit | event | analytics | social | random
    text: str
    parse_mode: str = ParseMode.HTML


# --- Ротация ролей и зарплат для «набора в команду» ---
_RECRUIT_ROLES: Tuple[Tuple[str, int, int, str], ...] = (
    # (название, min_зарплата, max_зарплата, эмодзи)
    ("Модератор чата обмена",        8_000, 15_000, "🛡"),
    ("Админ игровой группы",         8_000, 15_000, "👑"),
    ("Помощник по обменнику",        5_000, 12_000, "🤝"),
    ("Техподдержка",                10_000, 18_000, "🛠"),
    ("Старший админ",               15_000, 25_000, "⭐️"),
    ("Пиарщик",                      8_000, 20_000, "📣"),
    ("Модератор ночной смены",       7_000, 12_000, "🌙"),
    ("Аналитик ставок",             10_000, 20_000, "📊"),
)

_RECRUIT_REQUIREMENTS: Tuple[str, ...] = (
    "Быть активным и адекватным",
    "Знать правила проекта",
    "Уметь решать конфликты",
    "Онлайн от 2-3 часов в день",
    "Возраст 16+",
    "Опыт в подобных проектах — плюс",
    "Стрессоустойчивость",
)

_RECRUIT_BENEFITS: Tuple[str, ...] = (
    "Статус админа и уважение",
    "Бонусы и токены за работу",
    "Доступ к закрытой инфе",
    "Опыт и рост в проекте",
    "Личный кабинет с отчётами",
    "Приоритетная поддержка",
)

_RECRUIT_CONTACT: Tuple[str, ...] = (
    "@victorw",
    "@tokens_hr",
    "@tokens_admin",
)


def _pick_unique(pool: Sequence[Any], k: int) -> List[Any]:
    k = max(0, min(k, len(pool)))
    return random.sample(list(pool), k) if k > 0 else []


def _rand_salary(lo: int, hi: int, step: int = 500) -> int:
    """Рандомная зарплата, кратная step, в [lo, hi]."""
    try:
        lo_s = ((lo + step - 1) // step) * step
        hi_s = (hi // step) * step
        if hi_s < lo_s:
            return lo
        return random.randrange(lo_s, hi_s + 1, step)
    except Exception:
        return lo


def generate_recruit_post() -> NewsPost:
    """
    Генерирует пост «набор в команду TOKENS» в стиле присланного примера,
    но с рандомизацией ролей, зарплат и требований.
    """
    roles = _pick_unique(_RECRUIT_ROLES, random.randint(4, 6))
    reqs = _pick_unique(_RECRUIT_REQUIREMENTS, random.randint(3, 5))
    bens = _pick_unique(_RECRUIT_BENEFITS, random.randint(3, 4))
    contact = random.choice(_RECRUIT_CONTACT)
    period = random.choice(["неделя", "неделя", "неделя", "месяц"])

    lines: List[str] = []
    lines.append("🚀 <b>НАБОР В АДМИНИСТРАЦИЮ TOKENS!</b>")
    lines.append(
        random.choice((
            "Друзья, наш проект растёт, и нам нужны надёжные люди в команду! 🔥",
            "Проект набирает обороты — ищем в команду амбициозных людей! 💼",
            "Мы расширяемся! Требуются ответственные члены команды. 🚀",
        ))
    )
    lines.append("")
    lines.append("👑 <b>КТО НАМ НУЖЕН:</b>")
    for name, lo, hi, emo in roles:
        lines.append(f"• {emo} {name}")
    lines.append("")
    lines.append("💰 <b>ЗАРПЛАТА В ТОКЕНАХ:</b>")
    for name, lo, hi, emo in roles:
        salary = _rand_salary(lo, hi)
        lines.append(f"• {name} — {fmt_int(salary)} токенов/{period}")
    lines.append("")
    lines.append("📋 <b>ТРЕБОВАНИЯ:</b>")
    for r in reqs:
        lines.append(f"• {r}")
    lines.append("")
    lines.append("💎 <b>ЧТО ПОЛУЧАЕШЬ:</b>")
    for bn in bens:
        lines.append(f"• {bn}")
    lines.append("")
    lines.append("📩 <b>КАК ПОДАТЬ ЗАЯВКУ:</b>")
    lines.append(f"Напиши в личку: <code>{contact}</code>")
    lines.append("Укажи: имя, возраст, опыт, сколько времени в сети.")
    lines.append("")
    lines.append("⚡️ Ждём именно тебя! Вливайся в команду! 🚀")
    return NewsPost(kind="recruit", text="\n".join(lines))


def generate_event_post(ctx: Optional[Dict[str, Any]] = None) -> NewsPost:
    """Анонс ивента/турнира. Если есть контекст (турнир) — используем его."""
    ctx = ctx or {}
    prize = int(ctx.get("prize") or random.choice((50_000, 100_000, 250_000, 500_000)))
    minutes = int(ctx.get("minutes") or random.choice((30, 45, 60)))
    title = ctx.get("title") or random.choice((
        "Гранд-Турнир", "Ночная гонка", "Экспресс-рулетка", "Джекпот-мания",
    ))
    lines = [
        f"🏆 <b>{title}!</b>",
        f"Длительность: <b>{minutes} мин</b>",
        f"Призовой фонд: <b>{fmt_int(prize)}</b> TOKENS",
        "",
        random.choice((
            "Крутите рулетку — каждый спин идёт в зачёт. Топ-3 заберут банк!",
            "Играйте в любимые игры — победитель определяется по сумме выигрышей.",
            "Кто больше поставит за отведённое время — тот и заберёт пул.",
        )),
        "",
        "🔥 Не пропусти!",
    ]
    return NewsPost(kind="event", text="\n".join(lines))


def generate_analytics_post(snap: Optional[Dict[str, Any]] = None) -> NewsPost:
    """Аналитика экономики в человеческом виде."""
    snap = snap or {}
    bank = int(snap.get("bank") or 0)
    burned = int(snap.get("burned") or 0)
    earned = int(snap.get("earned") or 0)
    jackpot = int(snap.get("jackpot") or 0)
    users = int(snap.get("users") or 0)
    online = int(snap.get("online") or 0)

    trend = "📈" if earned > burned else ("📉" if burned > earned else "⚖️")
    lines = [
        "📊 <b>ЭКОНОМИКА TOKENS — СВОДКА</b>",
        f"{trend} Общий банк: <b>{fmt_int(bank)}</b> TOKENS",
        f"🔥 Сожжено в играх (сутки): <b>{fmt_int(burned)}</b>",
        f"💸 Начислено (сутки): <b>{fmt_int(earned)}</b>",
        f"💎 Джекпот-пул: <b>{fmt_int(jackpot)}</b>",
        f"👥 Юзеров: <b>{fmt_int(users)}</b> | 🟢 Онлайн: <b>{fmt_int(online)}</b>",
        "",
        random.choice((
            "Цифры не врут: экономика живёт. Не упусти свой шанс!",
            "Казино всегда в плюсе — но кто-то же забирает джекпот. Может, ты?",
            "Баланс сил меняется каждый час. Играй на опережение.",
        )),
    ]
    return NewsPost(kind="analytics", text="\n".join(lines))


def generate_social_post() -> NewsPost:
    """Светский/провокационный пост для вовлечения."""
    lines = [random.choice((
        "💬 <b>Светская беседа</b>",
        "🗣 <b>Разговор в чате</b>",
        "🎭 <b>Мысли вслух</b>",
    ))]
    body = random.choice((
        "Как ваши дела, господа? Кто сегодня уже в плюсе — делитесь!",
        "Ставки сделаны. А кто рискнёт на джекпот сегодня?",
        "Заметил, что удача любит настойчивых. Кто играл вчера?",
        "Казино не работает, если в него не играть. 🎰",
        "Кто-нибудь видел сегодня КИТА? А то пул растёт подозрительно...",
        "Интересно, кто первым заберёт принудительный джекпот?",
    ))
    lines.append(body)
    return NewsPost(kind="social", text="\n".join(lines))


def generate_random_post() -> NewsPost:
    """Полностью случайный пост из всех генераторов."""
    return random.choice((
        generate_recruit_post,
        lambda: generate_event_post(),
        lambda: generate_analytics_post(),
        generate_social_post,
    ))()


# --- Дедупликация новостей --------------------------------------------------
_news_last_by_kind: Dict[str, float] = {}


def _news_kind_recent(kind: str) -> bool:
    ts = _news_last_by_kind.get(kind, 0.0)
    return (time.time() - ts) < NEWS_DEDUP_TTL_SEC


def _news_mark(kind: str) -> None:
    _news_last_by_kind[kind] = time.time()


# --- Публикация ------------------------------------------------------------

async def publish_news(post: NewsPost, *, force: bool = False) -> bool:
    """
    Публикует пост в NEWS_TARGET_CHAT.
    Если kind недавно публиковался и not force — пропускаем (антидубль).
    """
    if not NEWS_TARGET_CHAT:
        log.warning("publish_news: NEWS_TARGET_CHAT не задан — пропуск")
        return False
    if not force and _news_kind_recent(post.kind):
        log.info("publish_news: kind=%s недавно постили, пропуск", post.kind)
        return False
    sent = await safe_send(
        NEWS_TARGET_CHAT,
        post.text,
        parse_mode=post.parse_mode,
    )
    if sent:
        _news_mark(post.kind)
        await log_bot_activity("news_publish", f"kind={post.kind} chat={NEWS_TARGET_CHAT}")
        return True
    return False


async def publish_specific_news(kind: str) -> Optional[NewsPost]:
    """
    Публикует конкретный тип новости (для админ-кнопок).
    Возвращает пост или None при ошибке.
    """
    try:
        if kind == "recruit":
            post = generate_recruit_post()
        elif kind == "event":
            post = generate_event_post()
        elif kind == "analytics":
            snap = await dashboard_stats()
            post = generate_analytics_post(snap)
        elif kind == "social":
            post = generate_social_post()
        else:
            post = generate_random_post()
        ok = await publish_news(post, force=True)
        return post if ok else None
    except Exception as e:
        log_exc("publish_specific_news", e)
        return None


async def news_autopilot_tick() -> None:
    """
    Вызывается планировщиком (ЧАСТЬ 10) раз в NEWS_MIN_INTERVAL_SEC..MAX.
    Выбирает тип с учётом дедупа и публикует.
    Приоритет:
      1) Раз в 12ч — «набор в команду» (если аудитория растёт).
      2) Если давно не было event — анонс.
      3) Иначе — аналитика/social/random.
    """
    try:
        if not NEWS_TARGET_CHAT:
            return
        # 1) Набор в команду — приоритет, если давно не было
        if (time.time() - _news_last_by_kind.get("recruit", 0.0)) >= NEWS_RECRUIT_INTERVAL_SEC:
            post = generate_recruit_post()
            if await publish_news(post):
                return
        # 2) Event — если давно
        if (time.time() - _news_last_by_kind.get("event", 0.0)) >= 6 * 3600:
            post = generate_event_post()
            if await publish_news(post):
                return
        # 3) Аналитика — если давно
        if (time.time() - _news_last_by_kind.get("analytics", 0.0)) >= 6 * 3600:
            snap = await dashboard_stats()
            post = generate_analytics_post(snap)
            if await publish_news(post):
                return
        # 4) Иначе social/random
        post = random.choice((generate_social_post(), generate_random_post))
        if callable(post):
            post = post()
        await publish_news(post)
    except Exception as e:
        log_exc("news_autopilot_tick", e)


# =============================================================================
#  КОНЕЦ ЧАСТИ 4
# =============================================================================
#  ЧАСТЬ 5 подключит: обработчики меню и профиля (start, profile, daily, top, ref).

# =============================================================================
#  ЧАСТЬ 5 / 10 — ОБРАБОТЧИКИ МЕНЮ И ПРОФИЛЯ
#  Содержание:
#    - /start (с рефералкой), /menu, /help
#    - Профиль (детальный), баланс
#    - Дейли-бонус с серией
#    - Топ игроков (пагинация)
#    - Реферальная ссылка
#    - Промокод (через FSM)
#    - Квесты
#    - Callback-роутинг главного меню
#    - Хелперы: user_required, ban_guard, chat_guard
# =============================================================================

# =============================================================================
#  ХЕЛПЕРЫ-ОБЁРТКИ ДЛЯ ХЕНДЛЕРОВ
# =============================================================================

async def _guard_user(message: Message, state: Optional[FSMContext] = None) -> Optional[Dict[str, Any]]:
    """
    Гарантирует юзера в БД. Возвращает dict или None (если забанен/ошибка).
    Заодно чистит FSM, если передан state (при выходе в меню).
    """
    try:
        u = message.from_user
        if u is None:
            return None
        user = await ensure_user(u.id, u.username, u.first_name, u.last_name)
        if int(user.get("is_banned") or 0) == 1:
            with contextlib.suppress(Exception):
                await safe_send_autodelete(
                    message.chat.id,
                    "⛔ Вы заблокированы.",
                    delay=AUTODELETE_SHORT_SEC,
                )
            return None
        if state is not None:
            with contextlib.suppress(Exception):
                await state.clear()
        return user
    except Exception as e:
        log_exc("_guard_user", e)
        return None


async def _guard_cb(cb: CallbackQuery) -> Optional[Dict[str, Any]]:
    """Гарантирует юзера для callback. Уже отвечает на cb."""
    try:
        await cb.answer()
    except Exception:
        pass
    try:
        u = cb.from_user
        if u is None:
            return None
        user = await ensure_user(u.id, u.username, u.first_name, u.last_name)
        if int(user.get("is_banned") or 0) == 1:
            with contextlib.suppress(Exception):
                await safe_send_autodelete(cb.message.chat.id if cb.message else cb.from_user.id,
                                           "⛔ Вы заблокированы.", delay=5)
            return None
        return user
    except Exception as e:
        log_exc("_guard_cb", e)
        return None


def _is_private(chat: Any) -> bool:
    try:
        return getattr(chat, "type", "") == ChatType.PRIVATE
    except Exception:
        return False


# =============================================================================
#  /start
# =============================================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    /start [payload] — регистрация + рефералка.
    payload вида ref_<id> — привязка реферала.
    """
    try:
        u = message.from_user
        if u is None:
            return
        # Парсим payload
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        ref_by: Optional[int] = None
        if payload.startswith("ref_") and payload[4:].isdigit():
            ref_by = int(payload[4:])
            if ref_by == u.id:
                ref_by = None

        user = await ensure_user(u.id, u.username, u.first_name, u.last_name, referral_by=ref_by)
        if int(user.get("is_banned") or 0) == 1:
            await safe_send_autodelete(message.chat.id, "⛔ Вы заблокированы.", delay=5)
            return

        # Рефералка
        if ref_by:
            ok = await register_referral(ref_by, u.id)
            if ok:
                await log_bot_activity("referral_registered", f"ref={ref_by} user={u.id}")

        await state.clear()
        await safe_send(
            message.chat.id,
            TXT_MENU_MAIN,
            reply_markup=kb_main_menu(),
        )
    except Exception as e:
        log_exc("cmd_start", e)
        with contextlib.suppress(Exception):
            await safe_send(message.chat.id, TXT_ERROR)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
        await safe_send(message.chat.id, TXT_MENU_MAIN, reply_markup=kb_main_menu())
    except Exception as e:
        log_exc("cmd_menu", e)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Доступные команды:\n"
        "/start — регистрация\n"
        "/menu — главное меню\n"
        "/profile — профиль\n"
        "/balance — баланс\n"
        "/daily — ежедневный бонус\n"
        "/top — топ игроков\n"
        "/ref — реферальная ссылка\n"
        "/promo <code> — активировать промокод\n"
        "/quests — квесты на сегодня\n"
        "/help — эта справка\n\n"
        "Игры:\n"
        "🎡 Рулетка — выбор типа ставки\n"
        "🎲 Кубики — дуэль с казино\n"
        "💣 Мины — 5x5, множитель растёт\n"
        "⚔️ Дуэль — 1 на 1 с другим игроком\n\n"
        "💸 <code>@перевод 5000</code> (в ответ на сообщение) — перевод\n"
    )
    await safe_send_autodelete(message.chat.id, text, delay=120)


# =============================================================================
#  ПРОФИЛЬ
# =============================================================================

def _fmt_profile(user: Dict[str, Any], refs: int) -> str:
    vip = "✅ Да" if int(user.get("vip") or 0) == 1 else "❌ Нет"
    return TXT_PROFILE.format(
        user_id=user["user_id"],
        balance=fmt_int(user["balance"]),
        vip=vip,
        games=int(user.get("games_played") or 0),
        wins=int(user.get("games_won") or 0),
        refs=refs,
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        refs = await count_referrals(user["user_id"])
        text = _fmt_profile(user, refs)
        await safe_send_autodelete(
            message.chat.id,
            text,
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_back_menu(),
        )
    except Exception as e:
        log_exc("cmd_profile", e)


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        await safe_send_autodelete(
            message.chat.id,
            f"💰 Баланс: <b>{fmt_int(user['balance'])}</b> TOKENS",
            delay=AUTODELETE_SHORT_SEC,
        )
    except Exception as e:
        log_exc("cmd_balance", e)


@router.callback_query(F.data == cb_build("menu", "profile"))
async def cb_profile(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        refs = await count_referrals(user["user_id"])
        text = _fmt_profile(user, refs)
        await safe_edit_or_send(
            cb.message.chat.id,
            cb.message.message_id,
            text,
            reply_markup=kb_back_menu(),
        )
    except Exception as e:
        log_exc("cb_profile", e)


@router.callback_query(F.data == cb_build("menu", "main"))
async def cb_main_menu(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        await state.clear()
        if cb.message is None:
            return
        await safe_edit_or_send(
            cb.message.chat.id,
            cb.message.message_id,
            TXT_MENU_MAIN,
            reply_markup=kb_main_menu(),
        )
    except Exception as e:
        log_exc("cb_main_menu", e)


# =============================================================================
#  ЕЖЕДНЕВНЫЙ БОНУС
# =============================================================================

def _daily_reward(streak: int) -> int:
    """Бонус растёт со стриком: base * (1 + 0.1*min(streak, 14))."""
    mult = 1.0 + 0.10 * min(max(streak, 0), 14)
    return int(DAILY_BONUS_BASE * mult)


async def _claim_daily(user_id: int) -> Tuple[bool, int, int, int]:
    """
    Возвращает (ok, amount, streak, seconds_until_next).
    ok=False — слишком рано; seconds_until_next — сколько ждать.
    """
    try:
        now = now_ts()
        async with db_conn() as conn:
            async with conn.execute(
                "SELECT streak, last_claim FROM daily_bonus WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            streak = int(row["streak"]) if row else 0
            last = float(row["last_claim"]) if row else 0.0
            # Кулдаун 22 часа
            cooldown = 22 * 3600
            if now - last < cooldown:
                return False, 0, streak, int(cooldown - (now - last))
            # Проверим, не сбросить ли стрик (24ч+6ч форы)
            if last > 0 and (now - last) > (24 + 6) * 3600:
                streak = 0
            streak += 1
            amount = _daily_reward(streak)
            await conn.execute(
                "INSERT INTO daily_bonus (user_id, streak, last_claim, total_claims) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "streak = excluded.streak, last_claim = excluded.last_claim, "
                "total_claims = daily_bonus.total_claims + 1",
                (user_id, streak, now),
            )
        await add_balance(user_id, amount, reason="daily")
        return True, amount, streak, 0
    except Exception as e:
        log_exc("_claim_daily", e)
        return False, 0, 0, 0


async def _daily_status(user_id: int) -> Tuple[int, int]:
    """Возвращает (streak, seconds_until_next). 0 — доступно сейчас."""
    try:
        async with db_conn() as conn:
            async with conn.execute(
                "SELECT streak, last_claim FROM daily_bonus WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return 0, 0
        streak = int(row["streak"])
        last = float(row["last_claim"])
        wait = int(max(0, 22 * 3600 - (now_ts() - last)))
        return streak, wait
    except Exception as e:
        log_exc("_daily_status", e)
        return 0, 0


@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        ok, amount, streak, wait = await _claim_daily(user["user_id"])
        if not ok:
            h, m = wait // 3600, (wait % 3600) // 60
            await safe_send_autodelete(
                message.chat.id,
                TXT_DAILY_WAIT.format(hours=h, minutes=m),
                delay=AUTODELETE_SHORT_SEC,
            )
            return
        await safe_send_autodelete(
            message.chat.id,
            f"🎁 Ежедневный бонус получен!\n"
            f"🔥 Серия: <b>{streak}</b>\n"
            f"💰 Начислено: <b>+{fmt_int(amount)}</b> TOKENS",
            delay=AUTODELETE_DEFAULT_SEC,
        )
        await log_game(user["user_id"], message.chat.id, "daily", 0, "win", amount)
    except Exception as e:
        log_exc("cmd_daily", e)


@router.callback_query(F.data == cb_build("menu", "daily"))
async def cb_daily(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None:
            return
        ok, amount, streak, wait = await _claim_daily(user["user_id"])
        if not ok:
            h, m = wait // 3600, (wait % 3600) // 60
            await safe_answer_cb(cb, f"⏳ Через {h} ч {m} мин", alert=True)
            return
        await safe_answer_cb(cb, f"🎁 +{fmt_int(amount)} TOKENS (серия {streak})", alert=True)
        if cb.message is not None:
            await safe_edit_or_send(
                cb.message.chat.id,
                cb.message.message_id,
                f"🎁 <b>Бонус получен!</b>\n"
                f"🔥 Серия: <b>{streak}</b>\n"
                f"💰 Начислено: <b>+{fmt_int(amount)}</b> TOKENS",
                reply_markup=kb_back_menu(),
            )
    except Exception as e:
        log_exc("cb_daily", e)


# =============================================================================
#  ТОП ИГРОКОВ (с пагинацией)
# =============================================================================

def kb_top_pager(page: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if page > 0:
        b.button(text="◀️", callback_data=cb_build("top", "page", page - 1))
    b.button(text=f"{page + 1}", callback_data=cb_build("top", "noop"))
    b.button(text="▶️", callback_data=cb_build("top", "page", page + 1))
    b.button(text=BTN_MENU, callback_data=cb_build("menu", "main"))
    b.adjust(3, 1)
    return b.as_markup()


async def _render_top(page: int) -> str:
    page = max(0, page)
    offset = page * PAGE_SIZE
    rows = await _fetchall(
        "SELECT user_id, username, first_name, balance, games_won, vip "
        "FROM users WHERE balance > 0 ORDER BY balance DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, offset),
    )
    lines = [f"🏆 <b>Топ игроков</b> — стр. {page + 1}\n"]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for i, r in enumerate(rows, start=offset + 1):
            name = r["username"] and f"@{r['username']}" or (r["first_name"] or f"id{r['user_id']}")
            vip = " ⭐️" if int(r["vip"] or 0) == 1 else ""
            lines.append(
                f"{i}. {html_escape(name)}{vip} — <b>{fmt_int(r['balance'])}</b> "
                f"(побед: {int(r['games_won'] or 0)})"
            )
    return "\n".join(lines)


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    try:
        text = await _render_top(0)
        await safe_send_autodelete(
            message.chat.id,
            text,
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_top_pager(0),
        )
    except Exception as e:
        log_exc("cmd_top", e)


@router.callback_query(F.data.startswith(cb_build("top", "page")[:6]))
async def cb_top_page(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        parts = cb_parse(cb.data or "")
        page = int(parts[2]) if len(parts) >= 3 and parts[2].lstrip("-").isdigit() else 0
        page = max(0, page)
        if cb.message is None:
            return
        text = await _render_top(page)
        await safe_edit_or_send(
            cb.message.chat.id,
            cb.message.message_id,
            text,
            reply_markup=kb_top_pager(page),
        )
    except Exception as e:
        log_exc("cb_top_page", e)


@router.callback_query(F.data == cb_build("top", "noop"))
async def cb_top_noop(cb: CallbackQuery) -> None:
    await safe_answer_cb(cb)


# =============================================================================
#  РЕФЕРАЛКА
# =============================================================================

async def _make_ref_link(user_id: int) -> str:
    try:
        b = require_bot()
        me = await b.get_me()
        return f"https://t.me/{me.username}?start=ref_{user_id}"
    except Exception as e:
        log_exc("_make_ref_link", e)
        return f"https://t.me/?start=ref_{user_id}"


@router.message(Command("ref"))
async def cmd_ref(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        link = await _make_ref_link(user["user_id"])
        refs = await count_referrals(user["user_id"])
        text = (
            f"🔗 <b>Реферальная программа</b>\n\n"
            f"Приглашено: <b>{refs}</b>\n"
            f"За каждого друга после его первой игры: <b>+{fmt_int(REFERRAL_BONUS)}</b> TOKENS\n\n"
            f"Ваша ссылка:\n<code>{link}</code>"
        )
        await safe_send_autodelete(
            message.chat.id,
            text,
            delay=AUTODELETE_LONG_SEC,
            reply_markup=kb_back_menu(),
        )
    except Exception as e:
        log_exc("cmd_ref", e)


@router.callback_query(F.data == cb_build("menu", "ref"))
async def cb_ref(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        link = await _make_ref_link(user["user_id"])
        refs = await count_referrals(user["user_id"])
        text = (
            f"🔗 <b>Реферальная программа</b>\n\n"
            f"Приглашено: <b>{refs}</b>\n"
            f"За каждого друга после его первой игры: <b>+{fmt_int(REFERRAL_BONUS)}</b> TOKENS\n\n"
            f"Ваша ссылка:\n<code>{link}</code>"
        )
        await safe_edit_or_send(
            cb.message.chat.id,
            cb.message.message_id,
            text,
            reply_markup=kb_back_menu(),
        )
    except Exception as e:
        log_exc("cb_ref", e)


# =============================================================================
#  ПРОМОКОД (команда + FSM)
# =============================================================================

@router.message(Command("promo"))
async def cmd_promo(message: Message, state: FSMContext) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await state.set_state(BetStates.waiting_promo)
            await safe_send_autodelete(
                message.chat.id,
                "🎟 Введите промокод:",
                delay=AUTODELETE_SHORT_SEC,
                reply_markup=kb_cancel(),
            )
            return
        code = parts[1].strip()
        ok, err, amount = await activate_promo(code, user["user_id"])
        if ok:
            await safe_send_autodelete(
                message.chat.id,
                TXT_PROMO_OK.format(amount=fmt_int(amount)),
                delay=AUTODELETE_DEFAULT_SEC,
            )
        else:
            msg = {
                "already_used": TXT_PROMO_USED,
                "expired": TXT_PROMO_INVALID,
                "exhausted": TXT_PROMO_INVALID,
                "not_found": TXT_PROMO_INVALID,
            }.get(err, TXT_ERROR)
            await safe_send_autodelete(message.chat.id, msg, delay=AUTODELETE_SHORT_SEC)
    except Exception as e:
        log_exc("cmd_promo", e)


@router.message(StateFilter(BetStates.waiting_promo), F.text)
async def fsm_promo_code(message: Message, state: FSMContext) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        code = (message.text or "").strip()
        ok, err, amount = await activate_promo(code, user["user_id"])
        await state.clear()
        if ok:
            await safe_send_autodelete(
                message.chat.id,
                TXT_PROMO_OK.format(amount=fmt_int(amount)),
                delay=AUTODELETE_DEFAULT_SEC,
            )
        else:
            msg = {
                "already_used": TXT_PROMO_USED,
                "expired": TXT_PROMO_INVALID,
                "exhausted": TXT_PROMO_INVALID,
                "not_found": TXT_PROMO_INVALID,
            }.get(err, TXT_ERROR)
            await safe_send_autodelete(message.chat.id, msg, delay=AUTODELETE_SHORT_SEC)
    except Exception as e:
        log_exc("fsm_promo_code", e)
        with contextlib.suppress(Exception):
            await state.clear()


# =============================================================================
#  КВЕСТЫ
# =============================================================================

async def _render_quests(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    await ensure_quest_templates()
    quests = await generate_daily_quests(user_id)
    if not quests:
        text = "📜 На сегодня квестов нет. Возвращайтесь завтра!"
        return text, kb_back_menu()
    lines = ["📜 <b>Квесты на сегодня:</b>\n"]
    b = InlineKeyboardBuilder()
    for q in quests:
        progress = int(q["progress"])
        target = int(q["target"])
        reward = int(q["reward"])
        done = progress >= target
        mark = "✅" if done else f"{progress}/{target}"
        lines.append(f"• <code>{q['quest_id']}</code> — {mark} → +{fmt_int(reward)}")
        if done:
            b.button(
                text=f"🎁 Забрать {fmt_int(reward)}",
                callback_data=cb_build("quest", "claim", q["quest_id"]),
            )
    b.button(text=BTN_MENU, callback_data=cb_build("menu", "main"))
    b.adjust(1)
    return "\n".join(lines), b.as_markup()


@router.message(Command("quests"))
async def cmd_quests(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        text, kb = await _render_quests(user["user_id"])
        await safe_send_autodelete(
            message.chat.id, text, delay=AUTODELETE_LONG_SEC, reply_markup=kb,
        )
    except Exception as e:
        log_exc("cmd_quests", e)


@router.callback_query(F.data.startswith("quest:claim"))
async def cb_quest_claim(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 3:
            return
        quest_id = parts[2]
        ok, reward = await claim_quest_reward(user["user_id"], quest_id)
        if ok:
            await safe_answer_cb(cb, f"🎁 +{fmt_int(reward)} TOKENS", alert=True)
        else:
            await safe_answer_cb(cb, "Уже забрано или не выполнено", alert=True)
        text, kb = await _render_quests(user["user_id"])
        await safe_edit_or_send(cb.message.chat.id, cb.message.message_id, text, reply_markup=kb)
    except Exception as e:
        log_exc("cb_quest_claim", e)


# =============================================================================
#  CANCEL
# =============================================================================

@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb, TXT_CANCELLED)
        await state.clear()
        if cb.message is not None:
            await safe_edit_or_send(
                cb.message.chat.id,
                cb.message.message_id,
                TXT_MENU_MAIN,
                reply_markup=kb_main_menu(),
            )
    except Exception as e:
        log_exc("cb_cancel", e)


# =============================================================================
#  КОНЕЦ ЧАСТИ 5
# =============================================================================
#  ЧАСТЬ 6 подключит: игры на кубиках с корректным автоудалением.

# =============================================================================
#  ЧАСТЬ 6 / 10 — ИГРЫ НА КУБИКАХ
#  Содержание:
#    - Дуэль с казино (🎲): user vs bot, автоудаление
#    - Darts (🎯) и Basketball (🏀) как альтернативные кубики
#    - FSM: ожидание суммы ставки
#    - Антиспам 3 сек, атомарное списание, защита от двойного клика
#    - ВСЕГДА новое сообщение с кубиком (никогда edit), результат — отдельно
#    - Псевдо-ИИ реакции: крупный выигрыш/проигрыш -> пост в чат
# =============================================================================

# --- Конфиг кубиков --------------------------------------------------------
DICE_EMOJI: str = "🎲"
DART_EMOJI: str = "🎯"
BASKET_EMOJI: str = "🏀"
DICE_MAX_VALUE: Dict[str, int] = {
    "🎲": 6,
    "🎯": 6,
    "🏀": 5,
    "⚽️": 5,
    "🎰": 64,
    "🎳": 6,
}
# Победный исход — строго больше. Равные значения у 🎲/🎯/🎳 — ничья.
# Для баскетбола/футбола больше = лучше.

# Порог «крупного» выигрыша для триггера нейро-реакции
BIG_WIN_THRESHOLD: int = 50_000
BIG_LOSS_THRESHOLD: int = 50_000


# =============================================================================
#  ВСПОМОГАТЕЛЬНОЕ: проверить ставку
# =============================================================================

async def _validate_bet(user: Dict[str, Any], bet: int) -> Optional[str]:
    """Возвращает текст ошибки или None, если ставка валидна."""
    if bet < MIN_BET:
        return TXT_INVALID_BET_RANGE
    if bet > MAX_BET:
        return TXT_INVALID_BET_RANGE
    if int(user["balance"]) < bet:
        return TXT_NOT_ENOUGH
    return None


# =============================================================================
#  ВХОД В РЕЖИМ КУБИКОВ
# =============================================================================

@router.callback_query(F.data == cb_build("menu", "dice"))
async def cb_dice_menu(cb: CallbackQuery, state: FSMContext) -> None:
    """Показываем выбор суммы ставки для кубиков."""
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        await state.clear()
        await state.update_data(game="dice", bet=None)
        await state.set_state(BetStates.waiting_amount)
        text = (
            "🎲 <b>Кубики</b>\n\n"
            "Бросаем кубик. У кого больше — тот забирает ставку.\n"
            "Ничья — возврат.\n\n"
            f"Минимальная ставка: <b>{fmt_int(MIN_BET)}</b>\n"
            f"Максимальная: <b>{fmt_int(MAX_BET)}</b>\n\n"
            "Выберите сумму или введите своё:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_bet_amounts("dice"),
        )
    except Exception as e:
        log_exc("cb_dice_menu", e)


@router.callback_query(F.data.startswith("dice:amt:"))
async def cb_dice_amount(cb: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал быструю сумму."""
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        raw = parts[2] if len(parts) >= 3 else ""
        if raw == "all":
            bet = int(user["balance"])
        else:
            bet = int(raw) if raw.isdigit() else 0
        if bet <= 0:
            await safe_answer_cb(cb, TXT_INVALID_AMOUNT, alert=True)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_answer_cb(cb, err, alert=True)
            return
        await state.clear()
        await _play_dice(cb.message.chat.id, user, bet, cb.message.message_id)
    except Exception as e:
        log_exc("cb_dice_amount", e)


@router.message(StateFilter(BetStates.waiting_amount), F.text)
async def fsm_dice_amount(message: Message, state: FSMContext) -> None:
    """Ввод суммы вручную."""
    try:
        data = await state.get_data()
        if data.get("game") != "dice":
            return  # не наш сценарий
        user = await _guard_user(message)
        if user is None:
            return
        bet = parse_amount(message.text or "")
        if bet is None:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_send_autodelete(message.chat.id, err, delay=5)
            return
        await state.clear()
        await _play_dice(message.chat.id, user, bet, None, reply_to=message.message_id)
    except Exception as e:
        log_exc("fsm_dice_amount", e)


# =============================================================================
#  ЛОГИКА БРОСКА КУБИКОВ
# =============================================================================

async def _play_dice(
    chat_id: int,
    user: Dict[str, Any],
    bet: int,
    edit_message_id: Optional[int] = None,
    *,
    emoji: str = DICE_EMOJI,
    reply_to: Optional[int] = None,
) -> None:
    """
    Полный цикл игры в кубики.
    ВАЖНО:
      - Списываем ДО броска (атомарно).
      - Отправляем кубик как НОВОЕ сообщение (никаких edit).
      - Ждём value, считаем результат.
      - Результат — отдельным сообщением с автоудалением.
    """
    uid = int(user["user_id"])
    try:
        # Антиспам
        if not await check_game_antispam(uid):
            await safe_send_autodelete(chat_id, TXT_ANTISPAM, delay=3)
            return

        # Атомарное списание
        ok, new_balance = await try_withdraw(uid, bet, reason="dice_bet")
        if not ok:
            await safe_send_autodelete(chat_id, TXT_NOT_ENOUGH, delay=5)
            return

        # Отправляем кубик (новое сообщение!)
        dice_msg = await safe_send_dice(chat_id, emoji=emoji, reply_to=reply_to)
        if dice_msg is None:
            # Возврат ставки при сбое
            await add_balance(uid, bet, reason="dice_refund_error")
            await safe_send_autodelete(chat_id, TXT_ERROR, delay=5)
            return

        my_value = int(getattr(dice_msg, "dice", None).value) if getattr(dice_msg, "dice", None) else 0

        # Бросок казино
        await asyncio.sleep(0.5)
        bot_dice = await safe_send_dice(chat_id, emoji=emoji)
        if bot_dice is None or getattr(bot_dice, "dice", None) is None:
            await add_balance(uid, bet, reason="dice_refund_bot_error")
            await safe_send_autodelete(chat_id, "⚠️ Ошибка казино. Ставка возвращена.", delay=5)
            return
        their_value = int(bot_dice.dice.value)

        # Подсчёт
        if my_value > their_value:
            result = "win"
            commission = await get_chat_commission(chat_id)
            payout = int(bet * 2 * (1 - commission))
            await add_balance(uid, payout, reason="dice_win")
            delta = payout - bet
            outcome_text = TXT_DICE_WIN.format(amount=fmt_int(payout))
        elif my_value < their_value:
            result = "lose"
            delta = -bet
            outcome_text = TXT_DICE_LOSE.format(amount=fmt_int(bet))
            # 1% в джекпот
            jp = max(1, int(bet * JACKPOT_PERCENT))
            await jackpot_add(jp)
        else:
            result = "draw"
            await add_balance(uid, bet, reason="dice_draw")
            delta = 0
            outcome_text = TXT_DICE_DRAW

        # Лог игры
        await log_game(uid, chat_id, "dice", bet, result, delta, meta=f"{my_value}:{their_value}")
        # Винстрик
        streak = await update_win_streak(uid, chat_id, won=(result == "win"))
        # Квесты
        with contextlib.suppress(Exception):
            await quest_progress(uid, "place_bets", bet)
            if result == "win":
                await quest_progress(uid, "win_games", 1)

        # Итоговое сообщение (отдельно!)
        text = TXT_DICE_RESULT.format(
            mine=my_value, theirs=their_value, outcome=outcome_text,
        )
        await safe_send_autodelete(
            chat_id, text, delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_dice_again(bet),
        )

        # Псевдо-ИИ реакции
        with contextlib.suppress(Exception):
            if delta >= BIG_WIN_THRESHOLD:
                name = safe_name_from_dict(user)
                phrase = random.choice(NEURO_BIG_WIN_PHRASES).format(
                    name=html_escape(name), amount=fmt_int(delta),
                )
                await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)
            elif delta <= -BIG_LOSS_THRESHOLD:
                name = safe_name_from_dict(user)
                phrase = random.choice(NEURO_BIG_LOSS_PHRASES).format(
                    name=html_escape(name), amount=fmt_int(-delta),
                )
                await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)

    except Exception as e:
        log_exc("_play_dice", e)
        # Возврат ставки при любой ошибке (best-effort, без двойного возврата)
        with contextlib.suppress(Exception):
            await add_balance(uid, bet, reason="dice_refund_crash")


@router.callback_query(F.data.startswith("dice:again:"))
async def cb_dice_again(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        bet = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
        if bet <= 0:
            return
        if int(user["balance"]) < bet:
            await safe_answer_cb(cb, TXT_NOT_ENOUGH, alert=True)
            return
        await _play_dice(cb.message.chat.id, user, bet, cb.message.message_id)
    except Exception as e:
        log_exc("cb_dice_again", e)


# =============================================================================
#  ХЕЛПЕР: имя из dict-пользователя
# =============================================================================

def safe_name_from_dict(user: Dict[str, Any]) -> str:
    if not user:
        return "unknown"
    if user.get("username"):
        return f"@{user['username']}"
    parts = [user.get("first_name") or "", user.get("last_name") or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or f"id{user.get('user_id', '?')}"


# =============================================================================
#  КОНЕЦ ЧАСТИ 6
# =============================================================================
#  ЧАСТЬ 7 подключит: Мины, Дуэли, Переводы.

# =============================================================================
#  ЧАСТЬ 7 / 10 — МИНЫ, ДУЭЛИ, ПЕРЕВОДЫ
#  Содержание:
#    - МИНЫ 5x5: полноценная игра с множителями, касс-аутом, полем кнопок.
#    - ДУЭЛИ: 1v1, ожидание соперника, защита от double-join, авто-возврат.
#    - ПЕРЕВОДЫ: @перевод <сумма> в ответ на сообщение.
#    - In-memory состояние минных игр (с TTL) и дуэльных лобби.
#    - Антиспам, атомарные списания/начисления, лог игр, квесты, винстрики.
#    - Полная обработка ошибок и корректное автоудаление сообщений.
# =============================================================================

# =============================================================================
#  ЧАСТЬ 7.1 — МИНЫ 5x5
# =============================================================================
#  Правила:
#    - Игрок выбирает ставку и количество мин (от 1 до 24).
#    - Открывает клетки. За каждую безопасную — множитель растёт.
#    - Попал на мину — теряет всё.
#    - Нажал "Забрать" — забирает ставка * текущий_множитель.
#  Множитель считается по гипергеометрии:
#    mult = C(25, k) / C(25 - mines, k), где k — число открытых клеток.
#    Комиссия казино вычитается при касс-ауте (не при списании).

MINES_SIZE: int = 25          # 5x5
MINES_MIN_COUNT: int = 1
MINES_MAX_COUNT: int = 24
MINES_TTL_SEC: int = 3600     # заброшенная игра умирает через час
MINES_CACHE_LIMIT: int = 5000 # максимум активных игр в памяти


@dataclass
class MinesGame:
    game_key: str
    user_id: int
    chat_id: int
    bet: int
    mines_count: int
    mines_positions: Set[int]
    opened: Set[int] = field(default_factory=set)
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    message_id: Optional[int] = None


# game_key -> MinesGame
_mines_games: Dict[str, MinesGame] = {}
_mines_guard = asyncio.Lock()


def _mines_new_key(user_id: int) -> str:
    """Короткий уникальный ключ, укладывается в 64 байта callback_data."""
    return f"{user_id:x}{random.randint(100, 999)}"


def _mines_generate(mines_count: int) -> Set[int]:
    """Случайные позиции мин. Без numpy — просто sample из range(25)."""
    return set(random.sample(range(MINES_SIZE), mines_count))


def _mines_multiplier(opened_k: int, mines_count: int) -> float:
    """
    Справедливый множитель: C(25, k) / C(25 - mines, k).
    При k=0 -> 1.0. Растёт по мере открытия клеток.
    """
    if opened_k <= 0:
        return 1.0
    try:
        total = math.comb(MINES_SIZE, opened_k)
        safe = math.comb(MINES_SIZE - mines_count, opened_k)
        if safe <= 0:
            return 1.0
        return float(total) / float(safe)
    except Exception:
        return 1.0


async def _mines_store(game: MinesGame) -> None:
    async with _mines_guard:
        if len(_mines_games) >= MINES_CACHE_LIMIT:
            # Чистим старые/завершённые
            now = time.time()
            dead = [
                k for k, g in _mines_games.items()
                if g.finished or (now - g.started_at) > MINES_TTL_SEC
            ]
            for k in dead:
                _mines_games.pop(k, None)
        _mines_games[game.game_key] = game


async def _mines_get(game_key: str) -> Optional[MinesGame]:
    async with _mines_guard:
        return _mines_games.get(game_key)


async def _mines_drop(game_key: str) -> None:
    async with _mines_guard:
        _mines_games.pop(game_key, None)


# --- Вход в мины -----------------------------------------------------------

@router.callback_query(F.data == cb_build("menu", "mines"))
async def cb_mines_menu(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        await state.clear()
        await state.update_data(game="mines", bet=None)
        await state.set_state(BetStates.waiting_amount)
        text = (
            "💣 <b>Мины 5x5</b>\n\n"
            "Открывай клетки, не попав на мину. Множитель растёт с каждой\n"
            "безопасной клеткой. В любой момент можно забрать выигрыш.\n\n"
            f"Мин: <b>1–{MINES_MAX_COUNT}</b> (случайно)\n"
            f"Ставка: <b>{fmt_int(MIN_BET)}</b> – <b>{fmt_int(MAX_BET)}</b>\n\n"
            "Выберите сумму:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_bet_amounts("mn"),
        )
    except Exception as e:
        log_exc("cb_mines_menu", e)


@router.callback_query(F.data.startswith("mn:amt:"))
async def cb_mines_amount(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        raw = parts[2] if len(parts) >= 3 else ""
        bet = int(user["balance"]) if raw == "all" else (int(raw) if raw.isdigit() else 0)
        if bet <= 0:
            await safe_answer_cb(cb, TXT_INVALID_AMOUNT, alert=True)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_answer_cb(cb, err, alert=True)
            return
        # Спрашиваем количество мин
        await state.update_data(game="mines", bet=bet)
        b = InlineKeyboardBuilder()
        for n in (1, 2, 3, 5, 8, 12, 18, 24):
            b.button(text=str(n), callback_data=cb_build("mn", "start", bet, n))
        b.button(text=BTN_CANCEL, callback_data=cb_build("cancel", "1"))
        b.adjust(4, 4, 1)
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id,
            f"💣 Ставка: <b>{fmt_int(bet)}</b> TOKENS\nСколько мин?",
            reply_markup=b.as_markup(),
        )
    except Exception as e:
        log_exc("cb_mines_amount", e)


@router.message(StateFilter(BetStates.waiting_amount), F.text)
async def fsm_mines_amount(message: Message, state: FSMContext) -> None:
    try:
        data = await state.get_data()
        if data.get("game") != "mines":
            return
        user = await _guard_user(message)
        if user is None:
            return
        bet = parse_amount(message.text or "")
        if bet is None:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_send_autodelete(message.chat.id, err, delay=5)
            return
        await state.update_data(game="mines", bet=bet)
        b = InlineKeyboardBuilder()
        for n in (1, 2, 3, 5, 8, 12, 18, 24):
            b.button(text=str(n), callback_data=cb_build("mn", "start", bet, n))
        b.button(text=BTN_CANCEL, callback_data=cb_build("cancel", "1"))
        b.adjust(4, 4, 1)
        await safe_send_autodelete(
            message.chat.id,
            f"💣 Ставка: <b>{fmt_int(bet)}</b> TOKENS\nСколько мин?",
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=b.as_markup(),
        )
    except Exception as e:
        log_exc("fsm_mines_amount", e)


# --- Старт игры -------------------------------------------------------------

async def _start_mines(
    chat_id: int,
    user: Dict[str, Any],
    bet: int,
    mines_count: int,
) -> None:
    uid = int(user["user_id"])
    try:
        if not await check_game_antispam(uid):
            await safe_send_autodelete(chat_id, TXT_ANTISPAM, delay=3)
            return
        mines_count = max(MINES_MIN_COUNT, min(MINES_MAX_COUNT, int(mines_count)))
        ok, _ = await try_withdraw(uid, bet, reason="mines_bet")
        if not ok:
            await safe_send_autodelete(chat_id, TXT_NOT_ENOUGH, delay=5)
            return
        game = MinesGame(
            game_key=_mines_new_key(uid),
            user_id=uid,
            chat_id=chat_id,
            bet=bet,
            mines_count=mines_count,
            mines_positions=_mines_generate(mines_count),
        )
        await _mines_store(game)
        text = TXT_MINES_INTRO.format(bet=fmt_int(bet), mines=mines_count)
        sent = await safe_send(
            chat_id,
            text,
            reply_markup=kb_mines_field(game.opened, game_key=game.game_key),
        )
        if not sent:
            await add_balance(uid, bet, reason="mines_refund_no_msg")
            await _mines_drop(game.game_key)
            return
        game.message_id = sent[-1].message_id
        # После первого поля вешаем действия
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=game.message_id,
                reply_markup=kb_mines_field(game.opened, game_key=game.game_key),
            )
    except Exception as e:
        log_exc("_start_mines", e)
        with contextlib.suppress(Exception):
            await add_balance(uid, bet, reason="mines_refund_crash")


@router.callback_query(F.data.startswith("mn:start:"))
async def cb_mines_start(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 4:
            return
        bet = int(parts[2]) if parts[2].isdigit() else 0
        mines = int(parts[3]) if parts[3].isdigit() else 0
        if bet <= 0 or mines <= 0:
            return
        if int(user["balance"]) < bet:
            await safe_answer_cb(cb, TXT_NOT_ENOUGH, alert=True)
            return
        await state.clear()
        await _start_mines(cb.message.chat.id, user, bet, mines)
    except Exception as e:
        log_exc("cb_mines_start", e)


# --- Открытие клетки / касс-аут / сдаться ---------------------------------

@router.callback_query(F.data.startswith("mn:open:"))
async def cb_mines_open(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 4:
            return
        game_key = parts[2]
        idx = int(parts[3]) if parts[3].isdigit() else -1
        if idx < 0 or idx >= MINES_SIZE:
            return
        game = await _mines_get(game_key)
        if game is None or game.finished:
            await safe_answer_cb(cb, "Игра уже завершена", alert=True)
            return
        if game.user_id != int(user["user_id"]):
            await safe_answer_cb(cb, "Это не ваша игра", alert=True)
            return
        if idx in game.opened:
            await safe_answer_cb(cb, "Клетка уже открыта", alert=True)
            return
        if idx in game.mines_positions:
            # Взрыв
            game.finished = True
            await _mines_drop(game_key)
            # Показываем все мины
            final_kb = InlineKeyboardBuilder()
            for i in range(MINES_SIZE):
                if i in game.mines_positions:
                    final_kb.button(text="💥", callback_data=cb_build("mn", "noop", game_key, i))
                elif i in game.opened:
                    final_kb.button(text="✅", callback_data=cb_build("mn", "noop", game_key, i))
                else:
                    final_kb.button(text="⬜", callback_data=cb_build("mn", "noop", game_key, i))
            final_kb.adjust(5, 5, 5, 5, 5)
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(
                    chat_id=game.chat_id,
                    message_id=cb.message.message_id,
                    reply_markup=final_kb.as_markup(),
                )
            await log_game(game.user_id, game.chat_id, "mines", game.bet, "lose", -game.bet,
                           meta=f"mines={game.mines_count}, opened={len(game.opened)}")
            jp = max(1, int(game.bet * JACKPOT_PERCENT))
            await jackpot_add(jp)
            with contextlib.suppress(Exception):
                await quest_progress(game.user_id, "place_bets", game.bet)
                await quest_progress(game.user_id, "play_mines", 1)
            await safe_send_autodelete(
                game.chat_id,
                TXT_MINES_HIT.format(amount=fmt_int(game.bet)),
                delay=AUTODELETE_DEFAULT_SEC,
            )
            # Нейро-реакция
            with contextlib.suppress(Exception):
                if game.bet >= BIG_LOSS_THRESHOLD:
                    name = safe_name_from_dict(user)
                    phrase = random.choice(NEURO_BIG_LOSS_PHRASES).format(
                        name=html_escape(name), amount=fmt_int(game.bet),
                    )
                    await safe_send_autodelete(game.chat_id, phrase, delay=AUTODELETE_LONG_SEC)
            return
        # Безопасная клетка
        game.opened.add(idx)
        # Множитель после этого открытия
        mult = _mines_multiplier(len(game.opened), game.mines_count)
        # Обновляем поле
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(
                chat_id=game.chat_id,
                message_id=cb.message.message_id,
                reply_markup=kb_mines_field(game.opened, game_key=game.game_key),
            )
        # Если открыли все безопасные клетки — авто-касс-аут
        safe_total = MINES_SIZE - game.mines_count
        if len(game.opened) >= safe_total:
            await _mines_cashout(game, auto=True)
            return
        # Действия: забрать доступно всегда после 1 открытия
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(
                chat_id=game.chat_id,
                message_id=cb.message.message_id,
                reply_markup=kb_mines_field(game.opened, game_key=game.game_key),
            )
        await safe_answer_cb(
            cb,
            f"✅ Безопасно. Множитель: x{mult:.2f} "
            f"(потенциал: {fmt_int(int(game.bet * mult))})",
        )
    except Exception as e:
        log_exc("cb_mines_open", e)


async def _mines_cashout(game: MinesGame, auto: bool = False) -> None:
    """Забирает выигрыш по текущему множителю."""
    if game.finished:
        return
    game.finished = True
    try:
        mult = _mines_multiplier(len(game.opened), game.mines_count)
        commission = await get_chat_commission(game.chat_id)
        gross = int(game.bet * mult)
        payout = int(gross * (1 - commission)) if len(game.opened) > 0 else game.bet
        delta = payout - game.bet
        if delta > 0:
            await add_balance(game.user_id, payout, reason="mines_cashout")
        elif delta < 0:
            # Страховка: не уходим в минус
            await add_balance(game.user_id, payout, reason="mines_cashout")
        await log_game(
            game.user_id, game.chat_id, "mines", game.bet,
            "win" if delta >= 0 else "lose", delta,
            meta=f"mines={game.mines_count}, opened={len(game.opened)}, mult={mult:.3f}",
        )
        with contextlib.suppress(Exception):
            await quest_progress(game.user_id, "place_bets", game.bet)
            await quest_progress(game.user_id, "win_games", 1)
        with contextlib.suppress(Exception):
            await update_win_streak(game.user_id, game.chat_id, won=(delta >= 0))
        # Показываем мины и результат
        final_kb = InlineKeyboardBuilder()
        for i in range(MINES_SIZE):
            if i in game.mines_positions:
                final_kb.button(text="💥", callback_data=cb_build("mn", "noop", game.game_key, i))
            elif i in game.opened:
                final_kb.button(text="✅", callback_data=cb_build("mn", "noop", game.game_key, i))
            else:
                final_kb.button(text="⬜", callback_data=cb_build("mn", "noop", game.game_key, i))
        final_kb.adjust(5, 5, 5, 5, 5)
        if game.message_id:
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(
                    chat_id=game.chat_id,
                    message_id=game.message_id,
                    reply_markup=final_kb.as_markup(),
                )
        prefix = "🎉 Авто-касс-аут!" if auto else "💰"
        await safe_send_autodelete(
            game.chat_id,
            f"{prefix} Забрали: <b>+{fmt_int(payout)}</b> TOKENS (x{mult:.2f})\n"
            f"Ставка: {fmt_int(game.bet)}, мин: {game.mines_count}",
            delay=AUTODELETE_LONG_SEC,
            reply_markup=kb_back_menu(),
        )
        # Псевдо-ИИ реакция на крупный выигрыш
        with contextlib.suppress(Exception):
            if delta >= BIG_WIN_THRESHOLD:
                u = await get_user(game.user_id)
                name = safe_name_from_dict(u or {})
                phrase = random.choice(NEURO_BIG_WIN_PHRASES).format(
                    name=html_escape(name), amount=fmt_int(delta),
                )
                await safe_send_autodelete(game.chat_id, phrase, delay=AUTODELETE_LONG_SEC)
    except Exception as e:
        log_exc("_mines_cashout", e)
    finally:
        await _mines_drop(game.game_key)


@router.callback_query(F.data.startswith("mn:cash:"))
async def cb_mines_cash(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 3:
            return
        game = await _mines_get(parts[2])
        if game is None or game.finished or game.user_id != int(user["user_id"]):
            await safe_answer_cb(cb, "Игра недоступна", alert=True)
            return
        if len(game.opened) == 0:
            await safe_answer_cb(cb, "Откройте хотя бы одну клетку", alert=True)
            return
        await _mines_cashout(game, auto=False)
    except Exception as e:
        log_exc("cb_mines_cash", e)


@router.callback_query(F.data.startswith("mn:giveup:"))
async def cb_mines_giveup(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 3:
            return
        game = await _mines_get(parts[2])
        if game is None or game.finished or game.user_id != int(user["user_id"]):
            await safe_answer_cb(cb, "Игра недоступна", alert=True)
            return
        # Сдача = потеря ставки
        game.finished = True
        await _mines_drop(game.game_key)
        with contextlib.suppress(Exception):
            await log_game(game.user_id, game.chat_id, "mines", game.bet, "lose", -game.bet,
                           meta=f"giveup, mines={game.mines_count}, opened={len(game.opened)}")
            jp = max(1, int(game.bet * JACKPOT_PERCENT))
            await jackpot_add(jp)
        await safe_send_autodelete(
            game.chat_id,
            f"🏳️ Сдались. Потеряно <b>{fmt_int(game.bet)}</b> TOKENS.",
            delay=AUTODELETE_DEFAULT_SEC,
        )
    except Exception as e:
        log_exc("cb_mines_giveup", e)


@router.callback_query(F.data.startswith("mn:noop:"))
async def cb_mines_noop(cb: CallbackQuery) -> None:
    await safe_answer_cb(cb)


# =============================================================================
#  ЧАСТЬ 7.2 — ДУЭЛИ 1v1
# =============================================================================
#  Правила:
#    - Игрок A создаёт лобби со ставкой.
#    - Игрок B нажимает «Принять», если у него достаточно баланса.
#    - Оба бросают кубик; у кого больше — забирает банк минус комиссия.
#    - Ничья — возврат обоим.
#    - Через 30 сек без соперника — авто-отмена и возврат.

DUEL_TIMEOUT_SEC: int = 30


@dataclass
class Duel:
    owner_id: int
    chat_id: int
    bet: int
    message_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    finished: bool = False


# owner_id -> Duel
_duels: Dict[int, Duel] = {}
_duels_guard = asyncio.Lock()


async def _duel_timeout_watch(duel: Duel) -> None:
    """Фон: через DUEL_TIMEOUT_SEC, если дуэль не закрыта — отменяем и возвращаем."""
    try:
        await asyncio.sleep(DUEL_TIMEOUT_SEC)
        async with _duels_guard:
            cur = _duels.get(duel.owner_id)
            if cur is not duel or cur.finished:
                return
            cur.finished = True
            _duels.pop(duel.owner_id, None)
        await add_balance(duel.owner_id, duel.bet, reason="duel_timeout_refund")
        await safe_send_autodelete(
            duel.chat_id, TXT_DUEL_NO_OPPONENT, delay=AUTODELETE_DEFAULT_SEC,
        )
        with contextlib.suppress(Exception):
            await log_game(duel.owner_id, duel.chat_id, "duel", duel.bet, "draw", 0,
                           meta="timeout")
        if duel.message_id:
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(
                    chat_id=duel.chat_id,
                    message_id=duel.message_id,
                    reply_markup=None,
                )
    except Exception as e:
        log_exc("_duel_timeout_watch", e)


@router.callback_query(F.data == cb_build("menu", "duel"))
async def cb_duel_menu(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        await state.clear()
        await state.update_data(game="duel", bet=None)
        await state.set_state(BetStates.waiting_amount)
        text = (
            "⚔️ <b>Дуэль 1 на 1</b>\n\n"
            "Вы создаёте лобби. Соперник принимает — оба бросают кубик.\n"
            "У кого больше — забирает банк. Ничья — возврат.\n\n"
            "Выберите сумму ставки:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_bet_amounts("duel"),
        )
    except Exception as e:
        log_exc("cb_duel_menu", e)


@router.callback_query(F.data.startswith("duel:amt:"))
async def cb_duel_amount(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        raw = parts[2] if len(parts) >= 3 else ""
        bet = int(user["balance"]) if raw == "all" else (int(raw) if raw.isdigit() else 0)
        if bet <= 0:
            await safe_answer_cb(cb, TXT_INVALID_AMOUNT, alert=True)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_answer_cb(cb, err, alert=True)
            return
        await _create_duel(cb.message.chat.id, user, bet, cb.message.message_id)
    except Exception as e:
        log_exc("cb_duel_amount", e)


async def _create_duel(
    chat_id: int,
    user: Dict[str, Any],
    bet: int,
    edit_message_id: Optional[int] = None,
) -> None:
    uid = int(user["user_id"])
    try:
        if not await check_game_antispam(uid):
            await safe_send_autodelete(chat_id, TXT_ANTISPAM, delay=3)
            return
        async with _duels_guard:
            if uid in _duels and not _duels[uid].finished:
                # Уже есть лобби — не плодим
                raise RuntimeError("У вас уже есть активное лобби")
        ok, _ = await try_withdraw(uid, bet, reason="duel_bet")
        if not ok:
            await safe_send_autodelete(chat_id, TXT_NOT_ENOUGH, delay=5)
            return
        duel = Duel(owner_id=uid, chat_id=chat_id, bet=bet)
        async with _duels_guard:
            _duels[uid] = duel
        text = (
            f"⚔️ <b>Дуэль создана!</b>\n"
            f"Ставка: <b>{fmt_int(bet)}</b> TOKENS\n"
            f"Открыл: {safe_name_from_dict(user)}\n\n"
            f"Ожидаем соперника ({DUEL_TIMEOUT_SEC} сек)..."
        )
        sent = await safe_send(
            chat_id, text,
            reply_markup=kb_duel_join(bet, uid),
        )
        if sent:
            duel.message_id = sent[-1].message_id
        asyncio.create_task(_duel_timeout_watch(duel), name=f"duel_watch:{uid}")
    except Exception as e:
        log_exc("_create_duel", e)
        with contextlib.suppress(Exception):
            await add_balance(uid, bet, reason="duel_refund_crash")


@router.callback_query(F.data.startswith("duel:join:"))
async def cb_duel_join(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 4:
            return
        bet = int(parts[2]) if parts[2].isdigit() else 0
        owner_id = int(parts[3]) if parts[3].lstrip("-").isdigit() else 0
        if bet <= 0 or owner_id == 0:
            return
        joiner_id = int(user["user_id"])
        if joiner_id == owner_id:
            await safe_answer_cb(cb, "Нельзя играть с самим собой", alert=True)
            return
        async with _duels_guard:
            duel = _duels.get(owner_id)
            if duel is None or duel.finished:
                await safe_answer_cb(cb, "Лобби уже закрыто", alert=True)
                return
            if duel.bet != bet:
                await safe_answer_cb(cb, "Ставка изменилась", alert=True)
                return
            # Атомарно помечаем финиш, чтобы не было двойного join
            if duel.finished:
                await safe_answer_cb(cb, "Лобби уже закрыто", alert=True)
                return
            duel.finished = True
            _duels.pop(owner_id, None)
        # Списываем у джойнера
        ok, _ = await try_withdraw(joiner_id, bet, reason="duel_bet")
        if not ok:
            # Возвращаем владельцу и закрываем
            await add_balance(owner_id, bet, reason="duel_refund")
            await safe_answer_cb(cb, TXT_NOT_ENOUGH, alert=True)
            await safe_send_autodelete(
                duel.chat_id, "Соперник не смог оплатить. Лобби закрыто.",
                delay=AUTODELETE_SHORT_SEC,
            )
            return
        # Оба бросают
        try:
            d1 = await safe_send_dice(duel.chat_id, emoji=DICE_EMOJI)
            await asyncio.sleep(0.5)
            d2 = await safe_send_dice(duel.chat_id, emoji=DICE_EMOJI)
            if d1 is None or d2 is None or d1.dice is None or d2.dice is None:
                # Возврат
                await add_balance(owner_id, bet, reason="duel_refund_err")
                await add_balance(joiner_id, bet, reason="duel_refund_err")
                await safe_send_autodelete(duel.chat_id, "⚠️ Ошибка. Ставки возвращены.",
                                           delay=AUTODELETE_SHORT_SEC)
                return
            v1, v2 = int(d1.dice.value), int(d2.dice.value)
            commission = await get_chat_commission(duel.chat_id)
            pot = bet * 2
            if v1 == v2:
                await add_balance(owner_id, bet, reason="duel_draw")
                await add_balance(joiner_id, bet, reason="duel_draw")
                await log_game(owner_id, duel.chat_id, "duel", bet, "draw", 0, meta=f"{v1}:{v2}")
                await log_game(joiner_id, duel.chat_id, "duel", bet, "draw", 0, meta=f"{v1}:{v2}")
                text = f"🤝 Ничья ({v1}:{v2}). Ставки возвращены."
            else:
                winner = owner_id if v1 > v2 else joiner_id
                loser = joiner_id if winner == owner_id else owner_id
                payout = int(pot * (1 - commission))
                await add_balance(winner, payout, reason="duel_win")
                delta_w = payout - bet
                delta_l = -bet
                await log_game(winner, duel.chat_id, "duel", bet, "win", delta_w, meta=f"{v1}:{v2}")
                await log_game(loser, duel.chat_id, "duel", bet, "lose", delta_l, meta=f"{v1}:{v2}")
                with contextlib.suppress(Exception):
                    await quest_progress(winner, "place_bets", bet)
                    await quest_progress(winner, "win_games", 1)
                    await quest_progress(loser, "place_bets", bet)
                    await update_win_streak(winner, duel.chat_id, won=True)
                    await update_win_streak(loser, duel.chat_id, won=False)
                jp = max(1, int(bet * JACKPOT_PERCENT))
                await jackpot_add(jp)
                wu = await get_user(winner)
                wname = safe_name_from_dict(wu or {})
                text = (
                    f"⚔️ <b>Дуэль завершена!</b>\n"
                    f"{v1} : {v2}\n"
                    f"🏆 Победитель: {html_escape(wname)}\n"
                    f"💰 Выигрыш: <b>+{fmt_int(payout)}</b> TOKENS"
                )
                with contextlib.suppress(Exception):
                    if delta_w >= BIG_WIN_THRESHOLD:
                        phrase = random.choice(NEURO_BIG_WIN_PHRASES).format(
                            name=html_escape(wname), amount=fmt_int(delta_w),
                        )
                        await safe_send_autodelete(duel.chat_id, phrase,
                                                   delay=AUTODELETE_LONG_SEC)
            await safe_send_autodelete(duel.chat_id, text, delay=AUTODELETE_LONG_SEC)
        except Exception as e:
            log_exc("cb_duel_join.play", e)
            await add_balance(owner_id, bet, reason="duel_refund_crash")
            await add_balance(joiner_id, bet, reason="duel_refund_crash")
    except Exception as e:
        log_exc("cb_duel_join", e)


@router.callback_query(F.data.startswith("duel:cancel:"))
async def cb_duel_cancel(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 3:
            return
        owner_id = int(parts[2]) if parts[2].lstrip("-").isdigit() else 0
        if int(user["user_id"]) != owner_id:
            await safe_answer_cb(cb, "Это не ваше лобби", alert=True)
            return
        async with _duels_guard:
            duel = _duels.get(owner_id)
            if duel is None or duel.finished:
                await safe_answer_cb(cb, "Лобби уже закрыто", alert=True)
                return
            duel.finished = True
            _duels.pop(owner_id, None)
        await add_balance(owner_id, duel.bet, reason="duel_cancel_refund")
        await safe_answer_cb(cb, "Лобби отменено, ставка возвращена.")
        if cb.message:
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(
                    chat_id=cb.message.chat.id,
                    message_id=cb.message.message_id,
                    reply_markup=None,
                )
    except Exception as e:
        log_exc("cb_duel_cancel", e)


# =============================================================================
#  ЧАСТЬ 7.3 — ПЕРЕВОДЫ
# =============================================================================
#  Команда @перевод <сумма> в ответ на сообщение.
#  Или /transfer <user_id|@username> <сумма>.
#  Защита: нельзя переводить себе, проверка баланса, атомарный transfer_balance.

_TRANSFER_RE = re.compile(r"^@?(?:перевод|transfer)\s+(.+)$", re.IGNORECASE)


async def _do_transfer(
    chat_id: int,
    from_user: Dict[str, Any],
    to_id: int,
    amount: int,
) -> None:
    if amount <= 0:
        await safe_send_autodelete(chat_id, TXT_INVALID_AMOUNT, delay=5)
        return
    if int(from_user["user_id"]) == to_id:
        await safe_send_autodelete(chat_id, "🚫 Нельзя переводить себе.", delay=5)
        return
    to_user = await get_user(to_id)
    if to_user is None:
        await ensure_user(to_id)
        to_user = await get_user(to_id)
    ok, err, new_balance = await transfer_balance(
        int(from_user["user_id"]), to_id, amount, reason="transfer"
    )
    if not ok:
        msg = {
            "not_enough": TXT_NOT_ENOUGH,
            "self_transfer": "🚫 Нельзя переводить себе.",
            "invalid_amount": TXT_INVALID_AMOUNT,
        }.get(err, TXT_TRANSFER_FAIL.format(reason=err))
        await safe_send_autodelete(chat_id, msg, delay=5)
        return
    to_name = safe_name_from_dict(to_user or {"user_id": to_id})
    await safe_send_autodelete(
        chat_id,
        TXT_TRANSFER_OK.format(amount=fmt_int(amount), name=html_escape(to_name)),
        delay=AUTODELETE_DEFAULT_SEC,
    )
    # Уведомление получателю (в его личку, best-effort)
    with contextlib.suppress(Exception):
        await safe_send(
            to_id,
            f"💸 Получен перевод: <b>+{fmt_int(amount)}</b> TOKENS\n"
            f"От: {html_escape(safe_name_from_dict(from_user))}",
            parse_mode=ParseMode.HTML,
        )
    # Псевдо-ИИ реакция на крупные переводы
    with contextlib.suppress(Exception):
        if amount >= BIG_WIN_THRESHOLD:
            await safe_send_autodelete(
                chat_id,
                f"🤝 Крупный перевод: {html_escape(safe_name_from_dict(from_user))} → "
                f"{html_escape(to_name)} — <b>{fmt_int(amount)}</b> TOKENS",
                delay=AUTODELETE_LONG_SEC,
            )


@router.message(Command("transfer"))
async def cmd_transfer(message: Message) -> None:
    try:
        user = await _guard_user(message)
        if user is None:
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await safe_send_autodelete(
                message.chat.id,
                "💸 Формат: <code>/transfer @username 5000</code>\n"
                "или ответьте на сообщение: <code>@перевод 5000</code>",
                delay=AUTODELETE_LONG_SEC,
            )
            return
        target_raw = parts[1].lstrip("@")
        amount = parse_amount(parts[2])
        if amount is None:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        # Определяем target_id
        to_id: Optional[int] = None
        if target_raw.isdigit():
            to_id = int(target_raw)
        else:
            # Ищем по username
            row = await _fetchone(
                "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE",
                (target_raw,),
            )
            if row:
                to_id = int(row["user_id"])
        if to_id is None:
            await safe_send_autodelete(
                message.chat.id, "🚫 Получатель не найден.", delay=5,
            )
            return
        await _do_transfer(message.chat.id, user, to_id, amount)
    except Exception as e:
        log_exc("cmd_transfer", e)


@router.message(F.reply_to_message, F.text.regexp(_TRANSFER_RE))
async def msg_transfer_reply(message: Message) -> None:
    """«@перевод 5000» в ответ на сообщение — переводит автору сообщения."""
    try:
        user = await _guard_user(message)
        if user is None or message.reply_to_message is None:
            return
        target = message.reply_to_message.from_user
        if target is None:
            return
        m = _TRANSFER_RE.match((message.text or "").strip())
        if not m:
            return
        amount = parse_amount(m.group(1))
        if amount is None:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        await _do_transfer(message.chat.id, user, target.id, amount)
    except Exception as e:
        log_exc("msg_transfer_reply", e)


@router.message(F.text.regexp(r"^@перевод\s+(.+)$"))
async def msg_transfer_no_reply(message: Message) -> None:
    """«@перевод 5000» без reply — подсказка."""
    await safe_send_autodelete(
        message.chat.id,
        "💡 Ответьте на сообщение получателя командой «@перевод <сумма>».",
        delay=AUTODELETE_SHORT_SEC,
    )


# =============================================================================
#  КОНЕЦ ЧАСТИ 7
# =============================================================================
#  ЧАСТЬ 8 подключит: Рулетка (парсер, ставки, спин, результат, статистика).

# =============================================================================
#  ЧАСТЬ 8 / 10 — РУЛЕТКА
#  Содержание:
#    - Умный парсер ставок (к/ч/чёт/нечёт/число/диапазон/дюжина/колонка)
#    - FSM-сценарий выбора суммы и типа
#    - Атомарный спин под roulette_lock (защита от race condition)
#    - Анимация «крутится» + корректное автоудаление
#    - Начисление выигрыша с учётом VIP и комиссии чата
#    - Джекпот (1% от проигрышей) и турнирная статистика
#    - Квесты, винстрики, псевдо-ИИ реакции
#    - Кнопки «Повторить / Удвоить»
#    - Валидация всех входов, защита от double-spend
# =============================================================================

# Европейская рулетка: 0..36
ROULETTE_NUMBERS: Tuple[int, ...] = tuple(range(37))

# Текстовые алиасы (RU + EN) для парсера
_RED_ALIASES: Set[str] = {"к", "кр", "красн", "красное", "red", "r"}
_BLACK_ALIASES: Set[str] = {"ч", "чёрн", "черн", "чёрное", "черное", "black", "b"}
_EVEN_ALIASES: Set[str] = {"чёт", "чет", "чётн", "четн", "чётное", "even", "e"}
_ODD_ALIASES: Set[str] = {"нечёт", "нечет", "нечётн", "нечетн", "нечётное", "нечетное", "odd", "o"}
_LOW_ALIASES: Set[str] = {"low", "лоу", "1-18", "1–18", "1..18", "малые"}
_HIGH_ALIASES: Set[str] = {"high", "хай", "19-36", "19–36", "19..36", "большие"}
_GREEN_ALIASES: Set[str] = {"зеро", "zero", "0", "зел", "зелён", "зеленое"}
_DOZEN_ALIASES: Dict[str, str] = {
    "1-12": "dozen1", "1–12": "dozen1", "1..12": "dozen1",
    "13-24": "dozen2", "13–24": "dozen2", "13..24": "dozen2",
    "25-36": "dozen3", "25–36": "dozen3", "25..36": "dozen3",
    "1-я": "dozen1", "2-я": "dozen2", "3-я": "dozen3",
}
_COLUMN_ALIASES: Dict[str, str] = {
    "col1": "column1", "col2": "column2", "col3": "column3",
    "1col": "column1", "2col": "column2", "3col": "column3",
}

# Идентификатор игры для логов/квестов
GAME_ROULETTE: str = "roulette"

# Максимальная ставка на точное число (страховка от слива джекпота)
MAX_BET_EXACT: int = 25_000

# Пауза «анимации» между списанием и результатом (секунды)
ROULETTE_SPIN_MIN_SEC: float = 1.2
ROULETTE_SPIN_MAX_SEC: float = 2.2


# =============================================================================
#  1. УМНЫЙ ПАРСЕР СТАВОК
# =============================================================================
#  Формат: "<тип> [значение]" или диапазон/число.
#  Примеры:
#    "к" / "красное"          -> red
#    "ч" / "черное"           -> black
#    "чёт" / "even"           -> even
#    "нечет" / "odd"          -> odd
#    "1-12" / "1–12" / "1..12"-> dozen1
#    "17"                     -> exact 17
#    "0"                      -> exact 0
#    "low"/"1-18"             -> low
#    "high"/"19-36"           -> high
#    "col1" / "1кол"          -> column1
# =============================================================================

class RouletteBetParse:
    """Результат парсинга: тип, значение, «человеческое» описание, ошибка."""
    __slots__ = ("bet_type", "bet_value", "human", "error")

    def __init__(
        self,
        bet_type: Optional[str] = None,
        bet_value: Optional[str] = None,
        human: str = "",
        error: Optional[str] = None,
    ) -> None:
        self.bet_type = bet_type
        self.bet_value = bet_value
        self.human = human
        self.error = error

    def ok(self) -> bool:
        return self.error is None and self.bet_type is not None


def parse_roulette_bet(raw: str) -> RouletteBetParse:
    """
    Умный парсер ставок рулетки.
    Возвращает RouletteBetParse. Никогда не бросает.
    """
    try:
        if raw is None:
            return RouletteBetParse(error="empty")
        s = str(raw).strip().lower()
        if not s:
            return RouletteBetParse(error="empty")
        # Нормализуем дефисы
        s_norm = s.replace("–", "-").replace("—", "-").replace("..", "-")
        # Убираем пробелы для диапазонов, но оставляем для слов
        s_compact = s_norm.replace(" ", "")

        # 1) Прямые алиасы
        if s in _RED_ALIASES:
            return RouletteBetParse("red", None, "🔴 Красное")
        if s in _BLACK_ALIASES:
            return RouletteBetParse("black", None, "⚫ Чёрное")
        if s in _EVEN_ALIASES:
            return RouletteBetParse("even", None, "Чёт")
        if s in _ODD_ALIASES:
            return RouletteBetParse("odd", None, "Нечет")
        if s in _LOW_ALIASES:
            return RouletteBetParse("low", None, "1-18")
        if s in _HIGH_ALIASES:
            return RouletteBetParse("high", None, "19-36")
        if s in _GREEN_ALIASES:
            return RouletteBetParse("exact", "0", "🟢 Зеро")

        # 2) Дюжины
        if s_compact in _DOZEN_ALIASES:
            dt = _DOZEN_ALIASES[s_compact]
            human = {"dozen1": "1-12", "dozen2": "13-24", "dozen3": "25-36"}[dt]
            return RouletteBetParse(dt, None, human)
        # Числовые дюжины «1 12», «13 24», «25 36» — тоже поддержим
        m = re.fullmatch(r"(\d{1,2})\s*[- ]\s*(\d{1,2})", s_norm)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if (lo, hi) == (1, 12):
                return RouletteBetParse("dozen1", None, "1-12")
            if (lo, hi) == (13, 24):
                return RouletteBetParse("dozen2", None, "13-24")
            if (lo, hi) == (25, 36):
                return RouletteBetParse("dozen3", None, "25-36")
            if (lo, hi) == (1, 18):
                return RouletteBetParse("low", None, "1-18")
            if (lo, hi) == (19, 36):
                return RouletteBetParse("high", None, "19-36")

        # 3) Колонки
        if s_compact in _COLUMN_ALIASES:
            ct = _COLUMN_ALIASES[s_compact]
            human = {"column1": "1-я колонка", "column2": "2-я колонка", "column3": "3-я колонка"}[ct]
            return RouletteBetParse(ct, None, human)
        if s_compact in ("1кол", "2кол", "3кол", "1колонка", "2колонка", "3колонка"):
            ct = {"1": "column1", "2": "column2", "3": "column3"}[s_compact[0]]
            human = {"column1": "1-я колонка", "column2": "2-я колонка", "column3": "3-я колонка"}[ct]
            return RouletteBetParse(ct, None, human)

        # 4) Точное число
        if s_compact.isdigit():
            n = int(s_compact)
            if 0 <= n <= 36:
                return RouletteBetParse("exact", str(n), f"Число {n}")
            return RouletteBetParse(error="number_out_of_range")

        # 5) Диапазон вида "5-10"
        m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", s_norm)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if not (0 <= lo <= 36 and 0 <= hi <= 36 and lo < hi):
                return RouletteBetParse(error="range_invalid")
            # Спец-диапазоны
            if (lo, hi) == (1, 12):
                return RouletteBetParse("dozen1", None, "1-12")
            if (lo, hi) == (13, 24):
                return RouletteBetParse("dozen2", None, "13-24")
            if (lo, hi) == (25, 36):
                return RouletteBetParse("dozen3", None, "25-36")
            if (lo, hi) == (1, 18):
                return RouletteBetParse("low", None, "1-18")
            if (lo, hi) == (19, 36):
                return RouletteBetParse("high", None, "19-36")
            # Произвольный диапазон — не поддерживаем (только стандартные)
            return RouletteBetParse(error="range_unsupported")

        return RouletteBetParse(error="unknown")
    except Exception as e:
        log_exc("parse_roulette_bet", e)
        return RouletteBetParse(error="internal")


def _roulette_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in ROULETTE_RED else "black"


def _roulette_color_emoji(n: int) -> str:
    c = _roulette_color(n)
    if c == "red":
        return "🔴"
    if c == "black":
        return "⚫"
    return "🟢"


def _roulette_is_win(
    n: int,
    bet_type: str,
    bet_value: Optional[str],
) -> bool:
    """
    Проверяет, выиграла ли ставка при выпавшем числе n.
    ВАЖНО: 0 при чёт/нечёт/красное/чёрное/дюжинах/колонках/low/high — всегда проигрыш
    (кроме exact=0 и ставки на 0). Так работает европейская рулетка.
    """
    try:
        if n < 0 or n > 36:
            return False
        if bet_type == "exact":
            try:
                return int(bet_value or "-1") == n
            except Exception:
                return False
        if n == 0:
            return False
        if bet_type == "red":
            return n in ROULETTE_RED
        if bet_type == "black":
            return n in ROULETTE_BLACK
        if bet_type == "even":
            return n % 2 == 0
        if bet_type == "odd":
            return n % 2 == 1
        if bet_type == "low":
            return 1 <= n <= 18
        if bet_type == "high":
            return 19 <= n <= 36
        if bet_type == "dozen1":
            return 1 <= n <= 12
        if bet_type == "dozen2":
            return 13 <= n <= 24
        if bet_type == "dozen3":
            return 25 <= n <= 36
        if bet_type == "column1":
            return n % 3 == 1
        if bet_type == "column2":
            return n % 3 == 2
        if bet_type == "column3":
            return n % 3 == 0
        return False
    except Exception as e:
        log_exc("_roulette_is_win", e)
        return False


def _roulette_payout_multiplier(bet_type: str) -> float:
    return float(ROULETTE_PAYOUTS.get(bet_type, 0.0))


def _roulette_human_bet(bet_type: str, bet_value: Optional[str]) -> str:
    if bet_type == "exact":
        return f"Число {bet_value}"
    return {
        "red": "🔴 Красное",
        "black": "⚫ Чёрное",
        "even": "Чёт",
        "odd": "Нечет",
        "low": "1-18",
        "high": "19-36",
        "dozen1": "1-12",
        "dozen2": "13-24",
        "dozen3": "25-36",
        "column1": "1-я колонка",
        "column2": "2-я колонка",
        "column3": "3-я колонка",
    }.get(bet_type, bet_type)


# =============================================================================
#  2. ВХОД В РУЛЕТКУ
# =============================================================================

@router.callback_query(F.data == cb_build("menu", "roulette"))
async def cb_roulette_menu(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        await state.clear()
        await state.update_data(game="roulette", bet=None)
        await state.set_state(BetStates.waiting_amount)
        text = (
            "🎡 <b>Рулетка</b>\n\n"
            "Европейская рулетка (0–36).\n"
            "Ставки: красное/чёрное, чёт/нечет, дюжины, колонки, точное число.\n\n"
            f"Минимальная ставка: <b>{fmt_int(MIN_BET)}</b>\n"
            f"Максимальная: <b>{fmt_int(MAX_BET)}</b>\n\n"
            "Выберите сумму или введите своё:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_bet_amounts("rl"),
        )
    except Exception as e:
        log_exc("cb_roulette_menu", e)


@router.callback_query(F.data.startswith("rl:amt:"))
async def cb_roulette_amount(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        raw = parts[2] if len(parts) >= 3 else ""
        bet = int(user["balance"]) if raw == "all" else (int(raw) if raw.isdigit() else 0)
        if bet <= 0:
            await safe_answer_cb(cb, TXT_INVALID_AMOUNT, alert=True)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_answer_cb(cb, err, alert=True)
            return
        await state.update_data(game="roulette", bet=bet)
        text = (
            f"🎡 <b>Рулетка</b>\n"
            f"Ставка: <b>{fmt_int(bet)}</b> TOKENS\n\n"
            f"Выберите тип ставки:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_roulette_types(bet),
        )
    except Exception as e:
        log_exc("cb_roulette_amount", e)


@router.message(StateFilter(BetStates.waiting_amount), F.text)
async def fsm_roulette_amount(message: Message, state: FSMContext) -> None:
    """
    Ручной ввод суммы ИЛИ полной ставки: "5000 к", "10000 17", "500 чёт".
    Умный парсер: если в строке есть и сумма, и тип — сразу спин.
    """
    try:
        data = await state.get_data()
        if data.get("game") != "roulette":
            return
        user = await _guard_user(message)
        if user is None:
            return
        text = (message.text or "").strip()
        # Пытаемся распарсить "сумма [тип]"
        m = re.match(r"^(\S+)(?:\s+(.+))?$", text)
        if not m:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        bet = parse_amount(m.group(1))
        if bet is None:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        err = await _validate_bet(user, bet)
        if err:
            await safe_send_autodelete(message.chat.id, err, delay=5)
            return
        rest = (m.group(2) or "").strip()
        if rest:
            # Пользователь ввёл сумму + тип — сразу спин
            parsed = parse_roulette_bet(rest)
            if not parsed.ok():
                await safe_send_autodelete(
                    message.chat.id,
                    "🚫 Не понял тип ставки. Пример: <code>5000 к</code>, "
                    "<code>10000 17</code>, <code>500 чёт</code>.",
                    delay=AUTODELETE_LONG_SEC,
                )
                return
            await state.clear()
            await _spin_roulette(
                message.chat.id, user, bet, parsed.bet_type, parsed.bet_value,
                reply_to=message.message_id,
            )
            return
        # Только сумма — показываем кнопки
        await state.update_data(game="roulette", bet=bet)
        await safe_send_autodelete(
            message.chat.id,
            f"🎡 Ставка: <b>{fmt_int(bet)}</b> TOKENS\n\nВыберите тип ставки:",
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_roulette_types(bet),
        )
    except Exception as e:
        log_exc("fsm_roulette_amount", e)


# =============================================================================
#  3. СПИН — ГЛАВНАЯ ЛОГИКА
# =============================================================================

async def _spin_roulette(
    chat_id: int,
    user: Dict[str, Any],
    bet: int,
    bet_type: str,
    bet_value: Optional[str],
    reply_to: Optional[int] = None,
) -> None:
    """
    Полный цикл рулетки.
    Гарантии:
      - roulette_lock удерживается на время списания+начисления.
      - Двойной клик невозможен: сначала атомарно списываем.
      - VIP +5% к выигрышу, комиссия чата вычитается из выигрыша.
      - 1% от проигрыша -> джекпот.
      - Турнирная статистика: score += bet (для турниров).
      - Все вызовы Telegram API в try/except.
    """
    uid = int(user["user_id"])
    try:
        # Антиспам
        if not await check_game_antispam(uid):
            await safe_send_autodelete(chat_id, TXT_ANTISPAM, delay=3)
            return
        # Валидация ставки
        err = await _validate_bet(user, bet)
        if err:
            await safe_send_autodelete(chat_id, err, delay=5)
            return
        # Ограничение на точное число
        if bet_type == "exact" and bet > MAX_BET_EXACT:
            await safe_send_autodelete(
                chat_id,
                f"🚫 Максимальная ставка на число: {fmt_int(MAX_BET_EXACT)}.",
                delay=AUTODELETE_SHORT_SEC,
            )
            return
        # Проверка типа
        if bet_type not in ROULETTE_PAYOUTS:
            await safe_send_autodelete(chat_id, "🚫 Неизвестный тип ставки.", delay=5)
            return
        if bet_type == "exact":
            try:
                n_val = int(bet_value or "-1")
            except Exception:
                n_val = -1
            if not (0 <= n_val <= 36):
                await safe_send_autodelete(
                    chat_id, "🚫 Число должно быть от 0 до 36.", delay=5,
                )
                return

        # Крутим под глобальным локом рулетки — защита от race condition
        async with roulette_lock:
            # Атомарное списание (внутри лока)
            ok, new_balance = await try_withdraw(uid, bet, reason=f"roulette_{bet_type}")
            if not ok:
                await safe_send_autodelete(chat_id, TXT_NOT_ENOUGH, delay=5)
                return
            # Анимация: сообщение о том, что крутится
            human_bet = _roulette_human_bet(bet_type, bet_value)
            spin_text = (
                f"🎡 Крутим...\n"
                f"Ставка: <b>{fmt_int(bet)}</b> на {human_bet}"
            )
            await safe_send_autodelete(chat_id, spin_text, delay=4)
            # Небольшая задержка «анимации»
            await asyncio.sleep(random.uniform(ROULETTE_SPIN_MIN_SEC, ROULETTE_SPIN_MAX_SEC))
            # Выпавшее число
            n = random.randint(0, 36)
            color_emoji = _roulette_color_emoji(n)
            color = _roulette_color(n)

            # Результат
            won = _roulette_is_win(n, bet_type, bet_value)
            # VIP-бонус
            vip = int(user.get("vip") or 0) == 1
            vip_mult = (1.0 + VIP_BONUS_PERCENT) if vip else 1.0
            # Комиссия чата
            commission = await get_chat_commission(chat_id)
            # Сезонный множитель
            seasonal = is_seasonal_multiplier_active()

            delta = 0
            payout = 0
            if won:
                mult = _roulette_payout_multiplier(bet_type)
                gross = int(round(bet * mult))
                # VIP-бонус применяем к gross, затем комиссию
                gross_after_vip = int(round(gross * vip_mult))
                payout = int(round(gross_after_vip * (1 - commission) * seasonal))
                # Возврат ставки уже не нужен — она списана; payout включает всё
                await add_balance(uid, payout, reason="roulette_win")
                delta = payout - bet
            else:
                # Проигрыш — 1% в джекпот
                jp = max(1, int(bet * JACKPOT_PERCENT))
                await jackpot_add(jp)
                delta = -bet

            # Логи
            await log_roulette(uid, chat_id, bet, bet_type, bet_value, n, won, payout)
            await log_game(
                uid, chat_id, GAME_ROULETTE, bet,
                "win" if won else "lose", delta,
                meta=f"type={bet_type},value={bet_value},number={n}",
            )

            # Квесты (place_bets — всегда; win_games/win_roulette — если выиграл)
            with contextlib.suppress(Exception):
                await quest_progress(uid, "place_bets", bet)
                await quest_progress(uid, "play_roulette", 1)
                if won:
                    await quest_progress(uid, "win_roulette", 1)
                    await quest_progress(uid, "win_games", 1)

            # Винстрик
            with contextlib.suppress(Exception):
                await update_win_streak(uid, chat_id, won=won)

            # Турнирная статистика
            with contextlib.suppress(Exception):
                t = await get_active_tournament(chat_id)
                if t is not None:
                    # score += bet: активность важнее победы
                    await tournament_add_score(int(t["id"]), uid, bet)

            # Рефералка — на первую игру
            with contextlib.suppress(Exception):
                await reward_referral_on_game(uid)

            # Псевдо-ИИ контекст: запоминаем последнего выигравшего
            if won:
                try:
                    chat_last_winner[chat_id] = {
                        "user_id": uid,
                        "name": safe_name_from_dict(user),
                        "amount": delta,
                        "ts": time.time(),
                    }
                except Exception:
                    pass

            # Итоговое сообщение
            if won:
                outcome_line = TXT_ROULETTE_WIN.format(amount=fmt_int(delta))
            else:
                outcome_line = TXT_ROULETTE_LOSE.format(amount=fmt_int(bet))
            # Пометки о бонусах
            extra: List[str] = []
            if won:
                if vip:
                    extra.append("⭐️ VIP: +5%")
                if seasonal > 1.0:
                    extra.append(f"🎉 Сезон: x{seasonal:.1f}")
                if commission > 0:
                    extra.append(f"🏦 Комиссия чата: {commission * 100:.1f}%")
            if extra:
                outcome_line += "\n" + " | ".join(extra)

            result_text = TXT_ROULETTE_RESULT.format(
                number=n, color_emoji=color_emoji, outcome_line=outcome_line,
            )
            await safe_send_autodelete(
                chat_id,
                result_text,
                delay=AUTODELETE_DEFAULT_SEC,
                reply_markup=kb_roulette_again(bet, bet_type, bet_value),
            )

            # Псевдо-ИИ реакции
            with contextlib.suppress(Exception):
                if delta >= BIG_WIN_THRESHOLD:
                    phrase = random.choice(NEURO_BIG_WIN_PHRASES).format(
                        name=html_escape(safe_name_from_dict(user)),
                        amount=fmt_int(delta),
                    )
                    await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)
                elif delta <= -BIG_LOSS_THRESHOLD:
                    phrase = random.choice(NEURO_BIG_LOSS_PHRASES).format(
                        name=html_escape(safe_name_from_dict(user)),
                        amount=fmt_int(-delta),
                    )
                    await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)
                # Винстрик >= 3 — отдельная фраза
                streak = await get_win_streak(uid)
                if won and streak >= 3:
                    phrase = random.choice(NEURO_WIN_STREAK_PHRASES).format(
                        name=html_escape(safe_name_from_dict(user)),
                        streak=streak,
                    )
                    await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)
    except Exception as e:
        log_exc("_spin_roulette", e)
        # Best-effort возврат при краше
        with contextlib.suppress(Exception):
            await add_balance(uid, bet, reason="roulette_refund_crash")


# =============================================================================
#  4. CALLBACK: СПИН ИЗ КНОПОК
# =============================================================================

@router.callback_query(F.data.startswith("rl:spin:"))
async def cb_roulette_spin(cb: CallbackQuery) -> None:
    """
    callback_data: rl:spin:<bet>:<type>[:value]
    """
    try:
        await safe_answer_cb(cb)
        user = await _guard_cb(cb)
        if user is None or cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        if len(parts) < 4:
            return
        try:
            bet = int(parts[2])
        except Exception:
            bet = 0
        bet_type = parts[3]
        bet_value = parts[4] if len(parts) >= 5 and parts[4] != "" else None
        if bet <= 0:
            await safe_answer_cb(cb, TXT_INVALID_AMOUNT, alert=True)
            return
        if bet_type not in ROULETTE_PAYOUTS:
            await safe_answer_cb(cb, "🚫 Неизвестный тип ставки", alert=True)
            return
        # Проверка двойного клика: переключаем клавиатуру на «крутится»
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(
                chat_id=cb.message.chat.id,
                message_id=cb.message.message_id,
                reply_markup=None,
            )
        await _spin_roulette(cb.message.chat.id, user, bet, bet_type, bet_value)
    except Exception as e:
        log_exc("cb_roulette_spin", e)


# =============================================================================
#  5. ТЕКСТОВЫЙ ВВОД «сумма тип» ВНЕ FSM
# =============================================================================
#  Пример: "5000 к", "10000 17", "500 чёт"
#  Работает в личке и в группе (если казино включено).

_ROULETTE_TEXT_RE = re.compile(r"^\s*(\S+)\s+(\S.*)$")


@router.message(F.text.regexp(r"^\s*\S+\s+\S.*$"))
async def msg_roulette_quick_bet(message: Message, state: FSMContext) -> None:
    """
    Быстрая ставка в рулетку текстом без FSM:
    "5000 к", "10000 17", "500 чёт" — если первая часть парсится как сумма,
    а вторая — как тип ставки.
    Не мешает другим сценариям: если state активен — не вмешиваемся.
    """
    try:
        # Если есть активный FSM — не трогаем (кроме waiting_amount roulette)
        cur_state = await state.get_state()
        if cur_state is not None and cur_state != BetStates.waiting_amount.state:
            return
        data = await state.get_data()
        if cur_state == BetStates.waiting_amount.state and data.get("game") != "roulette":
            return
        text = (message.text or "").strip()
        m = _ROULETTE_TEXT_RE.match(text)
        if not m:
            return
        user = await _guard_user(message)
        if user is None:
            return
        bet = parse_amount(m.group(1))
        if bet is None:
            return
        parsed = parse_roulette_bet(m.group(2))
        if not parsed.ok():
            return
        # Проверим лимиты: не отвечаем ошибкой на любое сообщение — только если
        # пользователь явно целится в рулетку (тип распознан).
        err = await _validate_bet(user, bet)
        if err:
            await safe_send_autodelete(message.chat.id, err, delay=5)
            return
        await state.clear()
        await _spin_roulette(
            message.chat.id, user, bet, parsed.bet_type, parsed.bet_value,
            reply_to=message.message_id,
        )
    except Exception as e:
        log_exc("msg_roulette_quick_bet", e)


# =============================================================================
#  6. ИНФО О РУЛЕТКЕ (справка)
# =============================================================================

@router.callback_query(F.data == cb_build("rl", "help"))
async def cb_roulette_help(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        text = (
            "🎡 <b>Рулетка: справка</b>\n\n"
            "<b>Выплаты:</b>\n"
            "• Красное/Чёрное/Чёт/Нечет/1-18/19-36 — x2\n"
            "• Дюжины/Колонки — x3\n"
            "• Точное число — x36\n\n"
            "<b>Особенности:</b>\n"
            "• 0 — всегда выигрыш только для ставки «Зеро»\n"
            "• VIP: +5% к выигрышу\n"
            "• Комиссия чата удерживается из выигрыша\n"
            "• 1% от проигрыша идёт в джекпот\n\n"
            "<b>Быстрые ставки текстом:</b>\n"
            "<code>5000 к</code> — 5000 на красное\n"
            "<code>10000 17</code> — 10000 на число 17\n"
            "<code>500 чёт</code> — 500 на чёт"
        )
        if cb.message is not None:
            await safe_edit_or_send(
                cb.message.chat.id, cb.message.message_id, text,
                reply_markup=kb_back_menu(),
            )
    except Exception as e:
        log_exc("cb_roulette_help", e)


# =============================================================================
#  КОНЕЦ ЧАСТИ 8
# =============================================================================
#  ЧАСТЬ 9 подключит: Админка + Live-Дашборд.

# =============================================================================
#  ЧАСТЬ 9 / 10 — АДМИНКА + LIVE-ДАШБОРД
#  Содержание:
#    - Команды: /admin, /stats, /broadcast, /ban, /unban
#    - Live-Дашборд с inline-кнопками: онлайн, банк, топ-выигрыши, график
#    - Управление промокодами: создание, список, удаление
#    - Управление новостями (авто-генератор из ЧАСТИ 4)
#    - Античит: алерты в ЛС главному админу при аномалиях
#    - Inline-кнопки дашборда: обновление, график, топ, активность
#    - Все действия логируются в admin_logs
# =============================================================================

# =============================================================================
#  ХЕЛПЕРЫ ПРОВЕРКИ ПРАВ
# =============================================================================

def _require_admin(message: Message) -> bool:
    """Проверяет, что отправитель — админ. Если нет, отвечает и возвращает False."""
    try:
        uid = message.from_user.id if message.from_user else 0
        if not is_admin(uid):
            # Не отвечаем в группах, чтобы не спамить
            if _is_private(message.chat):
                asyncio.create_task(
                    safe_send_autodelete(message.chat.id, TXT_ADMIN_ONLY, delay=5)
                )
            return False
        return True
    except Exception as e:
        log_exc("_require_admin", e)
        return False


async def _require_admin_cb(cb: CallbackQuery) -> bool:
    try:
        uid = cb.from_user.id if cb.from_user else 0
        if not is_admin(uid):
            await safe_answer_cb(cb, TXT_ADMIN_ONLY, alert=True)
            return False
        return True
    except Exception as e:
        log_exc("_require_admin_cb", e)
        return False


# =============================================================================
#  LIVE-ДАШБОРД
# =============================================================================

async def _render_dashboard() -> str:
    """Собирает актуальную сводку и форматирует в текст."""
    try:
        stats = await dashboard_stats()
        return TXT_ADMIN_DASHBOARD.format(
            online=fmt_int(stats["online"]),
            users=fmt_int(stats["users"]),
            bank=fmt_int(stats["bank"]),
            jackpot=fmt_int(stats["jackpot"]),
            burned=fmt_int(stats["burned"]),
            earned=fmt_int(stats["earned"]),
        )
    except Exception as e:
        log_exc("_render_dashboard", e)
        return "⚠️ Ошибка при сборке дашборда."


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    try:
        if not _require_admin(message):
            return
        await state.clear()
        text = await _render_dashboard()
        await safe_send(
            message.chat.id,
            text,
            reply_markup=kb_admin_dashboard(),
        )
    except Exception as e:
        log_exc("cmd_admin", e)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Быстрая сводка одной командой."""
    try:
        if not _require_admin(message):
            return
        text = await _render_dashboard()
        await safe_send(message.chat.id, text, reply_markup=kb_admin_dashboard())
    except Exception as e:
        log_exc("cmd_stats", e)


@router.callback_query(F.data.startswith("adm:dash:"))
async def cb_admin_dash(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        if cb.message is None:
            return
        parts = cb_parse(cb.data or "")
        action = parts[2] if len(parts) >= 3 else "refresh"

        if action == "refresh":
            text = await _render_dashboard()
            await safe_edit_or_send(
                cb.message.chat.id, cb.message.message_id, text,
                reply_markup=kb_admin_dashboard(),
            )
            return

        if action == "chart":
            hourly = await activity_by_hour_last_24h()
            # Строим ASCII-график
            lines = ["📊 <b>Активность по часам (24ч)</b>\n"]
            max_val = max(hourly.values()) if hourly else 0
            for h in range(24):
                v = hourly.get(h, 0)
                bar_len = int((v / max_val) * 20) if max_val > 0 else 0
                bar = "█" * bar_len
                lines.append(f"{h:02d}:00 |{bar} {v}")
            text = "\n".join(lines)
            await safe_edit_or_send(
                cb.message.chat.id, cb.message.message_id, text,
                reply_markup=kb_admin_dashboard(),
            )
            return

        if action == "wins":
            wins = await biggest_wins_last_24h(10)
            lines = ["🏆 <b>Крупнейшие выигрыши за 24ч</b>\n"]
            if not wins:
                lines.append("Пока нет данных.")
            else:
                for i, w in enumerate(wins, start=1):
                    u = await get_user(int(w["user_id"]))
                    name = safe_name_from_dict(u or {"user_id": w["user_id"]})
                    lines.append(
                        f"{i}. {html_escape(name)} — <b>+{fmt_int(w['delta'])}</b> "
                        f"({w['game']})"
                    )
            text = "\n".join(lines)
            await safe_edit_or_send(
                cb.message.chat.id, cb.message.message_id, text,
                reply_markup=kb_admin_dashboard(),
            )
            return

        if action == "activity":
            acts = await recent_bot_activity(20)
            lines = ["🤖 <b>Последняя активность бота</b>\n"]
            if not acts:
                lines.append("Пока нет данных.")
            else:
                for a in acts:
                    ts = dt.datetime.fromtimestamp(float(a["created_at"])).strftime("%H:%M:%S")
                    lines.append(
                        f"<code>{ts}</code> {a['action_type']}: "
                        f"{html_escape(str(a.get('details') or ''))[:80]}"
                    )
            text = "\n".join(lines)
            await safe_edit_or_send(
                cb.message.chat.id, cb.message.message_id, text,
                reply_markup=kb_admin_dashboard(),
            )
            return

        # неизвестное — просто рефреш
        text = await _render_dashboard()
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_admin_dashboard(),
        )
    except Exception as e:
        log_exc("cb_admin_dash", e)


# =============================================================================
#  УПРАВЛЕНИЕ НОВОСТЯМИ (АВТО-ГЕНЕРАТОР)
# =============================================================================

@router.callback_query(F.data == cb_build("adm", "news", "menu"))
async def cb_admin_news_menu(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        if cb.message is None:
            return
        target = NEWS_TARGET_CHAT or "не задан (NEWS_CHANNEL_ID)"
        text = (
            f"📣 <b>Управление новостями</b>\n\n"
            f"Куда постим: <code>{target}</code>\n\n"
            f"Выберите тип поста для мгновенной публикации:"
        )
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id, text,
            reply_markup=kb_admin_news_menu(),
        )
    except Exception as e:
        log_exc("cb_admin_news_menu", e)


@router.callback_query(F.data.startswith("adm:news:"))
async def cb_admin_news_publish(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        parts = cb_parse(cb.data or "")
        kind = parts[2] if len(parts) >= 3 else "random"
        if kind == "menu":
            return
        if not NEWS_TARGET_CHAT:
            await safe_answer_cb(cb, "NEWS_CHANNEL_ID не задан", alert=True)
            return
        await safe_answer_cb(cb, "⏳ Публикую...", alert=False)
        post = await publish_specific_news(kind)
        if post is None:
            await safe_answer_cb(cb, "⚠️ Не удалось опубликовать", alert=True)
            return
        # Прекрасный UX: показываем превью опубликованного
        preview = post.text[:1000]
        await safe_send(
            cb.message.chat.id if cb.message else cb.from_user.id,
            f"✅ <b>Опубликовано ({kind}):</b>\n\n{preview}",
        )
    except Exception as e:
        log_exc("cb_admin_news_publish", e)


# =============================================================================
#  ПРОМОКОДЫ (FSM)
# =============================================================================

@router.callback_query(F.data == cb_build("adm", "promo", "list"))
async def cb_admin_promo_list(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        if cb.message is None:
            return
        promos = await list_promos(20)
        lines = ["🎟 <b>Промокоды</b>\n"]
        if not promos:
            lines.append("Пока нет активных промокодов.")
        else:
            for p in promos:
                exp = p.get("expires_at") or 0
                exp_str = (
                    dt.datetime.fromtimestamp(float(exp)).strftime("%d.%m %H:%M")
                    if float(exp) > 0 else "∞"
                )
                lines.append(
                    f"<code>{p['code']}</code> — {fmt_int(p['amount'])} "
                    f"({p['uses']}/{p['max_uses']}) до {exp_str}"
                )
        # Кнопка создания
        b = InlineKeyboardBuilder()
        b.button(text="➕ Создать промокод", callback_data=cb_build("adm", "promo", "create"))
        b.button(text="🧹 Очистить истёкшие", callback_data=cb_build("adm", "promo", "purge"))
        b.button(text=BTN_BACK, callback_data=cb_build("adm", "dash", "refresh"))
        b.adjust(1, 1, 1)
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id,
            "\n".join(lines), reply_markup=b.as_markup(),
        )
    except Exception as e:
        log_exc("cb_admin_promo_list", e)


@router.callback_query(F.data == cb_build("adm", "promo", "purge"))
async def cb_admin_promo_purge(cb: CallbackQuery) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        n = await purge_expired_promos()
        await safe_answer_cb(cb, f"Удалено: {n}", alert=True)
    except Exception as e:
        log_exc("cb_admin_promo_purge", e)


@router.callback_query(F.data == cb_build("adm", "promo", "create"))
async def cb_admin_promo_create(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        if cb.message is None:
            return
        await state.clear()
        await state.set_state(AdminStates.waiting_promo_code)
        await safe_edit_or_send(
            cb.message.chat.id, cb.message.message_id,
            "🎟 Введите код промокода (латиница, цифры, до 20 символов):",
            reply_markup=kb_cancel(),
        )
    except Exception as e:
        log_exc("cb_admin_promo_create", e)


@router.message(StateFilter(AdminStates.waiting_promo_code), F.text)
async def fsm_admin_promo_code(message: Message, state: FSMContext) -> None:
    try:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        code = (message.text or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9_]{1,20}", code):
            await safe_send_autodelete(
                message.chat.id,
                "🚫 Код должен содержать только A-Z, 0-9, _ (до 20 символов).",
                delay=10,
            )
            return
        await state.update_data(promo_code=code)
        await state.set_state(AdminStates.waiting_promo_amount)
        await safe_send_autodelete(
            message.chat.id,
            f"Код: <code>{code}</code>\nВведите сумму в TOKENS:",
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_cancel(),
        )
    except Exception as e:
        log_exc("fsm_admin_promo_code", e)


@router.message(StateFilter(AdminStates.waiting_promo_amount), F.text)
async def fsm_admin_promo_amount(message: Message, state: FSMContext) -> None:
    try:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        amount = parse_amount(message.text or "")
        if amount is None or amount <= 0:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        await state.update_data(promo_amount=amount)
        await state.set_state(AdminStates.waiting_promo_uses)
        await safe_send_autodelete(
            message.chat.id,
            f"Сумма: <b>{fmt_int(amount)}</b>\nВведите количество активаций (целое число):",
            delay=AUTODELETE_DEFAULT_SEC,
            reply_markup=kb_cancel(),
        )
    except Exception as e:
        log_exc("fsm_admin_promo_amount", e)


@router.message(StateFilter(AdminStates.waiting_promo_uses), F.text)
async def fsm_admin_promo_uses(message: Message, state: FSMContext) -> None:
    try:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        uses = parse_amount(message.text or "")
        if uses is None or uses <= 0 or uses > 100_000:
            await safe_send_autodelete(message.chat.id, "🚫 Некорректное число.", delay=5)
            return
        data = await state.get_data()
        code = data.get("promo_code") or ""
        amount = int(data.get("promo_amount") or 0)
        # Срок: 7 дней по умолчанию
        expires_at = now_ts() + 7 * 86400
        ok = await create_promo(code, amount, uses, expires_at, message.from_user.id)
        await state.clear()
        if ok:
            await safe_send_autodelete(
                message.chat.id,
                f"✅ Промокод <code>{code}</code> создан!\n"
                f"Сумма: {fmt_int(amount)}\n"
                f"Активаций: {uses}\n"
                f"Срок: 7 дней",
                delay=AUTODELETE_LONG_SEC,
            )
            await log_admin_action(
                message.from_user.id, "promo_create", details=f"code={code} amount={amount} uses={uses}",
            )
        else:
            await safe_send_autodelete(message.chat.id, "⚠️ Не удалось создать промокод.", delay=5)
    except Exception as e:
        log_exc("fsm_admin_promo_uses", e)
        with contextlib.suppress(Exception):
            await state.clear()


# =============================================================================
#  БАН / РАЗБАН
# =============================================================================

@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    try:
        if not _require_admin(message) or message.from_user is None:
            return
        # Цель: reply или /ban <id>
        target_id: Optional[int] = None
        parts = (message.text or "").split(maxsplit=1)
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
        elif len(parts) >= 2 and parts[1].strip().isdigit():
            target_id = int(parts[1].strip())
        if target_id is None:
            await safe_send_autodelete(
                message.chat.id,
                "🚫 Укажите: /ban <id> или ответьте на сообщение.",
                delay=AUTODELETE_SHORT_SEC,
            )
            return
        await ensure_user(target_id)
        await set_ban(target_id, True)
        await log_admin_action(message.from_user.id, "ban", target_id)
        await safe_send_autodelete(
            message.chat.id,
            f"⛔ Пользователь <code>{target_id}</code> забанен.",
            delay=AUTODELETE_DEFAULT_SEC,
        )
    except Exception as e:
        log_exc("cmd_ban", e)


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    try:
        if not _require_admin(message) or message.from_user is None:
            return
        target_id: Optional[int] = None
        parts = (message.text or "").split(maxsplit=1)
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
        elif len(parts) >= 2 and parts[1].strip().isdigit():
            target_id = int(parts[1].strip())
        if target_id is None:
            await safe_send_autodelete(
                message.chat.id,
                "🚫 Укажите: /unban <id> или ответьте на сообщение.",
                delay=AUTODELETE_SHORT_SEC,
            )
            return
        await ensure_user(target_id)
        await set_ban(target_id, False)
        await log_admin_action(message.from_user.id, "unban", target_id)
        await safe_send_autodelete(
            message.chat.id,
            f"✅ Пользователь <code>{target_id}</code> разбанен.",
            delay=AUTODELETE_DEFAULT_SEC,
        )
    except Exception as e:
        log_exc("cmd_unban", e)


# =============================================================================
#  ВЫДАТЬ / ЗАБРАТЬ БАЛАНС
# =============================================================================

@router.message(Command("give"))
async def cmd_give(message: Message) -> None:
    try:
        if not _require_admin(message) or message.from_user is None:
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            await safe_send_autodelete(
                message.chat.id, "🚫 Формат: /give <id> <сумма>", delay=5,
            )
            return
        if not parts[1].isdigit():
            return
        target_id = int(parts[1])
        amount = parse_amount(parts[2])
        if amount is None or amount <= 0:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        await ensure_user(target_id)
        await add_balance(target_id, amount, reason=f"admin_give:{message.from_user.id}")
        await log_admin_action(message.from_user.id, "give", target_id, f"amount={amount}")
        await safe_send_autodelete(
            message.chat.id,
            f"✅ Начислено <b>+{fmt_int(amount)}</b> пользователю <code>{target_id}</code>.",
            delay=AUTODELETE_DEFAULT_SEC,
        )
    except Exception as e:
        log_exc("cmd_give", e)


@router.message(Command("take"))
async def cmd_take(message: Message) -> None:
    try:
        if not _require_admin(message) or message.from_user is None:
            return
        parts = (message.text or "").split()
        if len(parts) < 3 or not parts[1].isdigit():
            await safe_send_autodelete(
                message.chat.id, "🚫 Формат: /take <id> <сумма>", delay=5,
            )
            return
        target_id = int(parts[1])
        amount = parse_amount(parts[2])
        if amount is None or amount <= 0:
            await safe_send_autodelete(message.chat.id, TXT_INVALID_AMOUNT, delay=5)
            return
        ok, nb = await try_withdraw(target_id, amount, reason=f"admin_take:{message.from_user.id}")
        await log_admin_action(message.from_user.id, "take", target_id, f"amount={amount}")
        if ok:
            await safe_send_autodelete(
                message.chat.id,
                f"✅ Списано <b>{fmt_int(amount)}</b> у <code>{target_id}</code>. "
                f"Остаток: {fmt_int(nb)}.",
                delay=AUTODELETE_DEFAULT_SEC,
            )
        else:
            await safe_send_autodelete(
                message.chat.id, "🚫 Недостаточно средств у пользователя.", delay=5,
            )
    except Exception as e:
        log_exc("cmd_take", e)


# =============================================================================
#  РАССЫЛКА
# =============================================================================

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    try:
        if not _require_admin(message):
            return
        # Если reply — берём текст оттуда, иначе — после команды
        text = ""
        if message.reply_to_message and message.reply_to_message.text:
            text = message.reply_to_message.text
        else:
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) >= 2:
                text = parts[1].strip()
        if not text:
            await safe_send_autodelete(
                message.chat.id,
                "📣 Формат: <code>/broadcast текст</code>\n"
                "или ответьте на сообщение с текстом.",
                delay=AUTODELETE_LONG_SEC,
            )
            return
        # Подтверждение
        await state.update_data(broadcast_text=text)
        await state.set_state(AdminStates.waiting_broadcast)
        await safe_send_autodelete(
            message.chat.id,
            f"📣 <b>Предпросмотр рассылки:</b>\n\n{text[:3000]}\n\n"
            f"Подтвердить отправку всем пользователям?",
            delay=AUTODELETE_LONG_SEC,
            reply_markup=kb_confirm("bc", "send"),
        )
    except Exception as e:
        log_exc("cmd_broadcast", e)


@router.callback_query(F.data.startswith("bc:send"))
async def cb_broadcast_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        await safe_answer_cb(cb)
        if not await _require_admin_cb(cb):
            return
        data = await state.get_data()
        text = data.get("broadcast_text") or ""
        await state.clear()
        if not text:
            await safe_answer_cb(cb, "Текст потерян", alert=True)
            return
        # Запускаем рассылку в фоне
        asyncio.create_task(_run_broadcast(text, cb.from_user.id), name="broadcast_task")
        await safe_answer_cb(cb, "🚀 Рассылка запущена", alert=True)
    except Exception as e:
        log_exc("cb_broadcast_confirm", e)


async def _run_broadcast(text: str, admin_id: int) -> None:
    """Фоновая рассылка с rate-limit и отчётом админу."""
    try:
        rows = await _fetchall("SELECT user_id FROM users WHERE is_banned = 0")
        total = len(rows)
        sent_ok = 0
        sent_fail = 0
        for row in rows:
            uid = int(row["user_id"])
            try:
                await safe_send(uid, text)
                sent_ok += 1
            except Exception:
                sent_fail += 1
            # Rate-limit: Telegram не любит >30 msg/sec
            await asyncio.sleep(0.05)
        await log_admin_action(
            admin_id, "broadcast",
            details=f"ok={sent_ok} fail={sent_fail} total={total}",
        )
        await safe_send(
            admin_id,
            f"📣 <b>Рассылка завершена</b>\n"
            f"Успешно: {sent_ok}\n"
            f"Ошибок: {sent_fail}\n"
            f"Всего: {total}",
        )
    except Exception as e:
        log_exc("_run_broadcast", e)


# =============================================================================
#  АНТИЧИТ: ПРОВЕРКА АНОМАЛИЙ
# =============================================================================
#  Запускается планировщиком (ЧАСТЬ 10) каждые 15 минут.
#  Ищет юзеров с подозрительной активностью (много игр подряд без паузы).
#  Шлёт алерт главному админу в ЛС.

async def anticheat_scan() -> None:
    """Ищет аномалии и шлёт алерты главному админу."""
    try:
        if MAIN_ADMIN_ID == 0:
            return
        # Аномалия: > 50 игр за последний час
        since = now_ts() - 3600
        rows = await _fetchall(
            "SELECT user_id, COUNT(*) AS c FROM games_log "
            "WHERE created_at >= ? GROUP BY user_id "
            "HAVING c >= 50 ORDER BY c DESC LIMIT 5",
            (since,),
        )
        for r in rows:
            uid = int(r["user_id"])
            count = int(r["c"])
            u = await get_user(uid)
            name = safe_name_from_dict(u or {"user_id": uid})
            text = (
                f"🚨 <b>Античит-алерт</b>\n"
                f"Пользователь: {html_escape(name)} (<code>{uid}</code>)\n"
                f"Игр за час: <b>{count}</b>\n"
                f"Возможен фарм. Проверьте."
            )
            with contextlib.suppress(Exception):
                await safe_send(MAIN_ADMIN_ID, text)
            with contextlib.suppress(Exception):
                await log_bot_activity(
                    "anticheat_alert", f"user={uid} games_1h={count}",
                )
    except Exception as e:
        log_exc("anticheat_scan", e)


# =============================================================================
#  КОНЕЦ ЧАСТИ 9
# =============================================================================
#  ЧАСТЬ 10 подключит: АВТОНОМНЫЙ МОЗГ (APScheduler), Веб-сервер, main(), запуск.

# =============================================================================
#  ЧАСТЬ 10 / 10 — АВТОНОМНЫЙ МОЗГ, ВЕБ-СЕРВЕР, MAIN, ЗАПУСК
#  Содержание:
#    - Работа с медиа (папка images/ + Fallback на текст)
#    - Планировщик APScheduler (турниры, джекпот, нейро-общение, экономика)
#    - Асинхронный aiohttp веб-сервер (healthcheck для Render)
#    - Глобальный error handler для aiogram 3
#    - Функция main() с корректной инициализацией и graceful shutdown
# =============================================================================

# =============================================================================
#  1. МЕДИА-ХЕЛПЕРЫ (КАРТИНКИ ИЗ ПАПКИ images/)
# =============================================================================
#  Требование: Fallback на текст, если картинки нет или Телеграм выдал ошибку.
#  Используем FSInputFile для локальных файлов.

IMAGES_DIR: Path = BASE_DIR / "images"

# Маппинг ключей на файлы
IMAGE_FILES: Dict[str, str] = {
    "start": "start.jpg",
    "profile": "profile.jpg",
    "bonus": "bonus.jpg",
    "chats": "chats.jpg",
    "commands": "commands.jpg",
    "donate": "donate.jpg",
    "how_to_play": "how_to_play.jpg",
    "ref": "ref.jpg",
    "support": "support.jpg",
    "top": "top.jpg",
}

def get_image_path(key: str) -> Optional[Path]:
    """Возвращает путь к картинке, если она существует."""
    try:
        filename = IMAGE_FILES.get(key)
        if not filename:
            return None
        p = IMAGES_DIR / filename
        if p.exists() and p.is_file():
            return p
        return None
    except Exception as e:
        log_exc("get_image_path", e)
        return None


async def safe_send_photo_or_text(
    chat_id: int,
    photo_key: str,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.HTML,
    autodelete: Optional[int] = None,
) -> Optional[Message]:
    """
    Пытается отправить фото с подписью. Если фото нет или ошибка — шлёт текст.
    Поддерживает автоудаление, если указан параметр autodelete.
    """
    b = require_bot()
    photo_path = get_image_path(photo_key)
    msg = None
    
    if photo_path is not None:
        try:
            input_file = FSInputFile(photo_path)
            # Подпись ограничена 1024 символами
            caption = text[:TG_MAX_CAPTION]
            msg = await b.send_photo(
                chat_id=chat_id,
                photo=input_file,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as e:
            log.warning("safe_send_photo_or_text bad_request (%s): %s", photo_key, e)
            msg = None
        except Exception as e:
            log_exc("safe_send_photo_or_text.photo", e)
            msg = None

    # Fallback на текст (если фото упало или его нет)
    if msg is None:
        sent_list = await safe_send(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        msg = sent_list[-1] if sent_list else None

    # Автоудаление
    if msg is not None and autodelete is not None:
        with contextlib.suppress(Exception):
            _spawn_autodelete(chat_id, msg.message_id, autodelete)
            
    return msg


# =============================================================================
#  2. АВТОНОМНЫЙ МОЗГ (APScheduler)
# =============================================================================
#  Бот сам создает движуху. Все задачи обернуты в try/except, чтобы
#  падение одной задачи не убило планировщик.

async def task_auto_tournaments() -> None:
    """Раз в 6 часов создает турнир в случайном event_chat."""
    try:
        chats = await list_event_chats(50)
        if not chats:
            return
        # Выбираем случайный чат
        target = random.choice(chats)
        chat_id = int(target["chat_id"])
        # Проверяем, нет ли уже активного
        active = await get_active_tournament(chat_id)
        if active:
            return
        # Создаем
        prize = random.choice((50_000, 100_000, 250_000))
        tid = await create_tournament(chat_id, TOURNAMENT_DURATION_MIN, prize)
        if not tid:
            return
        text = TXT_TOURNAMENT_START.format(
            minutes=TOURNAMENT_DURATION_MIN, prize=fmt_int(prize)
        )
        await safe_send(chat_id, text)
        await log_bot_activity("auto_tournament_start", f"chat={chat_id} tid={tid} prize={prize}")
    except Exception as e:
        log_exc("task_auto_tournaments", e)

async def task_finalize_tournaments() -> None:
    """Раз в 5 минут проверяет и закрывает истекшие турниры."""
    try:
        expired = await list_expired_active_tournaments()
        for t in expired:
            tid = int(t["id"])
            chat_id = int(t["chat_id"])
            res = await finalize_tournament(tid)
            if not res:
                continue
            awards = res["awards"]
            if not awards:
                await safe_send(chat_id, "🏁 Турнир завершён. Активности не было.")
                continue
            # Формируем отчет
            text = TXT_TOURNAMENT_END.format(
                p1_name=html_escape(awards[0]["name"]) if len(awards) > 0 else "-",
                p1_score=fmt_int(awards[0]["score"]) if len(awards) > 0 else 0,
                p1_prize=fmt_int(awards[0]["prize"]) if len(awards) > 0 else 0,
                p2_name=html_escape(awards[1]["name"]) if len(awards) > 1 else "-",
                p2_score=fmt_int(awards[1]["score"]) if len(awards) > 1 else 0,
                p2_prize=fmt_int(awards[1]["prize"]) if len(awards) > 1 else 0,
                p3_name=html_escape(awards[2]["name"]) if len(awards) > 2 else "-",
                p3_score=fmt_int(awards[2]["score"]) if len(awards) > 2 else 0,
                p3_prize=fmt_int(awards[2]["prize"]) if len(awards) > 2 else 0,
            )
            await safe_send(chat_id, text)
            await log_bot_activity("auto_tournament_end", f"chat={chat_id} tid={tid}")
    except Exception as e:
        log_exc("task_finalize_tournaments", e)

async def task_jackpot_check() -> None:
    """Раз в час проверяет пул джекпота. Если огромный — форсит."""
    try:
        pool = await jackpot_get_pool()
        if pool < JACKPOT_FORCE_THRESHOLD:
            return
        # Ищем случайного активного юзера
        rows = await _fetchall("SELECT user_id FROM users WHERE last_seen > ? ORDER BY RANDOM() LIMIT 1", (now_ts() - 86400,))
        if not rows:
            return
        winner_id = int(rows[0]["user_id"])
        # Забираем пул
        amount = await jackpot_take_all(winner_id, None)
        if amount > 0:
            u = await get_user(winner_id)
            name = safe_name_from_dict(u or {"user_id": winner_id})
            text = TXT_JACKPOT_FORCED.format(
                pool=fmt_int(pool), winner=html_escape(name), amount=fmt_int(amount)
            )
            # Пишем в новостной канал
            if NEWS_TARGET_CHAT:
                await safe_send(NEWS_TARGET_CHAT, text)
            await log_bot_activity("jackpot_forced", f"winner={winner_id} amount={amount}")
    except Exception as e:
        log_exc("task_jackpot_check", e)

async def task_neuro_communication() -> None:
    """Нейро-общение: раз в 1-3 часа пишет в event_chats."""
    try:
        chats = await list_event_chats(20)
        if not chats:
            return
        for c in chats:
            chat_id = int(c["chat_id"])
            last_fired = float(c.get("last_event_at") or 0)
            # Если недавно писали — пропускаем
            if now_ts() - last_fired < random.randint(NEURO_IDLE_MIN * 60, NEURO_IDLE_MAX * 60):
                continue
            
            # Выбираем фразу
            phrase = random.choice(NEURO_IDLE_PHRASES)
            
            # Если был недавний крупный выигрыш — можно поздравить
            last_win = chat_last_winner.get(chat_id)
            if last_win and (time.time() - last_win.get("ts", 0)) < 3600:
                phrase = random.choice(NEURO_WIN_STREAK_PHRASES).format(
                    name=html_escape(last_win["name"]), streak=random.randint(3, 5)
                )

            await safe_send_autodelete(chat_id, phrase, delay=AUTODELETE_LONG_SEC)
            await mark_event_chat_fired(chat_id)
            await log_bot_activity("neuro_chat", f"chat={chat_id}")
            break  # по одному чату за тик, чтобы не спамить
    except Exception as e:
        log_exc("task_neuro_communication", e)

async def task_economy_regulator() -> None:
    """Раз в сутки анализирует экономику и регулирует комиссию."""
    try:
        snap = await economy_snapshot_today()
        ratio = await economy_balance_ratio()
        
        # Логика: если сжигают больше, чем зарабатывают (ratio > 1.2) — снижаем комиссию.
        # Если инфляция (ratio < 0.8) — повышаем.
        new_comm = BURN_COMMISSION_BASE
        if ratio > 1.2:
            new_comm = max(0.02, BURN_COMMISSION_BASE - 0.02)
        elif ratio < 0.8:
            new_comm = min(0.15, BURN_COMMISSION_BASE + 0.02)
            
        if new_comm != BURN_COMMISSION_BASE:
            # Обновляем во всех чатах
            async with db_conn() as conn:
                await conn.execute("UPDATE chat_settings SET commission = ?", (new_comm,))
            await log_bot_activity("economy_regulated", f"new_commission={new_comm:.2f} ratio={ratio:.2f}")
            
            # Уведомляем новостной канал
            if NEWS_TARGET_CHAT:
                await safe_send(NEWS_TARGET_CHAT, TXT_ECONOMY_NOTICE.format(commission=new_comm*100))
    except Exception as e:
        log_exc("task_economy_regulator", e)

async def task_sleeping_revive() -> None:
    """Реанимация спящих: шлет пуш в ЛС."""
    try:
        users = await find_sleeping_users(days=SLEEPING_USER_DAYS, limit=20)
        for u in users:
            uid = int(u["user_id"])
            name = safe_name_from_dict(u)
            text = NEURO_SLEEPING_PUSH.format(
                name=html_escape(name.split()[0]), amount=fmt_int(SLEEPING_REVIVE_BONUS)
            )
            sent = await safe_send(uid, text)
            if sent:
                await add_balance(uid, SLEEPING_REVIVE_BONUS, reason="revive_bonus")
                await mark_revive_sent(uid)
                await asyncio.sleep(0.1)  # rate limit
    except Exception as e:
        log_exc("task_sleeping_revive", e)

async def task_news_autopilot() -> None:
    """Авто-генератор новостей из ЧАСТИ 4."""
    await news_autopilot_tick()

async def task_anticheat() -> None:
    """Античит из ЧАСТИ 9."""
    await anticheat_scan()


# =============================================================================
#  3. AIOHTTP WEB SERVER (HEALTHCHECK ДЛЯ RENDER)
# =============================================================================

async def healthcheck_handler(request: web.Request) -> web.Response:
    """JSON-статус для Render."""
    try:
        stats = await dashboard_stats()
        status = {
            "status": "ok",
            "bot_ready": BOT_READY,
            "uptime_sec": int(time.time() - BOT_START_TS),
            "users_online": stats["online"],
            "total_users": stats["users"],
            "version": BOT_VERSION,
        }
        return web.json_response(status, status=200)
    except Exception as e:
        log_exc("healthcheck_handler", e)
        return web.json_response({"status": "error", "detail": str(e)}, status=500)

async def start_web_server() -> web.AppRunner:
    """Запускает aiohttp сервер на PORT."""
    app = web.Application()
    app.router.add_get("/", healthcheck_handler)
    app.router.add_get("/health", healthcheck_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Веб-сервер запущен на порту %s", PORT)
    return runner


# =============================================================================
#  4. ГЛОБАЛЬНЫЙ ERROR HANDLER
# =============================================================================

async def global_error_handler(event: Any) -> bool:
    """Ловит все необработанные ошибки aiogram."""
    try:
        log_exc("global_error_handler", event.exception)
        # Пытаемся ответить юзеру
        update = event.update
        if update.message:
            await safe_send(update.message.chat.id, "⚠️ Произошла системная ошибка. Админы уже уведомлены.")
        elif update.callback_query and update.callback_query.message:
            await safe_answer_cb(update.callback_query, "⚠️ Ошибка", alert=True)
    except Exception:
        pass
    return True


# =============================================================================
#  5. MAIN — ТОЧКА ВХОДА
# =============================================================================

async def main() -> None:
    global bot, dp, scheduler, BOT_START_TS
    BOT_START_TS = time.time()
    
    log.info("=== ЗАПУСК %s v%s ===", BOT_NAME, BOT_VERSION)
    
    # 1. Валидация окружения
    validate_env()
    if not BOT_TOKEN:
        log.error("Нет BOT_TOKEN. Остановка.")
        return

    # 2. Удаление старой БД (требование Render)
    purge_old_database()
    
    # 3. Инициализация БД
    await create_tables()
    await ensure_quest_templates()
    
    # 4. Инициализация бота
    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(token=BOT_TOKEN, default=default_props)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрируем роутер
    dp.include_router(router)
    dp.errors.register(global_error_handler)
    
    # 5. Запуск веб-сервера ДО поллинга
    web_runner = await start_web_server()
    
    # 6. Инициализация планировщика
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # Турниры
    scheduler.add_job(task_auto_tournaments, IntervalTrigger(hours=TOURNAMENT_INTERVAL_HOURS), id="auto_tourn", replace_existing=True)
    scheduler.add_job(task_finalize_tournaments, IntervalTrigger(minutes=5), id="finalize_tourn", replace_existing=True)
    
    # Джекпот
    scheduler.add_job(task_jackpot_check, IntervalTrigger(minutes=JACKPOT_CHECK_MIN), id="jackpot", replace_existing=True)
    
    # Нейро-общение
    scheduler.add_job(task_neuro_communication, IntervalTrigger(minutes=30), id="neuro", replace_existing=True)
    
    # Экономика
    scheduler.add_job(task_economy_regulator, IntervalTrigger(hours=ECONOMY_REGULATOR_HOURS), id="economy", replace_existing=True)
    
    # Реанимация
    scheduler.add_job(task_sleeping_revive, IntervalTrigger(hours=12), id="revive", replace_existing=True)
    
    # Новости
    scheduler.add_job(task_news_autopilot, IntervalTrigger(hours=4), id="news", replace_existing=True)
    
    # Античит
    scheduler.add_job(task_anticheat, IntervalTrigger(minutes=15), id="anticheat", replace_existing=True)
    
    scheduler.start()
    log.info("APScheduler запущен.")
    
    # 7. Установка команд бота
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="profile", description="Профиль"),
            BotCommand(command="daily", description="Бонус"),
            BotCommand(command="top", description="Топ игроков"),
            BotCommand(command="help", description="Помощь"),
        ])
    except Exception as e:
        log_exc("set_commands", e)

    # 8. Поллинг
    BOT_READY = True
    log.info("Бот готов к приёму сообщений!")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        log_exc("polling", e)
    finally:
        log.info("Завершение работы...")
        BOT_READY = False
        with contextlib.suppress(Exception):
            scheduler.shutdown(wait=False)
        with contextlib.suppress(Exception):
            await web_runner.cleanup()
        with contextlib.suppress(Exception):
            await bot.session.close()
        log.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановка по сигналу.")
    except Exception as e:
        log_exc("__main__", e)
        sys.exit(1)