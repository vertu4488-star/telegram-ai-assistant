"""Logging configuration and sensitive data sanitization."""

import logging
import re
import sys
from typing import Optional


class SensitiveFilter(logging.Filter):
    """Filter that masks tokens and API keys in log records."""

    _PATTERNS = [
        re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}", re.IGNORECASE),  # Telegram Bot Token pattern
        re.compile(r"AIza[0-9A-Za-z-_]{35}", re.IGNORECASE),       # Google API Key pattern
        re.compile(r"Bearer\s+[A-Za-z0-9\._\-]+", re.IGNORECASE), # Bearer tokens
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._sanitize(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self._sanitize(v) if isinstance(v, str) else v for v in record.args)
        return True

    @classmethod
    def _sanitize(cls, text: str) -> str:
        for pattern in cls._PATTERNS:
            text = pattern.sub("[REDACTED_SECRET]", text)
        return text


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with formatting and security filtering."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-configuration
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveFilter())

    root_logger.addHandler(console_handler)

    # Reduce noisy logs from third-party libraries
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
