# ═══════════════════════════════════════════════════════════════
# admin/scan.py — ПРОБИВ ИГРОКА
# ═══════════════════════════════════════════════════════════════

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from config import ADMIN_ID, TZ_MINSK
from utils import fmt_num, get_rank_name
from database import (
    get_conn, release_conn,
    get_user, get_user_id_by_username,
)


def register(dp: Dispatcher):
    """Регистрирует команду /scan."""

    @dp.message(Command("scan", "пробив"))
    async def cmd_scan(message: Message):
        """Пробив игрока: вся инфа."""
        if message.from_user.id != ADMIN_ID:
            return

        args = message.text.split()
        uid = None

        # ═══ Способ 1: Reply на сообщение ═══
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
            if not target.is_bot:
                uid = target.id

        # ═══ Способ 2: Парсим аргумент ═══
        if not uid and len(args) >= 2:
            target = args[1].strip()

            # 2.1: /scan me — свой профиль
            if target.lower() in ("me", "я", "себя", "мой"):
                uid = message.from_user.id

            # 2.2: /scan @username
            elif target.startswith('@'):
                uid = get_user_id_by_username(target[1:])

            # 2.3: /scan 6403424348 (ID)
            elif target.isdigit():
                uid = int(target)

        # ═══ Если ничего не нашли — показываем помощь ═══
        if not uid:
            await message.answer(
                "🔍 <b>ПРОБИВ ИГРОКА</b>\n"
                "▬▬▬▬▬▬▬▬▬▬\n\n"
                "<b>Способы:</b>\n"
                "1️⃣ <code>/scan @username</code> — по юзернейму\n"
                "2️⃣ <code>/scan 6403424348</code> — по ID\n"
                "3️⃣ <code>/scan me</code> — свой профиль\n"
                "4️⃣ Ответь на сообщение игрока и напиши <code>/scan</code>\n\n"
                "💡 Также можно: <code>/пробив @user</code>",
                parse_mode="HTML"
            )
            return

        # ═══ Собираем инфу ═══
        conn = get_conn()
        c = conn.cursor()

        # Проверка существования игрока
        c.execute("""SELECT username, balance, bank, xp, banned, unlimited,
                     total_lost, total_won, ref_count, ref_earnings,
                     login_streak, birthday, credit_blocked
                     FROM users WHERE user_id = %s""", (uid,))
        row = c.fetchone()

        if not row:
            c.close()
            release_conn(conn)
            await message.answer(
                f"❌ <b>Игрок не найден</b>\n\n"
                f"🆔 ID: <code>{uid}</code>",
                parse_mode="HTML"
            )
            return

        username, balance, bank, xp, banned, unlimited, \
        total_lost, total_won, ref_count, ref_earnings, \
        login_streak, birthday, credit_blocked = row

        # Игровая статистика
        c.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE win > 0),
                     COALESCE(SUM(bet), 0), COALESCE(SUM(win), 0),
                     COALESCE(MAX(bet), 0), COALESCE(MAX(win), 0),
                     MAX(created_at)
                     FROM game_log WHERE user_id = %s""", (uid,))
        g_row = c.fetchone()
        total_games, total_wins, total_bet, total_win, max_bet, max_win, last_game = g_row

        # Алерты
        c.execute("SELECT COUNT(*) FROM alerts WHERE user_id = %s", (uid,))
        alerts_count = c.fetchone()[0]

        # Кредиты
        c.execute("""SELECT COUNT(*) FROM credits 
                     WHERE user_id = %s AND status IN ('active', 'overdue')""", (uid,))
        credits_count = c.fetchone()[0]

        # Транзакции
        c.execute("""SELECT COALESCE(SUM(amount) FILTER (WHERE amount > 0), 0),
                     COALESCE(SUM(amount) FILTER (WHERE amount < 0), 0)
                     FROM transactions WHERE user_id = %s""", (uid,))
        tx_row = c.fetchone()
        total_in, total_out = tx_row

        # Дата регистрации
        c.execute("SELECT MIN(created_at) FROM transactions WHERE user_id = %s", (uid,))
        reg_row = c.fetchone()
        reg_date = reg_row[0].strftime('%d.%m.%Y') if reg_row and reg_row[0] else "?"

        # Место в топе
        c.execute("SELECT COUNT(*) FROM users WHERE balance > %s", (balance,))
        top_place = c.fetchone()[0] + 1
        c.execute("SELECT COUNT(*) FROM users")
        total_players = c.fetchone()[0]

        c.close()
        release_conn(conn)

        # ═══ Расчёты ═══
        winrate = round(total_wins / total_games * 100) if total_games > 0 else 0
        profit = (total_win or 0) - (total_bet or 0)
        level = xp // 100
        rank = get_rank_name(level)

        # Статус
        status_line = ""
        if banned:
            status_line += "🚫 БАН "
        if unlimited:
            status_line += "♾️ БЕЗЛИМИТ "
        if credit_blocked:
            status_line += "⚠️ КРЕДИТ-БЛОК "
        if not status_line:
            status_line = "✅ АКТИВЕН"

        # Последняя игра
        last_game_str = "—"
        if last_game:
            if last_game.tzinfo is None:
                last_game = last_game.replace(tzinfo=TZ_MINSK)
            mins_ago = int((datetime.now(TZ_MINSK) - last_game).total_seconds() // 60)
            if mins_ago < 60:
                last_game_str = f"{mins_ago} мин назад"
            elif mins_ago < 1440:
                last_game_str = f"{mins_ago // 60} ч назад"
            else:
                last_game_str = f"{mins_ago // 1440} дн назад"

        # ═══ Красивый вывод ═══
        text = (
            f"🔍 <b>ПРОБИВ ИГРОКА</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬\n\n"
            f"👤 <b>{username or f'user_{uid}'}</b>\n"
            f"🆔 <code>{uid}</code>\n"
            f"📅 Регистрация: <b>{reg_date}</b>\n"
            f"📊 Последняя игра: <b>{last_game_str}</b>\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"📡 СТАТУС: {status_line}\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"🎖 Ранг: <b>{rank}</b>\n"
            f"⭐ XP: <b>{fmt_num(xp)}</b> (ур. {level})\n"
            f"🔥 Streak: <b>{login_streak or 0}</b> дн.\n"
            f"🎂 ДР: <b>{birthday or '—'}</b>\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"💰 БАЛАНСЫ\n"
            f"💎 {fmt_num(balance)} · 🏦 {fmt_num(bank)}\n"
            f"📊 Всего: <b>{fmt_num(balance + bank)}</b>\n"
            f"🏅 Место: <b>#{top_place}</b> из {total_players}\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 ИГРЫ\n"
            f"Игр: <b>{fmt_num(total_games)}</b> · Побед: <b>{fmt_num(total_wins)}</b> ({winrate}%)\n"
            f"Профит: <b>{'+' if profit >= 0 else ''}{fmt_num(profit)}</b>\n"
            f"🔥 Best: <b>{fmt_num(max_win)}</b>\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"💸 Приход: <b>+{fmt_num(total_in or 0)}</b>\n"
            f"📤 Расход: <b>{fmt_num(total_out or 0)}</b>\n\n"
            f"▬▬▬▬▬▬▬▬▬▬\n"
            f"🚨 Алерты: <b>{alerts_count}</b>\n"
            f"💳 Кредиты: <b>{credits_count}</b>\n"
            f"👥 Рефералы: <b>{ref_count or 0}</b>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 История", callback_data=f"u_hist_{uid}"),
             InlineKeyboardButton(text="💰 Транзакции", callback_data=f"u_tx_{uid}")],
            [InlineKeyboardButton(text="🚨 Алерты", callback_data=f"u_alerts_{uid}")],
        ])

        await message.answer(text, parse_mode="HTML", reply_markup=kb)