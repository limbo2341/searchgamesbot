import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database import create_tables
from bot.handlers import get_all_routers
from bot.middlewares import DatabaseMiddleware, AntiSpamMiddleware, BanCheckMiddleware
from bot.utils import setup_logging

logger = setup_logging()


async def main():
    logger.info("Starting IgroMemory bot...")

    # Create DB tables
    await create_tables()
    logger.info("Database ready.")

    # Setup storage
    try:
        storage = RedisStorage.from_url(settings.redis_url)
        logger.info("Redis storage connected.")
    except Exception as e:
        logger.warning(f"Redis not available ({e}), using MemoryStorage.")
        storage = MemoryStorage()

    # Bot & Dispatcher
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Middlewares
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.message.middleware(AntiSpamMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(AntiSpamMiddleware(rate_limit=0.3))
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())

    # Routers
    dp.include_router(get_all_routers())

    # Start polling
    logger.info("Bot started! Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
