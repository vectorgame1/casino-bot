import asyncio
import logging
import datetime
import os
import random
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, KeyboardButton, InlineKeyboardButton, ReplyKeyboardRemove, FSInputFile, LabeledPrice
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from psycopg_pool import ConnectionPool

# НАСТРОЙКИ
BOT_TOKEN = "8940867005:AAHeQpS4_I1XZWfzC107G3EPNneQF_8JbYA" 
ADMIN_ID = 6403424348 
CHAT_ID = -1004366922819 
GROUP_LINK = "https://t.me/tokenplays"
START_BONUS = 5000
CURRENCY = "Tokens"
LINK_TO_TERMS = "https://telegra.ph/Pravila-01-01"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

user_router = Router()
admin_router = Router()
group_router = Router()
dp.include_routers(user_router, admin_router, group_router)

# БАЗА
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, open=True)

def db_execute(query, params=(), fetchone=False, fetchall=False):
    query = query.replace("?", "%s")
    try:
        with db_pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchone() if fetchone else cursor.fetchall() if fetchall else None
                conn.commit()
                return result
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        return None

def get_user(user_id):
    user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        db_execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, "Unknown", START_BONUS))
        user = db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    return user

def update_balance(user_id, amount):
    db_execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))

def format_money(amount):
    return f"{amount:,}".replace(",", " ") + f" {CURRENCY}"

def init_db():
    db_execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'ru', balance BIGINT DEFAULT 5000,
        role TEXT DEFAULT 'user', last_bonus TEXT, clan_id INTEGER DEFAULT NULL, clan_donated BIGINT DEFAULT 0
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS clans (
        id SERIAL PRIMARY KEY, name TEXT, owner_id BIGINT, treasury BIGINT DEFAULT 0, join_fee BIGINT DEFAULT 5000, level INTEGER DEFAULT 1
    )""")
    db_execute("""CREATE TABLE IF NOT EXISTS tickets (id SERIAL PRIMARY KEY, user_id BIGINT, text TEXT, date TEXT)""")
    db_execute("""CREATE TABLE IF NOT EXISTS games_log (id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet BIGINT, win BIGINT, date TEXT)""")
    logger.info("База готова.")

# СТИКЕРЫ (ПРАВИЛЬНЫЕ!)
STICKER_MONEY = "CAACAgIAAxkBAAEj985q4eL9Brj-YpyQvGjLXw3FCOZZjQACSKgAAjAhEUsk5lafkHLFYD0E"
STICKER_GIFT = "CAACAgIAAxkBAAEj98Bq4eLXEYu2vZI5kR8FAa-5At5VCwACLqwAAkDWEEu1vr_yoL997j0E"
STICKER_CHECK = "CAACAgIAAxkBAAEj97Jq4eKR30htSL0IqPlPzJVRVzFtJwACYqIAAmLKEEtbsW05dAABQME9BA"
STICKER_CROSS = "CAACAgIAAxkBAAEj97Zq4eKm7xpZZNfngFE8pjITZLQJ8wACaqUAArUtEUtHgEGdmAH6CT0E"
STICKER_VIP = "CAACAgIAAxkBAAEj99Bq4eL-1vc-E-lWg0SnnmQOohX96wACxaQAAu96EUteo43HZ6JM4T0E"
STICKER_WAIT = "CAACAgIAAxkBAAEj97hq4eKu4LVAQjvc8bvWLJsPGs4AAfcAAu6lAAIhCRFLfU-i5scDVp49BA"
STICKER_TRANSFER = "CAACAgEAAxkBAAEj9-Bq4eVW4VZEtByB92myle5Upux2mgACzgIAAgZEGETPmJF48lyuaD0E"
STICKER_TICKET = "CAACAgIAAxkBAAEj975q4eLJDqoTYwmhP1WgPmG147qWZgACdKkAAlAcEEt7BK5iDF740T0E"
STICKER_WHEEL = "CAACAgIAAxkBAAEj98Jq4eLY_6DZL-z-pta0MkNblBDoIAACY6YAAopJCEulegpkQ4jAtj0E"

# КЛАВИАТУРЫ
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус"))
    builder.row(KeyboardButton(text="💎 Донат"), KeyboardButton(text="🛡 Клан"))
    builder.row(KeyboardButton(text="🆘 Поддержка"))
    return builder.as_markup(resize_keyboard=True)

def get_profile_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📜 История"), KeyboardButton(text="🔗 Моя Рефка"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_support_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="💰 Как заработать?"), KeyboardButton(text="💳 Проблема с оплатой"))
    builder.row(KeyboardButton(text="✍️ Написать Админу"), KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_donate_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⭐ Купить Звезды"), KeyboardButton(text="👑 Купить VIP"))
    builder.row(KeyboardButton(text="⬅️ Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_clan_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
    builder.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="📜 Мой клан"))
    builder.row(KeyboardButton(text="🚪 Выйти из клана"), KeyboardButton(text="⬅️ В Игры"))
    return builder.as_markup(resize_keyboard=True)

# ==============================================================================
# ЧАСТЬ 2: СТАРТ, ПРОФИЛЬ, ДОНАТ, ПОДДЕРЖКА
# ==============================================================================

# Стикеры для VIP (рандомный выбор)
VIP_STICKERS = [
    "CAACAgIAAxkBAAEj96xq4eJXgVef7iLshpSS5HehGR9fvAACX7IAAgOYEEtkVuP2AAGD3tY9BA", # 1-й VIP
    "CAACAgIAAxkBAAEj965q4eJ3NdOJTNZKOXjLl-EefvciHgACJaAAAuNkEEtMkr6KfsoC1j0E", # 2-й VIP
    "CAACAgIAAxkBAAEj97Bq4eJ6Nm0yg_NAkGH6X0a3pgmesAACXrgAAjPACUvbsySuV4_7ez0E"  # 3-й VIP
]

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    
    if user[4] == "banned":
        try: await message.answer_sticker(STICKER_CROSS)
        except: pass
        return await message.answer("🚫 <b>Твой аккаунт заблокирован.</b>")

    text = (
        f"👑 <b>ДОБРО ПОЖАЛОВАТЬ В ИМПЕРИЮ TOKENS, {message.from_user.first_name}!</b>\n\n"
        f"💎 Здесь ты сам вершишь свою судьбу. Испытай удачу в играх, прокачай свой клан или сорви джекпот в нашем чате!\n\n"
        f"⚖️ <i>Виртуальная экономика. Все ставки — исключительно развлечение. Играй с умом.</i>\n\n"
        f"📜 Нажимая кнопки ниже, ты соглашаешься с правилами нашего Дома."
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🚀 Ворваться в игру (Чат)", url=GROUP_LINK))
    builder.row(InlineKeyboardButton(text="📜 Правила Дома", url=LINK_TO_TERMS))

    try:
        photo = FSInputFile("assets/start.jpg")
        await message.answer_photo(photo=photo, caption=text, reply_markup=builder.as_markup())
    except:
        await message.answer(text, reply_markup=builder.as_markup())
        
    await message.answer("👇 <i>Твой личный кабинет:</i>", reply_markup=get_main_menu())

@user_router.message(F.text == "⬅️ Назад")
async def global_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню:", reply_markup=get_main_menu())

# --- ПРОФИЛЬ ---
@user_router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_user(message.from_user.id)
    rank = "💎 Легенда" if user[3] > 1000000 else "🔥 Хайроллер" if user[3] > 500000 else "⭐ Профи" if user[3] > 100000 else "🟢 Новичок"
    vip = "👑 VIP" if user[4] == "vip" else "❌ Нет"
    
    text = (
        f"👤 <b>ТВОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"🏆 Ранг: <b>{rank}</b>\n"
        f"💰 Баланс: <b>{format_money(user[3])}</b>\n"
        f"💎 VIP: {vip}\n"
        f"🛡 Клан: {'Есть' if user[12] else 'Нет'}"
    )
    
    # Если VIP, показываем случайный VIP стикер
    if user[4] == "vip":
        try: await message.answer_sticker(random.choice(VIP_STICKERS))
        except: pass
        
    await message.answer(text, reply_markup=get_profile_menu())

@user_router.message(F.text == "🎁 Бонус")
async def daily_bonus(message: Message):
    user = get_user(message.from_user.id)
    now = datetime.datetime.now()
    
    if user[5] and now - datetime.datetime.fromisoformat(user[5]) < datetime.timedelta(hours=24):
        time_left = datetime.timedelta(hours=24) - (now - datetime.datetime.fromisoformat(user[5]))
        try: await message.answer_sticker(STICKER_WAIT)
        except: pass
        return await message.answer(f"⏳ <b>Бонус уже забран.</b>\nСледующий через: <b>{time_left.seconds//3600} ч. {(time_left.seconds%3600)//60} мин.</b>", reply_markup=get_main_menu())
        
    # ТУТ СТИКЕР КОЛЕСА
    try: await message.answer_sticker(STICKER_WHEEL)
    except: pass
    
    status = await message.answer("🎁 <i>Крутим колесо удачи...</i> 🎡")
    await asyncio.sleep(1.5)
    
    prizes = [(2500, 25), (3000, 20), (4000, 15), (5000, 15), (7500, 10), (10000, 7), (15000, 4), (20000, 2.5), (25000, 1.5)]
    choices = [p[0] for p in prizes]
    weights = [p[1] for p in prizes]
    prize = random.choices(choices, weights=weights, k=1)[0]
    
    update_balance(user[0], prize)
    db_execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now.isoformat(), user[0]))
    await status.delete()
    
    await message.answer(f"🎉 <b>УДАЧА УЛЫБНУЛАСЬ ТЕБЕ!</b>\n\n💰 Ты выиграл: <b>+{format_money(prize)}</b>\n\n<i>Приходи завтра!</i>", reply_markup=get_main_menu())

# --- ДОНАТ ---
@user_router.message(F.text == "💎 Донат")
async def donate_menu(message: Message):
    hour = datetime.datetime.now().hour
    random.seed(hour // 3)
    rate = random.randint(8000, 15000)
    rate_str = f"{rate:,}".replace(",", " ")
    text = f"💎 <b>ДОНАТ И VIP</b>\n\n🔥 Курс дня: 1 ⭐ = <b>{rate_str} Tokens</b>\n<i>(Обновляется каждые 3 часа)</i>\n\n👇 <i>Выбери:</i>"
    await message.answer(text, reply_markup=get_donate_menu())

@user_router.message(F.text == "⭐ Купить Звезды")
async def buy_stars_menu(message: Message):
    hour = datetime.datetime.now().hour
    random.seed(hour // 3)
    rate = random.randint(8000, 15000)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⭐ 15 Stars", callback_data=f"buy_stars_15_{rate}"))
    builder.row(InlineKeyboardButton(text="⭐ 50 Stars", callback_data=f"buy_stars_50_{rate}"))
    await message.answer(f"⭐ <b>ПОКУПКА ЗВЕЗД</b>\n\n🔥 Курс: 1 ⭐ = {rate} Tokens\n\nВыбери пакет:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    _, _, amount, rate = callback.data.split("_")
    await callback.message.answer_invoice(title="Звезды", description=f"Обмен {amount} Stars", payload=f"stars_{amount}_{rate}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Stars", amount=int(amount))], start_parameter="buy")
    await callback.answer()

@user_router.message(F.text == "👑 Купить VIP")
async def buy_vip_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👑 VIP 1 день (5 ⭐)", callback_data="buy_vip_5_1"))
    builder.row(InlineKeyboardButton(text="👑 VIP 7 дней (30 ⭐)", callback_data="buy_vip_30_7"))
    builder.row(InlineKeyboardButton(text="👑 VIP 30 дней (100 ⭐)", callback_data="buy_vip_100_30"))
    await message.answer("👑 <b>ПОКУПКА VIP</b>\n\nВыбери срок:", reply_markup=builder.as_markup())

@user_router.callback_query(F.data.startswith("buy_vip_"))
async def process_buy_vip(callback: CallbackQuery):
    _, _, price, days = callback.data.split("_")
    await callback.message.answer_invoice(title=f"VIP {days} дн.", description="Активация VIP", payload=f"vip_{days}", provider_token="", currency="XTR", prices=[LabeledPrice(label="VIP", amount=int(price))], start_parameter="buy")
    await callback.answer()

@user_router.message(F.successful_payment)
async def success_payment(message: Message):
    payment = message.successful_payment
    user = get_user(message.from_user.id)
    
    if payment.invoice_payload.startswith("vip_"):
        days = int(payment.invoice_payload.split("_")[1])
        db_execute("UPDATE users SET role = 'vip' WHERE user_id = ?", (user[0],))
        update_balance(user[0], 10000 * days)
        
        # Рандомный VIP стикер
        try: await message.answer_sticker(random.choice(VIP_STICKERS))
        except: pass
        
        await message.answer(f"✅ <b>VIP АКТИВИРОВАН!</b>\nСрок: {days} дней.", reply_markup=get_main_menu())
        
    elif payment.invoice_payload.startswith("stars_"):
        parts = payment.invoice_payload.split("_")
        update_balance(user[0], int(parts[1]) * int(parts[2]))
        
        # Зеленая галочка (успех)
        try: await message.answer_sticker(STICKER_CHECK)
        except: pass
        
        await message.answer("✅ <b>ОПЛАТА УСПЕШНА!</b>", reply_markup=get_main_menu())

# --- ПОДДЕРЖКА (ТИКЕТЫ) ---
class SupportStates(StatesGroup):
    waiting_ticket = State()

@user_router.message(F.text == "🆘 Поддержка")
async def support_menu(message: Message):
    await message.answer("🆘 <b>ЦЕНТР ПОДДЕРЖКИ</b>", reply_markup=get_support_menu())

@user_router.message(F.text == "✍️ Написать Админу")
async def sup_ticket(message: Message, state: FSMContext):
    await message.answer("✍️ Опиши проблему одним сообщением.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(SupportStates.waiting_ticket)

@user_router.message(SupportStates.waiting_ticket)
async def process_ticket(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    db_execute("INSERT INTO tickets (user_id, text, date) VALUES (?, ?, ?)", (user[0], message.text, datetime.datetime.now().isoformat()))
    try: await bot.send_message(ADMIN_ID, f"🎫 <b>ТИКЕТ</b>\nОт: @{message.from_user.username}\n{message.text}")
    except: pass
    
    # Ящик / Конверт (тикет)
    try: await message.answer_sticker(STICKER_TICKET)
    except: pass
    
    await message.answer("✅ Тикет отправлен.", reply_markup=get_main_menu())
    await state.clear()

# ==============================================================================
# ЧАСТЬ 3: ИГРЫ В ЧАТЕ, КЛАНЫ, НЕЙРО-АДМИН И ЗАПУСК
# ==============================================================================

# --- БАЛАНС И ПЕРЕВОД ---
@group_router.message(F.text.lower().in_(["б", "баланс"]))
async def cmd_balance_group(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    user = get_user(message.from_user.id)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    text = f"💰 <b>Баланс</b> {name}:\n💵 <b>{format_money(user[3])}</b>"
    await message.reply(text)

@group_router.message(F.text.regexp(r"(?i)^перевод\s+(\d+)$"))
async def cmd_transfer_group(message: Message):
    if message.chat.type not in ["group", "supergroup"]: return
    if not message.reply_to_message: return await message.reply("❌ Ответь (Reply) на сообщение того, кому переводишь!")
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id: return await message.reply("❌ Себе нельзя!")
    try: amount = int(message.text.split()[1])
    except: return await message.reply("❌ Введи число!")
    sender = get_user(message.from_user.id)
    if sender[3] < amount: return await message.reply("❌ Мало средств!")
    
    update_balance(sender[0], -amount)
    update_balance(target_id, amount)
    try: await message.answer_sticker(STICKER_TRANSFER)
    except: pass
    await message.reply(f"✅ <b>Перевод выполнен!</b>\n\n👤 От: {message.from_user.first_name}\n👤 Кому: {message.reply_to_message.from_user.first_name}\n💰 Сумма: <b>{format_money(amount)}</b>")

# --- СТИКЕРНЫЕ ИГРЫ ---
@group_router.message(F.text.regexp(r"(?i)^(кости|дартс|баскет|футбол|боулинг|слот)\s+(\d+)$"))
async def play_dice_group(message: Message):
    parts = message.text.lower().split()
    game, amount = parts[0], int(parts[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    emoji = {"кости": "🎲", "дартс": "🎯", "баскет": "🏀", "футбол": "⚽", "боулинг": "🎳", "слот": "🎰"}[game]
    msg = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(3.5)
    val = msg.dice.value
    win = False
    if game in ["кости", "дартс"] and val >= 4: win = True
    elif game == "баскет" and val >= 3: win = True
    elif game == "футбол" and val >= 4: win = True
    elif game == "боулинг" and val == 6: win = True
    elif game == "слот" and val in [1, 22, 43, 64]: win = True
    if win:
        update_balance(user[0], amount * 2)
        try: await message.answer_sticker(STICKER_CHECK)
        except: pass
        await message.reply(f"🎉 <b>ПОБЕДА!</b>\nВыпало: {val}\nВыигрыш: <b>{format_money(amount * 2)}</b>")
    else:
        try: await message.answer_sticker(STICKER_CROSS)
        except: pass
        await message.reply(f"😢 <b>Проигрыш.</b>\nВыпало: {val}")

# --- УМНАЯ РУЛЕТКА ---
active_roulette = {}
@group_router.message(F.text.regexp(r"(?i)^(к|ч|з|красное|черное|зеро|чет|нечет|\d+-\d+|\d+)\s+(\d+)$"))
async def bet_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette: active_roulette[chat_id] = {"status": "waiting", "bets": []}
    if active_roulette[chat_id]["status"] != "waiting": return await message.reply("⏳ Идет раунд.")
    
    parts = message.text.lower().split()
    bet, amount = parts[0], int(parts[1])
    if amount < 100: return await message.reply("❌ Минимальная ставка 100!")
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    
    update_balance(user[0], -amount)
    active_roulette[chat_id]["bets"].append({"uid": user[0], "name": message.from_user.first_name, "bet": bet, "amount": amount})
    await message.reply(f"✅ <b>Ставка принята:</b> {message.from_user.first_name}\n🎯 На: {bet.upper()}\n💰 Сумма: {format_money(amount)}")

@group_router.message(F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    if chat_id not in active_roulette or not active_roulette[chat_id]["bets"]: return
    active_roulette[chat_id]["status"] = "playing"
    
    # ТА САМАЯ ГИФКА
    try: msg = await message.answer_animation(animation=FSInputFile("assets/roulette.gif"), caption="🎡 <i>Рулетка крутится...</i>")
    except: msg = await message.answer("🎡 <i>Рулетка крутится...</i>")
    await asyncio.sleep(3)
    
    result_num = random.randint(0, 36)
    reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "з" if result_num == 0 else "к" if result_num in reds else "ч"
    res_name = {"к": "Красное 🔴", "ч": "Черное ⚫", "з": "Зеро 🟢"}[color]
    
    text = f"🎯 Выпало: <b>{result_num} {res_name}</b>\n\n"
    winners = []
    for b in active_roulette[chat_id]["bets"]:
        win = False
        if b['bet'] in [color, "красное" if color=="к" else "черное" if color=="ч" else "зеро"]: win = True
        elif b['bet'] == "чет" and result_num % 2 == 0 and result_num != 0: win = True
        elif b['bet'] == "нечет" and result_num % 2 != 0: win = True
        elif "-" in b['bet']:
            start, end = map(int, b['bet'].split("-"))
            if start <= result_num <= end: win = True
        elif b['bet'].isdigit():
            if int(b['bet']) == result_num: win = True
            
        if win:
            if b['bet'].isdigit(): mult = 36
            elif "-" in b['bet']: mult = 2.5
            else: mult = 2
            prize = int(b['amount'] * mult)
            update_balance(b['uid'], prize)
            winners.append(f"👤 <b>{b['name']}</b> выиграл {format_money(prize)}")
            
    text += "\n".join(winners) if winners else "😢 Победителей нет."
    try: await msg.edit_caption(caption=text)
    except: await msg.edit_text(text)
    active_roulette[chat_id] = {"status": "waiting", "bets": []}

# --- МИНЫ ---
active_mines = {}
@group_router.message(F.text.regexp(r"(?i)^мины\s+(\d+)$"))
async def play_mines(message: Message):
    amount = int(message.text.split()[1])
    user = get_user(message.from_user.id)
    if user[3] < amount: return await message.reply("❌ Мало средств.")
    update_balance(user[0], -amount)
    game_key = f"{message.chat.id}_{message.from_user.id}"
    mines = random.sample(range(25), 5)
    active_mines[game_key] = {"uid": user[0], "bet": amount, "mines": mines, "opened": []}
    builder = InlineKeyboardBuilder()
    for i in range(25): builder.button(text="⬜", callback_data=f"m_{game_key}_{i}")
    builder.adjust(5, 5, 5, 5, 5)
    await message.reply(f"💣 <b>МИНЫ</b>\nСтавка: {format_money(amount)}", reply_markup=builder.as_markup())

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
        await callback.message.edit_text(f"💥 <b>БУМ!</b> Проигрыш {format_money(game['bet'])}.", reply_markup=builder.as_markup())
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
    update_balance(game["uid"], win)
    await callback.message.edit_text(f"💰 <b>Забрали!</b>\nПриз: {format_money(win)}")
    del active_mines[game_key]
    await callback.answer("Зачислено!")

@group_router.callback_query(F.data == "m_ign")
async def ign_mine(callback: CallbackQuery): await callback.answer("Недоступно.")

# --- КЛАНЫ ---
@user_router.message(F.text == "🛡 Клан")
async def clan_menu(message: Message):
    user = get_user(message.from_user.id)
    builder = ReplyKeyboardBuilder()
    text = "🛡 <b>КЛАНОВАЯ СИСТЕМА</b>\n\n<i>Кланы — это объединения игроков. Качай уровень и получай бонусы!</i>\n\n"
    if not user[12]:
        builder.row(KeyboardButton(text="➕ Создать клан (100к)"), KeyboardButton(text="🏆 Топ кланов"))
        builder.row(KeyboardButton(text="🤝 Вступить в клан"))
        text += "Ты пока не в клане."
    else:
        clan = db_execute("SELECT name, treasury, owner_id, COALESCE(join_fee, 5000), COALESCE(level, 1) FROM clans WHERE id = ?", (user[12],), fetchone=True)
        builder.row(KeyboardButton(text="💰 Внести в казну"), KeyboardButton(text="🏆 Топ кланов"))
        builder.row(KeyboardButton(text="📜 Мой клан"), KeyboardButton(text="🏅 Топ меценатов"))
        if clan[2] == user[0]:
            builder.row(KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📈 Прокачать клан"))
            builder.row(KeyboardButton(text="💵 Собрать налог"), KeyboardButton(text="🥾 Кикнуть игрока"))
            role = "👑 Владелец"
        else:
            builder.row(KeyboardButton(text="🚪 Выйти из клана"))
            role = "🛡 Рядовой"
        progress = int((clan[1] / 1000000) * 10)
        progress = min(progress, 10)
        bar = "🟩" * progress + "⬜️" * (10 - progress)
        text += (
            f"<b>Твой клан:</b> {clan[0]}\n"
            f"<b>Уровень:</b> {clan[4]} / 5\n"
            f"<b>Роль:</b> {role}\n"
            f"<b>Казна:</b> {format_money(clan[1])}\n"
            f"[{bar}]\n"
            f"<b>Награда за вход:</b> {format_money(clan[3])}"
        )
    builder.row(KeyboardButton(text="⬅️ В Игры"))
    await message.answer(text, reply_markup=builder.as_markup(resize_keyboard=True))

# --- НЕЙРО-АДМИН ---
@admin_router.message(F.text.startswith("@"))
async def neuro_admin(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2: return
    cmd = args[0].lower()
    def find_user(t):
        t = t.replace("@", "")
        return db_execute("SELECT user_id FROM users WHERE user_id = ?", (int(t),), fetchone=True) if t.isdigit() else db_execute("SELECT user_id FROM users WHERE username = ?", (t,), fetchone=True)

    if cmd == "@бан":
        u = find_user(args[1])
        if u:
            db_execute("UPDATE users SET role = 'banned' WHERE user_id = ?", (u[0],))
            await message.reply(f"🚫 Игрок {args[1]} забанен.")
    elif cmd == "@анбан":
        u = find_user(args[1])
        if u:
            db_execute("UPDATE users SET role = 'user' WHERE user_id = ?", (u[0],))
            await message.reply(f"✅ Игрок {args[1]} разбанен.")
    elif cmd == "@выдать" and len(args) >= 3:
        u = find_user(args[1])
        if u:
            try:
                amount = int(args[2].lower().replace("к", "000").replace("кк", "000000"))
                update_balance(u[0], amount)
                await message.reply(f"✅ Выдано {format_money(amount)} игроку {args[1]}.")
            except: await message.reply("❌ Ошибка в сумме.")
    elif cmd == "@забрать" and len(args) >= 3:
        u = find_user(args[1])
        if u:
            try:
                amount = int(args[2].lower().replace("к", "000").replace("кк", "000000"))
                update_balance(u[0], -amount)
                await message.reply(f"✅ Забрано {format_money(amount)} у {args[1]}.")
            except: await message.reply("❌ Ошибка в сумме.")
    elif cmd == "@дроп" and len(args) >= 2:
        try:
            amount = int(args[1].lower().replace("к", "000"))
            builder = InlineKeyboardBuilder().button(text="💰 СХВАТИТЬ", callback_data=f"manual_drop_{amount}")
            await bot.send_message(CHAT_ID, f"🚨 <b>ДРОП!</b> Кто первый нажмет — заберет {format_money(amount)}!", reply_markup=builder.as_markup())
            await message.answer("✅ Дроп запущен.")
        except: pass

@group_router.callback_query(F.data.startswith("manual_drop_"))
async def claim_manual_drop(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    user = get_user(callback.from_user.id)
    update_balance(user[0], amount)
    try: await callback.message.answer_sticker(STICKER_MONEY)
    except: pass
    await callback.message.edit_text(f"💰 Мешок забрал <b>{callback.from_user.first_name}</b>! Он получил {format_money(amount)}!")
    await callback.answer("Ты забрал куш!", show_alert=True)

async def auto_drop():
    amount = random.choice([10000, 25000, 50000])
    builder = InlineKeyboardBuilder().button(text="💰 СХВАТИТЬ", callback_data=f"autodrop_{amount}")
    try: await bot.send_message(CHAT_ID, f"🚨 <b>ЗОЛОТАЯ ЛИХОРАДКА!</b> 🚨\n\nКто первый нажмет — заберет {format_money(amount)}!", reply_markup=builder.as_markup())
    except: pass

@group_router.callback_query(F.data.startswith("autodrop_"))
async def claim_auto_drop(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    user = get_user(callback.from_user.id)
    update_balance(user[0], amount)
    try: await callback.message.answer_sticker(STICKER_MONEY)
    except: pass
    await callback.message.edit_text(f"💰 Мешок забрал <b>{callback.from_user.first_name}</b>! Он получил {format_money(amount)}!")
    await callback.answer("Ты забрал куш!", show_alert=True)

# --- ЗАПУСК ---
async def main():
    init_db()
    scheduler.add_job(auto_drop, "interval", hours=2)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass