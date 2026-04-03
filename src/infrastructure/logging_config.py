"""
Structured logging configuration for Puch AI Voice Server.

Usage:
    from src.infrastructure.logging_config import configure_logging
    configure_logging()  # call once at startup, before any loggers are used

Respects two env vars:
    LOG_LEVEL  — DEBUG | INFO | WARNING | ERROR (default: INFO)
    LOG_FORMAT — json | text (default: text; set json for production / CloudWatch)

JSON output fields (each line is a valid JSON object):
    timestamp, level, name, message
    + any extras passed via logger.info("msg", extra={...})

Correlation helpers:
    with log_context(stream_id="abc123"):
        logger.info("event")   # → {"stream_id": "abc123", ...}
"""

import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Generator, Optional

from pythonjsonlogger.json import JsonFormatter


# ── Context variable for per-request correlation IDs ─────────────────────────
_log_context: ContextVar[Dict[str, Any]] = ContextVar("_log_context", default={})


class ContextInjectingFilter(logging.Filter):
    """Inject current log-context fields (e.g., stream_id) into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _log_context.get({}).items():
            setattr(record, key, value)
        return True


@contextmanager
def log_context(**kwargs: Any) -> Generator[None, None, None]:
    """
    Context manager that injects extra fields into all log records emitted
    inside the block.

    Example::

        async def handle_call(stream_id: str):
            with log_context(stream_id=stream_id):
                logger.info("call started")   # ← stream_id appears in output
    """
    token = _log_context.set({**_log_context.get({}), **kwargs})
    try:
        yield
    finally:
        _log_context.reset(token)


def configure_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
) -> None:
    """
    Configure root logger once at application startup.

    Parameters are read from env vars when not explicitly provided:
      LOG_LEVEL  — log verbosity (default INFO)
      LOG_FORMAT — 'json' or 'text' (default 'text')

    Idempotent: calling more than once is safe (handlers are not duplicated).
    """
    log_level_str = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_format = (fmt or os.getenv("LOG_FORMAT", "text")).lower()
    log_level = getattr(logging, log_level_str, logging.INFO)

    root = logging.getLogger()

    # Avoid adding duplicate handlers on repeated calls (e.g., during tests)
    if root.handlers:
        root.setLevel(log_level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(ContextInjectingFilter())

    if log_format == "json":
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(log_level)
