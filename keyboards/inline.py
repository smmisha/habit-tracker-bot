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

def get_settings_keyboard(notify_achievements: bool) -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    keyboard = [
        [
            InlineKeyboardButton(text="⏰ Время отчета", callback_data="cfg_time"),
            InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="cfg_tz")
        ],
        [
            InlineKeyboardButton(
                text="🏆 Награды: ВКЛ ✅" if notify_achievements else "🏆 Награды: ВЫКЛ ❌",
                callback_data="cfg_toggle_achievements"
            )
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

def get_excuses_keyboard(forgot_left: int) -> InlineKeyboardMarkup:
    """Выбор причины опоздания на чек-ин"""
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"Забыл ({forgot_left} поп.) 🤷‍♂️" if forgot_left > 0 else "Забыл (лимит исчерпан) ❌", 
                callback_data="excuse_forgot"
            )
        ],
        [
            InlineKeyboardButton(text="Болел 🤒", callback_data="excuse_sick"),
            InlineKeyboardButton(text="Не было интернета 📵", callback_data="excuse_internet")
        ],
        [
            InlineKeyboardButton(text="Был занят / Работа 💼", callback_data="excuse_busy"),
            InlineKeyboardButton(text="Другое 📝", callback_data="excuse_other")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
