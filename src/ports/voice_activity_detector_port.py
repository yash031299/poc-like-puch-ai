"""VoiceActivityDetectorPort — driven port for voice activity detection."""

from abc import ABC, abstractmethod
from enum import Enum

from src.domain.entities.audio_chunk import AudioChunk


class VoiceActivity(Enum):
    """
    Voice activity states returned by VAD detection.
    
    Business Rule: VAD must distinguish between speech and silence/noise
    to enable intelligent audio buffering and reduce unnecessary processing.
    """
    SPEECH = "speech"      # Active speech detected
    SILENCE = "silence"    # Silence or background noise only
    UNKNOWN = "unknown"    # Unable to determine (e.g., ambiguous signal)


class VoiceActivityDetectorPort(ABC):
    """
    Driven port for detecting voice activity in audio streams.
    
    Business Rule: VAD enables intelligent buffering by distinguishing
    between active speech and silence. This reduces LLM API calls by
    batching complete utterances rather than processing every audio chunk.
    
    Implementations may use WebRTC VAD, Silero VAD, energy-based detection, etc.
    """

    @abstractmethod
    def detect_speech(self, chunk: AudioChunk) -> VoiceActivity:
        """
        Detect voice activity in an audio chunk.
        
        Args:
            chunk: Audio chunk to analyze
            
        Returns:
            VoiceActivity enum indicating speech/silence/unknown
            
        Raises:
            ValueError: If audio format is incompatible with VAD
            
        Business Rule: Must process chunks in < 10ms to maintain
        real-time performance (1-2ms latency target).
        """

    @abstractmethod
    def set_sensitivity(self, level: int) -> None:
        """
        Set VAD sensitivity level.
        
        Args:
            level: Sensitivity level (0 = least aggressive, 3 = most aggressive)
                  - 0: Only very clear speech detected (fewest false positives)
                  - 1: Normal sensitivity (balanced)
                  - 2: More sensitive (recommended for telephony)
                  - 3: Most sensitive (may have false positives in noise)
                  
        Raises:
            ValueError: If level is not in valid range [0-3]
            
        Business Rule: Higher sensitivity detects more speech but may
        trigger on background noise. Lower sensitivity is more conservative.
        """

    @abstractmethod
    def reset(self, stream_id: str) -> None:
        """
        Reset VAD internal state for a stream.
        
        Args:
            stream_id: Stream identifier to reset state for
            
        Business Rule: Must be called when a conversation ends or
        when Exotel sends 'clear' event to avoid state leakage between calls.
        """

    @abstractmethod
    def is_compatible_format(self, chunk: AudioChunk) -> bool:
        """
        Check if audio format is compatible with this VAD implementation.
        
        Args:
            chunk: Audio chunk to check format compatibility
            
        Returns:
            True if format is supported, False otherwise
            
        Business Rule: VAD implementations have specific requirements
        (e.g., WebRTC VAD requires 8kHz, 16kHz, or 32kHz sample rates,
        mono channel, PCM16LE encoding).
        """
