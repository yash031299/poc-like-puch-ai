"""Cost Tracker — Track API costs for budget management and alerting.

Tracks per-provider API costs (Google STT, Google TTS, Gemini LLM) and
alerts when budget thresholds are exceeded.

Usage:
    tracker = CostTracker(daily_budget_usd=100.0)
    
    # Record a call with costs
    cost = tracker.record_call({
        "call_id": "call-123",
        "stt_duration_seconds": 45,
        "tts_text": "Generated speech text",
        "input_tokens": 100,
        "output_tokens": 50,
    })
    
    # Check budget status
    remaining = tracker.get_remaining_budget()
    breakdown = tracker.get_cost_breakdown()
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass, field

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

    Alerts when daily budget is exceeded.
    """

    # Provider costs (approximate as of 2024)
    GOOGLE_STT_COST_PER_MIN = 0.015  # $0.015 per minute
    GOOGLE_TTS_COST_PER_1K_CHARS = 0.015  # $0.015 per 1K characters
    GEMINI_INPUT_COST_PER_1M = 0.075  # $0.075 per 1M input tokens
    GEMINI_OUTPUT_COST_PER_1M = 0.3  # $0.3 per 1M output tokens

    def __init__(self, daily_budget_usd: float = 500.0):
        """
        Initialize CostTracker.

        Args:
            daily_budget_usd: Daily budget in USD (default: $500)
        """
        self.daily_budget_usd = daily_budget_usd
        self.daily_cost = 0.0
        self.call_costs: Dict[str, float] = {}
        self.provider_costs: Dict[str, float] = {
            "google_stt": 0.0,
            "google_tts": 0.0,
            "gemini": 0.0,
        }
        self.last_reset = datetime.now()

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
        output_tokens: int
    ) -> float:
        """
        Calculate cost for LLM (Language Model).

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * self.GEMINI_INPUT_COST_PER_1M
        output_cost = (output_tokens / 1_000_000) * self.GEMINI_OUTPUT_COST_PER_1M
        total_cost = input_cost + output_cost

        logger.debug(
            f"LLM cost: {input_tokens} input + {output_tokens} output → ${total_cost:.6f}"
        )
        return total_cost

    def record_call(self, call_record: Dict) -> float:
        """
        Record API costs for a call.

        Args:
            call_record: Dict with:
                - call_id: Unique call ID
                - stt_duration_seconds: Duration of STT audio
                - tts_text: Text that was synthesized
                - input_tokens: LLM input tokens
                - output_tokens: LLM output tokens

        Returns:
            Total cost for this call in USD
        """
        call_id = call_record.get("call_id", "unknown")
        
        # Calculate per-provider costs
        stt_cost = self.calculate_stt_cost(
            call_record.get("stt_duration_seconds", 0)
        )
        tts_cost = self.calculate_tts_cost(
            call_record.get("tts_text", "")
        )
        llm_cost = self.calculate_llm_cost(
            call_record.get("input_tokens", 0),
            call_record.get("output_tokens", 0)
        )

        total_cost = stt_cost + tts_cost + llm_cost

        # Record costs
        self.call_costs[call_id] = total_cost
        self.daily_cost += total_cost
        self.provider_costs["google_stt"] += stt_cost
        self.provider_costs["google_tts"] += tts_cost
        self.provider_costs["gemini"] += llm_cost

        logger.info(
            f"Call {call_id} cost: ${total_cost:.6f} "
            f"(STT: ${stt_cost:.6f}, TTS: ${tts_cost:.6f}, LLM: ${llm_cost:.6f})"
        )

        # Check budget
        if self.is_budget_exceeded():
            logger.warning(
                f"⚠️ BUDGET EXCEEDED: Daily cost ${self.daily_cost:.2f} "
                f"> ${self.daily_budget_usd:.2f}"
            )

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
            "google_stt": self.provider_costs["google_stt"],
            "google_tts": self.provider_costs["google_tts"],
            "gemini": self.provider_costs["gemini"],
            "remaining_budget": self.get_remaining_budget(),
            "budget_percentage": self.get_budget_percentage(),
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
            f"  Total: ${breakdown['total']:.2f}\n"
            f"    - STT: ${breakdown['google_stt']:.2f}\n"
            f"    - TTS: ${breakdown['google_tts']:.2f}\n"
            f"    - LLM: ${breakdown['gemini']:.2f}\n"
            f"  Budget: ${self.daily_budget_usd:.2f}\n"
            f"  Remaining: ${remaining:.2f} ({100-percentage:.1f}%)\n"
            f"  Status: {'🚨 EXCEEDED' if self.is_budget_exceeded() else '✅ OK'}"
        )
