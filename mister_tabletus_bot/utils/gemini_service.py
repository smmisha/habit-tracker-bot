import json
import logging
from PIL import Image
import google.generativeai as genai
from config import GEMINI_API_KEY, GOOGLE_VISION_API_KEY


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

async def ocr_image_google_vision(image_path: str) -> Optional[str]:
    """
    Выполняет OCR над изображением с помощью Google Cloud Vision API REST-запроса.
    Возвращает объединенный текст, распознанный на картинке.
    """
    if not GOOGLE_VISION_API_KEY:
        return None
    
    import base64
    import aiohttp
    
    try:
        with open(image_path, "rb") as image_file:
            image_content = base64.b64encode(image_file.read()).decode("utf-8")
            
        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_API_KEY}"
        payload = {
            "requests": [
                {
                    "image": {
                        "content": image_content
                    },
                    "features": [
                        {"type": "TEXT_DETECTION"}
                    ]
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=8.0) as response:
                if response.status == 200:
                    result = await response.json()
                    responses = result.get("responses", [])
                    if responses and "fullTextAnnotation" in responses[0]:
                        return responses[0]["fullTextAnnotation"]["text"]
                else:
                    logger.error(f"Google Vision API вернул код {response.status}: {await response.text()}")
    except Exception as e:
        logger.error(f"Ошибка вызова Google Vision API: {e}")
    return None

async def parse_ocr_text_locally(ocr_text: str) -> Optional[dict]:
    import re
    import database
    from utils.local_recommendations import DRUG_RECS
    
    if not ocr_text:
        return None
        
    cleaned_lines = [line.strip().lower() for line in ocr_text.split('\n') if line.strip()]
    
    matched_name = None
    
    # 1. Match local recommendations triggers (fast offline matching)
    for item in DRUG_RECS:
        for trigger in item["triggers"]:
            for line in cleaned_lines:
                if trigger in line:
                    matched_name = trigger.capitalize()
                    break
            if matched_name:
                break
        if matched_name:
            break
            
    # 2. Match database medication_dict (known drugs)
    if not matched_name:
        try:
            words = []
            for line in cleaned_lines:
                for w in re.split(r'[^a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ]', line):
                    if len(w) > 3:
                        words.append(w.strip().lower())
            
            for w in words:
                if await database.check_medication_dict(w):
                    matched_name = w.capitalize()
                    break
        except Exception as e:
            logger.error(f"Error checking medication_dict during local OCR parse: {e}")
            
    if not matched_name:
        return None
        
    # We found a match! Let's extract dosage and quantity using regex
    combined = " " + " ".join(cleaned_lines) + " "
    
    # Dosage regex
    dosage_match = re.search(r'(\d+(?:\.\d+)?\s*(?:мг|г|мл|мкг|mg|g|ml|mcg|ед|units))', combined, re.IGNORECASE)
    dosage = dosage_match.group(1).strip() if dosage_match else None
    
    # Quantity regex
    quantity_match = re.search(r'(\d+)\s*(?:таб|капс|шт|таблеток|капсул|pcs|tablets|capsules|kapsuł|kapsulek|kapsułek|tabl|амп|amp)', combined, re.IGNORECASE)
    quantity = int(quantity_match.group(1)) if quantity_match else None

    
    return {
        "name": matched_name,
        "active_ingredient": None,
        "dosage": dosage,
        "quantity": quantity
    }

async def translate_to_english_via_gemini(name: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None
    import asyncio
    prompt = f"Translate the medicine name '{name}' to its English brand name or standard generic name. Return ONLY the translated name in English, without any punctuation, explanations, or extra words."
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        response = await asyncio.wait_for(
            model.generate_content_async(prompt),
            timeout=5.0
        )
        translated = response.text.strip().strip('"').strip("'")
        return translated if translated else None
    except Exception as e:
        logger.error(f"Error translating drug name via Gemini: {e}")
        return None

async def query_openfda_api(english_name: str) -> Optional[dict]:
    import urllib.request
    import urllib.parse
    import json
    import asyncio
    
    query = urllib.parse.quote(f'openfda.brand_name:"{english_name}"')
    url = f"https://api.fda.gov/drug/label.json?search={query}&limit=1"
    headers = {'User-Agent': 'MisterTabletusBot/1.0'}
    
    async def fetch(api_url):
        try:
            req = urllib.request.Request(api_url, headers=headers)
            def run_fetch():
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, run_fetch)
        except Exception:
            return None
            
    # Try brand name search first
    data = await fetch(url)
    if not data or not data.get("results"):
        # Try generic name search
        query_generic = urllib.parse.quote(f'openfda.generic_name:"{english_name}"')
        url_generic = f"https://api.fda.gov/drug/label.json?search={query_generic}&limit=1"
        data = await fetch(url_generic)
        
    if data and data.get("results"):
        result = data["results"][0]
        openfda = result.get("openfda", {})
        return {
            "brand_name": openfda.get("brand_name", [None])[0],
            "generic_name": openfda.get("generic_name", [None])[0],
            "dosage": result.get("dosage_and_administration", [None])[0],
            "warnings": result.get("warnings", [None])[0]
        }
    return None

async def parse_medicine_photo(image_path: str) -> dict:
    """
    Распознает лекарство по фотографии упаковки с помощью Google Vision OCR + Gemini,
    с автоматическим фоллбэком на чистый Gemini Vision при необходимости.
    """
    import asyncio
    
    # 1. Попытка использовать Google Cloud Vision API (очень точный, легкий и не требующий зависимостей)
    try:
        ocr_text = await ocr_image_google_vision(image_path)
        if ocr_text:
            # Пробуем разобрать локально (быстро, без вызовов AI при нагрузке)
            local_match = await parse_ocr_text_locally(ocr_text)
            if local_match and local_match.get("name") and local_match.get("dosage"):
                logger.info(f"Найдено локальное совпадение OCR: {local_match}")
                return local_match
            
            # Если локальный разбор неполный, используем Gemini для парсинга OCR текста (быстро и дешево)
            if GEMINI_API_KEY:
                prompt = f"""
                Проанализируй распознанный OCR-текст с упаковки лекарства и определи:
                1. Название препарата на русском языке (или оригинальное, если оно импортное, например, 'Но-шпа' или 'Нурофен').
                2. Действующее вещество препарата (МНН, на русском языке, например, 'Дротаверин' или 'Ибупрофен'). Если не написано в тексте, определи по своей базе знаний для этого бренда.
                3. Дозировку одной таблетки/дозы (например, '400 мг', '10 мг/мл', если есть).
                4. Общее количество таблеток/капсул/объем в упаковке (целое число, если указано, например, 20 или 50).
                
                OCR текст:
                "{ocr_text}"
                
                Верни строго JSON-объект следующего формата:
                {{
                    "name": "Название лекарства (коммерческое название)",
                    "active_ingredient": "Действующее вещество (МНН, на русском языке, например, 'Ибупрофен')",
                    "dosage": "Дозировка лекарства (например, '400 мг' или null, если не найдено)",
                    "quantity": "Количество таблеток/доз в упаковке (целое число или null, если не найдено)"
                }}
                
                Обязательно верни только валидный JSON, без оборачивания в ```json и без лишних слов.
                """
                model = genai.GenerativeModel("gemini-3.5-flash")
                response = await asyncio.wait_for(
                    model.generate_content_async(
                        prompt,
                        generation_config=genai.GenerationConfig(
                            temperature=0.1,
                            response_mime_type="application/json"
                        )
                    ),
                    timeout=5.0
                )
                
                result_text = response.text.strip()
                if result_text.startswith("```json"):
                    result_text = result_text[7:]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]
                result_text = result_text.strip()
                
                data = json.loads(result_text)
                # Если локальный парсер нашел название, но Gemini вернул кривое название, доверяем локальному
                if local_match and local_match.get("name") and not data.get("name"):
                    data["name"] = local_match["name"]
                return data
    except Exception as ocr_err:
        logger.error(f"Ошибка парсинга через Google Vision OCR + Gemini text: {ocr_err}. Фоллбэк на Gemini Vision...")

        
    # 2. Фоллбэк: прямой вызов Gemini Vision к картинке
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

    # 3. Запускаем поиск по Wikipedia и кэширование в фоновой задаче,
    # чтобы не задерживать пользователя блокирующими HTTP-запросами.
    async def bg_wiki_check():
        try:
            is_valid = await check_wikipedia_drug(name)
            if is_valid:
                await database.add_medication_dict(cleaned_name)
        except Exception as cache_err:
            logger.error(f"Ошибка фонового кэширования названия {cleaned_name}: {cache_err}")
            
    import asyncio
    asyncio.create_task(bg_wiki_check())
    return True

async def suggest_dosage(medicine_name: str) -> list:
    """
    Возвращает список рекомендаций по дозировкам с кэшированием в базе данных.
    Таймаут первого запроса к ИИ — 5.5 секунды.
    """
    fallback_dosages = ['1 таблетка', '1 капсула', '1 шт']
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
    На основе названия препарата/добавки "{medicine_name}" предложи 3-4 наиболее распространенных вариантов дозировки для одного приема (например: "500 мг", "1 таблетка", "10 мг", "1 капсула").
    
    ВАЖНО: Если введенное слово "{medicine_name}" НЕ является лекарством, витамином, БАДом или медицинским средством (например, это обычное бытовое слово, шутка, бессмыслица или предмет вроде "бред", "какашка", "стол"), предложи ТОЛЬКО нейтральные общие варианты дозировок без миллиграммов, граммов и миллилитров (например: ["1 шт", "1 таблетка", "1 капсула"]). Не предлагай для не-лекарств варианты вроде "500 мг" или "10 мл".
    
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
async def get_medicine_recommendations(medicine_name: str, lang: str = "ru") -> str:
    """
    Возвращает рекомендации по приему лекарства (например, чем запивать, с чем не сочетать)
    на основе названия препарата с помощью локальной базы, OpenFDA или Gemini с таймаутом.
    """
    cleaned_name = medicine_name.strip().lower()
    if not cleaned_name:
        return ""
        
    # 0. Проверяем в локальном словаре популярных лекарств (мгновенно, 0 вызовов к API)
    from utils import local_recommendations
    local_rec = local_recommendations.get_local_recommendation(cleaned_name, lang)
    if local_rec:
        return local_rec

    # 1. Проверяем в локальном кэше рекомендаций (с учетом языка)
    import database
    import asyncio
    
    cache_key = f"{cleaned_name}:{lang}"
    try:
        cached_rec = await database.get_medication_rec(cache_key)
        if cached_rec:
            return cached_rec
    except Exception as e:
        logger.error(f"Ошибка чтения кэша рекомендаций: {e}")
        
    # 2. Если нет в кэше, опрашиваем OpenFDA
    fda_data = None
    try:
        # Убираем скобки с действующим веществом, если они есть, для чистого поиска
        import re
        search_name = re.sub(r'\(.*?\)', '', cleaned_name).strip()
        
        # Проверяем, есть ли кириллица
        is_cyrillic = bool(re.search(r'[а-яА-ЯёЁіІїЇєЄґҐ]', search_name))
        english_name = search_name
        if is_cyrillic and GEMINI_API_KEY:
            english_name = await translate_to_english_via_gemini(search_name)
            
        if english_name:
            fda_data = await query_openfda_api(english_name)
    except Exception as fda_err:
        logger.error(f"Ошибка поиска в OpenFDA: {fda_err}")

    # Если нашли данные в OpenFDA, форматируем и переводим с помощью Gemini
    if fda_data and GEMINI_API_KEY:
        try:
            lang_names = {"ru": "русский", "uk": "украинский", "en": "английский"}
            lang_name = lang_names.get(lang, "русский")
            
            prompt = f"""
            У меня есть официальные данные по лекарству из базы FDA (на английском языке).
            Название: {fda_data.get('brand_name')} ({fda_data.get('generic_name')})
            Инструкция по применению: {fda_data.get('dosage')}
            Предупреждения/противопоказания: {fda_data.get('warnings')}
            
            Сформулируй краткую рекомендацию по приему этого лекарства на языке: {lang_name} (буквально 2-3 предложения).
            Расскажи суть: как правильно принимать (до/после еды, чем запивать, с чем не сочетать).
            Используй дружелюбный тон от лица заботливого медицинского маскота "Мистера Таблетуса".
            Не давай дисклеймеров, пиши сразу суть.
            """
            
            model = genai.GenerativeModel("gemini-3.5-flash")
            response = await asyncio.wait_for(
                model.generate_content_async(
                    prompt,
                    generation_config=genai.GenerationConfig(temperature=0.3)
                ),
                timeout=5.0
            )
            rec_text = response.text.strip()
            if rec_text:
                try:
                    await database.add_medication_rec(cache_key, rec_text)
                except Exception as cache_err:
                    logger.error(f"Не удалось кэшировать рекомендации: {cache_err}")
                return rec_text
        except Exception as trans_err:
            logger.error(f"Ошибка перевода OpenFDA данных: {trans_err}")

    # 3. Полный фоллбэк на генерацию через Gemini
    if not GEMINI_API_KEY:
        fallbacks = {
            "ru": "Принимайте лекарство согласно инструкции. Запивайте достаточным количеством воды.",
            "en": "Take the medication according to the instructions. Drink plenty of water.",
            "uk": "Приймайте ліки згідно з інструкцією. Запивайте достатньою кількістю води."
        }
        return fallbacks.get(lang, fallbacks["ru"])
    
    lang_instructions = {
        "ru": 'Ответь на русском языке.',
        "en": 'Answer in English.',
        "uk": 'Відповідай українською мовою.'
    }
    lang_instruction = lang_instructions.get(lang, lang_instructions["ru"])
    
    prompt = f"""
    Дай краткую рекомендацию по приему лекарства/БАДа "{medicine_name}" (буквально 2-3 предложения).
    Расскажи, как его правильно принимать (например, до/после еды, чем лучше запивать, с чем нельзя сочетать, например, с алкоголем или молоком).
    Используй дружелюбный тон от лица заботливого медицинского маскота "Мистера Таблетуса".
    Не давай дисклеймеров, пиши сразу суть.
    {lang_instruction}
    """
    
    fallbacks = {
        "ru": "Рекомендуется принимать согласно инструкции на упаковке. Запивайте чистой водой, избегайте приема алкоголя во время курса лечения.",
        "en": "Take according to the package instructions. Drink with water, avoid alcohol during the course of treatment.",
        "uk": "Рекомендується приймати згідно з інструкцією на упаковці. Запивайте чистою водою, уникайте вживання алкоголю під час курсу лікування."
    }
    fallback = fallbacks.get(lang, fallbacks["ru"])
    
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(temperature=0.3)
            ),
            timeout=4.0
        )
        rec_text = response.text.strip()
        
        if rec_text:
            try:
                await database.add_medication_rec(cache_key, rec_text)
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


async def classify_medicine_name(medicine_name: str) -> dict:
    """
    Классифицирует название препарата через Gemini:
    - real: реально существующий препарат/БАД
    - plausible: реалистичное, но отсутствующее в справочниках название (нужно спросить действующее вещество)
    - nonsense: обычное бытовое слово/бессмыслица (не нужно спрашивать МНН)
    """
    fallback = {"category": "real", "explanation": ""}
    if not GEMINI_API_KEY:
        return fallback
        
    prompt = f"""
    Проанализируй слово/фразу "{medicine_name}" и определи, к какой категории оно относится в контексте медицины и фармакологии:
    
    Категории:
    1. "real" - реальное существующее коммерческое название лекарства, витамина или БАД (например, "Аспирин", "Золофт", "Гидазепам", "Есцителопрам").
    2. "plausible" - вымышленное, редкое или новое слово, которое грамматически и фонетически звучит как название лекарства или БАДа, но такого препарата нет в официальных справочниках (например, "Радукпирон", "Аспиринус", "Новопасситин").
    3. "nonsense" - обычное бытовое слово, оскорбление, предмет, фрукт, овощ или любая бессмыслица, которая никак не может быть названием лекарства (например, "Какашка", "Стол", "Привет", "Дурак", "qwerty").
    
    Верни строго JSON-объект следующего формата (без markdown разметки и лишних слов):
    {{
        "category": "одно из: real, plausible, nonsense",
        "explanation": "краткое объяснение на русском языке"
    }}
    """
    import asyncio
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            ),
            timeout=5.0
        )
        
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        data = json.loads(result_text)
        if isinstance(data, dict) and "category" in data:
            return data
    except Exception as e:
        logger.error(f"Ошибка классификации названия лекарства через Gemini: {e}")
        
    return fallback


async def extract_active_ingredient_from_url(url: str, medicine_name: str) -> Optional[str]:
    """
    Скачивает страницу по URL, очищает её от HTML-тегов и с помощью Gemini
    пытается извлечь действующее вещество (МНН) для указанного лекарства.
    """
    if not GEMINI_API_KEY:
        return None
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    import asyncio
    import urllib.request
    import urllib.parse
    from typing import Optional
    
    def fetch_url():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Ошибка при скачивании URL {url}: {e}")
            return None

    loop = asyncio.get_event_loop()
    html_content = await loop.run_in_executor(None, fetch_url)
    if not html_content:
        return None
        
    # Очищаем текст от скриптов, стилей и HTML-тегов
    import re
    cleaned_text = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html_content, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'<[^>]+>', ' ', cleaned_text)
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    # Ограничиваем объем текста для отправки в модель (например, первые 15000 символов)
    truncated_text = cleaned_text[:15000]
    
    prompt = f"""
    Проанализируй текст веб-страницы и найди действующее вещество (МНН - международное непатентованное наименование) для препарата "{medicine_name}".
    Текст страницы:
    "{truncated_text}"
    
    Верни строго JSON-объект следующего формата (без markdown разметки и лишних слов):
    {{
        "active_ingredient": "Название действующего вещества на русском языке, с большой буквы (например, 'Ибупрофен'). Если действующее вещество не найдено, верни null"
    }}
    """
    
    try:
        model = genai.GenerativeModel("gemini-3.5-flash")
        response = await asyncio.wait_for(
            model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            ),
            timeout=8.0
        )
        
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        data = json.loads(result_text)
        if isinstance(data, dict):
            return data.get("active_ingredient")
    except Exception as e:
        logger.error(f"Ошибка извлечения МНН из URL через Gemini: {e}")
        
    return None





