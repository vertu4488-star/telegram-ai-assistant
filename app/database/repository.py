"""Repository layer for database operations on Users and Messages."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Message, User, utc_now


class UserRepository:
    """Repository handling database queries for User entities."""

    @staticmethod
    async def upsert_user(
        session: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> User:
        """Create a new user or update an existing user's profile."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.language_code = language_code
            user.updated_at = utc_now()

        await session.flush()
        return user

    @staticmethod
    async def get_user_by_telegram_id(
        session: AsyncSession, telegram_id: int
    ) -> Optional[User]:
        """Fetch user by Telegram ID."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_telegram_ids(session: AsyncSession) -> List[int]:
        """Return a list of all registered Telegram IDs for broadcasting."""
        stmt = select(User.telegram_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_total_users_count(session: AsyncSession) -> int:
        """Get total count of registered users."""
        stmt = select(func.count(User.id))
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def get_active_users_count(
        session: AsyncSession, since_hours: int = 24
    ) -> int:
        """Count distinct users who sent messages in the last N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        stmt = select(func.count(func.distinct(Message.telegram_id))).where(
            Message.created_at >= cutoff
        )
        result = await session.execute(stmt)
        return result.scalar() or 0


class MessageRepository:
    """Repository handling database queries for conversation Messages."""

    @staticmethod
    async def save_message(
        session: AsyncSession,
        telegram_id: int,
        role: str,
        content: str,
    ) -> Message:
        """Persist a conversation message turn."""
        msg = Message(
            telegram_id=telegram_id,
            role=role,
            content=content,
            created_at=utc_now(),
        )
        session.add(msg)
        await session.flush()
        return msg

    @staticmethod
    async def get_recent_messages(
        session: AsyncSession,
        telegram_id: int,
        limit: int = 20,
    ) -> Sequence[Message]:
        """Fetch the most recent N messages for a user, ordered chronologically (oldest to newest)."""
        stmt = (
            select(Message)
            .where(Message.telegram_id == telegram_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()  # Reverse to get oldest -> newest order
        return messages

    @staticmethod
    async def clear_history(session: AsyncSession, telegram_id: int) -> int:
        """Delete conversation history for a user. Returns number of rows deleted."""
        stmt = delete(Message).where(Message.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.rowcount or 0

    @staticmethod
    async def get_total_messages_count(session: AsyncSession) -> int:
        """Get total number of messages stored in the database."""
        stmt = select(func.count(Message.id))
        result = await session.execute(stmt)
        return result.scalar() or 0
