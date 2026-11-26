"""Дни без отметки: поиск, отметка задним числом и короткий отчет после нее."""
from datetime import date, datetime, time, timedelta, timezone

import pytz
from sqlalchemy import select, update

from database.db_helper import db_helper
from database.models import CheckInLog, RelapseLog, SlipEvent, User
from services import recovery_tasks

# За сколько прошедших дней бот предлагает отметить пропуски
REPORT_WINDOW_DAYS = 14
LATE_MARK_REASON = "Отмечено позже"
MILESTONES = (1, 3, 7, 14, 30, 90)


def user_today(user: User) -> date:
    """Сегодняшняя дата в часовом поясе пользователя"""
    try:
        return datetime.now(pytz.timezone(user.timezone)).date()
    except pytz.UnknownTimeZoneError:
        return date.today()


async def _relapse_dates(session, user_id: int, since: date) -> set[date]:
    result = await session.execute(
        select(RelapseLog.timestamp).where(
            RelapseLog.user_id == user_id,
            RelapseLog.timestamp >= datetime.combine(since, time.min),
        )
    )
    return {moment.date() for moment in result.scalars().all()}


async def get_unmarked_days(user_id: int) -> list[date]:
    """Прошедшие дни без отметки (status="missed"), от старых к новым"""
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return []

        today = user_today(user)
        since = today - timedelta(days=REPORT_WINDOW_DAYS)
        result = await session.execute(
            select(CheckInLog.checkin_date).where(
                CheckInLog.user_id == user_id,
                CheckInLog.status == "missed",
                CheckInLog.checkin_date >= since,
                CheckInLog.checkin_date < today,
            )
        )
        # День с уже записанным срывом повторно не спрашиваем
        return sorted(set(result.scalars().all()) - await _relapse_dates(session, user_id, since))


async def add_missed_days_for_pause(user_id: int) -> None:
    """Пока бот стоял на паузе, чек-ины не создавались: добавляет эти дни как неотмеченные"""
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return

        today = user_today(user)
        since = today - timedelta(days=REPORT_WINDOW_DAYS)
        result = await session.execute(
            select(CheckInLog.checkin_date).where(CheckInLog.user_id == user_id)
        )
        known = set(result.scalars().all())
        if not known:
            return

        relapsed = await _relapse_dates(session, user_id, since)
        day = max(since, min(known))
        while day < today:
            if day not in known and day not in relapsed:
                session.add(CheckInLog(user_id=user_id, checkin_date=day, status="missed"))
            day += timedelta(days=1)
        await session.commit()


def _moment_of_day(user: User, day: date) -> tuple[datetime, datetime]:
    """
    Время срыва задним числом: час отчета в указанный день.
    Возвращает (время сервера как у datetime.now(), то же в UTC), оба без tzinfo.
    """
    hour, minute = map(int, user.checkin_time.split(":"))
    try:
        user_tz = pytz.timezone(user.timezone)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.timezone("Europe/Kyiv")

    aware = user_tz.localize(datetime.combine(day, time(hour, minute)))
    server = aware.astimezone().replace(tzinfo=None)
    if server.date() != day:
        # Ночной час отчета при переводе в часовой пояс сервера уезжает на соседний день
        server = datetime.combine(day, time(12, 0))
    return min(server, datetime.now()), aware.astimezone(timezone.utc).replace(tzinfo=None)


async def mark_day(user_id: int, day: date, relapsed: bool, reason: str | None = None) -> bool:
    """
    Отмечает день из списка неотмеченных.
    Возвращает False, если день недоступен или уже отмечен (например, двойное нажатие).
    """
    if day not in await get_unmarked_days(user_id):
        return False

    async with db_helper.session_factory() as session:
        # Атомарное обновление: из двух одновременных нажатий сработает только одно
        result = await session.execute(
            update(CheckInLog)
            .where(
                CheckInLog.user_id == user_id,
                CheckInLog.checkin_date == day,
                CheckInLog.status == "missed",
            )
            .values(
                status="relapsed" if relapsed else "clean",
                excuse_reason=None if relapsed else LATE_MARK_REASON,
                timestamp=datetime.now(),
            )
        )
        if not result.rowcount:
            return False

        user = await session.get(User, user_id)
        user.consecutive_missed_checkins = 0

        if relapsed:
            happened_at, happened_at_utc = _moment_of_day(user, day)
            session.add(RelapseLog(
                user_id=user_id, timestamp=happened_at, trigger_reason=reason, is_late_mark=True
            ))
            session.add(SlipEvent(user_id=user_id, occurred_at=happened_at_utc, notified_partner=False))
            user.total_relapses += 1
            # Счетчик только сдвигается вперед: более поздний срыв не отменяется более ранним
            if user.streak_start is None or happened_at > user.streak_start:
                user.streak_start = happened_at
                passed_days = (datetime.now() - happened_at).days
                # Уже пройденные вехи помечаем выданными, чтобы не слать медали задним числом
                user.awarded_milestones = ",".join(str(m) for m in MILESTONES if m <= passed_days)
            # Срок задания считается от момента отметки, а не от дня срыва
            await recovery_tasks.ensure_task(session, user_id)

        await session.commit()
        return True


async def build_report_summary(user_id: int, days: int = 30) -> str:
    """Короткий отчет за последние дни после отметки пропусков"""
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return ""

        since = user_today(user) - timedelta(days=days - 1)
        result = await session.execute(
            select(CheckInLog.checkin_date, CheckInLog.status).where(
                CheckInLog.user_id == user_id, CheckInLog.checkin_date >= since
            )
        )
        rows = result.all()
        relapsed = await _relapse_dates(session, user_id, since)
        relapsed |= {day for day, status in rows if status == "relapsed"}
        clean = {day for day, status in rows if status == "clean"} - relapsed
        unmarked = {day for day, status in rows if status == "missed"} - relapsed - clean
        streak_days = max(0, (datetime.now() - user.streak_start).days)

    return (
        f"📊 <b>Отчет за {days} дней</b>\n"
        f"☀️ Чистых: <b>{len(clean)}</b>\n"
        f"⚠️ Дней со срывом: <b>{len(relapsed)}</b>\n"
        f"❔ Без отметки: <b>{len(unmarked)}</b>\n"
        f"⏳ Текущий стрик: <b>{streak_days}</b> дн."
    )
