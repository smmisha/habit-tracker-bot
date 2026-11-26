from datetime import datetime, date, timedelta
import pytz
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, and_
from database.db_helper import db_helper
from database.models import User, CheckInLog, RelapseLog
from keyboards.inline import get_day_report_keyboard, get_day_trigger_keyboard
from services.userbot_client import userbot
from services.ai_service import ai_service
from services import recovery_tasks
from services.day_report import build_report_summary, get_unmarked_days, mark_day

logger = logging.getLogger(__name__)
router = Router()

def get_user_local_time(timezone_str: str) -> datetime:
    """Получить текущее локальное время пользователя"""
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz)
    except Exception:
        return datetime.now()

def is_on_time(user_local_time: datetime, scheduled_time_str: str) -> bool:
    """
    Проверяет, укладывается ли пользователь в интервал отметки.
    Интервал: запланированное время +/- 5 минут.
    """
    try:
        hour, minute = map(int, scheduled_time_str.split(":"))
        scheduled_today = user_local_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # Допускаем погрешность в 5 минут
        start_time = scheduled_today - timedelta(minutes=5)
        end_time = scheduled_today + timedelta(minutes=5)
        
        return start_time <= user_local_time <= end_time
    except Exception as e:
        logger.error(f"Ошибка проверки времени чек-ина: {e}")
        return False

@router.callback_query(F.data == "checkin_clean")
async def process_checkin_clean(callback: CallbackQuery, state: FSMContext = None):
    user_id = callback.from_user.id
    if state:
        await state.clear()
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден.")
            return
            
        local_now = get_user_local_time(user.timezone)
        today_date = local_now.date()
        
        # Ищем открытые чек-ины (в пределах 24ч окна)
        checkin_result = await session.execute(
            select(CheckInLog)
            .where(
                and_(
                    CheckInLog.user_id == user_id,
                    CheckInLog.status == "pending"
                )
            )
            .order_by(CheckInLog.checkin_date.desc())
        )
        pending_logs = checkin_result.scalars().all()
        
        if pending_logs:
            now_dt = datetime.now()
            for ch in pending_logs:
                ch.status = "clean"
                ch.timestamp = now_dt
                ch.excuse_reason = None
        else:
            session.add(CheckInLog(
                user_id=user_id,
                checkin_date=today_date,
                status="clean",
                timestamp=datetime.now(),
                excuse_reason=None
            ))
            
        # Любой ручной ответ сбрасывает счетчик молчания
        user.consecutive_missed_checkins = 0
        user.last_checkin_message_id = None
        user.is_active = True
        
        delta = datetime.now() - user.streak_start
        streak_days = max(0, delta.days)
        
        await session.commit()
        
        import html
        try:
            await callback.message.edit_text("⏳ <i>Подключаю ИИ-ассистента...</i>")
        except Exception as e:
            logger.warning(f"Failed to send 'Connecting AI' status in checkin_clean: {e}")
            
        try:
            ai_response = await ai_service.generate_clean_checkin_response(streak_days)
        except Exception as e:
            logger.error(f"Error calling AI service in checkin_clean: {e}")
            ai_response = f"Отлично! Твой день прошел чисто. Текущий стрик: {streak_days} дн. Продолжай в том же духе!"
            
        ai_response_escaped = html.escape(ai_response)
        clean_text = (
            "☀️ <b>Отметка выполнена! Твой день прошел чисто!</b>\n\n"
            f"{ai_response_escaped}"
        )
        try:
            await callback.message.edit_text(clean_text)
        except Exception as e:
            logger.error(f"Failed to edit message in checkin_clean: {e}")
            try:
                await callback.message.answer(clean_text)
            except Exception as e2:
                logger.error(f"Failed to send clean checkin answer fallback: {e2}")
        try:
            await callback.answer()
        except Exception:
            pass

    try:
        await send_unmarked_days_prompt(callback.message, user_id)
    except Exception as e:
        logger.error(f"Не удалось предложить отметить пропущенные дни {user_id}: {e}")

@router.callback_query(F.data == "checkin_relapsed")
async def process_checkin_relapsed(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if user:
            user.consecutive_missed_checkins = 0
            user.last_checkin_message_id = None
            user.is_active = True
            await session.commit()

    await callback.answer()
    from keyboards.inline import get_trigger_keyboard
    await callback.message.edit_text(
        "⚠️ <b>Запись срыва при чек-ине</b>\n\n"
        "Нам искренне жаль. Но помни: срыв — это не поражение, а повод сделать работу над ошибками. "
        "Путь к свободе не бывает идеально ровным. Не сдавайся!\n\n"
        "<b>Что послужило главным триггером срыва?</b> Выбери вариант на кнопках ниже:",
        reply_markup=get_trigger_keyboard()
    )

# --- ДНИ БЕЗ ОТМЕТКИ ---
DAY_REASONS = {
    "bored": "Скука / Безделье",
    "stress": "Стресс / Усталость",
    "lonely": "Одиночество / Грусть",
    "web": "Искушение в интернете",
    "other": "Другая причина",
}
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")

def _day_label(day: date) -> str:
    return f"{day.strftime('%d.%m')}, {WEEKDAYS[day.weekday()]}"

def _day_question(days: list[date]) -> str:
    return (
        "📝 <b>Дни без отметки</b>\n"
        f"Осталось отметить: {len(days)}\n\n"
        f"Как прошел день <b>{_day_label(days[0])}</b>?"
    )

async def send_unmarked_days_prompt(message: Message, user_id: int) -> bool:
    """Предлагает отметить прошедшие дни без ответа, начиная с самого раннего"""
    days = await get_unmarked_days(user_id)
    if not days:
        return False
    await message.answer(_day_question(days), reply_markup=get_day_report_keyboard(days[0].isoformat()))
    return True

async def _announce_survey_task(callback: CallbackQuery, state: FSMContext | None):
    """Задание, созданное отметками задним числом, отправляется после опроса по дням"""
    if not state:
        return
    task_id = (await state.get_data()).get("survey_task_id")
    if not task_id:
        return
    await state.update_data(survey_task_id=None)
    card = await recovery_tasks.open_task_card(callback.from_user.id, task_id)
    if card:
        await callback.message.answer(card[0], reply_markup=card[1])

async def _show_next_day(callback: CallbackQuery, note: str, state: FSMContext | None = None):
    """Следующий неотмеченный день, а когда они закончились, отчет"""
    user_id = callback.from_user.id
    days = await get_unmarked_days(user_id)
    if days:
        await callback.message.edit_text(
            f"{note}\n\n{_day_question(days)}",
            reply_markup=get_day_report_keyboard(days[0].isoformat())
        )
    else:
        summary = await build_report_summary(user_id)
        await callback.message.edit_text(f"{note}\n\n✅ <b>Дней без отметки не осталось.</b>\n\n{summary}")
        await _announce_survey_task(callback, state)

@router.callback_query(F.data.startswith("day:"))
async def process_day_report(callback: CallbackQuery, state: FSMContext = None):
    await callback.answer()
    parts = callback.data.split(":")
    action = parts[1]

    if action == "later":
        await callback.message.edit_text(
            "⏭ Хорошо. Эти дни пока останутся без отметки, вернуться к ним можно через /start."
        )
        await _announce_survey_task(callback, state)
        return

    try:
        day = date.fromisoformat(parts[2])
    except (IndexError, ValueError):
        return

    if day not in await get_unmarked_days(callback.from_user.id):
        await _show_next_day(callback, "Этот день уже отмечен или недоступен.", state)
        return

    if action == "relapse":
        await callback.message.edit_text(
            f"Что послужило главным триггером срыва <b>{_day_label(day)}</b>?",
            reply_markup=get_day_trigger_keyboard(day.isoformat(), DAY_REASONS)
        )
    elif action == "ask":
        await callback.message.edit_text(
            _day_question([day]), reply_markup=get_day_report_keyboard(day.isoformat())
        )
    elif action == "clean":
        marked = await mark_day(callback.from_user.id, day, relapsed=False)
        note = f"☀️ {_day_label(day)}: чисто." if marked else "Этот день уже отмечен."
        await _show_next_day(callback, note, state)
    elif action == "why" and len(parts) == 4 and parts[3] in DAY_REASONS:
        task_before = await recovery_tasks.get_open_task_id(callback.from_user.id)
        marked = await mark_day(callback.from_user.id, day, relapsed=True, reason=DAY_REASONS[parts[3]])
        task_after = await recovery_tasks.get_open_task_id(callback.from_user.id)
        if state and task_after != task_before:
            await state.update_data(survey_task_id=task_after)
        note = (
            f"😔 {_day_label(day)}: записан срыв.\n"
            "🕊️ По соглашению о нем нужно в течение недели самому рассказать старейшине."
        ) if marked else "Этот день уже отмечен."
        await _show_next_day(callback, note, state)
