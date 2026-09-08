"""Telegram bot commands configuration and menu registration."""

import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

logger = logging.getLogger(__name__)

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🚀 Start the bot & show menu"),
    BotCommand(command="help", description="❓ Help & how to use"),
    BotCommand(command="newchat", description="🆕 Clear memory & start fresh chat"),
    BotCommand(command="memory", description="🧠 Conversation memory status"),
    BotCommand(command="settings", description="⚙️ View assistant settings"),
    BotCommand(command="about", description="ℹ️ About this bot"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """Register default slash commands with Telegram UI menu."""
    try:
        await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
        logger.info("Telegram bot menu commands registered successfully.")
    except Exception as exc:
        logger.error("Failed to register bot commands: %s", exc)
