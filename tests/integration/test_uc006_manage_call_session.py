"""Integration tests for UC-006: Manage Call Session.

Verifies the Gherkin scenarios from features/UC-006-manage-call-session.feature.
Tests are pure domain/application — no external dependencies.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from src.domain.aggregates.conversation_session import ConversationSession
from src.domain.entities.ai_response import AIResponse
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat
from src.domain.value_objects.stream_identifier import StreamIdentifier


def _make_session(sid: str = "sid-001") -> ConversationSession:
    return ConversationSession.create(
        stream_identifier=StreamIdentifier(sid),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1),
    )


def _fmt() -> AudioFormat:
    return AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)


def _chunk(seq: int) -> AudioChunk:
    return AudioChunk(seq, datetime.now(timezone.utc), _fmt(), bytes(3200))


def _utterance(text: str, is_final: bool = True) -> Utterance:
    return Utterance(text, 0.95, is_final, datetime.now(timezone.utc))


def _ai_response(text: str) -> AIResponse:
    r = AIResponse("utt-1", datetime.now(timezone.utc))
    r.append_text(text)
    r.complete()
    return r


# ── Scenario: Initialize new call session ─────────────────────────────────────

def test_uc006_new_session_starts_in_initiated_state() -> None:
    session = _make_session()
    assert session.call_session.state == "initiated"


def test_uc006_new_session_has_unique_stream_identifier() -> None:
    s1 = _make_session("sid-A")
    s2 = _make_session("sid-B")
    assert s1.stream_id != s2.stream_id


def test_uc006_new_session_not_active_not_ended() -> None:
    session = _make_session()
    assert not session.is_active
    assert not session.is_ended


# ── Scenario: Transition session state through lifecycle ──────────────────────

def test_uc006_activate_transitions_to_active() -> None:
    session = _make_session()
    session.activate()
    assert session.is_active
    assert not session.is_ended


def test_uc006_end_transitions_to_ended() -> None:
    session = _make_session()
    session.activate()
    session.end()
    assert session.is_ended
    assert not session.is_active


def test_uc006_cannot_re_activate_ended_session() -> None:
    session = _make_session()
    session.activate()
    session.end()
    with pytest.raises(Exception):
        session.activate()


# ── Scenario: Track conversation entities within session ──────────────────────

def test_uc006_audio_chunks_stored_in_session() -> None:
    session = _make_session()
    session.activate()
    session.add_audio_chunk(_chunk(1))
    session.add_audio_chunk(_chunk(2))
    assert len(session.audio_chunks) == 2


def test_uc006_utterances_stored_in_session() -> None:
    session = _make_session()
    session.activate()
    utt = _utterance("Hello")
    session.add_utterance(utt)
    assert len(session.utterances) == 1
    assert session.utterances[0].text == "Hello"


def test_uc006_ai_responses_stored_in_session() -> None:
    session = _make_session()
    session.activate()
    resp = _ai_response("How can I help?")
    session.add_ai_response(resp)
    assert len(session.ai_responses) == 1


def test_uc006_speech_segments_stored_in_session() -> None:
    session = _make_session()
    session.activate()
    seg = SpeechSegment("r1", 0, bytes(3200), _fmt(), True, datetime.now(timezone.utc))
    session.add_speech_segment(seg)
    assert len(session.speech_segments) == 1


# ── Scenario: Maintain conversation context ───────────────────────────────────

def test_uc006_final_utterances_accessible_for_context() -> None:
    session = _make_session()
    session.activate()
    session.add_utterance(_utterance("First turn", is_final=True))
    session.add_utterance(_utterance("Second turn", is_final=True))
    finals = session.final_utterances
    assert len(finals) == 2
    assert finals[0].text == "First turn"
    assert finals[1].text == "Second turn"


def test_uc006_partial_utterances_excluded_from_finals() -> None:
    session = _make_session()
    session.activate()
    session.add_utterance(_utterance("Complete thought", is_final=True))
    session.add_utterance(_utterance("partial...", is_final=False))
    assert len(session.final_utterances) == 1


# ── Scenario: Prevent adding entities to ended session ───────────────────────

def test_uc006_cannot_add_audio_chunk_to_ended_session() -> None:
    session = _make_session()
    session.activate()
    session.end()
    with pytest.raises(ValueError, match="ended"):
        session.add_audio_chunk(_chunk(1))


# ── Scenario: Query session state ────────────────────────────────────────────

def test_uc006_session_tracks_caller_info() -> None:
    session = ConversationSession.create(
        stream_identifier=StreamIdentifier("sid-caller"),
        caller_number="+91XXXXXXXXXX",
        called_number="+1800XXXXXXX",
        audio_format=_fmt(),
    )
    assert session.caller_number == "+91XXXXXXXXXX"
    assert session.called_number == "+1800XXXXXXX"


def test_uc006_session_stream_id_accessible() -> None:
    session = _make_session("sid-query")
    assert session.stream_id == "sid-query"


# ── Scenario: Retrieve conversation history in order ─────────────────────────

def test_uc006_utterances_returned_in_chronological_order() -> None:
    session = _make_session()
    session.activate()
    for i, text in enumerate(["First", "Second", "Third"]):
        session.add_utterance(_utterance(text))
    texts = [u.text for u in session.utterances]
    assert texts == ["First", "Second", "Third"]


# ── Rule: State transitions must be valid ─────────────────────────────────────

def test_uc006_state_machine_initiated_to_active_to_ended() -> None:
    session = _make_session()
    assert session.call_session.state == "initiated"
    session.activate()
    assert session.call_session.state == "active"
    session.end()
    assert session.call_session.state == "ended"


def test_uc006_no_transition_from_ended() -> None:
    session = _make_session()
    session.activate()
    session.end()
    with pytest.raises(Exception):
        session.end()  # already ended
