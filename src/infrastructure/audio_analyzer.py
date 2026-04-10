"""AudioAnalyzer — Compute RMS energy and noise floor detection for audio frames.

Enables intelligent audio buffering by:
- Computing RMS (Root Mean Square) energy for each 20ms frame
- Determining noise floor threshold (-40dB)
- Distinguishing between speech and background noise
- Supporting noise suppression at the frame level

Used by EnhancedAudioBufferManager to improve VAD accuracy.
"""

import logging
import math
import struct
from typing import Tuple

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """Analyzes audio frame energy for noise floor detection."""

    # Reference pressure for dB calculation (1 Pa RMS)
    _REFERENCE_PRESSURE = 1.0
    
    # Minimum dB threshold for speech detection
    # -40dB is aggressive but tolerates quiet speech
    # -30dB is lenient (more background noise slips through)
    DEFAULT_NOISE_FLOOR_DB = -40.0

    def __init__(self, noise_floor_db: float = DEFAULT_NOISE_FLOOR_DB):
        """
        Initialize audio analyzer.

        Args:
            noise_floor_db: Energy threshold in dB below which audio is silence
                          Default: -40dB (good balance for telephony)
                          
        Business Rule:
        - -50dB: Very aggressive, may miss quiet speakers
        - -40dB: Recommended for telephony (default)
        - -30dB: Lenient, passes more background noise
        - -20dB: Very lenient, likely too permissive
        """
        if noise_floor_db > 0:
            raise ValueError(f"Noise floor must be <= 0dB, got {noise_floor_db}")
        
        self._noise_floor_db = noise_floor_db
        logger.info(f"AudioAnalyzer initialized: noise_floor={noise_floor_db}dB")

    def compute_rms_energy_db(self, audio_data: bytes) -> float:
        """
        Compute RMS (Root Mean Square) energy of audio frame in dB.

        Args:
            audio_data: PCM16LE (signed 16-bit little-endian) audio bytes

        Returns:
            Energy in dB (0dB = max amplitude, negative = quieter)

        Business Rule:
        - RMS captures average energy (not peak)
        - dB scale: 20 * log10(RMS / reference)
        - -40dB ≈ quiet speech, background noise
        - 0dB = clipping/very loud
        
        Example:
        - Silent frame: -80dB
        - Quiet speech: -35dB
        - Normal speech: -20 to -10dB
        - Loud speech: -5 to 0dB
        """
        if len(audio_data) == 0:
            return float('-inf')  # Empty = silence

        # Parse PCM16LE (signed 16-bit little-endian)
        try:
            samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)
        except struct.error:
            logger.warning(f"Cannot parse audio data (length {len(audio_data)} bytes)")
            return float('-inf')

        # Calculate RMS
        if len(samples) == 0:
            return float('-inf')

        sum_of_squares = sum(s ** 2 for s in samples)
        rms = math.sqrt(sum_of_squares / len(samples))

        # Convert to dB (with small epsilon to avoid log(0))
        epsilon = 1e-10
        rms_db = 20.0 * math.log10(max(rms, epsilon) / (self._REFERENCE_PRESSURE * 32768.0))

        return rms_db

    def is_above_noise_floor(self, audio_data: bytes) -> bool:
        """
        Determine if audio frame is above noise floor (likely speech).

        Args:
            audio_data: PCM16LE audio bytes

        Returns:
            True if energy > noise_floor_db, False otherwise

        Business Rule:
        - Above threshold → likely speech
        - Below threshold → likely silence/background noise
        """
        energy_db = self.compute_rms_energy_db(audio_data)
        is_speech = energy_db > self._noise_floor_db

        logger.debug(
            f"Audio frame: {energy_db:.1f}dB vs threshold {self._noise_floor_db}dB "
            f"→ {'SPEECH' if is_speech else 'SILENCE'}"
        )

        return is_speech

    def get_noise_floor_db(self) -> float:
        """Get current noise floor threshold in dB."""
        return self._noise_floor_db

    def set_noise_floor_db(self, noise_floor_db: float) -> None:
        """
        Update noise floor threshold.

        Args:
            noise_floor_db: New threshold in dB

        Raises:
            ValueError: If threshold > 0dB
        """
        if noise_floor_db > 0:
            raise ValueError(f"Noise floor must be <= 0dB, got {noise_floor_db}")
        
        old = self._noise_floor_db
        self._noise_floor_db = noise_floor_db
        logger.info(f"Noise floor updated: {old}dB → {noise_floor_db}dB")

    @staticmethod
    def estimate_dynamic_noise_floor(frame_energies: list[float], percentile: int = 20) -> float:
        """
        Estimate noise floor from frame energies using percentile method.

        Args:
            frame_energies: List of energy values (in dB) from recent frames
            percentile: Which percentile to use as noise floor (default 20th)
                       Lower percentile = lower threshold = more sensitive

        Returns:
            Estimated noise floor in dB

        Business Rule:
        - Collect energies from ~1-2 seconds of audio
        - Noise floor ≈ 20th percentile (quietest 20% of frames)
        - This adapts to environment (loud office vs quiet room)
        - Update threshold periodically as background noise changes

        Example:
        If frame energies are: [-50, -35, -30, -28, -20, -15]
        20th percentile ≈ -45dB (noise floor)
        Speech would need to be > -45dB
        """
        if not frame_energies:
            return AudioAnalyzer.DEFAULT_NOISE_FLOOR_DB

        # Remove infinities (empty frames)
        valid_energies = [e for e in frame_energies if e != float('-inf')]
        
        if not valid_energies:
            return AudioAnalyzer.DEFAULT_NOISE_FLOOR_DB

        # Sort and find percentile
        valid_energies.sort()
        # Calculate index: percentile position in sorted list
        # For 20th percentile of 100 items, we want item #20 (0-indexed: 19)
        # Formula: index = percentile * len / 100, clamped to valid range
        index = min(len(valid_energies) - 1, max(0, int(len(valid_energies) * percentile / 100.0)))
        estimated_floor = valid_energies[index]

        logger.debug(
            f"Estimated noise floor from {len(valid_energies)} frames: {estimated_floor:.1f}dB "
            f"({percentile}th percentile)"
        )

        return estimated_floor
