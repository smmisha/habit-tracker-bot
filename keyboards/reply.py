from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню бота"""
    keyboard = [
        [
            KeyboardButton(text="📊 Мой счетчик"),
            KeyboardButton(text="🆘 SOS / Паника")
        ],
        [
            KeyboardButton(text="⚠️ Срыв"),
            KeyboardButton(text="⚙️ Настройки")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True
    )
