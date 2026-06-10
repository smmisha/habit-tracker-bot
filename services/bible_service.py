import urllib.request
import re
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

# Локальный список ободряющих стихов на случай отсутствия сети или блокировок
LOCAL_VERSES = [
    {
        "citation": "1 Коринфянам 10:13",
        "text": "Вас постигло искушение не иное, как человеческое; и верен Бог, Который не попустит вам быть искушаемыми сверх сил, но при искушении даст и облегчение, так чтобы вы могли перенести.",
        "commentary": "Бог всегда дает выход из любого испытания. Когда наступает тяга, помни: это состояние временно, и у тебя есть силы перенести его."
    },
    {
        "citation": "Иакова 1:12",
        "text": "Блажен человек, который переносит искушение, потому что, быв испытан, он получит венец жизни, который обещал Господь любящим Его.",
        "commentary": "Каждая победа над сиюминутным желанием делает твой дух крепче и приближает тебя к истинной свободе."
    },
    {
        "citation": "Притчи 4:23",
        "text": "Больше всего хранимого храни сердце твое, потому что из него источники жизни.",
        "commentary": "Твои мысли определяют твои поступки. Оберегай свой разум от нечистых образов, так как они отравляют твою жизнь."
    },
    {
        "citation": "Галатам 5:16",
        "text": "Я говорю: поступайте по духу, и вы не будете исполнять вожделений плоти.",
        "commentary": "Сосредоточься на полезных делах, духовных целях и созидании. Наполни свою жизнь смыслом, и плохим привычкам не останется места."
    },
    {
        "citation": "Римлянам 12:2",
        "text": "И не сообразуйтесь с веком сим, но преобразуйтесь обновлением ума вашего, чтобы вам познавать, что есть воля Божия, благая, угодная и совершенная.",
        "commentary": "Отказ от PMO — это не просто воздержание, это полное обновление твоего мышления и взгляда на мир."
    },
    {
        "citation": "Матфея 26:41",
        "text": "Бодрствуйте и молитесь, чтобы не впасть в искушение: дух бодр, плоть же немощна.",
        "commentary": "Будь бдителен. Искушение часто приходит в моменты усталости или одиночества. Будь наготове защитить свою чистоту."
    },
    {
        "citation": "1 Петра 5:8-9",
        "text": "Трезвитесь, бодрствуйте, потому что противник ваш диавол ходит, как рыкающий лев, ища, кого поглотить. Противостойте ему твердою верою...",
        "commentary": "Искушение активно пытается увести тебя с правильного пути. Противостой ему решительно с первых секунд, не вступая в компромиссы."
    },
    {
        "citation": "Филиппийцам 4:13",
        "text": "Все могу в укрепляющем меня Иисусе.",
        "commentary": "Тебе не нужно справляться только своими силами. Проси поддержки у Бога, и Он даст тебе силу выстоять."
    },
    {
        "citation": "Притчи 24:16",
        "text": "Ибо семь раз упадет праведник, и встанет; а нечестивые впадут в погибель.",
        "commentary": "Даже если в прошлом были неудачи, праведного человека отличает то, что он всегда встает и продолжает борьбу. Твой путь продолжается!"
    },
    {
        "citation": "2 Тимофею 2:22",
        "text": "Юношеских похотей убегай, а держись правды, веры, любви, мира со всеми призывающими Господа от чистого сердца.",
        "commentary": "Лучший способ победить искушение — физически убежать от него. Закрой вкладку, отложи телефон, выйди на свежий воздух."
    }
]

class BibleService:
    def get_local_verse(self) -> dict:
        """Получить стих из локальной базы на основе текущего дня года"""
        day_of_year = datetime.now().timetuple().tm_yday
        idx = day_of_year % len(LOCAL_VERSES)
        return LOCAL_VERSES[idx]

    def parse_citation(self, citation_str: str):
        """
        Парсит главу и стихи из строки цитаты (например, "2 Кор. 7:11", "Иона 1:1—4").
        Возвращает кортеж (глава, список_стихов).
        """
        try:
            # Очищаем от HTML и лишних пробелов
            citation_str = re.sub(r'<[^>]+>', '', citation_str).strip()
            citation_str = " ".join(citation_str.split())
            
            if ":" not in citation_str:
                return None, None
                
            before_colon, after_colon = citation_str.rsplit(":", 1)
            
            # Находим главу (число непосредственно перед двоеточием)
            chapter_match = re.search(r'(\d+)\s*$', before_colon)
            if not chapter_match:
                return None, None
            chapter = int(chapter_match.group(1))
            
            # Находим стихи
            # Проверяем диапазон (через дефис или длинное тире)
            range_match = re.search(r'(\d+)\s*[\-——–]\s*(\d+)', after_colon)
            if range_match:
                start_v = int(range_match.group(1))
                end_v = int(range_match.group(2))
                verses = list(range(start_v, end_v + 1))
            else:
                # Перечисление через запятую или одиночный стих
                parts = re.findall(r'\d+', after_colon)
                if parts:
                    verses = [int(p) for p in parts]
                else:
                    return None, None
            return chapter, verses
        except Exception as e:
            logger.error(f"Error parsing citation '{citation_str}': {e}")
            return None, None

    async def fetch_full_verse(self, citation_link: str, citation_text: str) -> str:
        """
        Переходит по ссылке цитаты на wol.jw.org и извлекает полный текст стиха/стихов.
        """
        import aiohttp
        
        chapter, verses = self.parse_citation(citation_text)
        if not chapter or not verses:
            logger.warning(f"Could not parse chapter/verses from citation '{citation_text}'")
            return None
            
        url = citation_link
        if not url.startswith("http"):
            url = f"https://wol.jw.org{url}"
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        full_text_parts = []
                        for v in verses:
                            # Ищем тег span с id="v{любая_книга}-{chapter}-{v}-{часть}"
                            pattern = rf'<span[^>]*id="v\d+-{chapter}-{v}-[^"]*"[^>]*>(.*?)</span>'
                            matches = re.findall(pattern, html, re.DOTALL)
                            
                            v_text_parts = []
                            for match in matches:
                                # Удаляем ссылки на сноски (класс fn) и перекрестные ссылки (класс b)
                                cleaned = re.sub(r'<a[^>]*class="[^"]*(?:fn|b)[^"]*"[^>]*>.*?</a>', '', match)
                                # Удаляем номер стиха (класс vl или vp)
                                cleaned = re.sub(r'<a[^>]*class="[^"]*(?:vl|vp)[^"]*"[^>]*>.*?</a>', '', cleaned)
                                # Удаляем оставшиеся HTML-теги
                                cleaned = re.sub(r'<[^>]+>', '', cleaned)
                                # Убираем неразрывные пробелы
                                cleaned = cleaned.replace('\xa0', ' ').replace('\u202f', ' ').strip()
                                v_text_parts.append(cleaned)
                                
                            if v_text_parts:
                                joined_v_text = " ".join(" ".join(v_text_parts).split())
                                if len(verses) > 1:
                                    full_text_parts.append(f"[{v}] {joined_v_text}")
                                else:
                                    full_text_parts.append(joined_v_text)
                                    
                        if full_text_parts:
                            return " ".join(full_text_parts)
        except Exception as e:
            logger.error(f"Error fetching full verse from {url}: {e}")
            
        return None

    async def fetch_daily_text(self) -> dict:
        """
        Пытается спарсить стих дня с сайта wol.jw.org на русском языке.
        Использует aiohttp и точечную изоляцию контейнера даты во избежание сдвига на день назад/вперед.
        Затем переходит по ссылке цитаты для извлечения полного текста стиха.
        При неудаче пробует Gemini API с Google Search, при критических ошибках/лимитах — локальный список.
        """
        import aiohttp
        import json
        
        # Определяем текущую дату по часовому поясу Киева
        tz = pytz.timezone("Europe/Kyiv")
        now = datetime.now(tz)
        
        # Строка даты в формате data-date="2026-06-09T00:00:00.000Z"
        date_str = f"{now.year:04d}-{now.month:02d}-{now.day:02d}T00:00:00.000Z"
        
        # Пробуем несколько возможных форматов ссылок (с lp-u, так как для русского языка на wol используется u)
        urls_to_try = [
            f"https://wol.jw.org/ru/wol/h/r2/lp-u/{now.year}/{now.month}/{now.day}",
            f"https://wol.jw.org/ru/wol/dt/r2/lp-u/{now.year}/{now.month}/{now.day}"
        ]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Connection": "keep-alive"
        }
        
        for url in urls_to_try:
            try:
                logger.info(f"Attempting to fetch daily text directly from {url} using robust parsing...")
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Ищем блок для конкретной целевой даты
                            start_pattern = f'data-date="{date_str}"'
                            start_match = re.search(start_pattern, html)
                            if not start_match:
                                logger.warning(f"Date block {date_str} not found in HTML from {url}")
                                continue
                                
                            start_idx = start_match.start()
                            # Находим конец блока (следующий контейнер tabContent или конец текста)
                            next_tab_match = re.search(r'class="tabContent"', html[start_idx + len(start_pattern):])
                            if next_tab_match:
                                end_idx = start_idx + len(start_pattern) + next_tab_match.start()
                            else:
                                end_idx = len(html)
                                
                            day_html = html[start_idx:end_idx]
                            
                            # Парсим стих дня (класс themeScrp) внутри блока этого дня
                            scripture_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', day_html, re.DOTALL)
                            # Парсим комментарий дня (класс sb) внутри блока этого дня
                            commentary_match = re.search(r'<p[^>]*class="[^"]*sb[^"]*"[^>]*>(.*?)</p>', day_html, re.DOTALL)
                            
                            if scripture_match:
                                clean_scripture = re.sub(r'<[^>]+>', '', scripture_match.group(1)).strip()
                                clean_scripture = " ".join(clean_scripture.split())
                                
                                # Пробуем извлечь ссылку на цитату и вытащить полный стих
                                clean_verse_content = clean_scripture
                                display_citation = f"Стих дня ({now.strftime('%d.%m.%Y')})"
                                
                                link_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', scripture_match.group(1), re.DOTALL)
                                if link_match:
                                    citation_link = link_match.group(1)
                                    citation_text = re.sub(r'<[^>]+>', '', link_match.group(2)).strip()
                                    citation_text = " ".join(citation_text.split())
                                    
                                    logger.info(f"Parsed citation link: {citation_link}, text: {citation_text}")
                                    display_citation = f"{citation_text} ({now.strftime('%d.%m.%Y')})"
                                    
                                    full_text = await self.fetch_full_verse(citation_link, citation_text)
                                    if full_text:
                                        logger.info("Successfully fetched full verse text!")
                                        clean_verse_content = full_text
                                
                                clean_commentary = ""
                                if commentary_match:
                                    clean_commentary = re.sub(r'<[^>]+>', '', commentary_match.group(1)).strip()
                                    clean_commentary = " ".join(clean_commentary.split())
                                
                                logger.info(f"Successfully scraped and isolated daily text for {date_str}")
                                return {
                                    "citation": display_citation,
                                    "text": clean_verse_content,
                                    "commentary": clean_commentary if clean_commentary else "Ободряющие размышления на сегодня."
                                }
            except Exception as e:
                logger.warning(f"Failed to directly fetch daily text from {url}: {e}")
                
        # Если прямой парсинг не удался (например, из-за блокировки IP на Render),
        # пробуем запросить у Gemini API с включенным поиском (Google Search Grounding).
        logger.warning("Direct fetch failed. Trying Gemini API with Google Search grounding...")
        try:
            from config.config import settings
            
            api_key = settings.gemini_api_key
            if api_key and api_key.strip() not in ("", "your_gemini_api_key_here"):
                model = "gemini-3.1-flash-lite"  # Используем основную модель проекта
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                
                months_ru = {
                    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
                    5: "мая", 6: "июня", 7: "июля", 8: "августа",
                    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
                }
                month_name = months_ru.get(now.month, "января")
                
                prompt = (
                    f"Найди через Google Поиск стих дня на сегодня ({now.day} {month_name} {now.year} года) "
                    "с сайта wol.jw.org на русском языке. "
                    "Тебе нужно найти точную цитату (например, '2 Коринфянам 7:11'), текст этого стиха и абзац размышления/комментария под ним.\n"
                    "Верни ответ строго в формате JSON со следующими полями:\n"
                    "- 'citation': цитата стиха\n"
                    "- 'text': текст стиха на русском\n"
                    "- 'commentary': размышление под стихом\n"
                    "Пиши только чистый JSON, без markdown разметки (не используй ```json)."
                )
                
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt}
                            ]
                        }
                    ],
                    "tools": [
                        {"googleSearch": {}}
                    ]
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(gemini_url, json=payload, headers={"Content-Type": "application/json"}, timeout=15) as response:
                        if response.status == 200:
                            data = await response.json()
                            res_text = data['candidates'][0]['content']['parts'][0]['text']
                            res_clean = res_text.strip().replace("```json", "").replace("```", "").strip()
                            parsed = json.loads(res_clean)
                            if parsed.get("citation") and parsed.get("text"):
                                logger.info("Successfully fetched daily text via Gemini Google Search!")
                                return {
                                    "citation": parsed["citation"],
                                    "text": parsed["text"],
                                    "commentary": parsed.get("commentary", "Ободряющие размышления на сегодня.")
                                }
                        else:
                            logger.error(f"Gemini Search API returned status {response.status}: {await response.text()}")
        except Exception as e:
            logger.error(f"Failed to fetch daily text via Gemini Google Search: {e}")
                
        # Возвращаем локальный стих, если все попытки не удались
        logger.warning("All online daily text attempts failed. Using local backup.")
        return self.get_local_verse()

bible_service = BibleService()
