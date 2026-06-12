import asyncio
import sys
import os

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.db_helper import db_helper
from database.models import User, CheckInLog, JournalEntry
from services.scheduler import send_weekly_reports
from main import bot

async def main():
    print("=== Ручной запуск недельного отчета ===")
    
    # Инициализируем бота (токен подгружается из .env)
    # Напрямую вызовем функцию отправки отчетов
    try:
        await send_weekly_reports()
        print("Метод send_weekly_reports() успешно выполнен!")
    except Exception as e:
        print(f"Ошибка при выполнении: {e}")
        
    await db_helper.dispose()

if __name__ == "__main__":
    asyncio.run(main())
