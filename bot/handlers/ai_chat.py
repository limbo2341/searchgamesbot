"""
ai_chat.py — Вільний чат з Gemini.

Ліміти:
- Звичайні користувачі: 5 повідомлень на день
- Premium + Admin: безліміт
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.keyboards import back_keyboard, main_menu_keyboard, ai_chat_keyboard
from bot.services.ai_service import _call_gemini

logger = logging.getLogger(__name__)
router = Router()

FREE_CHAT_DAILY_LIMIT = 5

CHAT_BTN = [
    "🤖 AI Чат", "🤖 AI Чат (ліміт)", "🤖 AI Chat",
    "🤖 AI Chat (limited)", "🤖 AI Чат (обмежено)",
]

CHAT_SYSTEM_PROMPT = """You are a friendly gaming assistant. You love all types of games — mobile, PC, console, retro.
You help users:
- Discuss games, recommend new ones
- Answer questions about games, mechanics, cheats, guides
- Share interesting gaming facts

LANGUAGE RULE: Always reply in the same language the user uses.
Keep responses concise and friendly. Use emojis occasionally."""


class AIChatStates(StatesGroup):
    chatting = State()


async def get_user_info(telegram_id: int):
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user


# ── Вхід у чат ──

@router.message(F.text.in_(CHAT_BTN))
async def start_ai_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user_info(message.from_user.id)
    if not user:
        await message.answer("❌ Профіль не знайдено.")
        return

    lang = user.language
    is_admin = message.from_user.id in settings.admin_ids
    is_premium = user.premium_status

    # Перевіряємо ліміт для звичайних юзерів
    if not is_premium and not is_admin:
        chat_count = await _get_chat_count(message.from_user.id)
        remaining = max(0, FREE_CHAT_DAILY_LIMIT - chat_count)
        if remaining <= 0:
            await message.answer(
                f"⚠️ <b>Денний ліміт чату вичерпано</b>\n\n"
                f"Безкоштовно доступно {FREE_CHAT_DAILY_LIMIT} повідомлень на день.\n"
                f"Купи <b>Premium</b> для безлімітного чату! ⭐",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium),
            )
            return
        limit_text = f"\n💬 <i>Залишилось повідомлень сьогодні: {remaining}/{FREE_CHAT_DAILY_LIMIT}</i>"
    else:
        limit_text = "\n💬 <i>Безліміт ⭐</i>"

    welcome = {
        "ua": f"🤖 <b>AI Чат з Gemini</b>\n\nПривіт! Я готовий поговорити про ігри, порадити щось цікаве або відповісти на питання.{limit_text}\n\n<i>Напиши /stop або натисни «Назад» щоб вийти.</i>",
        "ru": f"🤖 <b>AI Чат с Gemini</b>\n\nПривет! Готов поговорить об играх, порекомендовать что-то интересное.{limit_text}\n\n<i>Напиши /stop или нажми «Назад» для выхода.</i>",
        "en": f"🤖 <b>AI Chat with Gemini</b>\n\nHey! Ready to talk about games, give recommendations or answer questions.{limit_text}\n\n<i>Type /stop or press Back to exit.</i>",
    }

    await state.set_state(AIChatStates.chatting)
    await state.update_data(chat_history=[], chat_count_session=0)

    await message.answer(
        welcome.get(lang, welcome["en"]),
        parse_mode="HTML",
        reply_markup=back_keyboard(lang),
    )


# ── Повідомлення в чаті ──

@router.message(AIChatStates.chatting)
async def process_ai_chat(message: Message, state: FSMContext):
    ALL_BACK = ["← Back", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]
    if message.text in ALL_BACK or message.text == "/stop":
        user = await get_user_info(message.from_user.id)
        lang = user.language if user else "en"
        is_admin = message.from_user.id in settings.admin_ids
        is_premium = user.premium_status if user else False
        await state.clear()
        await message.answer(
            "👋 Вийшов з чату." if lang == "ua" else "👋 Exited chat.",
            reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium),
        )
        return

    user = await get_user_info(message.from_user.id)
    if not user:
        return

    lang = user.language
    is_admin = message.from_user.id in settings.admin_ids
    is_premium = user.premium_status

    # Перевірка ліміту для безкоштовних
    if not is_premium and not is_admin:
        chat_count = await _get_chat_count(message.from_user.id)
        if chat_count >= FREE_CHAT_DAILY_LIMIT:
            await state.clear()
            await message.answer(
                f"⚠️ Ліміт {FREE_CHAT_DAILY_LIMIT} повідомлень на день вичерпано.\n"
                f"Купи <b>Premium</b> для безліміту! ⭐",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium),
            )
            return
        await _increment_chat_count(message.from_user.id)

    data = await state.get_data()
    history: list = data.get("chat_history", [])

    # Додаємо системний промпт якщо це перше повідомлення
    if not history:
        history = [{"role": "user", "content": f"[System: {CHAT_SYSTEM_PROMPT}]\n\n{message.text}"}]
    else:
        history.append({"role": "user", "content": message.text})

    typing_msg = await message.answer("✍️ Думаю...")

    raw = await _call_gemini(history)

    await typing_msg.delete()

    if raw is None:
        await message.answer(
            "😕 Gemini не відповідає. Спробуй ще раз." if lang == "ua"
            else "😕 Gemini is unavailable. Try again.",
        )
        return

    # Зберігаємо відповідь в історію
    history.append({"role": "model", "content": raw})

    # Обрізаємо до 20 останніх повідомлень
    if len(history) > 20:
        history = history[-20:]

    await state.update_data(chat_history=history)

    # Показуємо ліміт для безкоштовних
    if not is_premium and not is_admin:
        new_count = await _get_chat_count(message.from_user.id)
        remaining = max(0, FREE_CHAT_DAILY_LIMIT - new_count)
        footer = f"\n\n💬 <i>Залишилось: {remaining}/{FREE_CHAT_DAILY_LIMIT}</i>"
        await message.answer(raw + footer, parse_mode="HTML", reply_markup=back_keyboard(lang))
    else:
        await message.answer(raw, parse_mode="HTML", reply_markup=back_keyboard(lang))


# ── Очистити історію ──

@router.callback_query(F.data == "aichat:clear")
async def clear_chat_history(callback: CallbackQuery, state: FSMContext):
    await state.update_data(chat_history=[])
    await callback.answer("🗑️ Історію очищено!", show_alert=False)


# ── Redis лічильник чату ──

async def _get_chat_count(telegram_id: int) -> int:
    try:
        from bot.database.engine import get_redis
        redis = await get_redis()
        key = f"chat_count:{telegram_id}:{__import__('datetime').date.today()}"
        val = await redis.get(key)
        return int(val) if val else 0
    except Exception:
        return 0


async def _increment_chat_count(telegram_id: int):
    try:
        from bot.database.engine import get_redis
        redis = await get_redis()
        key = f"chat_count:{telegram_id}:{__import__('datetime').date.today()}"
        await redis.incr(key)
        await redis.expire(key, 86400)  # 24 години
    except Exception:
        pass
