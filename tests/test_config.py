"""Unit tests for configuration loading and validation."""

import pytest
from app.config import Settings


def test_default_settings():
    """Verify default configuration values."""
    s = Settings(
        TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        GEMINI_API_KEY="AIzaSyTestApiKey123456789012345678",
    )
    assert s.GEMINI_MODEL == "gemini-3.7-flash"
    assert s.MAX_HISTORY_MESSAGES == 20
    assert s.RATE_LIMIT_MESSAGES_PER_MINUTE == 10
    assert s.REQUEST_TIMEOUT_SECONDS == 30
    assert s.ADMIN_USER_ID is None
    assert not s.is_admin(12345)


def test_admin_user_id_parsing():
    """Verify parsing of admin user ID from string and int."""
    s1 = Settings(ADMIN_USER_ID=987654321)  # type: ignore[arg-type]
    assert s1.ADMIN_USER_ID == 987654321
    assert s1.is_admin(987654321)
    assert not s1.is_admin(111111)

    s2 = Settings(ADMIN_USER_ID="555444333")  # type: ignore[arg-type]
    assert s2.ADMIN_USER_ID == 555444333

    s3 = Settings(ADMIN_USER_ID="")  # type: ignore[arg-type]
    assert s3.ADMIN_USER_ID is None


def test_sensitive_masking_in_repr():
    """Verify that tokens and keys are never printed in plaintext in repr."""
    raw_token = "123456789:ABCdefGhIJklmnOpQRstUVwxYZ"
    raw_key = "AIzaSySecretApiKey1234567890abcdef"
    s = Settings(TELEGRAM_BOT_TOKEN=raw_token, GEMINI_API_KEY=raw_key)
    repr_str = repr(s)

    assert raw_token not in repr_str
    assert raw_key not in repr_str
    assert "..." in repr_str
