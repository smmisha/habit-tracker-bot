import os
from pathlib import Path
from dotenv import load_dotenv

# Определение базовой директории
BASE_DIR = Path(__file__).resolve().parent

# Загрузка переменных окружения
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_FILE = os.getenv("DB_FILE", "tabletus.db")
DATABASE_URL = os.getenv("DATABASE_URL")


ALLOWED_USERS = []
allowed_users_raw = os.getenv("ALLOWED_USERS")
if allowed_users_raw:
    for item in allowed_users_raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.isdigit() or (item.startswith("-") and item[1:].isdigit()):
            ALLOWED_USERS.append(int(item))
        else:
            ALLOWED_USERS.append(item.lower().replace("@", ""))


DB_PATH = BASE_DIR / DB_FILE
PHOTOS_DIR = BASE_DIR / "photos"

# Создание директории для хранения фото, если её нет
PHOTOS_DIR.mkdir(exist_ok=True)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в файле .env!")
