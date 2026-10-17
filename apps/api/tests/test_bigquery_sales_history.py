"""Tests for the BigQuery-backed ``get_sales_history`` reader (ADR 0024).

Uses an in-memory ``FakeBigQueryClient`` that records the issued query and
returns canned rows. Covers the bounded query shape, the
empty/error → ``None`` contract, the typed ``BigQuerySalesEvidence``
schema, and the provenance-tuple ``version`` invariants (issue #215).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from retailtwin_api.agents.orchestrator.tool_registry import SalesHistoryArgs
from retailtwin_api.bigquery_sales_history import (
    ALLOWED_DATASET_ID,
    ALLOWED_PROJECT_ID,
    DEFAULT_MAX_ROWS,
    TABLE_SALES_EVENTS,
    BigQuerySalesEvidence,
    read_sales_history,
)


class _FakeRow(SimpleNamespace):
    """A BigQuery row with the canonical fields."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class FakeBigQueryClient:
    """Records every ``query`` call and returns canned rows.

    ``row_factory`` is a callable: ``(query) -> list[_FakeRow]``. ``raise_on_query``
    raises a specific exception when set. Each call can return an
    independently configurable ``job_id`` and ``watermark_factory`` so
    callers can exercise different ``source_watermark`` / lineage
    combinations.

    ``job_ids`` is an optional sequence of job ids; when supplied, the
    Nth call returns the Nth id (wrapping with the last entry when the
    sequence is exhausted). This lets a single fake client simulate two
    distinct BigQuery jobs without having to spin up a second client.
    """

    def __init__(
        self,
        *,
        row_factory: Any = None,
        raise_on_query: type[BaseException] | None = None,
        job_id: str = "bq-job-test",
        job_ids: Sequence[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._row_factory = row_factory
        self._raise_on_query = raise_on_query
        self._job_id = job_id
        self._job_ids: Sequence[str] | None = job_ids

    def query(self, query: str, *, job_config: Any) -> Any:
        self.calls.append(query)
        if self._raise_on_query is not None:
            raise self._raise_on_query("bq-error")
        rows = self._row_factory(query) if self._row_factory else []
        if self._job_ids is not None:
            index = len(self.calls) - 1
            if index < len(self._job_ids):
                job_id = self._job_ids[index]
            else:
                job_id = self._job_ids[-1]
        else:
            job_id = self._job_id

        class _Job:
            def result(self_inner: Any) -> Any:
                return iter(rows)

        return SimpleNamespace(job_id=job_id, result=_Job().result)


def _args(sku: str = "P017", window_hours: int = 4) -> SalesHistoryArgs:
    return SalesHistoryArgs(sku=sku, window_hours=window_hours)


def _now() -> datetime:
    return datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _saturday_rows(
    *,
    landed_at: datetime | None = _now(),
    count: int = 20,
    quantity: int = 4,
) -> list[_FakeRow]:
    return [
        _FakeRow(
            event_id=f"evt-saturday-{i}",
            correlation_id="run-weekend-demand-surge-1",
            sku="P017",
            quantity=quantity,
            occurred_at=_now(),
            landed_at=landed_at,
        )
        for i in range(count)
    ]


class TestReadSalesHistoryShape:
    def test_query_targets_canonical_table(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: [])
        read_sales_history(
            _args(), client=client, job_config=None, store_id="store-001", now=_now()
        )
        assert TABLE_SALES_EVENTS in client.calls[0]
        assert "P017" in client.calls[0]

    def test_query_binds_window(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: [])
        read_sales_history(
            _args(window_hours=24), client=client, job_config=None, store_id="store-001", now=_now()
        )
        assert "TIMESTAMP(" in client.calls[0]
        assert "AND " in client.calls[0]
        assert "ORDER BY" in client.calls[0]

    def test_query_is_bounded_with_limit(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: [])
        read_sales_history(
            _args(),
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
            max_rows=DEFAULT_MAX_ROWS,
        )
        assert f"LIMIT {DEFAULT_MAX_ROWS}" in client.calls[0]

    def test_query_selects_landed_at_for_watermark(self) -> None:
        """The SELECT list must include ``landed_at`` so the reader
        can compute MAX(landed_at) as the source watermark."""
        client = FakeBigQueryClient(row_factory=lambda q: [])
        read_sales_history(
            _args(), client=client, job_config=None, store_id="store-001", now=_now()
        )
        assert "landed_at" in client.calls[0]


class TestReadSalesHistoryReturn:
    def test_returns_versioned_mapping_when_rows_present(self) -> None:
        rows = _saturday_rows()
        client = FakeBigQueryClient(row_factory=lambda q: rows)
        result = read_sales_history(
            _args(), client=client, job_config=None, store_id="store-001", now=_now()
        )
        assert result is not None
        # Issue #215: the BigQuery job id moves to ``query_job_id``;
        # ``version`` is now a deterministic digest of the provenance
        # tuple so reruns against the same snapshot reproduce.
        assert result["query_job_id"] == "bq-job-test"
        assert result["version"].startswith("sales-evidence-")
        assert result["row_count"] == 20
        assert result["total_quantity"] == 80
        assert result["sku"] == "P017"
        assert result["window_hours"] == 4

    def test_returns_none_when_no_rows(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: [])
        assert read_sales_history(
            _args(), client=client, job_config=None, store_id="store-001", now=_now()
        ) is None

    def test_returns_none_on_client_error(self) -> None:
        client = FakeBigQueryClient(raise_on_query=RuntimeError)
        assert read_sales_history(
            _args(), client=client, job_config=None, store_id="store-001", now=_now()
        ) is None


class TestReadSalesHistoryP017Canonical:
    """The canonical weekend-surge fixture used by issue #30 / #32 / #33.

    Verifies the reader returns the versioned payload that downstream
    code consumes when investigating the P017 surge scenario.
    """

    def test_p017_saturday_surge_total_matches_canonical_numbers(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: _saturday_rows())
        result = read_sales_history(
            _args(window_hours=4),
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        assert result is not None
        # 20 rows × 4 units = 80 units sold in the canonical 4h window.
        assert result["total_quantity"] == 80
        assert result["row_count"] == 20
        assert result["correlation_ids"] == ["run-weekend-demand-surge-1"] * 20


class TestBigQuerySalesEvidenceTyped:
    """Issue #215: the BigQuery reader output is a Pydantic-typed mapping.

    ``BigQuerySalesEvidence`` is the canonical typed view of one
    ``read_sales_history`` result. The investigator's ``bind_read_port``
    handler refuses anything without a ``version``; the typed model
    guarantees the field is present before the mapping is serialized
    into the evidence bundle.
    """

    def test_round_trip_preserves_canonical_fields(self) -> None:
        client = FakeBigQueryClient(row_factory=lambda q: _saturday_rows())
        result = read_sales_history(
            _args(window_hours=4),
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        assert result is not None
        evidence = BigQuerySalesEvidence.model_validate(result)
        assert evidence.version.startswith("sales-evidence-")
        assert evidence.query_job_id == "bq-job-test"
        assert evidence.sku == "P017"
        assert evidence.store_id == "store-001"
        assert evidence.window_hours == 4
        assert evidence.total_quantity == 80
        assert evidence.row_count == 20
        assert evidence.source == f"bigquery.{ALLOWED_PROJECT_ID}.{ALLOWED_DATASET_ID}.sales_events"
        # Round-trip via ``as_mapping`` keeps the same shape the registry
        # serializes into the tool result.
        assert evidence.as_mapping()["version"].startswith("sales-evidence-")
        assert evidence.as_mapping()["total_quantity"] == 80

    def test_typed_model_rejects_missing_version(self) -> None:
        with pytest.raises(ValidationError):
            BigQuerySalesEvidence.model_validate(
                {
                    "store_id": "store-001",
                    "sku": "P017",
                    "window_hours": 4,
                    "observed_at": _now().isoformat(),
                    "row_count": 0,
                    "total_quantity": 0,
                    "event_ids": [],
                    "correlation_ids": [],
                    "source": "bigquery.retailtwin.sales_events",
                }
            )


class TestReadSalesHistoryDeterminism:
    """Issue #215: the same ``run_id`` runs twice must reproduce the same result.

    The Investigator is the source of evidence — it must not duplicate
    state. The reader's determinism is exercised by running two queries
    against a fake client that returns the same rows and asserting the
    ``version`` + totals are byte-identical.
    """

    def test_two_runs_against_same_rows_return_identical_evidence(self) -> None:
        rows = _saturday_rows()
        client = FakeBigQueryClient(row_factory=lambda q: rows)
        args = _args(window_hours=4)
        first = read_sales_history(
            args,
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        second = read_sales_history(
            args,
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        assert first == second
        assert first is not None
        assert second is not None
        assert first["query_job_id"] == "bq-job-test"
        assert first["total_quantity"] == 80
        assert second["total_quantity"] == 80
        # No duplication: the BigQuery client saw two queries (the
        # reader is stateless), but the returned mapping is identical
        # so the investigator's bundle does not gain extra entries.
        assert len(client.calls) == 2


# ─── issue #215 — provenance = window + watermark + lineage + job_id ────────


class TestSalesEvidenceProvenance:
    """Issue #215 / PR #253 review: the sales evidence version must
    carry the query window, the source watermark (MAX(landed_at)), and
    the data lineage alongside (still kept) the BigQuery job id.

    The fix moves ``version`` from ``job_id`` to a deterministic digest
    of ``query_window``, ``source_watermark``, and ``data_lineage`` so
    a rerun against the same snapshot reproduces the same string. The
    job id stays under ``query_job_id`` for debugging.
    """

    def test_sales_evidence_carries_window_watermark_lineage(self) -> None:
        """All four fields are present, typed, and round-trip through
        the registry's ``as_mapping``."""
        saturday_landed = datetime(2026, 10, 10, 11, 55, 0, tzinfo=timezone.utc)
        client = FakeBigQueryClient(row_factory=lambda q: _saturday_rows(landed_at=saturday_landed))
        result = read_sales_history(
            _args(window_hours=4),
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        assert result is not None

        # ``query_window`` is a (start_iso, end_iso) tuple.
        assert isinstance(result["query_window"], list)
        assert len(result["query_window"]) == 2
        window_start, window_end = result["query_window"]
        assert window_start.endswith("Z") or "+" in window_start
        assert window_end.endswith("Z") or "+" in window_end
        parsed_start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        parsed_end = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        # The canonical 4h window: [now - 4h, now].
        assert parsed_end - parsed_start == timedelta(hours=4)
        assert parsed_end == _now().astimezone(timezone.utc)

        # ``source_watermark`` is MAX(landed_at) over the returned rows.
        assert result["source_watermark"] is not None
        watermark = datetime.fromisoformat(result["source_watermark"].replace("Z", "+00:00"))
        assert watermark == saturday_landed.astimezone(timezone.utc)

        # ``data_lineage`` is the canonical (project_id, dataset_id, table_id).
        assert result["data_lineage"] == [ALLOWED_PROJECT_ID, ALLOWED_DATASET_ID, "sales_events"]

        # ``content_digest`` is a deterministic sha256 over the row contents.
        assert isinstance(result["content_digest"], str)
        assert len(result["content_digest"]) == 64
        assert all(character in "0123456789abcdef" for character in result["content_digest"])

        # ``query_job_id`` is the BigQuery debugging id (kept alongside).
        assert result["query_job_id"] == "bq-job-test"

        # The typed schema enforces the five fields and rejects extras.
        evidence = BigQuerySalesEvidence.model_validate(result)
        assert evidence.query_window == (window_start, window_end)
        assert evidence.source_watermark == result["source_watermark"]
        assert evidence.data_lineage == (ALLOWED_PROJECT_ID, ALLOWED_DATASET_ID, "sales_events")
        assert evidence.content_digest == result["content_digest"]
        assert evidence.query_job_id == "bq-job-test"

    def test_sales_evidence_is_deterministic_for_same_inputs(self) -> None:
        """Same window + same watermark + same lineage + same fake
        client → same evidence mapping (issue #215 stable provenance)."""
        saturday_landed = datetime(2026, 10, 10, 11, 55, 0, tzinfo=timezone.utc)
        client = FakeBigQueryClient(row_factory=lambda q: _saturday_rows(landed_at=saturday_landed))
        args = _args(window_hours=4)

        first = read_sales_history(
            args, client=client, job_config=None, store_id="store-001", now=_now()
        )
        second = read_sales_history(
            args, client=client, job_config=None, store_id="store-001", now=_now()
        )

        # The full mapping, including the new provenance fields, is
        # byte-identical across reruns.
        assert first == second
        assert first is not None
        # ``version`` is now a deterministic digest, so it is identical
        # between the two runs (was the BigQuery job id before the
        # change-requested fix).
        assert first["version"] == second["version"]
        assert first["version"].startswith("sales-evidence-")
        # ``query_job_id`` stayed as the BigQuery debug id.
        assert first["query_job_id"] == "bq-job-test"

    def test_sales_evidence_distinguishes_query_jobs(self) -> None:
        """Different windows → different watermarks → different versions.

        Two queries against different ``now`` values read different rows
        and therefore different ``MAX(landed_at)``; the stable
        ``version`` digest must reflect that, even when the underlying
        ``query_job_id`` is reused.
        """
        early_landed = datetime(2026, 10, 9, 9, 30, 0, tzinfo=timezone.utc)
        late_landed = datetime(2026, 10, 10, 11, 55, 0, tzinfo=timezone.utc)
        early_client = FakeBigQueryClient(
            row_factory=lambda q: _saturday_rows(landed_at=early_landed),
            job_id="bq-job-shared",
        )
        late_client = FakeBigQueryClient(
            row_factory=lambda q: _saturday_rows(landed_at=late_landed),
            job_id="bq-job-shared",
        )

        early_window = datetime(2026, 10, 10, 4, 0, 0, tzinfo=timezone.utc)
        late_window = _now()

        early = read_sales_history(
            _args(window_hours=4),
            client=early_client,
            job_config=None,
            store_id="store-001",
            now=early_window,
        )
        late = read_sales_history(
            _args(window_hours=4),
            client=late_client,
            job_config=None,
            store_id="store-001",
            now=late_window,
        )

        assert early is not None and late is not None
        # Different watermarks → different versions even though the
        # shared fake client supplied the same job id.
        assert early["source_watermark"] != late["source_watermark"]
        assert early["version"] != late["version"]
        # ``query_job_id`` is intentionally the same — version must
        # still differ because it carries the watermark.
        assert early["query_job_id"] == late["query_job_id"] == "bq-job-shared"

    def test_sales_evidence_version_is_stable_across_query_jobs(self) -> None:
        """Issue #215 / PR #253 review (16:13 UTC): the same underlying
        source data MUST yield the same ``version`` across distinct
        BigQuery jobs.

        Two distinct BigQuery job ids (``bq-job-A`` and ``bq-job-B``)
        against the fake client return the SAME underlying rows for the
        SAME window. The resulting ``BigQuerySalesEvidence`` MUST share:

        * ``query_window``
        * ``source_watermark``
        * ``data_lineage``
        * ``content_digest``
        * ``version``

        while ``query_job_id`` MUST differ (it is per-execution and
        cannot be stable). This is the regression test the second
        CHANGES_REQUESTED review demanded.
        """

        rows = _saturday_rows()
        # Two distinct BigQuery job ids issued for two different
        # queries; the fake client returns the SAME rows for both.
        client = FakeBigQueryClient(
            row_factory=lambda q: rows,
            job_ids=("bq-job-A", "bq-job-B"),
        )
        args = _args(window_hours=4)

        first = read_sales_history(
            args,
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )
        second = read_sales_history(
            args,
            client=client,
            job_config=None,
            store_id="store-001",
            now=_now(),
        )

        assert first is not None
        assert second is not None

        # Stable provenance — same window + same watermark + same
        # lineage + same content.
        assert first["query_window"] == second["query_window"]
        assert first["source_watermark"] == second["source_watermark"]
        assert first["data_lineage"] == second["data_lineage"]
        assert first["content_digest"] == second["content_digest"]

        # The load-bearing assertion: same rows → same version, even
        # when the BigQuery job id differs.
        assert first["version"] == second["version"]
        assert first["version"].startswith("sales-evidence-")

        # The job ids MUST differ (the fake client simulates two
        # distinct jobs); the version stays the same.
        assert first["query_job_id"] == "bq-job-A"
        assert second["query_job_id"] == "bq-job-B"
        assert first["query_job_id"] != second["query_job_id"]

        # Two queries landed against the fake client.
        assert len(client.calls) == 2
