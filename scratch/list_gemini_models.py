import asyncio
import aiohttp
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.config import settings

async def list_gemini_models():
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY is not set!")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                print("Available Gemini Models:")
                for model in data.get("models", []):
                    print(f"- {model['name']} (supportedActions: {model.get('supportedGenerationMethods')})")
            else:
                print(f"Failed to list models: {response.status}")
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(list_gemini_models())
