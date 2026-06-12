from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    waiting_for_partner = State()
    waiting_for_timezone = State()
    waiting_for_checkin_time = State()
    waiting_for_other_excuse = State()
    waiting_for_panic_reason = State()
    waiting_for_relapse_trigger_other = State()
    panic_chat = State()
    waiting_for_journal_entry = State()
    waiting_for_confession = State()
