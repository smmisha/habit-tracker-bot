import os
import sys
import time
import urllib.request
import urllib.parse
import json
import logging
from datetime import datetime

# Добавляем родительскую директорию в path, чтобы импортировать database и config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("bot_monitor")

# Настройки получателя уведомлений
# MONITOR_CHAT_ID может быть ID чата (например, 1496819884), ID канала (например, -1002220456108)
# или публичным юзернеймом канала (например, @my_channel_status).
# Настраивается через переменные окружения, по умолчанию отправляет владельцу бота.
MONITOR_CHAT_ID = os.getenv("MONITOR_CHAT_ID", "1496819884")
BOT_TOKEN = os.getenv("MONITOR_BOT_TOKEN", config.BOT_TOKEN)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE_PATH = os.path.join(SCRIPT_DIR, "last_daily_report.txt")

def send_telegram_message(text: str):
    """Отправляет сообщение в Telegram канал или чат напрямую через Bot API"""
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
                logger.error(f"Ошибка отправки сообщения: {res_data}")
            else:
                logger.info(f"Сообщение успешно отправлено в {MONITOR_CHAT_ID}")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в Telegram: {e}")

async def get_all_bots_status():
    """Получает текущие статусы всех зарегистрированных ботов из БД"""
    try:
        rows = await database.fetch_all(
            "SELECT name, last_ping FROM bot_status",
            "SELECT name, last_ping FROM bot_status"
        )
        return rows, None
    except Exception as e:
        logger.error(f"Ошибка запроса статуса ботов из БД: {e}")
        return [], str(e)

def get_last_daily_report_time() -> float:
    """Читает время последнего суточного отчета из файла"""
    try:
        if os.path.exists(REPORT_FILE_PATH):
            with open(REPORT_FILE_PATH, "r") as f:
                return float(f.read().strip())
    except Exception as e:
        logger.error(f"Не удалось прочитать время последнего суточного отчета: {e}")
    return 0.0

def set_last_daily_report_time(t: float):
    """Записывает время последнего суточного отчета в файл"""
    try:
        with open(REPORT_FILE_PATH, "w") as f:
            f.write(str(t))
    except Exception as e:
        logger.error(f"Не удалось записать время суточного отчета: {e}")

async def main():
    logger.info(f"Запуск Мульти-мониторинга ботов (Получатель: {MONITOR_CHAT_ID})...")
    await database.init_db()
    
    # Словарь для отслеживания состояния каждого бота:
    # { 'bot_name': { 'last_alert': timestamp, 'is_offline': bool } }
    bot_states = {}
    last_db_error_alert = 0.0
    
    while True:
        try:
            rows, error_msg = await get_all_bots_status()
            now = datetime.utcnow()
            
            if error_msg:
                logger.error(f"Ошибка проверки статуса базы данных: {error_msg}")
                if time.time() - last_db_error_alert > 3600:
                    send_telegram_message(
                        f"🚨 *Мониторинг:* Ошибка подключения монитора к базе данных:\n`{error_msg}`"
                    )
                    last_db_error_alert = time.time()
            else:
                for r in rows:
                    bot_name = r["name"]
                    last_ping_str = r["last_ping"]
                    
                    # Убираем миллисекунды из строки
                    if "." in last_ping_str:
                        last_ping_str = last_ping_str.split(".")[0]
                        
                    try:
                        last_ping = datetime.fromisoformat(last_ping_str)
                    except Exception as parse_err:
                        logger.error(f"Ошибка парсинга даты '{last_ping_str}' для бота {bot_name}: {parse_err}")
                        continue
                        
                    diff_seconds = (now - last_ping).total_seconds()
                    
                    # Инициализируем состояние бота в памяти, если его нет
                    if bot_name not in bot_states:
                        bot_states[bot_name] = {"last_alert": 0.0, "is_offline": False}
                    
                    # Если пинга нет больше 15 минут (900 секунд)
                    if diff_seconds > 900:
                        minutes_offline = int(diff_seconds // 60)
                        
                        # Если бот до этого работал нормально — отправляем аларм сразу
                        # Если уже лежал — отправляем напоминание раз в час
                        if not bot_states[bot_name]["is_offline"] or (time.time() - bot_states[bot_name]["last_alert"] > 3600):
                            send_telegram_message(
                                f"🚨 *Внимание!* Бот `{bot_name}` не отвечает уже более *{minutes_offline}* минут!\n"
                                f"Пожалуйста, проверьте статус приложения."
                            )
                            bot_states[bot_name]["last_alert"] = time.time()
                            bot_states[bot_name]["is_offline"] = True
                    else:
                        # Бот работает нормально.
                        # Если до этого он лежал — присылаем сообщение о восстановлении
                        if bot_states[bot_name]["is_offline"]:
                            send_telegram_message(
                                f"🟢 *Восстановление:* Бот `{bot_name}` снова в строю и отправляет сигналы активности!"
                            )
                        
                        bot_states[bot_name]["is_offline"] = False
                        bot_states[bot_name]["last_alert"] = 0.0
                
                # Проверяем необходимость отправки суточного отчета по всем ботам
                last_report = get_last_daily_report_time()
                if time.time() - last_report > 86400:
                    report_lines = []
                    for r in rows:
                        b_name = r["name"]
                        b_ping = r["last_ping"]
                        
                        # Определяем статус
                        state = bot_states.get(b_name, {})
                        is_off = state.get("is_offline", False)
                        
                        status_icon = "❌ Не активен" if is_off else "✅ Активен"
                        report_lines.append(f"🤖 *{b_name}*: {status_icon} (последний пинг: {b_ping} UTC)")
                    
                    if not report_lines:
                        report_lines.append("_Нет зарегистрированных ботов для мониторинга._")
                        
                    report_text = "📊 *Суточный отчет о работе ботов:*\n\n" + "\n".join(report_lines)
                    send_telegram_message(report_text)
                    set_last_daily_report_time(time.time())
            
        except Exception as loop_err:
            logger.error(f"Критическая ошибка цикла монитора: {loop_err}")
            
        # Пауза 5 минут
        await asyncio.sleep(300)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Мониторинг остановлен.")
