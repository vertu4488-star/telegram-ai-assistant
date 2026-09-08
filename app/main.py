"""Application entry point and bot lifecycle management."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Message

from app.ai.gemini import gemini_service
from app.bot.commands import setup_bot_commands
from app.bot.handlers import router as bot_router
from app.bot.middlewares import RateLimitMiddleware, UserTrackingMiddleware
from app.config import settings
from app.database.database import close_db, init_db
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent) -> bool:
    """Global error handler for unhandled Telegram update exceptions."""
    logger.exception("Unhandled error in Telegram update processing: %s", event.exception)

    if event.update.message and isinstance(event.update.message, Message):
        try:
            await event.update.message.answer(
                "⚠️ An unexpected error occurred while processing your message. "
                "Please try again later."
            )
        except Exception:
            pass  # Suppress failure to notify user

    # Return True to indicate error was handled
    return True


def build_dispatcher() -> Dispatcher:
    """Construct and configure the aiogram Dispatcher."""
    dp = Dispatcher()

    # Register Middlewares
    user_tracking = UserTrackingMiddleware()
    rate_limiter = RateLimitMiddleware()

    dp.message.outer_middleware(user_tracking)
    dp.callback_query.outer_middleware(user_tracking)

    dp.message.middleware(rate_limiter)
    dp.callback_query.middleware(rate_limiter)

    # Register Routers
    dp.include_router(bot_router)

    # Register Global Error Handler
    dp.errors.register(global_error_handler)

    return dp


async def main() -> None:
    """Main application lifecycle runner."""
    setup_logging()
    logger.info("Starting Telegram AI Assistant...")

    # Validate essential configurations
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing! Please configure it in your .env file."
        )
        sys.exit(1)

    if not settings.GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY is not set! The bot will run, but AI generations will fail until configured."
        )

    # 1. Initialize database schema
    await init_db()

    # 2. Configure Telegram Bot and Dispatcher
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher()

    # 3. Register menu commands in Telegram
    await setup_bot_commands(bot)

    logger.info(
        "Bot started successfully! (Model: %s, Max History: %d)",
        settings.GEMINI_MODEL,
        settings.MAX_HISTORY_MESSAGES,
    )

    try:
        # Delete webhook before starting polling (if previously set)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logger.info("Shutting down bot and closing connections...")
        await bot.session.close()
        await close_db()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
