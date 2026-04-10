"""PostgresCallLogger — PostgreSQL-backed call logging for analytics and compliance.

Logs all calls with comprehensive metadata for analytics, compliance, and debugging.

Usage:
    logger = PostgresCallLogger(db_url="postgresql://localhost/exotel_db")
    await logger.connect()
    
    record = CallRecord(
        call_id=call_id,
        stream_sid=stream_sid,
        caller_id=caller_id,
        called_id=called_id,
        started_at=datetime.now(),
        duration_seconds=45,
        status="completed",
        total_utterances=3,
        total_api_calls=6,
        error_message=None,
    )
    await logger.log_call(record)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid

try:
    import psycopg
    from psycopg import AsyncConnection
except ImportError:
    AsyncConnection = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """Immutable record of a single call for logging."""
    call_id: str
    stream_sid: str
    caller_id: str
    called_id: str
    started_at: datetime
    duration_seconds: int
    status: str  # completed, timeout, error
    total_utterances: int
    total_api_calls: int
    error_message: Optional[str] = None


SCHEMA_SQL = """
-- Create calls table for logging all voice AI calls
CREATE TABLE IF NOT EXISTS calls (
    call_id UUID PRIMARY KEY,
    stream_sid VARCHAR(256) NOT NULL,
    caller_id VARCHAR(256),
    called_id VARCHAR(256),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    status VARCHAR(50) NOT NULL,
    total_utterances INTEGER DEFAULT 0,
    total_api_calls INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_stream_sid ON calls(stream_sid);
CREATE INDEX IF NOT EXISTS idx_started_at ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_caller_id ON calls(caller_id);
"""


class PostgresCallLogger:
    """
    PostgreSQL-backed call logger for production deployments.

    Persists comprehensive call metadata for:
    - Analytics (call counts, durations, success rates)
    - Compliance (audit trails, call records)
    - Debugging (error logs, performance analysis)

    Connection pooling: Uses connection pooling for efficiency.
    Graceful degradation: Continues operating if DB is temporarily unavailable.
    """

    def __init__(self, db_url: str = "postgresql://localhost/exotel_db"):
        """
        Initialize PostgreSQL call logger.

        Args:
            db_url: PostgreSQL connection URL (default: localhost)
        """
        self.db_url = db_url
        self.db_pool: Optional[AsyncConnection] = None

    async def connect(self) -> None:
        """
        Establish connection to PostgreSQL.

        Should be called during application startup (lifespan).
        """
        try:
            self.db_pool = await psycopg.AsyncConnection.connect(self.db_url)
            await self._initialize_schema()
            logger.info("✅ PostgreSQL connected: %s", self.db_url)
        except Exception as e:
            logger.error("❌ PostgreSQL connection failed: %s", e)
            raise

    async def disconnect(self) -> None:
        """
        Close PostgreSQL connection.

        Should be called during application shutdown (lifespan).
        """
        if self.db_pool:
            await self.db_pool.close()
            logger.info("✅ PostgreSQL disconnected")

    async def _initialize_schema(self) -> None:
        """Initialize database schema on startup."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute(SCHEMA_SQL)
            await self.db_pool.commit()
            logger.info("✅ Database schema initialized")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            await self.db_pool.rollback()
            raise

    async def log_call(self, record: CallRecord) -> None:
        """
        Log a completed call to the database.

        Args:
            record: CallRecord with all call metadata

        Raises:
            Exception: If database write fails
        """
        if not self.db_pool:
            logger.warning("⚠️ PostgreSQL not connected, skipping call log")
            return

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute("""
                    INSERT INTO calls (
                        call_id, stream_sid, caller_id, called_id,
                        started_at, ended_at, duration_seconds,
                        status, total_utterances, total_api_calls, error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    uuid.UUID(record.call_id),
                    record.stream_sid,
                    record.caller_id,
                    record.called_id,
                    record.started_at,
                    datetime.now(),  # ended_at
                    record.duration_seconds,
                    record.status,
                    record.total_utterances,
                    record.total_api_calls,
                    record.error_message,
                ))
            await self.db_pool.commit()
            logger.debug(f"✅ Call logged: {record.call_id[:8]}...")
        except Exception as e:
            logger.error(f"❌ Failed to log call {record.call_id}: {e}")
            await self.db_pool.rollback()
            raise

    async def get_calls_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query calls within a date range.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            status: Optional filter by status (completed, error, timeout)

        Returns:
            List of call records
        """
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.cursor() as cur:
                query = """
                    SELECT * FROM calls
                    WHERE started_at >= %s AND started_at <= %s
                """
                params = [start_date, end_date]

                if status:
                    query += " AND status = %s"
                    params.append(status)

                query += " ORDER BY started_at DESC"

                await cur.execute(query, params)
                rows = await cur.fetchall()

                # Convert to list of dicts
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to query calls: {e}")
            return []

    async def find_by_stream_sid(self, stream_sid: str) -> List[Dict[str, Any]]:
        """
        Find all calls for a specific stream.

        Useful for debugging individual conversations.

        Args:
            stream_sid: Exotel stream identifier

        Returns:
            List of calls for this stream
        """
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM calls WHERE stream_sid = %s ORDER BY started_at DESC",
                    (stream_sid,)
                )
                rows = await cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to find calls by stream_sid: {e}")
            return []

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Retrieve overall call statistics.

        Returns:
            Dict with total_calls, completed_calls, avg_duration, etc.
        """
        if not self.db_pool:
            return {}

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute("""
                    SELECT
                        COUNT(*) as total_calls,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_calls,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_calls,
                        SUM(CASE WHEN status = 'timeout' THEN 1 ELSE 0 END) as timeout_calls,
                        COALESCE(AVG(duration_seconds), 0) as avg_duration_seconds,
                        COALESCE(MAX(duration_seconds), 0) as max_duration_seconds,
                        COALESCE(SUM(duration_seconds), 0) as total_duration_seconds,
                        COALESCE(AVG(total_utterances), 0) as avg_utterances,
                        COALESCE(AVG(total_api_calls), 0) as avg_api_calls
                    FROM calls
                """)
                row = await cur.fetchone()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row)) if row else {}
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    async def get_daily_stats(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Retrieve daily aggregated statistics.

        Useful for dashboards and reports.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of daily statistics
        """
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute("""
                    SELECT
                        DATE(started_at) as date,
                        COUNT(*) as call_count,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_count,
                        AVG(duration_seconds) as avg_duration,
                        AVG(total_utterances) as avg_utterances,
                        AVG(total_api_calls) as avg_api_calls
                    FROM calls
                    WHERE started_at >= %s AND started_at <= %s
                    GROUP BY DATE(started_at)
                    ORDER BY DATE(started_at) DESC
                """, (start_date, end_date))
                rows = await cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return []

    async def health_check(self) -> bool:
        """
        Health check for PostgreSQL connection.

        Returns:
            True if PostgreSQL is reachable, False otherwise
        """
        if not self.db_pool:
            return False

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
            return True
        except Exception:
            return False

    async def get_error_summary(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get summary of errors in the last N days.

        Useful for monitoring and alerting.

        Args:
            days: Number of days to look back

        Returns:
            List of error counts by error message
        """
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.cursor() as cur:
                await cur.execute("""
                    SELECT
                        error_message,
                        COUNT(*) as count,
                        DATE(started_at) as date
                    FROM calls
                    WHERE status = 'error'
                    AND started_at >= NOW() - INTERVAL '%s days'
                    GROUP BY error_message, DATE(started_at)
                    ORDER BY count DESC
                """, (days,))
                rows = await cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get error summary: {e}")
            return []
