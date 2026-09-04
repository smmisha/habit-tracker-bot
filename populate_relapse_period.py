import asyncio
import os
import sys
from datetime import datetime, date, timedelta, time
from sqlalchemy import select, and_, delete
from database.db_helper import DatabaseHelper
from database.models import User, RelapseLog, CheckInLog, SlipEvent

USER_ID = 5037862619

RELAPSE_START = date(2026, 8, 16)
RELAPSE_END = date(2026, 8, 27)

CLEAN_START = date(2026, 8, 28)
CLEAN_END = date(2026, 9, 3)

TODAY = date(2026, 9, 4)

async def populate(db_url: str):
    print(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else db_url}...")
    db = DatabaseHelper(db_url)
    await db.init_db()

    async with db.session_factory() as session:
        # 1. Поиск пользователя
        result = await session.execute(select(User).where(User.id == USER_ID))
        user = result.scalar_one_or_none()

        if not user:
            print(f"[ERROR] User {USER_ID} not found in database!")
            await db.dispose()
            return False

        print(f"Found user: {user.first_name} (@{user.username})")

        # 2. Удаляем старые логи за этот период (16 августа - 4 сентября) во избежание дубликатов
        await session.execute(
            delete(RelapseLog).where(
                and_(
                    RelapseLog.user_id == USER_ID,
                    RelapseLog.timestamp >= datetime.combine(RELAPSE_START, time.min),
                    RelapseLog.timestamp <= datetime.combine(TODAY, time.max)
                )
            )
        )
        await session.execute(
            delete(SlipEvent).where(
                and_(
                    SlipEvent.user_id == USER_ID,
                    SlipEvent.occurred_at >= datetime.combine(RELAPSE_START, time.min),
                    SlipEvent.occurred_at <= datetime.combine(TODAY, time.max)
                )
            )
        )
        await session.execute(
            delete(CheckInLog).where(
                and_(
                    CheckInLog.user_id == USER_ID,
                    CheckInLog.checkin_date >= RELAPSE_START,
                    CheckInLog.checkin_date <= TODAY
                )
            )
        )

        # 3. Добавляем срывы с 16 по 27 августа (12 дней)
        relapse_days_count = (RELAPSE_END - RELAPSE_START).days + 1
        for i in range(relapse_days_count):
            day_date = RELAPSE_START + timedelta(days=i)
            day_dt = datetime.combine(day_date, time(20, 0, 0))

            # Лог срыва
            session.add(RelapseLog(
                user_id=USER_ID,
                timestamp=day_dt,
                trigger_reason=f"Срыв ({day_date.strftime('%d.%m.%Y')})"
            ))

            # Событие срыва
            session.add(SlipEvent(
                user_id=USER_ID,
                occurred_at=day_dt,
                notified_partner=True
            ))

            # Чек-ин со статусом relapsed
            session.add(CheckInLog(
                user_id=USER_ID,
                checkin_date=day_date,
                status="relapsed",
                timestamp=datetime.combine(day_date, time(21, 0, 0))
            ))

        print(f"[OK] Added {relapse_days_count} relapse days from {RELAPSE_START} to {RELAPSE_END}.")

        # 4. Добавляем чистые дни с 28 августа по 3 сентября (7 дней)
        clean_days_count = (CLEAN_END - CLEAN_START).days + 1
        for i in range(clean_days_count):
            day_date = CLEAN_START + timedelta(days=i)
            session.add(CheckInLog(
                user_id=USER_ID,
                checkin_date=day_date,
                status="clean",
                timestamp=datetime.combine(day_date, time(21, 0, 0))
            ))

        print(f"[OK] Added {clean_days_count} clean days from {CLEAN_START} to {CLEAN_END}.")

        # 5. Добавляем сегодняшний чек-ин (4 сентября) в статусе pending
        session.add(CheckInLog(
            user_id=USER_ID,
            checkin_date=TODAY,
            status="pending"
        ))

        # 6. Обновляем поля пользователя
        # Стрик начинается после последнего срыва 27 августа
        user.streak_start = datetime.combine(RELAPSE_END, time(0, 0, 0))
        
        # Считаем общее количество записей в relapse_logs
        await session.flush()
        count_res = await session.execute(
            select(RelapseLog).where(RelapseLog.user_id == USER_ID)
        )
        total_logs = len(count_res.scalars().all())
        user.total_relapses = total_logs
        user.awarded_milestones = "1,3,7"  # Достигнутые награды за 8 дней чистоты

        await session.commit()
        print(f"[OK] User profile updated successfully:")
        print(f"   - streak_start: {user.streak_start}")
        print(f"   - total_relapses: {user.total_relapses}")
        print(f"   - awarded_milestones: {user.awarded_milestones}")

    await db.dispose()
    return True

async def main():
    db_url = sys.argv[1] if len(sys.argv) > 1 else (os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///bot.db")
    await populate(db_url)

if __name__ == "__main__":
    asyncio.run(main())
