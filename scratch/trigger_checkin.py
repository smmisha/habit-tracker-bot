import asyncio
import sys
import os
from datetime import date

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.db_helper import db_helper
from database.models import User, CheckInLog
from keyboards.inline import get_checkin_keyboard
from main import bot

async def main():
    user_id = 5037862619
    today_date = date(2026, 6, 8)
    
    print(f"=== Принудительный запуск чек-ина для {user_id} ===")
    
    async with db_helper.session_factory() as session:
        # 1. Удаляем существующие логи чек-ина за сегодня
        from sqlalchemy import delete
        await session.execute(
            delete(CheckInLog).where(
                CheckInLog.user_id == user_id,
                CheckInLog.checkin_date == today_date
            )
        )
        await session.commit()
        print("Сегодняшние старые записи чек-ина удалены.")
        
        # 2. Создаем новую запись со статусом "pending"
        new_log = CheckInLog(
            user_id=user_id,
            checkin_date=today_date,
            status="pending"
        )
        session.add(new_log)
        await session.commit()
        print("Создана запись чек-ина со статусом pending.")
        
        # 3. Отправляем сообщение пользователю
        text = (
            "🔔 <b>Время ежедневного отчета!</b>\n\n"
            "Пожалуйста, сделайте отметку о том, как прошел сегодняшний день. "
            "У вас есть 5 минут для своевременной отметки или до 20 часов дополнительного времени."
        )
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_checkin_keyboard()
        )
        print("Чек-ин сообщение отправлено пользователю!")

    await db_helper.dispose()

if __name__ == "__main__":
    asyncio.run(main())
