from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.config import settings
from database.models import Base

class DatabaseHelper:
    def __init__(self, url: str, echo: bool = False):
        # Настройка асинхронного движка. Для SQLite отключаем пул потоков для безопасности
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            
        self.engine = create_async_engine(
            url,
            echo=echo,
            connect_args=connect_args
        )
        
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    async def init_db(self):
        """Создание таблиц, если они не существуют"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
    async def dispose(self):
        """Закрытие соединений"""
        await self.engine.dispose()

# Глобальный объект хелпера базы данных
db_helper = DatabaseHelper(settings.database_url)
