import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from config.config import settings

logger = logging.getLogger(__name__)
router = Router()

async def send_spiritual_message_to_user(bot, user_id: int, data: dict):
    """
    Отправляет персонализированное сообщение с духовным наставлением и ОДНОЙ целевой
    статьей в личный чат пользователя в Telegram.
    """
    thought = data.get("spiritual_thought", "")
    action = data.get("spiritual_action", "Преклоните колени в молитве о даровании святого духа (1 Кор. 10:13).")
    primary = data.get("primary_material") or (data.get("materials", [{}])[0])
    temptation_title = data.get("temptation_title", "Духовное подкрепление")
    
    text = (
        f"📖 <b>ДУХОВНОЕ ПОДКРЕПЛЕНИЕ: {temptation_title.upper()}</b>\n"
        "───────────────────────────────────\n"
        f"{thought}\n\n"
        f"💡 <b>Духовный шаг прямо сейчас:</b>\n"
        f"<i>{action}</i>\n\n"
        f"🎯 <b>Целевой библейский материал для изучения:</b>\n"
        f"• <b>{primary.get('title', '')}</b>\n"
        f"<i>{primary.get('description', '')}</i>"
    )
    
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{primary.get('icon', '📖')} Открыть статью на {primary.get('type_label', 'wol.jw.org')}",
                url=primary.get("url")
            )
        ],
        [
            InlineKeyboardButton(
                text="📖 Я прочитал(а) статью",
                callback_data="spiritual_read"
            )
        ],
        [
            InlineKeyboardButton(
                text="📱 Открыть в Mini App",
                url=f"{settings.mini_app_link}?startapp=sos"
            )
        ]
    ]
    
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await bot.send_message(chat_id=user_id, text=text, reply_markup=markup, disable_web_page_preview=True)

@router.message(Command("panic"))
async def cmd_panic(message: Message, state: FSMContext):
    await state.clear()
    
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆘 Открыть SOS / Срыв в Mini App",
                    url=f"{settings.mini_app_link}?startapp=sos"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📖 Духовное подкрепление (jw.org / wol)",
                    callback_data="send_spiritual_help"
                )
            ]
        ]
    )
    
    await message.answer(
        "🆘 <b>РЕЖИМ SOS / ПАНИКА</b>\n\n"
        "Не поддавайтесь импульсу! Каждая секунда борьбы делает вас сильнее. "
        "Перейдите в SOS-раздел Mini App или нажмите кнопку ниже, чтобы получить духовное подкрепление.",
        reply_markup=inline_kb
    )

@router.callback_query(F.data == "send_spiritual_help")
async def cb_send_spiritual_help(callback: CallbackQuery):
    await callback.answer("Подбираем целевой духовный материал...", show_alert=False)
    from services.ai_service import ai_service
    data = await ai_service.generate_spiritual_study_materials()
    await send_spiritual_message_to_user(callback.bot, callback.from_user.id, data)

@router.callback_query(F.data == "spiritual_read")
async def cb_spiritual_read(callback: CallbackQuery):
    await callback.answer("Статья прочитана! Почувствовали облегчение?", show_alert=False)
    try:
        # Обновляем кнопки под сообщением, предлагая отметить победу
        current_markup = callback.message.reply_markup
        new_keyboard = []
        if current_markup and current_markup.inline_keyboard:
            # Оставляем кнопку ссылки на статью
            new_keyboard.append([current_markup.inline_keyboard[0][0]])
            
        new_keyboard.append([
            InlineKeyboardButton(
                text="✅ Помогло! Тяга отступила",
                callback_data="spiritual_helped"
            )
        ])
        new_keyboard.append([
            InlineKeyboardButton(
                text="📱 Открыть Mini App",
                url=f"{settings.mini_app_link}?startapp=sos"
            )
        ])
        
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard)
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить клавиатуру spiritual_read: {e}")

@router.callback_query(F.data == "spiritual_helped")
async def cb_spiritual_helped(callback: CallbackQuery):
    await callback.answer("Слава Богу! Тяга отступила, стрик сохранен! 💪", show_alert=True)
    try:
        await callback.message.edit_text(
            "🎉 <b>Слава Богу! Вы устояли перед искушением!</b>\n\n"
            "Ваш стрик чистоты продолжается. Иегова видит ваше искреннее сердце и благословляет вашу верность (1 Коринфянам 10:13)."
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить сообщение духовной помощи: {e}")

