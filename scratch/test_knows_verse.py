import asyncio
import aiohttp
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.config import settings

async def test_knows_verse():
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY is not set!")
        return

    model = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = (
        "Каков точный стих дня (цитата) и текст этого стиха из брошюры 'Исследовать Писания каждый день' "
        "на сегодня (9 июня 2026 года) на русском языке? "
        "Верни ответ строго в формате JSON со следующими полями:\n"
        "- 'citation': цитата стиха\n"
        "- 'text': текст стиха на русском\n"
        "- 'commentary': размышление/комментарий под ним\n"
        "Ответь только чистым JSON без разметки markdown."
    )
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
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
    asyncio.run(test_knows_verse())
