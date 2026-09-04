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
                                 "Пожалуйста, пройдите чек-ин прямо сейчас."
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление в ЛС боту: {e}")

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
        if user_id <= 0:
            return web.json_response({"error": "Invalid user_id"}, status=400)
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
        checkins = {c.checkin_date: (c.status, c.excuse_reason) for c in checkins_result.scalars().all()}
        
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
            excuse_reason = None
            
            if relapse_count > 0:
                status = "relapsed"
            elif day_date in checkins:
                ch_status, ch_excuse = checkins[day_date]
                excuse_reason = ch_excuse
                if ch_status == "clean":
                    status = "clean"
                elif ch_status == "relapsed":
                    status = "relapsed"
                    
            calendar_days.append({
                "date": day_date.isoformat(),
                "status": status,
                "relapse_count": relapse_count,
                "excuse_reason": excuse_reason
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
        content = str(data.get("content", "")).strip()
        if user_id <= 0:
            return web.json_response({"error": "Invalid user_id"}, status=400)
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    if not content or len(content) < 5:
        return web.json_response({"error": "Заметка слишком короткая (минимум 5 символов)"}, status=400)
        
    if len(content) > 2000:
        return web.json_response({"error": "Заметка слишком длинная (максимум 2000 символов)"}, status=400)
        
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
        
    # Запускаем фоновый анализ записи на предмет компромиссов/самообмана
    async def run_silent_compromise_check():
        try:
            from services.ai_service import ai_service
            
            analysis = await ai_service.analyze_journal_for_compromise(content)
            if analysis.get("detected"):
                # Отправляем предупреждение самому пользователю в чат
                user_warning = (
                    f"⚠️ <b>Обнаружен компромисс и «торги с разумом»!</b>\n\n"
                    f"ИИ-помощник заметил в вашей записи опасные мысли: <i>«{analysis.get('reason')}»</i>.\n\n"
                    f"Пожалуйста, помните: компромиссы (вроде «посмотрел одним глазком» или поиск самооправданий) — "
                    f"это первый шаг к реальному срыву. Не поддавайтесь уловкам мозга!"
                )
                await bot.send_message(chat_id=user_id, text=user_warning)
        except Exception as e:
            logger.error(f"Ошибка выполнения фоновой проверки компромиссов: {e}")

    asyncio.create_task(run_silent_compromise_check())
        
    return web.json_response({"success": True, "message": f"Заметка успешно {action_text}!"})

async def handle_api_log_relapse(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        trigger_reason = str(data.get("trigger_reason", "Срыв зафиксирован через Mini App")).strip()[:500]
        if user_id <= 0:
            return web.json_response({"error": "Invalid user_id"}, status=400)
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    from database.models import User
    from handlers.tracker import execute_relapse_reset
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return web.json_response({"error": "User not found"}, status=404)
            
    # Отменяем таймер тихой тревоги, если он был активен
    from services.scheduler import scheduler
    try:
        scheduler.remove_job(f"panic_alert_{user_id}")
    except Exception:
        pass

    # Выполняем сброс счетчика чистоты и оповещение напарника по правилу скользящего окна
    await execute_relapse_reset(user_id, trigger_reason, bot=bot)
    
    return web.json_response({
        "success": True, 
        "confession_pending": False,
        "message": "Счетчик чистоты сброшен. Пожалуйста, откройте чат с ботом."
    })

async def handle_api_manage_panic(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        action = str(data.get("action", "")).strip()  # "initiate", "start", "helped" or "failed"
        trigger_reason = str(data.get("trigger_reason", "Тяга во время паники")).strip()[:500]
        if user_id <= 0 or action not in {"initiate", "start", "helped", "failed"}:
            return web.json_response({"error": "Invalid request payload"}, status=400)
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
        
        if action == "initiate":
            from services.scheduler import scheduler, send_silent_panic_alert
            try:
                scheduler.remove_job(f"panic_alert_{user_id}")
            except Exception:
                pass
                
            import pytz
            from datetime import timedelta
            kyiv_tz = pytz.timezone("Europe/Kyiv")
            run_time = datetime.now(kyiv_tz) + timedelta(minutes=5)
            
            scheduler.add_job(
                send_silent_panic_alert,
                'date',
                run_date=run_time,
                args=[user_id],
                id=f"panic_alert_{user_id}",
                replace_existing=True
            )
            logger.info(f"Запущен 5-минутный таймер тихой тревоги SOS для {user_id}")
            
            # Отправляем сообщение напарнику о начале SOS через бизнес-соединение
            if partner_username and business_connection_id:
                async def send_sos_to_partner():
                    try:
                        alert_text = await ai_service.humanize_sos_alert()
                        await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                        logger.info(f"Напарник {partner_username} уведомлен о начале SOS для {user_id}")
                    except Exception as e:
                        logger.error(f"Не удалось отправить SOS-уведомление напарнику: {e}")
                asyncio.create_task(send_sos_to_partner())
                
            return web.json_response({"success": True})
            
        elif action == "start":
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
        from services.scheduler import scheduler
        try:
            scheduler.remove_job(f"panic_alert_{user_id}")
        except Exception:
            pass
            
        async def send_help_ok():
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="🎉 <b>Отлично! Ты справился с тягой и защитил свой стрик!</b>\n\nКаждая такая победа делает тебя сильнее."
                )
                
                # Дополнительно оповещаем напарника об успехе
                if partner_username and business_connection_id:
                    alert_text = await ai_service.humanize_sos_success()
                    await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
                    logger.info(f"Напарник {partner_username} уведомлен об успешном выходе из SOS для {user_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}")
        asyncio.create_task(send_help_ok())
        return web.json_response({"success": True, "message": "Поздравляем с победой над тягой!"})
        
    elif action == "failed":
        from services.scheduler import scheduler
        try:
            scheduler.remove_job(f"panic_alert_{user_id}")
        except Exception:
            pass
            
        from database.models import User
        from handlers.tracker import execute_relapse_reset
        
        async with db_helper.session_factory() as session:
            user_db = await session.get(User, user_id)
            if not user_db:
                return web.json_response({"error": "User not found"}, status=404)
                
        # Выполняем сброс счетчика чистоты и оповещение напарника по правилу скользящего окна
        await execute_relapse_reset(user_id, f"Паника: {trigger_reason}", bot=bot)
        
        return web.json_response({
            "success": True, 
            "confession_pending": False,
            "message": "Счетчик сброшен после выхода из режима SOS. Пожалуйста, откройте чат с ботом."
        })
        
    return web.json_response({"error": "Unknown action"}, status=400)

async def handle_api_accept_covenant(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        if user_id <= 0:
            return web.json_response({"error": "Invalid request payload"}, status=400)
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
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
            
    # Не переходим в waiting_for_partner, так как напарник зафиксирован.
    # Вместо этого отправляем клавиатуру чек-ина.
    from keyboards.inline import get_checkin_keyboard
    try:
        await bot.send_message(
            chat_id=user_id,
            text="✅ <b>Соглашение совести подтверждено!</b>\n\nКак прошел сегодняшний день? Все под контролем?",
            reply_markup=get_checkin_keyboard()
        )
    except Exception as e:
        logger.error(f"Не удалось отправить клавиатуру чек-ина пользователю {user_id}: {e}")
        
    return web.json_response({"success": True})

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get("/", handle_ping),
        web.get("/dashboard", handle_webapp),
        web.get("/api/stats", handle_api_stats),
        web.post("/api/journal", handle_api_save_journal),
        web.post("/api/relapse", handle_api_log_relapse),
        web.post("/api/initiate_relapse", handle_api_log_relapse),
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
    # Проверяем, нужно ли выполнить автоматический перенос базы данных
    old_db = os.getenv("OLD_DATABASE_URL")
    new_db = os.getenv("NEW_DATABASE_URL")
    if old_db and new_db:
        logger.info("Обнаружены переменные OLD_DATABASE_URL и NEW_DATABASE_URL. Запуск автоматической миграции...")
        try:
            import migrate_on_server
            await migrate_on_server.main()
        except Exception as e:
            logger.error(f"Ошибка во время автоматического переноса базы: {e}")

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
