# G06 Submission Gate runbook

The G06 Submission Gate (issue #53) runs the flagship scenario — Weekend
Demand Surge for SKU `P017` on `store-001` — 20 consecutive times from a
deterministic reset and records a 20-row run matrix. The gate is the last
release check before Competition-100 submission.

This document explains how to run the gate, what each piece of evidence
contains, and how to interpret the matrix.

> **Status (2026-10-18):** The in-memory preflight path (`scripts/run-submission-gate.sh`
> + `tests/e2e/gates/run_flagship_scenario.py`) is stable and reproducible.
> PR #247's reviewers closed that runner with three blockers that converge on
> the **deployed** Cloud Run stack — not TestClient — and that production-mode
> path is tracked under "Production-mode runner (TODO)" below. The runner now
> captures all production-mode fields reviewers asked for, and `--mode negative`
> exercises the no-stale-commit REFRESH_REQUIRED row. Closure of #53 still
> requires a real Cloud Run + Firestore + Vertex + Pub/Sub run; this runner
> is the runner-side preparation for that work.

## Components

| Path | Role |
| --- | --- |
| `tests/e2e/gates/run_flagship_scenario.py` | Python runner that drives the full chain once (Observer → Investigator → Planner → Simulator → DCG → Executor → Live Twin → audit). Emits one structured JSON evidence file. |
| `scripts/run-submission-gate.sh` | Bash orchestrator that calls the Python runner N consecutive times, writes one JSON per run, and aggregates them into one matrix JSON. Halts on the first failure. |
| `artifacts/submission-gate/<run-id>.json` | Per-run structured evidence. |
| `artifacts/submission-gate/<run-id>.stderr.log` | Per-run stderr (truncated tail is shown in the runner output on FAIL). |
| `artifacts/submission-gate/matrix.json` | Aggregate 20-row matrix JSON. |

## What the flagship scenario proves

Each run exercises the full canonical chain on the real API app:

1. `POST /events` for each of the 13 `sale.completed` events from
   `data/synthetic/weekend-demand-surge.json`.
2. The Observer accepts every event and starts one investigation per
   accepted sale (no prompt).
3. The autonomy drains: INVESTIGATE → PLAN → SIMULATE produce a
   `simulation_id` and a Decision for every investigation.
4. `POST /simulations/{id}/approve` runs the Decision Context Guard
   (`NoStaleCommit`) on fresh Live Twin reads; the first ALLOW issues a
   signed single-use authorization and the guarded Executor commits the
   actions to the Live Twin.
5. `GET /store` shows the Live Twin move for SKU P017 (shelf increased).
6. The audit trail (`app.state.review_audit`, `app.state.guard_audit`)
   carries the same correlation_id (`run-weekend-demand-surge-1`) on every
   committed event.

The deterministic reset happens because every run rebuilds the same
in-memory Live Twin from the committed fixture plus the canonical
P017 baseline (A02 / A02-S03, facings 2, shelf 8, backroom 54) and
republishes the same 13 events with the same correlation_id. Two
consecutive runs of the same scenario produce byte-identical evidence.

## Determinism sources

- **Seed** — the canonical Weekend Demand Surge is `seed=1` and is hard-
  wired in `retailtwin_api.demand_surge.CANONICAL_SEED`. Any other seed is
  refused by `reset_weekend_demand_surge`.
- **P017 baseline** — `tests/e2e/gates/run_flagship_scenario.py` seeds P017
  at `A02 / A02-S03`, `facings=2`, `shelf=8`, `backroom=54` (matches the
  inventory the canonical weekend-demand-surge fixture assumes).
- **Provider** — `FakeLlmProvider` returns the same canned tool-call list and
  plan JSON for every cycle. No network call.
- **Live Twin** — `InMemoryTwinRepository` seeded deterministically per run.
- **Correlation id** — every published event carries
  `correlation_id=run-weekend-demand-surge-1` so the audit chain is stable.

## Quick start

```bash
# Default: 20 runs, seed "submission", evidence under
# artifacts/submission-gate/, matrix at artifacts/submission-gate/matrix.json
bash scripts/run-submission-gate.sh

# Smoke (used in CI / local pre-merge)
bash scripts/run-submission-gate.sh --runs 2 --seed smoke --out /tmp/g06-smoke.json
```

## CLI options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--runs <N>` | `20` | Total consecutive runs (use 20 for the real submission, 2 for CI smoke). |
| `--seed <name>` | `submission` | Every run is named `<name>-01` .. `<name>-NN`. |
| `--out <path>` | `artifacts/submission-gate/matrix.json` | Aggregate matrix output path. |
| `--evidence-dir <path>` | `artifacts/submission-gate` | Per-run evidence output directory. |
| `--flagship <path>` | `tests/e2e/gates/run_flagship_scenario.py` | Path to the flagship Python runner. |
| `--pythonpath <path>` | `.` | `PYTHONPATH` for the Python process. |

## Per-run evidence JSON

Each run writes one JSON file with:

```jsonc
{
  "gate": "G06",
  "scenario": "weekend-demand-surge",
  "issue": 53,
  "mode": "happy" | "negative",
  "run_id": "<seed>-NN",
  "seed": 1,
  "result": "PASS" | "FAIL",
  "started_at": "<ISO-8601>",
  "finished_at": "<ISO-8601>",
  "git_sha": "<current HEAD, or null if not in a git repo>",
  "runtime": {
    "environment": "in-memory preflight" | "production-cloudrun",
    "provider_mode": "fake" | "vertex_gemini",
    "live_twin_backend": "memory" | "firestore",
    "app_env": "e2e-smoke" | "production",
    "cloud_run_revision": "<sha or null>",
    "app": "retailtwin_api.main.create_app with AutonomousInvestigations",
    "scenario_fixture": "data/synthetic/weekend-demand-surge.json",
    "provider": "FakeLlmProvider: scripted P017 tool calls and plan JSON",
    "provider_calls": <int>,
    "store_id": "store-001",
    "sku": "P017",
    "p017_baseline": {
      "shelf_id": "A02", "slot_id": "A02-S03", "facings": 2,
      "shelf_quantity": 8, "backroom_quantity": 54
    },
    "mode": "happy" | "negative",
    "verifier_verdict": "VERIFIED" | "INCONCLUSIVE" | "NOT_RUN",
    "actions": [{ "action": {...}, "kind": "guarded_live_mutation" }, ...],
    "dcg_audit": { "events": [...], "gate_breakdown": { "context": { "verdict": "REFRESH_REQUIRED", "reason_code": "VERSION_STALE", ... } } },
    "correlation_id_round_trip": { "expected": "<run_id>", "observed_in_agent_events": [...] }
  },
  "checks": [
    {"check": "<name>", "passed": true, "detail": "<short reason>"},
    ...
  ],
  "steps": {
    "fixture": { "event_ids": [...], "event_count": 13, ... },
    "drain": { "background_runs": [...], "recorded_simulations": 14 },
    "approvals": [...],
    "audit": { "reviews": [...], "guard_events": [...], ... },
    "committed": { "decision_id": "...", "simulation_id": "...", "action": {...} },
    "live_after": { "sku": "P017", "shelf_quantity": 20, ... }
  },
  "logs": [ { "ts": "...", "logger": "...", "level": "...", "message": "..." } ]
}
```

The required checks for PASS (happy mode):

| check | meaning |
| --- | --- |
| `all_13_events_published` | All 13 `sale.completed` events were accepted by `POST /events` (HTTP 200 or 201). |
| `weekend_demand_surge_detected` | The committed fixture yields the canonical spike (baseline 12.5/h → surge 18.25/h, +46%). |
| `observer_accepted_every_sale` | Every accepted event started exactly one investigation (no prompt). |
| `every_investigation_completed_simulation` | 13/13 investigations produced a `simulation_id`. |
| `guard_allowed_on_fresh_reads` | At least one approve call returned `verdict=ALLOW`. |
| `simulation_id_present` | The committed decision carries a `simulation_id`. |
| `decision_id_present` | The committed decision carries a `decision_id`. |
| `p017_shelf_increased` | P017 `shelf_quantity` increased on `GET /store` after the commit. |
| `audit_trail_complete` | A review record exists and every guard event for the committed decision carries `correlation_id=run-weekend-demand-surge-1`. |

## Aggregate matrix JSON

```jsonc
{
  "gate": "G06",
  "issue": 53,
  "scenario": "weekend-demand-surge",
  "seed": "<seed>",
  "total_runs": 20,
  "passed": 20,
  "failed": 0,
  "started_at": "<first run start>",
  "finished_at": "<last run finish>",
  "runs": [
    {
      "run_index": 1,
      "run_id": "<seed>-01",
      "exit_code": 0,
      "result": "PASS",
      "started_at": "<ISO-8601>",
      "finished_at": "<ISO-8601>",
      "evidence_path": "artifacts/submission-gate/<seed>-01.json",
      "evidence_sha256": "<sha256(prev|run_id|exit|result)>"
    },
    ...
  ]
}
```

`evidence_sha256` is a tamper-evident hash chain over `(prev_hash, run_id,
exit_code, result)`. Reordering or editing any row will break the chain.

## Interpreting results

* **All 20 PASS, exit 0** — the matrix is the evidence that the gate
  passed. Send the PR for review; the reviewer decides whether the
  20-row matrix closes the issue.
* **Any FAIL** — the script exits 1 and stops further runs. The failing
  run's evidence and stderr log are kept; the matrix still contains the
  rows that ran, with the failing row's `result: "FAIL"`.
* **No row is removed.** A single FAIL resets the consecutive count for
  the runbook owner: the operator must fix, re-run from `run_index = 1`,
  and obtain 20 consecutive PASS rows before submission.

## What the runner does NOT do

* **It does not call Vertex / Gemini.** Production LLM use is a separate
  concern (issue #2 / PR #179). The gate uses `FakeLlmProvider` to keep the
  evidence deterministic.
* **It does not touch Firestore Live Twin.** The in-memory Live Twin is the
  same boundary the G03/G04/G05 gates exercise; the `LIVE_TWIN_BACKEND=
  firestore` env var is wired into `Settings` but does not require GCP
  credentials for the local run.
* **It does not close issue #53.** Only the reviewer closes it after the
  20-row matrix is on record.

## Local reproduction

```bash
# 1. Create a worktree and check out the branch.
git worktree add ../retailtwin-ai-issue-53 -b issue/53-submission-gate main
cd ../retailtwin-ai-issue-53

# 2. Install dev deps once.
pip install -e apps/api[dev]

# 3. Run the smoke (2 runs) before the full 20.
bash scripts/run-submission-gate.sh --runs 2 --seed smoke --out /tmp/g06-smoke.json

# 4. When the smoke is green, run the full 20.
bash scripts/run-submission-gate.sh --seed submission

# 5. Inspect the matrix.
python3 -m json.tool artifacts/submission-gate/matrix.json
```

## Production-mode runner (TODO)

PR #247's reviewers closed the in-memory runner with three blockers that
converge on a **deployed** Cloud Run revision, not TestClient. The
production-mode runner is the runner-side preparation for that closure;
the actual run against the deployed stack is gated on Cloud Run CD
(#143), the cloud runtime matrix (#134), and a real Vertex Gemini
adapter that does not bypass the DCG (`#2`).

### Production-mode fields captured (today)

The Python flagship harness now writes these fields into every per-run
evidence JSON so the same script can run in **either** the in-memory
preflight mode or against the deployed stack later:

| Field | In-memory preflight (today) | Production (when the stack is wired) |
| --- | --- | --- |
| `runtime.environment` | `"in-memory preflight"` | `"production-cloudrun"` (set by the shell via `G06_ENVIRONMENT`) |
| `runtime.provider_mode` | `"fake"` | `"vertex_gemini"` |
| `runtime.live_twin_backend` | `"memory"` | `"firestore"` |
| `runtime.app_env` | `"e2e-smoke"` | `"production"` |
| `runtime.cloud_run_revision` | `null` | the SHA captured by `gcloud run services describe` |
| `runtime.verifier_verdict` | `VERIFIED` / `INCONCLUSIVE` / `NOT_RUN` | same labels, populated from the real Verifier |
| `runtime.actions[]` | `[{action, kind}]`, every committed action tagged `guarded_live_mutation` | tags also include `simulation_only` for SIMULATION routes |
| `runtime.dcg_audit` | per-gate verdict + reason_code slice, mirroring `policy_result["checks"]` | identical shape, populated from real guard events |
| `runtime.correlation_id_round_trip` | the correlation_id the script sent and what `GET /agent/events` observed | round-tripped through Pub/Sub → BigQuery `agent_action_audit` → Live Twin diff |
| `git_sha` | the SHA in the worktree | the SHA the runner was cut from, anchored to that revision |

Reviewers required these fields by name (review blocker #2). They are
present in every per-run JSON the in-memory preflight already produces;
the production-mode shell only needs to populate the right values.

### No-stale-commit negative case

The same harness now exposes a `--mode negative` flag that exercises the
REFRESH_REQUIRED path on the same Decision Context Guard. Pre-CSG, this
was only covered by `tests/e2e/test_stale_context.py`. Pre-CSG, G06
halted on first FAIL and had no explicit matrix row for the no-stale-
commit case (DoD-2 of issue #53 was only partial). The runner now emits
a separate evidence JSON for `--mode negative` with these checks:

```
p017_starts_at_version_n
p017_moved_to_n_plus_1
guard_returns_refresh_required
guard_reason_is_version_stale
no_commit_binding_issued
live_twin_unmutated
guard_audit_records_correlation_id
```

The runner script `scripts/run-submission-gate.sh` does not yet loop
over `--mode negative`. The production shell below invokes it once per
matrix so the reviewer sees a REFRESH_REQUIRED row alongside the 20
ALLOW rows.

### Production-mode shell (currently a documented stub)

`scripts/run-submission-gate-cloudrun.sh` is a documented stub, not an
executable. It refuses to run today because the deployed `retailtwin-api`
revision is a fixture-only reader and does not yet satisfy the contract
PR #247's reviewers required. Once the wiring below is in place, this
stub becomes the production orchestrator:

1. Confirm target: `PROJECT_ID=retailtwin-ai-511002`, `REGION=us-central1`.
2. Capture `G06_CLOUD_RUN_REVISION` from
   `gcloud run services describe retailtwin-api`.
3. Capture the BigQuery dataset identity (`retailtwin`), the Pub/Sub
   topic (`store-events`) and subscription (`store-events-analytics`),
   and the Live Twin kind (`firestore_native_default`).
4. Set the env var contract the Python flagship harness reads
   (`G06_ENVIRONMENT`, `G06_PROVIDER_MODE`, `LIVE_TWIN_BACKEND`,
   `APP_ENV`, `G06_CLOUD_RUN_REVISION`, `G06_RUNTIME=cloudrun`,
   `G06_API_URL`).
5. Reuse the existing Python harness with `--mode happy` for the 19
   ALLOW rows and `--mode negative` for the 1 REFRESH_REQUIRED row.
6. Fail closed on any missing checkpoint. The in-memory preflight is
   kept on purpose as the integration layer below this shell.

### What is *not* in this PR

- The deployed Cloud Run wiring. issue #143 (CD), issue #134 (matrix).
- The production Vertex Gemini adapter. issue #2 (`#2`).
- Live Firestore Live Twin path. issue #18 (executor) is on main, but
  `LIVE_TWIN_BACKEND=firestore` is wired into `Settings` only and the
  Cloud Run service today does not exercise it.
- Visible 3D post-commit check. issue #180 and #225 feed default
  scenes; the deployed review worker is not in scope here.

The runner-side work above is the preparation; closure of #53 still
requires the production deployment run against the deployed stack.
