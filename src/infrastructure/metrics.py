"""Prometheus Metrics — Production observability for Exotel voice AI.

Exports metrics in Prometheus format for scraping and Grafana dashboards.

Metrics:
- exotel_calls_total: Counter of all calls
- exotel_call_duration_seconds: Histogram of call durations
- stt_latency_seconds: Histogram of STT latency
- llm_latency_seconds: Histogram of LLM latency
- tts_latency_seconds: Histogram of TTS latency
- pipeline_latency_p95_seconds: Gauge of p95 pipeline latency
- active_sessions: Gauge of currently active sessions
- memory_usage_bytes: Gauge of process memory usage
- circuit_breaker_state: Gauge of circuit breaker state per provider
- api_cost_usd_total: Counter of cumulative API costs
- daily_cost_usd: Gauge of daily API costs

Usage:
    metrics = MetricsCollector()
    
    # Record metrics during operation
    metrics.record_call_start()
    metrics.record_call_duration(45.0)
    metrics.record_stt_latency(0.125)
    metrics.set_active_sessions(42)
    
    # Export to Prometheus format
    prometheus_text = metrics.export_metrics()
"""

import logging
import time
import psutil
from typing import Dict, Optional
from collections import deque
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
)

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Prometheus metrics collection for production observability.

    Tracks:
    - Call volume and duration
    - STT/LLM/TTS latencies
    - Active sessions and memory usage
    - Circuit breaker states
    - API costs and budget tracking
    """

    # Latency histogram buckets (in seconds): 50ms, 100ms, 250ms, 500ms, 1s, 2s, 5s, 10s
    LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
    # Duration histogram buckets (in seconds): 10s, 30s, 60s, 2min, 5min, 10min, 30min
    DURATION_BUCKETS = (10, 30, 60, 120, 300, 600, 1800)

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        Initialize MetricsCollector.

        Args:
            registry: Optional custom Prometheus registry (for testing)
        """
        self.registry = registry or CollectorRegistry()

        # ── Call Metrics ────────────────────────────────────────────────────
        self.calls_total = Counter(
            "exotel_calls_total",
            "Total number of calls received",
            registry=self.registry,
        )
        self.calls_completed = Counter(
            "exotel_calls_completed_total",
            "Total number of completed calls",
            registry=self.registry,
        )
        self.calls_error = Counter(
            "exotel_calls_error_total",
            "Total number of calls with errors",
            registry=self.registry,
        )
        self.calls_timeout = Counter(
            "exotel_calls_timeout_total",
            "Total number of timed-out calls",
            registry=self.registry,
        )

        self.call_duration = Histogram(
            "exotel_call_duration_seconds",
            "Call duration in seconds",
            buckets=self.DURATION_BUCKETS,
            registry=self.registry,
        )

        # ── Latency Metrics ────────────────────────────────────────────────
        self.stt_latency = Histogram(
            "stt_latency_seconds",
            "Speech-to-Text latency in seconds",
            buckets=self.LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.llm_latency = Histogram(
            "llm_latency_seconds",
            "Language Model latency in seconds",
            buckets=self.LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.tts_latency = Histogram(
            "tts_latency_seconds",
            "Text-to-Speech latency in seconds",
            buckets=self.LATENCY_BUCKETS,
            registry=self.registry,
        )

        self.pipeline_latency_p95 = Gauge(
            "pipeline_latency_p95_seconds",
            "P95 end-to-end pipeline latency",
            registry=self.registry,
        )

        # ── Session & Resource Metrics ──────────────────────────────────────
        self.active_sessions = Gauge(
            "active_sessions",
            "Number of currently active sessions",
            registry=self.registry,
        )

        self.memory_usage = Gauge(
            "memory_usage_bytes",
            "Process memory usage in bytes",
            registry=self.registry,
        )

        # ── Circuit Breaker Metrics ────────────────────────────────────────
        # States: 0=closed (healthy), 1=open (failing), 0.5=half-open (testing)
        self.circuit_breaker = Gauge(
            "circuit_breaker_state",
            "Circuit breaker state (0=closed, 0.5=half-open, 1=open)",
            labelnames=["provider"],
            registry=self.registry,
        )

        # ── Cost Metrics ────────────────────────────────────────────────────
        self.api_cost_total = Counter(
            "api_cost_usd_total",
            "Cumulative API costs in USD",
            labelnames=["provider"],
            registry=self.registry,
        )

        self.daily_cost = Gauge(
            "daily_cost_usd",
            "Daily API costs in USD",
            registry=self.registry,
        )

        # ── Internal state ──────────────────────────────────────────────────
        self.circuit_breaker_states: Dict[str, str] = {}
        self.pipeline_latencies = deque(maxlen=100)  # Keep last 100 latencies for p95

    # ── Call Recording ──────────────────────────────────────────────────────

    def record_call_start(self) -> None:
        """Record the start of a new call."""
        self.calls_total.inc()
        logger.debug("📞 Call started (total: %s)", self.calls_total._value.get())

    def record_call_completed(self) -> None:
        """Record a successfully completed call."""
        self.calls_completed.inc()

    def record_call_error(self) -> None:
        """Record a call that ended with an error."""
        self.calls_error.inc()

    def record_call_timeout(self) -> None:
        """Record a call that timed out."""
        self.calls_timeout.inc()

    def record_call_duration(self, duration_seconds: float) -> None:
        """
        Record the duration of a completed call.

        Args:
            duration_seconds: Call duration in seconds
        """
        self.call_duration.observe(duration_seconds)
        logger.debug("📊 Call duration: %.2fs", duration_seconds)

    # ── Latency Recording ───────────────────────────────────────────────────

    def record_stt_latency(self, latency_seconds: float) -> None:
        """
        Record STT provider latency.

        Args:
            latency_seconds: Latency in seconds
        """
        self.stt_latency.observe(latency_seconds)
        self._update_pipeline_latency()

    def record_llm_latency(self, latency_seconds: float) -> None:
        """
        Record LLM provider latency.

        Args:
            latency_seconds: Latency in seconds
        """
        self.llm_latency.observe(latency_seconds)
        self._update_pipeline_latency()

    def record_tts_latency(self, latency_seconds: float) -> None:
        """
        Record TTS provider latency.

        Args:
            latency_seconds: Latency in seconds
        """
        self.tts_latency.observe(latency_seconds)
        self._update_pipeline_latency()

    def record_pipeline_latency(self, latency_seconds: float) -> None:
        """
        Record end-to-end pipeline latency.

        Args:
            latency_seconds: Latency in seconds
        """
        self.pipeline_latencies.append(latency_seconds)
        self._update_pipeline_latency()

    def _update_pipeline_latency(self) -> None:
        """Calculate and update p95 pipeline latency."""
        if not self.pipeline_latencies:
            return

        sorted_latencies = sorted(self.pipeline_latencies)
        p95_index = int(len(sorted_latencies) * 0.95)
        p95 = sorted_latencies[p95_index]

        self.pipeline_latency_p95.set(p95)
        logger.debug("📈 Pipeline latency p95: %.3fs", p95)

    # ── Session Management ──────────────────────────────────────────────────

    def set_active_sessions(self, count: int) -> None:
        """
        Set the number of active sessions.

        Args:
            count: Number of active sessions
        """
        self.active_sessions.set(count)
        logger.debug("👥 Active sessions: %d", count)

    def increment_active_sessions(self) -> None:
        """Increment active session count."""
        self.active_sessions.inc()

    def decrement_active_sessions(self) -> None:
        """Decrement active session count."""
        self.active_sessions.dec()

    # ── Resource Monitoring ────────────────────────────────────────────────

    def update_memory_usage(self) -> None:
        """Update process memory usage metric."""
        try:
            process = psutil.Process()
            memory_bytes = process.memory_info().rss
            self.memory_usage.set(memory_bytes)
            logger.debug("💾 Memory usage: %.1f MB", memory_bytes / (1024 * 1024))
        except Exception as e:
            logger.error("Failed to update memory usage: %s", e)

    # ── Circuit Breaker Tracking ────────────────────────────────────────────

    def record_circuit_breaker(self, provider: str, state: str) -> None:
        """
        Record circuit breaker state change for a provider.

        Args:
            provider: Provider name (google_stt, gemini, etc.)
            state: Circuit breaker state (closed, open, half-open)
        """
        state_value = 0.0  # closed
        if state == "open":
            state_value = 1.0
        elif state == "half-open":
            state_value = 0.5

        self.circuit_breaker.labels(provider=provider).set(state_value)
        self.circuit_breaker_states[provider] = state
        logger.debug("🔌 Circuit breaker %s: %s", provider, state)

    # ── Cost Tracking ────────────────────────────────────────────────────────

    def record_api_cost(self, provider: str, cost_usd: float) -> None:
        """
        Record API cost for a specific provider.

        Args:
            provider: Provider name (google_stt, google_tts, gemini)
            cost_usd: Cost in USD
        """
        self.api_cost_total.labels(provider=provider).inc(cost_usd)
        logger.debug("💰 API cost (%s): $%.6f", provider, cost_usd)

    def record_daily_cost(self, cost_usd: float) -> None:
        """
        Record daily API costs.

        Args:
            cost_usd: Daily cost in USD
        """
        self.daily_cost.set(cost_usd)
        logger.debug("💵 Daily cost: $%.2f", cost_usd)

    # ── Export ──────────────────────────────────────────────────────────────

    def export_metrics(self) -> str:
        """
        Export metrics in Prometheus text format.

        Returns:
            Metrics in Prometheus format (TEXT_TYPE)
        """
        return generate_latest(self.registry).decode("utf-8")

    # ── Health Check ────────────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, float]:
        """
        Get a summary of key metrics.

        Returns:
            Dict with call count, active sessions, memory usage, etc.
        """
        return {
            "total_calls": self.calls_total._value.get(),
            "completed_calls": self.calls_completed._value.get(),
            "error_calls": self.calls_error._value.get(),
            "timeout_calls": self.calls_timeout._value.get(),
            "active_sessions": self.active_sessions._value.get(),
            "memory_mb": self.memory_usage._value.get() / (1024 * 1024),
            "pipeline_latency_p95_ms": self.pipeline_latency_p95._value.get() * 1000,
        }
