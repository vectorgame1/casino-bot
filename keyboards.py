from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="🏦 Банк"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="💎 Донат"), KeyboardButton(text="🆘 Помощь")],
        [KeyboardButton(text="🌐 Язык")]
    ], resize_keyboard=True)

def bank_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📥 Положить"), KeyboardButton(text="📤 Снять")],
        [KeyboardButton(text="💳 Кредит"), KeyboardButton(text="💸 Погасить кредит")],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

def profile_menu_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="profile_bonus"), InlineKeyboardButton(text="📦 Кейс", callback_data="profile_case")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")]
    ])

def bet_actions_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data="bet_repeat"), InlineKeyboardButton(text="⏫ Удвоить", callback_data="bet_double")]
    ])

def mod_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],
        [KeyboardButton(text="⚠️ Предупреждение"), KeyboardButton(text="📌 Закрепить")],
        [KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS Админу")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В главное меню")]
    ], resize_keyboard=True)

def admin_panel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="👑 Админ-панель")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="📖 Хелп"), KeyboardButton(text="⬅️ В главное меню")]
    ], resize_keyboard=True)