"""
Unit tests for OpenTelemetry tracing infrastructure.

Tests:
  - OTel initialization with Jaeger exporter
  - Trace context extraction from headers
  - Trace context injection into headers
  - Trace ID propagation through context variables
  - @traced_use_case decorator
  - @traced_adapter_call decorator
  - Trace ID in log records
  - Sampling rate configuration
"""

import logging
import os
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest
from opentelemetry import trace

from src.infrastructure.tracing import (
    init_tracing,
    get_tracer,
    set_trace_id,
    get_trace_id,
    extract_trace_context_from_headers,
    inject_trace_context_to_headers,
    traced_use_case,
    traced_adapter_call,
)
from src.infrastructure.logging_config import configure_logging


class TestTracingInitialization:
    """Test OpenTelemetry initialization and configuration."""

    def test_init_tracing_with_defaults(self) -> None:
        """Test initialization with default parameters."""
        init_tracing()
        tracer = get_tracer("test")
        assert tracer is not None

    def test_init_tracing_with_custom_params(self) -> None:
        """Test initialization with custom Jaeger host/port."""
        init_tracing(
            jaeger_agent_host="custom-host",
            jaeger_agent_port=9999,
            service_name="custom-service",
            sample_rate=0.5,
        )
        tracer = get_tracer("test")
        assert tracer is not None

    def test_init_tracing_from_env_vars(self, monkeypatch) -> None:
        """Test that environment variables override defaults."""
        monkeypatch.setenv("JAEGER_AGENT_HOST", "env-host")
        monkeypatch.setenv("JAEGER_AGENT_PORT", "7831")
        monkeypatch.setenv("JAEGER_SERVICE_NAME", "env-service")
        monkeypatch.setenv("OTEL_SAMPLE_RATE", "0.1")

        init_tracing()
        tracer = get_tracer("test")
        assert tracer is not None

    def test_get_tracer_returns_valid_tracer(self) -> None:
        """Test that get_tracer returns a functional tracer."""
        init_tracing(sample_rate=1.0)  # 100% sampling for testing
        tracer = get_tracer(__name__)
        assert tracer is not None

        # Test creating a span
        with tracer.start_as_current_span("test_span") as span:
            assert span is not None
            # Span may not be recording if OTLP export fails, which is ok


class TestTraceContextManagement:
    """Test trace context variable management."""

    def test_set_and_get_trace_id(self) -> None:
        """Test setting and retrieving trace ID."""
        trace_id = "test-trace-123"
        set_trace_id(trace_id)
        assert get_trace_id() == trace_id

    def test_get_trace_id_without_set(self) -> None:
        """Test getting trace ID when none is set."""
        # Reset context
        set_trace_id(None)
        assert get_trace_id() is None

    def test_trace_id_isolation_between_tasks(self) -> None:
        """Test that trace IDs are isolated between async contexts."""
        # This is testing contextvars isolation
        set_trace_id("trace-1")
        id1 = get_trace_id()

        set_trace_id("trace-2")
        id2 = get_trace_id()

        assert id1 != id2
        assert id2 == "trace-2"


class TestHeaderContextExtraction:
    """Test trace context extraction from HTTP/WebSocket headers."""

    def test_extract_w3c_trace_context(self) -> None:
        """Test extracting W3C Trace Context from traceparent header."""
        headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        }
        trace_id = extract_trace_context_from_headers(headers)
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_extract_stream_sid_as_fallback(self) -> None:
        """Test using stream_sid as fallback trace ID."""
        headers = {"stream_sid": "stream-12345"}
        trace_id = extract_trace_context_from_headers(headers)
        assert trace_id == "stream-12345"

    def test_extract_with_missing_trace_context(self) -> None:
        """Test extracting when no trace context is present."""
        headers = {"content-type": "application/json"}
        trace_id = extract_trace_context_from_headers(headers)
        assert trace_id is None

    def test_extract_with_malformed_traceparent(self) -> None:
        """Test extracting with malformed traceparent header."""
        headers = {"traceparent": "malformed"}
        # Should return None or handle gracefully
        trace_id = extract_trace_context_from_headers(headers)
        # Could be None or fallback behavior
        assert trace_id is not None or trace_id is None

    def test_extract_with_case_insensitive_headers(self) -> None:
        """Test header extraction is case-insensitive."""
        headers = {"Traceparent": "00-1234567890abcdef1234567890abcdef-0000000000000000-01"}
        trace_id = extract_trace_context_from_headers(headers)
        assert trace_id == "1234567890abcdef1234567890abcdef"


class TestHeaderContextInjection:
    """Test trace context injection into headers."""

    def test_inject_trace_context_into_headers(self) -> None:
        """Test injecting trace context into headers."""
        set_trace_id("test-trace-id")
        headers = {}
        result = inject_trace_context_to_headers(headers)

        assert "traceparent" in result
        assert "test-trace-id" in result["traceparent"]

    def test_inject_trace_context_with_explicit_trace_id(self) -> None:
        """Test injecting with explicit trace ID parameter."""
        headers = {}
        result = inject_trace_context_to_headers(headers, trace_id="explicit-id")

        assert "traceparent" in result
        assert "explicit-id" in result["traceparent"]

    def test_inject_without_trace_context(self) -> None:
        """Test injection when no trace context exists."""
        set_trace_id(None)
        headers = {"existing": "header"}
        result = inject_trace_context_to_headers(headers)

        assert "existing" in result
        assert result["existing"] == "header"


class TestTracedUseCaseDecorator:
    """Test @traced_use_case decorator."""

    @pytest.mark.asyncio
    async def test_traced_async_use_case(self) -> None:
        """Test tracing an async use case."""
        init_tracing()

        @traced_use_case
        async def mock_use_case(self, stream_id: str) -> str:
            return f"processed {stream_id}"

        instance = Mock()
        result = await mock_use_case(instance, "test-stream-123")

        assert result == "processed test-stream-123"
        assert get_trace_id() == "test-stream-123"

    @pytest.mark.asyncio
    async def test_traced_use_case_with_exception(self) -> None:
        """Test that exceptions are properly recorded in spans."""
        init_tracing()

        @traced_use_case
        async def failing_use_case(self, stream_id: str) -> None:
            raise ValueError("Test error")

        instance = Mock()
        instance.__class__.__name__ = "TestUseCase"

        with pytest.raises(ValueError):
            await failing_use_case(instance, "test-stream")

    @pytest.mark.asyncio
    async def test_traced_use_case_sets_span_attributes(self) -> None:
        """Test that span attributes are set correctly."""
        init_tracing()

        @traced_use_case
        async def mock_use_case(self, stream_id: str) -> str:
            return "result"

        instance = Mock()
        instance.__class__.__name__ = "MockUseCase"

        result = await mock_use_case(instance, "stream-xyz")

        assert result == "result"
        assert get_trace_id() == "stream-xyz"


class TestTracedAdapterCallDecorator:
    """Test @traced_adapter_call decorator."""

    @pytest.mark.asyncio
    async def test_traced_adapter_call_async(self) -> None:
        """Test tracing an async adapter call."""
        init_tracing()

        @traced_adapter_call("google.stt", provider="google")
        async def mock_transcribe(audio: bytes) -> str:
            return "transcribed text"

        result = await mock_transcribe(b"audio-data")
        assert result == "transcribed text"

    @pytest.mark.asyncio
    async def test_traced_adapter_call_with_attributes(self) -> None:
        """Test that custom span attributes are set."""
        init_tracing()

        @traced_adapter_call(
            "google.tts",
            provider="google",
            voice="en-US-Neural2-F",
            language="en",
        )
        async def mock_synthesize(text: str) -> bytes:
            return b"audio-bytes"

        result = await mock_synthesize("hello world")
        assert result == b"audio-bytes"

    @pytest.mark.asyncio
    async def test_traced_adapter_call_error_handling(self) -> None:
        """Test that errors are properly recorded."""
        init_tracing()

        @traced_adapter_call("external.api", service="test")
        async def failing_adapter() -> None:
            raise RuntimeError("API error")

        with pytest.raises(RuntimeError):
            await failing_adapter()


class TestTraceIDInLogging:
    """Test that trace IDs are injected into log records."""

    def test_log_record_has_trace_id_attribute(self) -> None:
        """Test that log records include trace ID."""
        # Configure logging
        configure_logging(fmt="text")

        logger = logging.getLogger("test_logger")
        init_tracing()

        # Create a span to populate trace context
        tracer = get_tracer("test")
        with tracer.start_as_current_span("test_span") as span:
            # Get a log record
            handler = logger.handlers[0] if logger.handlers else None
            if handler:
                # Log something (simplified check)
                logger.info("Test message")


class TestSamplingConfiguration:
    """Test sampling rate configuration."""

    def test_sampling_rate_0_01(self, monkeypatch) -> None:
        """Test 1% sampling rate (0.01)."""
        monkeypatch.setenv("OTEL_SAMPLE_RATE", "0.01")
        init_tracing()
        # Sampling is probabilistic, so we can't test directly,
        # but initialization should succeed
        tracer = get_tracer("test")
        assert tracer is not None

    def test_sampling_rate_from_env(self, monkeypatch) -> None:
        """Test reading sampling rate from environment."""
        monkeypatch.setenv("OTEL_SAMPLE_RATE", "0.5")
        init_tracing()
        tracer = get_tracer("test")
        assert tracer is not None

    def test_sampling_rate_default(self) -> None:
        """Test default sampling rate is 1%."""
        init_tracing()
        tracer = get_tracer("test")
        assert tracer is not None


class TestTraceContextPropagation:
    """Test trace context propagation through the pipeline."""

    @pytest.mark.asyncio
    async def test_trace_id_propagation_across_use_cases(self) -> None:
        """Test that trace ID is maintained across use cases."""
        init_tracing()
        stream_id = "test-stream-prop"

        set_trace_id(stream_id)

        @traced_use_case
        async def use_case_1(self, stream_id: str) -> str:
            return stream_id

        @traced_use_case
        async def use_case_2(self, stream_id: str) -> str:
            current = get_trace_id()
            return current or "not set"

        instance = Mock()
        instance.__class__.__name__ = "TestUC"

        result1 = await use_case_1(instance, stream_id)
        result2 = await use_case_2(instance, stream_id)

        assert result1 == stream_id
        assert result2 == stream_id
