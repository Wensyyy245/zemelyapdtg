import asyncio
import logging
import random
import aiohttp
import sys
from pathlib import Path
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Определение абсолютных путей
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_FILE = DATA_DIR / "tokens.db"

# Принудительно создаем папку data, если её нет
DATA_DIR.mkdir(parents=True, exist_ok=True)

if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# ========================= НАСТРОЙКИ И ЛОГИРОВАНИЕ =========================
MAIN_BOT_TOKEN = "8546316879:AAHjZPp3iQjtmyaeQxET1-IKSbUy4z6RJ6A"  # Твой проверяльщик
LOG_GROUP_ID = -5417151890
ADMIN_ID = 8794011165

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ========================= ИМПОРТ TOKENS_DB ИЗ MAIN =========================
try:
    from main import tokens_db
    USE_DB = True
    log.info("✅ tokens_db успешно импортирован из main.py")
except ImportError as e:
    USE_DB = False
    log.warning(f"⚠️ Не удалось импортировать tokens_db из main.py ({e}), будет использоваться fallback")

# ========================= ХЕЛПЕРЫ =========================
async def check_bot(session: aiohttp.ClientSession, token: str) -> dict | None:
    if ":" not in token:
        return {"token": token, "username": token}

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            data = await resp.json()
            if data.get("ok"):
                username = data["result"].get("username")
                return {"token": token, "username": username or "unknown"}
    except Exception as e:
        log.debug(f"Токен нерабочий: {str(e)[:50]}")
    return None

async def get_working_bots(tokens: list[str]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(check_bot(session, t) for t in tokens), return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]

async def init_db_with_path():
    if not USE_DB:
        return
    
    for attr in ("db_path", "path", "_db_path", "db_name"):
        if hasattr(tokens_db, attr):
            setattr(tokens_db, attr, DATABASE_FILE)
            log.info(f"⚙️ В tokens_db из main.py установлен Path: {DATABASE_FILE}")
            
    await tokens_db.init()

async def get_tokens_from_db() -> list[str]:
    if not USE_DB:
        return []
    try:
        await init_db_with_path()
        tokens = []
        async with tokens_db._conn().execute(
            "SELECT token FROM tokens WHERE status IN ('available', 'used', 'active')"
        ) as cur:
            rows = await cur.fetchall()
            tokens = [row[0] for row in rows]
        log.info(f"📥 Загружено {len(tokens)} токенов/юзернеймов из {DATABASE_FILE}")
        return tokens
    except Exception as e:
        log.error(f"Ошибка получения токенов из БД: {e}")
        return []

# ========================= НОВАЯ ПЕРЕМЕННАЯ =========================
BOTS_DISABLED = False

async def do_clean_tokens():
    global BOTS_DISABLED
    if BOTS_DISABLED:
        return

    try:
        tokens = await get_tokens_from_db()
        working = await get_working_bots(tokens)
        working_usernames = {w["username"] for w in working if w["username"] != "unknown"}
        
        dead_count = 0
        for token in tokens:
            if ":" not in token:
                continue

            bot = Bot(token=token)
            try:
                await bot.get_me()
                username = (await bot.get_me()).username
                if username in working_usernames:
                    await bot.session.close()
                    continue
                await bot.session.close()
            except Exception:
                pass
            
            if hasattr(tokens_db, "update_token_status"):
                await tokens_db.update_token_status(token, "dead", 0)
                await tokens_db._conn().execute(
                    "DELETE FROM tokens WHERE token = ? AND status = 'dead'",
                    (token,)
                )
                await tokens_db._conn().commit()
                dead_count += 1
        
        if dead_count > 0:
            log.info(f"🧹 Удалено {dead_count} мёртвых токенов")
        else:
            log.debug("✅ Все токены рабочие, удаление не нужно")
    except Exception as e:
        log.error(f"Ошибка в проверке токенов: {e}")

async def remove_dead_tokens():
    global BOTS_DISABLED
    if BOTS_DISABLED:
        log.warning("🚫 Боты отключены — очистка токенов при запуске НЕ запускается")
        return

    log.info("🔍 Запуск первичной проверки и очистки токенов при старте...")
    await do_clean_tokens()
    
    while True:
        try:
            await asyncio.sleep(3600)
            now = datetime.now()
            if now.hour == 0 and now.minute == 0:
                log.info("⏰ Ежедневная плановая очистка токенов (00:00)...")
                await do_clean_tokens()
        except Exception as e:
            log.error(f"Ошибка в цикле remove_dead_tokens: {e}")

async def send_log(text: str):
    try:
        bot = Bot(token=MAIN_BOT_TOKEN)
        await bot.send_message(LOG_GROUP_ID, f"📋 {text}")
        await bot.session.close()
    except Exception as e:
        log.error(f"Не удалось отправить лог в Telegram-группу: {e}")

# ========================= ХЕНДЛЕРЫ =========================
async def cmd_start(message: Message):
    global BOTS_DISABLED
    if BOTS_DISABLED:
        await message.answer(
            "🚫 <b>Анти-снос бот временно отключен</b>\n\n"
            "Будет включен когда когда будет нужно\n"
            "Следите за новостями в нашем тгк: https://t.me/+JypFAG4wqgk0ZTEy",
            parse_mode="HTML"
        )
        return

    kb = InlineKeyboardBuilder()
    kb.button(text='Найти', callback_data="check_bots:none")
    kb.adjust(1)
    
    user_name = message.from_user.first_name if message.from_user else "пользователь"
    
    text = (
        f'<tg-emoji emoji-id="5472055112702629499">👋</tg-emoji> Привет, <b>{user_name}</b>! '
        'Я бот, который поможет тебе найти наших ботов. Нажми кнопку ниже:'
    )
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

async def check_bots_handler(callback: CallbackQuery):
    global BOTS_DISABLED
    if BOTS_DISABLED:
        await callback.message.edit_text(
            "🚫 <b>Анти-снос бот временно отключен</b>\n\n"
            "Будет включен когда когда будет нужно\n"
            "Следите за новостями в нашем тгк: https://t.me/+3pDFo-jEEpk5ZWYy",
            parse_mode="HTML"
        )
        return

    await callback.answer("Ищем случайного бота...")
    
    current_bot_username = callback.data.split(":")[1]
    
    tokens = await get_tokens_from_db()
    if not tokens:
        return await callback.message.edit_text("❌ Нет токенов в базе или база недоступна.")
    
    working = await get_working_bots(tokens)
    if not working:
        return await callback.message.edit_text("❌ Нет доступных рабочих ботов в данный момент.")
    
    candidates = [b for b in working if b['username'] != current_bot_username]
    if not candidates:  
        candidates = working  
        
    random_bot = random.choice(candidates)
    random_text = f"🎲 <b>Случайный рабочий бот:</b>\n🤖 @{random_bot['username']}"
        
    kb = InlineKeyboardBuilder()
    kb.button(text="🔥 Перейти к боту", url=f"https://t.me/{random_bot['username']}")
    kb.button(text="🔄 Обновить", callback_data=f"check_bots:{random_bot['username']}")
    kb.adjust(1)
    
    try:
        await callback.message.edit_text(random_text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e):
            log.error(f"Ошибка изменения сообщения: {e}")

async def cmd_add_bot(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer(
            "⚠️ <b>Формат команды:</b>\n<code>/adddbot юзернейм_бота</code>", 
            parse_mode="HTML"
        )

    bot_username = args[1].strip().replace("@", "")

    if not bot_username:
        return await message.answer("❌ Юзернейм не может быть пустым.")

    if not USE_DB:
        return await message.answer("❌ База данных недоступна (ошибка импорта tokens_db).")

    try:
        async with tokens_db._conn().execute(
            "SELECT token FROM tokens WHERE token = ?", (bot_username,)
        ) as cur:
            exists = await cur.fetchone()
        
        if exists:
            return await message.answer(f"⚠️ Бот <code>@{bot_username}</code> уже есть в базе данных.", parse_mode="HTML")

        await tokens_db._conn().execute(
            "INSERT INTO tokens (token, status) VALUES (?, 'available')",
            (bot_username,)
        )
        await tokens_db._conn().commit()

        log.info(f"➕ Админ добавил нового бота в БД: @{bot_username}")
        await message.answer(f"✅ Бот <code>@{bot_username}</code> успешно добавлен в базу данных со статусом <b>available</b>.", parse_mode="HTML")

    except Exception as e:
        log.error(f"Ошибка при добавлении бота в БД: {e}")
        await message.answer(f"❌ Произошла ошибка при сохранении в базе данных: {e}")

async def cmd_remove_bot(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer(
            "⚠️ <b>Формат команды:</b>\n<code>/removeeebot юзернейм_или_токен</code>", 
            parse_mode="HTML"
        )

    target = args[1].strip().replace("@", "")

    if not target:
        return await message.answer("❌ Значение для удаления не может быть пустым.")

    if not USE_DB:
        return await message.answer("❌ База данных недоступна.")

    try:
        async with tokens_db._conn().execute(
            "SELECT token FROM tokens WHERE token = ?", (target,)
        ) as cur:
            exists = await cur.fetchone()

        if not exists:
            return await message.answer(f"❌ Бот или токен <code>{target}</code> не найден в базе данных.", parse_mode="HTML")

        await tokens_db._conn().execute(
            "DELETE FROM tokens WHERE token = ?", (target,)
        )
        await tokens_db._conn().commit()

        log.info(f"🗑️ Админ удалил бота/токен из БД: {target}")
        await message.answer(f"✅ Бот/токен <code>{target}</code> успешно удален из базы данных.", parse_mode="HTML")

    except Exception as e:
        log.error(f"Ошибка при удалении бота из БД: {e}")
        await message.answer(f"❌ Произошла ошибка при удалении из базы данных: {e}")

# НОВЫЕ КОМАНДЫ /off и /on (только для админа)
async def cmd_off(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    global BOTS_DISABLED
    BOTS_DISABLED = True
    
    log.info("🚫 /off — боты отключены админом")
    await send_log(
        "🚫 Анти-снос бот временно отключен\n"
        "Будет включен когда когда будет нужно\n"
        "Следите за новостями в нашем тгк: https://t.me/+JypFAG4wqgk0ZTEy"
    )

async def cmd_on(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    global BOTS_DISABLED
    BOTS_DISABLED = False
    
    log.info("✅ /on — боты снова активны")
    await send_log("✅ Анти-снос бот включен. Полная работа возобновлена.")
    
    asyncio.create_task(remove_dead_tokens())

# ========================= ЗАПУСК =========================
async def main():
    log.info("🚀 Запуск active.py...")
    if USE_DB:
        await init_db_with_path()

    global BOTS_DISABLED
    
    if BOTS_DISABLED:
        log.warning("🚫 Боты отключены — очистка токенов при запуске НЕ запускается")
        await send_log(
            "🚫 Анти-снос бот временно отключен\n"
            "Будет включен когда когда будет нужно\n"
            "Следите за новостями в нашем тгк: https://t.me/+JypFAG4wqgk0ZTEy"
        )
    else:
        asyncio.create_task(remove_dead_tokens())
    
    bot = Bot(token=MAIN_BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрация хендлеров (включая новые /off и /on)
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_add_bot, F.text.startswith('/adddbot'))
    dp.message.register(cmd_remove_bot, F.text.startswith('/removeeebot'))
    dp.message.register(cmd_off, F.text.startswith('/off'))
    dp.message.register(cmd_on, F.text.startswith('/on'))
    dp.callback_query.register(check_bots_handler, F.data.startswith("check_bots:"))
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
