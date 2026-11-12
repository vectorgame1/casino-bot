# bot.py
# TOKENS | PRIVATE CLUB — Telegram Bot
# aiogram 3.x + aiohttp + aiosqlite
# Senior Python Developer Edition

import asyncio
import logging
import os
import time
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    Dice,
    PreCheckoutQuery,
    SuccessfulPayment,
    LabeledPrice,
    BotCommand,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# ============================================================
# ===                 НАСТРОЙКИ / ENV                     ===
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
PORT = int(os.getenv("PORT", "8080"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com/app")
DB_PATH = os.getenv("DB_PATH", "tokens.db")

# ID администраторов (через запятую в env)
ADMIN_IDS: List[int] = []
_raw_admins = os.getenv("ADMIN_IDS", "")
if _raw_admins:
    for _a in _raw_admins.split(","):
        _a = _a.strip()
        if _a.lstrip("-").isdigit():
            ADMIN_IDS.append(int(_a))

# Экономика
BONUS_AMOUNT = 5000
BONUS_COOLDOWN = 24 * 60 * 60  # 24 часа
VIP_PRICE_TOKENS = 50000
VIP_DURATION = 30 * 24 * 60 * 60  # 30 дней

# Игровые лимиты
MIN_BET = 100
MAX_BET = 500_000
GAME_COOLDOWN = 3  # сек (анти double-spend)
USER_CACHE_TTL = 5  # сек кэш get_user

# Прочее
START_BALANCE = 5000
RULETTE_PAUSE = 3
DICE_TIMEOUT = 3
AUTO_DELETE = 15

# Курс (для конвертаций, если понадобится)
DEFAULT_RATE = 1.0

# ============================================================
# ===                    ЛОГИРОВАНИЕ                      ===
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("TOKENS")

# ============================================================
# ===                    ИНИЦИАЛИЗАЦИЯ                    ===
# ============================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ============================================================
# ===                ГЛОБАЛЬНЫЕ СОСТОЯНИЯ                  ===
# ============================================================

# Кэш пользователей: {user_id: (timestamp, data)}
_user_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}

# Кулдаун игр: {user_id: last_play_ts}
_game_cooldown: Dict[int, float] = {}

# Активные дуэли: {duel_id: {...}}
_active_duels: Dict[str, Dict[str, Any]] = {}

# Активные мины: {user_id: {...}}
_active_mines: Dict[int, Dict[str, Any]] = {}

# Флаги
GAMES_ENABLED = True
TRANSFERS_ENABLED = True
MAINTENANCE_MODE = False

# ============================================================
# ===                     БАЗА ДАННЫХ                    ===
# ============================================================

import aiosqlite


class Database:
    """Асинхронная обёртка над SQLite с WAL и пулом соединений."""

    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.commit()
        log.info("БД подключена: %s", self.path)

    async def close(self):
        if self._conn:
            await self._conn.close()
            log.info("БД отключена")

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "БД не инициализирована"
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cur

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    async def fetchall(self, sql: str, params: tuple = ()) -> List[aiosqlite.Row]:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows


db = Database(DB_PATH)


async def init_db():
    """Создание всех таблиц при старте."""
    await db.connect()

    # Пользователи
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            username       TEXT,
            first_name     TEXT,
            balance        INTEGER NOT NULL DEFAULT 0,
            games_played   INTEGER NOT NULL DEFAULT 0,
            games_won      INTEGER NOT NULL DEFAULT 0,
            total_wagered  INTEGER NOT NULL DEFAULT 0,
            total_won      INTEGER NOT NULL DEFAULT 0,
            vip_until      INTEGER NOT NULL DEFAULT 0,
            banned         INTEGER NOT NULL DEFAULT 0,
            ban_reason     TEXT,
            hidden_balance INTEGER NOT NULL DEFAULT 0,
            no_transfers   INTEGER NOT NULL DEFAULT 0,
            language       TEXT NOT NULL DEFAULT 'ru',
            clan_id        INTEGER,
            registered_at  INTEGER NOT NULL DEFAULT 0,
            last_bonus     INTEGER NOT NULL DEFAULT 0,
            last_seen      INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Игровые логи
    await db.execute("""
        CREATE TABLE IF NOT EXISTS game_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            game_type   TEXT NOT NULL,
            bet         INTEGER NOT NULL,
            win         INTEGER NOT NULL,
            result      TEXT,
            created_at  INTEGER NOT NULL
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id, created_at)")

    # Транзакции
    await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            type        TEXT NOT NULL,
            description TEXT,
            created_at  INTEGER NOT NULL
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, created_at)")

    # Кланы
    await db.execute("""
        CREATE TABLE IF NOT EXISTS clans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            owner_id    INTEGER NOT NULL,
            balance     INTEGER NOT NULL DEFAULT 0,
            created_at  INTEGER NOT NULL
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS clan_members (
            user_id     INTEGER PRIMARY KEY,
            clan_id     INTEGER NOT NULL,
            role        TEXT NOT NULL DEFAULT 'member',
            joined_at   INTEGER NOT NULL
        )
    """)

    # Дуэли
    await db.execute("""
        CREATE TABLE IF NOT EXISTS duels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger  INTEGER NOT NULL,
            opponent    INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  INTEGER NOT NULL
        )
    """)

    # Админ-лог
    await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER NOT NULL,
            action      TEXT NOT NULL,
            target_id   INTEGER,
            details     TEXT,
            created_at  INTEGER NOT NULL
        )
    """)

    # Настройки бота
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Ежедневные награды (для бонуса)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id     INTEGER PRIMARY KEY,
            last_claim  INTEGER NOT NULL
        )
    """)

    # Заготовки под Mini App (сессии/токены)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS web_sessions (
            token       TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            created_at  INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL
        )
    """)

    # Инициализация дефолтных настроек
    defaults = {
        "rate": str(DEFAULT_RATE),
        "games_enabled": "1",
        "transfers_enabled": "1",
    }
    for k, v in defaults.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v)
        )

    log.info("Все таблицы созданы/проверены.")


# ============================================================
# ===              ХЕЛПЕРЫ РАБОТЫ С БД                   ===
# ============================================================

def now_ts() -> int:
    return int(time.time())


def fmt_num(n: int) -> str:
    """Форматирование числа с пробелами: 5000 -> '5 000'."""
    return f"{int(n):,}".replace(",", " ")


async def get_user(user_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Получить пользователя (кэш 5 сек)."""
    ts = time.time()
    if use_cache:
        cached = _user_cache.get(user_id)
        if cached and (ts - cached[0]) < USER_CACHE_TTL:
            return cached[1]

    row = await db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not row:
        return None
    data = dict(row)
    _user_cache[user_id] = (ts, data)
    return data


async def ensure_user(
    user_id: int, username: Optional[str] = None, first_name: Optional[str] = None
) -> Dict[str, Any]:
    """Создать пользователя если нет, иначе обновить профиль."""
    row = await db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if row is None:
        await db.execute(
            """INSERT INTO users(user_id, username, first_name, balance, registered_at, last_seen)
               VALUES(?, ?, ?, ?, ?, ?)""",
            (user_id, username, first_name, START_BALANCE, now_ts(), now_ts()),
        )
        log.info("Новый пользователь: %s (%s)", user_id, first_name)
        _user_cache.pop(user_id, None)
        data = await get_user(user_id, use_cache=False)
        assert data is not None
        return data
    else:
        # Обновим username/first_name и last_seen
        await db.execute(
            """UPDATE users SET username = COALESCE(?, username),
                               first_name = COALESCE(?, first_name),
                               last_seen = ?
               WHERE user_id = ?""",
            (username, first_name, now_ts(), user_id),
        )
        _user_cache.pop(user_id, None)
        data = dict(row)
        data["username"] = username or data.get("username")
        data["first_name"] = first_name or data.get("first_name")
        data["last_seen"] = now_ts()
        _user_cache[user_id] = (time.time(), data)
        return data


async def change_balance(user_id: int, delta: int, tx_type: str = "system",
                         description: str = "") -> int:
    """Атомарно изменить баланс и записать транзакцию. Возвращает новый баланс."""
    async with db._lock:
        cur = await db.conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (delta, user_id),
        )
        await db.conn.commit()
        await cur.close()
        await db.conn.execute(
            "INSERT INTO transactions(user_id, amount, type, description, created_at) VALUES(?,?,?,?,?)",
            (user_id, delta, tx_type, description, now_ts()),
        )
        await db.conn.commit()
        cur = await db.conn.execute(
            "SELECT balance FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        await cur.close()
    _user_cache.pop(user_id, None)
    return int(row["balance"]) if row else 0


async def set_balance(user_id: int, value: int, tx_type: str = "admin",
                      description: str = "") -> int:
    """Жёстко установить баланс (для админов)."""
    old = await get_user(user_id, use_cache=False)
    old_bal = int(old["balance"]) if old else 0
    delta = value - old_bal
    if delta != 0:
        await db.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?", (value, user_id)
        )
        await db.execute(
            "INSERT INTO transactions(user_id, amount, type, description, created_at) VALUES(?,?,?,?,?)",
            (user_id, delta, tx_type, description, now_ts()),
        )
    _user_cache.pop(user_id, None)
    return value


async def log_game(user_id: int, game: str, bet: int, win: int, result: str = ""):
    await db.execute(
        "INSERT INTO game_log(user_id, game_type, bet, win, result, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, game, bet, win, result, now_ts()),
    )
    # Обновим агрегаты
    if bet > 0:
        await db.execute(
            """UPDATE users SET games_played = games_played + 1,
                               total_wagered = total_wagered + ?
               WHERE user_id = ?""",
            (bet, user_id),
        )
        if win > 0:
            await db.execute(
                """UPDATE users SET games_won = games_won + 1,
                                   total_won = total_won + ?
                   WHERE user_id = ?""",
                (win, user_id),
            )
    _user_cache.pop(user_id, None)


async def log_admin(admin_id: int, action: str, target_id: Optional[int] = None,
                    details: str = ""):
    await db.execute(
        "INSERT INTO admin_log(admin_id, action, target_id, details, created_at) VALUES(?,?,?,?,?)",
        (admin_id, action, target_id, details, now_ts()),
    )


async def get_setting(key: str, default: str = "") -> str:
    row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str):
    await db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ============================================================
# ===           ПРОВЕРКИ / АНТИДУБЛЬ / КУЛДАУН          ===
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def check_cooldown(user_id: int) -> Tuple[bool, float]:
    """Проверить кулдаун игр. Возвращает (ok, осталось_сек)."""
    last = _game_cooldown.get(user_id, 0)
    diff = time.time() - last
    if diff < GAME_COOLDOWN:
        return False, GAME_COOLDOWN - diff
    return True, 0.0


def touch_cooldown(user_id: int):
    _game_cooldown[user_id] = time.time()


async def check_and_subtract_bet(user_id: int, bet: int) -> Tuple[bool, str, Optional[Dict]]:
    """Проверка ставки и списание. Возвращает (ok, message, user_data)."""
    global GAMES_ENABLED
    if not GAMES_ENABLED:
        return False, "🎮 Игры временно отключены администрацией.", None
    ok, left = check_cooldown(user_id)
    if not ok:
        return False, f"⏱ Подождите `{left:.1f}` сек. перед следующей игрой.", None
    if bet < MIN_BET:
        return False, f"Минимальная ставка — `{fmt_num(MIN_BET)}` TOKENS.", None
    if bet > MAX_BET:
        return False, f"Максимальная ставка — `{fmt_num(MAX_BET)}` TOKENS.", None
    user = await get_user(user_id, use_cache=False)
    if not user:
        return False, "Профиль не найден. Нажмите /start.", None
    if user["banned"]:
        return False, "🚫 Ваш доступ ограничен.", None
    if user["balance"] < bet:
        return False, f"Недостаточно средств. Ваш баланс: `{fmt_num(user['balance'])}` TOKENS.", None
    # Списываем (анти double-spend — сразу)
    touch_cooldown(user_id)
    await change_balance(user_id, -bet, tx_type="bet", description="Ставка")
    return True, "", user


# ============================================================
# ===                AIOHTTP WEB-СЕРВЕР                  ===
# ============================================================

web_app = web.Application()


def _json(data: Dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda x: json.dumps(x, ensure_ascii=False))


async def api_health(request: web.Request) -> web.Response:
    return _json({"status": "ok", "service": "TOKENS", "time": now_ts()})


async def api_user(request: web.Request) -> web.Response:
    """/api/user/{user_id} — информация о пользователе для Mini App."""
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json({"ok": False, "error": "invalid user_id"}, 400)

    user = await get_user(uid)
    if not user:
        return _json({"ok": False, "error": "user_not_found"}, 404)

    return _json({
        "ok": True,
        "user": {
            "user_id": uid,
            "first_name": user.get("first_name"),
            "username": user.get("username"),
            "balance": int(user["balance"]),
            "vip": bool(user["vip_until"] > now_ts()),
            "games_played": int(user["games_played"]),
            "games_won": int(user["games_won"]),
            "hidden_balance": bool(user["hidden_balance"]),
            "registered_at": int(user["registered_at"]),
        }
    })


async def api_bet(request: web.Request) -> web.Response:
    """/api/bet — приём ставки из Mini App.
    Ожидает JSON: {"user_id": int, "game": str, "bet": int, "choice": optional}
    """
    try:
        payload = await request.json()
    except Exception:
        return _json({"ok": False, "error": "invalid_json"}, 400)

    uid = payload.get("user_id")
    game = str(payload.get("game", "")).lower()
    bet = payload.get("bet")

    if not isinstance(uid, int) or not isinstance(bet, int):
        return _json({"ok": False, "error": "user_id and bet required (int)"}, 400)
    if bet <= 0:
        return _json({"ok": False, "error": "bet must be positive"}, 400)
    if game not in ("dice", "coin", "mines", "roulette", "slots"):
        return _json({"ok": False, "error": "unknown_game"}, 400)

    # Проверим доступность игр
    if not GAMES_ENABLED:
        return _json({"ok": False, "error": "games_disabled"}, 403)

    user = await get_user(uid)
    if not user:
        return _json({"ok": False, "error": "user_not_found"}, 404)
    if user["banned"]:
        return _json({"ok": False, "error": "user_banned"}, 403)
    if user["balance"] < bet:
        return _json({"ok": False, "error": "insufficient_funds",
                      "balance": int(user["balance"])}, 400)
    if bet < MIN_BET or bet > MAX_BET:
        return _json({"ok": False, "error": "bet_out_of_range"}, 400)

    # Кулдаун
    ok, left = check_cooldown(uid)
    if not ok:
        return _json({"ok": False, "error": "cooldown", "left": round(left, 2)}, 429)
    touch_cooldown(uid)

    # Списываем ставку
    await change_balance(uid, -bet, tx_type="web_bet", description=f"Mini App: {game}")

    # Простейшая логика выигрыша для API (для полноценного геймплея — отдельные эндпоинты)
    win = 0
    result_text = "lose"

    if game == "coin":
        # 50/50 x2
        if random.random() < 0.48:
            win = bet * 2
            result_text = "win"
    elif game == "dice":
        # бросок 1..6, win if >3 -> x2
        roll = random.randint(1, 6)
        if roll > 3:
            win = bet * 2
            result_text = f"win_roll_{roll}"
        else:
            result_text = f"lose_roll_{roll}"
    elif game == "slots":
        # 3 барабана 0..9
        reels = [random.randint(0, 9) for _ in range(3)]
        if reels[0] == reels[1] == reels[2]:
            win = bet * 10
            result_text = f"jackpot_{reels}"
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            win = bet * 2
            result_text = f"pair_{reels}"
        else:
            result_text = f"lose_{reels}"
    elif game == "roulette":
        # Простая рулетка: чёт/нечет по числу 0..36
        num = random.randint(0, 36)
        choice = str(payload.get("choice", "red"))
        if choice in ("even", "чёт") and num != 0 and num % 2 == 0:
            win = bet * 2
            result_text = f"win_even_{num}"
        elif choice in ("odd", "нечет") and num % 2 == 1:
            win = bet * 2
            result_text = f"win_odd_{num}"
        elif choice in ("red", "black"):
            reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
            if (choice == "red" and num in reds) or (choice == "black" and num != 0 and num not in reds):
                win = bet * 2
                result_text = f"win_{choice}_{num}"
            else:
                result_text = f"lose_{choice}_{num}"
        else:
            result_text = f"lose_{num}"
    elif game == "mines":
        # Заглушка: 30% шанс на x3 (в реальности — поле и открытия)
        if random.random() < 0.30:
            win = bet * 3
            result_text = "win_mines"
        else:
            result_text = "lose_mines"

    if win > 0:
        await change_balance(uid, win, tx_type="web_win", description=f"Mini App: {game}")

    await log_game(uid, f"web_{game}", bet, win, result_text)

    new_balance = (await get_user(uid, use_cache=False))["balance"]
    return _json({
        "ok": True,
        "result": result_text,
        "bet": bet,
        "win": win,
        "balance": int(new_balance),
    })


# Регистрируем роуты
web_app.router.add_get("/api/health", api_health)
web_app.router.add_get("/api/user/{user_id}", api_user)
web_app.router.add_post("/api/bet", api_bet)
# Заглушка для корня
web_app.router.add_get("/", lambda r: _json({"service": "TOKENS API", "status": "ok"}))


async def start_web_server():
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("🌐 Web API запущен на порту %s", PORT)


# ============================================================
# ===                  ЗАПУСК БОТА                        ===
# ============================================================

async def on_startup():
    await init_db()
    await start_web_server()

    # Команды бота
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="bonus", description="Ежедневный бонус"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="start_ru", description="Рулетка: старт"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        log.warning("Не удалось установить команды: %s", e)

    me = await bot.get_me()
    log.info("✅ Бот запущен: @%s (id=%s)", me.username, me.id)
    log.info("👥 Админов: %d", len(ADMIN_IDS))


async def on_shutdown():
    await db.close()
    log.info("Бот остановлен.")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Прервано пользователем.")

# ============================================================
# ===             REPLY-КЛАВИАТУРА И ГЛАВНОЕ МЕНЮ        ===
# ============================================================

BTN_GAMES = "🎮 Игры"
BTN_BONUS = "🎁 Бонус"
BTN_DONATE = "💎 Донат"
BTN_PROFILE = "👤 Профиль"
BTN_CLAN = "🛡 Клан"
BTN_TOP = "🏆 Топ"
BTN_CHATS = "💬 Чаты"
BTN_SUPPORT = "🆘 Поддержка"
BTN_MINIAPP = "📱 Мини-Апп"


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Главное меню (9 кнопок)."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=BTN_GAMES),
        KeyboardButton(text=BTN_BONUS),
        KeyboardButton(text=BTN_DONATE),
    )
    builder.row(
        KeyboardButton(text=BTN_PROFILE),
        KeyboardButton(text=BTN_CLAN),
        KeyboardButton(text=BTN_TOP),
    )
    builder.row(
        KeyboardButton(text=BTN_CHATS),
        KeyboardButton(text=BTN_SUPPORT),
    )
    builder.row(
        KeyboardButton(
            text=BTN_MINIAPP,
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def back_inline_kb(callback: str = "menu_main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data=callback)
    return b.as_markup()


# ============================================================
# ===             СТИЛЬНЫЕ ТЕКСТОВЫЕ ШАБЛОНЫ             ===
# ============================================================

CLUB_HEADER = "<b>TOKENS | PRIVATE CLUB</b>"
CLUB_FOOTER = "— <i>TOKENS | PRIVATE CLUB</i>"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━"


def greeting_text(first_name: str, balance: int) -> str:
    return (
        f"`TOKENS | PRIVATE CLUB`\n"
        f"{DIVIDER}\n"
        f"Приветствую, <b>{first_name}</b>.\n"
        f"Баланс: `{fmt_num(balance)}` TOKENS.\n"
        f"{DIVIDER}"
    )


# ============================================================
# ===                    /start                          ===
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user is None:
        return
    u = message.from_user
    user = await ensure_user(u.id, u.username, u.first_name or "Игрок")

    if user["banned"]:
        await message.answer(
            f"{CLUB_HEADER}\n\n"
            f"🚫 Ваш доступ ограничен.\n"
            f"Причина: <i>{user.get('ban_reason') or 'не указана'}</i>",
            reply_markup=None,
        )
        return

    await message.answer(
        greeting_text(user["first_name"] or "Игрок", int(user["balance"])),
        reply_markup=main_reply_kb(),
    )


# ============================================================
# ===             ИНЛАЙН-ГЛАВНОЕ МЕНЮ (fallback)         ===
# ============================================================

@router.callback_query(F.data == "menu_main")
async def cb_menu_main(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await ensure_user(cb.from_user.id, cb.from_user.username,
                             cb.from_user.first_name or "Игрок")
    text = greeting_text(user["first_name"] or "Игрок", int(user["balance"]))
    b = InlineKeyboardBuilder()
    b.button(text="🎮 Игры", callback_data="m:games")
    b.button(text="🎁 Бонус", callback_data="m:bonus")
    b.button(text="💎 Донат", callback_data="m:donate")
    b.button(text="👤 Профиль", callback_data="m:profile")
    b.button(text="🛡 Клан", callback_data="m:clan")
    b.button(text="🏆 Топ", callback_data="m:top")
    b.button(text="💬 Чаты", callback_data="m:chats")
    b.button(text="🆘 Поддержка", callback_data="m:support")
    b.adjust(3, 3, 2)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===             РАЗВОДКА REPLY-КНОПОК ПО МЕНЮ           ===
# ============================================================

@router.message(F.text == BTN_PROFILE)
async def menu_profile(message: Message):
    if message.from_user is None:
        return
    await show_profile(message, message.from_user.id)


@router.message(F.text == BTN_TOP)
async def menu_top(message: Message):
    await show_top(message)


@router.message(F.text == BTN_BONUS)
async def menu_bonus(message: Message):
    if message.from_user is None:
        return
    await claim_bonus(message, message.from_user.id)


@router.message(F.text == BTN_DONATE)
async def menu_donate(message: Message):
    await show_donate(message)


@router.message(F.text == BTN_SUPPORT)
async def menu_support(message: Message):
    text = (
        f"{CLUB_HEADER}\n\n"
        f"🆘 <b>Поддержка</b>\n"
        f"{DIVIDER}\n"
        f"По всем вопросам обращайтесь к администрации клуба.\n\n"
        f"• Технические проблемы\n"
        f"• Вопросы по балансу\n"
        f"• Предложения и жалобы\n\n"
        f"{CLUB_FOOTER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✉️ Написать", url="https://t.me/username_placeholder")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup())


@router.message(F.text == BTN_CHATS)
async def menu_chats(message: Message):
    text = (
        f"{CLUB_HEADER}\n\n"
        f"💬 <b>Чаты клуба</b>\n"
        f"{DIVIDER}\n"
        f"Присоединяйтесь к общению участников клуба.\n\n"
        f"{CLUB_FOOTER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="💬 Основной чат", url="https://t.me/chat_placeholder")
    b.button(text="📢 Канал новостей", url="https://t.me/channel_placeholder")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup())


@router.message(F.text == BTN_CLAN)
async def menu_clan(message: Message):
    await show_clan_menu(message)


@router.message(F.text == BTN_GAMES)
async def menu_games(message: Message):
    await show_games_menu(message)


@router.message(F.text == BTN_MINIAPP)
async def menu_miniapp(message: Message):
    text = (
        f"{CLUB_HEADER}\n\n"
        f"📱 <b>Мини-Приложение</b>\n"
        f"{DIVIDER}\n"
        f"Откройте полную версию клуба в Mini App.\n\n"
        f"{CLUB_FOOTER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="📱 Открыть Mini App", web_app=WebAppInfo(url=WEBAPP_URL))
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===                    ПРОФИЛЬ                         ===
# ============================================================

def _profile_text(user: Dict[str, Any], user_id: int) -> str:
    bal = int(user["balance"])
    vip_active = int(user["vip_until"]) > now_ts()
    if vip_active:
        until = datetime.fromtimestamp(user["vip_until"], tz=timezone.utc).strftime("%d.%m.%Y")
        vip_str = f"`VIP` (до `{until}`)"
    else:
        vip_str = "`BASIC`"
    reg = datetime.fromtimestamp(user["registered_at"], tz=timezone.utc).strftime("%d.%m.%Y")
    games = int(user["games_played"])
    wins = int(user["games_won"])
    wr = f"{(wins / games * 100):.1f}%" if games > 0 else "0.0%"
    return (
        f"{CLUB_HEADER}\n"
        f"{DIVIDER}\n"
        f"👤 <b>Профиль</b>\n\n"
        f"• Имя: <b>{user['first_name'] or '—'}</b>\n"
        f"• ID: `{user_id}`\n"
        f"• Статус: {vip_str}\n"
        f"• Баланс: `{fmt_num(bal)}` TOKENS\n"
        f"• Игр: `{fmt_num(games)}`\n"
        f"• Побед: `{fmt_num(wins)}`\n"
        f"• Винрейт: `{wr}`\n"
        f"• Дата регистрации: `{reg}`\n"
        f"{DIVIDER}"
    )


def _profile_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚙️ Настройки", callback_data="p:settings")
    b.button(text="📜 История", callback_data="p:history")
    b.button(text="💎 VIP", callback_data="p:vip")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(3, 1)
    return b.as_markup()


async def show_profile(message: Message, user_id: int):
    user = await get_user(user_id)
    if not user:
        await message.answer("Профиль не найден. /start")
        return
    await message.answer(_profile_text(user, user_id), reply_markup=_profile_kb())


@router.callback_query(F.data == "m:profile")
async def cb_profile(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        await cb.message.answer("Профиль не найден. /start")
        return
    text = _profile_text(user, cb.from_user.id)
    try:
        await cb.message.edit_text(text, reply_markup=_profile_kb())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_profile_kb())


# ============================================================
# ===              ПРОФИЛЬ — НАСТРОЙКИ                   ===
# ============================================================

@router.callback_query(F.data == "p:settings")
async def cb_settings(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        return

    lang = "Русский" if user["language"] == "ru" else "English"
    hide = "✅ Вкл" if user["hidden_balance"] else "❌ Выкл"
    no_trans = "🚫 Запрещены" if user["no_transfers"] else "✅ Разрешены"

    text = (
        f"{CLUB_HEADER}\n"
        f"{DIVIDER}\n"
        f"⚙️ <b>Настройки профиля</b>\n\n"
        f"• Язык: `{lang}`\n"
        f"• Скрыть баланс: `{hide}`\n"
        f"• Переводы: `{no_trans}`\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Язык", callback_data="p:set:lang")
    b.button(text="👁 Скрыть баланс", callback_data="p:set:hide")
    b.button(text="💸 Запрет переводов", callback_data="p:set:notx")
    b.button(text="◀️ Назад", callback_data="m:profile")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "p:set:lang")
async def cb_set_lang(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        return
    new_lang = "en" if user["language"] == "ru" else "ru"
    await db.execute("UPDATE users SET language = ? WHERE user_id = ?",
                     (new_lang, cb.from_user.id))
    _user_cache.pop(cb.from_user.id, None)
    await cb_settings(cb)


@router.callback_query(F.data == "p:set:hide")
async def cb_set_hide(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        return
    new_val = 0 if user["hidden_balance"] else 1
    await db.execute("UPDATE users SET hidden_balance = ? WHERE user_id = ?",
                     (new_val, cb.from_user.id))
    _user_cache.pop(cb.from_user.id, None)
    await cb_settings(cb)


@router.callback_query(F.data == "p:set:notx")
async def cb_set_notx(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        return
    new_val = 0 if user["no_transfers"] else 1
    await db.execute("UPDATE users SET no_transfers = ? WHERE user_id = ?",
                     (new_val, cb.from_user.id))
    _user_cache.pop(cb.from_user.id, None)
    await cb_settings(cb)


# ============================================================
# ===              ПРОФИЛЬ — ИСТОРИЯ                     ===
# ============================================================

@router.callback_query(F.data == "p:history")
async def cb_history(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    rows = await db.fetchall(
        "SELECT game_type, bet, win, created_at FROM game_log "
        "WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (cb.from_user.id,),
    )
    if not rows:
        text = (
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"📜 <b>История игр</b>\n\n"
            f"Пока нет записей.\n{DIVIDER}"
        )
    else:
        lines = [f"{CLUB_HEADER}\n{DIVIDER}\n📜 <b>Последние 10 игр</b>\n"]
        for r in rows:
            dt = datetime.fromtimestamp(r["created_at"], tz=timezone.utc).strftime("%d.%m %H:%M")
            sign = "➕" if r["win"] > 0 else "➖"
            lines.append(
                f"• `{dt}` | {r['game_type']} | ставка `{fmt_num(r['bet'])}` | "
                f"{sign} `{fmt_num(r['win'])}`"
            )
        lines.append(DIVIDER)
        text = "\n".join(lines)
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="m:profile")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===              ПРОФИЛЬ — VIP                        ===
# ===        VIP: 5 ⭐ за 1 день (Stars), без TOKENS     ===
# ============================================================

VIP_STARS_PER_DAY = 5
VIP_DAY_SECONDS = 24 * 60 * 60


def _vip_text(user: Dict[str, Any]) -> str:
    if int(user["vip_until"]) > now_ts():
        until = datetime.fromtimestamp(user["vip_until"], tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
        status = f"Активен до `{until}`"
    else:
        status = "Не активен"
    return (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"💎 <b>VIP-статус</b>\n\n"
        f"• Цена: `{VIP_STARS_PER_DAY}` ⭐ за `1` день\n"
        f"• Ваш статус: {status}\n\n"
        f"Преимущества:\n"
        f"• Повышенный лимит ставок\n"
        f"• Приоритетная поддержка\n"
        f"• Особый статус в клубе\n"
        f"{DIVIDER}"
    )


def _vip_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"💎 Купить 1 день за {VIP_STARS_PER_DAY} ⭐", callback_data="p:vip:buy")
    b.button(text="◀️ Назад", callback_data="m:profile")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "p:vip")
async def cb_vip_info(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user:
        return
    text = _vip_text(user)
    try:
        await cb.message.edit_text(text, reply_markup=_vip_kb())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_vip_kb())


@router.callback_query(F.data == "p:vip:buy")
async def cb_vip_buy(cb: CallbackQuery):
    """Invoice в Stars: 5 ⭐ за 1 день VIP."""
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or cb.message is None:
        return
    try:
        await cb.message.answer_invoice(
            title="VIP | 1 день",
            description="Премиум-статус в клубе TOKENS на 24 часа",
            payload=f"vipday:{cb.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label="VIP 1 день", amount=VIP_STARS_PER_DAY)],
            provider_token="",
        )
    except Exception as e:
        log.exception("Ошибка инвойса VIP: %s", e)
        try:
            await cb.answer("Ошибка создания платежа", show_alert=True)
        except Exception:
            pass


# ============================================================
# ===                    БОНУС                           ===
# ============================================================

async def claim_bonus(message: Message, user_id: int):
    user = await get_user(user_id, use_cache=False)
    if not user:
        await message.answer("Профиль не найден. /start")
        return
    if user["banned"]:
        await message.answer("🚫 Доступ ограничен.")
        return
    now = now_ts()
    last = int(user.get("last_bonus") or 0)
    if now - last < BONUS_COOLDOWN:
        left = BONUS_COOLDOWN - (now - last)
        hh = left // 3600
        mm = (left % 3600) // 60
        await message.answer(
            f"{CLUB_HEADER}\n\n"
            f"🎁 <b>Бонус</b>\n"
            f"{DIVIDER}\n"
            f"Следующий бонус доступен через `{hh:02d}:{mm:02d}`.\n"
            f"{DIVIDER}",
            reply_markup=back_inline_kb(),
        )
        return
    await change_balance(user_id, BONUS_AMOUNT, tx_type="bonus", description="Ежедневный бонус")
    await db.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now, user_id))
    _user_cache.pop(user_id, None)
    await message.answer(
        f"{CLUB_HEADER}\n\n"
        f"🎁 <b>Бонус получен</b>\n"
        f"{DIVIDER}\n"
        f"Вам начислено: `{fmt_num(BONUS_AMOUNT)}` TOKENS.\n"
        f"Возвращайтесь через 24 часа.\n"
        f"{DIVIDER}",
        reply_markup=main_reply_kb(),
    )


@router.callback_query(F.data == "m:bonus")
async def cb_bonus(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or cb.message is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user:
        return
    now = now_ts()
    last = int(user.get("last_bonus") or 0)
    if now - last < BONUS_COOLDOWN:
        left = BONUS_COOLDOWN - (now - last)
        hh = left // 3600
        mm = (left % 3600) // 60
        text = (
            f"{CLUB_HEADER}\n\n"
            f"🎁 <b>Бонус</b>\n{DIVIDER}\n"
            f"Следующий бонус доступен через `{hh:02d}:{mm:02d}`.\n{DIVIDER}"
        )
        b = back_inline_kb()
    else:
        text = (
            f"{CLUB_HEADER}\n\n"
            f"🎁 <b>Ежедневный бонус</b>\n{DIVIDER}\n"
            f"Доступно начисление: `{fmt_num(BONUS_AMOUNT)}` TOKENS.\n"
            f"Нажмите кнопку ниже, чтобы забрать.\n{DIVIDER}"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="🎁 Забрать бонус", callback_data="m:bonus:claim")
        kb.button(text="◀️ Назад", callback_data="menu_main")
        kb.adjust(1)
        b = kb.as_markup()
    try:
        await cb.message.edit_text(text, reply_markup=b)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b)


@router.callback_query(F.data == "m:bonus:claim")
async def cb_bonus_claim(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or cb.message is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user:
        return
    now = now_ts()
    last = int(user.get("last_bonus") or 0)
    if now - last < BONUS_COOLDOWN:
        try:
            await cb.answer("Бонус ещё недоступен.", show_alert=True)
        except Exception:
            pass
        return
    await change_balance(cb.from_user.id, BONUS_AMOUNT, tx_type="bonus",
                         description="Ежедневный бонус")
    await db.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?",
                     (now, cb.from_user.id))
    _user_cache.pop(cb.from_user.id, None)
    text = (
        f"{CLUB_HEADER}\n\n"
        f"🎁 <b>Бонус получен</b>\n{DIVIDER}\n"
        f"Начислено: `{fmt_num(BONUS_AMOUNT)}` TOKENS.\n"
        f"Возвращайтесь через 24 часа.\n{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===                    ТОП                            ===
# ============================================================

def _top_text(rows: List[aiosqlite.Row]) -> str:
    lines = [f"{CLUB_HEADER}\n{DIVIDER}\n🏆 <b>Топ-10 по балансу</b>\n"]
    if not rows:
        lines.append("Топ пока пуст.")
    else:
        medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
        for i, r in enumerate(rows):
            vip_mark = " 💎" if r["vip_until"] > now_ts() else ""
            name = (r["first_name"] or "—")[:20]
            lines.append(f"{medals[i]} <b>{name}</b>{vip_mark} — `{fmt_num(r['balance'])}`")
    lines.append(DIVIDER)
    return "\n".join(lines)


async def show_top(message: Message):
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance, vip_until FROM users "
        "WHERE banned = 0 ORDER BY balance DESC LIMIT 10"
    )
    await message.answer(_top_text(rows))


@router.callback_query(F.data == "m:top")
async def cb_top(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance, vip_until FROM users "
        "WHERE banned = 0 ORDER BY balance DESC LIMIT 10"
    )
    text = _top_text(rows)
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===                    ДОНАТ                          ===
# ===   Курс: 1 ⭐ = 7500 TOKENS, минимум 1 ⭐          ===
# ===   + Кнопка "Своя сумма" (FSM ввод Stars)          ===
# ============================================================

# Курс пополнения
STARS_TO_TOKENS = 7500
# Минимальная сумма — 1 звезда
MIN_CUSTOM_STARS = 1
MAX_CUSTOM_STARS = 10000

# Фиксированные пакеты (считаются от курса)
DONATE_OPTIONS = [
    (50, 5000),
    (100, 11000),
    (250, 30000),
    (500, 65000),
]


def _donate_packages() -> List[Tuple[int, int]]:
    """Возвращает список (stars, tokens) по актуальному курсу."""
    # Фиксированные пакеты оставляем «бонусными», но >= stars*rate быть не обязано —
    # считаем по курсу и даём приятные округлённые значения.
    return [(stars, stars * STARS_TO_TOKENS) for stars, _ in DONATE_OPTIONS]


class DonateStates(StatesGroup):
    waiting_custom_amount = State()


def _donate_text() -> str:
    lines = [
        f"{CLUB_HEADER}",
        DIVIDER,
        "💎 <b>Пополнение TOKENS</b>",
        "",
        f"Курс: `1` ⭐ = `{fmt_num(STARS_TO_TOKENS)}` TOKENS",
        f"Минимум: `{fmt_num(MIN_CUSTOM_STARS)}` ⭐",
        "",
        "Выберите пакет или введите свою сумму:",
    ]
    for stars, tokens in _donate_packages():
        lines.append(f"• {stars} ⭐ → `{fmt_num(tokens)}` TOKENS")
    lines.extend([
        "",
        f"💎 <b>VIP</b> — `{VIP_STARS_PER_DAY}` ⭐ за `1` день",
        DIVIDER,
    ])
    return "\n".join(lines)


def _donate_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for stars, _ in DONATE_OPTIONS:
        b.button(text=f"{stars} ⭐", callback_data=f"don:{stars}")
    b.button(text="✏️ Своя сумма", callback_data="don:custom")
    b.button(text=f"💎 VIP за {VIP_STARS_PER_DAY} ⭐ / 1 день", callback_data="p:vip")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(2, 2, 1, 1, 1)
    return b.as_markup()


async def show_donate(message: Message):
    await message.answer(_donate_text(), reply_markup=_donate_kb())


@router.callback_query(F.data == "m:donate")
async def cb_donate(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    try:
        await cb.message.edit_text(_donate_text(), reply_markup=_donate_kb())
    except TelegramBadRequest:
        await cb.message.answer(_donate_text(), reply_markup=_donate_kb())


# -------- Своя сумма --------

@router.callback_query(F.data == "don:custom")
async def cb_donate_custom(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or cb.message is None:
        return
    await state.set_state(DonateStates.waiting_custom_amount)
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"✏️ <b>Своя сумма</b>\n\n"
        f"Введите количество Telegram Stars (⭐).\n"
        f"• Минимум: `{fmt_num(MIN_CUSTOM_STARS)}` ⭐\n"
        f"• Максимум: `{fmt_num(MAX_CUSTOM_STARS)}` ⭐\n"
        f"• Курс: `1` ⭐ = `{fmt_num(STARS_TO_TOKENS)}` TOKENS\n\n"
        f"Отправьте число в чат или /cancel для отмены.\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✖️ Отмена", callback_data="don:cancel")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.message(DonateStates.waiting_custom_amount, Command("cancel"))
async def msg_custom_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_reply_kb())


@router.message(DonateStates.waiting_custom_amount, F.text)
async def msg_custom_amount(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    raw = (message.text or "").strip().replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await message.answer("⚠️ Введите целое число Stars.")
        return
    stars = int(raw)
    if stars < MIN_CUSTOM_STARS:
        await message.answer(f"⚠️ Минимум `{fmt_num(MIN_CUSTOM_STARS)}` ⭐.")
        return
    if stars > MAX_CUSTOM_STARS:
        await message.answer(f"⚠️ Максимум `{fmt_num(MAX_CUSTOM_STARS)}` ⭐.")
        return
    await state.clear()
    tokens_amount = stars * STARS_TO_TOKENS
    try:
        await message.answer_invoice(
            title=f"{fmt_num(tokens_amount)} TOKENS",
            description=f"Пополнение на {fmt_num(tokens_amount)} TOKENS за {stars} ⭐",
            payload=f"donate:{stars}:{tokens_amount}:{message.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)],
            provider_token="",
        )
    except Exception as e:
        log.exception("Ошибка инвойса custom: %s", e)
        await message.answer("Ошибка создания платежа. Попробуйте позже.")


@router.callback_query(F.data == "don:cancel")
async def cb_donate_cancel(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()
    except Exception:
        pass
    await state.clear()
    try:
        await cb.message.edit_text(_donate_text(), reply_markup=_donate_kb())
    except TelegramBadRequest:
        await cb.message.answer(_donate_text(), reply_markup=_donate_kb())


# -------- Фиксированные пакеты --------

@router.callback_query(F.data.startswith("don:"))
async def cb_donate_pay(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or cb.message is None:
        return
    parts = cb.data.split(":")
    if len(parts) < 2:
        return
    # Игнорируем служебные кнопки
    if parts[1] in ("custom", "cancel"):
        return
    try:
        stars = int(parts[1])
    except ValueError:
        return
    if stars < MIN_CUSTOM_STARS:
        try:
            await cb.answer(f"Минимум {MIN_CUSTOM_STARS} ⭐", show_alert=True)
        except Exception:
            pass
        return
    tokens_amount = stars * STARS_TO_TOKENS
    if tokens_amount <= 0:
        return
    try:
        await cb.message.answer_invoice(
            title=f"{fmt_num(tokens_amount)} TOKENS",
            description=f"Пакет {fmt_num(tokens_amount)} TOKENS за {stars} Telegram Stars",
            payload=f"donate:{stars}:{tokens_amount}:{cb.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)],
            provider_token="",
        )
    except Exception as e:
        log.exception("Ошибка инвойса: %s", e)
        try:
            await cb.answer("Ошибка создания платежа", show_alert=True)
        except Exception:
            pass


# ============================================================
# ===     ОБРАБОТКА ПЛАТЕЖЕЙ (Stars: донат + VIP день)   ===
# ============================================================

@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    try:
        await pcq.answer(ok=True)
    except Exception:
        pass


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    if message.from_user is None or message.successful_payment is None:
        return
    payload = message.successful_payment.invoice_payload
    parts = payload.split(":")
    head = parts[0] if parts else ""

    # --- VIP за 1 день ---
    if head == "vipday":
        user = await get_user(message.from_user.id, use_cache=False)
        base = max(now_ts(), int(user["vip_until"]) if user else 0)
        new_until = base + VIP_DAY_SECONDS
        await db.execute("UPDATE users SET vip_until = ? WHERE user_id = ?",
                         (new_until, message.from_user.id))
        _user_cache.pop(message.from_user.id, None)
        await log_admin(0, "vip_day_purchase", message.from_user.id,
                        f"{VIP_STARS_PER_DAY}⭐")
        until_str = datetime.fromtimestamp(new_until, tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"{CLUB_HEADER}\n\n"
            f"💎 <b>VIP активирован</b>\n"
            f"{DIVIDER}\n"
            f"Статус: `VIP`\n"
            f"Действует до: `{until_str}`\n"
            f"{DIVIDER}",
            reply_markup=main_reply_kb(),
        )
        return

    # --- Донат TOKENS (пакет или своя сумма) ---
    if head == "donate" and len(parts) >= 4:
        try:
            stars = int(parts[1])
            tokens_amount = int(parts[2])
        except ValueError:
            return
        await change_balance(message.from_user.id, tokens_amount, tx_type="donate",
                             description=f"Пополнение {stars}⭐")
        await log_admin(0, "donate", message.from_user.id, f"{stars}⭐ -> {tokens_amount}")
        await message.answer(
            f"{CLUB_HEADER}\n\n"
            f"💎 <b>Пополнение успешно</b>\n"
            f"{DIVIDER}\n"
            f"Оплачено: `{stars}` ⭐\n"
            f"Зачислено: `{fmt_num(tokens_amount)}` TOKENS.\n"
            f"Спасибо за поддержку клуба.\n"
            f"{DIVIDER}",
            reply_markup=main_reply_kb(),
        )
        return


# ============================================================
# ===              МЕНЮ ИГР (13 кнопок)                 ===
# ============================================================

def _games_text() -> str:
    return (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎮 <b>Игры клуба</b>\n\n"
        f"Выберите игру или ознакомьтесь с правилами.\n"
        f"Ставки: от `{fmt_num(MIN_BET)}` до `{fmt_num(MAX_BET)}` TOKENS.\n"
        f"{DIVIDER}"
    )


def _games_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎲 Кости", callback_data="g:dice")
    b.button(text="🎯 Дартс", callback_data="g:darts")
    b.button(text="🏀 Баскет", callback_data="g:basket")
    b.button(text="⚽ Футбол", callback_data="g:football")
    b.button(text="🎳 Боулинг", callback_data="g:bowling")
    b.button(text="🃏 БЖ", callback_data="g:bj")
    b.button(text="🎰 Слоты", callback_data="g:slots")
    b.button(text="💣 Мины", callback_data="g:mines")
    b.button(text="⚔️ Дуэли", callback_data="g:duels")
    b.button(text="🎡 Рулетка", callback_data="g:roulette")
    b.button(text="🎁 Бонусы", callback_data="m:bonus")
    b.button(text="📋 Все команды", callback_data="g:commands")
    b.button(text="❓ Что такое TOKENS?", callback_data="g:about")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(3, 3, 3, 1, 1, 1, 1)
    return b.as_markup()


async def show_games_menu(message: Message):
    await message.answer(_games_text(), reply_markup=_games_kb())


@router.callback_query(F.data == "m:games")
async def cb_games(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    try:
        await cb.message.edit_text(_games_text(), reply_markup=_games_kb())
    except TelegramBadRequest:
        await cb.message.answer(_games_text(), reply_markup=_games_kb())


@router.callback_query(F.data == "g:commands")
async def cb_commands(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"📋 <b>Игровые команды</b>\n\n"
        f"• `кости 1000` — игра в кости\n"
        f"• `дартс 1000` — дартс\n"
        f"• `баскет 1000` — баскетбол\n"
        f"• `футбол 1000` — футбол\n"
        f"• `боулинг 1000` — боулинг\n"
        f"• `бж 1000` — блэкджек\n"
        f"• `слоты 1000` — слоты\n"
        f"• `мины 1000` — мины (5x5, 3 мины)\n"
        f"• `дуэль @user 1000` — дуэль\n"
        f"• `старт 1000` — рулетка (запуск)\n\n"
        f"<b>Рулетка — ставки:</b>\n"
        f"• `к 1000` / `ч 500` — красное/чёрное\n"
        f"• `1000 чет` / `1000 нечет`\n"
        f"• `0 100` — на зеро\n"
        f"• `1000 1 2 3` — на числа\n"
        f"• `500 10-20` — на диапазон\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="m:games")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "g:about")
async def cb_about(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"❓ <b>Что такое TOKENS?</b>\n\n"
        f"TOKENS — внутренняя валюта игрового клуба.\n\n"
        f"• Начисляются за ежедневный бонус\n"
        f"• Покупаются за Telegram Stars\n"
        f"• Используются в играх клуба\n"
        f"• Накапливаются в профиле\n\n"
        f"<i>TOKENS не являются денежными средствами и не подлежат выводу.</i>\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="m:games")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


# ============================================================
# ===                    КЛАН (меню)                     ===
# ============================================================

def _clan_menu_text() -> str:
    return (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🛡 <b>Кланы</b>\n\n"
        f"Объединяйтесь в кланы, соревнуйтесь и развивайтесь вместе.\n"
        f"{DIVIDER}"
    )


def _clan_menu_kb(user: Optional[Dict[str, Any]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if user and user.get("clan_id"):
        b.button(text="🛡 Мой клан", callback_data="clan:my")
    b.button(text="➕ Создать клан", callback_data="clan:create")
    b.button(text="📋 Список кланов", callback_data="clan:list")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    return b.as_markup()


async def show_clan_menu(message: Message):
    if message.from_user is None:
        return
    user = await get_user(message.from_user.id)
    await message.answer(_clan_menu_text(), reply_markup=_clan_menu_kb(user))


@router.callback_query(F.data == "m:clan")
async def cb_clan(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    try:
        await cb.message.edit_text(_clan_menu_text(), reply_markup=_clan_menu_kb(user))
    except TelegramBadRequest:
        await cb.message.answer(_clan_menu_text(), reply_markup=_clan_menu_kb(user))


# ============================================================
# ===             ОБЩИЕ CALLBACK ДЛЯ ЧАТОВ/ПОДДЕРЖКИ      ===
# ============================================================

@router.callback_query(F.data == "m:support")
async def cb_support(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    text = (
        f"{CLUB_HEADER}\n\n"
        f"🆘 <b>Поддержка</b>\n"
        f"{DIVIDER}\n"
        f"По всем вопросам обращайтесь к администрации клуба.\n\n"
        f"• Технические проблемы\n"
        f"• Вопросы по балансу\n"
        f"• Предложения и жалобы\n\n"
        f"{CLUB_FOOTER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✉️ Написать", url="https://t.me/username_placeholder")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "m:chats")
async def cb_chats(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    text = (
        f"{CLUB_HEADER}\n\n"
        f"💬 <b>Чаты клуба</b>\n"
        f"{DIVIDER}\n"
        f"Присоединяйтесь к общению участников клуба.\n\n"
        f"{CLUB_FOOTER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="💬 Основной чат", url="https://t.me/chat_placeholder")
    b.button(text="📢 Канал новостей", url="https://t.me/channel_placeholder")
    b.button(text="◀️ Назад", callback_data="menu_main")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())

# ============================================================
# ===              ИГРЫ: ОБЩИЕ УТИЛИТЫ                    ===
# ============================================================

# Эмодзи для стикерных игр
DICE_EMOJI = {
    "dice": "🎲",
    "darts": "🎯",
    "basket": "🏀",
    "football": "⚽",
    "bowling": "🎳",
    "slots": "🎰",
}

# Названия игр для сообщений
GAME_NAMES = {
    "dice": "Кости",
    "darts": "Дартс",
    "basket": "Баскет",
    "football": "Футбол",
    "bowling": "Боулинг",
    "slots": "Слоты",
    "bj": "Блэкджек",
    "mines": "Мины",
}


def parse_bet(text: str) -> Optional[int]:
    """Распарсить сумму ставки из текста. Поддерживает '1k', '1к', '1000'."""
    if not text:
        return None
    t = text.strip().lower().replace(" ", "").replace(",", "")
    mult = 1
    if t.endswith("k") or t.endswith("к"):
        mult = 1000
        t = t[:-1]
    if not t.isdigit():
        return None
    try:
        return int(t) * mult
    except ValueError:
        return None


async def safe_delete(message: Message, delay: float):
    """Удалить сообщение через delay секунд (без падений)."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def send_temp(chat_id: int, text: str, delay: int = AUTO_DELETE,
                    reply_markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
    """Отправить сообщение и удалить через delay секунд."""
    try:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception:
        return None
    asyncio.create_task(safe_delete(msg, delay))
    return msg


def result_text(game: str, bet: int, win: int, detail: str = "") -> str:
    """Форматирование результата игры в премиум-стиле."""
    if win > bet:
        net = win - bet
        sign = "➕"
        verdict = "ПОБЕДА"
    elif win == bet:
        net = 0
        sign = "➖"
        verdict = "ВОЗВРАТ"
    else:
        net = bet - win
        sign = "➖"
        verdict = "ПРОИГРЫШ"
    lines = [
        f"{CLUB_HEADER}",
        DIVIDER,
        f"🎮 <b>{GAME_NAMES.get(game, game)}</b>",
        "",
        f"• Ставка: `{fmt_num(bet)}` TOKENS",
    ]
    if detail:
        lines.append(f"• {detail}")
    if win > 0 and win > bet:
        lines.append(f"• Выигрыш: `{fmt_num(win)}` TOKENS")
        lines.append(f"• {sign} Чистыми: `{fmt_num(net)}` TOKENS")
    elif win == bet:
        lines.append(f"• Возврат: `{fmt_num(bet)}` TOKENS")
    else:
        lines.append(f"• {sign} Потеря: `{fmt_num(net)}` TOKENS")
    lines.append("")
    lines.append(f"Результат: <b>{verdict}</b>")
    lines.append(DIVIDER)
    return "\n".join(lines)


def render_bar(value: int, max_value: int, size: int = 10) -> str:
    """Полоса прогресса ▰▱."""
    if max_value <= 0:
        return "▱" * size
    filled = int(round(size * value / max_value))
    filled = max(0, min(size, filled))
    return "▰" * filled + "▱" * (size - filled)


# ============================================================
# ===          СТИКЕРНЫЕ ИГРЫ (dice-подобные)           ===
# ============================================================

async def play_dice_game(message: Message, game: str, bet: int):
    """Универсальная стикерная игра (reply_dice / emoji)."""
    if message.from_user is None:
        return
    uid = message.from_user.id

    # Проверка и списание ставки
    ok, err, user = await check_and_subtract_bet(uid, bet)
    if not ok:
        await send_temp(message.chat.id, err, delay=8)
        return

    emoji = DICE_EMOJI.get(game, "🎲")
    # Отправляем индикатор
    try:
        placeholder = await message.answer(
            f"🎮 <b>{GAME_NAMES.get(game, game)}</b>\n"
            f"{DIVIDER}\n"
            f"Бросок... ставка `{fmt_num(bet)}` TOKENS.",
        )
    except Exception:
        placeholder = None

    # Отправляем "кости" от лица бота
    try:
        dice_msg: Dice = await bot.send_dice(message.chat.id, emoji=emoji)
    except Exception as e:
        log.exception("send_dice error: %s", e)
        # Возврат ставки
        await change_balance(uid, bet, tx_type="refund", description="Возврат ставки")
        if placeholder:
            try:
                await placeholder.edit_text("⚠️ Ошибка игры. Ставка возвращена.")
            except Exception:
                pass
        return

    await asyncio.sleep(DICE_TIMEOUT)
    value = dice_msg.dice.value if dice_msg.dice else 0

    # Логика выигрыша
    win = 0
    detail = f"Значение: `{value}`"

    if game == "dice":
        # 1..6, >3 — победа x2
        if value > 3:
            win = bet * 2
            detail += " (> 3)"
    elif game == "darts":
        # 1..6, >=4 — победа x2
        if value >= 4:
            win = bet * 2
            detail += " (>= 4)"
    elif game == "basket":
        # 1..5, >3 — победа x2
        if value > 3:
            win = bet * 2
            detail += " (> 3)"
    elif game == "football":
        # 1..5, >3 — победа x2
        if value > 3:
            win = bet * 2
            detail += " (> 3)"
    elif game == "bowling":
        # 1..6, >=5 — победа x2
        if value >= 5:
            win = bet * 2
            detail += " (>= 5)"
    elif game == "slots":
        # 1..64 — джекпот на 64, парные — меньше
        # Упрощённо: value>=43 — победа x2, 64 — x5
        if value == 64:
            win = bet * 5
            detail += " (ДЖЕКПОТ x5)"
        elif value >= 43:
            win = bet * 2
            detail += " (>= 43)"

    if win > 0:
        await change_balance(uid, win, tx_type="win", description=f"Выигрыш {game}")

    await log_game(uid, game, bet, win, f"value={value}")

    text = result_text(game, bet, win, detail)
    if placeholder:
        try:
            await placeholder.edit_text(text)
        except Exception:
            pass
        asyncio.create_task(safe_delete(placeholder, AUTO_DELETE))
    else:
        await send_temp(message.chat.id, text, delay=AUTO_DELETE)


# ---- Хендлеры команд стикерных игр ----

@router.message(F.text.regexp(r"^(кости|кубик|кубики)\s+", flags=0) if hasattr(F.text, "regexp") else F.text.startswith("кости"))
async def cmd_dice(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `кости 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "dice", bet)


@router.message(F.text.startswith("дартс"))
async def cmd_darts(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `дартс 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "darts", bet)


@router.message(F.text.startswith("баскет"))
async def cmd_basket(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `баскет 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "basket", bet)


@router.message(F.text.startswith("футбол"))
async def cmd_football(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `футбол 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "football", bet)


@router.message(F.text.startswith("боулинг"))
async def cmd_bowling(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `боулинг 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "bowling", bet)


@router.message(F.text.startswith("слоты"))
async def cmd_slots(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `слоты 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await play_dice_game(message, "slots", bet)


# ============================================================
# ===              БЛЭКДЖЕК (БЖ)                         ===
# ============================================================

# Состояние БЖ: {user_id: {...}}
_active_bj: Dict[int, Dict[str, Any]] = {}

# Колода: значения от 2 до 11 (11 = туз, при переборе → 1)
BJ_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
BJ_SUITS = ["♠", "♥", "♦", "♣"]


def _bj_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def _bj_hand_value(hand: List[str]) -> int:
    """Считает сумму карт, мягкий туз (11→1) при переборе."""
    total = sum(_bj_value(c) for c in hand)
    aces = sum(1 for c in hand if c == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _bj_draw() -> str:
    return random.choice(BJ_RANKS)


def _bj_format_cards(cards: List[str]) -> str:
    return " ".join(f"`{c}`" for c in cards)


async def start_bj(message: Message, bet: int):
    if message.from_user is None:
        return
    uid = message.from_user.id
    if uid in _active_bj:
        await send_temp(message.chat.id, "⚠️ У Вас уже активна игра в БЖ. Завершите её.", delay=8)
        return

    ok, err, user = await check_and_subtract_bet(uid, bet)
    if not ok:
        await send_temp(message.chat.id, err, delay=8)
        return

    player = [_bj_draw(), _bj_draw()]
    dealer = [_bj_draw(), _bj_draw()]
    _active_bj[uid] = {
        "bet": bet,
        "player": player,
        "dealer": dealer,
        "message_id": None,
        "chat_id": message.chat.id,
        "started": time.time(),
    }

    await _bj_send_state(message.chat.id, uid)


async def _bj_send_state(chat_id: int, uid: int, edit_message_id: Optional[int] = None):
    state = _active_bj.get(uid)
    if not state:
        return
    player_val = _bj_hand_value(state["player"])
    dealer_shown = state["dealer"][:1]
    dealer_val = _bj_value(state["dealer"][0])

    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🃏 <b>Блэкджек</b>\n\n"
        f"• Ставка: `{fmt_num(state['bet'])}` TOKENS\n\n"
        f"👤 Ваши карты: {_bj_format_cards(state['player'])} (сумма: `{player_val}`)\n"
        f"🎩 Дилер: {_bj_format_cards(dealer_shown)} + `?` (открыто: `{dealer_val}`)\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="➕ Взять", callback_data=f"bj:hit:{uid}")
    b.button(text="✋ Стоп", callback_data=f"bj:stand:{uid}")
    b.adjust(2)
    kb = b.as_markup()

    if edit_message_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=edit_message_id,
                                        text=text, reply_markup=kb)
            return
        except Exception:
            pass
    try:
        msg = await bot.send_message(chat_id, text, reply_markup=kb)
        state["message_id"] = msg.message_id
    except Exception as e:
        log.exception("BJ send error: %s", e)


@router.callback_query(F.data.startswith("bj:hit:"))
async def cb_bj_hit(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    try:
        target_uid = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        return
    if target_uid != cb.from_user.id:
        try:
            await cb.answer("Это не Ваша игра.", show_alert=True)
        except Exception:
            pass
        return
    state = _active_bj.get(target_uid)
    if not state:
        try:
            await cb.answer("Игра завершена.", show_alert=True)
        except Exception:
            pass
        return

    state["player"].append(_bj_draw())
    pv = _bj_hand_value(state["player"])

    if pv > 21:
        # Перебор — поражение
        await _bj_finish(target_uid, cb.message.chat.id, cb.message.message_id, bust=True)
        return
    if pv == 21:
        # Автостоп
        await _bj_finish(target_uid, cb.message.chat.id, cb.message.message_id)
        return

    # Обновляем
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🃏 <b>Блэкджек</b>\n\n"
        f"• Ставка: `{fmt_num(state['bet'])}` TOKENS\n\n"
        f"👤 Ваши карты: {_bj_format_cards(state['player'])} (сумма: `{pv}`)\n"
        f"🎩 Дилер: {_bj_format_cards(state['dealer'][:1])} + `?`\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="➕ Взять", callback_data=f"bj:hit:{target_uid}")
    b.button(text="✋ Стоп", callback_data=f"bj:stand:{target_uid}")
    b.adjust(2)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("bj:stand:"))
async def cb_bj_stand(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    try:
        target_uid = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        return
    if target_uid != cb.from_user.id:
        try:
            await cb.answer("Это не Ваша игра.", show_alert=True)
        except Exception:
            pass
        return
    await _bj_finish(target_uid, cb.message.chat.id, cb.message.message_id)


async def _bj_finish(uid: int, chat_id: int, message_id: Optional[int], bust: bool = False):
    state = _active_bj.pop(uid, None)
    if not state:
        return
    bet = state["bet"]
    player = state["player"]
    dealer = state["dealer"]

    pv = _bj_hand_value(player)
    dv = _bj_hand_value(dealer)

    # Если не перебор игрока — дилер добирает до 17
    if not bust:
        while dv < 17:
            dealer.append(_bj_draw())
            dv = _bj_hand_value(dealer)

    win = 0
    detail = ""

    if bust or pv > 21:
        detail = f"Перебор: `{pv}`"
        win = 0
    elif dv > 21 or pv > dv:
        if pv == 21 and len(player) == 2:
            win = int(bet * 2.5)
            detail = f"BLACKJACK! `{pv}` vs `{dv}`"
        else:
            win = bet * 2
            detail = f"Победа: `{pv}` vs `{dv}`"
    elif pv == dv:
        win = bet
        detail = f"Ничья: `{pv}` vs `{dv}`"
    else:
        detail = f"Поражение: `{pv}` vs `{dv}`"

    if win > 0:
        await change_balance(uid, win, tx_type="win", description=f"БЖ выигрыш")
    await log_game(uid, "bj", bet, win, detail)

    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🃏 <b>Блэкджек — итог</b>\n\n"
        f"👤 Ваши: {_bj_format_cards(player)} (`{pv}`)\n"
        f"🎩 Дилер: {_bj_format_cards(dealer)} (`{dv}`)\n\n"
        f"• Ставка: `{fmt_num(bet)}`\n"
    )
    if win > bet:
        text += f"• Выигрыш: `{fmt_num(win)}` (чистыми `{fmt_num(win - bet)}`)\n"
    elif win == bet:
        text += f"• Возврат: `{fmt_num(bet)}`\n"
    else:
        text += f"• Потеря: `{fmt_num(bet)}`\n"
    text += f"\n{detail}\n{DIVIDER}"

    if message_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            asyncio.create_task(_delete_by_ids(chat_id, message_id, AUTO_DELETE))
            return
        except Exception:
            pass
    await send_temp(chat_id, text, delay=AUTO_DELETE)


async def _delete_by_ids(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


@router.message(F.text.startswith("бж"))
async def cmd_bj(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `бж 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await start_bj(message, bet)


# ============================================================
# ===                     МИНЫ 5x5                       ===
# ============================================================

MINES_SIZE = 5
MINES_COUNT = 3
MINES_TOTAL = MINES_SIZE * MINES_SIZE  # 25


def _mines_multiplier(opened: int) -> float:
    """Множитель выигрыша в зависимости от числа открытых клеток."""
    # Чем больше открыто — тем выше множитель
    base = 1.0
    table = {
        1: 1.10, 2: 1.25, 3: 1.45, 4: 1.70, 5: 2.00,
        6: 2.40, 7: 2.90, 8: 3.50, 9: 4.30, 10: 5.30,
        11: 6.60, 12: 8.30, 13: 10.50, 14: 13.50, 15: 17.50,
        16: 23.00, 17: 30.00, 18: 40.00, 19: 55.00, 20: 75.00,
        21: 100.00, 22: 140.00,
    }
    return table.get(opened, base)


def _mines_kb(state: Dict[str, Any]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    opened = state["opened"]
    for idx in range(MINES_TOTAL):
        if idx in state["mines"] and idx in state["clicked"]:
            b.button(text="💥", callback_data=f"mn:none:{idx}")
        elif idx in state["clicked"]:
            b.button(text="💎", callback_data=f"mn:none:{idx}")
        else:
            b.button(text="⬜", callback_data=f"mn:open:{idx}")
    # Кнопка "Забрать"
    b.button(text="💰 Забрать", callback_data="mn:take")
    b.adjust(MINES_SIZE, MINES_SIZE, MINES_SIZE, MINES_SIZE, MINES_SIZE, 1)
    return b.as_markup()


def _mines_text(state: Dict[str, Any]) -> str:
    opened = len(state["clicked"])
    mult = _mines_multiplier(opened) if opened > 0 else 1.0
    potential = int(state["bet"] * mult) if opened > 0 else 0
    return (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"💣 <b>Мины</b>\n\n"
        f"• Ставка: `{fmt_num(state['bet'])}` TOKENS\n"
        f"• Мин на поле: `{MINES_COUNT}`\n"
        f"• Открыто: `{opened}` / `{MINES_TOTAL - MINES_COUNT}`\n"
        f"• Множитель: `x{mult:.2f}`\n"
        f"• К забору: `{fmt_num(potential)}` TOKENS\n\n"
        f"Открывайте безопасные клетки 💎.\n{DIVIDER}"
    )


async def start_mines(message: Message, bet: int):
    if message.from_user is None:
        return
    uid = message.from_user.id
    if uid in _active_mines:
        await send_temp(message.chat.id, "⚠️ У Вас уже активна игра в Мины.", delay=8)
        return
    ok, err, user = await check_and_subtract_bet(uid, bet)
    if not ok:
        await send_temp(message.chat.id, err, delay=8)
        return

    mines = set(random.sample(range(MINES_TOTAL), MINES_COUNT))
    state = {
        "bet": bet,
        "mines": mines,
        "clicked": set(),
        "chat_id": message.chat.id,
        "message_id": None,
        "started": time.time(),
    }
    _active_mines[uid] = state

    try:
        msg = await message.answer(_mines_text(state), reply_markup=_mines_kb(state))
        state["message_id"] = msg.message_id
    except Exception as e:
        log.exception("mines send error: %s", e)
        _active_mines.pop(uid, None)
        await change_balance(uid, bet, tx_type="refund", description="Возврат ставки")


@router.message(F.text.startswith("мины") | F.text.startswith("мин ") | F.text.startswith("мина "))
async def cmd_mines(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id, "Использование: `мины 1000`", delay=8)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await start_mines(message, bet)


@router.callback_query(F.data.startswith("mn:"))
async def cb_mines(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    uid = cb.from_user.id
    state = _active_mines.get(uid)
    if not state:
        try:
            await cb.answer("Игра завершена.", show_alert=True)
        except Exception:
            pass
        return

    parts = cb.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "none":
        return

    if action == "take":
        # Забрать выигрыш
        opened = len(state["clicked"])
        if opened == 0:
            try:
                await cb.answer("Откройте хотя бы одну клетку.", show_alert=True)
            except Exception:
                pass
            return
        mult = _mines_multiplier(opened)
        win = int(state["bet"] * mult)
        await change_balance(uid, win, tx_type="win", description="Мины — забрал")
        await log_game(uid, "mines", state["bet"], win, f"opened={opened}")
        _active_mines.pop(uid, None)
        text = (
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"💣 <b>Мины — итог</b>\n\n"
            f"• Открыто: `{opened}`\n"
            f"• Множитель: `x{mult:.2f}`\n"
            f"• Ставка: `{fmt_num(state['bet'])}`\n"
            f"• Выигрыш: `{fmt_num(win)}`\n"
            f"{DIVIDER}"
        )
        try:
            await cb.message.edit_text(text)
        except Exception:
            await send_temp(state["chat_id"], text, delay=AUTO_DELETE)
        asyncio.create_task(_delete_by_ids(state["chat_id"], cb.message.message_id, AUTO_DELETE))
        return

    if action == "open":
        try:
            idx = int(parts[2])
        except (IndexError, ValueError):
            return
        if idx in state["clicked"]:
            return
        if idx in state["mines"]:
            # Взрыв — конец игры
            state["clicked"].add(idx)
            _active_mines.pop(uid, None)
            await log_game(uid, "mines", state["bet"], 0, f"boom={idx}")
            # Откроем все мины
            try:
                await cb.message.edit_text(
                    _mines_text(state) + "\n💥 <b>ВЗРЫВ! Ставка потеряна.</b>",
                    reply_markup=_mines_kb(state),
                )
            except Exception:
                pass
            asyncio.create_task(_delete_by_ids(state["chat_id"], cb.message.message_id, AUTO_DELETE + 3))
            return

        state["clicked"].add(idx)
        opened = len(state["clicked"])
        # Победа — все безопасные открыты
        if opened == MINES_TOTAL - MINES_COUNT:
            mult = _mines_multiplier(opened)
            win = int(state["bet"] * mult)
            await change_balance(uid, win, tx_type="win", description="Мины — все открыты")
            await log_game(uid, "mines", state["bet"], win, "perfect")
            _active_mines.pop(uid, None)
            text = (
                f"{CLUB_HEADER}\n{DIVIDER}\n"
                f"💣 <b>Мины — победа!</b>\n\n"
                f"• Открыто: `{opened}` (все безопасные)\n"
                f"• Множитель: `x{mult:.2f}`\n"
                f"• Выигрыш: `{fmt_num(win)}`\n"
                f"{DIVIDER}"
            )
            try:
                await cb.message.edit_text(text)
            except Exception:
                await send_temp(state["chat_id"], text, delay=AUTO_DELETE)
            asyncio.create_task(_delete_by_ids(state["chat_id"], cb.message.message_id, AUTO_DELETE))
            return

        # Обновляем поле
        try:
            await cb.message.edit_text(_mines_text(state), reply_markup=_mines_kb(state))
        except TelegramBadRequest:
            pass
        return


# ============================================================
# ===                    ДУЭЛИ                           ===
# ============================================================

import uuid

DUEL_EXPIRY = 120  # сек


async def start_duel(message: Message, opponent_id: int, bet: int):
    if message.from_user is None:
        return
    uid = message.from_user.id
    if uid == opponent_id:
        await send_temp(message.chat.id, "⚠️ Нельзя дуэль с самим собой.", delay=8)
        return

    ok, err, user = await check_and_subtract_bet(uid, bet)
    if not ok:
        await send_temp(message.chat.id, err, delay=8)
        return

    opp = await get_user(opponent_id, use_cache=False)
    if not opp:
        await change_balance(uid, bet, tx_type="refund", description="Дуэль: соперник не найден")
        await send_temp(message.chat.id, "⚠️ Соперник не найден в клубе.", delay=8)
        return
    if opp["banned"]:
        await change_balance(uid, bet, tx_type="refund", description="Дуэль: соперник забанен")
        await send_temp(message.chat.id, "⚠️ Соперник ограничен.", delay=8)
        return
    if int(opp["balance"]) < bet:
        await change_balance(uid, bet, tx_type="refund", description="Дуэль: недостаточно у соперника")
        await send_temp(
            message.chat.id,
            f"⚠️ У соперника недостаточно средств (`{fmt_num(opp['balance'])}`).",
            delay=8,
        )
        return

    duel_id = uuid.uuid4().hex[:10]
    _active_duels[duel_id] = {
        "challenger": uid,
        "challenger_name": user["first_name"] or "Игрок",
        "opponent": opponent_id,
        "opponent_name": opp["first_name"] or "Игрок",
        "bet": bet,
        "created": time.time(),
        "status": "pending",
    }

    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"⚔️ <b>Вызов на дуэль</b>\n\n"
        f"• От: <b>{user['first_name']}</b>\n"
        f"• Кому: <b>{opp['first_name']}</b>\n"
        f"• Ставка: `{fmt_num(bet)}` TOKENS\n\n"
        f"<i>У соперника 2 минуты на ответ.</i>\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"duel:accept:{duel_id}")
    b.button(text="❌ Отклонить", callback_data=f"duel:decline:{duel_id}")
    b.adjust(2)
    await message.answer(text, reply_markup=b.as_markup())
    # Авто-истечение
    asyncio.create_task(_duel_expire(duel_id, message.chat.id))


async def _duel_expire(duel_id: str, chat_id: int):
    await asyncio.sleep(DUEL_EXPIRY)
    d = _active_duels.pop(duel_id, None)
    if not d:
        return
    if d["status"] != "pending":
        return
    await change_balance(d["challenger"], d["bet"], tx_type="refund",
                         description="Дуэль: истекла")
    try:
        await bot.send_message(
            chat_id,
            f"⚔️ Дуэль истекла. Ставка `{fmt_num(d['bet'])}` возвращена инициатору.",
        )
    except Exception:
        pass


@router.message(F.text.startswith("дуэль") | F.text.startswith("дуель") | F.text.startswith("duel"))
async def cmd_duel(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await send_temp(message.chat.id, "Использование: `дуэль @user 1000`", delay=8)
        return

    target = parts[1]
    # Определяем opponent_id: из entities или username
    opponent_id: Optional[int] = None

    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                opponent_id = ent.user.id
                break
    if opponent_id is None and target.startswith("@"):
        uname = target.lstrip("@").lower()
        # Ищем в БД
        row = await db.fetchone(
            "SELECT user_id FROM users WHERE LOWER(username) = ?", (uname,)
        )
        if row:
            opponent_id = int(row["user_id"])
    if opponent_id is None and target.isdigit():
        opponent_id = int(target)

    if opponent_id is None:
        await send_temp(
            message.chat.id,
            "⚠️ Не удалось определить соперника. Укажите @username или ID.",
            delay=8,
        )
        return

    bet = parse_bet(parts[2])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await start_duel(message, opponent_id, bet)


@router.callback_query(F.data.startswith("duel:"))
async def cb_duel(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    parts = cb.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    duel_id = parts[2]
    d = _active_duels.get(duel_id)
    if not d:
        try:
            await cb.answer("Дуэль не найдена или уже завершена.", show_alert=True)
        except Exception:
            pass
        return
    if d["status"] != "pending":
        try:
            await cb.answer("Дуэль уже обработана.", show_alert=True)
        except Exception:
            pass
        return

    # Только соперник может отвечать
    if cb.from_user.id != d["opponent"]:
        try:
            await cb.answer("Только соперник может ответить.", show_alert=True)
        except Exception:
            pass
        return

    if action == "decline":
        _active_duels.pop(duel_id, None)
        await change_balance(d["challenger"], d["bet"], tx_type="refund",
                             description="Дуэль: отказ")
        text = (
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"⚔️ <b>Дуэль отклонена</b>\n\n"
            f"• Инициатор: <b>{d['challenger_name']}</b>\n"
            f"• Соперник: <b>{d['opponent_name']}</b>\n"
            f"• Ставка возвращена инициатору.\n"
            f"{DIVIDER}"
        )
        try:
            await cb.message.edit_text(text)
        except Exception:
            pass
        return

    if action == "accept":
        # Проверяем баланс соперника
        opp = await get_user(d["opponent"], use_cache=False)
        if not opp or int(opp["balance"]) < d["bet"]:
            _active_duels.pop(duel_id, None)
            await change_balance(d["challenger"], d["bet"], tx_type="refund",
                                 description="Дуэль: у соперника нет средств")
            try:
                await cb.answer("Недостаточно средств для дуэли.", show_alert=True)
            except Exception:
                pass
            return
        # Списываем у соперника
        ok2 = await change_balance(d["opponent"], -d["bet"], tx_type="duel_bet",
                                   description="Дуэль: ставка")
        d["status"] = "running"
        # Определяем победителя
        roll1 = random.randint(1, 100)
        roll2 = random.randint(1, 100)
        # Ничья → перебрасываем
        while roll1 == roll2:
            roll1 = random.randint(1, 100)
            roll2 = random.randint(1, 100)
        winner = d["challenger"] if roll1 > roll2 else d["opponent"]
        pot = d["bet"] * 2
        await change_balance(winner, pot, tx_type="duel_win", description="Дуэль: победа")
        await log_game(d["challenger"], "duel", d["bet"],
                       0, f"vs={d['opponent']} result={'win' if winner == d['challenger'] else 'lose'}")
        await log_game(d["opponent"], "duel", d["bet"],
                       0, f"vs={d['challenger']} result={'win' if winner == d['opponent'] else 'lose'}")
        _active_duels.pop(duel_id, None)

        winner_name = d["challenger_name"] if winner == d["challenger"] else d["opponent_name"]
        text = (
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"⚔️ <b>Дуэль завершена</b>\n\n"
            f"• {d['challenger_name']}: `{roll1}`\n"
            f"• {d['opponent_name']}: `{roll2}`\n\n"
            f"🏆 Победитель: <b>{winner_name}</b>\n"
            f"• Приз: `{fmt_num(pot)}` TOKENS\n"
            f"{DIVIDER}"
        )
        try:
            await cb.message.edit_text(text)
        except Exception:
            pass


# ============================================================
# ===              ВЫЗОВЫ ИГР ИЗ INLINE-МЕНЮ             ===
# ============================================================

@router.callback_query(F.data.startswith("g:"))
async def cb_game_select(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    game = cb.data.split(":", 1)[1] if ":" in cb.data else ""
    if game in ("commands", "about"):
        return

    hints = {
        "dice": "`кости 1000`",
        "darts": "`дартс 1000`",
        "basket": "`баскет 1000`",
        "football": "`футбол 1000`",
        "bowling": "`боулинг 1000`",
        "bj": "`бж 1000`",
        "slots": "`слоты 1000`",
        "mines": "`мины 1000`",
        "duels": "`дуэль @user 1000`",
        "roulette": "`старт 1000`",
    }
    name = GAME_NAMES.get(game, game.capitalize())
    hint = hints.get(game, "")
    if not hint:
        return

    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎮 <b>{name}</b>\n\n"
        f"Отправьте в чат команду:\n"
        f"{hint}\n\n"
        f"• Мин. ставка: `{fmt_num(MIN_BET)}`\n"
        f"• Макс. ставка: `{fmt_num(MAX_BET)}`\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="m:games")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())

# ============================================================
# ===                    РУЛЕТКА                          ===
# ============================================================

# Европейская рулетка: 0..36
ROULETTE_RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
ROULETTE_BLACK = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

# Состояние рулетки: {chat_id: {...}}
_roulette_state: Dict[int, Dict[str, Any]] = {}
ROULETTE_BETTING_TIME = 30  # секунд на приём ставок


def _roulette_color(n: int) -> str:
    if n == 0:
        return "green"
    if n in ROULETTE_RED:
        return "red"
    return "black"


def _roulette_color_ru(c: str) -> str:
    return {"red": "красное", "black": "чёрное", "green": "зеро"}.get(c, c)


def parse_roulette_bet(text: str) -> Optional[Dict[str, Any]]:
    """
    Парсит ставку рулетки. Поддерживает:
      к 1000              → красное
      ч 500               → чёрное
      1000 чет            → чёт
      1000 нечет          → нечет
      0 100 / з 100       → зеро
      1000 1 2 3          → конкретные числа
      500 10-20           → диапазон
      1000                → ставка на чёт (по умолчанию)? нет, вернём None
    """
    if not text:
        return None
    t = text.strip().lower().replace("ё", "е")

    # --- к/ч ---
    m = re.match(r"^(к|ч)\s+([\d\s,]+)$", t)
    if m:
        color = "red" if m.group(1) == "к" else "black"
        bet = parse_bet(m.group(2))
        if bet:
            return {"type": "color", "value": color, "bet": bet}
        return None

    # --- зеро: "0 100" или "з 100" ---
    m = re.match(r"^(0|з|зеро)\s+([\d\s,]+)$", t)
    if m:
        bet = parse_bet(m.group(2))
        if bet:
            return {"type": "number", "value": [0], "bet": bet}
        return None

    # --- диапазон: "500 10-20" ---
    m = re.match(r"^([\d\s,]+)\s+(\d{1,2})\s*-\s*(\d{1,2})$", t)
    if m:
        bet = parse_bet(m.group(1))
        a, b = int(m.group(2)), int(m.group(3))
        if bet and 0 <= a <= 36 and 0 <= b <= 36 and a < b:
            return {"type": "range", "value": (a, b), "bet": bet}
        return None

    # --- чет/нечет: "1000 чет" или "1000 нечет" ---
    m = re.match(r"^([\d\s,]+)\s+(чет|нечет|чёт|нечёт)$", t)
    if m:
        bet = parse_bet(m.group(1))
        if bet:
            parity = "even" if "не" not in m.group(2) else "odd"
            # ВАЖНО: "чет" = чёт, "нечет" = нечет
            if m.group(2).startswith("не"):
                parity = "odd"
            else:
                parity = "even"
            return {"type": "parity", "value": parity, "bet": bet}
        return None

    # --- числа: "1000 1 2 3" ---
    m = re.match(r"^([\d\s,]+)\s+((?:\d{1,2}\s*)+)$", t)
    if m:
        bet = parse_bet(m.group(1))
        nums_str = m.group(2).strip()
        try:
            nums = [int(x) for x in re.findall(r"\d{1,2}", nums_str)]
        except ValueError:
            return None
        if bet and nums and all(0 <= n <= 36 for n in nums):
            return {"type": "numbers", "value": nums, "bet": bet}
        return None

    return None


def _roulette_bets_summary(bets: Dict[int, Dict[str, Any]]) -> str:
    """Сводка ставок игроков в рулетке."""
    if not bets:
        return "Ставок пока нет."
    lines = []
    for uid, b in bets.items():
        name = b.get("name") or "—"
        bet = b["bet"]
        t = b["type"]
        if t == "color":
            label = "🔴 красное" if b["value"] == "red" else "⚫ чёрное"
        elif t == "parity":
            label = "чёт" if b["value"] == "even" else "нечет"
        elif t == "number":
            label = "зеро (0)"
        elif t == "numbers":
            label = "числа " + ", ".join(map(str, b["value"]))
        elif t == "range":
            a, bb = b["value"]
            label = f"диапазон {a}–{bb}"
        else:
            label = "?"
        lines.append(f"• <b>{name}</b>: `{fmt_num(bet)}` на {label}")
    return "\n".join(lines)


def _check_roulette_win(b: Dict[str, Any], number: int) -> int:
    """Возвращает сумму выигрыша (0 при проигрыше)."""
    t = b["type"]
    bet = b["bet"]
    if t == "color":
        color = _roulette_color(number)
        if (b["value"] == "red" and color == "red") or \
           (b["value"] == "black" and color == "black"):
            return bet * 2
    elif t == "parity":
        if number == 0:
            return 0
        if b["value"] == "even" and number % 2 == 0:
            return bet * 2
        if b["value"] == "odd" and number % 2 == 1:
            return bet * 2
    elif t == "number":
        if number in b["value"]:
            return bet * 36
    elif t == "numbers":
        if number in b["value"]:
            return bet * 36
    elif t == "range":
        a, bb = b["value"]
        if a <= number <= bb:
            # Множитель зависит от ширины диапазона: 36 / (bb-a+1)
            k = 36 // max(1, (bb - a + 1))
            return bet * max(2, k)
    return 0


async def _roulette_timer(chat_id: int, state_id: str):
    """Через RULETTE_BETTING_TIME завершает приём ставок и запускает рулетку."""
    await asyncio.sleep(ROULETTE_BETTING_TIME)
    st = _roulette_state.get(chat_id)
    if not st or st["id"] != state_id:
        return
    if st["status"] != "betting":
        return
    await _roulette_spin(chat_id)


async def cmd_roulette_start(message: Message, bet: int):
    """Запуск рулетки: `старт 1000` (инициатор делает ставку на чёт, если не указано иное)."""
    if message.from_user is None:
        return
    chat_id = message.chat.id
    if chat_id in _roulette_state:
        await send_temp(chat_id, "⚠️ Рулетка уже идёт в этом чате.", delay=8)
        return
    if message.from_user is None:
        return

    st_id = uuid.uuid4().hex[:10]
    state = {
        "id": st_id,
        "initiator": message.from_user.id,
        "status": "betting",
        "bets": {},
        "message_id": None,
        "chat_id": chat_id,
        "created": time.time(),
    }
    _roulette_state[chat_id] = state

    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎡 <b>Рулетка запущена</b>\n\n"
        f"Приём ставок — `{ROULETTE_BETTING_TIME}` сек.\n\n"
        f"<b>Как делать ставки:</b>\n"
        f"• `к 1000` — красное (`×2`)\n"
        f"• `ч 500` — чёрное (`×2`)\n"
        f"• `1000 чет` — чёт (`×2`)\n"
        f"• `1000 нечет` — нечет (`×2`)\n"
        f"• `0 100` — зеро (`×36`)\n"
        f"• `1000 1 2 3` — числа (`×36`)\n"
        f"• `500 10-20` — диапазон\n\n"
        f"<i>Инициатор может сразу сделать свою ставку в этом же сообщении.</i>\n"
        f"{DIVIDER}"
    )
    msg = await message.answer(text)
    state["message_id"] = msg.message_id
    asyncio.create_task(_roulette_timer(chat_id, st_id))


@router.message(F.text.regexp(r"^старт\s+") if hasattr(F.text, "regexp") else F.text.startswith("старт"))
async def cmd_roulette(message: Message):
    if message.from_user is None or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await send_temp(message.chat.id,
                        "Использование: `старт 1000` (затем игроки делают ставки)",
                        delay=10)
        return
    bet = parse_bet(parts[1])
    if not bet:
        await send_temp(message.chat.id, "⚠️ Укажите корректную ставку.", delay=8)
        return
    await cmd_roulette_start(message, bet)


@router.message(F.text.regexp(
    r"^(к|ч|з|зеро|0)\s+\d|^[\d\s,]+\s+(чет|нечет|чёт|нечёт|\d{1,2}|[0-9]{1,2}\s*-\s*[0-9]{1,2})"
) if hasattr(F.text, "regexp") else None)
async def cmd_roulette_bet(message: Message):
    """Парсит ставки рулетки в чате, если идёт приём."""
    if message.from_user is None or not message.text:
        return
    chat_id = message.chat.id
    state = _roulette_state.get(chat_id)
    if not state or state["status"] != "betting":
        return  # Нет рулетки — пропускаем

    parsed = parse_roulette_bet(message.text)
    if not parsed:
        return

    uid = message.from_user.id
    bet = parsed["bet"]

    # Проверка бана
    user = await get_user(uid, use_cache=False)
    if not user:
        return
    if user["banned"]:
        await send_temp(chat_id, "🚫 Доступ ограничен.", delay=8)
        return

    if bet < MIN_BET:
        await send_temp(chat_id, f"Минимальная ставка — `{fmt_num(MIN_BET)}` TOKENS.", delay=8)
        return
    if bet > MAX_BET:
        await send_temp(chat_id, f"Максимальная ставка — `{fmt_num(MAX_BET)}` TOKENS.", delay=8)
        return
    if user["balance"] < bet:
        await send_temp(chat_id, "Недостаточно средств.", delay=8)
        return

    # Кулдаун общий (анти double-spend)
    ok, left = check_cooldown(uid)
    if not ok:
        await send_temp(chat_id, f"⏱ Подождите `{left:.1f}` сек.", delay=6)
        return

    # Списание и учёт
    touch_cooldown(uid)
    await change_balance(uid, -bet, tx_type="roulette_bet", description="Ставка в рулетке")
    state["bets"][uid] = {
        **parsed,
        "name": user["first_name"] or "Игрок",
        "user_id": uid,
    }

    # Обновим сообщение со сводкой
    await _roulette_refresh(chat_id)


async def _roulette_refresh(chat_id: int):
    state = _roulette_state.get(chat_id)
    if not state or not state.get("message_id"):
        return
    left = int(ROULETTE_BETTING_TIME - (time.time() - state["created"]))
    left = max(0, left)
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎡 <b>Рулетка — приём ставок</b>\n\n"
        f"• До старта: `{left}` сек.\n"
        f"• Ставок: `{len(state['bets'])}`\n"
        f"• Общая сумма: `{fmt_num(sum(b['bet'] for b in state['bets'].values()))}` TOKENS\n\n"
        f"{_roulette_bets_summary(state['bets'])}\n"
        f"{DIVIDER}"
    )
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=text)
    except TelegramBadRequest:
        pass


async def _roulette_spin(chat_id: int):
    state = _roulette_state.get(chat_id)
    if not state:
        return
    state["status"] = "spinning"

    if not state["bets"]:
        text = (
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"🎡 <b>Рулетка</b>\n\n"
            f"Ставок не поступило. Отмена.\n{DIVIDER}"
        )
        _roulette_state.pop(chat_id, None)
        if state.get("message_id"):
            try:
                await bot.edit_message_text(chat_id=chat_id,
                                            message_id=state["message_id"], text=text)
            except Exception:
                pass
        return

    # Отправляем стикер рулетки
    try:
        await bot.send_dice(chat_id, emoji="🎰")
    except Exception:
        pass

    await asyncio.sleep(RULETTE_PAUSE)
    number = random.randint(0, 36)
    color = _roulette_color(number)
    color_ru = _roulette_color_ru(color)

    # Расчёт
    results_lines = []
    total_bet = 0
    total_win = 0
    for uid, b in state["bets"].items():
        win = _check_roulette_win(b, number)
        total_bet += b["bet"]
        total_win += win
        if win > 0:
            await change_balance(uid, win, tx_type="roulette_win",
                                 description=f"Рулетка: {number}")
            results_lines.append(
                f"🏆 <b>{b['name']}</b> — выиграл `{fmt_num(win)}` (чистыми `{fmt_num(win - b['bet'])}`)"
            )
        else:
            results_lines.append(
                f"➖ <b>{b['name']}</b> — проиграл `{fmt_num(b['bet'])}`"
            )
        await log_game(uid, "roulette", b["bet"], win, f"num={number}")

    result_text_msg = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎡 <b>Рулетка — результат</b>\n\n"
        f"Выпало: <b>`{number}`</b> ({color_ru})\n\n"
        f"<b>Итоги:</b>\n"
        + "\n".join(results_lines) +
        f"\n\n• Общая ставка: `{fmt_num(total_bet)}`\n"
        f"• Общий выигрыш: `{fmt_num(total_win)}`\n"
        f"{DIVIDER}"
    )

    _roulette_state.pop(chat_id, None)
    if state.get("message_id"):
        try:
            await bot.edit_message_text(chat_id=chat_id,
                                        message_id=state["message_id"],
                                        text=result_text_msg)
            asyncio.create_task(_delete_by_ids(chat_id, state["message_id"], AUTO_DELETE + 5))
            return
        except Exception:
            pass
    await send_temp(chat_id, result_text_msg, delay=AUTO_DELETE + 5)


# ============================================================
# ===                    КЛАНЫ                           ===
# ============================================================

CLAN_CREATE_COST = 25000
CLAN_MAX_MEMBERS = 20
CLAN_MIN_NAME = 3
CLAN_MAX_NAME = 20


def _clan_member_kb(user: Dict[str, Any], is_owner: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 Вложить", callback_data="clan:deposit")
    if is_owner:
        b.button(text="👥 Участники", callback_data="clan:members")
        b.button(text="🗑 Удалить клан", callback_data="clan:delete")
    b.button(text="🚪 Покинуть клан", callback_data="clan:leave")
    b.button(text="◀️ Назад", callback_data="m:clan")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "clan:my")
async def cb_clan_my(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user or not user.get("clan_id"):
        try:
            await cb.answer("Вы не в клане.", show_alert=True)
        except Exception:
            pass
        return
    clan_row = await db.fetchone("SELECT * FROM clans WHERE id = ?", (user["clan_id"],))
    if not clan_row:
        await db.execute("UPDATE users SET clan_id = NULL WHERE user_id = ?", (cb.from_user.id,))
        _user_cache.pop(cb.from_user.id, None)
        try:
            await cb.answer("Клан не найден.", show_alert=True)
        except Exception:
            pass
        return
    members = await db.fetchall(
        "SELECT user_id, role, joined_at FROM clan_members WHERE clan_id = ?",
        (user["clan_id"],),
    )
    is_owner = int(clan_row["owner_id"]) == cb.from_user.id
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🛡 <b>{clan_row['name']}</b>\n\n"
        f"• Владелец ID: `{clan_row['owner_id']}`\n"
        f"• Участников: `{len(members)}` / `{CLAN_MAX_MEMBERS}`\n"
        f"• Баланс клана: `{fmt_num(int(clan_row['balance']))}` TOKENS\n"
        f"{DIVIDER}"
    )
    try:
        await cb.message.edit_text(text, reply_markup=_clan_member_kb(user, is_owner))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=_clan_member_kb(user, is_owner))


@router.callback_query(F.data == "clan:list")
async def cb_clan_list(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    rows = await db.fetchall(
        "SELECT c.id, c.name, c.balance, COUNT(cm.user_id) AS cnt "
        "FROM clans c LEFT JOIN clan_members cm ON cm.clan_id = c.id "
        "GROUP BY c.id ORDER BY c.balance DESC LIMIT 15"
    )
    lines = [f"{CLUB_HEADER}\n{DIVIDER}\n🛡 <b>Топ-15 кланов</b>\n"]
    if not rows:
        lines.append("Кланов пока нет.")
    else:
        for i, r in enumerate(rows):
            lines.append(
                f"• <b>{r['name']}</b> — `{fmt_num(r['balance'])}` | участников: `{r['cnt']}`"
            )
    lines.append(DIVIDER)
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="m:clan")
    b.adjust(1)
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


class ClanStates(StatesGroup):
    waiting_name = State()
    waiting_deposit = State()


@router.callback_query(F.data == "clan:create")
async def cb_clan_create(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user:
        return
    if user.get("clan_id"):
        try:
            await cb.answer("Вы уже в клане.", show_alert=True)
        except Exception:
            pass
        return
    if int(user["balance"]) < CLAN_CREATE_COST:
        try:
            await cb.answer(
                f"Нужно {fmt_num(CLAN_CREATE_COST)} TOKENS для создания клана.",
                show_alert=True,
            )
        except Exception:
            pass
        return
    await state.set_state(ClanStates.waiting_name)
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🛡 <b>Создание клана</b>\n\n"
        f"• Стоимость: `{fmt_num(CLAN_CREATE_COST)}` TOKENS\n"
        f"• Имя: `{CLAN_MIN_NAME}`–`{CLAN_MAX_NAME}` символов\n\n"
        f"Отправьте название клана в чат или /cancel.\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✖️ Отмена", callback_data="clan:cancel")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.message(ClanStates.waiting_name, Command("cancel"))
async def msg_clan_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_reply_kb())


@router.message(ClanStates.waiting_name, F.text)
async def msg_clan_name(message: Message, state: FSMContext):
    if message.from_user is None or not message.text:
        return
    name = message.text.strip()
    if len(name) < CLAN_MIN_NAME or len(name) > CLAN_MAX_NAME:
        await message.answer(f"⚠️ Имя: от `{CLAN_MIN_NAME}` до `{CLAN_MAX_NAME}` символов.")
        return
    if not re.match(r"^[A-Za-zА-Яа-яЁё0-9_\- ]+$", name):
        await message.answer("⚠️ Разрешены буквы, цифры, пробел, `_` и `-`.")
        return
    existing = await db.fetchone("SELECT id FROM clans WHERE LOWER(name) = ?", (name.lower(),))
    if existing:
        await message.answer("⚠️ Клан с таким именем уже существует.")
        return
    user = await get_user(message.from_user.id, use_cache=False)
    if not user or int(user["balance"]) < CLAN_CREATE_COST:
        await message.answer("⚠️ Недостаточно средств.")
        await state.clear()
        return
    await change_balance(message.from_user.id, -CLAN_CREATE_COST, tx_type="clan_create",
                         description=f"Создание клана {name}")
    cur = await db.execute(
        "INSERT INTO clans(name, owner_id, balance, created_at) VALUES(?,?,?,?)",
        (name, message.from_user.id, 0, now_ts()),
    )
    clan_id = cur.lastrowid
    await db.execute(
        "INSERT INTO clan_members(user_id, clan_id, role, joined_at) VALUES(?,?,?,?)",
        (message.from_user.id, clan_id, "owner", now_ts()),
    )
    await db.execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, message.from_user.id))
    _user_cache.pop(message.from_user.id, None)
    await state.clear()
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🛡 <b>Клан создан</b>\n\n"
        f"• Имя: <b>{name}</b>\n"
        f"• Владелец: Вы\n"
        f"• Потрачено: `{fmt_num(CLAN_CREATE_COST)}` TOKENS\n"
        f"{DIVIDER}",
        reply_markup=main_reply_kb(),
    )


@router.callback_query(F.data == "clan:cancel")
async def cb_clan_cancel(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()
    except Exception:
        pass
    await state.clear()
    try:
        await cb.message.edit_text(_clan_menu_text(), reply_markup=_clan_menu_kb(None))
    except TelegramBadRequest:
        await cb.message.answer(_clan_menu_text(), reply_markup=_clan_menu_kb(None))


@router.callback_query(F.data == "clan:deposit")
async def cb_clan_deposit(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user or not user.get("clan_id"):
        try:
            await cb.answer("Вы не в клане.", show_alert=True)
        except Exception:
            pass
        return
    await state.set_state(ClanStates.waiting_deposit)
    text = (
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"💰 <b>Вклад в клан</b>\n\n"
        f"Отправьте сумму TOKENS для вклада в казну клана.\n"
        f"Ваш баланс: `{fmt_num(user['balance'])}` TOKENS\n"
        f"{DIVIDER}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="✖️ Отмена", callback_data="clan:cancel")
    b.adjust(1)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.message(ClanStates.waiting_deposit, Command("cancel"))
async def msg_deposit_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_reply_kb())


@router.message(ClanStates.waiting_deposit, F.text)
async def msg_clan_deposit(message: Message, state: FSMContext):
    if message.from_user is None or not message.text:
        return
    amount = parse_bet(message.text.strip())
    if not amount or amount <= 0:
        await message.answer("⚠️ Введите корректную сумму.")
        return
    user = await get_user(message.from_user.id, use_cache=False)
    if not user or not user.get("clan_id"):
        await state.clear()
        return
    if int(user["balance"]) < amount:
        await message.answer("⚠️ Недостаточно средств.")
        return
    await change_balance(message.from_user.id, -amount, tx_type="clan_deposit",
                         description=f"Вклад в клан #{user['clan_id']}")
    await db.execute("UPDATE clans SET balance = balance + ? WHERE id = ?",
                     (amount, user["clan_id"]))
    await state.clear()
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"💰 <b>Вклад внесён</b>\n\n"
        f"• Внесено: `{fmt_num(amount)}` TOKENS\n"
        f"• Клан: #{user['clan_id']}\n"
        f"{DIVIDER}",
        reply_markup=main_reply_kb(),
    )


@router.callback_query(F.data == "clan:leave")
async def cb_clan_leave(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user or not user.get("clan_id"):
        try:
            await cb.answer("Вы не в клане.", show_alert=True)
        except Exception:
            pass
        return
    clan_row = await db.fetchone("SELECT * FROM clans WHERE id = ?", (user["clan_id"],))
    if clan_row and int(clan_row["owner_id"]) == cb.from_user.id:
        try:
            await cb.answer("Владелец не может покинуть клан. Удалите клан.", show_alert=True)
        except Exception:
            pass
        return
    await db.execute("DELETE FROM clan_members WHERE user_id = ?", (cb.from_user.id,))
    await db.execute("UPDATE users SET clan_id = NULL WHERE user_id = ?", (cb.from_user.id,))
    _user_cache.pop(cb.from_user.id, None)
    try:
        await cb.answer("Вы покинули клан.")
    except Exception:
        pass
    await cb_clan_my(cb)


@router.callback_query(F.data == "clan:members")
async def cb_clan_members(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id)
    if not user or not user.get("clan_id"):
        return
    clan_row = await db.fetchone("SELECT * FROM clans WHERE id = ?", (user["clan_id"],))
    if not clan_row or int(clan_row["owner_id"]) != cb.from_user.id:
        try:
            await cb.answer("Только владелец.", show_alert=True)
        except Exception:
            pass
        return
    rows = await db.fetchall(
        "SELECT cm.user_id, cm.role, u.first_name, u.balance "
        "FROM clan_members cm JOIN users u ON u.user_id = cm.user_id "
        "WHERE cm.clan_id = ? ORDER BY cm.joined_at",
        (user["clan_id"],),
    )
    lines = [f"{CLUB_HEADER}\n{DIVIDER}\n👥 <b>Участники клана {clan_row['name']}</b>\n"]
    for i, r in enumerate(rows, 1):
        role = "👑" if r["role"] == "owner" else "•"
        lines.append(f"{role} <b>{r['first_name'] or '—'}</b> (ID `{r['user_id']}`)")
    lines.append(DIVIDER)
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data="clan:my")
    b.adjust(1)
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "clan:delete")
async def cb_clan_delete(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None:
        return
    user = await get_user(cb.from_user.id, use_cache=False)
    if not user or not user.get("clan_id"):
        return
    clan_row = await db.fetchone("SELECT * FROM clans WHERE id = ?", (user["clan_id"],))
    if not clan_row or int(clan_row["owner_id"]) != cb.from_user.id:
        try:
            await cb.answer("Только владелец.", show_alert=True)
        except Exception:
            pass
        return
    balance = int(clan_row["balance"])
    if balance > 0:
        await change_balance(cb.from_user.id, balance, tx_type="clan_refund",
                             description=f"Возврат казны клана {clan_row['name']}")
    await db.execute("UPDATE users SET clan_id = NULL WHERE clan_id = ?", (user["clan_id"],))
    await db.execute("DELETE FROM clan_members WHERE clan_id = ?", (user["clan_id"],))
    await db.execute("DELETE FROM clans WHERE id = ?", (user["clan_id"],))
    _user_cache.pop(cb.from_user.id, None)
    try:
        await cb.answer("Клан удалён.")
    except Exception:
        pass
    try:
        await cb.message.edit_text(_clan_menu_text(), reply_markup=_clan_menu_kb(None))
    except TelegramBadRequest:
        await cb.message.answer(_clan_menu_text(), reply_markup=_clan_menu_kb(None))


# ============================================================
# ===            ФИНАЛЬНЫЙ fallback для unknown             ===
# ============================================================

@router.message(F.text)
async def unknown_text(message: Message):
    """Если сообщение не распознано ни одним хендлером — подсказка."""
    if message.from_user is None:
        return
    # Не отвечаем на reply-кнопки — они уже обработаны выше
    text = (message.text or "").strip()
    if text in {BTN_GAMES, BTN_BONUS, BTN_DONATE, BTN_PROFILE, BTN_CLAN,
                BTN_TOP, BTN_CHATS, BTN_SUPPORT, BTN_MINIAPP}:
        return
    if text.startswith("/"):
        return
    # Неизвестная команда/сообщение
    await send_temp(
        message.chat.id,
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"Неизвестная команда. Нажмите /start или выберите в меню.\n"
        f"{DIVIDER}",
        delay=6,
    )


# ============================================================
# ===         РЕГИСТРАЦИЯ MIDDLEWARE (защита от флуда)      ===
# ============================================================

class AntiFloodMiddleware:
    """Простой rate-limit: не более 5 сообщений в 3 сек на пользователя."""

    def __init__(self, rate: float = 3.0, burst: int = 5):
        self.rate = rate
        self.burst = burst
        self._tokens: Dict[int, Tuple[float, float]] = {}

    async def __call__(self, handler, event, data):
        uid = None
        if hasattr(event, "from_user") and event.from_user:
            uid = event.from_user.id
        if uid is None:
            return await handler(event, data)

        now = time.time()
        last_ts, tokens = self._tokens.get(uid, (now, float(self.burst)))
        # Пополняем токены
        elapsed = now - last_ts
        tokens = min(float(self.burst), tokens + elapsed * (self.burst / self.rate))
        if tokens < 1:
            self._tokens[uid] = (now, tokens)
            return  # молча игнорируем
        tokens -= 1
        self._tokens[uid] = (now, tokens)
        return await handler(event, data)


# Middleware на message и callback
dp.message.middleware(AntiFloodMiddleware(rate=3.0, burst=5))
dp.callback_query.middleware(AntiFloodMiddleware(rate=3.0, burst=5))


# ============================================================
# ===             ИМПОРТ re ДЛЯ РУЛЕТКИ                  ===
# ============================================================

# re уже импортирован в части 1 через стандартные средства? 
# Гарантируем наличие:
import re  # noqa: E402

# ============================================================
# ===                 АДМИН-ПУЛЬТ                         ===
# ============================================================

ADMIN_HELP_TEXT = (
    f"{CLUB_HEADER}\n{DIVIDER}\n"
    f"🛡 <b>Админ-пульт</b>\n\n"
    f"<b>Экономика:</b>\n"
    f"• `@выдать <id|@user> <сумма>` — выдать TOKENS\n"
    f"• `@забрать <id|@user> <сумма>` — забрать TOKENS\n"
    f"• `@обнулить <id|@user>` — обнулить баланс\n"
    f"• `@баланс <id|@user>` — показать баланс\n"
    f"• `@выдать_всем <сумма>` — выдать всем\n"
    f"• `@забрать_всем <сумма>` — забрать у всех\n"
    f"• `@дроп <сумма>` — глобальный дроп в чат\n\n"
    f"<b>Пользователи:</b>\n"
    f"• `@бан <id|@user> [причина]` — бан\n"
    f"• `@разбан <id|@user>` — разбан\n"
    f"• `@юзер <id|@user>` — подробный профиль\n"
    f"• `@стата` — статистика бота\n\n"
    f"<b>VIP:</b>\n"
    f"• `@выдать_vip <id|@user> <дни>` — выдать VIP\n"
    f"• `@снять_vip <id|@user>` — снять VIP\n\n"
    f"<b>Топ/Логи:</b>\n"
    f"• `@топ_баланс` — топ-10 по балансу\n"
    f"• `@лог [N]` — последние N записей админ-лога\n\n"
    f"<b>Система:</b>\n"
    f"• `@рассылка <текст>` — рассылка всем\n"
    f"• `@рестарт` — мягкий рестарт\n"
    f"• `@бекап` — резервная копия БД\n"
    f"• `@сброс_курса` — сброс курса\n"
    f"• `@отключить_игры` / `@включить_игры`\n"
    f"• `@помощь` — эта справка\n"
    f"{DIVIDER}"
)


def _is_admin_msg(message: Message) -> bool:
    return message.from_user is not None and is_admin(message.from_user.id)


async def _resolve_user(arg: str) -> Optional[int]:
    """Разрешить аргумент в user_id: '12345' → 12345, '@user' → поиск по username."""
    if not arg:
        return None
    a = arg.strip()
    if a.isdigit():
        return int(a)
    if a.startswith("@"):
        uname = a[1:].lower()
        row = await db.fetchone(
            "SELECT user_id FROM users WHERE LOWER(username) = ?", (uname,)
        )
        if row:
            return int(row["user_id"])
    return None


async def _resolve_target(message: Message, args: List[str], idx: int = 0) -> Optional[int]:
    """Разрешает target: сначала entities (text_mention / mention), потом аргумент, потом reply."""
    # reply
    if message.reply_to_message and message.reply_to_message.from_user and len(args) <= idx:
        return message.reply_to_message.from_user.id
    # entities
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user.id
    # аргумент
    if len(args) > idx:
        return await _resolve_user(args[idx])
    # reply fallback
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


async def _admin_log_and_reply(message: Message, action: str, target_id: Optional[int],
                               details: str, text: str):
    if message.from_user is None:
        return
    await log_admin(message.from_user.id, action, target_id, details)
    await message.answer(text)


# ---------- @помощь ----------

@router.message(F.text.startswith("@помощь") | F.text.startswith("@help"))
async def admin_help(message: Message):
    if not _is_admin_msg(message):
        return
    try:
        await message.answer(ADMIN_HELP_TEXT)
    except Exception:
        pass


# ---------- @выдать ----------

@router.message(F.text.startswith("@выдать "))
async def admin_give(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("⚠️ Укажите пользователя (ID/@user/reply).")
        return
    if len(parts) < 3 and not message.reply_to_message:
        await message.answer("Использование: `@выдать <id|@user> <сумма>`")
        return
    amount_arg = parts[-1]
    amount = parse_bet(amount_arg)
    if not amount or amount <= 0:
        await message.answer("⚠️ Укажите корректную сумму.")
        return
    target = await get_user(target_id, use_cache=False)
    if not target:
        await message.answer("⚠️ Пользователь не найден в клубе.")
        return
    new_bal = await change_balance(target_id, amount, tx_type="admin_give",
                                   description=f"Админ-выдача #{message.from_user.id}")
    await _admin_log_and_reply(
        message, "give", target_id, f"+{amount}",
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"✅ Выдано `{fmt_num(amount)}` TOKENS пользователю `{target_id}`.\n"
        f"Новый баланс: `{fmt_num(new_bal)}`.\n{DIVIDER}",
    )


# ---------- @забрать ----------

@router.message(F.text.startswith("@забрать "))
async def admin_take(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("⚠️ Укажите пользователя.")
        return
    amount = parse_bet(parts[-1])
    if not amount or amount <= 0:
        await message.answer("⚠️ Укажите корректную сумму.")
        return
    target = await get_user(target_id, use_cache=False)
    if not target:
        await message.answer("⚠️ Пользователь не найден.")
        return
    take = min(amount, int(target["balance"]))
    new_bal = await change_balance(target_id, -take, tx_type="admin_take",
                                   description=f"Админ-списание #{message.from_user.id}")
    await _admin_log_and_reply(
        message, "take", target_id, f"-{take}",
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"✅ Забрано `{fmt_num(take)}` TOKENS у `{target_id}`.\n"
        f"Новый баланс: `{fmt_num(new_bal)}`.\n{DIVIDER}",
    )


# ---------- @обнулить ----------

@router.message(F.text.startswith("@обнулить"))
async def admin_zero(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("⚠️ Укажите пользователя.")
        return
    new_bal = await set_balance(target_id, 0, tx_type="admin_zero",
                                description=f"Админ-обнуление #{message.from_user.id}")
    await _admin_log_and_reply(
        message, "zero", target_id, "0",
        f"✅ Баланс `{target_id}` обнулён.",
    )


# ---------- @баланс ----------

@router.message(F.text.startswith("@баланс"))
async def admin_balance_check(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("⚠️ Укажите пользователя.")
        return
    target = await get_user(target_id, use_cache=False)
    if not target:
        await message.answer("⚠️ Не найден.")
        return
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"👤 <b>{target['first_name'] or '—'}</b> (`{target_id}`)\n"
        f"• Баланс: `{fmt_num(target['balance'])}` TOKENS\n"
        f"• Игр: `{fmt_num(target['games_played'])}`\n"
        f"• Побед: `{fmt_num(target['games_won'])}`\n"
        f"{DIVIDER}"
    )


# ---------- @выдать_всем ----------

@router.message(F.text.startswith("@выдать_всем "))
async def admin_give_all(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `@выдать_всем <сумма>`")
        return
    amount = parse_bet(parts[1])
    if not amount or amount <= 0:
        await message.answer("⚠️ Укажите корректную сумму.")
        return
    rows = await db.fetchall("SELECT user_id FROM users WHERE banned = 0")
    count = 0
    for r in rows:
        try:
            await change_balance(int(r["user_id"]), amount, tx_type="admin_give_all",
                                 description="Массовая выдача")
            count += 1
        except Exception:
            continue
    await _admin_log_and_reply(
        message, "give_all", None, f"+{amount} x{count}",
        f"✅ Выдано `{fmt_num(amount)}` TOKENS — `{count}` пользователям.",
    )


# ---------- @забрать_всем ----------

@router.message(F.text.startswith("@забрать_всем "))
async def admin_take_all(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `@забрать_всем <сумма>`")
        return
    amount = parse_bet(parts[1])
    if not amount or amount <= 0:
        await message.answer("⚠️ Укажите корректную сумму.")
        return
    rows = await db.fetchall("SELECT user_id, balance FROM users WHERE banned = 0")
    count = 0
    for r in rows:
        take = min(amount, int(r["balance"]))
        if take <= 0:
            continue
        try:
            await change_balance(int(r["user_id"]), -take, tx_type="admin_take_all",
                                 description="Массовое списание")
            count += 1
        except Exception:
            continue
    await _admin_log_and_reply(
        message, "take_all", None, f"-{amount} x{count}",
        f"✅ Забрано до `{fmt_num(amount)}` TOKENS — у `{count}` пользователей.",
    )


# ---------- @дроп (глобальный дроп в чат) ----------

@router.message(F.text.startswith("@дроп "))
async def admin_drop(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `@дроп <сумма>`")
        return
    amount = parse_bet(parts[1])
    if not amount or amount <= 0:
        await message.answer("⚠️ Укажите корректную сумму.")
        return
    # Дроп доступен для всех — первым нажавшим
    drop_id = uuid.uuid4().hex[:8]
    _global_drops[drop_id] = {
        "amount": amount,
        "chat_id": message.chat.id,
        "created": time.time(),
        "claimed": False,
    }
    b = InlineKeyboardBuilder()
    b.button(text=f"🎁 Забрать {fmt_num(amount)}", callback_data=f"drop:{drop_id}")
    b.adjust(1)
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🎁 <b>Глобальный дроп</b>\n\n"
        f"Сумма: `{fmt_num(amount)}` TOKENS\n"
        f"Первый нажавший забирает всё.\n"
        f"{DIVIDER}",
        reply_markup=b.as_markup(),
    )
    await log_admin(message.from_user.id, "drop", None, f"{amount}")


# ---------- @бан ----------

@router.message(F.text.startswith("@бан ") | F.text.startswith("@бан"))
async def admin_ban(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=2)
    target_id = await _resolve_target(message, parts[1:2] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("Использование: `@бан <id|@user> [причина]`")
        return
    reason = parts[2] if len(parts) > 2 else "не указана"
    await db.execute("UPDATE users SET banned = 1, ban_reason = ? WHERE user_id = ?",
                     (reason, target_id))
    _user_cache.pop(target_id, None)
    await _admin_log_and_reply(
        message, "ban", target_id, reason,
        f"🚫 Пользователь `{target_id}` забанен. Причина: <i>{reason}</i>",
    )


# ---------- @разбан ----------

@router.message(F.text.startswith("@разбан"))
async def admin_unban(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("Использование: `@разбан <id|@user>`")
        return
    await db.execute("UPDATE users SET banned = 0, ban_reason = NULL WHERE user_id = ?",
                     (target_id,))
    _user_cache.pop(target_id, None)
    await _admin_log_and_reply(
        message, "unban", target_id, "",
        f"✅ Пользователь `{target_id}` разбанен.",
    )


# ---------- @юзер ----------

@router.message(F.text.startswith("@юзер"))
async def admin_user_info(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("Использование: `@юзер <id|@user>`")
        return
    u = await get_user(target_id, use_cache=False)
    if not u:
        await message.answer("⚠️ Не найден.")
        return
    reg = datetime.fromtimestamp(u["registered_at"], tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    vip_until = u["vip_until"]
    vip_str = (
        datetime.fromtimestamp(vip_until, tz=timezone.utc).strftime("%d.%m.%Y")
        if vip_until > now_ts() else "нет"
    )
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"👤 <b>{u['first_name'] or '—'}</b>\n\n"
        f"• ID: `{target_id}`\n"
        f"• Username: @{u['username'] or '—'}\n"
        f"• Баланс: `{fmt_num(u['balance'])}`\n"
        f"• Игр: `{fmt_num(u['games_played'])}` | Побед: `{fmt_num(u['games_won'])}`\n"
        f"• Поставлено: `{fmt_num(u['total_wagered'])}` | Выиграно: `{fmt_num(u['total_won'])}`\n"
        f"• VIP до: `{vip_str}`\n"
        f"• Бан: `{'да' if u['banned'] else 'нет'}`\n"
        f"• Дата регистрации: `{reg}`\n"
        f"{DIVIDER}"
    )


# ---------- @стата ----------

@router.message(F.text.startswith("@стата"))
async def admin_stats(message: Message):
    if not _is_admin_msg(message):
        return
    total_users = (await db.fetchone("SELECT COUNT(*) AS c FROM users"))["c"]
    banned = (await db.fetchone("SELECT COUNT(*) AS c FROM users WHERE banned = 1"))["c"]
    total_balance = (await db.fetchone("SELECT COALESCE(SUM(balance),0) AS s FROM users"))["s"]
    games_cnt = (await db.fetchone("SELECT COUNT(*) AS c FROM game_log"))["c"]
    clans_cnt = (await db.fetchone("SELECT COUNT(*) AS c FROM clans"))["c"]
    vip_cnt = (await db.fetchone("SELECT COUNT(*) AS c FROM users WHERE vip_until > ?",
                                 (now_ts(),)))["c"]
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"📊 <b>Статистика клуба</b>\n\n"
        f"• Пользователей: `{fmt_num(total_users)}`\n"
        f"• Из них VIP: `{fmt_num(vip_cnt)}`\n"
        f"• Забанено: `{fmt_num(banned)}`\n"
        f"• Кланов: `{fmt_num(clans_cnt)}`\n"
        f"• Сыграно игр: `{fmt_num(games_cnt)}`\n"
        f"• Общий баланс: `{fmt_num(total_balance)}` TOKENS\n"
        f"• Игры: `{'вкл' if GAMES_ENABLED else 'выкл'}`\n"
        f"{DIVIDER}"
    )


# ---------- @топ_баланс ----------

@router.message(F.text.startswith("@топ_баланс"))
async def admin_top_balance(message: Message):
    if not _is_admin_msg(message):
        return
    rows = await db.fetchall(
        "SELECT user_id, first_name, balance FROM users ORDER BY balance DESC LIMIT 10"
    )
    lines = [f"{CLUB_HEADER}\n{DIVIDER}\n💰 <b>Топ-10 по балансу</b>\n"]
    for i, r in enumerate(rows, 1):
        lines.append(f"• `{i}.` {r['first_name'] or '—'} (`{r['user_id']}`): `{fmt_num(r['balance'])}`")
    lines.append(DIVIDER)
    await message.answer("\n".join(lines))


# ---------- @лог ----------

@router.message(F.text.startswith("@лог"))
async def admin_log_view(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    limit = 10
    if len(parts) > 1 and parts[1].isdigit():
        limit = max(1, min(50, int(parts[1])))
    rows = await db.fetchall(
        "SELECT admin_id, action, target_id, details, created_at "
        "FROM admin_log ORDER BY id DESC LIMIT ?", (limit,)
    )
    lines = [f"{CLUB_HEADER}\n{DIVIDER}\n📜 <b>Последние {limit} записей</b>\n"]
    if not rows:
        lines.append("Пусто.")
    for r in rows:
        dt = datetime.fromtimestamp(r["created_at"], tz=timezone.utc).strftime("%d.%m %H:%M")
        lines.append(
            f"• `{dt}` | {r['action']} | admin=`{r['admin_id']}` | "
            f"target=`{r['target_id'] or '—'}` | {r['details'] or ''}"
        )
    lines.append(DIVIDER)
    await message.answer("\n".join(lines))


# ---------- @выдать_vip / @снять_vip ----------

@router.message(F.text.startswith("@выдать_vip "))
async def admin_give_vip(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:2] if len(parts) > 1 else [])
    if target_id is None or len(parts) < 3:
        await message.answer("Использование: `@выдать_vip <id|@user> <дни>`")
        return
    try:
        days = int(parts[2])
    except ValueError:
        await message.answer("⚠️ Дни — целое число.")
        return
    if days <= 0:
        await message.answer("⚠️ Дни > 0.")
        return
    user = await get_user(target_id, use_cache=False)
    if not user:
        await message.answer("⚠️ Не найден.")
        return
    base = max(now_ts(), int(user["vip_until"]))
    new_until = base + days * 24 * 60 * 60
    await db.execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_until, target_id))
    _user_cache.pop(target_id, None)
    await _admin_log_and_reply(
        message, "give_vip", target_id, f"+{days}d",
        f"✅ VIP на `{days}` дн. выдан `{target_id}`.",
    )


@router.message(F.text.startswith("@снять_vip"))
async def admin_remove_vip(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split()
    target_id = await _resolve_target(message, parts[1:] if len(parts) > 1 else [])
    if target_id is None:
        await message.answer("Использование: `@снять_vip <id|@user>`")
        return
    await db.execute("UPDATE users SET vip_until = 0 WHERE user_id = ?", (target_id,))
    _user_cache.pop(target_id, None)
    await _admin_log_and_reply(
        message, "remove_vip", target_id, "",
        f"✅ VIP снят у `{target_id}`.",
    )


# ---------- @рассылка ----------

@router.message(F.text.startswith("@рассылка "))
async def admin_broadcast(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `@рассылка <текст>`")
        return
    text = parts[1]
    rows = await db.fetchall("SELECT user_id FROM users WHERE banned = 0")
    sent = 0
    failed = 0
    for r in rows:
        uid = int(r["user_id"])
        try:
            await bot.send_message(uid, f"{CLUB_HEADER}\n\n{text}\n\n{CLUB_FOOTER}")
            sent += 1
        except TelegramForbiddenError:
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # rate-limit Telegram
    await _admin_log_and_reply(
        message, "broadcast", None, f"sent={sent}",
        f"✅ Рассылка: `{sent}` доставлено, `{failed}` не удалось.",
    )


# ---------- @рестарт ----------

@router.message(F.text.startswith("@рестарт"))
async def admin_restart(message: Message):
    if not _is_admin_msg(message):
        return
    await message.answer("♻️ Мягкий рестарт...")
    await log_admin(message.from_user.id, "restart", None, "")
    # Просто пробуем снова инициализировать бота
    try:
        await bot.get_me()
        await message.answer("✅ Бот в порядке.")
    except Exception as e:
        await message.answer(f"⚠️ Проблемы с ботом: {e}")


# ---------- @бекап ----------

@router.message(F.text.startswith("@бекап"))
async def admin_backup(message: Message):
    if not _is_admin_msg(message):
        return
    try:
        # WAL checkpoint для консистентного бекапа
        await db.execute("PRAGMA wal_checkpoint(FULL)")
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{ts}.db"
        # Копируем файл
        import shutil
        shutil.copy2(DB_PATH, backup_name)
        await message.answer(
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"💾 <b>Бекап создан</b>\n\n"
            f"• Файл: `{backup_name}`\n"
            f"{DIVIDER}"
        )
        await log_admin(message.from_user.id, "backup", None, backup_name)
    except Exception as e:
        log.exception("backup error: %s", e)
        await message.answer(f"⚠️ Ошибка бекапа: {e}")


# ---------- @сброс_курса ----------

@router.message(F.text.startswith("@сброс_курса"))
async def admin_reset_rate(message: Message):
    if not _is_admin_msg(message):
        return
    await set_setting("rate", str(DEFAULT_RATE))
    await log_admin(message.from_user.id, "reset_rate", None, str(DEFAULT_RATE))
    await message.answer(f"✅ Курс сброшен: `{DEFAULT_RATE}`.")


# ---------- @изменить_курс ----------

@router.message(F.text.startswith("@изменить_курс "))
async def admin_change_rate(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `@изменить_курс <значение>`")
        return
    try:
        rate = float(parts[1].replace(",", "."))
    except ValueError:
        await message.answer("⚠️ Введите число.")
        return
    if rate <= 0:
        await message.answer("⚠️ Курс > 0.")
        return
    await set_setting("rate", str(rate))
    await log_admin(message.from_user.id, "change_rate", None, str(rate))
    await message.answer(f"✅ Курс установлен: `{rate}`.")


# ---------- @глобальный_дроп (алиас @дроп) ----------

@router.message(F.text.startswith("@глобальный_дроп "))
async def admin_global_drop(message: Message):
    if not _is_admin_msg(message) or not message.text:
        return
    # Перенаправляем в @дроп
    await admin_drop(message)


# ---------- @отключить_игры / @включить_игры ----------

@router.message(F.text.startswith("@отключить_игры"))
async def admin_disable_games(message: Message):
    if not _is_admin_msg(message):
        return
    global GAMES_ENABLED
    GAMES_ENABLED = False
    await set_setting("games_enabled", "0")
    await log_admin(message.from_user.id, "disable_games", None, "")
    await message.answer("⏸ Игры отключены.")


@router.message(F.text.startswith("@включить_игры"))
async def admin_enable_games(message: Message):
    if not _is_admin_msg(message):
        return
    global GAMES_ENABLED
    GAMES_ENABLED = True
    await set_setting("games_enabled", "1")
    await log_admin(message.from_user.id, "enable_games", None, "")
    await message.answer("▶️ Игры включены.")


# ---------- @разбан_все / @бан_все (бонус) ----------

@router.message(F.text.startswith("@разбан_все"))
async def admin_unban_all(message: Message):
    if not _is_admin_msg(message):
        return
    await db.execute("UPDATE users SET banned = 0, ban_reason = NULL WHERE banned = 1")
    _user_cache.clear()
    await log_admin(message.from_user.id, "unban_all", None, "")
    await message.answer("✅ Все разбанены.")


# ============================================================
# ===              ОБРАБОТКА ДРОПОВ                      ===
# ============================================================

_global_drops: Dict[str, Dict[str, Any]] = {}


@router.callback_query(F.data.startswith("drop:"))
async def cb_drop_claim(cb: CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    if cb.from_user is None or not cb.data:
        return
    drop_id = cb.data.split(":", 1)[1]
    d = _global_drops.get(drop_id)
    if not d or d.get("claimed"):
        try:
            await cb.answer("Дроп уже забрали.", show_alert=True)
        except Exception:
            pass
        return
    d["claimed"] = True
    d["claimed_by"] = cb.from_user.id
    await change_balance(cb.from_user.id, d["amount"], tx_type="drop",
                         description=f"Глобальный дроп {drop_id}")
    await log_admin(0, "drop_claim", cb.from_user.id, f"{d['amount']}")
    try:
        await cb.message.edit_text(
            f"{CLUB_HEADER}\n{DIVIDER}\n"
            f"🎁 <b>Дроп забран</b>\n\n"
            f"• Счастливчик: <b>{cb.from_user.first_name}</b>\n"
            f"• Сумма: `{fmt_num(d['amount'])}` TOKENS\n"
            f"{DIVIDER}"
        )
    except Exception:
        pass
    # Автоочистка
    asyncio.create_task(_drop_cleanup(drop_id))


async def _drop_cleanup(drop_id: str):
    await asyncio.sleep(300)
    _global_drops.pop(drop_id, None)


# ============================================================
# ===          ОБРАБОТЧИК /start С ГЛУБОКИМИ ССЫЛКАМИ     ===
# ============================================================

@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject):
    if message.from_user is None:
        return
    u = message.from_user
    await ensure_user(u.id, u.username, u.first_name or "Игрок")
    arg = (command.args or "").strip()
    if arg.startswith("ref_"):
        try:
            ref_id = int(arg[4:])
        except ValueError:
            ref_id = 0
        if ref_id and ref_id != u.id:
            ref = await get_user(ref_id)
            if ref:
                await change_balance(ref_id, 1000, tx_type="ref_bonus",
                                     description=f"Реферал {u.id}")
                await message.answer("✅ Вам начислен реферальный бонус 1000 TOKENS!")
    # Обычное приветствие
    user = await get_user(u.id)
    if user:
        await message.answer(
            greeting_text(user["first_name"] or "Игрок", int(user["balance"])),
            reply_markup=main_reply_kb(),
        )


# ============================================================
# ===               ПРОВЕРКА ВОССТАНОВЛЕНИЯ              ===
# ============================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        f"{CLUB_HEADER}\n{DIVIDER}\n"
        f"🆘 <b>Справка</b>\n\n"
        f"• /start — главное меню\n"
        f"• /profile — профиль\n"
        f"• /bonus — бонус\n"
        f"• /top — топ игроков\n\n"
        f"<b>Игры:</b>\n"
        f"`кости 1000`, `дартс 1000`, `баскет 1000`\n"
        f"`футбол 1000`, `боулинг 1000`, `бж 1000`, `слоты 1000`\n"
        f"`мины 1000` — мины\n"
        f"`дуэль @user 1000` — дуэль\n"
        f"`старт 1000` — рулетка\n\n"
        f"<b>Рулетка:</b>\n"
        f"`к 1000` / `ч 500` / `1000 чет` / `1000 нечет`\n"
        f"`0 100` / `1000 1 2 3` / `500 10-20`\n"
        f"{DIVIDER}"
    )


# ============================================================
# ===        ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ ИЗ БД              ===
# ============================================================

async def restore_state():
    """Восстанавливает настройки из БД при старте."""
    global GAMES_ENABLED
    try:
        rate_val = await get_setting("rate", str(DEFAULT_RATE))
        games_val = await get_setting("games_enabled", "1")
        GAMES_ENABLED = (games_val == "1")
        log.info("Состояние: games=%s, rate=%s", GAMES_ENABLED, rate_val)
    except Exception as e:
        log.exception("restore_state error: %s", e)


# ============================================================
# ===        ОЧИСТКА КЭША И ЗАВИСШИХ СОСТОЯНИЙ          ===
# ============================================================

async def cleanup_loop():
    """Периодическая очистка старых состояний игр."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        # Просроченные дуэли
        for did in list(_active_duels.keys()):
            d = _active_duels.get(did)
            if d and now - d["created"] > DUEL_EXPIRY + 30:
                _active_duels.pop(did, None)
        # Просроченные мины (>30 мин)
        for uid in list(_active_mines.keys()):
            s = _active_mines.get(uid)
            if s and now - s["started"] > 1800:
                _active_mines.pop(uid, None)
        # Просроченные БЖ
        for uid in list(_active_bj.keys()):
            s = _active_bj.get(uid)
            if s and now - s["started"] > 900:
                _active_bj.pop(uid, None)
        # Просроченные рулетки
        for cid in list(_roulette_state.keys()):
            s = _roulette_state.get(cid)
            if s and now - s["created"] > 600:
                _roulette_state.pop(cid, None)
        # Кэш пользователей
        if len(_user_cache) > 5000:
            _user_cache.clear()
        # Кулдауны
        for uid in list(_game_cooldown.keys()):
            if now - _game_cooldown[uid] > 60:
                _game_cooldown.pop(uid, None)


# ============================================================
# ===               ФИНАЛЬНЫЙ ЗАПУСК                     ===
# ============================================================

async def on_startup_final():
    await init_db()
    await restore_state()
    await start_web_server()

    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="bonus", description="Ежедневный бонус"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        log.warning("Не удалось установить команды: %s", e)

    me = await bot.get_me()
    log.info("✅ Бот запущен: @%s (id=%s)", me.username, me.id)
    log.info("👥 Админов: %d", len(ADMIN_IDS))
    log.info("🌐 Web API на :%d", PORT)

    # Фоновая очистка
    asyncio.create_task(cleanup_loop())


async def on_shutdown_final():
    await db.close()
    log.info("Бот остановлен.")


# Переопределяем старт/стоп (перезаписываем из Части 1)
dp.startup.register(on_startup_final)
dp.shutdown.register(on_shutdown_final)


async def main_final():
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main_final())
    except (KeyboardInterrupt, SystemExit):             
        log.info("Прервано пользователем.")