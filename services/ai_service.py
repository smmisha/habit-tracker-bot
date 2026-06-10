import aiohttp
import logging
from config.config import settings

logger = logging.getLogger(__name__)

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
                async with aiohttp.ClientSession() as session:
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

    async def generate_sos_response(self, user_feeling: str) -> str:
        """
        Генерирует индивидуальное поддерживающее сообщение от ИИ
        в зависимости от того, что написал пользователь в SOS-режиме.
        """
        prompt = (
            "Ты — эмпатичный, поддерживающий и мудрый психолог-коуч по преодолению зависимостей (особенно PMO). "
            "Пользователь нажал кнопку SOS (Паника) в боте трекера чистоты, потому что он на грани срыва. "
            f"Его текущее состояние/мысли: \"{user_feeling}\".\n\n"
            "Напиши теплое, поддерживающее сообщение на русском языке (максимум 3-4 предложения). "
            "Дай конкретный простой совет (например, отложить телефон, сменить комнату, сделать физическое упражнение, подышать). "
            "Говори дружелюбно, без осуждения и нотаций, верь в его силы. Не используй сложные термины."
        )
        
        fallback = (
            "Сделай глубокий вдох и медленный выдох. 🧘‍♂️\n\n"
            "Помни, что тяга — это просто химическая реакция в мозге, и она ослабнет через несколько минут. "
            "Отложи телефон в сторону, смени обстановку (выйди на прогулку или в другую комнату) и сделай 15 приседаний. "
            "Ты сильнее, чем этот мимолетный импульс!"
        )
        return await self._call_gemini(prompt, fallback)

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
        )
        
        fallback = f"☀️ Отлично! Твой день прошел чисто. Текущий стрик: {streak_days} дн. Продолжай в том же духе!"
        return await self._call_gemini(prompt, fallback)

    async def generate_relapse_response(self, trigger_reason: str) -> str:
        """
        Генерирует теплое сочувствующее сообщение после срыва.
        """
        prompt = (
            "Ты — сострадательный, поддерживающий психолог-коуч по преодолению зависимостей. "
            f"У пользователя произошел срыв (причина: \"{trigger_reason}\"). Он сбросил счетчик.\n\n"
            "Напиши теплое поддерживающее сообщение на русском языке (2-3 предложения). "
            "Никакого осуждения, стыда или нотаций. Поддержи его веру в себя, напомни, что срыв — это "
            "опыт на пути к свободе, и вдохнови продолжить путь с новыми силами."
        )
        
        fallback = (
            "😔 Очень жаль. Счетчик сброшен. Но помни: срыв — это не поражение, а повод сделать работу над ошибками. "
            "Не сдавайся, твой стрик чистоты начат заново! Ты справишься."
        )
        return await self._call_gemini(prompt, fallback)

    async def generate_chat_response(self, contents: list) -> str:
        """
        Генерирует ответ ИИ в рамках диалога поддержки с учетом контекста беседы.
        """
        if self.api_key and self.api_key.strip() not in ("", "your_gemini_api_key_here"):
            system_instruction = (
                "Ты — эмпатичный, но твердый психолог-коуч по преодолению зависимостей (особенно PMO). "
                "Пользователь находится в состоянии тяги и общается с тобой в чате экстренной помощи SOS. "
                "Внимание: пользователь может пытаться оправдать себя, торговаться или искать лазейки для срыва. "
                "Твоя задача — тепло, но твердо возвращать его к реальности, разоблачать уловки ума и помогать ему "
                "закрыть мессенджер и переключиться на другое занятие (спорт, прогулка, молитва). "
                "Не поддерживай его оправдания. Отвечай кратко (2-3 предложения), дружелюбно и практично."
            )
            
            payload = {
                "contents": contents,
                "systemInstruction": {
                    "parts": [
                        {"text": system_instruction}
                    ]
                }
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.url, json=payload, headers={"Content-Type": "application/json"}) as response:
                        if response.status == 200:
                            data = await response.json()
                            text = data['candidates'][0]['content']['parts'][0]['text']
                            return text.strip()
                        else:
                            error_text = await response.text()
                            logger.error(f"Gemini API returned status {response.status}: {error_text}")
            except Exception as e:
                logger.error(f"Error calling Gemini API in chat mode: {e}")

        return "Я понимаю, что тебе сейчас тяжело. Но помни: это просто импульс, который пройдет. Не веди внутренний диалог, займи себя делом прямо сейчас."

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
            "человека, который борется с зависимостью (PMO) и сохраняет чистоту. "
            f"Текущий стрик чистоты пользователя: {streak_days} дней.\n"
            "Фраза должна быть без кавычек, длиной до 10-12 слов. "
            "Она должна быть глубокой, вдохновляющей и практичной, например: \"Каждый день чистоты — это инвестиция в твою свободу\" "
            "или \"Твоя сила растет в моменты, когда ты говоришь себе нет\". "
            "Не используй избитые клише."
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
            "Ты — профессиональный, эмпатичный и проницательный психолог-коуч по преодолению зависимостей (в частности, PMO).\n"
            "Перед тобой список ежедневных заметок (дневник) пользователя за последнюю неделю:\n"
            f"{entries_text}\n"
            "Проанализируй эти записи и составь короткий, поддерживающий психологический отчет-разбор на русском языке (до 150-200 слов).\n"
            "Сделай следующее:\n"
            "1. Выдели его эмоциональное состояние на этой неделе (какие эмоции преобладали).\n"
            "2. Выяви потенциальные триггеры тяги, о которых он упоминал (усталость, скука, одиночество, стресс и т.д.).\n"
            "3. Напиши 1-2 практических совета о том, на что обратить внимание на следующей неделе, чтобы закрепить результат.\n"
            "Говори бережно, поддерживающе, но профессионально и точно. Форматируй текст красиво с использованием Markdown."
        )
        
        fallback = "Продолжайте вести дневник! ИИ проанализирует ваши записи, когда их накопится достаточно."
        return await self._call_gemini(prompt, fallback)

    async def generate_dynamic_sos_steps(self, total_relapses: int, triggers: list, journal_notes: list) -> list:
        """
        Генерирует 3 персонализированных шага первой помощи на основе истории пользователя.
        Возвращает список словарей [{'title': '...', 'description': '...'}, ...]
        """
        import json
        
        triggers_summary = ", ".join(triggers) if triggers else "нет зафиксированных триггеров"
        journal_summary = "\n".join([f"- {n}" for n in journal_notes]) if journal_notes else "нет записей за неделю"
        
        prompt = (
            "Ты — эмпатичный, профессиональный психотерапевт и коуч по борьбе с зависимостями.\n"
            "Пользователь нажал кнопку экстренной помощи (SOS), так как чувствует сильную тягу.\n\n"
            f"Статистика пользователя:\n"
            f"- Всего срывов: {total_relapses}\n"
            f"- Основные триггеры прошлых срывов: {triggers_summary}\n"
            f"- Последние записи в его дневнике:\n{journal_summary}\n\n"
            "Составь ровно 3 персонализированных, кратких, практических шага первой помощи, чтобы помочь ему справиться с тягой прямо сейчас. "
            "Каждый шаг должен быть коротким (1-2 предложения), четким и бить точно в его уязвимые места (например, если в дневнике стресс — "
            "дать дыхательную практику; если скука — простое физическое действие; если искушение в сети — убрать девайсы).\n\n"
            "Ответ должен быть строго в формате JSON, содержащим список из 3 объектов, каждый из которых имеет поля 'title' и 'description'. "
            "Не используй Markdown разметку ```json в ответе, пиши только сырой JSON. Пример формата:\n"
            '[\n  {"title": "Шаг 1: ...", "description": "..."},\n  {"title": "Шаг 2: ...", "description": "..."},\n  {"title": "Шаг 3: ...", "description": "..."}\n]'
        )
        
        fallback_list = [
            {
                "title": "Шаг 1: Искренняя молитва",
                "description": "Обратитесь к Богу в молитве о силе и самообладании. Это поможет переключить фокус мыслей."
            },
            {
                "title": "Шаг 2: Полезное чтение",
                "description": "Откройте сегодняшний стих дня или прочтите ободряющие мысли, чтобы наполнить разум правильными образами."
            },
            {
                "title": "Шаг 3: Физическое упражнение",
                "description": "Сделайте 20 отжиманий/приседаний или умойтесь ледяной водой. Физическое действие снимет импульс."
            }
        ]
        
        try:
            res_text = await self._call_gemini(prompt, "")
            if res_text:
                res_text_clean = res_text.strip().replace("```json", "").replace("```", "").strip()
                parsed = json.loads(res_text_clean)
                if isinstance(parsed, list) and len(parsed) == 3:
                    return parsed
        except Exception as e:
            logger.error(f"Ошибка генерации или парсинга динамических SOS-шагов: {e}")
            
        return fallback_list

    async def generate_daily_bible_verse(self) -> dict:
        """
        Генерирует библейский стих и размышление на основе ИИ в формате JSON.
        Возвращает словарь {'citation': '...', 'text': '...', 'commentary': '...'}
        """
        import json
        prompt = (
            "Выбери один ободряющий и сильный библейский стих на русском языке, помогающий человеку "
            "в борьбе с искушениями, тягой к вредным привычкам (PMO) или в развитии самообладания и стойкости.\n\n"
            "Ответ должен быть строго в формате JSON без разметки markdown (пиши только сырой JSON). "
            "Словарь должен содержать три строковых поля:\n"
            "1. 'citation' — Книга, глава и стих (например, '1 Коринфянам 10:13').\n"
            "2. 'text' — Точный синодальный текст этого стиха на русском языке.\n"
            "3. 'commentary' — Краткое, глубокое, поддерживающее размышление к этому стиху (2-3 предложения), "
            "ориентированное на укрепление духа и преодоление тяги.\n\n"
            "Пример формата:\n"
            '{\n  "citation": "Притчи 4:23",\n  "text": "Больше всего хранимого храни сердце твое...",\n  "commentary": "..." \n}'
        )
        
        fallback = {
            "citation": "1 Коринфянам 10:13",
            "text": "Вас постигло искушение не иное, как человеческое; и верен Бог, Который не попустит вам быть искушаемыми сверх сил...",
            "commentary": "Бог всегда дает выход из любого испытания. Когда наступает тяга, помни: это состояние временно, и у тебя есть силы перенести его."
        }
        
        try:
            res_text = await self._call_gemini(prompt, "")
            if res_text:
                res_text_clean = res_text.strip().replace("```json", "").replace("```", "").strip()
                parsed = json.loads(res_text_clean)
                if isinstance(parsed, dict) and "citation" in parsed and "text" in parsed and "commentary" in parsed:
                    return parsed
        except Exception as e:
            logger.error(f"Ошибка генерации стиха дня через ИИ: {e}")
            
        return fallback

ai_service = GeminiAIService()
