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


TEMPTATION_ITEMS = [
    ("masturbation", "✊ Мастурбация"),
    ("porn", "🔞 Порнография"),
    ("sexting", "💬 Секстинг / Чат"),
    ("premarital_sex", "💔 Секс с девушкой"),
    ("general", "🧠 Навязчивые мысли"),
]

def get_temptation_multiselect_keyboard(selected_types: list = None) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура множественного выбора искушений с чекбоксами"""
    if selected_types is None:
        selected_types = []
        
    keyboard = []
    for key, label in TEMPTATION_ITEMS:
        box = "✅" if key in selected_types else "⬜"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{box} {label}",
                callback_data=f"toggle_temptation:{key}"
            )
        ])
        
    count = len(selected_types)
    submit_text = f"🔍 Получить духовное решение ({count})" if count > 0 else "🔍 Получить духовное решение"
    keyboard.append([
        InlineKeyboardButton(text=submit_text, callback_data="submit_temptations")
    ])
    keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_spiritual")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

