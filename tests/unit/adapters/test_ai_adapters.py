"""Tests for AI adapters using Fakes — no real API calls."""

import asyncio
import pytest
from datetime import datetime, timezone


# ── GeminiLLMAdapter ─────────────────────────────────────────────────────────

def test_gemini_adapter_implements_llm_port() -> None:
    """Adapter satisfies LanguageModelPort interface."""
    from src.adapters.gemini_llm_adapter import GeminiLLMAdapter
    from src.ports.language_model_port import LanguageModelPort
    import inspect

    assert issubclass(GeminiLLMAdapter, LanguageModelPort)
    assert hasattr(GeminiLLMAdapter, "generate")


def test_gemini_adapter_with_fake_client() -> None:
    """Adapter yields tokens from SDK response chunks using a fake client."""
    from src.adapters.gemini_llm_adapter import GeminiLLMAdapter
    from src.domain.entities.utterance import Utterance

    # Fake the new google-genai SDK client
    class FakeChunk:
        def __init__(self, text): self.text = text

    class FakeStream:
        def __iter__(self):
            return iter([FakeChunk("Hello "), FakeChunk("there!"), FakeChunk("")])

    class FakeModels:
        def generate_content_stream(self, *args, **kwargs): return FakeStream()

    class FakeClient:
        models = FakeModels()

    adapter = GeminiLLMAdapter.__new__(GeminiLLMAdapter)
    adapter._client = FakeClient()
    adapter._model_name = "gemini-2.0-flash"

    utt = Utterance("How are you?", 0.95, True, datetime.now(timezone.utc))

    async def run():
        tokens = []
        async for token in adapter.generate("s1", utt, []):
            tokens.append(token)
        return tokens

    tokens = asyncio.run(run())
    assert "Hello " in tokens
    assert "there!" in tokens
    assert "" not in tokens  # empty chunks filtered


# ── GoogleSTTAdapter ──────────────────────────────────────────────────────────

def test_stt_adapter_implements_port() -> None:
    from src.adapters.google_stt_adapter import GoogleSTTAdapter
    from src.ports.speech_to_text_port import SpeechToTextPort

    assert issubclass(GoogleSTTAdapter, SpeechToTextPort)


def test_stt_adapter_with_fake_client() -> None:
    """Adapter yields Utterances from fake SDK response."""
    from src.adapters.google_stt_adapter import GoogleSTTAdapter
    from src.domain.entities.audio_chunk import AudioChunk
    from src.domain.value_objects.audio_format import AudioFormat

    class FakeAlternative:
        transcript = "Hello there"
        confidence = 0.92

    class FakeResult:
        alternatives = [FakeAlternative()]

    class FakeResponse:
        results = [FakeResult()]

    class FakeSTTClient:
        def recognize(self, config, audio): return FakeResponse()

    adapter = GoogleSTTAdapter.__new__(GoogleSTTAdapter)
    adapter._client = FakeSTTClient()
    adapter._language_code = "en-US"

    fmt = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
    chunk = AudioChunk(1, datetime.now(timezone.utc), fmt, bytes(3200))

    async def run():
        utterances = []
        async for utt in adapter.transcribe("s1", chunk):
            utterances.append(utt)
        return utterances

    utterances = asyncio.run(run())
    assert len(utterances) == 1
    assert utterances[0].text == "Hello there"
    assert abs(utterances[0].confidence - 0.92) < 0.01
    assert utterances[0].is_final is True


# ── GoogleTTSAdapter ──────────────────────────────────────────────────────────

def test_tts_adapter_implements_port() -> None:
    from src.adapters.google_tts_adapter import GoogleTTSAdapter
    from src.ports.text_to_speech_port import TextToSpeechPort

    assert issubclass(GoogleTTSAdapter, TextToSpeechPort)


def test_tts_adapter_chunks_audio_correctly() -> None:
    """Adapter splits synthesized audio into 3200-byte segments."""
    from src.adapters.google_tts_adapter import GoogleTTSAdapter
    from src.domain.entities.ai_response import AIResponse

    class FakeTTSResponse:
        audio_content = bytes(9600)  # 3 segments of 3200 bytes

    class FakeTTSClient:
        def synthesize_speech(self, input, voice, audio_config):
            return FakeTTSResponse()

    adapter = GoogleTTSAdapter.__new__(GoogleTTSAdapter)
    from src.domain.value_objects.audio_format import AudioFormat
    adapter._client = FakeTTSClient()
    adapter._language_code = "en-US"
    adapter._voice_name = "en-US-Neural2-F"
    adapter._sample_rate = 16000
    adapter._audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    resp = AIResponse("utt-1", datetime.now(timezone.utc))
    resp.append_text("Hello!")
    resp.complete()

    async def run():
        segs = []
        async for seg in adapter.synthesize("s1", resp):
            segs.append(seg)
        return segs

    segs = asyncio.run(run())
    assert len(segs) == 3
    assert all(seg.size_bytes == 3200 for seg in segs)
    assert all(seg.size_bytes % 320 == 0 for seg in segs)
    assert segs[-1].is_last is True
    assert segs[0].is_last is False


def test_tts_adapter_pads_last_chunk_to_320_multiple() -> None:
    """Partial last chunk is zero-padded to next multiple of 320."""
    from src.adapters.google_tts_adapter import GoogleTTSAdapter
    from src.domain.entities.ai_response import AIResponse
    from src.domain.value_objects.audio_format import AudioFormat

    # 3200 + 100 bytes → last chunk padded to 320
    class FakeTTSResponse:
        audio_content = bytes(3300)

    class FakeTTSClient:
        def synthesize_speech(self, **kwargs): return FakeTTSResponse()
        def synthesize_speech(self, input, voice, audio_config): return FakeTTSResponse()

    adapter = GoogleTTSAdapter.__new__(GoogleTTSAdapter)
    adapter._client = FakeTTSClient()
    adapter._language_code = "en-US"
    adapter._voice_name = "en-US-Neural2-F"
    adapter._sample_rate = 16000
    adapter._audio_format = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)

    resp = AIResponse("utt-1", datetime.now(timezone.utc))
    resp.append_text("Hi!")
    resp.complete()

    async def run():
        segs = []
        async for seg in adapter.synthesize("s1", resp):
            segs.append(seg)
        return segs

    segs = asyncio.run(run())
    # All segments must be multiples of 320
    for seg in segs:
        assert seg.size_bytes % 320 == 0
    assert segs[-1].is_last is True
