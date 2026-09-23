# Test Architecture Triage Report

**Date:** 2026-09-22
**Task:** TRIAGE #4: Design layered test architecture and fault campaigns
**Source:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/4

---

## 1. Executive Summary

This document specifies a layered test architecture for OpsSwarm Enterprise. It assesses the current pytest suite,
defines test layers (unit, contract, skills, integration, E2E, fault, security, smoke), and provides migration guidance.

**Key Finding:** Current tests (13 total) are flat-structured and use fakes. The architecture must evolve to support
skill-level contract testing (#3) and fault/invariant testing (#9) without overlap.

---

## 2. Current Test Inventory

### 2.1 Test Files (Flat Structure)

| File                            | Tests | Type        | Dependencies                 |
|---------------------------------|-------|-------------|------------------------------|
| `tests/test_commands.py`        | 2     | Unit        | `opsswarm.commands`          |
| `tests/test_issue_parse.py`     | 1     | Unit        | `opsswarm.skill_logic`       |
| `tests/test_openclaw_parser.py` | 1     | Unit        | `opsswarm.skill_logic`       |
| `tests/test_orchestrator.py`    | 4     | Integration | `FakeGitHub`, `FakeOpenClaw` |
| `tests/test_policy.py`          | 4     | Unit        | `opsswarm.policy`            |
| `tests/test_webhook.py`         | 1     | Unit        | `opsswarm.webhook`           |

**Total:** 13 tests

### 2.2 Fake Infrastructure

| Fake           | Location         | Purpose                                                                                 |
|----------------|------------------|-----------------------------------------------------------------------------------------|
| `FakeGitHub`   | `tests/fakes.py` | Stub GitHub API (get_issue, comment, set_labels, close_issue, create_issue, permission) |
| `FakeOpenClaw` | `tests/fakes.py` | Stub OpenClaw agent (run_json with canned responses)                                    |

### 2.3 Runtime Seams Identified

1. **GitHub API Boundary:** `opsswarm.github_client` module - HTTP calls to GitHub REST API
2. **OpenClaw Agent Boundary:** `opsswarm.openclaw` module - Process/subprocess spawning
3. **File System Boundary:** `opsswarm.store`, `opsswarm.evidence` - JSONL persistence
4. **Webhook Boundary:** `opsswarm.webhook` - HTTP signature verification

---

## 3. Proposed Directory/Marker Model

### 3.1 Directory Structure

```
tests/
├── __init__.py
├── conftest.py                 # Shared fixtures
├── fakes.py                    # Current fakes (migrate to fakes/)
│
├── unit/                       # Unit tests - pure functions, no I/O
│   ├── __init__.py
│   ├── commands/
│   │   └── test_parse*.py
│   ├── policy/
│   │   └── test_classify*.py
│   ├── models/
│   │   └── test_validate*.py
│   └── markdown/
│   │   └── test_render*.py
│
├── contract/                  # Skill contract tests (see #3)
│   ├── __init__.py
│   ├── s1_intent_guard/
│   │   └── test_*.py
│   ├── s2_task_graph/
│   ├── s3_horizon_plan/
│   ├── s4_role_dispatch/
│   ├── s5_collab_exec/
│   ├── s6_resilience_guard/
│   ├── s7_observe_verify/
│   └── s8_orchestration_hub/
│
├── integration/               # Multi-component tests with fakes
│   ├── __init__.py
│   ├── orchestrator/
│   │   └── test_*flow*.py    # Current test_orchestrator.py moves here
│   ├── store/
│   │   └── test_persistence*.py
│   └── webhook/
│       └── test_signature*.py
│
├── e2e/                      # Full system tests (real HTTP/process)
│   ├── __init__.py
│   ├── github_mock/
│   │   └── test_*.py         # httpx mocking GitHub
│   └── full_pipeline/
│       └── test_incident*.py
│
├── fault/                    # Fault injection tests (see #9)
│   ├── __init__.py
│   ├── idempotency/
│   │   └── test_duplicate*.py
│   ├── concurrency/
│   │   └── test_race*.py
│   ├── restart/
│   │   └── test_recovery*.py
│   └── ambiguity/
│       └── test_*.py
│
├── security/                 # Security tests
│   ├── __init__.py
│   ├── webhook/
│   │   └── test_signature*.py
│   └── permissions/
│       └── test_*.py
│
└── smoke/                    # Smoke tests for CI
    ├── __init__.py
    └── test_startup*.py
```

### 3.2 Pytest Markers

| Marker                     | Layer       | Purpose                     |
|----------------------------|-------------|-----------------------------|
| `@pytest.mark.unit`        | unit        | Pure function tests, no I/O |
| `@pytest.mark.contract`    | contract    | Skill contract validation   |
| `@pytest.mark.integration` | integration | Multi-component with fakes  |
| `@pytest.mark.e2e`         | e2e         | Real HTTP/process boundary  |
| `@pytest.mark.fault`       | fault       | Fault injection scenarios   |
| `@pytest.mark.security`    | security    | Authz/authn tests           |
| `@pytest.mark.smoke`       | smoke       | Quick sanity checks         |
| `@pytest.mark.slow`        | any         | Long-running tests          |

### 3.3 Pytest Configuration

```python
# pyproject.toml additions
[tool.pytest.ini_options]
markers = [
    "unit: Pure function tests with no I/O",
    "contract: Skill contract validation tests",
    "integration: Multi-component tests with fakes",
    "e2e: Full system tests with real HTTP/process",
    "fault: Fault injection and recovery tests",
    "security: Authorization and authentication tests",
    "smoke: Quick sanity checks",
    "slow: Long-running tests",
]
```

---

## 4. Real HTTP/Process Boundary Strategy

### 4.1 Boundary Classification

| Boundary         | Current               | Strategy                                | Test Layer       |
|------------------|-----------------------|-----------------------------------------|------------------|
| GitHub API       | `httpx` real calls    | Mock via `pytest-httpx` or `responses`  | e2e              |
| OpenClaw Process | `subprocess` spawning | `unittest.mock` patch or `FakeOpenClaw` | integration      |
| File System      | JSONL read/write      | `tmp_path` fixture                      | unit/integration |
| Webhook HTTP     | FastAPI incoming      | `TestClient` from `fastapi.testclient`  | integration      |

### 4.2 HTTP Mocking Pattern

```python
# tests/e2e/github_mock/conftest.py
import pytest
import httpx

@pytest.fixture
def mock_github(responses):
    """Mock GitHub API responses using pytest-httpx."""
    pass
```

### 4.3 Process Boundary Pattern

```python
# tests/integration/openclaw/test_dispatch.py
from unittest.mock import patch, AsyncMock

@pytest.mark.integration
async def test_task_dispatch():
    with patch('opsswarm.openclaw.subprocess.run') as mock_run:
        mock_run.return_value = AsyncMock()
        # test dispatch logic
```

---

## 5. Fakes/Stubs and Persistence Requirements

### 5.1 Current Fakes (Migrate)

| Fake           | Move To                   | Adaptations Needed                        |
|----------------|---------------------------|-------------------------------------------|
| `FakeGitHub`   | `tests/fakes/github.py`   | Add async methods, configurable responses |
| `FakeOpenClaw` | `tests/fakes/openclaw.py` | Response queue, call recording            |

### 5.2 New Fakes Required

| Fake                 | Location                  | Purpose                        |
|----------------------|---------------------------|--------------------------------|
| `FakeEvidenceStore`  | `tests/fakes/evidence.py` | In-memory evidence for testing |
| `FakePolicyEngine`   | `tests/fakes/policy.py`   | Configurable policy outcomes   |
| `FakeGitHubDelivery` | `tests/fakes/webhook.py`  | Deduplication test helper      |

### 5.3 Persistence Test Strategy

| Data              | Test Approach                        |
|-------------------|--------------------------------------|
| Run state (JSONL) | Use `tmp_path`, assert file contents |
| Evidence store    | In-memory fake, verify append        |
| Config loading    | Patch filesystem, assert parsed      |

---

## 6. Fault Scenarios and Ownership

### 6.1 Fault Categories

| Category              | Scenarios                                             | Test Layer | Owner               |
|-----------------------|-------------------------------------------------------|------------|---------------------|
| **Idempotency**       | Duplicate webhook delivery, duplicate comment         | fault      | This spec (#4) → #9 |
| **Concurrency**       | Concurrent approve/abort, parallel comments           | fault      | This spec (#4) → #9 |
| **Restart Recovery**  | Crash during WAITING_APPROVAL, crash during EXECUTING | fault      | This spec (#4) → #9 |
| **Ambiguity**         | Unclear remediation options, partial evidence         | fault      | This spec (#4) → #9 |
| **Skill Contract**    | Invalid input/output per S1-S8                        | contract   | #3                  |
| **Policy Regression** | Risk classification changes                           | unit       | #3                  |
| **API Compatibility** | GitHub API breaking changes                           | e2e        | #3                  |

### 6.2 Boundary with Issue #3 (192 Skill Tests)

| This Spec (#4)                      | Issue #3                        |
|-------------------------------------|---------------------------------|
| Test architecture, layers, fixtures | 192 substantive skill tests     |
| Fault injection strategy            | Normal + boundary + error cases |
| Marker definitions                  | Test implementation             |
| Migration plan                      | Tests themselves                |

**Partition:** #4 defines the framework; #3 fills the framework with tests.

### 6.3 Boundary with Issue #9 (Persistence Hardening)

| This Spec (#4)               | Issue #9                                  |
|------------------------------|-------------------------------------------|
| Test architecture for faults | Implementation of idempotency/concurrency |
| Fault scenario definitions   | Code fixes for fault tolerance            |
| Recovery test patterns       | Actual persistence logic                  |
| Restart test fixtures        | State machine changes                     |

**Partition:** #4 designs the test patterns; #9 implements the hardened behavior and tests it.

---

## 7. Migration Plan (Preserving Current Tests)

### 7.1 Phase 1: Restructure (No Code Changes)

1. Create directory hierarchy (`tests/unit/`, `tests/integration/`, etc.)
2. Add `conftest.py` with marker registration
3. Move `fakes.py` → `tests/fakes/`
4. Add markers to existing tests (no content changes)

```bash
# Conceptual migration commands
mkdir -p tests/unit tests/contract tests/integration tests/e2e tests/fault tests/security tests/smoke
mkdir -p tests/fakes
mv tests/fakes.py tests/fakes/__init__.py
# Move test files preserving test functions
```

### 7.2 Phase 2: Marker Migration

Add markers to existing tests:

```python
# Before
def test_safe_auto_resolves(tmp_path, cfg, issue):
    ...

# After
@pytest.mark.integration
@pytest.mark.slow
async def test_safe_auto_resolves(tmp_path, cfg, issue):
    ...
```

### 7.3 Phase 3: Expand Layers

1. Create `tests/contract/` structure for #3
2. Create `tests/fault/` structure for #9
3. Add `tests/e2e/` with httpx mocking

### 7.4 Current Tests Migration Map

| Current File              | Target Directory                  | Markers                    |
|---------------------------|-----------------------------------|----------------------------|
| `test_commands.py`        | `tests/unit/commands/`            | `@pytest.mark.unit`        |
| `test_policy.py`          | `tests/unit/policy/`              | `@pytest.mark.unit`        |
| `test_issue_parse.py`     | `tests/unit/models/`              | `@pytest.mark.unit`        |
| `test_webhook.py`         | `tests/security/webhook/`         | `@pytest.mark.security`    |
| `test_orchestrator.py`    | `tests/integration/orchestrator/` | `@pytest.mark.integration` |
| `test_openclaw_parser.py` | `tests/unit/models/`              | `@pytest.mark.unit`        |

---

## 8. CI Execution Matrix

### 8.1 Test Selection by CI Trigger

| Trigger             | Run Layers                                             | Execution Time Target |
|---------------------|--------------------------------------------------------|-----------------------|
| Every commit        | `unit`, `security`, `smoke`                            | < 30s                 |
| PR review           | `unit`, `integration`, `security`                      | < 2min                |
| Merge to main       | `unit`, `integration`, `contract`, `security`, `smoke` | < 5min                |
| Scheduled (nightly) | `e2e`, `fault`                                         | < 15min               |
| Release             | `e2e`, `fault`, `full`                                 | < 30min               |

### 8.2 Pytest Command Matrix

```bash
# Quick (every commit)
pytest -m "unit or security or smoke"

# Standard PR
pytest -m "unit or integration or security"

# Full pipeline
pytest -m "unit or integration or contract or security or smoke"

# Nightly fault tests
pytest -m "fault"

# E2E (requires secrets)
pytest -m "e2e" --env=staging
```

### 8.3 GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Test

on:
     push:
          branches: [main]
     pull_request:

jobs:
     quick:
          runs-on: ubuntu-latest
          steps:
               - uses: actions/checkout@v4
               - run: pytest -m "unit or security or smoke" --tb=short

     full:
          needs: quick
          runs-on: ubuntu-latest
          steps:
               - uses: actions/checkout@v4
               - run: pytest -m "unit or integration or contract or security" --tb=short

     nightly:
          if: github.event_name == 'schedule'
          runs-on: ubuntu-latest
          steps:
               - uses: actions/checkout@v4
               - run: pytest -m "fault or e2e" --tb=short
```

---

## 9. Acceptance Criteria Validation

| Criterion                           | Status | Notes                      |
|-------------------------------------|--------|----------------------------|
| Current test inventory documented   | ✅      | 13 tests across 6 files    |
| Proposed directory/marker model     | ✅      | 8-layer structure defined  |
| Real HTTP/process boundary strategy | ✅      | Mock patterns specified    |
| Fakes/stubs requirements            | ✅      | Current + new fakes listed |
| Fault scenarios and ownership       | ✅      | Partitioned with #3/#9     |
| Migration plan preserving tests     | ✅      | 3-phase migration          |
| CI execution matrix                 | ✅      | Trigger-based selection    |
| Overlaps with #3/#9 partitioned     | ✅      | Clear boundaries defined   |

---

## 10. Test Layer Summary

| Layer           | Purpose             | Entrypoint              | Fixtures                     | Validation Command |
|-----------------|---------------------|-------------------------|------------------------------|--------------------|
| **unit**        | Pure function logic | `pytest -m unit`        | `tmp_path`                   | `assert`           |
| **contract**    | Skill I/O contracts | `pytest -m contract`    | `skill_fixture`              | JSON schema        |
| **integration** | Multi-component     | `pytest -m integration` | `FakeGitHub`, `FakeOpenClaw` | state assertions   |
| **e2e**         | Real boundaries     | `pytest -m e2e`         | `mock_github`, `TestClient`  | HTTP status        |
| **fault**       | Chaos injection     | `pytest -m fault`       | `crash_sim`, `race_sim`      | exception/timeout  |
| **security**    | Authn/authz         | `pytest -m security`    | `TestClient`                 | 403/401 checks     |
| **smoke**       | Sanity              | `pytest -m smoke`       | none                         | import check       |

---

**End of Report**
