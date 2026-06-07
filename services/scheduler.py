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

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

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
                        
                        # Отправляем сообщение пользователю
                        await bot.send_message(
                            chat_id=user.id,
                            text="🔔 <b>Время ежедневного отчета!</b>\n\n"
                                 "Пожалуйста, сделайте отметку о том, как прошел сегодняшний день. "
                                 "У вас есть 5 минут для своевременной отметки или до 20 часов дополнительного времени.",
                            reply_markup=get_checkin_keyboard()
                        )
                        logger.info(f"Отправлен ежедневный чек-ин пользователю {user.id}")
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
                    
                    # Отправляем сообщение пользователю
                    if was_active_enough:
                        user_text = (
                            "🚨 <b>Срок дополнительной попытки вышел!</b>\n\n"
                            "Вы не отметились в течение 20 часов после назначенного времени. "
                            "Напарнику отправлено автоматическое уведомление о пропуске отчета."
                        )
                    else:
                        user_text = (
                            "🚨 <b>Срок дополнительной попытки вышел!</b>\n\n"
                            "Вы не отметились в течение 20 часов после назначенного времени. "
                            "Поскольку вы практически не пользовались Telegram (активность менее 10 минут), "
                            "автоматическое уведомление напарнику НЕ отправлялось."
                        )
                        
                    try:
                        await bot.send_message(
                            chat_id=user.id,
                            text=user_text
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление пользователю {user.id}: {e}")
                        
                    # Отправляем сообщение напарнику только если пользователь был активен >= 10 минут
                    if was_active_enough:
                        business_connection_id = user.business_connection_id
                        if partner_username and business_connection_id:
                            alert_text = (
                                "🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы сообщить: я пропустил обязательную ежедневную отметку "
                                "и не выходил на связь с ботом более 20 часов. Вероятно, я на грани срыва или избегаю контроля. Пожалуйста, свяжись со мной."
                            )
                            await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                            logger.info(f"Напарник уведомлен для пользователя {user.id} (активность >= 10 мин)")
                    else:
                        logger.info(f"Напарник НЕ уведомлен для пользователя {user.id} (активность < 10 мин или 0)")
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
                            
                        # 2. Оповещаем напарника, если опция включена
                        if user.notify_partner_achievements:
                            partner_username = user.partner_username
                            business_connection_id = user.business_connection_id
                            
                            if partner_username and business_connection_id:
                                alert_text = (
                                    f"🤖 [Автоматическое сообщение] Привет! Я достиг новой важной вехи чистоты — "
                                    f"{m} дней подряд! 🎉 Спасибо за твою поддержку."
                                )
                                await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                                logger.info(f"Отправлено уведомление о медали {m}д напарнику для {user.id}")
            except Exception as e:
                logger.error(f"Ошибка проверки достижений для пользователя {user.id}: {e}")

async def send_daily_bible_verses():
    """Ежедневная отправка библейского стиха в 09:00"""
    from main import bot
    
    # Получаем стих дня
    verse = await bible_service.fetch_daily_text()
    
    message_text = (
        "📖 <b>ЕЖЕДНЕВНОЕ ИССЛЕДОВАНИЕ ПИСАНИЙ</b>\n"
        "──────────────────────────\n"
        f"<b>{verse['citation']}</b>\n\n"
        f"<i>«{verse['text']}»</i>\n\n"
        f"<b>Размышление:</b>\n{verse['commentary']}\n"
        "──────────────────────────\n"
        "👋 <i>Пусть эти слова поддержат тебя и дадут сил на сегодня! Хорошего дня!</i>"
    )
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        
        for user in users:
            try:
                # Определяем локальное время 09:00 для пользователя (позже это запустится cron-ом в 9 утра по его таймзоне)
                await bot.send_message(chat_id=user.id, text=message_text)
                logger.info(f"Отправлен стих дня пользователю {user.id}")
            except Exception as e:
                logger.error(f"Не удалось отправить стих дня пользователю {user.id}: {e}")

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
                
                # 1. Отправляем отчет самому пользователю
                user_report = (
                    "📊 <b>ТВОЙ ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ</b>\n"
                    "──────────────────────────\n"
                    f"☀️ Чистых дней: <b>{clean_count} из 7</b>\n"
                    f"⚠️ Срывов зафиксировано: <b>{relapse_count}</b>\n"
                    f"🔄 Использовано лимитов «Забыл»: <b>{forgot_count} из 3</b>\n"
                    "──────────────────────────\n"
                    "<i>Отчет также автоматически отправлен твоему напарнику.</i>"
                )
                try:
                    await bot.send_message(chat_id=user.id, text=user_report)
                except Exception as e:
                    logger.error(f"Не удалось отправить недельный отчет пользователю {user.id}: {e}")
                    
                # 2. Отправляем сообщение напарнику
                partner_username = user.partner_username
                business_connection_id = user.business_connection_id
                
                if partner_username and business_connection_id:
                    alert_text = (
                        f"🤖 [Автоматический еженедельный отчет] Привет! Мой отчет о прогрессе за неделю:\n"
                        f"• Чистых дней: {clean_count} из 7\n"
                        f"• Срывов зафиксировано: {relapse_count}\n"
                        f"• Использовано причин 'Забыл': {forgot_count}/3\n\n"
                        f"Спасибо, что остаешься моим напарником и помогаешь мне в этом пути!"
                    )
                    await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                    logger.info(f"Отправлен недельный отчет напарнику для {user.id}")
            except Exception as e:
                logger.error(f"Ошибка формирования недельного отчета для {user.id}: {e}")

def setup_scheduler():
    """Инициализация и запуск планировщика"""
    # Чек-ины проверяются каждую минуту
    scheduler.add_job(check_and_send_checkins, "interval", minutes=1)
    # Дедлайны 20 часов проверяются каждые 5 минут
    scheduler.add_job(check_missed_deadlines, "interval", minutes=5)
    # Проверка достижений каждый час
    scheduler.add_job(check_milestone_achievements, "interval", hours=1)
    
    # Ежедневная рассылка библейского стиха в 09:00 по Киевскому времени (локально для сервера)
    scheduler.add_job(send_daily_bible_verses, "cron", hour=9, minute=0)
    
    # Еженедельный отчет напарнику по воскресеньям в 21:00 по Киевскому времени
    scheduler.add_job(send_weekly_reports, "cron", day_of_week="sun", hour=21, minute=0)
    
    scheduler.start()
    logger.info("Планировщик APScheduler запущен с новыми задачами.")
