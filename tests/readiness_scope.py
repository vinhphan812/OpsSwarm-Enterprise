"""Scoped readiness isolation for tests that exercise the HTTP surface.

The readiness manager is a process-global singleton (``opsswarm.runtime.readiness``).
A ``TestClient`` used as a context manager runs the FastAPI lifespan, and the
lifespan shutdown handler starts a drain on that singleton.  The drain state
therefore outlives the test that triggered it: every later test in the same
process observes the singleton as draining and guarded endpoints answer
``503 Service Unavailable`` instead of their real status.

The fixture below replaces the singleton for the duration of a single test and
restores the previous manager afterwards, so drain state can never cross a
test boundary.  Production behaviour is untouched: only the test's own view of
the singleton is swapped.

The replacement manager starts *not ready* and *not draining*.  That is
deliberate: the swap must not mask a missing startup preflight (a ``/ready``
probe still answers ``503`` until startup completes), it only prevents a drain
performed by one test from suppressing the next test's ingress.
"""

from __future__ import annotations

import pytest

import opsswarm.runtime as runtime
from opsswarm.runtime import ReadinessManager


@pytest.fixture(autouse=True)
def scoped_readiness():
    """Install a fresh readiness manager for one test, then restore the original.

    Yields the scoped manager so a test can inspect its own drain state.
    """
    original = runtime.readiness
    runtime.readiness = ReadinessManager()
    try:
        yield runtime.readiness
    finally:
        runtime.readiness = original
