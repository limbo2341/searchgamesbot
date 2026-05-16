"""
bot_control.py — Вмикання/вимикання бота адміном.

Логіка:
- Redis зберігає ключ bot:disabled = "1" / відсутній
- Middleware перевіряє цей ключ перед кожним повідомленням
- При вимкненні: адмін пише причину → всім юзерам розсилається сповіщення
- При вмиканні: всім розсилається що бот знову працює
"""

import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.keyboards import bot_disable_confirm_keyboard, admin_main_keyboard, back_keyboard

logger = logging.getLogger(__name__)
router = Router()

# Redis ключ
BOT_DISABLED_KEY = "bot:disabled"
BOT_DISABLE_REASON_KEY = "bot:disable_reason"


class BotControlStates(StatesGroup):
    waiting_for_disable_reason = State()


# ── Утиліти Redis ──

async def is_bot_disabled(redis) -> bool:
    val = await redis.get(BOT_DISABLED_KEY)
    return val is not None


async def set_bot_disabled(redis, reason: str):
    await redis.set(BOT_DISABLED_KEY, "1")
    await redis.set(BOT_DISABLE_REASON_KEY, reason)


async def set_bot_enabled(redis):
    await redis.delete(BOT_DISABLED_KEY)
    await redis.delete(BOT_DISABLE_REASON_KEY)


async def get_disable_reason(redis) -> str:
    val = await redis.get(BOT_DISABLE_REASON_KEY)
    if val:
        return val.decode() if isinstance(val, bytes) else val
    return "Технічні роботи"


# ── Broadcast всім користувачам ──

async def broadcast_to_all(bot: Bot, text: str):
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        users = await user_repo.get_all_active()

    sent = 0
    failed = 0
    for user in users:
        try:
            await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    logger.info(f"Broadcast done: {sent} sent, {failed} failed")
    return sent, failed


# ── Колбеки адмін-панелі ──

@router.callback_query(F.data == "admin:bot:disable")
async def admin_bot_disable_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    # Перевіряємо чи бот вже вимкнений
    redis = callback.bot.redis if hasattr(callback.bot, "redis") else None
    if redis and await is_bot_disabled(redis):
        await callback.answer("⚠️ Бот вже вимкнений!", show_alert=True)
        return

    await state.set_state(BotControlStates.waiting_for_disable_reason)
    await callback.message.answer(
        "🔴 <b>Вимкнення бота</b>\n\n"
        "Напиши причину вимкнення.\n"
        "Це повідомлення отримають <b>всі користувачі</b>.\n\n"
        "<i>Або напиши /cancel щоб скасувати.</i>",
        parse_mode="HTML",
        reply_markup=back_keyboard("ua"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bot:enable")
async def admin_bot_enable(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    redis = callback.bot.redis if hasattr(callback.bot, "redis") else None
    if not redis:
        await callback.answer("❌ Redis недоступний", show_alert=True)
        return

    if not await is_bot_disabled(redis):
        await callback.answer("✅ Бот вже увімкнений!", show_alert=True)
        return

    await set_bot_enabled(redis)

    enable_text = (
        "✅ <b>Бот знову працює!</b>\n\n"
        "🎮 Можеш шукати ігри — все відновлено!"
    )
    sent, failed = await broadcast_to_all(callback.bot, enable_text)

    await callback.message.answer(
        f"✅ <b>Бот увімкнений!</b>\n"
        f"📨 Надіслано: {sent} | ❌ Помилок: {failed}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bot:cancel")
async def admin_bot_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Скасовано.", reply_markup=admin_main_keyboard())
    await callback.answer()


# ── Отримання причини вимкнення ──

@router.message(BotControlStates.waiting_for_disable_reason)
async def admin_bot_disable_reason(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return

    if message.text in ["← Назад", "🏠 Головне меню", "/cancel"]:
        await state.clear()
        await message.answer("❌ Скасовано.", reply_markup=admin_main_keyboard())
        return

    reason = message.text.strip()
    if len(reason) < 3:
        await message.answer("⚠️ Напиши причину (мінімум 3 символи).")
        return

    redis = message.bot.redis if hasattr(message.bot, "redis") else None
    if not redis:
        await message.answer("❌ Redis недоступний. Неможливо вимкнути бота.")
        await state.clear()
        return

    await set_bot_disabled(redis, reason)

    disable_text = (
        f"🔴 <b>Бот тимчасово вимкнений</b>\n\n"
        f"📋 <b>Причина:</b> {reason}\n\n"
        f"<i>Ми повідомимо коли бот знову запрацює.</i>"
    )
    sent, failed = await broadcast_to_all(message.bot, disable_text)

    await state.clear()
    await message.answer(
        f"🔴 <b>Бот вимкнено!</b>\n"
        f"📨 Надіслано: {sent} | ❌ Помилок: {failed}\n\n"
        f"<b>Причина:</b> {reason}\n\n"
        f"Щоб увімкнути — Admin Panel → 🟢 Увімкнути бота",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )
