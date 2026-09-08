"""Middlewares for user tracking and rate limiting."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserTrackingMiddleware(BaseMiddleware):
    """Middleware that automatically upserts user profile data on each incoming interaction."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if from_user and not from_user.is_bot:
            try:
                await UserService.register_or_update_user(
                    telegram_id=from_user.id,
                    username=from_user.username,
                    first_name=from_user.first_name,
                    last_name=from_user.last_name,
                    language_code=from_user.language_code,
                )
            except Exception as exc:
                logger.error("Failed to track user %d in middleware: %s", from_user.id, exc)

        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """In-memory sliding-window rate limiter per user."""

    def __init__(
        self,
        rate_limit_per_minute: int | None = None,
        notification_cooldown_seconds: float = 10.0,
    ) -> None:
        self.limit = rate_limit_per_minute or settings.RATE_LIMIT_MESSAGES_PER_MINUTE
        self.notification_cooldown = notification_cooldown_seconds
        # Mapping: user_id -> list of unix timestamps
        self._user_timestamps: Dict[int, List[float]] = defaultdict(list)
        # Mapping: user_id -> last rate-limit warning timestamp
        self._last_warning: Dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Only rate-limit Message events (or CallbackQueries if needed)
        from_user = getattr(event, "from_user", None)
        if not from_user or from_user.is_bot:
            return await handler(event, data)

        # Bypass rate limiter for admin
        if settings.is_admin(from_user.id):
            return await handler(event, data)

        user_id = from_user.id
        now = time.time()
        window_start = now - 60.0

        async with self._lock:
            # Clean timestamps older than 60s
            timestamps = [t for t in self._user_timestamps[user_id] if t > window_start]
            self._user_timestamps[user_id] = timestamps

            if len(timestamps) >= self.limit:
                last_warn = self._last_warning.get(user_id, 0.0)
                if (now - last_warn) > self.notification_cooldown:
                    self._last_warning[user_id] = now
                    warning_text = (
                        "⚠️ You're sending messages too quickly. "
                        "Please wait a moment and try again."
                    )
                    if isinstance(event, Message):
                        await event.answer(warning_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(warning_text, show_alert=True)
                return  # Drop handling

            # Record this event timestamp
            self._user_timestamps[user_id].append(now)

        return await handler(event, data)
