import urllib.request
import urllib.parse
import re

async def test_proxy():
    target_url = "https://wol.jw.org/ru/wol/h/r2/lp-u/2026/6/9"
    
    # Список публичных бесплатных прокси-сервисов для тестирования
    proxy_urls = [
        f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(target_url)}",
        f"https://api.allorigins.win/get?url={urllib.parse.quote(target_url)}"
    ]
    
    for p_url in proxy_urls:
        print(f"\nПробуем прокси: {p_url[:80]}...")
        try:
            req = urllib.request.Request(
                p_url,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8')
                
                # Если это allorigins, то HTML упакован в JSON
                if "allorigins" in p_url:
                    import json
                    try:
                        js_data = json.loads(content)
                        content = js_data.get("contents", "")
                    except Exception as e:
                        print("Ошибка парсинга JSON allorigins:", e)
                
                # Пробуем найти стих дня
                scripture_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', content, re.DOTALL)
                commentary_match = re.search(r'<p[^>]*class="[^"]*sb[^"]*"[^>]*>(.*?)</p>', content, re.DOTALL)
                
                if scripture_match:
                    clean_scripture = re.sub(r'<[^>]+>', '', scripture_match.group(1)).strip()
                    clean_commentary = ""
                    if commentary_match:
                        clean_commentary = re.sub(r'<[^>]+>', '', commentary_match.group(1)).strip()
                        
                    print("УСПЕХ!")
                    print(f"Стих: {clean_scripture}")
                    print(f"Комментарий (первых 100 символов): {clean_commentary[:100]}...")
                    return
                else:
                    print("Стих не найден в полученном HTML. Длина HTML:", len(content))
                    if len(content) < 500:
                        print("HTML:", content)
        except Exception as e:
            print(f"Ошибка прокси: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_proxy())
