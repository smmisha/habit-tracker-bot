import asyncio
import aiohttp
import re

async def test_scrape():
    url = "https://wol.jw.org/ru/wol/h/r2/lp-u/2026/6/9"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    print(f"Fetching {url}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                print(f"Status: {response.status}")
                html = await response.text()
                print(f"Successfully read {len(html)} characters.")
                
                # Check for scriptures
                scripture_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                commentary_match = re.search(r'<p[^>]*class="[^"]*sb[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                
                if scripture_match:
                    clean_scripture = re.sub(r'<[^>]+>', '', scripture_match.group(1)).strip()
                    print(f"FOUND Scripture: {clean_scripture}")
                else:
                    print("Scripture not found in HTML. Snippet:")
                    print(html[:1000])
    except Exception as e:
        print(f"Scraping error: {e}")

if __name__ == "__main__":
    asyncio.run(test_scrape())
