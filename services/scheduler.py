from datetime import datetime, time, timedelta
import pytz
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from database.db_helper import db_helper
from database.models import User, CheckInLog
from keyboards.inline import get_checkin_keyboard
from services.userbot_client import userbot
from services.ai_service import ai_service
from config.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Kyiv"))

async def check_and_send_checkins():
    """Каждую минуту проверяет, кому пора отправить чек-ин"""
    from main import bot
    async with db_helper.session_factory() as session:
        # Получаем всех активных пользователей
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        for user in users:
            try:
                # Определяем локальное время пользователя
                user_tz = pytz.timezone(user.timezone)
                local_now = datetime.now(user_tz)
                local_time_str = local_now.strftime("%H:%M")
                
                # Если время совпадает с назначенным
                if local_time_str == user.checkin_time:
                    today_date = local_now.date()
                    
                    # Проверяем, отправляли ли уже чек-ин на сегодня
                    checkin_result = await session.execute(
                        select(CheckInLog)
                        .where(
                            and_(
                                CheckInLog.user_id == user.id,
                                CheckInLog.checkin_date == today_date
                            )
                        )
                    )
                    existing = checkin_result.scalar_one_or_none()
                    
                    if not existing:
                        # Создаем новую запись чек-ина со статусом "pending"
                        new_log = CheckInLog(
                            user_id=user.id,
                            checkin_date=today_date,
                            status="pending"
                        )
                        session.add(new_log)
                        await session.commit()
                        
                        # Отправляем сообщение с кнопкой Соглашения пользователю
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
                        from main import bot, dp
                        
                        keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text="📄 Читать и подписать Соглашение",
                                        web_app=WebAppInfo(url=f"{settings.webapp_base_url.rstrip('/')}/webapp/purity_covenant_jw_v2.html")
                                    )
                                ]
                            ]
                        )
                        
                        sent_msg = await bot.send_message(
                            chat_id=user.id,
                            text="🔔 <b>Время ежедневного отчета!</b>\n\n"
                                 "Пожалуйста, откройте и подтвердите Соглашение совести перед заполнением отчёта.",
                             reply_markup=keyboard
                        )
                        
                        # Сохраняем ID сообщения в контексте FSM
                        state_ctx = dp.fsm.resolve_context(bot, user.id, user.id)
                        await state_ctx.update_data(covenant_msg_id=sent_msg.message_id)
                        
                        logger.info(f"Отправлен ежедневный чек-ин (соглашение) пользователю {user.id}")
            except Exception as e:
                logger.error(f"Ошибка при обработке чек-ина для пользователя {user.id}: {e}")

async def check_missed_deadlines():
    """
    Проверяет просроченные чек-ины (свыше 20 часов).
    Запускается каждые 5-10 минут.
    """
    from main import bot
    async with db_helper.session_factory() as session:
        # Ищем все незавершенные чек-ины
        result = await session.execute(
            select(CheckInLog)
            .where(CheckInLog.status == "pending")
        )
        pending_logs = result.scalars().all()
        
        for log in pending_logs:
            try:
                # Получаем пользователя
                user_result = await session.execute(select(User).where(User.id == log.user_id))
                user = user_result.scalar_one_or_none()
                
                if not user:
                    continue
                    
                # Вычисляем дедлайн (запланированное время + 20 часов)
                user_tz = pytz.timezone(user.timezone)
                hour, minute = map(int, user.checkin_time.split(":"))
                
                # Создаем datetime на дату чек-ина
                scheduled_naive = datetime.combine(log.checkin_date, time(hour, minute))
                # Делаем локализованным в таймзоне пользователя
                scheduled_dt = user_tz.localize(scheduled_naive)
                
                # Дедлайн = время отметки + 20 часов
                deadline_dt = scheduled_dt + timedelta(hours=20)
                
                # Текущее время в таймзоне пользователя
                local_now = datetime.now(user_tz)
                
                if local_now > deadline_dt:
                    logger.warning(f"Пользователь {user.id} пропустил дедлайн 20 часов для даты {log.checkin_date}")
                    
                    # Проверяем, сколько пользователь был активен
                    was_active_enough = False
                    if user.activity_start and user.activity_last:
                        active_duration = user.activity_last - user.activity_start
                        if active_duration >= timedelta(minutes=10):
                            was_active_enough = True
                    
                    # Обновляем статус
                    log.status = "missed"
                    log.timestamp = datetime.now()
                    log.excuse_reason = "Срок доп. попытки (20 часов) истек"
                    
                    # Сбрасываем текущую активность
                    user.activity_start = None
                    user.activity_last = None
                    partner_username = user.partner_username
                    await session.commit()
                    
                    user_text = (
                        "🚨 <b>Срок дополнительной попытки вышел!</b>\n\n"
                        "Вы не отметились в течение 20 часов после назначенного времени."
                    )
                    try:
                        await bot.send_message(
                            chat_id=user.id,
                            text=user_text
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление пользователю {user.id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка проверки дедлайна для записи {log.id}: {e}")

from aiogram.types import FSInputFile
from services.bible_service import bible_service
import os

async def check_milestone_achievements():
    """Ежечасная проверка достижений (вех чистоты) пользователей"""
    from main import bot
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        milestones = [1, 3, 7, 14, 30, 90]
        badge_names = {
            1: "Бронзовая медаль (1 день чистоты) 🥉",
            3: "Серебряная медаль (3 дня чистоты) 🥈",
            7: "Золотая медаль (7 дней чистоты) 🥇",
            14: "Платиновая медаль (14 дней чистоты) 🏆",
            30: "Изумрудная звезда (30 дней чистоты) 💚",
            90: "Алмазная корона (90 дней чистоты) 👑"
        }
        
        for user in users:
            try:
                # Рассчитываем стрик в днях
                delta = datetime.now() - user.streak_start
                streak_days = delta.days
                
                # Загружаем уже выданные медали
                awarded = [int(x) for x in user.awarded_milestones.split(",") if x.strip().isdigit()]
                
                for m in milestones:
                    if streak_days >= m and m not in awarded:
                        # Нашли новую веху!
                        awarded.append(m)
                        user.awarded_milestones = ",".join(str(x) for x in sorted(awarded))
                        await session.commit()
                        
                        badge_name = badge_names[m]
                        badge_path = f"keyboards/badges/badge_{m}d.png"
                        
                        # 1. Поздравляем пользователя
                        reward_suggestion = await ai_service.generate_milestone_reward_suggestion(m)
                        
                        user_text = (
                            f"🏆 <b>ДОСТИГНУТА НОВАЯ ВЕХА!</b>\n"
                            f"──────────────────────────\n"
                            f"Поздравляем! Ты сохраняешь чистоту уже <b>{m}</b> дней подряд!\n"
                            f"Твоя награда: <b>{badge_name}</b>\n"
                            f"──────────────────────────\n"
                            f"🎁 <b>Идея для награды от ИИ:</b> {reward_suggestion}\n\n"
                            f"📈 Твой ежедневный лимит вопросов к ИИ-помощнику увеличился на +1!\n"
                            f"──────────────────────────\n"
                            f"💪 <i>Ты делаешь невероятный прогресс. Продолжай в том же духе!</i>"
                        )
                        
                        try:
                            if os.path.exists(badge_path):
                                await bot.send_photo(
                                    chat_id=user.id,
                                    photo=FSInputFile(badge_path),
                                    caption=user_text
                                )
                            else:
                                await bot.send_message(chat_id=user.id, text=user_text)
                        except Exception as e:
                            logger.error(f"Не удалось отправить медаль пользователю {user.id}: {e}")
                            
                        # Напарник о достижениях не уведомляется, чтобы не спамить
                        pass
            except Exception as e:
                logger.error(f"Ошибка проверки достижений для пользователя {user.id}: {e}")

async def send_daily_bible_verses():
    """Ежедневная отправка библейского стиха в 09:00"""
    from main import bot
    
    # Получаем стих дня
    verse = await bible_service.fetch_daily_text()
    
    # Сообщение БЕЗ комментария (только цитата и сам стих)
    message_text = (
        "📖 <b>ЕЖЕДНЕВНОЕ ИССЛЕДОВАНИЕ ПИСАНИЙ</b>\n"
        "──────────────────────────\n"
        f"<b>{verse['citation']}</b>\n\n"
        f"<i>«{verse['text']}»</i>\n"
        "──────────────────────────\n"
        "👋 <i>Пусть эти слова поддержат тебя и дадут сил на сегодня! Хорошего дня!</i>"
    )
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        for user in users:
            # 1. Пытаемся удалить вчерашний стих
            if user.last_verse_message_id:
                try:
                    await bot.delete_message(chat_id=user.id, message_id=user.last_verse_message_id)
                    logger.info(f"Успешно удален вчерашний стих дня (ID: {user.last_verse_message_id}) у пользователя {user.id}")
                except Exception as delete_error:
                    logger.warning(f"Не удалось удалить вчерашний стих дня у пользователя {user.id}: {delete_error}")
            
            try:
                # 2. Отправляем сегодняшний стих
                sent_msg = await bot.send_message(chat_id=user.id, text=message_text)
                logger.info(f"Отправлен стих дня пользователю {user.id}, message_id: {sent_msg.message_id}")
                
                # 3. Запоминаем ID сообщения
                user.last_verse_message_id = sent_msg.message_id
            except Exception as e:
                logger.error(f"Не удалось отправить стих дня пользователю {user.id}: {e}")
                
        try:
            await session.commit()
            logger.info("Состояния last_verse_message_id успешно сохранены в БД")
        except Exception as commit_error:
            logger.error(f"Ошибка сохранения ID сообщений стихов в БД: {commit_error}")
            await session.rollback()

async def send_weekly_reports():
    """Еженедельный воскресный отчет для напарника и пользователя"""
    from main import bot
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        one_week_ago = datetime.now() - timedelta(days=7)
        
        for user in users:
            try:
                # Собираем чек-ины за последние 7 дней
                logs_result = await session.execute(
                    select(CheckInLog)
                    .where(
                        and_(
                            CheckInLog.user_id == user.id,
                            CheckInLog.timestamp >= one_week_ago
                        )
                    )
                )
                logs = logs_result.scalars().all()
                
                clean_count = sum(1 for log in logs if log.status == "clean")
                relapse_count = sum(1 for log in logs if log.status == "relapsed")
                
                # Подсчет причин 'Забыл'
                forgot_count = sum(1 for log in logs if log.excuse_reason and "Забыл" in log.excuse_reason)
                
                # Собираем заметки дневника за последние 7 дней
                from database.models import JournalEntry
                journal_result = await session.execute(
                    select(JournalEntry)
                    .where(
                        and_(
                            JournalEntry.user_id == user.id,
                            JournalEntry.entry_date >= one_week_ago.date()
                        )
                    )
                    .order_by(JournalEntry.entry_date)
                )
                journal_entries = journal_result.scalars().all()
                
                # Генерируем ИИ-анализ дневника
                ai_journal_analysis = await ai_service.generate_weekly_journal_analysis(journal_entries)

                # 1. Отправляем отчет самому пользователю
                user_report = (
                    "📊 <b>ТВОЙ ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ</b>\n"
                    "──────────────────────────\n"
                    f"☀️ Чистых дней: <b>{clean_count} из 7</b>\n"
                    f"⚠️ Срывов зафиксировано: <b>{relapse_count}</b>\n"
                    f"🔄 Использовано лимитов «Забыл»: <b>{forgot_count} из 3</b>\n"
                    "──────────────────────────\n"
                    "<i>Держитесь чистоты и оставайтесь сильными! 💪</i>"
                )
                try:
                    await bot.send_message(chat_id=user.id, text=user_report)
                    
                    # Отправляем ИИ-анализ дневника отдельным сообщением
                    analysis_msg = (
                        "🧠 <b>ПСИХОЛОГИЧЕСКИЙ АНАЛИЗ НЕДЕЛИ</b>\n"
                        "──────────────────────────\n"
                        f"{ai_journal_analysis}"
                    )
                    await bot.send_message(chat_id=user.id, text=analysis_msg)
                except Exception as e:
                    logger.error(f"Не удалось отправить недельный отчет пользователю {user.id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка формирования недельного отчета для {user.id}: {e}")

async def send_silent_panic_alert(user_id: int):
    """Отключено: сообщение напарнику отправляется ТОЛЬКО в случае явной фиксации срыва"""
    pass

def setup_scheduler():
    """Инициализация и запуск планировщика"""
    # Чек-ины проверяются каждую минуту
    scheduler.add_job(check_and_send_checkins, "interval", minutes=1)
    # Дедлайны 20 часов проверяются каждые 5 минут
    scheduler.add_job(check_missed_deadlines, "interval", minutes=5)
    # Проверка достижений каждый час
    scheduler.add_job(check_milestone_achievements, "interval", hours=1)
    
    # Ежедневная рассылка библейского стиха в 09:00 по Киевскому времени (локально для сервера)
    scheduler.add_job(send_daily_bible_verses, "cron", hour=9, minute=0, misfire_grace_time=36000)
    
    # Еженедельный отчет напарнику по воскресеньям в 21:00 по Киевскому времени
    scheduler.add_job(send_weekly_reports, "cron", day_of_week="sun", hour=21, minute=0, misfire_grace_time=36000)
    
    scheduler.start()
    logger.info("Планировщик APScheduler запущен с новыми задачами.")
