"""CallerAudioPort — output port for streaming synthesized audio to caller."""

from abc import ABC, abstractmethod

from src.domain.entities.speech_segment import SpeechSegment


class CallerAudioPort(ABC):
    """
    Output port for sending synthesized speech audio back to the caller.

    Hexagonal Architecture: This is a driven port (secondary port).
    The domain use cases depend on this interface; infrastructure adapters
    implement it (e.g., ExotelWebSocketAdapter).

    Business Rule: Audio is streamed segment-by-segment to maintain low latency.
    The last segment carries is_last=True to signal stream completion.
    """

    @abstractmethod
    async def send_segment(self, stream_id: str, segment: SpeechSegment) -> None:
        """
        Send a single synthesized audio segment to the caller.

        Args:
            stream_id: The call stream identifier (routes to correct WebSocket)
            segment: The SpeechSegment containing PCM audio bytes to send
        """
