from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from bot.config import settings
import logging
logger = logging.getLogger(__name__)
class Base(DeclarativeBase):
    pass
engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://").replace("postgres://", "postgresql+asyncpg://"),
    echo=False, pool_size=10, max_overflow=20, pool_pre_ping=True,
)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")
async def close_db():
    await engine.dispose()
_redis_client = None
def set_redis(redis):
    global _redis_client
    _redis_client = redis
async def get_redis():
    global _redis_client
    if _redis_client:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=False)
        await r.ping()
        _redis_client = r
        return r
    except Exception as e:
        logger.error(f"get_redis failed: {e}")
        return None
