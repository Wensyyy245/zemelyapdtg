import aiosqlite
import json
from datetime import datetime
from pathlib import Path

TOKENS_DB_PATH = Path("data/tokens.db")
TOKENS_DB_PATH.parent.mkdir(exist_ok=True)

class TokensDB:
    _instance = None
    _db = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def init(self):
        """Инициализация базы данных токенов"""
        self._db = await aiosqlite.connect(TOKENS_DB_PATH)
        
        # Таблица токенов
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                username TEXT,
                added_by INTEGER,
                status TEXT DEFAULT 'available',  -- available, used, banned
                created_at TEXT,
                used_at TEXT,
                mirror_id INTEGER,
                user_id INTEGER,
                last_heartbeat TEXT,
                is_active INTEGER DEFAULT 0
            )
        """)
        
        # Индексы
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_status ON tokens (status)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens (user_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_username ON tokens (username)")
        
        await self._db.commit()
        print("✅ База данных токенов инициализирована")

    async def add_token(self, token: str, username: str = None, added_by: int = None) -> bool:
        """Добавляет токен в базу"""
        try:
            await self._db.execute(
                "INSERT INTO tokens (token, username, added_by, created_at, status) VALUES (?, ?, ?, ?, 'available')",
                (token, username, added_by, datetime.now().isoformat())
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_available_token(self) -> dict:
        """Получает доступный токен"""
        async with self._db.execute(
            "SELECT id, token, username FROM tokens WHERE status = 'available' LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row:
            return {"id": row[0], "token": row[1], "username": row[2]}
        return None

    async def get_user_tokens(self, user_id: int) -> list:
        """Получает токены пользователя"""
        async with self._db.execute(
            "SELECT id, token, username, status, created_at, used_at, is_active FROM tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ) as cur:
            return await cur.fetchall()

    async def use_token(self, token: str, user_id: int, mirror_id: int = None):
        """Помечает токен как использованный"""
        await self._db.execute(
            "UPDATE tokens SET status = 'used', used_at = ?, user_id = ?, mirror_id = ? WHERE token = ?",
            (datetime.now().isoformat(), user_id, mirror_id, token)
        )
        await self._db.commit()

    async def update_token_status(self, token: str, status: str, is_active: int = None):
        """Обновляет статус токена"""
        if is_active is not None:
            await self._db.execute(
                "UPDATE tokens SET status = ?, is_active = ? WHERE token = ?",
                (status, is_active, token)
            )
        else:
            await self._db.execute(
                "UPDATE tokens SET status = ? WHERE token = ?",
                (status, token)
            )
        await self._db.commit()

    async def get_token_by_username(self, username: str) -> dict:
        """Получает токен по юзернейму"""
        async with self._db.execute(
            "SELECT id, token, username, status, user_id, is_active FROM tokens WHERE username = ?",
            (username,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return {
                "id": row[0],
                "token": row[1],
                "username": row[2],
                "status": row[3],
                "user_id": row[4],
                "is_active": row[5]
            }
        return None

    async def get_all_tokens(self) -> list:
        """Получает все токены"""
        async with self._db.execute(
            "SELECT id, token, username, status, user_id, is_active FROM tokens ORDER BY created_at DESC"
        ) as cur:
            return await cur.fetchall()

    async def get_stats(self) -> dict:
        """Получает статистику по токенам"""
        async with self._db.execute("SELECT COUNT(*) FROM tokens") as cur:
            total = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM tokens WHERE status = 'available'") as cur:
            available = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM tokens WHERE status = 'used'") as cur:
            used = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM tokens WHERE status = 'banned'") as cur:
            banned = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM tokens WHERE is_active = 1") as cur:
            active = (await cur.fetchone())[0]
        
        return {
            "total": total,
            "available": available,
            "used": used,
            "banned": banned,
            "active": active
        }

    async def close(self):
        if self._db:
            await self._db.close()

# Глобальный экземпляр
tokens_db = TokensDB()
