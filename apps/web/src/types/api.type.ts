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

/** Server state of the flagship controller's idempotent start, apart from the run's phase. */
export type ServerState = "NOT_STARTED" | "STARTING" | "RUNNING" | "ERROR";

/** Retry info while the backend retries a start. */
export type RetryInfo = {
  attempt: number;
  max_attempts: number;
  next_retry_at: number | null;
  backoff_delays: number[];
};

/**
 * Response from `GET /flagship/status`. Mirrors `FlagshipStatus` on apps/api
 * (`retailtwin_api/flagship/controller.py`). `timeline` rows are loose dictionaries
 * (`stage`, `detail`, etc.); the UI only renders the common keys.
 */
export type FlagshipStatusResponse = {
  run_id: string | null;
  phase: "IDLE" | "RUNNING" | "COMPLETE" | "ERROR";
  seed?: number;
  started_at?: string | null;
  completed_at?: string | null;
  correlation_id: string | null;
  context_version?: string | null;
  guard_verdict?: "ALLOW" | "REFRESH_REQUIRED" | "DENY" | "HUMAN_REVIEW" | string | null;
  guard_reason_code?: string | null;
  committed_decision_id?: string | null;
  replan_refresh_count?: number;
  replan_reason_code?: string | null;
  verification_status?: "VERIFIED" | "FAILED" | string | null;
  verification_reason_code?: string | null;
  error?: string | null;
  /** The controller's steps; a row may carry no `at` (`timelineEntries` stamps it then). */
  timeline?: { stage: string; detail?: string; at?: string; status?: string; duration_ms?: number }[];
  /** Server state from the idempotent start contract. */
  status?: ServerState;
  /** Retry info while the backend retries the start. */
  retry_info?: RetryInfo;
};

/** The `GET /flagship/status` snapshot the Agent Activity panel shows. */
export type FlagshipStatus = FlagshipStatusResponse;

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
  /** `GET /anomalies`. Returns open anomalies for the store. */
  anomalies: () => Promise<AnomaliesResponse>;
  /** `GET /checkouts/{checkout_id}`. Returns checkout summary and transactions. */
  checkouts: (checkoutId: string) => Promise<CheckoutResponse>;
  /** `GET /stockout-risk`. TODO(BE): apps/api serves no such route yet, and nothing reads it until it does. */
  stockoutRisk: () => Promise<unknown>;
  /** `GET /flagship/status` - Get the current flagship run status. */
  flagshipStatus: () => Promise<FlagshipStatusResponse>;
  /** `POST /flagship/reset` - Reset the flagship run. */
  flagshipReset: () => Promise<{ run_id: string }>;
  /** `POST /flagship/start` - Start a new flagship run with the given correlation_id. */
  flagshipStart: (correlationId: string) => Promise<{ run_id: string; correlation_id: string; phase: string }>;
  /** `GET /agent/events` - Get agent events, optionally filtered by cursor. */
  agentEvents: (since?: string | null) => Promise<AgentEventsResponse>;
};
