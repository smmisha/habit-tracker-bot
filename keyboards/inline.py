from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_relapse_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение срыва"""
    keyboard = [
        [
            InlineKeyboardButton(text="Да, сорвался 😔", callback_data="relapse_confirm"),
            InlineKeyboardButton(text="Отмена ❌", callback_data="relapse_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    keyboard = [
        [
            InlineKeyboardButton(text="⏰ Время отчета", callback_data="cfg_time"),
            InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="cfg_tz")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_reset_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа сброса (тихий или с исповедью)"""
    keyboard = [
        [
            InlineKeyboardButton(text="🤫 Сбросить тихо", callback_data="relapse_type_quiet"),
            InlineKeyboardButton(text="📢 Сообщить напарнику", callback_data="relapse_type_confess")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="relapse_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_checkin_keyboard() -> InlineKeyboardMarkup:
    """Ежедневный чек-ин"""
    keyboard = [
        [
            InlineKeyboardButton(text="Да, сегодня чист! ☀️", callback_data="checkin_clean"),
            InlineKeyboardButton(text="Сорвался 😔", callback_data="checkin_relapsed")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_trigger_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора триггеров срыва"""
    keyboard = [
        [
            InlineKeyboardButton(text="🥱 Скука / Безделье", callback_data="relapse_trigger_bored"),
            InlineKeyboardButton(text="😫 Стресс / Усталость", callback_data="relapse_trigger_stress")
        ],
        [
            InlineKeyboardButton(text="😔 Одиночество / Грусть", callback_data="relapse_trigger_lonely"),
            InlineKeyboardButton(text="🔞 Искушение в интернете", callback_data="relapse_trigger_web")
        ],
        [
            InlineKeyboardButton(text="📝 Другое", callback_data="relapse_trigger_other"),
            InlineKeyboardButton(text="❌ Отмена срыва", callback_data="relapse_trigger_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_day_report_keyboard(day: str) -> InlineKeyboardMarkup:
    """Отметка дня без ответа (day в формате ГГГГ-ММ-ДД)"""
    keyboard = [
        [
            InlineKeyboardButton(text="☀️ Чисто", callback_data=f"day:clean:{day}"),
            InlineKeyboardButton(text="😔 Срыв", callback_data=f"day:relapse:{day}")
        ],
        [InlineKeyboardButton(text="⏭ Позже", callback_data="day:later")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_day_trigger_keyboard(day: str, reasons: dict[str, str]) -> InlineKeyboardMarkup:
    """Причина срыва за прошедший день"""
    buttons = [
        InlineKeyboardButton(text=text, callback_data=f"day:why:{day}:{code}")
        for code, text in reasons.items()
    ]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"day:ask:{day}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
