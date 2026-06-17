import asyncio
import logging
from aiogram import Bot, Dispatcher
from utils.fsm_storage import SQLiteStorage
from config import DB_PATH, DATABASE_URL

import database
import scheduler
from config import BOT_TOKEN
from handlers import start, medications, buddy

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Инициализация базы данных...")
    await database.init_db()
    
    # Инициализация хранилища FSM
    storage = SQLiteStorage(DATABASE_URL if DATABASE_URL else DB_PATH)
    await storage.init_db()
    
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=storage)
    
    # Регистрация Whitelist Middleware
    from aiogram import BaseMiddleware
    from aiogram.types import Message, CallbackQuery
    from config import ALLOWED_USERS

    class WhitelistMiddleware(BaseMiddleware):
        def __init__(self, allowed_users: list):
            self.allowed_users = allowed_users
            super().__init__()

        async def __call__(self, handler, event, data):
            user = getattr(event, "from_user", None)
            if not user:
                return await handler(event, data)
                
            if not self.allowed_users:
                return await handler(event, data)
                
            user_id = user.id
            username = (user.username or "").lower()
            
            # Разрешено, если в белом списке
            if user_id in self.allowed_users or username in self.allowed_users:
                return await handler(event, data)
                
            # Разрешено, если уже зарегистрирован
            is_registered = await database.get_user(user_id)
            if is_registered:
                return await handler(event, data)
                
            # Разрешено, если пришел по реферальной ссылке бадди
            if isinstance(event, Message) and event.text and event.text.startswith("/start buddy_"):
                return await handler(event, data)
                
            # Разрешено подтвердить/отклонить запрос бадди
            if isinstance(event, CallbackQuery) and event.data and (event.data.startswith("accept_buddy:") or event.data.startswith("reject_buddy:")):
                return await handler(event, data)
                
            # Блокируем всех остальных
            if isinstance(event, Message):
                await event.answer(
                    "🔒 *Мистер Таблетус:* «Извините, сейчас идет закрытое тестирование бота. "
                    "Доступ разрешен только участникам бета-теста!»",
                    parse_mode="Markdown"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("🔒 Доступ только для бета-тестеров!", show_alert=True)
            return

    dp.message.outer_middleware(WhitelistMiddleware(ALLOWED_USERS))
    dp.callback_query.outer_middleware(WhitelistMiddleware(ALLOWED_USERS))

    # Регистрация обработчиков (рутеров)
    dp.include_router(start.router)
    dp.include_router(medications.router)
    dp.include_router(buddy.router)
    # Настройка команд меню бота
    logger.info("Настройка команд меню бота...")
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="🌐 Смена языка / Change language"),
        BotCommand(command="cancel", description="❌ Отменить операцию / Cancel")
    ])

    logger.info("Настройка планировщика напоминаний...")
    await scheduler.setup_scheduler(bot)
    
    # Запуск бота в режиме лонг-поллинга
    logger.info("Запуск лонг-поллинга бота...")
    try:
        # Убираем все входящие сообщения, отправленные пока бот был оффлайн
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка при работе бота: {e}", exc_info=True)
    finally:
        await bot.session.close()
        await database.close_db()
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
