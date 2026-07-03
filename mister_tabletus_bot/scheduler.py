import os
import json
import logging
import pytz
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database
from utils.locales import _T

logger = logging.getLogger(__name__)

# Глобальный планировщик
scheduler = AsyncIOScheduler()

async def send_reminder_job(bot: Bot, user_id: int, reminder_id: int, med_id: int, expected_time_str: str, override_date: str = None):
    """Задача, которая запускается планировщиком для отправки напоминания о лекарстве"""
    try:
        user = await database.get_user(user_id)
        med = await database.get_medication(med_id)
        if not user or not med or not med['is_active']:
            return

        user = dict(user)
        med = dict(med)

        user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        now_local = datetime.now(user_tz)
        
        # Check course end date
        if med.get('end_date'):
            try:
                end_date = datetime.strptime(med['end_date'], "%Y-%m-%d").date()
                if now_local.date() > end_date:
                    # Course completed! Soft delete and remove reminders
                    await database.delete_medication(med_id)
                    reminders = await database.get_medication_reminders(med_id)
                    for r in reminders:
                        remove_reminder_from_scheduler(r['id'])
                    logger.info(f"Medication {med_id} ({med['name']}) course ended on {med['end_date']}. Soft deleted.")
                    return
            except Exception as date_err:
                logger.error(f"Error checking end_date for med {med_id}: {date_err}")

        # Уникальный идентификатор конкретного приёма (дата + ожидаемое время)
        ref_date = now_local.date()
        if override_date:
            try:
                ref_date = datetime.strptime(override_date, "%Y-%m-%d").date()
            except Exception as date_err:
                logger.error(f"Error parsing override_date '{override_date}' for med {med_id}: {date_err}")

        expected_time_iso = now_local.replace(
            year=ref_date.year,
            month=ref_date.month,
            day=ref_date.day,
            hour=int(expected_time_str.split(':')[0]),
            minute=int(expected_time_str.split(':')[1]),
            second=0, microsecond=0
        ).isoformat()
        
        # Проверяем, нет ли уже лога в истории (если пользователь уже принял лекарство раньше времени)
        status_history = await database.get_history_status(med_id, expected_time_iso)
        if status_history in ['taken', 'taken_late', 'skipped']:
            logger.info(f"Reminder for med {med_id} at {expected_time_iso} already has status '{status_history}'. Skipping reminder notification.")
            return
            
        # Записываем в историю как 'pending' (ожидает подтверждения), если записи еще нет
        if status_history is None:
            await database.log_history(user_id, med_id, expected_time_iso, 'pending', '')
        
        # Текст сообщения от Мистера Таблетуса
        relation_text = {
            'before_meal': ' (до еды 🍽️)',
            'with_meal': ' (во время еды 🍽️)',
            'after_meal': ' (после еды 🍽️)',
            'none': ''
        }.get(med['food_relation'], '')
        
        msg_text = (
            f"🔔 *Время принять лекарство!*\n\n"
            f"💊 *{med['name']}*\n"
            f"⚖️ Дозировка: {med['dosage'] or 'не указана'}{relation_text}\n"
            f"📦 Остаток в аптечке: {med['stock_count']} шт.\n\n"
            f"🤖 *Мистер Таблетус:* «Не затягивайте с приемом, моё здоровье зависит от вашей дисциплины!»"
        )
        
        # Создаем интерактивные кнопки
        # Формат callback_data: action:med_id:reminder_id:expected_time_iso
        # Важно: callback_data в Telegram ограничена 64 байтами. 
        # expected_time_iso обычно занимает ~25 байт. action:med_id:reminder_id занимает ~20 байт. Влезаем!
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принял", callback_data=f"take:{med_id}:{expected_time_iso}"),
                InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip:{med_id}:{expected_time_iso}")
            ],
            [
                InlineKeyboardButton(text="⏰ Напомнить через 15 мин", callback_data=f"snooze:{med_id}:{expected_time_iso}")
            ]
        ])
        
        image_path = med['image_path']
        if not image_path or not os.path.exists(image_path):
            image_path = "photos/default_pill.png"
            
        sent_message = None
        if os.path.exists(image_path):
            try:
                photo = FSInputFile(image_path)
                sent_message = await bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=msg_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as photo_err:
                logger.error(f"Не удалось отправить фото лекарства: {photo_err}")
                
        if not sent_message:
            sent_message = await bot.send_message(
                chat_id=user_id,
                text=msg_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

            
        # Запускаем отложенную задачу проверки подтверждения через 45 минут
        # Для тестирования можно сократить, но сделаем 45 минут по умолчанию
        check_time = datetime.now() + timedelta(minutes=45)
        scheduler.add_job(
            check_unconfirmed_job,
            'date',
            run_date=check_time,
            args=[bot, user_id, med_id, expected_time_iso, sent_message.message_id]
        )
        
    except Exception as e:
        logger.error(f"Ошибка в send_reminder_job: {e}", exc_info=True)

async def check_unconfirmed_job(bot: Bot, user_id: int, med_id: int, expected_time_iso: str, message_id: int):
    """Проверяет через 45 минут, принял ли пользователь лекарство. Если нет — штрафует и шлет алармы."""
    try:
        status_history = await database.get_history_status(med_id, expected_time_iso)
                
        # Если статус до сих пор pending — значит пользователь проигнорировал пуш
        if status_history == 'pending':
            # 1. Меняем статус на skipped
            await database.update_history_status(med_id, expected_time_iso, 'skipped', datetime.now().isoformat())
            
            # 2. Штрафуем Тамагочи (-15 здоровья)
            status = await database.update_user_tamagotchi(user_id, health_delta=-15, xp_delta=0)
            
            med = await database.get_medication(med_id)
            if med:
                med = dict(med)
            med_name = med['name'] if med else "лекарство"
            
            user_info = await database.get_user(user_id)
            if user_info:
                user_info = dict(user_info)
            lang = user_info.get("language") if user_info else "ru"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=_T("btn_take_late", lang), callback_data=f"take_late:{med_id}:{expected_time_iso}")
                ]
            ])
            
            # 3. Отправляем гневное/грустное сообщение пользователю
            health_msg = f"💔 Моё здоровье упало до {status['health']}%!" if status else ""
            await bot.send_message(
                chat_id=user_id,
                text=f"🚨 *Пропущен прием лекарства!*\n\n"
                     f"Вы не подтвердили прием *{med_name}* вовремя (прошло 45 минут).\n\n"
                     f"🤢 *Мистер Таблетус:* «Ай! Мне стало хуже... Пожалуйста, не забывайте о своем здоровье и обо мне! {health_msg}»",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Попытаемся отредактировать старое сообщение, убрав кнопки клавиатуры
            try:
                await bot.edit_message_reply_markup(chat_id=user_id, message_id=message_id, reply_markup=None)
            except Exception:
                pass
                
            # 4. Оповещаем Бадди (друзей), если фича включена у пользователя
            if user_info and user_info['buddies_enabled'] == 1:
                buddies = await database.get_user_buddies(user_id)
                user_name = user_info['first_name'] or "Ваш друг"
                
                for buddy in buddies:
                    try:
                        await bot.send_message(
                            chat_id=buddy['buddy_tg_id'],
                            text=f"✉️ *Дружеское напоминание от Мистера Таблетуса!*\n\n"
                                 f"Кажется, *{user_name}* забыл(а) отметить прием лекарства *{med_name}*.\n"
                                 f"Напишите или наберите его/ее, чтобы по-дружески напомнить! Поддержка — это важно! 🤝",
                            parse_mode="Markdown"
                        )
                    except Exception as buddy_err:
                        logger.error(f"Не удалось отправить уведомление Бадди {buddy['buddy_tg_id']}: {buddy_err}")
                    
    except Exception as e:
        logger.error(f"Ошибка в check_unconfirmed_job: {e}", exc_info=True)

async def write_heartbeat_job():
    """Записывает текущее время в базу данных для подтверждения активности бота"""
    try:
        from datetime import datetime
        now_str = datetime.utcnow().isoformat()
        await database.execute(
            "INSERT INTO bot_status (name, last_ping) VALUES ('mister_tabletus', ?) ON CONFLICT (name) DO UPDATE SET last_ping = EXCLUDED.last_ping",
            "INSERT INTO bot_status (name, last_ping) VALUES ('mister_tabletus', $1) ON CONFLICT (name) DO UPDATE SET last_ping = EXCLUDED.last_ping",
            (now_str,)
        )
    except Exception as e:
        logger.error(f"Ошибка в write_heartbeat_job: {e}", exc_info=True)

async def setup_scheduler(bot: Bot):
    """Инициализация и запуск планировщика, загрузка всех активных напоминаний из БД"""
    if not scheduler.running:
        scheduler.start()
    else:
        scheduler.remove_all_jobs()
        
    # Записываем heartbeat при старте
    await write_heartbeat_job()
    
    # Добавляем задачу раз в 5 минут
    scheduler.add_job(
        write_heartbeat_job,
        'interval',
        minutes=5,
        id="bot_heartbeat",
        replace_existing=True
    )
        
    reminders = await database.get_all_reminders_for_scheduler()
    
    count = 0
    for r in reminders:
        add_reminder_to_scheduler(bot, r)
        count += 1
        
    # Загружаем недельные отчеты и очистку для всех пользователей
    try:
        users = await database.get_all_users()
        for u in users:
            schedule_user_weekly_jobs(bot, dict(u))
        logger.info(f"Scheduled weekly report and cleanup jobs for {len(users)} users.")
    except Exception as e:
        logger.error(f"Error scheduling weekly jobs in setup_scheduler: {e}", exc_info=True)
        
    # Временный одноразовый переотчет для @U_lisko (user_id 5323839684) на 24 июня в 10:45 по Киеву
    try:
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        run_time = kyiv_tz.localize(datetime(2026, 6, 24, 10, 45, 0))
        if run_time > datetime.now(kyiv_tz):
            # Escitalopram (med_id 5, reminder_id 5)
            scheduler.add_job(
                send_reminder_job,
                'date',
                run_date=run_time,
                id="temp_resend_ulisko_5",
                args=[bot, 5323839684, 5, 5, "11:00", "2026-06-23"],
                replace_existing=True
            )
            # Gidazepam (med_id 6, reminder_id 6)
            scheduler.add_job(
                send_reminder_job,
                'date',
                run_date=run_time,
                id="temp_resend_ulisko_6",
                args=[bot, 5323839684, 6, 6, "11:00", "2026-06-23"],
                replace_existing=True
            )
            logger.info("Successfully scheduled temp one-time resend for @U_lisko at 10:45 Kyiv time.")
    except Exception as temp_err:
        logger.error(f"Error scheduling temp resend for @U_lisko: {temp_err}")

    logger.info(f"Планировщик запущен. Загружено {count} напоминаний.")


def add_reminder_to_scheduler(bot: Bot, r):
    """Добавляет задачу напоминания в APScheduler с учетом часового пояса пользователя"""
    job_id = f"reminder_{r['reminder_id']}"
    
    # Пытаемся распарсить часовой пояс
    try:
        user_tz = pytz.timezone(r['timezone'] or 'Europe/Moscow')
    except Exception:
        user_tz = pytz.timezone('Europe/Moscow')
        
    try:
        time_str = r['time_str']
        if ':' not in time_str:
            if len(time_str) == 2 and time_str.isdigit():
                time_str = f"{time_str}:00"
            else:
                raise ValueError(f"Invalid time format: '{time_str}'")
        hour, minute = map(int, time_str.split(':'))
    except Exception as parse_err:
        logger.error(f"Error parsing time_str '{r['time_str']}' for reminder {r['reminder_id']}: {parse_err}")
        return
    
    # Настраиваем триггер в зависимости от типа расписания
    trigger = None
    if r['schedule_type'] == 'daily':
        trigger = CronTrigger(hour=hour, minute=minute, timezone=user_tz)
    elif r['schedule_type'] == 'specific_days':
        # schedule_data хранит массив индексов дней недели (0-Пн, 6-Вс)
        days = json.loads(r['schedule_data']) if r['schedule_data'] else [0,1,2,3,4,5,6]
        # Преобразуем в строковый формат для CronTrigger (например, "mon,wed,fri")
        days_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        days_str = ",".join([days_map[d] for d in days if d in days_map])
        trigger = CronTrigger(day_of_week=days_str, hour=hour, minute=minute, timezone=user_tz)
    elif r['schedule_type'] == 'interval':
        # interval (каждые N дней) — сложнее сделать чистым CronTrigger, но для простоты
        # сделаем запуск каждый день, а внутри обработчика или здесь будем проверять дату начала.
        # Для MVP сделаем запуск ежедневно в указанное время, а проверку интервала добавим позже
        trigger = CronTrigger(hour=hour, minute=minute, timezone=user_tz)
        
    if trigger:
        # Если задача уже существует, удаляем её перед добавлением
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        scheduler.add_job(
            send_reminder_job,
            trigger,
            id=job_id,
            args=[bot, r['user_id'], r['reminder_id'], r['medication_id'], r['time_str']],
            replace_existing=True
        )

def remove_reminder_from_scheduler(reminder_id: int):
    """Удаляет задачу напоминания из планировщика"""
    job_id = f"reminder_{reminder_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

def remove_snooze_jobs_from_scheduler(med_id: int):
    """Удаляет все отложенные (snoozed) напоминания для указанного лекарства из планировщика"""
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(f"snooze_{med_id}_"):
            try:
                scheduler.remove_job(job.id)
                logger.info(f"Успешно удалена отложенная задача {job.id} из планировщика.")
            except Exception as e:
                logger.error(f"Не удалось удалить отложенную задачу {job.id}: {e}")

def schedule_user_weekly_jobs(bot: Bot, u: dict):
    user_id = u['id']
    try:
        user_tz = pytz.timezone(u['timezone'] or 'Europe/Moscow')
    except Exception:
        user_tz = pytz.timezone('Europe/Moscow')
        
    report_job_id = f"weekly_report_{user_id}"
    cleanup_job_id = f"weekly_cleanup_{user_id}"
    
    # Remove existing jobs if any
    if scheduler.get_job(report_job_id):
        scheduler.remove_job(report_job_id)
    if scheduler.get_job(cleanup_job_id):
        scheduler.remove_job(cleanup_job_id)
        
    # Schedule Weekly Report on Monday at 10:00 AM
    scheduler.add_job(
        send_weekly_report_job,
        CronTrigger(day_of_week='mon', hour=10, minute=0, timezone=user_tz),
        id=report_job_id,
        args=[bot, user_id],
        replace_existing=True
    )
    
    # Schedule Weekly Cleanup on Tuesday at 03:00 AM
    scheduler.add_job(
        weekly_cleanup_job,
        CronTrigger(day_of_week='tue', hour=3, minute=0, timezone=user_tz),
        id=cleanup_job_id,
        args=[user_id],
        replace_existing=True
    )

async def reschedule_user_jobs(bot: Bot, user_id: int):
    # 1. Reschedule all medication reminders
    reminders = await database.get_user_reminders_for_scheduler(user_id)
    
    # First remove any existing reminders from this user from scheduler
    for r in reminders:
        remove_reminder_from_scheduler(r['reminder_id'])
        
    for r in reminders:
        add_reminder_to_scheduler(bot, r)
        
    # 2. Reschedule the weekly report and cleanup jobs
    user = await database.get_user(user_id)
    if not user:
        return
    schedule_user_weekly_jobs(bot, dict(user))
    logger.info(f"Rescheduled weekly jobs and {len(reminders)} medication reminders for user {user_id}")

async def send_weekly_report_job(bot: Bot, user_id: int):
    try:
        user = await database.get_user(user_id)
        if not user:
            return
        user = dict(user)
        lang = user.get("language") or "ru"
        
        # 1. Fetch user's history
        history = await database.get_user_history(user_id)
        if not history:
            history = []
            
        # 2. Fetch user's medications
        meds = await database.get_user_medications(user_id)
        # If the user has NO medications at all, they get nothing
        if not meds:
            logger.info(f"User {user_id} has no medications. Skipping weekly report.")
            return
            
        # 3. Filter history for the previous week
        try:
            user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        except Exception:
            user_tz = pytz.timezone('Europe/Moscow')
            
        now_local = datetime.now(user_tz)
        today_date = now_local.date()
        
        # Calculate last week's start (Monday) and end (Sunday)
        start_of_this_week = today_date - timedelta(days=today_date.weekday())
        start_of_last_week = start_of_this_week - timedelta(days=7)
        end_of_last_week = start_of_this_week - timedelta(days=1)
        
        start_of_last_week_str = start_of_last_week.isoformat()
        end_of_last_week_str = end_of_last_week.isoformat()
        
        logger.info(f"Weekly report for {user_id} from {start_of_last_week_str} to {end_of_last_week_str}")
        
        last_week_history = []
        for h in history:
            h = dict(h)
            try:
                rem_date_str = h['reminder_time'].split("T")[0]
                if start_of_last_week_str <= rem_date_str <= end_of_last_week_str:
                    last_week_history.append(h)
            except Exception as e:
                logger.error(f"Error parsing reminder_time: {e}")
                
        total_scheduled = len(last_week_history)
        total_taken = sum(1 for h in last_week_history if h['status'] in ['taken', 'taken_late'])
        total_skipped = sum(1 for h in last_week_history if h['status'] == 'skipped')
        total_pending = sum(1 for h in last_week_history if h['status'] == 'pending')
        
        # If no reminders were scheduled, skip
        if total_scheduled == 0:
            logger.info(f"User {user_id} had 0 scheduled reminders in the past week. Skipping report.")
            return
            
        # 4. Check feedback eligibility:
        # - total_taken <= 1
        # - at least one medication is scheduled for a period > 1 day
        has_long_course = False
        for med in meds:
            med = dict(med)
            start_date_str = med.get('start_date')
            end_date_str = med.get('end_date')
            if not end_date_str:
                has_long_course = True
                break
            if start_date_str and end_date_str:
                try:
                    s_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    e_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    if s_dt != e_dt:
                        has_long_course = True
                        break
                except:
                    pass
                    
        is_feedback_eligible = (total_taken <= 1) and has_long_course
        
        if is_feedback_eligible:
            msg_text = _T("weekly_feedback", lang, taken=total_taken)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✍️ Написать @mishanya404", url="https://t.me/mishanya404")
                ],
                [
                    InlineKeyboardButton(text=_T("btn_feedback_no_use", lang), callback_data="feedback_no_use")
                ]
            ])
            await bot.send_message(
                chat_id=user_id,
                text=msg_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            logger.info(f"Sent weekly low usage feedback message to user {user_id}")
        else:
            if total_skipped == 0 and total_pending == 0:
                msg_text = _T("weekly_perfect", lang)
            else:
                msg_text = _T("weekly_good", lang, taken=total_taken, total=total_scheduled)
                
            await bot.send_message(
                chat_id=user_id,
                text=msg_text,
                parse_mode="Markdown"
            )
            logger.info(f"Sent weekly adherence report to user {user_id}")
            
    except Exception as e:
        logger.error(f"Error in send_weekly_report_job: {e}", exc_info=True)

async def weekly_cleanup_job(user_id: int):
    try:
        user = await database.get_user(user_id)
        if not user:
            return
        user = dict(user)
        try:
            user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        except Exception:
            user_tz = pytz.timezone('Europe/Moscow')
            
        now_local = datetime.now(user_tz)
        today_date = now_local.date()
        
        # Tuesday cleanup: delete history older than Monday of the current week
        start_of_this_week = today_date - timedelta(days=today_date.weekday())
        start_of_this_week_str = start_of_this_week.isoformat()
        
        await database.delete_old_history(user_id, start_of_this_week_str)
        logger.info(f"Cleaned up history for user {user_id} before {start_of_this_week_str}")
    except Exception as e:
        logger.error(f"Error in weekly_cleanup_job for user {user_id}: {e}", exc_info=True)
