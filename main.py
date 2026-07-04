import asyncio
import random
import os
import sys
import uuid
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
from aiogram.exceptions import TelegramBadRequest

# ========================= НАСТРОЙКИ МУЛЬТИБОТА =========================

MAIN_TOKENS = [
    "8971264936:AAGnz7N90o_T1_EUEa694KTZThdFWGFhqgI",
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

GLOBAL_BOTS_POOL = []

# ========================= СОСТОЯНИЯ (FSM) =========================

class AdminStates(StatesGroup):
    mailing_text = State()
    user_manage_id = State()    
    user_change_diamonds = State() 
    event_percent = State()    
    event_hours = State()      
    event_giveaway = State()   

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
    # Таблица для отслеживания активаций промокодов (1 юзер = 1 активация конкретного кода)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS promo_activations (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    # Таблица для чеков на алмазы
    await db.execute("""
        CREATE TABLE IF NOT EXISTS diamond_checks (
            check_id TEXT PRIMARY KEY,
            creator_id INTEGER,
            diamonds_per_use INTEGER,
            uses_left INTEGER
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
    async with db.execute("SELECT user_id FROM users") as cur: users = await cur.fetchall()
    for (uid,) in users:
        bot_worker = random.choice(GLOBAL_BOTS_POOL)
        try:
            await bot_worker.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.03) 
        except Exception:
            try:
                await GLOBAL_BOTS_POOL[0].send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.03)
            except Exception: pass

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
            if member.status not in ["member", "administrator", "creator"]: return False
        except Exception: return False
    return True

async def get_user_data(user_id: int, first_name: str = "Пользователь"):
    async with db.execute("SELECT diamonds, premium, x2_until, keep_videos FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, first_name, diamonds) VALUES (?, ?, 8)", (user_id, first_name))
            await db.commit()
            return {"diamonds": 8, "premium": 0, "x2_until": None, "keep_videos": 0}
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
    t_str = f" ({timer})" if timer else ""
    
    text1 = f"🎁 100 💎 — <s>{prices[0]}</s> -> {final_prices[0]} ⭐️" if discount_pct > 0 else f"🎁 100 алмазов — {prices[0]} ⭐️"
    text2 = f"🎁 250 💎 — <s>{prices[1]}</s> -> {final_prices[1]} ⭐️" if discount_pct > 0 else f"🎁 250 алмазов — {prices[1]} ⭐️"
    text3 = f"🎁 500 💎 — <s>{prices[2]}</s> -> {final_prices[2]} ⭐️" if discount_pct > 0 else f"🎁 500 алмазов — {prices[2]} ⭐️"
    
    kb.button(text=text1 + t_str, callback_data="stars_100")
    kb.button(text=text2 + t_str, callback_data="stars_250")
    kb.button(text=text3 + t_str, callback_data="stars_500")
    kb.button(text="✍️ Ввести свое количество алмазов", callback_data="stars_custom")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_abilities_kb(discount_pct: int = 0, timer: str = ""):
    p1, p2 = 50, 500
    f1 = int(p1 * (1 - discount_pct / 100))
    f2 = int(p2 * (1 - discount_pct / 100))
    t_str = f" ({timer})" if timer else ""
    
    kb = InlineKeyboardBuilder()
    text1 = f"🚀 х2 Рефералы (24ч) — <s>{p1}</s> -> {f1} 💎" if discount_pct > 0 else f"🚀 х2 от Рефералов (24ч) — {p1} 💎"
    text2 = f"♾ Видео навсегда — <s>{p2}</s> -> {f2} 💎" if discount_pct > 0 else f"♾ Видео навсегда — {p2} 💎"
    
    kb.button(text=text1 + t_str, callback_data="buy_boost_x2")
    kb.button(text=text2 + t_str, callback_data="buy_keep_videos")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_premium_kb(discount_pct: int = 0, timer: str = ""):
    p1, p2 = 1500, 2000
    f1 = int(p1 * (1 - discount_pct / 100))
    f2 = int(p2 * (1 - discount_pct / 100))
    t_str = f" ({timer})" if timer else ""
    
    kb = InlineKeyboardBuilder()
    text1 = f"🌟 Премиум — <s>{p1}</s> -> {f1} 💎" if discount_pct > 0 else f"🌟 Премиум (Все бесплатно) — {p1} 💎"
    text2 = f"🔥 Премиум+ — <s>{p2}</s> -> {f2} 💎" if discount_pct > 0 else f"🔥 Премиум+ (Архивы + Навсегда) — {p2} 💎"
    
    kb.button(text=text1 + t_str, callback_data="buy_prem_normal")
    kb.button(text=text2 + t_str, callback_data="buy_prem_plus")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="👤 Управление пользователями", callback_data="admin_manage_users")
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

# ========================= ХЕНДЛЕРЫ БОТА =========================

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    name = message.from_user.first_name
    args = message.text.split()
    
    # Реферальная система или активация чеков
    if len(args) > 1:
        param = args[1]
        
        # АКТИВАЦИЯ ЧЕКА ИЗ КРИПТОБОТА
        if param.startswith("check_"):
            check_id = param.replace("check_", "")
            
            # Сначала проверяем подписку
            if not await check_subscription(user_id, bot):
                return await message.answer("⚠️ Чтобы забрать чек, сначала подпишитесь на наши каналы, а затем снова перейдите по ссылке!")
                
            async with db.execute("SELECT creator_id, diamonds_per_use, uses_left FROM diamond_checks WHERE check_id = ?", (check_id,)) as cur:
                check_row = await cur.fetchone()
                
            if not check_row:
                return await message.answer("❌ Данный чек не найден или уже полностью активирован.")
                
            creator_id, diamonds, uses_left = check_row
            
            if creator_id == user_id:
                return await message.answer("❌ Вы не можете активировать свой собственный чек!")
                
            # Проверяем, не активировал ли этот юзер чек ранее
            async with db.execute("SELECT 1 FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, f"check_{check_id}")) as cur:
                if await cur.fetchone():
                    return await message.answer("❌ Вы уже активировали этот чек ранее!")
            
            # Проводим начисление
            await add_diamonds(user_id, diamonds)
            # Записываем активацию чека в базу
            await db.execute("INSERT INTO promo_activations VALUES (?, ?)", (user_id, f"check_{check_id}"))
            
            if uses_left - 1 <= 0:
                await db.execute("DELETE FROM diamond_checks WHERE check_id = ?", (check_id,))
            else:
                await db.execute("UPDATE diamond_checks SET uses_left = uses_left - 1 WHERE check_id = ?", (check_id,))
                
            await db.commit()
            
            # Уведомляем создателя
            try:
                await bot.send_message(creator_id, f"💸 Ваш чек был активирован! Пользователь {name} забрал {diamonds} 💎")
            except Exception:
                pass
                
            return await message.answer(f"🎉 <b>Чек успешно активирован!</b>\n\nВы получили: +<b>{diamonds}</b> 💎", reply_markup=main_menu(user_id))

        # СТАНДАРТНЫЙ РЕФЕРАЛ (если это просто ID)
        elif param.isdigit():
            referrer_id = int(param)
            if referrer_id != user_id:
                async with db.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,)) as cur:
                    if not await cur.fetchone():
                        await db.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                        ref_data = await get_user_data(referrer_id)
                        
                        base_reward = 4
                        if await is_event_active("global_x2_until"): base_reward = 8 
                        if ref_data["x2_until"] and datetime.fromisoformat(ref_data["x2_until"]) > datetime.now(): base_reward *= 2 
                            
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

# ========================= МАГАЗИН И ПЛАТЕЖИ =========================

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
    
    is_disc = await is_event_active("global_discount_until")
    if is_disc:
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
        is_disc = await is_event_active("global_discount_until")
        if is_disc:
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
    try: await callback.message.edit_text("⚡ <b>Магазин способностей</b>", reply_markup=shop_abilities_kb(discount_pct=pct, timer=timer))
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
    timer = await get_event_remaining_time("global_discount_until")
    try: await callback.message.edit_text("👑 <b>Премиум подписки</b>", reply_markup=shop_premium_kb(discount_pct=pct, timer=timer))
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

# ========================= ПРОСМОТР МЕДИА =========================

@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    
    is_free = await is_event_active("global_free_view_until")
    is_lucky = await is_event_active("global_lucky_hour_until")
    
    if udata["premium"] == 0 and not is_free:
        if not is_lucky:
            if udata["diamonds"] < 6: return await callback.answer("❌ Нужно 6 💎", show_alert=True)
            await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ?", (user_id,))
            await db.commit()
        
    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV"))
    if not videos: return await callback.answer("Папка media пуста.", show_alert=True)
    is_forever = (udata["keep_videos"] == 1 or udata["premium"] == 2)
    
    cap = "📹 Ваше видео!" if is_forever else "📹 Видео удалится через 30 минут."
    if is_free: cap += " (🔥 По ивенту БЕСПЛАТНО)"
    if is_lucky:
        await add_diamonds(user_id, 2)
        cap += " (🍀 Счастливый час: +2 💎 за просмотр!)"
        
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
    is_lucky = await is_event_active("global_lucky_hour_until")
    
    if udata["premium"] == 0 and not is_free:
        if not is_lucky:
            if udata["diamonds"] < 3: return await callback.answer("❌ Нужно 3 💎", show_alert=True)
            await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ?", (user_id,))
            await db.commit()
        
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("Папка photo пуста.", show_alert=True)
    
    if is_lucky:
        await add_diamonds(user_id, 2)
        
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)), caption="🍀 Счастливый час: +2 💎!" if is_lucky else None)
    await callback.answer()

# ========================= МЕНЮ ПРОМОКОДОВ И ЧЕКОВ =========================

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Активировать промокод", callback_data="promo_activate")
    kb.button(text="➕ Создать промокод", callback_data="promo_create")
    kb.button(text="🧾 Создать чек (как в CryptoBot)", callback_data="check_create")
    kb.button(text="◀️ Назад в главное меню", callback_data="back_main")
    kb.adjust(1)
    await callback.message.edit_text("🎟 <b>Раздел Чеков и Промокодов</b>\n\nЗдесь вы можете активировать промокод или упаковать свои алмазы в чеки для друзей!", reply_markup=kb.as_markup())

# АКТИВАЦИЯ ПРОМОКОДА
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
        
    if not row: 
        return await message.answer("❌ Промокод не найден.")
        
    cid, reward, left = row
    if left <= 0: 
        return await message.answer("❌ Промокод закончился.")
        
    if cid == user_id: 
        return await message.answer("❌ Вы не можете активировать собственный промокод.")
    
    # ПРОВЕРКА НА ПОВТОРНУЮ АКТИВАЦИЮ (1 человек = 1 активация)
    async with db.execute("SELECT 1 FROM promo_activations WHERE user_id = ? AND code = ?", (user_id, code)) as cur:
        if await cur.fetchone():
            return await message.answer("❌ Вы уже активировали этот промокод ранее!")
            
    # Записываем факт активации, списываем попытку и даем награду
    await db.execute("INSERT INTO promo_activations VALUES (?, ?)", (user_id, code))
    
    if left - 1 == 0: 
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else: 
        await db.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
        
    await add_diamonds(user_id, reward)
    await db.commit()
    await message.answer(f"🎉 <b>Промокод успешно активирован!</b>\nНа ваш баланс зачислено: +<b>{reward}</b> 💎")

# СОЗДАНИЕ ПРОМОКОДА
@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✨ Введите текст промокода (слово/код):")
    await state.set_state(PromoStates.create_code)

@router.message(PromoStates.create_code)
async def process_promo_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip().upper())
    await message.answer("💎 Введите награду в алмазах за 1 активацию:")
    await state.set_state(PromoStates.create_reward)

@router.message(PromoStates.create_reward)
async def process_promo_reward(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Введите целое число:")
    await state.update_data(reward=int(message.text))
    await message.answer("👥 Кол-во людей, которые смогут его активировать:")
    await state.set_state(PromoStates.create_uses)

@router.message(PromoStates.create_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Введите целое число:")
        
    uses = int(message.text)
    data = await state.get_data()
    total = data['reward'] * uses
    bal = await get_user_data(message.from_user.id)
    
    if bal['diamonds'] < total: 
        await state.clear()
        return await message.answer("❌ Недостаточно 💎 для обеспечения промокода!")
        
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (total, message.from_user.id))
    await db.execute("INSERT INTO promo_codes VALUES (?, ?, ?, ?)", (data['code'], message.from_user.id, data['reward'], uses))
    await db.commit()
    await state.clear()
    
    # КРАСИВЫЙ СТИЛЬНЫЙ ТЕКСТ ПОСЛЕ СОЗДАНИЯ
    beautiful_text = (
        f"🎟 <b>ПРОМОКОД УСПЕШНО СОЗДАН!</b> 🎟\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🏷 <b>Код:</b> <code>{data['code']}</code>\n"
        f"💎 <b>Ценность:</b> <code>{data['reward']}</code> алмазов каждому\n"
        f"👥 <b>Лимит активаций:</b> <code>{uses}</code> человек(а)\n\n"
        f"ℹ️ <i>Каждый пользователь бота сможет активировать этот промокод строго <b>один раз</b>!</i>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👉 Нажмите на код выше, чтобы скопировать его."
        f"👉 Боты для активации: @zemelyacomeback_bot @ZemlayyaBot"
    )
    await message.answer(beautiful_text, reply_markup=main_menu(message.from_user.id))


# ========================= СИСТЕМА ЧЕКОВ (CRYPTOBOT СТИЛЬ) =========================

@router.callback_query(F.data == "check_create")
async def check_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🧾 <b>Создание алмазного чека</b>\n\nВведите количество алмазов, которое получит <b>один</b> человек:")
    await state.set_state(CheckStates.create_diamonds)

@router.message(CheckStates.create_diamonds)
async def process_check_diamonds(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        return await message.answer("❌ Введите корректное число алмазов:")
    await state.update_data(diamonds=int(message.text))
    await message.answer("👥 Сколько человек смогут забрать этот чек?")
    await state.set_state(CheckStates.create_uses)

@router.message(CheckStates.create_uses)
async def process_check_uses(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        return await message.answer("❌ Введите корректное число человек:")
        
    uses = int(message.text)
    data = await state.get_data()
    diamonds_per_use = data['diamonds']
    total_needed = diamonds_per_use * uses
    
    bal = await get_user_data(message.from_user.id)
    if bal['diamonds'] < total_needed:
        await state.clear()
        return await message.answer(f"❌ У вас недостаточно алмазов. Требуется: {total_needed} 💎, у вас: {bal['diamonds']} 💎")
        
    # Списываем баланс и создаем чек
    check_id = str(uuid.uuid4())[:8].upper() # Короткий уникальный ID чека
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (total_needed, message.from_user.id))
    await db.execute("INSERT INTO diamond_checks VALUES (?, ?, ?, ?)", (check_id, message.from_user.id, diamonds_per_use, uses))
    await db.commit()
    await state.clear()
    
    # Получаем юзернейм бота для генерации красивой прямой ссылки
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
        f"📢 <i>Отправьте эту ссылку другу или в чат. Тот, кто перейдет по ней первым, мгновенно заберет награду!</i>"
    )
    await message.answer(beautiful_check_text, reply_markup=main_menu(message.from_user.id))

# ========================= ОСТАЛЬНЫЕ СТАНДАРТНЫЕ ХЕНДЛЕРЫ =========================

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
        await callback.message.edit_text("🛠 ТП: @zemelya_admin", reply_markup=InlineKeyboardBuilder().button(text="◀️ Назад", callback_data="back_main").as_markup())

# ========================= АДМИН ПАНЕЛЬ И СИСТЕМА ИВЕНТОВ =========================

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id in ADMIN_IDS: 
        await callback.message.edit_text("🛠 <b>Административная Панель</b>:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("👤 <b>Управление пользователями</b>\n\nВведите Telegram ID пользователя, баланс которого хотите изменить:")
    await state.set_state(AdminStates.user_manage_id)

@router.message(AdminStates.user_manage_id)
async def process_user_search(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("❌ ID должен состоять только из цифр. Попробуйте еще раз:")
    
    uid = int(text)
    async with db.execute("SELECT first_name, diamonds FROM users WHERE user_id = ?", (uid,)) as cur:
        row = await cur.fetchone()
    
    if not row:
        return await message.answer("❌ Пользователь с таким ID не найден в базе данных.")
        
    await state.update_data(target_id=uid)
    await message.answer(
        f"👤 <b>Пользователь найден:</b>\n"
        f"ID: <code>{uid}</code>\n"
        f"Имя: {row[0]}\n"
        f"Текущие алмазы: <b>{row[1]}</b> 💎\n\n"
        f"✍️ Чтобы изменить баланс, введите число.\n"
        f"Пример: <code>100</code> (выдать 100), или <code>-50</code> (забрать 50):"
    )
    await state.set_state(AdminStates.user_change_diamonds)

@router.message(AdminStates.user_change_diamonds)
async def process_user_change_diamonds(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    try:
        amount = int(text)
    except ValueError:
        return await message.answer("❌ Введите корректное целое число (положительное или отрицательное):")
        
    data = await state.get_data()
    uid = data.get("target_id")
    await state.clear()
    
    await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, uid))
    await db.commit()
    
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (uid,)) as cur:
        new_bal = (await cur.fetchone())[0]
        
    await message.answer(f"✅ Успешно изменено на {amount}. Новый баланс пользователя: <b>{new_bal}</b> 💎.", reply_markup=admin_menu())

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
        f"📉 Кастомные Скидки в шопе: {disc_active}\n"
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
    await callback.message.edit_text("🍀 <b>Ивент: Счастливый Час (+2 💎 за просмотры)</b>\n\nВведите время действия ивента в <b>ЧАСАХ</b>:")
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
    if not text.isdigit() or not (1 <= int(text) <= 99):
        return await message.answer("❌ Ошибка! Введите корректный процент скидки (от 1 до 99):")
    
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
        await message.answer(f"✅ Глобальный ивент <b>х2 Рефералы</b> запущен!")
        asyncio.create_task(broadcast_event_start("🚀 ДВОЙНЫЕ НАГРАДЫ ЗА ДРУЗЕЙ (х2)", "С этого момента за каждого приглашенного реферала абсолютно все пользователи получают двойную выплату алмазов!", hours))
        
    elif etype == "discount":
        pct = data.get("discount_pct", 30)
        await set_setting("global_discount_percent", str(pct))
        await set_setting("global_discount_until", until_time)
        await message.answer(f"✅ Ивент <b>Скидки -{pct}%</b> успешно запущен!")
        asyncio.create_task(broadcast_event_start(f"📉 ШОК-СКИДКИ В МАГАЗИНЕ (-{pct}%)", f"Цены на способности, улучшения и покупку алмазов за Звезды снижены на {pct}%!", hours))
        
    elif etype == "x3_stars":
        await set_setting("global_x3_stars_until", until_time)
        await message.answer(f"✅ Ивент <b>Х3 Алмазы за Stars</b> запущен!")
        asyncio.create_task(broadcast_event_start("⚡️ АЛМАЗНЫЙ ЛИВЕНЬ (Х3 К ПОКУПКАМ)", "Внимание! Любая покупка алмазов через Telegram Stars увеличивается в 3 раза!", hours))
        
    elif etype == "free_view":
        await set_setting("global_free_view_until", until_time)
        await message.answer(f"✅ Ивент <b>Бесплатный Просмотр</b> запущен!")
        asyncio.create_task(broadcast_event_start("🆓 АТТРАКЦИОН НЕВИДАННОЙ ЩЕДРОСТИ (0 💎)", "Администрация открыла бесплатный просмотр всех видео и фото для всех пользователей!", hours))

    elif etype == "lucky_hour":
        await set_setting("global_lucky_hour_until", until_time)
        await message.answer(f"✅ Ивент <b>Счастливый Час</b> запущен на {hours} ч.!")
        asyncio.create_task(broadcast_event_start("🍀 СЧАСТЛИВЫЙ ЧАС (+2 💎 ЗА АКТИВНОСТЬ)", "Невероятный бонус! Просматривайте медиа прямо сейчас и вместо списания алмазов получайте +2 💎 прямо на баланс за каждое выполненное действие!", hours))

@router.callback_query(F.data == "ev_setup_giveaway")
async def ev_setup_giveaway(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.edit_text("🎁 <b>Ивент: Раздача Алмазов</b>\n\nВведите количество алмазов для <b>КАЖДОГО</b> пользователя:")
    await state.set_state(AdminStates.event_giveaway)

@router.message(AdminStates.event_giveaway)
async def process_event_giveaway(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.strip()
    if not text.isdigit(): return await message.answer("❌ Введите корректное целое число алмазов:")
        
    amount = int(text)
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
    await message.answer("⏳ Запущена массовая рассылка...")
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
            if await is_event_active("global_x3_stars_until"): diamonds *= 3
            await add_diamonds(message.from_user.id, diamonds)
            x3_msg = " [⚡️ Сработал Ивент Х3!]" if await is_event_active("global_x3_stars_until") else ""
            await message.answer(f"🎉 <b>Оплата зачислена!</b> +<b>{diamonds}</b> 💎.{x3_msg}")

    print(f"⏳ Проверка основного списка токенов...")
    for token in MAIN_TOKENS:
        try:
            bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            bot_user = await bot_instance.get_me()
            await bot_instance.delete_webhook(drop_pending_updates=True)
            GLOBAL_BOTS_POOL.append(bot_instance)
            print(f"✅ Бот @{bot_user.username} добавлен в пул.")
        except Exception as e:
            print(f"❌ Ошибка токена {token[:15]}: {e}")

    if not GLOBAL_BOTS_POOL:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Нет валидных токенов.")
        return

    asyncio.create_task(delete_old_videos())
    await dp.start_polling(*GLOBAL_BOTS_POOL)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): print("Выключение ядра.")
