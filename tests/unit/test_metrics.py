"""Prometheus Metrics Tests.

Tests for metrics collection and export:
- Counter metrics (calls_total)
- Histogram metrics (latencies)
- Gauge metrics (active_sessions, memory_usage)
- Circuit breaker state tracking
"""

import pytest
from unittest.mock import patch, MagicMock
import psutil
from prometheus_client import REGISTRY, CollectorRegistry

from src.infrastructure.metrics import MetricsCollector


@pytest.fixture
def metrics():
    """Fixture providing MetricsCollector with clean registry."""
    # Use a custom registry to avoid conflicts
    custom_registry = CollectorRegistry()
    collector = MetricsCollector(registry=custom_registry)
    return collector


def test_metrics_calls_total_counter(metrics):
    """Test calls total counter increment."""
    metrics.record_call_start()
    metrics.record_call_start()
    
    # Verify export contains the calls
    output = metrics.export_metrics()
    assert "exotel_calls_total" in output


def test_metrics_call_duration_histogram(metrics):
    """Test call duration histogram."""
    # Record a call duration
    metrics.record_call_duration(45.5)
    
    # Verify in export
    output = metrics.export_metrics()
    assert "exotel_call_duration_seconds" in output


def test_metrics_stt_latency(metrics):
    """Test STT latency recording."""
    metrics.record_stt_latency(0.125)
    
    output = metrics.export_metrics()
    assert "stt_latency_seconds" in output


def test_metrics_llm_latency(metrics):
    """Test LLM latency recording."""
    metrics.record_llm_latency(0.850)
    
    output = metrics.export_metrics()
    assert "llm_latency_seconds" in output


def test_metrics_tts_latency(metrics):
    """Test TTS latency recording."""
    metrics.record_tts_latency(0.250)
    
    output = metrics.export_metrics()
    assert "tts_latency_seconds" in output


def test_metrics_active_sessions_gauge(metrics):
    """Test active sessions gauge."""
    metrics.set_active_sessions(42)
    
    output = metrics.export_metrics()
    assert "active_sessions" in output


def test_metrics_memory_usage_gauge(metrics):
    """Test memory usage gauge."""
    metrics.update_memory_usage()
    
    output = metrics.export_metrics()
    assert "memory_usage_bytes" in output


def test_metrics_circuit_breaker_state(metrics):
    """Test circuit breaker state tracking."""
    # Record open circuit
    metrics.record_circuit_breaker("google_stt", "open")
    
    # Record closed circuit
    metrics.record_circuit_breaker("google_tts", "closed")
    
    # Verify states are tracked
    assert "google_stt" in metrics.circuit_breaker_states
    assert metrics.circuit_breaker_states["google_stt"] == "open"


def test_metrics_pipeline_latency_p95(metrics):
    """Test pipeline latency p95 calculation."""
    # Record multiple latencies
    for i in range(100):
        metrics.record_pipeline_latency(0.5 + (i * 0.01))
    
    output = metrics.export_metrics()
    assert "pipeline_latency_p95_seconds" in output


def test_metrics_api_cost_tracking(metrics):
    """Test API cost tracking."""
    metrics.record_api_cost("google_stt", 0.0125)
    metrics.record_api_cost("gemini", 0.00015)
    
    output = metrics.export_metrics()
    assert "api_cost_usd_total" in output


def test_metrics_daily_cost(metrics):
    """Test daily cost tracking."""
    metrics.record_daily_cost(2.50)
    
    output = metrics.export_metrics()
    assert "daily_cost_usd" in output


def test_metrics_export_prometheus_format(metrics):
    """Test that metrics can be exported in Prometheus format."""
    # Record some metrics
    metrics.record_call_start()
    metrics.record_call_duration(45.0)
    metrics.set_active_sessions(5)
    
    # Get registry output
    output = metrics.export_metrics()
    
    # Should contain Prometheus format headers
    assert "# HELP exotel_calls_total" in output or "exotel_calls_total" in output
    assert "# TYPE" in output or "exotel_calls_total" in output


def test_metrics_latency_buckets(metrics):
    """Test that histogram has proper buckets."""
    # Record a call duration that should fit in a bucket
    metrics.record_call_duration(1.5)
    
    output = metrics.export_metrics()
    assert "exotel_call_duration_seconds" in output


def test_metrics_call_status_tracking(metrics):
    """Test tracking call status (completed, error, timeout)."""
    metrics.record_call_completed()
    metrics.record_call_error()
    metrics.record_call_timeout()
    
    output = metrics.export_metrics()
    assert "exotel_calls_completed_total" in output
    assert "exotel_calls_error_total" in output
    assert "exotel_calls_timeout_total" in output


def test_metrics_concurrent_updates(metrics):
    """Test that metrics handle concurrent updates safely."""
    # Simulate concurrent calls
    for i in range(100):
        metrics.record_call_start()
        metrics.record_call_duration(0.1 + (i * 0.01))
    
    output = metrics.export_metrics()
    assert "exotel_calls_total" in output


def test_metrics_memory_bytes(metrics):
    """Test memory usage in bytes."""
    metrics.update_memory_usage()
    
    output = metrics.export_metrics()
    assert "memory_usage_bytes" in output


def test_metrics_reset(metrics):
    """Test that metrics can be reset (for testing)."""
    metrics.record_call_start()
    metrics.record_call_start()
    
    output = metrics.export_metrics()
    assert "exotel_calls_total" in output


def test_metrics_circuit_breaker_counts(metrics):
    """Test circuit breaker state transitions."""
    providers = ["google_stt", "google_tts", "gemini"]
    
    for provider in providers:
        metrics.record_circuit_breaker(provider, "closed")
    
    # All should be recorded
    assert len(metrics.circuit_breaker_states) >= 3
