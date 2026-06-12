import asyncio
import aiohttp
import re
from datetime import datetime
import pytz

async def test_robust_parse():
    tz = pytz.timezone("Europe/Kyiv")
    now = datetime.now(tz)
    
    # 2026-06-09T00:00:00.000Z
    date_str = f"{now.year:04d}-{now.month:02d}-{now.day:02d}T00:00:00.000Z"
    print(f"Target date: {date_str}")
    
    url = f"https://wol.jw.org/ru/wol/h/r2/lp-u/{now.year}/{now.month}/{now.day}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            
            # Find the section starting with data-date="YYYY-MM-DDT00:00:00.000Z"
            # and end with the next tabContent or end of string
            start_pattern = f'data-date="{date_str}"'
            start_match = re.search(start_pattern, html)
            if not start_match:
                print("Could not find date section in HTML!")
                return
                
            start_idx = start_match.start()
            # Find the next tabContent block to isolate this day's text
            next_tab_match = re.search(r'class="tabContent"', html[start_idx + len(start_pattern):])
            if next_tab_match:
                end_idx = start_idx + len(start_pattern) + next_tab_match.start()
            else:
                end_idx = len(html)
                
            day_html = html[start_idx:end_idx]
            
            # Parse scripture
            scripture_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', day_html, re.DOTALL)
            commentary_match = re.search(r'<p[^>]*class="[^"]*sb[^"]*"[^>]*>(.*?)</p>', day_html, re.DOTALL)
            
            if scripture_match:
                clean_scripture = re.sub(r'<[^>]+>', '', scripture_match.group(1)).strip()
                clean_scripture = " ".join(clean_scripture.split())
                
                clean_commentary = ""
                if commentary_match:
                    clean_commentary = re.sub(r'<[^>]+>', '', commentary_match.group(1)).strip()
                    clean_commentary = " ".join(clean_commentary.split())
                    
                print("SUCCESS!")
                print(f"Scripture: {clean_scripture}")
                print(f"Commentary: {clean_commentary}")
            else:
                print("Failed to parse scripture inside the date block.")

if __name__ == "__main__":
    asyncio.run(test_robust_parse())
