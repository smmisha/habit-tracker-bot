import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Определяем корневую директорию проекта
BASE_DIR = Path(__file__).parent.parent

class Settings(BaseSettings):
    bot_token: str = Field(default="your_bot_token_here")
    api_id: int = Field(default=0)
    api_hash: str = Field(default="your_api_hash_here")
    database_url: str = Field(default="sqlite+aiosqlite:///bot.db")
    gemini_api_key: str = Field(default="")
    mistral_api_key: str = Field(default="")

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Инициализируем настройки
settings = Settings()
