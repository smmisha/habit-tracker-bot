from datetime import datetime, timezone
from io import BytesIO
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, and_
from database.db_helper import db_helper
from database.models import User, RelapseLog, CheckInLog, SlipEvent
from keyboards.inline import get_relapse_confirm_keyboard, get_reset_type_keyboard, get_trigger_keyboard
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

async def execute_relapse_reset(user_id: int, trigger_reason: str, callback: CallbackQuery = None, message: Message = None, bot = None):
    """Выполнить сброс счетчика чистоты и залогировать причину"""
    now = datetime.now()
    now_utc = datetime.now(timezone.utc)
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return {"partner_notified": False, "recent_count": 0, "confirm_text": "Пользователь не найден"}
            
        # 1. Сброс стрика и очистка наград
        user.streak_start = now
        user.total_relapses += 1
        user.awarded_milestones = ""
        
        # 2. Логирование срыва в традиционный лог (для совместимости)
        log = RelapseLog(
            user_id=user_id,
            timestamp=now,
            trigger_reason=trigger_reason
        )
        session.add(log)
        
        # 3. Логирование срыва в slip_events (в UTC)
        slip = SlipEvent(
            user_id=user_id,
            occurred_at=now_utc,
            notified_partner=False
        )
        session.add(slip)
        
        # 4. Обновляем активный чек-ин на "relapsed", если он находится в статусе pending
        checkin_result = await session.execute(
            select(CheckInLog)
            .where(and_(CheckInLog.user_id == user_id, CheckInLog.status == "pending"))
        )
        active_checkin = checkin_result.scalar_one_or_none()
        if active_checkin:
            active_checkin.status = "relapsed"
            active_checkin.timestamp = now
            
        # Сохраняем в БД, чтобы новая запись попала в выборку
        await session.commit()
        
        # 5. Автоматическое уведомление напарника при ЛЮБОМ срыве (без поблажек и задержек)
        partner_username = user.partner_username
        business_connection_id = user.business_connection_id
        
        partner_notified = False
        if partner_username:
            user_tag = f"@{user.username}" if user.username else (user.first_name or f"ID {user.id}")
            alert_text = (
                f"⚠️ <b>Уведомление о срыве</b>\n\n"
                f"Пользователь {user_tag} зафиксировал срыв.\n"
                f"Счетчик чистоты сброшен."
            )
            try:
                sent = await userbot.send_message_to_partner(
                    business_connection_id=business_connection_id,
                    partner_username=partner_username,
                    text=alert_text,
                    bot=bot
                )
                if sent:
                    partner_notified = True
                    slip.notified_partner = True
                    await session.commit()
            except Exception as e:
                logger.error(f"Error sending relapse alert to partner: {e}")
                    
        # 6. Расчет статистики триггеров
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
    
    confirm_text = "😔 <b>Счетчик сброшен. Стрик чистоты начат заново!</b>\n\n"
    if partner_notified:
        partner_tag = partner_username if partner_username.isdigit() else f"@{partner_username}"
        confirm_text += f"📬 Вашему напарнику <code>{partner_tag}</code> автоматически отправлено уведомление о срыве.\n\n"
    elif partner_username:
        confirm_text += "⚠️ <i>Не удалось доставить авто-уведомление напарнику. Пожалуйста, напишите ему лично.</i>\n\n"
    else:
        confirm_text += "ℹ️ Напарник не указан в настройках бота.\n\n"
        
    confirm_text += (
        "📊 <b>Статистика твоих триггеров срывов:</b>\n"
        f"{stats_text}"
    )
    
    confirm_text += (
        "\n\n🕊️ <b>Точка нового старта:</b>\n"
        "Срыв — это не поражение, а повод сделать работу над ошибками. "
        "Перечитайте и подтвердите Соглашение совести перед Иеговой, чтобы обновить свой фокус и продолжить путь чистоты."
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    from config.config import settings
    covenant_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📜 Читать и подтвердить Соглашение совести",
                    web_app=WebAppInfo(url=f"{settings.webapp_base_url.rstrip('/')}/webapp/purity_covenant_jw_v2.html")
                )
            ]
        ]
    )
    
    try:
        if callback:
            await callback.message.edit_text(confirm_text, reply_markup=covenant_kb)
        elif message:
            await message.answer(confirm_text, reply_markup=covenant_kb)
        elif bot:
            await bot.send_message(chat_id=user_id, text=confirm_text, reply_markup=covenant_kb)
        else:
            from main import bot as default_bot
            await default_bot.send_message(chat_id=user_id, text=confirm_text, reply_markup=covenant_kb)
    except Exception as e:
        logger.error(f"Failed to send confirmation text to user: {e}")

    return {
        "partner_notified": partner_notified,
        "recent_count": 1 if partner_notified else 0,
        "confirm_text": confirm_text
    }

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
    user_id = message.from_user.id
    text = message.text.strip()
    await state.clear()
    await execute_relapse_reset(user_id, f"Другое: {text}", message=message)

@router.callback_query(F.data == "relapse_cancel")
async def process_relapse_cancel(callback: CallbackQuery):
    await callback.message.edit_text("✅ Отмена. Держись, ты справляешься! 💪")
    await callback.answer()
