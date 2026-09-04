import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_

# Import models
from database.models import Base, User, SlipEvent

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

class TestRollingWindow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create engine and tables
        self.engine = create_async_engine(DATABASE_URL, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.session = self.session_factory()
        
        # Add test user
        self.user_id = 12345
        self.user = User(id=self.user_id, username="test_user", first_name="Test")
        self.session.add(self.user)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def simulate_relapse_and_check(self, current_time_utc: datetime) -> bool:
        """
        Simulates the core business logic of execute_relapse_reset:
        1. Adds a new SlipEvent at current_time_utc.
        2. Counts slip events in the rolling 7-day window.
        3. If count >= 3 and has_unnotified, returns True (partner would be notified)
           and sets notified_partner = True for all slip events in the window.
        """
        # 1. Log the new slip event
        new_slip = SlipEvent(
            user_id=self.user_id,
            occurred_at=current_time_utc,
            notified_partner=False
        )
        self.session.add(new_slip)
        await self.session.commit()
        
        # 2. Query slip events in the last 7 days (rolling)
        seven_days_ago = current_time_utc - timedelta(days=7)
        
        result = await self.session.execute(
            select(SlipEvent)
            .where(
                and_(
                    SlipEvent.user_id == self.user_id,
                    SlipEvent.occurred_at >= seven_days_ago
                )
            )
        )
        recent_slips = result.scalars().all()
        recent_count = len(recent_slips)
        has_unnotified = any(not s.notified_partner for s in recent_slips)
        
        partner_notified = False
        if recent_count >= 3 and has_unnotified:
            partner_notified = True
            for s in recent_slips:
                s.notified_partner = True
            await self.session.commit()
            
        return partner_notified

    async def test_series_within_7_days(self):
        """
        Test Case 1: 3 relapses occur within a rolling 7-day period.
        Expected: The 3rd relapse triggers a partner notification and marks all as notified.
        """
        now = datetime.now(timezone.utc)
        
        # First relapse on Day 1 (6 days ago)
        notified1 = await self.simulate_relapse_and_check(now - timedelta(days=6))
        self.assertFalse(notified1, "First relapse should not notify partner")
        
        # Second relapse on Day 3 (4 days ago)
        notified2 = await self.simulate_relapse_and_check(now - timedelta(days=4))
        self.assertFalse(notified2, "Second relapse should not notify partner")
        
        # Third relapse on Day 6 (now - within 7 days of the first one)
        notified3 = await self.simulate_relapse_and_check(now)
        self.assertTrue(notified3, "Third relapse within 7 days should notify partner")
        
        # Verify that all 3 events are marked as notified_partner = True
        result = await self.session.execute(select(SlipEvent).where(SlipEvent.user_id == self.user_id))
        slips = result.scalars().all()
        self.assertEqual(len(slips), 3)
        self.assertTrue(all(s.notified_partner for s in slips), "All slips in the window should be marked as notified")

    async def test_relapses_spread_out_beyond_7_days(self):
        """
        Test Case 2: Relapses occur but are spread out beyond the rolling 7-day window.
        E.g. Day 1 (8 days ago), Day 2 (7 days and 1 hour ago), Day 9 (now).
        Expected: No notification on Day 9 because older events are outside the 7-day window.
        """
        now = datetime.now(timezone.utc)
        
        # Relapse 1: 8 days ago (outside window)
        notified1 = await self.simulate_relapse_and_check(now - timedelta(days=8))
        self.assertFalse(notified1)
        
        # Relapse 2: 7 days and 1 hour ago (outside window)
        notified2 = await self.simulate_relapse_and_check(now - timedelta(days=7, hours=1))
        self.assertFalse(notified2)
        
        # Relapse 3: now (within window, but count in window is only 1)
        notified3 = await self.simulate_relapse_and_check(now)
        self.assertFalse(notified3, "Should not notify since previous relapses are outside the rolling 7-day window")
        
        # Verify database states
        result = await self.session.execute(select(SlipEvent).where(SlipEvent.user_id == self.user_id))
        slips = result.scalars().all()
        self.assertEqual(len(slips), 3)
        self.assertFalse(any(s.notified_partner for s in slips), "No slips should be marked as notified")

    async def test_relapse_exactly_on_7_day_boundary(self):
        """
        Test Case 3: Verify the boundary case (exactly 7-day difference, i.e. 168 hours).
        Expected: Since the comparison is occurred_at >= seven_days_ago (inclusive),
        a relapse exactly 7 days ago (inclusive) is counted in the window and triggers the notification.
        """
        now = datetime.now(timezone.utc)
        
        # Relapse 1: exactly 7 days ago
        notified1 = await self.simulate_relapse_and_check(now - timedelta(days=7))
        self.assertFalse(notified1)
        
        # Relapse 2: 3 days ago
        notified2 = await self.simulate_relapse_and_check(now - timedelta(days=3))
        self.assertFalse(notified2)
        
        # Relapse 3: now
        notified3 = await self.simulate_relapse_and_check(now)
        self.assertTrue(notified3, "Exactly 7-day difference should be inclusive and trigger notification")
        
        # Verify that all 3 are marked as notified
        result = await self.session.execute(select(SlipEvent).where(SlipEvent.user_id == self.user_id))
        slips = result.scalars().all()
        self.assertEqual(len(slips), 3)
        self.assertTrue(all(s.notified_partner for s in slips))

if __name__ == "__main__":
    unittest.main()
