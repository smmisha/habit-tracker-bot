import json
import sqlite3
import aiosqlite
import asyncpg
from typing import Dict, Any, Optional
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

class PersistentSQLStorage(BaseStorage):
    def __init__(self, db_path_or_url: str):
        import urllib.parse
        self.db_path_or_url = str(db_path_or_url)
        self.is_pg = self.db_path_or_url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://"))
        if self.is_pg:
            try:
                scheme_split = self.db_path_or_url.split("://", 1)
                scheme = scheme_split[0]
                rest = scheme_split[1]
                if "@" in rest:
                    userinfo, hostspec = rest.rsplit("@", 1)
                    if ":" in userinfo:
                        user, password = userinfo.split(":", 1)
                        if urllib.parse.unquote(password) == password:
                            encoded_password = urllib.parse.quote(password)
                            userinfo = f"{user}:{encoded_password}"
                    rest = f"{userinfo}@{hostspec}"
                self.db_path_or_url = f"{scheme}://{rest}"
            except:
                pass
        self.pg_pool = None

    async def init_db(self):
        if self.is_pg:
            if not self.pg_pool:
                self.pg_pool = await asyncpg.create_pool(self.db_path_or_url, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS fsm_storage (
                        bot_id BIGINT,
                        chat_id BIGINT,
                        user_id BIGINT,
                        destiny TEXT,
                        state TEXT,
                        data TEXT,
                        PRIMARY KEY (bot_id, chat_id, user_id, destiny)
                    )
                """)
        else:
            async with aiosqlite.connect(self.db_path_or_url) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS fsm_storage (
                        bot_id INTEGER,
                        chat_id INTEGER,
                        user_id INTEGER,
                        destiny TEXT,
                        state TEXT,
                        data TEXT,
                        PRIMARY KEY (bot_id, chat_id, user_id, destiny)
                    )
                """)
                await db.commit()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if hasattr(state, "state") else state
        if self.is_pg:
            if not self.pg_pool:
                self.pg_pool = await asyncpg.create_pool(self.db_path_or_url, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO fsm_storage (bot_id, chat_id, user_id, destiny, state, data)
                    VALUES ($1, $2, $3, $4, $5, '{}')
                    ON CONFLICT(bot_id, chat_id, user_id, destiny) 
                    DO UPDATE SET state = EXCLUDED.state
                """, key.bot_id, key.chat_id, key.user_id, key.destiny, state_str)
        else:
            async with aiosqlite.connect(self.db_path_or_url) as db:
                await db.execute("""
                    INSERT INTO fsm_storage (bot_id, chat_id, user_id, destiny, state, data)
                    VALUES (?, ?, ?, ?, ?, '{}')
                    ON CONFLICT(bot_id, chat_id, user_id, destiny) 
                    DO UPDATE SET state = excluded.state
                """, (key.bot_id, key.chat_id, key.user_id, key.destiny, state_str))
                await db.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        if self.is_pg:
            if not self.pg_pool:
                self.pg_pool = await asyncpg.create_pool(self.db_path_or_url, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                val = await conn.fetchval("""
                    SELECT state FROM fsm_storage
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3 AND destiny = $4
                """, key.bot_id, key.chat_id, key.user_id, key.destiny)
                return val
        else:
            async with aiosqlite.connect(self.db_path_or_url) as db:
                async with db.execute("""
                    SELECT state FROM fsm_storage
                    WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND destiny = ?
                """, (key.bot_id, key.chat_id, key.user_id, key.destiny)) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        data_str = json.dumps(data, ensure_ascii=False)
        if self.is_pg:
            if not self.pg_pool:
                self.pg_pool = await asyncpg.create_pool(self.db_path_or_url, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO fsm_storage (bot_id, chat_id, user_id, destiny, state, data)
                    VALUES ($1, $2, $3, $4, NULL, $5)
                    ON CONFLICT(bot_id, chat_id, user_id, destiny) 
                    DO UPDATE SET data = EXCLUDED.data
                """, key.bot_id, key.chat_id, key.user_id, key.destiny, data_str)
        else:
            async with aiosqlite.connect(self.db_path_or_url) as db:
                await db.execute("""
                    INSERT INTO fsm_storage (bot_id, chat_id, user_id, destiny, state, data)
                    VALUES (?, ?, ?, ?, NULL, ?)
                    ON CONFLICT(bot_id, chat_id, user_id, destiny) 
                    DO UPDATE SET data = excluded.data
                """, (key.bot_id, key.chat_id, key.user_id, key.destiny, data_str))
                await db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        if self.is_pg:
            if not self.pg_pool:
                self.pg_pool = await asyncpg.create_pool(self.db_path_or_url, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                val = await conn.fetchval("""
                    SELECT data FROM fsm_storage
                    WHERE bot_id = $1 AND chat_id = $2 AND user_id = $3 AND destiny = $4
                """, key.bot_id, key.chat_id, key.user_id, key.destiny)
                if val:
                    try:
                        return json.loads(val)
                    except json.JSONDecodeError:
                        return {}
                return {}
        else:
            async with aiosqlite.connect(self.db_path_or_url) as db:
                async with db.execute("""
                    SELECT data FROM fsm_storage
                    WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND destiny = ?
                """, (key.bot_id, key.chat_id, key.user_id, key.destiny)) as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        try:
                            return json.loads(row[0])
                        except json.JSONDecodeError:
                            return {}
                    return {}

    async def close(self) -> None:
        if self.pg_pool:
            await self.pg_pool.close()
            self.pg_pool = None

# Экспортируем как SQLiteStorage для обратной совместимости в main.py
SQLiteStorage = PersistentSQLStorage
