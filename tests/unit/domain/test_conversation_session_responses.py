"""Tests for ConversationSession with AIResponse and SpeechSegment."""

import pytest
from datetime import datetime, timezone


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_conversation():
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    return ConversationSession.create(
        stream_identifier=StreamIdentifier("stream-r"),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )


def _make_utterance(text: str = "Hello"):
    from src.domain.entities.utterance import Utterance
    return Utterance(text=text, confidence=0.95, is_final=True, timestamp=datetime.now(timezone.utc))


def _make_response(utterance_id: str):
    from src.domain.entities.ai_response import AIResponse
    r = AIResponse(utterance_id=utterance_id, timestamp=datetime.now(timezone.utc))
    r.append_text("Hi there!")
    r.complete()
    return r


def _make_segment(response_id: str, position: int = 0, is_last: bool = True):
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat
    return SpeechSegment(
        response_id=response_id,
        position=position,
        audio_data=bytes(3200),
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        is_last=is_last,
        timestamp=datetime.now(timezone.utc),
    )


# ── AIResponse collection ────────────────────────────────────────────────────

def test_can_add_ai_response_to_conversation() -> None:
    conv = _make_conversation()
    utt = _make_utterance()
    conv.add_utterance(utt)

    resp = _make_response(utt.utterance_id)
    conv.add_ai_response(resp)

    assert len(conv.ai_responses) == 1
    assert conv.ai_responses[0] == resp


def test_latest_ai_response_returns_most_recent() -> None:
    conv = _make_conversation()

    utt1 = _make_utterance("First")
    utt2 = _make_utterance("Second")
    conv.add_utterance(utt1)
    conv.add_utterance(utt2)

    resp1 = _make_response(utt1.utterance_id)
    resp2 = _make_response(utt2.utterance_id)
    conv.add_ai_response(resp1)
    conv.add_ai_response(resp2)

    assert conv.latest_ai_response == resp2


def test_latest_ai_response_is_none_when_empty() -> None:
    conv = _make_conversation()
    assert conv.latest_ai_response is None


def test_ai_responses_for_utterance() -> None:
    """Can retrieve all AIResponses for a specific utterance."""
    conv = _make_conversation()
    utt = _make_utterance()
    conv.add_utterance(utt)

    resp = _make_response(utt.utterance_id)
    conv.add_ai_response(resp)

    results = conv.get_ai_responses_for(utt.utterance_id)
    assert len(results) == 1
    assert results[0] == resp


# ── SpeechSegment collection ─────────────────────────────────────────────────

def test_can_add_speech_segment_to_conversation() -> None:
    conv = _make_conversation()
    utt = _make_utterance()
    conv.add_utterance(utt)
    resp = _make_response(utt.utterance_id)
    conv.add_ai_response(resp)

    seg = _make_segment(resp.response_id)
    conv.add_speech_segment(seg)

    assert len(conv.speech_segments) == 1
    assert conv.speech_segments[0] == seg


def test_speech_segments_for_response() -> None:
    """Can retrieve segments belonging to a specific response."""
    conv = _make_conversation()
    utt = _make_utterance()
    conv.add_utterance(utt)
    resp = _make_response(utt.utterance_id)
    conv.add_ai_response(resp)

    seg0 = _make_segment(resp.response_id, position=0, is_last=False)
    seg1 = _make_segment(resp.response_id, position=1, is_last=True)
    conv.add_speech_segment(seg0)
    conv.add_speech_segment(seg1)

    segs = conv.get_speech_segments_for(resp.response_id)
    assert len(segs) == 2
    assert segs[0].position == 0
    assert segs[1].position == 1
