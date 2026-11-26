import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.db_helper import db_helper
from database.models import Base, CheckInLog, JournalEntry, RecoveryTask, RelapseLog, SlipEvent, User, UserPlan
from services import day_report
from services.ai_service import ai_service
from services.bible_service import LOCAL_VERSES, bible_service
from services.scheduler import check_milestone_achievements, send_weekly_reports
from handlers import checkin, common, journal, panic, recovery, tracker
from utils.states import Form

USER_ID = 999001
OTHER_ID = 999002


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)
        self.originals = (db_helper.engine, db_helper.session_factory)
        db_helper.engine, db_helper.session_factory = self.engine, self.session_factory

        async with self.session_factory() as session:
            session.add(User(id=USER_ID, first_name="Test", total_relapses=1, checkin_time="21:00",
                             streak_start=datetime.now() - timedelta(days=10)))
            session.add(User(id=OTHER_ID, first_name="Other"))
            await session.commit()
        async with self.session_factory() as session:
            self.today = day_report.user_today(await session.get(User, USER_ID))

    async def asyncTearDown(self):
        db_helper.engine, db_helper.session_factory = self.originals
        await self.engine.dispose()

    def ago(self, days: int) -> date:
        return self.today - timedelta(days=days)

    async def add_days(self, *pairs, user_id=USER_ID):
        async with self.session_factory() as session:
            for days, status in pairs:
                session.add(CheckInLog(user_id=user_id, checkin_date=self.ago(days), status=status))
            await session.commit()

    async def add_relapse(self, days: int):
        async with self.session_factory() as session:
            session.add(RelapseLog(user_id=USER_ID, timestamp=datetime.combine(self.ago(days), datetime.min.time())))
            await session.commit()

    async def user(self, user_id=USER_ID) -> User:
        async with self.session_factory() as session:
            return await session.get(User, user_id)

    async def rows(self, model, user_id=USER_ID):
        async with self.session_factory() as session:
            return (await session.execute(select(model).where(model.user_id == user_id))).scalars().all()

    async def statuses(self, user_id=USER_ID):
        return {row.checkin_date: row.status for row in await self.rows(CheckInLog, user_id)}


class TestUnmarkedDays(DatabaseTestCase):
    async def test_lists_only_recent_missed_days_without_recorded_relapse(self):
        await self.add_days((20, "missed"), (5, "missed"), (3, "missed"), (2, "clean"), (1, "pending"), (0, "missed"))
        await self.add_relapse(5)
        self.assertEqual(await day_report.get_unmarked_days(USER_ID), [self.ago(3)])

    async def test_mark_clean_works_once(self):
        await self.add_days((3, "missed"))
        self.assertTrue(await day_report.mark_day(USER_ID, self.ago(3), relapsed=False))
        self.assertFalse(await day_report.mark_day(USER_ID, self.ago(3), relapsed=True))
        row = (await self.rows(CheckInLog))[0]
        self.assertEqual((row.status, row.excuse_reason), ("clean", day_report.LATE_MARK_REASON))
        self.assertEqual((await self.user()).total_relapses, 1)
        self.assertEqual(await self.rows(RelapseLog), [])

    async def test_late_relapse_updates_counters_and_moves_streak_only_forward(self):
        await self.add_days((6, "missed"), (4, "missed"))
        self.assertTrue(await day_report.mark_day(USER_ID, self.ago(4), relapsed=True, reason="Стресс / Усталость"))

        user = await self.user()
        self.assertEqual(user.total_relapses, 2)
        self.assertEqual(user.streak_start.date(), self.ago(4))
        self.assertIn(user.awarded_milestones, ("1,3", "1"))
        relapse = (await self.rows(RelapseLog))[0]
        self.assertEqual((relapse.timestamp.date(), relapse.trigger_reason), (self.ago(4), "Стресс / Усталость"))
        slip = (await self.rows(SlipEvent))[0]
        self.assertFalse(slip.notified_partner)

        self.assertTrue(await day_report.mark_day(USER_ID, self.ago(6), relapsed=True))
        user = await self.user()
        self.assertEqual(user.total_relapses, 3)
        self.assertEqual(user.streak_start.date(), self.ago(4))

    async def test_cannot_mark_today_future_or_foreign_days(self):
        await self.add_days((0, "missed"), (-1, "missed"))
        await self.add_days((3, "missed"), user_id=OTHER_ID)
        for days in (0, -1, 3):
            with self.subTest(days=days):
                self.assertFalse(await day_report.mark_day(USER_ID, self.ago(days), relapsed=True))
        self.assertEqual(await self.statuses(OTHER_ID), {self.ago(3): "missed"})
        self.assertEqual((await self.user()).total_relapses, 1)

    async def test_pause_days_become_unmarked_except_recorded_relapse(self):
        await self.add_days((5, "clean"))
        await self.add_relapse(3)
        await day_report.add_missed_days_for_pause(USER_ID)
        await day_report.add_missed_days_for_pause(USER_ID)
        self.assertEqual(await day_report.get_unmarked_days(USER_ID), [self.ago(4), self.ago(2), self.ago(1)])
        self.assertEqual(len(await self.rows(CheckInLog)), 4)

    async def test_new_user_gets_no_pause_days(self):
        await day_report.add_missed_days_for_pause(USER_ID)
        self.assertEqual(await self.rows(CheckInLog), [])


class TestDayReportHandlers(DatabaseTestCase):
    def callback(self, data=""):
        callback = MagicMock()
        callback.data = data
        callback.from_user.id = USER_ID
        callback.answer = AsyncMock()
        callback.message.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        return callback

    async def test_buttons_walk_through_days_and_finish_with_report(self):
        await self.add_days((3, "missed"), (2, "missed"))

        first = self.callback(f"day:clean:{self.ago(3).isoformat()}")
        await checkin.process_day_report(first)
        keyboard = first.message.edit_text.await_args.kwargs["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, f"day:clean:{self.ago(2).isoformat()}")

        ask = self.callback(f"day:relapse:{self.ago(2).isoformat()}")
        await checkin.process_day_report(ask)
        self.assertEqual((await self.statuses())[self.ago(2)], "missed")

        why = self.callback(f"day:why:{self.ago(2).isoformat()}:web")
        await checkin.process_day_report(why)
        text = why.message.edit_text.await_args.args[0]
        self.assertIn("Отчет за 30 дней", text)
        self.assertIn("старейшине", text)
        self.assertEqual(await self.statuses(), {self.ago(3): "clean", self.ago(2): "relapsed"})

    async def test_malformed_buttons_change_nothing(self):
        await self.add_days((2, "missed"))
        day = self.ago(2).isoformat()
        for data in ("day:clean:not-a-date", "day:clean", f"day:why:{day}:hack", f"day:why:{day}"):
            with self.subTest(data=data):
                await checkin.process_day_report(self.callback(data))
        self.assertEqual(await self.statuses(), {self.ago(2): "missed"})

    async def test_clean_checkin_offers_unmarked_days(self):
        await self.add_days((2, "missed"), (0, "pending"))
        callback = self.callback("checkin_clean")
        with patch.object(ai_service, "generate_clean_checkin_response", AsyncMock(return_value="Молодец")):
            await checkin.process_checkin_clean(callback)
        self.assertIn("Дни без отметки", callback.message.answer.await_args.args[0])
        self.assertEqual((await self.statuses())[self.ago(2)], "missed")


class TestScheduledMessages(DatabaseTestCase):
    async def test_weekly_report_counts_unmarked_and_escapes_ai_text(self):
        await self.add_days((1, "clean"), (2, "missed"), (3, "missed"), (9, "missed"))
        with patch.object(ai_service, "generate_weekly_journal_analysis", AsyncMock(return_value="сон < 5 ч & стресс")), \
             patch("main.bot.send_message", new_callable=AsyncMock) as send:
            await send_weekly_reports()
        texts = [call.kwargs["text"] for call in send.await_args_list if call.kwargs["chat_id"] == USER_ID]
        self.assertIn("Без отметки: <b>2</b>", texts[0])
        self.assertNotIn("Забыл", texts[0])
        self.assertIn("сон &lt; 5 ч &amp; стресс", texts[1])

    async def test_milestone_message_is_escaped_and_promises_nothing_extra(self):
        async with self.session_factory() as session:
            (await session.get(User, USER_ID)).streak_start = datetime.now() - timedelta(days=1, hours=1)
            (await session.get(User, OTHER_ID)).is_active = False
            await session.commit()
        with patch.object(ai_service, "generate_milestone_reward_suggestion", AsyncMock(return_value="чай <и> книга")), \
             patch("main.bot.send_photo", new_callable=AsyncMock) as photo, \
             patch("main.bot.send_message", new_callable=AsyncMock) as message:
            await check_milestone_achievements()
        call = photo.await_args or message.await_args
        text = call.kwargs.get("caption") or call.kwargs.get("text")
        self.assertIn("чай &lt;и&gt; книга", text)
        self.assertNotIn("вопросов", text)


class TestCuratedSpiritualTexts(unittest.IsolatedAsyncioTestCase):
    async def test_study_materials_never_use_ai(self):
        with patch.object(ai_service, "api_key", "configured"), \
             patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as gemini:
            for kind in ("sexting", "porn", "premarital_sex", "general"):
                for round_number in (1, 2):
                    data = await ai_service.generate_spiritual_study_materials(temptation_type=kind, round=round_number)
                    self.assertTrue(data["spiritual_thought"])
        gemini.assert_not_awaited()

    async def test_notes_about_masturbation_lead_to_porn(self):
        data = await ai_service.generate_spiritual_study_materials(user_notes="Тянет к мастурбации")
        self.assertEqual(data["temptation_types"], ["porn"])
        self.assertEqual([item["url"].rsplit("/", 1)[1] for item in data["materials"]], ["2019447"])

    async def test_empty_selection_falls_back_to_porn(self):
        for notes in (None, "рука болит после работы"):
            with self.subTest(notes=notes):
                data = await ai_service.generate_spiritual_study_materials(user_notes=notes)
                self.assertEqual((data["temptation_type"], data["temptation_types"]), ("porn", ["porn"]))

    async def test_type_from_cached_old_app_is_treated_as_porn(self):
        data = await ai_service.generate_spiritual_study_materials(temptation_types=["sexting", "masturbation", "porn"])
        self.assertEqual(data["temptation_types"], ["sexting", "porn"])

    async def test_reflection_feedback_is_fixed_even_when_ai_writes_its_own(self):
        text = "Запомнилось из Притчи 4:23, что сердце надо беречь с первых секунд."
        reply = '{"accepted": true, "feedback": "выдуманный стих"}'
        with patch.object(ai_service, "api_key", "configured"), \
             patch.object(ai_service, "_call_gemini", AsyncMock(return_value=reply)):
            result = await ai_service.evaluate_article_reflection("Статья", text)
        self.assertTrue(result["accepted"])
        self.assertNotIn("выдуманный", result["feedback"])

    async def test_daily_verse_falls_back_to_local_list_without_ai(self):
        with patch("aiohttp.ClientSession.get", side_effect=OSError("offline")), \
             patch("aiohttp.ClientSession.post") as post:
            verse = await bible_service.fetch_daily_text()
        self.assertIn(verse, LOCAL_VERSES)
        post.assert_not_called()
        self.assertNotIn("Притчи 24:16", [item["citation"] for item in LOCAL_VERSES])


class RecordingSession(BaseSession):
    """Вместо Telegram: запоминает исходящие запросы"""

    def __init__(self):
        super().__init__()
        self.sent = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        return None

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def close(self):
        pass


class TestRouting(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        # Роутер можно подключить только к одному диспетчеру, поэтому он общий на класс
        cls.dp = Dispatcher(storage=MemoryStorage())
        for module in (common, tracker, checkin, panic, journal, recovery):
            cls.dp.include_router(module.router)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.session = RecordingSession()
        self.bot = Bot("123456:TEST-FAKE-TOKEN-FOR-LOCAL-TESTS", session=self.session,
                       default=DefaultBotProperties(parse_mode="HTML"))
        self.state = self.dp.fsm.get_context(self.bot, USER_ID, USER_ID)
        await self.state.clear()

    async def send(self, first_name="Test", **content):
        message = Message(
            message_id=1, date=datetime.now(), chat=Chat(id=USER_ID, type="private"),
            from_user=TgUser(id=USER_ID, is_bot=False, first_name=first_name), **content,
        )
        self.session.sent.clear()
        await self.dp.feed_update(self.bot, Update(update_id=1, message=message))
        return "\n".join(getattr(method, "text", None) or "" for method in self.session.sent)

    async def test_command_during_trigger_input_opens_sos_instead_of_recording(self):
        await self.state.set_state(Form.waiting_for_relapse_trigger_other)
        reply = await self.send(text="/panic")
        self.assertIn("РЕЖИМ SOS", reply)
        self.assertEqual(await self.rows(RelapseLog), [])

    async def test_photo_during_trigger_input_asks_for_text(self):
        await self.state.set_state(Form.waiting_for_relapse_trigger_other)
        reply = await self.send(photo=[PhotoSize(file_id="a", file_unique_id="b", width=1, height=1)])
        self.assertIn("Напиши причину текстом", reply)
        self.assertEqual(await self.rows(RelapseLog), [])
        self.assertEqual(await self.state.get_state(), Form.waiting_for_relapse_trigger_other.state)

    async def test_leaving_trigger_input_by_command_does_not_record_next_message(self):
        for command in ("/start", "/covenant", "/settings", "/streak"):
            with self.subTest(command=command):
                await self.state.set_state(Form.waiting_for_relapse_trigger_other)
                await self.send(text=command)
                await self.send(text="привет")
                self.assertIsNone(await self.state.get_state())
                self.assertEqual(await self.rows(RelapseLog), [])

    async def test_choosing_another_trigger_button_ends_text_input(self):
        await self.state.set_state(Form.waiting_for_relapse_trigger_other)
        user = TgUser(id=USER_ID, is_bot=False, first_name="Test")
        message = Message(message_id=2, date=datetime.now(), chat=Chat(id=USER_ID, type="private"),
                          from_user=user, text="Выбери причину")
        callback = CallbackQuery(id="1", from_user=user, chat_instance="x",
                                 data="relapse_trigger_bored", message=message)
        await self.dp.feed_update(self.bot, Update(update_id=2, callback_query=callback))
        await self.send(text="привет")
        self.assertEqual([r.trigger_reason for r in await self.rows(RelapseLog)], ["Скука / Безделье"])

    async def test_long_trigger_text_is_saved_within_column_limit(self):
        await self.state.set_state(Form.waiting_for_relapse_trigger_other)
        await self.send(text="а" * 900)
        reason = (await self.rows(RelapseLog))[0].trigger_reason
        self.assertEqual(len(reason), len("Другое: ") + 400)

    async def test_settings_input_lets_commands_through_and_rejects_non_text(self):
        for state in (Form.waiting_for_timezone, Form.waiting_for_checkin_time):
            with self.subTest(state=state.state):
                await self.state.set_state(state)
                reply = await self.send(photo=[PhotoSize(file_id="a", file_unique_id="b", width=1, height=1)])
                self.assertIn("ответьте текстом", reply)
                reply = await self.send(text="/panic")
                self.assertIn("РЕЖИМ SOS", reply)

    async def test_user_text_is_escaped(self):
        async with self.session_factory() as session:
            session.add(JournalEntry(user_id=USER_ID, entry_date=date.today(), content="сон <5 часов"))
            await session.commit()
        self.assertIn("сон &lt;5 часов", await self.send(text="/journal"))
        self.assertIn("&lt;Имя&gt;", await self.send(first_name="<Имя>", text="/start"))

    async def test_start_after_pause_resumes_and_asks_about_days(self):
        await self.add_days((4, "clean"))
        async with self.session_factory() as session:
            (await session.get(User, USER_ID)).is_active = False
            await session.commit()
        reply = await self.send(text="/start")
        self.assertIn("Напоминания снова включены", reply)
        self.assertIn("Осталось отметить: 3", reply)
        self.assertTrue((await self.user()).is_active)

    async def press(self, data):
        """Нажатие кнопки под сообщением бота"""
        user = TgUser(id=USER_ID, is_bot=False, first_name="Test")
        message = Message(message_id=2, date=datetime.now(), chat=Chat(id=USER_ID, type="private"),
                          from_user=user, text="Сообщение бота")
        callback = CallbackQuery(id="1", from_user=user, chat_instance="x", data=data, message=message)
        self.session.sent.clear()
        await self.dp.feed_update(self.bot, Update(update_id=2, callback_query=callback))
        return "\n".join(getattr(method, "text", None) or "" for method in self.session.sent)

    async def relapse_and_start_writing(self) -> RecoveryTask:
        await self.press("relapse_trigger_web")
        task = (await self.rows(RecoveryTask))[0]
        self.assertIn("Напиши пересказ одним сообщением", await self.press(f"task:write:{task.id}"))
        self.assertEqual(await self.state.get_state(), Form.waiting_for_recovery_summary.state)
        return task

    async def test_cause_button_sends_confirmation_then_task(self):
        reply = await self.press("relapse_trigger_web")
        self.assertIn("выполни задание ниже", reply)
        self.assertLess(reply.index("Счетчик сброшен"), reply.index("Задание на сутки"))
        self.assertEqual([task.status for task in await self.rows(RecoveryTask)], ["open"])

    async def test_other_reason_text_creates_task(self):
        await self.state.set_state(Form.waiting_for_relapse_trigger_other)
        reply = await self.send(text="не спалось")
        self.assertIn("Задание на сутки", reply)
        self.assertEqual(len(await self.rows(RecoveryTask)), 1)

    async def test_summary_in_chat_is_checked_and_saved(self):
        task = await self.relapse_and_start_writing()

        self.assertIn("Пока коротко", await self.send(text="Статья хорошая."))
        self.assertEqual(await self.state.get_state(), Form.waiting_for_recovery_summary.state)
        photo = [PhotoSize(file_id="a", file_unique_id="b", width=1, height=1)]
        self.assertIn("Напиши пересказ текстом", await self.send(photo=photo))

        summary = ("Статья показывает, что ловушка начинается с одного взгляда. Запомнился совет сразу закрывать "
                   "экран, молиться и менять занятие. Беру себе правило: телефон ночует на кухне, а вечером "
                   "я не листаю ленту в одиночестве и звоню другу, когда тянет.")
        reply = await self.send(text=summary)
        self.assertIn("задание выполнено. Копия — в дневнике.", reply)
        self.assertIn("Хочешь записать план на следующий раз?", reply)
        self.assertEqual(await self.state.get_state(), Form.waiting_for_plan.state)
        stored = (await self.rows(RecoveryTask))[0]
        self.assertEqual((stored.id, stored.status, stored.summary), (task.id, "done", summary))
        self.assertIn(summary, (await self.rows(JournalEntry))[0].content)
        await self.press("plan:skip")
        self.assertIn("уже закрыто", await self.press(f"task:write:{task.id}"))
        self.assertIsNone(await self.state.get_state())

    _SUMMARY = (
        "Статья показывает, что ловушка начинается с одного взгляда. Запомнился совет сразу закрывать "
        "экран, молиться и менять занятие. Беру себе правило: телефон ночует на кухне, а вечером "
        "я не листаю ленту в одиночестве и звоню другу, когда тянет."
    )

    async def finish_summary(self) -> str:
        await self.relapse_and_start_writing()
        return await self.send(text=self._SUMMARY)

    async def test_plan_after_summary_is_checked_and_saved(self):
        await self.finish_summary()
        photo = [PhotoSize(file_id="a", file_unique_id="b", width=1, height=1)]
        self.assertIn("Напиши план текстом", await self.send(photo=photo))
        self.assertIn("уложись в 300", await self.send(text="я" * 301))
        self.assertEqual(await self.state.get_state(), Form.waiting_for_plan.state)

        reply = await self.send(text="Если <ночь>, то выхожу на кухню")
        self.assertIn("План сохранён: «Если &lt;ночь&gt;, то выхожу на кухню»", reply)
        self.assertIsNone(await self.state.get_state())
        stored = [(plan.kind, plan.text) for plan in await self.rows(UserPlan)]
        self.assertEqual(stored, [("if_then", "Если <ночь>, то выхожу на кухню")])

    async def test_plan_question_can_be_skipped_or_left_by_command(self):
        await self.finish_summary()
        self.assertIn("План можно записать позже", await self.press("plan:skip"))
        self.assertIsNone(await self.state.get_state())
        await self.send(text="обычное сообщение")

        await self.state.set_state(Form.waiting_for_plan)
        self.assertIn("РЕЖИМ SOS", await self.send(text="/panic"))
        await self.send(text="обычное сообщение")
        await self.state.set_state(Form.waiting_for_plan)
        self.assertIn("Действие отменено", await self.send(text="/cancel"))
        self.assertEqual(await self.rows(UserPlan), [])

    async def test_old_skip_button_keeps_other_input(self):
        await self.state.set_state(Form.waiting_for_timezone)
        self.assertEqual(await self.press("plan:skip"), "")
        self.assertEqual(await self.state.get_state(), Form.waiting_for_timezone.state)

    async def test_no_plan_question_when_five_plans_exist(self):
        async with self.session_factory() as session:
            session.add_all(UserPlan(user_id=USER_ID, kind="if_then", text=f"план {i}") for i in range(5))
            await session.commit()
        reply = await self.finish_summary()
        self.assertIn("задание выполнено", reply)
        self.assertNotIn("Хочешь записать план", reply)
        self.assertIsNone(await self.state.get_state())

    async def test_task_message_includes_plans(self):
        async with self.session_factory() as session:
            session.add(UserPlan(user_id=USER_ID, kind="if_then", text="Если тянет, то на кухню"))
            await session.commit()
        self.assertIn("Если тянет, то на кухню", await self.press("relapse_trigger_web"))

    async def test_commands_leave_summary_input(self):
        task = await self.relapse_and_start_writing()
        self.assertIn("РЕЖИМ SOS", await self.send(text="/panic"))
        self.assertIsNone(await self.state.get_state())
        for cancel in ("/cancel", "отмена"):
            await self.press(f"task:write:{task.id}")
            self.assertIn("Действие отменено", await self.send(text=cancel))
        stored = (await self.rows(RecoveryTask))[0]
        self.assertEqual((stored.status, stored.summary), ("open", None))
        self.assertEqual(await self.rows(JournalEntry), [])

    async def test_foreign_task_button_does_not_start_input(self):
        async with self.session_factory() as session:
            session.add(RecoveryTask(user_id=OTHER_ID, created_at=datetime.now(),
                                     due_at=datetime.now() + timedelta(hours=24),
                                     article_url="https://wol.jw.org/ru/", article_title="Чужая"))
            await session.commit()
        foreign = (await self.rows(RecoveryTask, OTHER_ID))[0]
        for data in (f"task:write:{foreign.id}", "task:write:abc"):
            with self.subTest(data=data):
                reply = await self.press(data)
                self.assertIn("уже закрыто", reply)
                self.assertNotIn("Чужая", reply)
                self.assertIsNone(await self.state.get_state())

    async def test_settings_have_no_dead_options(self):
        reply = await self.send(text="/settings")
        self.assertNotIn("Забыл", reply)
        self.assertNotIn("наград", reply)


if __name__ == "__main__":
    unittest.main()
