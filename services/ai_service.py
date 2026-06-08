import aiohttp
import logging
from config.config import settings

logger = logging.getLogger(__name__)

class GeminiAIService:
    def __init__(self):
        self.api_key = settings.gemini_api_key
        # Используем современную и быструю модель gemini-3.5-flash
        self.model = "gemini-3.5-flash"
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    async def _call_gemini(self, prompt: str, fallback_text: str) -> str:
        """Вспомогательный метод для выполнения запросов к Gemini API"""
        if not self.api_key or self.api_key.strip() in ("", "your_gemini_api_key_here"):
            logger.warning("Gemini API key is not configured or invalid. Using fallback.")
            return fallback_text

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
        if not self.api_key or self.api_key.strip() in ("", "your_gemini_api_key_here"):
            return "Я рядом и поддерживаю тебя. Пожалуйста, держись."

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
        return await self._call_gemini(prompt, fallback)

ai_service = GeminiAIService()
