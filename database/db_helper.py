from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.config import settings
from database.models import Base

class DatabaseHelper:
    def __init__(self, url: str, echo: bool = False):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            
        # Настройка асинхронного движка. Для SQLite отключаем пул потоков для безопасности
        connect_args = {}
        engine_kwargs = {
            "echo": echo,
        }
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        elif "postgresql" in url:
            connect_args = {
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            }
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_recycle"] = 180
            
        self.engine = create_async_engine(
            url,
            connect_args=connect_args,
            **engine_kwargs
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
            
        # Добавляем колонку last_verse_message_id, если её нет в БД
        try:
            from sqlalchemy import text
            async with self.session_factory() as session:
                bind = self.engine
                if "sqlite" in str(bind.url):
                    # Для SQLite
                    res = await session.execute(text("PRAGMA table_info(users)"))
                    columns = [row[1] for row in res.fetchall()]
                    if "last_verse_message_id" not in columns:
                        await session.execute(text("ALTER TABLE users ADD COLUMN last_verse_message_id INTEGER"))
                        await session.commit()
                else:
                    # Для PostgreSQL / Neon
                    await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_verse_message_id BIGINT"))
                    await session.commit()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to add last_verse_message_id column dynamically: {e}")
            
    async def dispose(self):
        """Закрытие соединений"""
        await self.engine.dispose()

# Глобальный объект хелпера базы данных
db_helper = DatabaseHelper(settings.database_url)
