"""
Performance and memory-layout tests for hot-path domain entities.

These tests verify that __slots__ is correctly applied (no __dict__),
and that batch entity creation stays within latency targets.
"""

import time
from datetime import datetime

import pytest

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat


_FMT = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)
_NOW = datetime.utcnow()
_PCM = b"\x00\x01" * 160  # 320 bytes — minimum Exotel chunk


# ── __slots__ ─────────────────────────────────────────────────────────────────

class TestSlots:
    """Verify __slots__ is set — no __dict__ overhead on hot entities."""

    def test_audio_chunk_no_dict(self):
        chunk = AudioChunk(1, _NOW, _FMT, _PCM)
        assert not hasattr(chunk, "__dict__"), "AudioChunk must use __slots__"

    def test_speech_segment_no_dict(self):
        seg = SpeechSegment("resp-1", 0, _PCM, _FMT, is_last=True, timestamp=_NOW)
        assert not hasattr(seg, "__dict__"), "SpeechSegment must use __slots__"

    def test_utterance_no_dict(self):
        utt = Utterance("hello", confidence=0.9, is_final=True, timestamp=_NOW)
        assert not hasattr(utt, "__dict__"), "Utterance must use __slots__"

    def test_audio_chunk_slots_contents(self):
        """Verify the exact slot names match expected private attrs."""
        expected = {"_sequence_number", "_timestamp", "_audio_format", "_audio_data"}
        assert set(AudioChunk.__slots__) == expected

    def test_speech_segment_slots_contents(self):
        expected = {
            "_response_id", "_position", "_audio_data",
            "_audio_format", "_is_last", "_timestamp",
        }
        assert set(SpeechSegment.__slots__) == expected

    def test_utterance_slots_contents(self):
        expected = {"_utterance_id", "_text", "_confidence", "_is_final", "_timestamp"}
        assert set(Utterance.__slots__) == expected


# ── Bulk creation speed ───────────────────────────────────────────────────────

class TestBulkCreation:
    """
    Create N entities and assert total wall time is below a generous budget.

    These are not micro-benchmarks — they catch catastrophic regressions
    (e.g., accidentally copying large buffers in __init__).
    """

    N = 1_000  # 1 k entities — representative of a busy call

    def test_audio_chunk_bulk_creation(self):
        start = time.perf_counter()
        for i in range(self.N):
            AudioChunk(i + 1, _NOW, _FMT, _PCM)
        elapsed_ms = (time.perf_counter() - start) * 1000
        # Very generous: 1000 chunks < 500ms (anything faster is fine)
        assert elapsed_ms < 500, f"AudioChunk creation too slow: {elapsed_ms:.1f}ms for {self.N}"

    def test_utterance_bulk_creation(self):
        start = time.perf_counter()
        for i in range(self.N):
            Utterance(f"word {i}", confidence=0.9, is_final=True, timestamp=_NOW)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Utterance creation too slow: {elapsed_ms:.1f}ms for {self.N}"

    def test_speech_segment_bulk_creation(self):
        start = time.perf_counter()
        for i in range(self.N):
            SpeechSegment("resp-1", i, _PCM, _FMT, is_last=(i == self.N - 1), timestamp=_NOW)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"SpeechSegment creation too slow: {elapsed_ms:.1f}ms for {self.N}"


# ── Audio chunk chunking math ─────────────────────────────────────────────────

class TestChunkingMath:
    """Verify 320-byte alignment helpers used in TTS pipeline."""

    def test_chunk_size_multiple_of_320(self):
        """Exotel requires chunks to be multiples of 320 bytes."""
        chunk = AudioChunk(1, _NOW, _FMT, _PCM)
        assert chunk.size_bytes % 320 == 0

    def test_duration_calculation_8khz_mono(self):
        """320 bytes at 8000 Hz mono PCM16LE = 20ms."""
        chunk = AudioChunk(1, _NOW, _FMT, _PCM)
        # 320 bytes / (2 bytes/sample * 1 channel) = 160 samples
        # 160 samples / 8000 Hz = 0.02s (20ms)
        assert abs(chunk.duration_seconds - 0.02) < 1e-6

    def test_duration_calculation_16khz_mono(self):
        """3200 bytes at 16000 Hz mono PCM16LE = 100ms."""
        fmt_16k = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        big_pcm = b"\x00\x01" * 1600  # 3200 bytes
        chunk = AudioChunk(1, _NOW, fmt_16k, big_pcm)
        assert abs(chunk.duration_seconds - 0.1) < 1e-6
