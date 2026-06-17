import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
import database
from utils.locales import _T

logger = logging.getLogger(__name__)
router = Router()

@router.message(StateFilter("*"), lambda m: m.text in [_T("menu_buddies", "ru"), _T("menu_buddies", "en"), _T("menu_buddies", "uk")] if m.text else False)
async def list_buddies(message: Message, bot: Bot, state: FSMContext = None):
    if state:
        await state.clear()

    user_id = message.from_user.id
    buddies = await database.get_user_buddies(user_id)
    user = await database.get_user(user_id)
    lang = user.get("language") if user else "ru"
    buddies_enabled = user['buddies_enabled'] if user else 1
    
    status_str = _T("buddy_enabled", lang) if buddies_enabled == 1 else _T("buddy_disabled", lang)
    toggle_text = _T("btn_buddy_toggle_off", lang) if buddies_enabled == 1 else _T("btn_buddy_toggle_on", lang)
    
    bot_info = await bot.get_me()
    # Ссылка для приглашения Бадди
    invite_link = f"https://t.me/{bot_info.username}?start=buddy_{user_id}"
    
    text = _T("buddy_title", lang, status=status_str)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_buddy_status")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    
    if buddies:
        await message.answer(_T("buddy_list_header", lang))
        for idx, b in enumerate(buddies, 1):
            name_str = f"@{b['buddy_username']}" if b['buddy_username'] else b['buddy_name']
            
            # Добавим кнопку удаления Бадди
            del_lbl = _T("btn_del_buddy", lang)
            keyboard_del = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=del_lbl, callback_data=f"del_buddy:{b['buddy_tg_id']}")]
            ])
            await message.answer(f"👤 *{b['buddy_name']}* ({name_str})", reply_markup=keyboard_del, parse_mode="Markdown")
            
    # Отправляем сообщение с инструкцией по приглашению
    invite_text = _T("buddy_invite_instruction", lang, link=invite_link)
    await message.answer(invite_text, parse_mode="Markdown")

@router.callback_query(F.data == "toggle_buddy_status")
async def process_toggle_buddy_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_status = await database.toggle_buddies_enabled(user_id)
    
    user = await database.get_user(user_id)
    lang = user.get("language") if user else "ru"
    
    status_str = _T("buddy_enabled", lang) if new_status == 1 else _T("buddy_disabled", lang)
    toggle_text = _T("btn_buddy_toggle_off", lang) if new_status == 1 else _T("btn_buddy_toggle_on", lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_buddy_status")]
    ])
    
    text = _T("buddy_title", lang, status=status_str)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer(_T("buddy_updated", lang))

@router.callback_query(F.data.startswith("del_buddy:"))
async def process_delete_buddy(callback: CallbackQuery):
    buddy_tg_id = int(callback.data.split(":")[1])
    await database.delete_buddy(callback.from_user.id, buddy_tg_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    await callback.answer(_T("buddy_deleted_toast", lang))
    await callback.message.delete()
    await callback.message.answer(_T("buddy_deleted_msg", lang))
