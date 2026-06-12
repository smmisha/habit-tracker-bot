import asyncio
import aiohttp
import sys
import os

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import settings

async def test_prompts():
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY не установлен!")
        return
        
    model = "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompts = [
        # Вариант 1: Прямой вопрос
        "Напиши стих дня и размышление на сегодня (9 июня 2026 года) с сайта wol.jw.org на русском языке.",
        
        # Вариант 2: С контекстом о книге
        "Найди в своей базе знаний стих дня и размышление из брошюры 'Исследовать Писания каждый день' на 9 июня 2026 года на русском языке.",
        
        # Вариант 3: Описание конкретного стиха
        "Какой стих дня на 9 июня 2026 года в календаре ежедневных стихов Свидетелей Иеговы на русском языке?"
    ]
    
    async with aiohttp.ClientSession() as session:
        for idx, prompt in enumerate(prompts, 1):
            print(f"\n--- Пробуем Промпт #{idx} ---")
            print(f"Запрос: {prompt}")
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            }
            try:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
                    if response.status == 200:
                        data = await response.json()
                        text = data['candidates'][0]['content']['parts'][0]['text']
                        print("Ответ:")
                        print(text)
                    else:
                        print(f"Ошибка API {response.status}: {await response.text()}")
            except Exception as e:
                print(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(test_prompts())
