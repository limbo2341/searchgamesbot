"""
bot_disabled_middleware.py — Middleware для вимкненого бота.
Якщо бот вимкнений адміном — звичайні юзери отримують повідомлення про це.
Адміни можуть користуватись ботом завжди.
"""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot.config import settings

BOT_DISABLED_KEY = "bot:disabled"
BOT_DISABLE_REASON_KEY = "bot:disable_reason"


class BotDisabledMiddleware(BaseMiddleware):
    def __init__(self, redis):
        self.redis = redis
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Отримуємо user_id
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        # Адміни завжди проходять
        if user_id and user_id in settings.admin_ids:
            return await handler(event, data)

        # Перевіряємо чи бот вимкнений
        try:
            is_disabled = await self.redis.get(BOT_DISABLED_KEY)
            if is_disabled:
                reason_raw = await self.redis.get(BOT_DISABLE_REASON_KEY)
                reason = (
                    reason_raw.decode() if isinstance(reason_raw, bytes)
                    else (reason_raw or "Технічні роботи")
                )
                msg = (
                    f"🔴 <b>Бот тимчасово вимкнений</b>\n\n"
                    f"📋 Причина: {reason}\n\n"
                    f"<i>Ми повідомимо коли відновиться робота.</i>"
                )
                if isinstance(event, Message):
                    await event.answer(msg, parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🔴 Бот вимкнений. Зачекай.", show_alert=True)
                return  # Не передаємо далі
        except Exception:
            pass  # Якщо Redis недоступний — пропускаємо

        return await handler(event, data)
