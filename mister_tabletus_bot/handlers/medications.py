import os
import asyncio
import re
import uuid
import logging
from datetime import datetime, timedelta
import pytz
from aiogram import Router, F, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

import database
import scheduler
from utils import gemini_service
from handlers.start import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()

async def download_searched_image(url: str) -> str:
    """Скачивает изображение по ссылке во временный файл и возвращает путь к нему"""
    import urllib.request
    import os
    import uuid
    import asyncio
    
    os.makedirs("photos", exist_ok=True)
    ext = url.split('.')[-1].split('?')[0].lower()
    if ext not in ['jpg', 'jpeg', 'png']:
        ext = 'jpg'
    local_path = f"photos/{uuid.uuid4()}.{ext}"
    
    def download():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(local_path, 'wb') as f:
                    f.write(response.read())
            return local_path
        except Exception as e:
            logger.error(f"Не удалось скачать картинку {url}: {e}")
            return None
            
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, download)


# Состояния FSM для добавления лекарства
class AddMedication(StatesGroup):
    waiting_for_input = State()         # Ожидание фото, текста или кнопки "Вручную"
    confirming_parsed = State()         # Подтверждение автоматически распарсенных данных
    waiting_for_name = State()          # Ручной ввод: название
    waiting_for_dosage = State()        # Ручной ввод: дозировка
    waiting_for_food = State()          # Ручной ввод: отношение к еде
    waiting_for_times = State()         # Ручной ввод: время приемов
    waiting_for_stock = State()         # Ручной ввод: остаток в аптечке
    waiting_for_schedule_after_photo = State() # После фото: ожидание ввода графика текстом

# --- СПИСОК ЛЕКАРСТВ ---

@router.message(StateFilter("*"), F.text == "💊 Мои лекарства")
async def list_medications(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
    meds = await database.get_user_medications(message.from_user.id)
    if not meds:
        await message.answer(
            "📭 Ваша аптечка пуста. Нажмите *➕ Добавить лекарство*, чтобы внести первое средство.",
            parse_mode="Markdown"
        )
        return
        
    text = "📋 *Ваша active аптечка:*\n\n"
    for idx, med in enumerate(meds, 1):
        relation_text = {
            'before_meal': 'до еды 🍽️',
            'with_meal': 'во время еды 🍽️',
            'after_meal': 'после еды 🍽️',
            'none': 'без связи с едой'
        }.get(med['food_relation'], 'нет данных')
        
        # Получим время напоминаний
        reminders = await database.get_medication_reminders(med['id'])
        times_list = ", ".join([r['time_str'] for r in reminders]) if reminders else "не задано"
        
        active_ing = f" ({med['active_ingredient']})" if med['active_ingredient'] else ""
        text += (
            f"{idx}. *{med['name']}*{active_ing}\n"
            f"   ⚖️ Дозировка: {med['dosage'] or 'не указана'}\n"
            f"   🍽️ Прием: {relation_text}\n"
            f"   ⏰ Время: {times_list}\n"
            f"   📦 Остаток: {med['stock_count']} шт. (порог: {med['stock_alert_threshold']})\n"
        )
        
        # Добавляем кнопку удаления для каждого лекарства
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"del_med:{med['id']}")
            ]
        ])
        
        image_path = med['image_path']
        if not image_path or not os.path.exists(image_path):
            image_path = "photos/default_pill.png"
            
        if os.path.exists(image_path):
            from aiogram.types import FSInputFile
            await message.answer_photo(
                photo=FSInputFile(image_path),
                caption=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        # Сбрасываем текст для следующего лекарства
        text = ""

@router.callback_query(F.data.startswith("del_med:"))
async def process_delete_medication(callback: CallbackQuery):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    # Удаляем напоминания из планировщика
    reminders = await database.get_medication_reminders(med_id)
    for r in reminders:
        scheduler.remove_reminder_from_scheduler(r['id'])
        
    # Помечаем лекарство как неактивное
    await database.delete_medication(med_id)
    
    await callback.answer("Лекарство удалено!")
    await callback.message.delete()
    await callback.message.answer(f"🗑️ Лекарство *{med['name']}* успешно удалено из аптечки.", parse_mode="Markdown")

# --- ДОБАВЛЕНИЕ ЛЕКАРСТВА ---

@router.message(StateFilter("*"), F.text == "➕ Добавить лекарство")
async def start_add_medication(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddMedication.waiting_for_input)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⌨️ Ввести вручную", callback_data="add_manual")]
    ])
    
    await message.answer(
        "➕ *Добавление нового лекарства*\n\n"
        "Вы можете прислать мне:\n"
        "1. 📸 *Фотографию упаковки* (я распознаю её с помощью ИИ).\n"
        "2. 💬 *Описание текстом в свободной форме* (например: _«Парацетамол по 1 таблетке 2 раза в день после еды в 08:00 и 20:00 на 5 дней»_).\n\n"
        "Или нажмите кнопку ниже для ручного ввода:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "add_manual", StateFilter(AddMedication.waiting_for_input))
async def process_add_manual(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddMedication.waiting_for_name)
    await callback.message.answer("Введите название лекарства (например, Аспирин):", reply_markup=ReplyKeyboardRemove())
    await callback.message.delete()

@router.callback_query(StateFilter(AddMedication.waiting_for_input), F.data.startswith("add_manual_prefilled:"))
async def process_add_manual_prefilled(callback: CallbackQuery, state: FSMContext):
    name = callback.data.split(":", 1)[1]
    
    await state.set_state(AddMedication.waiting_for_dosage)
    await state.update_data(name=name, active_ingredient=None)
    
    processing_dosage = await callback.message.answer("🔍 *Мистер Таблетус подбирает варианты дозировок...* 🤖", parse_mode="Markdown")
    dosages = await gemini_service.suggest_dosage(name)
    await processing_dosage.delete()
    
    keyboard_buttons = []
    for d in dosages:
        keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.answer(
        f"Введите дозировку для *{name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
        f"_(Или выберите один из вариантов ниже)_",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.message.delete()


# --- Ввод текстом (NLP) ---
@router.message(StateFilter(AddMedication.waiting_for_input), F.text)
async def process_text_schedule(message: Message, state: FSMContext):
    processing_msg = await message.answer("🔍 *Мистер Таблетус анализирует ваш текст...* 🤖", parse_mode="Markdown")
    
    parsed_data = await gemini_service.parse_text_schedule(message.text)
    await processing_msg.delete()
    
    if not parsed_data or not parsed_data.get("name"):
        # Попробуем найти известное лекарство по словам
        words = message.text.strip().split()
        detected_name = None
        for word in words:
            # Убираем знаки препинания
            word_clean = re.sub(r"[^\w\-]", "", word).strip().lower()
            if not word_clean:
                continue
            # Быстрая проверка по БД (название из словаря)
            is_val = await gemini_service.validate_medicine_name(word_clean)
            if is_val:
                detected_name = word_clean.capitalize()
                break
                
        if not detected_name and len(words) <= 2:
            # Если слов мало, возьмем весь текст
            detected_name = message.text.strip().capitalize()
            
        if detected_name:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"⌨️ Настроить {detected_name} вручную", 
                        callback_data=f"add_manual_prefilled:{detected_name}"
                    )
                ],
                [
                    InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")
                ]
            ])
            await message.answer(
                f"🤖 *Мистер Таблетус:* «Я распознал название препарата **{detected_name}**, "
                f"но не смог автоматически определить расписание (ИИ временно перегружен).\n\n"
                f"Желаете настроить график для этого лекарства по шагам вручную?»",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return

        # Fallback if nothing was found at all
        await message.answer(
            "😔 К сожалению, мне не удалось распознать расписание. Попробуйте написать по-другому "
            "(например: _«Нурофен 2 раза в день в 9:00 и 21:00»_) или введите данные вручную:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⌨️ Ввести вручную", callback_data="add_manual")]
            ])
        )
        return


    # Валидация распознанного названия лекарства через Gemini
    processing_validation = await message.answer("🔍 *Проверяю распознанное название...* 🤖", parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(parsed_data["name"])
    await processing_validation.delete()
    
    if not is_valid:
        await message.answer(
            f"😔 Кажется, в тексте указано некорректное название лекарства (распознано как *«{parsed_data['name']}»*).\n"
            "Пожалуйста, попробуйте написать по-другому (например: _«Нурофен 2 раза в день в 9:00 и 21:00»_) или введите данные вручную:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⌨️ Ввести вручную", callback_data="add_manual")]
            ]),
            parse_mode="Markdown"
        )
        return


    # Изображение по умолчанию
    parsed_data["image_path"] = None

    # Сохраняем распарсенные данные во временное хранилище FSM
    await state.update_data(parsed_data=parsed_data)
    await state.set_state(AddMedication.confirming_parsed)
    
    relation_ru = {
        'before_meal': 'до еды 🍽️',
        'with_meal': 'во время еды 🍽️',
        'after_meal': 'после еды 🍽️',
        'none': 'без связи с едой'
    }.get(parsed_data.get("food_relation"), 'без связи с едой')
    
    times_str = ", ".join(parsed_data.get("times", []))
    
    active_ing_ru = f" ({parsed_data['active_ingredient']})" if parsed_data.get('active_ingredient') else ""
    confirm_text = (
        f"🤖 *Я распознал следующие данные:*\n\n"
        f"💊 Название: **{parsed_data['name']}**{active_ing_ru}\n"
        f"⚖️ Дозировка: **{parsed_data.get('dosage') or '1 шт.'}**\n"
        f"🍽️ Прием: **{relation_ru}**\n"
        f"⏰ Время приемов: **{times_str}**\n"
        f"📅 Расписание: **Ежедневно**\n"
        f"📦 Остаток в аптечке: **{parsed_data.get('stock_count') or 20} шт.**\n\n"
        f"Всё верно?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, всё верно", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Нет, ввести заново", callback_data="confirm_no")
        ]
    ])
    
    image_path = parsed_data.get("image_path")
    if not image_path or not os.path.exists(image_path):
        image_path = "photos/default_pill.png"
        
    if os.path.exists(image_path):
        from aiogram.types import FSInputFile
        await message.answer_photo(
            photo=FSInputFile(image_path),
            caption=confirm_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(confirm_text, reply_markup=keyboard, parse_mode="Markdown")



# --- Ввод фото (Vision OCR) ---
@router.message(StateFilter(AddMedication.waiting_for_input), F.photo)
async def process_photo_medication(message: Message, state: FSMContext, bot: Bot):
    processing_msg = await message.answer("🔍 *Мистер Таблетус сканирует упаковку...* 📸", parse_mode="Markdown")
    
    # Загружаем фото
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    # Создаем уникальный путь для файла
    os.makedirs("photos", exist_ok=True)
    file_ext = file_info.file_path.split(".")[-1]
    local_path = f"photos/{uuid.uuid4()}.{file_ext}"
    
    await bot.download_file(file_info.file_path, local_path)
    
    # Распознаем фото через Gemini Vision
    parsed_data = await gemini_service.parse_medicine_photo(local_path)
    await processing_msg.delete()
    
    if not parsed_data or not parsed_data.get("name"):
        await message.answer(
            "😔 Мне не удалось четко распознать коробку лекарства. Пожалуйста, сфотографируйте "
            "крупнее лицевую сторону или введите данные вручную:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⌨️ Ввести вручную", callback_data="add_manual")]
            ])
        )
        # Удаляем локальный файл
        if os.path.exists(local_path):
            os.remove(local_path)
        return
        
    # Валидация названия лекарства с фото через Gemini
    processing_validation = await message.answer("🔍 *Проверяю распознанное с фото название...* 🤖", parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(parsed_data["name"])
    await processing_validation.delete()
    
    if not is_valid:
        await message.answer(
            f"😔 Мне показалось, что на фото изображено *«{parsed_data['name']}»*, но это не похоже на настоящее лекарство или БАД.\n"
            "Пожалуйста, сфотографируйте коробку крупнее с лицевой стороны или введите данные вручную:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⌨️ Ввести вручную", callback_data="add_manual")]
            ]),
            parse_mode="Markdown"
        )
        if os.path.exists(local_path):
            os.remove(local_path)
        return

        
    # Сохраняем путь к картинке и распознанные данные в FSM
    parsed_data["image_path"] = local_path
    await state.update_data(photo_data=parsed_data)
    await state.set_state(AddMedication.waiting_for_schedule_after_photo)
    
    await message.answer(
        f"🤖 *Я распознал упаковку лекарства:*\n\n"
        f"💊 Название: **{parsed_data['name']}**\n"
        f"⚖️ Дозировка: **{parsed_data.get('dosage') or 'не определена'}**\n"
        f"📦 Остаток (в пачке): **{parsed_data.get('quantity') or 20} шт.**\n\n"
        f"✍️ Напишите текстом, как часто его нужно принимать (например: _«3 раза в день во время еды в 10:00, 14:00 и 20:00»_):",
        parse_mode="Markdown"
    )

@router.message(StateFilter(AddMedication.waiting_for_schedule_after_photo), F.text)
async def process_schedule_after_photo(message: Message, state: FSMContext):
    state_data = await state.get_data()
    photo_data = state_data.get("photo_data")
    
    processing_msg = await message.answer("🔍 *Мистер Таблетус анализирует график...* 🤖", parse_mode="Markdown")
    parsed_schedule = await gemini_service.parse_text_schedule(message.text)
    await processing_msg.delete()
    
    if not parsed_schedule:
        await message.answer("Не удалось распознать график. Напишите еще раз (например: _«каждый день в 09:00»_):")
        return
        
    # Объединяем данные из фото и текстового графика
    merged_data = {
        "name": photo_data["name"],
        "dosage": photo_data.get("dosage") or parsed_schedule.get("dosage") or "1 шт.",
        "food_relation": parsed_schedule.get("food_relation") or "none",
        "times": parsed_schedule.get("times") or ["09:00"],
        "schedule_type": parsed_schedule.get("schedule_type") or "daily",
        "schedule_data": parsed_schedule.get("schedule_data"),
        "stock_count": photo_data.get("quantity") or parsed_schedule.get("stock_count") or 20,
        "image_path": photo_data.get("image_path")
    }
    
    await state.update_data(parsed_data=merged_data)
    await state.set_state(AddMedication.confirming_parsed)
    
    relation_ru = {
        'before_meal': 'до еды 🍽️',
        'with_meal': 'во время еды 🍽️',
        'after_meal': 'после еды 🍽️',
        'none': 'без связи с едой'
    }.get(merged_data["food_relation"], 'без связи с едой')
    
    times_str = ", ".join(merged_data["times"])
    
    active_ing_ru = f" ({merged_data['active_ingredient']})" if merged_data.get('active_ingredient') else ""
    confirm_text = (
        f"🤖 *Проверьте итоговую карточку:*\n\n"
        f"💊 Название: **{merged_data['name']}**{active_ing_ru}\n"
        f"⚖️ Дозировка: **{merged_data['dosage']}**\n"
        f"🍽️ Прием: **{relation_ru}**\n"
        f"⏰ Время приемов: **{times_str}**\n"
        f"📅 Расписание: **Ежедневно**\n"
        f"📦 Остаток в аптечке: **{merged_data['stock_count']} шт.**\n\n"
        f"Всё верно?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, всё верно", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Нет, ввести заново", callback_data="confirm_no")
        ]
    ])
    
    image_path = merged_data.get("image_path")
    if not image_path or not os.path.exists(image_path):
        image_path = "photos/default_pill.png"
        
    if os.path.exists(image_path):
        from aiogram.types import FSInputFile
        await message.answer_photo(
            photo=FSInputFile(image_path),
            caption=confirm_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(confirm_text, reply_markup=keyboard, parse_mode="Markdown")


# --- Подтверждение автозаполнения ---

@router.callback_query(StateFilter(AddMedication.confirming_parsed), F.data == "confirm_yes")
async def process_confirm_yes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    data = state_data.get("parsed_data")
    
    # 1. Сохраняем в Базу Данных
    med_id = await database.add_medication(
        user_id=callback.from_user.id,
        name=data["name"],
        active_ingredient=data.get("active_ingredient"),
        dosage=data["dosage"],
        food_relation=data["food_relation"],
        stock_count=data.get("stock_count") or 20,
        stock_alert_threshold=5,
        image_path=data.get("image_path")
    )
    
    # 2. Добавляем напоминания в планировщик
    for time_str in data["times"]:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type=data.get("schedule_type") or "daily",
            schedule_data=data.get("schedule_data")
        )
        
    # Перезагружаем задачи в планировщике
    await scheduler.setup_scheduler(bot)
    
    await callback.message.delete()
    
    success_text = f"🎉 Лекарство *{data['name']}* успешно добавлено в вашу аптечку!\n\n"
    await callback.message.answer(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await state.clear()
    
    # Отправляем рекомендации асинхронно в фоне
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(medicine_name)
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации от Мистера Таблетуса для {medicine_name}:*\n{recommendations}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, callback.from_user.id, data["name"]))


@router.callback_query(StateFilter(AddMedication.confirming_parsed), F.data == "confirm_no")
async def process_confirm_no(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    data = state_data.get("parsed_data", {})
    # Удаляем фото, если оно было сохранено локально
    if data.get("image_path") and os.path.exists(data["image_path"]):
        os.remove(data["image_path"])
        
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Добавление отменено. Вы можете начать заново, нажав кнопку в меню.", reply_markup=get_main_menu_keyboard())

# --- ПОШАГОВЫЙ РУЧНОЙ ВВОД ---

@router.message(StateFilter(AddMedication.waiting_for_name))
async def process_manual_name(message: Message, state: FSMContext):
    raw_name = message.text.strip()
    match = re.match(r"([^(]+)\s*(?:\(([^)]+)\))?", raw_name)
    if match:
        name = match.group(1).strip()
        active_ingredient = match.group(2).strip() if match.group(2) else None
    else:
        name = raw_name
        active_ingredient = None
        
    # Валидация названия через Gemini
    processing_msg = await message.answer("🔍 *Мистер Таблетус проверяет название...* 🤖", parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(name)
    await processing_msg.delete()
    
    if not is_valid:
        await message.answer(
            "⚠️ *Мистер Таблетус:* «Похоже, это не название лекарства, витамина или БАДа. "
            "Пожалуйста, проверьте написание и введите корректное название (например, _Аспирин_ или _Парацетамол_):»",
            parse_mode="Markdown"
        )
        return
        
    await state.update_data(name=name, active_ingredient=active_ingredient)
    await state.set_state(AddMedication.waiting_for_dosage)
    
    # Запрос дозировки с рекомендациями от Gemini
    processing_dosage = await message.answer("🔍 *Мистер Таблетус подбирает варианты дозировок...* 🤖", parse_mode="Markdown")
    dosages = await gemini_service.suggest_dosage(name)
    await processing_dosage.delete()
    
    keyboard_buttons = []
    for d in dosages:
        keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer(
        f"Введите дозировку для *{name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
        f"_(Или выберите один из вариантов ниже)_",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )



@router.message(StateFilter(AddMedication.waiting_for_dosage))
async def process_manual_dosage(message: Message, state: FSMContext):
    await state.update_data(dosage=message.text)
    await state.set_state(AddMedication.waiting_for_food)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍽️ До еды", callback_data="food:before_meal"),
            InlineKeyboardButton(text="🥣 Во время еды", callback_data="food:with_meal")
        ],
        [
            InlineKeyboardButton(text="🍰 После еды", callback_data="food:after_meal"),
            InlineKeyboardButton(text="🤷 Без связи с едой", callback_data="food:none")
        ]
    ])
    await message.answer("Как принимать по отношению к еде?", reply_markup=keyboard)

@router.callback_query(StateFilter(AddMedication.waiting_for_dosage), F.data.startswith("dosage_suggest:"))
async def process_dosage_suggest_callback(callback: CallbackQuery, state: FSMContext):
    dosage = callback.data.split(":", 1)[1]
    await state.update_data(dosage=dosage)
    await state.set_state(AddMedication.waiting_for_food)
    
    await callback.message.delete()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍽️ До еды", callback_data="food:before_meal"),
            InlineKeyboardButton(text="🥣 Во время еды", callback_data="food:with_meal")
        ],
        [
            InlineKeyboardButton(text="🍰 После еды", callback_data="food:after_meal"),
            InlineKeyboardButton(text="🤷 Без связи с едой", callback_data="food:none")
        ]
    ])
    await callback.message.answer(
        f"Вы выбрали дозировку: *{dosage}*\n\nКак принимать по отношению к еде?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )



@router.callback_query(StateFilter(AddMedication.waiting_for_food), F.data.startswith("food:"))
async def process_manual_food(callback: CallbackQuery, state: FSMContext):
    food_relation = callback.data.split(":")[1]
    await state.update_data(food_relation=food_relation)
    await state.set_state(AddMedication.waiting_for_times)
    
    await callback.message.edit_text(
        "Укажите время приемов через запятую или пробел в формате ЧЧ:ММ (например: *09:00, 21:00*):",
        parse_mode="Markdown"
    )

@router.message(StateFilter(AddMedication.waiting_for_times))
async def process_manual_times(message: Message, state: FSMContext):
    # Разбираем время
    raw_times = message.text.replace(",", " ").split()
    times = []
    
    for t in raw_times:
        t = t.strip()
        try:
            # Валидация формата времени
            datetime.strptime(t, "%H:%M")
            times.append(t)
        except ValueError:
            await message.answer(f"❌ Некорректный формат времени: `{t}`. Введите время в формате ЧЧ:ММ (например, 08:30):", parse_mode="Markdown")
            return
            
    if not times:
        await message.answer("Пожалуйста, введите хотя бы одно время (например, 14:00):")
        return
        
    await state.update_data(times=times)
    await state.set_state(AddMedication.waiting_for_stock)
    await message.answer("Сколько таблеток/доз сейчас в аптечке (введите число, например, 30):")

@router.message(StateFilter(AddMedication.waiting_for_stock))
async def process_manual_stock(message: Message, state: FSMContext, bot: Bot):
    try:
        stock = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 20):")
        return
        
    state_data = await state.get_data()
    
    # Изображение по умолчанию
    image_path = None
        
    # Формируем итоговые данные для сохранения
    med_id = await database.add_medication(
        user_id=message.from_user.id,
        name=state_data["name"],
        active_ingredient=state_data.get("active_ingredient"),
        dosage=state_data["dosage"],
        food_relation=state_data["food_relation"],
        stock_count=stock,
        stock_alert_threshold=5,
        image_path=image_path
    )

    
    for time_str in state_data["times"]:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type='daily'
        )
        
    # Настраиваем планировщик
    await scheduler.setup_scheduler(bot)
    
    success_text = f"🎉 Лекарство *{state_data['name']}* успешно добавлено в аптечку!\n\n"
    await message.answer(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await state.clear()
    
    # Отправляем рекомендации асинхронно в фоне
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(medicine_name)
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации от Мистера Таблетуса для {medicine_name}:*\n{recommendations}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, state_data["name"]))


# --- ОБРАБОТКА ДЕЙСТВИЙ ИЗ УВЕДОМЛЕНИЙ (ПРИНЯЛ / ПРОПУСТИЛ) ---

@router.callback_query(F.data.startswith("take:"))
async def process_take_pill(callback: CallbackQuery, bot: Bot):
    # take:med_id:expected_time_iso
    parts = callback.data.split(":")
    med_id = int(parts[1])
    expected_time_iso = ":".join(parts[2:])
    
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    # Проверяем историю, чтобы не кликали дважды
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history == 'taken':
        await callback.answer("Прием уже подтвержден!")
        return
        
    # 1. Обновляем статус в истории
    await database.update_history_status(med_id, expected_time_iso, 'taken', datetime.now().isoformat())
        
    # 2. Уменьшаем запас на 1 дозу
    await database.update_medication_stock(med_id, -1)
    updated_med = await database.get_medication(med_id)
    
    # 3. Награждаем маскота (+5 здоровья, +10 XP)
    status = await database.update_user_tamagotchi(callback.from_user.id, health_delta=5, xp_delta=10)
    
    # Текст фидбека от маскота
    mascot_msg = f"❤️ Моё здоровье: {status['health']}% (+5%) | ⭐ Уровень: {status['level']}" if status else ""
    if status and status.get("level_up"):
        mascot_msg += "\n🎉 **LEVEL UP!** Мистер Таблетус повысил свой уровень!"
        
    stock_warning = ""
    if updated_med and updated_med['stock_count'] <= updated_med['stock_alert_threshold']:
        stock_warning = f"\n⚠️ *Внимание:* в аптечке осталось всего {updated_med['stock_count']} шт.!"
        
    feedback_text = (
        f"✅ *Принято в {datetime.now().strftime('%H:%M')}!*\n\n"
        f"💊 Препарат: *{med['name']}*\n"
        f"🤖 *Мистер Таблетус:* «Спасибо! Будьте здоровы! {mascot_msg}»"
        f"{stock_warning}"
    )
    
    # Редактируем сообщение, убирая кнопки и заменяя текст
    if callback.message.photo:
        await callback.message.edit_caption(caption=feedback_text, reply_markup=None, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=feedback_text, reply_markup=None, parse_mode="Markdown")
        
    await callback.answer("Прием подтвержден!")

@router.callback_query(F.data.startswith("skip:"))
async def process_skip_pill(callback: CallbackQuery):
    parts = callback.data.split(":")
    med_id = int(parts[1])
    expected_time_iso = ":".join(parts[2:])
    
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    # Проверяем историю
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history in ['taken', 'skipped']:
        await callback.answer("Прием уже обработан!")
        return
        
    # 1. Записываем пропуск
    await database.update_history_status(med_id, expected_time_iso, 'skipped', datetime.now().isoformat())
        
    # 2. Штрафуем маскота (-15 здоровья)
    status = await database.update_user_tamagotchi(callback.from_user.id, health_delta=-15, xp_delta=0)
    mascot_msg = f"💔 Моё здоровье: {status['health']}% (-15%)" if status else ""
    
    feedback_text = (
        f"❌ *Прием пропущен!*\n\n"
        f"💊 Препарат: *{med['name']}*\n"
        f"🤖 *Мистер Таблетус:* «Эх... Постарайтесь больше не забывать. Мне больно! {mascot_msg}»"
    )
    
    if callback.message.photo:
        await callback.message.edit_caption(caption=feedback_text, reply_markup=None, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=feedback_text, reply_markup=None, parse_mode="Markdown")
        
    await callback.answer("Прием пропущен.")

@router.callback_query(F.data.startswith("snooze:"))
async def process_snooze_pill(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    med_id = int(parts[1])
    expected_time_iso = ":".join(parts[2:])
    
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    # Изменяем сообщение
    snoozed_text = (
        f"⏰ *Напоминание отложено на 15 минут!*\n\n"
        f"💊 Препарат: *{med['name']}*\n"
        f"🤖 *Мистер Таблетус:* «Хорошо, я вернусь к вам через 15 минут. Не забудьте!»"
    )
    
    if callback.message.photo:
        await callback.message.edit_caption(caption=snoozed_text, reply_markup=None, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=snoozed_text, reply_markup=None, parse_mode="Markdown")
        
    # Запускаем отложенный вызов в планировщике на +15 минут
    run_time = datetime.now() + timedelta(minutes=15)
    
    # Генерируем новый reminder_id для планировщика
    job_id = f"snooze_{med_id}_{int(run_time.timestamp())}"
    
    # Задача отправки пуша
    scheduler.scheduler.add_job(
        scheduler.send_reminder_job,
        'date',
        run_date=run_time,
        id=job_id,
        args=[bot, callback.from_user.id, 0, med_id, datetime.now().strftime("%H:%M")]
    )
    
    await callback.answer("Отложено на 15 минут!")
