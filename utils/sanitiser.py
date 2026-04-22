"""
Input sanitisation layer.
Cleans raw text before it reaches the AI processor.

Handles:
- HTML/script tag stripping
- Control character removal
- Excessive whitespace normalisation
- Length truncation (prevents token abuse)
- Null / whitespace-only detection
"""

import re
from utils.logger import logger

MAX_INPUT_LENGTH = 2000  # characters — prevents runaway token usage


def sanitise(raw_text: str, record_id: str) -> str | None:
    """
    Clean and validate raw input text.
    Returns sanitised string, or None if input is unusable.
    """
    if not raw_text or not isinstance(raw_text, str):
        logger.warning(f"[{record_id}] Input is null or non-string")
        return None

    text = raw_text

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Remove script/style content
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove control characters (except newline and tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Collapse excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Empty after cleaning
    if not text:
        logger.warning(f"[{record_id}] Input empty after sanitisation")
        return None

    # Whitespace-only or too short to be meaningful
    if len(text) < 5:
        logger.warning(f"[{record_id}] Input too short to classify: '{text}'")
        return None

    # Truncate if over limit
    if len(text) > MAX_INPUT_LENGTH:
        logger.warning(f"[{record_id}] Input truncated from {len(text)} to {MAX_INPUT_LENGTH} chars")
        text = text[:MAX_INPUT_LENGTH] + "..."

    return text
