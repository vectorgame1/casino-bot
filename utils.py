# utils.py — ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (БРОНЕБОЙНЫЕ)
import asyncio
from config import MAX_BIGINT, MAX_BALANCE, MAX_BANK

# ═══════════════ АВТОУДАЛЕНИЕ ═══════════════

last_bot_message = {}

async def send_clean(message, text: str, **kwargs):
    """Удаляет прошлое сообщение бота в этом чате и отправляет новое."""
    chat_id = message.chat.id
    old_id = last_bot_message.get(chat_id)
    
    # Удаляем старое
    if old_id:
        try:
            await message.bot.delete_message(chat_id, old_id)
        except Exception:
            pass
            
    # Пытаемся отправить новое
    try:
        sent = await message.answer(text, **kwargs)
    except Exception as e:
        # Если произошла ошибка с HTML-тегами (например, кривой символ)
        if "parse_mode" in kwargs:
            del kwargs["parse_mode"]
        
        # Убираем HTML из текста (на всякий случай)
        clean_text = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        
        try:
            sent = await message.answer(clean_text, **kwargs)
        except Exception:
            # Если и это не сработало — просто отправляем как есть
            sent = await message.answer("⚠️ Ошибка в тексте, но сообщение доставлено.")
            
    last_bot_message[chat_id] = sent.message_id
    return sent

# ═══════════════ ФОРМАТИРОВАНИЕ И ЛИМИТЫ ═══════════════

def clamp(x, min_val=-MAX_BIGINT, max_val=MAX_BIGINT):
    """Ограничивает число в пределах BIGINT."""
    try:
        return max(min_val, min(int(x), max_val))
    except Exception:
        return 0

def clamp_balance(amount: int) -> tuple:
    """Ограничивает баланс до MAX_BALANCE. Возвращает (сумма, излишек)."""
    amount = clamp(amount)
    if amount > MAX_BALANCE:
        return MAX_BALANCE, amount - MAX_BALANCE
    return amount, 0

def clamp_bank(amount: int) -> tuple:
    """Ограничивает банк до MAX_BANK. Возвращает (сумма, излишек)."""
    amount = clamp(amount)
    if amount > MAX_BANK:
        return MAX_BANK, amount - MAX_BANK
    return amount, 0

def fmt_num(n) -> str:
    """Форматирует число с пробелами: 1 000 000."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

# ═══════════════ ИГРОВЫЕ УТИЛИТЫ ═══════════════

def make_xp_bar(xp: int) -> str:
    """Прогресс-бар XP: ▰▰▰▱▱▱▱▱▱▱"""
    progress = xp % 100
    fill = int(progress / 100 * 10)
    return "▰" * fill + "▱" * (10 - fill)

def get_rank_name(level: int) -> str:
    """Ранг по уровню."""
    if level < 5:   return f"🥉 Бронза {['I','II','III'][min(level, 2)]}"
    if level < 10:  return "🥈 Серебро III"
    if level < 15:  return "🥈 Серебро II"
    if level < 20:  return "🥈 Серебро I"
    if level < 25:  return "🥇 Золото III"
    if level < 30:  return "🥇 Золото II"
    if level < 35:  return "🥇 Золото I"
    if level < 45:  return "💎 Платина"
    if level < 55:  return "💠 Бриллиант"
    return "🖤 Чёрная карта"