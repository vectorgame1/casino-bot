# ============================================================
# keyboards.py — v59
# ============================================================
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ================= ИГРОК =================
def get_main_kb(uid=None):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💎 Донат")],
        [KeyboardButton(text="🆘 Помощь"), KeyboardButton(text="🌐 Язык")]
    ], resize_keyboard=True)

def get_profile_kb(uid=None):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="📦 Кейс")],
        [KeyboardButton(text="🎟 Лотерея"), KeyboardButton(text="🎡 Колесо")],
        [KeyboardButton(text="📜 Квесты"), KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def get_cases_kb(uid=None):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎁 Обычный кейс"), KeyboardButton(text="💎 VIP Кейс")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def get_donate_kb(uid=None):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐ Купить Stars"), KeyboardButton(text="👑 Купить VIP")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def get_support_kb(uid=None):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Проблема с игрой"), KeyboardButton(text="💳 Вопрос по оплате")],
        [KeyboardButton(text="🚫 Бан или мут"), KeyboardButton(text="🐞 Нашёл баг")],
        [KeyboardButton(text="✍️ Свой вопрос")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

# ================= МОДЕРАТОР =================
def mod_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],
        [KeyboardButton(text="⚠️ Варн"), KeyboardButton(text="📌 Закреп")],
        [KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

# ================= ПИАРЩИК =================
def pr_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Получить текст"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

# ================= АДМИН =================
def admin_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎁 Ивент")],
        [KeyboardButton(text="🛠 Управление"), KeyboardButton(text="📜 Отчет")],
        [KeyboardButton(text="⬅️ В меню")]
    ], resize_keyboard=True)

def admin_players_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💰 Выдать"), KeyboardButton(text="💸 Забрать")],
        [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

# ================= ИНЛАЙН =================
def bet_actions_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data="bet_repeat"), InlineKeyboardButton(text="⏫ Удвоить", callback_data="bet_double")]
    ])