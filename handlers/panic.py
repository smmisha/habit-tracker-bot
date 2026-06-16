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
                    text="🆘 Открыть SOS / Срыв в Mini App",
                    url=f"{settings.mini_app_link}?startapp=sos"
                )
            ]
        ]
    )
    
    await message.answer(
        "🆘 <b>РЕЖИМ SOS / ПАНИКА</b>\n\n"
        "Не поддавайтесь импульсу! Каждая секунда борьбы делает вас сильнее. "
        "Перейдите в SOS-раздел Mini App для прохождения инструкций помощи и фиксации состояния.",
        reply_markup=inline_kb
    )
