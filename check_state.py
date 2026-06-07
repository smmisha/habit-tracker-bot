import sqlite3
import os
from datetime import datetime
import pytz

db_path = "bot.db"
if not os.path.exists(db_path):
    print("Database bot.db does not exist!")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 1. Данные пользователя
        cursor.execute("SELECT id, username, checkin_time, timezone, forgot_count FROM users WHERE id = 5037862619")
        user = cursor.fetchone()
        if user:
            print("=== Данные пользователя ===")
            print(f"ID: {user[0]}")
            print(f"Username: {user[1]}")
            print(f"Время чек-ина: '{user[2]}'")
            print(f"Часовой пояс: {user[3]}")
            print(f"forgot_count: {user[4]}")
            
            # Локальное время
            user_tz = pytz.timezone(user[3])
            user_now = datetime.now(user_tz)
            print(f"Локальное время пользователя: {user_now.strftime('%d.%m.%Y %H:%M:%S')}")
            
        # 2. Логи за сегодня
        cursor.execute("SELECT * FROM checkin_logs WHERE checkin_date = '2026-06-07'")
        logs = cursor.fetchall()
        print("\n=== Чек-ины за сегодня ===")
        if not logs:
            print("Сегодняшних логов чек-ина нет в базе данных.")
        else:
            for log in logs:
                print(f"ID: {log[0]}, User ID: {log[1]}, Дата: {log[2]}, Статус: {log[3]}, Время: {log[4]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
