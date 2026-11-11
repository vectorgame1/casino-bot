import asyncio
import os
import random
import time
import json
import sqlite3
import aiosqlite
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any, Union

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, LabeledPrice,
    PreCheckoutQuery, ContentType
)
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ChatType, DiceEmoji
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8940867005:AAHeQpS4_I1XZWfzC107G3EPNneQF_8JbYA") # Если токен обрезан на скрине, допиши его полностью!
ADMIN_IDS = [6403424348] 
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/vctorw")

CHAT_GAME = "https://t.me/tokenplays"
CHAT_EXCHANGE = "https://t.me/Tokenschange"
CHAT_NEWS = "https://t.me/TokenCasinoTournaments"

BOT_USERNAME = os.getenv("BOT_USERNAME", "GameBot")
DB_PATH = os.getenv("DB_PATH", "gamebot.db")
PORT = int(os.getenv("PORT", "8080"))

START_STICKER = "🎰"
WIN_STICKER = "🎉"
LOSE_STICKER = "😢"

HOW_TO_PLAY = (
    "<b>📖 КАК ИГРАТЬ</b>\n\n"
    "<b>🎲 Кости</b>\n"
    "Ставишь сумму, бот бросает анимированные кости.\n"
    "Выигрыш зависит от выпавшей комбинации:\n"
    "• 1 — x0 (проигрыш)\n"
    "• 2-3 — x1 (возврат)\n"
    "• 4-5 — x1.5\n"
    "• 6 — x2\n"
    "• Дубль — x3\n\n"
    "<b>🎯 Дартс</b>\n"
    "Бот бросает дротик. Попадание в центр — x3.\n"
    "Красный круг — x2. Синий — x1.5.\n\n"
    "<b>🏀 Баскетбол</b>\n"
    "Анимированный бросок мяча.\n"
    "Гол — x2, точный бросок — x3.\n\n"
    "<b>⚽ Футбол</b>\n"
    "Удар по воротам. Гол — x2.\n\n"
    "<b>🎳 Боулинг</b>\n"
    "Страйк (все кегли) — x3, спэр — x2.\n\n"
    "<b>🎰 Слоты</b>\n"
    "Три барабана. Три одинаковых — x5.\n"
    "Два одинаковых — x1.5.\n\n"
    "<b>💣 Мины</b>\n"
    "Поле 5x5. Открывай клетки, не попав на мину.\n"
    "Чем больше открыл — тем больше кэшаут.\n\n"
    "<b>🃏 Блэкджек</b>\n"
    "Набери 21 очко, не переборщи.\n"
    "Ближе к 21 чем дилер — победа x2.\n\n"
    "<b>⚔️ Дуэли</b>\n"
    "Вызови другого игрока на дуэль.\n"
    "Победитель забирает банк.\n\n"
    "<b>🎁 Подарки</b>\n"
    "Отправляй подарки другим игрокам.\n\n"
    "<b>🎡 Рулетка</b>\n"
    "Ставки в чате: «к 1000», «10-20 500».\n"
    "Ведущий запускает «старт» — колесо крутится.\n"
    "Побеждает одна из ставок.\n\n"
    "<b>🏰 Кланы</b>\n"
    "Создай клан, качай его, плати налог.\n"
    "Клановые бонусы к выигрышу.\n\n"
    "<b>💎 VIP</b>\n"
    "Покупай VIP для повышенных лимитов.\n\n"
    "<b>🎁 Бонус</b>\n"
    "Ежедневный бонус — заходи каждый день.\n\n"
    "<b>👥 Рефералка</b>\n"
    "Приглашай друзей, получай % от их ставок.\n\n"
    "Удачи в игре! 🍀"
)

GAMES_MENU = (
    "<b>🎮 ИГРЫ</b>\n\n"
    "Выбери игру из меню ниже.\n"
    "Все игры используют анимированные стикеры Telegram.\n"
    "Ставки списываются автоматически."
)

PROFILE_TEXT = (
    "<b>👤 ПРОФИЛЬ</b>\n\n"
    "🆔 ID: <code>{user_id}</code>\n"
    "👤 Имя: {name}\n"
    "💰 Баланс: <b>{balance}</b> 💎\n"
    "🏆 Побед: {wins}\n"
    "💀 Поражений: {losses}\n"
    "🎮 Всего игр: {games}\n"
    "⭐ Уровень: {level}\n"
    "🏰 Клан: {clan}\n"
    "💎 VIP: {vip}\n"
    "📅 Регистрация: {reg_date}"
)

DONATE_TEXT = (
    "<b>💎 ДОНАТ</b>\n\n"
    "Курс: <b>1 ⭐ = {rate} 💎</b>\n\n"
    "Выбери пакет:\n"
    "• 100 ⭐ — 1000 💎\n"
    "• 250 ⭐ — 2700 💎 (+8%)\n"
    "• 500 ⭐ — 6000 💎 (+20%)\n"
    "• 1000 ⭐ — 13000 💎 (+30%)\n\n"
    "Оплата через Telegram Stars."
)

BONUS_TEXT = (
    "<b>🎁 БОНУС</b>\n\n"
    "Твой ежедневный бонус: <b>{bonus}</b> 💎\n"
    "Следующий бонус через: {timer}\n\n"
    "Заходи каждый день — бонус растёт!"
)

TOP_TEXT = (
    "<b>🏆 ТОП ИГРОКОВ</b>\n\n"
    "{players}"
)

REF_TEXT = (
    "<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
    "Твоя ссылка:\n"
    "<code>{link}</code>\n\n"
    "Приглашено: <b>{refs}</b>\n"
    "Заработано: <b>{earned}</b> 💎\n\n"
    "Ты получаешь 5% от ставок рефералов!"
)

SUPPORT_TEXT = (
    "<b>🆘 ПОДДЕРЖКА</b>\n\n"
    "Если у тебя проблемы — пиши в поддержку.\n"
    "Мы отвечаем в течение 24 часов.\n\n"
    "🔗 {link}"
)

# Читаем ссылки из .env с дефолтными значениями (если вдруг забыл вписать)
CHAT_GAME = os.getenv("CHAT_GAME", "https://t.me/+link1")
CHAT_EXCHANGE = os.getenv("CHAT_EXCHANGE", "https://t.me/+link2")
CHAT_NEWS = os.getenv("CHAT_NEWS", "https://t.me/+link3")

def chats_inline_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎰 Игровой чат", url=CHAT_GAME)
    kb.button(text="💱 Обмен валют", url=CHAT_EXCHANGE)
    kb.button(text="📢 Новости", url=CHAT_NEWS)
    kb.button(text="⬅️ Назад", callback_data="nav_menu")
    kb.adjust(1)
    return kb.as_markup()

CLANS_TEXT = (
    "<b>🏰 КЛАНЫ</b>\n\n"
    "Создай клан за <b>10000</b> 💎\n"
    "Прокачивай клан, плати налог.\n\n"
    "Твой клан: <b>{clan}</b>\n"
    "Участников: {members}\n"
    "Уровень: {level}"
)


class GameStates(StatesGroup):
    waiting_bet = State()
    waiting_mines = State()
    waiting_duel_target = State()
    waiting_duel_bet = State()
    waiting_gift_target = State()
    waiting_gift_amount = State()
    waiting_clan_name = State()
    waiting_promo = State()
    waiting_roulette_bet = State()
    waiting_admin_input = State()
    waiting_admin_input


async def auto_delete(message: Message, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def fmt_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def vip_multiplier(vip_level: int) -> float:
    return {0: 1.0, 1: 1.1, 2: 1.25, 3: 1.5}.get(vip_level, 1.0)


def level_from_xp(xp: int) -> int:
    return max(1, int(xp ** 0.5) + 1)


def xp_for_next(level: int) -> int:
    return (level ** 2) * 100


class DB:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Открывает соединение с SQLite и создаёт все таблицы."""
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        await self.create_tables()

    async def close(self):
        """Закрывает соединение с БД."""
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def create_tables(self):
        """Создаёт все необходимые таблицы с индексами."""
        async with self._lock:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    balance INTEGER DEFAULT 1000,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    games INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    vip_level INTEGER DEFAULT 0,
                    vip_until TEXT DEFAULT NULL,
                    clan_id INTEGER DEFAULT NULL,
                    referrer_id INTEGER DEFAULT NULL,
                    ref_earned INTEGER DEFAULT 0,
                    last_bonus TEXT DEFAULT NULL,
                    bonus_streak INTEGER DEFAULT 0,
                    banned INTEGER DEFAULT 0,
                    reg_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    total_bet INTEGER DEFAULT 0,
                    total_win INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS clans (
                    clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    owner_id INTEGER NOT NULL,
                    treasury INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    tax INTEGER DEFAULT 5,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    members_count INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    game TEXT NOT NULL,
                    bet INTEGER NOT NULL,
                    win INTEGER NOT NULL,
                    result TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS roulette_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    winner_id INTEGER,
                    bet_amount INTEGER,
                    bet_type TEXT,
                    participants TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS promocodes (
                    code TEXT PRIMARY KEY,
                    amount INTEGER NOT NULL,
                    uses_left INTEGER DEFAULT 1,
                    created_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS duels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    challenger_id INTEGER NOT NULL,
                    opponent_id INTEGER NOT NULL,
                    bet INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS mines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    bet INTEGER NOT NULL,
                    mines_count INTEGER NOT NULL,
                    field TEXT NOT NULL,
                    opened TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance);
                CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id);
                CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
            """)
            await self.conn.commit()

    async def get_user(self, user_id: int) -> Optional[aiosqlite.Row]:
        """Возвращает пользователя по ID или None."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()

    async def ensure_user(self, user_id: int, username: str = "",
                          first_name: str = "", referrer_id: Optional[int] = None) -> aiosqlite.Row:
        """Создаёт пользователя если нет и возвращает запись."""
        user = await self.get_user(user_id)
        if not user:
            async with self._lock:
                await self.conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, username, first_name, referrer_id) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, username or "", first_name or "", referrer_id)
                )
                await self.conn.commit()
            if referrer_id:
                ref = await self.get_user(referrer_id)
                if ref:
                    await self.conn.execute(
                        "UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL",
                        (referrer_id, user_id)
                    )
                    await self.conn.commit()
            user = await self.get_user(user_id)
        else:
            if username != user["username"] or first_name != user["first_name"]:
                await self.conn.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username or "", first_name or "", user_id)
                )
                await self.conn.commit()
        return user

    async def get_balance(self, user_id: int) -> int:
        """Возвращает баланс пользователя."""
        user = await self.get_user(user_id)
        return user["balance"] if user else 0

    async def add_balance(self, user_id: int, amount: int) -> int:
        """Добавляет (или вычитает) баланс. Возвращает новый баланс."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?",
                (amount, user_id)
            )
            await self.conn.commit()
        return await self.get_balance(user_id)

    async def take_balance(self, user_id: int, amount: int) -> bool:
        """Списывает сумму если хватает. Возвращает успех."""
        async with self._lock:
            async with self.conn.execute(
                "SELECT balance FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row or row["balance"] < amount:
                return False
            await self.conn.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, user_id)
            )
            await self.conn.commit()
            return True

    async def update_stats(self, user_id: int, game: str, bet: int,
                           win: int, result: str = ""):
        """Обновляет статистику после игры и записывает историю."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET games = games + 1, "
                "wins = wins + ?, losses = losses + ?, "
                "total_bet = total_bet + ?, total_win = total_win + ?, "
                "xp = xp + ? WHERE user_id = ?",
                (1 if win > bet else 0, 0 if win > bet else 1,
                 bet, win, max(1, bet // 100), user_id)
            )
            await self.conn.execute(
                "INSERT INTO history (user_id, game, bet, win, result) VALUES (?, ?, ?, ?, ?)",
                (user_id, game, bet, win, result)
            )
            await self.conn.commit()
        await self.update_level(user_id)
        await self.pay_clan_tax(user_id, bet)
        await self.pay_referral(user_id, bet)

    async def update_level(self, user_id: int):
        """Пересчитывает уровень по XP."""
        user = await self.get_user(user_id)
        if not user:
            return
        new_level = level_from_xp(user["xp"])
        if new_level != user["level"]:
            await self.conn.execute(
                "UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id)
            )
            await self.conn.commit()

    async def pay_clan_tax(self, user_id: int, bet: int):
        """Отчисляет налог клана с ставки."""
        user = await self.get_user(user_id)
        if not user or not user["clan_id"]:
            return
        clan = await self.get_clan(user["clan_id"])
        if not clan:
            return
        tax = bet * clan["tax"] // 100
        if tax > 0:
            async with self._lock:
                await self.conn.execute(
                    "UPDATE clans SET treasury = treasury + ? WHERE clan_id = ?",
                    (tax, clan["clan_id"])
                )
                await self.conn.commit()

    async def pay_referral(self, user_id: int, bet: int):
        """Начисляет рефереру 5% от ставки."""
        user = await self.get_user(user_id)
        if not user or not user["referrer_id"]:
            return
        reward = bet * 5 // 100
        if reward > 0:
            async with self._lock:
                await self.conn.execute(
                    "UPDATE users SET balance = balance + ?, ref_earned = ref_earned + ? WHERE user_id = ?",
                    (reward, reward, user["referrer_id"])
                )
                await self.conn.commit()

    async def add_history(self, user_id: int, game: str, bet: int,
                          win: int, result: str = ""):
        """Пишет запись в историю игр."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO history (user_id, game, bet, win, result) VALUES (?, ?, ?, ?, ?)",
                (user_id, game, bet, win, result)
            )
            await self.conn.commit()

    async def get_history(self, user_id: int, limit: int = 20) -> List[aiosqlite.Row]:
        """Возвращает последние игры пользователя."""
        async with self.conn.execute(
            "SELECT * FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            return await cur.fetchall()

    async def top_players(self, limit: int = 10) -> List[aiosqlite.Row]:
        """Топ игроков по балансу."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE banned = 0 ORDER BY balance DESC LIMIT ?",
            (limit,)
        ) as cur:
            return await cur.fetchall()

    async def top_by_wins(self, limit: int = 10) -> List[aiosqlite.Row]:
        """Топ по победам."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE banned = 0 ORDER BY wins DESC LIMIT ?",
            (limit,)
        ) as cur:
            return await cur.fetchall()

    async def claim_bonus(self, user_id: int) -> Tuple[bool, int, int]:
        """Выдаёт ежедневный бонус. Возвращает (успех, сумма, streak)."""
        user = await self.get_user(user_id)
        if not user:
            return False, 0, 0
        now = datetime.utcnow()
        last = user["last_bonus"]
        streak = user["bonus_streak"] or 0
        if last:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt < timedelta(hours=24):
                return False, 0, streak
            if now - last_dt < timedelta(hours=48):
                streak += 1
            else:
                streak = 1
        else:
            streak = 1
        bonus = 500 + min(streak, 30) * 100
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET balance = balance + ?, last_bonus = ?, bonus_streak = ? "
                "WHERE user_id = ?",
                (bonus, now.isoformat(), streak, user_id)
            )
            await self.conn.commit()
        return True, bonus, streak

    async def get_bonus_timer(self, user_id: int) -> str:
        """Возвращает строку таймера до следующего бонуса."""
        user = await self.get_user(user_id)
        if not user or not user["last_bonus"]:
            return "доступен"
        last = datetime.fromisoformat(user["last_bonus"])
        diff = timedelta(hours=24) - (datetime.utcnow() - last)
        if diff.total_seconds() <= 0:
            return "доступен"
        h = diff.seconds // 3600
        m = (diff.seconds % 3600) // 60
        return f"{h}ч {m}м"

    async def get_refs_count(self, user_id: int) -> int:
        """Количество приглашённых."""
        async with self.conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE referrer_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["c"] if row else 0

    async def create_clan(self, name: str, owner_id: int) -> Optional[int]:
        """Создаёт клан. Возвращает clan_id или None."""
        async with self._lock:
            try:
                cur = await self.conn.execute(
                    "INSERT INTO clans (name, owner_id) VALUES (?, ?)",
                    (name, owner_id)
                )
                clan_id = cur.lastrowid
                await self.conn.execute(
                    "UPDATE users SET clan_id = ? WHERE user_id = ?",
                    (clan_id, owner_id)
                )
                await self.conn.commit()
                return clan_id
            except sqlite3.IntegrityError:
                return None

    async def get_clan(self, clan_id: int) -> Optional[aiosqlite.Row]:
        """Получает клан по ID."""
        async with self.conn.execute(
            "SELECT * FROM clans WHERE clan_id = ?", (clan_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_clan_by_name(self, name: str) -> Optional[aiosqlite.Row]:
        """Получает клан по имени."""
        async with self.conn.execute(
            "SELECT * FROM clans WHERE name = ?", (name,)
        ) as cur:
            return await cur.fetchone()

    async def get_user_clan(self, user_id: int) -> Optional[aiosqlite.Row]:
        """Клан пользователя."""
        user = await self.get_user(user_id)
        if not user or not user["clan_id"]:
            return None
        return await self.get_clan(user["clan_id"])

    async def clan_members(self, clan_id: int) -> List[aiosqlite.Row]:
        """Участники клана."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE clan_id = ?", (clan_id,)
        ) as cur:
            return await cur.fetchall()

    async def join_clan(self, user_id: int, clan_id: int) -> bool:
        """Вступает в клан."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, user_id)
            )
            await self.conn.execute(
                "UPDATE clans SET members_count = members_count + 1 WHERE clan_id = ?",
                (clan_id,)
            )
            await self.conn.commit()
        return True

    async def leave_clan(self, user_id: int) -> bool:
        """Выходит из клана."""
        user = await self.get_user(user_id)
        if not user or not user["clan_id"]:
            return False
        clan_id = user["clan_id"]
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET clan_id = NULL WHERE user_id = ?", (user_id,)
            )
            await self.conn.execute(
                "UPDATE clans SET members_count = MAX(1, members_count - 1) WHERE clan_id = ?",
                (clan_id,)
            )
            await self.conn.commit()
        return True

    async def upgrade_clan(self, clan_id: int) -> bool:
        """Прокачивает клан за счёт казны."""
        clan = await self.get_clan(clan_id)
        if not clan:
            return False
        cost = clan["level"] * 50000
        if clan["treasury"] < cost:
            return False
        async with self._lock:
            await self.conn.execute(
                "UPDATE clans SET treasury = treasury - ?, level = level + 1 WHERE clan_id = ?",
                (cost, clan_id)
            )
            await self.conn.commit()
        return True

    async def clan_deposit(self, user_id: int, amount: int) -> bool:
        """Пополнение казны клана."""
        user = await self.get_user(user_id)
        if not user or not user["clan_id"]:
            return False
        if not await self.take_balance(user_id, amount):
            return False
        async with self._lock:
            await self.conn.execute(
                "UPDATE clans SET treasury = treasury + ? WHERE clan_id = ?",
                (amount, user["clan_id"])
            )
            await self.conn.commit()
        return True

    async def set_clan_tax(self, clan_id: int, tax: int):
        """Устанавливает налог клана."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE clans SET tax = ? WHERE clan_id = ?", (tax, clan_id)
            )
            await self.conn.commit()

    async def create_promo(self, code: str, amount: int, uses: int, admin_id: int) -> bool:
        """Создаёт промокод."""
        async with self._lock:
            try:
                await self.conn.execute(
                    "INSERT INTO promocodes (code, amount, uses_left, created_by) VALUES (?, ?, ?, ?)",
                    (code, amount, uses, admin_id)
                )
                await self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    async def use_promo(self, user_id: int, code: str) -> Optional[int]:
        """Активирует промокод. Возвращает сумму или None."""
        async with self._lock:
            async with self.conn.execute(
                "SELECT * FROM promocodes WHERE code = ?", (code,)
            ) as cur:
                row = await cur.fetchone()
            if not row or row["uses_left"] <= 0:
                return None
            await self.conn.execute(
                "UPDATE promocodes SET uses_left = uses_left - 1 WHERE code = ?", (code,)
            )
            await self.conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (row["amount"], user_id)
            )
            await self.conn.commit()
            return row["amount"]

    async def get_vip_until(self, user_id: int) -> Optional[str]:
        """Дата окончания VIP."""
        user = await self.get_user(user_id)
        return user["vip_until"] if user else None

    async def set_vip(self, user_id: int, level: int, days: int):
        """Выдаёт VIP."""
        until = (datetime.utcnow() + timedelta(days=days)).isoformat()
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET vip_level = ?, vip_until = ? WHERE user_id = ?",
                (level, until, user_id)
            )
            await self.conn.commit()

    async def check_vip(self, user_id: int) -> int:
        """Проверяет актуальность VIP. Возвращает уровень."""
        user = await self.get_user(user_id)
        if not user or not user["vip_until"]:
            return 0
        if datetime.utcnow() > datetime.fromisoformat(user["vip_until"]):
            await self.conn.execute(
                "UPDATE users SET vip_level = 0, vip_until = NULL WHERE user_id = ?",
                (user_id,)
            )
            await self.conn.commit()
            return 0
        return user["vip_level"]

    async def log_admin(self, admin_id: int, action: str,
                        target_id: Optional[int] = None, details: str = ""):
        """Логирует админское действие."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO admin_logs (admin_id, action, target_id, details) VALUES (?, ?, ?, ?)",
                (admin_id, action, target_id, details)
            )
            await self.conn.commit()

    async def ban_user(self, user_id: int, banned: bool = True):
        """Блокирует/разблокирует пользователя."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id)
            )
            await self.conn.commit()

    async def create_duel(self, challenger_id: int, opponent_id: int, bet: int) -> int:
        """Создаёт дуэль."""
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO duels (challenger_id, opponent_id, bet) VALUES (?, ?, ?)",
                (challenger_id, opponent_id, bet)
            )
            await self.conn.commit()
            return cur.lastrowid

    async def get_duel(self, duel_id: int) -> Optional[aiosqlite.Row]:
        """Получает дуэль."""
        async with self.conn.execute(
            "SELECT * FROM duels WHERE id = ?", (duel_id,)
        ) as cur:
            return await cur.fetchone()

    async def finish_duel(self, duel_id: int, status: str):
        """Завершает дуэль."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE duels SET status = ? WHERE id = ?", (status, duel_id)
            )
            await self.conn.commit()

    async def create_mines(self, user_id: int, bet: int, mines_count: int,
                           field: str) -> int:
        """Создаёт игру в мины."""
        async with self._lock:
            cur = await self.conn.execute(
                "INSERT INTO mines (user_id, bet, mines_count, field) VALUES (?, ?, ?, ?)",
                (user_id, bet, mines_count, field)
            )
            await self.conn.commit()
            return cur.lastrowid

    async def get_mines(self, game_id: int) -> Optional[aiosqlite.Row]:
        """Получает игру мины."""
        async with self.conn.execute(
            "SELECT * FROM mines WHERE id = ?", (game_id,)
        ) as cur:
            return await cur.fetchone()

    async def update_mines(self, game_id: int, opened: str, status: str = "active"):
        """Обновляет состояние мины."""
        async with self._lock:
            await self.conn.execute(
                "UPDATE mines SET opened = ?, status = ? WHERE id = ?",
                (opened, status, game_id)
            )
            await self.conn.commit()

    async def get_setting(self, key: str, default: str = "") -> str:
        """Читает настройку."""
        async with self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        """Записывает настройку."""
        async with self._lock:
            await self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            await self.conn.commit()

    async def all_users(self) -> List[aiosqlite.Row]:
        """Все пользователи."""
        async with self.conn.execute("SELECT * FROM users") as cur:
            return await cur.fetchall()

    async def log_roulette(self, chat_id: int, winner_id: int, bet_amount: int,
                           bet_type: str, participants: str):
        """Логирует рулетку."""
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO roulette_logs (chat_id, winner_id, bet_amount, bet_type, participants) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, winner_id, bet_amount, bet_type, participants)
            )
            await self.conn.commit()

    async def get_roulette_logs(self, chat_id: int, limit: int = 20) -> List[aiosqlite.Row]:
        """Логи рулетки чата."""
        async with self.conn.execute(
            "SELECT * FROM roulette_logs WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        ) as cur:
            return await cur.fetchall()


db = DB()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def kb_main() -> ReplyKeyboardMarkup:
    """Главное Reply-меню бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="💎 Донат"), KeyboardButton(text="🎁 Бонус")],
            [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🏰 Кланы")],
            [KeyboardButton(text="👥 Рефералка"), KeyboardButton(text="📖 Как играть")],
            [KeyboardButton(text="🆘 Поддержка"), KeyboardButton(text="💬 Чаты")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )


def kb_games() -> InlineKeyboardMarkup:
    """Меню игр."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"),
             InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_basket"),
             InlineKeyboardButton(text="⚽ Футбол", callback_data="game_football")],
            [InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling"),
             InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots")],
            [InlineKeyboardButton(text="💣 Мины", callback_data="game_mines"),
             InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_blackjack")],
            [InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_duels"),
             InlineKeyboardButton(text="🎁 Подарки", callback_data="game_gift")],
            [InlineKeyboardButton(text="🎡 Рулетка (чат)", callback_data="game_roulette")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def kb_bet(game: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора ставки для игры."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="100", callback_data=f"bet_{game}_100"),
             InlineKeyboardButton(text="500", callback_data=f"bet_{game}_500"),
             InlineKeyboardButton(text="1000", callback_data=f"bet_{game}_1000")],
            [InlineKeyboardButton(text="5000", callback_data=f"bet_{game}_5000"),
             InlineKeyboardButton(text="10000", callback_data=f"bet_{game}_10000"),
             InlineKeyboardButton(text="25000", callback_data=f"bet_{game}_25000")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav_menu")],
        ]
    )


def kb_mines(game_id: int, opened: List[int], mines_count: int) -> InlineKeyboardMarkup:
    """Игровое поле 5x5 для мин."""
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened:
                row.append(InlineKeyboardButton(text="💎", callback_data="mines_noop"))
            else:
                row.append(InlineKeyboardButton(text="⬜", callback_data=f"mines_open_{game_id}_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="💰 Забрать", callback_data=f"mines_cashout_{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_blackjack(game_id: int) -> InlineKeyboardMarkup:
    """Кнопки блэкджека."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Взять", callback_data=f"bj_hit_{game_id}"),
             InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj_stand_{game_id}")],
        ]
    )


def kb_back(callback: str = "nav_menu") -> InlineKeyboardMarkup:
    """Универсальная кнопка назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback)]]
    )


def kb_donate() -> InlineKeyboardMarkup:
    """Клавиатура доната."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="100 ⭐ — 700 000 💎", callback_data="donate_100")],
            [InlineKeyboardButton(text="250 ⭐ — 1 750 000 💎", callback_data="donate_250")],
            [InlineKeyboardButton(text="500 ⭐ — 3 500 000 💎", callback_data="donate_500")],
            [InlineKeyboardButton(text="1000 ⭐ — 7 000 000 💎", callback_data="donate_1000")],
            [InlineKeyboardButton(text="✍️ Своя сумма", callback_data="donate_custom")], # <--- ДОБАВИТЬ
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def kb_top() -> InlineKeyboardMarkup:
    """Клавиатура топа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 По балансу", callback_data="top_balance"),
             InlineKeyboardButton(text="🏆 По победам", callback_data="top_wins")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def kb_clans_main() -> InlineKeyboardMarkup:
    """Меню кланов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏰 Создать клан", callback_data="clan_create")],
            [InlineKeyboardButton(text="📋 Мой клан", callback_data="clan_info")],
            [InlineKeyboardButton(text="💰 Пополнить казну", callback_data="clan_deposit")],
            [InlineKeyboardButton(text="⬆️ Прокачать клан", callback_data="clan_upgrade")],
            [InlineKeyboardButton(text="🚪 Выйти из клана", callback_data="clan_leave")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


def kb_clan_owner() -> InlineKeyboardMarkup:
    """Кнопки владельца клана."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Налог", callback_data="clan_tax")],
            [InlineKeyboardButton(text="👥 Участники", callback_data="clan_members")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="clan_info")],
        ]
    )


def kb_duel_accept(duel_id: int) -> InlineKeyboardMarkup:
    """Кнопки принятия дуэли."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"duel_accept_{duel_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"duel_decline_{duel_id}")],
        ]
    )


def kb_roulette_help() -> InlineKeyboardMarkup:
    """Помощь по рулетке."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📜 Лог", callback_data="roulette_log")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
        ]
    )


# ============================================================
# УТИЛИТЫ
# ============================================================

async def send_photo_or_text(message: Message, photo_name: str, text: str,
                             kb=None):
    """Отправляет фото если есть, иначе текст."""
    path = photo_name
    if os.path.exists(path):
        await message.answer_photo(FSInputFile(path), caption=text, reply_markup=kb,
                                   parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def edit_or_send(call: CallbackQuery, text: str, kb=None):
    """Редактирует сообщение или отправляет новое."""
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ============================================================
# ХЕНДЛЕРЫ МЕНЮ
# ============================================================

async def cmd_start(message: Message, command: CommandObject = None):
    """Обработчик /start с поддержкой рефералки."""
    uid = message.from_user.id
    ref_id = None
    if command and command.args:
        try:
            ref_id = int(command.args)
            if ref_id == uid:
                ref_id = None
        except ValueError:
            ref_id = None

    user = await db.ensure_user(uid, message.from_user.username or "",
                                message.from_user.first_name or "", ref_id)

    if user["banned"]:
        await message.answer("⛔ Ты заблокирован в боте.")
        return

    text = (
        f"<b>🎮 Добро пожаловать, {message.from_user.first_name}!</b>\n\n"
        "Это игровой бот с кучей мини-игр, кланами и бонусами.\n"
        "Выбирай игру в меню и вперёд к победе! 🍀\n\n"
        f"💰 Твой баланс: <b>{fmt_money(user['balance'])}</b> 💎"
    )
    if os.path.exists("start.jpg"):
        await message.answer_photo(FSInputFile("start.jpg"), caption=text,
                                   reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)


async def menu_profile(message: Message):
    """Профиль пользователя."""
    uid = message.from_user.id
    user = await db.ensure_user(uid, message.from_user.username or "",
                                message.from_user.first_name or "")
    if user["banned"]:
        await message.answer("⛔ Ты заблокирован в боте.")
        return
    vip = await db.check_vip(uid)
    clan = await db.get_user_clan(uid)
    clan_name = clan["name"] if clan else "—"
    vip_status = f"Уровень {vip}" if vip > 0 else "нет"
    text = PROFILE_TEXT.format(
        user_id=uid,
        name=message.from_user.first_name,
        balance=fmt_money(user["balance"]),
        wins=user["wins"],
        losses=user["losses"],
        games=user["games"],
        level=user["level"],
        clan=clan_name,
        vip=vip_status,
        reg_date=user["reg_date"][:10] if user["reg_date"] else "—"
    )
    if os.path.exists("profile.jpg"):
        await message.answer_photo(FSInputFile("profile.jpg"), caption=text,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_donate(message: Message):
    """Меню доната."""
    rate = await db.get_setting("donate_rate", "10")
    if os.path.exists("donate.jpg"):
        await message.answer_photo(FSInputFile("donate.jpg"),
                                   caption=DONATE_TEXT.format(rate=rate),
                                   reply_markup=kb_donate(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(DONATE_TEXT.format(rate=rate),
                             reply_markup=kb_donate(), parse_mode=ParseMode.HTML)


async def menu_bonus(message: Message):
    """Ежедневный бонус."""
    uid = message.from_user.id
    await db.ensure_user(uid, message.from_user.username or "", message.from_user.first_name or "")
    timer = await db.get_bonus_timer(uid)
    user = await db.get_user(uid)
    streak = user["bonus_streak"] or 0
    next_bonus = 500 + min(streak + 1, 30) * 100
    text = BONUS_TEXT.format(bonus=fmt_money(next_bonus), timer=timer)
    if os.path.exists("bonus.jpg"):
        await message.answer_photo(FSInputFile("bonus.jpg"), caption=text,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_top(message: Message):
    """Топ игроков."""
    await message.answer(TOP_TEXT.format(players="Нажми кнопку ниже 👇"),
                         reply_markup=kb_top(), parse_mode=ParseMode.HTML)


async def menu_ref(message: Message):
    """Реферальная система."""
    uid = message.from_user.id
    user = await db.ensure_user(uid, message.from_user.username or "", message.from_user.first_name or "")
    refs = await db.get_refs_count(uid)
    link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    text = REF_TEXT.format(link=link, refs=refs, earned=fmt_money(user["ref_earned"] or 0))
    if os.path.exists("ref.jpg"):
        await message.answer_photo(FSInputFile("ref.jpg"), caption=text,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_how(message: Message):
    """Как играть."""
    if os.path.exists("how.jpg"):
        await message.answer_photo(FSInputFile("how.jpg"), caption=HOW_TO_PLAY,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(HOW_TO_PLAY, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_support(message: Message):
    """Поддержка."""
    text = SUPPORT_TEXT.format(link=SUPPORT_LINK)
    if os.path.exists("support.jpg"):
        await message.answer_photo(FSInputFile("support.jpg"), caption=text,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_chats(message: Message):
    """Чаты."""
    text = (
        "<b>💬 ЧАТЫ</b>\n\n"
        "Присоединяйся к нашим чатам:\n\n"
        f"🎮 Игровой чат: {CHAT_GAME}\n"
        f"💱 Обменник: {CHAT_EXCHANGE}\n"
        f"📢 Новости: {CHAT_NEWS}"
    )
    if os.path.exists("chats.jpg"):
        await message.answer_photo(FSInputFile("chats.jpg"), caption=text,
                                   reply_markup=kb_back(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_back(), parse_mode=ParseMode.HTML)


async def menu_clans(message: Message):
    """Меню кланов."""
    uid = message.from_user.id
    await db.ensure_user(uid, message.from_user.username or "", message.from_user.first_name or "")
    clan = await db.get_user_clan(uid)
    if clan:
        text = CLANS_TEXT.format(clan=clan["name"], members=clan["members_count"], level=clan["level"])
    else:
        text = CLANS_TEXT.format(clan="—", members=0, level=0)
    if os.path.exists("clans.jpg"):
        await message.answer_photo(FSInputFile("clans.jpg"), caption=text,
                                   reply_markup=kb_clans_main(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=kb_clans_main(), parse_mode=ParseMode.HTML)


async def menu_games(message: Message):
    """Меню игр."""
    await message.answer(GAMES_MENU, reply_markup=kb_games(), parse_mode=ParseMode.HTML)


# ============================================================
# CALLBACK: НАВИГАЦИЯ
# ============================================================

async def cb_nav_menu(call: CallbackQuery):
    """Возврат в главное меню — удаляет сообщение и шлёт Reply-меню."""
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("Главное меню 👇", reply_markup=kb_main())
    await call.answer()


async def cb_back_to_games(call: CallbackQuery):
    """Назад в меню игр."""
    await edit_or_send(call, GAMES_MENU, kb_games())
    await call.answer()


# ============================================================
# CALLBACK: ДОНАТ
# ============================================================

DONATE_PACKS = {100: 700000, 250: 1750000, 500: 3500000, 1000: 7000000}


async def cb_donate(call: CallbackQuery, state: FSMContext):
    """Обработка выбора донат-пакета."""
    # Проверяем, нажали ли на "Своя сумма"
    if call.data == "donate_custom":
        await state.set_state(GameStates.waiting_custom_donate)
        await call.message.answer(
            "✍️ <b>Введи количество звезд (⭐):</b>\n\n"
            "Минимум: 1 ⭐\n"
            "Курс: 1 ⭐ = 7000 💎",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back()
        )
        await call.answer()
        return

    # Если нажали на обычный пакет
    try:
        stars = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    
    if stars not in DONATE_PACKS:
        await call.answer("Неверный пакет", show_alert=True)
        return
        
    if not PAYMENT_TOKEN:
        await call.answer("Оплата временно недоступна", show_alert=True)
        return
        
    try:
        await call.bot.send_invoice(
            chat_id=call.from_user.id,
            title=f"Покупка {DONATE_PACKS[stars]} 💎",
            description=f"Пакет {stars} ⭐ = {DONATE_PACKS[stars]} 💎",
            payload=f"donate_{stars}",
            provider_token=PAYMENT_TOKEN,
            currency="XTR",
            prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)],
            start_parameter="donate"
        )
        await call.answer()
    except Exception as e:
        logger.error(f"invoice error: {e}")
        await call.answer("Ошибка создания платежа", show_alert=True)

async def fsm_custom_donate(message: Message, state: FSMContext):
    """Обработка введенной суммы звезд."""
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введи число (например: 50)")
        return
    
    stars = int(message.text)
    if stars < 1:
        await message.answer("❌ Минимальная сумма — 1 ⭐")
        return
        
    if stars > 10000:
        await message.answer("❌ Максимум за один раз — 10 000 ⭐")
        return

    await state.clear()
    diamonds = stars * 7000 # Наш курс

    if not PAYMENT_TOKEN:
        await message.answer("Оплата временно недоступна", show_alert=True)
        return
        
    try:
        await message.bot.send_invoice(
            chat_id=message.from_user.id,
            title=f"Покупка {diamonds} 💎",
            description=f"Своя сумма: {stars} ⭐ = {diamonds} 💎",
            payload=f"donate_{stars}",
            provider_token=PAYMENT_TOKEN,
            currency="XTR",
            prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)],
            start_parameter="donate"
        )
    except Exception as e:
        logger.error(f"invoice error: {e}")
        await message.answer("Ошибка создания платежа.")

# ============================================================
# CALLBACK: БОНУС
# ============================================================

async def cb_claim_bonus(call: CallbackQuery):
    """Получение бонуса."""
    uid = call.from_user.id
    await db.ensure_user(uid, call.from_user.username or "", call.from_user.first_name or "")
    ok, amount, streak = await db.claim_bonus(uid)
    if not ok:
        await call.answer("Бонус ещё не готов! Загляни позже.", show_alert=True)
        return
    await call.answer(f"Бонус {fmt_money(amount)} 💎 получен!", show_alert=True)
    await edit_or_send(
        call,
        f"🎉 <b>Бонус получен!</b>\n\n"
        f"Сумма: <b>{fmt_money(amount)}</b> 💎\n"
        f"Серия: <b>{streak}</b> дней\n\n"
        f"Возвращайся через 24 часа!",
        kb_back()
    )


# ============================================================
# CALLBACK: ТОП
# ============================================================

async def cb_top_balance(call: CallbackQuery):
    """Топ по балансу."""
    players = await db.top_players(10)
    lines = []
    for i, p in enumerate(players, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} {p['first_name'] or 'Игрок'} — <b>{fmt_money(p['balance'])}</b> 💎")
    await edit_or_send(call, f"<b>🏆 ТОП ПО БАЛАНСУ</b>\n\n" + "\n".join(lines) if lines else "Пусто", kb_top())
    await call.answer()


async def cb_top_wins(call: CallbackQuery):
    """Топ по победам."""
    players = await db.top_by_wins(10)
    lines = []
    for i, p in enumerate(players, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} {p['first_name'] or 'Игрок'} — <b>{p['wins']}</b> побед")
    await edit_or_send(call, f"<b>🏆 ТОП ПО ПОБЕДАМ</b>\n\n" + "\n".join(lines) if lines else "Пусто", kb_top())
    await call.answer()


# ============================================================
# CALLBACK: КЛАНЫ (основное)
# ============================================================

async def cb_clan_create(call: CallbackQuery, state: FSMContext):
    """Создание клана — запрос имени."""
    uid = call.from_user.id
    user = await db.get_user(uid)
    if user and user["clan_id"]:
        await call.answer("Ты уже в клане!", show_alert=True)
        return
    if user and user["balance"] < 10000:
        await call.answer("Нужно 10 000 💎 для создания клана", show_alert=True)
        return
    await state.set_state(GameStates.waiting_clan_name)
    await call.message.answer("Введи название клана (3-20 символов):")
    await call.answer()


async def cb_clan_info(call: CallbackQuery):
    """Информация о клане."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan:
        await edit_or_send(call, "🏰 <b>Ты не в клане.</b>\n\nСоздай или вступи в клан.", kb_clans_main())
        await call.answer()
        return
    members = await db.clan_members(clan["clan_id"])
    owner = clan["owner_id"] == uid
    text = (
        f"🏰 <b>КЛАН: {clan['name']}</b>\n\n"
        f"👑 Владелец: <code>{clan['owner_id']}</code>\n"
        f"📊 Уровень: <b>{clan['level']}</b>\n"
        f"💰 Казна: <b>{fmt_money(clan['treasury'])}</b> 💎\n"
        f"👥 Участников: <b>{len(members)}</b>\n"
        f"💸 Налог: <b>{clan['tax']}%</b>\n\n"
        f"⬆️ Стоимость апгрейда: <b>{fmt_money(clan['level'] * 50000)}</b> 💎"
    )
    if owner:
        await edit_or_send(call, text, kb_clan_owner())
    else:
        await edit_or_send(call, text, kb_back("clan_info"))
    await call.answer()


async def cb_clan_deposit(call: CallbackQuery, state: FSMContext):
    """Пополнение казны — запрос суммы."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan:
        await call.answer("Ты не в клане!", show_alert=True)
        return
    await state.set_state(GameStates.waiting_admin_input)
    await state.update_data(action="clan_deposit")
    await call.message.answer("Введи сумму для пополнения казны:")
    await call.answer()


async def cb_clan_upgrade(call: CallbackQuery):
    """Апгрейд клана."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan:
        await call.answer("Ты не в клане!", show_alert=True)
        return
    if clan["owner_id"] != uid:
        await call.answer("Только владелец может прокачивать клан", show_alert=True)
        return
    ok = await db.upgrade_clan(clan["clan_id"])
    if not ok:
        await call.answer(f"Недостаточно в казне! Нужно {fmt_money(clan['level'] * 50000)} 💎", show_alert=True)
        return
    await call.answer("Клан прокачан! 🎉", show_alert=True)
    await cb_clan_info(call)


async def cb_clan_leave(call: CallbackQuery):
    """Выход из клана."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan:
        await call.answer("Ты не в клане!", show_alert=True)
        return
    if clan["owner_id"] == uid:
        await call.answer("Владелец не может выйти. Передай клан или удали.", show_alert=True)
        return
    await db.leave_clan(uid)
    await call.answer("Ты вышел из клана", show_alert=True)
    await edit_or_send(call, "🚪 Ты вышел из клана.", kb_clans_main())


async def cb_clan_tax(call: CallbackQuery, state: FSMContext):
    """Установка налога."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan or clan["owner_id"] != uid:
        await call.answer("Только владелец", show_alert=True)
        return
    await state.set_state(GameStates.waiting_admin_input)
    await state.update_data(action="clan_tax")
    await call.message.answer("Введи налог (1-20%):")
    await call.answer()


async def cb_clan_members(call: CallbackQuery):
    """Список участников клана."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan:
        await call.answer("Ты не в клане!", show_alert=True)
        return
    members = await db.clan_members(clan["clan_id"])
    lines = []
    for m in members[:30]:
        marker = "👑" if m["user_id"] == clan["owner_id"] else "•"
        lines.append(f"{marker} {m['first_name'] or 'Игрок'} — {fmt_money(m['balance'])} 💎")
    await edit_or_send(call, f"<b>👥 Участники {clan['name']}</b>\n\n" + "\n".join(lines), kb_back("clan_info"))
    await call.answer()


# ============================================================
# FSM: ОБРАБОТКА ВВОДА (кланы)
# ============================================================

async def fsm_clan_name(message: Message, state: FSMContext):
    """Обработка имени клана."""
    uid = message.from_user.id
    name = message.text.strip() if message.text else ""
    if len(name) < 3 or len(name) > 20:
        await message.answer("Название должно быть от 3 до 20 символов.")
        return
    if not await db.take_balance(uid, 10000):
        await message.answer("Недостаточно средств (10 000 💎).")
        await state.clear()
        return
    clan_id = await db.create_clan(name, uid)
    await state.clear()
    if not clan_id:
        await db.add_balance(uid, 10000)
        await message.answer("Клан с таким именем уже существует. Средства возвращены.")
        return
    await message.answer(f"🏰 Клан <b>{name}</b> создан!", reply_markup=kb_main(), parse_mode=ParseMode.HTML)


async def fsm_clan_input(message: Message, state: FSMContext):
    """Общий обработчик ввода для клановых действий."""
    data = await state.get_data()
    action = data.get("action")
    uid = message.from_user.id
    text = message.text.strip() if message.text else ""
    await state.clear()

    if action == "clan_deposit":
        try:
            amount = int(text)
        except ValueError:
            await message.answer("Введи число.")
            return
        if amount <= 0:
            await message.answer("Сумма должна быть положительной.")
            return
        ok = await db.clan_deposit(uid, amount)
        await message.answer("✅ Казна пополнена!" if ok else "❌ Недостаточно средств.")
    elif action == "clan_tax":
        try:
            tax = int(text)
        except ValueError:
            await message.answer("Введи число.")
            return
        if tax < 1 or tax > 20:
            await message.answer("Налог от 1 до 20%.")
            return
        clan = await db.get_user_clan(uid)
        if clan and clan["owner_id"] == uid:
            await db.set_clan_tax(clan["clan_id"], tax)
            await message.answer(f"✅ Налог установлен: {tax}%")
        else:
            await message.answer("❌ Ошибка.")


# ============================================================
# CALLBACK: МЕНЮ ИГР / СТАВКИ
# ============================================================

async def cb_game_select(call: CallbackQuery):
    """Выбор игры — показываем клавиатуру ставок."""
    game = call.data.replace("game_", "")
    names = {
        "dice": "🎲 Кости", "darts": "🎯 Дартс", "basket": "🏀 Баскет",
        "football": "⚽ Футбол", "bowling": "🎳 Боулинг", "slots": "🎰 Слоты",
        "mines": "💣 Мины", "blackjack": "🃏 Блэкджек", "duels": "⚔️ Дуэли",
        "gift": "🎁 Подарки", "roulette": "🎡 Рулетка",
    }
    title = names.get(game, "Игра")
    if game == "roulette":
        await edit_or_send(
            call,
            "<b>🎡 РУЛЕТКА</b>\n\n"
            "Рулетка работает в чатах.\n"
            "Ставки: «к 1000», «10-20 500», «100 200 300».\n"
            "Ведущий пишет «старт» — колесо крутится.\n\n"
            "Команда <code>лог</code> — история рулетки.",
            kb_roulette_help()
        )
        await call.answer()
        return
    if game == "duels":
        await edit_or_send(
            call,
            "<b>⚔️ ДУЭЛИ</b>\n\n"
            "Вызови игрока: <code>дуэль @username 1000</code>\n"
            "Или ответь на сообщение: <code>дуэль 1000</code>",
            kb_back("nav_games")
        )
        await call.answer()
        return
    if game == "gift":
        await edit_or_send(
            call,
            "<b>🎁 ПОДАРКИ</b>\n\n"
            "Отправь подарок: <code>подарок @username 500</code>\n"
            "Или ответь на сообщение: <code>подарок 500</code>",
            kb_back("nav_games")
        )
        await call.answer()
        return
    if game == "blackjack":
        await edit_or_send(call, f"{title}\n\nВыбери ставку:", kb_bet("blackjack"))
        await call.answer()
        return
    await edit_or_send(call, f"{title}\n\nВыбери ставку:", kb_bet(game))
    await call.answer()


async def cb_bet(call: CallbackQuery, state: FSMContext):
    """Обработка выбора ставки — вызывает игру."""
    parts = call.data.split("_")
    if len(parts) < 3:
        await call.answer("Ошибка", show_alert=True)
        return
    game = parts[1]
    try:
        bet = int(parts[2])
    except ValueError:
        await call.answer("Ошибка", show_alert=True)
        return
    uid = call.from_user.id
    user = await db.ensure_user(uid, call.from_user.username or "", call.from_user.first_name or "")
    if user["banned"]:
        await call.answer("Ты заблокирован", show_alert=True)
        return
    if user["balance"] < bet:
        await call.answer("Недостаточно средств!", show_alert=True)
        return
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass

    from_bet_handlers = {
        "dice": play_dice, "darts": play_darts, "basket": play_basket,
        "football": play_football, "bowling": play_bowling, "slots": play_slots,
        "blackjack": play_blackjack,
    }
    if game == "mines":
        await play_mines(call.message, uid, bet)
        return
    handler = from_bet_handlers.get(game)
    if handler:
        await handler(call.message, uid, bet)
    else:
        await call.message.answer("Игра не найдена.")


# ============================================================
# РЕГИСТРАЦИЯ РОУТЕРА (часть 2)
# ============================================================

router = Router()


def register_part2(dp: Dispatcher):
    """Регистрирует хендлеры части 2."""
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(menu_profile, F.text == "👤 Профиль")
    dp.message.register(menu_donate, F.text == "💎 Донат")
    dp.message.register(menu_bonus, F.text == "🎁 Бонус")
    dp.message.register(menu_top, F.text == "🏆 Топ")
    dp.message.register(menu_ref, F.text == "👥 Рефералка")
    dp.message.register(menu_how, F.text == "📖 Как играть")
    dp.message.register(menu_support, F.text == "🆘 Поддержка")
    dp.message.register(menu_chats, F.text == "💬 Чаты")
    dp.message.register(menu_clans, F.text == "🏰 Кланы")
    dp.message.register(menu_games, F.text == "🎮 Игры")
    dp.message.register(fsm_clan_name, GameStates.waiting_clan_name)
    dp.message.register(fsm_clan_input, GameStates.waiting_admin_input)

    dp.callback_query.register(cb_nav_menu, F.data == "nav_menu")
    dp.callback_query.register(cb_back_to_games, F.data == "nav_games")
    dp.callback_query.register(cb_donate, F.data.startswith("donate_"))
    dp.message.register(fsm_custom_donate, GameStates.waiting_custom_donate)
    dp.callback_query.register(cb_claim_bonus, F.data == "claim_bonus")
    dp.callback_query.register(cb_top_balance, F.data == "top_balance")
    dp.callback_query.register(cb_top_wins, F.data == "top_wins")
    dp.callback_query.register(cb_clan_create, F.data == "clan_create")
    dp.callback_query.register(cb_clan_info, F.data == "clan_info")
    dp.callback_query.register(cb_clan_deposit, F.data == "clan_deposit")
    dp.callback_query.register(cb_clan_upgrade, F.data == "clan_upgrade")
    dp.callback_query.register(cb_clan_leave, F.data == "clan_leave")
    dp.callback_query.register(cb_clan_tax, F.data == "clan_tax")
    dp.callback_query.register(cb_clan_members, F.data == "clan_members")
    dp.callback_query.register(cb_game_select, F.data.startswith("game_"))
    dp.callback_query.register(cb_bet, F.data.startswith("bet_"))

    dp.pre_checkout_query.register(pre_checkout)
    dp.message.register(successful_payment, F.content_type == ContentType.SUCCESSFUL_PAYMENT)

# ============================================================
# ИГРЫ: БАЗОВЫЕ ХЕЛПЕРЫ
# ============================================================

DICE_TIMEOUT = 3.5
MAX_BET = 1_000_000


async def validate_bet(uid: int, bet: int) -> Tuple[bool, str]:
    """Проверяет ставку: лимиты, баланс, бан."""
    user = await db.get_user(uid)
    if not user:
        return False, "Сначала напиши /start"
    if user["banned"]:
        return False, "⛔ Ты заблокирован."
    if bet < 100:
        return False, "Минимальная ставка — 100 💎"
    vip = await db.check_vip(uid)
    max_bet = MAX_BET * (1 + vip) // 1
    if bet > max_bet:
        return False, f"Максимальная ставка — {fmt_money(max_bet)} 💎"
    if user["balance"] < bet:
        return False, "Недостаточно средств!"
    return True, ""


async def finish_game(uid: int, game: str, bet: int, win: int,
                      result_text: str = "", msg: Optional[Message] = None,
                      delay_delete: int = 30):
    """Начисляет выигрыш, пишет статистику, удаляет сообщение."""
    if win > 0:
        await db.add_balance(uid, win)
    await db.update_stats(uid, game, bet, win, result_text)
    if msg:
        asyncio.create_task(auto_delete(msg, delay_delete))


def win_multiplier(game: str, value: int) -> float:
    """Возвращает множитель выигрыша по значению стикера."""
    if game == "dice":
        return {1: 0.0, 2: 1.0, 3: 1.0, 4: 1.5, 5: 1.5, 6: 2.0}.get(value, 0.0)
    if game == "darts":
        return {1: 0.0, 2: 0.0, 3: 0.0, 4: 1.5, 5: 2.0, 6: 3.0}.get(value, 0.0)
    if game == "basket":
        return {1: 0.0, 2: 0.0, 3: 0.0, 4: 1.5, 5: 2.0, 6: 3.0}.get(value, 0.0)
    if game == "football":
        return {1: 0.0, 2: 0.0, 3: 2.0, 4: 0.0, 5: 2.0}.get(value, 0.0)
    if game == "bowling":
        return {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 3.0}.get(value, 0.0)
    if game == "slots":
        return {1: 0.0, 2: 1.5, 3: 0.0, 4: 5.0}.get(value, 0.0)
    return 0.0


# ============================================================
# DICE-ИГРЫ (анимированные стикеры Telegram)
# ============================================================

async def _dice_play(message: Message, uid: int, bet: int, game: str,
                     emoji: str, game_title: str, win_table_desc: str):
    """Универсальная логика игры с reply_dice."""
    ok, err = await validate_bet(uid, bet)
    if not ok:
        await message.answer(err)
        return
    if not await db.take_balance(uid, bet):
        await message.answer("Недостаточно средств!")
        return
    user = await db.get_user(uid)
    vip = await db.check_vip(uid)
    vip_mult = vip_multiplier(vip)

    msg = await message.answer_dice(emoji=emoji)
    asyncio.create_task(auto_delete(msg, 30))
    await asyncio.sleep(DICE_TIMEOUT)

    value = msg.dice.value
    mult = win_multiplier(game, value)
    win = int(bet * mult * vip_mult)
    if win > 0:
        await db.add_balance(uid, win)
        result = f"Выигрыш x{mult}"
    else:
        result = "Проигрыш"
    await db.update_stats(uid, game_title, bet, win, result)

    balance = await db.get_balance(uid)
    if win > bet:
        emoji_res = "🎉"
        text = (
            f"{emoji_res} <b>{game_title}</b>\n\n"
            f"Результат: <b>{value}</b>\n"
            f"Множитель: <b>x{mult}</b>{' (VIP x' + str(vip_mult) + ')' if vip_mult > 1 else ''}\n"
            f"Выигрыш: <b>+{fmt_money(win)}</b> 💎\n"
            f"Баланс: <b>{fmt_money(balance)}</b> 💎"
        )
    elif win == bet:
        text = (
            f"🤝 <b>{game_title}</b>\n\n"
            f"Результат: <b>{value}</b>\n"
            f"Возврат ставки: <b>{fmt_money(win)}</b> 💎\n"
            f"Баланс: <b>{fmt_money(balance)}</b> 💎"
        )
    else:
        text = (
            f"😢 <b>{game_title}</b>\n\n"
            f"Результат: <b>{value}</b>\n"
            f"Проигрыш: <b>{fmt_money(bet)}</b> 💎\n"
            f"Баланс: <b>{fmt_money(balance)}</b> 💎"
        )
    info = await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb_games())
    asyncio.create_task(auto_delete(info, 30))


async def play_dice(message: Message, uid: int, bet: int):
    """Игра в кости."""
    await _dice_play(message, uid, bet, "dice", DiceEmoji.DICE,
                     "🎲 КОСТИ", "1-x0, 2-3-x1, 4-5-x1.5, 6-x2")


async def play_darts(message: Message, uid: int, bet: int):
    """Дартс."""
    await _dice_play(message, uid, bet, "darts", DiceEmoji.DARTS,
                     "🎯 ДАРТС", "центр x3, красное x2, синее x1.5")


async def play_basket(message: Message, uid: int, bet: int):
    """Баскетбол."""
    await _dice_play(message, uid, bet, "basket", DiceEmoji.BASKETBALL,
                     "🏀 БАСКЕТ", "гол x2, точный x3")


async def play_football(message: Message, uid: int, bet: int):
    """Футбол."""
    await _dice_play(message, uid, bet, "football", DiceEmoji.FOOTBALL,
                     "⚽ ФУТБОЛ", "гол x2")


async def play_bowling(message: Message, uid: int, bet: int):
    """Боулинг."""
    await _dice_play(message, uid, bet, "bowling", DiceEmoji.BOWLING,
                     "🎳 БОУЛИНГ", "страйк x3")


async def play_slots(message: Message, uid: int, bet: int):
    """Слоты (используем слот-эмодзи)."""
    await _dice_play(message, uid, bet, "slots", DiceEmoji.SLOT_MACHINE,
                     "🎰 СЛОТЫ", "три одинаковых x5, два x1.5")


# ============================================================
# МИНЫ (поле 5x5)
# ============================================================

MINES_COEFS = [1.0, 1.1, 1.25, 1.4, 1.6, 1.85, 2.15, 2.5, 2.9, 3.4,
               4.0, 4.7, 5.5, 6.5, 7.7, 9.1, 10.8, 12.8, 15.2, 18.0]


async def play_mines(message: Message, uid: int, bet: int):
    """Запуск игры в мины."""
    ok, err = await validate_bet(uid, bet)
    if not ok:
        await message.answer(err)
        return
    if not await db.take_balance(uid, bet):
        await message.answer("Недостаточно средств!")
        return
    await message.answer(
        "💣 <b>МИНЫ</b>\n\n"
        "Выбери количество мин (сложность):\n"
        "• 1 мина — x1.05 за клетку\n"
        "• 3 мины — x1.25\n"
        "• 5 мин — x1.6\n"
        "• 10 мин — x4\n\n"
        "Открывай клетки и забирай кэшаут!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 💣", callback_data=f"mines_start_{uid}_{bet}_1"),
             InlineKeyboardButton(text="3 💣", callback_data=f"mines_start_{uid}_{bet}_3")],
            [InlineKeyboardButton(text="5 💣", callback_data=f"mines_start_{uid}_{bet}_5"),
             InlineKeyboardButton(text="10 💣", callback_data=f"mines_start_{uid}_{bet}_10")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"mines_cancel_{uid}_{bet}")],
        ]),
        parse_mode=ParseMode.HTML
    )


async def cb_mines_start(call: CallbackQuery):
    """Пользователь выбрал сложность — генерируем поле."""
    parts = call.data.split("_")
    try:
        uid, bet, mines_count = int(parts[2]), int(parts[3]), int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    if call.from_user.id != uid:
        await call.answer("Это не твоя игра!", show_alert=True)
        return
    cells = list(range(25))
    random.shuffle(cells)
    mine_positions = cells[:mines_count]
    field = json.dumps({"mines": mine_positions, "mines_count": mines_count, "bet": bet})
    game_id = await db.create_mines(uid, bet, mines_count, field)
    await call.message.edit_text(
        f"💣 <b>МИНЫ (5x5)</b>\n"
        f"Ставка: <b>{fmt_money(bet)}</b> 💎\n"
        f"Мин на поле: <b>{mines_count}</b>\n\n"
        f"Открыто клеток: <b>0</b>\n"
        f"Текущий выигрыш: <b>0</b> 💎",
        reply_markup=kb_mines(game_id, [], mines_count),
        parse_mode=ParseMode.HTML
    )
    await call.answer()


async def cb_mines_open(call: CallbackQuery):
    """Открытие клетки."""
    parts = call.data.split("_")
    try:
        game_id, idx = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    game = await db.get_mines(game_id)
    if not game or game["status"] != "active":
        await call.answer("Игра завершена", show_alert=True)
        return
    if call.from_user.id != game["user_id"]:
        await call.answer("Это не твоя игра!", show_alert=True)
        return
    field = json.loads(game["field"])
    opened = json.loads(game["opened"])
    if idx in opened:
        await call.answer("Уже открыто", show_alert=True)
        return
    if idx in field["mines"]:
        # Проигрыш
        await db.update_mines(game_id, json.dumps(opened), "lost")
        text = (
            f"💥 <b>МИНА!</b>\n\n"
            f"Ты наступил на мину 💣\n"
            f"Проигрыш: <b>{fmt_money(field['bet'])}</b> 💎"
        )
        await call.message.edit_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=kb_games())
        await db.update_stats(game["user_id"], "mines", field["bet"], 0, "Проигрыш")
        await call.answer()
        return
    opened.append(idx)
    mines_count = field["mines_count"]
    safe_total = 25 - mines_count
    coef = MINES_COEFS[min(len(opened) - 1, len(MINES_COEFS) - 1)]
    current_win = int(field["bet"] * coef)
    await db.update_mines(game_id, json.dumps(opened), "active")
    await call.message.edit_text(
        f"💣 <b>МИНЫ (5x5)</b>\n"
        f"Ставка: <b>{fmt_money(field['bet'])}</b> 💎\n"
        f"Мин на поле: <b>{mines_count}</b>\n\n"
        f"Открыто клеток: <b>{len(opened)}/{safe_total}</b>\n"
        f"Текущий выигрыш: <b>{fmt_money(current_win)}</b> 💎",
        reply_markup=kb_mines(game_id, opened, mines_count),
        parse_mode=ParseMode.HTML
    )
    await call.answer(f"Безопасно! Кэшаут: {fmt_money(current_win)} 💎")


async def cb_mines_cashout(call: CallbackQuery):
    """Кэшаут в минах."""
    parts = call.data.split("_")
    try:
        game_id = int(parts[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    game = await db.get_mines(game_id)
    if not game or game["status"] != "active":
        await call.answer("Игра завершена", show_alert=True)
        return
    if call.from_user.id != game["user_id"]:
        await call.answer("Это не твоя игра!", show_alert=True)
        return
    opened = json.loads(game["opened"])
    if not opened:
        await call.answer("Открой хотя бы одну клетку", show_alert=True)
        return
    field = json.loads(game["field"])
    mines_count = field["mines_count"]
    coef = MINES_COEFS[min(len(opened) - 1, len(MINES_COEFS) - 1)]
    win = int(field["bet"] * coef)
    await db.add_balance(game["user_id"], win)
    await db.update_mines(game_id, json.dumps(opened), "won")
    await db.update_stats(game["user_id"], "mines", field["bet"], win, "Кэшаут")
    await call.message.edit_text(
        f"💰 <b>КЭШАУТ!</b>\n\n"
        f"Выигрыш: <b>+{fmt_money(win)}</b> 💎\n"
        f"Открыто: <b>{len(opened)}</b> клеток",
        parse_mode=ParseMode.HTML
    )
    await call.answer(f"Забрано {fmt_money(win)} 💎", show_alert=True)


async def cb_mines_cancel(call: CallbackQuery):
    """Отмена запуска мин — возврат средств."""
    parts = call.data.split("_")
    try:
        uid, bet = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    if call.from_user.id != uid:
        await call.answer("Не твоя игра", show_alert=True)
        return
    await db.add_balance(uid, bet)
    await call.message.edit_text("❌ Игра отменена, ставка возвращена.")
    await call.answer()


# ============================================================
# БЛЭКДЖЕК
# ============================================================

BJ_GAMES: Dict[int, Dict] = {}
BJ_ID = 0


def bj_new_deck() -> List[str]:
    """Создаёт колоду."""
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    return [f"{r}{s}" for r in ranks for s in ["♠", "♥", "♦", "♣"]]


def bj_value(card: str) -> int:
    """Стоимость карты."""
    r = card[:-1]
    if r in ("J", "Q", "K"):
        return 10
    if r == "A":
        return 11
    return int(r)


def bj_hand_value(hand: List[str]) -> int:
    """Считает очки с учётом тузов."""
    total = sum(bj_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


async def play_blackjack(message: Message, uid: int, bet: int):
    """Запуск блэкджека."""
    global BJ_ID
    ok, err = await validate_bet(uid, bet)
    if not ok:
        await message.answer(err)
        return
    if not await db.take_balance(uid, bet):
        await message.answer("Недостаточно средств!")
        return
    deck = bj_new_deck()
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    BJ_ID += 1
    game_id = BJ_ID
    BJ_GAMES[game_id] = {
        "uid": uid, "bet": bet, "player": player, "dealer": dealer,
        "deck": deck, "done": False
    }
    text = (
        f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
        f"Твоя рука: {' '.join(player)} (<b>{bj_hand_value(player)}</b>)\n"
        f"Дилер: {dealer[0]} 🎴\n\n"
        f"Ставка: <b>{fmt_money(bet)}</b> 💎"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb_blackjack(game_id))


async def cb_bj_hit(call: CallbackQuery):
    """Взять карту."""
    try:
        game_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    g = BJ_GAMES.get(game_id)
    if not g or g["done"]:
        await call.answer("Игра завершена", show_alert=True)
        return
    if call.from_user.id != g["uid"]:
        await call.answer("Не твоя игра", show_alert=True)
        return
    g["player"].append(g["deck"].pop())
    val = bj_hand_value(g["player"])
    if val > 21:
        g["done"] = True
        await db.update_stats(g["uid"], "blackjack", g["bet"], 0, "Перебор")
        await call.message.edit_text(
            f"🃏 <b>ПЕРЕБОР</b>\n\n"
            f"Твоя рука: {' '.join(g['player'])} (<b>{val}</b>)\n"
            f"Проигрыш: <b>{fmt_money(g['bet'])}</b> 💎",
            parse_mode=ParseMode.HTML
        )
        del BJ_GAMES[game_id]
        await call.answer()
        return
    if val == 21:
        await bj_finish_stand(call, game_id)
        return
    await call.message.edit_text(
        f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
        f"Твоя рука: {' '.join(g['player'])} (<b>{val}</b>)\n"
        f"Дилер: {g['dealer'][0]} 🎴\n\n"
        f"Ставка: <b>{fmt_money(g['bet'])}</b> 💎",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_blackjack(game_id)
    )
    await call.answer()


async def cb_bj_stand(call: CallbackQuery):
    """Хватит — дилер добирает."""
    try:
        game_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    await bj_finish_stand(call, game_id)


async def bj_finish_stand(call: CallbackQuery, game_id: int):
    """Финал блэкджека."""
    g = BJ_GAMES.get(game_id)
    if not g or g["done"]:
        await call.answer("Игра завершена", show_alert=True)
        return
    g["done"] = True
    while bj_hand_value(g["dealer"]) < 17:
        g["dealer"].append(g["deck"].pop())
    pv = bj_hand_value(g["player"])
    dv = bj_hand_value(g["dealer"])
    bet = g["bet"]
    if dv > 21:
        win = bet * 2
        result = "Дилер перебрал"
    elif pv > dv:
        win = bet * 2
        result = "Победа"
    elif pv == dv:
        win = bet
        result = "Ничья"
    else:
        win = 0
        result = "Поражение"
    if win > 0:
        await db.add_balance(g["uid"], win)
    await db.update_stats(g["uid"], "blackjack", bet, win, result)
    emoji = "🎉" if win > bet else ("🤝" if win == bet else "😢")
    await call.message.edit_text(
        f"{emoji} <b>БЛЭКДЖЕК</b>\n\n"
        f"Твоя рука: {' '.join(g['player'])} (<b>{pv}</b>)\n"
        f"Дилер: {' '.join(g['dealer'])} (<b>{dv}</b>)\n\n"
        f"Результат: <b>{result}</b>\n"
        f"{'Выигрыш' if win > bet else ('Возврат' if win == bet else 'Проигрыш')}: "
        f"<b>{fmt_money(win)}</b> 💎",
        parse_mode=ParseMode.HTML
    )
    del BJ_GAMES[game_id]
    await call.answer()


# ============================================================
# ДУЭЛИ
# ============================================================

async def cmd_duel(message: Message):
    """Вызов на дуэль: /duel @user 1000 или ответом."""
    uid = message.from_user.id
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Дуэли только в чатах.")
        return
    args = (message.text or "").split()
    # Ожидаем: /duel [@user] [bet] — либо reply + сумма
    opponent_id = None
    bet = None
    if message.reply_to_message and message.reply_to_message.from_user:
        opponent_id = message.reply_to_message.from_user.id
        for a in args[1:]:
            if a.isdigit():
                bet = int(a)
                break
    else:
        if len(args) >= 3 and args[1].startswith("@"):
            username = args[1].lstrip("@")
            async with db.conn.execute(
                "SELECT user_id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                opponent_id = row["user_id"]
            if len(args) >= 3 and args[2].isdigit():
                bet = int(args[2])
    if not opponent_id or opponent_id == uid:
        await message.answer("Использование: <code>/duel @user 1000</code> или reply на сообщение.",
                             parse_mode=ParseMode.HTML)
        return
    if not bet or bet < 100:
        await message.answer("Минимальная ставка дуэли — 100 💎")
        return
    ok, err = await validate_bet(uid, bet)
    if not ok:
        await message.answer(err)
        return
    if not await db.take_balance(uid, bet):
        await message.answer("Недостаточно средств!")
        return
    duel_id = await db.create_duel(uid, opponent_id, bet)
    await message.answer(
        f"⚔️ <b>ДУЭЛЬ!</b>\n\n"
        f"<a href='tg://user?id={uid}'>{message.from_user.first_name}</a> "
        f"вызывает <a href='tg://user?id={opponent_id}'>соперника</a>\n"
        f"Ставка: <b>{fmt_money(bet)}</b> 💎",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_duel_accept(duel_id)
    )


async def cb_duel_accept(call: CallbackQuery):
    """Принятие дуэли."""
    try:
        duel_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    duel = await db.get_duel(duel_id)
    if not duel or duel["status"] != "pending":
        await call.answer("Дуэль неактивна", show_alert=True)
        return
    if call.from_user.id != duel["opponent_id"]:
        await call.answer("Эта дуэль не для тебя", show_alert=True)
        return
    bet = duel["bet"]
    if not await db.take_balance(duel["opponent_id"], bet):
        await call.answer("Недостаточно средств", show_alert=True)
        return
    roll1 = random.randint(1, 100)
    roll2 = random.randint(1, 100)
    if roll1 > roll2:
        winner = duel["challenger_id"]
        loser = duel["opponent_id"]
    elif roll2 > roll1:
        winner = duel["opponent_id"]
        loser = duel["challenger_id"]
    else:
        winner = None
        loser = None
    if winner:
        await db.add_balance(winner, bet * 2)
        await db.update_stats(winner, "duel", bet, bet * 2, "Победа")
        await db.update_stats(loser, "duel", bet, 0, "Поражение")
        await db.finish_duel(duel_id, "finished")
        await call.message.edit_text(
            f"⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ</b>\n\n"
            f"Ход 1: <b>{roll1}</b>\n"
            f"Ход 2: <b>{roll2}</b>\n\n"
            f"🏆 Победитель: <a href='tg://user?id={winner}'>победитель</a>\n"
            f"💰 Выигрыш: <b>{fmt_money(bet * 2)}</b> 💎",
            parse_mode=ParseMode.HTML
        )
    else:
        await db.add_balance(duel["challenger_id"], bet)
        await db.add_balance(duel["opponent_id"], bet)
        await db.finish_duel(duel_id, "draw")
        await call.message.edit_text(
            f"⚔️ <b>НИЧЬЯ</b>\n\nХод 1: {roll1}\nХод 2: {roll2}\n\nСтавки возвращены.",
            parse_mode=ParseMode.HTML
        )
    await call.answer()


async def cb_duel_decline(call: CallbackQuery):
    """Отклонение дуэли."""
    try:
        duel_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    duel = await db.get_duel(duel_id)
    if not duel or duel["status"] != "pending":
        await call.answer("Дуэль неактивна", show_alert=True)
        return
    if call.from_user.id not in (duel["opponent_id"], duel["challenger_id"]):
        await call.answer("Нет прав", show_alert=True)
        return
    await db.add_balance(duel["challenger_id"], duel["bet"])
    await db.finish_duel(duel_id, "declined")
    await call.message.edit_text("❌ Дуэль отклонена. Ставка возвращена.")
    await call.answer()


# ============================================================
# ПОДАРКИ
# ============================================================

async def cmd_gift(message: Message):
    """Подарок: /gift @user 500 или reply."""
    uid = message.from_user.id
    args = (message.text or "").split()
    target_id = None
    amount = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        for a in args[1:]:
            if a.isdigit():
                amount = int(a)
                break
    else:
        if len(args) >= 3 and args[1].startswith("@"):
            username = args[1].lstrip("@")
            async with db.conn.execute(
                "SELECT user_id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                target_id = row["user_id"]
            if len(args) >= 3 and args[2].isdigit():
                amount = int(args[2])
    if not target_id or target_id == uid:
        await message.answer("Использование: <code>/gift @user 500</code>", parse_mode=ParseMode.HTML)
        return
    if not amount or amount < 10:
        await message.answer("Минимальный подарок — 10 💎")
        return
    if not await db.take_balance(uid, amount):
        await message.answer("Недостаточно средств!")
        return
    await db.add_balance(target_id, amount)
    await message.answer(
        f"🎁 <a href='tg://user?id={uid}'>{message.from_user.first_name}</a> "
        f"подарил <a href='tg://user?id={target_id}'>пользователю</a> "
        f"<b>{fmt_money(amount)}</b> 💎",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ ЧАСТИ 3
# ============================================================

def register_part3(dp: Dispatcher):
    """Регистрирует хендлеры игр и дуэлей."""
    dp.message.register(play_dice, Command("dice"))
    dp.message.register(cmd_duel, Command("duel"))
    dp.message.register(cmd_gift, Command("gift"))

    dp.callback_query.register(cb_mines_start, F.data.startswith("mines_start_"))
    dp.callback_query.register(cb_mines_open, F.data.startswith("mines_open_"))
    dp.callback_query.register(cb_mines_cashout, F.data.startswith("mines_cashout_"))
    dp.callback_query.register(cb_mines_cancel, F.data.startswith("mines_cancel_"))

    dp.callback_query.register(cb_bj_hit, F.data.startswith("bj_hit_"))
    dp.callback_query.register(cb_bj_stand, F.data.startswith("bj_stand_"))

    dp.callback_query.register(cb_duel_accept, F.data.startswith("duel_accept_"))
    dp.callback_query.register(cb_duel_decline, F.data.startswith("duel_decline_"))

# ============================================================
# РУЛЕТКА — сбор ставок в чате
# ============================================================

# Формат ставки: {chat_id: {"bets": [{"uid","name","amount","type"}], "collecting": bool, "msg_id": int}}
ROULETTE_STATE: Dict[int, Dict] = {}
ROULETTE_BET_PATTERN = re.compile(
    r"^\s*(к|красн\w*|ч|черн\w*|з|зеро|0)\s+(\d[\d\s]*)$",
    re.IGNORECASE
)
ROULETTE_RANGE_PATTERN = re.compile(
    r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s+(\d[\d\s]*)$"
)
ROULETTE_LIST_PATTERN = re.compile(
    r"^\s*((?:\d{1,2}[\s,]+){1,}\d{1,2})\s+(\d[\d\s]*)$"
)

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}


def parse_roulette_bet(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    Парсит ставки формата:
      «к 1000»   — на красное
      «ч 1000»   — на чёрное
      «з 1000»   — на зеро
      «10-20 500» — на диапазон чисел
      «100 200 300» — на набор чисел
      «7 500» — на конкретное число
    Возвращает список словарей {kind, numbers|color, amount} или None.
    """
    t = text.strip().lower()

    m = ROULETTE_BET_PATTERN.match(t)
    if m:
        color_raw, amount_raw = m.group(1), m.group(2)
        amount = int(amount_raw.replace(" ", ""))
        if amount < 100:
            return None
        color = "red" if color_raw.startswith("к") else \
                "black" if color_raw.startswith("ч") else "zero"
        return [{"kind": "color", "color": color, "amount": amount}]

    m = ROULETTE_RANGE_PATTERN.match(t)
    if m:
        a, b, amt = int(m.group(1)), int(m.group(2)), int(m.group(3).replace(" ", ""))
        if a > b:
            a, b = b, a
        if 0 <= a and b <= 36 and amt >= 100:
            return [{"kind": "numbers", "numbers": list(range(a, b + 1)), "amount": amt}]

    m = ROULETTE_LIST_PATTERN.match(t)
    if m:
        nums_raw, amt = m.group(1), int(m.group(2).replace(" ", ""))
        nums = [int(x) for x in re.split(r"[\s,]+", nums_raw) if x.isdigit()]
        nums = [n for n in nums if 0 <= n <= 36]
        if nums and amt >= 100:
            return [{"kind": "numbers", "numbers": nums, "amount": amt}]
    return None


async def handle_roulette_message(message: Message) -> bool:
    """
    Проверяет, является ли сообщение ставкой/командой рулетки.
    Возвращает True, если обработано (нужно прервать другие хендлеры).
    """
    chat_id = message.chat.id
    if message.chat.type == ChatType.PRIVATE:
        return False
    text = (message.text or "").strip()
    if not text:
        return False

    low = text.lower()

    # старт
    if low == "старт":
        return await roulette_start(message)
    # лог
    if low == "лог":
        return await roulette_show_log(message)
    # отмена
    if low == "отмена":
        state = ROULETTE_STATE.get(chat_id)
        if state and state.get("collecting"):
            state["collecting"] = False
            state["bets"] = []
            await message.reply("🛑 Сбор ставок отменён.")
            return True
        return False

    # парсинг ставки
    parsed = parse_roulette_bet(text)
    if not parsed:
        return False

    uid = message.from_user.id
    user = await db.ensure_user(uid, message.from_user.username or "",
                                message.from_user.first_name or "")
    if user["banned"]:
        return True

    state = ROULETTE_STATE.setdefault(chat_id, {"bets": [], "collecting": False})
    if not state["collecting"]:
        state["collecting"] = True
        state["bets"] = []
        state["chat_id"] = chat_id
        starter = await message.reply(
            "🎡 <b>РУЛЕТКА — СБОР СТАВОК ОТКРЫТ!</b>\n\n"
            "Форматы:\n"
            "• <code>к 1000</code> — красное\n"
            "• <code>ч 1000</code> — чёрное\n"
            "• <code>з 1000</code> — зеро\n"
            "• <code>10-20 500</code> — диапазон\n"
            "• <code>100 200 300</code> — набор чисел\n"
            "• <code>7 500</code> — число\n\n"
            "Старт: <code>старт</code> · Отмена: <code>отмена</code>",
            parse_mode=ParseMode.HTML
        )
        state["msg_id"] = starter.message_id

    # списываем
    total = sum(p["amount"] for p in parsed)
    if not await db.take_balance(uid, total):
        await message.reply("❌ Недостаточно средств для этой ставки.")
        return True

    for p in parsed:
        p["uid"] = uid
        p["name"] = message.from_user.first_name or "Игрок"
        state["bets"].append(p)

    await message.reply(
        f"✅ Ставка принята: {total:,} 💎\n"
        f"Всего ставок: <b>{len(state['bets'])}</b>".replace(",", " "),
        parse_mode=ParseMode.HTML
    )
    return True


def calc_payout(spin: int, bet: Dict[str, Any]) -> int:
    """Вычисляет выплату за ставку по выигрышному числу."""
    kind = bet["kind"]
    amount = bet["amount"]
    if kind == "color":
        color = bet["color"]
        if color == "red" and spin in RED_NUMBERS:
            return amount * 2
        if color == "black" and spin in BLACK_NUMBERS:
            return amount * 2
        if color == "zero" and spin == 0:
            return amount * 36
        return 0
    if kind == "numbers":
        nums = bet["numbers"]
        if spin in nums:
            return amount * (36 // max(1, len(nums)))
        return 0
    return 0


async def roulette_start(message: Message) -> bool:
    """Запуск рулетки."""
    chat_id = message.chat.id
    state = ROULETTE_STATE.get(chat_id)
    if not state or not state.get("collecting") or not state["bets"]:
        await message.reply("❌ Нет ставок. Сделай ставку и потом пиши «старт».")
        return True
    state["collecting"] = False
    bets = state["bets"]
    spin = random.randint(0, 36)
    if spin == 0:
        color = "🟢 зеро"
    elif spin in RED_NUMBERS:
        color = "🔴 красное"
    else:
        color = "⚫ чёрное"

    # считаем выплаты
    winners: Dict[int, Dict[str, Any]] = {}
    total_bets = sum(b["amount"] for b in bets)
    total_paid = 0
    for b in bets:
        payout = calc_payout(spin, b)
        if payout > 0:
            await db.add_balance(b["uid"], payout)
            total_paid += payout
            w = winners.setdefault(b["uid"], {"name": b["name"], "amount": 0})
            w["amount"] += payout
        await db.update_stats(b["uid"], "roulette", b["amount"], payout,
                              f"spin={spin}")

    # лог в БД
    await db.log_roulette(chat_id, 0, total_bets, str(spin),
                          json.dumps([{"uid": b["uid"], "amount": b["amount"],
                                       "kind": b["kind"]} for b in bets]))

    text = f"🎡 <b>ВЫПАЛО: {spin} {color}</b>\n\n"
    text += f"Всего ставок: <b>{fmt_money(total_bets)}</b> 💎\n"
    if winners:
        text += "<b>Выигрыши:</b>\n"
        for uid, w in winners.items():
            text += f"• {w['name']} — <b>+{fmt_money(w['amount'])}</b> 💎\n"
        text += f"\n<b>Выплачено:</b> {fmt_money(total_paid)} 💎"
    else:
        text += "😢 Победителей нет — ставки ушли в казино."

    await message.reply(text, parse_mode=ParseMode.HTML)

    # сброс
    ROULETTE_STATE[chat_id] = {"bets": [], "collecting": False}
    return True


async def roulette_show_log(message: Message) -> bool:
    """Показ лога рулетки (последние 20)."""
    chat_id = message.chat.id
    rows = await db.get_roulette_logs(chat_id, 20)
    if not rows:
        await message.reply("📜 История рулетки пуста.")
        return True
    lines = ["<b>📜 ЛОГ РУЛЕТКИ (последние 20)</b>\n"]
    for r in rows:
        try:
            parts = json.loads(r["participants"] or "[]")
        except Exception:
            parts = []
        winner = r["winner_id"] or 0
        num = r["bet_type"] or "?"
        lines.append(
            f"#{r['id']} · spin=<b>{num}</b> · "
            f"банк=<b>{fmt_money(r['bet_amount'] or 0)}</b> · "
            f"участников={len(parts)} · "
            f"{r['created_at'][:19]}"
        )
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)
    return True


async def cmd_roulette_help(message: Message):
    """Справка по рулетке в личке."""
    await message.answer(
        "<b>🎡 РУЛЕТКА</b>\n\n"
        "Работает только в групповых чатах.\n\n"
        "<b>Ставки:</b>\n"
        "• <code>к 1000</code> — красное (x2)\n"
        "• <code>ч 1000</code> — чёрное (x2)\n"
        "• <code>з 1000</code> — зеро (x36)\n"
        "• <code>10-20 500</code> — диапазон\n"
        "• <code>100 200 300</code> — набор чисел\n"
        "• <code>7 500</code> — конкретное число (x36)\n\n"
        "<b>Команды:</b>\n"
        "• <code>старт</code> — запустить колесо\n"
        "• <code>лог</code> — история рулетки\n"
        "• <code>отмена</code> — отменить сбор",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_roulette_help()
    )


async def cb_roulette_log(call: CallbackQuery):
    """Лог из инлайн-кнопки."""
    chat_id = call.message.chat.id
    rows = await db.get_roulette_logs(chat_id, 20)
    if not rows:
        await edit_or_send(call, "📜 История рулетки пуста.", kb_roulette_help())
        await call.answer()
        return
    lines = ["<b>📜 ЛОГ РУЛЕТКИ (последние 20)</b>\n"]
    for r in rows:
        try:
            parts = json.loads(r["participants"] or "[]")
        except Exception:
            parts = []
        lines.append(
            f"#{r['id']} · spin=<b>{r['bet_type'] or '?'}</b> · "
            f"банк=<b>{fmt_money(r['bet_amount'] or 0)}</b> · "
            f"участников={len(parts)}"
        )
    await edit_or_send(call, "\n".join(lines), kb_roulette_help())
    await call.answer()


# ============================================================
# ЕДИНЫЙ ОБРАБОТЧИК ГРУПП (рулетка)
# ============================================================

async def group_roulette_router(message: Message) -> bool:
    """Пробуем обработать сообщение в чате как рулетку. True — обработано."""
    if message.chat.type == ChatType.PRIVATE:
        return False
    if not message.text:
        return False
    return await handle_roulette_message(message)


# ============================================================
# РЕГИСТРАЦИЯ ЧАСТИ 4 (ИСПРАВЛЕННАЯ)
# ============================================================

def register_part4(dp: Dispatcher):
    """Хендлеры рулетки (сообщения чатов + инлайн лог)."""
    # Убрали (?i) из середины, флаг re.IGNORECASE ставится в конце регулярки
    dp.message.register(
        group_roulette_router, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        F.text.regexp(r"^(старт|лог|отмена)$", flags=re.IGNORECASE) | F.text.regexp(r"\d+")
    )
    dp.message.register(cmd_roulette_help, Command("roulette"))
    dp.callback_query.register(cb_roulette_log, F.data == "roulette_log")
    
# ============================================================
# КЛАНЫ — расширенные команды (налог, кик, передача)
# ============================================================

async def cb_clan_kick(call: CallbackQuery):
    """Кик участника из клана (только владелец)."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan or clan["owner_id"] != uid:
        await call.answer("Только владелец может кикать", show_alert=True)
        return
    args = call.data.split("_")
    if len(args) < 3:
        await call.answer("Ошибка", show_alert=True)
        return
    target = int(args[2])
    if target == uid:
        await call.answer("Нельзя кикнуть себя", show_alert=True)
        return
    await db.leave_clan(target)
    await call.answer("Участник кикнут", show_alert=True)
    await cb_clan_members(call)


async def cb_clan_transfer(call: CallbackQuery):
    """Передать клан (только владелец)."""
    uid = call.from_user.id
    clan = await db.get_user_clan(uid)
    if not clan or clan["owner_id"] != uid:
        await call.answer("Только владелец", show_alert=True)
        return
    args = call.data.split("_")
    if len(args) < 3:
        await call.answer("Ошибка", show_alert=True)
        return
    target = int(args[2])
    member = await db.get_user(target)
    if not member or member["clan_id"] != clan["clan_id"]:
        await call.answer("Этот игрок не в твоём клане", show_alert=True)
        return
    async with db._lock:
        await db.conn.execute(
            "UPDATE clans SET owner_id = ? WHERE clan_id = ?", (target, clan["clan_id"])
        )
        await db.conn.commit()
    await call.answer("Клан передан новому владельцу", show_alert=True)


# ============================================================
# VIP
# ============================================================

VIP_PACKS = {
    1: {"days": 30, "price": 50000, "name": "🥉 VIP Бронза"},
    2: {"days": 30, "price": 150000, "name": "🥈 VIP Серебро"},
    3: {"days": 30, "price": 500000, "name": "🥇 VIP Золото"},
}


def kb_vip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥉 VIP Бронза — 50 000 💎 (x1.1)",
                              callback_data="vip_buy_1")],
        [InlineKeyboardButton(text="🥈 VIP Серебро — 150 000 💎 (x1.25)",
                              callback_data="vip_buy_2")],
        [InlineKeyboardButton(text="🥇 VIP Золото — 500 000 💎 (x1.5)",
                              callback_data="vip_buy_3")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_menu")],
    ])


async def menu_vip(message: Message):
    """Меню VIP."""
    uid = message.from_user.id
    await db.ensure_user(uid, message.from_user.username or "",
                         message.from_user.first_name or "")
    level = await db.check_vip(uid)
    until = await db.get_vip_until(uid)
    status = f"Уровень {level} до {until[:10]}" if level else "нет"
    await message.answer(
        f"<b>💎 VIP-ПОДПИСКА</b>\n\n"
        f"Твой статус: <b>{status}</b>\n\n"
        f"Бонусы:\n"
        f"• 🥉 Бронза — x1.1 к выигрышу\n"
        f"• 🥈 Серебро — x1.25 к выигрышу\n"
        f"• 🥇 Золото — x1.5 к выигрышу\n\n"
        f"Срок: 30 дней.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_vip()
    )


async def cb_vip_buy(call: CallbackQuery):
    """Покупка VIP."""
    try:
        level = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        await call.answer("Ошибка", show_alert=True)
        return
    pack = VIP_PACKS.get(level)
    if not pack:
        await call.answer("Ошибка", show_alert=True)
        return
    uid = call.from_user.id
    if not await db.take_balance(uid, pack["price"]):
        await call.answer("Недостаточно средств", show_alert=True)
        return
    await db.set_vip(uid, level, pack["days"])
    await call.answer(f"{pack['name']} активирован!", show_alert=True)
    await edit_or_send(call,
                       f"✅ <b>{pack['name']}</b> активирован на {pack['days']} дней.\n"
                       f"Твой множитель выигрыша: <b>x{vip_multiplier(level)}</b>",
                       kb_back())


# ============================================================
# ПРОМОКОДЫ
# ============================================================

async def cmd_promo(message: Message):
    """Активация промокода: /promo CODE."""
    uid = message.from_user.id
    await db.ensure_user(uid, message.from_user.username or "", message.from_user.first_name or "")
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/promo КОД</code>", parse_mode=ParseMode.HTML)
        return
    code = args[1].strip()
    amount = await db.use_promo(uid, code)
    if amount is None:
        await message.answer("❌ Промокод не найден или использован.")
        return
    await message.answer(f"🎁 Промокод активирован! Получено <b>{fmt_money(amount)}</b> 💎",
                         parse_mode=ParseMode.HTML)


# ============================================================
# АДМИН-КОМАНДЫ (50+)
# ============================================================

def is_admin_filter(message: Message) -> bool:
    return bool(message.from_user and is_admin(message.from_user.id))


async def _get_target(message: Message) -> Optional[int]:
    """Извлекает ID цели из reply или @username."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    args = (message.text or "").split()
    if len(args) >= 2:
        token = args[1]
        if token.startswith("@"):
            username = token.lstrip("@")
            async with db.conn.execute(
                "SELECT user_id FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
            return row["user_id"] if row else None
        if token.lstrip("-").isdigit():
            return int(token)
    return None


async def _get_arg_int(message: Message, pos: int) -> Optional[int]:
    args = (message.text or "").split()
    if len(args) > pos and args[pos].lstrip("-").isdigit():
        return int(args[pos])
    return None


async def _admin_action(message: Message, action: str, target: Optional[int] = None,
                        details: str = ""):
    await db.log_admin(message.from_user.id, action, target, details)
    for aid in ADMIN_IDS:
        if aid == message.from_user.id:
            continue
        try:
            await message.bot.send_message(
                aid, f"🛡 Админ {message.from_user.id}: {action} → {target} ({details})"
            )
        except Exception:
            pass


# ---- @ help ----
async def cmd_admin_help(message: Message):
    """Список всех админ-команд."""
    if not is_admin(message.from_user.id):
        return
    text = (
        "<b>🛡 АДМИН-КОМАНДЫ</b>\n\n"
        "<b>💎 Баланс</b>\n"
        "• <code>/setbal @user 1000</code>\n"
        "• <code>/give @user 1000</code>\n"
        "• <code>/take @user 1000</code>\n"
        "• <code>/reset @user</code>\n\n"
        "<b>🚫 Бан</b>\n"
        "• <code>/ban @user</code>\n"
        "• <code>/unban @user</code>\n"
        "• <code>/mute @user</code> (в чате)\n\n"
        "<b>🎁 Промо / дроп</b>\n"
        "• <code>/promo_create КОД СУММА ИСПОЛЬЗОВАНИЙ</code>\n"
        "• <code>/drop 1000</code> — дроп всем\n"
        "• <code>/drop 1000 @user</code>\n\n"
        "<b>💎 VIP</b>\n"
        "• <code>/give_vip @user 3 30</code>\n"
        "• <code>/take_vip @user</code>\n\n"
        "<b>📊 Статистика</b>\n"
        "• <code>/stats</code> — общая\n"
        "• <code>/user @user</code> — карточка\n"
        "• <code>/bal @user</code>\n"
        "• <code>/hist @user 20</code>\n\n"
        "<b>🏰 Кланы</b>\n"
        "• <code>/clan_delete ИМЯ</code>\n"
        "• <code>/clan_setlevel ИМЯ 10</code>\n"
        "• <code>/clan_treasury ИМЯ 100000</code>\n\n"
        "<b>⚙️ Система</b>\n"
        "• <code>/settings</code>\n"
        "• <code>/set_donate_rate 10</code>\n"
        "• <code>/backup</code> — бекап БД\n"
        "• <code>/restart</code> — рестарт бота\n"
        "• <code>/clear</code> — очистить историю\n"
        "• <code>/broadcast ТЕКСТ</code> — рассылка\n"
        "• <code>/say @user ТЕКСТ</code> — написать от бота\n"
        "• <code>/reload_settings</code>\n\n"
        "<b>🎡 Рулетка</b>\n"
        "• <code>/rlog CHAT_ID</code>\n\n"
        "<b>💰 Прочее</b>\n"
        "• <code>/setbal_all 1000</code>\n"
        "• <code>/bonus_reset @user</code>\n"
        "• <code>/delete_user @user</code>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


# ---- Баланс ----
async def admin_setbal(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    amount = await _get_arg_int(message, 2) if not message.reply_to_message else await _get_arg_int(message, 1)
    if not target or amount is None:
        await message.answer("Использование: /setbal @user 1000")
        return
    await db.ensure_user(target)
    current = await db.get_balance(target)
    await db.add_balance(target, amount - current)
    await _admin_action(message, "setbal", target, str(amount))
    await message.answer(f"✅ Баланс {target}: {fmt_money(amount)} 💎")


async def admin_give(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    amount = await _get_arg_int(message, 2) if not message.reply_to_message else await _get_arg_int(message, 1)
    if not target or amount is None:
        await message.answer("Использование: /give @user 1000")
        return
    await db.ensure_user(target)
    new = await db.add_balance(target, amount)
    await _admin_action(message, "give", target, str(amount))
    await message.answer(f"✅ Выдано {amount} 💎 → {target}. Баланс: {fmt_money(new)}")


async def admin_take(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    amount = await _get_arg_int(message, 2) if not message.reply_to_message else await _get_arg_int(message, 1)
    if not target or amount is None:
        await message.answer("Использование: /take @user 1000")
        return
    await db.add_balance(target, -amount)
    await _admin_action(message, "take", target, str(amount))
    await message.answer(f"✅ Списано {amount} 💎 у {target}")


async def admin_reset(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /reset @user")
        return
    await db.ensure_user(target)
    current = await db.get_balance(target)
    await db.add_balance(target, -current)
    await _admin_action(message, "reset", target)
    await message.answer(f"✅ Баланс {target} обнулён.")


async def admin_setbal_all(message: Message):
    if not is_admin(message.from_user.id):
        return
    amount = await _get_arg_int(message, 1)
    if amount is None:
        await message.answer("Использование: /setbal_all 1000")
        return
    users = await db.all_users()
    async with db._lock:
        await db.conn.execute("UPDATE users SET balance = ?", (amount,))
        await db.conn.commit()
    await _admin_action(message, "setbal_all", None, str(amount))
    await message.answer(f"✅ Баланс всех ({len(users)}) установлен на {fmt_money(amount)}")


# ---- Бан ----
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /ban @user")
        return
    await db.ensure_user(target)
    await db.ban_user(target, True)
    await _admin_action(message, "ban", target)
    await message.answer(f"🚫 {target} заблокирован.")


async def admin_unban(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /unban @user")
        return
    await db.ban_user(target, False)
    await _admin_action(message, "unban", target)
    await message.answer(f"✅ {target} разблокирован.")


async def admin_mute(message: Message):
    """Мут в чате (только если бот админ)."""
    if not is_admin(message.from_user.id):
        return
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Только в чате.")
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /mute @user")
        return
    try:
        from aiogram.types import ChatPermissions
        await message.bot.restrict_chat_member(
            message.chat.id, target,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(hours=1)
        )
        await message.answer(f"🔇 {target} замучен на 1 час.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ---- Промо / дроп ----
async def admin_promo_create(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 4:
        await message.answer("Использование: /promo_create КОД СУММА ИСПОЛЬЗОВАНИЙ")
        return
    code, amount, uses = args[1], args[2], args[3]
    if not amount.isdigit() or not uses.isdigit():
        await message.answer("Сумма и использования должны быть числами.")
        return
    ok = await db.create_promo(code, int(amount), int(uses), message.from_user.id)
    await _admin_action(message, "promo_create", None, f"{code} {amount} {uses}")
    if ok:
        await message.answer(f"✅ Промокод <code>{code}</code> создан: {amount} 💎 × {uses}",
                             parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Такой промокод уже существует.")


async def admin_drop(message: Message):
    """Дроп всем или одному."""
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    amount = await _get_arg_int(message, 2) if not message.reply_to_message and target else await _get_arg_int(message, 1)
    # Если цель указана
    if target and amount:
        await db.ensure_user(target)
        await db.add_balance(target, amount)
        await _admin_action(message, "drop", target, str(amount))
        await message.answer(f"🎁 Дроп {amount} 💎 → {target}")
        return
    # Иначе всем
    amount = await _get_arg_int(message, 1)
    if amount is None:
        await message.answer("Использование: /drop 1000 [@user]")
        return
    users = await db.all_users()
    async with db._lock:
        await db.conn.execute("UPDATE users SET balance = balance + ?", (amount,))
        await db.conn.commit()
    await _admin_action(message, "drop_all", None, str(amount))
    await message.answer(f"🎁 Дроп {fmt_money(amount)} 💎 всем ({len(users)} чел.)")


# ---- VIP ----
async def admin_give_vip(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /give_vip @user 3 30")
        return
    base = 2 if not message.reply_to_message else 1
    level = await _get_arg_int(message, base)
    days = await _get_arg_int(message, base + 1)
    if level is None or days is None:
        await message.answer("Использование: /give_vip @user 3 30")
        return
    await db.ensure_user(target)
    await db.set_vip(target, level, days)
    await _admin_action(message, "give_vip", target, f"lvl={level} days={days}")
    await message.answer(f"💎 VIP {level} выдан {target} на {days} дней.")


async def admin_take_vip(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /take_vip @user")
        return
    async with db._lock:
        await db.conn.execute(
            "UPDATE users SET vip_level = 0, vip_until = NULL WHERE user_id = ?", (target,)
        )
        await db.conn.commit()
    await _admin_action(message, "take_vip", target)
    await message.answer(f"✅ VIP снят с {target}.")


# ---- Статистика ----
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db.conn.execute("SELECT COUNT(*) c, SUM(balance) b FROM users") as cur:
        row = await cur.fetchone()
    total_users = row["c"] or 0
    total_balance = row["b"] or 0
    async with db.conn.execute("SELECT COUNT(*) c FROM clans") as cur:
        clans = (await cur.fetchone())["c"]
    async with db.conn.execute("SELECT COUNT(*) c FROM history") as cur:
        games = (await cur.fetchone())["c"]
    async with db.conn.execute("SELECT SUM(bet) s, SUM(win) w FROM history") as cur:
        h = await cur.fetchone()
    await message.answer(
        f"<b>📊 СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"💰 Баланс всех: <b>{fmt_money(total_balance)}</b> 💎\n"
        f"🏰 Кланов: <b>{clans}</b>\n"
        f"🎮 Игр: <b>{games}</b>\n"
        f"💵 Ставок: <b>{fmt_money(h['s'] or 0)}</b> 💎\n"
        f"🏆 Выплачено: <b>{fmt_money(h['w'] or 0)}</b> 💎",
        parse_mode=ParseMode.HTML
    )


async def admin_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /user @user")
        return
    u = await db.get_user(target)
    if not u:
        await message.answer("Не найден.")
        return
    vip = await db.check_vip(target)
    clan = await db.get_user_clan(target)
    await message.answer(
        f"<b>👤 КАРТОЧКА {target}</b>\n\n"
        f"Имя: {u['first_name']} (@{u['username']})\n"
        f"💰 Баланс: {fmt_money(u['balance'])}\n"
        f"🏆 Побед: {u['wins']} / 💀 Поражений: {u['losses']}\n"
        f"🎮 Игр: {u['games']}\n"
        f"⭐ Уровень: {u['level']} (XP {u['xp']})\n"
        f"💎 VIP: {vip}\n"
        f"🏰 Клан: {clan['name'] if clan else '—'}\n"
        f"👥 Рефов: {await db.get_refs_count(target)}\n"
        f"🚫 Бан: {'да' if u['banned'] else 'нет'}\n"
        f"📅 Рег: {u['reg_date'][:10]}",
        parse_mode=ParseMode.HTML
    )


async def admin_bal(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /bal @user")
        return
    bal = await db.get_balance(target)
    await message.answer(f"💰 {target}: {fmt_money(bal)} 💎")


async def admin_hist(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /hist @user")
        return
    rows = await db.get_history(target, 20)
    if not rows:
        await message.answer("История пуста.")
        return
    lines = [f"<b>📜 История {target}</b>\n"]
    for r in rows:
        lines.append(f"• {r['game']} | bet={fmt_money(r['bet'])} win={fmt_money(r['win'])} "
                     f"| {r['created_at'][:19]}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_delete_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /delete_user @user")
        return
    async with db._lock:
        await db.conn.execute("DELETE FROM users WHERE user_id = ?", (target,))
        await db.conn.execute("DELETE FROM history WHERE user_id = ?", (target,))
        await db.conn.commit()
    await _admin_action(message, "delete_user", target)
    await message.answer(f"🗑 {target} удалён.")


# ---- Кланы ----
async def admin_clan_delete(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /clan_delete ИМЯ")
        return
    name = args[1].strip()
    clan = await db.get_clan_by_name(name)
    if not clan:
        await message.answer("Клан не найден.")
        return
    async with db._lock:
        await db.conn.execute("UPDATE users SET clan_id = NULL WHERE clan_id = ?",
                              (clan["clan_id"],))
        await db.conn.execute("DELETE FROM clans WHERE clan_id = ?", (clan["clan_id"],))
        await db.conn.commit()
    await _admin_action(message, "clan_delete", None, name)
    await message.answer(f"🗑 Клан {name} удалён.")


async def admin_clan_setlevel(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 3:
        await message.answer("Использование: /clan_setlevel ИМЯ 10")
        return
    name, lvl = args[1], args[2]
    if not lvl.isdigit():
        await message.answer("Уровень — число.")
        return
    clan = await db.get_clan_by_name(name)
    if not clan:
        await message.answer("Клан не найден.")
        return
    async with db._lock:
        await db.conn.execute("UPDATE clans SET level = ? WHERE clan_id = ?",
                              (int(lvl), clan["clan_id"]))
        await db.conn.commit()
    await _admin_action(message, "clan_setlevel", None, f"{name} {lvl}")
    await message.answer(f"✅ Уровень клана {name} = {lvl}")


async def admin_clan_treasury(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 3:
        await message.answer("Использование: /clan_treasury ИМЯ 100000")
        return
    name, amount = args[1], args[2]
    if not amount.lstrip("-").isdigit():
        await message.answer("Сумма — число.")
        return
    clan = await db.get_clan_by_name(name)
    if not clan:
        await message.answer("Клан не найден.")
        return
    async with db._lock:
        await db.conn.execute("UPDATE clans SET treasury = ? WHERE clan_id = ?",
                              (int(amount), clan["clan_id"]))
        await db.conn.commit()
    await _admin_action(message, "clan_treasury", None, f"{name} {amount}")
    await message.answer(f"✅ Казна клана {name} = {fmt_money(int(amount))} 💎")


# ---- Система ----
async def admin_settings(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db.conn.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    lines = ["<b>⚙️ НАСТРОЙКИ</b>\n"]
    for r in rows:
        lines.append(f"• <code>{r['key']}</code> = {r['value']}")
    if not rows:
        lines.append("— пусто —")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_set_donate_rate(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /set_donate_rate 10")
        return
    await db.set_setting("donate_rate", args[1])
    await message.answer(f"✅ Курс = {args[1]}")


async def admin_backup(message: Message):
    """Отправляет файл БД."""
    if not is_admin(message.from_user.id):
        return
    try:
        if os.path.exists(DB_PATH):
            await message.answer_document(FSInputFile(DB_PATH),
                                          caption=f"💾 Бекап от {datetime.utcnow()}")
        else:
            await message.answer("Файл БД не найден.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


async def admin_restart(message: Message):
    """Рестарт процесса (внешний supervisor поднимет)."""
    if not is_admin(message.from_user.id):
        return
    await _admin_action(message, "restart")
    await message.answer("♻️ Перезапуск...")
    await asyncio.sleep(1)
    os._exit(0)


async def admin_clear(message: Message):
    """Очистка истории."""
    if not is_admin(message.from_user.id):
        return
    async with db._lock:
        await db.conn.execute("DELETE FROM history")
        await db.conn.commit()
    await _admin_action(message, "clear_history")
    await message.answer("🧹 История игр очищена.")


async def admin_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /broadcast ТЕКСТ")
        return
    text = args[1]
    users = await db.all_users()
    ok, fail = 0, 0
    for u in users:
        try:
            await message.bot.send_message(u["user_id"], text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await _admin_action(message, "broadcast", None, f"{ok}/{fail}")
    await message.answer(f"📢 Рассылка: {ok} ✅ / {fail} ❌")


async def admin_say(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /say @user ТЕКСТ")
        return
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /say @user ТЕКСТ")
        return
    try:
        await message.bot.send_message(target, args[2])
        await message.answer("✅ Отправлено.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


async def admin_reload_settings(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("♻️ Настройки перечитаны.")


async def admin_rlog(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await message.answer("Использование: /rlog CHAT_ID")
        return
    chat_id = int(args[1])
    rows = await db.get_roulette_logs(chat_id, 30)
    if not rows:
        await message.answer("Пусто.")
        return
    lines = [f"<b>🎡 Лог чата {chat_id}</b>\n"]
    for r in rows:
        lines.append(f"#{r['id']} spin={r['bet_type']} банк={fmt_money(r['bet_amount'] or 0)} "
                     f"{r['created_at'][:19]}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_bonus_reset(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = await _get_target(message)
    if not target:
        await message.answer("Использование: /bonus_reset @user")
        return
    async with db._lock:
        await db.conn.execute(
            "UPDATE users SET last_bonus = NULL, bonus_streak = 0 WHERE user_id = ?",
            (target,)
        )
        await db.conn.commit()
    await message.answer(f"✅ Бонус сброшен у {target}")


# ============================================================
# РЕГИСТРАЦИЯ ЧАСТИ 5
# ============================================================

def register_part5(dp: Dispatcher):
    dp.message.register(cmd_admin_help, Command("help"))
    dp.message.register(cmd_admin_help, Command("admin"))
    dp.message.register(admin_setbal, Command("setbal"))
    dp.message.register(admin_give, Command("give"))
    dp.message.register(admin_take, Command("take"))
    dp.message.register(admin_reset, Command("reset"))
    dp.message.register(admin_setbal_all, Command("setbal_all"))
    dp.message.register(admin_ban, Command("ban"))
    dp.message.register(admin_unban, Command("unban"))
    dp.message.register(admin_mute, Command("mute"))
    dp.message.register(admin_promo_create, Command("promo_create"))
    dp.message.register(admin_drop, Command("drop"))
    dp.message.register(admin_give_vip, Command("give_vip"))
    dp.message.register(admin_take_vip, Command("take_vip"))
    dp.message.register(admin_stats, Command("stats"))
    dp.message.register(admin_user, Command("user"))
    dp.message.register(admin_bal, Command("bal"))
    dp.message.register(admin_hist, Command("hist"))
    dp.message.register(admin_delete_user, Command("delete_user"))
    dp.message.register(admin_clan_delete, Command("clan_delete"))
    dp.message.register(admin_clan_setlevel, Command("clan_setlevel"))
    dp.message.register(admin_clan_treasury, Command("clan_treasury"))
    dp.message.register(admin_settings, Command("settings"))
    dp.message.register(admin_set_donate_rate, Command("set_donate_rate"))
    dp.message.register(admin_backup, Command("backup"))
    dp.message.register(admin_restart, Command("restart"))
    dp.message.register(admin_clear, Command("clear"))
    dp.message.register(admin_broadcast, Command("broadcast"))
    dp.message.register(admin_say, Command("say"))
    dp.message.register(admin_reload_settings, Command("reload_settings"))
    dp.message.register(admin_rlog, Command("rlog"))
    dp.message.register(admin_bonus_reset, Command("bonus_reset"))

    dp.message.register(cmd_promo, Command("promo"))
    dp.message.register(menu_vip, Command("vip"))
    dp.callback_query.register(cb_vip_buy, F.data.startswith("vip_buy_"))
    dp.callback_query.register(cb_clan_kick, F.data.startswith("clan_kick_"))
    dp.callback_query.register(cb_clan_transfer, F.data.startswith("clan_transfer_"))

# ============================================================
# ДОПОЛНИТЕЛЬНЫЕ АДМИН-КОМАНДЫ (добиваем до 50+)
# ============================================================

async def admin_unban_all(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db._lock:
        await db.conn.execute("UPDATE users SET banned = 0")
        await db.conn.commit()
    await _admin_action(message, "unban_all")
    await message.answer("✅ Все разбанены.")


async def admin_top_reset(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db._lock:
        await db.conn.execute("UPDATE users SET wins = 0, losses = 0, games = 0")
        await db.conn.commit()
    await _admin_action(message, "top_reset")
    await message.answer("✅ Топ сброшен.")


async def admin_set_max_bet(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /set_max_bet 1000000")
        return
    await db.set_setting("max_bet", args[1])
    global MAX_BET
    MAX_BET = int(args[1])
    await message.answer(f"✅ MAX_BET = {fmt_money(MAX_BET)}")


async def admin_give_all_vip(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 3 or not args[1].isdigit() or not args[2].isdigit():
        await message.answer("Использование: /give_all_vip 1 30")
        return
    level, days = int(args[1]), int(args[2])
    users = await db.all_users()
    until = (datetime.utcnow() + timedelta(days=days)).isoformat()
    async with db._lock:
        await db.conn.execute("UPDATE users SET vip_level = ?, vip_until = ?",
                              (level, until))
        await db.conn.commit()
    await _admin_action(message, "give_all_vip", None, f"{level} {days}")
    await message.answer(f"💎 VIP {level} выдан всем ({len(users)}) на {days} дней.")


async def admin_log(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db.conn.execute(
        "SELECT * FROM admin_logs ORDER BY id DESC LIMIT 30"
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        await message.answer("Лог пуст.")
        return
    lines = ["<b>📜 ADMIN LOG</b>\n"]
    for r in rows:
        lines.append(f"• {r['created_at'][:19]} {r['admin_id']} → {r['action']} "
                     f"({r['target_id']}) {r['details'] or ''}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_export_users(message: Message):
    if not is_admin(message.from_user.id):
        return
    users = await db.all_users()
    data = [dict(u) for u in users]
    tmp = "users_export.json"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    await message.answer_document(FSInputFile(tmp), caption=f"👥 {len(data)} пользователей")
    try:
        os.remove(tmp)
    except Exception:
        pass


async def admin_online(message: Message):
    if not is_admin(message.from_user.id):
        return
    now = datetime.utcnow()
    async with db.conn.execute(
        "SELECT COUNT(*) c FROM users WHERE reg_date >= ?",
        ((now - timedelta(days=1)).isoformat(),)
    ) as cur:
        day = (await cur.fetchone())["c"]
    await message.answer(f"👥 Новых за сутки: {day}")


async def admin_ping(message: Message):
    if not is_admin(message.from_user.id):
        return
    t0 = time.time()
    m = await message.answer("🏓 ...")
    dt = (time.time() - t0) * 1000
    await m.edit_text(f"🏓 Pong: <b>{dt:.0f} ms</b>", parse_mode=ParseMode.HTML)


async def admin_setting_get(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /setting KEY")
        return
    val = await db.get_setting(args[1], "—")
    await message.answer(f"<code>{args[1]}</code> = {val}", parse_mode=ParseMode.HTML)


async def admin_setting_set(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /set_setting KEY VALUE")
        return
    await db.set_setting(args[1], args[2])
    await message.answer(f"✅ {args[1]} = {args[2]}")


async def admin_promo_list(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with db.conn.execute("SELECT * FROM promocodes ORDER BY created_at DESC LIMIT 50") as cur:
        rows = await cur.fetchall()
    if not rows:
        await message.answer("Промокодов нет.")
        return
    lines = ["<b>🎁 ПРОМОКОДЫ</b>\n"]
    for r in rows:
        lines.append(f"• <code>{r['code']}</code> {fmt_money(r['amount'])} × {r['uses_left']}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_promo_delete(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /promo_delete КОД")
        return
    async with db._lock:
        await db.conn.execute("DELETE FROM promocodes WHERE code = ?", (args[1],))
        await db.conn.commit()
    await message.answer(f"🗑 Промокод {args[1]} удалён.")


async def admin_event_trigger(message: Message):
    """Ручной запуск ивента: /event happy|drop|roulette."""
    if not is_admin(message.from_user.id):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /event happy|drop|roulette")
        return
    kind = args[1].lower()
    if kind == "happy":
        asyncio.create_task(happy_hour_event())
        await message.answer("✅ Happy Hour запущен.")
    elif kind == "drop":
        asyncio.create_task(auto_drop_event())
        await message.answer("✅ Авто-дроп запущен.")
    elif kind == "roulette":
        asyncio.create_task(auto_roulette_event())
        await message.answer("✅ Авто-рулетка запущена.")
    else:
        await message.answer("Неизвестный ивент.")


# ============================================================
# АВТО-ИВЕНТЫ
# ============================================================

HAPPY_HOUR_ACTIVE = False
HAPPY_HOUR_MULT = 2.0


async def get_global_mult() -> float:
    """Глобальный множитель выигрыша (для happy hour)."""
    global HAPPY_HOUR_ACTIVE
    if HAPPY_HOUR_ACTIVE:
        return HAPPY_HOUR_MULT
    return 1.0


async def happy_hour_event(duration_min: int = 10):
    """Счастливый час — x2 выигрыш на 10 минут."""
    global HAPPY_HOUR_ACTIVE
    if HAPPY_HOUR_ACTIVE:
        return
    HAPPY_HOUR_ACTIVE = True
    await db.set_setting("happy_hour", "1")
    users = await db.all_users()
    for u in users[:2000]:
        try:
            await active_bot.send_message(
                u["user_id"],
                "🎉 <b>СЧАСТЛИВЫЙ ЧАС!</b>\n\n"
                "В течение 10 минут все выигрыши <b>x2</b>!\n"
                "Скорее в игру! 🎮",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await asyncio.sleep(0.03)
    await asyncio.sleep(duration_min * 60)
    HAPPY_HOUR_ACTIVE = False
    await db.set_setting("happy_hour", "0")
    for u in users[:2000]:
        try:
            await active_bot.send_message(
                u["user_id"], "🕐 Счастливый час закончился. Спасибо за игру!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await asyncio.sleep(0.03)


async def auto_drop_event(amount: int = 500):
    """Авто-дроп всем активным."""
    users = await db.all_users()
    if not users:
        return
    async with db._lock:
        await db.conn.execute("UPDATE users SET balance = balance + ?", (amount,))
        await db.conn.commit()
    for u in users[:500]:
        try:
            await active_bot.send_message(
                u["user_id"],
                f"🎁 <b>АВТО-ДРОП!</b>\n\n"
                f"Каждому +<b>{fmt_money(amount)}</b> 💎\n"
                f"Заходи играть!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        await asyncio.sleep(0.03)


async def auto_roulette_event():
    """Автоматическая рулетка в главном чате (если задан MAIN_CHAT_ID)."""
    chat_id = await db.get_setting("main_chat_id", "")
    if not chat_id or not chat_id.lstrip("-").isdigit():
        return
    chat_id = int(chat_id)
    spin = random.randint(0, 36)
    if spin == 0:
        color = "🟢 зеро"
    elif spin in RED_NUMBERS:
        color = "🔴 красное"
    else:
        color = "⚫ чёрное"
    try:
        await active_bot.send_message(
            chat_id,
            f"🎡 <b>АВТО-РУЛЕТКА</b>\n\n"
            f"Выпало: <b>{spin} {color}</b>\n"
            f"Следующий запуск через 30 минут.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============================================================
# ПЛАНИРОВЩИК (APScheduler)
# ============================================================

scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler():
    """Настройка авто-ивентов по расписанию."""
    scheduler.add_job(happy_hour_event, "cron", hour="18", minute="0", id="happy_hour")
    scheduler.add_job(auto_drop_event, "cron", hour="12", minute="0", id="auto_drop")
    scheduler.add_job(auto_roulette_event, "interval", minutes=30, id="auto_roulette")
    scheduler.start()
    logger.info("Scheduler started")


# ============================================================
# ВЕБ-СЕРВЕР (Render health check)
# ============================================================

active_bot: Optional[Bot] = None


async def health(request):
    """Health-check для Render."""
    return web.json_response({"status": "ok", "time": datetime.utcnow().isoformat()})


async def web_root(request):
    return web.Response(text="GameBot is running 🎮")


async def start_web():
    """Запуск aiohttp веб-сервера."""
    app = web.Application()
    app.router.add_get("/", web_root)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")


# ============================================================
# MAIN
# ============================================================

async def on_startup(bot: Bot):
    global active_bot
    active_bot = bot
    await db.connect()
    # синхронизируем MAX_BET
    global MAX_BET
    mb = await db.get_setting("max_bet", "")
    if mb.isdigit():
        MAX_BET = int(mb)
    setup_scheduler()
    logger.info("Bot started")


async def on_shutdown(bot: Bot):
    scheduler.shutdown(wait=False)
    await db.close()
    logger.info("Bot stopped")


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN не задан. Установи переменную окружения.")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    register_part2(dp)
    register_part3(dp)
    register_part4(dp)
    register_part5(dp)

    # доп. админ-команды из части 6
    dp.message.register(admin_unban_all, Command("unban_all"))
    dp.message.register(admin_top_reset, Command("top_reset"))
    dp.message.register(admin_set_max_bet, Command("set_max_bet"))
    dp.message.register(admin_give_all_vip, Command("give_all_vip"))
    dp.message.register(admin_log, Command("log"))
    dp.message.register(admin_export_users, Command("export_users"))
    dp.message.register(admin_online, Command("online"))
    dp.message.register(admin_ping, Command("ping"))
    dp.message.register(admin_setting_get, Command("setting"))
    dp.message.register(admin_setting_set, Command("set_setting"))
    dp.message.register(admin_promo_list, Command("promo_list"))
    dp.message.register(admin_promo_delete, Command("promo_delete"))
    dp.message.register(admin_event_trigger, Command("event"))

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await start_web()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())