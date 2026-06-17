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

logger = logging.getLogger(__name__)

# Глобальный планировщик
scheduler = AsyncIOScheduler()

async def send_reminder_job(bot: Bot, user_id: int, reminder_id: int, med_id: int, expected_time_str: str):
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
        expected_time_iso = now_local.replace(
            hour=int(expected_time_str.split(':')[0]),
            minute=int(expected_time_str.split(':')[1]),
            second=0, microsecond=0
        ).isoformat()
        
        # Проверяем, нет ли уже лога (чтобы избежать дублирования при перезапуске)
        # И записываем в историю как 'pending' (ожидает подтверждения)
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
            
            # 3. Отправляем гневное/грустное сообщение пользователю
            health_msg = f"💔 Моё здоровье упало до {status['health']}%!" if status else ""
            await bot.send_message(
                chat_id=user_id,
                text=f"🚨 *Пропущен прием лекарства!*\n\n"
                     f"Вы не подтвердили прием *{med_name}* вовремя (прошло 45 минут).\n\n"
                     f"🤢 *Мистер Таблетус:* «Ай! Мне стало хуже... Пожалуйста, не забывайте о своем здоровье и обо мне! {health_msg}»",
                parse_mode="Markdown"
            )
            
            # Попытаемся отредактировать старое сообщение, убрав кнопки клавиатуры
            try:
                await bot.edit_message_reply_markup(chat_id=user_id, message_id=message_id, reply_markup=None)
            except Exception:
                pass
                
            # 4. Оповещаем Бадди (друзей), если фича включена у пользователя
            user_info = await database.get_user(user_id)
            if user_info:
                user_info = dict(user_info)
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

async def setup_scheduler(bot: Bot):
    """Инициализация и запуск планировщика, загрузка всех активных напоминаний из БД"""
    if not scheduler.running:
        scheduler.start()
    else:
        scheduler.remove_all_jobs()
        
    reminders = await database.get_all_reminders_for_scheduler()
    
    count = 0
    for r in reminders:
        add_reminder_to_scheduler(bot, r)
        count += 1
        
    logger.info(f"Планировщик запущен. Загружено {count} напоминаний.")


def add_reminder_to_scheduler(bot: Bot, r):
    """Добавляет задачу напоминания в APScheduler с учетом часового пояса пользователя"""
    job_id = f"reminder_{r['reminder_id']}"
    
    # Пытаемся распарсить часовой пояс
    try:
        user_tz = pytz.timezone(r['timezone'] or 'Europe/Moscow')
    except Exception:
        user_tz = pytz.timezone('Europe/Moscow')
        
    hour, minute = map(int, r['time_str'].split(':'))
    
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
