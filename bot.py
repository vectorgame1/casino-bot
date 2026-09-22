import asyncio
import logging
import os
import threading
import random
import json
import time
import psycopg2
from psycopg2 import pool
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, LabeledPrice, PreCheckoutQuery
)
from flask import Flask, jsonify, request
from flask_cors import CORS

# ═══════════════ КОНСТАНТЫ ═══════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 6403424348
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MINI_APP_URL = "https://thriving-lokum-1f7004.netlify.app"
GROUP_URL = "https://t.me/+xrmEcGndccs5ZGFi"

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

MULT_COLOR = 2
MULT_ZERO = 36
MULT_NUMBER = 36
MULT_RANGE = 1.2

MAX_BALANCE = 9_000_000_000          # ⚡ новый лимит
MAX_BET = 100_000_000_000
DAILY_BONUS = 10000                  # ⚡ единый бонус
MAX_BIGINT = 9_000_000_000_000_000_000

# ═══════════════ ИГРОВЫЕ ДАННЫЕ ═══════════════
MINES_LEVELS = {
    "easy":   {"name": "🟢 Лёгкий",  "mines": 3,  "step": 0.15},
    "medium": {"name": "🟡 Средний", "mines": 5,  "step": 0.25},
    "hard":   {"name": "🔴 Хардкор", "mines": 10, "step": 0.50},
}

VIP_LEVELS = [
    {"name": "🥉 Бронза",  "xp": 0,     "cashback": 1,  "icon": "🥉"},
    {"name": "🥈 Серебро", "xp": 100,   "cashback": 3,  "icon": "🥈"},
    {"name": "🥇 Золото",  "xp": 500,   "cashback": 5,  "icon": "🥇"},
    {"name": "💎 Платина", "xp": 2000,  "cashback": 7,  "icon": "💎"},
    {"name": "👑 Алмаз",   "xp": 10000, "cashback": 10, "icon": "👑"},
]

QUESTS = [
    {"key": "roulette_10", "name": "🎡 Сыграй 10 раз в рулетку",  "target": 10,     "reward": 5000},
    {"key": "mines_win_5", "name": "💣 Выиграй 5 раз в Мины",     "target": 5,      "reward": 5000},
    {"key": "bets_20",     "name": "🎰 Сделай 20 ставок",          "target": 20,     "reward": 10000},
    {"key": "win_100k",    "name": "💰 Выиграй 100 000 токенов",   "target": 100000, "reward": 20000},
    {"key": "bj_5",        "name": "🃏 Сыграй в Блэкджек 5 раз",   "target": 5,      "reward": 5000},
    {"key": "jackpot_1",   "name": "💎 Сорви джекпот",              "target": 1,      "reward": 100000},
]

GAME_NAMES = {
    "roulette": "🎡 Рулетка",
    "slots": "🎰 Слоты",
    "coin": "🪙 Монетка",
    "mines": "💣 Мины",
    "bj": "🃏 Блэкджек",
    "duel": "⚔️ Дуэль",
}

# ═══════════════ АНИМАЦИИ (1 строка, много кадров) ═══════════════
ANIM_ROULETTE = [
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴",
    "🔴 ⚫",
    "🔴",
]
ANIM_ROULETTE_DELAYS = [0.2, 0.2, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6]

ANIM_SLOTS_SPIN = [
    "┃ 🍒 ┃ 🍋 ┃ 🍊 ┃",
    "┃ 🍇 ┃ 💎 ┃ 7️⃣ ┃",
    "┃ 🍊 ┃ 🍒 ┃ 🍋 ┃",
]

ANIM_COIN = ["🦅", "👑", "🦅", "👑", "🦅", "👑"]
ANIM_COIN_DELAYS = [0.25, 0.25, 0.25, 0.3, 0.35, 0.4]

ANIM_DUEL = ["⚔️", "🔴 ⚔️ 🔵", "🔴 💥 🔵", "🔵 💥 🔴", "🔴 ⚔️ 🔵", "💥 БАХ!"]
ANIM_DUEL_DELAYS = [0.3, 0.3, 0.3, 0.3, 0.4, 0.5]

# ═══════════════ СОСТОЯНИЯ ═══════════════
active_bets = {}
bj_games = {}
duel_games = {}
mines_games = {}
disabled_games = set()
giveaway_timers = {}
edit_state = {}
edit_case_state = {}
edit_shop_state = {}          # для магазина 2.0
bank_input_state = {}
admin_action_state = {}        # для админ-диалогов

event_double = False
maintenance_on = False
jackpot_amount = 10000


# ═══════════════ КЭШ В ПАМЯТИ ═══════════════
_cache = {}

def cache_get(key, ttl=30):
    """Получить из кэша. Если просрочено — вернуть None."""
    if key in _cache:
        val, exp = _cache[key]
        if time.time() < exp:
            return val
    return None

def cache_set(key, value, ttl=30):
    _cache[key] = (value, time.time() + ttl)

def cache_invalidate(prefix=None):
    if prefix is None:
        _cache.clear()
    else:
        keys = [k for k in _cache.keys() if k.startswith(prefix)]
        for k in keys:
            _cache.pop(k, None)


# ═══════════════ ПУЛ СОЕДИНЕНИЙ ═══════════════
_db_pool = None

def init_pool():
    global _db_pool
    try:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=2, maxconn=20, dsn=DATABASE_URL, sslmode='require'
        )
        print("✅ Connection pool создан (2-20)")
    except Exception as e:
        print(f"⚠️ Пул не создан, fallback на одиночные подключения: {e}")
        _db_pool = None


def get_conn():
    if _db_pool:
        return _db_pool.getconn()
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def release_conn(conn):
    if _db_pool:
        _db_pool.putconn(conn)
    else:
        conn.close()


def get_db():
    """Совместимость со старым кодом."""
    return get_conn()


# ═══════════════ ЛИМИТ БАЛАНСА ═══════════════
def clamp_balance(amount):
    """Обрезает до MAX_BALANCE. Возвращает (обрезанный, излишек)."""
    amount = clamp(amount)
    if amount > MAX_BALANCE:
        return MAX_BALANCE, amount - MAX_BALANCE
    return amount, 0


def clamp(x):
    try:
        return max(-MAX_BIGINT, min(int(x), MAX_BIGINT))
    except Exception:
        return 0


# ═══════════════ УТИЛИТЫ VIP ═══════════════
def get_event_mult():
    return 2 if event_double else 1


def get_vip_level(xp):
    level = 0
    for i, v in enumerate(VIP_LEVELS):
        if xp >= v["xp"]:
            level = i
    return level


def get_vip_info(xp):
    level = get_vip_level(xp)
    v = VIP_LEVELS[level]
    next_xp = VIP_LEVELS[level + 1]["xp"] if level + 1 < len(VIP_LEVELS) else v["xp"]
    return {
        "level": level, "name": v["name"], "icon": v["icon"],
        "cashback": v["cashback"], "xp": xp, "next_xp": next_xp,
    }


# ═══════════════ FLASK ═══════════════
app = Flask(__name__)
CORS(app)


@app.route('/')
def home():
    return "Bot is running!"


@app.route('/health')
def health():
    return "OK"


@app.route('/api/balance/<int:user_id>')
def api_balance(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned", "banned": True}), 403
    xp = get_xp(user_id)
    vip = get_vip_info(xp)
    boost = get_active_boost(user_id)
    boost_data = None
    if boost:
        boost_data = {"mult": boost[0], "until": boost[1].isoformat() if boost[1] else None}
    return jsonify({
        "user_id": user_id,
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "unlimited": is_unlimited(user_id),
        "xp": xp,
        "vip_level": vip["level"],
        "vip_name": vip["name"],
        "vip_icon": vip["icon"],
        "cashback": vip["cashback"],
        "boost": boost_data,
    })


@app.route('/api/boost/<int:user_id>')
def api_boost(user_id):
    boost = get_active_boost(user_id)
    if boost:
        return jsonify({
            "active": True,
            "mult": boost[0],
            "until": boost[1].isoformat() if boost[1] else None
        })
    return jsonify({"active": False, "mult": 1})


@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    uid = data.get('user_id')
    amt = data.get('amount')
    if uid is None or amt is None:
        return jsonify({"error": "Missing"}), 400
    if is_banned(uid):
        return jsonify({"error": "Banned"}), 403
    return jsonify({"user_id": uid, "balance": set_balance(uid, amt)})


@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    data = request.json
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    amount = data.get('amount')
    if admin_id != ADMIN_ID:
        return jsonify({"error": "Access denied"}), 403
    if target_id is None or amount is None:
        return jsonify({"error": "Missing"}), 400
    ensure_user(target_id, f"user_{target_id}")
    new_balance = set_balance(target_id, amount)
    return jsonify({"user_id": target_id, "balance": new_balance})


def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)


web_thread = threading.Thread(target=run_web)
web_thread.daemon = True
web_thread.start()


# ═══════════════ ИНИЦИАЛИЗАЦИЯ БД ═══════════════
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        balance BIGINT DEFAULT 1000,
        bank BIGINT DEFAULT 0,
        banned BOOLEAN DEFAULT FALSE,
        unlimited BOOLEAN DEFAULT FALSE,
        got_start_bonus BOOLEAN DEFAULT FALSE,
        xp BIGINT DEFAULT 0,
        vip_level INT DEFAULT 0,
        total_lost BIGINT DEFAULT 0,
        total_won BIGINT DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS game_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        game TEXT,
        bet BIGINT,
        win BIGINT,
        detail TEXT,
        time TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS quests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        quest_key TEXT NOT NULL,
        progress BIGINT DEFAULT 0,
        target BIGINT DEFAULT 1,
        completed BOOLEAN DEFAULT FALSE,
        claimed BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, quest_key)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS achievements (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        achievement_key TEXT NOT NULL,
        unlocked BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, achievement_key)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS titles (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        granted_by BIGINT,
        granted_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS giveaways (
        id SERIAL PRIMARY KEY,
        amount BIGINT,
        ends_at TIMESTAMP,
        created_by BIGINT,
        status TEXT DEFAULT 'active',
        winner_id BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_members (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,
        user_id BIGINT,
        username TEXT,
        last_seen TIMESTAMP DEFAULT NOW(),
        UNIQUE(chat_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS boosts (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        mult INT,
        until TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    # ALTER: новые колонки
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_last_claim TIMESTAMP")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS inventory JSONB DEFAULT '[]'::jsonb")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_earnings BIGINT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_count INT DEFAULT 0")

    # Индексы для ускорения
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_game ON game_log(game)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_created ON game_log(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_boosts_user ON boosts(user_id, until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_group_members_chat ON group_members(chat_id, user_id)")

    conn.commit()
    c.close()
    release_conn(conn)
    print("✅ БД инициализирована + индексы + новые колонки")


# ═══════════════ CRUD USERS ═══════════════
def get_user(user_id):
    cache_key = f"user_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    cache_set(cache_key, row, ttl=10)
    return row


def get_user_id_by_username(username):
    if username.startswith('@'):
        username = username[1:]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else None


def ensure_user(user_id, username):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, username) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET username = %s",
        (user_id, username, username)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")


def get_xp(user_id):
    cache_key = f"xp_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = row[0] if row else 0
    cache_set(cache_key, val, ttl=10)
    return val


def add_xp(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET xp = xp + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT xp FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_xp = row[0] if row else 0
    new_level = get_vip_level(new_xp)
    c.execute("UPDATE users SET vip_level = %s WHERE user_id = %s", (new_level, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{user_id}")
    cache_invalidate(f"user_{user_id}")
    return new_xp, new_level


def is_banned(user_id):
    cache_key = f"banned_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = bool(row[0]) if row and row[0] else False
    cache_set(cache_key, val, ttl=15)
    return val


def set_banned(user_id, banned=True):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, banned) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET banned = %s",
        (user_id, banned, banned)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"banned_{user_id}")


def is_unlimited(user_id):
    cache_key = f"unl_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT unlimited FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = bool(row[0]) if row and row[0] else False
    cache_set(cache_key, val, ttl=15)
    return val


def set_unlimited(user_id, unlimited=True):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, unlimited) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET unlimited = %s",
        (user_id, unlimited, unlimited)
    )
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"unl_{user_id}")


def set_balance(user_id, amount):
    """
    Изменяет баланс. Излишек > MAX_BALANCE уходит в банк.
    Возвращает новый баланс.
    """
    amount = clamp(amount)
    if is_unlimited(user_id) and amount < 0:
        # безлимит — не списываем
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        return row[0] if row else 0

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, 1000) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_balance = row[0] if row else 0

    # Лимит баланса — излишек в банк
    if new_balance > MAX_BALANCE:
        overflow = new_balance - MAX_BALANCE
        c.execute("UPDATE users SET balance = %s, bank = bank + %s WHERE user_id = %s",
                  (MAX_BALANCE, overflow, user_id))
        new_balance = MAX_BALANCE

    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return new_balance


def set_balance_exact(user_id, amount):
    amount, overflow = clamp_balance(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, balance) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET balance = %s",
        (user_id, amount, amount)
    )
    if overflow > 0:
        c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (overflow, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return amount


def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000


def set_bank(user_id, amount):
    amount = clamp(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, bank) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else 0


def get_bank(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row and row[0] else 0


# ═══════════════ ТОПЫ (с кэшем) ═══════════════
def get_top(limit=10):
    cached = cache_get("top_balance", ttl=30)
    if cached is not None:
        return cached[:limit]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY balance DESC LIMIT 50")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    cache_set("top_balance", rows, ttl=30)
    return rows[:limit]


def get_top_xp(limit=10):
    cached = cache_get("top_xp", ttl=30)
    if cached is not None:
        return cached[:limit]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY xp DESC LIMIT 50")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    cache_set("top_xp", rows, ttl=30)
    return rows[:limit]


def get_top_games(limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.balance, u.xp, COUNT(g.id) as games
        FROM users u
        LEFT JOIN game_log g ON u.user_id = g.user_id
        GROUP BY u.user_id, u.username, u.balance, u.xp
        ORDER BY games DESC LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_top_wins(limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.balance, u.xp, COUNT(g.id) as wins
        FROM users u
        LEFT JOIN game_log g ON u.user_id = g.user_id AND g.win > 0
        GROUP BY u.user_id, u.username, u.balance, u.xp
        ORDER BY wins DESC LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned = FALSE")
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return [r[0] for r in rows]


# ═══════════════ ГРУППЫ ═══════════════
def track_group_member(chat_id, user_id, username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO group_members (chat_id, user_id, username, last_seen)
                 VALUES (%s, %s, %s, NOW())
                 ON CONFLICT (chat_id, user_id) DO UPDATE
                 SET username = %s, last_seen = NOW()""",
              (chat_id, user_id, username, username))
    conn.commit()
    c.close()
    release_conn(conn)


def get_group_members(chat_id, limit=100):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username FROM group_members
                 WHERE chat_id = %s ORDER BY last_seen DESC LIMIT %s""",
              (chat_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


# ═══════════════ БУСТЫ ═══════════════
def get_user_mult(user_id):
    boost = get_active_boost(user_id)
    return boost[0] if boost else 1


def get_active_boost(user_id):
    cache_key = f"boost_{user_id}"
    cached = cache_get(cache_key, ttl=10)
    if cached is not None:
        return cached if cached != "none" else None
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT mult, until FROM boosts
                 WHERE user_id = %s AND until > NOW()
                 ORDER BY mult DESC LIMIT 1""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    cache_set(cache_key, row if row else "none", ttl=10)
    return row


def add_boost(user_id, mult, minutes):
    until = datetime.now() + timedelta(minutes=minutes)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO boosts (user_id, mult, until) VALUES (%s, %s, %s)",
              (user_id, mult, until))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"boost_{user_id}")
    return until


# ═══════════════ ЛОГИ ═══════════════
def log_game(user_id, username, game, bet, win, detail):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO game_log (user_id, username, game, bet, win, detail, time)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)""",
              (user_id, username, game, clamp(bet), clamp(win), detail,
               datetime.now().strftime("%H:%M:%S")))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("top_balance")
    cache_invalidate("top_xp")


def get_last_roulette_results(limit=10, chat_id=None):
    conn = get_conn()
    c = conn.cursor()
    if chat_id is not None:
        c.execute("""
            SELECT g.detail FROM game_log g
            JOIN group_members gm ON gm.user_id = g.user_id
            WHERE g.game='рулетка' AND gm.chat_id = %s
            ORDER BY g.id DESC LIMIT %s
        """, (chat_id, limit))
    else:
        c.execute("SELECT detail FROM game_log WHERE game='рулетка' ORDER BY id DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_big_wins(limit=10, min_win=100000):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT username, game, win, time FROM game_log
                 WHERE win >= %s ORDER BY win DESC LIMIT %s""", (min_win, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_recent_users(minutes=5, limit=20):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT DISTINCT u.user_id, u.username, u.balance
                 FROM users u
                 JOIN game_log g ON u.user_id = g.user_id
                 WHERE g.created_at > NOW() - INTERVAL '%s minutes'
                 ORDER BY u.balance DESC LIMIT %s""", (minutes, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_user_logs(user_id, limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT game, bet, win, detail, time FROM game_log
                 WHERE user_id = %s ORDER BY id DESC LIMIT %s""", (user_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_user_history(user_id, game=None, limit=15):
    conn = get_conn()
    c = conn.cursor()
    if game:
        c.execute("""SELECT game, bet, win, detail, time FROM game_log
                     WHERE user_id = %s AND game = %s ORDER BY id DESC LIMIT %s""",
                  (user_id, game, limit))
    else:
        c.execute("""SELECT game, bet, win, detail, time FROM game_log
                     WHERE user_id = %s ORDER BY id DESC LIMIT %s""",
                  (user_id, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_user_stats(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (user_id,))
    total_games = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (user_id,))
    total_wins = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(bet), 0) FROM game_log WHERE user_id = %s", (user_id,))
    total_bet = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(win), 0) FROM game_log WHERE user_id = %s", (user_id,))
    total_win = c.fetchone()[0]
    c.execute("SELECT COALESCE(MAX(win), 0) FROM game_log WHERE user_id = %s", (user_id,))
    best_win = c.fetchone()[0]
    c.execute("""SELECT game, COUNT(*) as cnt FROM game_log
                 WHERE user_id = %s GROUP BY game ORDER BY cnt DESC LIMIT 1""", (user_id,))
    fav = c.fetchone()
    c.close()
    release_conn(conn)
    return {
        "total_games": total_games,
        "total_wins": total_wins,
        "total_bet": total_bet,
        "total_win": total_win,
        "profit": total_win - total_bet,
        "best_win": best_win,
        "fav_game": fav[0] if fav else "—",
        "winrate": round(total_wins / total_games * 100) if total_games > 0 else 0,
    }


# ═══════════════ КВЕСТЫ ═══════════════
def update_quest(user_id, quest_key, amount=1):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, progress, target, completed FROM quests WHERE user_id = %s AND quest_key = %s",
              (user_id, quest_key))
    row = c.fetchone()
    if not row:
        target = next((q["target"] for q in QUESTS if q["key"] == quest_key), 1)
        c.execute("INSERT INTO quests (user_id, quest_key, progress, target) VALUES (%s, %s, %s, %s)",
                  (user_id, quest_key, amount, target))
    else:
        qid, progress, target, completed = row
        if completed:
            c.close()
            release_conn(conn)
            return
        new_progress = progress + amount
        c.execute("UPDATE quests SET progress = %s WHERE id = %s", (new_progress, qid))
        if new_progress >= target:
            c.execute("UPDATE quests SET completed = TRUE WHERE id = %s", (qid,))
    conn.commit()
    c.close()
    release_conn(conn)


def get_user_quests(user_id):
    conn = get_conn()
    c = conn.cursor()
    result = []
    for q in QUESTS:
        c.execute("SELECT progress, target, completed, claimed FROM quests WHERE user_id = %s AND quest_key = %s",
                  (user_id, q["key"]))
        row = c.fetchone()
        if row:
            progress, target, completed, claimed = row
        else:
            progress, target, completed, claimed = 0, q["target"], False, False
        result.append({
            "key": q["key"], "name": q["name"], "reward": q["reward"],
            "progress": progress, "target": target,
            "completed": completed, "claimed": claimed,
        })
    c.close()
    release_conn(conn)
    return result


def claim_quest(user_id, quest_key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, target, completed, claimed FROM quests WHERE user_id = %s AND quest_key = %s",
              (user_id, quest_key))
    row = c.fetchone()
    if not row:
        c.close()
        release_conn(conn)
        return None
    qid, target, completed, claimed = row
    if not completed or claimed:
        c.close()
        release_conn(conn)
        return None
    reward = next((q["reward"] for q in QUESTS if q["key"] == quest_key), 0)
    set_balance(user_id, reward)
    c.execute("UPDATE quests SET claimed = TRUE WHERE id = %s", (qid,))
    conn.commit()
    c.close()
    release_conn(conn)
    return reward


# ═══════════════ ТИТУЛЫ ═══════════════
def add_title(user_id, title, granted_by=0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO titles (user_id, title, granted_by) VALUES (%s, %s, %s)",
              (user_id, title, granted_by))
    conn.commit()
    c.close()
    release_conn(conn)


def get_user_titles(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT title FROM titles WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return [r[0] for r in rows]


def get_main_title(user_id):
    titles = get_user_titles(user_id)
    return titles[0] if titles else ""


def clear_user_titles(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)


def set_vip_level(user_id, level):
    conn = get_conn()
    c = conn.cursor()
    xp_needed = VIP_LEVELS[level]["xp"] if 0 <= level < len(VIP_LEVELS) else 0
    c.execute("UPDATE users SET xp = %s, vip_level = %s WHERE user_id = %s",
              (xp_needed, level, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{user_id}")


def reset_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET balance = 1000, bank = 0, xp = 0, vip_level = 0,
                 total_lost = 0, total_won = 0, inventory = '[]'::jsonb
                 WHERE user_id = %s""", (user_id,))
    c.execute("DELETE FROM quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM achievements WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate()


# ═══════════════ ЕЖЕДНЕВНЫЙ БОНУС ═══════════════
def get_daily_status(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT daily_last_claim FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if not row or not row[0]:
        return True, 0
    last = row[0]
    delta = datetime.now() - last
    if delta >= timedelta(hours=24):
        return True, 0
    left = int((timedelta(hours=24) - delta).total_seconds())
    return False, left


def claim_daily(user_id):
    can, _ = get_daily_status(user_id)
    if not can:
        return False
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET daily_last_claim = NOW() WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    set_balance(user_id, DAILY_BONUS)
    return True


def fmt_time_left(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}ч {m}мин"


# ═══════════════ ИНВЕНТАРЬ ═══════════════
def get_inventory(user_id):
    """Возвращает список предметов из JSONB."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT inventory FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if not row or not row[0]:
        return []
    inv = row[0]
    if isinstance(inv, str):
        try:
            inv = json.loads(inv)
        except Exception:
            return []
    return inv if isinstance(inv, list) else []


def save_inventory(user_id, inventory):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET inventory = %s::jsonb WHERE user_id = %s",
              (json.dumps(inventory, ensure_ascii=False), user_id))
    conn.commit()
    c.close()
    release_conn(conn)


def add_to_inventory(user_id, item):
    """Добавляет предмет в инвентарь. item — dict."""
    inv = get_inventory(user_id)
    item["inv_id"] = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    item["obtained_at"] = datetime.now().isoformat()
    inv.append(item)
    save_inventory(user_id, inv)
    return item["inv_id"]


def remove_from_inventory(user_id, inv_id):
    inv = get_inventory(user_id)
    new_inv = [it for it in inv if it.get("inv_id") != inv_id]
    if len(new_inv) == len(inv):
        return False
    save_inventory(user_id, new_inv)
    return True


def find_inventory_item(user_id, inv_id):
    inv = get_inventory(user_id)
    for it in inv:
        if it.get("inv_id") == inv_id:
            return it
    return None


def use_inventory_item(user_id, inv_id):
    """Активирует предмет из инвентаря. Возвращает (success, message)."""
    item = find_inventory_item(user_id, inv_id)
    if not item:
        return False, "❌ Предмет не найден"
    t = item.get("type")
    if t == "boost":
        add_boost(user_id, item["mult"], item["minutes"])
        remove_from_inventory(user_id, inv_id)
        return True, f"⚡ Буст ×{item['mult']} на {item['minutes']} мин активирован!"
    if t == "title":
        add_title(user_id, item["title"], 0)
        remove_from_inventory(user_id, inv_id)
        return True, f"🏷️ Титул «{item['title']}» активирован!"
    if t == "vip":
        set_vip_level(user_id, item["vip_level"])
        remove_from_inventory(user_id, inv_id)
        return True, f"👑 VIP уровень {item['vip_level']} активирован!"
    if t == "case":
        return False, "🎰 Кейс нужно открыть отдельно"
    return False, "❌ Неизвестный тип"


# ═══════════════ РЕФЕРАЛЬНАЯ СИСТЕМА ═══════════════
def set_referrer(user_id, referrer_id):
    """Привязывает пользователя к рефереру (только если ещё нет)."""
    if user_id == referrer_id:
        return False
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        c.close()
        release_conn(conn)
        return False
    c.execute("UPDATE users SET referrer_id = %s WHERE user_id = %s", (referrer_id, user_id))
    c.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = %s", (referrer_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    # Бонус обоим
    set_balance(user_id, 5000)
    set_balance(referrer_id, 5000)
    return True


def get_referrals(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users WHERE referrer_id = %s", (user_id,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def get_ref_stats(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(ref_count, 0), COALESCE(ref_earnings, 0) FROM users WHERE user_id = %s",
              (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return (row[0], row[1]) if row else (0, 0)


def add_ref_earnings(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET ref_earnings = ref_earnings + %s WHERE user_id = %s",
              (amount, user_id))
    conn.commit()
    c.close()
    release_conn(conn)


def get_ref_top(limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, ref_count, ref_earnings
                 FROM users WHERE ref_count > 0
                 ORDER BY ref_count DESC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


# ═══════════════ МАГАЗИН 2.0 ═══════════════
DEFAULT_SHOP_ITEMS = [
    {"id": "boost_2_30", "type": "boost", "name": "⚡ ×2 на 30 мин",
     "desc": "Множитель ×2 на 30 мин", "mult": 2, "minutes": 30,
     "stars": 5, "tokens": None},
    {"id": "boost_3_60", "type": "boost", "name": "⚡ ×3 на 1 час",
     "desc": "Множитель ×3 на 60 мин", "mult": 3, "minutes": 60,
     "stars": 15, "tokens": 500000},
    {"id": "title_legend", "type": "title", "name": "👑 Титул «Легенда»",
     "desc": "Крутой титул в профиле", "title": "👑 Легенда",
     "stars": 50, "tokens": 5000000},
    {"id": "vip_silver", "type": "vip", "name": "🥈 VIP Серебро",
     "desc": "Повышение до Серебра", "vip_level": 1,
     "stars": 25, "tokens": 1000000},
]


def get_shop_items():
    cached = cache_get("shop_items", ttl=20)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'shop_items'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            items = json.loads(row[0])
            if isinstance(items, list) and items:
                cache_set("shop_items", items, ttl=20)
                return items
        except Exception:
            pass
    cache_set("shop_items", list(DEFAULT_SHOP_ITEMS), ttl=20)
    return list(DEFAULT_SHOP_ITEMS)


def save_shop_items(items):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(items, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('shop_items', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("shop_items")


# ═══════════════ КЕЙСЫ ═══════════════
DEFAULT_CASES = [
    {
        "id": "bronze", "name": "🥉 Бронзовый",
        "desc": "Простой кейс", "stars": 5,
        "rewards": [
            {"type": "boost", "mult": 2, "minutes": 30, "chance": 60},
            {"type": "boost", "mult": 2, "minutes": 60, "chance": 30},
            {"type": "boost", "mult": 2, "minutes": 120, "chance": 10},
        ]
    },
    {
        "id": "silver", "name": "🥈 Серебряный",
        "desc": "Средний кейс", "stars": 15,
        "rewards": [
            {"type": "boost", "mult": 3, "minutes": 30, "chance": 50},
            {"type": "boost", "mult": 3, "minutes": 60, "chance": 35},
            {"type": "boost", "mult": 3, "minutes": 120, "chance": 15},
        ]
    },
    {
        "id": "gold", "name": "🥇 Золотой",
        "desc": "Лучший кейс", "stars": 35,
        "rewards": [
            {"type": "boost", "mult": 5, "minutes": 15, "chance": 40},
            {"type": "boost", "mult": 5, "minutes": 30, "chance": 30},
            {"type": "boost", "mult": 5, "minutes": 60, "chance": 20},
            {"type": "title", "title": "🎰 Лудоман", "chance": 8},
            {"type": "title", "title": "👑 Легенда", "chance": 2},
        ]
    },
]


def get_cases():
    cached = cache_get("cases", ttl=20)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'cases'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            cases = json.loads(row[0])
            if isinstance(cases, list) and cases:
                cache_set("cases", cases, ttl=20)
                return cases
        except Exception:
            pass
    cache_set("cases", [dict(c) for c in DEFAULT_CASES], ttl=20)
    return [dict(c) for c in DEFAULT_CASES]


def save_cases(cases):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(cases, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('cases', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("cases")


def get_case_by_id(case_id):
    for c in get_cases():
        if c["id"] == case_id:
            return c
    return None


def roll_case_reward(case):
    rewards = case["rewards"]
    total = sum(r.get("chance", 0) for r in rewards)
    if total <= 0:
        return rewards[0] if rewards else None
    roll = random.uniform(0, total)
    acc = 0
    for r in rewards:
        acc += r.get("chance", 0)
        if roll <= acc:
            return r
    return rewards[-1]


def apply_case_reward_to_inventory(user_id, reward):
    """Кладёт награду в инвентарь. Возвращает текст."""
    if reward["type"] == "boost":
        add_to_inventory(user_id, {
            "type": "boost", "mult": int(reward["mult"]),
            "minutes": int(reward["minutes"])
        })
        return f"⚡ Буст ×{reward['mult']} на {reward['minutes']} мин"
    if reward["type"] == "title":
        add_to_inventory(user_id, {"type": "title", "title": reward["title"]})
        return f"🏷️ Титул «{reward['title']}»"
    if reward["type"] == "vip":
        add_to_inventory(user_id, {"type": "vip", "vip_level": int(reward["vip_level"])})
        return f"👑 VIP уровень {reward['vip_level']}"
    return "🎁 Награда"


# ═══════════════ ДИЗАБЛ ИГР ═══════════════
def get_disabled_games():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'disabled_games'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        return set(row[0].split(',')) if row[0] else set()
    return set()


def save_disabled_games():
    conn = get_conn()
    c = conn.cursor()
    value = ','.join(disabled_games)
    c.execute("""INSERT INTO settings (key, value) VALUES ('disabled_games', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)


def load_settings():
    global disabled_games
    disabled_games = get_disabled_games()
    print(f"✅ Настройки: disabled_games = {disabled_games}")


def is_game_disabled(game):
    return game in disabled_games


# ═══════════════ РОЗЫГРЫШ ═══════════════
def create_giveaway(amount, minutes, creator_id):
    conn = get_conn()
    c = conn.cursor()
    ends_at = datetime.now() + timedelta(minutes=minutes)
    c.execute("""INSERT INTO giveaways (amount, ends_at, created_by, status)
                 VALUES (%s, %s, %s, 'active') RETURNING id""", (amount, ends_at, creator_id))
    gid = c.fetchone()[0]
    conn.commit()
    c.close()
    release_conn(conn)
    return gid, ends_at


def finish_giveaway(gid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, amount FROM giveaways WHERE id = %s AND status = 'active'", (gid,))
    row = c.fetchone()
    if not row:
        c.close()
        release_conn(conn)
        return None
    uid, amount = row
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, uid))
    c.execute("UPDATE giveaways SET status = 'finished', winner_id = %s WHERE id = %s", (uid, gid))
    conn.commit()
    c.close()
    release_conn(conn)
    return uid, amount


# ═══════════════ БЛЭКДЖЕК ═══════════════
def hand_score(cards):
    score = 0
    aces = 0
    for c in cards:
        val = c[:-1]
        if val == 'A':
            score += 11
            aces += 1
        elif val in ['K', 'Q', 'J', '10']:
            score += 10
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score


def create_deck():
    suits = ['♠', '♥', '♦', '♣']
    values = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = [v + s for s in suits for v in values]
    random.shuffle(deck)
    return deck


def fmt_hand(cards, hide_second=False):
    if hide_second and len(cards) >= 2:
        return f"{cards[0]} 🂠"
    return " ".join(cards)


def parse_target(message):
    args = message.text.split()
    if len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        return uid, username
    if (message.reply_to_message and message.reply_to_message.from_user
            and not message.reply_to_message.from_user.is_bot):
        t = message.reply_to_message.from_user
        return t.id, (t.username or t.first_name)
    return None, None
# ═══════════════ КЛАВИАТУРЫ ═══════════════
def group_url_kb(text="🎮 ИГРАТЬ В ГРУППЕ"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=GROUP_URL)]
    ])


def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


# ─── ГЛАВНОЕ МЕНЮ ───
def group_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu_bank"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
         InlineKeyboardButton(text="🎁 Бонус", callback_data="menu_daily")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop"),
         InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
        [InlineKeyboardButton(text="🎰 Кейсы", callback_data="menu_cases"),
         InlineKeyboardButton(text="🏪 Рынок", callback_data="menu_market")],
        [InlineKeyboardButton(text="🎯 Квесты", callback_data="menu_quests"),
         InlineKeyboardButton(text="🔗 Рефка", callback_data="menu_ref")],
    ])


def private_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 ИГРАТЬ В ГРУППЕ", url=GROUP_URL)],
        [InlineKeyboardButton(text="🎁 БОНУС", callback_data="menu_daily"),
         InlineKeyboardButton(text="🎰 КЕЙСЫ", callback_data="menu_cases")],
        [InlineKeyboardButton(text="🛒 МАГАЗИН", callback_data="menu_shop"),
         InlineKeyboardButton(text="👤 ПРОФИЛЬ", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🎒 ИНВЕНТАРЬ", callback_data="menu_inventory"),
         InlineKeyboardButton(text="🏪 РЫНОК", callback_data="menu_market")],
        [InlineKeyboardButton(text="🎯 КВЕСТЫ", callback_data="menu_quests"),
         InlineKeyboardButton(text="🏆 ТОП", callback_data="menu_top")],
        [InlineKeyboardButton(text="🔗 ПРИГЛАСИТЬ ДРУГА", callback_data="menu_ref"),
         InlineKeyboardButton(text="📊 СТАТИСТИКА", callback_data="menu_stats")],
        [InlineKeyboardButton(text="💎 MINI APP", web_app={"url": MINI_APP_URL})]
    ])


# ─── ИГРЫ ───
def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="info_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="info_slots")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="info_coin"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="info_bj")],
        [InlineKeyboardButton(text="💣 Мины", callback_data="info_mines"),
         InlineKeyboardButton(text="⚔️ Дуэль", callback_data="info_duel")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
    ])


def back_to_games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К играм", callback_data="menu_games")]
    ])


# ─── ПРОФИЛЬ ───
def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История", callback_data="menu_history"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton(text="🏷️ Титулы", callback_data="menu_mytitles"),
         InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


def history_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="hist_roulette"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="hist_slots")],
        [InlineKeyboardButton(text="💣 Мины", callback_data="hist_mines"),
         InlineKeyboardButton(text="🃏 Блэкджек", callback_data="hist_bj")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="hist_coin"),
         InlineKeyboardButton(text="⚔️ Дуэль", callback_data="hist_duel")],
        [InlineKeyboardButton(text="📋 Всё", callback_data="hist_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_profile")]
    ])


def mytitles_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_profile")]
    ])


# ─── ТОП ───
def top_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 По балансу", callback_data="top_balance"),
         InlineKeyboardButton(text="⭐ По XP", callback_data="top_xp")],
        [InlineKeyboardButton(text="🎮 По играм", callback_data="top_games"),
         InlineKeyboardButton(text="🏆 По победам", callback_data="top_wins")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


# ─── БАНК ───
def bank_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Положить", callback_data="bank_deposit"),
         InlineKeyboardButton(text="➖ Снять", callback_data="bank_withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


def bank_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_bank")]
    ])


# ─── МАГАЗИН ───
def shop_kb():
    items = get_shop_items()
    rows = []
    for i, it in enumerate(items):
        price_parts = []
        if it.get("stars"):
            price_parts.append(f"{it['stars']} ⭐")
        if it.get("tokens"):
            price_parts.append(f"{it['tokens']:,} 💎".replace(',', ' '))
        price = " / ".join(price_parts) if price_parts else "—"
        rows.append([InlineKeyboardButton(
            text=f"{it['name']} — {price}",
            callback_data=f"shop_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_item_kb(idx):
    items = get_shop_items()
    if idx < 0 or idx >= len(items):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_shop")]
        ])
    it = items[idx]
    rows = []
    if it.get("stars"):
        rows.append([InlineKeyboardButton(
            text=f"⭐ Купить за {it['stars']} Stars",
            callback_data=f"shop_buy_stars_{idx}"
        )])
    if it.get("tokens"):
        rows.append([InlineKeyboardButton(
            text=f"💎 Купить за {it['tokens']:,}".replace(',', ' '),
            callback_data=f"shop_buy_tokens_{idx}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── КЕЙСЫ ───
def cases_kb():
    cases = get_cases()
    rows = []
    for c in cases:
        rows.append([InlineKeyboardButton(
            text=f"{c['name']} — {c['stars']} ⭐",
            callback_data=f"case_buy_{c['id']}_{c['stars']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── ИНВЕНТАРЬ ───
def inventory_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷️ Титулы", callback_data="inv_titles"),
         InlineKeyboardButton(text="⚡ Бусты", callback_data="inv_boosts")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="inv_vip"),
         InlineKeyboardButton(text="🎰 Кейсы", callback_data="inv_cases")],
        [InlineKeyboardButton(text="📦 Всё", callback_data="inv_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


def inventory_list_kb(user_id, filter_type=None):
    inv = get_inventory(user_id)
    if filter_type:
        inv = [it for it in inv if it.get("type") == filter_type]
    rows = []
    for it in inv[:10]:  # первые 10
        t = it.get("type")
        if t == "boost":
            label = f"⚡ ×{it['mult']} / {it['minutes']}м"
        elif t == "title":
            label = f"🏷️ {it['title']}"
        elif t == "vip":
            label = f"👑 VIP {it['vip_level']}"
        elif t == "case":
            label = f"🎰 Кейс {it.get('case_id', '')}"
        else:
            label = "❓ Предмет"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"inv_view_{it['inv_id']}"
        )])
    back_target = "menu_inventory"
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_item_kb(inv_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Использовать", callback_data=f"inv_use_{inv_id}")],
        [InlineKeyboardButton(text="💰 Продать", callback_data=f"inv_sell_{inv_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_inventory")]
    ])


# ─── РЫНОК ───
def market_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить", callback_data="market_browse"),
         InlineKeyboardButton(text="💰 Продать", callback_data="market_sell")],
        [InlineKeyboardButton(text="📦 Мои лоты", callback_data="market_mylots")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


def market_lots_kb(lots, page=0, per_page=5):
    rows = []
    start = page * per_page
    end = start + per_page
    for i, lot in enumerate(lots[start:end]):
        real_idx = start + i
        t = lot.get("type")
        if t == "boost":
            label = f"⚡ ×{lot['payload']['mult']} / {lot['payload']['minutes']}м"
        elif t == "title":
            label = f"🏷️ {lot['payload']['title']}"
        elif t == "vip":
            label = f"👑 VIP {lot['payload']['vip_level']}"
        else:
            label = "❓"
        price = f"{lot['price']:,} 💎".replace(',', ' ')
        rows.append([InlineKeyboardButton(
            text=f"{label} — {price}",
            callback_data=f"market_buy_{real_idx}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"market_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}", callback_data="market_noop"))
    if end < len(lots):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"market_page_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def market_sell_kb(user_id):
    inv = get_inventory(user_id)
    rows = []
    for it in inv[:10]:
        t = it.get("type")
        if t == "boost":
            label = f"⚡ ×{it['mult']} / {it['minutes']}м"
        elif t == "title":
            label = f"🏷️ {it['title']}"
        elif t == "vip":
            label = f"👑 VIP {it['vip_level']}"
        else:
            label = "❓"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"market_sellitem_{it['inv_id']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── РЕФКА ───
def ref_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои рефералы", callback_data="ref_list")],
        [InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="ref_top")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


# ─── КВЕСТЫ ───
def quests_kb(user_id):
    quests = get_user_quests(user_id)
    rows = []
    for q in quests:
        if q["completed"] and not q["claimed"]:
            rows.append([InlineKeyboardButton(
                text=f"✅ {q['name']} (+{q['reward']:,})".replace(',', ' '),
                callback_data=f"quest_claim_{q['key']}"
            )])
        elif q["claimed"]:
            rows.append([InlineKeyboardButton(
                text=f"✔️ {q['name']}",
                callback_data="quest_noop"
            )])
        else:
            rows.append([InlineKeyboardButton(
                text=f"{q['name']} [{q['progress']}/{q['target']}]",
                callback_data="quest_noop"
            )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── РУЛЕТКА / БЖ / МИНЫ ───
def roulette_kb(bet=100):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное ×2", callback_data=f"bet_red_{bet}"),
         InlineKeyboardButton(text="⚫ Чёрное ×2", callback_data=f"bet_black_{bet}")],
        [InlineKeyboardButton(text="🟢 Зеро ×36", callback_data=f"bet_green_{bet}")],
        [InlineKeyboardButton(text="10", callback_data="setbet_10"),
         InlineKeyboardButton(text="100", callback_data="setbet_100"),
         InlineKeyboardButton(text="1K", callback_data="setbet_1000"),
         InlineKeyboardButton(text="MAX", callback_data="setbet_max")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
    ])


def bj_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="bj_hit"),
         InlineKeyboardButton(text="✋ Хватит", callback_data="bj_stand")]
    ])


def mines_level_kb(bet):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (3 💣)", callback_data=f"mines_start_easy_{bet}")],
        [InlineKeyboardButton(text="🟡 Средний (5 💣)", callback_data=f"mines_start_medium_{bet}")],
        [InlineKeyboardButton(text="🔴 Хардкор (10 💣)", callback_data=f"mines_start_hard_{bet}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_games")]
    ])


def mines_field_kb(user_id):
    game = mines_games.get(user_id)
    if not game:
        return None
    opened = game["opened"]
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in opened:
                if idx in game["mines_positions"]:
                    row.append(InlineKeyboardButton(text="💣", callback_data="mines_noop"))
                else:
                    row.append(InlineKeyboardButton(text="💎", callback_data="mines_noop"))
            else:
                row.append(InlineKeyboardButton(text="⬜", callback_data=f"mines_open_{idx}"))
        rows.append(row)
    if opened:
        mult = game["mult"]
        cashout = int(game["bet"] * mult)
        rows.append([InlineKeyboardButton(
            text=f"💰 Забрать ×{mult:.2f} ({cashout:,})".replace(',', ' '),
            callback_data="mines_cashout"
        )])
    else:
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mines_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── АДМИН-ПАНЕЛЬ (6 КАТЕГОРИЙ) ───
def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_cat_players"),
         InlineKeyboardButton(text="🎮 Игры", callback_data="admin_cat_games")],
        [InlineKeyboardButton(text="🛒 Контент", callback_data="admin_cat_content"),
         InlineKeyboardButton(text="💰 Экономика", callback_data="admin_cat_economy")],
        [InlineKeyboardButton(text="📢 Связь", callback_data="admin_cat_comm"),
         InlineKeyboardButton(text="📊 Мониторинг", callback_data="admin_cat_monitor")],
        [InlineKeyboardButton(text="🎮 Mini App", web_app={"url": MINI_APP_URL})],
        [InlineKeyboardButton(text="📋 Все команды", callback_data="admin_all_cmds")]
    ])


def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_players_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="admin_pi_info")],
        [InlineKeyboardButton(text="🚫 Ban / Unban", callback_data="admin_ban_start")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="admin_vip_start"),
         InlineKeyboardButton(text="🏷️ Титул", callback_data="admin_title_start")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="admin_bal_start"),
         InlineKeyboardButton(text="📊 XP", callback_data="admin_xp_start")],
        [InlineKeyboardButton(text="🔄 Reset", callback_data="admin_reset_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_games_kb():
    rows = []
    for key, name in GAME_NAMES.items():
        status = "❌" if key in disabled_games else "✅"
        rows.append([InlineKeyboardButton(
            text=f"{status} {name}",
            callback_data=f"admin_toggle_{key}"
        )])
    rows.append([InlineKeyboardButton(text="🎰 Event ×2", callback_data="admin_event"),
                 InlineKeyboardButton(text="🛠️ Тех.работы", callback_data="admin_maintenance")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_content_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Редактор магазина", callback_data="editshop_start")],
        [InlineKeyboardButton(text="🎰 Редактор кейсов", callback_data="editcases_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_economy_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Бонус игроку", callback_data="admin_bonus_start")],
        [InlineKeyboardButton(text="💎 Джекпот", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="🎁 Розыгрыш", callback_data="admin_giveaway_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_comm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_show")],
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="📋 Все игроки", callback_data="admin_all_players")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_monitor_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="🏆 Big Wins", callback_data="admin_bigwins_show")],
        [InlineKeyboardButton(text="📜 Логи игрока", callback_data="admin_logs_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


# ═══════════════ ФУНКЦИИ РЕНДЕРА ЭКРАНОВ ═══════════════
def profile_text(user_id, username):
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    vip = get_vip_info(xp)
    stats = get_user_stats(user_id)
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""
    boost = get_active_boost(user_id)
    boost_line = ""
    if boost:
        mins_left = int((boost[1] - datetime.now()).total_seconds() // 60)
        boost_line = f"\n⚡ Буст: <b>×{boost[0]}</b> ({mins_left} мин)"

    if is_unlimited(user_id):
        bal_line = "💎 Баланс: ♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"💎 Баланс: <b>{balance:,}</b>".replace(',', ' ')

    if vip["next_xp"] > vip["xp"]:
        progress = vip["xp"] - VIP_LEVELS[vip["level"]]["xp"]
        total = vip["next_xp"] - VIP_LEVELS[vip["level"]]["xp"]
        fill = int(progress / total * 10) if total > 0 else 0
        bar = "▰" * fill + "▱" * (10 - fill)
        xp_line = f"{bar} {progress}/{total} XP"
    else:
        xp_line = "🏆 МАКСИМАЛЬНЫЙ УРОВЕНЬ"

    return (
        f"👤 <b>ПРОФИЛЬ</b>\n\n"
        f"🎭 <b>{username}</b>{title_line}\n"
        f"{vip['icon']} <b>{vip['name']}</b>\n"
        f"{xp_line}{boost_line}\n\n"
        f"{bal_line}\n"
        f"🏦 Банк: <b>{bank:,}</b>\n"
        f"💰 Кешбэк: <b>{vip['cashback']}%</b>\n\n"
        f"🎮 Игр: <b>{stats['total_games']}</b>\n"
        f"🏆 Побед: <b>{stats['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{stats['winrate']}%</b>"
    ).replace(',', ' ')


def stats_text(user_id, username):
    s = get_user_stats(user_id)
    profit = s["profit"]
    profit_emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
    return (
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"🎭 <b>{username}</b>\n\n"
        f"🎮 Всего игр: <b>{s['total_games']}</b>\n"
        f"🏆 Побед: <b>{s['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{s['winrate']}%</b>\n\n"
        f"💰 Ставок: <b>{s['total_bet']:,}</b>\n"
        f"💵 Выигрышей: <b>{s['total_win']:,}</b>\n"
        f"{profit_emoji} Профит: <b>{profit:+,}</b>\n"
        f"🔥 Best: <b>{s['best_win']:,}</b>\n\n"
        f"🎯 Любимая: <b>{s['fav_game']}</b>"
    ).replace(',', ' ')


def history_text(user_id, username, game=None):
    logs = get_user_history(user_id, game=game, limit=15)
    title = f"📜 История: {game}" if game else "📜 История игр"
    if not logs:
        return f"{title}\n\nПока пусто..."
    txt = f"{title}\n\n"
    for i, (g, bet, win, detail, time) in enumerate(logs, 1):
        profit = win - bet
        emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
        txt += f"{i}. {emoji} <b>{g}</b> | {bet:,} → {win:,} | {time}\n".replace(',', ' ')
    return txt


def top_text(mode="balance"):
    if mode == "balance":
        rows = get_top(10); title = "💎 ТОП по БАЛАНСУ"
        def metric(r): return f"<b>{r[2]:,}</b>".replace(',', ' ')
    elif mode == "xp":
        rows = get_top_xp(10); title = "⭐ ТОП по XP"
        def metric(r): return f"<b>{(r[3] or 0):,} XP</b>".replace(',', ' ')
    elif mode == "games":
        rows = get_top_games(10); title = "🎮 ТОП по ИГРАМ"
        def metric(r): return f"<b>{r[4]} игр</b>"
    elif mode == "wins":
        rows = get_top_wins(10); title = "🏆 ТОП по ПОБЕДАМ"
        def metric(r): return f"<b>{r[4]} побед</b>"
    else:
        rows = get_top(10); title = "🏆 ТОП-10"
        def metric(r): return f"<b>{r[2]:,}</b>".replace(',', ' ')

    if not rows:
        return f"🏆 <b>{title}</b>\n\nПока нет игроков!"

    txt = f"🏆 <b>{title}</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        uid, uname = row[0], row[1]
        xp = row[3] or 0
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        vip = get_vip_info(xp)
        vip_icon = f" {vip['icon']}" if xp else ""
        t = get_main_title(uid)
        title_str = f" 🏷️{t}" if t else ""
        txt += f"{medal}{vip_icon} {uname}{title_str} — {metric(row)}\n"
    return txt


def bank_text(user_id, username):
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    total = clamp(balance + bank)
    daily_interest = int(bank * 0.05) if bank > 0 else 0
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"<b>{balance:,}</b> 💎".replace(',', ' ')
    return (
        f"🏦 <b>БАНК</b>\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"💎 Баланс: {bal_line}\n"
        f"🏦 В банке: <b>{bank:,}</b> 💎\n"
        f"📊 Всего: <b>{total:,}</b> 💎\n\n"
        f"📈 Проценты:\n"
        f"💵 Ставка: <b>5% в день</b>\n"
        f"🎁 За сутки: <b>+{daily_interest:,}</b> 💎\n\n"
        f"👇 Выбери действие:"
    ).replace(',', ' ')


def shop_text():
    items = get_shop_items()
    if not items:
        return "🛒 <b>МАГАЗИН</b>\n\nПока пусто..."
    txt = "🛒 <b>МАГАЗИН</b>\n\n"
    txt += "<i>Бусты, титулы, VIP</i>\n\n"
    for it in items:
        price_parts = []
        if it.get("stars"):
            price_parts.append(f"{it['stars']} ⭐")
        if it.get("tokens"):
            price_parts.append(f"{it['tokens']:,} 💎".replace(',', ' '))
        price = " / ".join(price_parts) if price_parts else "—"
        txt += f"{it['name']} — {price}\n"
    txt += "\n👇 Выбери товар:"
    return txt


def shop_item_text(idx):
    items = get_shop_items()
    if idx < 0 or idx >= len(items):
        return "❌ Товар не найден"
    it = items[idx]
    price_parts = []
    if it.get("stars"):
        price_parts.append(f"{it['stars']} ⭐")
    if it.get("tokens"):
        price_parts.append(f"{it['tokens']:,} 💎".replace(',', ' '))
    price = " / ".join(price_parts) if price_parts else "—"
    return (
        f"🛒 <b>{it['name']}</b>\n\n"
        f"📝 {it.get('desc', '')}\n\n"
        f"💰 Цена: <b>{price}</b>\n\n"
        f"👇 Выбери способ оплаты:"
    )


def cases_text():
    cases = get_cases()
    if not cases:
        return "🎰 <b>КЕЙСЫ</b>\n\nПока пусто..."
    txt = "🎰 <b>КЕЙСЫ</b>\n\n"
    for c in cases:
        txt += f"{c['name']} — {c['stars']} ⭐\n"
    txt += "\n💎 Покупка за Telegram Stars\n🎁 Внутри — бусты, титулы, VIP\n\n👇 Выбери кейс:"
    return txt


def inventory_text(user_id, filter_type=None):
    inv = get_inventory(user_id)
    if filter_type:
        inv = [it for it in inv if it.get("type") == filter_type]
    title_map = {
        None: "🎒 ИНВЕНТАРЬ",
        "boost": "⚡ МОИ БУСТЫ",
        "title": "🏷️ МОИ ТИТУЛЫ",
        "vip": "👑 МОИ VIP",
        "case": "🎰 МОИ КЕЙСЫ",
    }
    title = title_map.get(filter_type, "🎒 ИНВЕНТАРЬ")
    if not inv:
        return f"{title}\n\nПусто..."
    txt = f"{title}\n\n"
    txt += f"📦 Всего: <b>{len(inv)}</b>\n\n"
    for it in inv[:10]:
        t = it.get("type")
        if t == "boost":
            txt += f"⚡ ×{it['mult']} / {it['minutes']}м\n"
        elif t == "title":
            txt += f"🏷️ {it['title']}\n"
        elif t == "vip":
            txt += f"👑 VIP {it['vip_level']}\n"
        elif t == "case":
            txt += f"🎰 Кейс {it.get('case_id', '')}\n"
    if len(inv) > 10:
        txt += f"\n...и ещё {len(inv) - 10}"
    return txt


def ref_text(user_id, username):
    count, earnings = get_ref_stats(user_id)
    link = f"https://t.me/{(await_bot_username())}?start=ref_{user_id}"
    return (
        f"🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{earnings:,}</b> 💎\n\n"
        f"🎁 За каждого друга: <b>+5 000</b> 💎 тебе и ему\n"
        f"📈 +5% с его выигрышей (3 уровня)\n\n"
        f"🔗 Твоя ссылка:\n"
        f"<code>{link}</code>\n\n"
        f"👇 Подробнее:"
    ).replace(',', ' ')


_bot_username_cache = None
def await_bot_username():
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    return "gold1_casino_bot"


def market_text():
    lots = get_market_lots()
    txt = "🏪 <b>РЫНОК</b>\n\n"
    txt += f"📊 Активных лотов: <b>{len(lots)}</b>\n\n"
    txt += "👇 Выбери раздел:"
    return txt


# ─── РЫНОК: функции хранилища ───
def get_market_lots():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'market_lots'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return []
    return []


def save_market_lots(lots):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(lots, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('market_lots', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)


def add_market_lot(user_id, username, item, price):
    lots = get_market_lots()
    lot = {
        "id": f"lot_{int(time.time()*1000)}_{random.randint(100,999)}",
        "seller_id": user_id,
        "seller_name": username,
        "type": item.get("type"),
        "payload": {k: v for k, v in item.items() if k not in ("inv_id", "obtained_at", "type")},
        "price": price,
        "created_at": datetime.now().isoformat(),
    }
    lots.append(lot)
    save_market_lots(lots)
    return lot["id"]


def buy_market_lot(buyer_id, lot_idx):
    lots = get_market_lots()
    if lot_idx < 0 or lot_idx >= len(lots):
        return False, "❌ Лот не найден"
    lot = lots[lot_idx]
    if lot["seller_id"] == buyer_id:
        return False, "❌ Нельзя купить свой лот"
    buyer_balance = get_balance(buyer_id)
    price = lot["price"]
    if buyer_balance < price and not is_unlimited(buyer_id):
        return False, f"❌ Недостаточно! Нужно {price:,} 💎".replace(',', ' ')
    # Списание у покупателя
    set_balance(buyer_id, -price)
    # Комиссия 5% → джекпот
    commission = int(price * 0.05)
    seller_gets = price - commission
    global jackpot_amount
    jackpot_amount += commission
    # Начисление продавцу
    set_balance(lot["seller_id"], seller_gets)
    # Передача предмета
    new_item = dict(lot["payload"])
    new_item["type"] = lot["type"]
    add_to_inventory(buyer_id, new_item)
    # Удаление лота
    lots.pop(lot_idx)
    save_market_lots(lots)
    return True, (
        f"✅ Куплено!\n"
        f"💰 Цена: <b>{price:,}</b> 💎\n"
        f"💸 Продавцу: <b>{seller_gets:,}</b> 💎\n"
        f"🎰 Комиссия в джекпот: <b>{commission:,}</b> 💎"
    ).replace(',', ' ')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ═══════════════ /start ═══════════════
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)

    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return

    # Обработка реферальной ссылки: /start ref_12345
    args = message.text.split()
    if len(args) >= 2 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                ok = set_referrer(user_id, referrer_id)
                if ok:
                    await message.answer(
                        f"🎉 <b>Ты пришёл по приглашению!</b>\n\n"
                        f"💰 Тебе начислено <b>+5 000</b> 💎\n"
                        f"👤 Пригласивший тоже получил бонус",
                        parse_mode="HTML"
                    )
        except Exception:
            pass

    is_private = message.chat.type == 'private'

    # Админ в личке — панель
    if is_private and user_id == ADMIN_ID:
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        txt = (
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👤 <b>{username}</b>\n"
            f"💎 Баланс: <b>{balance:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n\n"
            f"📋 <b>Выбери раздел:</b>"
        ).replace(',', ' ')
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
        return

    # Бонус новичка
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT got_start_bonus FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    got_bonus = row[0] if row and row[0] else False
    c.close()
    release_conn(conn)

    bonus_text = ""
    if not got_bonus:
        set_balance(user_id, 5000)
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET got_start_bonus = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        c.close()
        release_conn(conn)
        bonus_text = "\n\n🎁 <b>БОНУС НОВИЧКА: +5 000 токенов!</b>"

    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    vip = get_vip_info(xp)
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""

    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"💎 <b>{balance:,}</b> токенов".replace(',', ' ')

    vip_line = f"{vip['icon']} {vip['name']} | XP: {xp}{title_line}"

    if is_private:
        txt = (
            f"🎰 <b>ДОБРО ПОЖАЛОВАТЬ В ТОКЕНЫ!</b>\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"{vip_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{bank:,}</b>{bonus_text}\n\n"
            f"🎮 <b>ЧТО УМЕЕТ БОТ:</b>\n"
            f"🎮 <b>Игры</b> — рулетка, слоты, мины, блэкджек, монетка, дуэль\n"
            f"🎁 <b>Бонус</b> — +10 000 💎 раз в 24 часа\n"
            f"🎰 <b>Кейсы</b> — за ⭐ Stars: бусты, титулы, VIP\n"
            f"🛒 <b>Магазин</b> — покупки за ⭐ Stars и 💎 токены\n"
            f"🎒 <b>Инвентарь</b> — все твои предметы\n"
            f"🏪 <b>Рынок</b> — продай друзьям за токены\n"
            f"🎯 <b>Квесты</b> — задания с наградами\n"
            f"🔗 <b>Рефка</b> — приглашай друзей, получай бонусы\n\n"
            f"💡 <b>Играть нужно в группе!</b>\n"
            f"Жми кнопку ниже 👇"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=private_kb())
    else:
        txt = (
            f"🎰 <b>ТОКЕНЫ</b>\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"{vip_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{bank:,}</b>{bonus_text}\n\n"
            f"🎮 Нажми <b>Игры</b>!\n\n"
            f"<code>б</code> — баланс | <code>топ</code> — топ\n"
            f"<code>профиль</code> — профиль | <code>квесты</code> — квесты\n"
            f"<code>банк</code> — банк | <code>дуэль 1000 @user</code>\n"
            f"<code>мины 100</code> — Мины 💣 | <code>бж 100</code> — блэкджек\n"
            f"<code>спин 100</code> — слоты | <code>орёл 100</code> — монетка\n"
            f"<code>к/ч/з 100</code> — рулетка | <code>го</code> — запуск"
        ).replace(',', ' ')
        await message.answer(txt, parse_mode="HTML", reply_markup=group_kb())


# ═══════════════ /admin ═══════════════
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    txt = (
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"👤 <b>{username}</b>\n"
        f"💎 Баланс: <b>{balance:,}</b>\n"
        f"🏦 Банк: <b>{bank:,}</b>\n\n"
        f"📋 <b>Выбери раздел:</b>"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())


# ═══════════════ /profile ═══════════════
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    await message.answer(profile_text(user_id, username), parse_mode="HTML", reply_markup=profile_kb())


# ═══════════════ /quests ═══════════════
@dp.message(Command("quests"))
async def cmd_quests(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    quests = get_user_quests(user_id)
    txt = "🎯 <b>КВЕСТЫ</b>\n\nВыполняй задания → получай награды!\n\n"
    for q in quests:
        if q["claimed"]:
            txt += f"✔️ {q['name']}\n"
        elif q["completed"]:
            txt += f"✅ {q['name']} → жми Забрать!\n"
        else:
            txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
    await message.answer(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))


# ═══════════════ /balance ═══════════════
@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    if is_unlimited(user_id):
        await message.answer(
            f"💰 <b>Баланс</b>\n\n👤 {username}\n♾️ <b>БЕЗЛИМИТ</b>\n🏦 Банк: <b>{bank:,}</b>".replace(',', ' '),
            parse_mode="HTML")
    else:
        await message.answer(
            f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 Баланс: <b>{balance:,}</b>\n🏦 Банк: <b>{bank:,}</b>".replace(',', ' '),
            parse_mode="HTML")


# ═══════════════ /top ═══════════════
@dp.message(Command("top"))
async def cmd_top(message: Message):
    await message.answer(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())


# ═══════════════ /shop ═══════════════
@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    await message.answer(shop_text(), parse_mode="HTML", reply_markup=shop_kb())


# ═══════════════ /cases ═══════════════
@dp.message(Command("cases"))
async def cmd_cases(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    await message.answer(cases_text(), parse_mode="HTML", reply_markup=cases_kb())


# ═══════════════ /inventory ═══════════════
@dp.message(Command("inventory", "inv"))
async def cmd_inventory(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    await message.answer(
        inventory_text(user_id),
        parse_mode="HTML",
        reply_markup=inventory_main_kb()
    )


# ═══════════════ /ref ═══════════════
@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    # Получаем username бота
    try:
        me = await bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = "gold1_casino_bot"

    count, earnings = get_ref_stats(user_id)
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    txt = (
        f"🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{earnings:,}</b> 💎\n\n"
        f"🎁 За каждого друга: <b>+5 000</b> 💎 тебе и ему\n"
        f"📈 +5% с его выигрышей (3 уровня)\n\n"
        f"🔗 Твоя ссылка:\n"
        f"<code>{link}</code>\n\n"
        f"👇 Подробнее:"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML", reply_markup=ref_kb())


# ═══════════════ /market ═══════════════
@dp.message(Command("market"))
async def cmd_market(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    await message.answer(market_text(), parse_mode="HTML", reply_markup=market_main_kb())


# ═══════════════ /give ═══════════════
@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 2 and args[1].lower() in ['unlimited', 'безлимит', '∞']:
        set_unlimited(message.from_user.id, True)
        await message.answer("♾️ <b>БЕЗЛИМИТ АКТИВИРОВАН!</b>", parse_mode="HTML")
        return
    if len(args) >= 2 and args[1].lower() in ['all', 'off', 'выкл']:
        set_unlimited(message.from_user.id, False)
        await message.answer("✅ <b>БЕЗЛИМИТ ОТКЛЮЧЁН</b>", parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except Exception:
            return
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, amount)
        await message.answer(f"✅ <b>+{amount:,}</b> → @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except Exception:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, amount)
    await message.answer(f"✅ <b>+{amount:,}</b> → {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /take ═══════════════
@dp.message(Command("take"))
async def cmd_take(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 2 and args[1].lower() == 'all':
        if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
            await message.answer("❌ Ответь на сообщение игрока", parse_mode="HTML")
            return
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        tb = get_balance(target.id)
        if tb <= 0:
            await message.answer("❌ Нет фишек!", parse_mode="HTML")
            return
        set_balance(target.id, -tb)
        await message.answer(f"✅ <b>Забрано всё!</b> -{tb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except Exception:
            return
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, -amount)
        await message.answer(f"✅ <b>-{amount:,}</b> ← @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except Exception:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, -amount)
    await message.answer(f"✅ <b>-{amount:,}</b> ← {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /ban ═══════════════
@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    elif len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        if uid:
            set_banned(uid, True)
            await message.answer(f"🚫 <b>@{username} забанен!</b>", parse_mode="HTML")
        else:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    if not target:
        await message.answer("❌ Ответь или <code>/ban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, True)
    await message.answer(f"🚫 <b>{target.username or target.first_name} забанен!</b>", parse_mode="HTML")


# ═══════════════ /unban ═══════════════
@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    elif len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        if uid:
            set_banned(uid, False)
            await message.answer(f"✅ <b>@{username} разбанен!</b>", parse_mode="HTML")
        else:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    if not target:
        await message.answer("❌ Ответь или <code>/unban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, False)
    await message.answer(f"✅ <b>{target.username or target.first_name} разбанен!</b>", parse_mode="HTML")


# ═══════════════ /broadcast ═══════════════
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ <code>/broadcast Текст</code>", parse_mode="HTML")
        return
    text = args[1]
    uids = get_all_user_ids()
    if not uids:
        await message.answer("❌ Нет игроков", parse_mode="HTML")
        return
    sent, failed = 0, 0
    for uid in uids:
        try:
            await bot.send_message(uid, f"📢 <b>РАССЫЛКА</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await message.answer(f"📢 <b>Готово</b>\n✅ {sent} | ❌ {failed}", parse_mode="HTML")


# ═══════════════ /stats ═══════════════
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    conn = get_conn()
    c = conn.cursor()
    if len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        c.execute("SELECT user_id, username, balance, bank, xp FROM users WHERE username = %s", (username,))
        row = c.fetchone()
        if not row:
            c.close()
            release_conn(conn)
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        uid, uname, bal, bank, xp = row
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (uid,))
        tg = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (uid,))
        tw = c.fetchone()[0]
        c.close()
        release_conn(conn)
        vip = get_vip_info(xp or 0)
        txt = (
            f"📊 <b>СТАТИСТИКА ИГРОКА</b>\n\n"
            f"👤 {uname} (<code>{uid}</code>)\n"
            f"{vip['icon']} {vip['name']} | XP: {xp}\n"
            f"💎 Баланс: <b>{bal:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n\n"
            f"🎮 Игр: <b>{tg}</b>\n"
            f"🏆 Побед: <b>{tw}</b>"
        ).replace(',', ' ')
        await message.answer(txt, parse_mode="HTML")
        return
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
    total_balance = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE unlimited = TRUE")
    unlimited_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM game_log")
    total_games = c.fetchone()[0]
    c.close()
    release_conn(conn)
    txt = (
        f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Игроков: <b>{total_users}</b>\n"
        f"💎 Токенов: <b>{total_balance:,}</b>\n"
        f"🎮 Игр: <b>{total_games}</b>\n\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"♾️ Безлимитов: <b>{unlimited_count}</b>"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")


# ═══════════════ /event ═══════════════
@dp.message(Command("event"))
async def cmd_event(message: Message):
    global event_double
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
        await message.answer(f"🎰 <b>ИВЕНТ ×2</b>\n\nСтатус: <b>{status}</b>\n\n<code>/event double on/off</code>", parse_mode="HTML")
        return
    if args[1].lower() == "double" and len(args) >= 3:
        mode = args[2].lower()
        if mode == "on":
            event_double = True
            await message.answer("🎰 <b>ИВЕНТ ×2 ВКЛЮЧЁН!</b>", parse_mode="HTML")
        elif mode == "off":
            event_double = False
            await message.answer("🎰 <b>ИВЕНТ ×2 ВЫКЛЮЧЕН</b>", parse_mode="HTML")


# ═══════════════ /maintenance ═══════════════
@dp.message(Command("maintenance"))
async def cmd_maintenance(message: Message):
    global maintenance_on
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
        await message.answer(f"🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nСтатус: <b>{status}</b>", parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "on":
        maintenance_on = True
        await message.answer("🛠️ <b>ТЕХ.РАБОТЫ ВКЛЮЧЕНЫ</b>", parse_mode="HTML")
    elif sub == "off":
        maintenance_on = False
        await message.answer("✅ <b>ТЕХ.РАБОТЫ ВЫКЛЮЧЕНЫ</b>", parse_mode="HTML")


# ═══════════════ /bonus ═══════════════
@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("🎁 <code>/bonus @user 50000</code>\n<code>/bonus all 10000</code>", parse_mode="HTML")
        return
    target = args[1]
    try:
        amount = int(args[2])
    except Exception:
        await message.answer("❌ Неверная сумма", parse_mode="HTML")
        return
    if target.lower() == 'all':
        uids = get_all_user_ids()
        count = 0
        for uid in uids:
            try:
                set_balance(uid, amount)
                count += 1
            except Exception:
                pass
        await message.answer(f"🎁 <b>+{amount:,} всем!</b>\n👥 {count}".replace(',', ' '), parse_mode="HTML")
        return
    if target.startswith('@'):
        username = target[1:]
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, amount)
        await message.answer(f"🎁 <b>+{amount:,}</b> → @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /jackpot ═══════════════
@dp.message(Command("jackpot"))
async def cmd_jackpot(message: Message):
    global jackpot_amount
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer(f"💎 <b>ДЖЕКПОТ</b>: <b>{jackpot_amount:,}</b>".replace(',', ' '), parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "set" and len(args) >= 3:
        try:
            amount = int(args[2])
        except Exception:
            return
        jackpot_amount = clamp(amount)
        await message.answer(f"💎 <b>Установлен</b>: {jackpot_amount:,}".replace(',', ' '), parse_mode="HTML")
    elif sub == "reset":
        jackpot_amount = 10000
        await message.answer("💎 <b>Сброшен</b>: 10 000", parse_mode="HTML")
    elif sub == "status":
        await message.answer(f"💎 <b>Текущий</b>: {jackpot_amount:,}".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /set_xp ═══════════════
@dp.message(Command("set_xp"))
async def cmd_set_xp(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ <code>/set_xp @user 1000</code>", parse_mode="HTML")
        return
    username = args[1][1:] if args[1].startswith('@') else args[1]
    try:
        amount = int(args[2])
    except Exception:
        return
    uid = get_user_id_by_username(username)
    if not uid:
        await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET xp = %s, vip_level = %s WHERE user_id = %s",
              (amount, get_vip_level(amount), uid))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{uid}")
    await message.answer(f"✅ @{username} XP = <b>{amount}</b>".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /bigwins ═══════════════
@dp.message(Command("bigwins"))
async def cmd_bigwins(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    wins = get_big_wins(limit=10, min_win=100000)
    if not wins:
        await message.answer("📊 Крупных выигрышей пока нет (мин. 100K)", parse_mode="HTML")
        return
    txt = "🏆 <b>ТОП-10 КРУПНЫХ ВЫИГРЫШЕЙ</b>\n\n"
    for i, (uname, game, win, time) in enumerate(wins, 1):
        txt += f"{i}. <b>{uname}</b> — {game} +{win:,} ({time})\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")


# ═══════════════ /setbal ═══════════════
@dp.message(Command("setbal"))
async def cmd_setbal(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 and not message.reply_to_message:
        await message.answer("❌ <code>/setbal @user 1000</code>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        try:
            amount = int(args[1])
        except Exception:
            await message.answer("❌ Неверная сумма", parse_mode="HTML")
            return
        set_balance_exact(target.id, amount)
        await message.answer(f"✅ <b>{target.username or target.first_name}</b>: баланс = <b>{amount:,}</b>".replace(',', ' '), parse_mode="HTML")
        return
    uid, uname = parse_target(message)
    if not uid:
        await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
        return
    try:
        amount = int(args[2])
    except Exception:
        await message.answer("❌ Неверная сумма", parse_mode="HTML")
        return
    set_balance_exact(uid, amount)
    await message.answer(f"✅ <b>@{uname}</b>: баланс = <b>{amount:,}</b>".replace(',', ' '), parse_mode="HTML")


# ═══════════════ /resetuser ═══════════════
@dp.message(Command("resetuser"))
async def cmd_resetuser(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message:
        await message.answer("❌ <code>/resetuser @user</code>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        reset_user(target.id)
        await message.answer(f"✅ <b>{target.username or target.first_name}</b> полностью сброшен", parse_mode="HTML")
        return
    uid, uname = parse_target(message)
    if not uid:
        await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
        return
    reset_user(uid)
    await message.answer(f"✅ <b>@{uname}</b> полностью сброшен", parse_mode="HTML")


# ═══════════════ /logs ═══════════════
@dp.message(Command("logs"))
async def cmd_logs(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message:
        await message.answer("❌ <code>/logs @user</code>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        uid = target.id
        uname = target.username or target.first_name
    else:
        uid, uname = parse_target(message)
    if not uid:
        await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
        return
    logs = get_user_logs(uid, 10)
    if not logs:
        await message.answer(f"📜 У @{uname} пока нет игр", parse_mode="HTML")
        return
    txt = f"📜 <b>Последние 10 игр @{uname}</b>\n\n"
    for i, (game, bet, win, detail, time) in enumerate(logs, 1):
        profit = win - bet
        emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
        txt += f"{i}. {emoji} <b>{game}</b> | {bet:,} → {win:,} | {detail} | {time}\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")


# ═══════════════ /vip ═══════════════
@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 and not message.reply_to_message:
        await message.answer("❌ <code>/vip @user 3</code>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        try:
            level = int(args[1])
        except Exception:
            await message.answer("❌ Уровень 0-4", parse_mode="HTML")
            return
        if not 0 <= level <= 4:
            await message.answer("❌ Уровень 0-4", parse_mode="HTML")
            return
        set_vip_level(target.id, level)
        v = VIP_LEVELS[level]
        await message.answer(f"✅ <b>{target.username or target.first_name}</b> → {v['icon']} {v['name']}", parse_mode="HTML")
        return
    uid, uname = parse_target(message)
    if not uid:
        await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
        return
    try:
        level = int(args[2])
    except Exception:
        await message.answer("❌ Уровень 0-4", parse_mode="HTML")
        return
    if not 0 <= level <= 4:
        await message.answer("❌ Уровень 0-4", parse_mode="HTML")
        return
    set_vip_level(uid, level)
    v = VIP_LEVELS[level]
    await message.answer(f"✅ <b>@{uname}</b> → {v['icon']} {v['name']}", parse_mode="HTML")


# ═══════════════ /title ═══════════════
@dp.message(Command("title"))
async def cmd_title(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ <code>/title @user Легенда</code>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        title_text = ' '.join(args[1:])
        if title_text.lower() == 'clear':
            clear_user_titles(target.id)
            await message.answer(f"✅ Титулы очищены", parse_mode="HTML")
            return
        add_title(target.id, title_text, message.from_user.id)
        await message.answer(f"🏷️ → <b>{title_text}</b>", parse_mode="HTML")
        return
    uid, uname = parse_target(message)
    if not uid:
        await message.answer(f"❌ @{uname} не найден", parse_mode="HTML")
        return
    if len(args) < 3:
        await message.answer("❌ <code>/title @user Легенда</code>", parse_mode="HTML")
        return
    title_text = args[2]
    if title_text.lower() == 'clear':
        clear_user_titles(uid)
        await message.answer(f"✅ Титулы очищены", parse_mode="HTML")
        return
    add_title(uid, title_text, message.from_user.id)
    await message.answer(f"🏷️ <b>@{uname}</b> → <b>{title_text}</b>", parse_mode="HTML")


# ═══════════════ /games ═══════════════
@dp.message(Command("games"))
async def cmd_games(message: Message):
    global disabled_games
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or args[1].lower() == "list":
        txt = "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n"
        for key, name in GAME_NAMES.items():
            status = "❌ ВЫКЛ" if key in disabled_games else "✅ ВКЛ"
            txt += f"{name} — {status}\n"
        txt += "\n📋 <code>/games on/off slots</code>"
        await message.answer(txt, parse_mode="HTML")
        return
    if len(args) < 3:
        await message.answer("❌ <code>/games on/off slots</code>", parse_mode="HTML")
        return
    action = args[1].lower()
    game = args[2].lower()
    if action not in ["on", "off"]:
        await message.answer("❌ on / off", parse_mode="HTML")
        return
    if game == "all":
        if action == "off":
            disabled_games = set(GAME_NAMES.keys())
        else:
            disabled_games = set()
        save_disabled_games()
        await message.answer(f"✅ Все игры: {'ВЫКЛ' if action == 'off' else 'ВКЛ'}", parse_mode="HTML")
        return
    if game not in GAME_NAMES:
        await message.answer(f"❌ Не найдено: {', '.join(GAME_NAMES.keys())}", parse_mode="HTML")
        return
    if action == "off":
        disabled_games.add(game)
        save_disabled_games()
        await message.answer(f"❌ <b>{GAME_NAMES[game]}</b> выключена", parse_mode="HTML")
    else:
        disabled_games.discard(game)
        save_disabled_games()
        await message.answer(f"✅ <b>{GAME_NAMES[game]}</b> включена", parse_mode="HTML")


# ═══════════════ /active ═══════════════
@dp.message(Command("active"))
async def cmd_active(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_recent_users(minutes=5, limit=20)
    if not users:
        await message.answer("📊 За последние 5 минут никто не играл", parse_mode="HTML")
        return
    txt = "📊 <b>Активные за 5 минут</b>\n\n"
    for i, (uid, uname, bal) in enumerate(users, 1):
        txt += f"{i}. <b>{uname}</b> — 💎 {bal:,}\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")


# ═══════════════ /giveaway ═══════════════
@dp.message(Command("giveaway"))
async def cmd_giveaway(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Формат: /giveaway 10000 30m", parse_mode="HTML")
        return
    amount = int(args[1]) if args[1].isdigit() else 0
    if amount == 0:
        return
    time_str = args[2].lower()
    minutes = 0
    if time_str.endswith('h'):
        minutes = int(time_str[:-1]) * 60
    elif time_str.endswith('m'):
        minutes = int(time_str[:-1])
    if minutes == 0:
        return
    is_group = message.chat.id < 0
    if is_group:
        members = get_group_members(message.chat.id)
        if not members:
            await message.answer("В этой группе ещё никто не играл", parse_mode="HTML")
            return
        users = [m[0] for m in members]
        scope = f"группы ({len(users)} чел.)"
    else:
        users = get_all_user_ids()
        scope = f"всех игроков ({len(users)} чел.)"
    gid, ends_at = create_giveaway(amount, minutes, message.from_user.id)
    await message.answer(
        f"🎁 <b>РОЗЫГРЫШ ЗАПУЩЕН!</b>\n\n"
        f"💰 Приз: <b>{amount:,}</b>\n"
        f"👥 {scope}\n"
        f"⏱️ До: <b>{(ends_at + timedelta(hours=3)).strftime('%H:%M:%S')}</b>".replace(',', ' '),
        parse_mode="HTML"
    )
    count = 0
    for uid in users:
        try:
            await bot.send_message(
                uid,
                f"🎁 <b>РОЗЫГРЫШ!</b>\n\n"
                f"💰 Приз: <b>{amount:,}</b>\n"
                f"⏱️ До: <b>{(ends_at + timedelta(hours=3)).strftime('%H:%M')}</b>".replace(',', ' '),
                parse_mode="HTML"
            )
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"Уведомлено: {count}", parse_mode="HTML")


# ═══════════════ /editshop, /editcases ═══════════════
@dp.message(Command("editshop", "editboost"))
async def cmd_editshop(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if message.chat.type != 'private':
        await message.answer("⚠️ Редактор работает только в личке с ботом!", parse_mode="HTML")
        return
    edit_shop_state.pop(message.from_user.id, None)
    await message.answer(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())


@dp.message(Command("editcases"))
async def cmd_editcases(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if message.chat.type != 'private':
        await message.answer("⚠️ Редактор работает только в личке с ботом!", parse_mode="HTML")
        return
    edit_case_state.pop(message.from_user.id, None)
    await message.answer(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
    # ═══════════════ ГЛАВНЫЙ CALLBACK HANDLER ═══════════════
@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)

    if call.message and call.message.chat and call.message.chat.id < 0:
        track_group_member(call.message.chat.id, user_id, username)

    if is_banned(user_id):
        await call.answer("🚫 ВЫ ЗАБЛОКИРОВАНЫ", show_alert=True)
        return

    if maintenance_on and user_id != ADMIN_ID:
        await call.answer("🛠️ Тех.работы. Попробуй позже!", show_alert=True)
        return

    # ─── ЗАПРЕТ ИГР В ЛИЧКЕ ───
    game_prefixes = ("bet_", "group_bet_", "mines_", "bj_", "setbet_")
    if data.startswith(game_prefixes):
        chat_type = call.message.chat.type if call.message and call.message.chat else "private"
        if chat_type == "private" and user_id != ADMIN_ID:
            try:
                await call.message.answer(
                    "🎮 <b>Играть можно только в группе!</b>\n\n👇 Жми кнопку ниже:",
                    parse_mode="HTML",
                    reply_markup=group_url_kb("🎮 ПЕРЕЙТИ В ГРУППУ")
                )
            except Exception:
                pass
            await call.answer("🎮 Только в группе!", show_alert=True)
            return

    # ═══════════════ ПОКУПКА БУСТА ═══════════════
    if data.startswith("buy_boost_"):
        parts = data.split("_")
        try:
            mult = int(parts[2]); minutes = int(parts[3]); stars = int(parts[4])
        except Exception:
            await call.answer("❌ Ошибка товара", show_alert=True)
            return
        items = get_shop_items()
        actual = next((it for it in items if it.get("mult") == mult and it.get("minutes") == minutes), None)
        if not actual or actual.get("stars") != stars:
            await call.answer("❌ Товар изменился. Открой /shop заново.", show_alert=True)
            return
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"Буст ×{mult} на {minutes} мин",
                description=f"Личный множитель ×{mult} на {minutes} минут",
                payload=f"boost_{mult}_{minutes}",
                currency="XTR",
                prices=[LabeledPrice(label=f"×{mult} на {minutes} мин", amount=stars)],
            )
        except Exception as e:
            print(f"Ошибка инвойса: {e}")
        return

    # ═══════════════ МАГАЗИН 2.0 ═══════════════
    if data.startswith("shop_item_"):
        try:
            idx = int(data.replace("shop_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        try:
            await call.message.edit_text(shop_item_text(idx), parse_mode="HTML", reply_markup=shop_item_kb(idx))
        except Exception:
            pass
        await call.answer()
        return

    if data.startswith("shop_buy_stars_"):
        try:
            idx = int(data.replace("shop_buy_stars_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        items = get_shop_items()
        if idx < 0 or idx >= len(items):
            await call.answer("❌ Товар не найден", show_alert=True)
            return
        it = items[idx]
        stars = it.get("stars", 0)
        if stars <= 0:
            await call.answer("❌ Товар не продаётся за Stars", show_alert=True)
            return
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=it["name"],
                description=it.get("desc", ""),
                payload=f"shop_stars_{idx}",
                currency="XTR",
                prices=[LabeledPrice(label=it["name"], amount=stars)],
            )
        except Exception as e:
            print(f"Ошибка инвойса: {e}")
        return

    if data.startswith("shop_buy_tokens_"):
        try:
            idx = int(data.replace("shop_buy_tokens_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        items = get_shop_items()
        if idx < 0 or idx >= len(items):
            await call.answer("❌ Товар не найден", show_alert=True)
            return
        it = items[idx]
        price = it.get("tokens", 0)
        if price <= 0:
            await call.answer("❌ Товар не продаётся за токены", show_alert=True)
            return
        balance = get_balance(user_id)
        if balance < price and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно! Нужно {price:,} 💎".replace(',', ' '), show_alert=True)
            return
        set_balance(user_id, -price)
        # Выдача в инвентарь
        reward_text = grant_shop_item(user_id, it)
        nb = get_balance(user_id)
        await call.answer("✅ Куплено!", show_alert=True)
        try:
            await call.message.edit_text(
                f"✅ <b>КУПЛЕНО!</b>\n\n"
                f"🎁 {reward_text}\n\n"
                f"💎 Баланс: <b>{nb:,}</b>\n\n"
                f"📦 Предмет в инвентаре!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                    [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop")]
                ])
            )
        except Exception:
            pass
        return

    # ═══════════════ КЕЙСЫ ═══════════════
    if data.startswith("case_buy_"):
        parts = data.split("_")
        case_id = parts[2]
        try:
            stars = int(parts[3])
        except Exception:
            await call.answer("❌ Ошибка кейса", show_alert=True)
            return
        case = get_case_by_id(case_id)
        if not case or case["stars"] != stars:
            await call.answer("❌ Кейс изменился. Открой /cases заново.", show_alert=True)
            return
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"Кейс «{case['name']}»",
                description=case.get("desc", "Кейс с наградами"),
                payload=f"case_{case_id}",
                currency="XTR",
                prices=[LabeledPrice(label=case["name"], amount=stars)],
            )
        except Exception as e:
            print(f"Ошибка инвойса кейса: {e}")
        return

    # ═══════════════ ИНВЕНТАРЬ ═══════════════
    if data == "menu_inventory":
        try:
            await call.message.edit_text(
                inventory_text(user_id),
                parse_mode="HTML",
                reply_markup=inventory_main_kb()
            )
        except Exception:
            pass
        await call.answer()
        return

    if data == "inv_titles":
        await call.message.edit_text(
            inventory_text(user_id, "title"),
            parse_mode="HTML",
            reply_markup=inventory_list_kb(user_id, "title")
        )
        await call.answer()
        return

    if data == "inv_boosts":
        await call.message.edit_text(
            inventory_text(user_id, "boost"),
            parse_mode="HTML",
            reply_markup=inventory_list_kb(user_id, "boost")
        )
        await call.answer()
        return

    if data == "inv_vip":
        await call.message.edit_text(
            inventory_text(user_id, "vip"),
            parse_mode="HTML",
            reply_markup=inventory_list_kb(user_id, "vip")
        )
        await call.answer()
        return

    if data == "inv_cases":
        await call.message.edit_text(
            inventory_text(user_id, "case"),
            parse_mode="HTML",
            reply_markup=inventory_list_kb(user_id, "case")
        )
        await call.answer()
        return

    if data == "inv_all":
        await call.message.edit_text(
            inventory_text(user_id),
            parse_mode="HTML",
            reply_markup=inventory_list_kb(user_id)
        )
        await call.answer()
        return

    if data.startswith("inv_view_"):
        inv_id = data.replace("inv_view_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌ Предмет не найден", show_alert=True)
            return
        t = item.get("type")
        if t == "boost":
            title = f"⚡ Буст ×{item['mult']} / {item['minutes']}м"
        elif t == "title":
            title = f"🏷️ {item['title']}"
        elif t == "vip":
            title = f"👑 VIP {item['vip_level']}"
        elif t == "case":
            title = f"🎰 Кейс {item.get('case_id', '')}"
        else:
            title = "❓ Предмет"
        await call.message.edit_text(
            f"📦 <b>{title}</b>\n\n"
            f"👇 Что делаем?",
            parse_mode="HTML",
            reply_markup=inventory_item_kb(inv_id)
        )
        await call.answer()
        return

    if data.startswith("inv_use_"):
        inv_id = data.replace("inv_use_", "")
        ok, msg = use_inventory_item(user_id, inv_id)
        if ok:
            await call.answer("✅ Активировано!", show_alert=True)
            try:
                await call.message.edit_text(
                    f"✅ <b>АКТИВИРОВАНО!</b>\n\n{msg}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                        [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
                    ])
                )
            except Exception:
                pass
        else:
            await call.answer(msg, show_alert=True)
        return

    if data.startswith("inv_sell_"):
        inv_id = data.replace("inv_sell_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌ Не найдено", show_alert=True)
            return
        # Открываем диалог ввода цены
        edit_shop_state[user_id] = {"mode": "sell_price", "inv_id": inv_id}
        await call.message.edit_text(
            f"💰 <b>ВЫСТАВИТЬ НА РЫНОК</b>\n\n"
            f"📦 Предмет: <b>{item.get('type')}</b>\n\n"
            f"Введи цену в токенах 💎\n"
            f"<i>(минимум 10 000, максимум 9 000 000 000)</i>\n\n"
            f"❌ Отмена: /inventory",
            parse_mode="HTML"
        )
        await call.answer()
        return

    # ═══════════════ РЫНОК ═══════════════
    if data == "menu_market":
        await call.message.edit_text(market_text(), parse_mode="HTML", reply_markup=market_main_kb())
        await call.answer()
        return

    if data == "market_browse":
        lots = get_market_lots()
        if not lots:
            await call.message.edit_text(
                "🏪 <b>РЫНОК</b>\n\n😢 Пока пусто...\n\nБудь первым, кто выставит!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💰 Продать", callback_data="market_sell")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")]
                ])
            )
            await call.answer()
            return
        await call.message.edit_text(
            f"🏪 <b>РЫНОК — КУПИТЬ</b>\n\nАктивных лотов: <b>{len(lots)}</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=market_lots_kb(lots, page=0)
        )
        await call.answer()
        return

    if data.startswith("market_page_"):
        try:
            page = int(data.replace("market_page_", ""))
        except Exception:
            page = 0
        lots = get_market_lots()
        await call.message.edit_text(
            f"🏪 <b>РЫНОК — КУПИТЬ</b>\n\nАктивных лотов: <b>{len(lots)}</b>\n\n👇 Выбери:",
            parse_mode="HTML",
            reply_markup=market_lots_kb(lots, page=page)
        )
        await call.answer()
        return

    if data.startswith("market_buy_"):
        try:
            idx = int(data.replace("market_buy_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        ok, msg = buy_market_lot(user_id, idx)
        if ok:
            await call.answer("✅ Куплено!", show_alert=True)
            try:
                await call.message.edit_text(
                    f"✅ <b>ПОКУПКА УСПЕШНА</b>\n\n{msg}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                        [InlineKeyboardButton(text="🏪 Рынок", callback_data="menu_market")]
                    ])
                )
            except Exception:
                pass
        else:
            await call.answer(msg, show_alert=True)
        return

    if data == "market_sell":
        inv = get_inventory(user_id)
        if not inv:
            await call.answer("🎒 У тебя пусто!", show_alert=True)
            return
        await call.message.edit_text(
            f"💰 <b>ВЫСТАВИТЬ НА РЫНОК</b>\n\nВыбери предмет:",
            parse_mode="HTML",
            reply_markup=market_sell_kb(user_id)
        )
        await call.answer()
        return

    if data.startswith("market_sellitem_"):
        inv_id = data.replace("market_sellitem_", "")
        item = find_inventory_item(user_id, inv_id)
        if not item:
            await call.answer("❌ Не найдено", show_alert=True)
            return
        edit_shop_state[user_id] = {"mode": "sell_price", "inv_id": inv_id}
        await call.message.edit_text(
            f"💰 <b>ЦЕНА ЛОТА</b>\n\n"
            f"📦 Предмет: <b>{item.get('type')}</b>\n\n"
            f"Введи цену в токенах 💎\n"
            f"<i>(от 10 000)</i>\n\n"
            f"❌ Отмена: /market",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data == "market_mylots":
        lots = get_market_lots()
        my_lots = [l for l in lots if l["seller_id"] == user_id]
        if not my_lots:
            await call.answer("📦 У тебя нет лотов", show_alert=True)
            return
        txt = "📦 <b>МОИ ЛОТЫ</b>\n\n"
        rows = []
        for i, lot in enumerate(my_lots):
            price = f"{lot['price']:,} 💎".replace(',', ' ')
            txt += f"• {lot.get('type', '?')} — {price}\n"
            rows.append([InlineKeyboardButton(
                text=f"❌ Снять лот {i+1}",
                callback_data=f"market_remove_{lot['id']}"
            )])
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_market")])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await call.answer()
        return

    if data.startswith("market_remove_"):
        lot_id = data.replace("market_remove_", "")
        lots = get_market_lots()
        removed = None
        new_lots = []
        for l in lots:
            if l["id"] == lot_id and l["seller_id"] == user_id:
                removed = l
            else:
                new_lots.append(l)
        if removed:
            save_market_lots(new_lots)
            # Возврат предмета
            item = dict(removed["payload"])
            item["type"] = removed["type"]
            add_to_inventory(user_id, item)
            await call.answer("✅ Лот снят, предмет возвращён", show_alert=True)
        else:
            await call.answer("❌ Не найден", show_alert=True)
        return

    if data == "market_noop":
        await call.answer()
        return

    # ═══════════════ РЕФКА ═══════════════
    if data == "menu_ref":
        try:
            me = await bot.get_me()
            bot_username = me.username
        except Exception:
            bot_username = "gold1_casino_bot"
        count, earnings = get_ref_stats(user_id)
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        txt = (
            f"🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
            f"👤 <b>{username}</b>\n\n"
            f"👥 Приглашено: <b>{count}</b>\n"
            f"💰 Заработано: <b>{earnings:,}</b> 💎\n\n"
            f"🎁 За каждого друга: <b>+5 000</b> 💎 тебе и ему\n"
            f"📈 +5% с его выигрышей (3 уровня)\n\n"
            f"🔗 Твоя ссылка:\n<code>{link}</code>"
        ).replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=ref_kb())
        await call.answer()
        return

    if data == "ref_list":
        refs = get_referrals(user_id)
        if not refs:
            await call.answer("👥 Пока никого", show_alert=True)
            return
        txt = f"👥 <b>МОИ РЕФЕРАЛЫ ({len(refs)})</b>\n\n"
        for i, (uid, uname) in enumerate(refs[:30], 1):
            txt += f"{i}. <b>{uname}</b>\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=ref_kb())
        await call.answer()
        return

    if data == "ref_top":
        rows = get_ref_top(10)
        if not rows:
            await call.answer("🏆 Пока пусто", show_alert=True)
            return
        txt = "🏆 <b>ТОП РЕФЕРЕРОВ</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, cnt, earn) in enumerate(rows):
            m = medals[i] if i < 3 else f"{i+1}."
            txt += f"{m} <b>{uname}</b> — {cnt} 👥 | {earn:,} 💎\n".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=ref_kb())
        await call.answer()
        return

    # ═══════════════ РЕДАКТОРЫ (магазин/кейсы) ═══════════════
    if data == "editshop_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        edit_shop_state.pop(user_id, None)
        try:
            await call.message.edit_text(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        except Exception:
            await call.message.answer(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        await call.answer()
        return

    if data.startswith("editshop_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editshop_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        await call.message.edit_text(editshop_item_text(idx), parse_mode="HTML", reply_markup=editshop_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editshop_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editshop_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        prompts = {
            "name": "🏷 Введи новое название:",
            "desc": "📝 Введи новое описание:",
            "stars": "⭐ Введи новую цену в Stars (или 0 чтобы убрать):",
            "tokens": "💎 Введи новую цену в токенах (или 0 чтобы убрать):",
            "mult": "⚡ Введи множитель (для буста):",
            "minutes": "⏱ Введи минуты (для буста):",
            "title": "🏷 Введи название титула:",
            "vip_level": "👑 Введи VIP уровень (0-4):",
        }
        edit_shop_state[user_id] = {"mode": "edit_shop", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n"
            f"❌ Отмена: /editshop",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data.startswith("editshop_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editshop_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editshop_delok_{idx}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editshop_item_{idx}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ ТОВАР?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editshop_delok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editshop_delok_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        items = get_shop_items()
        if 0 <= idx < len(items):
            items.pop(idx)
            save_shop_items(items)
        await call.message.edit_text(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        await call.answer("✅ Удалено")
        return

    if data == "editshop_add":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Буст", callback_data="editshop_newtype_boost"),
             InlineKeyboardButton(text="🏷️ Титул", callback_data="editshop_newtype_title")],
            [InlineKeyboardButton(text="👑 VIP", callback_data="editshop_newtype_vip"),
             InlineKeyboardButton(text="🔙 Назад", callback_data="editshop_start")]
        ])
        await call.message.edit_text(
            "➕ <b>НОВЫЙ ТОВАР</b>\n\n👇 Выбери тип:",
            parse_mode="HTML",
            reply_markup=kb
        )
        await call.answer()
        return

    if data.startswith("editshop_newtype_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        new_type = data.replace("editshop_newtype_", "")
        edit_shop_state[user_id] = {"mode": "new_shop", "type": new_type, "step": "name", "data": {"type": new_type}}
        await call.message.edit_text(
            f"➕ <b>НОВЫЙ ТОВАР ({new_type})</b>\n\n🏷 Введи название:\n\n❌ Отмена: /editshop",
            parse_mode="HTML"
        )
        await call.answer()
        return

    # ═══════════════ РЕДАКТОР КЕЙСОВ ═══════════════
    if data == "editcases_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        edit_case_state.pop(user_id, None)
        try:
            await call.message.edit_text(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        except Exception:
            await call.message.answer(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        await call.answer()
        return

    if data.startswith("editcases_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editcases_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        await call.message.edit_text(editcases_item_text(idx), parse_mode="HTML", reply_markup=editcases_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editcases_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        prompts = {
            "name": "🏷 Введи название кейса:",
            "desc": "📝 Введи описание:",
            "stars": "⭐ Введи цену в Stars:",
        }
        edit_case_state[user_id] = {"mode": "editcase", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /editcases",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data.startswith("editcases_rewards_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editcases_rewards_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        await call.message.edit_text(editcases_item_text(idx), parse_mode="HTML", reply_markup=editcases_rewards_kb(idx))
        await call.answer()
        return

    if data.startswith("editcases_reward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_reward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        await call.message.edit_text(
            editcases_reward_edit_text(ci, ri),
            parse_mode="HTML",
            reply_markup=editcases_reward_kb(ci, ri)
        )
        await call.answer()
        return

    if data.startswith("editcases_editreward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_editreward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        await call.message.edit_text(
            editcases_reward_edit_text(ci, ri),
            parse_mode="HTML",
            reply_markup=editcases_reward_edit_kb(ci, ri)
        )
        await call.answer()
        return

    if data.startswith("editcases_rf_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_rf_", "").split("_")
        try:
            ci, ri, field = int(parts[0]), int(parts[1]), parts[2]
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        prompts = {
            "mult": "⚡ Множитель:",
            "minutes": "⏱ Минуты:",
            "chance": "🎲 Шанс % (0-100):",
            "title": "🏷 Титул:",
        }
        edit_case_state[user_id] = {"mode": "editreward", "ci": ci, "ri": ri, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ</b>\n\n{prompts.get(field, 'Значение:')}\n\n❌ Отмена: /editcases",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data.startswith("editcases_delreward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_delreward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editcases_delrewardok_{ci}_{ri}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editcases_reward_{ci}_{ri}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ ПРИЗ?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editcases_delrewardok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        parts = data.replace("editcases_delrewardok_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        cases = get_cases()
        if 0 <= ci < len(cases):
            rewards = cases[ci]["rewards"]
            if 0 <= ri < len(rewards):
                rewards.pop(ri)
                save_cases(cases)
        await call.message.edit_text(editcases_item_text(ci), parse_mode="HTML", reply_markup=editcases_rewards_kb(ci))
        await call.answer("✅")
        return

    if data.startswith("editcases_addreward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            ci = int(data.replace("editcases_addreward_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Буст", callback_data=f"editcases_newboost_{ci}"),
             InlineKeyboardButton(text="🏷 Титул", callback_data=f"editcases_newtitle_{ci}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"editcases_rewards_{ci}")]
        ])
        await call.message.edit_text("➕ <b>НОВЫЙ ПРИЗ</b>\n\n👇 Тип:", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editcases_newboost_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            ci = int(data.replace("editcases_newboost_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        edit_case_state[user_id] = {"mode": "newboost", "ci": ci, "step": "mult"}
        await call.message.edit_text("➕ <b>НОВЫЙ БУСТ</b>\n\n⚡ Множитель:", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editcases_newtitle_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            ci = int(data.replace("editcases_newtitle_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        edit_case_state[user_id] = {"mode": "newtitle", "ci": ci, "step": "title"}
        await call.message.edit_text("➕ <b>НОВЫЙ ТИТУЛ</b>\n\n🏷 Название:", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editcases_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editcases_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editcases_delok_{idx}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editcases_item_{idx}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ КЕЙС?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editcases_delok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True)
            return
        try:
            idx = int(data.replace("editcases_delok_", ""))
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        cases = get_cases()
        if 0 <= idx < len(cases):
            cases.pop(idx)
            save_cases(cases)
        await call.message.edit_text(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        await call.answer("✅")
        return

    # ═══════════════ АДМИН-ПАНЕЛЬ ═══════════════
    if data.startswith("admin_"):
        if user_id != ADMIN_ID:
            await call.answer("❌ Только для админа", show_alert=True)
            return

        if data == "admin_back":
            balance = get_balance(user_id)
            bank = get_bank(user_id)
            txt = (
                f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
                f"👤 <b>{username}</b>\n"
                f"💎 Баланс: <b>{balance:,}</b>\n"
                f"🏦 Банк: <b>{bank:,}</b>\n\n"
                f"📋 <b>Выбери раздел:</b>"
            ).replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
            await call.answer()
            return

        if data == "admin_cat_players":
            txt = "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\nРабота с профилями, банами, VIP.\n\n👇 Выбери действие:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_players_kb())
            await call.answer()
            return

        if data == "admin_cat_games":
            txt = "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\nВключай/выключай кнопками:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_games_kb())
            await call.answer()
            return

        if data == "admin_cat_content":
            txt = "🛒 <b>УПРАВЛЕНИЕ КОНТЕНТОМ</b>\n\nМагазин, кейсы:\n\n👇 Выбери:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_content_kb())
            await call.answer()
            return

        if data == "admin_cat_economy":
            txt = "💰 <b>ЭКОНОМИКА</b>\n\nБонусы, джекпот, розыгрыши:\n\n👇 Выбери:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_economy_kb())
            await call.answer()
            return

        if data == "admin_cat_comm":
            txt = "📢 <b>СВЯЗЬ</b>\n\nРассылки, статистика:\n\n👇 Выбери:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_comm_kb())
            await call.answer()
            return

        if data == "admin_cat_monitor":
            txt = "📊 <b>МОНИТОРИНГ</b>\n\nАктивность, выигрыши, логи:\n\n👇 Выбери:"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_monitor_kb())
            await call.answer()
            return

        # Игры: переключение ВКЛ/ВЫКЛ
        if data.startswith("admin_toggle_"):
            game = data.replace("admin_toggle_", "")
            if game not in GAME_NAMES:
                await call.answer("❌", show_alert=True)
                return
            if game in disabled_games:
                disabled_games.discard(game)
                save_disabled_games()
                await call.answer(f"✅ {GAME_NAMES[game]} включена")
            else:
                disabled_games.add(game)
                save_disabled_games()
                await call.answer(f"❌ {GAME_NAMES[game]} выключена")
            await call.message.edit_text(
                "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\nВключай/выключай кнопками:",
                parse_mode="HTML",
                reply_markup=admin_games_kb()
            )
            return

        # Активные — показать сразу
        if data == "admin_active_show":
            users = get_recent_users(minutes=5, limit=20)
            if not users:
                txt = "📊 За последние 5 минут никто не играл"
            else:
                txt = "📊 <b>Активные за 5 минут</b>\n\n"
                for i, (uid, uname, bal) in enumerate(users, 1):
                    txt += f"{i}. <b>{uname}</b> — 💎 {bal:,}\n".replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_all_players":
            conn = get_conn()
            c = conn.cursor()
            c.execute("""
                SELECT user_id, username, balance, banned
                FROM users
                ORDER BY balance DESC
                LIMIT 30
            """)
            rows = c.fetchall()
            c.execute("SELECT COUNT(*) FROM users")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
            banned = c.fetchone()[0]
            c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
            total_balance = c.fetchone()[0]
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM game_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
            active_24h = c.fetchone()[0]
            c.close()
            release_conn(conn)

            medals = ["🥇", "🥈", "🥉"]
            txt = f"👥 <b>ВСЕ ИГРОКИ</b>\n━━━━━━━━━━━━━━━━━━\n\n"

            for i, row in enumerate(rows):
                uid, uname, bal, is_banned = row
                medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
                ban_icon = " 🚫" if is_banned else ""
                uname = uname or f"user_{uid}"
                bal_str = f"{bal:,}".replace(',', ' ')
                txt += f"{medal} {uname} — <b>{bal_str}</b> 💎{ban_icon}\n"

            if total > 30:
                txt += f"\n<i>...и ещё {total - 30}</i>\n"

            txt += f"\n━━━━━━━━━━━━━━━━━━\n"
            txt += f"📊 Всего: <b>{total}</b>\n"
            txt += f"🟢 Активных за 24ч: <b>{active_24h}</b>\n"
            txt += f"🚫 Забанено: <b>{banned}</b>\n"
            txt += f"💎 Общий баланс: <b>{total_balance:,}</b>".replace(',', ' ')

            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        # Статистика — показать сразу
        if data == "admin_stats_show":
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
            total_balance = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM game_log")
            total_games = c.fetchone()[0]
            c.close()
            release_conn(conn)
            txt = (
                f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
                f"👥 Игроков: <b>{total_users}</b>\n"
                f"💎 Токенов: <b>{total_balance:,}</b>\n"
                f"🎮 Игр: <b>{total_games}</b>"
            ).replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        # Big Wins — сразу
        if data == "admin_bigwins_show":
            wins = get_big_wins(limit=10, min_win=100000)
            if not wins:
                txt = "📊 Крупных выигрышей нет"
            else:
                txt = "🏆 <b>BIG WINS</b>\n\n"
                for i, (uname, game, win, time) in enumerate(wins, 1):
                    txt += f"{i}. <b>{uname}</b> — {game} +{win:,} ({time})\n".replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        # Диалоги — вход в режим ожидания ввода
        if data == "admin_broadcast_start":
            admin_action_state[user_id] = {"mode": "broadcast"}
            await call.message.edit_text(
                "📢 <b>РАССЫЛКА</b>\n\nОтправь текст (можно с HTML):\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_ban_start":
            admin_action_state[user_id] = {"mode": "ban"}
            await call.message.edit_text(
                "🚫 <b>BAN / UNBAN</b>\n\nОтправь @username:\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_vip_start":
            admin_action_state[user_id] = {"mode": "vip"}
            await call.message.edit_text(
                "👑 <b>VIP</b>\n\nФормат: <code>@username уровень</code>\nПример: <code>@vasya 3</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_title_start":
            admin_action_state[user_id] = {"mode": "title"}
            await call.message.edit_text(
                "🏷 <b>ТИТУЛ</b>\n\nФормат: <code>@username Титул</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_bal_start":
            admin_action_state[user_id] = {"mode": "balance"}
            await call.message.edit_text(
                "💰 <b>БАЛАНС</b>\n\nФормат: <code>@username сумма</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_xp_start":
            admin_action_state[user_id] = {"mode": "xp"}
            await call.message.edit_text(
                "📊 <b>XP</b>\n\nФормат: <code>@username XP</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_reset_start":
            admin_action_state[user_id] = {"mode": "reset"}
            await call.message.edit_text(
                "🔄 <b>RESET</b>\n\nФормат: <code>@username</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_bonus_start":
            admin_action_state[user_id] = {"mode": "bonus"}
            await call.message.edit_text(
                "🎁 <b>БОНУС</b>\n\nФормат: <code>@username сумма</code> или <code>all сумма</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_logs_start":
            admin_action_state[user_id] = {"mode": "logs"}
            await call.message.edit_text(
                "📜 <b>ЛОГИ</b>\n\nФормат: <code>@username</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_giveaway_start":
            admin_action_state[user_id] = {"mode": "giveaway"}
            await call.message.edit_text(
                "🎁 <b>РОЗЫГРЫШ</b>\n\nФормат: <code>сумма время</code>\nПример: <code>10000 1h</code>\n\n❌ Отмена: /admin",
                parse_mode="HTML"
            )
            await call.answer()
            return

        if data == "admin_event":
            status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
            txt = f"🎰 <b>EVENT ×2</b>\n\nСтатус: <b>{status}</b>\n\n<code>/event double on/off</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        if data == "admin_maintenance":
            status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
            txt = f"🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nСтатус: <b>{status}</b>\n\n<code>/maintenance on/off</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return


        if data == "admin_pi_info":
            txt = "👤 <b>ПРОФИЛЬ ИГРОКА</b>\n\n<code>/stats @user</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        if data == "admin_all_cmds":
            txt = (
                "📋 <b>ВСЕ КОМАНДЫ</b>\n\n"
                "🎮 Игры: <code>/games on/off slots</code>\n"
                "🎁 Бонус: <code>/bonus @user 50000</code>\n"
                "💰 Баланс: <code>/setbal @user 1000</code>\n"
                "🚫 Ban: <code>/ban @user</code>\n"
                "👑 VIP: <code>/vip @user 3</code>\n"
                "🏷 Титул: <code>/title @user Легенда</code>\n"
                "🎁 Розыгрыш: <code>/giveaway 10000 1h</code>\n"
                "🛒 Магазин: <code>/editshop</code> или <code>/editboost</code>\n"
                "🎰 Кейсы: <code>/editcases</code>"
            )
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        await call.answer()
        return

    # ═══════════════ КВЕСТЫ ═══════════════
    if data.startswith("quest_claim_"):
        quest_key = data.replace("quest_claim_", "")
        reward = claim_quest(user_id, quest_key)
        if reward:
            new_balance = get_balance(user_id)
            await call.answer(f"✅ +{reward:,} 💎".replace(',', ' '), show_alert=True)
            try:
                await call.message.edit_text(
                    f"🎯 <b>КВЕСТ ВЫПОЛНЕН!</b>\n\n"
                    f"💰 Награда: <b>+{reward:,}</b>\n"
                    f"💎 Баланс: <b>{new_balance:,}</b>".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=quests_kb(user_id)
                )
            except Exception:
                pass
        else:
            await call.answer("❌ Уже получено", show_alert=True)
        return

    if data == "quest_noop":
        await call.answer()
        return

    # ═══════════════ МЕНЮ ═══════════════
    balance = get_balance(user_id)
    bank = get_bank(user_id)

    if data == "menu_main":
        xp = get_xp(user_id)
        vip = get_vip_info(xp)
        if is_unlimited(user_id):
            bal_line = "♾️ БЕЗЛИМИТ"
            total_line = "♾️"
        else:
            bal_line = f"<b>{balance:,}</b> 💎".replace(',', ' ')
            total_line = f"<b>{clamp(balance + bank):,}</b> 💎".replace(',', ' ')
        boost = get_active_boost(user_id)
        if boost:
            mins_left = int((boost[1] - datetime.now()).total_seconds() // 60)
            boost_line = f"⚡ ×{boost[0]} • {mins_left} мин"
        else:
            boost_line = "❌ нет"
        txt = (
            f"🎰 <b>ТОКЕНЫ-КАЗИНО</b>\n\n"
            f"👤 <b>{username}</b>\n"
            f"{vip['icon']} {vip['name']}\n\n"
            f"💎 Баланс: {bal_line}\n"
            f"🏦 Банк: <b>{bank:,}</b> 💎\n"
            f"📊 Всего: {total_line}\n\n"
            f"⚡ Буст: {boost_line}\n\n"
            f"👇 Выбирай:"
        ).replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_games":
        await call.message.edit_text("🎮 <b>ИГРЫ</b>\n\nВыбери игру:", parse_mode="HTML", reply_markup=games_kb())

    elif data == "menu_shop":
        await call.message.edit_text(shop_text(), parse_mode="HTML", reply_markup=shop_kb())

    elif data == "menu_cases":
        await call.message.edit_text(cases_text(), parse_mode="HTML", reply_markup=cases_kb())

    elif data == "menu_profile":
        await call.message.edit_text(profile_text(user_id, username), parse_mode="HTML", reply_markup=profile_kb())

    elif data == "menu_stats":
        await call.message.edit_text(stats_text(user_id, username), parse_mode="HTML", reply_markup=back_to_main_kb())

    elif data == "menu_history":
        await call.message.edit_text(history_text(user_id, username), parse_mode="HTML", reply_markup=history_kb())

    elif data.startswith("hist_"):
        game_map = {
            "hist_roulette": "рулетка", "hist_slots": "слоты",
            "hist_mines": "мины", "hist_bj": "блэкджек",
            "hist_coin": "монетка", "hist_duel": "дуэль",
            "hist_all": None,
        }
        game = game_map.get(data)
        await call.message.edit_text(history_text(user_id, username, game), parse_mode="HTML", reply_markup=history_kb())

    elif data == "menu_mytitles":
        titles = get_user_titles(user_id)
        if not titles:
            txt = "🏷️ <b>МОИ ТИТУЛЫ</b>\n\nПока пусто. Титулы выпадают из кейсов!"
        else:
            txt = "🏷️ <b>МОИ ТИТУЛЫ</b>\n\n"
            for i, t in enumerate(titles, 1):
                txt += f"{i}. {t}\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=mytitles_kb())

    elif data == "menu_quests":
        quests = get_user_quests(user_id)
        txt = "🎯 <b>КВЕСТЫ</b>\n\n"
        for q in quests:
            if q["claimed"]:
                txt += f"✔️ {q['name']}\n"
            elif q["completed"]:
                txt += f"✅ {q['name']} → Забрать!\n"
            else:
                txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))

    elif data == "menu_daily":
        can, left = get_daily_status(user_id)
        if can:
            claim_daily(user_id)
            nb = get_balance(user_id)
            await call.answer(f"🎁 +{DAILY_BONUS:,} 💎".replace(',', ' '), show_alert=True)
            try:
                await call.message.edit_text(
                    f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"
                    f"💰 Получено: <b>+{DAILY_BONUS:,}</b>\n"
                    f"💎 Баланс: <b>{nb:,}</b>\n\n"
                    f"⏳ Следующий через 24ч".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=group_kb()
                )
            except Exception:
                pass
        else:
            await call.answer(f"⏳ Через {fmt_time_left(left)}", show_alert=True)

    elif data == "menu_balance":
        if is_unlimited(user_id):
            await call.answer(f"♾️ БЕЗЛИМИТ\n🏦 {bank:,}".replace(',', ' '), show_alert=True)
        else:
            await call.answer(f"💎 {balance:,}\n🏦 {bank:,}".replace(',', ' '), show_alert=True)

    elif data == "menu_bank":
        await call.message.edit_text(bank_text(user_id, username), parse_mode="HTML", reply_markup=bank_kb())

    elif data == "bank_deposit":
        bank_input_state[user_id] = {"mode": "deposit"}
        await call.message.edit_text(
            f"🏦 <b>ПОЛОЖИТЬ В БАНК</b>\n\n💎 Баланс: <b>{balance:,}</b>\n\nВведи сумму:".replace(',', ' '),
            parse_mode="HTML", reply_markup=bank_cancel_kb()
        )

    elif data == "bank_withdraw":
        bank_input_state[user_id] = {"mode": "withdraw"}
        await call.message.edit_text(
            f"🏦 <b>СНЯТЬ ИЗ БАНКА</b>\n\n🏦 В банке: <b>{bank:,}</b>\n\nВведи сумму:".replace(',', ' '),
            parse_mode="HTML", reply_markup=bank_cancel_kb()
        )

    elif data == "menu_top":
        await call.message.edit_text(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())

    elif data.startswith("top_"):
        mode = data.replace("top_", "")
        await call.message.edit_text(top_text(mode), parse_mode="HTML", reply_markup=top_kb())

    elif data == "menu_log":
        chat_id = call.message.chat.id if call.message and call.message.chat else None
        rows = get_last_roulette_results(10, chat_id=chat_id)
        if not rows:
            txt = "📜 Пока пусто в этом чате..."
        else:
            txt = "📜 <b>Результаты</b>\n\n"
            for i, (detail,) in enumerate(rows, 1):
                p = detail.split()
                txt += f"{i}. {p[1] if len(p) > 1 else detail}\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    # ═══════════════ ИНФО ПО ИГРАМ ═══════════════
    elif data == "info_roulette":
        await call.message.edit_text("🎡 <b>РУЛЕТКА</b>\n\n<code>к 1000</code> — красное ×2\n<code>ч 1000</code> — чёрное ×2\n<code>з 1000</code> — зеро ×36\n\n<code>го</code> — запуск", parse_mode="HTML", reply_markup=back_to_games_kb())
    elif data == "info_slots":
        await call.message.edit_text("🎰 <b>СЛОТЫ</b>\n\n<code>спин 1000</code>\n\n🍒×10 | 🍋×15 | 🍊×20 | 🍇×25 | 💎×50 | 7️⃣×100", parse_mode="HTML", reply_markup=back_to_games_kb())
    elif data == "info_coin":
        await call.message.edit_text("🪙 <b>МОНЕТКА</b>\n\n<code>орёл 1000</code> / <code>решка 1000</code> — ×2", parse_mode="HTML", reply_markup=back_to_games_kb())
    elif data == "info_bj":
        await call.message.edit_text("🃏 <b>БЛЭКДЖЕК</b>\n\n<code>бж 1000</code>\n\n×2", parse_mode="HTML", reply_markup=back_to_games_kb())
    elif data == "info_mines":
        await call.message.edit_text("💣 <b>МИНЫ</b>\n\n<code>мины 1000</code>\n\n🟢 3 | 🟡 5 | 🔴 10", parse_mode="HTML", reply_markup=back_to_games_kb())
    elif data == "info_duel":
        await call.message.edit_text("⚔️ <b>ДУЭЛЬ</b>\n\n<code>дуэль 1000 @user</code>", parse_mode="HTML", reply_markup=back_to_games_kb())

    # ═══════════════ СТАВКИ И ИГРЫ (callbacks) ═══════════════
    elif data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        bet = balance if val == "max" else int(val)
        await call.message.edit_reply_markup(reply_markup=roulette_kb(bet))
        await call.answer(f"💎 {bet:,}".replace(',', ' '))

    elif data.startswith("mines_start_"):
        parts = data.split("_")
        level = parts[2]; bet = int(parts[3])
        if level not in MINES_LEVELS:
            await call.answer("❌", show_alert=True); return
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌ Ставка неверна", show_alert=True); return
        if balance < bet and not is_unlimited(user_id):
            await call.answer("❌ Недостаточно!", show_alert=True); return
        set_balance(user_id, -bet)
        positions = list(range(25))
        random.shuffle(positions)
        mines_positions = set(positions[:MINES_LEVELS[level]["mines"]])
        mines_games[user_id] = {
            "bet": bet, "level": level,
            "mines_positions": mines_positions,
            "opened": set(), "mult": 1.0,
        }
        add_xp(user_id, 2)
        update_quest(user_id, "bets_20")
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[level]['name']}</b>\n\n"
            f"💰 Ставка: <b>{bet:,}</b>\n"
            f"💎 Множитель: <b>×1.00</b>\n"
            f"🎁 Забрать: <b>{bet:,}</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[level]['mines']}</b>".replace(',', ' '),
            parse_mode="HTML", reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💣 Началось!")

    elif data.startswith("mines_open_"):
        if user_id not in mines_games:
            await call.answer("❌ Не найдена", show_alert=True); return
        game = mines_games[user_id]
        idx = int(data.replace("mines_open_", ""))
        if idx in game["opened"]:
            await call.answer("❌ Открыто", show_alert=True); return
        await call.message.edit_text("⏳ Открываем...", parse_mode="HTML")
        await asyncio.sleep(0.3)
        if idx in game["mines_positions"]:
            game["opened"].add(idx)
            await call.message.edit_text("💥 БУМ!", parse_mode="HTML")
            await asyncio.sleep(0.4)
            log_game(user_id, username, "мины", game["bet"], 0, f"{game['level']} бум")
            xp = get_xp(user_id)
            vip = get_vip_info(xp)
            cb = int(game["bet"] * vip["cashback"] / 100)
            if cb > 0 and not is_unlimited(user_id):
                set_balance(user_id, cb)
            await call.message.edit_text(
                f"💥 <b>БУМ! Мина!</b>\n\n😢 -<b>{game['bet']:,}</b>".replace(',', ' '),
                parse_mode="HTML", reply_markup=group_kb()
            )
            del mines_games[user_id]
            await call.answer(); return
        game["opened"].add(idx)
        game["mult"] = round(1 + len(game["opened"]) * MINES_LEVELS[game["level"]]["step"], 2)
        safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]
        if len(game["opened"]) == safe_total:
            wa = clamp(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
            set_balance(user_id, wa)
            log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} all")
            update_quest(user_id, "win_100k", wa)
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🏆 <b>ПОЛЕ ОЧИЩЕНО!</b>\n\n💰 <b>+{wa:,}</b>\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML", reply_markup=group_kb()
            )
            del mines_games[user_id]
            await call.answer("🎉"); return
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[game['level']]['name']}</b>\n\n"
            f"💰 Ставка: <b>{game['bet']:,}</b>\n"
            f"💎 Множитель: <b>×{game['mult']:.2f}</b>\n"
            f"🎁 Забрать: <b>{int(game['bet']*game['mult']):,}</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[game['level']]['mines']}</b>".replace(',', ' '),
            parse_mode="HTML", reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💎")

    elif data == "mines_cashout":
        if user_id not in mines_games:
            await call.answer("❌", show_alert=True); return
        game = mines_games[user_id]
        if not game["opened"]:
            await call.answer("❌ Открой 1 клетку", show_alert=True); return
        wa = clamp(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, wa)
        nb = get_balance(user_id)
        log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} x{game['mult']}")
        update_quest(user_id, "win_100k", wa)
        await call.message.edit_text(
            f"💰 <b>ЗАБРАЛ!</b>\n\n🎁 +<b>{wa:,}</b>\n💎 {nb:,}".replace(',', ' '),
            parse_mode="HTML", reply_markup=group_kb()
        )
        del mines_games[user_id]
        await call.answer("💰")

    elif data == "mines_cancel":
        if user_id in mines_games:
            game = mines_games[user_id]
            if not game["opened"]:
                set_balance(user_id, game["bet"])
                del mines_games[user_id]
                await call.message.edit_text("❌ Отменено", parse_mode="HTML", reply_markup=group_kb())
                await call.answer("Возвращено"); return
        await call.answer("❌")

    elif data == "mines_noop":
        await call.answer()

    elif data.startswith("bet_"):
        parts = data.split("_")
        bet_type = parts[1]; bet = int(parts[2])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌", show_alert=True); return
        if balance < bet and not is_unlimited(user_id):
            await call.answer("❌ Недостаточно!", show_alert=True); return
        set_balance(user_id, -bet)
        # Анимация рулетки
        for i, frame in enumerate(ANIM_ROULETTE):
            try:
                await call.message.edit_text(f"🎡 <b>РУЛЕТКА</b>\n\n🎲 Крутится...\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(ANIM_ROULETTE_DELAYS[i] if i < len(ANIM_ROULETTE_DELAYS) else 0.3)
        result = random.randint(0, 36)
        color = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        win = False; mult = 0
        if bet_type == "red" and result in RED_NUMBERS:
            win = True; mult = MULT_COLOR
        elif bet_type == "black" and result in BLACK_NUMBERS:
            win = True; mult = MULT_COLOR
        elif bet_type == "green" and result == 0:
            win = True; mult = MULT_ZERO
        add_xp(user_id, 1)
        update_quest(user_id, "roulette_10")
        if win:
            wa = clamp(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            update_quest(user_id, "win_100k", wa)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n🎉 <b>ПОБЕДА!</b>\n💰 +{wa:,}\n💎 {nb:,}".replace(',', ' ')
        else:
            nb = get_balance(user_id)
            xp = get_xp(user_id); vip = get_vip_info(xp)
            cb = int(bet * vip["cashback"] / 100)
            if cb > 0 and not is_unlimited(user_id):
                nb = set_balance(user_id, cb)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n😢 -{bet:,}\n💰 Кешбэк: +{cb:,}\n💎 {nb:,}".replace(',', ' ')
        log_game(user_id, username, "рулетка", bet, wa if win else 0, f"{result} {color}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ ×2", callback_data=f"bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)

    elif data.startswith("group_bet_"):
        parts = data.split("_")
        bet_type = parts[2]; bet = int(parts[3])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌", show_alert=True); return
        if balance < bet and not is_unlimited(user_id):
            await call.answer("❌ Недостаточно!", show_alert=True); return
        set_balance(user_id, -bet)
        for i, frame in enumerate(ANIM_ROULETTE):
            try:
                await call.message.edit_text(f"🎡 <b>РУЛЕТКА</b>\n\n🎲 Крутится...\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(ANIM_ROULETTE_DELAYS[i] if i < len(ANIM_ROULETTE_DELAYS) else 0.3)
        result = random.randint(0, 36)
        color = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        win = False; mult = 0
        if bet_type == "red" and result in RED_NUMBERS:
            win = True; mult = MULT_COLOR
        elif bet_type == "black" and result in BLACK_NUMBERS:
            win = True; mult = MULT_COLOR
        elif bet_type == "green" and result == 0:
            win = True; mult = MULT_ZERO
        if win:
            wa = clamp(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n🎉 <b>ПОБЕДА!</b>\n💰 +{wa:,}\n💎 {nb:,}".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
        else:
            nb = get_balance(user_id)
            xp = get_xp(user_id); vip = get_vip_info(xp)
            cb = int(bet * vip["cashback"] / 100)
            if cb > 0 and not is_unlimited(user_id):
                nb = set_balance(user_id, cb)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n😢 -{bet:,}\n💰 Кешбэк: +{cb:,}\n💎 {nb:,}".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"group_bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ ×2", callback_data=f"group_bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)

    elif data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌", show_alert=True); return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'])}\n\n💥 ПЕРЕБОР!\n💸 -{game['bet']:,}\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML", reply_markup=group_kb()
            )
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score}")
            del bj_games[user_id]
        else:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'], hide_second=True)}\n\n🎯 Ещё?",
                parse_mode="HTML", reply_markup=bj_kb()
            )

    elif data == "bj_stand":
        if user_id not in bj_games:
            await call.answer("❌", show_alert=True); return
        game = bj_games[user_id]
        while hand_score(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        d_score = hand_score(game["dealer"])
        add_xp(user_id, 2)
        update_quest(user_id, "bj_5")
        update_quest(user_id, "bets_20")
        if d_score > 21 or p_score > d_score:
            wa = clamp(game["bet"] * 2 * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            res = f"🎉 <b>ПОБЕДА!</b>\n💰 +{wa - game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], wa, f"{p_score} vs {d_score}")
        elif p_score == d_score:
            set_balance(user_id, game["bet"])
            nb = get_balance(user_id)
            res = "🤝 <b>Ничья</b>"
            log_game(user_id, username, "блэкджек", game["bet"], game["bet"], f"{p_score}")
        else:
            nb = get_balance(user_id)
            res = f"😢 <b>Проигрыш</b>\n💸 -{game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} vs {d_score}")
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'])} = <b>{d_score}</b>\n\n{res}\n\n💎 {nb:,}".replace(',', ' '),
            parse_mode="HTML", reply_markup=group_kb()
        )
        del bj_games[user_id]

    await call.answer()


# ═══════════════ ФУНКЦИЯ ВЫДАЧИ ТОВАРА ИЗ МАГАЗИНА ═══════════════
def grant_shop_item(user_id, it):
    """Выдаёт предмет из магазина в инвентарь. Возвращает текст."""
    t = it.get("type", "boost")
    if t == "boost":
        add_to_inventory(user_id, {
            "type": "boost", "mult": int(it.get("mult", 2)),
            "minutes": int(it.get("minutes", 30))
        })
        return f"⚡ Буст ×{it.get('mult')} на {it.get('minutes')} мин"
    if t == "title":
        add_to_inventory(user_id, {"type": "title", "title": it.get("title", "🏷️ Титул")})
        return f"🏷️ Титул «{it.get('title')}»"
    if t == "vip":
        add_to_inventory(user_id, {"type": "vip", "vip_level": int(it.get("vip_level", 1))})
        return f"👑 VIP уровень {it.get('vip_level')}"
    return "🎁 Предмет"


# ═══════════════ РЕДАКТОР МАГАЗИНА: вспомогательные ═══════════════
def editshop_list_text():
    items = get_shop_items()
    if not items:
        return "🛒 <b>МАГАЗИН</b>\n\nПусто. Нажми ➕ ниже"
    txt = "🛒 <b>РЕДАКТОР МАГАЗИНА</b>\n\n"
    for i, it in enumerate(items, 1):
        prices = []
        if it.get("stars"): prices.append(f"{it['stars']}⭐")
        if it.get("tokens"): prices.append(f"{it['tokens']:,}💎".replace(',', ' '))
        price = " / ".join(prices) if prices else "—"
        txt += f"{i}. {it['name']} — {price}\n"
    return txt


def editshop_list_kb():
    items = get_shop_items()
    rows = []
    for i, it in enumerate(items):
        rows.append([InlineKeyboardButton(
            text=f"{i+1}. {it['name']}",
            callback_data=f"editshop_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="editshop_add")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editshop_item_text(idx):
    items = get_shop_items()
    if idx < 0 or idx >= len(items):
        return "❌ Товар не найден"
    it = items[idx]
    prices = []
    if it.get("stars"): prices.append(f"{it['stars']} ⭐")
    if it.get("tokens"): prices.append(f"{it['tokens']:,} 💎".replace(',', ' '))
    price = " / ".join(prices) if prices else "—"
    txt = (
        f"🛒 <b>{it['name']}</b>\n\n"
        f"📝 {it.get('desc', '—')}\n"
        f"🎯 Тип: <b>{it.get('type', '?')}</b>\n"
        f"💰 Цена: <b>{price}</b>\n"
    )
    if it.get("type") == "boost":
        txt += f"⚡ ×{it.get('mult')} на {it.get('minutes')}м\n"
    elif it.get("type") == "title":
        txt += f"🏷️ {it.get('title')}\n"
    elif it.get("type") == "vip":
        txt += f"👑 VIP {it.get('vip_level')}\n"
    txt += "\n👇 Что меняем?"
    return txt


def editshop_item_kb(idx):
    items = get_shop_items()
    if idx < 0 or idx >= len(items):
        return admin_back_kb()
    it = items[idx]
    rows = [
        [InlineKeyboardButton(text="🏷 Название", callback_data=f"editshop_field_{idx}_name"),
         InlineKeyboardButton(text="📝 Описание", callback_data=f"editshop_field_{idx}_desc")],
        [InlineKeyboardButton(text="⭐ Цена Stars", callback_data=f"editshop_field_{idx}_stars"),
         InlineKeyboardButton(text="💎 Цена токены", callback_data=f"editshop_field_{idx}_tokens")],
    ]
    if it.get("type") == "boost":
        rows.append([InlineKeyboardButton(text="⚡ Множитель", callback_data=f"editshop_field_{idx}_mult"),
                     InlineKeyboardButton(text="⏱ Минуты", callback_data=f"editshop_field_{idx}_minutes")])
    elif it.get("type") == "title":
        rows.append([InlineKeyboardButton(text="🏷 Титул", callback_data=f"editshop_field_{idx}_title")])
    elif it.get("type") == "vip":
        rows.append([InlineKeyboardButton(text="👑 VIP уровень", callback_data=f"editshop_field_{idx}_vip_level")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editshop_del_{idx}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="editshop_start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ РЕДАКТОР КЕЙСОВ: вспомогательные ═══════════════
def editcases_list_text():
    cases = get_cases()
    if not cases:
        return "🎰 <b>КЕЙСОВ НЕТ</b>"
    txt = "🎰 <b>РЕДАКТОР КЕЙСОВ</b>\n\n"
    for i, c in enumerate(cases, 1):
        txt += f"{i}. {c['name']} — {c['stars']}⭐ | 🎁 {len(c['rewards'])}\n"
    return txt


def editcases_list_kb():
    cases = get_cases()
    rows = []
    for i, c in enumerate(cases):
        rows.append([InlineKeyboardButton(
            text=f"{i+1}. {c['name']} ({c['stars']}⭐)",
            callback_data=f"editcases_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editcases_item_text(idx):
    cases = get_cases()
    if idx < 0 or idx >= len(cases):
        return "❌ Кейс не найден"
    c = cases[idx]
    txt = (
        f"🎰 <b>{c['name']}</b>\n\n"
        f"📝 {c.get('desc', '—')}\n"
        f"⭐ Цена: <b>{c['stars']}</b>\n\n"
        f"🎁 <b>Призы:</b>\n"
    )
    for i, r in enumerate(c["rewards"], 1):
        if r["type"] == "boost":
            txt += f"{i}. ⚡ ×{r['mult']} / {r['minutes']}м — {r['chance']}%\n"
        elif r["type"] == "title":
            txt += f"{i}. 🏷 {r['title']} — {r['chance']}%\n"
    return txt


def editcases_item_kb(idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Название", callback_data=f"editcases_field_{idx}_name"),
         InlineKeyboardButton(text="📝 Описание", callback_data=f"editcases_field_{idx}_desc")],
        [InlineKeyboardButton(text="⭐ Цена", callback_data=f"editcases_field_{idx}_stars")],
        [InlineKeyboardButton(text="🎁 Призы", callback_data=f"editcases_rewards_{idx}")],
        [InlineKeyboardButton(text="🗑 Удалить кейс", callback_data=f"editcases_del_{idx}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="editcases_start")]
    ])


def editcases_rewards_kb(ci):
    cases = get_cases()
    if ci < 0 or ci >= len(cases):
        return admin_back_kb()
    rows = []
    for i, r in enumerate(cases[ci]["rewards"]):
        if r["type"] == "boost":
            label = f"⚡ ×{r['mult']} / {r['minutes']}м / {r['chance']}%"
        else:
            label = f"🏷 {r['title']} / {r['chance']}%"
        rows.append([InlineKeyboardButton(
            text=f"{i+1}. {label}",
            callback_data=f"editcases_reward_{ci}_{i}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"editcases_addreward_{ci}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"editcases_item_{ci}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editcases_reward_kb(ci, ri):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"editcases_editreward_{ci}_{ri}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editcases_delreward_{ci}_{ri}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"editcases_rewards_{ci}")]
    ])


def editcases_reward_edit_kb(ci, ri):
    cases = get_cases()
    if ci < 0 or ci >= len(cases): return admin_back_kb()
    r = cases[ci]["rewards"][ri]
    rows = []
    if r["type"] == "boost":
        rows.append([InlineKeyboardButton(text="⚡ Множитель", callback_data=f"editcases_rf_{ci}_{ri}_mult"),
                     InlineKeyboardButton(text="⏱ Минуты", callback_data=f"editcases_rf_{ci}_{ri}_minutes")])
        rows.append([InlineKeyboardButton(text="🎲 Шанс", callback_data=f"editcases_rf_{ci}_{ri}_chance")])
    else:
        rows.append([InlineKeyboardButton(text="🏷 Титул", callback_data=f"editcases_rf_{ci}_{ri}_title")])
        rows.append([InlineKeyboardButton(text="🎲 Шанс", callback_data=f"editcases_rf_{ci}_{ri}_chance")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"editcases_reward_{ci}_{ri}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editcases_reward_edit_text(ci, ri):
    cases = get_cases()
    if ci < 0 or ci >= len(cases): return "❌"
    rewards = cases[ci]["rewards"]
    if ri < 0 or ri >= len(rewards): return "❌"
    r = rewards[ri]
    if r["type"] == "boost":
        return f"⚡ Буст ×{r['mult']} / {r['minutes']}м / {r['chance']}%"
    return f"🏷 {r['title']} / {r['chance']}%"
# ═══════════════ ДЖЕКПОТ (через БД — синхрон с Mini App) ═══════════════
def get_jackpot():
    """Читает джекпот из settings. Синхронизирован с Mini App."""
    cached = cache_get("jackpot", ttl=10)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'jackpot'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            val = int(row[0])
        except Exception:
            val = 10000
    else:
        val = 10000
        # Инициализация
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO settings (key, value) VALUES ('jackpot', '10000')
                     ON CONFLICT (key) DO NOTHING""")
        conn.commit()
        c.close()
        release_conn(conn)
    cache_set("jackpot", val, ttl=10)
    return val


def save_jackpot(amount):
    amount = clamp(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO settings (key, value) VALUES ('jackpot', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""",
              (str(amount), str(amount)))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("jackpot")


def add_to_jackpot(amount):
    """Добавляет сумму в джекпот (из комиссии рынка, ставок и т.д.)."""
    current = get_jackpot()
    new_val = clamp(current + amount)
    save_jackpot(new_val)
    return new_val


def reset_jackpot():
    save_jackpot(10000)
    return 10000


# ═══════════════ ТЕКСТОВЫЙ HANDLER (ГРУППА) ═══════════════
def parse_multi_bet(text):
    parts = text.split()
    if len(parts) < 2:
        return None, []
    try:
        bet = int(parts[0]) if parts[0].isdigit() else 0
    except ValueError:
        return None, []
    ranges = []
    for part in parts[1:]:
        try:
            if '-' in part:
                a, z = map(int, part.split('-'))
                ranges.append((a, z))
            else:
                ranges.append((int(part), int(part)))
        except ValueError:
            continue
    return bet, ranges


@dp.message(F.text, F.chat.type == 'private')
async def editor_text_handler(message: Message):
    """Перехват текста от админа в личке (редакторы + диалоги)."""
    user_id = message.from_user.id if message.from_user else None
    if user_id != ADMIN_ID:
        return

    # ═══════ ВВОД ЦЕНЫ ДЛЯ РЫНКА ═══════
    st = edit_shop_state.get(user_id)
    if st and st.get("mode") == "sell_price":
        inv_id = st["inv_id"]
        item = find_inventory_item(user_id, inv_id)
        if not item:
            edit_shop_state.pop(user_id, None)
            await message.answer("❌ Предмет не найден", parse_mode="HTML")
            return
        try:
            price = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Введи число:", parse_mode="HTML")
            return
        if price < 10000:
            await message.answer("❌ Минимум 10 000 💎", parse_mode="HTML")
            return
        if price > MAX_BALANCE:
            await message.answer(f"❌ Максимум {MAX_BALANCE:,}".replace(',', ' '), parse_mode="HTML")
            return
        # Снимаем предмет и создаём лот
        username = message.from_user.username or message.from_user.first_name
        remove_from_inventory(user_id, inv_id)
        add_market_lot(user_id, username, item, price)
        edit_shop_state.pop(user_id, None)
        await message.answer(
            f"✅ <b>ЛОТ ВЫСТАВЛЕН!</b>\n\n"
            f"💰 Цена: <b>{price:,}</b> 💎\n"
            f"🏪 Смотри на рынке: /market".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏪 Рынок", callback_data="menu_market")],
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")]
            ])
        )
        return

    # ═══════ РЕДАКТОР МАГАЗИНА: поля ═══════
    if st and st.get("mode") == "edit_shop":
        idx = st["idx"]; field = st["field"]
        items = get_shop_items()
        if idx < 0 or idx >= len(items):
            edit_shop_state.pop(user_id, None)
            await message.answer("❌ Товар не найден", parse_mode="HTML")
            return
        val = message.text.strip()

        if field == "name":
            items[idx]["name"] = val
        elif field == "desc":
            items[idx]["desc"] = val
        elif field in ("stars", "tokens"):
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML")
                return
            if num == 0:
                items[idx][field] = None
            elif num > 0:
                items[idx][field] = num
            else:
                await message.answer("❌ ≥ 0", parse_mode="HTML")
                return
        elif field in ("mult", "minutes", "vip_level"):
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML")
                return
            if num < 0:
                await message.answer("❌ ≥ 0", parse_mode="HTML")
                return
            items[idx][field] = num
        elif field == "title":
            items[idx]["title"] = val
        else:
            await message.answer("❌ Поле не найдено", parse_mode="HTML")
            return

        save_shop_items(items)
        edit_shop_state.pop(user_id, None)
        await message.answer(
            f"✅ <b>Обновлено!</b>\n\nОткрой /editshop заново.",
            parse_mode="HTML"
        )
        return

    # ═══════ НОВЫЙ ТОВАР (пошагово) ═══════
    if st and st.get("mode") == "new_shop":
        step = st["step"]
        data_dict = st["data"]
        val = message.text.strip()

        if step == "name":
            data_dict["name"] = val
            data_dict.setdefault("id", f"item_{int(time.time())}")
            st["step"] = "desc"
            edit_shop_state[user_id] = st
            await message.answer("📝 Теперь описание:", parse_mode="HTML")
            return
        if step == "desc":
            data_dict["desc"] = val
            st["step"] = "stars"
            edit_shop_state[user_id] = st
            await message.answer("⭐ Цена в Stars (0 = не продавать за Stars):", parse_mode="HTML")
            return
        if step == "stars":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            data_dict["stars"] = num if num > 0 else None
            st["step"] = "tokens"
            edit_shop_state[user_id] = st
            await message.answer("💎 Цена в токенах (0 = не продавать за токены):", parse_mode="HTML")
            return
        if step == "tokens":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            data_dict["tokens"] = num if num > 0 else None

            # Дальше зависит от типа
            t = data_dict.get("type")
            if t == "boost":
                st["step"] = "mult"
                edit_shop_state[user_id] = st
                await message.answer("⚡ Множитель (например 2):", parse_mode="HTML")
                return
            if t == "title":
                st["step"] = "title"
                edit_shop_state[user_id] = st
                await message.answer("🏷 Название титула:", parse_mode="HTML")
                return
            if t == "vip":
                st["step"] = "vip_level"
                edit_shop_state[user_id] = st
                await message.answer("👑 VIP уровень (0-4):", parse_mode="HTML")
                return
            return

        if step == "mult":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            data_dict["mult"] = num
            st["step"] = "minutes"
            edit_shop_state[user_id] = st
            await message.answer("⏱ Минуты:", parse_mode="HTML")
            return
        if step == "minutes":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число:", parse_mode="HTML")
                return
            data_dict["minutes"] = num
            # Готово!
            items = get_shop_items()
            items.append(data_dict)
            save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ <b>Товар добавлен!</b>\n\nОткрой /editshop.", parse_mode="HTML")
            return
        if step == "title":
            data_dict["title"] = val
            items = get_shop_items()
            items.append(data_dict)
            save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ <b>Товар добавлен!</b>", parse_mode="HTML")
            return
        if step == "vip_level":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число 0-4:", parse_mode="HTML")
                return
            if not 0 <= num <= 4:
                await message.answer("❌ 0-4", parse_mode="HTML")
                return
            data_dict["vip_level"] = num
            items = get_shop_items()
            items.append(data_dict)
            save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ <b>Товар добавлен!</b>", parse_mode="HTML")
            return
        return

    # ═══════ РЕДАКТОР КЕЙСОВ ═══════
    st = edit_case_state.get(user_id)
    if st:
        mode = st.get("mode")

        if mode == "editcase":
            cases = get_cases(); idx = st["idx"]; field = st["field"]
            if idx < 0 or idx >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML"); return
            val = message.text.strip()
            if field == "name":
                cases[idx]["name"] = val
            elif field == "desc":
                cases[idx]["desc"] = val
            elif field == "stars":
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML"); return
                if num < 1:
                    await message.answer("❌ ≥ 1", parse_mode="HTML"); return
                cases[idx]["stars"] = num
            save_cases(cases)
            edit_case_state.pop(user_id, None)
            await message.answer("✅ Открой /editcases заново.", parse_mode="HTML")
            return

        if mode == "editreward":
            cases = get_cases(); ci = st["ci"]; ri = st["ri"]; field = st["field"]
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML"); return
            rewards = cases[ci]["rewards"]
            if ri < 0 or ri >= len(rewards):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML"); return
            val = message.text.strip()
            if field == "title":
                rewards[ri]["title"] = val
            elif field in ("mult", "minutes", "chance"):
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML"); return
                if field == "chance" and not (0 <= num <= 100):
                    await message.answer("❌ 0-100", parse_mode="HTML"); return
                if field != "chance" and num < 1:
                    await message.answer("❌ ≥ 1", parse_mode="HTML"); return
                rewards[ri][field] = num
            save_cases(cases)
            edit_case_state.pop(user_id, None)
            await message.answer("✅", parse_mode="HTML")
            return

        if mode == "newboost":
            ci = st["ci"]; step = st["step"]
            cases = get_cases()
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML"); return
            val = message.text.strip()
            if step == "mult":
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                st["mult"] = num; st["step"] = "minutes"
                edit_case_state[user_id] = st
                await message.answer("⏱ Минуты:", parse_mode="HTML"); return
            if step == "minutes":
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                st["minutes"] = num; st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Шанс %:", parse_mode="HTML"); return
            if step == "chance":
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                cases[ci]["rewards"].append({
                    "type": "boost", "mult": st["mult"],
                    "minutes": st["minutes"], "chance": num
                })
                save_cases(cases)
                edit_case_state.pop(user_id, None)
                await message.answer("✅ Буст добавлен", parse_mode="HTML"); return
            return

        if mode == "newtitle":
            ci = st["ci"]; step = st["step"]
            cases = get_cases()
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None)
                await message.answer("❌", parse_mode="HTML"); return
            val = message.text.strip()
            if step == "title":
                st["title"] = val; st["step"] = "chance"
                edit_case_state[user_id] = st
                await message.answer("🎲 Шанс %:", parse_mode="HTML"); return
            if step == "chance":
                try:
                    num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                cases[ci]["rewards"].append({"type": "title", "title": st["title"], "chance": num})
                save_cases(cases)
                edit_case_state.pop(user_id, None)
                await message.answer("✅ Титул добавлен", parse_mode="HTML"); return
            return

    # ═══════ БАНК ═══════
    bst = bank_input_state.get(user_id)
    if bst:
        mode = bst.get("mode")
        try:
            amount = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Число:", parse_mode="HTML"); return
        if amount < 1:
            await message.answer("❌ Минимум 1", parse_mode="HTML"); return
        if mode == "deposit":
            bal = get_balance(user_id)
            if bal < amount and not is_unlimited(user_id):
                bank_input_state.pop(user_id, None)
                await message.answer(f"❌ Недостаточно! Баланс: {bal:,}".replace(',', ' '), parse_mode="HTML")
                return
            set_balance(user_id, -amount)
            new_bank = set_bank(user_id, amount)
            new_bal = get_balance(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>ПОЛОЖЕНО В БАНК</b>\n\n"
                f"💰 +<b>{amount:,}</b>\n"
                f"💎 Баланс: <b>{new_bal:,}</b>\n"
                f"🏦 В банке: <b>{new_bank:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=bank_kb()
            )
            return
        if mode == "withdraw":
            bank = get_bank(user_id)
            if bank < amount:
                bank_input_state.pop(user_id, None)
                await message.answer(f"❌ В банке только {bank:,}".replace(',', ' '), parse_mode="HTML")
                return
            set_bank(user_id, -amount)
            new_bal = set_balance(user_id, amount)
            new_bank = get_bank(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>СНЯТО ИЗ БАНКА</b>\n\n"
                f"💰 +<b>{amount:,}</b>\n"
                f"💎 Баланс: <b>{new_bal:,}</b>\n"
                f"🏦 В банке: <b>{new_bank:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=bank_kb()
            )
            return
        bank_input_state.pop(user_id, None)
        return

    # ═══════ АДМИН-ДИАЛОГИ ═══════
    ast = admin_action_state.get(user_id)
    if ast:
        mode = ast.get("mode")
        val = message.text.strip()

        if mode == "broadcast":
            admin_action_state.pop(user_id, None)
            uids = get_all_user_ids()
            sent, failed = 0, 0
            for uid in uids:
                try:
                    await bot.send_message(uid, f"📢 <b>РАССЫЛКА</b>\n\n{val}", parse_mode="HTML")
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
            await message.answer(f"📢 <b>Готово</b>\n✅ {sent} | ❌ {failed}", parse_mode="HTML")
            return

        if mode == "ban":
            admin_action_state.pop(user_id, None)
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_banned(uid, True)
            await message.answer(f"🚫 <b>@{uname} забанен!</b>", parse_mode="HTML")
            return

        if mode == "vip":
            admin_action_state.pop(user_id, None)
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user уровень", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try:
                level = int(parts[1])
            except ValueError:
                await message.answer("❌ Уровень число", parse_mode="HTML"); return
            if not 0 <= level <= 4:
                await message.answer("❌ 0-4", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_vip_level(uid, level)
            v = VIP_LEVELS[level]
            await message.answer(f"✅ <b>@{uname}</b> → {v['icon']} {v['name']}", parse_mode="HTML")
            return

        if mode == "title":
            admin_action_state.pop(user_id, None)
            parts = val.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("❌ @user Титул", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            title_text = parts[1]
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            add_title(uid, title_text, user_id)
            await message.answer(f"🏷️ <b>@{uname}</b> → <b>{title_text}</b>", parse_mode="HTML")
            return

        if mode == "balance":
            admin_action_state.pop(user_id, None)
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ Сумма число", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_balance_exact(uid, amount)
            await message.answer(f"✅ <b>@{uname}</b>: баланс = <b>{amount:,}</b>".replace(',', ' '), parse_mode="HTML")
            return

        if mode == "xp":
            admin_action_state.pop(user_id, None)
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user XP", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ XP число", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET xp = %s, vip_level = %s WHERE user_id = %s",
                      (amount, get_vip_level(amount), uid))
            conn.commit()
            c.close()
            release_conn(conn)
            cache_invalidate(f"xp_{uid}")
            await message.answer(f"✅ @{uname} XP = <b>{amount}</b>".replace(',', ' '), parse_mode="HTML")
            return

        if mode == "reset":
            admin_action_state.pop(user_id, None)
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            reset_user(uid)
            await message.answer(f"✅ <b>@{uname}</b> полностью сброшен", parse_mode="HTML")
            return

        if mode == "bonus":
            admin_action_state.pop(user_id, None)
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма или all сумма", parse_mode="HTML"); return
            target = parts[0]; 
            try:
                amount = int(parts[1])
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            if target.lower() == "all":
                uids = get_all_user_ids()
                count = 0
                for uid in uids:
                    try:
                        set_balance(uid, amount); count += 1
                    except Exception:
                        pass
                await message.answer(f"🎁 +{amount:,} всем! ({count})".replace(',', ' '), parse_mode="HTML")
                return
            uname = target.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            nb = set_balance(uid, amount)
            await message.answer(f"🎁 <b>+{amount:,}</b> → @{uname}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
            return

        if mode == "logs":
            admin_action_state.pop(user_id, None)
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            logs = get_user_logs(uid, 10)
            if not logs:
                await message.answer(f"📜 Пусто", parse_mode="HTML"); return
            txt = f"📜 <b>Последние 10 игр @{uname}</b>\n\n"
            for i, (game, bet, win, detail, time) in enumerate(logs, 1):
                profit = win - bet
                emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
                txt += f"{i}. {emoji} {game} | {bet:,} → {win:,} | {time}\n".replace(',', ' ')
            await message.answer(txt, parse_mode="HTML")
            return
            if mode == "jackpot_set":
             admin_action_state.pop(user_id, None)
            try:
                amount = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML")
                return
            if amount < 0:
                await message.answer("❌ ≥ 0", parse_mode="HTML")
                return
            save_jackpot(amount)
            await message.answer(f"✅ Джекпот = <b>{amount:,}</b> 💎".replace(',', ' '), parse_mode="HTML")
            return


        if mode == "giveaway":
            admin_action_state.pop(user_id, None)
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ сумма время", parse_mode="HTML"); return
            try:
                amount = int(parts[0])
            except ValueError:
                await message.answer("❌ Сумма", parse_mode="HTML"); return
            time_str = parts[1].lower()
            minutes = 0
            if time_str.endswith('h'):
                minutes = int(time_str[:-1]) * 60
            elif time_str.endswith('m'):
                minutes = int(time_str[:-1])
            if minutes == 0:
                await message.answer("❌ Формат: 30m / 1h", parse_mode="HTML"); return
            users = get_all_user_ids()
            gid, ends_at = create_giveaway(amount, minutes, user_id)
            await message.answer(
                f"🎁 <b>РОЗЫГРЫШ!</b>\n\n💰 {amount:,}\n⏱️ До {(ends_at + timedelta(hours=3)).strftime('%H:%M')}".replace(',', ' '),
                parse_mode="HTML"
            )
            for uid in users:
                try:
                    await bot.send_message(
                        uid,
                        f"🎁 <b>РОЗЫГРЫШ!</b>\n\n💰 {amount:,}\n⏱️ До {(ends_at + timedelta(hours=3)).strftime('%H:%M')}".replace(',', ' '),
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            return

        admin_action_state.pop(user_id, None)
        return

    return


@dp.message(F.text, F.chat.type != 'private')
async def text_handler(message: Message):
    if not message.text:
        return
    if not message.from_user or message.from_user.is_bot:
        return

    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    ensure_user(user_id, username)
    if chat_id < 0:
        track_group_member(chat_id, user_id, username)

    if is_banned(user_id):
        await message.reply("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return

    if maintenance_on and user_id != ADMIN_ID:
        await message.reply("🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nПопробуй позже!", parse_mode="HTML")
        return

    # ── БОНУС ──
    if text in ['бонус', 'bonus', 'ежедневка']:
        can, left = get_daily_status(user_id)
        if can:
            claim_daily(user_id)
            nb = get_balance(user_id)
            await message.reply(
                f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"
                f"💰 +<b>{DAILY_BONUS:,}</b>\n"
                f"💎 Баланс: <b>{nb:,}</b>\n\n"
                f"⏳ Следующий через 24ч".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            await message.reply(f"⏳ Через <b>{fmt_time_left(left)}</b>", parse_mode="HTML")
        return

    # ── ПРОФИЛЬ ──
    if text in ['профиль', 'я']:
        await message.reply(profile_text(user_id, username), parse_mode="HTML", reply_markup=profile_kb())
        return

    # ── КВЕСТЫ ──
    if text in ['квесты', 'quests']:
        quests = get_user_quests(user_id)
        txt = "🎯 <b>КВЕСТЫ</b>\n\n"
        for q in quests:
            if q["claimed"]:
                txt += f"✔️ {q['name']}\n"
            elif q["completed"]:
                txt += f"✅ {q['name']}\n"
            else:
                txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
        await message.reply(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))
        return

    # ── ДУЭЛЬ ──
    if len(parts) >= 3 and parts[0] == 'дуэль':
        try:
            bet = int(parts[1])
        except Exception:
            await message.reply("❌ Сумма"); return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна"); return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        target_username = parts[2][1:] if parts[2].startswith('@') else None
        if not target_username:
            await message.reply("❌ дуэль 1000 @user"); return
        opponent_id = get_user_id_by_username(target_username)
        if not opponent_id:
            await message.reply(f"❌ @{target_username} не найден"); return
        if opponent_id == user_id:
            await message.reply("❌ Себя нельзя"); return
        if chat_id in duel_games:
            await message.reply("❌ Уже есть дуэль"); return
        duel_games[chat_id] = {
            "challenger_id": user_id, "challenger_name": username, "challenger_bet": bet,
            "opponent_id": opponent_id, "opponent_name": target_username, "opponent_bet": bet,
            "active": False
        }
        await message.reply(
            f"⚔️ <b>ВЫЗОВ!</b>\n\n👤 {username} → @{target_username}\n💰 <b>{bet:,}</b>\n\n@{target_username}, напиши <code>принять</code>!".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    if text == 'принять':
        if chat_id not in duel_games or duel_games[chat_id].get("active"):
            return
        duel = duel_games[chat_id]
        if duel["opponent_id"] != user_id:
            return
        cb = get_balance(duel["challenger_id"])
        ob = get_balance(duel["opponent_id"])
        if cb < duel["challenger_bet"] and not is_unlimited(duel["challenger_id"]):
            await message.reply(f"❌ У {duel['challenger_name']} мало")
            del duel_games[chat_id]; return
        if ob < duel["opponent_bet"] and not is_unlimited(duel["opponent_id"]):
            await message.reply("❌ У тебя мало"); return
        set_balance(duel["challenger_id"], -duel["challenger_bet"])
        set_balance(duel["opponent_id"], -duel["opponent_bet"])
        duel["active"] = True
        total_bank = clamp(duel["challenger_bet"] + duel["opponent_bet"])
        msg = await message.reply(f"⚔️ <b>ДУЭЛЬ!</b>\n\n💰 <b>{total_bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        for i, frame in enumerate(ANIM_DUEL):
            await asyncio.sleep(ANIM_DUEL_DELAYS[i] if i < len(ANIM_DUEL_DELAYS) else 0.3)
            await msg.edit_text(f"⚔️ <b>ДУЭЛЬ</b>\n\n{frame}", parse_mode="HTML")
        winner_color = random.choice(['red', 'blue'])
        if winner_color == 'red':
            wid = duel["challenger_id"]; wn = duel["challenger_name"]; ln = duel["opponent_name"]; ce = "🔴"
        else:
            wid = duel["opponent_id"]; wn = duel["opponent_name"]; ln = duel["challenger_name"]; ce = "🔵"
        total_bank = clamp(int(total_bank * get_user_mult(wid)))
        nb = set_balance(wid, total_bank)
        add_xp(duel["challenger_id"], 3); add_xp(duel["opponent_id"], 3)
        log_game(wid, wn, "дуэль", total_bank // 2, total_bank, f"vs {ln}")
        await msg.edit_text(
            f"⚔️ <b>ДУЭЛЬ</b>\n\n{ce}\n\n🏆 <b>{wn}</b>\n💰 +{total_bank:,}\n💎 {nb:,}".replace(',', ' '),
            parse_mode="HTML"
        )
        del duel_games[chat_id]
        return

    if text == 'отмена' and chat_id in duel_games and not duel_games[chat_id].get("active"):
        duel = duel_games[chat_id]
        if user_id in [duel["challenger_id"], duel["opponent_id"]]:
            del duel_games[chat_id]
            await message.reply("❌ Дуэль отменена", parse_mode="HTML")
        return

    # ── БАНК ──
    if text == 'банк':
        await message.reply(bank_text(user_id, username), parse_mode="HTML", reply_markup=bank_kb())
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'положить':
        try:
            amount = int(parts[2])
        except Exception:
            await message.reply("❌ Сумма"); return
        if amount < 1:
            await message.reply("❌ Мин. 1"); return
        bal = get_balance(user_id)
        if bal < amount and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -amount)
        new_bank = set_bank(user_id, amount)
        new_bal = get_balance(user_id)
        await message.reply(f"🏦 В банк: -{amount:,}\n💎 {new_bal:,}\n🏦 {new_bank:,}".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'снять':
        try:
            amount = int(parts[2])
        except Exception:
            await message.reply("❌ Сумма"); return
        bank = get_bank(user_id)
        if bank < amount:
            await message.reply(f"❌ В банке {bank:,}".replace(',', ' ')); return
        set_bank(user_id, -amount)
        new_bal = set_balance(user_id, amount)
        new_bank = get_bank(user_id)
        await message.reply(f"🏦 Из банка: +{amount:,}\n💎 {new_bal:,}\n🏦 {new_bank:,}".replace(',', ' '), parse_mode="HTML")
        return

    # ── ПЕРЕВОД ──
    if parts[0] == 'п':
        if len(parts) < 2:
            await message.reply("💸 Ответь и напиши: п 1000"); return
        if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
            await message.reply("❌ Ответь на сообщение!"); return
        try:
            amount = int(parts[1])
        except Exception:
            await message.reply("❌ Сумма"); return
        if amount < 1:
            await message.reply("❌ Мин. 1"); return
        target = message.reply_to_message.from_user
        if target.id == user_id:
            await message.reply("❌ Себе нельзя"); return
        bal = get_balance(user_id)
        if bal < amount and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        ensure_user(target.id, target.username or target.first_name)
        set_balance(user_id, -amount)
        set_balance(target.id, amount)
        nb = get_balance(user_id); nt = get_balance(target.id)
        await message.reply(f"💸 Перевод: {amount:,}\n💎 {nb:,} | {nt:,}".replace(',', ' '), parse_mode="HTML")
        return

    # ── ОТМЕНА СТАВОК ──
    if text in ['отмена', 'отменить']:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            for b in active_bets[chat_id]["bets"]:
                set_balance(b["user_id"], b["bet_total"])
            del active_bets[chat_id]
            await message.reply(f"❌ Отменено ({count})", parse_mode="HTML")
        return

    # ── БАЛАНС ──
    if text in ['б', 'баланс']:
        bal = get_balance(user_id); bank = get_bank(user_id)
        xp = get_xp(user_id); vip = get_vip_info(xp)
        if is_unlimited(user_id):
            await message.reply(f"💰 {username}\n{vip['icon']} {vip['name']}\n♾️ БЕЗЛИМИТ\n🏦 {bank:,}".replace(',', ' '), parse_mode="HTML")
        else:
            await message.reply(f"💰 {username}\n{vip['icon']} {vip['name']}\n💎 <b>{bal:,}</b>\n🏦 {bank:,}".replace(',', ' '), parse_mode="HTML")
        return

    # ── ИГРЫ ──
    if text in ['игры', 'игра']:
        await message.reply("🎮 <b>ИГРЫ</b>", parse_mode="HTML", reply_markup=games_kb())
        return

    # ── ЛОГ ──
    if text in ['лог', 'log']:
        rows = get_last_roulette_results(10, chat_id=chat_id)
        if not rows:
            await message.reply("📜 Пусто", parse_mode="HTML"); return
        out = "📜 <b>Результаты:</b>\n\n"
        for i, (detail,) in enumerate(rows, 1):
            p = detail.split()
            out += f"{i}. {p[1] if len(p) > 1 else detail}\n"
        await message.reply(out, parse_mode="HTML")
        return

    # ── ТОП ──
    if text in ['топ', 'top']:
        await message.reply(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())
        return

    # ── МИНЫ ──
    if len(parts) == 2 and parts[0] in ['мины', 'мина', 'mines']:
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка"); return
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{bet:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=mines_level_kb(bet))
        return

    # ── ГО (рулетка запуск) ──
    if text == 'го':
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет ставок"); return
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        unlimited_in = any(is_unlimited(b["user_id"]) for b in bets)
        bank_line = "♾️" if unlimited_in else f"{total_bank:,}".replace(',', ' ')
        msg = await message.reply(f"🎡 <b>РУЛЕТКА!</b>\n💰 {bank_line}", parse_mode="HTML")
        for i, frame in enumerate(ANIM_ROULETTE):
            await asyncio.sleep(ANIM_ROULETTE_DELAYS[i] if i < len(ANIM_ROULETTE_DELAYS) else 0.3)
            try:
                await msg.edit_text(f"🎡 <b>РУЛЕТКА</b>\n💰 {bank_line}\n\n🎲 {frame}", parse_mode="HTML")
            except Exception:
                pass
        result = random.randint(0, 36)
        color = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        result_text = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n"
        winners = []
        user_last_bet = None
        for b in bets:
            win_amount = 0
            if b["type"] == "red" and result in RED_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR * get_event_mult() * get_user_mult(b["user_id"]))
            elif b["type"] == "black" and result in BLACK_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR * get_event_mult() * get_user_mult(b["user_id"]))
            elif b["type"] == "green" and result == 0:
                win_amount = int(b["bet_total"] * MULT_ZERO * get_event_mult() * get_user_mult(b["user_id"]))
            elif b["type"] == "ranges":
                win_mult = 0
                for (a, z) in b["ranges"]:
                    if a <= result <= z:
                        win_mult += MULT_RANGE
                if win_mult > 0:
                    win_amount = int(b["bet_total"] * win_mult * get_event_mult() * get_user_mult(b["user_id"]))
                user_last_bet = b
            if win_amount > 0:
                win_amount = clamp(win_amount)
                set_balance(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], win_amount, f"{result} {color}")
                if is_unlimited(b["user_id"]):
                    winners.append(f"🎉 {b['username']} — ♾️")
                else:
                    winners.append(f"🎉 {b['username']} — <b>+{win_amount:,}</b>".replace(',', ' '))
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], 0, f"{result} {color}")
        if winners:
            result_text += "\n".join(winners)
        else:
            result_text += "😢 Победителей нет"

        # ⚡ СРЫВ ДЖЕКПОТА при 🟢 Зеро
        if result == 0 and bets:
            jackpot = get_jackpot()
            if jackpot > 0:
                # Все, кто ставил на зеро, делят джекпот
                green_bettors = [b for b in bets if b["type"] == "green"]
                if green_bettors:
                    share = jackpot // len(green_bettors)
                    for b in green_bettors:
                        set_balance(b["user_id"], share)
                    result_text += f"\n\n💎 <b>ДЖЕКПОТ СОРВАН!</b>\n💰 {jackpot:,} 💎 разделены между {len(green_bettors)}".replace(',', ' ')
                    reset_jackpot()
                    add_xp(user_id, 50)

        # Комиссия 1% со ставок в джекпот
        commission = int(total_bank * 0.01)
        if commission > 0:
            add_to_jackpot(commission)

        del active_bets[chat_id]
        try:
            if user_last_bet:
                rkb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Ещё", callback_data=f"group_bet_{user_last_bet['type']}_{user_last_bet['bet']}")],
                    [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
                ])
                await msg.edit_text(result_text, parse_mode="HTML", reply_markup=rkb)
            else:
                await msg.edit_text(result_text, parse_mode="HTML")
        except Exception:
            await message.reply(result_text, parse_mode="HTML")
        return

    # ── СЛОТЫ (с остановкой барабанов по одному) ──
    if len(parts) == 2 and parts[0] in ['спин', 'spin']:
        if is_game_disabled('slots') and user_id != ADMIN_ID:
            await message.reply("❌ Слоты выключены"); return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка"); return
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -bet)

        symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
        r1 = random.choice(symbols); r2 = random.choice(symbols); r3 = random.choice(symbols)

        msg = await message.reply("🎰 <b>СЛОТЫ</b>\n\n🎲 Крутим барабаны...", parse_mode="HTML")
        # 3 кадра вращения
        for _ in range(3):
            a = random.choice(symbols); b = random.choice(symbols); c = random.choice(symbols)
            await asyncio.sleep(0.3)
            await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Крутим барабаны...\n\n┃ {a} ┃ {b} ┃ {c} ┃", parse_mode="HTML")
        # Остановка по одному
        await asyncio.sleep(0.4)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ ❓ ┃ ❓ ┃", parse_mode="HTML")
        await asyncio.sleep(0.5)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ {r2} ┃ ❓ ┃", parse_mode="HTML")
        await asyncio.sleep(0.6)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃", parse_mode="HTML")
        await asyncio.sleep(0.4)

        # Расчёт
        win = False; mult = 0
        if r1 == r2 == r3:
            win = True
            mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True; mult = 2
        add_xp(user_id, 1)
        update_quest(user_id, "bets_20")

        if win:
            wa = clamp(bet * mult * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "слоты", bet, wa, f"{r1}{r2}{r3}")
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n🎉 <b>ВЫИГРЫШ!</b>\n💰 +{wa:,} (×{mult})\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n😢 -{bet:,}\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML"
            )
        return

    # ── МОНЕТКА ──
    if len(parts) == 2 and parts[0] in ['орёл', 'орел', 'решка']:
        if is_game_disabled('coin') and user_id != ADMIN_ID:
            await message.reply("❌ Монетка выключена"); return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка"); return
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -bet)
        msg = await message.reply("🪙 <b>МОНЕТКА</b>\n\n🎲 Бросаем...", parse_mode="HTML")
        for i, frame in enumerate(ANIM_COIN):
            await asyncio.sleep(ANIM_COIN_DELAYS[i] if i < len(ANIM_COIN_DELAYS) else 0.3)
            await msg.edit_text(f"🪙 <b>МОНЕТКА</b>\n\n🎲 Бросаем...\n\n{frame}", parse_mode="HTML")
        choice = 'heads' if parts[0] in ['орёл', 'орел'] else 'tails'
        result = random.choice(['heads', 'tails'])
        add_xp(user_id, 1)
        update_quest(user_id, "bets_20")
        if result == choice:
            wa = clamp(bet * 2 * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, "🦅" if result == 'heads' else "👑")
            await msg.edit_text(
                f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅' if result == 'heads' else '👑'}\n\n🎉 <b>+{wa:,}</b>\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, "🦅" if result == 'heads' else "👑")
            await msg.edit_text(
                f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅' if result == 'heads' else '👑'}\n\n😢 -{bet:,}\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML"
            )
        return

    # ── БЛЭКДЖЕК ──
    if len(parts) == 2 and parts[0] in ['бж', 'блэкджек']:
        if is_game_disabled('bj') and user_id != ADMIN_ID:
            await message.reply("❌ БЖ выключен"); return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка"); return
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -bet)
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        bj_games[user_id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}
        p_score = hand_score(player)
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Ты: {fmt_hand(player)} = <b>{p_score}</b>\n🤖 Дилер: {fmt_hand(dealer, hide_second=True)}",
            parse_mode="HTML", reply_markup=bj_kb()
        )
        return

    # ── РУЛЕТКА СТАВКИ ──
    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        if is_game_disabled('roulette') and user_id != ADMIN_ID:
            await message.reply("❌ Рулетка выключена"); return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка"); return
        bal = get_balance(user_id)
        if bal < bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -bet)
        bet_type = 'red' if parts[0] == 'к' else ('black' if parts[0] == 'ч' else 'green')
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username,
            "type": bet_type, "bet": bet, "bet_total": bet
        })
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        icon = '🔴' if bet_type == 'red' else ('⚫' if bet_type == 'black' else '🟢')
        await message.reply(
            f"📊 <b>Ставка!</b>\n\n👤 {username}\n{icon} × <b>{bet:,}</b>\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 <code>го</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    # ── МУЛЬТИ-СТАВКА ──
    bet, ranges = parse_multi_bet(text)
    if bet and ranges:
        if bet < 10:
            await message.reply("❌ Мин. 10"); return
        total_bet = bet * len(ranges)
        if total_bet > MAX_BET:
            await message.reply("❌ Максимум"); return
        bal = get_balance(user_id)
        if bal < total_bet and not is_unlimited(user_id):
            await message.reply("❌ Недостаточно!"); return
        set_balance(user_id, -total_bet)
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({
            "user_id": user_id, "username": username, "type": "ranges",
            "bet": bet, "bet_total": total_bet, "ranges": ranges
        })
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        ranges_str = " ".join([f"{a}-{z}" if a != z else str(a) for (a, z) in ranges])
        await message.reply(
            f"📊 <b>Ставка!</b>\n\n🎯 <b>{ranges_str}</b>\n💰 <b>{bet:,}</b> × {len(ranges)} = <b>{total_bet:,}</b>\n\n🕐 <code>го</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return


# ═══════════════ ФОНОВЫЕ ЦИКЛЫ ═══════════════
async def bank_interest_loop():
    while True:
        await asyncio.sleep(86400)
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET bank = bank + (bank * 0.05)::BIGINT WHERE bank > 0")
            conn.commit()
            c.close()
            release_conn(conn)
            print("🏦 Проценты начислены")
        except Exception as e:
            print(f"Ошибка процентов: {e}")


async def giveaway_checker_loop():
    while True:
        await asyncio.sleep(60)
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM giveaways WHERE status = 'active' AND ends_at <= NOW()")
            rows = c.fetchall()
            c.close()
            release_conn(conn)
            for (gid,) in rows:
                result = finish_giveaway(gid)
                if result:
                    wid, prize = result
                    try:
                        wd = get_user(wid)
                        wn = wd[0] if wd else f"user_{wid}"
                        await bot.send_message(ADMIN_ID, f"🎁 Розыгрыш завершён! Победитель: {wn}", parse_mode="HTML")
                        await bot.send_message(wid, f"🎉 Ты выиграл! +{prize} 💎", parse_mode="HTML")
                    except Exception:
                        pass
        except Exception as e:
            print(f"Ошибка giveaway: {e}")


# ═══════════════ ДОПОЛНИТЕЛЬНЫЕ API ДЛЯ MINI APP ═══════════════
@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    xp = get_xp(user_id)
    vip = get_vip_info(xp)
    stats = get_user_stats(user_id)
    titles = get_user_titles(user_id)
    return jsonify({
        "user_id": user_id,
        "username": get_user(user_id)[0] if get_user(user_id) else "",
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "xp": xp,
        "vip_level": vip["level"],
        "vip_name": vip["name"],
        "vip_icon": vip["icon"],
        "cashback": vip["cashback"],
        "titles": titles,
        "stats": stats,
        "unlimited": is_unlimited(user_id),
    })


@app.route('/api/shop')
def api_shop():
    return jsonify(get_shop_items())


@app.route('/api/cases')
def api_cases():
    return jsonify(get_cases())


@app.route('/api/jackpot')
def api_jackpot():
    return jsonify({"jackpot": get_jackpot()})


@app.route('/api/inventory/<int:user_id>')
def api_inventory(user_id):
    return jsonify(get_inventory(user_id))


@app.route('/api/daily/status/<int:user_id>')
def api_daily_status(user_id):
    can, left = get_daily_status(user_id)
    return jsonify({"can_claim": can, "time_left": left, "amount": DAILY_BONUS})


@app.route('/api/daily/claim', methods=['POST'])
def api_daily_claim():
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
    if claim_daily(user_id):
        return jsonify({"success": True, "amount": DAILY_BONUS, "balance": get_balance(user_id)})
    return jsonify({"success": False, "error": "Already claimed"})


@app.route('/api/top')
def api_top():
    mode = request.args.get('mode', 'balance')
    if mode == 'balance':
        rows = get_top(10)
    elif mode == 'xp':
        rows = get_top_xp(10)
    else:
        rows = get_top(10)
    result = []
    for r in rows:
        result.append({
            "user_id": r[0], "username": r[1],
            "balance": r[2], "xp": r[3]
        })
    return jsonify(result)


@app.route('/api/market/lots')
def api_market_lots():
    return jsonify(get_market_lots())
# ═══════════════ ПРЕДОПЛАТА ═══════════════
@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


# ═══════════════ УСПЕШНАЯ ОПЛАТА ═══════════════
@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)

    # ═══════ БУСТ (старый формат buy_boost_) ═══════
    if payload.startswith("boost_"):
        parts = payload.split("_")
        try:
            mult = int(parts[1])
            minutes = int(parts[2])
        except Exception:
            await message.answer("❌ Ошибка буста", parse_mode="HTML")
            return
        until = add_boost(user_id, mult, minutes)
        await message.answer(
            f"✅ <b>БУСТ АКТИВИРОВАН!</b>\n\n"
            f"⚡ Множитель: <b>×{mult}</b>\n"
            f"⏱️ До: <b>{(until + timedelta(hours=3)).strftime('%H:%M:%S')}</b>\n\n"
            f"🎰 Заходи в игры!",
            parse_mode="HTML"
        )
        return

    # ═══════ МАГАЗИН 2.0 — за Stars ═══════
    if payload.startswith("shop_stars_"):
        try:
            idx = int(payload.replace("shop_stars_", ""))
        except Exception:
            await message.answer("❌ Ошибка товара", parse_mode="HTML")
            return
        items = get_shop_items()
        if idx < 0 or idx >= len(items):
            await message.answer("❌ Товар не найден", parse_mode="HTML")
            return
        it = items[idx]
        reward_text = grant_shop_item(user_id, it)
        await message.answer(
            f"✅ <b>КУПЛЕНО!</b>\n\n"
            f"🎁 {reward_text}\n\n"
            f"📦 Предмет в инвентаре!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop")]
            ])
        )
        return

    # ═══════ КЕЙС (открытие с выбором) ═══════
    if payload.startswith("case_"):
        case_id = payload.replace("case_", "")
        case = get_case_by_id(case_id)
        if not case:
            await message.answer("❌ Кейс не найден", parse_mode="HTML")
            return

        # Анимация открытия
        msg = await message.answer("🎰 <b>ОТКРЫВАЕМ КЕЙС...</b>\n\n[ ▓▓▓▓▓ ]", parse_mode="HTML")
        for frame in ["[ ▓▓▓░░ ]", "[ ▓▓░░░ ]", "[ ▓░░░░ ]", "[ ░░░░░ ]"]:
            await asyncio.sleep(0.4)
            try:
                await msg.edit_text(f"🎰 <b>ОТКРЫВАЕМ КЕЙС...</b>\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass

        reward = roll_case_reward(case)
        if not reward:
            await msg.edit_text("❌ Кейс пуст", parse_mode="HTML")
            return

        # Кладём в инвентарь
        reward_text = apply_case_reward_to_inventory(user_id, reward)
        # Сохраняем reward для анимации в Mini App
        save_last_reward(user_id, {
            "type": reward.get("type"),
            "mult": reward.get("mult"),
            "minutes": reward.get("minutes"),
            "title": reward.get("title"),
            "vip_level": reward.get("vip_level"),
            "case_name": case.get("name", ""),
        })

        # Достаём inv_id последнего предмета
        inv = get_inventory(user_id)
        last_inv_id = None
        if inv:
            last_inv_id = inv[-1].get("inv_id")

        # Кнопки выбора
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Использовать сейчас", callback_data=f"case_use_{last_inv_id}"),
             InlineKeyboardButton(text="📦 Оставить на полке", callback_data="case_keep")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")]
        ])
        await msg.edit_text(
            f"🎉 <b>КЕЙС «{case['name']}» ОТКРЫТ!</b>\n\n"
            f"🎁 Тебе выпало:\n"
            f"<b>{reward_text}</b>\n\n"
            f"👇 Что делаем?",
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # ═══════ FALLBACK ═══════
    print(f"⚠️ Неизвестный payload: {payload}")
    await message.answer("✅ Оплата получена!")


# ═══════════════ ОБРАБОТЧИКИ КНОПОК ПОСЛЕ КЕЙСА ═══════════════
@dp.callback_query(F.data.startswith("case_use_"))
async def case_use_handler(call: CallbackQuery):
    user_id = call.from_user.id
    inv_id = call.data.replace("case_use_", "")
    if not inv_id or inv_id == "None":
        await call.answer("❌ Предмет не найден", show_alert=True)
        return
    ok, msg_text = use_inventory_item(user_id, inv_id)
    if ok:
        await call.answer("✅ Активировано!", show_alert=True)
        try:
            await call.message.edit_text(
                f"✅ <b>АКТИВИРОВАНО!</b>\n\n{msg_text}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                    [InlineKeyboardButton(text="🎰 Ещё кейс", callback_data="menu_cases")]
                ])
            )
        except Exception:
            pass
    else:
        await call.answer(msg_text, show_alert=True)


@dp.callback_query(F.data == "case_keep")
async def case_keep_handler(call: CallbackQuery):
    await call.answer("📦 Предмет лежит на полке", show_alert=True)
    try:
        await call.message.edit_text(
            "📦 <b>ПРЕДМЕТ НА ПОЛКЕ</b>\n\n"
            "Он в твоём инвентаре. Активируешь, когда захочешь.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                [InlineKeyboardButton(text="🎰 Ещё кейс", callback_data="menu_cases")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
            ])
        )
    except Exception:
        pass


# ═══════════════ ДЖЕКПОТ: КНОПКИ В АДМИН-ПАНЕЛИ ═══════════════
@dp.callback_query(F.data == "admin_jackpot")
async def admin_jackpot_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    jp = get_jackpot()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сбросить до 10 000", callback_data="admin_jackpot_reset")],
        [InlineKeyboardButton(text="💰 Установить", callback_data="admin_jackpot_set"),
         InlineKeyboardButton(text="📊 Обновить", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    txt = (
        f"💎 <b>ДЖЕКПОТ</b>\n\n"
        f"💰 Текущий: <b>{jp:,}</b>\n\n"
        f"💡 Пополняется:\n"
        f"• 1% со ставок рулетки\n"
        f"• 5% с рынка\n\n"
        f"🎯 Срывается: 🟢 Зеро в рулетке".replace(',', ' ')
    )
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data == "admin_jackpot_reset")
async def admin_jackpot_reset_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    old = get_jackpot()
    reset_jackpot()
    await call.answer(f"✅ Сброшен с {old:,} до 10 000".replace(',', ' '), show_alert=True)
    jp = get_jackpot()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сбросить до 10 000", callback_data="admin_jackpot_reset")],
        [InlineKeyboardButton(text="💰 Установить", callback_data="admin_jackpot_set"),
         InlineKeyboardButton(text="📊 Обновить", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await call.message.edit_text(
        f"💎 <b>ДЖЕКПОТ</b>\n\n💰 Текущий: <b>{jp:,}</b>".replace(',', ' '),
        parse_mode="HTML", reply_markup=kb
    )


@dp.callback_query(F.data == "admin_jackpot_set")
async def admin_jackpot_set_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    admin_action_state[call.from_user.id] = {"mode": "jackpot_set"}
    await call.message.edit_text(
        "💰 <b>УСТАНОВИТЬ ДЖЕКПОТ</b>\n\nВведи сумму:\n\n❌ Отмена: /admin",
        parse_mode="HTML"
    )
    await call.answer()
    # ═══════════════ API: ПОКУПКА КЕЙСОВ ═══════════════
@app.route('/api/cases/buy', methods=['POST'])
def api_cases_buy():
    import requests as _requests
    data = request.json
    user_id = data.get('user_id')
    case_id = data.get('case_id')
    if not user_id or not case_id:
        return jsonify({"error": "Missing"}), 400
    case = get_case_by_id(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    try:
        # Используем прямой Telegram Bot API через requests (синхронно)
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"Кейс «{case['name']}»",
            "description": case.get("desc", "Кейс с наградами"),
            "payload": f"case_{case_id}",
            "currency": "XTR",
            "prices": json.dumps([
                {"label": case["name"], "amount": int(case["stars"])}
            ]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        else:
            print(f"Telegram API error: {result}")
            return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        print(f"Ошибка создания invoice кейса: {e}")
        return jsonify({"error": str(e)}), 500

    async def create_invoice():
        try:
            from aiogram.types import LabeledPrice
            invoice_link = await bot.create_invoice_link(
                title=f"Кейс «{case['name']}»",
                description=case.get("desc", "Кейс с наградами"),
                payload=f"case_{case_id}",
                currency="XTR",
                prices=[LabeledPrice(label=case["name"], amount=int(case["stars"]))],
            )
            return invoice_link
        except Exception as e:
            print(f"Ошибка создания invoice кейса: {e}")
            return None

    try:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        invoice_link = loop.run_until_complete(create_invoice())
        loop.close()
    except Exception as e:
        print(f"Loop error: {e}")
        return jsonify({"error": "Loop error"}), 500

    if not invoice_link:
        return jsonify({"error": "Failed to create invoice"}), 500

    return jsonify({"invoice_url": invoice_link})


# ═══════════════ API: ПОКУПКА ТОВАРА МАГАЗИНА ═══════════════
@app.route('/api/shop/buy', methods=['POST'])
def api_shop_buy():
    import requests as _requests
    data = request.json
    user_id = data.get('user_id')
    item_id = data.get('item_id')
    if not user_id or not item_id:
        return jsonify({"error": "Missing"}), 400

    items = get_shop_items()
    item = next((it for it in items if it.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Item not found"}), 404

    stars = item.get("stars", 0)
    if not stars or int(stars) < 1:
        return jsonify({"error": "Item not available for Stars"}), 400

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": item["name"],
            "description": item.get("desc", ""),
            "payload": f"shop_stars_{items.index(item)}",
            "currency": "XTR",
            "prices": json.dumps([
                {"label": item["name"], "amount": int(stars)}
            ]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        else:
            print(f"Telegram API error: {result}")
            return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        print(f"Ошибка создания invoice товара: {e}")
        return jsonify({"error": str(e)}), 500

    async def create_invoice():
        try:
            from aiogram.types import LabeledPrice
            invoice_link = await bot.create_invoice_link(
                title=item["name"],
                description=item.get("desc", ""),
                payload=f"shop_stars_{items.index(item)}",
                currency="XTR",
                prices=[LabeledPrice(label=item["name"], amount=int(stars))],
            )
            return invoice_link
        except Exception as e:
            print(f"Ошибка создания invoice товара: {e}")
            return None

    try:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        invoice_link = loop.run_until_complete(create_invoice())
        loop.close()
    except Exception as e:
        print(f"Loop error: {e}")
        return jsonify({"error": "Loop error"}), 500

    if not invoice_link:
        return jsonify({"error": "Failed to create invoice"}), 500

    return jsonify({"invoice_url": invoice_link})
    # ═══════════════ ФУНКЦИИ: last_reward ═══════════════
def save_last_reward(user_id, reward):
    try:
        conn = get_conn()
        c = conn.cursor()
        value = json.dumps(reward, ensure_ascii=False)
        key = f"last_reward_{user_id}"
        c.execute("""INSERT INTO settings (key, value) VALUES (%s, %s)
                     ON CONFLICT (key) DO UPDATE SET value = %s""",
                  (key, value, value))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"save_last_reward error: {e}")


def get_last_reward(user_id):
    try:
        conn = get_conn()
        c = conn.cursor()
        key = f"last_reward_{user_id}"
        c.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        print(f"get_last_reward error: {e}")
    return None


# ═══════════════ API: ПОСЛЕДНИЙ REWARD КЕЙСА ═══════════════
@app.route('/api/cases/last_reward/<int:user_id>')
def api_last_reward(user_id):
    reward = get_last_reward(user_id)
    if reward:
        return jsonify(reward)
    return jsonify({})


# ═══════════════ API: ИГРА РУЛЕТКА ═══════════════
@app.route('/api/game/roulette', methods=['POST'])
def api_game_roulette():
    import random as _random
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    choice = data.get('choice', 'red')

    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400

    balance = get_balance(user_id)
    is_unl = is_unlimited(user_id)
    if balance < bet and not is_unl:
        return jsonify({"error": "Not enough balance"}), 400

    set_balance(user_id, -bet)

    result = _random.randint(0, 36)
    if result == 0:
        color = "green"
    elif result in RED_NUMBERS:
        color = "red"
    else:
        color = "black"

    mult = 0
    win = False
    if choice == "red" and color == "red":
        win, mult = True, 2
    elif choice == "black" and color == "black":
        win, mult = True, 2
    elif choice == "green" and color == "green":
        win, mult = True, 36

    amount = 0
    if win:
        amount = int(bet * mult * get_event_mult() * get_user_mult(user_id))
        amount = clamp(amount)
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "рулетка", bet, amount, f"{result} {color}")

    add_xp(user_id, 1)
    update_quest(user_id, "roulette_10")

    return jsonify({
        "win": win,
        "result": result,
        "color": color,
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ API: ИГРА СЛОТЫ ═══════════════
@app.route('/api/game/slots', methods=['POST'])
def api_game_slots():
    import random as _random
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))

    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400

    balance = get_balance(user_id)
    is_unl = is_unlimited(user_id)
    if balance < bet and not is_unl:
        return jsonify({"error": "Not enough balance"}), 400

    set_balance(user_id, -bet)

    symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
    r1 = _random.choice(symbols)
    r2 = _random.choice(symbols)
    r3 = _random.choice(symbols)

    win = False
    mult = 0
    if r1 == r2 == r3:
        win = True
        mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
    elif r1 == r2 or r2 == r3 or r1 == r3:
        win = True
        mult = 2

    amount = 0
    if win:
        amount = int(bet * mult * get_event_mult() * get_user_mult(user_id))
        amount = clamp(amount)
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "слоты", bet, amount, f"{r1}{r2}{r3}")

    add_xp(user_id, 1)
    update_quest(user_id, "bets_20")

    return jsonify({
        "win": win,
        "reels": [r1, r2, r3],
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ API: ИГРА МОНЕТКА ═══════════════
@app.route('/api/game/coin', methods=['POST'])
def api_game_coin():
    import random as _random
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    choice = data.get('choice', 'heads')

    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400

    balance = get_balance(user_id)
    is_unl = is_unlimited(user_id)
    if balance < bet and not is_unl:
        return jsonify({"error": "Not enough balance"}), 400

    set_balance(user_id, -bet)

    result = "heads" if _random.random() < 0.5 else "tails"
    win = result == choice

    amount = 0
    if win:
        amount = int(bet * 2 * get_event_mult() * get_user_mult(user_id))
        amount = clamp(amount)
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "монетка", bet, amount, "🦅" if result == "heads" else "👑")

    add_xp(user_id, 1)
    update_quest(user_id, "bets_20")

    return jsonify({
        "win": win,
        "result": result,
        "amount": amount,
        "bet": bet,
        "balance": get_balance(user_id),
    })


# ═══════════════ API: ИГРА МИНЫ ═══════════════
@app.route('/api/game/mines/start', methods=['POST'])
def api_mines_start():
    import random as _random
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    level = data.get('level', 'easy')

    if not user_id or bet < 10 or level not in MINES_LEVELS:
        return jsonify({"error": "Invalid"}), 400

    balance = get_balance(user_id)
    is_unl = is_unlimited(user_id)
    if balance < bet and not is_unl:
        return jsonify({"error": "Not enough balance"}), 400

    set_balance(user_id, -bet)

    mines_count = MINES_LEVELS[level]["mines"]
    positions = list(range(25))
    _random.shuffle(positions)
    mine_positions = set(positions[:mines_count])

    game_data = {
        "bet": bet,
        "level": level,
        "mines": list(mine_positions),
        "opened": [],
    }
    conn = get_conn()
    c = conn.cursor()
    key = f"mines_game_{user_id}"
    value = json.dumps(game_data)
    c.execute("""INSERT INTO settings (key, value) VALUES (%s, %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""",
              (key, value, value))
    conn.commit()
    c.close()
    release_conn(conn)

    return jsonify({
        "success": True,
        "level": level,
        "bet": bet,
        "mines_count": mines_count,
    })


@app.route('/api/game/mines/open', methods=['POST'])
def api_mines_open():
    data = request.json
    user_id = data.get('user_id')
    idx = int(data.get('idx', -1))

    if not user_id or idx < 0 or idx > 24:
        return jsonify({"error": "Invalid"}), 400

    conn = get_conn()
    c = conn.cursor()
    key = f"mines_game_{user_id}"
    c.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = c.fetchone()
    c.close()
    release_conn(conn)

    if not row or not row[0]:
        return jsonify({"error": "No active game"}), 400

    game = json.loads(row[0])
    if idx in game["opened"]:
        return jsonify({"error": "Already opened"}), 400

    is_mine = idx in game["mines"]

    if is_mine:
        game["opened"].append(idx)
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()
        c.close()
        release_conn(conn)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "мины", game["bet"], 0, f"{game['level']} бум")
        return jsonify({
            "mine": True,
            "idx": idx,
            "win": False,
            "amount": 0,
            "mines": game["mines"],
            "balance": get_balance(user_id),
        })

    game["opened"].append(idx)
    opened_count = len(game["opened"])
    step = MINES_LEVELS[game["level"]]["step"]
    mult = round(1 + opened_count * step, 2)
    safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]

    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(game)
    c.execute("UPDATE settings SET value = %s WHERE key = %s", (value, key))
    conn.commit()
    c.close()
    release_conn(conn)

    if opened_count == safe_total:
        wa = clamp(int(game["bet"] * mult * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, wa)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "мины", game["bet"], wa, f"{game['level']} all")
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()
        c.close()
        release_conn(conn)
        return jsonify({
            "mine": False,
            "idx": idx,
            "win": True,
            "amount": wa,
            "balance": get_balance(user_id),
            "mult": mult,
            "cashout_auto": True,
            "mines": game["mines"],
        })

    return jsonify({
        "mine": False,
        "idx": idx,
        "win": False,
        "amount": 0,
        "mult": mult,
        "opened": game["opened"],
        "balance": get_balance(user_id),
    })


@app.route('/api/game/mines/cashout', methods=['POST'])
def api_mines_cashout():
    data = request.json
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"error": "Invalid"}), 400

    conn = get_conn()
    c = conn.cursor()
    key = f"mines_game_{user_id}"
    c.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = c.fetchone()
    c.close()
    release_conn(conn)

    if not row or not row[0]:
        return jsonify({"error": "No active game"}), 400

    game = json.loads(row[0])
    if not game["opened"]:
        return jsonify({"error": "Open at least 1 cell"}), 400

    opened_count = len(game["opened"])
    step = MINES_LEVELS[game["level"]]["step"]
    mult = round(1 + opened_count * step, 2)
    wa = clamp(int(game["bet"] * mult * get_event_mult() * get_user_mult(user_id)))
    set_balance(user_id, wa)
    u = get_user(user_id)
    uname = u[0] if u else "user"
    log_game(user_id, uname, "мины", game["bet"], wa, f"{game['level']} x{mult}")

    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key = %s", (key,))
    conn.commit()
    c.close()
    release_conn(conn)

    return jsonify({
        "win": True,
        "amount": wa,
        "mult": mult,
        "balance": get_balance(user_id),
    })
    # ═══════════════ API: ВСЕ ИГРОКИ ═══════════════
@app.route('/api/players')
def api_players():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, username, balance, xp, banned, unlimited
        FROM users
        ORDER BY balance DESC
    """)
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
    total_balance = c.fetchone()[0]
    c.execute("""
        SELECT COUNT(DISTINCT user_id) FROM game_log
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """)
    active_24h = c.fetchone()[0]
    c.close()
    release_conn(conn)

    players = []
    for r in rows:
        players.append({
            "user_id": r[0],
            "username": r[1] or f"user_{r[0]}",
            "balance": r[2] or 0,
            "xp": r[3] or 0,
            "banned": bool(r[4]),
            "unlimited": bool(r[5]),
        })

    return jsonify({
        "total": total,
        "banned": banned,
        "active_24h": active_24h,
        "total_balance": total_balance,
        "players": players,
    })


# ═══════════════ КОМАНДА /players ═══════════════
@dp.message(Command("players", "игроки"))
async def cmd_players(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, username, balance, banned
        FROM users
        ORDER BY balance DESC
        LIMIT 30
    """)
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
    total_balance = c.fetchone()[0]
    c.execute("""
        SELECT COUNT(DISTINCT user_id) FROM game_log
        WHERE created_at > NOW() - INTERVAL '24 hours'
    """)
    active_24h = c.fetchone()[0]
    c.close()
    release_conn(conn)

    medals = ["🥇", "🥈", "🥉"]
    txt = f"👥 <b>ВСЕ ИГРОКИ</b>\n"
    txt += f"━━━━━━━━━━━━━━━━━━\n\n"

    for i, row in enumerate(rows):
        uid, uname, bal, is_banned = row
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        ban_icon = " 🚫" if is_banned else ""
        uname = uname or f"user_{uid}"
        bal_str = f"{bal:,}".replace(',', ' ')
        txt += f"{medal} {uname} — <b>{bal_str}</b> 💎{ban_icon}\n"

    if total > 30:
        txt += f"\n<i>...и ещё {total - 30}</i>\n"

    txt += f"\n━━━━━━━━━━━━━━━━━━\n"
    txt += f"📊 Всего: <b>{total}</b>\n"
    txt += f"🟢 Активных за 24ч: <b>{active_24h}</b>\n"
    txt += f"🚫 Забанено: <b>{banned}</b>\n"
    txt += f"💎 Общий баланс: <b>{total_balance:,}</b>".replace(',', ' ')

    await message.answer(txt, parse_mode="HTML")




# ═══════════════ MAIN ═══════════════
async def main():
    init_pool()
    init_db()
    load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
    )
    print("🎰 Бот запущен!")
    asyncio.create_task(bank_interest_loop())
    asyncio.create_task(giveaway_checker_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
