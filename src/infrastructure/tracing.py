"""
OpenTelemetry distributed tracing configuration and utilities.

Provides:
  - OTel tracer initialization with OTLP exporter
  - Trace context extraction from WebSocket headers
  - Trace decorator for use_cases
  - Trace ID propagation through call pipeline

Usage:
    from src.infrastructure.tracing import get_tracer, init_tracing

    # At startup:
    init_tracing()

    # In use_cases:
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("operation_name") as span:
        span.set_attribute("user.id", user_id)
        # ... do work ...
"""

import functools
import logging
import os
from contextvars import ContextVar
from typing import Any, Callable, Optional, TypeVar

from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)

# ── Global tracer instance ──────────────────────────────────────────────────
_tracer_provider: Optional[TracerProvider] = None
_current_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

F = TypeVar("F", bound=Callable[..., Any])


def init_tracing(
    jaeger_agent_host: str = "localhost",
    jaeger_agent_port: int = 6831,
    service_name: str = "puch-ai-voice-server",
    sample_rate: float = 0.01,  # 1% sampling by default
) -> None:
    """
    Initialize OpenTelemetry with OTLP exporter (compatible with Jaeger).

    Args:
        jaeger_agent_host: Jaeger agent hostname (used for OTLP endpoint)
        jaeger_agent_port: Jaeger agent port (for OTLP gRPC: typically 4317)
        service_name: Service name for traces
        sample_rate: Sampling rate (0.0 to 1.0, default 0.01 = 1%)

    Environment variables:
        JAEGER_AGENT_HOST: Override jaeger_agent_host
        JAEGER_AGENT_PORT: Override jaeger_agent_port (for OTLP gRPC)
        JAEGER_SERVICE_NAME: Override service_name
        OTEL_SAMPLE_RATE: Override sample_rate (0.0 to 1.0)
        OTEL_EXPORTER_OTLP_ENDPOINT: Override OTLP endpoint
    """
    global _tracer_provider

    # Read from environment
    jaeger_agent_host = os.getenv("JAEGER_AGENT_HOST", jaeger_agent_host)
    jaeger_agent_port = int(os.getenv("JAEGER_AGENT_PORT", "4317"))  # OTLP gRPC default
    service_name = os.getenv("JAEGER_SERVICE_NAME", service_name)
    sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", sample_rate))
    
    # OTLP endpoint
    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        f"http://{jaeger_agent_host}:{jaeger_agent_port}"
    )

    try:
        # Create OTLP exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=True,  # Allow insecure connections for local testing
        )

        # Create tracer provider with sampling
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        _tracer_provider = TracerProvider(sampler=TraceIdRatioBased(sample_rate))
        _tracer_provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(_tracer_provider)

        logger.info(
            f"OpenTelemetry initialized: "
            f"service={service_name}, "
            f"otlp_endpoint={otlp_endpoint}, "
            f"sample_rate={sample_rate}"
        )
    except Exception as e:
        logger.warning(f"Failed to initialize OTLP exporter: {e}. Tracing disabled.")
        # Fallback to no-op tracer
        _tracer_provider = TracerProvider(sampler=TraceIdRatioBased(sample_rate))
        trace.set_tracer_provider(_tracer_provider)


def get_tracer(name: str) -> trace.Tracer:
    """Get or create a named tracer."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        logger.warning("Tracer provider not initialized, using default")
    return trace.get_tracer(name)


def set_trace_id(trace_id: str) -> None:
    """Set the current trace ID in context."""
    _current_trace_id.set(trace_id)


def get_trace_id() -> Optional[str]:
    """Get the current trace ID from context."""
    return _current_trace_id.get()


def extract_trace_context_from_headers(headers: dict) -> Optional[str]:
    """
    Extract W3C Trace Context from WebSocket headers.

    Looks for:
      - traceparent (W3C format: version-trace_id-parent_id-flags)
      - stream_sid (fallback, use as trace ID)

    Returns:
        Extracted trace ID or None
    """
    # W3C Trace Context: traceparent = "00-<trace_id>-<parent_id>-<flags>"
    traceparent = headers.get("traceparent") or headers.get("Traceparent")
    if traceparent:
        try:
            parts = traceparent.split("-")
            if len(parts) >= 2:
                return parts[1]
        except Exception:
            pass

    # Fallback: use stream_sid if available
    stream_sid = headers.get("stream_sid") or headers.get("Stream-Sid")
    if stream_sid:
        return stream_sid

    return None


def inject_trace_context_to_headers(headers: dict, trace_id: Optional[str] = None) -> dict:
    """
    Inject current trace context into headers for outgoing requests.

    Args:
        headers: Dictionary of headers
        trace_id: Optional override for trace ID

    Returns:
        Updated headers dict
    """
    if trace_id is None:
        trace_id = get_trace_id()

    if trace_id:
        # W3C Trace Context format
        headers["traceparent"] = f"00-{trace_id}-0000000000000000-01"

    return headers


def traced_use_case(func: F) -> F:
    """
    Decorator to automatically create spans for use_case methods.

    Extracts stream_id from first argument and sets as span attribute.

    Usage:
        @traced_use_case
        async def execute(self, stream_id: str, ...):
            ...
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer(func.__module__)
        use_case_name = args[0].__class__.__name__ if args else "unknown"
        operation = func.__name__

        with tracer.start_as_current_span(f"{use_case_name}.{operation}") as span:
            # Extract stream_id from args or kwargs
            stream_id = None
            if len(args) > 1:
                stream_id = args[1]
            elif "stream_id" in kwargs:
                stream_id = kwargs["stream_id"]

            if stream_id:
                span.set_attribute("stream_id", stream_id)
                set_trace_id(stream_id)

            span.set_attribute("use_case", use_case_name)

            try:
                result = await func(*args, **kwargs)
                span.set_attribute("status", "success")
                return result
            except Exception as e:
                span.set_attribute("status", "error")
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer(func.__module__)
        use_case_name = args[0].__class__.__name__ if args else "unknown"
        operation = func.__name__

        with tracer.start_as_current_span(f"{use_case_name}.{operation}") as span:
            # Extract stream_id from args or kwargs
            stream_id = None
            if len(args) > 1:
                stream_id = args[1]
            elif "stream_id" in kwargs:
                stream_id = kwargs["stream_id"]

            if stream_id:
                span.set_attribute("stream_id", stream_id)
                set_trace_id(stream_id)

            span.set_attribute("use_case", use_case_name)

            try:
                result = func(*args, **kwargs)
                span.set_attribute("status", "success")
                return result
            except Exception as e:
                span.set_attribute("status", "error")
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    # Return async wrapper for async functions, sync for sync
    if getattr(func, "__isabstractmethod__", False):
        return func  # type: ignore
    return async_wrapper if "async" in func.__code__.co_names else sync_wrapper  # type: ignore


def traced_adapter_call(span_name: str, **span_attributes: Any) -> Callable[[F], F]:
    """
    Decorator for adapter external calls (STT, TTS, LLM, etc).

    Usage:
        @traced_adapter_call("google.stt", provider="google", language="en")
        async def transcribe(self, audio: bytes) -> str:
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name) as span:
                for key, value in span_attributes.items():
                    span.set_attribute(key, value)

                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name) as span:
                for key, value in span_attributes.items():
                    span.set_attribute(key, value)

                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    span.set_attribute("status", "error")
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return async_wrapper if "async" in func.__code__.co_names else sync_wrapper  # type: ignore

    return decorator
