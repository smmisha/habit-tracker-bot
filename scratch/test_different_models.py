import asyncio
import aiohttp
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.config import settings

async def test_models():
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY is not set!")
        return

    models = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash"
    ]

    prompt = "Ответь одним словом: привет"

    async with aiohttp.ClientSession() as session:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    print(f"Model {model}: SUCCESS -> {text}")
                else:
                    print(f"Model {model}: FAILED ({response.status}) -> {await response.text()}")

if __name__ == "__main__":
    asyncio.run(test_models())
