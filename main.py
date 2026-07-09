import asyncio
import random
import os
import sys
import uuid
import time
import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO)
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
# ========================= НАСТРОЙКИ =========================

MAIN_TOKENS = [
    "8971264936:AAGnz7N90o_T1_EUEa694KTZThdFWGFhqgI",
    "8749652033:AAGxEa4xA2BU9wEUUcntIH3MfEoRVBniiwQ",
]

ADMIN_IDS = [
    8603534638,  
    8570452473,  
    8502341995,
    8794011165   
]

CHANNELS = [
    (-1004466816546, "Наш канал", "https://t.me/+2kcAsXlm-TpkYjMy"),
    ("@PavelGiftsPG", "Спонсор", "https://t.me/PavelGiftsPG"),
]

EVENT_CHANNEL_ID = -1004466816546  

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"
PACKS_DIR = DATA_DIR / "packs"
PACKS_DIR.mkdir(exist_ok=True)

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

# После этих строк:
# PHOTO_DIR.mkdir(exist_ok=True)

# ========================= ПАКИ =========================
PACKS_DIR = DATA_DIR / "packs"
PACKS_DIR.mkdir(exist_ok=True)

PACKS = {
    1: {
        "name": "Пак 1",
        "price": 100,
        "folder": PACKS_DIR / "pack1",
        "mega_link": "https://mega.nz/folder/ВАША_ССЫЛКА1"
    },
    2: {
        "name": "Пак 2",
        "price": 250,
        "folder": PACKS_DIR / "pack2",
        "mega_link": "https://mega.nz/folder/ВАША_ССЫЛКА2"
    },
    3: {
        "name": "Пак 3",
        "price": 400,
        "folder": PACKS_DIR / "pack3",
        "mega_link": "https://mega.nz/folder/ВАША_ССЫЛКА3"
    },
    4: {
        "name": "Пак 4",
        "price": 600,
        "folder": PACKS_DIR / "pack4",
        "mega_link": "https://mega.nz/folder/ВАША_ССЫЛКА4"
    }
}

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
    economy_value = State()
     pack_name = State()
    pack_description = State()
    pack_price = State()
    pack_file = State()

class PromoStates(StatesGroup):
    create_code = State()
    create_reward = State()
    create_uses = State()
    activate_code = State()

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
            username TEXT DEFAULT NULL,
            diamonds REAL DEFAULT 8.0,
            referred_by INTEGER DEFAULT NULL,
            is_referral_rewarded INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            banned_until INTEGER DEFAULT 0,
            premium INTEGER DEFAULT 0,
            x2_until TEXT DEFAULT NULL,
            keep_videos INTEGER DEFAULT 0,
             id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT,
        price INTEGER,
        photo_path TEXT,
        file_path TEXT,
        created_at TEXT
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

    try:
        await db.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT NULL")
        await db.commit()
        print("✅ Миграция: добавлена колонка username")
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
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('maintenance_mode', 'false')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('video_price', '6')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('photo_price', '3')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('referral_reward', '4')")
    await db.execute("INSERT OR IGNORE INTO settings VALUES ('auto_ban_limit', '10000')")

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
    await db.commit()

# ========================= ХЕЛПЕРЫ =========================

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

async def is_maintenance_mode() -> bool:
    val = await get_setting('maintenance_mode')
    return val.lower() == 'true'

def parse_duration_input(text: str):
    """Парсит ввод времени: '90m' / '90м' -> минуты, '2h' / '2ч' -> часы, просто число -> часы."""
    text = text.strip().lower()
    if not text:
        return None
    if text.endswith("m") or text.endswith("м"):
        num = text[:-1].strip()
        if num.isdigit() and int(num) > 0:
            return timedelta(minutes=int(num)), f"{num} мин."
    elif text.endswith("h") or text.endswith("ч"):
        num = text[:-1].strip()
        if num.isdigit() and int(num) > 0:
            return timedelta(hours=int(num)), f"{num} ч."
    elif text.isdigit() and int(text) > 0:
        return timedelta(hours=int(text)), f"{text} ч."
    return None

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

async def broadcast_event_start(title: str, description: str, duration_str: str = None):
    time_str = f"⏳ <b>Длительность:</b> {duration_str}\n" if duration_str else ""
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

# ========================= МИДЛВАРЬ =========================

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

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if await is_maintenance_mode():
            user = data.get("event_from_user")
            if user and user.id not in ADMIN_IDS:
                maintenance_text = (
                    "🛠 <b>Технические работы в боте!</b>\n\n"
                    "Бот временно недоступен.\n"
                    "Следите за новостями в нашем канале: https://t.me/+ryYTkHSQG6VmNjUy"
                )
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("🛠 Техработы!", show_alert=True)
                        if event.message:
                            await event.message.edit_text(maintenance_text)
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    try:
                        await event.answer(maintenance_text)
                    except Exception:
                        pass
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

async def get_user_data(user_id: int, first_name: str = "Пользователь", username: str = None):
    async with db.execute("SELECT diamonds, premium, x2_until, keep_videos, referred_by, is_referral_rewarded FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, first_name, username, diamonds) VALUES (?, ?, ?, 8.0)", (user_id, first_name, username))
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

        if username is not None:
            await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            await db.commit()
            
        return {"diamonds": diamonds_val, "premium": prem_val, "x2_until": row[2], "keep_videos": keep_val, "referred_by": row[4], "is_referral_rewarded": row[5]}

async def check_auto_ban(user_id: int):
    """Автоматически банит навсегда обычного пользователя (не админа), если его баланс алмазов превышает лимит."""
    if user_id in ADMIN_IDS:
        return
    async with db.execute("SELECT diamonds, is_banned FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return
    diamonds_val, is_banned_val = row
    try:
        limit = float(await get_setting("auto_ban_limit"))
    except (ValueError, TypeError):
        limit = 10000.0
    if diamonds_val > limit and is_banned_val != 1:
        await db.execute("UPDATE users SET is_banned = 1, banned_until = 0 WHERE user_id = ?", (user_id,))
        await db.commit()
        if GLOBAL_BOTS_POOL:
            try:
                await GLOBAL_BOTS_POOL[0].send_message(
                    user_id,
                    "⛔ <b>Ваш аккаунт заблокирован автоматической системой безопасности навсегда за подозрительное превышение лимита баланса алмазов.</b>\n\n"
                    "Свяжитесь с администрацией: @zemelya_admin",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

async def add_diamonds(user_id: int, amount: float):
    await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
    await db.commit()
    await check_auto_ban(user_id)

# ========================= КЛАВИАТУРЫ =========================

async def main_menu(user_id: int):
    try: video_price = float(await get_setting("video_price"))
    except (ValueError, TypeError): video_price = 6.0
    try: photo_price = float(await get_setting("photo_price"))
    except (ValueError, TypeError): photo_price = 3.0
    kb = InlineKeyboardBuilder()
    kb.button(text=f"📺 Смотреть видео ({video_price:g} 💎)", callback_data="watch")
    kb.button(text=f"📸 Посмотреть фото ({photo_price:g} 💎)", callback_data="watch_photo")
    kb.button(text="🎁 Паки", callback_data="packs_menu")
    kb.button(text="🛒 Магазин 💰", callback_data="shop_main")
    kb.button(text="🎟 Промокоды", callback_data="promo_menu")
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
    kb.button(text="⚡ Способности (за Звезды)", callback_data="cat_abilities")
    kb.button(text="👑 Премиум Статусы (за Алмазы)", callback_data="cat_premium")
    kb.button(text="📦 Паки (За Звезды)", callback_data="cat_packs")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_diamonds_kb(discount_pct: int = 0, timer: str = ""):
    kb = InlineKeyboardBuilder()
    prices = [80, 200, 400]
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
    p1, p2 = 50, 150
    f1 = int(p1 * (1 - discount_pct / 100))
    f2 = int(p2 * (1 - discount_pct / 100))
    timer_str = f" ({timer})" if timer else ""
    kb = InlineKeyboardBuilder()
    text1 = f"🚀 х2 Рефералы (24ч) — <s>{p1}</s> -> {f1} ⭐️" if discount_pct > 0 else f"🚀 х2 от Рефералов (24ч) — {p1} ⭐️"
    text2 = f"♾ Видео навсегда — <s>{p2}</s> -> {f2} ⭐️" if discount_pct > 0 else f"♾ Видео навсегда — {p2} ⭐️"
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
    kb.button(text="📦 Управление Паками", callback_data="admin_packs")
    kb.button(text="🚫 Забаненные пользователи", callback_data="admin_banned_list")
    kb.button(text="👑 Список админов", callback_data="admin_list_admins")
    kb.button(text="⚙️ Настройки экономики", callback_data="admin_economy")
    kb.button(text="📤 Экспорт пользователей (CSV)", callback_data="admin_export_users")
    kb.button(text="🎫 Активные промокоды", callback_data="admin_active_promos")
    kb.button(text="🗑 Удалить ВСЕ промокоды", callback_data="admin_delete_all_promos")
    kb.button(text="📢 Рассылка текста", callback_data="admin_mail")
    kb.button(text="🔥 Управление ИВЕНТАМИ", callback_data="admin_events_panel")
    kb.button(text="🛠 Техработы (Вкл/Выкл)", callback_data="admin_toggle_maintenance")
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

# ========================= ХЕНДЛЕРЫ =========================

router = Router()

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name
    username = message.from_user.username
    args = message.text.split()
    
    async with db.execute("SELECT referred_by, is_referral_rewarded FROM users WHERE user_id = ?", (user_id,)) as cur:
        existing = await cur.fetchone()
        
    is_new_user = (existing is None)
    
    if is_new_user and len(args) > 1:
        param = args[1]
        if param.isdigit():
            referrer_id = int(param)
            if referrer_id != user_id:
                await db.execute(
                    "INSERT INTO users (user_id, first_name, username, diamonds, referred_by, is_referral_rewarded) VALUES (?, ?, ?, 8.0, ?, 0)", 
                    (user_id, name, username, referrer_id)
                )
                await db.commit()
    
    udata = await get_user_data(user_id, name, username)

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
            try: base_reward = float(await get_setting("referral_reward"))
            except (ValueError, TypeError): base_reward = 4.0
            if await is_event_active("global_x2_until"): base_reward *= 2
            if ref_info[1] and datetime.fromisoformat(ref_info[1]) > datetime.now(): base_reward *= 2
            
            await add_diamonds(ref_id, base_reward)
            await db.execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            
            try: await bot.send_message(ref_id, f"🎉 Твой реферал {name} успешно выполнил условия подписки! Тебе начислено +{base_reward} 💎")
            except Exception: pass

    await message.answer(f"👋 Добро пожаловать! 💎\n\nНа балансе: <b>{udata['diamonds']}</b> алмазов", reply_markup=await main_menu(user_id))

# ========================= ХЕНДЛЕРЫ ПАКОВ (ПОЛЬЗОВАТЕЛЬСКИЕ) =========================

@router.callback_query(F.data == "packs_menu")
async def packs_menu(callback: CallbackQuery):
    async with db.execute("SELECT id, name, description, price, photo_path FROM packs ORDER BY id DESC") as cur:
        packs = await cur.fetchall()
    
    if not packs:
        kb = InlineKeyboardBuilder()
        kb.button(text="◀️ Назад в меню", callback_data="back_main")
        return await callback.message.edit_text("🎁 <b>Паки</b>\n\nПока нет доступных паков.", reply_markup=kb.as_markup())
    
    text = "🎁 <b>Доступные паки:</b>\n\nВыберите пак для просмотра:"
    kb = InlineKeyboardBuilder()
    
    for pack_id, name, desc, price, photo_path in packs:
        kb.button(text=f"📦 {name} — {price} ⭐️", callback_data=f"view_pack_{pack_id}")
    
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("view_pack_"))
async def view_pack(callback: CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    
    async with db.execute("SELECT name, description, price, photo_path FROM packs WHERE id = ?", (pack_id,)) as cur:
        pack = await cur.fetchone()
    
    if not pack:
        return await callback.answer("Пак не найден!", show_alert=True)
    
    name, desc, price, photo_path = pack
    
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💰 Купить за {price} ⭐️", callback_data=f"buy_pack_{pack_id}")
    kb.button(text="◀️ Назад к пакам", callback_data="packs_menu")
    kb.adjust(1)
    
    try:
        if Path(photo_path).exists():
            await callback.message.answer_photo(
                photo=FSInputFile(photo_path),
                caption=f"📦 <b>{name}</b>\n\n📄 {desc}\n\n💎 Цена: <b>{price} ⭐️</b>",
                reply_markup=kb.as_markup()
            )
        else:
            await callback.message.answer(
                f"📦 <b>{name}</b>\n\n📄 {desc}\n\n💎 Цена: <b>{price} ⭐️</b>",
                reply_markup=kb.as_markup()
            )
        await callback.message.delete()
    except Exception as e:
        logging.error(f"Ошибка отображения пака: {e}")
        await callback.answer("❌ Ошибка отображения пака.", show_alert=True)

@router.callback_query(F.data.startswith("buy_pack_"))
async def buy_pack(callback: CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    
    async with db.execute("SELECT name, description, price FROM packs WHERE id = ?", (pack_id,)) as cur:
        pack = await cur.fetchone()
    
    if not pack:
        return await callback.answer("Пак не найден!", show_alert=True)
    
    name, desc, price = pack
    
    try:
        await callback.message.answer_invoice(
            title=f"Пак: {name}",
            description=desc[:255],
            payload=f"buy_pack:{pack_id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"Пак {name}", amount=price)]
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка создания инвойса для пака: {e}")
        await callback.answer("❌ Ошибка создания счета.", show_alert=True)

# ========================= ХЕНДЛЕРЫ ПАКОВ (АДМИНСКИЕ) =========================

@router.callback_query(F.data == "admin_packs")
async def admin_packs(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    
    async with db.execute("SELECT id, name, price FROM packs ORDER BY id DESC") as cur:
        packs = await cur.fetchall()
    
    text = "📦 <b>Управление Паками</b>\n\n"
    kb = InlineKeyboardBuilder()
    
    if packs:
        text += "Существующие паки:\n"
        for pack_id, name, price in packs:
            text += f"• {name} — {price} ⭐️\n"
            kb.button(text=f"❌ Удалить {name}", callback_data=f"del_pack_{pack_id}")
    else:
        text += "Паков пока нет.\n"
    
    kb.button(text="➕ Создать Пак", callback_data="create_pack_start")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "create_pack_start")
async def create_pack_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("📸 <b>Шаг 1/5:</b> Отправьте фото-обложку для пака:")
    await state.set_state(AdminStates.pack_name)
    await state.update_data(pack_step="photo")

@router.message(AdminStates.pack_name, F.photo)
async def process_pack_photo(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    photo_path = PACKS_DIR / f"pack_{uuid.uuid4().hex[:8]}.jpg"
    await message.bot.download_file(file.file_path, destination=photo_path)
    
    await state.update_data(pack_photo=str(photo_path))
    await message.answer("📝 <b>Шаг 2/5:</b> Введите название пака:")
    await state.set_state(AdminStates.pack_description)

@router.message(AdminStates.pack_name)
async def process_pack_name_invalid(message: Message):
    await message.answer("❌ Пожалуйста, отправьте именно фото (изображение)!")

@router.message(AdminStates.pack_description)
async def process_pack_name(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    name = message.text.strip()
    if len(name) > 100:
        return await message.answer("❌ Название слишком длинное (макс 100 символов)!")
    
    await state.update_data(pack_name=name)
    await message.answer("📄 <b>Шаг 3/5:</b> Введите описание пака:")
    await state.set_state(AdminStates.pack_price)

@router.message(AdminStates.pack_price)
async def process_pack_description(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    desc = message.text.strip()
    if len(desc) > 500:
        return await message.answer("❌ Описание слишком длинное (макс 500 символов)!")
    
    await state.update_data(pack_description=desc)
    await message.answer("💎 <b>Шаг 4/5:</b> Введите цену пака в Звездах (целое число):")
    await state.set_state(AdminStates.pack_file)

@router.message(AdminStates.pack_file)
async def process_pack_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        return await message.answer("❌ Цена должна быть положительным целым числом!")
    
    await state.update_data(pack_price=int(text))
    await message.answer("📁 <b>Шаг 5/5:</b> Отправьте файл, который будут получать покупатели:")
    await state.set_state(AdminStates.pack_name)
    await state.update_data(pack_step="file")

@router.message(AdminStates.pack_name, F.document | F.video | F.photo | F.audio | F.voice | F.video_note | F.animation | F.sticker)
async def process_pack_file(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    
    data = await state.get_data()
    await state.clear()
    
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or f"file_{uuid.uuid4().hex[:8]}"
        file = await message.bot.get_file(file_id)
    elif message.video:
        file_id = message.video.file_id
        file_name = f"video_{uuid.uuid4().hex[:8]}.mp4"
        file = await message.bot.get_file(file_id)
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = f"photo_{uuid.uuid4().hex[:8]}.jpg"
        file = await message.bot.get_file(file_id)
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or f"audio_{uuid.uuid4().hex[:8]}.mp3"
        file = await message.bot.get_file(file_id)
    elif message.voice:
        file_id = message.voice.file_id
        file_name = f"voice_{uuid.uuid4().hex[:8]}.ogg"
        file = await message.bot.get_file(file_id)
    elif message.video_note:
        file_id = message.video_note.file_id
        file_name = f"videonote_{uuid.uuid4().hex[:8]}.mp4"
        file = await message.bot.get_file(file_id)
    elif message.animation:
        file_id = message.animation.file_id
        file_name = message.animation.file_name or f"gif_{uuid.uuid4().hex[:8]}.gif"
        file = await message.bot.get_file(file_id)
    elif message.sticker:
        file_id = message.sticker.file_id
        file_name = f"sticker_{uuid.uuid4().hex[:8]}.webp"
        file = await message.bot.get_file(file_id)
    else:
        return await message.answer("❌ Неподдерживаемый тип файла!")
    
    file_path = PACKS_DIR / file_name
    await message.bot.download_file(file.file_path, destination=file_path)
    
    await db.execute(
        "INSERT INTO packs (name, description, price, photo_path, file_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (data['pack_name'], data['pack_description'], data['pack_price'], data['pack_photo'], str(file_path), datetime.now().isoformat())
    )
    await db.commit()
    
    await message.answer(
        f"✅ <b>Пак успешно создан!</b>\n\n"
        f"📦 Название: {data['pack_name']}\n"
        f"💎 Цена: {data['pack_price']} ⭐️\n"
        f"📄 Описание: {data['pack_description']}",
        reply_markup=admin_menu()
    )

@router.callback_query(F.data.startswith("del_pack_"))
async def delete_pack(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    pack_id = int(callback.data.split("_")[2])
    
    async with db.execute("SELECT photo_path, file_path FROM packs WHERE id = ?", (pack_id,)) as cur:
        pack = await cur.fetchone()
    
    if pack:
        for path in [pack[0], pack[1]]:
            if path and Path(path).exists():
                try:
                    Path(path).unlink()
                except Exception:
                    pass
    
    await db.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
    await db.commit()
    
    await callback.answer("✅ Пак удален!", show_alert=True)
    await admin_packs(callback)

@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if await check_subscription(user_id, bot):
        udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
        
        if udata["referred_by"] and udata["is_referral_rewarded"] == 0:
            ref_id = udata["referred_by"]
            async with db.execute("SELECT premium, x2_until FROM users WHERE user_id = ?", (ref_id,)) as cur:
                ref_info = await cur.fetchone()
            if ref_info:
                try: base_reward = float(await get_setting("referral_reward"))
                except (ValueError, TypeError): base_reward = 4.0
                if await is_event_active("global_x2_until"): base_reward *= 2
                if ref_info[1] and datetime.fromisoformat(ref_info[1]) > datetime.now(): base_reward *= 2
                
                await add_diamonds(ref_id, base_reward)
                await db.execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                try: await bot.send_message(ref_id, f"🎉 Твой реферал {callback.from_user.first_name} подписался! Начислено +{base_reward} 💎")
                except Exception: pass

        await callback.message.edit_text("✅ Подписка подтверждена!", reply_markup=await main_menu(user_id))
    else:
        await callback.answer("❌ Ты не подписался на все каналы!", show_alert=True)

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
        try: video_price = float(await get_setting("video_price"))
        except (ValueError, TypeError): video_price = 6.0
        if current_diamonds < video_price: 
            return await callback.answer(f"❌ Недостаточно алмазов! Вам нужно минимум {video_price:g} 💎", show_alert=True)
            
        await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?", (video_price, user_id, video_price))
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
        try: photo_price = float(await get_setting("photo_price"))
        except (ValueError, TypeError): photo_price = 3.0
        if current_diamonds < photo_price: 
            return await callback.answer(f"❌ Недостаточно алмазов! Требуется {photo_price:g} 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?", (photo_price, user_id, photo_price))
        await db.commit()
        
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("Папка photo пуста.", show_alert=True)
    
    if is_lucky: await add_diamonds(user_id, 2.0)
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)), caption="🍀 Счастливый час: +2 💎!" if is_lucky else None)
    await callback.answer()

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.message.answer("❌ <b>Доступ к промокодам заблокирован, пока ваш баланс отрицательный!</b>")

    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Активировать промокод", callback_data="promo_activate")
    kb.button(text="➕ Создать промокод", callback_data="promo_create")
    kb.button(text="◀️ Назад в главное меню", callback_data="back_main")
    kb.adjust(1)
    await callback.message.edit_text("🎟 <b>Раздел Промокодов</b>\n\nЗдесь вы можете активировать промокод или создать свой!", reply_markup=kb.as_markup())

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
        f"✅ Промокод успешно создан!\n\n"
        f"🎫 Код: <b>{data['code']}</b>\n"
        f"💎 Награда: <b>{data['reward']}</b> за активацию\n"
        f"👥 Кол-во активаций: <b>{uses}</b>"
    )
    await message.answer(beautiful_text, reply_markup=await main_menu(message.from_user.id))

@router.callback_query(F.data == "leaderboard")
async def leaderboard_menu(callback: CallbackQuery):
    placeholders = ",".join("?" * len(ADMIN_IDS))
    query = f"SELECT user_id, first_name, diamonds FROM users WHERE diamonds >= 0 AND user_id NOT IN ({placeholders}) ORDER BY diamonds DESC LIMIT 10"
    async with db.execute(query, tuple(ADMIN_IDS)) as cur: 
        rows = await cur.fetchall()
        
    if not rows:
        kb = InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main")
        return await callback.message.edit_text("🏆 <b>Список лидеров пуст.</b>", reply_markup=kb.as_markup())
        
    text = "🏆 <b>ТОП-10 ИГРОКОВ ПО АЛМАЗАМ</b> 🏆\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    
    for i, (uid, name, diamonds) in enumerate(rows, 1):
        place = medals.get(i, f"{i}.")
        text += f"{place} {name} <code>(ID: {uid})</code> — <b>{diamonds} 💎</b>\n"
        
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id in ADMIN_IDS: 
        await callback.message.edit_text("🛠 <b>Административная Панель</b>:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("👤 <b>Улучшенная панель пользователей</b>\n\nВведите Telegram ID <b>или</b> @username пользователя для управления его балансом и статусом блокировок:")
    await state.set_state(AdminStates.user_manage_id)

@router.message(AdminStates.user_manage_id)
async def process_user_search(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()

    row = None
    if text.startswith("@"):
        uname = text[1:]
        async with db.execute("SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE username = ? COLLATE NOCASE", (uname,)) as cur:
            row = await cur.fetchone()
    elif text.isdigit():
        uid = int(text)
        async with db.execute("SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
    else:
        async with db.execute("SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE username = ? COLLATE NOCASE", (text,)) as cur:
            row = await cur.fetchone()
    
    if not row: return await message.answer("❌ Юзер не найден в БД бота. Проверьте ID или @username и попробуйте снова.")
    
    uid, uname_row, diamonds_val, is_banned_val, banned_until_val, premium_val = row
    await state.update_data(target_id=uid)
    
    ban_status = "❌ Нет"
    if is_banned_val == 1: ban_status = "⛔ Перманентно"
    elif banned_until_val > int(time.time()): ban_status = f"⏳ До {datetime.fromtimestamp(banned_until_val).strftime('%d.%m %H:%M')}"

    prem_status = "❌ Нет" if premium_val == 0 else ("🌟 Premium" if premium_val == 1 else "🔥 Premium+")
        
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Изменить баланс алмазов", callback_data="adm_change_diamonds")
    kb.button(text="👑 Выдать статус вручную", callback_data="adm_grant_premium_menu")
    kb.button(text="🚫 Заблокировать (Временный бан)", callback_data="adm_ban_time")
    kb.button(text="🔒 Забанить НАВСЕГДА", callback_data="adm_ban_forever")
    kb.button(text="🔓 Разблокировать", callback_data="adm_unban")
    kb.button(text="◀️ В админку", callback_data="admin_enter")
    kb.adjust(1)
    
    await message.answer(
        f"👤 <b>Пользователь:</b> {uname_row}\n"
        f"ID: <code>{uid}</code>\n"
        f"Баланс: <b>{diamonds_val}</b> 💎\n"
        f"Премиум: <b>{prem_status}</b>\n"
        f"Блокировка: <b>{ban_status}</b>",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "adm_grant_premium_menu")
async def adm_grant_premium_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    data = await state.get_data()
    uid = data.get("target_id")
    if not uid:
        return await callback.answer("Сначала выберите пользователя через поиск.", show_alert=True)

    kb = InlineKeyboardBuilder()
    kb.button(text="🌟 Выдать Premium", callback_data="adm_grant_prem_1")
    kb.button(text="🔥 Выдать Premium+", callback_data="adm_grant_prem_2")
    kb.button(text="🚫 Убрать статус", callback_data="adm_grant_prem_0")
    kb.button(text="◀️ Отмена", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.answer(f"👑 Выберите статус для пользователя <code>{uid}</code>:", reply_markup=kb.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("adm_grant_prem_"))
async def adm_grant_prem(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    level = int(callback.data.split("_")[-1])
    data = await state.get_data()
    uid = data.get("target_id")
    if not uid:
        return await callback.answer("Сначала выберите пользователя через поиск.", show_alert=True)

    if level == 0:
        await db.execute("UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?", (uid,))
    else:
        await db.execute("UPDATE users SET premium = ? WHERE user_id = ?", (level, uid))
    await db.commit()

    label = "статус снят" if level == 0 else ("Premium выдан" if level == 1 else "Premium+ выдан")
    await callback.answer(f"✅ {label}!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())

@router.callback_query(F.data == "adm_change_diamonds")
async def adm_change_diamonds_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введите новое значение баланса алмазов (баланс будет установлен именно на это число, например 50):")
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
    
    await db.execute("UPDATE users SET diamonds = ? WHERE user_id = ?", (amount, uid))
    await db.commit()
    await check_auto_ban(uid)
    await message.answer(f"✅ Баланс пользователя установлен на {amount} 💎.", reply_markup=admin_menu())

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

@router.callback_query(F.data == "admin_active_promos")
async def admin_active_promos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: 
        return await callback.answer("❌ У вас нет прав администратора!", show_alert=True)
    
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
        
        await callback.answer(f"✅ Промокод {promo_code} успешно удален!", show_alert=True)
        
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

@router.callback_query(F.data == "shop_main")
async def shop_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
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
    try: await callback.message.edit_text("💎 <b>Пополнение алмазов (Telegram Stars)</b>\n\n<i>Курс: 1 алмаз = 0.8 звезд</i>", reply_markup=shop_diamonds_kb(discount_pct=pct, timer=timer))
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
    raw_stars = diamonds * 0.8
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
    rates = {"stars_100": (100, 80), "stars_250": (250, 200), "stars_500": (500, 400)}
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
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("⚡ <b>Магазин способностей (оплата Telegram Stars)</b>", reply_markup=shop_abilities_kb(discount_pct=pct, timer=timer))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery, bot: Bot):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = max(1, int(50 * (1 - pct / 100)))
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Буст х2 Рефералы (24ч)",
            description="Ускоряет начисление наград от рефералов х2 на 24 часа.",
            payload="ability_x2",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=price)]
        )
        await callback.answer()
    except Exception:
        await callback.answer("❌ Ошибка создания счета Stars.", show_alert=True)

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    if udata["keep_videos"] == 1 or udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = max(1, int(150 * (1 - pct / 100)))
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Видео навсегда",
            description="Полученные видео больше никогда не будут удаляться.",
            payload="ability_keep_videos",
            currency="XTR",
            prices=[LabeledPrice(label="Telegram Stars", amount=price)]
        )
        await callback.answer()
    except Exception:
        await callback.answer("❌ Ошибка создания счета Stars.", show_alert=True)

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
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
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
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
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

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    udata = await get_user_data(callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
    await callback.message.edit_text(f"💎 Баланс: <b>{udata['diamonds']}</b> алмазов", reply_markup=await main_menu(callback.from_user.id))

@router.callback_query(F.data.in_({"referral", "support"}))
async def static_callbacks(callback: CallbackQuery, bot: Bot):
    if callback.data == "referral":
        me = await bot.get_me()
        try: ref_reward = float(await get_setting("referral_reward"))
        except (ValueError, TypeError): ref_reward = 4.0
        await callback.message.edit_text(f"👥 Реф. ссылка:\n<code>https://t.me/{me.username}?start={callback.from_user.id}</code>\n\nПриглашение: +{ref_reward:g} 💎\n\n<i>Важно: Алмазы поступят на твой аккаунт только после подписки приглашенного на каналы спонсоров!</i>", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())
    elif callback.data == "support":
        await callback.message.edit_text("🛠 ТП: @zemelya_admin", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    async with db.execute("SELECT COUNT(*) FROM users") as cur: total_users = (await cur.fetchone())[0]
    async with db.execute("SELECT COALESCE(SUM(diamonds), 0) FROM users WHERE diamonds > 0") as cur: total_diamonds = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1 OR banned_until > ?", (int(time.time()),)) as cur: banned_count = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM users WHERE premium > 0") as cur: premium_count = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM promo_codes") as cur: promo_count = (await cur.fetchone())[0]
    admin_placeholders = ",".join("?" * len(ADMIN_IDS))
    async with db.execute(
        f"SELECT first_name, diamonds FROM users WHERE diamonds >= 0 AND user_id NOT IN ({admin_placeholders}) ORDER BY diamonds DESC LIMIT 3",
        tuple(ADMIN_IDS)
    ) as cur: top_rows = await cur.fetchall()
    
    x2_active = "✅ Активен" if await is_event_active("global_x2_until") else "❌ Выключен"
    is_disc = await is_event_active("global_discount_until")
    pct = await get_setting("global_discount_percent")
    disc_active = f"✅ Активен (-{pct}%)" if is_disc else "❌ Выключен"
    x3_stars = "✅ Активен" if await is_event_active("global_x3_stars_until") else "❌ Выключен"
    free_view = "✅ Активен" if await is_event_active("global_free_view_until") else "❌ Выключен"
    lucky_hour = "✅ Активен" if await is_event_active("global_lucky_hour_until") else "❌ Выключен"
    
    top_text = "\n".join(f"  {i}. {n} — {d:g} 💎" for i, (n, d) in enumerate(top_rows, 1)) if top_rows else "  нет данных"
    
    text = (
        f"📊 <b>Статистика Системы:</b>\n\n"
        f"👥 Пользователей в БД: <b>{total_users}</b>\n"
        f"💎 Алмазов в обороте: <b>{total_diamonds:g}</b>\n"
        f"📦 Паков создано: <b>{total_packs}</b>\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"👑 С премиум-статусом: <b>{premium_count}</b>\n"
        f"🎫 Активных промокодов: <b>{promo_count}</b>\n"
        f"🪞 Активных ботов в пуле: <b>{len(GLOBAL_BOTS_POOL)}</b>\n\n"
        f"🏆 <b>Топ-3 по балансу:</b>\n{top_text}\n\n"
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
    await callback.message.edit_text("⏳ <b>Ивент: х2 Рефералы</b>\n\nВведите время действия ивента (например: <code>2h</code> — часы, <code>30m</code> — минуты, либо просто число часов):")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="x2")

@router.callback_query(F.data == "ev_setup_x3_stars")
async def ev_setup_x3_stars(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("⚡️ <b>Ивент: Х3 К покупкам Stars</b>\n\nВведите время действия ивента (например: <code>2h</code> — часы, <code>30m</code> — минуты, либо просто число часов):")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="x3_stars")

@router.callback_query(F.data == "ev_setup_free_view")
async def ev_setup_free_view(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🆓 <b>Ивент: Бесплатный Просмотр Медиа</b>\n\nВведите время действия ивента (например: <code>2h</code> — часы, <code>30m</code> — минуты, либо просто число часов):")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="free_view")

@router.callback_query(F.data == "ev_setup_lucky_hour")
async def ev_setup_lucky_hour(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🍀 <b>Ивент: Счастливый Час</b>\n\nВведите время действия ивента (например: <code>2h</code> — часы, <code>30m</code> — минуты, либо просто число часов):")
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
    await message.answer("⏳ Шаг 2: Введите время действия скидок (например: <code>2h</code> — часы, <code>30m</code> — минуты, либо просто число часов):")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="discount")

@router.message(AdminStates.event_hours)
async def process_event_hours(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    parsed = parse_duration_input(text)
    if not parsed:
        return await message.answer("❌ Некорректный формат. Введите, например: <code>2h</code> (часы), <code>30m</code> (минуты) или просто число часов:")
        
    delta, duration_label = parsed
    data = await state.get_data()
    etype = data.get("event_type")
    await state.clear()
    until_time = (datetime.now() + delta).isoformat()
    
    if etype == "x2":
        await set_setting("global_x2_until", until_time)
        await message.answer(f"✅ Глобальный ивент запущен!")
        asyncio.create_task(broadcast_event_start("🚀 ДВОЙНЫЕ НАГРАДЫ ЗА ДРУЗЕЙ (х2)", "С этого момента за каждого приглашенного реферала абсолютно все пользователи получают двойную выплату алмазов!", duration_label))
    elif etype == "discount":
        pct = data.get("discount_pct", 30)
        await set_setting("global_discount_percent", str(pct))
        await set_setting("global_discount_until", until_time)
        await message.answer(f"✅ Ивент Скидки -{pct}% успешно запущен!")
        asyncio.create_task(broadcast_event_start(f"📉 ШОК-СКИДКИ В МАГАЗИНЕ (-{pct}%)", f"Цены на способности, улучшения и покупку алмазов за Звезды снижены на {pct}%!", duration_label))
    elif etype == "x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await message.answer(f"✅ Ивент Х3 запущен!")
        asyncio.create_task(broadcast_event_start("⚡️ АЛМАЗНЫЙ ЛИВЕНЬ (Х3 К ПОКУПКАМ)", "Внимание! Любая покупка алмазов через Telegram Stars увеличивается в 3 раза!", duration_label))
    elif etype == "free_view":
        await set_setting("global_free_view_until", until_time)
        await message.answer(f"✅ Ивент Бесплатный Просмотр запущен!")
        asyncio.create_task(broadcast_event_start("🆓 АТТРАКЦИОН НЕВИДАННОЙ ЩЕДРОСТИ (0 💎)", "Администрация открыла бесплатный просмотр всех видео и фото для всех пользователей!", duration_label))
    elif etype == "lucky_hour":
        await set_setting("global_lucky_hour_until", until_time)
        await message.answer(f"✅ Ивент Счастливый Час запущен!")
        asyncio.create_task(broadcast_event_start("🍀 СЧАСТЛИВЫЙ ЧАС (+2 💎 ЗА АКТИВНОСТЬ)", "Невероятный бонус! Просматривайте медиа прямо сейчас и вместо списания алмазов получайте +2 💎 прямо на баланс!", duration_label))

@router.callback_query(F.data == "ev_setup_giveaway")
async def ev_setup_giveaway(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🎁 <b>Ивент: Раздача Алмазов</b>\n\nВведите количество алмазов для <b>КАЖДОГО</b> активного подписанного пользователя:")
    await state.set_state(AdminStates.event_giveaway)

@router.message(AdminStates.event_giveaway)
async def process_event_giveaway(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.text.strip().isdigit(): return await message.answer("❌ Введите целое число:")
    amount = int(message.text.strip())
    await state.clear()
    
    msg = await message.answer("⏳ Проверяю подписки и начисляю алмазы активным пользователям...")

    if not GLOBAL_BOTS_POOL:
        return await msg.edit_text("❌ Нет активных ботов для проверки подписок.")

    bot_worker = GLOBAL_BOTS_POOL[0]
    async with db.execute("SELECT user_id FROM users") as cur:
        users = await cur.fetchall()

    given = 0
    for (uid,) in users:
        try:
            if await check_subscription(uid, bot_worker):
                await add_diamonds(uid, float(amount))
                given += 1
        except Exception:
            continue

    await msg.edit_text(f"✅ Раздача завершена! Начислено по +{amount} 💎 для {given} активных подписанных пользователей.")
    asyncio.create_task(broadcast_event_start("🎁 МГНОВЕННАЯ СУПЕР-РАЗДАЧА", f"Администрация зачислила на баланс активным подписанным пользователям бота по <b>+{amount} алмазов</b>!", None))

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

# ========================= СИСТЕМНЫЕ ФУНКЦИИ =========================

async def delete_old_videos():
    while True:
        await asyncio.sleep(30)
        try:
            async with db.execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (datetime.now().isoformat(),)) as cur: 
                rows = await cur.fetchall()
            if rows and GLOBAL_BOTS_POOL:
                main_bot = GLOBAL_BOTS_POOL[0]
                for mid, cid in rows:
                    try: 
                        await main_bot.delete_message(cid, mid)
                    except Exception: 
                        pass
                    await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (mid, cid))
                await db.commit()
        except Exception: 
            pass

@router.callback_query(F.data == "admin_delete_all_promos")
async def admin_delete_all_promos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)
    
    try:
        async with db.execute("SELECT COUNT(*) FROM promo_codes") as cur:
            count = (await cur.fetchone())[0]
        
        await db.execute("DELETE FROM promo_codes")
        await db.execute("DELETE FROM promo_activations")
        await db.commit()
        
        await callback.answer(f"✅ Удалено {count} промокодов!", show_alert=True)
        await callback.message.edit_text("🗑 <b>Все промокоды успешно удалены.</b>", reply_markup=InlineKeyboardBuilder().button(text="◀️ В админку", callback_data="admin_enter").as_markup())
    except Exception as e:
        logging.error(f"Ошибка удаления всех промо: {e}")
        await callback.answer("⚠️ Ошибка при очистке.", show_alert=True)


@router.callback_query(F.data == "admin_toggle_maintenance")
async def admin_toggle_maintenance(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)
    
    current = await is_maintenance_mode()
    new_state = "false" if current else "true"
    await set_setting("maintenance_mode", new_state)
    
    status = "✅ ВКЛЮЧЕН" if new_state == "true" else "❌ ВЫКЛЮЧЕН"
    await callback.answer(f"Техработы: {status}", show_alert=True)
    
    # Обновляем текст, чтобы избежать ошибки "message is not modified"
    await callback.message.edit_text(
        f"🛠 <b>Административная Панель</b>\n\n"
        f"Технические работы: <b>{status}</b>",
        reply_markup=admin_menu()
    )

# ========================= ЗАБАНЕННЫЕ ПОЛЬЗОВАТЕЛИ =========================

@router.callback_query(F.data == "admin_banned_list")
async def admin_banned_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    now_ts = int(time.time())
    async with db.execute(
        "SELECT user_id, first_name, is_banned, banned_until FROM users WHERE is_banned = 1 OR banned_until > ? ORDER BY user_id LIMIT 30",
        (now_ts,)
    ) as cur:
        rows = await cur.fetchall()

    kb = InlineKeyboardBuilder()
    if not rows:
        text = "🚫 <b>Забаненных пользователей нет.</b>"
    else:
        text = "🚫 <b>Забаненные пользователи</b> (до 30 записей):\n\nНажмите на кнопку, чтобы разбанить.\n\n"
        for uid, fname, is_banned_val, banned_until_val in rows:
            status = "⛔ навсегда" if is_banned_val == 1 else f"⏳ до {datetime.fromtimestamp(banned_until_val).strftime('%d.%m %H:%M')}"
            text += f"▪️ {fname} <code>({uid})</code> — {status}\n"
            kb.button(text=f"🔓 Разбанить {fname} ({uid})", callback_data=f"banlist_unban_{uid}")

    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("banlist_unban_"))
async def banlist_unban(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    uid = int(callback.data.replace("banlist_unban_", ""))
    await db.execute("UPDATE users SET is_banned = 0, banned_until = 0 WHERE user_id = ?", (uid,))
    await db.commit()
    await callback.answer("🔓 Пользователь разбанен!", show_alert=True)
    await admin_banned_list(callback)

# ========================= СПИСОК АДМИНОВ =========================

@router.callback_query(F.data == "admin_list_admins")
async def admin_list_admins(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    text = "👑 <b>Список администраторов бота:</b>\n\n"
    for aid in ADMIN_IDS:
        async with db.execute("SELECT username, first_name FROM users WHERE user_id = ?", (aid,)) as cur:
            row = await cur.fetchone()
        if row:
            uname, fname = row
            label = f"@{uname}" if uname else fname
        else:
            label = "не запускал бота"
        text += f"▪️ {label} — <code>{aid}</code>\n"

    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    await callback.answer()

# ========================= НАСТРОЙКИ ЭКОНОМИКИ =========================

ECONOMY_SETTINGS_MAP = {
    "eco_set_video_price": ("video_price", "Цена просмотра видео (в 💎)"),
    "eco_set_photo_price": ("photo_price", "Цена просмотра фото (в 💎)"),
    "eco_set_referral_reward": ("referral_reward", "Награда за реферала (в 💎)"),
    "eco_set_autoban_limit": ("auto_ban_limit", "Лимит алмазов для автобана (в 💎)"),
}

@router.callback_query(F.data == "admin_economy")
async def admin_economy_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    video_price = await get_setting("video_price")
    photo_price = await get_setting("photo_price")
    referral_reward = await get_setting("referral_reward")
    autoban_limit = await get_setting("auto_ban_limit")

    text = (
        f"⚙️ <b>Настройки экономики бота</b>\n\n"
        f"📺 Цена видео: <b>{video_price} 💎</b>\n"
        f"📸 Цена фото: <b>{photo_price} 💎</b>\n"
        f"👥 Награда за реферала: <b>{referral_reward} 💎</b>\n"
        f"🚫 Лимит автобана: <b>{autoban_limit} 💎</b>\n\n"
        f"Выберите параметр, чтобы изменить значение:"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"📺 Цена видео ({video_price} 💎)", callback_data="eco_set_video_price")
    kb.button(text=f"📸 Цена фото ({photo_price} 💎)", callback_data="eco_set_photo_price")
    kb.button(text=f"👥 Награда за реферала ({referral_reward} 💎)", callback_data="eco_set_referral_reward")
    kb.button(text=f"🚫 Лимит автобана ({autoban_limit} 💎)", callback_data="eco_set_autoban_limit")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.in_(set(ECONOMY_SETTINGS_MAP.keys())))
async def eco_set_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    key, label = ECONOMY_SETTINGS_MAP[callback.data]
    await state.update_data(economy_key=key, economy_label=label)
    await callback.message.edit_text(f"✍️ Введите новое значение для параметра:\n<b>{label}</b>")
    await state.set_state(AdminStates.economy_value)

@router.message(AdminStates.economy_value)
async def process_economy_value(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip().replace(",", ".")
    try:
        val = float(text)
        if val < 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректное положительное число:")

    data = await state.get_data()
    key = data.get("economy_key")
    label = data.get("economy_label", key)
    await state.clear()

    val_str = str(int(val)) if val == int(val) else str(val)
    await set_setting(key, val_str)
    await message.answer(f"✅ Параметр «{label}» обновлён: <b>{val_str}</b>", reply_markup=admin_menu())

# ========================= ЭКСПОРТ ПОЛЬЗОВАТЕЛЕЙ =========================

@router.callback_query(F.data == "admin_export_users")
async def admin_export_users(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)

    await callback.answer("⏳ Формирую файл экспорта...")
    try:
        async with db.execute(
            "SELECT user_id, username, first_name, diamonds, premium, is_banned, banned_until, referred_by FROM users"
        ) as cur:
            rows = await cur.fetchall()

        export_path = DATA_DIR / "export_users.csv"
        with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "first_name", "diamonds", "premium", "is_banned", "banned_until", "referred_by"])
            writer.writerows(rows)

        await bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(export_path),
            caption=f"📤 Экспорт пользователей ({len(rows)} записей)"
        )
    except Exception as e:
        logging.error(f"Ошибка экспорта пользователей: {e}")
        await callback.message.answer("⚠️ Не удалось сформировать экспорт.")



@router.callback_query(F.data == "cat_packs")
async def cat_packs(callback: CallbackQuery):
    text = "📦 <b>Паки</b>\n\nВыберите пак для предпросмотра:"
    
    kb = InlineKeyboardBuilder()
    for pid, pack in PACKS.items():
        kb.button(
            text=f"{pack['name']} — {pack['price']} ⭐", 
            callback_data=f"pack_preview_{pid}"
        )
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data.startswith("pack_preview_"))
async def pack_preview(callback: CallbackQuery):
    try:
        pack_id = int(callback.data.split("_")[-1])
        pack = PACKS.get(pack_id)
        if not pack:
            return await callback.answer("❌ Пак не найден", show_alert=True)

        folder = pack["folder"]
        if not folder.exists():
            return await callback.answer("❌ Папка пака не найдена!", show_alert=True)

        images = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.PNG"):
            images.extend(folder.glob(ext))

        if not images:
            return await callback.answer("❌ В паке нет изображений!", show_alert=True)

        preview = random.choice(images)
        caption = f"""
📦 <b>{pack['name']}</b>
💰 Цена: <b>{pack['price']} ⭐</b>

После оплаты сразу получишь ссылку на Mega.nz
        """.strip()

        kb = InlineKeyboardBuilder()
        kb.button(text=f"💎 Купить за {pack['price']} ⭐", callback_data=f"buy_pack_{pack_id}")
        kb.adjust(1)

        # Удаляем предыдущее сообщение с предпросмотром, чтобы не было нагромождения
        try:
            await callback.message.delete()
        except:
            pass

        await callback.message.answer_photo(
            photo=FSInputFile(preview),
            caption=caption,
            reply_markup=kb.as_markup()
        )
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)[:80]}", show_alert=True)

@router.callback_query(F.data.startswith("buy_pack_"))
async def buy_pack(callback: CallbackQuery, bot: Bot):
    pack_id = int(callback.data.split("_")[-1])
    pack = PACKS.get(pack_id)
    if not pack:
        return await callback.answer("❌ Пак не найден", show_alert=True)

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=pack["name"],
        description=f"Полный пак • {pack['price']} Stars",
        payload=f"pack_{pack_id}",
        currency="XTR",
        prices=[LabeledPrice(label=pack["name"], amount=pack["price"])]
    )
    await callback.answer("⏳ Переход к оплате...")
    
# ========================= ГЛАВНЫЙ ЗАПУСК =========================

async def main():
    await init_db()
    
    asyncio.create_task(delete_old_videos())
    
    print("🚀 Запуск пула мультиботов...")

    # Один Dispatcher на все боты
    dp = Dispatcher()
    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())
    dp.include_router(router)

    @dp.pre_checkout_query()
    async def pre_checkout_query_handler(query: PreCheckoutQuery):
        await query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def payment_success_handler(message: Message):
        payload = message.successful_payment.invoice_payload
        
        # === ПОКУПКА АЛМАЗОВ ===
        if payload.startswith("buy_diamonds:"):
            diamonds = int(payload.split(":")[1])
            if await is_event_active("global_x3_stars_until"):
                diamonds *= 3
            await add_diamonds(message.from_user.id, float(diamonds))
            x3_msg = " [⚡️ Сработал Ивент Х3!]" if await is_event_active("global_x3_stars_until") else ""
            await message.answer(f"🎉 <b>Оплата зачислена!</b> +<b>{diamonds}</b> 💎.{x3_msg}")

        # === СПОСОБНОСТИ ЗА ЗВЕЗДЫ ===
        elif payload == "ability_x2":
            await db.execute("UPDATE users SET x2_until = ? WHERE user_id = ?", ((datetime.now() + timedelta(hours=24)).isoformat(), message.from_user.id))
            await db.commit()
            await message.answer("🚀 <b>Буст х2 Рефералы активирован на 24 часа!</b>")

        elif payload == "ability_keep_videos":
            await db.execute("UPDATE users SET keep_videos = 1 WHERE user_id = ?", (message.from_user.id,))
            await db.commit()
            await message.answer("♾ <b>Видео теперь сохраняются навсегда!</b>")

        #======= ПОКУПКА ПАКОВ #2===============
         elif payload.startswith("buy_pack:"):  # ← ДОБАВИТЬ ВЕСЬ ЭТОТ БЛОК
        pack_id = int(payload.split(":")[1])
        async with db.execute("SELECT name, file_path FROM packs WHERE id = ?", (pack_id,)) as cur:
            pack = await cur.fetchone()
        
        if pack:
            name, file_path = pack
            try:
                await message.answer_document(
                    document=FSInputFile(file_path),
                    caption=f"🎁 <b>Спасибо за покупку пака «{name}»!</b>\n\nНаслаждайтесь контентом!"
                )
            except Exception as e:
                logging.error(f"Ошибка отправки файла пака: {e}")
                await message.answer("❌ Ошибка при отправке файла. Свяжитесь с администратором.")
        else:
            await message.answer("❌ Пак не найден в базе данных.")

        # === ПОКУПКА ПАКОВ ===
        elif payload.startswith("pack_"):
            try:
                pack_id = int(payload.split("_")[1])
                pack = PACKS.get(pack_id)
                if pack:
                    await message.answer(
                        f"🎉 <b>{pack['name']} успешно оплачен!</b>\n\n"
                        f"🔗 <b>Ссылка на полный пак:</b>\n"
                        f"{pack['mega_link']}\n\n"
                        f"💾 Сохраните ссылку — она постоянная.",
                        disable_web_page_preview=True,
                        reply_markup=await main_menu(message.from_user.id)
                    )
                else:
                    await message.answer("✅ Оплата прошла успешно!")
            except Exception:
                await message.answer("✅ Оплата прошла успешно!")

    for token in MAIN_TOKENS:
        try:
            print(f"📱 Запускаю бота с токеном: {token[:10]}...")
            bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await bot_instance.delete_webhook(drop_pending_updates=True)
            GLOBAL_BOTS_POOL.append(bot_instance)
            print(f"✅ Бот [{token.split(':')[0]}] добавлен в пул.")
        except Exception as e:
            print(f"❌ Ошибка запуска бота с токеном {token.split(':')[0]}: {e}")
            import traceback
            traceback.print_exc()

    print(f"🤖 Все боты активны. Всего ботов: {len(GLOBAL_BOTS_POOL)}")

    # Один поллинг сразу для всех ботов пула
    await dp.start_polling(*GLOBAL_BOTS_POOL, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Бот остановлен.")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
