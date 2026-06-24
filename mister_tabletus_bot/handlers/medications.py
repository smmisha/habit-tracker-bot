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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

import database
import scheduler
from utils import gemini_service
from handlers.start import get_main_menu_keyboard
from utils.locales import _T

logger = logging.getLogger(__name__)
router = Router()

async def save_wizard_msg(state: FSMContext, msg_id: int):
    if not state:
        return
    try:
        data = await state.get_data()
        msg_ids = data.get("wizard_msg_ids", [])
        if msg_id not in msg_ids:
            msg_ids = list(msg_ids)
            msg_ids.append(msg_id)
            await state.update_data(wizard_msg_ids=msg_ids)
    except Exception as e:
        logger.error(f"Error saving wizard message ID: {e}")

async def delete_wizard_msgs(bot: Bot, chat_id: int, state: FSMContext):
    if not state:
        return
    try:
        data = await state.get_data()
        msg_ids = data.get("wizard_msg_ids", [])
        for msg_id in msg_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        await state.update_data(wizard_msg_ids=[])
    except Exception as e:
        logger.error(f"Error deleting wizard messages: {e}")

async def complete_wizard(message: Message, state: FSMContext, bot: Bot):
    await delete_wizard_msgs(bot, message.chat.id, state)
    try:
        await message.delete()
    except Exception:
        pass

async def download_searched_image(url: str) -> str:
    """Скачивает изображение по ссылке во временный файл и возвращает путь к нему"""
    import urllib.request
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
    waiting_for_duration = State()      # Ручной ввод: длительность курса


class EditMedication(StatesGroup):
    waiting_for_active_ingredient = State()
    waiting_for_photo = State()
    waiting_for_link = State()


class EditMedDetails(StatesGroup):
    waiting_for_field_selection = State()
    waiting_for_new_value = State()
    waiting_for_times = State()


def get_cancel_keyboard(lang: str = "ru"):
    """Возвращает reply клавиатуру с кнопкой отмены"""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=_T("btn_cancel", lang))]
    ], resize_keyboard=True)





# --- СПИСОК ЛЕКАРСТВ ---

@router.message(StateFilter("*"), lambda m: m.text in [_T("menu_my_meds", "ru"), _T("menu_my_meds", "en"), _T("menu_my_meds", "uk")] if m.text else False)
async def list_medications(message: Message, state: FSMContext = None, user_id: int = None):
    new_msg_ids = []
    u_id = user_id or message.from_user.id
    old_ids = await database.get_user_cabinet_msg_ids(u_id)
    for old_id in old_ids:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=old_id)
        except Exception:
            pass
    
    # Add user's trigger message to cleanup list
    new_msg_ids.append(message.message_id)

    if user_id is None:
        user_id = message.from_user.id
        
    user = await database.get_user(user_id)
    lang = user.get("language") if user else "ru"
    
    # Получаем все лекарства с их напоминаниями за один запрос
    rows = await database.get_user_medications_with_reminders(user_id)
    if not rows:
        empty_msg = await message.answer(
            _T("cabinet_empty", lang),
            parse_mode="Markdown"
        )
        new_msg_ids.append(empty_msg.message_id)
        await database.update_user_cabinet_msg_ids(user_id or message.from_user.id, new_msg_ids)
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
                'start_date': r['start_date'],
                'end_date': r['end_date'],
                'times': []
            }
        if r['time_str']:
            meds_dict[med_id]['times'].append(r['time_str'])

    # Отправляем заголовок
    header_msg = await message.answer(
        _T("active_cabinet", lang),
        parse_mode="Markdown"
    )
    new_msg_ids.append(header_msg.message_id)
    
    user_record = await database.get_user(message.from_user.id)
    
    for idx, (med_id, med) in enumerate(meds_dict.items(), 1):
        med_text, keyboard = await get_medication_card_data(med, idx, user_record, lang)
        card_msg = await message.answer(
            med_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        new_msg_ids.append(card_msg.message_id)

    await database.update_user_cabinet_msg_ids(user_id or message.from_user.id, new_msg_ids)


async def get_medication_card_data(med: dict, idx: int, user: dict, lang: str):
    relation_keys = {
        'before_meal': 'food_before',
        'with_meal': 'food_with',
        'after_meal': 'food_after',
        'none': 'food_none'
    }
    rel_key = relation_keys.get(med['food_relation'], 'food_none')
    relation_text = _T(rel_key, lang)
    for emoji in ["🥣", "🍽️", "🍽", "🍰", "🤷"]:
        relation_text = relation_text.replace(emoji, "")
    relation_text = relation_text.strip()
    
    # reminders/times
    reminders = await database.get_medication_reminders(med['id'])
    times_list = ", ".join(sorted([r['time_str'] for r in reminders])) if reminders else ("не задано" if lang == "ru" else "not set" if lang == "en" else "не задано")
    active_ing = f" ({med['active_ingredient']})" if med['active_ingredient'] else ""
    
    if med['start_date'] and med['end_date']:
        course_lbl = "Срок курса" if lang == "ru" else "Course duration" if lang == "en" else "Термін курсу"
        course_info = f"\n📅 {course_lbl}: с {med['start_date']} по {med['end_date']}"
    else:
        perm_text = _T('btn_permanent', lang)
        for emoji in ["🤷", "📅", "📆"]:
            perm_text = perm_text.replace(emoji, "")
        perm_text = perm_text.strip()
        course_info = f"\n📅 {perm_text}"
        
    dosage_lbl = "Дозировка" if lang == "ru" else "Dosage" if lang == "en" else "Дозування"
    intake_lbl = "Прием" if lang == "ru" else "Intake" if lang == "en" else "Прийом"
    time_lbl = "Время" if lang == "ru" else "Time" if lang == "en" else "Час"
    stock_lbl = "Остаток" if lang == "ru" else "Stock" if lang == "en" else "Залишок"
    pcs_lbl = "шт." if lang == "ru" else "pcs." if lang == "en" else "шт."
    threshold_lbl = "порог" if lang == "ru" else "threshold" if lang == "en" else "поріг"
    
    med_text = (
        f"{idx}. *{med['name']}*{active_ing}\n"
        f"⚖️ {dosage_lbl}: {med['dosage'] or ('не указана' if lang == 'ru' else 'not specified' if lang == 'en' else 'не вказана')}\n"
        f"🍽️ {intake_lbl}: {relation_text}\n"
        f"⏰ {time_lbl}: {times_list}\n"
        f"📦 {stock_lbl}: {med['stock_count']} {pcs_lbl} ({threshold_lbl}: {med['stock_alert_threshold']}){course_info}"
    )
    
    # Check if has untaken reminder today
    has_untaken = False
    try:
        user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        now_local = datetime.now(user_tz)
        for r in reminders:
            hour, minute = map(int, r['time_str'].split(':'))
            naive_dt = datetime.combine(now_local.date(), datetime.min.time()).replace(
                hour=hour, minute=minute
            )
            if hasattr(user_tz, 'localize'):
                expected_dt = user_tz.localize(naive_dt)
            else:
                expected_dt = naive_dt.replace(tzinfo=user_tz)
            # check status
            status = await database.get_history_status(med['id'], expected_dt.isoformat())
            if status not in ['taken', 'taken_late']:
                has_untaken = True
                break
    except Exception:
        pass
        
    buttons = [
        InlineKeyboardButton(text="✏️", callback_data=f"edit_med:{med['id']}"),
        InlineKeyboardButton(text="🗑️", callback_data=f"del_med:{med['id']}"),
        InlineKeyboardButton(text="💊", callback_data=f"take_med_cabinet:{med['id']}")
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    return med_text, keyboard


@router.callback_query(F.data.startswith("del_med:"))
async def process_delete_medication(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await callback.answer(err_msg)
        return
        
    # Удаляем напоминания из планировщика
    reminders = await database.get_medication_reminders(med_id)
    for r in reminders:
        scheduler.remove_reminder_from_scheduler(r['id'])
        
    # Помечаем лекарство как неактивное
    await database.delete_medication(med_id)
    
    del_ok = "Лекарство удалено!" if lang == "ru" else "Medication deleted!" if lang == "en" else "Препарат видалено!"
    await callback.answer(del_ok)
    await callback.message.delete()
    sent_msg = await callback.message.answer(_T("del_success", lang, name=med['name']), parse_mode="Markdown")
    
    # Update cabinet_msg_ids in database
    msg_ids = await database.get_user_cabinet_msg_ids(callback.from_user.id)
    if callback.message.message_id in msg_ids:
        try:
            msg_ids.remove(callback.message.message_id)
        except ValueError:
            pass
    msg_ids.append(sent_msg.message_id)
    await database.update_user_cabinet_msg_ids(callback.from_user.id, msg_ids)

@router.callback_query(F.data.startswith("edit_med:"))
async def process_edit_medication(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await callback.answer(err_msg)
        return
        
    await state.set_state(EditMedDetails.waiting_for_field_selection)
    await state.update_data(edit_med_id=med_id)
    
    prompt_text = (
        f"📝 *Что вы хотите изменить в лекарстве {med['name']}?*\n\n"
        f"Выберите поле для изменения:"
    ) if lang == "ru" else (
        f"📝 *What do you want to change in {med['name']}?*\n\n"
        f"Select a field to modify:"
    ) if lang == "en" else (
        f"📝 *Що ви хочете змінити в ліках {med['name']}?*\n\n"
        f"Оберіть поле для зміни:"
    )
    
    btn_dosage = "⚖️ Дозировка" if lang == "ru" else "⚖️ Dosage" if lang == "en" else "⚖️ Дозування"
    btn_food = "🍽️ Прием" if lang == "ru" else "🍽️ Intake" if lang == "en" else "🍽️ Прийом"
    btn_time = "⏰ Время приемов" if lang == "ru" else "⏰ Intake times" if lang == "en" else "⏰ Час прийомів"
    btn_stock = "📦 Остаток" if lang == "ru" else "📦 Stock" if lang == "en" else "📦 Залишок"
    btn_duration = "📅 Срок курса" if lang == "ru" else "📅 Course duration" if lang == "en" else "📅 Термін курсу"
    btn_cancel = "❌ Отмена" if lang == "ru" else "❌ Cancel" if lang == "en" else "❌ Скасувати"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=btn_dosage, callback_data=f"edit_sel:dosage:{med_id}"),
            InlineKeyboardButton(text=btn_food, callback_data=f"edit_sel:food:{med_id}")
        ],
        [
            InlineKeyboardButton(text=btn_time, callback_data=f"edit_sel:times:{med_id}"),
            InlineKeyboardButton(text=btn_stock, callback_data=f"edit_sel:stock:{med_id}")
        ],
        [
            InlineKeyboardButton(text=btn_duration, callback_data=f"edit_sel:duration:{med_id}")
        ],
        [
            InlineKeyboardButton(text=btn_cancel, callback_data="edit_cancel")
        ]
    ])
    
    await callback.message.edit_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "edit_cancel")
async def process_edit_cancel(callback: CallbackQuery, state: FSMContext):
    # Delete saved wizard messages
    state_data = await state.get_data()
    msg_ids = state_data.get("wizard_msg_ids", [])
    for msg_id in msg_ids:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except Exception:
            pass
            
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await list_medications(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_sel:"))
async def process_edit_field_selection(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    field = parts[1]
    med_id = int(parts[2])
    
    med = await database.get_medication(med_id)
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await callback.answer(err_msg)
        return
        
    await state.update_data(edit_med_id=med_id, edit_field=field)
    
    if field == "dosage":
        await state.set_state(EditMedDetails.waiting_for_new_value)
        prompt = (
            f"⚖️ *Редактирование дозировки для {med['name']}*\n\n"
            f"Текущая дозировка: `{med['dosage'] or 'не указана'}`\n\n"
            f"Введите новую дозировку (например, _1 таблетка_ или _50 мг_):"
        ) if lang == "ru" else (
            f"⚖️ *Editing dosage for {med['name']}*\n\n"
            f"Current dosage: `{med['dosage'] or 'not set'}`\n\n"
            f"Enter new dosage (e.g., _1 tablet_ or _50 mg_):"
        ) if lang == "en" else (
            f"⚖️ *Редагування дозування для {med['name']}*\n\n"
            f"Поточне дозування: `{med['dosage'] or 'не вказано'}`\n\n"
            f"Введіть нове дозування (наприклад, _1 таблетка_ або _50 мг_):"
        )
        
        await callback.message.delete()
        prompt_msg = await callback.message.answer(prompt, reply_markup=get_cancel_keyboard(lang), parse_mode="Markdown")
        await save_wizard_msg(state, prompt_msg.message_id)
        await callback.answer()
        
    elif field == "stock":
        await state.set_state(EditMedDetails.waiting_for_new_value)
        prompt = (
            f"📦 *Редактирование остатка для {med['name']}*\n\n"
            f"Текущий остаток: `{med['stock_count']} шт.`\n\n"
            f"Введите новое количество упаковок/таблеток в аптечке (целое число):"
        ) if lang == "ru" else (
            f"📦 *Editing stock for {med['name']}*\n\n"
            f"Current stock: `{med['stock_count']} pcs.`\n\n"
            f"Enter the new count of doses/pills in your cabinet (whole number):"
        ) if lang == "en" else (
            f"📦 *Редагування залишку для {med['name']}*\n\n"
            f"Поточний залишок: `{med['stock_count']} шт.`\n\n"
            f"Введіть нову кількість доз/таблеток в аптечці (ціле число):"
        )
        await callback.message.delete()
        prompt_msg = await callback.message.answer(prompt, reply_markup=get_cancel_keyboard(lang), parse_mode="Markdown")
        await save_wizard_msg(state, prompt_msg.message_id)
        await callback.answer()
        
    elif field == "times":
        await state.set_state(EditMedDetails.waiting_for_new_value)
        reminders = await database.get_medication_reminders(med_id)
        current_times = ", ".join(sorted([r['time_str'] for r in reminders])) if reminders else "не задано"
        
        prompt = (
            f"⏰ *Редактирование времени приемов для {med['name']}*\n\n"
            f"Текущее время приемов: `{current_times}`\n\n"
            f"Введите новое время приемов через запятую или пробел в формате ЧЧ:ММ (например: _08:00, 20:00_):"
        ) if lang == "ru" else (
            f"⏰ *Editing intake times for {med['name']}*\n\n"
            f"Current times: `{current_times}`\n\n"
            f"Enter new intake times separated by commas or spaces in HH:MM format (e.g., _08:00, 20:00_):"
        ) if lang == "en" else (
            f"⏰ *Редагування часу прийомів для {med['name']}*\n\n"
            f"Поточний час прийомів: `{current_times}`\n\n"
            f"Введіть новий час прийомів через кому або пробіл у форматі ГГ:ХХ (наприклад: _08:00, 20:00_):"
        )
        await callback.message.delete()
        prompt_msg = await callback.message.answer(prompt, reply_markup=get_cancel_keyboard(lang), parse_mode="Markdown")
        await save_wizard_msg(state, prompt_msg.message_id)
        await callback.answer()
        
    elif field == "food":
        prompt = (
            f"🍽️ *Редактирование отношения к еде для {med['name']}*\n\n"
            f"Выберите новый вариант приема:"
        ) if lang == "ru" else (
            f"🍽️ *Editing relation to meals for {med['name']}*\n\n"
            f"Select a new intake option:"
        ) if lang == "en" else (
            f"🍽️ *Редагування відношення до їжі для {med['name']}*\n\n"
            f"Оберіть новий варіант прийому:"
        )
        
        btn_before = _T("food_before", lang)
        btn_with = _T("food_with", lang)
        btn_after = _T("food_after", lang)
        btn_none = _T("food_none", lang)
        btn_cancel = "❌ Отмена" if lang == "ru" else "❌ Cancel" if lang == "en" else "❌ Скасувати"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=btn_before, callback_data=f"edit_val:food:before_meal:{med_id}"),
                InlineKeyboardButton(text=btn_with, callback_data=f"edit_val:food:with_meal:{med_id}")
            ],
            [
                InlineKeyboardButton(text=btn_after, callback_data=f"edit_val:food:after_meal:{med_id}"),
                InlineKeyboardButton(text=btn_none, callback_data=f"edit_val:food:none:{med_id}")
            ],
            [
                InlineKeyboardButton(text=btn_cancel, callback_data="edit_cancel")
            ]
        ])
        await callback.message.edit_text(prompt, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()
        
    elif field == "duration":
        prompt = (
            f"📅 *Редактирование длительности курса для {med['name']}*\n\n"
            f"Выберите тип курса:"
        ) if lang == "ru" else (
            f"📅 *Editing course duration for {med['name']}*\n\n"
            f"Select course type:"
        ) if lang == "en" else (
            f"📅 *Редагування тривалості курсу для {med['name']}*\n\n"
            f"Оберіть тип курсу:"
        )
        
        btn_permanent = _T("btn_permanent", lang)
        btn_custom = "✏️ Задать количество дней" if lang == "ru" else "✏️ Set number of days" if lang == "en" else "✏️ Вказати кількість днів"
        btn_cancel = "❌ Отмена" if lang == "ru" else "❌ Cancel" if lang == "en" else "❌ Скасувати"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=btn_permanent, callback_data=f"edit_val:duration:permanent:{med_id}")
            ],
            [
                InlineKeyboardButton(text=btn_custom, callback_data=f"edit_val:duration:custom:{med_id}")
            ],
            [
                InlineKeyboardButton(text=btn_cancel, callback_data="edit_cancel")
            ]
        ])
        await callback.message.edit_text(prompt, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data.startswith("edit_val:"))
async def process_edit_value_inline(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split(":")
    field = parts[1]
    value = parts[2]
    med_id = int(parts[3])
    
    med = await database.get_medication(med_id)
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await callback.answer(err_msg)
        return
        
    if field == "food":
        await state.update_data(edit_med_id=med_id, edit_food_relation=value)
        await state.set_state(EditMedDetails.waiting_for_times)
        
        prompt = (
            f"🍽️ *Способ приема выбран.* Теперь укажите количество приемов в день и время для лекарства *{med['name']}*.\n\n"
            f"Выберите вариант ниже или введите время в формате ЧЧ:ММ через пробел/запятую (например, _08:00, 20:00_):"
        ) if lang == "ru" else (
            f"🍽️ *Intake option selected.* Now specify the number of intakes per day and their times for *{med['name']}*.\n\n"
            f"Select an option below or enter times in HH:MM format separated by space/comma (e.g., _08:00, 20:00_):"
        ) if lang == "en" else (
            f"🍽️ *Спосіб прийому обрано.* Тепер вкажіть кількість прийомів на день та час для ліків *{med['name']}*.\n\n"
            f"Оберіть варіант нижче або введіть час у форматі ГГ:ХХ через пробіл/кому (наприклад, _08:00, 20:00_):"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("preset_1_day", lang), callback_data="edit_times_preset:09:00")],
            [InlineKeyboardButton(text=_T("preset_2_day", lang), callback_data="edit_times_preset:09:00,21:00")],
            [InlineKeyboardButton(text=_T("preset_3_day", lang), callback_data="edit_times_preset:08:00,14:00,20:00")],
            [InlineKeyboardButton(text="❌ Отмена" if lang == "ru" else "❌ Cancel" if lang == "en" else "❌ Скасувати", callback_data="edit_cancel")]
        ])
        
        await save_wizard_msg(state, callback.message.message_id)
        await callback.message.edit_text(prompt, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()
        
    elif field == "duration":
        if value == "permanent":
            user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
            now_local = datetime.now(user_tz)
            start_date_str = now_local.strftime("%Y-%m-%d")
            end_date_str = None
            
            await database.update_medication_duration(med_id, start_date_str, end_date_str)
            await scheduler.setup_scheduler(bot)
            
            success = (
                f"✅ Курс приема лекарства *{med['name']}* изменен на бессрочный!"
            ) if lang == "ru" else (
                f"✅ Course for *{med['name']}* has been successfully updated to permanent!"
            ) if lang == "en" else (
                f"✅ Курс прийому ліків *{med['name']}* змінено на безстроковий!"
            )
            
            await delete_wizard_msgs(bot, callback.message.chat.id, state)
            await state.clear()
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
            await callback.answer()
            
        elif value == "custom":
            await state.update_data(edit_med_id=med_id, edit_field="duration_days")
            await state.set_state(EditMedDetails.waiting_for_new_value)
            
            prompt = (
                f"📅 *Редактирование длительности курса для {med['name']}*\n\n"
                f"Укажите количество дней приема (целое число, например, `7` или `30`) или введите конечную дату в формате **ГГГГ-ММ-ДД** (например, `2026-06-25`):"
            ) if lang == "ru" else (
                f"📅 *Editing course duration for {med['name']}*\n\n"
                f"Enter the number of days of intake (whole number, e.g., `7` or `30`) or enter the end date in **YYYY-MM-DD** format (e.g., `2026-06-25`):"
            ) if lang == "en" else (
                f"📅 *Редагування тривалості курсу для {med['name']}*\n\n"
                f"Вкажіть кількість днів прийому (ціле число, наприклад, `7` або `30`) або введіть кінцеву дату у форматі **РРРР-ММ-ДД** (наприклад, `2026-06-25`):"
            )
            
            await callback.message.delete()
            prompt_msg = await callback.message.answer(prompt, reply_markup=get_cancel_keyboard(lang), parse_mode="Markdown")
            await save_wizard_msg(state, prompt_msg.message_id)
            await callback.answer()


@router.message(StateFilter(EditMedDetails.waiting_for_new_value))
async def process_edit_value_input(message: Message, state: FSMContext, bot: Bot):
    await save_wizard_msg(state, message.message_id)
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    field = state_data.get("edit_field")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Ошибка: лекарство не найдено в базе данных." if lang == "ru" else "Error: medication not found in database." if lang == "en" else "Помилка: препарат не знайдено в базі даних."
        sent_err = await message.answer(err_msg, reply_markup=get_main_menu_keyboard(lang))
        await save_wizard_msg(state, sent_err.message_id)
        await state.clear()
        return
        
    text = message.text.strip()
    
    if field == "dosage":
        if not text:
            sent_err = await message.answer("Пожалуйста, введите корректное значение:" if lang == "ru" else "Please enter a valid value:" if lang == "en" else "Будь ласка, введіть коректне значення:")
            await save_wizard_msg(state, sent_err.message_id)
            return
            
        await database.update_medication_dosage(med_id, text)
        
        success = (
            f"✅ Дозировка лекарства *{med['name']}* успешно обновлена на: **{text}**"
        ) if lang == "ru" else (
            f"✅ Dosage for *{med['name']}* has been successfully updated to: **{text}**"
        ) if lang == "en" else (
            f"✅ Дозування препарату *{med['name']}* успішно оновлено на: **{text}**"
        )
        
        await message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
        await complete_wizard(message, state, bot)
        await state.clear()
        
    elif field == "stock":
        try:
            stock = int(text)
            if stock < 0:
                raise ValueError()
        except ValueError:
            sent_err = await message.answer(_T("invalid_number", lang))
            await save_wizard_msg(state, sent_err.message_id)
            return
            
        await database.set_medication_stock(med_id, stock)
        
        success = (
            f"✅ Остаток лекарства *{med['name']}* успешно изменен на: **{stock} шт.**"
        ) if lang == "ru" else (
            f"✅ Stock count for *{med['name']}* has been successfully updated to: **{stock} pcs.**"
        ) if lang == "en" else (
            f"✅ Залишок ліків *{med['name']}* успішно змінено на: **{stock} шт.**"
        )
        
        await message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
        await complete_wizard(message, state, bot)
        await state.clear()
        
    elif field == "times":
        times = re.split(r"[,\s;]+", text)
        cleaned_times = []
        time_regex = re.compile(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
        
        for t in times:
            t = t.strip()
            if not t:
                continue
            if not time_regex.match(t):
                parts = t.split(":")
                if len(parts) == 2:
                    try:
                        h = int(parts[0])
                        m = int(parts[1])
                        if 0 <= h < 24 and 0 <= m < 60:
                            t = f"{h:02d}:{m:02d}"
                    except ValueError:
                        pass
            
            if time_regex.match(t):
                cleaned_times.append(t)
            else:
                sent_err = await message.answer(_T("invalid_time", lang, time=t))
                await save_wizard_msg(state, sent_err.message_id)
                return
                
        if not cleaned_times:
            sent_err = await message.answer(
                "Время не распознано. Введите время в формате ЧЧ:ММ через пробел:" if lang == "ru"
                else "No times recognized. Enter times in HH:MM format separated by space:" if lang == "en"
                else "Час не розпізнано. Введіть час у форматі ГГ:ХХ через пробіл:"
            )
            await save_wizard_msg(state, sent_err.message_id)
            return
            
        await database.delete_medication_reminders(med_id)
        for time_str in cleaned_times:
            await database.add_reminder(
                medication_id=med_id,
                time_str=time_str,
                schedule_type='daily'
            )
            
        await scheduler.setup_scheduler(bot)
        
        success = (
            f"✅ Время приемов для *{med['name']}* успешно обновлено на: **{', '.join(cleaned_times)}**"
        ) if lang == "ru" else (
            f"✅ Intake times for *{med['name']}* have been successfully updated to: **{', '.join(cleaned_times)}**"
        ) if lang == "en" else (
            f"✅ Час прийомів для *{med['name']}* успішно оновлено на: **{', '.join(cleaned_times)}**"
        )
        
        await message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
        await complete_wizard(message, state, bot)
        await state.clear()
        
    elif field == "duration_days":
        user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        now_local = datetime.now(user_tz)
        start_date_str = now_local.strftime("%Y-%m-%d")
        end_date_str = None
        
        try:
            days = int(text)
            if days <= 0:
                raise ValueError()
            end_date = now_local.date() + timedelta(days=days - 1)
            end_date_str = end_date.strftime("%Y-%m-%d")
        except ValueError:
            try:
                parsed_date = datetime.strptime(text, "%Y-%m-%d").date()
                if parsed_date < now_local.date():
                    past_err = ("❌ Дата окончания не может быть в прошлом. Введите корректную дату:" if lang == "ru"
                                else "❌ End date cannot be in the past. Enter a valid date:" if lang == "en"
                                else "❌ Дата закінчення не може бути в минулому. Введіть коректну дату:")
                    sent_err = await message.answer(past_err)
                    await save_wizard_msg(state, sent_err.message_id)
                    return
                end_date_str = parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                sent_err = await message.answer(
                    _T("invalid_duration", lang),
                    parse_mode="Markdown"
                )
                await save_wizard_msg(state, sent_err.message_id)
                return
                
        await database.update_medication_duration(med_id, start_date_str, end_date_str)
        await scheduler.setup_scheduler(bot)
        
        success = (
            f"✅ Курс приема лекарства *{med['name']}* успешно обновлен!\nПериод: с {start_date_str} по {end_date_str or 'бессрочно'}"
        ) if lang == "ru" else (
            f"✅ Course for *{med['name']}* has been successfully updated!\nPeriod: from {start_date_str} to {end_date_str or 'permanent'}"
        ) if lang == "en" else (
            f"✅ Курс прийому ліків *{med['name']}* успішно оновлено!\nПеріод: з {start_date_str} по {end_date_str or 'безстроково'}"
        )
        
        await message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
        await complete_wizard(message, state, bot)
        await state.clear()


@router.callback_query(StateFilter(EditMedDetails.waiting_for_times), F.data.startswith("edit_times_preset:"))
async def process_edit_times_preset(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    preset_data = callback.data.split(":", 1)[1]
    times = [t.strip() for t in preset_data.split(",")]
    
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    food_relation = state_data.get("edit_food_relation")
    
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await callback.answer(err_msg)
        await state.clear()
        return
        
    await database.update_medication_food_relation(med_id, food_relation)
    await database.delete_medication_reminders(med_id)
    for time_str in times:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type='daily'
        )
        
    await scheduler.setup_scheduler(bot)
    
    relation_keys = {
        'before_meal': 'food_before',
        'with_meal': 'food_with',
        'after_meal': 'food_after',
        'none': 'food_none'
    }
    rel_key = relation_keys.get(food_relation, 'food_none')
    rel_localized = _T(rel_key, lang)
    
    success = (
        f"✅ Настройки приема для лекарства *{med['name']}* успешно обновлены!\n"
        f"🍽️ Способ приема: **{rel_localized}**\n"
        f"⏰ Время приемов: **{', '.join(times)}**"
    ) if lang == "ru" else (
        f"✅ Intake settings for *{med['name']}* have been successfully updated!\n"
        f"🍽️ Intake option: **{rel_localized}**\n"
        f"⏰ Intake times: **{', '.join(times)}**"
    ) if lang == "en" else (
        f"✅ Налаштування прийому для ліків *{med['name']}* успішно оновлено!\n"
        f"🍽️ Спосіб прийому: **{rel_localized}**\n"
        f"⏰ Час прийомів: **{', '.join(times)}**"
    )
    
    await callback.message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
    await complete_wizard(callback.message, state, bot)
    await state.clear()
    await callback.answer()


@router.message(StateFilter(EditMedDetails.waiting_for_times))
async def process_edit_manual_times(message: Message, state: FSMContext, bot: Bot):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    raw_times = re.split(r"[,\s;]+", message.text)
    times = []
    time_regex = re.compile(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    
    for t in raw_times:
        t = t.strip()
        if not t:
            continue
        if not time_regex.match(t):
            parts = t.split(":")
            if len(parts) == 2:
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if 0 <= h < 24 and 0 <= m < 60:
                        t = f"{h:02d}:{m:02d}"
                except ValueError:
                    pass
        
        if time_regex.match(t):
            times.append(t)
        else:
            err_msg = await message.answer(_T("invalid_time", lang, time=t), parse_mode="Markdown")
            await save_wizard_msg(state, err_msg.message_id)
            return
            
    if not times:
        err_msg = await message.answer(
            "Время не распознано. Введите время в формате ЧЧ:ММ через пробел:" if lang == "ru"
            else "No times recognized. Enter times in HH:MM format separated by space:" if lang == "en"
            else "Час не розпізнано. Введіть час у форматі ГГ:ХХ через пробіл:"
        )
        await save_wizard_msg(state, err_msg.message_id)
        return
        
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    food_relation = state_data.get("edit_food_relation")
    
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Лекарство не найдено!" if lang == "ru" else "Medication not found!" if lang == "en" else "Препарат не знайдено!"
        await message.answer(err_msg, reply_markup=get_main_menu_keyboard(lang))
        await state.clear()
        return
        
    await database.update_medication_food_relation(med_id, food_relation)
    await database.delete_medication_reminders(med_id)
    for time_str in times:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type='daily'
        )
        
    await scheduler.setup_scheduler(bot)
    
    relation_keys = {
        'before_meal': 'food_before',
        'with_meal': 'food_with',
        'after_meal': 'food_after',
        'none': 'food_none'
    }
    rel_key = relation_keys.get(food_relation, 'food_none')
    rel_localized = _T(rel_key, lang)
    
    success = (
        f"✅ Настройки приема для лекарства *{med['name']}* успешно обновлены!\n"
        f"🍽️ Способ приема: **{rel_localized}**\n"
        f"⏰ Время приемов: **{', '.join(times)}**"
    ) if lang == "ru" else (
        f"✅ Intake settings for *{med['name']}* have been successfully updated!\n"
        f"🍽️ Intake option: **{rel_localized}**\n"
        f"⏰ Intake times: **{', '.join(times)}**"
    ) if lang == "en" else (
        f"✅ Налаштування прийому для ліків *{med['name']}* успішно оновлено!\n"
        f"🍽️ Спосіб прийому: **{rel_localized}**\n"
        f"⏰ Час прийомів: **{', '.join(times)}**"
    )
    
    await message.answer(success, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
    await complete_wizard(message, state, bot)
    await state.clear()


# --- ДОБАВЛЕНИЕ ЛЕКАРСТВА ---

@router.message(StateFilter("*"), lambda m: m.text in [_T("menu_add_med", "ru"), _T("menu_add_med", "en"), _T("menu_add_med", "uk")] if m.text else False)
async def start_add_medication(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddMedication.waiting_for_input)
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_T("btn_enter_manual", lang), callback_data="add_manual")]
    ])
    
    sent_msg = await message.answer(
        _T("add_welcome", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, message.message_id)
    await save_wizard_msg(state, sent_msg.message_id)


@router.callback_query(F.data == "add_manual")
async def process_add_manual(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    msg_ids = state_data.get("wizard_msg_ids", [])
    
    await state.clear()
    await state.set_state(AddMedication.waiting_for_name)
    await state.update_data(wizard_msg_ids=msg_ids)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    sent_msg = await callback.message.answer(
        _T("prompt_name", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, sent_msg.message_id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(StateFilter(AddMedication.waiting_for_input), F.data.startswith("add_manual_prefilled:"))
async def process_add_manual_prefilled(callback: CallbackQuery, state: FSMContext):
    name = callback.data.split(":", 1)[1]
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    await state.set_state(AddMedication.waiting_for_dosage)
    await state.update_data(name=name, active_ingredient=None)
    
    prompt_msg = await callback.message.answer(
        _T("prompt_dosage", lang, name=name) + "\n" +
        ("_(Загружаю варианты дозировок... если хотите, введите вручную прямо сейчас)_" if lang == "ru" 
         else "_(Loading dosage options... feel free to enter manually right now)_" if lang == "en" 
         else "_(Завантажую варіанти дозування... якщо хочете, введіть вручну просто зараз)_"),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, prompt_msg.message_id)
    await callback.message.delete()
    
    # Запуск фонового подбора дозировок через Gemini
    async def load_dosages_bg(msg_to_edit: Message, med_name: str, user_lang: str):
        try:
            dosages = await gemini_service.suggest_dosage(med_name)
            keyboard_buttons = []
            for d in dosages:
                keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await msg_to_edit.edit_text(
                _T("prompt_dosage", user_lang, name=med_name) + "\n" +
                ("_(Или выберите один из вариантов ниже)_" if user_lang == "ru" 
                 else "_(Or select one of the options below)_" if user_lang == "en" 
                 else "_(Або оберіть один з варіантів нижче)_"),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка фоновой загрузки дозировок: {e}")
            try:
                await msg_to_edit.edit_text(
                    _T("prompt_dosage", user_lang, name=med_name),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
                
    asyncio.create_task(load_dosages_bg(prompt_msg, name, lang))


# --- Ввод текстом (NLP) ---
@router.message(StateFilter(AddMedication.waiting_for_input), F.text)
async def process_text_schedule(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    processing_msg = await message.answer(_T("analyzing_text", lang), parse_mode="Markdown")
    parsed_data = await gemini_service.parse_text_schedule(message.text)
    await processing_msg.delete()
    
    if not parsed_data or not parsed_data.get("name"):
        # Попробуем найти известное лекарство по словам
        words = message.text.strip().split()
        detected_name = None
        for word in words:
            word_clean = re.sub(r"[^\w\-]", "", word).strip().lower()
            if not word_clean:
                continue
            is_val = await gemini_service.validate_medicine_name(word_clean)
            if is_val:
                detected_name = word_clean.capitalize()
                break
                
        if not detected_name and len(words) <= 2:
            detected_name = message.text.strip().capitalize()
            
        if detected_name:
            btn_txt = _T("btn_direct_manual", lang, name=detected_name)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=btn_txt, callback_data=f"add_manual_prefilled:{detected_name}")],
                [InlineKeyboardButton(text=_T("btn_confirm_no", lang), callback_data="confirm_no")]
            ])
            
            sent_msg = await message.answer(
                _T("detected_name_only", lang, detected_name=detected_name),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await save_wizard_msg(state, sent_msg.message_id)
            return

        # Fallback
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_enter_manual", lang), callback_data="add_manual")]
        ])
        sent_msg = await message.answer(
            _T("invalid_schedule", lang),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, sent_msg.message_id)
        return

    # Валидация названия
    processing_validation = await message.answer(_T("verifying_name", lang), parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(parsed_data["name"])
    await processing_validation.delete()
    
    if not is_valid:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_enter_manual", lang), callback_data="add_manual")]
        ])
        sent_msg = await message.answer(
            _T("invalid_med_name", lang, name=parsed_data['name']),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, sent_msg.message_id)
        return

    parsed_data["image_path"] = None

    # Сохраняем распарсенные данные во временное хранилище FSM
    await state.update_data(parsed_data=parsed_data)
    await state.set_state(AddMedication.confirming_parsed)
    
    relation_keys = {
        'before_meal': 'food_before',
        'with_meal': 'food_with',
        'after_meal': 'food_after',
        'none': 'food_none'
    }
    rel_key = relation_keys.get(parsed_data.get("food_relation"), 'food_none')
    relation_localized = _T(rel_key, lang)
    
    times_str = ", ".join(parsed_data.get("times", []))
    active_ing_str = f" ({parsed_data['active_ingredient']})" if parsed_data.get('active_ingredient') else ""
    
    confirm_text = _T(
        "confirm_caption", 
        lang, 
        name=parsed_data['name'] + active_ing_str,
        dosage=parsed_data.get('dosage') or "1 шт.",
        relation=relation_localized,
        times=times_str,
        stock=parsed_data.get('stock_count') or 20
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("btn_confirm_yes", lang), callback_data="confirm_yes"),
            InlineKeyboardButton(text=_T("btn_confirm_no", lang), callback_data="confirm_no")
        ]
    ])
    
    image_path = parsed_data.get("image_path")
    if not image_path or not os.path.exists(image_path):
        image_path = "photos/default_pill.png"
        
    if os.path.exists(image_path):
        from aiogram.types import FSInputFile
        sent_msg = await message.answer_photo(
            photo=FSInputFile(image_path),
            caption=confirm_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, sent_msg.message_id)
    else:
        sent_msg = await message.answer(confirm_text, reply_markup=keyboard, parse_mode="Markdown")
        await save_wizard_msg(state, sent_msg.message_id)


# --- Ввод фото (Vision OCR) ---
@router.message(StateFilter(AddMedication.waiting_for_input), F.photo)
async def process_photo_medication(message: Message, state: FSMContext, bot: Bot):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    processing_msg = await message.answer(_T("scanning_photo", lang), parse_mode="Markdown")
    
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    os.makedirs("photos", exist_ok=True)
    file_ext = file_info.file_path.split(".")[-1]
    local_path = f"photos/{uuid.uuid4()}.{file_ext}"
    
    await bot.download_file(file_info.file_path, local_path)
    
    # Распознаем фото через Gemini Vision
    parsed_data = await gemini_service.parse_medicine_photo(local_path)
    await processing_msg.delete()
    
    if not parsed_data or not parsed_data.get("name"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_enter_manual", lang), callback_data="add_manual")]
        ])
        sent_err = await message.answer(
            _T("invalid_photo_box", lang),
            reply_markup=keyboard
        )
        await save_wizard_msg(state, sent_err.message_id)
        if os.path.exists(local_path):
            os.remove(local_path)
        return
        
    # Валидация названия
    processing_validation = await message.answer(_T("verifying_name", lang), parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(parsed_data["name"])
    await processing_validation.delete()
    
    if not is_valid:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_enter_manual", lang), callback_data="add_manual")]
        ])
        sent_err = await message.answer(
            _T("invalid_photo_med", lang, name=parsed_data['name']),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, sent_err.message_id)
        if os.path.exists(local_path):
            os.remove(local_path)
        return

    parsed_data["image_path"] = local_path
    await state.update_data(photo_data=parsed_data)
    await state.set_state(AddMedication.waiting_for_schedule_after_photo)
    
    sent_msg = await message.answer(
        _T(
            "photo_recognized_text",
            lang,
            name=parsed_data['name'],
            dosage=parsed_data.get("dosage") or ("не определена" if lang=="ru" else "not specified" if lang=="en" else "не визначена"),
            quantity=parsed_data.get("quantity") or 20
        ),
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, sent_msg.message_id)


@router.message(StateFilter(AddMedication.waiting_for_schedule_after_photo), F.text)
async def process_schedule_after_photo(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    state_data = await state.get_data()
    photo_data = state_data.get("photo_data")
    
    processing_msg = await message.answer(_T("analyzing_schedule", lang), parse_mode="Markdown")
    parsed_schedule = await gemini_service.parse_text_schedule(message.text)
    await processing_msg.delete()
    
    if not parsed_schedule:
        sent_err = await message.answer(_T("invalid_photo_schedule", lang))
        await save_wizard_msg(state, sent_err.message_id)
        return
        
    merged_data = {
        "name": photo_data["name"],
        "dosage": photo_data.get("dosage") or parsed_schedule.get("dosage") or "1 шт.",
        "food_relation": parsed_schedule.get("food_relation") or "none",
        "times": parsed_schedule.get("times") or ["09:00"],
        "schedule_type": parsed_schedule.get("schedule_type") or "daily",
        "schedule_data": parsed_schedule.get("schedule_data"),
        "duration_days": parsed_schedule.get("duration_days"),
        "stock_count": photo_data.get("quantity") or parsed_schedule.get("stock_count") or 20,
        "image_path": photo_data.get("image_path")
    }
    
    await state.update_data(parsed_data=merged_data)
    await state.set_state(AddMedication.confirming_parsed)
    
    relation_keys = {
        'before_meal': 'food_before',
        'with_meal': 'food_with',
        'after_meal': 'food_after',
        'none': 'food_none'
    }
    rel_key = relation_keys.get(merged_data["food_relation"], 'food_none')
    relation_localized = _T(rel_key, lang)
    
    times_str = ", ".join(merged_data["times"])
    active_ing_str = f" ({merged_data['active_ingredient']})" if merged_data.get('active_ingredient') else ""
    
    confirm_text = _T(
        "confirm_caption",
        lang,
        name=merged_data['name'] + active_ing_str,
        dosage=merged_data['dosage'],
        relation=relation_localized,
        times=times_str,
        stock=merged_data['stock_count']
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("btn_confirm_yes", lang), callback_data="confirm_yes"),
            InlineKeyboardButton(text=_T("btn_confirm_no", lang), callback_data="confirm_no")
        ]
    ])
    
    image_path = merged_data.get("image_path")
    if not image_path or not os.path.exists(image_path):
        image_path = "photos/default_pill.png"
        
    if os.path.exists(image_path):
        from aiogram.types import FSInputFile
        sent_msg = await message.answer_photo(
            photo=FSInputFile(image_path),
            caption=confirm_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, sent_msg.message_id)
    else:
        sent_msg = await message.answer(confirm_text, reply_markup=keyboard, parse_mode="Markdown")
        await save_wizard_msg(state, sent_msg.message_id)


# --- Подтверждение автозаполнения ---

@router.callback_query(StateFilter(AddMedication.confirming_parsed), F.data == "confirm_yes")
async def process_confirm_yes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    data = state_data.get("parsed_data")
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    
    start_date_str = now_local.strftime("%Y-%m-%d")
    end_date_str = None
    
    duration_days = data.get("duration_days")
    if duration_days:
        try:
            days = int(duration_days)
            end_date = now_local.date() + timedelta(days=days - 1)
            end_date_str = end_date.strftime("%Y-%m-%d")
        except Exception:
            pass

    # 1. Сохраняем в Базу Данных
    med_id = await database.add_medication(
        user_id=callback.from_user.id,
        name=data["name"],
        active_ingredient=data.get("active_ingredient"),
        dosage=data["dosage"],
        food_relation=data["food_relation"],
        stock_count=data.get("stock_count") or 20,
        stock_alert_threshold=5,
        image_path=data.get("image_path"),
        start_date=start_date_str,
        end_date=end_date_str
    )
    
    # 2. Добавляем напоминания в планировщик
    for time_str in data["times"]:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type=data.get("schedule_type") or "daily",
            schedule_data=data.get("schedule_data")
        )
        
    await scheduler.setup_scheduler(bot)
    await callback.message.delete()
    
    start_display = start_date_str
    end_display = end_date_str if end_date_str else _T("course_no_limit", lang)
    success_text = _T("add_success", lang, name=data["name"], start=start_display, end=end_display)
    
    await delete_wizard_msgs(bot, callback.message.chat.id, state)
    await callback.message.answer(success_text, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
    await state.clear()
    
    # Фоновый анализ рекомендаций
    asyncio.create_task(run_background_classification_and_rec(bot, callback.from_user.id, med_id, data["name"]))


@router.callback_query(F.data == "confirm_no")
async def process_confirm_no(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    # Очищаем временные файлы
    data = state_data.get("parsed_data", {})
    if data and data.get("image_path") and os.path.exists(data["image_path"]):
        try:
            os.remove(data["image_path"])
        except Exception:
            pass
            
    photo_data = state_data.get("photo_data", {})
    if photo_data and photo_data.get("image_path") and os.path.exists(photo_data["image_path"]):
        try:
            os.remove(photo_data["image_path"])
        except Exception:
            pass
        
    # Delete saved wizard messages
    await delete_wizard_msgs(callback.bot, callback.message.chat.id, state)
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(_T("cancel_msg", lang), reply_markup=get_main_menu_keyboard(lang))
    await callback.answer()


# --- ПОШАГОВЫЙ РУЧНОЙ ВВОД ---

@router.message(StateFilter(AddMedication.waiting_for_name))
async def process_manual_name(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    raw_name = message.text.strip()
    match = re.match(r"([^(]+)\s*(?:\(([^)]+)\))?", raw_name)
    if match:
        name = match.group(1).strip()
        active_ingredient = match.group(2).strip() if match.group(2) else None
    else:
        name = raw_name
        active_ingredient = None
        
    # Валидация названия
    processing_msg = await message.answer(_T("verifying_name", lang), parse_mode="Markdown")
    is_valid = await gemini_service.validate_medicine_name(name)
    await processing_msg.delete()
    
    if not is_valid:
        err_msg = await message.answer(
            _T("prompt_name_invalid", lang),
            parse_mode="Markdown"
        )
        await save_wizard_msg(state, err_msg.message_id)
        return
        
    await state.update_data(name=name, active_ingredient=active_ingredient)
    await state.set_state(AddMedication.waiting_for_dosage)
    
    prompt_msg = await message.answer(
        _T("prompt_dosage", lang, name=name) + "\n" +
        ("_(Загружаю варианты дозировок... если хотите, введите вручную прямо сейчас)_" if lang == "ru" 
         else "_(Loading dosage options... feel free to enter manually right now)_" if lang == "en" 
         else "_(Завантажую варіанти дозування... якщо хочете, введіть вручну просто зараз)_"),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, prompt_msg.message_id)
    
    # Фоновый подбор дозировок через Gemini
    async def load_dosages_bg(msg_to_edit: Message, med_name: str, user_lang: str):
        try:
            dosages = await gemini_service.suggest_dosage(med_name)
            keyboard_buttons = []
            for d in dosages:
                keyboard_buttons.append([InlineKeyboardButton(text=d, callback_data=f"dosage_suggest:{d}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await msg_to_edit.edit_text(
                _T("prompt_dosage", user_lang, name=med_name) + "\n" +
                ("_(Или выберите один из вариантов ниже)_" if user_lang == "ru" 
                 else "_(Or select one of the options below)_" if user_lang == "en" 
                 else "_(Або оберіть один з варіантів нижче)_"),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка фоновой загрузки дозировок: {e}")
            try:
                await msg_to_edit.edit_text(
                    _T("prompt_dosage", user_lang, name=med_name),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
                
    asyncio.create_task(load_dosages_bg(prompt_msg, name, lang))


@router.message(StateFilter(AddMedication.waiting_for_dosage))
async def process_manual_dosage(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    await state.update_data(dosage=message.text)
    await state.set_state(AddMedication.waiting_for_food)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("food_before", lang), callback_data="food:before_meal"),
            InlineKeyboardButton(text=_T("food_with", lang), callback_data="food:with_meal")
        ],
        [
            InlineKeyboardButton(text=_T("food_after", lang), callback_data="food:after_meal"),
            InlineKeyboardButton(text=_T("food_none", lang), callback_data="food:none")
        ]
    ])
    sent_msg = await message.answer(_T("food_relation_q", lang), reply_markup=keyboard)
    await save_wizard_msg(state, sent_msg.message_id)


@router.callback_query(StateFilter(AddMedication.waiting_for_dosage), F.data.startswith("dosage_suggest:"))
async def process_dosage_suggest_callback(callback: CallbackQuery, state: FSMContext):
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    dosage = callback.data.split(":", 1)[1]
    await state.update_data(dosage=dosage)
    await state.set_state(AddMedication.waiting_for_food)
    
    await callback.message.delete()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("food_before", lang), callback_data="food:before_meal"),
            InlineKeyboardButton(text=_T("food_with", lang), callback_data="food:with_meal")
        ],
        [
            InlineKeyboardButton(text=_T("food_after", lang), callback_data="food:after_meal"),
            InlineKeyboardButton(text=_T("food_none", lang), callback_data="food:none")
        ]
    ])
    
    title_text = f"Вы выбрали дозировку: *{dosage}*\n\n" if lang=="ru" else f"You selected dosage: *{dosage}*\n\n" if lang=="en" else f"Ви обрали дозування: *{dosage}*\n\n"
    sent_msg = await callback.message.answer(
        title_text + _T("food_relation_q", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, sent_msg.message_id)


@router.callback_query(StateFilter(AddMedication.waiting_for_food), F.data.startswith("food:"))
async def process_manual_food(callback: CallbackQuery, state: FSMContext):
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    food_relation = callback.data.split(":")[1]
    await state.update_data(food_relation=food_relation)
    await state.set_state(AddMedication.waiting_for_times)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_T("preset_1_day", lang), callback_data="times_preset:09:00")],
        [InlineKeyboardButton(text=_T("preset_2_day", lang), callback_data="times_preset:09:00,21:00")],
        [InlineKeyboardButton(text=_T("preset_3_day", lang), callback_data="times_preset:08:00,14:00,20:00")]
    ])
    
    await callback.message.edit_text(
        _T("prompt_times", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@router.callback_query(StateFilter(AddMedication.waiting_for_times), F.data.startswith("times_preset:"))
async def process_times_preset(callback: CallbackQuery, state: FSMContext):
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    preset_data = callback.data.split(":", 1)[1]
    times = [t.strip() for t in preset_data.split(",")]
    
    await state.update_data(times=times)
    await state.set_state(AddMedication.waiting_for_stock)
    
    await callback.message.edit_text(
        _T("prompt_stock", lang),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(StateFilter(AddMedication.waiting_for_times))
async def process_manual_times(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    raw_times = message.text.replace(",", " ").split()
    times = []
    
    for t in raw_times:
        t = t.strip()
        try:
            datetime.strptime(t, "%H:%M")
            times.append(t)
        except ValueError:
            err_msg = await message.answer(_T("invalid_time", lang, time=t), parse_mode="Markdown")
            await save_wizard_msg(state, err_msg.message_id)
            return
            
    if not times:
        err_msg = await message.answer(_T("prompt_times_empty", lang))
        await save_wizard_msg(state, err_msg.message_id)
        return
        
    await state.update_data(times=times)
    await state.set_state(AddMedication.waiting_for_stock)
    sent_msg = await message.answer(_T("prompt_stock", lang))
    await save_wizard_msg(state, sent_msg.message_id)


@router.message(StateFilter(AddMedication.waiting_for_stock))
async def process_manual_stock(message: Message, state: FSMContext):
    await save_wizard_msg(state, message.message_id)
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    try:
        stock = int(message.text)
    except ValueError:
        err_msg = await message.answer(_T("invalid_number", lang))
        await save_wizard_msg(state, err_msg.message_id)
        return
        
    await state.update_data(stock_count=stock)
    await state.set_state(AddMedication.waiting_for_duration)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_T("btn_permanent", lang), callback_data="duration_permanent")]
    ])
    
    sent_msg = await message.answer(
        _T("prompt_duration", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await save_wizard_msg(state, sent_msg.message_id)


@router.message(StateFilter(AddMedication.waiting_for_duration))
async def process_manual_duration(message: Message, state: FSMContext, bot: Bot):
    await save_wizard_msg(state, message.message_id)
    text = message.text.strip()
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    
    start_date_str = now_local.strftime("%Y-%m-%d")
    end_date_str = None
    
    # Проверка на количество дней
    try:
        days = int(text)
        if days <= 0:
            raise ValueError()
        end_date = now_local.date() + timedelta(days=days - 1)
        end_date_str = end_date.strftime("%Y-%m-%d")
    except ValueError:
        # Проверка на формат YYYY-MM-DD
        try:
            parsed_date = datetime.strptime(text, "%Y-%m-%d").date()
            if parsed_date < now_local.date():
                past_err = ("❌ Дата окончания не может быть в прошлом. Введите корректную дату:" if lang == "ru"
                            else "❌ End date cannot be in the past. Enter a valid date:" if lang == "en"
                            else "❌ Дата закінчення не може бути в минулому. Введіть коректну дату:")
                err_msg = await message.answer(past_err)
                await save_wizard_msg(state, err_msg.message_id)
                return
            end_date_str = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            err_msg = await message.answer(
                _T("invalid_duration", lang),
                parse_mode="Markdown"
            )
            await save_wizard_msg(state, err_msg.message_id)
            return

    state_data = await state.get_data()
    
    med_id = await database.add_medication(
        user_id=message.from_user.id,
        name=state_data["name"],
        active_ingredient=state_data.get("active_ingredient"),
        dosage=state_data["dosage"],
        food_relation=state_data["food_relation"],
        stock_count=state_data["stock_count"],
        stock_alert_threshold=5,
        image_path=None,
        start_date=start_date_str,
        end_date=end_date_str
    )
    
    for time_str in state_data["times"]:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type='daily'
        )
        
    await scheduler.setup_scheduler(bot)
    
    start_display = start_date_str
    end_display = end_date_str
    success_text = _T("add_success", lang, name=state_data["name"], start=start_display, end=end_display)
    
    await message.answer(success_text, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
    await complete_wizard(message, state, bot)
    await state.clear()
    
    # Анализ лекарства
    asyncio.create_task(run_background_classification_and_rec(bot, message.from_user.id, med_id, state_data["name"]))


@router.callback_query(StateFilter(AddMedication.waiting_for_duration), F.data == "duration_permanent")
async def process_duration_permanent(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    
    start_date_str = now_local.strftime("%Y-%m-%d")
    end_date_str = None
    
    state_data = await state.get_data()
    
    med_id = await database.add_medication(
        user_id=callback.from_user.id,
        name=state_data["name"],
        active_ingredient=state_data.get("active_ingredient"),
        dosage=state_data["dosage"],
        food_relation=state_data["food_relation"],
        stock_count=state_data["stock_count"],
        stock_alert_threshold=5,
        image_path=None,
        start_date=start_date_str,
        end_date=end_date_str
    )
    
    for time_str in state_data["times"]:
        await database.add_reminder(
            medication_id=med_id,
            time_str=time_str,
            schedule_type='daily'
        )
        
    await scheduler.setup_scheduler(bot)
    
    start_display = start_date_str
    end_display = _T("course_no_limit", lang)
    success_text = _T("add_success", lang, name=state_data["name"], start=start_display, end=end_display)
    
    await delete_wizard_msgs(bot, callback.message.chat.id, state)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(success_text, reply_markup=get_main_menu_keyboard(lang), parse_mode="Markdown")
    await state.clear()
    await callback.answer()
    
    # Анализ лекарства
    asyncio.create_task(run_background_classification_and_rec(bot, callback.from_user.id, med_id, state_data["name"]))


# --- ОБРАБОТКА ДЕЙСТВИЙ ИЗ УВЕДОМЛЕНИЙ (ПРИНЯЛ / ПРОПУСТИЛ) ---

@router.callback_query(F.data.startswith("take:"))
async def process_take_pill(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    med_id = int(parts[1])
    expected_time_iso = ":".join(parts[2:])
    
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history == 'taken':
        await callback.answer("Прием уже подтвержден!")
        return
        
    user = await database.get_user(callback.from_user.id)
    import pytz
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow') if user else pytz.timezone('Europe/Moscow')
    now_local = datetime.now(user_tz)

    # 1. Обновляем статус в истории с использованием локального времени пользователя
    await database.update_history_status(med_id, expected_time_iso, 'taken', now_local.isoformat())
    scheduler.remove_snooze_jobs_from_scheduler(med_id)
        
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
        f"✅ *Принято в {now_local.strftime('%H:%M')}!*\n\n"
        f"💊 Препарат: *{med['name']}*\n"
        f"🤖 *Мистер Таблетус:* «Спасибо! Будьте здоровы! {mascot_msg}»"
        f"{stock_warning}"
    )
    
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
        
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history in ['taken', 'skipped']:
        await callback.answer("Прием уже обработан!")
        return
        
    # 1. Записываем пропуск
    await database.update_history_status(med_id, expected_time_iso, 'skipped', datetime.now().isoformat())
    scheduler.remove_snooze_jobs_from_scheduler(med_id)
        
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
        
    snoozed_text = (
        f"⏰ *Напоминание отложено на 15 минут!*\n\n"
        f"💊 Препарат: *{med['name']}*\n"
        f"🤖 *Мистер Таблетус:* «Хорошо, я вернусь к вам через 15 минут. Не забудьте!»"
    )
    
    if callback.message.photo:
        await callback.message.edit_caption(caption=snoozed_text, reply_markup=None, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=snoozed_text, reply_markup=None, parse_mode="Markdown")
        
    orig_date_str = None
    try:
        expected_time = datetime.fromisoformat(expected_time_iso)
        expected_time_str = expected_time.strftime("%H:%M")
        orig_date_str = expected_time.date().isoformat()
    except Exception:
        user = await database.get_user(callback.from_user.id)
        import pytz
        user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow') if user else pytz.timezone('Europe/Moscow')
        expected_time_str = datetime.now(user_tz).strftime("%H:%M")

    run_time = datetime.now() + timedelta(minutes=15)
    job_id = f"snooze_{med_id}_{int(run_time.timestamp())}"
    
    scheduler.scheduler.add_job(
        scheduler.send_reminder_job,
        'date',
        run_date=run_time,
        id=job_id,
        args=[bot, callback.from_user.id, 0, med_id, expected_time_str, orig_date_str]
    )
    
    await callback.answer("Отложено на 15 минут!")


# --- ОБРАБОТКА ПОЗДНЕГО ПРИЕМА ЛЕКАРСТВ ---

class TakeLateState(StatesGroup):
    waiting_for_time = State()

def calculate_next_dose_interval(target_time_str: str, all_times: list) -> float:
    if not all_times or len(all_times) <= 1:
        return 24.0
    sorted_times = sorted(all_times)
    if target_time_str not in sorted_times:
        return 24.0 / len(all_times)
    idx = sorted_times.index(target_time_str)
    next_idx = (idx + 1) % len(sorted_times)
    next_time_str = sorted_times[next_idx]
    try:
        t1 = datetime.strptime(target_time_str, "%H:%M")
        t2 = datetime.strptime(next_time_str, "%H:%M")
        diff = t2 - t1
        if diff.total_seconds() <= 0:
            diff += timedelta(days=1)
        return diff.total_seconds() / 3600.0
    except Exception:
        return 24.0 / len(all_times)

def resolve_actual_datetime(entered_time_str: str, expected_dt: datetime, now_dt: datetime) -> Optional[datetime]:
    try:
        hour, minute = map(int, entered_time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
    except ValueError:
        return None
    
    candidates = []
    tz = expected_dt.tzinfo
    for day_offset in [-1, 0, 1]:
        base_date = (expected_dt + timedelta(days=day_offset)).date()
        naive_dt = datetime.combine(base_date, datetime.min.time()).replace(
            hour=hour, minute=minute
        )
        if hasattr(tz, 'localize'):
            dt = tz.localize(naive_dt)
        else:
            dt = naive_dt.replace(tzinfo=tz)
        candidates.append(dt)
    
    valid_candidates = [c for c in candidates if c <= now_dt]
    if not valid_candidates:
        return None
        
    return min(valid_candidates, key=lambda c: abs((c - expected_dt).total_seconds()))

async def find_target_reminder_for_cabinet_take(med_id: int, user_tz, actual_time: datetime) -> Optional[tuple[dict, str]]:
    reminders = await database.get_medication_reminders(med_id)
    if not reminders:
        return None
        
    candidates = []
    for r in reminders:
        hour, minute = map(int, r['time_str'].split(':'))
        naive_dt = datetime.combine(actual_time.date(), datetime.min.time()).replace(
            hour=hour, minute=minute
        )
        if hasattr(user_tz, 'localize'):
            expected_dt = user_tz.localize(naive_dt)
        else:
            expected_dt = naive_dt.replace(tzinfo=user_tz)
            
        # Only consider candidates that are in the past or at most 2h in the future
        valid_cands = []
        for offset in [-1, 0, 1]:
            cand_naive = naive_dt + timedelta(days=offset)
            if hasattr(user_tz, 'localize'):
                cand = user_tz.localize(cand_naive)
            else:
                cand = cand_naive.replace(tzinfo=user_tz)
            
            if cand <= actual_time + timedelta(hours=2):
                valid_cands.append(cand)

        if not valid_cands:
            continue

        best_dt = min(valid_cands, key=lambda c: abs((c - actual_time).total_seconds()))
                
        expected_iso = best_dt.isoformat()
        status = await database.get_history_status(med_id, expected_iso)
        
        candidates.append({
            'reminder': r,
            'expected_dt': best_dt,
            'expected_iso': expected_iso,
            'status': status or 'pending'
        })
        
    untaken = [c for c in candidates if c['status'] not in ['taken', 'taken_late']]
    if not untaken:
        return None
        
    best_candidate = min(untaken, key=lambda c: abs((c['expected_dt'] - actual_time).total_seconds()))
    return best_candidate['reminder'], best_candidate['expected_iso']

async def perform_take_late(bot: Bot, user_id: int, med_id: int, expected_time_iso: str, actual_time: datetime, msg_id: int, callback: Optional[CallbackQuery] = None, state: Optional[FSMContext] = None):
    user = await database.get_user(user_id)
    if not user:
        return
    lang = user.get("language") if user else "ru"
    
    expected_time = datetime.fromisoformat(expected_time_iso)
    delay_seconds = (actual_time - expected_time).total_seconds()
    delay_hours = max(0.0, delay_seconds / 3600.0)
    
    # --- HARD LIMITS ---
    # 1. Cannot mark intake for a different day
    if actual_time.date() != expected_time.date():
        reject_text = _T("take_late_next_day", lang)
        if callback:
            await callback.answer(reject_text, show_alert=True)
        else:
            try:
                await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=reject_text, reply_markup=None, parse_mode="Markdown")
            except Exception:
                pass
        if state:
            await state.clear()
        return
    
    # 2. Cannot mark intake if more than 4 hours late
    if delay_hours > 4.0:
        reject_text = _T("take_late_too_late", lang)
        if callback:
            await callback.answer(reject_text, show_alert=True)
        else:
            try:
                await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=reject_text, reply_markup=None, parse_mode="Markdown")
            except Exception:
                pass
        if state:
            await state.clear()
        return
    
    is_on_time = delay_seconds <= 45.0 * 60.0
    status_to_log = 'taken' if is_on_time else 'taken_late'
    
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history in ['taken', 'taken_late']:
        if callback:
            await callback.answer("Прием уже подтвержден!")
        return
        
    med = await database.get_medication(med_id)
    if not med:
        return
    med_name = med['name']
    
    # 1. Update history status
    if status_history is None:
        await database.log_history(user_id, med_id, expected_time_iso, status_to_log, actual_time.isoformat())
    else:
        await database.update_history_status(med_id, expected_time_iso, status_to_log, actual_time.isoformat())
    scheduler.remove_snooze_jobs_from_scheduler(med_id)
    
    # 2. Update stock
    await database.update_medication_stock(med_id, -1)
    updated_med = await database.get_medication(med_id)
    
    stock_warning = ""
    if updated_med and updated_med['stock_count'] <= updated_med['stock_alert_threshold']:
        stock_warning = f"\n⚠️ *Внимание:* в аптечке осталось всего {updated_med['stock_count']} шт.!"
        
    actual_time_str = actual_time.strftime("%H:%M")
    
    # 3. Determine window and apply Tamagotchi health
    #    ≤ 45 min  → taken (on time): +5 HP, +10 XP
    #    > 45 min and ≤ 4h → taken_late: +5 HP, +5 XP
    if is_on_time:
        status = await database.update_user_tamagotchi(user_id, health_delta=5, xp_delta=10)
        mascot_msg = f"❤️ Моё здоровье: {status['health']}% (+5%) | ⭐ Уровень: {status['level']}" if status else ""
        if status and status.get("level_up"):
            mascot_msg += "\n🎉 **LEVEL UP!** Мистер Таблетус повысил свой уровень!"
        feedback_text = _T("taken_success", lang, time=actual_time_str, name=med_name, mascot_msg=mascot_msg, stock_warning=stock_warning)
    else:
        status = await database.update_user_tamagotchi(user_id, health_delta=5, xp_delta=5)
        mascot_msg = f"❤️ Моё здоровье: {status['health']}% (+5%) | ⭐ Уровень: {status['level']}" if status else ""
        if status and status.get("level_up"):
            mascot_msg += "\n🎉 **LEVEL UP!** Мистер Таблетус повысил свой уровень!"
        feedback_text = _T("taken_late_success", lang, time=actual_time_str, name=med_name, mascot_msg=mascot_msg, stock_warning=stock_warning)
            
    # 4. Handle rendering depending on source
    from_cabinet = False
    if state:
        state_data = await state.get_data()
        from_cabinet = state_data.get("from_cabinet", False)
        
    if from_cabinet:
        idx = 1
        if state:
            state_data = await state.get_data()
            idx = state_data.get("late_idx", 1)
        med_text, keyboard = await get_medication_card_data(updated_med, idx, user, lang)
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg_id,
                text=med_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await bot.send_message(
                chat_id=user_id,
                text=feedback_text,
                parse_mode="Markdown"
            )
        except Exception as edit_err:
            logger.error(f"Error updating cabinet card: {edit_err}")
    else:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=msg_id,
                text=feedback_text,
                reply_markup=None,
                parse_mode="Markdown"
            )
        except Exception as edit_err:
            logger.error(f"Error editing message in perform_take_late: {edit_err}")
            
    if callback:
        await callback.answer("Прием подтвержден!")
        
    if state:
        await state.clear()

@router.callback_query(F.data.startswith("take_med_cabinet:"))
async def process_take_med_cabinet_start(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    target = await find_target_reminder_for_cabinet_take(med_id, user_tz, now_local)
    if target is None:
        # Ищем информацию о последнем приеме
        query_sqlite = "SELECT action_time FROM history WHERE medication_id = ? AND status IN ('taken', 'taken_late') ORDER BY action_time DESC LIMIT 1"
        query_pg = "SELECT action_time FROM history WHERE medication_id = $1 AND status IN ('taken', 'taken_late') ORDER BY action_time DESC LIMIT 1"
        last_take = await database.fetch_one(query_sqlite, query_pg, (med_id,))
        last_info = ""
        if last_take and last_take.get("action_time"):
            try:
                time_str = last_take["action_time"]
                if "." in time_str:
                    time_str = time_str.split(".")[0]
                dt = datetime.fromisoformat(time_str)
                formatted = dt.strftime("%H:%M (%d.%m.%Y)")
                if lang == "ru":
                    last_info = f"\nПоследний прием: {formatted}"
                elif lang == "en":
                    last_info = f"\nLast intake: {formatted}"
                else:
                    last_info = f"\nОстанній прийом: {formatted}"
            except Exception:
                pass
        
        msg = (
            f"Все приемы этого лекарства на сегодня уже выполнены!{last_info}" if lang == "ru"
            else f"All intakes for this medication have already been completed today!{last_info}" if lang == "en"
            else f"Всі прийоми цих ліків на сьогодні вже виконані!{last_info}"
        )
        await callback.answer(msg, show_alert=True)
        return
        
    try:
        idx = int(callback.message.text.split(".")[0])
    except Exception:
        idx = 1
        
    await state.set_state(TakeLateState.waiting_for_time)
    await state.update_data(
        late_med_id=med_id,
        from_cabinet=True,
        late_msg_id=callback.message.message_id,
        late_idx=idx
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("btn_now", lang), callback_data="take_late_now"),
            InlineKeyboardButton(text=_T("btn_cancel", lang), callback_data="take_late_cancel")
        ]
    ])
    
    await callback.message.edit_text(
        _T("prompt_actual_time", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("take_late:"))
async def process_take_late_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    med_id = int(parts[1])
    expected_time_iso = ":".join(parts[2:])
    
    status_history = await database.get_history_status(med_id, expected_time_iso)
    if status_history in ['taken', 'taken_late']:
        await callback.answer("Прием уже подтвержден!")
        return
        
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    # Check: is it already the next day? If so — reject immediately
    try:
        user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
        now_local = datetime.now(user_tz)
        expected_time = datetime.fromisoformat(expected_time_iso)
        
        if now_local.date() != expected_time.date():
            await callback.answer(_T("take_late_next_day", lang), show_alert=True)
            # Remove the "take late" button from the old message
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
    except Exception as tz_err:
        logger.error(f"Error checking late limits: {tz_err}")
    
    await state.set_state(TakeLateState.waiting_for_time)
    await state.update_data(
        late_med_id=med_id,
        from_cabinet=False,
        late_expected_time_iso=expected_time_iso,
        late_msg_id=callback.message.message_id
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_T("btn_now", lang), callback_data="take_late_now"),
            InlineKeyboardButton(text=_T("btn_cancel", lang), callback_data="take_late_cancel")
        ]
    ])
    
    await callback.message.edit_text(
        _T("prompt_actual_time", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(TakeLateState.waiting_for_time, F.data == "take_late_now")
async def process_take_late_now(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = await database.get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    lang = user.get("language") if user else "ru"
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    
    state_data = await state.get_data()
    med_id = state_data.get("late_med_id")
    msg_id = state_data.get("late_msg_id")
    from_cabinet = state_data.get("from_cabinet", False)
    
    if from_cabinet:
        target = await find_target_reminder_for_cabinet_take(med_id, user_tz, now_local)
        if target is None:
            query_sqlite = "SELECT action_time FROM history WHERE medication_id = ? AND status IN ('taken', 'taken_late') ORDER BY action_time DESC LIMIT 1"
            query_pg = "SELECT action_time FROM history WHERE medication_id = $1 AND status IN ('taken', 'taken_late') ORDER BY action_time DESC LIMIT 1"
            last_take = await database.fetch_one(query_sqlite, query_pg, (med_id,))
            last_info = ""
            if last_take and last_take.get("action_time"):
                try:
                    time_str = last_take["action_time"]
                    if "." in time_str:
                        time_str = time_str.split(".")[0]
                    dt = datetime.fromisoformat(time_str)
                    formatted = dt.strftime("%H:%M (%d.%m.%Y)")
                    if lang == "ru":
                        last_info = f"\nПоследний прием: {formatted}"
                    elif lang == "en":
                        last_info = f"\nLast intake: {formatted}"
                    else:
                        last_info = f"\nОстанній прийом: {formatted}"
                except Exception:
                    pass
            await callback.answer(
                f"Все приемы этого лекарства на сегодня уже выполнены!{last_info}" if lang == "ru"
                else f"All intakes for this medication have already been completed today!{last_info}" if lang == "en"
                else f"Всі прийоми цих ліків на сьогодні вже виконані!{last_info}",
                show_alert=True
            )
            # Restore card
            idx = state_data.get("late_idx", 1)
            med = await database.get_medication(med_id)
            lang = user.get("language") if user else "ru"
            med_text, keyboard = await get_medication_card_data(med, idx, user, lang)
            try:
                await bot.edit_message_text(
                    chat_id=callback.from_user.id,
                    message_id=msg_id,
                    text=med_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            await state.clear()
            return
        expected_time_iso = target[1]
    else:
        expected_time_iso = state_data.get("late_expected_time_iso")
        
    await perform_take_late(bot, callback.from_user.id, med_id, expected_time_iso, now_local, msg_id, callback=callback, state=state)

@router.callback_query(TakeLateState.waiting_for_time, F.data == "take_late_cancel")
async def process_take_late_cancel(callback: CallbackQuery, state: FSMContext):
    try:
        user = await database.get_user(callback.from_user.id)
        lang = user.get("language") if user else "ru"
        
        state_data = await state.get_data()
        med_id = state_data.get("late_med_id")
        from_cabinet = state_data.get("from_cabinet", False)
        msg_id = state_data.get("late_msg_id")
        
        if from_cabinet:
            idx = state_data.get("late_idx", 1)
            med = await database.get_medication(med_id)
            if med:
                med_text, keyboard = await get_medication_card_data(med, idx, user, lang)
                try:
                    await callback.message.edit_text(med_text, reply_markup=keyboard, parse_mode="Markdown")
                except Exception:
                    pass
            else:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            await state.clear()
            await callback.answer(_T("take_late_canceled", lang))
            return
            
        expected_time_iso = state_data.get("late_expected_time_iso")
        med = await database.get_medication(med_id)
        med_name = med['name'] if med else "лекарство"
        health_msg = f"💔 Моё здоровье упало до {user['mascot_health']}%!" if user else ""
        
        text = (
            f"🚨 *Пропущен прием лекарства!*\n\n"
            f"Вы не подтвердили прием *{med_name}* вовремя (прошло 45 минут).\n\n"
            f"🤢 *Мистер Таблетус:* «Ай! Мне стало хуже... Пожалуйста, не забывайте о своем здоровье и обо мне! {health_msg}»"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=_T("btn_take_late", lang), callback_data=f"take_late:{med_id}:{expected_time_iso}")
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await state.clear()
        await callback.answer(_T("take_late_canceled", lang))
    except Exception as e:
        logger.error(f"Error in process_take_late_cancel: {e}", exc_info=True)
        await state.clear()
        try:
            await callback.answer("Отменено")
        except Exception:
            pass

@router.message(StateFilter(TakeLateState.waiting_for_time))
async def process_take_late_input(message: Message, state: FSMContext, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
        
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    user_tz = pytz.timezone(user['timezone'] or 'Europe/Moscow')
    now_local = datetime.now(user_tz)
    
    time_text = message.text.strip()
    state_data = await state.get_data()
    msg_id = state_data.get("late_msg_id")
    med_id = state_data.get("late_med_id")
    from_cabinet = state_data.get("from_cabinet", False)
    
    if not re.match(r"^\d{1,2}:\d{2}$", time_text):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=_T("btn_now", lang), callback_data="take_late_now"),
                InlineKeyboardButton(text=_T("btn_cancel", lang), callback_data="take_late_cancel")
            ]
        ])
        try:
            await bot.edit_message_text(
                chat_id=message.from_user.id,
                message_id=msg_id,
                text=f"{_T('prompt_actual_time', lang)}\n\n{_T('invalid_actual_time', lang, time=time_text)}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return
        
    if from_cabinet:
        reminders = await database.get_medication_reminders(med_id)
        if not reminders:
            await state.clear()
            return
        hour, minute = map(int, reminders[0]['time_str'].split(':'))
        temp_dt = datetime.combine(now_local.date(), datetime.min.time()).replace(
            hour=hour, minute=minute, tzinfo=user_tz
        )
        expected_date_ref = temp_dt
    else:
        expected_time_iso = state_data.get("late_expected_time_iso")
        expected_date_ref = datetime.fromisoformat(expected_time_iso)
        
    actual_time = resolve_actual_datetime(time_text, expected_date_ref, now_local)
    
    if actual_time is None:
        now_time_str = now_local.strftime("%H:%M")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=_T("btn_now", lang), callback_data="take_late_now"),
                InlineKeyboardButton(text=_T("btn_cancel", lang), callback_data="take_late_cancel")
            ]
        ])
        try:
            await bot.edit_message_text(
                chat_id=message.from_user.id,
                message_id=msg_id,
                text=f"{_T('prompt_actual_time', lang)}\n\n{_T('future_time_error', lang, now=now_time_str)}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return
        
    if from_cabinet:
        target = await find_target_reminder_for_cabinet_take(med_id, user_tz, actual_time)
        if target is None:
            idx = state_data.get("late_idx", 1)
            med = await database.get_medication(med_id)
            med_text, keyboard = await get_medication_card_data(med, idx, user, lang)
            try:
                await bot.edit_message_text(
                    chat_id=message.from_user.id,
                    message_id=msg_id,
                    text=med_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            await message.answer("Все приемы этого лекарства на сегодня уже выполнены!")
            await state.clear()
            return
        expected_time_iso = target[1]
    else:
        expected_time_iso = state_data.get("late_expected_time_iso")
        
    await perform_take_late(bot, message.from_user.id, med_id, expected_time_iso, actual_time, msg_id, state=state)


# --- ФОНОВАЯ КЛАССИФИКАЦИЯ И РЕКОМЕНДАЦИИ ИИ ---

async def run_background_classification_and_rec(bot: Bot, chat_id: int, med_id: int, medicine_name: str):
    try:
        user = await database.get_user(chat_id)
        lang = user.get("language") if user else "ru"
        
        # 1. Классифицируем название препарата через Gemini
        classification = await gemini_service.classify_medicine_name(medicine_name)
        category = classification.get("category", "real")
        
        if category == "real":
            recommendations = await gemini_service.get_medicine_recommendations(medicine_name, lang)
            if recommendations:
                caption = ("💡 *Рекомендации от Мистера Таблетуса для {name}:*\n{recs}" if lang == "ru"
                           else "💡 *Mr. Tabletus recommendations for {name}:*\n{recs}" if lang == "en"
                           else "💡 *Рекомендації від Містера Таблетуса для {name}:*\n{recs}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption.format(name=medicine_name, recs=recommendations),
                    parse_mode="Markdown"
                )
        elif category == "plausible":
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}"),
                    InlineKeyboardButton(text=_T("btn_send_photo", lang), callback_data=f"set_active_photo:{med_id}")
                ],
                [
                    InlineKeyboardButton(text=_T("btn_send_link", lang), callback_data=f"set_active_link:{med_id}")
                ]
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=_T("plausible_warning", lang, name=medicine_name),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else: # nonsense
            reminders = await database.get_medication_reminders(med_id)
            for r in reminders:
                scheduler.remove_reminder_from_scheduler(r['id'])
                
            await database.delete_medication(med_id)
            await scheduler.setup_scheduler(bot)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_T("btn_add_again", lang), callback_data="add_manual")]
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=_T("nonsense_warning", lang, name=medicine_name),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Ошибка фонового анализа лекарства {medicine_name}: {e}")


@router.callback_query(F.data.startswith("set_active_ing:"))
async def process_set_active_ing_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_active_ingredient)
    await state.update_data(edit_med_id=med_id)
    
    prompt = ("Введите действующее вещество для лекарства *{name}* (например: _Ибупрофен_):" if lang == "ru"
              else "Enter the active ingredient for *{name}* (e.g., _Ibuprofen_):" if lang == "en"
              else "Введіть діючу речовину для ліків *{name}* (наприклад: _Ібупрофен_):")
              
    await callback.message.answer(
        prompt.format(name=med['name']),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(StateFilter(EditMedication.waiting_for_active_ingredient))
async def process_input_active_ingredient(message: Message, state: FSMContext, bot: Bot):
    active_ingredient = message.text.strip()
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Ошибка: лекарство не найдено в базе данных." if lang == "ru" else "Error: medication not found in database." if lang == "en" else "Помилка: препарат не знайдено в базі даних."
        await message.answer(err_msg, reply_markup=get_main_menu_keyboard(lang))
        await state.clear()
        return
        
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    success = ("✅ Действующее вещество для *{name}* успешно обновлено на **{ing}**!" if lang == "ru"
               else "✅ Active ingredient for *{name}* has been successfully updated to **{ing}**!" if lang == "en"
               else "✅ Діючу речовину для *{name}* успішно оновлено на **{ing}**!")
               
    await message.answer(
        success.format(name=med['name'], ing=active_ingredient),
        reply_markup=get_main_menu_keyboard(lang),
        parse_mode="Markdown"
    )
    await state.clear()
    
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str, user_lang: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})", user_lang)
            if recommendations:
                caption = ("💡 *Рекомендации для {name} ({ing}):*\n{recs}" if user_lang == "ru"
                           else "💡 *Recommendations for {name} ({ing}):*\n{recs}" if user_lang == "en"
                           else "💡 *Рекомендації для {name} ({ing}):*\n{recs}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption.format(name=medicine_name, ing=ingredient, recs=recommendations),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient, lang))


@router.callback_query(F.data.startswith("set_active_photo:"))
async def process_set_active_photo_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_photo)
    await state.update_data(edit_med_id=med_id)
    
    prompt = ("📸 Пожалуйста, пришлите фотографию упаковки лекарства *{name}* (я попробую распознать действующее вещество с помощью ИИ):" if lang == "ru"
              else "📸 Please send a photo of the package for *{name}* (I will try to recognize the active ingredient using AI):" if lang == "en"
              else "📸 Будь ласка, надішліть фотографію упаковки ліків *{name}* (я спробую розпізнати діючу речовину за допомогою ШІ):")
              
    await callback.message.answer(
        prompt.format(name=med['name']),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_active_link:"))
async def process_set_active_link_callback(callback: CallbackQuery, state: FSMContext):
    med_id = int(callback.data.split(":")[1])
    med = await database.get_medication(med_id)
    
    user = await database.get_user(callback.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not med:
        await callback.answer("Лекарство не найдено!")
        return
        
    await state.set_state(EditMedication.waiting_for_link)
    await state.update_data(edit_med_id=med_id)
    
    prompt = ("🔗 Пожалуйста, отправьте ссылку на веб-страницу с описанием лекарства *{name}* (я прочитаю её и извлеку действующее вещество):" if lang == "ru"
              else "🔗 Please send a URL link to a webpage describing *{name}* (I will read it and extract the active ingredient):" if lang == "en"
              else "🔗 Будь ласка, надішліть посилання на веб-сторінку з описом ліків *{name}* (я прочитаю її та витягну діючу речовину):")
              
    await callback.message.answer(
        prompt.format(name=med['name']),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(StateFilter(EditMedication.waiting_for_photo), F.photo)
async def process_input_active_photo(message: Message, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Ошибка: лекарство не найдено в базе данных." if lang == "ru" else "Error: medication not found in database." if lang == "en" else "Помилка: препарат не знайдено в базі даних."
        await message.answer(err_msg, reply_markup=get_main_menu_keyboard(lang))
        await state.clear()
        return
        
    processing_msg = await message.answer(_T("scanning_photo", lang), parse_mode="Markdown")
    
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
        failed_prompt = ("😔 Мне не удалось распознать действующее вещество на этой фотографии.\nПожалуйста, пришлите другое фото упаковки, введите вещество текстом или отправьте ссылку:" if lang == "ru"
                         else "😔 I couldn't recognize the active ingredient in this photo.\nPlease send another photo, enter it as text, or send a link:" if lang == "en"
                         else "😔 Мені не вдалося розпізнати діючу речовину на цій фотографії.\nБудь ласка, надішліть інше фото упаковки, введіть речовину текстом або надішліть посилання:")
        await message.answer(
            failed_prompt,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text=_T("btn_send_link", lang), callback_data=f"set_active_link:{med_id}")]
            ])
        )
        return
        
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    success = ("✅ Действующее вещество для *{name}* успешно распознано как **{ing}** и обновлено!" if lang == "ru"
               else "✅ Active ingredient for *{name}* has been successfully recognized as **{ing}** and updated!" if lang == "en"
               else "✅ Діючу речовину для *{name}* успішно розпізнано як **{ing}** та оновлено!")
               
    await message.answer(
        success.format(name=med['name'], ing=active_ingredient),
        reply_markup=get_main_menu_keyboard(lang),
        parse_mode="Markdown"
    )
    await state.clear()
    
    # Рекомендации
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str, user_lang: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})", user_lang)
            if recommendations:
                caption = ("💡 *Рекомендации для {name} ({ing}):*\n{recs}" if user_lang == "ru"
                           else "💡 *Recommendations for {name} ({ing}):*\n{recs}" if user_lang == "en"
                           else "💡 *Рекомендації для {name} ({ing}):*\n{recs}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption.format(name=medicine_name, ing=ingredient, recs=recommendations),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient, lang))


@router.message(StateFilter(EditMedication.waiting_for_photo))
async def process_input_active_photo_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    prompt = ("⚠️ Пожалуйста, пришлите именно фотографию упаковки лекарства или выберите другой способ ввода:" if lang == "ru"
              else "⚠️ Please send an actual photo of the medication package or choose another input method:" if lang == "en"
              else "⚠️ Будь ласка, надішліть саме фотографію упаковки ліків або оберіть інший спосіб введення:")
              
    await message.answer(
        prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}")],
            [InlineKeyboardButton(text=_T("btn_send_link", lang), callback_data=f"set_active_link:{med_id}")]
        ])
    )


@router.message(StateFilter(EditMedication.waiting_for_link), F.text)
async def process_input_active_link(message: Message, state: FSMContext, bot: Bot):
    url = message.text.strip()
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    if not (url.startswith("http://") or url.startswith("https://")):
        invalid_format = ("❌ Неверный формат ссылки. Ссылка должна начинаться с `http://` или `https://`.\nПожалуйста, отправьте корректную ссылку или выберите другой способ:" if lang == "ru"
                          else "❌ Invalid URL format. The link must start with `http://` or `https://`.\nPlease send a valid link or choose another method:" if lang == "en"
                          else "❌ Невірний формат посилання. Посилання має починатися з `http://` або `https://`.\nБудь ласка, надішліть коректне посилання або оберіть інший спосіб:")
        await message.answer(
            invalid_format,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text=_T("btn_send_photo", lang), callback_data=f"set_active_photo:{med_id}")]
            ])
        )
        return
        
    med = await database.get_medication(med_id)
    if not med:
        err_msg = "Ошибка: лекарство не найдено в базе данных." if lang == "ru" else "Error: medication not found in database." if lang == "en" else "Помилка: препарат не знайдено в базі даних."
        await message.answer(err_msg, reply_markup=get_main_menu_keyboard(lang))
        await state.clear()
        return
        
    processing_msg = await message.answer(
        "🔍 *Мистер Таблетус анализирует веб-страницу...* 🌐" if lang == "ru"
        else "🔍 *Mr. Tabletus is analyzing the webpage...* 🌐" if lang == "en"
        else "🔍 *Містер Таблетус аналізує веб-сторінку...* 🌐",
        parse_mode="Markdown"
    )
    
    active_ingredient = await gemini_service.extract_active_ingredient_from_url(url, med["name"])
    await processing_msg.delete()
    
    if not active_ingredient:
        failed_link = ("😔 Мне не удалось найти действующее вещество по этой ссылке.\nПожалуйста, отправьте другую ссылку, введите действующее вещество текстом или пришлите фото упаковки:" if lang == "ru"
                       else "😔 I couldn't find the active ingredient at this link.\nPlease send another link, enter the active ingredient as text, or send a package photo:" if lang == "en"
                       else "😔 Мені не вдалося знайти діючу речовину за цим посиланням.\nБудь ласка, надішліть інше посилання, введіть діючу речовину текстом або надішліть фото упаковки:")
        await message.answer(
            failed_link,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}")],
                [InlineKeyboardButton(text=_T("btn_send_photo", lang), callback_data=f"set_active_photo:{med_id}")]
            ])
        )
        return
        
    await database.update_medication_active_ingredient(med_id, active_ingredient)
    
    success = ("✅ На основе веб-страницы действующее вещество для *{name}* определено как **{ing}** и обновлено!" if lang == "ru"
               else "✅ Based on the webpage, the active ingredient for *{name}* is determined as **{ing}** and updated!" if lang == "en"
               else "✅ На основі веб-сторінки діючу речовину для *{name}* визначено як **{ing}** та оновлено!")
               
    await message.answer(
        success.format(name=med['name'], ing=active_ingredient),
        reply_markup=get_main_menu_keyboard(lang),
        parse_mode="Markdown"
    )
    await state.clear()
    
    # Рекомендации
    async def send_recommendations_bg(bot: Bot, chat_id: int, medicine_name: str, ingredient: str, user_lang: str):
        try:
            recommendations = await gemini_service.get_medicine_recommendations(f"{medicine_name} ({ingredient})", user_lang)
            if recommendations:
                caption = ("💡 *Рекомендации для {name} ({ing}):*\n{recs}" if user_lang == "ru"
                           else "💡 *Recommendations for {name} ({ing}):*\n{recs}" if user_lang == "en"
                           else "💡 *Рекомендації для {name} ({ing}):*\n{recs}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption.format(name=medicine_name, ing=ingredient, recs=recommendations),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка фоновой отправки рекомендаций: {e}")
            
    asyncio.create_task(send_recommendations_bg(bot, message.from_user.id, med["name"], active_ingredient, lang))


@router.message(StateFilter(EditMedication.waiting_for_link))
async def process_input_active_link_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    med_id = state_data.get("edit_med_id")
    
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    prompt = ("⚠️ Пожалуйста, отправьте ссылку в виде текста или выберите другой способ ввода:" if lang == "ru"
              else "⚠️ Please send the URL as text or choose another input method:" if lang == "en"
              else "⚠️ Будь ласка, надішліть посилання у вигляді тексту або оберіть інший спосіб введення:")
              
    await message.answer(
        prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_T("btn_set_mnn", lang), callback_data=f"set_active_ing:{med_id}")],
            [InlineKeyboardButton(text=_T("btn_send_photo", lang), callback_data=f"set_active_photo:{med_id}")]
        ])
    )


# --- Обработчик свободного ввода названия лекарства (быстрый старт добавления) ---
def is_not_menu_button(message: Message) -> bool:
    if not message.text:
        return False
    text = message.text.strip()
    if text.startswith("/"):
        return False
    langs = ["ru", "en", "uk"]
    menu_buttons = []
    for l in langs:
        menu_buttons.extend([
            _T("menu_my_meds", l),
            _T("menu_add_med", l),
            _T("menu_tamagotchi", l),
            _T("menu_buddies", l),
            _T("menu_change_tz", l)
        ])
    return text not in menu_buttons

@router.message(StateFilter(None), F.text, is_not_menu_button)
async def process_unknown_text(message: Message, state: FSMContext):
    """Catch-all: user sent text outside any wizard — delete it and hint to use buttons."""
    user = await database.get_user(message.from_user.id)
    lang = user.get("language") if user else "ru"
    
    # Delete user's message immediately
    try:
        await message.delete()
    except Exception:
        pass
    
    # Send a temporary hint and auto-delete it after 5 seconds
    hint = await message.answer(
        _T("use_buttons_hint", lang),
        parse_mode="Markdown"
    )
    await asyncio.sleep(5)
    try:
        await hint.delete()
    except Exception:
        pass

@router.callback_query(F.data == "feedback_no_use")
async def process_feedback_no_use(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await database.get_user(user_id)
    lang = user.get("language") if user else "ru"
    
    # 1. Soft-delete all medications for this user and remove them from scheduler
    meds = await database.get_user_medications(user_id)
    for med in meds:
        await database.delete_medication(med['id'])
        reminders = await database.get_medication_reminders(med['id'])
        for r in reminders:
            scheduler.remove_reminder_from_scheduler(r['id'])
            
    # 2. Respond to the user
    goodbye_msg = {
        "ru": "Очень жаль! Я отключил все ваши напоминания. Если решите вернуться, просто добавьте новое лекарство с помощью меню. Буду ждать вас! 🤖💊",
        "en": "So sorry! I have disabled all your reminders. If you decide to return, just add a new medication via the menu. I'll be waiting! 🤖💊",
        "uk": "Дуже шкода! Я вимкнув усі ваші нагадування. Якщо вирішите повернутися, просто додайте нові ліки за допомогою меню. Буду чекати на вас! 🤖💊"
    }.get(lang, "Очень жаль! Я отключил все ваши напоминания. Если решите вернуться, просто добавьте новое лекарство с помощью меню. Буду ждать вас! 🤖💊")
    
    await callback.message.edit_text(
        text=goodbye_msg,
        reply_markup=None,
        parse_mode="Markdown"
    )
    await callback.answer()
