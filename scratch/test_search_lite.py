import asyncio
import aiohttp
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.config import settings

async def test_search():
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY is not set!")
        return

    model = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = (
        "Найди через Google Поиск стих дня на сегодня (9 июня 2026 года) с сайта wol.jw.org на русском языке. "
        "Тебе нужно найти точную цитату (например, '2 Коринфянам 7:11'), текст этого стиха и абзац размышления/комментария под ним.\n"
        "Верни ответ строго в формате JSON со следующими полями:\n"
        "- 'citation': цитата стиха\n"
        "- 'text': текст стиха на русском\n"
        "- 'commentary': размышление под стихом\n"
        "Пиши только чистый JSON, без markdown разметки (не используй ```json)."
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
                print("SUCCESS!")
                try:
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    print(text)
                except Exception as e:
                    print("Error parsing text field:", e)
                    print(data)
            else:
                print(f"FAILED ({response.status})")
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(test_search())
