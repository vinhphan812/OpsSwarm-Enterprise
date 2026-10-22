# Test Layer Taxonomy

OpsSwarm CI separates tests by the boundary and failure mode they validate. Each layer is independently runnable and publishes a clear result in the CI quality job.

| Layer | Path | Purpose | CI command |
| --- | --- | --- | --- |
| Unit | `tests/unit` | Isolated models, policies, skill logic, stores, and API behavior | `python -m pytest tests/unit -q` |
| Contract | `tests/contracts` | Structured OpenClaw/GitHub payloads, schemas, and interface invariants | `python -m pytest tests/contracts -q` |
| Integration | `tests/integration` | Orchestrator flows and cooperating adapters using controlled fakes | `python -m pytest tests/integration -q` |
| Fault | `tests/faults` | Timeouts, malformed responses, rate limits, write failures, and fail-closed behavior | `python -m pytest tests/faults -q` |
| E2E | `tests/e2e` | Real application boundaries and complete incident lifecycles | `python -m pytest tests/e2e -q` |
| Smoke | `tests/smoke` | Minimal release-health checks for the packaged/runtime surface | `python -m pytest tests/smoke -q` |
| Security | `tests/security` | Authentication, authorization, allowlists, and error/PII redaction contracts | `python -m pytest tests/security -q` |

## Execution policy

The quality job runs unit/contract, integration, fault, E2E, smoke, and security layers as separate steps. A failure in one layer is visible independently rather than being hidden in a monolithic suite. The final full-suite step remains a regression net across all tests.

The Security CI workflow complements (and does not replace) the security test layer. It performs static analysis and supply-chain checks including Bandit, pip-audit, Gitleaks, license scanning, SBOM generation, and CodeQL. Security tests validate application behavior; Security CI validates source and dependency posture.

## Coverage gate

The repository has exactly one coverage policy: **`pyproject.toml` is the single source of truth.** The threshold is declared in `[tool.coverage.report] fail_under`, and `pytest-cov` reads that value directly, so the gate binds even on a command line that passes no explicit `--cov-fail-under` flag.

Every other place that states the threshold is kept in agreement with it:

| Location | How the threshold is expressed |
| --- | --- |
| `pyproject.toml` | `fail_under = 90` — the source of truth |
| `Makefile` (`coverage` target) | `--cov-fail-under=90`, stated explicitly so a local `make coverage` run is held to the documented bar |
| `.github/workflows/ci.yml` | resolved from `pyproject.toml` at run time, so the enforced value cannot drift from the policy |

`scripts/verify_coverage_gate.py` enforces that agreement. It parses the threshold out of `pyproject.toml`, the `Makefile`, every workflow under `.github/workflows/`, and every helper script under `scripts/`, and fails when they disagree, when a declaration goes missing, or when the policy is lowered below the committed floor. The CI workflow runs it immediately before the coverage run, so a drifted gate is reported as a gate problem rather than as a coverage failure. `make verify-coverage-gate` runs the same check locally, and `make ci` runs it as part of the full gate sequence.

This guard exists because the three declarations previously drifted: the CI workflow enforced 89 while `pyproject.toml` and the `Makefile` declared 90. Pull requests #105 and #106 landed container-delivery code at 87.43% against the documented 90% policy because the gate that actually gated them had been quietly loosened. The regression tests in `tests/unit/test_verify_coverage_gate.py` prove the guard fails on a deliberately diverged value.

## Local verification

Install the development dependencies, then run a single layer or the complete layered sequence:

```bash
python -m pytest tests/unit tests/contracts -q
python -m pytest tests/integration -q
python -m pytest tests/faults -q
python -m pytest tests/e2e -q
python -m pytest tests/smoke -q
python -m pytest tests/security -q
python -m pytest -q
```

A skipped test is reported by pytest and should be reviewed when it represents an unavailable external boundary. It must not be silently treated as a passing assertion.
