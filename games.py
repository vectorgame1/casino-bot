# games.py — v61 (ИГРЫ)
import asyncio, random, time
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем из базы и утилит
from database import get_balance, set_balance, get_top, log_game, get_conn, release_conn, is_banned, get_user_id_by_username
from utils import fmt_num
from keyboards import bet_actions_inline
from config import ADMIN_ID, TZ_MINSK

games_router = Router()

# Глобальные хранилища для игр
active_bets = {}
is_spinning = {}
bj_games = {}
active_duels = {}

RED = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_color(num):
    if num == 0: return "🟢"
    return "🔴" if num in RED else "⚫"

async def delete_message_later(message: Message, delay: int = 150):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

class GamesStates(StatesGroup):
    mines_game = State()

# ============================================================
# 1. БАЛАНС, ТОПЫ, ПЕРЕВОДЫ
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip().in_({"б", "баланс", "b", "balance"}))
async def group_bal(message: Message):
    uid = message.from_user.id
    try:
        bal = get_balance(uid)
        if isinstance(bal, (tuple, list)): bal = bal[0]
        if bal is None: bal = 0
    except:
        bal = 0
    msg = await message.reply(f"💳 <b>БАЛАНС</b>\n👤 @{message.from_user.username or 'user'}\n💰 {fmt_num(bal)} Tokens")
    asyncio.create_task(delete_message_later(msg, 60))

@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().strip() == "топ")
async def top_balance(message: Message):
    try:
        top = get_top(10)
        if not top: return await message.reply("🏆 Топ пуст.")
        txt = "🏆 <b>ТОП-10 БОГАЧЕЙ</b>\n\n"
        for i, row in enumerate(top, 1):
            name = row[0] if isinstance(row, (list, tuple)) else row
            bal = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0
            txt += f"{i}. @{name} — <b>{fmt_num(bal)}</b>\n"
        msg = await message.reply(txt)
        asyncio.create_task(delete_message_later(msg, 120))
    except Exception as e:
        await message.reply(f"❌ Ошибка БД: {e}")

@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^п\s+(\d+)\s+(\d+)$"))
async def transfer_by_id(message: Message):
    parts = message.text.split()
    uid = message.from_user.id
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except: return
    if amount < 10: return await message.reply("❌ Мин. 10.")
    if get_balance(uid) < amount: return await message.reply("❌ Мало.")
    
    # Комиссия 0.1%
    commission = max(1, int(amount * 0.001))
    final_amount = amount - commission
    
    set_balance(uid, -amount)
    set_balance(target_id, final_amount)
    await message.reply(f"💸 <b>ПЕРЕВОД</b>\n👤 От: @{message.from_user.username or 'user'}\n🎯 Кому: <code>{target_id}</code>\n💰 Сумма: {fmt_num(final_amount)} (комиссия: {fmt_num(commission)})")

# ============================================================
# 2. РУЛЕТКА
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(к|ч|з|чет|чёт|нечет|нечёт|r|b|g)\s+(\d+)$"))
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.regexp(r"(?i)^(\d+)\s+(к|ч|з|чет|чёт|нечет|нечёт|r|b|g)$"))
async def place_color_bet(message: Message):
    uid = message.from_user.id
    chat_id = message.chat.id
    parts = message.text.lower().split()
    word, num = None, None
    for p in parts:
        if p.isdigit(): num = p
        elif p in ["к", "r", "ч", "b", "з", "g", "чет", "нечет", "чёт", "нечёт"]: word = p
    
    if not word or not num: return
    bet_type = {"к": "red", "r": "red", "ч": "black", "b": "black", "з": "green", "g": "green", "чет": "even", "нечет": "odd", "чёт": "even", "нечёт": "odd"}.get(word)
    try: bet = int(num)
    except: return
    
    if bet < 1: return await message.reply("❌ Мин. 1.")
    if get_balance(uid) < bet: return await message.reply("❌ Мало токенов.")
    
    set_balance(uid, -bet)
    if chat_id not in active_bets: active_bets[chat_id] = {"bets": [], "timer": None}
    active_bets[chat_id]["bets"].append({"user_id": uid, "username": message.from_user.username or "user", "type": bet_type, "bet": bet})
    
    names = {"red": "🔴 КРАСНОЕ", "black": "⚫ ЧЁРНОЕ", "green": "🟢 ЗЕРО", "even": "2️⃣ ЧЁТ", "odd": "1️⃣ НЕЧЁТ"}
    msg = await message.reply(f"🎰 <b>СТАВКА</b>\n@{message.from_user.username or 'user'} | {names[bet_type]} | {fmt_num(bet)}\n⚡️ Напиши <b>го</b>!", reply_markup=bet_actions_inline())
    asyncio.create_task(delete_message_later(msg, 120))

@games_router.callback_query(F.data.in_({"bet_repeat", "bet_double"}))
async def bet_actions_handler(call: CallbackQuery):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    if chat_id not in active_bets or not active_bets[chat_id]["bets"]:
        return await call.answer("Ставка устарела", show_alert=True)
    my_bets = [b for b in active_bets[chat_id]["bets"] if b["user_id"] == uid]
    if not my_bets: return await call.answer("Ты не делал ставку!", show_alert=True)
    
    for b in my_bets:
        if b.get("action") == call.data: return await call.answer("❌ Ты уже использовал это в раунде!", show_alert=True)
            
    last_bet = my_bets[-1]
    amount = last_bet["bet"]
    if call.data == "bet_double": amount *= 2
    if get_balance(uid) < amount: return await call.answer("❌ Недостаточно!", show_alert=True)
    
    set_balance(uid, -amount)
    active_bets[chat_id]["bets"].append({"user_id": uid, "username": call.from_user.username or "user", "type": last_bet["type"], "bet": amount, "action": call.data})
    try: await call.message.delete()
    except: pass
    await call.answer(f"✅ Ставка на {fmt_num(amount)} принята!")
    await call.message.reply(f"🎰 <b>{'УДВОЕНИЕ' if call.data == 'bet_double' else 'ПОВТОР'}</b>\n@{call.from_user.username or 'user'} | {fmt_num(amount)}")

@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "го")
async def start_roulette(message: Message):
    chat_id = message.chat.id
    uid = message.from_user.id
    if is_spinning.get(chat_id, False): return await message.reply("⏳ УЖЕ КРУТИТСЯ!")
    if chat_id not in active_bets or not active_bets[chat_id]["bets"]: return await message.reply("❌ Нет ставок.")
    if not any(b["user_id"] == uid for b in active_bets[chat_id]["bets"]): return await message.reply("❌ ТОЛЬКО ИГРОКИ СО СТАВКОЙ!")
    
    is_spinning[chat_id] = True
    bets = active_bets[chat_id]["bets"]
    total = sum(b["bet"] for b in bets)
    
    try: msg = await message.reply_animation(FSInputFile("roulette.gif"), caption=f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
    except: msg = await message.reply(f"🎡 КРУТИТСЯ...\n💰 {fmt_num(total)}")
    
    await asyncio.sleep(3)
    res = random.randint(0, 36)
    color = get_color(res)
    win, lose = [], []
    
    for b in bets:
        w = 0
        if b["type"] == "red" and res in RED: w = int(b["bet"] * 1.95)
        elif b["type"] == "black" and res in BLACK: w = int(b["bet"] * 1.95)
        elif b["type"] == "green" and res == 0: w = int(b["bet"] * 35)
        elif b["type"] == "even" and res != 0 and res % 2 == 0: w = int(b["bet"] * 1.95)
        elif b["type"] == "odd" and res % 2 != 0: w = int(b["bet"] * 1.95)
        
        if w > 0:
            set_balance(b["user_id"], w)
            win.append(f"🏆 @{b['username']} +{fmt_num(w)}")
        else:
            lose.append(f"💔 @{b['username']}")
            
    txt = f"🎡 <b>ВЫПАЛО: {color} {res}</b>\n"
    if win: txt += "🎉 <b>ПОБЕДИТЕЛИ:</b>\n" + "\n".join(win) + "\n\n"
    if lose: txt += "💔 <b>ПРОИГРАЛИ:</b>\n" + "\n".join(lose)
    
    try: await msg.edit_caption(caption=txt)
    except: await msg.edit_text(txt)
        
    conn = get_conn(); c = conn.cursor()
    try:
        c.execute("INSERT INTO group_logs (chat_id, detail) VALUES (%s, %s)", (chat_id, f"{color}{res}"))
        conn.commit()
    except: pass
    finally: c.close(); release_conn(conn)
        
    if chat_id in active_bets: active_bets[chat_id]["bets"] = []
    is_spinning[chat_id] = False
    asyncio.create_task(delete_message_later(msg, 120))

# ============================================================
# 3. ОСТАЛЬНЫЕ DICE-ИГРЫ (Кости, Баскет, Футбол и тд)
# ============================================================
async def play_dice_game(message: Message, game_name: str, emoji: str, win_cond, win_mult, lose_txt, win_txt):
    uid = message.from_user.id
    parts = message.text.lower().split()
    if len(parts) != 2: return
    try: bet = int(parts[1])
    except: return
    if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
    
    set_balance(uid, -bet)
    sent = await message.answer_dice(emoji=emoji)
    await asyncio.sleep(2.5)
    res = sent.dice.value
    
    if win_cond(res):
        win = int(bet * win_mult)
        set_balance(uid, win)
        try: log_game(uid, message.from_user.username or "user", game_name, bet, win, str(res))
        except: pass
        txt = win_txt.format(result=res, win=fmt_num(win))
    else:
        try: log_game(uid, message.from_user.username or "user", game_name, bet, 0, str(res))
        except: pass
        txt = lose_txt.format(result=res, bet=fmt_num(bet))
        
    msg = await message.reply(txt)
    asyncio.create_task(delete_message_later(msg, 120))

@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("кости ", "dice ")))
async def play_dice(message: Message): await play_dice_game(message, "кости", "🎲", lambda r: r >= 4, 1.95, "🎲 {result}\n😢 -{bet}", "🎲 {result}\n🎉 +{win}")
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("баскет ", "basket ")))
async def play_basket(message: Message): await play_dice_game(message, "баскет", "🏀", lambda r: r >= 3, 2, "🏀 {result}\n😢 -{bet}", "🏀 {result}\n🎉 +{win}")
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("футбол ", "football ")))
async def play_football(message: Message): await play_dice_game(message, "футбол", "⚽", lambda r: r >= 3, 2, "⚽ {result}\n😢 -{bet}", "⚽ {result}\n🎉 +{win}")
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("дартс ", "darts ")))
async def play_darts(message: Message): await play_dice_game(message, "дартс", "🎯", lambda r: r >= 3, 1.5, "🎯 {result}\n😢 -{bet}", "🎯 {result}\n🎉 +{win}")
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("слот ", "slots ")))
async def play_slots(message: Message): await play_dice_game(message, "слоты", "🎰", lambda r: r >= 32, 1.8, "🎰 {result}\n😢 -{bet}", "🎰 {result}\n🎉 +{win}")

# ============================================================
# 4. МОНЕТКА
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("монетка ", "coin ")))
async def play_coin(message: Message):
    uid = message.from_user.id
    parts = message.text.lower().split()
    if len(parts) < 3: return await message.reply("❌ <code>монетка 100 орел</code>")
    try: bet = int(parts[1])
    except: return
    choice = parts[2]
    if choice not in ["орел", "решка", "ребро"]: return await message.reply("❌ орел/решка/ребро.")
    if bet < 1 or get_balance(uid) < bet: return await message.reply("❌ Мало.")
    
    set_balance(uid, -bet)
    await asyncio.sleep(1)
    res = random.choices(["орел", "решка", "ребро"], weights=[49.5, 49.5, 1])[0]
    
    if res == "ребро" and choice == "ребро":
        win = int(bet * 10); set_balance(uid, win)
        txt = f"🪙 РЕБРО! ДЖЕКПОТ +{fmt_num(win)} (x10)"
    elif res == choice:
        win = int(bet * 2); set_balance(uid, win)
        txt = f"🪙 {res.upper()}! +{fmt_num(win)} (x2)"
    else:
        txt = f"🪙 {res.upper()}. -{fmt_num(bet)}"
        
    msg = await message.reply(txt)
    asyncio.create_task(delete_message_later(msg, 120))

# ============================================================
# 5. БЛЭКДЖЕК
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith(("бж ", "bj ")))
async def play_bj(message: Message):
    parts = message.text.lower().split()
    if len(parts) != 2: return
    try: bet = int(parts[1])
    except: return
    uid = message.from_user.id
    if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
    
    set_balance(uid, -bet)
    p1, p2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
    d1, d2 = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]), random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
    
    if d1 + d2 == 21 and p1 + p2 != 21:
        return await message.reply(f"🃏 <b>БЛЭКДЖЕК У ДИЛЕРА!</b>\nТвои: {p1+p2}, Дилер: 21\n😢 Ставка {fmt_num(bet)} сгорела.")
    if p1 + p2 == 21:
        win = int(bet * 2.5); set_balance(uid, win)
        return await message.reply(f"🃏 <b>БЛЭКДЖЕК!</b>\nТвои: 21\n🎉 Выигрыш: <b>+{fmt_num(win)}</b> (x2.5)")
        
    bj_games[uid] = {"bet": bet, "player": [p1, p2], "dealer": [d1, d2], "chat_id": message.chat.id}
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
        InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
    ]])
    await message.reply(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(bet)}\n\n👤 Твои карты: <b>{p1} + {p2} = {p1+p2}</b>\n🤖 Дилер: <b>{d1} + ?</b>", reply_markup=kb)

@games_router.callback_query(F.data.startswith("bj_hit_"))
async def bj_hit(call: CallbackQuery):
    uid = int(call.data.split("_")[2])
    if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
    game = bj_games.pop(uid, None)
    if not game: return await call.answer("Игра не найдена", show_alert=True)
    
    new_card = random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11])
    game["player"].append(new_card)
    player_sum = sum(game["player"])
    
    if player_sum > 21:
        await call.message.edit_text(f"🃏 <b>ПЕРЕБОР!</b>\nТы набрал {player_sum}. Ставка {fmt_num(game['bet'])} сгорела.")
        return await call.answer("Перебор!")
        
    bj_games[uid] = game
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🃏 Взять", callback_data=f"bj_hit_{uid}"),
        InlineKeyboardButton(text="🛑 Хватит", callback_data=f"bj_stand_{uid}")
    ]])
    await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n💰 Ставка: {fmt_num(game['bet'])}\n\n👤 Твои карты: <b>{' + '.join(map(str, game['player']))} = {player_sum}</b>\n🤖 Дилер: <b>{game['dealer'][0]} + ?</b>", reply_markup=kb)
    await call.answer(f"Выпала карта: {new_card}")

@games_router.callback_query(F.data.startswith("bj_stand_"))
async def bj_stand(call: CallbackQuery):
    uid = int(call.data.split("_")[2])
    if call.from_user.id != uid: return await call.answer("Это не твоя игра!", show_alert=True)
    game = bj_games.pop(uid, None)
    if not game: return await call.answer("Игра не найдена", show_alert=True)
    
    player_sum = sum(game["player"])
    dealer_sum = sum(game["dealer"])
    while dealer_sum < 17:
        game["dealer"].append(random.choice([2,3,4,5,6,7,8,9,10,10,10,10,11]))
        dealer_sum = sum(game["dealer"])
        
    if dealer_sum > 21 or player_sum > dealer_sum:
        win = int(game["bet"] * 1.8); set_balance(uid, win)
        result = f"🎉 <b>ТЫ ВЫИГРАЛ!</b>\nВыигрыш: <b>+{fmt_num(win)}</b>"
    elif player_sum == dealer_sum:
        set_balance(uid, game["bet"])
        result = f"🤝 <b>НИЧЬЯ!</b>\nСтавка возвращена."
    else:
        result = f"😢 <b>ТЫ ПРОИГРАЛ!</b>\nСтавка сгорела."
        
    await call.message.edit_text(f"🃏 <b>БЛЭКДЖЕК</b>\n\n👤 Твои карты: {player_sum}\n🤖 Дилер: {dealer_sum}\n\n{result}")
    await call.answer("Игра окончена!")

# ============================================================
# 6. МИНЫ
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("мины "))
async def play_mines_start(message: Message, state: FSMContext):
    parts = message.text.lower().split()
    if len(parts) != 2: return
    try: bet = int(parts[1])
    except: return
    uid = message.from_user.id
    if bet < 10 or get_balance(uid) < bet: return await message.reply("❌ Мин. 10 или мало средств.")
    
    set_balance(uid, -bet)
    mines = random.sample(list(range(25)), 3)
    await state.update_data(bet=bet, mines=mines, opened=[], mult=1.0)
    await state.set_state(GamesStates.mines_game)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬜", callback_data=f"mine_{r*5+c}") for c in range(5)] for r in range(5)])
    kb.inline_keyboard.append([InlineKeyboardButton(text="💰 ЗАБРАТЬ (x1.0)", callback_data="mine_cashout")])
    
    msg = await message.reply(f"💣 <b>МИНЫ</b>\n💰 Ставка: <b>{fmt_num(bet)}</b>\n💣 Мин: 3\n\nОткрывай клетки!", reply_markup=kb)
    
    async def auto_fail():
        await asyncio.sleep(300)
        data = await state.get_data()
        if data.get("bet"):
            await state.clear()
            try: await msg.edit_text(f"⏰ <b>ВРЕМЯ ВЫШЛО!</b>\n😢 Ставка <b>{fmt_num(data['bet'])}</b> сгорела.")
            except: pass
    asyncio.create_task(auto_fail())

@games_router.callback_query(F.data.startswith("mine_"))
async def mines_handler(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data or "bet" not in data: return await call.answer("Игра устарела.")
    bet, mines, opened, mult = data["bet"], data["mines"], data["opened"], data["mult"]
    
    if call.data == "mine_cashout":
        win = int(bet * mult); set_balance(call.from_user.id, win)
        await state.clear()
        await call.message.edit_text(f"💰 <b>ЗАБРАЛ!</b>\n💎 Выигрыш: <b>+{fmt_num(win)}</b>\n📈 x{mult:.2f}")
        return await call.answer("Зачислено!")
        
    idx = int(call.data.split("_")[1])
    if idx in opened: return await call.answer("Уже открыто!")
    
    if idx in mines:
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💣" if r*5+c in mines else ("💎" if r*5+c in opened else "⬜"), callback_data="none") for c in range(5)] for r in range(5)])
        await call.message.edit_text(f"💥 <b>БУМ!</b>\n😢 Ставка <b>{fmt_num(bet)}</b> сгорела.", reply_markup=kb)
        return await call.answer("БУМ!")
        
    opened.append(idx)
    mult = round(1.0 + (len(opened) * 0.15), 2)
    await state.update_data(opened=opened, mult=mult)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎" if r*5+c in opened else "⬜", callback_data=f"mine_{r*5+c}" if r*5+c not in opened else "none") for c in range(5)] for r in range(5)])
    kb.inline_keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ (x{mult:.2f})", callback_data="mine_cashout")])
    await call.message.edit_text(f"💣 <b>МИНЫ</b>\n💰 {fmt_num(bet)}\n📈 Выигрыш: <b>{fmt_num(int(bet * mult))}</b> (x{mult:.2f})\n\nОткрывай дальше!", reply_markup=kb)
    await call.answer("Безопасно!")

# ============================================================
# 7. ДУЭЛИ
# ============================================================
@games_router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("дуэль "))
async def play_duel(message: Message):
    if not message.reply_to_message: return await message.reply("⚔️ Ответь на сообщение соперника и напиши <code>дуэль 100</code>.")
    challenger = message.from_user
    opponent = message.reply_to_message.from_user
    if challenger.id == opponent.id or opponent.is_bot: return await message.reply("❌ Нельзя.")
    parts = message.text.lower().split()
    if len(parts) != 2: return await message.reply("❌ Формат: <code>дуэль 100</code>")
    try: bet = int(parts[1])
    except: return
    if bet < 10: return await message.reply("❌ Мин. 10.")
    if get_balance(challenger.id) < bet or get_balance(opponent.id) < bet: return await message.reply("❌ Мало средств.")
    
    set_balance(challenger.id, -bet)
    chat_id = message.chat.id
    duel_id = f"{chat_id}_{challenger.id}_{opponent.id}_{int(time.time())}"
    active_duels[duel_id] = {"challenger_id": challenger.id, "challenger_name": challenger.username or challenger.first_name, "opponent_id": opponent.id, "opponent_name": opponent.username or opponent.first_name, "bet": bet, "chat_id": chat_id, "created": time.time()}
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"duel_accept_{duel_id}")],[InlineKeyboardButton(text="❌ ОТКЛОНИТЬ", callback_data=f"duel_decline_{duel_id}")]])
    await message.reply(f"⚔️ <b>ВЫЗОВ!</b>\n👤 @{challenger.username or challenger.first_name} VS @{opponent.username or opponent.first_name}\n💰 {fmt_num(bet)}\n\n@{opponent.username or opponent.first_name}, жми кнопку!", reply_markup=kb)
    
    async def auto_expire():
        await asyncio.sleep(120)
        d = active_duels.pop(duel_id, None)
        if d:
            set_balance(d["challenger_id"], d["bet"])
            try: await message.reply(f"⏰ <b>ДУЭЛЬ ПРОТУХЛА</b>\n💰 {fmt_num(d['bet'])} возвращены @{d['challenger_name']}.")
            except: pass
    asyncio.create_task(auto_expire())

@games_router.callback_query(F.data.startswith("duel_accept_"))
async def duel_accept_handler(call: CallbackQuery):
    duel_id = call.data.replace("duel_accept_", "")
    duel = active_duels.get(duel_id)
    if not duel: return await call.answer("❌ Устарело.", show_alert=True)
    if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
    if get_balance(duel["opponent_id"]) < duel["bet"]: return await call.answer("❌ Мало средств.", show_alert=True)
    
    duel = active_duels.pop(duel_id, None)
    if not duel: return await call.answer("❌ Уже принята.", show_alert=True)
    set_balance(duel["opponent_id"], -duel["bet"])
    
    try: await call.message.edit_text(f"⚔️ <b>ДУЭЛЬ!</b>\n🔵 @{duel['challenger_name']}\n🔴 @{duel['opponent_name']}\n💰 {fmt_num(duel['bet'] * 2)}\n\n🎲 Бросаем...")
    except: pass
    await call.answer("Принято!")
    
    await asyncio.sleep(1.5)
    d1 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
    await asyncio.sleep(0.5)
    d2 = await call.bot.send_dice(chat_id=call.message.chat.id, emoji="🎲")
    await asyncio.sleep(3.5)
    
    v1, v2 = d1.dice.value, d2.dice.value
    if v1 == v2:
        set_balance(duel["challenger_id"], duel["bet"]); set_balance(duel["opponent_id"], duel["bet"])
        return await call.message.reply(f"🤝 <b>НИЧЬЯ!</b> ({v1} и {v2}). Ставки возвращены.")
        
    if v1 > v2: w_id, w_name, w_d, l_d = duel["challenger_id"], duel["challenger_name"], v1, v2
    else: w_id, w_name, w_d, l_d = duel["opponent_id"], duel["opponent_name"], v2, v1
    set_balance(w_id, duel["bet"] * 2)
    await call.message.reply(f"🏆 <b>ПОБЕДИТЕЛЬ</b>\n🥇 @{w_name} ({w_d})\n💔 ({l_d})\n💰 +{fmt_num(duel['bet'] * 2)}")

@games_router.callback_query(F.data.startswith("duel_decline_"))
async def duel_decline_handler(call: CallbackQuery):
    duel_id = call.data.replace("duel_decline_", "")
    duel = active_duels.get(duel_id)
    if not duel: return await call.answer("❌ Устарело.", show_alert=True)
    if call.from_user.id != duel["opponent_id"]: return await call.answer("❌ Не твой вызов.", show_alert=True)
    
    duel = active_duels.pop(duel_id, None)
    if not duel: return await call.answer("❌ Уже обработано.", show_alert=True)
    set_balance(duel["challenger_id"], duel["bet"])
    
    try: await call.message.edit_text(f"❌ <b>ОТКЛОНЕНО</b>\n@{call.from_user.username or call.from_user.first_name} отказался.\n💰 {fmt_num(duel['bet'])} возвращены.")
    except: pass
    await call.answer("Отклонено.")