# ═══════════════════════════════════════════════════════════════
# АВТОУДАЛЕНИЕ СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════

last_bot_message = {}

async def send_clean(message, text: str, **kwargs):
    """Удаляет прошлое сообщение бота и отправляет новое."""
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