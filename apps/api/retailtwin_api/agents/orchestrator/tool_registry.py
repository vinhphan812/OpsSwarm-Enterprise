"""Allow-listed tools for the orchestrator.

One pydantic model is the schema for each tool. ``llm_tools`` turns that model
into the provider-neutral ``LlmTool`` list. The OpenAI-compatible and Vertex
adapters translate that list. Agent code does not keep a second tool definition.

Capabilities are ``READ``, ``SIMULATION``, and ``COMMIT_REQUEST``. There is no
live-write capability. A handler must not mutate the Live Twin.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    MoveProduct,
    ReplenishShelf,
    ToolCapability,
)
from retailtwin_api.llm.contracts import LlmTool, LlmToolCall
from retailtwin_api.schemas import ProductInventory, StoreResponse

log = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_S = 2.0
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")

UNKNOWN_TOOL = "unknown_tool"
INVALID_ARGUMENTS = "invalid_arguments"
PERMISSION_DENIED = "permission_denied"
TIMEOUT = "timeout"
LIVE_WRITE_FORBIDDEN = "live_write_forbidden"
NOT_FOUND = "not_found"
SOURCE_UNAVAILABLE = "source_unavailable"
HANDLER_FAILED = "handler_failed"

# Names that would write the Live Twin. They are refused even if a caller
# grants every capability. Anything else outside the registry is unknown.
LIVE_WRITE_TOOLS = frozenset(
    {
        "write_firestore",
        "update_firestore",
        "delete_firestore",
        "set_inventory",
        "update_inventory",
        "delete_inventory",
        "mutate_live_twin",
        "write_live_twin",
        "update_live_twin",
        "delete_live_twin",
        "apply_live_action",
        "commit_to_live",
        "commit_live",
        "set_shelf_quantity",
        "update_store_state",
        "delete_store",
        "patch_store",
        "put_inventory",
    }
)

Handler = Callable[[Any], Mapping[str, Any]]


class ToolRegistryError(Exception):
    """The registry was configured incorrectly. This is not a model-facing error."""


class ToolFailure(Exception):
    """A tool refused the call with a controlled code and message."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    name: str
    capability: ToolCapability | None = None
    output: dict[str, Any] | None = None
    error_code: str | None = None
    message: str | None = None
    correlation_id: str | None = None


@dataclass
class ToolActivity:
    """Process-local record of accepted simulation and commit requests.

    This is not the Live Twin and it is not an authorization.
    """

    simulations: list[dict[str, Any]] = field(default_factory=list)
    simulation_actions: list[dict[str, Any]] = field(default_factory=list)
    commit_requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _Spec:
    name: str
    description: str
    capability: ToolCapability
    parameters: dict[str, Any]
    args_model: type[BaseModel]
    handler: Handler
    timeout_s: float


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkuArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)


class ShelfArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelf_id: str = Field(min_length=1)


class SkuHorizonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    horizon_hours: int = Field(ge=1, le=168)


class SalesHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    window_hours: int = Field(ge=1, le=168)


class MoveProductArgs(MoveProduct):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    from_slot: str = Field(min_length=1)
    to_slot: str = Field(min_length=1)


class ChangeFacingsArgs(ChangeFacings):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)


class ReplenishShelfArgs(ReplenishShelf):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)


class CreateSimulationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_version: str | None = None


class CompareScenariosArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_ids: list[str] = Field(min_length=2)


class CalculateBusinessImpactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(min_length=1)


class SubmitActionForCommitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision


@dataclass(frozen=True)
class CatalogTool:
    name: str
    description: str
    capability: ToolCapability
    args_model: type[BaseModel]


def _catalog(*items: CatalogTool) -> dict[str, CatalogTool]:
    return {item.name: item for item in items}


CATALOG = _catalog(
    CatalogTool(
        "get_store_state",
        "Read the current store view. Does not change the store.",
        ToolCapability.READ,
        EmptyArgs,
    ),
    CatalogTool(
        "get_shelf_state",
        "Read the products on one shelf. Does not change the store.",
        ToolCapability.READ,
        ShelfArgs,
    ),
    CatalogTool(
        "get_inventory",
        "Read one SKU: shelf, slot, facings, quantities, and version. Does not change the store.",
        ToolCapability.READ,
        SkuArgs,
    ),
    CatalogTool(
        "get_backroom_inventory",
        "Read the backroom quantity for one SKU. Does not change the store.",
        ToolCapability.READ,
        SkuArgs,
    ),
    CatalogTool(
        "get_product_performance",
        "Read deterministic product-performance evidence for one SKU.",
        ToolCapability.READ,
        SkuArgs,
    ),
    CatalogTool(
        "get_sales_history",
        "Read deterministic sales history for one SKU and window.",
        ToolCapability.READ,
        SalesHistoryArgs,
    ),
    CatalogTool(
        "get_sales_velocity",
        "Read deterministic sales velocity for one SKU.",
        ToolCapability.READ,
        SkuArgs,
    ),
    CatalogTool(
        "forecast_demand",
        "Read a deterministic demand forecast for one SKU and horizon.",
        ToolCapability.READ,
        SkuHorizonArgs,
    ),
    CatalogTool(
        "get_stockout_risk",
        "Read a deterministic stockout risk for one SKU and horizon.",
        ToolCapability.READ,
        SkuHorizonArgs,
    ),
    CatalogTool(
        "get_planogram",
        "Read the current planogram. Does not change the store.",
        ToolCapability.READ,
        EmptyArgs,
    ),
    CatalogTool(
        "move_product",
        "Accept a simulation action that moves a SKU between slots. Does not change the live store.",
        ToolCapability.SIMULATION,
        MoveProductArgs,
    ),
    CatalogTool(
        "change_facings",
        "Accept a simulation action that sets facings for a SKU. Does not change the live store.",
        ToolCapability.SIMULATION,
        ChangeFacingsArgs,
    ),
    CatalogTool(
        "replenish_shelf",
        "Accept a simulation action that replenishes a SKU. Does not change the live store.",
        ToolCapability.SIMULATION,
        ReplenishShelfArgs,
    ),
    CatalogTool(
        "create_simulation",
        "Open an empty simulation id at a context version. Does not change the live store.",
        ToolCapability.SIMULATION,
        CreateSimulationArgs,
    ),
    CatalogTool(
        "compare_scenarios",
        "Compare deterministic simulation results. Does not change the live store.",
        ToolCapability.SIMULATION,
        CompareScenariosArgs,
    ),
    CatalogTool(
        "calculate_business_impact",
        "Read a deterministic business impact for one simulation. Does not change the live store.",
        ToolCapability.SIMULATION,
        CalculateBusinessImpactArgs,
    ),
    CatalogTool(
        "submit_action_for_commit",
        "Record a commit request for an existing decision. Does not authorize it and does not change the live store.",
        ToolCapability.COMMIT_REQUEST,
        SubmitActionForCommitArgs,
    ),
)

# Offered to the model by the store registry. The other catalog names stay
# unwired until a deterministic port is bound, so the model cannot be handed
# a tool that would have to invent a number.
EXPOSED_TOOL_NAMES = frozenset(
    {
        "get_store_state",
        "get_shelf_state",
        "get_inventory",
        "get_backroom_inventory",
        "move_product",
        "change_facings",
        "replenish_shelf",
        "create_simulation",
        "submit_action_for_commit",
    }
)


def _canonical_parameters(model: type[BaseModel]) -> dict[str, Any]:
    """JSON object schema derived from the pydantic model, with refs inlined."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                key = str(node["$ref"]).rsplit("/", 1)[-1]
                target = walk(copy.deepcopy(defs[key]))
                extra = {
                    item_key: walk(item_value)
                    for item_key, item_value in node.items()
                    if item_key not in {"$ref", "$defs"}
                }
                if isinstance(target, dict):
                    target.update(extra)
                    target.pop("title", None)
                    return target
                return target
            return {
                item_key: walk(item_value)
                for item_key, item_value in node.items()
                if item_key not in {"$defs", "title"}
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    schema = walk(raw)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ToolRegistryError("tool schema must be a JSON object")
    return schema


def _is_live_write(name: str) -> bool:
    return name.casefold() in LIVE_WRITE_TOOLS


class _StoreReads(Protocol):
    """Structural reads used by the store-backed tools."""

    def inventory(self, sku: str) -> ProductInventory | None: ...

    def view(self) -> StoreResponse: ...


class ToolRegistry:
    def __init__(self) -> None:
        self.activity = ToolActivity()
        self._tools: dict[str, _Spec] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        capability: ToolCapability,
        args_model: type[BaseModel],
        handler: Handler,
        timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
    ) -> None:
        if not isinstance(name, str) or _TOOL_NAME.fullmatch(name) is None:
            raise ToolRegistryError("tool name must be a lower_snake identifier")
        if _is_live_write(name):
            raise ToolRegistryError(
                f"{name} is a live-write primitive and cannot be registered"
            )
        if name in self._tools:
            raise ToolRegistryError(f"{name} is already registered")
        if timeout_s <= 0:
            raise ToolRegistryError("timeout_s must be positive")
        if not isinstance(args_model, type) or not issubclass(args_model, BaseModel):
            raise ToolRegistryError("args_model must be a pydantic model")
        parameters = _canonical_parameters(args_model)
        self._tools[name] = _Spec(
            name=name,
            description=description,
            capability=capability,
            parameters=parameters,
            args_model=args_model,
            handler=handler,
            timeout_s=timeout_s,
        )

    def bind_catalog_tool(
        self,
        name: str,
        handler: Handler,
        *,
        timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
    ) -> None:
        item = CATALOG.get(name)
        if item is None:
            raise ToolRegistryError(f"{name} is not in the tool catalog")
        self.register(
            name=item.name,
            description=item.description,
            capability=item.capability,
            args_model=item.args_model,
            handler=handler,
            timeout_s=timeout_s,
        )

    def llm_tools(
        self,
        *,
        capabilities: Collection[ToolCapability] | None = None,
    ) -> list[LlmTool]:
        allowed = None if capabilities is None else set(capabilities)
        tools: list[LlmTool] = []
        for spec in self._tools.values():
            if allowed is not None and spec.capability not in allowed:
                continue
            tools.append(
                LlmTool(
                    name=spec.name,
                    description=spec.description,
                    parameters=copy.deepcopy(spec.parameters),
                )
            )
        return tools

    def invoke(
        self,
        name: object,
        arguments: object = None,
        *,
        granted: Collection[ToolCapability],
        correlation_id: str | None = None,
        timeout_s: float | None = None,
    ) -> ToolResult:
        if timeout_s is not None and timeout_s <= 0:
            raise ToolRegistryError("timeout_s must be positive")
        if isinstance(granted, str):
            raise ToolRegistryError("granted must be a collection of capabilities")
        if not isinstance(name, str) or name == "":
            return self._finish(
                name="" if not isinstance(name, str) else name,
                capability=None,
                correlation_id=correlation_id,
                error_code=UNKNOWN_TOOL,
                message="The tool is not registered.",
            )
        if _is_live_write(name):
            return self._finish(
                name=name,
                capability=None,
                correlation_id=correlation_id,
                error_code=LIVE_WRITE_FORBIDDEN,
                message="A live-write primitive is not a tool.",
            )
        spec = self._tools.get(name)
        if spec is None:
            return self._finish(
                name=name,
                capability=None,
                correlation_id=correlation_id,
                error_code=UNKNOWN_TOOL,
                message="The tool is not registered.",
            )
        if spec.capability not in set(granted):
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=PERMISSION_DENIED,
                message=f"{spec.capability.value} is not granted for this call.",
            )
        if arguments is None:
            payload: object = {}
        elif isinstance(arguments, Mapping):
            payload = dict(arguments)
        else:
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=INVALID_ARGUMENTS,
                message="Tool arguments must be an object.",
            )
        try:
            parsed = spec.args_model.model_validate(payload)
        except ValidationError:
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=INVALID_ARGUMENTS,
                message="The tool arguments are invalid.",
            )
        limit = spec.timeout_s if timeout_s is None else timeout_s
        try:
            output = _call_with_timeout(spec.handler, parsed, limit)
        except FuturesTimeout:
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=TIMEOUT,
                message="The tool timed out.",
            )
        except ToolFailure as exc:
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=exc.code,
                message=exc.message,
            )
        except Exception:
            log.exception(
                "tool handler failed name=%s correlation_id=%s",
                name,
                correlation_id,
            )
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=HANDLER_FAILED,
                message="The tool failed.",
            )
        try:
            encoded = json.dumps(output, allow_nan=False)
            decoded = json.loads(encoded)
        except (TypeError, ValueError):
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=HANDLER_FAILED,
                message="The tool failed.",
            )
        if not isinstance(decoded, dict):
            return self._finish(
                name=name,
                capability=spec.capability,
                correlation_id=correlation_id,
                error_code=HANDLER_FAILED,
                message="The tool failed.",
            )
        return self._finish(
            name=name,
            capability=spec.capability,
            correlation_id=correlation_id,
            output=decoded,
        )

    def execute_tool_calls(
        self,
        calls: list[LlmToolCall],
        *,
        granted: Collection[ToolCapability],
        correlation_id: str | None = None,
    ) -> list[ToolResult]:
        return [
            self.invoke(
                call.name,
                call.arguments,
                granted=granted,
                correlation_id=correlation_id,
            )
            for call in calls
        ]

    def _finish(
        self,
        *,
        name: str,
        capability: ToolCapability | None,
        correlation_id: str | None,
        output: dict[str, Any] | None = None,
        error_code: str | None = None,
        message: str | None = None,
    ) -> ToolResult:
        ok = error_code is None
        log.info(
            "tool name=%s capability=%s correlation_id=%s ok=%s error_code=%s",
            name,
            None if capability is None else capability.value,
            correlation_id,
            ok,
            error_code,
        )
        return ToolResult(
            ok=ok,
            name=name,
            capability=capability,
            output=output,
            error_code=error_code,
            message=message,
            correlation_id=correlation_id,
        )


def _call_with_timeout(handler: Handler, args: BaseModel, timeout_s: float) -> Mapping[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retailtwin-tool")
    future = pool.submit(handler, args)
    try:
        output = future.result(timeout=timeout_s)
    except FuturesTimeout:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    except Exception:
        pool.shutdown(wait=True)
        raise
    else:
        pool.shutdown(wait=True)
    if not isinstance(output, Mapping):
        raise ToolFailure(HANDLER_FAILED, "The tool failed.")
    return output


def build_store_registry(store: _StoreReads) -> ToolRegistry:
    """Registry whose reads come from ``store`` and whose writes do not exist."""
    registry = ToolRegistry()
    activity = registry.activity

    def get_store_state(_args: Any) -> Mapping[str, Any]:
        return store.view().model_dump()

    def get_shelf_state(args: Any) -> Mapping[str, Any]:
        products = [
            item.model_dump()
            for item in store.view().products
            if item.shelf_id == args.shelf_id
        ]
        if not products:
            raise ToolFailure(NOT_FOUND, f"Shelf {args.shelf_id} is not in the store.")
        return {"shelf_id": args.shelf_id, "products": products}

    def get_inventory(args: Any) -> Mapping[str, Any]:
        item = store.inventory(args.sku)
        if item is None:
            raise ToolFailure(NOT_FOUND, f"SKU {args.sku} is not in the store.")
        return item.model_dump()

    def get_backroom_inventory(args: Any) -> Mapping[str, Any]:
        item = store.inventory(args.sku)
        if item is None:
            raise ToolFailure(NOT_FOUND, f"SKU {args.sku} is not in the store.")
        return {
            "store_id": item.store_id,
            "sku": item.sku,
            "backroom_quantity": item.backroom_quantity,
            "version": item.version,
        }

    def move_product(args: Any) -> Mapping[str, Any]:
        action = MoveProduct(sku=args.sku, from_slot=args.from_slot, to_slot=args.to_slot)
        record = {"tool": "move_product", "action": action.model_dump()}
        activity.simulation_actions.append(record)
        return {"status": "accepted", "capability": ToolCapability.SIMULATION.value, **record}

    def change_facings(args: Any) -> Mapping[str, Any]:
        action = ChangeFacings(sku=args.sku, facings=args.facings)
        record = {"tool": "change_facings", "action": action.model_dump()}
        activity.simulation_actions.append(record)
        return {"status": "accepted", "capability": ToolCapability.SIMULATION.value, **record}

    def replenish_shelf(args: Any) -> Mapping[str, Any]:
        action = ReplenishShelf(sku=args.sku, quantity=args.quantity)
        record = {"tool": "replenish_shelf", "action": action.model_dump()}
        activity.simulation_actions.append(record)
        return {"status": "accepted", "capability": ToolCapability.SIMULATION.value, **record}

    def create_simulation(args: Any) -> Mapping[str, Any]:
        context_version = args.context_version or store.view().context_version
        record = {
            "simulation_id": f"sim-{len(activity.simulations) + 1}",
            "context_version": context_version,
            "status": "created",
        }
        activity.simulations.append(record)
        return record

    def submit_action_for_commit(args: Any) -> Mapping[str, Any]:
        decision = args.decision
        record = {
            "decision_id": decision.decision_id,
            "context_version": decision.context_version,
            "action_count": len(decision.proposed_actions),
            "decision": decision.model_dump(mode="json"),
        }
        activity.commit_requests.append(record)
        return {
            "status": "commit_requested",
            "decision_id": decision.decision_id,
            "context_version": decision.context_version,
            "action_count": len(decision.proposed_actions),
        }

    handlers: dict[str, Handler] = {
        "get_store_state": get_store_state,
        "get_shelf_state": get_shelf_state,
        "get_inventory": get_inventory,
        "get_backroom_inventory": get_backroom_inventory,
        "move_product": move_product,
        "change_facings": change_facings,
        "replenish_shelf": replenish_shelf,
        "create_simulation": create_simulation,
        "submit_action_for_commit": submit_action_for_commit,
    }
    for name, handler in handlers.items():
        item = CATALOG[name]
        registry.register(
            name=item.name,
            description=item.description,
            capability=item.capability,
            args_model=item.args_model,
            handler=handler,
        )
    return registry
