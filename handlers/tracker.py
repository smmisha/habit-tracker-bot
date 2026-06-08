from datetime import datetime
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.db_helper import db_helper
from database.models import User, RelapseLog
from keyboards.inline import get_relapse_confirm_keyboard
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
@router.message(F.text == "📊 Мой счетчик")
async def cmd_my_streak(message: Message):
    user_id = message.from_user.id
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Пользователь не найден. Введите /start.")
            return
            
        # Вычисляем разницу времени (в БД хранится наивный UTC)
        import pytz
        try:
            user_tz = pytz.timezone(user.timezone)
            now_local = datetime.now(user_tz)
            
            # Локализируем время начала стрика из БД как UTC и переводим в таймзону пользователя
            streak_start_utc = pytz.utc.localize(user.streak_start)
            streak_start_local = streak_start_utc.astimezone(user_tz)
            
            delta = now_local - streak_start_local
            display_start = streak_start_local.strftime('%d.%m.%Y %H:%M:%S')
        except Exception as e:
            logger.error(f"Ошибка конвертации таймзоны: {e}")
            delta = datetime.now() - user.streak_start
            display_start = user.streak_start.strftime('%d.%m.%Y %H:%M:%S')
            
        formatted_streak = format_timedelta(delta)
        
        partner_display = "не указан ⚠️"
        if user.partner_username:
            partner_display = user.partner_username if user.partner_username.isdigit() else f"@{user.partner_username}"
            
        # Генерируем мотивационную цитату с помощью ИИ
        streak_days = max(0, delta.days)
        ai_quote = await ai_service.generate_daily_motivational_quote(streak_days)
            
        stats_text = (
            "📊 <b>СТАТИСТИКА ЧИСТОТЫ</b>\n"
            "──────────────────────────\n"
            f"⏳ <b>Текущий стрик:</b> {formatted_streak}\n"
            f"📅 <b>Начало стрика:</b> <code>{display_start}</code>\n"
            f"⚠️ <b>Всего срывов:</b> <code>{user.total_relapses}</code>\n"
            f"👥 <b>Ваш напарник:</b> <code>{partner_display}</code>\n"
            "──────────────────────────\n"
            f"💪 <i>{ai_quote}</i>"
        )
    await message.answer(stats_text)

@router.message(F.text == "⚠️ Срыв")
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
            stats_list.append(f"• <b>{reason}</b>: {pct}% ({count} раз)")
            
    stats_text = "\n".join(stats_list) if stats_list else "Нет данных."
    
    if callback:
        await callback.message.edit_text("⏳ <i>Подключаю ИИ-ассистента...</i>")
    elif message:
        await message.answer("⏳ <i>Подключаю ИИ-ассистента...</i>")

    ai_response = await ai_service.generate_relapse_response(trigger_reason)

    confirm_text = (
        "😔 <b>Счетчик сброшен. Стрик чистоты начат заново!</b>\n\n"
        f"{ai_response}\n\n"
        "📊 <b>Статистика твоих триггеров срывов:</b>\n"
        f"{stats_text}"
    )
    
    if callback:
        await callback.message.edit_text(confirm_text)
    elif message:
        await message.answer(confirm_text)
        
    # 4. Оповещение напарника
    if partner_username and business_connection_id:
        alert_text = (
            f"🤖 [Автоматическое сообщение] Привет. Я пишу тебе, чтобы признаться: сегодня у меня произошел срыв, "
            f"и я сбросил счетчик чистоты. (Причина: {trigger_reason}). Мне очень нужны твои поддержка и контроль сейчас."
        )
        sent = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
        
        notify_msg = f"✅ Сообщение напарнику <code>@{partner_username}</code> успешно отправлено автоматически." if sent else f"⚠️ Не удалось автоматически отправить сообщение напарнику <code>@{partner_username}</code>."
        
        if callback:
            await callback.message.answer(notify_msg)
        elif message:
            await message.answer(notify_msg)

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
    await execute_relapse_reset(user_id, trigger, callback=callback)

@router.message(Form.waiting_for_relapse_trigger_other)
async def process_relapse_trigger_other_text(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    text = message.text.strip()
    await execute_relapse_reset(user_id, f"Другое: {text}", message=message)

@router.callback_query(F.data == "relapse_cancel")
async def process_relapse_cancel(callback: CallbackQuery):
    await callback.message.edit_text("✅ Отмена. Держись, ты справляешься! 💪")
    await callback.answer()
