import asyncio
import sys
import os

# Добавляем родительскую директорию в sys.path, чтобы импортировать модули проекта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.config import settings
from services.ai_service import ai_service

async def test_ai():
    output = []
    output.append("=== Тестирование AI интеграции ===")
    output.append(f"Gemini API Key: {settings.gemini_api_key[:10]}... (длина: {len(settings.gemini_api_key)})")
    output.append(f"Mistral API Key: {settings.mistral_api_key[:5]}... (длина: {len(settings.mistral_api_key)})")
    
    # 1. Тест Gemini
    output.append("\n1. Проверяем Gemini...")
    try:
        quote = await ai_service.generate_daily_motivational_quote(5)
        output.append(f"Результат Gemini: {quote}")
    except Exception as e:
        output.append(f"Ошибка Gemini: {e}")
        
    # 2. Тест Mistral (через принудительное отключение Gemini)
    output.append("\n2. Проверяем переключение на Mistral (временно отключаем Gemini)...")
    original_gemini_key = ai_service.api_key
    ai_service.api_key = "" # Сбрасываем ключ, чтобы сработал fallback
    
    try:
        quote_mistral = await ai_service.generate_daily_motivational_quote(5)
        output.append(f"Результат Mistral (fallback): {quote_mistral}")
    except Exception as e:
        output.append(f"Ошибка Mistral: {e}")
        
    # Восстанавливаем оригинальный ключ
    ai_service.api_key = original_gemini_key
    
    # 3. Тест динамических SOS-шагов через Mistral
    output.append("\n3. Тестируем генерацию SOS-шагов через Mistral...")
    ai_service.api_key = "" # снова отключаем Gemini для теста
    try:
        steps = await ai_service.generate_dynamic_sos_steps(3, ["усталость", "скука"], ["Чувствую сильное напряжение на работе", "Сложно держать фокус вечером"])
        output.append("Результат SOS-шагов от Mistral:")
        for idx, step in enumerate(steps, 1):
            output.append(f"  Шаг {idx}: {step.get('title')} -> {step.get('description')}")
    except Exception as e:
        output.append(f"Ошибка SOS через Mistral: {e}")
        
    ai_service.api_key = original_gemini_key
    
    # Записываем в UTF-8 файл
    output_path = os.path.join(os.path.dirname(__file__), 'test_ai_output.txt')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output))
    print(f"Результаты записаны в {output_path}")

if __name__ == "__main__":
    asyncio.run(test_ai())
