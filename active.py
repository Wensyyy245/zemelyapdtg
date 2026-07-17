import asyncio
import logging
import random
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
import sys
from pathlib import Path

# Добавляем путь для импорта tokens_db
sys.path.append(str(Path(__file__).parent))

# ========================= НАСТРОЙКИ =========================

# Токен бота-проверяльщика (тот, что будет отвечать на /start)
MAIN_BOT_TOKEN = "8859387155:AAFB24uaJowsQIv7r9ytYZ1IDPhf7Uaj79c"

# Список токенов для проверки (будет дополняться из БД)
BOT_TOKENS = [
    "8850923714:AAHbpaPvNlRY9Od7HLcfl5Iabd2kaE8KVY0",
    "8570482228:AAEcejQ7tilDewJNs6rSL3A3c8wCXtEB2Xw",
    "8693601845:AAFYjo4eWzZf_CosjKETLfvLmND7fNQGLyo",
]

# Группа для логов
LOG_GROUP_ID = -5417151890

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ========================= ИМПОРТ БД ТОКЕНОВ =========================

try:
    from tokens_db import tokens_db
    USE_DB = True
    log.info("✅ База данных токенов подключена")
except ImportError:
    USE_DB = False
    log.warning("⚠️ tokens_db не найден, работаем с фиксированным списком")

# ========================= ХЕЛПЕРЫ =========================

async def check_bot(session: aiohttp.ClientSession, token: str) -> dict | None:
    """
    Проверяет токен через метод getMe.
    Возвращает словарь с username и token, если токен рабочий, иначе None.
    """
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            if data.get("ok"):
                username = data["result"].get("username")
                return {"token": token, "username": username}
            else:
                return None
    except Exception as e:
        log.warning("Токен нерабочий (%s): %s...", str(e)[:30], token[:10])
        return None

async def get_working_bots(tokens: list[str]) -> list[dict]:
    """Проверяет все токены параллельно и возвращает список рабочих ботов."""
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(check_bot(session, t) for t in tokens))
    return [r for r in results if r is not None]

async def get_tokens_from_db() -> list[str]:
    """Получает токены из базы данных"""
    if not USE_DB:
        return BOT_TOKENS
    
    try:
        await tokens_db.init()
        tokens = []
        async with tokens_db._db.execute(
            "SELECT token FROM tokens WHERE status = 'available' OR status = 'used'"
        ) as cur:
            rows = await cur.fetchall()
            tokens = [row[0] for row in rows]
        return tokens
    except Exception as e:
        log.error(f"Ошибка получения токенов из БД: {e}")
        return BOT_TOKENS

async def send_log(text: str):
    """Отправляет лог в группу"""
    try:
        bot = Bot(token=MAIN_BOT_TOKEN)
        await bot.send_message(LOG_GROUP_ID, f"📋 {text}")
        await bot.session.close()
    except Exception as e:
        log.error(f"Ошибка отправки лога: {e}")

# ========================= ХЕНДЛЕРЫ =========================

async def cmd_start(message: Message) -> None:
    """Обработчик команды /start"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    await message.answer(
        f"👋 Привет, {user_name}!\n\n"
        "Я бот-проверяльщик зеркал. Я найду для тебя рабочий бот из пула.\n\n"
        "Нажми кнопку ниже, чтобы проверить доступные боты:",
        reply_markup=InlineKeyboardBuilder()
            .button(text="🔍 Проверить ботов", callback_data="check_bots")
            .button(text="📊 Статистика", callback_data="bot_stats")
            .adjust(1)
            .as_markup()
    )

async def cmd_check_bots(callback, is_callback=True) -> None:
    """Проверяет все боты и возвращает случайный рабочий"""
    
    # Получаем токены из БД или из списка
    tokens = await get_tokens_from_db()
    
    if not tokens:
        text = "❌ Нет токенов для проверки!"
        if is_callback:
            await callback.answer("Нет токенов!", show_alert=True)
            await callback.message.edit_text(text)
        else:
            await callback.message.answer(text)
        return
    
    # Проверяем токены
    working = await get_working_bots(tokens)
    
    if not working:
        text = "😔 Ни один бот не работает.\n\nПопробуйте позже или обратитесь в поддержку."
        if is_callback:
            await callback.answer("Ни один бот не работает!", show_alert=True)
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardBuilder()
                    .button(text="🔄 Проверить снова", callback_data="check_bots")
                    .as_markup()
            )
        else:
            await callback.message.answer(text)
        return
    
    # Выбираем случайный рабочий бот
    chosen = random.choice(working)
    
    # Создаем клавиатуру с кнопками для всех рабочих ботов
    kb = InlineKeyboardBuilder()
    for bot_info in working[:5]:  # Показываем максимум 5 ботов
        kb.button(
            text=f"🤖 @{bot_info['username']}",
            url=f"https://t.me/{bot_info['username']}"
        )
    
    kb.button(text="🔄 Обновить", callback_data="check_bots")
    kb.adjust(1)
    
    text = (
        f"✅ <b>Найден рабочий бот!</b>\n\n"
        f"🎯 <b>Случайный выбор:</b> @{chosen['username']}\n\n"
        f"📊 Всего проверено: <b>{len(tokens)}</b> токенов\n"
        f"🟢 Работает: <b>{len(working)}</b> ботов\n"
        f"🔴 Не работает: <b>{len(tokens) - len(working)}</b> ботов\n\n"
        f"👇 Нажми на бота, чтобы перейти:"
    )
    
    if is_callback:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()
    else:
        await callback.message.answer(text, reply_markup=kb.as_markup())

async def cmd_stats(message: Message) -> None:
    """Показывает статистику по ботам"""
    tokens = await get_tokens_from_db()
    working = await get_working_bots(tokens)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Проверить ботов", callback_data="check_bots")
    kb.button(text="◀️ Назад", callback_data="back_to_start")
    kb.adjust(1)
    
    text = (
        f"📊 <b>Статистика ботов</b>\n\n"
        f"📌 Всего токенов: <b>{len(tokens)}</b>\n"
        f"🟢 Работает: <b>{len(working)}</b>\n"
        f"🔴 Не работает: <b>{len(tokens) - len(working)}</b>\n\n"
        f"🕐 Последняя проверка: {datetime.now().strftime('%H:%M:%S')}"
    )
    
    if working:
        text += "\n\n✅ <b>Рабочие боты:</b>\n"
        for bot_info in working[:10]:
            text += f"  • @{bot_info['username']}\n"
        if len(working) > 10:
            text += f"  ... и еще {len(working) - 10} ботов"
    
    await message.answer(text, reply_markup=kb.as_markup())

# ========================= CALLBACK ХЕНДЛЕРЫ =========================

async def handle_check_bots(callback):
    """Обработчик нажатия на кнопку проверки"""
    await cmd_check_bots(callback, is_callback=True)

async def handle_bot_stats(callback):
    """Обработчик нажатия на кнопку статистики"""
    await cmd_stats(callback.message)

async def handle_back_to_start(callback):
    """Возврат в главное меню"""
    await callback.message.edit_text(
        "👋 <b>Бот-проверяльщик зеркал</b>\n\n"
        "Нажми кнопку ниже, чтобы проверить доступные боты:",
        reply_markup=InlineKeyboardBuilder()
            .button(text="🔍 Проверить ботов", callback_data="check_bots")
            .button(text="📊 Статистика", callback_data="bot_stats")
            .adjust(1)
            .as_markup()
    )
    await callback.answer()

# ========================= ЗАПУСК =========================

async def main() -> None:
    """Главная функция"""
    log.info("🚀 Запуск бота-проверяльщика...")
    
    # Инициализируем БД токенов если доступна
    if USE_DB:
        await tokens_db.init()
        log.info("✅ База данных токенов инициализирована")
    
    bot = Bot(token=MAIN_BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрируем хендлеры
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_stats, Command("stats"))
    
    # Регистрируем callback хендлеры
    dp.callback_query.register(handle_check_bots, F.data == "check_bots")
    dp.callback_query.register(handle_bot_stats, F.data == "bot_stats")
    dp.callback_query.register(handle_back_to_start, F.data == "back_to_start")
    
    log.info("✅ Бот запущен, ожидаем команды...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
