"""Logging utilities for the trading bot.

Filters emoji characters from console output to avoid encoding issues on
Windows terminals.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re

# Regex matching most Unicode emoji / pictograph ranges.
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F680-\U0001F6FF"   # transport & map symbols
    "\U0001F1E0-\U0001F1FF"   # flags
    "\U00002500-\U00002BEF"   # CJK / misc
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F926-\U0001F937"
    "\U00010000-\U0010FFFF"
    "♀-♂"
    "☀-⭕"
    "‍"
    "⏏"
    "⏩"
    "⌚"
    "️"
    "〰"
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    """Remove emoji characters from *text*."""
    return _EMOJI_RE.sub("", text)


class _EmojiFilter(logging.Filter):
    """Logging filter that strips emoji from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = strip_emoji(str(record.msg))
        return True


class TradingLogger:
    """Configure and provide a :class:`logging.Logger` for the trading bot.

    The logger writes detailed records (DEBUG+) to a rotating file and
    simpler records (INFO+) to the console.  Emoji characters are stripped
    from console output.
    """

    def __init__(
        self,
        log_file: str = "trading_bot.log",
        console_level: int = logging.INFO,
    ) -> None:
        self._logger = logging.getLogger("TradingBot")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        # --- rotating file handler ------------------------------------------
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - "
                "%(funcName)s:%(lineno)d - %(message)s"
            )
        )
        self._logger.addHandler(file_handler)

        # --- console handler with emoji filter ------------------------------
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.addFilter(_EmojiFilter())
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """Return the configured :class:`logging.Logger` instance."""
        return self._logger
