"""User service orchestrating user data and statistics."""

from typing import Dict, List, Optional

from app.database.database import get_db_session
from app.database.models import User
from app.database.repository import MessageRepository, UserRepository


class UserService:
    """Service handling user management and admin statistics."""

    @staticmethod
    async def register_or_update_user(
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> User:
        """Register a user upon interaction or update their profile attributes."""
        async with get_db_session() as session:
            user = await UserRepository.upsert_user(
                session=session,
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )
            return user

    @staticmethod
    async def get_user(telegram_id: int) -> Optional[User]:
        """Fetch user by Telegram ID."""
        async with get_db_session() as session:
            return await UserRepository.get_user_by_telegram_id(session, telegram_id)

    @staticmethod
    async def get_broadcast_recipients() -> List[int]:
        """Get all registered user Telegram IDs for broadcast."""
        async with get_db_session() as session:
            return await UserRepository.get_all_telegram_ids(session)

    @staticmethod
    async def get_system_stats() -> Dict[str, int]:
        """Fetch statistics for admin dashboard."""
        async with get_db_session() as session:
            total_users = await UserRepository.get_total_users_count(session)
            total_messages = await MessageRepository.get_total_messages_count(session)
            active_users_24h = await UserRepository.get_active_users_count(
                session, since_hours=24
            )
            return {
                "total_users": total_users,
                "total_messages": total_messages,
                "active_users_24h": active_users_24h,
            }
