import asyncio
import asyncpg
from sqlalchemy.engine import make_url

async def check_database(url_str, name):
    print(f"\n--- ПРОВЕРКА БАЗЫ ДАННЫХ: {name} ---")
    if url_str.startswith("postgresql://"):
        url_str = url_str.replace("postgresql://", "postgresql+asyncpg://", 1)
        
    try:
        url_obj = make_url(url_str)
    except Exception as e:
        print(f"Ошибка разбора URL: {e}")
        return

    conn = None
    try:
        # Пытаемся сначала напрямую, затем через пулер
        if url_obj.host and "pooler.supabase.com" in url_obj.host:
            project_ref = url_obj.username.split(".", 1)[1] if "." in url_obj.username else None
            if project_ref:
                try:
                    conn = await asyncpg.connect(
                        user="postgres",
                        password=url_obj.password,
                        database=url_obj.database or "postgres",
                        host=f"db.{project_ref}.supabase.co",
                        port=5432,
                        ssl='require',
                        statement_cache_size=0,
                        timeout=5.0
                    )
                except Exception:
                    pass
                    
        if not conn:
            conn = await asyncpg.connect(
                user=url_obj.username,
                password=url_obj.password,
                database=url_obj.database,
                host=url_obj.host,
                port=url_obj.port or 5432,
                ssl='require',
                statement_cache_size=0,
                timeout=10.0
            )
            
        print("Успешно подключено!")
        
        # Проверяем наличие таблиц и считаем строки
        tables = ["users", "relapse_logs", "checkin_logs", "journal_entries"]
        for table in tables:
            try:
                # Проверяем существование таблицы
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1)",
                    table
                )
                if table_exists:
                    count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
                    print(f"  Таблица '{table}': СУЩЕСТВУЕТ, строк: {count}")
                    if table == "users" and count > 0:
                        users_data = await conn.fetch('SELECT id, username, first_name, streak_start FROM users')
                        for u in users_data:
                            print(f"    - Пользователь ID {u['id']}: @{u['username']} ({u['first_name']}), стрик с {u['streak_start']}")
                else:
                    print(f"  Таблица '{table}': ОТСУТСТВУЕТ")
            except Exception as e:
                print(f"  Ошибка при проверке таблицы '{table}': {e}")
                
    except Exception as e:
        print(f"Ошибка подключения к базе: {e}")
    finally:
        if conn:
            await conn.close()

async def main():
    print("=== ИНСПЕКТОР БАЗ ДАННЫХ ===")
    
    old_url = input("\n1. Введите ссылку на СТАРУЮ базу (Mr Tabletus, из Render или ваших настроек): \n").strip().strip("'\"")
    new_url = input("\n2. Введите ссылку на НОВУЮ базу (xhabits, из Render): \n").strip().strip("'\"")
    
    await check_database(old_url, "СТАРАЯ (Mr Tabletus)")
    await check_database(new_url, "НОВАЯ (xhabits)")

if __name__ == "__main__":
    asyncio.run(main())
