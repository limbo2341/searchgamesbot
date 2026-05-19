import asyncio
import logging
from datetime import datetime
from sqlalchemy import select, update
from bot.database import async_session_maker
from bot.models import User

logger = logging.getLogger(__name__)

async def expire_premium_job():
    """Знімає прострочений Premium у всіх юзерів."""
    try:
        async with async_session_maker() as session:
            now = datetime.utcnow()
            result = await session.execute(
                select(User).where(
                    User.premium_status == True,
                    User.premium_until != None,
                    User.premium_until < now
                )
            )
            expired = list(result.scalars().all())

            if expired:
                tids = [u.telegram_id for u in expired]
                await session.execute(
                    update(User).where(
                        User.premium_status == True,
                        User.premium_until != None,
                        User.premium_until < now
                    ).values(premium_status=False, premium_until=None)
                )
                await session.commit()
                logger.info(f"Premium expired for {len(expired)} users: {tids}")
            else:
                logger.debug("No expired premium users found")
    except Exception as e:
        logger.error(f"expire_premium_job error: {e}")

async def run_premium_scheduler(bot=None):
    """Запускає перевірку кожні 30 хвилин."""
    logger.info("Premium scheduler started")
    while True:
        await expire_premium_job()
        await asyncio.sleep(1800)  # 30 хвилин
