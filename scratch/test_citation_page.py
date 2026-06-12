import asyncio
import aiohttp
import re

async def test_citation():
    url = "https://wol.jw.org/ru/wol/bc/r2/lp-u/1102026205/34/0"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            
            target = "чисты в этом деле"
            pos = html.find(target)
            if pos != -1:
                snippet = html[pos-300:pos+1000]
                with open("scratch/snippet.html", "w", encoding="utf-8") as f:
                    f.write(snippet)
                print("Snippet saved to scratch/snippet.html")
            else:
                print("Target not found.")

if __name__ == "__main__":
    asyncio.run(test_citation())
