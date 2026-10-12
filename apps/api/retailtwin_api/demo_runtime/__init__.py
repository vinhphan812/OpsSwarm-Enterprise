"""RetailTwin Demo Runtime — isolated demo orchestration namespace.

This package contains demo-only implementations and must NEVER be imported
by production code in retailtwin_api/ (outside of this package).

Production code must use retailtwin_api.demo_runtime.* imports — NOT
relative imports that reach into sibling packages.
"""
from __future__ import annotations

# Demo code has no compatibility aliases outside this isolated namespace.
from retailtwin_api.demo_runtime.agents import ExecutorAgent
from retailtwin_api.demo_runtime.agents import VerifierAgent
from retailtwin_api.demo_runtime.guard import (
    ActionValidation,
    CommitAuthorization,
    DCG,
    DCGVerdict,
    DCGVerdictResult,
    Decision,
)
from retailtwin_api.demo_runtime.services import SimulationService
from retailtwin_api.demo_runtime.services import TwinService
from retailtwin_api.demo_runtime import demo

__all__ = [
    "ActionValidation",
    "CommitAuthorization",
    "DCG",
    "DCGVerdict",
    "DCGVerdictResult",
    "Decision",
    "ExecutorAgent",
    "SimulationService",
    "TwinService",
    "VerifierAgent",
    "demo",
]
