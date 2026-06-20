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

ADMIN_ID = 1496819884
BOT_TOKEN = config.BOT_TOKEN
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE_PATH = os.path.join(SCRIPT_DIR, "last_daily_report.txt")

def send_telegram_message(text: str):
    """Отправляет сообщение в Telegram напрямую через Bot API"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_ID,
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
                logger.error(f"Ошибка отправки Telegram сообщения: {res_data}")
            else:
                logger.info("Сообщение успешно отправлено администратору")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в Telegram: {e}")

async def check_bot_status():
    """Проверяет время последнего пинга от бота в базе данных"""
    try:
        row = await database.fetch_one(
            "SELECT last_ping FROM bot_status WHERE name = 'mister_tabletus'",
            "SELECT last_ping FROM bot_status WHERE name = 'mister_tabletus'"
        )
        if not row or not row.get("last_ping"):
            return None, "Запись heartbeat не найдена в базе данных."

        last_ping_str = row["last_ping"]
        # Убираем миллисекунды, если они есть
        if "." in last_ping_str:
            last_ping_str = last_ping_str.split(".")[0]
        
        last_ping = datetime.fromisoformat(last_ping_str)
        return last_ping, None
    except Exception as e:
        logger.error(f"Ошибка при запросе статуса из БД: {e}")
        return None, str(e)

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
    logger.info("Запуск Mister Tabletus Monitor...")
    # Инициализируем базу данных
    await database.init_db()
    
    last_alert_sent = 0.0
    
    while True:
        try:
            last_ping, error_msg = await check_bot_status()
            now = datetime.utcnow()
            
            if error_msg:
                logger.error(f"Ошибка проверки здоровья бота: {error_msg}")
                # Отправляем оповещение об ошибке базы раз в час
                if time.time() - last_alert_sent > 3600:
                    send_telegram_message(
                        f"🚨 *Мониторинг:* Не удалось проверить статус бота. Ошибка соединения с БД:\n`{error_msg}`"
                    )
                    last_alert_sent = time.time()
            else:
                diff_seconds = (now - last_ping).total_seconds()
                logger.info(f"Последний heartbeat бота: {last_ping} (разница: {diff_seconds:.1f} сек)")
                
                if diff_seconds > 900:  # 15 минут (если бот пропустил 3 пинга по 5 минут)
                    # Бот завис или упал
                    if time.time() - last_alert_sent > 3600:
                        minutes_offline = int(diff_seconds // 60)
                        send_telegram_message(
                            f"🚨 *Внимание!* Бот «Мистер Таблетус» не активен уже более *{minutes_offline}* минут!\n"
                            f"Пожалуйста, проверьте логи или перезапустите сервис на Render."
                        )
                        last_alert_sent = time.time()
                else:
                    # Бот работает корректно
                    logger.info("Бот активен и работает.")
                    
                    # Проверяем необходимость отправки суточного отчета (раз в 24 часа)
                    last_report = get_last_daily_report_time()
                    if time.time() - last_report > 86400:
                        send_telegram_message(
                            "✅ *Мониторинг:* Бот «Мистер Таблетус» работает корректно. За последние 24 часа сбоев не обнаружено."
                        )
                        set_last_daily_report_time(time.time())
            
        except Exception as loop_err:
            logger.error(f"Ошибка в цикле монитора: {loop_err}")
            
        # Засыпаем на 5 минут перед следующим циклом проверки
        await asyncio.sleep(300)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Мониторинг остановлен.")
