from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Главное меню бота с встроенным WebApp дашбордом"""
    webapp_url = f"https://habit-tracker-bot-s7of.onrender.com/dashboard?user_id={user_id}"
    
    keyboard = [
        [
            KeyboardButton(text="📊 Мой счетчик", web_app=WebAppInfo(url=webapp_url)),
            KeyboardButton(text="🆘 SOS / Паника")
        ],
        [
            KeyboardButton(text="⚠️ Срыв"),
            KeyboardButton(text="⚙️ Настройки")
        ],
        [
            KeyboardButton(text="📝 Дневник")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True
    )
