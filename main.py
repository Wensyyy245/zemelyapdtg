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
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError

# ========================= НАСТРОЙКИ =========================

MAIN_TOKEN = "8971264936:AAEX4G42x3OQRMdjvOJGAJFJdydIVDGp_PE"
ADMIN_ID = 8603534638

# НАСТРОЙКА КАНАЛОВ (для закрытых укажи ID типа -100... и ссылку-приглашение)
CHANNELS = [
    ("@zemelya_new", "Публичный Канал 1", "https://t.me/zemelya_new"),
    (-1004466816546, "Закрытый Канал 2", "https://t.me/+ryYTkHSQG6VmNjUy"), 
]

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"
db = None

# ========================= СОСТОЯНИЯ (FSM) =========================

class AdminStates(StatesGroup):
    mailing_text = State()
    user_manage_id = State()
    change_balance = State()

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
    
    try: await db.execute("ALTER TABLE users ADD COLUMN premium INTEGER DEFAULT 0")
    except aiosqlite.OperationalError: pass
    try: await db.execute("ALTER TABLE users ADD COLUMN x2_until TEXT DEFAULT NULL")
    except aiosqlite.OperationalError: pass
    try: await db.execute("ALTER TABLE users ADD COLUMN keep_videos INTEGER DEFAULT 0")
    except aiosqlite.OperationalError: pass

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

# ========================= МИДЛВАРЬ БАНА И ХЕЛПЕРЫ =========================

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
    kb.button(text="🏆 Таблица лидеров", callback_data="leaderboard")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
    if user_id == ADMIN_ID:
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

def shop_abilities_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 х2 от Рефералов (24ч) — 50 💎", callback_data="buy_boost_x2")
    kb.button(text="♾ Видео навсегда — 500 💎", callback_data="buy_keep_videos")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def shop_premium_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🌟 Премиум (Все бесплатно) — 1500 💎", callback_data="buy_prem_normal")
    kb.button(text="🔥 Премиум+ (Архивы + Навсегда) — 2000 💎", callback_data="buy_prem_plus")
    kb.button(text="◀️ Назад в магазин", callback_data="shop_main")
    kb.adjust(1)
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="👥 Список участников", callback_data="admin_users_list")
    kb.button(text="📢 Рассылка", callback_data="admin_mail")
    kb.button(text="👤 Управление юзером", callback_data="admin_user")
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
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
                    reward = 4
                    if ref_data["x2_until"] and datetime.fromisoformat(ref_data["x2_until"]) > datetime.now():
                        reward = 8
                    await add_diamonds(referrer_id, reward)
                    try: await bot.send_message(referrer_id, f"🎉 Новый реферал! +{reward} 💎")
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

# --- Магазин КАТЕГОРИИ (Telegram Stars Оплата) ---
@router.callback_query(F.data == "shop_main")
async def shop_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    prem_status = "❌ Нет" if udata["premium"] == 0 else ("🌟 Premium" if udata["premium"] == 1 else "🔥 Premium+")
    keep_status = "✅ Да" if udata["keep_videos"] == 1 or udata["premium"] == 2 else "❌ Нет"
    boost_status = "❌ Нет"
    if udata["x2_until"] and datetime.fromisoformat(udata["x2_until"]) > datetime.now():
        boost_status = f"✅ Активен до {datetime.fromisoformat(udata['x2_until']).strftime('%H:%M %d.%m')}"
        
    text = f"🛒 <b>Магазин категорий</b>\n\n💰 Баланс: <b>{udata['diamonds']}</b> 💎\n👑 Премиум: <b>{prem_status}</b>\n🚀 Буст х2: <b>{boost_status}</b>\n♾ Навсегда: <b>{keep_status}</b>"
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
                currency="XTR", # Системные Звезды Telegram
                prices=[LabeledPrice(label="Telegram Stars", amount=stars_price)]
            )
            await callback.answer()
        except Exception:
            await callback.answer("❌ Ошибка создания инвойса Stars.", show_alert=True)

# --- Другие категории магазина ---
@router.callback_query(F.data == "cat_abilities")
async def cat_abilities(callback: CallbackQuery):
    try: await callback.message.edit_text("⚡ <b>Магазин способностей</b>", reply_markup=shop_abilities_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 50: return await callback.answer("❌ Нужно 50 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - 50, x2_until = ? WHERE user_id = ?", ((datetime.now() + timedelta(hours=24)).isoformat(), user_id))
    await db.commit()
    await callback.answer("🚀 Буст х2 активирован!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["keep_videos"] == 1 or udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    if udata["diamonds"] < 500: return await callback.answer("❌ Нужно 500 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - 500, keep_videos = 1 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("♾ Видео теперь сохраняются навсегда!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "cat_premium")
async def cat_premium(callback: CallbackQuery):
    try: await callback.message.edit_text("👑 <b>Премиум подписки</b>", reply_markup=shop_premium_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_prem_normal")
async def buy_prem_normal(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] >= 1: return await callback.answer("Уже активно!", show_alert=True)
    if udata["diamonds"] < 1500: return await callback.answer("❌ Нужно 1500 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - 1500, premium = 1 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("👑 PREMIUM статус активирован!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_prem_plus")
async def buy_prem_plus(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] == 2: return await callback.answer("Уже активно!", show_alert=True)
    if udata["diamonds"] < 2000: return await callback.answer("❌ Нужно 2000 💎", show_alert=True)
    await db.execute("UPDATE users SET diamonds = diamonds - 2000, premium = 2 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("🔥 PREMIUM+ статус активирован!", show_alert=True)
    await shop_main(callback)

# --- Контент ---
@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] == 0:
        if udata["diamonds"] < 6: return await callback.answer("❌ Нужно 6 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ?", (user_id,))
        await db.commit()
    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV"))
    if not videos: return await callback.answer("Папка media пуста.", show_alert=True)
    is_forever = (udata["keep_videos"] == 1 or udata["premium"] == 2)
    cap = "📹 Ваше видео!" if is_forever else "📹 Видео удалится через 30 минут."
    msg = await bot.send_video(chat_id=user_id, video=FSInputFile(random.choice(videos)), caption=cap)
    if not is_forever:
        await db.execute("INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)", ("", msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()))
        await db.commit()
    await callback.answer()

@router.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] == 0:
        if udata["diamonds"] < 3: return await callback.answer("❌ Нужно 3 💎", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ?", (user_id,))
        await db.commit()
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("Папка photo пуста.", show_alert=True)
    await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)))
    await callback.answer()

# --- Зеркала, Промокоды, Лидерборд ---
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
    
    msg = await message.answer("⏳ Перезапускаем ядро для активации зеркала...")
    try:
        test_bot = Bot(token=token)
        await test_bot.get_me()
        await test_bot.session.close()
        
        await db.execute("INSERT INTO mirrors (user_id, token, created_at) VALUES (?, ?, ?)", (message.from_user.id, token, datetime.now().isoformat()))
        await add_diamonds(message.from_user.id, 20)
        await db.commit()
        
        await msg.edit_text("🎉 Зеркало сохранено! Перезагружаю скрипт...")
        # Мягкий автоматический рестарт процесса для подтягивания нового бота в пуллинг
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

@router.callback_query(F.data == "admin_enter")
async def admin_enter(callback: CallbackQuery):
    if callback.from_user.id == ADMIN_ID: await callback.message.edit_text("🛠 Админка:", reply_markup=admin_menu())

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

# ========================= СИСТЕМНЫЕ ФУНКЦИИ И ОЧИСТКА =========================

async def delete_old_videos():
    while True:
        await asyncio.sleep(30)
        try:
            async with db.execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (datetime.now().isoformat(),)) as cur: rows = await cur.fetchall()
            if rows:
                main_bot = Bot(token=MAIN_TOKEN)
                for mid, cid in rows:
                    try: await main_bot.delete_message(cid, mid)
                    except Exception: pass
                    await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (mid, cid))
                await db.commit()
                await main_bot.session.close()
        except Exception: pass

# ========================= ЕДИНЫЙ ТОЧКА ВХОДА СИСТЕМЫ ПОЛЛИНГА =========================

async def main():
    await init_db()
    
    # Инициализируем главный глобальный диспетчер
    dp = Dispatcher()
    dp.include_router(router)
    
    # Регистрируем единые хендлеры платежей на Диспетчер
    @dp.pre_checkout_query()
    async def global_pre_checkout(pre_checkout_query: PreCheckoutQuery):
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def global_successful_payment(message: Message):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("buy_diamonds:"):
            diamonds = int(payload.split(":")[1])
            await add_diamonds(message.from_user.id, diamonds)
            await message.answer(f"🎉 <b>Оплата через Telegram Stars зачислена!</b> +<b>{diamonds}</b> 💎.")

    # Собираем пулы активных и валидных ботов
    bots_pool = []
    
    # 1. Добавляем главного бота
    try:
        main_bot = Bot(token=MAIN_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await main_bot.delete_webhook(drop_pending_updates=True)
        bots_pool.append(main_bot)
        print("✅ Главный бот успешно подготовлен.")
    except Exception as e:
        print(f"❌ Критическая ошибка инициализации главного токена: {e}")
        return

    # 2. Добавляем зеркала из базы данных
    async with db.execute("SELECT token FROM mirrors") as cur: mirrors = await cur.fetchall()
    for (token,) in mirrors:
        if token == MAIN_TOKEN: continue
        try:
            mirror_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await mirror_bot.delete_webhook(drop_pending_updates=True)
            bots_pool.append(mirror_bot)
            print(f"✅ Зеркало {token[:12]}... подключено в общий пул.")
        except Exception as e:
            print(f"⚠️ Зеркало с токеном {token[:12]}... пропущено из-за ошибки: {e}")

    # 3. Запуск фоновой очистки медиафайлов
    asyncio.create_task(delete_old_videos())
    
    # Включаем параллельный мульти-пуллинг на одном диспетчере
    print(f"🚀 Запуск одновременного пуллинга для {len(bots_pool)} ботов...")
    await dp.start_polling(*bots_pool)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): print("Выключение ядра.")
