"""Подсчеты по записанным срывам: причины и время суток."""
from services.recovery_tasks import to_user_time

# Часть суток: подпись, первый час, час окончания
DAY_PARTS = (
    ("Утро, с 6 до 12", 6, 12),
    ("День, с 12 до 18", 12, 18),
    ("Вечер, с 18 до 23", 18, 23),
    ("Ночь, с 23 до 6", 23, 6),
)
WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def normalize_trigger(reason: str) -> str:
    """Объединяет свободный ввод и служебные причины для статистики"""
    if reason.startswith("Другое:") or reason.startswith("Текстовое описание:"):
        return "Другая причина"
    if reason == "Ручной сброс через меню бота":
        return "Без указания причины"
    return reason


def _day_part(hour: int) -> int:
    for index, (_, start, end) in enumerate(DAY_PARTS):
        if start <= hour < end:
            return index
    return len(DAY_PARTS) - 1  # ночь переходит через полночь


def relapse_timing(user, relapses) -> dict:
    """
    Когда чаще срывы, по времени пользователя.
    Отмеченные задним числом не учитываются: время у них условное.
    """
    parts = [0] * len(DAY_PARTS)
    weekdays = [0] * len(WEEKDAY_LABELS)
    late = 0
    for relapse in relapses:
        if relapse.is_late_mark:
            late += 1
            continue
        local = to_user_time(user, relapse.timestamp)
        parts[_day_part(local.hour)] += 1
        weekdays[local.weekday()] += 1

    return {
        "total": sum(parts),
        "late_excluded": late,
        "parts": [{"label": label, "count": count} for (label, _, _), count in zip(DAY_PARTS, parts)],
        "weekdays": [{"label": label, "count": count} for label, count in zip(WEEKDAY_LABELS, weekdays)],
    }
