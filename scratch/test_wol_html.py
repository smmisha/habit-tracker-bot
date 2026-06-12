import urllib.request
import re

url = "https://wol.jw.org/ru/wol/h/r2/lp-u/2026/6/9"
req = urllib.request.Request(
    url, 
    headers={'User-Agent': 'Mozilla/5.0'}
)

try:
    with urllib.request.urlopen(req, timeout=5) as response:
        html = response.read().decode('utf-8')
        
        # Находим часть HTML с сегодняшней датой "Вторник, 9 июня"
        # Для анализа выведем блок кода вокруг этой даты
        start_idx = html.find("Вторник, 9")
        if start_idx != -1:
            print("=== Found section ===")
            print(html[start_idx-200:start_idx+2000])
        else:
            print("Date not found in HTML")
            # Выведем хотя бы часть HTML
            print(html[:1000])
            
except Exception as e:
    print("Error:", e)
