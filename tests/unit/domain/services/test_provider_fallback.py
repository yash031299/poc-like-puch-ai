"""Tests for Provider Fallback Strategy.

Tests cover:
- Provider switching and fallback logic
- Cost tracking across providers
- Budget enforcement
- Provider health status
- Error handling and recovery
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.services.provider_fallback import (
    ProviderFallback,
    ProviderStatus,
    ProviderMetrics,
)


@pytest.fixture
def provider_fallback():
    """Fixture providing ProviderFallback instance."""
    fallback = ProviderFallback(
        providers=["google", "openai"],
        budgets={"google": 1000.0, "openai": 1500.0},
    )
    return fallback


@pytest.fixture
def mock_adapters():
    """Fixture providing mock adapters."""
    google_adapter = AsyncMock()
    openai_adapter = AsyncMock()
    return {"google": google_adapter, "openai": openai_adapter}


class TestProviderFallbackInitialization:
    """Test ProviderFallback initialization."""

    def test_initialize_with_providers(self):
        """Test initialization with valid providers."""
        fallback = ProviderFallback(
            providers=["google", "openai"],
            budgets={"google": 1000.0, "openai": 1500.0},
        )
        assert fallback.providers == ["google", "openai"]
        assert fallback.get_current_provider() == "google"

    def test_initialize_with_no_providers_raises_error(self):
        """Test initialization with empty providers list."""
        with pytest.raises(ValueError):
            ProviderFallback(providers=[])

    def test_initialize_creates_metrics(self):
        """Test that metrics are initialized for each provider."""
        fallback = ProviderFallback(
            providers=["google", "openai"],
            budgets={"google": 500.0, "openai": 1000.0},
        )
        assert "google" in fallback.metrics
        assert "openai" in fallback.metrics
        assert fallback.metrics["google"].budget_usd == 500.0
        assert fallback.metrics["openai"].budget_usd == 1000.0


class TestProviderSwitching:
    """Test provider switching."""

    def test_get_current_provider(self, provider_fallback):
        """Test getting current provider."""
        current = provider_fallback.get_current_provider()
        assert current == "google"

    def test_set_current_provider_success(self, provider_fallback):
        """Test switching to a different provider."""
        result = provider_fallback.set_current_provider("openai")
        assert result is True
        assert provider_fallback.get_current_provider() == "openai"

    def test_set_current_provider_invalid(self, provider_fallback):
        """Test switching to invalid provider."""
        result = provider_fallback.set_current_provider("invalid")
        assert result is False

    def test_set_current_provider_budget_exceeded(self, provider_fallback):
        """Test that can't switch to provider with exceeded budget."""
        provider_fallback.metrics["openai"].monthly_cost_usd = 2000.0
        provider_fallback.metrics["openai"].budget_usd = 1500.0

        result = provider_fallback.set_current_provider("openai")
        assert result is False


class TestCostTracking:
    """Test cost tracking across providers."""

    def test_record_cost(self, provider_fallback):
        """Test recording cost for provider."""
        provider_fallback.record_cost("google", 5.0)
        assert provider_fallback.metrics["google"].total_cost_usd == 5.0
        assert provider_fallback.metrics["google"].monthly_cost_usd == 5.0

    def test_record_multiple_costs(self, provider_fallback):
        """Test recording multiple costs."""
        provider_fallback.record_cost("google", 5.0)
        provider_fallback.record_cost("google", 3.0)
        provider_fallback.record_cost("openai", 2.0)

        assert provider_fallback.metrics["google"].total_cost_usd == 8.0
        assert provider_fallback.metrics["openai"].total_cost_usd == 2.0
        assert provider_fallback.metrics["google"].monthly_cost_usd == 8.0

    def test_budget_percentage(self, provider_fallback):
        """Test budget percentage calculation."""
        provider_fallback.record_cost("google", 500.0)
        percentage = provider_fallback.get_budget_percentage("google")
        assert percentage == 50.0

    def test_is_budget_exceeded(self, provider_fallback):
        """Test budget exceeded detection."""
        assert not provider_fallback.is_budget_exceeded("google")

        provider_fallback.record_cost("google", 1500.0)
        assert provider_fallback.is_budget_exceeded("google")


class TestProviderFallback:
    """Test fallback operations."""

    @pytest.mark.asyncio
    async def test_call_with_fallback_primary_success(
        self,
        provider_fallback,
        mock_adapters,
    ):
        """Test successful call on primary provider."""
        provider_fallback.register_adapter("google", mock_adapters["google"])
        provider_fallback.register_adapter("openai", mock_adapters["openai"])

        mock_adapters["google"].transcribe = AsyncMock(return_value="transcribed")

        result = await provider_fallback.call_with_fallback(
            "transcribe", b"audio_data"
        )
        assert result == "transcribed"
        assert provider_fallback.metrics["google"].success_count == 1

    @pytest.mark.asyncio
    async def test_call_with_fallback_primary_fails_fallback(
        self,
        provider_fallback,
        mock_adapters,
    ):
        """Test fallback when primary provider fails."""
        provider_fallback.register_adapter("google", mock_adapters["google"])
        provider_fallback.register_adapter("openai", mock_adapters["openai"])

        mock_adapters["google"].transcribe = AsyncMock(
            side_effect=Exception("Google down")
        )
        mock_adapters["openai"].transcribe = AsyncMock(return_value="fallback_result")

        result = await provider_fallback.call_with_fallback(
            "transcribe", b"audio_data"
        )
        assert result == "fallback_result"
        assert provider_fallback.metrics["google"].error_count == 1
        assert provider_fallback.metrics["openai"].success_count == 1

    @pytest.mark.asyncio
    async def test_call_with_fallback_all_fail(
        self,
        provider_fallback,
        mock_adapters,
    ):
        """Test when all providers fail."""
        provider_fallback.register_adapter("google", mock_adapters["google"])
        provider_fallback.register_adapter("openai", mock_adapters["openai"])

        mock_adapters["google"].transcribe = AsyncMock(
            side_effect=Exception("Google down")
        )
        mock_adapters["openai"].transcribe = AsyncMock(
            side_effect=Exception("OpenAI down")
        )

        result = await provider_fallback.call_with_fallback(
            "transcribe", b"audio_data"
        )
        assert result is None
        assert provider_fallback.metrics["google"].error_count == 1
        assert provider_fallback.metrics["openai"].error_count == 1

    @pytest.mark.asyncio
    async def test_call_without_fallback(
        self,
        provider_fallback,
        mock_adapters,
    ):
        """Test call without fallback enabled."""
        provider_fallback.fallback_enabled = False
        provider_fallback.register_adapter("google", mock_adapters["google"])

        mock_adapters["google"].transcribe = AsyncMock(return_value="result")

        result = await provider_fallback.call_with_fallback(
            "transcribe", b"audio_data"
        )
        assert result == "result"


class TestProviderStatus:
    """Test provider status reporting."""

    def test_get_provider_status_single(self, provider_fallback):
        """Test getting status for single provider."""
        provider_fallback.record_cost("google", 100.0)
        status = provider_fallback.get_provider_status("google")

        assert status["provider"] == "google"
        assert status["total_cost_usd"] == 100.0
        assert status["budget_usd"] == 1000.0
        assert status["budget_percentage"] == 10.0
        assert not status["budget_exceeded"]

    def test_get_provider_status_all(self, provider_fallback):
        """Test getting status for all providers."""
        provider_fallback.record_cost("google", 100.0)
        provider_fallback.record_cost("openai", 50.0)

        status_all = provider_fallback.get_provider_status()

        assert "google" in status_all
        assert "openai" in status_all
        assert status_all["google"]["total_cost_usd"] == 100.0
        assert status_all["openai"]["total_cost_usd"] == 50.0

    def test_get_cost_comparison(self, provider_fallback):
        """Test cost comparison across providers."""
        provider_fallback.record_cost("google", 100.0)
        provider_fallback.record_cost("openai", 150.0)

        comparison = provider_fallback.get_cost_comparison()

        assert comparison["cheapest"] == "google"
        assert comparison["most_expensive"] == "openai"
        assert comparison["total_cost_usd"] == 250.0


class TestErrorHandling:
    """Test error handling and recovery."""

    def test_record_error(self, provider_fallback):
        """Test error recording."""
        provider_fallback._record_error("google", "Connection timeout")

        metrics = provider_fallback.metrics["google"]
        assert metrics.error_count == 1
        assert metrics.last_error == "Connection timeout"
        assert metrics.call_count == 1

    def test_provider_degraded_on_high_error_rate(self, provider_fallback):
        """Test provider marked as degraded on high error rate."""
        for _ in range(5):
            provider_fallback._record_error("google", "Error")

        metrics = provider_fallback.metrics["google"]
        assert metrics.error_count == 5
        assert metrics.status == ProviderStatus.DEGRADED

    def test_record_success(self, provider_fallback):
        """Test success recording."""
        provider_fallback._record_success("google")

        metrics = provider_fallback.metrics["google"]
        assert metrics.success_count == 1
        assert metrics.status == ProviderStatus.HEALTHY


class TestCostReset:
    """Test cost resets."""

    def test_reset_daily_costs(self, provider_fallback):
        """Test resetting daily costs."""
        provider_fallback.record_cost("google", 100.0)
        provider_fallback.record_cost("openai", 50.0)

        provider_fallback.reset_daily_costs()

        assert provider_fallback.metrics["google"].daily_cost_usd == 0.0
        assert provider_fallback.metrics["openai"].daily_cost_usd == 0.0

    def test_reset_monthly_costs(self, provider_fallback):
        """Test resetting monthly costs."""
        provider_fallback.record_cost("google", 100.0)

        provider_fallback.reset_monthly_costs()

        assert provider_fallback.metrics["google"].monthly_cost_usd == 0.0


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_unknown_provider_cost_recording(self, provider_fallback):
        """Test recording cost for unknown provider."""
        provider_fallback.record_cost("unknown", 10.0)
        # Should handle gracefully without error

    def test_zero_budget(self):
        """Test with zero budget."""
        fallback = ProviderFallback(
            providers=["google"],
            budgets={"google": 0.0},
        )
        assert fallback.metrics["google"].budget_usd == 0.0
        assert not fallback.is_budget_exceeded("google")

    def test_very_high_budget(self):
        """Test with very high budget."""
        fallback = ProviderFallback(
            providers=["google"],
            budgets={"google": 1_000_000.0},
        )
        fallback.record_cost("google", 50000.0)
        assert not fallback.is_budget_exceeded("google")
        assert fallback.get_budget_percentage("google") == 5.0
