"""Unit tests for database models, repositories, and persistence logic."""

import pytest
from app.database.repository import MessageRepository, UserRepository


@pytest.mark.asyncio
async def test_user_upsert_and_retrieval(async_db_session):
    """Test creating and updating user profiles."""
    session = async_db_session

    # 1. Create new user
    user = await UserRepository.upsert_user(
        session=session,
        telegram_id=12345678,
        username="sokha_dev",
        first_name="Sokha",
        last_name="Chan",
        language_code="km",
    )
    await session.commit()

    assert user.id is not None
    assert user.telegram_id == 12345678
    assert user.username == "sokha_dev"
    assert user.first_name == "Sokha"
    assert user.language_code == "km"

    # 2. Update user info
    updated_user = await UserRepository.upsert_user(
        session=session,
        telegram_id=12345678,
        username="sokha_updated",
        first_name="Sokha (Pro)",
        last_name="Chan",
        language_code="en",
    )
    await session.commit()

    assert updated_user.id == user.id
    assert updated_user.username == "sokha_updated"
    assert updated_user.first_name == "Sokha (Pro)"
    assert updated_user.language_code == "en"

    # 3. Retrieve user
    fetched = await UserRepository.get_user_by_telegram_id(session, 12345678)
    assert fetched is not None
    assert fetched.username == "sokha_updated"


@pytest.mark.asyncio
async def test_message_persistence_and_history_limit(async_db_session):
    """Test saving messages and retrieving limited chronological history."""
    session = async_db_session
    user_id = 998877

    # Save 10 messages
    for i in range(1, 11):
        role = "user" if i % 2 != 0 else "assistant"
        await MessageRepository.save_message(
            session=session,
            telegram_id=user_id,
            role=role,
            content=f"Message {i}",
        )
    await session.commit()

    # Total count check
    total = await MessageRepository.get_total_messages_count(session)
    assert total == 10

    # Fetch last 4 messages -> should be oldest to newest: 7, 8, 9, 10
    history = await MessageRepository.get_recent_messages(session, user_id, limit=4)
    assert len(history) == 4
    assert [m.content for m in history] == ["Message 7", "Message 8", "Message 9", "Message 10"]
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_clear_conversation(async_db_session):
    """Test clearing conversation history for a specific user."""
    session = async_db_session
    user1 = 1001
    user2 = 1002

    await MessageRepository.save_message(session, user1, "user", "Hello 1")
    await MessageRepository.save_message(session, user1, "assistant", "Hi 1")
    await MessageRepository.save_message(session, user2, "user", "Hello 2")
    await session.commit()

    # Clear user1 history
    deleted = await MessageRepository.clear_history(session, user1)
    await session.commit()

    assert deleted == 2
    u1_history = await MessageRepository.get_recent_messages(session, user1)
    assert len(u1_history) == 0

    u2_history = await MessageRepository.get_recent_messages(session, user2)
    assert len(u2_history) == 1


@pytest.mark.asyncio
async def test_user_repository_stats(async_db_session):
    """Test admin stats calculation."""
    session = async_db_session

    await UserRepository.upsert_user(session, 1001, username="u1")
    await UserRepository.upsert_user(session, 1002, username="u2")
    await MessageRepository.save_message(session, 1001, "user", "Active user message")
    await session.commit()

    total_users = await UserRepository.get_total_users_count(session)
    assert total_users == 2

    active_users = await UserRepository.get_active_users_count(session, since_hours=24)
    assert active_users == 1

    recipients = await UserRepository.get_all_telegram_ids(session)
    assert set(recipients) == {1001, 1002}
