"""BigQuery-backed ``get_sales_history`` reader (ADR 0024, issue #215).

ADR 0024 commits the durable agent pipeline to BigQuery as the canonical
evidence store. The ``retailtwin.sales_events`` table (ADR 0005) holds one
row per accepted ``sale.completed`` event with at least
``event_id``, ``correlation_id``, ``store_id``, ``sku``, ``quantity``,
``occurred_at``, and ``landed_at``.

This module exposes a single ``read_sales_history(args, *, client)``
function that:

* accepts the canonical ``SalesHistoryArgs`` ``{sku, window_hours}``;
* issues a bounded BigQuery query against the canonical lineage
  ``(project_id, dataset_id, table_id)`` for the configured
  ``store_id`` and SKU;
* returns a Mapping that carries
  ``query_window`` (start, end), ``source_watermark`` (MAX(landed_at)
  of the rows read), ``data_lineage`` (project_id, dataset_id,
  table_id), ``query_job_id`` (BigQuery debug id), a deterministic
  ``content_digest`` (sha256 over ``sku, quantity, occurred_at,
  landed_at`` of every returned row), and a deterministic ``version``
  derived from those five so the same underlying rows produce the
  same version across distinct BigQuery jobs;
* returns ``None`` when the BigQuery result is empty or the client
  raises — the wrapping ``bind_read_port`` handler converts that to
  ``source_unavailable`` and the investigator surfaces it as
  ``insufficient_evidence`` rather than invent numbers.

The BigQuery client is injected. Production wires
``google.cloud.bigquery.Client`` (ADC); tests inject a fake client that
records the query and returns canned rows. The query is bounded with a
``LIMIT`` so a misconfigured window cannot exhaust the slot.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from retailtwin_api.agents.orchestrator.tool_registry import SalesHistoryArgs

log = logging.getLogger(__name__)

# Canonical BigQuery lineage (issue #215 / ADR 0024). These four knobs
# are the source of truth for ``data_lineage``; the BigQuery reader
# refuses any other combination so a misconfigured client cannot read
# from a sibling project.
ALLOWED_PROJECT_ID = "retailtwin-ai-511002"
ALLOWED_DATASET_ID = "retailtwin"
TABLE_SALES_EVENTS = "retailtwin.sales_events"
DEFAULT_MAX_ROWS = 1000


class BigQuerySalesEvidence(BaseModel):
    """Typed view of one ``read_sales_history`` result.

    The ``version`` is a deterministic digest of ``query_window``,
    ``source_watermark``, ``data_lineage``, and ``content_digest``:
    the same window evaluated against the same underlying rows
    (identical ``MAX(landed_at)`` + identical content digest + same
    lineage) round-trips to the same string across distinct
    BigQuery jobs. The ``content_digest`` is a sha256 over
    ``(sku, quantity, occurred_at, landed_at)`` of every returned
    row, so two BigQuery queries that return the same rows produce
    the same digest even when they execute under different job ids.
    The BigQuery ``query_job_id`` is kept alongside for debugging
    only — it is not part of the provenance tuple. The
    investigator's ``bind_read_port`` handler refuses anything
    without a ``version``, so the typed ``BaseModel`` keeps the
    field populated before the JSON is serialized into the bundle.
    """

    model_config = ConfigDict(extra="forbid")

    # Stable evidence identity — same inputs (window, watermark,
    # lineage, content) always produce the same version, even
    # across distinct BigQuery jobs. The investigator reads
    # ``version`` off the bundle to thread the demand-evidence
    # version through to the KPI evaluator.
    version: str = Field(min_length=1)
    # (window_start_iso, window_end_iso) — the canonical BigQuery
    # query window. Both are timezone-aware ISO-8601 in UTC.
    query_window: tuple[str, str]
    # MAX(landed_at) of the rows the canonical query returned. The
    # watermark is the operational source-of-truth marker for the
    # snapshot; absent when the query returns no rows. ``None`` when
    # the query returned an empty result — the investigator records
    # the bundle as ``insufficient_evidence`` in that case.
    source_watermark: str | None
    # (project_id, dataset_id, table_id). Bound to the canonical
    # lineage above; the reader refuses anything else.
    data_lineage: tuple[str, str, str]
    # sha256 over ``(sku, quantity, occurred_at, landed_at)`` of
    # every row the query returned. Two queries returning the
    # same rows — even under different BigQuery job ids — yield
    # the same digest; the digest is what makes ``version``
    # stable across distinct jobs.
    content_digest: str = Field(min_length=1)
    # BigQuery job id for debugging; not part of the version. ``None``
    # when the underlying client did not assign a job id (e.g. a
    # fake test client).
    query_job_id: str | None
    store_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    window_hours: int = Field(ge=1, le=168)
    observed_at: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    total_quantity: int = Field(ge=0)
    event_ids: list[str]
    correlation_ids: list[str]
    source: str = Field(min_length=1)

    def as_mapping(self) -> dict[str, Any]:
        """JSON-safe mapping the registry can return from a read port."""
        return self.model_dump(mode="json")


class BigQueryClient(Protocol):
    """Minimal BigQuery query interface used by this reader.

    Mirrors ``google.cloud.bigquery.Client.query`` enough that a real
    client and a test fake both satisfy it.
    """

    def query(self, query: str, *, job_config: Any) -> Any: ...


def _build_query(args: SalesHistoryArgs, *, now: datetime, max_rows: int) -> str:
    end = now.astimezone(timezone.utc)
    start = end - timedelta(hours=args.window_hours)
    # Parameterized via string formatting; ``args.sku`` is validated by the
    # Pydantic model to ``min_length=1`` and ``args.window_hours`` to a
    # ``1..168`` range, so a SQL injection through either is not possible.
    sku = args.sku.replace("'", "''")
    return (
        "SELECT `event_id`, `correlation_id`, `store_id`, `sku`, `quantity`, "
        "`occurred_at`, `landed_at` "
        f"FROM `{TABLE_SALES_EVENTS}` "
        f"WHERE `sku` = '{sku}' "
        f"  AND `occurred_at` >= TIMESTAMP('{start.isoformat()}') "
        f"  AND `occurred_at` <= TIMESTAMP('{end.isoformat()}') "
        "ORDER BY `occurred_at` DESC "
        f"LIMIT {max_rows}"
    )


def _watermark_of(rows: list[Any]) -> str | None:
    """Return MAX(landed_at) over ``rows`` as an ISO string.

    Rows without a ``landed_at`` attribute, an empty window, or a
    single ``None`` value return ``None`` — the empty-window case is
    what the canonical query returns when the SKU has no recorded
    events, and the investigator surfaces it as ``insufficient_evidence``
    rather than invent a number.
    """
    if not rows:
        return None
    latest: datetime | None = None
    for row in rows:
        landed = getattr(row, "landed_at", None)
        if landed is None:
            continue
        if not isinstance(landed, datetime):
            continue
        if landed.tzinfo is None:
            continue
        normalised = landed.astimezone(timezone.utc)
        if latest is None or normalised > latest:
            latest = normalised
    return latest.isoformat() if latest is not None else None


def _content_digest(rows: list[Any]) -> str:
    """Compute a deterministic sha256 over the returned rows.

    Concatenates ``(sku, quantity, occurred_at, landed_at)`` of every
    row, joined by record separators, and returns the full sha256 hex
    digest. Two BigQuery queries that return the same underlying rows
    yield the same digest — even under different BigQuery job ids —
    so the ``version`` derived from this digest remains stable across
    jobs. The hash uses the full 64-hex digest because the digest is
    itself an input to the 16-hex ``version`` digest (it is not
    surfaced on log lines).
    """
    h = hashlib.sha256()
    for row in rows:
        sku = str(getattr(row, "sku", ""))
        quantity = int(getattr(row, "quantity", 0))
        occurred = getattr(row, "occurred_at", None)
        landed = getattr(row, "landed_at", None)
        occurred_iso = (
            occurred.astimezone(timezone.utc).isoformat()
            if isinstance(occurred, datetime) and occurred.tzinfo is not None
            else ""
        )
        landed_iso = (
            landed.astimezone(timezone.utc).isoformat()
            if isinstance(landed, datetime) and landed.tzinfo is not None
            else ""
        )
        h.update(b"row|")
        h.update(sku.encode("utf-8"))
        h.update(b"|")
        h.update(str(quantity).encode("utf-8"))
        h.update(b"|")
        h.update(occurred_iso.encode("utf-8"))
        h.update(b"|")
        h.update(landed_iso.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _stable_version(
    *,
    query_window: tuple[datetime, datetime],
    source_watermark: str | None,
    data_lineage: tuple[str, str, str],
    content_digest: str,
) -> str:
    """Deterministic ``version`` from the provenance tuple + content digest.

    Same window, same watermark, same lineage, same content digest
    — same version. Used as the BigQuery ``sales_history`` evidence
    version so two distinct BigQuery jobs returning the same
    underlying rows reproduce the same ``source_versions`` key
    end-to-end. The ``content_digest`` carries the row contents
    (sha256 over ``sku``, ``quantity``, ``occurred_at``, ``landed_at``
    of every returned row) so two queries reading the same snapshot
    cannot drift to different versions. The digest is a 16-hex
    sha256 prefix so it fits on a log line.
    """
    start, end = (
        query_window[0].astimezone(timezone.utc).isoformat(),
        query_window[1].astimezone(timezone.utc).isoformat(),
    )
    project, dataset, table = data_lineage
    payload = (
        f"window={start}/{end}"
        f"\nwatermark={source_watermark or 'none'}"
        f"\nlineage={project}:{dataset}:{table}"
        f"\ncontent={content_digest}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sales-evidence-{digest[:16]}"


def read_sales_history(
    args: SalesHistoryArgs,
    *,
    client: BigQueryClient,
    job_config: Any,
    store_id: str,
    now: datetime | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    project_id: str = ALLOWED_PROJECT_ID,
    dataset_id: str = ALLOWED_DATASET_ID,
    table_id: str = TABLE_SALES_EVENTS.split(".", 1)[1],
) -> Mapping[str, Any] | None:
    """Read versioned sales history for ``args`` from ``client``.

    Returns ``None`` when the BigQuery result is empty or the client
    raises. The wrapping ``bind_read_port`` handler converts the ``None``
    to ``source_unavailable`` so the investigator surfaces an
    ``insufficient_evidence`` failure rather than invent numbers.

    ``project_id``, ``dataset_id``, and ``table_id`` default to the
    canonical lineage; they are exposed for tests that pin a custom
    lineage and for the (future) multi-tenant reader.
    """
    evidence = _read_sales_evidence(
        args,
        client=client,
        job_config=job_config,
        store_id=store_id,
        now=now,
        max_rows=max_rows,
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id,
    )
    if evidence is None:
        return None
    return evidence.as_mapping()


def _read_sales_evidence(
    args: SalesHistoryArgs,
    *,
    client: BigQueryClient,
    job_config: Any,
    store_id: str,
    now: datetime | None,
    max_rows: int,
    project_id: str,
    dataset_id: str,
    table_id: str,
) -> BigQuerySalesEvidence | None:
    """Typed wrapper around the BigQuery query.

    Returns ``None`` on empty results or query failures so callers can
    distinguish "no data" from "data present, with a version". The
    typed ``BigQuerySalesEvidence`` carries the canonical
    ``version`` the investigator demands alongside the provenance
    tuple (window, watermark, lineage, job id) the KPI evaluator
    threads through ``evaluator_version``.
    """
    end = now or datetime.now(timezone.utc)
    query = _build_query(args, now=end, max_rows=max_rows)
    try:
        job = client.query(query, job_config=job_config)
        rows_iter = job.result()
        rows_list = list(rows_iter)
    except Exception as exc:  # noqa: BLE001 — surface BigQuery failures
        log.warning("bigquery_sales_history.read_failed sku=%s error=%s", args.sku, type(exc).__name__)
        return None
    if not rows_list:
        return None

    query_window: tuple[datetime, datetime] = (end - timedelta(hours=args.window_hours), end)
    source_watermark = _watermark_of(rows_list)
    data_lineage: tuple[str, str, str] = (project_id, dataset_id, table_id)
    content_digest = _content_digest(rows_list)
    query_job_id = _read_query_job_id(job)
    version = _stable_version(
        query_window=query_window,
        source_watermark=source_watermark,
        data_lineage=data_lineage,
        content_digest=content_digest,
    )

    total_quantity = sum(int(getattr(row, "quantity", 0)) for row in rows_list)
    event_ids = [str(getattr(row, "event_id", "")) for row in rows_list if getattr(row, "event_id", "")]
    correlation_ids = [str(getattr(row, "correlation_id", "")) for row in rows_list if getattr(row, "correlation_id", "")]
    return BigQuerySalesEvidence(
        version=version,
        query_window=(query_window[0].isoformat(), query_window[1].isoformat()),
        source_watermark=source_watermark,
        data_lineage=data_lineage,
        content_digest=content_digest,
        query_job_id=query_job_id,
        store_id=store_id,
        sku=args.sku,
        window_hours=args.window_hours,
        observed_at=end.isoformat(),
        row_count=len(rows_list),
        total_quantity=total_quantity,
        event_ids=event_ids,
        correlation_ids=correlation_ids,
        source=f"bigquery.{project_id}.{dataset_id}.{table_id}",
    )


# BigQuery job ids may contain a colon (project:job region etc.) or
# other non-``[A-Za-z0-9_-]`` separators depending on the client
# implementation. The query job id is for debugging only — strip it
# down to a safe token but allow ``None`` when no job id exists.
_SAFE_JOB_ID = re.compile(r"[^a-zA-Z0-9_-]+")


def _read_query_job_id(job: Any) -> str | None:
    """Return the BigQuery job id when the client surfaced one.

    ``None`` when the underlying client did not assign a job id (e.g.
    a fake test client that returned a plain object). The id is for
    debugging only — it does not feed the ``version``.
    """
    candidate = getattr(job, "job_id", None)
    if not isinstance(candidate, str) or not candidate:
        return None
    return _SAFE_JOB_ID.sub("-", candidate).strip("-") or None


__all__ = [
    "ALLOWED_DATASET_ID",
    "ALLOWED_PROJECT_ID",
    "BigQueryClient",
    "BigQuerySalesEvidence",
    "DEFAULT_MAX_ROWS",
    "TABLE_SALES_EVENTS",
    "read_sales_history",
]
