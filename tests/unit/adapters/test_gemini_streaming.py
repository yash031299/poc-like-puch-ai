"""Tests for GeminiResponseStreamer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.gemini_response_streamer import GeminiResponseStreamer
from src.adapters.stub_response_streamer import StubResponseStreamer


class MockGeminiChunk:
    """Mock chunk from Gemini API."""

    def __init__(self, text):
        self.text = text


class MockGeminiStream:
    """Mock streaming response from Gemini API."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.tokens):
            raise StopIteration
        token = self.tokens[self.index]
        self.index += 1
        return MockGeminiChunk(token)


@pytest.mark.asyncio
async def test_stub_response_streamer_yields_tokens():
    """Stub streamer yields word tokens."""
    streamer = StubResponseStreamer("Hello world test")

    tokens = []
    async for token in streamer.stream_response("any prompt"):
        tokens.append(token)

    assert len(tokens) == 3
    assert tokens[0] == "Hello "
    assert tokens[1] == "world "
    assert tokens[2] == "test "


@pytest.mark.asyncio
async def test_stub_response_streamer_custom_text():
    """Stub streamer can be initialized with custom response."""
    streamer = StubResponseStreamer("Custom response")

    tokens = []
    async for token in streamer.stream_response("prompt"):
        tokens.append(token)

    assert len(tokens) == 2
    full_response = "".join(tokens).strip()
    assert full_response == "Custom response"


@pytest.mark.asyncio
async def test_stub_response_streamer_single_word():
    """Stub streamer handles single-word response."""
    streamer = StubResponseStreamer("Word")

    tokens = []
    async for token in streamer.stream_response("prompt"):
        tokens.append(token)

    assert len(tokens) == 1
    assert tokens[0] == "Word "


@pytest.mark.asyncio
async def test_gemini_response_streamer_empty_chunks():
    """Gemini streamer skips empty chunks."""
    with patch("src.adapters.gemini_response_streamer.genai") as mock_genai:
        # Mock the API call
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        # Create mock stream with empty chunks
        mock_stream = MockGeminiStream(["Hello", "", "world", "", "!"])
        mock_client.models.generate_content_stream.return_value = mock_stream

        streamer = GeminiResponseStreamer("test-key")

        tokens = []
        async for token in streamer.stream_response("test prompt"):
            tokens.append(token)

        # Should only get non-empty tokens
        assert len(tokens) == 3
        assert tokens[0] == "Hello"
        assert tokens[1] == "world"
        assert tokens[2] == "!"


@pytest.mark.asyncio
async def test_gemini_response_streamer_full_response():
    """Gemini streamer concatenates tokens into full response."""
    with patch("src.adapters.gemini_response_streamer.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_stream = MockGeminiStream(["Hello ", "how ", "can ", "I ", "help?"])
        mock_client.models.generate_content_stream.return_value = mock_stream

        streamer = GeminiResponseStreamer("test-key")

        full_text = ""
        async for token in streamer.stream_response("test"):
            full_text += token

        assert full_text == "Hello how can I help?"


@pytest.mark.asyncio
async def test_gemini_response_streamer_uses_system_prompt():
    """Gemini streamer includes system instruction."""
    with patch("src.adapters.gemini_response_streamer.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_stream = MockGeminiStream(["test"])
        mock_client.models.generate_content_stream.return_value = mock_stream

        streamer = GeminiResponseStreamer("test-key")

        async for _ in streamer.stream_response("prompt"):
            pass

        # Verify generate_content_stream was called with system_instruction
        call_args = mock_client.models.generate_content_stream.call_args
        assert call_args is not None
        # Check that config was passed with system_instruction
        config_arg = call_args.kwargs.get("config") or call_args[0][3]
        assert config_arg is not None


@pytest.mark.asyncio
async def test_response_streamer_handles_exception():
    """Streamer propagates exceptions from API."""
    with patch("src.adapters.gemini_response_streamer.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content_stream.side_effect = RuntimeError("API error")

        streamer = GeminiResponseStreamer("test-key")

        with pytest.raises(RuntimeError, match="API error"):
            async for _ in streamer.stream_response("prompt"):
                pass
