import time
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from collections import defaultdict
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.config import settings

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session_maker() as session:
            data["session"] = session
            data["user_repo"] = UserRepository(session)
            return await handler(event, data)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        self.last_time: Dict[int, float] = defaultdict(float)
        self.warnings: Dict[int, int] = defaultdict(int)

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

        if user_id:
            now = time.time()
            if now - self.last_time[user_id] < self.rate_limit:
                self.warnings[user_id] += 1
                if self.warnings[user_id] > 3:
                    logger.warning(f"Spam detected from user {user_id}")
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ Too fast! Please slow down.", show_alert=False)
                return
            else:
                self.warnings[user_id] = 0
            self.last_time[user_id] = now

        return await handler(event, data)


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_repo: UserRepository = data.get("user_repo")
        user_id = None

        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and user_repo:
            user = await user_repo.get_by_telegram_id(user_id)
            if user and user.is_banned:
                if isinstance(event, Message):
                    await event.answer("🚫 You are banned from using this bot.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 You are banned.", show_alert=True)
                return

        return await handler(event, data)
