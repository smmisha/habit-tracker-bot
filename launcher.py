import subprocess
import sys
import os
import time

def main():
    print("LAUNCHER DATABASE ENV KEYS:", [k for k in os.environ.keys() if "DATABASE" in k or "URL" in k])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    habits_dir = base_dir
    tabletus_dir = os.path.join(base_dir, "mister_tabletus_bot")

    # Формируем переменные окружения для Трекера привычек
    habits_db = os.getenv("HABITS_DATABASE_URL", "")
    habits_token = os.getenv("HABITS_BOT_TOKEN", "")
    habits_env = os.environ.copy()
    if habits_token:
        habits_env["BOT_TOKEN"] = habits_token
    if habits_db:
        if habits_db.startswith("postgresql://"):
            habits_db = habits_db.replace("postgresql://", "postgresql+asyncpg://", 1)
        habits_env["DATABASE_URL"] = habits_db
        
    # Формируем переменные окружения для Мистера Таблетуса
    tabletus_db = os.getenv("TABLETUS_DATABASE_URL", "")
    tabletus_token = os.getenv("TABLETUS_BOT_TOKEN", "")
    tabletus_env = os.environ.copy()
    if tabletus_token:
        tabletus_env["BOT_TOKEN"] = tabletus_token
    if tabletus_db:
        if tabletus_db.startswith("postgresql+asyncpg://"):
            tabletus_db = tabletus_db.replace("postgresql+asyncpg://", "postgresql://", 1)
        tabletus_env["DATABASE_URL"] = tabletus_db

    print("=== LAUNCHER: Start Bots ===")
    
    p1 = None
    p2 = None

    # Запуск бота Трекера привычек
    if habits_token:
        print("Starting Habit Tracker Bot...")
        p1 = subprocess.Popen([sys.executable, "main.py"], cwd=habits_dir, env=habits_env)
    else:
        print("Habit Tracker Bot is disabled (HABITS_BOT_TOKEN not set).")

    # Запуск бота Мистера Таблетуса
    if tabletus_token:
        print("Starting Mister Tabletus Bot...")
        tabletus_py = os.path.join(tabletus_dir, "venv", "Scripts", "python.exe")
        if not os.path.exists(tabletus_py):
            tabletus_py = sys.executable
        p2 = subprocess.Popen([tabletus_py, "main.py"], cwd=tabletus_dir, env=tabletus_env)
    else:
        print("Mister Tabletus Bot is disabled (TABLETUS_BOT_TOKEN not set).")

    try:
        while True:
            # Проверяем состояние первого процесса (Трекер привычек)
            if p1 is not None and p1.poll() is not None:
                print("[Launcher] Habit Tracker Bot stopped. Restarting in 5s...")
                time.sleep(5)
                p1 = subprocess.Popen([sys.executable, "main.py"], cwd=habits_dir, env=habits_env)
                
            # Проверяем состояние второго процесса (Мистер Таблетус)
            if p2 is not None and p2.poll() is not None:
                print("[Launcher] Mister Tabletus Bot stopped. Restarting in 5s...")
                time.sleep(5)
                p2 = subprocess.Popen([tabletus_py, "main.py"], cwd=tabletus_dir, env=tabletus_env)
                
            # Если оба бота выключены, просто завершаем работу лаунчера
            if p1 is None and p2 is None:
                print("[Launcher] Both bots are disabled. Exiting.")
                break

            time.sleep(1)
    except KeyboardInterrupt:
        print("=== LAUNCHER: Stopping bots... ===")
        if p1 is not None:
            p1.terminate()
        if p2 is not None:
            p2.terminate()
        if p1 is not None:
            p1.wait()
        if p2 is not None:
            p2.wait()
        print("=== LAUNCHER: All processes stopped ===")

if __name__ == "__main__":
    main()
