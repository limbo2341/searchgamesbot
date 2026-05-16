from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from bot.models import SearchHistory, Favorite, Payment, Referral, SupportTicket
import json
import logging

logger = logging.getLogger(__name__)


class SearchHistoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, user_id: int, search_query: str, result_game: Optional[str] = None) -> SearchHistory:
        entry = SearchHistory(
            user_id=user_id,
            search_query=search_query,
            result_game=result_game,
            created_at=datetime.utcnow(),
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def get_user_history(self, user_id: int, limit: int = 10) -> List[SearchHistory]:
        result = await self.session.execute(
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_total_count(self) -> int:
        result = await self.session.execute(select(func.count(SearchHistory.id)))
        return result.scalar_one()


class FavoriteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, user_id: int, game_id: str, game_name: str, game_data: dict) -> Favorite:
        fav = Favorite(
            user_id=user_id,
            game_id=game_id,
            game_name=game_name,
            game_data=json.dumps(game_data, ensure_ascii=False),
            created_at=datetime.utcnow(),
        )
        self.session.add(fav)
        await self.session.commit()
        await self.session.refresh(fav)
        return fav

    async def remove(self, user_id: int, game_id: str) -> bool:
        result = await self.session.execute(
            select(Favorite)
            .where(Favorite.user_id == user_id, Favorite.game_id == game_id)
        )
        fav = result.scalar_one_or_none()
        if fav:
            await self.session.delete(fav)
            await self.session.commit()
            return True
        return False

    async def get_user_favorites(self, user_id: int) -> List[Favorite]:
        result = await self.session.execute(
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .order_by(Favorite.created_at.desc())
        )
        return result.scalars().all()

    async def is_favorite(self, user_id: int, game_id: str) -> bool:
        result = await self.session.execute(
            select(Favorite)
            .where(Favorite.user_id == user_id, Favorite.game_id == game_id)
        )
        return result.scalar_one_or_none() is not None

    async def count_user_favorites(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
        )
        return result.scalar_one()


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        tariff: str,
        amount: int,
        payment_method: str,
    ) -> Payment:
        payment = Payment(
            user_id=user_id,
            tariff=tariff,
            amount=amount,
            payment_method=payment_method,
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def update_screenshot(self, payment_id: int, file_id: str) -> None:
        await self.session.execute(
            update(Payment).where(Payment.id == payment_id).values(screenshot_file_id=file_id)
        )
        await self.session.commit()

    async def approve(self, payment_id: int, admin_id: int) -> Optional[Payment]:
        await self.session.execute(
            update(Payment).where(Payment.id == payment_id).values(
                status="approved",
                approved_by=admin_id,
            )
        )
        await self.session.commit()
        return await self.get_by_id(payment_id)

    async def reject(self, payment_id: int, admin_id: int) -> Optional[Payment]:
        await self.session.execute(
            update(Payment).where(Payment.id == payment_id).values(
                status="rejected",
                approved_by=admin_id,
            )
        )
        await self.session.commit()
        return await self.get_by_id(payment_id)

    async def get_by_id(self, payment_id: int) -> Optional[Payment]:
        result = await self.session.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def get_pending(self) -> List[Payment]:
        result = await self.session.execute(
            select(Payment).where(Payment.status == "pending").order_by(Payment.created_at.desc())
        )
        return result.scalars().all()

    async def get_all(self, limit: int = 50) -> List[Payment]:
        result = await self.session.execute(
            select(Payment).order_by(Payment.created_at.desc()).limit(limit)
        )
        return result.scalars().all()


class ReferralRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, inviter_id: int, invited_id: int) -> Referral:
        referral = Referral(
            inviter_id=inviter_id,
            invited_id=invited_id,
            created_at=datetime.utcnow(),
        )
        self.session.add(referral)
        await self.session.commit()
        await self.session.refresh(referral)
        return referral

    async def exists(self, invited_id: int) -> bool:
        result = await self.session.execute(
            select(Referral).where(Referral.invited_id == invited_id)
        )
        return result.scalar_one_or_none() is not None

    async def count_by_inviter(self, inviter_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Referral.id)).where(Referral.inviter_id == inviter_id)
        )
        return result.scalar_one()


class SupportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, message: str) -> SupportTicket:
        ticket = SupportTicket(
            user_id=user_id,
            message=message,
            status="open",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(ticket)
        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def get_open(self) -> List[SupportTicket]:
        result = await self.session.execute(
            select(SupportTicket)
            .where(SupportTicket.status == "open")
            .order_by(SupportTicket.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_id(self, ticket_id: int) -> Optional[SupportTicket]:
        result = await self.session.execute(
            select(SupportTicket).where(SupportTicket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def close(self, ticket_id: int, admin_reply: str) -> None:
        await self.session.execute(
            update(SupportTicket).where(SupportTicket.id == ticket_id).values(
                status="closed",
                admin_reply=admin_reply,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()
