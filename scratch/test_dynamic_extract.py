import asyncio
import aiohttp
import re

async def test_dynamic(url, chapter, verse_range_start, verse_range_end=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    
    if verse_range_end is None:
        verse_range_end = verse_range_start
        
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            
            full_text = []
            for v in range(verse_range_start, verse_range_end + 1):
                # Search for span with id="v{any_book_num}-{chapter}-{v}-{part}"
                pattern = rf'<span[^>]*id="v\d+-{chapter}-{v}-[^"]*"[^>]*>(.*?)</span>'
                matches = re.findall(pattern, html, re.DOTALL)
                
                v_text_parts = []
                for match in matches:
                    # Clean tags
                    # 1. Remove fn and b links
                    cleaned = re.sub(r'<a[^>]*class="[^"]*(?:fn|b)[^"]*"[^>]*>.*?</a>', '', match)
                    # 2. Remove vl and vp links
                    cleaned = re.sub(r'<a[^>]*class="[^"]*(?:vl|vp)[^"]*"[^>]*>.*?</a>', '', cleaned)
                    # 3. Strip tags
                    cleaned = re.sub(r'<[^>]+>', '', cleaned)
                    cleaned = cleaned.replace('\xa0', ' ').replace('\u202f', ' ').strip()
                    v_text_parts.append(cleaned)
                    
                if v_text_parts:
                    joined_v_text = " ".join(" ".join(v_text_parts).split())
                    full_text.append(f"{v} {joined_v_text}")
                else:
                    output.append(f"Warning: verse {v} not found on page")
                    
            output.append(f"\n--- Result for {url} (Chapter {chapter}, Verses {verse_range_start}-{verse_range_end}) ---")
            output.append(" ".join(full_text))

output = []

async def main():
    # 2 Corinthians 7:11
    await test_dynamic("https://wol.jw.org/ru/wol/bc/r2/lp-u/1102026205/34/0", 7, 11)
    
    # Proverbs 11:2 (from yesterday)
    await test_dynamic("https://wol.jw.org/ru/wol/bc/r2/lp-u/1102026205/32/0", 11, 2)
    
    with open("scratch/dynamic_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print("Saved results to scratch/dynamic_results.txt")

if __name__ == "__main__":
    asyncio.run(main())
