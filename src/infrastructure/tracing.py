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
import socket
from contextvars import ContextVar
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import urlparse

try:
    from opentelemetry import trace, context
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.trace import Status, StatusCode
    _OTEL_AVAILABLE = True
except ModuleNotFoundError:
    trace = None  # type: ignore
    context = None  # type: ignore
    TracerProvider = object  # type: ignore
    SimpleSpanProcessor = None  # type: ignore
    OTLPSpanExporter = None  # type: ignore
    Status = None  # type: ignore
    StatusCode = None  # type: ignore
    _OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Global tracer instance ──────────────────────────────────────────────────
_tracer_provider: Optional[TracerProvider] = None
_current_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

F = TypeVar("F", bound=Callable[..., Any])


class _NoOpSpan:
    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _NoOpTracer:
    def start_as_current_span(self, _name: str) -> _NoOpSpan:
        return _NoOpSpan()


_NOOP_TRACER = _NoOpTracer()


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


def _is_otlp_endpoint_reachable(endpoint: str, timeout_s: float = 0.25) -> bool:
    """Best-effort check to avoid OTLP retry noise when no collector exists."""
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return False
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _bind_tracer_provider(provider: TracerProvider) -> TracerProvider:
    """
    Bind provider only when no SDK provider is currently active.

    This avoids repeated "Overriding of current TracerProvider is not allowed"
    warnings when tracing initialization is attempted multiple times.
    """
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current
    trace.set_tracer_provider(provider)
    return provider


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

    if not _OTEL_AVAILABLE:
        logger.info("OpenTelemetry package not installed; tracing disabled.")
        return

    # Explicit global switch for environments/modes that should not export traces.
    if not _is_truthy(os.getenv("OTEL_ENABLED", "true")):
        logger.info("OTEL_ENABLED=false; tracing disabled.")
        return

    # Reuse existing provider if already initialized in this process.
    if _tracer_provider is not None:
        logger.debug("Tracing already initialized; skipping re-initialization.")
        return
    existing_provider = trace.get_tracer_provider()
    if isinstance(existing_provider, TracerProvider):
        _tracer_provider = existing_provider
        logger.debug("Tracing provider already configured; reusing existing provider.")
        return

    # Read from environment
    jaeger_agent_host = os.getenv("JAEGER_AGENT_HOST", jaeger_agent_host)
    jaeger_agent_port = int(os.getenv("JAEGER_AGENT_PORT", "4317"))  # OTLP gRPC default
    service_name = os.getenv("JAEGER_SERVICE_NAME", service_name)
    sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", sample_rate))
    sample_rate = max(0.0, min(1.0, sample_rate))

    # OTLP endpoint
    otlp_endpoint_env = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    otlp_endpoint = otlp_endpoint_env or f"http://{jaeger_agent_host}:{jaeger_agent_port}"
    exporter_enabled = _is_truthy(os.getenv("OTEL_EXPORTER_ENABLED", "true"))

    # If using default localhost endpoint and collector is absent, disable exporter
    # to avoid repetitive UNAVAILABLE retry logs in runtime.
    if exporter_enabled and not otlp_endpoint_env and jaeger_agent_host in ("localhost", "127.0.0.1"):
        if not _is_otlp_endpoint_reachable(otlp_endpoint):
            exporter_enabled = False
            logger.info(
                "OTLP collector not reachable at %s; initializing tracing without exporter.",
                otlp_endpoint,
            )

    try:
        # Create tracer provider with sampling
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        _tracer_provider = TracerProvider(sampler=TraceIdRatioBased(sample_rate))
        if exporter_enabled:
            otlp_exporter = OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=True,  # Allow insecure connections for local testing
            )
            _tracer_provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
        _tracer_provider = _bind_tracer_provider(_tracer_provider)

        logger.info(
            "OpenTelemetry initialized: service=%s sample_rate=%s exporter=%s endpoint=%s",
            service_name,
            sample_rate,
            "enabled" if exporter_enabled else "disabled",
            otlp_endpoint,
        )
    except Exception as e:
        logger.warning("Failed to initialize tracing exporter: %s. Tracing running without exporter.", e)
        # Fallback to local provider without exporter.
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        _tracer_provider = TracerProvider(sampler=TraceIdRatioBased(sample_rate))
        _tracer_provider = _bind_tracer_provider(_tracer_provider)


def get_tracer(name: str) -> Any:
    """
    Get or create a named tracer.
    
    In DEV_MODE, returns a no-op tracer to avoid warnings about uninitialized provider.
    """
    if not _OTEL_AVAILABLE:
        return _NOOP_TRACER

    # Explicitly disable tracing in low-overhead/test modes.
    if (
        os.getenv("DEV_MODE", "").lower() == "true"
        or os.getenv("POC_SIMPLE_LLM_MODE", "").lower() == "true"
        or not _is_truthy(os.getenv("OTEL_ENABLED", "true"))
    ):
        return _NOOP_TRACER
    
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        logger.warning("Tracer provider not initialized, using default")
    return trace.get_tracer(name)


def set_trace_id(trace_id: Optional[str]) -> None:
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
                if _OTEL_AVAILABLE and Status is not None and StatusCode is not None:
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
                if _OTEL_AVAILABLE and Status is not None and StatusCode is not None:
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
                    if _OTEL_AVAILABLE and Status is not None and StatusCode is not None:
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
                    if _OTEL_AVAILABLE and Status is not None and StatusCode is not None:
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return async_wrapper if "async" in func.__code__.co_names else sync_wrapper  # type: ignore

    return decorator
