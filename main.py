import asyncio
import random
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError

# ========================= НАСТРОЙКИ МУЛЬТИБОТА =========================

MAIN_TOKENS = [
    "8971264936:AAEX4G42x3OQRMdjvOJGAJFJdydIVDGp_PE",
    "8749652033:AAGxEa4xA2BU9wEUUcntIH3MfEoRVBniiwQ",
]

ADMIN_IDS = [
    8603534638,  # Вы
    8570452473,  # Второй админ
    8502341995   # Третий admin
]

CHANNELS = [
    (-1004466816546, "Наш канал", "https://t.me/+ryYTkHSQG6VmNjUy"),
    ("@PavelGiftsPG", "Спонсор", "https://t.me/PavelGiftsPG"),
]

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"
db = None

# Глобальный пул запущенных ботов для массовых рассылок по всем токенам
GLOBAL_BOTS_POOL = []

# ========================= СОСТОЯНИЯ (FSM) =========================

class AdminStates(StatesGroup):
    mailing_text = State()
    user_manage_id = State()
    change_balance = State()
    event_percent = State()    # Процент скидки
    event_hours = State()      # Время ивента
    event_giveaway = State()   # Раздача алмазов

class PromoStates(StatesGroup):
    create_code = State()
    create_reward = State()
    create_uses = State()
    activate_code = State()

class MirrorStates(StatesGroup):
    enter_token = State()

# ========================= БАЗА ДАННЫХ =========================

async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT 'Пользователь',
            diamonds INTEGER DEFAULT 8,
            referred_by INTEGER,
            is_banned INTEGER DEFAULT 0,
            premium INTEGER DEFAULT 0,
            x2_until TEXT DEFAULT NULL,
            keep_videos INTEGER DEFAULT 0
        )
    """)
    
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
        CREATE TABLE IF NOT EXISTS mirrors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token TEXT,
            created_at TEXT
        )
    """)
    await db.commit()

# ========================= ХЕЛПЕРЫ ИВЕНТОВ И ДАННЫХ =========================

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

# Функция рассылки, задействующая ВСЕ активные токены (основные + зеркала)
async def send_to_all_bots(text: str):
    if not GLOBAL_BOTS_POOL:
        return
    
    async with db.execute("SELECT user_id FROM users") as cur:
        users = await cur.fetchall()
        
    for (uid,) in users:
        # Пытаемся отправить сообщение через случайного бота из пула, чтобы снизить нагрузку и лимиты Telegram
        bot_worker = random.choice(GLOBAL_BOTS_POOL)
        try:
            await bot_worker.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.03) 
        except Exception:
            # Если бот выдал ошибку, пробуем отправить через первый основной (резервный вариант)
            try:
                await GLOBAL_BOTS_POOL[0].send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.03)
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
    await send_to_all_bots(text)

# ========================= МИДЛВАРЬ БАНА =========================

router = Router()

@router.message.outer_middleware()
@router.callback_query.outer_middleware()
async def ban_middleware(handler, event, data):
    user = data.get("event_from_user")
    if user:
        async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                if isinstance(event, CallbackQuery):
                    try: await event.answer("❌ Вы заблокированы!", show_alert=True)
                    except Exception: pass
                return
    return await handler(event, data)

async def check_subscription(user_id: int, bot: Bot) -> bool:
    for channel_data in CHANNELS:
        channel = channel_data[0] if isinstance(channel_data, (tuple, list)) else channel_data
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def get_user_data(user_id: int, first_name: str = "Пользователь"):
    async with db.execute("SELECT diamonds, premium, x2_until, keep_videos FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, first_name, diamonds) VALUES (?, ?, 8)", (user_id, first_name))
            await db.commit()
            return {"diamonds": 8, "premium": 0, "x2_until": None, "keep_videos": 0}
        await db.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        await db.commit()
        return {"diamonds": row[0], "premium": row[1], "x2_until": row[2], "keep_videos": row[3]}

async def add_diamonds(user_id: int, amount: int):
    await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
    await db.commit()

# ========================= КЛАВИАТУРЫ =========================

def main_menu(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📺 Смотреть видео (6 💎)", callback_data="watch")
    kb.button(text="📸 Посмотреть фото (3 💎)", callback_data="watch_photo")
    kb.button(text="🛒 Магазин 💰", callback_data="shop_main")
    kb.button(text="🎟 Промокоды", callback_data="promo_menu")
    kb.button(text="🪞 Создать зеркало (+20 💎)", callback_data="mirror_menu")
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

def shop_diamonds_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 100 алмазов — 50 ⭐️", callback_data="stars_100")
    kb.button(text="🎁 250 алмазов — 120 ⭐️", callback_data="stars_250")
    kb.button(text="🎁 500 алмазов — 200 ⭐️", callback_data="stars_500")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_abilities_kb(discount_pct: int = 0):
    p1 = int(50 * (1 - discount_pct / 100))
    p2 = int(500 * (1 - discount_pct / 100))
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🚀 х2 от Рефералов (24ч) — {p1} 💎", callback_data="buy_boost_x2")
    kb.button(text=f"♾ Видео навсегда — {p2} 💎", callback_data="buy_keep_videos")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_premium_kb(discount_pct: int = 0):
    p1 = int(1500 * (1 - discount_pct / 100))
    p2 = int(2000 * (1 - discount_pct / 100))
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🌟 Премиум (Все бесплатно) — {p1} 💎", callback_data="buy_prem_normal")
    kb.button(text=f"🔥 Премиум+ (Архивы + Навсегда) — {p2} 💎", callback_data="buy_prem_plus")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📢 Рассылка текста (По всем токенам)", callback_data="admin_mail")
    kb.button(text="🔥 Управление ИВЕНТАМИ", callback_data="admin_events_panel")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_events_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Запустить х2 Рефералы", callback_data="ev_setup_x2")
    kb.button(text="📉 Настроить Скидки % (Кастомные)", callback_data="ev_setup_discount")
    kb.button(text="🎁 Сделать Раздачу Алмазов всем", callback_data="ev_setup_giveaway")
    kb.button(text="⚡️ Запустить х3 Алмазы (Stars)", callback_data="ev_setup_x3_stars")
    kb.button(text="🆓 Запустить Бесплатный Просмотр медиа", callback_data="ev_setup_free_view")
    kb.button(text="◀️ Назад в Админку", callback_data="admin_enter")
    kb.adjust(1)
    return kb.as_markup()

# ========================= ХЕНДЛЕРЫ БОТА =========================

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name
    args = message.text.split()
    
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            async with db.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,)) as cur:
                if not await cur.fetchone():
                    await db.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                    ref_data = await get_user_data(referrer_id)
                    
                    base_reward = 4
                    if await is_event_active("global_x2_until"):
                        base_reward = 8 
                        
                    if ref_data["x2_until"] and datetime.fromisoformat(ref_data["x2_until"]) > datetime.now():
                        base_reward *= 2 
                        
                    await add_diamonds(referrer_id, base_reward)
                    try: await bot.send_message(referrer_id, f"🎉 Новый реферал! Вам зачислено +{base_reward} 💎")
                    except Exception: pass
                    
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
        return await message.answer("👋 Для работы бота подпишись на каналы:", reply_markup=kb.as_markup())
        
    udata = await get_user_data(user_id, name)
    await message.answer(f"👋 Добро пожаловать! 💎\n\nНа балансе: <b>{udata['diamonds']}</b> алмазов", reply_markup=main_menu(user_id))

@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if await check_subscription(user_id, bot):
        await callback.message.edit_text("✅ Подписка подтверждена!", reply_markup=main_menu(user_id))
    else:
        await callback.answer("❌ Ты не подписался на все каналы!", show_alert=True)

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
    disc_text = ""
    if is_disc:
        pct = await get_setting("global_discount_percent")
        disc_text = f"\n⚠️ <b>🔥 ДЕЙСТВУЕТ ГЛОБАЛЬНАЯ СКИДКА -{pct}% НА ВСЁ!</b>"

    if await is_event_active("global_x3_stars_until"):
        disc_text += "\n⚠️ <b>⚡️ ДЕЙСТВУЕТ ИВЕНТ: Х3 АЛМАЗЫ ПРИ ПОКУПКЕ!</b>"

    text = f"🛒 <b>Магазин категорий</b>{disc_text}\n\n💰 Баланс: <b>{udata['diamonds']}</b> 💎\n👑 Премиум: <b>{prem_status}</b>\n🚀 Буст х2: <b>{boost_status}</b>\n♾ Навсегда: <b>{keep_status}</b>"
    try: await callback.message.edit_text(text, reply_markup=shop_categories_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "cat_diamonds")
async def cat_diamonds(callback: CallbackQuery):
    try: await callback.message.edit_text("💎 <b>Пополнение алмазов (Telegram Stars)</b>", reply_markup=shop_diamonds_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("stars_"))
async def buy_diamonds_stars(callback: CallbackQuery):
    rates = {"stars_100": (100, 50), "stars_250": (250, 120), "stars_500": (500, 200)}
    if callback.data in rates:
        diamonds, stars_price = rates[callback.data]
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
    try: await callback.message.edit_text("⚡ <b>Магазин способностей</b>", reply_markup=shop_abilities_kb(discount_pct=pct))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(50 * (1 - pct / 100))
    
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, x2_until = ? WHERE user_id = ?", (price, (datetime.now() + timedelta(hours=24)).isoformat(), user_id))
    await db.commit()
    await callback.answer("🚀 Буст х2 активирован на 24 часа!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["keep_videos"] == 1 or udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(500 * (1 - pct / 100))
    
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, keep_videos = 1 WHERE user_id = ?", (price, user_id))
    await db.commit()
    await callback.answer("♾ Видео теперь сохраняются навсегда!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "cat_premium")
async def cat_premium(callback: CallbackQuery):
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    try: await callback.message.edit_text("👑 <b>Премиум подписки</b>", reply_markup=shop_premium_kb(discount_pct=pct))
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_prem_normal")
async def buy_prem_normal(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] >= 1: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(1500 * (1 - pct / 100))
    
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, premium = 1 WHERE user_id = ?", (price, user_id))
    await db.commit()
    await callback.answer("👑 PREMIUM статус активирован!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_prem_plus")
async def buy_prem_plus(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    is_disc = await is_event_active("global_discount_until")
    pct = int(await get_setting("global_discount_percent")) if is_disc else 0
    price = int(2000 * (1 - pct / 100))
    
    if udata["diamonds"] < price: return await callback.answer(f"❌ Нужно {price} 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - ?, premium = 2 WHERE user_id = ?", (price, user_id))
    await db.commit()
    await callback.answer("🔥 PREMIUM+ статус активирован!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    
    # Проверяем, активен ли ивент бесплатного просмотра
    is_free = await is_event_active("global_free_view_until")
    
    if udata["premium"] == 0 and not is_free:
        if udata["diamonds"] < 6: return await callback.answer("❌ Нужно 6 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ?", (user_id,))
        await db.commit()
        
    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV"))
    if not videos: return await callback.answer("Папка media пуста.", show_alert=True)
    is_forever = (udata["keep_videos"] == 1 or udata["premium"] == 2)
    
    cap = "📹 Ваше видео!" if is_forever else "📹 Видео удалится через 30 минут."
    if is_free: cap += " (🔥 По ивенту БЕСПЛАТНО)"
        
    msg = await bot.send_video(chat_id=user_id, video=FSInputFile(random.choice(videos)), caption=cap)
    if not is_forever:
        await db.execute("INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)", ("", msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()))
        await db.commit()
    await callback.answer()

@router.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    
    is_free = await is_event_active("global_free_view_until")
    
    if udata["premium"] == 0 and not is_free:
        if udata["diamonds"] < 3: return await callback.answer("❌ Нужно 3 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ?", (user_id,))
        await db.commit()
        
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("Папка photo пуста.", show_alert=True)
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)))
    await callback.answer()

@router.callback_query(F.data == "mirror_menu")
async def mirror_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with db.execute("SELECT COUNT(*) FROM mirrors WHERE user_id = ? AND created_at >= ?", (user_id, (datetime.now() - timedelta(days=1)).isoformat())) as cur:
        if (await cur.fetchone())[0] >= 2: return await callback.answer("❌ Лимит: 2 зеркала в сутки.", show_alert=True)
    kb = InlineKeyboardBuilder().button(text="🔗 Подключить токен", callback_data="mirror_start_enter").button(text="◀️ Назад", callback_data="back_main").adjust(1)
    await callback.message.edit_text("🪞 <b>Создание зеркал</b>\nОтправь токен нового бота из @BotFather и получи +20 💎!", reply_markup=kb.as_markup())

@router.callback_query(F.data == "mirror_start_enter")
async def mirror_start_enter(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Отправьте API Токен:")
    await state.set_state(MirrorStates.enter_token)

@router.message(MirrorStates.enter_token)
async def process_mirror_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 30: return await message.answer("❌ Неверный токен.")
    await state.clear()
    
    msg = await message.answer("⏳ Активация зеркала и перезагрузка...")
    try:
        test_bot = Bot(token=token)
        await test_bot.get_me()
        await test_bot.session.close()
        
        await db.execute("INSERT INTO mirrors (user_id, token, created_at) VALUES (?, ?, ?)", (message.from_user.id, token, datetime.now().isoformat()))
        await add_diamonds(message.from_user.id, 20)
        await db.commit()
        
        await msg.edit_text("🎉 Зеркало сохранено! Перезагружаю скрипт...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        await msg.edit_text("❌ Ошибка авторизации токена. Проверьте его в @BotFather.")

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder().button(text="✨ Активировать", callback_data="promo_activate").button(text="➕ Создать", callback_data="promo_create").button(text="◀️ Назад", callback_data="back_main").adjust(1)
    await callback.message.edit_text("🎟 Промокоды:", reply_markup=kb.as_markup())

@router.callback_query(F.data == "promo_activate")
async def promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Введите промокод:")
    await state.set_state(PromoStates.activate_code)

@router.message(PromoStates.activate_code)
async def process_promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.clear()
    async with db.execute("SELECT creator_id, reward, uses_left FROM promo_codes WHERE code = ?", (code,)) as cur: row = await cur.fetchone()
    if not row: return await message.answer("❌ Не найден.")
    cid, reward, left = row
    if left <= 0: return await message.answer("❌ Закончился.")
    if cid == message.from_user.id: return await message.answer("❌ Свой нельзя.")
    
    if left - 1 == 0: await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else: await db.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    await add_diamonds(message.from_user.id, reward)
    await db.commit()
    await message.answer(f"🎉 Активирован! +{reward} 💎")

@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✨ Текст промокода:")
    await state.set_state(PromoStates.create_code)

@router.message(PromoStates.create_code)
async def process_promo_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip().upper())
    await message.answer("💎 Награда за активацию:")
    await state.set_state(PromoStates.create_reward)

@router.message(PromoStates.create_reward)
async def process_promo_reward(message: Message, state: FSMContext):
    await state.update_data(reward=int(message.text))
    await message.answer("👥 Кол-во активаций:")
    await state.set_state(PromoStates.create_uses)

@router.message(PromoStates.create_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    uses = int(message.text)
    data = await state.get_data()
    total = data['reward'] * uses
    bal = await get_user_data(message.from_user.id)
    if bal['diamonds'] < total: return await message.answer("❌ Недостаточно 💎")
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (total, message.from_user.id))
    await db.execute("INSERT INTO promo_codes VALUES (?, ?, ?, ?)", (data['code'], message.from_user.id, data['reward'], uses))
    await db.commit()
    await message.answer(f"✅ Создан {data['code']}")
    await state.clear()

@router.callback_query(F.data == "leaderboard")
async def leaderboard_menu(callback: CallbackQuery):
    async with db.execute("SELECT first_name, diamonds FROM users ORDER BY diamonds DESC LIMIT 5") as cur: rows = await cur.fetchall()
    text = "🏆 <b>Лидеры по алмазам:</b>\n\n"
    for i, r in enumerate(rows, 1): text += f"{i}. {r[0]} — {r[1]} 💎\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    udata = await get_user_data(callback.from_user.id)
    await callback.message.edit_text(f"💎 Баланс: <b>{udata['diamonds']}</b>", reply_markup=main_menu(callback.from_user.id))

@router.callback_query(F.data.in_({"referral", "support"}))
async def static_callbacks(callback: CallbackQuery, bot: Bot):
    if callback.data == "referral":
        me = await bot.get_me()
        await callback.message.edit_text(f"👥 Реф. ссылка:\n<code>https://t.me/{me.username}?start={callback.from_user.id}</code>\n\nПриглашение: +4 💎", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())
    elif callback.data == "support":
        await callback.message.edit_text("🛠 ТП: @твой_юзернейм", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())

# ========================= АДМИН ПАНЕЛЬ И СИСТЕМА ИВЕНТОВ =========================

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id in ADMIN_IDS: 
        await callback.message.edit_text("🛠 <b>Административная Панель</b>:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    async with db.execute("SELECT COUNT(*) FROM users") as cur: total_users = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM mirrors") as cur: total_mirrors = (await cur.fetchone())[0]
    
    x2_active = "✅ Активен" if await is_event_active("global_x2_until") else "❌ Выключен"
    
    is_disc = await is_event_active("global_discount_until")
    pct = await get_setting("global_discount_percent")
    disc_active = f"✅ Активен (-{pct}%)" if is_disc else "❌ Выключен"
    
    x3_stars = "✅ Активен" if await is_event_active("global_x3_stars_until") else "❌ Выключен"
    free_view = "✅ Активен" if await is_event_active("global_free_view_until") else "❌ Выключен"
    
    text = (
        f"📊 <b>Статистика Системы:</b>\n\n"
        f"👥 Пользователей в БД: <b>{total_users}</b>\n"
        f"🪞 Активных ботов в пуле: <b>{len(GLOBAL_BOTS_POOL)}</b> (вкл. зеркала)\n"
        f"🪞 Всего зеркал в базе: <b>{total_mirrors}</b>\n\n"
        f"🔥 <b>Текущие Ивенты:</b>\n"
        f"🚀 Глобальный х2 реф: {x2_active}\n"
        f"📉 Кастомные Скидки в шопе: {disc_active}\n"
        f"⚡️ Х3 Пополнение (Stars): {x3_stars}\n"
        f"🆓 Бесплатные просмотры: {free_view}"
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

# Начало настройки кастомной скидки: сначала запрашиваем процент
@router.callback_query(F.data == "ev_setup_discount")
async def ev_setup_discount(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("📉 <b>Ивент: Кастомные Скидки</b>\n\nШаг 1: Введите процент скидки (только число от 1 до 99, например 35 или 50):")
    await state.set_state(AdminStates.event_percent)

@router.message(AdminStates.event_percent)
async def process_event_percent(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 99):
        return await message.answer("❌ Ошибка! Введите корректный процент скидки (от 1 до 99):")
    
    await state.update_data(discount_pct=int(text))
    await message.answer("⏳ Шаг 2: Введите время действия скидок в <b>ЧАСАХ</b> (целое число):")
    await state.set_state(AdminStates.event_hours)
    await state.update_data(event_type="discount")

@router.message(AdminStates.event_hours)
async def process_event_hours(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("❌ Пожалуйста, введите целое число часов:")
        
    hours = int(text)
    data = await state.get_data()
    etype = data.get("event_type")
    await state.clear()
    
    until_time = (datetime.now() + timedelta(hours=hours)).isoformat()
    
    if etype == "x2":
        await set_setting("global_x2_until", until_time)
        await message.answer(f"✅ Глобальный ивент <b>х2 Рефералы</b> запущен на {hours} ч.!")
        asyncio.create_task(broadcast_event_start(
            title="🚀 ДВОЙНЫЕ НАГРАДЫ ЗА ДРУЗЕЙ (х2)",
            description="С этого момента за каждого приглашенного реферала абсолютно все пользователи получают двойную выплату алмазов!",
            duration_hours=hours
        ))
        
    elif etype == "discount":
        pct = data.get("discount_pct", 30)
        await set_setting("global_discount_percent", str(pct))
        await set_setting("global_discount_until", until_time)
        await message.answer(f"✅ Ивент <b>Скидки -{pct}%</b> успешно запущен на {hours} ч.!")
        asyncio.create_task(broadcast_event_start(
            title=f"📉 ШОК-СКИДКИ В МАГАЗИНЕ (-{pct}%)",
            description=f"Цены на способности, улучшения и премиум-статусы во всех категориях магазина снижены на {pct}%!",
            duration_hours=hours
        ))
        
    elif etype == "x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await message.answer(f"✅ Ивент <b>Х3 Алмазы за Stars</b> запущен на {hours} ч.!")
        asyncio.create_task(broadcast_event_start(
            title="⚡️ АЛМАЗНЫЙ ЛИВЕНЬ (Х3 К ПОКУПКАМ)",
            description="Внимание! Любая покупка алмазов через Telegram Stars увеличивается в 3 раза! Покупаешь 100 — получаешь 300!",
            duration_hours=hours
        ))
        
    elif etype == "free_view":
        await set_setting("global_free_view_until", until_time)
        await message.answer(f"✅ Ивент <b>Бесплатный Просмотр</b> запущен на {hours} ч.!")
        asyncio.create_task(broadcast_event_start(
            title="🆓 АТТРАКЦИОН НЕВИДАННОЙ ЩЕДРОСТИ (0 💎)",
            description="Администрация открыла бесплатный просмотр всех видео и фото для всех пользователей! Алмазы за просмотр списываться не будут!",
            duration_hours=hours
        ))

@router.callback_query(F.data == "ev_setup_giveaway")
async def ev_setup_giveaway(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🎁 <b>Ивент: Раздача Алмазов</b>\n\nВведите количество алмазов, которое получит <b>КАЖДЫЙ</b> пользователь системы:")
    await state.set_state(AdminStates.event_giveaway)

@router.message(AdminStates.event_giveaway)
async def process_event_giveaway(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("❌ Введите корректное целое число алмазов:")
        
    amount = int(text)
    await state.clear()
    
    msg = await message.answer("⏳ Начисляю алмазы всей базе данных...")
    await db.execute("UPDATE users SET diamonds = diamonds + ?", (amount,))
    await db.commit()
    
    await msg.edit_text(f"✅ Раздача завершена! Всем добавлено по +{amount} 💎.")
    
    asyncio.create_task(broadcast_event_start(
        title="🎁 МГНОВЕННАЯ СУПЕР-РАЗДАЧА",
        description=f"Администрация зачислила на баланс каждому пользователю бота без исключения по <b>+{amount} алмазов</b>!",
        duration_hours=None
    ))

@router.callback_query(F.data == "admin_mail")
async def admin_mail(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("📢 Введите текст рекламной рассылки (уйдет по всем токенам/зеркалам):")
    await state.set_state(AdminStates.mailing_text)

@router.message(AdminStates.mailing_text)
async def process_admin_mailing(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text
    await state.clear()
    
    await message.answer("⏳ Запущена массовая мульти-рассылка по всей базе пользователей...")
    await send_to_all_bots(text)
    await message.answer("✅ Мульти-рассылка завершена.")

# ========================= СИСТЕМНЫЕ ФУНКЦИИ И ОЧИСТКА =========================

async def delete_old_videos():
    while True:
        await asyncio.sleep(30)
        try:
            async with db.execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (datetime.now().isoformat(),)) as cur: rows = await cur.fetchall()
            if rows and GLOBAL_BOTS_POOL:
                main_bot = GLOBAL_BOTS_POOL[0] # Удаляем через первого основного бота
                for mid, cid in rows:
                    try: await main_bot.delete_message(cid, mid)
                    except Exception: pass
                    await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (mid, cid))
                await db.commit()
        except Exception: pass

# ========================= МУЛЬТИ-ПОЛЛИНГ ЯДРО =========================

async def main():
    global GLOBAL_BOTS_POOL
    await init_db()
    
    dp = Dispatcher()
    dp.include_router(router)
    
    @dp.pre_checkout_query()
    async def global_pre_checkout(pre_checkout_query: PreCheckoutQuery):
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def global_successful_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_diamonds:"):
            diamonds = int(payload.split(":")[1])
            
            # Если активен ивент Х3 на пополнение
            if await is_event_active("global_x3_stars_until"):
                diamonds *= 3
                
            await add_diamonds(message.from_user.id, diamonds)
            
            x3_msg = " [⚡️ Сработал Ивент Х3!]" if await is_event_active("global_x3_stars_until") else ""
            await message.answer(f"🎉 <b>Оплата через Telegram Stars зачислена!</b> +<b>{diamonds}</b> 💎.{x3_msg}")

    print(f"⏳ Проверка основного списка токенов ({len(MAIN_TOKENS)} шт)...")
    for token in MAIN_TOKENS:
        try:
            bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            bot_user = await bot_instance.get_me()
            await bot_instance.delete_webhook(drop_pending_updates=True)
            GLOBAL_BOTS_POOL.append(bot_instance)
            print(f"✅ Основной бот @{bot_user.username} добавлен в пул.")
        except Exception as e:
            print(f"❌ Не удалось запустить основной токен {token[:15]}... Ошибка: {e}")

    if not GLOBAL_BOTS_POOL:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Ни один токен из списка MAIN_TOKENS не валиден.")
        return

    async with db.execute("SELECT token FROM mirrors") as cur: mirrors = await cur.fetchall()
    for (token,) in mirrors:
        if token in MAIN_TOKENS: continue
        try:
            mirror_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await mirror_bot.delete_webhook(drop_pending_updates=True)
            GLOBAL_BOTS_POOL.append(mirror_bot)
            print(f"✅ Зеркало юзера {token[:12]}... подключено в общий пул.")
        except Exception as e:
            print(f"⚠️ Зеркало юзера {token[:12]}... пропущено из-за ошибки: {e}")

    asyncio.create_task(delete_old_videos())
    
    print(f"🚀 Запуск одновременного пуллинга для {len(GLOBAL_BOTS_POOL)} ботов!")
    await dp.start_polling(*GLOBAL_BOTS_POOL)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): print("Выключение ядра.")
