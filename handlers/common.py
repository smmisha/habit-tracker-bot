import html
import re
import pytz
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, MenuButtonWebApp, MenuButtonDefault
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from config.config import settings
from database.db_helper import db_helper
from database.models import User
from keyboards.inline import get_settings_keyboard
from handlers.checkin import send_unmarked_days_prompt
from services.day_report import add_missed_days_for_pause
from utils.states import Form

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("cancel"), StateFilter("*"))
@router.message(F.text.casefold() == "отмена", StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть Mini App",
                    url=settings.mini_app_link
                )
            ]
        ]
    )
    
    if current_state is None:
        await message.answer("Нечего отменять. Вы находитесь в главном меню.", reply_markup=inline_kb)
        return
        
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=inline_kb)

PAUSE_RETURN_TEXT = (
    "Напоминания снова включены. Отметь пропущенные дни ниже.\n"
    "Если срыв был раньше этих дней, запиши его в приложении."
)

def get_mini_app_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть Mini App", url=settings.mini_app_link)]]
    )

async def resume_after_pause(user_id: int):
    """Включает напоминания после авто-паузы и добавляет дни паузы в список неотмеченных"""
    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return
        user.is_active = True
        user.consecutive_missed_checkins = 0
        user.last_checkin_message_id = None
        await session.commit()
    await add_missed_days_for_pause(user_id)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # Незавершенный ввод (например, причины срыва) сбрасывается любой командой
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    safe_name = html.escape(first_name)
    was_paused = False
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            db_user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                timezone="Europe/Kyiv",  # По умолчанию для Украины
                partner_username="693656777"  # По умолчанию напарник Михаил
            )
            session.add(db_user)
            await session.commit()
            welcome_text = (
                f"Привет, <b>{safe_name}</b>! 👋\n\n"
                "Этот бот разработан, чтобы помочь тебе в пути отказа от вредных привычек (PMO). "
                "Здесь ты сможешь вести автоматический счетчик чистых дней и проходить ежедневный чек-ин.\n\n"
                "⚙️ Для корректной работы проверь <b>Настройки</b> (/settings)."
            )
        else:
            db_user.username = username
            db_user.first_name = first_name
            if not db_user.is_active:
                was_paused = True
            else:
                db_user.consecutive_missed_checkins = 0
            await session.commit()
            welcome_text = (
                f"Рад видеть тебя снова, <b>{safe_name}</b>! Счетчик продолжает идти.\n\n"
                "💪 Оставайся сильным и помни, ради чего ты начал этот путь!"
            )
            
    # Установка постоянной кнопки меню чата на WebApp (дефолтной из BotFather)
    try:
        await message.bot.set_chat_menu_button(
            chat_id=user_id,
            menu_button=MenuButtonDefault()
        )
    except Exception as e:
        logger.error(f"Не удалось установить кнопку меню: {e}")

    if was_paused:
        await resume_after_pause(user_id)
        await message.answer(
            f"👋 <b>С возвращением, {safe_name}!</b>\n\n{PAUSE_RETURN_TEXT}",
            reply_markup=get_mini_app_keyboard()
        )
        await send_unmarked_days_prompt(message, user_id)
        return

    # Убираем старое reply-меню
    await message.answer("🔄 Загружаю интерфейс...", reply_markup=ReplyKeyboardRemove())
    
    await message.answer(welcome_text, reply_markup=get_mini_app_keyboard())
    await send_unmarked_days_prompt(message, user_id)


@router.callback_query(F.data.in_({"resume_bot_from_pause", "resume_clean", "resume_relapse"}))
async def process_resume_from_pause(callback: CallbackQuery):
    # resume_clean и resume_relapse остались на кнопках старых сообщений
    await callback.answer("Бот возобновлен!")
    await resume_after_pause(callback.from_user.id)
    await callback.message.edit_text(
        f"👋 <b>С возвращением!</b>\n\n{PAUSE_RETURN_TEXT}",
        reply_markup=get_mini_app_keyboard()
    )
    await send_unmarked_days_prompt(callback.message, callback.from_user.id)

@router.message(Command("covenant"))
async def cmd_covenant(message: Message, state: FSMContext):
    await state.clear()
    from aiogram.types import WebAppInfo
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📜 Читать соглашение",
                    web_app=WebAppInfo(url=f"{settings.webapp_base_url.rstrip('/')}/webapp/purity_covenant_jw_v2.html?mode=manifest&v=20261125-5")
                )
            ]
        ]
    )
    await message.answer(
        "📜 <b>Соглашение о духовной чистоте перед Иеговой</b>\n\n"
        "Это ваш ориентир совести — читать его желательно, но не обязательно, без таймеров и ограничений:\n"
        "• <i>Случайно попавшееся видео/фото, от которого ты сразу отвернулся (перелистнул/скрыл) — не срыв.</i>\n"
        "• <i>Засматривание на случайное или умышленный поиск — срыв, стрик обнуляется.</i>\n"
        "• <i>Мастурбация (даже без порнографии) и секстинг — тоже срыв.</i>\n"
        "• <i>При любом срыве — честное личное обращение к старейшине в течение недели на своей совести, без авто-отчётов.</i>",
        reply_markup=inline_kb
    )

@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext):
    await state.clear()
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
            "──────────────────────────\n"
            "<i>Выберите кнопку ниже, чтобы изменить нужный параметр.</i>"
        )
    await message.answer(settings_text, reply_markup=get_settings_keyboard())

# --- НАСТРОЙКА НАПАРНИКА УДАЛЕНА (ФИКСИРОВАННЫЙ НАПАРНИК) ---

# --- НАСТРОЙКА ЧАСОВОГО ПОЯСА ---
@router.callback_query(F.data == "cfg_tz")
async def process_cfg_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🌍 Укажите ваш часовой пояс (например, `Europe/Kyiv`, `Europe/Chisinau`, `Europe/Prague`, `Europe/Warsaw`):\n"
        "Это нужно для точного времени ежедневных напоминаний."
    )
    await state.set_state(Form.waiting_for_timezone)

@router.message(Form.waiting_for_timezone, F.text, ~F.text.startswith("/"))
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

@router.message(Form.waiting_for_checkin_time, F.text, ~F.text.startswith("/"))
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

@router.message(StateFilter(Form.waiting_for_timezone, Form.waiting_for_checkin_time), ~F.text)
async def process_settings_non_text(message: Message):
    await message.answer("✍️ Пожалуйста, ответьте текстом или отправьте /cancel.")
