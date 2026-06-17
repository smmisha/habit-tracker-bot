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

class EditMedication(StatesGroup):
    waiting_for_active_ingredient = State()
    waiting_for_photo = State()
    waiting_for_link = State()


# --- СПИСОК ЛЕКАРСТВ ---

@router.message(StateFilter("*"), F.text == "💊 Мои лекарства")
async def list_medications(message: Message, state: FSMContext = None):
    if state:
        await state.clear()
        
    # Получаем все лекарства с их напоминаниями за один запрос!
    rows = await database.get_user_medications_with_reminders(message.from_user.id)
    if not rows:
        await message.answer(
            "📭 Ваша аптечка пуста. Нажмите *➕ Добавить лекарство*, чтобы внести первое средство.",
            parse_mode="Markdown"
        )
        return

    # Группируем напоминания по лекарствам
    meds_dict = {}
    for r in rows:
        med_id = r['med_id']
        if med_id not in meds_dict:
            meds_dict[med_id] = {
                'id': med_id,
                'name': r['med_name'],
                'active_ingredient': r['active_ingredient'],
                'dosage': r['dosage'],
                'food_relation': r['food_relation'],
                'stock_count': r['stock_count'],
                'stock_alert_threshold': r['stock_alert_threshold'],
                'image_path': r['image_path'],
                'times': []
            }
        if r['time_str']:
            meds_dict[med_id]['times'].append(r['time_str'])

    # Формируем одно единое сообщение для всей аптечки
    text = "📋 *Ваша active аптечка:*\n\n"
    keyboard_buttons = []
    
    for idx, (med_id, med) in enumerate(meds_dict.items(), 1):
        relation_text = {
            'before_meal': 'до еды 🍽️',
            'with_meal': 'во время еды 🍽️',
            'after_meal': 'после еды 🍽️',
            'none': 'без связи с едой'
        }.get(med['food_relation'], 'нет данных')
        
        times_list = ", ".join(sorted(med['times'])) if med['times'] else "не задано"
        active_ing = f" ({med['active_ingredient']})" if med['active_ingredient'] else ""
        
        text += (
            f"{idx}. *{med['name']}*{active_ing}\n"
            f"   ⚖️ Дозировка: {med['dosage'] or 'не указана'}\n"
            f"   🍽️ Прием: {relation_text}\n"
            f"   ⏰ Время: {times_list}\n"
            f"   📦 Остаток: {med['stock_count']} шт. (порог: {med['stock_alert_threshold']})\n\n"
        )
        
        # Добавляем кнопку удаления для каждого лекарства в общий список
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"🗑️ Удалить {med['name']}", callback_data=f"del_med:{med['id']}")
        ])
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


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

@router.callback_query(F.data == "add_manual")
async def process_add_manual(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddMedication.waiting_for_name)
    await callback.message.answer("Введите название лекарства (например, Аспирин):", reply_markup=ReplyKeyboardRemove())
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(StateFilter(AddMedication.waiting_for_input), F.data.startswith("add_manual_prefilled:"))
async def process_add_manual_prefilled(callback: CallbackQuery, state: FSMContext):
    name = callback.data.split(":", 1)[1]
    
    await state.set_state(AddMedication.waiting_for_dosage)
    await state.update_data(name=name, active_ingredient=None)
    
    # Отправляем сообщение-запрос дозировки моментально
    prompt_msg = await callback.message.answer(
        f"Введите дозировку для *{name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
        f"_(Загружаю варианты дозировок... если хотите, введите вручную прямо сейчас)_",
        parse_mode="Markdown"
    )
    await callback.message.delete()
    
    # Запуск фонового подбора дозировок через Gemini
    async def load_dosages_bg(msg_to_edit: Message, med_name: str):
        try:
            dosages = await gemini_service.suggest_dosage(med_name)
            keyboard_buttons = []
            for d in dosages:
                keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await msg_to_edit.edit_text(
                f"Введите дозировку для *{med_name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
                f"_(Или выберите один из вариантов ниже)_",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка фоновой загрузки дозировок: {e}")
            try:
                await msg_to_edit.edit_text(
                    f"Введите дозировку для *{med_name}* (например: 1 таблетка, 500 мг, 10 мл):",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
                
    asyncio.create_task(load_dosages_bg(prompt_msg, name))


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
    
    # Запускаем фоновый анализ и отправку рекомендаций
    asyncio.create_task(run_background_classification_and_rec(bot, callback.from_user.id, med_id, data["name"]))


@router.callback_query(F.data == "confirm_no")
async def process_confirm_no(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    
    # Удаляем фото из parsed_data, если оно было сохранено локально
    data = state_data.get("parsed_data", {})
    if data and data.get("image_path") and os.path.exists(data["image_path"]):
        try:
            os.remove(data["image_path"])
        except Exception:
            pass
            
    # Удаляем фото из photo_data, если оно было сохранено локально
    photo_data = state_data.get("photo_data", {})
    if photo_data and photo_data.get("image_path") and os.path.exists(photo_data["image_path"]):
        try:
            os.remove(photo_data["image_path"])
        except Exception:
            pass
        
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Добавление отменено. Вы можете начать заново, нажав кнопку в меню.", reply_markup=get_main_menu_keyboard())
    await callback.answer("Добавление отменено")


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
        
    # Валидация названия (теперь быстрая, Wiki-поиск в фоне)
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
    
    # Отправляем сообщение-запрос дозировки моментально
    prompt_msg = await message.answer(
        f"Введите дозировку для *{name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
        f"_(Загружаю варианты дозировок... если хотите, введите вручную прямо сейчас)_",
        parse_mode="Markdown"
    )
    
    # Запуск фонового подбора дозировок через Gemini
    async def load_dosages_bg(msg_to_edit: Message, med_name: str):
        try:
            dosages = await gemini_service.suggest_dosage(med_name)
            keyboard_buttons = []
            for d in dosages:
                keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await msg_to_edit.edit_text(
                f"Введите дозировку для *{med_name}* (например: 1 таблетка, 500 мг, 10 мл):\n"
                f"_(Или выберите один из вариантов ниже)_",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка фоновой загрузки дозировок: {e}")
            try:
                await msg_to_edit.edit_text(
                    f"Введите дозировку для *{med_name}* (например: 1 таблетка, 500 мг, 10 мл):",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
                
    asyncio.create_task(load_dosages_bg(prompt_msg, name))



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
    
    # Запускаем фоновый анализ и отправку рекомендаций
    asyncio.create_task(run_background_classification_and_rec(bot, message.from_user.id, med_id, state_data["name"]))


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


# --- ФОНОВАЯ КЛАССИФИКАЦИЯ И РЕКОМЕНДАЦИИ ИИ ---

async def run_background_classification_and_rec(bot: Bot, chat_id: int, med_id: int, medicine_name: str):
    try:
        # 1. Классифицируем название препарата через Gemini
        classification = await gemini_service.classify_medicine_name(medicine_name)
        category = classification.get("category", "real")
        
        if category == "real":
            # Реальное лекарство -> запрашиваем и отправляем рекомендации
            recommendations = await gemini_service.get_medicine_recommendations(medicine_name)
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации от Мистера Таблетуса для {medicine_name}:*\n{recommendations}",
                    parse_mode="Markdown"
                )
        elif category == "plausible":
            # Вымышленное/редкое название -> предлагаем ввести действующее вещество, отправить фото или скинуть ссылку
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🧪 Указать вещество", callback_data=f"set_active_ing:{med_id}"),
                    InlineKeyboardButton(text="📸 Прислать фото", callback_data=f"set_active_photo:{med_id}")
                ],
                [
                    InlineKeyboardButton(text="🔗 Скинуть ссылку", callback_data=f"set_active_link:{med_id}")
                ]
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ *Мистер Таблетус:* «Я не нашел препарат **{medicine_name}** в медицинских справочниках.\n\n"
                     f"Если это настоящее лекарство (например, новое или редкое), пожалуйста, предоставьте дополнительную информацию (укажите действующее вещество, пришлите фото упаковки или ссылку на описание), чтобы я мог подобрать рекомендации.»",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else: # nonsense (какашка, бред, стол и т.д.)
            # Сначала получим напоминания, чтобы удалить их из планировщика в памяти
            reminders = await database.get_medication_reminders(med_id)
            for r in reminders:
                scheduler.remove_reminder_from_scheduler(r['id'])
                
            # Помечаем лекарство как неактивное в БД
            await database.delete_medication(med_id)
            
            # Перезагружаем задачи в планировщике
            await scheduler.setup_scheduler(bot)
            
            # Заведомо нелекарственное слово -> сообщаем об удалении и предлагаем ввести заново
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить лекарство заново", callback_data="add_manual")]
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ *Мистер Таблетус:* «Препарата с названием **{medicine_name}** не существует в медицинских справочниках.\n\n"
                     f"Я удалил эту запись из вашей аптечки. Пожалуйста, введите корректное название лекарства заново.»",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Ошибка фонового анализа лекарства {medicine_name}: {e}")


@router.callback_query(F.data.startswith("set_active_ing:"))
async def process_set_active_ing_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_active_ingredient)
    await state.update_data(edit_med_id=med_id)
    
    await callback.message.answer(
        f"Введите действующее вещество для лекарства *{med['name']}* (например: _Ибупрофен_):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(StateFilter(EditMedication.waiting_for_active_ingredient))
async def process_input_active_ingredient(message: Message, state: FSMContext, bot: Bot):
    active_ingredient = message.text.strip()
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    med = await database.get_medication(med_id)
    if not med:
        await message.answer("Ошибка: лекарство не найдено в базе данных.", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
        
    # Обновляем действующее вещество в базе данных
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    await message.answer(
        f"✅ Действующее вещество для *{med['name']}* успешно обновлено на **{active_ingredient}**!",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    
    # Заново запускаем отправку рекомендаций в фоне
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})")
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации от Мистера Таблетуса для {medicine_name} ({ingredient}):*\n{recommendations}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient))


@router.callback_query(F.data.startswith("set_active_photo:"))
async def process_set_active_photo_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_photo)
    await state.update_data(edit_med_id=med_id)
    
    await callback.message.answer(
        f"📸 Пожалуйста, пришлите фотографию упаковки лекарства *{med['name']}* (я попробую распознать действующее вещество с помощью ИИ):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_active_link:"))
async def process_set_active_link_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_link)
    await state.update_data(edit_med_id=med_id)
    
    await callback.message.answer(
        f"🔗 Пожалуйста, отправьте ссылку на веб-страницу с описанием лекарства *{med['name']}* (я прочитаю её и извлеку действующее вещество):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(StateFilter(EditMedication.waiting_for_photo), F.photo)
async def process_input_active_photo(message: Message, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    med = await database.get_medication(med_id)
    if not med:
        await message.answer("Ошибка: лекарство не найдено в базе данных.", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
        
    processing_msg = await message.answer("🔍 *Мистер Таблетус анализирует фото упаковки...* 📸", parse_mode="Markdown")
    
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        
        os.makedirs("photos", exist_ok=True)
        file_ext = file_info.file_path.split(".")[-1]
        local_path = f"photos/{uuid.uuid4()}.{file_ext}"
        
        await bot.download_file(file_info.file_path, local_path)
        
        parsed_data = await gemini_service.parse_medicine_photo(local_path)
        
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        parsed_data = None
        
    await processing_msg.delete()
    
    active_ingredient = parsed_data.get("active_ingredient") if parsed_data else None
    if not active_ingredient:
        await message.answer(
            "😔 Мне не удалось распознать действующее вещество на этой фотографии.\n"
            "Пожалуйста, пришлите другое фото упаковки, введите вещество текстом или отправьте ссылку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Ввести текстом", callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text="🔗 Скинуть ссылку", callback_data=f"set_active_link:{med_id}")]
            ])
        )
        return
        
    # Обновляем МНН в БД
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    await message.answer(
        f"✅ Действующее вещество для *{med['name']}* успешно распознано как **{active_ingredient}** и обновлено!",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    
    # Рекомендации
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})")
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации для {medicine_name} ({ingredient}):*\n{recommendations}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient))


@router.message(StateFilter(EditMedication.waiting_for_photo))
async def process_input_active_photo_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    await message.answer(
        "⚠️ Пожалуйста, пришлите именно фотографию упаковки лекарства или выберите другой способ ввода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Ввести текстом", callback_data=f"set_active_ing:{med_id}")],
            [InlineKeyboardButton(text="🔗 Скинуть ссылку", callback_data=f"set_active_link:{med_id}")]
        ])
    )


@router.message(StateFilter(EditMedication.waiting_for_link), F.text)
async def process_input_active_link(message: Message, state: FSMContext, bot: Bot):
    url = message.text.strip()
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer(
            "❌ Неверный формат ссылки. Ссылка должна начинаться с `http://` или `https://`.\n"
            "Пожалуйста, отправьте корректную ссылку или выберите другой способ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Ввести вещество", callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text="📸 Прислать фото", callback_data=f"set_active_photo:{med_id}")]
            ])
        )
        return
        
    med = await database.get_medication(med_id)
    if not med:
        await message.answer("Ошибка: лекарство не найдено в базе данных.", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
        
    processing_msg = await message.answer("🔍 *Мистер Таблетус анализирует веб-страницу...* 🌐", parse_mode="Markdown")
    
    active_ingredient = await gemini_service.extract_active_ingredient_from_url(url, med["name"])
    await processing_msg.delete()
    
    if not active_ingredient:
        await message.answer(
            "😔 Мне не удалось найти действующее вещество по этой ссылке.\n"
            "Пожалуйста, отправьте другую ссылку, введите действующее вещество текстом или пришлите фото упаковки:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧪 Ввести вещество", callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text="📸 Прислать фото", callback_data=f"set_active_photo:{med_id}")]
            ])
        )
        return
        
    # Обновляем МНН в БД
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    await message.answer(
        f"✅ На основе веб-страницы действующее вещество для *{med['name']}* определено как **{active_ingredient}** и обновлено!",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    
    # Рекомендации
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})")
            if recommendations:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 *Рекомендации для {medicine_name} ({ingredient}):*\n{recommendations}",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient))


@router.message(StateFilter(EditMedication.waiting_for_link))
async def process_input_active_link_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    await message.answer(
        "⚠️ Пожалуйста, отправьте ссылку в виде текста или выберите другой способ ввода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Ввести вещество", callback_data=f"set_active_ing:{med_id}")],
            [InlineKeyboardButton(text="📸 Прислать фото", callback_data=f"set_active_photo:{med_id}")]
        ])
    )


# --- Обработчик свободного ввода названия лекарства (быстрый старт добавления) ---
@router.message(StateFilter(None), F.text)
async def process_direct_medicine_name(message: Message, state: FSMContext):
    text = message.text.strip()
    
    # Игнорируем команды и кнопки меню
    if text.startswith("/"):
        return
        
    menu_buttons = [
        "💊 Мои лекарства",
        "➕ Добавить лекарство",
        "🤖 Мистер Таблетус (Тамагочи)",
        "👥 Мои Бадди",
        "⚙️ Сменить часовой пояс"
    ]
    if text in menu_buttons:
        return
        
    detected_name = text.capitalize()
    
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
        f"🤖 *Мистер Таблетус:* «Я заметил, что вы ввели название **{detected_name}**.\n\n"
        f"Желаете настроить расписание приема для этого лекарства по шагам?»",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )



