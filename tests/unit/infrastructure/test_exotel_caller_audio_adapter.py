"""Unit tests for ExotelCallerAudioAdapter — protocol compliance and bidirectional streaming.

Tests validate:
- Sequence number tracking (monotonically increasing per stream)
- Timestamp calculation (milliseconds from stream start)
- Chunk size validation (multiples of 320 bytes)
- JSON message format compliance with Exotel protocol
"""

import asyncio
import base64
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.infrastructure.exotel_caller_audio_adapter import ExotelCallerAudioAdapter
from src.domain.entities.speech_segment import SpeechSegment
from src.domain.value_objects.audio_format import AudioFormat


@pytest.fixture
def audio_format():
    """Standard audio format for tests."""
    return AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)


@pytest.fixture
def adapter():
    """Fresh adapter instance for each test."""
    return ExotelCallerAudioAdapter()


@pytest.fixture
def mock_websocket():
    """Mock WebSocket for testing."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


class TestExotelCallerAudioAdapterRegistration:
    """Test stream registration and cleanup."""

    def test_register_initializes_sequence_at_1(self, adapter, mock_websocket):
        """Test that sequence number starts at 1 when stream is registered."""
        adapter.register("stream-123", mock_websocket)
        assert adapter._sequence_numbers["stream-123"] == 1

    def test_register_tracks_stream_start_time(self, adapter, mock_websocket):
        """Test that stream start time is recorded for timestamp calculation."""
        adapter.register("stream-123", mock_websocket)
        assert "stream-123" in adapter._stream_start_times
        assert isinstance(adapter._stream_start_times["stream-123"], float)
        assert adapter._pacing_enabled["stream-123"] is False

    def test_register_tracks_negotiated_sample_rate(self, adapter, mock_websocket):
        """Adapter should track Exotel-negotiated sample rate per stream."""
        adapter.register("stream-123", mock_websocket, sample_rate=24000)
        assert adapter._stream_sample_rates["stream-123"] == 24000
        assert adapter._pacing_enabled["stream-123"] is True

    def test_unregister_cleans_up_state(self, adapter, mock_websocket):
        """Test that unregister removes all tracking state."""
        adapter.register("stream-123", mock_websocket)
        adapter.unregister("stream-123")
        
        assert "stream-123" not in adapter._connections
        assert "stream-123" not in adapter._sequence_numbers
        assert "stream-123" not in adapter._media_chunk_numbers
        assert "stream-123" not in adapter._media_timestamps_ms
        assert "stream-123" not in adapter._stream_start_times
        assert "stream-123" not in adapter._stream_sample_rates
        assert "stream-123" not in adapter._pacing_enabled
        assert "stream-123" not in adapter._sent_segment_counts

    def test_multiple_streams_have_independent_sequences(self, adapter, mock_websocket):
        """Test that different streams have independent sequence numbers."""
        ws1, ws2 = mock_websocket, AsyncMock()
        
        adapter.register("stream-1", ws1)
        adapter.register("stream-2", ws2)
        
        assert adapter._sequence_numbers["stream-1"] == 1
        assert adapter._sequence_numbers["stream-2"] == 1


class TestExotelCallerAudioAdapterMediaEvents:
    """Test media event creation and sending."""

    @pytest.mark.asyncio
    async def test_send_segment_includes_sequence_number(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that media events include sequence_number field."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),  # Valid 320-byte multiple
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        await adapter.send_segment("stream-123", segment)
        
        # Get the JSON message that was sent
        call_args = mock_websocket.send_text.call_args
        message = json.loads(call_args[0][0])
        
        assert message["sequence_number"] == 1
        assert message["event"] == "media"

    @pytest.mark.asyncio
    async def test_sequence_numbers_increment(self, adapter, audio_format, mock_websocket):
        """Test that sequence numbers increment with each media event."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        await adapter.send_segment("stream-123", segment)
        await adapter.send_segment("stream-123", segment)
        await adapter.send_segment("stream-123", segment)
        
        # Extract sequence numbers from all calls
        sequences = []
        for call in mock_websocket.send_text.call_args_list:
            message = json.loads(call[0][0])
            sequences.append(message["sequence_number"])
        
        assert sequences == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_media_event_includes_timestamp(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that media events include timestamp in milliseconds."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        await adapter.send_segment("stream-123", segment)
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        assert "media" in message
        assert "timestamp" in message["media"]
        # Timestamp should be a string representation of milliseconds
        assert isinstance(message["media"]["timestamp"], str)
        assert int(message["media"]["timestamp"]) >= 0

    @pytest.mark.asyncio
    async def test_media_event_includes_chunk_and_increments(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that outbound media includes chunk and increments per segment."""
        adapter.register("stream-123", mock_websocket)

        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )

        await adapter.send_segment("stream-123", segment)
        await adapter.send_segment("stream-123", segment)

        messages = [json.loads(call[0][0]) for call in mock_websocket.send_text.call_args_list]
        chunks = [msg["media"]["chunk"] for msg in messages]
        assert chunks == [1, 2]

    @pytest.mark.asyncio
    async def test_timestamp_increases_monotonically(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that timestamps increase with successive segments."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        await adapter.send_segment("stream-123", segment)
        await asyncio.sleep(0.01)  # Small delay to ensure time passes
        await adapter.send_segment("stream-123", segment)
        
        # Extract timestamps
        timestamps = []
        for call in mock_websocket.send_text.call_args_list:
            message = json.loads(call[0][0])
            timestamps.append(int(message["media"]["timestamp"]))
        
        # Second timestamp should be >= first (allowing for timing granularity)
        assert timestamps[1] >= timestamps[0]

    @pytest.mark.asyncio
    async def test_timestamp_advances_by_audio_duration(
        self, adapter, mock_websocket
    ):
        """Timestamp should advance by chunk audio duration (stream timeline)."""
        adapter.register("stream-123", mock_websocket)
        fmt_8k = AudioFormat(sample_rate=8000, encoding="PCM16LE", channels=1)

        # 3200 bytes at 8kHz PCM16 mono = 200ms of audio
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=fmt_8k,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )

        await adapter.send_segment("stream-123", segment)
        await adapter.send_segment("stream-123", segment)

        messages = [json.loads(call[0][0]) for call in mock_websocket.send_text.call_args_list]
        first_ts = int(messages[0]["media"]["timestamp"])
        second_ts = int(messages[1]["media"]["timestamp"])
        assert first_ts == 0
        assert second_ts == 200

    @pytest.mark.asyncio
    async def test_media_event_format_compliance(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that media event JSON matches Exotel protocol format."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        await adapter.send_segment("stream-123", segment)
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        # Verify structure matches Exotel spec
        assert message["event"] == "media"
        assert "sequence_number" in message
        assert "stream_sid" in message
        assert "sequenceNumber" in message
        assert "streamSid" in message
        assert "media" in message
        assert "chunk" in message["media"]
        assert "payload" in message["media"]
        assert "timestamp" in message["media"]
        assert "sequenceNumber" in message["media"]
        assert message["stream_sid"] == "stream-123"
        assert message["streamSid"] == "stream-123"
        assert isinstance(message["media"]["chunk"], int)

    @pytest.mark.asyncio
    async def test_send_segment_resamples_to_registered_sample_rate(
        self, adapter, mock_websocket
    ):
        """If stream is negotiated at 8kHz, outbound 16kHz PCM should be resampled to 8kHz."""
        adapter.register("stream-123", mock_websocket, sample_rate=8000)
        fmt_16k = AudioFormat(sample_rate=16000, encoding="PCM16LE", channels=1)
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),  # 100ms at 16kHz PCM16 mono
            audio_format=fmt_16k,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )

        await adapter.send_segment("stream-123", segment)

        message = json.loads(mock_websocket.send_text.call_args[0][0])
        decoded = base64.b64decode(message["media"]["payload"])
        # 100ms at 8kHz PCM16 mono => 1600 bytes
        assert len(decoded) == 1600


class TestExotelCallerAudioAdapterChunkValidation:
    """Test chunk size validation."""

    @pytest.mark.asyncio
    async def test_invalid_chunk_size_raises_assertion(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that chunk sizes not divisible by 320 raise AssertionError."""
        adapter.register("stream-123", mock_websocket)
        
        # 3201 bytes is NOT a multiple of 320
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3201),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        with pytest.raises(AssertionError, match="multiple of 320"):
            await adapter.send_segment("stream-123", segment)

    @pytest.mark.asyncio
    async def test_valid_chunk_sizes(self, adapter, audio_format, mock_websocket):
        """Test that valid chunk sizes (multiples of 320) are accepted."""
        adapter.register("stream-123", mock_websocket)
        
        for chunk_size in [320, 640, 3200, 6400, 96000]:
            mock_websocket.reset_mock()
            
            segment = SpeechSegment(
                response_id="resp-1",
                position=0,
                audio_data=bytes(chunk_size),
                audio_format=audio_format,
                is_last=False,
                timestamp=datetime.now(timezone.utc),
            )
            
            # Should not raise
            await adapter.send_segment("stream-123", segment)
            mock_websocket.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_chunk_size_validation_includes_details(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that validation error includes helpful debugging info."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(1000),  # 1000 % 320 = 40 (invalid)
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        with pytest.raises(AssertionError) as exc_info:
            await adapter.send_segment("stream-123", segment)
        
        error_msg = str(exc_info.value)
        assert "1000" in error_msg
        assert "stream-123" in error_msg
        assert "320" in error_msg


class TestExotelCallerAudioAdapterMarkEvents:
    """Test mark event creation and sequence numbering."""

    @pytest.mark.asyncio
    async def test_mark_event_includes_sequence_number(
        self, adapter, mock_websocket
    ):
        """Test that mark events include sequence_number."""
        adapter.register("stream-123", mock_websocket)
        
        await adapter.send_mark("stream-123", "mark-1")
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        assert message["event"] == "mark"
        assert message["sequence_number"] == 1
        assert message["mark"]["name"] == "mark-1"

    @pytest.mark.asyncio
    async def test_mark_sequence_continues_from_last_media(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that mark sequences are independent from media sequences."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Send media (seq 1), then mark (seq 2)
        await adapter.send_segment("stream-123", segment)
        await adapter.send_mark("stream-123", "playback-1")
        
        # Extract sequences
        calls = mock_websocket.send_text.call_args_list
        media_msg = json.loads(calls[0][0][0])
        mark_msg = json.loads(calls[1][0][0])
        
        assert media_msg["sequence_number"] == 1
        assert mark_msg["sequence_number"] == 2

    @pytest.mark.asyncio
    async def test_mark_event_format_compliance(self, adapter, mock_websocket):
        """Test that mark event JSON matches Exotel protocol format."""
        adapter.register("stream-123", mock_websocket)
        
        await adapter.send_mark("stream-123", "playback-checkpoint")
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        # Verify structure
        assert message["event"] == "mark"
        assert "sequence_number" in message
        assert "stream_sid" in message
        assert "mark" in message
        assert message["mark"]["name"] == "playback-checkpoint"


class TestExotelCallerAudioAdapterClearEvents:
    """Test clear event creation and sequence numbering."""

    @pytest.mark.asyncio
    async def test_clear_event_includes_sequence_number(
        self, adapter, mock_websocket
    ):
        """Test that clear events include sequence_number."""
        adapter.register("stream-123", mock_websocket)
        
        await adapter.send_clear("stream-123")
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        assert message["event"] == "clear"
        assert message["sequence_number"] == 1

    @pytest.mark.asyncio
    async def test_clear_sequence_continues_monotonically(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that clear events continue sequence from previous events."""
        adapter.register("stream-123", mock_websocket)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Send: media (1), mark (2), clear (3)
        await adapter.send_segment("stream-123", segment)
        await adapter.send_mark("stream-123", "mark-1")
        await adapter.send_clear("stream-123")
        
        calls = mock_websocket.send_text.call_args_list
        sequences = [
            json.loads(call[0][0])["sequence_number"]
            for call in calls
        ]
        
        assert sequences == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_clear_event_format_compliance(self, adapter, mock_websocket):
        """Test that clear event JSON matches Exotel protocol format."""
        adapter.register("stream-123", mock_websocket)
        
        await adapter.send_clear("stream-123")
        
        message = json.loads(mock_websocket.send_text.call_args[0][0])
        
        # Verify structure
        assert message["event"] == "clear"
        assert "sequence_number" in message
        assert "stream_sid" in message
        assert message["stream_sid"] == "stream-123"


class TestExotelCallerAudioAdapterStreamIsolation:
    """Test that different streams maintain independent state."""

    @pytest.mark.asyncio
    async def test_different_streams_have_independent_sequences(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that sequence numbers are maintained separately per stream."""
        ws1, ws2 = mock_websocket, AsyncMock()
        
        adapter.register("stream-1", ws1)
        adapter.register("stream-2", ws2)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Send to stream-1
        await adapter.send_segment("stream-1", segment)
        # Send to stream-2
        await adapter.send_segment("stream-2", segment)
        # Send to stream-1 again
        await adapter.send_segment("stream-1", segment)
        
        # Extract sequences
        stream1_seqs = [
            json.loads(call[0][0])["sequence_number"]
            for call in ws1.send_text.call_args_list
        ]
        stream2_seqs = [
            json.loads(call[0][0])["sequence_number"]
            for call in ws2.send_text.call_args_list
        ]
        
        assert stream1_seqs == [1, 2]
        assert stream2_seqs == [1]

    @pytest.mark.asyncio
    async def test_different_streams_have_independent_timestamps(
        self, adapter, audio_format, mock_websocket
    ):
        """Test that timestamp calculations are per-stream."""
        ws1, ws2 = mock_websocket, AsyncMock()
        
        adapter.register("stream-1", ws1)
        await asyncio.sleep(0.01)  # Time gap
        adapter.register("stream-2", ws2)
        
        segment = SpeechSegment(
            response_id="resp-1",
            position=0,
            audio_data=bytes(3200),
            audio_format=audio_format,
            is_last=False,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Send to both streams at same time
        await adapter.send_segment("stream-1", segment)
        await adapter.send_segment("stream-2", segment)
        
        # Extract timestamps
        msg1 = json.loads(ws1.send_text.call_args[0][0])
        msg2 = json.loads(ws2.send_text.call_args[0][0])
        
        ts1 = int(msg1["media"]["timestamp"])
        ts2 = int(msg2["media"]["timestamp"])
        
        # stream-1 was started before stream-2, so its timestamp should be larger
        # (showing more elapsed time)
        assert ts1 >= ts2
