import os
import logging
import pytz
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import database
from utils.locales import _T

logger = logging.getLogger(__name__)

class SetTimezone(StatesGroup):
    waiting_for_timezone = State()

router = Router()


# --- ОБЩИЙ ОБРАБОТЧИК ОТМЕНЫ ---
@router.message(
    StateFilter("*"),
    lambda m: m.text and (m.text.strip().lower() in [
        "отмена", "cancel", "скасувати",
        "❌ отмена", "❌ cancel", "❌ скасувати",
        "/cancel"
    ])
)
async def process_cancel_wizard(message: Message, state: FSMContext):
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    # Delete saved wizard messages
    state_data = await state.get_data()
    msg_ids = state_data.get("wizard_msg_ids", [])
    for msg_id in msg_ids:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
        except Exception:
            pass
            
    # Delete user's cancellation message
    try:
        await message.delete()
    except Exception:
        pass
        
    # Очищаем локальные временные файлы
    for key in ["parsed_data", "photo_data"]:
        data = state_data.get(key, {})
        if data and data.get("image_path") and os.path.exists(data["image_path"]):
            try:
                os.remove(data["image_path"])
            except Exception:
                pass
                
    await state.clear()
    await message.answer(
        _T("cancel_msg", lang),
        reply_markup=get_main_menu_keyboard(lang),
        parse_mode="Markdown"
    )


def get_main_menu_keyboard(lang: str = "ru"):
    """Возвращает клавиатуру главного меню с локализацией"""
    from utils.locales import _T
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [
            KeyboardButton(text=_T("menu_my_meds", lang)),
            KeyboardButton(text=_T("menu_add_med", lang))
        ],
        [
            KeyboardButton(text=_T("menu_tamagotchi", lang)),
            KeyboardButton(text=_T("menu_buddies", lang))
        ],
        [
            KeyboardButton(text=_T("menu_change_tz", lang))
        ]
    ], resize_keyboard=True)
    return keyboard

@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    await message.answer(
        _T("help_text", lang),
        parse_mode="Markdown"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    # Ограничиваем доступ только владельцу бота
    ADMIN_IDS = {1496819884}
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        # 1. Получаем общее количество пользователей
        res_users = await database.fetch_one("SELECT COUNT(*) as cnt FROM users", "SELECT COUNT(*) as cnt FROM users")
        total_users = res_users["cnt"] if res_users else 0

        # 2. Получаем детальную статистику по каждому пользователю
        query_sql = """
        SELECT 
            u.id, 
            u.username, 
            u.first_name,
            COALESCE(m.med_count, 0) as med_count,
            COALESCE(h.take_count, 0) as take_count,
            h.last_take
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) as med_count 
            FROM medications 
            WHERE is_active = 1 
            GROUP BY user_id
        ) m ON u.id = m.user_id
        LEFT JOIN (
            SELECT 
                user_id, 
                COUNT(*) as take_count, 
                MAX(action_time) as last_take 
            FROM history 
            WHERE status IN ('taken', 'taken_late')
            GROUP BY user_id
        ) h ON u.id = h.user_id
        ORDER BY take_count DESC, med_count DESC
        """
        
        user_stats = await database.fetch_all(query_sql, query_sql)
        
        active_lines = []
        idle_count = 0
        
        for row in user_stats:
            meds = row["med_count"]
            takes = row["take_count"]
            last_take = row["last_take"]
            
            name = f"@{row['username']}" if row['username'] else row['first_name']
            if not name:
                name = f"ID: {row['id']}"
                
            if meds > 0 or takes > 0:
                last_str = "нет"
                if last_take:
                    try:
                        t_str = last_take.split(".")[0]
                        if "T" in t_str:
                            dt_part, tm_part = t_str.split("T")
                            yy, mm, dd = dt_part.split("-")
                            hh_mm = ":".join(tm_part.split(":")[:2])
                            last_str = f"{hh_mm} ({dd}.{mm}.{yy})"
                        else:
                            last_str = last_take[:16]
                    except Exception:
                        last_str = last_take[:16]
                active_lines.append(f"👤 *{name}*: лекарств: {meds}, приёмов: {takes}, последний: `{last_str}`")
            else:
                idle_count += 1
                
        active_users_count = len(active_lines)
        
        stats_text = (
            f"📊 *Детальная статистика активности:*\n\n"
            f"👥 Всего зарегистрировано: *{total_users}*\n"
            f"⚡️ Активных пользователей: *{active_users_count}*\n"
            f"💤 Неактивных (только запустили): *{idle_count}*\n\n"
            f"🔥 *Список активных пользователей:*\n"
        )
        if active_lines:
            stats_text += "\n".join(active_lines)
        else:
            stats_text += "_Активных пользователей пока нет._"
            
        await message.answer(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await message.answer(f"❌ Ошибка при получении статистики: {e}")

@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    # Добавляем пользователя в базу данных
    await database.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name
    )
    
    # Показываем клавиатуру выбора языка
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Русский", callback_data="set_lang:ru"),
            InlineKeyboardButton(text="💬 English", callback_data="set_lang:en"),
            InlineKeyboardButton(text="💬 Українська", callback_data="set_lang:uk")
        ]
    ])
    
    # Сохраняем args (buddy_ диплинк), если они есть, чтобы передать после выбора языка
    if command.args:
        await state.update_data(start_args=command.args)
        
    await message.answer(
        "🌐 *Please select your language / Пожалуйста, выберите язык / Будь ласка, оберіть мову:*",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("set_lang:"))
async def process_set_lang(callback: CallbackQuery, state: FSMContext, bot: Bot):
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    # Сохраняем язык в БД
    await database.update_user_language(user_id, lang)
    
    # Восстанавливаем сохраненные args для бадди-диплинка
    state_data = await state.get_data()
    args = state_data.get("start_args")
    
    # Удаляем сообщение выбора языка
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    from utils.locales import _T
    
    # Если есть бадди-диплинк, обрабатываем его
    if args and args.startswith("buddy_"):
        try:
            target_user_id = int(args.split("_")[1])
            if target_user_id == callback.from_user.id:
                await callback.message.answer("⚠️ Вы не можете стать Бадди для самого себя!")
                await callback.answer()
                return
                
            target_user = await database.get_user(target_user_id)
            if not target_user:
                await callback.message.answer("⚠️ Пользователь не найден!")
                await callback.answer()
                return
                
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🤝 Стать Бадди", callback_data=f"accept_buddy:{target_user_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_buddy:{target_user_id}")
                ]
            ])
            
            await callback.message.answer(
                f"🤝 *Запрос на поддержку / Buddy request!*\n\n"
                f"Пользователь *{target_user['first_name']}* хочет добавить вас в качестве своего **Бадди**.\n\n"
                f"Вы будете получать дружеские напоминания, если он(а) пропустит приём.\n\n"
                f"Вы согласны поддержать друга?",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
            return
        except Exception as e:
            logger.error(f"Ошибка разбора диплинка бадди: {e}")
            
    # Если диплинка нет, присылаем приветствие и главное меню
    welcome_text = _T("welcome", lang, name=callback.from_user.first_name)
    await callback.message.answer(welcome_text, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")


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


@router.message(StateFilter("*"), lambda m: m.text in [_T("menu_change_tz", "ru"), _T("menu_change_tz", "en"), _T("menu_change_tz", "uk")] if m.text else False)
async def cmd_change_timezone(message: Message, state: FSMContext):
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    await state.clear()
    await state.set_state(SetTimezone.waiting_for_timezone)
    await message.answer(
        _T("set_tz_prompt", lang),
        parse_mode="Markdown"
    )

@router.message(SetTimezone.waiting_for_timezone)
async def process_custom_timezone(message: Message, state: FSMContext):
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    tz_name = message.text.strip()
    try:
        pytz.timezone(tz_name)
        # Если часовой пояс валидный, сохраняем в БД
        await database.update_user_timezone(message.from_user.id, tz_name)
        await state.clear()
        await message.answer(
            _T("tz_success", lang, tz=tz_name),
            reply_markup=get_main_menu_keyboard(lang),
            parse_mode="Markdown"
        )
    except Exception:
        await message.answer(
            _T("invalid_tz", lang),
            parse_mode="Markdown"
        )

@router.message(StateFilter("*"), lambda m: m.text in [_T("menu_tamagotchi", "ru"), _T("menu_tamagotchi", "en"), _T("menu_tamagotchi", "uk")] if m.text else False)
async def cmd_mascot_state(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
    user = await database.get_user(message.from_user.id)
    if not user:
        return
    lang = user.get("language") if user else "ru"
        
    health = user['mascot_health']
    level = user['mascot_level']
    xp = user['mascot_xp']
    
    # Визуальное состояние маскота
    if lang == "en":
        if health >= 80:
            status_emoji = "🟢 Excellent"
            quote = "'I am full of energy and ready to monitor your schedule! We are a great team!'"
            face = "😎"
        elif health >= 40:
            status_emoji = "🟡 Normal"
            quote = "'I feel okay, but let's not skip intakes!'"
            face = "😐"
        else:
            status_emoji = "🔴 Bad (sick)"
            quote = "'Oh... I think I'm getting sick. Please take your pills on time, I feel very bad!'"
            face = "🤢"
        
        status_text = (
            f"🏥 **Mr. Tabletus Status** {face}\n\n"
            f"❤️ Health: {health}% \n`{'🟢' * int(health / 10) + '🔴' * (10 - int(health / 10))}`\n"
            f"⭐ Level: {level}\n"
            f"📈 Experience (XP): {xp}/100\n"
            f"📋 Status: {status_emoji}\n\n"
            f"💬 *Tabletus Voice:* {quote}"
        )
    elif lang == "uk":
        if health >= 80:
            status_emoji = "🟢 Відмінне"
            quote = "«Я сповнений енергії та готовий стежити за вашим розкладом! Ми чудова команда!»"
            face = "😎"
        elif health >= 40:
            status_emoji = "🟡 Нормальне"
            quote = "«Почуваюся непогано, але давайте не пропускати прийоми!»"
            face = "😐"
        else:
            status_emoji = "🔴 Погане (хворіє)"
            quote = "«Ох... здається, я занедужую. Будь ласка, прийміть ваші таблетки вчасно, мені дуже зле!»"
            face = "🤢"
        
        status_text = (
            f"🏥 **Стан Містера Таблетуса** {face}\n\n"
            f"❤️ Здоров'я: {health}% \n`{'🟢' * int(health / 10) + '🔴' * (10 - int(health / 10))}`\n"
            f"⭐ Рівень: {level}\n"
            f"📈 Досвід (XP): {xp}/100\n"
            f"📋 Статус: {status_emoji}\n\n"
            f"💬 *Голос Таблетуса:* {quote}"
        )
    else: # ru
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
            
        status_text = (
            f"🏥 **Состояние Мистера Таблетуса** {face}\n\n"
            f"❤️ Здоровье: {health}% \n`{'🟢' * int(health / 10) + '🔴' * (10 - int(health / 10))}`\n"
            f"⭐ Уровень: {level}\n"
            f"📈 Опыт (XP): {xp}/100\n"
            f"📋 Статус: {status_emoji}\n\n"
            f"💬 *Голос Таблетуса:* {quote}"
        )
        
    await message.answer(status_text, parse_mode="Markdown")

