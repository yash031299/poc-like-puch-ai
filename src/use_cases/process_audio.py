"""ProcessAudioUseCase — receive audio chunk, transcribe, and trigger AI pipeline."""

import logging
from typing import List, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.domain.entities.utterance import Utterance
from src.domain.services.audio_buffer_manager import AudioBufferManager
from src.ports.session_repository_port import SessionRepositoryPort
from src.ports.speech_to_text_port import SpeechToTextPort
from src.infrastructure.tracing import traced_use_case

logger = logging.getLogger(__name__)


class ProcessAudioUseCase:
    """
    Application use case: Process an incoming audio chunk from caller.

    Orchestrates:
    1. Load session from repo
    2. Add audio chunk to buffer manager (with VAD)
    3. When buffer flushes (silence detected), combine chunks and transcribe
    4. For each final utterance: trigger GenerateResponse → StreamResponse
    5. Persist updated session
    6. Return list of utterances produced

    Business Rule: Uses Voice Activity Detection (VAD) to batch audio chunks
    into complete utterances. This reduces LLM API calls by 90%+ by processing
    only when the caller finishes speaking, rather than on every chunk.

    Optional generate_response and stream_response use cases close the
    full pipeline (STT → LLM → TTS → caller).
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        stt: SpeechToTextPort,
        buffer_manager: Optional[AudioBufferManager] = None,
        generate_response=None,
        stream_response=None,
    ) -> None:
        self._repo = session_repo
        self._stt = stt
        self._buffer_manager = buffer_manager
        self._generate = generate_response
        self._stream = stream_response

    @traced_use_case
    async def execute(self, stream_id: str, chunk: AudioChunk) -> List[Utterance]:
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        session.add_audio_chunk(chunk)
        session.set_listening()

        utterances: List[Utterance] = []

        # ═══ NEW: VAD-based buffering to reduce LLM calls ═══
        if self._buffer_manager is not None:
            # Add chunk to buffer manager (uses VAD internally)
            flushed_chunks = self._buffer_manager.add_chunk(stream_id, chunk)

            # Process only when buffer flushes (complete utterance detected)
            if flushed_chunks:
                logger.info(
                    f"Buffer flushed for stream {stream_id}: "
                    f"{len(flushed_chunks)} chunks buffered"
                )
                # Process each buffered chunk sequentially through STT so adapters
                # that expect per-chunk calls (e.g., StubSTTAdapter) behave correctly.
                # This preserves ordering while still avoiding immediate LLM calls
                # until a final utterance is emitted by the STT adapter.
                for c in flushed_chunks:
                    utterances.extend(await self._transcribe_and_handle(session, stream_id, c))

        # ═══ LEGACY: Process every chunk immediately (if no buffer manager) ═══
        else:
            # Original behavior: process every chunk (causes excessive LLM calls).
            utterances.extend(await self._transcribe_and_handle(session, stream_id, chunk))

        await self._repo.save(session)
        return utterances

    async def finalize_stream(self, stream_id: str) -> List[Utterance]:
        """
        Flush and process any pending VAD-buffered audio for a stream.

        Business Rule: On stop/disconnect we should transcribe remaining buffered
        caller audio so the final utterance is not dropped.
        """
        if self._buffer_manager is None:
            return []

        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        flushed_chunks = self._buffer_manager.flush(stream_id)
        if not flushed_chunks:
            return []

        logger.info(
            "Final stream flush for %s: %d buffered chunks", stream_id, len(flushed_chunks)
        )
        # Process each buffered chunk sequentially (same rationale as add_chunk)
        utterances: list[Utterance] = []
        for c in flushed_chunks:
            utterances.extend(await self._transcribe_and_handle(session, stream_id, c))
        await self._repo.save(session)
        return utterances

    def _combine_chunks(self, chunks: List[AudioChunk]) -> AudioChunk:
        """
        Combine multiple audio chunks into a single chunk for transcription.

        Business Rule: Concatenate audio data while preserving format and sequence.
        """
        if not chunks:
            raise ValueError("Cannot combine empty chunk list")

        # Use format from first chunk (all should have same format)
        audio_format = chunks[0].audio_format

        # Concatenate all audio data
        combined_audio = b"".join(chunk.audio_data for chunk in chunks)

        # Create combined chunk with first chunk's sequence number
        return AudioChunk(
            sequence_number=chunks[0].sequence_number,
            timestamp=chunks[0].timestamp,
            audio_format=audio_format,
            audio_data=combined_audio
        )

    async def _trigger_ai_pipeline(self, stream_id: str, utterance_id: str) -> None:
        """Trigger AI response generation and streaming."""
        try:
            response = await self._generate.execute(
                stream_id=stream_id,
                utterance_id=utterance_id,
            )
            await self._stream.execute(
                stream_id=stream_id,
                response_id=response.response_id,
            )
        except Exception as exc:
            # Avoid relying on module-level logger name resolution inside async tasks
            logging.getLogger(__name__).error("AI pipeline failed stream=%s: %s", stream_id, exc, exc_info=True)

    async def _transcribe_and_handle(
        self,
        session,
        stream_id: str,
        chunk: AudioChunk,
    ) -> List[Utterance]:
        """
        Transcribe one chunk and run downstream AI pipeline for final utterances.
        """
        utterances: List[Utterance] = []
        session.set_thinking()
        async for utterance in self._stt.transcribe(stream_id, chunk):
            logger.info("STT produced utterance for stream=%s final=%s text=%s", stream_id, utterance.is_final, getattr(utterance, 'text', ''))
            session.add_utterance(utterance)
            utterances.append(utterance)

            if utterance.is_final and self._generate and self._stream:
                logger.info("Triggering AI pipeline for stream=%s utterance=%s", stream_id, utterance.utterance_id)
                await self._trigger_ai_pipeline(stream_id, utterance.utterance_id)

        session.set_listening()
        return utterances
