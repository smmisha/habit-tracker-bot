import asyncio
import logging
import sys
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BusinessConnection, Message, BotCommand
from sqlalchemy import select, and_
from config.config import settings

# 1. Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Проверяем заполненность настроек
if settings.bot_token == "your_bot_token_here":
    logger.warning("!!! ВНИМАНИЕ !!! BOT_TOKEN не установлен в файле .env! Бот не сможет запуститься.")

# 2. Инициализация Bot и Dispatcher (до импорта хэндлеров, чтобы избежать циклов)
bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# 3. Импорт остальных компонентов после инициализации глобальных объектов
from database.db_helper import db_helper
from handlers.common import router as common_router
from handlers.tracker import router as tracker_router
from handlers.checkin import router as checkin_router
from handlers.panic import router as panic_router
from handlers.journal import router as journal_router
from services.userbot_client import userbot
from services.scheduler import setup_scheduler, scheduler

async def set_commands(bot: Bot):
    """Настройка команд меню бота"""
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="cancel", description="❌ Отменить операцию")
    ]
    await bot.set_my_commands(commands)
    logger.info("Команды меню бота успешно установлены.")

async def on_startup():
    """Действия при запуске бота"""
    logger.info("Запуск инициализации базы данных...")
    await db_helper.init_db()
    
    logger.info("Настройка команд меню...")
    await set_commands(bot)
    
    logger.info("Запуск планировщика чек-инов...")
    setup_scheduler()
    
    logger.info("Бот успешно инициализирован и готов к работе!")

async def on_shutdown():
    """Действия при завершении работы бота"""
    logger.info("Остановка планировщика...")
    if scheduler.running:
        scheduler.shutdown()
        
    logger.info("Закрытие соединений с БД...")
    await db_helper.dispose()
    
    logger.info("Завершение работы.")

# --- ОБРАБОТЧИКИ СОБЫТИЙ TELEGRAM BUSINESS ---

@dp.business_connection()
async def handle_business_connection(connection: BusinessConnection):
    """Срабатывает, когда пользователь подключает/отключает бота в 'Автоматизации чатов'"""
    user_id = connection.user.id
    is_enabled = connection.is_enabled
    connection_id = connection.id
    
    from database.models import User
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            if is_enabled:
                user.business_connection_id = connection_id
                logger.info(f"Бизнес-соединение {connection_id} успешно сохранено для пользователя {user_id}")
            else:
                user.business_connection_id = None
                logger.info(f"Бизнес-соединение отключено для пользователя {user_id}")
            await session.commit()

@dp.business_message()
async def handle_business_message(message: Message):
    """Срабатывает при отправке/получении сообщений в чатах, привязанных к бизнес-аккаунту"""
    connection_id = message.business_connection_id
    user_id = message.from_user.id  # Владелец бизнес-аккаунта
    
    from database.models import User, CheckInLog
    from datetime import datetime, timedelta
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        # Проверяем, что сообщение отправлено пользователем, подключившим этого бота
        if not user or user.business_connection_id != connection_id:
            return
            
        # Проверяем наличие активного ожидающего чек-ина
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
        
        if active_checkin:
            now = datetime.now()
            
            # Если активность еще не зафиксирована
            if not user.activity_start:
                user.activity_start = now
                user.activity_last = now
                await session.commit()
                logger.info(f"Бизнес-активность: зафиксировано начало общения в Telegram для {user_id}")
            else:
                # Обновляем время последней активности
                user.activity_last = now
                elapsed = now - user.activity_start
                await session.commit()
                
                if elapsed >= timedelta(minutes=30):
                    logger.warning(f"Бизнес-активность: пользователь {user_id} общался более 30 минут без отметки!")
                    
                    # Помечаем чек-ин пропущенным
                    active_checkin.status = "missed"
                    active_checkin.timestamp = now
                    active_checkin.excuse_reason = "Проигнорировал чек-ин (был онлайн >30 мин)"
                    
                    # Сбрасываем таймер активности
                    user.activity_start = None
                    user.activity_last = None
                    partner_username = user.partner_username
                    await session.commit()
                    
                    # Отправляем предупреждение самому пользователю
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text="🚨 <b>Вы общаетесь в Telegram уже более 30 минут, но не прошли ежедневный чек-ин!</b>\n\n"
                                 "Напарнику автоматически отправлено сообщение о пропуске отчета."
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление в ЛС боту: {e}")
                        
                    # Отправляем предупреждение напарнику от лица пользователя через бизнес-соединение
                    if partner_username:
                        alert_text = (
                            "🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы сообщить: бот зафиксировал мою активность в Telegram "
                            "(более 30 минут общения), но я проигнорировал обязательную отметку. Похоже, я избегаю отчета и нахожусь "
                            "на грани срыва. Пожалуйста, свяжись со мной."
                        )
                        await userbot.send_message_to_partner(connection_id, partner_username, alert_text)

# --- ВЕБ-СЕРВЕР И API ДЛЯ DASHBOARD (WEBAPP) ---

from datetime import datetime, date, timedelta
from database.models import User, CheckInLog, RelapseLog

async def handle_ping(request):
    return web.Response(text="OK")

async def handle_webapp(request):
    """Служба отдачи HTML-страницы дашборда с перенаправлением на статический путь"""
    user_id = request.query.get('user_id', '')
    target_url = "/webapp/index.html"
    if user_id:
        target_url += f"?user_id={user_id}"
    raise web.HTTPFound(target_url)

async def handle_api_stats(request):
    """API получения статистики пользователя для WebApp"""
    try:
        user_id_str = request.query.get('user_id')
        if not user_id_str:
            return web.json_response({"error": "Missing user_id"}, status=400)
        user_id = int(user_id_str)
    except ValueError:
        return web.json_response({"error": "Invalid user_id"}, status=400)

    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return web.json_response({"error": "User not found"}, status=404)
            
        # 1. Вычисляем текущий стрик
        delta = datetime.now() - user.streak_start
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            streak_str = f"{days} дн. {hours} ч."
        elif hours > 0:
            streak_str = f"{hours} ч. {minutes} мин."
        else:
            streak_str = f"{minutes} мин."
            
        # 2. Получаем историю чек-инов за последние 30 дней
        today = date.today()
        start_date = today - timedelta(days=29)
        
        checkins_result = await session.execute(
            select(CheckInLog)
            .where(
                and_(
                    CheckInLog.user_id == user_id,
                    CheckInLog.checkin_date >= start_date
                )
            )
        )
        checkins = {c.checkin_date: c.status for c in checkins_result.scalars().all()}
        
        # 3. Получаем срывы за последние 30 дней
        relapses_result = await session.execute(
            select(RelapseLog)
            .where(
                and_(
                    RelapseLog.user_id == user_id,
                    RelapseLog.timestamp >= datetime.combine(start_date, datetime.min.time())
                )
            )
        )
        relapses = relapses_result.scalars().all()
        
        # Считаем срывы по дням
        relapse_by_day = {}
        for r in relapses:
            r_date = r.timestamp.date()
            relapse_by_day[r_date] = relapse_by_day.get(r_date, 0) + 1
            
        # 4. Составляем список дней для календаря (30 дней)
        calendar_days = []
        for i in range(30):
            day_date = start_date + timedelta(days=i)
            status = "no-data"
            relapse_count = relapse_by_day.get(day_date, 0)
            
            if relapse_count > 0:
                status = "relapsed"
            elif day_date in checkins:
                ch_status = checkins[day_date]
                if ch_status == "clean":
                    status = "clean"
                elif ch_status == "relapsed":
                    status = "relapsed"
                    
            calendar_days.append({
                "date": day_date.isoformat(),
                "status": status,
                "relapse_count": relapse_count
            })
            
        # 5. Группируем триггеры срывов (всего за все время)
        all_relapses_result = await session.execute(
            select(RelapseLog.trigger_reason)
            .where(RelapseLog.user_id == user_id)
        )
        reasons = all_relapses_result.scalars().all()
        
        triggers = {}
        for r in reasons:
            if not r:
                continue
            clean_reason = r
            if r.startswith("Другое:") or r.startswith("Текстовое описание:"):
                clean_reason = "Другая причина"
            elif r == "Ручной сброс через меню бота":
                clean_reason = "Без указания причины"
            triggers[clean_reason] = triggers.get(clean_reason, 0) + 1
            
        # 6. Получаем историю дневника и настройки
        from database.models import JournalEntry
        from sqlalchemy import desc
        
        journal_result = await session.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .order_by(desc(JournalEntry.entry_date))
            .limit(5)
        )
        journal_history = [
            {
                "date": entry.entry_date.isoformat(),
                "content": entry.content
            }
            for entry in journal_result.scalars().all()
        ]
        
        partner_display = "НЕ УКАЗАН ⚠️"
        if user.partner_username:
            partner_display = user.partner_username if user.partner_username.isdigit() else f"@{user.partner_username}"
            
        settings_data = {
            "partner_display": partner_display,
            "checkin_time": user.checkin_time,
            "timezone": user.timezone,
            "notify_partner_achievements": user.notify_partner_achievements
        }
        
        from services.ai_service import ai_service
        ai_quote = await ai_service.generate_daily_motivational_quote(days)
            
        return web.json_response({
            "streak_str": streak_str,
            "total_relapses": user.total_relapses,
            "calendar_days": calendar_days,
            "triggers": triggers,
            "settings": settings_data,
            "journal_history": journal_history,
            "quote": ai_quote
        })

async def handle_api_save_journal(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        content = data.get("content", "").strip()
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    if not content or len(content) < 5:
        return web.json_response({"error": "Заметка слишком короткая"}, status=400)
        
    from database.models import JournalEntry
    from datetime import date
    
    today_date = date.today()
    
    async with db_helper.session_factory() as session:
        result = await session.execute(
            select(JournalEntry).where(
                and_(JournalEntry.user_id == user_id, JournalEntry.entry_date == today_date)
            )
        )
        entry = result.scalar_one_or_none()
        
        if entry:
            entry.content = content
            entry.created_at = datetime.now()
            action_text = "обновлена"
        else:
            entry = JournalEntry(
                user_id=user_id,
                entry_date=today_date,
                content=content
            )
            session.add(entry)
            action_text = "сохранена"
            
        await session.commit()
        
    return web.json_response({"success": True, "message": f"Заметка успешно {action_text}!"})

async def handle_api_log_relapse(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        trigger_reason = data.get("trigger_reason", "Срыв зафиксирован через Mini App").strip()
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    from database.models import User, RelapseLog
    from services.ai_service import ai_service
    from services.userbot_client import userbot
    
    now = datetime.now()
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return web.json_response({"error": "User not found"}, status=404)
            
        # Логируем срыв и сбрасываем счетчик
        user.streak_start = now
        user.total_relapses += 1
        
        log = RelapseLog(
            user_id=user_id,
            timestamp=now,
            trigger_reason=trigger_reason
        )
        session.add(log)
        await session.commit()
        
        partner_username = user.partner_username
        business_connection_id = user.business_connection_id
        
    # Запускаем ИИ-ассистента в фоне
    async def send_bot_alert():
        try:
            ai_response = await ai_service.generate_relapse_response(trigger_reason)
            await bot.send_message(
                chat_id=user_id,
                text=f"😔 <b>Счетчик сброшен. Начинаем стрик заново!</b>\n\n{ai_response}"
            )
            
            if partner_username and business_connection_id:
                alert_text = (
                    f"🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы признаться: сегодня у меня произошел срыв "
                    f"(триггер: {trigger_reason}), и я сбросил счетчик чистоты. Мне очень нужны твои поддержка и контроль сейчас."
                )
                sent = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                if sent:
                    await bot.send_message(chat_id=user_id, text=f"✅ Сообщение напарнику @{partner_username} успешно отправлено от вашего имени.")
                else:
                    await bot.send_message(chat_id=user_id, text=f"⚠️ Не удалось автоматически отправить сообщение напарнику @{partner_username}.")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений после срыва по API: {e}")
            
    asyncio.create_task(send_bot_alert())
    
    return web.json_response({"success": True, "message": "Срыв зафиксирован. Поддерживающее сообщение отправлено вам в чат."})

async def handle_api_manage_panic(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        action = data.get("action")  # "start", "helped" or "failed"
        trigger_reason = data.get("trigger_reason", "Тяга во время паники").strip()
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    from database.models import User, RelapseLog, JournalEntry
    from services.ai_service import ai_service
    from services.userbot_client import userbot
    from utils.states import Form
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return web.json_response({"error": "User not found"}, status=404)
            
        partner_username = user.partner_username
        business_connection_id = user.business_connection_id
        
        if action == "start":
            # 1. Загружаем историю триггеров срывов
            relapses_result = await session.execute(
                select(RelapseLog.trigger_reason)
                .where(RelapseLog.user_id == user_id)
                .order_by(RelapseLog.timestamp.desc())
                .limit(5)
            )
            triggers = [r for r in relapses_result.scalars().all() if r]
            
            # 2. Загружаем заметки дневника за последнюю неделю
            from datetime import timedelta
            one_week_ago = datetime.now() - timedelta(days=7)
            journal_result = await session.execute(
                select(JournalEntry.content)
                .where(
                    and_(
                        JournalEntry.user_id == user_id,
                        JournalEntry.entry_date >= one_week_ago.date()
                    )
                )
                .order_by(JournalEntry.entry_date.desc())
            )
            journal_notes = journal_result.scalars().all()
            
            # 3. Генерируем персонализированные ИИ-шаги
            guidelines = await ai_service.generate_dynamic_sos_steps(user.total_relapses, triggers, journal_notes)
            return web.json_response({"success": True, "guidelines": guidelines})
        
    if action == "helped":
        async def send_help_ok():
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="🎉 <b>Отлично! Ты справился с тягой и защитил свой стрик!</b>\n\nКаждая такая победа делает тебя сильнее."
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}")
        asyncio.create_task(send_help_ok())
        return web.json_response({"success": True, "message": "Поздравляем с победой над тягой!"})
        
    elif action == "failed":
        now = datetime.now()
        async with db_helper.session_factory() as session:
            user_db = await session.get(User, user_id)
            user_db.streak_start = now
            user_db.total_relapses += 1
            
            log = RelapseLog(
                user_id=user_id,
                timestamp=now,
                trigger_reason=f"Паника: {trigger_reason}"
            )
            session.add(log)
            await session.commit()
            
        async def send_help_failed():
            try:
                ai_response = await ai_service.generate_relapse_response(trigger_reason)
                await bot.send_message(
                    chat_id=user_id,
                    text=f"😔 <b>Счетчик сброшен. Попробуем снова!</b>\n\n{ai_response}"
                )
                
                state_ctx = dp.fsm.resolve_context(bot, user_id, user_id)
                await state_ctx.set_state(Form.panic_chat)
                await state_ctx.update_data(ai_questions_today=0)
                
                await bot.send_message(
                    chat_id=user_id,
                    text="💬 <b>Я подключил ИИ-ассистента для поддержки.</b>\n"
                         "Вы можете написать сюда ваши мысли или чувства, чтобы обсудить их с ИИ (введите ответ в чат):"
                )
                
                if partner_username and business_connection_id:
                    alert_text = (
                        f"🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы признаться: сегодня у меня произошел срыв "
                        f"(я нажал кнопку SOS, но не справился; триггер: {trigger_reason}). Мне очень нужны твои поддержка и контроль сейчас."
                    )
                    sent = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                    if sent:
                        await bot.send_message(chat_id=user_id, text=f"✅ Сообщение напарнику @{partner_username} успешно отправлено от вашего имени.")
                    else:
                        await bot.send_message(chat_id=user_id, text=f"⚠️ Не удалось автоматически отправить сообщение напарнику @{partner_username}.")
            except Exception as e:
                logger.error(f"Ошибка отправки сообщений при срыве в панике по API: {e}")
                
        asyncio.create_task(send_help_failed())
        return web.json_response({"success": True, "message": "Срыв зафиксирован. Алерт напарнику отправлен."})
        
    return web.json_response({"error": "Unknown action"}, status=400)

async def handle_api_accept_covenant(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    from utils.states import Form
    # Получаем контекст состояний для пользователя
    state_ctx = dp.fsm.resolve_context(bot, user_id, user_id)
    
    # Удаляем предыдущее сообщение с договором, если оно было сохранено в FSM
    state_data = await state_ctx.get_data()
    msg_id = state_data.get("covenant_msg_id")
    if msg_id:
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение договора {msg_id} для {user_id}: {e}")
            
    await state_ctx.set_state(Form.waiting_for_partner)
    
    try:
        await bot.send_message(
            chat_id=user_id,
            text="✅ <b>Соглашение совести успешно подтверждено!</b>\n\n"
                 "👥 Введите **цифровой ID** вашего нового напарника (например, `123456789`) или его Telegram-юзернейм (например, `partner_username`):\n\n"
                 "💡 **РЕКОМЕНДУЕТСЯ использовать цифровой ID**, так как Telegram надежно отправляет сообщения именно по нему."
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об успешном подписании договора пользователю {user_id}: {e}")
        
    return web.json_response({"success": True})

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get("/", handle_ping),
        web.get("/dashboard", handle_webapp),
        web.get("/api/stats", handle_api_stats),
        web.post("/api/journal", handle_api_save_journal),
        web.post("/api/relapse", handle_api_log_relapse),
        web.post("/api/panic", handle_api_manage_panic),
        web.post("/api/accept_covenant", handle_api_accept_covenant)
    ])
    
    # Раздача статики стилей и скриптов WebApp
    webapp_path = os.path.join(os.path.dirname(__file__), "webapp")
    # Раздаем файлы в корне webapp (style.css, index.html) и вложенные папки js/
    app.router.add_static('/webapp', path=webapp_path, name='webapp', show_index=True)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Встроенный веб-сервер и API запущены на порту {port}")

# --- ОСНОВНОЙ ЗАПУСК ---

async def main():
    # Подключаем роутеры
    dp.include_router(common_router)
    dp.include_router(tracker_router)
    dp.include_router(checkin_router)
    dp.include_router(panic_router)
    dp.include_router(journal_router)
    
    # Регистрируем события запуска и остановки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Запускаем фоновый веб-сервер
    asyncio.create_task(start_web_server())
    
    # Запуск поллинга
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка работы бота: {e}")

if __name__ == "__main__":
    # Установка корректного event loop для Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
