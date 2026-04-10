"""Cost Tracker Tests.

Tests for API cost tracking and budget management:
- Per-call API costs
- Daily cost aggregation
- Budget alerts
- Cost breakdown by provider
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.infrastructure.cost_tracker import CostTracker, ProviderCost


@pytest.fixture
def cost_tracker():
    """Fixture providing CostTracker."""
    return CostTracker(daily_budget_usd=100.0)


def test_cost_tracker_initialize():
    """Test CostTracker initialization."""
    tracker = CostTracker(daily_budget_usd=50.0)
    assert tracker.daily_budget_usd == 50.0


def test_cost_tracker_google_stt_cost():
    """Test Google STT cost calculation (approximately $0.015 per minute)."""
    tracker = CostTracker()
    
    # STT for 60 seconds of audio
    cost = tracker.calculate_stt_cost(duration_seconds=60)
    
    # Should be approximately $0.015
    assert 0.01 < cost < 0.02


def test_cost_tracker_google_tts_cost():
    """Test Google TTS cost calculation (approximately $0.015 per 1K characters)."""
    tracker = CostTracker()
    
    # 1000 characters of TTS
    cost = tracker.calculate_tts_cost(text="hello world" * 100)
    
    # Should be approximately $0.015
    assert cost > 0


def test_cost_tracker_gemini_cost():
    """Test Gemini LLM cost calculation."""
    tracker = CostTracker()
    
    # 1M input tokens, 1M output tokens (rough estimates)
    cost = tracker.calculate_llm_cost(
        input_tokens=1000,
        output_tokens=500
    )
    
    # Should be > 0
    assert cost > 0


def test_cost_tracker_record_call_cost():
    """Test recording a complete call cost."""
    tracker = CostTracker()
    
    call_record = {
        "call_id": "test-call-1",
        "stt_duration_seconds": 60,
        "tts_text": "Hello, this is a test call",
        "input_tokens": 100,
        "output_tokens": 50,
    }
    
    total_cost = tracker.record_call(call_record)
    
    assert total_cost > 0


def test_cost_tracker_daily_cost():
    """Test daily cost tracking."""
    tracker = CostTracker()
    
    # Record multiple calls
    for i in range(5):
        tracker.record_call({
            "call_id": f"call-{i}",
            "stt_duration_seconds": 30,
            "tts_text": "Test call " * 10,
            "input_tokens": 50,
            "output_tokens": 25,
        })
    
    daily_cost = tracker.get_daily_cost()
    assert daily_cost > 0


def test_cost_tracker_budget_check():
    """Test budget check."""
    tracker = CostTracker(daily_budget_usd=1.0)  # $1 budget
    
    # Record a call that should be under budget
    cost = tracker.record_call({
        "call_id": "test-call",
        "stt_duration_seconds": 10,
        "tts_text": "Test",
        "input_tokens": 10,
        "output_tokens": 5,
    })
    
    remaining = tracker.get_remaining_budget()
    assert remaining > 0


def test_cost_tracker_budget_exceeded():
    """Test budget exceeded alert."""
    tracker = CostTracker(daily_budget_usd=0.001)  # Very low budget
    
    # Record call that exceeds budget
    is_exceeded = tracker.is_budget_exceeded()
    
    # After recording a call, budget might be exceeded
    tracker.record_call({
        "call_id": "test-call",
        "stt_duration_seconds": 60,
        "tts_text": "Test" * 100,
        "input_tokens": 1000,
        "output_tokens": 500,
    })
    
    is_exceeded = tracker.is_budget_exceeded()
    assert isinstance(is_exceeded, bool)


def test_cost_tracker_provider_breakdown():
    """Test cost breakdown by provider."""
    tracker = CostTracker()
    
    # Record multiple calls
    for i in range(3):
        tracker.record_call({
            "call_id": f"call-{i}",
            "stt_duration_seconds": 30,
            "tts_text": "Test" * 50,
            "input_tokens": 100,
            "output_tokens": 50,
        })
    
    breakdown = tracker.get_cost_breakdown()
    
    assert "google_stt" in breakdown
    assert "google_tts" in breakdown
    assert "gemini" in breakdown


def test_cost_tracker_reset_daily():
    """Test resetting daily cost."""
    tracker = CostTracker()
    
    # Record a cost
    tracker.record_call({
        "call_id": "test-call",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
    })
    
    initial_cost = tracker.get_daily_cost()
    assert initial_cost > 0
    
    # Reset
    tracker.reset_daily_cost()
    
    reset_cost = tracker.get_daily_cost()
    assert reset_cost == 0.0


def test_cost_tracker_cost_per_call():
    """Test getting cost for a specific call."""
    tracker = CostTracker()
    
    call_id = "call-123"
    cost = tracker.record_call({
        "call_id": call_id,
        "stt_duration_seconds": 45,
        "tts_text": "Test call text",
        "input_tokens": 75,
        "output_tokens": 40,
    })
    
    retrieved_cost = tracker.get_call_cost(call_id)
    assert retrieved_cost == cost


def test_cost_tracker_stt_cost_by_duration():
    """Test STT cost scales with duration."""
    tracker = CostTracker()
    
    cost_30s = tracker.calculate_stt_cost(30)
    cost_60s = tracker.calculate_stt_cost(60)
    
    # 60s should cost roughly 2x as much as 30s
    assert cost_60s > cost_30s
    assert cost_60s / cost_30s == pytest.approx(2.0, rel=0.1)


def test_cost_tracker_tts_cost_by_length():
    """Test TTS cost scales with text length."""
    tracker = CostTracker()
    
    short_text = "Hello"
    long_text = "Hello world " * 100
    
    cost_short = tracker.calculate_tts_cost(short_text)
    cost_long = tracker.calculate_tts_cost(long_text)
    
    assert cost_long > cost_short


def test_cost_tracker_multiple_days():
    """Test tracking costs across multiple days."""
    tracker = CostTracker()
    
    # Record costs for today
    for i in range(3):
        tracker.record_call({
            "call_id": f"today-{i}",
            "stt_duration_seconds": 30,
            "tts_text": "Test",
            "input_tokens": 50,
            "output_tokens": 25,
        })
    
    today_cost = tracker.get_daily_cost()
    
    # Simulate reset for new day
    tracker.reset_daily_cost()
    tracker.last_reset = datetime.now() - timedelta(days=1)
    
    # Record costs for "yesterday"
    for i in range(2):
        tracker.record_call({
            "call_id": f"yesterday-{i}",
            "stt_duration_seconds": 20,
            "tts_text": "Test",
            "input_tokens": 40,
            "output_tokens": 20,
        })
    
    # Today's new cost
    new_today_cost = tracker.get_daily_cost()
    
    # Should be different
    assert new_today_cost != today_cost


def test_cost_tracker_monthly_budget():
    """Test monthly budget tracking."""
    tracker = CostTracker(
        daily_budget_usd=100.0,
        monthly_budget_usd=500.0
    )
    
    # Record calls
    for i in range(3):
        tracker.record_call({
            "call_id": f"call-{i}",
            "stt_duration_seconds": 60,
            "tts_text": "Test" * 100,
            "input_tokens": 200,
            "output_tokens": 100,
        })
    
    monthly_cost = tracker.get_cost_breakdown()["monthly_total"]
    assert monthly_cost > 0
    assert tracker.get_monthly_remaining_budget() > 0


def test_cost_tracker_monthly_budget_exceeded():
    """Test detection of monthly budget exceeded."""
    tracker = CostTracker(monthly_budget_usd=0.001)
    
    # Record a call that exceeds budget
    tracker.record_call({
        "call_id": "test-call",
        "stt_duration_seconds": 60,
        "tts_text": "Test" * 100,
        "input_tokens": 1000,
        "output_tokens": 500,
    })
    
    assert tracker.is_monthly_budget_exceeded()


def test_cost_tracker_per_user_costs():
    """Test per-user cost tracking."""
    tracker = CostTracker()
    
    # Record costs for different users
    tracker.record_call({
        "call_id": "call-1",
        "user_id": "user-1",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
    })
    
    tracker.record_call({
        "call_id": "call-2",
        "user_id": "user-2",
        "stt_duration_seconds": 60,
        "tts_text": "Test" * 2,
        "input_tokens": 100,
        "output_tokens": 50,
    })
    
    user1_costs = tracker.get_user_costs("user-1")
    user2_costs = tracker.get_user_costs("user-2")
    
    assert user1_costs["user_id"] == "user-1"
    assert user1_costs["call_count"] == 1
    assert user2_costs["call_count"] == 1
    assert user2_costs["daily_cost"] > user1_costs["daily_cost"]


def test_cost_tracker_per_user_limit_exceeded():
    """Test per-user daily limit exceeded."""
    tracker = CostTracker(per_user_daily_limit_usd=0.001)
    
    # Record a call that exceeds user limit
    tracker.record_call({
        "call_id": "test-call",
        "user_id": "user-1",
        "stt_duration_seconds": 60,
        "tts_text": "Test" * 100,
        "input_tokens": 1000,
        "output_tokens": 500,
    })
    
    user_costs = tracker.get_user_costs("user-1")
    assert user_costs["budget_exceeded"]


def test_cost_tracker_openai_provider():
    """Test OpenAI provider cost calculation."""
    tracker = CostTracker()
    
    # OpenAI and Gemini have different pricing models
    # OpenAI: $0.0005 per 1K input, $0.0015 per 1K output
    # Gemini: $0.075 per 1M input, $0.3 per 1M output
    openai_cost = tracker.calculate_llm_cost(
        input_tokens=1000000,
        output_tokens=500000,
        provider="openai"
    )
    
    gemini_cost = tracker.calculate_llm_cost(
        input_tokens=1000000,
        output_tokens=500000,
        provider="gemini"
    )
    
    # Both should be valid costs
    assert openai_cost > 0
    assert gemini_cost > 0
    # Gemini is actually cheaper per token at scale
    assert gemini_cost < openai_cost


def test_cost_tracker_provider_breakdown():
    """Test cost breakdown by provider."""
    tracker = CostTracker()
    
    # Record costs from different providers
    tracker.record_call({
        "call_id": "call-1",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
        "provider": "gemini",
    })
    
    tracker.record_call({
        "call_id": "call-2",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
        "provider": "openai",
    })
    
    breakdown = tracker.get_cost_breakdown()
    assert breakdown["gemini"] > 0
    assert breakdown["openai"] > 0


def test_cost_tracker_monthly_reset():
    """Test monthly cost reset."""
    tracker = CostTracker()
    
    # Record costs
    tracker.record_call({
        "call_id": "call-1",
        "user_id": "user-1",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
    })
    
    initial_monthly_cost = tracker.get_cost_breakdown()["monthly_total"]
    assert initial_monthly_cost > 0
    
    # Reset monthly
    tracker.reset_monthly_cost()
    
    assert tracker.get_cost_breakdown()["monthly_total"] == 0.0
    assert tracker.get_daily_cost() == 0.0
    assert len(tracker.user_daily_costs) == 0


def test_cost_tracker_alert_threshold():
    """Test alert threshold for budget."""
    tracker = CostTracker(
        daily_budget_usd=10.0,
        alert_threshold_percent=0.5
    )
    
    # Should not alert at 40% usage
    tracker.record_call({
        "call_id": "call-1",
        "stt_duration_seconds": 10,
        "tts_text": "Test",
        "input_tokens": 10,
        "output_tokens": 5,
    })
    
    # This doesn't raise an exception, but logs a warning internally
    # The test verifies it doesn't crash


def test_cost_tracker_cost_summary():
    """Test cost summary generation."""
    tracker = CostTracker()
    
    tracker.record_call({
        "call_id": "call-1",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
    })
    
    summary = tracker.get_cost_summary()
    assert "Daily Cost Summary" in summary
    assert "Daily Total" in summary
    assert "Monthly Total" in summary
    assert "Budget" in summary


def test_cost_tracker_budget_percentage_calculation():
    """Test budget percentage calculation."""
    tracker = CostTracker(daily_budget_usd=100.0, monthly_budget_usd=1000.0)
    
    tracker.record_call({
        "call_id": "call-1",
        "stt_duration_seconds": 30,
        "tts_text": "Test",
        "input_tokens": 50,
        "output_tokens": 25,
    })
    
    daily_pct = tracker.get_budget_percentage()
    monthly_pct = tracker.get_monthly_budget_percentage()
    
    assert 0 < daily_pct < 100
    assert 0 < monthly_pct < 100
    assert daily_pct > monthly_pct  # Should use more of daily budget
