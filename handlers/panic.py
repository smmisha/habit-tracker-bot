import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.db_helper import db_helper
from database.models import User
from services.ai_service import ai_service
from services.userbot_client import userbot
from datetime import date
from utils.states import Form
from config.config import settings

logger = logging.getLogger(__name__)
router = Router()

def get_panic_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура выбора причин паники (Шаг 2)"""
    keyboard = [
        [
            InlineKeyboardButton(text="🥱 Скучно / Нечем заняться", callback_data="panic_reason_bored"),
        ],
        [
            InlineKeyboardButton(text="😫 Сильный стресс / Усталость", callback_data="panic_reason_stressed"),
        ],
        [
            InlineKeyboardButton(text="😔 Одиноко / Грустно", callback_data="panic_reason_lonely"),
            InlineKeyboardButton(text="🔥 Сильная тяга", callback_data="panic_reason_urge")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="panic_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("panic"))
async def cmd_panic(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆘 Открыть SOS / Срыв в Mini App",
                    url=f"{settings.mini_app_link}?startapp=sos"
                )
            ]
        ]
    )
    
    await message.answer(
        "🆘 <b>РЕЖИМ SOS / ПАНИКА</b>\n\n"
        "Не поддавайтесь импульсу! Каждая секунда борьбы делает вас сильнее. "
        "Перейдите в SOS-раздел Mini App для прохождения инструкций помощи и фиксации состояния.",
        reply_markup=inline_kb
    )

@router.callback_query(F.data == "panic_guidelines_done")
async def process_panic_guidelines_done(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Помогло / Угроза миновала", callback_data="panic_first_helped"),
            InlineKeyboardButton(text="❌ Не помогло / Нужна помощь", callback_data="panic_first_failed")
        ]
    ])
    await callback.message.edit_text(
        "🆘 <b>РЕЖИМ ПАНИКИ (SOS)</b>\n\n"
        "<b>Тебе помогло справиться с тягой?</b> Выбери вариант ниже:",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "panic_first_helped")
async def process_panic_first_helped(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "💚 <b>Слава Богу! Стрик сохранен!</b>\n\n"
        "Ты проявил стойкость, применил правильные инструменты и победил искушение. "
        "Каждая такая победа делает тебя духовно и физически сильнее. Продолжай двигаться вперед! 💪"
    )

@router.callback_query(F.data == "panic_first_failed")
async def process_panic_first_failed(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    
    # 1. Получаем данные о напарнике
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        partner_username = user.partner_username if user else None
        business_connection_id = user.business_connection_id if user else None
        
    # 2. Отправляем первое экстренное сообщение напарнику
    partner_notified = False
    if partner_username and business_connection_id:
        alert_text = (
            f"🤖 [Автоматическое сообщение] Привет. Я нажал кнопку SOS в боте поддержки. "
            f"Сейчас я нахожусь на грани срыва. Мне очень нужны твои внимание и помощь. "
            f"Пожалуйста, напиши или позвони мне как можно скорее."
        )
        partner_notified = await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
        
    # 3. Переводим в состояние выбора причины
    await state.set_state(Form.waiting_for_panic_reason)
    
    notify_status = ""
    if partner_notified:
        notify_status = "🚨 <b>Напарнику отправлено экстренное уведомление!</b>\n\n"
    else:
        notify_status = "⚠️ Не удалось автоматически уведомить напарника (проверьте настройки).\n\n"
        
    await callback.message.edit_text(
        "🆘 <b>РЕЖИМ SOS (Шаг 2)</b>\n\n"
        f"{notify_status}"
        "Главное — не оставаться наедине с этим состоянием. "
        "Сейчас мы подключим ИИ-поддержку.\n\n"
        "<b>Что именно ты чувствуешь?</b> Выбери причину ниже или напиши свое состояние текстом (ответом на это сообщение):",
        reply_markup=get_panic_keyboard()
    )

async def handle_panic_action(user_id: int, reason_text: str, partner_reason: str, state: FSMContext, callback: CallbackQuery = None, message: Message = None):
    """Общая логика обработки паники (ИИ + отправка напарнику)"""
    # 1. Получаем данные о напарнике и лимитах ИИ
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            return
            
        partner_username = user.partner_username
        business_connection_id = user.business_connection_id
        
        # Сброс дневного счетчика вопросов, если настал новый день
        today_dt = date.today()
        if user.last_ai_query_date != today_dt:
            user.last_ai_query_date = today_dt
            user.ai_questions_used_today = 0
            
        # Расчет дневного лимита (базовый 3 + по 1 за каждую медаль)
        milestones_count = len([m for m in (user.awarded_milestones or "").split(",") if m.strip().isdigit()])
        daily_limit = 3 + milestones_count
        
        questions_left_before = max(0, daily_limit - user.ai_questions_used_today)
        
        if questions_left_before <= 0:
            # Лимит уже исчерпан на сегодня
            limit_msg = (
                "🆘 <b>РЕЖИМ SOS АКТИВИРОВАН</b>\n"
                "──────────────────────────\n"
                "🛑 <b>Ежедневный лимит ИИ-помощника исчерпан!</b>\n\n"
                f"На сегодня ты израсходовал все свои вопросы к ИИ (твой лимит согласно достижениям: <b>{daily_limit}</b> в день).\n\n"
                "Прекращай вести внутренние споры и искать оправдания. Закрой Telegram, сделай приседания или свяжись с напарником."
            )
            if callback:
                await callback.message.edit_text(limit_msg)
            elif message:
                await message.answer(limit_msg)
                
            # Все равно отправляем сообщение напарнику
            if partner_username and business_connection_id:
                alert_text = (
                    f"🤖 [Автоматическое сообщение] (Уточнение состояния) "
                    f"Мой триггер: {partner_reason}."
                )
                await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)
            return

        # Увеличиваем счетчик использованных вопросов
        user.ai_questions_used_today += 1
        await session.commit()
        
    # 2. Вызываем ИИ для генерации слов поддержки
    status_msg = None
    if callback:
        status_msg = await callback.message.edit_text("⏳ <i>Подключаю ИИ-ассистента для поддержки...</i>")
    elif message:
        status_msg = await message.answer("⏳ <i>Подключаю ИИ-ассистента для поддержки...</i>")
        
    ai_response = await ai_service.generate_sos_response(reason_text)
    
    # Считаем оставшиеся
    questions_left = max(0, daily_limit - user.ai_questions_used_today)
    
    # Инициализируем историю диалога в FSM, только если остались вопросы
    if questions_left > 0:
        history = [
            {"role": "user", "parts": [{"text": reason_text}]},
            {"role": "model", "parts": [{"text": ai_response}]}
        ]
        await state.set_state(Form.panic_chat)
        await state.update_data(history=history)
        info_text = f"💬 Ты можешь задать ИИ еще до <b>{questions_left}</b> уточняющих вопросов сегодня."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🏁 Завершить диалог", callback_data="panic_chat_finish")
            ]
        ])
    else:
        await state.clear()
        info_text = "🛑 Это был твой последний вопрос к ИИ на сегодня. Лимит исчерпан."
        keyboard = None
    
    # Форматируем красивый ответ с ИИ-поддержкой и инструкцией по чату
    support_text = (
        "🆘 <b>РЕЖИМ SOS АКТИВИРОВАН</b>\n"
        "──────────────────────────\n"
        f"{ai_response}\n"
        "──────────────────────────\n"
        f"{info_text}\n"
        "🚨 <b>Напарнику отправлено уведомление!</b> Постарайся дождаться ответа и не оставаться наедине со своими мыслями."
    )
    
    if status_msg:
        await status_msg.edit_text(support_text, reply_markup=keyboard)
        
    # 3. Отправляем сообщение напарнику (уточнение триггера)
    if partner_username and business_connection_id:
        alert_text = (
            f"🤖 [Автоматическое сообщение] (Уточнение состояния) "
            f"Мой триггер: {partner_reason}."
        )
        await userbot.send_message_to_partner(business_connection_id, partner_username, alert_text)

@router.callback_query(F.data.startswith("panic_reason_"))
async def process_panic_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    action = callback.data
    
    reasons = {
        "panic_reason_bored": ("скука и безделье", "Скука / Безделье"),
        "panic_reason_stressed": ("сильный стресс и усталость", "Стресс / Усталость"),
        "panic_reason_lonely": ("чувство одиночества и грусти", "Одиночество / Грусть"),
        "panic_reason_urge": ("сильная физическая тяга", "Сильная тяга")
    }
    
    reason_desc, partner_desc = reasons.get(action, ("неизвестное состояние", "Общая тяга"))
    
    await handle_panic_action(
        user_id=user_id,
        reason_text=f"Я чувствую: {reason_desc}. Мне очень тяжело держаться.",
        partner_reason=partner_desc,
        state=state,
        callback=callback
    )

@router.callback_query(F.data == "panic_cancel")
async def process_panic_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("💚 <b>Отмена режима паники.</b>\n\nОтличная работа! Ты контролируешь ситуацию. Продолжай двигаться вперед! 💪")

@router.message(Form.waiting_for_panic_reason)
async def process_panic_text_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    await handle_panic_action(
        user_id=user_id,
        reason_text=user_text,
        partner_reason=f"Текстовое описание: \"{user_text}\"",
        state=state,
        message=message
    )

@router.callback_query(F.data == "panic_chat_finish")
async def process_panic_chat_finish(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "💚 <b>Диалог с ИИ завершен.</b>\n\n"
        "Ты принял правильное решение прекратить внутренние споры и оправдания. "
        "Пожалуйста, закрой Telegram, займись спортом, выйди на улицу или позвони напарнику! 💪"
    )

@router.message(Form.panic_chat)
async def process_panic_chat_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    async with db_helper.session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await state.clear()
            return
            
        # Сброс дневного счетчика вопросов, если настал новый день
        today_dt = date.today()
        if user.last_ai_query_date != today_dt:
            user.last_ai_query_date = today_dt
            user.ai_questions_used_today = 0
            
        milestones_count = len([m for m in (user.awarded_milestones or "").split(",") if m.strip().isdigit()])
        daily_limit = 3 + milestones_count
        
        questions_left = max(0, daily_limit - user.ai_questions_used_today)
        
        if questions_left <= 0:
            await state.clear()
            await message.answer(
                "🛑 <b>Лимит общения на сегодня исчерпан.</b>\n\n"
                "Уловки ума и попытки оправданий позади. "
                "Пожалуйста, закрой мессенджер, сделай физические упражнения или свяжись с напарником прямо сейчас."
            )
            return
            
        # Увеличиваем счетчик использованных вопросов
        user.ai_questions_used_today += 1
        await session.commit()
        
        # Считаем оставшиеся после этого запроса
        questions_left_after = max(0, daily_limit - user.ai_questions_used_today)
        
    data = await state.get_data()
    history = data.get("history", [])
    
    # Добавляем сообщение пользователя в историю
    history.append({"role": "user", "parts": [{"text": user_text}]})
    
    status_msg = await message.answer("⏳ <i>ИИ обдумывает ответ...</i>")
    
    # Запрос к Gemini с учетом истории
    ai_response = await ai_service.generate_chat_response(history)
    
    # Добавляем ответ ИИ в историю
    history.append({"role": "model", "parts": [{"text": ai_response}]})
    
    # Обновляем состояние
    await state.update_data(history=history)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏁 Завершить диалог", callback_data="panic_chat_finish")
        ]
    ])
    
    if questions_left_after > 0:
        info_text = f"💬 Осталось вопросов к ИИ на сегодня: <b>{questions_left_after}</b>."
        response_text = (
            "🆘 <b>РЕЖИМ SOS (Диалог с ИИ)</b>\n"
            "──────────────────────────\n"
            f"{ai_response}\n"
            "──────────────────────────\n"
            f"{info_text}\n"
            "<i>Напиши свой вопрос или нажми кнопку ниже:</i>"
        )
        await status_msg.edit_text(response_text, reply_markup=keyboard)
    else:
        # Если вопросов больше нет, сразу завершаем сессию
        await state.clear()
        response_text = (
            "🆘 <b>РЕЖИМ SOS (Диалог завершен)</b>\n"
            "──────────────────────────\n"
            f"{ai_response}\n"
            "──────────────────────────\n"
            "🛑 <b>Это был твой последний вопрос на сегодня. Лимит исчерпан.</b>\n\n"
            "Прекращай вести внутренний диалог и оправдывать себя. "
            "Закрой мессенджер, займись спортом или напиши напарнику."
        )
        await status_msg.edit_text(response_text)
