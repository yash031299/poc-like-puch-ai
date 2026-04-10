"""Unit tests for InterruptMetrics service."""

import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_interrupt_metrics_records_interrupt_on_response_and_session() -> None:
    """Test that record_interrupt updates both response and session."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Hello there, can I help you today?")
    response.complete()
    
    session.add_ai_response(response)
    
    # Record interrupt
    await metrics.record_interrupt(
        session=session,
        response=response,
        token_count=3,
        context="Hello there"
    )
    
    # Response should have interrupt metadata
    assert response.is_interrupted()
    assert response.interrupted_at_token_count == 3
    assert response.interrupted_at_timestamp is not None
    assert response.interrupted_context == "Hello there"
    
    # Session should have interrupt in history
    assert len(session.interrupt_history) == 1
    assert session.interrupt_history[0].token_count == 3


@pytest.mark.asyncio
async def test_interrupt_metrics_computes_interrupt_rate() -> None:
    """Test that get_metrics computes accurate interrupt rate."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-123",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Simulate 10 responses, 3 of which are interrupted
    for i in range(10):
        response = AIResponse(
            utterance_id=f"utt-{i}",
            timestamp=datetime.now(timezone.utc)
        )
        response.append_text(f"Response {i}")
        response.complete()
        session.add_ai_response(response)
        
        # Count all responses
        metrics.increment_response_count("stream-123")
        
        # Interrupt 3 of them
        if i in [0, 3, 7]:
            await metrics.record_interrupt(
                session=session,
                response=response,
                token_count=5,
                context="test"
            )
    
    computed_metrics = metrics.get_metrics("stream-123")
    assert computed_metrics["total_responses"] == 10
    assert computed_metrics["interrupted_count"] == 3
    assert abs(computed_metrics["interrupt_rate"] - 0.3) < 0.01


@pytest.mark.asyncio
async def test_interrupt_metrics_computes_avg_tokens() -> None:
    """Test that get_metrics computes correct average tokens before interrupt."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-456",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Add 4 responses interrupted at different token counts
    token_counts = [5, 10, 15, 20]  # avg = 12.5
    for i, token_count in enumerate(token_counts):
        response = AIResponse(
            utterance_id=f"utt-{i}",
            timestamp=datetime.now(timezone.utc)
        )
        response.append_text(f"Response {i}")
        response.complete()
        session.add_ai_response(response)
        
        metrics.increment_response_count("stream-456")
        
        await metrics.record_interrupt(
            session=session,
            response=response,
            token_count=token_count,
            context="test"
        )
    
    computed_metrics = metrics.get_metrics("stream-456")
    assert computed_metrics["interrupted_count"] == 4
    assert abs(computed_metrics["avg_tokens_before_interrupt"] - 12.5) < 0.1


@pytest.mark.asyncio
async def test_interrupt_metrics_computes_early_interrupt_percentage() -> None:
    """Test that get_metrics computes early interrupt percentage correctly."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-789",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Create 10 interrupts: 6 early (< 10 tokens), 4 late (>= 10 tokens)
    token_counts = [2, 3, 5, 8, 9] + [15, 20, 25, 30, 40]
    for i, token_count in enumerate(token_counts):
        response = AIResponse(
            utterance_id=f"utt-{i}",
            timestamp=datetime.now(timezone.utc)
        )
        response.append_text(f"Response {i}")
        response.complete()
        session.add_ai_response(response)
        
        metrics.increment_response_count("stream-789")
        
        await metrics.record_interrupt(
            session=session,
            response=response,
            token_count=token_count,
            context="test"
        )
    
    computed_metrics = metrics.get_metrics("stream-789")
    assert computed_metrics["interrupted_count"] == 10
    # 5 out of 10 = 50% (5 early interrupts: 2,3,5,8,9)
    assert abs(computed_metrics["early_interrupt_pct"] - 50.0) < 1.0


@pytest.mark.asyncio
async def test_interrupt_metrics_returns_zero_for_unknown_stream() -> None:
    """Test that get_metrics returns zeros for unknown streams."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    
    metrics = InterruptMetrics()
    
    computed_metrics = metrics.get_metrics("unknown-stream")
    
    assert computed_metrics["interrupt_rate"] == 0.0
    assert computed_metrics["avg_tokens_before_interrupt"] == 0
    assert computed_metrics["early_interrupt_pct"] == 0.0
    assert computed_metrics["interrupted_count"] == 0
    assert computed_metrics["total_responses"] == 0


@pytest.mark.asyncio
async def test_interrupt_metrics_infers_intent_correctly() -> None:
    """Test that interrupt intent inference works based on token count."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-999",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    # Early interrupt (token_count=5, should infer early_rejection)
    response1 = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response1.append_text("Hello")
    response1.complete()
    session.add_ai_response(response1)
    metrics.increment_response_count("stream-999")
    
    await metrics.record_interrupt(
        session=session,
        response=response1,
        token_count=5,
        context="Hello"
    )
    
    assert session.interrupt_history[0].intent == "early_rejection"
    
    # Mid-range interrupt (token_count=15, should infer clarification)
    response2 = AIResponse(utterance_id="utt-2", timestamp=datetime.now(timezone.utc))
    response2.append_text("This is a longer response")
    response2.complete()
    session.add_ai_response(response2)
    metrics.increment_response_count("stream-999")
    
    await metrics.record_interrupt(
        session=session,
        response=response2,
        token_count=15,
        context="This is a longer"
    )
    
    assert session.interrupt_history[1].intent == "clarification"
    
    # Late interrupt (token_count=35, should infer objection_or_question)
    response3 = AIResponse(utterance_id="utt-3", timestamp=datetime.now(timezone.utc))
    response3.append_text("This is a very long response with lots of information")
    response3.complete()
    session.add_ai_response(response3)
    metrics.increment_response_count("stream-999")
    
    await metrics.record_interrupt(
        session=session,
        response=response3,
        token_count=35,
        context="This is a very long response with"
    )
    
    assert session.interrupt_history[2].intent == "objection_or_question"


@pytest.mark.asyncio
async def test_interrupt_metrics_validation() -> None:
    """Test that record_interrupt validates inputs."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-abc",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Test")
    response.complete()
    
    # Negative token count
    with pytest.raises(ValueError, match="token_count cannot be negative"):
        await metrics.record_interrupt(
            session=session,
            response=response,
            token_count=-1,
            context="test"
        )


@pytest.mark.asyncio
async def test_interrupt_metrics_clear_metrics() -> None:
    """Test that clear_metrics removes stored metrics."""
    from src.domain.services.interrupt_metrics import InterruptMetrics
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.entities.ai_response import AIResponse
    
    metrics = InterruptMetrics()
    
    session = ConversationSession.create(
        stream_identifier="stream-def",
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
    )
    
    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Test")
    response.complete()
    session.add_ai_response(response)
    
    metrics.increment_response_count("stream-def")
    
    await metrics.record_interrupt(session=session, response=response, token_count=3, context="t")
    
    # Metrics should exist
    assert metrics.get_metrics("stream-def")["interrupted_count"] == 1
    
    # Clear metrics
    metrics.clear_metrics("stream-def")
    
    # Should return zeros
    result = metrics.get_metrics("stream-def")
    assert result["interrupted_count"] == 0
