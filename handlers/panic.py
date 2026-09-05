import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config.config import settings

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("panic"))
async def cmd_panic(message: Message, state: FSMContext):
    await state.clear()
    
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆘 Открыть SOS / Духовная помощь в Mini App",
                    url=f"{settings.mini_app_link}?startapp=sos"
                )
            ]
        ]
    )
    
    await message.answer(
        "🆘 <b>РЕЖИМ SOS / ДУХОВНАЯ ПОМОЩЬ</b>\n\n"
        "Не поддавайтесь импульсу! Каждая секунда борьбы делает вас сильнее.\n"
        "Перейдите в раздел SOS в Mini App — там собрана духовная защита, целевые публикации и шаги победы над искушением.",
        reply_markup=inline_kb
    )
