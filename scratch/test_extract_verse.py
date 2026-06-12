import asyncio
import aiohttp
import re

async def test_extract():
    url = "https://wol.jw.org/ru/wol/bc/r2/lp-u/1102026205/34/0"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            
            # Ищем все вхождения span с id="v47-7-11-"
            pattern = r'<span[^>]*id="v47-7-11-[^"]*"[^>]*>(.*?)</span>'
            matches = re.findall(pattern, html, re.DOTALL)
            
            output = []
            output.append(f"Found {len(matches)} span matches for v47-7-11-:")
            for idx, match in enumerate(matches, 1):
                clean_text = re.sub(r'<[^>]+>', '', match).strip()
                # Remove extra spaces/newlines
                clean_text = " ".join(clean_text.split())
                output.append(f"Match {idx} raw: {match}")
                output.append(f"Match {idx} clean: {clean_text}")
                
            with open("scratch/verse_result.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(output))
            print("Saved to scratch/verse_result.txt")

if __name__ == "__main__":
    asyncio.run(test_extract())
