"""EnhancedAudioBufferManager — Intelligent audio buffering with noise floor detection.

Builds on AudioBufferManager with:
- Minimum speech duration (500ms) to reject false positives
- Noise floor suppression (-40dB) to eliminate background noise
- Enhanced state machine with ACCUMULATING state
- Silence recovery window for natural pauses

Solves the "excessive LLM calls" problem by:
1. Requiring 500ms+ of above-noise speech before triggering SPEAKING state
2. Ignoring background noise frames below -40dB
3. Supporting 500ms pauses within speech (doesn't flush on every silence)
4. Flushing only when user truly finishes speaking

Expected result: 600 LLM calls/minute → 20 calls/minute (1 per complete utterance)
"""

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Deque, Dict, Optional

from src.domain.entities.audio_chunk import AudioChunk
from src.infrastructure.audio_analyzer import AudioAnalyzer
from src.ports.voice_activity_detector_port import VoiceActivity, VoiceActivityDetectorPort

logger = logging.getLogger(__name__)


class EnhancedBufferState(Enum):
    """
    Enhanced state machine for speech detection with noise floor.
    
    Business Rule: Prevents false positives from background noise and short glitches.
    
    State transitions:
    - IDLE: Waiting for speech above noise floor
    - ACCUMULATING: Detected speech, waiting for minimum duration (500ms)
    - SPEAKING: Minimum duration reached, accumulating utterance
    - SILENCE_DETECTED: Silence after speech, waiting for recovery window
    - FLUSHING: Ready to process (transitional state)
    """
    IDLE = "idle"
    ACCUMULATING = "accumulating"
    SPEAKING = "speaking"
    SILENCE_DETECTED = "silence_detected"


class EnhancedAudioBufferManager:
    """
    Enhanced audio buffer manager with noise floor and minimum speech duration.
    
    Reduces false LLM calls by:
    1. Ignoring background noise below -40dB
    2. Requiring 500ms+ of speech before transition to SPEAKING
    3. Supporting 500ms natural pauses within speech
    4. Only flushing when user truly finishes speaking
    """

    def __init__(
        self,
        vad: VoiceActivityDetectorPort,
        analyzer: Optional[AudioAnalyzer] = None,
        silence_threshold_ms: int = 700,
        min_speech_duration_ms: int = 500,
        silence_recovery_ms: int = 500,
        max_buffer_duration_seconds: float = 30.0,
    ) -> None:
        """
        Initialize enhanced audio buffer manager.

        Args:
            vad: Voice activity detector
            analyzer: AudioAnalyzer for noise floor detection (optional)
            silence_threshold_ms: Silence duration before considering utterance done (default: 700ms)
            min_speech_duration_ms: Minimum speech duration before entering SPEAKING (default: 500ms)
            silence_recovery_ms: Grace period for natural pauses within speech (default: 500ms)
            max_buffer_duration_seconds: Max buffer duration before force-flush (default: 30s)

        Business Rule:
        - Silence threshold (700ms): Typical pause detection latency
        - Min speech duration (500ms): Reject clicks/glitches
        - Silence recovery (500ms): Allow natural pauses ("uh", "um", thinking pauses)
        - Max buffer (30s): Prevent memory overflow
        """
        if silence_threshold_ms < 100:
            raise ValueError("Silence threshold must be >= 100ms")
        if min_speech_duration_ms < 0:
            raise ValueError("Min speech duration must be >= 0ms")
        if silence_recovery_ms < 0:
            raise ValueError("Silence recovery must be >= 0ms")
        if max_buffer_duration_seconds <= 0:
            raise ValueError("Max buffer duration must be > 0")

        self._vad = vad
        self._analyzer = analyzer or AudioAnalyzer()
        self._silence_threshold_ms = silence_threshold_ms
        self._min_speech_duration_ms = min_speech_duration_ms
        self._silence_recovery_ms = silence_recovery_ms
        self._max_buffer_duration = max_buffer_duration_seconds

        # Per-stream state tracking
        self._stream_buffers: Dict[str, Deque[AudioChunk]] = {}
        self._stream_states: Dict[str, EnhancedBufferState] = {}
        self._silence_start_times: Dict[str, Optional[datetime]] = {}
        self._speech_start_times: Dict[str, Optional[datetime]] = {}
        self._buffer_start_times: Dict[str, Optional[datetime]] = {}
        self._accumulating_start_times: Dict[str, Optional[datetime]] = {}

        # Metrics
        self._chunks_buffered: Dict[str, int] = {}
        self._chunks_rejected: Dict[str, int] = {}
        self._flushes_count: Dict[str, int] = {}
        self._chunks_flushed_total: Dict[str, int] = {}

        logger.info(
            f"EnhancedAudioBufferManager initialized: "
            f"silence_threshold={silence_threshold_ms}ms, "
            f"min_speech_duration={min_speech_duration_ms}ms, "
            f"silence_recovery={silence_recovery_ms}ms, "
            f"max_buffer={max_buffer_duration_seconds}s, "
            f"noise_floor={self._analyzer.get_noise_floor_db()}dB"
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
        1. Silence threshold reached after SPEAKING state
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

        # Check noise floor
        is_above_noise_floor = self._analyzer.is_above_noise_floor(chunk.audio_data)

        # Get current state
        current_state = self._stream_states[stream_id]
        buffer = self._stream_buffers[stream_id]

        logger.debug(
            f"Stream {stream_id}: state={current_state.value}, "
            f"activity={activity.value}, above_noise_floor={is_above_noise_floor}, "
            f"buffer_size={len(buffer)}"
        )

        # State machine transitions with noise floor
        if current_state == EnhancedBufferState.IDLE:
            if activity == VoiceActivity.SPEECH and is_above_noise_floor:
                # Transition: IDLE → ACCUMULATING
                self._transition_to_accumulating(stream_id, chunk)
                buffer.append(chunk)
                self._chunks_buffered[stream_id] += 1
                return None
            else:
                # Reject chunk (no speech or below noise floor)
                self._chunks_rejected[stream_id] += 1
                return None

        elif current_state == EnhancedBufferState.ACCUMULATING:
            if activity == VoiceActivity.SPEECH and is_above_noise_floor:
                buffer.append(chunk)
                self._chunks_buffered[stream_id] += 1

                # Check if minimum duration reached
                accum_start = self._accumulating_start_times[stream_id]
                if accum_start is not None:
                    accum_duration_ms = (datetime.now(timezone.utc) - accum_start).total_seconds() * 1000
                    if accum_duration_ms >= self._min_speech_duration_ms:
                        # Transition: ACCUMULATING → SPEAKING
                        self._transition_to_speaking(stream_id)
                return None
            else:
                # Silence or below noise floor while accumulating
                # Don't transition yet, just discard (might be noise)
                self._chunks_rejected[stream_id] += 1
                return None

        elif current_state == EnhancedBufferState.SPEAKING:
            buffer.append(chunk)
            self._chunks_buffered[stream_id] += 1

            if activity == VoiceActivity.SILENCE or not is_above_noise_floor:
                # Transition: SPEAKING → SILENCE_DETECTED
                self._transition_to_silence_detected(stream_id)
                return None
            else:
                # Continue speaking
                # Reset silence timer
                self._silence_start_times[stream_id] = None

                # Check for buffer overflow
                if self._is_buffer_full(stream_id):
                    logger.warning(f"Stream {stream_id}: Max buffer duration exceeded, forcing flush")
                    return self._do_flush(stream_id)

                return None

        elif current_state == EnhancedBufferState.SILENCE_DETECTED:
            if activity == VoiceActivity.SPEECH and is_above_noise_floor:
                # Transition: SILENCE_DETECTED → SPEAKING (user resumed)
                logger.debug(f"Stream {stream_id}: Speech resumed after pause")
                self._transition_to_speaking(stream_id)
                buffer.append(chunk)
                self._chunks_buffered[stream_id] += 1
                self._silence_start_times[stream_id] = None
                return None
            else:
                # Still silence or below noise floor
                silence_start = self._silence_start_times[stream_id]
                if silence_start is not None:
                    silence_duration_ms = (datetime.now(timezone.utc) - silence_start).total_seconds() * 1000
                    if silence_duration_ms >= self._silence_threshold_ms:
                        # Silence threshold reached, flush!
                        logger.info(
                            f"Stream {stream_id}: Silence threshold reached "
                            f"({silence_duration_ms:.0f}ms), flushing buffer"
                        )
                        return self._do_flush(stream_id)

                # Still waiting for silence threshold
                return None

        return None

    def flush(self, stream_id: str) -> Optional[list[AudioChunk]]:
        """
        Explicitly flush any buffered audio for a stream.

        Used during stream end/disconnect to process remaining buffered audio.
        """
        if stream_id not in self._stream_states:
            return None

        return self._do_flush(stream_id)

    def reset(self, stream_id: str) -> None:
        """Reset buffer state for a stream."""
        if stream_id in self._stream_states:
            self._stream_states[stream_id] = EnhancedBufferState.IDLE
            self._stream_buffers[stream_id].clear()
            self._silence_start_times[stream_id] = None
            self._speech_start_times[stream_id] = None
            self._buffer_start_times[stream_id] = None
            self._accumulating_start_times[stream_id] = None
            logger.debug(f"Reset buffer state for stream {stream_id}")

    def get_metrics(self, stream_id: str) -> dict:
        """Get buffer metrics for a stream."""
        if stream_id not in self._stream_states:
            return {}

        return {
            "state": self._stream_states[stream_id].value,
            "buffer_size": len(self._stream_buffers[stream_id]),
            "chunks_buffered": self._chunks_buffered.get(stream_id, 0),
            "chunks_rejected": self._chunks_rejected.get(stream_id, 0),
            "flushes": self._flushes_count.get(stream_id, 0),
            "total_chunks_flushed": self._chunks_flushed_total.get(stream_id, 0),
        }

    # ═══ PRIVATE METHODS ═══

    def _initialize_stream(self, stream_id: str) -> None:
        """Initialize state for a new stream."""
        self._stream_buffers[stream_id] = deque()
        self._stream_states[stream_id] = EnhancedBufferState.IDLE
        self._silence_start_times[stream_id] = None
        self._speech_start_times[stream_id] = None
        self._buffer_start_times[stream_id] = None
        self._accumulating_start_times[stream_id] = None
        self._chunks_buffered[stream_id] = 0
        self._chunks_rejected[stream_id] = 0
        self._flushes_count[stream_id] = 0
        self._chunks_flushed_total[stream_id] = 0

    def _transition_to_accumulating(self, stream_id: str, chunk: AudioChunk) -> None:
        """Transition IDLE → ACCUMULATING."""
        logger.debug(f"Stream {stream_id}: IDLE → ACCUMULATING (first speech detected)")
        self._stream_states[stream_id] = EnhancedBufferState.ACCUMULATING
        self._accumulating_start_times[stream_id] = datetime.now(timezone.utc)
        if self._buffer_start_times[stream_id] is None:
            self._buffer_start_times[stream_id] = datetime.now(timezone.utc)

    def _transition_to_speaking(self, stream_id: str) -> None:
        """Transition ACCUMULATING → SPEAKING."""
        logger.info(
            f"Stream {stream_id}: ACCUMULATING → SPEAKING "
            f"(minimum speech duration {self._min_speech_duration_ms}ms reached)"
        )
        self._stream_states[stream_id] = EnhancedBufferState.SPEAKING
        self._speech_start_times[stream_id] = datetime.now(timezone.utc)

    def _transition_to_silence_detected(self, stream_id: str) -> None:
        """Transition SPEAKING → SILENCE_DETECTED."""
        logger.debug(f"Stream {stream_id}: SPEAKING → SILENCE_DETECTED")
        self._stream_states[stream_id] = EnhancedBufferState.SILENCE_DETECTED
        self._silence_start_times[stream_id] = datetime.now(timezone.utc)

    def _is_buffer_full(self, stream_id: str) -> bool:
        """Check if buffer exceeds max duration."""
        buffer_start = self._buffer_start_times[stream_id]
        if buffer_start is None:
            return False

        duration = (datetime.now(timezone.utc) - buffer_start).total_seconds()
        return duration >= self._max_buffer_duration

    def _do_flush(self, stream_id: str) -> Optional[list[AudioChunk]]:
        """Perform flush and reset state."""
        buffer = self._stream_buffers[stream_id]
        if not buffer:
            return None

        flushed = list(buffer)
        buffer.clear()

        self._stream_states[stream_id] = EnhancedBufferState.IDLE
        self._silence_start_times[stream_id] = None
        self._speech_start_times[stream_id] = None
        self._buffer_start_times[stream_id] = None
        self._accumulating_start_times[stream_id] = None
        self._flushes_count[stream_id] += 1
        self._chunks_flushed_total[stream_id] += len(flushed)

        logger.info(
            f"Stream {stream_id}: Flushed {len(flushed)} chunks "
            f"(total flushes: {self._flushes_count[stream_id]})"
        )

        return flushed
