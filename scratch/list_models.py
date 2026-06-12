import asyncio
import aiohttp
import sys
import os

# Добавляем родительскую директорию в sys.path, чтобы импортировать config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import settings

async def list_models():
    api_key = settings.mistral_api_key
    if not api_key:
        print("MISTRAL_API_KEY не установлен в .env")
        return
        
    url = "https://api.mistral.ai/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                print("Доступные модели Mistral:")
                models = sorted([m["id"] for m in data.get("data", [])])
                for m in models:
                    print(f"- {m}")
            else:
                print(f"Ошибка API: {response.status}")
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(list_models())
