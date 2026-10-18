"""FastAPI application for the RetailTwin day-0 boundary."""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from retailtwin_api.agent_activity import AgentActivityLog
from retailtwin_api.agents.executor import build_commit_service
from retailtwin_api.agents.observer.consumer import (
    MemoryActivationLedger,
    consume_available,
)
from retailtwin_api.agents.orchestrator.autonomy import AutonomousInvestigations
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry, build_store_registry
from retailtwin_api.backbone import EventPipe, MemoryPipe, MemoryQuarantine
from retailtwin_api.analytics_repository import (
    get_checkout_repository,
    unavailable_analytics_repositories,
)
from retailtwin_api.decisions import InMemoryDecisionSource, unavailable_decision_source
from retailtwin_api.persistence import get_persistence
from retailtwin_api.demand_surge import DemandSurgeScheduler
from retailtwin_api.errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from retailtwin_api.events import EventLog, ReviewAuditLog
from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, LiveTwinRepository
from retailtwin_api.flagship.agent_starter import FlagshipInvestigationStarter
from retailtwin_api.guard.decision_context_guard import InMemoryGuardAudit
from retailtwin_api.middleware import CorrelationMiddleware
from retailtwin_api.routes import router
from retailtwin_api.llm.factory import create_provider, llm_config_from_settings
from retailtwin_api.settings import Settings, get_settings
from retailtwin_api.simulation import SimulationRepository, _build_state
from retailtwin_api.store import LiveTwinStore, StoreReader, open_memory_live_store, open_store
from retailtwin_api.version import __version__, git_sha

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Build the EventPipe. Production Cloud Run uses MemoryPipe because
        # the ``store-events-agent`` subscription is **push-only** (the
        # push endpoint is ``POST /pubsub/agent-events`` on this same
        # instance — P0-1). Every environment uses MemoryPipe so a
        # developer or test never opens a real GCP project. Real events
        # arrive via the OIDC-verified HTTP push path.
        event_pipe = _build_event_pipe(resolved)
        activation_ledger = MemoryActivationLedger()
        quarantine = MemoryQuarantine()
        starter = FlagshipInvestigationStarter(
            controller_getter=lambda: getattr(app.state, "flagship_controller", None),
        )

        app.state.event_pipe = event_pipe
        app.state.activation_ledger = activation_ledger
        app.state.observer_quarantine = quarantine
        app.state.observer_starter = starter

        trigger_task: asyncio.Task[None] | None = None
        scheduler: DemandSurgeScheduler | None = None

        # Production is push-only (P0-1). The ``store-events-agent``
        # subscription is wired with a push endpoint (``POST /pubsub/agent-events``);
        # starting a background pull loop against the same subscription
        # would flip it back to pull, which Cloud Run cannot do — push and
        # pull are mutually exclusive on one subscription. The pull loop
        # only runs in dev / test, where the pipe is a MemoryPipe anyway.
        pull_disabled_in_production = (
            resolved.autonomous_pubsub_pull_disabled_in_production
        )
        run_pull_loop = (
            resolved.autonomous_trigger_enabled
            and not (resolved.is_production and pull_disabled_in_production)
        )
        if run_pull_loop:
            trigger_task = asyncio.create_task(
                _autonomous_trigger_loop(
                    event_pipe,
                    activation_ledger,
                    starter,
                    quarantine,
                ),
                name="retailtwin-autonomous-trigger",
            )
        if resolved.autonomous_scheduled_publisher_enabled:
            scheduler = DemandSurgeScheduler(
                event_pipe,
                float(resolved.autonomous_trigger_interval_seconds),
            )
            scheduler.start()

        # Surface the running background work on app.state so tests and
        # operators can introspect them without reaching into the lifespan
        # closure.
        app.state.trigger_task = trigger_task
        app.state.scheduler = scheduler

        try:
            yield
        finally:
            if trigger_task is not None:
                trigger_task.cancel()
                try:
                    await trigger_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("autonomous_trigger.teardown_failed")
            if scheduler is not None:
                await scheduler.stop()
            app.state.trigger_task = None
            app.state.scheduler = None

    app = FastAPI(
        title="RetailTwin API",
        # ADR 0025: the FastAPI advertised version derives from the canonical
        # VERSION file so /openapi.json matches /health and /version.
        version=__version__,
        description="Day-0 retail store event API. Structured JSON logs and "
        "correlation IDs are enabled in all environments.",
        lifespan=lifespan,
    )
    app.state.settings = resolved

    # Default is an in-process Live Twin seeded from the fixture. Firestore is
    # used only when LIVE_TWIN_BACKEND=firestore, so tests never open a live project.
    store = _open_store(resolved)
    app.state.store = store
    live_twin: LiveTwinRepository | None = store.twin if isinstance(store, LiveTwinStore) else None
    app.state.live_twin = live_twin
    app.state.guard_audit = InMemoryGuardAudit()
    app.state.commits = (
        build_commit_service(live_twin, app.state.guard_audit, production=resolved.is_production)
        if live_twin is not None
        else None
    )
    # The planner does not persist Decisions yet. A test or a later orchestrator injects a source.
    app.state.decisions = unavailable_decision_source()
    app.state.events = EventLog()
    app.state.review_audit = ReviewAuditLog()
    app.state.live_context_version = store.view().context_version if store.loaded else ""
    app.state.activity = AgentActivityLog()
    app.state.simulations = SimulationRepository(store.view, resolved.store_id, activity=app.state.activity)
    # Observer plumbing for POST /events (G03). The pipe and ledger are process memory.
    # When LIVE_TWIN_BACKEND=firestore, wire the durable adapters for production.
    durable_adapters = None
    if resolved.live_twin_backend == "firestore":
        durable_adapters = get_persistence(resolved, activity=app.state.activity)

    app.state.event_pipe = MemoryPipe()
    if durable_adapters is not None:
        # Use Firestore-backed durable adapters
        app.state.activation_ledger = durable_adapters.activation_ledger
        app.state.decisions = durable_adapters.decisions
        app.state.simulations = durable_adapters.simulations
    else:
        # Use in-memory adapters for fixture/memory backends
        app.state.activation_ledger = MemoryActivationLedger()
    app.state.quarantine = MemoryQuarantine()
    app.state.autonomy = None
    if resolved.autonomy_enabled and store.loaded:
        try:
            provider = create_provider(llm_config_from_settings(resolved))
        except Exception as exc:
            # A misconfigured provider disables autonomy; the read and review routes keep serving.
            provider = None
            logger.error("autonomy.unavailable", extra={"error_type": type(exc).__name__})
    else:
        provider = None
    if provider is not None:
        decisions = InMemoryDecisionSource()
        app.state.decisions = decisions
        autonomy_registry = build_store_registry(store)
        # Issue #215 / ADR 0024: wire the BigQuery-backed
        # ``get_sales_history`` reader so the autonomy path sees real
        # demand evidence in production. In non-cloud environments the
        # reader is wired to return ``None`` so the investigator
        # surfaces ``sales_history_unavailable`` rather than a fabricated
        # number.
        _wire_sales_history_port(autonomy_registry, settings=resolved)
        app.state.autonomy = AutonomousInvestigations(
            provider=provider,
            registry=autonomy_registry,
            store_view=store.view,
            proposals=app.state.simulations,
            decisions=decisions,
            activity=app.state.activity,
            build_state=_build_state,
        )
    if not store.loaded:
        logger.error(
            "fixture.unavailable",
            extra={"store_error": store.error, "fixture_path": str(resolved.store_fixture_path)},
        )
    # Analytics repositories: GCP-backed (BigQuery + Firestore); empty adapters in dev.
    # Checkout reads use the explicit in-memory scaffold pending a verified BQ schema.
    # Swap app.state repositories in integration tests.
    anomalies, revenue, promotions, _ = unavailable_analytics_repositories()
    app.state.anomalies = anomalies
    app.state.revenue = revenue
    app.state.promotions = promotions
    app.state.checkouts = get_checkout_repository()

    # Correlation + structured logging middleware (must be outermost)
    app.add_middleware(CorrelationMiddleware)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(resolved.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["accept", "content-type", "x-correlation-id"],
    )
    app.include_router(router)

    # Flagship controller — wired against the same canonical services
    # ``create_app`` already configured (Live Twin, Guard, store_id). The
    # routes return 503 when the controller is not configured, so a
    # transient wiring failure (e.g. the production LLM provider could not
    # be built) leaves the rest of the API intact.
    _wire_flagship_controller(app, resolved, live_twin, store)

    logger.info(
        "app.startup",
        extra={
            "app_env": resolved.app_env,
            "is_production": resolved.is_production,
            "store_id": resolved.store_id,
            "fixture_loaded": store.loaded,
            "fixture_path": str(resolved.store_fixture_path),
            "live_twin_backend": resolved.live_twin_backend,
            "flagship_wired": app.state.flagship_controller.is_configured
            if getattr(app.state, "flagship_controller", None) is not None
            else False,
            "version": __version__,
            "git_sha": git_sha,
        },
    )
    return app


def _open_store(settings: Settings) -> StoreReader:
    if settings.live_twin_backend == "fixture":
        return open_store(settings.store_fixture_path, settings.store_id)
    if settings.live_twin_backend == "firestore":
        return LiveTwinStore(FirestoreLiveTwinRepository(), settings.store_id)
    return open_memory_live_store(settings.store_fixture_path, settings.store_id)


def _build_bigquery_client() -> Any:
    """Construct the BigQuery client used by the sales-history reader.

    Production wires ``google.cloud.bigquery.Client`` (ADC); non-cloud
    environments (``APP_ENV`` not in ``{production, staging, e2e-smoke}``)
    return ``None`` so the investigator's ``get_sales_history`` port
    surfaces ``sales_history_unavailable`` instead of fabricating a
    number. The import is deferred so a developer machine without
    ``google-cloud-bigquery`` installed still boots.
    """
    try:
        from google.cloud import bigquery  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — google-cloud-bigquery is optional in dev.
        return None
    try:
        return bigquery.Client()
    except Exception as exc:  # noqa: BLE001 — surface any ADC failure
        logger.warning(
            "bigquery_sales_history.client_unavailable",
            extra={"reason": f"{type(exc).__name__}: {exc}"},
        )
        return None


def _wire_sales_history_port(registry: ToolRegistry, *, settings: Settings) -> None:
    """Bind the BigQuery-backed ``get_sales_history`` reader (issue #215).

    The reader is the canonical demand-evidence source for the agent
    chain. When the BigQuery client cannot be constructed (dev / test /
    missing ADC credentials), the port is bound to a reader that
    returns ``None`` — the wrapping ``bind_read_port`` handler converts
    that to ``SOURCE_UNAVAILABLE`` and the investigator surfaces it as
    ``insufficient_evidence`` with reason ``sales_history_unavailable``
    so the chain never invents a number.
    """
    from retailtwin_api.agents.investigator.evidence import bind_read_port
    from retailtwin_api.bigquery_sales_history import read_sales_history

    client = _build_bigquery_client() if settings.is_production else None

    def _sales_history(args: Any) -> Mapping[str, Any] | None:
        if client is None:
            # The reader was wired for empty/unavailable BigQuery; the
            # wrapping ``bind_read_port`` handler converts ``None`` to
            # ``SOURCE_UNAVAILABLE``.
            return None
        return read_sales_history(
            args,
            client=client,
            job_config=None,
            store_id=settings.store_id,
        )

    bind_read_port(registry, "get_sales_history", _sales_history)
    logger.info(
        "bigquery_sales_history.wired",
        extra={"client": "google.cloud.bigquery.Client" if client is not None else "unavailable"},
    )


def _ensure_simulation_kpi_path() -> None:
    """Make the canonical KPI evaluator importable as ``kpi.evaluator``.

    The flagship controller is wired against the same deterministic KPI
    formula the agent chain uses, and that formula lives under
    ``services/simulation`` (which in turn depends on
    ``services/forecasting`` for stockout risk). The test harness adds
    the directories to ``sys.path``; production code does the same here
    so a single import surface backs tests, dev runs and Cloud Run.
    """
    repo_root = Path(__file__).resolve().parents[3]
    for relative in ("services/simulation", "services/forecasting"):
        candidate = repo_root / relative
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _build_flagship_evaluator() -> Callable[..., Mapping[str, Any]]:
    """Adapter that turns the canonical KPI module into a ``CandidateEvaluator``.

    The flagship controller receives a ``CandidateEvaluator`` (a
    snapshot, candidate_id, actions → KPI mapping). The canonical
    ``evaluate_candidate`` lives in ``services/simulation/kpi/evaluator``
    and operates on Pydantic models. This adapter bridges the controller's
    Mapping-based protocol to that canonical scorer.
    """
    _ensure_simulation_kpi_path()
    from kpi.evaluator import (  # type: ignore[import-not-found]
        ChangeFacings as KpiChangeFacings,
    )
    from kpi.evaluator import (  # type: ignore[import-not-found]
        MoveProduct as KpiMoveProduct,
    )
    from kpi.evaluator import (  # type: ignore[import-not-found]
        ReplenishShelf as KpiReplenishShelf,
    )
    from kpi.evaluator import (  # type: ignore[import-not-found]
        SimulationSnapshot,
        evaluate_candidate,
    )

    def _evaluator(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
        *,
        evaluator_version: str | None = None,
    ) -> dict[str, Any]:
        observed_at = snapshot.get("observed_at")
        if not isinstance(observed_at, str):
            raise RuntimeError("observed_at must be an ISO string")
        from datetime import datetime

        built = SimulationSnapshot(
            simulation_id=snapshot["simulation_id"],
            store_id=snapshot["store_id"],
            context_version=snapshot["context_version"],
            correlation_id=snapshot["correlation_id"],
            observed_at=datetime.fromisoformat(observed_at),
            slots=tuple(
                {
                    "sku": slot["sku"],
                    "slot_id": slot["slot_id"],
                    "shelf_quantity": slot["shelf_quantity"],
                    "backroom_quantity": slot["backroom_quantity"],
                    "facings": slot["facings"],
                    "sales_velocity_units_per_hour": Decimal(
                        slot.get("sales_velocity_units_per_hour") or "0"
                    ),
                    "price": Decimal(slot.get("price") or "0"),
                }
                for slot in snapshot["slots"]
            ),
        )
        converted: list[Any] = []
        for action in actions:
            kind = action.get("type")
            if kind == "replenish_shelf":
                converted.append(
                    KpiReplenishShelf(sku=action["sku"], quantity=action["quantity"])
                )
            elif kind == "change_facings":
                converted.append(
                    KpiChangeFacings(sku=action["sku"], facings=action["facings"])
                )
            elif kind == "move_product":
                converted.append(
                    KpiMoveProduct(
                        sku=action["sku"],
                        from_slot=action["from_slot"],
                        to_slot=action["to_slot"],
                    )
                )
            else:
                raise RuntimeError(f"unknown action {kind}")
        return evaluate_candidate(
            built,
            candidate_id,
            tuple(converted),
            evaluator_version=evaluator_version,
        ).as_dict()

    return _evaluator


def _build_flagship_provider(settings: Settings) -> Any:
    """Build the LLM provider the flagship controller drives the chain with.

    In production the configured ``vertex_gemini`` adapter is mandatory.
    In dev/test the shipped ``fake`` provider is used. A misconfigured
    production build raises here and the flagship routes return 503.
    """
    from retailtwin_api.llm.factory import create_provider, install_builtin_providers
    from retailtwin_api.llm.factory import llm_config_from_settings

    install_builtin_providers()
    config = llm_config_from_settings(settings)
    return create_provider(config)


def _wire_flagship_controller(
    app: FastAPI,
    settings: Settings,
    live_twin: LiveTwinRepository | None,
    store: StoreReader,
) -> None:
    """Attach the flagship controller and routes to ``app``.

    The controller is wired against the same canonical services
    ``create_app`` already configured: the Live Twin, the store reader, the
    tool registry built on top of them, the configured LLM provider, and
    the deterministic KPI evaluator from ``services/simulation``. On any
    wiring failure (missing Live Twin, LLM provider cannot be built) the
    routes still mount and respond with 503.
    """
    from retailtwin_api.flagship import register_dependencies, register_routes

    app.state.flagship_controller = None
    register_routes(app)

    if live_twin is None or not store.loaded:
        logger.warning(
            "flagship.unavailable",
            extra={"reason": "live_twin or store is not loaded"},
        )
        return

    try:
        provider = _build_flagship_provider(settings)
    except Exception as exc:  # noqa: BLE001 — surface any provider build failure
        logger.warning(
            "flagship.provider_unavailable",
            extra={"reason": f"{type(exc).__name__}: {exc}"},
        )
        return

    registry = build_store_registry(store)
    # Issue #215 / ADR 0024: wire the BigQuery-backed
    # ``get_sales_history`` reader so the flagship chain sees real
    # demand evidence in production. In non-cloud environments the
    # reader is wired to return ``None`` so the investigator surfaces
    # ``sales_history_unavailable`` rather than a fabricated number.
    _wire_sales_history_port(registry, settings=settings)
    controller = register_dependencies(
        provider=provider,
        twin=live_twin,
        store_id=settings.store_id,
        registry=registry,
        evaluator=_build_flagship_evaluator(),
    )
    app.state.flagship_controller = controller
    logger.info(
        "flagship.wired",
        extra={
            "store_id": settings.store_id,
            "llm_provider": settings.llm_provider,
            "is_production": settings.is_production,
        },
    )


def _origins(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_event_pipe(settings: Settings) -> EventPipe:
    """Build the EventPipe the autonomous trigger pulls from.

    Production uses :class:`MemoryPipe` (P0-1). The ``store-events-agent``
    subscription is **push-only** in production: it carries a push
    endpoint that points at ``POST /pubsub/agent-events`` on the same
    Cloud Run instance. Real events arrive via that OIDC-verified HTTP
    push path, so a second consumer would either flip the subscription
    to pull (forbidden — push and pull are mutually exclusive on one
    subscription) or do nothing useful. ``GcpPubSubEventPipe`` is kept
    as a library for non-production tests and any future pull-mode
    consumer; the production lifespan does not instantiate it.

    Every other environment uses :class:`MemoryPipe` so the trigger can
    be exercised end-to-end without a real GCP project. The
    ``DemandSurgeScheduler`` (which publishes via the same pipe) also
    targets memory in production: in production real events come from
    real checkouts, not from the demo scheduler.
    """
    return MemoryPipe()


async def _autonomous_trigger_loop(
    pipe: EventPipe,
    ledger: MemoryActivationLedger,
    starter: FlagshipInvestigationStarter,
    quarantine: MemoryQuarantine,
) -> None:
    """Drive the observer consumer on the configured EventPipe.

    The consumer is sync; :class:`FlagshipInvestigationStarter` runs the
    flagship chain via :func:`asyncio.run` in the worker thread
    :func:`asyncio.to_thread` selects, so the FastAPI event loop stays
    responsive even when a flagship run takes seconds.
    """

    while True:
        try:
            await asyncio.to_thread(consume_available, pipe, ledger, starter, quarantine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("autonomous_trigger.consume_failed")
        await asyncio.sleep(0.5)


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "retailtwin_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
