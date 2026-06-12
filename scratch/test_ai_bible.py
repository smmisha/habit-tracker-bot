import asyncio
import sys
import os

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import settings
from services.ai_service import ai_service

async def test_ai_bible():
    print("=== Тестирование ИИ для поиска стиха дня ===")
    
    prompt = (
        "Каков ежедневный стих и комментарий к нему на сайте wol.jw.org на русском языке на 9 июня 2026 года? "
        "Пожалуйста, напиши точную цитату (например, 2 Коринфянам 7:11), текст стиха и краткую суть комментария. "
        "Ответь строго в формате JSON с полями 'citation', 'text', 'commentary'. "
        "Если ты не знаешь точный стих на эту дату, верни JSON с пустыми полями."
    )
    
    # Тест Gemini
    print("\n1. Запрашиваем Gemini...")
    try:
        res = await ai_service._call_gemini(prompt, "{}")
        print("Ответ Gemini:")
        print(res)
    except Exception as e:
        print(f"Ошибка Gemini: {e}")
        
    # Тест Mistral
    print("\n2. Запрашиваем Mistral...")
    try:
        res_mistral = await ai_service._call_mistral(prompt)
        print("Ответ Mistral:")
        print(res_mistral)
    except Exception as e:
        print(f"Ошибка Mistral: {e}")

if __name__ == "__main__":
    asyncio.run(test_ai_bible())
