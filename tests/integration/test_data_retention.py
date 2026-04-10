"""
Integration tests for data retention policy.
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from src.infrastructure.data_retention import DataRetentionPolicy


@pytest.mark.asyncio
class TestDataRetentionPolicy:
    """Test data retention policy functionality."""

    @pytest.fixture
    def retention_policy(self):
        """Create data retention policy instance."""
        return DataRetentionPolicy(
            db_url="postgresql://localhost/test",
            default_retention_days=90,
            audit_retention_days=365,
            session_retention_days=30,
        )

    @pytest.mark.asyncio
    async def test_initialization(self, retention_policy):
        """Test retention policy initialization."""
        assert retention_policy.default_retention_days == 90
        assert retention_policy.audit_retention_days == 365
        assert retention_policy.session_retention_days == 30

    @pytest.mark.asyncio
    async def test_initialize_tables(self, retention_policy):
        """Test table initialization."""
        with patch.object(retention_policy, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            await retention_policy.initialize()

            # Verify table creation
            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_set_retention_policy(self, retention_policy):
        """Test setting retention policy."""
        with patch.object(retention_policy, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            result = await retention_policy.set_retention_policy(
                data_type="call_logs",
                retention_days=60,
                anonymize_before_deletion=True,
            )

            assert result is True
            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_get_retention_policy(self, retention_policy):
        """Test getting retention policy."""
        with patch.object(retention_policy, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchone.return_value = (
                1,  # id
                "call_logs",  # data_type
                90,  # retention_days
                True,  # anonymize
                True,  # auto_delete
                None,  # last_deletion
                datetime.utcnow(),  # created_at
                datetime.utcnow(),  # updated_at
            )
            mock_result.description = [
                ("id",),
                ("data_type",),
                ("retention_days",),
                ("anonymize_before_deletion",),
                ("auto_delete",),
                ("last_deletion",),
                ("created_at",),
                ("updated_at",),
            ]

            policy = await retention_policy.get_retention_policy("call_logs")

            assert policy is not None

    @pytest.mark.asyncio
    async def test_delete_expired_data(self, retention_policy):
        """Test deleting expired data."""
        with patch.object(retention_policy, "get_retention_policy") as mock_get:
            with patch("psycopg.AsyncConnection.connect") as mock_connect:
                mock_conn = AsyncMock()
                mock_connect.return_value = mock_conn
                mock_conn.__aenter__.return_value = mock_conn
                mock_conn.__aexit__.return_value = None
                mock_conn.aclose = AsyncMock()

                mock_get.return_value = {
                    "retention_days": 30,
                    "anonymize_before_deletion": False,
                }

                count = await retention_policy.delete_expired_data("call_logs")

                assert count >= 0

    @pytest.mark.asyncio
    async def test_right_to_be_forgotten(self, retention_policy):
        """Test GDPR right to be forgotten."""
        with patch.object(retention_policy, "_get_connection") as mock_get_conn:
            mock_conn = AsyncMock()
            mock_get_conn.return_value.__aenter__.return_value = mock_conn
            mock_get_conn.return_value.__aexit__.return_value = None
            mock_conn.aclose = AsyncMock()

            result = await retention_policy.right_to_be_forgotten("user123")

            assert result is True
            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_right_to_be_forgotten_invalid_user(self, retention_policy):
        """Test right to be forgotten with invalid user."""
        with patch.object(retention_policy, "_get_connection") as mock_get_conn:
            mock_get_conn.side_effect = Exception("Connection error")

            result = await retention_policy.right_to_be_forgotten("invalid_user")

            assert result is False

    @pytest.mark.asyncio
    async def test_get_retention_status(self, retention_policy):
        """Test getting retention status."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_connect.return_value = mock_conn
            mock_conn.__aenter__.return_value = mock_conn
            mock_conn.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchall.return_value = []
            mock_result.description = []

            status = await retention_policy.get_retention_status()

            assert isinstance(status, dict)

    @pytest.mark.asyncio
    async def test_get_deletion_history(self, retention_policy):
        """Test getting deletion history."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_result = AsyncMock()

            mock_connect.return_value = mock_conn
            mock_conn.__aenter__.return_value = mock_conn
            mock_conn.__aexit__.return_value = None

            mock_conn.execute.return_value = mock_result
            mock_result.fetchall.return_value = []
            mock_result.description = []

            history = await retention_policy.get_deletion_history()

            assert isinstance(history, list)

    @pytest.mark.asyncio
    async def test_anonymize_data_call_logs(self, retention_policy):
        """Test anonymizing call logs."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn

            cutoff = datetime.utcnow() - timedelta(days=90)
            await retention_policy._anonymize_data(mock_conn, "call_logs", cutoff)

            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_anonymize_data_user_activity(self, retention_policy):
        """Test anonymizing user activity."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn

            cutoff = datetime.utcnow() - timedelta(days=90)
            await retention_policy._anonymize_data(mock_conn, "user_activity", cutoff)

            mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_log_deletion(self, retention_policy):
        """Test logging deletion event."""
        with patch("psycopg.AsyncConnection.connect") as mock_connect:
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn

            await retention_policy._log_deletion(
                mock_conn,
                "call_logs",
                100,
                "Test deletion",
                user_id="test_user",
            )

            mock_conn.execute.assert_called()
