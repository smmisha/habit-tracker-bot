import os

log_path = r'c:\Users\Michael\Desktop\my proJect\Projectorium\habit_tracker_bot\bot_run.log'

if os.path.exists(log_path):
    try:
        with open(log_path, 'r', encoding='utf-16le') as f:
            lines = f.readlines()
            print("=== Last 30 lines of bot_run.log ===")
            for line in lines[-30:]:
                print(line.strip())
    except Exception as e:
        print(f"Error reading log: {e}")
else:
    print("log file not found")
