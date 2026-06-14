import json
import logging
from PIL import Image
import google.generativeai as genai
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Настройка Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY не установлен! Функции ИИ будут недоступны.")

async def parse_text_schedule(text: str) -> dict:
    """
    Разбирает текстовое описание расписания приема лекарства с помощью Gemini.
    Возвращает словарь с параметрами.
    """
    if not GEMINI_API_KEY:
        return None
    
    prompt = f"""
    Проанализируй текст и выдели параметры приема лекарств.
    Текст: "{text}"
    
    Верни строго JSON-объект следующего формата (без markdown разметки и других символов):
    {{
        "name": "Название лекарства (на русском языке, с большой буквы, например, 'Аспирин')",
        "active_ingredient": "Действующее вещество лекарства (МНН, на русском языке, с большой буквы, например, 'Ацетилсалициловая кислота'). Если в тексте не указано, определи его по коммерческому названию из своей базы знаний. Если определить невозможно, верни null",
        "dosage": "Дозировка/количество для одного приема (например, '1 таблетка', '5 мг', '1 капсула', '1 шт')",
        "food_relation": "Отношение к еде (одно из: 'before_meal' (до еды), 'with_meal' (во время еды), 'after_meal' (после еды), 'none' (нет связи))",
        "times": ["Список времени приемов в формате ЧЧ:ММ (например, ['09:00', '21:00']). Если время не указано, предложи разумное дефолтное время исходя из количества раз в день (например, если 1 раз в день, то ['09:00']; если 2 раза, то ['09:00', '21:00']; если 3 раза, то ['09:00', '14:00', '21:00'])]",
        "schedule_type": "Тип расписания (одно из: 'daily' (каждый день), 'specific_days' (конкретные дни недели), 'interval' (через сколько-то дней))",
        "schedule_data": "Для 'daily' это null. Для 'specific_days' это массив чисел-индексов дней недели, где 0 - Понедельник, 6 - Воскресенье (например, [0, 2, 4] для Пн, Ср, Пт). Для 'interval' это число дней между приемами (например, 2 для приема раз в два дня)",
        "duration_days": "Длительность курса в днях (целое число, например, 7). Если не указано, верни null",
        "stock_count": "Количество таблеток/доз в аптечке, если упомянуто. Если нет, верни null"
    }}
    
    Обязательно верни только валидный JSON, без оборачивания в ```json и без лишних слов.
    """
    
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        # Для безопасности используем генерацию с температурными настройками для строгого вывода
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        # Очистим ответ от возможных остатков разметки
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        data = json.loads(result_text)
        return data
    except Exception as e:
        logger.error(f"Ошибка парсинга текста через Gemini: {e}")
        return None

async def parse_medicine_photo(image_path: str) -> dict:
    """
    Распознает лекарство по фотографии упаковки с помощью Gemini Vision.
    Возвращает название, дозировку и количество таблеток в пачке.
    """
    if not GEMINI_API_KEY:
        return None
    
    prompt = """
    Внимательно посмотри на это фото упаковки лекарства.
    Определи:
    1. Название препарата на русском языке (или оригинальное, если оно импортное, например, 'Но-шпа' или 'Нурофен').
    2. Действующее вещество препарата (МНН, на русском языке, например, 'Дротаверин' или 'Ибупрофен'). Если не написано на пачке, определи по своей базе знаний для этого бренда.
    3. Дозировку одной таблетки/дозы (например, '400 мг', '10 мг/мл', если есть).
    4. Общее количество таблеток/капсул/объем в упаковке (целое число, если указано на пачке, например, 20 или 50).
    
    Верни строго JSON-объект следующего формата:
    {
        "name": "Название лекарства (коммерческое название)",
        "active_ingredient": "Действующее вещество (МНН, на русском языке, например, 'Ибупрофен')",
        "dosage": "Дозировка лекарства (например, '400 мг' или null, если не найдено)",
        "quantity": "Количество таблеток/доз в упаковке (целое число или null, если не найдено)"
    }
    
    Обязательно верни только валидный JSON, без оборачивания в ```json и без лишних слов.
    """
    
    try:
        img = Image.open(image_path)
        model = genai.GenerativeModel("gemini-3.5-flash")
        
        response = await model.generate_content_async(
            [prompt, img],
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        data = json.loads(result_text)
        return data
    except Exception as e:
        logger.error(f"Ошибка распознавания фото через Gemini Vision: {e}")
        return None

async def check_wikipedia_drug(name: str) -> bool:
    """
    Проверяет существование лекарства/вещества через русское и украинское Wikipedia OpenSearch API.
    """
    import urllib.request
    import urllib.parse
    import json
    import asyncio
    
    cleaned_name = name.strip()
    headers = {
        'User-Agent': 'MisterTabletusBot/1.0 (contact: smmisha@github.com; generic medicine bot)'
    }
    
    for lang in ['ru', 'uk']:
        try:
            query = urllib.parse.quote(cleaned_name)
            url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=3&format=json"
            
            def fetch():
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=2.0) as response:
                        return json.loads(response.read().decode('utf-8'))
                except Exception:
                    return None
                    
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, fetch)
            if not res or len(res) < 3:
                continue
                
            titles = res[1]
            snippets = res[2]
            
            for title, snippet in zip(titles, snippets):
                if cleaned_name.lower() in title.lower() or title.lower() in cleaned_name.lower():
                    # Проверяем ключевые слова, характерные для медицинских статей
                    keywords = [
                        'лекарствен', 'препарат', 'вещество', 'витамин', 'средство', 'кислота', 
                        'таблет', 'атх', 'фармако', 'ліків', 'засіб', 'речовина', 'антибиотик',
                        'гормон', 'вакцина', 'бад'
                    ]
                    text_to_check = (title + " " + snippet).lower()
                    if any(kw in text_to_check for kw in keywords):
                        return True
        except Exception:
            pass
            
    return False

async def validate_medicine_name(name: str) -> bool:
    """
    Проверяет с помощью локального словаря, Wikipedia или regex, является ли введенная строка
    названием лекарства. Не блокирует пользователя, если это просто корректный текст.
    """
    cleaned_name = name.strip().lower()
    if not cleaned_name:
        return False
        
    # 1. Проверяем в локальном словаре (моментально)
    import database
    try:
        if await database.check_medication_dict(cleaned_name):
            return True
    except Exception as e:
        logger.error(f"Ошибка чтения локального словаря лекарств: {e}")
        
    # 2. Быстрая проверка формата (буквы, дефисы, пробелы)
    import re
    if not re.match(r"^[a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\s\-]+$", name.strip()):
        return False
        
    if len(name.strip()) < 2:
        return False

    # 3. Быстрый поиск по Wikipedia
    is_valid = await check_wikipedia_drug(name)
    if is_valid:
        try:
            await database.add_medication_dict(cleaned_name)
        except Exception as cache_err:
            logger.error(f"Не удалось кэшировать название {cleaned_name}: {cache_err}")
        return True
        
    # 4. Если в Википедии не нашли, но формат строки корректный — все равно одобряем, 
    # чтобы не блокировать ввод редких или пользовательских названий.
    return True

async def suggest_dosage(medicine_name: str) -> list:
    """
    Возвращает список рекомендаций по дозировкам с кэшированием в базе данных.
    Таймаут первого запроса к ИИ — 5.5 секунды.
    """
    fallback_dosages = ['1 таблетка', '1 капсула', '500 мг', '1 шт']
    cleaned_name = medicine_name.strip().lower()
    if not cleaned_name:
        return fallback_dosages
        
    # 1. Проверяем в локальном кэше дозировок (моментально)
    import database
    try:
        cached_dosages = await database.get_dosage_cache(cleaned_name)
        if cached_dosages:
            return cached_dosages
    except Exception as cache_err:
        logger.error(f"Ошибка чтения кэша дозировок: {cache_err}")

    if not GEMINI_API_KEY:
        return fallback_dosages
        
    prompt = f"""
    На основе названия лекарственного препарата/добавки "{medicine_name}" предложи 3-4 наиболее распространенных вариантов дозировки для одного приема (например: "500 мг", "1 таблетка", "10 мг", "1 капсула").
    Верни строго JSON-список строк, без markdown разметки.
    Пример вывода: ["500 мг", "1 таблетка", "1 капсула"]
    """
    import asyncio
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        
        # Запуск с таймаутом 5.5 секунды для первой генерации
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            ),
            timeout=5.5
        )
        
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        dosages = json.loads(result_text)
        if isinstance(dosages, list) and len(dosages) > 0:
            result_dosages = [str(d) for d in dosages[:4]]
            
            # Кэшируем полученные дозировки в БД
            try:
                await database.add_dosage_cache(cleaned_name, result_dosages)
            except Exception as save_err:
                logger.error(f"Ошибка сохранения кэша дозировок: {save_err}")
                
            return result_dosages
    except Exception as e:
        logger.error(f"Ошибка получения рекомендации дозировок от ИИ: {e}")
        
    return fallback_dosages

async def get_medicine_recommendations(medicine_name: str) -> str:
    """
    Возвращает рекомендации по приему лекарства (например, чем запивать, с чем не сочетать)
    на основе названия препарата с помощью локальной базы или Gemini с таймаутом.
    """
    cleaned_name = medicine_name.strip().lower()
    if not cleaned_name:
        return ""
        
    # 1. Проверяем в локальном кэше рекомендаций
    import database
    import asyncio
    
    try:
        cached_rec = await database.get_medication_rec(cleaned_name)
        if cached_rec:
            return cached_rec
    except Exception as e:
        logger.error(f"Ошибка чтения кэша рекомендаций: {e}")
        
    # 2. Если нет в кэше, опрашиваем Gemini с таймаутом 4 секунды
    if not GEMINI_API_KEY:
        return "Принимайте лекарство согласно инструкции. Запивайте достаточным количеством воды."
        
    prompt = f"""
    Дай краткую рекомендацию по приему лекарства/БАДа "{medicine_name}" (буквально 2-3 предложения).
    Расскажи, как его правильно принимать (например, до/после еды, чем лучше запивать, с чем нельзя сочетать, например, с алкоголем или молоком).
    Используй дружелюбный тон от лица заботливого медицинского маскота "Мистера Таблетуса".
    Не давай дисклеймеров, пиши сразу суть.
    """
    
    fallback = "Рекомендуется принимать согласно инструкции на упаковке. Запивайте чистой водой, избегайте приема алкоголя во время курса лечения."
    
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        # Оборачиваем запрос в таймаут 4 секунды
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(temperature=0.3)
            ),
            timeout=4.0
        )
        rec_text = response.text.strip()
        
        if rec_text:
            # Кэшируем результат
            try:
                await database.add_medication_rec(cleaned_name, rec_text)
            except Exception as cache_err:
                logger.error(f"Не удалось кэшировать рекомендации: {cache_err}")
            return rec_text
            
    except asyncio.TimeoutError:
        logger.warning(f"Таймаут получения рекомендаций для {medicine_name}")
    except Exception as e:
        logger.error(f"Ошибка получения рекомендаций через Gemini: {e}")
        
    return fallback


async def search_medicine_image(medicine_name: str) -> str:
    """
    Ищет изображение упаковки лекарства в Bing Images и возвращает URL.
    """
    import urllib.request
    import urllib.parse
    import re
    import asyncio
    
    query = urllib.parse.quote(f"{medicine_name} упаковка")
    url = f"https://www.bing.com/images/search?q={query}&form=HDRSC2"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    def fetch():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
            murls = re.findall(r'murl&quot;:&quot;([^&]+?)&quot;', html)
            if murls:
                return murls[0].replace('&amp;', '&')
        except Exception as e:
            logger.error(f"Ошибка поиска изображения для {medicine_name}: {e}")
        return None
        
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch)



