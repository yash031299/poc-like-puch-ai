"""NoiseFloorLearner — Learns adaptive noise floor from first utterance.

Implements Phase 3D.2 Adaptive Noise Floor Learning:
- Tracks first 500ms of audio (silence baseline)
- Computes: mean RMS + std dev of "quiet" periods
- Sets dynamic threshold = baseline_mean + 2*std_dev
- State: learning / learned (binary)
- Per-stream (one learner per stream_sid)

This reduces false positives (loud phone background) and false negatives
(quiet speakers) by adapting to the actual environment noise level.

Architecture:
- Accumulates audio frames during learning phase
- Computes RMS energy for each frame
- Calculates mean and std dev of frame energies
- Produces learned threshold = mean + 2*std_dev
- Falls back to -40dB if learning fails
"""

import logging
import struct
import math
from typing import List, Optional
from src.infrastructure.audio_analyzer import AudioAnalyzer

logger = logging.getLogger(__name__)


class NoiseFloorLearner:
    """Learns adaptive noise floor from first utterance audio."""

    # Default fallback if learning fails
    DEFAULT_FALLBACK_FLOOR_DB = -40.0
    
    # Learning configuration
    DEFAULT_LEARNING_DURATION_MS = 500
    
    # Frame duration (20ms is standard for audio processing)
    FRAME_DURATION_MS = 20

    def __init__(
        self,
        stream_sid: str,
        learning_duration_ms: int = DEFAULT_LEARNING_DURATION_MS,
    ) -> None:
        """
        Initialize a NoiseFloorLearner for a specific stream.

        Args:
            stream_sid: Unique stream identifier for per-stream learning
            learning_duration_ms: Duration to collect baseline audio (default: 500ms)
        """
        self._stream_sid = stream_sid
        self._learning_duration_ms = learning_duration_ms
        
        # Learning state
        self._is_learning = True  # Initially in learning phase
        self._learned_floor_db: Optional[float] = None
        
        # Accumulated audio frames during learning
        self._frame_energies: List[float] = []
        self._total_frames_collected = 0
        
        # Calculate target number of frames for learning duration
        # Assuming standard 16kHz, 20ms frames = 320 bytes per frame
        self._target_frames = max(1, learning_duration_ms // self.FRAME_DURATION_MS)
        
        logger.info(
            f"NoiseFloorLearner initialized: stream_sid={stream_sid}, "
            f"learning_duration={learning_duration_ms}ms, target_frames={self._target_frames}"
        )

    @property
    def stream_sid(self) -> str:
        """Get the stream identifier for this learner."""
        return self._stream_sid

    @property
    def is_learning(self) -> bool:
        """Check if currently in learning phase."""
        return self._is_learning

    @property
    def is_learned(self) -> bool:
        """Check if learning is complete."""
        return not self._is_learning

    def process_audio_chunk(self, chunk: bytes) -> Optional[float]:
        """
        Process audio chunk during learning phase.

        Accumulates frame energies and returns learned floor when complete.

        Args:
            chunk: Raw PCM16LE audio bytes (typically 20-100ms)

        Returns:
            Learned noise floor in dB if learning just completed, None otherwise

        Business Rule:
        - During learning phase: accumulate frame energies
        - When target duration reached: compute mean + 2*std_dev
        - Transition to learned state
        - Subsequent calls return None (learning complete)
        """
        if not self._is_learning:
            return None  # Already learned, ignore further audio

        if len(chunk) == 0:
            return None  # Empty chunk, skip

        # Parse PCM16LE frames from chunk
        try:
            samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
        except struct.error:
            logger.warning(f"Cannot parse audio data (length {len(chunk)} bytes)")
            return None

        # Compute energy for this chunk
        energy_db = self._compute_chunk_energy_db(chunk)
        self._frame_energies.append(energy_db)
        self._total_frames_collected += 1

        # Check if we've collected enough frames for learning
        if self._total_frames_collected >= self._target_frames:
            return self._finalize_learning()

        return None

    def _compute_chunk_energy_db(self, chunk: bytes) -> float:
        """
        Compute RMS energy of a chunk in dB.

        Args:
            chunk: PCM16LE audio bytes

        Returns:
            Energy in dB (same scale as AudioAnalyzer)
        """
        if len(chunk) == 0:
            return float('-inf')

        try:
            samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
        except struct.error:
            return float('-inf')

        if len(samples) == 0:
            return float('-inf')

        # Calculate RMS
        sum_of_squares = sum(s ** 2 for s in samples)
        rms = math.sqrt(sum_of_squares / len(samples))

        # Convert to dB using same reference as AudioAnalyzer
        epsilon = 1e-10
        rms_db = 20.0 * math.log10(
            max(rms, epsilon) / (1.0 * 32768.0)  # Reference = 1.0 Pa, max int16 = 32768
        )

        return rms_db

    def _finalize_learning(self) -> float:
        """
        Complete learning phase and compute adaptive threshold.

        Computes:
        - Mean of frame energies
        - Std dev of frame energies
        - Threshold = mean + 2*std_dev

        Returns:
            Learned noise floor threshold in dB
        """
        self._is_learning = False

        if not self._frame_energies:
            # No frames collected, use default
            self._learned_floor_db = self.DEFAULT_FALLBACK_FLOOR_DB
            logger.warning(
                f"NoiseFloorLearner: No frames collected for stream {self._stream_sid}, "
                f"using default floor {self._learned_floor_db}dB"
            )
            return self._learned_floor_db

        # Filter out infinities (empty frames)
        valid_energies = [e for e in self._frame_energies if e != float('-inf')]

        if not valid_energies:
            # All frames were empty, use default
            self._learned_floor_db = self.DEFAULT_FALLBACK_FLOOR_DB
            logger.warning(
                f"NoiseFloorLearner: No valid frames for stream {self._stream_sid}, "
                f"using default floor {self._learned_floor_db}dB"
            )
            return self._learned_floor_db

        # Compute mean and std dev
        mean_energy = sum(valid_energies) / len(valid_energies)
        variance = sum((e - mean_energy) ** 2 for e in valid_energies) / len(valid_energies)
        std_dev = math.sqrt(variance)

        # Threshold = mean + 2*std_dev
        # This means we detect speech that's 2 std devs above the baseline
        self._learned_floor_db = mean_energy + (2.0 * std_dev)

        logger.info(
            f"NoiseFloorLearner: Learning complete for stream {self._stream_sid}. "
            f"Frames: {len(valid_energies)}, Mean: {mean_energy:.1f}dB, "
            f"StdDev: {std_dev:.1f}dB, Threshold: {self._learned_floor_db:.1f}dB"
        )

        return self._learned_floor_db

    def get_noise_floor(self) -> float:
        """
        Get the learned noise floor threshold.

        Returns:
            Learned floor in dB if learning is complete,
            fallback (-40dB) if learning failed,
            default (-40dB) if learning not yet started
        """
        if self._learned_floor_db is not None:
            return self._learned_floor_db
        
        # Learning not yet complete, return default
        return self.DEFAULT_FALLBACK_FLOOR_DB

    def get_learning_progress(self) -> float:
        """
        Get learning progress as percentage (0.0 to 1.0).

        Returns:
            Progress: 0.0 = not started, 1.0 = complete
        """
        if not self._is_learning:
            return 1.0
        
        if self._target_frames <= 0:
            return 1.0
        
        progress = min(1.0, self._total_frames_collected / self._target_frames)
        return progress

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        state = "learned" if self.is_learned else "learning"
        floor = self._learned_floor_db if self._learned_floor_db is not None else "N/A"
        return (
            f"NoiseFloorLearner(stream_sid={self._stream_sid}, state={state}, "
            f"floor={floor}dB, progress={self.get_learning_progress():.1%})"
        )
