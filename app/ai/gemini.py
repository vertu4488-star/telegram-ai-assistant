"""Gemini AI Service integrating the official Google GenAI Python SDK."""

import asyncio
import logging
from typing import List, Optional, Sequence

from google import genai
from google.genai import errors, types

from app.ai.conversation import build_gemini_contents
from app.ai.prompts import SYSTEM_INSTRUCTION
from app.config import settings
from app.database.models import Message

logger = logging.getLogger(__name__)


class GeminiService:
    """Service wrapping Google GenAI SDK with async execution, retries, and timeouts."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.timeout_seconds = timeout_seconds or settings.REQUEST_TIMEOUT_SECONDS
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        """Lazy initialization of Google GenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate_response(
        self,
        prompt: str,
        history_messages: Optional[Sequence[Message]] = None,
        max_retries: int = 3,
    ) -> str:
        """
        Generate an AI assistant response given the prompt and conversation history.

        Handles:
        - Multi-turn conversation format
        - System instruction injection
        - Timeout handling
        - Exponential backoff retry on transient errors
        - Safe error messaging for users
        """
        history = history_messages or []
        contents = build_gemini_contents(history, prompt)

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
        )

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Sending request to Gemini model=%s (attempt %d/%d, history_turns=%d)",
                    self.model_name,
                    attempt,
                    max_retries,
                    len(history),
                )

                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=config,
                    ),
                    timeout=float(self.timeout_seconds),
                )

                if response and response.text:
                    result = response.text.strip()
                    logger.info(
                        "Gemini response received successfully (model=%s, chars=%d)",
                        self.model_name,
                        len(result),
                    )
                    return result
                elif response and response.candidates:
                    parts = []
                    for candidate in response.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if part.text:
                                    parts.append(part.text)
                    if parts:
                        result = "\n".join(parts).strip()
                        logger.info(
                            "Gemini response received successfully via candidate fallback (model=%s, chars=%d)",
                            self.model_name,
                            len(result),
                        )
                        return result

                logger.warning("Gemini returned an empty response (model=%s)", self.model_name)
                return "I received an empty response from the AI model. Please try asking again."

            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Gemini request timed out after %ds (attempt %d/%d)",
                    self.timeout_seconds,
                    attempt,
                    max_retries,
                )
                if attempt < max_retries:
                    await asyncio.sleep(1.5 * attempt)
                    continue
                return (
                    "⏳ The AI request timed out. Please try again in a moment "
                    "or ask a simpler question."
                )

            except errors.APIError as exc:
                last_error = exc
                status_code = getattr(exc, "code", None)
                logger.error(
                    "Gemini API error occurred (model=%s, status=%s): %s",
                    self.model_name,
                    status_code,
                    exc.message if hasattr(exc, "message") else str(exc),
                )

                if status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    backoff = 2.0 * attempt
                    logger.info("Retrying Gemini request after %.1fs backoff...", backoff)
                    await asyncio.sleep(backoff)
                    continue

                if status_code == 429:
                    return "⚠️ The AI service is currently receiving high traffic. Please wait a moment and try again."
                return "⚠️ An error occurred while communicating with the AI service. Please try again later."

            except Exception as exc:
                last_error = exc
                logger.exception("Unexpected error during Gemini generation: %s", exc)
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return "⚠️ An unexpected error occurred. Please try again in a few moments."

        logger.error("All %d attempts failed for Gemini generation. Last error: %s", max_retries, last_error)
        return "⚠️ Unable to generate a response at this time. Please try again later."


# Global singleton instance
gemini_service = GeminiService()
