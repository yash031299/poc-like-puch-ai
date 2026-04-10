"""Health Check Tests.

Tests for liveness and readiness probes:
- Liveness: Is process running?
- Readiness: Are dependencies (Redis, DB) available?
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.infrastructure.health import HealthCheck, HealthStatus


@pytest.fixture
def health_check():
    """Fixture providing HealthCheck."""
    return HealthCheck()


@pytest.mark.asyncio
async def test_health_liveness(health_check):
    """Test liveness probe."""
    status = await health_check.check_liveness()
    
    assert status.is_alive is True
    assert status.check_type == "liveness"


@pytest.mark.asyncio
async def test_health_readiness_no_dependencies(health_check):
    """Test readiness probe with no dependencies."""
    status = await health_check.check_readiness()
    
    # With no dependencies, should be ready
    assert status.is_ready is True
    assert status.check_type == "readiness"


@pytest.mark.asyncio
async def test_health_check_redis(health_check):
    """Test Redis health check."""
    # Mock Redis client
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(return_value=True)
    
    health_check.redis_client = redis_client
    
    is_healthy = await health_check.check_redis()
    
    assert is_healthy is True
    redis_client.ping.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_redis_failure(health_check):
    """Test Redis failure detection."""
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
    
    health_check.redis_client = redis_client
    
    is_healthy = await health_check.check_redis()
    
    assert is_healthy is False


@pytest.mark.asyncio
async def test_health_check_database(health_check):
    """Test database health check."""
    # Mock DB connection
    db_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.execute = AsyncMock()
    
    db_conn.cursor = MagicMock()
    db_conn.cursor.return_value = mock_cursor
    
    health_check.db_conn = db_conn
    
    is_healthy = await health_check.check_database()
    
    assert is_healthy is True


@pytest.mark.asyncio
async def test_health_check_database_failure(health_check):
    """Test database failure detection."""
    db_conn = AsyncMock()
    db_conn.cursor = MagicMock(side_effect=Exception("DB connection failed"))
    
    health_check.db_conn = db_conn
    
    is_healthy = await health_check.check_database()
    
    assert is_healthy is False


def test_health_status_structure():
    """Test HealthStatus dataclass structure."""
    status = HealthStatus(
        check_type="liveness",
        is_alive=True,
        is_ready=True,
        message="All systems operational"
    )
    
    assert status.check_type == "liveness"
    assert status.is_alive is True
    assert status.message == "All systems operational"


def test_health_check_to_dict():
    """Test converting health status to dict."""
    status = HealthStatus(
        check_type="readiness",
        is_alive=True,
        is_ready=True,
        message="Ready",
        dependencies={"redis": True, "database": True}
    )
    
    status_dict = status.to_dict()
    
    assert status_dict["check_type"] == "readiness"
    assert status_dict["dependencies"]["redis"] is True


@pytest.mark.asyncio
async def test_health_readiness_with_redis(health_check):
    """Test readiness with Redis dependency."""
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(return_value=True)
    health_check.redis_client = redis_client
    
    status = await health_check.check_readiness()
    
    assert status.is_ready is True
    assert status.dependencies.get("redis") is True


@pytest.mark.asyncio
async def test_health_readiness_redis_down(health_check):
    """Test readiness with Redis down."""
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
    health_check.redis_client = redis_client
    
    status = await health_check.check_readiness()
    
    # Should report not ready
    assert status.dependencies.get("redis") is False


@pytest.mark.asyncio
async def test_health_multiple_dependency_checks(health_check):
    """Test readiness with multiple dependencies."""
    # Mock Redis
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(return_value=True)
    health_check.redis_client = redis_client
    
    # Mock DB
    db_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    
    db_conn.cursor = MagicMock(return_value=mock_cursor)
    health_check.db_conn = db_conn
    
    status = await health_check.check_readiness()
    
    assert status.is_ready is True
    assert status.dependencies.get("redis") is True
    assert status.dependencies.get("database") is True


def test_health_status_summary():
    """Test health status summary message."""
    status = HealthStatus(
        check_type="readiness",
        is_ready=False,
        message="Database unavailable",
        dependencies={"redis": True, "database": False}
    )
    
    summary = status.get_summary()
    assert "Database unavailable" in summary or len(summary) > 0


def test_health_check_initialization():
    """Test HealthCheck initialization."""
    health = HealthCheck()
    
    assert health.redis_client is None
    assert health.db_conn is None


@pytest.mark.asyncio
async def test_health_response_format(health_check):
    """Test health check response format."""
    status = await health_check.check_liveness()
    
    # Should have required fields
    assert hasattr(status, "check_type")
    assert hasattr(status, "is_alive")
    assert hasattr(status, "timestamp")
    assert hasattr(status, "message")
