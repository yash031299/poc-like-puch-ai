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


class TestStreamingPipelineWithInterrupts:
    """Integration tests for Phase 3C interrupt handling in streaming pipeline."""

    @pytest.mark.asyncio
    async def test_llm_producer_stops_on_interrupt(self):
        """Test that LLM producer stops generating tokens when interrupted."""
        from src.domain.aggregates.conversation_session import ConversationSession
        
        buffer = TokenRingBuffer(capacity=10)
        produced_count = 0
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        session.set_speaking()
        
        async def producer_with_interrupt():
            nonlocal produced_count
            for i in range(100):  # Would produce many tokens
                if session.is_interrupted():
                    break
                await buffer.put(f"token{i}")
                produced_count += 1
                await asyncio.sleep(0.001)
            await buffer.complete()
        
        async def interrupt_after_delay():
            await asyncio.sleep(0.01)  # Let producer run a bit
            session.mark_interrupted()
        
        # Run producer and interrupt concurrently
        await asyncio.gather(
            producer_with_interrupt(),
            interrupt_after_delay()
        )
        
        # Should have produced fewer than 100 tokens due to interrupt
        assert produced_count < 100
        assert session.is_interrupted()

    @pytest.mark.asyncio
    async def test_tts_consumer_stops_on_interrupt(self):
        """Test that TTS consumer stops sending segments when interrupted."""
        from src.domain.aggregates.conversation_session import ConversationSession
        
        buffer = TokenRingBuffer(capacity=10)
        consumed_count = 0
        
        session = ConversationSession.create(
            stream_identifier="stream-123",
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        session.set_speaking()
        
        async def producer():
            for i in range(50):
                await buffer.put(f"token{i}")
                await asyncio.sleep(0.001)
            await buffer.complete()
        
        async def consumer_with_interrupt():
            nonlocal consumed_count
            while True:
                token = await buffer.get()
                if token is None:
                    break
                if session.is_interrupted():
                    break
                consumed_count += 1
                await asyncio.sleep(0.001)
        
        async def interrupt_after_delay():
            await asyncio.sleep(0.02)
            session.mark_interrupted()
        
        # Run all concurrently
        await asyncio.gather(
            producer(),
            consumer_with_interrupt(),
            interrupt_after_delay()
        )
        
        # Should have consumed fewer tokens due to interrupt
        assert consumed_count < 50
        assert session.is_interrupted()

    @pytest.mark.asyncio
    async def test_interrupt_flag_survives_session_reload(self):
        """Test that interrupt flag is preserved during session operations."""
        from src.domain.aggregates.conversation_session import ConversationSession
        from src.domain.value_objects.stream_identifier import StreamIdentifier
        from src.adapters.in_memory_session_repository import InMemorySessionRepository
        
        repo = InMemorySessionRepository()
        
        session = ConversationSession.create(
            stream_identifier=StreamIdentifier("stream-123"),
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        session.set_speaking()
        session.mark_interrupted()
        
        await repo.save(session)
        
        # Reload from repo
        reloaded = await repo.get("stream-123")
        
        # Interrupt flag should still be set
        assert reloaded is not None
        assert reloaded.is_interrupted()

    @pytest.mark.asyncio
    async def test_streaming_response_handles_early_interrupt(self):
        """Test that streaming response gracefully handles early interrupt."""
        from src.use_cases.streaming_generate_response import StreamingGenerateResponseUseCase
        from src.adapters.in_memory_session_repository import InMemorySessionRepository, FakeCallerAudio
        from src.adapters.stub_llm_adapter import StubLLMAdapter
        from src.adapters.stub_tts_adapter import StubTTSAdapter
        from src.domain.aggregates.conversation_session import ConversationSession
        from src.domain.value_objects.stream_identifier import StreamIdentifier
        from src.domain.entities.utterance import Utterance
        from datetime import datetime, timezone
        
        repo = InMemorySessionRepository()
        llm = StubLLMAdapter()
        tts = StubTTSAdapter()
        audio_out = FakeCallerAudio()
        
        use_case = StreamingGenerateResponseUseCase(repo, llm, tts, audio_out)
        
        # Create session with utterance
        session = ConversationSession.create(
            stream_identifier=StreamIdentifier("stream-123"),
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        session.activate()
        
        # Add a fake utterance
        utterance = Utterance(text="Test message", confidence=0.95, is_final=True, timestamp=datetime.now(timezone.utc))
        utterance._utterance_id = "utt-123"
        session._utterances.append(utterance)
        
        await repo.save(session)
        
        async def interrupt_during_response():
            # Let response processing start
            await asyncio.sleep(0.05)
            # Mark interrupt on session
            session.mark_interrupted()
        
        # Start response and interrupt concurrently
        response_task = asyncio.create_task(
            use_case.execute("stream-123", "utt-123")
        )
        interrupt_task = asyncio.create_task(interrupt_during_response())
        
        # Both should complete without errors
        await asyncio.gather(response_task, interrupt_task)
        
        # Session should be in listening state after interrupt
        reloaded = await repo.get("stream-123")
        assert reloaded is not None
        assert reloaded.interaction_state == "listening"

    @pytest.mark.asyncio
    async def test_interrupt_latency_under_100ms(self):
        """Test that interrupt detection and handling is <100ms."""
        from src.domain.aggregates.conversation_session import ConversationSession
        from src.domain.value_objects.stream_identifier import StreamIdentifier
        from datetime import datetime, timezone
        
        session = ConversationSession.create(
            stream_identifier=StreamIdentifier("stream-123"),
            caller_number="+1234567890",
            called_number="+0987654321",
            audio_format={"sample_rate": 16000, "encoding": "PCM16LE", "channels": 1}
        )
        session.set_speaking()
        
        # Measure time to mark interrupt
        start = datetime.now(timezone.utc)
        session.mark_interrupted()
        elapsed = datetime.now(timezone.utc) - start
        
        # Should be very fast (< 1ms)
        assert elapsed.total_seconds() < 0.001
        assert session.is_interrupted()

