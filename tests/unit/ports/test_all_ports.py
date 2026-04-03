"""Tests for all port interface definitions."""

import pytest
import asyncio
from datetime import datetime, timezone


# ── SpeechToTextPort ─────────────────────────────────────────────────────────

def test_stt_port_is_abstract() -> None:
    from src.ports.speech_to_text_port import SpeechToTextPort
    with pytest.raises(TypeError):
        SpeechToTextPort()  # type: ignore[abstract]


def test_fake_stt_port_yields_utterances() -> None:
    from src.ports.speech_to_text_port import SpeechToTextPort
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.entities.utterance import Utterance
    from src.domain.value_objects.audio_format import AudioFormat

    class FakeSTT(SpeechToTextPort):
        async def transcribe(self, stream_id, chunk):
            yield Utterance("Hello", 0.9, False, datetime.now(timezone.utc))
            yield Utterance("Hello there", 0.95, True, datetime.now(timezone.utc))

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    chunk = AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200))

    async def run():
        results = []
        async for utt in FakeSTT().transcribe("s1", chunk):
            results.append(utt)
        return results

    utterances = asyncio.run(run())
    assert len(utterances) == 2
    assert utterances[0].is_partial is True
    assert utterances[1].is_final is True


# ── LanguageModelPort ─────────────────────────────────────────────────────────

def test_llm_port_is_abstract() -> None:
    from src.ports.language_model_port import LanguageModelPort
    with pytest.raises(TypeError):
        LanguageModelPort()  # type: ignore[abstract]


def test_fake_llm_port_yields_tokens() -> None:
    from src.ports.language_model_port import LanguageModelPort
    from src.domain.entities.utterance import Utterance

    class FakeLLM(LanguageModelPort):
        async def generate(self, stream_id, utterance, context):
            for token in ["Hi", " there", "!"]:
                yield token

    utt = Utterance("Hello", 0.95, True, datetime.now(timezone.utc))

    async def run():
        tokens = []
        async for t in FakeLLM().generate("s1", utt, []):
            tokens.append(t)
        return tokens

    tokens = asyncio.run(run())
    assert tokens == ["Hi", " there", "!"]
    assert "".join(tokens) == "Hi there!"


# ── TextToSpeechPort ──────────────────────────────────────────────────────────

def test_tts_port_is_abstract() -> None:
    from src.ports.text_to_speech_port import TextToSpeechPort
    with pytest.raises(TypeError):
        TextToSpeechPort()  # type: ignore[abstract]


def test_fake_tts_port_yields_segments() -> None:
    from src.ports.text_to_speech_port import TextToSpeechPort
    from src.domain.entities.ai_response import AIResponse
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    class FakeTTS(TextToSpeechPort):
        async def synthesize(self, stream_id, response):
            yield SpeechSegment(response.response_id, 0, bytes(3200), fmt, False, datetime.now(timezone.utc))
            yield SpeechSegment(response.response_id, 1, bytes(3200), fmt, True, datetime.now(timezone.utc))

    r = AIResponse("utt-1", datetime.now(timezone.utc))
    r.append_text("Hi there!")
    r.complete()

    async def run():
        segs = []
        async for seg in FakeTTS().synthesize("s1", r):
            segs.append(seg)
        return segs

    segs = asyncio.run(run())
    assert len(segs) == 2
    assert segs[0].position == 0
    assert segs[1].is_last is True


# ── SessionRepositoryPort ─────────────────────────────────────────────────────

def test_session_repo_port_is_abstract() -> None:
    from src.ports.session_repository_port import SessionRepositoryPort
    with pytest.raises(TypeError):
        SessionRepositoryPort()  # type: ignore[abstract]


def test_fake_session_repo_stores_and_retrieves_sessions() -> None:
    from src.ports.session_repository_port import SessionRepositoryPort
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat

    class FakeSessionRepo(SessionRepositoryPort):
        def __init__(self):
            self._store = {}

        async def save(self, session):
            self._store[session.stream_identifier.value] = session

        async def get(self, stream_id):
            return self._store.get(stream_id)

        async def delete(self, stream_id):
            self._store.pop(stream_id, None)

    async def run():
        repo = FakeSessionRepo()
        session = ConversationSession.create(
            stream_identifier=StreamIdentifier("stream-123"),
            caller_number="+1111111111",
            called_number="+2222222222",
            audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
        )

        await repo.save(session)
        retrieved = await repo.get("stream-123")
        assert retrieved == session

        await repo.delete("stream-123")
        gone = await repo.get("stream-123")
        assert gone is None

    asyncio.run(run())
