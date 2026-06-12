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
                timezone="Europe/Kyiv",  # По умолчанию для Украины
                partner_username="693656777"  # По умолчанию напарник Михаил
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
            
    # Установка постоянной кнопки меню чата на WebApp (дефолтной из BotFather)
    try:
        await message.bot.set_chat_menu_button(
            chat_id=user_id,
            menu_button=MenuButtonDefault()
        )
    except Exception as e:
        logger.error(f"Не удалось установить кнопку меню: {e}")
        
    # Убираем старое reply-меню
    await message.answer("🔄 Загружаю интерфейс...", reply_markup=ReplyKeyboardRemove())
    
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
    await message.answer(welcome_text, reply_markup=inline_kb)

@router.message(Command("settings"))
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

# --- НАСТРОЙКА НАПАРНИКА И СОГЛАШЕНИЕ ---
@router.callback_query(F.data == "cfg_partner")
async def process_cfg_partner(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    
    from datetime import datetime, timedelta
    from database.models import RelapseLog
    
    async with db_helper.session_factory() as session:
        # Проверяем последний срыв пользователя в логах
        result = await session.execute(
            select(RelapseLog)
            .where(RelapseLog.user_id == user_id)
            .order_by(RelapseLog.timestamp.desc())
            .limit(1)
        )
        latest_relapse = result.scalar_one_or_none()
        
        if latest_relapse:
            time_since_relapse = datetime.now() - latest_relapse.timestamp
            if time_since_relapse < timedelta(hours=24):
                time_left = timedelta(hours=24) - time_since_relapse
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes = remainder // 60
                
                block_text = (
                    "❌ <b>СМЕНА НАПАРНИКА ЗАБЛОКИРОВАНА</b>\n\n"
                    "После срыва должно пройти не менее <b>24 часов</b>, прежде чем вы сможете сменить напарника-контролёра.\n"
                    "Это ограничение создано для борьбы с самообманом и избеганием контроля в критические моменты.\n\n"
                    f"⏳ Пожалуйста, подождите ещё: <b>{hours} ч. {minutes} мин.</b>"
                )
                await callback.message.answer(block_text)
                return
                
    covenant_text = (
        "📜 <b>СОГЛАШЕНИЕ О ДУХОВНОЙ ЧИСТОТЕ ПЕРЕД ИЕГОВОЙ</b>\n"
        "<i>(Подтверждается при каждой смене напарника)</i>\n\n"
        "«Воля Бога в том, чтобы вы были святы и воздерживались от блуда» (1 Фессалоникийцам 4:3)\n\n"
        "Для смены напарника вам необходимо открыть, прочитать и подписать Соглашение:\n\n"
        "1️⃣ Нажмите кнопку ниже для открытия текста Соглашения.\n"
        "2️⃣ Пролистайте документ до самого конца, чтобы активировать подтверждение.\n"
        "3️⃣ Подтвердите согласие внутри страницы, и бот предложит вам ввести новый ID.\n\n"
        "⚠️ <i>Без подписания Соглашения замена напарника невозможна.</i>"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Читать и подписать Соглашение",
                    web_app=WebAppInfo(url="https://habit-tracker-bot-s7of.onrender.com/webapp/purity_covenant_jw_v2.html")
                )
            ],
            [
                InlineKeyboardButton(text="🔴 Отмена", callback_data="covenant_cancel")
            ]
        ]
    )
    
    sent_msg = await callback.message.answer(covenant_text, reply_markup=keyboard)
    await state.update_data(covenant_msg_id=sent_msg.message_id)


@router.callback_query(F.data == "covenant_cancel")
async def process_covenant_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Действие отменено.")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("❌ Смена напарника отменена. Текущий напарник сохранен.")


@router.message(Form.waiting_for_partner)
async def process_partner_input(message: Message, state: FSMContext):
    partner_username = message.text.strip().replace("@", "")
    
    if len(partner_username) < 3 or not re.match(r"^[a-zA-Z0-9_-]+$", partner_username):
        await message.answer("❌ Некорректный формат. Пожалуйста, введите юзернейм или цифровой ID напарника.")
        return
        
    user_id = message.from_user.id
    user_username = message.from_user.username
    
    # Запрет указывать самого себя в качестве напарника (защита от обхода)
    if partner_username == str(user_id) or (user_username and partner_username.lower() == user_username.lower()):
        await message.answer("❌ Вы не можете указать самого себя в качестве напарника!")
        return
        
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            old_partner = user.partner_username
            user.partner_username = partner_username
            await session.commit()
            
            # Если был срыв или требовалась помощь в последние 24 часа, уведомляем старого напарника
            if old_partner and old_partner != partner_username and user.business_connection_id:
                from datetime import datetime, timedelta
                from database.models import RelapseLog
                from services.userbot_client import userbot
                
                limit_time = datetime.now() - timedelta(hours=24)
                relapse_check = await session.execute(
                    select(RelapseLog)
                    .where(RelapseLog.user_id == user_id)
                    .where(RelapseLog.timestamp >= limit_time)
                )
                has_recent_relapse = relapse_check.scalars().first() is not None
                
                if has_recent_relapse:
                    alert_text = (
                        f"🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы сообщить: "
                        f"я сменил напарника-контролера в трекере чистоты. "
                        f"Спасибо за твою поддержку в моей борьбе."
                    )
                    try:
                        await userbot.send_message_to_partner(user.business_connection_id, old_partner, alert_text)
                        logger.info(f"Уведомление о смене напарника успешно отправлено старому напарнику {old_partner}")
                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление о смене напарника старому напарнику {old_partner}: {e}")
            
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

