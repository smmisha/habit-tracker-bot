"""
Три шага SOS из проверенных карточек. ИИ здесь не используется.

Техники пересказаны своими словами. Источники:
- профилактика срывов Марлатта: https://pubmed.ncbi.nlm.nih.gov/10890810/
- осознанная профилактика срывов (MBRP), Боуэн и др.: https://pubmed.ncbi.nlm.nih.gov/24647726/
- планы «если…, то…», Гольвитцер и Ширан, 2006:
  https://www.socmot.uni-konstanz.de/publications/implementation-intentions-and-goal-achievement-meta-analysis-effects-and-processes
- ACT при проблемном просмотре порнографии: https://pubmed.ncbi.nlm.nih.gov/27157029
- HALT — практика групп поддержки, не результат исследования
"""
from collections import Counter

from services.relapse_stats import normalize_trigger

INTERNET_TRIGGER = "Искушение в интернете"
LONELY_TRIGGER = "Одиночество / Грусть"

# Ночь по времени пользователя: с 22:00 до 06:00
NIGHT_FROM_HOUR = 22
NIGHT_UNTIL_HOUR = 6

CARDS = {
    "remove_source": {
        "title": "Убери источник",
        "description": "Положи телефон в другую комнату экраном вниз или выйди сам. Пока источник под рукой, тяга держится дольше.",
        "source": "Марлатт, профилактика срывов: ситуации высокого риска",
    },
    "wave": {
        "title": "Пережди волну",
        "description": (
            "Тяга нарастает, доходит до пика и спадает, как волна. Не спорь с ней и не исполняй её: "
            "несколько минут медленно дыши и замечай, где в теле она ощущается и как меняется."
        ),
        "source": "Боуэн и др., MBRP",
    },
    "look_ahead": {
        "title": "Досмотри до конца",
        "description": (
            "Представь не первые минуты, а то, что будет через час: пустота, чувство вины, обнулённый счётчик. "
            "Стоит ли оно того?"
        ),
        "source": "практика профилактики срывов",
    },
    "halt": {
        "title": "Что со мной сейчас?",
        "description": (
            "Проверь себя: голоден, раздражён, одинок или устал? Поешь, выйди пройтись, напиши близкому человеку "
            "или ложись спать, а телефон оставь вне спальни."
        ),
        "source": "HALT, практика групп поддержки (не исследование)",
    },
    # Описанием двух следующих карточек служат записи самого пользователя
    "if_then": {"title": "Мой план", "source": "Гольвитцер и Ширан"},
    "reason": {"title": "Ради чего", "source": "ACT, мотивационное интервью"},
    "support": {
        "title": "Не оставайся один",
        "description": (
            "Напиши или позвони тому, кому доверяешь. Подробности не нужны: "
            "«Мне сейчас тяжело, поддержи меня» — уже достаточно."
        ),
        "source": "социальная поддержка",
    },
}


def build_sos_cards(triggers: list, plans: dict, local_hour: int) -> list[dict]:
    """
    triggers — причины всех срывов пользователя, plans — результат user_plans.get_plans,
    local_hour — текущий час по времени пользователя.
    """
    counts = Counter(normalize_trigger(reason) for reason in triggers if reason)
    top = max(counts.values(), default=0)

    def is_most_frequent(trigger: str) -> bool:
        # При равенстве частыми считаются все причины с наибольшим числом срывов
        return top > 0 and counts[trigger] == top

    night = local_hour >= NIGHT_FROM_HOUR or local_hour < NIGHT_UNTIL_HOUR
    first = CARDS["remove_source" if is_most_frequent(INTERNET_TRIGGER) or night else "halt"]

    own = next((kind for kind in ("if_then", "reason") if plans[kind]), None)
    if own:
        third = {**CARDS[own], "description": "\n".join(f"• {plan.text}" for plan in plans[own])}
    elif is_most_frequent(LONELY_TRIGGER):
        third = CARDS["support"]
    else:
        third = CARDS["look_ahead"]

    return [dict(first), dict(CARDS["wave"]), dict(third)]
