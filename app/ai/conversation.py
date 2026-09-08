"""Helpers to format conversation history for Google GenAI SDK."""

from typing import Any, List, Sequence

from google.genai import types

from app.database.models import Message


def build_gemini_contents(
    history_messages: Sequence[Message],
    current_prompt: str,
) -> List[types.Content]:
    """
    Convert stored Message records and current user prompt into google-genai Content objects.

    Gemini expects role='user' for user prompts and role='model' for AI responses.
    """
    contents: List[types.Content] = []

    for msg in history_messages:
        # Map database role to Gemini role ('user' -> 'user', 'assistant' -> 'model')
        if msg.role == "user":
            role = "user"
        elif msg.role in ("assistant", "model"):
            role = "model"
        else:
            continue  # Skip unsupported roles

        if not msg.content or not msg.content.strip():
            continue

        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg.content)],
            )
        )

    # Append current turn prompt
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=current_prompt)],
        )
    )

    return contents
