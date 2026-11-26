"""Задание после срыва: прочитать статью о порнографии и за сутки написать пересказ."""
import html
import logging
import math
import re
from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import quote

import pytz
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, or_, select, update

from database.db_helper import db_helper
from database.models import JournalEntry, RecoveryTask, User
from services import user_plans
from services.ai_service import GENERIC_REFLECTION_PHRASES

logger = logging.getLogger(__name__)

TASK_DURATION = timedelta(hours=24)

MIN_SUMMARY_LENGTH = 200
# Отсекает набор букв и одну фразу, повторенную много раз
MIN_DISTINCT_WORDS = 15
MAX_SUMMARY_LENGTH = 4096
JOURNAL_LIMIT = 2000

# Напоминания не приходят с 23:00 до 08:00 по времени пользователя
QUIET_FROM_HOUR = 23
QUIET_UNTIL_HOUR = 8

_WOL = "https://wol.jw.org/ru/wol/d/r2/lp-u/"
# Проверены на wol.jw.org и jw.org 26.11.2026; порядок задает очередность выдачи
ARTICLES = (
    ("Как не угодить в ловушку Сатаны", _WOL + "2019447"),
    ("Как держаться в стороне от порнографии?", _WOL + "102007444"),
    ("Зачем избегать порнографии?", _WOL + "1102008137"),
    ("Порнография: безобидное развлечение или отрава?", _WOL + "2013562"),
    ("Я много раз терпел неудачу, прежде чем смог победить себя", _WOL + "2016256"),
    ("Раз и навсегда снимите старую личность", _WOL + "2017525"),
    ("Чем опасна порнография", _WOL + "102003523"),
    (
        "Что говорит Библия о порнографии? Предосудителен ли киберсекс?",
        # Кириллица в адресе кодируется, чтобы Telegram принял ссылку в кнопке
        "https://www.jw.org/ru/" + quote("библейские-учения/вопросы/что-говорит-библия-о-порнографии") + "/",
    ),
    ("Что, если я пристрастился к порнографии?", _WOL + "502012510"),
)

DEADLINE_TEXT = (
    "⌛ Срок задания вышел. Оно остаётся открытым: прочитай статью и напиши пересказ, "
    "когда сможешь — это всё ещё важно."
)

SUBMIT_ERRORS = {
    "not_found": "Задание не найдено.",
    "closed": "Это задание уже закрыто.",
    "short": "Пока коротко. Добавь ещё пару предложений: о чём статья и что ты из неё берёшь.",
    "long": "Пересказ слишком длинный: уложись в 4096 символов.",
}


class SubmitResult(NamedTuple):
    status: str  # "done" или ключ из SUBMIT_ERRORS
    late: bool = False
    in_journal: bool = False


def server_now() -> datetime:
    """Время сервера без tzinfo, как во всей базе"""
    return datetime.now()


def as_server_time(moment: datetime) -> datetime:
    """Добавляет к времени из базы часовой пояс сервера"""
    return moment.astimezone()


def to_user_time(user: User, moment: datetime) -> datetime:
    try:
        user_tz = pytz.timezone(user.timezone)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.timezone("Europe/Kyiv")
    return as_server_time(moment).astimezone(user_tz)


async def get_open_task(session, user_id: int) -> RecoveryTask | None:
    """Последнее открытое задание пользователя"""
    result = await session.execute(
        select(RecoveryTask)
        .where(RecoveryTask.user_id == user_id, RecoveryTask.status == "open")
        .order_by(RecoveryTask.id.desc())
    )
    return result.scalars().first()


async def get_open_task_id(user_id: int) -> int | None:
    async with db_helper.session_factory() as session:
        task = await get_open_task(session, user_id)
        return task.id if task else None


async def _next_article(session, user_id: int) -> tuple[str, str]:
    """Первая еще не выданная статья, а когда выданы все — та, что выдавалась давнее всего"""
    result = await session.execute(
        select(RecoveryTask.article_url, func.max(RecoveryTask.id))
        .where(RecoveryTask.user_id == user_id)
        .group_by(RecoveryTask.article_url)
    )
    last_issued = dict(result.all())
    return min(ARTICLES, key=lambda article: last_issued.get(article[1], 0))


async def ensure_task(session, user_id: int, now: datetime | None = None) -> RecoveryTask:
    """
    Задание после срыва в той же транзакции, что и запись срыва (commit делает вызывающий).
    Пока открытое задание в сроке, новое не создается; просроченное закрывается как "missed".
    """
    now = now or server_now()
    result = await session.execute(
        select(RecoveryTask)
        .where(RecoveryTask.user_id == user_id, RecoveryTask.status == "open")
        .order_by(RecoveryTask.id.desc())
    )
    open_tasks = result.scalars().all()
    for task in open_tasks:
        if task.due_at > now:
            return task
    for task in open_tasks:
        task.status = "missed"

    title, url = await _next_article(session, user_id)
    task = RecoveryTask(
        user_id=user_id,
        created_at=now,
        due_at=now + TASK_DURATION,
        article_title=title,
        article_url=url,
    )
    session.add(task)
    return task


def task_keyboard(task: RecoveryTask) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Открыть статью", url=task.article_url)],
        [InlineKeyboardButton(text="✍️ Написать пересказ", callback_data=f"task:write:{task.id}")],
    ])


def task_card(user: User, task: RecoveryTask, plans: dict | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Сообщение с заданием, личными планами (результат user_plans.get_plans) и кнопки"""
    deadline = to_user_time(user, task.due_at).strftime("%H:%M, %d.%m")
    text = (
        "📖 <b>Задание на сутки</b>\n"
        f"Прочитай статью «{html.escape(task.article_title)}» и своими словами напиши пересказ: "
        "главную мысль, пример или стих, которые тебя задели.\n"
        f"Срок: до {deadline} (по твоему времени)."
    )
    own = user_plans.plans_block(plans) if plans else ""
    if own:
        text += f"\n\n{own}"
    return text, task_keyboard(task)


async def open_task_card(user_id: int, task_id: int | None = None):
    """Карточка открытого задания (или None, если такого уже нет)"""
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        task = await get_open_task(session, user_id)
        if not user or not task or (task_id is not None and task.id != task_id):
            return None
        return task_card(user, task, await user_plans.get_plans(session, user_id))


def task_payload(user: User, task: RecoveryTask, now: datetime | None = None) -> dict:
    """Открытое задание для Mini App"""
    left = (task.due_at - (now or server_now())).total_seconds()
    return {
        "id": task.id,
        "title": task.article_title,
        "url": task.article_url,
        "due_at": to_user_time(user, task.due_at).isoformat(),
        "hours_left": max(0, math.ceil(left / 3600)),
        "overdue": left <= 0,
    }


def is_summary_acceptable(summary: str) -> bool:
    """Не короче порога и не набор шаблонных фраз. ИИ пересказ не оценивает."""
    text = " ".join(summary.split())
    if len(text) < MIN_SUMMARY_LENGTH:
        return False
    words = " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())
    for phrase in GENERIC_REFLECTION_PHRASES:
        words = words.replace(phrase, " ")
    return len({word for word in words.split() if any(c.isalpha() for c in word)}) >= MIN_DISTINCT_WORDS


async def _copy_to_journal(session, user_id: int, title: str, summary: str, now: datetime) -> bool:
    """Копия пересказа в дневнике за сегодня. Обрезается только копия, прежние записи не трогаются."""
    header = f"📖 Пересказ после срыва: «{title}»\n"
    result = await session.execute(
        select(JournalEntry).where(JournalEntry.user_id == user_id, JournalEntry.entry_date == now.date())
    )
    entry = result.scalars().first()
    if not entry:
        session.add(JournalEntry(user_id=user_id, entry_date=now.date(), content=(header + summary)[:JOURNAL_LIMIT]))
        return True

    previous = entry.content.rstrip() + "\n\n"
    room = JOURNAL_LIMIT - len(previous)
    if room <= len(header):
        return False
    entry.content = previous + (header + summary)[:room]
    entry.created_at = now
    return True


async def submit_summary(user_id: int, task_id: int, summary: str, now: datetime | None = None) -> SubmitResult:
    """Принимает пересказ из чата или Mini App"""
    now = now or server_now()
    # Номер вне диапазона integer в Postgres вызвал бы ошибку запроса
    if not 0 < task_id < 2 ** 31:
        return SubmitResult("not_found")

    async with db_helper.session_factory() as session:
        task = await session.get(RecoveryTask, task_id)
        if not task or task.user_id != user_id:
            return SubmitResult("not_found")
        if task.status != "open":
            return SubmitResult("closed")

        text = summary.strip()
        if len(text) > MAX_SUMMARY_LENGTH:
            return SubmitResult("long")
        if not is_summary_acceptable(text):
            return SubmitResult("short")

        late = now > task.due_at
        # Атомарное обновление: из двух одновременных отправок сработает только одна
        result = await session.execute(
            update(RecoveryTask)
            .where(RecoveryTask.id == task_id, RecoveryTask.status == "open")
            .values(status="done", completed_at=now, summary=text)
        )
        if not result.rowcount:
            return SubmitResult("closed")

        in_journal = await _copy_to_journal(session, user_id, task.article_title, text, now)
        user = await session.get(User, user_id)
        user.consecutive_missed_checkins = 0
        await session.commit()

    return SubmitResult("done", late=late, in_journal=in_journal)


def _time_left_phrase(left: timedelta) -> str:
    # Запас в 10 минут: запуск раз в 5 минут не должен превращать 12 часов в 11
    hours = int((left + timedelta(minutes=10)) // timedelta(hours=1))
    if hours < 1:
        return "осталось меньше часа"
    if hours % 10 == 1 and hours % 100 != 11:
        return f"остался {hours} час"
    if 2 <= hours % 10 <= 4 and not 12 <= hours % 100 <= 14:
        return f"осталось {hours} часа"
    return f"осталось {hours} часов"


async def send_task_reminders(bot, now: datetime | None = None) -> None:
    """
    Напоминания за 12 и 3 часа и одно сообщение об истекшем сроке.
    Все состояние хранится в таблице. За один запуск задание получает не больше одного сообщения:
    после сна сервера или тихих часов отправляется только самое позднее из пропущенных.
    """
    now = now or server_now()
    async with db_helper.session_factory() as session:
        result = await session.execute(
            select(RecoveryTask, User)
            .join(User, User.id == RecoveryTask.user_id)
            .where(RecoveryTask.status == "open", User.is_active == True)
        )
        for task, user in result.all():
            try:
                hour = to_user_time(user, now).hour
                if hour >= QUIET_FROM_HOUR or hour < QUIET_UNTIL_HOUR:
                    continue

                left = task.due_at - now
                stage = None
                if left <= timedelta(0):
                    if task.deadline_notified:
                        continue
                    text = DEADLINE_TEXT
                else:
                    stage = 2 if left <= timedelta(hours=3) else 1 if left <= timedelta(hours=12) else 0
                    if stage <= task.reminders_sent:
                        continue
                    text = (
                        f"⏰ До конца срока задания {_time_left_phrase(left)}. "
                        f"Статья: «{html.escape(task.article_title)}»."
                    )

                await bot.send_message(chat_id=user.id, text=text, reply_markup=task_keyboard(task))
                if stage is None:
                    task.deadline_notified = True
                else:
                    task.reminders_sent = stage
                await session.commit()
            except Exception as e:
                logger.error(f"Не удалось отправить напоминание о задании {task.id}: {e}")


async def weekly_summary_line(session, user_id: int, since: datetime, now: datetime | None = None) -> str:
    """Строка недельного отчета: задания за неделю и все еще открытые"""
    now = now or server_now()
    result = await session.execute(
        select(RecoveryTask).where(
            RecoveryTask.user_id == user_id,
            or_(
                RecoveryTask.created_at > since,
                RecoveryTask.completed_at > since,
                RecoveryTask.status == "open",
            ),
        )
    )
    tasks = result.scalars().all()
    if not tasks:
        return ""

    done = sum(1 for task in tasks if task.status == "done")
    unmet = sum(1 for task in tasks if task.status == "missed" or (task.status == "open" and task.due_at <= now))
    line = f"📖 Задания после срыва: выполнено <b>{done}</b> из <b>{len(tasks)}</b>"
    if unmet:
        line += f", не выполнено <b>{unmet}</b>"
    return line
