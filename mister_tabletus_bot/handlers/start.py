import logging
import pytz
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import database

logger = logging.getLogger(__name__)

class SetTimezone(StatesGroup):
    waiting_for_timezone = State()

router = Router()


def get_main_menu_keyboard():
    """Возвращает клавиатуру главного меню"""
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [
            KeyboardButton(text="💊 Мои лекарства"),
            KeyboardButton(text="➕ Добавить лекарство")
        ],
        [
            KeyboardButton(text="🤖 Мистер Таблетус (Тамагочи)"),
            KeyboardButton(text="👥 Мои Бадди")
        ],
        [
            KeyboardButton(text="⚙️ Сменить часовой пояс")
        ]
    ], resize_keyboard=True)
    return keyboard

@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    # Добавляем пользователя в базу данных
    await database.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name
    )
    
    # Проверка диплинка для добавления Бадди
    if command.args and command.args.startswith("buddy_"):
        try:
            target_user_id = int(command.args.split("_")[1])
            if target_user_id == message.from_user.id:
                await message.answer("⚠️ Вы не можете стать Бадди для самого себя!")
                return
                
            target_user = await database.get_user(target_user_id)
            if not target_user:
                await message.answer("⚠️ Пользователь, отправивший ссылку, не найден в базе данных.")
                return
                
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🤝 Стать Бадди", callback_data=f"accept_buddy:{target_user_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_buddy:{target_user_id}")
                ]
            ])
            
            await message.answer(
                f"🤝 *Запрос на поддержку!*\n\n"
                f"Пользователь *{target_user['first_name']}* (@{target_user['username'] or 'нет_юзернейма'}) хочет добавить вас в качестве своего **Бадди**.\n\n"
                f"Вы будете получать дружеские напоминания в личные сообщения от Мистера Таблетуса, если он(а) случайно пропустит прием лекарств.\n\n"
                f"Вы согласны поддержать друга?",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.error(f"Ошибка разбора диплинка бадди: {e}")
    
    user = await database.get_user(message.from_user.id)
    
    welcome_text = (
        f"👋 Здравствуйте, {message.from_user.first_name}!\n\n"
        f"💊 Я — **Мистер Таблетус**, ваш персональный помощник и будильник для приема лекарств.\n\n"
        f"🦖 Моё здоровье напрямую связано с вашей дисциплиной! Если вы будете вовремя пить таблетки и отмечать приёмы, я буду счастлив и здоров. Если будете пропускать — я начну болеть.\n\n"
    )
    
    if user and user['timezone']:
        # Если часовой пояс уже настроен
        welcome_text += "Давайте следить за вашим здоровьем вместе!"
        await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    else:
        # Если часовой пояс не настроен
        welcome_text += (
            "⚠️ Для правильной отправки напоминаний мне нужно знать ваш часовой пояс.\n\n"
            "1. Перейдите по ссылке 👉 https://whatsmytimezone.com\n"
            "2. Скопируйте название часового пояса (например, `Europe/Paris` или `America/New_York`)\n"
            "3. **Отправьте скопированный текст мне в ответном сообщении:**"
        )
        await state.set_state(SetTimezone.waiting_for_timezone)
        await message.answer(welcome_text, parse_mode="Markdown")

# --- Обработчики подтверждения Бадди ---

@router.callback_query(F.data.startswith("accept_buddy:"))
async def process_accept_buddy(callback: CallbackQuery, bot: Bot):
    target_user_id = int(callback.data.split(":")[1])
    
    target_user = await database.get_user(target_user_id)
    if not target_user:
        await callback.answer("Пользователь не найден!")
        return
        
    # Добавляем связь
    await database.add_buddy(
        user_id=target_user_id,
        buddy_tg_id=callback.from_user.id,
        buddy_username=callback.from_user.username or "",
        buddy_name=callback.from_user.first_name
    )
    
    # Оповещаем пользователя, просившего опеку
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 *У вас появился Бадди!*\n\n"
                 f"*{callback.from_user.first_name}* (@{callback.from_user.username or 'нет_юзернейма'}) принял ваш запрос! "
                 f"Теперь он(а) ваш Бадди и сможет поддержать вас, если вы пропустите приём.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление о принятии бадди: {e}")
        
    await callback.answer("Успешно подтверждено!")
    await callback.message.edit_text(
        f"✅ Вы стали Бадди для *{target_user['first_name']}*!\n\n"
        f"Спасибо за поддержку друга! Мистер Таблетус сообщит вам, если понадобится помощь.",
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("reject_buddy:"))
async def process_reject_buddy(callback: CallbackQuery):
    await callback.answer("Запрос отклонен.")
    await callback.message.edit_text("❌ Запрос на поддержку отклонен.")


@router.message(StateFilter("*"), F.text == "⚙️ Сменить часовой пояс")
async def cmd_change_timezone(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SetTimezone.waiting_for_timezone)
    await message.answer(
        "🌐 *Смена часового пояса*\n\n"
        "1. Перейдите по ссылке 👉 https://whatsmytimezone.com\n"
        "2. Скопируйте название часового пояса (например, `Europe/Paris` или `America/New_York`)\n"
        "3. **Отправьте скопированный текст мне в ответ:**",
        parse_mode="Markdown"
    )

@router.message(SetTimezone.waiting_for_timezone)
async def process_custom_timezone(message: Message, state: FSMContext):
    tz_name = message.text.strip()
    try:
        pytz.timezone(tz_name)
        # Если часовой пояс валидный, сохраняем в БД
        await database.update_user_timezone(message.from_user.id, tz_name)
        await state.clear()
        await message.answer(
            f"✅ Ваш часовой пояс успешно изменен на **{tz_name}**!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
    except Exception:
        await message.answer(
            "❌ *Некорректный часовой пояс!*\n\n"
            "Пожалуйста, скопируйте его с сайта 👉 https://whatsmytimezone.com в точности (например: `Europe/Paris` или `America/New_York`, регистр букв важен) и отправьте еще раз:",
            parse_mode="Markdown"
        )

@router.message(StateFilter("*"), F.text == "🤖 Мистер Таблетус (Тамагочи)")
async def cmd_mascot_state(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
    user = await database.get_user(message.from_user.id)
    if not user:
        return
        
    health = user['mascot_health']
    level = user['mascot_level']
    xp = user['mascot_xp']
    
    # Визуальное состояние маскота
    if health >= 80:
        status_emoji = "🟢 Отличное"
        quote = "«Я полон энергии и готов следить за вашим расписанием! Мы отличная команда!»"
        face = "😎"
    elif health >= 40:
        status_emoji = "🟡 Нормальное"
        quote = "«Чувствую себя неплохо, но давайте не пропускать приёмы!»"
        face = "😐"
    else:
        status_emoji = "🔴 Плохое (болеет)"
        quote = "«Ох... кажется, я заболеваю. Пожалуйста, примите ваши таблетки вовремя, мне очень плохо!»"
        face = "🤢"
        
    # Рисуем полосу здоровья (progressbar)
    bar_length = 10
    filled = int(health / 100 * bar_length)
    progress_bar = "🟢" * filled + "🔴" * (bar_length - filled)
    
    await message.answer(
        f"🏥 **Состояние Мистера Таблетуса** {face}\n\n"
        f"❤️ Здоровье: {health}% \n`{progress_bar}`\n"
        f"⭐ Уровень: {level}\n"
        f"📈 Опыт (XP): {xp}/100\n"
        f"📋 Статус: {status_emoji}\n\n"
        f"💬 *Голос Таблетуса:* {quote}",
        parse_mode="Markdown"
    )
