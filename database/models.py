from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import BigInteger, ForeignKey, String, DateTime, Date, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    # Telegram User ID в качестве первичного ключа
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    
    # Настройки часового пояса и отчетов
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Kyiv")
    partner_username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Без символа @
    
    # Метрики и счетчики
    streak_start: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    total_relapses: Mapped[int] = mapped_column(default=0)
    forgot_count: Mapped[int] = mapped_column(default=0)  # Лимит равен 3
    
    # Время ежедневной проверки
    checkin_time: Mapped[str] = mapped_column(String(5), default="21:00")  # Формат HH:MM
    is_active: Mapped[bool] = mapped_column(default=True)
    
    # Отслеживание активности для дедлайнов (30 минут онлайна)
    activity_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    activity_last: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Выданные награды (через запятую, например "1,3,7")
    awarded_milestones: Mapped[str] = mapped_column(String(200), default="")
    
    # Уведомлять ли напарника о достижениях (медалях)
    notify_partner_achievements: Mapped[bool] = mapped_column(default=True)
    
    # ID бизнес-подключения для автоматизации чатов
    business_connection_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # ID последнего отправленного сообщения со стихом дня для последующего удаления
    last_verse_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # ИИ-помощник: учет заданных вопросов
    ai_questions_used_today: Mapped[int] = mapped_column(default=0)
    last_ai_query_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Связи с логами
    relapses: Mapped[List["RelapseLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    checkins: Mapped[List["CheckInLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    journal_entries: Mapped[List["JournalEntry"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RelapseLog(Base):
    __tablename__ = "relapse_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    trigger_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship(back_populates="relapses")


class CheckInLog(Base):
    __tablename__ = "checkin_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    checkin_date: Mapped[date] = mapped_column(Date, default=date.today)
    
    # Статусы: "pending" (ожидает), "clean" (чист), "relapsed" (срыв), "missed" (пропуск)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Причина пропуска, если отметка пройдена в дополнительный период
    excuse_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    user: Mapped["User"] = relationship(back_populates="checkins")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    entry_date: Mapped[date] = mapped_column(Date, default=date.today)
    content: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    user: Mapped["User"] = relationship(back_populates="journal_entries")
