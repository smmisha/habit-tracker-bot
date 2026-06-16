from datetime import datetime
from io import BytesIO
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.db_helper import db_helper
from database.models import User, RelapseLog
from keyboards.inline import get_relapse_confirm_keyboard
from config.config import settings
from services.userbot_client import userbot
from services.ai_service import ai_service

logger = logging.getLogger(__name__)
router = Router()

def format_timedelta(td) -> str:
    """Форматирование разницы во времени в читаемый вид"""
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"<b>{days}</b> дн.")
    if hours > 0 or days > 0:
        parts.append(f"<b>{hours}</b> ч.")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"<b>{minutes}</b> мин.")
    parts.append(f"<b>{seconds}</b> сек.")
    
    return " ".join(parts)

@router.message(Command("streak"))
async def cmd_my_streak(message: Message):
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Пользователь не найден. Введите /start.")
            return
            
        import pytz
        try:
            user_tz = pytz.timezone(user.timezone)
            now_local = datetime.now(user_tz)
            streak_start_utc = pytz.utc.localize(user.streak_start)
            streak_start_local = streak_start_utc.astimezone(user_tz)
            delta = now_local - streak_start_local
        except Exception:
            delta = datetime.now() - user.streak_start
            
        formatted_streak = format_timedelta(delta)
        
    stats_text = (
        "📊 <b>СТАТИСТИКА ЧИСТОТЫ</b>\n"
        "──────────────────────────\n"
        f"⏳ <b>Текущий стрик:</b> {formatted_streak}\n"
        f"⚠️ <b>Всего срывов:</b> <code>{user.total_relapses}</code>\n"
        "──────────────────────────"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Открыть дашборд в Mini App",
                    url=f"{settings.mini_app_link}?startapp=dashboard"
                )
            ]
        ]
    )
    await message.answer(stats_text, reply_markup=inline_kb)

# Оставляем хэндлеры срывов для вызова по API / команд (если нужно), но убираем текстовый матчинг кнопок

async def cmd_relapse(message: Message):
    await message.answer(
        "⚠️ <b>Вы уверены, что произошел срыв?</b>\n\n"
        "Это действие сбросит ваш счетчик чистоты до нуля и <b>автоматически отправит сообщение</b> вашему напарнику.",
        reply_markup=get_relapse_confirm_keyboard()
    )

from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from utils.states import Form

def get_trigger_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора триггеров срыва"""
    keyboard = [
        [
            InlineKeyboardButton(text="🥱 Скука / Безделье", callback_data="relapse_trigger_bored"),
            InlineKeyboardButton(text="😫 Стресс / Усталость", callback_data="relapse_trigger_stress")
        ],
        [
            InlineKeyboardButton(text="😔 Одиночество / Грусть", callback_data="relapse_trigger_lonely"),
            InlineKeyboardButton(text="🔞 Искушение в интернете", callback_data="relapse_trigger_web")
        ],
        [
            InlineKeyboardButton(text="📝 Другое", callback_data="relapse_trigger_other"),
            InlineKeyboardButton(text="❌ Отмена срыва", callback_data="relapse_trigger_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data == "relapse_confirm")
async def process_relapse_confirm(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "⚠️ <b>Запись срыва</b>\n\n"
        "Нам искренне жаль. Но помни: срыв — это не поражение, а повод сделать работу над ошибками. "
        "Путь к свободе не бывает идеально ровным. Не сдавайся!\n\n"
        "<b>Что послужило главным триггером срыва?</b> Выбери вариант на кнопках ниже:",
        reply_markup=get_trigger_keyboard()
    )

async def execute_relapse_reset(user_id: int, trigger_reason: str, callback: CallbackQuery = None, message: Message = None):
    """Выполнить сброс счетчика чистоты и залогировать причину"""
    now = datetime.now()
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return
            
        # 1. Сброс стрика и очистка наград
        user.streak_start = now
        user.total_relapses += 1
        user.awarded_milestones = ""
        
        # 2. Логирование срыва
        log = RelapseLog(
            user_id=user_id,
            timestamp=now,
            trigger_reason=trigger_reason
        )
        session.add(log)
        await session.commit()
        
        partner_username = user.partner_username
        business_connection_id = user.business_connection_id
        
        # 3. Расчет статистики триггеров
        relapses_result = await session.execute(
            select(RelapseLog.trigger_reason)
            .where(RelapseLog.user_id == user_id)
        )
        reasons = relapses_result.scalars().all()
        total_relapses = len(reasons)
        
    import html
    stats_list = []
    if total_relapses > 0:
        counts = {}
        for r in reasons:
            if not r:
                continue
            # Группировка
            clean_reason = r
            if r.startswith("Другое:") or r.startswith("Текстовое описание:"):
                clean_reason = "Другая причина"
            elif r == "Ручной сброс через меню бота":
                clean_reason = "Без указания причины"
            
            counts[clean_reason] = counts.get(clean_reason, 0) + 1
            
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        for reason, count in sorted_counts:
            pct = int((count / total_relapses) * 100)
            escaped_reason = html.escape(reason)
            stats_list.append(f"• <b>{escaped_reason}</b>: {pct}% ({count} раз)")
            
    stats_text = "\n".join(stats_list) if stats_list else "Нет данных."
    
    try:
        if callback:
            await callback.message.edit_text("⏳ <i>Подключаю ИИ-ассистента...</i>")
        elif message:
            await message.answer("⏳ <i>Подключаю ИИ-ассистента...</i>")
    except Exception as e:
        logger.warning(f"Failed to send 'Connecting AI' status: {e}")
 
    try:
        ai_response = await ai_service.generate_relapse_response(trigger_reason)
    except Exception as e:
        logger.error(f"Error calling AI service in execute_relapse_reset: {e}")
        ai_response = (
            "Очень жаль, что это произошло. Но помни: срыв — это не поражение, а повод сделать работу над ошибками. "
            "Не сдавайся, твой стрик чистоты начат заново! Ты справишься."
        )

    ai_response_escaped = html.escape(ai_response)
    confirm_text = (
        "😔 <b>Счетчик сброшен. Стрик чистоты начат заново!</b>\n\n"
        f"{ai_response_escaped}\n\n"
        "📊 <b>Статистика твоих триггеров срывов:</b>\n"
        f"{stats_text}"
    )
    
    try:
        if callback:
            await callback.message.edit_text(confirm_text)
        elif message:
            await message.answer(confirm_text)
    except Exception as e:
        logger.error(f"Failed to send confirmation text to user: {e}")
        if callback:
            try:
                await callback.message.answer(confirm_text)
            except Exception as e2:
                logger.error(f"Failed to send confirmation fallback: {e2}")
        
    # 4. Оповещение напарника
    if partner_username and business_connection_id:
        try:
            alert_text = await ai_service.humanize_relapse_confession(trigger_reason)
        except Exception as e:
            logger.error(f"Error humanizing confession: {e}")
            escaped_trigger = html.escape(trigger_reason)
            alert_text = f"Привет. К сожалению, сегодня у меня произошел срыв. Причина: {escaped_trigger}."
        
        try:
            sent = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
        except Exception as e:
            logger.error(f"Error sending message to partner: {e}")
            sent = False
        
        notify_msg = f"✅ Сообщение напарнику <code>@{partner_username}</code> успешно отправлено автоматически." if sent else f"⚠️ Не удалось автоматически отправить сообщение напарнику <code>@{partner_username}</code>."
        
        try:
            if callback:
                await callback.message.answer(notify_msg)
            elif message:
                await message.answer(notify_msg)
        except Exception as e:
            logger.error(f"Failed to send partner notification status to user: {e}")

async def start_confession_flow(user_id: int, trigger_reason: str, state: FSMContext, message: Message = None, callback: CallbackQuery = None, bot = None):
    """Инициализация процесса исповеди перед сбросом счетчика"""
    await state.set_state(Form.waiting_for_confession)
    await state.update_data(relapse_trigger_reason=trigger_reason)
    
    prompt_text = (
        "⚠️ <b>Шаг подтверждения срыва: Зеркало исповеди</b>\n\n"
        "Для сброса счетчика вы должны прислать в этот чат <b>голосовое сообщение или видеосообщение</b> с искренним признанием.\n\n"
        "💬 <b>Произнесите слова:</b>\n"
        "<i>«Иегова видит меня. Я признаю, что совершил срыв, и беру на себя ответственность перед старейшиной Андреем.»</i>\n\n"
        "ИИ проверит ваше сообщение. Только после успешной проверки счетчик чистоты будет сброшен, а старейшина Андрей получит автоматическое уведомление."
    )
    
    if callback:
        await callback.message.edit_text(prompt_text)
    elif message:
        await message.answer(prompt_text)
    elif bot:
        try:
            await bot.send_message(chat_id=user_id, text=prompt_text)
        except Exception as e:
            logger.error(f"Failed to send confession prompt to user {user_id}: {e}")

@router.callback_query(F.data.startswith("relapse_trigger_"))
async def process_relapse_trigger(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    action = callback.data
    
    if action == "relapse_trigger_cancel":
        await callback.message.edit_text("💚 <b>Отмена сброса.</b>\n\nТвой стрик в полной безопасности! Рад, что это была ложная тревога. Продолжай держаться! 💪")
        return
        
    if action == "relapse_trigger_other":
        await callback.message.edit_text("📝 Пожалуйста, кратко напишите в ответном сообщении, что послужило причиной срыва:")
        await state.set_state(Form.waiting_for_relapse_trigger_other)
        return
        
    reasons = {
        "relapse_trigger_bored": "Скука / Безделье",
        "relapse_trigger_stress": "Стресс / Усталость",
        "relapse_trigger_lonely": "Одиночество / Грусть",
        "relapse_trigger_web": "Искушение в интернете"
    }
    trigger = reasons.get(action, "Общая причина")
    await start_confession_flow(user_id, trigger, state=state, callback=callback)

@router.message(Form.waiting_for_relapse_trigger_other)
async def process_relapse_trigger_other_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    await start_confession_flow(user_id, f"Другое: {text}", state=state, message=message)

@router.message(Form.waiting_for_confession, F.voice | F.video_note)
async def process_confession_media(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    status_msg = await message.answer("⏳ <i>Скачиваю медиафайл и отправляю на проверку в Gemini AI...</i>")
    
    try:
        file_in_io = BytesIO()
        if message.voice:
            file = await message.bot.get_file(message.voice.file_id)
            mime_type = message.voice.mime_type or "audio/ogg"
            await message.bot.download_file(file.file_path, file_in_io)
        else: # video_note
            file = await message.bot.get_file(message.video_note.file_id)
            mime_type = "video/mp4"
            await message.bot.download_file(file.file_path, file_in_io)
            
        file_bytes = file_in_io.getvalue()
        
        await status_msg.edit_text("🎙️ <i>Gemini AI анализирует вашу речь на наличие признания срыва...</i>")
        
        is_approved = await ai_service.verify_confession_speech(file_bytes, mime_type)
        
        if is_approved:
            await status_msg.delete()
            state_data = await state.get_data()
            trigger_reason = state_data.get("relapse_trigger_reason", "Срыв подтвержден исповедью")
            await state.clear()
            await execute_relapse_reset(user_id, trigger_reason, message=message)
        else:
            await status_msg.edit_text(
                "❌ <b>Исповедь отклонена Gemini AI</b>\n\n"
                "Вы должны искренне и внятно признать свой срыв, упомянув Бога и напарника.\n\n"
                "💬 <b>Попробуйте сказать еще раз:</b>\n"
                "<i>«Иегова видит меня. Я признаю, что совершил срыв, и беру на себя ответственность перед старейшиной Андреем.»</i>\n\n"
                "Запишите и отправьте новое голосовое сообщение или видеосообщение."
            )
    except Exception as e:
        logger.error(f"Error processing confession: {e}")
        await status_msg.edit_text(
            "⚠️ Произошла техническая ошибка при проверке аудио/видео. Пожалуйста, попробуйте записать еще раз или введите /cancel для отмены."
        )

@router.message(Form.waiting_for_confession)
async def process_confession_invalid_type(message: Message):
    await message.answer(
        "⚠️ <b>Ожидание признания (Зеркало исповеди)</b>\n\n"
        "Для подтверждения срыва и сброса счетчика вы <b>обязаны отправить голосовое сообщение или видеосообщение</b>.\n\n"
        "💬 <b>Произнесите слова:</b>\n"
        "<i>«Иегова видит меня. Я признаю, что совершил срыв, и беру на себя ответственность перед старейшиной Андреем.»</i>\n\n"
        "Если вы хотите отменить сброс, отправьте команду /cancel."
    )

@router.callback_query(F.data == "relapse_cancel")
async def process_relapse_cancel(callback: CallbackQuery):
    await callback.message.edit_text("✅ Отмена. Держись, ты справляешься! 💪")
    await callback.answer()
