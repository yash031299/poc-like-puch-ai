"""InterruptMetrics service - Analyze interrupt patterns and compute analytics."""

from typing import Dict, Optional
from datetime import datetime, timezone

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.ai_response import AIResponse


class InterruptMetrics:
    """
    Service for recording and analyzing user interrupt patterns during responses.
    
    Business Rules:
    - Records interrupt metadata in AIResponse entities
    - Maintains in-memory metrics during active calls
    - Computes: interrupt_rate, early_interrupt_pct, avg_tokens_before_interrupt
    - Integrates with session history for auditing/analytics
    """
    
    def __init__(self) -> None:
        """Initialize the interrupt metrics service."""
        # In-memory metrics storage: stream_id -> metrics dict
        self._metrics: Dict[str, Dict] = {}
    
    async def record_interrupt(
        self,
        session: ConversationSession,
        response: AIResponse,
        token_count: int,
        context: str = ""
    ) -> None:
        """
        Record an interrupt on a response and update session history.
        
        Business Rule: This method integrates interrupt tracking at both the
        response level (response-specific data) and session level (aggregate history).
        
        Args:
            session: The ConversationSession containing the response
            response: The AIResponse being interrupted
            token_count: Which token # the user interrupted at
            context: What was being said (response text up to interrupt point)
            
        Raises:
            ValueError: If token_count is invalid or session/response invalid
        """
        if token_count < 0:
            raise ValueError("token_count cannot be negative")
        if not session:
            raise ValueError("session cannot be None")
        if not response:
            raise ValueError("response cannot be None")
        
        # Record interrupt on the response
        now = datetime.now(timezone.utc)
        response.record_interrupt(
            token_count=token_count,
            timestamp=now,
            context=context or response.text[:50]  # Use first 50 chars as fallback
        )
        
        # Record in session history with inferred intent
        intent = self._infer_interrupt_intent(response.text, token_count)
        session.record_interrupt(
            token_count=token_count,
            context=context or response.text[:50],
            intent=intent
        )
        
        # Update in-memory metrics
        stream_id = session.stream_id
        if stream_id not in self._metrics:
            self._metrics[stream_id] = {
                "total_responses": 0,
                "interrupted_count": 0,
                "total_tokens_before_interrupt": 0,
                "early_interrupts": 0,  # Interrupts before 10 tokens
            }
        
        metrics = self._metrics[stream_id]
        metrics["interrupted_count"] += 1
        metrics["total_tokens_before_interrupt"] += token_count
        
        if token_count < 10:
            metrics["early_interrupts"] += 1
    
    def increment_response_count(self, stream_id: str) -> None:
        """
        Increment the total response count for a stream.
        
        Business Rule: Call this every time a response is generated,
        regardless of whether it's interrupted.
        
        Args:
            stream_id: The stream identifier
        """
        if stream_id not in self._metrics:
            self._metrics[stream_id] = {
                "total_responses": 0,
                "interrupted_count": 0,
                "total_tokens_before_interrupt": 0,
                "early_interrupts": 0,
            }
        
        self._metrics[stream_id]["total_responses"] += 1
    
    def get_metrics(self, stream_id: str) -> Dict:
        """
        Get computed metrics for a stream/call.
        
        Returns:
            Dictionary with:
            - interrupt_rate: % of responses interrupted
            - avg_tokens_before_interrupt: Average token count at interrupt
            - early_interrupt_pct: % of interrupts before 10 tokens
            - interrupted_count: Total number of interrupts
            - total_responses: Total number of responses generated
        """
        if stream_id not in self._metrics:
            return {
                "interrupt_rate": 0.0,
                "avg_tokens_before_interrupt": 0,
                "early_interrupt_pct": 0.0,
                "interrupted_count": 0,
                "total_responses": 0,
            }
        
        metrics = self._metrics[stream_id]
        
        interrupt_rate = (
            metrics["interrupted_count"] / metrics["total_responses"]
            if metrics["total_responses"] > 0
            else 0.0
        )
        
        avg_tokens = (
            metrics["total_tokens_before_interrupt"] / metrics["interrupted_count"]
            if metrics["interrupted_count"] > 0
            else 0
        )
        
        early_interrupt_pct = (
            (metrics["early_interrupts"] / metrics["interrupted_count"] * 100)
            if metrics["interrupted_count"] > 0
            else 0.0
        )
        
        return {
            "interrupt_rate": round(interrupt_rate, 3),
            "avg_tokens_before_interrupt": round(avg_tokens, 1),
            "early_interrupt_pct": round(early_interrupt_pct, 1),
            "interrupted_count": metrics["interrupted_count"],
            "total_responses": metrics["total_responses"],
        }
    
    def clear_metrics(self, stream_id: str) -> None:
        """
        Clear metrics for a stream (e.g., call ended).
        
        Args:
            stream_id: The stream identifier to clear
        """
        self._metrics.pop(stream_id, None)
    
    def _infer_interrupt_intent(self, response_text: str, token_count: int) -> str:
        """
        Infer the user's likely intent based on when they interrupted.
        
        Business Rule: Early interrupts (< 10 tokens) suggest rejection/objection.
        Later interrupts suggest clarification or additional question.
        
        Args:
            response_text: The response text being interrupted
            token_count: The token count at interrupt
            
        Returns:
            Inferred intent category
        """
        if token_count < 10:
            return "early_rejection"
        elif token_count < 30:
            return "clarification"
        else:
            return "objection_or_question"
