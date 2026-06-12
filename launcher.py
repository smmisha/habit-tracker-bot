import subprocess
import sys
import os
import time

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    habits_dir = base_dir
    tabletus_dir = os.path.join(base_dir, "mister_tabletus_bot")

    # Формируем переменные окружения для Трекера привычек
    habits_db = os.getenv("HABITS_DATABASE_URL", "")
    if habits_db.startswith("postgresql://"):
        habits_db = habits_db.replace("postgresql://", "postgresql+asyncpg://", 1)
        
    habits_env = os.environ.copy()
    habits_env["BOT_TOKEN"] = os.getenv("HABITS_BOT_TOKEN", "")
    habits_env["DATABASE_URL"] = habits_db
    
    # Формируем переменные окружения для Мистера Таблетуса
    tabletus_db = os.getenv("TABLETUS_DATABASE_URL", "")
    if tabletus_db.startswith("postgresql+asyncpg://"):
        tabletus_db = tabletus_db.replace("postgresql+asyncpg://", "postgresql://", 1)
        
    tabletus_env = os.environ.copy()
    tabletus_env["BOT_TOKEN"] = os.getenv("TABLETUS_BOT_TOKEN", "")
    tabletus_env["DATABASE_URL"] = tabletus_db

    print("=== LAUNCHER: Запуск ботов ===")
    
    # Запуск бота Трекера привычек
    print("Запуск Habit Tracker Bot...")
    p1 = subprocess.Popen([sys.executable, "main.py"], cwd=habits_dir, env=habits_env)

    # Запуск бота Мистера Таблетуса
    print("Запуск Mister Tabletus Bot...")
    p2 = subprocess.Popen([sys.executable, "main.py"], cwd=tabletus_dir, env=tabletus_env)

    try:
        while True:
            # Проверяем состояние первого процесса
            if p1.poll() is not None:
                print("⚠️ [Launcher] Habit Tracker Bot завершил работу. Перезапуск через 5 сек...")
                time.sleep(5)
                p1 = subprocess.Popen([sys.executable, "main.py"], cwd=habits_dir, env=habits_env)
                
            # Проверяем состояние второго процесса
            if p2.poll() is not None:
                print("⚠️ [Launcher] Mister Tabletus Bot завершил работу. Перезапуск через 5 сек...")
                time.sleep(5)
                p2 = subprocess.Popen([sys.executable, "main.py"], cwd=tabletus_dir, env=tabletus_env)
                
            time.sleep(1)
    except KeyboardInterrupt:
        print("=== LAUNCHER: Останавливаем ботов... ===")
        p1.terminate()
        p2.terminate()
        p1.wait()
        p2.wait()
        print("=== LAUNCHER: Все процессы остановлены ===")

if __name__ == "__main__":
    main()
