"""StubResponseStreamer — ResponseStreamerPort stub for testing."""

from typing import AsyncIterator

from src.ports.response_streamer_port import ResponseStreamerPort


class StubResponseStreamer(ResponseStreamerPort):
    """
    Stub implementation of ResponseStreamerPort for testing.

    Yields pre-configured tokens without calling any external API.
    """

    def __init__(self, response_text: str = "I understand your request.") -> None:
        self._text = response_text

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        """
        Yield tokens from pre-configured response text.

        Args:
            prompt: Unused in stub

        Yields:
            Word tokens followed by space
        """
        for word in self._text.split():
            yield word + " "
