"""
bot_disabled_middleware.py — блокує команди коли бот вимкнений.
"""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot.config import settings

BOT_DISABLED_KEY = "bot:disabled"
BOT_REASON_KEY = "bot:disable_reason"


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
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        # Адміни завжди проходять
        if user_id and user_id in settings.admin_ids:
            return await handler(event, data)

        # Перевірка Redis
        try:
            if self.redis:
                disabled = await self.redis.get(BOT_DISABLED_KEY)
                if disabled:
                    reason_raw = await self.redis.get(BOT_REASON_KEY)
                    reason = ""
                    if reason_raw:
                        reason = reason_raw.decode() if isinstance(reason_raw, bytes) else str(reason_raw)
                    if not reason:
                        reason = "Технічні роботи"

                    msg = (
                        f"🔴 <b>Бот тимчасово вимкнений</b>\n\n"
                        f"📋 Причина: {reason}\n\n"
                        f"<i>Ми повідомимо коли відновиться робота.</i>"
                    )
                    if isinstance(event, Message):
                        await event.answer(msg, parse_mode="HTML")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("🔴 Бот вимкнений.", show_alert=True)
                    return
        except Exception:
            pass  # Якщо Redis недоступний — пропускаємо

        return await handler(event, data)
