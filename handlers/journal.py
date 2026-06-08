from datetime import date, datetime
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, desc
from database.db_helper import db_helper
from database.models import User, JournalEntry

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("journal"))
async def cmd_journal_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    async with db_helper.session_factory() as session:
        result = await session.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .order_by(desc(JournalEntry.entry_date))
            .limit(1)
        )
        last_entry = result.scalar_one_or_none()
        
    if last_entry:
        date_str = last_entry.entry_date.strftime("%d.%m.%Y")
        preview = last_entry.content[:100] + "..." if len(last_entry.content) > 100 else last_entry.content
        text = f"📖 <b>Ваша последняя запись от {date_str}:</b>\n\n«{preview}»"
    else:
        text = "📖 У вас пока нет записей в дневнике. Запишите свой первый день!"
        
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Открыть дневник в Mini App",
                    web_app=WebAppInfo(url=f"https://habit-tracker-bot-s7of.onrender.com/webapp/index.html?user_id={user_id}&tab=journal")
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=inline_kb)
