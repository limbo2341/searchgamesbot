import logging
from datetime import date
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.keyboards import back_keyboard, main_menu_keyboard
from bot.services.ai_service import chat_with_gemini

logger = logging.getLogger(__name__)
router = Router()
FREE_LIMIT = 5
CHAT_BTN = ["🤖 AI Чат", "🤖 AI Чат (ліміт)", "🤖 AI Chat", "🤖 AI Chat (limited)", "🤖 AI Чат (обмежено)"]
ALL_BACK = ["← Back", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]

class AIChatStates(StatesGroup):
    chatting = State()

async def _get_user(tid):
    async with async_session_maker() as session:
        return await UserRepository(session).get_by_telegram_id(tid)

async def _get_count(tid):
    try:
        from bot.database.engine import get_redis
        r = await get_redis()
        v = await r.get(f"chat:{tid}:{date.today()}")
        return int(v) if v else 0
    except Exception:
        return 0

async def _inc_count(tid):
    try:
        from bot.database.engine import get_redis
        r = await get_redis()
        k = f"chat:{tid}:{date.today()}"
        await r.incr(k)
        await r.expire(k, 86400)
    except Exception:
        pass

@router.message(F.text.in_(CHAT_BTN))
async def start_chat(message: Message, state: FSMContext):
    await state.clear()
    user = await _get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Профіль не знайдено.")
        return
    lang = user.language
    is_admin = message.from_user.id in settings.admin_ids
    is_premium = user.premium_status
    if not is_premium and not is_admin:
        count = await _get_count(message.from_user.id)
        remaining = max(0, FREE_LIMIT - count)
        if remaining <= 0:
            await message.answer(f"⚠️ <b>Ліміт чату вичерпано</b>\n\nДоступно {FREE_LIMIT} повідомлень/день.\nКупи <b>Premium</b> для безліміту! ⭐", parse_mode="HTML", reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium))
            return
        limit_info = f"\n💬 <i>Залишилось: {remaining}/{FREE_LIMIT}</i>"
    else:
        limit_info = "\n💬 <i>Безліміт ⭐</i>"
    msgs = {"ua": f"🤖 <b>AI Чат з Gemini</b>\n\nПривіт! Готовий говорити про ігри.{limit_info}\n\n<i>← Назад щоб вийти.</i>", "ru": f"🤖 <b>AI Чат с Gemini</b>\n\nПривет!{limit_info}\n\n<i>← Назад для выхода.</i>", "en": f"🤖 <b>AI Chat</b>\n\nHey! Ready to talk games.{limit_info}\n\n<i>← Back to exit.</i>"}
    await state.set_state(AIChatStates.chatting)
    await state.update_data(history=[])
    await message.answer(msgs.get(lang, msgs["en"]), parse_mode="HTML", reply_markup=back_keyboard(lang))

@router.message(AIChatStates.chatting)
async def process_chat(message: Message, state: FSMContext):
    if message.text in ALL_BACK or message.text == "/stop":
        user = await _get_user(message.from_user.id)
        lang = user.language if user else "en"
        is_admin = message.from_user.id in settings.admin_ids
        is_premium = user.premium_status if user else False
        await state.clear()
        await message.answer("👋 Вийшов з чату." if lang == "ua" else "👋 Exited.", reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium))
        return
    user = await _get_user(message.from_user.id)
    if not user:
        return
    lang = user.language
    is_admin = message.from_user.id in settings.admin_ids
    is_premium = user.premium_status
    if not is_premium and not is_admin:
        count = await _get_count(message.from_user.id)
        if count >= FREE_LIMIT:
            await state.clear()
            await message.answer(f"⚠️ Ліміт {FREE_LIMIT} повідомлень/день.\nКупи <b>Premium</b>! ⭐", parse_mode="HTML", reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium))
            return
        await _inc_count(message.from_user.id)
    data = await state.get_data()
    history = data.get("history", [])
    history.append({"role": "user", "content": message.text})
    typing = await message.answer("✍️ Думаю...")
    response = await chat_with_gemini(history)
    await typing.delete()
    if response is None:
        await message.answer("😕 Gemini не відповідає. Спробуй ще раз." if lang == "ua" else "😕 Try again.")
        return
    history.append({"role": "model", "content": response})
    if len(history) > 20:
        history = history[-20:]
    await state.update_data(history=history)
    if not is_premium and not is_admin:
        new_count = await _get_count(message.from_user.id)
        remaining = max(0, FREE_LIMIT - new_count)
        await message.answer(response + f"\n\n<i>💬 Залишилось: {remaining}/{FREE_LIMIT}</i>", parse_mode="HTML", reply_markup=back_keyboard(lang))
    else:
        await message.answer(response, parse_mode="HTML", reply_markup=back_keyboard(lang))

@router.callback_query(F.data == "aichat:clear")
async def clear_hist(callback: CallbackQuery, state: FSMContext):
    await state.update_data(history=[])
    await callback.answer("🗑️ Очищено!")
