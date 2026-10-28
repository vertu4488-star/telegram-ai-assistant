"""Telegram bot command, callback, and text message handlers."""

import asyncio
import logging
from typing import List, Optional

from aiogram import F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.ai.gemini import gemini_service
from app.bot.keyboards import get_main_inline_keyboard, get_new_chat_confirm_keyboard
from app.config import settings
from app.services.message_service import MessageService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = Router(name="bot_router")

# Owner notifications for real customer leads.
# ADMIN_USER_ID is configurable in Render; the known owner ID is a safe fallback.
OWNER_TELEGRAM_ID = settings.ADMIN_USER_ID or 473953596

LEAD_KEYWORDS = (
    "сколько стоит", "сколько будет стоить", "цена", "стоимость", "прайс",
    "сколько обойдется", "сколько обойдётся", "замена экрана", "замена дисплея",
    "замена аккумулятора", "замена батареи", "ремонт iphone", "ремонт айфона",
    "ремонт макбук", "ремонт macbook", "ремонт ipad", "починить", "починка",
    "консультац", "записаться", "запись на ремонт", "можно принести",
    "принимаете в ремонт", "где находитесь", "адрес сервиса", "сколько по времени",
    "срок ремонта", "не работает", "разбил", "не заряжается", "не включается",
)

def classify_lead_message(text: str) -> Optional[str]:
    """Return the customer-intent label when a message looks like a repair lead."""
    normalized = text.casefold()
    if any(term in normalized for term in ("сколько стоит", "стоимость", "цена", "прайс", "обойдется", "обойдётся")):
        return "Вопрос о цене"
    if any(term in normalized for term in ("консультац", "посовет", "подскажите", "можно узнать")):
        return "Запрос консультации"
    if any(term in normalized for term in ("записаться", "запись на ремонт", "принимаете в ремонт", "можно принести")):
        return "Запись / приём в ремонт"
    if any(term in normalized for term in LEAD_KEYWORDS):
        return "Возможный клиент: ремонт"
    return None


async def notify_owner_about_lead(message: Message, text: str, label: str) -> None:
    """Send the owner a concise Telegram alert about a potential customer."""
    if not OWNER_TELEGRAM_ID or not message.from_user:
        return
    user = message.from_user
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part) or "Без имени"
    username = f"@{user.username}" if user.username else "не указан"
    preview = " ".join(text.split())
    if len(preview) > 700:
        preview = preview[:697] + "..."
    alert = (
        "🔔 Активность потенциального клиента — New iPhone Service\n\n"
        f"Тип обращения: {label}\n"
        f"Клиент: {full_name}\n"
        f"Username: {username}\n"
        f"Telegram ID: {user.id}\n\n"
        f"Сообщение клиента:\n{preview}\n\n"
        f"Открыть диалог: tg://user?id={user.id}"
    )
    try:
        await message.bot.send_message(chat_id=OWNER_TELEGRAM_ID, text=alert)
    except Exception as exc:
        logger.warning("Failed to notify owner about customer lead: %s", exc)



# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def split_message(text: str, max_chunk_size: int = 4000) -> List[str]:
    """
    Split long text into safe chunks under Telegram's 4096 character limit.

    Attempts to split at paragraphs (double newlines) or lines to preserve readability.
    """
    if not text:
        return []

    if len(text) <= max_chunk_size:
        return [text]

    chunks: List[str] = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        # If adding this line exceeds the limit
        if len(current_chunk) + len(line) + 1 > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # If a single line is longer than max_chunk_size, break it arbitrarily
            if len(line) > max_chunk_size:
                for i in range(0, len(line), max_chunk_size):
                    chunk_part = line[i : i + max_chunk_size]
                    if i + max_chunk_size >= len(line):
                        current_chunk = chunk_part
                    else:
                        chunks.append(chunk_part)
            else:
                current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk and current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


async def send_safe_message(
    message: Message,
    text: str,
    reply_markup: Optional[object] = None,
) -> None:
    """
    Send text chunks safely to Telegram, falling back to plain text if Markdown fails.
    """
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        try:
            # First attempt: Markdown formatting
            await message.answer(
                chunk,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            logger.warning(
                "Markdown parsing failed (%s). Retrying as plain text.",
                exc,
            )
            # Fallback attempt: Plain text
            await message.answer(
                chunk,
                parse_mode=None,
                reply_markup=markup,
            )


async def send_typing_action_loop(bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Periodically trigger the 'typing...' chat action while AI generates content."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass  # Ignore transient network errors during typing indicator
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.5)
        except asyncio.TimeoutError:
            continue


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle /start command with a friendly bilingual welcome."""
    first_name = message.from_user.first_name if message.from_user else "друг"
    welcome_text = (
        f"👋 **Здравствуйте, {first_name}!**\n\n"
        "Это помощник New iPhone Service по смартфонам, Apple и ремонту техники.\n\n"
        "🔧 **Чем могу помочь:**\n"
        "• Диагностика неисправностей iPhone, iPad и MacBook\n"
        "• Разбор симптомов и измерений на уровне платы\n"
        "• Проверка гипотез и последовательность дальнейших тестов\n"
        "• Новости Apple и мобильных технологий\n\n"
        "Напишите вопрос обычным сообщением или выберите пункт меню ниже."
    )
    await message.answer(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Handle /help command explaining available commands and tips."""
    help_text = (
        "📖 **Как пользоваться помощником New iPhone Service:**\n\n"
        "**Команды:**\n"
        "• `/start` — открыть главное меню\n"
        "• `/help` — эта справка\n"
        "• `/newchat` — очистить историю диалога\n"
        "• `/memory` — состояние памяти диалога\n"
        "• `/settings` — настройки\n"
        "• `/about` — информация о боте\n\n"
        "**Как получить точный ответ:**\n"
        "Опишите модель устройства, симптомы и уже выполненные проверки. "
        "Для измерений укажите прибор, режим и полученные значения.\n"
        "Помощник отделяет подтверждённые факты от гипотез и не должен угадывать "
        "номера микросхем или контрольные напряжения без надёжных данных.\n"
        "Используйте `/newchat`, чтобы начать новую тему.\n"
    )
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("newchat"))
async def handle_newchat(message: Message) -> None:
    """Обработчик /newchat для очистки истории."""
    if not message.from_user:
        return
    deleted_count = await MessageService.clear_conversation(message.from_user.id)
    text = (
        "🧹 **История диалога очищена!**\n\n"
        f"Удалено сообщений из истории: {deleted_count}.\n"
        "Можно начать новую тему. Что обсудим?"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("memory"))
async def handle_memory(message: Message) -> None:
    """Handle /memory command displaying context depth."""
    if not message.from_user:
        return
    history = await MessageService.get_conversation_history(message.from_user.id)
    text = (
        "🧠 **Состояние памяти диалога:**\n\n"
        f"• Статус: **Активна** ✅\n"
        f"• Сообщений в контексте: **{len(history)}**\n"
        f"• Максимальный размер истории: **{settings.MAX_HISTORY_MESSAGES}** сообщений\n\n"
        "_Последние сообщения используются для сохранения контекста диалога._\n"
        "_Используйте `/newchat`, чтобы очистить историю._"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("settings"))
async def handle_settings(message: Message) -> None:
    """Handle /settings command."""
    user_id = message.from_user.id if message.from_user else 0
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "Не указан"
    is_admin_str = "Да 👑" if settings.is_admin(user_id) else "Нет"

    text = (
        "⚙️ **Настройки помощника:**\n\n"
        f"• **ID пользователя:** `{user_id}`\n"
        f"• **Имя пользователя:** {username}\n"
        f"• **Модель ИИ:** `{settings.GEMINI_MODEL}`\n"
        f"• **Максимальная история контекста:** `{settings.MAX_HISTORY_MESSAGES}` сообщений\n"
        f"• **Лимит запросов:** `{settings.RATE_LIMIT_MESSAGES_PER_MINUTE}` запросов в минуту\n"
        f"• **Права администратора:** {is_admin_str}\n\n"
        "_Чтобы очистить историю и начать заново, используйте `/newchat`._"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("about"))
async def handle_about(message: Message) -> None:
    """Handle /about command."""
    about_text = (
        "ℹ️ **О New iPhone Service**\n\n"
        "Помощник по диагностике смартфонов и компьютеров Apple, ремонту техники "
        "и новостям мобильного рынка.\n\n"
        "• ИИ: Google Gemini\n"
        "• Контекст диалога: сохраняется для продолжения диагностики\n"
        "• Рекомендации: пошаговые, с учётом модели и симптомов\n\n"
        "Важно: ответ ИИ — это помощь в диагностике, а не подтверждение неисправности "
        "без необходимых измерений."
    )
    await message.answer(about_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Admin Handlers
# ---------------------------------------------------------------------------


@router.message(Command("stats"))
async def handle_stats(message: Message) -> None:
    """Admin command to view bot usage statistics."""
    if not message.from_user or not settings.is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Эта команда доступна только администратору.")
        return

    stats = await UserService.get_system_stats()
    text = (
        "📊 **Bot Administration Statistics:**\n\n"
        f"• 👥 **Total Registered Users:** {stats['total_users']}\n"
        f"• 💬 **Total Messages Stored:** {stats['total_messages']}\n"
        f"• 🔥 **Active Users (Last 24h):** {stats['active_users_24h']}\n"
        f"• 🤖 **Active Model:** `{settings.GEMINI_MODEL}`\n"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("broadcast"))
async def handle_broadcast(message: Message) -> None:
    """Admin command to broadcast announcements to all users."""
    if not message.from_user or not settings.is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Эта команда доступна только администратору.")
        return

    # Extract broadcast message text after '/broadcast '
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "⚠️ Please provide a message to broadcast.\n"
            "Пример: `/broadcast Текст сообщения`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    broadcast_text = parts[1].strip()
    recipient_ids = await UserService.get_broadcast_recipients()

    if not recipient_ids:
        await message.answer("ℹ️ В базе пока нет зарегистрированных пользователей.")
        return

    status_msg = await message.answer(
        f"🚀 Начинаю рассылку для пользователей: {len(recipient_ids)}..."
    )

    sent_count = 0
    failed_count = 0

    for uid in recipient_ids:
        try:
            await message.bot.send_message(
                chat_id=uid,
                text=f"📢 **Announcement:**\n\n{broadcast_text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent_count += 1
            await asyncio.sleep(0.05)  # Telegram API flood control
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning("Failed to broadcast to user %d: %s", uid, exc)
            failed_count += 1
        except Exception as exc:
            logger.error("Unexpected broadcast error for user %d: %s", uid, exc)
            failed_count += 1

    await status_msg.edit_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"• Delivered: **{sent_count}**\n"
        f"• Failed/Blocked: **{failed_count}**\n"
        f"• Всего: **{len(recipient_ids)}**",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Callback Query Handlers
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "btn_ask_ai")
async def callback_ask_ai(callback: CallbackQuery) -> None:
    """Prompt user to type a message."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(
            "💬 Напишите вопрос по ремонту iPhone, iPad, MacBook или другой техники. "
            "Я разберу симптомы, возможные причины и следующий диагностический шаг.",
            parse_mode=None,
        )


@router.callback_query(F.data == "btn_new_chat")
async def callback_new_chat(callback: CallbackQuery) -> None:
    """Prompt confirmation to start a new chat."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(
            "Очистить историю диалога и начать новый чат?",
            reply_markup=get_new_chat_confirm_keyboard(),
        )


@router.callback_query(F.data == "confirm_new_chat")
async def callback_confirm_new_chat(callback: CallbackQuery) -> None:
    """Confirm and execute conversation wipe."""
    await callback.answer()
    if callback.from_user:
        await MessageService.clear_conversation(callback.from_user.id)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "🧹 **История диалога очищена!**\n\n"
            "Теперь можно начать новый диалог.",
            parse_mode=ParseMode.MARKDOWN,
        )


@router.callback_query(F.data == "cancel_new_chat")
async def callback_cancel_new_chat(callback: CallbackQuery) -> None:
    """Cancel conversation wipe."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "👌 Очистка отменена. История диалога сохранена."
        )


@router.callback_query(F.data == "btn_settings")
async def callback_settings(callback: CallbackQuery) -> None:
    """Show settings from inline button."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        user_id = callback.from_user.id if callback.from_user else 0
        is_admin_str = "Да 👑" if settings.is_admin(user_id) else "Нет"
        text = (
            "⚙️ **Настройки помощника:**\n\n"
            f"• **ID пользователя:** `{user_id}`\n"
            f"• **Модель ИИ:** `{settings.GEMINI_MODEL}`\n"
            f"• **Максимальная история контекста:** `{settings.MAX_HISTORY_MESSAGES}` сообщений\n"
            f"• **Лимит запросов:** `{settings.RATE_LIMIT_MESSAGES_PER_MINUTE}` запросов в минуту\n"
            f"• **Права администратора:** {is_admin_str}\n"
        )
        await callback.message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "btn_about")
async def callback_about(callback: CallbackQuery) -> None:
    """Show about information from inline button."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        about_text = (
            "ℹ️ **О помощнике New iPhone Service:**\n\n"
            "• **Платформа:** `aiogram 3.x`\n"
            "• **ИИ:** Google Gemini (`google-genai` SDK)\n"
            f"• **Модель:** `{settings.GEMINI_MODEL}`\n"
            "• **База данных:** SQLite и Async SQLAlchemy 2.0\n"
            "• **Возможности:** память диалога, безопасное форматирование и ограничение частоты запросов.\n"
        )
        await callback.message.answer(about_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# General Text Message Handler
# ---------------------------------------------------------------------------


@router.message(F.text & ~F.text.startswith("/"))
async def handle_user_text_message(message: Message) -> None:
    """
    Handle natural language user input:
    1. Persist user message to DB
    2. Retrieve conversation context
    3. Trigger typing status indicator
    4. Call Gemini AI service
    5. Save assistant response to DB
    6. Send formatted response to user
    """
    if not message.text or not message.from_user:
        return

    user_id = message.from_user.id
    user_prompt = message.text.strip()

    # Notify the owner immediately when a message indicates purchase/repair intent.
    lead_label = classify_lead_message(user_prompt)
    if lead_label:
        await notify_owner_about_lead(message, user_prompt, lead_label)

    # 1. Persist user message
    try:
        await MessageService.save_user_message(telegram_id=user_id, content=user_prompt)
    except Exception as exc:
        logger.error("Failed to save incoming user message: %s", exc)

    # 2. Fetch conversation history for multi-turn context
    history = []
    try:
        history = await MessageService.get_conversation_history(
            telegram_id=user_id,
            limit=settings.MAX_HISTORY_MESSAGES,
        )
        # Exclude the current message that was just saved from the history list to prevent duplication
        if history and history[-1].role == "user" and history[-1].content == user_prompt:
            history = list(history[:-1])
    except Exception as exc:
        logger.error("Failed to fetch conversation history: %s", exc)

    # 3. Start typing indicator background loop
    stop_typing_event = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_action_loop(
            bot=message.bot,
            chat_id=message.chat.id,
            stop_event=stop_typing_event,
        )
    )

    try:
        # 4. Generate AI response via Gemini
        ai_response = await gemini_service.generate_response(
            prompt=user_prompt,
            history_messages=history,
        )

        # 5. Persist assistant response
        try:
            await MessageService.save_assistant_message(
                telegram_id=user_id,
                content=ai_response,
            )
        except Exception as exc:
            logger.error("Failed to save assistant response: %s", exc)

        # 6. Send safe message chunks
        await send_safe_message(message=message, text=ai_response)

    except Exception as exc:
        logger.exception("Unexpected error while generating AI response: %s", exc)
        await message.answer(
            "⚠️ При обработке запроса произошла ошибка. Попробуйте ещё раз немного позже."
        )

    finally:
        # Stop typing indicator loop
        stop_typing_event.set()
        await typing_task
