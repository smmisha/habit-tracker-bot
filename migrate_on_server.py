import asyncio
import asyncpg
import os
from sqlalchemy.engine import make_url

async def get_columns(conn, table_name):
    query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = $1
    """
    rows = await conn.fetch(query, table_name)
    return [row['column_name'] for row in rows]

async def migrate_table(src_conn, dest_conn, table_name):
    print(f"\nМиграция таблицы {table_name}...")
    
    src_cols = await get_columns(src_conn, table_name)
    dest_cols = await get_columns(dest_conn, table_name)
    
    if not src_cols:
        print(f"Таблица {table_name} отсутствует в источнике. Пропускаем.")
        return
        
    common_cols = list(set(src_cols).intersection(set(dest_cols)))
    
    cols_str = ", ".join(f'"{c}"' for c in common_cols)
    rows = await src_conn.fetch(f'SELECT {cols_str} FROM "{table_name}"')
    print(f"Найдено строк в источнике: {len(rows)}")
    
    if not rows:
        return

    await dest_conn.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')
    print(f"Таблица {table_name} в приемнике очищена.")

    placeholders = ", ".join(f"${i+1}" for i in range(len(common_cols)))
    insert_query = f'INSERT INTO "{table_name}" ({cols_str}) VALUES ({placeholders})'
    
    success_count = 0
    for row in rows:
        try:
            values = [row[c] for c in common_cols]
            await dest_conn.execute(insert_query, *values)
            success_count += 1
        except Exception as e:
            print(f"Ошибка вставки строки: {e}")
            
    print(f"Успешно перенесено {success_count} из {len(rows)} строк.")

async def connect_to_db(url_str):
    if url_str.startswith("postgresql://"):
        url_str = url_str.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    url_obj = make_url(url_str)
    
    # Try direct connection first
    if url_obj.host and "pooler.supabase.com" in url_obj.host:
        username = url_obj.username
        if username and "." in username:
            project_ref = username.split(".", 1)[1]
            try:
                conn = await asyncpg.connect(
                    user="postgres",
                    password=url_obj.password,
                    database=url_obj.database or "postgres",
                    host=f"db.{project_ref}.supabase.co",
                    port=5432,
                    ssl='require',
                    statement_cache_size=0
                )
                print(f"Подключено напрямую к db.{project_ref}.supabase.co")
                return conn
            except Exception:
                pass
                
    return await asyncpg.connect(
        user=url_obj.username,
        password=url_obj.password,
        database=url_obj.database,
        host=url_obj.host,
        port=url_obj.port or 5432,
        ssl='require',
        statement_cache_size=0
    )

async def main():
    print("=== ЗАПУСК МИГРАЦИИ НА СЕРВЕРЕ ===")
    
    src_url = os.getenv("OLD_DATABASE_URL")
    dest_url = os.getenv("NEW_DATABASE_URL")
    
    if not src_url or not dest_url:
        print("Ошибка: Переменные OLD_DATABASE_URL и NEW_DATABASE_URL должны быть заданы!")
        return
        
    print("Подключение к базам данных...")
    try:
        src_conn = await connect_to_db(src_url)
        print("Успешно подключено к СТАРОЙ базе!")
    except Exception as e:
        print(f"Ошибка подключения к старой базе: {e}")
        return

    try:
        dest_conn = await connect_to_db(dest_url)
        print("Успешно подключено к НОВОЙ базе!")
    except Exception as e:
        print(f"Ошибка подключения к новой базе: {e}")
        await src_conn.close()
        return

    try:
        tables = ["users", "relapse_logs", "checkin_logs", "journal_entries"]
        for table in tables:
            await migrate_table(src_conn, dest_conn, table)
            
        print("\nСинхронизация автоинкрементных последовательностей ID...")
        await dest_conn.execute("SELECT setval(pg_get_serial_sequence('checkin_logs', 'id'), coalesce(max(id), 1)) FROM checkin_logs")
        await dest_conn.execute("SELECT setval(pg_get_serial_sequence('relapse_logs', 'id'), coalesce(max(id), 1)) FROM relapse_logs")
        await dest_conn.execute("SELECT setval(pg_get_serial_sequence('journal_entries', 'id'), coalesce(max(id), 1)) FROM journal_entries")
        
        print("\n🎉 ВСЕ ДАННЫЕ УСПЕШНО ПЕРЕНЕСЕНЫ!")
    finally:
        await src_conn.close()
        await dest_conn.close()
        print("Соединения закрыты.")

if __name__ == "__main__":
    asyncio.run(main())
