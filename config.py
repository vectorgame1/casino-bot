# ═══════════════════════════════════════════════════════════════
# config.py — КОНФИГ БОТА
# ═══════════════════════════════════════════════════════════════

import os
from datetime import timezone, timedelta

# ═══ ОСНОВНОЕ ═══

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = 6403424348
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ═══ ССЫЛКИ ═══

BOT_USERNAME = "gold1_casino_bot"
GROUP_URL = "https://t.me/+xrmEcGndccs5ZGFi"
EXCHANGE_CHAT_URL = "https://t.me/Tokenschange"
EXCHANGE_CHAT_ID = -1004424481023
MINI_APP_URL = "https://casino-miniapp.pages.dev"
TOURNAMENT_CHANNEL = "@TokenCasinoTournaments"

# ═══ ВРЕМЯ ═══

TZ_MINSK = timezone(timedelta(hours=3))

# ═══ ЛИМИТЫ ═══

MAX_BALANCE = 100_000_000
MAX_BANK = 100_000_000
MAX_TOTAL = MAX_BALANCE + MAX_BANK
MAX_BET = 100_000_000
MAX_WIN = 50_000_000
MAX_BANK_INTEREST = 25_000_000
BANK_INTEREST_RATE = 0.05
MAX_BIGINT = 9_000_000_000_000_000_000

# ═══ ЛИМИТЫ СТАВОК ═══

GAME_BET_LIMITS = {
    "roulette": 25_000_000,
    "slots": 500_000,
    "coin": 25_000_000,
    "mines": 2_500_000,
    "bj": 25_000_000,
    "duel": 25_000_000,
    "crash": 500_000,
    "plinko": 500_000,
}

# ═══ КРЕДИТЫ ═══

CREDIT_MIN = 50_000
CREDIT_MAX = 200_000
CREDIT_DAYS = 3
CREDIT_PERCENT = 0

# ═══ РЕФЕРАЛКА ═══

REF_BONUS_REFERRER = 5_000
REF_BONUS_REFERRED = 5_000
REF_COMMISSION_PERCENT = 5

# ═══ БОНУСЫ ═══

START_BONUS = 1_000
DAILY_BONUS = 5_000

# ═══ ПРОВЕРКИ ═══

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан!")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL не задан!")