"""Structured JSON logging with end-to-end secret redaction.

Redaction here covers every path by which text reaches a log record:

1. the formatted message (`record.getMessage()`, i.e. after `%`-interpolation
   of the logger's positional args);
2. the positional args themselves, post-interpolation;
3. the structured `context` payload attached by `log_context()`;
4. rendered exception text, including chained (`__cause__`/`__context__`)
   exceptions;
5. any bearer-token-shaped or secret-assignment-shaped substring anywhere in
   the above.

Two mechanisms do the work. `register_secret()` records exact values that are
known to be secret (client secret, access/refresh tokens, authorization
codes) so they are replaced literally wherever they appear, no matter how
they got there. Pattern matching then catches secret-shaped text that was
never registered. The registry is the strong guarantee; the patterns are
defense in depth.

This is still not a substitute for not logging token material in the first
place, which the rest of the package also does.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY_PATTERN = re.compile(
    r"(access_token|refresh_token|client_secret|consumer_secret|authorization"
    r"|password|passwd|api_key|apikey|secret|auth_code|authorization_code)",
    re.IGNORECASE,
)

_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)

# key=value / key: value / "key": "value" assignments carrying secret-shaped keys.
_ASSIGNMENT_PATTERN = re.compile(
    r"""(?P<key>["']?(?:access_token|refresh_token|client_secret|consumer_secret
        |password|passwd|api[_-]?key|secret|auth(?:orization)?_code|code)["']?)
        (?P<sep>\s*[:=]\s*)
        (?P<quote>["']?)(?P<value>[^\s"',;}&]+)(?P=quote)""",
    re.IGNORECASE | re.VERBOSE,
)

# Yahoo consumer keys and JWT-shaped blobs, which are secret by construction.
_TOKEN_SHAPED_PATTERNS = (
    re.compile(r"\bdj0y[A-Za-z0-9\-_]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
)

#: Exact secret values to strike from any text. Populated at runtime by the
#: token vault / OAuth client. Never logged or exposed itself.
_REGISTERED_SECRETS: set[str] = set()

#: Below this length a "secret" is too short to substitute safely without
#: mangling unrelated text.
_MIN_REGISTERABLE_SECRET_LEN = 6


def register_secret(value: Any) -> None:
    """Record an exact secret value to be scrubbed from all future log output."""

    if not isinstance(value, str):
        return
    candidate = value.strip()
    if len(candidate) >= _MIN_REGISTERABLE_SECRET_LEN:
        _REGISTERED_SECRETS.add(candidate)


def clear_registered_secrets() -> None:
    """Test helper: drop all registered secrets."""

    _REGISTERED_SECRETS.clear()


def scrub_text(text: Any) -> Any:
    """Remove registered and secret-shaped values from a string.

    Non-strings pass through untouched so numeric/boolean context fields keep
    their type in the JSON output.
    """

    if not isinstance(text, str):
        return text

    scrubbed = text
    # Longest first, so a secret that contains another secret as a prefix does
    # not leave a dangling tail behind.
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        if secret in scrubbed:
            scrubbed = scrubbed.replace(secret, REDACTED)

    scrubbed = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", scrubbed)
    scrubbed = _ASSIGNMENT_PATTERN.sub(
        lambda m: f"{m.group('key')}{m.group('sep')}{m.group('quote')}{REDACTED}{m.group('quote')}",
        scrubbed,
    )
    for pattern in _TOKEN_SHAPED_PATTERNS:
        scrubbed = pattern.sub(REDACTED, scrubbed)
    return scrubbed


def redact(payload: Any) -> Any:
    """Recursively redact secret-shaped keys and secret values from a payload."""

    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if _SECRET_KEY_PATTERN.search(str(key)):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact(value)
        return redacted
    if isinstance(payload, (list, tuple)):
        return [redact(item) for item in payload]
    return scrub_text(payload)


class _JsonFormatter(logging.Formatter):
    """JSON formatter that scrubs message, args, context, and exception text."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            # getMessage() applies %-interpolation of record.args, so scrubbing
            # its result covers both the format string and the arguments.
            "message": scrub_text(record.getMessage()),
        }

        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = redact(extra)

        if record.exc_info:
            # formatException renders the full chain, including "The above
            # exception was the direct cause of..." segments.
            payload["exc_info"] = scrub_text(self.formatException(record.exc_info))
        if record.exc_text:
            payload["exc_text"] = scrub_text(record.exc_text)
        if record.stack_info:
            payload["stack_info"] = scrub_text(self.formatStack(record.stack_info))

        return scrub_text(json.dumps(payload, sort_keys=True, default=str))


#: Marker so repeated configure_logging() calls recognize our own handler.
_HANDLER_TAG = "yahoo_fantasy_mcp_json_handler"


def configure_logging(level: str = "INFO", *, stream: Any = None) -> logging.Logger:
    """Configure the package logger idempotently.

    Repeated calls re-apply the level but never stack a second handler, and
    propagation stays off so records are not also emitted by the root logger's
    handlers (which do not redact).
    """

    logger = logging.getLogger("yahoo_fantasy_mcp")
    logger.setLevel(level)
    logger.propagate = False

    existing = [h for h in logger.handlers if getattr(h, "_tag", None) == _HANDLER_TAG]
    if existing:
        if stream is not None:
            for handler in existing:
                logger.removeHandler(handler)
        else:
            return logger

    handler = logging.StreamHandler(stream=stream if stream is not None else sys.stderr)
    handler.setFormatter(_JsonFormatter())
    handler._tag = _HANDLER_TAG  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return logger


def log_context(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    logger.log(level, message, extra={"context": context})
