from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from bot.models import User
import logging

logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        language: str = "en",
        invited_by: Optional[int] = None,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language=language,
            invited_by=invited_by,
            registration_date=datetime.utcnow(),
            last_search_reset=datetime.utcnow(),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_or_create(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        language: str = "en",
        invited_by: Optional[int] = None,
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False
        user = await self.create(telegram_id, username, first_name, language, invited_by)
        return user, True

    async def update_language(self, telegram_id: int, language: str) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(language=language)
        )
        await self.session.commit()

    async def update_username(self, telegram_id: int, username: str, first_name: str) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(
                username=username, first_name=first_name
            )
        )
        await self.session.commit()

    async def increment_search_count(self, telegram_id: int) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return
        now = datetime.utcnow()
        if user.last_search_reset is None or (now - user.last_search_reset).days >= 1:
            await self.session.execute(
                update(User).where(User.telegram_id == telegram_id).values(
                    daily_search_count=1,
                    last_search_reset=now,
                )
            )
        else:
            await self.session.execute(
                update(User).where(User.telegram_id == telegram_id).values(
                    daily_search_count=User.daily_search_count + 1
                )
            )
        await self.session.commit()

    async def can_search(self, telegram_id: int, free_limit: int = 2) -> bool:
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return False
        if user.is_banned:
            return False
        if user.premium_status:
            if user.premium_until and user.premium_until < datetime.utcnow():
                await self.remove_premium(telegram_id)
            else:
                return True
        now = datetime.utcnow()
        if user.last_search_reset is None or (now - user.last_search_reset).days >= 1:
            return True
        return user.daily_search_count < free_limit

    async def set_premium(self, telegram_id: int, days: Optional[int] = None) -> None:
        if days is None:
            premium_until = None
        else:
            premium_until = datetime.utcnow() + timedelta(days=days)
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(
                premium_status=True,
                premium_until=premium_until,
            )
        )
        await self.session.commit()

    async def remove_premium(self, telegram_id: int) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(
                premium_status=False,
                premium_until=None,
            )
        )
        await self.session.commit()

    async def ban_user(self, telegram_id: int) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(is_banned=True)
        )
        await self.session.commit()

    async def unban_user(self, telegram_id: int) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(is_banned=False)
        )
        await self.session.commit()

    async def increment_referrals(self, telegram_id: int) -> int:
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return 0
        new_count = user.referrals_count + 1
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(
                referrals_count=new_count
            )
        )
        await self.session.commit()
        return new_count

    async def get_all_users(self) -> List[User]:
        result = await self.session.execute(select(User))
        return result.scalars().all()

    async def get_total_count(self) -> int:
        result = await self.session.execute(select(func.count(User.id)))
        return result.scalar_one()

    async def get_premium_count(self) -> int:
        result = await self.session.execute(
            select(func.count(User.id)).where(User.premium_status == True)
        )
        return result.scalar_one()
