"""
bot_control.py — Вмикання/вимикання бота адміном.
"""

import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.keyboards import admin_main_keyboard, back_keyboard

logger = logging.getLogger(__name__)
router = Router()

BOT_DISABLED_KEY = "bot:disabled"
BOT_REASON_KEY = "bot:disable_reason"


class BotControlStates(StatesGroup):
    waiting_for_disable_reason = State()


async def _get_redis():
    """Отримує Redis з engine."""
    try:
        from bot.database.engine import get_redis
        return await get_redis()
    except Exception:
        try:
            import redis.asyncio as aioredis
            from bot.config import settings
            r = aioredis.from_url(settings.redis_url, decode_responses=False)
            await r.ping()
            return r
        except Exception as e:
            logger.error(f"Cannot get Redis: {e}")
            return None


async def is_bot_disabled() -> bool:
    redis = await _get_redis()
    if not redis:
        return False
    try:
        return await redis.get(BOT_DISABLED_KEY) is not None
    except Exception:
        return False


async def get_disable_reason() -> str:
    redis = await _get_redis()
    if not redis:
        return "Технічні роботи"
    try:
        val = await redis.get(BOT_REASON_KEY)
        if val:
            return val.decode() if isinstance(val, bytes) else str(val)
    except Exception:
        pass
    return "Технічні роботи"


async def broadcast_all(bot: Bot, text: str) -> tuple[int, int]:
    async with async_session_maker() as session:
        users = await UserRepository(session).get_all_active()
    sent = failed = 0
    for user in users:
        try:
            await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    return sent, failed


# ── Вимкнути бота ──

@router.callback_query(F.data == "admin:bot:disable")
async def btn_disable(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    if await is_bot_disabled():
        await callback.answer("⚠️ Бот вже вимкнений!", show_alert=True)
        return

    await state.set_state(BotControlStates.waiting_for_disable_reason)
    await callback.message.answer(
        "🔴 <b>Вимкнення бота</b>\n\n"
        "Напиши причину вимкнення.\n"
        "Всі користувачі отримають це повідомлення.\n\n"
        "<i>Напиши /cancel щоб скасувати.</i>",
        parse_mode="HTML",
        reply_markup=back_keyboard("ua"),
    )
    await callback.answer()


@router.message(BotControlStates.waiting_for_disable_reason)
async def receive_disable_reason(message: Message, state: FSMContext):
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

    redis = await _get_redis()
    if not redis:
        await message.answer("❌ Redis недоступний.")
        await state.clear()
        return

    await redis.set(BOT_DISABLED_KEY, "1")
    await redis.set(BOT_REASON_KEY, reason.encode())

    text = (
        f"🔴 <b>Бот тимчасово вимкнений</b>\n\n"
        f"📋 Причина: {reason}\n\n"
        f"<i>Повідомимо коли відновиться робота.</i>"
    )
    sent, failed = await broadcast_all(message.bot, text)

    await state.clear()
    await message.answer(
        f"🔴 <b>Бот вимкнено!</b>\n"
        f"📨 Надіслано: {sent} | ❌ Помилок: {failed}\n\n"
        f"<b>Причина:</b> {reason}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


# ── Увімкнути бота ──

@router.callback_query(F.data == "admin:bot:enable")
async def btn_enable(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    if not await is_bot_disabled():
        await callback.answer("✅ Бот вже увімкнений!", show_alert=True)
        return

    redis = await _get_redis()
    if not redis:
        await callback.answer("❌ Redis недоступний", show_alert=True)
        return

    await redis.delete(BOT_DISABLED_KEY)
    await redis.delete(BOT_REASON_KEY)

    text = "✅ <b>Бот знову працює!</b>\n\n🎮 Можеш шукати ігри — все відновлено!"
    sent, failed = await broadcast_all(callback.bot, text)

    await callback.message.answer(
        f"✅ <b>Бот увімкнений!</b>\n📨 Надіслано: {sent} | ❌ Помилок: {failed}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bot:cancel")
async def btn_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Скасовано.", reply_markup=admin_main_keyboard())
    await callback.answer()
