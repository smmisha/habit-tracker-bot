import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from services.bible_service import bible_service

async def test():
    print("=== Testing Updated bible_service ===")
    verse = await bible_service.fetch_daily_text()
    print("Result:")
    print(f"Citation: {verse.get('citation')}")
    print(f"Text: {verse.get('text')}")
    print(f"Commentary: {verse.get('commentary')}")

if __name__ == "__main__":
    asyncio.run(test())
