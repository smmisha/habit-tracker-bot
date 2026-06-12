import asyncio
import aiohttp
import re

async def test_structure():
    url = "https://wol.jw.org/ru/wol/h/r2/lp-u/2026/6/9"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            
            # Найдём все заголовки h2 или h3, или другие разделители дней
            matches = list(re.finditer(r'<h[1-6][^>]*>(.*?)</h[1-6]>', html, re.IGNORECASE))
            print(f"Found {len(matches)} headers:")
            for m in matches:
                clean_header = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                print(f"- Position {m.start()}: {clean_header}")
                
            # Давай найдем "Вторник, 9 июня" или "9"
            target_str = "9"
            target_pos = html.find("Вторник, 9")
            if target_pos != -1:
                print(f"\nFound 'Вторник, 9' at position {target_pos}")
                # Выведем кусок HTML вокруг этой позиции
                print(html[target_pos-200:target_pos+2000])

if __name__ == "__main__":
    asyncio.run(test_structure())
