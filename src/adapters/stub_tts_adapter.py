"""
StubTTSAdapter — zero-credential Text-to-Speech for local development and testing.

Returns real, valid PCM16LE audio (440 Hz sine wave) so the full pipeline
path — TTS → ExotelCallerAudioAdapter → WebSocket → caller — exercises real
base64 encoding, chunk splitting, and wire transmission.

No Google Cloud credentials required.

Usage (server.py DEV_MODE):
    tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)
"""

import math
import struct
from datetime import datetime, timezone
from typing import AsyncIterator

from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.text_to_speech_port import TextToSpeechPort

# Exotel requirements: multiples of 320 bytes; 3200 bytes = 100ms recommended minimum
_CHUNK_BYTES = 3200
_FREQ_HZ = 440  # A4 — audible tone so you can hear the stub is working


def _generate_sine_wave(
    frequency: float,
    duration_ms: int,
    sample_rate: int,
    amplitude: float = 0.3,
) -> bytes:
    """
    Generate PCM16LE mono sine wave of given frequency and duration.

    The output length is padded up to the nearest multiple of _CHUNK_BYTES
    so that chunking never produces an undersized final segment.
    """
    num_samples = int(sample_rate * duration_ms / 1000)
    samples: list[int] = []

    for i in range(num_samples):
        value = amplitude * math.sin(2 * math.pi * frequency * i / sample_rate)
        # PCM16 range: -32768 to 32767
        sample = int(value * 32767)
        samples.append(max(-32768, min(32767, sample)))

    raw = struct.pack(f"<{num_samples}h", *samples)  # little-endian int16

    # Pad to multiple of _CHUNK_BYTES
    remainder = len(raw) % _CHUNK_BYTES
    if remainder:
        raw += b"\x00" * (_CHUNK_BYTES - remainder)

    return raw


class StubTTSAdapter(TextToSpeechPort):
    """
    Deterministic TTS implementation for local testing.

    Synthesises a 440 Hz sine wave of `duration_ms` length and splits it
    into SpeechSegments of _CHUNK_BYTES each.  The AI response text is
    ignored — every call returns the same audio tone.

    This exercises the full downstream path:
        StubTTS → SpeechSegment → ExotelCallerAudioAdapter → WebSocket send

    No external dependencies — safe to use without GOOGLE_APPLICATION_CREDENTIALS.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        duration_ms: int = 400,  # 400ms → 2 chunks of 3200 bytes each at 8kHz
    ) -> None:
        self._sample_rate = sample_rate
        self._duration_ms = duration_ms
        self._audio_format = AudioFormat(
            sample_rate=sample_rate, encoding="PCM16LE", channels=1
        )
        # Pre-generate audio once (it never changes)
        self._pcm_data = _generate_sine_wave(_FREQ_HZ, duration_ms, sample_rate)
        # Track calls for test assertions
        self.call_count: int = 0

    async def synthesize(
        self, stream_id: str, response: AIResponse
    ) -> AsyncIterator[SpeechSegment]:
        self.call_count += 1
        data = self._pcm_data
        total_chunks = max(1, len(data) // _CHUNK_BYTES)
        now = datetime.now(timezone.utc)

        for position in range(total_chunks):
            start = position * _CHUNK_BYTES
            chunk = data[start : start + _CHUNK_BYTES]
            is_last = position == total_chunks - 1
            yield SpeechSegment(
                response_id=response.response_id,
                position=position,
                audio_data=chunk,
                audio_format=self._audio_format,
                is_last=is_last,
                timestamp=now,
            )
