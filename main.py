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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError

# ========================= НАСТРОЙКИ =========================

MAIN_TOKEN = "8971264936:AAEX4G42x3OQRMdjvOJGAJFJdydIVDGp_PE"
ADMIN_ID = 8502341995

CHANNELS = [
    (-1004466816546, "Наш канал", "https://t.me/+ryYTkHSQG6VmNjUy"), 
]

DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"

# Глобальные объекты
active_bots = {}
dp = Dispatcher()

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

db = None

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

# ========================= МИДЛВАРЬ ДЛЯ БАНА =========================

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
                    try: await event.answer("❌ Вы заблокированы в этом боте!", show_alert=True)
                    except Exception: pass
                return
    return await handler(event, data)

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

def promo_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Активировать промокод", callback_data="promo_activate")
    kb.button(text="➕ Создать промокод", callback_data="promo_create")
    kb.button(text="◀️ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

# ========================= ХЕЛПЕРЫ =========================

async def check_subscription(user_id: int, bot: Bot) -> bool:
    for channel, _ in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

async def get_user_data(user_id: int, first_name: str = "Пользователь"):
    async with db.execute("SELECT diamonds, premium, x2_until, keep_videos FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, first_name, diamonds) VALUES (?, ?, 8)", 
                (user_id, first_name)
            )
            await db.commit()
            return {"diamonds": 8, "premium": 0, "x2_until": None, "keep_videos": 0}
        await db.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        await db.commit()
        return {"diamonds": row[0], "premium": row[1], "x2_until": row[2], "keep_videos": row[3]}

async def get_user_diamonds(user_id: int, first_name: str = "Пользователь") -> int:
    data = await get_user_data(user_id, first_name)
    return data["diamonds"]

async def add_diamonds(user_id: int, amount: int):
    await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
    await db.commit()

# ========================= СИСТЕМА ЗЕРКАЛ =========================

@router.callback_query(F.data == "mirror_menu")
async def mirror_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    async with db.execute(
        "SELECT COUNT(*) FROM mirrors WHERE user_id = ? AND created_at >= ?", 
        (user_id, one_day_ago)
    ) as cur:
        created_today = (await cur.fetchone())[0]
        
    if created_today >= 2:
        return await callback.answer("❌ Лимит исчерпан! Можно создать не более 2 зеркал в сутки.", show_alert=True)
        
    text = (
        "🪞 <b>Создание зеркала бота</b>\n\n"
        "Вы можете подключить своего собственного бота! Он будет точной копией этого бота, с той же базой данных и балансами участников.\n\n"
        "🎁 За каждое созданное зеркало вы получите <b>+20 алмазов</b>!\n"
        "⚠️ <i>Ограничение: до 2 ботов в сутки.</i>\n\n"
        "<b>Как создать:</b>\n"
        "1. Перейдите в @BotFather и создайте нового бота через <code>/newbot</code>.\n"
        "2. Скопируйте полученный токен (API Token).\n"
        "3. Нажмите кнопку ниже и отправьте токен сюда."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Подключить токен", callback_data="mirror_start_enter")
    kb.button(text="◀️ Назад", callback_data="back_main")
    kb.adjust(1)
    
    try: await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "mirror_start_enter")
async def mirror_start_enter(callback: CallbackQuery, state: FSMContext):
    try: await callback.message.edit_text("📥 Отправьте API Токен вашего бота из @BotFather:")
    except TelegramBadRequest: pass
    await callback.answer()
    await state.set_state(MirrorStates.enter_token)

@router.message(MirrorStates.enter_token)
async def process_mirror_token(message: Message, state: FSMContext, bot: Bot):
    token = message.text.strip()
    user_id = message.from_user.id
    if ":" not in token or len(token) < 30:
        return await message.answer("❌ Неверный формат токена. Попробуйте еще раз.")
    if token in active_bots:
        await state.clear()
        return await message.answer("❌ Это зеркало уже запущено и работает!")
        
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    async with db.execute("SELECT COUNT(*) FROM mirrors WHERE user_id = ? AND created_at >= ?", (user_id, one_day_ago)) as cur:
        if (await cur.fetchone())[0] >= 2:
            await state.clear()
            return message.answer("❌ Превышен суточный лимит создания ботов (макс. 2).")

    checking_msg = await message.answer("⏳ Проверяем токен и запускаем зеркало...")
    try:
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        bot_user = await new_bot.get_me()
        now = datetime.now().isoformat()
        await db.execute("INSERT INTO mirrors (user_id, token, created_at) VALUES (?, ?, ?)", (user_id, token, now))
        await add_diamonds(user_id, 20)
        await db.commit()
        
        active_bots[token] = new_bot
        asyncio.create_task(start_bot_polling(new_bot))
        await checking_msg.delete()
        await message.answer(
            f"🎉 <b>Зеркало успешно запущено!</b>\n\n🤖 @{bot_user.username}\n🎁 +<b>20</b> 💎!",
            reply_markup=main_menu(user_id)
        )
        await state.clear()
    except (TelegramUnauthorizedError, TelegramBadRequest):
        await checking_msg.edit_text("❌ Не удалось авторизовать бота. Неверный токен.")
    except Exception:
        await checking_msg.edit_text("❌ Ошибка на стороне Telegram.")
        await state.clear()



# ========================= АДМИН ПАНЕЛЬ =========================

@router.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Добро пожаловать в панель администратора:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_enter")
async def admin_enter_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    try: await callback.message.edit_text("🛠 Панель администратора:", reply_markup=admin_menu())
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    async with db.execute("SELECT COUNT(*), SUM(diamonds) FROM users") as cur:
        total_users, total_diamonds = await cur.fetchone()
    async with db.execute("SELECT COUNT(*) FROM promo_codes") as cur:
        total_promos = (await cur.fetchone())[0]
    async with db.execute("SELECT COUNT(*) FROM mirrors") as cur:
        total_mirrors = (await cur.fetchone())[0]
        
    text = (
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего пользователей: <code>{total_users}</code>\n"
        f"💎 Алмазов в системе: <code>{total_diamonds or 0}</code>\n"
        f"🎟 Активных промокодов: <code>{total_promos}</code>\n"
        f"🪞 Активных зеркал: <code>{total_mirrors}</code>"
    )
    try: await callback.message.edit_text(text, reply_markup=admin_menu())
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    async with db.execute("SELECT user_id, first_name, diamonds, is_banned FROM users LIMIT 100") as cur:
        rows = await cur.fetchall()
    if not rows: return await callback.answer("База данных пуста.", show_alert=True)
    text = "👥 <b>Список участников (Топ-100):</b>\n\n"
    for row in rows:
        uid, name, diamonds, banned = row
        text += f"▪️ <code>{uid}</code> — <b>{name}</b> ({diamonds} 💎){' [🔒]' if banned else ''}\n"
    kb = InlineKeyboardBuilder().button(text="◀️ Назад в админку", callback_data="admin_enter")
    try: await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "admin_mail")
async def admin_mail(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try: await callback.message.edit_text("📢 Введите текст для рассылки (HTML):")
    except TelegramBadRequest: pass
    await callback.answer()
    await state.set_state(AdminStates.mailing_text)

@router.message(AdminStates.mailing_text)
async def process_mailing(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    await message.answer("🚀 Рассылка запущена...")
    async with db.execute("SELECT user_id FROM users") as cur: rows = await cur.fetchall()
    count = 0
    for row in rows:
        try:
            await bot.send_message(chat_id=row[0], text=message.text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await message.answer(f"✅ Рассылка завершена. Отправлено: {count}.")

@router.callback_query(F.data == "admin_user")
async def admin_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try: await callback.message.edit_text("👤 Введите Telegram ID пользователя:")
    except TelegramBadRequest: pass
    await callback.answer()
    await state.set_state(AdminStates.user_manage_id)

@router.message(AdminStates.user_manage_id)
async def process_user_manage(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit(): return await message.answer("❌ ID должен состоять из цифр.")
    target_id = int(message.text)
    async with db.execute("SELECT diamonds, is_banned, first_name FROM users WHERE user_id = ?", (target_id,)) as cur: row = await cur.fetchone()
    if not row:
        await state.clear()
        return await message.answer("❌ Юзер не найден.")
    await state.update_data(target_id=target_id)
    diamonds, is_banned, name = row
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Изменить баланс", callback_data="adm_change_bal")
    kb.button(text="🔓 Разбанить" if is_banned else "🔒 Забанить", callback_data="adm_toggle_ban")
    kb.button(text="❌ Отмена", callback_data="back_admin")
    kb.adjust(1)
    await message.answer(f"👤 Юзер: <b>{name}</b> (<code>{target_id}</code>)\n💎: <b>{diamonds}</b>\n🚦: <b>{'ЗАБАНЕН' if is_banned else 'Активен'}</b>", reply_markup=kb.as_markup())

@router.callback_query(F.data == "adm_toggle_ban")
async def adm_toggle_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    target_id = data.get("target_id")
    async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (target_id,)) as cur: is_banned = (await cur.fetchone())[0]
    await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (0 if is_banned else 1, target_id))
    await db.commit()
    await state.clear()
    try: await callback.message.edit_text("🛠 Статус изменен.", reply_markup=admin_menu())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "adm_change_bal")
async def adm_change_bal(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try: await callback.message.edit_text("💰 Число алмазов (плюс или минус):")
    except TelegramBadRequest: pass
    await state.set_state(AdminStates.change_balance)

@router.message(AdminStates.change_balance)
async def process_change_balance(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try: amount = int(message.text)
    except ValueError: return await message.answer("❌ Введите число.")
    data = await state.get_data()
    target_id = data.get("target_id")
    await add_diamonds(target_id, amount)
    await message.answer("✅ Баланс изменен.")
    await state.clear()

@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await callback.message.edit_text("🛠 Панель администратора:", reply_markup=admin_menu())
    except TelegramBadRequest: pass

# ========================= СИСТЕМА ЛИДЕРБОРДОВ =========================

@router.callback_query(F.data == "leaderboard")
async def leaderboard_menu(callback: CallbackQuery):
    async with db.execute("SELECT first_name, diamonds FROM users ORDER BY diamonds DESC LIMIT 5") as cur: top_diamonds = await cur.fetchall()
    async with db.execute("""
        SELECT u.first_name, COUNT(r.user_id) as ref_count FROM users u
        INNER JOIN users r ON r.referred_by = u.user_id
        GROUP BY u.user_id ORDER BY ref_count DESC LIMIT 5
    """) as cur: top_referrals = await cur.fetchall()
    text = "🏆 <b>ТАБЛИЦА ЛИДЕРОВ</b> 🏆\n\n💎 <b>Топ по алмазам:</b>\n"
    for i, (name, count) in enumerate(top_diamonds, 1): text += f"{i}. {name} — <code>{count}</code> 💎\n"
    text += "\n👥 <b>Топ по приглашениям:</b>\n"
    if top_referrals:
        for i, (name, count) in enumerate(top_referrals, 1): text += f"{i}. {name} — <code>{count}</code> реф.\n"
    else: text += "<i>Пока рефералов нет</i>\n"
    kb = InlineKeyboardBuilder().button(text="◀️ Назад в меню", callback_data="back_main")
    try: await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest: pass
    await callback.answer()

# ========================= СИСТЕМА ПРОМОКОДОВ =========================

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    try: await callback.message.edit_text("🎟 <b>Система промокодов:</b>", reply_markup=promo_menu_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    try: await callback.message.edit_text("✨ Текст промокода (буквы/цифры):")
    except TelegramBadRequest: pass
    await state.set_state(PromoStates.create_code)

@router.message(PromoStates.create_code)
async def process_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if not code.isalnum(): return await message.answer("❌ Только буквы и цифры.")
    async with db.execute("SELECT 1 FROM promo_codes WHERE code = ?", (code,)) as cur:
        if await cur.fetchone(): return await message.answer("❌ Промокод уже существует.")
    await state.update_data(code=code)
    await message.answer("💎 Награда за 1 активацию:")
    await state.set_state(PromoStates.create_reward)

@router.message(PromoStates.create_reward)
async def process_promo_reward(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1: return await message.answer("❌ Введите число.")
    await state.update_data(reward=int(message.text))
    await message.answer("👥 Количество активаций:")
    await state.set_state(PromoStates.create_uses)

@router.message(PromoStates.create_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1: return await message.answer("❌ Введите число.")
    uses = int(message.text)
    data = await state.get_data()
    code, reward = data['code'], data['reward']
    total_cost = reward * uses
    user_id = message.from_user.id
    user_diamonds = await get_user_diamonds(user_id, message.from_user.first_name)
    if user_diamonds < total_cost:
        await state.clear()
        return await message.answer(f"❌ Недостаточно алмазов (нужно {total_cost})")
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (total_cost, user_id))
    await db.execute("INSERT INTO promo_codes (code, creator_id, reward, uses_left) VALUES (?, ?, ?, ?)", (code, user_id, reward, uses))
    await db.commit()
    await message.answer(f"✅ Промокод <code>{code}</code> создан!", reply_markup=main_menu(user_id))
    await state.clear()

@router.callback_query(F.data == "promo_activate")
async def promo_activate(callback: CallbackQuery, state: FSMContext):
    try: await callback.message.edit_text("📥 Введите промокод:")
    except TelegramBadRequest: pass
    await state.set_state(PromoStates.activate_code)

@router.message(PromoStates.activate_code)
async def process_promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    async with db.execute("SELECT creator_id, reward, uses_left FROM promo_codes WHERE code = ?", (code,)) as cur: row = await cur.fetchone()
    if not row:
        await state.clear()
        return await message.answer("❌ Код не найден.", reply_markup=main_menu(user_id))
    creator_id, reward, uses_left = row
    if creator_id == user_id:
        await state.clear()
        return await message.answer("❌ Свой промокод нельзя активировать.", reply_markup=main_menu(user_id))
    if uses_left <= 0:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        await db.commit()
        await state.clear()
        return await message.answer("❌ Код закончился.", reply_markup=main_menu(user_id))
    new_uses = uses_left - 1
    if new_uses == 0: await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else: await db.execute("UPDATE promo_codes SET uses_left = ? WHERE code = ?", (new_uses, code))
    await add_diamonds(user_id, reward)
    await db.commit()
    await message.answer(f"🎉 Активирован! +<b>{reward}</b> 💎.", reply_markup=main_menu(user_id))
    await state.clear()

# ========================= ОБНОВЛЕННЫЙ МАГАЗИН КАТЕГОРИЙ =========================

@router.callback_query(F.data == "shop_main")
async def shop_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    
    # Текстовое описание статуса юзера
    prem_status = "❌ Нет" if udata["premium"] == 0 else ("🌟 Premium" if udata["premium"] == 1 else "🔥 Premium+")
    keep_status = "✅ Да" if udata["keep_videos"] == 1 or udata["premium"] == 2 else "❌ Нет"
    
    boost_status = "❌ Нет"
    if udata["x2_until"]:
        until_dt = datetime.fromisoformat(udata["x2_until"])
        if until_dt > datetime.now():
            boost_status = f"✅ Активен до {until_dt.strftime('%H:%M %d.%m')}"
            
    text = (
        f"🛒 <b>Магазин категорий</b>\n\n"
        f"💰 Твой баланс: <b>{udata['diamonds']}</b> 💎\n"
        f"👑 Премиум: <b>{prem_status}</b>\n"
        f"🚀 Реферальный буст х2: <b>{boost_status}</b>\n"
        f"♾ Сохранение видео навсегда: <b>{keep_status}</b>\n\n"
        f"Выберите интересующую вас категорию:"
    )
    try: await callback.message.edit_text(text, reply_markup=shop_categories_kb())
    except TelegramBadRequest: pass

# --- Категория 1: Алмазы (За Звезды) ---
@router.callback_query(F.data == "cat_diamonds")
async def cat_diamonds(callback: CallbackQuery):
    try: await callback.message.edit_text("💎 <b>Пополнение алмазов (Telegram Stars)</b>\n\nВыберите нужное количество алмазов для покупки за официальные звезды Telegram:", reply_markup=shop_diamonds_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("stars_"))
async def buy_diamonds_stars(callback: CallbackQuery):
    data = callback.data
    rates = {
        "stars_100": (100, 50),
        "stars_250": (250, 120),
        "stars_500": (500, 200)
    }
    if data in rates:
        diamonds, stars_price = rates[data]
        try:
            await callback.message.answer_invoice(
                title=f"Покупка {diamonds} алмазов",
                description=f"Начисление {diamonds} алмазов на баланс в боте.",
                payload=f"buy_diamonds:{diamonds}",
                currency="XTR",
                prices=[LabeledPrice(label="Алмазы", amount=stars_price)]
            )
            await callback.answer()
        except Exception:
            await callback.answer("❌ Не удалось создать инвойс.", show_alert=True)

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("buy_diamonds:"):
        diamonds = int(payload.split(":")[1])
        await add_diamonds(message.from_user.id, diamonds)
        await message.answer(f"🎉 <b>Оплата прошла успешно!</b>\n На ваш баланс зачислено +<b>{diamonds}</b> 💎.")

# --- Категория 2: Способности (За Алмазы) ---
@router.callback_query(F.data == "cat_abilities")
async def cat_abilities(callback: CallbackQuery):
    try: await callback.message.edit_text("⚡ <b>Магазин способностей</b>\n\nПокупайте полезные улучшения за накопленные алмазы:", reply_markup=shop_abilities_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_boost_x2")
async def buy_boost_x2(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["diamonds"] < 50:
        return await callback.answer("❌ Недостаточно алмазов (нужно 50 💎)", show_alert=True)
        
    new_until = datetime.now() + timedelta(hours=24)
    await db.execute("UPDATE users SET diamonds = diamonds - 50, x2_until = ? WHERE user_id = ?", (new_until.isoformat(), user_id))
    await db.commit()
    await callback.answer("🚀 Способность х2 активирована на 24 часа!", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_keep_videos")
async def buy_keep_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["keep_videos"] == 1 or udata["premium"] == 2:
        return await callback.answer("✨ Эта способность у вас уже активна!", show_alert=True)
    if udata["diamonds"] < 500:
        return await callback.answer("❌ Недостаточно алмазов (нужно 500 💎)", show_alert=True)
        
    await db.execute("UPDATE users SET diamonds = diamonds - 500, keep_videos = 1 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("♾ Отлично! Теперь просмотренные видео не будут удаляться автоматически.", show_alert=True)
    await shop_main(callback)

# --- Категория 3: Премиум (За Алмазы) ---
@router.callback_query(F.data == "cat_premium")
async def cat_premium(callback: CallbackQuery):
    try: await callback.message.edit_text("👑 <b>Премиум подписки</b>\n\nАктивируйте бесконечный доступ к контенту без трат алмазов:", reply_markup=shop_premium_kb())
    except TelegramBadRequest: pass

@router.callback_query(F.data == "buy_prem_normal")
async def buy_prem_normal(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] >= 1:
        return await callback.answer("⭐ У вас уже активен премиум статус!", show_alert=True)
    if udata["diamonds"] < 1500:
        return await callback.answer("❌ Недостаточно алмазов (нужно 1500 💎)", show_alert=True)
        
    await db.execute("UPDATE users SET diamonds = diamonds - 1500, premium = 1 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("👑 Поздравляем! Статус PREMIUM успешно активирован.", show_alert=True)
    await shop_main(callback)

@router.callback_query(F.data == "buy_prem_plus")
async def buy_prem_plus(callback: CallbackQuery):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    if udata["premium"] == 2:
        return await callback.answer("🔥 У вас уже активен максимальный премиум статус!", show_alert=True)
    if udata["diamonds"] < 2000:
        return await callback.answer("❌ Недостаточно алмазов (нужно 2000 💎)", show_alert=True)
        
    await db.execute("UPDATE users SET diamonds = diamonds - 2000, premium = 2 WHERE user_id = ?", (user_id,))
    await db.commit()
    await callback.answer("🔥 Эпично! Статус PREMIUM+ (Архивы + Бесконечные видео) активирован.", show_alert=True)
    await shop_main(callback)

# ========================= ОСТАЛЬНЫЕ ОБРАБОТЧИКИ =========================

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
                    
                    # Проверяем буст рефералов х2 у пригласившего
                    ref_data = await get_user_data(referrer_id)
                    reward = 4
                    if ref_data["x2_until"]:
                        if datetime.fromisoformat(ref_data["x2_until"]) > datetime.now():
                            reward = 8
                            
                    await add_diamonds(referrer_id, reward)
                    try: await bot.send_message(referrer_id, f"🎉 Новый реферал! Вам зачислено +{reward} алмазов (сработало x2 буст!)." if reward == 8 else "🎉 Новый реферал! +4 алмаза")
                    except Exception: pass
                    
    if not await check_subscription(user_id, bot):
        kb = InlineKeyboardBuilder()
        for channel, name_ch in CHANNELS: kb.button(text=name_ch, url=f"https://t.me/{channel[1:]}")
        kb.button(text="✅ Я подписался", callback_data="check_sub")
        kb.adjust(1)
        return await message.answer("👋 Для работы бота подпишись на каналы:", reply_markup=kb.as_markup())
        
    udata = await get_user_data(user_id, name)
    await message.answer(f"Добро пожаловать! 💎\n\nНа балансе: <b>{udata['diamonds']}</b> алмазов", reply_markup=main_menu(user_id))

async def check_subscription(user_id: int, bot: Bot) -> bool:
    for channel_data in CHANNELS:
        if isinstance(channel_data, (tuple, list)):
            channel = channel_data[0]
        else:
            channel = channel_data
            
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"Ошибка проверки подписки на {channel}: {e}")
            # Если бот не админ в закрытом канале, тут вылетит ошибка, и мы вернем False
            return False
    return True

    
    # Если премиум — просмотр бесплатный
    if udata["premium"] == 0:
        if udata["diamonds"] < 6: return await callback.answer("❌ Недостаточно алмазов (нужно 6)", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ?", (user_id,))
        await db.commit()
        
    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV")) + list(MEDIA_DIR.glob("*.avi"))
    if not videos: return await callback.answer("❌ Нет видео в папке data/media", show_alert=True)
    
    video_path = random.choice(videos)
    
    # Если у пользователя вечное видео или Premium+, оно не удалится
    is_forever = (udata["keep_videos"] == 1 or udata["premium"] == 2)
    caption_text = "📹 Вот твоё видео!\n\n⭐️ У вас подписка: видео останется навсегда!" if is_forever else "📹 Вот твоё видео!\n\n🕒 Оно удалится через 30 минут."
    
    msg = await bot.send_video(chat_id=user_id, video=FSInputFile(video_path), caption=caption_text)
    
    if not is_forever:
        await db.execute("INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)", (str(video_path), msg.message_id, user_id, (datetime.now() + timedelta(minutes=30)).isoformat()))
        await db.commit()
        
    await callback.answer("✅ Отправлено!")

@router.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    udata = await get_user_data(user_id, callback.from_user.first_name)
    
    # Если премиум — просмотр бесплатный
    if udata["premium"] == 0:
        if udata["diamonds"] < 3: return await callback.answer("❌ Недостаточно алмазов (нужно 3)", show_alert=True)
        await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ?", (user_id,))
        await db.commit()
        
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG"): photos.extend(PHOTO_DIR.glob(ext))
    if not photos: return await callback.answer("❌ Нет фото в папке data/photo", show_alert=True)
    
    try:
        # Для Premium+ указываем, что это из «архивов»
        cap = "📸 Ваше случайное фото из архивов!" if udata["premium"] == 2 else "📸 Ваше случайное фото!"
        await bot.send_photo(chat_id=user_id, photo=FSInputFile(random.choice(photos)), caption=cap)
        await callback.answer("✅ Отправлено!")
    except Exception:
        if udata["premium"] == 0:
            await add_diamonds(user_id, 3)
        await callback.answer("❌ Ошибка отправки.", show_alert=True)

@router.callback_query(F.data.in_({"back_main", "referral", "support"}))
async def menu_handlers(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if callback.data == "referral":
        me = await bot.get_me()
        text = f"👥 <b>Твоя реферальная ссылка:</b>\n\n<code>https://t.me/{me.username}?start={user_id}</code>\n\nЗа каждого реферала — <b>+4 алмаза</b>"
    elif callback.data == "support": text = "🛠 Техподдержка: @твой_юзернейм"
    else: text = "Главное меню"
    try: await callback.message.edit_text(text, reply_markup=main_menu(user_id) if callback.data not in ["referral", "support"] else None)
    except TelegramBadRequest: pass

@router.message(Command("restart_server"))
async def restart_server_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🔄 Выполняю полную перезагрузку ядра сервера...")
    import os, sys
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ========================= ЗАПУСК СИСТЕМЫ С МУЛЬТИБОТОМ =========================

async def delete_old_videos(bot: Bot):
    while True:
        await asyncio.sleep(30)
        try:
            now = datetime.now().isoformat()
            async with db.execute("SELECT message_id, chat_id FROM videos WHERE delete_at <= ?", (now,)) as cur: rows = await cur.fetchall()
            for message_id, chat_id in rows:
                try: await bot.delete_message(chat_id, message_id)
                except Exception: pass
                await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
            await db.commit()
        except Exception: pass

async def start_bot_polling(bot_instance: Bot):
    try:
        await bot_instance.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot_instance, handle_signals=False)
    except Exception as e:
        print(f"❌ Ошибка пулинга {bot_instance.token[:15]}: {e}")

async def main():
    await init_db()
    dp.include_router(router)

    # Запуск основного бота
    main_bot = Bot(token=MAIN_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    active_bots[MAIN_TOKEN] = main_bot
    asyncio.create_task(start_bot_polling(main_bot))
    
    # Запуск сохраненных зеркал из БД
    async with db.execute("SELECT token FROM mirrors") as cur: mirrors = await cur.fetchall()
    for (token,) in mirrors:
        if token in active_bots: continue
        try:
            mirror_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            active_bots[token] = mirror_bot
            asyncio.create_task(start_bot_polling(mirror_bot))
        except Exception: pass

    # Запускаем фоновую таску удаления видео
    asyncio.create_task(delete_old_videos(main_bot))
    
    print("🚀 Мультибот-платформа на Telegram Stars успешно запущена!")
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): print("Бот остановлен.")
