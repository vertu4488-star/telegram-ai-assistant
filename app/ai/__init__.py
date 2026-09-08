"""AI Service package using Google GenAI SDK."""

from app.ai.gemini import GeminiService
from app.ai.prompts import SYSTEM_INSTRUCTION

__all__ = ["GeminiService", "SYSTEM_INSTRUCTION"]
