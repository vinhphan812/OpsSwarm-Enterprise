import i18n from "@/i18n";
import type { Messages } from "@/i18n/locales/en";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type {
  Candidate,
  CandidateKPI,
  GuardResult,
  ReviewResult,
  Simulation,
  SimulationAction,
} from "@/types/simulation.type";
import { ACTION_TYPE, GUARD_VERDICT, REVIEW_DECISION, SIMULATION_STATUS } from "@/enums/simulation.enum";

/** Why a product is not drawn: a key under `issue` in the locale files. */
export type IssueCode = keyof Messages["issue"];

/**
 * A product record the scene cannot draw, and why. `sku` is its entity id. The reason
 * is a code with its values, translated where it is shown.
 */
export type ProductIssue = {
  sku: string;
  code: IssueCode;
  values?: Record<string, string | number>;
};

/** The issue's reason as text. */
export function issueReason(issue: ProductIssue): string {
  return i18n.t(`issue.${issue.code}`, issue.values);
}

type InvalidStateReason = Exclude<keyof Messages["invalidState"], "title">;

/** The payload is not a store response at all, so nothing in it can be trusted. */
export class InvalidTwinStateError extends Error {
  constructor(reason: InvalidStateReason, values?: Record<string, string>) {
    super(i18n.t("invalidState.title", { reason: i18n.t(`invalidState.${reason}`, values) }));
    this.name = "InvalidTwinStateError";
  }
}

/** Required product fields of `GET /store`, as `ProductInventory` in apps/api declares them. */
export const PRODUCT_FIELDS = [
  "store_id",
  "sku",
  "shelf_id",
  "slot_id",
  "facings",
  "shelf_quantity",
  "backroom_quantity",
  "version",
] as const satisfies ReadonlyArray<keyof ProductInventory>;

type Fields = Record<string, unknown>;

const isObject = (value: unknown): value is Fields =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

type Problem = Omit<ProductIssue, "sku">;

/** Why one product record breaks the contract, or null when it is valid. */
function productProblem(raw: Fields, storeId: string): Problem | null {
  if (raw.store_id !== storeId) {
    return { code: "wrongStore", values: { storeId: JSON.stringify(raw.store_id), expected: storeId } };
  }
  if (raw.shelf_id == null || raw.slot_id == null) return { code: "unassigned" };
  if (!isText(raw.shelf_id)) return { code: "invalidShelfId" };
  if (!isText(raw.slot_id)) return { code: "invalidSlotId" };
  for (const field of ["facings", "shelf_quantity", "backroom_quantity", "version"] as const) {
    if (!isCount(raw[field])) return { code: "invalidCount", values: { field, value: String(JSON.stringify(raw[field])) } };
  }
  return null;
}

/**
 * Checks a `GET /store` payload against the contract. A broken envelope throws; a
 * broken product is left out of `state` and reported in `issues`, so one bad record
 * never hides the rest of the store.
 */
export function parseStoreState(raw: unknown): { state: StoreResponse; issues: ProductIssue[] } {
  if (!isObject(raw)) throw new InvalidTwinStateError("notObject");
  for (const field of ["store_id", "context_version", "version"] as const) {
    if (!isText(raw[field])) throw new InvalidTwinStateError("missingField", { field });
  }
  if (!Array.isArray(raw.products)) throw new InvalidTwinStateError("productsNotArray");

  const storeId = raw.store_id as string;
  const products: ProductInventory[] = [];
  const issues: ProductIssue[] = [];
  const seen = new Set<string>();
  raw.products.forEach((item: unknown, index) => {
    if (!isObject(item) || !isText(item.sku)) {
      issues.push({ sku: `#${index}`, code: "missingSku" });
      return;
    }
    const sku = item.sku;
    if (seen.has(sku)) {
      issues.push({ sku, code: "duplicateSku" });
      return;
    }
    seen.add(sku);
    const problem = productProblem(item, storeId);
    if (problem) issues.push({ sku, ...problem });
    else products.push(item as ProductInventory);
  });

  return {
    state: {
      store_id: storeId,
      context_version: raw.context_version as string,
      version: raw.version as string,
      products,
    },
    issues,
  };
}

const STATUSES: readonly unknown[] = Object.values(SIMULATION_STATUS);
const ACTION_TYPES: readonly unknown[] = Object.values(ACTION_TYPE);

/**
 * Checks a `GET /simulations/{id}` payload against the FE's proposed contract (#26).
 * The proposed state is checked like `GET /store`, so a broken product is left out of
 * it; anything else that breaks the contract throws.
 */
export function parseSimulation(raw: unknown): Simulation {
  if (!isObject(raw)) throw new InvalidTwinStateError("notObject");
  for (const field of ["simulation_id", "store_id", "base_context_version"] as const) {
    if (!isText(raw[field])) throw new InvalidTwinStateError("missingField", { field });
  }
  if (!STATUSES.includes(raw.status)) throw new InvalidTwinStateError("invalidField", { field: "status" });
  const actions = raw.actions;
  if (!Array.isArray(actions) || !actions.every((action) => isObject(action) && ACTION_TYPES.includes(action.type) && isText(action.sku))) {
    throw new InvalidTwinStateError("invalidField", { field: "actions" });
  }
  const storeRaw = isObject(raw.state) && "store" in raw.state && isObject(raw.state.store)
    ? raw.state.store
    : raw.state;
  const { state } = parseStoreState(storeRaw);
  if (state.store_id !== raw.store_id) throw new InvalidTwinStateError("invalidField", { field: "state.store_id" });
  return {
    simulation_id: raw.simulation_id as string,
    store_id: raw.store_id as string,
    base_context_version: raw.base_context_version as string,
    status: raw.status as Simulation["status"],
    actions: actions as SimulationAction[],
    state,
  };
}

/** apps/api's names for a decision (`approved` / `rejected`), and the FE's own. */
const DECISIONS: Record<string, ReviewResult["decision"]> = {
  approved: REVIEW_DECISION.Approve,
  rejected: REVIEW_DECISION.Reject,
  [REVIEW_DECISION.Approve]: REVIEW_DECISION.Approve,
  [REVIEW_DECISION.Reject]: REVIEW_DECISION.Reject,
};
const VERDICTS: readonly unknown[] = Object.values(GUARD_VERDICT);
const textOrNull = (value: unknown) => value === null || value === undefined || isText(value);

/** Checks the guard's answer on an approval; null when the guard did not run. */
function parseGuard(raw: unknown): GuardResult | null {
  if (raw === null || raw === undefined) return null;
  const invalid = () => new InvalidTwinStateError("invalidField", { field: "guard" });
  if (!isObject(raw) || !VERDICTS.includes(raw.verdict) || !isText(raw.reason_code) || !isText(raw.context_version)) {
    throw invalid();
  }
  const policy = raw.policy_result ?? {};
  if (!isObject(policy) || !textOrNull(policy.failed_gate)) throw invalid();
  const checks = policy.checks ?? [];
  if (!Array.isArray(checks)) throw invalid();
  return {
    verdict: raw.verdict as GuardResult["verdict"],
    reason_code: raw.reason_code,
    context_version: raw.context_version,
    failed_gate: (policy.failed_gate as string | null | undefined) ?? null,
    checks: checks.map((check: unknown) => {
      if (!isObject(check) || !isText(check.gate) || typeof check.passed !== "boolean") throw invalid();
      return { gate: check.gate, passed: check.passed, detail: typeof check.detail === "string" ? check.detail : "" };
    }),
  };
}

/**
 * Checks a `POST /simulations/{id}/approve|reject` answer. An approval carries the guard's
 * verdict; a rejection never reaches the guard, so any verdict on it is dropped. Only an
 * approval the guard allowed can leave the run committed. Anything off throws.
 */
export function parseReviewResult(raw: unknown): ReviewResult {
  if (!isObject(raw)) throw new InvalidTwinStateError("notObject");
  if (!isText(raw.simulation_id)) throw new InvalidTwinStateError("missingField", { field: "simulation_id" });
  const decision = typeof raw.decision === "string" ? DECISIONS[raw.decision] : undefined;
  if (!decision) throw new InvalidTwinStateError("invalidField", { field: "decision" });
  if (!STATUSES.includes(raw.status)) throw new InvalidTwinStateError("invalidField", { field: "status" });
  const approval = decision === REVIEW_DECISION.Approve;
  const verdict = approval ? (raw.verdict ?? null) : null;
  if (approval && !VERDICTS.includes(verdict)) throw new InvalidTwinStateError("invalidField", { field: "verdict" });
  const allowed = verdict === GUARD_VERDICT.Allow;
  if (raw.status === SIMULATION_STATUS.Committed ? !allowed : allowed && raw.status === SIMULATION_STATUS.Rejected) {
    throw new InvalidTwinStateError("invalidField", { field: "status" });
  }
  for (const field of ["reason_code", "live_context_version", "detail_code"] as const) {
    if (!textOrNull(raw[field])) throw new InvalidTwinStateError("invalidField", { field });
  }
  return {
    simulation_id: raw.simulation_id,
    decision,
    status: raw.status as ReviewResult["status"],
    verdict: verdict as ReviewResult["verdict"],
    reason_code: (raw.reason_code as string | null | undefined) ?? null,
    live_context_version: (raw.live_context_version as string | null | undefined) ?? null,
    detail_code: (raw.detail_code as string | null | undefined) ?? null,
    guard: approval ? parseGuard(raw.guard) : null,
  };
}

/** Checks a candidate from `GET /simulations/{simulation_id}/candidates`. */
export function parseCandidate(raw: unknown): Candidate {
  if (!isObject(raw)) throw new InvalidTwinStateError("notObject");
  for (const field of ["candidate_id", "simulation_id", "evaluator_version", "provenance"] as const) {
    if (!isText(raw[field])) throw new InvalidTwinStateError("missingField", { field });
  }
  const actions = raw.proposed_actions;
  if (!Array.isArray(actions) || !actions.every((action) => isObject(action) && ACTION_TYPES.includes(action.type) && isText(action.sku))) {
    throw new InvalidTwinStateError("invalidField", { field: "proposed_actions" });
  }
  const storeRaw = isObject(raw.state) && "store" in raw.state && isObject(raw.state.store)
    ? raw.state.store
    : raw.state;
  const { state } = parseStoreState(storeRaw);
  const kpisRaw = raw.kpis;
  const kpis: CandidateKPI[] = [];
  if (Array.isArray(kpisRaw)) {
    for (const kpi of kpisRaw) {
      if (isObject(kpi) && isText(kpi.name) && typeof kpi.value === "number" && isText(kpi.unit) && isText(kpi.source)) {
        kpis.push({
          name: kpi.name as string,
          value: kpi.value as number,
          unit: kpi.unit as string,
          source: kpi.source as string,
        });
      }
    }
  }
  return {
    candidate_id: raw.candidate_id as string,
    simulation_id: raw.simulation_id as string,
    proposed_actions: actions as SimulationAction[],
    state,
    kpis,
    evaluator_version: raw.evaluator_version as string,
    provenance: raw.provenance as string,
    recommended: raw.recommended === true,
    rationale: isText(raw.rationale) ? raw.rationale : null,
  };
}
