"""Repository-level pytest configuration.

The only shared behaviour defined here is readiness isolation.  The readiness
manager is a process-global singleton (``opsswarm.runtime.readiness``), and a
``TestClient`` used as a context manager runs the FastAPI lifespan, whose
shutdown handler starts a drain on that singleton.  Without isolation the drain
outlives the test that triggered it and every later test in the same process
sees the service as draining (``503`` on guarded endpoints).

The scoped fixture lives in ``tests/readiness_scope.py`` so that test modules
can also use it explicitly; it is imported here to make it apply suite-wide.
"""

from __future__ import annotations

from tests.readiness_scope import scoped_readiness  # noqa: F401  (registers the fixture)
