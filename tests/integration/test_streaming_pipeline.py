"""Integration tests for Phase 3B streaming LLM/TTS pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import asyncio
from datetime import datetime, timezone

from src.domain.services.token_ring_buffer import TokenRingBuffer
from src.domain.entities.utterance import Utterance
from src.domain.value_objects.audio_format import AudioFormat
from src.adapters.stub_llm_adapter import StubLLMAdapter
from src.adapters.stub_tts_adapter import StubTTSAdapter


class TestTokenRingBufferIntegration:
    """Integration tests for TokenRingBuffer in LLM/TTS scenarios."""

    @pytest.mark.asyncio
    async def test_ring_buffer_producer_consumer(self):
        """Test token buffer with producer and consumer."""
        buffer = TokenRingBuffer(capacity=20)
        produced = []
        consumed = []

        async def producer():
            for i in range(50):
                token = f"word{i} "
                await buffer.put(token)
                produced.append(token)
            await buffer.complete()

        async def consumer():
            while True:
                token = await buffer.get()
                if token is None:
                    break
                consumed.append(token)

        await asyncio.gather(producer(), consumer())

        assert len(consumed) == 50
        assert consumed == produced

    @pytest.mark.asyncio
    async def test_ring_buffer_backpressure(self):
        """Test that ring buffer handles backpressure correctly."""
        buffer = TokenRingBuffer(capacity=5)
        max_size_observed = 0

        async def producer():
            for i in range(20):
                await buffer.put(f"t{i}")
            await buffer.complete()

        async def consumer():
            nonlocal max_size_observed
            while True:
                token = await buffer.get()
                if token is None:
                    break
                max_size_observed = max(max_size_observed, buffer.size())
                await asyncio.sleep(0.001)  # Slow consumer

        await asyncio.gather(producer(), consumer())
        # Buffer should never exceed capacity significantly
        assert max_size_observed <= 10  # Allow some margin


class TestStreamingAdapters:
    """Tests for streaming implementations in adapters."""

    @pytest.mark.asyncio
    async def test_stub_tts_synthesize_stream(self):
        """Test StubTTSAdapter.synthesize_stream implementation."""
        tts = StubTTSAdapter(sample_rate=8000, duration_ms=400)
        buffer = TokenRingBuffer()

        # Produce tokens
        await buffer.put("Hello")
        await buffer.put(" ")
        await buffer.put("world")
        await buffer.complete()

        # Synthesize from stream
        segments = []
        async for segment in tts.synthesize_stream("stream_id", "response_id", buffer):
            segments.append(segment)
            assert segment.response_id == "response_id"
            assert len(segment.audio_data) > 0

        # Should get segments
        assert len(segments) > 0
        assert segments[-1].is_last

    @pytest.mark.asyncio
    async def test_stub_tts_consumes_all_tokens(self):
        """Test that stub TTS adapter consumes all tokens from buffer."""
        tts = StubTTSAdapter()
        buffer = TokenRingBuffer()

        # Produce 100 tokens
        token_count = 100
        for i in range(token_count):
            await buffer.put(f"token{i}")
        await buffer.complete()

        # Consume via TTS
        segment_count = 0
        async for segment in tts.synthesize_stream("stream", "response", buffer):
            segment_count += 1

        # Should get segments (count depends on duration)
        assert segment_count > 0
        # Buffer should be completely consumed
        assert buffer.is_empty()


class TestStreamingErrorScenarios:
    """Tests for error handling in streaming."""

    @pytest.mark.asyncio
    async def test_producer_error_stops_consumer(self):
        """Test that producer error is handled."""
        buffer = TokenRingBuffer()

        async def failing_producer():
            await buffer.put("token1")
            raise RuntimeError("Producer failed")

        async def consumer():
            token = await buffer.get()
            assert token == "token1"

        # Producer error should propagate
        with pytest.raises(RuntimeError, match="Producer failed"):
            await asyncio.gather(failing_producer(), consumer())

    @pytest.mark.asyncio
    async def test_empty_buffer_eof(self):
        """Test EOF handling on empty buffer."""
        buffer = TokenRingBuffer()
        await buffer.complete()

        # Get should return None immediately
        token = await buffer.get()
        assert token is None


class TestStreamingPhraseBoundaries:
    """Tests for phrase boundary detection in TTS."""

    def test_google_tts_phrase_complete_punctuation(self):
        """Test phrase completion detection on sentence endings."""
        from src.adapters.google_tts_adapter import GoogleTTSAdapter

        tts = GoogleTTSAdapter()

        test_cases = [
            ("Hello.", 1, True, "period ends phrase"),
            ("What?", 1, True, "question mark ends phrase"),
            ("Really!", 1, True, "exclamation ends phrase"),
            ("Hello world", 1, False, "no punctuation"),
            ("Price: 3.14", 1, False, "decimal not phrase end"),
            ("Hi", 50, True, "token count triggers phrase"),
            ("Hello world", 50, True, "both punctuation and count"),
        ]

        for text, token_count, expected, reason in test_cases:
            result = tts._is_phrase_complete(text, token_count)
            assert result == expected, f"Failed: {reason} for '{text}' with {token_count} tokens"

    def test_google_tts_phrase_complete_token_count(self):
        """Test phrase completion by token accumulation."""
        from src.adapters.google_tts_adapter import GoogleTTSAdapter

        tts = GoogleTTSAdapter()

        # Below threshold
        assert not tts._is_phrase_complete("some text", 30)
        # At threshold
        assert tts._is_phrase_complete("some text", 50)
        # Above threshold
        assert tts._is_phrase_complete("some text", 100)


class TestConcurrentLLMTTS:
    """Tests for concurrent LLM and TTS operations."""

    @pytest.mark.asyncio
    async def test_llm_faster_than_tts(self):
        """Test when LLM produces faster than TTS consumes."""
        buffer = TokenRingBuffer(capacity=10)
        produced_count = 0
        consumed_count = 0

        async def fast_producer():
            nonlocal produced_count
            for i in range(100):
                await buffer.put(f"token{i}")
                produced_count += 1
                # Very fast
                if i % 10 == 0:
                    await asyncio.sleep(0.0001)
            await buffer.complete()

        async def slow_consumer():
            nonlocal consumed_count
            while True:
                token = await buffer.get()
                if token is None:
                    break
                consumed_count += 1
                # Slow
                await asyncio.sleep(0.001)

        await asyncio.gather(fast_producer(), slow_consumer())

        assert produced_count == 100
        assert consumed_count == 100

    @pytest.mark.asyncio
    async def test_tts_faster_than_llm(self):
        """Test when TTS consumes faster than LLM produces."""
        buffer = TokenRingBuffer(capacity=10)
        produced_count = 0
        consumed_count = 0

        async def slow_producer():
            nonlocal produced_count
            for i in range(20):
                await buffer.put(f"token{i}")
                produced_count += 1
                # Slow
                await asyncio.sleep(0.005)
            await buffer.complete()

        async def fast_consumer():
            nonlocal consumed_count
            while True:
                token = await buffer.get()
                if token is None:
                    break
                consumed_count += 1
                # Very fast
                if consumed_count % 5 == 0:
                    await asyncio.sleep(0.0001)

        await asyncio.gather(slow_producer(), fast_consumer())

        assert produced_count == 20
        assert consumed_count == 20

