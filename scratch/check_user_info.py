import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from datetime import datetime

DATABASE_URL = "postgresql+asyncpg://neondb_owner:npg_rJON3U8EulmI@ep-crimson-brook-aphhyeeg.c-7.us-east-1.aws.neon.tech/neondb?ssl=require"

async def main():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        print("=== Database Connection Established ===")
        
        # 1. Fetch users
        result = await conn.execute(text("SELECT id, username, first_name, checkin_time, timezone, is_active FROM users;"))
        users = result.fetchall()
        print(f"\nActive users count: {len(users)}")
        for u in users:
            print(f"- ID: {u[0]}, Username: {u[1]}, Name: {u[2]}, Check-in Time: {u[3]}, Timezone: {u[4]}, Active: {u[5]}")
            
        # 2. Fetch recent check-in logs
        result_logs = await conn.execute(text("SELECT id, user_id, checkin_date, status, timestamp, excuse_reason FROM checkin_logs ORDER BY id DESC LIMIT 10;"))
        logs = result_logs.fetchall()
        print("\n=== Recent Check-in Logs ===")
        for l in logs:
            print(f"- ID: {l[0]}, User ID: {l[1]}, Date: {l[2]}, Status: {l[3]}, Timestamp: {l[4]}, Excuse: {l[5]}")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
