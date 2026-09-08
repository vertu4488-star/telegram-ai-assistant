"""Unit tests for bot handlers, utilities, rate limiting, and message chunking."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiogram.types import Message as TgMessage
from app.bot.handlers import split_message
from app.bot.middlewares import RateLimitMiddleware
from app.config import Settings


def test_split_message_short():
    """Verify short messages are not split."""
    text = "Hello world! This is a short response."
    chunks = split_message(text, max_chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_message_empty():
    """Verify empty text produces empty list."""
    assert split_message("") == []


def test_split_message_long_paragraphs():
    """Verify long text is split cleanly without exceeding max chunk size."""
    para1 = "A" * 60
    para2 = "B" * 60
    para3 = "C" * 60
    full_text = f"{para1}\n\n{para2}\n\n{para3}"

    chunks = split_message(full_text, max_chunk_size=100)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 100


def test_split_message_very_long_single_line():
    """Verify a single ultra-long string without newlines is safely chunked."""
    long_line = "X" * 250
    chunks = split_message(long_line, max_chunk_size=100)
    assert len(chunks) == 3
    assert len(chunks[0]) == 100
    assert len(chunks[1]) == 100
    assert len(chunks[2]) == 50


@pytest.mark.asyncio
async def test_rate_limiter_middleware_allows_normal_traffic():
    """Verify rate limiter allows messages within the rate threshold."""
    middleware = RateLimitMiddleware(rate_limit_per_minute=5)
    handler = AsyncMock(return_value="OK")

    mock_event = MagicMock()
    mock_event.from_user.id = 12345
    mock_event.from_user.is_bot = False

    # Send 5 messages -> all should pass through
    for _ in range(5):
        res = await middleware(handler, mock_event, {})
        assert res == "OK"

    assert handler.call_count == 5


@pytest.mark.asyncio
async def test_rate_limiter_middleware_blocks_burst():
    """Verify rate limiter blocks when threshold is exceeded."""
    middleware = RateLimitMiddleware(rate_limit_per_minute=2, notification_cooldown_seconds=1.0)
    handler = AsyncMock(return_value="OK")

    mock_event = MagicMock(spec=TgMessage)
    mock_event.from_user = MagicMock()
    mock_event.from_user.id = 77777
    mock_event.from_user.is_bot = False
    mock_event.answer = AsyncMock()

    # First 2 allowed
    assert await middleware(handler, mock_event, {}) == "OK"
    assert await middleware(handler, mock_event, {}) == "OK"
    assert handler.call_count == 2

    # 3rd is blocked
    res3 = await middleware(handler, mock_event, {})
    assert res3 is None
    assert handler.call_count == 2
    mock_event.answer.assert_called_once()
    assert "quickly" in mock_event.answer.call_args[0][0].lower()


def test_admin_authorization():
    """Verify admin check authorization logic."""
    conf = Settings(ADMIN_USER_ID=100999)  # type: ignore[arg-type]
    assert conf.is_admin(100999) is True
    assert conf.is_admin(999999) is False
