"""Unit tests for CallerAudioPort — the streaming output port."""

import pytest


def test_caller_audio_port_is_abstract() -> None:
    """Test that CallerAudioPort cannot be instantiated directly."""
    from src.ports.caller_audio_port import CallerAudioPort

    with pytest.raises(TypeError):
        CallerAudioPort()  # type: ignore[abstract]


def test_caller_audio_port_defines_send_segment() -> None:
    """Test that the port declares the send_segment interface."""
    from src.ports.caller_audio_port import CallerAudioPort
    import inspect

    assert hasattr(CallerAudioPort, "send_segment")
    assert inspect.isabstract(CallerAudioPort)


def test_concrete_port_can_be_implemented() -> None:
    """Test that a fake can implement the port contract."""
    from src.ports.caller_audio_port import CallerAudioPort
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat
    from datetime import datetime, timezone

    class FakeCallerAudio(CallerAudioPort):
        def __init__(self) -> None:
            self.sent: list = []

        async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
            self.sent.append((stream_id, segment))

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    seg = SpeechSegment("resp-1", 0, bytes(3200), fmt, True, datetime.now(timezone.utc))

    fake = FakeCallerAudio()
    assert isinstance(fake, CallerAudioPort)
    assert hasattr(fake, "send_segment")


def test_fake_caller_audio_records_sent_segments() -> None:
    """Test that a fake implementation records calls for assertion in tests."""
    import asyncio
    from src.ports.caller_audio_port import CallerAudioPort
    from src.domain.entities.speech_segment import SpeechSegment
    from src.domain.value_objects.audio_format import AudioFormat
    from datetime import datetime, timezone

    class FakeCallerAudio(CallerAudioPort):
        def __init__(self) -> None:
            self.sent: list = []

        async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
            self.sent.append((stream_id, segment))

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    seg0 = SpeechSegment("resp-1", 0, bytes(3200), fmt, False, datetime.now(timezone.utc))
    seg1 = SpeechSegment("resp-1", 1, bytes(3200), fmt, True, datetime.now(timezone.utc))

    fake = FakeCallerAudio()

    async def run():
        await fake.send_segment("stream-123", seg0)
        await fake.send_segment("stream-123", seg1)

    asyncio.run(run())

    assert len(fake.sent) == 2
    assert fake.sent[0][0] == "stream-123"
    assert fake.sent[1][1].is_last is True
