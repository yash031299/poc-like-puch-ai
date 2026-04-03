"""AudioChunk entity - represents a segment of audio data from caller."""

from datetime import datetime
from typing import Optional

from src.domain.value_objects.audio_format import AudioFormat


class AudioChunk:
    """
    Entity representing a sequential chunk of audio data from caller.
    
    Business Rule: Audio chunks must be processed in sequence order
    to ensure accurate transcription. Each chunk has a sequence number
    for ordering and contains raw audio samples.
    """

    __slots__ = ("_sequence_number", "_timestamp", "_audio_format", "_audio_data")

    def __init__(
        self,
        sequence_number: int,
        timestamp: datetime,
        audio_format: AudioFormat,
        audio_data: bytes
    ) -> None:
        """
        Create an AudioChunk.
        
        Args:
            sequence_number: Sequential number for ordering (must be non-negative)
            timestamp: When the audio was recorded/received
            audio_format: Format specification (sample rate, encoding, channels)
            audio_data: Raw audio samples (must not be empty)
            
        Raises:
            ValueError: If sequence_number is negative or audio_data is empty
        """
        if sequence_number < 0:
            raise ValueError("Sequence number must be non-negative")
        
        if not audio_data:
            raise ValueError("Audio data cannot be empty")
        
        self._sequence_number = sequence_number
        self._timestamp = timestamp
        self._audio_format = audio_format
        self._audio_data = audio_data
    
    @property
    def sequence_number(self) -> int:
        """Get the sequence number for ordering."""
        return self._sequence_number
    
    @property
    def timestamp(self) -> datetime:
        """Get the timestamp when audio was recorded."""
        return self._timestamp
    
    @property
    def audio_format(self) -> AudioFormat:
        """Get the audio format specification."""
        return self._audio_format
    
    @property
    def audio_data(self) -> bytes:
        """Get the raw audio samples."""
        return self._audio_data
    
    @property
    def size_bytes(self) -> int:
        """Calculate size of audio data in bytes."""
        return len(self._audio_data)
    
    @property
    def duration_seconds(self) -> float:
        """
        Calculate duration of audio chunk in seconds.
        
        Business Rule: Duration depends on format (sample rate, channels, encoding).
        For PCM16LE: 2 bytes per sample per channel.
        """
        # PCM16LE uses 2 bytes per sample
        bytes_per_sample = 2
        
        # Calculate total samples
        total_bytes = len(self._audio_data)
        samples_per_channel = total_bytes / (bytes_per_sample * self._audio_format.channels)
        
        # Duration = samples / sample_rate
        duration = samples_per_channel / self._audio_format.sample_rate
        return duration
    
    def __eq__(self, other: object) -> bool:
        """
        Check equality based on sequence_number (entity identity).
        
        Business Rule: Two AudioChunks are the same if they have
        the same sequence number (even if data differs).
        """
        if not isinstance(other, AudioChunk):
            return False
        return self._sequence_number == other._sequence_number
    
    def __hash__(self) -> int:
        """Make AudioChunk hashable based on identity."""
        return hash(self._sequence_number)
    
    def __lt__(self, other: "AudioChunk") -> bool:
        """Compare for ordering by sequence number."""
        return self._sequence_number < other._sequence_number
    
    def __le__(self, other: "AudioChunk") -> bool:
        """Compare for ordering by sequence number."""
        return self._sequence_number <= other._sequence_number
    
    def __gt__(self, other: "AudioChunk") -> bool:
        """Compare for ordering by sequence number."""
        return self._sequence_number > other._sequence_number
    
    def __ge__(self, other: "AudioChunk") -> bool:
        """Compare for ordering by sequence number."""
        return self._sequence_number >= other._sequence_number
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"AudioChunk(seq={self._sequence_number}, "
            f"{self.size_bytes} bytes, "
            f"{self.duration_seconds:.3f}s)"
        )
