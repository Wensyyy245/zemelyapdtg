import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
import aiogram.client.session.aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, FSInputFile, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# ========================= НАСТРОЙКИ =========================

# ⚠️ ВНИМАНИЕ: Обязательно зайди в @BotFather, нажми /revoke и получи НОВЫЙ токен.
# Этот токен уже «засвечен» в интернете, его могут украсть злоумышленники!
TOKEN = "8766874600:AAEgeJveXfh95zH23GVlaHnOLuHAt5hpJUw"  

# Каналы для обязательной подписки
CHANNELS = [
    ("@zemelya_new", "Канал 1"),
]

MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

# ========================= БАЗА ДАННЫХ =========================

db = None

async def init_db():
    global db
    db = await aiosqlite.connect("bot.db")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            diamonds INTEGER DEFAULT 8,
            referred_by INTEGER
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
    await db.commit()

# ========================= КЛАВИАТУРЫ =========================

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📺 Смотреть видео", callback_data="watch")
    kb.button(text="🛒 Магазин", callback_data="shop")
    kb.button(text="👥 Рефералы", callback_data="referral")
    kb.button(text="🛠 Техподдержка", callback_data="support")
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

async def get_user_diamonds(user_id: int) -> int:
    async with db.execute("SELECT diamonds FROM users WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, diamonds) VALUES (?, 8)", (user_id,))
            await db.commit()
            return 8
        return row[0]

async def add_diamonds(user_id: int, amount: int):
    await db.execute(
        "UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", 
        (amount, user_id)
    )
    await db.commit()

# ========================= ОБРАБОТЧИКИ =========================

router = Router()

@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    user_id = message.from_user.id
    args = message.text.split()

    # Реферальная система
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            async with db.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,)) as cur:
                if not await cur.fetchone():
                    await db.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                    await add_diamonds(referrer_id, 4)
                    try:
                        await bot.send_message(referrer_id, "🎉 Новый реферал! +4 алмаза")
                    except Exception:
                        pass

    if not await check_subscription(user_id, bot):
        kb = InlineKeyboardBuilder()
        for channel, name in CHANNELS:
            kb.button(text=name, url=f"https://t.me/{channel[1:]}")
        kb.button(text="✅ Я подписался", callback_data="check_sub")
        kb.adjust(1)
        await message.answer("👋 Для работы бота подпишись на каналы:", reply_markup=kb.as_markup())
        return

    diamonds = await get_user_diamonds(user_id)
    await message.answer(
        f"Добро пожаловать! 💎\n\nНа балансе: <b>{diamonds}</b> алмазов",
        reply_markup=main_menu()
    )


@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, bot: Bot):
    if await check_subscription(callback.from_user.id, bot):
        await callback.message.edit_text(
            "✅ Подписка подтверждена!", 
            reply_markup=main_menu()
        )
    else:
        try:
            await callback.answer("❌ Ты не подписался на все каналы!", show_alert=True)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "watch")
async def watch(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    diamonds = await get_user_diamonds(user_id)

    if diamonds < 6:
        try:
            return await callback.answer("❌ Недостаточно алмазов (нужно 6)", show_alert=True)
        except TelegramBadRequest:
            return

    videos = list(MEDIA_DIR.glob("*.mp4")) + list(MEDIA_DIR.glob("*.MOV")) + list(MEDIA_DIR.glob("*.avi"))
    if not videos:
        try:
            return await callback.answer("❌ Нет видео в папке media", show_alert=True)
        except TelegramBadRequest:
            return

    # Списываем баланс только при наличии файлов
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

    try:
        await callback.answer("✅ Видео отправлено!")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    await callback.message.edit_text("🛒 Магазин алмазов:", reply_markup=shop_menu())
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


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
        await callback.message.edit_text(
            "Напиши количество алмазов (1 алмаз = 1 ⭐):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="shop")]])
        )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


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
    if callback.data == "referral":
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={callback.from_user.id}"
        text = f"👥 <b>Твоя реферальная ссылка:</b>\n\n<code>{link}</code>\n\nЗа каждого подписавшегося реферала — <b>+4 алмаза</b>"
    elif callback.data == "support":
        text = "🛠 Техподдержка: @твой_юзернейм"
    else:
        text = "Главное меню"

    await callback.message.edit_text(
        text, 
        reply_markup=main_menu() if callback.data not in ["referral", "support"] else None
    )
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


# ========================= ЗАПУСК =========================

async def delete_old_videos(bot: Bot):
    while True:
        await asyncio.sleep(30)  # Проверка каждые 30 секунд
        try:
            now = datetime.now().isoformat()
            
            # Сначала безопасно выбираем все старые видео
            async with db.execute("SELECT message_id, chat_id, file_id FROM videos WHERE delete_at <= ?", (now,)) as cur:
                rows = await cur.fetchall()
            
            if not rows:
                continue

            # Удаляем сообщения в Telegram и записи из базы
            for message_id, chat_id, file_id in rows:
                try:
                    await bot.delete_message(chat_id, message_id)
                except Exception:
                    pass  # Если пользователь уже сам удалил сообщение
                
                await db.execute(
                    "DELETE FROM videos WHERE message_id = ? AND chat_id = ?", 
                    (message_id, chat_id)
                )
            await db.commit()  # Коммитим всё разом, база не заблокируется
            
        except Exception as e:
            print(f"Ошибка в таске очистки видео: {e}")


async def main():
    await init_db()
    
    # Возвращаемся к стандартному серверу Telegram
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    dp.include_router(router)

    asyncio.create_task(delete_old_videos(bot))

    print("✅ Бот запущен! Ошибки сети будут обрабатываться автоматически.")
    
    # Режим ожидания (polling) с игнорированием сетевых ошибок, чтобы бот не падал
    await dp.start_polling(
        bot, 
        handle_signals=False, 
        close_bot_session=True
    )

if __name__ == "__main__":
    asyncio.run(main())