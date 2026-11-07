"""Application configuration loaded from environment variables."""

from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required Credentials
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram bot token obtained from @BotFather")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key")

    # AI Model Settings
    GEMINI_MODEL: str = Field(
        default="gemini-3.8-flash",
        description="Primary Gemini model identifier",
    )
    GEMINI_FALLBACK_MODEL: str = Field(
        default="gemini-3.5-flash-lite",
        description="Fallback Gemini model used when the primary model is temporarily unavailable",
    )

    # Channel news publishing settings
    NEWS_CHANNEL_USERNAME: str = Field(default="@New_Iphone_Service", description="Telegram channel username for automated news posts")
    NEWS_PUBLISH_SECRET: str = Field(default="", description="Shared secret required to trigger scheduled news publishing")

    # Storage Settings
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./bot.db", description="Database connection URL")

    # Admin Settings
    ADMIN_USER_ID: Optional[int] = Field(default=None, description="Telegram ID of the primary administrator")

    # Behavior Settings
    MAX_HISTORY_MESSAGES: int = Field(default=20, ge=1, le=100)
    RATE_LIMIT_MESSAGES_PER_MINUTE: int = Field(default=10, ge=1, le=120)
    REQUEST_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=120)

    @field_validator("ADMIN_USER_ID", mode="before")
    @classmethod
    def parse_admin_id(cls, value: object) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return None

    def is_admin(self, telegram_id: int) -> bool:
        return self.ADMIN_USER_ID is not None and self.ADMIN_USER_ID == telegram_id

    def __repr__(self) -> str:
        backend = self.DATABASE_URL.split(":", 1)[0].split("+", 1)[0].lower()
        return (f"<Settings model={self.GEMINI_MODEL!r} fallback_model={self.GEMINI_FALLBACK_MODEL!r} "
                f"telegram_configured={bool(self.TELEGRAM_BOT_TOKEN)} gemini_configured={bool(self.GEMINI_API_KEY)} "
                f"database_backend={backend!r} admin_configured={self.ADMIN_USER_ID is not None}>")


settings = Settings()
