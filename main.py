import asyncio
import logging
import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database import create_tables
from bot.handlers import get_all_routers
from bot.middlewares import DatabaseMiddleware, AntiSpamMiddleware, BanCheckMiddleware
from bot.middlewares.bot_disabled_middleware import BotDisabledMiddleware
from bot.utils import setup_logging

logger = setup_logging()


async def main():
    logger.info("Starting IgroMemory bot...")

    await create_tables()
    logger.info("Database ready.")

    # Redis
    redis_client = None
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
        await redis_client.ping()
        storage = RedisStorage.from_url(settings.redis_url)
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis not available ({e}), using MemoryStorage.")
        storage = MemoryStorage()
        redis_client = None

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Прикріплюємо redis до bot щоб handlers могли його використати
    if redis_client:
        bot.redis = redis_client

    dp = Dispatcher(storage=storage)

    # Middlewares — BotDisabled першим для message та callback
    if redis_client:
        dp.message.middleware(BotDisabledMiddleware(redis_client))
        dp.callback_query.middleware(BotDisabledMiddleware(redis_client))

    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.message.middleware(AntiSpamMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(AntiSpamMiddleware(rate_limit=0.3))
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())

    dp.include_router(get_all_routers())

    logger.info("Bot started! Polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        if redis_client:
            await redis_client.aclose()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
