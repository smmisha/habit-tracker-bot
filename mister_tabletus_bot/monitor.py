import os
import sys
import time
import urllib.request
import urllib.parse
import json
import logging
import asyncio
from datetime import datetime

# Пытаемся импортировать asyncpg для работы с базой данных
try:
    import asyncpg
except ImportError:
    print("Ошибка: библиотека 'asyncpg' не установлена.")
    print("Пожалуйста, установите её перед запуском скрипта: pip install asyncpg")
    sys.exit(1)

# ==================== НАСТРОЙКИ МОНИТОРИНГА ====================
# Вы можете прописать настройки прямо здесь (в кавычках) 
# или задать их через переменные окружения на вашем хостинге.
# ==============================================================

# Токен вашего Телеграм-бота, который будет слать уведомления
BOT_TOKEN = ""

# ID чата или канала для отправки уведомлений (например, "-1002220456108" или "1496819884")
MONITOR_CHAT_ID = ""

# Ссылка на базу данных PostgreSQL (Supabase)
# Пример: "postgresql://postgres.xxx:password@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
DATABASE_URL = ""

# ==============================================================

# Если переменные в коде выше пустые, пробуем прочитать их из окружения
BOT_TOKEN = BOT_TOKEN or os.getenv("MONITOR_BOT_TOKEN") or os.getenv("BOT_TOKEN")
MONITOR_CHAT_ID = MONITOR_CHAT_ID or os.getenv("MONITOR_CHAT_ID")
DATABASE_URL = DATABASE_URL or os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("bot_monitor")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if os.path.dirname(os.path.abspath(__file__)) else "."
REPORT_FILE_PATH = os.path.join(SCRIPT_DIR, "last_daily_report.txt")

def send_telegram_message(text: str):
    """Отправляет сообщение в Telegram напрямую через API"""
    if not BOT_TOKEN or not MONITOR_CHAT_ID:
        logger.error("Ошибка: BOT_TOKEN или MONITOR_CHAT_ID не заданы!")
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": MONITOR_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            if not res_data.get("ok"):
                logger.error(f"Ошибка API Telegram: {res_data}")
            else:
                logger.info(f"Сообщение отправлено в {MONITOR_CHAT_ID}")
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление: {e}")

async def get_all_bots_status():
    """Подключается к PostgreSQL и запрашивает статусы ботов"""
    if not DATABASE_URL:
        return [], "Ошибка: DATABASE_URL не задана!"

    conn = None
    try:
        # Подключаемся напрямую к базе данных
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0, timeout=10.0)
        
        # На всякий случай проверяем существование таблицы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_status (
                name TEXT PRIMARY KEY,
                last_ping TEXT
            )
        """)
        
        rows = await conn.fetch("SELECT name, last_ping FROM bot_status")
        return [dict(r) for r in rows], None
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return [], str(e)
    finally:
        if conn:
            await conn.close()

def get_last_daily_report_time() -> float:
    """Читает время последнего суточного отчета из файла"""
    try:
        if os.path.exists(REPORT_FILE_PATH):
            with open(REPORT_FILE_PATH, "r") as f:
                return float(f.read().strip())
    except Exception as e:
        logger.error(f"Не удалось прочитать время суточного отчета: {e}")
    return 0.0

def set_last_daily_report_time(t: float):
    """Записывает время последнего суточного отчета в файл"""
    try:
        with open(REPORT_FILE_PATH, "w") as f:
            f.write(str(t))
    except Exception as e:
        logger.error(f"Не удалось записать время суточного отчета: {e}")

async def main():
    logger.info("Запуск системы мониторинга...")
    
    # Проверка обязательных настроек
    if not BOT_TOKEN or not MONITOR_CHAT_ID or not DATABASE_URL:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Задайте настройки BOT_TOKEN, MONITOR_CHAT_ID и DATABASE_URL в начале скрипта!")
        # Отправляем сообщение в консоль, чтобы пользователь сразу заметил
        print("\n=== ВНИМАНИЕ! ===")
        print("Вам нужно открыть этот файл в текстовом редакторе и указать:")
        print("1. BOT_TOKEN")
        print("2. MONITOR_CHAT_ID")
        print("3. DATABASE_URL")
        print("=================\n")
        return

    logger.info(f"Мониторинг успешно запущен. Чат для отчетов: {MONITOR_CHAT_ID}")
    
    bot_states = {}
    last_db_error_alert = 0.0
    
    while True:
        try:
            rows, error_msg = await get_all_bots_status()
            now = datetime.utcnow()
            
            if error_msg:
                logger.error(f"Ошибка проверки статуса базы: {error_msg}")
                if time.time() - last_db_error_alert > 3600:
                    send_telegram_message(
                        f"🚨 *Мониторинг:* Ошибка подключения монитора к базе данных:\n`{error_msg}`"
                    )
                    last_db_error_alert = time.time()
            else:
                for r in rows:
                    bot_name = r["name"]
                    last_ping_str = r["last_ping"]
                    
                    if "." in last_ping_str:
                        last_ping_str = last_ping_str.split(".")[0]
                        
                    try:
                        last_ping = datetime.fromisoformat(last_ping_str)
                    except Exception as parse_err:
                        logger.error(f"Ошибка парсинга даты для бота {bot_name}: {parse_err}")
                        continue
                        
                    diff_seconds = (now - last_ping).total_seconds()
                    
                    if bot_name not in bot_states:
                        bot_states[bot_name] = {"last_alert": 0.0, "is_offline": False}
                    
                    # Если пинга нет больше 15 минут
                    if diff_seconds > 900:
                        minutes_offline = int(diff_seconds // 60)
                        
                        if not bot_states[bot_name]["is_offline"] or (time.time() - bot_states[bot_name]["last_alert"] > 3600):
                            send_telegram_message(
                                f"🚨 *Внимание!* Бот `{bot_name}` не отвечает уже более *{minutes_offline}* минут!\n"
                                f"Пожалуйста, проверьте статус приложения."
                            )
                            bot_states[bot_name]["last_alert"] = time.time()
                            bot_states[bot_name]["is_offline"] = True
                    else:
                        if bot_states[bot_name]["is_offline"]:
                            send_telegram_message(
                                f"🟢 *Восстановление:* Бот `{bot_name}` снова в строю!"
                            )
                        bot_states[bot_name]["is_offline"] = False
                        bot_states[bot_name]["last_alert"] = 0.0
                
                # Суточный отчет (раз в 24 часа)
                last_report = get_last_daily_report_time()
                if time.time() - last_report > 86400:
                    report_lines = []
                    for r in rows:
                        b_name = r["name"]
                        state = bot_states.get(b_name, {})
                        is_off = state.get("is_offline", False)
                        status_icon = "❌ Не активен" if is_off else "✅ Активен"
                        report_lines.append(f"🤖 *{b_name}*: {status_icon}")
                    
                    if not report_lines:
                        report_lines.append("_Нет зарегистрированных ботов для мониторинга._")
                        
                    report_text = "📊 *Суточный отчет о работе ботов:*\n\n" + "\n".join(report_lines)
                    send_telegram_message(report_text)
                    set_last_daily_report_time(time.time())
            
        except Exception as loop_err:
            logger.error(f"Ошибка в цикле: {loop_err}")
            
        await asyncio.sleep(300)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Мониторинг остановлен.")
