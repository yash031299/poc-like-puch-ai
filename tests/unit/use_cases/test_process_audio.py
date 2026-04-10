"""Tests for ProcessAudioUseCase."""

import pytest
import asyncio
from datetime import datetime, timezone


class FakeSessionRepo:
    def __init__(self, session=None):
        self._store = {session.stream_identifier.value: session} if session else {}

    async def save(self, session): self._store[session.stream_identifier.value] = session
    async def get(self, sid): return self._store.get(sid)
    async def delete(self, sid): self._store.pop(sid, None)


class FakeSTT:
    """Yields a partial then a final utterance."""
    def __init__(self, final_text: str = "Hello"):
        self.final_text = final_text

    async def transcribe(self, stream_id, chunk):
        from src.domain.entities.utterance import Utterance
        yield Utterance(self.final_text[:4] or "He", 0.7, False, datetime.now(timezone.utc))
        yield Utterance(self.final_text, 0.95, True, datetime.now(timezone.utc))


class FakeBufferManager:
    def __init__(self):
        self.flushed = {}
        self.flush_calls = []

    def add_chunk(self, stream_id, chunk):
        return None

    def flush(self, stream_id):
        self.flush_calls.append(stream_id)
        return self.flushed.get(stream_id)


def _make_active_session(stream_id="s1"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    sess = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    sess.activate()
    return sess


def test_process_audio_adds_chunk_and_utterances() -> None:
    from src.use_cases.process_audio import ProcessAudioUseCase
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    session = _make_active_session("s1")
    repo = FakeSessionRepo(session)
    stt = FakeSTT("Hello there")
    use_case = ProcessAudioUseCase(session_repo=repo, stt=stt)

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    chunk = AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200))

    async def run():
        return await use_case.execute(stream_id="s1", chunk=chunk)

    utterances = asyncio.run(run())

    # Chunk added to session
    assert len(session.audio_chunks) == 1

    # Utterances returned (partial + final)
    assert len(utterances) == 2
    assert utterances[-1].is_final is True
    assert utterances[-1].text == "Hello there"

    # Utterances stored in session
    assert len(session.utterances) == 2


def test_process_audio_raises_if_session_not_found() -> None:
    from src.use_cases.process_audio import ProcessAudioUseCase
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    repo = FakeSessionRepo()  # empty
    stt = FakeSTT()
    use_case = ProcessAudioUseCase(session_repo=repo, stt=stt)

    chunk = AudioChunk(1, datetime.now(timezone.utc),
                       AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1), bytes(3200))

    async def run():
        with pytest.raises(ValueError, match="No active session for stream missing"):
            await use_case.execute(stream_id="missing", chunk=chunk)

    asyncio.run(run())


def test_finalize_stream_flushes_buffered_audio() -> None:
    from src.use_cases.process_audio import ProcessAudioUseCase
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    session = _make_active_session("s1")
    repo = FakeSessionRepo(session)
    stt = FakeSTT("Buffered done")
    buffer_manager = FakeBufferManager()
    use_case = ProcessAudioUseCase(session_repo=repo, stt=stt, buffer_manager=buffer_manager)

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    buffer_manager.flushed["s1"] = [
        AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200)),
        AudioChunk(2, datetime.now(timezone.utc), fmt, bytes(3200)),
    ]

    async def run():
        return await use_case.finalize_stream("s1")

    utterances = asyncio.run(run())
    # FakeSTT yields 2 utterances per chunk (partial + final).
    # With 2 buffered chunks, that's 4 utterances total.
    assert len(utterances) == 4
    assert utterances[-1].text == "Buffered done"
    assert "s1" in buffer_manager.flush_calls


def test_finalize_stream_returns_empty_when_no_buffered_audio() -> None:
    from src.use_cases.process_audio import ProcessAudioUseCase

    session = _make_active_session("s1")
    repo = FakeSessionRepo(session)
    stt = FakeSTT()
    buffer_manager = FakeBufferManager()
    use_case = ProcessAudioUseCase(session_repo=repo, stt=stt, buffer_manager=buffer_manager)

    async def run():
        return await use_case.finalize_stream("s1")

    utterances = asyncio.run(run())
    assert utterances == []
