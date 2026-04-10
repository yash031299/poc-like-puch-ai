"""ResponseLengthOptimizer — Dynamically optimize response length based on interrupt patterns."""

import logging
from typing import Optional, Dict
from src.domain.services.interrupt_metrics import InterruptMetrics

logger = logging.getLogger(__name__)


class ResponseLengthOptimizer:
    """
    Service that computes optimal response length based on interrupt metrics.
    
    Business Rules:
    - Monitors early interrupt rate (interrupts in first 20% of response)
    - Reduces response length for intents with high early interrupt rates
    - Supports A/B testing with control vs optimized variants
    
    Architecture:
    - Depends on InterruptMetrics from Phase 3D.1
    - Outputs max_tokens range: 50-250 (default 150)
    - Integrates with prompt constraint in LLM calls
    """
    
    # Default and range constants
    DEFAULT_MAX_TOKENS = 150
    MIN_MAX_TOKENS = 50
    MAX_MAX_TOKENS = 250
    
    # Intent-specific defaults
    INTENT_DEFAULTS: Dict[str, int] = {
        "support_question": 200,      # Support → longer
        "confirmation": 80,            # Confirmation → shorter
        "clarification": 120,           # Clarification → medium
        "objection_or_question": 150,  # Default
        "early_rejection": 100,         # Early rejection → shorter
    }
    
    # Thresholds for early interrupt rate detection
    HIGH_EARLY_INTERRUPT_THRESHOLD = 0.30  # > 30%
    MEDIUM_EARLY_INTERRUPT_THRESHOLD = 0.15  # > 15%
    
    def __init__(self, metrics_service: InterruptMetrics):
        """
        Initialize ResponseLengthOptimizer with interrupt metrics service.
        
        Args:
            metrics_service: InterruptMetrics instance from Phase 3D.1
        """
        self._metrics = metrics_service
        logger.info("ResponseLengthOptimizer initialized with InterruptMetrics")
    
    def compute_max_tokens(self, intent: Optional[str] = None, stream_sid: Optional[str] = None) -> int:
        """
        Compute optimal max_tokens for a response based on interrupt metrics.
        
        Algorithm:
        1. Get early_interrupt_rate from metrics for this stream
        2. If high (> 30%), return SHORT (75 tokens)
        3. If medium (> 15%), return MEDIUM (110 tokens)
        4. Otherwise, return FULL (150 tokens) or intent-specific default
        
        Args:
            intent: The user intent (support_question, confirmation, etc.)
            stream_sid: Optional stream identifier for A/B variant lookup
            
        Returns:
            Recommended max_tokens (50-250 range)
        """
        # Default to intent-specific max tokens
        base_max_tokens = self.INTENT_DEFAULTS.get(intent, self.DEFAULT_MAX_TOKENS)
        
        # If no stream_sid, return base
        if not stream_sid:
            return self._clamp_tokens(base_max_tokens)
        
        # Get interrupt metrics for this stream
        metrics = self._metrics.get_metrics(stream_sid)
        if not metrics:
            return self._clamp_tokens(base_max_tokens)
        
        # Compute early interrupt rate (% of interrupts in first 20% of response)
        early_interrupt_pct = metrics.get("early_interrupt_pct", 0.0)
        early_interrupt_rate = early_interrupt_pct / 100.0 if early_interrupt_pct else 0.0
        
        # Apply reduction based on early interrupt rate
        if early_interrupt_rate > self.HIGH_EARLY_INTERRUPT_THRESHOLD:
            # High early interrupts → very short response
            optimized_tokens = int(base_max_tokens * 0.5)  # 50% reduction
            logger.info(
                f"High early interrupt rate ({early_interrupt_rate:.1%}) for intent={intent}, "
                f"reducing max_tokens from {base_max_tokens} to {optimized_tokens}"
            )
            return self._clamp_tokens(optimized_tokens)
        
        elif early_interrupt_rate > self.MEDIUM_EARLY_INTERRUPT_THRESHOLD:
            # Medium early interrupts → slightly shorter response
            optimized_tokens = int(base_max_tokens * 0.73)  # ~27% reduction
            logger.info(
                f"Medium early interrupt rate ({early_interrupt_rate:.1%}) for intent={intent}, "
                f"reducing max_tokens from {base_max_tokens} to {optimized_tokens}"
            )
            return self._clamp_tokens(optimized_tokens)
        
        else:
            # Low early interrupts → keep default
            logger.debug(
                f"Low early interrupt rate ({early_interrupt_rate:.1%}) for intent={intent}, "
                f"using default max_tokens={base_max_tokens}"
            )
            return self._clamp_tokens(base_max_tokens)
    
    def _clamp_tokens(self, tokens: int) -> int:
        """
        Clamp tokens to valid range [MIN_MAX_TOKENS, MAX_MAX_TOKENS].
        
        Args:
            tokens: Token count to clamp
            
        Returns:
            Clamped token count
        """
        return max(self.MIN_MAX_TOKENS, min(tokens, self.MAX_MAX_TOKENS))
    
    def get_intent_default(self, intent: Optional[str]) -> int:
        """
        Get default max_tokens for a specific intent.
        
        Args:
            intent: The intent (support_question, confirmation, etc.)
            
        Returns:
            Default max_tokens for that intent
        """
        return self.INTENT_DEFAULTS.get(intent, self.DEFAULT_MAX_TOKENS)
    
    def get_constraint_text(self, max_tokens: int) -> str:
        """
        Generate prompt constraint text for LLM.
        
        Args:
            max_tokens: Maximum tokens allowed
            
        Returns:
            Constraint text to add to prompt
        """
        return f"Keep your response concise and under {max_tokens} tokens."
