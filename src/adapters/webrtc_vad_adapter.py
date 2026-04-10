"""WebRTCVADAdapter — VoiceActivityDetectorPort backed by WebRTC VAD."""

import logging
from typing import Dict

import webrtcvad

from src.domain.entities.audio_chunk import AudioChunk
from src.ports.voice_activity_detector_port import VoiceActivity, VoiceActivityDetectorPort

logger = logging.getLogger(__name__)


class WebRTCVADAdapter(VoiceActivityDetectorPort):
    """
    Implements VoiceActivityDetectorPort using WebRTC Voice Activity Detector.

    WebRTC VAD is battle-tested (used in Chrome/Firefox) with:
    - Low latency (< 1ms per chunk)
    - Configurable sensitivity (0-3)
    - Support for 8kHz, 16kHz, 32kHz sample rates
    - Mono channel, PCM16LE encoding

    Business Rule: Processes audio in 10ms, 20ms, or 30ms frames.
    For real-time telephony, 20ms frames are recommended (320 bytes @ 16kHz).
    """

    # Valid WebRTC VAD sample rates
    _VALID_SAMPLE_RATES = {8000, 16000, 32000}

    # Valid frame durations in milliseconds
    _VALID_FRAME_DURATIONS_MS = {10, 20, 30}

    def __init__(self, sensitivity: int = 2) -> None:
        """
        Initialize WebRTC VAD adapter.

        Args:
            sensitivity: VAD sensitivity level (0-3, default 2)
                        0 = least aggressive, 3 = most aggressive

        Raises:
            ValueError: If sensitivity is not in range [0-3]
        """
        if not 0 <= sensitivity <= 3:
            raise ValueError(f"Sensitivity must be in range [0-3], got {sensitivity}")

        self._vad = webrtcvad.Vad(sensitivity)
        self._sensitivity = sensitivity

        # Track per-stream state (for reset functionality)
        self._stream_states: Dict[str, dict] = {}

        logger.info(f"WebRTC VAD initialized with sensitivity={sensitivity}")

    def detect_speech(self, chunk: AudioChunk) -> VoiceActivity:
        """
        Detect voice activity using WebRTC VAD.

        This implementation will split larger audio chunks into valid
        10/20/30ms frames and run VAD per-frame. If any frame contains
        speech, the chunk is considered SPEECH.
        """
        if not self.is_compatible_format(chunk):
            raise ValueError(
                f"Incompatible audio format for WebRTC VAD: "
                f"sample_rate={chunk.audio_format.sample_rate}, "
                f"encoding={chunk.audio_format.encoding}, "
                f"channels={chunk.audio_format.channels}"
            )

        # Validate frame duration
        duration_ms = chunk.duration_seconds * 1000
        if not any(abs(duration_ms - valid_dur) < 1 for valid_dur in self._VALID_FRAME_DURATIONS_MS):
            logger.debug(
                f"WebRTC VAD prefers frame durations of {self._VALID_FRAME_DURATIONS_MS}ms, "
                f"got {duration_ms:.1f}ms"
            )

        sample_rate = chunk.audio_format.sample_rate
        bytes_per_sample = 2  # PCM16LE

        # Choose a frame duration supported by WebRTC VAD (prefer 20ms)
        frame_ms = 20
        frame_bytes = int(sample_rate * (frame_ms / 1000.0) * bytes_per_sample)

        if frame_bytes <= 0:
            logger.error("Computed non-positive frame size for VAD")
            return VoiceActivity.UNKNOWN

        data = chunk.audio_data

        try:
            speech_found = False
            # Iterate over frames; pad the last frame if necessary
            for i in range(0, len(data), frame_bytes):
                frame = data[i : i + frame_bytes]
                if len(frame) < frame_bytes:
                    # pad with zeros to required size (webrtcvad expects exact frame size)
                    frame = frame + (b"\x00" * (frame_bytes - len(frame)))

                is_speech = self._vad.is_speech(frame, sample_rate)
                if is_speech:
                    speech_found = True
                    break

            result = VoiceActivity.SPEECH if speech_found else VoiceActivity.SILENCE

            logger.debug(
                f"VAD detected {result.value} for chunk seq={chunk.sequence_number} "
                f"({chunk.size_bytes} bytes, {duration_ms:.1f}ms, frame_ms={frame_ms})"
            )

            return result

        except Exception as exc:
            logger.error(f"WebRTC VAD error: {exc}", exc_info=True)
            return VoiceActivity.UNKNOWN

    def set_sensitivity(self, level: int) -> None:
        """
        Set VAD sensitivity level.

        Args:
            level: Sensitivity (0 = least aggressive, 3 = most aggressive)

        Raises:
            ValueError: If level not in [0-3]

        Business Rule:
        - 0: Only very clear speech (fewest false positives)
        - 1: Normal speech detection
        - 2: More sensitive (recommended for telephony with background noise)
        - 3: Most sensitive (may trigger on ambient noise)
        """
        if not 0 <= level <= 3:
            raise ValueError(f"Sensitivity level must be in [0-3], got {level}")

        self._vad.set_mode(level)
        self._sensitivity = level

        logger.info(f"WebRTC VAD sensitivity updated to {level}")

    def reset(self, stream_id: str) -> None:
        """
        Reset VAD state for a stream.

        Args:
            stream_id: Stream identifier to reset

        Business Rule: WebRTC VAD is stateless per-frame, but we track
        stream-level state for potential future extensions (e.g., smoothing).
        """
        if stream_id in self._stream_states:
            del self._stream_states[stream_id]
            logger.debug(f"Reset VAD state for stream {stream_id}")

    def is_compatible_format(self, chunk: AudioChunk) -> bool:
        """
        Check if audio format is compatible with WebRTC VAD.

        Args:
            chunk: Audio chunk to validate

        Returns:
            True if compatible, False otherwise

        Business Rule: WebRTC VAD requires:
        - Sample rate: 8000, 16000, or 32000 Hz
        - Encoding: PCM16LE (16-bit linear PCM, little-endian)
        - Channels: 1 (mono)
        """
        audio_format = chunk.audio_format

        # Check sample rate
        if audio_format.sample_rate not in self._VALID_SAMPLE_RATES:
            logger.warning(
                f"Incompatible sample rate: {audio_format.sample_rate} Hz. "
                f"WebRTC VAD requires one of {self._VALID_SAMPLE_RATES}"
            )
            return False

        # Check encoding (must be PCM16LE)
        if audio_format.encoding.upper() != "PCM16LE":
            logger.warning(
                f"Incompatible encoding: {audio_format.encoding}. "
                f"WebRTC VAD requires PCM16LE"
            )
            return False

        # Check channels (must be mono)
        if audio_format.channels != 1:
            logger.warning(
                f"Incompatible channel count: {audio_format.channels}. "
                f"WebRTC VAD requires mono (1 channel)"
            )
            return False

        return True

    @property
    def sensitivity(self) -> int:
        """Get current sensitivity level."""
        return self._sensitivity
