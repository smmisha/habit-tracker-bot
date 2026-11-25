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
from database.db_helper import db_helper, DatabaseHelper
from handlers.checkin import is_on_time
from handlers.tracker import format_timedelta, execute_relapse_reset
from config.config import settings
import hmac
import hashlib
import json
from urllib.parse import urlencode
from main import (
    handle_ping,
    handle_api_stats,
    handle_api_save_journal,
    handle_api_log_relapse,
    handle_api_manage_panic,
    handle_api_accept_covenant,
    handle_api_spiritual_help,
    handle_api_spiritual_reflection,
    validate_telegram_init_data,
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
            web.post("/api/spiritual_reflection", handle_api_spiritual_reflection),
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
        """Verify /api/relapse executes reset cleanly without notifying partner"""
        with patch("main.bot.send_message", new_callable=AsyncMock) as mock_send, \
             patch("services.userbot_client.userbot.send_message_to_partner", new_callable=AsyncMock) as mock_partner:
            resp = await self.client.request("POST", "/api/relapse", json={
                "user_id": self.user_id,
                "trigger_reason": "Стресс на работе"
            })
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("confession_pending"))
            mock_partner.assert_not_called()
            mock_send.assert_awaited()

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.total_relapses, 2)
            
            # Check slip event created without automatic partner alert
            slips = (await session.execute(select(SlipEvent).where(SlipEvent.user_id == self.user_id))).scalars().all()
            self.assertEqual(len(slips), 1)
            self.assertFalse(slips[0].notified_partner)

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

    def test_purity_covenant_conscience_rules_and_no_timer_lock(self):
        covenant_html = (Path(__file__).parent.parent / "webapp" / "purity_covenant_jw_v2.html").read_text(encoding="utf-8")
        # No timer lock or old partner ID / 3-relapse loophole
        self.assertNotIn("timeRemaining = 180", covenant_html)
        self.assertNotIn("693 656 777", covenant_html)
        self.assertNotIn("три раза подряд", covenant_html)
        # Key conscience rules present
        self.assertIn("Колоссянам 3:5", covenant_html)
        self.assertIn("не считается срывом", covenant_html)
        self.assertIn("продолжил смотреть", covenant_html)
        self.assertIn("в течение недели", covenant_html)
        self.assertIn("не обязательно", covenant_html)
        self.assertIn("основной посыл", covenant_html.lower())
        self.assertIn("порнографии", covenant_html.lower())
        self.assertIn("что именно я запомнил", covenant_html.lower())

    async def test_spiritual_reflection_rejects_shallow_and_saves_sincere(self):
        # 1. Generic shallow boilerplate should be rejected softly without saving
        resp_shallow = await self.client.request("POST", "/api/spiritual_reflection", json={
            "user_id": self.user_id,
            "article_title": "Что говорит Библия о порнографии?",
            "reflection_text": "порно это плохо и грех",
            "round": 1
        })
        self.assertEqual(resp_shallow.status, 200)
        shallow_data = await resp_shallow.json()
        self.assertFalse(shallow_data.get("accepted"))

        # 2. Sincere takeaway with verses should save into JournalEntry and append cleanly
        async with self.session_factory() as session:
            session.add(JournalEntry(
                user_id=self.user_id,
                entry_date=date.today(),
                content="Утренняя заметка перед работой."
            ))
            await session.commit()

        sincere_text = (
            "Запомнился Притчи 4:23 про то, как важно хранить сердце с самого начала. "
            "Из статьи понял, что нельзя торговаться со взглядом в первые секунды."
        )
        with patch("services.ai_service.ai_service._call_gemini", new_callable=AsyncMock, return_value='{"accepted": true, "feedback": "Отличный искренний вывод!"}'), \
             patch("main.bot.send_message", new_callable=AsyncMock):
            resp_ok = await self.client.request("POST", "/api/spiritual_reflection", json={
                "user_id": self.user_id,
                "article_title": "Что говорит Библия о порнографии?",
                "reflection_text": sincere_text,
                "round": 1
            })
            self.assertEqual(resp_ok.status, 200)
            ok_data = await resp_ok.json()
            self.assertTrue(ok_data.get("accepted"))

        async with self.session_factory() as session:
            entries = (await session.execute(select(JournalEntry).where(JournalEntry.user_id == self.user_id))).scalars().all()
            self.assertEqual(len(entries), 1)
            self.assertIn("Утренняя заметка", entries[0].content)
            self.assertIn("Притчи 4:23", entries[0].content)

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

    def _create_mock_init_data(self, user_dict, bot_token=None, tamper=False):
        token = bot_token or settings.bot_token
        auth_date = int(datetime.now().timestamp())
        params = {
            "auth_date": str(auth_date),
            "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": json.dumps(user_dict, separators=(",", ":")),
        }
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if tamper:
            calc_hash = "invalid_hash_signature_12345"
        params["hash"] = calc_hash
        return urlencode(params)

    def test_validate_telegram_init_data_valid(self):
        user = {"id": 123456, "first_name": "John", "username": "johndoe"}
        init_data = self._create_mock_init_data(user)
        result = validate_telegram_init_data(init_data, settings.bot_token)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("id"), 123456)
        self.assertEqual(result.get("username"), "johndoe")

    def test_validate_telegram_init_data_invalid_hash(self):
        user = {"id": 123456}
        init_data = self._create_mock_init_data(user, tamper=True)
        result = validate_telegram_init_data(init_data, settings.bot_token)
        self.assertIsNone(result)

    def test_validate_telegram_init_data_tampered(self):
        user = {"id": 123456}
        init_data = self._create_mock_init_data(user)
        tampered = init_data.replace("123456", "999999")
        result = validate_telegram_init_data(tampered, settings.bot_token)
        self.assertIsNone(result)

    def test_validate_telegram_init_data_wrong_token(self):
        user = {"id": 123456}
        init_data = self._create_mock_init_data(user, bot_token="12345:wrong_token")
        result = validate_telegram_init_data(init_data, settings.bot_token)
        self.assertIsNone(result)

    def test_validate_telegram_init_data_missing_hash(self):
        result = validate_telegram_init_data("user=%7B%22id%22%3A123%7D&auth_date=12345", settings.bot_token)
        self.assertIsNone(result)

    def test_validate_telegram_init_data_empty(self):
        self.assertIsNone(validate_telegram_init_data("", settings.bot_token))
        self.assertIsNone(validate_telegram_init_data(None, settings.bot_token))
        self.assertIsNone(validate_telegram_init_data("test", ""))

    async def test_stats_with_valid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id})
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("GET", "/api/stats", headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("streak_str", data)
        self.assertIn("calendar_days", data)

    async def test_stats_with_invalid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id}, tamper=True)
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("GET", "/api/stats", headers=headers)
        self.assertEqual(resp.status, 401)
        data = await resp.json()
        self.assertIn("error", data)

    async def test_journal_with_valid_init_data(self):
        with patch("main.bot.send_message", new_callable=AsyncMock):
            init_data = self._create_mock_init_data({"id": self.user_id})
            headers = {"X-Telegram-Init-Data": init_data}
            resp = await self.client.request("POST", "/api/journal", headers=headers, json={
                "content": "A valid authenticated journal reflection note"
            })
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertTrue(data.get("success"))
            self.assertIn("message", data)

    async def test_journal_with_invalid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id}, tamper=True)
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("POST", "/api/journal", headers=headers, json={
            "content": "A valid journal note with bad auth"
        })
        self.assertEqual(resp.status, 401)

    async def test_relapse_with_invalid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id}, tamper=True)
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("POST", "/api/relapse", headers=headers, json={
            "trigger_reason": "Relapse test"
        })
        self.assertEqual(resp.status, 401)

    async def test_panic_with_invalid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id}, tamper=True)
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("POST", "/api/panic", headers=headers, json={
            "action": "start"
        })
        self.assertEqual(resp.status, 401)

    async def test_spiritual_help_with_valid_init_data(self):
        init_data = self._create_mock_init_data({"id": self.user_id})
        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("GET", "/api/spiritual_help?temptation_type=loneliness", headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("materials", data)

    @patch("database.db_helper.create_async_engine")
    def test_database_helper_postgres_pool_settings(self, mock_create_engine):
        helper = DatabaseHelper("postgresql+asyncpg://user:pass@localhost/testdb")
        mock_create_engine.assert_called_once()
        _, kwargs = mock_create_engine.call_args
        self.assertTrue(kwargs.get("pool_pre_ping"))
        self.assertEqual(kwargs.get("pool_recycle"), 180)
        self.assertEqual(kwargs.get("connect_args", {}).get("statement_cache_size"), 0)

    @patch("database.db_helper.create_async_engine")
    def test_database_helper_sqlite_pool_settings(self, mock_create_engine):
        helper = DatabaseHelper("sqlite+aiosqlite:///:memory:")
        mock_create_engine.assert_called_once()
        _, kwargs = mock_create_engine.call_args
        self.assertNotIn("pool_pre_ping", kwargs)
        self.assertNotIn("pool_recycle", kwargs)
        self.assertEqual(kwargs.get("connect_args", {}).get("check_same_thread"), False)

    def test_scheduler_not_started_when_bot_paused(self):
        from services import scheduler as sched_mod
        with patch.object(settings, "bot_paused", True), \
             patch.object(sched_mod.scheduler, "start") as mock_start, \
             patch.object(sched_mod.scheduler, "add_job") as mock_add_job:
            sched_mod.setup_scheduler()
            mock_start.assert_not_called()
            mock_add_job.assert_not_called()

    async def test_missed_deadlines_skips_inactive_user(self):
        from services.scheduler import check_missed_deadlines
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = False
            session.add(CheckInLog(
                user_id=self.user_id,
                checkin_date=date.today() - timedelta(days=2),
                status="pending"
            ))
            await session.commit()

        with patch("main.bot.send_message", new_callable=AsyncMock) as mock_send:
            await check_missed_deadlines()
            mock_send.assert_not_called()

        async with self.session_factory() as session:
            logs = (await session.execute(select(CheckInLog).where(CheckInLog.user_id == self.user_id))).scalars().all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].status, "pending")

    async def test_auto_clean_after_24h_deletes_message_and_increments_missed(self):
        from services.scheduler import check_missed_deadlines
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = True
            user.consecutive_missed_checkins = 0
            user.last_checkin_message_id = 777
            session.add(CheckInLog(
                user_id=self.user_id,
                checkin_date=date.today() - timedelta(days=2),
                status="pending",
                message_id=777
            ))
            await session.commit()

        with patch("main.bot.delete_message", new_callable=AsyncMock) as mock_del, \
             patch("main.bot.send_message", new_callable=AsyncMock) as mock_send:
            await check_missed_deadlines()
            mock_del.assert_awaited_once_with(chat_id=self.user_id, message_id=777)
            mock_send.assert_not_called()

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.consecutive_missed_checkins, 1)
            self.assertTrue(user.is_active)
            self.assertIsNone(user.last_checkin_message_id)
            log = (await session.execute(select(CheckInLog).where(CheckInLog.user_id == self.user_id))).scalar_one()
            self.assertEqual(log.status, "clean")
            self.assertEqual(log.excuse_reason, "Авто-отметка (>24ч без ответа)")

    async def test_auto_pause_after_7_consecutive_missed_days(self):
        from services.scheduler import check_missed_deadlines
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = True
            user.consecutive_missed_checkins = 6
            session.add(CheckInLog(
                user_id=self.user_id,
                checkin_date=date.today() - timedelta(days=2),
                status="pending",
                message_id=888
            ))
            await session.commit()

        with patch("main.bot.delete_message", new_callable=AsyncMock), \
             patch("main.bot.send_message", new_callable=AsyncMock) as mock_send, \
             patch("services.userbot_client.userbot.send_message_to_partner", new_callable=AsyncMock) as mock_partner:
            await check_missed_deadlines()
            mock_partner.assert_not_called()
            mock_send.assert_awaited_once()
            args, kwargs = mock_send.call_args
            self.assertEqual(kwargs.get("chat_id"), self.user_id)
            self.assertIn("паузу", kwargs.get("text", ""))

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.consecutive_missed_checkins, 7)
            self.assertFalse(user.is_active)

    async def test_apply_nov_2026_fresh_start_reset_is_idempotent(self):
        from database.models import SystemMigration
        target_id = 5037862619
        async with self.session_factory() as session:
            session.add(User(
                id=target_id,
                username="misha",
                first_name="Michael",
                timezone="Europe/Kyiv",
                partner_username="8215716011",
                total_relapses=33,
                forgot_count=3,
                consecutive_missed_checkins=5,
                awarded_milestones="1,3,7,14,30",
                is_active=False
            ))
            session.add(RelapseLog(user_id=target_id, trigger_reason="Old trigger"))
            session.add(SlipEvent(user_id=target_id, notified_partner=True))
            session.add(CheckInLog(user_id=target_id, checkin_date=date(2026, 11, 17), status="missed"))
            session.add(JournalEntry(user_id=target_id, entry_date=date(2026, 11, 1), content="Old journal"))
            await session.commit()

        applied1 = await db_helper.apply_nov_2026_fresh_start_reset(target_user_id=target_id)
        self.assertTrue(applied1)

        async with self.session_factory() as session:
            user = await session.get(User, target_id)
            self.assertTrue(user.is_active)
            self.assertEqual(user.total_relapses, 1)
            self.assertEqual(user.forgot_count, 0)
            self.assertEqual(user.consecutive_missed_checkins, 0)
            self.assertEqual(user.awarded_milestones, "1,3")
            self.assertEqual(user.streak_start, datetime(2026, 11, 19, 20, 0, 0))
            self.assertEqual(user.partner_username, "8215716011")

            relapses = (await session.execute(select(RelapseLog).where(RelapseLog.user_id == target_id))).scalars().all()
            slips = (await session.execute(select(SlipEvent).where(SlipEvent.user_id == target_id))).scalars().all()
            checkins = (await session.execute(select(CheckInLog).where(CheckInLog.user_id == target_id).order_by(CheckInLog.checkin_date))).scalars().all()
            journals = (await session.execute(select(JournalEntry).where(JournalEntry.user_id == target_id))).scalars().all()

            self.assertEqual(len(relapses), 1)
            self.assertEqual(relapses[0].timestamp, datetime(2026, 11, 19, 20, 0, 0))
            self.assertEqual(len(slips), 1)
            self.assertTrue(slips[0].notified_partner)
            self.assertEqual([(c.checkin_date, c.status) for c in checkins], [
                (date(2026, 11, 19), "relapsed"),
                (date(2026, 11, 20), "clean"),
                (date(2026, 11, 21), "clean"),
                (date(2026, 11, 22), "clean"),
            ])
            self.assertEqual(len(journals), 0)

            # Second run must be idempotent no-op
            session.add(JournalEntry(user_id=target_id, entry_date=date(2026, 11, 23), content="New note after reset"))
            await session.commit()

        applied2 = await db_helper.apply_nov_2026_fresh_start_reset(target_user_id=target_id)
        self.assertFalse(applied2)

        async with self.session_factory() as session:
            journals_after = (await session.execute(select(JournalEntry).where(JournalEntry.user_id == target_id))).scalars().all()
            self.assertEqual(len(journals_after), 1)

    async def test_checkin_clean_anytime_resets_missed_counter(self):
        from handlers.checkin import process_checkin_clean
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.consecutive_missed_checkins = 4
            user.checkin_time = "03:00"
            session.add(CheckInLog(
                user_id=self.user_id,
                checkin_date=date.today(),
                status="pending"
            ))
            await session.commit()

        mock_callback = MagicMock()
        mock_callback.from_user.id = self.user_id
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.message.answer = AsyncMock()
        mock_callback.answer = AsyncMock()

        with patch("services.ai_service.ai_service.generate_clean_checkin_response", new_callable=AsyncMock, return_value="Молодец!"):
            await process_checkin_clean(mock_callback)

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.consecutive_missed_checkins, 0)
            log = (await session.execute(select(CheckInLog).where(CheckInLog.user_id == self.user_id))).scalar_one()
            self.assertEqual(log.status, "clean")
            self.assertIsNone(log.excuse_reason)

    async def test_resume_from_pause_callbacks(self):
        from handlers.common import process_resume_clean, process_resume_relapse
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = False
            user.consecutive_missed_checkins = 7
            await session.commit()

        cb = MagicMock()
        cb.from_user.id = self.user_id
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()

        await process_resume_clean(cb)
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertTrue(user.is_active)
            self.assertEqual(user.consecutive_missed_checkins, 0)

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = False
            user.consecutive_missed_checkins = 7
            await session.commit()

        await process_resume_relapse(cb)
        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertTrue(user.is_active)
            self.assertEqual(user.consecutive_missed_checkins, 0)
            cb.message.edit_text.assert_awaited()

    async def test_check_and_send_checkins_drift_tolerant(self):
        import pytz
        from services.scheduler import check_and_send_checkins

        kyiv_tz = pytz.timezone("Europe/Kyiv")
        fake_now_kyiv = kyiv_tz.localize(datetime(2026, 11, 23, 21, 1, 10))  # 21:01 (drifted 1 min past 21:00)

        mock_sent = MagicMock()
        mock_sent.message_id = 555

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            user.is_active = True
            user.checkin_time = "21:00"
            user.timezone = "Europe/Kyiv"
            await session.commit()

        with patch("services.scheduler.datetime") as mock_dt, \
             patch("main.bot.send_message", new_callable=AsyncMock, return_value=mock_sent) as mock_send:
            mock_dt.now.side_effect = lambda tz=None: fake_now_kyiv if tz else datetime(2026, 11, 23, 21, 1, 10)
            mock_dt.combine = datetime.combine

            # First tick at 21:01 sends even though scheduled was 21:00
            await check_and_send_checkins()
            self.assertEqual(mock_send.call_count, 1)

            # Second tick at 21:02 must NOT send duplicate
            await check_and_send_checkins()
            self.assertEqual(mock_send.call_count, 1)

        async with self.session_factory() as session:
            user = await session.get(User, self.user_id)
            self.assertEqual(user.last_checkin_message_id, 555)
            log = (await session.execute(select(CheckInLog).where(CheckInLog.user_id == self.user_id))).scalar_one()
            self.assertEqual(log.checkin_date, date(2026, 11, 23))
            self.assertEqual(log.message_id, 555)

    async def test_apply_nov_2026_24_relapse_record_is_idempotent(self):
        target_id = 5037862619
        async with self.session_factory() as session:
            session.add(User(
                id=target_id,
                username="misha",
                first_name="Michael",
                timezone="Europe/Kyiv",
                streak_start=datetime(2026, 11, 19, 20, 0, 0),
                total_relapses=1,
                is_active=True
            ))
            session.add(RelapseLog(
                user_id=target_id,
                timestamp=datetime(2026, 11, 19, 20, 0, 0),
                trigger_reason="Срыв (четверг, 19.11.2026)"
            ))
            session.add(CheckInLog(
                user_id=target_id,
                checkin_date=date(2026, 11, 24),
                status="clean",
                excuse_reason="Авто-отметка (>24ч без ответа)"
            ))
            await session.commit()

        applied1 = await db_helper.apply_nov_2026_24_relapse_record(target_user_id=target_id)
        self.assertTrue(applied1)

        async with self.session_factory() as session:
            user = await session.get(User, target_id)
            self.assertEqual(user.total_relapses, 2)
            self.assertEqual(user.streak_start, datetime(2026, 11, 24, 21, 0, 0))
            relapses = (await session.execute(select(RelapseLog).where(RelapseLog.user_id == target_id).order_by(RelapseLog.timestamp))).scalars().all()
            self.assertEqual(len(relapses), 2)
            self.assertEqual(relapses[-1].trigger_reason, "Искушение в интернете")
            ch = (await session.execute(select(CheckInLog).where(and_(CheckInLog.user_id == target_id, CheckInLog.checkin_date == date(2026, 11, 24))))).scalar_one()
            self.assertEqual(ch.status, "relapsed")
            self.assertIsNone(ch.excuse_reason)
            slips = (await session.execute(select(SlipEvent).where(SlipEvent.user_id == target_id))).scalars().all()
            self.assertEqual(len(slips), 1)
            self.assertFalse(slips[0].notified_partner)

        applied2 = await db_helper.apply_nov_2026_24_relapse_record(target_user_id=target_id)
        self.assertFalse(applied2)

if __name__ == "__main__":
    unittest.main()
