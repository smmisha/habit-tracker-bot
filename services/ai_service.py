import aiohttp
import logging
from config.config import settings

logger = logging.getLogger(__name__)

# Стихи приводятся только из проверенных текстов, а не из ответов ИИ
NO_SCRIPTURE = " Не цитируй Библию и не ссылайся на библейские стихи."

# Отписки вместо личного вывода о прочитанном
GENERIC_REFLECTION_PHRASES = (
    "порно это плохо",
    "порно плохо",
    "порно это грех",
    "порно грех",
    "смотреть порно грех",
    "нельзя смотреть порно",
    "я прочитал",
    "прочитал статью",
    "хорошая статья",
    "понятно",
    "согласен",
)


class GeminiAIService:
    def __init__(self):
        self.api_key = settings.gemini_api_key
        # Используем современную и быструю модель gemini-3.1-flash-lite
        self.model = "gemini-3.1-flash-lite"
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        self._quote_cache = {}

    async def _call_gemini(self, prompt: str, fallback_text: str) -> str:
        """Вспомогательный метод для выполнения запросов к Gemini API"""
        if self.api_key and self.api_key.strip() not in ("", "your_gemini_api_key_here"):
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            }

            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                    async with session.post(self.url, json=payload, headers={"Content-Type": "application/json"}) as response:
                        if response.status == 200:
                            data = await response.json()
                            text = data['candidates'][0]['content']['parts'][0]['text']
                            return text.strip()
                        else:
                            error_text = await response.text()
                            logger.error(f"Gemini API returned status {response.status}: {error_text}")
            except Exception as e:
                logger.error(f"Error calling Gemini API: {e}")

        return fallback_text

    async def generate_clean_checkin_response(self, streak_days: int) -> str:
        """
        Генерирует короткое вдохновляющее поздравление при успешном чистом дне.
        """
        prompt = (
            "Ты — эмпатичный, поддерживающий психолог-коуч по преодолению зависимостей. "
            "Пользователь успешно завершил еще один день без срывов. "
            f"Его текущий стрик составляет {streak_days} дней.\n\n"
            "Напиши очень короткое (1-2 предложения) вдохновляющее и теплое поздравление на русском языке. "
            "Избегай банальностей, говори дружелюбно и мотивирующе, отмечая ценность его усилий."
            + NO_SCRIPTURE
        )
        
        fallback = f"☀️ Отлично! Твой день прошел чисто. Текущий стрик: {streak_days} дн. Продолжай в том же духе!"
        return await self._call_gemini(prompt, fallback)

    async def generate_milestone_reward_suggestion(self, milestone_days: int) -> str:
        """
        Генерирует предложение о том, как пользователь может вознаградить себя за достижение вехи чистоты.
        """
        prompt = (
            "Ты — эмпатичный, поддерживающий психолог-коуч по преодолению зависимостей. "
            f"Пользователь достиг важной вехи: {milestone_days} дней чистоты подряд. "
            "Предложи 1-2 конкретных, здоровых и приятных способа, как он может порадовать или вознаградить себя "
            "сегодня за это достижение (на русском языке, 1-2 предложения). "
            "Примеры: приготовить вкусное блюдо, купить интересную книгу, сходить в кино, прогуляться в красивом месте, "
            "устроить вечер отдыха. Избегай банальностей, предлагай приятные и здоровые награды, будь теплым."
            + NO_SCRIPTURE
        )
        fallback = "Побалуй себя сегодня чем-то приятным: приготовь любимое блюдо, посмотри хороший фильм или проведи вечер в уютной обстановке. Ты заслужил это!"
        return await self._call_gemini(prompt, fallback)

    async def generate_daily_motivational_quote(self, streak_days: int) -> str:
        """
        Генерирует короткую ежедневную мотивационную цитату (для отображения на карточке статуса).
        """
        from datetime import date
        today = date.today()
        cache_key = (streak_days, today)
        
        if hasattr(self, "_quote_cache") and cache_key in self._quote_cache:
            return self._quote_cache[cache_key]
            
        prompt = (
            "Напиши одну очень короткую, емкую и сильную мотивационную фразу на русском языке для поддержки "
            "человека, который освобождается от порнографии и сохраняет чистоту. "
            f"Текущий стрик чистоты пользователя: {streak_days} дней.\n"
            "Фраза должна быть без кавычек, длиной до 10-12 слов. "
            "Она должна быть глубокой, вдохновляющей и практичной, например: \"Каждый день чистоты — это инвестиция в твою свободу\" "
            "или \"Твоя сила растет в моменты, когда ты говоришь себе нет\". "
            "Не используй избитые клише."
            + NO_SCRIPTURE
        )
        
        fallback = "Каждая секунда чистоты делает тебя сильнее! Держись!"
        result = await self._call_gemini(prompt, fallback)
        
        if hasattr(self, "_quote_cache"):
            # Prune older cache entries to free memory
            keys_to_delete = [k for k in self._quote_cache.keys() if k[1] != today]
            for k in keys_to_delete:
                self._quote_cache.pop(k, None)
            self._quote_cache[cache_key] = result
            
        return result

    async def generate_weekly_journal_analysis(self, entries: list) -> str:
        """
        Генерирует еженедельный психологический анализ дневника на основе записей за последние 7 дней.
        """
        if not entries:
            return "За эту неделю записей в дневнике не обнаружено. Постарайтесь делать заметки каждый день, чтобы ИИ мог составить более точный психологический анализ вашей тяги и привычек."

        # Форматируем заметки для ИИ
        entries_formatted = []
        for e in entries:
            date_str = e.entry_date.strftime("%d.%m.%Y")
            entries_formatted.append(f"Дата: {date_str}\nЗаметка: {e.content}\n")
            
        entries_text = "\n".join(entries_formatted)

        prompt = (
            "Ты — профессиональный, эмпатичный и проницательный психолог-коуч по преодолению зависимостей (в частности, от порнографии).\n"
            "Перед тобой список ежедневных заметок (дневник) пользователя за последнюю неделю:\n"
            f"{entries_text}\n"
            "Проанализируй эти записи и составь короткий, поддерживающий психологический отчет-разбор на русском языке (до 150-200 слов).\n"
            "Сделай следующее:\n"
            "1. Выдели его эмоциональное состояние на этой неделе (какие эмоции преобладали).\n"
            "2. Выяви потенциальные триггеры тяги, о которых он упоминал (усталость, скука, одиночество, стресс и т.д.).\n"
            "3. Напиши 1-2 практических совета о том, на что обратить внимание на следующей неделе, чтобы закрепить результат.\n"
            "Говори бережно, поддерживающе, но профессионально и точно. Пиши обычным текстом без Markdown и HTML-разметки."
            + NO_SCRIPTURE
        )
        
        fallback = "Продолжайте вести дневник! ИИ проанализирует ваши записи, когда их накопится достаточно."
        return await self._call_gemini(prompt, fallback)

    async def analyze_journal_for_compromise(self, content: str) -> dict:
        """
        Фоновый анализ дневника на предмет торгов с разумом, компромиссов (типа 'посмотрел одним глазком')
        и сильного риска срыва.
        Возвращает dict: {'detected': bool, 'reason': str}
        """
        if not self.api_key or self.api_key.strip() in ("", "your_gemini_api_key_here"):
            return {"detected": False, "reason": ""}
            
        prompt = (
            "Проанализируй следующую запись в дневнике человека, который освобождается от порнографии:\n"
            f"\"{content}\"\n\n"
            "Твоя задача — определить, признается ли пользователь в компромиссе с самим собой, "
            "«торгах с разумом» (rationalization) или поведении, близком к срыву (например, «посмотрел одним глазком», "
            "«глянул картинку только на секунду», «почти сорвался, но не до конца», «проверял себя», «искал лазейки»).\n\n"
            "Верни ответ строго в формате JSON с двумя полями (без markdown разметки ```json):\n"
            "1. 'detected' — true, если обнаружен компромисс, «взгляд одним глазком» или активный саботаж/торги; false в противном случае.\n"
            "2. 'reason' — Краткое объяснение на русском языке, почему ты считаешь это компромиссом (например, 'Признание в просмотре материалов одним глазком' или 'Попытка оправдать срыв усталостью'), либо пустая строка, если ничего не обнаружено.\n\n"
            "Пример формата:\n"
            '{\n  "detected": true,\n  "reason": "Попытка оправдать компромисс («посмотрел только одним глазком»)"\n}'
        )
        
        import json
        try:
            res_text = await self._call_gemini(prompt, "")
            if res_text:
                res_text_clean = res_text.strip().replace("```json", "").replace("```", "").strip()
                parsed = json.loads(res_text_clean)
                if isinstance(parsed, dict) and "detected" in parsed and "reason" in parsed:
                    return parsed
        except Exception as e:
            logger.error(f"Ошибка фонового анализа дневника на компромиссы: {e}")
            
        return {"detected": False, "reason": ""}

    async def generate_spiritual_study_materials(self, triggers: list = None, temptation_type: str = None, temptation_types: list = None, user_notes: str = None, round: int = 1) -> dict:
        """
        Подбирает проверенное наставление, духовный шаг и статьи на wol.jw.org
        под конкретное искушение (или связку искушений). Тексты составлены заранее
        и цитируют «Перевод нового мира», ИИ здесь не используется.
        Поддерживает round=1 (первое чтение) и round=2 (углубленное изучение, если тяга осталась).
        """
        # Статьи об освобождении от порнографии: главная тема, она же подбирается по умолчанию
        porn_primary = {
            "title": "Как не угодить в ловушку Сатаны",
            "type_label": "wol.jw.org Статья",
            "icon": "🔞",
            "description": "Как противостоять порнографии, сопротивляться желаниям и что делать, если непристойные сцены всплывают в памяти.",
            "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/2019447"
        }
        porn_secondary = {
            "title": "Как держаться в стороне от порнографии?",
            "type_label": "wol.jw.org Статья",
            "icon": "🛡️",
            "description": "Как понять, где подстерегает порнография, и заранее решить, как ей не поддаться.",
            "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/102007444"
        }

        # Каталог проверенных материалов по типам искушений (все URL проверены, 200 OK)
        categories = {
            "sexting": {
                "title": "Секстинг / Интимная переписка",
                "icon": "💬",
                "primary": {
                    "title": "Что мне нужно знать о секстинге?",
                    "type_label": "wol.jw.org Книга",
                    "icon": "📱",
                    "description": "Библейский взгляд на переписку с интимным подтекстом: скрытые опасности, последствия и защита чистой совести.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/502013360"
                },
                "secondary": {
                    "title": "Как мне избавиться от навязчивых мыслей о сексе?",
                    "type_label": "wol.jw.org Статья",
                    "icon": "🧠",
                    "description": "Практические библейские шаги по очищению мыслей и переключению фокуса на духовное.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/1102008131"
                },
                "fallback_thought": (
                    "Иегова видит твое сердце и желание быть честным. Интимная переписка или отправка фото может казаться безобидной игрой, "
                    "но Библия говорит: «Даже не упоминайте о разврате, нечистоте и жадности, ведь это не подобает святым» (Эфесянам 5:3). "
                    "Не разжигай огонь, который обожжет совесть. Отец ценит твою решимость оставаться чистым."
                ),
                "fallback_action": "Прямо сейчас отложи телефон экраном вниз, выйди в другую комнату или умойся холодной водой, помолившись о самообладании.",
                "secondary_thought": (
                    "Ты продолжаешь борьбу, и твой стрик в полной безопасности! Искушение не исчезает мгновенно — "
                    "душе нужно время, чтобы наполниться мыслями Бога. Главное не спешить: дело не в количестве минут, а в том, чтобы истина достигла сердца."
                ),
                "secondary_action": "Спокойно отложи все чаты и суету, удели время вдумчивому чтению без таймеров и спешки. Молись, чтобы слово Бога коснулось сердца."
            },
            "porn": {
                "title": "Порнография / Нечистые образы",
                "icon": "🔞",
                "primary": porn_primary,
                "secondary": porn_secondary,
                "fallback_thought": (
                    "«Больше всего остального береги своё сердце, Потому что из него — источники жизни» (Притчи 4:23). "
                    "Иегова знает, как агрессивно этот мир навязывает нечистоту, и не отворачивается от тебя из-за того, что накатило искушение. "
                    "Он ждет, что ты обратишься к нему за силой. Не корми плоть ядом — наполни разум правдой Царства."
                ),
                "fallback_action": "Немедленно закрой все вкладки и приложения с триггерами, преклони колени и прочитай вслух молитву из Псалма 119:37.",
                "secondary_thought": (
                    "Ты не сдался, и это главное! То, что тяга не исчезла мгновенно — естественно. "
                    "Читай без спешки и без ограничений по времени: важно не число минут, а чтобы Слово Бога принесло мир и чистоту в сердце. "
                    "«Бог верен, и он не допустит, чтобы вы были испытаны сверх того, что можете перенести» (1 Коринфянам 10:13). Твой стрик продолжается!"
                ),
                "secondary_action": "Посвяти время чтению этой статьи без спешки. Размышляй о том, как чистота защищает твою душу и близкую дружбу с Иеговой."
            },
            "premarital_sex": {
                "title": "Желание секса с девушкой / Блуд",
                "icon": "💔",
                "primary": {
                    "title": "Зачем ждать до брака?",
                    "type_label": "wol.jw.org Книга",
                    "icon": "💔",
                    "description": "Почему сохранение чистоты до брака защищает сердце, уважение к будущей жене и близкую дружбу с Богом.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/1102008095"
                },
                "secondary": {
                    "title": "Стремись к «святости в страхе Божьем»",
                    "type_label": "wol.jw.org Статья",
                    "icon": "🕊️",
                    "description": "Как сохранить святость тела и разума, когда плоть требует компромисса.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/2008366"
                },
                "fallback_thought": (
                    "Желание близости естественно, ведь его заложил Творец, но дьявол пытается исказить его через грех до брака. "
                    "«Убегайте от сексуальной безнравственности!» (1 Коринфянам 6:18) — Библия советует не торговаться с желанием, а решительно бежать от него. "
                    "Подумай о своей будущей чистой семье и о том, как высоко Иегова ценит твою верность Ему."
                ),
                "fallback_action": "Смени обстановку прямо сейчас: займись физической нагрузкой (отжимания, прогулка) и переключи мысли на чтение статьи.",
                "secondary_thought": (
                    "Желание плоти может быть упорным, но твоё посвящение Иегове сильнее. Ты не сорвался — ты стоишь в вере! "
                    "Погрузись в размышление о святости брака и чистой совести. Читай без спешки и таймеров, наполняя разум и сердце мыслями Бога."
                ),
                "secondary_action": "Встань и выйди на свежий воздух или смени обстановку. Прочитай статью спокойно, размышляя о ценности чистой совести перед Богом."
            },
            "general": {
                "title": "Чистота мыслей и сердца",
                "icon": "✨",
                "primary": {
                    "title": "Как мне избавиться от навязчивых мыслей о сексе?",
                    "type_label": "wol.jw.org Статья",
                    "icon": "🧠",
                    "description": "Методы защиты разума, фильтрации впечатлений и переключения внимания на духовные ценности.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/1102008131"
                },
                "secondary": {
                    "title": "Бог хочет, чтобы мы были чистыми",
                    "type_label": "wol.jw.org Урок",
                    "icon": "✨",
                    "description": "Нравственная чистота и близкие отношения с Богом.",
                    "url": "https://wol.jw.org/ru/wol/d/r2/lp-u/1102021240"
                },
                "fallback_thought": (
                    "Иегова знает твою внутреннюю боль и желание оставаться верным. Искушение временно, а чистая совесть перед Богом — вечна. "
                    "«Приблизьтесь к Богу, и он приблизится к вам» (Иакова 4:8). Наполни разум духовной пищей прямо сейчас."
                ),
                "fallback_action": "Сделай 10 глубоких вдохов, выпей стакан прохладной воды и углубись в чтение предложенной статьи.",
                "secondary_thought": (
                    "Раунд 2: духовное погружение. Насыщение разума требует искреннего внимания. "
                    "Не считай минуты — главное, чтобы сердце было затронуто чистой вестью Бога. Ты продолжаешь бороться, стрик чист и невредим!"
                ),
                "secondary_action": "Открой материал, помолись Иегове о помощи и читай без спешки. Искреннее размышление вытеснит плотские мысли."
            }
        }
        
        # Определение категорий (поддержка мультивыбора):
        requested = temptation_types if temptation_types and isinstance(temptation_types, list) else [temptation_type]
        selected_keys = []
        for t in requested:
            # Старая версия приложения из кэша еще может прислать убранный тип
            if t == "masturbation":
                t = "porn"
            if isinstance(t, str) and t in categories and t not in selected_keys:
                selected_keys.append(t)
            
        if user_notes:
            notes_lower = user_notes.lower()
            if any(k in notes_lower for k in ["переспать", "добрачн", "живой секс", "секс с девушк", "блуд", "постел", "близост"]):
                if "premarital_sex" not in selected_keys:
                    selected_keys.append("premarital_sex")
            if any(k in notes_lower for k in ["секстинг", "переписк", "интимн", "пошл", "нюдс", "скинуть фот", "сообщен сексуально"]):
                if "sexting" not in selected_keys:
                    selected_keys.append("sexting")
            porn_words = [
                "порно", "порнух", "эротик", "ххх", "видео 18+", "нечистые картинки",
                "мастурб", "рукоблуд", "онанизм", "кончить", "снять напряжение", "подроч",
            ]
            if any(k in notes_lower for k in porn_words):
                if "porn" not in selected_keys:
                    selected_keys.append("porn")
                    
        if not selected_keys:
            selected_keys = ["porn"]
            
        resolved_key = selected_keys[0]
        cat_data = categories[resolved_key]
        
        # Формируем читаемый заголовок (для одного или цепочки искушений)
        if len(selected_keys) == 1:
            temptation_title = cat_data["title"]
        else:
            temptation_title = " + ".join([categories[k]["title"] for k in selected_keys])
            
        # Список материалов по всем отмеченным темам
        materials = []
        for k in selected_keys:
            mat = categories[k].get("secondary" if round == 2 else "primary", categories[k]["primary"])
            if mat not in materials:
                materials.append(mat)
        primary_material = materials[0]
        
        # Выбираем фаллбэк мысли и действия с учетом мультивыбора
        if len(selected_keys) > 1:
            if round == 2:
                thought = (
                    f"Раунд 2: глубокое духовное укрепление. Когда искушение атакует сразу с нескольких сторон ({temptation_title}), "
                    "требуется больше терпения и времени в Слове Бога. Стрик сохранен, ты стоишь в вере! Иегова рядом."
                )
                action = "Продолжай спокойное вдумчивое чтение статей ниже. Искренняя молитва и библейские мысли вытеснят навязчивые импульсы."
            else:
                thought = (
                    f"Иегова видит твою борьбу прямо сейчас: когда несколько искушений переплетаются ({temptation_title}), "
                    "давление кажется сильнее. Но Библия заверяет: «Бог верен, и он не допустит, чтобы вы были испытаны сверх того, что можете перенести» (1 Коринфянам 10:13). "
                    "Не пытайся одолеть всё разом — сделай первый шаг к духовному миру."
                )
                action = "Немедленно разорви цепь триггеров: отложи телефон экраном вниз, выйди в другую комнату, ополосни лицо холодной водой и помолись Иегове о самообладании."
        else:
            if round == 2:
                thought = cat_data.get("secondary_thought", cat_data["fallback_thought"])
                action = cat_data.get("secondary_action", cat_data["fallback_action"])
            else:
                thought = cat_data["fallback_thought"]
                action = cat_data["fallback_action"]
        
        return {
            "spiritual_thought": thought,
            "spiritual_action": action,
            "temptation_type": resolved_key,
            "temptation_types": selected_keys,
            "temptation_title": temptation_title,
            "round": round,
            "primary_material": primary_material,
            "materials": materials
        }

    async def evaluate_article_reflection(self, article_title: str, reflection_text: str) -> dict:
        """
        Проверяет искренность и содержательность вывода после чтения статьи.
        ИИ решает только «принять или нет», тексты ответа заданы заранее.
        Отсеивает чисто формальные отписки вроде 'порно это плохо и грех' без конкретной мысли или стиха.
        При недоступности Gemini мягко принимает содержательный текст (>= 20 символов).
        """
        import json
        import re

        accepted_result = {
            "accepted": True,
            "feedback": "Спасибо за искренний разбор и внимание к Слову. Вывод сохранён в твой дневник!"
        }
        rejected_result = {
            "accepted": False,
            "feedback": "Напиши чуть подробнее: что именно из статьи запомнилось, какие стихи задели и что берёшь для себя. "
                        "Общей фразы вроде «порно — это плохо и грех» мало."
        }

        clean_text = (reflection_text or "").strip()
        if len(clean_text) < 20:
            return rejected_result

        normalized = re.sub(r"[^\w\sа-яА-ЯёЁ]", "", clean_text.lower()).strip()
        normalized_words = normalized.split()
        has_scripture_hint = bool(re.search(r"\d+\s*:\s*\d+|стих|псал|матф|коринф|притч|иаков|иоан|галат|рим|быт|иегова", normalized))
        if len(normalized_words) <= 9 and any(phrase in normalized for phrase in GENERIC_REFLECTION_PHRASES) and not has_scripture_hint:
            return rejected_result

        if self.api_key and self.api_key.strip() not in ("", "your_gemini_api_key_here"):
            prompt = (
                f"Пользователь прочитал духовную статью «{article_title}» во время искушения и написал свой вывод:\n"
                f"\"{clean_text}\"\n\n"
                "Оцени, является ли это хотя бы минимально содержательным, личным выводом (что запомнил, какой стих или мысль извлёк для себя), "
                "или это чистая формальная отписка ради галочки вроде 'порно это плохо и грех' / 'хорошая статья'.\n"
                "Не будь чрезмерно строгим к стилю, ошибкам или длине, если видно искреннюю личную мысль или упоминание стиха/идеи из статьи.\n"
                "Верни строго JSON без markdown: {\"accepted\": true} или {\"accepted\": false}"
            )
            try:
                res = await self._call_gemini(prompt, "")
                if res:
                    res_clean = res.strip().replace("```json", "").replace("```", "").strip()
                    parsed = json.loads(res_clean)
                    if isinstance(parsed, dict) and "accepted" in parsed:
                        return accepted_result if parsed["accepted"] else rejected_result
            except Exception as e:
                logger.error(f"Error in evaluate_article_reflection: {e}")

        return accepted_result

ai_service = GeminiAIService()

