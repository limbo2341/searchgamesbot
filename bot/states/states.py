from aiogram.fsm.state import State, StatesGroup


class LanguageSetup(StatesGroup):
    choosing_language = State()


class SearchStates(StatesGroup):
    waiting_for_description = State()
    showing_results = State()
    waiting_for_screenshot = State()
    clarifying = State()


class SupportStates(StatesGroup):
    waiting_for_message = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_user_id = State()
    waiting_for_premium_days = State()
    waiting_for_support_reply = State()
    waiting_for_ticket_id = State()


class PaymentStates(StatesGroup):
    choosing_tariff = State()
    choosing_method = State()
    waiting_for_screenshot = State()


class AIChatStates(StatesGroup):
    chatting = State()


class BotControlStates(StatesGroup):
    waiting_for_disable_reason = State()
