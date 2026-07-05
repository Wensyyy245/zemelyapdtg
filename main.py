import asyncio
import random
import os
import sys
import uuid
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO)

# ========================= НАСТРОЙКИ МУЛЬТИБОТА И КАНАЛОВ =========================

MAIN_TOKENS = [
    "8971264936:AAGnz7N90o_T1_EUEa694KTZThdFWGFhqgI",
    "8749652033:AAGxEa4xA2BU9wEUUcntIH3MfEoRVBniiwQ",
]

ADMIN_IDS = [
    8603534638,  
    8570452473,  
    8502341995   
]

CHANNELS = [
    (-1004466816546, "Наш канал", "https://t.me/+ryYTkHSQG6VmNjUy"),
    ("@PavelGiftsPG", "Спонсор", "https://t.me/PavelGiftsPG"),
]

EVENT_CHANNEL_ID = -1004466816546  

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"
db = None

GLOBAL_BOTS_POOL = []

# ========================= СОСТОЯНИЯ (FSM) =========================

class AdminStates(StatesGroup):
    mailing_text = State()
    user_manage_id = State()    
    user_change_diamonds = State() 
    user_ban_time = State()     
    event_percent = State()    
    event_hours = State()      
    event_giveaway = State()   
    create_task_data = State()  

class PromoStates(StatesGroup):
    create_code = State()
    create_reward = State()
    create_uses = State()
    activate_code = State()

class CheckStates(StatesGroup):
    create_diamonds = State()
    create_uses = State()

class ShopStates(StatesGroup):
    custom_diamonds = State()  

# ========================= БАЗА ДАННЫХ =========================

async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    
    # 1. Создаем таблицу, если её не было
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT 'Пользователь',
            diamonds REAL DEFAULT 8.0,
            referred_by INTEGER DEFAULT NULL,
            is_referral_rewarded INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            banned_until INTEGER DEFAULT 0,
            premium INTEGER DEFAULT 0,
            x2_until TEXT DEFAULT NULL,
            keep_videos INTEGER DEFAULT 0
        )
    """)
    
    # 2. МИГРАЦИЯ: Добавляем колонку banned_until (для временного бана)
    try:
        await db.execute("ALTER TABLE users ADD COLUMN banned_until INTEGER DEFAULT 0")
        await db.commit()
        print("✅ Миграция: добавлена колонка banned_until")
    except aiosqlite.OperationalError:
        pass

    # 3. МИГРАЦИЯ: Добавляем колонку is_referral_rewarded (защита рефералов от абуза)
    try:
        await db.execute("ALTER TABLE users ADD COLUMN is_referral_rewarded INTEGER DEFAULT 0")
        await db.commit()
        print("✅ Миграция: добавлена колонка is_referral_rewarded")
    except aiosqlite.OperationalError:
        pass
        
    # Инициализация остальных таблиц
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_x2_until', 'NULL')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_discount_until', 'NULL')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_discount_percent', '30')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_x3_stars_until', 'NULL')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_free_view_until', 'NULL')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('global_lucky_hour_until', 'NULL')")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            file_id TEXT,
            message_id INTEGER,
            chat_id INTEGER,
            delete_at TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            creator_id INTEGER,
            reward INTEGER,
            uses_left INTEGER
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_activations (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS diamond_checks (
            check_id TEXT PRIMARY KEY,
            creator_id INTEGER,
            diamonds_per_use INTEGER,
            uses_left INTEGER
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            channel_url TEXT,
            reward REAL,
            description TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_tasks (
            user_id INTEGER,
            task_id INTEGER,
            PRIMARY KEY (user_id, task_id)
        )
    """)
    await db.commit()

# ========================= ХЕЛПЕРЫ И ЗАЩИТА БАЛАНСА =========================

async def get_setting(key: str) -> str:
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else "NULL"

async def set_setting(key: str, value: str):
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await db.commit()

async def is_event_active(event_key: str) -> bool:
    val = await get_setting(event_key)
    if val == "NULL": return False
    try:
        return datetime.fromisoformat(val) > datetime.now()
    except Exception:
        return False

async def get_event_remaining_time(event_key: str) -> str:
    val = await get_setting(event_key)
    if val == "NULL": return ""
    try:
        end_time = datetime.fromisoformat(val)
        now = datetime.now()
        if end_time > now:
            diff = end_time - now
            hours, remainder = divmod(diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{diff.days * 24 + hours:02d}:{minutes:02d}"
    except Exception:
        pass
    return ""

async def send_to_all_bots(text: str):
    if not GLOBAL_BOTS_POOL: return
    async with db.execute("SELECT user_id FROM users") as cur: 
        users = await cur.fetchall()
        
    for (uid,) in users:
        bot_worker = random.choice(GLOBAL_BOTS_POOL)
        try:
            await bot_worker.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.04) 
        except Exception:
            try:
                await GLOBAL_BOTS_POOL[0].send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.04)
            except Exception: 
                pass

async def broadcast_event_start(title: str, description: str, duration_hours: int = None):
    time_str = f"⏳ <b>Длительность:</b> {duration_hours} час(ов)\n" if duration_hours else ""
    text = (
        f"🔔 <b>ГЛОБАЛЬНОЕ СОБЫТИЕ В БОТЕ!</b> 🔔\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🎉 <b>Ивент:</b> {title}\n"
        f"📢 {description}\n\n"
        f"{time_str}"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🚀 Заходи скорей и используй момент по максимуму!"
    )
    if GLOBAL_BOTS_POOL:
        try:
            await GLOBAL_BOTS_POOL[0].send_message(chat_id=EVENT_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Ошибка публикации в канал ивентов: {e}")
    await send_to_all_bots(text)

# ========================= МИДЛВАРЬ БАНА И АВТО-СБРОСА ПРЕМИУМА =========================

router = Router()

# Новый правильный класс мидлвари без ломающих декораторов
class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            async with db.execute("SELECT is_banned, banned_until, diamonds, premium FROM users WHERE user_id = ?", (user.id,)) as cur:
                row = await cur.fetchone()
                if row:
                    is_banned, banned_until, diamonds, premium = row
                    
                    if diamonds < 0 and premium > 0:
                        await db.execute("UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?", (user.id,))
                        await db.commit()
                        premium = 0
                    
                    current_ts = int(time.time())
                    if is_banned == 1 or (banned_until > 0 and banned_until > current_ts):
                        time_left_str = "навсегда" if banned_until == 0 else f"до {datetime.fromtimestamp(banned_until).strftime('%d.%m %H:%M')}"
                        if isinstance(event, CallbackQuery):
                            try: await event.answer(f"❌ Доступ заблокирован {time_left_str}!", show_alert=True)
                            except Exception: pass
                        elif isinstance(event, Message):
                            try: await event.answer(f"❌ <b>Ваш аккаунт заблокирован администратором {time_left_str}!</b>")
                            except Exception: pass
                        return
        return await handler(event, data)

async def check_subscription(user_id: int, bot: Bot) -> bool:
    for channel_data in CHANNELS:
        channel = channel_data[0] if isinstance(channel_data, (tuple, list)) else channel_data
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]: return False
        except Exception: return False
    return True

async def get_user_data(user_id: int, first_name: str = "Пользователь"):
    async with db.execute("SELECT diamonds, premium, x2_until, keep_videos, referred_by, is_referral_rewarded FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, first_name, diamonds) VALUES (?, ?, 8.0)", (user_id, first_name))
            await db.commit()
            return {"diamonds": 8.0, "premium": 0, "x2_until": None, "keep_videos": 0, "referred_by": None, "is_referral_rewarded": 0}
        
        # Защитная проверка: если баланс в минусе, на лету обнуляем привилегии
        diamonds_val = row[0]
        prem_val = row[1]
        keep_val = row[3]
        if diamonds_val < 0 and prem_val > 0:
            await db.execute("UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
            prem_val = 0
            keep_val = 0
            
        return {"diamonds": diamonds_val, "premium": prem_val, "x2_until": row[2], "keep_videos": keep_val, "referred_by": row[4], "is_referral_rewarded": row[5]}

async def add_diamonds(user_id: int, amount: float):
    await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
    await db.commit()

# ========================= КЛАВИАТУРЫ =========================

def main_menu(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📺 Смотреть видео (6 💎)", callback_data="watch")
    kb.button(text="📸 Посмотреть фото (3 💎)", callback_data="watch_photo")
    kb.button(text="🔥 Задания от спонсоров", callback_data="tasks_menu")
    kb.button(text="🛒 Магазин 💰", callback_data="shop_main")
    kb.button(text="🎟 Чеки / Промо", callback_data="promo_menu")
    kb.button(text="🏆 Таблица Лидеров", callback_data="leaderboard")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
    if user_id in ADMIN_IDS:
        kb.button(text="⚙️ Admin Panel", callback_data="admin_enter")
    kb.adjust(1)
    return kb.as_markup()

def shop_categories_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Купить Алмазы (за Звезды)", callback_data="cat_diamonds")
    kb.button(text="⚡ Способности (за Алмазы)", callback_data="cat_abilities")
    kb.button(text="👑 Премиум Статусы (за Алмазы)", callback_data="cat_premium")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_diamonds_kb(discount_pct: int = 0, timer: str = ""):
    kb = InlineKeyboardBuilder()
    prices = [50, 120, 200]
    final_prices = [int(p * (1 - discount_pct / 100)) if discount_pct > 0 else p for p in prices]
    timer_str = f" ({timer})" if timer else ""
    text1 = f"🎁 100 💎 — <s>{prices[0]}</s> -> {final_prices[0]} ⭐️" if discount_pct > 0 else f"🎁 100 алмазов — {prices[0]} ⭐️"
    text2 = f"🎁 250 💎 — <s>{prices[1]}</s> -> {final_prices[1]} ⭐️" if discount_pct > 0 else f"🎁 250 алмазов — {prices[1]} ⭐️"
    text3 = f"🎁 500 💎 — <s>{prices[2]}</s> -> {final_prices[2]} ⭐️" if discount_pct > 0 else f"🎁 500 алмазов — {prices[2]} ⭐️"
    kb.button(text=text1 + timer_str, callback_data="stars_100")
    kb.button(text=text2 + timer_str, callback_data="stars_250")
    kb.button(text=text3 + timer_str, callback_data="stars_500")
    kb.button(text="✍️ Ввести свое количество алмазов", callback_data="stars_custom")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_abilities_kb(discount_pct: int = 0, timer: str = ""):
    p1, p2 = 50, 500
    f1 = int(p1 * (1 - discount_pct / 100))
    f2 = int(p2 * (1 - discount_pct / 100))
    timer_str = f" ({timer})" if timer else ""
    kb = InlineKeyboardBuilder()
    text1 = f"🚀 х2 Рефералы (24ч) — <s>{p1}</s> -> {f1} 💎" if discount_pct > 0 else f"🚀 х2 от Рефералов (24ч) — {p1} 💎"
    text2 = f"♾ Видео навсегда — <s>{p2}</s> -> {f2} 💎" if discount_pct > 0 else f"♾ Видео навсегда — {p2} 💎"
    kb.button(text=text1 + timer_str, callback_data="buy_boost_x2")
    kb.button(text=text2 + timer_str, callback_data="buy_keep_videos")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_premium_kb(discount_pct: int = 0, timer: str = ""):
    p1, p2 = 1500, 2000
    f1 = int(p1 * (1 - discount_pct / 100))
    f2 = int(p2 * (1 - discount_pct / 100))
    timer_str = f" ({timer})" if timer else ""
    kb = InlineKeyboardBuilder()
    text1 = f"🌟 Премиум — <s>{p1}</s> -> {f1} 💎" if discount_pct > 0 else f"🌟 Премиум (Все бесплатно) — {p1} 💎"
    text2 = f"🔥 Премиум+ — <s>{p2}</s> -> {f2} 💎" if discount_pct > 0 else f"🔥 Премиум+ (Архивы + Навсегда) — {p2} 💎"
    kb.button(text=text1 + timer_str, callback_data="buy_prem_normal")
    kb.button(text=text2 + timer_str, callback_data="buy_prem_plus")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="👤 Управление юзерами (💎/🚫)", callback_data="admin_manage_users")
    kb.button(text="🎫 Активные промокоды", callback_data="admin_active_promos")
    kb.button(text="➕ Создать Задание (Оффер)", callback_data="admin_add_task")
    kb.button(text="📢 Рассылка текста", callback_data="admin_mail")
    kb.button(text="🔥 Управление ИВЕНТАМИ", callback_data="admin_events_panel")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_events_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Запустить х2 Рефералы", callback_data="ev_setup_x2")
    kb.button(text="📉 Настроить Скидки %", callback_data="ev_setup_discount")
    kb.button(text="🎁 Сделать Раздачу Алмазов всем", callback_data="ev_setup_giveaway")
    kb.button(text="⚡️ Запустить х3 Алмазы (Stars)", callback_data="ev_setup_x3_stars")
    kb.button(text="🆓 Запустить Бесплатный Просмотр", callback_data="ev_setup_free_view")
    kb.button(text="🍀 Запустить Счастливый Час (+2 💎)", callback_data="ev_setup_lucky_hour")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    return kb.as_markup()

# ========================= ХЕНДЛЕР СТАРТА И РЕФЕРАЛОВ =========================

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name
    args = message.text.split()
    
    async with db.execute("SELECT referred_by, is_referral_rewarded FROM users WHERE user_id = ?", (user_id,)) as cur:
        existing = await cur.fetchone()
        
    is_new_user = (existing is None)
    
    if is_new_user and len(args) > 1:
        param = args[1]
        if param.startswith("check_"):
            if not await check_subscription(user_id, bot):
                await get_user_data(user_id, name)
                return await message.answer("⚠️ Чтобы забрать чек, сначала подпишитесь на наши каналы, а затем снова перейдите по ссылке!")
            await get_user_data(user_id, name)
        elif param.isdigit():
            referrer_id = int(param)
            if referrer_id != user_id:
                await db.execute(
                    "INSERT INTO users (user_id, first_name, diamonds, referred_by, is_referral_rewarded) VALUES (?, ?, 8.0, ?, 0)", 
                    (user_id, name, referrer_id)
                )
                await db.commit()
    
    udata = await get_user_data(user_id, name)
    
    if len(args) > 1 and args[1].startswith("check_"):
        check_id = args[1].replace("check_", "")
        if not await check_subscription(user_id, bot):
            return await message.answer("⚠️ Подпишитесь на каналы спонсоров и повторите переход для активации чека!")
            
        async with db.execute("SELECT creator_id, diamonds_per_use, uses_left FROM diamond_checks WHERE check_id = ?", (check_id,)) as cur:
            check_row = await cur.fetchone()
            
        if not check_row:
            return await message.answer("❌ Данный чек не найден или уже полностью активирован.")
            
        creator_id, diamonds, uses_left = check_row
        if creator_id == user_id:
            return await message.answer("❌ Вы не можете активировать свой собственный чек!")
            
        async with db.execute("SELECT 1 FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, f"check_{check_id}")) as cur:
            if await cur.fetchone():
                return await message.answer("❌ Вы уже активировали этот чек ранее!")
        
        await add_diamonds(user_id, float(diamonds))
        await db.execute("INSERT INTO promo_activations VALUES (?, ?)", (user_id, f"check_{check_id}"))
        
        if uses_left - 1 <= 0:
            await db.execute("DELETE FROM diamond_checks WHERE check_id = ?", (check_id,))
        else:
            await db.execute("UPDATE diamond_checks SET uses_left = uses_left - 1 WHERE check_id = ?", (check_id,))
        await db.commit()
        
        try: await bot.send_message(creator_id, f"💸 Ваш чек активирован! Пользователь {name} забрал {diamonds} 💎")
        except Exception: pass
            
        return await message.answer(f"🎉 <b>Чек успешно активирован!</b>\n\nВы получили: +<b>{diamonds}</b> 💎", reply_markup=main_menu(user_id))

    if not await check_subscription(user_id, bot):
        kb = InlineKeyboardBuilder()
        for channel_data in CHANNELS:
            if isinstance(channel_data, (tuple, list)) and len(channel_data) >= 3:
                _, ch_name, ch_url = channel_data
            else:
                ch_id = channel_data[0] if isinstance(channel_data, (tuple, list)) else channel_data
                ch_name = "Канал"
                ch_url = f"https://t.me/{str(ch_id).replace('@', '')}"
            kb.button(text=ch_name, url=ch_url)
        kb.button(text="✅ Я подписался", callback_data="check_sub")
        kb.adjust(1)
        return await message.answer("👋 Для работы бота подпишись на каналы спонсоров:", reply_markup=kb.as_markup())
        
    if udata["referred_by"] and udata["is_referral_rewarded"] == 0:
        ref_id = udata["referred_by"]
        async with db.execute("SELECT premium, x2_until FROM users WHERE user_id = ?", (ref_id,)) as cur:
            ref_info = await cur.fetchone()
            
        if ref_info:
            base_reward = 4.0
            if await is_event_active("global_x2_until"): base_reward = 8.0
            if ref_info[1] and datetime.fromisoformat(ref_info[1]) > datetime.now(): base_reward *= 2
            
            await add_diamonds(ref_id, base_reward)
            await db.execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            
            try: await bot.send_message(ref_id, f"🎉 Твой реферал {name} успешно выполнил условия подписки! Тебе начислено +{base_reward} 💎")
            except Exception: pass

    await message.answer(f"👋 Добро пожаловать! 💎\n\nНа балансе: <b>{udata['diamonds']}</b> алмазов", reply_markup=main_menu(user_id))

@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if await check_subscription(user_id, bot):
        udata = await get_user_data(user_id, callback.from_user.first_name)
        
        if udata["referred_by"] and udata["is_referral_rewarded"] == 0:
            ref_id = udata["referred_by"]
            async with db.execute("SELECT premium, x2_until FROM users WHERE user_id = ?", (ref_id,)) as cur:
                ref_info = await cur.fetchone()
            if ref_info:
                base_reward = 4.0
                if await is_event_active("global_x2_until"): base_reward = 8.0
                if ref_info[1] and datetime.fromisoformat(ref_info[1]) > datetime.now(): base_reward *= 2
                
                await add_diamonds(ref_id, base_reward)
                await db.execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                try: await bot.send_message(ref_id, f"🎉 Твой реферал {callback.from_user.first_name} подписался! Начислено +{base_reward} 💎")
                except Exception: pass

        await callback.message.edit_text("✅ Подписка подтверждена!", reply_markup=main_menu(user_id))
    else:
        await callback.answer("❌ Ты не подписался на все каналы!", show_alert=True)

# ========================= ДИНАМИЧЕСКИЕ ЗАДАНИЯ =========================

@router.callback_query(F.data == "tasks_menu")
async def tasks_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db.execute("""
        SELECT id, description, reward, channel_url FROM tasks 
        WHERE id NOT IN (SELECT task_id FROM user_tasks WHERE user_id = ?)
    """, (user_id,)) as cur:
        available_tasks = await cur.fetchall()
        
    if not available_tasks:
        return await callback.message.edit_text("🎉 Вы выполнили все доступные задания! Приходите позже.", reply_markup=InlineKeyboardBuilder().button(text="◀️ Меню", callback_data="back_main").as_markup())
        
    text = "📋 <b>Доступные задания от спонсоров:</b>\n\nПодписывайтесь на каналы и получайте алмазы!\n\n"
    kb = InlineKeyboardBuilder()
    for tid, desc, reward, url in available_tasks:
        text += f"🔹 {desc} — <b>+{reward} 💎</b>\n"
        kb.button(text=f"Выполнить (+{reward} 💎)", callback_data=f"go_task_{tid}")
        
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("go_task_"))
async def go_task_page(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    async with db.execute("SELECT description, reward, channel_url FROM tasks WHERE id = ?", (task_id,)) as cur:
        task = await cur.fetchone()
        
    if not task:
        return await callback.answer("Задание не найдено.", show_alert=True)
        
    desc, reward, url = task
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Перейти в канал", url=url)
    kb.button(text="✅ Проверить подписку", callback_data=f"check_task_{task_id}")
    kb.button(text="◀️ К списку заданий", callback_data="tasks_menu")
    kb.adjust(1)
    
    await callback.message.edit_text(f"🚀 <b>Выполнение задания:</b>\n\nℹ️ {desc}\n💰 Награда: <b>{reward} 💎</b>", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("check_task_"))
async def check_task_status(callback: CallbackQuery, bot: Bot):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    async with db.execute("SELECT channel_id, reward FROM tasks WHERE id = ?", (task_id,)) as cur:
        task = await cur.fetchone()
    if not task: return await callback.answer("Ошибка задания.", show_alert=True)
    
    ch_id, reward = task
    try:
        tg_id = int(ch_id) if ch_id.replace("-","").isdigit() else ch_id
        member = await bot.get_chat_member(chat_id=tg_id, user_id=user_id)
        is_subbed = member.status in ["member", "administrator", "creator"]
    except Exception:
        is_subbed = False
        
    if is_subbed:
        async with db.execute("SELECT 1 FROM user_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id)) as cur:
            if await cur.fetchone(): return await callback.answer("Уже выполнено!", show_alert=True)
            
        await db.execute("INSERT INTO user_tasks VALUES (?, ?)", (user_id, task_id))
        await add_diamonds(user_id, float(reward))
        await db.commit()
        await callback.answer("🎉 Задание засчитано! Алмазы начислены.", show_alert=True)
        await tasks_menu(callback)
    else:
        await callback.answer("❌ Вы не подписались на канал спонсора или не открыли бота в нем!", show_alert=True)

# ========================= АНТИ-ДЮП ПРОСМОТР МЕДИАФАЙЛОВ =========================

@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    
    async with db.execute("SELECT diamonds, premium, keep_videos FROM users WHERE user_id = ?", (user_id,)) as cur:
        u_row = await cur.fetchone()
        
    if not u_row: return await callback.answer("Ошибка авторизации.", show_alert=True)
    current_diamonds, premium, keep_videos = u_row
    
    if current_diamonds < 0:
        return await callback.message.answer("❌ <b>Просмотр заблокирован! Ваш баланс отрицательный. Пополните счет для разблокировки функций бота.</b>")

    is_free = await is_event_active("global_free_view_until")
    is_lucky = await is_event_active("global_lucky_hour_until")
    
    if premium == 0 and not is_free and not is_lucky:
        if current_diamonds < 6: 
            return await callback.answer("❌ Недостаточно алмазов! Вам нужно минимум 6 💎", show_alert=True)
            
        await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ? AND diamonds >= 6", (user_id,))
        await db.commit()

    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV"))
    if not videos: return await callback.answer("Папка media пуста.", show_alert=True)
    is_forever = (keep_videos == 1 or premium == 2)
    
    cap = "📹 Ваше видео!" if is_forever else "📹 Видео удалится через 30 минут."
    if is_free: cap += " (🔥 По ивенту БЕСПЛАТНО)"
    if is_lucky:
        await add_diamonds(user_id, 2.0)
        cap += " (🍀 Счастливый час: +2 💎 за просмотр!)"
        
    msg = await bot.send_video(chat_id=user_id, video=FSInputFile(random.choice(videos)), caption=cap)
    if not is_forever:
        await db.execute("INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)", ("", msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()))
        await db.commit()
    await callback.answer()

@router.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    
    async with db.execute("SELECT diamonds, premium FROM users WHERE user_id = ?", (user_id,)) as cur:
        u_row = await cur.fetchone()
    if not u_row: return await callback.answer("Ошибка.", show_alert=True)
    current_diamonds, premium = u_row
    
    if current_diamonds < 0:
        return await callback.message.answer("❌ <b>Просмотр заблокирован! Баланс в минусе.</b>")

    is_free = await is_event_active("global_free_view_until")
    is_lucky = await is_event_active("global_lucky_hour_until")
    
    if premium == 0 and not is_free and not is_lucky:
        if current_diamonds < 3: 
            return await callback.answer("❌ Недостаточно алмазов! Требуется 3 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ? AND diamonds >= 3", (user_id,))
        await db.commit()
        
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("Папка photo пуста.", show_alert=True)
    
    if is_lucky: await add_diamonds(user_id, 2.0)
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)), caption="🍀 Счастливый час: +2 💎!" if is_lucky else None)
    await callback.answer()

# ========================= АНТИ-ДЮП ПРОМОКОДЫ И ЧЕКИ =========================

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.message.answer("❌ <b>Доступ к чекам и промокодам заблокирован, пока ваш баланс отрицательный!</b>")

    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Активировать промокод", callback_data="promo_activate")
    kb.button(text="➕ Создать промокод", callback_data="promo_create")
    kb.button(text="🧾 Создать чек", callback_data="check_create")
    kb.button(text="◀️ Назад в главное меню", callback_data="back_main")
    kb.adjust(1)
    await callback.message.edit_text("🎟 <b>Раздел Чеков и Промокодов</b>\n\nЗдесь вы можете активировать промокод или упаковать свои алмазы в чеки!", reply_markup=kb.as_markup())

@router.callback_query(F.data == "promo_activate")
async def promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Введите промокод:")
    await state.set_state(PromoStates.activate_code)

@router.message(PromoStates.activate_code)
async def process_promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    await state.clear()
    
    async with db.execute("SELECT creator_id, reward, uses_left FROM promo_codes WHERE code = ?", (code,)) as cur: 
        row = await cur.fetchone()
    if not row: return await message.answer("❌ Промокод не найден.")
        
    cid, reward, left = row
    if left <= 0: return await message.answer("❌ Промокод закончился.")
    if cid == user_id: return await message.answer("❌ Вы не можете активировать собственный промокод.")
    
    async with db.execute("SELECT 1 FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, code)) as cur:
        if await cur.fetchone(): return await message.answer("❌ Вы уже активировали этот промокод ранее!")
            
    await db.execute("INSERT INTO promo_activations VALUES (?, ?)", (user_id, code))
    if left - 1 == 0: await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else: await db.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
        
    await add_diamonds(user_id, float(reward))
    await db.commit()
    await message.answer(f"🎉 <b>Промокод успешно активирован!</b>\nНа ваш баланс зачислено: +<b>{reward}</b> 💎")

@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.answer("❌ Нельзя создавать промокоды с отрицательным балансом!", show_alert=True)

    await callback.message.edit_text("✨ Введите текст промокода (слово/код):")
    await state.set_state(PromoStates.create_code)

@router.message(PromoStates.create_code)
async def process_promo_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip().upper())
    await message.answer("💎 Введите награду в алмазах за 1 активацию (целое число):")
    await state.set_state(PromoStates.create_reward)

@router.message(PromoStates.create_reward)
async def process_promo_reward(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0: 
        await state.clear()
        return await message.answer("❌ Ошибка: награда должна быть целым положительным числом! Операция отменена.")
        
    await state.update_data(reward=int(text))
    await message.answer("👥 Кол-во людей, которые смогут его активировать:")
    await state.set_state(PromoStates.create_uses)

@router.message(PromoStates.create_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0: 
        await state.clear()
        return await message.answer("❌ Ошибка: количество использований должно быть положительным!")
        
    uses = int(text)
    data = await state.get_data()
    total = data['reward'] * uses
    
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
        bal = await cur.fetchone()
        
    if not bal or bal[0] < total or bal[0] < 0: 
        await state.clear()
        return await message.answer(f"❌ Недостаточно 💎 или баланс отрицательный! Требуется: {total} 💎")
        
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?", (total, message.from_user.id, total))
    await db.execute("INSERT INTO promo_codes VALUES (?, ?, ?, ?)", (data['code'], message.from_user.id, data['reward'], uses))
    await db.commit()
    await state.clear()
    
    beautiful_text = (
        f"🎟 <b>ПРОМОКОД УСПЕШНО СОЗДАН!</b> 🎟\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🏷 <b>Код:</b> <code>{data['code']}</code>\n"
        f"💎 <b>Ценность:</b> <code>{data['reward']}</code> алмазов каждому\n"
        f"👥 <b>Лимит активаций:</b> <code>{uses}</code> человек(а)\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👉 Нажмите на код выше, чтобы скопировать его."
    )
    await message.answer(beautiful_text, reply_markup=main_menu(message.from_user.id))

@router.callback_query(F.data == "check_create")
async def check_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.answer("❌ Нельзя создавать чеки с отрицательным балансом!", show_alert=True)

    await callback.message.edit_text("🧾 <b>Создание алмазного чека</b>\n\nВведите количество алмазов, которое получит <b>один</b> человек (целое положительное):")
    await state.set_state(CheckStates.create_diamonds)

@router.message(CheckStates.create_diamonds)
async def process_check_diamonds(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0: 
        await state.clear()
        return await message.answer("❌ Ошибка: номинал чека должен быть строго целым положительным числом!")
    await state.update_data(diamonds=int(text))
    await message.answer("👥 Сколько человек смогут забрать этот чек?")
    await state.set_state(CheckStates.create_uses)

@router.message(CheckStates.create_uses)
async def process_check_uses(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0: 
        await state.clear()
        return await message.answer("❌ Ошибка: число человек должно быть положительным!")
        
    uses = int(text)
    data = await state.get_data()
    diamonds_per_use = data['diamonds']
    total_needed = diamonds_per_use * uses
    
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
        bal = await cur.fetchone()
        
    if not bal or bal[0] < total_needed or bal[0] < 0:
        await state.clear()
        return await message.answer(f"❌ У вас недостаточно алмазов или баланс меньше нуля. Требуется: {total_needed} 💎")
        
    check_id = str(uuid.uuid4())[:8].upper()
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?", (total_needed, message.from_user.id, total_needed))
    await db.execute("INSERT INTO diamond_checks VALUES (?, ?, ?, ?)", (check_id, message.from_user.id, diamonds_per_use, uses))
    await db.commit()
    await state.clear()
    
    me = await message.bot.get_me()
    check_link = f"https://t.me/{me.username}?start=check_{check_id}"
    beautiful_check_text = (
        f"🧾 <b>ЧЕК НА АЛМАЗЫ ГОТОВ!</b> 🧾\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"💰 <b>Номинал:</b> <code>{diamonds_per_use}</code> 💎 на человека\n"
        f"👥 <b>Количество активаций:</b> <code>{uses}</code>\n"
        f"💎 <b>Всего выделено:</b> <code>{total_needed}</code> 💎\n\n"
        f"🔗 <b>Ссылка для активации чека:</b>\n"
        f"<code>{check_link}</code>\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📢 <i>Отправьте эту ссылку другу или в чат. Кто перейдет по ней, мгновенно заберет награду!</i>"
    )
    await message.answer(beautiful_check_text, reply_markup=main_menu(message.from_user.id))

# ========================= ТАБЛИЦА ЛИДЕРОВ (ТОП-10 С АЙДИ) =========================

@router.callback_query(F.data == "leaderboard")
async def leaderboard_menu(callback: CallbackQuery):
    async with db.execute("SELECT user_id, first_name, diamonds FROM users WHERE diamonds >= 0 ORDER BY diamonds DESC LIMIT 10") as cur: 
        rows = await cur.fetchall()
        
    if not rows:
        kb = InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main")
        return await callback.message.edit_text("🏆 <b>Список лидеров пуст.</b>", reply_markup=kb.as_markup())
        
    text = "🏆 <b>ТОП-10 ИГРОКОВ ПО АЛМАЗАМ</b> 🏆\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (uid, name, diamonds) in enumerate(rows, 1):
        place = medals.get(i, f"{i}.")
        # Вывод ника, ID кликабельным кодом и баланса
        text += f"{place} {name} <code>(ID: {uid})</code> — <b>{diamonds} 💎</b>\n"
        
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

# ========================= АДМИНИСТРАТИВНАЯ ПАНЕЛЬ И УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =========================

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id in ADMIN_IDS: 
        await callback.message.edit_text("🛠 <b>Административная Панель</b>:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("👤 <b>Улучшенная панель пользователей</b>\n\nВведите Telegram ID пользователя для управления его балансом и статусом блокировок:")
    await state.set_state(AdminStates.user_manage_id)

@router.message(AdminStates.user_manage_id)
async def process_user_search(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit(): return await message.answer("❌ ID должен состоять только из цифр:")
        
    uid = int(text)
    async with db.execute("SELECT first_name, diamonds, is_banned, banned_until FROM users WHERE user_id = ?", (uid,)) as cur:
        row = await cur.fetchone()
    
    if not row: return await message.answer("❌ Юзер не найден в БД бота.")
    await state.update_data(target_id=uid)
    
    ban_status = "❌ Нет"
    if row[2] == 1: ban_status = "⛔ Перманентно"
    elif row[3] > int(time.time()): ban_status = f"⏳ До {datetime.fromtimestamp(row[3]).strftime('%d.%m %H:%M')}"
        
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Изменить баланс алмазов", callback_data="adm_change_diamonds")
    kb.button(text="🚫 Заблокировать (Временный бан)", callback_data="adm_ban_time")
    kb.button(text="🔒 Забанить НАВСЕГДА", callback_data="adm_ban_forever")
    kb.button(text="🔓 Разблокировать", callback_data="adm_unban")
    kb.button(text="◀️ В админку", callback_data="admin_enter")
    kb.adjust(1)
    
    await message.answer(
        f"👤 <b>Пользователь:</b> {row[0]}\n"
        f"ID: <code>{uid}</code>\n"
        f"Баланс: <b>{row[1]}</b> 💎\n"
        f"Блокировка: <b>{ban_status}</b>",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "adm_change_diamonds")
async def adm_change_diamonds_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введите число алмазов (например, 50 или -30 для списания):")
    await state.set_state(AdminStates.user_change_diamonds)
    await callback.answer()

@router.message(AdminStates.user_change_diamonds)
async def process_user_change_diamonds(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    try: amount = float(message.text.strip())
    except ValueError: return await message.answer("❌ Введите число:")
    
    data = await state.get_data()
    uid = data.get("target_id")
    await state.clear()
    
    await add_diamonds(uid, amount)
    await message.answer(f"✅ Баланс успешно изменен на {amount} 💎.", reply_markup=admin_menu())

@router.callback_query(F.data == "adm_ban_time")
async def adm_ban_time_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⏱ Введите время блокировки в <b>МИНУТАХ</b> (например, 60 для 1 часа или 1440 для суток):")
    await state.set_state(AdminStates.user_ban_time)
    await callback.answer()

@router.message(AdminStates.user_ban_time)
async def process_user_ban_time(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.text.strip().isdigit(): return await message.answer("❌ Введите целое число минут:")
    
    minutes = int(message.text.strip())
    until_ts = int(time.time()) + (minutes * 60)
    
    data = await state.get_data()
    uid = data.get("target_id")
    await state.clear()
    
    await db.execute("UPDATE users SET is_banned = 0, banned_until = ? WHERE user_id = ?", (until_ts, uid))
    await db.commit()
    await message.answer(f"✅ Пользователь <code>{uid}</code> временно заблокирован на {minutes} мин.", reply_markup=admin_menu())

@router.callback_query(F.data == "adm_ban_forever")
async def adm_ban_forever(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_id")
    await state.clear()
    await db.execute("UPDATE users SET is_banned = 1, banned_until = 0 WHERE user_id = ?", (uid,))
    await db.commit()
    await callback.answer("⛔ Заблокирован навсегда!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())

@router.callback_query(F.data == "adm_unban")
async def adm_unban(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = data.get("target_id")
    await state.clear()
    await db.execute("UPDATE users SET is_banned = 0, banned_until = 0 WHERE user_id = ?", (uid,))
    await db.commit()
    await callback.answer("🔓 Полностью разблокирован!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())

# ========================= ПРОСМОТР И ОЧИСТКА ПРОМОКОДОВ (АДМИН) =========================

# ========================= ПРОСМОТР И ОЧИСТКА ПРОМОКОДОВ (АДМИН) =========================

@router.callback_query(F.data == "admin_active_promos")
async def admin_active_promos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: 
        return await callback.answer("❌ У вас нет прав администратора!", show_alert=True)
    
    # Мгновенно гасим анимацию загрузки кнопки в Telegram
    await callback.answer()
    
    try:
        async with db.execute("SELECT code, reward, uses_left, creator_id FROM promo_codes") as cur:
            promos = await cur.fetchall()
            
        if not promos:
            kb = InlineKeyboardBuilder()
            kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
            return await callback.message.edit_text(
                "🎫 <b>Активных промокодов нет.</b>\n\nБаза данных чиста от кодов.", 
                reply_markup=kb.as_markup(),
                parse_mode=ParseMode.HTML
            )
            
        text = "🎫 <b>Список активных промокодов:</b>\n\nНажмите на кнопку под сообщением, чтобы удалить промокод.\n\n"
        kb = InlineKeyboardBuilder()
        
        for code, reward, uses_left, creator in promos:
            text += f"▪️ Код: <code>{code}</code> | Награда: <b>{reward} 💎</b> | Осталось: <b>{uses_left} шт.</b> (ID: <code>{creator}</code>)\n"
            kb.button(text=f"❌ Удалить {code}", callback_data=f"adm_del_promo_{code}")
            
        kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
        kb.adjust(1)
        
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        
    except Exception as e:
        logging.error(f"Ошибка вывода промокодов: {e}")
        await callback.message.answer("⚠️ Ошибка при чтении списка промокодов из базы данных.")

@router.callback_query(F.data.startswith("adm_del_promo_"))
async def admin_delete_promo_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: 
        return await callback.answer("❌ У вас нет прав!", show_alert=True)
        
    promo_code = callback.data.replace("adm_del_promo_", "")
    
    try:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (promo_code,))
        await db.commit()
        
        # Показываем всплывающее уведомление об успешном удалении
        await callback.answer(f"✅ Промокод {promo_code} успешно удален!", show_alert=True)
        
        # Обновляем список промокодов на экране
        async with db.execute("SELECT code, reward, uses_left, creator_id FROM promo_codes") as cur:
            promos = await cur.fetchall()
            
        if not promos:
            kb = InlineKeyboardBuilder()
            kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
            return await callback.message.edit_text(
                "🎫 <b>Активных промокодов нет.</b>\n\nБаза данных чиста от кодов.", 
                reply_markup=kb.as_markup(),
                parse_mode=ParseMode.HTML
            )
            
        text = "🎫 <b>Список активных промокодов:</b>\n\nНажмите на кнопку под сообщением, чтобы удалить промокод.\n\n"
        kb = InlineKeyboardBuilder()
        
        for code, reward, uses_left, creator in promos:
            text += f"▪️ Код: <code>{code}</code> | Награда: <b>{reward} 💎</b> | Осталось: <b>{uses_left} шт.</b> (ID: <code>{creator}</code>)\n"
            kb.button(text=f"❌ Удалить {code}", callback_data=f"adm_del_promo_{code}")
            
        kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
        kb.adjust(1)
        
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        
    except Exception as e:
        logging.error(f"Ошибка при удалении промокода: {e}")
        await callback.answer("⚠️ Не удалось удалить промокод.", show_alert=True)

# ========================= ИНСТРУМЕНТ СОЗДАНИЯ ЗАДАНИЙ (АДМИН) =========================

@router.callback_query(F.data == "admin_add_task")
async def admin_add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text(
        "➕ <b>Инструмент создания рекламных заданий</b>\n\n"
        "Отправьте параметры строго через разделитель <code>|</code> в одну строчку:\n"
        "<code>ID_Канала|Ссылка_На_Канал|Награда_В_Алмазах|Описание_Задания</code>\n\n"
        "Пример формата:\n"
        "<code>-10022334455|https://t.me/pavel_blog|4.5|Подпишись на личный блог Павла</code>"
    )
    await state.set_state(AdminStates.create_task_data)

@router.message(AdminStates.create_task_data)
async def process_admin_create_task(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    try:
        parts = text.split("|")
        ch_id = parts[0].strip()
        ch_url = parts[1].strip()
        reward = float(parts[2].strip())
        description = parts[3].strip()
        
        await db.execute("INSERT INTO tasks (channel_id, channel_url, reward, description) VALUES (?, ?, ?, ?)", (ch_id, ch_url, reward, description))
        await db.commit()
        await state.clear()
        await message.answer("✅ <b>Задание создано!</b> Оно автоматически появилось в меню 'Задания от спонсоров'.", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ Ошибка парсинга строки. Проверьте разделители и формат! Лог: {e}")

# ========================= МАГАЗИН И ПЛАТЕЖИ СТАРС =========================

@router.callback_query(F.data == "shop_main")
async def shop_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    prem_status = "❌ Нет" if udata["premium"] == 0 else ("🌟 Premium" if udata["premium"] == 1 else "🔥 Premium+")
    keep_status = "✅ Да" if udata["keep_videos"] == 1 or udata["premium"] == 2 else "❌ Нет"
    
    boost_status = "❌ Нет"
    if udata["x2_until"] and datetime.fromisoformat(udata["x2_until"]) > datetime.now():
        boost_status = f"✅ Активен до {datetime.fromisoformat(udata['x2_until']).strftime('%H:%M %d.%m')}"
        
    is_disc = await is_event_active("global_discount_until")
    timer = await get_event_remaining_time("global_discount_until")
    disc_text = ""
    if is_disc:
        pct = await get_setting("global_discount_percent")
        disc_text = f"\n⚠️ <b>🔥 ДЕЙСТВУЕТ СКИДКА -{pct}% (Осталось: {timer})</b>"

    if await is_event_active("global_x3_stars_until"):
        t_x3 = await get_event_remaining_time("global_x3_stars_until")
        disc_text += f"\n⚠️ <b>⚡️ ИВЕНТ: Х3 АЛМАЗЫ ПРИ ПОКУПКЕ! ({t_x3})</b>"

    text = f"🛒 <b>Магазин категорий</b>{disc_text}\n\n💰 Баланс: <b>{udata['diamonds']}</b> 💎\n👑 Премиум: <b>{prem_status}</b>\n🚀 Буст х2: <b>{boost_status}</b>\n♾ Навсегда: <b>{keep_status}</b>"
    try: await callback.message.edit_text(text, reply_markup=shop_categories_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "cat_diamonds")
async def cat_diamonds(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("💎 <b>Пополнение алмазов (Telegram Stars)</b>\n\n<i>Курс: 1 алмаз = 0.5 звезд</i>", reply_markup=shop_diamonds_kb(discount_pct=pct, timer=timer))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "stars_custom")
async def stars_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✍️ Введите желаемое количество алмазов для покупки (минимум 10):")
    await state.set_state(ShopStates.custom_diamonds)

@router.message(ShopStates.custom_diamonds)
async def process_custom_diamonds(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) < 10:
        return await message.answer("❌ Введите корректное число алмазов (от 10 и выше):")
    
    diamonds = int(text)
    await state.clear()
    raw_stars = diamonds * 0.5
    stars_price = max(1, int(raw_stars + 0.999))
    
    if await is_event_active("global_discount_until"):
        pct = int(await get_setting("global_discount_percent"))
        stars_price = max(1, int(stars_price * (1 - pct / 100)))

    try:
        await message.answer_invoice(
            title=f"Покупка {diamonds} алмазов",
            description=f"Кастомное начисление {diamonds} алмазов на игровой баланс.",
            payload=f"buy_diamonds:{diamonds}",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=stars_price)]
        )
    except Exception:
        await message.answer("❌ Ошибка генерации счета Telegram Stars.")

@router.callback_query(F.data.startswith("stars_"))
async def buy_diamonds_stars(callback: CallbackQuery):
    rates = {"stars_100": (100, 50), "stars_250": (250, 120), "stars_500": (500, 200)}
    if callback.data in rates:
        diamonds, stars_price = rates[callback.data]
        if await is_event_active("global_discount_until"):
            pct = int(await get_setting("global_discount_percent"))
            stars_price = max(1, int(stars_price * (1 - pct / 100)))
        try:
            await callback.message.answer_invoice(
                title=f"Покупка {diamonds} алмазов",
                description=f"Начисление {diamonds} алмазов на баланс.",
                payload=f"buy_diamonds:{diamonds}",
                currency="XTR",
                prices=[LabeledPrice(label="Telegram Stars", amount=stars_price)]
            )
            await callback.answer()
        except Exception:
            await callback.answer("❌ Ошибка создания инвойса Stars.", show_alert=True)

@router.callback_query(F.data == "cat_abilities")
async def cat_abilities(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0: return await callback.answer("❌ У вас отрицательный баланс!", show_alert=True)

    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("⚡ <b>Магазин способностей</b>", reply_markup=shop_abilities_kb(discount_pct=pct, timer=timer))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 0: return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(50 * (1 - pct / 100))
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, x2_until = ? WHERE user_id = ? AND diamonds >= ?", (price, (datetime.now() + timedelta(hours=24)).isoformat(), user_id, price))
    await db.commit()
    await callback.answer("🚀 Буст х2 активирован на 24 часа!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 0: return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    if udata["keep_videos"] == 1 or udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(500 * (1 - pct / 100))
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, keep_videos = 1 WHERE user_id = ? AND diamonds >= ?", (price, user_id, price))
    await db.commit()
    await callback.answer("♾ Видео теперь сохраняются навсегда!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "cat_premium")
async def cat_premium(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0: return await callback.answer("❌ У вас отрицательный баланс!", show_alert=True)

    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("👑 <b>Премиум подписки</b>", reply_markup=shop_premium_kb(discount_pct=pct, timer=timer))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_prem_normal")
async def buy_prem_normal(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 0: return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    if udata["premium"] >= 1: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(1500 * (1 - pct / 100))
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, premium = 1 WHERE user_id = ? AND diamonds >= ?", (price, user_id, price))
    await db.commit()
    await callback.answer("👑 PREMIUM статус активирован!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_prem_plus")
async def buy_prem_plus(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 0: return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    if udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(2000 * (1 - pct / 100))
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, premium = 2 WHERE user_id = ? AND diamonds >= ?", (price, user_id, price))
    await db.commit()
    await callback.answer("🔥 PREMIUM+ статус активирован!", show_alert=True)
    await shop_main(callback)

# ========================= СТАНДАРТНЫЕ МЕНЮ =========================

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    udata = await get_user_data(callback.from_user.id)
    await callback.message.edit_text(f"💎 Баланс: <b>{udata['diamonds']}</b> алмазов", reply_markup=main_menu(callback.from_user.id))

@router.callback_query(F.data.in_({"referral", "support"}))
async def static_callbacks(callback: CallbackQuery, bot: Bot):
    if callback.data == "referral":
        me = await bot.get_me()
        await callback.message.edit_text(f"👥 Реф. ссылка:\n<code>https://t.me/{me.username}?start={callback.from_user.id}</code>\n\nПриглашение: +4 💎\n\n<i>Важно: Алмазы поступят на твой аккаунт только после подписки приглашенного на каналы спонсоров!</i>", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())
    elif callback.data == "support":
        await callback.message.edit_text("🛠 ТП: @твой_юзернейм", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())

# ========================= УПРАВЛЕНИЕ ИВЕНТАМИ И СТАТИСТИКА (АДМИН) =========================

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    async with db.execute("SELECT COUNT(*) FROM users") as cur: total_users = (await cur.fetchone())[0]
    
    x2_active = "✅ Активен" if await is_event_active("global_x2_until") else "❌ Выключен"
    is_disc = await is_event_active("global_discount_until")
    pct = await get_setting("global_discount_percent")
    disc_active = f"✅ Активен (-{pct}%)" if is_disc else "❌ Выключен"
    x3_stars = "✅ Активен" if await is_event_active("global_x3_stars_until") else "❌ Выключен"
    free_view = "✅ Активен" if await is_event_active("global_free_view_until") else "❌ Выключен"
    lucky_hour = "✅ Активен" if await is_event_active("global_lucky_hour_until") else "❌ Выключен"
    
    text = (
        f"📊 <b>Статистика Системы:</b>\n\n"
        f"👥 Пользователей в БД: <b>{total_users}</b>\n"
        f"🪞 Активных ботов в пуле: <b>{len(GLOBAL_BOTS_POOL)}</b>\n\n"
        f"🔥 <b>Текущие Ивенты:</b>\n"
        f"🚀 Глобальный х2 реф: {x2_active}\n"
        f"📉 Скидки в шопе: {disc_active}\n"
        f"⚡️ Х3 Пополнение (Stars): {x3_stars}\n"
        f"🆓 Бесплатные просмотры: {free_view}\n"
        f"🍀 Счастливый час (+2 💎): {lucky_hour}"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="admin_enter").as_markup())

@router.callback_query(F.data == "admin_events_panel")
async def admin_events_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🔥 <b>Управление Ивентами</b>\n\nВыберите тип ивента для настройки и запуска:", reply_markup=admin_events_kb())

@router.callback_query(F.data == "ev_setup_x2")
async def ev_setup_x2(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("⏳ <b>Ивент: х2 Рефералы</b>\n\nВведите время действия ивента в <b>ЧАСАХ</b>:")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="x2")

@router.callback_query(F.data == "ev_setup_x3_stars")
async def ev_setup_x3_stars(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("⚡️ <b>Ивент: Х3 К покупкам Stars</b>\n\nВведите время действия ивента в <b>ЧАСАХ</b>:")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="x3_stars")

@router.callback_query(F.data == "ev_setup_free_view")
async def ev_setup_free_view(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🆓 <b>Ивент: Бесплатный Просмотр Медиа</b>\n\nВведите время действия ивента в <b>ЧАСАХ</b>:")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="free_view")

@router.callback_query(F.data == "ev_setup_lucky_hour")
async def ev_setup_lucky_hour(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🍀 <b>Ивент: Счастливый Час</b>\n\nВведите время действия ивента в <b>ЧАСАХ</b>:")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="lucky_hour")

@router.callback_query(F.data == "ev_setup_discount")
async def ev_setup_discount(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("📉 <b>Ивент: Кастомные Скидки</b>\n\nШаг 1: Введите процент скидки (число от 1 до 99):")
    await state.set_state(AdminStates.event_percent)

@router.message(AdminStates.event_percent)
async def process_event_percent(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 99): return await message.answer("❌ Введите корректный процент (от 1 до 99):")
    await state.update_data(discount_pct=int(text))
    await message.answer("⏳ Шаг 2: Введите время действия скидок в <b>ЧАСАХ</b>:")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="discount")

@router.message(AdminStates.event_hours)
async def process_event_hours(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit(): return await message.answer("❌ Пожалуйста, введите целое число часов:")
        
    hours = int(text)
    data = await state.get_data()
    etype = data.get("event_type")
    await state.clear()
    until_time = (datetime.now() + timedelta(hours=hours)).isoformat()
    
    if etype == "x2":
        await set_setting("global_x2_until", until_time)
        await message.answer(f"✅ Глобальный ивент запущен!")
        asyncio.create_task(broadcast_event_start("🚀 ДВОЙНЫЕ НАГРАДЫ ЗА ДРУЗЕЙ (х2)", "С этого момента за каждого приглашенного реферала абсолютно все пользователи получают двойную выплату алмазов!", hours))
    elif etype == "discount":
        pct = data.get("discount_pct", 30)
        await set_setting("global_discount_percent", str(pct))
        await set_setting("global_discount_until", until_time)
        await message.answer(f"✅ Ивент Скидки -{pct}% успешно запущен!")
        asyncio.create_task(broadcast_event_start(f"📉 ШОК-СКИДКИ В МАГАЗИНЕ (-{pct}%)", f"Цены на способности, улучшения и покупку алмазов за Звезды снижены на {pct}%!", hours))
    elif etype == "x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await message.answer(f"✅ Ивент Х3 запущен!")
        asyncio.create_task(broadcast_event_start("⚡️ АЛМАЗНЫЙ ЛИВЕНЬ (Х3 К ПОКУПКАМ)", "Внимание! Любая покупка алмазов через Telegram Stars увеличивается в 3 раза!", hours))
    elif etype == "free_view":
        await set_setting("global_free_view_until", until_time)
        await message.answer(f"✅ Ивент Бесплатный Просмотр запущен!")
        asyncio.create_task(broadcast_event_start("🆓 АТТРАКЦИОН НЕВИДАННОЙ ЩЕДРОСТИ (0 💎)", "Администрация открыла бесплатный просмотр всех видео и фото для всех пользователей!", hours))
    elif etype == "lucky_hour":
        await set_setting("global_lucky_hour_until", until_time)
        await message.answer(f"✅ Ивент Счастливый Час запущен!")
        asyncio.create_task(broadcast_event_start("🍀 СЧАСТЛИВЫЙ ЧАС (+2 💎 ЗА АКТИВНОСТЬ)", "Невероятный бонус! Просматривайте медиа прямо сейчас и вместо списания алмазов получайте +2 💎 прямо на баланс!", hours))

@router.callback_query(F.data == "ev_setup_giveaway")
async def ev_setup_giveaway(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🎁 <b>Ивент: Раздача Алмазов</b>\n\nВведите количество алмазов для <b>КАЖДОГО</b> пользователя:")
    await state.set_state(AdminStates.event_giveaway)

@router.message(AdminStates.event_giveaway)
async def process_event_giveaway(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.text.strip().isdigit(): return await message.answer("❌ Введите целое число:")
    amount = int(message.text.strip())
    await state.clear()
    
    msg = await message.answer("⏳ Начисляю алмазы всей базе данных...")
    await db.execute("UPDATE users SET diamonds = diamonds + ?", (amount,))
    await db.commit()
    await msg.edit_text(f"✅ Раздача завершена! Всем добавлено по +{amount} 💎.")
    asyncio.create_task(broadcast_event_start("🎁 МГНОВЕННАЯ СУПЕР-РАЗДАЧА", f"Администрация зачислила на баланс каждому пользователю бота по <b>+{amount} алмазов</b>!", None))

@router.callback_query(F.data == "admin_mail")
async def admin_mail(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("📢 Введите текст рекламной рассылки:")
    await state.set_state(AdminStates.mailing_text)

@router.message(AdminStates.mailing_text)
async def process_admin_mailing(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text
    await state.clear()
    await message.answer("⏳ Запущена массовая рассылка по всем ботам пула...")
    await send_to_all_bots(text)
    await message.answer("✅ Рассылка завершена.")

# ========================= СИСТЕМНЫЕ ФУНКЦИИ И ОЧИСТКА =========================

async def delete_old_videos():
    while True:
        await asyncio.sleep(30)
        try:
            async with db.execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (datetime.now().isoformat(),)) as cur: rows = await cur.fetchall()
            if rows and GLOBAL_BOTS_POOL:
                main_bot = GLOBAL_BOTS_POOL[0]
                for mid, cid in rows:
                    try: await main_bot.delete_message(cid, mid)
                    except Exception: pass
                    await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (mid, cid))
                await db.commit()
        except Exception: pass

# ========================= МУЛЬТИ-ПОЛЛИНГ ЯДРО БОТА =========================

# ========================= ГЛАВНЫЙ ЗАПУСК СИСТЕМЫ =========================

async def main():
    await init_db()
    dp = Dispatcher()
    
    # Правильное подключение кастомной мидлвари в Aiogram 3.x
    dp.update.outer_middleware(BanMiddleware())
    dp.include_router(router)

       @dp.message(F.successful_payment)
    async def global_successful_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_diamonds:"):
            diamonds = int(payload.split(":")[1])
            if await is_event_active("global_x3_stars_until"): diamonds *= 3
            await add_diamonds(message.from_user.id, float(diamonds))
            x3_msg = " [⚡️ Сработал Ивент Х3!]" if await is_event_active("global_x3_stars_until") else ""
            await message.answer(f"🎉 <b>Оплата зачислена!</b> +<b>{diamonds}</b> 💎.{x3_msg}")
    
    print("🚀 Запуск пула мультиботов...")
    for token in MAIN_TOKENS:
        try:
            bot_instance = Bot(token=token, properties=DefaultBotProperties(parse_mode=ParseMode.HTML))
            GLOBAL_BOTS_POOL.append(bot_instance)
            await bot_instance.delete_webhook(drop_pending_updates=True)
            asyncio.create_task(dp.start_polling(bot_instance, allowed_updates=dp.resolve_used_update_types()))
            print(f"✅ Бот [{token.split(':')[0]}] успешно запущен.")
        except Exception as e:
            print(f"❌ Ошибка запуска бота с токеном {token.split(':')[0]}: {e}")
            
    print("🤖 Все боты активны. Ожидание событий...")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Бот остановлен.")
