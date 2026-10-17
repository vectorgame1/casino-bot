# ═══════════════════════════════════════════════════════════════
# database.py — ВСЯ РАБОТА С БАЗОЙ (v2)
# ═══════════════════════════════════════════════════════════════

import psycopg2
from psycopg2 import pool
import time
import json
from datetime import datetime, timedelta

from config import (
    DATABASE_URL, TZ_MINSK,
    MAX_BALANCE, MAX_BANK,
)

# ═══════════════ ПУЛ СОЕДИНЕНИЙ ═══════════════
_db_pool = None

def init_pool():
    global _db_pool
    try:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=2, maxconn=20, dsn=DATABASE_URL, sslmode='require'
        )
        print("✅ Connection pool создан")
    except Exception as e:
        print(f"⚠️ Пул не создан: {e}")
        _db_pool = None

def get_conn():
    global _db_pool
    if _db_pool:
        try:
            conn = _db_pool.getconn()
            try:
                c = conn.cursor()
                c.execute("SELECT 1")
                c.close()
                return conn
            except Exception:
                try: _db_pool.putconn(conn, close=True)
                except: pass
                return _db_pool.getconn()
        except Exception:
            try: _db_pool.closeall()
            except: pass
            init_pool()
            return _db_pool.getconn()
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def release_conn(conn):
    if _db_pool:
        _db_pool.putconn(conn)
    else:
        conn.close()

# ═══════════════ КЭШ ═══════════════
_cache = {}

def cache_get(key: str, ttl: int = 30):
    if key in _cache:
        val, exp = _cache[key]
        if time.time() < exp:
            return val
    return None

def cache_set(key: str, value, ttl: int = 30):
    _cache[key] = (value, time.time() + ttl)

def cache_invalidate(prefix: str = None):
    if prefix is None:
        _cache.clear()
    else:
        keys = [k for k in _cache.keys() if k.startswith(prefix)]
        for k in keys:
            _cache.pop(k, None)

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
        total_won BIGINT DEFAULT 0,
        referrer_id BIGINT,
        ref_count INT DEFAULT 0,
        ref_earnings BIGINT DEFAULT 0,
        login_streak INT DEFAULT 0,
        last_login_date DATE
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
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
    
    conn.commit()
    c.close()
    release_conn(conn)
    print("✅ БД инициализирована")

# ═══════════════ CRUD ПОЛЬЗОВАТЕЛЕЙ ═══════════════
def ensure_user(user_id: int, username: str):
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

def get_balance(user_id: int) -> int:
    cache_key = f"user_{user_id}"
    cached = cache_get(cache_key, ttl=5)
    if cached: return cached[1]
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    
    if row:
        cache_set(cache_key, row, ttl=5)
        return row[1]
    return 0

def set_balance(user_id: int, amount: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_bal = row[0] if row else 0

    if new_bal > MAX_BALANCE:
        overflow = new_bal - MAX_BALANCE
        c.execute("UPDATE users SET balance = %s, bank = LEAST(bank + %s, %s) WHERE user_id = %s", (MAX_BALANCE, overflow, MAX_BANK, user_id))
        new_bal = MAX_BALANCE
    elif new_bal < 0:
        c.execute("UPDATE users SET balance = 0 WHERE user_id = %s", (user_id,))
        new_bal = 0

    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return new_bal

def check_and_give_bonus(user_id: int, bonus_amount: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT got_start_bonus FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    if row and row[0] is True:
        c.close()
        release_conn(conn)
        return False
    c.execute("UPDATE users SET got_start_bonus = TRUE, balance = balance + %s WHERE user_id = %s", (bonus_amount, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return True

def is_banned(user_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return bool(row[0]) if row else False

# ═══════════════ НАСТРОЙКИ (КУРС) ═══════════════
def get_rate(key: str, default: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row:
        return int(row[0])
    return default

def set_rate(key: str, value: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = %s",
        (key, str(value), str(value))
    )
    conn.commit()
    c.close()
    release_conn(conn)

# ═══════════════ ЛОГИ ═══════════════
def log_game(user_id: int, username: str, game: str, bet: int, win: int, detail: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO game_log (user_id, username, game, bet, win, detail, time)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)""",
              (user_id, username, game, bet, win, detail, datetime.now(TZ_MINSK).strftime("%H:%M:%S")))
    conn.commit()
    c.close()
    release_conn(conn)

# ═══════════════ ТОП И XP ═══════════════
def get_top(limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY balance DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows

def get_xp(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else 0