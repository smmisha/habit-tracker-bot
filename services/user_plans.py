"""Личные планы «если…, то…» и причины «Ради чего»."""
import html

from sqlalchemy import delete, select

from database.db_helper import db_helper
from database.models import User, UserPlan

# if_then — план на минуту тяги, reason — зачем пользователю свобода
PLAN_KINDS = ("if_then", "reason")
MAX_PLANS_PER_KIND = 5
MAX_PLAN_LENGTH = 300

PLAN_ERRORS = {
    "empty": "Напиши хотя бы несколько слов.",
    "long": "Слишком длинно: уложись в 300 символов.",
    "limit": "Уже пять записей. Удали лишнюю, чтобы добавить новую.",
    "not_found": "Запись не найдена.",
}


async def get_plans(session, user_id: int) -> dict[str, list[UserPlan]]:
    """Записи пользователя по видам, от старых к новым"""
    result = await session.execute(
        select(UserPlan).where(UserPlan.user_id == user_id).order_by(UserPlan.id)
    )
    plans = {kind: [] for kind in PLAN_KINDS}
    for plan in result.scalars().all():
        if plan.kind in plans:
            plans[plan.kind].append(plan)
    return plans


def plans_payload(plans: dict[str, list[UserPlan]]) -> dict:
    """Записи для Mini App"""
    return {kind: [{"id": p.id, "text": p.text} for p in items] for kind, items in plans.items()}


def plans_block(plans: dict[str, list[UserPlan]]) -> str:
    """Планы и причины для сообщения с заданием (HTML)"""
    blocks = []
    for kind, title in (("if_then", "🗺 <b>Мой план</b>"), ("reason", "❤️ <b>Ради чего</b>")):
        if plans[kind]:
            lines = "\n".join(f"• {html.escape(plan.text)}" for plan in plans[kind])
            blocks.append(f"{title}\n{lines}")
    return "\n\n".join(blocks)


async def has_room(user_id: int, kind: str) -> bool:
    async with db_helper.session_factory() as session:
        return len((await get_plans(session, user_id))[kind]) < MAX_PLANS_PER_KIND


async def add_plan(user_id: int, kind: str, text: str) -> str:
    """Возвращает "added" или ключ из PLAN_ERRORS. kind проверяет вызывающий код."""
    text = text.strip()
    if not text:
        return "empty"
    if len(text) > MAX_PLAN_LENGTH:
        return "long"

    async with db_helper.session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return "not_found"
        if len((await get_plans(session, user_id))[kind]) >= MAX_PLANS_PER_KIND:
            return "limit"
        session.add(UserPlan(user_id=user_id, kind=kind, text=text))
        user.consecutive_missed_checkins = 0
        await session.commit()
    return "added"


async def delete_plan(user_id: int, plan_id: int) -> bool:
    # Номер вне диапазона integer в Postgres вызвал бы ошибку запроса
    if not 0 < plan_id < 2 ** 31:
        return False
    async with db_helper.session_factory() as session:
        result = await session.execute(
            delete(UserPlan).where(UserPlan.id == plan_id, UserPlan.user_id == user_id)
        )
        await session.commit()
    return bool(result.rowcount)
