"""Structured JSON logging with secret redaction.

Every log line goes through `redact()` before it is emitted so a stray
`logger.info(str(response))` cannot leak an access token, refresh token, or
client secret into logs. This is defense in depth, not a substitute for
never logging raw token payloads in the first place.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any


_SECRET_KEY_PATTERN = re.compile(
    r"(access_token|refresh_token|client_secret|authorization|password)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]+=*", re.IGNORECASE)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    return value


def redact(payload: Any) -> Any:
    """Recursively redact secret-shaped keys and bearer tokens from a payload."""

    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if _SECRET_KEY_PATTERN.search(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact(value)
        return redacted
    if isinstance(payload, (list, tuple)):
        return [redact(item) for item in payload]
    return _redact_value(payload)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = redact(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("yahoo_fantasy_mcp")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    return logger


def log_context(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    logger.log(level, message, extra={"context": context})
