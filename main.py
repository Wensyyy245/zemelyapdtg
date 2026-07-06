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
# ИСПРАВЛЕНО: Добавлен BaseMiddleware в импорт, чтобы кнопки снова ожили!
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
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
    
    try:
        await db.execute("ALTER TABLE users ADD COLUMN banned_until INTEGER DEFAULT 0")
        await db.commit()
        print("✅ Миграция: добавлена колонка banned_until")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE users ADD COLUMN is_referral_rewarded INTEGER DEFAULT 0")
        await db.commit()
        print("✅ Миграция: добавлена колонка is_referral_rewarded")
    except aiosqlite.OperationalError:
        pass
        
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

# ========================= ХЕЛПЕРЫ И ЗАЗАЩИТА БАЛАНСА =========================

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

# ========================= ПРОСМОТР МЕДИАФАЙЛОВ =========================

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

# ========================= ПРОМОКОДЫ И ЧЕКИ =========================

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
    if left - 1 == 0:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else:
        await db.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    await add_diamonds(user_id, float(reward))
    await db.commit()
    await message.answer(f"🎉 <b>Промокод успешно активирован!</b>\nНа ваш баланс зачислено: +<b>{reward}</b> 💎")

@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0: return await callback.answer("❌ Нельзя создавать промокоды с отрицательным балансом!", show_alert=True)
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
    if row and row[0] < 0: return await callback.answer("❌ Нельзя создавать чеки с отрицательным балансом!", show_alert=True)
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
        f"🔗 <b>Ссылка для активации чека:</b>\n<code>{check_link}</code>"
    )
    await message.answer(beautiful_check_text, reply_markup=main_menu(message.from_user.id))

# ========================= МАГАЗИН И TELEGRAM STARS =========================

@router.callback_query(F.data == "shop_main")
async def shop_main(callback: CallbackQuery):
    await callback.message.edit_text("🛒 <b>Добро пожаловать в магазин бота!</b>\n\nВыбирайте интересующую вас категорию товаров:", reply_markup=shop_categories_kb())

@router.callback_query(F.data == "cat_diamonds")
async def cat_diamonds(callback: CallbackQuery):
    pct = 0
    if await is_event_active("global_discount_until"):
        try: pct = int(await get_setting("global_discount_percent"))
        except: pct = 30
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text("💎 <b>Пополнение алмазов через Telegram Stars</b>\n\nКурс обмена: <b>1 алмаз = 0.5 ⭐️ Звезды</b>\nВыберите пакет:", reply_markup=shop_diamonds_kb(pct, timer))

@router.callback_query(F.data == "cat_abilities")
async def cat_abilities(callback: CallbackQuery):
    pct = 0
    if await is_event_active("global_discount_until"):
        try: pct = int(await get_setting("global_discount_percent"))
        except: pct = 30
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text("⚡ <b>Улучшения профиля и суперспособности</b>\n\nПокупаются за алмазы с баланса:", reply_markup=shop_abilities_kb(pct, timer))

@router.callback_query(F.data == "cat_premium")
async def cat_premium(callback: CallbackQuery):
    pct = 0
    if await is_event_active("global_discount_until"):
        try: pct = int(await get_setting("global_discount_percent"))
        except: pct = 30
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text("👑 <b>Премиум статусы в боте</b>\n\nДают полный доступ ко всем функциям бесплатно:", reply_markup=shop_premium_kb(pct, timer))

# Обработка оплаты Звездами
@router.callback_query(F.data.startswith("stars_"))
async def process_stars_buy(callback: CallbackQuery, state: FSMContext, bot: Bot):
    plan = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    pct = 0
    if await is_event_active("global_discount_until"):
        try: pct = int(await get_setting("global_discount_percent"))
        except: pct = 30
        
    if plan == "custom":
        await callback.message.edit_text("✍️ Введите количество алмазов, которое хотите купить (целое число от 10 до 5000):")
        await state.set_state(ShopStates.custom_diamonds)
        return
        
    diamonds = int(plan)
    stars_cost = int(diamonds * 0.5)
    if pct > 0: stars_cost = int(stars_cost * (1 - pct / 100))
    if stars_cost < 1: stars_cost = 1
    
    prices = [LabeledPrice(label=f"Покупка {diamonds} 💎", amount=stars_cost)]
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"Покупка {diamonds} Алмазов",
            description=f"Зачисление {diamonds} алмазов на игровой баланс бота.",
            payload=f"buy_diamonds:{diamonds}",
            provider_token="", # Оставляем пустым для Telegram Stars!
            currency="XTR",
            prices=prices
        )
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Ошибка выставления счета: {e}", show_alert=True)

@router.message(ShopStates.custom_diamonds)
async def process_custom_diamonds_amount(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    await state.clear()
    if not text.isdigit() or int(text) < 10 or int(text) > 5000:
        return await message.answer("❌ Ошибка: количество алмазов должно быть числом от 10 до 5000!")
        
    diamonds = int(text)
    stars_cost = int(diamonds * 0.5)
    
    pct = 0
    if await is_event_active("global_discount_until"):
        try: pct = int(await get_setting("global_discount_percent"))
        except: pct = 30
    if pct > 0: stars_cost = int(stars_cost * (1 - pct / 100))
    if stars_cost < 1: stars_cost = 1
    
    prices = [LabeledPrice(label=f"Покупка {diamonds} 💎", amount=stars_cost)]
    try:
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title=f"Покупка {diamonds} Алмазов",
            description=f"Зачисление индивидуального пакета {diamonds} алмазов на баланс.",
            payload=f"buy_diamonds:{diamonds}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка платежной системы: {e}")

# Покупка способностей за алмазы баланса
@router.callback_query(F.data.startswith("buy_"))
async def process_buy_item_diamonds(callback: CallbackQuery):
    item = callback.data.replace("buy_", "")
    user_id = callback.from_user.id
    
    prices = {"boost_x2": 50, "keep_videos": 500, "prem_normal": 1500, "prem_plus": 2000}
    if item not in prices: return await callback.answer("Товар не найден.")
    
    cost = prices[item]
    if await is_event_active("global_discount_until"):
        try:
            pct = int(await get_setting("global_discount_percent"))
            cost = int(cost * (1 - pct / 100))
        except: pass
        
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row or row[0] < cost:
        return await callback.answer(f"❌ Недостаточно алмазов! Требуется {cost} 💎", show_alert=True)
        
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?", (cost, user_id, cost))
    
    if item == "boost_x2":
        until = (datetime.now() + timedelta(hours=24)).isoformat()
        await db.execute("UPDATE users SET x2_until = ? WHERE user_id = ?", (until, user_id))
        msg = "🚀 Вы успешно купили буст х2 на 24 часа!"
    elif item == "keep_videos":
        await db.execute("UPDATE users SET keep_videos = 1 WHERE user_id = ?", (user_id,))
        msg = "♾ Поздравляем! Теперь просмотренные видео не будут удаляться из вашего чата."
    elif item == "prem_normal":
        await db.execute("UPDATE users SET premium = 1 WHERE user_id = ?", (user_id,))
        msg = "🌟 Вам выдан статус ПРЕМИУМ! Весь контент теперь бесплатный."
    elif item == "prem_plus":
        await db.execute("UPDATE users SET premium = 2, keep_videos = 1 WHERE user_id = ?", (user_id,))
        msg = "🔥 Вам выдан супер-статус ПРЕМИУМ+! Всё бесплатно, видео сохраняются навсегда."
        
    await db.commit()
    await callback.message.answer(msg)
    await callback.answer()

# Навигация назад
@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(f"👋 Главное меню бота. Выберите раздел:", reply_markup=main_menu(callback.from_user.id))

# ========================= АДМИН-ПАНЕЛЬ И ИВЕНТЫ =========================

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("Отказано в доступе.", show_alert=True)
    await callback.message.edit_text("⚙️ <b>Панель управления проектом Swill Way</b>", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_events_panel")
async def admin_events_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🔥 <b>Управление глобальными событиями во всех ботах пула:</b>", reply_markup=admin_events_kb())

@router.callback_query(F.data.startswith("ev_setup_"))
async def setup_event_trigger(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    ev_type = callback.data.replace("ev_setup_", "")
    await state.update_data(ev_type=ev_type)
    
    if ev_type == "setup_discount":
        await callback.message.edit_text("📉 Введите процент скидки в магазине (целое число от 1 до 90):")
        await state.set_state(AdminStates.event_percent)
    elif ev_type == "setup_giveaway":
        await callback.message.edit_text("🎁 Введите сумму раздачи алмазов для КАЖДОГО пользователя:")
        await state.set_state(AdminStates.event_giveaway)
    else:
        await callback.message.edit_text("⏳ Введите длительность события в часах (целое число):")
        await state.set_state(AdminStates.event_hours)

@router.message(AdminStates.event_hours)
async def process_event_hours(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit(): return await message.answer("Ошибка: введите целое число.")
    hours = int(text)
    data = await state.get_data()
    ev = data['ev_type']
    await state.clear()
    
    until_time = (datetime.now() + timedelta(hours=hours)).isoformat()
    
    if ev == "setup_x2":
        await set_setting("global_x2_until", until_time)
        await broadcast_event_start("х2 Награда за рефералов!", "Реферальный бонус временно увеличен до 8 💎 за каждого приглашенного пользователя!", hours)
    elif ev == "setup_x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await broadcast_event_start("х3 Пополнение Алмазов!", "При покупке алмазов через Telegram Stars вы будете получать в ТРИ РАЗА БОЛЬШЕ алмазов!", hours)
    elif ev == "setup_free_view":
        await set_setting("global_free_view_until", until_time)
        await broadcast_event_start("Бесплатный просмотр контента!", "Все ограничения сняты! Смотрите видео и фото абсолютно БЕСПЛАТНО, алмазы не списываются!", hours)
    elif ev == "setup_lucky_hour":
        await set_setting("global_lucky_hour_until", until_time)
        await broadcast_event_start("Счастливый час!", "За просмотр медиафайлов вы больше не тратите алмазы, а наоборот — ПОЛУЧАЕТЕ +2 💎 за каждый просмотр!", hours)
        
    await message.answer("🚀 Событие успешно запущено на уровне всей сети ботов!", reply_markup=admin_menu())

# ОСТАЛЬНЫЕ БАЗОВЫЕ ХЕНДЛЕРЫ
@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery):
    await callback.message.answer("🛠 <b>Служба поддержки проекта</b>\n\nЕсли у вас возникли вопросы по оплате, багам или сотрудничеству, пишите главным администраторам проекта:\n👉 @PavelGiftsPG")
    await callback.answer()

@router.callback_query(F.data == "leaderboard")
async def leaderboard_handler(callback: CallbackQuery):
    async with db.execute("SELECT first_name, diamonds FROM users ORDER BY diamonds DESC LIMIT 10") as cur:
        rows = await cur.fetchall()
    text = "🏆 <b>ТОП-10 Богатейших пользователей бота:</b>\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. 👤 {row[0]} — <b>{row[1]} 💎</b>\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardBuilder().button(text="◀️ Меню", callback_data="back_main").as_markup())

@router.callback_query(F.data == "referral")
async def referral_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    me = await callback.message.bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={user_id}"
    
    async with db.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)) as cur:
        cnt = (await cur.fetchone())[0]
        
    text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"Приглашайте друзей и зарабатывайте алмазы!\n"
        f"💰 Награда за друга: <b>4.0 💎</b> (или 8.0 💎 во время ивентов!)\n\n"
        f"📈 Вы пригласили: <b>{cnt}</b> человек\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardBuilder().button(text="◀️ Меню", callback_data="back_main").as_markup())

# ========================= КОРНЕВОЙ ЗАПУСК МУЛЬТИБОТОВ =========================

async def main():
    await init_db()
    
    dp = Dispatcher()
    dp.include_router(router)
    # Регистрируем исправленную мидлварь глобально на все события
    dp.message.middleware(BanMiddleware())
    dp.callback_query.middleware(BanMiddleware())
    
    @dp.pre_checkout_query()
    async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
        await pre_checkout_query.answer(ok=True)
        
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
            
    print("🤖 Пул мультиботов активен. Ожидание обновлений...")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Бот остановлен.")
