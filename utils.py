import asyncio
from config import MAX_BIGINT, MAX_BALANCE, MAX_BANK

last_bot_message = {}

async def send_clean(message, text: str, **kwargs):
    chat_id = message.chat.id
    old_id = last_bot_message.get(chat_id)
    if old_id:
        try:
            await message.bot.delete_message(chat_id, old_id)
        except Exception:
            pass
    sent = await message.answer(text, **kwargs)
    last_bot_message[chat_id] = sent.message_id
    return sent

def clamp(x, min_val=-MAX_BIGINT, max_val=MAX_BIGINT):
    try:
        return max(min_val, min(int(x), max_val))
    except Exception:
        return 0

def fmt_num(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

def make_xp_bar(xp: int) -> str:
    progress = xp % 100
    fill = int(progress / 100 * 10)
    return "▰" * fill + "▱" * (10 - fill)

def get_rank_name(level: int) -> str:
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