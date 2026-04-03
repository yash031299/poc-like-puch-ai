"""AudioBufferManager — domain service for intelligent audio buffering with VAD."""

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Deque, Dict, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.ports.voice_activity_detector_port import VoiceActivity, VoiceActivityDetectorPort

logger = logging.getLogger(__name__)


class BufferState(Enum):
    """
    Buffer state machine for speech detection.
    
    Business Rule: State transitions ensure we only process complete utterances:
    - IDLE → SPEAKING: First speech detected
    - SPEAKING → SILENCE_DETECTED: Silence after speech
    - SILENCE_DETECTED → IDLE: Silence threshold reached (flush buffer)
    - SILENCE_DETECTED → SPEAKING: Speech resumed (continue buffering)
    """
    IDLE = "idle"                          # No speech detected yet
    SPEAKING = "speaking"                  # Actively receiving speech
    SILENCE_DETECTED = "silence_detected"  # Silence after speech (waiting for threshold)


class AudioBufferManager:
    """
    Domain service for intelligent audio buffering using Voice Activity Detection.
    
    Business Rule: Accumulate audio chunks while user speaks, detect silence
    to identify utterance boundaries, flush complete utterances to reduce
    unnecessary STT/LLM processing.
    
    This solves the "too many LLM calls" problem by batching audio chunks
    into complete utterances rather than processing every 10-40ms chunk.
    """

    def __init__(
        self,
        vad: VoiceActivityDetectorPort,
        silence_threshold_ms: int = 700,
        max_buffer_duration_seconds: float = 30.0
    ) -> None:
        """
        Initialize AudioBufferManager.
        
        Args:
            vad: Voice activity detector for speech/silence detection
            silence_threshold_ms: Milliseconds of silence before flushing (default: 700ms)
            max_buffer_duration_seconds: Maximum buffer duration to prevent overflow (default: 30s)
            
        Business Rule:
        - Silence threshold: 500-1000ms balances responsiveness vs false positives
        - Max buffer: Protects against memory overflow during long monologues
        """
        if silence_threshold_ms < 100:
            raise ValueError("Silence threshold must be >= 100ms")
        
        if max_buffer_duration_seconds <= 0:
            raise ValueError("Max buffer duration must be > 0")
        
        self._vad = vad
        self._silence_threshold_ms = silence_threshold_ms
        self._max_buffer_duration = max_buffer_duration_seconds
        
        # Per-stream state tracking
        self._stream_buffers: Dict[str, Deque[AudioChunk]] = {}
        self._stream_states: Dict[str, BufferState] = {}
        self._silence_start_times: Dict[str, Optional[datetime]] = {}
        self._buffer_start_times: Dict[str, Optional[datetime]] = {}
        
        # Metrics
        self._chunks_buffered: Dict[str, int] = {}
        self._flushes_count: Dict[str, int] = {}
        self._chunks_flushed_total: Dict[str, int] = {}
        self._audio_seconds_flushed_total: Dict[str, float] = {}
        
        logger.info(
            f"AudioBufferManager initialized: "
            f"silence_threshold={silence_threshold_ms}ms, "
            f"max_buffer={max_buffer_duration_seconds}s"
        )

    def add_chunk(self, stream_id: str, chunk: AudioChunk) -> Optional[list[AudioChunk]]:
        """
        Add an audio chunk and determine if buffer should be flushed.
        
        Args:
            stream_id: Stream identifier
            chunk: Audio chunk to add
            
        Returns:
            List of buffered chunks if flush triggered, None otherwise
            
        Business Rule: Flush occurs when:
        1. Silence threshold reached after speech
        2. Max buffer duration exceeded (safety)
        3. Explicitly requested via flush()
        """
        # Initialize stream state if needed
        if stream_id not in self._stream_states:
            self._initialize_stream(stream_id)
        
        # Detect voice activity
        try:
            activity = self._vad.detect_speech(chunk)
        except Exception as exc:
            logger.error(f"VAD error for stream {stream_id}: {exc}")
            activity = VoiceActivity.UNKNOWN
        
        # Get current state
        current_state = self._stream_states[stream_id]
        buffer = self._stream_buffers[stream_id]
        
        logger.debug(
            f"Stream {stream_id}: state={current_state.value}, "
            f"activity={activity.value}, buffer_size={len(buffer)}"
        )
        
        # State machine transitions
        if current_state == BufferState.IDLE:
            if activity == VoiceActivity.SPEECH:
                # Transition: IDLE → SPEAKING
                self._transition_to_speaking(stream_id, chunk)
                buffer.append(chunk)
                self._chunks_buffered[stream_id] += 1
                return None
            else:
                # Still idle, discard chunk (no speech yet)
                return None
                
        elif current_state == BufferState.SPEAKING:
            buffer.append(chunk)
            self._chunks_buffered[stream_id] += 1
            
            if activity == VoiceActivity.SILENCE:
                # Transition: SPEAKING → SILENCE_DETECTED
                self._transition_to_silence_detected(stream_id)
                return None
            else:
                # Continue speaking
                # Check for buffer overflow
                if self._is_buffer_full(stream_id):
                    logger.warning(
                        f"Stream {stream_id}: Max buffer duration exceeded, forcing flush"
                    )
                    return self._flush_buffer(stream_id)
                return None
                
        elif current_state == BufferState.SILENCE_DETECTED:
            buffer.append(chunk)
            self._chunks_buffered[stream_id] += 1
            
            if activity == VoiceActivity.SPEECH:
                # Transition: SILENCE_DETECTED → SPEAKING (speech resumed)
                self._transition_back_to_speaking(stream_id)
                return None
            else:
                # Check if silence threshold reached
                if self._is_silence_threshold_reached(stream_id):
                    # Flush buffer and return to IDLE
                    return self._flush_buffer(stream_id)
                return None
        
        return None

    def flush(self, stream_id: str) -> Optional[list[AudioChunk]]:
        """
        Explicitly flush buffer for a stream.
        
        Args:
            stream_id: Stream to flush
            
        Returns:
            List of buffered chunks if any exist, None otherwise
            
        Business Rule: Called on stream end or "clear" event from Exotel
        """
        if stream_id not in self._stream_buffers:
            return None
        
        return self._flush_buffer(stream_id)

    def reset(self, stream_id: str) -> None:
        """
        Reset buffer state for a stream.
        
        Args:
            stream_id: Stream to reset
            
        Business Rule: Called on Exotel "clear" event or stream end
        """
        if stream_id in self._stream_buffers:
            del self._stream_buffers[stream_id]
        if stream_id in self._stream_states:
            del self._stream_states[stream_id]
        if stream_id in self._silence_start_times:
            del self._silence_start_times[stream_id]
        if stream_id in self._buffer_start_times:
            del self._buffer_start_times[stream_id]
        if stream_id in self._chunks_buffered:
            del self._chunks_buffered[stream_id]
        if stream_id in self._flushes_count:
            del self._flushes_count[stream_id]
        if stream_id in self._chunks_flushed_total:
            del self._chunks_flushed_total[stream_id]
        if stream_id in self._audio_seconds_flushed_total:
            del self._audio_seconds_flushed_total[stream_id]
        
        # Reset VAD state
        self._vad.reset(stream_id)
        
        logger.debug(f"Reset buffer manager for stream {stream_id}")

    def get_metrics(self, stream_id: str) -> dict:
        """Get buffer metrics for a stream."""
        return {
            "state": self._stream_states.get(stream_id, BufferState.IDLE).value,
            "chunks_buffered": self._chunks_buffered.get(stream_id, 0),
            "flushes_count": self._flushes_count.get(stream_id, 0),
            "chunks_flushed_total": self._chunks_flushed_total.get(stream_id, 0),
            "audio_seconds_flushed_total": self._audio_seconds_flushed_total.get(stream_id, 0.0),
            "buffer_size": len(self._stream_buffers.get(stream_id, [])),
        }

    # ── Private methods ────────────────────────────────────────────────────────

    def _initialize_stream(self, stream_id: str) -> None:
        """Initialize state for a new stream."""
        self._stream_buffers[stream_id] = deque()
        self._stream_states[stream_id] = BufferState.IDLE
        self._silence_start_times[stream_id] = None
        self._buffer_start_times[stream_id] = None
        self._chunks_buffered[stream_id] = 0
        self._flushes_count[stream_id] = 0
        self._chunks_flushed_total[stream_id] = 0
        self._audio_seconds_flushed_total[stream_id] = 0.0
        
        logger.debug(f"Initialized buffer for stream {stream_id}")

    def _transition_to_speaking(self, stream_id: str, chunk: AudioChunk) -> None:
        """Transition from IDLE to SPEAKING."""
        self._stream_states[stream_id] = BufferState.SPEAKING
        self._buffer_start_times[stream_id] = chunk.timestamp
        self._silence_start_times[stream_id] = None
        
        logger.debug(f"Stream {stream_id}: IDLE → SPEAKING")

    def _transition_to_silence_detected(self, stream_id: str) -> None:
        """Transition from SPEAKING to SILENCE_DETECTED."""
        self._stream_states[stream_id] = BufferState.SILENCE_DETECTED
        self._silence_start_times[stream_id] = datetime.now(timezone.utc)
        
        logger.debug(f"Stream {stream_id}: SPEAKING → SILENCE_DETECTED")

    def _transition_back_to_speaking(self, stream_id: str) -> None:
        """Transition from SILENCE_DETECTED back to SPEAKING."""
        self._stream_states[stream_id] = BufferState.SPEAKING
        self._silence_start_times[stream_id] = None
        
        logger.debug(f"Stream {stream_id}: SILENCE_DETECTED → SPEAKING (resumed)")

    def _is_silence_threshold_reached(self, stream_id: str) -> bool:
        """Check if silence duration exceeds threshold."""
        silence_start = self._silence_start_times.get(stream_id)
        if silence_start is None:
            return False
        
        silence_duration = (datetime.now(timezone.utc) - silence_start).total_seconds() * 1000
        return silence_duration >= self._silence_threshold_ms

    def _is_buffer_full(self, stream_id: str) -> bool:
        """Check if buffer duration exceeds maximum."""
        buffer_start = self._buffer_start_times.get(stream_id)
        if buffer_start is None:
            return False
        
        buffer_duration = (datetime.now(timezone.utc) - buffer_start).total_seconds()
        return buffer_duration >= self._max_buffer_duration

    def _flush_buffer(self, stream_id: str) -> Optional[list[AudioChunk]]:
        """Flush buffer and return chunks."""
        buffer = self._stream_buffers.get(stream_id)
        if not buffer or len(buffer) == 0:
            return None
        
        # Convert deque to list
        chunks = list(buffer)
        
        # Calculate total duration
        total_duration = sum(chunk.duration_seconds for chunk in chunks)
        
        # Clear buffer and reset state
        buffer.clear()
        self._stream_states[stream_id] = BufferState.IDLE
        self._silence_start_times[stream_id] = None
        self._buffer_start_times[stream_id] = None
        self._flushes_count[stream_id] += 1
        self._chunks_flushed_total[stream_id] += len(chunks)
        self._audio_seconds_flushed_total[stream_id] += total_duration
        
        logger.info(
            f"Stream {stream_id}: Flushed buffer with {len(chunks)} chunks "
            f"({total_duration:.2f}s) - flush #{self._flushes_count[stream_id]}"
        )
        
        return chunks

    @property
    def silence_threshold_ms(self) -> int:
        """Get silence threshold in milliseconds."""
        return self._silence_threshold_ms

    @property
    def max_buffer_duration_seconds(self) -> float:
        """Get maximum buffer duration in seconds."""
        return self._max_buffer_duration
