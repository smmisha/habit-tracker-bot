import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime, timedelta, date, timezone
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, and_

from database.models import Base, User, CheckInLog, RelapseLog, SlipEvent, JournalEntry
from database.db_helper import db_helper
from handlers.checkin import is_on_time
from handlers.tracker import format_timedelta, execute_relapse_reset
from main import (
    handle_ping,
    handle_api_stats,
    handle_api_save_journal,
    handle_api_log_relapse,
    handle_api_manage_panic,
    handle_api_accept_covenant,
    handle_api_spiritual_help,
)

class TestApiAndBusinessLogic(AioHTTPTestCase):
    async def setUpAsync(self):
        await super().setUpAsync()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.orig_engine = db_helper.engine
        self.orig_factory = db_helper.session_factory
        db_helper.engine = self.engine
        db_helper.session_factory = self.session_factory
        
        # Add test user
        self.user_id = 999001
        async with self.session_factory() as session:
            user = User(
                id=self.user_id,
                username="tester",
                first_name="Test User",
                streak_start=datetime.now() - timedelta(days=5),
                total_relapses=1,
                checkin_time="21:00",
                partner_username="partner123"
            )
            session.add(user)
            await session.commit()

    async def tearDownAsync(self):
        db_helper.engine = self.orig_engine
        db_helper.session_factory = self.orig_factory
        await self.engine.dispose()
        await super().tearDownAsync()

    async def get_application(self):
        app = web.Application()
        app.add_routes([
            web.get("/", handle_ping),
            web.get("/api/stats", handle_api_stats),
            web.post("/api/journal", handle_api_save_journal),
            web.post("/api/relapse", handle_api_log_relapse),
            web.post("/api/panic", handle_api_manage_panic),
            web.post("/api/accept_covenant", handle_api_accept_covenant),
            web.get("/api/spiritual_help", handle_api_spiritual_help),
            web.post("/api/spiritual_help", handle_api_spiritual_help),
        ])
        return app

    async def test_ping(self):
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertEqual(text, "OK")

    async def test_stats_missing_user_id(self):
        resp = await self.client.request("GET", "/api/stats")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("Missing user_id", data.get("error", ""))

    async def test_stats_invalid_user_id(self):
        resp = await self.client.request("GET", "/api/stats?user_id=-5")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("Invalid user_id", data.get("error", ""))

    async def test_stats_nonexistent_user(self):
        resp = await self.client.request("GET", "/api/stats?user_id=111222")
        self.assertEqual(resp.status, 404)
        data = await resp.json()
        self.assertIn("User not found", data.get("error", ""))

    async def test_stats_success(self):
        resp = await self.client.request("GET", f"/api/stats?user_id={self.user_id}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("streak_str", data)
        self.assertIn("total_relapses", data)
        self.assertEqual(data["total_relapses"], 1)
        self.assertIn("calendar_days", data)
        self.assertEqual(len(data["calendar_days"]), 30)
        self.assertIn("settings", data)
        self.assertEqual(data["settings"]["checkin_time"], "21:00")

    async def test_journal_empty_or_short(self):
        resp = await self.client.request("POST", "/api/journal", json={
            "user_id": self.user_id,
            "content": "abc"
        })
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("слишком короткая", data.get("error", ""))

    async def test_journal_too_long(self):
        long_content = "x" * 2005
        resp = await self.client.request("POST", "/api/journal", json={
            "user_id": self.user_id,
            "content": long_content
        })
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("слишком длинная", data.get("error", ""))

    async def test_journal_save_success(self):
        with patch("main.bot.send_message", new_callable=AsyncMock):
            resp = await self.client.request("POST", "/api/journal", json={
                "user_id": self.user_id,
                "content": "Сегодня был прекрасный день без компромиссов."
            })
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data.get("success"))

        async with self.session_factory() as session:
            result = await session.execute(
                select(JournalEntry).where(JournalEntry.user_id == self.user_id)
            )
            entries = result.scalars().all()
            self.assertEqual(len(entries), 1)
            self.assertIn("прекрасный день", entries[0].content)

    async def test_relapse_api_no_crash(self):
        """Verify /api/relapse does NOT crash with start_confession_flow ImportError and executes reset"""
        with patch("main.bot.send_message", new_callable=AsyncMock) as mock_send:
            resp = await self.client.request("POST", "/api/relapse", json={
                "user_id": self.user_id,
                "trigger_reason": "Стресс на работе"
            })
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("confession_pending"))

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.total_relapses, 2)
            
            # Check slip event created
            slips = (await session.execute(select(SlipEvent).where(SlipEvent.user_id == self.user_id))).scalars().all()
            self.assertEqual(len(slips), 1)

    async def test_panic_invalid_action(self):
        resp = await self.client.request("POST", "/api/panic", json={
            "user_id": self.user_id,
            "action": "unknown_action"
        })
        self.assertEqual(resp.status, 400)

    async def test_panic_initiate(self):
        resp = await self.client.request("POST", "/api/panic", json={
            "user_id": self.user_id,
            "action": "initiate"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))

    async def test_panic_failed_preserves_streak_no_relapse(self):
        """Verify action=failed in /api/panic does NOT reset streak and redirects to spiritual help"""
        async with self.session_factory() as session:
            user_before = await session.get(User, self.user_id)
            initial_streak_start = user_before.streak_start
            initial_relapses = user_before.total_relapses

        with patch("main.bot.send_message", new_callable=AsyncMock):
            resp = await self.client.request("POST", "/api/panic", json={
                "user_id": self.user_id,
                "action": "failed",
                "trigger_reason": "Сильная тяга ночью"
            })
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("relapse"))

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            # Streak and relapses must remain intact
            self.assertEqual(user.total_relapses, initial_relapses)
            self.assertEqual(user.streak_start, initial_streak_start)

    def test_panic_clean_launcher(self):
        from config.config import settings
        from handlers.panic import router
        # Verify router exists and has panic command
        self.assertIsNotNone(router)

    async def test_accept_covenant_invalid_payload(self):
        resp = await self.client.request("POST", "/api/accept_covenant", json={
            "user_id": -1
        })
        self.assertEqual(resp.status, 400)

    async def test_accept_covenant_success(self):
        resp = await self.client.request("POST", "/api/accept_covenant", json={
            "user_id": 999001,
            "mode": "restart"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))

    async def test_spiritual_help(self):
        resp = await self.client.request("GET", "/api/spiritual_help?user_id=999001")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("success"))
        self.assertTrue(len(data.get("spiritual_thought", "")) > 0)
        self.assertTrue(len(data.get("spiritual_action", "")) > 0)
        primary = data.get("primary_material")
        self.assertIsNotNone(primary)
        self.assertIn("title", primary)
        self.assertIn("url", primary)
        self.assertTrue(primary["url"].startswith("http"))
        self.assertTrue("jw.org" in primary["url"] or "wol.jw.org" in primary["url"])

    async def test_spiritual_help_post_sexting(self):
        resp = await self.client.request("POST", "/api/spiritual_help", json={
            "user_id": 999001,
            "temptation_type": "sexting"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("temptation_type"), "sexting")
        primary = data.get("primary_material")
        self.assertIsNotNone(primary)
        self.assertIn("секстинг", primary["title"].lower())
        self.assertTrue("wol.jw.org/ru/wol/d/r2/lp-u/502013360" in primary["url"])

    async def test_spiritual_help_post_custom_notes(self):
        resp = await self.client.request("POST", "/api/spiritual_help", json={
            "user_id": 999001,
            "user_notes": "Увидел фото знакомой девушки, очень хочу переспать"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("temptation_type"), "premarital_sex")
        primary = data.get("primary_material")
        self.assertIsNotNone(primary)
        self.assertTrue("wol.jw.org" in primary["url"])

    async def test_spiritual_help_round_2(self):
        resp = await self.client.request("POST", "/api/spiritual_help", json={
            "user_id": 999001,
            "temptation_type": "masturbation",
            "round": 2
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("round"), 2)
        primary = data.get("primary_material")
        self.assertIsNotNone(primary)
        self.assertTrue("1101989353" in primary["url"])

    async def test_spiritual_help_multi_select(self):
        resp = await self.client.request("POST", "/api/spiritual_help", json={
            "user_id": 999001,
            "temptation_types": ["sexting", "masturbation"]
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("sexting", data.get("temptation_types"))
        self.assertIn("masturbation", data.get("temptation_types"))
        self.assertIn("Секстинг", data.get("temptation_title"))
        self.assertIn("Мастурбация", data.get("temptation_title"))
        materials = data.get("materials")
        self.assertIsNotNone(materials)
        self.assertEqual(len(materials), 2)
        urls = [m["url"] for m in materials]
        self.assertTrue(any("502013360" in u for u in urls))
        self.assertTrue(any("1102008082" in u for u in urls))

    async def test_panic_partner_contacted_preserves_streak(self):
        async with self.session_factory() as session:
            user_before = await session.get(User, self.user_id)
            initial_streak_start = user_before.streak_start
            initial_relapses = user_before.total_relapses

        resp = await self.client.request("POST", "/api/panic", json={
            "user_id": self.user_id,
            "action": "partner_contacted"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))

        async with self.session_factory() as session:
            user_after = await session.get(User, self.user_id)
            self.assertEqual(user_after.streak_start, initial_streak_start)
            self.assertEqual(user_after.total_relapses, initial_relapses)


    def test_is_on_time_logic(self):
        scheduled = "21:00"
        base_time = datetime(2026, 6, 1, 21, 0, 0)
        
        # Exactly on time
        self.assertTrue(is_on_time(base_time, scheduled))
        # 4 minutes early
        self.assertTrue(is_on_time(base_time - timedelta(minutes=4), scheduled))
        # 5 minutes late (boundary)
        self.assertTrue(is_on_time(base_time + timedelta(minutes=5), scheduled))
        # 6 minutes late (outside window)
        self.assertFalse(is_on_time(base_time + timedelta(minutes=6), scheduled))
        # 6 minutes early (outside window)
        self.assertFalse(is_on_time(base_time - timedelta(minutes=6), scheduled))

    def test_format_timedelta(self):
        td1 = timedelta(days=2, hours=3, minutes=15, seconds=30)
        formatted1 = format_timedelta(td1)
        self.assertIn("2</b> дн.", formatted1)
        self.assertIn("3</b> ч.", formatted1)
        self.assertIn("15</b> мин.", formatted1)
        self.assertIn("30</b> сек.", formatted1)

        td2 = timedelta(minutes=45, seconds=10)
        formatted2 = format_timedelta(td2)
        self.assertNotIn("дн.", formatted2)
        self.assertIn("45</b> мин.", formatted2)

if __name__ == "__main__":
    unittest.main()
