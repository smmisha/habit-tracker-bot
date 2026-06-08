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
        BotCommand(command="streak", description="📊 Мой счетчик"),
        BotCommand(command="settings", description="⚙️ Настройки"),
        BotCommand(command="panic", description="🆘 SOS / Паника"),
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
            
        return web.json_response({
            "streak_str": streak_str,
            "total_relapses": user.total_relapses,
            "calendar_days": calendar_days,
            "triggers": triggers
        })

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get("/", handle_ping),
        web.get("/dashboard", handle_webapp),
        web.get("/api/stats", handle_api_stats)
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
