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

/** Response from `GET /flagship/status`. */
export type FlagshipStatusResponse = {
  run_id: string | null;
  phase: "IDLE" | "RUNNING" | "COMPLETE" | "ERROR";
  correlation_id: string | null;
  error?: string;
  timeline?: { stage: string; detail?: string; at: string }[];
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
  checkout: (checkoutId: string) => Promise<CheckoutResponse>;
  /** `GET /flagship/status` - Get the current flagship run status. */
  flagshipStatus: () => Promise<FlagshipStatusResponse>;
  /** `POST /flagship/reset` - Reset the flagship run. */
  flagshipReset: () => Promise<{ run_id: string }>;
  /** `POST /flagship/start` - Start a new flagship run with the given correlation_id. */
  flagshipStart: (correlationId: string) => Promise<{ run_id: string; correlation_id: string; phase: string }>;
  /** `GET /agent/events` - Get agent events, optionally filtered by cursor. */
  agentEvents: (since?: string | null) => Promise<AgentEventsResponse>;
};
