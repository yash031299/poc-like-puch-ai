"""StreamingGenerateResponseUseCase — parallel LLM token generation and TTS synthesis."""

import asyncio
import logging
from typing import TYPE_CHECKING

from src.domain.entities.ai_response import AIResponse
from src.domain.entities.utterance import Utterance
from src.domain.services.token_ring_buffer import TokenRingBuffer
from src.ports.caller_audio_port import CallerAudioPort
from src.ports.language_model_port import LanguageModelPort
from src.ports.session_repository_port import SessionRepositoryPort
from src.ports.text_to_speech_port import TextToSpeechPort

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StreamingGenerateResponseUseCase:
    """
    Generate AI response with parallel LLM token generation and TTS synthesis.

    This use case coordinates two concurrent tasks:
    1. LLM Producer: Generates tokens via language model, puts them into TokenRingBuffer
    2. TTS Consumer: Reads tokens from buffer, synthesizes partial phrases, sends audio

    Enables first audio byte to be heard within 500-800ms instead of waiting
    5-8 seconds for complete LLM response.

    Flow:
        LLM generates tokens → TokenRingBuffer ↔ TTS synthesizes phrases → Audio to caller
                                 [concurrent]

    Backpressure: If TTS is slower than LLM, the ring buffer will fill up and
    LLM will wait until space is available. This prevents memory overflow.
    """

    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        llm: LanguageModelPort,
        tts: TextToSpeechPort,
        audio_out: CallerAudioPort,
    ) -> None:
        self._repo = session_repo
        self._llm = llm
        self._tts = tts
        self._audio_out = audio_out

    async def execute(
        self,
        stream_id: str,
        utterance_id: str,
    ) -> AIResponse:
        """
        Execute streaming response generation.

        Loads the utterance, creates a TokenRingBuffer, starts both LLM and TTS
        concurrently, waits for both to complete, then returns the complete AIResponse.

        Args:
            stream_id: The call stream identifier
            utterance_id: The utterance to generate response for

        Returns:
            Complete AIResponse (populated from all synthesized tokens)

        Raises:
            ValueError: If stream or utterance not found
        """
        session = await self._repo.get(stream_id)
        if session is None:
            raise ValueError(f"No active session for stream {stream_id}")

        utterance = next(
            (u for u in session.utterances if u.utterance_id == utterance_id), None
        )
        if utterance is None:
            raise ValueError(f"Utterance {utterance_id} not found in session {stream_id}")

        # Create the AI response entity
        ai_response = AIResponse(text="", response_id=f"{stream_id}_{utterance_id}")

        logger.info(
            "Starting streaming response for stream=%s utterance=%s",
            stream_id,
            utterance_id,
        )
        session.set_speaking()

        # Create token ring buffer (256 token capacity)
        token_buffer = TokenRingBuffer(capacity=256)

        try:
            # Run LLM producer and TTS consumer concurrently
            llm_task = asyncio.create_task(
                self._llm_producer(stream_id, utterance, ai_response, token_buffer)
            )
            tts_task = asyncio.create_task(
                self._tts_consumer(stream_id, ai_response.response_id, token_buffer, audio_out=self._audio_out)
            )

            # Wait for both to complete
            await asyncio.gather(llm_task, tts_task)

            logger.info(
                "Finished streaming response for stream=%s utterance=%s text_length=%d",
                stream_id,
                utterance_id,
                len(ai_response.text),
            )

            ai_response.mark_delivered()
            session.set_listening()
            session.add_ai_response(ai_response)
            await self._repo.save(session)

            return ai_response

        except Exception as e:
            logger.error(
                "Error in streaming response for stream=%s: %s",
                stream_id,
                e,
                exc_info=True,
            )
            session.set_listening()
            await self._repo.save(session)
            raise

    async def _llm_producer(
        self,
        stream_id: str,
        utterance: Utterance,
        ai_response: AIResponse,
        token_buffer: TokenRingBuffer,
    ) -> None:
        """
        LLM producer task: generate tokens and put into ring buffer.

        Consumes tokens from LLM, accumulates them into ai_response.text,
        and puts each token into the buffer for TTS to consume.

        Args:
            stream_id: Call identifier
            utterance: User utterance to respond to
            ai_response: Response entity to accumulate text into
            token_buffer: Buffer to receive tokens
        """
        try:
            async for token in self._llm.generate(stream_id, utterance):
                # Accumulate token into final response text
                ai_response._text += token  # type: ignore
                # Put token into buffer for TTS to consume
                await token_buffer.put(token)
                logger.debug("LLM produced token: %s (buffer size: %d)", repr(token[:20]), token_buffer.size())
        except Exception as e:
            logger.error("LLM producer error: %s", e, exc_info=True)
        finally:
            # Signal TTS that no more tokens will arrive
            await token_buffer.complete()
            logger.debug("LLM producer completed")

    async def _tts_consumer(
        self,
        stream_id: str,
        response_id: str,
        token_buffer: TokenRingBuffer,
        audio_out: CallerAudioPort,
    ) -> None:
        """
        TTS consumer task: synthesize tokens and send audio segments.

        Reads tokens from buffer, batches them into phrases, synthesizes,
        and sends segments to caller.

        Args:
            stream_id: Call identifier
            response_id: Response identifier
            token_buffer: Buffer to consume tokens from
            audio_out: Port to send audio segments to
        """
        try:
            async for segment in self._tts.synthesize_stream(stream_id, response_id, token_buffer):
                logger.debug(
                    "TTS produced segment: pos=%d bytes=%d is_last=%s",
                    segment.position,
                    len(segment.audio_data),
                    segment.is_last,
                )
                await audio_out.send_segment(stream_id, segment)
        except Exception as e:
            logger.error("TTS consumer error: %s", e, exc_info=True)
        finally:
            logger.debug("TTS consumer completed")
