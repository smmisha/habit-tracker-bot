from datetime import datetime, date, timedelta
import pytz
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, and_
from database.db_helper import db_helper
from database.models import User, CheckInLog, RelapseLog
from keyboards.inline import get_excuses_keyboard
from services.userbot_client import userbot
from services.ai_service import ai_service
from utils.states import Form

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
async def process_checkin_clean(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден.")
            return
            
        local_now = get_user_local_time(user.timezone)
        today_date = local_now.date()
        
        # Ищем вчерашний или сегодняшний незаконченный чек-ин
        checkin_result = await session.execute(
            select(CheckInLog)
            .where(
                and_(
                    CheckInLog.user_id == user_id,
                    CheckInLog.status == "pending"
                )
            )
        )
        active_checkin = checkin_result.scalar_one_or_none()
        
        # Если активной записи нет, создаем ее для сегодняшнего дня
        if not active_checkin:
            active_checkin = CheckInLog(user_id=user_id, checkin_date=today_date, status="pending")
            session.add(active_checkin)
            await session.flush()
            
        # Проверяем, вовремя ли сделана отметка
        if is_on_time(local_now, user.checkin_time):
            # ВОВРЕМЯ
            active_checkin.status = "clean"
            active_checkin.timestamp = datetime.now()
            
            # Вычисляем текущий стрик для ИИ-помощника
            delta = datetime.now() - user.streak_start
            streak_days = delta.days
            
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
        else:
            # ОПОЗДАНИЕ (запускается опрос о причинах)
            forgot_left = 3 - user.forgot_count
            await callback.message.edit_text(
                "⏰ Ты делаешь отметку с опозданием.\n"
                "Пожалуйста, выбери причину пропуска графика:",
                reply_markup=get_excuses_keyboard(forgot_left)
            )
            await callback.answer()

@router.callback_query(F.data == "checkin_relapsed")
async def process_checkin_relapsed(callback: CallbackQuery):
    await callback.answer()
    from keyboards.inline import get_trigger_keyboard
    await callback.message.edit_text(
        "⚠️ <b>Запись срыва при чек-ине</b>\n\n"
        "Нам искренне жаль. Но помни: срыв — это не поражение, а повод сделать работу над ошибками. "
        "Путь к свободе не бывает идеально ровным. Не сдавайся!\n\n"
        "<b>Что послужило главным триггером срыва?</b> Выбери вариант на кнопках ниже:",
        reply_markup=get_trigger_keyboard()
    )

# --- ОБРАБОТКА ПРИЧИН ОПОЗДАНИЯ ---
async def save_excuse(user_id: int, excuse_text: str, callback: CallbackQuery = None, message: Message = None):
    """Вспомогательная функция сохранения причины опоздания"""
    async with db_helper.session_factory() as session:
        # Ищем незакрытый чек-ин
        checkin_result = await session.execute(
            select(CheckInLog)
            .where(and_(CheckInLog.user_id == user_id, CheckInLog.status == "pending"))
        )
        active_checkin = checkin_result.scalar_one_or_none()
        
        if active_checkin:
            active_checkin.status = "clean"
            active_checkin.timestamp = datetime.now()
            active_checkin.excuse_reason = excuse_text
            await session.commit()
            
        text = f"✅ Причина пропуска сохранена: <b>«{excuse_text}»</b>. Стрик продолжается! 💪"
        if callback:
            await callback.message.edit_text(text)
        elif message:
            await message.answer(text)

@router.callback_query(F.data.startswith("excuse_"))
async def process_excuse_selection(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data
    
    if action in ("excuse_forgot", "excuse_forgot_limit"):
        # Считаем попытки «Забыл»
        async with db_helper.session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.forgot_count += 1
                current_forgot = user.forgot_count
                partner_username = user.partner_username
                business_connection_id = user.business_connection_id
                await session.commit()
                
        if current_forgot > 3:
            # Превышен лимит! Отправляем сообщение напарнику
            await save_excuse(user_id, "Забыл (Лимит превышен)", callback=callback)
            
            if partner_username and business_connection_id:
                alert_text = (
                    "🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы сообщить: я систематически пропускаю отчеты в боте "
                    "(я снова превысил лимит причин 'Забыл'). Это знак того, что я могу быть на грани срыва и мне нужна твоя помощь."
                )
                sent = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                if sent:
                    await callback.message.answer(
                        f"🚨 <b>Лимит причин «Забыл» превышен!</b> Сообщение о нарушении отправлено напарнику <code>@{partner_username}</code>."
                    )
                else:
                    await callback.message.answer(
                        "🚨 <b>Лимит причин «Забыл» превышен!</b> Не удалось отправить сообщение напарнику."
                    )
            else:
                await callback.message.answer(
                    "🚨 <b>Лимит причин «Забыл» превышен!</b> Сообщение напарнику не отправлено (нет настройки)."
                )
        else:
            left = 3 - current_forgot
            await save_excuse(user_id, f"Забыл ({current_forgot}/3)", callback=callback)
            await callback.message.answer(f"⚠️ <b>Обратите внимание:</b> у вас осталось <b>{left}</b> попыток выбора причины «Забыл».")
            
    elif action == "excuse_sick":
        await save_excuse(user_id, "Болел", callback=callback)
        
    elif action == "excuse_internet":
        await save_excuse(user_id, "Не было интернета", callback=callback)
        
    elif action == "excuse_busy":
        await save_excuse(user_id, "Был занят / Работа", callback=callback)
        
    elif action == "excuse_other":
        await callback.message.edit_text("📝 Пожалуйста, напишите кратко причину пропуска графика в ответном сообщении:")
        await state.set_state(Form.waiting_for_other_excuse)
        
    await callback.answer()

@router.message(Form.waiting_for_other_excuse)
async def process_other_excuse_input(message: Message, state: FSMContext):
    excuse_text = message.text.strip()
    if len(excuse_text) < 3:
        await message.answer("❌ Слишком короткий ответ. Опишите причину подробнее:")
        return
        
    await save_excuse(message.from_user.id, f"Другое: {excuse_text}", message=message)
    await state.clear()
