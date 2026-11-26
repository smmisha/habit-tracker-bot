import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytz
from sqlalchemy import text

from database.db_helper import DatabaseHelper
from database.models import RelapseLog, User, UserPlan
from services import day_report, recovery_tasks, relapse_stats, sos_cards, user_plans
from tests.test_missed_days_and_content import USER_ID, OTHER_ID, DatabaseTestCase

KYIV = pytz.timezone("Europe/Kyiv")
SERVER_ZONES = (pytz.utc, KYIV)
INTERNET = sos_cards.INTERNET_TRIGGER
LONELY = sos_cards.LONELY_TRIGGER


def plans(if_then=(), reason=()):
    return {
        "if_then": [SimpleNamespace(text=item) for item in if_then],
        "reason": [SimpleNamespace(text=item) for item in reason],
    }


def titles(triggers=(), own=None, hour=12) -> list[str]:
    return [card["title"] for card in sos_cards.build_sos_cards(list(triggers), own or plans(), hour)]


class TestSosCards(unittest.TestCase):
    def test_default_cards_by_day(self):
        self.assertEqual(titles(), ["Что со мной сейчас?", "Пережди волну", "Досмотри до конца"])

    def test_first_card_removes_source_at_night(self):
        for hour in (22, 23, 0, 5):
            self.assertEqual(titles(hour=hour)[0], "Убери источник", hour)
        for hour in (6, 12, 21):
            self.assertEqual(titles(hour=hour)[0], "Что со мной сейчас?", hour)

    def test_first_card_follows_most_frequent_trigger(self):
        self.assertEqual(titles([INTERNET, INTERNET, LONELY])[0], "Убери источник")
        self.assertEqual(titles([INTERNET, LONELY, LONELY])[0], "Что со мной сейчас?")
        # Равенство считается: обе причины самые частые
        self.assertEqual(titles([INTERNET, LONELY]), ["Убери источник", "Пережди волну", "Не оставайся один"])
        # Свободный ввод объединяется в одну причину, как в статистике
        self.assertEqual(titles(["Другое: раз", "Другое: два", INTERNET])[0], "Что со мной сейчас?")
        self.assertEqual(titles([None, "", INTERNET])[0], "Убери источник")

    def test_third_card_prefers_own_plans_then_reasons(self):
        own = plans(if_then=["Если ночь, то на кухню", "Если скучно, то пройтись"], reason=["Ради семьи"])
        third = sos_cards.build_sos_cards([LONELY], own, 12)[2]
        self.assertEqual(third["title"], "Мой план")
        self.assertEqual(third["description"], "• Если ночь, то на кухню\n• Если скучно, то пройтись")

        third = sos_cards.build_sos_cards([LONELY], plans(reason=["Ради семьи"]), 12)[2]
        self.assertEqual((third["title"], third["description"]), ("Ради чего", "• Ради семьи"))
        self.assertEqual(titles([LONELY, LONELY, INTERNET])[2], "Не оставайся один")
        self.assertEqual(titles([INTERNET])[2], "Досмотри до конца")

    def test_every_card_has_text_and_source(self):
        for card in sos_cards.build_sos_cards([], plans(if_then=["план"]), 12):
            self.assertTrue(card["title"] and card["description"] and card["source"])
        self.assertIn("не исследование", sos_cards.CARDS["halt"]["source"])
        # Возвращаются копии: правка ответа не меняет каталог
        sos_cards.build_sos_cards([], plans(), 12)[1]["title"] = "другое"
        self.assertEqual(sos_cards.CARDS["wave"]["title"], "Пережди волну")


class TestRelapseTiming(unittest.TestCase):
    def test_parts_and_weekdays_use_user_time(self):
        user = SimpleNamespace(timezone="Europe/Kyiv")
        # Декабрь 2026 по Киеву: 1 декабря — вторник
        local = [(1, 5, 59), (1, 6, 0), (1, 11, 59), (1, 12, 0), (1, 18, 0), (1, 23, 0), (7, 0, 30)]
        for zone in SERVER_ZONES:
            with self.subTest(server=zone.zone), patch.object(recovery_tasks, "as_server_time", zone.localize):
                relapses = [
                    SimpleNamespace(
                        is_late_mark=False,
                        timestamp=KYIV.localize(datetime(2026, 12, *moment)).astimezone(zone).replace(tzinfo=None),
                    )
                    for moment in local
                ]
                relapses.append(SimpleNamespace(is_late_mark=True, timestamp=datetime(2026, 12, 3, 21, 0)))
                # Запись из базы без отметки считается обычной
                relapses.append(SimpleNamespace(is_late_mark=None, timestamp=relapses[0].timestamp))
                timing = relapse_stats.relapse_timing(user, relapses)

                self.assertEqual((timing["total"], timing["late_excluded"]), (8, 1))
                self.assertEqual([row["count"] for row in timing["parts"]], [2, 1, 1, 4])
                self.assertEqual([row["count"] for row in timing["weekdays"]], [1, 7, 0, 0, 0, 0, 0])

    def test_labels_write_ranges_in_words(self):
        labels = [row["label"] for row in relapse_stats.relapse_timing(None, [])["parts"]]
        self.assertEqual(labels, ["Утро, с 6 до 12", "День, с 12 до 18", "Вечер, с 18 до 23", "Ночь, с 23 до 6"])


class TestLateMarkFlag(DatabaseTestCase):
    async def test_only_backdated_relapse_is_flagged(self):
        await self.add_days((3, "missed"))
        await day_report.mark_day(USER_ID, self.ago(3), relapsed=True)
        async with self.session_factory() as session:
            session.add(RelapseLog(user_id=USER_ID, timestamp=datetime.now()))
            await session.commit()
        flags = sorted(relapse.is_late_mark for relapse in await self.rows(RelapseLog))
        self.assertEqual(flags, [False, True])


class TestOldDatabaseUpgrade(unittest.IsolatedAsyncioTestCase):
    async def test_init_db_adds_late_mark_column_to_existing_table(self):
        helper = DatabaseHelper("sqlite+aiosqlite:///:memory:")
        try:
            async with helper.engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE relapse_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT, "
                    "timestamp DATETIME, trigger_reason VARCHAR(500))"
                ))
                await conn.execute(text(
                    "INSERT INTO relapse_logs (user_id, timestamp) VALUES (1, '2026-01-05 21:00:00.000000')"
                ))
            await helper.init_db()
            await helper.init_db()  # повторный запуск ничего не ломает

            async with helper.session_factory() as session:
                session.add(User(id=1, first_name="Old"))
                session.add(RelapseLog(user_id=1, timestamp=datetime.now(), is_late_mark=True))
                await session.commit()
                rows = (await session.execute(
                    text("SELECT is_late_mark FROM relapse_logs ORDER BY id")
                )).scalars().all()
            self.assertEqual(rows, [0, 1])
        finally:
            await helper.dispose()


class TestUserPlans(DatabaseTestCase):
    async def texts(self, kind, user_id=USER_ID):
        async with self.session_factory() as session:
            return [plan.text for plan in (await user_plans.get_plans(session, user_id))[kind]]

    async def test_limits_are_checked_per_kind(self):
        self.assertEqual(await user_plans.add_plan(USER_ID, "if_then", "   "), "empty")
        self.assertEqual(await user_plans.add_plan(USER_ID, "if_then", "я" * 301), "long")
        self.assertEqual(await user_plans.add_plan(USER_ID, "if_then", f"  {'я' * 300}  "), "added")
        for number in range(4):
            self.assertEqual(await user_plans.add_plan(USER_ID, "if_then", f"план {number}"), "added")
        self.assertFalse(await user_plans.has_room(USER_ID, "if_then"))
        self.assertEqual(await user_plans.add_plan(USER_ID, "if_then", "шестой"), "limit")
        self.assertEqual(await user_plans.add_plan(USER_ID, "reason", "Ради семьи"), "added")
        self.assertEqual(len(await self.texts("if_then")), 5)
        self.assertEqual(await user_plans.add_plan(555, "reason", "Нет такого"), "not_found")

    async def test_only_owner_can_delete(self):
        await user_plans.add_plan(USER_ID, "reason", "Ради семьи")
        plan = (await self.rows(UserPlan))[0]
        self.assertFalse(await user_plans.delete_plan(OTHER_ID, plan.id))
        self.assertFalse(await user_plans.delete_plan(USER_ID, 2 ** 40))
        self.assertTrue(await user_plans.delete_plan(USER_ID, plan.id))
        self.assertFalse(await user_plans.delete_plan(USER_ID, plan.id))
        self.assertEqual(await self.texts("reason"), [])

    async def test_task_card_shows_escaped_plans(self):
        await user_plans.add_plan(USER_ID, "if_then", "Если <ночь>, то на кухню")
        await user_plans.add_plan(USER_ID, "reason", "Ради семьи")
        async with self.session_factory() as session:
            task = await recovery_tasks.ensure_task(session, USER_ID)
            await session.commit()
        card = (await recovery_tasks.open_task_card(USER_ID))[0]
        self.assertIn("Мой план</b>\n• Если &lt;ночь&gt;, то на кухню", card)
        self.assertIn("Ради чего</b>\n• Ради семьи", card)
        self.assertNotIn("Мой план", recovery_tasks.task_card(await self.user(), task)[0])
        self.assertNotIn("Мой план", recovery_tasks.task_card(await self.user(), task, plans())[0])


if __name__ == "__main__":
    unittest.main()
