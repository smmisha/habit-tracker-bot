import asyncio
import logging
import sys
from config.config import settings
from database.db_helper import db_helper
from database.models import Base

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

async def run_migration():
    logger.info("=== START DATABASE MIGRATION FOR SLIP_EVENTS ===")
    logger.info(f"Target Database URL: {settings.database_url}")
    
    try:
        # init_db will connect to the engine and run Base.metadata.create_all
        # which creates the slip_events table if it does not exist.
        await db_helper.init_db()
        logger.info("Database tables initialized successfully.")
        
        # Double check if table is created (especially if Postgres)
        from sqlalchemy import text
        async with db_helper.session_factory() as session:
            if "sqlite" in settings.database_url:
                res = await session.execute(text("PRAGMA table_info(slip_events)"))
                cols = res.fetchall()
                logger.info(f"Verified slip_events columns in SQLite: {[c[1] for c in cols]}")
            else:
                res = await session.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'slip_events'"
                ))
                cols = res.fetchall()
                logger.info(f"Verified slip_events columns in Postgres: {[c[0] for c in cols]}")
                
        logger.info("=== DATABASE MIGRATION COMPLETED SUCCESSFULLY ===")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise e
    finally:
        await db_helper.dispose()

if __name__ == "__main__":
    asyncio.run(run_migration())
