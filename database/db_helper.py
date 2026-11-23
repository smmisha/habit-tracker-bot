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
            
        # Добавляем недостающие колонки динамически, если их нет в БД
        try:
            from sqlalchemy import text
            async with self.session_factory() as session:
                bind = self.engine
                if "sqlite" in str(bind.url):
                    res = await session.execute(text("PRAGMA table_info(users)"))
                    user_cols = {row[1] for row in res.fetchall()}
                    if "last_verse_message_id" not in user_cols:
                        await session.execute(text("ALTER TABLE users ADD COLUMN last_verse_message_id INTEGER"))
                    if "last_checkin_message_id" not in user_cols:
                        await session.execute(text("ALTER TABLE users ADD COLUMN last_checkin_message_id INTEGER"))
                    if "consecutive_missed_checkins" not in user_cols:
                        await session.execute(text("ALTER TABLE users ADD COLUMN consecutive_missed_checkins INTEGER DEFAULT 0"))

                    res_ch = await session.execute(text("PRAGMA table_info(checkin_logs)"))
                    ch_cols = {row[1] for row in res_ch.fetchall()}
                    if "message_id" not in ch_cols:
                        await session.execute(text("ALTER TABLE checkin_logs ADD COLUMN message_id INTEGER"))
                    await session.commit()
                else:
                    await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_verse_message_id BIGINT"))
                    await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_checkin_message_id BIGINT"))
                    await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS consecutive_missed_checkins INTEGER DEFAULT 0"))
                    await session.execute(text("ALTER TABLE checkin_logs ADD COLUMN IF NOT EXISTS message_id BIGINT"))
                    await session.commit()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to add dynamic columns: {e}")

    async def apply_nov_2026_fresh_start_reset(self, target_user_id: int = 5037862619) -> bool:
        """
        Одноразовый и идемпотентный сброс истории для начала с чистого листа:
        последний срыв фиксируется в четверг 19.11.2026, предыдущий бэкграунд стирается,
        пользовательские настройки (напарник, таймзона, время отчета) сохраняются.
        """
        from datetime import datetime, date
        from sqlalchemy import delete
        from database.models import User, RelapseLog, SlipEvent, CheckInLog, JournalEntry, SystemMigration
        import logging
        logger = logging.getLogger(__name__)

        migration_id = "reset_2026_11_19_fresh_start"
        async with self.session_factory() as session:
            existing = await session.get(SystemMigration, migration_id)
            if existing:
                return False

            session.add(SystemMigration(id=migration_id))

            user = await session.get(User, target_user_id)
            if user:
                await session.execute(delete(RelapseLog).where(RelapseLog.user_id == target_user_id))
                await session.execute(delete(SlipEvent).where(SlipEvent.user_id == target_user_id))
                await session.execute(delete(CheckInLog).where(CheckInLog.user_id == target_user_id))
                await session.execute(delete(JournalEntry).where(JournalEntry.user_id == target_user_id))

                relapse_dt = datetime(2026, 11, 19, 20, 0, 0)
                user.streak_start = relapse_dt
                user.total_relapses = 1
                user.forgot_count = 0
                user.consecutive_missed_checkins = 0
                user.last_checkin_message_id = None
                user.awarded_milestones = "1,3"
                user.is_active = True
                user.activity_start = None
                user.activity_last = None

                session.add(RelapseLog(
                    user_id=target_user_id,
                    timestamp=relapse_dt,
                    trigger_reason="Срыв (четверг, 19.11.2026)"
                ))
                session.add(SlipEvent(
                    user_id=target_user_id,
                    occurred_at=datetime(2026, 11, 19, 18, 0, 0),
                    notified_partner=True
                ))
                session.add(CheckInLog(
                    user_id=target_user_id,
                    checkin_date=date(2026, 11, 19),
                    status="relapsed",
                    timestamp=relapse_dt
                ))
                for day_num in (20, 21, 22):
                    session.add(CheckInLog(
                        user_id=target_user_id,
                        checkin_date=date(2026, 11, day_num),
                        status="clean",
                        timestamp=datetime(2026, 11, day_num, 21, 0, 0)
                    ))
                logger.info(f"Выполнен полный сброс истории и старт с 19.11.2026 для пользователя {target_user_id}")

            await session.commit()
            return True
            
    async def dispose(self):
        """Закрытие соединений"""
        await self.engine.dispose()

# Глобальный объект хелпера базы данных
db_helper = DatabaseHelper(settings.database_url)
