"""
Unit tests for audit logger.
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from src.infrastructure.audit_logger import AuditLogger


@pytest.mark.asyncio
class TestAuditLogger:
    """Test audit logger functionality."""

    @pytest.fixture
    def audit_logger(self):
        """Create audit logger instance."""
        return AuditLogger(db_url="postgresql://localhost/test")

    @pytest.mark.asyncio
    async def test_initialization(self, audit_logger):
        """Test audit logger initialization."""
        assert audit_logger.db_url == "postgresql://localhost/test"
        assert audit_logger.table_name == "audit_trail"

    @pytest.mark.asyncio
    async def test_audit_logger_initialization_creates_table(self, audit_logger):
        """Test audit logger table creation."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn
            mock_conn.__aenter__.return_value = mock_conn
            mock_conn.__aexit__.return_value = None

            await audit_logger.initialize()

            # Verify table creation
            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_log_action(self, audit_logger):
        """Test logging an action."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchone.return_value = (123,)

            result = await audit_logger.log_action(
                action="TEST_ACTION",
                user_id="user123",
                resource_type="call",
                resource_id="call456",
            )

            assert result == 123
            mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_action_with_details(self, audit_logger):
        """Test logging action with details."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchone.return_value = (456,)

            details = {"duration": 120, "status": "completed"}
            result = await audit_logger.log_action(
                action="CALL_END",
                user_id="user123",
                details=details,
                outcome="success",
            )

            assert result == 456

    @pytest.mark.asyncio
    async def test_get_audit_trail(self, audit_logger):
        """Test querying audit trail."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchall.return_value = []
            mock_result.description = [("id",), ("action",), ("timestamp",)]

            entries = await audit_logger.get_audit_trail(limit=10)

            assert entries == []

    @pytest.mark.asyncio
    async def test_get_audit_trail_with_filters(self, audit_logger):
        """Test querying audit trail with filters."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchall.return_value = []
            mock_result.description = [("id",), ("action",)]

            entries = await audit_logger.get_audit_trail(
                action="CALL_START",
                user_id="user123",
                resource_type="call",
            )

            assert entries == []

    @pytest.mark.asyncio
    async def test_export_audit_log_json(self, audit_logger):
        """Test exporting audit log as JSON."""
        with patch.object(audit_logger, "get_audit_trail") as mock_get:
            mock_get.return_value = [
                {
                    "id": 1,
                    "action": "TEST",
                    "timestamp": datetime.utcnow(),
                }
            ]

            result = await audit_logger.export_audit_log(format="json")

            assert "TEST" in result
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_export_audit_log_csv(self, audit_logger):
        """Test exporting audit log as CSV."""
        with patch.object(audit_logger, "get_audit_trail") as mock_get:
            mock_get.return_value = [
                {
                    "id": 1,
                    "action": "TEST",
                    "user_id": "user123",
                }
            ]

            result = await audit_logger.export_audit_log(format="csv")

            assert "id" in result
            assert "action" in result
            assert "TEST" in result

    @pytest.mark.asyncio
    async def test_get_statistics(self, audit_logger):
        """Test getting audit trail statistics."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchone.side_effect = [(100,), (50,), (25,)]
            mock_result.fetchall.side_effect = [
                [("CALL_START", 30), ("CALL_END", 20)],
                [("success", 75), ("failure", 25)],
            ]

            stats = await audit_logger.get_statistics()

            assert "total_entries" in stats
            assert stats["total_entries"] == 100

    @pytest.mark.asyncio
    async def test_cleanup_old_entries(self, audit_logger):
        """Test cleaning up old audit entries."""
        with patch.object(audit_logger, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = None
            mock_conn.info = None

            count = await audit_logger.cleanup_old_entries(days=90)

            assert count >= 0
