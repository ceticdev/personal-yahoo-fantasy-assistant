"""Redaction regression suite.

The central guarantee: a sentinel secret registered with `register_secret()`
never appears in captured log output, no matter which path it travels --
message format string, interpolated logger arguments, structured context,
an exception message, or a chained exception's message.
"""

import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from yahoo_fantasy_mcp.logging_utils import (
    clear_registered_secrets,
    configure_logging,
    log_context,
    redact,
    register_secret,
    scrub_text,
)

SENTINEL = "SUPER-SECRET-SENTINEL-a1b2c3d4e5f6"


@pytest.fixture
def captured_logger():
    """A package logger writing to an in-memory stream."""

    clear_registered_secrets()
    logger = logging.getLogger("yahoo_fantasy_mcp")
    saved = list(logger.handlers)
    for handler in saved:
        logger.removeHandler(handler)

    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    try:
        yield logger, stream
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        for handler in saved:
            logger.addHandler(handler)
        clear_registered_secrets()


# -- the sentinel guarantee ------------------------------------------------


def test_sentinel_never_appears_in_the_formatted_message(captured_logger):
    logger, stream = captured_logger
    register_secret(SENTINEL)

    logger.info("refreshing with token %s now", SENTINEL)

    assert SENTINEL not in stream.getvalue()
    assert "[REDACTED]" in stream.getvalue()


def test_sentinel_never_appears_from_interpolated_args(captured_logger):
    logger, stream = captured_logger
    register_secret(SENTINEL)

    logger.warning("multi %s and %s", SENTINEL, {"nested": SENTINEL})

    assert SENTINEL not in stream.getvalue()


def test_sentinel_never_appears_in_structured_context(captured_logger):
    logger, stream = captured_logger
    register_secret(SENTINEL)

    log_context(
        logger,
        logging.INFO,
        "yahoo_api_request",
        path="league/999.l.100000/settings",
        note=f"value was {SENTINEL}",
        nested={"deep": [SENTINEL]},
    )

    assert SENTINEL not in stream.getvalue()


def test_sentinel_never_appears_in_exception_text(captured_logger):
    logger, stream = captured_logger
    register_secret(SENTINEL)

    try:
        raise RuntimeError(f"boom with {SENTINEL}")
    except RuntimeError:
        logger.exception("tool_crashed")

    output = stream.getvalue()
    assert SENTINEL not in output
    assert "RuntimeError" in output


def test_sentinel_never_appears_in_a_chained_exception(captured_logger):
    logger, stream = captured_logger
    register_secret(SENTINEL)

    try:
        try:
            raise ValueError(f"inner cause carrying {SENTINEL}")
        except ValueError as inner:
            raise RuntimeError("outer wrapper") from inner
    except RuntimeError:
        logger.exception("tool_crashed")

    output = stream.getvalue()
    assert SENTINEL not in output
    # The chain really was rendered -- so the absence above means redaction,
    # not that the cause was simply dropped.
    assert "ValueError" in output and "RuntimeError" in output


def test_sentinel_absent_across_every_channel_at_once(captured_logger):
    """One assertion covering the whole surface, as a standing regression."""

    logger, stream = captured_logger
    register_secret(SENTINEL)

    logger.info("plain %s", SENTINEL)
    log_context(logger, logging.INFO, f"ctx {SENTINEL}", field=SENTINEL)
    try:
        try:
            raise ValueError(SENTINEL)
        except ValueError as inner:
            raise RuntimeError(SENTINEL) from inner
    except RuntimeError:
        logger.exception("crash %s", SENTINEL)

    assert SENTINEL not in stream.getvalue()


# -- pattern-based redaction (unregistered secrets) ------------------------


def test_redacts_secret_shaped_keys():
    payload = {
        "access_token": "abc123",
        "refresh_token": "def456",
        "client_secret": "shh",
        "safe_field": "keep me",
        "nested": {"password": "hunter2", "ok": 1},
    }
    result = redact(payload)
    assert result["access_token"] == "[REDACTED]"
    assert result["refresh_token"] == "[REDACTED]"
    assert result["client_secret"] == "[REDACTED]"
    assert result["safe_field"] == "keep me"
    assert result["nested"]["password"] == "[REDACTED]"
    assert result["nested"]["ok"] == 1


def test_redacts_bearer_token_in_strings():
    payload = {"header": "Authorization: Bearer abcDEF123.456-_~+/="}
    result = redact(payload)
    assert "abcDEF123" not in result["header"]


def test_redacts_unregistered_secret_shaped_assignments():
    text = "POST failed: client_secret=9f8e7d6c5b4a3210 and code=AUTHCODE123456"
    scrubbed = scrub_text(text)
    assert "9f8e7d6c5b4a3210" not in scrubbed
    assert "AUTHCODE123456" not in scrubbed


def test_redacts_yahoo_consumer_key_and_jwt_shapes():
    scrubbed = scrub_text(
        "key dj0yJmk9abcdefghijklmnop and jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
    )
    assert "dj0yJmk9" not in scrubbed
    assert "eyJhbGciOiJIUzI1NiJ9" not in scrubbed


def test_non_string_context_values_keep_their_type():
    result = redact({"status": 403, "stale": True, "age": 1.5})
    assert result == {"status": 403, "stale": True, "age": 1.5}


# -- handler hygiene -------------------------------------------------------


def test_repeated_configuration_does_not_stack_handlers():
    logger = logging.getLogger("yahoo_fantasy_mcp")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    configure_logging("INFO")
    first = len(logger.handlers)
    configure_logging("INFO")
    configure_logging("DEBUG")

    assert first == 1
    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG


def test_records_do_not_propagate_to_unredacting_root_handlers(captured_logger):
    logger, _ = captured_logger
    register_secret(SENTINEL)

    root_stream = io.StringIO()
    root_handler = logging.StreamHandler(root_stream)
    logging.getLogger().addHandler(root_handler)
    try:
        logger.error("leak attempt %s", SENTINEL)
    finally:
        logging.getLogger().removeHandler(root_handler)

    # propagate=False means the root handler -- which does no redaction --
    # never sees the record at all.
    assert root_stream.getvalue() == ""
