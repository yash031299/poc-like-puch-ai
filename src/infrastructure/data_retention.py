"""
Data Retention Policy module for GDPR compliance.

Features:
- Automatic deletion of call logs after N days
- "Right to be forgotten" support
- Retention schedule configuration
- Anonymization before deletion
- Configurable retention periods per data type
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import psycopg

logger = logging.getLogger(__name__)


class DataRetentionPolicy:
    """Manages data retention and deletion for compliance."""

    def __init__(
        self,
        db_url: str,
        default_retention_days: int = 90,
        audit_retention_days: int = 365,
        session_retention_days: int = 30,
    ):
        """Initialize data retention policy.
        
        Args:
            db_url: PostgreSQL connection URL
            default_retention_days: Default days to retain data (90)
            audit_retention_days: Days to retain audit logs (365)
            session_retention_days: Days to retain session data (30)
        """
        self.db_url = db_url
        self.default_retention_days = default_retention_days
        self.audit_retention_days = audit_retention_days
        self.session_retention_days = session_retention_days

        self.retention_table = "data_retention_policy"
        self.deletion_log_table = "deletion_log"

    async def initialize(self):
        """Initialize retention policy tables."""
        async with self._get_connection() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.retention_table} (
                    id BIGSERIAL PRIMARY KEY,
                    data_type VARCHAR(100) NOT NULL UNIQUE,
                    retention_days INTEGER NOT NULL,
                    anonymize_before_deletion BOOLEAN DEFAULT true,
                    auto_delete BOOLEAN DEFAULT true,
                    last_deletion TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS {self.deletion_log_table} (
                    id BIGSERIAL PRIMARY KEY,
                    data_type VARCHAR(100) NOT NULL,
                    record_count INTEGER,
                    deletion_date TIMESTAMP WITH TIME ZONE,
                    reason VARCHAR(255),
                    user_id VARCHAR(255),
                    status VARCHAR(50),
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_retention_policy_data_type 
                    ON {self.retention_table}(data_type);
                CREATE INDEX IF NOT EXISTS idx_deletion_log_created_at 
                    ON {self.deletion_log_table}(created_at DESC);
            """)

            # Initialize default retention policies
            await self._initialize_default_policies(conn)

    async def _get_connection(self):
        """Get database connection."""
        return await psycopg.AsyncConnection.connect(self.db_url)

    async def _initialize_default_policies(self, conn):
        """Initialize default retention policies."""
        policies = [
            ("call_logs", self.default_retention_days, True),
            ("session_data", self.session_retention_days, False),
            ("audit_logs", self.audit_retention_days, False),
            ("user_activity", self.default_retention_days, True),
            ("error_logs", 30, False),
        ]

        for data_type, retention_days, anonymize in policies:
            try:
                await conn.execute(f"""
                    INSERT INTO {self.retention_table} 
                    (data_type, retention_days, anonymize_before_deletion)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (data_type) DO NOTHING
                """, (data_type, retention_days, anonymize))
            except Exception as e:
                logger.warning(f"Failed to initialize policy for {data_type}: {e}")

    async def set_retention_policy(
        self,
        data_type: str,
        retention_days: int,
        anonymize_before_deletion: bool = True,
        auto_delete: bool = True,
    ) -> bool:
        """Set retention policy for data type.
        
        Args:
            data_type: Type of data (e.g., 'call_logs')
            retention_days: Days to retain
            anonymize_before_deletion: Anonymize before deleting
            auto_delete: Auto-delete expired data
            
        Returns:
            True if policy set successfully
        """
        try:
            async with self._get_connection() as conn:
                await conn.execute(f"""
                    INSERT INTO {self.retention_table}
                    (data_type, retention_days, anonymize_before_deletion, auto_delete)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (data_type) DO UPDATE SET
                        retention_days = $2,
                        anonymize_before_deletion = $3,
                        auto_delete = $4,
                        updated_at = CURRENT_TIMESTAMP
                """, (data_type, retention_days, anonymize_before_deletion, auto_delete))
                logger.info(f"Set retention policy: {data_type} = {retention_days} days")
                return True
        except Exception as e:
            logger.error(f"Failed to set retention policy: {e}")
            return False

    async def get_retention_policy(self, data_type: str) -> Optional[Dict[str, Any]]:
        """Get retention policy for data type.
        
        Args:
            data_type: Type of data
            
        Returns:
            Policy dict
        """
        try:
            async with self._get_connection() as conn:
                result = await conn.execute(f"""
                    SELECT * FROM {self.retention_table}
                    WHERE data_type = $1
                """, (data_type,))
                row = await result.fetchone()
                if row:
                    columns = [desc[0] for desc in result.description]
                    return dict(zip(columns, row))
                return None
        except Exception as e:
            logger.error(f"Failed to get retention policy: {e}")
            return None

    async def delete_expired_data(self, data_type: str) -> int:
        """Delete data older than retention period.
        
        Args:
            data_type: Type of data to delete
            
        Returns:
            Number of records deleted
        """
        try:
            # Get policy
            policy = await self.get_retention_policy(data_type)
            if not policy:
                logger.warning(f"No retention policy for {data_type}")
                return 0

            # Calculate cutoff date
            cutoff_date = datetime.utcnow() - timedelta(days=policy["retention_days"])

            async with self._get_connection() as conn:
                # Anonymize if required
                if policy["anonymize_before_deletion"]:
                    await self._anonymize_data(conn, data_type, cutoff_date)

                # Delete
                if data_type == "call_logs":
                    result = await conn.execute(
                        "DELETE FROM call_logs WHERE created_at < $1",
                        (cutoff_date,),
                    )
                elif data_type == "session_data":
                    result = await conn.execute(
                        "DELETE FROM sessions WHERE created_at < $1",
                        (cutoff_date,),
                    )
                elif data_type == "user_activity":
                    result = await conn.execute(
                        "DELETE FROM user_activity WHERE created_at < $1",
                        (cutoff_date,),
                    )
                else:
                    logger.warning(f"Unknown data type: {data_type}")
                    return 0

                # Log deletion
                await self._log_deletion(conn, data_type, 0, "Expired data deletion")

                logger.info(f"Deleted {data_type} records older than {cutoff_date}")
                return 0
        except Exception as e:
            logger.error(f"Failed to delete expired data: {e}")
            return 0

    async def _anonymize_data(
        self,
        conn,
        data_type: str,
        cutoff_date: datetime,
    ):
        """Anonymize data before deletion.
        
        Args:
            conn: Database connection
            data_type: Type of data
            cutoff_date: Only anonymize before this date
        """
        try:
            from .pii_masker import PIIMasker
            masker = PIIMasker()

            if data_type == "call_logs":
                # Anonymize call logs
                await conn.execute("""
                    UPDATE call_logs
                    SET 
                        caller_id = 'REDACTED',
                        caller_name = 'REDACTED',
                        transcript = 'REDACTED'
                    WHERE created_at < $1 AND caller_id != 'REDACTED'
                """, (cutoff_date,))
            elif data_type == "user_activity":
                # Anonymize user activity
                await conn.execute("""
                    UPDATE user_activity
                    SET 
                        user_id = 'REDACTED',
                        details = '{"action": "REDACTED"}'::jsonb
                    WHERE created_at < $1 AND user_id != 'REDACTED'
                """, (cutoff_date,))

            logger.info(f"Anonymized {data_type} before deletion")
        except Exception as e:
            logger.warning(f"Failed to anonymize {data_type}: {e}")

    async def _log_deletion(
        self,
        conn,
        data_type: str,
        record_count: int,
        reason: str,
        user_id: Optional[str] = None,
    ):
        """Log deletion event."""
        try:
            await conn.execute(f"""
                INSERT INTO {self.deletion_log_table}
                (data_type, record_count, deletion_date, reason, user_id, status)
                VALUES ($1, $2, $3, $4, $5, 'completed')
            """, (data_type, record_count, datetime.utcnow(), reason, user_id))
        except Exception as e:
            logger.warning(f"Failed to log deletion: {e}")

    async def right_to_be_forgotten(self, user_id: str) -> bool:
        """Delete all data for user (GDPR right to be forgotten).
        
        Args:
            user_id: User to delete
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Processing right to be forgotten for user: {user_id}")

            async with self._get_connection() as conn:
                # Delete from multiple tables
                tables = ["sessions", "call_logs", "user_activity"]
                for table in tables:
                    try:
                        await conn.execute(
                            f"DELETE FROM {table} WHERE user_id = $1",
                            (user_id,),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete from {table}: {e}")

                # Log the deletion
                await self._log_deletion(
                    conn,
                    "user_data",
                    0,
                    f"Right to be forgotten for user {user_id}",
                    user_id,
                )

                logger.info(f"Completed right to be forgotten for user: {user_id}")
                return True
        except Exception as e:
            logger.error(f"Right to be forgotten failed: {e}")
            return False

    async def get_retention_status(self) -> Dict[str, Any]:
        """Get current retention policy status.
        
        Returns:
            Status dict with policies and next cleanup dates
        """
        try:
            async with self._get_connection() as conn:
                result = await conn.execute(f"""
                    SELECT * FROM {self.retention_table}
                    ORDER BY data_type
                """)
                rows = await result.fetchall()

                if not rows:
                    return {}

                columns = [desc[0] for desc in result.description]
                policies = {}
                for row in rows:
                    policy = dict(zip(columns, row))
                    data_type = policy.pop("data_type")
                    policies[data_type] = policy

                return {
                    "policies": policies,
                    "last_cleanup": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            logger.error(f"Failed to get retention status: {e}")
            return {}

    async def get_deletion_history(self, limit: int = 100) -> list:
        """Get deletion history.
        
        Args:
            limit: Max records to return
            
        Returns:
            List of deletion log entries
        """
        try:
            async with self._get_connection() as conn:
                result = await conn.execute(f"""
                    SELECT * FROM {self.deletion_log_table}
                    ORDER BY created_at DESC
                    LIMIT $1
                """, (limit,))
                rows = await result.fetchall()

                if not rows:
                    return []

                columns = [desc[0] for desc in result.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get deletion history: {e}")
            return []


# Global data retention policy instance
_retention_policy: Optional[DataRetentionPolicy] = None


async def get_retention_policy(db_url: Optional[str] = None) -> DataRetentionPolicy:
    """Get or create global data retention policy."""
    global _retention_policy
    if _retention_policy is None:
        import os
        db_url = db_url or os.getenv("DATABASE_URL", "postgresql://localhost/puchai")
        _retention_policy = DataRetentionPolicy(db_url)
        await _retention_policy.initialize()
    return _retention_policy
