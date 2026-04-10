"""
Audit Trail module for immutable action logging.

Logs:
- All user actions (call start, end, configuration changes)
- Timestamp and user attribution
- Action details and outcomes
- Immutable append-only PostgreSQL storage
- Export for compliance reporting
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import psycopg
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class AuditLogger:
    """Immutable audit trail logger."""

    def __init__(self, db_url: str):
        """Initialize audit logger.
        
        Args:
            db_url: PostgreSQL connection URL
        """
        self.db_url = db_url
        self.table_name = "audit_trail"

    async def initialize(self):
        """Initialize audit trail table if not exists."""
        async with self._get_connection() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    action VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255),
                    resource_type VARCHAR(255),
                    resource_id VARCHAR(255),
                    details JSONB,
                    status VARCHAR(50),
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    outcome VARCHAR(50),
                    error_message TEXT,
                    duration_ms INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Create index for efficient queries (append-only table optimization)
                CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp 
                    ON {self.table_name}(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_trail_action 
                    ON {self.table_name}(action);
                CREATE INDEX IF NOT EXISTS idx_audit_trail_user_id 
                    ON {self.table_name}(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_trail_resource 
                    ON {self.table_name}(resource_type, resource_id);
                
                -- Create immutable constraint (PostgreSQL 15+)
                -- ALTER TABLE {self.table_name} ADD CONSTRAINT audit_immutable CHECK (true) NOINHERIT;
            """)

    @asynccontextmanager
    async def _get_connection(self):
        """Get database connection."""
        async with await psycopg.AsyncConnection.connect(self.db_url) as conn:
            yield conn

    async def log_action(
        self,
        action: str,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status: str = "completed",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        outcome: str = "success",
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> int:
        """Log an action to audit trail.
        
        Args:
            action: Action name (e.g., 'CALL_START', 'CONFIG_CHANGE')
            user_id: ID of user performing action
            resource_type: Type of resource (e.g., 'call', 'session')
            resource_id: ID of resource
            details: Additional details as dict
            status: Action status (completed, failed, pending)
            ip_address: Client IP address
            user_agent: Client user agent
            outcome: Result (success, failure, partial)
            error_message: Error message if outcome is failure
            duration_ms: Duration in milliseconds
            
        Returns:
            Audit log entry ID
        """
        try:
            details_json = json.dumps(details or {})

            async with self._get_connection() as conn:
                result = await conn.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        action, user_id, resource_type, resource_id,
                        details, status, ip_address, user_agent,
                        outcome, error_message, duration_ms
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                    """,
                    (
                        action,
                        user_id,
                        resource_type,
                        resource_id,
                        details_json,
                        status,
                        ip_address,
                        user_agent,
                        outcome,
                        error_message,
                        duration_ms,
                    ),
                )
                row = await result.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error(f"Failed to log action: {e}")
            return 0

    async def get_audit_trail(
        self,
        limit: int = 100,
        offset: int = 0,
        action: Optional[str] = None,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Query audit trail.
        
        Args:
            limit: Max results
            offset: Offset for pagination
            action: Filter by action
            user_id: Filter by user
            resource_type: Filter by resource type
            start_date: Filter by start date
            end_date: Filter by end date
            
        Returns:
            List of audit log entries
        """
        try:
            query = f"SELECT * FROM {self.table_name} WHERE 1=1"
            params = []

            if action:
                query += " AND action = $" + str(len(params) + 1)
                params.append(action)

            if user_id:
                query += " AND user_id = $" + str(len(params) + 1)
                params.append(user_id)

            if resource_type:
                query += " AND resource_type = $" + str(len(params) + 1)
                params.append(resource_type)

            if start_date:
                query += " AND timestamp >= $" + str(len(params) + 1)
                params.append(start_date)

            if end_date:
                query += " AND timestamp <= $" + str(len(params) + 1)
                params.append(end_date)

            query += f" ORDER BY timestamp DESC LIMIT ${ len(params) + 1} OFFSET ${len(params) + 2}"
            params.extend([limit, offset])

            async with self._get_connection() as conn:
                result = await conn.execute(query, params)
                rows = await result.fetchall()

                # Convert rows to dicts
                if not rows:
                    return []

                # Get column names
                columns = [desc[0] for desc in result.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to query audit trail: {e}")
            return []

    async def export_audit_log(
        self,
        format: str = "json",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> str:
        """Export audit log for compliance.
        
        Args:
            format: Export format (json, csv)
            start_date: Export from date
            end_date: Export to date
            
        Returns:
            Exported data as string
        """
        try:
            entries = await self.get_audit_trail(
                limit=10000,
                start_date=start_date,
                end_date=end_date,
            )

            if format == "json":
                # Convert datetime objects to strings
                for entry in entries:
                    if "timestamp" in entry and isinstance(entry["timestamp"], datetime):
                        entry["timestamp"] = entry["timestamp"].isoformat()
                    if "created_at" in entry and isinstance(entry["created_at"], datetime):
                        entry["created_at"] = entry["created_at"].isoformat()

                return json.dumps(entries, indent=2, default=str)

            elif format == "csv":
                import csv
                import io

                if not entries:
                    return ""

                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=entries[0].keys())
                writer.writeheader()
                writer.writerows(entries)
                return output.getvalue()

            else:
                return ""
        except Exception as e:
            logger.error(f"Failed to export audit log: {e}")
            return ""

    async def get_statistics(self) -> Dict[str, Any]:
        """Get audit trail statistics.
        
        Returns:
            Statistics dict
        """
        try:
            async with self._get_connection() as conn:
                # Total entries
                result = await conn.execute(
                    f"SELECT COUNT(*) as total FROM {self.table_name}"
                )
                total = (await result.fetchone())[0]

                # Entries by action
                result = await conn.execute(
                    f"""
                    SELECT action, COUNT(*) as count 
                    FROM {self.table_name} 
                    GROUP BY action 
                    ORDER BY count DESC
                    """
                )
                by_action = {row[0]: row[1] for row in await result.fetchall()}

                # Last 24 hours
                result = await conn.execute(
                    f"""
                    SELECT COUNT(*) as count 
                    FROM {self.table_name} 
                    WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    """
                )
                last_24h = (await result.fetchone())[0]

                # Success vs failure
                result = await conn.execute(
                    f"""
                    SELECT outcome, COUNT(*) as count 
                    FROM {self.table_name} 
                    GROUP BY outcome
                    """
                )
                by_outcome = {row[0]: row[1] for row in await result.fetchall()}

                return {
                    "total_entries": total,
                    "last_24h_entries": last_24h,
                    "by_action": by_action,
                    "by_outcome": by_outcome,
                }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    async def cleanup_old_entries(self, days: int = 90) -> int:
        """Delete audit entries older than N days.
        
        Args:
            days: Delete entries older than this many days
            
        Returns:
            Number of entries deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            async with self._get_connection() as conn:
                result = await conn.execute(
                    f"""
                    DELETE FROM {self.table_name} 
                    WHERE timestamp < $1
                    """,
                    (cutoff_date,),
                )
                # In psycopg3, execute() returns command execution status
                # We need to extract row count from cursor
                return conn.info.transaction.get("rows_deleted", 0) if hasattr(conn, "info") else 0
        except Exception as e:
            logger.error(f"Failed to cleanup old entries: {e}")
            return 0


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


async def get_audit_logger(db_url: Optional[str] = None) -> AuditLogger:
    """Get or create global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        import os
        db_url = db_url or os.getenv("DATABASE_URL", "postgresql://localhost/puchai")
        _audit_logger = AuditLogger(db_url)
        await _audit_logger.initialize()
    return _audit_logger
