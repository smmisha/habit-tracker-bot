import html
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
    """Каждую минуту закрывает просроченные чек-ины и отправляет активным пользователям вечерний чек-ин"""
    await check_missed_deadlines()

    from main import bot
    async with db_helper.session_factory() as session:
        # Получаем всех активных пользователей
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        for user in users:
            try:
                if (user.consecutive_missed_checkins or 0) >= 7:
                    continue

                # Определяем локальное время пользователя
                user_tz = pytz.timezone(user.timezone)
                local_now = datetime.now(user_tz)
                hour, minute = map(int, user.checkin_time.split(":"))
                today_date = local_now.date()
                scheduled_today = user_tz.localize(datetime.combine(today_date, time(hour, minute)))
                elapsed_sec = (local_now - scheduled_today).total_seconds()
                
                # Запускаем в 2-часовом окне (защита от пропуска минуты из-за дрейфа или рестарта)
                if 0 <= elapsed_sec < 7200:
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
                    existing = checkin_result.scalars().first()
                    
                    if not existing:
                        # Удаляем предыдущее неотвеченное сообщение чек-ина, если оно осталось в чате
                        if user.last_checkin_message_id:
                            try:
                                await bot.delete_message(chat_id=user.id, message_id=user.last_checkin_message_id)
                            except Exception:
                                pass
                            user.last_checkin_message_id = None

                        # Отправляем сообщение с прямыми кнопками чек-ина (до фиксации в БД, чтобы сбой сети не скрыл чек-ин)
                        sent_msg = await bot.send_message(
                            chat_id=user.id,
                            text="🔔 <b>Время ежедневного отчета!</b>\n\nКак прошел сегодняшний день? Все под контролем?",
                            reply_markup=get_checkin_keyboard()
                        )
                        new_log = CheckInLog(
                            user_id=user.id,
                            checkin_date=today_date,
                            status="pending",
                            message_id=sent_msg.message_id
                        )
                        session.add(new_log)
                        user.last_checkin_message_id = sent_msg.message_id
                        await session.commit()
                        
                        logger.info(f"Отправлен ежедневный чек-ин пользователю {user.id}")
            except Exception as e:
                logger.error(f"Ошибка при обработке чек-ина для пользователя {user.id}: {e}")

async def check_missed_deadlines():
    """
    Обрабатывает чек-ины, на которые не было ответа более 24 часов:
    - Оставляет день без отметки ('missed'): молчание не считается чистым днем.
      Позже бот предложит отметить такие дни.
    - Удаляет зависшее сообщение с кнопками, чтобы не захламлять чат.
    - На 7-й день тишины подряд переводит бота в режим паузы (is_active = False).
    """
    from main import bot
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    async with db_helper.session_factory() as session:
        # Ищем все незавершенные чек-ины в хронологическом порядке
        result = await session.execute(
            select(CheckInLog)
            .where(CheckInLog.status == "pending")
            .order_by(CheckInLog.checkin_date.asc())
        )
        pending_logs = result.scalars().all()
        
        for log in pending_logs:
            try:
                user_result = await session.execute(select(User).where(User.id == log.user_id))
                user = user_result.scalar_one_or_none()
                
                if not user or not user.is_active:
                    continue
                    
                # Вычисляем порог авто-зачета (запланированное время + 24 часа)
                user_tz = pytz.timezone(user.timezone)
                hour, minute = map(int, user.checkin_time.split(":"))
                
                scheduled_naive = datetime.combine(log.checkin_date, time(hour, minute))
                scheduled_dt = user_tz.localize(scheduled_naive)
                deadline_dt = scheduled_dt + timedelta(hours=24)
                local_now = datetime.now(user_tz)
                
                if local_now >= deadline_dt:
                    logger.info(f"Пользователь {user.id} не отвечал >24ч за {log.checkin_date}: день без отметки")
                    
                    # Удаляем зависшее сообщение чек-ина из чата
                    if log.message_id:
                        try:
                            await bot.delete_message(chat_id=user.id, message_id=log.message_id)
                        except Exception:
                            pass
                        if user.last_checkin_message_id == log.message_id:
                            user.last_checkin_message_id = None

                    log.status = "missed"
                    log.timestamp = datetime.now()
                    log.excuse_reason = None
                    
                    user.activity_start = None
                    user.activity_last = None
                    user.consecutive_missed_checkins = (user.consecutive_missed_checkins or 0) + 1
                    
                    if user.consecutive_missed_checkins >= 7:
                        user.is_active = False
                        await session.commit()
                        logger.warning(f"Пользователь {user.id} не отвечал 7 дней подряд: бот остановлен (is_active=False)")
                        
                        pause_kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text="▶️ Вернуться и продолжить",
                                callback_data="resume_bot_from_pause"
                            )
                        ]])
                        try:
                            await bot.send_message(
                                chat_id=user.id,
                                text=(
                                    "⏸️ <b>Бот поставлен на паузу</b>\n\n"
                                    "Ты не отвечал на ежедневные отчёты 7 дней подряд. "
                                    "Чтобы не беспокоить тебя впустую, я остановил все напоминания и рассылки.\n\n"
                                    "Когда будешь готов вернуться — нажми кнопку ниже или введи /start. "
                                    "Тогда сможешь отметить пропущенные дни."
                                ),
                                reply_markup=pause_kb
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление об авто-паузе пользователю {user.id}: {e}")
                    else:
                        await session.commit()
            except Exception as e:
                logger.error(f"Ошибка закрытия чек-ина/паузы для записи {log.id}: {e}")

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
                            f"🎁 <b>Идея для награды от ИИ:</b> {html.escape(reward_suggestion)}\n"
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
        f"<b>{html.escape(verse['citation'])}</b>\n\n"
        f"<i>«{html.escape(verse['text'])}»</i>\n"
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
                            # по дате дня, а не по времени отметки: пропуски отмечают позже
                            CheckInLog.checkin_date > one_week_ago.date()
                        )
                    )
                )
                logs = logs_result.scalars().all()
                
                clean_count = sum(1 for log in logs if log.status == "clean")
                relapse_count = sum(1 for log in logs if log.status == "relapsed")
                
                missed_count = sum(1 for log in logs if log.status == "missed")
                
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
                    f"❔ Без отметки: <b>{missed_count}</b>\n"
                    "──────────────────────────\n"
                    "<i>Держитесь чистоты и оставайтесь сильными! 💪</i>"
                )
                if missed_count:
                    user_report += "\n<i>Отметить пропущенные дни можно через /start.</i>"
                try:
                    await bot.send_message(chat_id=user.id, text=user_report)
                    
                    # Отправляем ИИ-анализ дневника отдельным сообщением
                    analysis_msg = (
                        "🧠 <b>ПСИХОЛОГИЧЕСКИЙ АНАЛИЗ НЕДЕЛИ</b>\n"
                        "──────────────────────────\n"
                        f"{html.escape(ai_journal_analysis)}"
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
    if settings.bot_paused:
        logger.warning("Планировщик APScheduler НЕ запущен (режим паузы bot_paused=True).")
        return

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
