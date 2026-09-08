"""Inline and reply keyboards for the Telegram AI Assistant Bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Return the main menu inline keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text="🤖 Ask AI", callback_data="btn_ask_ai"),
            InlineKeyboardButton(text="🆕 New Chat", callback_data="btn_new_chat"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data="btn_settings"),
            InlineKeyboardButton(text="ℹ️ About", callback_data="btn_about"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_new_chat_confirm_keyboard() -> InlineKeyboardMarkup:
    """Return confirmation keyboard before wiping conversation history."""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Yes, start new chat", callback_data="confirm_new_chat"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_new_chat"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
