# keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎰 Игры"),     KeyboardButton(text="💰 Баланс")],
            [KeyboardButton(text="🏦 Банк"),     KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏪 Донат"),    KeyboardButton(text="🆘 Помощь")],
        ],
        resize_keyboard=True
    )

def games_menu() -> ReplyKeyboardMarkup:
    """Меню игр (для групп)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎰 Рулетка"),  KeyboardButton(text="🎲 Кости")],
            [KeyboardButton(text="🃏 Блэкджек"), KeyboardButton(text="💣 Мины")],
            [KeyboardButton(text="🎡 Колесо"),   KeyboardButton(text="🪙 Монетка")],
            [KeyboardButton(text="🎰 Слоты"),    KeyboardButton(text="⚔️ Дуэль")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

def donate_menu() -> ReplyKeyboardMarkup:
    """Донат-магазин (только токены)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 50 000 Tokens — 7 ⭐")],
            [KeyboardButton(text="💎 150 000 Tokens — 20 ⭐")],
            [KeyboardButton(text="💎 300 000 Tokens — 40 ⭐")],
            [KeyboardButton(text="💎 1 000 000 Tokens — 125 ⭐")],
            [KeyboardButton(text="💎 2 000 000 Tokens — 265 ⭐")],
            [KeyboardButton(text="💎 Своя сумма")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

def support_menu() -> ReplyKeyboardMarkup:
    """Поддержка."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 Tokens не пришли"), KeyboardButton(text="🎮 Что-то сломалось в игре")],
            [KeyboardButton(text="💳 Вопрос по оплате"), KeyboardButton(text="🚫 Бан или мут")],
            [KeyboardButton(text="🐞 Нашёл баг"),        KeyboardButton(text="📜 Правила бота")],
            [KeyboardButton(text="✍️ Свой вопрос")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

def admin_panel_kb() -> ReplyKeyboardMarkup:
    """Админ-панель (Reply)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🛒 Контент"), KeyboardButton(text="💰 Экономика")],
            [KeyboardButton(text="📢 Связь"), KeyboardButton(text="📊 Мониторинг")],
            [KeyboardButton(text="📋 Все команды")],
            [KeyboardButton(text="⬅️ Назад в админку")],
        ],
        resize_keyboard=True
    )