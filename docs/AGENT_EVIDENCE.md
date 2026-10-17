# Agent Evidence Chain — P017 BigQuery demand evidence

> **Status date:** 2026-10-16
> **Owner:** Agent chain (issue #215, ADR 0024)
> **Replaces the hard-coded P017 sales history** in issue #30 / #31 / #32
> tests with a bounded BigQuery read against ``retailtwin.sales_events``
> (ADR 0005).

## 1. Purpose

Issue #215 ([P0][DATA-AI]) commits the agent evidence chain to
**BigQuery as the canonical demand-evidence store**. Every
investigation for a real ``sale.completed`` event now reads the
canonical ``retailtwin.sales_events`` window via the
``get_sales_history`` READ port and threads a **stable evidence
identity** (query window, source watermark, data lineage, **content
digest over the returned rows**) through the Investigator → Planner →
Simulation → KPI evaluator chain as ``evaluator_version``. The
content digest is a sha256 over ``(sku, quantity, occurred_at,
landed_at)`` of every returned row, so two distinct BigQuery jobs
returning the same rows produce the same ``version``. The BigQuery
job id is kept alongside as ``query_job_id`` for debugging only.

The hard-coded P017 sales numbers from issues #30 / #31 / #32 stay as
test fixtures; a real run never invents a number. When BigQuery is
empty, raises, or unreachable, the investigator surfaces
``sales_history_unavailable`` as ``insufficient_evidence`` and the
chain stops — it does not fabricate a recommendation.

## 2. Data path

```
┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  ┌──────────────────┐
│  Pub/Sub    │→ │   BQ        │→ │ Investigator    │→ │ Planner /        │
│  store-     │  │ retailtwin. │  │ get_sales_hrs.. │  │ Simulator /      │
│  events     │  │ sales_events│  │ + other reads   │  │ KPI evaluator    │
└─────────────┘  └─────────────┘  └─────────────────┘  └──────────────────┘
                                                        │
                                                        ▼
                                            SimulationKPIResult
                                                .evaluator_version
                                                = sales-evidence-<sha256 digest>
                                                  (BQ job id lives in
                                                   payload.query_job_id)
```

| Stage | Module | Field |
| ----- | ------ | ----- |
| BQ read | `apps/api/retailtwin_api/bigquery_sales_history.py::read_sales_history` | ``BigQuerySalesEvidence.version`` = sha256[16] of ``query_window`` + ``source_watermark`` + ``data_lineage`` + ``content_digest``; ``query_job_id`` kept for debugging |
| Investigator port | `apps/api/retailtwin_api/agents/investigator/evidence.py::bind_read_port("get_sales_history", ...)` | wraps the reader; ``None`` / exceptions → ``source_unavailable`` |
| Investigator bundle | `agents/investigator/evidence.py::_bundle` | ``EvidenceBundle.source_versions["sales_history"]`` = digest; full payload carries the four-field provenance tuple |
| Typed evidence planner | `agents/planner/plans.py::plan` | consumes ``EvidenceBundle``; ``Decision.evidence`` carries the digest + tuple |
| Simulator | `agents/simulator/branch.py::_demand_evidence_version` | reads ``decision.evidence[*].source_versions["sales_history"]`` (the digest) |
| KPI evaluator | `services/simulation/kpi/evaluator.py::evaluate_candidate` | accepts ``evaluator_version``; ``KpiResult.evaluator_version`` round-trips the digest |
| SimulationKPIResult | `contracts.py::SimulationKPIResult` | carries ``evaluator_version`` end-to-end |

### Provenance tuple (issue #215 / PR #253)

```python
BigQuerySalesEvidence(
    version="sales-evidence-<sha256[16]>",          # deterministic
    query_window=(start_iso, end_iso),              # 4h Saturday window
    source_watermark=MAX(landed_at),                # canonical snapshot marker
    data_lineage=(project_id, dataset_id, table_id),# retailtwin-ai-511002:retailtwin:sales_events
    content_digest="<sha256 of (sku,quantity,occurred_at,landed_at) per row>",
    query_job_id="bq-job-...",                      # BigQuery debug id (kept)
    sku="P017", window_hours=4,
    row_count=20, total_quantity=80,
    event_ids=[...], correlation_ids=[...],
    source="bigquery.retailtwin-ai-511002.retailtwin.sales_events",
)
```

The BigQuery job id alone is not a stable source snapshot — every
rerun gets a fresh id. The five-field evidence identity is
**deterministic and content-bound**: the same ``query_window``
evaluated against the same underlying rows (identical
``MAX(landed_at)`` + identical content digest + same lineage)
yields the same ``version`` across distinct BigQuery jobs. The
``content_digest`` is the load-bearing piece: it captures the
row contents (sha256 over ``sku``, ``quantity``, ``occurred_at``,
``landed_at`` for every returned row), so two queries reading the
same snapshot cannot drift to different versions even when they
execute under different BigQuery job ids. The ``query_job_id`` is
retained so a developer can jump to BigQuery to inspect the
actual job.

## 3. Provenance types

```python
# agents/investigator/evidence.py
SALES_HISTORY_UNAVAILABLE = "sales_history_unavailable"
DEMAND_EVIDENCE_SOURCE = "sales_history"

# services/simulation/kpi/evaluator.py
NO_DEMAND_EVIDENCE_VERSION = "none"

# agents/simulator/branch.py
NO_DEMAND_EVIDENCE_VERSION = "none"
```

The investigator's evidence bundle carries two maps:

* ``entity_versions`` (SKU → inventory version) — keyed by SKU, used
  by Planner / DCG / Executor.
* ``source_versions`` (source name → version) — keyed by source name
  (``sales_history``, ``forecast``); carries the demand-evidence
  ``version`` field the simulator threads into
  ``SimulationKPIResult.evaluator_version``.

When the BigQuery reader returns ``None`` or raises, the investigator
records an ``insufficient_evidence`` item with reason
``sales_history_unavailable``. The chain does not invent a quantity.

## 4. Live cloud test (production wiring)

Production calls the BigQuery-backed reader at startup. The wiring
lives in `apps/api/retailtwin_api/main.py::_wire_sales_history_port`:

* In production (``APP_ENV=production``) the helper constructs
  ``google.cloud.bigquery.Client`` (ADC) and binds the
  ``get_sales_history`` port on the autonomy and flagship registries.
* In dev / test / staging the BigQuery client is ``None``; the reader
  is bound to a function that returns ``None``. The investigator
  surfaces ``sales_history_unavailable`` and the chain still does
  not invent a number.

A live cloud test against the canonical P017 Saturday 4h window (20
rows × 4 units = 80 units) sets ``evaluator_version`` to the real
BigQuery job id, so the audit trail can prove which ``sales_events``
snapshot the candidate was scored against.

## 5. Failure modes

| Condition | Reader returns | Investigator surfaces | KPI evaluator |
| --------- | -------------- | --------------------- | ------------- |
| BQ empty | ``None`` | ``insufficient_evidence`` reason = ``sales_history_unavailable`` | chain fails closed |
| BQ raises | ``None`` (logged) | ``insufficient_evidence`` reason = ``sales_history_unavailable`` | chain fails closed |
| BQ missing job id | deterministic digest | ``sales_history`` item with ``version`` = digest | evaluator threads digest |
| Different BQ job, same rows | same digest, same version | identical ``source_versions`` entry | identical ``evaluator_version` |
| Dev / no ADC | port returns ``None`` | ``insufficient_evidence`` reason = ``sales_history_unavailable`` | chain fails closed |
| Legacy callers | ``NO_DEMAND_EVIDENCE_VERSION`` = ``"none"`` | unchanged | unchanged |

## 6. Tests

* `apps/api/tests/test_bigquery_sales_history.py` — reader unit tests
  (query shape, empty / error → ``None``, P017 Saturday 80-unit
  fixture, Pydantic round-trip, determinism across runs,
  `test_sales_evidence_version_is_stable_across_query_jobs`
  regression — same rows under two distinct BigQuery job ids
  yield the same ``version``).
* `apps/api/tests/test_investigator.py::TestInvestigatorBigQuerySalesHistory`
  — investigator integration: fake BigQuery client returns P017 rows;
  assert evidence bundle carries version + SKU + sum. Empty BQ and
  BQ errors both surface ``sales_history_unavailable``. Two
  ``run_id`` runs return identical bundles (no duplication).
* `apps/api/tests/test_simulator.py::TestSimulatorEvaluatorVersion` —
  simulator threads ``decision.evidence[*].source_versions["sales_history"]``
  into ``SimulationKPIResult.evaluator_version``.
* `apps/api/tests/test_simulation_routes.py::TestSimulationKPIEvaluatorVersion`
  — ``SimulationKPIResult`` round-trips ``evaluator_version``.
* `services/simulation/tests/test_kpi.py::TestEvaluatorVersionProvenance`
  — canonical ``KpiResult.evaluator_version`` round-trips; default
  is ``NO_DEMAND_EVIDENCE_VERSION``; JSON schema accepts the field.

## 7. ADR references

* **ADR 0024** — durable agent pipeline (this issue's umbrella).
* **ADR 0005** — ``retailtwin.sales_events`` canonical table.
* **ADR 0011** — investigator evidence bundle (no guessing).
* **ADR 0014** — Decision Context Guard (rejects insufficient
  evidence).
* **ADR 0023** — autonomous event path (no Live reset).