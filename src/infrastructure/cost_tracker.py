"""Cost Tracker — Track API costs for budget management and alerting.

Tracks per-provider API costs (Google STT, Google TTS, Gemini LLM, OpenAI) and
alerts when budget thresholds are exceeded. Supports monthly budget enforcement
and per-user cost tracking.

Usage:
    tracker = CostTracker(
        daily_budget_usd=100.0,
        monthly_budget_usd=3000.0
    )
    
    # Record a call with costs
    cost = tracker.record_call({
        "call_id": "call-123",
        "user_id": "user-456",
        "stt_duration_seconds": 45,
        "tts_text": "Generated speech text",
        "input_tokens": 100,
        "output_tokens": 50,
        "provider": "google",
    })
    
    # Check budget status
    remaining = tracker.get_remaining_budget()
    breakdown = tracker.get_cost_breakdown()
    user_costs = tracker.get_user_costs("user-456")
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ProviderCost:
    """Cost configuration for a provider."""
    name: str
    cost_per_unit: float
    unit: str  # "minute", "1k_chars", "1m_tokens"


class CostTracker:
    """
    Track API costs for production budgeting and alerting.

    Tracks:
    - Google STT: ~$0.015 per minute of audio
    - Google TTS: ~$0.015 per 1K characters
    - Gemini: ~$0.075 per 1M input tokens + $0.3 per 1M output tokens
    - OpenAI: ~$0.0005 per 1K input tokens + $0.0015 per 1K output tokens

    Supports:
    - Daily and monthly budget enforcement
    - Per-user cost tracking and limits
    - Provider-specific costs and budgets
    - Alert thresholds and alerting
    """

    # Provider costs (approximate as of 2024)
    GOOGLE_STT_COST_PER_MIN = 0.015
    GOOGLE_TTS_COST_PER_1K_CHARS = 0.015
    GEMINI_INPUT_COST_PER_1M = 0.075
    GEMINI_OUTPUT_COST_PER_1M = 0.3
    OPENAI_INPUT_COST_PER_1K = 0.0005
    OPENAI_OUTPUT_COST_PER_1K = 0.0015

    def __init__(
        self,
        daily_budget_usd: float = 500.0,
        monthly_budget_usd: float = 10000.0,
        per_user_daily_limit_usd: float = 100.0,
        alert_threshold_percent: float = 0.8,
    ):
        """
        Initialize CostTracker.

        Args:
            daily_budget_usd: Daily budget in USD (default: $500)
            monthly_budget_usd: Monthly budget in USD (default: $10,000)
            per_user_daily_limit_usd: Per-user daily limit (default: $100)
            alert_threshold_percent: Alert when this % of budget is used (0-1)
        """
        self.daily_budget_usd = daily_budget_usd
        self.monthly_budget_usd = monthly_budget_usd
        self.per_user_daily_limit_usd = per_user_daily_limit_usd
        self.alert_threshold_percent = alert_threshold_percent

        self.daily_cost = 0.0
        self.monthly_cost = 0.0
        self.call_costs: Dict[str, float] = {}
        self.provider_costs: Dict[str, float] = {
            "google_stt": 0.0,
            "google_tts": 0.0,
            "gemini": 0.0,
            "openai": 0.0,
        }
        
        # Per-user tracking
        self.user_daily_costs: Dict[str, float] = defaultdict(float)
        self.user_call_counts: Dict[str, int] = defaultdict(int)
        self.user_alerts: Dict[str, List[str]] = defaultdict(list)
        
        # Timestamps
        self.last_reset = datetime.now()
        self.monthly_reset = datetime.now()

    def calculate_stt_cost(self, duration_seconds: float) -> float:
        """
        Calculate cost for STT (Speech-to-Text).

        Args:
            duration_seconds: Duration of audio in seconds

        Returns:
            Cost in USD
        """
        minutes = duration_seconds / 60.0
        cost = minutes * self.GOOGLE_STT_COST_PER_MIN
        logger.debug(f"STT cost: {duration_seconds}s → ${cost:.6f}")
        return cost

    def calculate_tts_cost(self, text: str) -> float:
        """
        Calculate cost for TTS (Text-to-Speech).

        Args:
            text: Text to synthesize

        Returns:
            Cost in USD
        """
        char_count = len(text)
        thousands = char_count / 1000.0
        cost = thousands * self.GOOGLE_TTS_COST_PER_1K_CHARS
        logger.debug(f"TTS cost: {char_count} chars → ${cost:.6f}")
        return cost

    def calculate_llm_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        provider: str = "gemini",
    ) -> float:
        """
        Calculate cost for LLM.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            provider: LLM provider ("gemini" or "openai")

        Returns:
            Cost in USD
        """
        if provider == "openai":
            input_cost = (input_tokens / 1000) * self.OPENAI_INPUT_COST_PER_1K
            output_cost = (output_tokens / 1000) * self.OPENAI_OUTPUT_COST_PER_1K
        else:  # gemini (default)
            input_cost = (input_tokens / 1_000_000) * self.GEMINI_INPUT_COST_PER_1M
            output_cost = (output_tokens / 1_000_000) * self.GEMINI_OUTPUT_COST_PER_1M

        total_cost = input_cost + output_cost

        logger.debug(
            f"LLM cost ({provider}): {input_tokens} input + {output_tokens} output "
            f"→ ${total_cost:.6f}"
        )
        return total_cost

    def record_call(self, call_record: Dict) -> float:
        """
        Record API costs for a call.

        Args:
            call_record: Dict with:
                - call_id: Unique call ID
                - user_id: Optional user ID for per-user tracking
                - stt_duration_seconds: Duration of STT audio
                - tts_text: Text that was synthesized
                - input_tokens: LLM input tokens
                - output_tokens: LLM output tokens
                - provider: Optional provider name ("gemini", "openai", etc.)

        Returns:
            Total cost for this call in USD
        """
        call_id = call_record.get("call_id", "unknown")
        user_id = call_record.get("user_id", "unknown")
        provider = call_record.get("provider", "gemini")
        
        # Calculate per-provider costs
        stt_cost = self.calculate_stt_cost(
            call_record.get("stt_duration_seconds", 0)
        )
        tts_cost = self.calculate_tts_cost(
            call_record.get("tts_text", "")
        )
        llm_cost = self.calculate_llm_cost(
            call_record.get("input_tokens", 0),
            call_record.get("output_tokens", 0),
            provider=provider,
        )

        total_cost = stt_cost + tts_cost + llm_cost

        # Record costs
        self.call_costs[call_id] = total_cost
        self.daily_cost += total_cost
        self.monthly_cost += total_cost
        
        self.provider_costs["google_stt"] += stt_cost
        self.provider_costs["google_tts"] += tts_cost
        if provider == "openai":
            self.provider_costs["openai"] += llm_cost
        else:
            self.provider_costs["gemini"] += llm_cost

        # Per-user tracking
        self.user_daily_costs[user_id] += total_cost
        self.user_call_counts[user_id] += 1

        logger.info(
            f"Call {call_id} (user {user_id}) cost: ${total_cost:.6f} "
            f"({provider})"
        )

        # Check budgets and alert
        self._check_budgets(call_id, user_id)

        return total_cost

    def get_call_cost(self, call_id: str) -> Optional[float]:
        """
        Get cost for a specific call.

        Args:
            call_id: Call ID

        Returns:
            Cost in USD, or None if call not found
        """
        return self.call_costs.get(call_id)

    def get_daily_cost(self) -> float:
        """
        Get today's total cost.

        Returns:
            Cost in USD
        """
        return self.daily_cost

    def get_remaining_budget(self) -> float:
        """
        Get remaining budget for today.

        Returns:
            Remaining budget in USD
        """
        remaining = self.daily_budget_usd - self.daily_cost
        logger.debug(
            f"Budget status: ${remaining:.2f} remaining "
            f"(used ${self.daily_cost:.2f} of ${self.daily_budget_usd:.2f})"
        )
        return remaining

    def get_budget_percentage(self) -> float:
        """
        Get percentage of daily budget used.

        Returns:
            Percentage (0-100)
        """
        if self.daily_budget_usd == 0:
            return 0.0
        return (self.daily_cost / self.daily_budget_usd) * 100.0

    def is_budget_exceeded(self) -> bool:
        """
        Check if daily budget has been exceeded.

        Returns:
            True if budget exceeded, False otherwise
        """
        return self.daily_cost > self.daily_budget_usd

    def is_budget_critical(self, threshold: float = 0.8) -> bool:
        """
        Check if budget is approaching limit.

        Args:
            threshold: Critical threshold (default: 80%)

        Returns:
            True if usage >= threshold, False otherwise
        """
        percentage = self.get_budget_percentage()
        return percentage >= (threshold * 100)

    def get_cost_breakdown(self) -> Dict[str, float]:
        """
        Get cost breakdown by provider.

        Returns:
            Dict with provider costs
        """
        breakdown = {
            "total": self.daily_cost,
            "monthly_total": self.monthly_cost,
            "google_stt": self.provider_costs["google_stt"],
            "google_tts": self.provider_costs["google_tts"],
            "gemini": self.provider_costs["gemini"],
            "openai": self.provider_costs["openai"],
            "remaining_budget": self.get_remaining_budget(),
            "budget_percentage": self.get_budget_percentage(),
            "monthly_remaining": self.get_monthly_remaining_budget(),
            "monthly_percentage": self.get_monthly_budget_percentage(),
        }
        logger.debug(f"Cost breakdown: {breakdown}")
        return breakdown

    def reset_daily_cost(self) -> None:
        """
        Reset daily cost and call costs.

        Usually called at midnight or for testing.
        """
        logger.info(
            f"Resetting daily cost. Total spent today: ${self.daily_cost:.2f}"
        )
        self.daily_cost = 0.0
        self.call_costs.clear()
        self.provider_costs = {
            "google_stt": 0.0,
            "google_tts": 0.0,
            "gemini": 0.0,
        }
        self.last_reset = datetime.now()

    def get_cost_summary(self) -> str:
        """
        Get a human-readable cost summary.

        Returns:
            Formatted cost summary
        """
        breakdown = self.get_cost_breakdown()
        remaining = breakdown["remaining_budget"]
        percentage = breakdown["budget_percentage"]

        return (
            f"Daily Cost Summary:\n"
            f"  Daily Total: ${breakdown['total']:.2f}\n"
            f"  Monthly Total: ${breakdown['monthly_total']:.2f}\n"
            f"    - STT: ${breakdown['google_stt']:.2f}\n"
            f"    - TTS: ${breakdown['google_tts']:.2f}\n"
            f"    - LLM (Gemini): ${breakdown['gemini']:.2f}\n"
            f"    - LLM (OpenAI): ${breakdown['openai']:.2f}\n"
            f"  Daily Budget: ${self.daily_budget_usd:.2f}\n"
            f"  Monthly Budget: ${self.monthly_budget_usd:.2f}\n"
            f"  Remaining: ${remaining:.2f} ({100-percentage:.1f}%)\n"
            f"  Status: {'🚨 EXCEEDED' if self.is_budget_exceeded() else '✅ OK'}"
        )

    def _check_budgets(self, call_id: str, user_id: str) -> None:
        """Check daily, monthly, and per-user budgets, alert if exceeded."""
        # Daily budget alert
        if self.get_budget_percentage() >= (self.alert_threshold_percent * 100):
            msg = (
                f"⚠️ Daily budget approaching: "
                f"${self.daily_cost:.2f} / ${self.daily_budget_usd:.2f} "
                f"({self.get_budget_percentage():.1f}%)"
            )
            logger.warning(msg)

        # Daily budget exceeded
        if self.is_budget_exceeded():
            logger.error(
                f"❌ DAILY BUDGET EXCEEDED: ${self.daily_cost:.2f} "
                f"> ${self.daily_budget_usd:.2f}"
            )

        # Monthly budget exceeded
        if self.is_monthly_budget_exceeded():
            logger.error(
                f"❌ MONTHLY BUDGET EXCEEDED: ${self.monthly_cost:.2f} "
                f"> ${self.monthly_budget_usd:.2f}"
            )

        # Per-user daily limit exceeded
        user_cost = self.user_daily_costs.get(user_id, 0.0)
        if user_cost > self.per_user_daily_limit_usd:
            alert = (
                f"Per-user daily limit exceeded for {user_id}: "
                f"${user_cost:.2f} > ${self.per_user_daily_limit_usd:.2f}"
            )
            logger.error(alert)
            self.user_alerts[user_id].append(alert)

    def get_user_costs(self, user_id: str) -> Dict[str, float]:
        """Get cost breakdown for a specific user."""
        return {
            "user_id": user_id,
            "daily_cost": self.user_daily_costs.get(user_id, 0.0),
            "call_count": self.user_call_counts.get(user_id, 0),
            "average_cost_per_call": (
                self.user_daily_costs.get(user_id, 0.0) /
                max(1, self.user_call_counts.get(user_id, 0))
            ),
            "budget_limit": self.per_user_daily_limit_usd,
            "budget_exceeded": (
                self.user_daily_costs.get(user_id, 0.0) >
                self.per_user_daily_limit_usd
            ),
        }

    def is_monthly_budget_exceeded(self) -> bool:
        """Check if monthly budget has been exceeded."""
        return self.monthly_cost > self.monthly_budget_usd

    def get_monthly_remaining_budget(self) -> float:
        """Get remaining monthly budget."""
        return max(0.0, self.monthly_budget_usd - self.monthly_cost)

    def get_monthly_budget_percentage(self) -> float:
        """Get percentage of monthly budget used (0-100)."""
        if self.monthly_budget_usd == 0:
            return 0.0
        return (self.monthly_cost / self.monthly_budget_usd) * 100.0

    def reset_monthly_cost(self) -> None:
        """Reset monthly cost and user costs."""
        logger.info(
            f"Resetting monthly cost. Total spent: ${self.monthly_cost:.2f}"
        )
        self.monthly_cost = 0.0
        self.daily_cost = 0.0
        self.call_costs.clear()
        self.user_daily_costs.clear()
        self.user_call_counts.clear()
        self.user_alerts.clear()
        self.provider_costs = {
            "google_stt": 0.0,
            "google_tts": 0.0,
            "gemini": 0.0,
            "openai": 0.0,
        }
        self.monthly_reset = datetime.now()
