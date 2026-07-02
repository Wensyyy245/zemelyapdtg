import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, FSInputFile, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# ========================= НАСТРОЙКИ =========================

TOKEN = "8971264936:AAEX4G42x3OQRMdjvOJGAJFJdydIVDGp_PE"
ADMIN_ID = 8502341995

CHANNELS = [
    ("@XtrR9ohBifY1MGI6", "Канал 1"),
]

# Перенос всех путей в папку data
DATA_DIR = Path("data")
MEDIA_DIR = DATA_DIR / "media"
PHOTO_DIR = DATA_DIR / "photo"

DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
PHOTO_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"

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

# ========================= БАЗА ДАННЫХ =========================

db = None

async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    # Добавлено поле first_name для хранения имени (для топ-листов)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT 'Пользователь',
            diamonds INTEGER DEFAULT 8,
            referred_by INTEGER,
            is_banned INTEGER DEFAULT 0
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
                    try:
                        await event.answer("❌ Вы заблокированы в этом боте!", show_alert=True)
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
                return
    return await handler(event, data)

# ========================= КЛАВИАТУРЫ =========================

def main_menu(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📺 Смотреть видео (6 💎)", callback_data="watch")
    kb.button(text="📸 Посмотреть фото (3 💎)", callback_data="watch_photo")
    kb.button(text="🛒 Магазин", callback_data="shop")
    kb.button(text="🎟 Промокоды", callback_data="promo_menu")
    kb.button(text="🏆 Таблица лидеров", callback_data="leaderboard")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
    
    if user_id == ADMIN_ID:
        kb.button(text="⚙️ Admin Panel", callback_data="admin_enter")
        
    kb.adjust(1)
    return kb.as_markup()

def shop_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="100 алмазов — 50 ⭐", callback_data="buy_100")
    kb.button(text="250 алмазов — 95 ⭐", callback_data="buy_250")
    kb.button(text="500 алмазов — 150 ⭐", callback_data="buy_500")
    kb.button(text="💎 Другое количество", callback_data="buy_custom")
    kb.button(text="◀️ Назад", callback_data="back_main")
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

async def get_user_diamonds(user_id: int, first_name: str = "Пользователь") -> int:
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            # ИСПРАВЛЕНО: передаем ровно 2 параметра (user_id, first_name)
            await db.execute(
                "INSERT INTO users (user_id, first_name, diamonds) VALUES (?, ?, 8)", 
                (user_id, first_name)
            )
            await db.commit()
            return 8
        
        # Обновляем имя, если оно изменилось в ТГ
        await db.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        await db.commit()
        return row[0]

async def add_diamonds(user_id: int, amount: int):
    await db.execute(
        "UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", 
        (amount, user_id)
    )
    await db.commit()

# ========================= АДМИН ПАНЕЛЬ =========================

@router.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 Добро пожаловать в панель администратора:", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_enter")
async def admin_enter_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        try: await callback.answer("❌ Нет прав", show_alert=True)
        except Exception: pass
        return
    try:
        await callback.message.edit_text("🛠 Панель администратора:", reply_markup=admin_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    async with db.execute("SELECT COUNT(*), SUM(diamonds) FROM users") as cur:
        total_users, total_diamonds = await cur.fetchone()
    async with db.execute("SELECT COUNT(*) FROM promo_codes") as cur:
        total_promos = (await cur.fetchone())[0]
        
    now_time = datetime.now().strftime("%H:%M:%S")
    text = (
        f"📊 <b>Статистика бота (обновлено в {now_time}):</b>\n\n"
        f"👥 Всего пользователей: <code>{total_users}</code>\n"
        f"💎 Алмазов в системе: <code>{total_diamonds or 0}</code>\n"
        f"🎟 Активных промокодов: <code>{total_promos}</code>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer("📊 Статистика уже актуальна!")

@router.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    async with db.execute("SELECT user_id, first_name, diamonds, is_banned FROM users LIMIT 100") as cur:
        rows = await cur.fetchall()
        
    if not rows:
        return await callback.answer("База данных пуста.", show_alert=True)
        
    text = "👥 <b>Список участников (Топ-100):</b>\n\n"
    for row in rows:
        uid, name, diamonds, banned = row
        status = " [🔒]" if banned else ""
        text += f"▪️ <code>{uid}</code> — <b>{name}</b> ({diamonds} 💎){status}\n"
        
    # Кнопка возврата в админку
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в админку", callback_data="admin_enter")
    
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data == "admin_mail")
async def admin_mail(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try:
        await callback.message.edit_text("📢 Введите текст для рассылки (поддерживается HTML):")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    await state.set_state(AdminStates.mailing_text)

@router.message(AdminStates.mailing_text)
async def process_mailing(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    
    await message.answer("🚀 Рассылка запущена...")
    async with db.execute("SELECT user_id FROM users") as cur:
        rows = await cur.fetchall()
        
    count = 0
    for row in rows:
        try:
            await bot.send_message(chat_id=row[0], text=message.text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.answer(f"✅ Рассылка завершена. Успешно отправлено: {count} пользователям.")

@router.callback_query(F.data == "admin_user")
async def admin_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try:
        await callback.message.edit_text("👤 Введите Telegram ID пользователя для управления:")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    await state.set_state(AdminStates.user_manage_id)

@router.message(AdminStates.user_manage_id)
async def process_user_manage(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit():
        return await message.answer("❌ ID должен состоять только из цифр. Попробуйте еще раз.")
        
    target_id = int(message.text)
    async with db.execute("SELECT diamonds, is_banned, first_name FROM users WHERE user_id = ?", (target_id,)) as cur:
        row = await cur.fetchone()
        
    if not row:
        await state.clear()
        return await message.answer("❌ Пользователь не найден в базе данных.")
        
    await state.update_data(target_id=target_id)
    diamonds, is_banned, name = row
    
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Изменить баланс", callback_data="adm_change_bal")
    kb.button(text="🔓 Разбанить" if is_banned else "🔒 Забанить", callback_data="adm_toggle_ban")
    kb.button(text="❌ Отмена", callback_data="back_admin")
    kb.adjust(1)
    
    status = "ЗАБАНЕН" if is_banned else "Активен"
    await message.answer(
        f"👤 Пользователь: <b>{name}</b> (<code>{target_id}</code>)\n"
        f"💎 Баланс: <b>{diamonds}</b>\n"
        f"🚦 Статус: <b>{status}</b>", 
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "adm_toggle_ban")
async def adm_toggle_ban(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    target_id = data.get("target_id")
    
    async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (target_id,)) as cur:
        is_banned = (await cur.fetchone())[0]
        
    new_ban = 0 if is_banned else 1
    await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_ban, target_id))
    await db.commit()
    
    try: await callback.answer("✅ Статус бана изменен!")
    except Exception: pass
    await state.clear()
    try:
        await callback.message.edit_text("🛠 Операция успешна. Возвращаюсь в меню.", reply_markup=admin_menu())
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "adm_change_bal")
async def adm_change_bal(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    try:
        await callback.message.edit_text("💰 Введите число алмазов (например: 50 для начисления, или -50 для списания):")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    await state.set_state(AdminStates.change_balance)

@router.message(AdminStates.change_balance)
async def process_change_balance(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        amount = int(message.text)
    except ValueError:
        return await message.answer("❌ Введите корректное число.")
        
    data = await state.get_data()
    target_id = data.get("target_id")
    
    await add_diamonds(target_id, amount)
    await message.answer(f"✅ Баланс пользователя {target_id} изменен на {amount} алмазов.")
    await state.clear()

@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("🛠 Панель администратора:", reply_markup=admin_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

# ========================= СИСТЕМА ЛИДЕРБОРДОВ =========================

@router.callback_query(F.data == "leaderboard")
async def leaderboard_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. Топ по алмазам (тут всё работало отлично)
    async with db.execute("SELECT first_name, diamonds FROM users ORDER BY diamonds DESC LIMIT 5") as cur:
        top_diamonds = await cur.fetchall()
        
    # 2. ИСПРАВЛЕННЫЙ Топ по рефералам
    # Считаем количество упоминаний каждого пользователя в колонке referred_by
    async with db.execute("""
        SELECT u.first_name, COUNT(r.user_id) as ref_count
        FROM users u
        INNER JOIN users r ON r.referred_by = u.user_id
        GROUP BY u.user_id
        ORDER BY ref_count DESC
        LIMIT 5
    """) as cur:
        top_referrals = await cur.fetchall()
        
    text = "🏆 <b>ТАБЛИЦА ЛИДЕРОВ</b> 🏆\n\n"
    
    text += "💎 <b>Топ по алмазам:</b>\n"
    for i, (name, count) in enumerate(top_diamonds, 1):
        text += f"{i}. {name} — <code>{count}</code> 💎\n"
        
    text += "\n👥 <b>Топ по приглашениям:</b>\n"
    
    if top_referrals:
        for i, (name, count) in enumerate(top_referrals, 1):
            text += f"{i}. {name} — <code>{count}</code> реф.\n"
    else:
        text += "<i>Пока никто никого не пригласил</i>\n"
        
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в меню", callback_data="back_main")
    
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

# ========================= КАТЕГОРИЯ ПРОМОКОДОВ =========================

@router.callback_query(F.data == "promo_menu")
async def promo_menu(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "🎟 <b>Система промокодов:</b>\n\nВы можете активировать чужой промокод или создать свой собственный, выделив алмазы из личного баланса.",
            reply_markup=promo_menu_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data == "promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text("✨ Придумайте и напишите текст промокода (английские буквы/цифры):")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    await state.set_state(PromoStates.create_code)

@router.message(PromoStates.create_code)
async def process_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if not code.isalnum():
        return await message.answer("❌ Промокод должен состоять только из букв и цифр.")
        
    async with db.execute("SELECT 1 FROM promo_codes WHERE code = ?", (code,)) as cur:
        if await cur.fetchone():
            return await message.answer("❌ Такой промокод уже существует. Придумайте другой.")
            
    await state.update_data(code=code)
    await message.answer("💎 Сколько алмазов получит активировавший (награда за 1 активацию)?")
    await state.set_state(PromoStates.create_reward)

@router.message(PromoStates.create_reward)
async def process_promo_reward(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1:
        return await message.answer("❌ Введите целое число больше нуля.")
        
    await state.update_data(reward=int(message.text))
    await message.answer("👥 Сколько человек смогут активировать этот промокод?")
    await state.set_state(PromoStates.create_uses)

@router.message(PromoStates.create_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1:
        return await message.answer("❌ Введите целое число больше нуля.")
        
    uses = int(message.text)
    data = await state.get_data()
    code = data['code']
    reward = data['reward']
    
    total_cost = reward * uses
    user_id = message.from_user.id
    user_diamonds = await get_user_diamonds(user_id, message.from_user.first_name)
    
    if user_diamonds < total_cost:
        await state.clear()
        return await message.answer(f"❌ Недостаточно алмазов. Для создания нужно <b>{total_cost}</b> 💎, у вас: <b>{user_diamonds}</b>")
        
    await db.execute("UPDATE users SET diamonds = diamonds - ? WHERE user_id = ?", (total_cost, user_id))
    await db.execute(
        "INSERT INTO promo_codes (code, creator_id, reward, uses_left) VALUES (?, ?, ?, ?)",
        (code, user_id, reward, uses)
    )
    await db.commit()
    
    await message.answer(
        f"✅ Промокод успешно создан!\n\n"
        f"🎫 Код: <code>{code}</code>\n"
        f"💎 Награда: {reward} за активацию\n"
        f"👥 Кол-во активаций: {uses}\n"
        f"💸 Списано с баланса: {total_cost} алмазов.",
        reply_markup=main_menu(user_id)
    )
    await state.clear()

@router.callback_query(F.data == "promo_activate")
async def promo_activate(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text("📥 Введите промокод для активации:")
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()
    await state.set_state(PromoStates.activate_code)

@router.message(PromoStates.activate_code)
async def process_promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    async with db.execute("SELECT creator_id, reward, uses_left FROM promo_codes WHERE code = ?", (code,)) as cur:
        row = await cur.fetchone()
        
    if not row:
        await state.clear()
        return await message.answer("❌ Такого промокода не существует или он истек.", reply_markup=main_menu(user_id))
        
    creator_id, reward, uses_left = row
    
    if creator_id == user_id:
        await state.clear()
        return await message.answer("❌ Вы не можете активировать собственный промокод.", reply_markup=main_menu(user_id))
        
    if uses_left <= 0:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        await db.commit()
        await state.clear()
        return await message.answer("❌ У этого промокода закончились активации.", reply_markup=main_menu(user_id))
        
    new_uses = uses_left - 1
    if new_uses == 0:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    else:
        await db.execute("UPDATE promo_codes SET uses_left = ? WHERE code = ?", (new_uses, code))
        
    await add_diamonds(user_id, reward)
    await db.commit()
    
    await message.answer(f"🎉 Промокод успешно активирован! +<b>{reward}</b> 💎 добавлено на баланс.", reply_markup=main_menu(user_id))
    await state.clear()

# ========================= СТАНДАРТНЫЕ ОБРАБОТЧИКИ =========================

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
                    await add_diamonds(referrer_id, 4)
                    try:
                        await bot.send_message(referrer_id, "🎉 Новый реферал! +4 алмаза")
                    except TelegramForbiddenError:
                        pass
                    except Exception:
                        pass

    if not await check_subscription(user_id, bot):
        kb = InlineKeyboardBuilder()
        for channel, name_ch in CHANNELS:
            kb.button(text=name_ch, url=f"https://t.me/{channel[1:]}")
        kb.button(text="✅ Я подписался", callback_data="check_sub")
        kb.adjust(1)
        await message.answer("👋 Для работы бота подпишись на каналы:", reply_markup=kb.as_markup())
        return

    diamonds = await get_user_diamonds(user_id, name)
    await message.answer(
        f"Добро пожаловать! 💎\n\nНа балансе: <b>{diamonds}</b> алмазов",
        reply_markup=main_menu(user_id)
    )

@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    name = callback.from_user.first_name
    try:
        if await check_subscription(user_id, bot):
            await get_user_diamonds(user_id, name)
            await callback.message.edit_text("✅ Подписка подтверждена!", reply_markup=main_menu(user_id))
        else:
            await callback.answer("❌ Ты не подписался на все каналы!", show_alert=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    diamonds = await get_user_diamonds(user_id, callback.from_user.first_name)

    if diamonds < 6:
        try: return await callback.answer("❌ Недостаточно алмазов (нужно 6)", show_alert=True)
        except (TelegramBadRequest, TelegramForbiddenError): return

    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV")) + list(MEDIA_DIR.glob("*.avi"))
    if not videos:
        try: return await callback.answer("❌ Нет видео в папке data/media", show_alert=True)
        except (TelegramBadRequest, TelegramForbiddenError): return

    await db.execute("UPDATE users SET diamonds = diamonds - 6 WHERE user_id = ?", (user_id,))
    await db.commit()

    video_path = random.choice(videos)
    msg = await bot.send_video(
        chat_id=user_id,
        video=FSInputFile(video_path),
        caption="📹 Вот твоё видео!\n\n🕒 Оно удалится автоматически через 30 минут."
    )

    delete_time = (datetime.now() + timedelta(minutes=30)).isoformat()
    await db.execute(
        "INSERT INTO videos (file_id, message_id, chat_id, delete_at) VALUES (?, ?, ?, ?)",
        (str(video_path), msg.message_id, user_id, delete_time)
    )
    await db.commit()

    try: await callback.answer("✅ Видео отправлено!")
    except (TelegramBadRequest, TelegramForbiddenError): pass

# КНОПКА ОТПРАВКИ РАНДОМНОГО ФОТО ЗА 3 АЛМАЗА
@router.callback_query(F.data == "watch_photo")
async def watch_photo(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    diamonds = await get_user_diamonds(user_id, callback.from_user.first_name)

    if diamonds < 3:
        try: return await callback.answer("❌ Недостаточно алмазов (нужно 3)", show_alert=True)
        except (TelegramBadRequest, TelegramForbiddenError): return

    # Ищем картинки расширений jpg, jpeg, png, webp
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG"):
        photos.extend(PHOTO_DIR.glob(ext))

    if not photos:
        try: return await callback.answer("❌ Нет фото в папке data/photo", show_alert=True)
        except (TelegramBadRequest, TelegramForbiddenError): return

    await db.execute("UPDATE users SET diamonds = diamonds - 3 WHERE user_id = ?", (user_id,))
    await db.commit()

    photo_path = random.choice(photos)
    
    try:
        await bot.send_photo(
            chat_id=user_id,
            photo=FSInputFile(photo_path),
            caption="📸 Ваше случайное фото!"
        )
        await callback.answer("✅ Фото отправлено!")
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        # Если отправка сорвалась, возвращаем баланс
        await add_diamonds(user_id, 3)
        try: await callback.answer("❌ Ошибка отправки фото.", show_alert=True)
        except Exception: pass

@router.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🛒 Магазин алмазов:", reply_markup=shop_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data.startswith("buy_"))
async def buy_diamonds(callback: CallbackQuery, bot: Bot):
    data = callback.data
    prices = {"buy_100": (100, 50), "buy_250": (250, 95), "buy_500": (500, 150)}

    if data in prices:
        diamonds, stars = prices[data]
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"{diamonds} алмазов",
            description=f"Оплата {stars} Telegram Stars",
            payload=f"diamonds_{diamonds}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{diamonds} алмазов", "amount": stars}]
        )
    elif data == "buy_custom":
        try:
            await callback.message.edit_text(
                "Напиши количество алмазов (1 алмаз = 1 ⭐):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="shop")]])
            )
        except TelegramBadRequest:
            pass
    try: await callback.answer()
    except (TelegramBadRequest, TelegramForbiddenError): pass

@router.message(F.text.isdigit())
async def custom_amount(message: Message, bot: Bot):
    try:
        amount = int(message.text)
        if amount < 1: raise ValueError
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title=f"{amount} алмазов",
            description=f"Оплата {amount} Telegram Stars",
            payload=f"diamonds_{amount}",
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{amount} алмазов", "amount": amount}]
        )
    except Exception:
        await message.answer("❌ Введи корректное число.")

@router.pre_checkout_query()
async def pre_checkout(pre: PreCheckoutQuery):
    await pre.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    diamonds = int(message.successful_payment.invoice_payload.split("_")[1])
    await add_diamonds(message.from_user.id, diamonds)
    await message.answer(f"✅ Успешно! +<b>{diamonds}</b> алмазов")

@router.callback_query(F.data.in_({"back_main", "referral", "support"}))
async def menu_handlers(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if callback.data == "referral":
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={user_id}"
        text = f"👥 <b>Твоя реферальная ссылка:</b>\n\n<code>{link}</code>\n\nЗа каждого подписавшегося реферала — <b>+4 алмаза</b>"
    elif callback.data == "support":
        text = "🛠 Техподдержка: @твой_юзернейм"
    else:
        text = "Главное меню"

    try:
        await callback.message.edit_text(
            text, 
            reply_markup=main_menu(user_id) if callback.data not in ["referral", "support"] else None
        )
        await callback.answer()
    except TelegramBadRequest:
        await callback.answer()

# ========================= ЗАПУСК =========================

async def delete_old_videos(bot: Bot):
    while True:
        await asyncio.sleep(30)
        try:
            now = datetime.now().isoformat()
            async with db.execute("SELECT message_id, chat_id, file_id FROM videos WHERE delete_at <= ?", (now,)) as cur:
                rows = await cur.fetchall()
            
            if not rows: continue

            for message_id, chat_id, file_id in rows:
                try: await bot.delete_message(chat_id, message_id)
                except Exception: pass
                
                await db.execute("DELETE FROM videos WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
            await db.commit()
        except Exception as e:
            print(f"Ошибка в таске очистки видео: {e}")

async def main():
    await init_db()
    
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    dp.include_router(router)

    asyncio.create_task(delete_old_videos(bot))

    print("✅ Бот успешно запущен на хостинге!")
    await dp.start_polling(bot, handle_signals=False, close_bot_session=True)

if __name__ == "__main__":
    asyncio.run(main())
