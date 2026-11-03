"""Failure classes for the shared (PostgreSQL) rate-limit path (Issue #127).

These live in their own module so that ``opsswarm.auth`` can classify a
shared-store failure without importing ``opsswarm.ha_db`` at module scope.
``ha_db`` imports ``psycopg`` directly and is only available when the optional
``ha`` extra is installed, whereas ``auth`` is part of the base package.
"""

from __future__ import annotations


class RateLimitError(RuntimeError):
    """Base class for shared rate-limit failures."""


class RateLimitInfrastructureError(RateLimitError):
    """The shared rate-limit store could not be reached.

    The database is unreachable (connection refused, timeout, DNS failure,
    pool exhausted).  The failure is transient and external to the request, so
    the caller is throttled by a bounded local fallback rather than being
    waved through.
    """


class RateLimitProgrammingError(RateLimitError):
    """The shared rate-limit store is reachable but its schema is not usable.

    The database answered, but the query or the schema is wrong - a missing
    table, invalid SQL, a schema mismatch.  That is a deployment defect and
    must not be masked at runtime, so it propagates to the caller.
    """
