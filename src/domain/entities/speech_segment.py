"""SpeechSegment entity - synthesized audio derived from AIResponse text."""

from datetime import datetime

from src.domain.value_objects.audio_format import AudioFormat


class SpeechSegment:
    """
    Entity representing a chunk of synthesized speech audio.

    Business Rule: SpeechSegments are produced from AIResponse text by a TTS
    engine and streamed incrementally back to the caller.  Position orders
    segments within the same response; is_last marks the final segment.
    """

    __slots__ = ("_response_id", "_position", "_audio_data", "_audio_format", "_is_last", "_timestamp")

    def __init__(
        self,
        response_id: str,
        position: int,
        audio_data: bytes,
        audio_format: AudioFormat,
        is_last: bool,
        timestamp: datetime,
    ) -> None:
        if not response_id or not response_id.strip():
            raise ValueError("response_id cannot be empty")
        if not audio_data:
            raise ValueError("Audio data cannot be empty")
        if position < 0:
            raise ValueError("Position must be non-negative")

        self._response_id = response_id
        self._position = position
        self._audio_data = audio_data
        self._audio_format = audio_format
        self._is_last = is_last
        self._timestamp = timestamp

    # --- Read ---

    @property
    def response_id(self) -> str:
        return self._response_id

    @property
    def position(self) -> int:
        return self._position

    @property
    def audio_data(self) -> bytes:
        return self._audio_data

    @property
    def audio_format(self) -> AudioFormat:
        return self._audio_format

    @property
    def is_last(self) -> bool:
        return self._is_last

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    @property
    def size_bytes(self) -> int:
        return len(self._audio_data)

    @property
    def duration_seconds(self) -> float:
        """Duration calculated for PCM16LE (2 bytes/sample)."""
        bytes_per_sample = 2
        samples = len(self._audio_data) / (bytes_per_sample * self._audio_format.channels)
        return samples / self._audio_format.sample_rate

    # --- Ordering ---

    def __lt__(self, other: "SpeechSegment") -> bool:
        return self._position < other._position

    def __le__(self, other: "SpeechSegment") -> bool:
        return self._position <= other._position

    def __gt__(self, other: "SpeechSegment") -> bool:
        return self._position > other._position

    def __ge__(self, other: "SpeechSegment") -> bool:
        return self._position >= other._position

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SpeechSegment):
            return False
        return self._response_id == other._response_id and self._position == other._position

    def __hash__(self) -> int:
        return hash((self._response_id, self._position))

    def __repr__(self) -> str:
        flag = "last" if self._is_last else "mid"
        return (
            f"SpeechSegment(pos={self._position}, "
            f"{self.size_bytes}B, {flag})"
        )
