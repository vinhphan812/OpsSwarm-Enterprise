"""Issue #70 — HA Coordination (ADR-030).

This module provides PostgreSQL-backed coordination for high-availability
multi-process deployments. When disabled (ha.enabled = false), the
functions in this module are no-ops and the system falls back to
in-memory behavior.

Environment variables
---------------------
HA_DATABASE_URL    PostgreSQL connection string (psycopg2 format).
                   Only used when ha.enabled = true.

Example:
    HA_DATABASE_URL=postgresql://user:pass@localhost:5432/opsswarm
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncGenerator, Optional

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .config import get_ha

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Instance identification
# ----------------------------------------------------------------------

# Process-unique instance ID generated at startup. Used for lease ownership.
_INSTANCE_ID: str | None = None


def get_instance_id() -> str:
    """Return this process's unique instance ID.
    
    Generated once at startup and persisted for the lifetime of the process.
    Used to identify which process owns run leases.
    """
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        # Try to load from env (for testing) first
        _INSTANCE_ID = os.environ.get("HA_INSTANCE_ID") or str(uuid.uuid4())
        logger.info("HA instance ID: %s", _INSTANCE_ID)
    return _INSTANCE_ID


def reset_instance_id() -> None:
    """Reset instance ID. For testing only."""
    global _INSTANCE_ID
    _INSTANCE_ID = None


# ----------------------------------------------------------------------
# Database connection pool
# ----------------------------------------------------------------------

# Lazy-initialized async connection pool
_connection_pool: asyncio.Queue[AsyncConnection] | None = None
_pool_size = 5


async def _create_pool(database_url: str) -> asyncio.Queue[AsyncConnection]:
    """Create a pool of async PostgreSQL connections."""
    global _connection_pool
    if _connection_pool is not None:
        return _connection_pool

    pool = asyncio.Queue(maxsize=_pool_size)
    for _ in range(_pool_size):
        conn = await AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
            autocommit=False,
        )
        await pool.put(conn)
    _connection_pool = pool
    logger.info("Created HA database connection pool (size=%d)", _pool_size)
    return pool


async def _get_connection() -> AsyncConnection:
    """Get a connection from the pool."""
    global _connection_pool
    cfg = get_ha({})  # Use empty dict to get defaults
    if not cfg.get("enabled") or not cfg.get("database_url"):
        raise RuntimeError("HA is not enabled or database_url not set")

    if _connection_pool is None:
        await _create_pool(cfg["database_url"])
    
    # Wait for a connection with timeout
    try:
        conn = await asyncio.wait_for(_connection_pool.get(), timeout=5.0)
    except asyncio.TimeoutError:
        raise RuntimeError("Timeout waiting for database connection")

    # Check if connection is still alive
    if conn.closed:
        # Reconnect
        cfg = get_ha({})
        conn = await AsyncConnection.connect(
            cfg["database_url"],
            row_factory=dict_row,
            autocommit=False,
        )
    
    return conn


async def _return_connection(conn: AsyncConnection) -> None:
    """Return a connection to the pool."""
    global _connection_pool
    if _connection_pool is not None and not conn.closed:
        await _connection_pool.put(conn)


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """Context manager for database operations.
    
    Yields an async connection from the pool. The connection is automatically
    returned to the pool on exit.
    
    Example:
        async with get_db() as conn:
            await conn.execute("SELECT 1")
    """
    conn = await _get_connection()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await _return_connection(conn)


async def close_db_pool() -> None:
    """Close all database connections. Call on shutdown."""
    global _connection_pool
    if _connection_pool is not None:
        while not _connection_pool.empty():
            try:
                conn = _connection_pool.get_nowait()
                await conn.close()
            except asyncio.QueueEmpty:
                break
        _connection_pool = None
        logger.info("Closed HA database connection pool")


# ----------------------------------------------------------------------
# Health checks
# ----------------------------------------------------------------------


async def check_postgres_health() -> bool:
    """Verify Postgres connection is alive.
    
    Returns True if we can execute a simple query successfully.
    Returns False if Postgres is unreachable or any error occurs.
    """
    try:
        async with get_db() as conn:
            await conn.execute("SELECT 1")
            return True
    except Exception as e:
        logger.warning("Postgres health check failed: %s", e)
        return False


async def check_instance_leases() -> tuple[bool, int]:
    """Verify this instance holds valid leases.
    
    Returns (has_leases, lease_count):
    - has_leases: True if this instance holds at least one valid lease
    - lease_count: Number of valid leases held by this instance
    
    Returns (False, 0) if no leases or on error.
    """
    try:
        instance_id = get_instance_id()
        async with get_db() as conn:
            rows = await conn.execute(
                """
                SELECT run_id FROM run_leases 
                WHERE owner_id = %s AND expires_at > NOW()
                """,
                (instance_id,),
            )
            leases = await rows.fetchall()
            return len(leases) > 0, len(leases)
    except Exception as e:
        logger.warning("Failed to check instance leases: %s", e)
        return False, 0


# ----------------------------------------------------------------------
# Rate limiting (ADR-030 "Shared Anti-Replay / Rate-Limit State")
# ----------------------------------------------------------------------


async def check_rate_limit_pg(
    key: str,
    limit: int,
    window_seconds: int = 3600,
) -> tuple[bool, int]:
    """Check and update rate limit using PostgreSQL.
    
    Uses SELECT FOR UPDATE to serialize concurrent requests for the same key.
    Implements a fixed-window counter algorithm.
    
    Args:
        key: Rate limit bucket key (e.g., "scope:opsswarm:monitor" or IP address)
        limit: Maximum requests allowed in the window
        window_seconds: Window size in seconds (default: 1 hour)
    
    Returns:
        (allowed, retry_after):
        - allowed: True if request is within limit, False if over limit
        - retry_after: Seconds until the window resets (0 if allowed)
    """
    now = datetime.now(timezone.utc)
    window_start = now.replace(second=0, microsecond=0)
    
    try:
        async with get_db() as conn:
            # Try to acquire lock and get current count
            row = await conn.execute(
                """
                SELECT hits FROM rate_limit_buckets
                WHERE key = %s 
                  AND window_start = %s 
                  AND window_seconds = %s
                FOR UPDATE
                """,
                (key, window_start, window_seconds),
            )
            existing = await row.fetchone()
            
            if existing is None:
                # New bucket - insert with hit count of 1
                await conn.execute(
                    """
                    INSERT INTO rate_limit_buckets (key, hits, window_start, window_seconds)
                    VALUES (%s, 1, %s, %s)
                    ON CONFLICT (key, window_start) DO UPDATE SET hits = rate_limit_buckets.hits + 1
                    """,
                    (key, window_start, window_seconds),
                )
                return True, 0
            
            hits = existing["hits"]
            if hits >= limit:
                # Over limit - calculate retry time
                window_end = window_start + timedelta(seconds=window_seconds)
                retry_after = int((window_end - now).total_seconds()) + 1
                return False, max(1, retry_after)
            
            # Within limit - increment counter
            await conn.execute(
                """
                UPDATE rate_limit_buckets 
                SET hits = hits + 1 
                WHERE key = %s AND window_start = %s
                """,
                (key, window_start),
            )
            return True, 0
            
    except Exception as e:
        logger.error("Rate limit check failed: %s", e)
        # Fail-open on database errors to avoid blocking service
        # TODO: Could fail-closed by raising, but that would cause total outage
        return True, 0


async def prune_expired_rate_limits() -> int:
    """Prune expired rate limit buckets from the database.
    
    Deletes buckets whose window_start is older than 2 hours.
    Should be called periodically (e.g., once per hour).
    
    Returns:
        Number of rows deleted.
    """
    try:
        async with get_db() as conn:
            result = await conn.execute(
                """
                DELETE FROM rate_limit_buckets 
                WHERE window_start < NOW() - INTERVAL '2 hours'
                """
            )
            deleted = result.rowcount
            if deleted > 0:
                logger.info("Pruned %d expired rate limit buckets", deleted)
            return deleted
    except Exception as e:
        logger.error("Failed to prune rate limits: %s", e)
        return 0


# ----------------------------------------------------------------------
# Lease management (ADR-030 "Lease Ownership / Expiry / Takeover")
# ----------------------------------------------------------------------


async def acquire_run_lease(run_id: str, ttl_seconds: int = 30) -> tuple[bool, str | None]:
    """Acquire or renew a lease on a run.
    
    Uses INSERT ... ON CONFLICT to atomically acquire or renew the lease.
    
    Args:
        run_id: The run to acquire a lease on
        ttl_seconds: Lease TTL in seconds (default: 30)
    
    Returns:
        (acquired, current_owner):
        - acquired: True if this instance now holds the lease
        - current_owner: The instance ID that holds the lease (may be this instance)
    """
    instance_id = get_instance_id()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    
    try:
        async with get_db() as conn:
            # Try to acquire lease - succeeds if we own it or it's expired
            await conn.execute(
                """
                INSERT INTO run_leases (run_id, owner_id, expires_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE
                SET owner_id = EXCLUDED.owner_id,
                    expires_at = EXCLUDED.expires_at
                WHERE run_leases.owner_id = EXCLUDED.owner_id
                   OR run_leases.expires_at < NOW()
                """,
                (run_id, instance_id, expires_at),
            )
            
            # Verify we got it
            row = await conn.execute(
                "SELECT owner_id FROM run_leases WHERE run_id = %s AND expires_at > NOW()",
                (run_id,),
            )
            current = await row.fetchone()
            
            if current and current["owner_id"] == instance_id:
                return True, instance_id
            return False, current["owner_id"] if current else None
            
    except Exception as e:
        logger.error("Failed to acquire run lease: %s", e)
        return False, None


async def release_run_lease(run_id: str) -> bool:
    """Release a lease on a run.
    
    Only releases if this instance currently owns the lease.
    
    Args:
        run_id: The run to release
    
    Returns:
        True if lease was released, False otherwise.
    """
    instance_id = get_instance_id()
    
    try:
        async with get_db() as conn:
            result = await conn.execute(
                """
                DELETE FROM run_leases 
                WHERE run_id = %s AND owner_id = %s
                """,
                (run_id, instance_id),
            )
            return result.rowcount > 0
    except Exception as e:
        logger.error("Failed to release run lease: %s", e)
        return False
