"""Integration tests for length constraint enforcement (Phase 3D.5)."""

import pytest
from src.domain.services.response_length_optimizer import ResponseLengthOptimizer
from src.domain.services.interrupt_metrics import InterruptMetrics
from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.utterance import Utterance
from src.domain.entities.ai_response import AIResponse


class TestLengthConstraintEnforcement:
    """Test suite for enforcing length constraints in prompts."""
    
    @pytest.fixture
    def metrics_service(self):
        """Create a fresh InterruptMetrics instance."""
        return InterruptMetrics()
    
    @pytest.fixture
    def optimizer(self, metrics_service):
        """Create ResponseLengthOptimizer."""
        return ResponseLengthOptimizer(metrics_service)
    
    def test_constraint_text_includes_max_tokens(self, optimizer):
        """Test: Constraint text includes the max_tokens value."""
        for max_tokens in [50, 100, 150, 200, 250]:
            constraint = optimizer.get_constraint_text(max_tokens)
            assert str(max_tokens) in constraint
            assert "token" in constraint.lower()
    
    def test_constraint_text_format_valid_for_prompts(self, optimizer):
        """Test: Constraint text is properly formatted for LLM prompts."""
        constraint = optimizer.get_constraint_text(100)
        
        # Should be a string, start with capital letter, end with period
        assert isinstance(constraint, str)
        assert len(constraint) > 0
        assert constraint[0].isupper() or constraint[0] in "Keep"
        assert constraint.endswith(".")
    
    def test_optimizer_integrates_with_interrupt_metrics(self, metrics_service, optimizer):
        """Test: Optimizer correctly reads metrics from InterruptMetrics service."""
        stream_id = "test_stream"
        
        # Simulate recording some interrupts via metrics service
        session = ConversationSession(stream_identifier=stream_id)
        utterance = Utterance(text="Hello", utterance_id="u1")
        response = AIResponse(text="Hi there", response_id="r1")
        
        # Record multiple early interrupts
        for _ in range(3):
            metrics_service.record_interrupt(
                session=session,
                response=response,
                token_count=5,  # Early interrupt (< 10 tokens)
            )
        
        # Record a late interrupt
        metrics_service.record_interrupt(
            session=session,
            response=response,
            token_count=25,
        )
        
        # Now optimizer should see high early interrupt rate
        metrics = metrics_service.get_metrics(stream_id)
        assert metrics["early_interrupt_pct"] == 75.0  # 3 out of 4 interrupts are early
        
        # Optimizer should recommend shorter response
        max_tokens = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        assert max_tokens < ResponseLengthOptimizer.DEFAULT_MAX_TOKENS
    
    def test_intent_aware_constraint_application(self, optimizer):
        """Test: Constraint accounts for intent-specific token limits."""
        # Short intent (confirmation) should use shorter constraint
        short_constraint = optimizer.get_constraint_text(
            optimizer.get_intent_default("confirmation")
        )
        
        # Long intent (support_question) should use longer constraint
        long_constraint = optimizer.get_constraint_text(
            optimizer.get_intent_default("support_question")
        )
        
        # Extract token counts from constraints
        short_tokens = int([s for s in short_constraint.split() if s.isdigit()][0])
        long_tokens = int([s for s in long_constraint.split() if s.isdigit()][0])
        
        assert short_tokens < long_tokens
    
    def test_max_tokens_never_exceeds_250(self, optimizer, metrics_service):
        """Test: Computed max_tokens never exceed 250 (hard limit)."""
        # Create a session with no interrupts (should return default)
        stream_id = "no_interrupt_stream"
        metrics_service._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 0,
            "total_tokens_before_interrupt": 0,
            "early_interrupts": 0,
        }
        
        result = optimizer.compute_max_tokens(intent="support_question", stream_sid=stream_id)
        assert result <= ResponseLengthOptimizer.MAX_MAX_TOKENS
    
    def test_max_tokens_never_below_50(self, optimizer, metrics_service):
        """Test: Computed max_tokens never drop below 50 (hard minimum)."""
        # Create a session with all early interrupts (should return very short)
        stream_id = "all_early_interrupt_stream"
        metrics_service._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 10,
            "total_tokens_before_interrupt": 50,
            "early_interrupts": 10,  # All interrupts are early
        }
        
        result = optimizer.compute_max_tokens(intent="confirmation", stream_sid=stream_id)
        assert result >= ResponseLengthOptimizer.MIN_MAX_TOKENS


class TestMetricsDrivenOptimization:
    """Test suite for metrics-driven response length optimization."""
    
    @pytest.fixture
    def metrics_service(self):
        """Create a fresh InterruptMetrics instance."""
        return InterruptMetrics()
    
    @pytest.fixture
    def optimizer(self, metrics_service):
        """Create ResponseLengthOptimizer."""
        return ResponseLengthOptimizer(metrics_service)
    
    def test_optimization_reduces_response_for_high_interrupt_intent(self, metrics_service, optimizer):
        """Test: Optimizer reduces response length for frequently interrupted intents."""
        stream_id = "high_interrupt_stream"
        
        # Simulate high early interrupt rate (40%)
        metrics_service._metrics[stream_id] = {
            "total_responses": 5,
            "interrupted_count": 5,
            "total_tokens_before_interrupt": 40,
            "early_interrupts": 2,  # 40% early interrupt rate
        }
        
        # Get metrics to verify
        metrics = metrics_service.get_metrics(stream_id)
        early_rate = metrics["early_interrupt_pct"] / 100.0
        assert early_rate >= 0.30  # Above high threshold
        
        # Optimizer should reduce response length
        optimized_tokens = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        default_tokens = optimizer.compute_max_tokens(intent=None, stream_sid=None)
        
        assert optimized_tokens < default_tokens
    
    def test_optimization_increases_response_for_low_interrupt_intent(self, metrics_service, optimizer):
        """Test: Optimizer keeps full response for low-interrupt intents."""
        stream_id = "low_interrupt_stream"
        
        # Simulate low early interrupt rate (5%)
        metrics_service._metrics[stream_id] = {
            "total_responses": 20,
            "interrupted_count": 2,
            "total_tokens_before_interrupt": 200,
            "early_interrupts": 0,  # 0% early interrupt rate
        }
        
        # Get metrics to verify
        metrics = metrics_service.get_metrics(stream_id)
        early_rate = metrics["early_interrupt_pct"] / 100.0
        assert early_rate < 0.15  # Below medium threshold
        
        # Optimizer should keep default/full response length
        optimized_tokens = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        default_tokens = optimizer.compute_max_tokens(intent=None, stream_sid=None)
        
        assert optimized_tokens == default_tokens
    
    def test_optimization_accounts_for_intent_defaults(self, metrics_service, optimizer):
        """Test: Optimization respects intent-specific default token limits."""
        stream_id = "stream1"
        
        # No interrupts, so optimizer uses intent defaults
        metrics_service._metrics[stream_id] = {
            "total_responses": 5,
            "interrupted_count": 0,
            "total_tokens_before_interrupt": 0,
            "early_interrupts": 0,
        }
        
        # Support questions default to 200 tokens
        support_tokens = optimizer.compute_max_tokens(intent="support_question", stream_sid=stream_id)
        assert support_tokens == 200
        
        # Confirmations default to 80 tokens
        confirm_tokens = optimizer.compute_max_tokens(intent="confirmation", stream_sid=stream_id)
        assert confirm_tokens == 80
    
    def test_optimization_with_mixed_interrupt_patterns(self, metrics_service, optimizer):
        """Test: Optimizer handles mixed interrupt patterns correctly."""
        stream_id = "mixed_stream"
        
        # Mix of early and late interrupts
        metrics_service._metrics[stream_id] = {
            "total_responses": 10,
            "interrupted_count": 6,
            "total_tokens_before_interrupt": 150,  # Average 25 tokens
            "early_interrupts": 2,  # 33% early (above high threshold)
        }
        
        metrics = metrics_service.get_metrics(stream_id)
        assert metrics["early_interrupt_pct"] > 30.0
        
        # Should reduce response length
        optimized = optimizer.compute_max_tokens(intent=None, stream_sid=stream_id)
        default = optimizer.DEFAULT_MAX_TOKENS
        assert optimized < default
    
    def test_optimization_preserves_minimum_viable_response(self, metrics_service, optimizer):
        """Test: Even with high interrupts, maintains minimum response length (50 tokens)."""
        stream_id = "extreme_interrupt_stream"
        
        # Extremely high early interrupt rate
        metrics_service._metrics[stream_id] = {
            "total_responses": 20,
            "interrupted_count": 20,
            "total_tokens_before_interrupt": 200,
            "early_interrupts": 20,  # 100% early interrupts
        }
        
        optimized = optimizer.compute_max_tokens(intent="confirmation", stream_sid=stream_id)
        
        # Should never go below 50 tokens
        assert optimized >= ResponseLengthOptimizer.MIN_MAX_TOKENS
        # Should be significantly shorter than default
        assert optimized < ResponseLengthOptimizer.DEFAULT_MAX_TOKENS
