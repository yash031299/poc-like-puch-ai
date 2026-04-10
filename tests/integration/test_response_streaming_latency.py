"""Tests for response streaming latency."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.gemini_response_streamer import GeminiResponseStreamer
from src.adapters.stub_response_streamer import StubResponseStreamer


class MockGeminiChunk:
    """Mock chunk from Gemini API."""

    def __init__(self, text, delay=0):
        self.text = text
        self.delay = delay


class DelayedMockGeminiStream:
    """Mock streaming response with configurable delays."""

    def __init__(self, tokens_with_delays):
        self.tokens = tokens_with_delays
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.tokens):
            raise StopIteration

        token_text, delay = self.tokens[self.index]
        self.index += 1

        if delay > 0:
            time.sleep(delay)

        chunk = MockGeminiChunk(token_text)
        return chunk


@pytest.mark.asyncio
async def test_first_token_latency_under_200ms():
    """First token arrives within 200ms limit."""
    with patch("src.adapters.gemini_response_streamer.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Tokens with minimal delay
        tokens = [
            ("Hello ", 0.01),  # 10ms
            ("world", 0.02),   # 20ms
        ]
        mock_stream = DelayedMockGeminiStream(tokens)
        mock_client.models.generate_content_stream.return_value = mock_stream

        streamer = GeminiResponseStreamer("test-key")

        start = time.monotonic()
        first_token_time = None
        token_index = 0
        async for token in streamer.stream_response("test"):
            if token_index == 0:
                first_token_time = time.monotonic() - start
            token_index += 1

        # First token should arrive in less than 200ms
        assert first_token_time is not None
        assert first_token_time < 0.2


@pytest.mark.asyncio
async def test_streaming_accumulates_tokens():
    """Multiple tokens accumulate into full response."""
    streamer = StubResponseStreamer("The quick brown fox")

    accumulated = ""
    token_count = 0
    async for token in streamer.stream_response("prompt"):
        accumulated += token
        token_count += 1

    assert token_count == 4
    assert "quick" in accumulated
    assert "brown" in accumulated
    assert "fox" in accumulated


@pytest.mark.asyncio
async def test_streaming_token_timing():
    """Tokens arrive at expected intervals."""
    streamer = StubResponseStreamer("A B C D E")

    tokens_and_times = []
    start = time.monotonic()

    async for token in streamer.stream_response("prompt"):
        elapsed = time.monotonic() - start
        tokens_and_times.append((token, elapsed))

    # Should have 5 tokens
    assert len(tokens_and_times) == 5

    # All tokens should arrive in quick succession (stub is synchronous)
    for token, elapsed in tokens_and_times:
        assert elapsed < 1.0  # All within 1 second


@pytest.mark.asyncio
async def test_streaming_empty_response():
    """Streaming handles empty response (no tokens)."""
    streamer = StubResponseStreamer("")

    tokens = []
    async for token in streamer.stream_response("prompt"):
        tokens.append(token)

    # Empty string split yields empty list
    assert len(tokens) == 0


@pytest.mark.asyncio
async def test_streaming_large_token_sequence():
    """Streaming handles many tokens efficiently."""
    # Create a response with many tokens
    words = " ".join([f"word{i}" for i in range(100)])
    streamer = StubResponseStreamer(words)

    token_count = 0
    start = time.monotonic()

    async for token in streamer.stream_response("prompt"):
        token_count += 1

    elapsed = time.monotonic() - start

    assert token_count == 100
    # Should complete quickly (stub is synchronous)
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_streaming_chunk_accumulation():
    """Tokens can be accumulated into chunks for TTS."""
    streamer = StubResponseStreamer("One two three four five six seven eight nine ten")

    # Accumulate into 50-token chunks
    chunk_size = 50
    chunks = []
    current_chunk = ""
    token_count = 0

    async for token in streamer.stream_response("prompt"):
        current_chunk += token
        token_count += 1

        if token_count >= chunk_size:
            chunks.append(current_chunk)
            current_chunk = ""
            token_count = 0

    if current_chunk:
        chunks.append(current_chunk)

    # Should have at least one chunk (10 words < 50 tokens but more than words)
    assert len(chunks) >= 1
    full_text = "".join(chunks)
    assert "One" in full_text
    assert "ten" in full_text
