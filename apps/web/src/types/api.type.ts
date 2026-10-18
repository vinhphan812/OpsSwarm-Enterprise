import type { RevenuePeriod } from "@/enums/commerce.enum";
import type { PromotionsSummary } from "@/types/promotion.type";
import type { RevenueSummary } from "@/types/revenue.type";
import type { ReviewDecision } from "@/enums/simulation.enum";
import type { CandidatesResponse, ReviewRequest, ReviewResult, Simulation, SimulationsResponse } from "@/types/simulation.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type { AnomaliesResponse } from "@/types/anomaly.type";
import type { CheckoutResponse } from "@/types/checkout.type";

export type HealthResponse = {
  status: "ok" | "degraded";
  service: "retailtwin-api";
  environment: string;
  store_id: string;
  fixture_loaded: boolean;
};

/** Server state from idempotent start - separate from run phase */
export type ServerState = "NOT_STARTED" | "STARTING" | "RUNNING" | "ERROR";

/** Retry info from the backend's idempotent start */
export type RetryInfo = {
  attempt: number;
  max_attempts: number;
  next_retry_at: number | null;
  backoff_delays: number[];
};

/** Response from `GET /flagship/status`. */
export type FlagshipStatusResponse = {
  run_id: string | null;
  phase: "IDLE" | "RUNNING" | "COMPLETE" | "ERROR";
  correlation_id: string | null;
  error?: string;
  timeline?: { stage: string; detail?: string; at: string }[];
  /** Server state from idempotent start contract (NOT_STARTED, STARTING, RUNNING, ERROR) */
  status?: ServerState;
  /** Retry info when backend is retrying start */
  retry_info?: RetryInfo;
};

/** An event from `GET /agent/events`. */
export type AgentEvent = {
  id: string;
  ts: string;
  stage: string;
  status: string;
  correlation_id: string;
  summary?: string;
  decision?: string;
  sku?: string;
  shelf_id?: string;
  slot_id?: string;
  simulation_id?: string;
};

/** Response from `GET /agent/events`. */
export type AgentEventsResponse = {
  events: AgentEvent[];
  cursor: string | null;
};

/**
 * One row of `GET /flagship/status`. Mirrors `FlagshipStatus` on apps/api.
 * `timeline` rows are loose dictionaries (`stage`, `detail`, etc.); the UI
 * just renders them, no schema is enforced on the wire beyond the common
 * keys the panel reads.
 */
export type FlagshipStatus = {
  run_id: string | null;
  phase: "IDLE" | "RUNNING" | "COMPLETE" | "ERROR" | string;
  seed: number;
  started_at: string | null;
  completed_at: string | null;
  correlation_id: string | null;
  context_version: string | null;
  guard_verdict: "ALLOW" | "REFRESH_REQUIRED" | "DENY" | "HUMAN_REVIEW" | string | null;
  guard_reason_code: string | null;
  committed_decision_id: string | null;
  replan_refresh_count: number;
  replan_reason_code: string | null;
  verification_status: "VERIFIED" | "FAILED" | string | null;
  verification_reason_code: string | null;
  timeline: Array<{ stage: string; detail?: string; status?: string; duration_ms?: number }>;
  error: string | null;
  /** Server state from idempotent start contract (NOT_STARTED, STARTING, RUNNING, ERROR) */
  status?: "NOT_STARTED" | "STARTING" | "RUNNING" | "ERROR";
  /** Retry info when backend is retrying start */
  retry_info?: {
    attempt: number;
    max_attempts: number;
    next_retry_at: number | null;
    backoff_delays: number[];
  };
};

export type RetailTwinClient = {
  health: () => Promise<HealthResponse>;
  store: () => Promise<StoreResponse>;
  inventory: (sku: string) => Promise<ProductInventory>;
  /** `GET /revenue?period=`. TODO(BE): not served by apps/api yet. */
  revenue: (period: RevenuePeriod) => Promise<RevenueSummary>;
  /** `GET /promotions`. TODO(BE): not served by apps/api yet. */
  promotions: () => Promise<PromotionsSummary>;
  /** `GET /simulations?status=open`. TODO(BE): not served by apps/api yet (#26). */
  simulations: () => Promise<SimulationsResponse>;
  /** `GET /simulations/{simulation_id}`. TODO(BE): not served by apps/api yet (#26). */
  simulation: (simulationId: string) => Promise<Simulation>;
  /** `GET /simulations/{simulation_id}/candidates`. */
  candidates: (simulationId: string) => Promise<CandidatesResponse>;
  /**
   * `POST /simulations/{simulation_id}/approve|reject`. The only write the web app makes:
   * it asks, and the guard and the Executor decide. TODO(BE): not served by apps/api yet.
   */
  reviewSimulation: (simulationId: string, decision: ReviewDecision, request: ReviewRequest) => Promise<ReviewResult>;
  /** `GET /flagship/status`. Latest DCG verdict from the flagship controller singleton. */
  flagshipStatus: () => Promise<FlagshipStatus>;
  /** `POST /flagship/reset`. Reseeds the Live Twin to the canonical fixture. */
  flagshipReset: () => Promise<{ phase: string; context_version: string }>;
  /** `POST /flagship/start`. Drives the 8-stage chain end-to-end on the canonical surge event. */
  flagshipStart: () => Promise<unknown>;
  /** `GET /agent/events`. Paginated activity feed. */
  agentEvents: (since?: string | null) => Promise<AgentEventsResponse>;
  /** `GET /anomalies`. */
  anomalies: () => Promise<AnomaliesResponse>;
  /** `GET /stockout-risk`. Returns risk scores for all slots. */
  stockoutRisk: () => Promise<unknown>;
  /** `GET /checkouts`. */
  checkouts: (checkoutId?: string) => Promise<CheckoutResponse>;
};
