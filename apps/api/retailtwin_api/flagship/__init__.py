"""Flagship Demo Controller — deterministic Weekend Demand Surge (issue #41).

The controller exposes ``reset``, ``start`` and ``status`` over HTTP and drives
the autonomous chain end-to-end::

    EVENT → INVESTIGATE → PLAN → SIMULATE → GUARD → LIVE 3D ACTION → VERIFY

Only event timing and the canonical seed are controlled for reproducibility.
Every other step uses the production canonical services:

  * real Investigator (``agents/investigator``)
  * real Planner (``agents/planner``)
  * real Simulator + deterministic KPI evaluator (``agents/simulator``)
  * real Decision Context Guard ``NoStaleCommit``
  * real guarded Executor (``agents/executor``)
  * real Replan loop (``agents/orchestrator/replan``)
  * real post-action Verifier (``agents/verifier``)
  * real provider-neutral LLM (adapters in ``llm/``; tests use ``FakeLlmProvider``)
  * real Live Twin boundary (``firestore_twin``; tests use ``InMemoryTwinRepository``)

The controller does not invent evidence, actions, scores or KPI values. The
``replan`` loop is the one path that recovers from a stale block, and the
``verify`` step re-reads the Live Twin and reports VERIFIED / REGRESSION /
INCONCLUSIVE on the actions that just committed.
"""
from __future__ import annotations

from retailtwin_api.flagship.controller import (
    FlagshipController,
    FlagshipDependencies,
    FlagshipPhase,
    FlagshipRequest,
    FlagshipRunResult,
    FlagshipStatus,
    FlagshipStateError,
    get_controller,
    register_dependencies,
)
from retailtwin_api.flagship.routes import register_routes

__all__ = [
    "FlagshipController",
    "FlagshipDependencies",
    "FlagshipPhase",
    "FlagshipRequest",
    "FlagshipRunResult",
    "FlagshipStateError",
    "FlagshipStatus",
    "get_controller",
    "register_dependencies",
    "register_routes",
]
