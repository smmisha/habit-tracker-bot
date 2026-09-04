import asyncio
import os
import sys
from datetime import datetime, timezone
from sqlalchemy import select
from database.db_helper import DatabaseHelper
from database.models import User, RelapseLog, SlipEvent

USER_ID = 5037862619
RELAPSE_DATETIME_STR = "2026-08-27 00:00:00"
RELAPSE_DT = datetime.strptime(RELAPSE_DATETIME_STR, "%Y-%m-%d %H:%M:%S")

async def update_relapse(db_url: str):
    print(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else db_url}...")
    db = DatabaseHelper(db_url)
    await db.init_db()
    
    async with db.session_factory() as session:
        result = await session.execute(select(User).where(User.id == USER_ID))
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"[ERROR] User with ID {USER_ID} not found in database!")
            await db.dispose()
            return False
            
        print(f"Found user: {user.first_name} (@{user.username}), current streak_start: {user.streak_start}, total_relapses: {user.total_relapses}")
        
        # Обновляем поля пользователя
        user.streak_start = RELAPSE_DT
        user.total_relapses += 1
        user.awarded_milestones = "1,3,7"  # Достигнутые вехи (1, 3, 7 дней) для 8-дневного стрика
        
        # Добавляем запись в relapse_logs
        log = RelapseLog(
            user_id=USER_ID,
            timestamp=RELAPSE_DT,
            trigger_reason="Зафиксирован срыв от 27 августа 2026"
        )
        session.add(log)
        
        # Добавляем запись в slip_events
        slip = SlipEvent(
            user_id=USER_ID,
            occurred_at=RELAPSE_DT,
            notified_partner=False
        )
        session.add(slip)
        
        await session.commit()
        print(f"[OK] Successfully updated user {USER_ID}:")
        print(f"   - streak_start: {user.streak_start}")
        print(f"   - total_relapses: {user.total_relapses}")
        print(f"   - awarded_milestones: {user.awarded_milestones}")
        print(f"   - Added RelapseLog and SlipEvent for {RELAPSE_DATETIME_STR}")
        
    await db.dispose()
    return True

async def main():
    db_url = sys.argv[1] if len(sys.argv) > 1 else (os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///bot.db")
    await update_relapse(db_url)

if __name__ == "__main__":
    asyncio.run(main())
