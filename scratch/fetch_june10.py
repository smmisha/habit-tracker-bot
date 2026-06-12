import asyncio
import aiohttp

async def fetch_june10():
    url = "https://wol.jw.org/ru/wol/h/r2/lp-u/2026/6/10"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            with open("scratch/june10.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("Saved HTML to scratch/june10.html")

if __name__ == "__main__":
    asyncio.run(fetch_june10())
