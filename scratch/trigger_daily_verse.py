import asyncio
import sys
import os

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.db_helper import db_helper
from services.scheduler import send_daily_bible_verses
from main import bot

async def main():
    print("=== Ручной запуск отправки стиха дня ===")
    try:
        await db_helper.init_db()
        await send_daily_bible_verses()
        print("Метод send_daily_bible_verses() успешно выполнен!")
    except Exception as e:
        print(f"Ошибка при выполнении: {e}")
        
    await db_helper.dispose()

if __name__ == "__main__":
    asyncio.run(main())
