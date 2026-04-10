"""Health Checks — Liveness and readiness probes for Kubernetes orchestration.

Provides:
- Liveness probe: Is the process running?
- Readiness probe: Are dependencies (Redis, PostgreSQL) available?

Kubernetes will:
- Restart if liveness probe fails
- Remove from load balancer if readiness probe fails

Usage:
    health = HealthCheck()
    health.redis_client = redis_repo.redis_client
    health.db_conn = postgres_logger.db_pool
    
    # In FastAPI:
    @app.get("/health/live")
    async def liveness():
        status = await health.check_liveness()
        return status.to_dict()
    
    @app.get("/health/ready")
    async def readiness():
        status = await health.check_readiness()
        return status.to_dict()
"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health check status response."""
    check_type: str  # "liveness" or "readiness"
    is_alive: Optional[bool] = None  # For liveness
    is_ready: Optional[bool] = None  # For readiness
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    dependencies: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON response."""
        return {
            "check_type": self.check_type,
            "status": "healthy" if (self.is_alive or self.is_ready) else "unhealthy",
            "is_alive": self.is_alive,
            "is_ready": self.is_ready,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "dependencies": self.dependencies,
        }

    def get_summary(self) -> str:
        """Get human-readable summary."""
        status = "✅ HEALTHY" if (self.is_alive or self.is_ready) else "❌ UNHEALTHY"
        deps = ", ".join(
            f"{k}={'✅' if v else '❌'}" for k, v in self.dependencies.items()
        )
        return f"{status}: {self.message} [{deps}]"


class HealthCheck:
    """
    Kubernetes-compatible health checks for orchestration.

    Liveness probe:
    - Checks if process is running
    - Fast check, minimal dependencies
    - Restart pod if fails

    Readiness probe:
    - Checks external dependencies (Redis, DB)
    - More comprehensive
    - Remove from load balancer if fails
    """

    def __init__(self):
        """Initialize HealthCheck."""
        self.redis_client = None
        self.db_conn = None
        self.startup_time = datetime.now()

    async def check_liveness(self) -> HealthStatus:
        """
        Liveness probe - is the process running?

        Returns:
            HealthStatus with is_alive set
        """
        try:
            # Simple check: process is running
            # Could add memory/CPU limits here
            is_alive = True

            return HealthStatus(
                check_type="liveness",
                is_alive=is_alive,
                message="Process is running",
            )
        except Exception as e:
            logger.error(f"Liveness check failed: {e}")
            return HealthStatus(
                check_type="liveness",
                is_alive=False,
                message=f"Process check failed: {e}",
            )

    async def check_readiness(self) -> HealthStatus:
        """
        Readiness probe - are dependencies available?

        Returns:
            HealthStatus with is_ready set and dependencies listed
        """
        dependencies = {}

        # Check Redis
        redis_ok = await self.check_redis()
        dependencies["redis"] = redis_ok

        # Check Database
        db_ok = await self.check_database()
        dependencies["database"] = db_ok

        # Overall readiness
        is_ready = all(dependencies.values())

        message = (
            "All dependencies healthy"
            if is_ready
            else "One or more dependencies unavailable"
        )

        logger.info(f"Readiness check: {message} {dependencies}")

        return HealthStatus(
            check_type="readiness",
            is_ready=is_ready,
            message=message,
            dependencies=dependencies,
        )

    async def check_redis(self) -> bool:
        """
        Check Redis connection.

        Returns:
            True if Redis is reachable, False otherwise
        """
        if not self.redis_client:
            logger.debug("Redis client not configured")
            return True  # No Redis configured, so no failure

        try:
            await self.redis_client.ping()
            logger.debug("✅ Redis healthy")
            return True
        except Exception as e:
            logger.error(f"❌ Redis check failed: {e}")
            return False

    async def check_database(self) -> bool:
        """
        Check PostgreSQL connection.

        Returns:
            True if database is reachable, False otherwise
        """
        if not self.db_conn:
            logger.debug("Database connection not configured")
            return True  # No DB configured, so no failure

        try:
            async with self.db_conn.cursor() as cur:
                await cur.execute("SELECT 1")
            logger.debug("✅ Database healthy")
            return True
        except Exception as e:
            logger.error(f"❌ Database check failed: {e}")
            return False

    def get_uptime_seconds(self) -> float:
        """
        Get process uptime in seconds.

        Returns:
            Uptime in seconds
        """
        return (datetime.now() - self.startup_time).total_seconds()

    async def detailed_status(self) -> Dict:
        """
        Get detailed status for monitoring.

        Returns:
            Dict with detailed health information
        """
        liveness = await self.check_liveness()
        readiness = await self.check_readiness()

        return {
            "status": "healthy" if (liveness.is_alive and readiness.is_ready) else "unhealthy",
            "liveness": liveness.to_dict(),
            "readiness": readiness.to_dict(),
            "uptime_seconds": self.get_uptime_seconds(),
        }
