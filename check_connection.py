import asyncio
from aiogram import Bot
from database.db_helper import db_helper
from database.models import User
from sqlalchemy import select

async def main():
    print("=== Проверка статуса Бизнес-подключения ===")
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == 5037862619))
        user = result.scalar_one_or_none()
        
        if not user:
            print("Пользователь не найден.")
            return
            
        conn_id = user.business_connection_id
        print(f"ID соединения из базы: {conn_id}")
        
        if not conn_id:
            print("Бизнес-соединение отсутствует.")
            return
            
    from config.config import settings
    bot = Bot(token=settings.bot_token)
    
    try:
        connection = await bot.get_business_connection(business_connection_id=conn_id)
        print("\n=== Информация от Telegram API ===")
        print(f"ID: {connection.id}")
        print(f"Пользователь: {connection.user.id}")
        print(f"Активно: {connection.is_enabled}")
        print(f"Бот может отвечать: {connection.can_reply}")
    except Exception as e:
        print(f"\n❌ Ошибка получения статуса подключения: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
