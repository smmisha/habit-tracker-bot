import json
import sqlite3
import aiosqlite
import asyncpg
from typing import Optional
import urllib.parse
from config import DB_PATH, DATABASE_URL as RAW_DATABASE_URL

def clean_db_url(url: str) -> str:
    if not url:
        return url
    if not url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://")):
        return url
    try:
        scheme_split = url.split("://", 1)
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
        return f"{scheme}://{rest}"
    except:
        return url

DATABASE_URL = clean_db_url(RAW_DATABASE_URL)

# Глобальный пул соединений для PostgreSQL
pg_pool = None

def is_postgres() -> bool:
    return bool(DATABASE_URL)

async def init_db():
    if is_postgres():
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        async with pg_pool.acquire() as conn:
            # Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    timezone TEXT,
                    mascot_health INTEGER DEFAULT 100,
                    mascot_xp INTEGER DEFAULT 0,
                    mascot_level INTEGER DEFAULT 1,
                    buddies_enabled INTEGER DEFAULT 1
                )
            """)
            # Таблица лекарств
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS medications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    name TEXT NOT NULL,
                    active_ingredient TEXT,
                    dosage TEXT,
                    food_relation TEXT,
                    stock_count INTEGER DEFAULT 0,
                    stock_alert_threshold INTEGER DEFAULT 5,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            # Таблица напоминаний (время и расписание)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    medication_id INTEGER,
                    time_str TEXT NOT NULL,
                    schedule_type TEXT DEFAULT 'daily',
                    schedule_data TEXT,
                    FOREIGN KEY (medication_id) REFERENCES medications (id) ON DELETE CASCADE
                )
            """)
            # Таблица истории приемов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    medication_id INTEGER,
                    reminder_time TEXT,
                    action_time TEXT,
                    status TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (medication_id) REFERENCES medications (id) ON DELETE CASCADE
                )
            """)
            # Таблица опекунов (Бадди)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS buddies (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    buddy_tg_id BIGINT,
                    buddy_username TEXT,
                    buddy_name TEXT,
                    is_confirmed INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    UNIQUE (user_id, buddy_tg_id)
                )
            """)
            # Таблица быстрого словаря названий лекарств
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS medication_dict (
                    name TEXT PRIMARY KEY
                )
            """)
            # Таблица кэша медицинских рекомендаций
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS medication_rec (
                    name TEXT PRIMARY KEY,
                    recommendations TEXT
                )
            """)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            # Таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    timezone TEXT,
                    mascot_health INTEGER DEFAULT 100,
                    mascot_xp INTEGER DEFAULT 0,
                    mascot_level INTEGER DEFAULT 1,
                    buddies_enabled INTEGER DEFAULT 1
                )
            """)
            # Таблица лекарств
            await db.execute("""
                CREATE TABLE IF NOT EXISTS medications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT NOT NULL,
                    active_ingredient TEXT,
                    dosage TEXT,
                    food_relation TEXT,
                    stock_count INTEGER DEFAULT 0,
                    stock_alert_threshold INTEGER DEFAULT 5,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            # Таблица напоминаний (время и расписание)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    medication_id INTEGER,
                    time_str TEXT NOT NULL,
                    schedule_type TEXT DEFAULT 'daily',
                    schedule_data TEXT,
                    FOREIGN KEY (medication_id) REFERENCES medications (id) ON DELETE CASCADE
                )
            """)
            # Таблица истории приемов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    medication_id INTEGER,
                    reminder_time TEXT,
                    action_time TEXT,
                    status TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (medication_id) REFERENCES medications (id) ON DELETE CASCADE
                )
            """)
            # Таблица опекунов (Бадди)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS buddies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    buddy_tg_id INTEGER,
                    buddy_username TEXT,
                    buddy_name TEXT,
                    is_confirmed INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            # Таблица быстрого словаря названий лекарств
            await db.execute("""
                CREATE TABLE IF NOT EXISTS medication_dict (
                    name TEXT PRIMARY KEY
                )
            """)
            # Таблица кэша медицинских рекомендаций
            await db.execute("""
                CREATE TABLE IF NOT EXISTS medication_rec (
                    name TEXT PRIMARY KEY,
                    recommendations TEXT
                )
            """)
            await db.commit()

async def close_db():
    global pg_pool
    if pg_pool:
        await pg_pool.close()
        pg_pool = None

# --- Вспомогательные методы выполнения запросов ---

async def execute(query_sqlite: str, query_pg: str, params: tuple = ()):
    processed_params = [json.dumps(p) if isinstance(p, (dict, list)) else p for p in params]
    if is_postgres():
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        async with pg_pool.acquire() as conn:
            return await conn.execute(query_pg, *processed_params)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query_sqlite, processed_params)
            await db.commit()
            return cursor.lastrowid

async def execute_insert(query_sqlite: str, query_pg: str, params: tuple = ()):
    processed_params = [json.dumps(p) if isinstance(p, (dict, list)) else p for p in params]
    if is_postgres():
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        actual_pg_query = query_pg
        if "returning" not in query_pg.lower():
            actual_pg_query += " RETURNING id"
        async with pg_pool.acquire() as conn:
            val = await conn.fetchval(actual_pg_query, *processed_params)
            return val
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query_sqlite, processed_params)
            await db.commit()
            return cursor.lastrowid

async def fetch_one(query_sqlite: str, query_pg: str, params: tuple = ()):
    processed_params = [json.dumps(p) if isinstance(p, (dict, list)) else p for p in params]
    if is_postgres():
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(query_pg, *processed_params)
            return dict(row) if row else None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query_sqlite, processed_params) as cursor:
                row = await cursor.fetchone()
                return row

async def fetch_all(query_sqlite: str, query_pg: str, params: tuple = ()):
    processed_params = [json.dumps(p) if isinstance(p, (dict, list)) else p for p in params]
    if is_postgres():
        global pg_pool
        if not pg_pool:
            pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(query_pg, *processed_params)
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query_sqlite, processed_params) as cursor:
                rows = await cursor.fetchall()
                return rows


# --- Пользователи ---

async def get_user(user_id: int):
    return await fetch_one(
        "SELECT * FROM users WHERE id = ?",
        "SELECT * FROM users WHERE id = $1",
        (user_id,)
    )

async def add_user(user_id: int, username: str, first_name: str):
    await execute(
        "INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?, ?, ?)",
        "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
        (user_id, username, first_name)
    )

async def update_user_timezone(user_id: int, timezone: str):
    await execute(
        "UPDATE users SET timezone = ? WHERE id = ?",
        "UPDATE users SET timezone = $1 WHERE id = $2",
        (timezone, user_id)
    )

async def update_user_tamagotchi(user_id: int, health_delta: int, xp_delta: int):
    user = await get_user(user_id)
    if not user:
        return None
    
    new_health = max(0, min(100, user['mascot_health'] + health_delta))
    new_xp = user['mascot_xp'] + xp_delta
    new_level = user['mascot_level']
    
    level_up = False
    while new_xp >= 100:
        new_xp -= 100
        new_level += 1
        new_health = 100
        level_up = True
        
    await execute(
        "UPDATE users SET mascot_health = ?, mascot_xp = ?, mascot_level = ? WHERE id = ?",
        "UPDATE users SET mascot_health = $1, mascot_xp = $2, mascot_level = $3 WHERE id = $4",
        (new_health, new_xp, new_level, user_id)
    )
    return {"health": new_health, "xp": new_xp, "level": new_level, "level_up": level_up}


# --- Лекарства ---

async def add_medication(user_id: int, name: str, active_ingredient: str, dosage: str, food_relation: str, stock_count: int, stock_alert_threshold: int, image_path: str = None) -> int:
    return await execute_insert(
        """INSERT INTO medications (user_id, name, active_ingredient, dosage, food_relation, stock_count, stock_alert_threshold, image_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        """INSERT INTO medications (user_id, name, active_ingredient, dosage, food_relation, stock_count, stock_alert_threshold, image_path)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
        (user_id, name, active_ingredient, dosage, food_relation, stock_count, stock_alert_threshold, image_path)
    )

async def get_medication(med_id: int):
    return await fetch_one(
        "SELECT * FROM medications WHERE id = ?",
        "SELECT * FROM medications WHERE id = $1",
        (med_id,)
    )

async def get_user_medications(user_id: int):
    return await fetch_all(
        "SELECT * FROM medications WHERE user_id = ? AND is_active = 1",
        "SELECT * FROM medications WHERE user_id = $1 AND is_active = 1",
        (user_id,)
    )

async def delete_medication(med_id: int):
    await execute(
        "UPDATE medications SET is_active = 0 WHERE id = ?",
        "UPDATE medications SET is_active = 0 WHERE id = $1",
        (med_id,)
    )

async def update_medication_stock(med_id: int, delta: int):
    await execute(
        "UPDATE medications SET stock_count = MAX(0, stock_count + ?) WHERE id = ?",
        "UPDATE medications SET stock_count = GREATEST(0, stock_count + $1) WHERE id = $2",
        (delta, med_id)
    )


# --- Напоминания ---

async def add_reminder(medication_id: int, time_str: str, schedule_type: str = 'daily', schedule_data: list = None):
    # schedule_data в хелперах сериализуется автоматически, если это list/dict
    await execute(
        "INSERT INTO reminders (medication_id, time_str, schedule_type, schedule_data) VALUES (?, ?, ?, ?)",
        "INSERT INTO reminders (medication_id, time_str, schedule_type, schedule_data) VALUES ($1, $2, $3, $4)",
        (medication_id, time_str, schedule_type, schedule_data)
    )

async def get_medication_reminders(medication_id: int):
    rows = await fetch_all(
        "SELECT * FROM reminders WHERE medication_id = ?",
        "SELECT * FROM reminders WHERE medication_id = $1",
        (medication_id,)
    )
    # В PostgreSQL json/jsonb/text поле может возвращаться как готовый list/dict или как строка, в зависимости от драйвера/типа
    # Чтобы быть уверенными, декодируем строку, если schedule_data пришел строкой
    processed_rows = []
    for r in rows:
        row_dict = dict(r)
        if isinstance(row_dict.get('schedule_data'), str):
            try:
                row_dict['schedule_data'] = json.loads(row_dict['schedule_data'])
            except:
                pass
        processed_rows.append(row_dict)
    return processed_rows

async def get_all_reminders_for_scheduler():
    query = """
        SELECT 
            r.id as reminder_id, r.time_str, r.schedule_type, r.schedule_data,
            m.id as medication_id, m.name as med_name, m.active_ingredient, m.dosage, m.food_relation, m.stock_count, m.stock_alert_threshold, m.image_path,
            u.id as user_id, u.timezone, u.mascot_health, u.mascot_level, u.buddies_enabled
        FROM reminders r
        JOIN medications m ON r.medication_id = m.id
        JOIN users u ON m.user_id = u.id
        WHERE m.is_active = 1
    """
    rows = await fetch_all(query, query)
    processed_rows = []
    for r in rows:
        row_dict = dict(r)
        if isinstance(row_dict.get('schedule_data'), str):
            try:
                row_dict['schedule_data'] = json.loads(row_dict['schedule_data'])
            except:
                pass
        processed_rows.append(row_dict)
    return processed_rows


# --- История приемов ---

async def log_history(user_id: int, medication_id: int, reminder_time: str, status: str, action_time: str):
    await execute(
        "INSERT INTO history (user_id, medication_id, reminder_time, status, action_time) VALUES (?, ?, ?, ?, ?)",
        "INSERT INTO history (user_id, medication_id, reminder_time, status, action_time) VALUES ($1, $2, $3, $4, $5)",
        (user_id, medication_id, reminder_time, status, action_time)
    )

async def get_history_status(medication_id: int, reminder_time: str):
    row = await fetch_one(
        "SELECT status FROM history WHERE medication_id = ? AND reminder_time = ?",
        "SELECT status FROM history WHERE medication_id = $1 AND reminder_time = $2",
        (medication_id, reminder_time)
    )
    return row['status'] if row else None

async def update_history_status(medication_id: int, reminder_time: str, status: str, action_time: str):
    await execute(
        "UPDATE history SET status = ?, action_time = ? WHERE medication_id = ? AND reminder_time = ?",
        "UPDATE history SET status = $1, action_time = $2 WHERE medication_id = $3 AND reminder_time = $4",
        (status, action_time, medication_id, reminder_time)
    )



# --- Опекуны (Бадди) ---

async def add_buddy(user_id: int, buddy_tg_id: int, buddy_username: str, buddy_name: str):
    # Сначала проверяем существование
    existing = await fetch_one(
        "SELECT id FROM buddies WHERE user_id = ? AND buddy_tg_id = ?",
        "SELECT id FROM buddies WHERE user_id = $1 AND buddy_tg_id = $2",
        (user_id, buddy_tg_id)
    )
    if existing:
        return
        
    await execute(
        "INSERT INTO buddies (user_id, buddy_tg_id, buddy_username, buddy_name, is_confirmed) VALUES (?, ?, ?, ?, 1)",
        "INSERT INTO buddies (user_id, buddy_tg_id, buddy_username, buddy_name, is_confirmed) VALUES ($1, $2, $3, $4, 1)",
        (user_id, buddy_tg_id, buddy_username, buddy_name)
    )

async def get_user_buddies(user_id: int):
    return await fetch_all(
        "SELECT * FROM buddies WHERE user_id = ? AND is_confirmed = 1",
        "SELECT * FROM buddies WHERE user_id = $1 AND is_confirmed = 1",
        (user_id,)
    )

async def delete_buddy(user_id: int, buddy_tg_id: int):
    await execute(
        "DELETE FROM buddies WHERE user_id = ? AND buddy_tg_id = ?",
        "DELETE FROM buddies WHERE user_id = $1 AND buddy_tg_id = $2",
        (user_id, buddy_tg_id)
    )

async def toggle_buddies_enabled(user_id: int) -> int:
    row = await fetch_one(
        "SELECT buddies_enabled FROM users WHERE id = ?",
        "SELECT buddies_enabled FROM users WHERE id = $1",
        (user_id,)
    )
    if not row:
        return 1
    new_status = 0 if row['buddies_enabled'] == 1 else 1
    
    await execute(
        "UPDATE users SET buddies_enabled = ? WHERE id = ?",
        "UPDATE users SET buddies_enabled = $1 WHERE id = $2",
        (new_status, user_id)
    )
    return new_status


# --- Кэш названий и рекомендаций для ИИ ---

async def check_medication_dict(name: str) -> bool:
    row = await fetch_one(
        "SELECT name FROM medication_dict WHERE name = ?",
        "SELECT name FROM medication_dict WHERE name = $1",
        (name,)
    )
    return row is not None

async def add_medication_dict(name: str):
    await execute(
        "INSERT OR IGNORE INTO medication_dict (name) VALUES (?)",
        "INSERT INTO medication_dict (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
        (name,)
    )

async def get_medication_rec(name: str) -> Optional[str]:
    row = await fetch_one(
        "SELECT recommendations FROM medication_rec WHERE name = ?",
        "SELECT recommendations FROM medication_rec WHERE name = $1",
        (name,)
    )
    return row['recommendations'] if row else None

async def add_medication_rec(name: str, recommendations: str):
    await execute(
        "INSERT OR REPLACE INTO medication_rec (name, recommendations) VALUES (?, ?)",
        "INSERT INTO medication_rec (name, recommendations) VALUES ($1, $2) ON CONFLICT (name) DO UPDATE SET recommendations = EXCLUDED.recommendations",
        (name, recommendations)
    )
