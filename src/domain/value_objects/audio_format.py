"""AudioFormat value object - describes technical characteristics of audio data."""

from typing import Any


class AudioFormat:
    """
    Immutable value object describing audio format specifications.
    
    Business Rule: AudioFormat specifies how to interpret audio samples
    (sample rate, encoding, channels) and is immutable once created.
    """
    
    def __init__(self, sample_rate: int, encoding: str, channels: int) -> None:
        """
        Create a new AudioFormat.
        
        Args:
            sample_rate: Samples per second (e.g., 8000, 16000, 24000 Hz)
            encoding: Audio encoding format (e.g., "PCM16LE")
            channels: Number of audio channels (1=mono, 2=stereo)
            
        Raises:
            ValueError: If parameters are invalid
        """
        # Validate sample rate
        if sample_rate <= 0:
            raise ValueError("Sample rate must be positive")
        
        # Validate encoding
        if not encoding:
            raise ValueError("Encoding cannot be empty")
        
        # Validate channels
        if channels not in (1, 2):
            raise ValueError("Channels must be 1 (mono) or 2 (stereo)")
        
        # Use object.__setattr__ to set values on immutable object
        object.__setattr__(self, "_sample_rate", sample_rate)
        object.__setattr__(self, "_encoding", encoding)
        object.__setattr__(self, "_channels", channels)
    
    @property
    def sample_rate(self) -> int:
        """Get the sample rate in Hz."""
        return self._sample_rate  # type: ignore
    
    @property
    def encoding(self) -> str:
        """Get the encoding format."""
        return self._encoding  # type: ignore
    
    @property
    def channels(self) -> int:
        """Get the number of channels (1=mono, 2=stereo)."""
        return self._channels  # type: ignore
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent attribute modification (immutability)."""
        raise AttributeError("AudioFormat is immutable")
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on all parameters."""
        if not isinstance(other, AudioFormat):
            return False
        return (
            self.sample_rate == other.sample_rate
            and self.encoding == other.encoding
            and self.channels == other.channels
        )
    
    def __hash__(self) -> int:
        """Make AudioFormat hashable (can be used in sets/dicts)."""
        return hash((self.sample_rate, self.encoding, self.channels))
    
    def __str__(self) -> str:
        """String representation."""
        channel_str = "mono" if self.channels == 1 else "stereo"
        return f"{self.sample_rate}Hz {self.encoding} {channel_str}"
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"AudioFormat(sample_rate={self.sample_rate}, "
            f"encoding='{self.encoding}', channels={self.channels})"
        )
