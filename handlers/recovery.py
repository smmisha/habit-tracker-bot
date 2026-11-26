"""Пересказ статьи после срыва и план на следующий раз в чате."""
import html

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services import recovery_tasks, user_plans
from utils.states import Form

router = Router()

WRITE_PROMPT = (
    "✍️ Напиши пересказ одним сообщением: о чём статья, что запомнилось и что ты берёшь для себя. "
    "Хотя бы три предложения.\n"
    "Отменить — /cancel"
)

PLAN_QUESTION = (
    "Хочешь записать план на следующий раз? Например: „Если вечером я один и тянет к телефону, "
    "то выхожу на кухню и звоню другу“. Напиши одним сообщением или нажми «Пропустить»."
)
PLAN_SKIPPED_TEXT = "Хорошо. План можно записать позже в приложении, во вкладке «Дневник»."
PLAN_SKIP_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="plan:skip")]]
)


@router.callback_query(F.data.startswith("task:write:"))
async def process_task_write(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    raw_id = callback.data.rsplit(":", 1)[1]
    open_id = await recovery_tasks.get_open_task_id(user_id)

    if not raw_id.isdecimal() or int(raw_id) != open_id:
        await callback.message.answer(recovery_tasks.SUBMIT_ERRORS["closed"])
        # Вместо закрытого задания показываем текущее, если оно есть
        card = await recovery_tasks.open_task_card(user_id)
        if card:
            await callback.message.answer(card[0], reply_markup=card[1])
        return

    await state.set_state(Form.waiting_for_recovery_summary)
    await state.update_data(task_id=open_id)
    await callback.message.answer(WRITE_PROMPT)


# Команды проходят к своим обработчикам, а не записываются как пересказ
@router.message(Form.waiting_for_recovery_summary, F.text, ~F.text.startswith("/"))
async def process_summary_text(message: Message, state: FSMContext):
    data = await state.get_data()
    result = await recovery_tasks.submit_summary(message.from_user.id, data.get("task_id", 0), message.text)

    if result.status == "short":
        # Состояние сохраняется: следующее сообщение снова считается пересказом
        await message.answer(recovery_tasks.SUBMIT_ERRORS["short"])
        return

    await state.clear()
    if result.status != "done":
        await message.answer(recovery_tasks.SUBMIT_ERRORS[result.status])
        return

    if result.late:
        reply = "✅ Пересказ сохранён. Срок уже прошёл, задание засчитано с опозданием."
    else:
        reply = "✅ Пересказ сохранён, задание выполнено."
    if result.in_journal:
        reply += " Копия — в дневнике."
    await message.answer(reply)

    if await user_plans.has_room(message.from_user.id, "if_then"):
        await state.set_state(Form.waiting_for_plan)
        await message.answer(PLAN_QUESTION, reply_markup=PLAN_SKIP_KEYBOARD)


@router.message(Form.waiting_for_recovery_summary, ~F.text)
async def process_summary_non_text(message: Message):
    await message.answer("Напиши пересказ текстом или отправь /cancel.")


@router.callback_query(F.data == "plan:skip")
async def process_plan_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # Кнопка под старым вопросом не прерывает другой ввод
    if await state.get_state() == Form.waiting_for_plan.state:
        await state.clear()
        await callback.message.answer(PLAN_SKIPPED_TEXT)


@router.message(Form.waiting_for_plan, F.text, ~F.text.startswith("/"))
async def process_plan_text(message: Message, state: FSMContext):
    status = await user_plans.add_plan(message.from_user.id, "if_then", message.text)
    if status in ("empty", "long"):
        await message.answer(user_plans.PLAN_ERRORS[status], reply_markup=PLAN_SKIP_KEYBOARD)
        return

    await state.clear()
    if status != "added":
        await message.answer(user_plans.PLAN_ERRORS[status])
        return
    await message.answer(
        f"✅ План сохранён: «{html.escape(message.text.strip())}»\n"
        "Он появится в SOS и в сообщении с заданием. Удалить его можно в приложении, во вкладке «Дневник»."
    )


@router.message(Form.waiting_for_plan, ~F.text)
async def process_plan_non_text(message: Message):
    await message.answer("Напиши план текстом или нажми «Пропустить».", reply_markup=PLAN_SKIP_KEYBOARD)
