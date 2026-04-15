"""Tests for GenerateResponseUseCase."""

import pytest
import asyncio
from datetime import datetime, timezone


class FakeSessionRepo:
    def __init__(self, session=None):
        self._store = {session.stream_identifier.value: session} if session else {}

    async def save(self, session): self._store[session.stream_identifier.value] = session
    async def get(self, sid): return self._store.get(sid)
    async def delete(self, sid): self._store.pop(sid, None)


class FakeLLM:
    def __init__(self, response_text: str = "Hi there!"):
        self._text = response_text

    async def generate(self, stream_id, utterance, context):
        for token in self._text.split():
            yield token + " "


class EmptyLLM:
    async def generate(self, stream_id, utterance, context):
        if False:
            yield ""


class FailingLLM:
    async def generate(self, stream_id, utterance, context):
        raise RuntimeError("503 UNAVAILABLE")
        if False:
            yield ""


def _make_session_with_utterance(stream_id="s1"):
    from src.domain.aggregates.conversation_session import ConversationSession
    from src.domain.value_objects.stream_identifier import StreamIdentifier
    from src.domain.value_objects.audio_format import AudioFormat
    from src.domain.entities.utterance import Utterance

    sess = ConversationSession.create(
        stream_identifier=StreamIdentifier(stream_id),
        caller_number="+1111111111",
        called_number="+2222222222",
        audio_format=AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1),
    )
    sess.activate()
    utt = Utterance("How are you?", 0.93, True, datetime.now(timezone.utc))
    sess.add_utterance(utt)
    return sess, utt


def test_generate_response_creates_ai_response() -> None:
    from src.use_cases.generate_response import GenerateResponseUseCase

    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    llm = FakeLLM("I am doing well today!")
    use_case = GenerateResponseUseCase(session_repo=repo, llm=llm)

    async def run():
        return await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    response = asyncio.run(run())

    assert response is not None
    assert response.utterance_id == utt.utterance_id
    assert response.state == "complete"
    assert len(response.text) > 0
    assert session.interaction_state == "listening"

    # Stored in session
    assert len(session.ai_responses) == 1


def test_generate_response_raises_if_utterance_not_found() -> None:
    from src.use_cases.generate_response import GenerateResponseUseCase

    session, _ = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    use_case = GenerateResponseUseCase(session_repo=repo, llm=FakeLLM())

    async def run():
        with pytest.raises(ValueError, match="Utterance not-found not found"):
            await use_case.execute(stream_id="s1", utterance_id="not-found")

    asyncio.run(run())


def test_generate_response_raises_on_empty_streamed_output() -> None:
    from src.use_cases.generate_response import GenerateResponseUseCase

    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    use_case = GenerateResponseUseCase(session_repo=repo, llm=EmptyLLM())

    async def run():
        with pytest.raises(ValueError, match="Cannot complete a response with no text"):
            await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    asyncio.run(run())


def test_generate_response_uses_degraded_text_when_llm_fails() -> None:
    from src.use_cases.generate_response import GenerateResponseUseCase

    session, utt = _make_session_with_utterance()
    repo = FakeSessionRepo(session)
    use_case = GenerateResponseUseCase(
        session_repo=repo,
        llm=FailingLLM(),
        degraded_response_text="I am temporarily unavailable. Please try again shortly.",
    )

    async def run():
        return await use_case.execute(stream_id="s1", utterance_id=utt.utterance_id)

    response = asyncio.run(run())
    assert "temporarily unavailable" in response.text
    assert response.state == "complete"
