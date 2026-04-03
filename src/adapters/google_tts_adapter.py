"""GoogleTTSAdapter — TextToSpeechPort backed by Google Cloud Text-to-Speech."""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from google.cloud import texttospeech

from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.text_to_speech_port import TextToSpeechPort

# Exotel streams expect PCM16LE — LINEAR16 in Google nomenclature
_AUDIO_ENCODING = texttospeech.AudioEncoding.LINEAR16

# Segment size: 3200 bytes = 100ms at 16kHz PCM16LE (multiple of 320 bytes)
_CHUNK_BYTES = 3200


class GoogleTTSAdapter(TextToSpeechPort):
    """
    Implements TextToSpeechPort using Google Cloud Text-to-Speech.

    Synthesizes full audio then chunks it into SpeechSegments of
    _CHUNK_BYTES each, matching Exotel's expected multiples-of-320 bytes.
    """

    def __init__(
        self,
        language_code: str = "en-US",
        voice_name: str = "en-US-Neural2-F",
        sample_rate: int = 16000,
    ) -> None:
        self._client = texttospeech.TextToSpeechClient()
        self._language_code = language_code
        self._voice_name = voice_name
        self._sample_rate = sample_rate
        self._audio_format = AudioFormat(
            sample_rate=sample_rate, encoding="PCM16LE", channels=1
        )

    async def synthesize(
        self, stream_id: str, response: AIResponse
    ) -> AsyncIterator[SpeechSegment]:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, self._synthesize_sync, response.text)

        # Chunk audio into multiples of 320 bytes
        segments = self._chunk_audio(response.response_id, audio_bytes)
        for segment in segments:
            yield segment

    def _synthesize_sync(self, text: str) -> bytes:
        """Synchronous Google TTS call (runs in thread pool)."""
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=self._language_code,
            name=self._voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=_AUDIO_ENCODING,
            sample_rate_hertz=self._sample_rate,
        )
        response = self._client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content

    def _chunk_audio(self, response_id: str, audio_bytes: bytes) -> list[SpeechSegment]:
        """
        Split raw PCM16LE bytes into fixed-size SpeechSegments.

        Business Rule: Chunks must be multiples of 320 bytes.
        Pad the final chunk with silence (zero bytes) if needed.
        """
        # Ensure total length is multiple of 320
        remainder = len(audio_bytes) % 320
        if remainder:
            audio_bytes += b"\x00" * (320 - remainder)

        segments = []
        position = 0
        offset = 0
        total = len(audio_bytes)

        while offset < total:
            chunk = audio_bytes[offset : offset + _CHUNK_BYTES]
            # Pad last chunk if needed
            if len(chunk) < _CHUNK_BYTES:
                chunk = chunk + b"\x00" * (_CHUNK_BYTES - len(chunk))

            is_last = (offset + _CHUNK_BYTES) >= total
            segments.append(
                SpeechSegment(
                    response_id=response_id,
                    position=position,
                    audio_data=chunk,
                    audio_format=self._audio_format,
                    is_last=is_last,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            position += 1
            offset += _CHUNK_BYTES

        # Ensure last segment has is_last=True
        if segments:
            last = segments[-1]
            if not last.is_last:
                segments[-1] = SpeechSegment(
                    response_id=last.response_id,
                    position=last.position,
                    audio_data=last.audio_data,
                    audio_format=last.audio_format,
                    is_last=True,
                    timestamp=last.timestamp,
                )

        return segments
