from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from tokens import tokens_db
except ImportError:
    tokens_db = None  # Объект создастся чуть ниже, сразу после объявления класса FallbackTokensDB


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("telegram_bot")

if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ========================= CONFIG =========================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("BOT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"
PACKS_DIR = DATA_DIR / "packs"
PACKS_DIR.mkdir(parents=True, exist_ok=True)

PACKSZVEZDA = {
    1: {"name": "Пак Полины ШГШ", "price": 30, "folder": PACKS_DIR / "pack1", "mega_link": "https://mega.nz/folder/mbQCia4B#pLXxfYKpxKM0wRyd-29glQ"},
    2: {"name": "Пак Златы", "price": 30, "folder": PACKS_DIR / "pack2", "mega_link": "https://mega.nz/folder/uWJlHY5a#V3EJuxs6-gKM9ZJgZa3CwA"},
    3: {"name": "Пак Янги18", "price": 99, "folder": PACKS_DIR / "pack8", "mega_link": "https://mega.nz/folder/cVklTYSJ#znRJ19C6CvCgsN_lZj2ZEw"},
}

PROCHIEPAKI = {
    4: {"name": "Пак 1", "price": 99, "folder": PACKS_DIR / "pack3", "mega_link": "https://mega.nz/folder/SMNWEIoA#BZagaT85jJGc0kcO-N-F3A"},
    5: {"name": "Пак 2", "price": 149, "folder": PACKS_DIR / "pack4", "mega_link": "https://mega.nz/folder/kiF2nb6T#FXuuQqFbxyDybJq7qomvHA"},
    6: {"name": "Пак 3", "price": 199, "folder": PACKS_DIR / "pack5", "mega_link": "https://mega.nz/folder/rmIB0T5L#ZAnu_nFzEPhq4UgZrouaBw"},
    7: {"name": "Пак 4", "price": 299, "folder": PACKS_DIR / "pack7", "mega_link": "https://mega.nz/folder/eNc3kZgK#eRFNRIOAUiQrH5tREGBDHQ"},
}

for pack_dict in (PACKSZVEZDA, PROCHIEPAKI):
    for pack_data in pack_dict.values():
        pack_data["folder"].mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"
TOKENS_DB_PATH = DATA_DIR / "tokens.db"

for folder in (DATA_DIR, MEDIA_DIR, PHOTO_DIR, PACKS_DIR):
    folder.mkdir(parents=True, exist_ok=True)

# Секретный ключ для защиты Callback Data от хакеров/подделок (сгенерирован случайно при запуске)
ADMIN_SECRET_SALT = os.getenv("ADMIN_SECRET_SALT", uuid.uuid4().hex)

# ========================= CRYPTO SIGNATURE FOR CALLBACKS =========================

def get_admin_sign(user_id: int) -> str:
    """Генерирует уникальную 8-символьную подпись для верификации колбэков админа."""
    return hashlib.sha256(f"{user_id}:{ADMIN_SECRET_SALT}".encode()).hexdigest()[:8]

def verify_admin_callback(callback: CallbackQuery) -> bool:
    """Проверяет, принадлежит ли подпись в callback.data текущему пользователю."""
    if callback.from_user.id not in ADMIN_IDS:
        return False
    parts = callback.data.split(":")
    if len(parts) < 2:
        return False
    expected_sign = get_admin_sign(callback.from_user.id)
    return parts[-1] == expected_sign
def split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]


def parse_int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer in %s=%r; using %s", name, raw, default)
        return default


def parse_int_list_env(name: str) -> list[int]:
    result: list[int] = []
    for value in split_env_list(os.getenv(name)):
        try:
            result.append(int(value))
        except ValueError:
            logger.warning("Skipping invalid integer in %s: %r", name, value)
    return result


MAIN_BOT_TOKENS = [
    "8842603644:AAFlaIV81P9TT2Y_E1mYYkVwR5JIpWpBd08",
    # ДОБАВЛЯЙТЕ СКОЛЬКО УГОДНО ТОКЕНОВ СЮДА
]
PAYMENT_BOT_TOKEN = "8947363174:AAG2Ly6FWUlcjKyZoSHJP04SCxQECtSV0CQ"
CHANNELS = [
    (-1003475196063, "Наш канал", "https://t.me/+JypFAG4wqgk0ZTEy"),
    ("@Klubnichkin812", "Наш резерв", "https://t.me/Klubnichkin812"),
]
LOG_GROUP_ID = -5417151890  # <--- СЮДА ВСТАВЬТЕ ID ВАШЕЙ ГРУППЫ
ADMIN_IDS = [8794011165]
EVENT_CHANNEL_ID = -1003475196063
# ========================= FALLBACK TOKENS DB =========================

class FallbackTokensDB:
    def __init__(self, path: Path):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                username TEXT,
                status TEXT DEFAULT 'available',
                user_id INTEGER,
                mirror_id INTEGER,
                is_active INTEGER DEFAULT 0,
                created_at TEXT,
                used_at TEXT
            )
            """
        )
        await self.db.commit()

    def _conn(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("tokens_db is not initialized")
        return self.db

    async def add_token(self, token: str, username: str | None = None, user_id: int | None = None, status: str = 'available') -> bool:
        db_conn = self._conn()
        try:
            await db_conn.execute(
                """
                INSERT INTO tokens (token, username, status, user_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, username, status, user_id, datetime.now().isoformat()),
            )
            await db_conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def delete_token_by_value(self, token: str) -> None:
        db_conn = self._conn()
        await db_conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
        await db_conn.commit()

    async def get_token_by_username(self, value: str):
        db_conn = self._conn()
        async with db_conn.execute(
            """
            SELECT id, token, username, status, user_id, is_active
            FROM tokens
            WHERE username = ? COLLATE NOCASE OR token = ?
            """,
            (value.lstrip("@"), value),
        ) as cur:
            return await cur.fetchone()

    async def get_token_by_value(self, token: str):
        db_conn = self._conn()
        async with db_conn.execute(
            "SELECT id, token, username, status, user_id, is_active FROM tokens WHERE token = ?",
            (token,),
        ) as cur:
            return await cur.fetchone()

    async def get_available_token(self):
        db_conn = self._conn()
        async with db_conn.execute(
            "SELECT id, token, username FROM tokens WHERE status = 'available' ORDER BY id LIMIT 1"
        ) as cur:
            return await cur.fetchone()

    async def use_token(self, token: str, user_id: int, mirror_id: int | None = None) -> None:
        db_conn = self._conn()
        await db_conn.execute(
            """
            UPDATE tokens
            SET status = 'used', user_id = ?, mirror_id = ?, is_active = 1, used_at = ?
            WHERE token = ?
            """,
            (user_id, mirror_id, datetime.now().isoformat(), token),
        )
        await db_conn.commit()

    async def update_token_status(self, token: str, status: str, is_active: int = 0) -> None:
        db_conn = self._conn()
        await db_conn.execute(
            "UPDATE tokens SET status = ?, is_active = ? WHERE token = ?",
            (status, is_active, token),
        )
        await db_conn.commit()

    async def get_all_tokens(self):
        db_conn = self._conn()
        async with db_conn.execute(
            """
            SELECT id, token, username, status, user_id, is_active
            FROM tokens
            ORDER BY id DESC
            """
        ) as cur:
            return await cur.fetchall()

    async def get_stats(self) -> dict[str, int]:
        db_conn = self._conn()
        stats = {"total": 0, "available": 0, "used": 0, "active": 0, "banned": 0}
        try:
            async with db_conn.execute("SELECT COUNT(*) FROM tokens") as cur:
                stats["total"] = (await cur.fetchone())[0]
            for status in ("available", "used", "banned"):
                async with db_conn.execute("SELECT COUNT(*) FROM tokens WHERE status = ?", (status,)) as cur:
                    stats[status] = (await cur.fetchone())[0]
            async with db_conn.execute("SELECT COUNT(*) FROM tokens WHERE is_active = 1") as cur:
                stats["active"] = (await cur.fetchone())[0]
        except Exception as e:
            logger.error(f"Error getting stats from tokens_db: {e}")
        return stats

# Регистрируем глобальный объект fallback-базы, если импорт сверху не удался
if 'tokens_db' not in globals() or tokens_db is None:
    tokens_db = FallbackTokensDB(TOKENS_DB_PATH)

# ========================= GLOBALS =========================

db: aiosqlite.Connection | None = None
MAIN_BOTS: dict[str, Bot] = {}
ACTIVE_BOTS: dict[str, str] = {}
MIRROR_BOTS: dict[str, Bot] = {}
BOT_INSTANCES: dict[str, Bot] = {}
GLOBAL_BOTS_POOL: list[Bot] = []
MIRROR_TASKS: dict[str, asyncio.Task] = {}
PAYMENT_BOT_USERNAME: str | None = None
PAYMENT_BOT_INSTANCE: Bot | None = None


def get_db() -> aiosqlite.Connection:
    if db is None:
        raise RuntimeError("Database is not initialized")
    return db


def current_bot_token(bot: Bot | None) -> str | None:
    if bot is None:
        return None
    for token, instance in BOT_INSTANCES.items():
        if instance is bot:
            return token
    return None


# ========================= NOT ADMIN FILTER =========================
def not_admin_filter(column: str = "user_id") -> tuple[str, tuple[int, ...]]:
    if not ADMIN_IDS:
        return "1 = 1", ()
    placeholders = ",".join("?" for _ in ADMIN_IDS)
    return f"{column} NOT IN ({placeholders})", tuple(ADMIN_IDS)


# ========================= LOGGER =========================

async def send_log(text: str, bot: Bot | None = None) -> None:
    """
    Отправляет логи ТОЛЬКО через PAYMENT_BOT.
    Логи со всех ботов (главных и зеркал) теперь идут только сюда.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_text = f"[{timestamp}] {text}"
    print(log_text)  # всегда выводим в консоль

    if LOG_GROUP_ID == 0:
        return

    # ТОЛЬКО PAYMENT BOT
    if PAYMENT_BOT_INSTANCE is None:
        logger.warning("PAYMENT_BOT_INSTANCE is None. Cannot send log.")
        return

    try:
        await PAYMENT_BOT_INSTANCE.send_message(
            LOG_GROUP_ID, 
            f"📋 {log_text}",
            parse_mode=ParseMode.HTML
        )
    except Exception as exc:
        logger.warning(f"Failed to send log via PAYMENT_BOT: {exc}")

# ========================= STATES =========================

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


# ========================= DATABASE =========================

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

    user_migrations = [
        "ALTER TABLE users ADD COLUMN banned_until INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN daily_reward_last TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN daily_won REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN daily_reset_date TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN username TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT 'Пользователь'",
        "ALTER TABLE users ADD COLUMN diamonds REAL DEFAULT 8.0",
        "ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN is_referral_rewarded INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN premium INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN x2_until TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN keep_videos INTEGER DEFAULT 0",
    ]

    for sql in user_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    default_settings = {
        "global_x2_until": "NULL",
        "global_discount_until": "NULL",
        "global_discount_percent": "30",
        "global_x3_stars_until": "NULL",
        "global_free_view_until": "NULL",
        "global_lucky_hour_until": "NULL",
        "maintenance_mode": "false",
        "video_price": "6",
        "photo_price": "3",
        "referral_reward": "4",
        "auto_ban_limit": "10000",
    }

    for key, value in default_settings.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    await db.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            file_id TEXT,
            message_id INTEGER,
            chat_id INTEGER,
            delete_at TEXT
        )
    """)

    video_migrations = [
        "ALTER TABLE videos ADD COLUMN file_id TEXT",
        "ALTER TABLE videos ADD COLUMN message_id INTEGER",
        "ALTER TABLE videos ADD COLUMN chat_id INTEGER",
        "ALTER TABLE videos ADD COLUMN delete_at TEXT",
    ]

    for sql in video_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            creator_id INTEGER,
            reward INTEGER,
            uses_left INTEGER
        )
    """)

    promo_code_migrations = [
        "ALTER TABLE promo_codes ADD COLUMN creator_id INTEGER",
        "ALTER TABLE promo_codes ADD COLUMN reward INTEGER",
        "ALTER TABLE promo_codes ADD COLUMN uses_left INTEGER",
    ]

    for sql in promo_code_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_activations (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)

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

    admin_pack_migrations = [
        "ALTER TABLE admin_packs ADD COLUMN name TEXT",
        "ALTER TABLE admin_packs ADD COLUMN description TEXT",
        "ALTER TABLE admin_packs ADD COLUMN price INTEGER",
        "ALTER TABLE admin_packs ADD COLUMN photo_path TEXT",
        "ALTER TABLE admin_packs ADD COLUMN file_path TEXT",
        "ALTER TABLE admin_packs ADD COLUMN created_at TEXT",
    ]

    for sql in admin_pack_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

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

    payment_order_migrations = [
        "ALTER TABLE payment_orders ADD COLUMN claim_id TEXT",
        "ALTER TABLE payment_orders ADD COLUMN user_id INTEGER",
        "ALTER TABLE payment_orders ADD COLUMN item_type TEXT",
        "ALTER TABLE payment_orders ADD COLUMN item_data TEXT",
        "ALTER TABLE payment_orders ADD COLUMN stars_price INTEGER",
        "ALTER TABLE payment_orders ADD COLUMN bot_token TEXT",
        "ALTER TABLE payment_orders ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE payment_orders ADD COLUMN created_at TEXT",
        "ALTER TABLE payment_orders ADD COLUMN paid_at TEXT",
        "ALTER TABLE payment_orders ADD COLUMN claimed_at TEXT",
    ]

    for sql in payment_order_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

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

    mirror_migrations = [
        "ALTER TABLE mirrors ADD COLUMN user_id INTEGER",
        "ALTER TABLE mirrors ADD COLUMN token TEXT",
        "ALTER TABLE mirrors ADD COLUMN bot_username TEXT",
        "ALTER TABLE mirrors ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE mirrors ADD COLUMN created_at TEXT",
        "ALTER TABLE mirrors ADD COLUMN activated_at TEXT",
        "ALTER TABLE mirrors ADD COLUMN last_heartbeat TEXT",
    ]

    for sql in mirror_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_user ON mirrors (user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_status ON mirrors (status)")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            token TEXT PRIMARY KEY,
            username TEXT,
            last_heartbeat TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    bot_status_migrations = [
        "ALTER TABLE bot_status ADD COLUMN username TEXT",
        "ALTER TABLE bot_status ADD COLUMN last_heartbeat TEXT",
        "ALTER TABLE bot_status ADD COLUMN is_active INTEGER DEFAULT 1",
    ]

    for sql in bot_status_migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except aiosqlite.OperationalError:
            pass

    await db.commit()
    print("✅ База данных инициализирована")


# ========================= HELPERS =========================

async def get_setting(key: str) -> str:
    async with get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else "NULL"


async def set_setting(key: str, value: str) -> None:
    await get_db().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await get_db().commit()


async def is_event_active(event_key: str) -> bool:
    val = await get_setting(event_key)
    if val == "NULL":
        return False
    try:
        return datetime.fromisoformat(val) > datetime.now()
    except Exception:
        return False


async def get_event_remaining_time(event_key: str) -> str:
    val = await get_setting(event_key)
    if val == "NULL":
        return ""
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
    return (await get_setting("maintenance_mode")).lower() == "true"


def parse_duration_input(text: str) -> tuple[timedelta, str] | None:
    text = text.strip().lower()
    if not text:
        return None
    if text.endswith(("m", "м")):
        num = text[:-1].strip()
        if num.isdigit() and int(num) > 0:
            return timedelta(minutes=int(num)), f"{num} мин."
    if text.endswith(("h", "ч")):
        num = text[:-1].strip()
        if num.isdigit() and int(num) > 0:
            return timedelta(hours=int(num)), f"{num} ч."
    if text.isdigit() and int(text) > 0:
        return timedelta(hours=int(text)), f"{text} ч."
    return None


async def check_subscription(user_id: int, bot: Bot | None = None) -> bool:
    if not CHANNELS:
        return True
    
    payment_bot = PAYMENT_BOT_INSTANCE
    if payment_bot is None:
        if bot is not None:
            payment_bot = bot
        else:
            logger.warning("PAYMENT_BOT_INSTANCE is None, using passed bot for subscription check")
            payment_bot = bot

    if payment_bot is None:
        return True

    for channel, _, _ in CHANNELS:
        try:
            member = await payment_bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in {"member", "administrator", "creator"}:
                return False
        except Exception as exc:
            logger.warning(f"Subscription check failed for channel {channel}: {exc}")
            return False
    return True


def subscription_keyboard() -> Any:
    kb = InlineKeyboardBuilder()
    for _, ch_name, ch_url in CHANNELS:
        kb.button(text=ch_name, url=ch_url)
    kb.button(text="✅ Я подписался", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()


async def send_to_all_bots(text: str) -> None:
    if not GLOBAL_BOTS_POOL:
        return
    async with get_db().execute("SELECT user_id FROM users") as cur:
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


async def broadcast_event_start(title: str, description: str, duration_str: str | None = None) -> None:
    time_str = f"⏳ <b>Длительность:</b> {duration_str}\n" if duration_str else ""
    text = (
        "🔔 <b>ГЛОБАЛЬНОЕ СОБЫТИЕ В БОТЕ!</b> 🔔\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🎉 <b>Ивент:</b> {title}\n"
        f"📢 {description}\n\n"
        f"{time_str}"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "🚀 Заходи скорей и используй момент по максимуму!"
    )
    if EVENT_CHANNEL_ID and GLOBAL_BOTS_POOL:
        try:
            await GLOBAL_BOTS_POOL[0].send_message(chat_id=EVENT_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            logger.error("Failed to publish event: %s", exc)
    await send_to_all_bots(text)


async def get_user_data(user_id: int, first_name: str = "Пользователь", username: str | None = None) -> dict[str, Any]:
    async with get_db().execute(
        """
        SELECT diamonds, premium, x2_until, keep_videos, referred_by, is_referral_rewarded
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        await get_db().execute(
            "INSERT INTO users (user_id, first_name, username, diamonds) VALUES (?, ?, ?, 8.0)",
            (user_id, first_name, username),
        )
        await get_db().commit()
        return {
            "diamonds": 8.0,
            "premium": 0,
            "x2_until": None,
            "keep_videos": 0,
            "referred_by": None,
            "is_referral_rewarded": 0,
        }

    diamonds_val, prem_val, x2_until, keep_val, referred_by, rewarded = row
    if diamonds_val < 0 and prem_val > 0:
        await get_db().execute("UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?", (user_id,))
        await get_db().commit()
        prem_val = 0
        keep_val = 0

    if username is not None:
        await get_db().execute(
            "UPDATE users SET first_name = ?, username = ? WHERE user_id = ?",
            (first_name, username, user_id),
        )
        await get_db().commit()

    return {
        "diamonds": diamonds_val,
        "premium": prem_val,
        "x2_until": x2_until,
        "keep_videos": keep_val,
        "referred_by": referred_by,
        "is_referral_rewarded": rewarded,
    }


async def check_auto_ban(user_id: int) -> None:
    if user_id in ADMIN_IDS:
        return
    async with get_db().execute("SELECT diamonds, is_banned FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return
    diamonds_val, is_banned_val = row
    try:
        limit = float(await get_setting("auto_ban_limit"))
    except (ValueError, TypeError):
        limit = 10000.0
    if diamonds_val > limit and is_banned_val != 1:
        await get_db().execute("UPDATE users SET is_banned = 1, banned_until = 0 WHERE user_id = ?", (user_id,))
        await get_db().commit()
        if GLOBAL_BOTS_POOL:
            try:
                await GLOBAL_BOTS_POOL[0].send_message(
                    user_id,
                    "⛔ <b>Ваш аккаунт заблокирован автоматической системой безопасности навсегда "
                    "за подозрительное превышение лимита баланса алмазов.</b>\n\n"
                    "Свяжитесь с администрацией.",
                )
            except Exception:
                pass


async def add_diamonds(user_id: int, amount: float) -> None:
    await get_db().execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
    await get_db().commit()
    await check_auto_ban(user_id)


async def check_daily_reward(user_id: int) -> tuple[bool, int]:
    async with get_db().execute("SELECT daily_reward_last FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row or not row[0]:
        return True, 0
    try:
        last = datetime.fromisoformat(row[0])
    except ValueError:
        return True, 0
    elapsed = (datetime.now() - last).total_seconds()
    return (True, 0) if elapsed >= 86400 else (False, int(86400 - elapsed))


async def get_user_mirrors(user_id: int) -> list[tuple[Any, ...]]:
    async with get_db().execute(
        """
        SELECT id, bot_username, status, created_at, activated_at
        FROM mirrors
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    ) as cur:
        return await cur.fetchall()


async def get_mirror_count(user_id: int) -> int:
    async with get_db().execute("SELECT COUNT(*) FROM mirrors WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def create_mirror_record(user_id: int, token: str, username: str) -> int:
    cursor = await get_db().execute(
        """
        INSERT INTO mirrors (user_id, token, bot_username, status, created_at)
        VALUES (?, ?, ?, 'active', ?)
        """,
        (user_id, token, username, datetime.now().isoformat()),
    )
    await get_db().commit()
    return int(cursor.lastrowid)


async def token_exists(token: str, username: str | None = None) -> bool:
    if hasattr(tokens_db, "get_token_by_value"):
        row = await tokens_db.get_token_by_value(token)
        if row:
            return True
    if hasattr(tokens_db, "get_token_by_username"):
        row = await tokens_db.get_token_by_username(token)
        if row:
            return True
        if username:
            row = await tokens_db.get_token_by_username(username)
            if row:
                return True
    return token in BOT_INSTANCES


async def mark_token_used(token: str, user_id: int, mirror_id: int | None = None) -> None:
    if hasattr(tokens_db, "use_token"):
        try:
            await tokens_db.use_token(token, user_id, mirror_id)
            await send_log(f"✅ Токен зеркала помечен как used (user={user_id}, mirror={mirror_id})")
        except Exception as e:
            logger.error(f"mark_token_used error: {e}")


async def update_token_status(token: str, status: str, is_active: int) -> None:
    if hasattr(tokens_db, "update_token_status"):
        await tokens_db.update_token_status(token, status, is_active)


# ========================= PAYMENT =========================

async def create_payment_order(
    user_id: int,
    item_type: str,
    item_data: dict[str, Any],
    stars_price: int,
    bot_token: str | None = None,
) -> str:
    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    await get_db().execute(
        """
        INSERT INTO payment_orders
            (payment_id, user_id, item_type, item_data, stars_price, bot_token, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            payment_id,
            user_id,
            item_type,
            json.dumps(item_data, ensure_ascii=False),
            stars_price,
            bot_token or "",
            datetime.now().isoformat(),
        ),
    )
    await get_db().commit()
    return payment_id


async def get_order(payment_id: str | None = None, claim_id: str | None = None) -> dict[str, Any] | None:
    if payment_id:
        sql = """
            SELECT payment_id, claim_id, user_id, item_type, item_data, stars_price, status, bot_token
            FROM payment_orders
            WHERE payment_id = ?
        """
        params = (payment_id,)
    elif claim_id:
        sql = """
            SELECT payment_id, claim_id, user_id, item_type, item_data, stars_price, status, bot_token
            FROM payment_orders
            WHERE claim_id = ?
        """
        params = (claim_id,)
    else:
        return None

    async with get_db().execute(sql, params) as cur:
        row = await cur.fetchone()
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
        "bot_token": row[7],
    }


async def generate_payment_link(
    user_id: int,
    item_type: str,
    item_data: dict[str, Any],
    stars_price: int,
    bot_token: str | None = None,
) -> str:
    if not PAYMENT_BOT_USERNAME:
        raise RuntimeError("Payment bot is not started")
    if bot_token is None:
        bot_token = next(iter(MAIN_BOTS.keys()), "")
    payment_id = await create_payment_order(user_id, item_type, item_data, stars_price, bot_token)

    cutoff = (datetime.now() - timedelta(hours=6)).isoformat()
    await get_db().execute("DELETE FROM payment_orders WHERE status = 'pending' AND created_at < ?", (cutoff,))
    await get_db().commit()

    return f"https://t.me/{PAYMENT_BOT_USERNAME}?start={payment_id}"


async def process_payment(user_id: int, item_type: str, item_data: dict[str, Any], main_bot: Bot) -> None:
    if item_type == "diamonds":
        diamonds = float(item_data["amount"])
        if await is_event_active("global_x3_stars_until"):
            diamonds *= 3
        await add_diamonds(user_id, diamonds)
        x3_msg = " [⚡️ Х3 Ивент!]" if await is_event_active("global_x3_stars_until") else ""
        try:
            await main_bot.send_message(user_id, f"🎉 <b>Оплата зачислена!</b> +{diamonds:g} 💎{x3_msg}")
        except Exception:
            pass
    elif item_type == "ability_x2":
        await get_db().execute(
            "UPDATE users SET x2_until = ? WHERE user_id = ?",
            ((datetime.now() + timedelta(hours=24)).isoformat(), user_id),
        )
        await get_db().commit()
        try:
            await main_bot.send_message(user_id, "🚀 <b>Буст х2 Рефералы активирован на 24 часа!</b>")
        except Exception:
            pass
    elif item_type == "ability_keep_videos":
        await get_db().execute("UPDATE users SET keep_videos = 1 WHERE user_id = ?", (user_id,))
        await get_db().commit()
        try:
            await main_bot.send_message(user_id, "♾ <b>Видео теперь сохраняются навсегда!</b>")
        except Exception:
            pass
    elif item_type == "mega_pack":
        try:
            await main_bot.send_message(
                user_id,
                f"🎉 <b>{item_data['name']} успешно оплачен!</b>\n\n"
                f"🔗 <b>Ссылка на полный пак:</b>\n"
                f"{item_data['mega_link']}\n\n"
                f"💾 Сохраните ссылку — она постоянная.",
                disable_web_page_preview=True,
            )
        except Exception:
            pass
    elif item_type == "admin_pack":
        pack_id = item_data["pack_id"]
        async with get_db().execute("SELECT name, file_path FROM admin_packs WHERE id = ?", (pack_id,)) as cur:
            pack = await cur.fetchone()
        if pack:
            name, file_path = pack
            try:
                await main_bot.send_document(
                    user_id,
                    document=FSInputFile(file_path),
                    caption=f"🎁 <b>Спасибо за покупку пака «{name}»!</b>",
                )
            except Exception as exc:
                logger.error("Failed to send admin pack: %s", exc)


# ========================= MIDDLEWARE =========================

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            async with get_db().execute(
                "SELECT is_banned, banned_until, diamonds, premium FROM users WHERE user_id = ?",
                (user.id,),
            ) as cur:
                row = await cur.fetchone()
            if row:
                is_banned, banned_until, diamonds, premium = row
                if diamonds < 0 and premium > 0:
                    await get_db().execute(
                        "UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?",
                        (user.id,),
                    )
                    await get_db().commit()
                current_ts = int(time.time())
                if is_banned == 1 or (banned_until > 0 and banned_until > current_ts):
                    time_left = "навсегда" if banned_until == 0 else f"до {datetime.fromtimestamp(banned_until).strftime('%d.%m %H:%M')}"
                    if isinstance(event, CallbackQuery):
                        await event.answer(f"❌ Доступ заблокирован {time_left}!", show_alert=True)
                    elif isinstance(event, Message):
                        await event.answer(f"❌ <b>Ваш аккаунт заблокирован администратором {time_left}!</b>")
                    return
        return await handler(event, data)


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if await is_maintenance_mode():
            user = data.get("event_from_user")
            if user and user.id not in ADMIN_IDS:
                text = "🛠 <b>Технические работы в боте!</b>\n\nБот временно недоступен."
                if isinstance(event, CallbackQuery):
                    await event.answer("🛠 Техработы!", show_alert=True)
                    if event.message:
                        try:
                            await event.message.edit_text(text)
                        except TelegramBadRequest:
                            await event.message.answer(text)
                elif isinstance(event, Message):
                    await event.answer(text)
                return
        return await handler(event, data)


# ========================= KEYBOARDS =========================

async def main_menu(user_id: int):
    try:
        video_price = float(await get_setting("video_price"))
    except (ValueError, TypeError):
        video_price = 6.0
    try:
        photo_price = float(await get_setting("photo_price"))
    except (ValueError, TypeError):
        photo_price = 3.0

    kb = InlineKeyboardBuilder()
    kb.button(text=f"📺 Смотреть видео ({video_price:g} 💎)", callback_data="watch")
    kb.button(text=f"📸 Посмотреть фото ({photo_price:g} 💎)", callback_data="watch_photo")
    kb.button(text="🎁 Ежедневная награда", callback_data="daily_reward")
    kb.button(text="🛒 Магазин 💰", callback_data="shop_main")
    kb.button(text="🔄 Зеркала (+20 💎)", callback_data="mirror_menu")
    kb.button(text="🎟 Промокоды", callback_data="promo_menu")
    kb.button(text="🎮 Казино", callback_data="casino_menu")
    kb.button(text="🏆 Таблица Лидеров", callback_data="leaderboard")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
    if user_id in ADMIN_IDS:
        kb.button(text="⚙️ Admin Panel", callback_data="admin_enter")
    can_claim, remaining = await check_daily_reward(user_id)
    if not can_claim:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        kb.button(text=f"⏳ {hours}ч {minutes}м", callback_data="daily_reward_disabled")
    kb.adjust(1)
    return kb.as_markup()


def shop_categories_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Купить Алмазы (за Звезды)", callback_data="cat_diamonds")
    kb.button(text="⚡ Способности (за Звезды)", callback_data="cat_abilities")
    kb.button(text="👑 Премиум Статусы (за Алмазы)", callback_data="cat_premium")
    kb.button(text="📦 Паки (за Звезды)", callback_data="cat_packs")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def shop_diamonds_kb(discount_pct: int = 0, timer: str = ""):
    kb = InlineKeyboardBuilder()
    prices = [80, 200, 400]
    amounts = [100, 250, 500]
    timer_str = f" ({timer})" if timer else ""
    for amount, price in zip(amounts, prices):
        final = max(1, int(price * (1 - discount_pct / 100))) if discount_pct > 0 else price
        text = f"🎁 {amount} 💎 — <s>{price}</s> -> {final} ⭐️" if discount_pct > 0 else f"🎁 {amount} алмазов — {price} ⭐️"
        kb.button(text=text + timer_str, callback_data=f"stars_{amount}")
    kb.button(text="✍️ Ввести свое количество алмазов", callback_data="stars_custom")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()


def shop_abilities_kb(discount_pct: int = 0, timer: str = ""):
    kb = InlineKeyboardBuilder()
    timer_str = f" ({timer})" if timer else ""
    for text, price, callback_data in (
        ("🚀 х2 Рефералы (24ч)", 50, "buy_boost_x2"),
        ("♾ Видео навсегда", 150, "buy_keep_videos"),
    ):
        final = max(1, int(price * (1 - discount_pct / 100))) if discount_pct > 0 else price
        label = f"{text} — <s>{price}</s> -> {final} ⭐️" if discount_pct > 0 else f"{text} — {price} ⭐️"
        kb.button(text=label + timer_str, callback_data=callback_data)
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()


def shop_premium_kb(discount_pct: int = 0, timer: str = ""):
    kb = InlineKeyboardBuilder()
    timer_str = f" ({timer})" if timer else ""
    for text, price, callback_data in (
        ("🌟 Премиум (Все бесплатно)", 1500, "buy_prem_normal"),
        ("🔥 Премиум+ (Архивы + Навсегда)", 2000, "buy_prem_plus"),
    ):
        final = max(1, int(price * (1 - discount_pct / 100))) if discount_pct > 0 else price
        label = f"{text} — <s>{price}</s> -> {final} 💎" if discount_pct > 0 else f"{text} — {price} 💎"
        kb.button(text=label + timer_str, callback_data=callback_data)
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("📊 Статистика", "admin_stats"),
        ("👤 Управление юзерами (💎/🚫)", "admin_manage_users"),
        ("🚫 Забаненные пользователи", "admin_banned_list"),
        ("👑 Список админов", "admin_list_admins"),
        ("🪞 Управление зеркалами", "admin_manage_mirrors"),
        ("🔑 Токены для зеркал", "admin_tokens"),
        ("⚙️ Настройки экономики", "admin_economy"),
        ("📤 Экспорт пользователей (CSV)", "admin_export_users"),
        ("🎫 Активные промокоды", "admin_active_promos"),
        ("🗑 Удалить ВСЕ промокоды", "admin_delete_all_promos"),
        ("📢 Рассылка текста", "admin_mail"),
        ("🔥 Управление ИВЕНТАМИ", "admin_events_panel"),
        ("🛠 Техработы (Вкл/Выкл)", "admin_toggle_maintenance"),
        ("◀️ Назад в меню", "back_main"),
    ]
    for text, callback_data in buttons:
        kb.button(text=text, callback_data=callback_data)
    kb.adjust(1)
    return kb.as_markup()


def admin_events_kb():
    kb = InlineKeyboardBuilder()
    for text, callback_data in (
        ("🚀 Запустить х2 Рефералы", "ev_setup_x2"),
        ("📉 Настроить Скидки %", "ev_setup_discount"),
        ("🎁 Сделать Раздачу Алмазов всем", "ev_setup_giveaway"),
        ("⚡️ Запустить х3 Алмазы (Stars)", "ev_setup_x3_stars"),
        ("🆓 Запустить Бесплатный Просмотр", "ev_setup_free_view"),
        ("🍀 Запустить Счастливый Час (+2 💎)", "ev_setup_lucky_hour"),
        ("◀️ Назад в Админку", "admin_enter"),
    ):
        kb.button(text=text, callback_data=callback_data)
    kb.adjust(1)
    return kb.as_markup()


def casino_menu():
    kb = InlineKeyboardBuilder()
    for text, callback_data in (
        ("🎲 Кости", "game_dice"),
        ("⚽️ Футбол", "game_football"),
        ("🎯 Дартс", "game_darts"),
        ("🏀 Баскетбол", "game_basket"),
        ("🎰 Слоты", "game_slots"),
        ("🎳 Боулинг", "game_bowling"),
        ("◀️ В главное меню", "back_main"),
    ):
        kb.button(text=text, callback_data=callback_data)
    kb.adjust(2)
    return kb.as_markup()


def bet_keyboard(game_callback: str):
    kb = InlineKeyboardBuilder()
    for bet in (1, 3, 5):
        kb.button(text=f"{bet} 💎", callback_data=f"bet_{game_callback}_{bet}")
    kb.button(text="◀️ Назад", callback_data="casino_menu")
    kb.adjust(3)
    return kb.as_markup()


# ========================= MAIN HANDLERS =========================

async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Пользователь"
    username = message.from_user.username
    args = message.text.split() if message.text else []

    # 1. Проверка получения оплаченного товара
    if len(args) > 1 and args[1].startswith("claim_"):
        claim_id = args[1][len("claim_") :]
        order = await get_order(claim_id=claim_id)
        if not order:
            return await message.answer("❌ Ссылка недействительна.")
        if order["user_id"] != user_id:
            return await message.answer("❌ Не ваша ссылка.")
        if order["status"] == "claimed":
            return await message.answer("ℹ️ Товар уже получен.")
        if order["status"] != "paid":
            return await message.answer("❌ Оплата не подтверждена.")

        await get_user_data(user_id, name, username)
        await process_payment(user_id, order["item_type"], order["item_data"], bot)
        await get_db().execute(
            "UPDATE payment_orders SET status = 'claimed', claimed_at = ? WHERE payment_id = ?",
            (datetime.now().isoformat(), order["payment_id"]),
        )
        await get_db().commit()
        udata = await get_user_data(user_id, name, username)
        return await message.answer(
            f"✅ Товар выдан!\n\n💰 Баланс: {udata['diamonds']} 💎",
            reply_markup=await main_menu(user_id),
        )

    # 2. Логика детекта реферальной ссылки (работает, только если в конце передан ID)
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        potential_referrer = int(args[1])
        if potential_referrer != user_id:
            referrer_id = potential_referrer

    # Проверяем наличие пользователя в базе данных
    async with get_db().execute("SELECT user_id, referred_by, is_referral_rewarded FROM users WHERE user_id = ?", (user_id,)) as cur:
        existing_user = await cur.fetchone()

    if not existing_user:
        # Если пользователя нет, создаем его. 
        # referred_by запишется только тогда, когда старт был по РЕФ-ССЫЛКЕ.
        # Если вошли просто по юзернейму зеркала — запишется NULL (None).
        await get_db().execute(
            """
            INSERT INTO users (user_id, first_name, username, diamonds, referred_by, is_referral_rewarded)
            VALUES (?, ?, ?, 8.0, ?, 0)
            """,
            (user_id, name, username, referrer_id),
        )
        await get_db().commit()
    else:
        # Если пользователь уже существовал, но у него не было реферера, и сейчас он перешел по реф-ссылке
        if existing_user[1] is None and referrer_id:
            await get_db().execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
            await get_db().commit()

    # Обновляем и вытаскиваем актуальные данные пользователя
    udata = await get_user_data(user_id, name, username)

    # 3. Проверка Обязательной подписки на каналы
    if not await check_subscription(user_id, bot):
        return await message.answer("👋 Подпишись на каналы:", reply_markup=subscription_keyboard())

    # 4. Начисление +4 алмазов за приглашение (сработает ТОЛЬКО при наличии реферера)
    if udata["referred_by"] and udata["is_referral_rewarded"] == 0:
        ref_id = udata["referred_by"]
        try:
            base_reward = float(await get_setting("referral_reward"))
        except (ValueError, TypeError):
            base_reward = 4.0
        if await is_event_active("global_x2_until"):
            base_reward *= 2
        async with get_db().execute("SELECT x2_until FROM users WHERE user_id = ?", (ref_id,)) as cur:
            ref_x2 = await cur.fetchone()
        if ref_x2 and ref_x2[0] and datetime.fromisoformat(ref_x2[0]) > datetime.now():
            base_reward *= 2
            
        await add_diamonds(ref_id, base_reward)
        await get_db().execute("UPDATE users SET is_referral_rewarded = 1 WHERE user_id = ?", (user_id,))
        await get_db().commit()
        try:
            await bot.send_message(ref_id, f"🎉 Твой реферал {name} активировался! Получено +{base_reward:g} 💎")
        except Exception:
            pass
        await send_log(f"👥 Реферал {name} (ID: {user_id}) активировался для {ref_id} -> +{base_reward:g} 💎")

    # Вывод главного меню
    await message.answer(
        f"👋 Добро пожаловать!\n\n💰 Баланс: {udata['diamonds']} 💎",
        reply_markup=await main_menu(user_id),
    )
    me = await bot.get_me()
    await send_log(f"👤 {name} (ID: {user_id}) запустил бота @{me.username}", bot)


async def check_sub(callback: CallbackQuery, bot: Bot):
    if await check_subscription(callback.from_user.id, bot):
        udata = await get_user_data(callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
        await callback.message.edit_text(
            f"✅ Подписка проверена.\n\n💰 Баланс: <b>{udata['diamonds']}</b> 💎",
            reply_markup=await main_menu(callback.from_user.id),
        )
        return await callback.answer("✅ Готово!")
    await callback.answer("❌ Подпишись на все каналы!", show_alert=True)


async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    async with get_db().execute("SELECT diamonds, premium, keep_videos FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return await callback.answer("Ошибка авторизации.", show_alert=True)
    current_diamonds, premium, keep_videos = row
    if current_diamonds < 0:
        return await callback.message.answer("❌ <b>Просмотр заблокирован! Ваш баланс отрицательный.</b>")

    is_free = await is_event_active("global_free_view_until")
    is_lucky = await is_event_active("global_lucky_hour_until")
    if premium == 0 and not is_free and not is_lucky:
        try:
            video_price = float(await get_setting("video_price"))
        except (ValueError, TypeError):
            video_price = 6.0
        if current_diamonds < video_price:
            return await callback.answer(f"❌ Недостаточно алмазов! Нужно {video_price:g} 💎", show_alert=True)
        await get_db().execute(
            "UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?",
            (video_price, user_id, video_price),
        )
        await get_db().commit()

    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MP4")) + list(MEDIA_DIR.glob("*.mov")) + list(MEDIA_DIR.glob("*.MOV"))
    if not videos:
        return await callback.answer("Папка media пуста.", show_alert=True)

    is_forever = keep_videos == 1 or premium == 2
    caption = "📹 Ваше видео!" if is_forever else "📹 Видео удалится через 30 минут."
    if is_free:
        caption += " (🔥 По ивенту БЕСПЛАТНО)"
    if is_lucky:
        await add_diamonds(user_id, 2.0)
        caption += " (🍀 Счастливый час: +2 💎 за просмотр!)"

    msg = await bot.send_video(
        chat_id=user_id,
        video=FSInputFile(random.choice(videos)),
        caption=caption,
        has_spoiler=True,
    )
    if not is_forever:
        await get_db().execute(
            "INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)",
            ("", msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()),
        )
        await get_db().commit()
    await callback.answer()


async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    async with get_db().execute("SELECT diamonds, premium FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return await callback.answer("Ошибка.", show_alert=True)
    current_diamonds, premium = row
    if current_diamonds < 0:
        return await callback.message.answer("❌ <b>Просмотр заблокирован! Баланс в минусе.</b>")

    is_free = await is_event_active("global_free_view_until")
    is_lucky = await is_event_active("global_lucky_hour_until")
    if premium == 0 and not is_free and not is_lucky:
        try:
            photo_price = float(await get_setting("photo_price"))
        except (ValueError, TypeError):
            photo_price = 3.0
        if current_diamonds < photo_price:
            return await callback.answer(f"❌ Недостаточно алмазов! Требуется {photo_price:g} 💎", show_alert=True)
        await get_db().execute(
            "UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?",
            (photo_price, user_id, photo_price),
        )
        await get_db().commit()

    photos: list[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG", "*.WEBP"):
        photos.extend(PHOTO_DIR.glob(ext))
    if not photos:
        return await callback.answer("Папка photo пуста.", show_alert=True)

    if is_lucky:
        await add_diamonds(user_id, 2.0)
    photo_msg = await bot.send_photo(
        chat_id=user_id,
        photo=FSInputFile(random.choice(photos)),
        caption="🍀 Счастливый час: +2 💎!" if is_lucky else None,
        has_spoiler=True,
    )
    if premium != 2:
        await get_db().execute(
            "INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)",
            ("", photo_msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()),
        )
        await get_db().commit()
    await callback.answer()


# ========================= MIRRORS =========================

async def mirror_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    mirrors = await get_user_mirrors(user_id)
    mirror_count = await get_mirror_count(user_id)
    stats = await tokens_db.get_stats() if hasattr(tokens_db, "get_stats") else {"total": 0, "available": 0, "used": 0, "active": 0, "banned": 0}

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать зеркало (+20 💎)", callback_data="create_mirror_process")
    kb.button(text="📋 Мои зеркала", callback_data="my_mirrors")
    if mirrors:
        kb.button(text="🔄 Перезапустить зеркала", callback_data="restart_mirrors")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)

    text = (
        "🔄 <b>Управление зеркалами</b>\n\n"
        f"📊 Ваших зеркал: <b>{mirror_count}</b>\n"
        f"🔑 Токенов в базе: <b>{stats.get('total', 0)}</b>\n\n"
        "1. Создайте бота в @BotFather\n"
        "2. Скопируйте токен\n"
        "3. Нажмите «Создать зеркало»\n"
        "4. Отправьте токен текстом\n\n"
        "⚠️ Один пользователь может создать до двух зеркал."
    )
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


async def create_mirror_process(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if await is_mirror_limit_reached(user_id):
        return await callback.answer("❌ Максимум 2 зеркала на пользователя!", show_alert=True)
        
    await callback.message.edit_text("📥 <b>Отправьте токен вашего бота из @BotFather:</b>\n\nПример: <code>123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ</code>")
    await state.set_state(MirrorStates.enter_token)
    await callback.answer()


async def process_mirror_token(message: Message, state: FSMContext):
    user_id = message.from_user.id
    token = (message.text or "").strip()
    if ":" not in token or not token.split(":", 1)[0].isdigit():
        return await message.answer("❌ Неверный формат токена. Отправьте токен из @BotFather.")

    try:
        test_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        me = await test_bot.get_me()
        username = me.username
        await test_bot.session.close()
    except Exception as exc:
        return await message.answer(f"❌ Не удалось подключиться к боту.\nОшибка: {str(exc)[:100]}")

    if not username:
        return await message.answer("❌ У бота нет username.")

    if await is_mirror_limit_reached(user_id):
        return await message.answer("❌ Максимум 2 зеркала на пользователя!")

    if await token_exists(token, username):
        return await message.answer("❌ Этот токен или бот уже используется.")

    await state.clear()

    add_result = False
    try:
        if hasattr(tokens_db, "add_token"):
            add_result = await tokens_db.add_token(token, username, user_id, status='used')
            if add_result:
                await send_log(f"🔑 Токен зеркала @{username} успешно добавлен в tokens.db")
        else:
            add_result = True
    except Exception as e:
        logger.error(f"Ошибка добавления токена в tokens.db: {e}")

    if add_result is False:
        return await message.answer("❌ Этот токен уже есть в базе tokens.db.")

    mirror_id = await create_mirror_record(user_id, token, username)
    await mark_token_used(token, user_id, mirror_id)
    success = await start_mirror_bot(token, username)

    if success:
        await update_token_status(token, "used", 1)
        await get_db().execute(
            "UPDATE mirrors SET status = 'active', activated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), mirror_id),
        )
        await get_db().commit()
        await add_diamonds(user_id, 20.0)

        kb = InlineKeyboardBuilder()
        kb.button(text="🔗 Перейти к боту", url=f"https://t.me/{username}")
        kb.button(text="◀️ В меню зеркал", callback_data="mirror_menu")
        kb.adjust(1)

        await message.answer(
            f"✅ <b>Зеркало успешно создано!</b>\n\n"
            f"🤖 Бот: @{username}\n"
            f"💎 Награда: +20 💎\n"
            f"🔗 <code>https://t.me/{username}</code>",
            reply_markup=kb.as_markup(),
        )
        await send_log(f"🔄 Пользователь {user_id} создал зеркало @{username} (+20 💎)")
    else:
        await get_db().execute("UPDATE mirrors SET status = 'inactive' WHERE id = ?", (mirror_id,))
        await get_db().commit()
        await update_token_status(token, "banned", 0)
        await message.answer("❌ Не удалось запустить бота-зеркало.")


async def is_mirror_limit_reached(user_id: int) -> bool:
    count = await get_mirror_count(user_id)
    return count >= 2


async def my_mirrors(callback: CallbackQuery):
    user_id = callback.from_user.id
    mirrors = await get_user_mirrors(user_id)
    if not mirrors:
        return await callback.answer("У вас нет зеркал!", show_alert=True)
    kb = InlineKeyboardBuilder()
    text = "📋 <b>Ваши зеркала:</b>\n\n"
    for _, username, status, created_at, _ in mirrors:
        status_emoji = {"pending": "⏳", "active": "✅", "inactive": "❌"}.get(status, "❓")
        status_text = {"pending": "Создается...", "active": "Работает", "inactive": "Неактивен"}.get(status, "Неизвестно")
        created = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
        text += f"{status_emoji} @{username} — {status_text}\n   🕐 Создан: {created}\n\n"
        if status == "active":
            kb.button(text=f"🔗 @{username}", url=f"https://t.me/{username}")
    kb.button(text="🔄 Обновить", callback_data="my_mirrors")
    kb.button(text="◀️ Назад", callback_data="mirror_menu")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


async def restart_mirrors(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with get_db().execute(
        "SELECT token, bot_username FROM mirrors WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return await callback.answer("Нет активных зеркал.", show_alert=True)
    ok = 0
    for token, username in rows:
        if await start_mirror_bot(token, username):
            ok += 1
    await callback.answer(f"🔄 Перезапущено: {ok}", show_alert=True)


async def no_tokens(callback: CallbackQuery):
    await callback.answer("⏳ Нет доступных токенов.", show_alert=True)


# ========================= DAILY / PROMO / LEADERBOARD =========================

async def daily_reward(callback: CallbackQuery):
    user_id = callback.from_user.id
    can_claim, remaining = await check_daily_reward(user_id)
    if not can_claim:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return await callback.answer(f"⏳ Через {hours}ч {minutes}м", show_alert=True)
    reward = random.randint(2, 8)
    await add_diamonds(user_id, float(reward))
    await get_db().execute(
        "UPDATE users SET daily_reward_last = ? WHERE user_id = ?",
        (datetime.now().isoformat(), user_id),
    )
    await get_db().commit()
    await callback.answer(f"🎉 +{reward} 💎", show_alert=True)
    await callback.message.edit_text(
        f"🎁 Ежедневная награда!\n\n+{reward} 💎",
        reply_markup=await main_menu(user_id),
    )


async def daily_reward_disabled(callback: CallbackQuery):
    await callback.answer("⏳ Подождите до следующей награды!", show_alert=True)


async def promo_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with get_db().execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.message.answer("❌ <b>Доступ к промокодам заблокирован, пока баланс отрицательный!</b>")
    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Активировать промокод", callback_data="promo_activate")
    kb.button(text="➕ Создать промокод", callback_data="promo_create")
    kb.button(text="◀️ Назад в главное меню", callback_data="back_main")
    kb.adjust(1)
    await callback.message.edit_text(
        "🎟 <b>Раздел Промокодов</b>\n\nЗдесь можно активировать промокод или создать свой.",
        reply_markup=kb.as_markup(),
    )


async def promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Введите промокод:")
    await state.set_state(PromoStates.activate_code)


async def process_promo_activate(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    user_id = message.from_user.id
    await state.clear()
    async with get_db().execute("SELECT creator_id, reward, uses_left FROM promo_codes WHERE code = ?", (code,)) as cur:
        row = await cur.fetchone()
    if not row:
        return await message.answer("❌ Промокод не найден.")
    creator_id, reward, uses_left = row
    if uses_left <= 0:
        return await message.answer("❌ Промокод закончился.")
    if creator_id == user_id:
        return await message.answer("❌ Вы не можете активировать собственный промокод.")
    async with get_db().execute("SELECT 1 FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, code)) as cur:
        if await cur.fetchone():
            return await message.answer("❌ Вы уже активировали этот промокод ранее!")
    await get_db().execute("INSERT INTO promo_activations VALUES (?, ?)", (user_id, code))
    if uses_left - 1 == 0:
        await get_db().execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else:
        await get_db().execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    await add_diamonds(user_id, float(reward))
    await get_db().commit()
    await message.answer(f"🎉 <b>Промокод успешно активирован!</b>\nНа баланс зачислено: +<b>{reward}</b> 💎")


async def promo_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with get_db().execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.answer("❌ Нельзя создавать промокоды с отрицательным балансом!", show_alert=True)
    await callback.message.edit_text("✨ Введите текст промокода:")
    await state.set_state(PromoStates.create_code)


async def process_promo_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code:
        return await message.answer("❌ Код не может быть пустым.")
    await state.update_data(code=code)
    await message.answer("💎 Введите награду в алмазах за 1 активацию:")
    await state.set_state(PromoStates.create_reward)


async def process_promo_reward(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await state.clear()
        return await message.answer("❌ Награда должна быть целым положительным числом. Операция отменена.")
    await state.update_data(reward=int(text))
    await message.answer("👥 Кол-во людей, которые смогут его активировать:")
    await state.set_state(PromoStates.create_uses)


async def process_promo_uses(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await state.clear()
        return await message.answer("❌ Количество использований должно быть положительным.")
    uses = int(text)
    data = await state.get_data()
    total = data["reward"] * uses
    async with get_db().execute("SELECT diamonds FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
        balance = await cur.fetchone()
    if not balance or balance[0] < total or balance[0] < 0:
        await state.clear()
        return await message.answer(f"❌ Недостаточно 💎 или баланс отрицательный! Требуется: {total} 💎")
    try:
        await get_db().execute(
            "UPDATE users SET diamonds = diamonds - ? WHERE user_id = ? AND diamonds >= ?",
            (total, message.from_user.id, total),
        )
        await get_db().execute(
            "INSERT INTO promo_codes VALUES (?, ?, ?, ?)",
            (data["code"], message.from_user.id, data["reward"], uses),
        )
        await get_db().commit()
    except aiosqlite.IntegrityError:
        await state.clear()
        return await message.answer("❌ Такой промокод уже существует.")
    await state.clear()
    await message.answer(
        f"✅ Промокод успешно создан!\n\n"
        f"🎫 Код: <b>{data['code']}</b>\n"
        f"💎 Награда: <b>{data['reward']}</b> за активацию\n"
        f"👥 Кол-во активаций: <b>{uses}</b>",
        reply_markup=await main_menu(message.from_user.id),
    )


async def leaderboard_menu(callback: CallbackQuery):
    clause, params = not_admin_filter("user_id")
    async with get_db().execute(
        f"""
        SELECT user_id, first_name, diamonds
        FROM users
        WHERE diamonds >= 0 AND {clause}
        ORDER BY diamonds DESC
        LIMIT 10
        """,
        params,
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        kb = InlineKeyboardBuilder()
        kb.button(text="◀️ Назад", callback_data="back_main")
        return await callback.message.edit_text("🏆 <b>Список лидеров пуст.</b>", reply_markup=kb.as_markup())
    text = "🏆 <b>ТОП-10 ИГРОКОВ ПО АЛМАЗАМ</b> 🏆\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (uid, name, diamonds) in enumerate(rows, 1):
        text += f"{medals.get(i, f'{i}.')} {name} <code>(ID: {uid})</code> — <b>{diamonds:g} 💎</b>\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# ========================= ADMIN =========================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_enter(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.message.edit_text("🛠 <b>Административная Панель</b>:", reply_markup=admin_menu())


async def admin_manage_users(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(
        "👤 <b>Панель пользователей</b>\n\n"
        "Введите Telegram ID или @username пользователя:"
    )
    await state.set_state(AdminStates.user_manage_id)


async def process_user_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if text.startswith("@"):
        sql = "SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE username = ? COLLATE NOCASE"
        params = (text[1:],)
    elif text.isdigit():
        sql = "SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE user_id = ?"
        params = (int(text),)
    else:
        sql = "SELECT user_id, first_name, diamonds, is_banned, banned_until, premium FROM users WHERE username = ? COLLATE NOCASE"
        params = (text,)
    async with get_db().execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return await message.answer("❌ Юзер не найден в БД.")
    uid, first_name, diamonds_val, is_banned_val, banned_until_val, premium_val = row
    await state.update_data(target_id=uid)

    ban_status = "❌ Нет"
    if is_banned_val == 1:
        ban_status = "⛔ Перманентно"
    elif banned_until_val > int(time.time()):
        ban_status = f"⏳ До {datetime.fromtimestamp(banned_until_val).strftime('%d.%m %H:%M')}"
    premium_status = "❌ Нет" if premium_val == 0 else ("🌟 Premium" if premium_val == 1 else "🔥 Premium+")

    kb = InlineKeyboardBuilder()
    for text_btn, data in (
        ("💎 Изменить баланс алмазов", "adm_change_diamonds"),
        ("👑 Выдать статус вручную", "adm_grant_premium_menu"),
        ("🚫 Заблокировать (Временный бан)", "adm_ban_time"),
        ("🔒 Забанить НАВСЕГДА", "adm_ban_forever"),
        ("🔓 Разблокировать", "adm_unban"),
        ("◀️ В админку", "admin_enter"),
    ):
        kb.button(text=text_btn, callback_data=data)
    kb.adjust(1)
    await message.answer(
        f"👤 <b>Пользователь:</b> {first_name}\n"
        f"ID: <code>{uid}</code>\n"
        f"Баланс: <b>{diamonds_val:g}</b> 💎\n"
        f"Премиум: <b>{premium_status}</b>\n"
        f"Блокировка: <b>{ban_status}</b>",
        reply_markup=kb.as_markup(),
    )


async def adm_grant_premium_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    uid = (await state.get_data()).get("target_id")
    if not uid:
        return await callback.answer("Сначала выберите пользователя.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="🌟 Выдать Premium", callback_data="adm_grant_prem_1")
    kb.button(text="🔥 Выдать Premium+", callback_data="adm_grant_prem_2")
    kb.button(text="🚫 Убрать статус", callback_data="adm_grant_prem_0")
    kb.button(text="◀️ Отмена", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.answer(f"👑 Выберите статус для пользователя <code>{uid}</code>:", reply_markup=kb.as_markup())
    await callback.answer()


async def adm_grant_prem(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    level = int(callback.data.split("_")[-1])
    uid = (await state.get_data()).get("target_id")
    if not uid:
        return await callback.answer("Сначала выберите пользователя.", show_alert=True)
    if level == 0:
        await get_db().execute("UPDATE users SET premium = 0, keep_videos = 0 WHERE user_id = ?", (uid,))
    else:
        await get_db().execute("UPDATE users SET premium = ? WHERE user_id = ?", (level, uid))
    await get_db().commit()
    label = "статус снят" if level == 0 else ("Premium выдан" if level == 1 else "Premium+ выдан")
    await callback.answer(f"✅ {label}!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())


async def adm_change_diamonds_handler(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer("✍️ Введите новое значение баланса алмазов:")
    await state.set_state(AdminStates.user_change_diamonds)
    await callback.answer()


async def process_user_change_diamonds(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        return await message.answer("❌ Введите число:")
    uid = (await state.get_data()).get("target_id")
    await state.clear()
    if not uid:
        return await message.answer("❌ Пользователь не выбран.")
    await get_db().execute("UPDATE users SET diamonds = ? WHERE user_id = ?", (amount, uid))
    await get_db().commit()
    await check_auto_ban(uid)
    await message.answer(f"✅ Баланс пользователя установлен на {amount:g} 💎.", reply_markup=admin_menu())


async def adm_ban_time_handler(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer("⏱ Введите время блокировки в минутах:")
    await state.set_state(AdminStates.user_ban_time)
    await callback.answer()


async def process_user_ban_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        return await message.answer("❌ Введите целое число минут:")
    uid = (await state.get_data()).get("target_id")
    await state.clear()
    if not uid:
        return await message.answer("❌ Пользователь не выбран.")
    minutes = int(text)
    until_ts = int(time.time()) + minutes * 60
    await get_db().execute("UPDATE users SET is_banned = 0, banned_until = ? WHERE user_id = ?", (until_ts, uid))
    await get_db().commit()
    await message.answer(f"✅ Пользователь <code>{uid}</code> заблокирован на {minutes} мин.", reply_markup=admin_menu())


async def adm_ban_forever(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    uid = (await state.get_data()).get("target_id")
    await state.clear()
    if not uid:
        return await callback.answer("Пользователь не выбран.", show_alert=True)
    await get_db().execute("UPDATE users SET is_banned = 1, banned_until = 0 WHERE user_id = ?", (uid,))
    await get_db().commit()
    await callback.answer("⛔ Заблокирован навсегда!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())


async def adm_unban(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    uid = (await state.get_data()).get("target_id")
    await state.clear()
    if not uid:
        return await callback.answer("Пользователь не выбран.", show_alert=True)
    await get_db().execute("UPDATE users SET is_banned = 0, banned_until = 0 WHERE user_id = ?", (uid,))
    await get_db().commit()
    await callback.answer("🔓 Полностью разблокирован!", show_alert=True)
    await callback.message.answer("Выполнено.", reply_markup=admin_menu())


# ========================= ADMIN MANAGING MIRRORS =========================

async def admin_manage_mirrors(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
        
    async with get_db().execute("SELECT id, user_id, bot_username, status FROM mirrors ORDER BY id DESC") as cur:
        mirrors = await cur.fetchall()
        
    kb = InlineKeyboardBuilder()
    if not mirrors:
        kb.button(text="◀️ Назад в админку", callback_data="admin_enter")
        return await callback.message.edit_text("🪞 <b>Зеркал в системе еще не создано.</b>", reply_markup=kb.as_markup())
        
    text = "🪞 <b>Список всех зеркал в системе:</b>\n\nВыберите для просмотра деталей:\n"
    for m_id, u_id, username, status in mirrors:
        status_emoji = {"active": "🟢", "pending": "⏳", "inactive": "🔴"}.get(status, "⚪")
        text += f"{status_emoji} ID: {m_id} | @{username} (Юзер: <code>{u_id}</code>)\n"
        kb.button(text=f"🤖 @{username} (ID: {m_id})", callback_data=f"adm_mirror_view_{m_id}")
        
    kb.button(text="◀️ Назад в админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def admin_mirror_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
        
    mirror_id = int(callback.data.split("_")[-1])
    async with get_db().execute("SELECT id, user_id, token, bot_username, status, created_at, activated_at FROM mirrors WHERE id = ?", (mirror_id,)) as cur:
        mirror = await cur.fetchone()
        
    if not mirror:
        return await callback.answer("❌ Зеркало не найдено.", show_alert=True)
        
    m_id, u_id, token, username, status, created, activated = mirror
    
    text = (
        f"🪞 <b>Информация о зеркале #{m_id}</b>\n\n"
        f"🤖 Бот: @{username}\n"
        f"👤 Создатель (ID): <code>{u_id}</code>\n"
        f"📊 Статус: <b>{status}</b>\n"
        f"📅 Создан: <code>{created}</code>\n"
        f"⚡ Активирован: <code>{activated or 'Нет данных'}</code>\n\n"
        f"🔑 Токен: <code>{token}</code>"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Удалить зеркало", callback_data=f"adm_mirror_del_{m_id}")
    kb.button(text="◀️ К списку зеркал", callback_data="admin_manage_mirrors")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def admin_mirror_delete_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
        
    mirror_id = int(callback.data.split("_")[-1])
    async with get_db().execute("SELECT token, bot_username FROM mirrors WHERE id = ?", (mirror_id,)) as cur:
        row = await cur.fetchone()
        
    if row:
        token, username = row
        # Останавливаем пуллинг и удаляем из локальных словарей
        old_task = MIRROR_TASKS.pop(token, None)
        if old_task:
            old_task.cancel()
        old_bot = MIRROR_BOTS.pop(token, None)
        if old_bot:
            try:
                GLOBAL_BOTS_POOL[:] = [bot for bot in GLOBAL_BOTS_POOL if bot is not old_bot]
                await old_bot.session.close()
            except Exception:
                pass
        BOT_INSTANCES.pop(token, None)
        ACTIVE_BOTS.pop(token, None)
        
        # Удаляем данные из обеих баз данных
        await get_db().execute("DELETE FROM mirrors WHERE id = ?", (mirror_id,))
        await get_db().execute("DELETE FROM bot_status WHERE token = ?", (token,))
        await get_db().commit()
        
        if hasattr(tokens_db, "delete_token_by_value"):
            await tokens_db.delete_token_by_value(token)
            
        await callback.answer(f"✅ Зеркало @{username} успешно удалено!", show_alert=True)
        await send_log(f"🗑 Администратор удалил зеркало @{username} (ID: {mirror_id})")
        
    await admin_manage_mirrors(callback)


# ========================= TOKENS LOGIC CONTINUED =========================

async def admin_tokens(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    stats = await tokens_db.get_stats() if hasattr(tokens_db, "get_stats") else {"total": 0, "available": 0, "used": 0, "active": 0, "banned": 0}
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить токены", callback_data="admin_add_tokens")
    kb.button(text="📊 Все токены", callback_data="admin_view_tokens")
    kb.button(text="◀️ Назад в админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(
        "🔑 <b>Управление токенами</b>\n\n"
        f"Всего: <b>{stats.get('total', 0)}</b>\n"
        f"Доступно: <b>{stats.get('available', 0)}</b>\n"
        f"Использовано: <b>{stats.get('used', 0)}</b>\n"
        f"Активно: <b>{stats.get('active', 0)}</b>\n"
        f"Забанено: <b>{stats.get('banned', 0)}</b>",
        reply_markup=kb.as_markup(),
    )


async def admin_add_tokens(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.message.edit_text("🔑 <b>Добавление токенов</b>\n\nВведите токены, каждый с новой строки:")
    await state.set_state(AdminStates.add_token)


async def process_add_tokens(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    tokens = [token.strip() for token in (message.text or "").splitlines() if token.strip()]
    added = 0
    errors = 0
    for token in tokens:
        try:
            test_bot = Bot(token=token)
            me = await test_bot.get_me()
            username = me.username
            await test_bot.session.close()
            result = await tokens_db.add_token(token, username, message.from_user.id, status='available') if hasattr(tokens_db, "add_token") else False
            if result is not False:
                added += 1
                await send_log(f"🔑 Добавлен токен @{username}")
            else:
                errors += 1
        except Exception as exc:
            errors += 1
            await send_log(f"❌ Ошибка добавления токена: {exc}")
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="admin_tokens")
    await message.answer(f"✅ <b>Готово</b>\n\n➕ Добавлено: <b>{added}</b>\n❌ Ошибок: <b>{errors}</b>", reply_markup=kb.as_markup())


async def admin_view_tokens(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    tokens = await tokens_db.get_all_tokens() if hasattr(tokens_db, "get_all_tokens") else []
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="admin_tokens")
    if not tokens:
        return await callback.message.edit_text("📋 <b>Нет токенов в базе.</b>", reply_markup=kb.as_markup())
    text = "📋 <b>Все токены:</b>\n\n"
    for _, token, username, status, user_id, is_active in tokens[:20]:
        status_emoji = {"available": "🟢", "used": "🔵", "banned": "🔴", "main_bot": "👑"}.get(status, "⚪")
        text += f"{status_emoji} @{username or 'unknown'} — {status} {'✅' if is_active else '❌'}\n"
        if user_id:
            text += f"   👤 ID: {user_id}\n"
        text += f"   🆔 {token[:20]}...\n\n"
    if len(tokens) > 20:
        text += f"\n... и еще {len(tokens) - 20} токенов"
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def admin_active_promos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    async with get_db().execute("SELECT code, reward, uses_left, creator_id FROM promo_codes") as cur:
        promos = await cur.fetchall()
    kb = InlineKeyboardBuilder()
    if not promos:
        kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
        return await callback.message.edit_text("🎫 <b>Активных промокодов нет.</b>", reply_markup=kb.as_markup())
    text = "🎫 <b>Список активных промокодов:</b>\n\n"
    for code, reward, uses_left, creator in promos:
        text += f"▪️ <code>{code}</code> | <b>{reward} 💎</b> | Осталось: <b>{uses_left}</b> | ID: <code>{creator}</code>\n"
        kb.button(text=f"❌ Удалить {code}", callback_data=f"adm_del_promo_{code}")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def admin_delete_promo_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    promo_code = callback.data.replace("adm_del_promo_", "")
    await get_db().execute("DELETE FROM promo_codes WHERE code = ?", (promo_code,))
    await get_db().commit()
    await callback.answer(f"✅ Промокод {promo_code} удален!", show_alert=True)
    await admin_active_promos(callback)


async def admin_delete_all_promos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    async with get_db().execute("SELECT COUNT(*) FROM promo_codes") as cur:
        count = (await cur.fetchone())[0]
    await get_db().execute("DELETE FROM promo_codes")
    await get_db().execute("DELETE FROM promo_activations")
    await get_db().commit()
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ В админку", callback_data="admin_enter")
    await callback.answer(f"✅ Удалено {count} промокодов!", show_alert=True)
    await callback.message.edit_text("🗑 <b>Все промокоды успешно удалены.</b>", reply_markup=kb.as_markup())


async def admin_toggle_maintenance(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    new_state = "false" if await is_maintenance_mode() else "true"
    await set_setting("maintenance_mode", new_state)
    status = "✅ ВКЛЮЧЕН" if new_state == "true" else "❌ ВЫКЛЮЧЕН"
    await callback.answer(f"Техработы: {status}", show_alert=True)
    await callback.message.edit_text(
        f"🛠 <b>Административная Панель</b>\n\nТехнические работы: <b>{status}</b>",
        reply_markup=admin_menu(),
    )


async def admin_banned_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    now_ts = int(time.time())
    async with get_db().execute(
        """
        SELECT user_id, first_name, is_banned, banned_until
        FROM users
        WHERE is_banned = 1 OR banned_until > ?
        ORDER BY user_id
        LIMIT 30
        """,
        (now_ts,),
    ) as cur:
        rows = await cur.fetchall()
    kb = InlineKeyboardBuilder()
    if not rows:
        text = "🚫 <b>Забаненных пользователей нет.</b>"
    else:
        text = "🚫 <b>Забаненные пользователи</b>:\n\n"
        for uid, first_name, is_banned_val, banned_until_val in rows:
            status = "⛔ навсегда" if is_banned_val == 1 else f"⏳ до {datetime.fromtimestamp(banned_until_val).strftime('%d.%m %H:%M')}"
            text += f"▪️ {first_name} <code>({uid})</code> — {status}\n"
            kb.button(text=f"🔓 Разбанить {uid}", callback_data=f"banlist_unban_{uid}")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


async def banlist_unban(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    uid = int(callback.data.replace("banlist_unban_", ""))
    await get_db().execute("UPDATE users SET is_banned = 0, banned_until = 0 WHERE user_id = ?", (uid,))
    await get_db().commit()
    await callback.answer("🔓 Пользователь разбанен!", show_alert=True)
    await admin_banned_list(callback)


async def admin_list_admins(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    text = "👑 <b>Список администраторов бота:</b>\n\n"
    for aid in ADMIN_IDS:
        async with get_db().execute("SELECT username, first_name FROM users WHERE user_id = ?", (aid,)) as cur:
            row = await cur.fetchone()
        label = "не запускал бота"
        if row:
            username, first_name = row
            label = f"@{username}" if username else first_name
        text += f"▪️ {label} — <code>{aid}</code>\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


ECONOMY_SETTINGS_MAP = {
    "eco_set_video_price": ("video_price", "Цена просмотра видео (в 💎)"),
    "eco_set_photo_price": ("photo_price", "Цена просмотра фото (в 💎)"),
    "eco_set_referral_reward": ("referral_reward", "Награда за реферала (в 💎)"),
    "eco_set_autoban_limit": ("auto_ban_limit", "Лимит алмазов для автобана (в 💎)"),
}


async def admin_economy_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    video_price = await get_setting("video_price")
    photo_price = await get_setting("photo_price")
    referral_reward = await get_setting("referral_reward")
    autoban_limit = await get_setting("auto_ban_limit")
    text = (
        "⚙️ <b>Настройки экономики бота</b>\n\n"
        f"📺 Цена видео: <b>{video_price} 💎</b>\n"
        f"📸 Цена фото: <b>{photo_price} 💎</b>\n"
        f"👥 Награда за реферала: <b>{referral_reward} 💎</b>\n"
        f"🚫 Лимит автобана: <b>{autoban_limit} 💎</b>"
    )
    kb = InlineKeyboardBuilder()
    for key, (_, label) in ECONOMY_SETTINGS_MAP.items():
        kb.button(text=label, callback_data=key)
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def eco_set_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    key, label = ECONOMY_SETTINGS_MAP[callback.data]
    await state.update_data(economy_key=key, economy_label=label)
    await callback.message.edit_text(f"✍️ Введите новое значение:\n<b>{label}</b>")
    await state.set_state(AdminStates.economy_value)


async def process_economy_value(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = float((message.text or "").strip().replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректное положительное число:")
    data = await state.get_data()
    await state.clear()
    key = data.get("economy_key")
    label = data.get("economy_label", key)
    if not key:
        return await message.answer("❌ Параметр не выбран.")
    val_str = str(int(val)) if val == int(val) else str(val)
    await set_setting(key, val_str)
    await message.answer(f"✅ Параметр «{label}» обновлён: <b>{val_str}</b>", reply_markup=admin_menu())


async def admin_export_users(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer("⏳ Формирую файл экспорта...")
    async with get_db().execute(
        "SELECT user_id, username, first_name, diamonds, premium, is_banned, banned_until, referred_by FROM users"
    ) as cur:
        rows = await cur.fetchall()
    export_path = DATA_DIR / "export_users.csv"
    with open(export_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "first_name", "diamonds", "premium", "is_banned", "banned_until", "referred_by"])
        writer.writerows(rows)
    await bot.send_document(callback.from_user.id, FSInputFile(export_path), caption=f"📤 Экспорт пользователей ({len(rows)} записей)")


async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    clause, params = not_admin_filter("user_id")
    async with get_db().execute("SELECT COUNT(*) FROM users") as cur:
        total_users = (await cur.fetchone())[0]
    async with get_db().execute(f"SELECT COALESCE(SUM(diamonds), 0) FROM users WHERE diamonds >= 0 AND {clause}", params) as cur:
        positive_diamonds = (await cur.fetchone())[0]
    async with get_db().execute(f"SELECT COALESCE(SUM(diamonds), 0) FROM users WHERE diamonds < 0 AND {clause}", params) as cur:
        negative_diamonds = (await cur.fetchone())[0]
    async with get_db().execute("SELECT COUNT(*) FROM users WHERE is_banned = 1 OR banned_until > ?", (int(time.time()),)) as cur:
        banned_count = (await cur.fetchone())[0]
    async with get_db().execute("SELECT COUNT(*) FROM users WHERE premium > 0") as cur:
        premium_count = (await cur.fetchone())[0]
    async with get_db().execute("SELECT COUNT(*) FROM promo_codes") as cur:
        promo_count = (await cur.fetchone())[0]

    x2_active = "✅ Активен" if await is_event_active("global_x2_until") else "❌ Выключен"
    is_disc = await is_event_active("global_discount_until")
    pct = await get_setting("global_discount_percent")
    disc_active = f"✅ Активен (-{pct}%)" if is_disc else "❌ Выключен"
    x3_stars = "✅ Активен" if await is_event_active("global_x3_stars_until") else "❌ Выключен"
    free_view = "✅ Активен" if await is_event_active("global_free_view_until") else "❌ Выключен"
    lucky_hour = "✅ Активен" if await is_event_active("global_lucky_hour_until") else "❌ Выключен"

    text = (
        "📊 <b>Статистика Системы:</b>\n\n"
        f"👥 Пользователей в БД: <b>{total_users}</b>\n"
        f"💎 Алмазов в плюсе: <b>{positive_diamonds:g}</b>\n"
        f"📉 Алмазов в минусе: <b>{negative_diamonds:g}</b>\n"
        f"🚫 Забанено: <b>{banned_count}</b>\n"
        f"👑 С премиум-статусом: <b>{premium_count}</b>\n"
        f"🎫 Активных промокодов: <b>{promo_count}</b>\n"
        f"🪞 Активных ботов в пуле: <b>{len(GLOBAL_BOTS_POOL)}</b>\n\n"
        "🔥 <b>Текущие Ивенты:</b>\n"
        f"🚀 Глобальный х2 реф: {x2_active}\n"
        f"📉 Скидки в шопе: {disc_active}\n"
        f"⚡️ Х3 Пополнение (Stars): {x3_stars}\n"
        f"🆓 Бесплатные просмотры: {free_view}\n"
        f"🍀 Счастливый час (+2 💎): {lucky_hour}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="admin_enter")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# ========================= EVENTS / MAILING =========================

async def admin_events_panel(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.message.edit_text("🔥 <b>Управление Ивентами</b>\n\nВыберите тип ивента:", reply_markup=admin_events_kb())


async def ev_setup_x2(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("⏳ <b>Ивент: х2 Рефералы</b>\n\nВведите время: <code>2h</code>, <code>30m</code> или число часов.")
    await state.update_data(event_type="x2")
    await state.set_state(AdminStates.event_hours)


async def ev_setup_x3_stars(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("⚡️ <b>Ивент: Х3 К покупкам Stars</b>\n\nВведите время: <code>2h</code>, <code>30m</code> или число часов.")
    await state.update_data(event_type="x3_stars")
    await state.set_state(AdminStates.event_hours)


async def ev_setup_free_view(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("🆓 <b>Ивент: Бесплатный Просмотр</b>\n\nВведите время: <code>2h</code>, <code>30m</code> или число часов.")
    await state.update_data(event_type="free_view")
    await state.set_state(AdminStates.event_hours)


async def ev_setup_lucky_hour(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("🍀 <b>Ивент: Счастливый Час</b>\n\nВведите время: <code>2h</code>, <code>30m</code> или число часов.")
    await state.update_data(event_type="lucky_hour")
    await state.set_state(AdminStates.event_hours)


async def ev_setup_discount(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("📉 <b>Ивент: Скидки</b>\n\nВведите процент скидки от 1 до 99:")
    await state.set_state(AdminStates.event_percent)


async def process_event_percent(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 99):
        return await message.answer("❌ Введите корректный процент от 1 до 99:")
    await state.update_data(discount_pct=int(text), event_type="discount")
    await message.answer("⏳ Введите время действия скидок: <code>2h</code>, <code>30m</code> или число часов.")
    await state.set_state(AdminStates.event_hours)


async def process_event_hours(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parsed = parse_duration_input(message.text or "")
    if not parsed:
        return await message.answer("❌ Некорректный формат. Например: <code>2h</code>, <code>30m</code> или число часов.")
    delta, duration_label = parsed
    data = await state.get_data()
    await state.clear()
    etype = data.get("event_type")
    until_time = (datetime.now() + delta).isoformat()

    if etype == "x2":
        await set_setting("global_x2_until", until_time)
        await message.answer("✅ Глобальный ивент запущен!")
        asyncio.create_task(broadcast_event_start("🚀 ДВОЙНЫЕ НАГРАДЫ ЗА ДРУЗЕЙ (х2)", "За каждого приглашенного реферала выплата удваивается.", duration_label))
    elif etype == "discount":
        pct = data.get("discount_pct", 30)
        await set_setting("global_discount_percent", str(pct))
        await set_setting("global_discount_until", until_time)
        await message.answer(f"✅ Ивент Скидки -{pct}% запущен!")
        asyncio.create_task(broadcast_event_start(f"📉 СКИДКИ В МАГАЗИНЕ (-{pct}%)", f"Цены в магазине снижены на {pct}%.", duration_label))
    elif etype == "x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await message.answer("✅ Ивент Х3 запущен!")
        asyncio.create_task(broadcast_event_start("⚡️ Х3 К ПОКУПКАМ", "Любая покупка алмазов через Telegram Stars увеличивается в 3 раза.", duration_label))
    elif etype == "free_view":
        await set_setting("global_free_view_until", until_time)
        await message.answer("✅ Ивент Бесплатный Просмотр запущен!")
        asyncio.create_task(broadcast_event_start("🆓 БЕСПЛАТНЫЙ ПРОСМОТР", "Просмотр видео и фото временно бесплатный.", duration_label))
    elif etype == "lucky_hour":
        await set_setting("global_lucky_hour_until", until_time)
        await message.answer("✅ Ивент Счастливый Час запущен!")
        asyncio.create_task(broadcast_event_start("🍀 СЧАСТЛИВЫЙ ЧАС (+2 💎)", "За просмотр медиа начисляется +2 💎.", duration_label))


async def ev_setup_giveaway(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("🎁 <b>Раздача Алмазов</b>\n\nВведите количество алмазов для каждого подписанного пользователя:")
    await state.set_state(AdminStates.event_giveaway)


async def process_event_giveaway(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        return await message.answer("❌ Введите целое число:")
    amount = int(text)
    await state.clear()
    msg = await message.answer("⏳ Проверяю подписки и начисляю алмазы...")
    if not GLOBAL_BOTS_POOL:
        return await msg.edit_text("❌ Нет активных ботов.")
    bot_worker = GLOBAL_BOTS_POOL[0]
    async with get_db().execute("SELECT user_id FROM users") as cur:
        users = await cur.fetchall()
    given = 0
    for (uid,) in users:
        try:
            if await check_subscription(uid, bot_worker):
                await add_diamonds(uid, float(amount))
                given += 1
        except Exception:
            continue
    await msg.edit_text(f"✅ Раздача завершена! +{amount} 💎 для {given} пользователей.")
    asyncio.create_task(broadcast_event_start("🎁 РАЗДАЧА", f"На баланс активным подписанным пользователям начислено по <b>+{amount} 💎</b>.", None))


async def admin_mail(callback: CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        await callback.message.edit_text("📢 Введите текст рассылки:")
        await state.set_state(AdminStates.mailing_text)


async def process_admin_mailing(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text or ""
    await state.clear()
    await message.answer("⏳ Рассылка запущена...")
    await send_to_all_bots(text)
    await message.answer("✅ Рассылка завершена.")


# ========================= SHOP =========================

async def shop_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    prem_status = "❌ Нет" if udata["premium"] == 0 else ("🌟 Premium" if udata["premium"] == 1 else "🔥 Premium+")
    keep_status = "✅ Да" if udata["keep_videos"] == 1 or udata["premium"] == 2 else "❌ Нет"
    boost_status = "❌ Нет"
    if udata["x2_until"] and datetime.fromisoformat(udata["x2_until"]) > datetime.now():
        boost_status = f"✅ Активен до {datetime.fromisoformat(udata['x2_until']).strftime('%H:%M %d.%m')}"

    disc_text = ""
    if await is_event_active("global_discount_until"):
        pct = await get_setting("global_discount_percent")
        timer = await get_event_remaining_time("global_discount_until")
        disc_text = f"\n⚠️ <b>🔥 СКИДКА -{pct}% (Осталось: {timer})</b>"
    if await is_event_active("global_x3_stars_until"):
        timer = await get_event_remaining_time("global_x3_stars_until")
        disc_text += f"\n⚠️ <b>⚡️ Х3 АЛМАЗЫ ПРИ ПОКУПКЕ! ({timer})</b>"

    text = (
        f"🛒 <b>Магазин категорий</b>{disc_text}\n\n"
        f"💰 Баланс: <b>{udata['diamonds']:g}</b> 💎\n"
        f"👑 Премиум: <b>{prem_status}</b>\n"
        f"🚀 Буст х2: <b>{boost_status}</b>\n"
        f"♾ Навсегда: <b>{keep_status}</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=shop_categories_kb())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=shop_categories_kb())


async def cat_diamonds(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text(
        "💎 <b>Пополнение алмазов (Telegram Stars)</b>\n\n<i>Курс: 1 алмаз = 0.8 звезд</i>",
        reply_markup=shop_diamonds_kb(discount_pct=pct, timer=timer),
    )


async def stars_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✍️ Введите желаемое количество алмазов для покупки (минимум 10):")
    await state.set_state(ShopStates.custom_diamonds)


async def process_custom_diamonds(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 10:
        return await message.answer("❌ Введите корректное число алмазов (от 10 и выше):")
    diamonds = int(text)
    await state.clear()
    stars_price = max(1, int(diamonds * 0.8 + 0.999))
    if await is_event_active("global_discount_until"):
        pct = int(await get_setting("global_discount_percent"))
        stars_price = max(1, int(stars_price * (1 - pct / 100)))
    try:
        payment_link = await generate_payment_link(
            message.from_user.id,
            "diamonds",
            {"amount": diamonds},
            stars_price,
            current_bot_token(bot),
        )
    except RuntimeError:
        return await message.answer("❌ Бот оплаты не запущен. Попробуйте позже.")
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_diamonds")
    kb.adjust(1)
    await message.answer(
        f"💎 <b>Покупка {diamonds} алмазов</b>\n\n"
        f"💰 Сумма: {stars_price} ⭐️\n\n"
        f"⚠️ Оплата производится через отдельного бота.",
        reply_markup=kb.as_markup(),
    )


async def buy_diamonds_stars(callback: CallbackQuery, bot: Bot):
    rates = {"stars_100": (100, 80), "stars_250": (250, 200), "stars_500": (500, 400)}
    if callback.data not in rates:
        return
    diamonds, stars_price = rates[callback.data]
    if await is_event_active("global_discount_until"):
        pct = int(await get_setting("global_discount_percent"))
        stars_price = max(1, int(stars_price * (1 - pct / 100)))
    try:
        payment_link = await generate_payment_link(
            callback.from_user.id,
            "diamonds",
            {"amount": diamonds},
            stars_price,
            current_bot_token(bot),
        )
    except RuntimeError:
        return await callback.answer("❌ Бот оплаты не запущен.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_diamonds")
    kb.adjust(1)
    await callback.message.edit_text(
        f"💎 <b>Покупка {diamonds} алмазов</b>\n\n"
        f"💰 Сумма: {stars_price} ⭐️\n\n"
        f"⚠️ Оплата через отдельного бота.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


async def cat_abilities(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text(
        "⚡ <b>Магазин способностей (оплата Telegram Stars)</b>",
        reply_markup=shop_abilities_kb(discount_pct=pct, timer=timer),
    )


async def buy_boost_x2(callback: CallbackQuery, bot: Bot):
    pct = int(await get_setting("global_discount_percent")) if await is_event_active("global_discount_until") else 0
    price = max(1, int(50 * (1 - pct / 100)))
    try:
        payment_link = await generate_payment_link(callback.from_user.id, "ability_x2", {}, price, current_bot_token(bot))
    except RuntimeError:
        return await callback.answer("❌ Бот оплаты не запущен.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_abilities")
    kb.adjust(1)
    await callback.message.edit_text(f"🚀 <b>Буст х2 Рефералы (24ч)</b>\n\n💰 Сумма: {price} ⭐️", reply_markup=kb.as_markup())
    await callback.answer()


async def buy_keep_videos(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    if udata["keep_videos"] == 1 or udata["premium"] == 2:
        return await callback.answer("Уже активно!", show_alert=True)
    pct = int(await get_setting("global_discount_percent")) if await is_event_active("global_discount_until") else 0
    price = max(1, int(150 * (1 - pct / 100)))
    try:
        payment_link = await generate_payment_link(user_id, "ability_keep_videos", {}, price, current_bot_token(bot))
    except RuntimeError:
        return await callback.answer("❌ Бот оплаты не запущен.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_abilities")
    kb.adjust(1)
    await callback.message.edit_text(f"♾ <b>Video навсегда</b>\n\n💰 Сумма: {price} ⭐️", reply_markup=kb.as_markup())
    await callback.answer()


async def cat_premium(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with get_db().execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] < 0:
        return await callback.answer("❌ У вас отрицательный баланс!", show_alert=True)
    pct = int(await get_setting("global_discount_percent")) if await is_event_active("global_discount_until") else 0
    timer = await get_event_remaining_time("global_discount_until")
    await callback.message.edit_text("👑 <b>Премиум подписки</b>", reply_markup=shop_premium_kb(discount_pct=pct, timer=timer))


async def buy_prem_normal(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    if udata["diamonds"] < 0:
        return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    if udata["premium"] >= 1:
        return await callback.answer("Уже активно!", show_alert=True)
    pct = int(await get_setting("global_discount_percent")) if await is_event_active("global_discount_until") else 0
    price = max(1, int(1500 * (1 - pct / 100)))
    if udata["diamonds"] < price:
        return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await get_db().execute("UPDATE users SET diamonds = diamonds - ?, premium = 1 WHERE user_id = ? AND diamonds >= ?", (price, user_id, price))
    await get_db().commit()
    await callback.answer("👑 PREMIUM статус активирован!", show_alert=True)
    await shop_main(callback)


async def buy_prem_plus(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name, callback.from_user.username)
    if udata["diamonds"] < 0:
        return await callback.answer("❌ Баланс в минусе!", show_alert=True)
    if udata["premium"] == 2:
        return await callback.answer("Уже активно!", show_alert=True)
    pct = int(await get_setting("global_discount_percent")) if await is_event_active("global_discount_until") else 0
    price = max(1, int(2000 * (1 - pct / 100)))
    if udata["diamonds"] < price:
        return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await get_db().execute("UPDATE users SET diamonds = diamonds - ?, premium = 2 WHERE user_id = ? AND diamonds >= ?", (price, user_id, price))
    await get_db().commit()
    await callback.answer("🔥 PREMIUM+ статус активирован!", show_alert=True)
    await shop_main(callback)


async def back_main(callback: CallbackQuery):
    udata = await get_user_data(callback.from_user.id, callback.from_user.first_name, callback.from_user.username)
    await callback.message.edit_text(
        f"💎 Баланс: <b>{udata['diamonds']:g}</b> алмазов",
        reply_markup=await main_menu(callback.from_user.id),
    )


async def static_callbacks(callback: CallbackQuery, bot: Bot):
    if callback.data == "referral":
        me = await bot.get_me()
        try:
            ref_reward = float(await get_setting("referral_reward"))
        except (ValueError, TypeError):
            ref_reward = 4.0
        kb = InlineKeyboardBuilder()
        kb.button(text="◀️ Назад", callback_data="back_main")
        await callback.message.edit_text(
            f"👥 Реф. ссылка:\n<code>https://t.me/{me.username}?start={callback.from_user.id}</code>\n\n"
            f"Приглашение: +{ref_reward:g} 💎\n\n"
            "<i>Алмазы поступят после подписки приглашенного на каналы.</i>",
            reply_markup=kb.as_markup(),
        )
    elif callback.data == "support":
        kb = InlineKeyboardBuilder()
        kb.button(text="◀️ Назад", callback_data="back_main")
        await callback.message.edit_text("🛠 ТП: @Klubnichka_admin", reply_markup=kb.as_markup())


# ========================= PACKS =========================

async def cat_packs(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🌟 Паки знаменитостей", callback_data="celebrity_packs")
    kb.button(text="📦 Прочие паки", callback_data="other_packs")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    text = "📦 <b>Раздел Паков</b>\n\nВыберите категорию:"
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


async def celebrity_packs_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for pid, pack in PACKSZVEZDA.items():
        kb.button(text=f"📦 {pack['name']} — {pack['price']} ⭐️", callback_data=f"pack_preview_{pid}")
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)
    text = "🌟 <b>Паки знаменитостей</b>\n\nВыберите пак:" if PACKSZVEZDA else "🌟 <b>Паки не настроены.</b>"
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def other_packs_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for pid, pack in PROCHIEPAKI.items():
        kb.button(text=f"📦 {pack['name']} — {pack['price']} ⭐️", callback_data=f"pack_preview_{pid}")
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)
    text = "📦 <b>Прочие паки</b>\n\nВыберите пак:" if PROCHIEPAKI else "📦 <b>Паки не настроены.</b>"
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


async def pack_preview(callback: CallbackQuery):
    pack_id = int(callback.data.split("_")[-1])
    pack = PACKSZVEZDA.get(pack_id) or PROCHIEPAKI.get(pack_id)
    if not pack:
        return await callback.answer("❌ Пак не найден", show_alert=True)
    images: list[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.PNG", "*.WEBP"):
        images.extend(pack["folder"].glob(ext))
    if not images:
        return await callback.answer("❌ В папке пака нет изображений для превью.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💎 Купить за {pack['price']} ⭐", callback_data=f"buy_mega_pack_{pack_id}")
    kb.button(text="◀️ Назад к пакам", callback_data="cat_packs")
    kb.adjust(1)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer_photo(
        photo=FSInputFile(random.choice(images)),
        caption=f"📦 <b>{pack['name']}</b>\n💰 Цена: <b>{pack['price']} ⭐</b>\n\nНажмите кнопку ниже для покупки.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


async def buy_mega_pack(callback: CallbackQuery, bot: Bot):
    pack_id = int(callback.data.split("_")[-1])
    pack = PACKSZVEZDA.get(pack_id) or PROCHIEPAKI.get(pack_id)
    if not pack:
        return await callback.answer("❌ Пак не найден", show_alert=True)
    if not pack.get("mega_link"):
        return await callback.answer("❌ У этого пака не настроена ссылка.", show_alert=True)
    try:
        payment_link = await generate_payment_link(
            callback.from_user.id,
            "mega_pack",
            {"name": pack["name"], "mega_link": pack["mega_link"]},
            int(pack["price"]),
            current_bot_token(bot),
        )
    except RuntimeError:
        return await callback.answer("❌ Бот оплаты не запущен.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=payment_link)
    kb.button(text="◀️ Назад", callback_data="cat_packs")
    kb.adjust(1)
    text = f"📦 <b>{pack['name']}</b>\n\n💰 Сумма: {pack['price']} ⭐️\n\n⚠️ Оплата через отдельного бота."
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


# ========================= CASINO =========================

async def casino_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id)
    
    daily_won = await check_and_reset_daily_win(user_id)
    if daily_won >= 100:
        return await callback.answer("❌ Вы уже выиграли 100 алмазов сегодня. Лимит исчерпан!", show_alert=True)
    
    text = (
        "🎮 <b>Казино</b>\n\n"
        f"💰 Баланс: <b>{udata['diamonds']:g}</b> 💎\n\n"
        "Выбери игру:\n\n"
        "🎲 Кости — 4,5,6 — x2\n"
        "⚽️ Футбол — Гол — x1.5\n"
        "🎯 Дартс — Центр — x3\n"
        "🏀 Баскетбол — Попал — x1.5\n"
        "🎰 Слоты — Удача — x5\n"
        "🎳 Боулинг — Страйк — x2"
    )
    await callback.message.edit_text(text, reply_markup=casino_menu())


async def choose_bet(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data
    names = {
        "game_dice": "🎲 Кости",
        "game_football": "⚽️ Футбол",
        "game_darts": "🎯 Дартс",
        "game_basket": "🏀 Баскетбол",
        "game_slots": "🎰 Слоты",
        "game_bowling": "🎳 Боулинг",
    }
    await state.update_data(game=game_type)
    await callback.message.edit_text(f"🎮 <b>{names.get(game_type, 'Игра')}</b>\n\nВыберите ставку:", reply_markup=bet_keyboard(game_type))


async def process_bet(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split("_")
    bet = int(parts[-1])
    game_callback = "_".join(parts[1:-1])
    user_id = callback.from_user.id
    udata = await get_user_data(user_id)
    if udata["diamonds"] < bet:
        return await callback.answer("❌ Недостаточно алмазов!", show_alert=True)
    await get_db().execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (bet, user_id))
    await get_db().commit()
    await state.update_data(bet=bet, game=game_callback)
    await play_animated_game(callback, bot, state, game_callback, bet)


async def play_animated_game(callback: CallbackQuery, bot: Bot, state: FSMContext, game_type: str, bet: int):
    emoji_map = {
        "game_dice": "🎲",
        "game_football": "⚽",
        "game_darts": "🎯",
        "game_basket": "🏀",
        "game_slots": "🎰",
        "game_bowling": "🎳",
    }
    daily_won = await check_and_reset_daily_win(callback.from_user.id)
    if daily_won >= 100:
        return await callback.answer("❌ Дневной лимит выигрыша исчерпан (100 💎)", show_alert=True)

    dice_msg = await bot.send_dice(chat_id=callback.from_user.id, emoji=emoji_map.get(game_type, "🎲"))
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
            "game_bowling": (5, 2.0),
        }
        threshold, multiplier = rules.get(game_type, (4, 2.0))
        win = value >= threshold

    win_amount = int(bet * multiplier) if win else 0
    if win and daily_won + win_amount > 100:
        win_amount = max(0, int(100 - daily_won))
        win = win_amount > 0
    if win:
        await add_diamonds(callback.from_user.id, win_amount)
        await add_daily_win(callback.from_user.id, win_amount)
        result = f"🎉 <b>ВЫИГРЫШ!</b>\n\nВы выиграли <b>{win_amount} 💎</b> (x{multiplier:g})"
    else:
        result = "😔 <b>Проигрыш</b>\nСтавка сгорела."

    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 Играть ещё", callback_data="casino_menu")
    kb.button(text="◀️ В меню", callback_data="back_main")
    kb.adjust(1)
    balance = (await get_user_data(callback.from_user.id))["diamonds"]
    await bot.send_message(callback.from_user.id, f"{result}\n\n💰 Текущий баланс: <b>{balance:g}</b> 💎", reply_markup=kb.as_markup())
    await state.clear()


async def check_and_reset_daily_win(user_id: int) -> float:
    today = datetime.now().date().isoformat()
    async with get_db().execute("SELECT daily_won, daily_reset_date FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return 0.0
    daily_won, reset_date = row
    if reset_date != today:
        await get_db().execute("UPDATE users SET daily_won = 0, daily_reset_date = ? WHERE user_id = ?", (today, user_id))
        await get_db().commit()
        return 0.0
    return float(daily_won or 0)


async def add_daily_win(user_id: int, amount: float):
    await get_db().execute("UPDATE users SET daily_won = daily_won + ? WHERE user_id = ?", (amount, user_id))
    await get_db().commit()


# ========================= SYSTEM TASKS =========================

async def delete_old_videos():
    while True:
        await asyncio.sleep(30)
        try:
            async with get_db().execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (datetime.now().isoformat(),)) as cur:
                rows = await cur.fetchall()
            if rows and GLOBAL_BOTS_POOL:
                bot = GLOBAL_BOTS_POOL[0]
                for message_id, chat_id in rows:
                    try:
                        await bot.delete_message(chat_id, message_id)
                    except Exception:
                        pass
                    await get_db().execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
                await get_db().commit()
        except Exception as exc:
            logger.warning("delete_old_videos failed: %s", exc)

async def log_bot_status() -> None:
    status_text = "🤖 <b>СТАТУС БОТОВ:</b>\n\n"
    for token, username in ACTIVE_BOTS.items():
        kind = "главный" if token in MAIN_BOTS else "зеркало"
        status_text += f"✅ @{username} — активен ({kind})\n"

    status_text += f"\n👥 Всего ботов: <b>{len(ACTIVE_BOTS)}</b>\n"
    status_text += f"💳 Бот оплаты: @{PAYMENT_BOT_USERNAME or 'не запущен'}"
    
    await send_log(status_text)
    
async def heartbeat_checker():
    while True:
        await asyncio.sleep(60)
        now = datetime.now().isoformat()
        for token, username in list(ACTIVE_BOTS.items()):
            bot = BOT_INSTANCES.get(token)
            try:
                if bot:
                    await bot.get_me()
                    await get_db().execute(
                        "INSERT OR REPLACE INTO bot_status (token, username, last_heartbeat, is_active) VALUES (?, ?, ?, 1)",
                        (token, username, now),
                    )
                    await get_db().commit()
            except Exception as exc:
                await send_log(f"⚠️ Бот @{username} не отвечает: {exc}")
                await get_db().execute("UPDATE bot_status SET is_active = 0 WHERE token = ?", (token,))
                await get_db().commit()


# ========================= PAYMENT BOT =========================

async def setup_payment_bot_handlers(dp_payment: Dispatcher) -> None:
    @dp_payment.message(Command("start"))
    async def payment_bot_start(message: Message):
        user_id = message.from_user.id
        args = message.text.split() if message.text else []
        if len(args) <= 1 or not args[1].startswith("pay_"):
            kb = InlineKeyboardBuilder()
            if ACTIVE_BOTS:
                username = next(iter(ACTIVE_BOTS.values()))
                kb.button(text="🔙 Вернуться в главного бота", url=f"https://t.me/{username}")
            return await message.answer("💳 <b>Бот для оплаты</b>\n\nИспользуйте ссылку из главного бота.", reply_markup=kb.as_markup())

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
            "mega_pack": order["item_data"].get("name", "Пак"),
            "admin_pack": order["item_data"].get("name", "Пак"),
        }
        title = item_titles.get(order["item_type"], "Покупка")
        try:
            await message.answer_invoice(
                title=title,
                description=f"Оплата: {title}",
                payload=payment_id,
                currency="XTR",
                prices=[LabeledPrice(label="Telegram Stars", amount=int(order["stars_price"]))],
            )
        except Exception as exc:
            logger.error("Failed to create invoice: %s", exc)
            await message.answer("❌ Не удалось создать счёт на оплату. Попробуйте позже.")

    @dp_payment.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        order = await get_order(payment_id=query.invoice_payload)
        if not order or order["status"] != "pending":
            return await query.answer(ok=False, error_message="Заказ более недействителен.")
        await query.answer(ok=True)

    @dp_payment.message(F.successful_payment)
    async def successful_payment(message: Message):
        payment_id = message.successful_payment.invoice_payload
        order = await get_order(payment_id=payment_id)
        if not order:
            return await message.answer("❌ Заказ не найден.")
        claim_id = uuid.uuid4().hex[:16]
        await get_db().execute(
            "UPDATE payment_orders SET status = 'paid', claim_id = ?, paid_at = ? WHERE payment_id = ?",
            (claim_id, datetime.now().isoformat(), payment_id),
        )
        await get_db().commit()
        bot_username = ACTIVE_BOTS.get(order.get("bot_token")) or next(iter(ACTIVE_BOTS.values()), None)
        if not bot_username:
            return await message.answer("✅ Оплата прошла, но главный бот не найден. Обратитесь в поддержку.")
        claim_link = f"https://t.me/{bot_username}?start=claim_{claim_id}"
        kb = InlineKeyboardBuilder()
        kb.button(text="🎁 Получить товар", url=claim_link)
        await message.answer("✅ Оплата прошла успешно!\n\nНажмите кнопку, чтобы получить товар:", reply_markup=kb.as_markup())
        await send_log(f"💳 Оплата {payment_id} от @{message.from_user.username or message.from_user.first_name}")


# ========================= ROUTER / STARTUP =========================

def create_router() -> Router:
    router = Router()

    router.message(Command("start"))(start)
    router.callback_query(F.data == "check_sub")(check_sub)
    router.callback_query(F.data == "watch")(watch)
    router.callback_query(F.data == "watch_photo")(watch_photo)

    router.callback_query(F.data == "mirror_menu")(mirror_menu)
    router.callback_query(F.data == "create_mirror_process")(create_mirror_process)
    router.message(MirrorStates.enter_token)(process_mirror_token)
    router.callback_query(F.data == "my_mirrors")(my_mirrors)
    router.callback_query(F.data == "restart_mirrors")(restart_mirrors)
    router.callback_query(F.data == "no_tokens")(no_tokens)

    router.callback_query(F.data == "daily_reward")(daily_reward)
    router.callback_query(F.data == "daily_reward_disabled")(daily_reward_disabled)

    router.callback_query(F.data == "admin_tokens")(admin_tokens)
    router.callback_query(F.data == "admin_add_tokens")(admin_add_tokens)
    router.message(AdminStates.add_token)(process_add_tokens)
    router.callback_query(F.data == "admin_view_tokens")(admin_view_tokens)

    router.callback_query(F.data == "promo_menu")(promo_menu)
    router.callback_query(F.data == "promo_activate")(promo_activate)
    router.message(PromoStates.activate_code)(process_promo_activate)
    router.callback_query(F.data == "promo_create")(promo_create)
    router.message(PromoStates.create_code)(process_promo_code)
    router.message(PromoStates.create_reward)(process_promo_reward)
    router.message(PromoStates.create_uses)(process_promo_uses)

    router.callback_query(F.data == "leaderboard")(leaderboard_menu)
    router.callback_query(F.data == "admin_enter")(admin_enter)
    router.callback_query(F.data == "admin_manage_users")(admin_manage_users)
    router.message(AdminStates.user_manage_id)(process_user_search)
    router.callback_query(F.data == "adm_grant_premium_menu")(adm_grant_premium_menu)
    router.callback_query(F.data.startswith("adm_grant_prem_"))(adm_grant_prem)
    router.callback_query(F.data == "adm_change_diamonds")(adm_change_diamonds_handler)
    router.message(AdminStates.user_change_diamonds)(process_user_change_diamonds)
    router.callback_query(F.data == "adm_ban_time")(adm_ban_time_handler)
    router.message(AdminStates.user_ban_time)(process_user_ban_time)
    router.callback_query(F.data == "adm_ban_forever")(adm_ban_forever)
    router.callback_query(F.data == "adm_unban")(adm_unban)
    
    # Роутеры для админ-управления зеркалами
    router.callback_query(F.data == "admin_manage_mirrors")(admin_manage_mirrors)
    router.callback_query(F.data.startswith("adm_mirror_view_"))(admin_mirror_view)
    router.callback_query(F.data.startswith("adm_mirror_del_"))(admin_mirror_delete_callback)
    
    router.callback_query(F.data == "admin_active_promos")(admin_active_promos)
    router.callback_query(F.data.startswith("adm_del_promo_"))(admin_delete_promo_callback)
    router.callback_query(F.data == "admin_delete_all_promos")(admin_delete_all_promos)
    router.callback_query(F.data == "admin_toggle_maintenance")(admin_toggle_maintenance)
    router.callback_query(F.data == "admin_banned_list")(admin_banned_list)
    router.callback_query(F.data.startswith("banlist_unban_"))(banlist_unban)
    router.callback_query(F.data == "admin_list_admins")(admin_list_admins)
    router.callback_query(F.data == "admin_economy")(admin_economy_panel)
    router.callback_query(F.data.in_(set(ECONOMY_SETTINGS_MAP.keys())))(eco_set_start)
    router.message(AdminStates.economy_value)(process_economy_value)
    router.callback_query(F.data == "admin_export_users")(admin_export_users)
    router.callback_query(F.data == "admin_stats")(admin_stats)

    router.callback_query(F.data == "admin_events_panel")(admin_events_panel)
    router.callback_query(F.data == "ev_setup_x2")(ev_setup_x2)
    router.callback_query(F.data == "ev_setup_x3_stars")(ev_setup_x3_stars)
    router.callback_query(F.data == "ev_setup_free_view")(ev_setup_free_view)
    router.callback_query(F.data == "ev_setup_lucky_hour")(ev_setup_lucky_hour)
    router.callback_query(F.data == "ev_setup_discount")(ev_setup_discount)
    router.message(AdminStates.event_percent)(process_event_percent)
    router.message(AdminStates.event_hours)(process_event_hours)
    router.callback_query(F.data == "ev_setup_giveaway")(ev_setup_giveaway)
    router.message(AdminStates.event_giveaway)(process_event_giveaway)
    router.callback_query(F.data == "admin_mail")(admin_mail)
    router.message(AdminStates.mailing_text)(process_admin_mailing)

    router.callback_query(F.data == "shop_main")(shop_main)
    router.callback_query(F.data == "cat_diamonds")(cat_diamonds)
    router.callback_query(F.data == "stars_custom")(stars_custom)
    router.message(ShopStates.custom_diamonds)(process_custom_diamonds)
    router.callback_query(F.data.startswith("stars_"))(buy_diamonds_stars)
    router.callback_query(F.data == "cat_abilities")(cat_abilities)
    router.callback_query(F.data == "buy_boost_x2")(buy_boost_x2)
    router.callback_query(F.data == "buy_keep_videos")(buy_keep_videos)
    router.callback_query(F.data == "cat_premium")(cat_premium)
    router.callback_query(F.data == "buy_prem_normal")(buy_prem_normal)
    router.callback_query(F.data == "buy_prem_plus")(buy_prem_plus)
    router.callback_query(F.data == "back_main")(back_main)
    router.callback_query(F.data.in_({"referral", "support"}))(static_callbacks)

    router.callback_query(F.data == "cat_packs")(cat_packs)
    router.callback_query(F.data == "celebrity_packs")(celebrity_packs_menu)
    router.callback_query(F.data == "other_packs")(other_packs_menu)
    router.callback_query(F.data.startswith("pack_preview_"))(pack_preview)
    router.callback_query(F.data.startswith("buy_mega_pack_"))(buy_mega_pack)

    router.callback_query(F.data == "casino_menu")(casino_main)
    router.callback_query(F.data.startswith("game_"))(choose_bet)
    router.callback_query(F.data.startswith("bet_"))(process_bet)
    
    @router.message(Command("status"))
    async def cmd_status(message: Message):
        if message.chat.id != LOG_GROUP_ID:
            return
        await log_bot_status()

    @router.message(Command("tokens"))
    async def cmd_tokens(message: Message):
        if message.chat.id != LOG_GROUP_ID:
            return
        await admin_tokens(message)

    @router.message(Command("mirrors"))
    async def cmd_mirrors(message: Message):
        if message.chat.id != LOG_GROUP_ID:
            return
        stats = await tokens_db.get_stats() if hasattr(tokens_db, "get_stats") else {}
        text = f"🪞 <b>Зеркала:</b>\nВсего токенов: {stats.get('total', 0)}\nАктивных: {stats.get('active', 0)}"
        await message.answer(text)

    @router.message(Command("restart_all"))
    async def cmd_restart_all(message: Message):
        if message.chat.id != LOG_GROUP_ID:
            return
        await send_log("🔄 Перезапуск всех зеркал по команде из логов...")
    return router


def configure_dispatcher(dp: Dispatcher) -> None:
    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())
    dp.include_router(create_router())


async def start_mirror_bot(token: str, username: str) -> bool:
    try:
        old_task = MIRROR_TASKS.pop(token, None)
        if old_task:
            old_task.cancel()
        old_bot = MIRROR_BOTS.pop(token, None)
        if old_bot:
            try:
                GLOBAL_BOTS_POOL[:] = [bot for bot in GLOBAL_BOTS_POOL if bot is not old_bot]
                await old_bot.session.close()
            except Exception:
                pass

        mirror_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await mirror_bot.delete_webhook(drop_pending_updates=True)
        dp_mirror = Dispatcher()
        configure_dispatcher(dp_mirror)
        task = asyncio.create_task(dp_mirror.start_polling(mirror_bot, allowed_updates=dp_mirror.resolve_used_update_types()))

        MIRROR_BOTS[token] = mirror_bot
        BOT_INSTANCES[token] = mirror_bot
        ACTIVE_BOTS[token] = username
        GLOBAL_BOTS_POOL.append(mirror_bot)
        MIRROR_TASKS[token] = task
        await get_db().execute(
            "INSERT OR REPLACE INTO bot_status (token, username, last_heartbeat, is_active) VALUES (?, ?, ?, 1)",
            (token, username, datetime.now().isoformat()),
        )
        await get_db().commit()
        return True
    except Exception as exc:
        await send_log(f"❌ Ошибка запуска зеркала @{username}: {exc}")
        return False


async def activate_existing_mirrors() -> int:
    async with get_db().execute(
        "SELECT id, token, bot_username FROM mirrors WHERE status IN ('active', 'pending')"
    ) as cur:
        mirrors = await cur.fetchall()
    activated = 0
    for mirror_id, token, username in mirrors:
        if await start_mirror_bot(token, username):
            await get_db().execute(
                "UPDATE mirrors SET status = 'active', activated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), mirror_id),
            )
            activated += 1
        else:
            await get_db().execute("UPDATE mirrors SET status = 'inactive' WHERE id = ?", (mirror_id,))
    await get_db().commit()
    return activated


# ========================= MAIN =========================
async def main() -> None:
    global PAYMENT_BOT_USERNAME, PAYMENT_BOT_INSTANCE

    if not MAIN_BOT_TOKENS:
        raise RuntimeError("Set MAIN_BOT_TOKENS environment variable with one or more Telegram bot tokens.")
    if not PAYMENT_BOT_TOKEN:
        raise RuntimeError("Set PAYMENT_BOT_TOKEN environment variable.")

    await init_db()

    if isinstance(tokens_db, FallbackTokensDB):
        await tokens_db.init()
        await send_log("📁 Локальная база tokens.db успешно инициализирована")

    await send_log("🚀 Запуск системы...")

    main_bots: list[Bot] = []
    for token in MAIN_BOT_TOKENS:
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await bot.delete_webhook(drop_pending_updates=True)
            me = await bot.get_me()
            username = me.username
            MAIN_BOTS[token] = bot
            ACTIVE_BOTS[token] = username
            BOT_INSTANCES[token] = bot
            GLOBAL_BOTS_POOL.append(bot)
            main_bots.append(bot)
            
            # --- ИСПРАВЛЕНИЕ АВТОМАТИЧЕСКОГО ДОБАВЛЕНИЯ ГЛАВНЫХ БОТОВ (ОТСТУПЫ ИСПРАВЛЕНЫ) ---
            if hasattr(tokens_db, "get_token_by_value"):
                existing_token = await tokens_db.get_token_by_value(token)
                if not existing_token:
                    # Если токена вообще нет в tokens.db — создаем запись
                    await tokens_db.add_token(token, username, None, status='main_bot')
                else:
                    # Если он уже есть, принудительно ставим статус главного бота
                    await tokens_db.update_token_status(token, 'main_bot', is_active=1)
            # ---------------------------------------------------------------------------------

            await get_db().execute(
                "INSERT OR REPLACE INTO bot_status (token, username, last_heartbeat, is_active) VALUES (?, ?, ?, 1)",
                (token, username, datetime.now().isoformat()),
            )
            await get_db().commit()
            await send_log(f"✅ Бот @{username} подготовлен и добавлен в tokens.db", bot)
        except Exception as exc:
            await send_log(f"❌ Ошибка запуска главного бота: {exc}")

    if not main_bots:
        raise RuntimeError("No main bot could be started. Check MAIN_BOT_TOKENS.")

    payment_bot = Bot(token=PAYMENT_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await payment_bot.delete_webhook(drop_pending_updates=True)
    payment_me = await payment_bot.get_me()
    PAYMENT_BOT_USERNAME = payment_me.username
    PAYMENT_BOT_INSTANCE = payment_bot

    main_dp = Dispatcher()
    configure_dispatcher(main_dp)

    payment_dp = Dispatcher()
    await setup_payment_bot_handlers(payment_dp)

    active_process = None
    try:
        import subprocess
        import sys
        from pathlib import Path
        
        active_path = Path(__file__).parent / "active.py"
        if active_path.exists():
            active_process = subprocess.Popen([sys.executable, str(active_path)])
            await send_log(f"✅ active.py успешно запущен (PID: {active_process.pid})")
        else:
            await send_log("⚠️ Файл active.py не найден")
    except Exception as e:
        await send_log(f"❌ Не удалось запустить active.py: {e}")

    tasks = [
        asyncio.create_task(main_dp.start_polling(*main_bots, allowed_updates=main_dp.resolve_used_update_types())),
        asyncio.create_task(payment_dp.start_polling(payment_bot, allowed_updates=payment_dp.resolve_used_update_types())),
        asyncio.create_task(delete_old_videos()),
        asyncio.create_task(heartbeat_checker()),
    ]

    activated = await activate_existing_mirrors()
    await send_log(f"✅ Бот оплаты @{PAYMENT_BOT_USERNAME} запущен")
    if activated:
        await send_log(f"🔄 Активировано зеркал: {activated}")

    await asyncio.sleep(3)
    await log_bot_status()

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if active_process:
            try:
                active_process.terminate()
            except:
                pass
        for bot in list(BOT_INSTANCES.values()) + ([PAYMENT_BOT_INSTANCE] if PAYMENT_BOT_INSTANCE else []):
            try:
                await bot.session.close()
            except:
                pass
            
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен")
    except Exception as exc:
        print(f"❌ Критическая ошибка: {exc}")
        raise
