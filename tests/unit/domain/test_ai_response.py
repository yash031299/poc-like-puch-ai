"""Unit tests for AIResponse entity."""

import pytest
from datetime import datetime, timezone


def test_ai_response_can_be_created() -> None:
    """Test AIResponse creation with required attributes."""
    from src.domain.entities.ai_response import AIResponse

    ts = datetime.now(timezone.utc)
    response = AIResponse(utterance_id="utt-1", timestamp=ts)

    assert response is not None
    assert response.utterance_id == "utt-1"
    assert response.timestamp == ts
    assert response.text == ""
    assert response.state == "generating"


def test_ai_response_validates_utterance_id() -> None:
    """Test that utterance_id cannot be empty."""
    from src.domain.entities.ai_response import AIResponse

    ts = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="utterance_id cannot be empty"):
        AIResponse(utterance_id="", timestamp=ts)


def test_ai_response_can_append_text() -> None:
    """Test that text tokens can be streamed in."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Hello")
    response.append_text(", how can")
    response.append_text(" I help?")

    assert response.text == "Hello, how can I help?"
    assert response.state == "generating"


def test_ai_response_cannot_append_to_complete_response() -> None:
    """Test that completed responses cannot receive more tokens."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Done.")
    response.complete()

    with pytest.raises(ValueError, match="Cannot append to a complete response"):
        response.append_text(" More text")


def test_ai_response_complete_transition() -> None:
    """Test state transitions: generating → complete."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Hello!")
    response.complete()

    assert response.state == "complete"
    assert response.text == "Hello!"


def test_ai_response_complete_requires_non_empty_text() -> None:
    """Test that an empty response cannot be completed."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))

    with pytest.raises(ValueError, match="Cannot complete a response with no text"):
        response.complete()


def test_ai_response_delivered_transition() -> None:
    """Test state transition: complete → delivered."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Hi there!")
    response.complete()
    response.mark_delivered()

    assert response.state == "delivered"


def test_ai_response_cannot_deliver_before_complete() -> None:
    """Test that generating responses cannot be marked delivered."""
    from src.domain.entities.ai_response import AIResponse

    response = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    response.append_text("Partial…")

    with pytest.raises(ValueError, match="Cannot deliver a response that is not complete"):
        response.mark_delivered()


def test_ai_response_has_unique_id() -> None:
    """Test that each AIResponse has a unique ID."""
    from src.domain.entities.ai_response import AIResponse

    ts = datetime.now(timezone.utc)
    r1 = AIResponse(utterance_id="utt-1", timestamp=ts)
    r2 = AIResponse(utterance_id="utt-1", timestamp=ts)

    assert r1.response_id != r2.response_id


def test_ai_response_equality_by_id() -> None:
    """Test entity identity based on response_id."""
    from src.domain.entities.ai_response import AIResponse

    r1 = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    r2 = AIResponse(utterance_id="utt-2", timestamp=datetime.now(timezone.utc))

    assert r1 != r2
    assert r1 == r1


def test_ai_response_string_representation() -> None:
    """Test __repr__ is useful."""
    from src.domain.entities.ai_response import AIResponse

    r = AIResponse(utterance_id="utt-1", timestamp=datetime.now(timezone.utc))
    r.append_text("Hello!")
    r.complete()

    s = repr(r)
    assert "AIResponse" in s
    assert "complete" in s
    assert "Hello!" in s
