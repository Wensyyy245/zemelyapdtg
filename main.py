import asyncio
import random
import os
import sys
import uuid
import time
import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
# После всех импортов добавьте:
from tokens_db import tokens_db

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

# ========================= НАСТРОЙКИ =========================

# МНОГО ГЛАВНЫХ БОТОВ - КАЖДЫЙ РАБОТАЕТ САМ ПО СЕБЕ
MAIN_BOT_TOKENS = [
    "8850923714:AAHbpaPvNlRY9Od7HLcfl5Iabd2kaE8KVY0",
    "8570482228:AAEcejQ7tilDewJNs6rSL3A3c8wCXtEB2Xw",
    "8693601845:AAFYjo4eWzZf_CosjKETLfvLmND7fNQGLyo",
    # ДОБАВЛЯЙТЕ СКОЛЬКО УГОДНО ТОКЕНОВ СЮДА
]

# ОДИН БОТ ДЛЯ ОПЛАТЫ
PAYMENT_BOT_TOKEN = "8611620522:AAHwdkqnaCIJPPY-pNVgtV63xarI9vrzidY"

# ГРУППА ДЛЯ ЛОГОВ (ЗАМЕНИТЕ НА ВАШ ID)
LOG_GROUP_ID = -5417151890  # <--- СЮДА ВСТАВЬТЕ ID ВАШЕЙ ГРУППЫ

# ОСТАЛЬНЫЕ НАСТРОЙКИ ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ
ADMIN_IDS = [8603534638, 8570452473, 8502341995, 8794011165]
# ... и т.д.

CHANNELS = [
    (-1003475196063, "Наш канал", "https://t.me/+JypFAG4wqgk0ZTEy"),
    ("@Zemlyankaaaaa", "Наш резерв", "https://t.me/Zemlyankaaaaa"),
    ("@PavelGiftsPG", "Спонсор", "https://t.me/PavelGiftsPG"),
]

EVENT_CHANNEL_ID = -1003475196063

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

# ========================= ПАКИ =========================
PACKS_DIR = DATA_DIR / "packs"
PACKS_DIR.mkdir(exist_ok=True)
PACKSZVEZDA = {
    1: {"name": "Пак Полины ШГШ", "price": 30, "folder": PACKS_DIR / "pack1", "mega_link": "https://mega.nz/folder/mbQCia4B#pLXxfYKpxKM0wRyd-29glQ"},
    2: {"name": "Пак Златы", "price": 30, "folder": PACKS_DIR / "pack2", "mega_link": "https://mega.nz/folder/uWJlHY5a#V3EJuxs6-gKM9ZJgZa3CwA"},
    3: {"name": "Пак Янги18", "price": 400, "folder": PACKS_DIR / "pack8", "mega_link": "https://mega.nz/folder/cVklTYSJ#znRJ19C6CvCgsN_lZj2ZEw"}
}

PROCHIEPAKI = {
    4: {"name": "Пак 1", "price": 150, "folder": PACKS_DIR / "pack3", "mega_link": "https://mega.nz/folder/SMNWEIoA#BZagaT85jJGc0kcO-N-F3A"},
    5: {"name": "Пак 2", "price": 250, "folder": PACKS_DIR / "pack4", "mega_link": "https://mega.nz/folder/kiF2nb6T#FXuuQqFbxyDybJq7qomvHA"},
    6: {"name": "Пак 3", "price": 300, "folder": PACKS_DIR / "pack5", "mega_link": "https://mega.nz/folder/rmIB0T5L#ZAnu_nFzEPhq4UgZrouaBw"},
    7: {"name": "Пак 4", "price": 500, "folder": PACKS_DIR / "pack7", "mega_link": "https://mega.nz/folder/eNc3kZgK#eRFNRIOAUiQrH5tREGBDHQ"}
}

for pack_dict in (PACKSZVEZDA, PROCHIEPAKI):
    for pack_data in pack_dict.values():
        pack_data["folder"].mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"
# ========================= ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =========================

db = None
MAIN_BOTS = {}          # token: bot_instance
ACTIVE_BOTS = {}
MIRROR_BOTS = {}   # token: username
PAYMENT_BOT_USERNAME = None
PAYMENT_BOT_INSTANCE = None
BOT_INSTANCES = {}      # для хранения ссылок на ботов

# ========================= ЛОГГЕР =========================

async def send_log(text: str, bot=None):
    """Отправляет лог в группу"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_text = f"[{timestamp}] {text}"
    print(log_text)
    
    if bot is None and MAIN_BOTS:
        bot = list(MAIN_BOTS.values())[0]
    
    if bot:
        try:
            await bot.send_message(LOG_GROUP_ID, f"📋 {log_text}")
        except Exception as e:
            print(f"Ошибка отправки лога: {e}")

async def log_bot_status():
    """Логирует статус всех ботов"""
    status_text = "🤖 <b>СТАТУС БОТОВ:</b>\n\n"
    for token, username in ACTIVE_BOTS.items():
        status_text += f"✅ @{username} — активен\n"
    
    status_text += f"\n👥 Всего ботов: <b>{len(ACTIVE_BOTS)}</b>\n"
    status_text += f"💳 Бот оплаты: @{PAYMENT_BOT_USERNAME or 'не запущен'}"
    
    bot = list(MAIN_BOTS.values())[0] if MAIN_BOTS else None
    if bot:
        try:
            await bot.send_message(LOG_GROUP_ID, status_text)
        except Exception as e:
            print(f"Ошибка логирования статуса: {e}")

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
    add_token = State()

class MirrorStates(StatesGroup):
    enter_token = State()
    confirm_create = State()

class GameStates(StatesGroup):
    choose_game = State()
    choose_bet = State()

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
            keep_videos INTEGER DEFAULT 0
        )
    """)

    # Миграции
    try:
        await db.execute("ALTER TABLE users ADD COLUMN banned_until INTEGER DEFAULT 0")
        await db.commit()
        print("✅ Миграция: добавлена колонка banned_until")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE users ADD COLUMN daily_reward_last TEXT DEFAULT NULL")
        await db.commit()
        print("✅ Добавлено поле daily_reward_last")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE users ADD COLUMN daily_won REAL DEFAULT 0")
        await db.commit()
        print("✅ Добавлено поле daily_won")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE users ADD COLUMN daily_reset_date TEXT DEFAULT NULL")
        await db.commit()
        print("✅ Добавлено поле daily_reset_date")
    except aiosqlite.OperationalError:
        pass

    try:
        await db.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT NULL")
        await db.commit()
        print("✅ Миграция: добавлена колонка username")
    except aiosqlite.OperationalError:
        pass

    # Таблица настроек
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Настройки по умолчанию
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

    # Таблица видео
    await db.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            file_id TEXT,
            message_id INTEGER,
            chat_id INTEGER,
            delete_at TEXT
        )
    """)

    # Таблица промокодов
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            creator_id INTEGER,
            reward INTEGER,
            uses_left INTEGER
        )
    """)

    # Таблица активаций промокодов
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_activations (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)

    # Таблица админ-паков
    await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price INTEGER,
            photo_path TEXT,
            file_path TEXT,
            created_at TEXT
        )
    """)

    # Таблица заказов для оплаты
    await db.execute("""
        CREATE TABLE IF NOT EXISTS payment_orders (
            payment_id TEXT PRIMARY KEY,
            claim_id TEXT UNIQUE,
            user_id INTEGER,
            item_type TEXT,
            item_data TEXT,
            stars_price INTEGER,
            bot_token TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            paid_at TEXT,
            claimed_at TEXT
        )
    """)

    # Таблица зеркал
    await db.execute("""
        CREATE TABLE IF NOT EXISTS mirrors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token TEXT,
            bot_username TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            activated_at TEXT,
            last_heartbeat TEXT
        )
    """)

    # Индексы для mirrors
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_user ON mirrors (user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_status ON mirrors (status)")

    # Таблица статуса ботов
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            token TEXT PRIMARY KEY,
            username TEXT,
            last_heartbeat TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    await db.commit()
    print("✅ База данных инициализирована")

# ========================= ХЕЛПЕРЫ =========================

async def get_setting(key: str) -> str:
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else "NULL"

# ========================= ЗЕРКАЛА =========================

async def get_user_mirrors(user_id: int) -> list:
    """Получает список зеркал пользователя"""
    async with db.execute(
        "SELECT id, bot_username, status, created_at, activated_at FROM mirrors WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ) as cur:
        return await cur.fetchall()

async def get_mirror_count(user_id: int) -> int:
    """Получает количество зеркал пользователя"""
    async with db.execute("SELECT COUNT(*) FROM mirrors WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0

async def create_mirror_record(user_id: int, token: str, username: str) -> int:
    """Создает запись о зеркале в БД"""
    cursor = await db.execute(
        "INSERT INTO mirrors (user_id, token, bot_username, status, created_at) VALUES (?, ?, ?, 'active', ?)",
        (user_id, token, username, datetime.now().isoformat())
    )
    await db.commit()
    return cursor.lastrowid

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

# ========================= СИСТЕМА ОПЛАТЫ ЧЕРЕЗ ОТДЕЛЬНОГО БОТА =========================
#
# Схема:
# 1. Главный бот создаёт запись заказа в общей таблице payment_orders (status='pending')
#    и даёт пользователю ссылку вида https://t.me/<PaymentBot>?start=pay_<payment_id>
# 2. Пользователь переходит по ссылке во второго бота. Второй бот проверяет заказ
#    в общей БД и выставляет РЕАЛЬНЫЙ инвойс Telegram Stars (answer_invoice).
# 3. Пользователь оплачивает. Второй бот получает successful_payment,
#    помечает заказ status='paid', генерирует claim_id и присылает ссылку вида
#    https://t.me/<MainBot>?start=claim_<claim_id>
# 4. Пользователь переходит по этой ссылке в главного бота. Главный бот проверяет
#    в БД, что заказ действительно оплачен и ещё не выдан, выдаёт товар и
#    помечает status='claimed'.
#
# Никакая выдача товара никогда не происходит по самому факту перехода по ссылке
# без реальной проверки статуса оплаты в БД.

async def create_payment_order(user_id: int, item_type: str, item_data: dict, stars_price: int) -> str:
    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    await db.execute(
        "INSERT INTO payment_orders (payment_id, user_id, item_type, item_data, stars_price, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (payment_id, user_id, item_type, json.dumps(item_data), stars_price, datetime.now().isoformat())
    )
    await db.commit()
    return payment_id

async def get_order(payment_id: str = None, claim_id: str = None):
    if payment_id:
        async with db.execute(
            "SELECT payment_id, claim_id, user_id, item_type, item_data, stars_price, status FROM payment_orders WHERE payment_id = ?",
            (payment_id,)
        ) as cur:
            row = await cur.fetchone()
    elif claim_id:
        async with db.execute(
            "SELECT payment_id, claim_id, user_id, item_type, item_data, stars_price, status FROM payment_orders WHERE claim_id = ?",
            (claim_id,)
        ) as cur:
            row = await cur.fetchone()
    else:
        return None
    if not row:
        return None
    return {
        "payment_id": row[0],
        "claim_id": row[1],
        "user_id": row[2],
        "item_type": row[3],
        "item_data": json.loads(row[4]) if row[4] else {},
        "stars_price": row[5],
        "status": row[6],
    }

async def generate_payment_link(user_id: int, item_type: str, item_data: dict, stars_price: int, bot_token: str = None) -> str:
    """Создаёт заказ и возвращает ссылку на бота оплаты"""
    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    
    # Сохраняем, из какого бота пришел запрос
    if bot_token is None:
        bot_token = list(MAIN_BOTS.keys())[0] if MAIN_BOTS else ""
    
    await db.execute(
        """INSERT INTO payment_orders 
           (payment_id, user_id, item_type, item_data, stars_price, bot_token, status, created_at) 
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (payment_id, user_id, item_type, json.dumps(item_data), stars_price, bot_token, datetime.now().isoformat())
    )
    await db.commit()
    
    # Чистим старые заказы
    cutoff = (datetime.now() - timedelta(hours=6)).isoformat()
    await db.execute("DELETE FROM payment_orders WHERE status = 'pending' AND created_at < ?", (cutoff,))
    await db.commit()
    
    return f"https://t.me/{PAYMENT_BOT_USERNAME}?start={payment_id}"

async def check_daily_reward(user_id: int) -> tuple:
    """Проверяет, можно ли получить ежедневную награду. Возвращает (можно_ли, осталось_секунд)"""
    async with db.execute("SELECT daily_reward_last FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    
    if not row or not row[0]:
        return True, 0
    
    last = datetime.fromisoformat(row[0])
    now = datetime.now()
    elapsed = (now - last).total_seconds()
    
    if elapsed >= 86400:
        return True, 0
    else:
        return False, int(86400 - elapsed)

async def process_payment(user_id: int, item_type: str, item_data: dict, main_bot: Bot):
    """Выдаёт товар после подтверждённой оплаты."""
    if item_type == "diamonds":
        diamonds = item_data['amount']
        if await is_event_active("global_x3_stars_until"):
            diamonds *= 3
        await add_diamonds(user_id, float(diamonds))
        x3_msg = " [⚡️ Х3 Ивент!]" if await is_event_active("global_x3_stars_until") else ""
        try:
            await main_bot.send_message(user_id, f"🎉 <b>Оплата зачислена!</b> +{diamonds} 💎{x3_msg}")
        except Exception:
            pass
    elif item_type == "ability_x2":
        await db.execute("UPDATE users SET x2_until = ? WHERE user_id = ?",
                        ((datetime.now() + timedelta(hours=24)).isoformat(), user_id))
        await db.commit()
        try:
            await main_bot.send_message(user_id, "🚀 <b>Буст х2 Рефералы активирован на 24 часа!</b>")
        except Exception:
            pass
    elif item_type == "ability_keep_videos":
        await db.execute("UPDATE users SET keep_videos = 1 WHERE user_id = ?", (user_id,))
        await db.commit()
        try:
            await main_bot.send_message(user_id, "♾ <b>Видео теперь сохраняются навсегда!</b>")
        except Exception:
            pass
    elif item_type == "mega_pack":
        pack = item_data
        try:
            await main_bot.send_message(
                user_id,
                f"🎉 <b>{pack['name']} успешно оплачен!</b>\n\n"
                f"🔗 <b>Ссылка на полный пак:</b>\n"
                f"{pack['mega_link']}\n\n"
                f"💾 Сохраните ссылку — она постоянная.",
                disable_web_page_preview=True
            )
        except Exception:
            pass
    elif item_type == "admin_pack":
        pack_id = item_data['pack_id']
        async with db.execute("SELECT name, file_path FROM admin_packs WHERE id = ?", (pack_id,)) as cur:
            pack = await cur.fetchone()
        if pack:
            name, file_path = pack
            try:
                await main_bot.send_document(
                    user_id,
                    document=FSInputFile(file_path),
                    caption=f"🎁 <b>Спасибо за покупку пака «{name}»!</b>"
                )
            except Exception as e:
                logging.error(f"Ошибка отправки файла: {e}")

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
                    "Следите за новостями в нашем канале: https://t.me/+JypFAG4wqgk0ZTEy"
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

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Админы обходят проверку
        if user.id in ADMIN_IDS:
            return await handler(event, data)

        bot = data.get("bot")

        if not await check_subscription(user.id, bot):
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

            sub_text = "👋 Для работы бота подпишись на каналы спонсоров:"

            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("❌ Подпишись на все каналы!", show_alert=True)
                    if event.message:
                        await event.message.edit_text(sub_text, reply_markup=kb.as_markup())
                except Exception:
                    pass
            elif isinstance(event, Message):
                try:
                    await event.answer(sub_text, reply_markup=kb.as_markup())
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
    kb.button(text="🎁 Ежедневная награда", callback_data="daily_reward")
    kb.button(text="🛒 Магазин 💰", callback_data="shop_main")
    kb.button(text="🔄 Зеркала", callback_data="mirror_menu")
    kb.button(text="🎟 Промокоды", callback_data="promo_menu")
    kb.button(text="🎮 Казино (Тест)", callback_data="casino_menu")
    kb.button(text="🏆 Таблица Лидеров", callback_data="leaderboard")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
    if user_id in ADMIN_IDS:
        kb.button(text="⚙️ Admin Panel", callback_data="admin_enter")
    kb.adjust(1)
    
    # ДОБАВЛЯЕМ ПРОВЕРКУ ЕЖЕДНЕВНОЙ НАГРАДЫ
    can_claim, remaining = await check_daily_reward(user_id)
    if not can_claim:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        kb.button(text=f"⏳ {hours}ч {minutes}м", callback_data="daily_reward_disabled")
    
    return kb.as_markup()  # <--- return должен быть здесь!

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
    kb.button(text="🚫 Забаненные пользователи", callback_data="admin_banned_list")
    kb.button(text="👑 Список админов", callback_data="admin_list_admins")
    kb.button(text="🔑 Токены для зеркал", callback_data="admin_tokens")
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

def casino_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Кости", callback_data="game_dice")
    kb.button(text="⚽️ Футбол", callback_data="game_football")
    kb.button(text="🎯 Дартс", callback_data="game_darts")
    kb.button(text="🏀 Баскетбол", callback_data="game_basket")
    kb.button(text="🎰 Слоты", callback_data="game_slots")
    kb.button(text="🎳 Боулинг", callback_data="game_bowling")
    kb.button(text="◀️ В главное меню", callback_data="back_main")
    kb.adjust(2)
    return kb.as_markup()


def bet_keyboard(game_callback: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="1 💎", callback_data=f"bet_{game_callback}_1")
    kb.button(text="3 💎", callback_data=f"bet_{game_callback}_3")
    kb.button(text="5 💎", callback_data=f"bet_{game_callback}_5")
    kb.button(text="◀️ Назад", callback_data="casino_menu")
    kb.adjust(3)
    return kb.as_markup()

# ========================= ХЕНДЛЕРЫ (ГЛАВНЫЙ БОТ) =========================

router = Router()

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name
    username = message.from_user.username
    args = message.text.split()
    
    # Обработка получения товара по claim
    if len(args) > 1 and args[1].startswith("claim_"):
        claim_id = args[1][len("claim_"):]
        async with db.execute(
            "SELECT user_id, item_type, item_data, status, payment_id FROM payment_orders WHERE claim_id = ?",
            (claim_id,)
        ) as cur:
            order = await cur.fetchone()
        
        if not order:
            return await message.answer("❌ Ссылка недействительна.")
        
        uid, item_type, item_data, status, payment_id = order
        if uid != user_id:
            return await message.answer("❌ Не ваша ссылка.")
        if status == "claimed":
            return await message.answer("ℹ️ Товар уже получен.")
        if status != "paid":
            return await message.answer("❌ Оплата не подтверждена.")
        
        await process_payment(user_id, item_type, json.loads(item_data), bot)
        await db.execute(
            "UPDATE payment_orders SET status = 'claimed', claimed_at = ? WHERE payment_id = ?",
            (datetime.now().isoformat(), payment_id)
        )
        await db.commit()
        
        udata = await get_user_data(user_id, name, username)
        return await message.answer(
            f"✅ Товар выдан!\n\n💰 Баланс: {udata['diamonds']} 💎",
            reply_markup=await main_menu(user_id)
        )
    
    # Реферальная ссылка
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cur:
                existing = await cur.fetchone()
            if not existing:
                await db.execute(
                    "INSERT INTO users (user_id, first_name, username, diamonds, referred_by) VALUES (?, ?, ?, 8.0, ?)",
                    (user_id, name, username, referrer_id)
                )
                await db.commit()
    
    udata = await get_user_data(user_id, name, username)
    
    # Проверка подписки
    if not await check_subscription(user_id, bot):
        kb = InlineKeyboardBuilder()
        for channel_data in CHANNELS:
            _, ch_name, ch_url = channel_data
            kb.button(text=ch_name, url=ch_url)
        kb.button(text="✅ Я подписался", callback_data="check_sub")
        kb.adjust(1)
        return await message.answer("👋 Подпишись на каналы:", reply_markup=kb.as_markup())
    
    # НАЧИСЛЕНИЕ РЕФЕРАЛЬНОЙ НАГРАДЫ (ИСПРАВЛЕНО)
    if udata["referred_by"] and udata["is_referral_rewarded"] == 0:
        ref_id = udata["referred_by"]
        try:
            base_reward = float(await get_setting("referral_reward"))
        except:
            base_reward = 4.0
        
        # Проверяем глобальный x2 ивент
        if await is_event_active("global_x2_until"):
            base_reward *= 2
        
        # Проверяем персональный x2 буст у реферала
        async with db.execute("SELECT x2_until FROM users WHERE user_id = ?", (ref_id,)) as cur:
            ref_x2 = await cur.fetchone()
        if ref_x2 and ref_x2[0] and datetime.fromisoformat(ref_x2[0]) > datetime.now():
            base_reward *= 2
        
        await add_diamonds(ref_id, base_reward)
        await db.execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
        await db.commit()
        
        # Отправляем уведомление рефералу
        try:
            await bot.send_message(ref_id, f"🎉 Твой реферал {name} активировался! Получено +{base_reward} 💎")
        except:
            pass
        
        # Логируем
        await send_log(f"👥 Реферал {name} (ID: {user_id}) привел {ref_id} -> +{base_reward} 💎")
    
    await message.answer(
        f"👋 Добро пожаловать!\n\n💰 Баланс: {udata['diamonds']} 💎",
        reply_markup=await main_menu(user_id)
    )
    
    await send_log(f"👤 {name} (ID: {user_id}) запустил бота @{(await bot.get_me()).username}")

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

    msg = await bot.send_video(   # ← было с неправильным отступом
        chat_id=user_id,
        video=FSInputFile(random.choice(videos)),
        caption=cap,
        has_spoiler=True
    )
    if not is_forever:
        await db.execute(
            "INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)",
            ("", msg.message_id, user_id, (datetime.now() + timedelta(minutes=10)).isoformat())
        )
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

    if is_lucky: await add_diamonds(user_id, 2.0)   # ← исправлен отступ
    photo_msg = await bot.send_photo(
        chat_id=user_id,
        photo=FSInputFile(random.choice(photos)),
        caption="🍀 Счастливый час: +2 💎!" if is_lucky else None,
        has_spoiler=True
    )
    is_forever_photo = (premium == 2)
    if not is_forever_photo:
        await db.execute(
            "INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)",
            ("", photo_msg.message_id, user_id, (datetime.now() + timedelta(minutes=10)).isoformat())
        )
        await db.commit()
    await callback.answer()

@router.callback_query(F.data == "mirror_menu")
async def mirror_menu(callback: CallbackQuery):
    """Меню управления зеркалами"""
    user_id = callback.from_user.id
    mirrors = await get_user_mirrors(user_id)
    mirror_count = await get_mirror_count(user_id)
    
    stats = await tokens_db.get_stats()
    
    kb = InlineKeyboardBuilder()
    if stats['available'] > 0:
        kb.button(text=f"➕ Создать зеркало (+20 💎)", callback_data="create_mirror")
    else:
        kb.button(text="⏳ Нет доступных токенов", callback_data="no_tokens")
    kb.button(text="📋 Мои зеркала", callback_data="my_mirrors")
    
    if mirrors:
        kb.button(text="🔄 Перезапустить зеркала", callback_data="restart_mirrors")
    
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    
    text = (
        "🔄 <b>Управление зеркалами</b>\n\n"
        f"📊 Всего зеркал: <b>{mirror_count}</b>\n"
        f"🟢 Доступно токенов: <b>{stats['available']}</b>\n\n"
        "💡 <b>Инструкция:</b>\n"
        "1. Создайте бота в @BotFather\n"
        "2. Скопируйте токен\n"
        "3. Нажмите 'Создать зеркало'\n"
        "4. Вставьте токен\n"
        "5. Получите +20 💎!\n\n"
        "⚠️ Бот-зеркало будет работать сразу после создания!"
    )
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "create_mirror")
async def create_mirror_start(callback: CallbackQuery, state: FSMContext):
    """Начало создания зеркала"""
    user_id = callback.from_user.id
    
    # Проверяем, есть ли доступные токены
    token_data = await tokens_db.get_available_token()
    if not token_data:
        return await callback.answer(
            "❌ Нет доступных токенов! Администратор добавит токены позже.",
            show_alert=True
        )
    
    # Проверяем лимит (максимум 5 зеркал)
    mirror_count = await get_mirror_count(user_id)
    if mirror_count >= 5:
        return await callback.answer(
            "❌ Максимум 5 зеркал на пользователя!",
            show_alert=True
        )
    
    await callback.message.edit_text(
        "🔑 <b>Создание зеркала</b>\n\n"
        "1. Перейдите в @BotFather\n"
        "2. Создайте нового бота командой /newbot\n"
        "3. Скопируйте полученный токен\n"
        "4. Вставьте токен сюда (отправьте текстом):\n\n"
        "⚠️ Токен должен быть в формате:\n"
        "<code>1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>"
    )
    await state.set_state(MirrorStates.enter_token)

@router.message(MirrorStates.enter_token)
async def process_mirror_token(message: Message, state: FSMContext, bot: Bot):
    """Обработка введенного токена"""
    user_id = message.from_user.id
    token = message.text.strip()
    
    # Валидация токена
    if ':' not in token or not token.split(':')[0].isdigit():
        return await message.answer(
            "❌ Неверный формат токена!\n\n"
            "Токен должен быть в формате:\n"
            "<code>1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>"
        )
    
    await state.clear()
    
    # Проверяем, есть ли токен в базе
    existing = await tokens_db.get_token_by_username(token)
    if existing:
        return await message.answer("❌ Этот токен уже используется!")
    
    # Проверяем токен через Telegram API
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        username = me.username
        await test_bot.session.close()
    except Exception as e:
        return await message.answer(
            f"❌ Не удалось подключиться к боту!\nОшибка: {str(e)[:100]}"
        )
    
    # Проверяем лимит
    mirror_count = await get_mirror_count(user_id)
    if mirror_count >= 5:
        return await message.answer("❌ Максимум 5 зеркал на пользователя!")
    
    # Сохраняем токен в базу токенов
    await tokens_db.add_token(token, username, user_id)
    
    # Создаем зеркало
    mirror_id = await create_mirror_record(user_id, token, username)
    
    # Помечаем токен как использованный
    await tokens_db.use_token(token, user_id, mirror_id)
    
    # Запускаем бота-зеркало
    success = await start_mirror_bot(token, username)
    
    if success:
        await tokens_db.update_token_status(token, 'used', 1)
        await db.execute(
            "UPDATE mirrors SET status = 'active', activated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), mirror_id)
        )
        await db.commit()
        
        # Начисляем награду
        await add_diamonds(user_id, 20.0)
        
        await message.answer(
            f"✅ <b>Зеркало успешно создано!</b>\n\n"
            f"🤖 Бот: @{username}\n"
            f"💎 Награда: +20 💎\n\n"
            f"📊 Всего зеркал: {mirror_count + 1}\n"
            f"🔗 <code>https://t.me/{username}</code>",
            reply_markup=InlineKeyboardBuilder()
                .button(text="🔗 Перейти к боту", url=f"https://t.me/{username}")
                .button(text="◀️ В меню зеркал", callback_data="mirror_menu")
                .adjust(1)
                .as_markup()
        )
        
        await send_log(f"🔄 Пользователь создал зеркало @{username} (+20 💎)")
    else:
        await db.execute(
            "UPDATE mirrors SET status = 'inactive' WHERE id = ?",
            (mirror_id,)
        )
        await db.commit()
        await tokens_db.update_token_status(token, 'banned', 0)
        await message.answer(
            "❌ Не удалось запустить бота-зеркало!\n"
            "Обратитесь в поддержку: @zemelya_admin"
        )

@router.callback_query(F.data == "my_mirrors")
async def my_mirrors(callback: CallbackQuery):
    """Список зеркал пользователя"""
    user_id = callback.from_user.id
    mirrors = await get_user_mirrors(user_id)
    
    if not mirrors:
        return await callback.answer("У вас нет зеркал!", show_alert=True)
    
    kb = InlineKeyboardBuilder()
    text = "📋 <b>Ваши зеркала:</b>\n\n"
    
    for mirror_id, username, status, created_at, activated_at in mirrors:
        status_emoji = {'pending': '⏳', 'active': '✅', 'inactive': '❌'}.get(status, '❓')
        status_text = {'pending': 'Создается...', 'active': 'Работает', 'inactive': 'Неактивен'}.get(status, 'Неизвестно')
        
        created = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
        text += f"{status_emoji} @{username} — {status_text}\n"
        text += f"   🕐 Создан: {created}\n\n"
        
        if status == 'active':
            kb.button(text=f"🔗 @{username}", url=f"https://t.me/{username}")
    
    kb.button(text="🔄 Обновить", callback_data="my_mirrors")
    kb.button(text="◀️ Назад", callback_data="mirror_menu")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data == "no_tokens")
async def no_tokens(callback: CallbackQuery):
    await callback.answer("⏳ Нет доступных токенов для создания зеркал!", show_alert=True)

@router.callback_query(F.data == "daily_reward")
async def daily_reward(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    can_claim, remaining = await check_daily_reward(user_id)
    if not can_claim:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return await callback.answer(f"⏳ Через {hours}ч {minutes}м", show_alert=True)
    
    reward = random.randint(2, 8)
    await add_diamonds(user_id, reward)
    await db.execute(
        "UPDATE users SET daily_reward_last = ? WHERE user_id = ?",
        (datetime.now().isoformat(), user_id)
    )
    await db.commit()
    
    await callback.answer(f"🎉 +{reward} 💎", show_alert=True)
    await callback.message.edit_text(
        f"🎁 Ежедневная награда!\n\n+{reward} 💎",
        reply_markup=await main_menu(user_id)
    )
    await send_log(f"👤 {callback.from_user.first_name} получил +{reward} 💎")

@router.callback_query(F.data == "daily_reward_disabled")
async def daily_reward_disabled(callback: CallbackQuery):
    await callback.answer("⏳ Подождите до следующей награды!", show_alert=True)

@router.callback_query(F.data == "admin_tokens")
async def admin_tokens(callback: CallbackQuery):
    """Админ-панель управления токенами"""
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)
    
    stats = await tokens_db.get_stats()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить токены", callback_data="admin_add_tokens")
    kb.button(text="📊 Все токены", callback_data="admin_view_tokens")
    kb.button(text="◀️ Назад в админку", callback_data="admin_enter")
    kb.adjust(1)
    
    await callback.message.edit_text(
        f"🔑 <b>Управление токенами</b>\n\n"
        f"📊 Статистика:\n"
        f"  • Всего: <b>{stats['total']}</b>\n"
        f"  • Доступно: <b>{stats['available']}</b>\n"
        f"  • Использовано: <b>{stats['used']}</b>\n"
        f"  • Активно: <b>{stats['active']}</b>\n"
        f"  • Забанено: <b>{stats['banned']}</b>",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "admin_add_tokens")
async def admin_add_tokens(callback: CallbackQuery, state: FSMContext):
    """Добавление новых токенов"""
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)
    
    await callback.message.edit_text(
        "🔑 <b>Добавление токенов</b>\n\n"
        "Введите токены, каждый с новой строки:\n\n"
        "Пример:\n"
        "<code>1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>\n"
        "<code>1234567891:ABCdefGHIjklMNOpqrsTUVwxya</code>"
    )
    await state.set_state(AdminStates.add_token)

@router.message(AdminStates.add_token)
async def process_add_tokens(message: Message, state: FSMContext):
    """Обработка добавления токенов"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    tokens = [t.strip() for t in message.text.split('\n') if t.strip()]
    added = 0
    errors = 0
    
    for token in tokens:
        try:
            # Проверяем токен
            test_bot = Bot(token=token)
            me = await test_bot.get_me()
            username = me.username
            await test_bot.session.close()
            
            # Сохраняем в базу токенов
            if await tokens_db.add_token(token, username, message.from_user.id):
                added += 1
                await send_log(f"🔑 Добавлен токен @{username}")
            else:
                errors += 1
        except Exception as e:
            errors += 1
            await send_log(f"❌ Ошибка добавления токена: {e}")
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Токены добавлены!</b>\n\n"
        f"➕ Добавлено: <b>{added}</b>\n"
        f"❌ Ошибок: <b>{errors}</b>",
        reply_markup=InlineKeyboardBuilder()
            .button(text="◀️ Назад", callback_data="admin_tokens")
            .as_markup()
    )

@router.callback_query(F.data == "admin_view_tokens")
async def admin_view_tokens(callback: CallbackQuery):
    """Просмотр всех токенов"""
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет прав!", show_alert=True)
    
    tokens = await tokens_db.get_all_tokens()
    
    if not tokens:
        return await callback.answer("Нет токенов в базе!", show_alert=True)
    
    kb = InlineKeyboardBuilder()
    text = "📋 <b>Все токены:</b>\n\n"
    
    for token_id, token, username, status, user_id, is_active in tokens[:20]:
        status_emoji = {
            'available': '🟢',
            'used': '🔵',
            'banned': '🔴'
        }.get(status, '⚪')
        
        active_text = "✅" if is_active else "❌"
        text += f"{status_emoji} @{username} — {status} {active_text}\n"
        if user_id:
            text += f"   👤 ID: {user_id}\n"
        text += f"   🆔 {token[:20]}...\n\n"
    
    if len(tokens) > 20:
        text += f"\n... и еще {len(tokens) - 20} токенов"
    
    kb.button(text="◀️ Назад", callback_data="admin_tokens")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

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

@router.message(MirrorStates.enter_token)
async def process_mirror_token(message: Message, state: FSMContext, bot: Bot):
    """Обработка введенного токена"""
    user_id = message.from_user.id
    token = message.text.strip()
    
    if ':' not in token:
        return await message.answer("❌ Неверный формат токена! Попробуйте снова.")
    
    await state.clear()
    
    # Проверяем токен
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        username = me.username
        await test_bot.session.close()
    except Exception as e:
        return await message.answer(f"❌ Ошибка: {str(e)[:100]}")
    
    # Проверяем лимит
    mirror_count = await get_mirror_count(user_id)
    if mirror_count >= 5:
        return await message.answer("❌ Максимум 5 зеркал!")
    
    # Сохраняем токен в БД
    await tokens_db.add_token(token, username, user_id)
    await tokens_db.use_token(token, user_id)
    
    # Создаем зеркало
    cursor = await db.execute(
        "INSERT INTO mirrors (user_id, token, bot_username, status, created_at) VALUES (?, ?, ?, 'active', ?)",
        (user_id, token, username, datetime.now().isoformat())
    )
    await db.commit()
    mirror_id = cursor.lastrowid
    
    # Запускаем бота-зеркало
    success = await start_mirror_bot(token, username)
    
    if success:
        await tokens_db.update_token_status(token, 'used', 1)
        await db.execute(
            "UPDATE mirrors SET status = 'active', activated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), mirror_id)
        )
        await db.commit()
        
        # Начисляем награду
        await add_diamonds(user_id, 20.0)
        
        await message.answer(
            f"✅ <b>Зеркало создано!</b>\n\n"
            f"🤖 @{username}\n"
            f"💎 +20 💎\n\n"
            f"🔗 <code>https://t.me/{username}</code>",
            reply_markup=InlineKeyboardBuilder()
                .button(text="🔗 Перейти", url=f"https://t.me/{username}")
                .button(text="◀️ Назад", callback_data="mirror_menu")
                .adjust(1)
                .as_markup()
        )
        
        await send_log(f"🔄 Пользователь создал зеркало @{username} (+20 💎)")
    else:
        await db.execute("UPDATE mirrors SET status = 'inactive' WHERE id = ?", (mirror_id,))
        await db.commit()
        await message.answer("❌ Ошибка запуска зеркала!")

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

bot_token = list(MAIN_BOTS.keys())[list(MAIN_BOTS.values()).index(bot)]  # получаем токен текущего бота
payment_link = await generate_payment_link(
    user_id, 
    "diamonds", 
    {"amount": diamonds}, 
    stars_price,
    bot_token  # <--- передаем токен
)

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_diamonds")
    kb.adjust(1)

    await message.answer(
        f"💎 <b>Покупка {diamonds} алмазов</b>\n\n"
        f"💰 Сумма: {stars_price} ⭐️\n\n"
        f"⚠️ Оплата производится через отдельного бота.\n"
        f"Нажмите кнопку ниже для перехода:",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data.startswith("stars_"))
async def buy_diamonds_stars(callback: CallbackQuery):
    rates = {"stars_100": (100, 80), "stars_250": (250, 200), "stars_500": (500, 400)}
    if callback.data in rates:
        diamonds, stars_price = rates[callback.data]
        if await is_event_active("global_discount_until"):
            pct = int(await get_setting("global_discount_percent"))
            stars_price = max(1, int(stars_price * (1 - pct / 100)))

        payment_link = await generate_payment_link(
            callback.from_user.id,
            "diamonds",
            {'amount': diamonds},
            stars_price
        )

        kb = InlineKeyboardBuilder()
        kb.button(text="💳 Перейти к оплате", url=payment_link)
        kb.button(text="◀️ Назад", callback_data="cat_diamonds")
        kb.adjust(1)

        await callback.message.edit_text(
            f"💎 <b>Покупка {diamonds} алмазов</b>\n\n"
            f"💰 Сумма: {stars_price} ⭐️\n\n"
            f"⚠️ Оплата производится через отдельного бота.\n"
            f"Нажмите кнопку ниже для перехода:",
            reply_markup=kb.as_markup()
        )
        await callback.answer()

@router.callback_query(F.data == "cat_abilities")
async def cat_abilities(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("⚡ <b>Магазин способностей (оплата Telegram Stars)</b>", reply_markup=shop_abilities_kb(discount_pct=pct, timer=timer))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = max(1, int(50 * (1 - pct / 100)))

    payment_link = await generate_payment_link(
        callback.from_user.id,
        "ability_x2",
        {},
        price
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_abilities")
    kb.adjust(1)

    await callback.message.edit_text(
        f"🚀 <b>Буст х2 Рефералы (24ч)</b>\n\n"
        f"💰 Сумма: {price} ⭐️\n\n"
        f"⚠️ Оплата через отдельного бота.\n"
        f"Нажмите кнопку ниже:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    if udata["keep_videos"] == 1 or udata["premium"] == 2:
        return await callback.answer("Уже активно!", show_alert=True)

    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = max(1, int(150 * (1 - pct / 100)))

    payment_link = await generate_payment_link(
        user_id,
        "ability_keep_videos",
        {},
        price
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_abilities")
    kb.adjust(1)

    await callback.message.edit_text(
        f"♾ <b>Видео навсегда</b>\n\n"
        f"💰 Сумма: {price} ⭐️\n\n"
        f"⚠️ Оплата через отдельного бота.\n"
        f"Нажмите кнопку ниже:",
        reply_markup=kb.as_markup()
    )
    await callback.answer()

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

    admin_placeholders = ",".join("?" * len(ADMIN_IDS))
    params = tuple(ADMIN_IDS)

    async with db.execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]

    async with db.execute(
        f"SELECT COALESCE(SUM(diamonds), 0) FROM users WHERE diamonds >= 0 AND user_id NOT IN ({admin_placeholders})",
        params
    ) as cur:
        positive_diamonds = (await cur.fetchone())[0]

    async with db.execute(
        f"SELECT COALESCE(SUM(diamonds), 0) FROM users WHERE diamonds < 0 AND user_id NOT IN ({admin_placeholders})",
        params
    ) as cur:
        negative_diamonds = (await cur.fetchone())[0]

    async with db.execute(
        "SELECT COUNT(*) FROM users WHERE is_banned = 1 OR banned_until > ?",
        (int(time.time()),)
    ) as cur:
        banned_count = (await cur.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM users WHERE premium > 0") as cur:
        premium_count = (await cur.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM promo_codes") as cur:
        promo_count = (await cur.fetchone())[0]

    async with db.execute("SELECT COUNT(*) FROM admin_packs") as cur:
        packs_count = (await cur.fetchone())[0]

    async with db.execute(
        f"""SELECT first_name, diamonds
            FROM users
            WHERE diamonds >= 0
              AND user_id NOT IN ({admin_placeholders})
            ORDER BY diamonds DESC LIMIT 10""",
        params
    ) as cur:
        top_positive = await cur.fetchall()

    async with db.execute(
        f"""SELECT first_name, diamonds
            FROM users
            WHERE diamonds < 0
              AND user_id NOT IN ({admin_placeholders})
            ORDER BY diamonds ASC LIMIT 10""",
        params
    ) as cur:
        top_negative = await cur.fetchall()

    x2_active = "✅ Активен" if await is_event_active("global_x2_until") else "❌ Выключен"
    is_disc = await is_event_active("global_discount_until")
    pct = await get_setting("global_discount_percent")
    disc_active = f"✅ Активен (-{pct}%)" if is_disc else "❌ Выключен"
    x3_stars = "✅ Активен" if await is_event_active("global_x3_stars_until") else "❌ Выключен"
    free_view = "✅ Активен" if await is_event_active("global_free_view_until") else "❌ Выключен"
    lucky_hour = "✅ Активен" if await is_event_active("global_lucky_hour_until") else "❌ Выключен"

    def format_top(rows, is_negative=False):
        if not rows:
            return "  нет данных"
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (name, diamonds) in enumerate(rows, 1):
            medal = medals.get(i, f"{i}.")
            lines.append(f"{medal} {name} — <b>{diamonds:g} 💎</b>")
        return "\n".join(lines)

    text = (
        f"📊 <b>Статистика Системы:</b>\n\n"
        f"👥 Пользователей в БД: <b>{total_users}</b>\n"
        f"💎 Алмазов в плюсе: <b>{positive_diamonds:g}</b>\n"
        f"📉 Алмазов в минусе: <b>{negative_diamonds:g}</b>\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"👑 С премиум-статусом: <b>{premium_count}</b>\n"
        f"🎫 Активных промокодов: <b>{promo_count}</b>\n"
        f"🪞 Активных ботов в пуле: <b>{len(GLOBAL_BOTS_POOL)}</b>\n\n"
        f"🔥 <b>Текущие Ивенты:</b>\n"
        f"🚀 Глобальный х2 реф: {x2_active}\n"
        f"📉 Скидки в шопе: {disc_active}\n"
        f"⚡️ Х3 Пополнение (Stars): {x3_stars}\n"
        f"🆓 Бесплатные просмотры: {free_view}\n"
        f"🍀 Счастливый час (+2 💎): {lucky_hour}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="admin_enter").as_markup()
    )
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

# ========================= ПАКИ (ПОЛЬЗОВАТЕЛЬСКИЕ) =========================

@router.callback_query(F.data == "cat_packs")
async def cat_packs(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🌟 Паки знаменитостей", callback_data="celebrity_packs")
    kb.button(text="📦 Прочие паки", callback_data="other_packs")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)

    text = "📦 <b>Раздел Паков</b>\n\nВыберите категорию:"

    if callback.message.photo or getattr(callback.message, 'video', None) or getattr(callback.message, 'document', None):
        try: await callback.message.delete()
        except: pass
        await callback.message.answer(text, reply_markup=kb.as_markup())
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=kb.as_markup())

    await callback.answer()


@router.callback_query(F.data == "celebrity_packs")
async def celebrity_packs_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for pid, pack in PACKSZVEZDA.items():
        kb.button(
            text=f"📦 {pack['name']} — {pack['price']} ⭐️",
            callback_data=f"pack_preview_{pid}"
        )
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)

    await callback.message.edit_text("🌟 <b>Паки знаменитостей</b>\n\nВыберите пак:", reply_markup=kb.as_markup())


@router.callback_query(F.data == "other_packs")
async def other_packs_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for pid, pack in PROCHIEPAKI.items():
        kb.button(
            text=f"📦 {pack['name']} — {pack['price']} ⭐️",
            callback_data=f"pack_preview_{pid}"
        )
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)

    await callback.message.edit_text("📦 <b>Прочие паки</b>\n\nВыберите пак:", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("pack_preview_"))
async def pack_preview(callback: CallbackQuery):
    try:
        pack_id = int(callback.data.split("_")[-1])

        pack = PACKSZVEZDA.get(pack_id) or PROCHIEPAKI.get(pack_id)

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

Нажмите кнопку ниже для покупки.
После оплаты сразу получишь ссылку на Mega.nz
        """.strip()

        kb = InlineKeyboardBuilder()
        kb.button(text=f"💎 Купить за {pack['price']} ⭐", callback_data=f"buy_mega_pack_{pack_id}")
        kb.button(text="◀️ Назад к пакам", callback_data="cat_packs")
        kb.adjust(1)

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

@router.callback_query(F.data.startswith("buy_mega_pack_"))
async def buy_mega_pack(callback: CallbackQuery):
    pack_id = int(callback.data.split("_")[-1])
    pack = PACKSZVEZDA.get(pack_id) or PROCHIEPAKI.get(pack_id)

    if not pack:
        return await callback.answer("❌ Пак не найден", show_alert=True)

    payment_link = await generate_payment_link(
        callback.from_user.id,
        "mega_pack",
        {"name": pack["name"], "mega_link": pack["mega_link"]},
        pack["price"]
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)

    text = (
        f"📦 <b>{pack['name']}</b>\n\n"
        f"💰 Сумма: {pack['price']} ⭐️\n\n"
        f"⚠️ Оплата через отдельного бота.\n"
        f"Нажмите кнопку ниже:"
    )

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup())
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=kb.as_markup())

    await callback.answer()
# ========================= КАЗИНО =========================

@router.callback_query(F.data == "casino_menu")
async def casino_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id)

    if udata["diamonds"] > 300:
        return await callback.answer(
            "❌ В казино можно играть только при балансе до 300 алмазов!",
            show_alert=True
        )

    daily_won = await check_and_reset_daily_win(user_id)
    if daily_won >= 100:
        return await callback.answer(
            "❌ Вы уже выиграли 100 алмазов сегодня. Лимит исчерпан!",
            show_alert=True
        )

    text = (
        "🎮 <b>Казино</b>\n\n"
        f"💰 Баланс: <b>{udata['diamonds']}</b> 💎\n\n"
        "Выбери игру:\n\n"
        "🎲 Кости — Выпадет 4,5,6 — x2\n"
        "⚽️ Футбол — Гол — x1.5\n"
        "🎯 Дартс — В центр — x3\n"
        "🏀 Баскетбол — Попал — x1.5\n"
        "🎰 Слоты — Три одинак. — x5\n"
        "🎳 Боулинг — Страйк — x2"
    )

    await callback.message.edit_text(text, reply_markup=casino_menu())


@router.callback_query(F.data.startswith("game_"))
async def choose_bet(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data
    await state.update_data(game=game_type)

    names = {
        "game_dice": "🎲 Кости",
        "game_football": "⚽️ Футбол",
        "game_darts": "🎯 Дартс",
        "game_basket": "🏀 Баскетбол",
        "game_slots": "🎰 Слоты",
        "game_bowling": "🎳 Боулинг"
    }

    await callback.message.edit_text(
        f"🎮 <b>{names.get(game_type, 'Игра')}</b>\n\nВыберите ставку:",
        reply_markup=bet_keyboard(game_type)
    )


@router.callback_query(F.data.startswith("bet_"))
async def process_bet(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split("_")
    bet = int(parts[-1])
    game_callback = "_".join(parts[1:-1])

    user_id = callback.from_user.id
    udata = await get_user_data(user_id)

    if udata["diamonds"] < bet:
        return await callback.answer("❌ Недостаточно алмазов!", show_alert=True)

    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (bet, user_id))
    await db.commit()

    await state.update_data(bet=bet, game=game_callback)

    await play_animated_game(callback, bot, state, game_callback, bet)


async def play_animated_game(callback: CallbackQuery, bot: Bot, state: FSMContext, game_type: str, bet: int):
    emoji_map = {
        "game_dice": "🎲", "game_football": "⚽", "game_darts": "🎯",
        "game_basket": "🏀", "game_slots": "🎰", "game_bowling": "🎳"
    }
    emoji = emoji_map.get(game_type, "🎲")

    daily_won = await check_and_reset_daily_win(callback.from_user.id)
    if daily_won >= 100:
        return await callback.answer("❌ Дневной лимит выигрыша в казино исчерпан (100 💎)", show_alert=True)

    dice_msg = await bot.send_dice(chat_id=callback.from_user.id, emoji=emoji)
    await asyncio.sleep(2.8)

    value = dice_msg.dice.value

    if game_type == "game_slots":
        win = value in (1, 6)
        multiplier = 5.0
    else:
        rules = {
            "game_dice": (4, 2.0),
            "game_football": (4, 1.5),
            "game_darts": (6, 3.0),
            "game_basket": (4, 1.5),
            "game_bowling": (5, 2.0)
        }
        threshold, multiplier = rules.get(game_type, (4, 2.0))
        win = value >= threshold

    win_amount = int(bet * multiplier) if win else 0

    if win and daily_won + win_amount > 100:
        win_amount = int(100 - daily_won)
        if win_amount <= 0:
            win_amount = 0
            win = False

    if win and win_amount > 0:
        await add_diamonds(callback.from_user.id, win_amount)
        await add_daily_win(callback.from_user.id, win_amount)
        result = f"🎉 <b>ВЫИГРЫШ!</b>\n\nВы выиграли <b>{win_amount} 💎</b> (x{multiplier})"
    else:
        result = "😔 <b>Проигрыш</b>\nСтавка сгорела."

    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 Играть ещё", callback_data="casino_menu")
    kb.button(text="◀️ В меню", callback_data="back_main")
    kb.adjust(1)

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=f"{result}\n\n💰 Текущий баланс: <b>{(await get_user_data(callback.from_user.id))['diamonds']}</b> 💎",
        reply_markup=kb.as_markup()
    )

    await state.clear()

async def check_and_reset_daily_win(user_id: int):
    today = datetime.now().date().isoformat()

    async with db.execute(
        "SELECT daily_won, daily_reset_date FROM users WHERE user_id = ?",
        (user_id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return 0.0

    daily_won, reset_date = row
    if reset_date != today:
        await db.execute(
            "UPDATE users SET daily_won = 0, daily_reset_date = ? WHERE user_id = ?",
            (today, user_id)
        )
        await db.commit()
        return 0.0
    return float(daily_won or 0)


async def add_daily_win(user_id: int, amount: float):
    await db.execute(
        "UPDATE users SET daily_won = daily_won + ? WHERE user_id = ?",
        (amount, user_id)
    )
    await db.commit()

# ========================= БОТ ОПЛАТЫ: ЛОГИКА =========================

async def setup_payment_bot_handlers(dp_payment: Dispatcher, main_bot: Bot):  # <--- main_bot добавлен
    """Регистрирует хендлеры второго бота: реальный инвойс Stars + проверка оплаты."""

    @dp_payment.message(Command("start"))
    async def payment_bot_start(message: Message):
        user_id = message.from_user.id
        args = message.text.split()

        if len(args) <= 1 or not args[1].startswith("pay_"):
            return await message.answer(
                "💳 <b>Бот для оплаты</b>\n\n"
                "Используйте ссылку из главного бота для оплаты товаров.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="🔙 Вернуться в главного бота", url="https://t.me/zemlysan_DBot")
                    .as_markup()
            )
            async def heartbeat_checker():
    """Проверка активности ботов каждую минуту"""
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        
        for token, username in list(ACTIVE_BOTS.items()):
            try:
                bot = MAIN_BOTS.get(token)
                if bot:
                    me = await bot.get_me()
                    await db.execute(
                        "UPDATE bot_status SET last_heartbeat = ?, is_active = 1 WHERE token = ?",
                        (now.isoformat(), token)
                    )
                    await db.commit()
            except Exception as e:
                await send_log(f"⚠️ Бот @{username} не отвечает: {e}")
                await db.execute(
                    "UPDATE bot_status SET is_active = 0 WHERE token = ?",
                    (token,)
                )
                await db.commit()

        payment_id = args[1]
        order = await get_order(payment_id=payment_id)

        if not order:
            return await message.answer("❌ Ссылка оплаты недействительна или устарела.")

        if order["user_id"] != user_id:
            return await message.answer("❌ Эта ссылка оплаты принадлежит другому пользователю!")

        if order["status"] == "paid":
            return await message.answer("✅ Этот заказ уже оплачен. Вернитесь в главного бота, чтобы получить товар.")
        if order["status"] == "claimed":
            return await message.answer("ℹ️ Товар по этому заказу уже был получен ранее.")

        item_titles = {
            "diamonds": f"Покупка {order['item_data'].get('amount', '?')} алмазов",
            "ability_x2": "Буст х2 Рефералы (24ч)",
            "ability_keep_videos": "Видео навсегда",
            "mega_pack": order['item_data'].get('name', 'Пак'),
        }
        title = item_titles.get(order["item_type"], "Покупка")

        try:
            await message.answer_invoice(
                title=title,
                description=f"Оплата: {title}",
                payload=payment_id,
                currency="XTR",
                prices=[LabeledPrice(label="Telegram Stars", amount=order["stars_price"])]
            )
        except Exception as e:
            logging.error(f"Ошибка выставления счета: {e}")
            await message.answer("❌ Не удалось создать счёт на оплату. Попробуйте ещё раз позже.")

    @dp_payment.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        payment_id = query.invoice_payload
        order = await get_order(payment_id=payment_id)
        if not order or order["status"] != "pending":
            return await query.answer(ok=False, error_message="Заказ более недействителен.")
        await query.answer(ok=True)

@dp_payment.message(F.successful_payment)
async def successful_payment(message: Message):
    payment_id = message.successful_payment.invoice_payload
    now = datetime.now().isoformat()
    
    claim_id = uuid.uuid4().hex[:16]
    await db.execute(
        "UPDATE payment_orders SET status = 'paid', claim_id = ?, paid_at = ? WHERE payment_id = ?",
        (claim_id, now, payment_id)
    )
    await db.commit()
    
    # Получаем токен главного бота, которому принадлежит заказ
    async with db.execute("SELECT bot_token FROM payment_orders WHERE payment_id = ?", (payment_id,)) as cur:
        row = await cur.fetchone()
        bot_token = row[0] if row else list(MAIN_BOTS.keys())[0]
    
    # Получаем юзернейм правильного бота
    bot_username = ACTIVE_BOTS.get(bot_token, "zemlysan_DBot")  # замените на дефолтный юзернейм
    
    claim_link = f"https://t.me/{bot_username}?start=claim_{claim_id}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Получить товар", url=claim_link)
    kb.adjust(1)
    
    await message.answer(
        "✅ Оплата прошла успешно!\n\nНажмите кнопку, чтобы получить товар в главном боте:",
        reply_markup=kb.as_markup()
    )
    
    await send_log(f"💳 Оплата {payment_id} от @{message.from_user.username or message.from_user.first_name}")

# ========================= ГЛАВНЫЙ ЗАПУСК =========================

async def main():
    global db, MAIN_BOTS, ACTIVE_BOTS, PAYMENT_BOT_USERNAME, MIRROR_BOTS, GLOBAL_BOTS_POOL
    
    await init_db()
    await tokens_db.init()  # <--- ДОБАВЬТЕ ИНИЦИАЛИЗАЦИЮ БД ТОКЕНОВ
    await send_log("🚀 Запуск системы...")
    
    bot_tasks = []
    
    # ЗАПУСК ВСЕХ ГЛАВНЫХ БОТОВ
    for token in MAIN_BOT_TOKENS:
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await bot.delete_webhook(drop_pending_updates=True)
            
            me = await bot.get_me()
            username = me.username
            
            MAIN_BOTS[token] = bot
            ACTIVE_BOTS[token] = username
            GLOBAL_BOTS_POOL.append(bot)  # <--- ДОБАВЛЯЕМ В ПУЛ
            
       
            
            # Сохраняем статус в БД
            await db.execute(
                "INSERT OR REPLACE INTO bot_status (token, username, last_heartbeat, is_active) VALUES (?, ?, ?, 1)",
                (token, username, datetime.now().isoformat())
            )
            await db.commit()
            
            dp = Dispatcher()
            dp.include_router(router)
            
            # Добавляем мидлвари (если есть)
            # dp.message.outer_middleware(BanMiddleware())
            # dp.callback_query.outer_middleware(BanMiddleware())
            
            bot_tasks.append(asyncio.create_task(
                dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            ))
            
            await send_log(f"✅ Бот @{username} запущен")
            
        except Exception as e:
            await send_log(f"❌ Ошибка запуска бота: {e}")
    
    # ЗАПУСК БОТА ОПЛАТЫ
    try:
        payment_bot = Bot(token=PAYMENT_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await payment_bot.delete_webhook(drop_pending_updates=True)
        
        me = await payment_bot.get_me()
        PAYMENT_BOT_USERNAME = me.username
        
        dp_payment = Dispatcher()
        await setup_payment_bot_handlers(dp_payment, main_bot)  # <--- ЭТУ ФУНКЦИЮ НАДО ПЕРЕДЕЛАТЬ
        
        bot_tasks.append(asyncio.create_task(
            dp_payment.start_polling(payment_bot, allowed_updates=dp_payment.resolve_used_update_types())
        ))
        await send_log(f"✅ Бот оплаты @{PAYMENT_BOT_USERNAME} запущен")
        
    except Exception as e:
        await send_log(f"❌ Ошибка бота оплаты: {e}")

    # ========================= ЗАПУСК ЗЕРКАЛ =========================

async def start_mirror_bot(token: str, username: str):
    """Запускает бота-зеркало"""
    try:
        # Проверяем, не запущен ли уже
        if token in MIRROR_BOTS:
            try:
                await MIRROR_BOTS[token].session.close()
            except:
                pass
        
        mirror_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await mirror_bot.delete_webhook(drop_pending_updates=True)
        
        dp_mirror = Dispatcher()
        dp_mirror.include_router(create_router())
        
        # Запускаем в фоне
        asyncio.create_task(
            dp_mirror.start_polling(mirror_bot, allowed_updates=dp_mirror.resolve_used_update_types())
        )
        
        MIRROR_BOTS[token] = mirror_bot
        return True
    except Exception as e:
        await send_log(f"❌ Ошибка запуска зеркала @{username}: {e}")
        return False

async def activate_pending_mirrors():
    """Активирует все ожидающие зеркала из БД"""
    await send_log("🔄 Активация зеркал...")
    
    async with db.execute(
        "SELECT id, token, bot_username FROM mirrors WHERE status = 'pending'"
    ) as cur:
        mirrors = await cur.fetchall()
    
    activated = 0
    for mirror_id, token, username in mirrors:
        success = await start_mirror_bot(token, username)
        if success:
            await db.execute(
                "UPDATE mirrors SET status = 'active', activated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), mirror_id)
            )
            await db.commit()
            activated += 1
            await send_log(f"✅ Зеркало @{username} активировано")
        else:
            await db.execute(
                "UPDATE mirrors SET status = 'inactive' WHERE id = ?",
                (mirror_id,)
            )
            await db.commit()
            await send_log(f"❌ Зеркало @{username} не запустилось")
    
    return activated

# В main(), после запуска всех ботов, добавьте:
async def main():
    global db, MAIN_BOTS, ACTIVE_BOTS, PAYMENT_BOT_USERNAME, MIRROR_BOTS
    
    # ... существующий код инициализации ...
    
    # ЗАПУСК ЗЕРКАЛ
    await send_log("🚀 Запуск зеркал...")
    
    # Запускаем все активные зеркала
    async with db.execute(
        "SELECT id, token, bot_username FROM mirrors WHERE status = 'active'"
    ) as cur:
        mirrors = await cur.fetchall()
    
    for mirror_id, token, username in mirrors:
        await start_mirror_bot(token, username)
        await send_log(f"🔄 Зеркало @{username} запущено")
    
    # Активируем ожидающие зеркала
    activated = await activate_pending_mirrors()
    
    # ... остальной код ...
    
    # ЗАПУСК HEARTBEAT
    bot_tasks.append(asyncio.create_task(heartbeat_checker()))
    
    # Логируем статус через 3 секунды
    await asyncio.sleep(3)
    await log_bot_status()
    
    await send_log(f"🚀 Запущено {len(MAIN_BOTS)} главных ботов")
    
    # Ждем все задачи
    await asyncio.gather(*bot_tasks, return_exceptions=True)

async def heartbeat_checker():
    """Проверка активности ботов каждую минуту"""
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        for token, username in list(ACTIVE_BOTS.items()):
            try:
                bot = MAIN_BOTS.get(token)
                if bot:
                    await db.execute(
                        "UPDATE bot_status SET last_heartbeat = ?, is_active = 1 WHERE token = ?",
                        (now.isoformat(), token)
                    )
                    await db.commit()
            except Exception as e:
                await send_log(f"⚠️ Бот @{username} не отвечает: {e}")
                await db.execute(
                    "UPDATE bot_status SET is_active = 0 WHERE token = ?",
                    (token,)
                )
                await db.commit()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
