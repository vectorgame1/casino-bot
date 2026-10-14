# ═══════════════════════════════════════════════════════════════
# admin/menu.py — REPLY-МЕНЮ АДМИНА
# ═══════════════════════════════════════════════════════════════

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


# ═══════════════ ГЛАВНОЕ МЕНЮ АДМИНА ═══════════════

def admin_main_kb() -> ReplyKeyboardMarkup:
    """Главное Reply-меню админа."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="💰 Экономика"), KeyboardButton(text="🛒 Контент")],
            [KeyboardButton(text="📢 Связь"), KeyboardButton(text="📊 Мониторинг")],
            [KeyboardButton(text="💳 Кредиты"), KeyboardButton(text="🛡️ Модерация")],
            [KeyboardButton(text="⚙️ Бот"), KeyboardButton(text="📋 Команды")],
            [KeyboardButton(text="🔙 Назад в игрока")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: БОТ ═══════════════

def admin_bot_kb() -> ReplyKeyboardMarkup:
    """Подменю управления ботом."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔴 Выключить бота"), KeyboardButton(text="🟢 Включить бота")],
            [KeyboardButton(text="🔄 Перезапуск"), KeyboardButton(text="📊 Статус бота")],
            [KeyboardButton(text="📜 Логи"), KeyboardButton(text="⚠️ Ошибки")],
            [KeyboardButton(text="🛠️ Тех.работы ВКЛ"), KeyboardButton(text="✅ Тех.работы ВЫКЛ")],
            [KeyboardButton(text="🌐 WebApp")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: ИГРОКИ ═══════════════

def admin_players_kb() -> ReplyKeyboardMarkup:
    """Подменю управления игроками."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Пробив"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="📊 XP")],
            [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
            [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="🎬 Следить")],
            [KeyboardButton(text="🗑 Удалить"), KeyboardButton(text="📋 Список")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: ИГРЫ ═══════════════

def admin_games_kb() -> ReplyKeyboardMarkup:
    """Подменю управления играми."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Вкл все"), KeyboardButton(text="❌ Выкл все")],
            [KeyboardButton(text="🎡 Рулетка"), KeyboardButton(text="🎰 Слоты")],
            [KeyboardButton(text="🪙 Монетка"), KeyboardButton(text="💣 Мины")],
            [KeyboardButton(text="🃏 БЖ"), KeyboardButton(text="⚔️ Дуэль")],
            [KeyboardButton(text="🎰 Event ×2")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: ЭКОНОМИКА ═══════════════

def admin_economy_kb() -> ReplyKeyboardMarkup:
    """Подменю экономики."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💰 Лимиты")],
            [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="📈 Проценты банка")],
            [KeyboardButton(text="💸 Кэшбэк")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: КОНТЕНТ ═══════════════

def admin_content_kb() -> ReplyKeyboardMarkup:
    """Подменю контента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎰 Кейсы")],
            [KeyboardButton(text="💰 Tokens-паки"), KeyboardButton(text="👑 VIP")],
            [KeyboardButton(text="⭐ XP-паки")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: СВЯЗЬ ═══════════════

def admin_comm_kb() -> ReplyKeyboardMarkup:
    """Подменю связи (рассылки)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📨 Всем"), KeyboardButton(text="📨 По ID")],
            [KeyboardButton(text="📨 В группу"), KeyboardButton(text="📨 Активным")],
            [KeyboardButton(text="📨 Неактивным"), KeyboardButton(text="📨 Топ-100")],
            [KeyboardButton(text="📨 VIP"), KeyboardButton(text="📨 Забаненным")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: МОНИТОРИНГ ═══════════════

def admin_monitor_kb() -> ReplyKeyboardMarkup:
    """Подменю мониторинга."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Онлайн")],
            [KeyboardButton(text="🎮 Топ игр"), KeyboardButton(text="🏆 Big Wins")],
            [KeyboardButton(text="💰 Профит"), KeyboardButton(text="🚨 Алерты")],
            [KeyboardButton(text="📈 График"), KeyboardButton(text="📋 Отчёт")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: КРЕДИТЫ ═══════════════

def admin_credits_kb() -> ReplyKeyboardMarkup:
    """Подменю кредитов."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🚫 Должники")],
            [KeyboardButton(text="🔓 Разблокировать"), KeyboardButton(text="📋 Все кредиты")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: МОДЕРАЦИЯ ═══════════════

def admin_moderation_kb() -> ReplyKeyboardMarkup:
    """Подменю модерации."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Бан"), KeyboardButton(text="✅ Разбан")],
            [KeyboardButton(text="🔇 Мут"), KeyboardButton(text="🔊 Размут")],
            [KeyboardButton(text="⚠️ Варн"), KeyboardButton(text="📋 Варны")],
            [KeyboardButton(text="📜 История банов"), KeyboardButton(text="📋 Список банов")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )


# ═══════════════ ПОДМЕНЮ: КОМАНДЫ ═══════════════

def admin_commands_kb() -> ReplyKeyboardMarkup:
    """Подменю команд."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Все команды")],
            [KeyboardButton(text="🔙 Назад в админ")],
        ],
        resize_keyboard=True,
    )