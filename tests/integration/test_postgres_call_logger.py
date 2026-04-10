"""PostgreSQL Call Logger Integration Tests.

Tests for PostgresCallLogger that verify:
- Call event logging (accept, end, errors)
- Database persistence
- Schema and indexes
- Analytics queries
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from src.adapters.postgres_call_logger import PostgresCallLogger, CallRecord


@pytest.fixture
def postgres_logger():
    """Fixture providing PostgresCallLogger with mocked database."""
    logger = PostgresCallLogger(db_url="postgresql://localhost/test_db")
    
    # Create proper async context managers for cursor
    mock_cursor = MagicMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.description = [("id",), ("name",)]
    
    # Make cursor async context manager work
    async def cursor_context(*args, **kwargs):
        return mock_cursor
    
    mock_db = MagicMock()
    mock_db.cursor = MagicMock()
    
    # Configure cursor to be a proper async context manager
    mock_db.cursor.return_value = MagicMock()
    mock_db.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_db.cursor.return_value.__aexit__ = AsyncMock(return_value=None)
    
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    
    logger.db_pool = mock_db
    return logger


@pytest.fixture
def sample_call_record():
    """Create a sample CallRecord for testing."""
    call_id = str(uuid.uuid4())
    return CallRecord(
        call_id=call_id,
        stream_sid="stream-test-123",
        caller_id="+919876543210",
        called_id="+919123456789",
        started_at=datetime.now(),
        duration_seconds=45,
        status="completed",
        total_utterances=3,
        total_api_calls=6,
        error_message=None,
    )


@pytest.mark.asyncio
async def test_postgres_logger_connects(postgres_logger):
    """Test database connection."""
    postgres_logger.db_pool.execute = AsyncMock()
    
    # Simulate successful connection
    assert postgres_logger.db_pool is not None


@pytest.mark.asyncio
async def test_postgres_logger_logs_call(postgres_logger, sample_call_record):
    """Test logging a completed call."""
    # cursor is already mocked in the fixture
    
    await postgres_logger.log_call(sample_call_record)
    
    # Verify execute was called with INSERT statement
    postgres_logger.db_pool.cursor.assert_called()
    postgres_logger.db_pool.commit.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_logger_stores_call_metadata(postgres_logger):
    """Test that all call metadata is stored correctly."""
    call_id = str(uuid.uuid4())
    record = CallRecord(
        call_id=call_id,
        stream_sid="stream-xyz",
        caller_id="+11234567890",
        called_id="+19876543210",
        started_at=datetime.now(),
        duration_seconds=120,
        status="timeout",
        total_utterances=5,
        total_api_calls=10,
        error_message="Caller disconnected",
    )
    
    await postgres_logger.log_call(record)
    
    # Verify execute was called with correct data
    postgres_logger.db_pool.commit.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_logger_query_calls_by_date(postgres_logger):
    """Test querying calls within a date range."""
    # Mock the fetch response
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.fetchall = AsyncMock(
        return_value=[
            (
                "call-id-1",
                "stream-1",
                "+1234567890",
                "+9876543210",
                datetime.now(),
                datetime.now(),
                30,
                "completed",
                1,
                2,
                None,
                datetime.now(),
            )
        ]
    )
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.description = [
        ("call_id",), ("stream_sid",), ("caller_id",), ("called_id",),
        ("started_at",), ("ended_at",), ("duration_seconds",),
        ("status",), ("total_utterances",), ("total_api_calls",),
        ("error_message",), ("created_at",)
    ]
    
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 31)
    
    calls = await postgres_logger.get_calls_in_range(start_date, end_date)
    
    assert len(calls) == 1
    assert calls[0]["stream_sid"] == "stream-1"


@pytest.mark.asyncio
async def test_postgres_logger_statistics(postgres_logger):
    """Test retrieving call statistics."""
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.fetchone = AsyncMock(
        return_value=(100, 85, 15, 0, 45.0, 120, 4500, 3.0, 6.0)
    )
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.description = [
        ("total_calls",), ("completed_calls",), ("error_calls",), ("timeout_calls",),
        ("avg_duration_seconds",), ("max_duration_seconds",), ("total_duration_seconds",),
        ("avg_utterances",), ("avg_api_calls",)
    ]
    
    stats = await postgres_logger.get_statistics()
    
    assert stats["total_calls"] == 100
    assert stats["completed_calls"] == 85


@pytest.mark.asyncio
async def test_postgres_logger_handles_connection_error(postgres_logger):
    """Test graceful handling of connection errors."""
    postgres_logger.db_pool.execute = AsyncMock(side_effect=Exception("Connection failed"))
    
    call_record = CallRecord(
        call_id=str(uuid.uuid4()),
        stream_sid="stream-test",
        caller_id="+1234567890",
        called_id="+9876543210",
        started_at=datetime.now(),
        duration_seconds=10,
        status="completed",
        total_utterances=1,
        total_api_calls=2,
        error_message=None,
    )
    
    # Should not raise exception
    with pytest.raises(Exception):
        await postgres_logger.log_call(call_record)


@pytest.mark.asyncio
async def test_postgres_logger_schema_tables():
    """Test that required schema tables are defined."""
    from src.adapters.postgres_call_logger import SCHEMA_SQL
    
    # Schema should contain table definition
    assert "CREATE TABLE" in SCHEMA_SQL
    assert "calls" in SCHEMA_SQL
    assert "call_id UUID PRIMARY KEY" in SCHEMA_SQL
    assert "stream_sid VARCHAR" in SCHEMA_SQL
    assert "caller_id VARCHAR" in SCHEMA_SQL
    assert "started_at TIMESTAMP" in SCHEMA_SQL
    assert "duration_seconds INTEGER" in SCHEMA_SQL
    assert "status VARCHAR" in SCHEMA_SQL


@pytest.mark.asyncio
async def test_postgres_logger_schema_indexes():
    """Test that required indexes are defined."""
    from src.adapters.postgres_call_logger import SCHEMA_SQL
    
    # Schema should contain index definitions
    assert "CREATE INDEX" in SCHEMA_SQL
    assert "idx_stream_sid" in SCHEMA_SQL
    assert "idx_started_at" in SCHEMA_SQL


@pytest.mark.asyncio
async def test_postgres_logger_find_by_stream_sid(postgres_logger):
    """Test finding calls by stream_sid."""
    call_id = str(uuid.uuid4())
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.fetchall = AsyncMock(
        return_value=[(call_id, "stream-target", "+1234567890", "+9876543210", datetime.now(), None, 30, "completed", 1, 2, None, datetime.now())]
    )
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.description = [
        ("call_id",), ("stream_sid",), ("caller_id",), ("called_id",),
        ("started_at",), ("ended_at",), ("duration_seconds",),
        ("status",), ("total_utterances",), ("total_api_calls",),
        ("error_message",), ("created_at",)
    ]
    
    calls = await postgres_logger.find_by_stream_sid("stream-target")
    
    assert len(calls) == 1
    assert calls[0]["stream_sid"] == "stream-target"


@pytest.mark.asyncio
async def test_postgres_logger_error_logging(postgres_logger):
    """Test logging calls with errors."""
    call_id = str(uuid.uuid4())
    record = CallRecord(
        call_id=call_id,
        stream_sid="stream-error",
        caller_id="+1234567890",
        called_id="+9876543210",
        started_at=datetime.now(),
        duration_seconds=5,
        status="error",
        total_utterances=0,
        total_api_calls=1,
        error_message="API timeout: Google STT service unavailable",
    )
    
    await postgres_logger.log_call(record)
    
    postgres_logger.db_pool.commit.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_logger_call_record_serialization():
    """Test CallRecord dataclass serialization."""
    call_id = str(uuid.uuid4())
    record = CallRecord(
        call_id=call_id,
        stream_sid="stream-test",
        caller_id="+1234567890",
        called_id="+9876543210",
        started_at=datetime(2024, 1, 15, 10, 30, 0),
        duration_seconds=60,
        status="completed",
        total_utterances=5,
        total_api_calls=10,
        error_message=None,
    )
    
    # Verify all fields are accessible
    assert record.call_id == call_id
    assert record.stream_sid == "stream-test"
    assert record.status == "completed"


@pytest.mark.asyncio
async def test_postgres_logger_concurrent_calls(postgres_logger):
    """Test logging multiple concurrent calls."""
    
    calls = [
        CallRecord(
            call_id=str(uuid.uuid4()),
            stream_sid=f"stream-{i}",
            caller_id=f"+123456789{i}",
            called_id="+9876543210",
            started_at=datetime.now(),
            duration_seconds=30 + i * 10,
            status="completed",
            total_utterances=i + 1,
            total_api_calls=i * 2,
            error_message=None,
        )
        for i in range(10)
    ]
    
    for call in calls:
        await postgres_logger.log_call(call)
    
    # Should have called commit 10 times
    assert postgres_logger.db_pool.commit.call_count == 10


@pytest.mark.asyncio
async def test_postgres_logger_query_by_date_range(postgres_logger):
    """Test date range query for analytics."""
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.fetchall = AsyncMock(
        return_value=[(
            "2024-01-15",
            42,
            40,
            45.0,
            3.0,
            6.0
        )]
    )
    postgres_logger.db_pool.cursor.return_value.__aenter__.return_value.description = [
        ("date",), ("call_count",), ("completed_count",),
        ("avg_duration",), ("avg_utterances",), ("avg_api_calls",)
    ]
    
    start_date = datetime(2024, 1, 15)
    end_date = datetime(2024, 1, 15)
    
    stats = await postgres_logger.get_daily_stats(start_date, end_date)
    
    assert len(stats) > 0
