import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytz

from database.db_helper import DatabaseHelper, db_helper
from database.models import JournalEntry, RecoveryTask, RelapseLog, User
from handlers import checkin
from services import day_report, recovery_tasks
from services.ai_service import ai_service
from services.scheduler import send_weekly_reports
from tests.test_missed_days_and_content import USER_ID, OTHER_ID, DatabaseTestCase

KYIV = pytz.timezone("Europe/Kyiv")

SUMMARY = (
    "В статье говорится, что порнография действует как ловушка: сначала кажется безобидной, "
    "а потом отнимает покой и дружбу с Богом. Мне запомнился пример о том, как важно сразу отводить глаза. "
    "Для себя беру решение убирать телефон из спальни и вечером звонить другу."
)


class RecoveryTestCase(DatabaseTestCase):
    async def tasks(self, user_id=USER_ID):
        return sorted(await self.rows(RecoveryTask, user_id), key=lambda task: task.id)

    async def issue(self, now: datetime, user_id=USER_ID) -> RecoveryTask:
        async with self.session_factory() as session:
            task = await recovery_tasks.ensure_task(session, user_id, now)
            await session.commit()
            return task


class TestTaskCreation(RecoveryTestCase):
    async def test_second_task_waits_until_first_is_overdue(self):
        start = datetime.now() - timedelta(days=3)
        first = await self.issue(start)
        self.assertEqual(first.due_at, start + timedelta(hours=24))
        self.assertEqual((await self.issue(start + timedelta(hours=23))).id, first.id)
        self.assertEqual(len(await self.tasks()), 1)

        second = await self.issue(start + timedelta(hours=25))
        self.assertNotEqual(second.id, first.id)
        self.assertEqual([task.status for task in await self.tasks()], ["missed", "open"])
        self.assertIsNone((await self.tasks())[0].completed_at)

    async def test_task_is_new_after_previous_one_is_done(self):
        now = datetime.now()
        first = await self.issue(now)
        await recovery_tasks.submit_summary(USER_ID, first.id, SUMMARY)
        self.assertNotEqual((await self.issue(now + timedelta(minutes=1))).id, first.id)

    async def test_articles_rotate_unseen_first_then_oldest(self):
        start = datetime.now() - timedelta(days=40)
        urls = [(await self.issue(start + timedelta(days=2 * i))).article_url for i in range(12)]
        catalog = [url for _, url in recovery_tasks.ARTICLES]
        self.assertEqual(urls, catalog + catalog[:3])
        # Статьи другого пользователя на очередность не влияют
        self.assertEqual((await self.issue(start, OTHER_ID)).article_url, catalog[0])

    def test_article_catalog(self):
        urls = [url for _, url in recovery_tasks.ARTICLES]
        self.assertEqual(len(set(urls)), 9)
        for url in urls:
            self.assertTrue(url.startswith(("https://wol.jw.org/ru/", "https://www.jw.org/ru/")))
            self.assertTrue(url.isascii())

    async def test_late_relapse_creates_task_counted_from_marking_moment(self):
        await self.add_days((5, "missed"))
        before = datetime.now()
        self.assertTrue(await day_report.mark_day(USER_ID, self.ago(5), relapsed=True))
        task = (await self.tasks())[0]
        self.assertTrue(before <= task.created_at <= datetime.now())
        self.assertEqual(task.due_at - task.created_at, timedelta(hours=24))

    async def test_clean_or_repeated_mark_creates_no_extra_task(self):
        await self.add_days((3, "missed"), (2, "missed"))
        await day_report.mark_day(USER_ID, self.ago(3), relapsed=False)
        self.assertEqual(await self.tasks(), [])
        await day_report.mark_day(USER_ID, self.ago(2), relapsed=True)
        self.assertFalse(await day_report.mark_day(USER_ID, self.ago(2), relapsed=True))
        self.assertEqual(len(await self.tasks()), 1)


class TestSurveyAnnouncement(RecoveryTestCase):
    def callback(self, data):
        callback = MagicMock()
        callback.data = data
        callback.from_user.id = USER_ID
        callback.answer = AsyncMock()
        callback.message.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        return callback

    def state(self):
        data = {}
        state = MagicMock()
        state.get_data = AsyncMock(side_effect=lambda: dict(data))

        async def update_data(**values):
            data.update(values)

        state.update_data = AsyncMock(side_effect=update_data)
        return state

    async def press(self, data, state) -> list[str]:
        callback = self.callback(data)
        await checkin.process_day_report(callback, state)
        return [call.args[0] for call in callback.message.answer.await_args_list]

    async def test_task_is_sent_once_after_the_last_day(self):
        await self.add_days((3, "missed"), (2, "missed"))
        state = self.state()
        self.assertEqual(await self.press(f"day:why:{self.ago(3).isoformat()}:web", state), [])
        sent = await self.press(f"day:why:{self.ago(2).isoformat()}:web", state)
        self.assertEqual(len(sent), 1)
        self.assertIn("Задание на сутки", sent[0])
        self.assertEqual(await self.press("day:later", state), [])

    async def test_task_is_sent_when_survey_is_postponed(self):
        await self.add_days((3, "missed"), (2, "missed"))
        state = self.state()
        await self.press(f"day:why:{self.ago(3).isoformat()}:web", state)
        sent = await self.press("day:later", state)
        self.assertEqual(len(sent), 1)
        self.assertIn("Задание на сутки", sent[0])

    async def test_task_already_sent_in_chat_is_not_repeated(self):
        await self.issue(datetime.now())
        await self.add_days((2, "missed"))
        sent = await self.press(f"day:why:{self.ago(2).isoformat()}:web", self.state())
        self.assertEqual(sent, [])

    async def test_clean_survey_sends_no_task(self):
        await self.add_days((2, "missed"))
        self.assertEqual(await self.press(f"day:clean:{self.ago(2).isoformat()}", self.state()), [])


class TestSummary(RecoveryTestCase):
    def test_threshold_and_template_phrases(self):
        self.assertTrue(recovery_tasks.is_summary_acceptable(SUMMARY))
        # Обычные слова из списка отписок не мешают настоящему пересказу
        self.assertTrue(recovery_tasks.is_summary_acceptable("Я прочитал статью. " + SUMMARY))
        for text in (
            SUMMARY[:199],
            " " * 300 + "коротко",
            "а" * 400,
            "Порно — это плохо и грех. " * 12,
            "Хорошая статья, понятно, согласен. " * 10,
            "1234567890 " * 30,
        ):
            with self.subTest(text=text[:40]):
                self.assertFalse(recovery_tasks.is_summary_acceptable(text))

    async def test_accepted_summary_is_stored_and_copied_to_journal(self):
        task = await self.issue(datetime.now())
        async with self.session_factory() as session:
            (await session.get(User, USER_ID)).consecutive_missed_checkins = 4
            await session.commit()

        result = await recovery_tasks.submit_summary(USER_ID, task.id, f"  {SUMMARY}  ")
        self.assertEqual(result, ("done", False, True))
        stored = (await self.tasks())[0]
        self.assertEqual((stored.status, stored.summary), ("done", SUMMARY))
        self.assertIsNotNone(stored.completed_at)
        entry = (await self.rows(JournalEntry))[0]
        self.assertEqual(entry.entry_date, date.today())
        self.assertEqual(entry.content, f"📖 Пересказ после срыва: «{task.article_title}»\n{SUMMARY}")
        self.assertEqual((await self.user()).consecutive_missed_checkins, 0)

        again = await recovery_tasks.submit_summary(USER_ID, task.id, SUMMARY)
        self.assertEqual(again.status, "closed")

    async def test_only_journal_copy_is_cut_to_column_limit(self):
        old_note = "Утренняя заметка. " * 90
        async with self.session_factory() as session:
            session.add(JournalEntry(user_id=USER_ID, entry_date=date.today(), content=old_note))
            await session.commit()
        task = await self.issue(datetime.now())
        long_summary = SUMMARY + " " + " ".join(f"мысль{i}" for i in range(200))

        result = await recovery_tasks.submit_summary(USER_ID, task.id, long_summary)
        self.assertTrue(result.in_journal)
        content = (await self.rows(JournalEntry))[0].content
        self.assertEqual(len(content), 2000)
        self.assertTrue(content.startswith(old_note.rstrip()))
        self.assertIn("Пересказ после срыва", content)
        self.assertEqual((await self.tasks())[0].summary, long_summary)

    async def test_full_journal_keeps_old_text(self):
        old_note = "я" * 2000
        async with self.session_factory() as session:
            session.add(JournalEntry(user_id=USER_ID, entry_date=date.today(), content=old_note))
            await session.commit()
        task = await self.issue(datetime.now())
        result = await recovery_tasks.submit_summary(USER_ID, task.id, SUMMARY)
        self.assertEqual((result.status, result.in_journal), ("done", False))
        self.assertEqual((await self.rows(JournalEntry))[0].content, old_note)

    async def test_rejections_change_nothing(self):
        task = await self.issue(datetime.now())
        cases = (
            (OTHER_ID, task.id, SUMMARY, "not_found"),
            (USER_ID, task.id + 100, SUMMARY, "not_found"),
            (USER_ID, 2 ** 40, SUMMARY, "not_found"),
            (USER_ID, task.id, "коротко", "short"),
            (USER_ID, task.id, SUMMARY * 20, "long"),
        )
        for user_id, task_id, text, status in cases:
            with self.subTest(status=status, task_id=task_id):
                result = await recovery_tasks.submit_summary(user_id, task_id, text)
                self.assertEqual(result.status, status)
        self.assertEqual((await self.tasks())[0].status, "open")
        self.assertEqual(await self.rows(JournalEntry), [])

    async def test_overdue_task_is_accepted_as_late(self):
        task = await self.issue(datetime.now() - timedelta(hours=30))
        result = await recovery_tasks.submit_summary(USER_ID, task.id, SUMMARY)
        self.assertEqual((result.status, result.late), ("done", True))


class TestReminders(RecoveryTestCase):
    """Время задается по часам пользователя (Киев), а сервер — то в UTC, то в Киеве."""

    SERVER_ZONES = (pytz.utc, KYIV)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()

    async def on_each_server(self, scenario):
        for zone in self.SERVER_ZONES:
            with self.subTest(server=zone.zone), \
                 patch.object(recovery_tasks, "as_server_time", zone.localize):
                async with self.session_factory() as session:
                    await session.execute(RecoveryTask.__table__.delete())
                    await session.commit()
                self.bot.send_message.reset_mock()
                self.zone = zone
                await scenario()

    def at(self, day: int, hour: int, minute: int = 0) -> datetime:
        """Киевское время декабря 2026 в виде времени сервера, как оно лежит в базе"""
        moment = KYIV.localize(datetime(2026, 12, day, hour, minute))
        return moment.astimezone(self.zone).replace(tzinfo=None)

    async def tick(self, moment: datetime) -> list[str]:
        self.bot.send_message.reset_mock()
        await recovery_tasks.send_task_reminders(self.bot, moment)
        return [call.kwargs["text"] for call in self.bot.send_message.await_args_list]

    async def test_card_shows_deadline_in_user_time(self):
        async def scenario():
            task = await self.issue(self.at(1, 14, 5))
            text, keyboard = recovery_tasks.task_card(await self.user(), task)
            self.assertIn("Срок: до 14:05, 02.12 (по твоему времени).", text)
            self.assertEqual(keyboard.inline_keyboard[0][0].url, task.article_url)
            self.assertEqual(keyboard.inline_keyboard[1][0].callback_data, f"task:write:{task.id}")
            payload = recovery_tasks.task_payload(await self.user(), task, self.at(1, 14, 5))
            self.assertEqual(payload["due_at"], "2026-12-02T14:05:00+02:00")
            self.assertEqual((payload["hours_left"], payload["overdue"]), (24, False))

        await self.on_each_server(scenario)

    async def test_each_message_is_sent_once(self):
        async def scenario():
            await self.issue(self.at(1, 20))  # срок 02.12 в 20:00
            self.assertEqual(await self.tick(self.at(2, 7, 55)), [])
            first = await self.tick(self.at(2, 8))
            self.assertEqual(len(first), 1)
            self.assertIn("осталось 12 часов", first[0])
            self.assertEqual(await self.tick(self.at(2, 8, 5)), [])
            self.assertEqual(await self.tick(self.at(2, 16, 55)), [])
            second = await self.tick(self.at(2, 17))
            self.assertIn("осталось 3 часа", second[0])
            self.assertEqual(await self.tick(self.at(2, 17, 5)), [])
            expired = await self.tick(self.at(2, 20))
            self.assertEqual(expired, [recovery_tasks.DEADLINE_TEXT])
            self.assertEqual(await self.tick(self.at(2, 20, 5)), [])
            self.assertEqual(await self.tick(self.at(3, 12)), [])

        await self.on_each_server(scenario)

    async def test_quiet_hours_move_reminder_to_morning(self):
        async def scenario():
            await self.issue(self.at(1, 13))  # 12 часов остается в 01:00
            for moment in (self.at(1, 23), self.at(2, 1), self.at(2, 7, 59)):
                self.assertEqual(await self.tick(moment), [])
            morning = await self.tick(self.at(2, 8))
            self.assertEqual(len(morning), 1)
            self.assertIn("осталось 5 часов", morning[0])

        await self.on_each_server(scenario)

    async def test_reminder_is_dropped_when_morning_is_after_deadline(self):
        async def scenario():
            await self.issue(self.at(1, 2))  # срок 02.12 в 02:00, ночью
            self.assertIn("часов", (await self.tick(self.at(1, 14)))[0])
            self.assertEqual(await self.tick(self.at(1, 23, 30)), [])
            self.assertEqual(await self.tick(self.at(2, 3)), [])
            self.assertEqual(await self.tick(self.at(2, 8)), [recovery_tasks.DEADLINE_TEXT])
            self.assertEqual(await self.tick(self.at(2, 8, 5)), [])

        await self.on_each_server(scenario)

    async def test_after_server_sleep_only_latest_message_is_sent(self):
        async def scenario():
            await self.issue(self.at(1, 20))
            woke = await self.tick(self.at(2, 18))
            self.assertEqual(len(woke), 1)
            self.assertIn("осталось 2 часа", woke[0])
            self.assertEqual((await self.tasks())[0].reminders_sent, 2)
            self.assertEqual(await self.tick(self.at(2, 18, 5)), [])

            async with self.session_factory() as session:
                await session.execute(RecoveryTask.__table__.delete())
                await session.commit()
            await self.issue(self.at(1, 20))
            self.assertEqual(await self.tick(self.at(3, 10)), [recovery_tasks.DEADLINE_TEXT])
            self.assertEqual(await self.tick(self.at(3, 10, 5)), [])

        await self.on_each_server(scenario)

    async def test_inactive_users_and_finished_tasks_are_skipped(self):
        async def scenario():
            await self.issue(self.at(1, 20))
            await self.issue(self.at(1, 20), OTHER_ID)
            async with self.session_factory() as session:
                (await session.get(User, USER_ID)).is_active = False
                (await session.get(RecoveryTask, (await self.tasks(OTHER_ID))[0].id)).status = "done"
                await session.commit()
            self.assertEqual(await self.tick(self.at(2, 10)), [])
            self.assertEqual(await self.tick(self.at(3, 10)), [])
            async with self.session_factory() as session:
                (await session.get(User, USER_ID)).is_active = True
                await session.commit()

        await self.on_each_server(scenario)

    async def test_failed_send_is_retried(self):
        async def scenario():
            await self.issue(self.at(1, 20))
            self.bot.send_message.side_effect = OSError("offline")
            await recovery_tasks.send_task_reminders(self.bot, self.at(2, 8))
            self.assertEqual((await self.tasks())[0].reminders_sent, 0)
            self.bot.send_message.side_effect = None
            self.assertEqual(len(await self.tick(self.at(2, 8, 5))), 1)

        await self.on_each_server(scenario)

    def test_hour_forms(self):
        cases = {
            timedelta(hours=11, minutes=55): "осталось 12 часов",
            timedelta(hours=2, minutes=56): "осталось 3 часа",
            timedelta(hours=1, minutes=5): "остался 1 час",
            timedelta(minutes=30): "осталось меньше часа",
        }
        for left, phrase in cases.items():
            self.assertEqual(recovery_tasks._time_left_phrase(left), phrase)


class TestWeeklyReport(RecoveryTestCase):
    async def report(self) -> str:
        with patch.object(ai_service, "generate_weekly_journal_analysis", AsyncMock(return_value="разбор")), \
             patch("main.bot.send_message", new_callable=AsyncMock) as send:
            await send_weekly_reports()
        return next(call.kwargs["text"] for call in send.await_args_list if call.kwargs["chat_id"] == USER_ID)

    async def test_counts_done_and_missed_tasks(self):
        now = datetime.now()
        first = await self.issue(now - timedelta(days=5))
        await recovery_tasks.submit_summary(USER_ID, first.id, SUMMARY)
        await self.issue(now - timedelta(days=4))  # будет заменено: не выполнено
        await self.issue(now - timedelta(days=1, hours=2))  # открыто и просрочено
        text = await self.report()
        self.assertIn("Задания после срыва: выполнено <b>1</b> из <b>3</b>, не выполнено <b>2</b>", text)
        self.assertLess(text.index("Задания после срыва"), text.index("Держитесь чистоты"))

    async def test_open_task_in_time_is_not_called_missed(self):
        await self.issue(datetime.now())
        text = await self.report()
        self.assertIn("выполнено <b>0</b> из <b>1</b>", text)
        self.assertNotIn("не выполнено", text)

    async def test_no_line_without_tasks_and_old_closed_ones(self):
        self.assertNotIn("Задания после срыва", await self.report())
        old = await self.issue(datetime.now() - timedelta(days=20))
        await recovery_tasks.submit_summary(USER_ID, old.id, SUMMARY, datetime.now() - timedelta(days=19))
        self.assertNotIn("Задания после срыва", await self.report())


class TestInitDb(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_creates_table_without_rls(self):
        helper = DatabaseHelper("sqlite+aiosqlite:///:memory:")
        try:
            with self.assertNoLogs("database.db_helper", level="WARNING"):
                await helper.init_db()
        finally:
            await helper.dispose()

    async def test_postgres_enables_row_level_security(self):
        connection = MagicMock()
        connection.execute = AsyncMock()
        connection.run_sync = AsyncMock()
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        engine.url = "postgresql+asyncpg://test"
        engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
        engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        helper = DatabaseHelper.__new__(DatabaseHelper)
        helper.engine = engine
        helper.session_factory = MagicMock()
        helper.session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
        helper.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await helper.init_db()
        statements = [str(call.args[0]) for call in connection.execute.await_args_list]
        self.assertEqual(statements, [
            "ALTER TABLE relapse_logs ADD COLUMN IF NOT EXISTS is_late_mark BOOLEAN DEFAULT FALSE",
            "ALTER TABLE recovery_tasks ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE user_plans ENABLE ROW LEVEL SECURITY",
        ])


if __name__ == "__main__":
    unittest.main()
