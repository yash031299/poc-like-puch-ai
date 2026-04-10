"""Provider Fallback Strategy — Intelligent provider rotation with cost tracking.

Implements multi-provider fallback for STT, LLM, and TTS with:
- Automatic provider rotation based on availability
- Per-provider cost tracking and budget management
- Transparent switching to minimize latency
- Provider health monitoring and status reporting

Usage:
    fallback = ProviderFallback(
        providers=["google", "openai"],
        budgets={"google": 100.0, "openai": 150.0}
    )
    
    # Use primary provider, fallback automatically if needed
    result = await fallback.call_stt(audio_bytes)
    
    # Check provider health
    status = fallback.get_provider_status()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Provider health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class ProviderMetrics:
    """Metrics for a single provider."""
    name: str
    total_cost_usd: float = 0.0
    daily_cost_usd: float = 0.0
    monthly_cost_usd: float = 0.0
    budget_usd: float = 1000.0
    call_count: int = 0
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    status: ProviderStatus = ProviderStatus.HEALTHY
    last_status_check: datetime = field(default_factory=datetime.now)


class ProviderFallback:
    """
    Multi-provider fallback strategy with cost and budget management.
    
    Supports transparent switching between providers (Google, OpenAI, etc.)
    with cost tracking and budget enforcement per provider.
    """

    def __init__(
        self,
        providers: List[str],
        budgets: Optional[Dict[str, float]] = None,
        cost_thresholds: Optional[Dict[str, float]] = None,
        fallback_enabled: bool = True,
    ):
        """
        Initialize ProviderFallback.

        Args:
            providers: List of provider names in priority order
            budgets: Dict mapping provider to monthly budget in USD
            cost_thresholds: Dict mapping provider to cost threshold before switching
            fallback_enabled: Whether automatic fallback is enabled
        """
        if not providers:
            raise ValueError("At least one provider must be specified")

        self.providers = providers
        self.fallback_enabled = fallback_enabled
        self.current_provider_index = 0
        
        # Initialize metrics for each provider
        self.metrics: Dict[str, ProviderMetrics] = {}
        for provider in providers:
            budget = budgets.get(provider, 1000.0) if budgets else 1000.0
            self.metrics[provider] = ProviderMetrics(
                name=provider,
                budget_usd=budget,
            )
        
        self.cost_thresholds = cost_thresholds or {
            p: budgets.get(p, 1000.0) * 0.8
            if budgets
            else 800.0
            for p in providers
        }
        
        # Provider adapters (set by caller)
        self.provider_adapters: Dict[str, Any] = {}

    def register_adapter(
        self,
        provider: str,
        adapter: Any,
    ) -> None:
        """
        Register a provider adapter.

        Args:
            provider: Provider name
            adapter: Adapter instance (STT, LLM, or TTS)
        """
        if provider not in self.providers:
            logger.warning(f"Provider {provider} not in configured providers")
        self.provider_adapters[provider] = adapter
        logger.debug(f"Registered adapter for provider: {provider}")

    def get_current_provider(self) -> str:
        """Get the current active provider."""
        return self.providers[self.current_provider_index]

    def set_current_provider(self, provider: str) -> bool:
        """
        Manually switch to a specific provider.

        Args:
            provider: Provider name

        Returns:
            True if switch successful, False if provider not available
        """
        if provider not in self.providers:
            logger.error(f"Provider {provider} not configured")
            return False

        if self.is_budget_exceeded(provider):
            logger.warning(
                f"Cannot switch to {provider}: budget exceeded "
                f"(${self.metrics[provider].monthly_cost_usd:.2f} "
                f"> ${self.metrics[provider].budget_usd:.2f})"
            )
            return False

        self.current_provider_index = self.providers.index(provider)
        logger.info(f"Switched to provider: {provider}")
        return True

    async def call_with_fallback(
        self,
        operation: str,
        *args,
        **kwargs,
    ) -> Optional[Any]:
        """
        Execute an operation with automatic fallback.

        Args:
            operation: Operation name (e.g., "transcribe", "generate", "synthesize")
            *args: Positional arguments for the operation
            **kwargs: Keyword arguments for the operation

        Returns:
            Result from operation, or None if all providers fail
        """
        if not self.fallback_enabled:
            provider = self.get_current_provider()
            adapter = self.provider_adapters.get(provider)
            if not adapter:
                logger.error(f"No adapter for provider: {provider}")
                return None
            return await self._execute_operation(
                provider, adapter, operation, *args, **kwargs
            )

        # Try providers in order of priority
        for i, provider in enumerate(self.providers):
            if self.is_budget_exceeded(provider):
                logger.debug(f"Skipping {provider}: budget exceeded")
                continue

            adapter = self.provider_adapters.get(provider)
            if not adapter:
                logger.debug(f"No adapter for provider: {provider}")
                continue

            try:
                result = await self._execute_operation(
                    provider, adapter, operation, *args, **kwargs
                )
                if result is not None:
                    self.current_provider_index = i
                    return result
            except Exception as e:
                logger.warning(
                    f"Operation {operation} failed on {provider}: {e}"
                )
                self._record_error(provider, str(e))
                continue

        logger.error(
            f"All providers exhausted for operation: {operation}"
        )
        return None

    async def _execute_operation(
        self,
        provider: str,
        adapter: Any,
        operation: str,
        *args,
        **kwargs,
    ) -> Optional[Any]:
        """
        Execute an operation on a specific provider.

        Args:
            provider: Provider name
            adapter: Provider adapter
            operation: Operation name
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Operation result
        """
        if not hasattr(adapter, operation):
            raise AttributeError(f"Adapter has no method: {operation}")

        method = getattr(adapter, operation)
        result = await method(*args, **kwargs)

        self._record_success(provider)
        return result

    def record_cost(
        self,
        provider: str,
        cost_usd: float,
    ) -> None:
        """
        Record a cost transaction for a provider.

        Args:
            provider: Provider name
            cost_usd: Cost in USD
        """
        if provider not in self.metrics:
            logger.warning(f"Unknown provider: {provider}")
            return

        metrics = self.metrics[provider]
        metrics.total_cost_usd += cost_usd
        metrics.daily_cost_usd += cost_usd
        metrics.monthly_cost_usd += cost_usd

        logger.debug(
            f"Recorded cost for {provider}: ${cost_usd:.6f} "
            f"(total: ${metrics.total_cost_usd:.2f})"
        )

        if metrics.monthly_cost_usd > self.cost_thresholds.get(provider, 800.0):
            logger.warning(
                f"Cost threshold approached for {provider}: "
                f"${metrics.monthly_cost_usd:.2f} > "
                f"${self.cost_thresholds[provider]:.2f}"
            )

    def is_budget_exceeded(self, provider: str) -> bool:
        """
        Check if provider budget is exceeded.

        Args:
            provider: Provider name

        Returns:
            True if budget exceeded, False otherwise
        """
        if provider not in self.metrics:
            return False

        metrics = self.metrics[provider]
        return metrics.monthly_cost_usd > metrics.budget_usd

    def get_budget_percentage(self, provider: str) -> float:
        """
        Get percentage of budget used for a provider.

        Args:
            provider: Provider name

        Returns:
            Budget usage percentage (0-100)
        """
        if provider not in self.metrics:
            return 0.0

        metrics = self.metrics[provider]
        if metrics.budget_usd == 0:
            return 0.0

        return (metrics.monthly_cost_usd / metrics.budget_usd) * 100.0

    def _record_success(self, provider: str) -> None:
        """Record a successful operation."""
        if provider in self.metrics:
            self.metrics[provider].success_count += 1
            self.metrics[provider].call_count += 1
            self.metrics[provider].status = ProviderStatus.HEALTHY

    def _record_error(self, provider: str, error_msg: str) -> None:
        """Record an operation error."""
        if provider not in self.metrics:
            return

        metrics = self.metrics[provider]
        metrics.error_count += 1
        metrics.call_count += 1
        metrics.last_error = error_msg
        metrics.last_error_time = datetime.now()

        # Mark as degraded if error rate > 20%
        if metrics.call_count > 0:
            error_rate = metrics.error_count / metrics.call_count
            if error_rate > 0.2:
                metrics.status = ProviderStatus.DEGRADED

    def get_provider_status(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Get status and metrics for a provider.

        Args:
            provider: Provider name (if None, returns all providers)

        Returns:
            Dict with provider metrics and status
        """
        if provider is None:
            return {
                p: self._get_single_provider_status(p)
                for p in self.providers
            }

        return self._get_single_provider_status(provider)

    def _get_single_provider_status(self, provider: str) -> Dict[str, Any]:
        """Get status for a single provider."""
        if provider not in self.metrics:
            return {"error": f"Unknown provider: {provider}"}

        metrics = self.metrics[provider]
        return {
            "provider": provider,
            "status": metrics.status.value,
            "total_cost_usd": round(metrics.total_cost_usd, 6),
            "daily_cost_usd": round(metrics.daily_cost_usd, 6),
            "monthly_cost_usd": round(metrics.monthly_cost_usd, 6),
            "budget_usd": metrics.budget_usd,
            "budget_percentage": round(self.get_budget_percentage(provider), 2),
            "budget_exceeded": self.is_budget_exceeded(provider),
            "call_count": metrics.call_count,
            "success_count": metrics.success_count,
            "error_count": metrics.error_count,
            "error_rate": round(
                metrics.error_count / max(1, metrics.call_count), 3
            ),
            "last_error": metrics.last_error,
            "last_error_time": (
                metrics.last_error_time.isoformat()
                if metrics.last_error_time
                else None
            ),
        }

    def reset_daily_costs(self) -> None:
        """Reset daily costs for all providers."""
        for metrics in self.metrics.values():
            logger.info(
                f"Resetting daily cost for {metrics.name}: "
                f"${metrics.daily_cost_usd:.2f}"
            )
            metrics.daily_cost_usd = 0.0

    def reset_monthly_costs(self) -> None:
        """Reset monthly costs for all providers."""
        for metrics in self.metrics.values():
            logger.info(
                f"Resetting monthly cost for {metrics.name}: "
                f"${metrics.monthly_cost_usd:.2f}"
            )
            metrics.monthly_cost_usd = 0.0

    def get_cost_comparison(self) -> Dict[str, Any]:
        """
        Get cost comparison across all providers.

        Returns:
            Dict with cost metrics for each provider
        """
        comparison = {
            "timestamp": datetime.now().isoformat(),
            "providers": {},
            "cheapest": None,
            "most_expensive": None,
            "total_cost_usd": 0.0,
        }

        for provider in self.providers:
            status = self._get_single_provider_status(provider)
            comparison["providers"][provider] = status
            comparison["total_cost_usd"] += status["total_cost_usd"]

        if self.providers:
            costs = [
                comparison["providers"][p]["total_cost_usd"]
                for p in self.providers
            ]
            min_idx = costs.index(min(costs))
            max_idx = costs.index(max(costs))
            comparison["cheapest"] = self.providers[min_idx]
            comparison["most_expensive"] = self.providers[max_idx]

        return comparison
