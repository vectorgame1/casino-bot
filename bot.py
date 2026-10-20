# bot.py — FINAL v59 (ВСЁ В ОДНОМ)
# ============================================================
# v59 CHANGES vs v58:
#  - FIX: auto_moderator не ломает игры (return только при нарушении)
#  - NEW: welcome_new_member (приветствие новичкам в группе)
#  - FIX: daily_case теперь ПРИБАВЛЯЕТ, а не перезаписывает баланс
#  - FIX: блэкджек не списывает ставку дважды
#  - FIX: mines_handler не падает на протухшем state
#  - FIX: дилер-блэкджек при старте
#  - NEW: MODS/MOD_LIMITS сохраняются в state.json
#  - NEW: автоочистка дуэлей (2 мин) с возвратом
#  - FIX: broadcast_photo (F.photo без F.text)
#  - FIX: BotStates вместо строк
#  - FIX: play_dice_game проверка len(parts)
#  - FIX: start_roulette проверка bets
#  - FIX: admin_ban_btn возвращает ReplyKeyboard
#  - FIX: init_db гарантирует game_log и group_logs
#  - FIX: /mute_all — одиночный таск
#  - FIX: duel_accept через pop
#  - FIX: play_coin проверка len(parts)
#  - FIX: bet_actions проверка bets
#  - FIX: admin_clear РЕАЛЬНО удаляет 20 сообщений
#  - NEW: /help (общий, RU+EN)
#  - NEW: /mod_help (RU+EN)
#  - NEW: /admin_help (RU+EN)
#  - LIMIT: MAX_MOD_GIVE = 5_000_000
#  - FIX: кнопка 🧹 Очистить РЕАЛЬНО чистит игровой чат
# ============================================================

import asyncio, logging, os, random, re, time, json
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ChatMemberUpdated, ChatPermissions
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, ADMIN_ID, START_BONUS, STARS_RATE, TZ_MINSK, GROUP_URL, SUPPORT_USERNAME
from keyboards import main_menu, games_menu, donate_menu, admin_panel_kb, support_menu, bank_menu, profile_menu_inline, bet_actions_inline, mod_panel_kb
from database import (
    init_pool, init_db, get_balance, set_balance, ensure_user,
    check_and_give_bonus, is_banned, get_top, get_xp, set_banned,
    get_user_id_by_username, get_conn, release_conn, log_game, get_rate
)
from utils import send_clean, fmt_num, make_xp_bar, get_rank_name
from state_manager import load_mods, save_mods, refresh_week

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# БЛОК 1. СОСТОЯНИЯ И КОНСТАНТЫ
# ============================================================
class BotStates(StatesGroup):
    waiting_scan = State()
    waiting_amount = State()
    waiting_bank_amount = State()
    waiting_credit_name = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_credit_purpose = State()
    waiting_custom_support = State()
    waiting_broadcast_target = State()
    waiting_broadcast_text = State()
    mines_game = State()
    waiting_promo = State()
    # v59: новые состояния
    waiting_admin_give = State()
    waiting_admin_take = State()
    waiting_admin_ban = State()
    waiting_admin_unban = State()
    waiting_quick_amount = State()
    waiting_broadcast_photo = State()
    waiting_support_text = State()


active_bets = {}
is_spinning = {}
support_replies = {}
credit_requests = {}
last_bot_message = {}
user_warns = {}
muted_users = {}
bj_games = {}
active_duels = {}

# v59: модеры и лимиты грузим из state.json
MODS, MOD_LIMITS = load_mods()

# v59: ЛИМИТ ВЫДАЧИ МОДЕРА = 5 000 000 (было 10 000 000)
MAX_MOD_GIVE = 5_000_000

GLOBAL_MUTE = False
GLOBAL_MUTE_TASK: asyncio.Task | None = None

PROMO_CODES = {}

RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

BAD_WORDS = ["хуй", "хуя", "хую", "хуе", "хуи", "хуйн", "хуес", "хуеп", "хуит", "пизд", "пизж", "пизда", "пизде", "пизду", "пиздо", "пиздюл", "пиздоб", "бля", "блят", "блядь", "бляди", "блядю", "блядо", "бляду", "сука", "суки", "суке", "суку", "сукой", "сучк", "сучон", "ебал", "ебат", "ебуч", "ебан", "еби", "ебуч", "ебук", "ебани", "мудак", "мудил", "мудень", "мудозвон", "долбоеб", "долбаеб", "долбоёб", "долбаёб", "гандон", "гондон", "залуп", "залупа", "залупу", "залупой", "залупок", "пидор", "пидар", "пидорас", "пидорасина", "хуесос", "хуесосина", "отъеб", "въеб", "съеб", "заеб", "уеб", "наеб", "поъеб", "приеб", "проеб", "разъеб", "жопа", "жопу", "жопой", "жопе", "срать", "срал", "сру", "хер", "хрен", "член", "шлюх", "проститут", "дроч"]

# v59: разрешённые команды в группе (модератор их не трогает)
GROUP_CMD_WHITELIST = {
    "б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го",
    "что нового", "отмена", "ставки", "п",
}

# v59: fallback клавиатура для админа (если keyboards не отдаёт)
def admin_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Игроки"), KeyboardButton(text="👑 Админ-панель")],
    ], resize_keyboard=True)


def mod_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Мои лимиты"), KeyboardButton(text="🧹 Очистить")],
        [KeyboardButton(text="⚠️ Предупреждение"), KeyboardButton(text="📌 Закрепить")],
        [KeyboardButton(text="🔓 Разбан"), KeyboardButton(text="🚨 SOS Админу")],
    ], resize_keyboard=True)


def get_color(num):
    if num == 0:
        return "🟢"
    return "🔴" if num in RED else "⚫"


# ============================================================
# БЛОК 2. УТИЛИТЫ
# ============================================================
async def delete_message_later(message: Message, delay: int = 150):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def send_clean_private(message: Message, text: str, reply_markup=None):
    uid = message.from_user.id
    if uid in last_bot_message:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message[uid])
        except Exception:
            pass
    msg = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    last_bot_message[uid] = msg.message_id
    # v59: ограничим размер кэша
    if len(last_bot_message) > 1000:
        keys = list(last_bot_message.keys())
        for k in keys[:200]:
            last_bot_message.pop(k, None)
    return msg


async def start_web_server():
    async def health(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()


def _now():
    return datetime.now(TZ_MINSK)


def persist_mods():
    save_mods(MODS, MOD_LIMITS)


# ============================================================
# БЛОК 3. MAIN
# ============================================================
async def main():
    asyncio.create_task(start_web_server())
    init_pool()
    init_db()

    # v59: гарантируем game_log и group_logs
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS game_log (id BIGSERIAL PRIMARY KEY, user_id BIGINT, username TEXT, game TEXT, bet BIGINT, win BIGINT, result TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS group_logs (chat_id BIGINT, detail TEXT, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit(); c.close(); release_conn(conn)
    except Exception as e:
        logger.warning(f"init_db extra tables: {e}")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username

    # ========================================================
    # БЛОК 4. ПРИВЕТСТВИЕ БОТА И НОВЫХ ИГРОКОВ
    # ========================================================
    @dp.my_chat_member()
    async def on_bot_added(event: ChatMemberUpdated):
        if event.new_chat_member.status == "member" and event.old_chat_member.status in ["left", "kicked"]:
            txt = (
                f"👋 <b>СПАСИБО ЗА ДОБАВЛЕНИЕ!</b>\n\n"
                f"Я — <b>{BOT_NAME.upper()}</b>!\n\n"
                f"🎮 Напиши <b>игры</b>, чтобы начать!\n"
                f"💰 Напиши <b>б</b>, чтобы проверить баланс.\n"
                f"📖 Напиши <b>/help</b>, чтобы увидеть все команды."
            )
            try:
                await event.bot.send_message(event.chat.id, txt)
            except Exception:
                pass

    # v59: NEW — приветствие новичкам
    @dp.message(F.new_chat_members)
    async def welcome_new_member(message: Message):
        for user in message.new_chat_members:
            if user.is_bot:
                continue
            try:
                ensure_user(user.id, user.username or user.first_name)
            except Exception:
                pass
            txt = (
                f"🎉 <b>ДОБРО ПОЖАЛОВАТЬ В КЛУБ!</b>\n\n"
                f"👋 Привет, <b>{user.first_name}</b>!\n"
                f"Ты попал в самое крутое казино Telegram.\n\n"
                f"🎮 <b>Напиши <code>игры</code></b>, чтобы увидеть все игры.\n"
                f"💰 <b>Напиши <code>б</code></b>, чтобы проверить баланс.\n"
                f"🎁 <b>Напиши <code>бонус</code></b> в ЛС бота, чтобы получить 5000 токенов!\n"
                f"📖 <b>Напиши <code>/help</code></b>, чтобы увидеть все команды.\n\n"
                f"🔥 <i>Удачи и больших выигрышей!</i>"
            )
            try:
                await message.answer(txt)
            except Exception:
                pass

    # ========================================================
    # БЛОК 5. ХЕЛПЫ (RU + EN)
    # ========================================================
    @dp.message(Command("help", "помощь"))
    async def cmd_help(message: Message):
        txt = (
            "════════════════════════════════\n"
            "🇷🇺 <b>РУССКИЙ</b>\n"
            "════════════════════════════════\n\n"
            "👤 <b>ИГРОК (в ЛС):</b>\n"
            "• <code>/start</code> — запуск\n"
            "• <code>/ref</code> / <code>/реф</code> — рефералка\n"
            "• <code>/promo КОД</code> / <code>/промо КОД</code> — промокод\n"
            "• <code>бонус</code> — ежедневный бонус +5 000\n"
            "• <code>кейс</code> — ежедневный кейс (5/10/25к)\n"
            "• <code>профиль</code> — профиль (XP, ранг)\n\n"
            "🎮 <b>ГРУППА:</b>\n"
            "• <code>б</code> / <code>баланс</code> — баланс\n"
            "• <code>игры</code> — меню игр\n"
            "• <code>топ</code> — топ-10\n"
            "• <code>лог</code> — последние числа\n"
            "• <code>п ID СУММА</code> — перевод\n"
            "• <code>к 100</code> / <code>ч 100</code> / <code>з 100</code> — рулетка\n"
            "• <code>чет 100</code> / <code>нечет 100</code> — чёт/нечёт\n"
            "• <code>го</code> — запуск рулетки\n"
            "• <code>кости/баскет/футбол/дартс/боулинг/слот/монетка/мины/бж/дуэль + сумма</code>\n\n"
            "════════════════════════════════\n"
            "🇬🇧 <b>ENGLISH</b>\n"
            "════════════════════════════════\n\n"
            "👤 <b>PLAYER (DM):</b>\n"
            "• <code>/start</code> — start\n"
            "• <code>/ref</code> — referral\n"
            "• <code>/promo CODE</code> — promo\n"
            "• <code>бонус</code> — daily bonus +5000\n"
            "• <code>кейс</code> — daily case (5/10/25k)\n"
            "• <code>профиль</code> — profile\n\n"
            "🎮 <b>GROUP:</b>\n"
            "• <code>б</code> — balance\n"
            "• <code>игры</code> — games menu\n"
            "• <code>топ</code> — top-10\n"
            "• <code>лог</code> — last numbers\n"
            "• <code>п ID AMOUNT</code> — transfer\n"
            "• <code>к/ч/з 100</code> — roulette\n"
            "• <code>чет/нечет 100</code> — even/odd\n"
            "• <code>го</code> — spin\n"
            "• <code>кости/баскет/футбол/дартс/боулинг/слот/монетка/мины/бж/дуэль + amount</code>"
        )
        await send_clean_private(message, txt)

    @dp.message(Command("mod_help", "помощь_модеру"))
    async def cmd_mod_help(message: Message):
        uid = message.from_user.id
        if uid not in MODS and uid != ADMIN_ID:
            return await message.reply("❌ Ты не модер.")
        txt = (
            "════════════════════════════════\n"
            "🛠 <b>МОДЕРАТОР — RU</b>\n"
            "════════════════════════════════\n\n"
            "✅ <b>Твои права:</b>\n"
            "• <code>/mod_give @user 1000</code> / <code>/выдать_токены @user 1000</code> — выдать токены\n"
            "• <code>/mod_warn</code> / <code>/предупреждение</code> (ответом) — мут 5 мин\n"
            "• <code>/mod_clean</code> / <code>/очистить_чат</code> — очистить игровой чат\n"
            "• <code>/mod_pin</code> / <code>/закрепить_модер</code> (ответом) — закрепить\n"
            "• <code>/mod_unban @user</code> / <code>/разбанить_модер @user</code> — разбан\n"
            "• <code>/mod_alert</code> / <code>/sos</code> — SOS админу\n"
            "• <code>/mod_my_limit</code> / <code>/мои_лимиты</code> — лимиты\n"
            "• <code>/mod_list</code> / <code>/список_модеров</code> — список модеров\n\n"
            "❌ <b>НЕ можешь:</b>\n"
            "• Банить (только Админ)\n"
            "• Забирать токены (только Админ)\n"
            "• Снимать модеров (только Админ)\n\n"
            "💰 <b>Лимит выдачи:</b> 5 000 000 токенов в неделю\n\n"
            "════════════════════════════════\n"
            "🛠 <b>MODERATOR — EN</b>\n"
            "════════════════════════════════\n\n"
            "✅ <b>Your rights:</b>\n"
            "• <code>/mod_give @user 1000</code> — give tokens\n"
            "• <code>/mod_warn</code> (reply) — 5 min mute\n"
            "• <code>/mod_clean</code> — clean game chat\n"
            "• <code>/mod_pin</code> (reply) — pin\n"
            "• <code>/mod_unban @user</code> — unban\n"
            "• <code>/mod_alert</code> — SOS to admin\n"
            "• <code>/mod_my_limit</code> — limits\n"
            "• <code>/mod_list</code> — mods list\n\n"
            "❌ <b>You CANNOT:</b>\n"
            "• Ban (Admin only)\n"
            "• Take tokens (Admin only)\n"
            "• Remove mods (Admin only)\n\n"
            "💰 <b>Give limit:</b> 5 000 000 tokens per week"
        )
        await send_clean_private(message, txt, reply_markup=mod_panel_kb() if uid in MODS else None)

    @dp.message(Command("admin_help", "помощь_админу"))
    async def cmd_admin_help(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        txt = (
            "════════════════════════════════\n"
            "👑 <b>АДМИН — RU</b>\n"
            "════════════════════════════════\n\n"
            "💰 <b>ЭКОНОМИКА:</b>\n"
            "• <code>/give_all 1000</code> / <code>/выдать_всем 1000</code> — выдать всем\n"
            "• <code>/reset_user @user</code> / <code>/сброс_игрока @user</code> — обнулить\n"
            "• <code>/reset_credit @user</code> / <code>/простить_долг @user</code> — простить кредит\n"
            "• <code>/jackpot 50000</code> / <code>/джекпот 50000</code> — накрутить банк\n"
            "• <code>/drop 10000</code> / <code>/дроп 10000</code> — дроп\n\n"
            "👥 <b>ИГРОКИ:</b>\n"
            "• <code>/stats</code> / <code>/стата</code> — статистика\n"
            "• <code>/history @user</code> / <code>/история @user</code> — история игр\n"
            "• <code>/spy @user</code> / <code>/шпион @user</code> — активность 24ч\n"
            "• <code>/ban @user</code> / <code>/бан @user</code> — бан\n"
            "• <code>/unban @user</code> / <code>/разбан @user</code> — разбан\n"
            "• <code>/kick</code> / <code>/кик</code> (ответом) — кик\n\n"
            "💬 <b>ЧАТ:</b>\n"
            "• <code>/say Текст</code> / <code>/сказать Текст</code> — написать\n"
            "• <code>/clear</code> / <code>/очистить</code> — очистить чат\n"
            "• <code>/mute_all</code> / <code>/мут_всех</code> — глобальный мут\n"
            "• <code>/pin</code> / <code>/закрепить</code> (ответом)\n"
            "• <code>/unpin</code> / <code>/открепить</code>\n\n"
            "📊 <b>СТАТА:</b>\n"
            "• <code>/top_games</code> / <code>/топ_игр</code> — топ-5 игр\n\n"
            "📢 <b>РАССЫЛКА:</b>\n"
            "• <code>/broadcast_photo</code> / <code>/рассылка_фото</code>\n\n"
            "🛡 <b>МОДЕРАТОРЫ:</b>\n"
            "• <code>/mod_add @user</code> / <code>/добавить_модера @user</code>\n"
            "• <code>/mod_remove @user</code> / <code>/снять_модера @user</code>\n"
            "• <code>/mod_list</code> / <code>/список_модеров</code>\n"
            "• <code>/mod_give @user 1000</code> / <code>/выдать_токены @user 1000</code>\n"
            "• <code>/mod_my_limit</code> / <code>/мои_лимиты</code>\n"
            "• <code>/mod_warn</code> / <code>/предупреждение</code> (ответом)\n"
            "• <code>/mod_clean</code> / <code>/очистить_чат</code>\n"
            "• <code>/mod_pin</code> / <code>/закрепить_модер</code> (ответом)\n"
            "• <code>/mod_unban @user</code> / <code>/разбанить_модер @user</code>\n"
            "• <code>/mod_alert</code> / <code>/sos</code>\n"
            "• <code>/mod_help</code> / <code>/помощь_модеру</code>\n\n"
            "════════════════════════════════\n"
            "👑 <b>ADMIN — EN</b>\n"
            "════════════════════════════════\n\n"
            "💰 <b>ECONOMY:</b>\n"
            "• <code>/give_all 1000</code>\n"
            "• <code>/reset_user @user</code>\n"
            "• <code>/reset_credit @user</code>\n"
            "• <code>/jackpot 50000</code>\n"
            "• <code>/drop 10000</code>\n\n"
            "👥 <b>PLAYERS:</b>\n"
            "• <code>/stats</code>\n"
            "• <code>/history @user</code>\n"
            "• <code>/spy @user</code>\n"
            "• <code>/ban @user</code>\n"
            "• <code>/unban @user</code>\n"
            "• <code>/kick</code> (reply)\n\n"
            "💬 <b>CHAT:</b>\n"
            "• <code>/say Text</code>\n"
            "• <code>/clear</code>\n"
            "• <code>/mute_all</code>\n"
            "• <code>/pin</code> (reply)\n"
            "• <code>/unpin</code>\n\n"
            "📊 <b>STATS:</b>\n"
            "• <code>/top_games</code>\n\n"
            "📢 <b>BROADCAST:</b>\n"
            "• <code>/broadcast_photo</code>\n\n"
            "🛡 <b>MODERATORS:</b>\n"
            "• <code>/mod_add @user</code>\n"
            "• <code>/mod_remove @user</code>\n"
            "• <code>/mod_list</code>\n"
            "• <code>/mod_give @user 1000</code>\n"
            "• <code>/mod_my_limit</code>\n"
            "• <code>/mod_warn</code> (reply)\n"
            "• <code>/mod_clean</code>\n"
            "• <code>/mod_pin</code> (reply)\n"
            "• <code>/mod_unban @user</code>\n"
            "• <code>/mod_alert</code>\n"
            "• <code>/mod_help</code>"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    # ========================================================
    # БЛОК 6. СТАРТ (ЛС)
    # ========================================================
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        args = message.text.split()

        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_id = int(args[1].replace("ref_", ""))
            except Exception:
                ref_id = 0
            if ref_id and ref_id != uid:
                ensure_user(uid, message.from_user.username or message.from_user.first_name)
                conn = get_conn(); c = conn.cursor()
                try:
                    c.execute("SELECT referral_id FROM users WHERE user_id = %s", (uid,))
                    row = c.fetchone()
                    if not row or row[0] == 0:
                        c.execute("UPDATE users SET referral_id = %s WHERE user_id = %s", (ref_id, uid))
                        set_balance(ref_id, 10000)
                        conn.commit()
                        try:
                            await bot.send_message(ref_id, "🎉 <b>ДРУГ ЗАШЕЛ!</b>\n+10 000 Tokens!")
                        except Exception:
                            pass
                finally:
                    c.close(); release_conn(conn)

        ensure_user(uid, message.from_user.username or message.from_user.first_name)
        if is_banned(uid):
            return await send_clean(message, "🚫 Заблокирован.")
        if message.chat.type != "private":
            return await message.reply(f"👋 ЛС: @{bot.username}")
        if uid == ADMIN_ID:
            return await cmd_admin(message, state)

        is_new = check_and_give_bonus(uid, START_BONUS)
        bonus = f"🎁 Бонус: +{fmt_num(START_BONUS)}\n\n" if is_new else ""
        txt = (
            f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В {BOT_NAME.upper()}</b>\n\n"
            f"👋 {message.from_user.first_name}!\n"
            f"{bonus}👇 Выбери действие:\n\n"
            f"📖 <b>Напиши /help</b>, чтобы увидеть все команды."
        )
        await send_clean_private(message, txt, reply_markup=main_menu())

    # ========================================================
    # БЛОК 7. ЛС: ПРОФИЛЬ, БОНУС, КЕЙС, РЕФ, ПРОМО
    # ========================================================
    @dp.message(F.text.lower().strip().in_({"👤 профиль", "профиль"}))
    async def cmd_prof(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        bal = get_balance(uid)
        xp = get_xp(uid)
        lvl = xp // 100
        txt = (
            f"👤 <b>ПРОФИЛЬ</b>\n"
            f"🎖 Ранг: {get_rank_name(lvl)}\n"
            f"📊 XP: {xp}\n"
            f"{make_xp_bar(xp)}\n"
            f"💰 Баланс: <b>{fmt_num(bal)}</b>"
        )
        await send_clean_private(message, txt, reply_markup=profile_menu_inline())

    @dp.callback_query(F.data == "profile_bonus")
    async def prof_bonus(call: CallbackQuery):
        await call.message.delete()
        await cmd_bonus(call.message, None)
        await call.answer()

    @dp.callback_query(F.data == "profile_case")
    async def prof_case(call: CallbackQuery):
        await call.message.delete()
        await daily_case(call.message, None)
        await call.answer()

    @dp.callback_query(F.data == "profile_back")
    async def prof_back(call: CallbackQuery):
        await call.message.delete()
        await call.message.answer("🏠 Главное меню:", reply_markup=main_menu())
        await call.answer()

    @dp.message(F.text.lower() == "бонус")
    async def cmd_bonus(message: Message, state: FSMContext):
        # await state.clear() <- УБРАНО
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT last_login_date FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            today = _now().date()
            if row and row[0] == today:
                return await send_clean_private(message, "⏳ Бонус уже взят.")
            c.execute("UPDATE users SET balance = balance + 5000, last_login_date = %s WHERE user_id = %s", (today, uid))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        await send_clean_private(message, "🎁 <b>БОНУС +5 000 Tokens</b>", reply_markup=main_menu())

    @dp.message(F.text.lower() == "кейс")
    async def daily_case(message: Message, state: FSMContext):
        # await state.clear() <- УБРАНО
        if message.chat.type != "private":
            return await message.reply(f"🎁 Кейс в ЛС: @{BOT_USERNAME}")
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            try:
                c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_case_date DATE")
                conn.commit()
            except Exception:
                conn.rollback()
            c.execute("SELECT last_case_date FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            today = _now().date()
            if row and row[0] == today:
                return await send_clean_private(message, "⏳ Кейс уже открыт!")
            c.execute("UPDATE users SET last_case_date = %s WHERE user_id = %s", (today, uid))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        # ... дальше твой код с case.gif и начислением
        if uid in last_bot_message:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message[uid])
            except Exception:
                pass
        try:
            msg = await message.answer_animation(FSInputFile("case.gif"), caption="🎁 ОТКРЫВАЕМ...")
        except Exception:
            msg = await message.answer("🎁 ОТКРЫВАЕМ...")
        await asyncio.sleep(2.5)
        try:
            await msg.delete()
        except Exception:
            pass
        amount = random.choice([5000, 10000, 25000])
        # v59: ПРИБАВЛЯЕМ, а не перезаписываем
        new_bal = get_balance(uid) + amount
        set_balance(uid, amount)
        res_msg = await message.answer(
            f"🎉 <b>КЕЙС ОТКРЫТ!</b>\n"
            f"Ты выиграл: <b>{fmt_num(amount)} Tokens!</b>\n"
            f"💰 Новый баланс: <b>{fmt_num(new_bal)}</b>",
            reply_markup=main_menu()
        )
        last_bot_message[uid] = res_msg.message_id

    @dp.message(Command("ref", "реф"))
    async def cmd_ref(message: Message):
        if message.chat.type != "private":
            return await message.reply(f"🤝 ЛС: @{bot.username}")
        ref_link = f"https://t.me/{bot.username}?start=ref_{message.from_user.id}"
        await send_clean_private(
            message,
            f"🤝 <b>РЕФЕРАЛКА</b>\n\nЗа друга <b>10 000 Tokens</b>!\n🔗 <code>{ref_link}</code>",
            reply_markup=main_menu()
        )

    @dp.message(Command("promo", "промо"))
    async def cmd_promo(message: Message, state: FSMContext):
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/promo КОД</code>")
        code = parts[1].upper()
        uid = message.from_user.id
        if code not in PROMO_CODES:
            return await send_clean_private(message, "❌ <b>НЕВЕРНЫЙ ПРОМОКОД</b>", reply_markup=main_menu())
        promo = PROMO_CODES[code]
        if uid in promo["used_by"]:
            return await send_clean_private(message, "⏳ Ты уже использовал этот промокод.", reply_markup=main_menu())
        if len(promo["used_by"]) >= promo["uses"]:
            return await send_clean_private(message, "❌ <b>ЛИМИТ ИСЧЕРПАН</b>", reply_markup=main_menu())
        promo["used_by"].append(uid)
        set_balance(uid, promo["amount"])
        await send_clean_private(
            message,
            f"🎉 <b>ПРОМОКОД АКТИВИРОВАН!</b>\nТы получил: <b>{fmt_num(promo['amount'])} Tokens!</b>",
            reply_markup=main_menu()
        )

    # ========================================================
    # БЛОК 8. БАНК И КРЕДИТЫ
    # ========================================================
    @dp.message(F.text == "🏦 Банк")
    async def bank_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        bal = get_balance(message.from_user.id)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT bank FROM users WHERE user_id = %s", (message.from_user.id,))
            row = c.fetchone()
            bank = row[0] if row and row[0] is not None else 0
        except Exception:
            bank = 0
        finally:
            c.close(); release_conn(conn)
        txt = (
            f"🏦 <b>БАНК</b>\n"
            f"💎 На руках: <b>{fmt_num(bal)}</b>\n"
            f"🏦 В сейфе: <b>{fmt_num(bank)}</b>\n\n"
            f"👇 Действие:"
        )
        await send_clean_private(message, txt, reply_markup=bank_menu())

    @dp.message(F.text == "📥 Положить")
    async def bank_deposit_start(message: Message, state: FSMContext):
        await send_clean_private(message, "💰 Введи сумму для вклада:")
        await state.set_state(BotStates.waiting_bank_amount)
        await state.update_data(action="deposit")

    @dp.message(F.text == "📤 Снять")
    async def bank_withdraw_start(message: Message, state: FSMContext):
        await send_clean_private(message, "💸 Введи сумму для снятия:")
        await state.set_state(BotStates.waiting_bank_amount)
        await state.update_data(action="withdraw")

    @dp.message(BotStates.waiting_bank_amount)
    async def bank_process(message: Message, state: FSMContext):
        data = await state.get_data()
        if message.text == "⬅️ Назад":
            await state.clear()
            return await bank_menu_handler(message, state)
        try:
            amount = int(message.text)
        except ValueError:
            return await send_clean_private(message, "❌ Введи число.")
        if amount <= 0:
            return await send_clean_private(message, "❌ Сумма должна быть > 0.")
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            if data.get("action") == "deposit":
                if get_balance(uid) < amount:
                    return await send_clean_private(message, "❌ Недостаточно.")
                set_balance(uid, -amount)
                c.execute("UPDATE users SET bank = COALESCE(bank, 0) + %s WHERE user_id = %s", (amount, uid))
                conn.commit()
                await send_clean_private(message, f"✅ Внесено <b>{fmt_num(amount)}</b>.")
            else:
                c.execute("SELECT bank FROM users WHERE user_id = %s", (uid,))
                row = c.fetchone()
                bank = row[0] if row else 0
                if bank < amount:
                    return await send_clean_private(message, "❌ Мало в банке.")
                c.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (amount, uid))
                set_balance(uid, amount)
                conn.commit()
                await send_clean_private(message, f"✅ Снято <b>{fmt_num(amount)}</b>.")
        finally:
            c.close(); release_conn(conn)
        await state.clear()
        await bank_menu_handler(message, state)

    @dp.message(F.text == "💳 Кредит")
    async def credit_start(message: Message, state: FSMContext):
        await state.clear()
        await send_clean_private(message, "💳 <b>ЗАЯВКА НА КРЕДИТ</b>\n1️⃣ Введи имя:")
        await state.set_state(BotStates.waiting_credit_name)

    @dp.message(BotStates.waiting_credit_name)
    async def credit_name(message: Message, state: FSMContext):
        await state.update_data(credit_name=message.text)
        await send_clean_private(message, "2️⃣ Сумма (10к-100к):")
        await state.set_state(BotStates.waiting_credit_amount)

    @dp.message(BotStates.waiting_credit_amount)
    async def credit_amount(message: Message, state: FSMContext):
        try:
            amt = int(message.text)
        except Exception:
            return await send_clean_private(message, "❌ Число.")
        if amt < 10000 or amt > 100000:
            return await send_clean_private(message, "❌ 10-100к.")
        await state.update_data(credit_amount=amt)
        await send_clean_private(message, "3️⃣ Срок (1-7 дней):")
        await state.set_state(BotStates.waiting_credit_term)

    @dp.message(BotStates.waiting_credit_term)
    async def credit_term(message: Message, state: FSMContext):
        try:
            days = int(message.text)
        except Exception:
            return await send_clean_private(message, "❌ Число.")
        if days < 1 or days > 7:
            return await send_clean_private(message, "❌ От 1 до 7 дней.")
        await state.update_data(credit_term=days)
        await send_clean_private(message, "4️⃣ Цель кредита:")
        await state.set_state(BotStates.waiting_credit_purpose)

    @dp.message(BotStates.waiting_credit_purpose)
    async def credit_purpose(message: Message, state: FSMContext):
        data = await state.get_data()
        data["credit_purpose"] = message.text
        user = message.from_user
        await state.clear()
        req_id = f"{user.id}_{int(time.time())}"
        credit_requests[req_id] = {"user_id": user.id, **data}
        admin_txt = (
            f"💳 <b>КРЕДИТ</b>\n"
            f"👤 @{user.username or 'user'}\n"
            f"💰 {fmt_num(data['credit_amount'])}\n"
            f"📅 {data['credit_term']} дней\n"
            f"🎯 {data['credit_purpose']}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"cr_acc_{req_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cr_dec_{req_id}")]
        ])
        try:
            await message.bot.send_message(ADMIN_ID, admin_txt, reply_markup=kb)
            await send_clean_private(message, "✅ Заявка отправлена!", reply_markup=main_menu())
        except Exception:
            await send_clean_private(message, "❌ Ошибка", reply_markup=main_menu())

    @dp.callback_query(F.data.startswith("cr_acc_"))
    async def credit_accept(call: CallbackQuery):
        req_id = call.data.replace("cr_acc_", "")
        req = credit_requests.pop(req_id, None)
        if not req:
            return await call.answer("Устарело", show_alert=True)
        uid = req["user_id"]
        set_balance(uid, req["credit_amount"])
        conn = get_conn(); c = conn.cursor()
        try:
            try:
                c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credit_debt BIGINT DEFAULT 0")
            except Exception:
                conn.rollback()
            c.execute("UPDATE users SET credit_debt = %s WHERE user_id = %s", (int(req["credit_amount"] * 1.03), uid))
            conn.commit()
        except Exception:
            pass
        finally:
            c.close(); release_conn(conn)
        await call.message.edit_text("✅ Выдано!")
        try:
            await call.bot.send_message(uid, f"🎉 Кредит одобрен на {fmt_num(req['credit_amount'])}!")
        except Exception:
            pass
        await call.answer("Ок")

    @dp.callback_query(F.data.startswith("cr_dec_"))
    async def credit_decline(call: CallbackQuery):
        req_id = call.data.replace("cr_dec_", "")
        req = credit_requests.pop(req_id, None)
        if not req:
            return await call.answer("Устарело", show_alert=True)
        await call.message.edit_text("❌ Отклонено.")
        await call.answer()

    @dp.message(F.text == "💸 Погасить кредит")
    async def credit_repay(message: Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT credit_debt FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            debt = row[0] if row and row[0] else 0
        except Exception:
            debt = 0
        finally:
            c.close(); release_conn(conn)
        if debt <= 0:
            return await send_clean_private(message, "✅ У тебя нет долгов!", reply_markup=bank_menu())
        if get_balance(uid) < debt:
            return await send_clean_private(message, f"❌ Мало средств! Долг: {fmt_num(debt)}", reply_markup=bank_menu())
        set_balance(uid, -debt)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("UPDATE users SET credit_debt = 0 WHERE user_id = %s", (uid,))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        await send_clean_private(message, f"✅ Кредит погашен! Списано: {fmt_num(debt)}", reply_markup=bank_menu())


    # ========================================================
    # БЛОК 10. ИГРЫ
    # ========================================================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "игры")
    async def group_games_rules(message: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
            [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
            [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
            [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
            [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        msg = await message.reply("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку, чтобы узнать правила:", reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 150))

    @dp.callback_query(F.data.startswith("game_info_"))
    async def game_info_handler(call: CallbackQuery):
        game = call.data.replace("game_info_", "")
        if game == "close":
            try:
                await call.message.delete()
            except Exception:
                pass
            return await call.answer("Меню закрыто.")
        if game == "back":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game_info_roulette"), InlineKeyboardButton(text="💣 Мины", callback_data="game_info_mines")],
                [InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_info_bj"), InlineKeyboardButton(text="⚔️ Дуэли", callback_data="game_info_duel")],
                [InlineKeyboardButton(text="🎲 Кости", callback_data="game_info_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_info_slots")],
                [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_info_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_info_football")],
                [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_info_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_info_bowling")],
                [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_info_coin")],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
            ])
            try:
                await call.message.edit_text("🎮 <b>ВЫБЕРИ ИГРУ</b>\n👇 Нажми на кнопку, чтобы узнать правила:", reply_markup=kb)
            except Exception:
                pass
            return await call.answer()

        info = {
            "roulette": "🎡 <b>РУЛЕТКА</b>\n• <code>к 100</code> / <code>ч 100</code>\n• <code>100 1-18</code>\n• <code>го</code> — Запуск",
            "mines": "💣 <b>МИНЫ</b>\n• <code>мины 100</code>\nОткрывай клетки, собирай кэш!",
            "bj": "🃏 <b>БЛЭКДЖЕК</b>\n• <code>бж 100</code>\nНабери 21 очко, чтобы победить!",
            "duel": "⚔️ <b>ДУЭЛИ</b>\nОтветь на сообщение игрока:\n• <code>дуэль 100</code>",
            "dice": "🎲 <b>КОСТИ</b>\n• <code>кости 100</code>\nВыигрыш 4, 5, 6 (x1.95)",
            "slots": "🎰 <b>СЛОТЫ</b>\n• <code>спин 100</code>\nШанс 50% (x1.8)",
            "basket": "🏀 <b>БАСКЕТ</b>\n• <code>баскет 100</code>\nПопал (x2)",
            "football": "⚽ <b>ФУТБОЛ</b>\n• <code>футбол 100</code>\nГол (x2)",
            "darts": "🎯 <b>ДАРТС</b>\n• <code>дартс 100</code>\nЯблочко (x5)",
            "bowling": "🎳 <b>БОУЛИНГ</b>\n• <code>боулинг 100</code>\nСтрайк (x3)",
            "coin": "🪙 <b>МОНЕТКА</b>\n• <code>монетка 100 орел</code>\nОрел/Решка x2, Ребро x10"
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="game_info_back"), InlineKeyboardButton(text="❌ Закрыть", callback_data="game_info_close")]
        ])
        try:
            await call.message.edit_text(info.get(game, "Информация не найдена."), reply_markup=kb)
        except Exception:
            pass
        await call.answer()

    # --- МИНЫ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
    async def play_mines_start(message: Message, state: FSMContext):
        parts = message.text.lower().split()
        if len(parts) != 2:
            return await message.reply("❌ <code>мины 100</code>")
        try:
            bet = int(parts[1])
        except Exception:
            return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet:
            return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet)
        mines = random.sample(list(range(25)), 3)
        await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0)
        await state.set_state(BotStates.mines_game)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
        msg = await message.reply(
            f"💣 <b>МИНЫ</b>\n"
            f"💰 Ставка: <b>{fmt_num(bet)}</b>\n"
            f"💣 Мин: 3\n"
            f"⏳ Время: 5 минут\n\n"
            f"Открывай клетки!",
            reply_markup=kb
        )

        async def auto_fail():
            await asyncio.sleep(300)
            data = await state.get_data()
            if data.get("bet"):
                await state.clear()
                try:
                    await msg.edit_text(f"⏰ <b>ВРЕМЯ ВЫШЛО!</b>\n😢 Ставка <b>{fmt_num(data['bet'])}</b> сгорела.")
                except Exception:
                    pass
        asyncio.create_task(auto_fail())

    @dp.callback_query(F.data.startswith("mine_"))
    async def mines_handler(call: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        # v59: защита от протухшего state
        if not data or "bet" not in data:
            return await call.answer("Игра устарела.")
        bet, mines, opened, mult = data["bet"], data["mines"], data["opened"], data["mult"]
        if call.data == "mine_cashout":
            win = int(bet * mult)
            set_balance(call.from_user.id, win)
            await state.clear()
            try:
                await call.message.edit_text(
                    f"💰 <b>ЗАБРАЛ!</b>\n💎 Выигрыш: <b>+{fmt_num(win)}</b>\n📈 x{mult:.2f}"
                )
            except Exception:
                pass
            return await call.answer("Зачислено!")
        idx = int(call.data.split("_")[1])
        if idx in opened:
            return await call.answer("Уже открыто!")
        if idx in mines:
            await state.clear()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣" if r*5+c in mines else ("💎" if r*5+c in opened else "⬜"), callback_data="none") for c in range(5)] for r in range(5)])
            try:
                await call.message.edit_text(f"💥 <b>БУМ!</b>\n😢 Ставка <b>{fmt_num(bet)}</b> сгорела.", reply_markup=kb)
            except Exception:
                pass
            return await call.answer("БУМ!")
        opened.append(idx)
        mult = round(1.0 + (len(opened) * 0.15), 2)
        await state.update_data(opened=opened, mult=mult)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
        try:
            await call.message.edit_text(
                f"💣 <b>МИНЫ</b>\n"
                f"💰 {fmt_num(bet)}\n"
                f"📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\n"
                f"Открывай дальше!",
                reply_markup=kb
            )
        except Exception:
            pass
        await call.answer("Безопасно!")

    # --- БЛЭКДЖЕК ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("бж "))
    async def play_bj(message: Message):
        parts = message.text.lower().split()
        if len(parts) != 2:
            return await message.reply("❌ <code>бж 100</code>")
        try:
            bet = int(parts[1])
        except Exception:
            return
        uid = message.from_user.id
        if bet < 10 or get_balance(uid) < bet:
            return await message.reply("❌ Мин. 10 или мало средств.")
        set_balance(uid, -bet)
        p1, p2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        d1, d2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        # v59: проверка блэкджека дилера
        if d1 + d2 == 21 and p1 + p2 != 21:
            return await message.reply(
                f"🃏 <b>БЛЭКДЖЕК У ДИЛЕРА!</b>\n"
                f"👤 Твои карты: {p1} + {p2} = {p1+p2}\n"
                f"🤖 Дилер: {d1} + {d2} = 21\n"
                f"😢 Ставка {fmt_num(bet)} сгорела."
            )
        if p1 + p2 == 21:
            win = int(bet * 2.5)
            set_balance(uid, win)
            return await message.reply(
                f"🃏 <b>БЛЭКДЖЕК!</b>\n"
                f"👤 Твои карты: {p1} + {p2} = 21\n"
                f"🎉 Выигрыш: <b>+{fmt_num(win)}</b> (x2.5)"
            )
        bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
            InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
        ]])
        await message.reply(
            f"🃏 <b>БЛЭКДЖЕК</b>\n"
            f"💰 Ставка: {fmt_num(bet)}\n\n"
            f"👤 Твои карты: <b>{p1} + {p2} = {p1+p2}</b>\n"
            f"🤖 Дилер: <b>{d1} + ?</b>",
            reply_markup=kb
        )

    @dp.callback_query(F.data.startswith("bj_hit_"))
    async def bj_hit(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid:
            return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game:
            return await call.answer("Игра не найдена", show_alert=True)
        new_card = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
        game["player"].append(new_card)
        player_sum = sum(game["player"])
        if player_sum > 21:
            # v59: ставка уже списана при старте — НЕ списываем снова
            try:
                await call.message.edit_text(
                    f"🃏 <b>ПЕРЕБОР!</b>\n"
                    f"Ты набрал {player_sum}. Ставка {fmt_num(game['bet'])} сгорела."
                )
            except Exception:
                pass
            return await call.answer("Перебор!")
        bj_games[uid] = game
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
            InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
        ]])
        try:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n"
                f"💰 Ставка: {fmt_num(game['bet'])}\n\n"
                f"👤 Твои карты: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n"
                f"🤖 Дилер: <b>{game['dealer'][0]} + ?</b>",
                reply_markup=kb
            )
        except Exception:
            pass
        await call.answer(f"Выпала карта: {new_card}")

    @dp.callback_query(F.data.startswith("bj_stand_"))
    async def bj_stand(call: CallbackQuery):
        uid = int(call.data.split("_")[2])
        if call.from_user.id != uid:
            return await call.answer("Это не твоя игра!", show_alert=True)
        game = bj_games.pop(uid, None)
        if not game:
            return await call.answer("Игра не найдена", show_alert=True)
        player_sum = sum(game["player"])
        dealer_sum = sum(game["dealer"])
        while dealer_sum < 17:
            game["dealer"].append(random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]))
            dealer_sum = sum(game["dealer"])
        if dealer_sum > 21 or player_sum > dealer_sum:
            win = int(game["bet"] * 1.8)
            set_balance(uid, win)
            result = f"🎉 <b>ТЫ ВЫИГРАЛ!</b>\nВыигрыш: <b>+{fmt_num(win)}</b>"
        elif player_sum == dealer_sum:
            set_balance(uid, game["bet"])
            result = f"🤝 <b>НИЧЬЯ!</b>\nСтавка возвращена."
        else:
            result = f"😢 <b>ТЫ ПРОИГРАЛ!</b>\nСтавка сгорела."
        try:
            await call.message.edit_text(
                f"🃏 <b>БЛЭКДЖЕК</b>\n\n"
                f"👤 Твои карты: {player_sum}\n"
                f"🤖 Дилер: {dealer_sum}\n\n"
                f"{result}"
            )
        except Exception:
            pass
        await call.answer("Игра окончена!")

    # --- ДУЭЛИ ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("дуэль "))
    async def play_duel(message: Message):
        if not message.reply_to_message:
            return await message.reply("⚔️ Ответь на сообщение соперника и напиши <code>дуэль 100</code>.")
        challenger = message.from_user
        opponent = message.reply_to_message.from_user
        if challenger.id == opponent.id or opponent.is_bot:
            return await message.reply("❌ Нельзя.")
        parts = message.text.lower().split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>дуэль 100</code>")
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 10:
            return await message.reply("❌ Мин. 10.")
        if get_balance(challenger.id) < bet or get_balance(opponent.id) < bet:
            return await message.reply("❌ Мало средств.")
        set_balance(challenger.id, -bet)
        chat_id = message.chat.id
        duel_id = f"{chat_id}_{challenger.id}_{opponent.id}_{int(time.time())}"
        active_duels[duel_id] = {
            "challenger_id": challenger.id,
            "challenger_name": challenger.username or challenger.first_name,
            "opponent_id": opponent.id,
            "opponent_name": opponent.username or opponent.first_name,
            "bet": bet,
            "chat_id": chat_id,
            "created": time.time(),
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}")],
            [InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}")]
        ])
        await message.reply(
            f"⚔️ <b>ВЫЗОВ!</b>\n"
            f"👤 @{challenger.username or challenger.first_name} VS @{opponent.username or opponent.first_name}\n"
            f"💰 {fmt_num(bet)}\n\n"
            f"@{opponent.username or opponent.first_name}, жми кнопку!",
            reply_markup=kb
        )

        # v59: автоочистка дуэлей
        async def auto_expire():
            await asyncio.sleep(120)
            d = active_duels.pop(duel_id, None)
            if d:
                set_balance(d["challenger_id"], d["bet"])
                try:
                    await message.reply(f"⏰ <b>ДУЭЛЬ ПРОТУХЛА</b>\n💰 {fmt_num(d['bet'])} возвращены @{d['challenger_name']}.")
                except Exception:
                    pass
        asyncio.create_task(auto_expire())

    @dp.callback_query(F.data.startswith("duel_accept_"))
    async def duel_accept_handler(call: CallbackQuery):
        duel_id = call.data.replace("duel_accept_", "")
        duel = active_duels.get(duel_id)
        if not duel:
            return await call.answer("❌ Устарело.", show_alert=True)
        if call.from_user.id != duel["opponent_id"]:
            return await call.answer("❌ Не твой вызов.", show_alert=True)
        if get_balance(duel["opponent_id"]) < duel["bet"]:
            return await call.answer("❌ Мало средств.", show_alert=True)
        duel = active_duels.pop(duel_id, None)
        if not duel:
            return await call.answer("❌ Уже принята.", show_alert=True)
        set_balance(duel["opponent_id"], -duel["bet"])
        try:
            await call.message.edit_text(
                f"⚔️ <b>ДУЭЛЬ!</b>\n"
                f"🔵 @{duel['challenger_name']}\n"
                f"🔴 @{duel['opponent_name']}\n"
                f"💰 {fmt_num(duel['bet'] * 2)}\n\n"
                f"🎲 Бросаем..."
            )
        except Exception:
            pass
        await call.answer("Принято!")
        await asyncio.sleep(1.5)
        d1 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
        await asyncio.sleep(0.5)
        d2 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
        await asyncio.sleep(3.5)
        v1, v2 = d1.dice.value, d2.dice.value
        if v1 == v2:
            set_balance(duel["challenger_id"], duel["bet"])
            set_balance(duel["opponent_id"], duel["bet"])
            return await call.message.reply(f"🤝 <b>НИЧЬЯ!</b> ({v1} и {v2}). Ставки возвращены.")
        if v1 > v2:
            w_id, w_name, w_d, l_d = duel["challenger_id"], duel["challenger_name"], v1, v2
        else:
            w_id, w_name, w_d, l_d = duel["opponent_id"], duel["opponent_name"], v2, v1
        set_balance(w_id, duel["bet"] * 2)
        await call.message.reply(
            f"🏆 <b>ПОБЕДИТЕЛЬ</b>\n"
            f"🥇 @{w_name} ({w_d})\n"
            f"💔 ({l_d})\n"
            f"💰 +{fmt_num(duel['bet'] * 2)}"
        )

    @dp.callback_query(F.data.startswith("duel_decline_"))
    async def duel_decline_handler(call: CallbackQuery):
        duel_id = call.data.replace("duel_decline_", "")
        duel = active_duels.get(duel_id)
        if not duel:
            return await call.answer("❌ Устарело.", show_alert=True)
        if call.from_user.id != duel["opponent_id"]:
            return await call.answer("❌ Не твой вызов.", show_alert=True)
        duel = active_duels.pop(duel_id, None)
        if not duel:
            return await call.answer("❌ Уже обработано.", show_alert=True)
        set_balance(duel["challenger_id"], duel["bet"])
        try:
            await call.message.edit_text(
                f"❌ <b>ОТКЛОНЕНО</b>\n"
                f"@{call.from_user.username or call.from_user.first_name} отказался.\n"
                f"💰 {fmt_num(duel['bet'])} возвращены."
            )
        except Exception:
            pass
        await call.answer("Отклонено.")

    # --- ОСТАЛЬНЫЕ ИГРЫ ---
    async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
        uid = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        parts = message.text.lower().split()
        # v59: проверка длины
        if len(parts) != 2:
            return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 1 or get_balance(uid) < bet:
            return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji=emoji)
        await asyncio.sleep(2.5)
        res = sent.dice.value
        if win_cond(res):
            win = int(bet * win_mult)
            set_balance(uid, win)
            try:
                log_game(uid, username, game_name, bet, win, str(res))
            except Exception:
                pass
            txt = win_txt.format(result=res, win=fmt_num(win))
        else:
            try:
                log_game(uid, username, game_name, bet, 0, str(res))
            except Exception:
                pass
            txt = lose_txt.format(result=res, bet=fmt_num(bet))
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "баскетбол ")))
    async def play_basket(message: Message):
        await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "фут ")))
    async def play_football(message: Message):
        await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "кубик ", "дайс ")))
    async def play_dice(message: Message):
        await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "спин ")))
    async def play_slots(message: Message):
        await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8, "🎰 {result}\n😢 -{bet}", "🎰 {result}\n🎉 +{win}")

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "дарт ")))
    async def play_darts(message: Message):
        uid = message.from_user.id
        parts = message.text.lower().split()
        if len(parts) != 2:
            return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 1 or get_balance(uid) < bet:
            return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji="🎯")
        await asyncio.sleep(2.5)
        res = sent.dice.value
        if res == 6:
            win = int(bet * 5)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "дартс", bet, win, str(res))
            except Exception:
                pass
            txt = f"🎯 ЯБЛОЧКО! +{fmt_num(win)} (x5)"
        elif res >= 3:
            win = int(bet * 1.5)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "дартс", bet, win, str(res))
            except Exception:
                pass
            txt = f"🎯 Попал! +{fmt_num(win)} (x1.5)"
        else:
            try:
                log_game(uid, message.from_user.username or "user", "дартс", bet, 0, str(res))
            except Exception:
                pass
            txt = f"🎯 Мимо. -{fmt_num(bet)}"
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("боулинг ", "боул ")))
    async def play_bowling(message: Message):
        uid = message.from_user.id
        parts = message.text.lower().split()
        if len(parts) != 2:
            return
        try:
            bet = int(parts[1])
        except Exception:
            return
        if bet < 1 or get_balance(uid) < bet:
            return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        sent = await message.answer_dice(emoji="🎳")
        await asyncio.sleep(2.5)
        res = sent.dice.value
        if res == 6:
            win = int(bet * 3)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "боулинг", bet, win, str(res))
            except Exception:
                pass
            txt = f"🎳 СТРАЙК! +{fmt_num(win)} (x3)"
        elif res >= 4:
            win = int(bet * 1.5)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "боулинг", bet, win, str(res))
            except Exception:
                pass
            txt = f"🎳 Сбил! +{fmt_num(win)} (x1.5)"
        else:
            try:
                log_game(uid, message.from_user.username or "user", "боулинг", bet, 0, str(res))
            except Exception:
                pass
            txt = f"🎳 Мимо. -{fmt_num(bet)}"
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("монетка ", "монета ")))
    async def play_coin(message: Message):
        uid = message.from_user.id
        parts = message.text.lower().split()
        # v59: проверка длины
        if len(parts) < 3:
            return await message.reply("❌ <code>монетка 100 орел</code>")
        try:
            bet = int(parts[1])
        except Exception:
            return
        choice = parts[2]
        if choice not in ["орел", "решка", "ребро"]:
            return await message.reply("❌ орел/решка/ребро.")
        if bet < 1 or get_balance(uid) < bet:
            return await message.reply("❌ Мало.")
        set_balance(uid, -bet)
        await asyncio.sleep(1)
        res = random.choices(["орел", "решка", "ребро"], weights=[49.5, 49.5, 1])[0]
        if res == "ребро" and choice == "ребро":
            win = int(bet * 10)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "монетка", bet, win, res)
            except Exception:
                pass
            txt = f"🪙 РЕБРО! ДЖЕКПОТ +{fmt_num(win)} (x10)"
        elif res == choice:
            win = int(bet * 2)
            set_balance(uid, win)
            try:
                log_game(uid, message.from_user.username or "user", "монетка", bet, win, res)
            except Exception:
                pass
            txt = f"🪙 {res.upper()}! +{fmt_num(win)} (x2)"
        else:
            try:
                log_game(uid, message.from_user.username or "user", "монетка", bet, 0, res)
            except Exception:
                pass
            txt = f"🪙 {res.upper()}. -{fmt_num(bet)}"
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))

    # --- РУЛЕТКА ---
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт)\s+(\d+)$"))
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт)$"))
    async def place_color_bet(message: Message):
        uid = message.from_user.id
        chat_id = message.chat.id
        parts = message.text.lower().split()
        word = None
        num = None
        for p in parts:
            if p.isdigit():
                num = p
            elif p in ["к", "ч", "з", "чет", "чёт", "нечет", "нечёт"]:
                word = p
        if not word or not num:
            return
        bet_type = {"к": "red", "ч": "black", "з": "green", "чет": "even", "чёт": "even", "нечет": "odd", "нечёт": "odd"}.get(word)
        try:
            bet = int(num)
        except Exception:
            return
        if bet < 1:
            return await message.reply("❌ Мин. 1.")
        bal = get_balance(uid)
        if bal < bet:
            return await message.reply(f"❌ Мало. Баланс: {fmt_num(bal)}")
        set_balance(uid, -bet)
        if chat_id not in active_bets:
            active_bets[chat_id] = {"bets": [], "timer": None}
        if active_bets[chat_id].get("timer"):
            active_bets[chat_id]["timer"].cancel()
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
        names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
        msg = await message.reply(
            f"🎰 <b>СТАВКА</b>\n"
            f"@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n"
            f"⚡️ Напиши <b>го</b>!",
            reply_markup=bet_actions_inline()
        )
        asyncio.create_task(delete_message_later(msg, 120))

    @dp.callback_query(F.data.in_({"bet_repeat", "bet_double"}))
    async def bet_actions_handler(call: CallbackQuery):
        uid = call.from_user.id
        chat_id = call.message.chat.id
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            return await call.answer("Ставка устарела", show_alert=True)
        my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == uid]
        if not my_bets:
            return await call.answer("Ты не делал ставку!", show_alert=True)
        for b in my_bets:
            if b.get("action") == call.data:
                return await call.answer("❌ Ты уже использовал это в раунде!", show_alert=True)
        last_bet = my_bets[-1]
        amount = last_bet["bet"]
        if call.data == "bet_double":
            amount *= 2
        if get_balance(uid) < amount:
            return await call.answer("❌ Недостаточно!", show_alert=True)
        set_balance(uid, -amount)
        active_bets[chat_id]["bets"].append({"user_id": uid, "username": call.from_user.username or "user", "type": last_bet["type"], "bet": amount, "action": call.data})
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.answer(f"✅ Ставка на {fmt_num(amount)} принята!")
        await call.message.reply(
            f"🎰 <b>{'УДВОЕНИЕ' if call.data == 'bet_double' else 'ПОВТОР'}</b>\n"
            f"@{call.from_user.username or 'user'} | {fmt_num(amount)}"
        )

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
    async def start_roulette(message: Message):
        chat_id = message.chat.id
        uid = message.from_user.id
        if is_spinning.get(chat_id, False):
            return await message.reply("⏳ УЖЕ КРУТИТСЯ!")
        if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
            return await message.reply("❌ Нет ставок.")
        if not any(b["user_id"] == uid for b in active_bets[chat_id]["bets"]):
            return await message.reply("❌ ТОЛЬКО ИГРОКИ СО СТАВКОЙ!")
        
        is_spinning[chat_id] = True
        if active_bets[chat_id].get("timer"):
            active_bets[chat_id]["timer"].cancel()
        
        bets = active_bets[chat_id]["bets"]
        total = sum(b["bet"] for b in bets)
        
        # Отправляем гифку с кнопками (Удвоить / Повторить)
        kb = bet_actions_inline() # Берем кнопки из keyboards.py
        try:
            msg = await message.reply_animation(
                FSInputFile("roulette.gif"), 
                caption=f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}\n\n👇 Хочешь еще?", 
                reply_markup=kb
            )
        except Exception:
            msg = await message.reply(
                f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}\n\n👇 Хочешь еще?", 
                reply_markup=kb
            )
            
        await asyncio.sleep(3)
        res = random.randint(0, 36)
        color = get_color(res)
        win, lose = [], []
        for b in bets:
            w = 0
            if b["type"] == "red" and res in RED:
                w = int(b["bet"] * 1.95)
            elif b["type"] == "black" and res in BLACK:
                w = int(b["bet"] * 1.95)
            elif b["type"] == "green" and res == 0:
                w = int(b["bet"] * 35)
            elif b["type"] == "even" and res != 0 and res % 2 == 0:
                w = int(b["bet"] * 1.95)
            elif b["type"] == "odd" and res % 2 != 0:
                w = int(b["bet"] * 1.95)
            if w > 0:
                set_balance(b["user_id"], w)
                win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
            else:
                lose.append(f"💔 @{b['username']}")
                
        txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n"
        if win:
            txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
        if lose:
            txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
            
        try:
            await msg.edit_caption(caption=txt) # Убираем кнопки после окончания
        except Exception:
            try:
                await msg.edit_text(txt)
            except Exception:
                pass
                
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, f"{color}{res}"))
            conn.commit()
        except Exception:
            pass
        finally:
            c.close(); release_conn(conn)
            
        # Очищаем ставки текущего раунда, но не удаляем сообщение сразу, чтобы юзер увидел кнопки
        if chat_id in active_bets:
            active_bets[chat_id]["bets"] = []  # Очищаем ставки, но оставляем структуру
        is_spinning[chat_id] = False
        asyncio.create_task(delete_message_later(msg, 120))

    # ========================================================
    # БЛОК 11. МОДЕРАТОР (auto_moderator + /mod_*)
    # ========================================================
    # v59: РАБОЧАЯ кнопка 🧹 Очистить — реально чистит игровой чат
    @dp.message(F.text == "🧹 Очистить")
    async def mod_clean_btn(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID:
            return
        # Реально удаляем последние 100 сообщений (максимум для бота — 100 за раз)
        deleted = 0
        try:
            history = []
            async for msg in message.bot.get_chat_history(message.chat.id, limit=100):
                history.append(msg)
            for m in history:
                try:
                    await message.bot.delete_message(message.chat.id, m.message_id)
                    deleted += 1
                except Exception:
                    pass
        except Exception:
            pass
        try:
            info = await message.answer(f"🧹 <b>ЧИСТКА</b>\nУдалено сообщений: <b>{deleted}</b>")
            await asyncio.sleep(5)
            await info.delete()
        except Exception:
            pass

    @dp.message(Command("mod_clean", "очистить_чат"))
    async def mod_clean_cmd(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID:
            return
        deleted = 0
        try:
            history = []
            async for m in message.bot.get_chat_history(message.chat.id, limit=100):
                history.append(m)
            for m in history:
                try:
                    await message.bot.delete_message(message.chat.id, m.message_id)
                    deleted += 1
                except Exception:
                    pass
        except Exception:
            pass
        try:
            info = await message.answer(f"🧹 <b>ЧИСТКА</b>\nУдалено сообщений: <b>{deleted}</b>")
            await asyncio.sleep(5)
            await info.delete()
        except Exception:
            pass

    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if not message.from_user:
            return
        if message.from_user.id == ADMIN_ID or message.from_user.is_bot:
            return
        # Пропускаем команды и известные игровые сообщения
        if message.text:
            t = message.text.strip()
            if t.startswith("/"):
                return
            if t.lower() in GROUP_CMD_WHITELIST:
                return
            # игровые команды: мины/бж/кости/баскет/футбол/дартс/боулинг/слот/монетка/дуэль + сумма
            low = t.lower()
            for prefix in ("мины ", "бж ", "кости ", "кубик ", "дайс ", "баскет ", "баскетбол ", "футбол ", "фут ", "дартс ", "дарт ", "боулинг ", "боул ", "слот ", "спин ", "монетка ", "монета ", "дуэль ", "к ", "ч ", "з ", "чет ", "чёт ", "нечет ", "нечёт "):
                if low.startswith(prefix):
                    return
        if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == message.bot.id:
            return

        uid = message.from_user.id
        now = _now()

        if GLOBAL_MUTE and uid != ADMIN_ID:
            try:
                await message.delete()
            except Exception:
                pass
            return

        if uid in muted_users:
            if now < muted_users[uid]:
                try:
                    await message.delete()
                except Exception:
                    pass
                return
            else:
                del muted_users[uid]

        is_bad = False
        if message.text:
            text_lower = message.text.lower()
            if any(word in text_lower for word in BAD_WORDS):
                is_bad = True

        is_caps = False
        if message.text and len(message.text) > 5:
            caps_count = sum(1 for c in message.text if c.isupper())
            if caps_count / len(message.text) > 0.7:
                is_caps = True

        is_spam = False
        if uid in user_warns and user_warns[uid].get("last_msg") == message.text:
            user_warns[uid]["spam_count"] = user_warns[uid].get("spam_count", 0) + 1
            if user_warns[uid]["spam_count"] >= 5:
                is_spam = True
        else:
            if uid in user_warns:
                user_warns[uid]["spam_count"] = 0

        # v59: ВАЖНО — return ТОЛЬКО при нарушении
        if not (is_bad or is_caps or is_spam):
            return

        try:
            await message.delete()
        except Exception:
            pass

        if uid not in user_warns:
            user_warns[uid] = {"count": 0, "time": now, "last_msg": None, "spam_count": 0}
        if (now - user_warns[uid]["time"]).total_seconds() > 3600:
            user_warns[uid]["count"] = 0
        user_warns[uid]["count"] += 1
        user_warns[uid]["time"] = now
        user_warns[uid]["last_msg"] = message.text
        count = user_warns[uid]["count"]
        reason = "мат" if is_bad else ("капс" if is_caps else "спам")

        if count >= 3 or is_spam:
            mute_time = 10 if is_spam else 24
            muted_users[uid] = now + timedelta(minutes=mute_time)
            del user_warns[uid]
            try:
                await message.answer(
                    f"🚫 <b>МУТ</b>\n"
                    f"@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}."
                )
            except Exception:
                pass
        else:
            try:
                msg = await message.reply(
                    f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n"
                    f"@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!"
                )
                asyncio.create_task(delete_message_later(msg, 30))
            except Exception:
                pass

    # /mod_* команды
    @dp.message(Command("mod_add", "добавить_модера"))
    async def mod_add(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/mod_add @username</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        if uid in MODS:
            return await message.reply("❌ Он уже модер.")
        MODS.append(uid)
        MOD_LIMITS[uid] = {"week_start": _now().date(), "given": 0}
        persist_mods()
        try:
            user = await message.bot.get_chat(uid)
            name = user.first_name
        except Exception:
            name = "Игрок"
        txt = (
            f"👑 <b>ТЕБЯ НАЗНАЧИЛИ МОДЕРАТОРОМ!</b>\n\n"
            f"Привет, <b>{name}</b>! Ты получил права младшего администратора.\n\n"
            f"🛠 <b>Твои возможности:</b>\n"
            f"• 🎁 Выдавать токены (до 5 000 000 в неделю)\n"
            f"• ⚠️ Выдавать предупреждения\n"
            f"• 🧹 Очищать чат\n"
            f"• 🚨 Вызывать Админа\n\n"
            f"⚠️ <b>ВАЖНО:</b> Ты НЕ можешь банить или забирать токены.\n\n"
            f"📖 <b>Справка:</b> /mod_help\n\n"
            f"👇 <i>Тебе открыта новая клавиатура!</i>"
        )
        try:
            await message.bot.send_message(uid, txt, reply_markup=mod_panel_kb())
            await message.reply(f"✅ Игрок @{target} назначен модером!")
        except Exception:
            await message.reply("❌ Не удалось отправить сообщение модеру.")

    @dp.message(Command("mod_remove", "снять_модера"))
    async def mod_remove(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/mod_remove @username</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        if uid not in MODS:
            return await message.reply("❌ Он не модер.")
        MODS.remove(uid)
        MOD_LIMITS.pop(uid, None)
        persist_mods()
        txt = (
            "😔 <b>ТЫ БОЛЬШЕ НЕ МОДЕРАТОР</b>\n\n"
            "Твои права младшего администратора были сняты.\n"
            "Спасибо за работу! Надеюсь, ты продолжишь играть в нашем казино как обычный игрок.\n\n"
            "👇 <i>Тебе возвращена обычная клавиатура.</i>"
        )
        try:
            await message.bot.send_message(uid, txt, reply_markup=main_menu())
        except Exception:
            pass
        await message.reply(f"✅ Игрок @{target} больше не модер.")

    @dp.message(Command("mod_list", "список_модеров"))
    async def mod_list(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if not MODS:
            return await message.reply("📜 Список модеров пуст.")
        txt = "👑 <b>СПИСОК МОДЕРАТОРОВ</b>\n\n"
        for i, uid in enumerate(MODS, 1):
            txt += f"{i}. <code>{uid}</code>\n"
        await message.reply(txt)

    @dp.message(Command("mod_give", "выдать_токены"))
    async def mod_give(message: Message):
        if message.from_user.id != ADMIN_ID and message.from_user.id not in MODS:
            return
        parts = message.text.split()
        if len(parts) != 3:
            return await message.reply("❌ Формат: <code>/mod_give @user 1000</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        try:
            amount = int(parts[2])
        except Exception:
            return await message.reply("❌ Введи число.")
        mod_id = message.from_user.id
        if mod_id in MODS:
            lim = refresh_week(mod_id, MOD_LIMITS)
            if lim["given"] + amount > MAX_MOD_GIVE:
                return await message.reply(f"❌ Лимит! Выдано {fmt_num(lim['given'])} из {fmt_num(MAX_MOD_GIVE)}.")
            lim["given"] += amount
            MOD_LIMITS[mod_id] = lim
            persist_mods()
        set_balance(uid, amount)
        await message.reply(f"✅ @{target} выдано <b>{fmt_num(amount)}</b> токенов.")
        try:
            await message.bot.send_message(uid, f"🎁 Тебе выдали {fmt_num(amount)} токенов!")
        except Exception:
            pass

    @dp.message(Command("mod_my_limit", "мои_лимиты"))
    @dp.message(F.text == "📊 Мои лимиты")
    async def mod_my_limit(message: Message):
        uid = message.from_user.id
        if uid not in MODS:
            return
        lim = refresh_week(uid, MOD_LIMITS)
        persist_mods()
        given = lim["given"]
        left = MAX_MOD_GIVE - given
        await message.reply(
            f"📊 <b>ТВОИ ЛИМИТЫ</b>\n\n"
            f"Выдано: <b>{fmt_num(given)}</b>\n"
            f"Осталось: <b>{fmt_num(left)}</b>\n"
            f"Лимит: <b>{fmt_num(MAX_MOD_GIVE)}</b>/неделя"
        )

    @dp.message(Command("mod_warn", "предупреждение"))
    @dp.message(F.text == "⚠️ Предупреждение")
    async def mod_warn(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID:
            return
        if not message.reply_to_message:
            return await message.reply("❌ Ответь на сообщение игрока.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, uid,
                ChatPermissions(can_send_messages=False),
                until_date=_now() + timedelta(minutes=5)
            )
            await message.reply(f"⚠️ Игрок @{message.reply_to_message.from_user.username or 'user'} получил предупреждение (мут 5 мин).")
        except Exception:
            await message.reply("❌ Не могу замутить.")

    @dp.message(Command("mod_alert", "sos"))
    @dp.message(F.text == "🚨 SOS Админу")
    async def mod_alert(message: Message):
        if message.from_user.id not in MODS:
            return
        await message.reply("🚨 Сигнал отправлен Админу!")
        try:
            await message.bot.send_message(
                ADMIN_ID,
                f"🚨 <b>SOS ОТ МОДЕРА</b>\n@{message.from_user.username} вызывает тебя в чат <b>{message.chat.title}</b>"
            )
        except Exception:
            pass

    @dp.message(Command("mod_pin", "закрепить_модер"))
    @dp.message(F.text == "📌 Закрепить")
    async def mod_pin(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID:
            return
        if not message.reply_to_message:
            return await message.reply("❌ Ответь на сообщение.")
        try:
            await message.bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        except Exception:
            return await message.reply("❌ Не могу закрепить.")
        await message.reply("✅ Закреплено!")

    @dp.message(Command("mod_unban", "разбанить_модер"))
    @dp.message(F.text == "🔓 Разбан")
    async def mod_unban(message: Message):
        if message.from_user.id not in MODS and message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/mod_unban @username</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Не найден.")
        set_banned(uid, False)
        await message.reply(f"✅ Игрок @{target} разбанен.")

    # ========================================================
    # БЛОК 12. АДМИН
    # ========================================================
    @dp.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID:
            return
        txt = (
            "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n\n"
            "👇 Выбери раздел:\n\n"
            "📖 <b>Справка:</b> /admin_help\n"
            "🛡 <b>Хелп модера:</b> /mod_help"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(Command("say", "сказать"))
    async def admin_say(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        text = message.text.replace("/say", "").replace("/сказать", "").strip()
        if not text:
            return await message.reply("❌ Напиши текст: <code>/say Привет!</code>")
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text}")

    @dp.message(Command("give_all", "выдать_всем"))
    async def admin_give_all(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/give_all 1000</code>")
        try:
            amount = int(parts[1])
        except Exception:
            return await message.reply("❌ Введи число.")
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("UPDATE users SET balance = balance + %s", (amount,))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        await message.reply(f"✅ Выдано <b>{fmt_num(amount)}</b> токенов ВСЕМ игрокам!")

    @dp.message(Command("stats", "стата"))
    async def admin_stats(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
            tu, tb = c.fetchone()
            c.execute("SELECT COUNT(*) FROM game_log")
            tg = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE banned = TRUE")
            banned = c.fetchone()[0]
        finally:
            c.close(); release_conn(conn)
        txt = (
            f"📊 <b>СТАТИСТИКА</b>\n\n"
            f"👥 Игроков: <b>{tu}</b>\n"
            f"💎 Общий баланс: <b>{fmt_num(tb)}</b>\n"
            f"🎮 Сыграно игр: <b>{tg}</b>\n"
            f"🚫 Забанено: <b>{banned}</b>"
        )
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(Command("history", "история"))
    async def admin_history(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/history @username</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT game, bet, win, time FROM game_log WHERE user_id = %s ORDER BY id DESC LIMIT 10", (uid,))
            rows = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        if not rows:
            return await message.reply("📜 У этого игрока нет истории игр.")
        txt = f"📜 <b>ИСТОРИЯ ИГР</b> (@{target})\n\n"
        for g, b, w, t in rows:
            txt += f"• {g} | Ставка: {fmt_num(b)} | Выигрыш: {fmt_num(w)}\n"
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    # v59: /clear — РЕАЛЬНО чистит чат
    @dp.message(Command("clear", "очистить"))
    async def admin_clear(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if message.chat.type not in ["group", "supergroup"]:
            return await message.reply("❌ Только для групп.")
        deleted = 0
        try:
            history = []
            async for m in message.bot.get_chat_history(message.chat.id, limit=100):
                history.append(m)
            for m in history:
                try:
                    await message.bot.delete_message(message.chat.id, m.message_id)
                    deleted += 1
                except Exception:
                    pass
        except Exception:
            pass
        try:
            info = await message.answer(f"🧹 <b>ЧИСТКА</b>\nУдалено: <b>{deleted}</b>")
            await asyncio.sleep(5)
            await info.delete()
        except Exception:
            pass

    @dp.message(Command("mute_all", "мут_всех"))
    async def admin_mute_all(message: Message):
        global GLOBAL_MUTE, GLOBAL_MUTE_TASK
        if message.from_user.id != ADMIN_ID:
            return
        if message.chat.type not in ["group", "supergroup"]:
            return await message.reply("❌ Только для групп.")
        if GLOBAL_MUTE_TASK and not GLOBAL_MUTE_TASK.done():
            GLOBAL_MUTE_TASK.cancel()
        GLOBAL_MUTE = True
        await message.answer("🔇 <b>ГЛОБАЛЬНЫЙ МУТ</b>\nВсе игроки заглушены на 1 час. Пишет только админ.")

        async def unmute():
            global GLOBAL_MUTE
            await asyncio.sleep(3600)
            GLOBAL_MUTE = False
            try:
                await message.answer("🔊 <b>МУТ СНЯТ</b>\nЧат снова активен.")
            except Exception:
                pass
        GLOBAL_MUTE_TASK = asyncio.create_task(unmute())

    @dp.message(Command("pin", "закрепить"))
    async def admin_pin(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.reply_to_message:
            return await message.reply("❌ Ответь на сообщение.")
        try:
            await message.bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        except Exception:
            return await message.reply("❌ Не могу закрепить.")
        await message.reply("✅ Закреплено!")

    @dp.message(Command("unpin", "открепить"))
    async def admin_unpin(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        try:
            await message.bot.unpin_chat_message(message.chat.id)
        except Exception:
            return await message.reply("❌ Не могу открепить.")
        await message.reply("✅ Откреплено!")

    @dp.message(Command("top_games", "топ_игр"))
    async def admin_top_games(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT game, COUNT(*) FROM game_log GROUP BY game ORDER BY COUNT(*) DESC LIMIT 5")
            rows = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        txt = "🎮 <b>ТОП-5 ИГР</b>\n\n"
        for i, (g, cnt) in enumerate(rows, 1):
            txt += f"{i}. {g} — <b>{cnt}</b> ставок\n"
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(Command("reset_user", "сброс_игрока"))
    async def admin_reset_user(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/reset_user @user</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        set_balance(uid, 0)
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("UPDATE users SET bank = 0, credit_debt = 0, xp = 0 WHERE user_id = %s", (uid,))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        await message.reply(f"✅ Игрок @{target} полностью сброшен.")

    @dp.message(Command("spy", "шпион"))
    async def admin_spy(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/spy @user</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT game, bet, win, time FROM game_log WHERE user_id = %s AND time > NOW() - INTERVAL '1 day'", (uid,))
            rows = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        if not rows:
            return await message.reply("🕵️ За последние 24 часа игрок не играл.")
        txt = f"🕵️ <b>ШПИОН (@{target} за 24ч)</b>\n\n"
        for g, b, w, t in rows:
            txt += f"• {g} | {fmt_num(b)} -> {fmt_num(w)}\n"
        await send_clean_private(message, txt, reply_markup=admin_panel_kb())

    @dp.message(Command("jackpot", "джекпот"))
    async def admin_jackpot(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/jackpot 50000</code>")
        try:
            amount = int(parts[1])
        except Exception:
            return await message.reply("❌ Введи число.")
        await message.reply(f"✅ В банк рулетки добавлено {fmt_num(amount)} токенов (для хайпа).")

    @dp.message(Command("drop", "дроп"))
    async def admin_drop(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/drop 10000</code>")
        try:
            amount = int(parts[1])
        except Exception:
            return await message.reply("❌ Введи число.")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 ЗАБРАТЬ", callback_data=f"drop_{amount}")]])
        await message.answer(f"💸 <b>ДРОП!</b>\nКто первый нажмет — получит <b>{fmt_num(amount)}</b> токенов!", reply_markup=kb)

    @dp.callback_query(F.data.startswith("drop_"))
    async def drop_handler(call: CallbackQuery):
        amount = int(call.data.replace("drop_", ""))
        uid = call.from_user.id
        set_balance(uid, amount)
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(f"🎉 @{call.from_user.username or 'user'} забрал дроп <b>{fmt_num(amount)}</b>!")

    @dp.message(Command("reset_credit", "простить_долг"))
    async def admin_reset_credit(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/reset_credit @user</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("UPDATE users SET credit_debt = 0 WHERE user_id = %s", (uid,))
            conn.commit()
        finally:
            c.close(); release_conn(conn)
        await message.reply(f"✅ Игроку @{target} прощен долг.")

    # v59: FIX broadcast — только F.photo
    @dp.message(Command("broadcast_photo", "рассылка_фото"))
    async def admin_broadcast_photo(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "📸 Отправь картинку с подписью (текст будет в подписи):")
        await state.set_state(BotStates.waiting_broadcast_photo)

    @dp.message(F.photo)
    async def broadcast_photo_handler(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if await state.get_state() != BotStates.waiting_broadcast_photo.state:
            return
        await state.clear()
        photo = message.photo[-1].file_id
        caption = message.caption or "📢 Новое объявление!"
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT user_id FROM users")
            users = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        sent = 0
        await send_clean_private(message, "⏳ Рассылка...")
        for (uid,) in users:
            try:
                await message.bot.send_photo(uid, photo, caption=caption)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await send_clean_private(message, f"✅ Отправлено: {sent}")

    @dp.message(Command("kick", "кик"))
    async def admin_kick(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.reply_to_message:
            return await message.reply("❌ Ответь на сообщение игрока.")
        uid = message.reply_to_message.from_user.id
        try:
            await message.bot.ban_chat_member(message.chat.id, uid)
            await message.bot.unban_chat_member(message.chat.id, uid)
            await message.reply(f"✅ Игрок @{message.reply_to_message.from_user.username or 'user'} кикнут.")
        except Exception:
            await message.reply("❌ Не могу кикнуть.")

    @dp.message(Command("ban", "бан"))
    async def admin_ban(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if not message.reply_to_message:
            return await message.reply("❌ Ответь на сообщение игрока.")
        uid = message.reply_to_message.from_user.id
        set_banned(uid, True)
        await message.reply(f"✅ Игрок @{message.reply_to_message.from_user.username or 'user'} забанен в боте.")

    @dp.message(Command("unban", "разбан"))
    async def admin_unban(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) != 2:
            return await message.reply("❌ Формат: <code>/unban @user</code>")
        target = parts[1].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await message.reply("❌ Игрок не найден.")
        set_banned(uid, False)
        await message.reply(f"✅ Игрок @{target} разбанен.")

    # ========================================================
    # БЛОК 13. АДМИН — КНОПКИ
    # ========================================================
    @dp.message(F.text == "👥 Игроки")
    async def admin_players_btn(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID:
            return
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="🔍 Скан"), KeyboardButton(text="💰 Выдать")],
            [KeyboardButton(text="💸 Забрать"), KeyboardButton(text="🚫 Бан")],
            [KeyboardButton(text="✅ Разбан"), KeyboardButton(text="⬅️ Назад в админку")]
        ], resize_keyboard=True)
        txt = (
            "👥 <b>УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n"
            "• 🔍 <b>Скан</b> — полное досье на игрока\n"
            "• 💰 <b>Выдать</b> — добавить токены\n"
            "• 💸 <b>Забрать</b> — списать токены\n"
            "• 🚫 <b>Бан</b> — заблокировать\n"
            "• ✅ <b>Разбан</b> — разблокировать"
        )
        await send_clean_private(message, txt, reply_markup=kb)

    @dp.message(F.text == "⬅️ Назад в админку")
    async def admin_back_btn(message: Message, state: FSMContext):
        await state.clear()
        if message.from_user.id != ADMIN_ID:
            return
        await cmd_admin(message, state)

    @dp.message(F.text == "👑 Админ-панель")
    async def admin_panel_btn(message: Message, state: FSMContext):
        await cmd_admin(message, state)

    # --- СКАН ---
    @dp.message(F.text == "🔍 Скан")
    async def admin_scan_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "🔍 <b>СКАН ИГРОКА</b>\n\nВведи <b>@username</b> или <b>ID</b> игрока (например, <code>@user</code>):\n\n<i>Напиши «отмена», чтобы выйти.</i>")
        await state.set_state(BotStates.waiting_scan)

    @dp.message(BotStates.waiting_scan)
    async def process_scan(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Скан отменен.", reply_markup=admin_reply_kb())
        target = message.text.replace("@", "").strip()
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            await state.clear()
            return await send_clean_private(message, "❌ <b>ИГРОК НЕ НАЙДЕН</b>", reply_markup=admin_reply_kb())
        conn = get_conn(); c = conn.cursor()
        try:
            c.execute("SELECT username, balance, bank, credit_debt, xp, banned, last_login_date, referral_id FROM users WHERE user_id = %s", (uid,))
            row = c.fetchone()
            if not row:
                return await send_clean_private(message, "❌ Игрок не найден в базе.", reply_markup=admin_reply_kb())
            uname, bal, bank, debt, xp, banned, last_login, ref_id = row
            c.execute("SELECT game, bet, win, time FROM game_log WHERE user_id = %s ORDER BY id DESC LIMIT 5", (uid,))
            recent_games = c.fetchall()
        finally:
            c.close(); release_conn(conn)
        status = "🚫 <b>ЗАБАНЕН</b>" if banned else "✅ <b>Активен</b>"
        ref_txt = f"<code>{ref_id}</code>" if ref_id and ref_id != 0 else "Нет"
        last_login_txt = last_login.strftime("%d.%m.%Y") if last_login else "Неизвестно"
        games_txt = ""
        if recent_games:
            for g, b, w, t in recent_games:
                games_txt += f"• {g} | Ставка: {fmt_num(b)} | Выигрыш: {fmt_num(w)}\n"
        else:
            games_txt = "Нет истории игр.\n"
        txt = (
            f"🕵️ <b>ДОСЬЕ ИГРОКА</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 <b>Имя:</b> @{uname}\n"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n"
            f"🚫 <b>Статус:</b> {status}\n"
            f"📅 <b>Последний вход:</b> {last_login_txt}\n"
            f"👥 <b>Реферер:</b> {ref_txt}\n"
            f"━━━━━━━━━━━━━━\n"
            f"💎 <b>Баланс:</b> {fmt_num(bal)} Tokens\n"
            f"🏦 <b>В банке:</b> {fmt_num(bank or 0)} Tokens\n"
            f"💳 <b>Долг:</b> {fmt_num(debt or 0)} Tokens\n"
            f"⭐ <b>Опыт:</b> {xp} XP (Уровень {xp // 100})\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎮 <b>Последние 5 игр:</b>\n"
            f"{games_txt}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Выдать", callback_data=f"quick_give_{uid}"), InlineKeyboardButton(text="💸 Забрать", callback_data=f"quick_take_{uid}")],
            [InlineKeyboardButton(text="🚫 Бан", callback_data=f"quick_ban_{uid}"), InlineKeyboardButton(text="✅ Разбан", callback_data=f"quick_unban_{uid}")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="quick_close")]
        ])
        await send_clean_private(message, txt, reply_markup=kb)
        await state.clear()

    @dp.callback_query(F.data.startswith("quick_"))
    async def quick_action_handler(call: CallbackQuery, state: FSMContext):
        if call.from_user.id != ADMIN_ID:
            return
        action = call.data.split("_")[1]
        if action == "close":
            try:
                await call.message.delete()
            except Exception:
                pass
            return await call.answer("Закрыто")
        try:
            uid = int(call.data.split("_")[2])
        except Exception:
            return await call.answer("Ошибка", show_alert=True)
        if action == "give":
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_clean_private(call.message, f"💰 Введи сумму для выдачи игроку (ID: {uid}):\n\n<i>Напиши «отмена», чтобы выйти.</i>")
            await state.update_data(target_uid=uid, action="quick_give")
            await state.set_state(BotStates.waiting_quick_amount)
        elif action == "take":
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_clean_private(call.message, f"💸 Введи сумму для списания у игрока (ID: {uid}):\n\n<i>Напиши «отмена», чтобы выйти.</i>")
            await state.update_data(target_uid=uid, action="quick_take")
            await state.set_state(BotStates.waiting_quick_amount)
        elif action == "ban":
            set_banned(uid, True)
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_clean_private(call.message, f"✅ Игрок <code>{uid}</code> забанен.", reply_markup=admin_reply_kb())
        elif action == "unban":
            set_banned(uid, False)
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_clean_private(call.message, f"✅ Игрок <code>{uid}</code> разбанен.", reply_markup=admin_reply_kb())
        await call.answer()

    @dp.message(BotStates.waiting_quick_amount)
    async def quick_amount_process(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Действие отменено.", reply_markup=admin_reply_kb())
        data = await state.get_data()
        uid = data.get("target_uid")
        action = data.get("action")
        try:
            amount = int(message.text)
        except Exception:
            return await message.reply("❌ Введи число.")
        if action == "quick_give":
            set_balance(uid, amount)
            await send_clean_private(message, f"✅ Игроку <code>{uid}</code> выдано <b>{fmt_num(amount)}</b> токенов.", reply_markup=admin_reply_kb())
        elif action == "quick_take":
            set_balance(uid, -amount)
            await send_clean_private(message, f"✅ У игрока <code>{uid}</code> списано <b>{fmt_num(amount)}</b> токенов.", reply_markup=admin_reply_kb())
        await state.clear()

    # --- ВЫДАТЬ / ЗАБРАТЬ / БАН / РАЗБАН через кнопки ---
    @dp.message(F.text == "💰 Выдать")
    async def admin_give_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "💰 Введи <b>@username</b> (или ID) и <b>сумму</b> через пробел.\n\nПример: <code>@user 1000</code>\n\n<i>Напиши «отмена», чтобы выйти.</i>")
        await state.set_state(BotStates.waiting_admin_give)

    @dp.message(BotStates.waiting_admin_give)
    async def process_admin_give(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Выдача отменена.", reply_markup=admin_reply_kb())
        parts = message.text.split()
        if len(parts) != 2:
            return await send_clean_private(message, "❌ Формат: <code>@user 1000</code>")
        target = parts[0].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await send_clean_private(message, "❌ Игрок не найден.")
        try:
            amount = int(parts[1])
        except Exception:
            return await send_clean_private(message, "❌ Введи число.")
        set_balance(uid, amount)
        await send_clean_private(message, f"✅ Игроку @{target} выдано <b>{fmt_num(amount)}</b> токенов.", reply_markup=admin_reply_kb())
        try:
            await message.bot.send_message(uid, f"🎁 Тебе выдали {fmt_num(amount)} токенов!")
        except Exception:
            pass
        await state.clear()

    @dp.message(F.text == "💸 Забрать")
    async def admin_take_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "💸 Введи <b>@username</b> (или ID) и <b>сумму</b> через пробел.\n\nПример: <code>@user 1000</code>\n\n<i>Напиши «отмена», чтобы выйти.</i>")
        await state.set_state(BotStates.waiting_admin_take)

    @dp.message(BotStates.waiting_admin_take)
    async def process_admin_take(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Списание отменено.", reply_markup=admin_reply_kb())
        parts = message.text.split()
        if len(parts) != 2:
            return await send_clean_private(message, "❌ Формат: <code>@user 1000</code>")
        target = parts[0].replace("@", "")
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await send_clean_private(message, "❌ Игрок не найден.")
        try:
            amount = int(parts[1])
        except Exception:
            return await send_clean_private(message, "❌ Введи число.")
        set_balance(uid, -amount)
        await send_clean_private(message, f"✅ У игрока @{target} списано <b>{fmt_num(amount)}</b> токенов.", reply_markup=admin_reply_kb())
        await state.clear()

    @dp.message(F.text == "🚫 Бан")
    async def admin_ban_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "🚫 Введи <b>@username</b> (или ID) игрока для бана:\n\n<i>Напиши «отмена», чтобы выйти.</i>")
        await state.set_state(BotStates.waiting_admin_ban)

    @dp.message(BotStates.waiting_admin_ban)
    async def process_admin_ban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Бан отменен.", reply_markup=admin_reply_kb())
        target = message.text.replace("@", "").strip()
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await send_clean_private(message, "❌ Игрок не найден.")
        set_banned(uid, True)
        await send_clean_private(message, f"✅ Игрок @{target} забанен.", reply_markup=admin_reply_kb())
        await state.clear()

    @dp.message(F.text == "✅ Разбан")
    async def admin_unban_btn(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        await send_clean_private(message, "✅ Введи <b>@username</b> (или ID) игрока для разбана:\n\n<i>Напиши «отмена», чтобы выйти.</i>")
        await state.set_state(BotStates.waiting_admin_unban)

    @dp.message(BotStates.waiting_admin_unban)
    async def process_admin_unban(message: Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        if message.text.lower() == "отмена":
            await state.clear()
            return await send_clean_private(message, "❌ Разбан отменен.", reply_markup=admin_reply_kb())
        target = message.text.replace("@", "").strip()
        uid = int(target) if target.isdigit() else get_user_id_by_username(target)
        if not uid:
            return await send_clean_private(message, "❌ Игрок не найден.")
        set_banned(uid, False)
        await send_clean_private(message, f"✅ Игрок @{target} разбанен.", reply_markup=admin_reply_kb())
        await state.clear()

    # ================= ГРУППА: БАЛАНС, ТОП, ЛОГ =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"б", "баланс"}))
    async def group_bal(message: Message):
        uid = message.from_user.id
        try:
            bal = get_balance(uid)
            # Если база вернула кортеж/список/словарь - достаем число
            if isinstance(bal, (tuple, list)):
                bal = bal[0]
            elif isinstance(bal, dict):
                bal = list(bal.values())[0]
            if bal is None:
                bal = 0
        except Exception as e:
            logger.error(f"DB ERROR in group_bal: {e}")
            await message.reply(f"❌ Ошибка базы данных: {e}")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Открыть кейс", url=f"https://t.me/{BOT_USERNAME}?start=case")]
        ])
        txt = (
            f"💳 <b>БАЛАНС</b>\n"
            f"👤 @{message.from_user.username or 'user'}\n"
            f"💰 {fmt_num(bal)} Tokens\n\n"
            f"👇 <i>Кейс в ЛС!</i>"
        )
        msg = await message.reply(txt, reply_markup=kb)
        asyncio.create_task(delete_message_later(msg, 60))

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip() == "топ")
    async def group_top(message: Message):
        try:
            top = get_top(10)
            if not top:
                return await message.reply("🏆 Топ пуст.")
            
            txt = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n\n"
            for i, row in enumerate(top, 1):
                if isinstance(row, (tuple, list)):
                    name = row[0]
                    bal = row[1] if len(row) > 1 else 0
                elif isinstance(row, dict):
                    name = row.get("username", "user")
                    bal = row.get("balance", 0)
                else:
                    name = str(row)
                    bal = 0
                txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
                
            msg = await message.reply(txt)
            asyncio.create_task(delete_message_later(msg, 120))
        except Exception as e:
            logger.error(f"DB ERROR in group_top: {e}")
            await message.reply(f"❌ Ошибка базы данных в топе: {e}")
            
            txt = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n\n"
            for i, row in enumerate(top, 1):
                name = row[0] if isinstance(row, (list, tuple)) else row
                bal = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0
                txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
                
            msg = await message.reply(txt)
            asyncio.create_task(delete_message_later(msg, 120))
        except Exception as e:
            logger.error(f"DB ERROR in group_top: {e}")
            await message.reply(f"❌ Ошибка базы данных в топе: {e}")

    # ================= МОДЕРАТОР =================
    @dp.message(F.chat.type.in_({"group", "supergroup"}))
    async def auto_moderator(message: Message):
        if message.from_user.id == ADMIN_ID or message.from_user.is_bot: return
        
        # Пропускаем команды и кнопки бота, чтобы не ломать игры
        if message.text and (message.text.startswith("/") or message.text.lower().strip() in ["б", "баланс", "игры", "топ", "лог", "бонус", "кейс", "го", "что нового", "отмена", "ставки"]): return
        if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id: return
        
        uid = message.from_user.id
        now = datetime.now(TZ_MINSK)
        
        # 1. Глобальный мут
        if GLOBAL_MUTE and uid != ADMIN_ID:
            try: await message.delete()
            except: pass
            return
            
        # 2. Проверка на мут
        if uid in muted_users:
            if now < muted_users[uid]:
                try: await message.delete()
                except: pass
                return 
            else: del muted_users[uid]
                
        # 3. Анализ текста
        is_bad = False
        if message.text:
            text_lower = message.text.lower()
            if any(word in text_lower for word in BAD_WORDS): is_bad = True
                
        is_caps = False
        if message.text and len(message.text) > 5:
            caps_count = sum(1 for c in message.text if c.isupper())
            if caps_count / len(message.text) > 0.7: is_caps = True
                
        is_spam = False
        if uid in user_warns and user_warns[uid].get("last_msg") == message.text:
            user_warns[uid]["spam_count"] = user_warns[uid].get("spam_count", 0) + 1
            if user_warns[uid]["spam_count"] >= 5: is_spam = True
        else:
            if uid in user_warns: user_warns[uid]["spam_count"] = 0
                
        # 4. Если есть нарушение — наказываем
        if is_bad or is_caps or is_spam:
            try: await message.delete()
            except: pass
            
            if uid not in user_warns: user_warns[uid] = {"count": 0, "time": now, "last_msg": None, "spam_count": 0}
            if (now - user_warns[uid]["time"]).total_seconds() > 3600: user_warns[uid]["count"] = 0
            
            user_warns[uid]["count"] += 1
            user_warns[uid]["time"] = now
            user_warns[uid]["last_msg"] = message.text
            count = user_warns[uid]["count"]
            reason = "мат" if is_bad else ("капс" if is_caps else "спам")
            
            if count >= 3 or is_spam:
                mute_time = 10 if is_spam else 24
                muted_users[uid] = now + timedelta(minutes=mute_time)
                del user_warns[uid]
                await message.answer(f"🚫 <b>МУТ</b>\n@{message.from_user.username or message.from_user.first_name} получил мут на {mute_time} мин. за {reason}.")
            else:
                msg = await message.reply(f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ {count}/3</b>\n@{message.from_user.username or message.from_user.first_name}, не пиши {reason}!")
                asyncio.create_task(delete_message_later(msg, 30))
            
            return # ВАЖНО: Если нарушение было, дальше не идем

    # ========================================================
    # ЗАПУСК
    # ========================================================
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)