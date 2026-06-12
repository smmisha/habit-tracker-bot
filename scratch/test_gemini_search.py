import asyncio
import aiohttp
import sys
import os

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import settings

async def test_gemini_search():
    print("=== Тестирование Gemini Search Grounding ===")
    
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY не установлен!")
        return
        
    # Используем модель проекта
    model = "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = (
        "Каков точный ежедневный стих (цитата) и текст стиха на сайте wol.jw.org на русском языке на сегодня, 9 июня 2026 года? "
        "Сделай поиск в Google. Найди страницу wol.jw.org/ru/wol/h/r2/lp-u/2026/6/9. "
        "Верни ответ строго в формате JSON с полями 'citation' (например, 2 Коринфянам 7:11) и 'text' (сам стих на русском). "
        "Не добавляй разметку markdown, напиши только сырой JSON."
    )
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "tools": [
            {"googleSearch": {}}
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
            if response.status == 200:
                data = await response.json()
                print("Ответ от Gemini (с поиском):")
                try:
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    print(text)
                except Exception as e:
                    print("Ошибка извлечения текста:", e)
                    print(data)
            else:
                print(f"Ошибка API: {response.status}")
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(test_gemini_search())
