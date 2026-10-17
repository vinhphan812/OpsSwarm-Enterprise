"""Read-only evidence collector for the Day-0 Foundation Gate (issue #10).

This script proves that the production cloud path works end to end against
project ``retailtwin-ai-511002`` in ``us-central1``. It is invoked by
``scripts/verify-day0-gate.sh`` and emits one JSON document per run.

The script does not write to Firestore, BigQuery, Pub/Sub, or Vertex AI
beyond what an integrated smoke test already does (publishing one
``sale.completed`` event and running one Vertex ``get_inventory`` read).

Every check is wrapped in a ``Check`` context manager that records PASS,
FAIL, or SKIPPED with a message and optional ``details`` payload. The
final JSON document has the shape:

    {
      "run_id": "...",            # ISO 8601 timestamp + short hex suffix
      "started_at": "...",
      "finished_at": "...",
      "project": "retailtwin-ai-511002",
      "region": "us-central1",
      "vertex_model": "gemini-2.5-flash",
      "checks": [
         {"id": "cloud-run", "status": "PASS", "message": "...", "details": {...}},
         ...
      ],
      "summary": {"pass": 6, "fail": 0, "skipped": 0}
    }

Exit codes:
  0  every required check PASS
  1  at least one required check FAIL
  2  a precondition (project, ADC, npm) was not met
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ── Constants ─────────────────────────────────────────────────────────────────
CANONICAL_PROJECT = "retailtwin-ai-511002"
CANONICAL_REGION = "us-central1"
CANONICAL_STORE = "store-001"
CANONICAL_SKU = "P001"
VERTEX_MODEL = os.environ.get("DAY0_VERTEX_MODEL", "gemini-2.5-flash")
PIPELINE_TOPIC = os.environ.get("DAY0_TOPIC", "store-events")
BIGQUERY_DATASET = os.environ.get("DAY0_DATASET", "retailtwin")
BIGQUERY_TABLE = os.environ.get("DAY0_TABLE", "sales_events")
MAX_BILLING_BYTES = 100_000_000
EVIDENCE_SCHEMA_VERSION = 1


# ── Evidence model ────────────────────────────────────────────────────────────
@dataclass
class CheckRecord:
    id: str
    status: str  # "pass" | "fail" | "skipped"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class EvidenceLog:
    """Accumulates Check records and serializes them to a JSON file."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.started_at = _now_iso()
        self.checks: list[CheckRecord] = []
        self.skipped_checks: list[CheckRecord] = []

    def add(self, record: CheckRecord) -> None:
        self.checks.append(record)

    def summary(self) -> dict[str, int]:
        passed = sum(1 for c in self.checks if c.status == "pass")
        failed = sum(1 for c in self.checks if c.status == "fail")
        skipped = sum(1 for c in self.checks if c.status == "skipped")
        return {"pass": passed, "fail": failed, "skipped": skipped}

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": _now_iso(),
            "project": CANONICAL_PROJECT,
            "region": CANONICAL_REGION,
            "vertex_model": VERTEX_MODEL,
            "checks": [
                {
                    "id": c.id,
                    "status": c.status,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
            "summary": self.summary(),
        }


@contextmanager
def check(log: EvidenceLog, check_id: str):
    """Run a block as one named check and record its outcome.

    The block must call ``record(...)`` with status and message, or raise.
    On uncaught exception the check is recorded as FAIL with the exception
    text (without secrets).
    """
    try:
        yield None
    except _PreconditionError as exc:
        log.add(CheckRecord(check_id, "skipped", str(exc)))
        raise
    except Exception as exc:
        log.add(CheckRecord(check_id, "fail", f"{type(exc).__name__}: {exc}"))
    else:
        # Status was set inside the block via record(); if not, mark as skipped.
        last = next((c for c in reversed(log.checks) if c.id == check_id), None)
        if last is None:
            log.add(CheckRecord(check_id, "skipped", "no status recorded"))
    finally:
        pass


def record(log: EvidenceLog, check_id: str, status: str, message: str, **details: Any) -> None:
    """Append or update a CheckRecord with explicit status."""
    log.add(CheckRecord(check_id, status, message, details))


class _PreconditionError(Exception):
    """Raised when a precondition for the gate is missing."""


# ── Helpers ──────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(2).hex()}"


def _gcloud(args: list[str], *, check: bool = True) -> str:
    """Run a gcloud command and return stdout. Raises on error.

    Subcommands that target a resource (``services``, ``firestore``,
    ``pubsub``, etc.) accept ``--project``. Property getters like
    ``config get-value`` do not, so we strip the project flag for those.
    """
    if args and args[0] == "config":
        cmd = ["gcloud", *args]
    else:
        cmd = ["gcloud", *args, "--project", CANONICAL_PROJECT, "--format=value"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"},
    )
    return proc.stdout.strip()


def _http_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GET {url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GET {url} did not return JSON: {exc}") from exc


def _access_token() -> str:
    proc = subprocess.run(
        ["gcloud", "auth", "print-access-token", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise _PreconditionError(
            f"gcloud auth print-access-token failed: {proc.stderr.strip()}"
        )
    token = proc.stdout.strip()
    if not token:
        raise _PreconditionError("gcloud returned an empty access token")
    return token


def _active_account() -> str:
    proc = subprocess.run(
        ["gcloud", "config", "get-value", "account"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise _PreconditionError("gcloud config get-value account failed")
    return proc.stdout.strip()


def _bq_query(query: str) -> list[dict[str, Any]]:
    # The ``bq`` wrapper script re-parses the command line; calling it via
    # ``shell=True`` with a single string sidesteps the wrapper's argument
    # splitter, which otherwise flags ``--maximum_bytes_billed`` as
    # "appears after final command line argument". ``shlex.quote`` keeps
    # the query safe.
    import shlex

    cmd = (
        f"bq --project_id={shlex.quote(CANONICAL_PROJECT)} "
        f"--format=json query --use_legacy_sql=false "
        f"--maximum_bytes_billed={MAX_BILLING_BYTES} {shlex.quote(query)}"
    )
    proc = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"bq query failed (rc={proc.returncode}): "
            f"stdout={proc.stdout.strip()[:200]} stderr={proc.stderr.strip()[:300]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bq query did not return JSON: {exc}") from exc


def _check_preconditions() -> None:
    """Reject if the caller is not on the canonical project or cannot read it.

    The Day-0 Gate is capability-based: any gcloud identity that can
    read the canonical project, read ``stores/store-001`` in Firestore,
    and query ``retailtwinsales_events`` in BigQuery is accepted. The
    previous version hard-coded one human account; the new version
    accepts the configured ADC identity (gcloud user account, WIF
    impersonation, self-hosted runner service account, etc.) so the
    gate can run from CI, the WIF provider, or another authorized
    maintainer.

    An optional ``DAY0_REQUIRED_ACCOUNTS`` env var can pin execution
    to one or more specific accounts (comma-separated). When unset, any
    account with the required IAM is accepted.
    """
    project = _gcloud(["config", "get-value", "project"])
    if project != CANONICAL_PROJECT:
        raise _PreconditionError(
            f"Refusing project {project!r}. Day-0 Gate is locked to "
            f"{CANONICAL_PROJECT}."
        )
    required = os.environ.get("DAY0_REQUIRED_ACCOUNTS", "").strip()
    if required:
        account = _active_account()
        allowed = {a.strip() for a in required.split(",") if a.strip()}
        if account not in allowed:
            raise _PreconditionError(
                f"Refusing to run as {account!r}. "
                f"DAY0_REQUIRED_ACCOUNTS={sorted(allowed)}."
            )
    # Capability probes: cheap, read-only, and prove the identity can
    # actually read what the gate depends on. Failures raise and abort.
    _assert_can_read_firestore()
    _assert_can_query_bigquery()


def _assert_can_read_firestore() -> None:
    """Refuse the gate if the active identity cannot read Firestore stores/store-001."""
    token = _access_token()
    url = (
        f"https://firestore.googleapis.com/v1/projects/{CANONICAL_PROJECT}"
        f"/databases/(default)/documents/stores/{CANONICAL_STORE}"
    )
    try:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status == 403:
                raise _PreconditionError(
                    f"Firestore GET stores/{CANONICAL_STORE} returned HTTP 403. "
                    "The active gcloud identity does not have datastore.user "
                    f"on {CANONICAL_PROJECT}. Run `gcloud auth login` as a "
                    "user with that role or impersonate the runtime SA."
                )
            if response.status >= 500:
                raise _PreconditionError(
                    f"Firestore GET stores/{CANONICAL_STORE} returned HTTP "
                    f"{response.status}; Firestore is unreachable from this host."
                )
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise _PreconditionError(
                f"Firestore GET returned HTTP 403 (active identity lacks "
                f"datastore.user on {CANONICAL_PROJECT})."
            ) from exc
        raise _PreconditionError(
            f"Firestore GET returned HTTP {exc.code}; the gate cannot verify "
            f"the identity's IAM from this host."
        ) from exc
    except urllib.error.URLError as exc:
        raise _PreconditionError(
            f"Firestore is unreachable from this host: {exc.reason}. "
            "The Day-0 Gate requires a path to Firestore."
        ) from exc


def _assert_can_query_bigquery() -> None:
    """Refuse the gate if the active identity cannot query BigQuery sales."""
    try:
        rows = _bq_query(
            f"SELECT 1 AS one FROM `{CANONICAL_PROJECT}.{BIGQUERY_DATASET}."
            f"{BIGQUERY_TABLE}` LIMIT 1"
        )
        if not isinstance(rows, list):
            raise _PreconditionError(
                "BigQuery SELECT did not return a list; the active identity "
                "may be missing bigquery.user on the canonical dataset."
            )
    except RuntimeError as exc:
        raise _PreconditionError(
            f"BigQuery probe failed: {exc}. The Day-0 Gate requires "
            f"bigquery.user on {CANONICAL_PROJECT}:{BIGQUERY_DATASET}."
        ) from exc


# ── Individual checks ────────────────────────────────────────────────────────
def check_cloud_run_service(log: EvidenceLog, *, url: str) -> None:
    """Hit /health on the deployed Cloud Run service and verify production state."""
    with check(log, "cloud-run"):
        health = _http_json(f"{url.rstrip('/')}/health")
        if health.get("app_env") != "production":
            raise RuntimeError(f"Cloud Run app_env is {health.get('app_env')!r}, expected production")
        if not health.get("fixture_loaded"):
            raise RuntimeError("Cloud Run fixture_loaded is false")
        store_resp = _http_json(f"{url.rstrip('/')}/store")
        products = store_resp.get("products", [])
        sku = next((p for p in products if p.get("sku") == CANONICAL_SKU), None)
        if sku is None:
            raise RuntimeError(f"Cloud Run /store did not return {CANONICAL_SKU}")
        record(
            log,
            "cloud-run",
            "pass",
            f"Deployed service {url} reports production + {CANONICAL_SKU}",
            service_url=url,
            store_context_version=store_resp.get("context_version"),
            p001=sku,
        )


def check_firestore_p001(log: EvidenceLog) -> None:
    """Read stores/store-001/inventory/P001 directly via Firestore REST."""
    with check(log, "firestore-p001"):
        token = _access_token()
        headers = {"Authorization": f"Bearer {token}"}
        store_url = (
            f"https://firestore.googleapis.com/v1/projects/{CANONICAL_PROJECT}"
            f"/databases/(default)/documents/stores/{CANONICAL_STORE}"
        )
        inv_url = (
            f"https://firestore.googleapis.com/v1/projects/{CANONICAL_PROJECT}"
            f"/databases/(default)/documents/stores/{CANONICAL_STORE}/inventory/{CANONICAL_SKU}"
        )
        store = _http_json(store_url, headers=headers)
        inventory = _http_json(inv_url, headers=headers)
        fields = inventory.get("fields", {})
        required = {
            "sku", "shelf_id", "slot_id", "facings",
            "shelf_quantity", "backroom_quantity", "version", "store_id",
        }
        missing = [k for k in required if k not in fields]
        if missing:
            raise RuntimeError(f"Firestore P001 missing fields: {missing}")
        record(
            log,
            "firestore-p001",
            "pass",
            f"Firestore stores/{CANONICAL_STORE}/inventory/{CANONICAL_SKU} present",
            store_document={
                "name": store.get("name"),
                "version": store.get("fields", {}).get("version", {}).get("stringValue"),
            },
            inventory_fields={
                k: fields.get(k, {}).get("stringValue") or fields.get(k, {}).get("integerValue")
                for k in required
            },
        )


def check_local_api_firestore(log: EvidenceLog) -> None:
    """Boot the API locally with LIVE_TWIN_BACKEND=firestore and verify /store.

    The local process is started on a free port and torn down before
    returning. ADC must already be configured for the canonical project.
    """
    with check(log, "local-api-firestore"):
        port = _free_port()
        env = {
            **os.environ,
            "APP_ENV": "e2e-smoke",
            "LIVE_TWIN_BACKEND": "firestore",
            "AUTONOMY_ENABLED": "false",
            "GOOGLE_CLOUD_PROJECT": CANONICAL_PROJECT,
            "GOOGLE_CLOUD_LOCATION": CANONICAL_REGION,
            "API_HOST": "127.0.0.1",
            "API_PORT": str(port),
            "STORE_ID": CANONICAL_STORE,
            "LOG_LEVEL": "WARNING",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "apps" / "api"),
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "retailtwin_api"],
            env=env,
            cwd=str(Path(__file__).resolve().parents[1] / "apps" / "api"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            if not _wait_for_health(base_url, timeout_s=30):
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:500] if proc.stderr else ""
                raise RuntimeError(f"Local API failed to start. stderr: {stderr}")
            store = _http_json(f"{base_url}/store")
            products = store.get("products", [])
            sku = next((p for p in products if p.get("sku") == CANONICAL_SKU), None)
            if sku is None:
                raise RuntimeError(
                    f"Local API (firestore backend) did not return {CANONICAL_SKU}"
                )
            record(
                log,
                "local-api-firestore",
                "pass",
                f"Local API LIVE_TWIN_BACKEND=firestore returned {CANONICAL_SKU}",
                context_version=store.get("context_version"),
                p001=sku,
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def check_pubsub_event_path(log: EvidenceLog) -> None:
    """Publish one sale.completed event and verify the Pub/Sub delivery path.

    The Day-0 contract is that ``backbone_cli.py publish`` lands the
    event on topic ``store-events`` with the ordering key set, and the
    message is then delivered to subscription ``store-events-analytics``.
    The analytics lander (a separate process) is responsible for the
    BigQuery row.

    By default the gate records a PASS on the publish + delivery leg
    and surfaces whether the BigQuery row was landed as ``bq_landed``.
    When ``DAY0_REQUIRE_BQ_ROW=1`` is set the BigQuery row is required:
    a missing row fails the check. The env var is off by default so
    the gate does not depend on a long-running lander process; CI and
    ops can flip it on when the lander is known to be up.
    """
    with check(log, "pubsub-event-path"):
        event_id = f"day0-gate-{_run_id().lower()}"
        correlation_id = f"run-day0-gate-{int(time.time())}"
        fixture = {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "event_type": "sale.completed",
            "store_id": CANONICAL_STORE,
            "sku": CANONICAL_SKU,
            "quantity": 1,
            "occurred_at": _now_iso(),
            "source": "day0-gate",
        }
        fixture_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"day0-{event_id}.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "retailtwin_api.backbone_cli",
                    "publish", "--fixture", str(fixture_path),
                ],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "apps" / "api"),
                },
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"backbone_cli publish failed: {proc.stderr.strip()[:300]}"
                )
            # Subscription should receive the message within 30 s.
            delivered = None
            for _ in range(6):
                time.sleep(5)
                pull_proc = subprocess.run(
                    [
                        "gcloud", "pubsub", "subscriptions", "pull",
                        "store-events-analytics",
                        "--project", CANONICAL_PROJECT,
                        "--limit", "20",
                        "--format", "json",
                    ],
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
                        "CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB": "https://us-central1-pubsub.googleapis.com/",
                    },
                    check=False,
                )
                if pull_proc.returncode != 0:
                    continue
                try:
                    messages = json.loads(pull_proc.stdout)
                except json.JSONDecodeError:
                    continue
                if not isinstance(messages, list):
                    continue
                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    inner = msg.get("message", {})
                    if not isinstance(inner, dict):
                        continue
                    data_b64 = inner.get("data", "")
                    if not data_b64:
                        continue
                    import base64
                    try:
                        decoded = base64.b64decode(data_b64).decode("utf-8", errors="replace")
                    except Exception:
                        continue
                    if event_id in decoded:
                        delivered = {
                            "message_id": inner.get("messageId"),
                            "ordering_key": inner.get("orderingKey"),
                        }
                        break
                if delivered is not None:
                    break
            if delivered is None:
                raise RuntimeError(
                    f"Pub/Sub store-events-analytics did not deliver event_id={event_id}"
                )
            # Try to find the row in BigQuery (landed by the separate analytics
            # lander process). The default is to record whether the row
            # was landed without requiring it. ``DAY0_REQUIRE_BQ_ROW=1``
            # flips the check to require the row.
            try:
                rows = _bq_query(
                    f"SELECT event_id, sku, quantity FROM `{CANONICAL_PROJECT}."
                    f"{BIGQUERY_DATASET}.{BIGQUERY_TABLE}` "
                    f"WHERE event_id = '{event_id}' LIMIT 1"
                )
                bq_row = rows[0] if rows else None
            except Exception:
                bq_row = None
            require_bq = os.environ.get("DAY0_REQUIRE_BQ_ROW", "").strip() == "1"
            if require_bq and bq_row is None:
                raise RuntimeError(
                    f"DAY0_REQUIRE_BQ_ROW=1 but BigQuery {BIGQUERY_DATASET}."
                    f"{BIGQUERY_TABLE} did not land event_id={event_id}. The "
                    "analytics lander must be running before the gate can "
                    "claim Pub/Sub → BigQuery landing end to end."
                )
            record(
                log,
                "pubsub-event-path",
                "pass",
                f"Published {event_id} and verified delivery to {PIPELINE_TOPIC}"
                + ("; BigQuery row landed" if bq_row is not None else ""),
                event_id=event_id,
                correlation_id=correlation_id,
                delivery=delivered,
                bq_landed=bool(bq_row),
                bq_row=bq_row,
                bq_required=require_bq,
            )
        finally:
            fixture_path.unlink(missing_ok=True)


def check_vertex_live_inventory(log: EvidenceLog) -> None:
    """Run one real Vertex get_inventory(P001) read and compare to Firestore."""
    with check(log, "vertex-live-inventory"):
        # The opt-in live test mocks ADC if RETAILTWIN_VERTEX_LIVE=1 is set,
        # but in our case we want the real call. Import the read function and
        # build a provider directly.
        from retailtwin_api.agents.orchestrator.inventory_read import read_inventory
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository
        from retailtwin_api.llm.factory import LlmConfig, create_provider

        twin = FirestoreLiveTwinRepository()
        expected = twin.get_inventory(CANONICAL_STORE, CANONICAL_SKU)
        if expected is None:
            raise RuntimeError(
                f"Firestore stores/{CANONICAL_STORE}/inventory/{CANONICAL_SKU} missing"
            )
        provider = create_provider(
            LlmConfig(
                provider="vertex_gemini",
                model=VERTEX_MODEL,
                project_id=CANONICAL_PROJECT,
                location=CANONICAL_REGION,
                timeout=90,
            )
        )
        correlation_id = f"day0-gate-{int(time.time())}"
        result = asyncio.run(
            read_inventory(
                twin,
                provider=provider,
                store_id=CANONICAL_STORE,
                sku=CANONICAL_SKU,
                correlation_id=correlation_id,
                model=VERTEX_MODEL,
            )
        )
        if not result.ok:
            raise RuntimeError(
                f"Vertex get_inventory returned error_code={result.error_code!r}"
            )
        output = result.output or {}
        for field_name in (
            "shelf_id",
            "slot_id",
            "facings",
            "shelf_quantity",
            "backroom_quantity",
            "version",
        ):
            if output.get(field_name) != getattr(expected, field_name):
                raise RuntimeError(
                    f"Vertex field {field_name}={output.get(field_name)!r} "
                    f"differs from Firestore {getattr(expected, field_name)!r}"
                )
        record(
            log,
            "vertex-live-inventory",
            "pass",
            f"Vertex {VERTEX_MODEL} get_inventory({CANONICAL_SKU}) matches Firestore",
            firestore_version=expected.version,
            vertex_output=output,
            correlation_id=correlation_id,
        )


def check_repo_hygiene(log: EvidenceLog) -> None:
    """Assert no .env files, no committed secrets, no conflict markers."""
    with check(log, "repo-hygiene"):
        repo_root = Path(__file__).resolve().parents[1]
        # .env files (excluding .env.example/.env.sample/.env.template)
        env_files = []
        for path in repo_root.rglob(".env*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root)
            # Skip any node_modules/.venv/dist/build/artifacts/.git anywhere
            # in the path, not just at the top.
            if any(part in {"node_modules", ".venv", "dist", "build", "artifacts", ".git"} for part in rel.parts):
                continue
            name = rel.name
            if name in {".env.example", ".env.sample", ".env.template"}:
                continue
            env_files.append(str(rel))
        if env_files:
            raise RuntimeError(f"Committed .env files found: {env_files}")
        # Conflict markers (real git markers start at column 0).
        # Skip vendored and build output directories that are not part of
        # the committed source (node_modules, .venv, dist, build, artifacts).
        marker_files: list[str] = []
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root)
            # Skip any node_modules/.venv/dist/build/artifacts/.git anywhere
            # in the path, not just at the top.
            if any(part in {"node_modules", ".venv", "dist", "build", "artifacts", ".git"} for part in rel.parts):
                continue
            if path.suffix not in {
                ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml",
                ".md", ".sh", ".toml", ".cfg", ".txt",
            }:
                continue
            try:
                # A real git conflict marker appears at column 0.
                for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = raw_line.lstrip()
                    if stripped.startswith(("<<<<<<<", "=======")) and raw_line == stripped:
                        marker_files.append(str(rel))
                        break
            except OSError:
                continue
        if marker_files:
            raise RuntimeError(f"Git conflict markers in: {marker_files}")
        record(
            log,
            "repo-hygiene",
            "pass",
            "No .env files or conflict markers in the repo",
            checked_files=sum(
                1
                for p in repo_root.rglob("*")
                if p.is_file()
                and not any(
                    part in {"node_modules", ".venv", "dist", "build", "artifacts", ".git"}
                    for part in p.relative_to(repo_root).parts
                )
            ),
        )


# ── Utility helpers ──────────────────────────────────────────────────────────
def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, *, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            payload = _http_json(f"{base_url}/health")
            if payload.get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.5)
    return False


# ── Entry point ──────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Day-0 Foundation Gate evidence collector")
    parser.add_argument(
        "--cloud-run-url",
        default="https://retailtwin-api-5rgtvr4gpa-uc.a.run.app",
        help="Deployed Cloud Run service URL (no trailing slash)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "artifacts" / "day0-foundation"),
        help="Directory to write the evidence JSON into",
    )
    parser.add_argument(
        "--skip-vertex",
        action="store_true",
        help="Skip the Vertex live read (saves one billable Gemini call)",
    )
    parser.add_argument(
        "--skip-pubsub",
        action="store_true",
        help="Skip the Pub/Sub + BigQuery smoke (no new sale.completed row)",
    )
    parser.add_argument(
        "--skip-cloud-run",
        action="store_true",
        help="Skip the deployed Cloud Run probe",
    )
    parser.add_argument(
        "--require-bq-row",
        action="store_true",
        help=(
            "Require the BigQuery sales_events row landed by the analytics "
            "lander (sets DAY0_REQUIRE_BQ_ROW=1). Off by default; the gate "
            "only verifies Pub/Sub delivery when the lander is not running."
        ),
    )
    args = parser.parse_args(argv)
    if args.require_bq_row:
        os.environ["DAY0_REQUIRE_BQ_ROW"] = "1"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = _run_id()

    log = EvidenceLog(run_id)

    try:
        _check_preconditions()
    except _PreconditionError as exc:
        record(log, "preconditions", "skipped", str(exc))
        _write_evidence(output_dir, log)
        print(f"SKIPPED  {exc}", file=sys.stderr)
        return 2

    record(log, "preconditions", "pass", "Project + active account OK")

    if not args.skip_cloud_run:
        try:
            check_cloud_run_service(log, url=args.cloud_run_url)
        except Exception as exc:
            record(log, "cloud-run", "fail", f"{type(exc).__name__}: {exc}")

    try:
        check_firestore_p001(log)
    except Exception as exc:
        record(log, "firestore-p001", "fail", f"{type(exc).__name__}: {exc}")

    try:
        check_local_api_firestore(log)
    except Exception as exc:
        record(log, "local-api-firestore", "fail", f"{type(exc).__name__}: {exc}")

    if not args.skip_pubsub:
        try:
            check_pubsub_event_path(log)
        except Exception as exc:
            record(log, "pubsub-event-path", "fail", f"{type(exc).__name__}: {exc}")
    else:
        record(log, "pubsub-event-path", "skipped", "Skipped via --skip-pubsub")

    if not args.skip_vertex:
        try:
            check_vertex_live_inventory(log)
        except Exception as exc:
            record(log, "vertex-live-inventory", "fail", f"{type(exc).__name__}: {exc}")
    else:
        record(log, "vertex-live-inventory", "skipped", "Skipped via --skip-vertex")

    try:
        check_repo_hygiene(log)
    except Exception as exc:
        record(log, "repo-hygiene", "fail", f"{type(exc).__name__}: {exc}")

    _write_evidence(output_dir, log)
    _print_summary(log)
    return 0 if log.summary()["fail"] == 0 else 1


def _write_evidence(output_dir: Path, log: EvidenceLog) -> None:
    path = output_dir / f"{log.run_id}.json"
    path.write_text(json.dumps(log.to_json(), indent=2), encoding="utf-8")
    # Always write to the canonical path too
    latest = output_dir / "latest.json"
    latest.write_text(json.dumps(log.to_json(), indent=2), encoding="utf-8")


def _print_summary(log: EvidenceLog) -> None:
    summary = log.summary()
    print(f"\n=== Day-0 Foundation Gate ({log.run_id}) ===")
    for c in log.checks:
        marker = {"pass": "✓", "fail": "✗", "skipped": "~"}.get(c.status, "?")
        print(f"  {marker} {c.id:24}  {c.message}")
    print(f"\nSummary: {summary['pass']} pass, {summary['fail']} fail, {summary['skipped']} skipped")


if __name__ == "__main__":
    sys.exit(main())