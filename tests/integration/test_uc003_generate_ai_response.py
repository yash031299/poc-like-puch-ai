"""Integration tests for UC-003: Generate AI Response.

Verifies Gherkin scenarios from features/UC-003-generate-ai-response.feature
"""

from datetime import datetime, timezone


# ── helpers ──────────────────────────────────────────────────────────────────

def _base_conversation():
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    conv = ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-ai-test"),
        caller_number="+1234567890",
        called_number="+0987654321",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    conv.activate()
    return conv


# ── tests ─────────────────────────────────────────────────────────────────────

def test_uc003_generate_response_for_utterance() -> None:
    """
    Scenario: Generate AI response for a caller's utterance
      Given the caller says "Hello, can you help me?"
      When the AI generates a response
      Then an AIResponse entity is created
      And the response is linked to the caller's utterance
      And the response text is non-empty when complete
    """
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse

    conv = _base_conversation()

    # Caller says something
    utterance = Utterance(
        text="Hello, can you help me?",
        confidence=0.95,
        is_final=True,
        timestamp=datetime.now(timezone.utc),
    )
    conv.add_utterance(utterance)

    # AI generates a response (simulated streaming)
    response = AIResponse(utterance_id=utterance.utterance_id, timestamp=datetime.now(timezone.utc))
    response.append_text("Hello!")
    response.append_text(" Of course, I'd be happy to help.")
    response.complete()

    conv.add_ai_response(response)

    # Assertions
    assert len(conv.ai_responses) == 1
    assert conv.latest_ai_response == response
    assert response.utterance_id == utterance.utterance_id
    assert response.text == "Hello! Of course, I'd be happy to help."
    assert response.state == "complete"


def test_uc003_streaming_response_builds_progressively() -> None:
    """
    Scenario: AI streams its response incrementally
      Given the caller has asked a question
      When the AI generates a response token by token
      Then each token appended grows the response text
      And the text builds monotonically (never shrinks)
    """
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse

    conv = _base_conversation()

    utterance = Utterance(
        text="What time is it?",
        confidence=0.92,
        is_final=True,
        timestamp=datetime.now(timezone.utc),
    )
    conv.add_utterance(utterance)

    response = AIResponse(utterance_id=utterance.utterance_id, timestamp=datetime.now(timezone.utc))
    tokens = ["The", " current", " time", " is", " 3 PM."]

    previous_len = 0
    for token in tokens:
        response.append_text(token)
        assert len(response.text) >= previous_len  # monotonically growing
        previous_len = len(response.text)

    response.complete()
    assert response.text == "The current time is 3 PM."
    assert response.state == "complete"


def test_uc003_response_marked_delivered_after_speech_synthesis() -> None:
    """
    Scenario: Response delivered to caller after speech synthesis
      Given an AIResponse is complete
      When the synthesized audio is sent to the caller
      Then the AIResponse is marked as delivered
      And SpeechSegments are recorded in the conversation
    """
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    conv = _base_conversation()
    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    utterance = Utterance("Help me", 0.90, True, datetime.now(timezone.utc))
    conv.add_utterance(utterance)

    response = AIResponse(utterance_id=utterance.utterance_id, timestamp=datetime.now(timezone.utc))
    response.append_text("Sure, I can help!")
    response.complete()
    conv.add_ai_response(response)

    # TTS produces two speech segments
    seg0 = SpeechSegment(response.response_id, 0, bytes(3200), fmt, False, datetime.now(timezone.utc))
    seg1 = SpeechSegment(response.response_id, 1, bytes(3200), fmt, True, datetime.now(timezone.utc))
    conv.add_speech_segment(seg0)
    conv.add_speech_segment(seg1)

    # Response delivered
    response.mark_delivered()

    assert response.state == "delivered"
    assert len(conv.speech_segments) == 2
    segs = conv.get_speech_segments_for(response.response_id)
    assert segs[0].position == 0
    assert segs[1].position == 1
    assert segs[1].is_last is True


def test_uc003_multiple_turns_in_conversation() -> None:
    """
    Scenario: Multi-turn conversation with several utterances and responses
      Given a caller has a multi-turn conversation
      When each utterance gets a corresponding AI response
      Then the conversation records all turns in order
    """
    from src.domain.entities.utterance import Utterance
    from src.domain.entities.ai_response import AIResponse

    conv = _base_conversation()

    turns = [
        ("Hello!", "Hi there! How can I help?"),
        ("What is the weather?", "It's sunny today."),
        ("Thanks!", "You're welcome! Have a great day."),
    ]

    for caller_text, ai_text in turns:
        utt = Utterance(caller_text, 0.93, True, datetime.now(timezone.utc))
        conv.add_utterance(utt)

        resp = AIResponse(utt.utterance_id, datetime.now(timezone.utc))
        resp.append_text(ai_text)
        resp.complete()
        resp.mark_delivered()
        conv.add_ai_response(resp)

    assert len(conv.utterances) == 3
    assert len(conv.ai_responses) == 3

    for utt, resp in zip(conv.utterances, conv.ai_responses):
        assert resp.utterance_id == utt.utterance_id
        assert resp.state == "delivered"
