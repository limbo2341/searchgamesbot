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
from bot.database.engine import set_redis
from bot.handlers import get_all_routers
from bot.utils.premium_scheduler import run_premium_scheduler
from bot.middlewares.subscription_middleware import SubscriptionMiddleware
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
        # Зберігаємо redis в engine для використання в handlers
        set_redis(redis_client)
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis not available ({e}), using MemoryStorage.")
        storage = MemoryStorage()
        redis_client = None

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)

    # BotDisabled middleware першим
    if redis_client:
        dp.message.middleware(BotDisabledMiddleware(redis_client))
        dp.callback_query.middleware(BotDisabledMiddleware(redis_client))

    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.message.middleware(AntiSpamMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(AntiSpamMiddleware(rate_limit=0.3))
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(get_all_routers())

    logger.info("Bot started! Polling...")
    try:
        asyncio.create_task(run_premium_scheduler(bot))
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        if redis_client:
            await redis_client.aclose()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
