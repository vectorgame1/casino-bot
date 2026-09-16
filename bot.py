import asyncio
import logging
import os
import threading
import random
import psycopg2
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask, jsonify, request
from flask_cors import CORS

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 6403424348
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MINI_APP_URL = "https://vectorgame1.github.io/casino/"

RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]

MULT_COLOR = 2
MULT_ZERO = 36
MULT_NUMBER = 36
MULT_RANGE = 1.2

MAX_BIGINT = 9_000_000_000_000_000_000
MAX_BET = 100_000_000_000

def clamp(x):
    try:
        return max(-MAX_BIGINT, min(int(x), MAX_BIGINT))
    except:
        return 0

MINES_LEVELS = {
    "easy":   {"name": "🟢 Лёгкий",   "mines": 3,  "step": 0.15},
    "medium": {"name": "🟡 Средний",  "mines": 5,  "step": 0.25},
    "hard":   {"name": "🔴 Хардкор",  "mines": 10, "step": 0.50},
}

VIP_LEVELS = [
    {"name": "🥉 Бронза",  "xp": 0,     "cashback": 1,  "icon": "🥉"},
    {"name": "🥈 Серебро", "xp": 100,   "cashback": 3,  "icon": "🥈"},
    {"name": "🥇 Золото",  "xp": 500,   "cashback": 5,  "icon": "🥇"},
    {"name": "💎 Платина", "xp": 2000,  "cashback": 7,  "icon": "💎"},
    {"name": "👑 Алмаз",   "xp": 10000, "cashback": 10, "icon": "👑"},
]

QUESTS = [
    {"key": "roulette_10",  "name": "🎡 Сыграй 10 раз в рулетку",  "target": 10,     "reward": 5000},
    {"key": "mines_win_5",  "name": "💣 Выиграй 5 раз в Мины",     "target": 5,      "reward": 5000},
    {"key": "bets_20",      "name": "🎰 Сделай 20 ставок",          "target": 20,     "reward": 10000},
    {"key": "win_100k",     "name": "💰 Выиграй 100 000 токенов",   "target": 100000, "reward": 20000},
    {"key": "bj_5",         "name": "🃏 Сыграй в Блэкджек 5 раз",   "target": 5,      "reward": 5000},
    {"key": "jackpot_1",    "name": "💎 Сорви джекпот",              "target": 1,      "reward": 100000},
]

ACHIEVEMENTS = [
    {"key": "first_jackpot",  "name": "🎰 Первый джекпот"},
    {"key": "millionaire",    "name": "💰 Миллионер"},
    {"key": "lucky_36",       "name": "🍀 Счастливчик (×36)"},
    {"key": "crash_10x",      "name": "🚀 Краш ×10"},
    {"key": "mines_all",      "name": "💎 Очистил поле"},
]

GAME_NAMES = {
    "roulette": "🎡 Рулетка",
    "slots": "🎰 Слоты",
    "coin": "🪙 Монетка",
    "mines": "💣 Мины",
    "bj": "🃏 Блэкджек",
    "duel": "⚔️ Дуэль",
}

ANIM_ROULETTE = ["🔴 ⚫ 🔴 ⚫ 🔴", "⚫ 🔴 ⚫ 🔴 ⚫", "🔴 ⚫ 🔴 ⚫ 🔴", "⚫ 🔴 ⚫ 🔴 ⚫"]
ANIM_SLOTS = [
    "┃ 🍒 ┃ 🍋 ┃ 🍊 ┃",
    "┃ 🍇 ┃ 💎 ┃ 7️⃣ ┃",
    "┃ 🍊 ┃ 🍒 ┃ 🍋 ┃",
    "┃ 💎 ┃ 7️⃣ ┃ 🍇 ┃",
]
ANIM_COIN = ["🦅", "👑", "🦅", "👑"]
ANIM_DUEL = ["🔴", "🔵", "🔴", "🔵", "🔴"]

active_bets = {}
bj_games = {}
duel_games = {}
mines_games = {}
disabled_games = set()
giveaway_timers = {}

event_double = False
maintenance_on = False
jackpot_amount = 10000

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
        "level": level,
        "name": v["name"],
        "icon": v["icon"],
        "cashback": v["cashback"],
        "xp": xp,
        "next_xp": next_xp,
    }

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
    })

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

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db()
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
    conn.commit()
    c.close()
    conn.close()
    print("✅ БД инициализирована")

def get_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row

def get_user_id_by_username(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else None

def ensure_user(user_id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = %s",
              (user_id, username, username))
    conn.commit()
    c.close()
    conn.close()

def get_xp(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0

def add_xp(user_id, amount):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET xp = xp + %s WHERE user_id = %s", (amount, user_id))
    c.execute("SELECT xp FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    new_xp = row[0] if row else 0
    new_level = get_vip_level(new_xp)
    c.execute("UPDATE users SET vip_level = %s WHERE user_id = %s", (new_level, user_id))
    conn.commit()
    c.close()
    conn.close()
    return new_xp, new_level

def update_quest(user_id, quest_key, amount=1):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, progress, target, completed FROM quests WHERE user_id = %s AND quest_key = %s", (user_id, quest_key))
    row = c.fetchone()
    if not row:
        target = next((q["target"] for q in QUESTS if q["key"] == quest_key), 1)
        c.execute("INSERT INTO quests (user_id, quest_key, progress, target) VALUES (%s, %s, %s, %s)",
                  (user_id, quest_key, amount, target))
    else:
        qid, progress, target, completed = row
        if completed:
            c.close()
            conn.close()
            return
        new_progress = progress + amount
        c.execute("UPDATE quests SET progress = %s WHERE id = %s", (new_progress, qid))
        if new_progress >= target:
            c.execute("UPDATE quests SET completed = TRUE WHERE id = %s", (qid,))
    conn.commit()
    c.close()
    conn.close()

def get_user_quests(user_id):
    conn = get_db()
    c = conn.cursor()
    result = []
    for q in QUESTS:
        c.execute("SELECT progress, target, completed, claimed FROM quests WHERE user_id = %s AND quest_key = %s", (user_id, q["key"]))
        row = c.fetchone()
        if row:
            progress, target, completed, claimed = row
        else:
            progress, target, completed, claimed = 0, q["target"], False, False
        result.append({
            "key": q["key"],
            "name": q["name"],
            "reward": q["reward"],
            "progress": progress,
            "target": target,
            "completed": completed,
            "claimed": claimed,
        })
    c.close()
    conn.close()
    return result

def claim_quest(user_id, quest_key):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, target, completed, claimed FROM quests WHERE user_id = %s AND quest_key = %s", (user_id, quest_key))
    row = c.fetchone()
    if not row:
        c.close()
        conn.close()
        return None
    qid, target, completed, claimed = row
    if not completed or claimed:
        c.close()
        conn.close()
        return None
    reward = next((q["reward"] for q in QUESTS if q["key"] == quest_key), 0)
    set_balance(user_id, reward)
    c.execute("UPDATE quests SET claimed = TRUE WHERE id = %s", (qid,))
    conn.commit()
    c.close()
    conn.close()
    return reward
    
def unlock_achievement(user_id, key):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM achievements WHERE user_id = %s AND achievement_key = %s AND unlocked = TRUE", (user_id, key))
    row = c.fetchone()
    if row:
        c.close()
        conn.close()
        return False
    c.execute("INSERT INTO achievements (user_id, achievement_key, unlocked) VALUES (%s, %s, TRUE) ON CONFLICT (user_id, achievement_key) DO UPDATE SET unlocked = TRUE", (user_id, key))
    conn.commit()
    c.close()
    conn.close()
    return True

def is_banned(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else False

def set_banned(user_id, banned=True):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, banned) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET banned = %s",
              (user_id, banned, banned))
    conn.commit()
    c.close()
    conn.close()

def is_unlimited(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT unlimited FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else False

def set_unlimited(user_id, unlimited=True):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, unlimited) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET unlimited = %s",
              (user_id, unlimited, unlimited))
    conn.commit()
    c.close()
    conn.close()

def set_balance(user_id, amount):
    amount = clamp(amount)
    if is_unlimited(user_id) and amount < 0:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        return row[0] if row else 0
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, 1000) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0

def set_balance_exact(user_id, amount):
    amount = clamp(amount)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET balance = %s",
              (user_id, amount, amount))
    conn.commit()
    c.close()
    conn.close()
    return amount

def get_balance(user_id):
    user = get_user(user_id)
    return user[1] if user else 1000

def set_bank(user_id, amount):
    amount = clamp(amount)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, bank) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else 0

def get_bank(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT bank FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row and row[0] else 0

def get_top(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp FROM users ORDER BY balance DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def get_all_user_ids():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned = FALSE")
    rows = c.fetchall()
    c.close()
    conn.close()
    return [r[0] for r in rows]

def log_game(user_id, username, game, bet, win, detail):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO game_log (user_id, username, game, bet, win, detail, time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
              (user_id, username, game, clamp(bet), clamp(win), detail, datetime.now().strftime("%H:%M:%S")))
    conn.commit()
    c.close()
    conn.close()

def get_last_roulette_results(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT detail FROM game_log WHERE game='рулетка' ORDER BY id DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def get_big_wins(limit=10, min_win=100000):
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT username, game, win, time FROM game_log
                 WHERE win >= %s ORDER BY win DESC LIMIT %s""", (min_win, limit))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def get_recent_users(minutes=5, limit=20):
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT u.user_id, u.username, u.balance, MAX(g.id) as last_id
                 FROM users u
                 JOIN game_log g ON u.user_id = g.user_id
                 GROUP BY u.user_id, u.username, u.balance
                 ORDER BY last_id DESC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def get_user_logs(user_id, limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT game, bet, win, detail, time FROM game_log
                 WHERE user_id = %s ORDER BY id DESC LIMIT %s""", (user_id, limit))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def reset_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""UPDATE users SET balance = 1000, bank = 0, xp = 0, vip_level = 0,
                 total_lost = 0, total_won = 0 WHERE user_id = %s""", (user_id,))
    c.execute("DELETE FROM quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM achievements WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM game_log WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    conn.close()

def set_vip_level(user_id, level):
    conn = get_db()
    c = conn.cursor()
    xp_needed = VIP_LEVELS[level]["xp"] if 0 <= level < len(VIP_LEVELS) else 0
    c.execute("UPDATE users SET xp = %s, vip_level = %s WHERE user_id = %s", (xp_needed, level, user_id))
    conn.commit()
    c.close()
    conn.close()

def add_title(user_id, title, granted_by):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO titles (user_id, title, granted_by) VALUES (%s, %s, %s)", (user_id, title, granted_by))
    conn.commit()
    c.close()
    conn.close()

def get_user_titles(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title FROM titles WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return [r[0] for r in rows]

def get_main_title(user_id):
    titles = get_user_titles(user_id)
    return titles[0] if titles else ""

def clear_user_titles(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    conn.close()

def get_disabled_games():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'disabled_games'")
    row = c.fetchone()
    c.close()
    conn.close()
    if row and row[0]:
        return set(row[0].split(',')) if row[0] else set()
    return set()

def save_disabled_games():
    conn = get_db()
    c = conn.cursor()
    value = ','.join(disabled_games)
    c.execute("""INSERT INTO settings (key, value) VALUES ('disabled_games', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    conn.close()

def load_settings():
    global disabled_games
    disabled_games = get_disabled_games()
    print(f"✅ Загружены настройки: disabled_games = {disabled_games}")

def is_game_disabled(game):
    return game in disabled_games

def create_giveaway(amount, minutes, creator_id):
    conn = get_db()
    c = conn.cursor()
    ends_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    c.execute("""INSERT INTO giveaways (amount, ends_at, created_by, status)
                 VALUES (%s, %s, %s, 'active') RETURNING id""", (amount, ends_at, creator_id))
    gid = c.fetchone()[0]
    conn.commit()
    c.close()
    conn.close()
    return gid, ends_at

def finish_giveaway(gid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT amount, status FROM giveaways WHERE id = %s", (gid,))
    row = c.fetchone()
    if not row or row[1] != 'active':
        c.close()
        conn.close()
        return None
    amount = row[0]
    users = get_all_user_ids()
    if not users:
        c.execute("UPDATE giveaways SET status = 'no_winner' WHERE id = %s", (gid,))
        conn.commit()
        c.close()
        conn.close()
        return None
    winner_id = random.choice(users)
    set_balance(winner_id, amount)
    c.execute("UPDATE giveaways SET status = 'finished', winner_id = %s WHERE id = %s", (winner_id, gid))
    conn.commit()
    c.close()
    conn.close()
    return winner_id, amount
    
def hand_score(cards):
    score = 0
    aces = 0
    for c in cards:
        val = c[:-1]
        if val == 'A':
            score += 11
            aces += 1
        elif val in ['K','Q','J','10']:
            score += 10
        else:
            score += int(val)
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

def create_deck():
    suits = ['♠','♥','♦','♣']
    values = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    deck = [v+s for s in suits for v in values]
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
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        t = message.reply_to_message.from_user
        return t.id, (t.username or t.first_name)
    return None, None

def private_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Открыть Casino", web_app={"url": MINI_APP_URL})],
        [InlineKeyboardButton(text="🏆 Топ игроков", callback_data="menu_top")]
    ])

def group_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="menu_balance")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu_bank"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="menu_top")],
        [InlineKeyboardButton(text="📜 Лог", callback_data="menu_log")]
    ])

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
        [InlineKeyboardButton(text="🟢 Лёгкий  (3 💣)", callback_data=f"mines_start_easy_{bet}")],
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
        rows.append([InlineKeyboardButton(text=f"💰 Забрать ×{mult:.2f} ({cashout:,})".replace(',', ' '), callback_data="mines_cashout")])
    else:
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mines_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def mines_field_text(user_id):
    game = mines_games[user_id]
    level = MINES_LEVELS[game["level"]]
    opened_count = len(game["opened"])
    mult = game["mult"]
    cashout = int(game["bet"] * mult)
    safe_total = 25 - level["mines"]
    return (
        f"💣 <b>МИНЫ — {level['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{game['bet']:,}</b>\n"
        f"💎 Множитель: <b>×{mult:.2f}</b>\n"
        f"🎁 Забрать: <b>{cashout:,}</b>\n"
        f"🔥 Открыто: <b>{opened_count}</b> / {safe_total}\n"
        f"💣 Мин: <b>{level['mines']}</b>"
    ).replace(',', ' ')

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎰 Event ×2", callback_data="admin_event"),
         InlineKeyboardButton(text="🛠️ Тех.работы", callback_data="admin_maintenance")],
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="admin_bonus"),
         InlineKeyboardButton(text="💎 Джекпот", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_users"),
         InlineKeyboardButton(text="🚫 Ban/Unban", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🎮 Управление играми", callback_data="admin_games"),
         InlineKeyboardButton(text="🎁 Розыгрыш", callback_data="admin_giveaway")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="admin_vip"),
         InlineKeyboardButton(text="📊 Active", callback_data="admin_active")],
        [InlineKeyboardButton(text="🎮 Mini App", web_app={"url": MINI_APP_URL})],
        [InlineKeyboardButton(text="📋 Все команды", callback_data="admin_all_cmds")]
    ])

def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)

    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return

    is_private = message.chat.type == 'private'

    if is_private and user_id == ADMIN_ID:
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        txt = (
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>{username}</b> (ID: <code>{user_id}</code>)\n"
            f"💎 Баланс: <b>{balance:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n\n"
            f"📋 <b>УПРАВЛЕНИЕ БОТОМ</b>\n\n"
            f"Нажми на кнопку — покажу команду 👇"
        ).replace(',', ' ')
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT got_start_bonus FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    got_bonus = row[0] if row and row[0] else False
    c.close()
    conn.close()

    bonus_text = ""
    if not got_bonus:
        set_balance(user_id, 5000)
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET got_start_bonus = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        c.close()
        conn.close()
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
            f"🎰 <b>ДОБРО ПОЖАЛОВАТЬ В ТОКЕНЫ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"{vip_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{bank:,}</b>{bonus_text}\n\n"
            f"🎮 <b>КАК ИГРАТЬ:</b>\n"
            f"1. Жми <b>«ИГРАТЬ»</b>\n"
            f"2. Выбирай игру\n"
            f"3. Делай ставки\n"
            f"4. Выигрывай токены!"
        ).replace(',', ' ')
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎰 ИГРАТЬ", callback_data="menu_games"),
             InlineKeyboardButton(text="🎁 БОНУС", callback_data="menu_daily")],
            [InlineKeyboardButton(text="👤 ПРОФИЛЬ", callback_data="menu_profile"),
             InlineKeyboardButton(text="🎯 КВЕСТЫ", callback_data="menu_quests")],
            [InlineKeyboardButton(text="🏆 ТОП", callback_data="menu_top"),
             InlineKeyboardButton(text="💎 MINI APP", web_app={"url": MINI_APP_URL})]
        ])
        await message.answer(txt, parse_mode="HTML", reply_markup=kb)
    else:
        txt = (
            f"🎰 <b>ТОКЕНЫ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
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

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    txt = (
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{username}</b> (ID: <code>{user_id}</code>)\n"
        f"💎 Баланс: <b>{balance:,}</b>\n"
        f"🏦 Банк: <b>{bank:,}</b>\n\n"
        f"📋 <b>УПРАВЛЕНИЕ БОТОМ</b>\n\n"
        f"Нажми на кнопку — покажу команду 👇"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    vip = get_vip_info(xp)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (user_id,))
    total_games = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (user_id,))
    total_wins = c.fetchone()[0]
    c.close()
    conn.close()
    winrate = round(total_wins / total_games * 100) if total_games > 0 else 0
    if vip["next_xp"] > vip["xp"]:
        progress = vip["xp"] - VIP_LEVELS[vip["level"]]["xp"]
        total = vip["next_xp"] - VIP_LEVELS[vip["level"]]["xp"]
        bar = "▓" * int(progress / total * 10) + "░" * (10 - int(progress / total * 10))
        xp_line = f"📊 <b>{progress}/{total}</b> XP\n{bar}"
    else:
        xp_line = "🏆 <b>МАКСИМАЛЬНЫЙ УРОВЕНЬ</b>"
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""
    txt = (
        f"👤 <b>ПРОФИЛЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎭 <b>{username}</b>{title_line}\n"
        f"{vip['icon']} <b>{vip['name']}</b>\n"
        f"{xp_line}\n\n"
        f"💎 Баланс: <b>{balance:,}</b>\n"
        f"🏦 Банк: <b>{bank:,}</b>\n"
        f"💰 Кешбэк: <b>{vip['cashback']}%</b>\n\n"
        f"🎮 Игр: <b>{total_games}</b>\n"
        f"🏆 Побед: <b>{total_wins}</b>\n"
        f"📈 Винрейт: <b>{winrate}%</b>"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("quests"))
async def cmd_quests(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    quests = get_user_quests(user_id)
    txt = "🎯 <b>КВЕСТЫ</b>\n━━━━━━━━━━━━━━━━━━\n"
    txt += "Выполняй задания → получай награды!\n\n"
    for q in quests:
        if q["claimed"]:
            txt += f"✔️ {q['name']}\n"
        elif q["completed"]:
            txt += f"✅ {q['name']} → жми Забрать!\n"
        else:
            txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
    await message.answer(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))
    
@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await message.answer("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    if is_unlimited(user_id):
        await message.answer(f"💰 <b>Баланс</b>\n\n👤 {username}\n♾️ <b>У тебя БЕЗЛИМИТ</b>\n🏦 В банке: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")
    else:
        await message.answer(f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 Баланс: <b>{balance:,}</b>\n🏦 В банке: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = get_top(10)
    if not rows:
        await message.answer("📊 <b>Пока нет игроков!</b>", parse_mode="HTML")
        return
    txt = "🏆 <b>ТОП-10</b>\n━━━━━━━━━━━━━━━━━━\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        uid, uname, bal, xp = row
        medal = medals[i] if i < 3 else f"{i+1}."
        vip = get_vip_info(xp or 0)
        icon = vip["icon"] if xp else ""
        title = get_main_title(uid)
        t = f" 🏷️{title}" if title else ""
        txt += f"{medal} {icon} {uname}{t} — <b>{bal:,}</b>\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 2 and args[1].lower() in ['unlimited', 'безлимит', '∞']:
        set_unlimited(message.from_user.id, True)
        await message.answer(f"♾️ <b>БЕЗЛИМИТ АКТИВИРОВАН!</b>\n\n❌ Снять: <code>/give all</code>", parse_mode="HTML")
        return
    if len(args) >= 2 and args[1].lower() in ['all', 'off', 'выкл']:
        set_unlimited(message.from_user.id, False)
        await message.answer(f"✅ <b>БЕЗЛИМИТ ОТКЛЮЧЁН</b>", parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, amount)
        await message.answer(f"✅ <b>+{amount:,}</b> → @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, amount)
    await message.answer(f"✅ <b>+{amount:,}</b> → {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("take"))
async def cmd_take(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) >= 2 and args[1].lower() == 'all':
        if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
            await message.answer("❌ Ответь на сообщение игрока", parse_mode="HTML")
            return
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        tb = get_balance(target.id)
        if tb <= 0:
            await message.answer(f"❌ Нет фишек!", parse_mode="HTML")
            return
        set_balance(target.id, -tb)
        await message.answer(f"✅ <b>Забрано всё!</b>\n💸 -{tb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if len(args) >= 3 and args[1].startswith('@'):
        username = args[1][1:]
        try:
            amount = int(args[2])
        except:
            return
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, -amount)
        await message.answer(f"✅ <b>-{amount:,}</b> ← @{username}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return
    if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
        return
    if len(args) < 2:
        return
    try:
        amount = int(args[1])
    except:
        return
    target = message.reply_to_message.from_user
    ensure_user(target.id, target.username or target.first_name)
    nb = set_balance(target.id, -amount)
    await message.answer(f"✅ <b>-{amount:,}</b> ← {target.username or target.first_name}\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
    elif len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        uid = get_user_id_by_username(username)
        if uid:
            set_banned(uid, True)
            await message.answer(f"🚫 <b>Игрок @{username} забанен!</b>", parse_mode="HTML")
        else:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    if not target:
        await message.answer("❌ Ответь или <code>/ban @username</code>", parse_mode="HTML")
        return
    ensure_user(target.id, target.username or target.first_name)
    set_banned(target.id, True)
    await message.answer(f"🚫 <b>{target.username or target.first_name} забанен!</b>", parse_mode="HTML")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    target = None
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
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
    sent = 0
    failed = 0
    for uid in uids:
        try:
            await bot.send_message(uid, f"📢 <b>РАССЫЛКА</b>\n━━━━━━━━━━━━━━━━━━\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed += 1
    await message.answer(f"📢 <b>Готово</b>\n✅ {sent} | ❌ {failed}", parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    conn = get_db()
    c = conn.cursor()
    if len(args) >= 2 and args[1].startswith('@'):
        username = args[1][1:]
        c.execute("SELECT user_id, username, balance, bank, xp FROM users WHERE username = %s", (username,))
        row = c.fetchone()
        if not row:
            c.close()
            conn.close()
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        uid, uname, bal, bank, xp = row
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (uid,))
        total_games = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (uid,))
        total_wins = c.fetchone()[0]
        c.close()
        conn.close()
        vip = get_vip_info(xp or 0)
        txt = (
            f"📊 <b>СТАТИСТИКА ИГРОКА</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 {uname} (<code>{uid}</code>)\n"
            f"{vip['icon']} {vip['name']} | XP: {xp}\n"
            f"💎 Баланс: <b>{bal:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n\n"
            f"🎮 Игр: <b>{total_games}</b>\n"
            f"🏆 Побед: <b>{total_wins}</b>"
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
    conn.close()
    txt = (
        f"📊 <b>СТАТИСТИКА БОТА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <b>{total_users}</b>\n"
        f"💎 Токенов: <b>{total_balance:,}</b>\n"
        f"🎮 Игр: <b>{total_games}</b>\n\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"♾️ Безлимитов: <b>{unlimited_count}</b>"
    ).replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("event"))
async def cmd_event(message: Message):
    global event_double
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
        await message.answer(f"🎰 <b>ИВЕНТ ×2</b>\nСтатус: <b>{status}</b>\n\n<code>/event double on/off</code>", parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "double":
        if len(args) >= 3:
            mode = args[2].lower()
            if mode == "on":
                event_double = True
                await message.answer(f"🎰 <b>ИВЕНТ ×2 ВКЛЮЧЁН!</b>", parse_mode="HTML")
            elif mode == "off":
                event_double = False
                await message.answer(f"🎰 <b>ИВЕНТ ×2 ВЫКЛЮЧЕН</b>", parse_mode="HTML")
            return
    if sub == "status":
        status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
        await message.answer(f"🎰 Статус: <b>{status}</b>", parse_mode="HTML")
        
@dp.message(Command("maintenance"))
async def cmd_maintenance(message: Message):
    global maintenance_on
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
        await message.answer(f"🛠️ <b>ТЕХ.РАБОТЫ</b>\nСтатус: <b>{status}</b>\n\n<code>/maintenance on/off</code>", parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "on":
        maintenance_on = True
        await message.answer(f"🛠️ <b>ТЕХ.РАБОТЫ ВКЛЮЧЕНЫ</b>", parse_mode="HTML")
    elif sub == "off":
        maintenance_on = False
        await message.answer(f"✅ <b>ТЕХ.РАБОТЫ ВЫКЛЮЧЕНЫ</b>", parse_mode="HTML")
    elif sub == "status":
        status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
        await message.answer(f"🛠️ Статус: <b>{status}</b>", parse_mode="HTML")

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("🎁 <code>/bonus @user 50000</code> | <code>/bonus all 10000</code>", parse_mode="HTML")
        return
    target = args[1]
    try:
        amount = int(args[2])
    except:
        await message.answer("❌ Неверная сумма", parse_mode="HTML")
        return
    if target.lower() == 'all':
        uids = get_all_user_ids()
        count = 0
        for uid in uids:
            try:
                set_balance(uid, amount)
                count += 1
            except:
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
        except:
            return
        jackpot_amount = clamp(amount)
        await message.answer(f"💎 <b>Установлен</b>: {jackpot_amount:,}".replace(',', ' '), parse_mode="HTML")
    elif sub == "reset":
        jackpot_amount = 10000
        await message.answer(f"💎 <b>Сброшен</b>: 10 000", parse_mode="HTML")
    elif sub == "status":
        await message.answer(f"💎 <b>Текущий</b>: {jackpot_amount:,}".replace(',', ' '), parse_mode="HTML")

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
    except:
        return
    uid = get_user_id_by_username(username)
    if not uid:
        await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET xp = %s, vip_level = %s WHERE user_id = %s", (amount, get_vip_level(amount), uid))
    conn.commit()
    c.close()
    conn.close()
    await message.answer(f"✅ @{username} XP = <b>{amount}</b>".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("bigwins"))
async def cmd_bigwins(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    wins = get_big_wins(limit=10, min_win=100000)
    if not wins:
        await message.answer("📊 Крупных выигрышей пока нет (мин. 100K)", parse_mode="HTML")
        return
    txt = "🏆 <b>ТОП-10 КРУПНЫХ ВЫИГРЫШЕЙ</b>\n━━━━━━━━━━━━━━━━━━\n"
    for i, (uname, game, win, time) in enumerate(wins, 1):
        txt += f"{i}. <b>{uname}</b> — {game} +{win:,} ({time})\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("setbal"))
async def cmd_setbal(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 and not message.reply_to_message:
        await message.answer("❌ <code>/setbal @user 1000</code>\nили реплаем: <code>/setbal 1000</code>", parse_mode="HTML")
        return
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        try:
            amount = int(args[1])
        except:
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
    except:
        await message.answer("❌ Неверная сумма", parse_mode="HTML")
        return
    set_balance_exact(uid, amount)
    await message.answer(f"✅ <b>@{uname}</b>: баланс = <b>{amount:,}</b>".replace(',', ' '), parse_mode="HTML")

@dp.message(Command("resetuser"))
async def cmd_resetuser(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message:
        await message.answer("❌ <code>/resetuser @user</code>\nили реплаем", parse_mode="HTML")
        return
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
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

@dp.message(Command("logs"))
async def cmd_logs(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 and not message.reply_to_message:
        await message.answer("❌ <code>/logs @user</code>\nили реплаем", parse_mode="HTML")
        return
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
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
    txt = f"📜 <b>Последние 10 игр @{uname}</b>\n━━━━━━━━━━━━━━━━━━\n"
    for i, (game, bet, win, detail, time) in enumerate(logs, 1):
        profit = win - bet
        emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
        txt += f"{i}. {emoji} <b>{game}</b> | 💰 {bet:,} → {win:,} ({profit:+,}) | {detail} | {time}\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")
    
@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 and not message.reply_to_message:
        await message.answer("❌ <code>/vip @user 3</code>\nили реплаем: <code>/vip 3</code>", parse_mode="HTML")
        return
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        try:
            level = int(args[1])
        except:
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
    except:
        await message.answer("❌ Уровень 0-4", parse_mode="HTML")
        return
    if not 0 <= level <= 4:
        await message.answer("❌ Уровень 0-4", parse_mode="HTML")
        return
    set_vip_level(uid, level)
    v = VIP_LEVELS[level]
    await message.answer(f"✅ <b>@{uname}</b> → {v['icon']} {v['name']}", parse_mode="HTML")

@dp.message(Command("title"))
async def cmd_title(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ <code>/title @user Легенда</code>\n<code>/title @user clear</code>", parse_mode="HTML")
        return
    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target = message.reply_to_message.from_user
        ensure_user(target.id, target.username or target.first_name)
        title_text = ' '.join(args[1:])
        if title_text.lower() == 'clear':
            clear_user_titles(target.id)
            await message.answer(f"✅ Титулы <b>{target.username or target.first_name}</b> очищены", parse_mode="HTML")
            return
        add_title(target.id, title_text, message.from_user.id)
        await message.answer(f"🏷️ <b>{target.username or target.first_name}</b> → <b>{title_text}</b>", parse_mode="HTML")
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
        await message.answer(f"✅ Титулы <b>@{uname}</b> очищены", parse_mode="HTML")
        return
    add_title(uid, title_text, message.from_user.id)
    await message.answer(f"🏷️ <b>@{uname}</b> → <b>{title_text}</b>", parse_mode="HTML")

@dp.message(Command("games"))
async def cmd_games(message: Message):
    global disabled_games
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        txt = "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for key, name in GAME_NAMES.items():
            status = "❌ ВЫКЛ" if key in disabled_games else "✅ ВКЛ"
            txt += f"{name} — {status}\n"
        txt += "\n📋 <code>/games on slots</code>\n<code>/games off slots</code>\n<code>/games on all</code>\n<code>/games off all</code>"
        await message.answer(txt, parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "list":
        txt = "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for key, name in GAME_NAMES.items():
            status = "❌ ВЫКЛ" if key in disabled_games else "✅ ВКЛ"
            txt += f"{name} — {status}\n"
        await message.answer(txt, parse_mode="HTML")
        return
    if len(args) < 3:
        await message.answer("❌ <code>/games on/off slots</code>", parse_mode="HTML")
        return
    action = sub
    game = args[2].lower()
    if action not in ["on", "off"]:
        await message.answer("❌ Действие: on / off", parse_mode="HTML")
        return
    if game == "all":
        if action == "off":
            disabled_games = set(GAME_NAMES.keys())
        else:
            disabled_games = set()
        save_disabled_games()
        await message.answer(f"✅ Все игры: <b>{'ВЫКЛ' if action == 'off' else 'ВКЛ'}</b>", parse_mode="HTML")
        return
    if game not in GAME_NAMES:
        await message.answer(f"❌ Игра не найдена. Доступно: {', '.join(GAME_NAMES.keys())}", parse_mode="HTML")
        return
    if action == "off":
        disabled_games.add(game)
        save_disabled_games()
        await message.answer(f"❌ <b>{GAME_NAMES[game]}</b> выключена", parse_mode="HTML")
    else:
        disabled_games.discard(game)
        save_disabled_games()
        await message.answer(f"✅ <b>{GAME_NAMES[game]}</b> включена", parse_mode="HTML")

@dp.message(Command("active"))
async def cmd_active(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_recent_users(minutes=5, limit=20)
    if not users:
        await message.answer("📊 За последние 5 минут никто не играл", parse_mode="HTML")
        return
    txt = "📊 <b>Активные за 5 минут</b>\n━━━━━━━━━━━━━━━━━━\n"
    for i, (uid, uname, bal) in enumerate(users, 1):
        txt += f"{i}. <b>{uname}</b> — 💎 {bal:,}\n".replace(',', ' ')
    await message.answer(txt, parse_mode="HTML")

@dp.message(Command("giveaway"))
async def cmd_giveaway(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        args = message.text.split()       
    if len(args) < 3:
        await message.answer(
            "📋 <b>РОЗЫГРЫШ</b>\n━━━━━━━━━━━━━━━━━━\n"
            "<code>/giveaway 10000 30m</code> — 30 минут\n"
            "<code>/giveaway 10000 1h</code> — 1 час\n"
            "<code>/giveaway 10000 24h</code> — 24 часа\n\n"
            "⏱️ Формат: <code>30m</code> / <code>1h</code> / <code>24h</code>",
            parse_mode="HTML"
        )
        return
        amount = int(args[1]) if args[1].isdigit() else 0
    if amount == 0:
        return
    minutes = 0
    time_str = args[2].lower()
    if time_str.endswith('h'):
        minutes = int(time_str[:-1]) * 60
    elif time_str.endswith('m'):
        minutes = int(time_str[:-1])
    else:
        minutes = 0
            if minutes == 0:
        return
    await message.answer(
        f"🎁 <b>РОЗЫГРЫШ ЗАПУЩЕН!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Приз: <b>{amount:,}</b>\n"
        f"⏱️ До: <b>{ends_at.strftime('%H:%M:%S')}</b>\n"
        f"👥 Все игроки участвуют\n\n"
        f"ID: <code>{gid}</code>".replace(',', ' '),
        parse_mode="HTML"
    )
    try:
        users = get_all_user_ids()
        count = 0
        for uid in users:
            try:
                await bot.send_message(
                    uid,
                    f"🎁 <b>РОЗЫГРЫШ!</b>\n💰 Приз: <b>{amount:,}</b>\n⏱️ До: <b>{(ends_at + timedelta(hours=3)).strftime('%H:%M')}</b>\n\n🏆 Победитель — случайный игрок!".replace(',', ' '),
                )
                count += 1
                await asyncio.sleep(0.05)
            except:
                pass
        await message.answer(f"✅ Уведомлено: {count} игроков", parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка рассылки: {e}")
        
# ========== КНОПКИ ==========
@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        await call.answer("🚫 ВЫ ЗАБЛОКИРОВАНЫ", show_alert=True)
        return
    if maintenance_on and user_id != ADMIN_ID:
        await call.answer("🛠️ Тех.работы. Попробуй позже!", show_alert=True)
        return

    if data.startswith("admin_"):
        if user_id != ADMIN_ID:
            await call.answer("❌ Только для админа", show_alert=True)
            return
        if data == "admin_back":
            balance = get_balance(user_id)
            bank = get_bank(user_id)
            txt = (
                f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>{username}</b> (ID: <code>{user_id}</code>)\n"
                f"💎 Баланс: <b>{balance:,}</b>\n"
                f"🏦 Банк: <b>{bank:,}</b>\n\n"
                f"📋 <b>УПРАВЛЕНИЕ БОТОМ</b>\n\n"
                f"Нажми на кнопку — покажу команду 👇"
            ).replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
            await call.answer()
            return
        if data == "admin_broadcast":
            txt = f"📢 <b>РАССЫЛКА</b>\n━━━━━━━━━━━━━━━━━━\n<code>/broadcast Текст</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_stats":
            txt = f"📊 <b>СТАТИСТИКА</b>\n━━━━━━━━━━━━━━━━━━\n<code>/stats</code> | <code>/stats @user</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_event":
            status = "✅ ВКЛ" if event_double else "❌ ВЫКЛ"
            txt = f"🎰 <b>EVENT ×2</b>\n━━━━━━━━━━━━━━━━━━\nСтатус: <b>{status}</b>\n\n<code>/event double on/off</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_maintenance":
            status = "🛠️ ВКЛ" if maintenance_on else "✅ ВЫКЛ"
            txt = f"🛠️ <b>ТЕХ.РАБОТЫ</b>\n━━━━━━━━━━━━━━━━━━\nСтатус: <b>{status}</b>\n\n<code>/maintenance on/off</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_bonus":
            txt = f"🎁 <b>БОНУС</b>\n━━━━━━━━━━━━━━━━━━\n<code>/bonus @user 50000</code>\n<code>/bonus all 10000</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_jackpot":
            txt = f"💎 <b>ДЖЕКПОТ</b>\n━━━━━━━━━━━━━━━━━━\n💰 Текущий: <b>{jackpot_amount:,}</b>\n\n<code>/jackpot set 1000000</code>".replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_users":
            txt = f"👥 <b>ИГРОКИ</b>\n━━━━━━━━━━━━━━━━━━\n<code>/setbal @user 1000</code>\n<code>/resetuser @user</code>\n<code>/logs @user</code>\n<code>/vip @user 3</code>\n<code>/title @user Легенда</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_ban":
            txt = f"🚫 <b>BAN / UNBAN</b>\n━━━━━━━━━━━━━━━━━━\n<code>/ban @user</code>\n<code>/unban @user</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_games":
            txt = "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n━━━━━━━━━━━━━━━━━━\n"
            for key, name in GAME_NAMES.items():
                status = "❌ ВЫКЛ" if key in disabled_games else "✅ ВКЛ"
                txt += f"{name} — {status}\n"
            txt += "\n📋 <code>/games on/off slots</code>\n<code>/games list</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_giveaway":
            txt = f"🎁 <b>РОЗЫГРЫШ</b>\n━━━━━━━━━━━━━━━━━━\n<code>/giveaway 10000 30m</code>\n<code>/giveaway 10000 1h</code>\n<code>/giveaway 10000 24h</code>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_vip":
            txt = f"👑 <b>VIP</b>\n━━━━━━━━━━━━━━━━━━\n<code>/vip @user 0-4</code>\n\n0 — 🥉 Бронза\n1 — 🥈 Серебро\n2 — 🥇 Золото\n3 — 💎 Платина\n4 — 👑 Алмаз"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_active":
            users = get_recent_users(minutes=5, limit=20)
            if not users:
                txt = "📊 За последние 5 минут никто не играл"
            else:
                txt = "📊 <b>Активные за 5 минут</b>\n━━━━━━━━━━━━━━━━━━\n"
                for i, (uid, uname, bal) in enumerate(users, 1):
                    txt += f"{i}. <b>{uname}</b> — 💎 {bal:,}\n".replace(',', ' ')
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        if data == "admin_all_cmds":
            txt = (
                f"📋 <b>ВСЕ КОМАНДЫ</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<b>💰 Экономика:</b>\n"
                f"<code>/setbal @user 1000</code>\n"
                f"<code>/resetuser @user</code>\n"
                f"<code>/give @user 1000</code>\n"
                f"<code>/take @user 1000</code>\n"
                f"<code>/bonus @user 50000</code>\n\n"
                f"<b>👥 Игроки:</b>\n"
                f"<code>/vip @user 3</code>\n"
                f"<code>/title @user Легенда</code>\n"
                f"<code>/ban @user</code>\n"
                f"<code>/unban @user</code>\n"
                f"<code>/set_xp @user 1000</code>\n\n"
                f"<b>📊 Мониторинг:</b>\n"
                f"<code>/logs @user</code>\n"
                f"<code>/active</code>\n"
                f"<code>/bigwins</code>\n"
                f"<code>/stats [@user]</code>\n\n"
                f"<b>🎮 Игры:</b>\n"
                f"<code>/games on/off slots</code>\n"
                f"<code>/event double on/off</code>\n"
                f"<code>/maintenance on/off</code>\n\n"
                f"<b>🎁 Фан:</b>\n"
                f"<code>/giveaway 10000 1h</code>\n"
                f"<code>/jackpot set/reset</code>\n"
                f"<code>/broadcast Текст</code>"
            )
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return
        await call.answer()
        return

    if data.startswith("quest_claim_"):
        quest_key = data.replace("quest_claim_", "")
        reward = claim_quest(user_id, quest_key)
        if reward:
            new_balance = get_balance(user_id)
            await call.answer(f"✅ +{reward:,} токенов!".replace(',', ' '), show_alert=True)
            await call.message.edit_text(
                f"🎯 <b>КВЕСТ ВЫПОЛНЕН!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 Награда: <b>+{reward:,}</b>\n"
                f"💎 Баланс: <b>{new_balance:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=quests_kb(user_id)
            )
        else:
            await call.answer("❌ Уже получено", show_alert=True)
        return

    if data == "quest_noop":
        await call.answer()
        return

    balance = get_balance(user_id)
    bank = get_bank(user_id)
    
    if data == "menu_main":
        if is_unlimited(user_id):
            bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
        else:
            bal_line = f"💎 <b>{balance:,}</b>".replace(',', ' ')
        txt = f"🎰 <b>ТОКЕНЫ</b>\n━━━━━━━━━━━━━━━━━━\n👤 {username}\n{bal_line}\n🏦 <b>{bank:,}</b>".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_games":
        txt = "🎮 <b>ИГРЫ</b>\n━━━━━━━━━━━━━━━━━━\nВыбери игру:"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=games_kb())

    elif data == "menu_profile":
        xp = get_xp(user_id)
        vip = get_vip_info(xp)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (user_id,))
        total_games = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (user_id,))
        total_wins = c.fetchone()[0]
        c.close()
        conn.close()
        winrate = round(total_wins / total_games * 100) if total_games > 0 else 0
        title = get_main_title(user_id)
        title_line = f"\n🏷️ <b>{title}</b>" if title else ""
        txt = (
            f"👤 <b>ПРОФИЛЬ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎭 <b>{username}</b>{title_line}\n"
            f"{vip['icon']} <b>{vip['name']}</b>\n\n"
            f"💎 Баланс: <b>{balance:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n"
            f"💰 Кешбэк: <b>{vip['cashback']}%</b>\n\n"
            f"🎮 Игр: <b>{total_games}</b>\n"
            f"🏆 Побед: <b>{total_wins}</b>\n"
            f"📈 Винрейт: <b>{winrate}%</b>"
        ).replace(',', ' ')
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)

    elif data == "menu_quests":
        quests = get_user_quests(user_id)
        txt = "🎯 <b>КВЕСТЫ</b>\n━━━━━━━━━━━━━━━━━━\nВыполняй задания → получай награды!\n\n"
        for q in quests:
            if q["claimed"]:
                txt += f"✔️ {q['name']}\n"
            elif q["completed"]:
                txt += f"✅ {q['name']} → Забрать!\n"
            else:
                txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))

    elif data == "menu_daily":
        await call.answer("🎁 Ежедневный бонус — скоро! 🚀", show_alert=True)

    elif data == "menu_balance":
        if is_unlimited(user_id):
            await call.answer(f"♾️ БЕЗЛИМИТ\n🏦 {bank:,}".replace(',', ' '), show_alert=True)
        else:
            await call.answer(f"💎 {balance:,}\n🏦 {bank:,}".replace(',', ' '), show_alert=True)

    elif data == "menu_bank":
        txt = (
            f"🏦 <b>БАНК</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 {username}\n"
            f"💎 Баланс: <b>{balance:,}</b>\n"
            f"🏦 В банке: <b>{bank:,}</b>\n\n"
            f"<code>банк положить 1000</code>\n"
            f"<code>банк снять 1000</code>".replace(',', ' ')
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_top":
        rows = get_top(10)
        txt = "🏆 <b>ТОП-10</b>\n━━━━━━━━━━━━━━━━━━\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = medals[i] if i < 3 else f"{i+1}."
            vip = get_vip_info(xp or 0)
            icon = vip["icon"] if xp else ""
            title = get_main_title(uid)
            t = f" 🏷️{title}" if title else ""
            txt += f"{medal} {icon} {uname}{t} — <b>{bal:,}</b>\n".replace(',', ' ')
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "menu_log":
        rows = get_last_roulette_results(10)
        if not rows:
            txt = "📜 Пока пусто..."
        else:
            txt = "📜 <b>Результаты:</b>\n━━━━━━━━━━━━━━━━━━\n"
            for i, (detail,) in enumerate(rows, 1):
                parts_d = detail.split()
                if len(parts_d) >= 2:
                    txt += f"{i}. {parts_d[1]} {parts_d[0]}\n"
                else:
                    txt += f"{i}. {detail}\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=group_kb())

    elif data == "info_roulette":
        txt = f"🎡 <b>РУЛЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n<code>к 1000</code> — красное (×2)\n<code>ч 1000</code> — чёрное (×2)\n<code>з 1000</code> — зеро (×36)\n<code>1000 5</code> — число\n\n<code>го</code> — запуск"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_slots":
        txt = f"🎰 <b>СЛОТЫ</b>\n━━━━━━━━━━━━━━━━━━\n<code>спин 1000</code>\n\n🍒×10 | 🍋×15 | 🍊×20 | 🍇×25 | 💎×50 | 7️⃣×100"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_coin":
        txt = f"🪙 <b>МОНЕТКА</b>\n━━━━━━━━━━━━━━━━━━\n<code>орёл 1000</code> / <code>решка 1000</code>\n\n×2"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_bj":
        txt = f"🃏 <b>БЛЭКДЖЕК</b>\n━━━━━━━━━━━━━━━━━━\n<code>бж 1000</code>\n\n➕ Взять | ✋ Хватит\n×2"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_mines":
        txt = f"💣 <b>МИНЫ</b>\n━━━━━━━━━━━━━━━━━━\n<code>мины 1000</code>\n\n🟢 3 | 🟡 5 | 🔴 10"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data == "info_duel":
        txt = f"⚔️ <b>ДУЭЛЬ</b>\n━━━━━━━━━━━━━━━━━━\n<code>дуэль 1000 @user</code>\n→ <code>принять</code>"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=back_to_games_kb())

    elif data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        bet = balance if val == "max" else int(val)
        await call.message.edit_reply_markup(reply_markup=roulette_kb(bet))
        await call.answer(f"💎 Ставка: {bet:,}".replace(',', ' '))

    elif data.startswith("mines_start_"):
        parts = data.split("_")
        level = parts[2]
        bet = int(parts[3])
        if level not in MINES_LEVELS:
            await call.answer("❌ Уровень не найден", show_alert=True)
            return
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌ Ставка неверна", show_alert=True)
            return
        if balance < bet and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно!", show_alert=True)
            return
        set_balance(user_id, -bet)
        positions = list(range(25))
        random.shuffle(positions)
        mines_positions = set(positions[:MINES_LEVELS[level]["mines"]])
        mines_games[user_id] = {
            "bet": bet,
            "level": level,
            "mines_positions": mines_positions,
            "opened": set(),
            "mult": 1.0,
        }
        add_xp(user_id, 2)
        update_quest(user_id, "bets_20")
        await call.message.edit_text(mines_field_text(user_id), parse_mode="HTML", reply_markup=mines_field_kb(user_id))
        await call.answer("💣 Игра началась!")

    elif data.startswith("mines_open_"):
        if user_id not in mines_games:
            await call.answer("❌ Игра не найдена!", show_alert=True)
            return
        game = mines_games[user_id]
        idx = int(data.replace("mines_open_", ""))
        if idx in game["opened"]:
            await call.answer("❌ Уже открыто!", show_alert=True)
            return
        await call.message.edit_text("⏳ <b>Открываем...</b>", parse_mode="HTML")
        await asyncio.sleep(0.4)
        if idx in game["mines_positions"]:
            game["opened"].add(idx)
            await call.message.edit_text(f"💥 <b>БУМ!</b>", parse_mode="HTML")
            await asyncio.sleep(0.5)
            await call.message.edit_text(
                f"💥 <b>БУМ! Мина!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"😢 Проиграл <b>{game['bet']:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=mines_field_kb(user_id)
            )
            log_game(user_id, username, "мины", game["bet"], 0, f"{game['level']} бум")
            xp = get_xp(user_id)
            vip = get_vip_info(xp)
            cashback = int(game["bet"] * vip["cashback"] / 100)
            if cashback > 0 and not is_unlimited(user_id):
                set_balance(user_id, cashback)
            del mines_games[user_id]
            await call.answer()
            return
        game["opened"].add(idx)
        game["mult"] = round(1 + len(game["opened"]) * MINES_LEVELS[game["level"]]["step"], 2)
        safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]
        if len(game["opened"]) == safe_total:
            wa = clamp(int(game["bet"] * game["mult"] * get_event_mult()))
            set_balance(user_id, wa)
            log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} all")
            unlock_achievement(user_id, "mines_all")
            update_quest(user_id, "win_100k", wa)
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🏆 <b>ПОЛЕ ОЧИЩЕНО!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 Множитель: <b>×{game['mult']:.2f}</b>\n"
                f"🎁 Выигрыш: <b>{wa:,}</b>\n"
                f"💎 Баланс: <b>{nb:,}</b>".replace(',', ' '),
                parse_mode="HTML",
                reply_markup=group_kb()
            )
            del mines_games[user_id]
            await call.answer("🎉 Победа!")
            return
        await call.message.edit_text(mines_field_text(user_id), parse_mode="HTML", reply_markup=mines_field_kb(user_id))
        await call.answer("💎 Открыто!")

    elif data == "mines_cashout":
        if user_id not in mines_games:
            await call.answer("❌ Игра не найдена!", show_alert=True)
            return
        game = mines_games[user_id]
        if not game["opened"]:
            await call.answer("❌ Открой хотя бы 1 клетку!", show_alert=True)
            return
        wa = clamp(int(game["bet"] * game["mult"] * get_event_mult()))
        set_balance(user_id, wa)
        nb = get_balance(user_id)
        log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} x{game['mult']}")
        update_quest(user_id, "win_100k", wa)
        await call.message.edit_text(
            f"💰 <b>ЗАБРАЛ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎁 Выигрыш: <b>{wa:,}</b>\n"
            f"💎 Баланс: <b>{nb:,}</b>".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=group_kb()
        )
        del mines_games[user_id]
        await call.answer("💰 Забрал!")

    elif data == "mines_cancel":
        if user_id in mines_games:
            game = mines_games[user_id]
            if not game["opened"]:
                set_balance(user_id, game["bet"])
                del mines_games[user_id]
                await call.message.edit_text(f"❌ <b>Игра отменена</b>", parse_mode="HTML", reply_markup=group_kb())
                await call.answer("Возвращено")
                return
        await call.answer("❌ Нельзя отменить")

    elif data == "mines_noop":
        await call.answer()
        
    elif data.startswith("bet_"):
        parts = data.split("_")
        bet_type = parts[1]
        bet = int(parts[2])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌ Ставка неверна", show_alert=True)
            return
        if balance < bet and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно!", show_alert=True)
            return
        set_balance(user_id, -bet)
        for frame in ANIM_ROULETTE:
            try:
                await call.message.edit_text(f"🎡 <b>Крутится...</b>\n\n{frame}", parse_mode="HTML")
            except Exception as e:
                print(f"Ошибка анимации: {e}")
            await asyncio.sleep(0.4)
        result = random.randint(0, 36)
        if result == 0:
            color = "🟢"
        elif result in RED_NUMBERS:
            color = "🔴"
        else:
            color = "⚫"
        win = False
        mult = 0
        if bet_type == "red" and result in RED_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "black" and result in BLACK_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "green" and result == 0:
            win = True
            mult = MULT_ZERO
        add_xp(user_id, 1)
        update_quest(user_id, "roulette_10")
        update_quest(user_id, "bets_20")
        if win:
            wa = clamp(int(bet * mult * get_event_mult()))
            nb = set_balance(user_id, wa)
            update_quest(user_id, "win_100k", wa)
            if result == 36:
                unlock_achievement(user_id, "lucky_36")
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n━━━━━━━━━━━━━━━━━━\n🎉 <b>ПОБЕДА!</b>\n💰 <b>+{wa:,}</b> (×{mult})\n\n💎 Баланс: <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
        else:
            nb = get_balance(user_id)
            xp = get_xp(user_id)
            vip = get_vip_info(xp)
            cashback = int(bet * vip["cashback"] / 100)
            if cashback > 0 and not is_unlimited(user_id):
                nb = set_balance(user_id, cashback)
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n━━━━━━━━━━━━━━━━━━\n😢 <b>Проигрыш</b>\n💸 -{bet:,}\n💰 Кешбэк: +{cashback:,}\n\n💎 Баланс: <b>{nb:,}</b>".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
        rkb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=rkb)

    elif data.startswith("group_bet_"):
        parts = data.split("_")
        bet_type = parts[2]
        bet = int(parts[3])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌ Ставка неверна", show_alert=True)
            return
        if balance < bet and not is_unlimited(user_id):
            await call.answer(f"❌ Недостаточно!", show_alert=True)
            return
        set_balance(user_id, -bet)
        for frame in ANIM_ROULETTE:
            try:
                await call.message.edit_text(f"🎡 <b>Крутится...</b>\n\n{frame}", parse_mode="HTML")
            except Exception as e:
                print(f"Ошибка анимации: {e}")
            await asyncio.sleep(0.4)
        result = random.randint(0, 36)
        if result == 0:
            color = "🟢"
        elif result in RED_NUMBERS:
            color = "🔴"
        else:
            color = "⚫"
        win = False
        mult = 0
        if bet_type == "red" and result in RED_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "black" and result in BLACK_NUMBERS:
            win = True
            mult = MULT_COLOR
        elif bet_type == "green" and result == 0:
            win = True
            mult = MULT_ZERO
        if win:
            wa = clamp(int(bet * mult * get_event_mult()))
            nb = set_balance(user_id, wa)
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n━━━━━━━━━━━━━━━━━━\n🎉 <b>ПОБЕДА!</b>\n💰 +{wa:,}\n💎 {nb:,}".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
        else:
            nb = get_balance(user_id)
            xp = get_xp(user_id)
            vip = get_vip_info(xp)
            cashback = int(bet * vip["cashback"] / 100)
            if cashback > 0 and not is_unlimited(user_id):
                nb = set_balance(user_id, cashback)
            txt = f"🎰 <b>Выпало: {color} {result}</b>\n━━━━━━━━━━━━━━━━━━\n😢 Проигрыш -{bet:,}\n💰 Кешбэк: +{cashback:,}\n💎 {nb:,}".replace(',', ' ')
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
        rkb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"group_bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"group_bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=rkb)

    elif data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n👤 Ты: {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 Дилер: {fmt_hand(game['dealer'])}\n\n💥 <b>ПЕРЕБОР!</b>\n💸 -{game['bet']:,}\n💎 {nb:,}".replace(',', ' '),
                parse_mode="HTML", reply_markup=group_kb()
            )
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} перебор")
            del bj_games[user_id]
        else:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n👤 Ты: {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 Дилер: {fmt_hand(game['dealer'], hide_second=True)}\n\n🎯 <b>Ещё карту?</b>",
                parse_mode="HTML", reply_markup=bj_kb()
            )

    elif data == "bj_stand":
        if user_id not in bj_games:
            await call.answer("❌ Игра не найдена!")
            return
        game = bj_games[user_id]
        while hand_score(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        d_score = hand_score(game["dealer"])
        add_xp(user_id, 2)
        update_quest(user_id, "bj_5")
        update_quest(user_id, "bets_20")
        if d_score > 21 or p_score > d_score:
            wa = clamp(game["bet"] * 2 * get_event_mult())
            nb = set_balance(user_id, wa)
            result_text = f"🎉 <b>ПОБЕДА!</b>\n💰 +{wa - game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], wa, f"{p_score} vs {d_score}")
        elif p_score == d_score:
            set_balance(user_id, game["bet"])
            nb = get_balance(user_id)
            result_text = "🤝 <b>Ничья</b>"
            log_game(user_id, username, "блэкджек", game["bet"], game["bet"], f"{p_score} vs {d_score}")
        else:
            nb = get_balance(user_id)
            result_text = f"😢 <b>Проигрыш</b>\n💸 -{game['bet']:,}"
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} vs {d_score}")
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n👤 Ты: {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 Дилер: {fmt_hand(game['dealer'])} = <b>{d_score}</b>\n\n{result_text}\n\n💎 {nb:,}".replace(',', ' '),
            parse_mode="HTML", reply_markup=group_kb()
        )
        del bj_games[user_id]

    await call.answer()
    
def parse_multi_bet(text):
    parts = text.split()
    if len(parts) < 2:
        return None, None
    try:
        bet = int(parts[0])
    except:
        return None, None
    ranges = []
    for p in parts[1:]:
        if '-' in p:
            try:
                a, b = p.split('-')
                a, b = int(a), int(b)
                if 0 <= a <= 36 and 0 <= b <= 36:
                    ranges.append((min(a,b), max(a,b)))
            except:
                pass
        elif p.isdigit():
            num = int(p)
            if 0 <= num <= 36:
                ranges.append((num, num))
    return bet, ranges

@dp.message()
async def text_handler(message: Message):
    if not message.text:
        return
    if message.from_user.is_bot:
        return
    if message.chat.type == 'private':
        return
    text = message.text.strip().lower()
    parts = text.split()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    ensure_user(user_id, username)

    if is_banned(user_id):
        await message.reply("🚫 <b>ВЫ ЗАБЛОКИРОВАНЫ</b>", parse_mode="HTML")
        return

    if maintenance_on and user_id != ADMIN_ID:
        await message.reply("🛠️ <b>ТЕХ.РАБОТЫ</b>\n\nПопробуй позже!", parse_mode="HTML")
        return

    if text in ['профиль', 'я']:
        xp = get_xp(user_id)
        vip = get_vip_info(xp)
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s", (user_id,))
        total_games = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM game_log WHERE user_id = %s AND win > 0", (user_id,))
        total_wins = c.fetchone()[0]
        c.close()
        conn.close()
        winrate = round(total_wins / total_games * 100) if total_games > 0 else 0
        title = get_main_title(user_id)
        title_line = f"\n🏷️ <b>{title}</b>" if title else ""
        txt = (
            f"👤 <b>ПРОФИЛЬ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎭 <b>{username}</b>{title_line}\n"
            f"{vip['icon']} <b>{vip['name']}</b>\n"
            f"📊 XP: <b>{xp}</b>\n\n"
            f"💎 Баланс: <b>{balance:,}</b>\n"
            f"🏦 Банк: <b>{bank:,}</b>\n"
            f"💰 Кешбэк: <b>{vip['cashback']}%</b>\n\n"
            f"🎮 Игр: <b>{total_games}</b>\n"
            f"🏆 Побед: <b>{total_wins}</b>\n"
            f"📈 Винрейт: <b>{winrate}%</b>"
        ).replace(',', ' ')
        await message.reply(txt, parse_mode="HTML")
        return

    if text in ['квесты', 'quests']:
        quests = get_user_quests(user_id)
        txt = "🎯 <b>КВЕСТЫ</b>\n━━━━━━━━━━━━━━━━━━\n"
        for q in quests:
            if q["claimed"]:
                txt += f"✔️ {q['name']}\n"
            elif q["completed"]:
                txt += f"✅ {q['name']} → Забрать!\n"
            else:
                txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
        await message.reply(txt, parse_mode="HTML", reply_markup=quests_kb(user_id))
        return

    if len(parts) >= 3 and parts[0] == 'дуэль':
        try:
            bet = int(parts[1])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        target_username = parts[2][1:] if parts[2].startswith('@') else None
        if not target_username:
            await message.reply("❌ <code>дуэль 1000 @username</code>", parse_mode="HTML")
            return
        opponent_id = get_user_id_by_username(target_username)
        if not opponent_id:
            await message.reply(f"❌ @{target_username} не найден!")
            return
        if opponent_id == user_id:
            await message.reply("❌ Нельзя себя!")
            return
        if chat_id in duel_games:
            await message.reply("❌ Уже есть дуэль!")
            return
        duel_games[chat_id] = {
            "challenger_id": user_id,
            "challenger_name": username,
            "challenger_bet": bet,
            "opponent_id": opponent_id,
            "opponent_name": target_username,
            "opponent_bet": bet,
            "active": False
        }
        await message.reply(
            f"⚔️ <b>ВЫЗОВ!</b>\n👤 {username} → @{target_username}\n💰 <b>{bet:,}</b>\n\n@{target_username}, напиши <code>принять</code>!".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    if text == 'принять':
        if chat_id not in duel_games or duel_games[chat_id].get("active"):
            return
        duel = duel_games[chat_id]
        if duel["opponent_id"] != user_id:
            return
        c_balance = get_balance(duel["challenger_id"])
        o_balance = get_balance(duel["opponent_id"])
        if c_balance < duel["challenger_bet"] and not is_unlimited(duel["challenger_id"]):
            await message.reply(f"❌ У {duel['challenger_name']} мало!")
            del duel_games[chat_id]
            return
        if o_balance < duel["opponent_bet"] and not is_unlimited(duel["opponent_id"]):
            await message.reply(f"❌ У тебя мало!")
            return
        set_balance(duel["challenger_id"], -duel["challenger_bet"])
        set_balance(duel["opponent_id"], -duel["opponent_bet"])
        duel["active"] = True
        total_bank = clamp(duel["challenger_bet"] + duel["opponent_bet"])
        msg = await message.reply(
            f"⚔️ <b>ДУЭЛЬ!</b>\n👤 {duel['challenger_name']} vs {duel['opponent_name']}\n💰 <b>{total_bank:,}</b>\n\n🎲 Крутится...".replace(',', ' '),
            parse_mode="HTML"
        )
        for i in range(5):
            frame = " ".join(ANIM_DUEL[:i+1])
            await asyncio.sleep(0.5)
            await msg.edit_text(f"⚔️ <b>ДУЭЛЬ</b>\n\n🎲 {frame}", parse_mode="HTML")
        winner_color = random.choice(['red', 'blue'])
        if winner_color == 'red':
            winner_id = duel["challenger_id"]
            winner_name = duel["challenger_name"]
            loser_name = duel["opponent_name"]
            color_emoji = "🔴"
        else:
            winner_id = duel["opponent_id"]
            winner_name = duel["opponent_name"]
            loser_name = duel["challenger_name"]
            color_emoji = "🔵"
        new_balance = set_balance(winner_id, total_bank)
        add_xp(duel["challenger_id"], 3)
        add_xp(duel["opponent_id"], 3)
        log_game(winner_id, winner_name, "дуэль", total_bank // 2, total_bank, f"vs {loser_name}")
        await msg.edit_text(
            f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n🎲 {color_emoji}\n\n🏆 <b>{winner_name}</b>\n💰 +{total_bank:,}\n💎 {new_balance:,}".replace(',', ' '),
            parse_mode="HTML"
        )
        del duel_games[chat_id]
        return

    if text == 'отмена' and chat_id in duel_games and not duel_games[chat_id].get("active"):
        duel = duel_games[chat_id]
        if user_id in [duel["challenger_id"], duel["opponent_id"]]:
            del duel_games[chat_id]
            await message.reply("❌ <b>Дуэль отменена</b>", parse_mode="HTML")
        return

    if text == 'банк':
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        total = clamp(balance + bank)
        await message.reply(
            f"🏦 <b>БАНК</b>\n👤 {username}\n💰 <b>{balance:,}</b>\n🏦 <b>{bank:,}</b>\n💎 Всего: <b>{total:,}</b>\n\n<code>банк положить 1000</code>\n<code>банк снять 1000</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return
        
    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'положить':
        try:
            amount = int(parts[2])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        balance = get_balance(user_id)
        if balance < amount and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -amount)
        new_bank = set_bank(user_id, amount)
        new_balance = get_balance(user_id)
        await message.reply(f"🏦 <b>В БАНК</b>\n💰 -{amount:,}\n💎 {new_balance:,}\n🏦 {new_bank:,}".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'снять':
        try:
            amount = int(parts[2])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        bank = get_bank(user_id)
        if bank < amount:
            await message.reply(f"❌ В банке только {bank:,}".replace(',', ' '))
            return
        set_bank(user_id, -amount)
        new_balance = set_balance(user_id, amount)
        new_bank = get_bank(user_id)
        await message.reply(f"🏦 <b>ИЗ БАНКА</b>\n💰 +{amount:,}\n💎 {new_balance:,}\n🏦 {new_bank:,}".replace(',', ' '), parse_mode="HTML")
        return

    if parts[0] == 'п':
        if len(parts) < 2:
            await message.reply("💸 Ответь и напиши: <code>п 1000</code>", parse_mode="HTML")
            return
        if not message.reply_to_message or message.reply_to_message.from_user.is_bot:
            await message.reply("❌ Ответь на сообщение!")
            return
        try:
            amount = int(parts[1])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if amount < 1:
            await message.reply("❌ Минимум 1!")
            return
        target = message.reply_to_message.from_user
        if target.id == user_id:
            await message.reply("❌ Себе нельзя!")
            return
        balance = get_balance(user_id)
        if balance < amount and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        ensure_user(target.id, target.username or target.first_name)
        set_balance(user_id, -amount)
        set_balance(target.id, amount)
        nb = get_balance(user_id)
        nt = get_balance(target.id)
        await message.reply(f"💸 <b>ПЕРЕВОД!</b>\n👤 {username} → {target.username or target.first_name}\n💰 <b>{amount:,}</b>\n💎 {nb:,} | {nt:,}".replace(',', ' '), parse_mode="HTML")
        return

    if text in ['отмена', 'отменить']:
        if chat_id in active_bets and active_bets[chat_id]["bets"]:
            count = len(active_bets[chat_id]["bets"])
            for b in active_bets[chat_id]["bets"]:
                set_balance(b["user_id"], b["bet_total"])
            del active_bets[chat_id]
            await message.reply(f"❌ <b>Ставки отменены!</b> Возвращено: {count}", parse_mode="HTML")
        return

    if text in ['б', 'баланс']:
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        xp = get_xp(user_id)
        vip = get_vip_info(xp)
        if is_unlimited(user_id):
            await message.reply(f"💰 <b>БАЛАНС</b>\n👤 {username}\n{vip['icon']} {vip['name']}\n♾️ БЕЗЛИМИТ\n🏦 {bank:,}".replace(',', ' '), parse_mode="HTML")
        else:
            await message.reply(f"💰 <b>БАЛАНС</b>\n👤 {username}\n{vip['icon']} {vip['name']}\n💎 <b>{balance:,}</b>\n🏦 Банк: <b>{bank:,}</b>".replace(',', ' '), parse_mode="HTML")
        return

    if text in ['игры', 'игра']:
        await message.reply("🎮 <b>ИГРЫ</b>", parse_mode="HTML", reply_markup=games_kb())
        return

    if text in ['лог', 'log']:
        rows = get_last_roulette_results(10)
        if not rows:
            await message.reply("📜 Пока пусто...", parse_mode="HTML")
            return
        out = "📜 <b>Результаты:</b>\n"
        for i, (detail,) in enumerate(rows, 1):
            parts_d = detail.split()
            if len(parts_d) >= 2:
                out += f"{i}. {parts_d[1]} {parts_d[0]}\n"
            else:
                out += f"{i}. {detail}\n"
        await message.reply(out, parse_mode="HTML")
        return

    if text in ['топ', 'top']:
        rows = get_top(10)
        if not rows:
            await message.reply("📊 Пока нет игроков!", parse_mode="HTML")
            return
        out = "🏆 <b>ТОП-10</b>\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            uid, uname, bal, xp = row
            medal = medals[i] if i < 3 else f"{i+1}."
            vip = get_vip_info(xp or 0)
            icon = vip["icon"] if xp else ""
            title = get_main_title(uid)
            t = f" 🏷️{title}" if title else ""
            out += f"{medal} {icon} {uname}{t} — <b>{bal:,}</b>\n".replace(',', ' ')
        await message.reply(out, parse_mode="HTML")
        return

    if len(parts) == 2 and parts[0] in ['мины', 'мина', 'mines']:
        try:
            bet = int(parts[1])
        except:
            await message.reply("❌ Неверная сумма!")
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{bet:,}</b>".replace(',', ' '), parse_mode="HTML", reply_markup=mines_level_kb(bet))
        return

    if text == 'го':
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет активных ставок!")
            return
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        unlimited_in_bets = any(is_unlimited(b["user_id"]) for b in bets)
        bank_line = "♾️" if unlimited_in_bets else f"{total_bank:,}".replace(',', ' ')
        msg = await message.reply(f"🎡 <b>РУЛЕТКА!</b>\n💰 {bank_line}\n\n🎲 Крутится...", parse_mode="HTML")
        for frame in ANIM_ROULETTE:
            await asyncio.sleep(0.7)
            try:
                await msg.edit_text(f"🎡 <b>РУЛЕТКА</b>\n💰 {bank_line}\n\n🎲 {frame}", parse_mode="HTML")
            except Exception as e:
                print(f"Ошибка анимации: {e}")
        result = random.randint(0, 36)
        color = "🟢" if result == 0 else ("🔴" if result in RED_NUMBERS else "⚫")
        result_text = f"🎰 <b>{color} {result}</b>\n"
        winners = []
        user_last_bet = None
        for b in bets:
            win_amount = 0
            if b["type"] == "red" and result in RED_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR * get_event_mult())
            elif b["type"] == "black" and result in BLACK_NUMBERS:
                win_amount = int(b["bet_total"] * MULT_COLOR * get_event_mult())
            elif b["type"] == "green" and result == 0:
                win_amount = int(b["bet_total"] * MULT_ZERO * get_event_mult())
            elif b["type"] == "number" and result == b["number"]:
                win_amount = int(b["bet_total"] * MULT_NUMBER * get_event_mult())
            elif b["type"] == "ranges":
                win_mult = 0
                for (a, z) in b["ranges"]:
                    if a <= result <= z:
                        win_mult += MULT_RANGE
                if win_mult > 0:
                    win_amount = int(b["bet_total"] * win_mult * get_event_mult())
            if b["user_id"] == user_id:
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
            result_text += "😢 <b>Победителей нет</b>"
        del active_bets[chat_id]
        try:
            if user_last_bet:
                rkb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"group_bet_{user_last_bet['type']}_{user_last_bet['bet']}"),
                     InlineKeyboardButton(text="⬆️ Удвоить", callback_data=f"group_bet_{user_last_bet['type']}_{user_last_bet['bet']*2}")],
                    [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
                ])
                await msg.edit_text(result_text, parse_mode="HTML", reply_markup=rkb)
            else:
                await msg.edit_text(result_text, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка финала: {e}")
            await message.reply(result_text, parse_mode="HTML")
        return
        
    if len(parts) == 2 and parts[0] in ['спин', 'spin']:
        if is_game_disabled('slots') and user_id != ADMIN_ID:
            await message.reply("❌ <b>Слоты временно отключены</b>", parse_mode="HTML")
            return
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -bet)
        msg = await message.reply("🎰 <b>КРУТИМ...</b>", parse_mode="HTML")
        for frame in ANIM_SLOTS:
            await asyncio.sleep(0.5)
            await msg.edit_text(f"🎰 <b>КРУТИМ...</b>\n{frame}", parse_mode="HTML")
        symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
        r1 = random.choice(symbols)
        r2 = random.choice(symbols)
        r3 = random.choice(symbols)
        win = False
        mult = 0
        if r1 == r2 == r3:
            win = True
            mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True
            mult = 2
        add_xp(user_id, 1)
        update_quest(user_id, "bets_20")
        if win:
            wa = clamp(bet * mult * get_event_mult())
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "слоты", bet, wa, f"{r1}{r2}{r3}")
            await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n🎉 <b>+{wa:,}</b> (×{mult})\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n😢 <b>-{bet:,}</b>\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 2 and parts[0] in ['орёл', 'орел', 'решка']:
        if is_game_disabled('coin') and user_id != ADMIN_ID:
            await message.reply("❌ <b>Монетка временно отключена</b>", parse_mode="HTML")
            return
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -bet)
        msg = await message.reply("🪙 <b>ПОДБРАСЫВАЕМ...</b>", parse_mode="HTML")
        for frame in ANIM_COIN:
            await asyncio.sleep(0.4)
            await msg.edit_text(f"🪙 <b>ПОДБРАСЫВАЕМ...</b>\n\n{frame}", parse_mode="HTML")
        choice = 'heads' if parts[0] in ['орёл', 'орел'] else 'tails'
        result = random.choice(['heads', 'tails'])
        add_xp(user_id, 1)
        update_quest(user_id, "bets_20")
        if result == choice:
            wa = clamp(bet * 2 * get_event_mult())
            nb = set_balance(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, "🦅" if result == 'heads' else "👑")
            await msg.edit_text(f"🪙 <b>МОНЕТКА</b>\n🎯 {'🦅' if result == 'heads' else '👑'}\n🎉 <b>+{wa:,}</b>\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, "🦅" if result == 'heads' else "👑")
            await msg.edit_text(f"🪙 <b>МОНЕТКА</b>\n🎯 {'🦅' if result == 'heads' else '👑'}\n😢 <b>-{bet:,}</b>\n💎 {nb:,}".replace(',', ' '), parse_mode="HTML")
        return

    if len(parts) == 2 and parts[0] in ['бж', 'блэкджек']:
        if is_game_disabled('bj') and user_id != ADMIN_ID:
            await message.reply("❌ <b>Блэкджек временно отключён</b>", parse_mode="HTML")
            return
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -bet)
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        bj_games[user_id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}
        p_score = hand_score(player)
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n👤 Ты: {fmt_hand(player)} = <b>{p_score}</b>\n🤖 Дилер: {fmt_hand(dealer, hide_second=True)}",
            parse_mode="HTML", reply_markup=bj_kb()
        )
        return

    if len(parts) == 2 and parts[0] in ['к', 'ч', 'з']:
        if is_game_disabled('roulette') and user_id != ADMIN_ID:
            await message.reply("❌ <b>Рулетка временно отключена</b>", parse_mode="HTML")
            return
        try:
            bet = int(parts[1])
        except:
            return
        if bet < 10 or bet > MAX_BET:
            await message.reply("❌ Ставка неверна")
            return
        balance = get_balance(user_id)
        if balance < bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -bet)
        bet_type = 'red' if parts[0] == 'к' else ('black' if parts[0] == 'ч' else 'green')
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({"user_id": user_id, "username": username, "type": bet_type, "bet": bet, "bet_total": bet})
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        icon = '🔴' if bet_type == 'red' else ('⚫' if bet_type == 'black' else '🟢')
        await message.reply(
            f"📊 <b>Ставка!</b>\n👤 {username}\n{icon} × <b>{bet:,}</b>\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 <code>го</code>\n❌ <code>отмена</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return

    bet, ranges = parse_multi_bet(text)
    if bet and ranges:
        if bet < 10:
            await message.reply("❌ Минимум 10!")
            return
        total_bet = bet * len(ranges)
        if total_bet > MAX_BET:
            await message.reply("❌ Максимум превышен")
            return
        balance = get_balance(user_id)
        if balance < total_bet and not is_unlimited(user_id):
            await message.reply(f"❌ Недостаточно!")
            return
        set_balance(user_id, -total_bet)
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": []}
        active_bets[chat_id]["bets"].append({"user_id": user_id, "username": username, "type": "ranges", "bet": bet, "bet_total": total_bet, "ranges": ranges})
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        ranges_str = " ".join([f"{a}-{z}" if a != z else str(a) for (a, z) in ranges])
        await message.reply(
            f"📊 <b>Ставка!</b>\n👤 {username}\n🎯 <b>{ranges_str}</b>\n💰 <b>{bet:,}</b> × {len(ranges)} = <b>{total_bet:,}</b>\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{total_bank:,}</b>\n\n🕐 <code>го</code>".replace(',', ' '),
            parse_mode="HTML"
        )
        return
        
async def bank_interest_loop():
    while True:
        await asyncio.sleep(86400)
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE users SET bank = bank + (bank * 0.05)::BIGINT WHERE bank > 0")
            conn.commit()
            c.close()
            conn.close()
            print("🏦 Проценты начислены")
        except Exception as e:
            print(f"Ошибка процентов: {e}")

async def giveaway_checker_loop():
    while True:
        await asyncio.sleep(60)
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("""SELECT id, amount FROM giveaways
                         WHERE status = 'active' AND ends_at <= NOW()""")
            rows = c.fetchall()
            c.close()
            conn.close()
            for gid, amount in rows:
                result = finish_giveaway(gid)
                if result:
                    winner_id, prize = result
                    try:
                        winner_data = get_user(winner_id)
                        wname = winner_data[0] if winner_data else f"user_{winner_id}"
                        await bot.send_message(
                            ADMIN_ID,
                            f"🎁 <b>РОЗЫГРЫШ ЗАВЕРШЁН!</b>\n🏆 Победитель: <b>{wname}</b>\n💰 +{prize:,}".replace(',', ' '),
                            parse_mode="HTML"
                        )
                        await bot.send_message(
                            winner_id,
                            f"🎉 <b>ТЫ ВЫИГРАЛ РОЗЫГРЫШ!</b>\n💰 +{prize:,} токенов!".replace(',', ' '),
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        print(f"Ошибка уведомления: {e}")
        except Exception as e:
            print(f"Ошибка giveaway_checker: {e}")

async def main():
    init_db()
    load_settings()
    logging.basicConfig(level=logging.INFO)
    print("🎰 Бот запущен!")
    asyncio.create_task(bank_interest_loop())
    asyncio.create_task(giveaway_checker_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
