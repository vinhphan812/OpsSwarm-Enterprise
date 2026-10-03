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
