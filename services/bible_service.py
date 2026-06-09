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

    async def fetch_daily_text(self) -> dict:
        """
        Пытается спарсить стих дня с сайта wol.jw.org на русском языке.
        При неудаче возвращает стих из локального списка.
        """
        # Определяем текущую дату по часовому поясу Киева
        tz = pytz.timezone("Europe/Kyiv")
        now = datetime.now(tz)
        
        # Пробуем несколько возможных форматов ссылок (с lp-u, так как для русского языка на wol используется u)
        urls_to_try = [
            f"https://wol.jw.org/ru/wol/h/r2/lp-u/{now.year}/{now.month}/{now.day}",
            f"https://wol.jw.org/ru/wol/dt/r2/lp-u/{now.year}/{now.month}/{now.day}"
        ]
        
        for url in urls_to_try:
            try:
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                )
                # Открываем с таймаутом 5 секунд
                with urllib.request.urlopen(req, timeout=5) as response:
                    html = response.read().decode('utf-8')
                    
                    # Парсим стих дня (класс themeScrp)
                    scripture_match = re.search(r'<p[^>]*class="[^"]*themeScrp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                    
                    # Парсим комментарий дня (класс sb)
                    commentary_match = re.search(r'<p[^>]*class="[^"]*sb[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                    
                    if scripture_match:
                        clean_scripture = re.sub(r'<[^>]+>', '', scripture_match.group(1)).strip()
                        clean_scripture = " ".join(clean_scripture.split())
                        
                        clean_commentary = ""
                        if commentary_match:
                            clean_commentary = re.sub(r'<[^>]+>', '', commentary_match.group(1)).strip()
                            clean_commentary = " ".join(clean_commentary.split())
                        
                        logger.info(f"Successfully parsed daily text from {url}")
                        return {
                            "citation": f"Стих дня ({now.strftime('%d.%m.%Y')})",
                            "text": clean_scripture,
                            "commentary": clean_commentary if clean_commentary else "Ободряющие размышления на сегодня."
                        }
            except Exception as e:
                logger.warning(f"Failed to fetch daily text from {url}: {e}")
                
        # Если онлайн-запрос заблокирован/упал, пробуем ИИ
        logger.warning("All online daily text attempts failed. Trying AI fallback...")
        try:
            from services.ai_service import ai_service
            ai_verse = await ai_service.generate_daily_bible_verse()
            if ai_verse and "citation" in ai_verse:
                logger.info("Successfully generated daily verse using AI fallback.")
                return ai_verse
        except Exception as e:
            logger.error(f"Failed to generate daily verse via AI: {e}")

        # Возвращаем локальный стих, если ИИ тоже не ответил
        logger.warning("All online daily text and AI fallback attempts failed. Using local backup.")
        return self.get_local_verse()

bible_service = BibleService()
