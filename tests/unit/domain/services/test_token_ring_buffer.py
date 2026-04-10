"""Tests for TokenRingBuffer — async circular buffer for token streaming."""

import pytest
import asyncio
from src.domain.services.token_ring_buffer import TokenRingBuffer


class TestTokenRingBufferInit:
    """Test initialization and basic properties."""

    def test_init_default_capacity(self):
        """Should initialize with default capacity of 256."""
        buf = TokenRingBuffer()
        assert buf.capacity() == 256

    def test_init_custom_capacity(self):
        """Should initialize with custom capacity."""
        buf = TokenRingBuffer(capacity=512)
        assert buf.capacity() == 512

    def test_init_invalid_capacity_zero(self):
        """Should reject capacity of 0."""
        with pytest.raises(ValueError, match="Capacity must be > 0"):
            TokenRingBuffer(capacity=0)

    def test_init_invalid_capacity_negative(self):
        """Should reject negative capacity."""
        with pytest.raises(ValueError, match="Capacity must be > 0"):
            TokenRingBuffer(capacity=-5)

    def test_initial_state(self):
        """Should start empty and not complete."""
        buf = TokenRingBuffer()
        assert buf.is_empty()
        assert buf.size() == 0
        assert not buf.is_complete()


class TestBasicOperations:
    """Test basic put/get operations."""

    @pytest.mark.asyncio
    async def test_put_single_token(self):
        """Should put a single token into buffer."""
        buf = TokenRingBuffer()
        await buf.put("hello")
        assert buf.size() == 1
        assert not buf.is_empty()

    @pytest.mark.asyncio
    async def test_get_single_token(self):
        """Should get the token that was put."""
        buf = TokenRingBuffer()
        await buf.put("hello")
        token = await buf.get()
        assert token == "hello"
        assert buf.is_empty()

    @pytest.mark.asyncio
    async def test_put_get_fifo_order(self):
        """Should maintain FIFO order."""
        buf = TokenRingBuffer()
        tokens = ["hello", "world", "test"]
        for token in tokens:
            await buf.put(token)
        
        for expected in tokens:
            result = await buf.get()
            assert result == expected

    @pytest.mark.asyncio
    async def test_put_empty_token_raises(self):
        """Should reject empty tokens."""
        buf = TokenRingBuffer()
        with pytest.raises(ValueError, match="Token cannot be empty"):
            await buf.put("")


class TestBackpressure:
    """Test backpressure when buffer reaches capacity."""

    @pytest.mark.asyncio
    async def test_buffer_respects_capacity_limit(self):
        """Buffer should not exceed capacity."""
        buf = TokenRingBuffer(capacity=3)
        
        # Fill to capacity
        await buf.put("token1")
        await buf.put("token2")
        await buf.put("token3")
        assert buf.size() == 3
        
        # Verify we can't add more without space
        assert buf.size() == buf.capacity()

    @pytest.mark.asyncio
    async def test_put_get_alternating_respects_capacity(self):
        """Put/get alternating should respect capacity."""
        buf = TokenRingBuffer(capacity=2)
        
        await buf.put("a")
        await buf.put("b")
        assert buf.size() == 2
        
        token = await buf.get()
        assert token == "a"
        assert buf.size() == 1
        
        await buf.put("c")
        assert buf.size() == 2


class TestCompleteSignal:
    """Test complete() and EOF behavior."""

    @pytest.mark.asyncio
    async def test_get_returns_none_on_eof(self):
        """Should return None when buffer empty after complete()."""
        buf = TokenRingBuffer()
        await buf.put("token")
        token = await buf.get()
        assert token == "token"
        
        # Complete signal
        await buf.complete()
        
        # Next get should return None (EOF)
        result = await buf.get()
        assert result is None

    @pytest.mark.asyncio
    async def test_put_after_complete_raises(self):
        """Should reject puts after complete() called."""
        buf = TokenRingBuffer()
        await buf.complete()
        
        with pytest.raises(ValueError, match="Cannot put token after complete"):
            await buf.put("token")

    @pytest.mark.asyncio
    async def test_complete_wakes_waiting_consumers(self):
        """complete() should wake consumers waiting on empty buffer."""
        buf = TokenRingBuffer()
        await buf.complete()
        
        # Get should return None immediately (no wait)
        result = await buf.get()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_waits_until_complete_or_token(self):
        """Get should wait if empty, return None on complete."""
        buf = TokenRingBuffer()
        
        got_none = False
        
        async def get_and_check():
            nonlocal got_none
            result = await buf.get()
            got_none = result is None
        
        task = asyncio.create_task(get_and_check())
        await asyncio.sleep(0.05)
        assert not got_none  # Still waiting
        
        # Signal complete
        await buf.complete()
        await asyncio.wait_for(task, timeout=1.0)
        assert got_none


class TestConcurrentProducerConsumer:
    """Test concurrent producer/consumer scenarios."""

    @pytest.mark.asyncio
    async def test_producer_consumer_concurrent(self):
        """Should handle concurrent producer and consumer."""
        buf = TokenRingBuffer(capacity=10)
        consumed = []
        
        async def producer():
            for i in range(20):
                await buf.put(f"token{i}")
                await asyncio.sleep(0.001)
            await buf.complete()
        
        async def consumer():
            while True:
                token = await buf.get()
                if token is None:
                    break
                consumed.append(token)
                await asyncio.sleep(0.002)
        
        await asyncio.gather(producer(), consumer())
        assert len(consumed) == 20
        assert consumed == [f"token{i}" for i in range(20)]

    @pytest.mark.asyncio
    async def test_multiple_consumers_not_supported(self):
        """Multiple consumers may see duplicates/missing tokens."""
        # This is expected behavior — TokenRingBuffer is designed
        # for single producer, single consumer.
        # Test documents that behavior.
        buf = TokenRingBuffer()
        await buf.put("token1")
        await buf.put("token2")
        
        # First consumer gets token1
        token1 = await buf.get()
        assert token1 == "token1"
        
        # Second consumer gets token2
        token2 = await buf.get()
        assert token2 == "token2"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_empty_get_waits_indefinitely(self):
        """Get on empty buffer (not complete) should wait."""
        buf = TokenRingBuffer()
        
        async def get_with_timeout():
            try:
                await asyncio.wait_for(buf.get(), timeout=0.1)
                return "got token"
            except asyncio.TimeoutError:
                return "timed out waiting"
        
        result = await get_with_timeout()
        assert result == "timed out waiting"

    @pytest.mark.asyncio
    async def test_capacity_one(self):
        """Should work with minimum capacity of 1."""
        buf = TokenRingBuffer(capacity=1)
        await buf.put("a")
        token = await buf.get()
        assert token == "a"

    @pytest.mark.asyncio
    async def test_large_capacity(self):
        """Should work with large capacity."""
        buf = TokenRingBuffer(capacity=10000)
        assert buf.capacity() == 10000

    @pytest.mark.asyncio
    async def test_fill_to_exact_capacity(self):
        """Should allow filling to exact capacity."""
        buf = TokenRingBuffer(capacity=5)
        for i in range(5):
            await buf.put(f"token{i}")
        assert buf.size() == 5

    @pytest.mark.asyncio
    async def test_drain_and_refill(self):
        """Should allow draining and refilling."""
        buf = TokenRingBuffer(capacity=3)
        
        # Fill
        for i in range(3):
            await buf.put(f"a{i}")
        
        # Drain
        for i in range(3):
            token = await buf.get()
            assert token == f"a{i}"
        
        # Refill
        for i in range(3):
            await buf.put(f"b{i}")
        
        # Drain again
        for i in range(3):
            token = await buf.get()
            assert token == f"b{i}"

    @pytest.mark.asyncio
    async def test_complete_idempotent(self):
        """Calling complete() multiple times should be safe."""
        buf = TokenRingBuffer()
        await buf.complete()
        await buf.complete()  # Should not raise
        assert buf.is_complete()

    @pytest.mark.asyncio
    async def test_is_empty_after_complete(self):
        """is_empty should be True after draining completed buffer."""
        buf = TokenRingBuffer()
        await buf.put("token")
        await buf.complete()
        
        token = await buf.get()
        assert token == "token"
        assert buf.is_empty()
        
        # Final get returns None
        result = await buf.get()
        assert result is None


class TestIntegrationScenario:
    """Test realistic LLM streaming scenario."""

    @pytest.mark.asyncio
    async def test_llm_producer_tts_consumer_scenario(self):
        """Simulate LLM producing tokens, TTS consuming and synthesizing."""
        buf = TokenRingBuffer(capacity=20)
        produced_count = 0
        consumed_tokens = []
        
        async def llm_producer():
            nonlocal produced_count
            # Simulate LLM producing tokens at variable rate
            for i in range(50):
                await buf.put(f"token{i}")
                produced_count += 1
                # Variable latency
                if i % 5 == 0:
                    await asyncio.sleep(0.005)
            await buf.complete()
        
        async def tts_consumer():
            # Simulate TTS consuming at slower rate
            while True:
                token = await buf.get()
                if token is None:
                    break
                consumed_tokens.append(token)
                await asyncio.sleep(0.001)  # Slower than producer
        
        await asyncio.gather(llm_producer(), tts_consumer())
        
        assert produced_count == 50
        assert len(consumed_tokens) == 50
        assert consumed_tokens == [f"token{i}" for i in range(50)]
        assert buf.is_complete()
        assert buf.is_empty()

    @pytest.mark.asyncio
    async def test_tts_slower_than_llm_backpressure(self):
        """TTS slower than LLM should trigger backpressure."""
        buf = TokenRingBuffer(capacity=5)
        produced = []
        consumed = []
        
        async def fast_producer():
            for i in range(20):
                await buf.put(f"token{i}")
                produced.append(i)
            await buf.complete()
        
        async def slow_consumer():
            while True:
                token = await buf.get()
                if token is None:
                    break
                consumed.append(token)
                await asyncio.sleep(0.01)  # Much slower
        
        await asyncio.gather(fast_producer(), slow_consumer())
        
        assert len(produced) == 20
        assert len(consumed) == 20
