import urllib.request
import re
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

# Локальный список ободряющих стихов («Перевод нового мира») на случай отсутствия сети или блокировок
LOCAL_VERSES = [
    {
        "citation": "1 Коринфянам 10:13",
        "text": "Испытания, с которыми вы сталкиваетесь, обычные, с ними сталкиваются все люди. Но Бог верен, и он не допустит, чтобы вы были испытаны сверх того, что можете перенести. При испытании он даст выход, чтобы вы смогли его выдержать.",
        "commentary": "Бог всегда дает выход из любого испытания. Когда наступает тяга, помни: это состояние временно, и у тебя есть силы перенести его."
    },
    {
        "citation": "Иакова 1:12",
        "text": "Счастлив человек, который стойко переносит испытание, потому что, выдержав его, он получит в награду жизнь, которую Иегова обещал тем, кто его любит.",
        "commentary": "Каждая победа над сиюминутным желанием делает твой дух крепче и приближает тебя к истинной свободе."
    },
    {
        "citation": "Притчи 4:23",
        "text": "Больше всего остального береги своё сердце, Потому что из него — источники жизни.",
        "commentary": "Твои мысли определяют твои поступки. Оберегай свой разум от нечистых образов, так как они отравляют твою жизнь."
    },
    {
        "citation": "Галатам 5:16",
        "text": "Говорю вам: поступайте по духу, и вы не будете потакать никаким грешным желаниям.",
        "commentary": "Сосредоточься на полезных делах, духовных целях и созидании. Наполни свою жизнь смыслом, и плохим привычкам не останется места."
    },
    {
        "citation": "Римлянам 12:2",
        "text": "Больше не позволяйте миру формировать вас, но меняйтесь, обновляя свой ум, чтобы понять, в чём состоит воля Бога, и лично убедиться, что она добрая, приятная и совершенная.",
        "commentary": "Отказ от PMO — это не просто воздержание, это полное обновление твоего мышления и взгляда на мир."
    },
    {
        "citation": "Матфея 26:41",
        "text": "Бодрствуйте и постоянно молитесь, чтобы не поддаться искушению. Дух готов, но тело слабо.",
        "commentary": "Будь бдителен. Искушение часто приходит в моменты усталости или одиночества. Будь наготове защитить свою чистоту."
    },
    {
        "citation": "1 Петра 5:8, 9",
        "text": "Сохраняйте здравомыслие, будьте бдительны! Ваш враг, Дьявол, ходит, как рычащий лев, и ищет себе добычу. Противостаньте ему, оставаясь твёрдыми в вере, ведь вы знаете, что с такими же страданиями сталкиваются все ваши братья во всём мире.",
        "commentary": "Искушение активно пытается увести тебя с правильного пути. Противостой ему решительно с первых секунд, не вступая в компромиссы."
    },
    {
        "citation": "Филиппийцам 4:13",
        "text": "Всё мне под силу благодаря тому, кто меня укрепляет.",
        "commentary": "Тебе не нужно справляться только своими силами. Проси поддержки у Бога, и он даст тебе силу выстоять."
    },
    {
        "citation": "Притчи 28:13",
        "text": "Скрывающий свои грехи не будет успешен, А к тому, кто признаётся в них и перестаёт грешить, будет проявлено милосердие.",
        "commentary": "Честность открывает дорогу к помощи. Не прячь борьбу: признай ее и оставь то, что тянет назад."
    },
    {
        "citation": "2 Тимофею 2:22",
        "text": "Поэтому убегай от юношеских желаний и стремись к праведности, вере, любви и миру вместе с теми, кто с чистым сердцем призывает Господа.",
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
        При неудаче берет стих из локального проверенного списка (ИИ стихи не пересказывает).
        """
        import aiohttp
        
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
                
        # Возвращаем локальный стих, если все попытки не удались
        logger.warning("Direct daily text fetch failed. Using local backup.")
        return self.get_local_verse()

bible_service = BibleService()
