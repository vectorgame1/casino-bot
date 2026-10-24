import asyncio
import logging
import sqlite3
import datetime
import random
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
AI_API_KEY = os.getenv("OPENROUTER_API_KEY", "") 
DB_PATH = "casino.db"
START_BONUS = 5000
CURRENCY = "Tokens"
GROUP_LINK = "https://t.me/+ТВОЯ_ССЫЛКА" # ВСТАВЬ ССЫЛКУ НА ГРУППУ!

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

user_router = Router()
admin_router = Router()
mod_router = Router()
pr_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, mod_router, pr_router, group_router)

# ==============================================================================
# БАЗА ДАННЫХ
# ==============================================================================
def db_execute(query, params=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone: result = cursor.fetchone()
    elif fetchall: result = cursor.fetchall()
    conn.commit()
    conn.close()
    return result

def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru',
        balance INTEGER DEFAULT 5000, xp INTEGER DEFAULT 0, rank TEXT DEFAULT 'Новичок',
        vip_until TEXT DEFAULT NULL, last_bonus TEXT DEFAULT NULL, streak INTEGER DEFAULT 0,
        last_wheel TEXT DEFAULT NULL, role TEXT DEFAULT 'user', warns INTEGER DEFAULT 0,
        clan_id INTEGER DEFAULT NULL, last_work TEXT DEFAULT NULL
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, treasury INTEGER DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, amount INTEGER, date TEXT
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS lottery (user_id INTEGER PRIMARY KEY)""")
    db_execute("""CREATE TABLE IF NOT EXISTS promos (
        code TEXT PRIMARY KEY, reward INTEGER, limit_count INTEGER, used_count INTEGER DEFAULT 0
    )""")
    logger.info("База данных инициализирована.")

def get_user(user_id):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        db_execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, "Unknown", START_BONUS))
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return user

def update_balance(user_id, amount, action="change"):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, ?, ?)", 
               (user_id, action, amount, datetime.datetime.now().isoformat()))

def is_vip(user_id):
    user = get_user(user_id)
    if user[6]:
        return datetime.datetime.fromisoformat(user[6]) > datetime.datetime.now()
    return False

def format_money(amount):
    return f"{amount:,}".replace(",", " ") + f" {CURRENCY}"

# ==============================================================================
# ЛОКАЛИЗАЦИЯ (RU/EN)
# ==============================================================================
TEXTS = {
    "ru": {
        "menu_games": "🎮 Игры", "menu_prof": "👤 Профиль", "menu_donate": "💎 Донат", 
        "menu_transfer": "💸 Перевод", "menu_help": "🆘 Поддержка", "menu_back": "⬅️ Назад",
        "welcome": "👑 <b>ДОБРО ПОЖАЛОВАТЬ В КАЗИНО</b>\n\n👋 Привет, {name}!\n👇 Выбери действие:",
        "profile": "👤 <b>ПРОФИЛЬ</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Баланс: <b>{bal}</b>\n💎 VIP: {vip}\n",
        "btn_bonus": "🎁 Бонус", "btn_history": "📜 История"
    },
    "en": {
        "menu_games": "🎮 Games", "menu_prof": "👤 Profile", "menu_donate": "💎 Donate", 
        "menu_transfer": "💸 Transfer", "menu_help": "🆘 Support", "menu_back": "⬅️ Back",
        "welcome": "👑 <b>WELCOME TO CASINO</b>\n\n👋 Hi, {name}!\n👇 Choose action:",
        "profile": "👤 <b>PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: <b>{bal}</b>\n💎 VIP: {vip}\n",
        "btn_bonus": "🎁 Bonus", "btn_history": "📜 History"
    }
}

def get_text(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, "Text not found")
    if kwargs: return text.format(**kwargs)
    return text

# ==============================================================================
# КЛАВИАТУРЫ
# ==============================================================================
def get_main_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "menu_games")), KeyboardButton(text=get_text(lang, "menu_prof")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_donate")), KeyboardButton(text=get_text(lang, "menu_transfer")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_help")))
    return builder.as_markup(resize_keyboard=True)

def get_profile_menu(lang):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=get_text(lang, "btn_bonus")), KeyboardButton(text=get_text(lang, "btn_history")))
    builder.row(KeyboardButton(text=get_text(lang, "menu_back")))
    return builder.as_markup(resize_keyboard=True)

# ==============================================================================
# СТАРТ И ПРОФИЛЬ
# ==============================================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private": return
    user = get_user(message.from_user.id)
    await state.clear()
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНА (Загрузится в Части 3)</b>", reply_markup=get_main_menu(user[2]))
    elif user[10] == "moderator":
        await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРА (Загрузится в Части 3)</b>", reply_markup=get_main_menu(user[2]))
    elif user[10] == "promoter":
        await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА (Загрузится в Части 3)</b>", reply_markup=get_main_menu(user[2]))
    else:
        await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

@user_router.message(F.text.in_(["👤 Профиль", "👤 Profile"]))
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    lang = user[2]
    vip = "✅" if is_vip(user[0]) else "❌"
    text = get_text(lang, "profile", uid=user[0], bal=format_money(user[3]), vip=vip)
    await message.answer(text, reply_markup=get_profile_menu(lang))

@user_router.message(F.text.in_(["⬅️ Назад", "⬅️ Back"]))
async def back_to_main(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(get_text(user[2], "welcome", name=message.from_user.first_name), reply_markup=get_main_menu(user[2]))

# ==============================================================================
# ПЕРЕВОДЫ И БОНУСЫ
# ==============================================================================
class TransferStates(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

@user_router.message(F.text.in_(["💸 Перевод", "💸 Transfer"]))
async def transfer_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await message.answer("Введи ID игрока, кому хочешь перевести:" if user[2]=="ru" else "Enter player ID to transfer:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(TransferStates.waiting_id)

@user_router.message(TransferStates.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    try: target_id = int(message.text)
    except: return await message.answer("❌ Введи число!")
    if target_id == message.from_user.id: return await message.answer("❌ Себе нельзя!")
    await state.update_data(target=target_id)
    await message.answer("Введи сумму перевода:" if get_user(message.from_user.id)[2]=="ru" else "Enter amount:")
    await state.set_state(TransferStates.waiting_amount)

@user_router.message(TransferStates.waiting_amount)
async def transfer_amount(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    target = data['target']
    sender = get_user(message.from_user.id)
    
    if sender[3] < amount: return await message.answer("❌ Мало средств!")
    if amount <= 0: return await message.answer("❌ Сумма > 0!")
    
    update_balance(sender[0], -amount, "transfer_out")
    update_balance(target, amount, "transfer_in")
    await message.answer(f"✅ Переведено {format_money(amount)} игроку <code>{target}</code>", reply_markup=get_main_menu(sender[2]))
    await state.clear()

@user_router.message(F.text.in_(["🎁 Бонус", "🎁 Bonus"]))
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    if user[7] and now - datetime.datetime.fromisoformat(user[7]) < datetime.timedelta(hours=24):
        return await message.answer("⏳ Бонус уже забран. Приходи позже." if user[2]=="ru" else "⏳ Bonus already claimed.")
    update_balance(user[0], 5000, "bonus")
    db_execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await message.answer("🎁 Ты забрал бонус: <b>5 000 Tokens</b>!" if user[2]=="ru" else "🎁 You claimed bonus: <b>5 000 Tokens</b>!")

# ==============================================================================
# ЧАСТЬ 2: ИГРЫ (Стикеры, Рулетка, Мины, Лесенка, БЖ, Джокер)
# ==============================================================================
import asyncio

# --- 1. МЕНЮ ИГР В ГРУППЕ ---
@group_router.message(Command("игры"))
async def group_games_menu(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кости", callback_data="g_dice")
    builder.button(text="🎯 Дартс", callback_data="g_darts")
    builder.button(text="🏀 Баскет", callback_data="g_basket")
    builder.button(text="⚽ Футбол", callback_data="g_football")
    builder.button(text="🎳 Боулинг", callback_data="g_bowling")
    builder.button(text="🎡 Рулетка", callback_data="g_roulette")
    builder.button(text="💣 Мины", callback_data="g_mines")
    builder.button(text="🪜 Лесенка", callback_data="g_stairs")
    builder.button(text="🃏 Блэкджек", callback_data="g_bj")
    builder.button(text="🃏 Джокер", callback_data="g_joker")
    builder.adjust(2, 2, 2, 2, 2)
    
    await message.answer(
        "🎰 <b>ИГРОВОЙ ЗАЛ</b>\n"
        "Выбери игру (пиши сумму в чат, например: <code>кости 1000</code>):",
        reply_markup=builder.as_markup()
    )

# --- 2. СТИКЕРЫ (Кости, Дартс, Баскет, Футбол, Боулинг) ---
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг)\s+(\d+)$"))
async def play_dice_group(message: Message):
    parts = message.text.lower().split()
    game, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount, f"bet_{game}")
    emoji = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳"}[game]
    
    msg = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5)
    val = msg.dice.value
    
    win = False
    if game in ["кости", "дартс"] and val >= 4: win = True
    elif game == "баскет" and val >= 3: win = True
    elif game == "футбол" and val >= 4: win = True
    elif game == "боулинг" and val == 6: win = True
    
    if win:
        update_balance(user[0], amount * 2, f"win_{game}")
        await message.reply(f"🎉 Победа! Выпало {val}. Выигрыш: {format_money(amount * 2)}!")
    else:
        await message.reply(f"😢 Проигрыш. Выпало {val}.")

# --- 3. РУЛЕТКА (Текстовая) ---
active_roulette = {}

@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет)\s+(\d+)$"))
async def bet_roulette(message: Message):
    parts = message.text.lower().split()
    bet, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    chat_id = message.chat.id
    if chat_id not in active_roulette: active_roulette[chat_id] = []
    
    update_balance(user[0], -amount, "roulette_bet")
    active_roulette[chat_id].append({"uid": user[0], "bet": bet, "amount": amount})
    await message.reply(f"✅ Ставка {amount} на {bet} принята. Жми 'го'!")

@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette or not active_roulette[chat_id]: return
    
    bets = active_roulette.pop(chat_id)
    msg = await message.answer("🎡 Рулетка крутится...")
    await asyncio.sleep(3)
    
    result = random.choice(["к", "ч", "з"])
    res_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[result]
    text = f"🎯 Выпало: <b>{res_name}</b>\n\n"
    
    winners = []
    for b in bets:
        win = False
        if b['bet'] == result or (result == "к" and b['bet'] in ["красное", "чет"]) or (result == "ч" and b['bet'] in ["черное", "нечет"]):
            win = True
        elif b['bet'] == "з" and result == "з": win = True
            
        if win:
            prize = b['amount'] * 2
            update_balance(b['uid'], prize, "roulette_win")
            winners.append(f"👤 <a href='tg://user?id={b['uid']}'>{b['uid']}</a> выиграл {format_money(prize)}")
            
    text += "\n".join(winners) if winners else "😢 Победителей нет."
    await msg.edit_text(text)

# --- 4. МИНЫ (Сетка 5х5) ---
active_mines = {}

@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount, "bet_mines")
    game_key = f"{message.chat.id}_{message.from_user.id}"
    mines = random.sample(range(25), 5)
    active_mines[game_key] = {"uid": user[0], "bet": amount, "mines": mines, "opened": []}
    
    builder = InlineKeyboardBuilder()
    for i in range(25):
        builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    
    await message.reply(f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}\nИщи безопасные клетки!", reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("m_"))
async def open_mine(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4: return
    game_key = f"{parts[1]}_{parts[2]}"
    cell = int(parts[3])
    
    if game_key not in active_mines: return await callback.answer("Игра окончена.", show_alert=True)
    game = active_mines[game_key]
    if callback.from_user.id != game["uid"]: return await callback.answer("Не твоя игра!", show_alert=True)
    if cell in game["opened"]: return await callback.answer("Уже открыта.", show_alert=True)
    
    if cell in game["mines"]:
        builder = InlineKeyboardBuilder()
        for i in range(25): builder.button(text="💥" if i in game["mines"] else "💎", callback_data="m_ign")
        builder.adjust(5, 5, 5, 5, 5)
        await callback.message.edit_text(f"💥 <b>БУМ!</b> Вы проиграли {format_money(game['bet'])}.", reply_markup=builder.as_markup())
        del active_mines[game_key]
        return await callback.answer()
        
    game["opened"].append(cell)
    win = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    
    builder = InlineKeyboardBuilder()
    for i in range(25):
        if i in game["opened"]: builder.button(text="💎", callback_data="m_ign")
        else: builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    builder.row(InlineKeyboardButton(text=f"💰 Забрать {format_money(win)}", callback_data=f"m_cash_{game_key}"))
    
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer(f"Безопасно! Потенциал: {format_money(win)}")

@group_router.callback_query(F.data.startswith("m_cash_"))
async def cashout_mine(callback: CallbackQuery):
    game_key = callback.data.split("m_cash_")[1]
    if game_key not in active_mines: return
    game = active_mines[game_key]
    win = int(game["bet"] * (1 + len(game["opened"]) * 0.2))
    update_balance(game["uid"], win, "win_mines")
    await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
    del active_mines[game_key]
    await callback.answer("Зачислено!")

@group_router.callback_query(F.data == "m_ign")
async def ign_mine(callback: CallbackQuery):
    await callback.answer("Недоступно.")

# --- 5. ЛЕСЕНКА (10 шагов, 3 обрыва) ---
active_stairs = {}

@group_router.message(F.text.regexp(r"(?i)^лесенка\s+(\d+)$"))
async def play_stairs(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount, "bet_stairs")
    game_key = f"{message.chat.id}_{message.from_user.id}"
    dead_cells = random.sample(range(1, 10), 3)
    active_stairs[game_key] = {"uid": user[0], "bet": amount, "dead": dead_cells, "step": 1}
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🚶 Шагнуть (x1.3)", callback_data=f"st_{game_key}")
    
    await message.reply(f"🪜 <b>ЛЕСЕНКА</b>\nСтавка: {format_money(amount)}\nПройди 10 шагов, избегай 3 обрывов!", reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("st_"))
async def step_stairs(callback: CallbackQuery):
    game_key = callback.data.split("st_")[1]
    if game_key not in active_stairs: return
    game = active_stairs[game_key]
    if callback.from_user.id != game["uid"]: return await callback.answer("Не твоя игра!", show_alert=True)
    
    game["step"] += 1
    if game["step"] in game["dead"]:
        await callback.message.edit_text(f"💀 <b>СГОРЕЛ!</b> Вы упали на шаге {game['step']}. Проигрыш {format_money(game['bet'])}.")
        del active_stairs[game_key]
        return await callback.answer()
        
    if game["step"] >= 10:
        win = game["bet"] * 5
        update_balance(game["uid"], win, "win_stairs")
        await callback.message.edit_text(f"🏆 <b>ПОБЕДА!</b> Вы прошли 10 шагов! Выигрыш x5: {format_money(win)}!")
        del active_stairs[game_key]
        return await callback.answer()
        
    win = int(game["bet"] * (1 + game["step"] * 0.3))
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🚶 Шагнуть (x{1 + game['step']*0.3:.1f})", callback_data=f"st_{game_key}")
    builder.button(text=f"💰 Забрать {format_money(win)}", callback_data=f"st_cash_{game_key}")
    builder.adjust(1, 1)
    
    await callback.message.edit_text(f"🪜 <b>ЛЕСЕНКА</b>\nШаг: {game['step']}/10\nПотенциал: {format_money(win)}", reply_markup=builder.as_markup())
    await callback.answer("Успешно!")

@group_router.callback_query(F.data.startswith("st_cash_"))
async def cashout_stairs(callback: CallbackQuery):
    game_key = callback.data.split("st_cash_")[1]
    if game_key not in active_stairs: return
    game = active_stairs[game_key]
    win = int(game["bet"] * (1 + game["step"] * 0.3))
    update_balance(game["uid"], win, "win_stairs")
    await callback.message.edit_text(f"💰 Вы забрали {format_money(win)} на шаге {game['step']}!")
    del active_stairs[game_key]
    await callback.answer("Зачислено!")

# --- 6. БЛЭКДЖЕК (Упрощенный) ---
active_bj = {}

@group_router.message(F.text.regexp(r"(?i)^бж\s+(\d+)$"))
async def play_bj(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount, "bet_bj")
    game_key = f"{message.chat.id}_{message.from_user.id}"
    p_cards = [random.randint(2, 11), random.randint(2, 11)]
    d_cards = [random.randint(2, 11), random.randint(2, 11)]
    active_bj[game_key] = {"uid": user[0], "bet": amount, "p": p_cards, "d": d_cards}
    
    text = f"🃏 <b>БЛЭКДЖЕК</b>\nТвои карты: {p_cards[0]} + {p_cards[1]} = {sum(p_cards)}\nДилер: {d_cards[0]} + ?\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="Взять", callback_data=f"bj_hit_{game_key}")
    builder.button(text="Хватит", callback_data=f"bj_stand_{game_key}")
    
    await message.reply(text, reply_markup=builder.as_markup())

@group_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(callback: CallbackQuery):
    game_key = callback.data.split("bj_hit_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    
    card = random.randint(2, 11)
    game["p"].append(card)
    score = sum(game["p"])
    
    if score > 21:
        await callback.message.edit_text(f"🃏 Перебор! Сумма: {score}. Проигрыш {format_money(game['bet'])}.")
        del active_bj[game_key]
    else:
        text = f"🃏 <b>БЛЭКДЖЕК</b>\nТвои карты: {', '.join(map(str, game['p']))} = {score}\nДилер: {game['d'][0]} + ?"
        builder = InlineKeyboardBuilder()
        builder.button(text="Взять", callback_data=f"bj_hit_{game_key}")
        builder.button(text="Хватит", callback_data=f"bj_stand_{game_key}")
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@group_router.callback_query(F.data.startswith("bj_stand_"))
async def bj_stand(callback: CallbackQuery):
    game_key = callback.data.split("bj_stand_")[1]
    if game_key not in active_bj: return
    game = active_bj[game_key]
    p_score = sum(game["p"])
    d_score = sum(game["d"])
    while d_score < 17:
        game["d"].append(random.randint(2, 11))
        d_score = sum(game["d"])
    
    text = f"🃏 <b>БЛЭКДЖЕК</b>\nТвои: {', '.join(map(str, game['p']))} = {p_score}\nДилер: {', '.join(map(str, game['d']))} = {d_score}\n\n"
    if d_score > 21 or p_score > d_score:
        update_balance(game["uid"], game["bet"] * 2, "win_bj")
        text += "🎉 Ты выиграл!"
    elif p_score == d_score:
        update_balance(game["uid"], game["bet"], "draw_bj")
        text += "🤝 Ничья. Возврат ставки."
    else:
        text += "😢 Дилер выиграл."
    await callback.message.edit_text(text)
    del active_bj[game_key]
    await callback.answer()

# --- 7. ДЖОКЕР (Быстрая игра) ---
@group_router.message(F.text.regexp(r"(?i)^джокер\s+(\d+)$"))
async def play_joker(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount, "bet_joker")
    msg = await message.answer_dice(emoji="🃏")
    await asyncio.sleep(3)
    
    if msg.dice.value in [1, 2]:
        update_balance(user[0], amount * 3, "win_joker")
        await message.reply(f"🃏 ДЖОКЕР! Выигрыш x3: {format_money(amount * 3)}!")
    else:
        await message.reply("😢 Не повезло.")

# ==============================================================================
# ЧАСТЬ 3: АДМИНКА, МОДЕРЫ, ПИАРЩИКИ, ПОДДЕРЖКА И ИИ
# ==============================================================================

# --- 1. СОСТОЯНИЯ ДЛЯ FSM ---
class AdminStates(StatesGroup):
    waiting_give_id = State()
    waiting_give_amount = State()
    waiting_promo = State()
    waiting_ai_prompt = State()
    waiting_broadcast = State()

class ModStates(StatesGroup):
    waiting_mod_give_id = State()
    waiting_mod_give_amount = State()

class SupportStates(StatesGroup):
    waiting_ticket = State()

# ==============================================================================
# 2. ПАНЕЛЬ АДМИНА
# ==============================================================================
async def show_admin_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Live-Статистика", callback_data="adm_stats")
    builder.button(text="💸 Экономика", callback_data="adm_eco")
    builder.button(text="🎁 Промокоды", callback_data="adm_promo")
    builder.button(text="👥 Люди", callback_data="adm_people")
    builder.button(text="🤖 ИИ-Генератор", callback_data="adm_ai")
    builder.button(text="⬅️ В меню игрока", callback_data="adm_exit")
    builder.adjust(2, 2, 1, 1)
    await message.answer("👑 <b>ПАНЕЛЬ АДМИНА</b>\nВыбери действие:", reply_markup=builder.as_markup())

@admin_router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("Нет доступа", show_alert=True)
    users = db_execute("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_bal = db_execute("SELECT SUM(balance) FROM users", fetchone=True)[0] or 0
    text = f"📊 <b>СТАТИСТИКА</b>\n\n👥 Игроков: <b>{users}</b>\n💰 В обороте: <b>{format_money(total_bal)}</b>"
    builder = InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="adm_back")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@admin_router.callback_query(F.data == "adm_eco")
async def adm_eco(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("Нет доступа", show_alert=True)
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Выдать по ID", callback_data="eco_give_id")
    builder.button(text="💸 Забрать по ID", callback_data="eco_take_id")
    builder.button(text="📉 Налог 10%", callback_data="eco_tax")
    builder.button(text="⬅️ Назад", callback_data="adm_back")
    builder.adjust(2, 1, 1)
    await callback.message.edit_text("💸 <b>ЭКОНОМИКА</b>\nВыбери операцию:", reply_markup=builder.as_markup())

@admin_router.callback_query(F.data == "eco_tax")
async def eco_tax(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("Нет доступа", show_alert=True)
    users = db_execute("SELECT user_id, balance FROM users WHERE balance > 100000", fetchall=True)
    total = 0
    for u in users:
        tax = int(u[1] * 0.1)
        update_balance(u[0], -tax, "tax")
        total += tax
    await callback.answer(f"📉 Собрано налогов: {format_money(total)}", show_alert=True)

@admin_router.callback_query(F.data == "eco_give_id")
async def eco_give_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введи ID игрока, кому выдать:")
    await state.set_state(AdminStates.waiting_give_id)

@admin_router.message(AdminStates.waiting_give_id)
async def eco_give_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target, action="give")
    await message.answer("Введи сумму:")
    await state.set_state(AdminStates.waiting_give_amount)

@admin_router.callback_query(F.data == "eco_take_id")
async def eco_take_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введи ID игрока, у кого забрать:")
    await state.set_state(AdminStates.waiting_give_id)

@admin_router.message(AdminStates.waiting_give_amount)
async def eco_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    data = await state.get_data()
    target, action = data['target'], data['action']
    
    if action == "give":
        update_balance(target, amount, "admin_give")
        await message.answer(f"✅ Выдано {format_money(amount)} игроку {target}")
    else:
        update_balance(target, -amount, "admin_take")
        await message.answer(f"✅ Забрано {format_money(amount)} у игрока {target}")
    await state.clear()

@admin_router.callback_query(F.data == "adm_promo")
async def adm_promo(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать промокод", callback_data="promo_create")
    builder.button(text="⬅️ Назад", callback_data="adm_back")
    builder.adjust(1, 1)
    await callback.message.edit_text("🎁 <b>ПРОМОКОДЫ</b>", reply_markup=builder.as_markup())

@admin_router.callback_query(F.data == "promo_create")
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи код, сумму и лимит через пробел:\nПример: <code>WELCOME 5000 100</code>")
    await state.set_state(AdminStates.waiting_promo)

@admin_router.message(AdminStates.waiting_promo)
async def promo_create_finish(message: Message, state: FSMContext):
    try:
        code, reward, limit = message.text.split()
        db_execute("INSERT OR REPLACE INTO promos (code, reward, limit_count) VALUES (?, ?, ?)", (code.upper(), int(reward), int(limit)))
        await message.answer(f"✅ Промокод <b>{code.upper()}</b> создан!")
    except:
        await message.answer("❌ Ошибка формата. Пиши: КОД СУММА ЛИМИТ")
    await state.clear()

@admin_router.callback_query(F.data == "adm_ai")
async def adm_ai_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🤖 <b>ИИ-ГЕНЕРАТОР</b>\nНапиши запрос (например: 'Напиши рекламный пост про рулетку'):")
    await state.set_state(AdminStates.waiting_ai_prompt)

@admin_router.message(AdminStates.waiting_ai_prompt)
async def process_ai(message: Message, state: FSMContext):
    if not AI_API_KEY: 
        await message.answer("❌ Нет API ключа OpenRouter в настройках!")
        await state.clear()
        return
    
    await message.answer("⏳ Генерирую...")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "meta-llama/llama-3-8b-instruct:free",
        "messages": [{"role": "user", "content": message.text}]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    text = res['choices'][0]['message']['content']
                    await message.answer(f"📝 <b>ИИ ответил:</b>\n\n{text}")
                else:
                    await message.answer("❌ Ошибка ИИ. Проверь ключ.")
    except Exception as e:
        await message.answer(f"❌ Ошибка сети: {e}")
    await state.clear()

@admin_router.callback_query(F.data == "adm_back")
async def adm_back(callback: CallbackQuery):
    await show_admin_panel(callback.message)

@admin_router.callback_query(F.data == "adm_exit")
async def adm_exit(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Ты в меню игрока:", reply_markup=get_main_menu(get_user(callback.from_user.id)[2]))

# --- Ввод промокода ИГРОКОМ ---
@user_router.message(F.text.regexp(r"(?i)^промо\s+(\w+)$"))
async def use_promo(message: Message):
    code = message.text.split()[1].upper()
    promo = db_execute("SELECT reward, limit_count, used_count FROM promos WHERE code = ?", (code,), fetchone=True)
    if not promo: return await message.reply("❌ Промокод не найден.")
    if promo[2] >= promo[1]: return await message.reply("❌ Лимит активаций исчерпан.")
    
    user = get_user(message.from_user.id)
    update_balance(user[0], promo[0], f"promo_{code}")
    db_execute("UPDATE promos SET used_count = used_count + 1 WHERE code = ?", (code,))
    await message.reply(f"✅ Промокод активирован! Ты получил {format_money(promo[0])}!")

# ==============================================================================
# 3. ПАНЕЛЬ МОДЕРА
# ==============================================================================
async def show_mod_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Выдать Токены", callback_data="mod_give")
    builder.button(text="🚫 Забанить", callback_data="mod_ban")
    builder.button(text="🧹 Очистить чат", callback_data="mod_clean")
    builder.button(text="⬅️ Выход", callback_data="adm_exit")
    builder.adjust(2, 1, 1)
    await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРА</b>\nЛимит выдачи: 500 000 Tokens/день.", reply_markup=builder.as_markup())

@mod_router.callback_query(F.data == "mod_give")
async def mod_give_start(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if user[10] not in ["moderator", "admin"] and callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введи ID игрока, кому выдать токены:")
    await state.set_state(ModStates.waiting_mod_give_id)

@mod_router.message(ModStates.waiting_mod_give_id)
async def mod_give_amount(message: Message, state: FSMContext):
    try: target = int(message.text)
    except: return await message.answer("❌ Введи число!")
    await state.update_data(target=target)
    await message.answer("Введи сумму (лимит 500к):")
    await state.set_state(ModStates.waiting_mod_give_amount)

@mod_router.message(ModStates.waiting_mod_give_amount)
async def mod_give_finish(message: Message, state: FSMContext):
    try: amount = int(message.text)
    except: return await message.answer("❌ Введи число!")
    
    if amount > 500000:
        return await message.answer("❌ Превышен лимит выдачи (макс 500 000)!")
        
    data = await state.get_data()
    update_balance(data['target'], amount, "mod_give")
    await message.answer(f"✅ Выдано {format_money(amount)} игроку {data['target']}")
    await state.clear()

@mod_router.callback_query(F.data == "mod_ban")
async def mod_ban_start(callback: CallbackQuery):
    await callback.message.edit_text("Напиши в чат: <code>/бан ID</code> (или ответом на сообщение)")

@mod_router.callback_query(F.data == "mod_clean")
async def mod_clean_start(callback: CallbackQuery):
    await callback.message.edit_text("Напиши в чат: <code>/чистка 50</code> (удалит 50 последних сообщений)")

# ==============================================================================
# 4. ПАНЕЛЬ ПИАРЩИКА
# ==============================================================================
async def show_pr_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Моя Реф-Ссылка", callback_data="pr_ref")
    builder.button(text="🎁 Создать Промокод", callback_data="pr_promo")
    builder.button(text="🤖 ИИ-Копирайтер", callback_data="pr_ai")
    builder.button(text="⬅️ Выход", callback_data="adm_exit")
    builder.adjust(1, 1, 1, 1)
    await message.answer("📢 <b>ПАНЕЛЬ ПИАРЩИКА</b>", reply_markup=builder.as_markup())

@pr_router.callback_query(F.data == "pr_ref")
async def pr_ref(callback: CallbackQuery):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    await callback.message.edit_text(f"🔗 <b>Твоя реферальная ссылка:</b>\n\n<code>{link}</code>\n\nПриглашай людей и получай % от их проигрышей!")

@pr_router.callback_query(F.data == "pr_ai")
async def pr_ai_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🤖 Введи тему для рекламного поста:")
    await state.set_state(AdminStates.waiting_ai_prompt)

# ==============================================================================
# 5. ПОДДЕРЖКА (FAQ и Тикеты)
# ==============================================================================
def get_support_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Как заработать?", callback_data="sup_earn")
    builder.button(text="💳 Проблема с оплатой", callback_data="sup_pay")
    builder.button(text="🎁 Не пришел бонус", callback_data="sup_bonus")
    builder.button(text="🎰 Как играть?", callback_data="sup_games")
    builder.button(text="✍️ Написать Админу", callback_data="sup_ticket")
    builder.button(text="⬅️ Назад", callback_data="sup_back")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

@user_router.message(F.text.in_(["🆘 Поддержка", "🆘 Support"]))
async def support_menu(message: Message):
    await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>\nВыбери тему, которая тебя интересует:", reply_markup=get_support_menu())

@user_router.callback_query(F.data.startswith("sup_"))
async def support_handler(callback: CallbackQuery, state: FSMContext):
    if callback.data == "sup_back":
        await callback.message.delete()
        return await callback.answer()
        
    if callback.data == "sup_earn":
        await callback.message.edit_text("💰 <b>КАК ЗАРАБОТАТЬ</b>\n\n1. Играй в игры в нашем чате.\n2. Забирай ежедневный бонус.\n3. Работай (/работа в чате).\n4. Выигрывай в лотерею.", reply_markup=get_support_menu())
    elif callback.data == "sup_pay":
        await callback.message.edit_text("💳 <b>ОПЛАТА</b>\n\nЕсли Stars списались, а токены не пришли — напиши Админу.", reply_markup=get_support_menu())
    elif callback.data == "sup_bonus":
        await callback.message.edit_text("🎁 <b>БОНУС</b>\n\nБонус доступен раз в 24 часа. Проверь время в профиле.", reply_markup=get_support_menu())
    elif callback.data == "sup_games":
        await callback.message.edit_text("🎰 <b>ИГРЫ</b>\n\nВсе игры в чате. Напиши /игры в группе.", reply_markup=get_support_menu())
    elif callback.data == "sup_ticket":
        await callback.message.edit_text("✍️ Напиши свой вопрос одним сообщением. Админ ответит тебе в ЛС.")
        await state.set_state(SupportStates.waiting_ticket)
    await callback.answer()

@user_router.message(SupportStates.waiting_ticket)
async def process_ticket(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    admin_text = f"📩 <b>ТИКЕТ</b>\nОт: @{message.from_user.username} (ID: <code>{user[0]}</code>)\n\n{message.text}\n\n<i>Ответь Reply на это сообщение.</i>"
    try:
        admin_msg = await bot.send_message(ADMIN_ID, admin_text)
        db_execute("INSERT INTO logs (user_id, action, amount, date) VALUES (?, ?, 0, ?)", (user[0], f"ticket_{admin_msg.message_id}", datetime.datetime.now().isoformat()))
        await message.answer("✅ Вопрос отправлен Админу. Ожидай ответа.")
    except:
        await message.answer("❌ Ошибка отправки.")

@admin_router.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply_ticket(message: Message):
    if not message.reply_to_message: return
    log = db_execute("SELECT user_id FROM logs WHERE action = ?", (f"ticket_{message.reply_to_message.message_id}",), fetchone=True)
    if log:
        try:
            await bot.send_message(log[0], f"✉️ <b>ОТВЕТ ОТ АДМИНА:</b>\n\n{message.text}")
            await message.reply("✅ Ответ отправлен игроку.")
        except:
            await message.reply("❌ Игрок закрыл ЛС.")

# ==============================================================================
# ЗАПУСК
# ==============================================================================
async def main():
    init_db()
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")