"""Unit tests for ResponseLengthOptimizer service (Phase 3D.5)."""

import pytest
from src.domain.services.response_length_optimizer import ResponseLengthOptimizer
from src.domain.services.interrupt_metrics import InterruptMetrics


class TestResponseLengthOptimizer:
    """Test suite for ResponseLengthOptimizer logic."""
    
    @pytest.fixture
    def metrics_service(self):
        """Create a fresh InterruptMetrics instance for each test."""
        return InterruptMetrics()
    
    @pytest.fixture
    def optimizer(self, metrics_service):
        """Create ResponseLengthOptimizer with mock metrics."""
        return ResponseLengthOptimizer(metrics_service)
    
    def test_compute_max_tokens_default_no_intent(self, optimizer):
        """Test: Default max_tokens returned when intent is None."""
        result = optimizer.compute_max_tokens(intent=None, stream_sid="test_stream")
        assert result == ResponseLengthOptimizer.DEFAULT_MAX_TOKENS
    
    def test_compute_max_tokens_intent_specific_default(self, optimizer):
        """Test: Intent-specific defaults are applied."""
        # Confirmation intent should get shorter default (80 tokens)
        result = optimizer.compute_max_tokens(intent="confirmation", stream_sid=None)
        assert result == 80
        
        # Support question should get longer default (200 tokens)
        result = optimizer.compute_max_tokens(intent="support_question", stream_sid=None)
        assert result == 200
    
    def test_compute_max_tokens_clamping_min(self, optimizer):
        """Test: Max tokens are clamped to minimum (50)."""
        # Even if we somehow compute very low tokens, clamping enforces minimum
        optimizer._metrics._metrics["test"] = {
            "total_responses": 1,
            "interrupted_count": 1,
            "total_tokens_before_interrupt": 1,
            "early_interrupts": 1,  # Very early interrupt
        }
        
        result = optimizer.compute_max_tokens(intent="confirmation", stream_sid="test")
        assert result >= ResponseLengthOptimizer.MIN_MAX_TOKENS
    
    def test_compute_max_tokens_clamping_max(self, optimizer):
        """Test: Max tokens are clamped to maximum (250)."""
        # Override default to test clamping
        optimizer.INTENT_DEFAULTS["extreme_intent"] = 500
        result = optimizer.compute_max_tokens(intent="extreme_intent", stream_sid=None)
        assert result <= ResponseLengthOptimizer.MAX_MAX_TOKENS
    
    def test_compute_max_tokens_high_early_interrupt_rate(self, optimizer):
        """Test: High early interrupt rate (>30%) reduces tokens significantly."""
        # Setup metrics with high early interrupt rate
        stream_id = "high_interrupt_stream"
        optimizer._metrics._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 5,
            "total_tokens_before_interrupt": 25,
            "early_interrupts": 4,  # 80% of interrupts are early (> 30% threshold)
        }
        
        # Get metrics to verify early_interrupt_pct is > 30%
        metrics = optimizer._metrics.get_metrics(stream_id)
        assert metrics["early_interrupt_pct"] > 30
        
        # Should return ~50% of base tokens (75 for default 150)
        result = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        assert 50 <= result <= 100  # Should be significantly reduced
    
    def test_compute_max_tokens_medium_early_interrupt_rate(self, optimizer):
        """Test: Medium early interrupt rate (15-30%) reduces tokens moderately."""
        stream_id = "medium_interrupt_stream"
        optimizer._metrics._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 8,
            "total_tokens_before_interrupt": 120,
            "early_interrupts": 2,  # 25% of interrupts are early (between 15-30%)
        }
        
        # Get metrics to verify early_interrupt_pct is between 15-30
        metrics = optimizer._metrics.get_metrics(stream_id)
        assert 15 < metrics["early_interrupt_pct"] <= 30
        
        # Should return ~73% of base tokens (110 for default 150)
        result = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        assert 100 <= result < 150  # Should be moderately reduced
    
    def test_compute_max_tokens_low_early_interrupt_rate(self, optimizer):
        """Test: Low early interrupt rate (<15%) keeps default tokens."""
        stream_id = "low_interrupt_stream"
        optimizer._metrics._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 2,
            "total_tokens_before_interrupt": 100,
            "early_interrupts": 0,  # No early interrupts
        }
        
        # Should return default tokens (150)
        result = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        assert result == ResponseLengthOptimizer.DEFAULT_MAX_TOKENS
    
    def test_get_intent_default(self, optimizer):
        """Test: get_intent_default returns correct defaults."""
        assert optimizer.get_intent_default("support_question") == 200
        assert optimizer.get_intent_default("confirmation") == 80
        assert optimizer.get_intent_default("clarification") == 120
        assert optimizer.get_intent_default("unknown_intent") == 150  # Falls back to default
    
    def test_get_constraint_text(self, optimizer):
        """Test: get_constraint_text generates valid prompt constraint."""
        constraint = optimizer.get_constraint_text(100)
        assert "100" in constraint
        assert "token" in constraint.lower()
        assert len(constraint) > 10
    
    def test_clamp_tokens_lower_bound(self, optimizer):
        """Test: _clamp_tokens enforces minimum."""
        assert optimizer._clamp_tokens(10) == ResponseLengthOptimizer.MIN_MAX_TOKENS
        assert optimizer._clamp_tokens(0) == ResponseLengthOptimizer.MIN_MAX_TOKENS
    
    def test_clamp_tokens_upper_bound(self, optimizer):
        """Test: _clamp_tokens enforces maximum."""
        assert optimizer._clamp_tokens(500) == ResponseLengthOptimizer.MAX_MAX_TOKENS
        assert optimizer._clamp_tokens(1000) == ResponseLengthOptimizer.MAX_MAX_TOKENS
    
    def test_clamp_tokens_valid_range(self, optimizer):
        """Test: _clamp_tokens preserves valid values."""
        assert optimizer._clamp_tokens(100) == 100
        assert optimizer._clamp_tokens(150) == 150
        assert optimizer._clamp_tokens(200) == 200
