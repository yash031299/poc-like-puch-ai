"""Tests for zero-credential stub adapters (StubSTT, StubLLM, StubTTS)."""

import asyncio
import struct
from datetime import datetime, timezone

import pytest

from src.adapters.stub_stt_adapter import StubSTTAdapter
from src.adapters.stub_llm_adapter import StubLLMAdapter
from src.adapters.stub_tts_adapter import StubTTSAdapter, _CHUNK_BYTES
from src.domain.entities.ai_response import AIResponse
from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat


# ── Helpers ───────────────────────────────────────────────────────────────────

_FMT = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
_NOW = datetime.now(timezone.utc)
_PCM = b"\x00\x01" * 160  # 320 bytes


def _chunk(seq: int) -> AudioChunk:
    return AudioChunk(seq, _NOW, _FMT, _PCM)


def _utterance(text: str = "hello") -> Utterance:
    return Utterance(text, confidence=0.9, is_final=True, timestamp=_NOW)


def _ai_response(text: str = "sure thing") -> AIResponse:
    return AIResponse(utterance_id="u1", timestamp=_NOW)


# ── StubSTTAdapter ────────────────────────────────────────────────────────────

class TestStubSTTAdapter:
    def test_implements_port(self):
        from src.ports.speech_to_text_port import SpeechToTextPort
        assert isinstance(StubSTTAdapter(), SpeechToTextPort)

    def test_returns_nothing_before_trigger(self):
        """Chunks 1 and 2 of 3 should produce no utterances."""
        stt = StubSTTAdapter(trigger_every=3)

        async def run():
            results = []
            async for u in stt.transcribe("s1", _chunk(1)):
                results.append(u)
            async for u in stt.transcribe("s1", _chunk(2)):
                results.append(u)
            return results

        results = asyncio.run(run())
        assert results == []

    def test_returns_utterance_at_trigger(self):
        """3rd chunk should produce a final utterance."""
        stt = StubSTTAdapter(transcript="hello world", trigger_every=3)

        async def run():
            results = []
            for i in range(1, 4):
                async for u in stt.transcribe("s1", _chunk(i)):
                    results.append(u)
            return results

        results = asyncio.run(run())
        assert len(results) == 1
        assert results[0].text == "hello world"
        assert results[0].is_final is True
        assert results[0].confidence == 0.99

    def test_triggers_again_after_second_cycle(self):
        """Should trigger at chunk 3 and again at chunk 6."""
        stt = StubSTTAdapter(trigger_every=3)

        async def run():
            count = 0
            for i in range(1, 7):
                async for _ in stt.transcribe("s1", _chunk(i)):
                    count += 1
            return count

        assert asyncio.run(run()) == 2

    def test_streams_are_isolated(self):
        """Two different stream IDs have independent counters."""
        stt = StubSTTAdapter(trigger_every=2)

        async def run():
            r1, r2 = [], []
            async for u in stt.transcribe("s1", _chunk(1)):
                r1.append(u)
            async for u in stt.transcribe("s2", _chunk(1)):
                r2.append(u)
            # s1 got chunk 1 only → no trigger yet
            # s2 got chunk 1 only → no trigger yet
            async for u in stt.transcribe("s1", _chunk(2)):
                r1.append(u)  # s1 chunk 2 → trigger
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert len(r1) == 1
        assert len(r2) == 0

    def test_custom_trigger_every_1(self):
        """trigger_every=1 means every single chunk yields a transcript."""
        stt = StubSTTAdapter(trigger_every=1)

        async def run():
            results = []
            for i in range(1, 4):
                async for u in stt.transcribe("s1", _chunk(i)):
                    results.append(u)
            return results

        results = asyncio.run(run())
        assert len(results) == 3


# ── StubLLMAdapter ────────────────────────────────────────────────────────────

class TestStubLLMAdapter:
    def test_implements_port(self):
        from src.ports.language_model_port import LanguageModelPort
        assert isinstance(StubLLMAdapter(), LanguageModelPort)

    def test_yields_words_of_response(self):
        """Should yield each word of the configured response."""
        llm = StubLLMAdapter(response="hello world test")

        async def run():
            tokens = []
            async for token in llm.generate("s1", _utterance(), []):
                tokens.append(token)
            return tokens

        tokens = asyncio.run(run())
        full = "".join(tokens).strip()
        assert full == "hello world test"

    def test_reassembled_response_equals_original(self):
        """Joining streamed tokens must reproduce original response."""
        response_text = "I am working correctly. How can I help?"
        llm = StubLLMAdapter(response=response_text)

        async def run():
            parts = []
            async for t in llm.generate("s1", _utterance("hi"), []):
                parts.append(t)
            return "".join(parts).strip()

        assert asyncio.run(run()) == response_text

    def test_increments_call_count(self):
        llm = StubLLMAdapter()

        async def run():
            async for _ in llm.generate("s1", _utterance(), []):
                pass
            async for _ in llm.generate("s1", _utterance(), []):
                pass

        asyncio.run(run())
        assert llm.call_count == 2

    def test_tracks_last_utterance_text(self):
        llm = StubLLMAdapter()

        async def run():
            async for _ in llm.generate("s1", _utterance("what time is it"), []):
                pass

        asyncio.run(run())
        assert llm.last_utterance_text == "what time is it"

    def test_context_ignored(self):
        """Context list is accepted but doesn't affect output."""
        llm = StubLLMAdapter(response="fixed")

        async def run():
            parts = []
            async for t in llm.generate("s1", _utterance(), ["ctx1", "ctx2", "ctx3"]):
                parts.append(t)
            return "".join(parts).strip()

        assert asyncio.run(run()) == "fixed"


# ── StubTTSAdapter ────────────────────────────────────────────────────────────

class TestStubTTSAdapter:
    def test_implements_port(self):
        from src.ports.text_to_speech_port import TextToSpeechPort
        assert isinstance(StubTTSAdapter(), TextToSpeechPort)

    def test_yields_at_least_one_segment(self):
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=100)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        assert len(segs) >= 1

    def test_last_segment_is_last(self):
        """The final SpeechSegment must have is_last=True."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        assert segs[-1].is_last is True
        for seg in segs[:-1]:
            assert seg.is_last is False

    def test_chunk_sizes_are_multiples_of_320(self):
        """Exotel requires all chunks to be multiples of 320 bytes."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        for seg in segs:
            assert seg.size_bytes % 320 == 0, (
                f"Segment {seg.position} size {seg.size_bytes} is not a multiple of 320"
            )

    def test_chunk_size_equals_3200(self):
        """Each chunk should be 3200 bytes (100ms at 8kHz = Exotel recommended minimum)."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        for seg in segs:
            assert seg.size_bytes == _CHUNK_BYTES

    def test_audio_is_valid_pcm16le(self):
        """
        Audio bytes must be parseable as int16 little-endian samples
        — i.e., the total byte count is a multiple of 2.
        """
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)

        async def run():
            data = b""
            async for s in tts.synthesize("s1", _ai_response()):
                data += s.audio_data
            return data

        data = asyncio.run(run())
        assert len(data) % 2 == 0, "PCM16LE data must have even byte count"
        # Should be parseable as int16 samples
        n_samples = len(data) // 2
        samples = struct.unpack(f"<{n_samples}h", data)
        assert len(samples) == n_samples

    def test_audio_format_matches_sample_rate(self):
        """SpeechSegment's audio_format.sample_rate must match constructor arg."""
        tts = StubTTSAdapter(sample_rate=16000, duration_ms=200)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        for seg in segs:
            assert seg.audio_format.sample_rate == 16000
            assert seg.audio_format.encoding == "PCM16LE"
            assert seg.audio_format.channels == 1

    def test_response_id_propagated(self):
        """SpeechSegments must carry the AI response's response_id."""
        resp = _ai_response("check id")
        tts = StubTTSAdapter()

        async def run():
            segs = []
            async for s in tts.synthesize("s1", resp):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        for seg in segs:
            assert seg.response_id == resp.response_id

    def test_positions_are_sequential(self):
        """Positions must be 0, 1, 2, … in order."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)

        async def run():
            segs = []
            async for s in tts.synthesize("s1", _ai_response()):
                segs.append(s)
            return segs

        segs = asyncio.run(run())
        for i, seg in enumerate(segs):
            assert seg.position == i

    def test_increments_call_count(self):
        tts = StubTTSAdapter()

        async def run():
            for _ in range(3):
                async for _ in tts.synthesize("s1", _ai_response()):
                    pass

        asyncio.run(run())
        assert tts.call_count == 3

    def test_pregenerated_audio_is_non_silent(self):
        """Sine wave audio must have non-zero samples (not all zeros like silence)."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=100)

        async def run():
            data = b""
            async for s in tts.synthesize("s1", _ai_response()):
                data += s.audio_data
            return data

        data = asyncio.run(run())
        n = len(data) // 2
        samples = struct.unpack(f"<{n}h", data)
        # At least some samples should be non-zero
        assert any(s != 0 for s in samples)
