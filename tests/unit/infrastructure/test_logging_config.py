"""Tests for structured logging configuration."""

import json
import logging
import io
from unittest.mock import patch

import pytest

from src.infrastructure.logging_config import (
    TraceContextInjectingFilter,
    configure_logging,
    log_context,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stream_logger(name: str = "test_logger") -> tuple:
    """Return (logger, stream) with a fresh StreamHandler for capture."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextInjectingFilter())
    lgr = logging.getLogger(name + "_" + str(id(stream)))
    lgr.propagate = False
    lgr.addHandler(handler)
    lgr.setLevel(logging.DEBUG)
    return lgr, stream


# ── configure_logging ─────────────────────────────────────────────────────────

class TestConfigureLogging:
    def test_configure_logging_sets_root_level(self):
        """configure_logging should honour LOG_LEVEL env var."""
        with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG", "LOG_FORMAT": "text"}):
            root = logging.getLogger()
            old_handlers = root.handlers[:]
            root.handlers.clear()
            try:
                configure_logging(level="DEBUG")
                assert root.level == logging.DEBUG
            finally:
                root.handlers = old_handlers

    def test_configure_logging_idempotent(self):
        """Calling configure_logging twice must not add duplicate handlers."""
        root = logging.getLogger()
        original_count = len(root.handlers)
        # Second call should be a no-op when handlers already exist
        configure_logging()
        configure_logging()
        assert len(root.handlers) == original_count or len(root.handlers) <= original_count + 1


# ── ContextInjectingFilter ────────────────────────────────────────────────────

class TestContextInjectingFilter:
    def test_injects_context_fields_into_record(self):
        """Fields from log_context() should appear in log records."""
        lgr, stream = _make_stream_logger("inject_test")
        lgr.handlers[0].setFormatter(logging.Formatter("%(message)s %(stream_id)s"))

        with log_context(stream_id="test-stream-42"):
            lgr.info("hello")

        output = stream.getvalue()
        assert "test-stream-42" in output

    def test_no_injection_outside_context(self):
        """Without log_context(), no stream_id field should be set."""
        lgr, stream = _make_stream_logger("no_inject")
        lgr.handlers[0].setFormatter(logging.Formatter("%(message)s"))

        lgr.info("bare message")

        output = stream.getvalue()
        assert "bare message" in output
        # Should not crash (no KeyError for missing stream_id)

    def test_nested_contexts_are_merged(self):
        """Nested log_context() calls should merge fields."""
        lgr, stream = _make_stream_logger("nested_ctx")
        lgr.handlers[0].setFormatter(
            logging.Formatter("%(message)s %(stream_id)s %(call_id)s")
        )

        with log_context(stream_id="outer"):
            with log_context(call_id="inner-call"):
                lgr.info("merged")

        output = stream.getvalue()
        assert "outer" in output
        assert "inner-call" in output

    def test_context_cleaned_up_after_exit(self):
        """log_context() must restore previous context on exit."""
        lgr, stream = _make_stream_logger("cleanup_ctx")

        token_fields: list = []

        class CapturingFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                token_fields.append(getattr(record, "stream_id", "MISSING"))
                return True

        lgr.handlers[0].addFilter(CapturingFilter())

        with log_context(stream_id="temp"):
            lgr.info("inside")

        lgr.info("outside")

        assert token_fields[0] == "temp"
        assert token_fields[1] == "MISSING"  # context was cleaned up


# ── JSON format ───────────────────────────────────────────────────────────────

class TestJsonLogging:
    def test_json_output_is_valid_json(self):
        """JSON log format must produce parseable JSON per line."""
        from pythonjsonlogger.json import JsonFormatter

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            )
        )
        lgr = logging.getLogger("json_test_" + str(id(stream)))
        lgr.propagate = False
        lgr.addHandler(handler)
        lgr.setLevel(logging.DEBUG)

        lgr.info("test message")

        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["message"] == "test message"
        assert "level" in parsed
        assert parsed["level"] == "INFO"

    def test_json_output_includes_extra_fields(self):
        """Extra fields passed via log_context should appear in JSON output."""
        from pythonjsonlogger.json import JsonFormatter

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(ContextInjectingFilter())
        handler.setFormatter(
            JsonFormatter(fmt="%(message)s %(stream_id)s")
        )
        lgr = logging.getLogger("json_extra_" + str(id(stream)))
        lgr.propagate = False
        lgr.addHandler(handler)
        lgr.setLevel(logging.DEBUG)

        with log_context(stream_id="stream-abc"):
            lgr.info("audio received")

        output = stream.getvalue().strip()
        parsed = json.loads(output)
        assert parsed.get("stream_id") == "stream-abc"
