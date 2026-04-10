"""InterruptDetector — Detects user interruption during AI response streaming.

Detects when a user speaks (via audio energy detection) while the AI is
responding (during SPEAKING state). Used by StreamingGenerateResponseUseCase
to check if response should be cancelled.

Architecture:
- Reuses AudioAnalyzer from Phase 3A for RMS energy calculation
- Phase 3D.2: Supports adaptive noise floor learning
- Monitors for audio energy > noise floor during SPEAKING state
- Sets interrupt flag on ConversationSession atomically
- Works with bidirectional streaming (user can interrupt mid-response)

Latency Target: <100ms from speech detection to interrupt flag set
"""

import logging
from typing import Optional

from src.infrastructure.audio_analyzer import AudioAnalyzer
from src.domain.aggregates.conversation_session import ConversationSession

logger = logging.getLogger(__name__)


class InterruptDetector:
    """Detects user interruption based on audio energy analysis."""

    def __init__(self, analyzer: Optional[AudioAnalyzer] = None, noise_floor_db: float = -40.0):
        """
        Initialize interrupt detector.

        Args:
            analyzer: AudioAnalyzer instance (can be None for testing)
            noise_floor_db: Energy threshold in dB for speech detection (fallback default)
                          Default: -40dB (from AudioAnalyzer.DEFAULT_NOISE_FLOOR_DB)
        """
        self._analyzer = analyzer or AudioAnalyzer(noise_floor_db=noise_floor_db)
        self._default_noise_floor_db = noise_floor_db
        logger.info(f"InterruptDetector initialized with noise_floor={noise_floor_db}dB")

    def detect_interrupt(self, session: ConversationSession, audio_chunk: bytes) -> bool:
        """
        Detect if user is interrupting during AI response.

        Business Logic:
        1. Only check during SPEAKING state (AI is talking)
        2. Use learned noise floor if available, else default
        3. Analyze audio energy of incoming chunk
        4. If energy > noise floor, user is likely speaking
        5. Mark session as interrupted and return True
        6. Return False if not in SPEAKING state or audio is silence

        Phase 3D.2: Supports adaptive noise floor learning
        - If session.is_noise_floor_learned(): use learned threshold
        - Else: use default threshold

        Args:
            session: ConversationSession with interaction state and noise floor
            audio_chunk: Raw audio bytes (PCM16LE format)

        Returns:
            True if interrupt was detected and flagged on session, False otherwise

        Latency: <10ms (direct RMS computation + energy comparison)
        """
        # Rule 1: Only check during SPEAKING state
        if session.interaction_state != "speaking":
            return False

        # Rule 2: Already interrupted in this cycle
        if session.is_interrupted():
            return False

        # Rule 3: Analyze audio energy
        if len(audio_chunk) == 0:
            return False

        # Phase 3D.2: Use learned noise floor if available
        noise_floor_db = session.get_noise_floor()
        
        # Temporarily set analyzer to use the appropriate threshold
        old_threshold = self._analyzer.get_noise_floor_db()
        try:
            self._analyzer.set_noise_floor_db(noise_floor_db)
            is_speech = self._analyzer.is_above_noise_floor(audio_chunk)
        finally:
            # Restore original analyzer threshold
            self._analyzer.set_noise_floor_db(old_threshold)

        if not is_speech:
            return False

        # Rule 4: Mark as interrupted
        session.mark_interrupted()
        
        logger.info(
            f"Interrupt detected: stream={session.stream_identifier}, "
            f"state={session.interaction_state}, user_speaking=True, "
            f"noise_floor={noise_floor_db:.1f}dB"
        )

        return True

    def get_noise_floor_db(self) -> float:
        """Get default configured noise floor threshold in dB."""
        return self._default_noise_floor_db

