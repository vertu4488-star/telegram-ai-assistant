"""Inline and reply keyboards for the Telegram AI Assistant Bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Return the main menu inline keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text="🔧 Диагностика и ремонт", callback_data="btn_ask_ai"),
        ],
        [
            InlineKeyboardButton(text="📰 Канал New iPhone Service", url="https://t.me/New_Iphone_Service"),
        ],
        [
            InlineKeyboardButton(text="🆕 Новый диалог", callback_data="btn_new_chat"),
            InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="btn_about"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="btn_settings"),
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
