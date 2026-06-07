import asyncio
from aiogram import Bot
from database.db_helper import db_helper
from database.models import User
from sqlalchemy import select

async def main():
    print("=== Диагностика отправки сообщения через Business API ===")
    
    # Получаем пользователя из БД
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == 5037862619))
        user = result.scalar_one_or_none()
        
        if not user:
            print("Ошибка: Пользователь не найден в базе данных!")
            return
            
        print(f"Пользователь: {user.username} (ID: {user.id})")
        print(f"ID напарника: {user.partner_username}")
        print(f"ID бизнес-подключения: {user.business_connection_id}")
        
        if not user.business_connection_id:
            print("Ошибка: Бизнес-подключение пустое (None)!")
            return
            
        conn_id = user.business_connection_id
        partner = "@mishanya404"
        
    from config.config import settings
    bot = Bot(token=settings.bot_token)
    
    print("Пробуем отправить сообщение...")
    try:
        await bot.send_message(
            chat_id=partner,
            text="Тестовое сообщение от бота поддержки.",
            business_connection_id=conn_id
        )
        print("✅ УСПЕХ! Сообщение отправлено успешно.")
    except Exception as e:
        print("\n❌ ПРОИЗОШЛА ОШИБКА ПРИ ОТПРАВКЕ:")
        print(f"Тип ошибки: {type(e).__name__}")
        print(f"Описание: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
