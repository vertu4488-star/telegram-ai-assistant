"""Telegram bot commands configuration and menu registration."""

import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

logger = logging.getLogger(__name__)

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🚀 Запустить бота и открыть меню"),
    BotCommand(command="help", description="❓ Помощь и инструкция"),
    BotCommand(command="newchat", description="🆕 Очистить историю и начать заново"),
    BotCommand(command="memory", description="🧠 Состояние памяти диалога"),
    BotCommand(command="settings", description="⚙️ Настройки помощника"),
    BotCommand(command="about", description="ℹ️ О боте"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """Register default slash commands with Telegram UI menu."""
    try:
        await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
        logger.info("Telegram bot menu commands registered successfully.")
    except Exception as exc:
        logger.error("Failed to register bot commands: %s", exc)
