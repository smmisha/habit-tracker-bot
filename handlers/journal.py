from datetime import date, datetime
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, and_, desc
from database.db_helper import db_helper
from database.models import User, JournalEntry
from utils.states import Form

logger = logging.getLogger(__name__)
router = Router()

def get_journal_keyboard():
    """Клавиатура управления дневником"""
    keyboard = [
        [KeyboardButton(text="✍️ Записать заметку"), KeyboardButton(text="📖 Последние записи")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@router.message(Command("journal"))
@router.message(F.text == "📝 Дневник")
async def cmd_journal_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📝 <b>Личный дневник самопомощи</b>\n\n"
        "Здесь вы можете записывать свои мысли, эмоции, уровень тяги и события дня.\n"
        "Каждое воскресенье ИИ Gemini будет собирать ваши записи за неделю, находить эмоциональные триггеры и давать полезный психологический анализ.",
        reply_markup=get_journal_keyboard()
    )

@router.message(F.text == "✍️ Записать заметку")
async def process_write_note(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>Напишите заметку за сегодня:</b>\n\n"
        "Опишите ваше самочувствие, уровень стресса, тяги, что помогло вам оставаться чистым сегодня или с какими трудностями вы столкнулись.\n\n"
        "<i>Отправьте текст в ответном сообщении:</i>"
    )
    await state.set_state(Form.waiting_for_journal_entry)

@router.message(Form.waiting_for_journal_entry)
async def save_journal_entry(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if len(text) < 5:
        await message.answer("❌ Заметка слишком короткая. Напишите хотя бы пару слов о сегодняшнем состоянии:")
        return

    today_date = date.today()
    
    async with db_helper.session_factory() as session:
        # Проверяем, есть ли уже запись за сегодня
        result = await session.execute(
            select(JournalEntry).where(
                and_(JournalEntry.user_id == user_id, JournalEntry.entry_date == today_date)
            )
        )
        entry = result.scalar_one_or_none()
        
        if entry:
            entry.content = text
            entry.created_at = datetime.now()
            action_text = "обновлена"
        else:
            entry = JournalEntry(
                user_id=user_id,
                entry_date=today_date,
                content=text
            )
            session.add(entry)
            action_text = "сохранена"
            
        await session.commit()

    await state.clear()
    
    # Импортируем клавиатуру главного меню
    from keyboards.reply import get_main_keyboard
    
    await message.answer(
        f"✅ <b>Заметка успешно {action_text}!</b>\n\n"
        "Вы сделали важный шаг для анализа своей тяги. Данные будут учтены при составлении отчета в воскресенье.",
        reply_markup=get_main_keyboard(user_id)
    )

@router.message(F.text == "📖 Последние записи")
async def process_view_notes(message: Message):
    user_id = message.from_user.id
    
    async with db_helper.session_factory() as session:
        result = await session.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .order_by(desc(JournalEntry.entry_date))
            .limit(5)
        )
        entries = result.scalars().all()
        
    if not entries:
        await message.answer("📖 У вас пока нет записей в дневнике. Самое время написать первую!")
        return
        
    notes_text = ["📖 <b>ВАШИ ЗАПИСИ (ПОСЛЕДНИЕ 5):</b>\n"]
    for e in entries:
        date_str = e.entry_date.strftime("%d.%m.%Y")
        notes_text.append(f"📅 <b>{date_str}</b>\n{e.content}\n──────────────────")
        
    await message.answer("\n".join(notes_text))
