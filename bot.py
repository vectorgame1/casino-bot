# ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 1/6 — ИМПОРТЫ, КОНСТАНТЫ, АНИМАЦИИ, FLASK API
# ═══════════════════════════════════════════════════════════════

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
    CallbackQuery, LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
)
from flask import Flask, jsonify, request
from flask_cors import CORS

# ═══════════════ КОНСТАНТЫ ═══════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ТВОЙ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 6403424348
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MINI_APP_URL = "https://thriving-lokum-1f7004.netlify.app"
GROUP_URL = "https://t.me/+xrmEcGndccs5ZGFi"
TOURNAMENT_CHANNEL = "@TokenCasinoTournaments"

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

MULT_COLOR = 2
MULT_ZERO = 36
MULT_NUMBER = 36
MULT_RANGE = 1.2

MAX_BALANCE = 9_000_000_000
MAX_BET = 100_000_000_000
DAILY_BONUS = 10000
MAX_BIGINT = 9_000_000_000_000_000_000

# ═══════════════ РЕФЕРАЛЬНАЯ СИСТЕМА (НЕ ТРОГАЕМ) ═══════════════
REF_BONUS_REFERRER = 5000
REF_BONUS_REFERRED = 5000

# ═══════════════ ИГРОВЫЕ ДАННЫЕ ═══════════════
MINES_LEVELS = {
    "easy":   {"name": "🟢 Лёгкий",  "mines": 3,  "step": 0.15},
    "medium": {"name": "🟡 Средний", "mines": 5,  "step": 0.25},
    "hard":   {"name": "🔴 Хардкор", "mines": 10, "step": 0.50},
}

GAME_NAMES = {
    "roulette": "🎡 Рулетка",
    "slots": "🎰 Слоты",
    "coin": "🪙 Монетка",
    "mines": "💣 Мины",
    "bj": "🃏 Блэкджек",
    "duel": "⚔️ Дуэль",
}

# ═══════════════ ДЕФОЛТНЫЕ VIP-УРОВНИ ═══════════════
# Формат: id, name, icon, stars (цена), cashback (%), bonus (Tokens),
#         duration_days (срок), exclusive_games (сколько игр)
DEFAULT_VIP_TIERS = [
    {"id": 1, "name": "Серебро",     "icon": "🥈", "stars": 25,  "cashback": 2,  "bonus": 5000,   "duration_days": 20, "exclusive_games": 0},
    {"id": 2, "name": "Золото",      "icon": "🥇", "stars": 50,  "cashback": 4,  "bonus": 15000,  "duration_days": 20, "exclusive_games": 1},
    {"id": 3, "name": "Платина",     "icon": "💎", "stars": 75,  "cashback": 6,  "bonus": 30000,  "duration_days": 20, "exclusive_games": 3},
    {"id": 4, "name": "Бриллиант",   "icon": "💠", "stars": 100, "cashback": 8,  "bonus": 50000,  "duration_days": 20, "exclusive_games": 99},
    {"id": 5, "name": "Чёрная карта", "icon": "🖤", "stars": 150, "cashback": 10, "bonus": 100000, "duration_days": 20, "exclusive_games": 99},
]

# ═══════════════ ДЕФОЛТНЫЕ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ═══════════════
DEFAULT_DAILY_QUESTS = [
    {"key": "daily_bets_5",     "name": "🎰 Сделать 5 ставок",   "target": 5,   "reward": 100},
    {"key": "daily_win_1",      "name": "🎲 Выиграть 1 раз",     "target": 1,   "reward": 200},
    {"key": "daily_ref_1",      "name": "👥 Пригласить друга",   "target": 1,   "reward": 500},
    {"key": "daily_buy_vip",    "name": "⭐ Купить VIP",          "target": 1,   "reward": 1000},
]

# ═══════════════ ДЕФОЛТНЫЕ НАГРАДЫ ЗА УРОВНИ ═══════════════
DEFAULT_LEVEL_REWARDS = [
    {"level": 5,  "type": "tokens", "value": 500},
    {"level": 10, "type": "cashback", "value": 2},
    {"level": 20, "type": "vip_games", "value": 1},
    {"level": 30, "type": "tokens", "value": 5000},
    {"level": 50, "type": "vip_tier", "value": 1},
]

# ═══════════════ ДЕФОЛТНЫЕ ПАКЕТЫ БУСТ XP ═══════════════
DEFAULT_XP_PACKS = [
    {"id": "xp_100",  "xp": 100,  "stars": 5},
    {"id": "xp_500",  "xp": 500,  "stars": 20},
    {"id": "xp_1000", "xp": 1000, "stars": 35},
]

# ═══════════════ ДЕФОЛТНЫЕ ТИТУЛЫ (НОВЫЕ) ═══════════════
DEFAULT_TITLES = [
    {"id": "newbie",    "name": "🥉 Новичок",    "condition": "games",     "value": 0},
    {"id": "player",    "name": "🥈 Игрок",      "condition": "games",     "value": 10},
    {"id": "pro",       "name": "🥇 Профи",      "condition": "games",     "value": 100},
    {"id": "highroller", "name": "💎 Хайроллер", "condition": "max_bet",   "value": 1000000},
    {"id": "lucky",     "name": "🔥 Везунчик",   "condition": "win_streak", "value": 10},
    {"id": "sniper",    "name": "⚡ Снайпер",     "condition": "wins",      "value": 100},
    {"id": "elite",     "name": "💠 Элита",      "condition": "max_win",   "value": 1000000},
    {"id": "legend",    "name": "👑 Легенда",    "condition": "max_win",   "value": 10000000},
    {"id": "shadow",    "name": "🖤 Тень",       "condition": "vip",       "value": 5},
    {"id": "whale",     "name": "🌟 Кит",        "condition": "top1",      "value": 1},
]

# ═══════════════ АНИМАЦИИ ═══════════════
ANIM_ROULETTE = [
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫ 🔴",
    "⚫ 🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴 ⚫",
    "🔴 ⚫ 🔴",
    "🔴",
]
ANIM_ROULETTE_DELAYS = [0.15, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]

ANIM_COIN = ["🦅", "👑", "🦅", "👑", "🦅", "👑"]
ANIM_COIN_DELAYS = [0.2, 0.2, 0.25, 0.25, 0.3, 0.35]

ANIM_DUEL = ["⚔️", "🔴 ⚔️ 🔵", "🔴 💥 🔵", "🔵 💥 🔴", "🔴 ⚔️ 🔵", "💥 БАХ!"]
ANIM_DUEL_DELAYS = [0.25, 0.25, 0.3, 0.3, 0.35, 0.4]


# ═══════════════ СОСТОЯНИЯ ═══════════════
active_bets = {}
bj_games = {}
duel_games = {}
mines_games = {} 
disabled_games = set()
giveaway_timers = {}
edit_state = {}
edit_case_state = {}
edit_shop_state = {}
edit_vip_state = {}
edit_xp_state = {}
edit_quest_state = {}
edit_level_state = {}
bank_input_state = {}
admin_action_state = {}
birthday_input_state = {}
lang_state = {}  # {user_id: "ru" | "en"}

event_double = False
maintenance_on = False
jackpot_amount = 10000

# ═══════════════ КЭШ ═══════════════
_cache = {}

def cache_get(key, ttl=30):
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
        print(f"⚠️ Пул не создан, fallback: {e}")
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
    return get_conn()

# ═══════════════ УТИЛИТЫ ═══════════════
def clamp_balance(amount):
    amount = clamp(amount)
    if amount > MAX_BALANCE:
        return MAX_BALANCE, amount - MAX_BALANCE
    return amount, 0

def clamp(x):
    try:
        return max(-MAX_BIGINT, min(int(x), MAX_BIGINT))
    except Exception:
        return 0

def get_event_mult():
    return 2 if event_double else 1

def fmt_num(n):
    """Числа через пробел: 1 000 000"""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

def fmt_balance(user_id, balance):
    """Красивое отображение баланса с учётом безлимита"""
    if is_unlimited(user_id):
        return "♾️ БЕЗЛИМИТ"
    return f"{fmt_num(balance)} Tokens"

def make_xp_bar(xp, next_xp, level):
    """Прогресс-бар XP: ▰▰▰▱▱▱▱▱▱▱"""
    if next_xp <= xp:
        return "▰" * 10
    base = 0
    return "▰" * 0  # заглушка, переопределим ниже

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
        "vip_tier": get_vip_tier(user_id),
        "vip_expires": get_vip_expires(user_id),
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

# ═══════════════ API ДЛЯ MINI APP ═══════════════
@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    xp = get_xp(user_id)
    stats = get_user_stats(user_id)
    titles = get_user_titles(user_id)
    u = get_user(user_id)
    return jsonify({
        "user_id": user_id,
        "username": u[0] if u else "",
        "balance": get_balance(user_id),
        "bank": get_bank(user_id),
        "xp": xp,
        "vip_tier": get_vip_tier(user_id),
        "vip_expires": get_vip_expires(user_id),
        "cashback": 5,
        "titles": titles,
        "stats": stats,
        "unlimited": is_unlimited(user_id),
    })


@app.route('/api/shop')
def api_shop():
    return jsonify(get_shop_items())


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
            "prices": json.dumps([{"label": item["name"], "amount": int(stars)}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/cases')
def api_cases():
    return jsonify(get_cases())


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
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"Кейс «{case['name']}»",
            "description": case.get("desc", "Кейс с наградами"),
            "payload": f"case_{case_id}",
            "currency": "XTR",
            "prices": json.dumps([{"label": case["name"], "amount": int(case["stars"])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/cases/last_reward/<int:user_id>')
def api_last_reward(user_id):
    reward = get_last_reward(user_id)
    if reward:
        return jsonify(reward)
    return jsonify({})


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

@app.route('/api/market/buy', methods=['POST'])
def api_market_buy():
    data = request.json
    user_id = data.get('user_id')
    lot_id = data.get('lot_id')
    if not user_id or not lot_id:
        return jsonify({"error": "Missing"}), 400
    lots = get_market_lots()
    lot_idx = None
    for i, l in enumerate(lots):
        if l.get("id") == lot_id:
            lot_idx = i
            break
    if lot_idx is None:
        return jsonify({"error": "Lot not found"}), 404
    ok, msg = buy_market_lot(user_id, lot_idx)
    if ok:
        return jsonify({"success": True, "message": msg})
    return jsonify({"error": msg}), 400


@app.route('/api/market/remove', methods=['POST'])
def api_market_remove():
    data = request.json
    user_id = data.get('user_id')
    lot_id = data.get('lot_id')
    if not user_id or not lot_id:
        return jsonify({"error": "Missing"}), 400
    lots = get_market_lots()
    removed = None
    new_lots = []
    for l in lots:
        if l.get("id") == lot_id and l.get("seller_id") == user_id:
            removed = l
        else:
            new_lots.append(l)
    if not removed:
        return jsonify({"error": "Lot not found"}), 404
    save_market_lots(new_lots)
    item = dict(removed["payload"])
    item["type"] = removed["type"]
    add_to_inventory(user_id, item)
    return jsonify({"success": True, "message": "Лот снят, предмет возвращён"})



# ═══════════════ API: VIP ═══════════════
@app.route('/api/vip')
def api_vip():
    return jsonify(get_vip_tiers())


@app.route('/api/vip/buy', methods=['POST'])
def api_vip_buy():
    import requests as _requests
    data = request.json
    user_id = data.get('user_id')
    tier_id = data.get('tier_id')
    if not user_id or not tier_id:
        return jsonify({"error": "Missing"}), 400
    info = get_vip_tier_info(int(tier_id))
    if not info:
        return jsonify({"error": "VIP not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"{info['icon']} VIP {info['id']} — {info['name']}",
            "description": f"Кэшбэк {info['cashback']}%, бонус +{fmt_num(info['bonus'])} Tokens, {info['duration_days']} дней",
            "payload": f"vip_{info['id']}_{info['stars']}",
            "currency": "XTR",
            "prices": json.dumps([{"label": f"VIP {info['id']} — {info['name']}", "amount": int(info['stars'])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════ API: XP-ПАКИ ═══════════════
@app.route('/api/xp')
def api_xp():
    return jsonify(get_xp_packs())


@app.route('/api/xp/buy', methods=['POST'])
def api_xp_buy():
    import requests as _requests
    data = request.json
    user_id = data.get('user_id')
    pack_id = data.get('pack_id')
    if not user_id or not pack_id:
        return jsonify({"error": "Missing"}), 400
    packs = get_xp_packs()
    pack = next((p for p in packs if p.get("id") == pack_id), None)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
        payload = {
            "title": f"⭐ Буст XP +{pack['xp']}",
            "description": f"Мгновенно +{pack['xp']} XP",
            "payload": f"xp_{pack['id']}_{pack['xp']}_{pack['stars']}",
            "currency": "XTR",
            "prices": json.dumps([{"label": f"+{pack['xp']} XP", "amount": int(pack['stars'])}]),
        }
        r = _requests.post(url, data=payload, timeout=15)
        result = r.json()
        if result.get("ok"):
            return jsonify({"invoice_url": result["result"]})
        return jsonify({"error": f"Telegram: {result.get('description', 'unknown')}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════ API: ЗАДАНИЯ ═══════════════
@app.route('/api/quests/<int:user_id>')
def api_quests(user_id):
    if is_banned(user_id):
        return jsonify({"error": "Banned"}), 403
    return jsonify(get_user_daily_quests(user_id))


@app.route('/api/quests/claim', methods=['POST'])
def api_quests_claim():
    data = request.json
    user_id = data.get('user_id')
    quest_key = data.get('quest_key')
    if not user_id or not quest_key:
        return jsonify({"error": "Missing"}), 400
    reward = claim_daily_quest(user_id, quest_key)
    if reward:
        return jsonify({"success": True, "reward": reward, "balance": get_balance(user_id)})
    return jsonify({"success": False, "error": "Already claimed or not completed"})


# ═══════════════ API: ТУРНИР ═══════════════
@app.route('/api/tournament')
def api_tournament():
    t = get_active_tournament()
    if not t:
        return jsonify({"active": False})
    tid, name, started, ends, p1, p2, p3 = t
    top = get_tournament_top(tid, 10)
    players = []
    for uid, uname, total in top:
        players.append({
            "user_id": uid,
            "username": uname,
            "total_won": total,
        })
    return jsonify({
        "active": True,
        "name": name,
        "ends_at": ends.isoformat() if ends else None,
        "prize_1": p1,
        "prize_2": p2,
        "prize_3": p3,
        "top": players,
    })


# ═══════════════ API: ПРОДАЖА НА РЫНОК ═══════════════
@app.route('/api/inventory/sell', methods=['POST'])
def api_inventory_sell():
    data = request.json
    user_id = data.get('user_id')
    inv_id = data.get('inv_id')
    price = data.get('price')
    if not user_id or not inv_id or not price:
        return jsonify({"error": "Missing"}), 400
    try:
        price = int(price)
    except Exception:
        return jsonify({"error": "Invalid price"}), 400
    if price < 10000:
        return jsonify({"error": "Minimum price is 10 000"}), 400
    if price > MAX_BALANCE:
        return jsonify({"error": "Maximum price exceeded"}), 400
    item = find_inventory_item(user_id, inv_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    username = get_user(user_id)
    uname = username[0] if username else f"user_{user_id}"
    remove_from_inventory(user_id, inv_id)
    lot_id = add_market_lot(user_id, uname, item, price)
    return jsonify({"success": True, "lot_id": lot_id, "price": price})


@app.route('/api/players')
def api_players():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, xp, banned, unlimited FROM users ORDER BY balance DESC")
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
    banned = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
    total_balance = c.fetchone()[0]
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
    return jsonify({"total": total, "banned": banned, "total_balance": total_balance, "players": players})


# ═══════════════ API: ИГРЫ ═══════════════
@app.route('/api/game/roulette', methods=['POST'])
def api_game_roulette():
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    choice = data.get('choice', 'red')
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    set_balance(user_id, -bet)
    result = random.randint(0, 36)
    if result == 0:
        color = "green"
    elif result in RED_NUMBERS:
        color = "red"
    else:
        color = "black"
    mult = 0; win = False
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
        pay_ref_commission(user_id, amount)
    add_xp(user_id, 1)
    update_quest(user_id, "roulette_10")
    update_daily_quest(user_id, "daily_bets_5", 1)
    return jsonify({
        "win": win, "result": result, "color": color,
        "amount": amount, "bet": bet, "balance": get_balance(user_id),
    })


@app.route('/api/game/slots', methods=['POST'])
def api_game_slots():
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    set_balance(user_id, -bet)
    symbols = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
    r1 = random.choice(symbols); r2 = random.choice(symbols); r3 = random.choice(symbols)
    win = False; mult = 0
    if r1 == r2 == r3:
        win = True
        mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
    elif r1 == r2 or r2 == r3 or r1 == r3:
        win = True; mult = 2
    amount = 0
    if win:
        amount = clamp(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "слоты", bet, amount, f"{r1}{r2}{r3}")
        pay_ref_commission(user_id, amount)
    add_xp(user_id, 1)
    update_quest(user_id, "bets_20")
    update_daily_quest(user_id, "daily_bets_5", 1)
    return jsonify({
        "win": win, "reels": [r1, r2, r3], "amount": amount,
        "bet": bet, "balance": get_balance(user_id),
    })


@app.route('/api/game/coin', methods=['POST'])
def api_game_coin():
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    choice = data.get('choice', 'heads')
    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    set_balance(user_id, -bet)
    result = "heads" if random.random() < 0.5 else "tails"
    win = result == choice
    amount = 0
    if win:
        amount = clamp(int(bet * 2 * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, amount)
        u = get_user(user_id)
        uname = u[0] if u else "user"
        log_game(user_id, uname, "монетка", bet, amount, "🦅" if result == "heads" else "👑")
        pay_ref_commission(user_id, amount)
    add_xp(user_id, 1)
    update_quest(user_id, "bets_20")
    update_daily_quest(user_id, "daily_bets_5", 1)
    return jsonify({
        "win": win, "result": result, "amount": amount,
        "bet": bet, "balance": get_balance(user_id),
    })


@app.route('/api/game/mines/start', methods=['POST'])
def api_mines_start():
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    level = data.get('level', 'easy')
    if not user_id or bet < 10 or level not in MINES_LEVELS:
        return jsonify({"error": "Invalid"}), 400
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Not enough balance"}), 400
    set_balance(user_id, -bet)
    mines_count = MINES_LEVELS[level]["mines"]
    positions = list(range(25))
    random.shuffle(positions)
    mine_positions = set(positions[:mines_count])
    game_data = {"bet": bet, "level": level, "mines": list(mine_positions), "opened": []}
    conn = get_conn()
    c = conn.cursor()
    key = f"mines_game_{user_id}"
    value = json.dumps(game_data)
    c.execute("""INSERT INTO settings (key, value) VALUES (%s, %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (key, value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    return jsonify({"success": True, "level": level, "bet": bet, "mines_count": mines_count})


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
            "mine": True, "idx": idx, "win": False, "amount": 0,
            "mines": game["mines"], "balance": get_balance(user_id),
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
        pay_ref_commission(user_id, wa)
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()
        c.close()
        release_conn(conn)
        return jsonify({
            "mine": False, "idx": idx, "win": True, "amount": wa,
            "balance": get_balance(user_id), "mult": mult,
            "cashout_auto": True, "mines": game["mines"],
        })
    return jsonify({
        "mine": False, "idx": idx, "win": False, "amount": 0,
        "mult": mult, "opened": game["opened"], "balance": get_balance(user_id),
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
    pay_ref_commission(user_id, wa)
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key = %s", (key,))
    conn.commit()
    c.close()
    release_conn(conn)
    return jsonify({"win": True, "amount": wa, "mult": mult, "balance": get_balance(user_id)})


# ═══════════════ ЗАПУСК FLASK ═══════════════
def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)

web_thread = threading.Thread(target=run_web)
web_thread.daemon = True
web_thread.start()

# ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 2/6 — БД, CRUD, УВЕДОМЛЕНИЯ, VIP-ХЕЛПЕРЫ, ЯЗЫК
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ИНИЦИАЛИЗАЦИЯ БД ═══════════════
def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ─── Основные таблицы ───
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

    # ─── НОВЫЕ таблицы ───
    c.execute("""CREATE TABLE IF NOT EXISTS purchase_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        purchase_type TEXT,
        item_name TEXT,
        price TEXT,
        source TEXT,
        extra TEXT,
        created_at TIMESTAMP DEFAULT NOW()
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
    c.execute("""CREATE TABLE IF NOT EXISTS level_rewards_claimed (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        level INT NOT NULL,
        claimed_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, level)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tournaments (
        id SERIAL PRIMARY KEY,
        name TEXT,
        started_at TIMESTAMP DEFAULT NOW(),
        ends_at TIMESTAMP,
        status TEXT DEFAULT 'active',
        prize_1 BIGINT DEFAULT 10000,
        prize_2 BIGINT DEFAULT 5000,
        prize_3 BIGINT DEFAULT 2000,
        winner_1 BIGINT,
        winner_2 BIGINT,
        winner_3 BIGINT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tournament_scores (
        id SERIAL PRIMARY KEY,
        tournament_id INT,
        user_id BIGINT,
        username TEXT,
        total_won BIGINT DEFAULT 0,
        UNIQUE(tournament_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS daily_cashback (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount BIGINT,
        date DATE DEFAULT CURRENT_DATE,
        paid_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, date)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_vip (
        user_id BIGINT PRIMARY KEY,
        tier INT DEFAULT 0,
        expires_at TIMESTAMP,
        purchased_at TIMESTAMP DEFAULT NOW()
    )""")

    # ─── ALTER users ───
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_last_claim TIMESTAMP")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS inventory JSONB DEFAULT '[]'::jsonb")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_earnings BIGINT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_count INT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday TEXT")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'ru'")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INT DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date DATE")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS win_streak INT DEFAULT 0")

    # ─── Индексы ───
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_user ON game_log(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_game ON game_log(game)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_game_log_created ON game_log(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_boosts_user ON boosts(user_id, until)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_group_members_chat ON group_members(chat_id, user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_log_created ON purchase_log(created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_purchase_log_user ON purchase_log(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tournament_scores ON tournament_scores(tournament_id, total_won DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_active_vip_expires ON active_vip(expires_at)")
    
    # ─── ТАБЛИЦЫ ДЛЯ CRASH ───
    c.execute("""CREATE TABLE IF NOT EXISTS crash_rounds (
        id SERIAL PRIMARY KEY,
        crash_point DECIMAL(10,2),
        started_at TIMESTAMP DEFAULT NOW(),
        crashed_at TIMESTAMP,
        status TEXT DEFAULT 'waiting'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS crash_bets (
        id SERIAL PRIMARY KEY,
        round_id INT,
        user_id BIGINT,
        username TEXT,
        bet BIGINT,
        auto_cashout DECIMAL(10,2),
        cashed_out_at DECIMAL(10,2),
        won BIGINT DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crash_bets_round ON crash_bets(round_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crash_bets_user ON crash_bets(user_id)")

    # ─── ТАБЛИЦА ДЛЯ PLINKO ───
    c.execute("""CREATE TABLE IF NOT EXISTS plinko_history (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        bet BIGINT,
        risk TEXT,
        position INT,
        multiplier DECIMAL(10,2),
        won BIGINT,
        created_at TIMESTAMP DEFAULT NOW()
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_plinko_user ON plinko_history(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_plinko_created ON plinko_history(created_at DESC)")

    conn.commit()
    c.close()
    release_conn(conn)
    print("✅ БД инициализирована + все таблицы + индексы")


# ═══════════════ CRUD: USERS ═══════════════
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
    """Начисляет XP. Возвращает (new_xp, level_changed, new_level)."""
    if amount <= 0:
        return get_xp(user_id), False, 0
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(xp, 0) FROM users WHERE user_id = %s", (user_id,))
    old_xp = c.fetchone()[0] or 0
    old_level = old_xp // 100  # каждый 100 XP = 1 уровень
    c.execute("UPDATE users SET xp = xp + %s WHERE user_id = %s", (amount, user_id))
    new_xp = old_xp + amount
    new_level = new_xp // 100
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"xp_{user_id}")
    cache_invalidate(f"user_{user_id}")
    return new_xp, (new_level > old_level), new_level


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
    amount = clamp(amount)
    if is_unlimited(user_id) and amount < 0:
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


# ═══════════════ VIP: ACTIVE TIER ═══════════════
def get_vip_tier(user_id):
    """Возвращает активный VIP tier (0 если нет/истёк)."""
    cache_key = f"vip_tier_{user_id}"
    cached = cache_get(cache_key, ttl=15)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT tier FROM active_vip WHERE user_id = %s AND expires_at > NOW()",
        (user_id,)
    )
    row = c.fetchone()
    c.close()
    release_conn(conn)
    val = row[0] if row else 0
    cache_set(cache_key, val, ttl=15)
    return val


def get_vip_expires(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM active_vip WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row[0] if row else None


def set_vip_tier(user_id, tier, days=20):
    """Апгрейд VIP — перезапись. tier=0 — убрать."""
    if tier == 0:
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM active_vip WHERE user_id = %s", (user_id,))
        conn.commit()
        c.close()
        release_conn(conn)
        cache_invalidate(f"vip_tier_{user_id}")
        return

    expires = datetime.now() + timedelta(days=days)
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO active_vip (user_id, tier, expires_at, purchased_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            tier = EXCLUDED.tier,
            expires_at = EXCLUDED.expires_at,
            purchased_at = NOW()
    """, (user_id, tier, expires))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate(f"vip_tier_{user_id}")


def get_vip_tier_info(tier_id):
    """Возвращает dict тира по id, или None."""
    if tier_id < 1 or tier_id > 5:
        return None
    tiers = get_vip_tiers()
    for t in tiers:
        if t["id"] == tier_id:
            return t
    return None


def get_vip_tiers():
    """Активные VIP-тиры (из settings или дефолтные)."""
    cached = cache_get("vip_tiers", ttl=30)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'vip_tiers'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            tiers = json.loads(row[0])
            if isinstance(tiers, list) and tiers:
                cache_set("vip_tiers", tiers, ttl=30)
                return tiers
        except Exception:
            pass
    cache_set("vip_tiers", [dict(t) for t in DEFAULT_VIP_TIERS], ttl=30)
    return [dict(t) for t in DEFAULT_VIP_TIERS]


def save_vip_tiers(tiers):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(tiers, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('vip_tiers', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("vip_tiers")


# ═══════════════ ЯЗЫК ═══════════════
def get_lang(user_id):
    """Возвращает 'ru' или 'en'."""
    if user_id in lang_state:
        return lang_state[user_id]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(lang, 'ru') FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    lang = row[0] if row else 'ru'
    if lang not in ('ru', 'en'):
        lang = 'ru'
    lang_state[user_id] = lang
    return lang


def set_lang(user_id, lang):
    if lang not in ('ru', 'en'):
        return
    lang_state[user_id] = lang
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET lang = %s WHERE user_id = %s", (lang, user_id))
    conn.commit()
    c.close()
    release_conn(conn)


# ═══════════════ ТОПЫ ═══════════════
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
    # Обновляем total_won / total_lost
    if win > 0:
        c.execute("UPDATE users SET total_won = total_won + %s WHERE user_id = %s", (win, user_id))
    else:
        c.execute("UPDATE users SET total_lost = total_lost + %s WHERE user_id = %s", (bet, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("top_balance")
    cache_invalidate("top_xp")
    # Обновляем турнир
    if win > 0:
        update_tournament_score(user_id, username, win)


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


# ═══════════════ УВЕДОМЛЕНИЯ АДМИНУ / PURCHASES ═══════════════
def log_purchase(user_id, username, purchase_type, item_name, price, source, extra=""):
    """Сохраняет покупку в purchase_log."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO purchase_log
                     (user_id, username, purchase_type, item_name, price, source, extra)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                  (user_id, username, purchase_type, item_name, price, source, extra))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[log_purchase] error: {e}")


async def notify_admin_purchase(user_id, username, purchase_type, item_name, price, source, extra=""):
    """Отправляет карточку покупки админу (с учётом фильтра)."""
    try:
        # Фильтр: что уведомлять
        should_notify = False
        if purchase_type == "stars":
            should_notify = True
        elif purchase_type == "case":
            should_notify = True
        elif purchase_type == "tokens":
            try:
                if int(str(price).split()[0]) > 1_000_000:
                    should_notify = True
            except Exception:
                pass
        elif purchase_type == "market":
            try:
                if int(str(price).split()[0]) > 500_000:
                    should_notify = True
            except Exception:
                pass
        elif purchase_type == "jackpot":
            should_notify = True
        # bonus — не уведомляем

        if not should_notify:
            return

        # Формируем карточку
        time_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        text = (
            f"📋 <b>Покупка!</b>\n"
            f"────────────\n"
            f"👤 Игрок: @{username or f'id{user_id}'}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💎 Товар: <b>{item_name}</b>\n"
            f"⭐ Сумма: <b>{price}</b>\n"
            f"📍 Источник: {source}\n"
            f"🕐 Время: {time_str}"
        )
        if extra:
            text += f"\n📝 {extra}"

        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print(f"[notify_admin_purchase] error: {e}")


def get_purchases(limit=20):
    """Последние N покупок."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, purchase_type, item_name, price, source, created_at
                 FROM purchase_log ORDER BY id DESC LIMIT %s""", (limit,))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


# ═══════════════ РЕФЕРАЛЬНАЯ СИСТЕМА (НЕ ТРОГАЕМ) ═══════════════
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
    set_balance(user_id, REF_BONUS_REFERRED)
    set_balance(referrer_id, REF_BONUS_REFERRER)
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


# ═══════════════ ИНВЕНТАРЬ ═══════════════
def get_inventory(user_id):
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
        set_vip_tier(user_id, item["vip_level"], 20)
        remove_from_inventory(user_id, inv_id)
        return True, f"👑 VIP {item['vip_level']} активирован на 20 дней!"
    if t == "case":
        return False, "🎰 Кейс нужно открыть отдельно"
    return False, "❌ Неизвестный тип"


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


# ═══════════════ ЕЖЕДНЕВНЫЙ ВХОД (STREAK) ═══════════════
def check_daily_login(user_id):
    """
    Проверяет streak входа. Возвращает (streak, bonus_awarded).
    Если заходил вчера — streak+1, если сегодня уже — ничего, иначе streak=1.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT login_streak, last_login_date FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    today = datetime.now().date()
    if not row:
        c.execute("UPDATE users SET login_streak = 1, last_login_date = %s WHERE user_id = %s",
                  (today, user_id))
        conn.commit()
        c.close()
        release_conn(conn)
        return 1, 0

    streak, last_date = row
    streak = streak or 0
    if last_date == today:
        c.close()
        release_conn(conn)
        return streak, 0

    if last_date == today - timedelta(days=1):
        streak += 1
    else:
        streak = 1

    bonus = 0
    if streak >= 7:
        bonus = 50000
        streak = 0

    c.execute("UPDATE users SET login_streak = %s, last_login_date = %s WHERE user_id = %s",
              (streak, today, user_id))
    conn.commit()
    c.close()
    release_conn(conn)
    if bonus > 0:
        set_balance(user_id, bonus)
    return streak, bonus


# ═══════════════ БАНК: ПРОЦЕНТЫ ═══════════════
def accrue_bank_interest():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET bank = bank + (bank * 0.05)::BIGINT WHERE bank > 0")
    conn.commit()
    c.close()
    release_conn(conn)


# ═══════════════ ТУРНИРЫ ═══════════════
def get_active_tournament():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, name, started_at, ends_at, prize_1, prize_2, prize_3
                 FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1""")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    return row


def start_tournament(name, duration_hours=168):
    """Запускает турнир на N часов (по умолчанию 7 дней)."""
    ends_at = datetime.now() + timedelta(hours=duration_hours)
    conn = get_conn()
    c = conn.cursor()
    # Закрываем предыдущие
    c.execute("UPDATE tournaments SET status = 'finished' WHERE status = 'active'")
    c.execute("""INSERT INTO tournaments (name, ends_at, status, prize_1, prize_2, prize_3)
                 VALUES (%s, %s, 'active', 10000, 5000, 2000) RETURNING id""",
              (name, ends_at))
    tid = c.fetchone()[0]
    conn.commit()
    c.close()
    release_conn(conn)
    return tid, ends_at


def update_tournament_score(user_id, username, win_amount):
    """Обновляет счёт игрока в активном турнире."""
    try:
        t = get_active_tournament()
        if not t:
            return
        tid = t[0]
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO tournament_scores (tournament_id, user_id, username, total_won)
                     VALUES (%s, %s, %s, %s)
                     ON CONFLICT (tournament_id, user_id) DO UPDATE
                     SET total_won = tournament_scores.total_won + EXCLUDED.total_won,
                         username = EXCLUDED.username""",
                  (tid, user_id, username, win_amount))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[update_tournament_score] {e}")


def get_tournament_top(tid, limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT user_id, username, total_won FROM tournament_scores
                 WHERE tournament_id = %s ORDER BY total_won DESC LIMIT %s""",
              (tid, limit))
    rows = c.fetchall()
    c.close()
    release_conn(conn)
    return rows


def finish_tournament(tid):
    """Финализирует турнир и начисляет призы."""
    t = get_active_tournament()
    if not t or t[0] != tid:
        return None
    top = get_tournament_top(tid, 3)
    prizes = [t[4], t[5], t[6]]  # prize_1, prize_2, prize_3
    winners = []
    for i, (uid, uname, total) in enumerate(top):
        if i < 3 and prizes[i] > 0:
            set_balance(uid, prizes[i])
            winners.append((uid, uname, prizes[i]))
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE tournaments SET status = 'finished',
                 winner_1 = %s, winner_2 = %s, winner_3 = %s WHERE id = %s""",
              (winners[0][0] if len(winners) > 0 else None,
               winners[1][0] if len(winners) > 1 else None,
               winners[2][0] if len(winners) > 2 else None,
               tid))
    conn.commit()
    c.close()
    release_conn(conn)
    return winners


# ═══════════════ ЕЖЕДНЕВНЫЙ КЭШБЭК 5% ═══════════════
def calc_cashback_today(user_id):
    """Считает 5% от проигрышей за последние 24 часа."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT COALESCE(SUM(bet - win), 0) FROM game_log
                 WHERE user_id = %s AND created_at > NOW() - INTERVAL '24 hours'
                 AND win < bet""", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    lost = row[0] if row else 0
    if lost <= 0:
        return 0
    return int(lost * 0.05)


def pay_daily_cashback():
    """Начисляет кэшбэк всем, кто играл за сутки."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, username, COALESCE(SUM(bet - win), 0) AS lost
        FROM game_log
        WHERE created_at > NOW() - INTERVAL '24 hours' AND win < bet
        GROUP BY user_id, username
        HAVING SUM(bet - win) > 0
    """)
    rows = c.fetchall()
    paid = 0
    for uid, uname, lost in rows:
        amount = int(lost * 0.05)
        if amount < 100:
            continue
        try:
            set_balance(uid, amount)
            c.execute("""INSERT INTO daily_cashback (user_id, amount)
                         VALUES (%s, %s) ON CONFLICT (user_id, date) DO NOTHING""",
                      (uid, amount))
            paid += 1
        except Exception as e:
            print(f"[cashback {uid}] {e}")
    conn.commit()
    c.close()
    release_conn(conn)
    return paid


# ═══════════════ XP-ПАКИ (БУСТ XP) ═══════════════
def get_xp_packs():
    cached = cache_get("xp_packs", ttl=30)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'xp_packs'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            packs = json.loads(row[0])
            if isinstance(packs, list) and packs:
                cache_set("xp_packs", packs, ttl=30)
                return packs
        except Exception:
            pass
    cache_set("xp_packs", [dict(p) for p in DEFAULT_XP_PACKS], ttl=30)
    return [dict(p) for p in DEFAULT_XP_PACKS]


def save_xp_packs(packs):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(packs, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('xp_packs', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("xp_packs")


# ═══════════════ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ═══════════════
def get_daily_quests():
    cached = cache_get("daily_quests", ttl=30)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'daily_quests'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            qs = json.loads(row[0])
            if isinstance(qs, list) and qs:
                cache_set("daily_quests", qs, ttl=30)
                return qs
        except Exception:
            pass
    cache_set("daily_quests", [dict(q) for q in DEFAULT_DAILY_QUESTS], ttl=30)
    return [dict(q) for q in DEFAULT_DAILY_QUESTS]


def save_daily_quests(quests):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(quests, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('daily_quests', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("daily_quests")


def get_user_daily_quests(user_id):
    """Возвращает список заданий с прогрессом за сегодня."""
    quests = get_daily_quests()
    result = []
    conn = get_conn()
    c = conn.cursor()
    for q in quests:
        c.execute("""SELECT progress, claimed, reset_at FROM daily_quests
                     WHERE user_id = %s AND quest_key = %s""",
                  (user_id, q["key"]))
        row = c.fetchone()
        if row and row[2] and row[2].date() == datetime.now().date():
            progress, claimed = row[0], row[1]
        else:
            # Сброс на сегодня
            c.execute("""INSERT INTO daily_quests (user_id, quest_key, progress, claimed, reset_at)
                         VALUES (%s, %s, 0, FALSE, NOW())
                         ON CONFLICT (user_id, quest_key) DO UPDATE
                         SET progress = 0, claimed = FALSE, reset_at = NOW()""",
                      (user_id, q["key"]))
            progress, claimed = 0, False
        result.append({
            "key": q["key"], "name": q["name"], "reward": q["reward"],
            "target": q["target"], "progress": progress,
            "completed": progress >= q["target"],
            "claimed": claimed,
        })
    conn.commit()
    c.close()
    release_conn(conn)
    return result


def update_daily_quest(user_id, quest_key, amount=1):
    """Обновляет прогресс ежедневного задания."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO daily_quests (user_id, quest_key, progress, reset_at)
                     VALUES (%s, %s, %s, NOW())
                     ON CONFLICT (user_id, quest_key) DO UPDATE
                     SET progress = daily_quests.progress + EXCLUDED.progress,
                         reset_at = NOW()""",
                  (user_id, quest_key, amount))
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[update_daily_quest] {e}")


def claim_daily_quest(user_id, quest_key):
    """Забирает награду. Возвращает reward или None."""
    quests = get_daily_quests()
    q = next((x for x in quests if x["key"] == quest_key), None)
    if not q:
        return None
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT progress, claimed FROM daily_quests
                 WHERE user_id = %s AND quest_key = %s""", (user_id, quest_key))
    row = c.fetchone()
    if not row or row[1] or row[0] < q["target"]:
        c.close()
        release_conn(conn)
        return None
    c.execute("""UPDATE daily_quests SET claimed = TRUE
                 WHERE user_id = %s AND quest_key = %s""", (user_id, quest_key))
    conn.commit()
    c.close()
    release_conn(conn)
    set_balance(user_id, q["reward"])
    return q["reward"]


# ═══════════════ НАГРАДЫ ЗА УРОВНИ ═══════════════
def get_level_rewards():
    cached = cache_get("level_rewards", ttl=30)
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'level_rewards'")
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        try:
            rewards = json.loads(row[0])
            if isinstance(rewards, list) and rewards:
                cache_set("level_rewards", rewards, ttl=30)
                return rewards
        except Exception:
            pass
    cache_set("level_rewards", [dict(r) for r in DEFAULT_LEVEL_REWARDS], ttl=30)
    return [dict(r) for r in DEFAULT_LEVEL_REWARDS]


def save_level_rewards(rewards):
    conn = get_conn()
    c = conn.cursor()
    value = json.dumps(rewards, ensure_ascii=False)
    c.execute("""INSERT INTO settings (key, value) VALUES ('level_rewards', %s)
                 ON CONFLICT (key) DO UPDATE SET value = %s""", (value, value))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate("level_rewards")


def check_level_rewards(user_id, new_level):
    """Проверяет и выдаёт награды за новый уровень. Возвращает список выданного."""
    rewards = get_level_rewards()
    given = []
    conn = get_conn()
    c = conn.cursor()
    for r in rewards:
        if r["level"] > new_level:
            continue
        c.execute("SELECT 1 FROM level_rewards_claimed WHERE user_id = %s AND level = %s",
                  (user_id, r["level"]))
        if c.fetchone():
            continue
        # Выдаём
        if r["type"] == "tokens":
            set_balance(user_id, r["value"])
            given.append(f"🏆 Уровень {r['level']} — +{fmt_num(r['value'])} Tokens")
        elif r["type"] == "cashback":
            given.append(f"🏆 Уровень {r['level']} — кэшбэк +{r['value']}%")
        elif r["type"] == "vip_games":
            given.append(f"🏆 Уровень {r['level']} — VIP-игры разблокированы")
        elif r["type"] == "vip_tier":
            set_vip_tier(user_id, r["value"], 20)
            given.append(f"🏆 Уровень {r['level']} — VIP {r['value']} бесплатно")
        c.execute("INSERT INTO level_rewards_claimed (user_id, level) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                  (user_id, r["level"]))
    conn.commit()
    c.close()
    release_conn(conn)
    return given


# ═══════════════ СБРОС ЮЗЕРА ═══════════════
def reset_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET balance = 1000, bank = 0, xp = 0, vip_level = 0,
                 total_lost = 0, total_won = 0, inventory = '[]'::jsonb,
                 birthday = NULL, login_streak = 0, last_login_date = NULL
                 WHERE user_id = %s""", (user_id,))
    c.execute("DELETE FROM quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM achievements WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM titles WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM daily_quests WHERE user_id = %s", (user_id,))
    c.execute("DELETE FROM level_rewards_claimed WHERE user_id = %s", (user_id,))
    conn.commit()
    c.close()
    release_conn(conn)
    cache_invalidate()


# ═══════════════ ЗАГРУЗКА НАСТРОЕК ═══════════════
def load_settings():
    global disabled_games
    disabled_games = get_disabled_games()
    print(f"✅ Настройки: disabled_games = {disabled_games}")


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


def is_game_disabled(game):
    return game in disabled_games
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 3/6 — МАГАЗИН, КЕЙСЫ, ДЖЕКПОТ, РЫНОК, НАГРАДЫ
# ═══════════════════════════════════════════════════════════════

# ═══════════════ КВЕСТЫ (старые) ═══════════════
QUESTS = [
    {"key": "roulette_10", "name": "🎡 Сыграй 10 раз в рулетку",  "target": 10,     "reward": 5000},
    {"key": "mines_win_5", "name": "💣 Выиграй 5 раз в Мины",     "target": 5,      "reward": 5000},
    {"key": "bets_20",     "name": "🎰 Сделай 20 ставок",          "target": 20,     "reward": 10000},
    {"key": "win_100k",    "name": "💰 Выиграй 100 000 Tokens",   "target": 100000, "reward": 20000},
    {"key": "bj_5",        "name": "🃏 Сыграй в Блэкджек 5 раз",   "target": 5,      "reward": 5000},
    {"key": "jackpot_1",   "name": "💎 Сорви джекпот",              "target": 1,      "reward": 100000},
]


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


def grant_shop_item(user_id, it):
    """Выдаёт предмет из магазина в инвентарь."""
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


# ═══════════════ ДЖЕКПОТ ═══════════════
def get_jackpot():
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
    current = get_jackpot()
    new_val = clamp(current + amount)
    save_jackpot(new_val)
    return new_val


def reset_jackpot():
    save_jackpot(10000)
    return 10000


# ═══════════════ РЫНОК ═══════════════
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
        return False, f"❌ Недостаточно! Нужно {fmt_num(price)} Tokens"
    set_balance(buyer_id, -price)
    commission = int(price * 0.05)
    seller_gets = price - commission
    add_to_jackpot(commission)
    set_balance(lot["seller_id"], seller_gets)
    new_item = dict(lot["payload"])
    new_item["type"] = lot["type"]
    add_to_inventory(buyer_id, new_item)
    lots.pop(lot_idx)
    save_market_lots(lots)
    return True, (
        f"✅ Куплено!\n"
        f"💰 Цена: <b>{fmt_num(price)}</b> Tokens\n"
        f"💸 Продавцу: <b>{fmt_num(seller_gets)}</b> Tokens\n"
        f"🎰 Комиссия в джекпот: <b>{fmt_num(commission)}</b> Tokens"
    )


# ═══════════════ LAST REWARD (для Mini App) ═══════════════
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


# ═══════════════ РЕФЕРАЛЬНАЯ КОМИССИЯ (НЕ ТРОГАЕМ) ═══════════════
def pay_ref_commission(user_id, win_amount):
    """Начисляет % с выигрыша реферала его рефереру (1 уровень, 5%)."""
    if win_amount <= 0:
        return
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        release_conn(conn)
        if not row or not row[0]:
            return
        ref = row[0]
        amt = int(win_amount * 5 / 100)
        if amt > 0:
            set_balance(ref, amt)
            add_ref_earnings(ref, amt)
    except Exception as e:
        print(f"[pay_ref_commission] error: {e}")


# ═══════════════ ПРОВЕРКА ТИТУЛОВ ═══════════════
def check_titles(user_id, username):
    """Проверяет и выдаёт новые титулы по достижениям."""
    try:
        stats = get_user_stats(user_id)
        games = stats["total_games"]
        wins = stats["total_wins"]
        max_win = stats["best_win"]

        # Получаем максимальную ставку
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(bet), 0) FROM game_log WHERE user_id = %s", (user_id,))
        max_bet = c.fetchone()[0]
        c.close()
        release_conn(conn)

        vip_tier = get_vip_tier(user_id)

        # Проверяем условия
        earned = []
        for t in DEFAULT_TITLES:
            # Уже есть?
            if t["name"] in get_user_titles(user_id):
                continue
            cond = t["condition"]
            val = t["value"]
            ok = False
            if cond == "games" and games >= val:
                ok = True
            elif cond == "wins" and wins >= val:
                ok = True
            elif cond == "max_bet" and max_bet >= val:
                ok = True
            elif cond == "max_win" and max_win >= val:
                ok = True
            elif cond == "vip" and vip_tier >= val:
                ok = True
            if ok:
                add_title(user_id, t["name"], 0)
                earned.append(t["name"])
        return earned
    except Exception as e:
        print(f"[check_titles] {e}")
        return []
        # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 4/6 — КЛАВИАТУРЫ, ТЕКСТЫ, LANG, HELP
# ═══════════════════════════════════════════════════════════════

# ═══════════════ ХЕЛПЕРЫ ДЛЯ XP-БАРА ═══════════════
def get_user_level(user_id):
    xp = get_xp(user_id)
    return xp // 100  # каждые 100 XP = уровень


def make_xp_bar(user_id):
    """Прогресс-бар XP: ▰▰▰▱▱▱▱▱▱▱"""
    xp = get_xp(user_id)
    level = xp // 100
    progress = xp % 100
    fill = int(progress / 100 * 10)
    bar = "▰" * fill + "▱" * (10 - fill)
    return bar


def get_rank_name(level):
    """Ранг по уровню (римские цифры для делений)."""
    if level < 5:
        return f"🥉 Бронза {['I','II','III'][min(level, 2)]}"
    elif level < 10:
        return "🥈 Серебро III"
    elif level < 15:
        return "🥈 Серебро II"
    elif level < 20:
        return "🥈 Серебро I"
    elif level < 25:
        return "🥇 Золото III"
    elif level < 30:
        return "🥇 Золото II"
    elif level < 35:
        return "🥇 Золото I"
    elif level < 45:
        return "💎 Платина"
    elif level < 55:
        return "💠 Бриллиант"
    else:
        return "🖤 Чёрная карта"


# ═══════════════ REPLY-КЛАВИАТУРЫ ═══════════════
def private_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👑 Профиль")],
            [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="🏆 Топ")],
            [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎰 Кейсы")],
            [KeyboardButton(text="🌐 WebApp")],
            [KeyboardButton(text="🔗 Рефералка"), KeyboardButton(text="🎯 Задания")],
            [KeyboardButton(text="🎮 Как играть?"), KeyboardButton(text="🌐 Язык")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_panel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Игроки")],
            [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="🛒 Контент")],
            [KeyboardButton(text="💰 Экономика")],
            [KeyboardButton(text="📢 Связь"), KeyboardButton(text="📊 Мониторинг")],
            [KeyboardButton(text="🌐 WebApp")],
            [KeyboardButton(text="🛒 Редактор магазина")],
            [KeyboardButton(text="🎰 Редактор кейсов")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ═══════════════ INLINE-КЛАВИАТУРЫ (общие) ═══════════════
def group_url_kb(text="🎮 ИГРАТЬ В ГРУППЕ"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=GROUP_URL)]
    ])


def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


def main_menu_inline_kb():
    """Главное inline-меню."""
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
        [InlineKeyboardButton(text="👑 VIP", callback_data="menu_vip"),
         InlineKeyboardButton(text="⭐ Буст XP", callback_data="menu_xp")],
        [InlineKeyboardButton(text="🎯 Задания", callback_data="menu_quests"),
         InlineKeyboardButton(text="🏆 Турнир", callback_data="menu_tournament")],
        [InlineKeyboardButton(text="🔗 Рефералка", callback_data="menu_ref"),
         InlineKeyboardButton(text="🌐 Язык", callback_data="menu_lang")],
    ])


def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История", callback_data="menu_history"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton(text="🎂 Дата рождения", callback_data="menu_birthday")],
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


def top_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 По балансу", callback_data="top_balance"),
         InlineKeyboardButton(text="⭐ По XP", callback_data="top_xp")],
        [InlineKeyboardButton(text="🎮 По играм", callback_data="top_games"),
         InlineKeyboardButton(text="🏆 По победам", callback_data="top_wins")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


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


def shop_kb():
    items = get_shop_items()
    rows = []
    for i, it in enumerate(items):
        price_parts = []
        if it.get("stars"):
            price_parts.append(f"{it['stars']} ⭐")
        if it.get("tokens"):
            price_parts.append(f"{fmt_num(it['tokens'])} Tokens")
        price = " / ".join(price_parts) if price_parts else "—"
        rows.append([InlineKeyboardButton(
            text=f"{it['name']} — {price}",
            callback_data=f"shop_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="⭐ Буст XP", callback_data="menu_xp")])
    rows.append([InlineKeyboardButton(text="👑 VIP", callback_data="menu_vip")])
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
            text=f"💎 Купить за {fmt_num(it['tokens'])}",
            callback_data=f"shop_buy_tokens_{idx}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


# ═══════════════ VIP-КЛАВИАТУРЫ ═══════════════
def vip_kb():
    tiers = get_vip_tiers()
    rows = []
    for t in tiers:
        rows.append([InlineKeyboardButton(
            text=f"{t['icon']} VIP {t['id']} — {t['name']} — {t['stars']} ⭐",
            callback_data=f"vip_buy_{t['id']}_{t['stars']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ XP-КЛАВИАТУРЫ ═══════════════
def xp_kb():
    packs = get_xp_packs()
    rows = []
    for p in packs:
        rows.append([InlineKeyboardButton(
            text=f"⭐ +{p['xp']} XP — {p['stars']} ⭐",
            callback_data=f"xp_buy_{p['id']}_{p['xp']}_{p['stars']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ═══════════════
def daily_quests_kb(user_id):
    quests = get_user_daily_quests(user_id)
    rows = []
    for q in quests:
        if q["claimed"]:
            rows.append([InlineKeyboardButton(
                text=f"✔️ {q['name']}",
                callback_data="quest_noop"
            )])
        elif q["completed"]:
            rows.append([InlineKeyboardButton(
                text=f"✅ Забрать: {q['name']} (+{fmt_num(q['reward'])})",
                callback_data=f"daily_quest_claim_{q['key']}"
            )])
        else:
            rows.append([InlineKeyboardButton(
                text=f"{q['name']} [{q['progress']}/{q['target']}]",
                callback_data="quest_noop"
            )])
    rows.append([InlineKeyboardButton(text="📋 Награды за уровни", callback_data="menu_level_rewards")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def level_rewards_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_quests")]
    ])


# ═══════════════ ИГРЫ ═══════════════
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


# ═══════════════ ИНВЕНТАРЬ ═══════════════
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
    for it in inv[:10]:
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
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_inventory")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_item_kb(inv_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Использовать", callback_data=f"inv_use_{inv_id}")],
        [InlineKeyboardButton(text="💰 Продать", callback_data=f"inv_sell_{inv_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_inventory")]
    ])


# ═══════════════ РЫНОК ═══════════════
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
        price = f"{fmt_num(lot['price'])} Tokens"
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


# ═══════════════ РЕФКА ═══════════════
def ref_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои рефералы", callback_data="ref_list")],
        [InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="ref_top")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])


# ═══════════════ РУЛЕТКА / БЖ / МИНЫ ═══════════════
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
            text=f"💰 Забрать ×{mult:.2f} ({fmt_num(cashout)})",
            callback_data="mines_cashout"
        )])
    else:
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mines_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════ АДМИН-ПАНЕЛЬ INLINE ═══════════════
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
        [InlineKeyboardButton(text="👑 Редактор VIP", callback_data="editvip_start")],
        [InlineKeyboardButton(text="⭐ Редактор XP", callback_data="editxp_start")],
        [InlineKeyboardButton(text="🎯 Редактор заданий", callback_data="editquest_start")],
        [InlineKeyboardButton(text="🏆 Редактор награды уровней", callback_data="editlevel_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_economy_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Бонус игроку", callback_data="admin_bonus_start")],
        [InlineKeyboardButton(text="💎 Джекпот", callback_data="admin_jackpot")],
        [InlineKeyboardButton(text="🎁 Розыгрыш", callback_data="admin_giveaway_start")],
        [InlineKeyboardButton(text="🏆 Турниры", callback_data="admin_tournament")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_comm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats_show")],
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="📋 Все игроки", callback_data="admin_all_players")],
        [InlineKeyboardButton(text="📋 Покупки", callback_data="admin_purchases")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


def admin_monitor_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Активные", callback_data="admin_active_show")],
        [InlineKeyboardButton(text="🏆 Big Wins", callback_data="admin_bigwins_show")],
        [InlineKeyboardButton(text="📜 Логи игрока", callback_data="admin_logs_start")],
        [InlineKeyboardButton(text="📋 Покупки", callback_data="admin_purchases")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])


# ═══════════════ РЕДАКТОР МАГАЗИНА ═══════════════
def editshop_list_text():
    items = get_shop_items()
    if not items:
        return "🛒 <b>МАГАЗИН</b>\n\nПусто. Нажми ➕ ниже"
    txt = "🛒 <b>РЕДАКТОР МАГАЗИНА</b>\n\n"
    for i, it in enumerate(items, 1):
        prices = []
        if it.get("stars"): prices.append(f"{it['stars']}⭐")
        if it.get("tokens"): prices.append(f"{fmt_num(it['tokens'])}💎")
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
    if it.get("tokens"): prices.append(f"{fmt_num(it['tokens'])} Tokens")
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
         InlineKeyboardButton(text="💎 Цена Tokens", callback_data=f"editshop_field_{idx}_tokens")],
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


# ═══════════════ РЕДАКТОР КЕЙСОВ ═══════════════
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


# ═══════════════ РЕДАКТОР VIP ═══════════════
def editvip_list_text():
    tiers = get_vip_tiers()
    txt = "👑 <b>РЕДАКТОР VIP</b>\n\n"
    for t in tiers:
        txt += (
            f"{t['icon']} <b>VIP {t['id']} — {t['name']}</b>\n"
            f"   Цена: {t['stars']} ⭐ | Кэшбэк: {t['cashback']}% | Бонус: {fmt_num(t['bonus'])} Tokens | Срок: {t['duration_days']} дн.\n\n"
        )
    return txt


def editvip_list_kb():
    tiers = get_vip_tiers()
    rows = []
    for t in tiers:
        rows.append([InlineKeyboardButton(
            text=f"{t['icon']} VIP {t['id']} — {t['name']}",
            callback_data=f"editvip_item_{t['id']}"
        )])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editvip_item_text(tid):
    t = get_vip_tier_info(tid)
    if not t:
        return "❌ VIP не найден"
    return (
        f"{t['icon']} <b>VIP {t['id']} — {t['name']}</b>\n\n"
        f"⭐ Цена: <b>{t['stars']}</b>\n"
        f"💸 Кэшбэк: <b>{t['cashback']}%</b>\n"
        f"🎁 Бонус: <b>{fmt_num(t['bonus'])}</b> Tokens\n"
        f"⏱ Срок: <b>{t['duration_days']}</b> дней\n"
        f"🎰 Эксклюзивных игр: <b>{t['exclusive_games']}</b>\n\n"
        f"👇 Что меняем?"
    )


def editvip_item_kb(tid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Цена", callback_data=f"editvip_field_{tid}_stars"),
         InlineKeyboardButton(text="💸 Кэшбэк", callback_data=f"editvip_field_{tid}_cashback")],
        [InlineKeyboardButton(text="🎁 Бонус", callback_data=f"editvip_field_{tid}_bonus"),
         InlineKeyboardButton(text="⏱ Срок", callback_data=f"editvip_field_{tid}_duration_days")],
        [InlineKeyboardButton(text="🎰 Экскл. игр", callback_data=f"editvip_field_{tid}_exclusive_games")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="editvip_start")]
    ])


# ═══════════════ РЕДАКТОР XP-ПАКОВ ═══════════════
def editxp_list_text():
    packs = get_xp_packs()
    txt = "⭐ <b>РЕДАКТОР БУСТ XP</b>\n\n"
    for p in packs:
        txt += f"• +{p['xp']} XP — {p['stars']} ⭐\n"
    return txt


def editxp_list_kb():
    packs = get_xp_packs()
    rows = []
    for i, p in enumerate(packs):
        rows.append([InlineKeyboardButton(
            text=f"+{p['xp']} XP — {p['stars']} ⭐",
            callback_data=f"editxp_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить пакет", callback_data="editxp_add")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editxp_item_text(idx):
    packs = get_xp_packs()
    if idx < 0 or idx >= len(packs):
        return "❌ Пакет не найден"
    p = packs[idx]
    return (
        f"⭐ <b>Пакет: +{p['xp']} XP</b>\n\n"
        f"💰 Цена: <b>{p['stars']} ⭐</b>\n\n"
        f"👇 Что меняем?"
    )


def editxp_item_kb(idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 XP", callback_data=f"editxp_field_{idx}_xp"),
         InlineKeyboardButton(text="⭐ Цена", callback_data=f"editxp_field_{idx}_stars")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editxp_del_{idx}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="editxp_start")]
    ])


# ═══════════════ РЕДАКТОР ЗАДАНИЙ ═══════════════
def editquest_list_text():
    qs = get_daily_quests()
    txt = "🎯 <b>РЕДАКТОР ЕЖЕДНЕВНЫХ ЗАДАНИЙ</b>\n\n"
    for i, q in enumerate(qs, 1):
        txt += f"{i}. {q['name']} — цель {q['target']} | +{fmt_num(q['reward'])}\n"
    return txt


def editquest_list_kb():
    qs = get_daily_quests()
    rows = []
    for i, q in enumerate(qs):
        rows.append([InlineKeyboardButton(
            text=f"{i+1}. {q['name']}",
            callback_data=f"editquest_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить задание", callback_data="editquest_add")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editquest_item_text(idx):
    qs = get_daily_quests()
    if idx < 0 or idx >= len(qs):
        return "❌ Задание не найдено"
    q = qs[idx]
    return (
        f"🎯 <b>{q['name']}</b>\n\n"
        f"🎯 Цель: <b>{q['target']}</b>\n"
        f"💰 Награда: <b>{fmt_num(q['reward'])}</b> Tokens\n\n"
        f"👇 Что меняем?"
    )


def editquest_item_kb(idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Название", callback_data=f"editquest_field_{idx}_name"),
         InlineKeyboardButton(text="🎯 Цель", callback_data=f"editquest_field_{idx}_target")],
        [InlineKeyboardButton(text="💰 Награда", callback_data=f"editquest_field_{idx}_reward")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editquest_del_{idx}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="editquest_start")]
    ])


# ═══════════════ РЕДАКТОР НАГРАД УРОВНЕЙ ═══════════════
def editlevel_list_text():
    rewards = get_level_rewards()
    txt = "🏆 <b>РЕДАКТОР НАГРАД ЗА УРОВНИ</b>\n\n"
    for i, r in enumerate(rewards, 1):
        if r["type"] == "tokens":
            v = f"+{fmt_num(r['value'])} Tokens"
        elif r["type"] == "cashback":
            v = f"кэшбэк +{r['value']}%"
        elif r["type"] == "vip_games":
            v = "VIP-игры разблокированы"
        elif r["type"] == "vip_tier":
            v = f"VIP {r['value']} бесплатно"
        else:
            v = str(r["value"])
        txt += f"{i}. Уровень {r['level']} — {v}\n"
    return txt


def editlevel_list_kb():
    rewards = get_level_rewards()
    rows = []
    for i, r in enumerate(rewards):
        rows.append([InlineKeyboardButton(
            text=f"Уровень {r['level']}",
            callback_data=f"editlevel_item_{i}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить награду", callback_data="editlevel_add")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_cat_content")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def editlevel_item_text(idx):
    rewards = get_level_rewards()
    if idx < 0 or idx >= len(rewards):
        return "❌ Награда не найдена"
    r = rewards[idx]
    return (
        f"🏆 <b>Уровень {r['level']}</b>\n\n"
        f"📊 Тип: <b>{r['type']}</b>\n"
        f"💰 Значение: <b>{r['value']}</b>\n\n"
        f"👇 Что меняем?"
    )


def editlevel_item_kb(idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Уровень", callback_data=f"editlevel_field_{idx}_level"),
         InlineKeyboardButton(text="💰 Значение", callback_data=f"editlevel_field_{idx}_value")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"editlevel_del_{idx}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="editlevel_start")]
    ])


# ═══════════════ ТЕКСТЫ РЕНДЕРА ═══════════════
def profile_text(user_id, username):
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    level = xp // 100
    rank = get_rank_name(level)
    bar = make_xp_bar(user_id)
    stats = get_user_stats(user_id)
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""

    # VIP
    vip_tier = get_vip_tier(user_id)
    vip_expires = get_vip_expires(user_id)
    if vip_tier > 0:
        info = get_vip_tier_info(vip_tier)
        if info:
            days_left = (vip_expires - datetime.now()).days if vip_expires else 0
            vip_line = f"\n{info['icon']} <b>VIP {info['id']} — {info['name']}</b> ({days_left} дн.)"
        else:
            vip_line = ""
    else:
        vip_line = ""

    # Boost
    boost = get_active_boost(user_id)
    boost_line = ""
    if boost:
        mins_left = int((boost[1] - datetime.now()).total_seconds() // 60)
        boost_line = f"\n⚡ Буст: <b>×{boost[0]}</b> ({mins_left} мин)"

    # Balance
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"<b>{fmt_num(balance)}</b> Tokens"

    # Birthday
    birthday_line = ""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT birthday FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    release_conn(conn)
    if row and row[0]:
        birthday_line = f"\n🎂 День рождения: <b>{row[0]}</b>"

    return (
        f"👤 <b>Профиль</b>\n"
        f"────────────\n"
        f"🎩 Статус: <b>{title or '—'}</b>{title_line if False else ''}\n"
        f"🎖 Ранг: <b>{rank}</b>\n"
        f"📊 Опыт: <b>{xp} / {(level+1)*100} XP</b>\n"
        f"{bar}\n"
        f"────────────\n"
        f"💎 Баланс: {bal_line}\n"
        f"🏦 В банке: <b>{fmt_num(bank)}</b> Tokens\n"
        f"♻️ Кэшбэк: <b>5%</b>{vip_line}{boost_line}{birthday_line}\n"
        f"────────────\n"
        f"🎮 Игр: <b>{stats['total_games']}</b>\n"
        f"🏆 Побед: <b>{stats['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{stats['winrate']}%</b>"
    )


def stats_text(user_id, username):
    s = get_user_stats(user_id)
    profit = s["profit"]
    profit_emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
    return (
        f"📊 <b>Статистика</b>\n"
        f"────────────\n\n"
        f"🎭 <b>{username}</b>\n\n"
        f"🎮 Всего игр: <b>{s['total_games']}</b>\n"
        f"🏆 Побед: <b>{s['total_wins']}</b>\n"
        f"📈 Винрейт: <b>{s['winrate']}%</b>\n\n"
        f"💰 Ставок: <b>{fmt_num(s['total_bet'])}</b>\n"
        f"💵 Выигрышей: <b>{fmt_num(s['total_win'])}</b>\n"
        f"{profit_emoji} Профит: <b>{'+' if profit >= 0 else ''}{fmt_num(profit)}</b>\n"
        f"🔥 Best: <b>{fmt_num(s['best_win'])}</b>\n\n"
        f"🎯 Любимая: <b>{s['fav_game']}</b>"
    )


def history_text(user_id, username, game=None):
    logs = get_user_history(user_id, game=game, limit=15)
    title = f"📜 История: {game}" if game else "📜 История игр"
    if not logs:
        return f"{title}\n\nПока пусто..."
    txt = f"{title}\n\n"
    for i, (g, bet, win, detail, time) in enumerate(logs, 1):
        profit = win - bet
        emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
        txt += f"{i}. {emoji} <b>{g}</b> | {fmt_num(bet)} → {fmt_num(win)} | {time}\n"
    return txt


def top_text(mode="balance"):
    if mode == "balance":
        rows = get_top(10); title = "💎 ТОП по БАЛАНСУ"
        def metric(r): return f"<b>{fmt_num(r[2])}</b> Tokens"
    elif mode == "xp":
        rows = get_top_xp(10); title = "⭐ ТОП по XP"
        def metric(r): return f"<b>{fmt_num(r[3] or 0)} XP</b>"
    elif mode == "games":
        rows = get_top_games(10); title = "🎮 ТОП по ИГРАМ"
        def metric(r): return f"<b>{r[4]} игр</b>"
    elif mode == "wins":
        rows = get_top_wins(10); title = "🏆 ТОП по ПОБЕДАМ"
        def metric(r): return f"<b>{r[4]} побед</b>"
    else:
        rows = get_top(10); title = "🏆 ТОП-10"
        def metric(r): return f"<b>{fmt_num(r[2])}</b> Tokens"

    if not rows:
        return f"🏆 <b>{title}</b>\n\nПока нет игроков!"

    txt = f"🏆 <b>{title}</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        uid, uname = row[0], row[1]
        xp = row[3] or 0
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        t = get_main_title(uid)
        title_str = f" 🏷️{t}" if t else ""
        txt += f"{medal} {uname}{title_str} — {metric(row)}\n"
    return txt


def bank_text(user_id, username):
    balance = get_balance(user_id)
    bank = get_bank(user_id)
    total = clamp(balance + bank)
    daily_interest = int(bank * 0.05) if bank > 0 else 0
    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"<b>{fmt_num(balance)}</b> Tokens"
    return (
        f"🏦 <b>Банк</b>\n"
        f"────────────\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"💎 Баланс: {bal_line}\n"
        f"🏦 В банке: <b>{fmt_num(bank)}</b> Tokens\n"
        f"📊 Всего: <b>{fmt_num(total)}</b> Tokens\n\n"
        f"📈 Проценты:\n"
        f"💵 Ставка: <b>5% в день</b>\n"
        f"🎁 За сутки: <b>+{fmt_num(daily_interest)}</b> Tokens\n\n"
        f"👇 Выбери действие:"
    )


def shop_text():
    items = get_shop_items()
    if not items:
        return "🛒 <b>МАГАЗИН</b>\n\nПока пусто..."
    txt = "🛒 <b>Магазин</b>\n"
    txt += "────────────\n\n"
    txt += "<i>Бусты, титулы, VIP</i>\n\n"
    for it in items:
        price_parts = []
        if it.get("stars"):
            price_parts.append(f"{it['stars']} ⭐")
        if it.get("tokens"):
            price_parts.append(f"{fmt_num(it['tokens'])} Tokens")
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
        price_parts.append(f"{fmt_num(it['tokens'])} Tokens")
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
    txt = "🎰 <b>Кейсы</b>\n"
    txt += "────────────\n\n"
    for c in cases:
        txt += f"{c['name']} — {c['stars']} ⭐\n"
    txt += "\n💎 Покупка за Telegram Stars\n🎁 Внутри — бусты, титулы, VIP\n\n👇 Выбери кейс:"
    return txt


def vip_text(user_id):
    tiers = get_vip_tiers()
    current = get_vip_tier(user_id)
    expires = get_vip_expires(user_id)
    txt = "👑 <b>VIP КЛУБ</b>\n"
    txt += "────────────\n\n"
    if current > 0 and expires:
        info = get_vip_tier_info(current)
        days = (expires - datetime.now()).days
        txt += f"Твой статус: {info['icon']} <b>VIP {info['id']} — {info['name']}</b>\n"
        txt += f"⏱ Осталось: <b>{days}</b> дней\n\n"
    else:
        txt += "Твой статус: <b>Нет VIP</b>\n\n"
    txt += "<b>Доступные VIP:</b>\n\n"
    for t in tiers:
        txt += (
            f"{t['icon']} <b>VIP {t['id']} — {t['name']}</b> — {t['stars']} ⭐\n"
            f"   💸 Кэшбэк {t['cashback']}%\n"
            f"   🎁 Бонус +{fmt_num(t['bonus'])} Tokens\n"
            f"   ⏱ Срок {t['duration_days']} дней\n\n"
        )
    txt += "👇 Выбери VIP:"
    return txt


def xp_text(user_id):
    packs = get_xp_packs()
    xp = get_xp(user_id)
    level = xp // 100
    txt = "⭐ <b>Буст XP</b>\n"
    txt += "────────────\n\n"
    txt += f"📊 Твой XP: <b>{fmt_num(xp)}</b>\n"
    txt += f"🎖 Уровень: <b>{level}</b>\n"
    txt += f"{make_xp_bar(user_id)}\n\n"
    txt += "<b>Доступные пакеты:</b>\n\n"
    for p in packs:
        txt += f"• +{p['xp']} XP — <b>{p['stars']} ⭐</b>\n"
    txt += "\n👇 Выбери пакет:"
    return txt


def quests_text(user_id):
    quests = get_user_daily_quests(user_id)
    txt = "🎯 <b>Ежедневные задания</b>\n"
    txt += "────────────\n\n"
    for q in quests:
        if q["claimed"]:
            txt += f"✔️ {q['name']}\n"
        elif q["completed"]:
            txt += f"✅ {q['name']} → Забрать!\n"
        else:
            txt += f"⬜ {q['name']} [{q['progress']}/{q['target']}]\n"
    txt += "\n💡 Задания обновляются раз в 24 часа"
    return txt


def level_rewards_text():
    rewards = get_level_rewards()
    txt = "🏆 <b>Награды за уровни</b>\n"
    txt += "────────────\n\n"
    for r in rewards:
        if r["type"] == "tokens":
            v = f"+{fmt_num(r['value'])} Tokens"
        elif r["type"] == "cashback":
            v = f"кэшбэк +{r['value']}%"
        elif r["type"] == "vip_games":
            v = "VIP-игры"
        elif r["type"] == "vip_tier":
            v = f"VIP {r['value']} бесплатно"
        else:
            v = str(r["value"])
        txt += f"🏆 Уровень <b>{r['level']}</b> — {v}\n"
    return txt


def tournament_text():
    t = get_active_tournament()
    if not t:
        return (
            "🏆 <b>Турнир</b>\n"
            "────────────\n\n"
            "😴 Сейчас нет активного турнира\n\n"
            "Следи за анонсами в канале:\n"
            f"{TOURNAMENT_CHANNEL}"
        )
    tid, name, started, ends, p1, p2, p3 = t
    top = get_tournament_top(tid, 10)
    txt = f"🏆 <b>{name}</b>\n"
    txt += "────────────\n\n"
    txt += f"⏱ До: <b>{ends.strftime('%d.%m %H:%M')}</b>\n\n"
    txt += f"🥇 1 место — <b>{fmt_num(p1)}</b> Tokens\n"
    txt += f"🥈 2 место — <b>{fmt_num(p2)}</b> Tokens\n"
    txt += f"🥉 3 место — <b>{fmt_num(p3)}</b> Tokens\n\n"
    txt += "📊 <b>Топ-10:</b>\n\n"
    if not top:
        txt += "Пока никто не играл"
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, total) in enumerate(top):
            m = medals[i] if i < 3 else f"{i+1}."
            txt += f"{m} {uname} — {fmt_num(total)} Tokens\n"
    return txt


def inventory_text(user_id, filter_type=None):
    inv = get_inventory(user_id)
    if filter_type:
        inv = [it for it in inv if it.get("type") == filter_type]
    title_map = {
        None: "🎒 Инвентарь",
        "boost": "⚡ Мои бусты",
        "title": "🏷️ Мои титулы",
        "vip": "👑 Мои VIP",
        "case": "🎰 Мои кейсы",
    }
    title = title_map.get(filter_type, "🎒 Инвентарь")
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


def market_text():
    lots = get_market_lots()
    txt = "🏪 <b>Рынок</b>\n"
    txt += "────────────\n\n"
    txt += f"📊 Активных лотов: <b>{len(lots)}</b>\n\n"
    txt += "👇 Выбери раздел:"
    return txt


def ref_text(user_id, username):
    count, earnings = get_ref_stats(user_id)
    try:
        bot_username = "gold1_casino_bot"
    except Exception:
        bot_username = "gold1_casino_bot"
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    return (
        f"🔗 <b>Реферальная система</b>\n"
        f"────────────\n\n"
        f"👤 <b>{username}</b>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{fmt_num(earnings)}</b> Tokens\n\n"
        f"🎁 За каждого друга: <b>+{fmt_num(REF_BONUS_REFERRER)}</b> тебе и ему\n"
        f"📈 +5% с его выигрышей\n\n"
        f"🔗 Твоя ссылка:\n"
        f"<code>{link}</code>"
    )


def purchases_text(limit=20):
    rows = get_purchases(limit)
    if not rows:
        return "📋 <b>Покупок пока нет</b>"
    txt = "📋 <b>Последние покупки</b>\n"
    txt += "────────────\n\n"
    for uid, uname, ptype, iname, price, source, created in rows:
        time_str = created.strftime("%d.%m %H:%M") if created else "—"
        txt += (
            f"👤 @{uname or f'id{uid}'}\n"
            f"💎 {iname} — {price}\n"
            f"📍 {source} | 🕐 {time_str}\n\n"
        )
    return txt


# ═══════════════ ЯЗЫКОВЫЕ СЛОВАРИ ═══════════════
LANG_TEXTS = {
    "ru": {
        "menu": "Главное меню",
        "back": "🔙 Назад",
        "cancel": "❌ Отмена",
    },
    "en": {
        "menu": "Main menu",
        "back": "🔙 Back",
        "cancel": "❌ Cancel",
    },
}


def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")]
    ])
    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 5/6 — HANDLERS, КОМАНДЫ, ПОКУПКИ, ФОНОВЫЕ ЦИКЛЫ
# ═══════════════════════════════════════════════════════════════

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

    # ─── Обработка реферальной ссылки ───
    args = message.text.split()
    if len(args) >= 2 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                ok = set_referrer(user_id, referrer_id)
                if ok:
                    await message.answer(
                        f"🎉 <b>Ты пришёл по приглашению!</b>\n\n"
                        f"💰 Тебе начислено <b>+{fmt_num(REF_BONUS_REFERRED)}</b> Tokens\n"
                        f"👤 Пригласивший тоже получил бонус",
                        parse_mode="HTML"
                    )
        except Exception:
            pass

    # ─── Ежедневный вход (streak) ───
    streak, bonus = check_daily_login(user_id)
    if bonus > 0:
        await message.answer(
            f"🔥 <b>7 дней подряд!</b>\n\n"
            f"🎁 Жирный бонус: <b>+{fmt_num(bonus)}</b> Tokens",
            parse_mode="HTML"
        )

    is_private = message.chat.type == 'private'

    # ─── Админ в личке ───
    if is_private and user_id == ADMIN_ID:
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        txt = (
            f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
            f"────────────\n\n"
            f"👤 <b>{username}</b>\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n\n"
            f"📋 <b>Выбери раздел:</b>"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
        return

    # ─── Бонус новичка ───
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
        bonus_text = f"\n\n🎁 <b>БОНУС НОВИЧКА: +{fmt_num(5000)} Tokens!</b>"

    balance = get_balance(user_id)
    bank = get_bank(user_id)
    xp = get_xp(user_id)
    level = xp // 100
    rank = get_rank_name(level)
    title = get_main_title(user_id)
    title_line = f"\n🏷️ <b>{title}</b>" if title else ""

    vip_tier = get_vip_tier(user_id)
    vip_line = ""
    if vip_tier > 0:
        info = get_vip_tier_info(vip_tier)
        if info:
            vip_line = f"\n{info['icon']} <b>VIP {info['id']} — {info['name']}</b>"

    if is_unlimited(user_id):
        bal_line = "♾️ <b>БЕЗЛИМИТ</b>"
    else:
        bal_line = f"💎 <b>{fmt_num(balance)}</b> Tokens"

    if is_private:
        txt = (
            f"🎰 <b>ДОБРО ПОЖАЛОВАТЬ В ТОКЕНЫ!</b>\n"
            f"────────────\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"🎖 {rank}{vip_line}{title_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b>{bonus_text}\n\n"
            f"🎮 <b>Что умеет бот:</b>\n"
            f"🎮 <b>Игры</b> — рулетка, слоты, мины, блэкджек, монетка, дуэль\n"
            f"🎁 <b>Бонус</b> — +{fmt_num(DAILY_BONUS)} Tokens раз в 24ч\n"
            f"🎰 <b>Кейсы</b> — за ⭐ Stars: бусты, титулы, VIP\n"
            f"🛒 <b>Магазин</b> — покупки за ⭐ Stars и Tokens\n"
            f"🎒 <b>Инвентарь</b> — все твои предметы\n"
            f"🏪 <b>Рынок</b> — продай друзьям\n"
            f"🎯 <b>Задания</b> — ежедневные квесты\n"
            f"👑 <b>VIP</b> — эксклюзивные привилегии\n"
            f"🔗 <b>Рефка</b> — приглашай друзей\n\n"
            f"💡 <b>Играть нужно в группе!</b>\n"
            f"Жми кнопку ниже 👇"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=private_kb())
    else:
        txt = (
            f"🎰 <b>ТОКЕНЫ</b>\n"
            f"────────────\n\n"
            f"👋 Привет, <b>{username}</b>!\n"
            f"🎖 {rank}{vip_line}{title_line}\n"
            f"{bal_line}\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b>{bonus_text}\n\n"
            f"🎮 Нажми <b>Игры</b>!\n\n"
            f"<code>б</code> — баланс | <code>топ</code> — топ\n"
            f"<code>профиль</code> — профиль | <code>задания</code> — задания\n"
            f"<code>банк</code> — банк | <code>дуэль 1000 @user</code>\n"
            f"<code>мины 100</code> — Мины 💣 | <code>бж 100</code> — блэкджек\n"
            f"<code>спин 100</code> — слоты | <code>орёл 100</code> — монетка\n"
            f"<code>к/ч/з 100</code> — рулетка | <code>го</code> — запуск"
        )
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu_inline_kb())


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
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n"
        f"────────────\n\n"
        f"👤 <b>{username}</b>\n"
        f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
        f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n\n"
        f"📋 <b>Выбери раздел:</b>"
    )
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
        await message.answer(f"✅ <b>+{fmt_num(amount)}</b> → @{username}\n💎 {fmt_num(nb)}", parse_mode="HTML")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
        await message.answer("❌ Ответь на сообщение игрока или: <code>/give @user сумма</code>", parse_mode="HTML")
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
    await message.answer(f"✅ <b>+{fmt_num(amount)}</b> → {target.username or target.first_name}\n💎 {fmt_num(nb)}", parse_mode="HTML")


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
        await message.answer(f"✅ <b>Забрано всё!</b> -{fmt_num(tb)}", parse_mode="HTML")
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
        await message.answer(f"✅ <b>-{fmt_num(amount)}</b> ← @{username}\n💎 {fmt_num(nb)}", parse_mode="HTML")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
        await message.answer("❌ Ответь на сообщение игрока", parse_mode="HTML")
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
    await message.answer(f"✅ <b>-{fmt_num(amount)}</b> ← {target.username or target.first_name}\n💎 {fmt_num(nb)}", parse_mode="HTML")


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
        txt = (
            f"📊 <b>СТАТИСТИКА ИГРОКА</b>\n\n"
            f"👤 {uname} (<code>{uid}</code>)\n"
            f"⭐ XP: {xp or 0}\n"
            f"💎 Баланс: <b>{fmt_num(bal)}</b>\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b>\n\n"
            f"🎮 Игр: <b>{tg}</b>\n"
            f"🏆 Побед: <b>{tw}</b>"
        )
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
        f"💎 Tokens: <b>{fmt_num(total_balance)}</b>\n"
        f"🎮 Игр: <b>{total_games}</b>\n\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"♾️ Безлимитов: <b>{unlimited_count}</b>"
    )
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
        await message.answer(f"🎁 <b>+{fmt_num(amount)} всем!</b>\n👥 {count}", parse_mode="HTML")
        return
    if target.startswith('@'):
        username = target[1:]
        uid = get_user_id_by_username(username)
        if not uid:
            await message.answer(f"❌ @{username} не найден", parse_mode="HTML")
            return
        nb = set_balance(uid, amount)
        await message.answer(f"🎁 <b>+{fmt_num(amount)}</b> → @{username}\n💎 {fmt_num(nb)}", parse_mode="HTML")


# ═══════════════ /jackpot ═══════════════
@dp.message(Command("jackpot"))
async def cmd_jackpot(message: Message):
    global jackpot_amount
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer(f"💎 <b>ДЖЕКПОТ</b>: <b>{fmt_num(get_jackpot())}</b>", parse_mode="HTML")
        return
    sub = args[1].lower()
    if sub == "set" and len(args) >= 3:
        try:
            amount = int(args[2])
        except Exception:
            return
        save_jackpot(amount)
        await message.answer(f"💎 <b>Установлен</b>: {fmt_num(amount)}", parse_mode="HTML")
    elif sub == "reset":
        reset_jackpot()
        await message.answer("💎 <b>Сброшен</b>: 10 000", parse_mode="HTML")


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
            f"💰 <b>Баланс</b>\n\n👤 {username}\n♾️ <b>БЕЗЛИМИТ</b>\n🏦 Банк: <b>{fmt_num(bank)}</b>",
            parse_mode="HTML")
    else:
        await message.answer(
            f"💰 <b>Баланс</b>\n\n👤 {username}\n💎 Баланс: <b>{fmt_num(balance)}</b>\n🏦 Банк: <b>{fmt_num(bank)}</b>",
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
    await message.answer(ref_text(user_id, username), parse_mode="HTML", reply_markup=ref_kb())


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


# ═══════════════ /vip ═══════════════
@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        return
    await message.answer(vip_text(user_id), parse_mode="HTML", reply_markup=vip_kb())


# ═══════════════ /xp ═══════════════
@dp.message(Command("xp"))
async def cmd_xp(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        return
    await message.answer(xp_text(user_id), parse_mode="HTML", reply_markup=xp_kb())


# ═══════════════ /quests ═══════════════
@dp.message(Command("quests", "задания"))
async def cmd_quests(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)
    if is_banned(user_id):
        return
    await message.answer(quests_text(user_id), parse_mode="HTML", reply_markup=daily_quests_kb(user_id))


# ═══════════════ /tournament ═══════════════
@dp.message(Command("tournament", "турнир"))
async def cmd_tournament(message: Message):
    await message.answer(tournament_text(), parse_mode="HTML")


# ═══════════════ /lang ═══════════════
@dp.message(Command("lang", "язык"))
async def cmd_lang(message: Message):
    await message.answer(
        "🌐 <b>Выбор языка</b>\n\n👇 Выбери язык интерфейса:",
        parse_mode="HTML",
        reply_markup=lang_kb()
    )


# ═══════════════ /purchases (админ) ═══════════════
@dp.message(Command("purchases"))
async def cmd_purchases(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(purchases_text(20), parse_mode="HTML")


# ═══════════════ REPLY-КНОПКИ ═══════════════
@dp.message(F.text == "👑 Профиль")
async def btn_profile(message: Message):
    await cmd_profile(message)


@dp.message(F.text == "🎁 Бонус")
async def btn_bonus(message: Message):
    user_id = message.from_user.id
    if is_banned(user_id):
        return
    can, left = get_daily_status(user_id)
    if can:
        claim_daily(user_id)
        nb = get_balance(user_id)
        await message.answer(
            f"🎁 <b>Ежедневный бонус</b>\n"
            f"────────────\n\n"
            f"Вы получили: <b>+{fmt_num(DAILY_BONUS)}</b> Tokens\n"
            f"Ваш баланс: <b>{fmt_num(nb)}</b> Tokens\n\n"
            f"Возвращайтесь завтра за новым бонусом! 🔥",
            parse_mode="HTML"
        )
    else:
        await message.answer(f"⏳ Приходи через <b>{fmt_time_left(left)}</b>", parse_mode="HTML")


@dp.message(F.text == "🏆 Топ")
async def btn_top(message: Message):
    await cmd_top(message)


@dp.message(F.text == "🎁 Донат" or F.text == "💰 Донат")
async def btn_donate(message: Message):
    await message.answer(
        f"⭐ <b>ДОНАТ</b>\n"
        f"────────────\n\n"
        f"⭐ <b>Покупки за Telegram Stars</b>\n"
        f"🎁 Пакеты бустов в магазине\n"
        f"👑 VIP-статусы\n"
        f"⭐ Буст XP\n\n"
        f"────────────\n\n"
        f"👉 Открой WebApp → 🛒 Магазин",
        parse_mode="HTML"
    )


@dp.message(F.text == "🔗 Рефералка")
async def btn_ref(message: Message):
    await cmd_ref(message)


@dp.message(F.text == "🎯 Задания" or F.text == "🎯 Квесты")
async def btn_quests(message: Message):
    await cmd_quests(message)


@dp.message(F.text == "🎮 Как играть?")
async def btn_howto(message: Message):
    await message.answer(
        f"🎮 <b>Как играть</b>\n"
        f"────────────\n\n"
        f"📌 <b>В группе:</b>\n"
        f"<code>спин 100</code>, <code>к 100</code>, <code>мины 100</code>\n\n"
        f"📌 <b>В Mini App:</b>\n"
        f"WebApp → 🎮 Игры\n\n"
        f"🎁 <b>Бонусы:</b>\n"
        f"Ежедневный +{fmt_num(DAILY_BONUS)} Tokens",
        parse_mode="HTML"
    )


@dp.message(F.text == "🛒 Магазин")
async def btn_shop(message: Message):
    await cmd_shop(message)


@dp.message(F.text == "🎰 Кейсы")
async def btn_cases(message: Message):
    await cmd_cases(message)


@dp.message(F.text == "🌐 Язык")
async def btn_lang(message: Message):
    await cmd_lang(message)


# ═══════════════ КНОПКА WebApp (ФИКС!) ═══════════════
@dp.message(F.text == "🌐 WebApp")
async def btn_webapp(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🌐 Открыть Mini App",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])
    await message.answer(
        "🌐 <b>Mini App</b>\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть казино:",
        parse_mode="HTML",
        reply_markup=kb
    )


# ═══════════════ АДМИН REPLY-КНОПКИ ═══════════════
@dp.message(F.text == "👥 Игроки")
async def btn_admin_players(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, balance, banned FROM users ORDER BY balance DESC LIMIT 20")
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.close()
    release_conn(conn)
    medals = ["🥇", "🥈", "🥉"]
    txt = f"👥 <b>Игроки ({total})</b>\n"
    txt += "═══════════════\n"
    for i, row in enumerate(rows):
        uid, uname, bal, is_b = row
        medal = medals[i] if i < 3 else f"{i+1}."
        ban = " 🚫" if is_b else ""
        txt += f"{medal} {uname or f'user_{uid}'} — <b>{fmt_num(bal)}</b>{ban}\n"
    await message.answer(txt, parse_mode="HTML")


@dp.message(F.text == "🎮 Игры")
async def btn_admin_games(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай кнопками:",
        parse_mode="HTML",
        reply_markup=admin_games_kb()
    )


@dp.message(F.text == "🛒 Контент")
async def btn_admin_content(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🛒 <b>УПРАВЛЕНИЕ КОНТЕНТОМ</b>\n\n👇 Выбери редактор:",
        parse_mode="HTML",
        reply_markup=admin_content_kb()
    )


@dp.message(F.text == "💰 Экономика")
async def btn_admin_economy(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "💰 <b>ЭКОНОМИКА</b>\n\n👇 Выбери действие:",
        parse_mode="HTML",
        reply_markup=admin_economy_kb()
    )


@dp.message(F.text == "📢 Связь")
async def btn_admin_comm(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📢 <b>СВЯЗЬ</b>\n\n👇 Выбери действие:",
        parse_mode="HTML",
        reply_markup=admin_comm_kb()
    )


@dp.message(F.text == "📊 Мониторинг")
async def btn_admin_monitor(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📊 <b>МОНИТОРИНГ</b>\n\n👇 Выбери действие:",
        parse_mode="HTML",
        reply_markup=admin_monitor_kb()
    )


@dp.message(F.text == "🛒 Редактор магазина")
async def btn_admin_edit_shop(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())


@dp.message(F.text == "🎰 Редактор кейсов")
async def btn_admin_edit_cases(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())


# ═══════════════ PRE-CHECKOUT / SUCCESSFUL PAYMENT ═══════════════
@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    ensure_user(user_id, username)

    # ─── БУСТ (старый формат) ───
    if payload.startswith("boost_"):
        parts = payload.split("_")
        try:
            mult = int(parts[1]); minutes = int(parts[2])
        except Exception:
            await message.answer("❌ Ошибка буста", parse_mode="HTML")
            return
        until = add_boost(user_id, mult, minutes)
        await message.answer(
            f"✅ <b>БУСТ АКТИВИРОВАН!</b>\n\n"
            f"⚡ Множитель: <b>×{mult}</b>\n"
            f"⏱️ До: <b>{(until + timedelta(hours=3)).strftime('%H:%M:%S')}</b>",
            parse_mode="HTML"
        )
        log_purchase(user_id, username, "stars", f"Буст ×{mult} на {minutes} мин", f"{message.successful_payment.total_amount} ⭐", "Бот")
        await notify_admin_purchase(user_id, username, "stars", f"Буст ×{mult} на {minutes} мин", f"{message.successful_payment.total_amount} ⭐", "Бот")
        return

    # ─── МАГАЗИН — за Stars ───
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
            f"✅ <b>КУПЛЕНО!</b>\n\n🎁 {reward_text}\n\n📦 Предмет в инвентаре!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop")]
            ])
        )
        price_str = f"{message.successful_payment.total_amount} ⭐"
        log_purchase(user_id, username, "stars", it["name"], price_str, "Бот")
        await notify_admin_purchase(user_id, username, "stars", it["name"], price_str, "Бот")
        return

    # ─── КЕЙС ───
    if payload.startswith("case_"):
        case_id = payload.replace("case_", "")
        case = get_case_by_id(case_id)
        if not case:
            await message.answer("❌ Кейс не найден", parse_mode="HTML")
            return
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
        reward_text = apply_case_reward_to_inventory(user_id, reward)
        save_last_reward(user_id, {
            "type": reward.get("type"),
            "mult": reward.get("mult"),
            "minutes": reward.get("minutes"),
            "title": reward.get("title"),
            "vip_level": reward.get("vip_level"),
            "case_name": case.get("name", ""),
        })
        inv = get_inventory(user_id)
        last_inv_id = inv[-1].get("inv_id") if inv else None
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Использовать сейчас", callback_data=f"case_use_{last_inv_id}"),
             InlineKeyboardButton(text="📦 Оставить на полке", callback_data="case_keep")],
            [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")]
        ])
        await msg.edit_text(
            f"🎉 <b>КЕЙС «{case['name']}» ОТКРЫТ!</b>\n\n"
            f"🎁 Тебе выпало:\n<b>{reward_text}</b>\n\n"
            f"👇 Что делаем?",
            parse_mode="HTML",
            reply_markup=kb
        )
        price_str = f"{message.successful_payment.total_amount} ⭐"
        log_purchase(user_id, username, "case", f"Кейс «{case['name']}» → {reward_text}", price_str, "Бот")
        await notify_admin_purchase(user_id, username, "case", f"Кейс «{case['name']}»", price_str, "Бот", extra=f"Выпало: {reward_text}")
        return

    # ─── VIP ───
    if payload.startswith("vip_"):
        parts = payload.split("_")
        try:
            tid = int(parts[1]); stars = int(parts[2])
        except Exception:
            await message.answer("❌ Ошибка VIP", parse_mode="HTML")
            return
        info = get_vip_tier_info(tid)
        if not info:
            await message.answer("❌ VIP не найден", parse_mode="HTML")
            return
        set_vip_tier(user_id, tid, info["duration_days"])
        set_balance(user_id, info["bonus"])
        nb = get_balance(user_id)
        await message.answer(
            f"✅ <b>VIP АКТИВИРОВАН!</b>\n"
            f"────────────\n\n"
            f"{info['icon']} <b>VIP {info['id']} — {info['name']}</b>\n"
            f"⏱ Срок: <b>{info['duration_days']}</b> дней\n"
            f"💸 Кэшбэк: <b>{info['cashback']}%</b>\n"
            f"🎁 Бонус: <b>+{fmt_num(info['bonus'])}</b> Tokens\n"
            f"💎 Баланс: <b>{fmt_num(nb)}</b>",
            parse_mode="HTML"
        )
        price_str = f"{stars} ⭐"
        log_purchase(user_id, username, "stars", f"VIP {tid} — {info['name']}", price_str, "Бот")
        await notify_admin_purchase(user_id, username, "stars", f"VIP {tid} — {info['name']}", price_str, "Бот")
        # Обновляем задание "Купить VIP"
        update_daily_quest(user_id, "daily_buy_vip", 1)
        return

    # ─── XP-ПАК ───
    if payload.startswith("xp_"):
        parts = payload.split("_")
        try:
            pack_id = parts[1]
            xp_amount = int(parts[2]); stars = int(parts[3])
        except Exception:
            await message.answer("❌ Ошибка пакета", parse_mode="HTML")
            return
        old_xp = get_xp(user_id)
        new_xp, level_changed, new_level = add_xp(user_id, xp_amount)
        rewards_given = []
        if level_changed:
            rewards_given = check_level_rewards(user_id, new_level)
        txt = (
            f"✅ <b>БУСТ XP КУПЛЕН!</b>\n"
            f"────────────\n\n"
            f"📊 +<b>{fmt_num(xp_amount)}</b> XP\n"
            f"🎖 Уровень: <b>{new_level}</b>\n"
        )
        if rewards_given:
            txt += "\n🎁 <b>Награды:</b>\n" + "\n".join(rewards_given)
        await message.answer(txt, parse_mode="HTML")
        price_str = f"{stars} ⭐"
        log_purchase(user_id, username, "stars", f"Буст XP +{xp_amount}", price_str, "Бот")
        await notify_admin_purchase(user_id, username, "stars", f"Буст XP +{xp_amount}", price_str, "Бот")
        return

    print(f"⚠️ Неизвестный payload: {payload}")
    await message.answer("✅ Оплата получена!")


# ═══════════════ CASE: USE / KEEP ═══════════════
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
            "📦 <b>ПРЕДМЕТ НА ПОЛКЕ</b>\n\nОн в твоём инвентаре. Активируешь, когда захочешь.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                [InlineKeyboardButton(text="🎰 Ещё кейс", callback_data="menu_cases")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
            ])
        )
    except Exception:
        pass


# ═══════════════ АДМИН: ДЖЕКПОТ ═══════════════
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
        f"💰 Текущий: <b>{fmt_num(jp)}</b>\n\n"
        f"💡 Пополняется:\n"
        f"• 1% со ставок рулетки\n"
        f"• 5% с рынка\n\n"
        f"🎯 Срывается: 🟢 Зеро в рулетке"
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
    await call.answer(f"✅ Сброшен с {fmt_num(old)} до 10 000", show_alert=True)


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


# ═══════════════ АДМИН: ТУРНИРЫ ═══════════════
@dp.callback_query(F.data == "admin_tournament")
async def admin_tournament_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    t = get_active_tournament()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Запустить турнир (7 дней)", callback_data="admin_tournament_start")],
        [InlineKeyboardButton(text="⏹ Завершить текущий", callback_data="admin_tournament_finish")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    if t:
        txt = (
            f"🏆 <b>ТУРНИРЫ</b>\n\n"
            f"✅ Активный: <b>{t[1]}</b>\n"
            f"⏱ До: <b>{t[3].strftime('%d.%m %H:%M')}</b>\n"
        )
    else:
        txt = "🏆 <b>ТУРНИРЫ</b>\n\n😴 Нет активного турнира"
    await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data == "admin_tournament_start")
async def admin_tournament_start_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    tid, ends_at = start_tournament(f"🏆 Турнир недели #{tid}" if False else "🏆 Турнир недели", 168)
    await call.answer(f"✅ Турнир запущен до {ends_at.strftime('%d.%m %H:%M')}", show_alert=True)
    # Анонс в канал
    try:
        await bot.send_message(
            TOURNAMENT_CHANNEL,
            f"🏆 <b>НОВЫЙ ТУРНИР!</b>\n"
            f"────────────\n\n"
            f"🥇 1 место — <b>10 000</b> Tokens\n"
            f"🥈 2 место — <b>5 000</b> Tokens\n"
            f"🥉 3 место — <b>2 000</b> Tokens\n\n"
            f"⏱ До: <b>{ends_at.strftime('%d.%m %H:%M')}</b>\n\n"
            f"Участвуй: @gold1_casino_bot",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[tournament announce] {e}")


@dp.callback_query(F.data == "admin_tournament_finish")
async def admin_tournament_finish_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    t = get_active_tournament()
    if not t:
        await call.answer("❌ Нет активного турнира", show_alert=True)
        return
    winners = finish_tournament(t[0])
    if winners:
        txt = "🏆 <b>ТУРНИР ЗАВЕРШЁН!</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, uname, prize) in enumerate(winners):
            txt += f"{medals[i]} {uname} — {fmt_num(prize)} Tokens\n"
        await call.answer("✅ Турнир завершён", show_alert=True)
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
        try:
            await bot.send_message(TOURNAMENT_CHANNEL, txt, parse_mode="HTML")
        except Exception:
            pass
    else:
        await call.answer("❌ Ошибка", show_alert=True)


# ═══════════════ АДМИН: ПОКУПКИ ═══════════════
@dp.callback_query(F.data == "admin_purchases")
async def admin_purchases_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌", show_alert=True)
        return
    await call.message.edit_text(purchases_text(20), parse_mode="HTML", reply_markup=admin_back_kb())
    await call.answer()


# ═══════════════ ФОНОВЫЕ ЦИКЛЫ ═══════════════
async def bank_interest_loop():
    while True:
        await asyncio.sleep(86400)
        try:
            accrue_bank_interest()
            print("🏦 Проценты банка начислены")
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
                from_chunk = True
                conn = get_conn()
                c = conn.cursor()
                c.execute("SELECT user_id, amount FROM giveaways WHERE id = %s AND status = 'active'", (gid,))
                row = c.fetchone()
                if not row:
                    c.close(); release_conn(conn); continue
                uid, amount = row
                c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, uid))
                c.execute("UPDATE giveaways SET status = 'finished', winner_id = %s WHERE id = %s", (uid, gid))
                conn.commit()
                c.close()
                release_conn(conn)
                try:
                    await bot.send_message(uid, f"🎉 Ты выиграл розыгрыш! +{fmt_num(amount)} Tokens", parse_mode="HTML")
                except Exception:
                    pass
        except Exception as e:
            print(f"Ошибка giveaway: {e}")


async def cashback_loop():
    """Кэшбэк 5% от проигрышей за день, каждый день в 00:00 UTC."""
    while True:
        try:
            now = datetime.utcnow()
            # Время до следующего 00:00 UTC
            next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            wait_seconds = (next_midnight - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            # Начисляем
            paid = pay_daily_cashback()
            print(f"💸 Кэшбэк начислен {paid} игрокам")
            # Уведомления
            # (отдельно не шлём, чтобы не спамить — можно включить при желании)
        except Exception as e:
            print(f"[cashback_loop] {e}")
            await asyncio.sleep(3600)


async def tournament_checker_loop():
    """Проверяет, не закончился ли турнир."""
    while True:
        await asyncio.sleep(300)  # каждые 5 минут
        try:
            t = get_active_tournament()
            if t and t[3] and t[3] <= datetime.now():
                winners = finish_tournament(t[0])
                if winners:
                    txt = "🏆 <b>ТУРНИР ЗАВЕРШЁН!</b>\n\n"
                    medals = ["🥇", "🥈", "🥉"]
                    for i, (uid, uname, prize) in enumerate(winners):
                        txt += f"{medals[i]} {uname} — {fmt_num(prize)} Tokens\n"
                    try:
                        await bot.send_message(TOURNAMENT_CHANNEL, txt, parse_mode="HTML")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[tournament_loop] {e}")


async def vip_expire_loop():
    """Очищает истёкшие VIP."""
    while True:
        await asyncio.sleep(3600)  # каждый час
        try:
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM active_vip WHERE expires_at <= NOW()")
            conn.commit()
            c.close()
            release_conn(conn)
            cache_invalidate("vip_tier_")
        except Exception as e:
            print(f"[vip_expire_loop] {e}")





    # ═══════════════════════════════════════════════════════════════
# ЧАСТЬ 6/6 — CALLBACK HANDLER, TEXT HANDLER, EDITOR HANDLER
# ═══════════════════════════════════════════════════════════════

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

    # ─── Запрет игр в личке ───
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

    # ═══════════════ ЯЗЫК ═══════════════
    if data == "menu_lang":
        await call.message.edit_text(
            "🌐 <b>Выбор языка</b>\n\n👇 Выбери язык:",
            parse_mode="HTML",
            reply_markup=lang_kb()
        )
        await call.answer()
        return

    if data.startswith("set_lang_"):
        lang = data.replace("set_lang_", "")
        if lang in ("ru", "en"):
            set_lang(user_id, lang)
            flag = "🇷🇺" if lang == "ru" else "🇬🇧"
            await call.answer(f"{flag} Язык изменён!", show_alert=True)
            try:
                await call.message.edit_text(
                    f"{flag} <b>Язык: {lang.upper()}</b>\n\n"
                    f"✅ Сохранено",
                    parse_mode="HTML",
                    reply_markup=back_to_main_kb()
                )
            except Exception:
                pass
        return

    # ═══════════════ MENU ═══════════════
    if data == "menu_main":
        balance = get_balance(user_id)
        bank = get_bank(user_id)
        xp = get_xp(user_id)
        level = xp // 100
        rank = get_rank_name(level)
        vip_tier = get_vip_tier(user_id)
        vip_line = ""
        if vip_tier > 0:
            info = get_vip_tier_info(vip_tier)
            if info:
                vip_line = f"{info['icon']} VIP {info['id']} — {info['name']}\n"

        boost = get_active_boost(user_id)
        if boost:
            mins_left = int((boost[1] - datetime.now()).total_seconds() // 60)
            boost_line = f"⚡ ×{boost[0]} • {mins_left} мин"
        else:
            boost_line = "❌ нет"

        if is_unlimited(user_id):
            total_line = "♾️"
        else:
            total_line = f"<b>{fmt_num(clamp(balance + bank))}</b> Tokens"

        txt = (
            f"🎰 <b>ТОКЕНЫ-КАЗИНО</b>\n"
            f"────────────\n\n"
            f"👤 <b>{username}</b>\n"
            f"🎖 {rank}\n"
            f"{vip_line}\n"
            f"💎 Баланс: <b>{fmt_num(balance)}</b> Tokens\n"
            f"🏦 Банк: <b>{fmt_num(bank)}</b> Tokens\n"
            f"📊 Всего: {total_line}\n\n"
            f"⚡ Буст: {boost_line}\n\n"
            f"👇 Выбирай:"
        )
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=main_menu_inline_kb())
        await call.answer()
        return

    if data == "menu_games":
        await call.message.edit_text("🎮 <b>ИГРЫ</b>\n\nВыбери игру:", parse_mode="HTML", reply_markup=games_kb())
        await call.answer()
        return

    if data == "menu_shop":
        await call.message.edit_text(shop_text(), parse_mode="HTML", reply_markup=shop_kb())
        await call.answer()
        return

    if data == "menu_cases":
        await call.message.edit_text(cases_text(), parse_mode="HTML", reply_markup=cases_kb())
        await call.answer()
        return

    if data == "menu_profile":
        await call.message.edit_text(profile_text(user_id, username), parse_mode="HTML", reply_markup=profile_kb())
        await call.answer()
        return

    if data == "menu_stats":
        await call.message.edit_text(stats_text(user_id, username), parse_mode="HTML", reply_markup=back_to_main_kb())
        await call.answer()
        return

    if data == "menu_history":
        await call.message.edit_text(history_text(user_id, username), parse_mode="HTML", reply_markup=history_kb())
        await call.answer()
        return

    if data == "menu_birthday":
        birthday_input_state[user_id] = True
        await call.message.edit_text(
            "🎂 <b>ДАТА РОЖДЕНИЯ</b>\n\n"
            "Отправь свою дату в формате <code>ДД.ММ</code>\n"
            "Например: <code>15.06</code>\n\n"
            "🎁 В день рождения бот подарит бонус!\n\n"
            "❌ Отмена: /profile",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data.startswith("hist_"):
        game_map = {
            "hist_roulette": "рулетка", "hist_slots": "слоты",
            "hist_mines": "мины", "hist_bj": "блэкджек",
            "hist_coin": "монетка", "hist_duel": "дуэль",
            "hist_all": None,
        }
        game = game_map.get(data)
        await call.message.edit_text(history_text(user_id, username, game), parse_mode="HTML", reply_markup=history_kb())
        await call.answer()
        return

    if data == "menu_quests":
        await call.message.edit_text(quests_text(user_id), parse_mode="HTML", reply_markup=daily_quests_kb(user_id))
        await call.answer()
        return

    if data == "menu_level_rewards":
        await call.message.edit_text(level_rewards_text(), parse_mode="HTML", reply_markup=level_rewards_kb())
        await call.answer()
        return

    if data == "menu_tournament":
        await call.message.edit_text(tournament_text(), parse_mode="HTML", reply_markup=back_to_main_kb())
        await call.answer()
        return

    if data == "menu_daily":
        can, left = get_daily_status(user_id)
        if can:
            claim_daily(user_id)
            nb = get_balance(user_id)
            await call.answer(f"🎁 +{fmt_num(DAILY_BONUS)}", show_alert=True)
            try:
                await call.message.edit_text(
                    f"🎁 <b>Ежедневный бонус</b>\n"
                    f"────────────\n\n"
                    f"Вы получили: <b>+{fmt_num(DAILY_BONUS)}</b> Tokens\n"
                    f"Ваш баланс: <b>{fmt_num(nb)}</b> Tokens\n\n"
                    f"Возвращайтесь завтра за новым бонусом! 🔥",
                    parse_mode="HTML",
                    reply_markup=back_to_main_kb()
                )
            except Exception:
                pass
        else:
            await call.answer(f"⏳ Через {fmt_time_left(left)}", show_alert=True)
        return

    if data == "menu_balance":
        bank = get_bank(user_id)
        if is_unlimited(user_id):
            await call.answer(f"♾️ БЕЗЛИМИТ\n🏦 {fmt_num(bank)}", show_alert=True)
        else:
            balance = get_balance(user_id)
            await call.answer(f"💎 {fmt_num(balance)}\n🏦 {fmt_num(bank)}", show_alert=True)
        return

    if data == "menu_bank":
        await call.message.edit_text(bank_text(user_id, username), parse_mode="HTML", reply_markup=bank_kb())
        await call.answer()
        return

    if data == "bank_deposit":
        balance = get_balance(user_id)
        bank_input_state[user_id] = {"mode": "deposit"}
        await call.message.edit_text(
            f"🏦 <b>ПОЛОЖИТЬ В БАНК</b>\n\n💎 Баланс: <b>{fmt_num(balance)}</b>\n\nВведи сумму:",
            parse_mode="HTML", reply_markup=bank_cancel_kb()
        )
        await call.answer()
        return

    if data == "bank_withdraw":
        bank = get_bank(user_id)
        bank_input_state[user_id] = {"mode": "withdraw"}
        await call.message.edit_text(
            f"🏦 <b>СНЯТЬ ИЗ БАНКА</b>\n\n🏦 В банке: <b>{fmt_num(bank)}</b>\n\nВведи сумму:",
            parse_mode="HTML", reply_markup=bank_cancel_kb()
        )
        await call.answer()
        return

    if data == "menu_top":
        await call.message.edit_text(top_text("balance"), parse_mode="HTML", reply_markup=top_kb())
        await call.answer()
        return

    if data.startswith("top_"):
        mode = data.replace("top_", "")
        await call.message.edit_text(top_text(mode), parse_mode="HTML", reply_markup=top_kb())
        await call.answer()
        return

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

    if data in ("inv_titles", "inv_boosts", "inv_vip", "inv_cases", "inv_all"):
        filter_map = {"inv_titles": "title", "inv_boosts": "boost", "inv_vip": "vip", "inv_cases": "case", "inv_all": None}
        ft = filter_map[data]
        try:
            await call.message.edit_text(
                inventory_text(user_id, ft),
                parse_mode="HTML",
                reply_markup=inventory_list_kb(user_id, ft)
            )
        except Exception:
            pass
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
            f"📦 <b>{title}</b>\n\n👇 Что делаем?",
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
        edit_shop_state[user_id] = {"mode": "sell_price", "inv_id": inv_id}
        await call.message.edit_text(
            f"💰 <b>ВЫСТАВИТЬ НА РЫНОК</b>\n\n"
            f"📦 Предмет: <b>{item.get('type')}</b>\n\n"
            f"Введи цену в Tokens\n"
            f"<i>(минимум 10 000, максимум {fmt_num(MAX_BALANCE)})</i>\n\n"
            f"❌ Отмена: /inventory",
            parse_mode="HTML"
        )
        await call.answer()
        return

    # ═══════════════ VIP ═══════════════
    if data == "menu_vip":
        await call.message.edit_text(vip_text(user_id), parse_mode="HTML", reply_markup=vip_kb())
        await call.answer()
        return

    if data.startswith("vip_buy_"):
        parts = data.replace("vip_buy_", "").split("_")
        try:
            tid = int(parts[0]); stars = int(parts[1])
        except Exception:
            await call.answer("❌ Ошибка", show_alert=True)
            return
        info = get_vip_tier_info(tid)
        if not info or info["stars"] != stars:
            await call.answer("❌ VIP изменился. Открой заново.", show_alert=True)
            return
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"{info['icon']} VIP {tid} — {info['name']}",
                description=f"Кэшбэк {info['cashback']}%, бонус +{fmt_num(info['bonus'])} Tokens, {info['duration_days']} дней",
                payload=f"vip_{tid}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label=f"VIP {tid} — {info['name']}", amount=stars)],
            )
        except Exception as e:
            print(f"VIP invoice error: {e}")
        return

    # ═══════════════ XP ═══════════════
    if data == "menu_xp":
        await call.message.edit_text(xp_text(user_id), parse_mode="HTML", reply_markup=xp_kb())
        await call.answer()
        return

    if data.startswith("xp_buy_"):
        parts = data.replace("xp_buy_", "").split("_")
        try:
            pack_id = parts[0]
            xp_amount = int(parts[1]); stars = int(parts[2])
        except Exception:
            await call.answer("❌ Ошибка", show_alert=True)
            return
        await call.answer()
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title=f"⭐ Буст XP +{xp_amount}",
                description=f"Мгновенно +{xp_amount} XP",
                payload=f"xp_{pack_id}_{xp_amount}_{stars}",
                currency="XTR",
                prices=[LabeledPrice(label=f"+{xp_amount} XP", amount=stars)],
            )
        except Exception as e:
            print(f"XP invoice error: {e}")
        return

    # ═══════════════ ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ═══════════════
    if data.startswith("daily_quest_claim_"):
        qkey = data.replace("daily_quest_claim_", "")
        reward = claim_daily_quest(user_id, qkey)
        if reward:
            new_balance = get_balance(user_id)
            await call.answer(f"✅ +{fmt_num(reward)} Tokens", show_alert=True)
            try:
                await call.message.edit_text(
                    f"🎯 <b>ЗАДАНИЕ ВЫПОЛНЕНО!</b>\n\n"
                    f"💰 Награда: <b>+{fmt_num(reward)}</b> Tokens\n"
                    f"💎 Баланс: <b>{fmt_num(new_balance)}</b>",
                    parse_mode="HTML",
                    reply_markup=daily_quests_kb(user_id)
                )
            except Exception:
                pass
        else:
            await call.answer("❌ Уже получено", show_alert=True)
        return

    if data == "quest_noop":
        await call.answer()
        return

    # ═══════════════ МАГАЗИН ═══════════════
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
            await call.answer("❌ Не продаётся за Stars", show_alert=True)
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
            print(f"Shop invoice error: {e}")
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
            await call.answer("❌ Не продаётся за Tokens", show_alert=True)
            return
        balance = get_balance(user_id)
        if balance < price and not is_unlimited(user_id):
            await call.answer(f"❌ Нужно {fmt_num(price)} Tokens", show_alert=True)
            return
        set_balance(user_id, -price)
        reward_text = grant_shop_item(user_id, it)
        nb = get_balance(user_id)
        await call.answer("✅ Куплено!", show_alert=True)
        try:
            await call.message.edit_text(
                f"✅ <b>КУПЛЕНО!</b>\n\n"
                f"🎁 {reward_text}\n\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
                f"📦 Предмет в инвентаре!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")],
                    [InlineKeyboardButton(text="🛒 Магазин", callback_data="menu_shop")]
                ])
            )
        except Exception:
            pass
        # Логируем
        price_str = f"{fmt_num(price)} Tokens"
        log_purchase(user_id, username, "tokens", it["name"], price_str, "Бот")
        await notify_admin_purchase(user_id, username, "tokens", it["name"], price_str, "Бот")
        return

    # ═══════════════ КЕЙСЫ ═══════════════
    if data.startswith("case_buy_"):
        parts = data.split("_")
        case_id = parts[2]
        try:
            stars = int(parts[3])
        except Exception:
            await call.answer("❌", show_alert=True)
            return
        case = get_case_by_id(case_id)
        if not case or case["stars"] != stars:
            await call.answer("❌ Кейс изменился", show_alert=True)
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
            print(f"Case invoice error: {e}")
        return

    # ═══════════════ РЕФКА ═══════════════
    if data == "menu_ref":
        await call.message.edit_text(ref_text(user_id, username), parse_mode="HTML", reply_markup=ref_kb())
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
            txt += f"{m} <b>{uname}</b> — {cnt} 👥 | {fmt_num(earn)} Tokens\n"
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=ref_kb())
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
                "🏪 <b>РЫНОК</b>\n\n😢 Пока пусто...\n\nБудь первым!",
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
        lots = get_market_lots()
        lot_price = lots[idx]["price"] if 0 <= idx < len(lots) else 0
        lot_name = lots[idx].get("type", "?") if 0 <= idx < len(lots) else "?"
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
            # Лог + уведомление
            price_str = f"{fmt_num(lot_price)} Tokens"
            log_purchase(user_id, username, "market", f"Лот: {lot_name}", price_str, "Бот")
            await notify_admin_purchase(user_id, username, "market", f"Лот: {lot_name}", price_str, "Бот")
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
            f"Введи цену в Tokens\n"
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
            price = f"{fmt_num(lot['price'])} Tokens"
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

    # ═══════════════ INFO ИГР ═══════════════
    if data == "info_roulette":
        await call.message.edit_text("🎡 <b>РУЛЕТКА</b>\n\n<code>к 1000</code> — красное ×2\n<code>ч 1000</code> — чёрное ×2\n<code>з 1000</code> — зеро ×36\n\n<code>го</code> — запуск", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return
    if data == "info_slots":
        await call.message.edit_text("🎰 <b>СЛОТЫ</b>\n\n<code>спин 1000</code>\n\n🍒×10 | 🍋×15 | 🍊×20 | 🍇×25 | 💎×50 | 7️⃣×100", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return
    if data == "info_coin":
        await call.message.edit_text("🪙 <b>МОНЕТКА</b>\n\n<code>орёл 1000</code> / <code>решка 1000</code> — ×2", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return
    if data == "info_bj":
        await call.message.edit_text("🃏 <b>БЛЭКДЖЕК</b>\n\n<code>бж 1000</code>\n\n×2", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return
    if data == "info_mines":
        await call.message.edit_text("💣 <b>МИНЫ</b>\n\n<code>мины 1000</code>\n\n🟢 3 | 🟡 5 | 🔴 10", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return
    if data == "info_duel":
        await call.message.edit_text("⚔️ <b>ДУЭЛЬ</b>\n\n<code>дуэль 1000 @user</code>", parse_mode="HTML", reply_markup=back_to_games_kb())
        await call.answer()
        return

    # ═══════════════ СТАВКИ / ИГРЫ ═══════════════
    if data.startswith("setbet_"):
        val = data.replace("setbet_", "")
        balance = get_balance(user_id)
        bet = balance if val == "max" else int(val)
        await call.message.edit_reply_markup(reply_markup=roulette_kb(bet))
        await call.answer(f"💎 {fmt_num(bet)}")
        return

    if data.startswith("mines_start_"):
        parts = data.split("_")
        level = parts[2]; bet = int(parts[3])
        if level not in MINES_LEVELS:
            await call.answer("❌", show_alert=True); return
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌ Ставка неверна", show_alert=True); return
        balance = get_balance(user_id)
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
        update_daily_quest(user_id, "daily_bets_5", 1)
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[level]['name']}</b>\n\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
            f"💎 Множитель: <b>×1.00</b>\n"
            f"🎁 Забрать: <b>{fmt_num(bet)}</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[level]['mines']}</b>",
            parse_mode="HTML", reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💣 Началось!")
        return

    if data.startswith("mines_open_"):
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
            # Сбрасываем win_streak
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET win_streak = 0 WHERE user_id = %s", (user_id,))
            conn.commit()
            c.close()
            release_conn(conn)
            await call.message.edit_text(
                f"💥 <b>БУМ! Мина!</b>\n\n😢 -<b>{fmt_num(game['bet'])}</b>",
                parse_mode="HTML", reply_markup=back_to_main_kb()
            )
            del mines_games[user_id]
            await call.answer(); return
        game["opened"].add(idx)
        game["mult"] = round(1 + len(game["opened"]) * MINES_LEVELS[game["level"]]["step"], 2)
        safe_total = 25 - MINES_LEVELS[game["level"]]["mines"]
        if len(game["opened"]) == safe_total:
            wa = clamp(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
            set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} all")
            update_quest(user_id, "win_100k", wa)
            update_quest(user_id, "mines_win_5", 1)
            update_daily_quest(user_id, "daily_win_1", 1)
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🏆 <b>ПОЛЕ ОЧИЩЕНО!</b>\n\n💰 <b>+{fmt_num(wa)}</b>\n💎 {fmt_num(nb)}",
                parse_mode="HTML", reply_markup=back_to_main_kb()
            )
            del mines_games[user_id]
            await call.answer("🎉"); return
        await call.message.edit_text(
            f"💣 <b>МИНЫ — {MINES_LEVELS[game['level']]['name']}</b>\n\n"
            f"💰 Ставка: <b>{fmt_num(game['bet'])}</b>\n"
            f"💎 Множитель: <b>×{game['mult']:.2f}</b>\n"
            f"🎁 Забрать: <b>{fmt_num(int(game['bet']*game['mult']))}</b>\n"
            f"💣 Мин: <b>{MINES_LEVELS[game['level']]['mines']}</b>",
            parse_mode="HTML", reply_markup=mines_field_kb(user_id)
        )
        await call.answer("💎")
        return

    if data == "mines_cashout":
        if user_id not in mines_games:
            await call.answer("❌", show_alert=True); return
        game = mines_games[user_id]
        if not game["opened"]:
            await call.answer("❌ Открой 1 клетку", show_alert=True); return
        wa = clamp(int(game["bet"] * game["mult"] * get_event_mult() * get_user_mult(user_id)))
        set_balance(user_id, wa)
        pay_ref_commission(user_id, wa)
        nb = get_balance(user_id)
        log_game(user_id, username, "мины", game["bet"], wa, f"{game['level']} x{game['mult']}")
        update_quest(user_id, "win_100k", wa)
        update_quest(user_id, "mines_win_5", 1)
        update_daily_quest(user_id, "daily_win_1", 1)
        await call.message.edit_text(
            f"💰 <b>ЗАБРАЛ!</b>\n\n🎁 +<b>{fmt_num(wa)}</b>\n💎 {fmt_num(nb)}",
            parse_mode="HTML", reply_markup=back_to_main_kb()
        )
        del mines_games[user_id]
        await call.answer("💰")
        return

    if data == "mines_cancel":
        if user_id in mines_games:
            game = mines_games[user_id]
            if not game["opened"]:
                set_balance(user_id, game["bet"])
                del mines_games[user_id]
                await call.message.edit_text("❌ Отменено", parse_mode="HTML", reply_markup=back_to_main_kb())
                await call.answer("Возвращено")
                return
        await call.answer("❌")
        return

    if data == "mines_noop":
        await call.answer()
        return

    if data.startswith("bet_"):
        parts = data.split("_")
        bet_type = parts[1]; bet = int(parts[2])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌", show_alert=True); return
        balance = get_balance(user_id)
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
        add_xp(user_id, 1)
        update_quest(user_id, "roulette_10")
        update_daily_quest(user_id, "daily_bets_5", 1)
        if win:
            wa = clamp(int(bet * mult * get_event_mult() * get_user_mult(user_id)))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            update_quest(user_id, "win_100k", wa)
            update_daily_quest(user_id, "daily_win_1", 1)
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n🎉 <b>ПОБЕДА!</b>\n💰 +{fmt_num(wa)}\n💎 {fmt_num(nb)}"
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n😢 -{fmt_num(bet)}\n💎 {fmt_num(nb)}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ ×2", callback_data=f"bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("group_bet_"):
        parts = data.split("_")
        bet_type = parts[2]; bet = int(parts[3])
        if bet < 10 or bet > MAX_BET:
            await call.answer("❌", show_alert=True); return
        balance = get_balance(user_id)
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
            pay_ref_commission(user_id, wa)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n🎉 <b>ПОБЕДА!</b>\n💰 +{fmt_num(wa)}\n💎 {fmt_num(nb)}"
            log_game(user_id, username, "рулетка", bet, wa, f"{result} {color}")
        else:
            nb = get_balance(user_id)
            txt = f"🎡 <b>РУЛЕТКА</b>\n\n🎯 {color} {result}\n\n😢 -{fmt_num(bet)}\n💎 {fmt_num(nb)}"
            log_game(user_id, username, "рулетка", bet, 0, f"{result} {color}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"group_bet_{bet_type}_{bet}"),
             InlineKeyboardButton(text="⬆️ ×2", callback_data=f"group_bet_{bet_type}_{bet*2}")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main")]
        ])
        await call.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data == "bj_hit":
        if user_id not in bj_games:
            await call.answer("❌", show_alert=True); return
        game = bj_games[user_id]
        game["player"].append(game["deck"].pop())
        p_score = hand_score(game["player"])
        if p_score > 21:
            nb = get_balance(user_id)
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'])}\n\n💥 ПЕРЕБОР!\n💸 -{fmt_num(game['bet'])}\n💎 {fmt_num(nb)}",
                parse_mode="HTML", reply_markup=back_to_main_kb()
            )
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score}")
            del bj_games[user_id]
        else:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'], hide_second=True)}\n\n🎯 Ещё?",
                parse_mode="HTML", reply_markup=bj_kb()
            )
        await call.answer()
        return

    if data == "bj_stand":
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
        update_daily_quest(user_id, "daily_bets_5", 1)
        if d_score > 21 or p_score > d_score:
            wa = clamp(game["bet"] * 2 * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            res = f"🎉 <b>ПОБЕДА!</b>\n💰 +{fmt_num(wa - game['bet'])}"
            log_game(user_id, username, "блэкджек", game["bet"], wa, f"{p_score} vs {d_score}")
            update_daily_quest(user_id, "daily_win_1", 1)
        elif p_score == d_score:
            set_balance(user_id, game["bet"])
            nb = get_balance(user_id)
            res = "🤝 <b>Ничья</b>"
            log_game(user_id, username, "блэкджек", game["bet"], game["bet"], f"{p_score}")
        else:
            nb = get_balance(user_id)
            res = f"😢 <b>Проигрыш</b>\n💸 -{fmt_num(game['bet'])}"
            log_game(user_id, username, "блэкджек", game["bet"], 0, f"{p_score} vs {d_score}")
        await call.message.edit_text(
            f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 {fmt_hand(game['player'])} = <b>{p_score}</b>\n🤖 {fmt_hand(game['dealer'])} = <b>{d_score}</b>\n\n{res}\n\n💎 {fmt_num(nb)}",
            parse_mode="HTML", reply_markup=back_to_main_kb()
        )
        del bj_games[user_id]
        await call.answer()
        return

    # ═══════════════ АДМИН ═══════════════
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
                f"💎 Баланс: <b>{fmt_num(balance)}</b>\n"
                f"🏦 Банк: <b>{fmt_num(bank)}</b>\n\n"
                f"📋 <b>Выбери раздел:</b>"
            )
            # ReplyKeyboard нельзя в edit_text — отправляем НОВОЕ
            await call.message.answer(txt, parse_mode="HTML", reply_markup=admin_panel_kb())
            await call.answer()
            return

        if data == "admin_cat_players":
            await call.message.edit_text(
                "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n👇 Выбери действие:",
                parse_mode="HTML", reply_markup=admin_players_kb()
            )
            await call.answer()
            return

        if data == "admin_cat_games":
            await call.message.edit_text(
                "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай:",
                parse_mode="HTML", reply_markup=admin_games_kb()
            )
            await call.answer()
            return

        if data == "admin_cat_content":
            await call.message.edit_text(
                "🛒 <b>УПРАВЛЕНИЕ КОНТЕНТОМ</b>\n\n👇 Выбери:",
                parse_mode="HTML", reply_markup=admin_content_kb()
            )
            await call.answer()
            return

        if data == "admin_cat_economy":
            await call.message.edit_text(
                "💰 <b>ЭКОНОМИКА</b>\n\n👇 Выбери:",
                parse_mode="HTML", reply_markup=admin_economy_kb()
            )
            await call.answer()
            return

        if data == "admin_cat_comm":
            await call.message.edit_text(
                "📢 <b>СВЯЗЬ</b>\n\n👇 Выбери:",
                parse_mode="HTML", reply_markup=admin_comm_kb()
            )
            await call.answer()
            return

        if data == "admin_cat_monitor":
            await call.message.edit_text(
                "📊 <b>МОНИТОРИНГ</b>\n\n👇 Выбери:",
                parse_mode="HTML", reply_markup=admin_monitor_kb()
            )
            await call.answer()
            return

        if data.startswith("admin_toggle_"):
            game = data.replace("admin_toggle_", "")
            if game not in GAME_NAMES:
                await call.answer("❌", show_alert=True); return
            if game in disabled_games:
                disabled_games.discard(game)
                save_disabled_games()
                await call.answer(f"✅ {GAME_NAMES[game]} включена")
            else:
                disabled_games.add(game)
                save_disabled_games()
                await call.answer(f"❌ {GAME_NAMES[game]} выключена")
            await call.message.edit_text(
                "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n👇 Включай/выключай:",
                parse_mode="HTML", reply_markup=admin_games_kb()
            )
            return

        if data == "admin_active_show":
            users = get_recent_users(minutes=5, limit=20)
            if not users:
                txt = "📊 За последние 5 минут никто не играл"
            else:
                txt = "📊 <b>Активные за 5 минут</b>\n\n"
                for i, (uid, uname, bal) in enumerate(users, 1):
                    txt += f"{i}. <b>{uname}</b> — 💎 {fmt_num(bal)}\n"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        if data == "admin_all_players":
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT user_id, username, balance, banned FROM users ORDER BY balance DESC LIMIT 30")
            rows = c.fetchall()
            c.execute("SELECT COUNT(*) FROM users")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
            banned = c.fetchone()[0]
            c.execute("SELECT COALESCE(SUM(balance), 0) FROM users")
            total_balance = c.fetchone()[0]
            c.close()
            release_conn(conn)
            medals = ["🥇", "🥈", "🥉"]
            txt = f"👥 <b>ВСЕ ИГРОКИ</b>\n═══════════════\n\n"
            for i, row in enumerate(rows):
                uid, uname, bal, is_b = row
                medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
                ban = " 🚫" if is_b else ""
                txt += f"{medal} {uname or f'user_{uid}'} — <b>{fmt_num(bal)}</b>{ban}\n"
            if total > 30:
                txt += f"\n<i>...и ещё {total - 30}</i>\n"
            txt += f"\n═══════════════\n"
            txt += f"📊 Всего: <b>{total}</b>\n🚫 Забанено: <b>{banned}</b>\n💎 Общий баланс: <b>{fmt_num(total_balance)}</b>"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

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
                f"📊 <b>СТАТИСТИКА</b>\n\n"
                f"👥 Игроков: <b>{total_users}</b>\n"
                f"💎 Tokens: <b>{fmt_num(total_balance)}</b>\n"
                f"🎮 Игр: <b>{total_games}</b>"
            )
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        if data == "admin_bigwins_show":
            wins = get_big_wins(limit=10, min_win=100000)
            if not wins:
                txt = "📊 Крупных выигрышей нет"
            else:
                txt = "🏆 <b>BIG WINS</b>\n\n"
                for i, (uname, game, win, time) in enumerate(wins, 1):
                    txt += f"{i}. <b>{uname}</b> — {game} +{fmt_num(win)} ({time})\n"
            await call.message.edit_text(txt, parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

        if data == "admin_broadcast_start":
            admin_action_state[user_id] = {"mode": "broadcast"}
            await call.message.edit_text("📢 <b>РАССЫЛКА</b>\n\nОтправь текст:\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_ban_start":
            admin_action_state[user_id] = {"mode": "ban"}
            await call.message.edit_text("🚫 <b>BAN / UNBAN</b>\n\nОтправь @username:\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_vip_start":
            admin_action_state[user_id] = {"mode": "vip"}
            await call.message.edit_text("👑 <b>VIP</b>\n\nФормат: <code>@username уровень</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_title_start":
            admin_action_state[user_id] = {"mode": "title"}
            await call.message.edit_text("🏷 <b>ТИТУЛ</b>\n\nФормат: <code>@username Титул</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_bal_start":
            admin_action_state[user_id] = {"mode": "balance"}
            await call.message.edit_text("💰 <b>БАЛАНС</b>\n\nФормат: <code>@username сумма</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_xp_start":
            admin_action_state[user_id] = {"mode": "xp"}
            await call.message.edit_text("📊 <b>XP</b>\n\nФормат: <code>@username XP</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_reset_start":
            admin_action_state[user_id] = {"mode": "reset"}
            await call.message.edit_text("🔄 <b>RESET</b>\n\nФормат: <code>@username</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_bonus_start":
            admin_action_state[user_id] = {"mode": "bonus"}
            await call.message.edit_text("🎁 <b>БОНУС</b>\n\n<code>@username сумма</code> или <code>all сумма</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_logs_start":
            admin_action_state[user_id] = {"mode": "logs"}
            await call.message.edit_text("📜 <b>ЛОГИ</b>\n\nФормат: <code>@username</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
            await call.answer()
            return

        if data == "admin_giveaway_start":
            admin_action_state[user_id] = {"mode": "giveaway"}
            await call.message.edit_text("🎁 <b>РОЗЫГРЫШ</b>\n\nФормат: <code>сумма время</code>\nПример: <code>10000 1h</code>\n\n❌ Отмена: /admin", parse_mode="HTML")
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
            await call.message.edit_text("👤 <code>/stats @user</code>", parse_mode="HTML", reply_markup=admin_back_kb())
            await call.answer()
            return

    # ═══════════════ РЕДАКТОР МАГАЗИНА ═══════════════
    if data == "editshop_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        except Exception:
            await call.message.answer(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        await call.answer()
        return

    if data.startswith("editshop_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editshop_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editshop_item_text(idx), parse_mode="HTML", reply_markup=editshop_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editshop_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editshop_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True); return
        prompts = {
            "name": "🏷 Введи новое название:",
            "desc": "📝 Введи новое описание:",
            "stars": "⭐ Введи цену в Stars (0 = убрать):",
            "tokens": "💎 Введи цену в Tokens (0 = убрать):",
            "mult": "⚡ Введи множитель:",
            "minutes": "⏱ Введи минуты:",
            "title": "🏷 Введи название титула:",
            "vip_level": "👑 Введи VIP уровень (0-5):",
        }
        edit_shop_state[user_id] = {"mode": "edit_shop", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /editshop",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data.startswith("editshop_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editshop_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editshop_delok_{idx}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editshop_item_{idx}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ ТОВАР?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editshop_delok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editshop_delok_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        items = get_shop_items()
        if 0 <= idx < len(items):
            items.pop(idx)
            save_shop_items(items)
        await call.message.edit_text(editshop_list_text(), parse_mode="HTML", reply_markup=editshop_list_kb())
        await call.answer("✅ Удалено")
        return

    if data == "editshop_add":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Буст", callback_data="editshop_newtype_boost"),
             InlineKeyboardButton(text="🏷️ Титул", callback_data="editshop_newtype_title")],
            [InlineKeyboardButton(text="👑 VIP", callback_data="editshop_newtype_vip"),
             InlineKeyboardButton(text="🔙 Назад", callback_data="editshop_start")]
        ])
        await call.message.edit_text("➕ <b>НОВЫЙ ТОВАР</b>\n\n👇 Тип:", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editshop_newtype_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
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
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        except Exception:
            await call.message.answer(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        await call.answer()
        return

    if data.startswith("editcases_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editcases_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editcases_item_text(idx), parse_mode="HTML", reply_markup=editcases_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editcases_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True); return
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
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editcases_rewards_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editcases_item_text(idx), parse_mode="HTML", reply_markup=editcases_rewards_kb(idx))
        await call.answer()
        return

    if data.startswith("editcases_reward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_reward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(
            editcases_reward_edit_text(ci, ri),
            parse_mode="HTML",
            reply_markup=editcases_reward_kb(ci, ri)
        )
        await call.answer()
        return

    if data.startswith("editcases_editreward_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_editreward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(
            editcases_reward_edit_text(ci, ri),
            parse_mode="HTML",
            reply_markup=editcases_reward_edit_kb(ci, ri)
        )
        await call.answer()
        return

    if data.startswith("editcases_rf_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_rf_", "").split("_")
        try:
            ci, ri, field = int(parts[0]), int(parts[1]), parts[2]
        except Exception:
            await call.answer("❌", show_alert=True); return
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
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_delreward_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True); return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editcases_delrewardok_{ci}_{ri}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editcases_reward_{ci}_{ri}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ ПРИЗ?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editcases_delrewardok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editcases_delrewardok_", "").split("_")
        try:
            ci, ri = int(parts[0]), int(parts[1])
        except Exception:
            await call.answer("❌", show_alert=True); return
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
            await call.answer("❌", show_alert=True); return
        try:
            ci = int(data.replace("editcases_addreward_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
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
            await call.answer("❌", show_alert=True); return
        try:
            ci = int(data.replace("editcases_newboost_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        edit_case_state[user_id] = {"mode": "newboost", "ci": ci, "step": "mult"}
        await call.message.edit_text("➕ <b>НОВЫЙ БУСТ</b>\n\n⚡ Множитель:", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editcases_newtitle_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            ci = int(data.replace("editcases_newtitle_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        edit_case_state[user_id] = {"mode": "newtitle", "ci": ci, "step": "title"}
        await call.message.edit_text("➕ <b>НОВЫЙ ТИТУЛ</b>\n\n🏷 Название:", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editcases_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editcases_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"editcases_delok_{idx}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"editcases_item_{idx}")]
        ])
        await call.message.edit_text("🗑 <b>УДАЛИТЬ КЕЙС?</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()
        return

    if data.startswith("editcases_delok_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editcases_delok_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        cases = get_cases()
        if 0 <= idx < len(cases):
            cases.pop(idx)
            save_cases(cases)
        await call.message.edit_text(editcases_list_text(), parse_mode="HTML", reply_markup=editcases_list_kb())
        await call.answer("✅")
        return

    # ═══════════════ РЕДАКТОР VIP ═══════════════
    if data == "editvip_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editvip_list_text(), parse_mode="HTML", reply_markup=editvip_list_kb())
        except Exception:
            await call.message.answer(editvip_list_text(), parse_mode="HTML", reply_markup=editvip_list_kb())
        await call.answer()
        return

    if data.startswith("editvip_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            tid = int(data.replace("editvip_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editvip_item_text(tid), parse_mode="HTML", reply_markup=editvip_item_kb(tid))
        await call.answer()
        return

    if data.startswith("editvip_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editvip_field_", "").split("_")
        try:
            tid = int(parts[0])
            field = "_".join(parts[1:])  # duration_days может содержать _
        except Exception:
            await call.answer("❌", show_alert=True); return
        prompts = {
            "stars": "⭐ Введи цену в Stars:",
            "cashback": "💸 Введи кэшбэк %:",
            "bonus": "🎁 Введи бонус в Tokens:",
            "duration_days": "⏱ Введи срок в днях:",
            "exclusive_games": "🎰 Введи кол-во эксклюзивных игр:",
        }
        edit_vip_state[user_id] = {"mode": "editvip", "tid": tid, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ VIP {tid}</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /admin",
            parse_mode="HTML"
        )
        await call.answer()
        return

    # ═══════════════ РЕДАКТОР XP ═══════════════
    if data == "editxp_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editxp_list_text(), parse_mode="HTML", reply_markup=editxp_list_kb())
        except Exception:
            await call.message.answer(editxp_list_text(), parse_mode="HTML", reply_markup=editxp_list_kb())
        await call.answer()
        return

    if data.startswith("editxp_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editxp_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editxp_item_text(idx), parse_mode="HTML", reply_markup=editxp_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editxp_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editxp_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True); return
        prompts = {
            "xp": "📊 Введи XP:",
            "stars": "⭐ Введи цену в Stars:",
        }
        edit_xp_state[user_id] = {"mode": "editxp", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ ПАКЕТА</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /admin",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data == "editxp_add":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        edit_xp_state[user_id] = {"mode": "newxp", "step": "xp"}
        await call.message.edit_text("➕ <b>НОВЫЙ ПАКЕТ</b>\n\n📊 Введи XP:\n\n❌ Отмена: /admin", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editxp_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editxp_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        packs = get_xp_packs()
        if 0 <= idx < len(packs):
            packs.pop(idx)
            save_xp_packs(packs)
        await call.message.edit_text(editxp_list_text(), parse_mode="HTML", reply_markup=editxp_list_kb())
        await call.answer("✅ Удалено")
        return

    # ═══════════════ РЕДАКТОР ЗАДАНИЙ ═══════════════
    if data == "editquest_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editquest_list_text(), parse_mode="HTML", reply_markup=editquest_list_kb())
        except Exception:
            await call.message.answer(editquest_list_text(), parse_mode="HTML", reply_markup=editquest_list_kb())
        await call.answer()
        return

    if data.startswith("editquest_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editquest_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editquest_item_text(idx), parse_mode="HTML", reply_markup=editquest_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editquest_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editquest_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True); return
        prompts = {
            "name": "🏷 Введи название:",
            "target": "🎯 Введи цель:",
            "reward": "💰 Введи награду:",
        }
        edit_quest_state[user_id] = {"mode": "editquest", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ ЗАДАНИЯ</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /admin",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data == "editquest_add":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        edit_quest_state[user_id] = {"mode": "newquest", "step": "name"}
        await call.message.edit_text("➕ <b>НОВОЕ ЗАДАНИЕ</b>\n\n🏷 Введи название:\n\n❌ Отмена: /admin", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editquest_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editquest_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        qs = get_daily_quests()
        if 0 <= idx < len(qs):
            qs.pop(idx)
            save_daily_quests(qs)
        await call.message.edit_text(editquest_list_text(), parse_mode="HTML", reply_markup=editquest_list_kb())
        await call.answer("✅ Удалено")
        return

    # ═══════════════ РЕДАКТОР НАГРАД УРОВНЕЙ ═══════════════
    if data == "editlevel_start":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            await call.message.edit_text(editlevel_list_text(), parse_mode="HTML", reply_markup=editlevel_list_kb())
        except Exception:
            await call.message.answer(editlevel_list_text(), parse_mode="HTML", reply_markup=editlevel_list_kb())
        await call.answer()
        return

    if data.startswith("editlevel_item_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editlevel_item_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        await call.message.edit_text(editlevel_item_text(idx), parse_mode="HTML", reply_markup=editlevel_item_kb(idx))
        await call.answer()
        return

    if data.startswith("editlevel_field_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        parts = data.replace("editlevel_field_", "").split("_")
        try:
            idx = int(parts[0]); field = parts[1]
        except Exception:
            await call.answer("❌", show_alert=True); return
        prompts = {
            "level": "📊 Введи уровень:",
            "value": "💰 Введи значение:",
        }
        edit_level_state[user_id] = {"mode": "editlevel", "idx": idx, "field": field}
        await call.message.edit_text(
            f"✏️ <b>РЕДАКТИРОВАНИЕ</b>\n\n{prompts.get(field, 'Введи значение:')}\n\n❌ Отмена: /admin",
            parse_mode="HTML"
        )
        await call.answer()
        return

    if data == "editlevel_add":
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        edit_level_state[user_id] = {"mode": "newlevel", "step": "level"}
        await call.message.edit_text("➕ <b>НОВАЯ НАГРАДА</b>\n\n📊 Введи уровень:\n\n❌ Отмена: /admin", parse_mode="HTML")
        await call.answer()
        return

    if data.startswith("editlevel_del_"):
        if user_id != ADMIN_ID:
            await call.answer("❌", show_alert=True); return
        try:
            idx = int(data.replace("editlevel_del_", ""))
        except Exception:
            await call.answer("❌", show_alert=True); return
        rewards = get_level_rewards()
        if 0 <= idx < len(rewards):
            rewards.pop(idx)
            save_level_rewards(rewards)
        await call.message.edit_text(editlevel_list_text(), parse_mode="HTML", reply_markup=editlevel_list_kb())
        await call.answer("✅ Удалено")
        return

    # ─── Прочие callback'и (не обработаны) ───
    await call.answer()


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ИГР
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# TEXT_HANDLER (ГРУППА) — ИГРОВЫЕ КОМАНДЫ
# ═══════════════════════════════════════════════════════════════
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
                f"💰 +<b>{fmt_num(DAILY_BONUS)}</b>\n"
                f"💎 Баланс: <b>{fmt_num(nb)}</b>\n\n"
                f"⏳ Следующий через 24ч",
                parse_mode="HTML"
            )
        else:
            await message.reply(f"⏳ Через <b>{fmt_time_left(left)}</b>", parse_mode="HTML")
        return

    # ── ПРОФИЛЬ ──
    if text in ['профиль', 'я']:
        await message.reply(profile_text(user_id, username), parse_mode="HTML", reply_markup=profile_kb())
        return

    # ── ЗАДАНИЯ ──
    if text in ['задания', 'квесты', 'quests']:
        await message.reply(quests_text(user_id), parse_mode="HTML", reply_markup=daily_quests_kb(user_id))
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
            f"⚔️ <b>ВЫЗОВ!</b>\n\n👤 {username} → @{target_username}\n💰 <b>{fmt_num(bet)}</b>\n\n@{target_username}, напиши <code>принять</code>!",
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
        msg = await message.reply(f"⚔️ <b>ДУЭЛЬ!</b>\n\n💰 <b>{fmt_num(total_bank)}</b>", parse_mode="HTML")
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
        pay_ref_commission(wid, total_bank)
        add_xp(duel["challenger_id"], 3); add_xp(duel["opponent_id"], 3)
        log_game(wid, wn, "дуэль", total_bank // 2, total_bank, f"vs {ln}")
        update_daily_quest(wid, "daily_win_1", 1)
        await msg.edit_text(
            f"⚔️ <b>ДУЭЛЬ</b>\n\n{ce}\n\n🏆 <b>{wn}</b>\n💰 +{fmt_num(total_bank)}\n💎 {fmt_num(nb)}",
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
        await message.reply(f"🏦 В банк: -{fmt_num(amount)}\n💎 {fmt_num(new_bal)}\n🏦 {fmt_num(new_bank)}", parse_mode="HTML")
        return

    if len(parts) == 3 and parts[0] == 'банк' and parts[1] == 'снять':
        try:
            amount = int(parts[2])
        except Exception:
            await message.reply("❌ Сумма"); return
        bank = get_bank(user_id)
        if bank < amount:
            await message.reply(f"❌ В банке {fmt_num(bank)}"); return
        set_bank(user_id, -amount)
        new_bal = set_balance(user_id, amount)
        new_bank = get_bank(user_id)
        await message.reply(f"🏦 Из банка: +{fmt_num(amount)}\n💎 {fmt_num(new_bal)}\n🏦 {fmt_num(new_bank)}", parse_mode="HTML")
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
        await message.reply(f"💸 Перевод: {fmt_num(amount)}\n💎 {fmt_num(nb)} | {fmt_num(nt)}", parse_mode="HTML")
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
        xp = get_xp(user_id)
        level = xp // 100
        rank = get_rank_name(level)
        if is_unlimited(user_id):
            await message.reply(f"💰 {username}\n🎖 {rank}\n♾️ БЕЗЛИМИТ\n🏦 {fmt_num(bank)}", parse_mode="HTML")
        else:
            await message.reply(f"💰 {username}\n🎖 {rank}\n💎 <b>{fmt_num(bal)}</b>\n🏦 {fmt_num(bank)}", parse_mode="HTML")
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
        await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>", parse_mode="HTML", reply_markup=mines_level_kb(bet))
        return

    # ── ГО (рулетка запуск) ──
    if text == 'го':
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            await message.reply("❌ Нет ставок"); return
        bets = active_bets[chat_id]["bets"]
        total_bank = clamp(sum(b["bet_total"] for b in bets))
        unlimited_in = any(is_unlimited(b["user_id"]) for b in bets)
        bank_line = "♾️" if unlimited_in else f"{fmt_num(total_bank)}"
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
                pay_ref_commission(b["user_id"], win_amount)
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], win_amount, f"{result} {color}")
                update_daily_quest(b["user_id"], "daily_win_1", 1)
                if is_unlimited(b["user_id"]):
                    winners.append(f"🎉 {b['username']} — ♾️")
                else:
                    winners.append(f"🎉 {b['username']} — <b>+{fmt_num(win_amount)}</b>")
            else:
                log_game(b["user_id"], b["username"], "рулетка", b["bet_total"], 0, f"{result} {color}")
        if winners:
            result_text += "\n".join(winners)
        else:
            result_text += "😢 Победителей нет"

        # ─── СРЫВ ДЖЕКПОТА при Зеро ───
        if result == 0 and bets:
            jackpot = get_jackpot()
            if jackpot > 0:
                green_bettors = [b for b in bets if b["type"] == "green"]
                if green_bettors:
                    share = jackpot // len(green_bettors)
                    for b in green_bettors:
                        set_balance(b["user_id"], share)
                    result_text += f"\n\n💎 <b>ДЖЕКПОТ СОРВАН!</b>\n💰 {fmt_num(jackpot)} разделены между {len(green_bettors)}"
                    # Уведомление админу
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"💎 <b>СРЫВ ДЖЕКПОТА!</b>\n────────────\n"
                            f"💰 Сумма: <b>{fmt_num(jackpot)}</b>\n"
                            f"👥 Победителей: <b>{len(green_bettors)}</b>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    reset_jackpot()
                    add_xp(user_id, 50)

        # Комиссия 1% в джекпот
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

    # ── СЛОТЫ ──
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

        msg = await message.reply("🎰 <b>СЛОТЫ</b>\n\n🎲 Крутим...", parse_mode="HTML")
        for _ in range(3):
            a = random.choice(symbols); b = random.choice(symbols); c = random.choice(symbols)
            await asyncio.sleep(0.3)
            await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Крутим...\n\n┃ {a} ┃ {b} ┃ {c} ┃", parse_mode="HTML")
        await asyncio.sleep(0.4)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ ❓ ┃ ❓ ┃", parse_mode="HTML")
        await asyncio.sleep(0.5)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ {r2} ┃ ❓ ┃", parse_mode="HTML")
        await asyncio.sleep(0.6)
        await msg.edit_text(f"🎰 <b>СЛОТЫ</b>\n\n🎲 Останавливается...\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃", parse_mode="HTML")
        await asyncio.sleep(0.4)

        win = False; mult = 0
        if r1 == r2 == r3:
            win = True
            mult = {'🍒': 10, '🍋': 15, '🍊': 20, '🍇': 25, '💎': 50, '7️⃣': 100}.get(r1, 10)
        elif r1 == r2 or r2 == r3 or r1 == r3:
            win = True; mult = 2
        add_xp(user_id, 1)
        update_quest(user_id, "bets_20")
        update_daily_quest(user_id, "daily_bets_5", 1)

        if win:
            wa = clamp(bet * mult * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "слоты", bet, wa, f"{r1}{r2}{r3}")
            update_daily_quest(user_id, "daily_win_1", 1)
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n🎉 <b>ВЫИГРЫШ!</b>\n💰 +{fmt_num(wa)} (×{mult})\n💎 {fmt_num(nb)}",
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "слоты", bet, 0, f"{r1}{r2}{r3}")
            await msg.edit_text(
                f"🎰 <b>СЛОТЫ</b>\n\n┃ {r1} ┃ {r2} ┃ {r3} ┃\n\n😢 -{fmt_num(bet)}\n💎 {fmt_num(nb)}",
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
        update_daily_quest(user_id, "daily_bets_5", 1)
        if result == choice:
            wa = clamp(bet * 2 * get_event_mult() * get_user_mult(user_id))
            nb = set_balance(user_id, wa)
            pay_ref_commission(user_id, wa)
            log_game(user_id, username, "монетка", bet, wa, "🦅" if result == 'heads' else "👑")
            update_daily_quest(user_id, "daily_win_1", 1)
            await msg.edit_text(
                f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅' if result == 'heads' else '👑'}\n\n🎉 <b>+{fmt_num(wa)}</b>\n💎 {fmt_num(nb)}",
                parse_mode="HTML"
            )
        else:
            nb = get_balance(user_id)
            log_game(user_id, username, "монетка", bet, 0, "🦅" if result == 'heads' else "👑")
            await msg.edit_text(
                f"🪙 <b>МОНЕТКА</b>\n\n🎯 {'🦅' if result == 'heads' else '👑'}\n\n😢 -{fmt_num(bet)}\n💎 {fmt_num(nb)}",
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
            f"📊 <b>Ставка!</b>\n\n👤 {username}\n{icon} × <b>{fmt_num(bet)}</b>\n⚡ Всего: {len(bets)}\n💰 Банк: <b>{fmt_num(total_bank)}</b>\n\n🕐 <code>го</code>",
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
            f"📊 <b>Ставка!</b>\n\n🎯 <b>{ranges_str}</b>\n💰 <b>{fmt_num(bet)}</b> × {len(ranges)} = <b>{fmt_num(total_bet)}</b>\n\n🕐 <code>го</code>",
            parse_mode="HTML"
        )
        return


# ═══════════════════════════════════════════════════════════════
# EDITOR_TEXT_HANDLER (ЛИЧКА) — ВВОД ИЗ РЕДАКТОРОВ + ДИАЛОГИ
# ═══════════════════════════════════════════════════════════════
@dp.message(F.text, F.chat.type == 'private')
async def editor_text_handler(message: Message):
    user_id = message.from_user.id if message.from_user else None
    if user_id != ADMIN_ID:
        # Обычный юзер — только birthday
        if birthday_input_state.get(user_id):
            val = message.text.strip()
            parts = val.split(".")
            if len(parts) == 2:
                try:
                    d, m = int(parts[0]), int(parts[1])
                    if 1 <= d <= 31 and 1 <= m <= 12:
                        conn = get_conn()
                        c = conn.cursor()
                        c.execute("UPDATE users SET birthday = %s WHERE user_id = %s", (val, user_id))
                        conn.commit()
                        c.close()
                        release_conn(conn)
                        birthday_input_state.pop(user_id, None)
                        await message.answer(
                            f"✅ <b>Дата сохранена: {val}</b>\n\n🎂 Поздравим в этот день!",
                            parse_mode="HTML"
                        )
                        return
                except Exception:
                    pass
            await message.answer("❌ Формат: <code>ДД.ММ</code>\nПример: <code>15.06</code>\n\n/profile", parse_mode="HTML")
        return  # ⚠️ ВАЖНО! Обычный юзер — выходим, НЕ идём в админ-код
        

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
            await message.answer("❌ Минимум 10 000 Tokens", parse_mode="HTML")
            return
        if price > MAX_BALANCE:
            await message.answer(f"❌ Максимум {fmt_num(MAX_BALANCE)}", parse_mode="HTML")
            return
        username = message.from_user.username or message.from_user.first_name
        remove_from_inventory(user_id, inv_id)
        add_market_lot(user_id, username, item, price)
        edit_shop_state.pop(user_id, None)
        await message.answer(
            f"✅ <b>ЛОТ ВЫСТАВЛЕН!</b>\n\n💰 Цена: <b>{fmt_num(price)}</b> Tokens\n🏪 Смотри: /market",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏪 Рынок", callback_data="menu_market")],
                [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="menu_inventory")]
            ])
        )
        return

    # ═══════ РЕДАКТОР МАГАЗИНА ═══════
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
                await message.answer("❌ Число", parse_mode="HTML"); return
            items[idx][field] = num if num > 0 else None
        elif field in ("mult", "minutes", "vip_level"):
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            items[idx][field] = num
        elif field == "title":
            items[idx]["title"] = val
        save_shop_items(items)
        edit_shop_state.pop(user_id, None)
        await message.answer("✅ <b>Обновлено!</b>\n\n/editshop", parse_mode="HTML")
        return

    # ═══════ НОВЫЙ ТОВАР ═══════
    if st and st.get("mode") == "new_shop":
        step = st["step"]; data_dict = st["data"]; val = message.text.strip()
        if step == "name":
            data_dict["name"] = val
            data_dict.setdefault("id", f"item_{int(time.time())}")
            st["step"] = "desc"; edit_shop_state[user_id] = st
            await message.answer("📝 Описание:", parse_mode="HTML"); return
        if step == "desc":
            data_dict["desc"] = val
            st["step"] = "stars"; edit_shop_state[user_id] = st
            await message.answer("⭐ Цена Stars (0 = не продавать):", parse_mode="HTML"); return
        if step == "stars":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            data_dict["stars"] = num if num > 0 else None
            st["step"] = "tokens"; edit_shop_state[user_id] = st
            await message.answer("💎 Цена Tokens (0 = не продавать):", parse_mode="HTML"); return
        if step == "tokens":
            try:
                num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            data_dict["tokens"] = num if num > 0 else None
            t = data_dict.get("type")
            if t == "boost":
                st["step"] = "mult"; edit_shop_state[user_id] = st
                await message.answer("⚡ Множитель:", parse_mode="HTML"); return
            if t == "title":
                st["step"] = "title"; edit_shop_state[user_id] = st
                await message.answer("🏷 Титул:", parse_mode="HTML"); return
            if t == "vip":
                st["step"] = "vip_level"; edit_shop_state[user_id] = st
                await message.answer("👑 VIP уровень (1-5):", parse_mode="HTML"); return
            return
        if step == "mult":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            data_dict["mult"] = num; st["step"] = "minutes"; edit_shop_state[user_id] = st
            await message.answer("⏱ Минуты:", parse_mode="HTML"); return
        if step == "minutes":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            data_dict["minutes"] = num
            items = get_shop_items(); items.append(data_dict); save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ Товар добавлен! /editshop", parse_mode="HTML"); return
        if step == "title":
            data_dict["title"] = val
            items = get_shop_items(); items.append(data_dict); save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ Товар добавлен!", parse_mode="HTML"); return
        if step == "vip_level":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число 1-5:", parse_mode="HTML"); return
            if not 1 <= num <= 5:
                await message.answer("❌ 1-5", parse_mode="HTML"); return
            data_dict["vip_level"] = num
            items = get_shop_items(); items.append(data_dict); save_shop_items(items)
            edit_shop_state.pop(user_id, None)
            await message.answer("✅ Товар добавлен!", parse_mode="HTML"); return
        return

    # ═══════ РЕДАКТОР VIP ═══════
    st = edit_vip_state.get(user_id)
    if st and st.get("mode") == "editvip":
        tid = st["tid"]; field = st["field"]
        tiers = get_vip_tiers()
        t = next((x for x in tiers if x["id"] == tid), None)
        if not t:
            edit_vip_state.pop(user_id, None)
            await message.answer("❌ VIP не найден", parse_mode="HTML"); return
        try:
            num = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Число", parse_mode="HTML"); return
        t[field] = num
        save_vip_tiers(tiers)
        edit_vip_state.pop(user_id, None)
        await message.answer(f"✅ VIP {tid}: {field} = {num}\n\n/admin", parse_mode="HTML")
        return

    # ═══════ РЕДАКТОР XP ═══════
    st = edit_xp_state.get(user_id)
    if st and st.get("mode") == "editxp":
        idx = st["idx"]; field = st["field"]
        packs = get_xp_packs()
        if idx < 0 or idx >= len(packs):
            edit_xp_state.pop(user_id, None)
            await message.answer("❌ Пакет не найден", parse_mode="HTML"); return
        try:
            num = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Число", parse_mode="HTML"); return
        packs[idx][field] = num
        save_xp_packs(packs)
        edit_xp_state.pop(user_id, None)
        await message.answer("✅ Обновлено! /admin", parse_mode="HTML")
        return

    if st and st.get("mode") == "newxp":
        step = st["step"]
        val = message.text.strip()
        if step == "xp":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            st["xp"] = num; st["step"] = "stars"; edit_xp_state[user_id] = st
            await message.answer("⭐ Цена в Stars:", parse_mode="HTML"); return
        if step == "stars":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            packs = get_xp_packs()
            packs.append({"id": f"xp_{int(time.time())}", "xp": st["xp"], "stars": num})
            save_xp_packs(packs)
            edit_xp_state.pop(user_id, None)
            await message.answer("✅ Пакет добавлен! /admin", parse_mode="HTML"); return
        return

    # ═══════ РЕДАКТОР ЗАДАНИЙ ═══════
    st = edit_quest_state.get(user_id)
    if st and st.get("mode") == "editquest":
        idx = st["idx"]; field = st["field"]
        qs = get_daily_quests()
        if idx < 0 or idx >= len(qs):
            edit_quest_state.pop(user_id, None)
            await message.answer("❌ Не найдено", parse_mode="HTML"); return
        val = message.text.strip()
        if field == "name":
            qs[idx]["name"] = val
        elif field in ("target", "reward"):
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            qs[idx][field] = num
        save_daily_quests(qs)
        edit_quest_state.pop(user_id, None)
        await message.answer("✅ Обновлено! /admin", parse_mode="HTML")
        return

    if st and st.get("mode") == "newquest":
        step = st["step"]; val = message.text.strip()
        if step == "name":
            st["name"] = val; st["step"] = "target"; edit_quest_state[user_id] = st
            await message.answer("🎯 Цель:", parse_mode="HTML"); return
        if step == "target":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            st["target"] = num; st["step"] = "reward"; edit_quest_state[user_id] = st
            await message.answer("💰 Награда:", parse_mode="HTML"); return
        if step == "reward":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            qs = get_daily_quests()
            qs.append({"key": f"quest_{int(time.time())}", "name": st["name"], "target": st["target"], "reward": num})
            save_daily_quests(qs)
            edit_quest_state.pop(user_id, None)
            await message.answer("✅ Задание добавлено! /admin", parse_mode="HTML"); return
        return

    # ═══════ РЕДАКТОР НАГРАД УРОВНЕЙ ═══════
    st = edit_level_state.get(user_id)
    if st and st.get("mode") == "editlevel":
        idx = st["idx"]; field = st["field"]
        rewards = get_level_rewards()
        if idx < 0 or idx >= len(rewards):
            edit_level_state.pop(user_id, None)
            await message.answer("❌ Не найдено", parse_mode="HTML"); return
        try: num = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Число", parse_mode="HTML"); return
        rewards[idx][field] = num
        save_level_rewards(rewards)
        edit_level_state.pop(user_id, None)
        await message.answer("✅ Обновлено! /admin", parse_mode="HTML")
        return

    if st and st.get("mode") == "newlevel":
        step = st["step"]; val = message.text.strip()
        if step == "level":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            st["level"] = num; st["step"] = "type"; edit_level_state[user_id] = st
            await message.answer("📊 Тип (tokens/cashback/vip_games/vip_tier):", parse_mode="HTML"); return
        if step == "type":
            if val not in ("tokens", "cashback", "vip_games", "vip_tier"):
                await message.answer("❌ tokens/cashback/vip_games/vip_tier", parse_mode="HTML"); return
            st["type"] = val; st["step"] = "value"; edit_level_state[user_id] = st
            await message.answer("💰 Значение:", parse_mode="HTML"); return
        if step == "value":
            try: num = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            rewards = get_level_rewards()
            rewards.append({"level": st["level"], "type": st["type"], "value": num})
            save_level_rewards(rewards)
            edit_level_state.pop(user_id, None)
            await message.answer("✅ Награда добавлена! /admin", parse_mode="HTML"); return
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
            if field == "name": cases[idx]["name"] = val
            elif field == "desc": cases[idx]["desc"] = val
            elif field == "stars":
                try: num = int(val)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML"); return
                cases[idx]["stars"] = num
            save_cases(cases)
            edit_case_state.pop(user_id, None)
            await message.answer("✅ /editcases", parse_mode="HTML"); return

        if mode == "editreward":
            cases = get_cases(); ci = st["ci"]; ri = st["ri"]; field = st["field"]
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None); return
            rewards = cases[ci]["rewards"]
            if ri < 0 or ri >= len(rewards):
                edit_case_state.pop(user_id, None); return
            val = message.text.strip()
            if field == "title": rewards[ri]["title"] = val
            elif field in ("mult", "minutes", "chance"):
                try: num = int(val)
                except ValueError:
                    await message.answer("❌ Число", parse_mode="HTML"); return
                rewards[ri][field] = num
            save_cases(cases)
            edit_case_state.pop(user_id, None)
            await message.answer("✅", parse_mode="HTML"); return

        if mode == "newboost":
            ci = st["ci"]; step = st["step"]
            cases = get_cases()
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None); return
            val = message.text.strip()
            if step == "mult":
                try: num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                st["mult"] = num; st["step"] = "minutes"; edit_case_state[user_id] = st
                await message.answer("⏱ Минуты:", parse_mode="HTML"); return
            if step == "minutes":
                try: num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                st["minutes"] = num; st["step"] = "chance"; edit_case_state[user_id] = st
                await message.answer("🎲 Шанс %:", parse_mode="HTML"); return
            if step == "chance":
                try: num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                cases[ci]["rewards"].append({"type": "boost", "mult": st["mult"], "minutes": st["minutes"], "chance": num})
                save_cases(cases)
                edit_case_state.pop(user_id, None)
                await message.answer("✅", parse_mode="HTML"); return
            return

        if mode == "newtitle":
            ci = st["ci"]; step = st["step"]
            cases = get_cases()
            if ci < 0 or ci >= len(cases):
                edit_case_state.pop(user_id, None); return
            val = message.text.strip()
            if step == "title":
                st["title"] = val; st["step"] = "chance"; edit_case_state[user_id] = st
                await message.answer("🎲 Шанс %:", parse_mode="HTML"); return
            if step == "chance":
                try: num = int(val)
                except ValueError:
                    await message.answer("❌", parse_mode="HTML"); return
                cases[ci]["rewards"].append({"type": "title", "title": st["title"], "chance": num})
                save_cases(cases)
                edit_case_state.pop(user_id, None)
                await message.answer("✅", parse_mode="HTML"); return
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
                await message.answer(f"❌ Недостаточно! Баланс: {fmt_num(bal)}", parse_mode="HTML"); return
            set_balance(user_id, -amount)
            new_bank = set_bank(user_id, amount)
            new_bal = get_balance(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>ПОЛОЖЕНО В БАНК</b>\n\n💰 +<b>{fmt_num(amount)}</b>\n💎 {fmt_num(new_bal)}\n🏦 {fmt_num(new_bank)}",
                parse_mode="HTML", reply_markup=bank_kb()
            ); return
        if mode == "withdraw":
            bank = get_bank(user_id)
            if bank < amount:
                bank_input_state.pop(user_id, None)
                await message.answer(f"❌ В банке {fmt_num(bank)}", parse_mode="HTML"); return
            set_bank(user_id, -amount)
            new_bal = set_balance(user_id, amount)
            new_bank = get_bank(user_id)
            bank_input_state.pop(user_id, None)
            await message.answer(
                f"🏦 <b>СНЯТО ИЗ БАНКА</b>\n\n💰 +<b>{fmt_num(amount)}</b>\n💎 {fmt_num(new_bal)}\n🏦 {fmt_num(new_bank)}",
                parse_mode="HTML", reply_markup=bank_kb()
            ); return
        bank_input_state.pop(user_id, None); return

    # ═══════ АДМИН-ДИАЛОГИ ═══════
    ast = admin_action_state.get(user_id)
    if ast:
        mode = ast.get("mode")
        val = message.text.strip()
        admin_action_state.pop(user_id, None)

        if mode == "broadcast":
            uids = get_all_user_ids()
            sent, failed = 0, 0
            for uid in uids:
                try:
                    await bot.send_message(uid, f"📢 <b>РАССЫЛКА</b>\n\n{val}", parse_mode="HTML")
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
            await message.answer(f"📢 <b>Готово</b>\n✅ {sent} | ❌ {failed}", parse_mode="HTML"); return

        if mode == "ban":
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_banned(uid, True)
            await message.answer(f"🚫 <b>@{uname} забанен!</b>", parse_mode="HTML"); return

        if mode == "vip":
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user уровень", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try: level = int(parts[1])
            except ValueError:
                await message.answer("❌ Уровень число", parse_mode="HTML"); return
            if not 0 <= level <= 5:
                await message.answer("❌ 0-5", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_vip_tier(uid, level, 20)
            await message.answer(f"✅ @{uname} → VIP {level}", parse_mode="HTML"); return

        if mode == "title":
            parts = val.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("❌ @user Титул", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            title_text = parts[1]
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            add_title(uid, title_text, user_id)
            await message.answer(f"🏷️ @{uname} → {title_text}", parse_mode="HTML"); return

        if mode == "balance":
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try: amount = int(parts[1])
            except ValueError:
                await message.answer("❌ Сумма число", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            set_balance_exact(uid, amount)
            await message.answer(f"✅ @{uname}: баланс = {fmt_num(amount)}", parse_mode="HTML"); return

        if mode == "xp":
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user XP", parse_mode="HTML"); return
            uname = parts[0].replace("@", "")
            try: amount = int(parts[1])
            except ValueError:
                await message.answer("❌ XP число", parse_mode="HTML"); return
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET xp = %s WHERE user_id = %s", (amount, uid))
            conn.commit()
            c.close()
            release_conn(conn)
            cache_invalidate(f"xp_{uid}")
            await message.answer(f"✅ @{uname} XP = {amount}", parse_mode="HTML"); return

        if mode == "reset":
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            reset_user(uid)
            await message.answer(f"✅ @{uname} сброшен", parse_mode="HTML"); return

        if mode == "bonus":
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ @user сумма / all сумма", parse_mode="HTML"); return
            target = parts[0]
            try: amount = int(parts[1])
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
                await message.answer(f"🎁 +{fmt_num(amount)} всем ({count})", parse_mode="HTML"); return
            uname = target.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            nb = set_balance(uid, amount)
            await message.answer(f"🎁 +{fmt_num(amount)} → @{uname}\n💎 {fmt_num(nb)}", parse_mode="HTML"); return

        if mode == "logs":
            uname = val.replace("@", "")
            uid = get_user_id_by_username(uname)
            if not uid:
                await message.answer(f"❌ @{uname} не найден", parse_mode="HTML"); return
            logs = get_user_logs(uid, 10)
            if not logs:
                await message.answer("📜 Пусто", parse_mode="HTML"); return
            txt = f"📜 <b>Последние 10 игр @{uname}</b>\n\n"
            for i, (game, bet, win, detail, t) in enumerate(logs, 1):
                profit = win - bet
                emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
                txt += f"{i}. {emoji} {game} | {fmt_num(bet)} → {fmt_num(win)} | {t}\n"
            await message.answer(txt, parse_mode="HTML"); return

        if mode == "jackpot_set":
            try: amount = int(val)
            except ValueError:
                await message.answer("❌ Число", parse_mode="HTML"); return
            save_jackpot(amount)
            await message.answer(f"✅ Джекпот = {fmt_num(amount)}", parse_mode="HTML"); return

        if mode == "giveaway":
            parts = val.split()
            if len(parts) < 2:
                await message.answer("❌ сумма время", parse_mode="HTML"); return
            try: amount = int(parts[0])
            except ValueError:
                await message.answer("❌ Сумма", parse_mode="HTML"); return
            time_str = parts[1].lower()
            minutes = 0
            if time_str.endswith('h'):
                minutes = int(time_str[:-1]) * 60
            elif time_str.endswith('m'):
                minutes = int(time_str[:-1])
            if minutes == 0:
                await message.answer("❌ 30m / 1h", parse_mode="HTML"); return
            users = get_all_user_ids()
            ends_at = datetime.now() + timedelta(minutes=minutes)
            conn = get_conn()
            c = conn.cursor()
            c.execute("INSERT INTO giveaways (amount, ends_at, created_by, status) VALUES (%s, %s, %s, 'active')",
                      (amount, ends_at, user_id))
            conn.commit()
            c.close()
            release_conn(conn)
            await message.answer(f"🎁 Розыгрыш! {fmt_num(amount)}", parse_mode="HTML"); return

        return

    # ─── Прочее не обрабатываем ───
    return   
# ═══════════════════════════════════════════════════════════════
# CRASH — MULTIPLAYER ИГРА
# ═══════════════════════════════════════════════════════════════

import random as _random

# ─── ГЛОБАЛЬНОЕ СОСТОЯНИЕ CRASH ───
crash_state = {
    "round_id": 0,
    "status": "waiting",       # waiting / running / crashed
    "multiplier": 1.00,
    "crash_point": 0.0,
    "started_at": 0.0,
    "next_round_at": 0.0,
    "history": [],             # последние 20 крашей
    "bets": [],                # ставки текущего раунда
}
crash_lock = asyncio.Lock()


def generate_crash_point():
    """Генерирует точку краха. RTP ~96%."""
    r = _random.random()
    if r < 0.03:
        return 1.00                                    # 3% — моментальный краш
    if r < 0.50:
        return round(_random.uniform(1.01, 1.50), 2)   # 47% — низкий
    if r < 0.85:
        return round(_random.uniform(1.50, 3.00), 2)   # 35% — средний
    if r < 0.97:
        return round(_random.uniform(3.00, 10.00), 2)  # 12% — высокий
    return round(_random.uniform(10.00, 100.00), 2)    # 3% — джекпот


async def crash_loop():
    """Фоновый цикл игры Crash (24/7)."""
    global crash_state
    print("🚀 Crash loop запущен")

    while True:
        try:
            # ═══ ФАЗА 1: ОТСЧЁТ (5 сек) ═══
            async with crash_lock:
                crash_state["status"] = "waiting"
                crash_state["multiplier"] = 1.00
                crash_state["crash_point"] = generate_crash_point()
                crash_state["bets"] = []
                crash_state["next_round_at"] = time.time() + 5
                crash_state["round_id"] += 1
                rid = crash_state["round_id"]

            # Создаём раунд в БД
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO crash_rounds (crash_point, status) VALUES (%s, 'waiting') RETURNING id",
                    (crash_state["crash_point"],)
                )
                db_round_id = c.fetchone()[0]
                conn.commit()
                c.close()
                release_conn(conn)
            except Exception as e:
                print(f"[crash_loop] db error: {e}")
                db_round_id = rid

            await asyncio.sleep(5)

            # ═══ ФАЗА 2: ПОЛЁТ ═══
            async with crash_lock:
                if crash_state["status"] != "waiting":
                    continue
                crash_state["status"] = "running"
                crash_state["started_at"] = time.time()

            # Обновляем статус в БД
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute("UPDATE crash_rounds SET status = 'running' WHERE id = %s", (db_round_id,))
                conn.commit()
                c.close()
                release_conn(conn)
            except Exception:
                pass

            start_time = time.time()
            while True:
                elapsed = time.time() - start_time
                # Формула роста: чем больше времени, тем быстрее растёт
                multiplier = round(1.0 + elapsed * 0.5 + (elapsed ** 2) * 0.15, 2)

                if multiplier >= crash_state["crash_point"]:
                    multiplier = crash_state["crash_point"]
                    async with crash_lock:
                        crash_state["multiplier"] = multiplier
                        crash_state["status"] = "crashed"
                    break

                async with crash_lock:
                    crash_state["multiplier"] = multiplier

                # Проверка авто-кэшаутов
                await check_crash_auto_cashouts(multiplier)

                await asyncio.sleep(0.1)

            # ═══ ФАЗА 3: КРАШ — финализация ═══
            await finalize_crash_round(db_round_id)

            # История
            async with crash_lock:
                crash_state["history"].insert(0, crash_state["crash_point"])
                crash_state["history"] = crash_state["history"][:20]

            # Пауза 5 сек
            await asyncio.sleep(5)

        except Exception as e:
            print(f"[crash_loop] error: {e}")
            await asyncio.sleep(5)


async def check_crash_auto_cashouts(current_mult):
    """Проверяет и выполняет авто-кэшауты."""
    async with crash_lock:
        for bet in crash_state["bets"]:
            if bet.get("cashed_out_at"):
                continue
            auto = bet.get("auto_cashout")
            if auto and current_mult >= auto:
                # Авто-кэшаут
                win = clamp(int(bet["bet"] * auto))
                set_balance(bet["user_id"], win)
                bet["cashed_out_at"] = auto
                bet["won"] = win
                # Запись в БД
                try:
                    conn = get_conn()
                    c = conn.cursor()
                    c.execute(
                        "UPDATE crash_bets SET cashed_out_at = %s, won = %s WHERE round_id = %s AND user_id = %s",
                        (auto, win, crash_state["round_id"], bet["user_id"])
                    )
                    conn.commit()
                    c.close()
                    release_conn(conn)
                except Exception:
                    pass
                # Лог игры
                log_game(bet["user_id"], bet["username"], "краш", bet["bet"], win, f"x{auto}")
                # Уведомление игроку
                try:
                    await bot.send_message(
                        bet["user_id"],
                        f"✅ <b>АВТО-ЗАБРАЛ ×{auto}</b>\n\n"
                        f"💰 Выигрыш: <b>+{fmt_num(win)}</b> Tokens",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass


async def finalize_crash_round(db_round_id):
    """Финализация раунда — все не забравшие проигрывают."""
    global crash_state
    async with crash_lock:
        crash_point = crash_state["crash_point"]
        bets = crash_state["bets"]

        for bet in bets:
            if bet.get("cashed_out_at"):
                continue  # Уже забрал
            # Проиграл
            log_game(bet["user_id"], bet["username"], "краш", bet["bet"], 0, f"boom {crash_point}")
            # Обновить в БД
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute(
                    "UPDATE crash_bets SET won = 0 WHERE round_id = %s AND user_id = %s AND cashed_out_at IS NULL",
                    (crash_state["round_id"], bet["user_id"])
                )
                conn.commit()
                c.close()
                release_conn(conn)
            except Exception:
                pass

    # Обновить раунд
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE crash_rounds SET status = 'crashed', crashed_at = NOW() WHERE id = %s",
            (db_round_id,)
        )
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception:
        pass


# ─── API: CRASH ───
@app.route('/api/crash/state')
def api_crash_state():
    """Текущее состояние раунда."""
    return jsonify({
        "round_id": crash_state["round_id"],
        "status": crash_state["status"],
        "multiplier": crash_state["multiplier"],
        "crash_point": crash_state["crash_point"] if crash_state["status"] == "crashed" else None,
        "next_round_at": crash_state["next_round_at"],
        "history": crash_state["history"][:20],
        "bets": crash_state["bets"],
        "time_to_next": max(0, crash_state["next_round_at"] - time.time()),
    })


@app.route('/api/crash/bet', methods=['POST'])
def api_crash_bet():
    """Сделать ставку в текущем раунде."""
    data = request.json
    user_id = data.get('user_id')
    username = data.get('username') or f"user_{user_id}"
    bet = int(data.get('bet', 0))
    auto_cashout = data.get('auto_cashout')
    if auto_cashout:
        try:
            auto_cashout = float(auto_cashout)
        except Exception:
            auto_cashout = None

    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400

    if crash_state["status"] != "waiting":
        return jsonify({"error": "Раунд уже идёт. Жди следующего."}), 400

    # Проверка на дубликат
    for b in crash_state["bets"]:
        if b["user_id"] == user_id:
            return jsonify({"error": "Ты уже сделал ставку в этом раунде"}), 400

    # Проверка баланса
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Недостаточно средств"}), 400

    # Списание
    set_balance(user_id, -bet)

    # Добавление ставки
    crash_state["bets"].append({
        "user_id": user_id,
        "username": username,
        "bet": bet,
        "auto_cashout": auto_cashout,
        "cashed_out_at": None,
        "won": 0,
    })

    # В БД
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO crash_bets (round_id, user_id, username, bet, auto_cashout)
               VALUES (%s, %s, %s, %s, %s)""",
            (crash_state["round_id"], user_id, username, bet, auto_cashout)
        )
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[crash bet] {e}")

    return jsonify({"success": True, "balance": get_balance(user_id)})


@app.route('/api/crash/cashout', methods=['POST'])
def api_crash_cashout():
    """Забрать выигрыш на текущем множителе."""
    data = request.json
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    if crash_state["status"] != "running":
        return jsonify({"error": "Раунд не идёт"}), 400

    current_mult = crash_state["multiplier"]

    for b in crash_state["bets"]:
        if b["user_id"] == user_id:
            if b["cashed_out_at"]:
                return jsonify({"error": "Уже забрал"}), 400
            win = clamp(int(b["bet"] * current_mult))
            set_balance(user_id, win)
            b["cashed_out_at"] = current_mult
            b["won"] = win
            log_game(user_id, b["username"], "краш", b["bet"], win, f"x{current_mult}")

            # БД
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute(
                    "UPDATE crash_bets SET cashed_out_at = %s, won = %s WHERE round_id = %s AND user_id = %s",
                    (current_mult, win, crash_state["round_id"], user_id)
                )
                conn.commit()
                c.close()
                release_conn(conn)
            except Exception:
                pass

            return jsonify({
                "success": True,
                "mult": current_mult,
                "win": win,
                "balance": get_balance(user_id),
            })

    return jsonify({"error": "У тебя нет ставки"}), 400


@app.route('/api/crash/history')
def api_crash_history():
    """История последних крашей."""
    return jsonify(crash_state["history"][:20])


# ═══════════════════════════════════════════════════════════════
# PLINKO — SINGLE-PLAYER ИГРА
# ═══════════════════════════════════════════════════════════════

PLINKO_MULTIPLIERS = {
    "low":    [1.5, 1.2, 1.1, 1.0, 0.5, 1.0, 1.1, 1.2, 1.5],
    "medium": [5.0, 2.0, 1.0, 0.5, 0.3, 0.5, 1.0, 2.0, 5.0],
    "high":   [100.0, 10.0, 2.0, 0.5, 0.0, 0.5, 2.0, 10.0, 100.0],
}


def generate_plinko_drop():
    """Симулирует падение шарика — 8 шагов 50/50."""
    position = 0
    for _ in range(8):
        if _random.random() < 0.5:
            position += 1
    # position от 0 до 8, но нам нужно 9 лунок (0..8)
    return min(position, 8)


@app.route('/api/plinko/play', methods=['POST'])
def api_plinko_play():
    """Сделать бросок шарика."""
    data = request.json
    user_id = data.get('user_id')
    bet = int(data.get('bet', 0))
    risk = data.get('risk', 'medium')

    if not user_id or bet < 10:
        return jsonify({"error": "Invalid bet"}), 400
    if risk not in PLINKO_MULTIPLIERS:
        return jsonify({"error": "Invalid risk"}), 400

    # Проверка баланса
    balance = get_balance(user_id)
    if balance < bet and not is_unlimited(user_id):
        return jsonify({"error": "Недостаточно средств"}), 400

    # Списание
    set_balance(user_id, -bet)

    # Генерация
    position = generate_plinko_drop()
    multiplier = PLINKO_MULTIPLIERS[risk][position]
    win = clamp(int(bet * multiplier)) if multiplier > 0 else 0

    if win > 0:
        set_balance(user_id, win)

    # Лог
    u = get_user(user_id)
    uname = u[0] if u else f"user_{user_id}"
    log_game(user_id, uname, "плинко", bet, win, f"{risk} x{multiplier} pos{position}")

    # БД
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO plinko_history (user_id, username, bet, risk, position, multiplier, won)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (user_id, uname, bet, risk, position, multiplier, win)
        )
        conn.commit()
        c.close()
        release_conn(conn)
    except Exception as e:
        print(f"[plinko] {e}")

    return jsonify({
        "win": win > 0,
        "position": position,
        "multiplier": multiplier,
        "amount": win,
        "bet": bet,
        "balance": get_balance(user_id),
    })


@app.route('/api/plinko/history')
def api_plinko_history():
    """История последних дропов (для ленты)."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT username, bet, risk, multiplier, won
            FROM plinko_history
            WHERE created_at > NOW() - INTERVAL '1 hour'
            ORDER BY id DESC LIMIT 20
        """)
        rows = c.fetchall()
        c.close()
        release_conn(conn)
        return jsonify([
            {"username": r[0], "bet": r[1], "risk": r[2], "multiplier": float(r[3]), "won": r[4]}
            for r in rows
        ])
    except Exception:
        return jsonify([])
    
# ═══════════════════════════════════════════════════════════════
# MAIN — ЗАПУСК БОТА
# ═══════════════════════════════════════════════════════════════
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
    asyncio.create_task(cashback_loop())
    asyncio.create_task(tournament_checker_loop())
    asyncio.create_task(vip_expire_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main()) 