"""GoogleTTSAdapter — TextToSpeechPort backed by Google Cloud Text-to-Speech."""

import asyncio
import re
from datetime import datetime, timezone
from typing import AsyncIterator

from src.domain.entities.ai_response import AIResponse
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.audio_format import AudioFormat
from src.ports.text_to_speech_port import TextToSpeechPort

# Segment size: 3200 bytes = 100ms at 16kHz PCM16LE (multiple of 320 bytes)
_CHUNK_BYTES = 3200
# Accumulate tokens until we have ~2-3 seconds of text (50-100 tokens typical)
_TOKEN_ACCUMULATE_TARGET = 50


class GoogleTTSAdapter(TextToSpeechPort):
    """
    Implements TextToSpeechPort using Google Cloud Text-to-Speech.

    Client is lazily initialized on first use so the server starts even
    when GOOGLE_APPLICATION_CREDENTIALS is not set (fails at first real call).

    Synthesizes full audio then chunks it into SpeechSegments of
    _CHUNK_BYTES each, matching Exotel's expected multiples-of-320 bytes.
    """

    def __init__(
        self,
        language_code: str = "en-US",
        voice_name: str = "en-US-Neural2-F",
        sample_rate: int = 16000,
    ) -> None:
        self._language_code = language_code
        self._voice_name = voice_name
        self._sample_rate = sample_rate
        self._audio_format = AudioFormat(
            sample_rate=sample_rate, encoding="PCM16LE", channels=1
        )
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            from google.cloud import texttospeech
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    async def synthesize(
        self, stream_id: str, response: AIResponse
    ) -> AsyncIterator[SpeechSegment]:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(None, self._synthesize_sync, response.text)

        for segment in self._chunk_audio(response.response_id, audio_bytes):
            yield segment

    async def synthesize_stream(
        self,
        stream_id: str,
        response_id: str,
        token_buffer,  # TokenRingBuffer
    ) -> AsyncIterator[SpeechSegment]:
        """
        Synthesize from a stream of LLM tokens.

        Accumulates tokens into phrases (detected by sentence-final punctuation or
        token count), synthesizes each phrase, and yields audio segments.

        Detects phrase boundaries on:
        - Sentence-final punctuation: . ! ? ; :
        - Token accumulation reaching target (~50 tokens)
        - EOF signal from token_buffer

        Args:
            stream_id: Call identifier
            response_id: Response identifier
            token_buffer: TokenRingBuffer yielding LLM tokens

        Yields:
            SpeechSegment objects as phrases are synthesized
        """
        accumulated_text = ""
        token_count = 0
        segment_position = 0
        loop = asyncio.get_event_loop()

        while True:
            # Get next token
            token = await token_buffer.get()

            if token is None:
                # EOF: synthesize any remaining text
                if accumulated_text.strip():
                    audio_bytes = await loop.run_in_executor(
                        None, self._synthesize_sync, accumulated_text
                    )
                    for segment in self._chunk_audio(response_id, audio_bytes):
                        # Mark last segment from last phrase
                        if segment.position == len(self._chunk_audio(response_id, audio_bytes)) - 1:
                            yield SpeechSegment(
                                response_id=segment.response_id,
                                position=segment_position,
                                audio_data=segment.audio_data,
                                audio_format=segment.audio_format,
                                is_last=True,
                                timestamp=segment.timestamp,
                            )
                            segment_position += 1
                        else:
                            yield SpeechSegment(
                                response_id=segment.response_id,
                                position=segment_position,
                                audio_data=segment.audio_data,
                                audio_format=segment.audio_format,
                                is_last=False,
                                timestamp=segment.timestamp,
                            )
                            segment_position += 1
                break

            # Accumulate token
            accumulated_text += token
            token_count += 1

            # Check if we should synthesize (phrase boundary detected)
            if self._is_phrase_complete(accumulated_text, token_count):
                if accumulated_text.strip():
                    audio_bytes = await loop.run_in_executor(
                        None, self._synthesize_sync, accumulated_text
                    )
                    for segment in self._chunk_audio(response_id, audio_bytes):
                        yield SpeechSegment(
                            response_id=segment.response_id,
                            position=segment_position,
                            audio_data=segment.audio_data,
                            audio_format=segment.audio_format,
                            is_last=False,
                            timestamp=segment.timestamp,
                        )
                        segment_position += 1

                # Reset for next phrase
                accumulated_text = ""
                token_count = 0

    def _is_phrase_complete(self, text: str, token_count: int) -> bool:
        """
        Detect if accumulated text forms a complete phrase.

        Phrase boundaries:
        - Ends with sentence-final punctuation (. ! ? ; :)
        - Accumulated token_count reaches target threshold

        Args:
            text: Accumulated text
            token_count: Number of tokens accumulated

        Returns:
            True if phrase is complete and should be synthesized
        """
        # Token threshold
        if token_count >= _TOKEN_ACCUMULATE_TARGET:
            return True

        # Sentence boundary: look for sentence-final punctuation at end
        stripped = text.rstrip()
        if stripped and stripped[-1] in ".!?;:":
            # Make sure it's not a decimal point (e.g., "3.14")
            if stripped[-1] == "." and len(stripped) > 1 and stripped[-2].isdigit():
                return False
            return True

        return False

    def _synthesize_sync(self, text: str) -> bytes:
        """Synchronous Google TTS call (runs in thread pool)."""
        from google.cloud import texttospeech
        client = self._get_client()

        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=self._language_code,
            name=self._voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=self._sample_rate,
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content

    def _chunk_audio(self, response_id: str, audio_bytes: bytes) -> list[SpeechSegment]:
        """
        Split raw PCM16LE bytes into fixed-size SpeechSegments.

        Business Rule: Chunks must be multiples of 320 bytes.
        Pad the final chunk with silence (zero bytes) if needed.
        """
        remainder = len(audio_bytes) % 320
        if remainder:
            audio_bytes += b"\x00" * (320 - remainder)

        segments = []
        position = 0
        offset = 0
        total = len(audio_bytes)

        while offset < total:
            chunk = audio_bytes[offset : offset + _CHUNK_BYTES]
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

        if segments and not segments[-1].is_last:
            last = segments[-1]
            segments[-1] = SpeechSegment(
                response_id=last.response_id,
                position=last.position,
                audio_data=last.audio_data,
                audio_format=last.audio_format,
                is_last=True,
                timestamp=last.timestamp,
            )

        return segments
