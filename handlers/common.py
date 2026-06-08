import re
import pytz
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.db_helper import db_helper
from database.models import User
from keyboards.reply import get_main_keyboard
from keyboards.inline import get_settings_keyboard
from utils.states import Form

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("cancel"), StateFilter("*"))
@router.message(F.text.casefold() == "отмена", StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять. Вы находитесь в главном меню.", reply_markup=get_main_keyboard(message.from_user.id))
        return
        
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard(message.from_user.id))

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            db_user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                timezone="Europe/Kyiv"  # По умолчанию для Украины
            )
            session.add(db_user)
            await session.commit()
            welcome_text = (
                f"Привет, <b>{first_name}</b>! 👋\n\n"
                "Этот бот разработан, чтобы помочь тебе в пути отказа от вредных привычек (PMO). "
                "Здесь ты сможешь вести автоматический счетчик чистых дней и проходить ежедневный чек-ин.\n\n"
                "🚨 <b>ВАЖНО:</b> Бот автоматически отправит предупреждение твоему напарнику от твоего имени "
                "через бизнес-аккаунт Telegram, если ты пропустишь обязательное время отчета или зафиксируешь срыв.\n\n"
                "⚙️ Для корректной работы перейди в <b>Настройки</b> и укажи ID или юзернейм напарника!"
            )
        else:
            db_user.username = username
            db_user.first_name = first_name
            await session.commit()
            welcome_text = (
                f"Рад видеть тебя снова, <b>{first_name}</b>! Счетчик продолжает идти.\n\n"
                "💪 Оставайся сильным и помни, ради чего ты начал этот путь!"
            )
            
    await message.answer(welcome_text, reply_markup=get_main_keyboard(user_id))

@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message):
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return
            
        partner_display = "НЕ УКАЗАН ⚠️"
        if user.partner_username:
            partner_display = user.partner_username if user.partner_username.isdigit() else f"@{user.partner_username}"
            
        settings_text = (
            "⚙️ <b>НАСТРОЙКИ ПРОФИЛЯ</b>\n"
            "──────────────────────────\n"
            f"👥 <b>Напарник:</b> <code>{partner_display}</code>\n"
            f"⏰ <b>Время отчета:</b> <code>{user.checkin_time}</code> (локальное)\n"
            f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
            f"🔄 <b>Лимит «Забыл»:</b> использовано <b>{user.forgot_count}</b> из 3\n"
            f"🏆 <b>Отчет о наградах:</b> <b>{'ВКЛ ✅' if user.notify_partner_achievements else 'ВЫКЛ ❌'}</b>\n"
            "──────────────────────────\n"
            "<i>Выберите кнопку ниже, чтобы изменить нужный параметр.</i>"
        )
    await message.answer(settings_text, reply_markup=get_settings_keyboard(user.notify_partner_achievements))

@router.callback_query(F.data == "cfg_toggle_achievements")
async def process_cfg_toggle_achievements(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден.")
            return
            
        user.notify_partner_achievements = not user.notify_partner_achievements
        new_val = user.notify_partner_achievements
        await session.commit()
        
        partner_display = "НЕ УКАЗАН ⚠️"
        if user.partner_username:
            partner_display = user.partner_username if user.partner_username.isdigit() else f"@{user.partner_username}"
            
        settings_text = (
            "⚙️ <b>НАСТРОЙКИ ПРОФИЛЯ</b>\n"
            "──────────────────────────\n"
            f"👥 <b>Напарник:</b> <code>{partner_display}</code>\n"
            f"⏰ <b>Время отчета:</b> <code>{user.checkin_time}</code> (локальное)\n"
            f"🌍 <b>Часовой пояс:</b> <code>{user.timezone}</code>\n"
            f"🔄 <b>Лимит «Забыл»:</b> использовано <b>{user.forgot_count}</b> из 3\n"
            f"🏆 <b>Отчет о наградах:</b> <b>{'ВКЛ ✅' if new_val else 'ВЫКЛ ❌'}</b>\n"
            "──────────────────────────\n"
            "<i>Выберите кнопку ниже, чтобы изменить нужный параметр.</i>"
        )
        
    await callback.message.edit_text(
        settings_text,
        reply_markup=get_settings_keyboard(new_val)
    )
    await callback.answer("Настройка наград обновлена!")

# --- НАСТРОЙКА НАПАРНИКА ---
@router.callback_query(F.data == "cfg_partner")
async def process_cfg_partner(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "👥 Введите **цифровой ID** вашего напарника (например, `123456789`) или его Telegram-юзернейм (например, `partner_username`):\n\n"
        "💡 **РЕКОМЕНДУЕТСЯ использовать цифровой ID**, так как Telegram надежно отправляет сообщения именно по нему. "
        "Узнать ID напарника можно, переслав любое его сообщение боту [@userinfobot](https://t.me/userinfobot)."
    )
    await state.set_state(Form.waiting_for_partner)

@router.message(Form.waiting_for_partner)
async def process_partner_input(message: Message, state: FSMContext):
    partner_username = message.text.strip().replace("@", "")
    
    if len(partner_username) < 3 or not re.match(r"^[a-zA-Z0-9_-]+$", partner_username):
        await message.answer("❌ Некорректный формат. Пожалуйста, введите юзернейм или цифровой ID напарника.")
        return
        
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.partner_username = partner_username
            await session.commit()
            
    await state.clear()
    display_partner = partner_username if partner_username.isdigit() else f"@{partner_username}"
    await message.answer(f"✅ Напарник успешно сохранен: {display_partner}")

# --- НАСТРОЙКА ЧАСОВОГО ПОЯСА ---
@router.callback_query(F.data == "cfg_tz")
async def process_cfg_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🌍 Укажите ваш часовой пояс (например, `Europe/Kyiv`, `Europe/Chisinau`, `Europe/Prague`, `Europe/Warsaw`):\n"
        "Это нужно для точного времени ежедневных напоминаний."
    )
    await state.set_state(Form.waiting_for_timezone)

@router.message(Form.waiting_for_timezone)
async def process_tz_input(message: Message, state: FSMContext):
    tz_input = message.text.strip()
    
    if tz_input not in pytz.all_timezones:
        await message.answer(
            "❌ Неверный часовой пояс. Пожалуйста, укажите точное имя из базы данных часовых поясов "
            "(например, `Europe/Kyiv`, `Europe/Warsaw`)."
        )
        return
        
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.timezone = tz_input
            await session.commit()
            
    await state.clear()
    await message.answer(f"✅ Часовой пояс изменен на: {tz_input}")

# --- НАСТРОЙКА ВРЕМЕНИ ЧЕК-ИНА ---
@router.callback_query(F.data == "cfg_time")
async def process_cfg_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "⏰ Введите время для ежедневной отметки в формате ЧЧ:ММ (например, `21:00` или `22:30`):"
    )
    await state.set_state(Form.waiting_for_checkin_time)

@router.message(Form.waiting_for_checkin_time)
async def process_time_input(message: Message, state: FSMContext):
    time_input = message.text.strip()
    
    if not re.match(r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$", time_input):
        await message.answer("❌ Некорректный формат времени. Введите время в формате ЧЧ:ММ (от 00:00 до 23:59).")
        return
        
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.checkin_time = time_input
            await session.commit()
            
    await state.clear()
    await message.answer(f"✅ Время чек-ина установлено на: {time_input}")

