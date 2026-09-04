import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

# Import models
from database.models import Base, User, SlipEvent, RelapseLog

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

class TestRelapseNotification(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(DATABASE_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.session = self.session_factory()
        
        # User with partner
        self.user_id = 12345
        self.user = User(
            id=self.user_id, 
            username="test_user", 
            first_name="Test",
            partner_username="test_partner",
            business_connection_id="conn_123"
        )
        self.session.add(self.user)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_every_relapse_notifies_partner_immediately(self):
        """
        Rule: A notification must be sent to the partner on EVERY relapse.
        No grace periods, no waiting for 3 relapses.
        """
        from handlers.tracker import execute_relapse_reset
        from database.db_helper import db_helper
        
        # Patch db_helper session_factory to use our in-memory DB
        with patch.object(db_helper, "session_factory", self.session_factory), \
             patch("services.userbot_client.userbot.send_message_to_partner", new_callable=AsyncMock) as mock_partner_send, \
             patch("main.bot.send_message", new_callable=AsyncMock):
             
            mock_partner_send.return_value = True
            
            # 1st relapse
            res1 = await execute_relapse_reset(self.user_id, "Trigger 1")
            self.assertTrue(res1["partner_notified"], "Partner must be notified on the first relapse")
            self.assertEqual(mock_partner_send.call_count, 1)
            self.assertIn("отправлено уведомление о срыве", res1["confirm_text"])
            
            # 2nd relapse
            res2 = await execute_relapse_reset(self.user_id, "Trigger 2")
            self.assertTrue(res2["partner_notified"], "Partner must be notified on the second relapse as well")
            self.assertEqual(mock_partner_send.call_count, 2)
            self.assertIn("отправлено уведомление о срыве", res2["confirm_text"])

    async def test_relapse_without_partner_does_not_crash(self):
        """If user has no partner configured, reset succeeds without sending alert"""
        from handlers.tracker import execute_relapse_reset
        from database.db_helper import db_helper
        
        # Remove partner from user
        async with self.session_factory() as session:
            u = await session.get(User, self.user_id)
            u.partner_username = None
            await session.commit()
            
        with patch.object(db_helper, "session_factory", self.session_factory), \
             patch("services.userbot_client.userbot.send_message_to_partner", new_callable=AsyncMock) as mock_partner_send, \
             patch("main.bot.send_message", new_callable=AsyncMock):
             
            res = await execute_relapse_reset(self.user_id, "Trigger")
            self.assertFalse(res["partner_notified"])
            mock_partner_send.assert_not_called()
            self.assertIn("Напарник не указан", res["confirm_text"])

if __name__ == "__main__":
    unittest.main()
