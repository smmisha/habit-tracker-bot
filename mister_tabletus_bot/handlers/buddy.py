import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
import database

logger = logging.getLogger(__name__)
router = Router()

@router.message(StateFilter("*"), F.text == "👥 Мои Бадди")
async def list_buddies(message: Message, bot: Bot, state: FSMContext = None):
    if state:
        await state.clear()

    user_id = message.from_user.id
    buddies = await database.get_user_buddies(user_id)
    user = await database.get_user(user_id)
    buddies_enabled = user['buddies_enabled'] if user else 1
    
    status_str = "🟢 Включена (Мистер Таблетус напишет Бадди при пропуске)" if buddies_enabled == 1 else "🔴 Выключена (бот не будет писать вашим Бадди)"
    toggle_text = "📴 Отключить поддержку Бадди" if buddies_enabled == 1 else "📳 Включить поддержку Бадди"
    
    bot_info = await bot.get_me()
    # Ссылка для приглашения Бадди
    invite_link = f"https://t.me/{bot_info.username}?start=buddy_{user_id}"
    
    text = (
        f"👥 *Ваши Бадди (Поддержка)*\n\n"
        f"Бадди — это ваши друзья или близкие, которые получат мягкое напоминание от Мистера Таблетуса, если вы случайно пропустите прием лекарств и не подтвердите его в течение 45 минут. Это помогает не забывать о важном по-дружески! 🤝\n\n"
        f"📢 *Статус поддержки:* {status_str}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_buddy_status")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    if buddies:
        await message.answer("✅ Список ваших Бадди:")
        for idx, b in enumerate(buddies, 1):
            name_str = f"@{b['buddy_username']}" if b['buddy_username'] else b['buddy_name']
            
            # Добавим кнопку удаления Бадди
            keyboard_del = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑️ Удалить Бадди", callback_data=f"del_buddy:{b['buddy_tg_id']}")]
            ])
            await message.answer(f"👤 *{b['buddy_name']}* ({name_str})", reply_markup=keyboard_del, parse_mode="Markdown")
            
    # Отправляем сообщение с инструкцией по приглашению
    invite_text = (
        f"➕ *Как добавить нового Бадди:*\n\n"
        f"Отправьте вашему другу или близкому человеку эту уникальную ссылку:\n"
        f"`{invite_link}`\n\n"
        f"Когда он перейдет по ней и нажмет кнопку «Старт», он автоматически станет вашим Бадди!"
    )
    
    await message.answer(invite_text, parse_mode="Markdown")

@router.callback_query(F.data == "toggle_buddy_status")
async def process_toggle_buddy_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_status = await database.toggle_buddies_enabled(user_id)
    
    status_str = "🟢 Включена (Мистер Таблетус напишет Бадди при пропуске)" if new_status == 1 else "🔴 Выключена (бот не будет писать вашим Бадди)"
    toggle_text = "📴 Отключить поддержку Бадди" if new_status == 1 else "📳 Включить поддержку Бадди"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_buddy_status")]
    ])
    
    text = (
        f"👥 *Ваши Бадди (Поддержка)*\n\n"
        f"Бадди — это ваши друзья или близкие, которые получат мягкое напоминание от Мистера Таблетуса, если вы случайно пропустите прием лекарств и не подтвердите его в течение 45 минут. Это помогает не забывать о важном по-дружески! 🤝\n\n"
        f"📢 *Статус поддержки:* {status_str}"
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer("Настройки обновлены!")

@router.callback_query(F.data.startswith("del_buddy:"))
async def process_delete_buddy(callback: CallbackQuery):
    buddy_tg_id = int(callback.data.split(":")[1])
    await database.delete_buddy(callback.from_user.id, buddy_tg_id)
    
    await callback.answer("Бадди удален!")
    await callback.message.delete()
    await callback.message.answer("🗑️ Связь с Бадди разорвана.")
