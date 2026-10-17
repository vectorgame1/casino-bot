# ═══════════════════════════════════════════════════════════════
# database.py — ВСЯ РАБОТА С БАЗОЙ ДАННЫХ
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
    """Создаёт пул соединений."""
    global _db_pool
    try:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=50,
            dsn=DATABASE_URL,
            sslmode='require',
        )
        print("✅ Connection pool создан")
    except Exception as e:
        print(f"⚠️ Пул не создан: {e}")
        _db_pool = None


def get_conn():
    """Берёт соединение с проверкой живости."""
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
                try:
                    _db_pool.putconn(conn, close=True)
                except Exception:
                    pass
                return _db_pool.getconn()
        except pool.PoolError:
            try:
                _db_pool.closeall()
            except Exception:
                pass
            init_pool()
            return _db_pool.getconn()
        except Exception:
            return psycopg2.connect(DATABASE_URL, sslmode='require')
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def release_conn(conn):
    """Возвращает соединение в пул."""
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
    """Создаёт все таблицы и индексы."""
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
        chat_id BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        amount BIGINT NOT NULL,
        detail TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        alert_type TEXT NOT NULL,
        priority TEXT DEFAULT 'medium',
        text TEXT,
        status TEXT DEFAULT 'new',
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS last_bets (
        user_id BIGINT PRIMARY KEY,
        chat_id BIGINT,
        bets JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS credits (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        amount BIGINT NOT NULL,
        issued_at TIMESTAMP DEFAULT NOW(),
        due_at TIMESTAMP NOT NULL,
        returned_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        reminded BOOLEAN DEFAULT FALSE
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS active_vip (
        user_id BIGINT PRIMARY KEY,
        tier INT DEFAULT 0,
        expires_at TIMESTAMP,
        purchased_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS boosts (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        mult INT,
        until TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS titles (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        granted_by BIGINT,
        granted_at TIMESTAMP DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS daily_quests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        quest_key TEXT NOT NULL,
        progress BIGINT DEFAULT 0,
        claimed BOOLEAN DEFAULT FALSE,
        reset_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, quest_key)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS group_members (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,
        user_id BIGINT,
        username TEXT,
        last_seen TIMESTAMP DEFAULT NOW(),
        UNIQUE(chat_id, user_id)
    )""")

    # Индексы
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_chat ON game_log(chat_id, game)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at DESC)")

    conn.commit()
    c.close()
    release_conn(conn)
    print("✅ БД инициализирована")


def add_columns():
    """Добавляет недостающие колонки."""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS inventory JSONB DEFAULT '[]'::jsonb")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_earnings BIGINT DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_count INT DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday TEXT")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'ru'")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INT DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date DATE")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_blocked BOOLEAN DEFAULT FALSE")
        c.execute("ALTER TABLE game_log ADD COLUMN IF NOT EXISTS chat_id BIGINT")
        conn.commit()
    except Exception as e:
        print(f"⚠️ add_columns: {e}")
    c.close()
    release_conn(conn)


# ═══════════════ CRUD: USERS ═══════════════

def get_user(user_id: int):
    """Возвращает (username, balance) или None."""
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


def get_user_id_by_username(username: str):
    """Ищет ID по @username."""
    if username.startswith('@'):
        username = username[1:]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else None


def ensure_user(user_id: int, username: str):
    """Создаёт юзера, если его нет."""
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
    user = get_user(user_id)
    return user[1] if user else 1000


def set_balance(user_id: int, amount: int) -> int:
    """Изменяет баланс."""
    from utils import clamp
    amount = clamp(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, 1000) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_balance = row[0] if row else 0

    if new_balance > MAX_BALANCE:
        overflow = new_balance - MAX_BALANCE
        c.execute("UPDATE users SET balance = %s, bank = LEAST(bank + %s, %s) WHERE user_id = %s",
                  (MAX_BALANCE, overflow, MAX_BANK, user_id))
        new_balance = MAX_BALANCE
    elif new_balance < 0:
        c.execute("UPDATE users SET balance = 0 WHERE user_id = %s", (user_id,))
        new_balance = 0

    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return new_balance


def set_balance_exact(user_id: int, amount: int) -> int:
    """Устанавливает точный баланс."""
    from utils import clamp_balance
    amount, overflow = clamp_balance(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, balance) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET balance = %s",
        (user_id, amount, amount)
    )
    if overflow > 0:
        c.execute("UPDATE users SET bank = LEAST(bank + %s, %s) WHERE user_id = %s",
                  (overflow, MAX_BANK, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return amount


# ═══════════════ БАНК ═══════════════

def get_bank(user_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row and row[0] else 0


def set_bank(user_id: int, amount: int) -> int:
    from utils import clamp
    amount = clamp(amount)
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, bank) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_bank = row[0] if row else 0

    if new_bank > MAX_BANK:
        c.execute("UPDATE users SET bank = %s WHERE user_id = %s", (MAX_BANK, user_id))
        new_bank = MAX_BANK
    elif new_bank < 0:
        c.execute("UPDATE users SET bank = 0 WHERE user_id = %s", (user_id,))
        new_bank = 0

    conn.commit()
    c.close()
    release_conn(conn)
    return new_bank


# ═══════════════ БАН / БЕЗЛИМИТ ═══════════════

def is_banned(user_id: int) -> bool:
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


def set_banned(user_id: int, banned: bool = True):
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


def is_unlimited(user_id: int) -> bool:
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


def set_unlimited(user_id: int, unlimited: bool = True):
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


# ═══════════════ XP ═══════════════

def get_xp(user_id: int) -> int:
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


def add_xp(user_id: int, amount: int) -> tuple:
    """Начисляет XP. Возвращает (new_xp, level_changed, new_level)."""
    if amount <= 0:
        return get_xp(user_id), False, 0
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    old_xp = c.fetchone()[0] or 0
    old_level = old_xp // 100
    c.execute("UPDATE users SET xp = xp + %s WHERE user_id = %s", (amount, user_id))
    new_xp = old_xp + amount
    new_level = new_xp // 100
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{user_id}")
    cache_invalidate(f"user_{user_id}")
    return new_xp, (new_level > old_level), new_level


# ═══════════════ ЛОГИ ═══════════════

def log_transaction(user_id: int, type_: str, amount: int, detail: str = ""):
    """Записывает транзакцию."""
    try:
        from utils import clamp
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO transactions (user_id, type, amount, detail)
                     VALUES (%s, %s, %s, %s)""",
                  (user_id, type_, clamp(amount), detail))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[log_transaction] {e}")


def log_game(user_id: int, username: str, game: str, bet: int, win: int, detail: str, chat_id: int = None):
    """Записывает игру."""
    from utils import clamp
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO game_log (user_id, username, game, bet, win, detail, time, chat_id)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
              (user_id, username, game, clamp(bet), clamp(win), detail,
               datetime.now(TZ_MINSK).strftime("%H:%M:%S"), chat_id))

    if win > 0:
        c.execute("UPDATE users SET total_won = total_won + %s WHERE user_id = %s", (win, user_id))
    else:
        c.execute("UPDATE users SET total_lost = total_lost + %s WHERE user_id = %s", (bet, user_id))

    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("top_balance")
    cache_invalidate("top_xp")

    if win > 0:
        log_transaction(user_id, "game_win", win, f"{game}: {detail}")
    else:
        log_transaction(user_id, "game_loss", -bet, f"{game}: {detail}")


# ═══════════════ TOP ═══════════════

def get_top(limit: int = 10):
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


def get_top_xp(limit: int = 10):
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


def get_total_players() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else 0

# ═══════════════════════════════════════════════════════════════
# settings — курс (PostgreSQL)
# ═══════════════════════════════════════════════════════════════

def get_rate(key: str, default: int) -> int:
    """Получить курс из БД (или default)."""
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
    """Установить курс."""
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

# ═══════════════════════════════════════════════════════════════
# НОВЫЕ ФУНКЦИИ ДЛЯ БОНУСА И КУРСА
# ═══════════════════════════════════════════════════════════════

def check_and_give_bonus(user_id: int, bonus_amount: int) -> bool:
    """Проверяет, получал ли юзер бонус. Если нет - начисляет."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT got_start_bonus FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    
    if row and row[0] is True:
        c.close()
        release_conn(conn)
        return False  # Уже получал
        
    # Если не получал — выдаем
    c.execute("UPDATE users SET got_start_bonus = TRUE, balance = balance + %s WHERE user_id = %s", (bonus_amount, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"user_{user_id}")
    return True


def get_rate(key: str, default: int) -> int:
    """Получить курс из БД (или default)."""
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
    """Установить курс."""
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